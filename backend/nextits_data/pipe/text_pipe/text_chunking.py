import os
import sys
import json
import time
import argparse
import re
from datetime import datetime
from pathlib import Path
import glob
from collections import defaultdict
import ollama
import subprocess

# 기본 디렉토리 설정
BASE_MARKDOWN_DIR = '/home/nextits2/.conda/envs/workbox/image_test/nextits_data/Results/4.Pipeline_results/text/markdown'
BASE_METADATA_DIR = '/home/nextits2/.conda/envs/workbox/image_test/nextits_data/Results/4.Pipeline_results/text'
OUTPUT_DIR = '/home/nextits2/.conda/envs/workbox/image_test/nextits_data/Results/5.Completion_results/text'

# 청킹 상태를 저장할 파일 경로
STATUS_FILE = '/home/nextits2/.conda/envs/workbox/image_test/nextits_data/Results/4.Pipeline_results/text/metadata_chunking_status.json'

def load_chunking_status():
    """
    청킹 상태 파일을 로드하는 함수
    
    Returns:
        dict: 청킹 상태 정보
    """
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                status = json.load(f)
                # 리스트를 set으로 변환 (필요한 경우)
                if 'processed_files' in status and isinstance(status['processed_files'], list):
                    status['processed_files'] = set(status['processed_files'])
                return status
        except json.JSONDecodeError:
            print(f"경고: 청킹 상태 파일이 손상되었습니다. 새로 시작합니다.")
    
    # 기본 상태 정보
    return {
        'processed_files': set(),  # 처리된 파일을 set으로 초기화
        'last_processed_index': -1,
        'total_files': 0,
        'start_time': time.time(),
        'error_files': {},  # 에러 발생한 파일 정보 저장
        'errors': [],
        'processed_folders': []  # 처리된 폴더 목록 추가
    }

def save_chunking_status(status):
    """
    청킹 상태를 파일에 저장하는 함수
    
    Args:
        status (dict): 저장할 청킹 상태 정보
    """
    # 현재 시간 업데이트
    status['last_update_time'] = time.time()
    
    # JSON 직렬화를 위해 set을 list로 변환
    status_copy = {}
    for key, value in status.items():
        if isinstance(value, set):
            status_copy[key] = list(value)  # set을 list로 변환
        else:
            status_copy[key] = value
    
    # 상태 파일 디렉토리 확인 및 생성
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status_copy, f, ensure_ascii=False, indent=4)

def find_metadata_folders():
    """
    메타데이터 파일이 있는 폴더를 찾는 함수
    
    Returns:
        dict: 파일 유형별(PDF/IMG) 폴더 리스트
    """
    folders = {
        'PDF': [],
        'IMG': []
    }
    
    # PDF 폴더 검색
    pdf_dir = os.path.join(BASE_METADATA_DIR, 'PDF')
    if os.path.exists(pdf_dir):
        # 각 하위 폴더(문서별 폴더) 찾기
        for item in os.listdir(pdf_dir):
            doc_folder = os.path.join(pdf_dir, item)
            if os.path.isdir(doc_folder):
                folders['PDF'].append(doc_folder)
    
    # IMG 폴더 검색
    img_dir = os.path.join(BASE_METADATA_DIR, 'IMG')
    if os.path.exists(img_dir):
        # 각 하위 폴더(이미지별 폴더) 찾기
        for item in os.listdir(img_dir):
            img_folder = os.path.join(img_dir, item)
            if os.path.isdir(img_folder):
                folders['IMG'].append(img_folder)
    
    return folders

def find_metadata_files(folder_path):
    """
    지정된 폴더에서 메타데이터 JSON 파일을 찾는 함수
    
    Args:
        folder_path (str): 검색할 폴더 경로
        
    Returns:
        list: 발견된 메타데이터 JSON 파일 경로 목록
    """
    metadata_files = []
    
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('_metadata.json'):
                metadata_files.append(os.path.join(root, file))
    
    return metadata_files

