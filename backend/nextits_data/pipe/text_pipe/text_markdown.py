#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import re
import time
import argparse
from collections import defaultdict


def extract_page_number(filename):
    """
    파일명에서 페이지 번호를 추출하는 함수
    
    Args:
        filename (str): 파일명
        
    Returns:
        int: 페이지 번호
    """
    match = re.search(r'layout_(\d+)', filename)
    if match:
        return int(match.group(1))
    return 0


def collect_sorted_json_files(base_dir):
    """
    정렬된 JSON 파일들을 수집하는 함수
    
    Args:
        base_dir (str): 기본 디렉토리 경로
        
    Returns:
        dict: 문서별로 그룹화된 JSON 파일 경로
    """
    # 문서별로 JSON 파일 그룹화
    document_files = defaultdict(list)
    
    # 디렉토리 순회
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith('_sorted.json'):
                file_path = os.path.join(root, file)
                
                # 문서 이름 추출 (디렉토리 이름)
                document_name = os.path.basename(os.path.dirname(file_path))
                
                # 문서별로 파일 그룹화
                document_files[document_name].append(file_path)
    
    # 각 문서 내의 파일들을 페이지 번호 순으로 정렬
    for document_name, files in document_files.items():
        document_files[document_name] = sorted(files, key=lambda x: extract_page_number(os.path.basename(x)))
    
    return document_files


