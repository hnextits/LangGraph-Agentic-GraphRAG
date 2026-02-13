"""
RAG 시스템을 위한 이미지 리랭커 모듈
SGLang /v1/rerank API + Qwen3-Reranker 프롬프트 포맷으로 검색 결과를 재정렬합니다.
"""
import os
import logging
import sys
import time
import threading
import requests
from typing import List, Dict, Any, Optional, Union

# 상위 디렉토리를 모듈 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import RAGConfig

# 로깅 설정 - 기본 레벨은 INFO로 설정 (디버깅을 위해 WARNING에서 변경)
# 이미 다른 모듈에서 basicConfig가 호출되었을 수 있으므로 여기서는 설정하지 않음
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # 디버깅을 위해 INFO 레벨로 변경

# Qwen3-Reranker 프롬프트 포맷 상수
_QUERY_PREFIX = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
_DOC_SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
_INSTRUCTION = 'Given a web search query, retrieve relevant passages that answer the query.\n'


class RAGReranker:
    """SGLang /v1/rerank API + Qwen3-Reranker 프롬프트 포맷 기반 이미지 리랭커."""
    _ready = False
    _lock = threading.Lock()

    def __init__(self, model_name: str = None, ollama_host: str = None):
        """리랭커 초기화 - SGLang 서버 연결을 확인합니다."""
        config = RAGConfig()
        self.model_name = model_name or config.SGLANG_RERANKER_MODEL
        self.endpoint = config.SGLANG_RERANKER_ENDPOINT  # e.g. "http://localhost:30002"
        self._api_url = f"{self.endpoint}/v1/rerank"
        self._timeout = 60
        self._session = requests.Session()
        
        self.stats = {
            'total_queries': 0,
            'total_documents': 0,
            'total_time': 0.0
        }
        
        logger.info(f"이미지 리랭커 초기화 완료 (SGLang): {self.model_name} -> {self.endpoint}")
    
    def _ensure_server_ready(self) -> bool:
        """SGLang 리랭커 서버가 응답 가능한지 확인합니다. 미기동 시 자동 기동."""
        from notebooklm.sglang_server_manager import sglang_manager

        if self.__class__._ready:
            try:
                resp = self._session.get(f"{self.endpoint}/health", timeout=3)
                if resp.status_code == 200:
                    sglang_manager.touch("reranker")
                    return True
            except Exception:
                pass
            self.__class__._ready = False

        with self.__class__._lock:
            if self.__class__._ready:
                sglang_manager.touch("reranker")
                return True
            try:
                resp = self._session.get(f"{self.endpoint}/health", timeout=5)
                if resp.status_code == 200:
                    self.__class__._ready = True
                    sglang_manager.touch("reranker")
                    logger.info("SGLang image reranker server ready: %s", self.endpoint)
                    return True
            except (requests.ConnectionError, requests.Timeout, Exception):
                pass

            # 서버가 응답하지 않으면 sglang_manager로 자동 기동
            logger.info("SGLang reranker server 미기동 → acquire로 자동 기동 시도")
            try:
                if sglang_manager.acquire("reranker"):
                    sglang_manager.release("reranker")
                    self.__class__._ready = True
                    return True
            except Exception as e:
                logger.error("SGLang reranker 자동 기동 실패: %s", e)
            return False

    def _load_model(self) -> bool:
        """서버 연결 확인 (하위 호환성 유지)."""
        return self._ensure_server_ready()
    
    def format_passage(self, doc: Union[Dict[str, Any], str]) -> str:
        """
        문서를 텍스트로 변환합니다 (SequenceClassification 모델용).
        """
        # 문서 텍스트 추출
        if isinstance(doc, str):
            return doc
        
        # 실제 임베딩에 사용되는 필드들만 추출
        text = doc.get('text', '')
        title = doc.get('title', '')
        caption = doc.get('caption', '')
        description = doc.get('description', '')
        
        # 텍스트 우선순위: text > caption > description > title
        if text:
            doc_text = text
        elif caption:
            doc_text = caption
        elif description:
            doc_text = description
        elif title:
            doc_text = title
        else:
            doc_text = ""
        
        # 문맥 정보 추가
        context_parts = []
        if title and title != doc_text:
            context_parts.append(f"Title: {title}")
        if doc.get('file_path'):
            file_name = os.path.basename(doc.get('file_path', ''))
            context_parts.append(f"File: {file_name}")
        
        # 문맥 정보 추가
        if context_parts and doc_text:
            doc_text = doc_text + "\n\n" + "\n".join(context_parts)
        
        return doc_text
    
    def compute_similarity(self, query: str, item: Union[Dict[str, Any], str]) -> float:
        """쿼리와 아이템 간의 유사도를 계산합니다 (SGLang API)."""
        try:
            passage = self.format_passage(item)
            if not passage.strip():
                logger.warning("문서 텍스트가 비어있어 기본 점수를 사용합니다.")
                return 0.5
            scores = self.compute_similarity_batch(query, [passage])
            return scores[0] if scores else 0.5
        except Exception as e:
            logger.error(f"유사도 계산 오류: {str(e)}")
            return 0.5

    def compute_similarity_batch(self, query: str, passages: List[str], cancellation_event: Optional[threading.Event] = None) -> List[float]:
        """SGLang /v1/rerank API를 호출하여 배치 유사도를 계산합니다."""
        if not self._ensure_server_ready():
            logger.error("SGLang image reranker server not available")
            return [0.5] * len(passages)
        
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Image reranking operation cancelled")

        try:
            # Qwen3-Reranker 프롬프트 포맷 적용
            formatted_query = f"{_QUERY_PREFIX}<Instruct>: {_INSTRUCTION}<Query>: {query}\n"
            formatted_docs = [f"<Document>: {doc} {_DOC_SUFFIX}" for doc in passages]

            payload = {
                "query": formatted_query,
                "documents": formatted_docs,
            }
            resp = self._session.post(
                self._api_url,
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            
            # SGLang /v1/rerank 응답: {"results": [{"index": 0, "relevance_score": 0.95}, ...]}
            results_data = data.get("results", [])
            score_map = {item["index"]: item["relevance_score"] for item in results_data}
            scores = [score_map.get(i, 0.5) for i in range(len(passages))]
            
            if scores:
                logger.info(f"이미지 리랭킹 점수 - 최소: {min(scores):.4f}, 최대: {max(scores):.4f}, 평균: {sum(scores)/len(scores):.4f}")
            return scores
            
        except requests.ConnectionError:
            logger.error("SGLang image reranker server connection failed: %s", self._api_url)
            return [0.5] * len(passages)
        except Exception as e:
            logger.error(f"SGLang image rerank API 호출 오류: {e}")
            return [0.5] * len(passages)
        
    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: Optional[int] = None,
        min_score: float = None,
        cancellation_event: Optional[threading.Event] = None
    ) -> List[Dict[str, Any]]:

        """
        검색 결과를 재정렬합니다.
        
        Args:
            query: 사용자 쿼리 문자열
            results: 초기 검색 결과 목록 (각 항목은 'text' 필드를 포함해야 함)
            top_k: 반환할 상위 결과 수 (None인 경우 모든 결과 반환)
            min_score: 최소 점수 임계값 (None인 경우 config에서 가져옴)
            
        Returns:
            List[Dict[str, Any]]: 재정렬된 결과 목록
        """
        start_time = time.time()
        logger.info(f"이미지 리랭커 호출 (SGLang): 쿼리='{query}', 결과 수={len(results)}, top_k={top_k}")
        
        if not results:
            logger.info("리랭킹할 결과가 없습니다.")
            return []
        
        # 서버가 준비되지 않았으면 원본 결과 반환
        if not self._ensure_server_ready():
            logger.warning("SGLang 리랭커 서버가 준비되지 않았습니다. 원본 결과를 그대로 반환합니다.")
            return results[:top_k] if top_k else results
        
        config = RAGConfig()
        if min_score is None:
            min_score = getattr(config, 'IMAGE_RERANK_SCORE_THRESHOLD', 0.7)
        
        self.stats['total_queries'] += 1
        self.stats['total_documents'] += len(results)
        
        # 텍스트 리랭커와 동일한 방식으로 배치 처리 적용
        passages = []
        for result in results:
            text = result.get('text', '')
            title = result.get('title', '')
            description = result.get('description', '')
            page_num = result.get('page_num', '')
            file_path = result.get('file_path', '') or result.get('image_path', '')
            
            # 텍스트 우선순위로 주요 컨텐츠 결정
            main_content = ''
            if text:
                main_content = text
            elif description:
                main_content = description
            elif title:
                main_content = title
            else:
                main_content = "" # 비어있는 경우 빈 문자열 사용
            
            # 문맥 정보 추가 (임베딩에 사용되는 필드들만)
            context_parts = []
            if title and title != main_content:
                context_parts.append(f"제목: {title}")
            if page_num:
                context_parts.append(f"페이지: {page_num}")
            if file_path:
                # 파일명만 추출
                file_name = os.path.basename(file_path)
                context_parts.append(f"파일: {file_name}")
            
            # 최종 텍스트 구성
            if context_parts and main_content:
                full_text = main_content + "\n\n" + "\n".join(context_parts)
            else:
                full_text = main_content
            
            # full_text가 비어있는 경우 기본값 설정
            if not full_text.strip():
                full_text = "내용 없음"
                logger.debug(f"ID={result.get('id', 'unknown')}: 주요 컨텐츠가 비어있어 기본 텍스트 사용")
            
            passages.append(full_text)
        
        # 배치 처리로 점수 계산
        try:
            logger.info(f"리랭킹 점수 계산 시작: {len(passages)}개 문서")
            scores = self.compute_similarity_batch(query, passages, cancellation_event=cancellation_event)
            logger.info(f"리랭킹 점수 계산 완료: {len(scores)}개 점수")
        except Exception as e:
            logger.error(f"리랭킹 점수 계산 중 오류 발생: {e}")
            # 오류 발생 시 원래 점수 유지
            scores = [result.get('score', 0.0) for result in results]
            logger.warning("오류로 인해 원래 점수를 유지합니다.")
        
        # 점수 업데이트 및 float32로 명시적 변환하여 일관성 유지
        reranked_results = []
        for result, score in zip(results, scores):
            result_with_score = result.copy()
            result_with_score['original_score'] = result.get('score', 0.0)
            
            # 점수를 명시적으로 Python float로 변환하여 dtype 문제 방지
            if score is None:
                score_value = 0.0
            elif isinstance(score, (list, tuple)):
                score_value = float(score[0]) if len(score) > 0 else 0.0
            else:
                try:
                    score_value = float(score)
                except (TypeError, ValueError):
                    score_value = 0.0
                
            result_with_score['rerank_score'] = score_value
            result_with_score['score'] = score_value
            result_with_score['reranked'] = True
            # image_base64 필드가 누락되지 않도록 보장
            if 'image_base64' not in result_with_score and 'image_base64' in result:
                result_with_score['image_base64'] = result['image_base64']
            reranked_results.append(result_with_score)
        
        # 점수에 따라 결과 정렬
        reranked_results.sort(key=lambda x: x.get('score', 0.0), reverse=True)
        
        # 최소 점수 필터링 적용
        if min_score > 0:
            filtered_results = [r for r in reranked_results if r.get('score', 0.0) >= min_score]
            logger.info(f"최소 점수 {min_score} 필터링 적용: {len(reranked_results)} -> {len(filtered_results)}개 결과")
            reranked_results = filtered_results
        
        # top_k가 지정된 경우 상위 결과만 반환
        if top_k is not None and top_k > 0:
            reranked_results = reranked_results[:top_k]
        
        # 통계 업데이트
        elapsed = time.time() - start_time
        self.stats['total_time'] += elapsed
        
        logger.info(f"쿼리 '{query}'에 대한 재정렬 완료, 결과 수: {len(reranked_results)}, 소요 시간: {elapsed:.2f}초")
        return reranked_results
