#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import argparse
import logging
import subprocess
import sys
from pathlib import Path

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 스크립트 위치를 기준으로 backend/ 디렉토리
BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Config:
    # 입출력 디렉토리 설정
    LAYOUT_INPUT_DIR = BASE_DIR / "nextits_data" / "Results" / "2.LayoutDetection"
    CROP_OUTPUT_DIR = BASE_DIR / "nextits_data" / "Results" / "3.Crop_image"
    METADATA_OUTPUT_DIR = BASE_DIR / "nextits_data" / "Results" / "5.Completion_results" / "image"
    
    # 처리 옵션
    SKIP_EXISTING = True  # 이미 처리된 파일 건너뛰기


def run_img_croplayoutimg(input_dir=None, output_dir=None, skip_existing=True):
    """
    이미지 크롭 스크립트(img_croplayoutimg.py)를 실행하는 함수
    
    Args:
        input_dir (str, optional): 레이아웃 감지 결과가 있는 입력 디렉토리 경로
        output_dir (str, optional): 크롭된 이미지를 저장할 출력 디렉토리 경로
        skip_existing (bool, optional): 이미 처리된 파일 건너뛰기 여부
    
    Returns:
        bool: 성공 여부
    """
    # 기본 디렉토리 설정
    if input_dir is None:
        input_dir = str(Config.LAYOUT_INPUT_DIR)
    
    if output_dir is None:
        output_dir = str(Config.CROP_OUTPUT_DIR)
    
    # img_croplayoutimg.py 스크립트 경로
    script_path = Path(__file__).parent / 'image_pipe' / 'img_croplayoutimg.py'
    
    if not script_path.exists():
        logger.error(f"오류: 이미지 크롭 스크립트를 찾을 수 없습니다: {script_path}")
        return False
    
    # 명령어 구성
    cmd = [
        'python',
        str(script_path),
        f'--input_dir={input_dir}',
        f'--output_dir={output_dir}'
    ]
    
    # skip_existing가 False일 때만 --no_skip_existing 플래그를 추가합니다.
    if not skip_existing:
        cmd.append('--no_skip_existing')
    
    # 스크립트 실행
    logger.info("이미지 크롭 스크립트 실행 중...")
    logger.info(f"명령어: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info("이미지 크롭 완료!")
            if result.stdout:
                logger.info(result.stdout)
            return True
        else:
            logger.error(f"이미지 크롭 중 오류 발생: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"이미지 크롭 스크립트 실행 중 예외 발생: {e}")
        return False


def run_metadata_merger(input_dir=None, output_dir=None):
    """
    메타데이터 병합 스크립트(metadata_merger.py)를 실행하는 함수
    
    Args:
        input_dir (str, optional): 크롭된 이미지와 메타데이터가 있는 입력 디렉토리 경로
        output_dir (str, optional): 병합된 메타데이터를 저장할 출력 디렉토리 경로
    
    Returns:
        bool: 성공 여부
    """
    # 기본 디렉토리 설정
    if input_dir is None:
        input_dir = str(Config.CROP_OUTPUT_DIR)
    
    if output_dir is None:
        output_dir = str(Config.METADATA_OUTPUT_DIR)
    
    # metadata_merger.py 스크립트 경로
    script_path = Path(__file__).parent / 'image_pipe' / 'metadata_merger.py'
    
    if not script_path.exists():
        logger.error(f"오류: 메타데이터 병합 스크립트를 찾을 수 없습니다: {script_path}")
        return False
    
    # 명령어 구성
    cmd = [
        'python',
        str(script_path),
        f'--input={input_dir}',
        f'--output={output_dir}'
    ]
    
    # 스크립트 실행
    logger.info("메타데이터 병합 스크립트 실행 중...")
    logger.info(f"명령어: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info("메타데이터 병합 완료!")
            if result.stdout:
                logger.info(result.stdout)
            return True
        else:
            logger.error(f"메타데이터 병합 중 오류 발생: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"메타데이터 병합 스크립트 실행 중 예외 발생: {e}")
        return False


def main():
    """
    메인 함수: 이미지 파이프라인 실행
    1. img_croplayoutimg.py 실행
    2. metadata_merger.py 실행
    """
    # 명령행 인자 처리
    parser = argparse.ArgumentParser(description="이미지 처리 파이프라인")
    
    # 입출력 디렉토리 인자
    parser.add_argument("--layout_input", type=str, help="레이아웃 감지 결과가 있는 입력 디렉토리")
    parser.add_argument("--crop_output", type=str, help="크롭된 이미지를 저장할 출력 디렉토리")
    parser.add_argument("--metadata_output", type=str, help="병합된 메타데이터를 저장할 출력 디렉토리")
    
    # 처리 옵션 인자
    parser.add_argument("--skip_existing", action="store_true", help="이미 처리된 파일 건너뛰기")
    
    args = parser.parse_args()
    
    # 인자에서 값 가져오기 (또는 기본값 사용)
    layout_input_dir = args.layout_input or str(Config.LAYOUT_INPUT_DIR)
    crop_output_dir = args.crop_output or str(Config.CROP_OUTPUT_DIR)
    metadata_output_dir = args.metadata_output or str(Config.METADATA_OUTPUT_DIR)
    skip_existing = args.skip_existing or Config.SKIP_EXISTING
    
    # 출력 디렉토리 생성
    os.makedirs(crop_output_dir, exist_ok=True)
    os.makedirs(metadata_output_dir, exist_ok=True)
    
    logger.info("=== 이미지 처리 파이프라인 시작 ===")
    logger.info(f"레이아웃 입력 디렉토리: {layout_input_dir}")
    logger.info(f"크롭 출력 디렉토리: {crop_output_dir}")
    logger.info(f"메타데이터 출력 디렉토리: {metadata_output_dir}")
    
    # 1단계: 이미지 크롭 스크립트 실행
    logger.info("\n[1/2] 이미지 크롭 스크립트 실행...")
    crop_success = run_img_croplayoutimg(
        input_dir=layout_input_dir,
        output_dir=crop_output_dir,
        skip_existing=skip_existing
    )
    
    if not crop_success:
        logger.error("이미지 크롭 단계 실패. 파이프라인 중단.")
        return 1
    
    # 2단계: 메타데이터 병합 스크립트 실행
    logger.info("\n[2/2] 메타데이터 병합 스크립트 실행...")
    merger_success = run_metadata_merger(
        input_dir=crop_output_dir,
        output_dir=metadata_output_dir
    )
    
    if not merger_success:
        logger.error("메타데이터 병합 단계 실패. 파이프라인 중단.")
        return 1
    
    logger.info("\n=== 이미지 처리 파이프라인 완료 ===\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

