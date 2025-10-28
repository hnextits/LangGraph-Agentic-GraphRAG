#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
요약 기능 모듈
SGLang Engine을 직접 사용하여 독립적으로 작동
md_summarizer 없이도 완전히 독립적으로 작동 가능
"""

import sglang as sgl
import logging
import re
import json
import os

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class AnswerGenerator:
    """MD 문서 요약을 위한 생성기 (SGLang Engine 직접 로드 방식)"""
    
    def __init__(self, model_name: str = "Qwen/Qwen3-4B-Instruct-2507"):
        """
        초기화
        
        Args:
            model_name: 사용할 모델 이름
        """
        self.model_name = model_name
        self.engine = None
        self.model_loaded = False
    
    def load_model(self):
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
            
            # Engine 클래스를 사용하여 모델 초기화
            # mem_fraction_static: SGLang이 사용할 GPU 메모리 비율
            # Qwen3-4B 모델은 약 8GB 필요, 0.2 = 20% 정도면 충분
            self.engine = sgl.Engine(
                model_path=self.model_name,
                mem_fraction_static=0.2,  # 메모리 할당량 제한 (20% - 약 16GB)
                disable_cuda_graph=True,  # CUDA 그래프 비활성화로 안정성 향상
                trust_remote_code=True,   # 원격 코드 신뢰
                dtype="auto"              # 자동으로 적절한 dtype 선택
            )
            
            self.model_loaded = True
            logger.info("SGLang Engine 초기화 완료")
            return True
        except Exception as e:
            logger.error(f"SGLang Engine 초기화 실패: {e}")
            self.model_loaded = False
            return False
    
    def cleanup_model(self):
        """모델 메모리 정리"""
        try:
            if self.engine is not None:
                del self.engine
                self.engine = None
            
            self.model_loaded = False
            logger.info("모델 메모리 정리 완료")
        except Exception as e:
            logger.error(f"모델 메모리 정리 중 오류: {e}")
    
    def generate_answer(self, content: str, max_tokens: int = 8192) -> str:
        """
        MD 문서 요약 생성
        
        Args:
            content: 요약할 문서 내용
            max_tokens: 최대 생성 토큰 수
            
        Returns:
            str: 생성된 요약 텍스트
        """
        if not content or content.isspace():
            return "(관련된 구글 검색 결과를 찾을 수 없습니다)"
        
        # 모델이 로드되지 않았으면 로드
        if not self.model_loaded:
            if not self.load_model():
                return "모델 로딩에 실패하여 답변을 생성할 수 없습니다."
        
        try:
            # 요약 생성을 위한 시스템 프롬프트
            system_prompt = """You are an expert summarizer. Read the following document carefully and provide a clear, accurate, and well-structured summary.
Focus on the key ideas, main arguments, important data points, and overall conclusions.
Avoid unnecessary details or examples.
Use concise and professional language suitable for an executive or technical audience.

The summary must be written entirely in Korean.

Please organize the output as follows:

Overview: A brief description of the document's purpose and scope.

Key Points: The most important findings, arguments, or insights (in bullet points).

Conclusion/Implications: What the document ultimately conveys or recommends.

(Optional) Notable Quotes or Data: If there are any key phrases or statistics worth highlighting."""
            
            # 사용자 프롬프트
            user_prompt = f"""Input document:
{content}

