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
class UploadResponse(BaseModel): message: str; files: List[Dict[str, Any]]
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
class TaskStatusResponse(BaseModel): task_id: str; status: str; message: Optional[str] = None; progress: Optional[int] = None; result: Optional[Any] = None; error: Optional[str] = None
class SummarizeResponse(BaseModel):
    summary: str
    files: List[str]
    timestamp: str


# --- 경로 설정 ---
BASE_DIR = Path(__file__).resolve().parent.parent
NEXTITS_DATA_DIR = BASE_DIR / "nextits_data"
DOC_DIR = NEXTITS_DATA_DIR / "doc"
DOC_METADATA_FILE = DOC_DIR / "metadata" / "file_metadata.json"
OCR_RESULTS_DIR = NEXTITS_DATA_DIR / "Results" / "4.OCR_results"
STT_TEXT_DIR = NEXTITS_DATA_DIR / "Results" / "7.stt"
SUMMARIZE_DIR = NEXTITS_DATA_DIR / "Results" / "6.summarize"

# --- 디렉터리 생성 ---
for dir_path in [
    DOC_DIR,
    DOC_DIR / "metadata",
    OCR_RESULTS_DIR,
    SUMMARIZE_DIR,
    STT_TEXT_DIR,
]:
    dir_path.mkdir(parents=True, exist_ok=True)
    
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

def run_text_indexing(task_id: str, file_path: str):
    """텍스트 인덱싱 실행 함수 - 4.OCR_results에서만 검색"""
    logger.info(f"[{task_id}] 텍스트 인덱싱 시작: {file_path}")
    tasks[task_id].update({
        'status': 'indexing',
        'message': '[분석 중] 데이터 임베딩 및 인덱싱 중...',
        'progress': max(tasks[task_id].get('progress', 0), 70)
    })
    try:
        if check_and_handle_pause(task_id): return
        base_name = Path(file_path).stem
        
        # 4.OCR_results에서만 검색
        md_file_path = OCR_RESULTS_DIR / f"{base_name}.md"

        if not md_file_path.exists():
            raise FileNotFoundError(
                f"4.OCR_results에서 파일을 찾을 수 없습니다: {md_file_path}"
            )

        original_cwd, original_sys_path, original_argv = os.getcwd(), list(sys.path), sys.argv
        try:
            notebooklm_path = str(BASE_DIR)
            sys.path.insert(0, notebooklm_path)
            os.chdir(notebooklm_path)

            from notebooklm.qwen3_late_chunking import main as chunking_main
            # API에서 호출할 때는 인자를 직접 전달
            chunking_main(input_file=str(md_file_path), recreate_schema=False, search_mode=False)
            
        finally:
            os.chdir(original_cwd)
            sys.path = original_sys_path
            sys.argv = original_argv

        tasks[task_id].update({
            'status': 'index_completed',
            'message': '파일 처리 및 인덱싱 완료',
            'progress': 100
        })
        logger.info(f"[{task_id}] 텍스트 인덱싱 성공")
    except Exception as e:
        logger.error(f"[{task_id}] 텍스트 인덱싱 실패: {e}", exc_info=True)
        tasks[task_id].update({'status': 'index_failed', 'error': str(e), 'progress': 100})

