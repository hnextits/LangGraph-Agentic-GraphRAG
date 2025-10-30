from fastapi import APIRouter, HTTPException, File, UploadFile, BackgroundTasks, Request, Body, Query
from typing import List, Dict, Any, Optional, Set
import os
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

# skill.search 모듈에서 필요한 함수 임포트
try:
    from skill.search.pipeline import search_google as perform_search
    from skill.search.util import sanitize_filename, crawling_web
    logger.info("skill.search 모듈을 성공적으로 가져왔습니다.")
except ImportError as e:
    logger.error(f"skill.search 모듈 가져오기 실패: {e}", exc_info=True)
    perform_search = None
    sanitize_filename = lambda x: x  # 폴백 함수
    crawling_web = None

# summarizer 모듈 임포트
try:
    from skill.search.summarizer import AnswerGenerator
    logger.info("AnswerGenerator 모듈 임포트 성공 (skill.search.summarizer)")
except ImportError as e:
    logger.error(f"AnswerGenerator 모듈 임포트 실패: {e}")
    AnswerGenerator = None

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
OCR_RESULTS_DIR = NEXTITS_DATA_DIR / "Results" / "3.OCR_results"
OCR_DIR = NEXTITS_DATA_DIR / "Results" / "2.OCR"  # 원본 텍스트 저장 경로
PROCESSED_DIR = NEXTITS_DATA_DIR / "Results" / "4.processed"  # 처리 결과 저장 경로
STT_TEXT_DIR = NEXTITS_DATA_DIR / "Results" / "7.stt"
SUMMARIZE_DIR = NEXTITS_DATA_DIR / "Results" / "6.summarize"
CRAWLING_DIR = BASE_DIR / "search_data" / "crawling"
SNIPPET_DIR = CRAWLING_DIR / "4.snippet"
CLEAN_MD_DIR = CRAWLING_DIR / "6.clean_md"

# --- 디렉터리 생성 ---
for dir_path in [
    DOC_DIR,
    OCR_RESULTS_DIR,
    OCR_DIR,
    PROCESSED_DIR,
    SUMMARIZE_DIR,
    SNIPPET_DIR,
    CLEAN_MD_DIR,
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
                'message': '작업이 사용자에 의해 취소되었습니다.'
            })
            logger.info(f"[Task {task_id}] 작업이 취소 상태로 변경되었습니다.")
        return True
    return False

# --- 백그라운드 작업 함수 ---
def run_document_pipeline(task_id: str, title: str, link: str):
    """(검색 기반) 문서 추가 및 인덱싱 파이프라인"""
    logger.info(f"[{task_id}] 문서 파이프라인 시작: {title}")
    tasks[task_id]['status'] = 'processing'
    tasks[task_id]['message'] = '웹 페이지 크롤링 중...'
    try:
        if check_and_handle_pause(task_id): return
        file_path = crawling_web(result={'title': title, 'link': link}, output_dir=str(DOC_DIR))
        
        if not (isinstance(file_path, str) and os.path.exists(file_path)):
            raise ValueError(f"크롤링 실패 또는 유효하지 않은 파일 경로: {file_path}")

        # OCR_RESULTS_DIR에도 복사 (클릭 시 표시용)
        try:
            import shutil
            file_name = Path(file_path).name
            ocr_copy_path = OCR_RESULTS_DIR / file_name
            shutil.copy2(file_path, ocr_copy_path)
            logger.info(f"[{task_id}] 크롤링 결과를 OCR_RESULTS_DIR에 복사: {ocr_copy_path}")
        except Exception as copy_error:
            logger.warning(f"[{task_id}] OCR_RESULTS_DIR 복사 실패 (계속 진행): {copy_error}")

        tasks[task_id]['message'] = '문서 청킹 및 인덱싱 중...'
        if check_and_handle_pause(task_id): return
        
        original_cwd, original_sys_path, original_argv = os.getcwd(), list(sys.path), sys.argv
        try:
            notebooklm_path = str(BASE_DIR)
            sys.path.insert(0, notebooklm_path)
            os.chdir(notebooklm_path)
            
            from notebooklm.qwen3_late_chunking import main as chunking_main
            # API에서 호출할 때는 인자를 직접 전달
            chunking_main(input_file=file_path, recreate_schema=False, search_mode=False)
            
            # TextSearcher는 Weaviate를 사용하므로 별도 index_path 불필요
            # from notebooklm.rag_text.text_search import TextSearcher
            # TextSearcher는 이미 chunking_main에서 Weaviate에 인덱싱됨
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
    """텍스트 인덱싱 실행 함수 - 3.OCR_results에서만 검색"""
    logger.info(f"[{task_id}] 텍스트 인덱싱 시작: {file_path}")
    tasks[task_id]['status'] = 'indexing'
    tasks[task_id]['message'] = '텍스트 인덱싱 중...'
    try:
        if check_and_handle_pause(task_id): return
        base_name = Path(file_path).stem
        
        # 3.OCR_results에서만 검색
        md_file_path = OCR_RESULTS_DIR / f"{base_name}.md"

        if not md_file_path.exists():
            raise FileNotFoundError(
                f"3.OCR_results에서 파일을 찾을 수 없습니다: {md_file_path}"
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
            'message': '파일 처리 및 인덱싱 완료'
        })
        logger.info(f"[{task_id}] 텍스트 인덱싱 성공")
    except Exception as e:
        logger.error(f"[{task_id}] 텍스트 인덱싱 실패: {e}", exc_info=True)
        tasks[task_id].update({'status': 'index_failed', 'error': str(e)})

