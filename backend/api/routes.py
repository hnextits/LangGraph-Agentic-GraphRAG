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

logger = logging.getLogger(__name__)
router = APIRouter(tags=["RAG"])

UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _resolve_sources_to_document_uuids(raw_sources: Optional[List[str]]) -> List[str]:
    """UUID 목록만 받아서 검증하고 반환합니다."""
    if not raw_sources:
        return []

    uuid_list: List[str] = []
    
    for item in raw_sources:
        if not item:
            continue
        if UUID_PATTERN.match(item):
            uuid_list.append(item)
        else:
            logger.warning("UUID 형식이 아닌 항목 거부: '%s'", item)

    # 중복 제거 및 순서 보존
    seen: Set[str] = set()
    unique_uuids: List[str] = []
    for value in uuid_list:
        if value and value not in seen:
            seen.add(value)
            unique_uuids.append(value)

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


def _get_config():
    """필요할 때마다 RAGConfig 인스턴스를 생성합니다."""
    from notebooklm.config import RAGConfig

    return RAGConfig()


def _get_session_id(request: Request) -> str:
    """요청 객체에서 세션 ID를 일관되게 추출합니다."""
    return getattr(request.state, "session_id", "default_session")


def _get_config_and_paths(request: Request):
    """자주 사용되는 config, session_id, paths를 함께 반환합니다."""
    config = _get_config()
    session_id = _get_session_id(request)
    paths = get_session_paths(request, config)
    return config, session_id, paths


def get_session_paths(request: Request, config=None):
    """요청의 세션 ID를 바탕으로 동적 경로를 반환합니다."""
    config = config or _get_config()
    session_id = _get_session_id(request)

    return {
        "doc_dir": config.get_session_doc_dir(session_id),
        "metadata_file": config.get_session_metadata_file(session_id),
        "ocr_results_dir": config.get_session_results_dir(session_id, "4.OCR_results"),
        "summarize_dir": config.get_session_results_dir(session_id, "6.summarize"),
        "stt_text_dir": config.get_session_results_dir(session_id, "7.stt"),
    }


def _get_doc_dir(config, session_id: Optional[str]):
    return config.get_session_doc_dir(session_id) if session_id else config.DEFAULT_DOC_DIR


def _get_results_dir(config, session_id: Optional[str], subdir: str):
    if session_id:
        return config.get_session_results_dir(session_id, subdir)
    return config.DATA_ROOT / "Results" / subdir

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
    stdout: Optional[str] = None
    stderr: Optional[str] = None
class SummarizeResponse(BaseModel):
    summary: str
    files: List[str]
    timestamp: str


# --- API 엔드포인트 구현 ---

@router.get("/files", response_model=FileListResponse)
async def list_files(request: Request):
    """업로드된 파일 목록 조회 (글로벌 + 세션별 병합, doc 디렉토리 기준)"""
    config, session_id, paths = _get_config_and_paths(request)
    logger.info(f"[/files] Session ID: {session_id}")
    
    # LeftBox에는 원본 문서(doc) 디렉토리의 파일들만 표시
    search_dirs = [
        config.DEFAULT_DOC_DIR,
        paths["doc_dir"]
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
        client = config.get_weaviate_client()
        if client and files_list:
            from notebooklm.weaviate_utils import get_document_uuid_map_with_session
            uuid_map = get_document_uuid_map_with_session(client, files_list, session_id)
            client.close()
    except Exception as e:
        logger.warning(f"UUID 매핑 조회 실패: {e}")

    return FileListResponse(files=files_list, document_uuid_map=uuid_map)


@router.get("/summarizes", response_model=FileListResponse)
async def list_summarizes(request: Request):
    """생성된 요약 파일 목록 조회 (글로벌 + 세션별 병합)"""
    config, _, paths = _get_config_and_paths(request)
    
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
    config, _, paths = _get_config_and_paths(request)
    
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
            error=status_data.get("error"),
            stdout=status_data.get("stdout"),
            stderr=status_data.get("stderr"),
        )
    
    # 2. GPU 작업 큐에서 확인
    from utils.task_queue import gpu_task_queue
    queue_status = gpu_task_queue.get_queue_status(task_id)
    if queue_status["status"] != "not_found":
        return TaskStatusResponse(
            task_id=task_id,
            status=queue_status["status"],
            message=queue_status["message"],
            progress=5 if queue_status["status"] == "pending" else 20,
            error=queue_status.get("error"),
            stdout=queue_status.get("stdout"),
            stderr=queue_status.get("stderr"),
        )
        
    raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")


