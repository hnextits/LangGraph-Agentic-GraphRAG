#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import json
import logging
import numpy as np
from typing import List, Dict, Any
import faiss
import pickle
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel

# config.py 파일이 있는 디렉토리를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RAGConfig

# 로깅 설정
logger = logging.getLogger(__name__)

class TextSearcher:
    def __init__(self, index_path: str = None, model_name: str = None, device: str = None):
        """텍스트 검색기를 초기화합니다."""
        config = RAGConfig()
        self.index_path = index_path if index_path else config.INDEX_DIR
        self.text_index = None
        self.dimension = config.VECTOR_DIMENSION  # config에서 값 가져오기
        self.max_length = config.MAX_LENGTH
        self.model_name = model_name if model_name else config.EMBEDDING_MODEL
        
        # GPU 분산 배치 설정 사용
        if device:
            self.device = device
        else:
            # config에서 텍스트 임베딩 전용 GPU 사용
            self.device = config.TEXT_EMBEDDING_DEVICE if torch.cuda.is_available() else "cpu"
            
        logger.info(f"텍스트 임베딩 모델이 {self.device}에 로드됩니다.")
        
        # 공유 임베딩 모델 초기화
        from shared_embedding import SharedEmbeddingModel
        self.shared_embedding = SharedEmbeddingModel()
        
        # 개선된 텍스트 리랭커 초기화 (클래스 레벨에서 관리)
        self.reranker = None
        self._initialize_reranker()
        
        # 메모리 정리
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        self.metadata_path = None
        self.has_metadata = False
        self.metadata_store = None
        self.index_to_id = None
        
        self.tokenizer = None
        self.model = None
        self.eod_id = None
        self.model_on_gpu = False  # 모델이 GPU에 있는지 추적
        
        logger.info(f"인덱스 디렉토리: {self.index_path}")
        
        # 초기화 시점에 인덱스 로드
        self.load_index()
    
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

    def load_index(self) -> bool:
        """FAISS 인덱스를 로드합니다. 성공 시 True, 실패 시 False를 반환합니다."""
        try:
            possible_index_files = [
                os.path.join(self.index_path, 'text_index.faiss'),
                os.path.join(self.index_path, 'faiss_index.faiss'),
                os.path.join(self.index_path, 'faiss_index.index'),
                os.path.join(self.index_path, 'text_index.index')
            ]
            
            index_file = None
            for file_path in possible_index_files:
                if os.path.exists(file_path):
                    index_file = file_path
                    break
            
            if index_file:
                self.text_index = faiss.read_index(index_file)
                logger.info(f"FAISS 인덱스 로드 완료: {index_file} (벡터 수: {self.text_index.ntotal})")
                
                # .faiss와 .index 확장자 모두 지원
                if '.faiss' in index_file:
                    pickle_metadata_path = index_file.replace('.faiss', '_metadata.pkl')
                else:
                    pickle_metadata_path = index_file.replace('.index', '_metadata.pkl')
                
                if os.path.exists(pickle_metadata_path):
                    try:
                        with open(pickle_metadata_path, 'rb') as f:
                            metadata_data = pickle.load(f)
                        
                        self.metadata_store = metadata_data.get('metadata_store', {})
                        self.index_to_id = metadata_data.get('index_to_id', {})
                        
                        logger.info(f"메타데이터 로드 완료: {len(self.metadata_store)} 항목")
                        
                        self.metadata_path = pickle_metadata_path
                        self.has_metadata = True
                    except Exception as e:
                        logger.error(f"메타데이터 로드 중 오류 발생: {str(e)}")
                        # 메타데이터 로드 실패는 인덱스 로드 실패로 간주하지 않음
                else:
                    logger.warning(f"메타데이터 파일이 존재하지 않습니다: {pickle_metadata_path}")
                
                return True  # 인덱스 로드 성공
            else:
                logger.warning(f"사용 가능한 FAISS 인덱스 파일이 존재하지 않습니다. 빈 인덱스를 생성합니다.")
                self.text_index = faiss.IndexFlatIP(self.dimension)
                return False  # 인덱스 파일이 없음
        except Exception as e:
            logger.error(f"인덱스 로드 중 오류 발생: {str(e)}")
            self.text_index = faiss.IndexFlatIP(self.dimension)
            return False  # 오류 발생

    def generate_embedding(self, text: str) -> np.ndarray:
        """
        쿼리 텍스트에 대한 임베딩을 생성합니다.
        공유 임베딩 모델을 사용하여 메모리 효율성을 높입니다.
        """
        try:
            # 공유 임베딩 모델 사용 확인
            if not self.shared_embedding.is_loaded():
                logger.error("공유 임베딩 모델이 로드되지 않았습니다.")
                raise RuntimeError("공유 임베딩 모델이 로드되지 않았습니다.")
            
            # 공유 임베딩 모델을 통한 임베딩 생성
            embedding = self.shared_embedding.generate_embedding(text)
            
            if len(embedding) != self.dimension:
                logger.warning(f"임베딩 차원이 예상과 다릅니다: {len(embedding)} vs {self.dimension}")
            
            # config에 따른 dtype 설정 (필요시 FAISS에서 float32로 변환)
            try:
                from config import RAGConfig
                rag_config = RAGConfig()
                if rag_config.GENERATOR_TORCH_DTYPE == "auto":
                    # auto인 경우 FAISS 호환성을 위해 float32 사용
                    return embedding.astype('float32')
                else:
                    # 기본적으로 float16 사용
                    return embedding.astype('float16')
            except Exception as e:
                # config 로드 실패 시 기본값 사용
                logger.warning(f"Config 로드 실패: {e}, 기본 dtype 사용")
                return embedding.astype('float16')
            
        except Exception as e:
            logger.error(f"임베딩 생성 중 오류 발생: {e}")
            raise RuntimeError(f"임베딩 생성 실패: {e}") from e
    


    def search(self, query: str, top_k: int = None, rerank: bool = True, rerank_top_k: int = None) -> List[Dict[str, Any]]:
        """텍스트 쿼리로 검색을 수행합니다."""
        # config에서 기본값 가져오기
        config = RAGConfig()
        top_k = top_k if top_k is not None else config.TEXT_TOP_K
        
        # 매 검색마다 인덱스를 리로드하여 최신 데이터 반영
        logger.info("검색 시작 전 인덱스를 리로드하여 최신 데이터를 반영합니다.")
        if not self.load_index():
            # 인덱스 로드 실패 시 기존 인덱스가 있는지 확인
            if self.text_index is None or self.text_index.ntotal == 0:
                logger.error("인덱스 로드 실패 및 기존 인덱스 없음. 검색을 진행할 수 없습니다.")
                return []

        search_top_k = top_k * 3 if rerank else top_k
        # 공유 임베딩 모델 사용 (메모리 절약)
        query_embedding = self.shared_embedding.generate_embedding(query)
        scores, indices = self.text_index.search(np.array([query_embedding]), search_top_k)

        results = []
        for i, idx in enumerate(indices[0]):
            score = float(scores[0][i])
            index = int(idx)
            
            doc_id = self.index_to_id.get(index) or self.index_to_id.get(str(index))
            
            result = {
                'score': score,
                'index': index,
                'id': doc_id or f"doc_{index}",
                'title': f"문서 {index}",
                'text': f"인덱스 {index}에 해당하는 문서"
            }
            
            if doc_id and doc_id in self.metadata_store:
                metadata = self.metadata_store[doc_id]
                result.update({
                    'title': metadata.get('metadata', {}).get('title', result['title']),
                    'text': metadata.get('text', result['text']),
                    'content_type': metadata.get('content_type', 'text'),
                    'raw_text': metadata.get('raw_text', '')[:100] + '...' if len(metadata.get('raw_text', '')) > 100 else metadata.get('raw_text', '')
                })
            results.append(result)

        logger.info(f"쿼리 '{query}'에 대한 검색 완료, 결과 수: {len(results)}")
        
        if rerank and results and self.reranker:
            try:
                if rerank_top_k is None:
                    rerank_top_k = top_k
                
                # 개선된 리랭커 사용
                logger.info(f"개선된 리랭커로 재정렬 시작 (top_k={rerank_top_k})")
                
                # config에서 설정값 가져오기
                config = RAGConfig()
                
                # ImprovedTextReranker의 rerank 메서드 호출
                reranked_results = self.reranker.rerank(
                    query=query, 
                    results=results, 
                    top_k=rerank_top_k,
                    min_score=config.RELEVANCE_THRESHOLD  # config에서 가져온 관련성 임계값
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

                # try:
                #     # 'reranked_results.txt' 파일에 결과를 덮어쓰기 모드('w')로 저장합니다.
                #     with open('reranked_results.txt', 'w', encoding='utf-8') as f:
                #         f.write(f"쿼리: {query}\n\n")
                #         for i, result in enumerate(results):
                #             title = result.get('title', '제목 없음')
                #             score = result.get('score', 0)
                #             text_content = result.get('text', '내용 없음')
                            
                #             f.write(f"순위 {i+1} (점수: {score:.4f})\n")
                #             f.write(f"제목: {title}\n")
                #             f.write(f"내용: {text_content}\n")
                #             f.write("-" * 30 + "\n")
                #     logger.info("리랭킹된 결과를 'reranked_results.txt' 파일에 성공적으로 저장했습니다.")
                # except Exception as e:
                #     logger.error(f"결과를 파일에 저장하는 중 오류 발생: {e}")
                
            except Exception as e:
                logger.error(f"개선된 리랭킹 중 오류 발생: {e}")
                logger.warning("리랭킹 없이 원본 결과를 반환합니다.")
        
        elif rerank and results and not self.reranker:
            logger.warning("리랭커가 초기화되지 않아 리랭킹을 건너뜁니다.")
        
        return results[:top_k]

if __name__ == "__main__":
    # 'page_num' 키가 메타데이터에 없을 경우를 대비하여 .get()으로 안전하게 접근하도록 수정
    searcher = TextSearcher()
    while True:
        query = input("검색 쿼리를 입력하세요 (종료하려면 'exit' 입력): ")
        if query.lower() == 'exit':
            break
            
        print(f"\n검색 결과 (리랭킹 미적용, 최대 5개):")
        initial_results = searcher.search(query, top_k=5, rerank=False)
        for i, result in enumerate(initial_results):
            title = result.get('title', '제목 없음')
            page_num_str = f"(페이지 {result.get('page_num', 'N/A')})" if 'page_num' in result else ''
            # print(f"{i+1}. {title} {page_num_str}- 유사도: {result.get('score', 0):.4f}")
            # print(f"   ID: {result.get('id', 'N/A')}")
            # print(f"   인덱스: {result.get('index', 'N/A')}")
            # print(f"   텍스트: {result.get('text', '')[:200]}...")
            # print()
        
        print("\n리랭킹 수행 중...")
        try:
            reranked_results = searcher.search(query, top_k=5, rerank=True)
            print(f"\n리랭킹 적용된 검색 결과 (최대 5개):")
            for i, result in enumerate(reranked_results):
                title = result.get('title', '제목 없음')
                page_num_str = f"(페이지 {result.get('page_num', 'N/A')})" if 'page_num' in result else ''
                print(f"{i+1}. {title} {page_num_str} - 리랭크 점수: {result.get('score', 0):.4f}")
                print(f"   ID: {result.get('id', 'N/A')}")
                print(f"   인덱스: {result.get('index', 'N/A')}")
                print(f"   텍스트: {result.get('text', '')[:200]}...")
                print()
        except Exception as e:
            print(f"\n리랭킹 중 오류 발생: {e}")
