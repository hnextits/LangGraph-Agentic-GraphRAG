#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import re
import copy
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.font_manager import FontProperties
import numpy as np
from PIL import Image

import os
import re
import json
import copy
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.font_manager import FontProperties

def identify_text_blocks(boxes, title_labels=None, content_labels=None, special_label_pairs=None):
    """
    텍스트 박스들을 블록으로 그룹화하는 함수
    
    Args:
        boxes (list): 텍스트 박스 목록
        title_labels (list, optional): 제목으로 간주할 레이블 목록 (기본값: ['paragraph_title'])
        content_labels (list, optional): 내용으로 간주할 레이블 목록 (기본값: ['text'])
        special_label_pairs (list, optional): 같은 블록으로 처리할 특별한 레이블 쌍 목록 (기본값: [('paragraph_title', 'text')])
        
    Returns:
        list: 블록 ID가 할당된 텍스트 박스 목록
    """
    # 기본값 설정
    if title_labels is None:
        title_labels = ['paragraph_title','doc_title']
    if content_labels is None:
        content_labels = ['text','content','reference','reference_content','aside_text']
    if special_label_pairs is None:
        special_label_pairs = [('paragraph_title', 'text')]
    # 텍스트 박스들을 복사
    boxes_with_blocks = copy.deepcopy(boxes)
    
    # x 좌표 유사성 임계값 (100픽셀)
    x_similarity_threshold = 100
    
    # y 좌표 유사성 임계값
    y_similarity_threshold = 250
    
    # 이전 박스와 현재 박스 간의 수직 거리 임계값
    threshold = 50
    
    # 1단계: x 좌표 유사성에 따라 텍스트를 그룹화
    x_groups = []
    
    for box in boxes_with_blocks:
        x0 = box['coordinate'][0]  # 왼쪽 x 좌표
        
        # 기존 그룹에 속하는지 확인
        found_group = False
        for group in x_groups:
            # 그룹의 첫 번째 박스의 x0 좌표와 비교
            group_x0 = group[0]['coordinate'][0]
            if abs(x0 - group_x0) < x_similarity_threshold:
                group.append(box)
                found_group = True
                break
        
        # 어떤 그룹에도 속하지 않으면 새 그룹 생성
        if not found_group:
            x_groups.append([box])
    
    # 2단계: 각 x 그룹 내에서 y 좌표에 따라 정렬
    for group in x_groups:
        group.sort(key=lambda box: box['coordinate'][1])  # y0 좌표로 정렬
    
    # 3단계: 각 x 그룹 내에서 y 좌표 유사성 및 기타 조건에 따라 블록 할당
    current_block_id = 0
    processed_boxes = {}  # 처리된 박스를 추적하기 위한 딕셔너리
    
    for group in x_groups:
        group_block_id = current_block_id
        
        # 그룹의 첫 번째 박스에 블록 ID 할당
        group[0]['block_id'] = group_block_id
        processed_boxes[id(group[0])] = True
        
        # 그룹 내 두 번째 박스부터 블록 ID 할당
        for i in range(1, len(group)):
            curr_box = group[i]
            prev_box = group[i-1]
            
            # 이전 박스와 현재 박스 간의 수직 거리 계산
            prev_box_bottom = prev_box['coordinate'][3]  # 이전 박스의 하단 y 좌표
            curr_box_top = curr_box['coordinate'][1]     # 현재 박스의 상단 y 좌표
            distance = curr_box_top - prev_box_bottom
            
            # y 좌표 유사성 확인
            y_start_similar = abs(curr_box['coordinate'][1] - prev_box['coordinate'][1]) < y_similarity_threshold
            
            is_new_block = False
            
            # y 좌표가 유사하지 않고 수직 거리가 임계값보다 크면 새 블록
            if distance > threshold and not y_start_similar:
                is_new_block = True
            # 레이블이 다르면 새 블록 시작 (단, 특별한 레이블 쌍은 예외 처리)
            elif curr_box.get('label') != prev_box.get('label'):
                # 특별한 레이블 쌍 확인 (예: paragraph_title 다음의 text는 같은 블록으로 처리)
                is_special_pair = False
                for title_label, content_label in special_label_pairs:
                    if prev_box.get('label') == title_label and curr_box.get('label') == content_label:
                        is_special_pair = True
                        break
                
                if not is_special_pair and not y_start_similar:  # 특별한 쌍이 아니고 y 좌표가 유사하지 않으면 새 블록
                    is_new_block = True
            
            # 텍스트 내용 분석 (번호 매기기 패턴 감지)
            curr_text = curr_box.get('text', '')
            if re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]|^\([0-9]+\)|^[0-9]+\.|^[0-9]+\)', curr_text):
                # 번호로 시작하는 텍스트는 새 블록으로 간주 (단, y 좌표가 유사하면 같은 블록으로 처리)
                if not y_start_similar:
                    is_new_block = True
            
            # 새 블록 할당
            if is_new_block:
                group_block_id += 1
                current_block_id += 1
            
            curr_box['block_id'] = group_block_id
            processed_boxes[id(curr_box)] = True
        
        current_block_id += 1
    
    # 4단계: 처리되지 않은 박스가 있는지 확인하고 처리
    result_boxes = []
    for box in boxes_with_blocks:
        if id(box) not in processed_boxes:
            box['block_id'] = current_block_id
            current_block_id += 1
        result_boxes.append(box)
    
    # 원래 순서대로 정렬
    # 주의: boxes.index(box)는 처리된 박스가 원본 목록에 없을 수 있음
    # 원래 순서를 유지하기 위해 인덱스 매핑을 사용
    # 원본 박스와 처리된 박스 간의 매핑 생성
    # 정렬을 생략하고 원래 순서를 유지
    
    return result_boxes


