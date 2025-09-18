from fastapi import APIRouter, HTTPException, File, UploadFile, BackgroundTasks, Request, Body
from typing import List, Dict, Any, Optional
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
from pathlib import Path
from datetime import datetime
import asyncio

# --- 필요한 모듈 임포트 (프로젝트 구조에 맞게 설정) ---
from api.pause_api import is_cancelled, cancel_task
from services.rag_service import get_rag_response
from search_test.crawler_pipeline import crawling_web, sanitize_filename

# --- 로거 및 라우터 설정 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

# --- 모듈 동적 로드 ---
try:
    backend_dir = Path(__file__).resolve().parent.parent
    search_test_dir = backend_dir / 'search_test'
    sys.path.append(str(search_test_dir))
    from crawler_pipeline import search as perform_search
    logger.info("crawler_pipeline 모듈을 성공적으로 가져왔습니다.")
except ImportError:
    logger.error("crawler_pipeline 모듈 가져오기 실패", exc_info=True)
    perform_search = None

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

# crawler_summary_llm 모듈 임포트
try:
    from crawler_summary_llm import AnswerGenerator
    logger.info("AnswerGenerator 모듈 임포트 성공")
except ImportError as e:
    logger.error(f"AnswerGenerator 모듈 임포트 실패: {e}")
    raise

# --- 작업 상태 관리 ---
tasks: Dict[str, Dict[str, Any]] = {}

# --- Pydantic 모델 정의 ---
class RootResponse(BaseModel): message: str
class SearchQuery(BaseModel): query: str
class SearchResponse(BaseModel): results: List[Dict[str, Any]]
class AddDocumentRequest(BaseModel): title: str; link: str
class TaskCreationResponse(BaseModel): task_id: str; status: str
class UploadResponse(BaseModel): message: str; files: List[Dict[str, Any]]
class FileListResponse(BaseModel): files: List[str]
class FileContentResponse(BaseModel): filename: str; content: str
class DeleteFilesRequest(BaseModel): filenames: List[str]
class DeleteFilesResponse(BaseModel): message: str; deleted_files: List[str]; failed_files: List[Dict[str, str]]
class ChatQuery(BaseModel): query: str; sources: List[str] = []
class ChatResponse(BaseModel): 
    task_id: Optional[str] = None
    answer: str
    images: List[str]
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
SUMMARIZE_DIR = NEXTITS_DATA_DIR / "Results" / "6.summarize"
CRAWLING_DIR = BASE_DIR / "search_test" / "Crawling_data"
SNIPPET_DIR = CRAWLING_DIR / "4.snippet"
CLEAN_MD_DIR = CRAWLING_DIR / "6.clean_md"

# --- 디렉터리 생성 ---
for dir_path in [DOC_DIR, OCR_RESULTS_DIR, SUMMARIZE_DIR, SNIPPET_DIR, CLEAN_MD_DIR]:
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

        tasks[task_id]['message'] = '문서 청킹 및 인덱싱 중...'
        if check_and_handle_pause(task_id): return
        
        original_cwd, original_sys_path, original_argv = os.getcwd(), list(sys.path), sys.argv
        try:
            notebooklm_path = str(BASE_DIR)
            sys.path.insert(0, notebooklm_path)
            os.chdir(notebooklm_path)
            
            from notebooklm.qwen3_late_chunking import main as chunking_main
            index_path = str(BASE_DIR / 'notebooklm' / 'faiss_test' / 'text_index.faiss')
            sys.argv = ['qwen3_late_chunking.py', '--input-file', file_path, '--index-path', index_path]
            chunking_main()
            
            from notebooklm.rag_text.text_search import TextSearcher
            TextSearcher(index_path=str(Path(index_path).parent))
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

