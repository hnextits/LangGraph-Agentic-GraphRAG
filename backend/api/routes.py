from fastapi import APIRouter, HTTPException, File, UploadFile, BackgroundTasks, Request, Body, Query
from typing import List, Dict, Any, Optional, Set
import os
import json
import shutil
from pydantic import BaseModel, field_validator
import logging
import traceback
import uuid
import threading
import re
import subprocess
import sys
import time  # 이미 임포트됨
from pathlib import Path
from datetime import datetime
import asyncio

# --- 필요한 모듈 임포트 (프로젝트 구조에 맞게 설정) ---
from api.pause_api import is_cancelled, cancel_task
from services.rag_service import run_rag_in_background
from skill.search.pipeline import search_google as perform_search
from skill.search.util import sanitize_filename as search_sanitize_filename, crawling_web

# --- 로거 설정 (먼저 설정) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _resolve_sources_to_document_uuids(raw_sources: Optional[List[str]]) -> List[str]:
    """사용자 입력 소스를 document_uuid 목록으로 변환합니다."""
    logger.info("채팅 요청 소스(raw): %s", raw_sources)

    if not raw_sources:
        return []

    uuid_list: List[str] = []
    filenames: List[str] = []

    for item in raw_sources:
        if not item:
            continue
        if UUID_PATTERN.match(item):
            uuid_list.append(item)
        else:
            filenames.append(item)

    if filenames:
        try:
            from notebooklm.config import RAGConfig
            from notebooklm.weaviate_utils import get_document_uuid_map

            config = RAGConfig()
            client = config.get_weaviate_client()
            if client:
                try:
                    uuid_map = get_document_uuid_map(client, filenames)
                    for filename in filenames:
                        resolved = uuid_map.get(filename)
                        if resolved:
                            uuid_list.append(resolved)
                        else:
                            logger.warning("'%s' 파일에 대한 document_uuid를 찾을 수 없습니다.", filename)
                finally:
                    client.close()
            else:
                logger.warning("Weaviate 클라이언트를 초기화할 수 없어 파일명을 UUID로 변환하지 못했습니다.")
        except Exception as exc:
            logger.warning("파일명을 document_uuid로 변환하는 중 오류 발생: %s", exc)

    # 중복 제거 및 순서 보존
    seen: Set[str] = set()
    unique_uuids: List[str] = []
    for value in uuid_list:
        if value and value not in seen:
            seen.add(value)
            unique_uuids.append(value)

    logger.info("채팅 요청 소스 변환 후(UUID): %s", unique_uuids)
    return unique_uuids

# 검색/크롤링 파이프라인에서 사용하는 공용 파일명 정규화
sanitize_filename = search_sanitize_filename

# summarizer 모듈 임포트 (요약 기능에 필요)
try:
    from skill.search.summarizer import AnswerGenerator
    logger.info("AnswerGenerator 모듈 임포트 성공 (skill.search.summarizer)")
except ImportError as e:
    logger.error(f"AnswerGenerator 모듈 임포트 실패: {e}")
    AnswerGenerator = None

# 요약 생성기 인스턴스 (싱글톤으로 관리) - LazyModelManager 사용으로 전환 중
answer_generator = None

def get_answer_generator(request: Request):
    """LazyModelManager를 통해 AnswerGenerator 인스턴스를 가져옵니다."""
    model_manager = request.app.state.model_manager
    return model_manager.acquire("answer_generator")


def sanitize_summary_filename(value: str) -> str:
    """요약 파일 저장용 간단한 파일명 정규화"""
    sanitized = re.sub(r"[^\w\-_\. ]", "_", value.strip())
    return sanitized or "summary"

# 백엔드 디렉토리 설정
backend_dir = Path(__file__).resolve().parent.parent

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

# --- 작업 상태 관리 ---
# 작업 상태는 main.py의 app.state를 통해 중앙에서 관리됩니다.

# 캐시 유효 시간 (1시간)
TASK_CACHE_TTL = 60 * 60

