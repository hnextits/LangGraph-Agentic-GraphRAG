#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import shutil
import re
import math
import datetime
import argparse
from pathlib import Path
from PIL import Image
import logging
import base64
import io
import cv2
import numpy as np
import traceback
from glob import glob

PROJECT_ROOT = Path(__file__).resolve().parents[4]
import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.data_pipeline.pipe.bootstrap import ensure_backend_root, configure_logging

ensure_backend_root()
configure_logging()
logger = logging.getLogger(__name__)

# 대상 레이블 (이 레이블만 크롭)
TARGET_LABELS = ['image','chart']

# 패딩 값 (바운딩 박스보다 상하좌우로 얼마나 더 크게 자를지)
PADDING = 5

# figure_title과의 최대 거리 (이 거리 내에 있는 figure_title을 찾음)
MAX_TITLE_DISTANCE = 50

# 최소 바운딩 박스 크기 설정 (이 크기보다 작은 바운딩 박스는 크롭하지 않음)
# 형식: {레이블: (최소 너비, 최소 높이)}
MIN_BOX_SIZE = {
    # 'image': (150, 150),  # 이미지는 최소 150x150 픽셀 이상
    # 'chart': (150, 150),  # 차트는 최소 150x150 픽셀 이상
    # 'table': (50, 20),  # 표는 최소 50x20 픽셀 이상
    # 'formula': (20, 10)  # 수식은 최소 20x10 픽셀 이상
}

# 최대 바운딩 박스 크기 설정 (이 크기보다 큰 바운딩 박스는 크롭하지 않음)
# 형식: {레이블: (최대 너비, 최대 높이)}
MAX_BOX_SIZE = {
    'image': (800, 850),  # 이미지는 최대 800x850 픽셀 이하
    'chart': (800, 850),  # 차트는 최대 800x850 픽셀 이하
}

# 스크립트 위치를 기준으로 backend/ 디렉토리
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

# 상대 경로로 디렉토리 설정
LAYOUT_DETECTION_DIR = BASE_DIR / "data_pipeline" / "Results" / "2.LayoutDetection"
CROP_IMAGE_DIR = BASE_DIR / "data_pipeline" / "Results" / "3.Crop_image"
OCR_RESULTS_DIR = BASE_DIR / "data_pipeline" / "Results" / "4.OCR_results"

# 기본값 설정 (명령행 인자로 재정의 가능)
INPUT_DIR = LAYOUT_DETECTION_DIR
OUTPUT_DIR = CROP_IMAGE_DIR

# 이미 처리된 파일 기록을 위한 세트
processed_files = set()

# 마지막으로 처리된 파일 경로 (이어하기 기능용)
last_processed_file = None

# 현재 날짜 (메타데이터용)
CURRENT_DATE = datetime.datetime.now().strftime("%Y.%m.%d")

def calculate_distance(box1, box2):
    """두 바운딩 박스 사이의 최소 거리 계산
    
    Args:
        box1: [x1, y1, x2, y2] 형식의 바운딩 박스 좌표
        box2: [x1, y1, x2, y2] 형식의 바운딩 박스 좌표
        
    Returns:
        두 박스 사이의 최소 거리. 격자가 겹치면 0 반환
    """
    # 박스 1의 좌표
    x1_1, y1_1, x2_1, y2_1 = box1
    
    # 박스 2의 좌표
    x1_2, y1_2, x2_2, y2_2 = box2
    
    # x축 거리 계산
    if x1_1 <= x2_2 and x2_1 >= x1_2:  # x축으로 격자가 겹치는 경우
        x_dist = 0
    else:
        x_dist = max(0, x1_2 - x2_1) if x1_2 > x2_1 else max(0, x1_1 - x2_2)
    
    # y축 거리 계산
    if y1_1 <= y2_2 and y2_1 >= y1_2:  # y축으로 격자가 겹치는 경우
        y_dist = 0
    else:
        y_dist = max(0, y1_2 - y2_1) if y1_2 > y2_1 else max(0, y1_1 - y2_2)
    
    # 유클리드 거리 계산
    if x_dist == 0 and y_dist == 0:  # 격자가 겹치는 경우
        return 0
    else:
        return math.sqrt(x_dist**2 + y_dist**2)