def run_processing_pipeline(task_id: str, file_path: str):
    """(업로드된 파일) 처리 및 인덱싱 파이프라인"""
    logger.info(f"[{task_id}] 파일 처리 파이프라인 시작: {file_path}")
    # 1단계: 업로드 직후 처리 대기 (이미 upload_files에서 0~5% 설정됨)
    # 2단계: 스크립트 실행 준비
    tasks[task_id].update({'status': 'processing', 'message': '파일 처리 준비 중...', 'progress': 10})

    try:
        if check_and_handle_pause(task_id): return
        script_path = NEXTITS_DATA_DIR / "pipe" / "run_file_processor.py"
        if not script_path.exists():
            raise FileNotFoundError(f"처리 스크립트를 찾을 수 없습니다: {script_path}")

        command = [sys.executable, str(script_path), "--file", file_path]
        logger.info(f"[{task_id}] run_file_processor 실행 (3단계): {' '.join(command)}")
        tasks[task_id].update({'status': 'processing', 'message': '파일 분석 스크립트 실행 (3단계)...', 'progress': 20})

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8'
        )

        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip()
            # 4단계: 스크립트 내부 진행 (로그에 따라 progress 점진적 상승 20~60)
            logger.info(f"[{task_id}] PIPELINE | {line}")
            
            # 사용자 친화적인 로그 변환
            user_friendly_msg = line
            if "Layout" in line or "감지" in line:
                user_friendly_msg = "레이아웃 감지 중..."
            elif "OCR" in line or "텍스트" in line:
                user_friendly_msg = "OCR 및 텍스트 추출 중..."
            elif "image" in line or "이미지" in line:
                user_friendly_msg = "이미지 변환 및 크롭 중..."
            elif "Embedding" in line or "임베딩" in line:
                user_friendly_msg = "데이터 임베딩 및 인덱싱 중..."
            elif "Processing" in line or "분석" in line:
                user_friendly_msg = "파일 분석 중..."

            current = tasks[task_id].get('progress', 20)
            new_progress = min(current + 2, 60) # 로그마다 2%씩 상승
            tasks[task_id].update({'progress': new_progress, 'message': f"[분석 중] {user_friendly_msg}"})

            # 취소 확인 (즉시 종료를 위해 SIGTERM 보낸 후 wait)
            if is_cancelled(task_id):
                logger.info(f"[{task_id}] 파이프라인 취소 감지됨. 프로세스 종료 시도.")
                process.terminate() # SIGTERM
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"[{task_id}] 프로세스가 5초 내에 종료되지 않아 강제 종료(Kill)합니다.")
                    process.kill() # SIGKILL
                
                tasks[task_id].update({'status': 'cancelled', 'message': '작업이 사용자에 의해 취소되었습니다.'})
                return

        return_code = process.wait()

        if return_code == 0:
            # 5단계: 스크립트 완료
            logger.info(f"[{task_id}] 스크립트 실행 성공 (5단계), 메타데이터 업데이트 및 텍스트 인덱싱 시작.")
            
            # 메타데이터 업데이트 실행
            try:
                from nextits_data.pipe.main_pipe.UDP_File_meta import main as update_meta
                update_meta()
                logger.info(f"[{task_id}] file_metadata.json 업데이트 완료.")
            except Exception as meta_err:
                logger.error(f"[{task_id}] 메타데이터 업데이트 중 오류 발생: {meta_err}")

            tasks[task_id].update({'status': 'processed', 'progress': 70, 'message': '파일 분석 완료, 인덱싱 시작 (5단계)...'})
            run_text_indexing(task_id, file_path)
        else:
            raise RuntimeError(f"스크립트 실행 실패 (exit code {return_code}).")
    except Exception as e:
        logger.error(f"[{task_id}] 파일 처리 파이프라인 실패: {e}", exc_info=True)
        tasks[task_id].update({'status': 'failed', 'error': str(e), 'progress': 100})


def build_answer_generator():
    """LazyModelManager용 AnswerGenerator 빌더."""
    if AnswerGenerator is None:
        raise RuntimeError("AnswerGenerator 모듈을 사용할 수 없습니다.")
    logger.info("Lazy builder를 통해 AnswerGenerator 인스턴스를 생성합니다.")
    return AnswerGenerator()


async def process_summarize_files(task_id: str, filenames: List[str], model_manager: Any):
    """지정된 파일들을 찾아 내용을 요약하는 백그라운드 함수 (LazyModelManager 사용)"""
    logger.info(f"[{task_id}] 파일 요약 작업 시작: {filenames}")
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
                    file_path = OCR_RESULTS_DIR / name
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
        result_file = SUMMARIZE_DIR / f"summary_{safe_filenames_str}.md"
        result_file.write_text(final_summary, encoding="utf-8")
        
        tasks[task_id].update({
            "status": "completed", "message": "요약이 완료되었습니다.", "progress": 100,
            "result": {"summary": final_summary, "sources": sources, "result_file": str(result_file)}
        })
        logger.info(f"[{task_id}] 파일 요약 작업 완료. 파일: {result_file}")

    except Exception as e:
        logger.error(f"[{task_id}] 파일 요약 파이프라인 실패: {e}", exc_info=True)
        tasks[task_id].update({"status": "failed", "message": f"오류 발생: {e}", "progress": 100, "error": str(e)})

async def process_search_and_summarize(task_id: str, query: str):
    """검색, 크롤링 기능은 제거되었습니다."""
    logger.error("검색 기반 요약 기능이 비활성화되었습니다.")
    task_status[task_id].update({
        "status": "failed",
        "message": "검색 기반 요약 기능이 제거되었습니다.",
        "progress": 100,
        "error": "Deprecated feature"
    })

