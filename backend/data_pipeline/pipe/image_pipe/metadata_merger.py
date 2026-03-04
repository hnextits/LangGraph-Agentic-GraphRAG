#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import argparse
from pathlib import Path
from collections import defaultdict

# 대상 폴더 이름 목록 (필요 시 수정 가능)
TARGET_FOLDER_NAMES = ['image', 'chart']


def find_image_folders(root_dir, target_folder_names=None):
    """
    주어진 루트 디렉토리에서 `target_folder_names`에 정의된 모든 폴더를 찾습니다.

    Args:
        root_dir (str): 검색을 시작할 루트 디렉토리 경로
        target_folder_names (list[str], optional): 찾을 폴더 이름 목록. 기본값은
            `TARGET_FOLDER_NAMES`.

    Returns:
        list[str]: 발견된 모든 대상 폴더의 경로 목록
    """
    if target_folder_names is None:
        target_folder_names = TARGET_FOLDER_NAMES

    found_folders = []
    for dirpath, dirnames, _ in os.walk(root_dir):
        for target in target_folder_names:
            if target in dirnames:
                found_folders.append(os.path.join(dirpath, target))

    return found_folders


def get_parent_folder_name(folder_path):
    """
    주어진 폴더 경로의 부모 폴더 이름을 반환합니다.
    
    Args:
        folder_path (str): 폴더 경로
        
    Returns:
        str: 부모 폴더 이름
    """
    return os.path.basename(os.path.dirname(folder_path))


def collect_metadata_files(image_folders):
    """
    각 image 폴더에서 메타데이터 JSON 파일을 수집하고 부모 폴더별로 그룹화합니다.
    
    Args:
        image_folders (list): image 폴더 경로 목록
        
    Returns:
        dict: 부모 폴더 이름을 키로, 메타데이터 파일 경로 목록을 값으로 하는 딕셔너리
    """
    metadata_files_by_parent = defaultdict(list)
    
    for folder in image_folders:
        parent_folder = get_parent_folder_name(folder)
        
        for file in os.listdir(folder):
            if file.endswith('_metadata.json'):
                metadata_files_by_parent[parent_folder].append(os.path.join(folder, file))
                
    return metadata_files_by_parent


def merge_metadata_files(metadata_files, output_dir):
    """
    메타데이터 파일들을 병합하여 출력 디렉토리에 저장합니다.
    
    Args:
        metadata_files (dict): 부모 폴더 이름을 키로, 메타데이터 파일 경로 목록을 값으로 하는 딕셔너리
        output_dir (str): 병합된 메타데이터 파일을 저장할 디렉토리 경로
        
    Returns:
        dict: 처리 결과 통계 (처리된 파일 수, 생성된 파일 수)
    """
    # 출력 디렉토리가 없으면 생성
    os.makedirs(output_dir, exist_ok=True)
    
    stats = {
        'processed_files': 0,
        'created_files': 0,
        'title_to_filename': {}
    }
    
    for parent_folder, files in metadata_files.items():
        if not files:
            continue
        
        # 각 파일에서 메타데이터 수집
        all_metadata = []
        title = None
        
        for file_path in files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 첫 번째 파일에서 title을 가져옴
                if title is None and 'metadata' in data and 'title' in data['metadata']:
                    title = data['metadata']['title']
                
                all_metadata.append(data)
                stats['processed_files'] += 1
                
            except Exception as e:
                print(f"파일 처리 중 오류 발생: {file_path}, 오류: {e}")
        
        # title이 없으면 부모 폴더 이름을 사용
        if not title:
            title = parent_folder
            
        # 병합된 메타데이터를 저장
        output_file = os.path.join(output_dir, f"{title}.json")
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(all_metadata, f, ensure_ascii=False, indent=4)
            
            stats['created_files'] += 1
            stats['title_to_filename'][title] = output_file
            print(f"병합 완료: {output_file} (파일 {len(all_metadata)}개 병합)")
            
        except Exception as e:
            print(f"파일 저장 중 오류 발생: {output_file}, 오류: {e}")
    
    return stats


# 스크립트 위치를 기준으로 backend/ 디렉토리
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

# 상대 경로로 디렉토리 설정
CROP_IMAGE_DIR = BASE_DIR / "data_pipeline" / "Results" / "3.Crop_image"
COMPLETION_RESULTS_DIR = BASE_DIR / "data_pipeline" / "Results" / "5.Completion_results" / "image"

def main():
    parser = argparse.ArgumentParser(description='이미지 메타데이터 JSON 파일을 병합하는 도구')
    parser.add_argument('--input', '-i', type=str, default=str(CROP_IMAGE_DIR),
                        help='검색을 시작할 루트 디렉토리 경로')
    parser.add_argument('--output', '-o', type=str, default=str(COMPLETION_RESULTS_DIR),
                        help='병합된 메타데이터 파일을 저장할 디렉토리 경로')
                        
    args = parser.parse_args()
    
    print(f"루트 디렉토리: {args.input}")
    print(f"출력 디렉토리: {args.output}")
    
        # 대상 폴더(image/chart 등) 찾기
    print(f"대상 폴더({', '.join(TARGET_FOLDER_NAMES)}) 검색 중...")
    image_folders = find_image_folders(args.input)
    print(f"발견된 대상 폴더: {len(image_folders)}개")
    
    # 메타데이터 파일 수집
    print("메타데이터 파일 수집 중...")
    metadata_files = collect_metadata_files(image_folders)
    print(f"메타데이터 파일이 있는 부모 폴더: {len(metadata_files)}개")
    
    # 메타데이터 파일 병합 및 저장
    print("메타데이터 파일 병합 및 저장 중...")
    stats = merge_metadata_files(metadata_files, args.output)
    
    # 결과 출력
    print("\n처리 완료:")
    print(f"- 처리된 메타데이터 파일: {stats['processed_files']}개")
    print(f"- 생성된 병합 파일: {stats['created_files']}개")
    print("\n생성된 파일 목록:")
    for title, filename in stats['title_to_filename'].items():
        print(f"- {title}: {filename}")


if __name__ == "__main__":
    main()