@router.delete("/files", response_model=DeleteFilesResponse)
async def delete_files(request: Request, delete_req: DeleteFilesRequest):
    """파일 삭제 (세션별 격리)"""
    _, _, paths = _get_config_and_paths(request)
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
    _, session_id, paths = _get_config_and_paths(request)
    doc_dir = paths["doc_dir"]
    
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
        
    # 작업 상태 초기화 (백그라운드 등록보다 먼저 수행: 레이스 컨디션 방지)
    tasks_dict = request.app.state.tasks
    tasks_dict[task_id] = {
        "status": "pending",
        "message": "파일 업로드 완료, 처리 대기 중...",
        "progress": 0
    }

    # 백그라운드 처리 파이프라인 시작
    background_tasks.add_task(run_processing_pipeline, task_id, uploaded_file_names, tasks_dict, session_id)
    
    return UploadResponse(
        task_id=task_id,
        message="파일 업로드 성공, 처리가 시작되었습니다.",
        files=file_info_list
    )


@router.get("/files/{filename}", response_model=FileContentResponse)
async def get_file_content(request: Request, filename: str):
    """특정 파일의 내용 조회 (OCR 결과 우선 검색)"""
    config, _, paths = _get_config_and_paths(request)
    
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
    session_id = _get_session_id(request)
    
    tasks_dict = request.app.state.tasks
    tasks_dict[task_id] = {"status": "pending", "message": "문서화 작업 대기 중..."}
    
    background_tasks.add_task(run_document_pipeline, task_id, doc_req.title, doc_req.link, tasks_dict, session_id)
    
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


async def run_document_pipeline(task_id: str, title: str, link: str, tasks_dict: Dict[str, Any], session_id: Optional[str] = None):
    """구글 검색 결과를 문서화하고 인덱싱하는 백그라운드 함수"""
    config = _get_config()
    doc_dir = _get_doc_dir(config, session_id)

    # 디렉토리 생성 보장
    doc_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[{task_id}] 문서 파이프라인 시작 (session: {session_id}): {title}")
    tasks_dict[task_id].update({'status': 'processing', 'message': '웹 페이지 크롤링 중...'})
    
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
        await run_text_indexing(task_id, [f"{safe_title}.md"], tasks_dict, session_id)
        
    except Exception as e:
        logger.error(f"[{task_id}] 문서 파이프라인 실패: {e}")
        tasks_dict[task_id].update({'status': 'failed', 'error': str(e)})

# 기존 상수 제거 또는 함수로 대체 (하위 호환성을 위해 유지하되 내부 로직에서는 get_session_paths 사용 권장)
BASE_DIR = Path(__file__).resolve().parent.parent
NEXTITS_DATA_DIR = BASE_DIR / "nextits_data"
    
# --- 유틸리티 함수 ---
def check_and_handle_pause(task_id: str, tasks_dict: Dict[str, Any]) -> bool:
    """작업 취소 상태를 확인하고 처리합니다."""
    if is_cancelled(task_id):
        if tasks_dict.get(task_id, {}).get('status') != 'cancelled':
            tasks_dict[task_id].update({
                'status': 'cancelled',
            })
            logger.info(f"[Task {task_id}] 작업이 취소 상태로 변경되었습니다.")
        return True
    return False

