import os
import base64
import re
import glob
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import logging

# 로깅 설정
logger = logging.getLogger(__name__)

# 이미지 기본 경로 설정 (serch_gui 프로젝트에 맞게 조정)
IMAGE_BASE_PATHS = [
    './nextits_data/Results/5.Completion_results/image',
    './nextits_data/Results',
    './nextits_data',
    './backend',
    './frontend/public/images',
    './images'
]

def find_image_file(image_path: str) -> Optional[str]:
    """이미지 파일의 실제 경로 찾기
    
    여러 기본 디렉토리에서 이미지 파일을 찾아 실제 경로 반환
    
    Args:
        image_path: 찾을 이미지 파일 경로 (상대 또는 절대 경로)
        
    Returns:
        이미지 파일의 실제 절대 경로 또는 None (찾지 못한 경우)
    """
    # 경로가 비어있거나 'None' 문자열인 경우 None 반환
    if not image_path or image_path == 'None':
        logger.warning("이미지 경로가 비어 있거나 'None'입니다.")
        return None
    
    # 절대 경로인 경우 바로 확인
    if os.path.isabs(image_path) and os.path.exists(image_path) and os.path.isfile(image_path):
        logger.info(f"절대 경로에서 이미지 발견: {image_path}")
        return image_path
    
    # 파일명만 추출
    filename = os.path.basename(image_path)
    logger.info(f"추출된 파일명: {filename}")
    
    # 메타데이터에서 이미지 경로 찾기 시도
    metadata_paths = [
        './nextits_data/Results/5.Completion_results/image_metadata.json',
        './nextits_data/image_metadata.json'
    ]
    
    for metadata_path in metadata_paths:
        if os.path.exists(metadata_path):
            try:
                import json
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                # 파일명 추출
                filename_no_ext = os.path.splitext(filename)[0]
                
                logger.info(f"메타데이터에서 이미지 검색: {filename} / {filename_no_ext}")
                
                # 메타데이터에서 파일명 또는 경로로 검색
                for item in metadata:
                    meta_filename = os.path.basename(item.get('file_path', ''))
                    meta_filename_no_ext = os.path.splitext(meta_filename)[0]
                    
                    # 파일명 또는 경로가 일치하는 경우
                    if (meta_filename == filename or 
                        meta_filename_no_ext == filename_no_ext or 
                        item.get('file_path') == image_path):
                        
                        real_path = item.get('file_path')
                        logger.info(f"메타데이터에서 이미지 경로 찾음: {real_path}")
                        
                        # 찾은 경로가 존재하는지 확인
                        if os.path.exists(real_path) and os.path.isfile(real_path):
                            logger.info(f"메타데이터 경로에서 파일 발견: {real_path}")
                            return real_path
            except Exception as e:
                logger.error(f"메타데이터 파일 처리 중 오류 발생: {str(e)}")
    
    # 기본 경로에서 검색
    for base_path in IMAGE_BASE_PATHS:
        if not os.path.exists(base_path):
            continue
            
        logger.info(f"검색 경로: {base_path}")
        
        # 직접 경로 조합 시도
        full_path = os.path.join(base_path, filename)
        logger.info(f"직접 경로 조합 시도: {full_path}")
        if os.path.exists(full_path) and os.path.isfile(full_path):
            logger.info(f"파일 발견: {full_path}")
            return full_path
            
        # 재귀적으로 하위 디렉토리 검색
        logger.info(f"하위 디렉토리 검색 시작: {base_path}")
        for root, _, files in os.walk(base_path):
            if filename in files:
                found_path = os.path.join(root, filename)
                logger.info(f"하위 디렉토리에서 파일 발견: {found_path}")
                return found_path
                
        # glob 패턴으로 검색 (파일명의 일부만 일치하는 경우)
        pattern = os.path.join(base_path, f'**/*{filename}*')
        logger.info(f"Glob 패턴 검색: {pattern}")
        matches = glob.glob(pattern, recursive=True)
        if matches:
            logger.info(f"Glob 검색 결과: {matches[0]} (총 {len(matches)}개 결과)")
            return matches[0]
    
    # 이미지 확장자 추가하여 재시도
    for ext in ['.jpg', '.jpeg', '.png', '.gif']:
        if not image_path.lower().endswith(ext):
            ext_path = image_path + ext
            result = find_image_file(ext_path)
            if result:
                return result
    
    logger.warning(f"이미지 파일을 찾을 수 없음: {image_path}")
    return None

from typing import Dict, Any

