import os
import sys
import importlib.util
import logging
import threading
from typing import Optional, Dict, Any, List, Set
import re
from utils.helpers import process_response_with_images, encode_image_to_base64

logger = logging.getLogger(__name__)

def _load_rag_module():
    """notebooklm 경로를 sys.path에 추가하고 RAGPipeline 클래스를 반환."""
    current_file_path = os.path.abspath(__file__)
    backend_dir = os.path.dirname(os.path.dirname(current_file_path))
    rag_path = os.path.join(backend_dir, "notebooklm")

    if not os.path.isdir(rag_path):
        raise FileNotFoundError(f"RAG 파이프라인 디렉터리를 찾을 수 없습니다: {rag_path}")

    original_cwd = os.getcwd()
    original_sys_path = list(sys.path)
    original_config_module = sys.modules.get("config")

    try:
        if "config" in sys.modules:
            del sys.modules["config"]

        sys.path.insert(0, rag_path)
        os.chdir(rag_path)

        from rag_pipeline import RAGPipeline  # pylint: disable=import-error

        return RAGPipeline
    finally:
        os.chdir(original_cwd)
        sys.path = original_sys_path

        if "config" in sys.modules:
            del sys.modules["config"]
        if original_config_module:
            sys.modules["config"] = original_config_module


def initialize_rag_pipeline():
    """애플리케이션 시작 시 RAG 파이프라인을 초기화하고 인스턴스를 반환합니다."""
    logger.info("RAG 파이프라인 초기화를 시작합니다...")
    try:
        pipeline_cls = _load_rag_module()
        return pipeline_cls()
    except Exception as e:
        logger.error(f"RAG 파이프라인 초기화 중 예외 발생: {e}", exc_info=True)
        return None

def build_rag_pipeline():
    """LazyModelManager용 RAGPipeline 빌더."""
    logger.info("Lazy builder를 통해 RAG 파이프라인을 생성합니다.")
    try:
        pipeline_cls = _load_rag_module()
        return pipeline_cls()
    except Exception:
        logger.exception("RAG 파이프라인 빌드 실패")
        raise


def cleanup_rag_pipeline(pipeline):
    """RAGPipeline 인스턴스 정리를 수행합니다."""
    logger.info("RAG 파이프라인 리소스를 정리합니다.")

    try:
        cleanup_fn = getattr(pipeline, "cleanup", None)
        if callable(cleanup_fn):
            cleanup_fn()
        else:
            generator = getattr(pipeline, "generator", None)
            if generator and hasattr(generator, "cleanup_model"):
                generator.cleanup_model()

            refiner = getattr(pipeline, "refiner", None)
            if refiner and hasattr(refiner, "cleanup_model"):
                refiner.cleanup_model()
            router = getattr(pipeline, "router", None)
            if router and hasattr(router, "cleanup"):
                router.cleanup()
    except Exception:
        logger.exception("RAG 파이프라인 정리 중 오류 발생")

def process_markdown_tables(text):
    """
    마크다운 테이블의 줄바꿈 문제를 해결하는 함수입니다.
    테이블 내의 줄바꿈을 HTML <br> 태그로 변환하여 표시합니다.
    """
    # 마크다운 테이블 패턴 정의
    table_pattern = re.compile(r'(\|[^\n]*\|\n)(\|\s*[-:]+[-\s:]*\|\n)((\|[^\n]*\|\n)+)', re.MULTILINE)
    
    def process_table(match):
        header = match.group(1)  # 테이블 헤더 행
        separator = match.group(2)  # 구분선
        body = match.group(3)  # 테이블 본문
        
        # 테이블 본문의 각 행 처리
        rows = body.split('\n')
        processed_rows = []
        
        for row in rows:
            if not row.strip():  # 빈 행 건너뛰기
                continue
                
            # 행을 셀로 분리
            cells = row.split('|')
            processed_cells = []
            
            for cell in cells:
                # 셀 내용의 줄바꿈을 <br>로 변환
                processed_cell = cell.replace('\n', '<br>')
                processed_cells.append(processed_cell)
            
            processed_rows.append('|'.join(processed_cells))
        
        # 처리된 테이블 재구성
        return header + separator + '\n'.join(processed_rows)
    
    # 마크다운 테이블 패턴을 찾아 처리
    processed_text = table_pattern.sub(process_table, text)
    
    # 위 패턴으로 처리되지 않은 테이블을 위한 백업 처리 방법
    # 테이블 행을 식별하는 정규식
    table_row_pattern = re.compile(r'^\s*\|(.+?)\|\s*$', re.MULTILINE)
    
    # 텍스트를 줄 단위로 분리
    lines = processed_text.split('\n')
    result_lines = []
    in_table = False
    table_header = None
    table_separator = None
    table_rows = []
    
    for i, line in enumerate(lines):
        # 테이블 행인지 확인
        is_table_row = bool(table_row_pattern.match(line))
        
        # 테이블 구분선인지 확인 (|---|---|
        is_separator = is_table_row and bool(re.search(r'\|\s*[-:]+\s*\|', line))
        
        # 테이블 시작 감지
        if is_table_row and not in_table:
            in_table = True
            table_header = line
            result_lines.append(line)
            continue
        
        # 테이블 구분선 감지
        if in_table and is_separator and table_header and not table_separator:
            table_separator = line
            result_lines.append(line)
            continue
        
        # 테이블 데이터 행 감지
        if in_table and is_table_row and table_header and table_separator:
            # 셀 내용의 줄바꿈을 <br>로 변환
            cells = line.split('|')
            processed_cells = []
            
            for cell in cells:
                processed_cell = cell.replace('\n', '<br>')
                processed_cells.append(processed_cell)
            
            result_lines.append('|'.join(processed_cells))
            continue
        
        # 테이블 종료 감지
        if in_table and not is_table_row:
            in_table = False
            table_header = None
            table_separator = None
        
        # 테이블이 아닌 경우 그대로 추가
        result_lines.append(line)
    
    return '\n'.join(result_lines)