async def run_text_indexing(task_id: str, file_names: List[str], tasks_dict: Dict[str, Any], session_id: Optional[str] = None):
    """텍스트 인덱싱 실행 함수 - 세션별 OCR 결과 디렉토리에서 검색"""
    config = _get_config()
    ocr_results_dir = _get_results_dir(config, session_id, "4.OCR_results")

    logger.info(f"[{task_id}] 텍스트 인덱싱 시작 (session: {session_id}): {file_names}")
    tasks_dict[task_id].update({
        'status': 'indexing',
        'message': '데이터 인덱싱 준비 중...',
        'progress': 75
    })

    try:
        if check_and_handle_pause(task_id, tasks_dict): return
        
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

            # fallback: OCR 결과가 원본 파일명이 아닌 변환 산출물 폴더명으로 생성되는 경우 대응
            if not any(Path(x).stem == base_name for x in processed_files): 
                base_variants = {
                    base_name,
                    base_name.replace(" ", "_"),
                    base_name.replace("_", " "),
                }
                matched = []
                for v in base_variants:
                    matched.extend(list(ocr_results_dir.glob(f"{v}*.md")))
                    matched.extend(list(ocr_results_dir.glob(f"{v}*.txt")))

                if matched:
                    matched_sorted = sorted(matched, key=lambda p: p.stat().st_mtime, reverse=True)
                    processed_files.append(str(matched_sorted[0]))
        
        if not processed_files:
            logger.warning(f"[{task_id}] 인덱싱할 처리된 파일을 찾지 못했습니다.")
            tasks_dict[task_id].update({'status': 'index_skipped', 'message': '인덱싱할 파일을 찾지 못해 건너뜁니다.', 'progress': 100})
            return

        # 2. embedding_text (late chunking) 실행
        from notebooklm.embedding_text import process_markdown_files
        from notebooklm.shared_embedding import shared_embedding
        
        # 임베딩 클라이언트 초기화 보장
        shared_embedding.load_model()
        
        # Weaviate 클라이언트 획득
        client = config.get_weaviate_client()
        if not client:
            raise RuntimeError("Weaviate 클라이언트를 초기화할 수 없습니다.")
        
        try:
            # late chunking 프로세스 실행 (session_id 전달)
            process_markdown_files(client, processed_files, session_id=session_id)
            logger.info(f"[{task_id}] Weaviate 벡터 인덱싱 성공")
        finally:
            client.close()

        # 3. Graph Extraction → .graph.json → Neo4j 저장
        tasks_dict[task_id].update({
            'status': 'graph_indexing',
            'message': '그래프 메타데이터 추출 및 Neo4j 저장 중...',
            'progress': 85
        })

        try:
            from nextits_data.pipe.langgraph_upload_pipeline import LangGraphUploadPipeline, UploadWorkflowState
            pipeline = LangGraphUploadPipeline(config)
            state = UploadWorkflowState(
                file_names=file_names,
                session_id=session_id,
                doc_dir=config.get_session_doc_dir(session_id) if session_id else config.DEFAULT_DOC_DIR,
                results_base=config.DATA_ROOT / "sessions" / session_id / "Results" if session_id else config.DATA_ROOT / "Results",
            )
            state.processed_files = processed_files
            pipeline._run_metadata_stage(state)
            logger.info(f"[{task_id}] 그래프 인덱싱 완료")
        except Exception as graph_err:
            logger.error(f"[{task_id}] 그래프 인덱싱 실패 (벡터 인덱싱은 성공): {graph_err}", exc_info=True)

        tasks_dict[task_id].update({
            'status': 'index_completed',
            'message': '파일 처리 및 인덱싱 완료 (벡터 + 그래프)',
            'progress': 100
        })
    except Exception as e:
        logger.error(f"[{task_id}] 텍스트 인덱싱 실패: {e}", exc_info=True)
        tasks_dict[task_id].update({'status': 'index_failed', 'error': str(e), 'progress': 100})