**output:**"""
            
            # 채팅 형식 프롬프트 구성
            prompt = f"""<|im_start|>system
{system_prompt}<|im_end|>
<|im_start|>user
{user_prompt}<|im_end|>
<|im_start|>assistant
"""
            
            # 샘플링 파라미터 설정
            sampling_params = {
                "temperature": 0.5,
                "top_p": 0.9,
                "max_new_tokens": max_tokens,
                "repetition_penalty": 1.3,
                "stop": ["<|im_end|>", "</think>"]
            }
            
            # SGLang Engine으로 텍스트 생성
            logger.info("SGLang Engine으로 텍스트 생성 시작")
            
            # 이벤트 루프 충돌 방지를 위해 ThreadPoolExecutor 사용
            import concurrent.futures
            import asyncio
            
            def run_generate_in_thread():
                """별도 스레드에서 새 이벤트 루프로 실행"""
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return self.engine.generate(prompt=prompt, sampling_params=sampling_params)
                finally:
                    new_loop.close()
                    asyncio.set_event_loop(None)
            
            # 현재 이벤트 루프 확인
            try:
                current_loop = asyncio.get_running_loop()
                # 이미 실행 중인 루프가 있으면 ThreadPoolExecutor 사용
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    result = executor.submit(run_generate_in_thread).result()
            except RuntimeError:
                # 실행 중인 루프가 없으면 직접 호출
                result = self.engine.generate(prompt=prompt, sampling_params=sampling_params)
            
            response = result["text"]
            
            # <think> 태그 제거
            response = re.sub(r'<[tT]hink>.*?</[tT]hink>', '', response, flags=re.DOTALL)
            
            # 불필요한 공백/줄바꿈 정리
            response = response.strip()
            
            logger.info("SGLang 텍스트 생성 완료")
            return response
            
        except Exception as e:
            logger.error(f"답변 생성 중 오류 발생: {e}")
            return f"답변 생성에 실패했습니다: {str(e)}"
    
    @staticmethod
    def make_llm_input_data(save_dir, json_data):
        """
        summarize_long_text_with_parallel 함수의 출력 JSON에서 link와 data를 추출하여 새로운 데이터를 생성합니다.
        data가 비어있는 경우 google_snipping을 대신 사용합니다.
        
        Args:
            save_dir: 저장할 디렉토리
            json_data: summarize_long_text_with_parallel 함수에서 생성된 JSON 데이터
        Return:
            processed_data: link와 data(또는 google_snipping)를 포함한 새로운 JSON 데이터
        """
        processed_data = []
        
        for item in json_data:
            # 기본 구조 생성
            processed_item = {
                "link": item.get("link", ""),
                "data": ""
            }
            
            # data 필드 확인 및 처리
            data = item.get("data")
            if not data or (isinstance(data, str) and data.strip() == ""):
                # data가 비어있으면 google_snipping 사용
                processed_item["data"] = item.get("google_snipping", "")
            else:
                # data가 있으면 그대로 사용
                processed_item["data"] = data
            
            processed_data.append(processed_item)
        
        # 처리된 데이터를 JSON 파일로 저장
        if save_dir:
            try:
                if not os.path.exists(save_dir):
                    os.makedirs(save_dir, exist_ok=True)
                with open(os.path.join(save_dir, "processed_data.json"), "w", encoding="utf-8") as f:
                    json.dump(processed_data, f, ensure_ascii=False, indent=4)
                logger.info("처리된 데이터가 JSON 파일로 저장되었습니다.")
            except Exception as e:
                logger.error(f"JSON 파일 저장 중 오류 발생: {e}")
        
        return processed_data


class Summarizer:
    """
    통합 요약 클래스
    AnswerGenerator를 래핑하여 사용
    """
    
    def __init__(self, model_name: str = "Qwen/Qwen3-4B-Instruct-2507"):
        """
        초기화
        
        Args:
            model_name: 사용할 모델 이름
        """
        self.model_name = model_name
        self.generator = AnswerGenerator(model_name=model_name)
        self.is_loaded = False
    
    def load(self):
        """모델 로드"""
        self.is_loaded = self.generator.load_model()
        return self.is_loaded
    
    def summarize(self, content: str, max_tokens: int = 8192) -> str:
        """
        텍스트 요약
        
        Args:
            content: 요약할 텍스트
            max_tokens: 최대 생성 토큰 수
            
        Returns:
            str: 요약된 텍스트
        """
        if not self.is_loaded:
            if not self.load():
                return "요약 모델을 로드할 수 없습니다."
        
        return self.generator.generate_answer(content, max_tokens=max_tokens)
    
    def cleanup(self):
        """모델 메모리 정리"""
        if self.is_loaded:
            self.generator.cleanup_model()
            self.is_loaded = False


# 간단한 텍스트 요약 함수 (LLM 없이)
def simple_summarize(text: str, ratio: float = 0.3) -> str:
    """
    간단한 텍스트 요약 (앞부분 추출)
    
    Args:
        text: 요약할 텍스트
        ratio: 추출 비율
        
    Returns:
        str: 요약된 텍스트
    """
    if not text or not text.strip():
        return "요약할 텍스트가 없습니다."
    
    summary_length = int(len(text) * ratio)
    if summary_length <= 0:
        return "요약할 텍스트가 없습니다."
    
    return text[:summary_length]