# --- 작업 상태 저장소 ---
# 작업 상태는 main.py의 app.state를 통해 중앙에서 관리됩니다.
# 아래 변수들은 하위 호환성을 위해 유지되지만, API 핸들러에서는 request.app.state를 사용해야 합니다.
tasks: Dict[str, Dict[str, Any]] = {}
task_status: Dict[str, Dict[str, Any]] = {}
task_cache: Dict[str, Dict[str, Any]] = {}
task_cache_timestamps: Dict[str, float] = {}

def cleanup_task_cache(request: Request):
    """오래된 작업 상태 캐시 정리"""
    current_time = time.time()
    expired_tasks = []
    task_cache_timestamps = request.app.state.task_cache_timestamps
    task_cache = request.app.state.task_cache

    for task_id, timestamp in list(task_cache_timestamps.items()):
        if current_time - timestamp > TASK_CACHE_TTL:
            expired_tasks.append(task_id)
    
    for task_id in expired_tasks:
        if task_id in task_cache:
            del task_cache[task_id]
        if task_id in task_cache_timestamps:
            del task_cache_timestamps[task_id]
    
    if expired_tasks:
        logger.info(f"오래된 작업 상태 {len(expired_tasks)}개 정리됨")


# --- Pydantic 모델 정의 ---
class RootResponse(BaseModel): message: str
class SearchQuery(BaseModel): query: str
class SearchResponse(BaseModel): results: List[Dict[str, Any]]
class AddDocumentRequest(BaseModel): title: str; link: str
class TaskCreationResponse(BaseModel): task_id: str; status: str
class FileTaskInfo(BaseModel):
    filename: str
    task_id: str

class UploadResponse(BaseModel):
    task_id: str
    message: str
    files: List[FileTaskInfo]
class FileListResponse(BaseModel):
    files: List[str]
    document_uuid_map: Optional[Dict[str, str]] = None
class FileContentResponse(BaseModel): filename: str; content: str
class DeleteResponse(BaseModel): message: str; filename: str; deleted: Optional[bool] = None
class DeleteFilesRequest(BaseModel):
    filenames: List[str]
    document_uuid_map: Optional[Dict[str, str]] = None
class DeleteFilesResponse(BaseModel): message: str; deleted_files: List[str]; failed_files: List[Dict[str, str]]
class ChatQuery(BaseModel): query: str; sources: List[str] = []
class ChatResponse(BaseModel):
    task_id: str
    message: str
class SummarizeRequest(BaseModel): filenames: List[str]
class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    message: Optional[str] = None
    progress: Optional[int] = None
    result: Optional[Any] = None
    error: Optional[str] = None
class SummarizeResponse(BaseModel):
    summary: str
    files: List[str]
    timestamp: str


# --- 경로 설정 및 세션 도우미 ---
def get_session_paths(request: Request):
    """요청의 세션 ID를 바탕으로 동적 경로를 반환합니다."""
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    session_id = getattr(request.state, "session_id", "default_session")
    
    return {
        "doc_dir": config.get_session_doc_dir(session_id),
        "metadata_file": config.get_session_metadata_file(session_id),
        "ocr_results_dir": config.get_session_results_dir(session_id, "4.OCR_results"),
        "summarize_dir": config.get_session_results_dir(session_id, "6.summarize"),
        "stt_text_dir": config.get_session_results_dir(session_id, "7.stt"),
    }

# 기존 상수 제거 또는 함수로 대체 (하위 호환성을 위해 유지하되 내부 로직에서는 get_session_paths 사용 권장)
BASE_DIR = Path(__file__).resolve().parent.parent
NEXTITS_DATA_DIR = BASE_DIR / "nextits_data"
    
# --- 유틸리티 함수 ---
def check_and_handle_pause(task_id: str) -> bool:
    """작업 취소 상태를 확인하고 처리합니다."""
    if is_cancelled(task_id):
        if tasks.get(task_id, {}).get('status') != 'cancelled':
            tasks[task_id].update({
                'status': 'cancelled',
            })
            logger.info(f"[Task {task_id}] 작업이 취소 상태로 변경되었습니다.")
        return True
    return False