# --- API 엔드포인트 구현 ---

# 작업 상태를 확인하는 API
@router.get("/tasks/{task_id}", response_model=TaskStatusResponse, tags=["Task Management"])
async def get_task_status(task_id: str, request: Request) -> TaskStatusResponse:
    # app.state에서 상태 변수들을 가져옵니다.
    tasks = request.app.state.tasks
    task_status = request.app.state.task_status
    task_cache = request.app.state.task_cache
    task_cache_timestamps = request.app.state.task_cache_timestamps

    # 오래된 캐시 정리 실행
    try:
        cleanup_task_cache(request)
    except Exception as e:
        logger.error(f"캐시 정리 중 오류 발생: {e}")
    
    try:
        # tasks, task_status, task_cache 순서로 확인
        if task_id in tasks:
            task_info = tasks[task_id]
            if task_info.get("status") in ["completed", "failed", "cancelled"]:
                task_cache[task_id] = task_info.copy()
                task_cache_timestamps[task_id] = time.time()
            return TaskStatusResponse(**task_info)

        if task_id in task_status:
            task_info = task_status[task_id]
            if task_info.get("status") in ["completed", "failed", "cancelled"]:
                task_cache[task_id] = task_info.copy()
                task_cache_timestamps[task_id] = time.time()
            return TaskStatusResponse(**task_info)

        if task_id in task_cache:
            task_cache_timestamps[task_id] = time.time()
            return TaskStatusResponse(**task_cache[task_id])
        else:
            # 로그 추가
            logger.warning(f"요청된 작업 ID가 존재하지 않음: {task_id}")
            raise HTTPException(
                status_code=404, 
                detail={
                    "message": f"작업 ID {task_id}를 찾을 수 없습니다.",
                    "error_code": "task_not_found",
                    "task_id": task_id
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"작업 상태 확인 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail={
                "message": f"작업 상태 확인 중 오류가 발생했습니다: {str(e)}",
                "error_code": "internal_server_error",
                "task_id": task_id
            }
        )

# -- 검색 및 요약 관련 API --
def run_document_pipeline(task_id: str, title: str, link: str):
    """구글 검색 결과를 문서화하고 인덱싱"""
    logger.info(f"[{task_id}] 문서 파이프라인 시작: {title}")
    tasks[task_id]['status'] = 'processing'
    tasks[task_id]['message'] = '웹 페이지 크롤링 중...'
    try:
        if check_and_handle_pause(task_id): 
            return
        file_path = crawling_web(result={'title': title, 'link': link}, output_dir=str(DOC_DIR))

        if not (isinstance(file_path, str) and os.path.exists(file_path)):
            raise ValueError(f"크롤링 실패 또는 유효하지 않은 파일 경로: {file_path}")

        tasks[task_id]['message'] = '문서 청킹 및 인덱싱 중...'
        if check_and_handle_pause(task_id): 
            return

        original_cwd, original_sys_path, original_argv = os.getcwd(), list(sys.path), sys.argv
        try:
            notebooklm_path = str(BASE_DIR)
            sys.path.insert(0, notebooklm_path)
            os.chdir(notebooklm_path)

            from notebooklm.qwen3_late_chunking import main as chunking_main
            chunking_main(input_file=file_path, recreate_schema=False, search_mode=True)
        finally:
            os.chdir(original_cwd)
            sys.path = original_sys_path
            sys.argv = original_argv

        tasks[task_id].update({
            'status': 'completed',
            'message': '문서 추가 및 인덱싱이 성공적으로 완료되었습니다.',
            'result': {'file_path': file_path}
        })
        logger.info(f"[{task_id}] 문서 처리 성공: {title}")
    except Exception as e:
        logger.error(f"[{task_id}] 문서 파이프라인 실패: {e}", exc_info=True)
        tasks[task_id].update({'status': 'failed', 'error': str(e)})


