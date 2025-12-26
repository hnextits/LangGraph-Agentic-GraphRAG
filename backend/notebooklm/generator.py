#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
RAG 시스템 생성기 - SGLang을 사용하여 로컬에서 모델을 로드하고 추론합니다.
"""

import os, re, copy, logging
import threading
from typing import List, Dict, Any, Optional, Set
import sglang as sgl

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SGLangGenerator:
    """
    RAG 시스템 생성기 (SGLang 버전)
    """
    
    def __init__(self, config):
        """
        생성기 초기화
        """
        self.config = config
        self.model_name = self.config.LLM_MODEL
        self.prompt_template = self.config.PROMPT_TEMPLATES
        self.runtime = None
        self.model_loaded = False
        self.tokenizer = None  # 임시 토크나이저 속성 추가
        self.engine = None
        logger.info("Generator 초기화 완료 (모델은 최초 요청 시 로드)")

    def _load_model(self):
        """SGLang Engine 초기화"""
        try:
            logger.info(f"SGLang Engine 초기화 중: {self.model_name}")
            
            # PyTorch를 사용하여 GPU 메모리 정리
            import torch
            if torch.cuda.is_available():
                # 미사용 캐시 메모리 해제
                torch.cuda.empty_cache()
                logger.info("GPU 캐시 메모리 정리 완료")
            
            logger.info("SGLang Engine API 직접 사용 - 모델 직접 로드")
            
            # Config에서 디바이스 설정 가져오기 (TEST_MODE 지원)
            import os
            device = self.config.TEXT_GENERATOR_DEVICE
            logger.info(f"SGLang Engine 디바이스 설정: {device}")
            
            # device가 "cuda:N" 형식이면 환경 변수로 설정
            original_cuda_visible = os.environ.get('CUDA_VISIBLE_DEVICES')
            if device != "auto" and device.startswith("cuda:"):
                gpu_id = device.split(":")[1]
                os.environ['CUDA_VISIBLE_DEVICES'] = gpu_id
                logger.info(f"CUDA_VISIBLE_DEVICES 설정: {gpu_id}")
            
            # Engine 클래스를 사용하여 모델 초기화
            # mem_fraction_static: SGLang이 사용할 GPU 메모리 비율
            # Qwen3-8B 모델은 약 16GB 필요, 0.3 = 30% 정도 필요
            try:
                self.engine = sgl.Engine(
                    model_path=self.model_name,
                    mem_fraction_static=0.3,  # 메모리 할당량 제한 (30% - 약 24GB)
                    disable_cuda_graph=True,  # CUDA 그래프 비활성화로 안정성 향상
                    trust_remote_code=True,   # 원격 코드 신뢰
                    dtype="auto"              # 자동으로 적절한 dtype 선택
                )
            finally:
                # 환경 변수 복원
                if original_cuda_visible is not None:
                    os.environ['CUDA_VISIBLE_DEVICES'] = original_cuda_visible
                elif 'CUDA_VISIBLE_DEVICES' in os.environ:
                    del os.environ['CUDA_VISIBLE_DEVICES']
            
            self.model_loaded = True
            logger.info("SGLang Engine 초기화 완료")
        except Exception as e:
            logger.error(f"SGLang Engine 초기화 실패: {e}")
            self.model_loaded = False
            raise

    def _ensure_model_loaded(self):
        """
        모델이 로드되지 않았다면 로드합니다.
        """
        if not self.model_loaded or self.engine is None:
            self._load_model()

    def ensure_model_loaded(self):
        """외부에서 호출 가능한 공개 메서드."""
        self._ensure_model_loaded()

    def cleanup_model(self):
        """SGLang 엔진과 GPU 리소스를 정리"""
        try:
            if self.engine is not None:
                shutdown = getattr(self.engine, "shutdown", None)
                if callable(shutdown):
                    shutdown()
                self.engine = None
            self.model_loaded = False

            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:  # pragma: no cover
                logger.exception("GPU 캐시 정리 중 오류")

            logger.info("SGLangGenerator 리소스 정리 완료")
        except Exception as exc:  # pragma: no cover
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
        """SGLang Engine을 사용하여 텍스트 생성"""
        self._ensure_model_loaded()

        try:
            logger.info("SGLang Engine으로 텍스트 생성 시작")
            
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before text generation")

            # 채팅 형식 프롬프트 구성
            prompt = f"""<|im_start|>system
{system_prompt}<|im_end|>
<|im_start|>user
{user_prompt}<|im_end|>
<|im_start|>assistant
"""
            
            # 샘플링 파라미터 설정
            sampling_params = {
                "temperature": self.config.GENERATOR_TEMPERATURE,
                "top_p": self.config.GENERATOR_TOP_P,
                "max_new_tokens": self.config.GENERATOR_MAX_TOKENS,
                "stop": ["<|im_end|>", "<|endoftext|>", "### 질문:", "### 답변:", "### 시스템:"]
            }
            
            # 백그라운드 스레드에서 실행될 때 이벤트 루프 문제 해결
            try:
                # 일반 동기 방식으로 시도
                result = self.engine.generate(prompt=prompt, sampling_params=sampling_params)
                response = result["text"]

                response = re.sub(r'<[tT]hink>.*?</[tT]hink>', '', response, flags=re.DOTALL)

                # 2. 불필요한 공백/줄바꿈 정리
                response = response.strip()


                return response

            except RuntimeError as e:
                if "no current event loop" in str(e):
                    # 이벤트 루프 문제 발생 시 이벤트 루프 생성 후 다시 시도
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    
                    # 다시 시도
                    result = self.engine.generate(prompt=prompt, sampling_params=sampling_params)
                    response = result["text"]

                    # <think> 태그 제거 로직 추가
                    response = re.sub(r'<[tT]hink>.*?</[tT]hink>', '', response, flags=re.DOTALL)
                    
                    # 불필요한 공백/줄바꿈 정리
                    response = response.strip()
                    
                else:
                    # 다른 오류는 그대로 전파
                    raise

            logger.info("SGLang 텍스트 생성 완료")
            return response
            
        except Exception as e:
            logger.error(f"SGLang 텍스트 생성 실패: {str(e)}", exc_info=True)
            # 오류 발생 시 임시 응답 생성
            fallback_response = f"""오류 발생: {str(e)}

질문: {user_prompt}

응답: 죄송합니다. 텍스트 생성 중 오류가 발생했습니다. 오류 내용: {str(e)}"""
            return fallback_response

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