def load_metadata_file(file_path):
    """
    메타데이터 JSON 파일을 로드하는 함수
    
    Args:
        file_path (str): JSON 파일 경로
        
    Returns:
        dict: 메타데이터 정보
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 파일 경로 정보 추가
            data['_source_path'] = file_path
            return data
    except Exception as e:
        print(f"오류: {file_path} 파일을 읽을 수 없습니다. {str(e)}")
        return None



def find_markdown_file(metadata_file):
    """
    메타데이터 파일에 해당하는 마크다운 파일을 찾는 함수
    
    Args:
        metadata_file (dict): 메타데이터 정보
        
    Returns:
        str: 마크다운 파일 경로
    """
    # 메타데이터에서 정보 추출
    metadata_info = metadata_file.get('metadata', {})
    title = metadata_info.get('title', '').strip()
    file_name = metadata_info.get('file_name', '').strip()
    
    if not title and not file_name:
        return None
    
    # 폴더명 추출
    file_path = metadata_info.get('file_path', '')
    folder_name = os.path.basename(os.path.dirname(file_path)) if file_path else ''
    
    # 마크다운 파일 경로 후보들
    candidates = []
    
    # 1. 제목으로 찾기
    if title:
        candidates.append(os.path.join(BASE_MARKDOWN_DIR, f"{title}.md"))
    
    # 2. 폴더명으로 찾기
    if folder_name:
        candidates.append(os.path.join(BASE_MARKDOWN_DIR, f"{folder_name}.md"))
    
    # 3. 파일명으로 찾기
    if file_name:
        base_name = re.sub(r'_\d+(?:_\d+)?$', '', file_name)
        candidates.append(os.path.join(BASE_MARKDOWN_DIR, f"{base_name}.md"))
        
        # 파일명에서 layout_ 접두사 제거
        if base_name.startswith('layout_'):
            clean_name = base_name.replace('layout_', '')
            candidates.append(os.path.join(BASE_MARKDOWN_DIR, f"{clean_name}.md"))
    
    # 후보 파일들 중 존재하는 파일 찾기
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    
    return None

def read_markdown_file(file_path):
    """
    마크다운 파일을 읽는 함수
    
    Args:
        file_path (str): 마크다운 파일 경로
        
    Returns:
        str: 마크다운 파일 내용
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"오류: {file_path} 파일을 읽을 수 없습니다. {str(e)}")
        return ""

def extract_page_content(markdown_content, page_num):
    """
    마크다운 내용에서 특정 페이지의 내용만 추출하는 함수
    
    Args:
        markdown_content (str): 마크다운 전체 내용
        page_num (int): 추출할 페이지 번호
        
    Returns:
        str: 해당 페이지 내용
    """
    # 페이지 구분자 찾기 (## 페이지 X)
    page_pattern = rf"## 페이지 {page_num}\s*\n"
    match = re.search(page_pattern, markdown_content)
    
    if not match:
        return ""
    
    start_pos = match.end()
    
    # 다음 페이지 찾기
    next_match = re.search(rf"## 페이지 {page_num+1}\s*\n", markdown_content)
    end_pos = next_match.start() if next_match else len(markdown_content)
    
    return markdown_content[start_pos:end_pos].strip()

def extract_content(markdown_content):
    """
    마크다운 내용에서 페이지 구분자를 제거하고 전체 내용을 추출하는 함수
    
    Args:
        markdown_content (str): 마크다운 내용
        
    Returns:
        str: 페이지 구분자가 제거된 내용
    """
    # 페이지 구분자 제거
    content = re.sub(r'\n---\n', '\n', markdown_content)
    
    # 페이지 헤더 제거 (## 페이지 X)
    content = re.sub(r'## 페이지 \d+', '', content)
    
    # 페이지 구분자 제거 (### 페이지)
    content = re.sub(r'### 페이지.*?\n', '', content)
    
    # 연속된 빈 줄 제거
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
    
    return content.strip()

def remove_duplicated_sentences(text):
    """
    반복되는 문장을 하나로 처리하는 함수
    
    Args:
        text (str): 원본 텍스트
        
    Returns:
        str: 중복 문장이 제거된 텍스트
    """
    # 문장 단위로 분리
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    # 중복 문장 제거
    unique_sentences = []
    for sentence in sentences:
        sentence = sentence.strip()
        if sentence and sentence not in unique_sentences:
            unique_sentences.append(sentence)
    
    return ' '.join(unique_sentences)