def process_response_with_images(response: str) -> Dict[str, Any]:
    """응답에서 이미지 태그를 추출하고 처리하고, 항상 dict를 반환합니다."""
    result = {
        'text': response,
        'images': []
    }
    
    # 마크다운 이미지 태그 추출 (![alt](path) 형식)
    markdown_image_pattern = r'!\[(.*?)\]\((.*?)\)'
    markdown_matches = re.findall(markdown_image_pattern, response)
    
    # HTML 이미지 태그 추출 (<img src="path" alt="alt"> 형식)
    html_image_pattern = r'<img\s+src=[\'"](.*?)[\'"](\s+alt=[\'"](.*?)[\'"]*)?'
    html_matches = re.findall(html_image_pattern, response)

    if not markdown_matches and not html_matches:
        return result  # 이미지가 없으면 초기 dict를 그대로 반환

    clean_text = response
    
    # 마크다운 이미지 처리
    for alt_text, img_path in markdown_matches:
        # 텍스트에서 마크다운 태그 제거
        clean_text = clean_text.replace(f'![{alt_text}]({img_path})', '')
        real_path = find_image_file(img_path)
        if real_path:
            image_data = {
                'path': real_path,
                'alt': alt_text,
                'title': alt_text,
                'base64': encode_image_to_base64(real_path)
            }
            if image_data.get('base64'):
                # 중복 추가 방지
                if not any(d['path'] == real_path for d in result['images']):
                    result['images'].append(image_data)
                    logger.info(f"마크다운 이미지 추가됨: {real_path}")

    # HTML 이미지 처리
    for img_path, _, alt_text in html_matches:
        # 텍스트에서 HTML 태그 제거
        clean_text = re.sub(r'<img\s+src=[\'"]' + re.escape(img_path) + r'[\'"].*?>', '', clean_text, flags=re.IGNORECASE)
        real_path = find_image_file(img_path)
        if real_path:
            image_data = {
                'path': real_path,
                'alt': alt_text,
                'title': alt_text,
                'base64': encode_image_to_base64(real_path)
            }
            if image_data.get('base64'):
                 # 중복 추가 방지
                if not any(d['path'] == real_path for d in result['images']):
                    result['images'].append(image_data)
                    logger.info(f"HTML 이미지 추가됨: {real_path}")

    result['text'] = clean_text.strip()
    return result

def encode_image_to_base64(image_path: str) -> Optional[str]:
    """이미지 파일을 base64로 인코딩
    
    Args:
        image_path: 이미지 파일 경로 (상대 또는 절대 경로)
        
    Returns:
        data URL 형식의 base64 인코딩된 이미지 문자열 또는 None (실패 시)
    """
    try:
        # 이미지 경로가 없는 경우 처리
        if not image_path:
            logger.warning("인코딩할 이미지 경로가 비어 있습니다.")
            return None
            
        # 실제 이미지 파일 경로 찾기 시도
        real_image_path = find_image_file(image_path)
        if not real_image_path:
            logger.warning(f"인코딩할 이미지 파일을 찾을 수 없음: {image_path}")
            return None
            
        # 이미지 파일 확장자 확인
        _, ext = os.path.splitext(real_image_path)
        if ext.lower() not in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif']:
            logger.warning(f"지원되지 않는 이미지 형식: {real_image_path}")
            return None
            
        # 파일 존재 확인
        if not os.path.exists(real_image_path) or not os.path.isfile(real_image_path):
            logger.warning(f"이미지 파일이 존재하지 않음: {real_image_path}")
            return None
            
        # 이미지 파일 크기 확인
        file_size = os.path.getsize(real_image_path)
        if file_size > 10 * 1024 * 1024:  # 10MB 제한
            logger.warning(f"이미지 파일이 너무 큽니다 ({file_size / 1024 / 1024:.2f}MB): {real_image_path}")
            return None
        elif file_size == 0:
            logger.warning(f"이미지 파일이 비어 있습니다: {real_image_path}")
            return None
            
        # 이미지 파일 읽기 및 인코딩
        with open(real_image_path, 'rb') as img_file:
            encoded = base64.b64encode(img_file.read()).decode('utf-8')
            
            # 인코딩 결과 확인
            if not encoded:
                logger.warning(f"이미지 인코딩 결과가 비어 있음: {real_image_path}")
                return None
                
            logger.info(f"이미지 인코딩 성공: {real_image_path} (크기: {len(encoded) / 1024:.2f}KB)")
            
            # MIME 타입 결정
            mime_type = 'image/jpeg'  # 기본값
            if ext.lower() in ['.png']:
                mime_type = 'image/png'
            elif ext.lower() in ['.gif']:
                mime_type = 'image/gif'
            elif ext.lower() in ['.bmp']:
                mime_type = 'image/bmp'
            elif ext.lower() in ['.tiff', '.tif']:
                mime_type = 'image/tiff'
            
            return f"data:{mime_type};base64,{encoded}"
            
    except FileNotFoundError:
        logger.error(f"이미지 파일을 찾을 수 없습니다: {image_path}")
        return None
    except PermissionError:
        logger.error(f"이미지 파일에 접근할 권한이 없습니다: {image_path}")
        return None
    except Exception as e:
        logger.error(f"이미지 인코딩 중 오류 발생: {str(e)}")
        return None
