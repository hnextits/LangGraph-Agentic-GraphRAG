"""
Markdown Document Parser
MD 파일을 파싱하고 전처리하는 모듈
"""

import re
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger
import markdown
from bs4 import BeautifulSoup


class MDParser:
    """마크다운 문서 파서"""
    
    def __init__(self):
        self.md = markdown.Markdown(extensions=['extra', 'codehilite'])
    
    def read_file(self, file_path: str) -> str:
        """
        MD 파일을 읽어서 텍스트 반환
        
        Args:
            file_path: MD 파일 경로
            
        Returns:
            str: 파일 내용
        """
        try:
            path = Path(file_path)
            if not path.exists():
                logger.error(f"파일을 찾을 수 없습니다: {file_path}")
                return ""
            
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            logger.info(f"파일 읽기 성공: {file_path} ({len(content)} 문자)")
            return content
            
        except Exception as e:
            logger.error(f"파일 읽기 오류 ({file_path}): {e}")
            return ""
    
    def clean_text(self, text: str) -> str:
        """
        텍스트 정리 (불필요한 공백, 특수문자 제거)
        
        Args:
            text: 원본 텍스트
            
        Returns:
            str: 정리된 텍스트
        """
        # 연속된 공백을 하나로
        text = re.sub(r'\s+', ' ', text)
        
        # 연속된 줄바꿈을 최대 2개로
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 앞뒤 공백 제거
        text = text.strip()
        
        return text
    
    def extract_metadata(self, content: str) -> Dict[str, any]:
        """
        MD 파일에서 메타데이터 추출 (YAML front matter)
        
        Args:
            content: MD 파일 내용
            
        Returns:
            dict: 메타데이터
        """
        metadata = {}
        
        # YAML front matter 패턴 (---)
        yaml_pattern = r'^---\s*\n(.*?)\n---\s*\n'
        match = re.match(yaml_pattern, content, re.DOTALL)
        
        if match:
            yaml_content = match.group(1)
            # 간단한 key: value 파싱
            for line in yaml_content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip()] = value.strip()
        
        return metadata
    
    def extract_headers(self, content: str) -> List[Dict[str, str]]:
        """
        MD 파일에서 헤더 추출
        
        Args:
            content: MD 파일 내용
            
        Returns:
            list: 헤더 정보 리스트 [{"level": 1, "text": "제목"}]
        """
        headers = []
        
        # 헤더 패턴 (# ~ ######)
        header_pattern = r'^(#{1,6})\s+(.+)$'
        
        for line in content.split('\n'):
            match = re.match(header_pattern, line)
            if match:
                level = len(match.group(1))
                text = match.group(2).strip()
                headers.append({"level": level, "text": text})
        
        return headers
    
    def chunk_text(self, text: str, chunk_size: int = 3600, overlap: int = 200) -> List[str]:
        """
        텍스트를 청크로 분할 (기존 시스템의 chunk_len과 동일)
        
        Args:
            text: 원본 텍스트
            chunk_size: 청크 크기 (문자 수)
            overlap: 청크 간 오버랩 크기
            
        Returns:
            list: 청크 리스트
        """
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            
            # 마지막 청크가 아니면 문장 경계에서 자르기
            if end < len(text):
                # 마침표, 느낌표, 물음표 뒤에서 자르기
                sentence_end = max(
                    text.rfind('.', start, end),
                    text.rfind('!', start, end),
                    text.rfind('?', start, end),
                    text.rfind('\n', start, end)
                )
                
                if sentence_end > start:
                    end = sentence_end + 1
            
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            # 다음 시작 위치 (오버랩 적용)
            start = end - overlap if end < len(text) else end
        
        logger.info(f"텍스트를 {len(chunks)}개 청크로 분할 (청크 크기: {chunk_size}, 오버랩: {overlap})")
        return chunks
    
    def parse_structured_content(self, content: str) -> Dict[str, any]:
        """
        MD 파일을 구조화된 형태로 파싱
        
        Args:
            content: MD 파일 내용
            
        Returns:
            dict: 구조화된 데이터
        """
        return {
            "metadata": self.extract_metadata(content),
            "headers": self.extract_headers(content),
            "content": self.clean_text(content),
            "length": len(content)
        }
    
    def convert_to_plain_text(self, md_content: str) -> str:
        """
        마크다운을 일반 텍스트로 변환 (HTML 태그 제거)
        
        Args:
            md_content: 마크다운 내용
            
        Returns:
            str: 일반 텍스트
        """
        # 마크다운을 HTML로 변환
        html = self.md.convert(md_content)
        
        # HTML 태그 제거
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text()
        
        # 정리
        text = self.clean_text(text)
        
        return text
    
    def batch_read_files(self, file_paths: List[str]) -> List[Dict[str, str]]:
        """
        여러 파일을 배치로 읽기
        
        Args:
            file_paths: 파일 경로 리스트
            
        Returns:
            list: [{"path": "...", "content": "..."}]
        """
        results = []
        
        for file_path in file_paths:
            content = self.read_file(file_path)
            if content:
                results.append({
                    "path": file_path,
                    "filename": Path(file_path).name,
                    "content": content
                })
        
        logger.info(f"배치 파일 읽기 완료: {len(results)}/{len(file_paths)} 성공")
        return results
