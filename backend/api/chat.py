from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import List, Any, Dict
import asyncio
import logging
# RAG 서비스 및 의존성 주입 함수 임포트
from services.rag_service import get_rag_response, build_rag_pipeline
# 이미지 처리 유틸리티 임포트
from utils.helpers import process_response_with_images

# 검색 기능 임포트 (이미 main.py에서 경로 추가됨)
try:
    from skill.search.pipeline import search_google as perform_search
except ImportError as e:
    logging.error(f"search pipeline 모듈 가져오기 실패: {e}")
    perform_search = None

logger = logging.getLogger(__name__)
router = APIRouter()

class ChatRequest(BaseModel):
    query: str
    sources: List[str]

class ChatResponse(BaseModel):
    answer: str
    images: List[str] = []  # base64 문자열 리스트

@router.post("/chat", response_model=ChatResponse)
async def handle_chat(chat_request: ChatRequest, http_request: Request, rag_pipeline: Any = Depends(build_rag_pipeline)):
    """
    사용자 질문을 받아 RAG 파이프라인으로 전달하고 답변을 반환합니다.
    RAG 파이프라인은 의존성 주입을 통해 안전하게 전달받습니다.
    """
    print("=== CHAT.PY ENDPOINT CALLED ===")
    logger.info("=== CHAT.PY ENDPOINT CALLED ===")
    logger.info(f"DEBUG: chat.py endpoint called with query: '{chat_request.query}'")
    logger.info(f"DEBUG: chat.py sources received: {chat_request.sources}")
    for i, source in enumerate(chat_request.sources):
        logger.info(f"DEBUG: chat.py Source[{i}]: '{source}' (length: {len(source)})")
    
    # 세션 ID 추출
    session_id = getattr(http_request.state, "session_id", "default_session")
    logger.info(f"DEBUG: chat.py Session ID: {session_id}")
    
    # 소스 필터링 로직
    source_filter_requested = bool(chat_request.sources)
    if not source_filter_requested:
        logger.info(f"DEBUG: chat.py No specific sources selected, will search within session {session_id} only")
    else:
        logger.info(f"DEBUG: chat.py Specific sources selected: {len(chat_request.sources)} files")
    try:
        # RAG 응답 생성
        # RAG 파이프라인의 process_query 메서드 사용
        import asyncio
        response_data = await asyncio.to_thread(
            rag_pipeline.process_query,
            query=chat_request.query,
            top_k=5,
            allowed_document_uuids=set(chat_request.sources) if chat_request.sources else None,
            session_id=session_id  # 세션 ID 전달
        )
        answer = response_data.get('answer', '답변을 생성하지 못했습니다.')
        
        # 응답에서 이미지 추출 및 처리
        processed_response = process_response_with_images(answer)
        
        logger.info(f"이미지 처리 결과: {len(processed_response['images'])}개 이미지 발견")
        # 프론트엔드 형식에 맞게 이미지 데이터를 base64 문자열의 리스트로 변환
        image_base64_list = [img.get('base64', '') for img in processed_response.get('images', []) if img.get('base64')]
        
        return ChatResponse(
            answer=processed_response['response'],
            images=image_base64_list
        )
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")


class ParallelRequest(BaseModel):
    query: str
    sources: List[str]
    enable_search: bool = True  # 검색 기능 활성화 여부

class ParallelResponse(BaseModel):
    rag_answer: str
    search_results: List[Dict[str, Any]]
    images: List[Dict[str, Any]] = []  # 이미지 데이터 리스트
    

@router.post("/parallel", response_model=ParallelResponse)
async def handle_parallel(parallel_request: ParallelRequest, http_request: Request, rag_pipeline: Any = Depends(build_rag_pipeline)):
    """
    RAG와 검색을 병렬로 수행하여 결과를 반환합니다.
    """
    # 세션 ID 추출
    session_id = getattr(http_request.state, "session_id", "default_session")
    logger.info(f"DEBUG: parallel endpoint Session ID: {session_id}")
    
    async def run_rag():
        """RAG 응답 생성 및 이미지 처리"""
        try:
            # RAG 응답 생성 - process_query 사용
            import asyncio
            answer_data = await asyncio.to_thread(
                rag_pipeline.process_query,
                query=parallel_request.query,
                top_k=5,
                allowed_document_uuids=set(parallel_request.sources) if parallel_request.sources else None,
                session_id=session_id  # 세션 ID 전달
            )
            answer = answer_data.get('answer', 'RAG 처리 중 오류가 발생했습니다.')
            
            # 응답에서 이미지 추출 및 처리
            processed_response = process_response_with_images(answer)
            
            return {
                'answer': processed_response['response'],
                'images': processed_response['images']
            }
        except Exception as e:
            logger.error(f"RAG 처리 중 오류: {e}")
            return {
                'answer': f"RAG 처리 중 오류가 발생했습니다: {str(e)}",
                'images': []
            }
    
    async def run_search():
        """검색 수행"""
        if not parallel_request.enable_search or perform_search is None:
            return []
        
        try:
            # 비동기로 검색 수행 (새로운 이벤트 루프에서 실행)
            results = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: perform_search(parallel_request.query, 10, [])
            )
            return results if results else []
        except Exception as e:
            logger.error(f"검색 처리 중 오류: {e}")
            return []
    
    try:
        # RAG와 검색을 병렬로 실행
        rag_task = run_rag()
        search_task = run_search()
        
        rag_result, search_results = await asyncio.gather(rag_task, search_task)
        
        # RAG 결과에서 답변과 이미지 분리
        rag_answer = rag_result['answer'] if isinstance(rag_result, dict) else rag_result
        rag_images = rag_result['images'] if isinstance(rag_result, dict) else []
        
        logger.info(f"병렬 처리 완료 - RAG 답변: {len(rag_answer)} 문자, 이미지: {len(rag_images)}개, 검색 결과: {len(search_results)}개")
        
        return ParallelResponse(
            rag_answer=rag_answer,
            search_results=search_results,
            images=rag_images
        )
        
    except Exception as e:
        logger.error(f"병렬 처리 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"병렬 처리 중 오류가 발생했습니다: {str(e)}")