def run_rag_in_background(
    task_id: str,
    query: str,
    sources: List[str],
    source_filter_requested: bool,
    rag_pipeline,
    cancellation_event: threading.Event,
    tasks_dict: Dict[str, Any],
    running_tasks_dict: Dict[str, Any],
    app_state: Any,  # app.state를 직접 받음
    session_id: Optional[str] = None,
    model_manager=None,
):
    """백그라운드에서 RAG 파이프라인을 실행하고 결과를 app_state에 저장합니다."""
    import time

    # app.state에서 캐시 관련 딕셔너리를 가져옵니다.
    task_cache = app_state.task_cache
    task_cache_timestamps = app_state.task_cache_timestamps

    tasks_dict[task_id].update({"status": "processing", "message": "RAG 파이프라인 로딩 중..."})
    logger.info(f"[Task {task_id}] Session ID for RAG: {session_id}")

    # rag_pipeline이 None이면 백그라운드에서 acquire + load_engine 수행
    _acquired_here = False
    if rag_pipeline is None and model_manager is not None:
        try:
            rag_pipeline = model_manager.acquire("rag_pipeline")
            _acquired_here = True
            if hasattr(rag_pipeline, "load_engine_sync"):
                rag_pipeline.load_engine_sync()
            tasks_dict[task_id].update({"message": "RAG 파이프라인 실행 중..."})
        except Exception as e:
            logger.error(f"[Task {task_id}] RAG 파이프라인 acquire/load 실패: {e}", exc_info=True)
            final_status = {
                "status": "failed",
                "message": "RAG 파이프라인을 로드할 수 없습니다.",
                "error": str(e)
            }
            tasks_dict[task_id].update(final_status)
            task_cache[task_id] = tasks_dict[task_id].copy()
            task_cache_timestamps[task_id] = time.time()
            if _acquired_here and model_manager:
                try:
                    model_manager.release("rag_pipeline")
                except Exception:
                    pass
            return

    try:
        response_data = get_rag_response(
            query,
            sources,
            rag_pipeline,
            cancellation_event,
            source_filter_requested=source_filter_requested,
            session_id=session_id,  # 세션 ID 전달
        )
        final_status = {
            "status": "completed",
            "message": "채팅 작업이 완료되었습니다.",
            "result": response_data
        }
        tasks_dict[task_id].update(final_status)
        
        # 작업 완료 시 캐시에 저장
        task_cache[task_id] = tasks_dict[task_id].copy()
        task_cache_timestamps[task_id] = time.time()
        logger.info(f"[Task {task_id}] 작업 상태를 캐시에 저장했습니다.")

    except Exception as e:
        logger.error(f"[Task {task_id}] 백그라운드 RAG 작업 중 오류: {e}", exc_info=True)
        final_status = {
            "status": "failed",
            "message": "오류가 발생했습니다.",
            "error": str(e)
        }
        tasks_dict[task_id].update(final_status)

        # 작업 실패 시에도 캐시에 저장
        task_cache[task_id] = tasks_dict[task_id].copy()
        task_cache_timestamps[task_id] = time.time()
        logger.info(f"[Task {task_id}] 실패한 작업 상태를 캐시에 저장했습니다.")
            
    finally:
        # running_tasks에서 해당 task 정리
        if task_id in running_tasks_dict:
            del running_tasks_dict[task_id]
            logger.info(f"[Task {task_id}] running_tasks에서 제거 완료.")
        # 백그라운드 작업 완료 후 rag_pipeline release (idle 타이머 시작)
        if model_manager:
            try:
                model_manager.release("rag_pipeline")
            except Exception:
                logger.exception(f"[Task {task_id}] rag_pipeline release 실패")