def sort_text_boxes_hybrid(boxes, title_labels=None, content_labels=None, special_label_pairs=None):
    """
    텍스트 박스를 y 좌표와 x 좌표를 고려하여 정렬하는 함수
    
    Args:
        boxes (list): 정렬할 텍스트 박스 목록
        title_labels (list, optional): 제목으로 간주할 레이블 목록
        content_labels (list, optional): 내용으로 간주할 레이블 목록
        special_label_pairs (list, optional): 같은 블록으로 처리할 특별한 레이블 쌍 목록
        
    Returns:
        list: 정렬된 텍스트 박스 목록
    """
    # 1. y 좌표로 대략적인 정렬
    y_sorted_boxes = sorted(boxes, key=lambda box: box['coordinate'][1])
    
    # 2. 블록 ID 할당
    boxes_with_blocks = identify_text_blocks(y_sorted_boxes, title_labels=title_labels, 
                                          content_labels=content_labels, special_label_pairs=special_label_pairs)
    
    # 3. 블록 ID와 y 좌표로 최종 정렬
    sorted_boxes = sorted(boxes_with_blocks, key=lambda box: (box['block_id'], box['coordinate'][1]))
    
    return sorted_boxes


def process_layout_json(input_path, output_dir=None, include_labels=None, exclude_labels=None, 
                   title_labels=None, content_labels=None, special_label_pairs=None):
    """
    레이아웃 JSON 파일을 처리하여 텍스트를 정렬하고 시각화하는 함수
    
    Args:
        input_path (str): 입력 JSON 파일 경로
        output_dir (str, optional): 출력 디렉토리 경로
        include_labels (list, optional): 포함할 레이블 목록 (None이면 모든 레이블 포함)
        exclude_labels (list, optional): 제외할 레이블 목록 (None이면 제외하지 않음)
        title_labels (list, optional): 제목으로 간주할 레이블 목록 (기본값: ['paragraph_title'])
        content_labels (list, optional): 내용으로 간주할 레이블 목록 (기본값: ['text'])
        special_label_pairs (list, optional): 같은 블록으로 처리할 특별한 레이블 쌍 목록 (기본값: [('paragraph_title', 'text')])
        
    Returns:
        list: 정렬된 텍스트 목록
    """
    # 입력 파일 읽기
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 원본 이미지 경로 추출
    image_path = input_path.replace('.json', '.png')
    if not os.path.exists(image_path):
        print(f"경고: 원본 이미지를 찾을 수 없습니다: {image_path}")
    else:
        print(f"원본 이미지 경로: {image_path}")
    
    # 원본 이미지 경로 추가
    data['image_path'] = image_path
    
    # 기본값 설정
    if include_labels is None:
        # 기본적으로 'text', 'paragraph_title', 'footer' 레이블 포함
        include_labels = ['text', 'paragraph_title', 'footer', 'content', 'reference', 'doc_title', 'aside_text', 'reference_content']
    if exclude_labels is None:
        exclude_labels = []
    
    # 텍스트 박스 추출
    text_boxes = []
    # JSON 구조 확인 (shapes 또는 boxes 키 사용)
    if 'shapes' in data:
        for item in data['shapes']:
            # 레이블 필터링 로직
            label = item['label']
            # 1. include_labels가 비어있지 않으면 해당 목록에 있는 레이블만 포함
            # 2. exclude_labels에 있는 레이블은 제외
            if (not include_labels or label in include_labels) and label not in exclude_labels:
                text_boxes.append({
                    'label': label,
                    'text': item.get('text', ''),
                    'coordinate': item['points'].copy()
                })
    elif 'boxes' in data:
        for item in data['boxes']:
            # 레이블 필터링 로직
            label = item['label']
            # 1. include_labels가 비어있지 않으면 해당 목록에 있는 레이블만 포함
            # 2. exclude_labels에 있는 레이블은 제외
            if (not include_labels or label in include_labels) and label not in exclude_labels:
                text_boxes.append({
                    'label': label,
                    'text': item.get('text', ''),
                    'coordinate': item['coordinate']
                })
    else:
        print(f"경고: JSON 파일 '{input_path}'에 'shapes' 또는 'boxes' 키가 없습니다.")
        return []
    
    # 텍스트 박스 정렬
    sorted_texts = sort_text_boxes_hybrid(
        text_boxes,
        title_labels=title_labels if 'title_labels' in locals() else None,
        content_labels=content_labels if 'content_labels' in locals() else None,
        special_label_pairs=special_label_pairs if 'special_label_pairs' in locals() else None
    )
    
    # 출력 디렉토리 설정
    if output_dir is None:
        # 기본 출력 디렉토리 설정
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(input_path)))
        file_name = os.path.basename(input_path).split('.')[0]
        
        # 원본 폴더명 추출 (PDF 파일명)
        parts = input_path.split('/')
        pdf_name_idx = parts.index('1.Converted_images') + 2 if '1.Converted_images' in parts else -1
        pdf_folder = parts[pdf_name_idx] if pdf_name_idx != -1 and pdf_name_idx < len(parts) else 'unknown'
        
        output_dir = os.path.join(base_dir, 'Results', '4.Pipeline_results', 'text', 'PDF', pdf_folder)
    
    # 출력 디렉토리가 없으면 생성
    os.makedirs(output_dir, exist_ok=True)
    
    # 정렬된 텍스트 저장
    output_json = {
        'input_path': input_path,
        'page_index': data.get('page_index'),
        'sorted_texts': sorted_texts
    }
    
    output_json_path = os.path.join(output_dir, f"{os.path.basename(input_path).split('.')[0]}_sorted.json")
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(output_json, f, ensure_ascii=False, indent=4)
    
    print(f'정렬된 텍스트가 {output_json_path}에 저장되었습니다.')
    
    # 메타데이터 JSON 파일 생성
    # 파일명과 페이지 번호 추출
    file_name = os.path.basename(input_path).split('.')[0]
    
    # PDF 폴더명 추출
    parts = input_path.split('/')
    pdf_folder_name = 'unknown'
    
    # 출력 디렉토리에서 폴더명 추출 (가장 정확한 방법)
    if output_dir:
        output_parts = output_dir.split('/')
        if 'PDF' in output_parts:
            pdf_idx = output_parts.index('PDF')
            if pdf_idx + 1 < len(output_parts):
                pdf_folder_name = output_parts[pdf_idx + 1]
    
    # 출력 디렉토리에서 추출 실패한 경우 입력 경로에서 추출 시도
    if pdf_folder_name == 'unknown':
        # 다양한 가능한 경로 패턴 처리
        for folder_pattern in ['1.Converted_images', '2.Layout_detection', '3.Crop_image', '4.Pipeline_results']:
            if folder_pattern in parts:
                try:
                    pdf_idx = parts.index(folder_pattern)
                    # PDF 폴더는 일반적으로 패턴 폴더 + 2 위치에 있음 (예: .../3.Crop_image/PDF/폴더명/...)
                    if pdf_idx + 2 < len(parts) and parts[pdf_idx + 1] == 'PDF':
                        pdf_folder_name = parts[pdf_idx + 2]
                        break
                except (ValueError, IndexError):
                    continue
    
    # 페이지 번호 추출
    page_num = '000'
    page_match = re.search(r'_([0-9]{3})_?', file_name)
    if page_match:
        page_num = page_match.group(1)
    
    # footer 레이블 찾기
    footer_text = None
    
    # 1. 정렬된 텍스트에서 footer 찾기
    for item in sorted_texts:
        if item.get('label') == 'footer':
            footer_text = item.get('text')
            break
            
    # 2. 정렬된 텍스트에서 찾지 못한 경우 원본 데이터에서 찾기
    if footer_text is None:
        # JSON 구조 확인 (shapes 또는 boxes 키 사용)
        if 'shapes' in data:
            for item in data['shapes']:
                if item.get('label') == 'footer':
                    footer_text = item.get('text', '')
                    print(f"원본 데이터에서 footer 텍스트를 찾았습니다: {footer_text}")
                    break
        elif 'boxes' in data:
            for item in data['boxes']:
                if item.get('label') == 'footer':
                    footer_text = item.get('text', '')
                    print(f"원본 데이터에서 footer 텍스트를 찾았습니다: {footer_text}")
                    break
    
    # 현재 날짜 가져오기
    from datetime import datetime
    current_date = datetime.now().strftime("%Y.%m.%d")
    
    # 이미지 경로 추출
    image_path = data.get('image_path', '')
    
    # 이미지 경로가 없으면 입력 경로에서 추출
    if not image_path:
        # 입력 경로가 JSON이면 동일한 디렉토리에 PNG 파일이 있을 가능성이 높음
        input_dir = os.path.dirname(input_path)
        base_name = os.path.basename(input_path).split('.')[0]
        possible_image_path = os.path.join(input_dir, f"{base_name}.png")
        
        if os.path.exists(possible_image_path):
            image_path = possible_image_path
    
    # 메타데이터 생성
    metadata = {
        "metadata": {
            "created_at": current_date,
            "modified_at": current_date,
            "title": pdf_folder_name,
            "page_num": page_num,
            "index": footer_text,
            "id": f"{page_num}_text",
            "file_name": file_name,
            "file_path": image_path,
            "text": None,
            "tags": None,
            "con_type": 'text',
            "subtitle": None,
            "caption": None
        }
    }
    
    # 메타데이터 파일 저장 (파일명_페이지no_01_metadata.json 형식으로)
    # 파일명에서 페이지 번호 부분을 추출하여 사용
    base_name_without_page = re.sub(r'_[0-9]{3}(?:_[0-9]+)?$', '', file_name)
    metadata_json_path = os.path.join(output_dir, f"{base_name_without_page}_{page_num}_01_metadata.json")
    with open(metadata_json_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=4)
    
    print(f'메타데이터가 {metadata_json_path}에 저장되었습니다.')
    
    # 시각화 이미지 생성
    visualize_sorted_texts(data, sorted_texts, os.path.join(output_dir, f"{os.path.basename(input_path).split('.')[0]}_visualization.png"))
    
    return sorted_texts


