import sglang as sgl
import logging
import re
import json
import os
import sys
import importlib.util
from pathlib import Path

# 절대 경로로 config.py 가져오기
backend_dir = Path(__file__).parent.parent.absolute()
config_path = backend_dir / "config.py"
spec = importlib.util.spec_from_file_location("backend_config", config_path)
backend_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend_config)

# SearchEngineConfig 가져오기
SearchEngineConfig = backend_config.SearchEngineConfig
config = SearchEngineConfig()

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AnswerGenerator:
    """요약된 텍스트를 기반으로 답변을 생성하는 클래스 (SGLang 버전)"""
    
    def __init__(self):
        self.model_name = config.model # 질문 응답에 적합한 모델
        self.engine = None
        self.model_loaded = False
    
    def load_model(self):
        """SGLang Engine 초기화"""
        try:
            logger.info(f"SGLang Engine 초기화 중: {self.model_name}")
            
            # PyTorch를 사용하여 GPU 메모리 사용량 제한
            import torch
            if torch.cuda.is_available():
                # GPU 메모리의 50%만 사용하도록 설정
                memory_fraction = 0.5
                logger.info(f"GPU 메모리 사용량 제한: {memory_fraction * 100}%")
                torch.cuda.set_per_process_memory_fraction(memory_fraction, 0)
                # 미사용 캐시 메모리 해제
                torch.cuda.empty_cache()
            
            # Engine 클래스를 사용하여 모델 초기화
            self.engine = sgl.Engine(
                model_path=self.model_name,
                mem_fraction_static=0.3,  # 메모리 할당량 제한 (30%)
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
    
    @staticmethod
    def make_llm_input_data(save_dir,json_data):
        """
        summarize_long_text_with_parallel 함수의 출력 JSON에서 link와 data를 추출하여 새로운 데이터를 생성합니다.
        data가 비어있는 경우 google_snipping을 대신 사용합니다.
        
        Args:
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
                with open(os.path.join(save_dir,"processed_data.json"), "w", encoding="utf-8") as f:
                    json.dump(processed_data, f, ensure_ascii=False, indent=4)
                print("처리된 데이터가 JSON 파일로 저장되었습니다.")
            except Exception as e:
                print(f"JSON 파일 저장 중 오류 발생: {e}")
        
        return processed_data

    def get_timestamp(self):
        """현재 시간을 문자열로 반환"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
    def generate_answer(self, google_search_results):
        """요약된 텍스트를 기반으로 답변 생성 - SGLang 버전"""
        
        if not google_search_results:
            return "(관련된 구글 검색 결과를 찾을 수 없습니다)"
        
        # 모델이 로드되지 않았으면 로드
        if not self.model_loaded:
            if not self.load_model():
                return "모델 로딩에 실패하여 답변을 생성할 수 없습니다."
        
        try:
            # 요약 생성을 위한 시스템 프롬프트
            system_prompt = """You are a summarization assistant. Follow the strict format below when generating summaries.

***You MUST respond in Korean ONLY. Do not use English or any other language. All explanations, terms, and sentences must be in Korean.***

# Output Format & Rules
■ Overall Structure
- Do not add any introduction or explanation before the summary.
- The summary must begin with **1. Topic Name**.
- Divide the content into 1 to 5 topics.
- Each topic must be bolded and numbered. (Example: **1. Founding of the Hanwha Eagles**)
- Each topic must consist of 4–5 sentences.
- The entire summary must be at least 25 lines long.

■ Content Creation and Source Citation
- At the end of every sentence, indicate the source number in square brackets. (Example: ...did [1])
- If background knowledge is required due to insufficient search results, add the phrase **(Background Information)** at the end of the sentence.
- The summary must be written entirely in Korean. No English, Chinese, or other languages are allowed.

# Final Output Structure
- After completing the summary, insert a separator line (`---`).
- Below the separator, create a **Source Links** section.
- List all sources in numerical order with their corresponding links."""
            
            # 사용자 프롬프트
            user_prompt = f"""# Input
[Google Search Results]
{google_search_results}"""
            
            # 채팅 형식 프롬프트 구성
            prompt = f"""<|im_start|>system
{system_prompt}<|im_end|>
<|im_start|>user
{user_prompt}<|im_end|>
<|im_start|>assistant
"""
            
            # 샘플링 파라미터 설정
            sampling_params = {
                "temperature": 0.7,
                "top_p": 0.9,
                "max_new_tokens": 8192,
                "stop": ["<|im_end|>", "</think>"]
            }
            
            # SGLang Engine으로 텍스트 생성
            logger.info("SGLang Engine으로 텍스트 생성 시작")
            
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


# def main():
#     None

# if __name__ == "__main__":
#     main()