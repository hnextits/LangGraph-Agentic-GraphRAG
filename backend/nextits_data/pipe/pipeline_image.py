#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import argparse
import logging
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.nextits_data.pipe.bootstrap import (
    ensure_backend_root,
    configure_logging,
    get_backend_dir,
    get_nextits_data_dir,
)

ensure_backend_root()
configure_logging()
logger = logging.getLogger(__name__)

# 경로 기본값
BACKEND_DIR = get_backend_dir()
NEXTITS_DATA_DIR = get_nextits_data_dir()

class Config:
    # 입출력 디렉토리 설정
    LAYOUT_INPUT_DIR = NEXTITS_DATA_DIR / "Results" / "2.LayoutDetection"
    CROP_OUTPUT_DIR = NEXTITS_DATA_DIR / "Results" / "3.Crop_image"
    METADATA_OUTPUT_DIR = NEXTITS_DATA_DIR / "Results" / "5.Completion_results" / "image"
    
    # 처리 옵션 (필요 시 설정에서 수정 가능)
    SKIP_EXISTING = True
    RESUME = True
    ADD_NUMBERING = True
    MIN_WIDTH = 200
    MIN_HEIGHT = 200
    MAX_WIDTH = 800
    MAX_HEIGHT = 850


def run_img_croplayoutimg(
    input_dir=None,
    output_dir=None,
    skip_existing=True,
    resume=True,
    add_numbering=True,
    min_width=None,
    min_height=None,
    max_width=None,
    max_height=None,
):
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
    
    # 세부 옵션 전달
    # img_croplayoutimg.py는 skip/resume/add_numbering 기본값이 True이므로
    # False일 때만 비활성화 플래그를 전달한다.
    if skip_existing is False:
        cmd.append('--no_skip_existing')
    if resume is False:
        cmd.append('--no_resume')
    if add_numbering is False:
        cmd.append('--no_add_numbering')
    if min_width is not None:
        cmd.append(f'--min_width={min_width}')
    if min_height is not None:
        cmd.append(f'--min_height={min_height}')
    if max_width is not None:
        cmd.append(f'--max_width={max_width}')
    if max_height is not None:
        cmd.append(f'--max_height={max_height}')
    
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
    parser.add_argument("--results_base", type=str, help="결과 저장 최상위 경로 (세션 지원용)")
    
    # 처리 옵션 인자
    parser.add_argument("--skip_existing", dest="skip_existing", action="store_true", help="이미 처리된 파일 건너뛰기")
    parser.add_argument("--no_skip_existing", dest="skip_existing", action="store_false", help="이미 처리된 파일도 다시 처리")
    parser.add_argument("--resume", dest="resume", action="store_true", help="중단된 위치부터 이어서 처리")
    parser.add_argument("--no_resume", dest="resume", action="store_false", help="항상 처음부터 처리")
    parser.add_argument("--add_numbering", dest="add_numbering", action="store_true", help="메타데이터에 넘버링 추가")
    parser.add_argument("--no_add_numbering", dest="add_numbering", action="store_false", help="메타데이터 넘버링 비활성화")
    parser.add_argument("--min_width", type=int, help="크롭할 최소 바운딩 박스 너비")
    parser.add_argument("--min_height", type=int, help="크롭할 최소 바운딩 박스 높이")
    parser.add_argument("--max_width", type=int, help="크롭할 최대 바운딩 박스 너비")
    parser.add_argument("--max_height", type=int, help="크롭할 최대 바운딩 박스 높이")
    parser.set_defaults(skip_existing=None, resume=None, add_numbering=None)
    
    args = parser.parse_args()
    
    # 인자에서 값 가져오기 (또는 기본값 사용)
    results_base = Path(args.results_base) if args.results_base else None
    
    if results_base:
        layout_input_dir = args.layout_input or str(results_base / "2.LayoutDetection")
        crop_output_dir = args.crop_output or str(results_base / "3.Crop_image")
        metadata_output_dir = args.metadata_output or str(results_base / "5.Completion_results" / "image")
    else:
        layout_input_dir = args.layout_input or str(Config.LAYOUT_INPUT_DIR)
        crop_output_dir = args.crop_output or str(Config.CROP_OUTPUT_DIR)
        metadata_output_dir = args.metadata_output or str(Config.METADATA_OUTPUT_DIR)
    skip_existing = Config.SKIP_EXISTING if args.skip_existing is None else args.skip_existing
    resume = Config.RESUME if args.resume is None else args.resume
    add_numbering = Config.ADD_NUMBERING if args.add_numbering is None else args.add_numbering
    min_width = args.min_width if args.min_width is not None else Config.MIN_WIDTH
    min_height = args.min_height if args.min_height is not None else Config.MIN_HEIGHT
    max_width = args.max_width if args.max_width is not None else Config.MAX_WIDTH
    max_height = args.max_height if args.max_height is not None else Config.MAX_HEIGHT

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
        skip_existing=skip_existing,
        resume=resume,
        add_numbering=add_numbering,
        min_width=min_width,
        min_height=min_height,
        max_width=max_width,
        max_height=max_height,
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