def visualize_sorted_texts(data, sorted_texts, output_path):
    """
    정렬된 텍스트를 시각화하는 함수
    
    Args:
        data (dict): 원본 레이아웃 데이터
        sorted_texts (list): 정렬된 텍스트 목록
        output_path (str): 출력 이미지 파일 경로
    """
    # 원본 이미지 경로 가져오기
    image_path = data.get('image_path', '')
    
    # 원본 이미지가 없으면 빈 캔버스 생성
    if not image_path or not os.path.exists(image_path):
        # 이미지 크기 설정
        width = data.get('imageWidth', 1000)
        height = data.get('imageHeight', 1000)
        
        # 그림 생성
        fig, ax = plt.subplots(figsize=(width/100, height/100))
        ax.set_xlim(0, width)
        ax.set_ylim(height, 0)  # y축 반전
        print(f"경고: 원본 이미지를 찾을 수 없습니다: {image_path}")
    else:
        # 원본 이미지 로드
        img = Image.open(image_path)
        width, height = img.size
        
        # 그림 생성
        fig, ax = plt.subplots(figsize=(width/100, height/100))
        ax.imshow(np.array(img))
        ax.set_xlim(0, width)
        ax.set_ylim(height, 0)  # y축 반전
    
    # 블록별 색상 설정
    block_colors = plt.cm.tab20(range(20))
    
    # 텍스트 박스 그리기
    for i, item in enumerate(sorted_texts):
        x0, y0, x1, y1 = item['coordinate']
        block_id = item.get('block_id', 0)
        color = block_colors[block_id % 20]
        
        # 박스 그리기
        rect = patches.Rectangle((x0, y0), x1-x0, y1-y0, linewidth=1, edgecolor=color, facecolor='none')
        ax.add_patch(rect)
        
        # 텍스트 번호 표시
        ax.text(x0, y0-5, str(i+1), fontsize=8, color='black', bbox=dict(facecolor='white', alpha=0.7))
        
        # 블록 ID 표시
        ax.text(x0+5, y0+5, f"B{block_id}", fontsize=6, color='red', bbox=dict(facecolor='white', alpha=0.7))
    
    # 이미지 저장
    plt.axis('off')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f'시각화 이미지가 {output_path}에 저장되었습니다.')


def print_sorted_texts(sorted_texts):
    """
    정렬된 텍스트를 블록 ID와 함께 출력하는 함수
    
    Args:
        sorted_texts (list): 정렬된 텍스트 목록
    """
    print("\n=== 정렬된 텍스트 출력 ===")
    
    # 블록별로 구분하여 출력
    current_block = -1
    for i, item in enumerate(sorted_texts):
        block_id = item.get('block_id', -1)
        
        # 블록이 변경되면 구분선 출력
        if block_id != current_block:
            if i > 0:
                print("----------------------------")
            print(f"\n[Block {block_id}]")
            current_block = block_id
            
        print(f"[{i+1}] [{item['label']}] {item['text']}")
    print("=== 정렬된 텍스트 끝 ===")
