#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
RAG 시스템 생성기 - 검색 결과를 기반으로 LLM을 통해 답변을 생성합니다. (수정된 버전)
"""

import os
import json
import logging
import copy  # FIX: deepcopy를 위해 import 추가
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
    RAG 시스템 생성기 (즉시 로딩)
    """
    
    def __init__(self, config):
        """
        생성기 초기화 (모델 즉시 로딩)
        """
        self.config = config
        self.device = self.config.TEXT_GENERATOR_DEVICE
        self.model_name = self.config.LLM_MODEL
        self.prompt_template = self.config.PROMPT_TEMPLATES
        self.model = None
        self.tokenizer = None
        self.model_loaded_on_gpu = False

        # 디바이스에 따라 torch_dtype 설정
        if "cuda" in self.device:
            self.torch_dtype = torch.float16
        else:
            self.torch_dtype = torch.float32
        
        # 토크나이저와 모델을 즉시 로드
        self._load_tokenizer()
        self._load_model()
        
        logger.info("Generator 초기화 및 모델 로딩 완료")

    def _load_tokenizer(self):
        """토크나이저만 먼저 로드"""
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                cache_dir=self.config.CACHE_DIR,
                local_files_only=True
            )
            if self.tokenizer.pad_token_id is None:
                self.tokenizer.pad_token_id = self.tokenizer.eos_token_id
            logger.info("토크나이저 로딩 완료")
        except Exception as e:
            logger.error(f"토크나이저 로딩 실패: {e}")
            raise

    def _load_model(self):
        """모델을 GPU에 로드"""
        logger.info(f"모델을 GPU에 로딩 중... ({self.model_name})")
        try:
            model_kwargs = {"torch_dtype": self.torch_dtype}
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                cache_dir=self.config.CACHE_DIR,
                local_files_only=True,
                **model_kwargs
            ).to(self.device)
            
            self.model_loaded_on_gpu = True
            logger.info("모델 GPU 로딩 완료")
        except Exception as e:
            logger.error(f"모델 GPU 로딩 실패: {e}")
            self.model = None
            self.model_loaded_on_gpu = False
            raise

    def generate_response(self, query: str, results) -> Dict[str, Any]:
        """
        검색 결과를 기반으로 답변 생성 (지연 로딩 적용)
        """
        try:
            
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
        """
        공통 메타데이터 포맷팅
        """
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
            return ""  # FIX: None 대신 빈 문자열 반환
            
        meta_info = self._format_metadata(result)
        return f"{index}. {text}{meta_info}"
        
    def _format_table_result(self, result, index):
        """테이블 결과 포맷팅"""
        table_data = result.get('table_data', '').strip()
        if not table_data:
            return ""  # 빈 문자열 반환
        
        # 테이블 데이터를 그대로 사용 (줄바꿈 처리는 rag_service.py에서 수행)
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
        """
        검색 결과를 컨텍스트 형식으로 포맷팅 (로직 개선)
        """
        if not results:
            return ""

        context_parts = []

        # REFACTORED: results가 단순 리스트일 경우와 딕셔너리일 경우를 모두 처리하는 통합 로직
        # 딕셔너리 형태가 아니라면, 리스트로 간주하고 'search_results'라는 가상 키로 감싸서 처리
        if isinstance(results, list):
            results_dict = {"search_results": results}
        elif isinstance(results, dict):
            results_dict = results
        else:
            return ""

        # REFACTORED: 중복을 제거하고 하나의 통합된 루프로 모든 검색 결과를 처리
        for searcher_name, searcher_results in results_dict.items():
            if not isinstance(searcher_results, list) or not searcher_results:
                continue
                
            context_parts.append(f"\n## {searcher_name.upper()} 검색 결과:")
            
            for i, result in enumerate(searcher_results, 1):
                if not isinstance(result, dict):
                    continue

                formatted_result = ""
                # con_type을 우선적으로 확인하여 이미지/테이블/텍스트 순으로 처리
                content_type = result.get("con_type")
                if content_type == "image" or "file_path" in result:
                    formatted_result = self._format_image_result(result, i)
                elif content_type == "table" or "table_data" in result or "table" in result:
                    formatted_result = self._format_table_result(result, i)
                elif content_type == "text" or "text" in result:
                    formatted_result = self._format_text_result(result, i)
                elif "formula" in result:
                    formatted_result = f"{i}. 수식: {result.get('formula', '')}"
                
                # 포맷팅 결과가 비어있지 않은 경우에만 추가
                if formatted_result:
                    context_parts.append(formatted_result)
        
        return "\n".join(context_parts)
    
    def _generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """
        허깅페이스 모델을 사용하여 텍스트 생성
        """
        if self.model is None or self.tokenizer is None:
            raise Exception("모델 또는 토크나이저가 로드되지 않았습니다.")
        
        # Qwen3 모델을 위한 채팅 템플릿 적용 방식으로 변경
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # enable_thinking=False 파라미터를 여기에 적용 (Qwen3 모델 문서에 따라)
        full_prompt = self.tokenizer.apply_chat_template(
            messages, 
            tokenize=False, 
            add_generation_prompt=True, 
            enable_thinking=False  # 생각 모드 비활성화
        )
        
        logger.info(f"텍스트 생성 시작: {self.model_name}")
        
        try:
            inputs = self.tokenizer(full_prompt, return_tensors="pt").to(self.device)
            
            with torch.no_grad():
                generation_params = {
                    "max_new_tokens": self.config.GENERATOR_MAX_TOKENS,
                    "num_beams": self.config.GENERATOR_NUM_BEAMS,
                    "do_sample": self.config.GENERATOR_DO_SAMPLE,
                    "pad_token_id": self.tokenizer.eos_token_id if self.config.GENERATOR_PAD_TOKEN_ID is None else self.config.GENERATOR_PAD_TOKEN_ID
                }

                if self.config.GENERATOR_DO_SAMPLE:
                    generation_params.update({
                        "temperature": self.config.GENERATOR_TEMPERATURE,
                        "top_p": self.config.GENERATOR_TOP_P,
                        "top_k": self.config.GENERATOR_TOP_K
                    })

                outputs = self.model.generate(**inputs, **generation_params)
            
            response = self.tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
            
            logger.info("텍스트 생성 완료")
            

                
            return response
        except Exception as e:
            logger.error(f"텍스트 생성 실패: {str(e)}", exc_info=True)
            raise