def run_text_indexing(task_id: str, file_path: str):
    """텍스트 인덱싱 실행 함수"""
    logger.info(f"[{task_id}] 텍스트 인덱싱 시작: {file_path}")
    tasks[task_id]['status'] = 'indexing'
    tasks[task_id]['message'] = '텍스트 인덱싱 중...'
    try:
        if check_and_handle_pause(task_id): return
        base_name = Path(file_path).stem
        md_file_path = OCR_RESULTS_DIR / f"{base_name}.md"
        
        if not md_file_path.exists():
            raise FileNotFoundError(f"OCR 결과 파일(.md)을 찾을 수 없습니다: {md_file_path}")

        original_cwd, original_sys_path, original_argv = os.getcwd(), list(sys.path), sys.argv
        try:
            notebooklm_path = str(BASE_DIR)
            sys.path.insert(0, notebooklm_path)
            os.chdir(notebooklm_path)

            from notebooklm.qwen3_late_chunking import main as chunking_main
            index_path = str(BASE_DIR / 'notebooklm' / 'faiss_test' / 'text_index.faiss')
            sys.argv = ['qwen3_late_chunking.py', '--input-file', str(md_file_path), '--index-path', index_path]
            chunking_main()
            
            from notebooklm.rag_text.text_search import TextSearcher
            TextSearcher(index_path=str(Path(index_path).parent))
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
        
        try:
            from search_test.crawler_summary_llm import AnswerGenerator
        except ImportError:
            tasks[task_id].update({"status": "failed", "error": "요약 모듈(first_summary_no_llm)을 찾을 수 없습니다."})
            return

        for i, filename in enumerate(filenames):
            if await asyncio.to_thread(check_and_handle_pause, task_id): return
            
            progress = 10 + int((i / len(filenames)) * 80)
            tasks[task_id].update({"message": f"파일 처리 중... ({i+1}/{len(filenames)}): {filename}", "progress": progress})

            # OCR 처리된 .md 파일을 우선적으로 찾음
            base_name = Path(filename).stem
            file_to_summarize = OCR_RESULTS_DIR / f"{base_name}.md"

            # .md 파일이 없으면 원본 파일 디렉토리(DOC_DIR)에서 찾아봄
            if not file_to_summarize.exists():
                file_to_summarize = DOC_DIR / filename
            
            if not file_to_summarize.exists():
                logger.warning(f"[{task_id}] 요약할 파일을 찾을 수 없습니다: {filename}")
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
        
        # 필요한 모듈 임포트
        try:
            from search_test.crawler_summary_llm import AnswerGenerator
            logger.info("LLM 요약 모듈 임포트 성공")
            generator = AnswerGenerator()
        except ImportError as e:
            logger.error(f"LLM 요약 모듈 임포트 실패: {e}")
            tasks[task_id].update({
                "status": "failed",
                "message": f"LLM 요약 모듈 로드 실패: {str(e)}",
                "progress": 100,
                "error": str(e)
            })
            return
            
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
        result_file = CLEAN_MD_DIR / f"summary_{timestamp}_{sanitize_filename(query)}.md"
        result_file.write_text(final_summary, encoding="utf-8")
        
        task_status[task_id].update({
            "status": "completed", "message": "요약이 완료되었습니다.", "progress": 100,
            "result": {"summary": final_summary, "sources": sources, "result_file": str(result_file)}
        })
        logger.info(f"[{task_id}] 요약 작업 완료. 파일: {result_file}")
    except Exception as e:
        logger.error(f"[{task_id}] 요약 작업 파이프라인 실패: {e}", exc_info=True)
        task_status[task_id].update({"status": "failed", "message": f"오류 발생: {e}", "progress": 100, "error": str(e)})

# --- API 엔드포인트 구현 ---

