import json
import copy
import os
import sys
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import glob
import re
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from PIL import Image
from pypdf import PdfReader
import threading
import asyncio
from types import SimpleNamespace
try:
    import sglang as sgl
except ImportError:
    sgl = None

from backend.data_pipeline.pipe.bootstrap import ensure_backend_root

ensure_backend_root()

import backend.data_pipeline.pipe.main_pipe.ocr_pipe.image_utils as image_utils
import backend.data_pipeline.pipe.main_pipe.ocr_pipe.table_format as table_format
import backend.data_pipeline.pipe.main_pipe.ocr_pipe.prompts as prompts

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
    "input_image_folder": str(BASE_DIR / "backend" / "data_pipeline" / "Results" / "1.Converted_images" / "PDF" / "RL_Slides_13_RLHF_DPO_r2"),
    "output_folder": str(BASE_DIR / "backend" / "data_pipeline" / "Results" / "4.OCR_results"),
    "model": "ChatDOC/OCRFlux-3B",
    "batch_size": 32,
    "max_new_tokens": 8192,
    "supported_image_extensions": [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"],
    "engine_mem_fraction": float(os.getenv("OCR_ENGINE_MEM_FRACTION", "0.13")),
    "tensor_parallel_size": int(os.getenv("OCR_TP_SIZE", "1")),
    "enable_cross_page_merge": False,
    "enable_cuda_graph": False,
}
# ====================================

# 전역 SGLang Engine 인스턴스
_ENGINE_INSTANCE = None
_ENGINE_LOCK = threading.Lock()

def _log(msg: str):
    print(msg, flush=True)

def get_ocrflux_engine(config):
    """싱글턴 패턴으로 SGLang Engine 로드"""
    global _ENGINE_INSTANCE
    with _ENGINE_LOCK:
        if _ENGINE_INSTANCE is not None:
            _log("Reusing existing OCRFlux engine")
            return _ENGINE_INSTANCE

        if sgl is None:
            raise ImportError("sglang is not installed")

        _log("Initializing NEW OCRFlux engine...")
        _log(f"  Config: mem_fraction={config.get('engine_mem_fraction', 0.13)}, "
             f"tp_size={config.get('tensor_parallel_size', 1)}, "
             f"cuda_graph={config.get('enable_cuda_graph', False)}")

        if config.get("enable_cuda_graph", False):
            os.environ["SGLANG_VIT_ENABLE_CUDA_GRAPH"] = "1"

        tp_size = config.get("tensor_parallel_size", 1)
        disable_graph = not config.get("enable_cuda_graph", False)

        try:
            _ENGINE_INSTANCE = sgl.Engine(
                model_path=config["model"],
                tp_size=tp_size,
                mem_fraction_static=config.get("engine_mem_fraction", 0.13),
                disable_cuda_graph=disable_graph,
                trust_remote_code=True,
                dtype="auto",
            )
            os.environ["_OCRFLUX_ENGINE_LOADED"] = "1"
            _log("SGLang Engine initialized")
        except Exception as e:
            _log(f"Error initializing SGLang Engine: {e}")
            raise

    return _ENGINE_INSTANCE

def cleanup_engine_cache():
    """작업 완료 후 엔진의 KV 캐시를 정리하여 메모리 누적 방지"""
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        return
    try:
        if hasattr(_ENGINE_INSTANCE, 'abort_request'):
            _ENGINE_INSTANCE.abort_request()
            _log("Engine KV cache cleared successfully")
    except Exception as e:
        _log(f"Failed to cleanup engine cache: {e}")

def shutdown_engine():
    """엔진 완전 종료 (LazyModelManager cleanup 시 호출)"""
    global _ENGINE_INSTANCE
    with _ENGINE_LOCK:
        if _ENGINE_INSTANCE is not None:
            try:
                _log("Shutting down OCRFlux engine...")
                if hasattr(_ENGINE_INSTANCE, 'shutdown'):
                    _ENGINE_INSTANCE.shutdown()
                _ENGINE_INSTANCE = None
                os.environ.pop("_OCRFLUX_ENGINE_LOADED", None)
                _log("OCRFlux engine shutdown complete")
            except Exception as e:
                _log(f"Error during engine shutdown: {e}")

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
    
    t0 = time.time()
    _log(f"Scanning folder: {folder_path}")
    
    for ext in supported_extensions:
        pattern = f"*{ext}"
        files = list(folder_path.glob(pattern))
        files.extend(list(folder_path.glob(pattern.upper())))
        image_files.extend(files)
    
    image_files = sorted(list(set(image_files)))
    
    valid_image_files = []
    for img_file in image_files:
        try:
            with Image.open(img_file) as img:
                img.verify()
            valid_image_files.append(str(img_file))
        except (IOError, SyntaxError) as e:
            _log(f"Skipping invalid image file: {img_file} ({e})")

    _log(f"Found {len(valid_image_files)} valid image files. elapsed={time.time() - t0:.1f}s")
    return valid_image_files

