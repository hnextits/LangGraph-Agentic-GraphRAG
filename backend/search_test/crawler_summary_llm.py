from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
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

class AnswerGenerator:
    """요약된 텍스트를 기반으로 답변을 생성하는 클래스"""
    
    def __init__(self):
        self.model_name = config.model # 질문 응답에 적합한 모델
        self.tokenizer = None
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
    
    def load_model(self):
        """모델 로드 - Qwen3 공식 사용법에 맞게 구현"""
        try:
            print(f"답변 생성 모델 로딩 중: {self.model_name}")
            
            # 토크나이저 로드 - Qwen3 권장 설정
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            
            # 모델 로드 - 공식 권장 설정 사용
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype="auto",  # 자동으로 최적의 dtype 선택
                device_map="auto"    # 자동으로 최적의 디바이스 할당
            )
            
            # 디바이스 정보 업데이트
            self.device = next(self.model.parameters()).device
            print(f"모델이 {self.device}에 로드되었습니다.")
                
            print("답변 생성 모델 로딩 완료")
            return True
        except Exception as e:
            print(f"모델 로딩 실패: {e}")
            return False
    
    def cleanup_model(self):
        """모델 메모리 정리"""
        try:
            if self.model is not None:
                del self.model
                self.model = None
            if self.tokenizer is not None:
                del self.tokenizer
                self.tokenizer = None
            
            # GPU 메모리 정리
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            
            print("모델 메모리 정리 완료")
        except Exception as e:
            print(f"모델 메모리 정리 중 오류: {e}")
    
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
        """요약된 텍스트를 기반으로 답변 생성 - Qwen3 공식 사용법에 맞게 구현"""
        
        if not google_search_results:
            return "(관련된 구글 검색 결과를 찾을 수 없습니다)"
        
        # 모델이 로드되지 않았으면 로드
        if not self.model or not self.tokenizer:
            if not self.load_model():
                return "모델 로딩에 실패하여 답변을 생성할 수 없습니다."
        
        try:
            # 요약 생성을 위한 프롬프트 작성
            prompt = f"""
                # Role
                You are a summarization assistant. Follow the strict format below when generating summaries.

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
                - List all sources in numerical order with their corresponding links.

                # Input
                [Google Search Results]
                {google_search_results}
                """
            
            # Qwen3 공식 사용법에 따른 메시지 형식
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
            
            # Qwen3 공식 사용법에 따른 토크나이저 설정
            text = self.tokenizer.apply_chat_template(
                messages, 
                tokenize=False, 
                add_generation_prompt=True,
                enable_thinking=False  # 생각 모드 비활성화
            )
            
            # 모델 입력 준비 - 공식 문서에 따른 방식
            model_inputs = self.tokenizer([text], return_tensors="pt").to(self.device)
            
            # 공식 문서에 따른 생성 파라미터 설정
            # 안정적인 생성을 위해 보수적인 설정 사용
            generation_config = {
                "max_new_tokens": 8192,  # 적절한 최대 토큰 수
                "do_sample": False,      # 결정적 생성을 위해 False 사용
                "temperature": 0.7,      # 적절한 온도
                "repetition_penalty": 1.1  # 반복 패널티
            }
            
            # 텍스트 생성
            with torch.no_grad():  # 메모리 사용량 감소를 위해 그래디언트 계산 비활성화
                generated_ids = self.model.generate(
                    **model_inputs,
                    **generation_config
                )
            
            # 생성된 텍스트 추출 - 공식 문서 방식 사용
            output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist()
            
            # 생각 컨텐츠 처리 (생각 모드를 사용하는 경우)
            try:
                # </think> 토큰 ID 찾기 (151668)
                think_end_token_id = 151668
                index = len(output_ids) - output_ids[::-1].index(think_end_token_id) if think_end_token_id in output_ids else 0
            except ValueError:
                index = 0
                
            # 생성된 콘텐츠 추출
            content = self.tokenizer.decode(output_ids[index:], skip_special_tokens=True).strip("\n")
            
            # 메모리 정리
            del model_inputs, generated_ids, output_ids
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                
            return content
            
        except Exception as e:
            print(f"답변 생성 중 오류 발생: {e}")
            return f"답변 생성에 실패했습니다: {str(e)}"


def main():
    None

if __name__ == "__main__":
    main()