def check_and_handle_pause(task_id: str) -> bool:
    """
    취소 상태를 확인하고 처리합니다.
    
    Args:
        task_id (str): 작업 ID
        task_id: 작업 ID
        
    Returns:
        bool: 작업이 취소되었으면 True, 계속 진행해야 하면 False
    """
    # 취소 상태 확인
    if is_cancelled(task_id):
        if tasks.get(task_id, {}).get('status') != 'cancelled':
            tasks[task_id]['status'] = 'cancelled'
            tasks[task_id]['message'] = '작업이 취소되었습니다.'
            logger.info(f"[Task {task_id}] 작업이 취소되었습니다.")
        return True
    
    return False

def run_text_indexing(task_id: str, file_names: List[str], session_id: Optional[str] = None):
    """텍스트 인덱싱 실행 함수 - 세션별 OCR 결과 디렉토리에서 검색"""
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    
    if session_id:
        ocr_results_dir = config.get_session_results_dir(session_id, "4.OCR_results")
    else:
        ocr_results_dir = config.DATA_ROOT / "Results" / "4.OCR_results"

    logger.info(f"[{task_id}] 텍스트 인덱싱 시작 (session: {session_id}): {file_names}")
    tasks[task_id].update({
        'status': 'indexing',
        'message': '데이터 인덱싱 준비 중...',
        'progress': 75
    })

    try:
        if check_and_handle_pause(task_id): return
        
        # 1. 파일 찾기 및 처리
        processed_files = []
        for file_name in file_names:
            base_name = Path(file_name).stem
            candidate_names = [file_name, f"{base_name}.md", f"{base_name}.txt"]
            
            for name in candidate_names:
                p = ocr_results_dir / name
                if p.exists():
                    processed_files.append(str(p))
                    break
        
        if not processed_files:
            logger.warning(f"[{task_id}] 인덱싱할 처리된 파일을 찾지 못했습니다.")
            tasks[task_id].update({'status': 'index_skipped', 'message': '인덱싱할 파일을 찾지 못해 건너뜁니다.', 'progress': 100})
            return

        # 2. qwen3_late_chunking 실행
        from notebooklm.qwen3_late_chunking import process_markdown_files
        from shared_embedding import shared_embedding
        
        # 모델 로드 보장
        if shared_embedding._model is None:
            logger.info(f"[{task_id}] Embedding 모델 로드 시작...")
            shared_embedding.load_model()
        
        # Weaviate 클라이언트 획득
        client = config.get_weaviate_client()
        if not client:
            raise RuntimeError("Weaviate 클라이언트를 초기화할 수 없습니다.")
        
        try:
            # late chunking 프로세스 실행 (session_id 전달)
            process_markdown_files(client, processed_files, session_id=session_id)
            
            tasks[task_id].update({
                'status': 'index_completed',
                'message': '파일 처리 및 인덱싱 완료',
                'progress': 100
            })
            logger.info(f"[{task_id}] 텍스트 인덱싱 성공")
        finally:
            client.close()
    except Exception as e:
        logger.error(f"[{task_id}] 텍스트 인덱싱 실패: {e}", exc_info=True)
        tasks[task_id].update({'status': 'index_failed', 'error': str(e), 'progress': 100})

