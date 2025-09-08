#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
RAG 시스템 생성기 - 검색 결과를 기반으로 LLM을 통해 답변을 생성합니다. (GPU 최적화 버전)
"""

import os
import json
import logging
import copy
import torch
from typing import List, Dict, Any, Optional
from transformers import AutoModelForCausalLM, AutoTokenizer

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import time
import threading

class Generator:
    """
    RAG 시스템 생성기 (GPU 강제 사용)
    """
    
    def __init__(self, config):
        """
        생성기 초기화 (모델 즉시 로딩)
        """
        self.config = config
        self.model_name = self.config.LLM_MODEL
        self.prompt_template = self.config.PROMPT_TEMPLATES
        self.model = None
        self.tokenizer = None
        self.model_loaded_on_gpu = False
        
        # GPU 사용 가능성 체크
        if not torch.cuda.is_available():
            logger.error("CUDA를 사용할 수 없습니다. GPU 드라이버와 PyTorch CUDA 버전을 확인하세요.")
            raise RuntimeError("CUDA가 사용 불가능합니다.")
        
        # GPU 디바이스 설정 (명시적)
        self.device = self._get_gpu_device()
        logger.info(f"사용할 GPU 디바이스: {self.device}")
        logger.info(f"CUDA 디바이스 개수: {torch.cuda.device_count()}")
        
        # torch_dtype 설정
        self.torch_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        logger.info(f"사용할 데이터 타입: {self.torch_dtype}")
        
        # 토크나이저와 모델을 즉시 로드
        self._load_tokenizer()
        self._load_model()
        
        logger.info("Generator 초기화 및 모델 로딩 완료")

    def _get_gpu_device(self):
        """가장 적합한 GPU 디바이스 반환"""
        if hasattr(self.config, 'TEXT_GENERATOR_DEVICE') and self.config.TEXT_GENERATOR_DEVICE:
            config_device = self.config.TEXT_GENERATOR_DEVICE
            # "auto"가 아닌 구체적인 디바이스 설정인 경우
            if config_device != "auto" and "cuda" in str(config_device):
                return config_device
        
        # 기본적으로 첫 번째 GPU 사용
        return "cuda:0" if torch.cuda.device_count() > 0 else "cuda"

    def _load_tokenizer(self):
        """토크나이저 로드"""
        try:
            logger.info(f"토크나이저 로딩 중: {self.model_name}")
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                cache_dir=getattr(self.config, 'CACHE_DIR', None),
                trust_remote_code=True  # 필요한 경우
            )
            if self.tokenizer.pad_token_id is None:
                self.tokenizer.pad_token_id = self.tokenizer.eos_token_id
            logger.info("토크나이저 로딩 완료")
        except Exception as e:
            logger.error(f"토크나이저 로딩 실패: {e}")
            raise

    def _load_model(self):
        """모델을 GPU에 강제 로드"""
        logger.info(f"모델을 GPU에 로딩 중: {self.model_name}")
        
        try:
            # GPU 메모리 정리
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            # 멀티 GPU 환경에서는 device_map 사용
            if torch.cuda.device_count() > 1:
                logger.info(f"멀티 GPU 환경 감지 ({torch.cuda.device_count()}개 GPU)")
                model_kwargs = {
                    "torch_dtype": self.torch_dtype,
                    "device_map": "auto",  # 멀티 GPU 자동 분산
                    "trust_remote_code": True,
                    "low_cpu_mem_usage": True
                }
            else:
                # 단일 GPU 환경에서는 명시적 device 지정
                logger.info("단일 GPU 환경")
                model_kwargs = {
                    "torch_dtype": self.torch_dtype,
                    "trust_remote_code": True,
                    "low_cpu_mem_usage": True
                }
            
            # 캐시 디렉토리 설정
            if hasattr(self.config, 'CACHE_DIR') and self.config.CACHE_DIR:
                model_kwargs["cache_dir"] = self.config.CACHE_DIR
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                attn_implementation="flash_attention_2",
                **model_kwargs
            )
            
            # 단일 GPU 환경에서 명시적으로 GPU로 이동
            if torch.cuda.device_count() == 1 or "device_map" not in model_kwargs:
                logger.info(f"모델을 {self.device}로 이동 중...")
                self.model = self.model.to(self.device)
            
            # 모델이 실제로 GPU에 로드되었는지 확인
            self._verify_gpu_loading()
            
            self.model_loaded_on_gpu = True
            logger.info("모델 GPU 로딩 완료")
            
        except Exception as e:
            logger.error(f"모델 GPU 로딩 실패: {e}")
            self.model = None
            self.model_loaded_on_gpu = False
            raise

    def _verify_gpu_loading(self):
        """모델이 실제로 GPU에 로드되었는지 확인"""
        if self.model is None:
            raise RuntimeError("모델이 로드되지 않았습니다.")
        
        # 모델의 첫 번째 파라미터의 디바이스 확인
        first_param_device = next(self.model.parameters()).device
        logger.info(f"모델 파라미터가 위치한 디바이스: {first_param_device}")
        
        # GPU에 로드되었는지 확인
        if first_param_device.type != 'cuda':
            raise RuntimeError(f"모델이 CPU({first_param_device})에 로드되었습니다. GPU 로딩이 실패했습니다.")
        
        # 입력 임베딩 레이어의 디바이스 확인
        if hasattr(self.model, 'get_input_embeddings'):
            embedding_device = self.model.get_input_embeddings().weight.device
            logger.info(f"입력 임베딩 레이어 디바이스: {embedding_device}")
            if embedding_device.type != 'cuda':
                logger.warning(f"입력 임베딩이 CPU에 있습니다: {embedding_device}")

    def generate_response(self, query: str, results) -> Dict[str, Any]:
        """
        검색 결과를 기반으로 답변 생성
        """
        try:
            # GPU 상태 재확인
            if not self.model_loaded_on_gpu:
                raise RuntimeError("모델이 GPU에 로드되지 않았습니다.")
            
            # 기존 로직과 동일
            filtered_results = copy.deepcopy(results)
            image_paths = []

            if isinstance(filtered_results, dict) and 'image' in filtered_results:
                image_results = filtered_results.get('image', [])
                filtered_images = [img for img in image_results if isinstance(img, dict) and img.get('score', 0) > 0.6]
                logger.info(f"유사도 필터링 후 이미지 개수: {len(filtered_images)}/{len(image_results)}")
                
                filtered_results['image'] = filtered_images
                image_paths = [img['file_path'] for img in filtered_images if 'file_path' in img]

            context = self.format_context(filtered_results)
            
            system_prompt = self.prompt_template["system"]
            user_prompt = self.prompt_template["user"].format(context=context, query=query)

            response = self._generate_text(system_prompt, user_prompt)
            
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
                content_type = result.get("con_type")
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
    
    def _generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """허깅페이스 모델을 사용하여 텍스트 생성 (GPU 강제 사용)"""
        if self.model is None or self.tokenizer is None:
            raise Exception("모델 또는 토크나이저가 로드되지 않았습니다.")
        
        # Qwen3 모델을 위한 채팅 템플릿
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        full_prompt = self.tokenizer.apply_chat_template(
            messages, 
            tokenize=False, 
            add_generation_prompt=True, 
            enable_thinking=False
        )
        
        logger.info(f"텍스트 생성 시작: {self.model_name}")
        
        try:
            # 모델의 실제 디바이스 확인
            model_device = next(self.model.parameters()).device
            logger.info(f"모델 디바이스: {model_device}")
            
            # 입력을 모델과 같은 디바이스로 이동
            inputs = self.tokenizer(full_prompt, return_tensors="pt")
            inputs = {k: v.to(model_device) for k, v in inputs.items()}
            logger.info(f"입력 텐서 디바이스: {inputs['input_ids'].device}")
            
            with torch.no_grad():
                generation_params = {
                    "max_new_tokens": getattr(self.config, 'GENERATOR_MAX_TOKENS', 512),
                    # "num_beams": getattr(self.config, 'GENERATOR_NUM_BEAMS', 1),
                    # "do_sample": getattr(self.config, 'GENERATOR_DO_SAMPLE', True),
                    "pad_token_id": self.tokenizer.eos_token_id
                }

                if generation_params["max_new_tokens"]:
                    generation_params.update({
                        "temperature": getattr(self.config, 'GENERATOR_TEMPERATURE', 0.7),
                        # "top_p": getattr(self.config, 'GENERATOR_TOP_P', 0.9),
                        # "top_k": getattr(self.config, 'GENERATOR_TOP_K', 50)
                    })

                logger.info("GPU에서 텍스트 생성 중...")
                outputs = self.model.generate(**inputs, **generation_params)
            
            # 생성된 토큰만 디코딩
            response = self.tokenizer.decode(
                outputs[0][inputs['input_ids'].shape[1]:], 
                skip_special_tokens=True
            )
            
            logger.info("GPU 텍스트 생성 완료")
            return response
            
        except Exception as e:
            logger.error(f"텍스트 생성 실패: {str(e)}", exc_info=True)
            raise

    def get_model_info(self):
        """모델 상태 정보 반환 (디버깅용)"""
        if self.model is None:
            return {"status": "모델이 로드되지 않음"}
        
        model_device = next(self.model.parameters()).device
        return {
            "model_loaded": self.model_loaded_on_gpu,
            "model_device": str(model_device),
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": torch.cuda.device_count(),
            "current_device": torch.cuda.current_device() if torch.cuda.is_available() else None,
            "memory_allocated": torch.cuda.memory_allocated() if torch.cuda.is_available() else 0,
            "memory_reserved": torch.cuda.memory_reserved() if torch.cuda.is_available() else 0
        }
