"""
Summary Index System
요약 인덱스 기반 문서 검색 시스템 (RAG)
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from pathlib import Path
from loguru import logger
import json
from datetime import datetime

from .sglang_client import SGLangClient
from .md_parser import MDParser


class MDSummaryIndex:
    """
    MD 문서 요약 인덱스 시스템
    기존 nextitslm의 요약 기능과 동일한 인터페이스 제공
    """
    
    def __init__(self, sglang_endpoints: List[str] = None):
        """
        Args:
            sglang_endpoints: SGLang 서버 엔드포인트 리스트
        """
        self.client = SGLangClient(sglang_endpoints)
        self.parser = MDParser()
        
        # 문서 저장소
        self.documents: List[Dict[str, any]] = []
        self.summaries: List[str] = []
        self.doc_id_map: Dict[str, int] = {}  # filename -> index
        
        logger.info("MDSummaryIndex 초기화 완료")
    
    def add_document(self, doc_id: str, content: str = None, file_path: str = None):
        """
        문서 추가
        
        Args:
            doc_id: 문서 ID (파일명)
            content: 문서 내용 (직접 제공)
            file_path: 문서 파일 경로 (파일에서 읽기)
        """
        if content is None and file_path is None:
            raise ValueError("content 또는 file_path 중 하나는 필수입니다.")
        
        # 파일에서 읽기
        if file_path:
            content = self.parser.read_file(file_path)
            if not content:
                logger.warning(f"파일 읽기 실패: {file_path}")
                return
        
        # 문서 추가
        doc_index = len(self.documents)
        self.documents.append({
            "id": doc_id,
            "content": content,
            "file_path": file_path,
            "added_at": datetime.now().isoformat()
        })
        self.doc_id_map[doc_id] = doc_index
        
        logger.info(f"문서 추가: {doc_id} (인덱스: {doc_index})")
    
    def add_documents_batch(self, file_paths: List[str]):
        """
        여러 문서를 배치로 추가
        
        Args:
            file_paths: 파일 경로 리스트
        """
        for file_path in file_paths:
            filename = Path(file_path).name
            self.add_document(filename, file_path=file_path)
        
        logger.info(f"배치 문서 추가 완료: {len(file_paths)}개")
    
    def generate_summaries(self, max_tokens: int = 2000):
        """
        모든 문서에 대한 요약 생성
        
        Args:
            max_tokens: 요약 최대 토큰 수
        """
        logger.info(f"요약 생성 시작: {len(self.documents)}개 문서")
        
        for i, doc in enumerate(self.documents):
            logger.info(f"요약 생성 중... ({i+1}/{len(self.documents)}): {doc['id']}")
            
            try:
                # 요약 생성 (기존 AnswerGenerator와 동일한 방식)
                summary = self.client.generate_answer(doc['content'], max_tokens)
                self.summaries.append(summary)
                
                logger.info(f"요약 생성 완료: {doc['id']}")
                
            except Exception as e:
                logger.error(f"요약 생성 실패 ({doc['id']}): {e}")
                self.summaries.append("")
        
        logger.info(f"전체 요약 생성 완료: {len(self.summaries)}개")
    
    def rank_documents(self, query: str, top_k: int = 3) -> List[Tuple[str, float]]:
        """
        쿼리에 대한 문서 순위 매기기
        
        Args:
            query: 검색 쿼리
            top_k: 상위 K개 문서 반환
            
        Returns:
            list: [(doc_id, score), ...]
        """
        if not self.summaries:
            logger.warning("요약이 생성되지 않았습니다. generate_summaries()를 먼저 호출하세요.")
            return []
        
        logger.info(f"문서 순위 매기기: '{query}'")
        
        ranked_scores = []
        
        for i, summary in enumerate(self.summaries):
            # 간단한 키워드 매칭 기반 점수 (실제로는 임베딩 사용 권장)
            score = self._calculate_relevance_score(query, summary)
            ranked_scores.append(score)
        
        # 상위 K개 선택
        ranked_indices = np.argsort(ranked_scores)[::-1][:top_k]
        results = [(self.documents[i]["id"], ranked_scores[i]) for i in ranked_indices]
        
        logger.info(f"상위 {top_k}개 문서: {[doc_id for doc_id, _ in results]}")
        return results
    
    def _calculate_relevance_score(self, query: str, summary: str) -> float:
        """
        간단한 키워드 매칭 기반 관련성 점수 계산
        (실제 프로덕션에서는 임베딩 기반 유사도 사용 권장)
        """
        query_lower = query.lower()
        summary_lower = summary.lower()
        
        # 키워드 매칭 점수
        query_words = set(query_lower.split())
        summary_words = set(summary_lower.split())
        
        if not query_words:
            return 0.0
        
        # Jaccard 유사도
        intersection = query_words & summary_words
        union = query_words | summary_words
        
        score = len(intersection) / len(union) if union else 0.0
        
        return score
    
    def search(self, query: str, top_k: int = 3) -> List[Dict[str, any]]:
        """
        쿼리로 문서 검색
        
        Args:
            query: 검색 쿼리
            top_k: 상위 K개 반환
            
        Returns:
            list: 검색 결과 [{"doc_id": "...", "summary": "...", "score": 0.0}]
        """
        ranked_results = self.rank_documents(query, top_k)
        
        results = []
        for doc_id, score in ranked_results:
            doc_index = self.doc_id_map[doc_id]
            results.append({
                "doc_id": doc_id,
                "summary": self.summaries[doc_index],
                "score": score,
                "content": self.documents[doc_index]["content"]
            })
        
        return results
    
    def get_summary(self, doc_id: str) -> Optional[str]:
        """
        특정 문서의 요약 반환
        
        Args:
            doc_id: 문서 ID
            
        Returns:
            str: 요약 텍스트
        """
        if doc_id not in self.doc_id_map:
            logger.warning(f"문서를 찾을 수 없습니다: {doc_id}")
            return None
        
        doc_index = self.doc_id_map[doc_id]
        
        if doc_index >= len(self.summaries):
            logger.warning(f"요약이 생성되지 않았습니다: {doc_id}")
            return None
        
        return self.summaries[doc_index]
    
    def save_index(self, save_path: str):
        """
        인덱스를 파일로 저장
        
        Args:
            save_path: 저장 경로
        """
        data = {
            "documents": self.documents,
            "summaries": self.summaries,
            "doc_id_map": self.doc_id_map,
            "saved_at": datetime.now().isoformat()
        }
        
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"인덱스 저장 완료: {save_path}")
    
    def load_index(self, load_path: str):
        """
        저장된 인덱스 로드
        
        Args:
            load_path: 로드 경로
        """
        load_path = Path(load_path)
        
        if not load_path.exists():
            logger.error(f"인덱스 파일을 찾을 수 없습니다: {load_path}")
            return
        
        with open(load_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.documents = data["documents"]
        self.summaries = data["summaries"]
        self.doc_id_map = data["doc_id_map"]
        
        logger.info(f"인덱스 로드 완료: {load_path} ({len(self.documents)}개 문서)")
    
    def get_statistics(self) -> Dict[str, any]:
        """
        인덱스 통계 정보 반환
        
        Returns:
            dict: 통계 정보
        """
        total_docs = len(self.documents)
        total_summaries = len(self.summaries)
        
        avg_content_length = np.mean([len(doc["content"]) for doc in self.documents]) if self.documents else 0
        avg_summary_length = np.mean([len(s) for s in self.summaries]) if self.summaries else 0
        
        return {
            "total_documents": total_docs,
            "total_summaries": total_summaries,
            "avg_content_length": int(avg_content_length),
            "avg_summary_length": int(avg_summary_length),
            "doc_ids": list(self.doc_id_map.keys())
        }