async def process_search_and_summarize(task_id: str, query: str):
    """검색, 크롤링, 요약 백그라운드 처리"""
    logger.info(f"[{task_id}] 검색 기반 요약 시작: '{query}'")
    try:
        task_status[task_id].update({"status": "running", "message": "구글 검색 중...", "progress": 10})
        if await asyncio.to_thread(check_and_handle_pause, task_id):
            return

        results = perform_search(query, 5, [])

        if not results:
            task_status[task_id].update({"status": "completed", "message": "검색 결과가 없습니다.", "progress": 100, "result": {"summary": "검색 결과가 없습니다.", "sources": []}})
            return

        unique_results = []
        seen_links = set()
        for result in results:
            link = result.get("link")
            if link and link not in seen_links:
                seen_links.add(link)
                unique_results.append(result)

        results = unique_results

        task_status[task_id].update({"status": "running", "message": "웹 페이지 크롤링 중...", "progress": 30})
        crawled_files = []
        for i, result in enumerate(results):
            if await asyncio.to_thread(check_and_handle_pause, task_id):
                return
            try:
                file_path = crawling_web(result=result, output_dir=str(SNIPPET_DIR))
                if file_path and os.path.exists(file_path):
                    crawled_files.append({"title": result.get("title"), "link": result.get("link"), "file_path": file_path})
                progress = 30 + int((i + 1) / len(results) * 40)
                task_status[task_id].update({"message": f"웹 페이지 크롤링 중... ({i+1}/{len(results)})", "progress": progress})
            except Exception as e:
                logger.warning(f"[{task_id}] 크롤링 중 일부 오류 ({result.get('link')}): {e}")

        if not crawled_files:
            task_status[task_id].update({"status": "failed", "message": "모든 페이지 크롤링 실패", "progress": 100, "error": "크롤링된 파일이 없습니다."})
            return

        task_status[task_id].update({"status": "running", "message": "내용 요약 중...", "progress": 70})
        summaries = []
        sources = []

        if AnswerGenerator is None:
            logger.error("LLM 요약 모듈을 사용할 수 없습니다")
            tasks[task_id].update({
                "status": "failed",
                "message": "LLM 요약 모듈 로드 실패",
                "progress": 100,
                "error": "AnswerGenerator를 import할 수 없습니다"
            })
            return

        logger.info("LLM 요약 모듈 사용 준비 완료")
        generator = AnswerGenerator()

        try:
            for i, file_info in enumerate(crawled_files):
                if await asyncio.to_thread(check_and_handle_pause, task_id):
                    return

                try:
                    with open(file_info["file_path"], 'r', encoding='utf-8') as f:
                        content = f.read()

                    if not content or content.isspace():
                        logger.warning(f"[{task_id}] 파일에 요약할 텍스트가 없습니다: {file_info['file_path']}")
                        continue

                    summary = generator.generate_answer(content)

                    if summary and summary != "(관련된 구글 검색 결과를 찾을 수 없습니다)":
                        summaries.append(summary)
                        sources.append({"title": file_info["title"], "link": file_info["link"]})

                    progress = 70 + int((i + 1) / len(crawled_files) * 20)
                    task_status[task_id].update({"message": f"요약 중... ({i+1}/{len(crawled_files)})", "progress": progress})

                except Exception as e:
                    logger.warning(f"[{task_id}] 요약 중 일부 오류 ({file_info['file_path']}): {e}")

            final_summary = "\n\n".join(summaries) if summaries else "요약할 내용이 없습니다."
        finally:
            if 'generator' in locals():
                generator.cleanup_model()
                logger.info(f"[{task_id}] LLM 요약 모델 메모리 정리 완료")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_query = sanitize_summary_filename(query)
        doc_file = DOC_DIR / f"search_summary_{timestamp}_{safe_query}.md"
        doc_file.write_text(final_summary, encoding='utf-8')
        logger.info(f"[{task_id}] 검색 결과를 DOC_DIR에 저장: {doc_file}")

        ocr_result_file = OCR_RESULTS_DIR / f"search_summary_{timestamp}_{safe_query}.md"
        ocr_result_file.write_text(final_summary, encoding='utf-8')
        logger.info(f"[{task_id}] 검색 결과를 OCR_RESULTS_DIR에 저장: {ocr_result_file}")

        task_status[task_id].update({
            "status": "completed", "message": "요약이 완료되었습니다.", "progress": 100,
            "result": {"summary": final_summary, "sources": sources, "result_file": str(doc_file), "ocr_result_file": str(ocr_result_file)}
        })
        logger.info(f"[{task_id}] 요약 작업 완료. DOC: {doc_file}, OCR: {ocr_result_file}")
    except Exception as e:
        logger.error(f"[{task_id}] 요약 작업 파이프라인 실패: {e}", exc_info=True)
        task_status[task_id].update({"status": "failed", "message": f"오류 발생: {e}", "progress": 100, "error": str(e)})


