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
router = APIRouter(tags=["RAG"])

UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _resolve_sources_to_document_uuids(raw_sources: Optional[List[str]]) -> List[str]:
    """UUID 목록만 받아서 검증하고 반환합니다."""
    logger.info("채팅 요청 소스(raw): %s", raw_sources)
    print(f"DEBUG _resolve_sources_to_document_uuids called with: {raw_sources}")

    if not raw_sources:
        print("DEBUG: raw_sources is empty or None")
        return []

    # UUID만 허용
    uuid_list: List[str] = []
    
    for i, item in enumerate(raw_sources):
        print(f"DEBUG: Processing item {i}: '{item}' (type: {type(item)}, length: {len(item) if item else 'N/A'})")
        if not item:
            print(f"DEBUG: Item {i} is empty, skipping")
            continue
            
        if UUID_PATTERN.match(item):
            print(f"DEBUG: Item {i} matches UUID pattern, adding to uuid_list")
            uuid_list.append(item)
        else:
            print(f"DEBUG: Item {i} does not match UUID pattern, rejecting")
            logger.warning("UUID 형식이 아닌 항목을 거부합니다: '%s'", item)

    # 중복 제거 및 순서 보존
    seen: Set[str] = set()
    unique_uuids: List[str] = []
    for value in uuid_list:
        if value and value not in seen:
            seen.add(value)
            unique_uuids.append(value)

    logger.info("최종 UUID 목록: %s", unique_uuids)
    print(f"DEBUG: Final unique UUIDs: {unique_uuids}")
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

def build_answer_generator():
    """LazyModelManager용 AnswerGenerator 빌더."""
    if AnswerGenerator is None:
        raise RuntimeError("AnswerGenerator 모듈을 사용할 수 없습니다.")
    logger.info("Lazy builder를 통해 AnswerGenerator 인스턴스를 생성합니다.")
    return AnswerGenerator()


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


# --- API 엔드포인트 구현 ---

@router.get("/files", response_model=FileListResponse)
async def list_files(request: Request):
    """업로드된 파일 목록 조회 (글로벌 + 세션별 병합, doc 디렉토리 기준)"""
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    paths = get_session_paths(request)
    
    # 세션 ID 추출
    session_id = getattr(request.state, "session_id", "default_session")
    logger.info(f"[/files] Session ID: {session_id}")
    
    # LeftBox에는 원본 문서(doc) 디렉토리의 파일들만 표시
    search_dirs = [
        config.DEFAULT_DOC_DIR, # 글로벌 doc
        paths["doc_dir"]        # 세션 doc
    ]
    
    # 1. 파일 목록 수집 (병합 및 중복 제거)
    all_files = set()
    for d in search_dirs:
        if d.exists():
            # .md, .txt, .pdf 파일 모두 수집하여 목록에 노출
            for f in d.iterdir():
                if f.is_file() and not f.name.startswith('.'):
                    all_files.add(f.name)
    
    files_list = sorted(list(all_files))
    
    # 2. Weaviate에서 UUID 매핑 정보 가져오기
    uuid_map = {}
    try:
        print(f"DEBUG: /files endpoint - files_list: {files_list}")
        client = config.get_weaviate_client()
        if client and files_list:
            from notebooklm.weaviate_utils import get_document_uuid_map_with_session
            print(f"DEBUG: Calling get_document_uuid_map_with_session with {len(files_list)} files")
            uuid_map = get_document_uuid_map_with_session(client, files_list, session_id)
            print(f"DEBUG: get_document_uuid_map_with_session returned: {uuid_map}")
            client.close()
        else:
            print(f"DEBUG: client is None or files_list is empty. client: {client}, files_list: {files_list}")
    except Exception as e:
        logger.warning(f"UUID 매핑 조회 실패: {e}")
        print(f"DEBUG: UUID mapping error: {e}")

    print(f"DEBUG: Final uuid_map to return: {uuid_map}")
    return FileListResponse(files=files_list, document_uuid_map=uuid_map)