async def run_text_indexing(task_id: str, file_names: List[str], session_id: Optional[str] = None):
    """텍스트 인덱싱 파이프라인 (Vector Store 저장)"""
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    
    if session_id:
        ocr_results_dir = config.get_session_results_dir(session_id, "4.OCR_results")
    else:
        ocr_results_dir = config.DATA_ROOT / "Results" / "4.OCR_results"

    logger.info(f"[{task_id}] 텍스트 인덱싱 시작 (session: {session_id}): {file_names}")
    tasks[task_id].update({
        'status': 'indexing',
        'message': '데이터 인덱싱 준비 중...',
        'progress': 75
    })

    try:
        if await asyncio.to_thread(check_and_handle_pause, task_id): return
        
        # 1. 파일 찾기 및 처리
        processed_files = []
        for file_name in file_names:
            base_name = Path(file_name).stem
            candidate_names = [file_name, f"{base_name}.md", f"{base_name}.txt"]
            
            for name in candidate_names:
                p = ocr_results_dir / name
                if p.exists():
                    processed_files.append(str(p))
                    break
        
        if not processed_files:
            logger.warning(f"[{task_id}] 인덱싱할 처리된 파일을 찾지 못했습니다.")
            tasks[task_id].update({'status': 'index_skipped', 'message': '인덱싱할 파일을 찾지 못해 건너뜁니다.', 'progress': 100})
            return

        # 메타데이터 업데이트 실행
        try:
            from nextits_data.pipe.main_pipe.UDP_File_meta import main as update_meta
            # session_id가 있으면 세션 doc_dir 전달, 없으면 기본값
            if session_id:
                doc_dir = config.get_session_doc_dir(session_id)
                await asyncio.to_thread(update_meta, target_dir=str(doc_dir))
            else:
                await asyncio.to_thread(update_meta)
            logger.info(f"[{task_id}] file_metadata.json 업데이트 완료.")
        except Exception as meta_err:
            logger.error(f"[{task_id}] 메타데이터 업데이트 중 오류 발생: {meta_err}")

        # 2. qwen3_late_chunking 실행
        from notebooklm.qwen3_late_chunking import process_markdown_files
        from shared_embedding import shared_embedding
        
        # 모델 로드 보장
        if shared_embedding._model is None:
            logger.info(f"[{task_id}] Embedding 모델 로드 시작...")
            await asyncio.to_thread(shared_embedding.load_model)
        
        # Weaviate 클라이언트 획득
        client = config.get_weaviate_client()
        if not client:
            raise RuntimeError("Weaviate 클라이언트를 초기화할 수 없습니다.")
        
        try:
            # late chunking 프로세스 실행 (session_id 전달)
            await asyncio.to_thread(process_markdown_files, client, processed_files, session_id=session_id)
            
            tasks[task_id].update({
                'status': 'index_completed',
                'message': '파일 처리 및 인덱싱 완료',
                'progress': 100
            })
            logger.info(f"[{task_id}] 텍스트 인덱싱 성공")
        finally:
            client.close()
    except Exception as e:
        logger.error(f"[{task_id}] 텍스트 인덱싱 실패: {e}", exc_info=True)
        tasks[task_id].update({'status': 'index_failed', 'error': str(e), 'progress': 100})

async def run_processing_pipeline(task_id: str, file_names: List[str], session_id: Optional[str] = None):
    """(업로드된 파일) 처리 및 인덱싱 파이프라인 (GPU 작업 큐 사용)"""
    from notebooklm.config import RAGConfig
    from utils.task_queue import gpu_task_queue
    config = RAGConfig()
    
    if session_id:
        doc_dir = config.get_session_doc_dir(session_id)
    else:
        doc_dir = config.DEFAULT_DOC_DIR

    logger.info(f"[{task_id}] 파일 처리 파이프라인 큐 등록 (session: {session_id}): {file_names}")
    tasks[task_id].update({'status': 'queued', 'message': '대기열에 등록되었습니다. GPU 리소스 확보 중...', 'progress': 5})

    try:
        script_path = NEXTITS_DATA_DIR / "pipe" / "run_file_processor.py"
        if not script_path.exists():
            raise FileNotFoundError(f"처리 스크립트를 찾을 수 없습니다: {script_path}")

        for file_name in file_names:
            file_path = doc_dir / file_name
            command = [sys.executable, str(script_path), "--file", str(file_path)]
            if session_id:
                command.extend(["--session_id", session_id])
            
            # 큐에 작업 등록
            await gpu_task_queue.add_task({
                "task_id": task_id,
                "session_id": session_id,
                "command": command
            })

        # 큐 상태 추적 루프
        while True:
            status_info = gpu_task_queue.get_queue_status(task_id)
            if status_info["status"] == "processing":
                tasks[task_id].update({
                    'status': 'processing', 
                    'message': status_info["message"],
                    'progress': 20
                })
            elif status_info["status"] == "pending":
                tasks[task_id].update({
                    'status': 'queued', 
                    'message': status_info["message"],
                    'progress': 5
                })
            elif status_info["status"] == "completed":
                break
            elif status_info["status"] == "failed":
                raise RuntimeError(status_info.get("error", "알 수 없는 작업 오류"))
            
            await asyncio.sleep(2)

        # 인덱싱 단계 진행
        await run_text_indexing(task_id, file_names, session_id)

    except Exception as e:
        logger.error(f"[{task_id}] 파일 처리 파이프라인 실패: {e}", exc_info=True)
        tasks[task_id].update({'status': 'failed', 'error': str(e), 'progress': 100})