def _filter_results_by_uuid(results: List[Dict[str, Any]], allowed_uuids: Set[str]) -> List[Dict[str, Any]]:
    """주어진 document_uuid 집합에 속하는 결과만 필터링합니다."""
    if not results or not allowed_uuids:
        return [] if allowed_uuids else results

    filtered = [item for item in results if item.get('document_uuid') in allowed_uuids]

    if not filtered:
        logger.info("document_uuid 필터링 후 결과가 없습니다.")
        return []

    logger.info("document_uuid 필터링 적용: %d -> %d", len(results), len(filtered))
    return filtered


def get_rag_response(
    query: str,
    sources: List[str],
    rag_pipeline,
    cancellation_event: Optional[threading.Event] = None,
    source_filter_requested: bool = False,
    session_id: Optional[str] = None,  # 세션 ID 추가
) -> Dict[str, Any]:
    """
    사용자 질문과 소스 정보를 받아 RAG 파이프라인을 통해 답변과 이미지를 생성합니다.
    """
    try:
        # RAG 파이프라인 실행 (취소 이벤트 전달)
        allowed_uuids: Set[str] = {src for src in sources if src}
        

        if source_filter_requested and not allowed_uuids:
            logger.warning(
                "소스 필터링을 요청했지만 document_uuid를 확인하지 못했습니다. 원본 소스: %s",
                sources,
            )

        results = rag_pipeline.process_query(
            query=query,
            top_k=5,
            cancellation_event=cancellation_event,
            allowed_document_uuids=allowed_uuids or None,
            session_id=session_id,  # 세션 ID 전달
        )

        if allowed_uuids:

            text_documents = results.get('text_documents')
            if isinstance(text_documents, list):
                results['text_documents'] = _filter_results_by_uuid(text_documents, allowed_uuids)

            image_documents = results.get('image_documents')
            if isinstance(image_documents, list):
                results['image_documents'] = _filter_results_by_uuid(image_documents, allowed_uuids)

        raw_answer = results.get('answer', '답변을 생성하는 데 실패했습니다.')
        
        # 마크다운 테이블 처리 - 줄바꿈 문제 해결
        raw_answer = process_markdown_tables(raw_answer)

        # 1. 텍스트 응답(answer)에 포함된 마크다운 이미지 처리
        processed_result = process_response_with_images(raw_answer)
        final_answer = processed_result['text']
        images = processed_result['images']  # 마크다운에서 추출된 이미지
        processed_image_paths = {img['path'] for img in images}

        # 2. RAG 파이프라인이 직접 반환한 이미지 처리 (핵심)
        pipeline_images = results.get('images', [])
        if pipeline_images:
            for img_item in pipeline_images:
                # file_path가 있고, 아직 추가되지 않았으며, base64 또는 image_base64 데이터가 있는지 확인
                base64_data = img_item.get('base64') or img_item.get('image_base64')
                file_path = img_item.get('file_path')
                
                # base64가 없는데 file_path만 있는 경우 백엔드에서 변환 시도
                if not base64_data and file_path:
                    base64_data = encode_image_to_base64(file_path)
                
                if file_path and file_path not in processed_image_paths and base64_data:
                    images.append({
                        'path': file_path,
                        'alt': os.path.basename(img_item.get('title', file_path)),
                        'title': img_item.get('title', os.path.basename(file_path)),
                        'base64': base64_data
                    })
                    processed_image_paths.add(file_path)
        
        # image_paths 리스트도 처리 (경로만 온 경우 대비)
        image_paths = results.get('image_paths', [])
        if image_paths:
            for path in image_paths:
                if path and path not in processed_image_paths:
                    base64_data = encode_image_to_base64(path)
                    if base64_data:
                        images.append({
                            'path': path,
                            'alt': os.path.basename(path),
                            'title': os.path.basename(path),
                            'base64': base64_data
                        })
                        processed_image_paths.add(path)
            
        # routes.py의 ChatResponse 모델은 List[str]을 기대하므로 base64 문자열 리스트로 변환
        final_images = [img['base64'] for img in images if img.get('base64')]

        return {"answer": final_answer, "images": final_images}

    except InterruptedError as e:
        logger.info(f"RAG 파이프라인 작업이 사용자에 의해 중단되었습니다: {e}")
        return {"answer": "요청이 중단되었습니다.", "images": []}
    except Exception as e:
        logger.error(f"RAG 응답 생성 중 오류 발생: {e}", exc_info=True)
        return {"answer": "답변 생성 중 오류가 발생했습니다.", "images": []}