def create_batches(image_files: list, batch_size: int) -> list:
    """이미지 파일들을 배치로 나누기"""
    batches = []
    for i in range(0, len(image_files), batch_size):
        batch = image_files[i:i + batch_size]
        batches.append(batch)

    _log(f"Created {len(batches)} batches with batch size {batch_size}")
    return batches

def safe_json_parse(json_str: str) -> dict:
    """안전한 JSON 파싱"""
    default_response = {
        "primary_language": "ko",
        "is_rotation_valid": True,
        "rotation_correction": 0,
        "is_table": False,
        "is_diagram": False,
        "natural_text": "JSON 파싱 실패"
    }
    
    try:
        data = json.loads(json_str)
        for key, default_value in default_response.items():
            if key not in data:
                data[key] = default_value
        return data
    except:
        pass
    
    try:
        cleaned = re.sub(r'\\u[^0-9a-fA-F]', '', json_str)
        cleaned = re.sub(r'\\u[0-9a-fA-F]{0,3}(?![0-9a-fA-F])', '', cleaned)
        
        if not cleaned.strip().endswith('}'):
            last_quote = cleaned.rfind('",')
            if last_quote > 0:
                cleaned = cleaned[:last_quote + 1] + '}'
            else:
                cleaned += '"}'
        
        data = json.loads(cleaned)
        for key, default_value in default_response.items():
            if key not in data:
                data[key] = default_value
        return data
    except:
        pass
    
    try:
        pattern = r'"natural_text"\s*:\s*"([^"]*(?:\\.[^"]*)*)"'
        match = re.search(pattern, json_str, re.DOTALL)
        if match:
            natural_text = match.group(1)
            natural_text = natural_text.replace('\\"', '"').replace('\\n', '\n')
            default_response["natural_text"] = natural_text
            return default_response
    except:
        pass
    
    return default_response
    
def process_single_response(response_tuple):
    """단일 응답을 처리하여 마크다운 결과를 생성 (병렬 처리를 위해 최상위 레벨로 이동)"""
    response, image_path = response_tuple
    try:
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
        _log(f"Error processing {Path(image_path).name}: {e}")
        _log(f"Raw output causing error: {response.outputs[0].text[:500]}...") # 원본 출력 로깅 추가
        return {
            "image_path": image_path,
            "image_name": Path(image_path).name,
            "markdown_text": f"# {Path(image_path).stem}\n\n[처리 실패: {str(e)}]\n\nRaw: {response.outputs[0].text[:200]}"
        }