# 작업 상태를 확인하는 API
@router.get("/tasks/{task_id}", response_model=TaskStatusResponse, tags=["Task Management"])
async def get_task_status(task_id: str) -> TaskStatusResponse:
    # tasks와 task_status 두 딕셔너리 모두 확인
    if task_id in tasks:
        return TaskStatusResponse(**tasks[task_id])
    elif task_id in task_status:
        return TaskStatusResponse(**task_status[task_id])
    else:
        raise HTTPException(status_code=404, detail=f"작업 ID {task_id}를 찾을 수 없습니다.")

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
        
        # OCR 결과 디렉토리 존재 여부 확인
        if not os.path.exists(OCR_RESULTS_DIR):
            logger.error(f"OCR 결과 디렉토리가 존재하지 않습니다: {OCR_RESULTS_DIR}")
            raise HTTPException(status_code=404, detail=f"OCR 결과 디렉토리가 존재하지 않습니다: {OCR_RESULTS_DIR}")
            
        # OCR 결과 디렉토리가 비어있는지 확인
        if not os.listdir(OCR_RESULTS_DIR):
            logger.error(f"OCR 결과 디렉토리가 비어 있습니다: {OCR_RESULTS_DIR}")
            raise HTTPException(status_code=404, detail=f"OCR 결과 디렉토리가 비어 있습니다. OCR 처리가 완료되었는지 확인하세요.")
            
        # 파일 내용 수집
        file_contents = []
        missing_files = []
        for file_name in file_names:
            file_path = os.path.join(OCR_RESULTS_DIR, file_name)
            if not os.path.exists(file_path):
                logger.warning(f"파일을 찾을 수 없음: {file_path}")
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
        
        # generate_answer 호출하여 요약 생성
        summary = generator.generate_answer(processed_data)
        
        # 요약 결과 저장 디렉토리 설정
        summary_dir = os.path.join(parent_dir, 'nextits_data', 'Results', '6.summarize')
        os.makedirs(summary_dir, exist_ok=True)

        # 타임스탬프 기반 파일명 생성
        timestamp = generator.get_timestamp().replace(" ", "_").replace(":", "-")
        summary_filename = f"summary_{file_name}.md"
        summary_path = os.path.join(summary_dir, summary_filename)

        # 요약 결과를 마크다운 파일로 저장
        with open(summary_path, "w", encoding="utf-8") as f:
            # 헤더 정보 추가
            f.write(f"# 요약 결과 ({generator.get_timestamp()})\n\n")
            f.write(f"## 요약 대상 파일\n")
            for file_name in file_names:
                f.write(f"- {file_name}\n")
            f.write("\n## 요약 내용\n\n")
            f.write(summary)

        # API 응답에 파일 경로 추가
        return {
            "summary": summary,
            "files": file_names,
            "timestamp": generator.get_timestamp(),
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
    return {"files": files}

# 원본 파일이 처리된 후의 텍스트(OCR) 내용을 조회하는 API
@router.get("/files/{filename}", response_model=FileContentResponse, tags=["Document Management"])
async def get_ocr_file_content(filename: str) -> FileContentResponse:
    base_name = Path(filename).stem
    file_path = OCR_RESULTS_DIR / f"{base_name}.md"
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"처리된 파일을 찾을 수 없습니다: {file_path.name}")
    content = file_path.read_text(encoding="utf-8")
    return {"filename": file_path.name, "content": content}

# 업로드된 파일을 삭제하는 API
@router.delete("/files", response_model=DeleteFilesResponse, tags=["Document Management"])
async def delete_doc_files(req: DeleteFilesRequest) -> DeleteFilesResponse:
    deleted, failed = [], []
    for filename in req.filenames:
        file_path = DOC_DIR / filename
        try:
            if file_path.is_file():
                file_path.unlink()
                deleted.append(filename)
            else:
                failed.append({"filename": filename, "reason": "파일을 찾을 수 없음"})
        except Exception as e:
            logger.error(f"Doc 파일 삭제 오류 ('{filename}'): {e}", exc_info=True)
            failed.append({"filename": filename, "reason": str(e)})
    return {
        "message": f"Doc 파일 {len(deleted)}개 삭제 성공, {len(failed)}개 실패.",
        "deleted_files": deleted,
        "failed_files": failed
    }

# -- 기타 API --
# RAG 챗봇에 질문하고 답변을 받는 API
@router.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(query: ChatQuery, request: Request) -> ChatResponse:
    task_id = str(uuid.uuid4())
    cancellation_event = threading.Event()
    request.app.state.running_tasks[task_id] = cancellation_event
    logger.info(f"[Task {task_id}] 채팅 작업 시작: '{query.query}'")

    try:
        rag_pipeline = getattr(request.app.state, 'rag_pipeline', None)
        if not rag_pipeline:
            raise HTTPException(status_code=503, detail="RAG 파이프라인을 사용할 수 없습니다.")

        response = await asyncio.to_thread(
            get_rag_response, 
            query.query, 
            query.sources, 
            rag_pipeline,
            cancellation_event
        )
        
        logger.info(f"[Task {task_id}] 채팅 작업 완료.")
        return ChatResponse(task_id=task_id, **response)

    except Exception as e:
        # InterruptedError는 service 계층에서 처리되므로 여기서는 일반 예외만 처리
        logger.error(f"[Task {task_id}] 채팅 처리 중 예상치 못한 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # 작업 완료 후 딕셔너리에서 제거
        if task_id in request.app.state.running_tasks:
            del request.app.state.running_tasks[task_id]
            logger.info(f"[Task {task_id}] 작업 상태 제거 완료.")

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