def run_processing_pipeline(task_id: str, file_path: str):
    """(업로드된 파일) 처리 및 인덱싱 파이프라인"""
    logger.info(f"[{task_id}] 파일 처리 파이프라인 시작: {file_path}")
    tasks[task_id]['status'] = 'processing'
    tasks[task_id]['message'] = '파일 처리 스크립트 실행 중...'
    try:
        if check_and_handle_pause(task_id): return
        script_path = NEXTITS_DATA_DIR / "pipe" / "run_file_processor.py"
        if not script_path.exists():
            raise FileNotFoundError(f"처리 스크립트를 찾을 수 없습니다: {script_path}")

        command = [sys.executable, str(script_path), "--file", file_path]
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8')

        if result.returncode == 0:
            logger.info(f"[{task_id}] 스크립트 실행 성공, 텍스트 인덱싱 시작.")
            tasks[task_id]['status'] = 'processed'
            run_text_indexing(task_id, file_path)
        else:
            raise RuntimeError(f"스크립트 실행 실패:\n{result.stderr}")
    except Exception as e:
        logger.error(f"[{task_id}] 파일 처리 파이프라인 실패: {e}", exc_info=True)
        tasks[task_id].update({'status': 'failed', 'error': str(e)})


# 요약 생성기 인스턴스 (싱글톤으로 관리)
answer_generator = None

def get_answer_generator():
    global answer_generator
    if answer_generator is None:
        answer_generator = AnswerGenerator()
        logger.info("AnswerGenerator 인스턴스 생성 완료")
    return answer_generator