# 웹 검색 결과를 반환하는 API
@router.post("/search", response_model=SearchResponse, tags=["Search & Summarize"])
async def search(query: SearchQuery) -> SearchResponse:
    if perform_search is None:
        raise HTTPException(status_code=500, detail="검색 모듈을 사용할 수 없습니다.")
    try:
        results = perform_search(query.query, 10, [])
        return {"results": results or []}
    except Exception as e:
        logger.error(f"검색 중 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 요약 작업을 시작시키는 API
@router.post("/summarize", response_model=TaskCreationResponse)
async def summarize_files(request_data: SummarizeRequest, background_tasks: BackgroundTasks, request: Request) -> TaskCreationResponse:
    """선택된 파일들을 요약하는 API (백그라운드 처리)"""
    file_names = request_data.filenames
    logger.info(f"요약 요청 받음: {file_names}")
    
    task_id = str(uuid.uuid4())
    tasks[task_id] = {"status": "pending", "message": "요약 작업 대기 중...", "progress": 0}
    
    background_tasks.add_task(process_summarize_files, task_id, file_names, request.app.state.model_manager)
    
    return TaskCreationResponse(task_id=task_id, status="pending")

# === 채팅 관련 API ===
@router.post("/chat", response_model=ChatResponse, tags=["Chat"])


# 생성된 요약 파일의 목록을 조회하는 API
@router.get("/summarizes", response_model=FileListResponse, tags=["Summarize"])
async def list_summary_files() -> FileListResponse:
    files = [f.name for f in SUMMARIZE_DIR.iterdir() if f.is_file()]
    return {"files": files}

# 특정 요약 파일의 내용을 상세 조회하는 API
@router.get("/summarizes/{filename}", response_model=FileContentResponse, tags=["Search & Summarize"])
async def get_summary_detail(filename: str) -> FileContentResponse:
    file_path = SUMMARIZE_DIR / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="요약 파일을 찾을 수 없습니다.")
    content = file_path.read_text(encoding="utf-8")
    return {"filename": filename, "content": content}

# 요약 파일을 삭제하는 API
@router.delete("/summarizes", response_model=DeleteFilesResponse, tags=["Search & Summarize"])
async def delete_summary_files(req: DeleteFilesRequest) -> DeleteFilesResponse:
    deleted, failed = [], []
    for filename in req.filenames:
        file_path = SUMMARIZE_DIR / filename
        try:
            if file_path.is_file():
                file_path.unlink()
                deleted.append(filename)
            else:
                failed.append({"filename": filename, "reason": "파일을 찾을 수 없음"})
        except Exception as e:
            logger.error(f"요약 파일 삭제 오류 ('{filename}'): {e}", exc_info=True)
            failed.append({"filename": filename, "reason": str(e)})
    return {
        "message": f"요약 파일 {len(deleted)}개 삭제 성공, {len(failed)}개 실패.",
        "deleted_files": deleted,
        "failed_files": failed
    }

# -- 문서 관리 관련 API --

