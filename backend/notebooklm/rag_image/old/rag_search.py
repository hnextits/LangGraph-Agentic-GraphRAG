import os
import json
import sys
import re
import time
import datetime
import requests
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel
import argparse
from PIL import Image
import torch
from transformers import AutoTokenizer, AutoModel, AutoProcessor, Qwen2VLForConditionalGeneration
import faiss
from fastapi import FastAPI, Request
import os


# Import RAGConfig from rag_config
from rag_config import RAGConfig

# Import QueryAnalyzer from rag_router
try:
    from rag_router import QueryAnalyzer
except ImportError:
    # 상대 경로로 시도
    try:
        from .rag_router import QueryAnalyzer
    except ImportError:
        print("[WARNING] QueryAnalyzer를 import할 수 없습니다. 쿼리 분석 기능이 제한됩니다.")
        QueryAnalyzer = None

# 5. RAG 검색 엔진
class RAGSearchEngine:
    def __init__(self, config: RAGConfig):
        """
        RAG 검색 엔진 초기화
        
        Args:
            config: RAG 설정 객체
        """
        self.config = config
        self.indices = {}
        self.metadata_lists = {}
        
        # QueryAnalyzer 초기화 (쿼리 분석을 위한 객체)
        self.query_analyzer = None
        if QueryAnalyzer is not None:
            try:
                self.query_analyzer = QueryAnalyzer(use_ml=True)
                print("[INFO] QueryAnalyzer가 성공적으로 초기화되었습니다.")
            except Exception as e:
                print(f"[WARNING] QueryAnalyzer 초기화 실패: {str(e)}")
        else:
            print("[WARNING] QueryAnalyzer 클래스를 찾을 수 없어 쿼리 분석 기능이 제한됩니다.")

        self.model = None # 모델 변수 초기화
        self.tokenizer = None # 토크나이저 변수 초기화
        # self.processor는 로드 로직 안에서 설정되므로 여기서 초기화하지 않아도 됩니다.

        # Ollama API를 사용하기 위한 설정
        try:
            print(f"Ollama 임베딩 모델 설정 중: {config.MULTIMODAL_MODEL}...")
            
            # Ollama API를 사용하므로 실제 모델 로드는 필요 없음
            # 대신 API 호출을 위한 설정만 저장
            self.model = None
            self.processor = None
            self.tokenizer = None
            
            # Ollama API URL 설정
            self.ollama_api_url = "http://localhost:11434/api/embeddings"
            
            print(f"Ollama 임베딩 모델 설정 완료: {config.MULTIMODAL_MODEL}")
            
            # 벡터 차원 확인
            print(f"벡터 차원: {config.VECTOR_DIMENSION}")
            
            # DEVICE 설정 유지 (API 호출이므로 실제로는 사용되지 않음)
            config.DEVICE = "cpu"  # Ollama API를 사용하므로 실제 디바이스는 중요하지 않음

        except Exception as e:
            print(f"모델 로드 오류: {str(e)}")
            raise # 오류를 다시 발생시켜 프로그램이 중단되도록 함
        
        # FAISS 인덱스 로드
        self.indices = {}
        self.metadata_lists = {}
        
        # 텍스트 인덱스 로드
        self.text_index_path = "/home/nextits2/.conda/envs/workbox/faiss_index/text_index"
        self.text_metadata_path = "/home/nextits2/.conda/envs/workbox/faiss_index/text_metadata.json"
        self.indices['text'], self.metadata_lists['text'] = self._load_single_index(self.text_index_path, self.text_metadata_path)
        
        # 이미지 인덱스 로드
        self.image_index_path = "/home/nextits2/.conda/envs/workbox/faiss_index/image_index"
        self.image_metadata_path = "/home/nextits2/.conda/envs/workbox/faiss_index/image_metadata.json"
        self.indices['image'], self.metadata_lists['image'] = self._load_single_index(self.image_index_path, self.image_metadata_path)
        
        print("텍스트 및 이미지 인덱스 로드 완료")
    
    def _load_single_index(self, index_path, metadata_path=None):
        """단일 FAISS 인덱스 및 메타데이터 로드
        
        Args:
            index_path: FAISS 인덱스 파일 경로 (확장자 제외)
            metadata_path: 메타데이터 JSON 파일 경로 (직접 지정)
        """
        # 기본 인덱스 초기화
        index = faiss.IndexFlatIP(self.config.VECTOR_DIMENSION)
        metadata_list = []
        
        try:
            # 인덱스 파일 경로
            index_file = f"{index_path}.faiss"
            if not os.path.exists(index_file):
                print(f"[WARNING] 인덱스 파일이 존재하지 않습니다: {index_file}")
                return index, metadata_list
                
            # FAISS 인덱스 로드
            index = faiss.read_index(index_file)
            print(f"[INFO] FAISS 인덱스 로드 성공: {index_file}, 항목 수: {index.ntotal if hasattr(index, 'ntotal') else '알 수 없음'}")

            
            # 메타데이터 로드 - 직접 지정된 경로 사용
            if metadata_path and os.path.exists(metadata_path):
                meta_file = metadata_path
                print(f"[INFO] 직접 지정된 메타데이터 파일 사용: {meta_file}")
            else:
                # 기본 경로 시도
                if "text" in index_path:
                    meta_file = os.path.join(os.path.dirname(index_path), "text_metadata.json")
                elif "image" in index_path:
                    meta_file = os.path.join(os.path.dirname(index_path), "image_metadata.json")
                else:
                    # 기본 방식으로 시도
                    index_name = os.path.basename(index_path)
                    meta_file = os.path.join(os.path.dirname(index_path), f"{index_name}_metadata.json")
                
                print(f"[DEBUG] 기본 메타데이터 파일 경로: {meta_file}")
                print(f"[DEBUG] 파일 존재 여부: {os.path.exists(meta_file)}")
            
            # 메타데이터 파일이 존재하지 않을 경우 빈 리스트 반환
            if not os.path.exists(meta_file):
                print(f"[WARNING] 메타데이터 파일을 찾을 수 없습니다: {meta_file}")
                # 디렉토리에 있는 파일 목록 출력
                print(f"[DEBUG] 디렉토리 내용: {os.listdir(os.path.dirname(index_path))}")
                
                # 임시 더미 메타데이터 생성 (테스트용)
                if hasattr(index, 'ntotal') and index.ntotal > 0:
                    print(f"[INFO] 임시 더미 메타데이터 생성 ({index.ntotal} 항목)")
                    # 임시 더미 메타데이터 생성
                    for i in range(index.ntotal):
                        metadata_list.append({
                            "id": f"dummy_{i}",
                            "title": f"Dummy Item {i}",
                            "text": f"This is a dummy item {i} created because metadata file was not found.",
                            "tags": ["dummy", "auto-generated"],
                            "page_num": 1,
                            "source": "auto-generated"
                        })
                    print(f"[INFO] 임시 더미 메타데이터 생성 완료 ({len(metadata_list)} 항목)")
                return index, metadata_list
                
            if os.path.exists(meta_file):
                with open(meta_file, 'r', encoding='utf-8') as f:
                    metadata_list = json.load(f)
                print(f"[SUCCESS] 인덱스와 메타데이터가 성공적으로 로드되었습니다: {index_path}, 메타데이터: {meta_file}")
            else:
                print(f"[WARNING] 메타데이터 파일을 찾을 수 없습니다: {meta_file}")
                # 디렉토리에 있는 파일 목록 출력
                print(f"[DEBUG] 디렉토리 내용: {os.listdir(os.path.dirname(index_path))}")

                
        except Exception as e:
            print(f"[ERROR] 인덱스 로드 중 오류 발생 ({index_path}): {str(e)}")
            
        return index, metadata_list
    
    def load_index(self):
        """FAISS 인덱스 및 메타데이터 로드"""
        # 기본 인덱스 초기화 (실패 시에도 사용할 수 있도록)
        self.index = faiss.IndexFlatIP(self.config.VECTOR_DIMENSION)
        self.metadata_list = []
        
        try:
            # 인덱스 로드
            index_file = f"{self.index_path}.index"
            if not os.path.exists(index_file):
                print(f"[ERROR] 인덱스 파일이 존재하지 않습니다: {index_file}")
                return False
            
            # print(f"[DEBUG] FAISS 인덱스 로드 시도: {index_file}")
            self.index = faiss.read_index(index_file)
            print(f"[DEBUG] FAISS 인덱스 로드 성공. 차원 수: {self.index.d}, 벡터 수: {self.index.ntotal}")
            
            # 메타데이터 로드
            meta_file = f"{self.index_path}.meta.json"
            if not os.path.exists(meta_file):
                print(f"[ERROR] 메타데이터 파일이 존재하지 않습니다: {meta_file}")
                return False
            
            # print(f"[DEBUG] 메타데이터 파일 로드 시도: {meta_file}")
            with open(meta_file, "r", encoding="utf-8") as f:
                self.metadata_list = json.load(f)
            
            # 메타데이터와 인덱스의 벡터 수가 일치하는지 확인
            if len(self.metadata_list) != self.index.ntotal:
                print(f"[WARNING] 메타데이터 수({len(self.metadata_list)})와 인덱스의 벡터 수({self.index.ntotal})가 일치하지 않습니다.")
            
            # print(f"[SUCCESS] 인덱스와 메타데이터가 성공적으로 로드되었습니다: {self.index_path}")
            print(f"[INFO] 로드된 벡터 수: {self.index.ntotal}, 메타데이터 수: {len(self.metadata_list)}")
            
            # 인덱스가 비어있는지 확인
            if self.index.ntotal == 0:
                print("[WARNING] 로드된 인덱스에 벡터가 없습니다.")
                return False
                
            return True
            
        except Exception as e:
            import traceback
            print(f"[ERROR] 인덱스 로드 중 예외 발생: {str(e)}")
            print("[TRACEBACK]")
            traceback.print_exc()
            print("[WARNING] 기본 인덱스를 사용합니다.")
            return False
    

    
    def generate_text_embedding(self, text: str) -> np.ndarray:
        """쿼리 텍스트에서 임베딩 생성 (Ollama API 사용)"""
        # 기본 반환값 설정 (오류 발생 시 사용)
        default_embedding = np.zeros(self.config.VECTOR_DIMENSION)
        
        try:
            # 입력 텍스트 유효성 검사
            if not text or not isinstance(text, str):
                print(f"[ERROR] 유효하지 않은 입력 텍스트: {text}")
                return default_embedding
            
            # 텍스트 길이 제한
            if len(text) > 1000:
                print(f"[WARNING] 텍스트 길이 제한: {len(text)} -> 1000")
                text = text[:1000]
            
            # Ollama API 호출
            import requests
            
            print(f"[DEBUG] Ollama API 호출 중: {self.config.MULTIMODAL_MODEL}")
            
            try:
                response = requests.post(
                    self.ollama_api_url,
                    json={
                        "model": self.config.MULTIMODAL_MODEL,
                        "prompt": text
                    },
                    timeout=30  # 타임아웃 설정 (30초)
                )
                
                # 응답 확인
                if response.status_code == 200:
                    # API 응답에서 임베딩 추출
                    embedding = np.array(response.json()["embedding"], dtype=np.float32)
                    
                    # 차원 확인
                    if embedding.shape[0] != self.config.VECTOR_DIMENSION:
                        print(f"[WARNING] 임베딩 차원 불일치: {embedding.shape[0]} (기대값: {self.config.VECTOR_DIMENSION})")
                        if embedding.shape[0] < self.config.VECTOR_DIMENSION:
                            print("[WARNING] 임베딩 차원이 설정값보다 작습니다. 인덱스를 재생성해야 할 수 있습니다.")
                        else:
                            print("[WARNING] 임베딩 차원이 설정값보다 큽니다. 설정값을 업데이트하세요.")
                    
                    # 정규화 (NaN 방지)
                    norm = np.linalg.norm(embedding)
                    if norm > 1e-10:
                        embedding = embedding / norm
                    else:
                        print("[WARNING] 임베딩 norm이 너무 작아 정규화를 건너뜁니다.")
                    
                    print(f"[DEBUG] 최종 임베딩 차원: {embedding.shape}")
                    return embedding
                else:
                    print(f"[ERROR] Ollama API 오류: {response.status_code}, {response.text}")
                    return default_embedding
                    
            except requests.exceptions.RequestException as e:
                print(f"[ERROR] Ollama API 요청 실패: {str(e)}")
                # 대체 URL 시도 (설정된 경우)
                if hasattr(self.config, 'OLLAMA_FALLBACK_URL') and self.config.OLLAMA_FALLBACK_URL:
                    print(f"[INFO] 대체 Ollama API URL 시도: {self.config.OLLAMA_FALLBACK_URL}/api/embeddings")
                    try:
                        response = requests.post(
                            f"{self.config.OLLAMA_FALLBACK_URL}/api/embeddings",
                            json={
                                "model": self.config.MULTIMODAL_MODEL,
                                "prompt": text
                            },
                            timeout=30
                        )
                        
                        if response.status_code == 200:
                            embedding = np.array(response.json()["embedding"], dtype=np.float32)
                            norm = np.linalg.norm(embedding)
                            if norm > 1e-10:
                                embedding = embedding / norm
                            return embedding
                    except Exception as e2:
                        print(f"[ERROR] 대체 Ollama API 요청도 실패: {str(e2)}")
                
                return default_embedding
                
        except Exception as e:
            import traceback
            print(f"[ERROR] 텍스트 임베딩 생성 실패: {str(e)}")
            print("[TRACEBACK]")
            traceback.print_exc()
            # 오류 발생 시 기본 임베딩 반환
            return default_embedding
    
    def search(self, query: str, top_k: int = None, media_type: str = None, use_hybrid: bool = True) -> Dict[str, Any]:
        """사용자 쿼리로 관련 이미지와 텍스트 검색
        
        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수 (None이면 기본값 사용)
            media_type: 필터링할 미디어 타입 ('image', 'text', None)
                    'image'는 이미지만 반환, 'text'는 텍스트만 반환, None은 이미지와 텍스트 모두 반환
            use_hybrid: 하이브리드 검색(키워드 매칭 + 시맨틱 검색) 사용 여부
        
        Returns:
            딕셔너리 형태의 검색 결과:
            {
                'images': [이미지 결과 리스트],
                'texts': [텍스트 결과 리스트],
                'query': 원본 쿼리,
                'top_k': 요청된 top_k 값
            }
        """
        if not query.strip():
            return {'images': [], 'texts': [], 'query': query, 'top_k': top_k or self.config.TOP_K, 'has_results': False, 'total_results': 0}
            
        # 기본값 설정
        if top_k is None:
            top_k = self.config.TOP_K
            
        # 하이브리드 검색 사용 시
        if use_hybrid:
            print(f"하이브리드 검색 수행 중... (top_k: {top_k}, 미디어 타입: {media_type or '모든 타입'})")
            hybrid_results = self.hybrid_search(query, top_k=top_k, media_type=media_type)
            
            # 결과 포맷팅 (하이브리드 검색은 이미 텍스트와 이미지 결과가 분리되어 있음)
            text_results = hybrid_results.get('texts', [])
            image_results = hybrid_results.get('images', [])
            total_results = len(text_results) + len(image_results)
            
            return {
                'texts': text_results,
                'images': image_results,
                'query': query,
                'top_k': top_k,
                'has_results': total_results > 0,
                'total_results': total_results
            }
        
        # 기본값 설정은 이미 위에서 처리됨
            
        # 미디어 타입이 지정되지 않은 경우 먼저 설명 요청인지 확인
        if media_type is None:
            # 설명 요청인지 먼저 확인 (QueryAnalyzer 분석 전에 수행)
            query_lower = query.lower()
            explanation_keywords = ['설명', '설명해', '설명해줄', '설명해줘', '설명해주', '설명해줄래', '설명해주세요', '설명해줘요', '설명해봐', '설명해봐라', 'explain', 'describe', 'tell me about', 'what is']
            
            is_explanation_query = any(keyword in query_lower for keyword in explanation_keywords)
            
            if is_explanation_query:
                # 설명 요청이면 텍스트와 이미지 모두 검색
                media_type = None
                print(f"[INFO] 쿼리 '{query}'는 설명 요청으로 판단되어 모든 타입을 검색합니다.")
            # 설명 요청이 아닌 경우에만 QueryAnalyzer 사용
            elif self.query_analyzer is not None:
                try:
                    # QueryAnalyzer를 활용하여 쿼리 분석
                    analysis_result = self.query_analyzer.analyze(query)
                    print(f"[INFO] 쿼리 분석 결과: {analysis_result.index_types}, 분석 방법: {analysis_result.method}, 신뢰도: {analysis_result.confidence:.2f}")
                    
                    # 분석 결과에 따라 미디어 타입 결정
                    if len(analysis_result.index_types) == 1:
                        if analysis_result.index_types[0] == 'image':
                            media_type = 'image'
                            print(f"[INFO] 쿼리 '{query}'는 이미지 검색으로 분석되었습니다.")
                        elif analysis_result.index_types[0] == 'text':
                            media_type = 'text'
                            print(f"[INFO] 쿼리 '{query}'는 텍스트 검색으로 분석되었습니다.")
                    # 여러 타입이 감지된 경우 신뢰도와 우선순위를 고려하여 결정
                    elif len(analysis_result.index_types) > 1:
                        # 텍스트 관련 키워드가 있는지 확인 (분석, 요약, 설명 등)
                        text_priority_keywords = ['요약', '설명', '정의', '개념', '의미', 'analysis', 'summary', 'definition']
                        if any(keyword in query.lower() for keyword in text_priority_keywords):
                            media_type = 'text'
                            print(f"[INFO] 쿼리 '{query}'는 텍스트 우선 키워드를 포함하여 텍스트 검색으로 결정되었습니다.")
                        # 이미지 관련 키워드가 있는지 확인
                        elif 'image' in analysis_result.index_types and ('이미지' in query.lower() or '사진' in query.lower() or '그림' in query.lower()):
                            media_type = 'image'
                            print(f"[INFO] 쿼리 '{query}'는 이미지 우선 키워드를 포함하여 이미지 검색으로 결정되었습니다.")
                        # 그 외의 경우 신뢰도가 높은 타입 선택
                        elif analysis_result.confidence > 0.5:
                            # 첫 번째 타입을 선택 (일반적으로 가장 신뢰도가 높은 타입)
                            media_type = analysis_result.index_types[0]
                            print(f"[INFO] 쿼리 '{query}'는 신뢰도 {analysis_result.confidence:.2f}로 {media_type} 검색으로 결정되었습니다.")
                except Exception as e:
                    print(f"[WARNING] 쿼리 분석 중 오류 발생: {str(e)}")
                    # 오류 발생 시 기본값 유지
                    media_type = None
                
            print(f"[INFO] 최종 결정된 미디어 타입: {media_type or '모든 타입'}")
        elif media_type is None:
            # QueryAnalyzer가 없는 경우 기본 키워드 기반 분석 시도
            query_lower = query.lower()
            image_keywords = ['이미지', '사진', '그림', '보여줘', '보여주', '보여달라', 'image', 'picture', 'photo', 'show me']
            text_keywords = ['텍스트', '문서', '글', 'text', 'document']
            explanation_keywords = ['설명', '설명해', '설명해줄', '설명해줘', '설명해주', '설명해줄래', '설명해주세요', '설명해줘요', '설명해봐', '설명해봐라', 'explain', 'describe', 'tell me about', 'what is']
            
            # 설명 요청인지 확인
            if any(keyword in query_lower for keyword in explanation_keywords):
                media_type = None  # 설명 요청은 모든 타입 검색
                print(f"[INFO] 쿼리 '{query}'는 설명 요청으로 판단되어 모든 타입을 검색합니다.")
            elif any(keyword in query_lower for keyword in image_keywords) and not any(keyword in query_lower for keyword in text_keywords):
                media_type = 'image'
                print(f"[INFO] 쿼리 '{query}'는 이미지 검색으로 분석되었습니다.")
            elif any(keyword in query_lower for keyword in text_keywords) and not any(keyword in query_lower for keyword in image_keywords):
                media_type = 'text'
                print(f"[INFO] 쿼리 '{query}'는 텍스트 검색으로 분석되었습니다.")
            else:
                print(f"[INFO] 쿼리 '{query}'의 미디어 타입을 분석할 수 없습니다. 모든 타입을 검색합니다.")
            
        # 쿼리 임베딩 생성
        try:
            query_embedding = self.generate_text_embedding(query)
            
            if query_embedding is None:
                print("[ERROR] 쿼리 임베딩 생성 실패: generate_text_embedding이 None을 반환했습니다.")
                return {'images': [], 'texts': [], 'query': query, 'top_k': top_k}
            
            # 정규화
            try:
                norm = np.linalg.norm(query_embedding)
                if norm > 1e-10:
                    query_embedding = query_embedding / norm
                else:
                    print("[WARNING] 쿼리 임베딩의 norm이 너무 작아 정규화를 건너뜁니다.")
            except Exception as norm_error:
                print(f"[WARNING] 쿼리 임베딩 정규화 실패: {str(norm_error)}")
                
        except Exception as e:
            import traceback
            error_msg = f"[ERROR] 쿼리 임베딩 생성 실패: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            return {'images': [], 'texts': [], 'query': query, 'top_k': top_k, 'error': str(e)}
        
        # 이미지와 텍스트 검색 결과 초기화
        image_results = []
        text_results = []
        
        # 검색할 미디어 타입 결정
        search_types = []
        if media_type is None:
            search_types = ['text', 'image']  # 기본값: 텍스트와 이미지 모두 검색
        elif media_type == 'image':
            search_types = ['image']
        elif media_type == 'text':
            search_types = ['text']
        
        # 각 미디어 타입별로 검색 수행
        for search_type in search_types:
            if search_type not in self.indices or search_type not in self.metadata_lists:
                print(f"[WARNING] {search_type} 인덱스 또는 메타데이터를 찾을 수 없습니다.")
                continue
                
            index = self.indices[search_type]
            metadata_list = self.metadata_lists[search_type]
            
            # 메타데이터 리스트 상태 확인
            print(f"[DEBUG] {search_type} 메타데이터 리스트 길이: {len(metadata_list)}")
            if len(metadata_list) == 0:
                print(f"[WARNING] {search_type} 메타데이터 리스트가 비어 있습니다!")
            else:
                print(f"[DEBUG] {search_type} 메타데이터 첫 항목 키: {list(metadata_list[0].keys()) if metadata_list else '없음'}")
                print(f"[DEBUG] {search_type} 메타데이터 마지막 항목 인덱스: {len(metadata_list)-1}")
                print(f"[DEBUG] {search_type} 인덱스 총 항목 수: {index.ntotal if hasattr(index, 'ntotal') else '알 수 없음'}")
                print(f"[DEBUG] {search_type} 인덱스 차원: {index.d if hasattr(index, 'd') else '알 수 없음'}")
                print(f"[DEBUG] {search_type} 인덱스 타입: {type(index).__name__}")
                if len(metadata_list) > 0 and isinstance(metadata_list[0], dict):
                    print(f"[DEBUG] {search_type} 메타데이터 첫 항목 예시: {metadata_list[0].get('title', '제목 없음')[:30]}...")
                else:
                    print(f"[WARNING] {search_type} 메타데이터 형식이 올바르지 않습니다: {type(metadata_list)}")
                    if metadata_list and len(metadata_list) > 0:
                        print(f"[DEBUG] 첫 항목 형식: {type(metadata_list[0])}")

            
            try:
                print(f"[DEBUG] {search_type} 검색 시작")
                
                # FAISS 검색 수행
                k = min(top_k, index.ntotal) if hasattr(index, 'ntotal') else top_k
                print(f"[DEBUG] {search_type} 검색: 상위 {k}개 결과 요청")
                
                # 쿼리 임베딩을 float32로 변환하여 검색
                query_embedding_float32 = query_embedding.astype(np.float32)
                distances, indices = index.search(
                    query_embedding_float32.reshape(1, -1), 
                    k
                )
                
                # 결과 처리
                for dist, idx in zip(distances[0], indices[0]):
                    # 인덱스 범위 검사 및 예외 처리 강화
                    if idx < 0 or idx >= len(metadata_list):
                        print(f"[WARNING] 유효하지 않은 인덱스 발견: {idx}, 메타데이터 리스트 길이: {len(metadata_list)}")
                        continue
                        
                    try:
                        # 딥코피를 통해 안전하게 처리
                        result = metadata_list[idx].copy() if isinstance(metadata_list[idx], dict) else {"error": "Invalid metadata format"}
                        similarity = float(1.0 - dist)  # 거리를 유사도로 변환 (1 - 거리)
                        result["similarity"] = similarity
                        result["search_fields"] = ["page_num", "text", "tags", "index"]
                        
                        # 유사도 threshold 적용
                        threshold = self.config.IMAGE_RELEVANCE_THRESHOLD if search_type == 'image' else self.config.TEXT_RELEVANCE_THRESHOLD
                        if similarity < threshold:
                            print(f"[INFO] {search_type} 결과 필터링: 유사도 {similarity:.4f}가 threshold {threshold} 미만")
                            continue
                        
                        if search_type == 'image':
                            image_results.append(result)
                        else:  # text
                            text_results.append(result)
                    except Exception as e:
                        print(f"[ERROR] 검색 결과 처리 중 오류: {str(e)}, 인덱스: {idx}")
                        import traceback
                        traceback.print_exc()
                
                print(f"[DEBUG] {search_type} 검색 완료: {len(image_results) if search_type == 'image' else len(text_results)}개 결과")
                
            except Exception as search_error:
                print(f"[ERROR] {search_type} 검색 중 오류: {str(search_error)}")
                import traceback
                traceback.print_exc()
        
        # 결과 정렬 (유사도 기준 내림차순)
        image_results = sorted(image_results, key=lambda x: x.get('similarity', 0), reverse=True)[:top_k]
        text_results = sorted(text_results, key=lambda x: x.get('similarity', 0), reverse=True)[:top_k]
        
        # media_type에 따라 결과 필터링
        if media_type == 'image':
            text_results = []
        elif media_type == 'text':
            image_results = []
            
        # 결과를 로그로 출력하여 확인
        print(f"[DEBUG] 최종 결과 - 텍스트: {len(text_results)}개, 이미지: {len(image_results)}개")
        
        # 결과가 있으면 예시 출력
        if text_results:
            print(f"[DEBUG] 텍스트 결과 첫 항목 예시: {text_results[0].get('title', '제목 없음')[:30]}...")
        if image_results:
            print(f"[DEBUG] 이미지 결과 첫 항목 예시: {image_results[0].get('title', '제목 없음')[:30]}...")
            
        # 결과 반환
        results = {
            'images': image_results,
            'texts': text_results,
            'query': query,
            'top_k': top_k,
            # 추가 필드 - 결과가 있는지 표시
            'has_results': len(text_results) > 0 or len(image_results) > 0,
            'total_results': len(text_results) + len(image_results)
        }
        
        return results
    
    def _format_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """검색 결과를 클라이언트에 적합한 형태로 포맷팅"""
        formatted_results = []
        
        for result in results:
            # 결과 형식 확인 - 새 검색 결과는 바로 메타데이터와 유사도를 포함
            if "metadata" in result and "similarity" in result:
                # 이전 형식의 결과
                metadata = result["metadata"]
                similarity = result["similarity"]
                rank = result.get("rank", 0)
                
                # 기본 필드 설정
                formatted_item = {
                    "similarity": similarity,
                    "rank": rank
                }
                
                # 메타데이터 필드 복사
                for key, value in metadata.items():
                    formatted_item[key] = value
            else:
                # 새 형식의 결과 (결과가 이미 메타데이터와 유사도를 포함)
                formatted_item = result.copy()
            
            # 파일 경로가 있는지 확인하고 정규화
            if "file_path" in formatted_item and formatted_item["file_path"]:
                # 파일 경로 정규화 (중복 슬래시 제거 등)
                file_path = os.path.normpath(formatted_item["file_path"])
                formatted_item["file_path"] = file_path
                
                # 이미지 URL 설정
                if file_path.startswith(self.config.IMAGE_BASE_PATH):
                    # 전체 경로 사용
                    formatted_item["image_url"] = file_path
                else:
                    # 파일이 기본 경로에 없는 경우 경로 추가
                    full_path = os.path.join(self.config.IMAGE_BASE_PATH, os.path.basename(file_path))
                    formatted_item["image_url"] = full_path
                
                # 디버그 로그 추가
                print(f"이미지 URL 설정: {formatted_item['image_url']}")
                
                # URL 인코딩 적용 (파일 시스템 경로를 사용하므로 이 부분은 제거)
                
                # 이미지 여부 확인 및 타입 설정
                is_image = any(file_path.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp"])
                formatted_item["type"] = "image" if is_image else "text"
            
            # 캡션 설정
            if "caption" not in formatted_item:
                if "text" in formatted_item and formatted_item["text"]:
                    formatted_item["caption"] = formatted_item["text"]
                else:
                    formatted_item["caption"] = formatted_item.get("title", "이미지 캡션 없음")
            
            # 타입이 아직 설정되지 않은 경우 기본값 설정
            if "type" not in formatted_item:
                formatted_item["type"] = "text"
            
            formatted_results.append(formatted_item)
        
        return formatted_results

    # 하이브리드 검색 함수 (키워드 매칭 + 시맨틱 검색)
    def hybrid_search(self, query: str, top_k: int = 5, media_type: str = None):
        """키워드 매칭과 시맨틱 검색을 결합한 하이브리드 검색
        
        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수
            media_type: 검색할 미디어 타입 ('image', 'text', None)
            
        Returns:
            하이브리드 검색 결과 목록 (이미지와 텍스트 결과 각각 top_k 개씩)
        """
        print(f"하이브리드 검색 수행 중... (top_k: {top_k}, 미디어 타입: {media_type or '모든 타입'})")
        
        # 1. 키워드 매칭 검색 수행
        print("정확한 텍스트 매칭 검색 수행 중...")
        keyword_results = self.exact_match_search(query, top_k=top_k*2, media_type=media_type)  # 더 많은 결과 가져오기
        
        # 2. 시맨틱 검색 수행 (하이브리드 플래그를 False로 설정하여 재귀 방지)
        print("임베딩 기반 검색 수행 중...")
        semantic_search_results = self.search(query, top_k=top_k*2, media_type=media_type, use_hybrid=False)
        
        # 미디어 타입에 따라 결과 가져오기
        semantic_results = []
        if media_type == 'image':
            semantic_results = semantic_search_results.get("images", [])
        elif media_type == 'text':
            semantic_results = semantic_search_results.get("texts", [])
        else:  # None - 모든 타입
            semantic_results = semantic_search_results.get("texts", []) + semantic_search_results.get("images", [])
        
        # 3. 결과 통합 및 중복 제거
        combined_results = {}
        
        # 키워드 결과 처리 (가중치 부여)
        keyword_weight = 0.6  # 키워드 매칭에 더 높은 가중치
        for item in keyword_results:
            item_id = item.get("id", str(id(item)))
            # 키워드 매칭 점수에 가중치 적용
            item["final_score"] = item.get("similarity", 0) * keyword_weight
            item["match_type"] = "keyword"
            combined_results[item_id] = item
        
        # 시맨틱 결과 처리
        semantic_weight = 0.4
        for item in semantic_results:
            item_id = item.get("id", str(id(item)))
            semantic_score = item.get("similarity", 0) * semantic_weight
            
            if item_id in combined_results:
                # 이미 키워드 결과에 있으면 점수 합산
                combined_results[item_id]["final_score"] += semantic_score
                # 출처 표시
                combined_results[item_id]["match_type"] = "hybrid"
            else:
                # 새로운 항목 추가
                item["final_score"] = semantic_score
                item["match_type"] = "semantic"
                combined_results[item_id] = item
        
        # 4. 미디어 타입별로 분류 및 정렬
        results_list = list(combined_results.values())
        
        # 미디어 타입별로 분류
        text_results = []
        image_results = []
        
        for item in results_list:
            media_type_item = item.get("media_type", "text")
            if media_type_item == "image":
                image_results.append(item)
            else:
                text_results.append(item)
        
        # 각 타입별로 점수 정렬
        text_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        image_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        
        # 임계값 필터링 적용
        filtered_text_results = []
        for item in text_results:
            if item.get("final_score", 0) >= self.config.TEXT_RELEVANCE_THRESHOLD:
                filtered_text_results.append(item)
            else:
                print(f"[INFO] 하이브리드 텍스트 결과 필터링: 최종 점수 {item.get('final_score', 0):.4f}가 threshold {self.config.TEXT_RELEVANCE_THRESHOLD} 미만")
        
        filtered_image_results = []
        for item in image_results:
            if item.get("final_score", 0) >= self.config.IMAGE_RELEVANCE_THRESHOLD:
                filtered_image_results.append(item)
            else:
                print(f"[INFO] 하이브리드 이미지 결과 필터링: 최종 점수 {item.get('final_score', 0):.4f}가 threshold {self.config.IMAGE_RELEVANCE_THRESHOLD} 미만")
        
        # 각 타입별로 top_k 개씩 선택
        top_text_results = filtered_text_results[:top_k]
        top_image_results = filtered_image_results[:top_k]
        
        print(f"하이브리드 검색 완료: 텍스트 {len(top_text_results)}개, 이미지 {len(top_image_results)}개 결과")
        
        # 분리된 결과 반환
        return {
            'texts': self._format_results(top_text_results),
            'images': self._format_results(top_image_results)
        }

    # 정확한 텍스트 매칭 검색 함수
    def exact_match_search(self, query: str, top_k: int = 5, media_type: str = None):
        """키워드 기반 검색 함수 - 메타데이터의 텍스트 필드에서 키워드 검색
        Args:
            query: 검색 쿼리
            top_k: 반환할 결과 수
            media_type: 검색할 미디어 타입 ('text', 'image', None=모두)
        Returns:
            검색 결과 리스트 (유사도 점수 포함)
        """
        print(f"정확한 텍스트 매칭 검색 수행 중...")
        
        # 결과를 저장할 딕셔너리 (중복 방지)
        results_dict = {}
        
        # 검색할 미디어 타입 결정
        if media_type == 'text':
            search_types = ['text']
        elif media_type == 'image':
            search_types = ['image']
        else:  # None - 모든 타입
            search_types = ['text', 'image']
            
        # 쿼리를 키워드로 분리 (콤마, 공백 등으로 구분)
        # 먼저 쿼리에서 큰따옴표와 작은따옴표 제거
        clean_query = query.replace('"', '').replace("'", '')
        keywords = [kw.strip() for kw in re.split(r'[,\s]+', clean_query) if kw.strip()]
        print(f"검색 키워드: {keywords}")
        print(f"키워드 타입: {type(keywords)}, 각 항목 타입: {[type(kw) for kw in keywords]}")
        
        if not keywords:
            # 키워드가 추출되지 않으면 원래 쿼리에서 따옴표만 제거하여 사용
            keywords = [clean_query]
        
        # 각 미디어 타입에 대해 모든 키워드 검색
        for search_type in search_types:
            if search_type not in self.metadata_lists or not self.metadata_lists[search_type]:
                print(f"경고: {search_type} 메타데이터가 없습니다.")
                continue
                
            metadata_list = self.metadata_lists[search_type]
            
            # 각 메타데이터에 대해 모든 키워드 검색
            for metadata in metadata_list:
                # 검색할 텍스트 필드 결정 (미디어 타입에 따라 다름)
                searchable_text = ""
                text_fields = []
                
                # 미디어 타입에 따라 검색할 필드 결정
                if search_type == 'text':
                    # 텍스트는 page_num, text, tags 필드를 검색
                    if "text" in metadata and metadata["text"]:
                        # 문자열이 아닌 경우 문자열로 변환
                        if isinstance(metadata["text"], str):
                            text_fields.append(metadata["text"])
                        else:
                            text_fields.append(str(metadata["text"]))
                    if "page_num" in metadata and metadata["page_num"]:
                        text_fields.append(str(metadata["page_num"]))
                    if "tags" in metadata and metadata["tags"]:
                        if isinstance(metadata["tags"], list):
                            # 모든 태그를 문자열로 변환하여 조인
                            text_fields.append(" ".join([str(tag) for tag in metadata["tags"]]))
                        else:
                            text_fields.append(str(metadata["tags"]))
                elif search_type == 'image':
                    # 이미지는 page_num, index, text, tags 필드를 검색
                    if "text" in metadata and metadata["text"]:
                        if isinstance(metadata["text"], str):
                            text_fields.append(metadata["text"])
                        else:
                            text_fields.append(str(metadata["text"]))
                    if "page_num" in metadata and metadata["page_num"]:
                        text_fields.append(str(metadata["page_num"]))
                    if "index" in metadata and metadata["index"]:
                        text_fields.append(str(metadata["index"]))
                    if "tags" in metadata and metadata["tags"]:
                        if isinstance(metadata["tags"], list):
                            # 모든 태그를 문자열로 변환하여 조인
                            text_fields.append(" ".join([str(tag) for tag in metadata["tags"]]))
                        else:
                            text_fields.append(str(metadata["tags"]))
                    
                # 모든 필드를 합쳐서 검색 가능한 텍스트 생성
                searchable_text = " ".join(text_fields).lower()
                
                if not searchable_text:
                    continue
                    
                metadata_id = metadata.get("id", str(id(metadata)))
                
                # 각 키워드에 대해 검색
                keyword_matches = 0
                total_similarity = 0.0
                
                for keyword in keywords:
                    keyword_lower = keyword.lower()
                    if keyword_lower in searchable_text:
                        keyword_matches += 1
                        
                        # 유사도 점수 계산 (텍스트 내 위치에 따라 계산)
                        position = searchable_text.find(keyword_lower)
                        # 시작 부분에 가까울수록 높은 점수 부여
                        similarity = 1.0 - (position / (len(searchable_text) + 1))
                        total_similarity += similarity
                
                # 하나 이상의 키워드가 일치하면 결과에 추가
                if keyword_matches > 0:
                    # 평균 유사도 계산
                    avg_similarity = total_similarity / len(keywords)
                    # 키워드 일치 비율 계산 (가중치 부여)
                    match_ratio = keyword_matches / len(keywords)
                    # 최종 유사도 = 평균 유사도 * 키워드 일치 비율 (더 많은 키워드가 일치할수록 높은 점수)
                    final_similarity = avg_similarity * match_ratio
                    
                    result = metadata.copy()
                    result["similarity"] = final_similarity
                    result["keyword_matches"] = keyword_matches
                    result["total_keywords"] = len(keywords)
                    result["media_type"] = search_type  # 미디어 타입 추가
                    
                    # 중복 결과 방지 (더 높은 유사도 점수로 업데이트)
                    if metadata_id not in results_dict or results_dict[metadata_id]["similarity"] < final_similarity:
                        results_dict[metadata_id] = result
            
        # 결과 리스트로 변환
        results = list(results_dict.values())
        
        # 유사도 점수에 따라 정렬
        results.sort(key=lambda x: x["similarity"], reverse=True)
        
        print(f"검색된 결과 수: {len(results)}")
        
        # top_k 결과만 반환
        return results[:top_k]

    # 메타데이터 목록 출력 함수
    def list_metadata(self):
        """인덱스에 포함된 메타데이터 목록을 출력하는 함수"""
        print("\n인덱스에 포함된 메타데이터 목록:")
        
        total_count = 0
        for media_type, metadata_list in self.metadata_lists.items():
            total_count += len(metadata_list)
            print(f"{media_type} 타입: {len(metadata_list)}개 항목")
        
        print(f"총 항목 수: {total_count}")
        
        # 각 미디어 타입별로 메타데이터 출력
        for media_type, metadata_list in self.metadata_lists.items():
            print(f"\n=== {media_type.upper()} 타입 메타데이터 ===\n")
            
            for i, metadata in enumerate(metadata_list[:5]):  # 각 타입별로 최대 5개만 출력
                print(f"\n[{media_type} 항목 {i+1}]")
                # 주요 메타데이터 필드 출력
                if "title" in metadata:
                    print(f"제목: {metadata['title']}")
                if "page_num" in metadata:
                    print(f"페이지: {metadata['page_num']}")
                if "id" in metadata:
                    print(f"ID: {metadata['id']}")
                if "file_path" in metadata:
                    print(f"파일 경로: {metadata['file_path']}")
                if "text" in metadata:
                    # 텍스트가 너무 길면 잘라서 표시
                    text = metadata["text"]
                    preview = text[:100] + "..." if len(text) > 100 else text
                    print(f"텍스트 미리보기: {preview}")
            
            if len(metadata_list) > 5:
                print(f"... 외 {len(metadata_list) - 5}개 항목 더 있음")
                print("-----------------------------\n")