def remove_repetitive_patterns(text, min_repetitions=4):
    """
    연속적으로 반복되는 패턴을 제거하는 함수
    
    Args:
        text (str): 처리할 텍스트
        min_repetitions (int): 최소 반복 횟수
        
    Returns:
        str: 반복 패턴이 제거된 텍스트
    """
    if not text or len(text) < 20:  # 너무 짧은 텍스트는 처리하지 않음
        return text
    
    # 문장 단위로 반복 처리
    sentences = re.split(r'([.!?\n])', text)
    processed_sentences = []
    i = 0
    while i < len(sentences):
        if i + 2 * min_repetitions <= len(sentences):
            # 현재 문장이 여러 번 반복되는지 확인
            sentence = sentences[i]
            repetition_count = 1
            j = i + 2  # 구분자를 건너뛰고 다음 문장으로
            
            while j < len(sentences) and sentences[j] == sentence:
                repetition_count += 1
                j += 2  # 구분자를 건너뛰고 다음 문장으로
            
            if repetition_count >= min_repetitions:
                processed_sentences.append(sentence)
                if i + 1 < len(sentences):  # 구분자 추가
                    processed_sentences.append(sentences[i+1])
                i = j  # 반복된 문장들을 건너뜀
                continue
        
        processed_sentences.append(sentences[i])
        i += 1
    
    # 단어 단위로 반복 처리
    text = ''.join(processed_sentences)
    
    # 긴 문장 패턴 처리
    # 길이가 긴 문장에서 반복 패턴을 찾기 위한 패턴 찾기
    # 예: "A B C D A B C D A B C D" -> "A B C D"
    # 문장 단위로 분할
    chunks = re.split(r'([.!?\n])', text)
    result_chunks = []
    
    for chunk in chunks:
        if len(chunk) < 20:  # 짧은 문장은 그대로 유지
            result_chunks.append(chunk)
            continue
        
        # 긴 문장에서 반복 패턴 찾기
        # 문장을 단어로 분할
        words = chunk.split()
        
        if len(words) < min_repetitions * 2:  # 단어가 너무 적으면 처리하지 않음
            result_chunks.append(chunk)
            continue
        
        # 단어 패턴 반복 처리
        result_words = []
        i = 0
        while i < len(words):
            pattern_found = False
            
            # 다양한 패턴 길이를 시도 (2~15개 단어 패턴)
            # 길이가 긴 패턴을 먼저 찾도록 역순으로 처리
            for pattern_len in range(min(15, len(words) // min_repetitions), 1, -1):
                if i + pattern_len * min_repetitions > len(words):
                    continue
                    
                # 현재 위치에서 패턴 추출
                pattern = words[i:i+pattern_len]
                repetition_count = 1
                j = i + pattern_len
                
                # 같은 패턴이 반복되는지 확인
                while j + pattern_len <= len(words) and words[j:j+pattern_len] == pattern:
                    repetition_count += 1
                    j += pattern_len
                
                if repetition_count >= min_repetitions:
                    # 패턴을 한 번만 추가
                    result_words.extend(pattern)
                    i = j  # 반복된 패턴들을 건너뜀
                    pattern_found = True
                    break
            
            if not pattern_found:
                result_words.append(words[i])
                i += 1
        
        result_chunks.append(' '.join(result_words))
    
    # 문장 단위로 분할한 결과를 다시 합치기
    return ''.join(result_chunks)
    
    # 추가 처리: 전체 텍스트에서 반복 패턴 찾기
    # 이 부분은 위에서 처리하지 못한 긴 문장 패턴을 처리하기 위한 추가 작업
    words = text.split()
    
    if len(words) < min_repetitions * 2:  # 단어가 너무 적으면 처리하지 않음
        return text
    
    # 단어 패턴 반복 처리
    result_words = []
    i = 0
    while i < len(words):
        pattern_found = False
        
        # 다양한 패턴 길이를 시도 (2~15개 단어 패턴)
        # 길이가 긴 패턴을 먼저 찾도록 역순으로 처리
        for pattern_len in range(min(15, len(words) // min_repetitions), 1, -1):
            if i + pattern_len * min_repetitions > len(words):
                continue
                
            # 현재 위치에서 패턴 추출
            pattern = words[i:i+pattern_len]
            repetition_count = 1
            j = i + pattern_len
            
            # 같은 패턴이 반복되는지 확인
            while j + pattern_len <= len(words) and words[j:j+pattern_len] == pattern:
                repetition_count += 1
                j += pattern_len
            
            if repetition_count >= min_repetitions:
                # 패턴을 한 번만 추가
                result_words.extend(pattern)
                i = j  # 반복된 패턴들을 건너뜀
                pattern_found = True
                break
        
        if not pattern_found:
            result_words.append(words[i])
            i += 1
    
    return ' '.join(result_words)


def json_to_markdown(json_files, output_dir, min_page_length=50, min_repetition=4):
    """
    JSON 파일들을 마크다운 형식으로 변환하는 함수
    
    Args:
        json_files (dict): 문서별로 그룹화된 JSON 파일 경로
        output_dir (str): 출력 디렉토리 경로
        min_page_length (int): 페이지당 최소 텍스트 길이 (기본값: 50자)
        min_repetition (int): 중복 패턴 감지를 위한 최소 반복 횟수 (기본값: 4회)
    """
    # 출력 디렉토리 생성
    os.makedirs(output_dir, exist_ok=True)
    
    # 각 문서별로 처리
    for document_name, files in json_files.items():
        # 마크다운 파일 경로
        md_file_path = os.path.join(output_dir, f"{document_name}.md")
        
        # 마크다운 파일 생성
        with open(md_file_path, 'w', encoding='utf-8') as md_file:
            # 문서 제목 작성
            md_file.write(f"# {document_name}\n\n")
            
            # 각 페이지별로 처리
            for j, file_path in enumerate(files):
                # JSON 파일 로드
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 페이지 번호 추출
                page_number = extract_page_number(os.path.basename(file_path))
                
                # 정렬된 텍스트 추출
                sorted_texts = data.get('sorted_texts', [])
                
                # 텍스트가 없는 경우 건너뛀
                if not sorted_texts:
                    continue
                
                # 페이지의 총 텍스트 길이 계산
                total_text = ""
                for text in sorted_texts:
                    content = text.get('text', '').strip()
                    if content:
                        total_text += content + " "
                
                # 최소 길이보다 짧은 페이지는 건너뛀
                if len(total_text) < min_page_length:
                    print(f"\t페이지 {page_number}: 텍스트 길이 {len(total_text)}자 - 최소 길이({min_page_length}자)보다 짧아서 삭제")
                    continue
                
                # 페이지 구분자 작성
                md_file.write(f"## 페이지 {page_number}\n\n")
                
                # 블록별로 그룹화
                blocks = defaultdict(list)
                for text in sorted_texts:
                    block_id = text.get('block_id', -1)
                    blocks[block_id].append(text)
                
                # 블록별로 마크다운 작성
                for block_id, texts in sorted(blocks.items()):
                    # 중복 텍스트 제거
                    seen_texts = set()
                    for text in texts:
                        label = text.get('label', '')
                        content = text.get('text', '').strip()
                        
                        # 중복 텍스트 건너뛀
                        if content in seen_texts or not content:
                            continue
                        
                        # footer 레이블은 마크다운에 포함하지 않음 (메타데이터에만 포함)
                        if label == 'footer':
                            continue
                        
                        seen_texts.add(content)
                        
                        # 텍스트 내 중복 패턴 제거
                        if len(content) > 100:  # 긴 텍스트에 대해서만 검사
                            # 반복 패턴 제거 함수 사용
                            cleaned_content = remove_repetitive_patterns(content, min_repetition)
                            if cleaned_content != content:
                                print(f"\t페이지 {page_number}: 반복 패턴 제거 - {len(content)}자 -> {len(cleaned_content)}자")
                                content = cleaned_content
                        
                        # 레이블에 따라 다른 형식으로 작성
                        if label == 'paragraph_title':
                            md_file.write(f"**{content}**\n\n")
                        else:
                            md_file.write(f"{content}\n\n")
                
                # 페이지 구분선 추가 (마지막 페이지 제외)
                if j < len(files) - 1:
                    md_file.write("---\n\n")
        
        print(f"마크다운 파일이 생성되었습니다: {md_file_path}")
    
    return len(json_files)


def load_status(status_file):
    """
    상태 파일을 로드하는 함수
    
    Args:
        status_file (str): 상태 파일 경로
        
    Returns:
        dict: 상태 정보
    """
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"상태 파일 로드 오류: {e}")
    
    return {'processed': [], 'last_update': time.time()}


def save_status(status_file, status):
    """
    상태 파일을 저장하는 함수
    
    Args:
        status_file (str): 상태 파일 경로
        status (dict): 상태 정보
    """
    status['last_update'] = time.time()
    
    try:
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"상태 파일 저장 오류: {e}")


# 스크립트 위치를 기준으로 backend/ 디렉토리
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

def main():
    """
    메인 함수
    """
    # 명령행 인수 처리
    parser = argparse.ArgumentParser(description='JSON 파일을 마크다운으로 변환하는 프로그램')
    parser.add_argument('--input-dir', '-i', required=True, help='JSON 파일이 있는 디렉토리')
    parser.add_argument('--output-dir', '-o', required=True, help='마크다운 파일을 저장할 디렉토리')
    parser.add_argument('--status-file', '-s', 
                      default=str(BASE_DIR / "nextits_data" / "Results" / "4.Pipeline_results" / "text" / "markdown_status.json"), 
                      help='상태 파일 경로')
    parser.add_argument('--skip', action='store_true', help='이미 처리된 파일 건너뛰기')
    parser.add_argument('--no-skip', dest='skip', action='store_false', help='이미 처리된 파일도 다시 처리')
    parser.add_argument('--resume', action='store_true', help='이전 작업 이어서 처리')
    parser.add_argument('--no-resume', dest='resume', action='store_false', help='처음부터 다시 처리')
    parser.add_argument('--min-page-length', type=int, default=50, help='페이지당 최소 텍스트 길이 (기본값: 50자)')
    parser.add_argument('--min-repetition', type=int, default=4, help='중복 패턴 감지를 위한 최소 반복 횟수 (기본값: 4회)')
    
    # 기본값 설정
    parser.set_defaults(skip=True, resume=True)
    
    args = parser.parse_args()
    
    # 상태 파일 로드
    status = load_status(args.status_file)
    
    # 출력 디렉토리 생성
    os.makedirs(args.output_dir, exist_ok=True)
    
    # JSON 파일 수집
    json_files = collect_sorted_json_files(args.input_dir)
    
    # 처리할 파일 필터링
    if args.skip and args.resume:
        # 이미 처리된 파일 제외
        for document_name in list(json_files.keys()):
            if document_name in status['processed']:
                print(f"이미 처리된 문서 건너뛀: {document_name}")
                del json_files[document_name]
    elif not args.resume:
        # 상태 초기화
        status['processed'] = []
    
    # 처리할 파일이 없는 경우
    if not json_files:
        print("처리할 JSON 파일이 없습니다.")
        return
    
    print(f"총 {len(json_files)}개의 문서를 처리합니다.")
    
    # JSON 파일을 마크다운으로 변환
    converted_count = json_to_markdown(json_files, args.output_dir, args.min_page_length, args.min_repetition)
    
    # 처리된 문서 업데이트
    for document_name in json_files.keys():
        if document_name not in status['processed']:
            status['processed'].append(document_name)
    
    # 상태 저장
    save_status(args.status_file, status)
    
    print(f"총 {converted_count}개의 문서가 마크다운으로 변환되었습니다.")


if __name__ == '__main__':
    main()
