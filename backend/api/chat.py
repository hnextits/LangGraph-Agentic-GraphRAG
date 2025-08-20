from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Any, Dict
import asyncio
import logging

# RAG 서비스 및 의존성 주입 함수 임포트
from services.rag_service import get_rag_response, get_rag_pipeline
# 이미지 처리 유틸리티 임포트
from utils.helpers import process_response_with_images

# 검색 기능 임포트 (이미 main.py에서 경로 추가됨)
try:
    from search_test.crawler_pipeline import search as perform_search
except ImportError as e:
    logging.error(f"crawler_pipeline 모듈 가져오기 실패: {e}")
    perform_search = None

logger = logging.getLogger(__name__)
router = APIRouter()

class ChatRequest(BaseModel):
    query: str
    sources: List[str]

class ChatResponse(BaseModel):
    answer: str
    images: List[Dict[str, Any]] = []  # 이미지 데이터 리스트

@router.post("/chat", response_model=ChatResponse)
async def handle_chat(request: ChatRequest, rag_pipeline: Any = Depends(get_rag_pipeline)):
    """
    사용자 질문을 받아 RAG 파이프라인으로 전달하고 답변을 반환합니다.
    RAG 파이프라인은 의존성 주입을 통해 안전하게 전달받습니다.
    """
    try:
        # RAG 응답 생성
        answer = get_rag_response(
            query=request.query, 
            sources=request.sources, 
            rag_pipeline=rag_pipeline
        )
        
        # 응답에서 이미지 추출 및 처리
        processed_response = process_response_with_images(answer)
        
        logger.info(f"이미지 처리 결과: {len(processed_response['images'])}개 이미지 발견")
        
        return ChatResponse(
            answer=processed_response['response'],
            images=processed_response['images']
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
async def handle_parallel(request: ParallelRequest, rag_pipeline: Any = Depends(get_rag_pipeline)):
    """
    RAG와 검색을 병렬로 수행하여 결과를 반환합니다.
    """
    async def run_rag():
        """RAG 응답 생성 및 이미지 처리"""
        try:
            # RAG 응답 생성
            answer = get_rag_response(
                query=request.query,
                sources=request.sources,
                rag_pipeline=rag_pipeline
            )
            
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
        if not request.enable_search or perform_search is None:
            return []
        
        try:
            # 비동기로 검색 수행 (새로운 이벤트 루프에서 실행)
            results = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: perform_search(request.query, 10, [])
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