def split_text_into_manageable_chunks(text, max_chunk_size=3000):
    """
    긴 텍스트를 처리 가능한 크기의 청크로 나누는 함수
    
    Args:
        text (str): 원본 텍스트
        max_chunk_size (int): 최대 청크 크기(문자 수)
        
    Returns:
        list: 처리 가능한 크기의 텍스트 청크 목록
    """
    if not text or len(text) <= max_chunk_size:
        return [text] if text else []
    
    # 문장 단위로 분리
    chunks = []
    current_chunk = ""
    
    # 문단 단위로 분리
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        # 문단이 최대 크기보다 크면 문장 단위로 분리
        if len(paragraph) > max_chunk_size:
            sentences = re.split(r'(?<=[.!?])\s+', paragraph)
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 2 <= max_chunk_size:
                    if current_chunk:
                        current_chunk += " " + sentence
                    else:
                        current_chunk = sentence
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence
        else:
            # 문단이 청크에 추가될 수 있는지 확인
            if len(current_chunk) + len(paragraph) + 4 <= max_chunk_size:
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = paragraph
    
    # 마지막 청크 추가
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

def semantic_chunking(text, model_name="qwen3:4b", chunk_size_range=(1000, 2000)):
    """
    텍스트를 시맨틱 청킹하는 함수
    
    Args:
        text (str): 청킹할 텍스트 내용
        model_name (str): 사용할 모델 이름
        chunk_size_range (tuple): 청크 크기 범위
        
    Returns:
        list: 청크 목록
    """
    if not text:
        return []
    
    # 청크 크기 설정
    min_size, max_size = chunk_size_range
    
    # 텍스트가 이미 작은 경우 그대로 반환
    if len(text) <= max_size:
        return [text]
    
    try:
        # 텍스트 길이 확인 및 로깅
        print(f"청킹할 텍스트 길이: {len(text)} 문자")
        
        # 시맨틱 청킹 프롬프트
        prompt = f"""
        당신은 문서를 의미론적으로 일관된 청크로 나누는 전문가입니다.
        입력받은 텍스트를 {min_size}~{max_size}자 범위 내에서 의미적으로 완결된 청크로 나누어 주세요.
        
        고품질 시맨틱 청킹을 위한 지침:
        1. 문맥의 흐름이 자연스럽게 이어지도록 청킹하세요. 문장이나 단락이 의미적으로 끊기지 않도록 주의하세요.
        2. 같은 주제나 개념을 다루는 내용은 가능한 한 같은 청크에 포함시키세요.
        3. 표, 그래프, 차트에 대한 설명은 반드시 관련 설명과 함께 같은 청크에 포함시키세요.
        4. 목록(리스트)은 관련 항목끼리 함께 그룹화하고, 가능하면 목록의 소개 문장도 포함시키세요.
        5. 각 청크는 독립적으로 이해할 수 있을 만큼 충분한 문맥을 포함해야 합니다.
        6. 청크 간 중복되는 내용은 최소화하되, 중요한 문맥 정보는 필요시 중복을 허용하세요.
        7. 페이지 번호나 문서 구조를 나타내는 메타데이터는 관련 내용과 함께 유지하세요.
        8. 제목과 그에 해당하는 내용은 가능한 한 같은 청크에 포함시키세요.
        
        입력 텍스트:
        ```
        {text[:5000] + '...' if len(text) > 5000 else text}
        ```
        
        출력 형식:
        청크 1:
        [청크 내용]
        
        청크 2:
        [청크 내용]
        
        ...
        """
        
        try:
            # Ollama API 호출 시도
            print(f"Ollama API 호출 시작 (모델: {model_name})...")
            response = ollama.chat(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=False
            )
            print("Ollama API 호출 성공")
            
            # 응답 텍스트
            response_text = response['message']['content']
            
            # 청크 추출
            chunks = []
            pattern = r'청크 \d+:\s*\n([\s\S]*?)(?=\n\s*청크 \d+:|$)'
            
            matches = re.finditer(pattern, response_text)
            for match in matches:
                chunk_text = match.group(1).strip()
                if chunk_text:
                    chunks.append(chunk_text)
            
            # 청크가 추출되지 않은 경우 기본 분할 방법 사용
            if not chunks:
                print("시맨틱 청킹 실패: 청크를 추출할 수 없습니다. 기본 분할 방법으로 대체합니다.")
                chunks = split_text_into_manageable_chunks(text, max_chunk_size=max_size)
            else:
                print(f"시맨틱 청킹 성공: {len(chunks)}개의 청크가 생성되었습니다.")
            
            return chunks
            
        except ImportError:
            print("Ollama 패키지를 찾을 수 없습니다. 기본 분할 방법으로 대체합니다.")
            return split_text_into_manageable_chunks(text, max_chunk_size=max_size)
        except ConnectionError:
            print("Ollama 서버에 연결할 수 없습니다. 기본 분할 방법으로 대체합니다.")
            return split_text_into_manageable_chunks(text, max_chunk_size=max_size)
        
    except Exception as e:
        print(f"시맨틱 청킹 중 오류 발생: {str(e)}")
        import traceback
        print(f"상세 오류: {traceback.format_exc()}")
        # 오류 발생 시 기본 분할 방법 사용
        return split_text_into_manageable_chunks(text, max_chunk_size=chunk_size_range[1])


