#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
이미지 처리 모듈 - 이미지 경로를 찾고 base64로 변환하는 기능을 제공합니다.
"""

import os
import json
import base64
import logging
from typing import List, Dict, Any, Optional

# 로깅 설정
logger = logging.getLogger(__name__)

# 이미지 기본 경로 설정
# New data path from config
from config import RAGConfig

# RAGConfig 인스턴스 생성
rag_config = RAGConfig()

IMAGE_BASE_PATHS = [
    os.path.join(rag_config.DATA_PATH, 'Results', '3.Crop_image', 'PDF'),
    os.path.join(rag_config.DATA_PATH, 'Results', '3.Crop_image', 'IMG'),
    os.path.join(rag_config.DATA_PATH, 'Results', '3.Crop_image'),
    os.path.join(rag_config.DATA_PATH, 'Results'),
    rag_config.DATA_PATH,
]

class ImageProcessor:
    """
    이미지 처리기 클래스
    이미지 경로를 찾고 base64로 변환하는 기능을 제공합니다.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        이미지 처리기 초기화
        
        Args:
            config: 설정 딕셔너리 (옵션)
        """
        self.config = config or {}
        self.image_base_paths = self.config.get("image_base_paths", IMAGE_BASE_PATHS)
        logger.info("이미지 처리기 초기화 완료")
    
    def find_image_file(self, image_path: str) -> Optional[str]:
        """
        이미지 파일의 실제 경로 찾기
        
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
        metadata_path = os.path.join(os.path.dirname(__file__), '..', 'faiss_test', 'image_metadata.json')
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                # 파일명 추출
                filename = os.path.basename(image_path)
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
        
        # 파일명만 추출하여 기본 이미지 경로에서 검색
        filename = os.path.basename(image_path)
        
        # 기본 이미지 경로에서 검색
        for base_path in self.image_base_paths:
            # 직접 경로 확인
            full_path = os.path.join(base_path, filename)
            if os.path.exists(full_path) and os.path.isfile(full_path):
                logger.info(f"기본 경로에서 이미지 발견: {full_path}")
                return full_path
            
            # 하위 디렉토리 검색
            for root, _, files in os.walk(base_path):
                if filename in files:
                    full_path = os.path.join(root, filename)
                    logger.info(f"하위 디렉토리에서 이미지 발견: {full_path}")
                    return full_path
        
        logger.warning(f"이미지 파일을 찾을 수 없음: {image_path}")
        return None
    
    def encode_image_to_base64(self, image_path: str) -> Optional[str]:
        """
        이미지 파일을 base64로 인코딩
        
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
            real_image_path = self.find_image_file(image_path)
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
                    
                # data URL 형식으로 base64 이미지 생성
                data_url = f"data:{mime_type};base64,{encoded}"
                return data_url
        except Exception as e:
            logger.error(f"이미지 인코딩 중 오류 발생 ({image_path}): {str(e)}")
            return None
    
    def process_image_paths(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        결과에 포함된 이미지 경로를 base64로 변환
        
        Args:
            results: 처리할 결과 딕셔너리
            
        Returns:
            이미지가 base64로 변환된 결과 딕셔너리
        """
        if not results:
            return results
            
        # 이미지 목록 초기화
        if 'images' not in results:
            results['images'] = []
        
        # image_paths 키 처리 (이미지 경로 목록)
        if 'image_paths' in results and isinstance(results['image_paths'], list):
            logger.info(f"image_paths 키 발견: {len(results['image_paths'])}개 이미지 처리 시작")
            
            for idx, path_item in enumerate(results['image_paths']):
                # 문자열 경로인 경우
                if isinstance(path_item, str):
                    image_path = path_item
                    base64_data = self.encode_image_to_base64(image_path)
                    
                    if base64_data:
                        # 이미지 정보 생성
                        image_info = {
                            'id': f'img_{idx}',
                            'title': f'이미지 {idx+1}',
                            'file_path': image_path,
                            'base64': base64_data
                        }
                        
                        # 이미지 목록에 추가
                        results['images'].append(image_info)
                        
                        # image_paths 항목 업데이트
                        results['image_paths'][idx] = image_info
                        
                        logger.info(f"이미지 {idx+1} 인코딩 성공: {image_path}")
                
                # 딕셔너리 형태인 경우
                elif isinstance(path_item, dict) and 'file_path' in path_item:
                    image_path = path_item['file_path']
                    base64_data = self.encode_image_to_base64(image_path)
                    
                    if base64_data:
                        # 기존 정보 유지하면서 base64 추가
                        path_item['base64'] = base64_data
                        path_item['id'] = path_item.get('id', f'img_{idx}')
                        
                        # 이미지 목록에 추가
                        results['images'].append(path_item)
                        
                        logger.info(f"이미지 {idx+1} 인코딩 성공 (딕셔너리): {image_path}")
            
            logger.info(f"image_paths 처리 완료: {len(results['images'])}개 이미지 인코딩됨")
            
        # 검색 결과 처리
        if 'results' in results and isinstance(results['results'], list):
            for idx, item in enumerate(results['results']):
                # 이미지 항목 처리
                if item.get('media_type') == 'image' and 'file_path' in item and item['file_path']:
                    image_path = item['file_path']
                    base64_data = self.encode_image_to_base64(image_path)
                    
                    if base64_data:
                        # 이미지 정보 생성
                        image_id = item.get('id', f'img_{idx}')
                        image_info = {
                            'id': image_id,
                            'title': item.get('title', ''),
                            'caption': item.get('caption', ''),
                            'page_num': item.get('page_num', ''),
                            'file_path': image_path,
                            'base64': base64_data
                        }
                        
                        # 이미지 목록에 추가
                        results['images'].append(image_info)
                        
                        # 결과 항목에도 base64 추가
                        item['base64'] = base64_data
        
        # 호환성을 위해 첫 번째 이미지도 'image' 키로 제공
        if results.get('images') and len(results['images']) > 0:
            results['image'] = results['images'][0]
            
        return results


# 싱글톤 인스턴스 생성
image_processor = ImageProcessor()
