from fastapi import APIRouter, HTTPException, File, UploadFile, BackgroundTasks, Request, Body
import asyncio
from typing import List, Dict, Any, Optional
import os
import shutil
from pydantic import BaseModel, validator
import logging
import traceback
import uuid
import re
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime
from services.rag_service import get_rag_response
from search_test.crawler_pipeline import crawling_web, sanitize_filename
from utils.helpers import process_response_with_images, encode_image_to_base64, find_image_file
from api.pause_api import is_cancelled

# 로거 설정
logger = logging.getLogger(__name__)

# search_test 디렉토리의 crawler_pipeline.py 모듈 가져오기
try:
    # 상대 경로를 사용하여 search_test 디렉토리의 모듈을 명시적으로 가져오기
    import sys
    from pathlib import Path
    
    # backend 디렉토리 경로 가져오기
    backend_dir = Path(__file__).parent.parent.absolute()
    search_test_dir = os.path.join(backend_dir, 'search_test')
    
    # search_test 디렉토리가 sys.path에 없으면 추가
    if search_test_dir not in sys.path:
        sys.path.append(str(search_test_dir))
        logger.info(f"search_test 디렉토리를 sys.path에 추가했습니다: {search_test_dir}")
    
    # 이제 crawler_pipeline.py에서 함수 가져오기
    from crawler_pipeline import search as perform_search, crawling_web
    logger.info("search_test/crawler_pipeline.py에서 search 및 crawling_web 함수를 성공적으로 가져왔습니다.")
    
except ImportError as e:
    logger.error(f"crawler_pipeline 모듈 가져오기 실패: {e}")
    logger.error(f"전체 오류 스택: {traceback.format_exc()}")
    perform_search = None
    crawling_web = None

# API 라우터 설정
router = APIRouter()

# 작업 상태를 저장할 딕셔너리 (프로세스 재시작 시 초기화됨)
tasks = {}
# no_llm_summary_routes.py에서 가져온 작업 상태 저장소
task_status = {}

# API 응답 모델 정의
class RootResponse(BaseModel):
    message: str

class SearchResponse(BaseModel):
    results: List[Dict[str, Any]]

class AddDocumentResponse(BaseModel):
    task_id: str
    file_name: str
    title: str
    status: str

class TaskStatusResponse(BaseModel):
    status: str
    file_name: Optional[str] = None
    title: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message: Optional[str] = None
    progress: Optional[int] = None

class UploadResponse(BaseModel):
    message: str
    files: List[Dict[str, Any]]

class FileListResponse(BaseModel):
    files: List[str]

class FileContentResponse(BaseModel):
    filename: str
    content: str

class SearchSummarizeResponse(BaseModel):
    task_id: str
    status: str

# nextits_data 경로 설정
NEXTITS_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'nextits_data'))
DOC_DIR = os.path.join(NEXTITS_DATA_DIR, "doc")
# 서버 시작 시 디렉터리가 없으면 생성
os.makedirs(DOC_DIR, exist_ok=True)

# 크롤링 결과 저장 디렉토리 (no_llm_summary_routes.py에서 가져옴)
CRAWLING_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'search_test', 'Crawling_data')
SNIPPET_DIR = os.path.join(CRAWLING_DIR, '4.snippet')
CLEAN_MD_DIR = os.path.join(CRAWLING_DIR, '6.clean_md')

# 디렉토리 생성
os.makedirs(SNIPPET_DIR, exist_ok=True)
os.makedirs(CLEAN_MD_DIR, exist_ok=True)

class RootResponse(BaseModel):
    message: str

@router.get("/", response_model=RootResponse)
def read_root() -> RootResponse:
    """서버가 실행 중인지 확인하는 기본 엔드포인트"""
    return {"message": "Welcome to the Chatbot API"}

class SearchQuery(BaseModel):
    query: str
    
    class Config:
        str_strip_whitespace = True  # 자동으로 공백 제거
    
    @validator('query')
    def validate_query(cls, v):
        if not v or not v.strip():
            raise ValueError('검색어는 비어있을 수 없습니다.')
        if len(v.strip()) < 1:
            raise ValueError('검색어는 최소 1자 이상이어야 합니다.')
        return v.strip()

class SearchResponse(BaseModel):
    results: List[Dict[str, Any]]

