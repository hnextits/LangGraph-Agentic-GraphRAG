#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
RAG 시스템 생성기 - SGLang 서버 API를 사용하여 텍스트를 생성합니다.
"""

import os, re, copy, logging
import threading
import requests
from typing import List, Dict, Any, Optional, Set

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SGLangGenerator:
    """
    RAG 시스템 생성기 (SGLang 서버 API 버전)
    
    모델을 직접 로드하지 않고 main.py에서 기동한
    SGLang 생성기 서버(port 30000)의 /v1/chat/completions API를 호출합니다.
    """
    _ready = False
    
    def __init__(self, config):
        """
        생성기 초기화
        """
        self.config = config
        self.model_name = self.config.LLM_MODEL
        self.prompt_template = self.config.PROMPT_TEMPLATES
        self.endpoint = self.config.SGLANG_GENERATOR_ENDPOINT  # e.g. "http://localhost:30000"
        self._api_url = f"{self.endpoint}/v1/chat/completions"
        self._timeout = 180
        self._session = requests.Session()
        self.model_loaded = False
        self.tokenizer = None  # 하위 호환성 유지
        self.engine = None     # 하위 호환성 유지
        logger.info(f"Generator 초기화 완료 (SGLang 서버): {self.model_name} -> {self.endpoint}")

    def _ensure_server_ready(self) -> bool:
        """SGLang 생성기 서버가 응답 가능한지 확인합니다. 미기동 시 자동 기동."""
        from notebooklm.sglang_server_manager import sglang_manager

        # _ready=True여도 실제 health check로 서버 생존 확인
        if self.__class__._ready:
            try:
                resp = self._session.get(f"{self.endpoint}/health", timeout=3)
                if resp.status_code == 200:
                    sglang_manager.touch("generator")
                    return True
            except Exception:
                pass
            self.__class__._ready = False
            self.model_loaded = False

        try:
            resp = self._session.get(f"{self.endpoint}/health", timeout=5)
            if resp.status_code == 200:
                self.__class__._ready = True
                self.model_loaded = True
                sglang_manager.touch("generator")
                logger.info("SGLang generator server ready: %s", self.endpoint)
                return True
        except (requests.ConnectionError, requests.Timeout, Exception):
            pass

        # 서버가 응답하지 않으면 sglang_manager로 자동 기동
        logger.info("SGLang generator server 미기동 → acquire로 자동 기동 시도")
        try:
            if sglang_manager.acquire("generator"):
                # acquire 성공 → 즉시 release하지 않음
                # 실제 API 호출 완료 후 _generate_text_sglang에서 release
                sglang_manager.release("generator")
                self.__class__._ready = True
                self.model_loaded = True
                return True
        except Exception as e:
            logger.error("SGLang generator 자동 기동 실패: %s", e)
        return False

    def _load_model(self):
        """서버 연결 확인 (하위 호환성 유지)."""
        self._ensure_server_ready()

    def _ensure_model_loaded(self):
        """서버 연결 확인 (하위 호환성 유지)."""
        self._ensure_server_ready()

    def ensure_model_loaded(self):
        """외부에서 호출 가능한 공개 메서드."""
        self._ensure_server_ready()

    def cleanup_model(self):
        """HTTP 세션 정리 (서버는 main.py에서 관리)"""
        try:
            self.__class__._ready = False
            self.model_loaded = False
            self._session.close()
            logger.info("SGLangGenerator 리소스 정리 완료")
        except Exception as exc:
            logger.error("SGLangGenerator cleanup 실패: %s", exc, exc_info=True)

    def generate_response(
        self,
        query: str,
        results,
        cancellation_event: Optional[threading.Event] = None,
        allowed_document_uuids: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """
        검색 결과를 기반으로 답변 생성
        """
        try:
            self._ensure_model_loaded()
            
            # 기존 로직과 동일
            filtered_results = copy.deepcopy(results)
            image_paths = []

            # 검색 결과가 없는지 확인
            has_results = False
            
            if isinstance(filtered_results, dict):
                # 텍스트 결과 확인
                if 'text_documents' in filtered_results and filtered_results['text_documents']:
                    has_results = True
                
                # 이미지 결과 확인
                if 'image_documents' in filtered_results and filtered_results['image_documents']:
                    has_results = True
                    
                # 이전 형식 호환성
                if 'image' in filtered_results:
                    image_results = filtered_results.get('image', [])
                    filtered_images = [img for img in image_results if isinstance(img, dict) and img.get('score', 0) > 0.6]
                    logger.info(f"유사도 필터링 후 이미지 개수: {len(filtered_images)}/{len(image_results)}")
                    
                    if filtered_images:
                        has_results = True
                    
                    filtered_results['image'] = filtered_images
                    image_paths = [img['file_path'] for img in filtered_images if 'file_path' in img]
            
            # 검색 결과가 없으면 적절한 메시지 반환
            if not has_results:
                logger.warning("검색 결과가 없습니다. '제공된 자료에서 해당 정보를 찾을 수 없습니다.' 메시지를 반환합니다.")
                return {
                    "answer": "제공된 자료에서 해당 정보를 찾을 수 없습니다.",
                    "image_paths": [],
                    "feedback_loops": 0,
                    "final_query": query,
                    "context": "",
                    "search_results": filtered_results
                }

            context = self.format_context(filtered_results)
            
            # 검색 결과가 없거나 빈 문서인 경우 추가 처리
            if not context or context.strip() == "":
                logger.warning("포맷팅된 컨텍스트가 비어 있습니다. '제공된 자료에서 해당 정보를 찾을 수 없습니다.' 메시지를 반환합니다.")
                return {
                    "answer": "제공된 자료에서 해당 정보를 찾을 수 없습니다.",
                    "image_paths": [],
                    "feedback_loops": 0,
                    "final_query": query,
                    "context": "",
                    "search_results": filtered_results
                }
            
            system_prompt = self.prompt_template["system"]
            user_prompt = self.prompt_template["user"].format(context=context, query=query)

            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before text generation")

            response = self._generate_text_sglang(system_prompt, user_prompt, cancellation_event=cancellation_event)
            
            return {
                "answer": response,
                "context_used": context,
                "image_paths": image_paths or None
            }
        except Exception as e:
            logger.error(f"답변 생성 실패: {str(e)}", exc_info=True)
            return {
                "answer": f"답변 생성 중 오류가 발생했습니다: {str(e)}",
                "error": str(e)
            }

    def _format_metadata(self, result):
        """공통 메타데이터 포맷팅"""
        meta_parts = []
        source = result.get('source') or result.get('file_path')
        if source:
            meta_parts.append(f"출처: {source}")
            
        page_num = result.get('page_num')
        if page_num and str(page_num).strip().lower() not in ["none", "n/a", ""]:
            meta_parts.append(f"페이지: {page_num}")
            
        if 'score' in result and result['score'] is not None:
            meta_parts.append(f"유사도: {float(result['score']):.4f}")
            
        return f" ({', '.join(meta_parts)})" if meta_parts else ""

    def _format_text_result(self, result, index):
        """텍스트 결과 포맷팅"""
        text = str(result.get('text', '')).strip()
        if not text:
            return ""
            
        meta_info = self._format_metadata(result)
        return f"{index}. {text}{meta_info}"
        
    def _format_table_result(self, result, index):
        """테이블 결과 포맷팅"""
        table_data = result.get('table_data', '').strip()
        if not table_data:
            return ""
        
        meta_info = self._format_metadata(result)
        return f"{index}. 표 데이터{meta_info}\n{table_data}"
    
    def _format_image_result(self, result, index):
        """이미지 결과 포맷팅"""
        file_path = result.get("file_path", "")
        title = result.get("title")
        caption = result.get("caption", "")
        
        if not title or str(title).strip().lower() in ["none", ""]:
            if file_path:
                title = os.path.splitext(os.path.basename(file_path))[0]
                title_parts = title.split('_')
                if len(title_parts) > 1 and title_parts[0]:
                    title = title_parts[0]
            else:
                title = "이미지"
        
        title = str(title).strip() if title is not None else "이미지"
        meta_info = self._format_metadata(result)
        image_item = f"{index}. {title}{meta_info}"
        
        if caption and str(caption).strip().lower() not in ["none", ""]:
            image_item += f"\n   - {caption}"
            
        return image_item

    def format_context(self, results) -> str:
        """검색 결과를 컨텍스트 형식으로 포맷팅"""
        if not results:
            return ""

        context_parts = []

        if isinstance(results, list):
            results_dict = {"search_results": results}
        elif isinstance(results, dict):
            results_dict = results
        else:
            return ""

        for searcher_name, searcher_results in results_dict.items():
            if not isinstance(searcher_results, list) or not searcher_results:
                continue
                
            context_parts.append(f"\n## {searcher_name.upper()} 검색 결과:")
            
            for i, result in enumerate(searcher_results, 1):
                if not isinstance(result, dict):
                    continue

                formatted_result = ""
                content_type = result.get("con_type") or result.get("content_type")
                if content_type == "image" or "file_path" in result:
                    formatted_result = self._format_image_result(result, i)
                elif content_type == "table" or "table_data" in result or "table" in result:
                    formatted_result = self._format_table_result(result, i)
                elif content_type == "text" or "text" in result:
                    formatted_result = self._format_text_result(result, i)
                elif "formula" in result:
                    formatted_result = f"{i}. 수식: {result.get('formula', '')}"
                
                if formatted_result:
                    context_parts.append(formatted_result)
        
        return "\n".join(context_parts)
    
    def _generate_text_sglang(self, system_prompt: str, user_prompt: str, cancellation_event: Optional[threading.Event] = None) -> str:
        """SGLang /v1/chat/completions API를 사용하여 텍스트 생성"""
        from notebooklm.sglang_server_manager import sglang_manager

        self._ensure_model_loaded()

        # 요청 처리 중 유휴 타임아웃으로 서버가 죽지 않도록 acquire/release로 보호
        sglang_manager.acquire("generator")
        try:
            logger.info("SGLang 서버로 텍스트 생성 시작")
            
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before text generation")

            stop_tokens = ["<" + "|im_end|" + ">", "<" + "|endoftext|" + ">"]

            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": self.config.GENERATOR_MAX_TOKENS,
                "temperature": self.config.GENERATOR_TEMPERATURE,
                "top_p": self.config.GENERATOR_TOP_P,
                "stop": stop_tokens,
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

            # <think> 태그 제거
            response = re.sub(r'<[tT]hink>.*?</[tT]hink>', '', response, flags=re.DOTALL)
            response = response.strip()

            logger.info("SGLang 텍스트 생성 완료")
            return response

        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            logger.warning("SGLang generator 타임아웃/연결실패, 서버 재시작 후 재시도: %s", e)
            # 서버 재시작 후 1회 재시도
            try:
                sglang_manager.shutdown_server("generator")
                self.__class__._ready = False
                self.model_loaded = False
                if sglang_manager.acquire("generator"):
                    resp = self._session.post(
                        self._api_url, json=payload, timeout=self._timeout,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    response = data["choices"][0]["message"]["content"]
                    response = re.sub(r'<[tT]hink>.*?</[tT]hink>', '', response, flags=re.DOTALL)
                    logger.info("SGLang 텍스트 생성 완료 (재시도 성공)")
                    return response.strip()
            except Exception as retry_err:
                logger.error("SGLang generator 재시도도 실패: %s", retry_err)
            return f"죄송합니다. 텍스트 생성 서버에 연결할 수 없습니다."
        except Exception as e:
            logger.error(f"SGLang 텍스트 생성 실패: {str(e)}", exc_info=True)
            return f"죄송합니다. 텍스트 생성 중 오류가 발생했습니다: {str(e)}"
        finally:
            sglang_manager.release("generator")

    def get_model_info(self):
        """모델 상태 정보 반환 (디버깅용)"""
        if not self.model_loaded:
            return {"status": "모델이 로드되지 않음"}
        
        return {
            "model_loaded": self.model_loaded,
            "model_name": self.model_name,
            "max_tokens": self.config.GENERATOR_MAX_TOKENS,
            "temperature": self.config.GENERATOR_TEMPERATURE
        }