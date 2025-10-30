import json
import copy
import os
import sys
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import glob
import re
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from PIL import Image
from pypdf import PdfReader
from vllm import LLM, SamplingParams

# 프로젝트 루트 디렉토리를 Python 경로에 추가
project_root = str(Path(__file__).resolve().parent.parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 절대 경로 임포트 사용
import backend.nextits_data.pipe.main_pipe.ocr_pipe.image_utils as image_utils
import backend.nextits_data.pipe.main_pipe.ocr_pipe.table_format as table_format
import backend.nextits_data.pipe.main_pipe.ocr_pipe.prompts as prompts

# 함수 참조 간소화
get_page_image = image_utils.get_page_image
is_image = image_utils.is_image
table_matrix2html = table_format.table_matrix2html
PageResponse = prompts.PageResponse
build_page_to_markdown_prompt = prompts.build_page_to_markdown_prompt
build_element_merge_detect_prompt = prompts.build_element_merge_detect_prompt
build_html_table_merge_prompt = prompts.build_html_table_merge_prompt

# 스크립트 위치를 기준으로 backend/ 디렉토리
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent.parent

# ============= 설정 구간 =============
CONFIG = {
    "input_image_folder": str(BASE_DIR / "backend" / "nextits_data" / "Results" / "1.Converted_images" / "PDF" / "원가관리회계"),  # 입력 이미지 폴더 경로
    "output_folder": str(BASE_DIR / "backend" / "nextits_data" / "Results" / "3.OCR_results"),  # 출력 폴더 경로
    "model": "ChatDOC/OCRFlux-3B",  # 모델 경로
    "batch_size": 256,  # 배치 크기
    "gpu_memory_utilization": 0.2,  # GPU 메모리 사용률
    "max_model_len": 32768,  # 모델 최대 길이
    "supported_image_extensions": [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"]
}
# ====================================

# 전역 모델 인스턴스
LLM_MODEL = None

def load_model(config):
    """모델을 한 번만 로드하여 전역 변수에 저장"""
    global LLM_MODEL
    if LLM_MODEL is None:
        print("Loading vLLM model for the first time...")
        LLM_MODEL = LLM(
            model=config["model"],
            gpu_memory_utilization=config["gpu_memory_utilization"],
            max_model_len=config["max_model_len"],
            trust_remote_code=True,  # 일부 모델은 이 옵션이 필요할 수 있습니다
            # attn_backend="eager"  # Flash-Attention 2 사용 명시
            enforce_eager=True,
        )
        print("vLLM model loaded successfully.")
    return LLM_MODEL

def build_qwen2_5_vl_prompt(question):
    return (
            "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n"
            f"<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|>"
            f"{question}<|im_end|>\n"
            "<|im_start|>assistant\n"
    )

def build_image_to_markdown_query(image_path: str, image_rotation: int = 0) -> dict:
    assert image_rotation in [0, 90, 180, 270], "Invalid image rotation provided in build_image_query"
    image = get_page_image(image_path, 1, image_rotation=image_rotation)
    question = build_page_to_markdown_prompt()
    prompt = build_qwen2_5_vl_prompt(question)
    query = {
        "prompt": prompt,
        "multi_modal_data": {"image": image},
    }
    return query

def collect_image_files(folder_path: str, supported_extensions: list) -> list:
    """폴더에서 지원하는 이미지 파일들을 수집"""
    image_files = []
    folder_path = Path(folder_path)
    
    if not folder_path.exists():
        raise ValueError(f"Image folder does not exist: {folder_path}")
    
    print(f"Scanning folder: {folder_path}")
    
    for ext in supported_extensions:
        # 대소문자 구분 없이 검색
        pattern = f"*{ext}"
        files = list(folder_path.glob(pattern))
        files.extend(list(folder_path.glob(pattern.upper())))
        image_files.extend(files)
    
    # 중복 제거 및 정렬
    image_files = sorted(list(set(image_files)))
    
    # PIL을 사용하여 실제 이미지 파일인지 검증
    valid_image_files = []
    for img_file in image_files:
        try:
            with Image.open(img_file) as img:
                img.verify()  # 이미지 데이터가 유효한지 확인
            valid_image_files.append(str(img_file))
        except (IOError, SyntaxError) as e:
            print(f"Skipping invalid image file: {img_file} ({e})")
    
    print(f"Found {len(valid_image_files)} valid image files")
    return valid_image_files

def create_batches(image_files: list, batch_size: int) -> list:
    """이미지 파일들을 배치로 나누기"""
    batches = []
    for i in range(0, len(image_files), batch_size):
        batch = image_files[i:i + batch_size]
        batches.append(batch)
    
    print(f"Created {len(batches)} batches with batch size {batch_size}")
    return batches

def safe_json_parse(json_str: str) -> dict:
    """안전한 JSON 파싱"""
    # 기본 PageResponse 구조
    default_response = {
        "primary_language": "ko",
        "is_rotation_valid": True,
        "rotation_correction": 0,
        "is_table": False,
        "is_diagram": False,
        "natural_text": "JSON 파싱 실패"
    }
    
    try:
        # 1차 시도: 원본 그대로
        data = json.loads(json_str)
        # 필수 필드 확인 및 보완
        for key, default_value in default_response.items():
            if key not in data:
                data[key] = default_value
        return data
    except:
        pass
    
    try:
        # 2차 시도: 간단한 정리 후
        # 유니코드 이스케이프 문제 수정
        cleaned = re.sub(r'\\u[^0-9a-fA-F]', '', json_str)  # 잘못된 \u 제거
        cleaned = re.sub(r'\\u[0-9a-fA-F]{0,3}(?![0-9a-fA-F])', '', cleaned)  # 불완전한 \u 제거
        
        # 문자열이 제대로 닫히지 않았으면 닫기
        if not cleaned.strip().endswith('}'):
            # 마지막 완전한 부분 찾기
            last_quote = cleaned.rfind('",')
            if last_quote > 0:
                cleaned = cleaned[:last_quote + 1] + '}'
            else:
                cleaned += '"}'
        
        data = json.loads(cleaned)
        # 필수 필드 확인 및 보완
        for key, default_value in default_response.items():
            if key not in data:
                data[key] = default_value
        return data
    except:
        pass
    
    try:
        # 3차 시도: natural_text만 추출
        pattern = r'"natural_text"\s*:\s*"([^"]*(?:\\.[^"]*)*)"'
        match = re.search(pattern, json_str, re.DOTALL)
        if match:
            natural_text = match.group(1)
            # 이스케이프 문자 처리
            natural_text = natural_text.replace('\\"', '"').replace('\\n', '\n')
            default_response["natural_text"] = natural_text
            return default_response
    except:
        pass
    
    # 완전 실패시 기본값 반환
    return default_response
    
def process_single_response(response_tuple):
    """단일 응답을 처리하여 마크다운 결과를 생성 (병렬 처리를 위해 최상위 레벨로 이동)"""
    response, image_path = response_tuple
    try:
        # <image> 태그를 정규식으로 제거
        raw_text = re.sub(r'<image>', '', response.outputs[0].text).strip()
        parsed_data = safe_json_parse(raw_text)
        
        markdown_element_list = []
        if parsed_data.get("is_table", False) and parsed_data.get("table_matrix"):
            table_html = table_matrix2html(parsed_data["table_matrix"])
            markdown_element_list.append(table_html)

        if parsed_data.get("natural_text"):
            text = parsed_data["natural_text"]
            markdown_element_list.append(text)
        
        final_markdown = "\n\n".join(markdown_element_list)
        
        result = {
            "image_path": image_path,
            "image_name": Path(image_path).name,
            "markdown_text": final_markdown
        }
        # print(f"Successfully processed: {Path(image_path).name}") # 주석 처리 (로그가 너무 많이 찍힘)
        return result
        
    except Exception as e:
        print(f"Error processing {Path(image_path).name}: {e}")
        return {
            "image_path": image_path,
            "image_name": Path(image_path).name,
            "markdown_text": f"# {Path(image_path).stem}\n\n[처리 실패: {str(e)}]"
        }

def process_image_batch(llm, image_batch: list) -> list:
    """이미지 배치를 처리하여 마크다운 결과 반환"""
    print(f"Processing batch of {len(image_batch)} images...")
    # 병렬로 쿼리 생성 (전처리)
    query_list = []
    valid_images = []

    def create_query(image_path):
        try:
            # 각 스레드에서 쿼리를 생성
            return image_path, build_image_to_markdown_query(image_path)
        except Exception as e:
            print(f"Failed to create query for {image_path}: {e}")
            return image_path, None

    with ThreadPoolExecutor() as executor:
        # map을 사용하여 각 이미지에 대해 create_query 함수를 병렬로 실행
        results = executor.map(create_query, image_batch)

    for image_path, query in results:
        if query:
            query_list.append(query)
            valid_images.append(image_path)
    
    if not query_list:
        print("No valid queries in batch")
        return []
    
    # 샘플링 파라미터 설정
    sampling_params = SamplingParams(
        temperature=0.0, 
        max_tokens=32768,
        stop=["<|im_end|>"],
        repetition_penalty=1.05
    )
    
    # vLLM으로 배치 생성
    responses = llm.generate(query_list, sampling_params=sampling_params)


    # ProcessPoolExecutor를 사용하여 CPU 바운드 후처리 작업을 병렬화 (GIL 우회)
    with ProcessPoolExecutor() as executor:
        processed_results = executor.map(process_single_response, zip(responses, valid_images))

    return [res for res in processed_results if res is not None]

def save_results(results: list, output_folder: str, input_folder_name: str):
    """결과를 하나의 마크다운 파일로 저장 (폴더명 사용)"""
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 폴더명으로 MD 파일명 생성
    md_filename = f"{input_folder_name}.md"
    md_filepath = output_path / md_filename
    
    # 모든 결과를 하나의 마크다운 파일로 합치기
    combined_markdown = []
    
    for result in results:
        image_name = result["image_name"]
        markdown_text = result["markdown_text"]
        
        # 각 이미지별로 구분자 추가
        combined_markdown.append(f"###{image_name}")
        combined_markdown.append(markdown_text)
        combined_markdown.append("")  # 빈 줄로 구분
    
    # 전체 마크다운 텍스트 생성
    final_markdown = "\n\n".join(combined_markdown)
    
    # 마크다운 파일 저장
    with open(md_filepath, "w", encoding='utf-8') as f:
        f.write(final_markdown)
    
    print(f"Saved combined markdown: {md_filepath}")
    print(f"Total images processed: {len(results)}")

def process_image_folder(config):
    """이미지 폴더 전체를 처리하는 메인 함수"""
    print("=== OCRFlux Image Folder Processing ===")
    print(f"Input folder: {config['input_image_folder']}")
    print(f"Output folder: {config['output_folder']}")
    print(f"Batch size: {config['batch_size']}")
    print(f"Model: {config['model']}")
    
    # 입력 폴더명 추출
    input_folder_name = Path(config["input_image_folder"]).name
    print(f"Output file will be: {input_folder_name}.md")
    
    # 이미지 파일 수집
    try:
        image_files = collect_image_files(
            config["input_image_folder"], 
            config["supported_image_extensions"]
        )
    except Exception as e:
        print(f"Error collecting image files: {e}")
        return
    
    if not image_files:
        print("No valid image files found!")
        return
    
    # vLLM 모델 로드 (전역 인스턴스 사용)
    llm = load_model(config)
    
    # 배치 생성
    batches = create_batches(image_files, config["batch_size"])
    
    # 각 배치 처리
    all_results = []
    for i, batch in enumerate(batches):
        print(f"\n--- Processing batch {i+1}/{len(batches)} ---")
        batch_results = process_image_batch(llm, batch)
        all_results.extend(batch_results)
    
    # 결과를 하나의 MD 파일로 저장
    print(f"\n--- Saving {len(all_results)} results to single MD file ---")
    save_results(all_results, config["output_folder"], input_folder_name)
    
    print("=== Processing completed ===")
    print(f"Results saved as: {config['output_folder']}/{input_folder_name}.md")

if __name__ == '__main__':
    config = CONFIG
    process_image_folder(config)