@router.post("/search", response_model=SearchResponse)
async def search(request: Request, query: SearchQuery) -> SearchResponse:
    # 요청 정보 상세 로깅
    logger.info(f"=== 검색 요청 시작 ===")
    logger.info(f"요청 URL: {request.url}")
    logger.info(f"요청 메서드: {request.method}")
    logger.info(f"요청 헤더: {dict(request.headers)}")
    logger.info(f"검색어: '{query.query}' (타입: {type(query.query)}, 길이: {len(query.query)})")
    
    if perform_search is None or crawling_web is None:
        error_msg = "검색 또는 크롤링 모듈을 가져올 수 없습니다. 서버 로그를 확인해주세요."
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
    
    try:
        logger.info("검색 함수 실행 시작")
        results = perform_search(query.query, 10, [])
        
        if results is None:
            logger.warning("검색 결과가 None입니다.")
            results = []
        
        logger.info(f"검색 완료: {len(results)}개 결과 반환")
        logger.info(f"=== 검색 요청 완료 ===")
        return {"results": results}
    except ValueError as ve:
        error_msg = f"입력 값 오류: {str(ve)}"
        logger.error(error_msg)
        raise HTTPException(status_code=422, detail=error_msg)
    except Exception as e:
        error_msg = f"검색 중 오류 발생: {str(e)}"
        logger.error(error_msg)
        logger.error(f"전체 오류 스택: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_msg)

class AddDocumentRequest(BaseModel):
    title: str
    link: str

class AddDocumentResponse(BaseModel):
    task_id: str
    file_name: str
    title: str
    status: str

def run_document_pipeline(title: str, link: str, task_id: str):
    """
    백그라운드에서 실행될 문서 처리 파이프라인.
    """
    logger.info(f"[Task {task_id}] 🚀 Starting document pipeline for: {title}")
    logger.info(f"[Task {task_id}] Initial task state: {tasks.get(task_id, 'NOT FOUND')}")
    
    tasks[task_id]['status'] = 'processing'
    output_dir = DOC_DIR
    
    logger.info(f"[Task {task_id}] Status set to 'processing', output_dir: {output_dir}")
    
    # 일시 중지 상태 확인 및 처리
    if check_and_handle_pause(task_id):
        return
    
    try:
        logger.info(f"[Task {task_id}] Crawling web for: {title}")
        file_path = crawling_web(result={'title': title, 'link': link}, output_dir=output_dir)
        
        # 크롤링 결과가 파일 경로인지 확인
        if isinstance(file_path, str) and os.path.exists(file_path):
            logger.info(f"[Task {task_id}] Using file: {file_path}")
        else:
            # 크롤링 결과가 유효한 파일 경로가 아닌 경우
            logger.error(f"[Task {task_id}] Invalid crawling result: {file_path}")
            tasks[task_id]['status'] = 'error'
            tasks[task_id]['message'] = f"Invalid crawling result: {file_path}"
            return
        
        if not file_path or not os.path.exists(file_path):
            raise ValueError(f"Failed to create markdown file for {title}")


        logger.info(f"[Task {task_id}] Running chunking script for: {file_path}")
        
        # rag_pipeline.py와 동일한 방식으로 직접 import하여 실행
        original_cwd = os.getcwd()
        original_sys_path = list(sys.path)
        
        try:
            # notebooklm 디렉토리 경로 설정
            notebooklm_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            sys.path.insert(0, notebooklm_path)
            os.chdir(notebooklm_path)
            
            # qwen3_late_chunking 모듈 동적 import
            from notebooklm.qwen3_late_chunking import main as chunking_main
            
            # 원래 sys.argv를 백업하고 새 인자 설정
            original_argv = sys.argv
            index_path = os.path.abspath(os.path.join(notebooklm_path, 'notebooklm', 'faiss_test', 'text_index.faiss'))
            sys.argv = ['qwen3_late_chunking.py', '--input-file', file_path, '--index-path', index_path]
            
            # 직접 main 함수 호출
            logger.info(f"[Task {task_id}] Directly calling chunking_main function")
            chunking_main()
            logger.info(f"[Task {task_id}] Chunking completed successfully")
            
            # 인덱스 다시 로드
            logger.info(f"[Task {task_id}] Reloading text index after chunking")
            try:
                # 새로운 TextSearcher 인스턴스를 생성하여 인덱스 다시 로드
                from notebooklm.rag_text.text_search import TextSearcher
                
                # 인덱스 디렉토리 경로
                index_dir = os.path.dirname(index_path)
                
                # 새 TextSearcher 인스턴스 생성 및 인덱스 로드
                temp_searcher = TextSearcher(index_path=index_dir)
                logger.info(f"[Task {task_id}] Created new TextSearcher and loaded index from {index_dir}")
                
                # 기존 인스턴스는 직접 접근할 수 없으므로 새로 생성한 TextSearcher만 사용
                # 이미 새로운 인덱스가 로드되었으므로 추가 작업 필요 없음
                logger.info(f"[Task {task_id}] New text searcher instance is ready with fresh index")
                
                # 이후 새로운 요청에서는 자동으로 새 인덱스가 사용됨
            except Exception as e:
                logger.error(f"[Task {task_id}] Error reloading text index: {str(e)}", exc_info=True)
            
        except Exception as e:
            logger.error(f"[Task {task_id}] Error during chunking: {str(e)}", exc_info=True)
            raise ValueError(f"Chunking failed: {str(e)}")
        finally:
            # 환경 복원
            os.chdir(original_cwd)
            sys.path = original_sys_path
            if 'original_argv' in locals():
                sys.argv = original_argv

        tasks[task_id]['status'] = 'completed'
        tasks[task_id]['result'] = f"Document '{title}' added and indexed successfully."
        logger.info(f"[Task {task_id}] ✅ TASK COMPLETED SUCCESSFULLY - Status set to 'completed'")
        logger.info(f"[Task {task_id}] Final task state: {tasks[task_id]}")

    except Exception as e:
        logger.error(f"[Task {task_id}] ❌ PIPELINE FAILED: {e}")
        logger.error(f"[Task {task_id}] Full error traceback: {traceback.format_exc()}")
        tasks[task_id]['status'] = 'failed'
        tasks[task_id]['error'] = str(e)
        logger.info(f"[Task {task_id}] Final task state (failed): {tasks[task_id]}")

@router.post("/add_document_from_search", response_model=AddDocumentResponse)
def add_document_from_search(request: AddDocumentRequest, background_tasks: BackgroundTasks) -> AddDocumentResponse:
    task_id = str(uuid.uuid4())
    safe_filename = re.sub(r'[\/*?":<>|]', "", request.title) # 유효하지 않은 문자 제거
    md_filename = f"{safe_filename}.md"
    
    tasks[task_id] = {
        'status': 'pending',
        'file_name': md_filename,
        'title': request.title
    }
    
    background_tasks.add_task(run_document_pipeline, request.title, request.link, task_id)
    
    return {"task_id": task_id, "file_name": md_filename, "title": request.title, "status": "processing"}

@router.get("/task_status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

# class SummarizeRequest(BaseModel):
#     query: str
#     documents: list

# @router.post("/api/summarize")
# async def summarize(request: SummarizeRequest) -> Dict[str, str]:
#     """
#     클라이언트로부터 문서 목록을 받아 요약 결과를 반환합니다.
#     """
#     documents = request.documents
#     logger.info(f"{len(documents)}개의 문서에 대한 요약 요청을 받았습니다.")

#     if perform_summarize is None:
#         raise HTTPException(status_code=500, detail="요약 모듈을 사용할 수 없습니다.")

#     if not documents:
#         raise HTTPException(status_code=400, detail="요약할 문서가 없습니다.")

#     try:
#         # crawler_pipeline의 summarize 함수 호출
#         summary_text = perform_summarize(request.query, request.documents)
#         logger.info("요약 생성을 완료했습니다.")
#         return {"summary": summary_text}

#     except Exception as e:
#         error_msg = f"요약 중 오류 발생: {str(e)}"
#         logger.error(error_msg)
#         logger.error(f"전체 오류 스택: {traceback.format_exc()}")
#         raise HTTPException(status_code=500, detail=error_msg)

def check_and_handle_pause(task_id: str) -> bool:
    """
    취소 상태를 확인하고 처리합니다.
    
    Args:
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
    """텍스트 인덱싱을 실행하는 함수 - 직접 함수 호출 방식으로 변경"""
    global tasks
    try:
        # 일시 중지 상태 확인 및 처리
        if check_and_handle_pause(task_id):
            return
            
        # 원본 파일 경로에서 파일명 추출
        file_name = os.path.basename(file_path)
        base_name, _ = os.path.splitext(file_name)
        
        # OCR 결과 파일 경로 생성
        ocr_results_dir = os.path.join(NEXTITS_DATA_DIR, "Results", "3.OCR_results")
        md_file_path = os.path.join(ocr_results_dir, f"{base_name}.md")
        
        # 파일이 존재하는지 확인
        if not os.path.exists(md_file_path):
            alternative_md_file = os.path.join(ocr_results_dir, f"{file_name}.md")
            if os.path.exists(alternative_md_file):
                md_file_path = alternative_md_file
            else:
                error_message = f"OCR 결과 파일을 찾을 수 없습니다: {md_file_path}"
                logger.error(error_message)
                tasks[task_id]['status'] = 'index_failed'
                tasks[task_id]['error'] = error_message
                return
        
        # 기본 인덱스 경로
        index_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'notebooklm', 'faiss_test', 'text_index.faiss'))
        
        logger.info(f"텍스트 인덱싱 시작 (task {task_id}): {md_file_path}")
        tasks[task_id]['status'] = 'indexing'
        tasks[task_id]['progress'] = "텍스트 인덱싱 중..."
        
        # 원래 작업 디렉토리와 sys.path 백업
        original_cwd = os.getcwd()
        original_sys_path = list(sys.path)
        original_argv = sys.argv
        
        try:
            # notebooklm 디렉토리 경로 설정
            notebooklm_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            sys.path.insert(0, notebooklm_path)
            os.chdir(notebooklm_path)
            
            # qwen3_late_chunking 모듈 동적 import
            from notebooklm.qwen3_late_chunking import main as chunking_main
            
            # 새 인자 설정
            sys.argv = ['qwen3_late_chunking.py', '--input-file', md_file_path, '--index-path', index_path]
            
            # 직접 main 함수 호출
            logger.info(f"[Task {task_id}] 직접 chunking_main 함수 호출")
            chunking_main()
            logger.info(f"[Task {task_id}] 청킹 완료")
            
            # 인덱스 다시 로드
            logger.info(f"[Task {task_id}] 텍스트 인덱스 다시 로드")
            try:
                # 새로운 TextSearcher 인스턴스를 생성하여 인덱스 다시 로드
                from notebooklm.rag_text.text_search import TextSearcher
                
                # 인덱스 디렉토리 경로
                index_dir = os.path.dirname(index_path)
                
                # 새 TextSearcher 인스턴스 생성 및 인덱스 로드
                temp_searcher = TextSearcher(index_path=index_dir)
                logger.info(f"[Task {task_id}] 새 TextSearcher 생성 및 인덱스 로드 완료: {index_dir}")
                
                # 이후 새로운 요청에서는 자동으로 새 인덱스가 사용됨
            except Exception as e:
                logger.warning(f"[Task {task_id}] 인덱스 다시 로드 중 경고 (치명적이지 않음): {e}")
            
            # 성공 상태 업데이트
            tasks[task_id]['status'] = 'index_completed'
            tasks[task_id]['result'] = {"message": "파일 처리 및 인덱싱 완료"}
            logger.info(f"텍스트 인덱싱 성공 (task {task_id})")
            
        finally:
            # 원래 환경 복원
            os.chdir(original_cwd)
            sys.path = original_sys_path
            sys.argv = original_argv
    
    except Exception as e:
        logger.error(f"텍스트 인덱싱 중 오류 발생 (task {task_id}): {e}", exc_info=True)
        tasks[task_id]['status'] = 'index_failed'
        tasks[task_id]['error'] = str(e)

def run_processing_pipeline(task_id: str, file_path: str):
    global tasks
    try:
        # 일시 중지 상태 확인 및 처리
        if check_and_handle_pause(task_id):
            return
            
        logger.info(f"Starting processing for task {task_id}: {file_path}")

        # pipe/run_file_processor.py 스크립트의 절대 경로
        script_path = os.path.join(NEXTITS_DATA_DIR, "pipe", "run_file_processor.py")

        if not os.path.exists(script_path):
            error_message = f"Processing script not found at {script_path}"
            logger.error(error_message)
            tasks[task_id] = {"status": "failed", "error": error_message, "file_path": file_path}
            return

        # subprocess를 사용하여 스크립트 실행
        command = [
            sys.executable,  # 현재 파이썬 인터프리터 사용
            script_path,
            "--file",
            file_path
        ]
        
        logger.info(f"Executing command: {' '.join(command)}")
        tasks[task_id]['status'] = 'processing'
        tasks[task_id]['progress'] = "파일 처리 중..."

        # 스크립트 실행
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8')

        # 실행 결과 로깅
        if result.returncode == 0:
            logger.info(f"Script execution successful for task {task_id}.")
            logger.info(f"STDOUT:\n{result.stdout}")
            tasks[task_id]['status'] = 'processed'
            tasks[task_id]['result'] = {"message": "File processed successfully", "output": result.stdout}
            
            # 파일 처리 완료 후 텍스트 인덱싱 실행
            logger.info(f"Starting text indexing for task {task_id}")
            run_text_indexing(task_id, file_path)
        else:
            error_message = f"Script execution failed for task {task_id} with return code {result.returncode}.\nSTDERR:\n{result.stderr}"
            logger.error(error_message)
            tasks[task_id] = {"status": "failed", "error": result.stderr, "file_path": file_path}

    except Exception as e:
        logger.error(f"Error processing task {task_id}: {e}", exc_info=True)
        tasks[task_id] = {"status": "failed", "error": str(e), "file_path": file_path}

@router.post("/upload", summary="Upload files and process them", response_model=UploadResponse)
async def upload_files(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)) -> UploadResponse:
    """
    파일을 비동기적으로 업로드하고 처리 파이프라인을 실행합니다.
    """
    logger.info(f"'/api/upload' 엔드포인트 수신. {len(files)}개의 파일.")
    saved_files_info = []
    for file in files:
        safe_filename = "".join(c for c in file.filename if c.isalnum() or c in ('_', '.', '-')).strip()
        if not safe_filename:
            safe_filename = f"{uuid.uuid4().hex}.dat"
            
        saved_file_path = os.path.join(DOC_DIR, safe_filename)
        
        try:
            with open(saved_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        
            logger.info(f"파일 저장 완료: {saved_file_path}")
            task_id = str(uuid.uuid4())
            tasks[task_id] = {"status": "queued", "filename": safe_filename}
            
            background_tasks.add_task(run_processing_pipeline, task_id, str(saved_file_path))
            
            saved_files_info.append({
                "filename": safe_filename,
                "task_id": task_id,
                "size": os.path.getsize(saved_file_path),
                "content_type": file.content_type
            })
            logger.info(f"파일 처리 작업 시작: {saved_file_path}, Task ID: {task_id}")

        except Exception as e:
            error_msg = f"'{safe_filename}' 파일 처리 시작 중 오류 발생: {e}"
            logger.error(error_msg)
            logger.error(f"전체 오류 스택: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=error_msg)
        finally:
            file.file.close()

    logger.info(f"파일 처리 작업 시작 및 응답 반환. Task IDs: {[info['task_id'] for info in saved_files_info]}")
    return {"message": f"{len(saved_files_info)}개의 파일이 성공적으로 업로드 및 처리 시작됨", "files": saved_files_info}

@router.get("/task_status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.get("/files", summary="List files in the document directory", response_model=FileListResponse)
async def list_files() -> FileListResponse:
    """
    `nextits_data/doc` 디렉터리에 있는 파일 목록을 반환합니다.
    """
    try:
        if not os.path.isdir(DOC_DIR):
            logger.warning(f"Doc directory not found at: {DOC_DIR}")
            return {"files": []}

        files = [f for f in os.listdir(DOC_DIR) if os.path.isfile(os.path.join(DOC_DIR, f))]
        logger.info(f"Found {len(files)} files in {DOC_DIR}")
        return {"files": files}
    except Exception as e:
        logger.error(f"Error listing files from {DOC_DIR}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="파일 목록을 가져오는 중 오류가 발생했습니다.")

@router.get("/file/{filename}", summary="Get file content from OCR results", response_model=FileContentResponse)
async def get_file_content(filename: str) -> FileContentResponse:
    """
    `nextits_data/Results/3.OCR_results` 디렉터리에서
    주어진 파일명과 동일한 이름의 마크다운(.md) 파일 내용을 반환합니다.
    """
    try:
        # 원본 파일 이름에서 확장자를 제거하고 .md를 붙이거나, 그대로 .md를 붙입니다.
        base_filename, _ = os.path.splitext(filename)
        md_filename = f"{filename}.md"
        
        ocr_results_dir = os.path.join(NEXTITS_DATA_DIR, "Results", "3.OCR_results")
        file_path = os.path.join(ocr_results_dir, md_filename)

        logger.info(f"Attempting to read file: {file_path}")

        if not os.path.isfile(file_path):
            # 혹시 모를 다른 경우 (e.g., report.pdf -> report.md)
            alternative_md_filename = f"{base_filename}.md"
            alternative_file_path = os.path.join(ocr_results_dir, alternative_md_filename)
            logger.info(f"Primary file not found, trying alternative: {alternative_file_path}")
            if not os.path.isfile(alternative_file_path):
                 raise HTTPException(status_code=404, detail=f"'{md_filename}' 또는 '{alternative_md_filename}' 파일을 찾을 수 없습니다.")
            file_path = alternative_file_path

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {"filename": os.path.basename(file_path), "content": content}

    except HTTPException as http_exc:
        logger.warning(f"File not found for '{filename}': {http_exc.detail}")
        raise http_exc
    except Exception as e:
        logger.error(f"Error reading file content for '{filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="파일 내용을 읽는 중 오류가 발생했습니다.")

# Pydantic 모델 정의
class ChatQuery(BaseModel):
    query: str
    sources: List[str] = []

class ChatResponse(BaseModel):
    answer: str
    images: List[str]

@router.post("/v1/chat", response_model=ChatResponse)
def chat(query: ChatQuery, request: Request) -> ChatResponse:
    logger.info(f"Received query: {query.query} with sources: {query.sources}")
    try:
        # RAG 파이프라인 인스턴스를 app.state에서 가져옵니다.
        rag_pipeline = request.app.state.rag_pipeline
        if not rag_pipeline:
            logger.error("RAG pipeline is not initialized or not found in app.state.")
            raise HTTPException(status_code=503, detail="RAG pipeline is not available.")

        # RAG 서비스를 직접 호출합니다.
        rag_response = get_rag_response(query.query, query.sources, rag_pipeline)
        
        # rag_response가 이미 {'answer': str, 'images': List[str]} 형식이니
        # ChatResponse 모델에 맞게 언패킹하여 전달합니다.
        return ChatResponse(**rag_response)

    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search_and_summarize", response_model=SearchSummarizeResponse)
async def search_and_summarize(
    background_tasks: BackgroundTasks,
    request_data: dict = Body(...)
) -> SearchSummarizeResponse:
    """
    검색어를 받아 구글 검색 결과를 크롤링하고 LLM 없이 요약하는 API 엔드포인트
    """
    query = request_data.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="검색어가 필요합니다")
    
    # 작업 ID 생성
    task_id = str(uuid.uuid4())
    task_status[task_id] = {
        "status": "pending",
        "message": "작업이 대기 중입니다",
        "progress": 0,
        "result": None,
        "error": None
    }
    
    # 백그라운드 작업으로 검색 및 요약 실행
    background_tasks.add_task(
        process_search_and_summarize,
        task_id=task_id,
        query=query
    )
    
    return {"task_id": task_id, "status": "pending"}


@router.get("/task_status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status_no_llm(task_id: str) -> TaskStatusResponse:
    """
    작업 상태를 확인하는 API 엔드포인트
    """
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    
    return task_status[task_id]


async def process_search_and_summarize(task_id: str, query: str):
    """
    백그라운드에서 검색, 크롤링, 요약을 처리하는 함수
    """
    try:
        # 취소 상태 확인 함수 정의
        async def check_pause():
            # 취소 상태 확인
            if is_cancelled(task_id):
                if task_status.get(task_id, {}).get('status') != 'cancelled':
                    task_status[task_id].update({
                        "status": "cancelled",
                        "message": "작업이 취소되었습니다."
                    })
                    logger.info(f"[Task {task_id}] 작업이 취소되었습니다.")
                return True
            
            return False
        
        # 상태 업데이트: 검색 시작
        task_status[task_id].update({
            "status": "running",
            "message": "구글 검색 중...",
            "progress": 10
        })
        
        # 일시 중지 확인
        if await check_pause():
            return
        
        # 1. 구글 검색 수행
        total_result_link = []
        results = perform_search(query, 5, total_result_link)
        
        if not results:
            task_status[task_id].update({
                "status": "completed",
                "message": "검색 결과가 없습니다",
                "progress": 100,
                "result": {"summary": "검색 결과가 없습니다", "sources": []}
            })
            return
        
        # 일시 중지 확인
        if await check_pause():
            return
            
        # 상태 업데이트: 크롤링 시작
        task_status[task_id].update({
            "status": "running",
            "message": "웹 페이지 크롤링 중...",
            "progress": 30
        })
        
        # 2. 크롤링 수행
        crawled_files = []
        for i, result in enumerate(results):
            try:
                # 크롤링 수행
                file_path = crawling_web(result=result, output_dir=SNIPPET_DIR)
                if file_path and os.path.exists(file_path):
                    crawled_files.append({
                        "title": result.get("title", "제목 없음"),
                        "link": result.get("link", ""),
                        "file_path": file_path
                    })
                    
                # 진행률 업데이트 (30% ~ 70%)
                progress = 30 + int((i + 1) / len(results) * 40)
                task_status[task_id].update({
                    "message": f"웹 페이지 크롤링 중... ({i+1}/{len(results)})",
                    "progress": progress
                })
            except Exception as e:
                logger.error(f"크롤링 중 오류 발생 ({result.get('link', '')}): {str(e)}")
                # 오류가 발생해도 계속 진행
        
        if not crawled_files:
            task_status[task_id].update({
                "status": "completed",
                "message": "크롤링된 파일이 없습니다",
                "progress": 100,
                "result": {"summary": "크롤링된 파일이 없습니다", "sources": []}
            })
            return
        
        # 일시 중지 확인
        if await check_pause():
            return
            
        # 상태 업데이트: 요약 시작
        task_status[task_id].update({
            "status": "running",
            "message": "크롤링된 내용 요약 중...",
            "progress": 70
        })
        
        # 3. 요약 수행
        summaries = []
        sources = []
        
        # 필요한 모듈 임포트
        try:
            from first_summary_no_llm import summarize_markdown_file
            logger.info("요약 모듈 임포트 성공")
        except ImportError as e:
            logger.error(f"모듈 임포트 실패: {e}")
            task_status[task_id].update({
                "status": "failed",
                "message": f"요약 모듈 로드 실패: {str(e)}",
                "progress": 100,
                "error": str(e)
            })
            return
        
        for i, file_info in enumerate(crawled_files):
            try:
                # 파일 요약
                summary = summarize_markdown_file(file_info["file_path"], ratio=0.3)
                
                if summary and summary != "요약할 텍스트가 없습니다.":
                    summaries.append(summary)
                    sources.append({
                        "title": file_info["title"],
                        "link": file_info["link"],
                        "summary": summary[:200] + "..." if len(summary) > 200 else summary
                    })
                
                # 진행률 업데이트 (70% ~ 90%)
                progress = 70 + int((i + 1) / len(crawled_files) * 20)
                task_status[task_id].update({
                    "message": f"요약 중... ({i+1}/{len(crawled_files)})",
                    "progress": progress
                })
            except Exception as e:
                logger.error(f"요약 중 오류 발생 ({file_info['file_path']}): {str(e)}")
                # 오류가 발생해도 계속 진행
        
        # 4. 최종 결과 생성
        if not summaries:
            final_summary = "요약할 내용이 없습니다."
        else:
            # 모든 요약을 하나로 합침
            final_summary = f"# '{query}'에 대한 검색 결과 요약\n\n"
            for i, summary in enumerate(summaries):
                final_summary += f"## 출처 {i+1}: {sources[i]['title']}\n\n{summary}\n\n"
        
        # 결과 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_file = os.path.join(CLEAN_MD_DIR, f"summary_{timestamp}.md")
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(final_summary)
        
        # 상태 업데이트: 완료
        task_status[task_id].update({
            "status": "completed",
            "message": "요약이 완료되었습니다",
            "progress": 100,
            "result": {
                "summary": final_summary,
                "sources": sources,
                "result_file": result_file
            }
        })
        
    except Exception as e:
        logger.error(f"작업 처리 중 오류 발생: {str(e)}", exc_info=True)
        task_status[task_id].update({
            "status": "failed",
            "message": f"오류 발생: {str(e)}",
            "progress": 100,
            "error": str(e)
        })
        