def _delete_document_resources(filename: str, document_uuid: Optional[str] = None) -> Dict[str, Any]:
    """원본 파일 및 연관 자원 삭제 후 결과 반환"""
    result = {
        "local_deleted": False,
        "weaviate_deleted": False,
        "error": None,
        "not_found": False,
        "weaviate_error": None,
    }

    try:
        file_path = DOC_DIR / filename

        if file_path.exists():
            try:
                os.remove(file_path)
                result["local_deleted"] = True
            except Exception as file_err:
                logger.warning("원본 파일 삭제 중 오류 발생 (%s): %s", file_path, file_err)
                result["error"] = f"원본 파일 삭제 실패: {file_err}"
        else:
            result["not_found"] = True
            logger.info("DOC_DIR에서 원본 파일을 찾지 못했습니다. Weaviate 정리만 진행합니다: %s", file_path)

        extra_paths: Set[Path] = set()

        # 1) OCR 텍스트
        extra_paths.add(DOC_DIR / f"{filename}.txt")

        # 2) Results 디렉터리 내 동일 문서 산출물
        stem_name = Path(filename).stem
        results_root = NEXTITS_DATA_DIR / "Results"
        if results_root.exists():
            for stage_dir in results_root.iterdir():
                if not stage_dir.is_dir():
                    continue

                # 2-1) stage_dir과 동일한 이름의 하위 폴더가 문서 이름인 경우
                target_dir = stage_dir / stem_name
                if target_dir.exists() and target_dir.is_dir():
                    extra_paths.add(target_dir)

                # 2-2) stage_dir 루트 바로 아래에 문서명 파일이 존재하는 경우
                root_file = stage_dir / filename
                if root_file.exists() and root_file.is_file():
                    extra_paths.add(root_file)

                # 2-3) stage_dir 내부에서 문서명으로 시작하는 파일(확장자 포함) 제거
                try:
                    for path in stage_dir.rglob("*"):
                        try:
                            if path.is_dir() and path.name == stem_name:
                                extra_paths.add(path)
                            elif path.is_file():
                                name = path.name
                                path_stem = path.stem
                                if (
                                    name == filename
                                    or path_stem == stem_name
                                    or name.startswith(f"{stem_name}.")
                                ):
                                    extra_paths.add(path)
                        except PermissionError:
                            logger.warning("결과 디렉토리 탐색 중 권한 오류: %s", path)
                            continue
                except PermissionError:
                    logger.warning("결과 디렉토리 접근 권한 없음: %s", stage_dir)
                    continue

        # 3) 메타데이터 JSON 업데이트
        extra_paths.add(DOC_METADATA_FILE)

        # 파일은 먼저, 디렉토리는 나중에 삭제
        for extra_file in sorted(extra_paths, key=lambda p: (p.is_dir(), str(p))):
            try:
                if extra_file.is_file():
                    if extra_file == DOC_METADATA_FILE:
                        # 메타데이터 파일은 삭제 대신 해당 엔트리 제거
                        try:
                            with open(DOC_METADATA_FILE, "r", encoding="utf-8") as f:
                                metadata = json.load(f)
                        except FileNotFoundError:
                            metadata = {}
                        except json.JSONDecodeError:
                            metadata = {}

                        metadata_list = metadata.get("metadata", [])
                        filtered = [entry for entry in metadata_list if entry.get("file_name") != filename]
                        if len(filtered) != len(metadata_list):
                            metadata["metadata"] = filtered
                            metadata["total_files"] = len(filtered)
                            metadata["generated_at"] = datetime.now().isoformat()
                            with open(DOC_METADATA_FILE, "w", encoding="utf-8") as f:
                                json.dump(metadata, f, ensure_ascii=False, indent=2)
                            logger.info("file_metadata.json에서 '%s' 레코드 제거 완료", filename)
                        continue
                    extra_file.unlink()
                elif extra_file.is_dir():
                    shutil.rmtree(extra_file)
            except Exception as e:
                logger.warning("추가 파일/디렉토리 삭제 중 오류 발생 (%s): %s", extra_file, e)

        try:
            from notebooklm.config import RAGConfig
            from notebooklm.weaviate_utils import delete_document, delete_document_by_filename

            config = RAGConfig()
            client = config.get_weaviate_client()

            if client:
                try:
                    if document_uuid:
                        logger.info("Weaviate 삭제 요청 (UUID 기준): filename=%s, uuid=%s", filename, document_uuid)
                        weaviate_deleted = delete_document(client, document_uuid)
                        result["weaviate_deleted"] = weaviate_deleted
                        if weaviate_deleted:
                            logger.info("Weaviate에서 문서 UUID '%s' 관련 데이터 삭제 완료", document_uuid)
                        else:
                            logger.warning("Weaviate에서 문서 UUID '%s' 관련 데이터를 찾을 수 없습니다. 파일명으로 재시도", document_uuid)
                            fallback_deleted = delete_document_by_filename(client, filename)
                            result["weaviate_deleted"] = fallback_deleted
                            if fallback_deleted:
                                logger.info("파일명 기반 Weaviate 삭제 성공: %s", filename)
                            else:
                                logger.warning("파일명 기반 Weaviate 삭제 실패: %s", filename)
                    else:
                        logger.info("Weaviate 삭제 요청 (파일명 기준): filename=%s", filename)
                        weaviate_deleted = delete_document_by_filename(client, filename)
                        result["weaviate_deleted"] = weaviate_deleted
                        if weaviate_deleted:
                            logger.info("Weaviate에서 문서 '%s' 관련 데이터 삭제 완료", filename)
                        else:
                            logger.warning("Weaviate에서 문서 '%s' 관련 데이터를 찾을 수 없습니다.", filename)
                finally:
                    client.close()
        except Exception as e:
            logger.error(f"Weaviate 데이터 삭제 오류: {str(e)}")
            result["weaviate_error"] = str(e)

        if result["weaviate_deleted"]:
            result["error"] = None

    except Exception as e:
        logger.error(f"파일 삭제 오류: {str(e)}")
        result["error"] = str(e)

    return result