def process_image_batch(engine, config, image_batch: list, batch_offset: int = 0, total_images: int = 0, progress_callback=None) -> list:
    """이미지 배치를 SGLang Engine으로 처리"""
    _log(f"Processing batch of {len(image_batch)} images via SGLang Engine...")

    prompts = []
    image_data_list = []
    valid_images = []

    for image_path in image_batch:
        try:
            query = build_image_to_markdown_query(image_path)
            prompts.append(query["prompt"])
            image_data_list.append(query["multi_modal_data"]["image"])
            valid_images.append(image_path)
        except Exception as e:
            _log(f"Failed to build query for {image_path}: {e}")

    if not prompts:
        _log("No valid queries in batch")
        return []

    sampling_params = {
        "temperature": 0.0,
        "max_new_tokens": config["max_new_tokens"],
        "stop": ["<|im_end|>"],
        "repetition_penalty": 1.05,
    }

    t0 = time.time()
    _log(f"Starting batch inference for {len(prompts)} images...")

    # uvloop event loop 처리
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop_policy(None)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _log("Created new asyncio event loop (uvloop policy reset)")

    responses = []
    for idx, (prompt, image_data, image_path) in enumerate(zip(prompts, image_data_list, valid_images)):
        img_name = Path(image_path).name
        current_num = batch_offset + idx + 1
        _log(f"  [{current_num}/{total_images}] Processing {img_name}...")

        if progress_callback is not None:
            try:
                progress_callback("OCR", f"OCR [{current_num}/{total_images}] - {img_name}", current_num, total_images)
            except Exception:
                pass

        img_t0 = time.time()
        try:
            out = engine.generate(
                prompt=prompt,
                image_data=image_data,
                sampling_params=sampling_params,
            )
            responses.append(SimpleNamespace(outputs=[SimpleNamespace(text=out["text"])]))
            _log(f"  [{current_num}/{total_images}] {img_name} done ({time.time() - img_t0:.1f}s)")
        except Exception as e:
            _log(f"  [{current_num}/{total_images}] {img_name} FAILED: {e}")
            _log(traceback.format_exc())
            raise

    _log(f"SGLang Engine generation done. elapsed={time.time() - t0:.1f}s")

    t1 = time.time()
    _log("Postprocess start")
    processed_list = []
    for response, image_path in zip(responses, valid_images):
        result = process_single_response((response, image_path))
        if result is not None:
            processed_list.append(result)

    for idx, result in enumerate(processed_list):
        result["page_number"] = idx + 1

    _log(f"Postprocess done. results={len(processed_list)} elapsed={time.time() - t1:.1f}s")
    return processed_list

def save_results(results: list, output_folder: str, input_folder_name: str):
    """결과를 하나의 마크다운 파일로 저장 (폴더명 사용)"""
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)
    
    md_filename = f"{input_folder_name}.md"
    md_filepath = output_path / md_filename
    
    combined_markdown = []
    
    for result in results:
        image_name = result["image_name"]
        markdown_text = result["markdown_text"]
        
        combined_markdown.append(f"### {image_name}")
        combined_markdown.append(markdown_text)
        combined_markdown.append("")
    
    final_markdown = "\n\n".join(combined_markdown)
    
    with open(md_filepath, "w", encoding='utf-8') as f:
        f.write(final_markdown)

    _log(f"Saved combined markdown: {md_filepath}")
    _log(f"Total images processed: {len(results)}")

def process_image_folder(config):
    """이미지 폴더 전체를 처리하는 메인 함수"""
    total_t0 = time.time()
    _log("=== OCRFlux Image Folder Processing ===")
    _log(f"Input folder: {config['input_image_folder']}")
    _log(f"Output folder: {config['output_folder']}")
    _log(f"Batch size: {config['batch_size']}")
    _log(f"Model: {config['model']}")
    
    input_folder_name = Path(config["input_image_folder"]).name
    _log(f"Output file will be: {input_folder_name}.md")
    
    try:
        image_files = collect_image_files(
            config["input_image_folder"], 
            config["supported_image_extensions"]
        )
    except Exception as e:
        _log(f"Error collecting image files: {e}")
        _log(traceback.format_exc())
        return
    
    if not image_files:
        _log("No valid image files found!")
        return
    
    # SGLang Engine 준비
    engine = get_ocrflux_engine(config)
    
    batches = create_batches(image_files, config["batch_size"])
    
    all_results = []
    for i, batch in enumerate(batches):
        _log(f"\n--- Processing batch {i+1}/{len(batches)} ---")
        _log(f"Progress: {len(all_results)}/{len(image_files)} images completed")
        batch_results = process_image_batch(
            engine,
            config,
            batch,
            batch_offset=len(all_results),
            total_images=len(image_files),
            progress_callback=None,
        )
        all_results.extend(batch_results)
        _log(f"Batch {i+1}/{len(batches)} complete: {len(all_results)}/{len(image_files)} total images done")
    
    _log(f"\n--- Saving {len(all_results)} results to single MD file ---")
    save_results(all_results, config["output_folder"], input_folder_name)
    
    _log("=== Processing completed ===")
    _log(f"Results saved as: {config['output_folder']}/{input_folder_name}.md")
    _log(f"Total elapsed: {time.time() - total_t0:.1f}s")
    
    _log("\n--- Cleaning up engine cache ---")
    cleanup_engine_cache()

if __name__ == '__main__':
    config = CONFIG
    process_image_folder(config)