async def run_text_indexing_v2(task_id: str, file_names: List[str], tasks_dict: Dict[str, Any], session_id: Optional[str] = None):
    """텍스트 인덱싱 파이프라인 (Vector Store 저장)"""
    config = _get_config()
    ocr_results_dir = _get_results_dir(config, session_id, "4.OCR_results")

    logger.info(f"[{task_id}] 텍스트 인덱싱 시작 (session: {session_id}): {file_names}")
    tasks_dict[task_id].update({
        'status': 'indexing',
        'message': '데이터 인덱싱 준비 중...',
        'progress': 75
    })

    try:
        if await asyncio.to_thread(check_and_handle_pause, task_id, tasks_dict): return
        
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

            # fallback: OCR 결과가 원본 파일명이 아닌 변환 산출물 폴더명으로 생성되는 경우 대응
            if not any(Path(x).stem == base_name for x in processed_files):
                base_variants = {
                    base_name,
                    base_name.replace(" ", "_"),
                    base_name.replace("_", " "),
                }
                matched = []
                for v in base_variants:
                    matched.extend(list(ocr_results_dir.glob(f"{v}*.md")))
                    matched.extend(list(ocr_results_dir.glob(f"{v}*.txt")))

                if matched:
                    matched_sorted = sorted(matched, key=lambda p: p.stat().st_mtime, reverse=True)
                    processed_files.append(str(matched_sorted[0]))
        
        if not processed_files:
            logger.warning(f"[{task_id}] 인덱싱할 처리된 파일을 찾지 못했습니다.")
            tasks_dict[task_id].update({'status': 'index_skipped', 'message': '인덱싱할 파일을 찾지 못해 건너뜁니다.', 'progress': 100})
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

        # 2. embedding_text (late chunking) 실행
        from notebooklm.embedding_text import process_markdown_files
        from notebooklm.shared_embedding import shared_embedding
        
        # 임베딩 클라이언트 초기화 보장
        await asyncio.to_thread(shared_embedding.load_model)
        
        # Weaviate 클라이언트 획득
        client = config.get_weaviate_client()
        if not client:
            raise RuntimeError("Weaviate 클라이언트를 초기화할 수 없습니다.")
        
        try:
            # late chunking 프로세스 실행 (session_id 전달)
            await asyncio.to_thread(process_markdown_files, client, processed_files, session_id=session_id)
            logger.info(f"[{task_id}] Weaviate 벡터 인덱싱 성공")
        finally:
            client.close()

        # 3. Graph Extraction → .graph.json → Neo4j 저장
        tasks_dict[task_id].update({
            'status': 'graph_indexing',
            'message': '그래프 메타데이터 추출 및 Neo4j 저장 중...',
            'progress': 85
        })

        try:
            from nextits_data.pipe.langgraph_upload_pipeline import LangGraphUploadPipeline
            pipeline = LangGraphUploadPipeline(config)
            
            # run_post_ocr_pipeline의 metadata 단계만 실행
            # (벡터 인덱싱은 이미 위에서 완료했으므로 metadata만)
            from nextits_data.pipe.langgraph_upload_pipeline import UploadWorkflowState
            state = UploadWorkflowState(
                file_names=file_names,
                session_id=session_id,
                doc_dir=config.get_session_doc_dir(session_id) if session_id else config.DEFAULT_DOC_DIR,
                results_base=config.DATA_ROOT / "sessions" / session_id / "Results" if session_id else config.DATA_ROOT / "Results",
            )
            state.processed_files = processed_files
            
            # LLM 메타데이터 추출 + Neo4j 저장
            state = await asyncio.to_thread(pipeline._run_metadata_stage, state)
            
            graph_count = len(state.metadata_files) if state.metadata_files else 0
            logger.info(f"[{task_id}] 그래프 인덱싱 완료: {graph_count}개 파일")
        except Exception as graph_err:
            logger.error(f"[{task_id}] 그래프 인덱싱 실패 (벡터 인덱싱은 성공): {graph_err}", exc_info=True)

        tasks_dict[task_id].update({
            'status': 'index_completed',
            'message': '파일 처리 및 인덱싱 완료 (벡터 + 그래프)',
            'progress': 100
        })
    except Exception as e:
        logger.error(f"[{task_id}] 텍스트 인덱싱 실패: {e}", exc_info=True)
        tasks_dict[task_id].update({'status': 'index_failed', 'error': str(e), 'progress': 100})