@router.get("/summarizes", response_model=FileListResponse)
async def list_summarizes(request: Request):
    """생성된 요약 파일 목록 조회 (글로벌 + 세션별 병합)"""
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    paths = get_session_paths(request)
    
    session_summarize_dir = paths["summarize_dir"]
    global_summarize_dir = config.DATA_ROOT / "Results" / "6.summarize"
    
    all_files = set()
    if global_summarize_dir.exists():
        all_files.update([f.name for f in global_summarize_dir.iterdir() if f.is_file() and f.suffix == ".md"])
    if session_summarize_dir.exists():
        all_files.update([f.name for f in session_summarize_dir.iterdir() if f.is_file() and f.suffix == ".md"])
    
    return FileListResponse(files=sorted(list(all_files)))


@router.get("/summarizes/{filename}", response_model=FileContentResponse)
async def get_summarize_content(request: Request, filename: str):
    """특정 요약 파일의 내용 조회 (세션 우선 후 글로벌 검색)"""
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    paths = get_session_paths(request)
    
    # 1. 세션 디렉토리 확인
    session_file = paths["summarize_dir"] / filename
    if session_file.exists():
        file_path = session_file
    else:
        # 2. 글로벌 디렉토리 확인
        global_file = config.DATA_ROOT / "Results" / "6.summarize" / filename
        if global_file.exists():
            file_path = global_file
        else:
            raise HTTPException(status_code=404, detail="요약 파일을 찾을 수 없습니다.")
    
    try:
        content = file_path.read_text(encoding="utf-8")
        return FileContentResponse(filename=filename, content=content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 읽기 오류: {e}")


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(request: Request, task_id: str):
    """작업 상태 조회 (GPU 큐 상태 포함)"""
    # 1. 메모리 내 작업 상태 확인
    tasks_dict = request.app.state.tasks
    if task_id in tasks_dict:
        status_data = tasks_dict[task_id]
        return TaskStatusResponse(
            task_id=task_id,
            status=status_data.get("status", "unknown"),
            message=status_data.get("message"),
            progress=status_data.get("progress"),
            result=status_data.get("result"),
            error=status_data.get("error")
        )
    
    # 2. GPU 작업 큐에서 확인
    from utils.task_queue import gpu_task_queue
    queue_status = gpu_task_queue.get_queue_status(task_id)
    if queue_status["status"] != "not_found":
        return TaskStatusResponse(
            task_id=task_id,
            status=queue_status["status"],
            message=queue_status["message"],
            progress=5 if queue_status["status"] == "pending" else 20
        )
        
    raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")


@router.delete("/files", response_model=DeleteFilesResponse)
async def delete_files(request: Request, delete_req: DeleteFilesRequest):
    """파일 삭제 (세션별 격리)"""
    paths = get_session_paths(request)
    doc_dir = paths["doc_dir"]
    ocr_dir = paths["ocr_results_dir"]
    
    deleted_files = []
    failed_files = []
    
    for filename in delete_req.filenames:
        try:
            # 원본 파일 삭제
            file_path = doc_dir / filename
            if file_path.exists():
                file_path.unlink()
            
            # OCR 결과 삭제
            base_name = Path(filename).stem
            for ext in [".md", ".txt", ".json"]:
                ocr_path = ocr_dir / f"{base_name}{ext}"
                if ocr_path.exists():
                    ocr_path.unlink()
            
            deleted_files.append(filename)
        except Exception as e:
            failed_files.append({"filename": filename, "error": str(e)})
            
    return DeleteFilesResponse(
        message="파일 삭제 처리가 완료되었습니다.",
        deleted_files=deleted_files,
        failed_files=failed_files
    )


@router.post("/upload/files", response_model=UploadResponse)
async def upload_files(request: Request, background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    """파일 업로드 및 처리 시작 (세션별 격리)"""
    paths = get_session_paths(request)
    doc_dir = paths["doc_dir"]
    session_id = getattr(request.state, "session_id", "default_session")
    
    # 디렉토리 생성 보장
    doc_dir.mkdir(parents=True, exist_ok=True)
    
    task_id = str(uuid.uuid4())
    uploaded_file_names = []
    file_info_list = []
    
    for file in files:
        file_path = doc_dir / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        uploaded_file_names.append(file.filename)
        file_info_list.append(FileTaskInfo(filename=file.filename, task_id=task_id))
        
    # 백그라운드 처리 파이프라인 시작
    background_tasks.add_task(run_processing_pipeline, task_id, uploaded_file_names, session_id)
    
    # 작업 상태 초기화
    tasks_dict = request.app.state.tasks
    tasks_dict[task_id] = {
        "status": "pending",
        "message": "파일 업로드 완료, 처리 대기 중...",
        "progress": 0
    }
    
    return UploadResponse(
        task_id=task_id,
        message="파일 업로드 성공, 처리가 시작되었습니다.",
        files=file_info_list
    )


@router.get("/files/{filename}", response_model=FileContentResponse)
async def get_file_content(request: Request, filename: str):
    """특정 파일의 내용 조회 (OCR 결과 우선 검색)"""
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    paths = get_session_paths(request)
    
    import urllib.parse
    decoded_filename = urllib.parse.unquote(filename)
    base_name = Path(decoded_filename).stem
    
    # 검색 후보 경로 리스트 (OCR 결과 우선)
    search_paths = [
        # 1. 세션 OCR 결과 디렉토리
        paths["ocr_results_dir"] / decoded_filename,
        paths["ocr_results_dir"] / f"{base_name}.md",
        paths["ocr_results_dir"] / f"{base_name}.txt",
        
        # 2. 글로벌 OCR 결과 디렉토리
        config.DATA_ROOT / "Results" / "4.OCR_results" / decoded_filename,
        config.DATA_ROOT / "Results" / "4.OCR_results" / f"{base_name}.md",
        config.DATA_ROOT / "Results" / "4.OCR_results" / f"{base_name}.txt",
        
        # 3. 세션 원본 문서 디렉토리
        paths["doc_dir"] / decoded_filename,
        
        # 4. 글로벌 원본 문서 디렉토리
        config.DEFAULT_DOC_DIR / decoded_filename
    ]

    file_path = None
    for p in search_paths:
        if p.exists() and p.is_file():
            file_path = p
            break
            
    if file_path is None:
        logger.error(f"파일을 찾을 수 없음 (OCR/Doc 검색 실패): {decoded_filename}")
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {decoded_filename}")
    
    try:
        content = file_path.read_text(encoding="utf-8")
        logger.info(f"파일 내용 로드 성공: {file_path}")
        return FileContentResponse(filename=decoded_filename, content=content)
    except Exception as e:
        logger.error(f"파일 읽기 오류 ({decoded_filename}): {e}")
        raise HTTPException(status_code=500, detail=f"파일 읽기 오류: {e}")

@router.post("/search", response_model=SearchResponse)
async def search_endpoint(query: SearchQuery):
    """구글 검색 수행 API"""
    logger.info(f"검색 요청: {query.query}")
    try:
        # skill.search.pipeline.search_google 함수 호출 (num 인자 사용)
        results = perform_search(query.query, num=10)
        return SearchResponse(results=results)
    except Exception as e:
        logger.error(f"검색 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"검색 오류: {e}")


@router.post("/upload/docs", response_model=TaskCreationResponse)
async def add_document_endpoint(request: Request, doc_req: AddDocumentRequest, background_tasks: BackgroundTasks):
    """구글 검색 결과 중 하나를 문서화(크롤링)하고 인덱싱하는 API"""
    task_id = str(uuid.uuid4())
    session_id = getattr(request.state, "session_id", "default_session")
    
    tasks_dict = request.app.state.tasks
    tasks_dict[task_id] = {"status": "pending", "message": "문서화 작업 대기 중..."}
    
    background_tasks.add_task(run_document_pipeline, task_id, doc_req.title, doc_req.link, session_id)
    
    return TaskCreationResponse(task_id=task_id, status="pending")


@router.post("/cancel", response_model=Dict[str, Any])
async def cancel_tasks_endpoint(request: Request, body: Dict[str, Any] = Body(...)):
    """작업 취소 API"""
    task_ids = body.get("task_ids", [])
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids가 필요합니다.")
        
    cancelled_count = 0
    for task_id in task_ids:
        if cancel_task(task_id):
            cancelled_count += 1
            
    return {"message": f"총 {len(task_ids)}개 중 {cancelled_count}개 작업에 대한 취소 요청이 전달되었습니다."}


async def run_document_pipeline(task_id: str, title: str, link: str, session_id: Optional[str] = None):
    """구글 검색 결과를 문서화하고 인덱싱하는 백그라운드 함수 (crawling_web 인자 및 결과 처리 수정)"""
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    
    # 1. 경로 설정 (세션 및 글로벌)
    if session_id:
        doc_dir = config.get_session_doc_dir(session_id)
    else:
        doc_dir = config.DEFAULT_DOC_DIR

    # 디렉토리 생성 보장
    doc_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[{task_id}] 문서 파이프라인 시작 (session: {session_id}): {title}")
    tasks[task_id].update({'status': 'processing', 'message': '웹 페이지 크롤링 중...'})
    
    try:
        # 1. 크롤링 (result 딕셔너리 구성 및 output_dir 전달)
        search_result = {
            'title': title,
            'link': link
        }
        
        # crawling_web(result, output_dir) 호출
        # 이 함수 내부에서 4.OCR_results로의 복사도 수행됨
        saved_file_path = crawling_web(search_result, output_dir=str(doc_dir))
        
        if not saved_file_path:
            raise ValueError("웹 페이지 크롤링 및 저장에 실패했습니다.")
            
        safe_title = sanitize_filename(title)
        
        # 3. 인덱싱 (Vector Store 저장)
        # asyncio.run() 대신 직접 await 호출하여 루프 중첩 방지
        await run_text_indexing(task_id, [f"{safe_title}.md"], session_id)
        
    except Exception as e:
        logger.error(f"[{task_id}] 문서 파이프라인 실패: {e}")
        tasks[task_id].update({'status': 'failed', 'error': str(e)})
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
    """지정된 파일들을 찾아 내용을 요약하는 백그라운드 함수 (글로벌 + 세션 검색)"""
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    
    # 1. 경로 설정 (세션 및 글로벌)
    session_ocr_dir = None
    session_summarize_dir = None
    if session_id:
        session_ocr_dir = config.get_session_results_dir(session_id, "4.OCR_results")
        session_summarize_dir = config.get_session_results_dir(session_id, "6.summarize")
    
    global_ocr_dir = config.DATA_ROOT / "Results" / "4.OCR_results"
    global_summarize_dir = config.DATA_ROOT / "Results" / "6.summarize"
    
    # 결과가 저장될 디렉토리 (세션 우선, 없으면 글로벌)
    summarize_dir = session_summarize_dir or global_summarize_dir

    logger.info(f"[{task_id}] 파일 요약 작업 시작 (session: {session_id}): {filenames}")
    tasks[task_id].update({"status": "running", "message": "요약할 파일을 찾는 중...", "progress": 10})
    
    try:
        summaries, sources = [], []
        
        # AnswerGenerator 획득
        try:
            generator = model_manager.acquire("answer_generator")
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

                # 4.OCR_results에서 파일 검색 (세션 우선 후 글로벌)
                base_name = Path(filename).stem
                candidate_names = [filename, f"{base_name}.md"]
                
                file_to_summarize = None
                for name in candidate_names:
                    # 세션 디렉토리 먼저 확인
                    if session_ocr_dir:
                        p = session_ocr_dir / name
                        if p.exists():
                            file_to_summarize = p
                            break
                    
                    # 글로벌 디렉토리 확인
                    p = global_ocr_dir / name
                    if p.exists():
                        file_to_summarize = p
                        break
                
                if file_to_summarize is None:
                    logger.warning(f"[{task_id}] OCR 결과에서 파일을 찾을 수 없습니다: {filename}")
                    continue

                try:
                    with open(file_to_summarize, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if not content or content.isspace():
                        logger.warning(f"[{task_id}] 파일에 요약할 텍스트가 없습니다: {filename}")
                        continue
                        
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
    print("=== ROUTES.PY CHAT ENDPOINT CALLED ===")
    logger.info("=== ROUTES.PY CHAT ENDPOINT CALLED ===")
    task_id = str(uuid.uuid4())
    cancellation_event = threading.Event()
    request.app.state.running_tasks[task_id] = cancellation_event
    logger.info(f"[Task {task_id}] 채팅 작업 시작: '{query.query}'")
    logger.info("[Task %s] 요청으로 전달된 sources(raw): %s", task_id, query.sources)
    
    # 세션 ID 추출
    session_id = getattr(request.state, "session_id", "default_session")
    logger.info(f"[Task {task_id}] Session ID: {session_id}")
    
    # DEBUG: UUID 형식 확인
    for i, source in enumerate(query.sources):
        logger.info(f"[Task {task_id}] Source[{i}]: '{source}' (length: {len(source)}, is_uuid: {bool(UUID_PATTERN.match(source))})")

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
    
    # 세션 기반 필터링 로직
    # 1. 사용자가 특정 파일을 체크한 경우: 해당 파일들만 검색
    # 2. 사용자가 특정 파일을 체크하지 않은 경우: 현재 세션의 파일들만 검색
    source_filter_requested = bool(query.sources)
    
    if not source_filter_requested:
        logger.info(f"[Task {task_id}] No specific sources selected, will search within session {session_id} only")
        # 현재 세션의 모든 파일 UUID들을 자동으로 가져오기
        try:
            from notebooklm.config import RAGConfig
            config = RAGConfig()
            paths = get_session_paths(request)
            
            # 세션 파일 목록 수집 (세션 + 글로벌 기본 파일들 모두 포함)
            session_files = set()
            
            # 1. 세션 디렉토리 파일들 추가
            for d in [paths["doc_dir"]]:
                if d.exists():
                    for f in d.iterdir():
                        if f.is_file() and not f.name.startswith('.'):
                            session_files.add(f.name)
            
            # 2. 글로벌 기본 파일들도 추가 (세션 사용자가 접근 가능한 파일들)
            if config.DEFAULT_DOC_DIR.exists():
                for f in config.DEFAULT_DOC_DIR.iterdir():
                    if f.is_file() and not f.name.startswith('.'):
                        session_files.add(f.name)
            
            if session_files:
                # 세션별 UUID 매핑 가져오기
                client = config.get_weaviate_client()
                if client:
                    from notebooklm.weaviate_utils import get_document_uuid_map_with_session
                    session_uuid_map = get_document_uuid_map_with_session(client, list(session_files), session_id)
                    client.close()
                    
                    # resolved_sources를 세션의 모든 파일 UUID로 교체
                    resolved_sources = list(session_uuid_map.values())
                    logger.info(f"[Task {task_id}] Auto-selected {len(resolved_sources)} files (session + default): {resolved_sources}")
        except Exception as e:
            logger.error(f"[Task {task_id}] Failed to auto-select session files: {e}")
    else:
        logger.info(f"[Task {task_id}] Specific sources selected: {len(resolved_sources)} files")

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
            app_state=request.app.state,  # app.state 전체를 전달
            session_id=session_id  # 세션 ID 전달
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