def extract_keywords(text, model_name="qwen3:4b", max_keywords=5):
    """
    텍스트에서 키워드를 추출하는 함수
    
    Args:
        text (str): 키워드를 추출할 텍스트 (시맨틱 청킹된 텍스트)
        model_name (str): 사용할 모델 이름
        max_keywords (int): 추출할 최대 키워드 수
        
    Returns:
        list: 추출된 키워드 목록
    """
    if not text or len(text.strip()) < 10:
        return []
    
    try:
        # 키워드 추출 프롬프트 - 명확하고 직접적인 지시로 개선
        prompt = f"""
        당신은 텍스트 분석 전문가입니다. 다음 텍스트에서 핵심 키워드를 추출해주세요.
        
        지시사항:
        1. 텍스트를 분석하여 핵심 키워드를 최소 1개에서 최대 {max_keywords}개 추출하세요.
        2. 키워드는 반드시 한국어 명사형으로만 작성하세요.
        3. 키워드는 콤마(,)로만 구분하여 나열하세요.
        4. 키워드만 나열하고 다른 설명이나 문장을 추가하지 마세요.
        5. 내부 사고 과정이나 분석 과정을 출력하지 마세요.
        6. 영어 단어는 사용하지 말고 한국어로만 작성하세요.
        
        텍스트:
        ```
        {text}
        ```
        
        키워드:
        """
        
        # Ollama API 호출
        response = ollama.chat(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )
        
        # 응답 텍스트에서 키워드 추출
        keywords_text = response['message']['content'].strip()
        print(f"모델 응답: '{keywords_text}'")
        
        # <think> 태그 및 내부 내용 완전히 제거
        keywords_text = re.sub(r'<think>.*?</think>', '', keywords_text, flags=re.DOTALL)
        # 닫는 태그 없이 <think>로 시작하는 경우도 처리
        keywords_text = re.sub(r'<think>.*?$', '', keywords_text, flags=re.DOTALL)
        
        # 콤마로 구분된 키워드 분리
        keywords = []
        for k in re.split(r'[,，、]', keywords_text):
            k = k.strip()
            if k:
                keywords.append(k)
        
        # 중복 제거 및 최대 개수 제한
        unique_keywords = []
        for kw in keywords:
            if kw not in unique_keywords and len(unique_keywords) < max_keywords:
                unique_keywords.append(kw)
        
        print(f"추출된 키워드: {', '.join(unique_keywords)}")
        return unique_keywords
        
    except Exception as e:
        print(f"키워드 추출 중 오류 발생: {str(e)}")
        return []  # 오류 발생 시 빈 리스트 반환