async def run_processing_pipeline(task_id: str, file_names: List[str], tasks_dict: Dict[str, Any], session_id: Optional[str] = None):
    """(업로드된 파일) 처리 및 인덱싱 파이프라인 (GPU 작업 큐 사용)"""
    from utils.task_queue import gpu_task_queue
    config = _get_config()
    doc_dir = _get_doc_dir(config, session_id)

    logger.info(f"[{task_id}] 파일 처리 파이프라인 큐 등록 (session: {session_id}): {file_names}")
    tasks_dict[task_id].update({'status': 'queued', 'message': '대기열에 등록되었습니다. GPU 리소스 확보 중...', 'progress': 5})

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
                tasks_dict[task_id].update({
                    'status': 'processing', 
                    'message': status_info["message"],
                    'progress': 20,
                    'stdout': status_info.get('stdout'),
                    'stderr': status_info.get('stderr'),
                })
            elif status_info["status"] == "pending":
                tasks_dict[task_id].update({
                    'status': 'queued', 
                    'message': status_info["message"],
                    'progress': 5,
                    'stdout': status_info.get('stdout'),
                    'stderr': status_info.get('stderr'),
                })
            elif status_info["status"] == "completed":
                # 서브프로세스 출력 로그를 task 상태에 반영
                tasks_dict[task_id].update({
                    'stdout': status_info.get('stdout'),
                    'stderr': status_info.get('stderr'),
                })
                break
            elif status_info["status"] == "failed":
                tasks_dict[task_id].update({
                    'stdout': status_info.get('stdout'),
                    'stderr': status_info.get('stderr'),
                })
                raise RuntimeError(status_info.get("error", "알 수 없는 작업 오류"))
            
            await asyncio.sleep(2)

        # 인덱싱 단계 진행
        await run_text_indexing_v2(task_id, file_names, tasks_dict, session_id)

    except Exception as e:
        logger.error(f"[{task_id}] 파일 처리 파이프라인 실패: {e}", exc_info=True)
        tasks_dict[task_id].update({'status': 'failed', 'error': str(e), 'progress': 100})


