import os
import json
import sys
import re
import time
import datetime
import requests
import numpy as np
from typing import List, Dict, Any, Tuple
from pydantic import BaseModel
import argparse
from PIL import Image
import torch
import faiss

# 상위 디렉토리 경로 추가 (config.py를 임포트하기 위해)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))
from config import RAGConfig
from embedding_system import VectorDBService

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from image_search_engine import ImageSearchEngine as ExternalImageSearchEngine

class ImageSearchEngine:
    def __init__(self, config: RAGConfig):
        """
        이미지 검색 엔진 초기화
        
        Args:
            config: RAG 설정 객체
        """
        self.config = config
        self.indices = {}
        self.metadata_lists = {}
        
        # QueryAnalyzer 초기화 (쿼리 분석을 위한 객체)
        self.query_analyzer = None

        self.model = None  # 모델 변수 초기화
        self.tokenizer = None  # 토크나이저 변수 초기화

        # VectorDBService 인스턴스 생성
        self.vector_db_service = VectorDBService(
            model_name=config.EMBEDDING_MODEL,
            vector_dimension=config.VECTOR_DIMENSION
        )

        # FAISS 인덱스 로드
        # self.indices = {}
        # self.metadata_lists = {}
        
        # 이미지 인덱스 로드
        self.image_index_path = os.path.join(config.INDEX_DIR, "image_index")
        self.image_metadata_path = os.path.join(config.INDEX_DIR, "image_metadata.json")
        self.indices['image'], self.metadata_lists['image'] = self._load_single_index(self.image_index_path, self.image_metadata_path)
        
        print("이미지 인덱스 로드 완료")
    
    def _load_single_index(self, index_path, metadata_path=None):
        """
        단일 FAISS 인덱스 및 메타데이터 로드
        
        Args:
            index_path: FAISS 인덱스 파일 경로 (확장자 제외)
            metadata_path: 메타데이터 JSON 파일 경로 (직접 지정)
        
        Returns:
            Tuple[faiss.Index, List[Dict[str, Any]]]: FAISS 인덱스와 메타데이터 리스트
        """
        # 인덱스 파일 경로에 .faiss 확장자 추가
        index_file = f"{index_path}.faiss"
        
        # 메타데이터 경로가 지정되지 않은 경우 기본 경로 사용
        if metadata_path is None:
            metadata_path = f"{index_path}_metadata.json"
        
        # FAISS 인덱스 로드
        if os.path.exists(index_file):
            print(f"FAISS 인덱스 로드 중: {index_file}")
            index = faiss.read_index(index_file)
            print(f"로드된 인덱스 벡터 수: {index.ntotal}")
        else:
            print(f"[WARNING] FAISS 인덱스 파일을 찾을 수 없습니다: {index_file}")
            # 빈 인덱스 생성
            dimension = self.config.VECTOR_DIMENSION
            index = faiss.IndexFlatL2(dimension)
            print(f"새로운 빈 인덱스 생성 (차원: {dimension})")
        
        # 메타데이터 로드
        metadata_list = []
        if os.path.exists(metadata_path):
            print(f"메타데이터 로드 중: {metadata_path}")
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata_list = json.load(f)
            print(f"로드된 메타데이터 항목 수: {len(metadata_list)}")
        else:
            print(f"[WARNING] 메타데이터 파일을 찾을 수 없습니다: {metadata_path}")
        
        return index, metadata_list
    
    def load_index(self):
        """
        FAISS 인덱스 및 메타데이터 로드
        """
        self.indices = {}
        self.metadata_lists = {}
        
        # 이미지 인덱스 로드
        self.indices['image'], self.metadata_lists['image'] = self._load_single_index(self.image_index_path, self.image_metadata_path)
        
        print("이미지 인덱스 로드 완료")
    
    def generate_text_embedding(self, text: str) -> np.ndarray:
        """
        텍스트에서 임베딩 생성 (VectorDBService의 함수 사용)
        
        Args:
            text: 임베딩할 텍스트
        
        Returns:
            텍스트 임베딩 벡터 (numpy 배열)
        """
        print(f"\n[DEBUG] 텍스트 임베딩 생성 시도: '{text[:50]}...'")
        try:
            embedding = self.vector_db_service.generate_text_embedding(text)
            embedding = embedding / np.linalg.norm(embedding)
            if embedding is None or (isinstance(embedding, np.ndarray) and np.all(embedding == 0)):
                print(f"[ERROR] 임베딩 생성 실패: 0 벡터 또는 None 반환됨")
            else:
                print(f"[SUCCESS] 임베딩 생성 성공: 차원={embedding.shape}, 노름={np.linalg.norm(embedding):.4f}")
                print(f"[DEBUG] 임베딩 샘플 (처음 5개 값): {embedding[:5]}")
            return embedding
        except Exception as e:
            print(f"[EXCEPTION] 임베딩 생성 중 예외 발생: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return np.zeros(self.config.VECTOR_DIMENSION)
    
    def search(self, query: str, top_k: int = None, use_hybrid: bool = False) -> List[Dict[str, Any]]:
        """
        사용자 쿼리로 관련 이미지 검색 - image_search_engine.py의 search 함수 사용
        
        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수 (None이면 기본값 사용)
            use_hybrid: 사용하지 않는 매개변수 (하위 호환성을 위해 유지)
        
        Returns:
            이미지 검색 결과 리스트
        """
        if top_k is None:
            top_k = getattr(self.config, 'TOP_K', 5)

        print(f"\n[DEBUG] 검색 시작: 쿼리='{query}', top_k={top_k}")
        
        # 현재 클래스의 인덱스와 메타데이터 사용
        # 외부 ImageSearchEngine 인스턴스 생성
        external_engine = ExternalImageSearchEngine(
            config=self.config,
            indices=self.indices,
            metadata_lists=self.metadata_lists
        )
        
        # 외부 search 함수 사용 (search_images 대신)
        results = external_engine.search(query, top_k=top_k)
        print(results)
        
        # 결과 형식 변환 (score -> similarity)
        for result in results:
            if 'score' in result:
                result['similarity'] = result['score'] * 100
                del result['score']

        print(f"[DEBUG] 검색 완료: {len(results)}개 결과 찾음")
        return results
    
    def list_image_metadata(self):
        """
        이미지 인덱스에 포함된 메타데이터 목록을 출력하는 함수
        """
        print("\n이미지 인덱스에 포함된 메타데이터 목록:")
        
        total_count = len(self.metadata_lists['image'])
        print(f"이미지 타입: {total_count}개 항목")
        
        print(f"총 항목 수: {total_count}")


def test_image_search():
    """
    이미지 검색 엔진 테스트 함수
    """
    # RAGConfig 객체 생성
    config = RAGConfig()
    
    # 이미지 검색 엔진 초기화
    engine = ImageSearchEngine(config)
    
    # 인덱스 로드
    engine.load_index()
    
    # 메타데이터 목록 출력
    engine.list_image_metadata()
    
    # 테스트 쿼리
    query = input("\n이미지 검색 쿼리를 입력하세요 (기본값: '테스트 이미지'): ") or "테스트 이미지"
    
    print("\n=== 이미지 검색 테스트 ===")
    print(f"이미지 검색 쿼리: {query}")
    
    # search 함수를 사용하여 검색 수행
    results = engine.search(query)
    print(f"이미지 검색 결과 수: {len(results)}")
    
    # 결과 출력
    for i, result in enumerate(results[:3], 1):
        similarity = result.get('similarity', 0.0)
        print(f"\n{i}. 유사도: {similarity:.2f}%")
        print(f"   ID: {result.get('id', 'N/A')}")
        if 'image_path' in result:
            print(f"   이미지 경로: {result['image_path']}")
        if 'caption' in result and result['caption']:
            print(f"   캡션: {result['caption']}")
        if 'title' in result and result['title']:
            print(f"   제목: {result['title']}")


if __name__ == "__main__":
    test_image_search()