def process_metadata_group(group, model_name="qwen3:4b"):
    """
    그룹화된 메타데이터를 처리하는 함수
    
    Args:
        group (list): 처리할 메타데이터 그룹
        model_name (str): 사용할 모델 이름
        
    Returns:
        list: 업데이트된 메타데이터 목록
    """
    if not group:
        return []
    
    # 그룹을 페이지 번호 순서대로 정렬
    group.sort(key=lambda x: int(x.get('metadata', {}).get('page_num', '0')) if x.get('metadata', {}).get('page_num', '0').isdigit() else 0)
    
    # 그룹에서 첫 번째 메타데이터 기준으로 정보 추출
    first_metadata = group[0]
    metadata_info = first_metadata.get('metadata', {})
    
    # 파일 이름 및 경로 추출
    title = metadata_info.get('title', 'unknown')
    file_path = metadata_info.get('file_path', '')
    folder_name = os.path.basename(os.path.dirname(file_path)) if file_path else ''
    
    # 마크다운 파일 경로 찾기
    markdown_path = find_markdown_file(first_metadata)
    if not markdown_path:
        print(f"경고: '{title}' 문서에 해당하는 마크다운 파일을 찾을 수 없습니다.")
        return group
    
    # 마크다운 내용 읽기
    markdown_content = read_markdown_file(markdown_path)
    if not markdown_content:
        print(f"경고: '{markdown_path}' 마크다운 파일이 비어 있거나 읽을 수 없습니다.")
        return group
    
    # 메타데이터에 해당하는 내용 추출 및 페이지 번호 추적
    all_texts = []
    page_numbers = []
    
    for metadata in group:
        page_num_str = metadata.get('metadata', {}).get('page_num', '0')
        try:
            page_num = int(page_num_str)
            if page_num > 0:
                page_content = extract_page_content(markdown_content, page_num)
                if page_content:
                    all_texts.append(page_content)
                    page_numbers.append(page_num)
        except ValueError:
            # 페이지 번호가 이미 범위 형식인 경우 처리
            pass
    
    # 페이지 범위 계산
    if page_numbers:
        page_numbers.sort()
        if len(page_numbers) == 1:
            page_range = f"{page_numbers[0]:03d}"
        else:
            page_range = f"{page_numbers[0]:03d}-{page_numbers[-1]:03d}"
    else:
        page_range = "000"
    
    # 모든 텍스트 내용 결합
    combined_text = '\n\n'.join(all_texts)
    clean_text = remove_duplicated_sentences(combined_text)
    
    # 시맨틱 청킹 수행
    chunks = semantic_chunking(clean_text, model_name=model_name)
    
    # 각 청크에 대한 키워드 추출 및 메타데이터 업데이트
    updated_metadata = []
    
    # 청크가 없는 경우 원본 그대로 반환
    if not chunks:
        return group
    
    # 청크가 하나인 경우 모든 메타데이터에 동일한 내용 적용
    if len(chunks) == 1:
        # 청킹된 텍스트 저장
        chunk_text = chunks[0]
        
        # 키워드 추출 - 최소 1개에서 최대 5개 키워드 추출
        print(f"청크 텍스트에서 키워드 추출 중... (텍스트 길이: {len(chunk_text)} 문자)")
        keywords = extract_keywords(chunk_text, model_name=model_name, max_keywords=5)
        print(f"추출된 키워드: {', '.join(keywords)}")
        
        # 첫 번째 메타데이터만 업데이트하고 나머지는 건너뛰기
        metadata_copy = json.loads(json.dumps(first_metadata))  # 딥 카피
        metadata_copy['metadata']['text'] = chunk_text
        metadata_copy['metadata']['tags'] = keywords
        metadata_copy['metadata']['page_num'] = page_range  # 페이지 범위 업데이트
        updated_metadata.append(metadata_copy)
    
    # 청크가 여러 개인 경우 각 청크별로 메타데이터 생성
    else:
        for i, chunk in enumerate(chunks):
            # 청크 정보 출력
            print(f"청크 {i+1}/{len(chunks)} 처리 중... (텍스트 길이: {len(chunk)} 문자)")
            
            # 키워드 추출 - 최소 1개에서 최대 5개 키워드 추출
            keywords = extract_keywords(chunk, model_name=model_name, max_keywords=5)
            print(f"청크 {i+1} 키워드: {', '.join(keywords)}")
            
            # 첫 번째 메타데이터를 기반으로 새 메타데이터 생성
            metadata_copy = json.loads(json.dumps(first_metadata))  # 딥 카피
            metadata_copy['metadata']['text'] = chunk
            metadata_copy['metadata']['tags'] = keywords
            metadata_copy['metadata']['page_num'] = page_range  # 페이지 범위 업데이트
            
            # 청크 번호를 ID에 추가
            if 'id' in metadata_copy['metadata']:
                base_id = metadata_copy['metadata']['id'].split('_')[0]
                metadata_copy['metadata']['id'] = f"{base_id}_text_chunk{i+1}"
            
            updated_metadata.append(metadata_copy)
    
    return updated_metadata