# 검색 결과(URL) 기반으로 문서를 저장하고 처리하는 작업을 시작시키는 API
@router.post("/upload/docs", response_model=TaskCreationResponse, tags=["Document Management"])
def add_document_from_search(req: AddDocumentRequest, background_tasks: BackgroundTasks) -> TaskCreationResponse:
    task_id = str(uuid.uuid4())
    tasks[task_id] = {"task_id": task_id, "status": "pending", "message": "문서 추가 작업이 대기 중입니다."}
    background_tasks.add_task(run_document_pipeline, task_id, req.title, req.link)
    return {"task_id": task_id, "status": "pending"}

# 로컬 파일을 서버에 업로드하고 처리하는 작업을 시작시키는 API
@router.post("/upload/files", response_model=UploadResponse, tags=["Document Management"])
async def upload_files(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)) -> UploadResponse:
    saved_files_info = []
    for file in files:
        try:
            safe_filename = sanitize_filename(file.filename)
            file_path = DOC_DIR / safe_filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            task_id = str(uuid.uuid4())
            tasks[task_id] = {"status": "queued", "filename": safe_filename, "task_id": task_id}
            background_tasks.add_task(run_processing_pipeline, task_id, str(file_path))
            
            saved_files_info.append({
                "filename": safe_filename, "task_id": task_id,
                "size": file_path.stat().st_size, "content_type": file.content_type
            })
        except Exception as e:
            logger.error(f"'{file.filename}' 파일 업로드 오류: {e}", exc_info=True)
        finally:
            file.file.close()
    return {"message": f"{len(saved_files_info)}개 파일의 처리가 시작되었습니다.", "files": saved_files_info}

# 업로드된 원본 파일 목록을 조회하는 API
@router.get("/files", response_model=FileListResponse, tags=["Document Management"])
async def list_doc_files() -> FileListResponse:
    files = [f.name for f in DOC_DIR.iterdir() if f.is_file()]

    document_uuid_map: Dict[str, str] = {}
    file_set = set(files)

    if file_set:
        try:
            from notebooklm.config import RAGConfig
            from notebooklm.weaviate_utils import get_document_uuid_map

            config = RAGConfig()
            client = config.get_weaviate_client()

            if client:
                try:
                    uuid_map = get_document_uuid_map(client, list(file_set))
                    document_uuid_map.update(uuid_map)
                except Exception as query_error:
                    logger.warning(f"Weaviate 문서 UUID 조회 중 오류 발생: {query_error}")
                finally:
                    client.close()
        except Exception as e:
            logger.warning(f"Weaviate 클라이언트 초기화 실패: {e}")

    response: Dict[str, Any] = {"files": files}
    if document_uuid_map:
        response["document_uuid_map"] = document_uuid_map

    return response

# 원본 파일이 처리된 후의 텍스트(OCR) 내용을 조회하는 API
@router.get("/files/{filename}", response_model=FileContentResponse, tags=["Document Management"])
async def get_ocr_file_content(filename: str) -> FileContentResponse:
    """4.OCR_results 디렉토리에서만 파일을 검색합니다."""
    base_name = Path(filename).stem
    candidate_names = [filename, f"{base_name}.md"]

    logger.info(f"파일 내용 조회 요청: {filename}, base_name: {base_name}")

    # 4.OCR_results에서만 검색
    existing_path = None
    for name in candidate_names:
        file_path = OCR_RESULTS_DIR / name
        if file_path.is_file():
            existing_path = file_path
            logger.info(f"4.OCR_results에서 파일 발견: {existing_path}")
            break

    if existing_path is None:
        logger.warning(f"4.OCR_results에서 파일을 찾을 수 없음: {filename}")
        detail = f"처리된 파일을 찾을 수 없습니다: {filename}"
        raise HTTPException(status_code=404, detail=detail)

    # 여러 인코딩 시도
    encodings = ['utf-8', 'utf-8-sig', 'cp949', 'euc-kr', 'latin-1']
    content = None
    
    for encoding in encodings:
        try:
            content = existing_path.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    
    if content is None:
        # 모든 인코딩 실패 시 바이너리로 읽고 에러 무시
        content = existing_path.read_bytes().decode('utf-8', errors='ignore')
    
    return {"filename": existing_path.name, "content": content}

