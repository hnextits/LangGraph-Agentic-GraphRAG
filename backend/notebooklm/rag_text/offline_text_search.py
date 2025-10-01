#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
텍스트 검색기 - SGLang을 사용한 오프라인 버전
기존 text_search.py 구조를 유지하면서 SGLang 오프라인 모드 지원
"""

import os
import sys
import json
import logging
import numpy as np
import threading
import multiprocessing
from typing import List, Dict, Any, Optional
import weaviate
import torch
import sglang as sgl
from transformers import AutoModel, AutoTokenizer

# config.py 파일이 있는 디렉토리를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RAGConfig
from weaviate_utils import create_schema

# 로깅 설정
logger = logging.getLogger(__name__)

class OfflineEmbeddingModel:
    """오프라인 임베딩 모델 - Hugging Face 기반"""
    
    _instance = None
    _model = None
    _tokenizer = None
    _is_loaded = False
    
    def __new__(cls, model_name="Qwen/Qwen3-Embedding-4B", device=None):
        if cls._instance is None:
            cls._instance = super(OfflineEmbeddingModel, cls).__new__(cls)
            cls.model_name = model_name
            cls.device = device if device else ("cuda" if torch.cuda.is_available() else "cpu")
            cls._load_model()
        return cls._instance
    
    @classmethod
    def _load_model(cls):
        """임베딩 모델 로드"""
        try:
            logger.info(f"오프라인 임베딩 모델 로드 중: {cls.model_name} (device: {cls.device})")
            cls._tokenizer = AutoTokenizer.from_pretrained(cls.model_name)
            cls._model = AutoModel.from_pretrained(cls.model_name).to(cls.device)
            cls._model.eval()  # 평가 모드로 설정
            cls._is_loaded = True
            logger.info(f"오프라인 임베딩 모델 로드 완료")
        except Exception as e:
            logger.error(f"오프라인 임베딩 모델 로드 실패: {e}")
            cls._is_loaded = False
            raise
    
    def is_loaded(self):
        """모델 로드 여부 확인"""
        return self._is_loaded
    
    def generate_embedding(self, text: str, normalize: bool = True) -> np.ndarray:
        """텍스트에 대한 임베딩 생성"""
        try:
            # 입력 텍스트 토큰화
            inputs = self._tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            # 그래디언트 계산 없이 임베딩 생성
            with torch.no_grad():
                outputs = self._model(**inputs)
                # CLS 토큰의 마지막 은닉 상태를 임베딩으로 사용
                embedding = outputs.last_hidden_state[:, 0, :].cpu().numpy()[0]
            
            # 필요시 정규화 수행
            if normalize:
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm
                    
            return embedding.astype('float32')
        except Exception as e:
            logger.error(f"임베딩 생성 중 오류 발생: {e}")
            raise RuntimeError(f"임베딩 생성 실패: {e}") from e

class OfflineTextSearcher:
    def __init__(self, model_name: str = None, device: str = None, chat_model_name: str = "Qwen/Qwen3-8B"):
        """오프라인 텍스트 검색기를 초기화합니다."""
        config = RAGConfig()
        self.dimension = config.VECTOR_DIMENSION
        self.max_length = config.MAX_LENGTH
        self.model_name = model_name if model_name else config.EMBEDDING_MODEL
        
        # GPU 분산 배치 설정 사용
        if device:
            self.device = device
        else:
            # config에서 텍스트 임베딩 전용 GPU 사용
            self.device = config.TEXT_EMBEDDING_DEVICE if torch.cuda.is_available() else "cpu"
            
        logger.info(f"오프라인 텍스트 임베딩 모델이 {self.device}에 로드됩니다.")
        
        # 오프라인 임베딩 모델 초기화
        self.offline_embedding = OfflineEmbeddingModel(model_name=self.model_name, device=self.device)
        
        # SGLang 대화 엔진 초기화 (선택적)
        self.chat_model_name = chat_model_name
        self.engine = None
        self._initialize_chat_engine()
        
        # 개선된 텍스트 리랭커 초기화 (클래스 레벨에서 관리)
        self.reranker = None
        self._initialize_reranker()
        
        # 메모리 정리
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # Weaviate 클라이언트 초기화
        self.client = config.get_weaviate_client()
        if self.client:
            # 스키마 생성 확인
            create_schema(self.client)
        else:
            logger.error("Weaviate 클라이언트 초기화 실패")
        
        self.class_name = config.WEAVIATE_TEXT_CLASS
        logger.info(f"오프라인 텍스트 검색기 초기화 완료 (클래스: {self.class_name})")
    
    def _initialize_chat_engine(self):
        """SGLang 대화 엔진 초기화"""
        try:
            # multiprocessing 설정
            multiprocessing.freeze_support()  # Windows에서 필요
            try:
                multiprocessing.set_start_method('spawn', force=True)
            except RuntimeError:
                pass  # 이미 설정된 경우 무시
                
            logger.info(f"SGLang 대화 엔진 초기화 중: {self.chat_model_name}...")
            self.engine = sgl.Engine(model_path=self.chat_model_name)
            logger.info("SGLang 대화 엔진 초기화 완료")
        except Exception as e:
            logger.error(f"SGLang 대화 엔진 초기화 실패: {e}")
            self.engine = None
    
    def _initialize_reranker(self):
        """개선된 텍스트 리랭커를 초기화합니다."""
        try:
            from rag_text.text_reranker_improved_2 import ImprovedTextReranker
            
            # config에서 설정값 가져오기
            config = RAGConfig()
            
            # 성능 최적화된 설정으로 리랭커 초기화
            self.reranker = ImprovedTextReranker(
                model_name=config.RERANKER_MODEL_NAME,  # config에서 모델 이름 가져오기
                max_length=8192,  # 적절한 길이 제한
                batch_size=config.RERANKER_BATCH_SIZE  # config에서 배치 크기 가져오기
            )
            logger.info(f"개선된 텍스트 리랭커 초기화 완료 - 모델: {config.RERANKER_MODEL_NAME}")
        except Exception as e:
            logger.error(f"개선된 텍스트 리랭커 초기화 실패: {e}")
            logger.warning("기존 TextReranker로 폴백합니다.")
            try:
                from rag_text.text_reranker import TextReranker
                self.reranker = TextReranker()
                logger.info("기존 TextReranker로 폴백 완료")
            except Exception as fallback_error:
                logger.error(f"기존 TextReranker 폴백도 실패: {fallback_error}")
                self.reranker = None

    def generate_embedding(self, text: str) -> np.ndarray:
        """
        쿼리 텍스트에 대한 임베딩을 생성합니다.
        오프라인 임베딩 모델을 사용합니다.
        """
        try:
            # 오프라인 임베딩 모델 사용 확인
            if not self.offline_embedding.is_loaded():
                logger.error("오프라인 임베딩 모델이 로드되지 않았습니다.")
                raise RuntimeError("오프라인 임베딩 모델이 로드되지 않았습니다.")
            
            # 오프라인 임베딩 모델을 통한 임베딩 생성
            embedding = self.offline_embedding.generate_embedding(text)
            
            if len(embedding) != self.dimension:
                logger.warning(f"임베딩 차원이 예상과 다릅니다: {len(embedding)} vs {self.dimension}")
            
            return embedding
            
        except Exception as e:
            logger.error(f"임베딩 생성 중 오류 발생: {e}")
            raise RuntimeError(f"임베딩 생성 실패: {e}") from e

    def search(self, query: str, top_k: int = None, rerank: bool = True, rerank_top_k: int = None, cancellation_event: Optional[threading.Event] = None) -> List[Dict[str, Any]]:
        """텍스트 쿼리로 검색을 수행합니다."""
        # config에서 기본값 가져오기
        config = RAGConfig()
        top_k = top_k if top_k is not None else config.TEXT_TOP_K
        
        if not self.client:
            logger.error("Weaviate 클라이언트가 초기화되지 않았습니다.")
            return []
        
        search_top_k = top_k * 3 if rerank else top_k
        
        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled before text embedding generation")
        
        try:
            # 오프라인 임베딩 모델 사용
            query_embedding = self.generate_embedding(query)
            
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before Weaviate search")
            
            # Weaviate 벡터 검색 수행
            vector_search_results = (
                self.client.query
                .get(self.class_name, ["text", "title", "source", "page_num", "metadata"])
                .with_near_vector({
                    "vector": query_embedding.tolist()
                })
                .with_limit(search_top_k)
                .with_additional(["distance"])
                .do()
            )
            
            # 결과 파싱
            results = []
            if "data" in vector_search_results and "Get" in vector_search_results["data"]:
                items = vector_search_results["data"]["Get"].get(self.class_name, [])
                
                for i, item in enumerate(items):
                    # Weaviate의 _additional 필드에서 거리 점수 가져오기
                    additional = item.get("_additional", {})
                    score = additional.get("distance", 0) if isinstance(additional, dict) else 0
                    # 거리를 유사도 점수로 변환 (1 - 거리)
                    similarity_score = 1 - score if score <= 1 else 0
                    
                    # 메타데이터 안전하게 처리
                    metadata = item.get("metadata", {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    
                    result = {
                        'score': similarity_score,
                        'index': i,
                        'id': item.get("id", f"doc_{i}"),
                        'title': item.get("title", f"문서 {i}"),
                        'text': item.get("text", f"인덱스 {i}에 해당하는 문서"),
                        'source': item.get("source", ""),
                        'page_num': item.get("page_num", 0),
                        'metadata': metadata
                    }
                    results.append(result)
            
            logger.info(f"쿼리 '{query}'에 대한 검색 완료, 결과 수: {len(results)}")
            
            # 리랭킹 적용
            if rerank and results and self.reranker:
                try:
                    if rerank_top_k is None:
                        rerank_top_k = top_k
                    
                    # 개선된 리랭커 사용
                    logger.info(f"개선된 리랭커로 재정렬 시작 (top_k={rerank_top_k})")
                    
                    # config에서 설정값 가져오기
                    config = RAGConfig()
                    
                    # 취소 확인
                    if cancellation_event and cancellation_event.is_set():
                        raise InterruptedError("Operation cancelled before reranking")
                    
                    # ImprovedTextReranker의 rerank 메서드 호출
                    reranked_results = self.reranker.rerank(
                        query, 
                        results, 
                        top_k=rerank_top_k, 
                        min_score=config.RELEVANCE_THRESHOLD, 
                        cancellation_event=cancellation_event
                    )
                    
                    # 리랭킹 통계 로깅
                    if hasattr(self.reranker, 'get_statistics'):
                        stats = self.reranker.get_statistics()
                        cache_hit_rate = stats.get('cache_hit_rate', 0)
                        logger.info(f"리랭킹 완료 - 캐시 적중률: {cache_hit_rate:.1f}%")
                    
                    results = reranked_results
                    logger.info(f"쿼리 '{query}'에 대한 개선된 리랭킹 완료, 결과 수: {len(results)}")
                    
                    # 리랭킹 결과 상세 로그 출력
                    logger.info(f"리랭킹 적용된 검색 결과 (최대 5개):")
                    for i, result in enumerate(results[:5]):
                        title = result.get('title', '제목 없음')
                        page_num_str = f"(페이지 {result.get('page_num', 'N/A')})" if 'page_num' in result else ''
                        logger.info(f"{i+1}. {title} {page_num_str} - 리랭크 점수: {result.get('score', 0):.4f}")
                        logger.info(f"   ID: {result.get('id', 'N/A')}, 인덱스: {result.get('index', 'N/A')}")
                        text_preview = result.get('text', '')[:100] + '...' if len(result.get('text', '')) > 100 else result.get('text', '')
                        logger.info(f"   텍스트: {text_preview}")
                
                except Exception as e:
                    logger.error(f"개선된 리랭킹 중 오류 발생: {e}")
                    logger.warning("리랭킹 없이 원본 결과를 반환합니다.")
            
            elif rerank and results and not self.reranker:
                logger.warning("리랭커가 초기화되지 않아 리랭킹을 건너뜁니다.")
            
            return results[:top_k]
            
        except Exception as e:
            logger.error(f"Weaviate 검색 중 오류 발생: {e}")
            return []
    
    def rag_chat(self, query: str, top_k: int = 3) -> str:
        """RAG 기반 대화 응답 생성"""
        if not self.engine:
            logger.error("SGLang 대화 엔진이 초기화되지 않았습니다.")
            return "SGLang 대화 엔진이 초기화되지 않아 응답을 생성할 수 없습니다."
        
        try:
            # 검색 수행
            search_results = self.search(query, top_k=top_k, rerank=True)
            
            # 검색 결과를 컨텍스트로 변환
            context = ""
            if search_results:
                context = "\n\n관련 문서:\n"
                for i, result in enumerate(search_results, 1):
                    title = result.get('title', f"문서 {i}")
                    score = result.get('score', 0)
                    text = result.get('text', '')
                    context += f"[문서 {i}] (유사도: {score:.2f}) {title}\n{text}\n\n"
            else:
                context = "\n\n관련 문서가 없습니다.\n"
            
            # 프롬프트 생성
            system_prompt = """당신은 지식 기반 질의응답 시스템입니다. 사용자의 질문에 대해 제공된 문서 정보를 기반으로 답변해주세요.
            제공된 문서에서 정보를 찾을 수 없는 경우, '제공된 문서에서 관련 정보를 찾을 수 없습니다'라고 답변하세요.
            답변은 한국어로 작성하고, 명확하고 간결하게 제공하세요."""
            
            prompt = f"시스템: {system_prompt}\n\n사용자: {query}\n{context}\n어시스턴트: "
            
            # 샘플링 파라미터 설정
            sampling_params = {
                "temperature": 0.7,
                "top_p": 0.95,
                "max_new_tokens": 4096
            }
            
            # 모델 응답 생성
            result = self.engine.generate(prompt=prompt, sampling_params=sampling_params)
            response = result["text"]
            
            return response
            
        except Exception as e:
            logger.error(f"RAG 대화 응답 생성 중 오류 발생: {e}")
            return f"응답 생성 중 오류가 발생했습니다: {str(e)}"
    
    def shutdown(self):
        """모델 및 엔진 종료"""
        # SGLang 엔진 종료
        if self.engine is not None:
            try:
                self.engine.shutdown()
                self.engine = None
                logger.info("SGLang 엔진 종료 완료")
            except Exception as e:
                logger.error(f"SGLang 엔진 종료 중 오류 발생: {e}")
        
        # 메모리 정리
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info("GPU 메모리 정리 완료")

def main():
    """오프라인 텍스트 검색기 테스트"""
    # 로깅 설정
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 명령행 인자 파싱
    import argparse
    parser = argparse.ArgumentParser(description="오프라인 텍스트 검색기 테스트")
    parser.add_argument('--model', type=str, default="Qwen/Qwen3-Embedding-4B", help='임베딩 모델 경로')
    parser.add_argument('--chat-model', type=str, default="Qwen/Qwen3-8B", help='대화 모델 경로')
    parser.add_argument('--device', type=str, default="auto", help='사용할 디바이스 (auto, cuda, cpu)')
    parser.add_argument('--mode', type=str, choices=['search', 'chat'], default='search', help='실행 모드 (search: 검색만, chat: RAG 대화)')
    args = parser.parse_args()
    
    # 디바이스 설정
    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    
    try:
        # multiprocessing 설정
        multiprocessing.freeze_support()  # Windows에서 필요
        try:
            multiprocessing.set_start_method('spawn', force=True)
        except RuntimeError:
            pass  # 이미 설정된 경우 무시
        
        # 검색기 초기화
        print(f"오프라인 텍스트 검색기 초기화 중... (임베딩 모델: {args.model}, 디바이스: {device})")
        searcher = OfflineTextSearcher(model_name=args.model, device=device, chat_model_name=args.chat_model)
        print("초기화 완료!")
        
        # 모드에 따라 실행
        if args.mode == 'search':
            # 검색 모드
            print("\n=== 오프라인 텍스트 검색 모드 ===")
            print("검색을 종료하려면 'exit' 또는 'quit'를 입력하세요.\n")
            
            while True:
                query = input("\n검색 쿼리: ")
                if query.lower() in ['exit', 'quit']:
                    break
                
                print("\n검색 중...")
                try:
                    # 리랭킹 미적용 검색
                    initial_results = searcher.search(query, top_k=5, rerank=False)
                    
                    print(f"\n검색 결과 (리랭킹 미적용, 최대 5개):")
                    if not initial_results:
                        print("검색 결과가 없습니다.")
                    else:
                        for i, result in enumerate(initial_results):
                            title = result.get('title', '제목 없음')
                            page_num_str = f"(페이지 {result.get('page_num', 'N/A')})" if 'page_num' in result else ''
                            print(f"[{i+1}] 유사도: {result.get('score', 0):.4f}")
                            print(f"문서 ID: {result.get('id', 'N/A')}")
                            print(f"내용: {result.get('text', '')[:200]}..." if len(result.get('text', '')) > 200 else f"내용: {result.get('text', '')}")
                            print("-" * 50)
                    
                    # 리랭킹 적용 검색
                    print("\n리랭킹 수행 중...")
                    reranked_results = searcher.search(query, top_k=5, rerank=True)
                    
                    print(f"\n검색 결과 (리랭킹 적용, 최대 5개):")
                    if not reranked_results:
                        print("검색 결과가 없습니다.")
                    else:
                        for i, result in enumerate(reranked_results):
                            title = result.get('title', '제목 없음')
                            page_num_str = f"(페이지 {result.get('page_num', 'N/A')})" if 'page_num' in result else ''
                            print(f"[{i+1}] 유사도: {result.get('score', 0):.4f}")
                            print(f"문서 ID: {result.get('id', 'N/A')}")
                            print(f"내용: {result.get('text', '')[:200]}..." if len(result.get('text', '')) > 200 else f"내용: {result.get('text', '')}")
                            print("-" * 50)
                    
                except Exception as e:
                    print(f"검색 중 오류 발생: {e}")
        
        else:
            # RAG 대화 모드
            print("\n=== 오프라인 RAG 대화 모드 ===")
            print("대화를 종료하려면 'exit' 또는 'quit'를 입력하세요.\n")
            
            while True:
                query = input("\n사용자: ")
                if query.lower() in ['exit', 'quit']:
                    break
                
                print("\n응답 생성 중...")
                try:
                    response = searcher.rag_chat(query, top_k=3)
                    print(f"\n어시스턴트: {response}")
                except Exception as e:
                    print(f"응답 생성 중 오류 발생: {e}")
        
        # 종료
        print("\n검색기를 종료합니다...")
        searcher.shutdown()
        print("종료 완료!")
        
    except Exception as e:
        print(f"프로그램 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