def update_metadata_files(metadata_list):
    """
    메타데이터 파일들을 업데이트하는 함수
    
    Args:
        metadata_list (list): 업데이트할 메타데이터 목록
        
    Returns:
        list: 업데이트된 메타데이터 파일 경로 목록
    """
    updated_files = []
    
    for metadata in metadata_list:
        # 원본 파일 경로 추출
        source_path = metadata.pop('_source_path', None)
        if not source_path:
            continue
        
        try:
            # 파일명에서 메타데이터 부분 추출
            file_name = os.path.basename(source_path)
            base_name = file_name.replace('_metadata.json', '')
            
            # 파일 경로에서 폴더명 추출
            folder_name = os.path.basename(os.path.dirname(source_path))
            
            # 새 파일 경로 생성
            output_folder = os.path.join(OUTPUT_DIR, folder_name)
            os.makedirs(output_folder, exist_ok=True)
            
            # 청킹된 메타데이터 파일 저장
            output_path = os.path.join(output_folder, f"{base_name}_chunked_metadata.json")
            
            # 파일 저장
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=4)
            
            # 파일 경로 업데이트 (필요한 경우)
            if 'metadata' in metadata and 'file_path' in metadata['metadata']:
                metadata['metadata']['file_path'] = output_path
            
            updated_files.append(output_path)
            
        except Exception as e:
            print(f"메타데이터 파일 업데이트 중 오류 발생: {source_path} - {str(e)}")
    
    return updated_files

def save_combined_metadata(all_metadata, output_name="combined_metadata.json"):
    """
    모든 메타데이터를 하나의 파일로 통합하여 저장하는 함수
    
    Args:
        all_metadata (list): 통합할 모든 메타데이터 목록
        output_name (str): 출력 파일 이름
        
    Returns:
        str: 통합 메타데이터 파일 경로
    """
    # 출력 디렉토리 생성
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 출력 파일 경로
    output_path = os.path.join(OUTPUT_DIR, output_name)
    
    # 메타데이터에서 _source_path 제거
    clean_metadata = []
    for metadata in all_metadata:
        metadata_copy = json.loads(json.dumps(metadata))
        if '_source_path' in metadata_copy:
            del metadata_copy['_source_path']
        clean_metadata.append(metadata_copy)
    
    # 파일 저장
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(clean_metadata, f, ensure_ascii=False, indent=4)
        print(f"통합 메타데이터 파일이 생성되었습니다: {output_path}")
        return output_path
    except Exception as e:
        print(f"통합 메타데이터 파일 생성 중 오류 발생: {str(e)}")
        return None

def folder_type(folder_path):
    """
    폴더 경로에서 파일 유형(PDF/IMG)을 판별하는 함수
    
    Args:
        folder_path (str): 폴더 경로
        
    Returns:
        str: 파일 유형 (PDF 또는 IMG)
    """
    if '/PDF/' in folder_path:
        return 'PDF'
    elif '/IMG/' in folder_path:
        return 'IMG'
    else:
        return '불명'

