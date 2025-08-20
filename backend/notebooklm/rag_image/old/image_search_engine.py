import os
import json
import requests
import numpy as np
import faiss
from typing import List, Dict, Any, Optional
import sys

# Import RAGConfig from config.py
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))
from config import RAGConfig

class ImageSearchEngine:
    def __init__(self, config: RAGConfig, indices: Dict, metadata_lists: Dict):
        self.config = config
        self.indices = indices
        self.metadata_lists = metadata_lists

    def generate_text_embedding(self, text: str) -> np.ndarray:
        """
        텍스트에서 임베딩 생성
        
        Args:
            text: 임베딩할 텍스트
        
        Returns:
            텍스트 임베딩 벡터 (numpy 배열)
        """
        try:
            # Ollama API를 통해 임베딩 생성 요청
            response = requests.post(
                f"{self.config.OLLAMA_API_URL}/api/embeddings",
                json={
                    "model": self.config.EMBEDDING_MODEL,
                    "prompt": text
                }
            )
            response.raise_for_status()  # HTTP 오류 발생 시 예외 발생
            embedding = response.json()["embedding"]
            if not embedding:
                print("[WARNING] API 응답에서 임베딩 데이터를 찾을 수 없습니다. 기본 임베딩(zeros)을 사용합니다.")
                return np.zeros(self.config.VECTOR_DIMENSION, dtype=np.float32)
            if len(embedding) != self.config.VECTOR_DIMENSION:
                print(f"[WARNING] 임베딩 차원({len(embedding)})이 설정된 차원({self.config.VECTOR_DIMENSION})과 일치하지 않습니다. 기본 임베딩(zeros)을 사용합니다.")
                return np.zeros(self.config.VECTOR_DIMENSION, dtype=np.float32)
            embedding = np.array(embedding, dtype=np.float32)
            norm = np.linalg.norm(embedding)
            if norm == 0:
                print("[WARNING] 임베딩 벡터의 노름이 0입니다. 기본 임베딩(zeros)을 사용합니다.")
                return np.zeros(self.config.VECTOR_DIMENSION, dtype=np.float32)
            return embedding / norm
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] 텍스트 임베딩 생성 중 오류 발생: {str(e)}")
            return np.zeros(self.config.VECTOR_DIMENSION, dtype=np.float32)  # 오류 발생 시 0 벡터 반환

    def search_images(self, query: str, top_k: int = None, threshold: float = None) -> List[Dict[str, Any]]:
        if top_k is None:
            top_k = self.config.TOP_K
        if threshold is None:
            threshold = getattr(self.config, 'IMAGE_THRESHOLD', 0.5)  # 기본값 0.5 설정

        query_embedding = self.generate_text_embedding(query)
        if np.all(query_embedding == 0):
            print("[WARNING] 쿼리 임베딩이 생성되지 않았거나 모두 0입니다. 검색 결과가 없을 수 있습니다.")
            return []

        results = []
        media_type = 'image'
        if media_type in self.indices and self.indices[media_type].ntotal > 0:
            # FAISS 인덱스에서 검색
            distances, indices = self.indices[media_type].search(query_embedding.reshape(1, -1), min(top_k * 2, self.indices[media_type].ntotal))
            
            # 결과 처리
            for idx, dist in zip(indices[0], distances[0]):
                if idx >= 0 and idx < len(self.metadata_lists[media_type]):
                    score = 1.0 / (1.0 + dist)  # 거리를 유사도로 변환
                    if score >= threshold:
                        meta = self.metadata_lists[media_type][int(idx)]
                        res = meta.copy()
                        res['score'] = float(score)
                        results.append(res)
            
            # 유사도 점수로 정렬
            results.sort(key=lambda x: x['score'], reverse=True)
            results = results[:top_k]
        
        return results

    def _format_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formatted = []
        base_url = "file:///"
        for res in results:
            meta = res['metadata']
            media_type = res.get('media_type', 'unknown')
            file_path = meta.get('file_path', meta.get('source', ''))
            if file_path and not file_path.startswith(('http://', 'https://', 'file://')):
                if not os.path.isabs(file_path):
                    file_path = os.path.abspath(file_path)
                file_path = base_url + file_path.replace(' ', '%20')
            formatted.append({
                "url": file_path,
                "caption": meta.get('caption', meta.get('title', 'No caption available')),
                "score": res['score'],
                "type": media_type
            })
        return formatted

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        텍스트 쿼리로 검색을 수행합니다. caption 필드만 사용합니다.
        
        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수
        """
        media_type = 'image'
        if media_type not in self.indices or self.indices[media_type].ntotal == 0:
            print("로드된 이미지 인덱스가 없습니다.")
            return []
            
        # caption 필드에 가중치를 두기 위해 쿼리 확장
        caption_weighted_query = query
        # caption에 많은 가중치 부여 (쿼리를 3번 반복)
        for _ in range(3):
            caption_weighted_query += f" {query}"
        
        print(f"Caption 필드에 가중치 적용된 쿼리: '{caption_weighted_query[:50]}...'")

        
        # 쿼리 임베딩 생성 및 정규화
        query_embedding = self.generate_text_embedding(caption_weighted_query)
        query_embedding = query_embedding / np.linalg.norm(query_embedding)

        # 검색 수행 (내적 유사도)
        scores, indices = self.indices[media_type].search(np.array([query_embedding]), top_k)

        results = []
        for i, idx in enumerate(indices[0]):
            result = {'score': float(scores[0][i]), 'index': int(idx)}
            if self.metadata_lists[media_type] and idx >= 0 and idx < len(self.metadata_lists[media_type]):
                metadata = self.metadata_lists[media_type][idx]
                # 선택된 필드만 추출
                result.update({
                    # 'title': metadata.get('title', ''),
                    # 'page_num': metadata.get('page_num', ''),
                    # 'index': metadata.get('index', ''),
                    # 'tags': metadata.get('tags', []),
                    'caption': metadata.get('caption', ''),
                    'id': metadata.get('id', '')  # id는 결과 식별을 위해 포함
                })
            results.append(result)

        print(f"쿼리 '{query}'에 대한 검색 완료, 결과 수: {len(results)}")
        return results

    def hybrid_search(self, query: str, top_k: int = None, media_type: str = 'image') -> List[Dict[str, Any]]:
        """
        키워드 매칭과 시맨틱 검색을 결합한 하이브리드 검색
        
        Args:
            query: 검색 쿼리
            top_k: 반환할 상위 결과 수
            media_type: 검색 대상 미디어 타입 ('text' 또는 'image')
        
        Returns:
            List[Dict[str, Any]]: 하이브리드 검색 결과 리스트
        """
        if top_k is None:
            top_k = self.config.TOP_K

        semantic_results = self.search_images(query, top_k=top_k * 2)
        keyword_results = self.exact_match_search(query, top_k=top_k * 2, media_type=media_type)

        combined_results = {}
        for res in semantic_results:
            id_ = res.get('id', res.get('file_path', str(res)))
            combined_results[id_] = {
                'semantic': res.get('score', 0.0),
                'keyword': 0.0,
                'metadata': res
            }
        for res in keyword_results:
            id_ = res.get('id', res.get('file_path', str(res)))
            if id_ in combined_results:
                combined_results[id_]['keyword'] = res.get('score', 0.0)
            else:
                combined_results[id_] = {
                    'semantic': 0.0,
                    'keyword': res.get('score', 0.0),
                    'metadata': res
                }

        final_results = []
        semantic_weight = getattr(self.config, 'SEMANTIC_WEIGHT', 0.6)  # 기본값 0.6 설정
        keyword_weight = getattr(self.config, 'KEYWORD_WEIGHT', 0.4)    # 기본값 0.4 설정
        threshold = getattr(self.config, 'IMAGE_THRESHOLD', 0.5)        # 기본값 0.5 설정

        for id_, data in combined_results.items():
            score = (semantic_weight * data['semantic'] + 
                     keyword_weight * data['keyword'])
            if score >= threshold:
                data['metadata']['score'] = score
                final_results.append(data['metadata'])

        final_results.sort(key=lambda x: x['score'], reverse=True)
        return final_results[:top_k]

    def exact_match_search(self, query: str, top_k: int = None, media_type: str = 'image') -> List[Dict[str, Any]]:
        """
        키워드 기반 검색으로 정확한 일치를 찾습니다.
        
        Args:
            query: 검색 쿼리
            top_k: 반환할 상위 결과 수
            media_type: 검색 대상 미디어 타입 ('text' 또는 'image')
        
        Returns:
            List[Dict[str, Any]]: 키워드 검색 결과 리스트
        """
        if top_k is None:
            top_k = self.config.TOP_K

        results = []
        query_lower = query.lower()
        
        if media_type in self.metadata_lists:
            for meta in self.metadata_lists[media_type]:
                text_content = (meta.get('text', '') or '') + ' ' + (meta.get('title', '') or '') + ' ' + (meta.get('caption', '') or '')
                if text_content.lower().find(query_lower) != -1:
                    score = text_content.lower().count(query_lower) / len(text_content) if len(text_content) > 0 else 0
                    res = meta.copy()
                    res['score'] = score
                    results.append(res)
            
            results.sort(key=lambda x: x['score'], reverse=True)
            results = results[:top_k]
        
        return results
