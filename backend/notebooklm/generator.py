#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG 시스템 생성기 - 검색 결과를 기반으로 LLM을 통해 답변을 생성합니다.
(배치 처리 및 추론 최적화 적용 / Flash Attention 제외 버전)
"""

import os
import json
import logging
import copy
import torch
from typing import List, Dict, Any

# transformers 라이브러리에서 필요한 모듈들을 가져옵니다.
# BitsAndBytesConfig는 모델 양자화를 위해 필요합니다.
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

# 로깅 기본 설정: INFO 레벨 이상의 로그를 시간, 이름, 레벨, 메시지 형식으로 출력합니다.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Generator:
    """
    RAG 시스템 생성기 (즉시 로딩, 배치 처리 및 최적화 적용)
    """

    def __init__(self, config):
        """
        생성자: 클래스가 처음 생성될 때 호출됩니다.
        config 객체로부터 설정을 읽어와 모델과 토크나이저를 즉시 로딩합니다.
        """
        self.config = config
        self.device = self.config.TEXT_GENERATOR_DEVICE
        self.model_name = self.config.LLM_MODEL
        self.prompt_template = self.config.PROMPT_TEMPLATES
        self.model = None
        self.tokenizer = None
        
        # GPU 사용 시 float16을, CPU 사용 시 float32를 기본 데이터 타입으로 설정합니다.
        if "cuda" in self.device:
            self.torch_dtype = torch.float16
        else:
            self.torch_dtype = torch.float32
            
        # 초기화 시 토크나이저와 모델을 바로 로드합니다.
        self._load_tokenizer()
        self._load_model()
        
        logger.info("✅ Generator 초기화 및 모델 로딩 완료")

    def _load_tokenizer(self):
        """
        Hugging Face Hub 또는 로컬 캐시에서 토크나이저를 로드합니다.
        """
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                cache_dir=self.config.CACHE_DIR,
                local_files_only=True
            )
            # 중요: 배치 처리를 위해서는 모든 문장의 길이를 맞추기 위한 '패딩(padding)'이 필요합니다.
            # pad_token이 없는 모델의 경우, 문장의 끝을 알리는 eos_token을 pad_token으로 사용합니다.
            if self.tokenizer.pad_token_id is None:
                self.tokenizer.pad_token_id = self.tokenizer.eos_token_id
            logger.info("Tokenizer 로딩 완료")
        except Exception as e:
            logger.error(f"❌ 토크나이저 로딩 실패: {e}")
            raise

    def _load_model(self):
        """
        Hugging Face Hub 또는 로컬 캐시에서 LLM 모델을 로드합니다.
        GPU 최적화 옵션(양자화)을 포함합니다.
        """
        logger.info(f"모델을 GPU에 로딩 중... ({self.model_name})")
        
        # --- GPU 최적화 옵션 ---

        # 1. 양자화 (Quantization): 모델의 가중치를 4-bit로 로드하여 메모리 사용량을 크게 줄이고, 추론 속도를 높입니다.
        # 필요 시 아래 주석을 해제하여 사용하세요.
        # quantization_config = BitsAndBytesConfig(
        #     load_in_4bit=True,
        #     bnb_4bit_quant_type="nf4",
        #     bnb_4bit_compute_dtype=self.torch_dtype,
        #     bnb_4bit_use_double_quant=True,
        # )
        
        try:
            model_kwargs = {
                "torch_dtype": self.torch_dtype,
                # "quantization_config": quantization_config, # 양자화 사용 시 주석 해제
                
                # 'device_map'을 사용하면 모델 레이어를 지정된 장치(GPU)에 자동으로 할당해 줍니다.
                "device_map": self.device,
            }
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                cache_dir=self.config.CACHE_DIR,
                local_files_only=True,
                **model_kwargs
            )
            
            # 2. torch.compile (선택 사항): PyTorch 2.0+ 에서 모델 코드를 JIT 컴파일하여 실행 속도를 높입니다.
            # 첫 번째 요청 시 컴파일 오버헤드가 있지만, 이후 반복적인 요청에서 성능 향상이 큽니다.
            # self.model = torch.compile(self.model, mode="reduce-overhead", fullgraph=True)

            logger.info("모델 GPU 로딩 완료")
        except Exception as e:
            logger.error(f"❌ 모델 GPU 로딩 실패: {e}")
            self.model = None
            raise
    
    def generate_response(self, query: str, results: Dict) -> Dict[str, Any]:
        """
        내부적으로는 단일 요청을 리스트로 감싸서 새로운 배치 처리 함수를 호출합니다.
        이를 통해 기존 코드와의 호환성을 유지합니다.
        """
        # 단일 요청을 리스트로 만들어 배치 함수에 전달하고, 결과 리스트의 첫 번째 항목을 반환합니다.
        batch_responses = self.generate_batch_response([query], [results])
        return batch_responses[0]

    def generate_batch_response(self, queries: List[str], results_list: List[Dict]) -> List[Dict[str, Any]]:
        """
        여러 개의 요청(queries)을 리스트로 받아 한 번에 처리
        """
        if not queries:
            return []
            
        try:
            prompts = []
            all_image_paths = []
            all_contexts_used = []

            # 각 쿼리와 검색 결과에 대해 프롬프트를 생성합니다.
            for query, results in zip(queries, results_list):
                filtered_results = copy.deepcopy(results)
                image_paths = []

                if isinstance(filtered_results, dict) and 'image' in filtered_results:
                    image_results = filtered_results.get('image', [])
                    filtered_images = [img for img in image_results if isinstance(img, dict) and img.get('score', 0) > 0.6]
                    filtered_results['image'] = filtered_images
                    image_paths = [img['file_path'] for img in filtered_images if 'file_path' in img]
                
                context = self.format_context(filtered_results)
                system_prompt = self.prompt_template["system"]
                user_prompt = self.prompt_template["user"].format(context=context, query=query)
                
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
                
                full_prompt = self.tokenizer.apply_chat_template(
                    messages, 
                    tokenize=False, 
                    add_generation_prompt=True
                )
                prompts.append(full_prompt)
                all_image_paths.append(image_paths or None)
                all_contexts_used.append(context)

            # 생성된 프롬프트 리스트를 모델에 한 번에 전달하여 답변을 생성합니다.
            responses = self._generate_text_batch(prompts)
            
            # 생성된 답변들을 각 요청에 맞게 조합하여 최종 결과를 만듭니다.
            final_results = []
            for i in range(len(queries)):
                final_results.append({
                    "answer": responses[i],
                    "context_used": all_contexts_used[i],
                    "image_paths": all_image_paths[i]
                })
            return final_results

        except Exception as e:
            logger.error(f"❌ 배치 답변 생성 실패: {str(e)}", exc_info=True)
            return [{
                "answer": f"답변 생성 중 오류가 발생했습니다: {str(e)}",
                "error": str(e)
            }] * len(queries)

    def _generate_text_batch(self, prompts: List[str]) -> List[str]:
        """
        여러 프롬프트를 받아 모델의 `generate` 함수를 한 번만 호출하여 텍스트를 일괄 생성
        """
        if self.model is None or self.tokenizer is None:
            raise Exception("모델 또는 토크나이저가 로드되지 않았습니다.")
        
        logger.info(f"텍스트 생성 시작 (배치 크기: {len(prompts)}): {self.model_name}")
        
        try:
            # 여러 프롬프트를 한 번에 토크나이징합니다. `padding=True`가 핵심입니다.
            # `truncation=True`는 모델이 처리할 수 있는 최대 길이를 넘는 입력을 잘라냅니다.
            inputs = self.tokenizer(
                prompts, return_tensors="pt", padding=True, truncation=True
            ).to(self.device)
            
            with torch.no_grad(): # 추론 시에는 gradient 계산이 필요 없으므로, 메모리 사용량을 줄이고 속도를 높입니다.
                generation_params = {
                    "max_new_tokens": self.config.GENERATOR_MAX_TOKENS,
                    "num_beams": self.config.GENERATOR_NUM_BEAMS,
                    "do_sample": self.config.GENERATOR_DO_SAMPLE,
                    "pad_token_id": self.tokenizer.eos_token_id, # pad_token_id를 eos_token_id로 설정하는 것이 일반적입니다.
                }

                if self.config.GENERATOR_DO_SAMPLE:
                    generation_params.update({
                        "temperature": self.config.GENERATOR_TEMPERATURE,
                        "top_p": self.config.GENERATOR_TOP_P,
                        "top_k": self.config.GENERATOR_TOP_K
                    })

                outputs = self.model.generate(**inputs, **generation_params)
            
            # 배치로 생성된 결과(outputs)에서 입력 부분을 제외하고, 각 결과를 디코딩하여 문자열 리스트로 만듭니다.
            batch_responses = self.tokenizer.batch_decode(
                outputs[:, inputs.input_ids.shape[1]:], skip_special_tokens=True
            )
            
            logger.info("텍스트 생성 완료")
            return batch_responses

        except Exception as e:
            logger.error(f"❌ 텍스트 생성 실패: {str(e)}", exc_info=True)
            raise

    def _format_metadata(self, result):
        """검색 결과의 메타데이터(출처, 페이지 등)를 보기 좋은 문자열로 포맷팅합니다."""
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
        """텍스트 타입의 검색 결과를 포맷팅합니다."""
        text = str(result.get('text', '')).strip()
        if not text:
            return ""
        meta_info = self._format_metadata(result)
        return f"{index}. {text}{meta_info}"
        
    def _format_table_result(self, result, index):
        """테이블 타입의 검색 결과를 포맷팅합니다."""
        table_data = result.get('table_data', '').strip()
        if not table_data:
            return ""
        meta_info = self._format_metadata(result)
        return f"{index}. 표 데이터{meta_info}\n{table_data}"
    
    def _format_image_result(self, result, index):
        """이미지 타입의 검색 결과를 포맷팅합니다."""
        file_path = result.get("file_path", "")
        title = result.get("title")
        caption = result.get("caption", "")
        
        if not title or str(title).strip().lower() in ["none", ""]:
            if file_path:
                title = os.path.splitext(os.path.basename(file_path))[0]
            else:
                title = "이미지"
        
        title = str(title).strip() if title is not None else "이미지"
        meta_info = self._format_metadata(result)
        image_item = f"{index}. {title}{meta_info}"
        
        if caption and str(caption).strip().lower() not in ["none", ""]:
            image_item += f"\n   - {caption}"
            
        return image_item

    def format_context(self, results) -> str:
        """다양한 타입의 검색 결과들을 LLM에 전달할 최종 컨텍스트(문맥) 문자열로 조합합니다."""
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
                elif content_type == "table" or "table_data" in result:
                    formatted_result = self._format_table_result(result, i)
                elif content_type == "text" or "text" in result:
                    formatted_result = self._format_text_result(result, i)
                
                if formatted_result:
                    context_parts.append(formatted_result)
        
        return "\n".join(context_parts)