def main(model_name="qwen3:4b", output_name="combined_metadata.json", reset=False):
    """
    메타데이터 청킹 프로세스를 실행하는 메인 함수
    
    Args:
        model_name (str): 시맨틱 청킹에 사용할 모델 이름
        output_name (str): 출력 통합 메타데이터 파일 이름
        reset (bool): 처리 상태를 초기화하고 모든 파일을 다시 처리할지 여부
        
    Returns:
        str: 통합 메타데이터 파일 경로
    """
    print(f"[{datetime.now()}] 메타데이터 청킹 프로세스를 시작합니다...")
    print(f"- 사용 모델: {model_name}")
    
    # 결과 저장 경로
    output_dir = OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    print(f"- 결과 저장 경로: {output_dir}")
    
    # 처리 상태 로드
    status = load_chunking_status()
    
    # processed_folders가 없으면 초기화
    if 'processed_folders' not in status:
        status['processed_folders'] = []
    
    # 메타데이터 폴더 찾기
    print(f"[{datetime.now()}] 메타데이터 폴더 검색 중...")
    folders = find_metadata_folders()
    pdf_folders = folders['PDF']
    img_folders = folders['IMG']
    print(f"PDF 폴더 {len(pdf_folders)}개, IMG 폴더 {len(img_folders)}개를 찾았습니다.\n")
    
    # 모든 폴더 처리
    all_folders = pdf_folders + img_folders
    all_metadata = []
    all_updated_metadata = []
    
    for i, folder_path in enumerate(all_folders, 1):
        folder_name = os.path.basename(folder_path)
        print(f"[{datetime.now()}] {folder_type(folder_path)} 폴더 처리 중 ({i}/{len(all_folders)}): {folder_name}")
        
        # 이미 처리된 폴더 건너뛰기
        if folder_name in status.get('processed_folders', []) and not reset:
            print(f"{folder_name} 폴더는 이미 처리되었습니다. 건너뛰니다.")
            # 이전에 처리된 메타데이터 로드
            folder_output_path = os.path.join(output_dir, f"{folder_name}_metadata.json")
            if os.path.exists(folder_output_path):
                try:
                    with open(folder_output_path, 'r', encoding='utf-8') as f:
                        folder_metadata = json.load(f)
                        all_metadata.extend(folder_metadata)
                    print(f"{folder_name} 폴더의 기존 메타데이터를 로드했습니다.")
                except Exception as e:
                    print(f"{folder_name} 폴더의 기존 메타데이터 로드 중 오류: {str(e)}")
            continue
        
        # 메타데이터 파일 찾기
        metadata_files = find_metadata_files(folder_path)
        print(f"{folder_name} 폴더에서 {len(metadata_files)}개의 메타데이터 파일을 찾았습니다.")
        
        if not metadata_files:
            continue
        
        # 메타데이터 파일 로드
        print(f"[{datetime.now()}] {folder_name} 메타데이터 파일 로드 중...")
        metadata_list = []
        for file_path in metadata_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    metadata_list.append(metadata)
            except Exception as e:
                print(f"경고: '{file_path}' 파일 로드 중 오류 발생: {str(e)}")
        
        print(f"총 {len(metadata_list)}개의 메타데이터 파일을 로드했습니다.")
        
        # 메타데이터를 페이지 순서대로 정렬
        print(f"[{datetime.now()}] {folder_name} 메타데이터를 페이지 순서대로 정렬 중...")
        metadata_list.sort(key=lambda x: int(x.get('metadata', {}).get('page_num', '0')) if x.get('metadata', {}).get('page_num', '0').isdigit() else 0)
        
        # 페이지 번호가 없거나 유효하지 않은 메타데이터 필터링
        filtered_metadata_list = []
        for metadata in metadata_list:
            page_num_str = metadata.get('metadata', {}).get('page_num', '0')
            if page_num_str and page_num_str.isdigit() and int(page_num_str) > 0:
                filtered_metadata_list.append(metadata)
            else:
                print(f"경고: 페이지 번호가 없거나 유효하지 않은 메타데이터를 건너뜁니다. (페이지: {page_num_str})")
        
        print(f"유효한 페이지가 있는 메타데이터 {len(filtered_metadata_list)}개를 처리합니다.")
        
        # 메타데이터 처리
        print(f"[{datetime.now()}] {folder_name} 메타데이터 처리 중...")
        folder_metadata = []
        
        # 각 페이지를 개별적으로 처리
        for i, metadata in enumerate(filtered_metadata_list, 1):
            # 메타데이터 정보 출력
            page_num = metadata.get('metadata', {}).get('page_num', '0')
            index = metadata.get('metadata', {}).get('index', 'null')
            print(f"{folder_name} 페이지 {i}/{len(filtered_metadata_list)} 처리 중... (인덱스: {index}, 페이지: {page_num})")
            
            # 개별 페이지 처리
            processed_metadata = process_metadata_group([metadata], model_name=model_name)
            folder_metadata.extend(processed_metadata)
        
        # 폴더별 메타데이터 저장
        folder_output_path = os.path.join(output_dir, f"{folder_name}_metadata.json")
        with open(folder_output_path, 'w', encoding='utf-8') as f:
            json.dump(folder_metadata, f, ensure_ascii=False, indent=2)
        print(f"{folder_name} 폴더의 메타데이터를 저장했습니다: {folder_output_path}")
        
        # 폴더별 처리 결과 저장
        print(f"[{datetime.now()}] {folder_name} 처리된 메타데이터 저장 중...")
        
        # folder_updated_metadata 변수 정의 (이전에 정의되지 않았음)
        folder_updated_metadata = folder_metadata
        
        # 개별 파일 업데이트
        updated_files = update_metadata_files(folder_updated_metadata)
        print(f"{folder_name} 폴더에서 {len(updated_files)}개의 메타데이터 파일이 업데이트되었습니다.")
        
        # 폴더별 통합 파일 저장
        folder_output_name = f"{folder_name}_metadata.json"
        folder_combined_file_path = save_combined_metadata(folder_updated_metadata, output_name=folder_output_name)
        print(f"{folder_name} 폴더 통합 메타데이터 파일 저장됨: {folder_combined_file_path}")
        
        # 처리된 폴더 목록에 추가
        if folder_name not in status['processed_folders']:
            status['processed_folders'].append(folder_name)
        
        # 전체 메타데이터에 추가
        all_updated_metadata.extend(folder_updated_metadata)
        
        # 상태 저장
        save_chunking_status(status)
    
    # 전체 처리 결과 저장
    print(f"\n[{datetime.now()}] 전체 처리된 메타데이터 저장 중...")
    
    # 전체 통합 파일 저장
    combined_file_path = save_combined_metadata(all_updated_metadata, output_name=output_name)
    print(f"전체 통합 메타데이터 파일 저장됨: {combined_file_path}")
    
    # 상태 최종 저장
    save_chunking_status(status)
    
    # 결과 반환
    return combined_file_path