async def process_summarize_files(task_id: str, filenames: List[str]):
    """지정된 파일들을 찾아 내용을 요약하는 백그라운드 함수"""
    logger.info(f"[{task_id}] 파일 요약 작업 시작: {filenames}")
    tasks[task_id].update({"status": "running", "message": "요약할 파일을 찾는 중...", "progress": 10})

    try:
        summaries, sources = [], []
        
        # AnswerGenerator는 이미 상단에서 import됨
        if AnswerGenerator is None:
            tasks[task_id].update({"status": "failed", "error": "요약 모듈을 찾을 수 없습니다."})
            return

        for i, filename in enumerate(filenames):
            if await asyncio.to_thread(check_and_handle_pause, task_id): return
            
            progress = 10 + int((i / len(filenames)) * 80)
            tasks[task_id].update({"message": f"파일 처리 중... ({i+1}/{len(filenames)}): {filename}", "progress": progress})

            # 3.OCR_results에서만 파일 검색
            base_name = Path(filename).stem
            candidate_names = [filename, f"{base_name}.md"]
            
            file_to_summarize = None
            for name in candidate_names:
                file_path = OCR_RESULTS_DIR / name
                if file_path.exists():
                    file_to_summarize = file_path
                    break
            
            if file_to_summarize is None:
                logger.warning(f"[{task_id}] 3.OCR_results에서 파일을 찾을 수 없습니다: {filename}")
                continue

            try:
                # 파일 내용 읽기
                with open(file_to_summarize, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if not content or content.isspace():
                    logger.warning(f"[{task_id}] 파일에 요약할 텍스트가 없습니다: {filename}")
                    continue
                    
                # AnswerGenerator 인스턴스 생성 및 요약 생성
                generator = AnswerGenerator()
                summary = generator.generate_answer(content)
                
                # 메모리 정리
                generator.cleanup_model()
                
                if summary and summary != "(관련된 구글 검색 결과를 찾을 수 없습니다)":
                    summaries.append(summary)
                    sources.append({"filename": filename, "path": str(file_to_summarize)})
            except Exception as e:
                logger.warning(f"[{task_id}] 파일 요약 중 오류 ({filename}): {e}")

        if not summaries:
            tasks[task_id].update({"status": "completed", "message": "요약할 내용이 있는 파일을 찾지 못했습니다.", "progress": 100, "result": {"summary": "요약할 내용이 없습니다.", "sources": []}})
            return

        final_summary = "\n\n---\n\n".join(summaries)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 여러 파일 요약 시 파일명을 명확히 함
        safe_filenames_str = sanitize_filename("_".join(filenames))
        result_file = SUMMARIZE_DIR / f"summary_{timestamp}_{safe_filenames_str}.md"
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
    """검색, 크롤링, 요약 백그라운드 처리 함수"""
    logger.info(f"[{task_id}] 요약 작업 시작: '{query}'")
    try:
        task_status[task_id].update({"status": "running", "message": "구글 검색 중...", "progress": 10})
        if await asyncio.to_thread(check_and_handle_pause, task_id): return
        
        results = perform_search(query, 5, [])
                
        if not results:
            task_status[task_id].update({"status": "completed", "message": "검색 결과가 없습니다.", "progress": 100, "result": {"summary": "검색 결과가 없습니다.", "sources": []}})
            return
        
        # 중복 결과 제거
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
            if await asyncio.to_thread(check_and_handle_pause, task_id): return
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
        
        # AnswerGenerator는 이미 상단에서 import됨
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
            
        # 요약 작업 수행
        try:
            for i, file_info in enumerate(crawled_files):
                if await asyncio.to_thread(check_and_handle_pause, task_id): 
                    return
                    
                try:
                    # 파일 내용 읽기
                    with open(file_info["file_path"], 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if not content or content.isspace():
                        logger.warning(f"[{task_id}] 파일에 요약할 텍스트가 없습니다: {file_info['file_path']}")
                        continue
                        
                    # 요약 생성
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
            # 메모리 정리
            if 'generator' in locals():
                generator.cleanup_model()
                logger.info(f"[{task_id}] LLM 요약 모델 메모리 정리 완료")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_query = sanitize_filename(query)
        
        # 1. DOC_DIR에 저장 (기존 동작 유지)
        doc_file = DOC_DIR / f"summary_{timestamp}_{safe_query}.md"
        doc_file.write_text(final_summary, encoding="utf-8")
        logger.info(f"[{task_id}] 검색 결과를 DOC_DIR에 저장: {doc_file}")
        
        # 2. OCR_RESULTS_DIR에도 저장 (클릭 시 표시용)
        ocr_result_file = OCR_RESULTS_DIR / f"summary_{timestamp}_{safe_query}.md"
        ocr_result_file.write_text(final_summary, encoding="utf-8")
        logger.info(f"[{task_id}] 검색 결과를 OCR_RESULTS_DIR에 저장: {ocr_result_file}")
        
        # MD 파일을 임베딩하여 Weaviate에 저장 (DOC_DIR 파일 사용)
        task_status[task_id].update({"status": "running", "message": "검색 결과 임베딩 중...", "progress": 95})
        try:
            logger.info(f"[{task_id}] MD 파일 임베딩 시작: {doc_file}")
            from notebooklm.qwen3_late_chunking import main as chunking_main
            
            # 임베딩 처리
            chunking_main(input_file=str(doc_file), recreate_schema=False, search_mode=False)
            logger.info(f"[{task_id}] MD 파일 임베딩 완료")
        except Exception as e:
            logger.error(f"[{task_id}] MD 파일 임베딩 중 오류 발생: {e}", exc_info=True)
            # 임베딩 실패해도 요약 결과는 반환
        
        task_status[task_id].update({
            "status": "completed", "message": "요약이 완료되었습니다.", "progress": 100,
            "result": {"summary": final_summary, "sources": sources, "result_file": str(doc_file), "ocr_result_file": str(ocr_result_file)}
        })
        logger.info(f"[{task_id}] 요약 작업 완료. DOC: {doc_file}, OCR: {ocr_result_file}")
    except Exception as e:
        logger.error(f"[{task_id}] 요약 작업 파이프라인 실패: {e}", exc_info=True)
        task_status[task_id].update({"status": "failed", "message": f"오류 발생: {e}", "progress": 100, "error": str(e)})

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
@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_files(request_data: SummarizeRequest) -> SummarizeResponse:
    # 요청 본문에서 file_names 추출
    file_names = request_data.filenames
    """
    선택된 파일들을 요약하는 API 엔드포인트
    """
    logger.info(f"요약 요청 받음: {file_names}")
    
    try:
        # AnswerGenerator 인스턴스 가져오기
        generator = get_answer_generator()
        
        # DOC_DIR 존재 여부 확인
        if not os.path.exists(DOC_DIR):
            logger.error(f"문서 디렉토리가 존재하지 않습니다: {DOC_DIR}")
            raise HTTPException(status_code=404, detail=f"문서 디렉토리가 존재하지 않습니다: {DOC_DIR}")
            
        # 파일 내용 수집 (개선된 파일 검색)
        file_contents = []
        missing_files = []
        
        # DOC_DIR과 OCR_RESULTS_DIR에서 파일 찾기
        search_dirs = [DOC_DIR, OCR_RESULTS_DIR]
        available_files = {}
        for search_dir in search_dirs:
            if os.path.exists(search_dir):
                for f in os.listdir(search_dir):
                    file_full_path = os.path.join(search_dir, f)
                    if os.path.isfile(file_full_path):
                        # 파일명을 키로, 전체 경로를 값으로 저장 (중복 시 덮어쓰기)
                        available_files[f] = file_full_path
        
        logger.info(f"검색 가능한 파일 수: {len(available_files)}")
        
        for file_name in file_names:
            file_path = available_files.get(file_name)
            found = False
            
            # 1. 정확한 파일명으로 검색
            if file_path and os.path.exists(file_path):
                found = True
                logger.info(f"파일 찾음: {file_name} -> {file_path}")
            else:
                # 2. 파일명 정규화하여 검색 (공백, 특수문자 처리)
                normalized_name = file_name.strip()
                for available_file, available_path in available_files.items():
                    if available_file == normalized_name or available_file.strip() == normalized_name:
                        file_path = available_path
                        found = True
                        logger.info(f"정규화된 파일명으로 찾음: {file_name} -> {available_file}")
                        break
                
                # 3. 확장자 없이 검색
                if not found:
                    base_name = os.path.splitext(file_name)[0]
                    for available_file, available_path in available_files.items():
                        if os.path.splitext(available_file)[0] == base_name:
                            file_path = available_path
                            found = True
                            logger.info(f"확장자 없이 찾음: {file_name} -> {available_file}")
                            break
            
            if not found:
                logger.warning(f"파일을 찾을 수 없음: {file_name}")
                logger.debug(f"사용 가능한 파일 목록 (처음 10개): {list(available_files.keys())[:10]}")
                missing_files.append(file_name)
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    file_contents.append({
                        "title": file_name,
                        "content": content
                    })
                logger.info(f"파일 로드 성공: {file_name}")
            except Exception as e:
                logger.error(f"파일 읽기 오류 ({file_name}): {str(e)}")
        
        if not file_contents:
            if missing_files:
                raise HTTPException(status_code=404, detail=f"요청한 파일을 찾을 수 없습니다: {', '.join(missing_files)}")
            else:
                raise HTTPException(status_code=404, detail="유효한 파일을 찾을 수 없습니다")
        
        # 임시 저장 디렉토리 설정
        temp_dir = os.path.join(parent_dir, 'nextits_data', 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        
        # 파일 내용을 make_llm_input_data에 맞는 형식으로 변환
        formatted_data = []
        for item in file_contents:
            formatted_data.append({
                "link": item["title"],  # 파일명을 링크로 사용
                "data": item["content"],  # 파일 내용을 데이터로 사용
                "google_snipping": ""  # 빈 스니핑
            })
        
        # make_llm_input_data 호출하여 입력 데이터 생성
        processed_data = generator.make_llm_input_data(temp_dir, formatted_data)
        
        # processed_data는 리스트이므로 문자열로 변환
        combined_content = ""
        for item in processed_data:
            link = item.get('link', '')
            data = item.get('data', '')
            if data:
                combined_content += f"\n\n## 출처: {link}\n\n{data}\n"
        
        # generate_answer 호출하여 요약 생성 (내부에서 자동으로 청킹 처리)
        summary = generator.generate_answer(combined_content)
        
        # 요약 결과 저장 디렉토리 설정
        summary_dir = os.path.join(parent_dir, 'nextits_data', 'Results', '6.summarize')
        os.makedirs(summary_dir, exist_ok=True)

        # 타임스탬프 기반 파일명 생성
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        summary_filename = f"summary_{file_name}.md"
        summary_path = os.path.join(summary_dir, summary_filename)

        # 요약 결과를 마크다운 파일로 저장
        with open(summary_path, "w", encoding="utf-8") as f:
            # 헤더 정보 추가
            f.write(summary)

        # API 응답에 파일 경로 추가
        return {
            "summary": summary,
            "files": file_names,
            "timestamp": timestamp,
            "summary_file": summary_path  # 저장된 파일 경로 추가
        }
        
    except Exception as e:
        logger.error(f"요약 생성 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"요약 생성 중 오류 발생: {str(e)}")


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

        extra_files = [
            OCR_DIR / f"{filename}.txt",
            STT_TEXT_DIR / f"{Path(filename).stem}.md",
            OCR_RESULTS_DIR / f"{Path(filename).stem}.md",
        ]

        for extra_file in extra_files:
            if extra_file.exists():
                try:
                    extra_file.unlink()
                except Exception as e:
                    logger.warning("추가 파일 삭제 중 오류 발생 (%s): %s", extra_file, e)

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
    """3.OCR_results 디렉토리에서만 파일을 검색합니다."""
    base_name = Path(filename).stem
    candidate_names = [filename, f"{base_name}.md"]

    logger.info(f"파일 내용 조회 요청: {filename}, base_name: {base_name}")

    # 3.OCR_results에서만 검색
    existing_path = None
    for name in candidate_names:
        file_path = OCR_RESULTS_DIR / name
        if file_path.is_file():
            existing_path = file_path
            logger.info(f"3.OCR_results에서 파일 발견: {existing_path}")
            break

    if existing_path is None:
        logger.warning(f"3.OCR_results에서 파일을 찾을 수 없음: {filename}")
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

    rag_pipeline = getattr(request.app.state, 'rag_pipeline', None)
    if rag_pipeline is None:
        raise HTTPException(status_code=503, detail="RAG 파이프라인을 사용할 수 없습니다.")

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