def get_bbox_size(box):
    """바운딩 박스의 너비와 높이 계산
    
    Args:
        box: [x1, y1, x2, y2] 형식의 바운딩 박스 좌표
        
    Returns:
        (너비, 높이) 튜플
    """
    x1, y1, x2, y2 = box
    width = abs(x2 - x1)
    height = abs(y2 - y1)
    return width, height

def extract_page_num(filename):
    """파일 이름에서 페이지 번호 추출
    
    Args:
        filename: 파일 이름 (예: layout_001.png)
        
    Returns:
        페이지 번호 문자열 또는 None
    """
    # layout_ 뒤의 숫자 추출
    match = re.search(r'layout_([0-9]+)', filename)
    if match:
        return match.group(1)
    return None

def extract_ocr_text_for_page(ocr_file_path, page_num):
    """OCR 결과 파일에서 특정 페이지 번호에 해당하는 텍스트 추출
    
    Args:
        ocr_file_path: OCR 결과 파일 경로
        page_num: 페이지 번호 (문자열)
        
    Returns:
        추출된 텍스트 또는 None
    """
    try:
        # OCR 결과 디렉토리 존재 여부 확인
        if not OCR_RESULTS_DIR.exists():
            logger.warning(f"OCR 결과 디렉토리가 존재하지 않음: {OCR_RESULTS_DIR}")
            return None
            
        if not os.path.exists(ocr_file_path):
            logger.warning(f"OCR 결과 파일을 찾을 수 없음: {ocr_file_path}")
            # OCR 디렉토리에 있는 파일들 나열
            if OCR_RESULTS_DIR.exists():
                available_files = list(OCR_RESULTS_DIR.glob("*.md"))
                logger.info(f"OCR 디렉토리에 있는 파일들: {[f.name for f in available_files]}")
            return None
            
        # 페이지 번호 형식 맞추기 (예: '1' -> '001')
        formatted_page_num = page_num.zfill(3)
        
        with open(ocr_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 구분자 패턴 (###014.png 또는 ####014.png 형식)
        target_marker = f"###{formatted_page_num}.png"
        # 정규식으로 모든 페이지 구분자 찾기 (### or #### + 3자리숫자.png)
        all_markers = list(re.finditer(r"(#{3,4}\d{3}\.png)", content))
        
        # 디버깅: 찾은 모든 구분자 출력
        found_markers = [match.group(1) for match in all_markers]
        logger.debug(f"OCR 파일에서 찾은 구분자들: {found_markers[:10]}...")  # 처음 10개만 출력
        logger.debug(f"찾는 구분자: {target_marker}")
        
        # 현재 페이지 구분자 찾기
        current_marker = None
        next_marker = None
        
        for i, match in enumerate(all_markers):
            marker_text = match.group(1)
            # `###` 또는 `####` 형식을 모두 고려하여 target_marker와 비교
            if marker_text.endswith(target_marker):
                current_marker = match
                logger.debug(f"찾은 구분자: {marker_text}")
                # 다음 구분자가 있으면 저장
                if i + 1 < len(all_markers):
                    next_marker = all_markers[i + 1]
                    logger.debug(f"다음 구분자: {next_marker.group(1)}")
                break
                
        if current_marker is None:
            logger.warning(f"페이지 {page_num}(형식: {formatted_page_num})에 대한 구분자를 찾을 수 없음")
            # 비슷한 구분자가 있는지 확인
            similar_markers = [m for m in found_markers if page_num in m or formatted_page_num in m]
            if similar_markers:
                logger.info(f"비슷한 구분자들: {similar_markers}")
            return None
            
        # 현재 구분자부터 다음 구분자 전까지의 내용 추출
        start_pos = current_marker.start()
        end_pos = next_marker.start() if next_marker else len(content)
        
        extracted_text = content[start_pos:end_pos].strip()
        
        # 빈 텍스트인 경우 None 반환
        if not extracted_text or extracted_text == current_marker.group(1):
            return None
            
        return extracted_text
        
    except Exception as e:
        logger.error(f"OCR 텍스트 추출 중 오류 발생: {e}")
        return None

def create_metadata(crop_path, original_json_path, pdf_folder_name, label, box_coords, boxes_data, page_num=None, index_num=1, number=None):
    """크롭된 이미지의 메타데이터 생성
    
    Args:
        crop_path: 크롭된 이미지 경로
        original_json_path: 원본 JSON 파일 경로
        pdf_folder_name: PDF 폴더 이름
        label: 크롭된 객체의 레이블
        box_coords: 크롭된 객체의 바운딩 박스 좌표
        boxes_data: 전체 바운딩 박스 데이터
        page_num: 페이지 번호 (선택적)
        index_num: 같은 페이지에서 같은 서브타이틀을 갖는 객체의 순서
        
    Returns:
        메타데이터 디셔너리
    """
    # 페이지 번호 처리
    if page_num is None:
        # IMAGERENDERING 폴더인지 확인
        if "IMAGERENDERING" in str(crop_path):
            page_num = "none"
        else:
            # layout_ 파일에서 페이지 번호 추출
            page_num = extract_page_num(os.path.basename(original_json_path))
            if page_num is None:
                page_num = "none"
    
    # 페이지 번호가 none이면 0으로 대체
    display_page_num = "0" if page_num == "none" else page_num
    
    # OCR 결과 파일 경로 생성
    ocr_result_path = OCR_RESULTS_DIR / f"{pdf_folder_name}.md"
    
    # OCR 텍스트 추출
    ocr_text = None
    if page_num != "none":
        ocr_text = extract_ocr_text_for_page(ocr_result_path, page_num)
        if ocr_text:
            logger.info(f"페이지 {page_num}에 대한 OCR 텍스트 추출 성공")
        else:
            logger.warning(f"페이지 {page_num}에 대한 OCR 텍스트 추출 실패")
    
    # ID 생성
    id_value = f"{page_num}_{label}" if page_num != "none" else f"none_{label}"
    
    # 푸터 레이블 찾기 (인덱스)
    index_value = None
    # IMAGERENDERING 폴더인 경우 인덱스는 항상 None
    if "IMAGERENDERING" not in str(crop_path):
        for box_data in boxes_data:
            if box_data.get("label") == "footer":
                # JSON에서 텍스트 가져오기
                if "text" in box_data:
                    index_value = box_data.get("text") or None
                else:
                    index_value = None
                break
    
    # figure_title 찾기 (서브타이틀)
    subtitle = None
    closest_title_box = None
    # IMAGERENDERING 폴더인 경우 서브타이틀은 항상 None
    if "IMAGERENDERING" not in str(crop_path):
        min_distance = MAX_TITLE_DISTANCE
        for box_data in boxes_data:
            if box_data.get("label") == "figure_title":
                title_coords = box_data.get("coordinate")
                if title_coords and len(title_coords) == 4:
                    distance = calculate_distance(box_coords, title_coords)
                    if distance <= min_distance:
                        closest_title_box = box_data
                        min_distance = distance
        
        # 가장 가까운 figure_title의 텍스트 가져오기
        if closest_title_box:
            if "text" in closest_title_box:
                subtitle = closest_title_box.get("text") or None
            else:
                subtitle = None
    
    # 파일 이름 생성 (폴더이름_페이지번호_순서번호)
    # 순서번호는 2자리수로 표시 (01, 02, ...)
    file_name = f"{pdf_folder_name}_{display_page_num}_{index_num:02d}"
    
    # 파일 경로를 상대 경로로 변환 (/backend/data_pipeline/... 형식)
    # BASE_DIR (backend/ 디렉토리)를 기준으로 상대 경로 계산
    try:
        relative_crop_path = f"/backend/{crop_path.relative_to(BASE_DIR)}"
    except Exception:
        # relative_to가 실패할 경우 (예: 다른 드라이브) 기본 str 사용
        relative_crop_path = str(crop_path)

    # 메타데이터 생성
    metadata = {
        "metadata": {
            "created_at": CURRENT_DATE,
            "modified_at": CURRENT_DATE,
            "title": pdf_folder_name,
            "page_num": page_num,
            "index": str(number) if number is not None else index_value,
            "id": id_value,
            "file_name": file_name,
            "file_path": relative_crop_path,
            "text": ocr_text,
            "tags": None,
            "con_type": label,
            "subtitle": subtitle,
            "caption": None,
            "box_coords": box_coords  # 바운딩 박스 좌표 추가
        }
    }
    
    return metadata

def ensure_dir(directory):
    """디렉토리가 존재하지 않으면 생성"""
    Path(directory).mkdir(parents=True, exist_ok=True)

def crop_image(image_path, box, output_path, padding=PADDING, number=None):
    """이미지에서 바운딩 박스 영역을 크롭하여 저장
    
    Args:
        image_path: 원본 이미지 경로
        box: [x1, y1, x2, y2] 형식의 바운딩 박스 좌표
        output_path: 크롭된 이미지를 저장할 경로
        padding: 바운딩 박스 주변에 추가할 패딩 픽셀 수
        number: 메타데이터에 추가할 번호
    """
    try:
        # 이미지 로드
        img = Image.open(image_path)
        
        # 바운딩 박스 좌표에 패딩 추가
        x1, y1, x2, y2 = box
        x1 = max(0, x1 - padding)
        y1 = max(0, y1 - padding)
        x2 = min(img.width, x2 + padding)
        y2 = min(img.height, y2 + padding)
        
        # 이미지 크롭
        cropped_img = img.crop((x1, y1, x2, y2))
        
        # 출력 디렉토리 생성
        ensure_dir(os.path.dirname(output_path))
        
        # 크롭된 이미지 저장
        cropped_img.save(output_path)
        return cropped_img
    except Exception as e:
        logger.error(f"이미지 크롭 중 오류 발생: {e} - {image_path}")
        return False

def process_json_file(json_path, pdf_folder_name, file_type="PDF", skip_existing=True, add_numbering=True, number_counter=1):
    """JSON 파일을 처리하여 해당하는 이미지에서 객체를 크롭
    
    Args:
        json_path: 레이아웃 JSON 파일 경로
        pdf_folder_name: PDF 폴더 이름
        file_type: 파일 타입 (PDF 또는 IMG)
        skip_existing: 이미 처리된 파일을 건너뛸지 여부
        add_numbering: 메타데이터에 넘버링을 추가할지 여부
        number_counter: 넘버링 시작 번호
    
    Returns:
        다음 넘버링 시작 번호
    """
    try:
        # 이미 처리된 파일인지 확인
        output_check_path = OUTPUT_DIR / file_type / pdf_folder_name
        
        # JSON 파일 로드
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 박스 데이터 가져오기
            boxes_data = data.get('boxes', [])
            
            # 레이블별 이미지 수 확인
            label_counts = {label: 0 for label in TARGET_LABELS}
            for box in boxes_data:
                label = box.get('label')
                if label in TARGET_LABELS:
                    label_counts[label] += 1
            
            # 현재 JSON의 페이지 번호/파일명 접두어 계산
            json_filename = os.path.basename(json_path)
            raw_page_num = extract_page_num(json_filename)
            page_num = raw_page_num if raw_page_num is not None else "none"
            display_page_num = "0" if page_num == "none" else page_num
            page_prefix = f"{pdf_folder_name}_{display_page_num}_"
            
            # 출력 폴더가 존재하고 skip_existing이 True인 경우, 그리고 처리할 레이블이 하나 이상 있는 경우에만 건너뛰기 로직 실행
            if skip_existing and output_check_path.exists() and any(label_counts.values()):
                all_processed = True
                
                # 각 레이블별로 처리된 이미지 수 확인 (현재 페이지 기준)
                for label in TARGET_LABELS:
                    expected_count = label_counts[label]
                    if expected_count == 0:
                        continue
                    
                    label_folder = output_check_path / label
                    if not label_folder.exists():
                        all_processed = False
                        break
                    
                    processed_count = len([
                        file_path for file_path in label_folder.glob('*_metadata.json')
                        if file_path.name.startswith(page_prefix)
                    ])
                    
                    if processed_count < expected_count:
                        all_processed = False
                        break
                
                if all_processed:
                    # 이미 모든 레이블이 처리된 경우
                    processed_files.add(json_path)
                    logger.info(f"이미 처리된 파일 건너뛴: {json_path}")
                    return number_counter
        except Exception as e:
            logger.error(f"JSON 파일 처리 중 오류 발생: {e} - {json_path}")
            return number_counter
            
        # 이미 처리된 파일인지 확인 (processed_files 세트에 있는 경우)
        if json_path in processed_files:
            logger.info(f"이미 처리된 파일 건너뛴: {json_path}")
            return number_counter
        
        # JSON 파일 로드
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 입력 이미지 경로 확인
        layout_img_path = str(json_path).rsplit('.', 1)[0] + '.png'
        
        # 레이아웃 이미지가 존재하는지 확인
        if not os.path.exists(layout_img_path):
            logger.warning(f"레이아웃 이미지를 찾을 수 없음: {layout_img_path}")
            return number_counter
        
        # 원본 이미지 경로 (JSON에서 가져옴)
        original_img_path = data.get('input_path')
        
        # 원본 이미지가 없는 경우 레이아웃 이미지 사용
        img_path = original_img_path if os.path.exists(original_img_path) else layout_img_path
        
        # 페이지 번호 정보는 위에서 계산됨
        
        # 모든 박스 데이터 가져오기 (메타데이터 생성에 사용)
        boxes_data = data.get('boxes', [])
        
        # 서브타이틀별 카운터 생성 (같은 페이지에서 같은 서브타이틀을 가진 객체의 순서 관리)
        subtitle_counters = {}
        
        # 바운딩 박스 처리
        for i, box_data in enumerate(boxes_data):
            label = box_data.get('label')
            
            # 대상 레이블만 처리
            if label not in TARGET_LABELS:
                continue
                
            # 최소 크기 확인
            min_width, min_height = MIN_BOX_SIZE.get(label, (0, 0))
            width, height = get_bbox_size(box_data['coordinate'])
            
            # 너비와 높이 모두 최소 기준보다 작은 경우에만 건너뜀 (둘 중 하나라도 기준을 만족하면 유지)
            if width < min_width and height < min_height:
                logger.debug(f"최소 크기보다 작은 바운딩 박스 건너뜀: {width}x{height} < {min_width}x{min_height}")
                continue
                
            # 최대 크기 확인
            max_width, max_height = MAX_BOX_SIZE.get(label, (float('inf'), float('inf')))
            if width > max_width or height > max_height:
                logger.debug(f"최대 크기보다 큰 바운딩 박스 건너뜀: {width}x{height} > {max_width}x{max_height}")
                continue
            
            # 해당 객체의 서브타이틀 찾기 (메타데이터 생성을 위해 미리 확인)
            subtitle = "none"
            if "IMAGERENDERING" not in str(json_path):
                min_distance = MAX_TITLE_DISTANCE
                for other_box in boxes_data:
                    if other_box.get("label") == "figure_title":
                        title_coords = other_box.get("coordinate")
                        if title_coords and len(title_coords) == 4:
                            distance = calculate_distance(box_data['coordinate'], title_coords)
                            if distance <= min_distance:
                                subtitle = "figure_title_found"  # 실제로는 텍스트 내용을 가져와야 하지만, 예제로 표시
                                min_distance = distance
            
            # 서브타이틀별 카운터 증가
            subtitle_str = subtitle if subtitle is not None else "none"
            subtitle_key = f"{page_num}_{subtitle_str}_{label}"
            if subtitle_key not in subtitle_counters:
                subtitle_counters[subtitle_key] = 1
            else:
                subtitle_counters[subtitle_key] += 1
            
            # 현재 객체의 순서 번호
            index_num = subtitle_counters[subtitle_key]
            
            # 메타데이터 생성
            metadata = create_metadata(
                crop_path=None,  # 나중에 업데이트
                original_json_path=json_path,
                pdf_folder_name=pdf_folder_name,
                label=label,
                box_coords=box_data['coordinate'],
                boxes_data=boxes_data,
                page_num=page_num,
                index_num=index_num,
                number=number_counter
            )
            
            # 파일 이름 가져오기
            file_name = metadata["metadata"]["file_name"]
            
            # 출력 경로 생성
            output_folder = OUTPUT_DIR / file_type / pdf_folder_name / label
            output_path = output_folder / f"{file_name}.png"
            
            # 이미지 크롭 및 저장
            cropped_img = crop_image(img_path, box_data['coordinate'], output_path, number=number_counter)
            if cropped_img:
                logger.info(f"크롭 완료: {label} - {output_path}")
                
                # 넘버링 카운터 증가 (성공적으로 크롭된 경우에만)
                number_counter += 1
                
                # 메타데이터 경로 업데이트 (상대 경로로 유지)
                try:
                    relative_output_path = f"/backend/{output_path.relative_to(BASE_DIR)}"
                except Exception:
                    relative_output_path = str(output_path)
                
                metadata["metadata"]["file_path"] = relative_output_path
                
                # 캡션과 태그는 사용하지 않음
                caption, tags = None, None
                
                # 메타데이터에 설명과 태그 추가
                if caption:
                    metadata["metadata"]["caption"] = caption
                if tags:
                    metadata["metadata"]["tags"] = tags
                    
                logger.info("이미지 메타데이터 생성 완료")
                
                # 메타데이터 JSON 파일 저장
                metadata_path = str(output_path).rsplit('.', 1)[0] + '_metadata.json'
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=4)
                    
                logger.info(f"메타데이터 저장 완료: {metadata_path}")
        
        # 처리 완료된 파일 기록
        processed_files.add(json_path)
        
    except Exception as e:
        logger.error(f"JSON 파일 처리 중 오류 발생: {e} - {json_path}")
    
    return number_counter

def process_layout_detection_results(input_dir, output_dir, skip_existing=True, resume=True, add_numbering=True):
    """레이아웃 감지 결과 디렉토리 처리
    
    Args:
        skip_existing: 이미 처리된 파일을 건너뛸지 여부
        resume: 마지막으로 처리된 파일부터 이어서 처리할지 여부
        add_numbering: 메타데이터에 넘버링을 추가할지 여부
    """
    # 출력 디렉토리 생성
    ensure_dir(output_dir)
    ensure_dir(output_dir / "PDF")
    ensure_dir(output_dir / "IMG")
    
    # 처리된 폴더 수와 파일 수 카운트
    processed_folders = 0
    processed_jsons = 0
    
    # 넘버링 카운터 초기화
    number_counter = 1
    
    # PDF와 IMG 폴더 처리
    for top_dir in input_dir.iterdir():
        if not top_dir.is_dir():
            continue
            
        # PDF 또는 IMG 폴더 확인
        top_dir_name = top_dir.name
        file_type = "PDF" if top_dir_name == "PDF" else "IMG"
        
        logger.info(f"{file_type} 폴더 처리 중: {top_dir_name}")
        
        # 각 파일 폴더 처리
        for pdf_folder in top_dir.iterdir():
            if not pdf_folder.is_dir():
                continue
            
            pdf_folder_name = pdf_folder.name
            logger.info(f"파일 처리 중: {pdf_folder_name}")
            
            # 모든 JSON 파일 처리
            json_files = list(pdf_folder.glob("layout_*.json"))
            
            if not json_files:
                logger.warning(f"JSON 파일을 찾을 수 없음: {pdf_folder}")
                continue
            
            # JSON 파일 정렬 (이름순)
            json_files.sort()
            
            # 이어하기 기능을 위한 시작 인덱스 계산
            global last_processed_file
            start_idx = 0
            if resume and last_processed_file:
                try:
                    start_idx = json_files.index(Path(last_processed_file)) + 1
                    logger.info(f"마지막으로 처리된 파일: {last_processed_file}")
                    logger.info(f"이어서 처리를 시작합니다. ({start_idx}/{len(json_files)})")
                except ValueError:
                    # 마지막으로 처리된 파일이 현재 폴더에 없는 경우
                    start_idx = 0
            
            # 각 JSON 파일 처리
            for idx, json_path in enumerate(json_files[start_idx:], start=start_idx+1):
                try:
                    # 넘버링 카운터 업데이트
                    result = process_json_file(json_path, pdf_folder_name, file_type, skip_existing, add_numbering, number_counter)
                    if result is not None:
                        number_counter = result
                    processed_jsons += 1
                    
                    # 마지막으로 처리된 파일 업데이트
                    last_processed_file = str(json_path)
                except Exception as e:
                    logger.error(f"'{str(json_path)}' 파일 처리 중 심각한 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                    logger.info("오류가 발생한 파일을 건너뛰고 다음 파일을 계속 처리합니다.")
                    continue
            
            processed_folders += 1
    
    logger.info(f"처리 완료: {processed_folders}개 폴더, {processed_jsons}개 JSON 파일")
    logger.info(f"크롭된 이미지가 저장된 경로: {output_dir}")
    if number_counter is not None and number_counter > 1:
        logger.info(f"총 {number_counter - 1}개의 이미지/차트에 메타데이터 넘버링을 추가했습니다.")
    else:
        logger.info("새로 처리된 이미지/차트가 없습니다.")

if __name__ == "__main__":
    # 명령행 인자 파싱
    parser = argparse.ArgumentParser(description="레이아웃 감지 결과에서 이미지 크롭")
    parser.add_argument("--input_dir", type=str, default=INPUT_DIR, help="레이아웃 결과 파일들이 있는 디렉토리")
    parser.add_argument("--output_dir", type=str, default=OUTPUT_DIR, help="크롭한 이미지 저장할 디렉토리")
    # '--skip_existing'의 기본값을 True로 설정하고, '--no_skip_existing'로 비활성화할 수 있도록 재구성
    parser.add_argument("--skip_existing", action="store_true", default=True, help="이미 처리된 파일 건너뛰기 (기본값: True)")
    parser.add_argument("--no_skip_existing", dest="skip_existing", action="store_false", help="이미 처리된 파일도 다시 처리")
    parser.add_argument("--resume", action="store_true", default=True, help="마지막으로 처리된 파일부터 이어서 처리 (기본값: True)")
    parser.add_argument("--no_resume", dest="resume", action="store_false", help="처음부터 다시 처리")
    parser.add_argument("--add_numbering", action="store_true", default=True, help="메타데이터에 넘버링 추가 (기본값: True)")
    parser.add_argument("--no_add_numbering", dest="add_numbering", action="store_false", help="메타데이터에 넘버링 추가하지 않음")
    parser.add_argument("--min_width", type=int, default=200, help="최소 바운딩 박스 너비 (기본값: 200)")
    parser.add_argument("--min_height", type=int, default=200, help="최소 바운딩 박스 높이 (기본값: 200)")
    parser.add_argument("--max_width", type=int, default=800, help="최대 바운딩 박스 너비 (기본값: 800)")
    parser.add_argument("--max_height", type=int, default=850, help="최대 바운딩 박스 높이 (기본값: 850)")
    args = parser.parse_args()
    
    logger.info("레이아웃 감지 결과에서 이미지 크롭 시작")
    logger.info(f"옵션: skip_existing={args.skip_existing}, resume={args.resume}, add_numbering={args.add_numbering} (메타데이터에 번호 추가)")
    logger.info(f"필터링 옵션: min_width={args.min_width}, min_height={args.min_height}, max_width={args.max_width}, max_height={args.max_height}")
    
    # 명령행 인자로 받은 값으로 MIN_BOX_SIZE와 MAX_BOX_SIZE 업데이트
    for label in TARGET_LABELS:
        MIN_BOX_SIZE[label] = (args.min_width, args.min_height)
        MAX_BOX_SIZE[label] = (args.max_width, args.max_height)
    
    # 경로 문자열을 Path 객체로 변환
    input_path = Path(args.input_dir)
    output_path = Path(args.output_dir)

    process_layout_detection_results(input_dir=input_path, output_dir=output_path, skip_existing=args.skip_existing, resume=args.resume, add_numbering=args.add_numbering)
    
    logger.info("이미지 크롭 완료")