# 업로드된 파일을 다중 삭제하는 API
@router.delete("/files", response_model=DeleteFilesResponse, tags=["Document Management"])
async def delete_files(req: DeleteFilesRequest) -> DeleteFilesResponse:
    deleted, failed = [], []
    uuid_map = req.document_uuid_map or {}

    logger.info("파일 삭제 요청 수신: files=%s, document_uuid_map_keys=%s", req.filenames, list(uuid_map.keys()))

    for filename in req.filenames:
        document_uuid = uuid_map.get(filename)
        result = _delete_document_resources(filename, document_uuid)

        if result["local_deleted"]:
            deleted.append(filename)
            if result.get("weaviate_error"):
                logger.warning(f"Weaviate 삭제 도중 경고 (파일: {filename}): {result['weaviate_error']}")
        else:
            reason = result["error"] or (
                "파일을 찾을 수 없습니다." if result.get("not_found") else "삭제 실패"
            )
            failed.append({"filename": filename, "reason": reason, "weaviate_error": result.get("weaviate_error")})

    message = f"파일 {len(deleted)}개 삭제 성공, {len(failed)}개 실패."
    return DeleteFilesResponse(message=message, deleted_files=deleted, failed_files=failed)


# 업로드된 파일을 삭제하는 API
@router.delete("/files/{filename}", response_model=DeleteResponse, tags=["Document Management"])
async def delete_file(filename: str, document_uuid: Optional[str] = Query(default=None)) -> DeleteResponse:
    result = _delete_document_resources(filename, document_uuid)

    if result["not_found"]:
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {filename}")

    if not result["local_deleted"]:
        detail = result["error"] or f"파일 삭제 중 오류 발생: {filename}"
        raise HTTPException(status_code=500, detail=detail)

    if result.get("weaviate_error"):
        logger.warning(f"Weaviate 삭제 도중 경고 (파일: {filename}): {result['weaviate_error']}")

    return DeleteResponse(message=f"파일이 성공적으로 삭제되었습니다.", filename=filename, deleted=result["weaviate_deleted"])

# -- 기타 API --
# RAG 채팅봇에 질문하고 답변을 받는 API
@router.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(query: ChatQuery, request: Request, background_tasks: BackgroundTasks) -> ChatResponse:
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
        generator = getattr(rag_pipeline, "generator", None)
        if generator and hasattr(generator, "ensure_model_loaded"):
            generator.ensure_model_loaded()
    except Exception as exc:
        logger.error("RAG 파이프라인을 로드하지 못했습니다: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="RAG 파이프라인을 초기화하지 못했습니다.")

    # try:
    #     generator = getattr(rag_pipeline, "generator", None)
    #     ensure_loader = getattr(generator, "ensure_model_loaded", None)
    #     if callable(ensure_loader):
    #         ensure_loader()
    # except Exception as exc:
    #     logger.error("RAG 생성기 초기화 중 오류가 발생했습니다: %s", exc, exc_info=True)
    #     model_manager.release("rag_pipeline")
    #     raise HTTPException(status_code=500, detail="답변 생성기를 초기화하지 못했습니다.")

    def schedule_rag_task():
        try:
            run_rag_in_background(
                task_id=task_id,
                query=query.query,
                sources=resolved_sources,
                source_filter_requested=source_filter_requested,
                rag_pipeline=rag_pipeline,
                cancellation_event=cancellation_event,
                tasks_dict=tasks,
                running_tasks_dict=request.app.state.running_tasks,
                app_state=request.app.state,
            )
        finally:
            model_manager.release("rag_pipeline")

    background_tasks.add_task(schedule_rag_task)

    return ChatResponse(task_id=task_id, message="채팅 작업이 시작되었습니다.")

# 진행 중인 백그라운드 작업을 ID로 지정하여 취소하는 API
@router.post("/cancel", tags=["Task Management"])
async def cancel_tasks_by_id(request: Request, task_ids: List[str] = Body(..., embed=True)):
    cancelled_count = 0
    running_tasks = request.app.state.running_tasks

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
