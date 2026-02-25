#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
RAG 시스템 정제기 - 최종 답변을 사용자에게 적합하게 다듬습니다.
Qwen3-1.7B 전용 모델 사용 (최적화됨)
"""

import os
import json
import logging
import time
import threading
import requests
import importlib
import sys
from typing import List, Dict, Any, Optional

# config.py 임포트
from config import RAGConfig

# rag_service의 process_markdown_tables 함수 임포트
def import_process_markdown_tables():
    """
    rag_service.py에서 process_markdown_tables 함수를 동적으로 임포트
    """
    try:
        from services.rag_service import process_markdown_tables
        return process_markdown_tables
    except ImportError:
        # 임포트 실패 시 로깅
        logging.error("rag_service.py에서 process_markdown_tables 함수를 임포트하는데 실패했습니다.")
        # 임포트 실패 시 None 반환
        return None

# process_markdown_tables 함수 동적 임포트
process_markdown_tables = import_process_markdown_tables()

# 로깅 설정
logger = logging.getLogger(__name__)

class Refiner:
    """
    RAG 시스템 정제기
    SGLang /v1/chat/completions API를 사용하여 답변을 정제합니다.
    """
    _ready = False
    
    def __init__(self, generator, config: RAGConfig = None):
        """
        정제기 초기화 (SGLang 서버 연결)
        
        Args:
            generator: Generator 인스턴스 (하위 호환성 유지)
            config: RAGConfig 인스턴스
        """
        if config is None:
            config = RAGConfig()
        
        self.config = config
        self.generator = generator  # 하위 호환성 유지
        
        # SGLang 서버 설정
        self.refiner_model_name = self.config.SGLANG_REFINER_MODEL
        self.endpoint = self.config.SGLANG_REFINER_ENDPOINT  # e.g. "http://localhost:30003"
        self._api_url = f"{self.endpoint}/v1/chat/completions"
        self._timeout = 60
        self._session = requests.Session()
        
        logger.info(f"Refiner 초기화 완료 (SGLang): {self.refiner_model_name} -> {self.endpoint}")

    def _ensure_server_ready(self) -> bool:
        """SGLang 리파이너 서버가 응답 가능한지 확인합니다. 미기동 시 자동 기동."""
        from notebooklm.sglang_server_manager import sglang_manager

        if self.__class__._ready:
            try:
                resp = self._session.get(f"{self.endpoint}/health", timeout=3)
                if resp.status_code == 200:
                    sglang_manager.touch("refiner")
                    return True
            except Exception:
                pass
            self.__class__._ready = False

        try:
            resp = self._session.get(f"{self.endpoint}/health", timeout=5)
            if resp.status_code == 200:
                self.__class__._ready = True
                sglang_manager.touch("refiner")
                logger.info("SGLang refiner server ready: %s", self.endpoint)
                return True
        except (requests.ConnectionError, requests.Timeout, Exception):
            pass

        # 서버가 응답하지 않으면 sglang_manager로 자동 기동
        logger.info("SGLang refiner server 미기동 → acquire로 자동 기동 시도")
        try:
            if sglang_manager.acquire("refiner"):
                sglang_manager.release("refiner")
                self.__class__._ready = True
                return True
        except Exception as e:
            logger.error("SGLang refiner 자동 기동 실패: %s", e)
        return False

    def refine_answer(self, query: str, answer: str, cancellation_event: Optional[threading.Event] = None) -> str:
        """
        답변 정제
        
        Args:
            query: 사용자 질문
            answer: 원본 답변
            
        Returns:
            정제된 답변
        """
        logger.info(f"Refiner.refine_answer 호출됨 - 원본 답변 길이: {len(answer)}")
        
        # 원본 답변에서 <think> 태그와 내용 제거
        cleaned_answer = self._clean_think_tags(answer)
        
        # 프롬프트 구성
        system_prompt = self.config.REFINER_SYSTEM_PROMPT
        user_prompt = self.config.REFINER_USER_PROMPT_TEMPLATE.format(query=query, answer=cleaned_answer)
        
        # LLM을 통한 정제 수행
        try:
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before refinement generation")
            
            refined_answer = self._generate_with_refiner_model(system_prompt, user_prompt, cancellation_event=cancellation_event)
            
            # <think> 태그가 있다면 제거하고 실제 답변만 추출
            refined_answer = self._extract_final_answer(refined_answer)
            
            # 중복 문장 제거
            refined_answer = self._remove_duplicated_sentences(refined_answer)
            
            # 마크다운 테이블 처리 - 줄바꿈 문제 해결
            if process_markdown_tables:
                logger.info("마크다운 테이블 처리 적용 중...")
                refined_answer = process_markdown_tables(refined_answer)
            
            logger.info(f"Refiner 답변 정제 완료 - 정제된 답변 길이: {len(refined_answer)}")
            logger.info(f"정제 전 답변 일부: {answer[:50]}...")
            logger.info(f"정제 후 답변 일부: {refined_answer[:50]}...")
            
            # 정제된 답변이 비어있으면 원본 답변 반환
            if not refined_answer.strip():
                logger.warning("정제된 답변이 비어있어서 원본 답변을 반환합니다.")
                return answer
                
            return refined_answer
        except Exception as e:
            logger.error(f"Refiner 답변 정제 실패: {str(e)}")
            return answer  # 실패 시 원본 답변 반환

    def _clean_think_tags(self, text: str) -> str:
        """<think> 태그와 내용 제거"""
        if "<think>" in text and "</think>" in text:
            try:
                text_parts = text.split("<think>", 1)
                think_and_rest = text_parts[1].split("</think>", 1)
                text = text_parts[0].strip() + " " + think_and_rest[1].strip()
                logger.debug(f"<think> 태그 제거 후 텍스트 길이: {len(text)}")
            except IndexError:
                logger.warning("텍스트의 <think> 태그 처리 중 오류 발생")
        elif "<think>" in text:
            try:
                parts = text.split("<think>", 1)
                if "\n\n" in parts[1]:
                    text = parts[0].strip() + " " + parts[1].split("\n\n", 1)[1].strip()
                    logger.debug(f"<think> 태그 제거 후 텍스트 길이: {len(text)}")
            except IndexError:
                logger.warning("텍스트의 <think> 태그 처리 중 오류 발생")
        return text

    def _extract_final_answer(self, text: str) -> str:
        """Qwen3 출력에서 최종 답변만 추출 (thinking 태그 제거)"""
        if "<think>" in text and "</think>" in text:
            try:
                # thinking 내용과 실제 답변 분리
                parts = text.split("</think>")
                if len(parts) > 1:
                    final_answer = parts[1].strip()
                    logger.debug(f"Thinking 태그 제거 후 최종 답변 길이: {len(final_answer)}")
                    return final_answer
            except Exception as e:
                logger.warning(f"Thinking 태그 처리 중 오류: {e}")
        
        # thinking 태그가 없거나 처리 실패 시 원본 반환
        return text
    
    def _preserve_markdown_tables(self, text: str) -> tuple:
        """마크다운 테이블을 보존하기 위해 임시로 대체"""
        import re
        
        # 마크다운 테이블 패턴 (헤더, 구분선, 데이터 행을 포함)
        table_pattern = re.compile(r'(\|[^\n]*\|\s*\n\s*\|[-:\s|]*\|[\s\S]*?(?:\n(?!\|)|$))', re.MULTILINE)
        
        # 테이블을 찾아서 임시 토큰으로 대체
        tables = []
        table_tokens = []
        
        def replace_table(match):
            table_text = match.group(0)
            token = f"__TABLE_TOKEN_{len(tables)}__"
            tables.append(table_text)
            table_tokens.append(token)
            return token
        
        # 테이블을 임시 토큰으로 대체
        processed_text = table_pattern.sub(replace_table, text)
        
        return processed_text, tables, table_tokens
    
    def _restore_markdown_tables(self, text: str, tables: list, table_tokens: list) -> str:
        """임시 토큰을 원래 테이블로 복원"""
        result = text
        for i, token in enumerate(table_tokens):
            result = result.replace(token, tables[i])
        return result
    
    def _remove_duplicated_sentences(self, text: str) -> str:
        """중복된 문장/라인 제거 (마크다운 테이블 보존 + 줄바꿈 유지)"""
        if not text:
            return text

        # 1) 테이블 보존
        processed_text, tables, tokens = self._preserve_markdown_tables(text)

        # 2) 줄 단위 처리
        seen = set()
        unique_lines = []
        for line in processed_text.splitlines():
            if not line.strip():
                unique_lines.append("")  # 빈 줄 그대로 유지
                continue
            if any(token in line for token in tokens):
                unique_lines.append(line)  # 테이블 토큰은 무조건 유지
                continue
            norm = line.strip().lower()
            if norm not in seen:
                seen.add(norm)
                unique_lines.append(line)

        # 3) 다시 합치기
        result = "\n".join(unique_lines)

        # 4) 테이블 복원
        return self._restore_markdown_tables(result, tables, tokens)
    
    def _generate_with_refiner_model(self, system_prompt: str, user_prompt: str, cancellation_event: Optional[threading.Event] = None) -> str:
        """
        SGLang /v1/chat/completions API를 사용하여 텍스트를 생성합니다.
        
        Args:
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            
        Returns:
            생성된 텍스트
        """
        try:
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before refinement generation")

            logger.info(f"Refiner SGLang 서버({self.refiner_model_name})로 텍스트 생성 중")
            
            payload = {
                "model": self.refiner_model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": self.config.REFINER_MAX_TOKENS,
                "temperature": 0.3,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            
            resp = self._session.post(
                self._api_url,
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            
            response = data["choices"][0]["message"]["content"]
            
            if not response:
                logger.warning("Refiner가 빈 응답을 생성했습니다.")
                return ""
            
            logger.info(f"Refiner 텍스트 생성 완료 - 응답 길이: {len(response)}")
            return response.strip()
            
        except requests.ConnectionError:
            logger.error("SGLang refiner server connection failed: %s", self._api_url)
            raise
        except Exception as e:
            logger.error(f"Refiner 텍스트 생성 실패: {str(e)}", exc_info=True)
            raise