async def process_summarize_files(task_id: str, filenames: List[str], model_manager: Any, session_id: Optional[str] = None):
    """지정된 파일들을 찾아 내용을 요약하는 백그라운드 함수 (LazyModelManager 사용)"""
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    
    if session_id:
        ocr_results_dir = config.get_session_results_dir(session_id, "4.OCR_results")
        summarize_dir = config.get_session_results_dir(session_id, "6.summarize")
    else:
        # 하위 호환성 (상수 사용 가능 시)
        ocr_results_dir = config.DATA_ROOT / "Results" / "4.OCR_results"
        summarize_dir = config.DATA_ROOT / "Results" / "6.summarize"

    logger.info(f"[{task_id}] 파일 요약 작업 시작 (session: {session_id}): {filenames}")
    tasks[task_id].update({"status": "running", "message": "요약할 파일을 찾는 중...", "progress": 10})
    
    try:
        summaries, sources = [], []
        
        # AnswerGenerator 획득
        try:
            generator = model_manager.acquire("answer_generator")
            # 모델이 실제 엔진을 로드하도록 보장
            if hasattr(generator, "load_model"):
                if not generator.model_loaded:
                    generator.load_model()
        except Exception as e:
            logger.error(f"[{task_id}] 요약 모델 획득 실패: {e}")
            tasks[task_id].update({"status": "failed", "error": f"요약 모델 로드 실패: {e}"})
            return

        try:
            for i, filename in enumerate(filenames):
                if await asyncio.to_thread(check_and_handle_pause, task_id): return
                
                progress = 10 + int((i / len(filenames)) * 80)
                tasks[task_id].update({"message": f"파일 처리 중... ({i+1}/{len(filenames)}): {filename}", "progress": progress})

                # 4.OCR_results에서만 파일 검색
                base_name = Path(filename).stem
                candidate_names = [filename, f"{base_name}.md"]
                
                file_to_summarize = None
                for name in candidate_names:
                    file_path = ocr_results_dir / name
                    if file_path.exists():
                        file_to_summarize = file_path
                        break
                
                if file_to_summarize is None:
                    logger.warning(f"[{task_id}] 4.OCR_results에서 파일을 찾을 수 없습니다: {filename}")
                    continue

                try:
                    # 파일 내용 읽기
                    with open(file_to_summarize, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if not content or content.isspace():
                        logger.warning(f"[{task_id}] 파일에 요약할 텍스트가 없습니다: {filename}")
                        continue
                        
                    # 요약 생성
                    summary = generator.generate_answer(content)
                    
                    if summary and summary != "(관련된 구글 검색 결과를 찾을 수 없습니다)":
                        summaries.append(summary)
                        sources.append({"filename": filename, "path": str(file_to_summarize)})
                except Exception as e:
                    logger.warning(f"[{task_id}] 파일 요약 중 오류 ({filename}): {e}")
        finally:
            model_manager.release("answer_generator")

        if not summaries:
            tasks[task_id].update({"status": "completed", "message": "요약할 내용이 있는 파일을 찾지 못했습니다.", "progress": 100, "result": {"summary": "요약할 내용이 없습니다.", "sources": []}})
            return

        final_summary = "\n\n---\n\n".join(summaries)
        # 여러 파일 요약 시 파일명을 명확히 함
        safe_filenames_str = sanitize_summary_filename("_".join(filenames))
        result_file = summarize_dir / f"summary_{safe_filenames_str}.md"
        result_file.write_text(final_summary, encoding="utf-8")
        
        tasks[task_id].update({
            "status": "completed", "message": "요약이 완료되었습니다.", "progress": 100,
            "result": {"summary": final_summary, "sources": sources, "result_file": str(result_file)}
        })
        logger.info(f"[{task_id}] 파일 요약 작업 완료. 파일: {result_file}")

    except Exception as e:
        logger.error(f"[{task_id}] 파일 요약 파이프라인 실패: {e}", exc_info=True)
        tasks[task_id].update({"status": "failed", "message": f"오류 발생: {e}", "progress": 100, "error": str(e)})

@router.post("/summarize", response_model=TaskCreationResponse)
async def summarize_files(request_data: SummarizeRequest, background_tasks: BackgroundTasks, request: Request) -> TaskCreationResponse:
    """선택된 파일들을 요약하는 API (백그라운드 처리)"""
    file_names = request_data.filenames
    logger.info(f"요약 요청 받음: {file_names}")
    
    task_id = str(uuid.uuid4())
    tasks[task_id] = {"task_id": task_id, "status": "pending", "message": "요약 작업이 대기 중입니다."}
    
    model_manager = getattr(request.app.state, "model_manager", None)
    session_id = getattr(request.state, "session_id", "default_session")
    
    background_tasks.add_task(
        process_summarize_files, 
        task_id, 
        file_names, 
        model_manager, 
        session_id=session_id
    )
    
    return {"task_id": task_id, "status": "pending"}


@router.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(request: Request, query: ChatQuery, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    cancellation_event = threading.Event()
    request.app.state.running_tasks[task_id] = cancellation_event
    logger.info(f"[Task {task_id}] 채팅 작업 시작: '{query.query}'")
    logger.info("[Task %s] 요청으로 전달된 sources(raw): %s", task_id, query.sources)

    model_manager = getattr(request.app.state, "model_manager", None)
    if model_manager is None:
        raise HTTPException(status_code=503, detail="모델 매니저를 초기화하지 못했습니다.")

    # app.state의 tasks 딕셔너리에 작업 상태 초기화
    tasks = request.app.state.tasks
    tasks[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "message": "채팅 작업이 대기 중입니다."
    }

    # 백그라운드에서 RAG 파이프라인 실행
    resolved_sources = _resolve_sources_to_document_uuids(query.sources)
    logger.info("[Task %s] 변환된 document_uuid 목록: %s", task_id, resolved_sources)
    source_filter_requested = bool(query.sources)

    try:
        rag_pipeline = model_manager.acquire("rag_pipeline")
        # SGLang 엔진 로드 확인 (추가)
        if hasattr(rag_pipeline, "load_engine"):
            await rag_pipeline.load_engine()

        background_tasks.add_task(
            run_rag_in_background,
            task_id=task_id,
            query=query.query,
            sources=resolved_sources,
            source_filter_requested=source_filter_requested,
            rag_pipeline=rag_pipeline,
            cancellation_event=cancellation_event,
            tasks_dict=tasks,  # app.state.tasks를 전달
            running_tasks_dict=request.app.state.running_tasks, # app.state.running_tasks를 전달
            app_state=request.app.state  # app.state 전체를 전달
        )
    finally:
        # 주의: 백그라운드 작업이 끝난 후 release해야 하므로 
        # run_rag_in_background 내부에서 release하거나 별도 스케줄링 필요
        async def schedule_rag_task():
            # run_rag_in_background 완료를 기다리는 로직이 필요할 수 있음
            # 현재는 단순 큐 등록이므로 release 시점 조정 필요
            # pass 
            model_manager.release("rag_pipeline")

        background_tasks.add_task(schedule_rag_task)

    return ChatResponse(task_id=task_id, message="채팅 작업이 시작되었습니다.")

    for task_id in task_ids:
        if task_id in running_tasks:
            try:
                running_tasks[task_id].set() # 취소 신호 보내기
                logger.info(f"[{task_id}] 작업 취소 요청됨.")
                cancelled_count += 1
            except Exception as e:
                logger.error(f"[{task_id}] 작업 취소 요청 중 오류: {e}", exc_info=True)
        else:
            logger.warning(f"취소 요청된 작업 ID를 찾을 수 없음: {task_id}")

    return {"message": f"총 {len(task_ids)}개 중 {cancelled_count}개 작업에 대한 취소 요청이 전달되었습니다."}