async def process_summarize_files(task_id: str, filenames: List[str], model_manager: Any, tasks_dict: Dict[str, Any], session_id: Optional[str] = None):
    """지정된 파일들을 찾아 내용을 요약하는 백그라운드 함수 (글로벌 + 세션 검색)"""
    config = _get_config()
    session_ocr_dir = _get_results_dir(config, session_id, "4.OCR_results") if session_id else None
    session_summarize_dir = _get_results_dir(config, session_id, "6.summarize") if session_id else None
    global_ocr_dir = _get_results_dir(config, None, "4.OCR_results")
    global_summarize_dir = _get_results_dir(config, None, "6.summarize")
    
    # 결과가 저장될 디렉토리 (세션 우선, 없으면 글로벌)
    summarize_dir = session_summarize_dir or global_summarize_dir

    logger.info(f"[{task_id}] 파일 요약 작업 시작 (session: {session_id}): {filenames}")
    tasks_dict[task_id].update({"status": "running", "message": "요약할 파일을 찾는 중...", "progress": 10})
    
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
            tasks_dict[task_id].update({"status": "failed", "error": f"요약 모델 로드 실패: {e}"})
            return

        try:
            for i, filename in enumerate(filenames):
                if await asyncio.to_thread(check_and_handle_pause, task_id, tasks_dict): return
                
                progress = 10 + int((i / len(filenames)) * 80)
                tasks_dict[task_id].update({"message": f"파일 처리 중... ({i+1}/{len(filenames)}): {filename}", "progress": progress})

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
            tasks_dict[task_id].update({"status": "completed", "message": "요약할 내용이 있는 파일을 찾지 못했습니다.", "progress": 100, "result": {"summary": "요약할 내용이 없습니다.", "sources": []}})
            return

        final_summary = "\n\n---\n\n".join(summaries)
        safe_filenames_str = sanitize_summary_filename("_".join(filenames))
        result_file = summarize_dir / f"summary_{safe_filenames_str}.md"
        result_file.write_text(final_summary, encoding="utf-8")
        
        tasks_dict[task_id].update({
            "status": "completed", "message": "요약이 완료되었습니다.", "progress": 100,
            "result": {"summary": final_summary, "sources": sources, "result_file": str(result_file)}
        })
        logger.info(f"[{task_id}] 파일 요약 작업 완료. 파일: {result_file}")

    except Exception as e:
        logger.error(f"[{task_id}] 파일 요약 파이프라인 실패: {e}", exc_info=True)
        tasks_dict[task_id].update({"status": "failed", "message": f"오류 발생: {e}", "progress": 100, "error": str(e)})

@router.post("/summarize", response_model=TaskCreationResponse)
async def summarize_files(request_data: SummarizeRequest, background_tasks: BackgroundTasks, request: Request) -> TaskCreationResponse:
    """선택된 파일들을 요약하는 API (백그라운드 처리)"""
    file_names = request_data.filenames
    logger.info(f"요약 요청 받음: {file_names}")
    
    task_id = str(uuid.uuid4())
    tasks_dict = request.app.state.tasks
    tasks_dict[task_id] = {"task_id": task_id, "status": "pending", "message": "요약 작업이 대기 중입니다."}
    
    model_manager = getattr(request.app.state, "model_manager", None)
    session_id = _get_session_id(request)
    
    background_tasks.add_task(
        process_summarize_files, 
        task_id, 
        file_names, 
        model_manager, 
        tasks_dict,
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
    
    config, session_id, paths = _get_config_and_paths(request)
    logger.info(f"[Task {task_id}] Session ID: {session_id}")
    

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
        try:
            session_files = set()
            doc_dir = paths["doc_dir"]
            if doc_dir.exists():
                for f in doc_dir.iterdir():
                    if f.is_file() and not f.name.startswith('.'):
                        session_files.add(f.name)

            if session_files:
                client = config.get_weaviate_client()
                if client:
                    from notebooklm.weaviate_utils import get_document_uuid_map_with_session
                    session_uuid_map = get_document_uuid_map_with_session(client, list(session_files), session_id)
                    client.close()

                    resolved_sources = list(session_uuid_map.values())
                    logger.info(f"[Task {task_id}] Auto-selected {len(resolved_sources)} session files: {resolved_sources}")
        except Exception as e:
            logger.error(f"[Task {task_id}] Failed to auto-select session files: {e}")
    else:
        logger.info(f"[Task {task_id}] Specific sources selected: {len(resolved_sources)} files")

    # acquire + load_engine은 백그라운드에서 수행 (HTTP 응답 블로킹 방지)
    background_tasks.add_task(
        run_rag_in_background,
        task_id=task_id,
        query=query.query,
        sources=resolved_sources,
        source_filter_requested=source_filter_requested,
        rag_pipeline=None,
        cancellation_event=cancellation_event,
        tasks_dict=tasks,
        running_tasks_dict=request.app.state.running_tasks,
        app_state=request.app.state,
        session_id=session_id,
        model_manager=model_manager,
    )

    return ChatResponse(task_id=task_id, message="채팅 작업이 시작되었습니다.")
