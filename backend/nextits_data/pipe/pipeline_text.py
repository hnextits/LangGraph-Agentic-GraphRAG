#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import time
import argparse
from text_pipe.text_processor import process_layout_json, print_sorted_texts


# 작업 상태를 저장할 파일 경로
STATUS_FILE = '/home/nextits2/.conda/envs/workbox/serch_gui/chatbot/backend/nextits_data/Results/4.Pipeline_results/text/text_processing_status.json'


def find_all_layout_json_files(base_dir):
    """
    지정된 디렉토리에서 모든 layout JSON 파일을 찾는 함수
    
    Args:
        base_dir (str): 검색할 기본 디렉토리 경로
        
    Returns:
        list: 발견된 모든 layout JSON 파일 경로 목록
    """
    layout_files = []
    
    # 디렉토리 순회
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith('.json') and 'layout_' in file:
                layout_files.append(os.path.join(root, file))
    
    return layout_files


def get_output_dir(input_path):
    """
    입력 파일 경로에 기반하여 출력 디렉토리 경로를 생성하는 함수
    
    Args:
        input_path (str): 입력 JSON 파일 경로
        
    Returns:
        str: 출력 디렉토리 경로
    """
    # 기본 출력 디렉토리 설정
    base_dir = '/home/nextits2/.conda/envs/workbox/serch_gui/chatbot/backend/nextits_data/Results/4.Pipeline_results/text'
    
    # 파일 타입(PDF/IMG) 및 파일명 추출
    if 'PDF' in input_path:
        file_type = 'PDF'
    else:
        file_type = 'IMG'
    
    # 파일명 추출 (마지막 디렉토리 이름)
    file_name = os.path.basename(os.path.dirname(input_path))
    
    # 출력 디렉토리 구조 생성
    output_dir = os.path.join(base_dir, file_type, file_name)
    
    return output_dir


def load_processing_status():
    """
    작업 상태 파일을 로드하는 함수
    
    Returns:
        dict: 작업 상태 정보
    """
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"경고: 작업 상태 파일이 손상되었습니다. 새로 시작합니다.")
    
    # 기본 상태 정보
    return {
        'processed_files': [],
        'last_processed_index': -1,
        'total_files': 0,
        'start_time': time.time(),
        'errors': []
    }


def save_processing_status(status):
    """
    작업 상태를 파일에 저장하는 함수
    
    Args:
        status (dict): 저장할 작업 상태 정보
    """
    # 현재 시간 업데이트
    status['last_update_time'] = time.time()
    
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=4)


def is_file_processed(file_path, status):
    """
    파일이 이미 처리되었는지 확인하는 함수
    
    Args:
        file_path (str): 확인할 파일 경로
        status (dict): 작업 상태 정보
        
    Returns:
        bool: 파일이 이미 처리되었으면 True, 아니면 False
    """
    # 출력 파일 경로 생성
    output_dir = get_output_dir(file_path)
    output_json_path = os.path.join(output_dir, os.path.basename(file_path).replace('.json', '_sorted.json'))
    
    # 출력 파일이 존재하는지 확인
    if os.path.exists(output_json_path):
        return True
    
    # 작업 상태에 포함되어 있는지 확인
    return file_path in status['processed_files']


def process_all_layout_json_files(base_dir=None, resume=True):
    """
    모든 레이아웃 JSON 파일을 처리하는 함수
    
    Args:
        base_dir (str, optional): 검색할 기본 디렉토리 경로
        resume (bool, optional): 중단된 작업을 이어서 할지 여부
        
    Returns:
        int: 처리된 파일 수
    """
    # 기본 디렉토리 설정
    if base_dir is None:
        base_dir = '/home/nextits2/.conda/envs/workbox/serch_gui/chatbot/backend/nextits_data/Results/2.LayoutDetection'
    
    # 모든 레이아웃 JSON 파일 찾기
    layout_files = find_all_layout_json_files(base_dir)
    layout_files.sort()  # 파일 경로 정렬
    
    # 작업 상태 로드
    status = load_processing_status()
    
    # 총 파일 수 업데이트
    status['total_files'] = len(layout_files)
    save_processing_status(status)
    
    # resume=True 이어도 **항상 전체 파일을 순회**하고,
    # 각 파일마다 is_file_processed() 로 건너뜁니다.
    # resume=False 를 지정하면 이전 상태를 초기화하여 모든 파일을 다시 처리합니다.
    if not resume:
        status['processed_files'] = []
        status['last_processed_index'] = -1
        print("Resume 비활성화: 이전 처리 상태를 초기화합니다.")

    processed_count = 0

    print(f"총 {len(layout_files)}개의 레이아웃 JSON 파일을 찾았습니다.")

    # 각 파일 처리
    for i, file_path in enumerate(layout_files):
        
        # 이미 처리된 파일인지 확인
        if is_file_processed(file_path, status):
            print(f"[{i+1}/{len(layout_files)}] 이미 처리된 파일 건너뜀: {os.path.basename(file_path)}")
            continue
        
        try:
            print(f"\n[{i+1}/{len(layout_files)}] 처리 중: {file_path}")
            
            # 출력 디렉토리 설정
            output_dir = get_output_dir(file_path)
            
            # 파일 처리
            sorted_texts = process_layout_json(file_path, output_dir)
            
            # 처리 결과 출력
            print_sorted_texts(sorted_texts)
            
            # 작업 상태 업데이트
            status['processed_files'].append(file_path)
            status['last_processed_index'] = i
            save_processing_status(status)
            
            processed_count += 1
            
        except Exception as e:
            print(f"오류 발생: {file_path} - {str(e)}")
            # 오류 정보 저장
            status['errors'].append({
                'file': file_path,
                'error': str(e),
                'index': i
            })
            save_processing_status(status)
    
    # 작업 완료 시간 업데이트
    status['end_time'] = time.time()
    status['completed'] = True
    save_processing_status(status)
    
    return processed_count