if __name__ == "__main__":
    import argparse
    
    # 명령행 인자 처리
    parser = argparse.ArgumentParser(description="메타데이터 파일을 시맨틱 청킹하고 통합하는 스크립트")
    parser.add_argument("--model", default="qwen3:4b", help="시맨틱 청킹에 사용할 Ollama 모델 이름 (기본값: qwen3:4b)")
    parser.add_argument("--output", default="combined_metadata.json", help="출력 통합 메타데이터 파일 이름 (기본값: combined_metadata.json)")
    parser.add_argument("--reset", action="store_true", help="처리 상태를 초기화하고 모든 파일을 다시 처리")
    
    args = parser.parse_args()
    
    # 상태 초기화 옵션 처리
    if args.reset:
        print("처리 상태를 초기화합니다. 모든 파일을 다시 처리합니다.")
        if os.path.exists(STATUS_FILE):
            os.remove(STATUS_FILE)
    
    # 메인 함수 실행
    result_path = main(model_name=args.model, output_name=args.output, reset=args.reset)
    
    if result_path:
        print(f"메타데이터 청킹 프로세스가 성공적으로 완료되었습니다.")
        print(f"결과 파일: {result_path}")
    else:
        print("메타데이터 청킹 프로세스 중 오류가 발생했습니다.")
        sys.exit(1)
