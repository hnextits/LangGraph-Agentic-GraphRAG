#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import glob
import json
import argparse
import requests
import base64
import io
import time
from pathlib import Path
from paddleocr import LayoutDetection
from PIL import Image
from tqdm import tqdm

# Ollama API 설정
OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5vl:7b"

# 레이아웃 감지 모델 초기화
def initialize_model():
    return LayoutDetection(
        model_name="PP-DocLayout_plus-L",
        threshold= {
            0: 0.3,   # paragraph_title
            1: 0.5,   # image
            2: 0.5,   # text
            3: 0.5,   # number
            4: 0.5,   # abstract
            5: 0.5,   # content
            6: 0.5,   # figure_table_chart_title
            7: 0.3,   # formula
            8: 0.5,   # table
            9: 0.5,   # reference
            10: 0.5,  # doc_title
            11: 0.5,  # footnote
            12: 0.5,  # header
            13: 0.5,  # algorithm
            14: 0.5,  # footer
            15: 0.45, # seal
            16: 0.5,  # chart
            17: 0.5,  # formula_number
            18: 0.5,  # aside_text
            19: 0.5   # reference_content
        },
        layout_nms=True,
        layout_unclip_ratio=[1.0, 1.0],
        layout_merge_bboxes_mode={
            0: "large",  # paragraph_title
            1: "large",  # image
            2: "large",  # text
            3: "union",  # number
            4: "union",  # abstract
            5: "union",  # content
            6: "large",  # figure_table_chart_title
            7: "large",  # formula
            8: "union",  # table
            9: "union",  # reference
            10: "union", # doc_title
            11: "union", # footnote
            12: "union", # header
            13: "union", # algorithm
            14: "union", # footer
            15: "union", # seal
            16: "large", # chart
            17: "union", # formula_number
            18: "union", # aside_text
            19: "union"  # reference_content
        }
    )

# 이미 처리된 파일인지 확인하는 함수
def is_already_processed(output_dir, file_name, page_num):
    # 페이지 번호가 숫자인지 문자열인지 확인
    if isinstance(page_num, int):
        layout_filename = f"layout_{page_num:03d}"
    else:
        layout_filename = f"layout_{page_num}"
    
    # 출력 파일 경로 확인
    file_output_dir = Path(output_dir) / file_name
    layout_img_path = file_output_dir / f"{layout_filename}.png"
    layout_json_path = file_output_dir / f"{layout_filename}.json"
    
    # 레이아웃 이미지와 JSON 파일이 모두 존재하는지 확인
    return layout_img_path.exists() and layout_json_path.exists()

