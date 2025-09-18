#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
텍스트 검색기 - 텍스트 쿼리를 처리하고 관련 문서를 검색합니다.
"""

import os
import json
import logging
import torch
import torch.nn.functional as F
import numpy as np
import faiss
import threading
from typing import List, Dict, Any, Optional, Tuple
from transformers import AutoTokenizer, AutoModel
from rag_image.image_reranker import RAGReranker

# config.py 파일이 있는 디렉토리를 sys.path에 추가
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RAGConfig

# shared_embedding 모듈 import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared_embedding import shared_embedding

# 로깅 설정
logger = logging.getLogger(__name__)

class ImageSearcher:
    """이미지 검색을 위한 클래스입니다. 이미지와 차트 모두 검색 가능합니다."""
    
    def __init__(self, index_path: str = None, metadata_path: str = None, model_name: str = None, ollama_host: str = None, use_reranker: bool = True, supported_types: List[str] = ['image', 'chart']):
        """이미지 검색기를 초기화합니다."""
        config = RAGConfig()
        self.index_path = index_path if index_path else config.INDEX_DIR
        self.image_index = None
        self.dimension = config.VECTOR_DIMENSION  # 임베딩 차원
        self.model_name = model_name if model_name else config.EMBEDDING_MODEL
        self.ollama_host = ollama_host if ollama_host else config.OLLAMA_API_URL
        self.metadata_pkl_path = os.path.join(self.index_path, 'image_metadata.pkl')  # PKL 메타데이터 경로
        self.metadata_json_path = os.path.join(self.index_path, 'image_metadata.json')  # JSON 메타데이터 경로 (후방 호환성)
        self.use_reranker = use_reranker
        self.supported_types = supported_types  # 지원하는 콘텐츠 타입 (기본값: image, chart)
        
        # GPU 분산 배치 설정 사용 - 이미지 임베딩 전용 GPU
        if torch.cuda.is_available():
            self.device = torch.device(config.IMAGE_EMBEDDING_DEVICE)
        else:
            self.device = torch.device('cpu')
        
        logger.info(f"디바이스 설정: {self.device}")
        
        # 공유 임베딩 모델 사용 (전역 싱글톤 인스턴스)
        self.shared_embedding = shared_embedding
        
        # 메모리 정리
        torch.cuda.empty_cache()
        
        # 공유 임베딩 모델을 사용하므로 별도의 모델 로드는 필요 없음
        # 메모리 최적화를 위해 주석 처리
        self.tokenizer = None
        self.model = None
        
        # 공유 임베딩 모델이 제대로 로드되었는지 확인
        if self.shared_embedding.is_loaded():
            logger.info(f"공유 임베딩 모델 사용 중: {self.shared_embedding._model_name} (디바이스: {self.shared_embedding._device})")
        else:
            logger.error("공유 임베딩 모델이 로드되지 않았습니다.")
        
        # 리랭커 초기화
        self.reranker = None
        if self.use_reranker:
            try:
                # 이미 상단에서 import 했으므로 중복 import 제거
                self.reranker = RAGReranker()
                logger.info("리랭커 초기화 완료")
            except Exception as e:
                logger.error(f"리랭커 초기화 중 오류 발생: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                self.reranker = None
        
        # 인덱스 로드
        self.load_index()

    def load_index(self) -> bool:
        """FAISS 인덱스를 로드합니다. 성공 시 True, 실패 시 False를 반환합니다."""
        try:
            index_file = os.path.join(self.index_path, 'image_index.faiss')
            if os.path.exists(index_file):
                self.image_index = faiss.read_index(index_file)
                logger.info(f"이미지 인덱스 로드 완료: {index_file}")
                return True  # 인덱스 로드 성공
            else:
                logger.warning(f"이미지 인덱스 파일이 존재하지 않습니다: {index_file}")
                self.image_index = faiss.IndexFlatIP(self.dimension)
                return False  # 인덱스 파일이 없음
        except Exception as e:
            logger.error(f"인덱스 로드 중 오류 발생: {str(e)}")
            self.image_index = faiss.IndexFlatIP(self.dimension)
            return False  # 오류 발생

    def generate_embedding(self, text: str) -> np.ndarray:
        """이미지에 대한 임베딩을 생성합니다. 공유 임베딩 모델을 사용합니다."""
        try:
            # 공유 임베딩 모델 사용
            if not self.shared_embedding.is_loaded():
                logger.error("공유 임베딩 모델이 로드되지 않았습니다.")
                return np.random.rand(self.dimension).astype('float32')
            
            # 공유 임베딩 모델을 통한 임베딩 생성
            embedding = self.shared_embedding.generate_embedding(text)
            
            if len(embedding) != self.dimension:
                logger.warning(f"임베딩 차원이 예상과 다릅니다: {len(embedding)} vs {self.dimension}")
            
            return embedding.astype('float32')
        except Exception as e:
            logger.error(f"공유 임베딩 모델 임베딩 생성 중 오류 발생: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return np.random.rand(self.dimension).astype('float32')  # 오류 발생 시 랜덤 벡터로 대체

    def search(self, query: str, top_k: int = 10, rerank: bool = True, cancellation_event: Optional[threading.Event] = None) -> List[Dict[str, Any]]:
        """이미지 쿼리로 검색을 수행합니다. 벡터 검색을 수행하고 결과에 해당하는 메타데이터를 가져옵니다.
        리랭크가 성공적으로 수행된 경우 리랭크된 결과만 반환하고, 그렇지 않은 경우 원본 결과를 반환합니다."""
        # 매 검색마다 인덱스 다시 로드
        if not self.load_index():
            logger.warning("이미지 인덱스 로드에 실패했습니다.")
            return []
            
        # 설정에서 기본값 가져오기
        config = RAGConfig()
        if top_k is None:
            top_k = config.IMAGE_TOP_K
        if self.image_index is None or self.image_index.ntotal == 0:
            logger.warning("로드된 이미지 인덱스가 없습니다.")
            return []

        # 쿼리 임베딩 생성 - 공유 임베딩 모델 사용 (메모리 절약)
        try:
            # 쿼리 전처리 - 공백 제거 및 정규화
            normalized_query = query.strip()
            logger.info(f"정규화된 쿼리: '{normalized_query}'")
            
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before image query embedding generation")

            # 쿼리 임베딩 생성
            query_embedding = self.shared_embedding.generate_embedding(normalized_query)
            
            # 임베딩 정보 로깅
            embedding_norm = np.linalg.norm(query_embedding)
            embedding_mean = np.mean(query_embedding)
            embedding_std = np.std(query_embedding)
            logger.info(f"이미지 검색 쿼리 임베딩 생성 성공: '{normalized_query[:50]}...'")
            logger.info(f"임베딩 통계 - 노름: {embedding_norm:.4f}, 평균: {embedding_mean:.4f}, 표준편차: {embedding_std:.4f}")
        except Exception as e:
            logger.error(f"이미지 검색 쿼리 임베딩 생성 실패: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # 임베딩 생성 실패 시 빈 결과 반환
            return []
        
        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled before image vector search")

        # PyTorch 를 사용한 검색 방식
        try:
            # config에서 통일된 dtype 설정 사용
            # 이미 상단에서 import한 RAGConfig 인스턴스 사용
            config_instance = RAGConfig()
            generator_dtype = getattr(config_instance, 'GENERATOR_TORCH_DTYPE', "auto")
            
            if generator_dtype == "auto":
                # auto인 경우 float32 사용 (FAISS 호환성)
                tensor_dtype = torch.float32
            else:
                # 기존 방식: GPU에서는 float16, CPU에서는 float32
                tensor_dtype = torch.float16 if self.device.type == "cuda" else torch.float32
                
            logger.info(f"Config에서 가져온 GENERATOR_TORCH_DTYPE: {generator_dtype}")
            logger.info(f"이미지 검색에 사용할 텐서 dtype: {tensor_dtype}")
            
            logger.info(f"이미지 검색에 사용할 텐서 dtype: {tensor_dtype}")
            
            # 쿼리 임베딩을 텐서로 변환 (명시적 dtype 지정)
            query_tensor = torch.tensor(query_embedding, device=self.device, dtype=tensor_dtype).unsqueeze(0)  # [1, dim]
            
            # FAISS 인덱스에서 벡터 추출
            if self.image_index.ntotal == 0:
                logger.warning("인덱스가 비어있습니다.")
                return []
            
            # 메타데이터에서 임베딩 추출
            # PKL 파일 우선 시도
            metadata = []
            index_vectors = None
            
            if os.path.exists(self.metadata_pkl_path):
                try:
                    import pickle
                    with open(self.metadata_pkl_path, 'rb') as f:
                        metadata = pickle.load(f)
                    logger.info(f"PKL 파일에서 이미지 메타데이터 로드 완료: {len(metadata)} 항목")
                    
                    # 임베딩 추출
                    if metadata and 'embedding' in metadata[0]:
                        index_vectors = np.array([item['embedding'] for item in metadata if 'embedding' in item])
                        logger.info(f"메타데이터에서 {len(index_vectors)} 개의 임베딩 추출")
                except Exception as e:
                    logger.error(f"PKL 메타데이터 로드 오류: {str(e)}")
            
            # 메타데이터에서 임베딩을 추출할 수 없는 경우 FAISS 직접 사용
            if index_vectors is None or len(index_vectors) == 0:
                logger.info("메타데이터에서 임베딩을 추출할 수 없어 FAISS 인덱스를 직접 사용합니다.")
                logger.info(f"실제 쿼리 임베딩을 FAISS에 전달: {query_embedding is not None}")
                return self._search_with_faiss(query_embedding, top_k)
                
            # 인덱스 텐서 생성 시에도 동일한 dtype 사용
            index_tensor = torch.tensor(index_vectors, device=self.device, dtype=tensor_dtype)  # [n, dim]
            
            # 디버깅을 위한 dtype 로깅
            logger.info(f"쿼리 텐서 dtype: {query_tensor.dtype}, 인덱스 텐서 dtype: {index_tensor.dtype}")
            
            # 정규화
            query_tensor = F.normalize(query_tensor, p=2, dim=1)
            index_tensor = F.normalize(index_tensor, p=2, dim=1)
            
            # 내적 계산 (코사인 유사도) - dtype 불일치 방지를 위한 안전장치
            try:
                similarities = torch.matmul(query_tensor, index_tensor.T)  # [1, n]
            except RuntimeError as e:
                if "expected mat1 and mat2 to have the same dtype" in str(e):
                    logger.warning(f"dtype 불일치 오류 발생, 명시적 변환 시도: {e}")
                    # 두 텐서를 동일한 dtype(float16)로 강제 변환
                    query_tensor = query_tensor.to(dtype=tensor_dtype)
                    index_tensor = index_tensor.to(dtype=tensor_dtype)
                    similarities = torch.matmul(query_tensor, index_tensor.T)
                    logger.info(f"{tensor_dtype} 강제 변환으로 성공적으로 유사도 계산 완료")
                else:
                    raise
            
            # 상위 k개 결과 가져오기
            config = RAGConfig()
            search_k = min(top_k, self.image_index.ntotal)
            scores, indices = torch.topk(similarities[0], k=search_k)
            
            # NumPy 배열로 변환
            scores = scores.cpu().numpy()
            indices = indices.cpu().numpy()
            
            logger.info(f"PyTorch 검색 완료: {len(indices)} 결과 찾음")
            
        except Exception as e:
            # 오류 발생 시 FAISS 방식으로 폴백
            logger.error(f"PyTorch 검색 오류, FAISS 방식으로 돌아감: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
            # FAISS 방식으로 검색
            query_embedding = query_embedding / np.linalg.norm(query_embedding)
            search_k = min(top_k, self.image_index.ntotal)
            scores, indices = self.image_index.search(np.array([query_embedding]), search_k)
            scores = scores[0]  # 2차원 배열에서 1차원으로 변환
            indices = indices[0]  # 2차원 배열에서 1차원으로 변환

        # 검색 시에만 메타데이터 파일 로드
        metadata = []
        
        # PKL 파일 우선 시도
        if os.path.exists(self.metadata_pkl_path):
            try:
                import pickle
                with open(self.metadata_pkl_path, 'rb') as f:
                    metadata = pickle.load(f)
                logger.info(f"PKL 파일에서 이미지 메타데이터 로드 완료: {len(metadata)} 항목")
            except Exception as e:
                logger.error(f"PKL 메타데이터 로드 오류: {str(e)}")
                metadata = []
        
        # PKL 파일이 없거나 로드 실패 시 JSON 파일 시도
        if not metadata and os.path.exists(self.metadata_json_path):
            try:
                with open(self.metadata_json_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                logger.info(f"JSON 파일에서 이미지 메타데이터 로드 완료: {len(metadata)} 항목")
            except Exception as e:
                logger.error(f"JSON 메타데이터 로드 오류: {str(e)}")
                metadata = []
            except Exception as e:
                logger.error(f"메타데이터 로드 중 오류 발생: {str(e)}")

        results = []
        for i, idx in enumerate(indices):
            score = float(scores[i])
            index = int(idx)
            
            # 기본 결과 정보
            result = {
                'score': score,
                'index': index,
                'id': f"doc_{index}",
                'title': f"문서 {index}",
                'page_num': 1,
                'text': f"인덱스 {index}에 해당하는 문서",
                'content_type': 'image'  # 이미지 콘텐츠 타입 추가
            }
            
            # 메타데이터가 있는 경우 실제 데이터로 대체
            if metadata and idx < len(metadata):
                meta_item = metadata[idx]
                # con_type을 content_type으로 변환하여 사용 (supported_types에 있는 타입만 처리)
                content_type = meta_item.get('con_type', 'image')
                # 지원하는 타입인지 확인 (기본값: image, chart)
                if content_type not in self.supported_types:
                    logger.debug(f"지원하지 않는 con_type: {content_type}, 기본값 'image'로 설정")
                    content_type = 'image'
                
                # 텍스트 필드 준비 - text가 없으면 title과 subtitle을 활용
                text = meta_item.get('text', '')
                if not text:
                    title = meta_item.get('title', '')
                    subtitle = meta_item.get('subtitle', '')
                    text = f"{title} {subtitle}".strip()
                
                # 캡션 필드 준비 - caption이 없으면 title을 활용
                caption = meta_item.get('caption', '')
                if not caption:
                    caption = meta_item.get('title', '')
                
                # 텍스트가 너무 길면 잘라내기
                if text and len(text) > 500:
                    text = text[:500] + '...'
                
                result.update({
                    'id': meta_item.get('id', result['id']),
                    'title': meta_item.get('title', result['title']),
                    'page_num': meta_item.get('page_num', result['page_num']),
                    'text': text,
                    'caption': caption,
                    'file_path': meta_item.get('file_path', ''),  # 파일 경로 추가
                    'tags': meta_item.get('tags', []),
                    'content_type': content_type,  # 이미지 콘텐츠 타입 추가
                    'description': meta_item.get('description', '')  # 설명 추가
                })
            
            results.append(result)

        logger.info(f"쿼리 '{query}'에 대한 검색 완료, 결과 수: {len(results)}")
        
        # 검색 결과의 content_type 확인
        content_types = {}
        for r in results[:10]:
            ct = r.get('content_type', 'None')
            if ct in content_types:
                content_types[ct] += 1
            else:
                content_types[ct] = 1
        logger.info(f"검색 결과의 content_type 분포: {content_types}")
        
        # 상위 3개 결과 상세 로깅
        for i, r in enumerate(results[:3]):
            logger.info(f"검색 결과 {i+1}: ID={r.get('id', 'N/A')}, 점수={r.get('score', 0):.4f}, content_type={r.get('content_type', 'N/A')}, con_type={r.get('con_type', 'N/A')}")
        
        # 임계값 필터링
        config = RAGConfig()
        
        # 지원하는 모든 타입(image, chart 등)에 대해 검색 결과 포함
        filtered_results = [r for r in results if r['score'] >= config.IMAGE_THRESHOLD and 
                           r.get('content_type', 'image') in self.supported_types]
        
        if len(filtered_results) < len(results):
            logger.info(f"임계값({config.IMAGE_THRESHOLD}) 및 타입 필터링 후 결과 수: {len(filtered_results)}")
            
        # 검색 결과의 content_type 분포 확인
        content_types_filtered = {}
        for r in filtered_results[:10]:
            ct = r.get('content_type', 'None')
            if ct in content_types_filtered:
                content_types_filtered[ct] += 1
            else:
                content_types_filtered[ct] = 1
        logger.info(f"필터링 후 content_type 분포: {content_types_filtered}")
        
        # 리랭커 적용 전 결과를 저장
        original_results = filtered_results.copy()
        
        # reranker를 사용하여 결과 재정렬 (매개변수 rerank도 고려)
        logger.info(f"Rerank 파라미터: {rerank}, 리랭커 사용 설정: {self.use_reranker}, 리랭커 객체 존재: {self.reranker is not None}, 결과 수: {len(filtered_results)}")
        # 항상 리랭킹 시도 - rerank 파라미터 무시
        if self.use_reranker and self.reranker and filtered_results:
            try:
                logger.info(f"Reranker를 사용하여 결과 재정렬 시작")
                # 취소 확인
                if cancellation_event and cancellation_event.is_set():
                    raise InterruptedError("Operation cancelled before image reranking")

                reranked_results = self.reranker.rerank(
                    query=query,
                    results=filtered_results,
                    top_k=top_k,
                    cancellation_event=cancellation_event
                )
                
                # 점수 정규화 제거 - 원본 점수 그대로 사용
                # 점수 분포 확인을 위한 로깅
                scores = [r['score'] for r in reranked_results]
                if scores:
                    logger.info(f"점수 분포 - 최소: {min(scores):.4f}, 최대: {max(scores):.4f}, 평균: {sum(scores)/len(scores):.4f}")
                
                # 원본 점수 그대로 사용 (정규화 없이)
                for result in reranked_results:
                    # 원본 점수를 그대로 유지
                    result['original_score'] = result.get('score', 0.0)  # 참조용으로 원본 점수 저장
                
                logger.info(f"Reranker를 사용하여 결과 재정렬 완료, 결과 수: {len(reranked_results)}")
                
                # 리랭킹된 이미지 결과 출력
                print(f"\n=== 이미지 리랭킹 결과 (top {min(len(reranked_results), 3)}) ===")
                for i, result in enumerate(reranked_results[:3]):
                    print(f"{i+1}. ID: {result.get('id', 'N/A')}")
                    print(f"   정규화 점수: {result.get('score', 0):.4f}")
                    print(f"   원본 점수: {result.get('original_score', 0):.4f}")
                    print(f"   제목: {result.get('title', '제목 없음')}")
                    print(f"   페이지: {result.get('page_num', 'N/A')}")
                    print(f"   설명: {result.get('description', '설명 없음')[:100]}...")
                    print()
                
                return reranked_results[:top_k]
            except Exception as e:
                logger.error(f"Reranker 사용 중 오류 발생: {str(e)}")
                # Reranker 오류 시 원래 결과 반환
                return original_results[:top_k]
        
        # top_k 제한
        return filtered_results[:top_k]
        
    def _search_with_faiss(self, query_embedding, top_k=None):
        """
        FAISS 인덱스를 직접 사용하여 검색
        
        Args:
            query_embedding: 쿼리 임베딩 벡터
            top_k: 반환할 최대 결과 수
            
        Returns:
            검색 결과 리스트 (메타데이터 포함)
        """
        # config에서 기본값 가져오기
        config = RAGConfig()
        top_k = top_k if top_k is not None else config.TOP_K
        
        # 디버깅: 입력 파라미터 확인
        logger.info(f"_search_with_faiss 호출됨: query_embedding is None = {query_embedding is None}, top_k = {top_k}")
        if query_embedding is not None:
            logger.info(f"쿼리 임베딩 타입: {type(query_embedding)}, 형태: {getattr(query_embedding, 'shape', 'N/A')}")
        
        try:
            # FAISS 인덱스가 비어있는지 확인
            if self.image_index.ntotal == 0:
                logger.warning("FAISS 인덱스가 비어있습니다.")
                return []
            
            # 쿼리 임베딩이 None인 경우 랜덤 검색
            if query_embedding is None:
                logger.warning("⚠️ 쿼리 임베딩이 None입니다! 랜덤 검색을 수행합니다.")
                # 랜덤 인덱스 선택
                indices = np.random.choice(self.image_index.ntotal, min(top_k, self.image_index.ntotal), replace=False)
                # 랜덤 점수를 0.1에서 0.5 사이로 설정하여 필터링되지 않도록 함
                scores = 0.1 + np.random.random(len(indices)) * 0.4  # 0.1~0.5 사이의 랜덤 점수
                logger.warning(f"랜덤 검색 결과: indices={indices[:3]}, scores={scores[:3]}")
            else:
                logger.info("✅ 쿼리 임베딩이 정상적으로 전달되었습니다. 실제 검색을 수행합니다.")
                # 쿼리 임베딩이 numpy 배열인지 확인
                if isinstance(query_embedding, torch.Tensor):
                    query_embedding = query_embedding.cpu().numpy()
                    
                # 쿼리 임베딩 차원 확인 및 조정
                if len(query_embedding.shape) == 1:
                    query_embedding = query_embedding.reshape(1, -1)
                    
                # 벡터 정규화 - 인덱싱 시 이미 정규화된 벡터가 저장되므로 쿼리 벡터만 정규화
                # 이미 정규화된 벡터 간의 내적은 코사인 유사도와 동일함
                norm = np.linalg.norm(query_embedding)
                if norm > 1e-10:  # 0으로 나누기 방지
                    query_embedding = query_embedding / norm
                logger.info(f"쿼리 임베딩 정규화 완료: 노름 = {np.linalg.norm(query_embedding):.4f}")
                    
                # FAISS 검색 수행
                search_k = min(top_k, self.image_index.ntotal)
                logger.info(f"FAISS 검색 시작: search_k={search_k}, 인덱스 전체 크기={self.image_index.ntotal}")
                
                # FAISS 검색 실행 - IndexFlatIP는 내적 기반 유사도 계산
                # 더 많은 결과를 가져와서 다양성 필터링 적용 (search_k의 2배)
                expanded_k = min(search_k * 2, self.image_index.ntotal)
                distances, indices = self.image_index.search(query_embedding, expanded_k)
                logger.info(f"FAISS 검색 결과(확장): distances={distances[0][:3]}, indices={indices[0][:3]}")
                
                # 결과 확인 - 모든 거리가 같은지 체크
                if len(distances[0]) > 1 and np.all(np.abs(distances[0] - distances[0][0]) < 1e-5):
                    logger.warning(f"모든 거리가 거의 동일함: {distances[0][0]:.6f}")
                    logger.warning(f"전체 거리 샘플: {distances[0][:5]}")
                    
                    # 거의 동일한 임베딩이 발견되면 다양성을 위해 랜덤 샘플링 추가
                    logger.warning("임베딩 다양성 부족 감지: 다양성 향상을 위한 처리 적용")
                    
                    # 원본 점수와 인덱스 저장
                    original_distances = distances[0].copy()
                    original_indices = indices[0].copy()
                    
                    # 다양성을 위해 약간의 랜덤 노이즈 추가 (0.001~0.01 사이)
                    noise = np.random.uniform(0.001, 0.01, size=len(original_distances))
                    adjusted_distances = original_distances * (1.0 - noise)
                    
                    # 정렬하여 새로운 순서 생성
                    sorted_idx = np.argsort(-adjusted_distances)  # 내림차순 정렬
                    distances = np.array([adjusted_distances[sorted_idx]])
                    indices = np.array([original_indices[sorted_idx]])
                    
                    logger.info(f"다양성 향상 처리 후 결과: distances={distances[0][:3]}, indices={indices[0][:3]}")
                
                # 코사인 유사도 값을 그대로 사용 (이미 정규화된 벡터 간의 내적이므로 코사인 유사도임)
                scores = distances[0]
                
                # 음수 유사도는 0으로 처리 (관련성 없음으로 간주)
                scores = np.maximum(scores, 0.0)
                
                # 인덱스 추출
                indices = indices[0]
                
                # 다양성 필터링 - 너무 유사한 결과 제거 (text_hash 기반)
                if len(indices) > search_k:
                    # 메타데이터 미리 로드
                    metadata_temp = []
                    if os.path.exists(self.metadata_pkl_path):
                        try:
                            with open(self.metadata_pkl_path, 'rb') as f:
                                metadata_temp = pickle.load(f)
                        except Exception as e:
                            logger.error(f"메타데이터 로드 오류: {str(e)}")
                    
                    # 다양성 필터링 적용
                    if metadata_temp:
                        filtered_indices = []
                        filtered_scores = []
                        seen_hashes = set()
                        
                        for idx, score in zip(indices, scores):
                            if idx >= len(metadata_temp):
                                continue
                                
                            # text_hash가 있으면 중복 체크
                            text_hash = metadata_temp[idx].get('text_hash', '')
                            if text_hash and text_hash in seen_hashes:
                                logger.info(f"중복 텍스트 필터링: 인덱스 {idx} 제외 (유사도: {score:.4f})")
                                continue
                                
                            # 해시 추가 및 결과 유지
                            if text_hash:
                                seen_hashes.add(text_hash)
                            filtered_indices.append(idx)
                            filtered_scores.append(score)
                            
                            # 원하는 개수에 도달하면 중단
                            if len(filtered_indices) >= search_k:
                                break
                        
                        # 필터링된 결과로 업데이트
                        if filtered_indices:
                            indices = np.array(filtered_indices)
                            scores = np.array(filtered_scores)
                            logger.info(f"다양성 필터링 후 결과 수: {len(indices)} (원래: {len(distances[0])})")
                        
                # 최종 결과 개수 제한
                if len(indices) > search_k:
                    indices = indices[:search_k]
                    scores = scores[:search_k]
                
                logger.info(f"처리된 점수: {scores[:3]}, 인덱스: {indices[:3]}")
                
            # 메타데이터 로드
            metadata = []
            if os.path.exists(self.metadata_pkl_path):
                try:
                    import pickle
                    with open(self.metadata_pkl_path, 'rb') as f:
                        metadata = pickle.load(f)
                    logger.info(f"PKL 파일에서 이미지 메타데이터 로드 완료: {len(metadata)} 항목")
                except Exception as e:
                    logger.error(f"FAISS 검색 중 메타데이터 로드 오류: {str(e)}")
                    
            # 결과 구성
            results = []
            for i, (idx, score) in enumerate(zip(indices, scores)):
                if idx < 0 or idx >= len(metadata):  # 유효하지 않은 인덱스 처리
                    continue
                    
                item = metadata[idx].copy() if idx < len(metadata) else {}
                item['score'] = float(score)
                item['index'] = int(idx)
                
                # content_type 필드 명시적으로 설정
                if 'con_type' in item:
                    content_type = item['con_type']
                    # 지원하는 타입인지 확인 (기본값: image, chart)
                    if content_type in self.supported_types:
                        item['content_type'] = content_type
                    else:
                        logger.debug(f"faiss_search: 지원하지 않는 con_type: {content_type}, 기본값 'image'로 설정")
                        item['content_type'] = 'image'
                else:
                    item['content_type'] = 'image'  # 기본값으로 'image' 설정
                results.append(item)
                
            logger.info(f"FAISS 직접 검색 완료, 결과 수: {len(results)}")
            return results
            
        except Exception as e:
            logger.error(f"FAISS 검색 중 오류 발생: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []

if __name__ == "__main__":
    print("이미지 검색기 스크립트 시작")
    config = RAGConfig()
    print("RAGConfig 로드 완료")
    try:
        searcher = ImageSearcher()
        print("ImageSearcher 초기화 완료")
        if searcher.reranker:
            print("Reranker 초기화 완료")
        else:
            print("Reranker 사용하지 않음")
    except Exception as e:
        print(f"ImageSearcher 초기화 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    while True:
        query = input("검색 쿼리를 입력하세요 (종료하려면 'exit' 입력): ")
        if query.lower() == 'exit':
            break
        
        # 사용자 정의 top_k 입력 받기 (선택 사항)
        top_k_input = input(f"검색 결과 수를 입력하세요 (기본값: {config.TOP_K}): ")
        top_k = int(top_k_input) if top_k_input.isdigit() else None
        
        results = searcher.search(query, top_k=top_k)
        
        # 검색 결과 출력
        print(f"\n[검색 결과] (최대 5개):")
        for i, result in enumerate(results[:5]):
            # 원래 점수가 있는 경우 함께 표시 (리랭크된 결과인 경우)
            score_display = f"{result['score']:.4f}"
            if 'original_score' in result:
                score_display += f" (\uc6d0래 점수: {result['original_score']:.4f})"
                print(f"{i+1}. {result['title']} (페이지 {result['page_num']}) - 유사도: {score_display} [리랭크됨]")
            else:
                print(f"{i+1}. {result['title']} (페이지 {result['page_num']}) - 유사도: {score_display}")
            
            print(f"   ID: {result['id']}")
            print(f"   인덱스: {result['index']}")
            caption = result.get('caption', '')
            print(f"   캡션: {caption[:200]}{'...' if len(caption) > 200 else ''}")
            print()
