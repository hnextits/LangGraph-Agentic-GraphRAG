#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
사용자 쿼리를 벡터 검색에 더 적합한 여러 형태로 재작성하는 모듈.
Hugging Face의 naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-1.5B 모델을 사용.
"""

import os
import logging
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from typing import List
from config import RAGConfig

# 로깅 설정
logger = logging.getLogger(__name__)

class QueryRewriter:
    def __init__(self, model_name: str = 'NEXTITS/Qwen3-0.6B-SFT-No.952', device: str = None):
        """
        QueryRewriter를 초기화합니다.

        Args:
            model_name (str): 사용할 Hugging Face 모델의 이름.
            device (str): 모델을 로드할 디바이스 ('cuda', 'cpu' 등). None일 경우 자동 감지.
        """
        config = RAGConfig()
        self.device = device if device else (config.QUERY_REWRITER_DEVICE if torch.cuda.is_available() else "cpu")
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        logger.info(f"Query Rewriter 객체 생성 완료. 사용할 디바이스: {self.device}")

    def _load_model(self):
        """
        필요 시 모델과 토크나이저를 로드합니다 (Lazy Loading).
        """
        if self.model is None or self.tokenizer is None:
            logger.info(f"'{self.model_name}' 모델 로드를 시작합니다...")
            try:
                # RAGConfig에서 토큰 가져오기
                from config import RAGConfig
                config = RAGConfig()
                hf_token = getattr(config, 'HF_TOKEN', None)
                
                # 토큰을 사용하여 모델 로드 - token 매개변수 사용 (use_auth_token 대신)
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, token=hf_token)
                
                # 메모리 문제 해결을 위한 설정
                torch.cuda.empty_cache()  # 기존 캐시 정리
                
                # 모델 로드 방식 변경
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    torch_dtype=torch.float16,
                    device_map="auto",  # 자동 장치 할당
                    token=hf_token,
                    low_cpu_mem_usage=True  # 낮은 CPU 메모리 사용
                )
                self.model.eval()
                logger.info("모델 로드가 완료되었습니다.")
            except Exception as e:
                logger.error(f"모델 로드 중 오류 발생: {e}")
                self.model = None
                self.tokenizer = None
                logger.error("모델 로드 실패로 인해 원본 쿼리만 사용합니다.")

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
        # 1. 모델 로드 (필요 시)
        self._load_model()
        if self.model is None:
            return [query] # 모델 로드 실패 시 원본 쿼리 반환

        # 2. 프롬프트 생성
        prompt = self._create_prompt(query)

        # 3. 모델 입력 준비
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)

        # 4. 쿼리 생성
        try:
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=0.7, # 일관성 있는 결과를 위해 온도를 약간 낮춤
                do_sample=True,
                top_p=0.95,
                eos_token_id=self.tokenizer.eos_token_id
            )
            # 생성된 텍스트에서 입력 프롬프트 부분은 제외
            generated_text = self.tokenizer.decode(outputs[0, inputs.input_ids.shape[1]:], skip_special_tokens=True)
            logger.info(f"모델 생성 결과:\n{generated_text}")

            # 5. 결과 파싱
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

        except Exception as e:
            logger.error(f"쿼리 생성 중 오류 발생: {e}")
            return [query] # 오류 발생 시 원본 쿼리만 반환

    def cleanup(self):
        """로딩된 모델과 토크나이저를 메모리에서 해제합니다."""
        try:
            if self.model is not None:
                del self.model
                self.model = None
            if self.tokenizer is not None:
                del self.tokenizer
                self.tokenizer = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
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