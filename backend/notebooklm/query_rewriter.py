#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
사용자 쿼리를 벡터 검색에 더 적합한 여러 형태로 재작성하는 모듈.
Hugging Face의 naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-1.5B 모델을 사용.
"""

import os
import logging
import requests
from typing import List
from config import RAGConfig

# 로깅 설정
logger = logging.getLogger(__name__)

class QueryRewriter:
    """SGLang /v1/chat/completions API를 사용하는 쿼리 리라이터.
    
    모델을 직접 로드하지 않고 SGLang 서버의 OpenAI 호환
    Chat Completions API를 호출하여 쿼리를 재작성합니다.
    """
    _ready = False

    def __init__(self, model_name: str = None, device: str = None):
        """
        QueryRewriter를 초기화합니다.

        Args:
            model_name (str): SGLang 서버에 로드된 모델 이름.
            device (str): 미사용 (하위 호환성 유지).
        """
        config = RAGConfig()
        self.model_name = model_name or config.SGLANG_QUERY_REWRITER_MODEL
        self.endpoint = config.SGLANG_QUERY_REWRITER_ENDPOINT  # e.g. "http://localhost:30004"
        self._api_url = f"{self.endpoint}/v1/chat/completions"
        self._timeout = 30
        self._session = requests.Session()
        logger.info(f"Query Rewriter 초기화 완료 (SGLang): {self.model_name} -> {self.endpoint}")

    def _load_model(self):
        """
        SGLang 서버 연결 확인. 미기동 시 자동 기동.
        """
        from notebooklm.sglang_server_manager import sglang_manager

        if self.__class__._ready:
            try:
                resp = self._session.get(f"{self.endpoint}/health", timeout=3)
                if resp.status_code == 200:
                    sglang_manager.touch("query_rewriter")
                    return
            except Exception:
                pass
            self.__class__._ready = False

        try:
            resp = self._session.get(f"{self.endpoint}/health", timeout=5)
            if resp.status_code == 200:
                self.__class__._ready = True
                sglang_manager.touch("query_rewriter")
                logger.info("SGLang query rewriter server ready: %s", self.endpoint)
                return
        except (requests.ConnectionError, requests.Timeout, Exception):
            pass

        # 서버가 응답하지 않으면 sglang_manager로 자동 기동
        logger.info("SGLang query rewriter server 미기동 → acquire로 자동 기동 시도")
        try:
            if sglang_manager.acquire("query_rewriter"):
                sglang_manager.release("query_rewriter")
                self.__class__._ready = True
        except Exception as e:
            logger.error("SGLang query rewriter 자동 기동 실패: %s", e)

    def _create_prompt(self, query: str) -> str:
        """
        Generate an instruction prompt for the LLM to rewrite a user query
        into several alternative queries optimized for Retrieval‑Augmented
        Generation (RAG).

        Args:
            query (str): The user's original query.

        Returns:
            str: The assembled prompt string.
        """
        prompt = f"""You are an expert query‑rewriter tasked with producing
        multiple alternative questions that maximize retrieval effectiveness
        in a RAG pipeline.

        [Your role]
        - Preserve the original intent while **substituting synonyms,
        related concepts, concrete examples, or hypothetical answers (HyDE)**
        to create four semantically rich variations.
        - Each question must be written as a **searchable, well‑formed sentence**.

        [Rules]
        - **Do NOT include the original query verbatim.**
        - Start each question with a number (1., 2., 3., 4.) and put each on
        its own line.
        - Expand or rephrase key terms with synonyms or adjacent concepts to
        broaden the search space.
        - Whenever helpful, change the viewpoint, assume different contexts,
        or introduce hypothetical scenarios.
        - Avoid trivial word swaps; aim for **meaningful semantic diversity**.

        ---
        [Example 1]
        User query: What are the pros and cons of RAG systems?

        Rewritten queries:
        1. How does retrieval‑augmented generation improve language‑model reliability?
        2. What technical challenges limit large‑scale adoption of RAG pipelines?
        3. Which side effects arise when external document search is combined with LLMs?
        4. Under what circumstances might retrieval fail to enhance generation quality?

        ---
        [Example 2]
        User query: The role of text rerankers

        Rewritten queries:
        1. What architectural features define learning‑based document rerankers?
        2. Why do cross‑encoders often outperform simple BM25 ranking?
        3. Real‑world applications of document reordering to increase LLM answer accuracy
        4. Assuming retrieved passages are reorganized, which criteria guide a reranker?

        ---
        [User query]
        {query}

        [Rewritten queries]
        """
        return prompt

    def _parse_output(self, generated_text: str) -> List[str]:
        """
        모델이 생성한 텍스트에서 재작성된 쿼리 목록을 파싱합니다.

        Args:
            generated_text (str): 모델의 생성 결과.

        Returns:
            List[str]: 파싱된 쿼리 문자열 목록.
        """
        rewritten_queries = []
        lines = generated_text.strip().split('\n')
        for line in lines:
            # "1.", "2." 와 같은 숫자+점 형식으로 시작하는 라인만 처리
            if line.strip() and line.strip()[0].isdigit() and '.' in line:
                # 숫자와 점, 공백을 제거하여 순수 쿼리만 추출
                clean_query = line.split('.', 1)[-1].strip()
                if clean_query:
                    rewritten_queries.append(clean_query)
        return rewritten_queries

    def rewrite_query(self, query: str, max_new_tokens: int = 150) -> List[str]:
        """
        주어진 쿼리를 여러 개의 새로운 쿼리로 재작성합니다.

        Args:
            query (str): 사용자의 원본 쿼리.
            max_new_tokens (int): 모델이 생성할 최대 토큰 수.

        Returns:
            List[str]: 재작성된 쿼리 목록. 병렬 검색에 바로 사용 가능.
        """
        # 1. 서버 연결 확인 (필요 시)
        self._load_model()

        # 2. 프롬프트 생성
        prompt = self._create_prompt(query)

        # 3. SGLang /v1/chat/completions API 호출
        try:
            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_new_tokens,
                "temperature": 0.7,
                "top_p": 0.95,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            resp = self._session.post(
                self._api_url,
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            
            generated_text = data["choices"][0]["message"]["content"]
            logger.info(f"모델 생성 결과:\n{generated_text}")

            # 4. 결과 파싱
            rewritten_queries = self._parse_output(generated_text)

            # 재작성된 쿼리가 없는 경우 원본 쿼리를 포함
            if not rewritten_queries:
                logger.warning("재작성된 쿼리를 생성하지 못했습니다. 원본 쿼리를 사용합니다.")
                return [query]
            
            # 최대 2개의 재작성된 쿼리만 사용
            if len(rewritten_queries) > 2:
                logger.info(f"재작성된 쿼리 제한: {len(rewritten_queries)} -> 2")
                rewritten_queries = rewritten_queries[:2]

            # 병렬 검색을 위해 원본 쿼리도 목록의 첫 번째에 추가
            return [query] + rewritten_queries

        except requests.ConnectionError:
            logger.error("SGLang query rewriter server connection failed: %s", self._api_url)
            return [query]
        except Exception as e:
            logger.error(f"쿼리 생성 중 오류 발생: {e}")
            return [query] # 오류 발생 시 원본 쿼리만 반환

    def cleanup(self):
        """HTTP 세션을 정리합니다."""
        try:
            self.__class__._ready = False
            self._session.close()
            logger.info("QueryRewriter 리소스 정리를 완료했습니다.")
        except Exception as exc:
            logger.error(f"QueryRewriter 정리 중 오류: {exc}")

# --- 사용 예시 ---
if __name__ == '__main__':
    # QueryRewriter 인스턴스 생성
    rewriter = QueryRewriter()

    # 재작성할 쿼리
    original_query = "라우터에서 크로스인코더는 왜 사용되나요?"
    
    print(f"[원본 쿼리]\n{original_query}\n")

    # 쿼리 재작성 실행
    # 이 과정에서 처음 실행 시 모델 다운로드 및 로드가 진행됩니다.
    rewritten_queries_list = rewriter.rewrite_query(original_query)

    print("[재작성된 쿼리 목록 (병렬 검색용)]")
    for i, q in enumerate(rewritten_queries_list):
        print(f"{i+1}. {q}")