def run_json_to_markdown(input_dir=None, output_dir=None, skip_existing=True, resume=True):
    """
    JSON 파일을 마크다운으로 변환하는 함수를 실행
    
    Args:
        input_dir (str, optional): 입력 디렉토리 경로
        output_dir (str, optional): 출력 디렉토리 경로
        skip_existing (bool, optional): 이미 처리된 파일 건너뛰기 여부
        resume (bool, optional): 중단된 작업 이어서 하기 여부
    """
    # 기본 디렉토리 설정
    if input_dir is None:
        input_dir = '/home/nextits2/.conda/envs/workbox/serch_gui/chatbot/backend/nextits_data/Results/4.Pipeline_results/text'
    
    if output_dir is None:
        output_dir = '/home/nextits2/.conda/envs/workbox/serch_gui/chatbot/backend/nextits_data/Results/4.Pipeline_results/text/markdown'
    
    # 출력 디렉토리 생성
    os.makedirs(output_dir, exist_ok=True)
    
    # json_to_markdown.py 스크립트 실행
    cmd = [
        'python',
        '/home/nextits2/.conda/envs/workbox/serch_gui/chatbot/backend/nextits_data/pipe/text_pipe/text_markdown.py',
        f'--input-dir={input_dir}',
        f'--output-dir={output_dir}'
    ]
    
    # 옵션 추가
    if not skip_existing:
        cmd.append('--no-skip-existing')
    if not resume:
        cmd.append('--no-resume')
    
    print("\nJSON 파일을 마크다운으로 변환 중...")
    print(f"명령어: {' '.join(cmd)}")
    
    import subprocess
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("마크다운 변환 완료!")
        print(result.stdout)
    else:
        print(f"마크다운 변환 중 오류 발생: {result.stderr}")


def run_text_chunking(model_name="qwen3:4b", reset=False):
    """시맨틱 청킹 및 최종 결과 통합 스크립트를 실행합니다.

    Args:
        model_name (str): 사용할 Ollama 모델 이름
        reset (bool): 처리 상태를 초기화하고 모든 파일을 다시 처리할지 여부
    """
    # text_chunking.py 스크립트 경로
    script_path = '/home/nextits2/.conda/envs/workbox/serch_gui/chatbot/backend/nextits_data/pipe/text_pipe/text_chunking.py'

    cmd = [
        'python',
        script_path,
        f'--model={model_name}'
    ]

    if reset:
        cmd.append('--reset')

    print("\n시맨틱 청킹 및 통합 결과 생성 중...")
    print(f"명령어: {' '.join(cmd)}")

    import subprocess
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print("시맨틱 청킹 및 통합 완료!")
        if result.stdout:
            print(result.stdout)
    else:
        print(f"시맨틱 청킹 중 오류 발생: {result.stderr}")


def main():
    """
    메인 함수
    """
    parser = argparse.ArgumentParser(description='레이아웃 JSON 파일의 텍스트 박스를 처리하는 프로그램')
    parser.add_argument('--base-dir', type=str, help='검색할 기본 디렉토리 경로')
    parser.add_argument('--no-resume', action='store_true', help='중단된 작업을 이어서 하지 않고 처음부터 시작')
    parser.add_argument('--no-markdown', action='store_true', help='마크다운 변환 건너뛰기')
    parser.add_argument('--no-chunking', action='store_true', help='시맨틱 청킹(최종 결과 생성) 단계 건너뛰기')
    parser.add_argument('--markdown-output-dir', type=str, help='마크다운 출력 디렉토리 경로')
    args = parser.parse_args()
    
    # 모든 레이아웃 JSON 파일 처리
    processed_count = process_all_layout_json_files(
        base_dir=args.base_dir,
        resume=not args.no_resume
    )
    
    print(f"\n작업 완료: {processed_count}개 파일 처리됨")
    
    # 블록 나누기가 완료된 후 마크다운 변환 실행
    if not args.no_markdown:
        run_json_to_markdown(
            output_dir=args.markdown_output_dir,
            resume=not args.no_resume
        )

    # 마크다운 변환 후 시맨틱 청킹 및 최종 결과 통합 실행
    if not args.no_chunking:
        run_text_chunking(reset=False)


if __name__ == '__main__':
    main()