# 이미지를 base64로 인코딩하는 함수
def encode_image_to_base64(image_path):
    """이미지를 base64로 인코딩"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

# 이미지에서 좌표에 해당하는 부분을 크롭하는 함수
def crop_image_from_coordinates(image_path, coordinates):
    """이미지에서 좌표에 해당하는 부분을 크롭"""
    try:
        img = Image.open(image_path)
        x1, y1, x2, y2 = [int(coord) for coord in coordinates]
        cropped_img = img.crop((x1, y1, x2, y2))
        
        # 메모리에 이미지 저장
        buffer = io.BytesIO()
        cropped_img.save(buffer, format="PNG")
        buffer.seek(0)
        
        # base64로 인코딩
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except Exception as e:
        print(f"이미지 크롭 중 오류 발생: {str(e)}")
        return None

# Ollama API를 사용하여 이미지에서 텍스트 추출하는 함수
def get_ocr_text_from_ollama(image_base64, label):
    """Ollama API를 사용하여 이미지에서 텍스트 추출"""
    prompt = f"이 이미지는 문서에서 감지된 '{label}' 영역입니다. 이미지에 있는 모든 텍스트를 정확하게 추출해주세요. 텍스트만 반환하고 다른 설명은 하지 마세요."
    
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "images": [image_base64]
    }
    
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            response = requests.post(OLLAMA_API_URL, json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "").strip()
            else:
                print(f"API 호출 실패 (상태 코드: {response.status_code}): {response.text}")
                if attempt < max_retries - 1:
                    print(f"{retry_delay}초 후 재시도...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
        except Exception as e:
            print(f"API 호출 중 오류 발생: {str(e)}")
            if attempt < max_retries - 1:
                print(f"{retry_delay}초 후 재시도...")
                time.sleep(retry_delay)
                retry_delay *= 2
    
    return "OCR 처리 실패"

# JSON 파일에 OCR 결과를 추가하는 함수
def add_ocr_to_json(json_path, excluded_labels=None):
    """레이아웃 JSON 파일을 처리하고 OCR 결과 추가"""
    if excluded_labels is None:
        excluded_labels = []
    
    try:
        # JSON 파일 읽기
        with open(json_path, 'r', encoding='utf-8') as f:
            layout_data = json.load(f)
        
        # 입력 이미지 경로 확인
        input_path = layout_data.get("input_path")
        if not input_path or not os.path.exists(input_path):
            print(f"입력 이미지를 찾을 수 없음: {input_path}")
            return False
        
        # 각 박스에 대해 OCR 처리
        for box in tqdm(layout_data.get("boxes", []), desc="OCR 처리 중"):
            label = box.get("label")
            
            # 제외할 레이블이면 건너뛰기
            if label in excluded_labels:
                continue
            
            # 좌표 추출
            coordinates = box.get("coordinate")
            if not coordinates or len(coordinates) != 4:
                continue
            
            # 이미지 크롭 및 base64 인코딩
            cropped_image_base64 = crop_image_from_coordinates(input_path, coordinates)
            if not cropped_image_base64:
                continue
            
            # Ollama API로 OCR 수행
            ocr_text = get_ocr_text_from_ollama(cropped_image_base64, label)
            
            # OCR 결과를 JSON에 추가
            box["text"] = ocr_text
        
        # 수정된 JSON 저장
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(layout_data, f, ensure_ascii=False, indent=4)
        
        return True
    
    except Exception as e:
        print(f"JSON 파일 처리 중 오류 발생: {str(e)}")
        return False

# 이미지 파일 처리 함수
def process_image(model, image_path, output_dir, file_name, page_num, skip_existing=True, ocr=False, excluded_labels=None):
    # 페이지 번호가 숫자인지 문자열인지 확인
    is_numeric_page = isinstance(page_num, int)
    
    # 출력 파일 이름 결정
    if is_numeric_page:
        layout_filename = f"layout_{page_num:03d}"
    else:
        layout_filename = f"layout_{page_num}"
    
    # 이미 처리된 파일인지 확인
    file_output_dir = Path(output_dir) / file_name
    layout_img_path = file_output_dir / f"{layout_filename}.png"
    layout_json_path = file_output_dir / f"{layout_filename}.json"
    
    if skip_existing and layout_img_path.exists() and layout_json_path.exists():
        print(f"이미 처리됨: {image_path} -> {layout_img_path}")
        return True
    
    print(f"레이아웃 감지 처리 중: {image_path}")
    
    # 출력 디렉토리 확인 및 생성
    file_output_dir.mkdir(parents=True, exist_ok=True)
    
    # 레이아웃 감지 실행
    output = model.predict(str(image_path), batch_size=1, layout_nms=True)
    
    # 결과 저장
    for res in output:
        # 결과 출력
        res.print()
        
        # 이미지로 저장
        res.save_to_img(save_path=str(layout_img_path))
        
        # JSON으로 저장
        res.save_to_json(save_path=str(layout_json_path))
    
    print(f"레이아웃 감지 완료: {image_path} -> {layout_img_path}")
    
    # OCR 처리 옵션이 활성화된 경우
    if ocr:
        print(f"OCR 처리 시작: {layout_json_path}")
        ocr_success = add_ocr_to_json(layout_json_path, excluded_labels)
        if ocr_success:
            print(f"OCR 처리 완료: {layout_json_path}")
        else:
            print(f"OCR 처리 실패: {layout_json_path}")
    
    return True

# 마지막으로 처리된 페이지 번호 찾기
def find_last_processed_page(output_dir, file_name):
    pdf_output_dir = Path(output_dir) / 'PDF' / file_name
    img_output_dir = Path(output_dir) / 'IMG' / file_name
    
    # PDF 디렉토리가 있는 경우
    if pdf_output_dir.exists():
        # PDF 디렉토리에서 모든 layout_*.png 파일 찾기
        layout_files = list(pdf_output_dir.glob("layout_*.png"))
        
        if layout_files:
            # 최대 페이지 번호 찾기 (숫자 파일만 처리)
            max_page = 0
            numeric_files_found = False
            
            for layout_file in layout_files:
                try:
                    # layout_001.png 형식에서 페이지 번호 추출
                    page_str = layout_file.stem.split('_')[1]
                    page_num = int(page_str)
                    max_page = max(max_page, page_num)
                    numeric_files_found = True
                except (IndexError, ValueError):
                    # 숫자가 아닌 파일은 무시
                    continue
            
            # 숫자 파일이 있는 경우에만 최대 페이지 번호 반환
            # 숫자 파일이 없는 경우 문자열 'non_numeric' 반환
            return max_page if numeric_files_found else 'non_numeric'
    
    # IMG 디렉토리가 있는 경우
    elif img_output_dir.exists():
        # IMG 디렉토리에서 모든 layout_*.png 파일 찾기
        layout_files = list(img_output_dir.glob("layout_*.png"))
        
        if layout_files:
            # 최대 페이지 번호 찾기 (숫자 파일만 처리)
            max_page = 0
            numeric_files_found = False
            
            for layout_file in layout_files:
                try:
                    # layout_001.png 형식에서 페이지 번호 추출
                    page_str = layout_file.stem.split('_')[1]
                    page_num = int(page_str)
                    max_page = max(max_page, page_num)
                    numeric_files_found = True
                except (IndexError, ValueError):
                    # 숫자가 아닌 파일은 무시
                    continue
            
            # 숫자 파일이 있는 경우에만 최대 페이지 번호 반환
            # 숫자 파일이 없는 경우 문자열 'non_numeric' 반환
            return max_page if numeric_files_found else 'non_numeric'
    
    # PDF와 IMG 디렉토리가 없는 경우
    return 0
    numeric_files_found = False
    
    for layout_file in layout_files:
        try:
            # layout_001.png 형식에서 페이지 번호 추출
            page_str = layout_file.stem.split('_')[1]
            page_num = int(page_str)
            max_page = max(max_page, page_num)
            numeric_files_found = True
        except (IndexError, ValueError):
            # 숫자가 아닌 파일은 무시
            continue
    
    # 숫자 파일이 있는 경우에만 최대 페이지 번호 반환
    # 숫자 파일이 없는 경우 문자열 'non_numeric' 반환
    return max_page if numeric_files_found else 'non_numeric'

# 디렉토리 내 모든 이미지 처리
def process_directory(input_dir, output_dir, skip_existing=True, resume=True, ocr=False, excluded_labels=None):
    print(f"입력 디렉토리: {input_dir}")
    print(f"출력 디렉토리: {output_dir}")
    print(f"이미 처리된 파일 건너뛬기: {skip_existing}")
    print(f"중단된 작업 이어서 처리하기: {resume}")
    
    # 모델 초기화
    model = initialize_model()
    
    # 결과 통계
    stats = {
        'total_dirs': 0,
        'total_images': 0,
        'processed': 0,
        'skipped': 0,
        'failed': 0
    }
    
    # 입력 디렉토리 내 모든 하위 디렉토리 처리
    input_path = Path(input_dir)
    
    # PDF와 IMG 디렉토리 확인
    pdf_dir = input_path / 'PDF'
    img_dir = input_path / 'IMG'
    
    # 모든 하위 디렉토리 찾기 (PDF와 IMG 디렉토리 내의 폴더들)
    subdirs = []
    
    if pdf_dir.exists() and pdf_dir.is_dir():
        subdirs.extend([d for d in pdf_dir.iterdir() if d.is_dir()])
    
    if img_dir.exists() and img_dir.is_dir():
        subdirs.extend([d for d in img_dir.iterdir() if d.is_dir()])
    
    if not subdirs:
        print(f"경고: {input_dir}에 하위 디렉토리가 없습니다. 현재 디렉토리 내 파일들을 처리하겠습니다.")
        subdirs = [input_path]
        # return stats
    
    stats['total_dirs'] = len(subdirs)
    
    # 각 하위 디렉토리 처리
    for src_dir in subdirs:
        # 원본 디렉토리 타입 확인 (PDF 또는 IMG)
        dir_type = 'PDF' if 'PDF' in str(src_dir.parent) else 'IMG'
        file_name = src_dir.name
        print(f"\n처리 중인 {dir_type} 디렉토리: {file_name}")
        
        # 디렉토리 내 모든 PNG 파일 찾기
        png_files = sorted(src_dir.glob("*.png"))
        
        if not png_files:
            print(f"경고: {src_dir}에 PNG 파일이 없습니다.")
            continue
        
        stats['total_images'] += len(png_files)
        
        # 중단된 작업 이어서 처리하기 위해 마지막으로 처리된 페이지 찾기
        last_processed_page = 0
        if resume:
            # 출력 디렉토리 구조에 맞게 경로 설정
            type_output_dir = Path(output_dir) / dir_type
            last_processed_page = find_last_processed_page(type_output_dir, file_name)
            # 숫자 파일이 있는 경우
            if isinstance(last_processed_page, int) and last_processed_page > 0:
                print(f"마지막으로 처리된 페이지: {last_processed_page}, 다음 페이지부터 처리합니다.")
            # 숫자가 아닌 파일만 있는 경우
            elif last_processed_page == 'non_numeric':
                print("숫자가 아닌 파일만 처리되었습니다. 모든 파일을 처리합니다.")
                last_processed_page = 0  # 숫자 파일 처리를 위해 0으로 초기화
        
        # 각 이미지 파일 처리
        for png_file in png_files:
            # 파일 이름에서 페이지 번호 추출 (숫자가 아닌 경우 파일 이름 그대로 사용)
            try:
                page_num = int(png_file.stem)
                is_numeric_filename = True
            except ValueError:
                # 숫자가 아닌 파일 이름(예: test_01_unwarp)의 경우 파일 이름 그대로 사용
                page_num = png_file.stem
                is_numeric_filename = False
            
            # 중단된 작업 이어서 처리하는 경우, 마지막으로 처리된 페이지보다 작은 페이지는 건너뛬기
            # (숫자 파일 이름인 경우에만 적용)
            if resume and is_numeric_filename and isinstance(last_processed_page, int) and page_num <= last_processed_page:
                print(f"건너뛰기 (이미 처리됨): {png_file}")
                stats['skipped'] += 1
                continue
            
            try:
                # 출력 디렉토리 구조에 맞게 경로 설정
                type_output_dir = Path(output_dir) / dir_type
                success = process_image(model, png_file, type_output_dir, file_name, page_num, skip_existing, ocr, excluded_labels)
                if success:
                    if is_already_processed(type_output_dir, file_name, page_num) and skip_existing:
                        stats['skipped'] += 1
                    else:
                        stats['processed'] += 1
                else:
                    stats['failed'] += 1
            except Exception as e:
                print(f"오류: {png_file} 처리 중 예외 발생: {str(e)}")
                stats['failed'] += 1
    
    return stats


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

# 메인 함수
def main():
    parser = argparse.ArgumentParser(description="레이아웃 감지 실행")
    parser.add_argument("--input_dir", type=str, 
                      default=str(BASE_DIR / "data_pipeline" / "Results" / "1.Converted_images"), 
                      help="변환된 PNG 이미지가 있는 디렉토리")
    parser.add_argument("--output_dir", type=str, 
                      default=str(BASE_DIR / "data_pipeline" / "Results" / "2.LayoutDetection"), 
                      help="레이아웃 감지 결과를 저장할 디렉토리")
    parser.add_argument("--skip_existing", action="store_true", help="이미 처리된 파일은 건너뛸기")
    parser.add_argument("--no_skip_existing", action="store_false", dest="skip_existing", help="이미 처리된 파일도 다시 처리하기")
    parser.add_argument("--resume", action="store_true", help="중단된 작업 이어서 처리하기")
    parser.add_argument("--no_resume", action="store_false", dest="resume", help="처음부터 모든 파일 처리하기")
    parser.add_argument("--ocr", action="store_true", help="레이아웃 감지 후 OCR 처리 수행")
    parser.add_argument("--no_ocr", action="store_false", dest="ocr", help="OCR 처리 건너뛰기")
    parser.add_argument("--exclude_labels", type=str, nargs="+", default=["image", "table", "formula"], help="OCR 처리에서 제외할 레이블 목록 (예: image figure table)")
    
    # 기본값 설정
    parser.set_defaults(skip_existing=True, resume=True, ocr=False)
    
    args = parser.parse_args()
    
    # OCR 설정 출력
    if args.ocr:
        print(f"OCR 처리 활성화됨, 제외할 레이블: {args.exclude_labels}")
    
    # 디렉토리 처리 함수 호출
    stats = process_directory(args.input_dir, args.output_dir, args.skip_existing, args.resume, args.ocr, args.exclude_labels)
    
    # 결과 출력
    print("\n===== 레이아웃 감지 결과 =====")
    print(f"처리된 디렉토리: {stats['total_dirs']}개")
    print(f"총 이미지: {stats['total_images']}개")
    print(f"성공: {stats['processed']}개")
    print(f"건너뛰: {stats['skipped']}개")
    print(f"실패: {stats['failed']}개")

if __name__ == "__main__":
    main()
