# Qwen/Qwen3-Embedding-4B Late Chunking with FAISS
# MD파일 처리 → Late Chunking → Vector DB 저장 전용 모듈
# python /home/jeonghs/workspace/nextitslm/backend/notebooklm/qwen3_late_chunking.py --input-file /home/jeonghs/workspace/nextitslm/backend/nextits_data/Results/3.OCR_results/원가관리회계.md --index-path /home/jeonghs/workspace/nextitslm/backend/notebooklm/faiss_test/text_index.faiss


import os
import re
import json
import logging
from typing import List, Dict, Tuple, Optional, Union, Any
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel
import markdown
from bs4 import BeautifulSoup
import argparse
from tqdm import tqdm
import pickle
from datetime import datetime
import hashlib
import uuid
import faiss

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ChunkInfo:
    """청크 정보 구조체"""
    chunk_id: str
    text: str
    raw_text: str  # LaTeX/HTML 포함 원본 텍스트
    start_pos: int
    end_pos: int
    token_start: int
    token_end: int
    chunk_index: int
    document_id: str
    content_type: str  # 'text', 'latex', 'table', 'code', 'mixed'
    metadata: Dict[str, Any]

@dataclass
class VectorEntry:
    """벡터 저장 엔트리"""
    id: str
    document_id: str
    chunk_id: str
    text: str
    raw_text: str
    embedding: np.ndarray
    content_type: str
    metadata: Dict[str, Any]
    created_at: datetime

class MixedContentProcessor:
    """LaTeX + HTML 테이블 + 텍스트 혼합 콘텐츠 처리기"""
    
    def __init__(self):
        self.md_parser = markdown.Markdown(extensions=[
            'fenced_code',
            'tables',
            'toc',
            'codehilite',
            'attr_list',
            'def_list',
            'footnotes'
        ])
        
        # 콘텐츠 타입별 패턴 정의
        self.latex_patterns = {
            'inline_paren': re.compile(r'\\\((.*?)\\\)', re.DOTALL),
            'inline_dollar': re.compile(r'\$([^$]+)\$'),
            'display_bracket': re.compile(r'\\\[(.*?)\\\]', re.DOTALL),
            'display_dollar': re.compile(r'\$\$(.*?)\$\$', re.DOTALL),
            'equation': re.compile(r'\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}', re.DOTALL),
            'align': re.compile(r'\\begin\{align\*?\}(.*?)\\end\{align\*?\}', re.DOTALL),
            'array': re.compile(r'\\begin\{array\}(.*?)\\end\{array\}', re.DOTALL),
            'matrix': re.compile(r'\\begin\{(?:matrix|pmatrix|bmatrix|vmatrix)\}(.*?)\\end\{(?:matrix|pmatrix|bmatrix|vmatrix)\}', re.DOTALL)
        }
        
        self.table_pattern = re.compile(r'<table.*?</table>', re.DOTALL | re.IGNORECASE)
        self.code_pattern = re.compile(r'```.*?```', re.DOTALL)
        self.header_pattern = re.compile(r'^#{1,6}\s+(.+)$', re.MULTILINE)
        
    def identify_content_type(self, text: str) -> str:
        """텍스트 청크의 주요 콘텐츠 타입 식별"""
        # 각 콘텐츠 타입별 매치 개수 계산
        latex_count = sum(len(pattern.findall(text)) for pattern in self.latex_patterns.values())
        table_count = len(self.table_pattern.findall(text))
        code_count = len(self.code_pattern.findall(text))
        
        total_special = latex_count + table_count + code_count
        text_length = len(text)
        
        # 특수 콘텐츠 비율 계산
        if total_special == 0:
            return 'text'
        
        special_ratio = total_special / max(1, text_length / 100)  # 100자당 특수 콘텐츠 비율
        
        if latex_count > table_count and latex_count > code_count:
            return 'latex' if special_ratio > 0.3 else 'mixed'
        elif table_count > 0:
            return 'table'
        elif code_count > 0:
            return 'code'
        else:
            return 'mixed'
    
    def extract_latex_expressions(self, text: str) -> List[Dict]:
        """LaTeX 수식 추출"""
        expressions = []
        
        for pattern_type, pattern in self.latex_patterns.items():
            for match in pattern.finditer(text):
                expressions.append({
                    'type': pattern_type,
                    'content': match.group(0),
                    'inner_content': match.group(1) if match.groups() else match.group(0),
                    'start': match.start(),
                    'end': match.end(),
                    'length': len(match.group(0))
                })
        
        return sorted(expressions, key=lambda x: x['start'])
    
    def extract_tables(self, text: str) -> List[Dict]:
        """HTML 테이블 추출 및 파싱"""
        tables = []
        
        for match in self.table_pattern.finditer(text):
            soup = BeautifulSoup(match.group(0), 'html.parser')
            table = soup.find('table')
            
            if table:
                rows = []
                headers = []
                
                # 헤더 추출
                header_row = table.find('tr')
                if header_row:
                    headers = [th.get_text().strip() for th in header_row.find_all(['th', 'td'])]
                
                # 모든 행 추출
                for tr in table.find_all('tr'):
                    row = [td.get_text().strip() for td in tr.find_all(['td', 'th'])]
                    if row:  # 빈 행 제외
                        rows.append(row)
                
                tables.append({
                    'content': match.group(0),
                    'headers': headers,
                    'rows': rows,
                    'start': match.start(),
                    'end': match.end(),
                    'row_count': len(rows),
                    'col_count': len(headers) if headers else (len(rows[0]) if rows else 0)
                })
        
        return tables
    
    def extract_code_blocks(self, text: str) -> List[Dict]:
        """코드 블록 추출"""
        code_blocks = []
        
        for match in self.code_pattern.finditer(text):
            content = match.group(0)
            # 언어 추출 (```python 형태)
            language = ''
            if content.startswith('```'):
                first_line = content.split('\n')[0]
                language = first_line[3:].strip()
            
            code_blocks.append({
                'content': content,
                'language': language,
                'start': match.start(),
                'end': match.end(),
                'length': len(content)
            })
        
        return code_blocks
    
    def process_markdown(self, file_path: str) -> Dict[str, Any]:
        """마크다운 파일 처리 및 구조화된 콘텐츠 분석"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 다양한 콘텐츠 타입 추출
        latex_expressions = self.extract_latex_expressions(content)
        tables = self.extract_tables(content)
        code_blocks = self.extract_code_blocks(content)
        
        # HTML 변환 (구조화된 파싱용)
        html = self.md_parser.convert(content)
        soup = BeautifulSoup(html, 'html.parser')
        
        # 섹션별 처리
        processed_sections = []
        
        # 헤더 구조 분석
        headers = self._extract_headers(content)
        
        # 각 요소 처리
        for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'pre', 'blockquote', 'table', 'div']):
            section_text = element.get_text().strip()
            if not section_text:
                continue
            
            # 원본 텍스트에서 해당 부분 찾기
            raw_text = self._find_raw_text(content, section_text, element.name)
            
            # 콘텐츠 타입 결정
            content_type = self.identify_content_type(raw_text)
            
            # 요소별 처리
            if element.name.startswith('h'):
                level = int(element.name[1])
                processed_text = f"{'#' * level} {section_text}"
                content_type = 'text'  # 헤더는 텍스트로 분류
            elif element.name == 'pre':
                processed_text = f"```\n{section_text}\n```"
                content_type = 'code'
            elif element.name == 'blockquote':
                processed_text = f"> {section_text}"
            elif element.name == 'table':
                processed_text = self._process_table_text(element)
                content_type = 'table'
            else:
                processed_text = section_text
            
            # 메타데이터 구성
            metadata = {
                'element_type': element.name,
                'length': len(processed_text),
                'has_latex': len(self.latex_patterns['inline_paren'].findall(raw_text)) > 0,
                'has_table': 'table' in element.name.lower(),
                'has_code': 'pre' in element.name.lower() or '```' in raw_text
            }
            
            processed_sections.append({
                'text': processed_text,
                'raw_text': raw_text,
                'content_type': content_type,
                'element_type': element.name,
                'metadata': metadata
            })
        
        return {
            'sections': processed_sections,
            'latex_expressions': latex_expressions,
            'tables': tables,
            'code_blocks': code_blocks,
            'headers': headers,
            'raw_content': content,
            'total_sections': len(processed_sections),
            'content_stats': self._calculate_content_stats(processed_sections)
        }
    
    def _extract_headers(self, content: str) -> List[Dict]:
        """헤더 구조 추출"""
        headers = []
        for match in self.header_pattern.finditer(content):
            level = len(match.group(0)) - len(match.group(0).lstrip('#'))
            headers.append({
                'level': level,
                'title': match.group(1).strip(),
                'start': match.start(),
                'end': match.end()
            })
        return headers
    
    def _find_raw_text(self, content: str, processed_text: str, element_type: str) -> str:
        """원본 콘텐츠에서 해당 섹션의 raw text 찾기"""
        # 간단한 텍스트 매칭 (개선 가능)
        lines = content.split('\n')
        
        # 헤더 처리
        if element_type.startswith('h'):
            clean_text = processed_text.lstrip('#').strip()
            for line in lines:
                if clean_text in line and line.strip().startswith('#'):
                    return line.strip()
        
        # 테이블 처리
        if element_type == 'table':
            for i, line in enumerate(lines):
                if '<table' in line:
                    # 테이블 끝까지 찾기
                    end_idx = i
                    for j in range(i, len(lines)):
                        if '</table>' in lines[j]:
                            end_idx = j
                            break
                    return '\n'.join(lines[i:end_idx+1])
        
        # 일반 텍스트 매칭
        for line in lines:
            if processed_text.strip() in line or line.strip() in processed_text:
                return line.strip()
        
        return processed_text
    
    def _process_table_text(self, table_element) -> str:
        """HTML 테이블을 읽기 쉬운 텍스트로 변환"""
        rows = []
        
        # 헤더 처리
        headers = []
        header_row = table_element.find('tr')
        if header_row:
            headers = [th.get_text().strip() for th in header_row.find_all(['th', 'td'])]
            if headers:
                rows.append(' | '.join(headers))
                rows.append(' | '.join(['---'] * len(headers)))
        
        # 데이터 행 처리
        for tr in table_element.find_all('tr')[1:]:  # 첫 번째 행은 헤더이므로 제외
            row = [td.get_text().strip() for td in tr.find_all(['td', 'th'])]
            if row:
                rows.append(' | '.join(row))
        
        return '\n'.join(rows)
    
    def _calculate_content_stats(self, sections: List[Dict]) -> Dict:
        """콘텐츠 통계 계산"""
        stats = {
            'total_sections': len(sections),
            'content_types': {},
            'total_length': 0,
            'avg_section_length': 0
        }
        
        for section in sections:
            content_type = section['content_type']
            stats['content_types'][content_type] = stats['content_types'].get(content_type, 0) + 1
            stats['total_length'] += len(section['text'])
        
        if stats['total_sections'] > 0:
            stats['avg_section_length'] = stats['total_length'] / stats['total_sections']
        
        return stats

class EnhancedSemanticChunker:
    """혼합 콘텐츠용 향상된 의미 청킹"""
    
    def __init__(self, max_chunk_size: int = 1000, overlap_size: int = 100, preserve_latex: bool = True):
        self.max_chunk_size = max_chunk_size
        self.overlap_size = overlap_size
        self.preserve_latex = preserve_latex  # LaTeX 수식 보존 여부
        
    def chunk_by_content_type(self, processed_data: Dict[str, Any]) -> List[Dict]:
        """콘텐츠 타입별 청킹"""
        sections = processed_data['sections']
        latex_expressions = processed_data['latex_expressions']
        tables = processed_data['tables']
        
        chunks = []
        current_chunk = []
        current_size = 0
        current_type = None
        
        for section in sections:
            section_text = section['text']
            section_raw = section['raw_text']
            section_type = section['content_type']
            section_size = len(section_text)
            
            # 콘텐츠 타입별 처리 전략
            if section_type == 'latex':
                # LaTeX 수식은 가능한 한 완전하게 유지
                if self.preserve_latex:
                    chunks.extend(self._handle_latex_section(section, current_chunk, current_size, current_type))
                    current_chunk = []
                    current_size = 0
                    current_type = None
                else:
                    # 일반 텍스트처럼 처리
                    current_chunk, current_size, current_type = self._add_to_chunk(
                        current_chunk, current_size, current_type, section, chunks
                    )
            
            elif section_type == 'table':
                # 테이블은 완전한 단위로 보존
                if current_chunk:
                    chunks.append(self._create_chunk(current_chunk, current_type))
                    current_chunk = []
                    current_size = 0
                
                # 테이블 청크 생성
                table_chunk = self._create_table_chunk(section)
                chunks.append(table_chunk)
                current_type = None
            
            elif section_type == 'code':
                # 코드 블록도 완전한 단위로 보존
                if current_chunk:
                    chunks.append(self._create_chunk(current_chunk, current_type))
                    current_chunk = []
                    current_size = 0
                
                code_chunk = self._create_code_chunk(section)
                chunks.append(code_chunk)
                current_type = None
            
            else:
                # 일반 텍스트 처리
                current_chunk, current_size, current_type = self._add_to_chunk(
                    current_chunk, current_size, current_type, section, chunks
                )
        
        # 남은 청크 처리
        if current_chunk:
            chunks.append(self._create_chunk(current_chunk, current_type))
        
        return chunks
    
    def _handle_latex_section(self, section: Dict, current_chunk: List, current_size: int, current_type: str) -> List[Dict]:
        """LaTeX 섹션 특별 처리"""
        chunks = []
        
        # 현재 청크가 있으면 먼저 저장
        if current_chunk:
            chunks.append(self._create_chunk(current_chunk, current_type))
        
        # LaTeX 섹션이 너무 크면 수식 단위로 분할
        if len(section['text']) > self.max_chunk_size:
            latex_chunks = self._split_latex_carefully(section)
            chunks.extend(latex_chunks)
        else:
            # 단일 LaTeX 청크로 처리
            latex_chunk = {
                'text': section['text'],
                'raw_text': section['raw_text'],
                'content_type': 'latex',
                'metadata': {
                    **section.get('metadata', {}),
                    'preserved_latex': True
                }
            }
            chunks.append(latex_chunk)
        
        return chunks
    
    def _split_latex_carefully(self, section: Dict) -> List[Dict]:
        """LaTeX 수식을 신중하게 분할"""
        text = section['text']
        raw_text = section['raw_text']
        
        # 수식 경계 찾기
        content_processor = MixedContentProcessor()
        expressions = content_processor.extract_latex_expressions(raw_text)
        
        if not expressions:
            return [self._create_text_chunks(text, raw_text)]
        
        chunks = []
        current_pos = 0
        current_chunk_text = []
        current_chunk_size = 0
        
        for expr in expressions:
            # 수식 앞 텍스트 추가
            if expr['start'] > current_pos:
                pre_text = raw_text[current_pos:expr['start']].strip()
                if pre_text:
                    if current_chunk_size + len(pre_text) > self.max_chunk_size and current_chunk_text:
                        chunks.append(self._create_single_chunk(current_chunk_text, 'latex'))
                        current_chunk_text = []
                        current_chunk_size = 0
                    
                    current_chunk_text.append(pre_text)
                    current_chunk_size += len(pre_text)
            
            # 수식 추가
            expr_text = expr['content']
            if current_chunk_size + len(expr_text) > self.max_chunk_size and current_chunk_text:
                chunks.append(self._create_single_chunk(current_chunk_text, 'latex'))
                current_chunk_text = []
                current_chunk_size = 0
            
            current_chunk_text.append(expr_text)
            current_chunk_size += len(expr_text)
            current_pos = expr['end']
        
        # 남은 텍스트 처리
        if current_pos < len(raw_text):
            remaining = raw_text[current_pos:].strip()
            if remaining:
                current_chunk_text.append(remaining)
        
        if current_chunk_text:
            chunks.append(self._create_single_chunk(current_chunk_text, 'latex'))
        
        return chunks
    
    def _create_single_chunk(self, text_parts: List[str], content_type: str) -> Dict:
        """단일 청크 생성"""
        combined_text = ' '.join(text_parts)
        return {
            'text': combined_text,
            'raw_text': combined_text,
            'content_type': content_type,
            'metadata': {'parts_count': len(text_parts)}
        }
    
    def _create_table_chunk(self, section: Dict) -> Dict:
        """테이블 청크 생성"""
        return {
            'text': section['text'],
            'raw_text': section['raw_text'],
            'content_type': 'table',
            'metadata': {
                **section.get('metadata', {}),
                'table_chunk': True
            }
        }
    
    def _create_code_chunk(self, section: Dict) -> Dict:
        """코드 청크 생성"""
        return {
            'text': section['text'],
            'raw_text': section['raw_text'],
            'content_type': 'code',
            'metadata': {
                **section.get('metadata', {}),
                'code_chunk': True
            }
        }
    
    def _add_to_chunk(self, current_chunk: List, current_size: int, current_type: str, 
                     section: Dict, chunks: List) -> Tuple[List, int, str]:
        """청크에 섹션 추가"""
        section_size = len(section['text'])
        
        if current_size + section_size > self.max_chunk_size and current_chunk:
            chunks.append(self._create_chunk(current_chunk, current_type))
            current_chunk = []
            current_size = 0
        
        current_chunk.append(section)
        current_size += section_size
        current_type = section['content_type']
        
        return current_chunk, current_size, current_type
    
    def _create_chunk(self, sections: List[Dict], content_type: str) -> Dict:
        """여러 섹션으로부터 청크 생성"""
        text_parts = []
        raw_parts = []
        
        for section in sections:
            text_parts.append(section['text'])
            raw_parts.append(section['raw_text'])
        
        return {
            'text': '\n\n'.join(text_parts),
            'raw_text': '\n\n'.join(raw_parts),
            'content_type': content_type or 'mixed',
            'metadata': {
                'section_count': len(sections),
                'merged_content': True
            }
        }
    
    def create_overlapping_chunks(self, chunks: List[Dict]) -> List[Dict]:
        """오버랩 청크 생성 (콘텐츠 타입 고려)"""
        if len(chunks) <= 1:
            return chunks
        
        overlapping_chunks = []
        
        for i, chunk in enumerate(chunks):
            if i == 0:
                overlapping_chunks.append(chunk)
            else:
                prev_chunk = chunks[i-1]
                
                # 텍스트 콘텐츠에만 오버랩 적용
                if (chunk['content_type'] == 'text' and 
                    prev_chunk['content_type'] == 'text' and
                    len(prev_chunk['text']) > self.overlap_size):
                    
                    overlap_text = prev_chunk['text'][-self.overlap_size:]
                    overlapping_chunk = {
                        'text': overlap_text + " " + chunk['text'],
                        'raw_text': overlap_text + " " + chunk['raw_text'],
                        'content_type': chunk['content_type'],
                        'metadata': {
                            **chunk.get('metadata', {}),
                            'has_overlap': True,
                            'overlap_size': len(overlap_text)
                        }
                    }
                    overlapping_chunks.append(overlapping_chunk)
                else:
                    overlapping_chunks.append(chunk)
        
        return overlapping_chunks

class FAISSVectorStore:
    """FAISS 기반 벡터 저장소"""
    
    def __init__(self, embedding_dim: int = 2560, index_type: str = "IP"):
        self.embedding_dim = embedding_dim
        self.index_type = index_type
        self.index = None
        self.metadata_store = {}
        self.id_to_index = {}
        self.index_to_id = {}
        self.next_index = 0
        
        self._init_index()
    
    def _init_index(self):
        """FAISS 인덱스 초기화"""
        if self.index_type == "IP":
            # IP 인덱스 (Inner Product) 사용
            # 단순 플랫 인덱스 사용
            self.index = faiss.IndexFlatIP(self.embedding_dim)
        elif self.index_type == "HNSW":
            # 고차원 데이터용 HNSW 인덱스
            self.index = faiss.IndexHNSWFlat(self.embedding_dim, 32)
        else:
            # 소규모 데이터용 플랫 인덱스
            self.index = faiss.IndexFlatIP(self.embedding_dim)
        
        logger.info(f"Initialized FAISS index: {self.index_type}")
    
    def add_vectors(self, vectors: List[VectorEntry]):
        """벡터를 FAISS 인덱스에 추가"""
        if not vectors:
            return
        
        # 임베딩 배열 준비
        embeddings = np.array([vec.embedding for vec in vectors], dtype=np.float32)
        
        # 코사인 유사도를 위한 정규화
        faiss.normalize_L2(embeddings)
        
        # 인덱스 훈련 (IP의 경우)
        if hasattr(self.index, 'is_trained') and not self.index.is_trained:
            self.index.train(embeddings)
        
        # 인덱스에 추가
        start_idx = self.next_index
        self.index.add(embeddings)
        
        # 메타데이터 저장
        for i, vec in enumerate(vectors):
            idx = start_idx + i
            self.id_to_index[vec.id] = idx
            self.index_to_id[idx] = vec.id
            self.metadata_store[vec.id] = {
                'document_id': vec.document_id,
                'chunk_id': vec.chunk_id,
                'text': vec.text,
                'raw_text': vec.raw_text,
                'content_type': vec.content_type,
                'metadata': vec.metadata,
                'created_at': vec.created_at
            }
        
        self.next_index += len(vectors)
        logger.info(f"Added {len(vectors)} vectors to FAISS index. Total: {self.next_index}")
    
    def save_index(self, file_path: str):
        """FAISS 인덱스 저장"""
        # 인덱스 파일 저장
        faiss.write_index(self.index, file_path)
        
        # 메타데이터 별도 저장 (.faiss와 .index 모두 지원)
        if '.faiss' in file_path:
            metadata_path = file_path.replace('.faiss', '_metadata.pkl')
        else:
            metadata_path = file_path.replace('.index', '_metadata.pkl')
            
        with open(metadata_path, 'wb') as f:
            pickle.dump({
                'metadata_store': self.metadata_store,
                'id_to_index': self.id_to_index,
                'index_to_id': self.index_to_id,
                'next_index': self.next_index,
                'embedding_dim': self.embedding_dim,
                'index_type': self.index_type
            }, f)
        
        logger.info(f"Saved FAISS index to {file_path}")
        logger.info(f"Saved metadata to {metadata_path}")
    
    def load_index(self, file_path: str):
        """FAISS 인덱스 로드"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Index file not found: {file_path}")
        
        # 인덱스 로드
        self.index = faiss.read_index(file_path)
        
        # 메타데이터 로드 (.faiss와 .index 모두 지원)
        if '.faiss' in file_path:
            metadata_path = file_path.replace('.faiss', '_metadata.pkl')
        else:
            metadata_path = file_path.replace('.index', '_metadata.pkl')
            
        if os.path.exists(metadata_path):
            with open(metadata_path, 'rb') as f:
                data = pickle.load(f)
                self.metadata_store = data['metadata_store']
                self.id_to_index = data['id_to_index']
                self.index_to_id = data['index_to_id']
                self.next_index = data['next_index']
                self.embedding_dim = data.get('embedding_dim', self.embedding_dim)
                self.index_type = data.get('index_type', self.index_type)
        
        logger.info(f"Loaded FAISS index from {file_path}")
        logger.info(f"Index contains {self.next_index} vectors")
    
    def get_stats(self) -> Dict:
        """벡터 저장소 통계 정보"""
        content_type_counts = {}
        document_counts = {}
        
        for metadata in self.metadata_store.values():
            # 콘텐츠 타입별 카운트
            content_type = metadata['content_type']
            content_type_counts[content_type] = content_type_counts.get(content_type, 0) + 1
            
            # 문서별 카운트
            doc_id = metadata['document_id']
            document_counts[doc_id] = document_counts.get(doc_id, 0) + 1
        
        return {
            'total_vectors': self.next_index,
            'total_documents': len(document_counts),
            'content_type_distribution': content_type_counts,
            'avg_chunks_per_doc': np.mean(list(document_counts.values())) if document_counts else 0,
            'embedding_dimension': self.embedding_dim,
            'index_type': self.index_type
        }

class Qwen3LateChunker:
    """Qwen3 모델을 사용한 Late Chunking 메인 클래스"""
    
    def __init__(self, 
                 model_name: str = "Qwen/Qwen3-Embedding-4B",
                #  max_length: int = 32768,
                 max_length: int = 10000,
                 device: str = "auto",
                 embedding_dim: int = 2560,
                 chunk_size: int = 1000,
                 overlap_size: int = 100,
                 preserve_latex: bool = True,
                 index_path: str = "text_index.faiss",
                 index_type: str = "IP"):
        
        self.model_name = model_name
        self.max_length = max_length
        self.embedding_dim = embedding_dim
        self.chunk_size = chunk_size
        self.overlap_size = overlap_size
        self.preserve_latex = preserve_latex
        self.index_path = index_path
        self.index_type = index_type
        
        # 디바이스 설정
        self.device = self._setup_device(device)
        logger.info(f"Using device: {self.device}")
        
        # 모델 및 토크나이저 로드
        self._load_model()
        
        # 프로세서 초기화
        self.content_processor = MixedContentProcessor()
        self.chunker = EnhancedSemanticChunker(
            chunk_size, overlap_size, preserve_latex
        )
        
        # FAISS 벡터 저장소 초기화
        self.vector_store = FAISSVectorStore(embedding_dim, index_type)
        
        # 기존 인덱스 로드 시도
        if os.path.exists(index_path):
            try:
                self.vector_store.load_index(index_path)
                logger.info("Loaded existing FAISS index")
            except Exception as e:
                logger.warning(f"Failed to load existing index: {e}")
        
        # 문서 추적
        self.processed_documents = set()
        self.document_metadata = {}
        
        # 처리 통계
        self.processing_stats = {
            'total_documents': 0,
            'total_chunks': 0,
            'total_processing_time': 0.0,
            'content_type_stats': {},
            'errors': []
        }
    
    def _setup_device(self, device: str) -> str:
        """멀티 GPU 환경 디바이스 설정"""
        if device == "auto":
            if torch.cuda.is_available():
                device_count = torch.cuda.device_count()
                logger.info(f"Found {device_count} CUDA devices")
                
                # GPU 메모리 확인
                if device_count > 1:
                    for i in range(device_count):
                        memory = torch.cuda.get_device_properties(i).total_memory / 2560**3
                        logger.info(f"GPU {i}: {memory:.1f}GB memory")
                    device = "cuda:1"  # 두 번째 GPU 사용 (생성 모델은 cuda:0에 할당)
                else:
                    device = "cuda"
            else:
                device = "cpu"
                logger.warning("CUDA not available, using CPU")
        
        return device
    
    def _load_model(self):
        """Qwen3 모델 및 토크나이저 로드"""
        try:
            logger.info(f"Loading {self.model_name}...")
            
            # 모델 로드 (멀티 GPU 지원) - config dtype 사용
            # config에서 GENERATOR_TORCH_DTYPE 설정 확인
            try:
                from config import RAGConfig
                rag_config = RAGConfig()
                if rag_config.GENERATOR_TORCH_DTYPE == "auto":
                    torch_dtype = "auto"
                else:
                    torch_dtype = torch.float16
            except Exception as e:
                # config 로드 실패 시 기본값 사용
                logger.warning(f"Config 로드 실패: {e}, 기본 dtype 사용")
                torch_dtype = torch.float16
            
            # generator.py 참고하여 모델 로드 방식 수정
            model_kwargs = {"torch_dtype": torch_dtype, "device_map": self.device}
            
            try:
                # 토크나이저 로드
                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    padding_side='left',
                    local_files_only=True
                )
                
                if self.tokenizer.pad_token_id is None:
                    self.tokenizer.pad_token_id = self.tokenizer.eos_token_id
                
                # 모델 로드
                logger.info(f"모델 로드 시도: {self.model_name}, device: {self.device}, dtype: {torch_dtype}")
                self.model = AutoModel.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    local_files_only=True,
                    **model_kwargs
                )
                
                logger.info(f"모델 '{self.model_name}' 로드 성공")
                logger.info(f"모델 디바이스: {next(self.model.parameters()).device}")
            except Exception as e:
                logger.error(f"모델 로드 실패: {e}")
                raise
            
            logger.info(f"텍스트 임베딩 모델 dtype 설정: {torch_dtype}")
            
            self.model.eval()
            
            # 특수 토큰 ID 가져오기
            self.eod_id = self.tokenizer.convert_tokens_to_ids("<|endoftext|>")
            if self.eod_id is None:
                # 대체 토큰 시도
                self.eod_id = self.tokenizer.eos_token_id
            
            logger.info("Model loaded successfully")
            logger.info(f"Model device: {next(self.model.parameters()).device}")
            
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            raise
    
    def _tokenize_with_positions(self, text: str) -> Dict:
        """위치 정보와 함께 토크나이징"""
        try:
            tokens = self.tokenizer(
                text,
                return_tensors="pt",
                padding=False,
                truncation=True,
                max_length=self.max_length - 2,
                return_offsets_mapping=True
            )
            
            # EOD 토큰 추가
            if self.eod_id is not None:
                tokens["input_ids"] = torch.cat([
                    tokens["input_ids"],
                    torch.tensor([[self.eod_id]])
                ], dim=1)
                
                tokens["attention_mask"] = torch.cat([
                    tokens["attention_mask"],
                    torch.tensor([[1]])
                ], dim=1)
            
            return tokens
            
        except Exception as e:
            logger.error(f"Tokenization error: {e}")
            raise
    
    def _get_chunk_boundaries(self, text: str, chunks: List[Dict], document_id: str) -> List[ChunkInfo]:
        """청크 경계 정보 생성"""
        chunk_infos = []
        current_pos = 0
        
        try:
            # 전체 텍스트 토크나이징
            full_tokens = self._tokenize_with_positions(text)
            offset_mapping = full_tokens["offset_mapping"][0]
            
            for i, chunk in enumerate(chunks):
                chunk_text = chunk['text']
                
                # 청크 시작 위치 찾기
                chunk_start = text.find(chunk_text, current_pos)
                if chunk_start == -1:
                    # 정확한 매치 실패 시 근사 위치 사용
                    chunk_start = current_pos
                    logger.warning(f"Exact chunk match failed for chunk {i}")
                
                chunk_end = chunk_start + len(chunk_text)
                
                # 토큰 위치 찾기
                token_start = 0
                token_end = len(offset_mapping) - 1
                
                # 시작 토큰 찾기
                for j, (start, end) in enumerate(offset_mapping):
                    if start <= chunk_start < end:
                        token_start = j
                        break
                
                # 종료 토큰 찾기
                for j, (start, end) in enumerate(offset_mapping):
                    if start < chunk_end <= end:
                        token_end = j
                        break
                
                # ChunkInfo 생성
                chunk_id = str(uuid.uuid4())
                
                chunk_info = ChunkInfo(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    raw_text=chunk.get('raw_text', chunk_text),
                    start_pos=chunk_start,
                    end_pos=chunk_end,
                    token_start=token_start,
                    token_end=token_end,
                    chunk_index=i,
                    document_id=document_id,
                    content_type=chunk.get('content_type', 'text'),
                    metadata={
                        "length": len(chunk_text),
                        "token_count": token_end - token_start + 1,
                        "content_type": chunk.get('content_type', 'text'),
                        **chunk.get('metadata', {})
                    }
                )
                
                chunk_infos.append(chunk_info)
                current_pos = chunk_end
                
        except Exception as e:
            logger.error(f"Error getting chunk boundaries: {e}")
            raise
        
        return chunk_infos
    
    def _mean_pool_chunk(self, token_embeddings: torch.Tensor, 
                        token_start: int, token_end: int) -> torch.Tensor:
        """청크 토큰들에 대한 평균 풀링"""
        try:
            chunk_tokens = token_embeddings[token_start:token_end+1]
            if len(chunk_tokens) == 0:
                logger.warning(f"Empty chunk tokens for range {token_start}:{token_end}")
                return torch.zeros(token_embeddings.size(-1), device=token_embeddings.device)
            
            return torch.mean(chunk_tokens, dim=0)
            
        except Exception as e:
            logger.error(f"Error in mean pooling: {e}")
            raise
    
    def process_markdown_file(self, file_path: str, document_id: str = None) -> str:
        """마크다운 파일 처리 및 FAISS 저장"""
        import time
        start_time = time.time()
        
        logger.info(f"Processing markdown file: {file_path}")
        
        try:
            # 문서 ID 생성
            if document_id is None:
                with open(file_path, 'rb') as f:
                    file_content = f.read()
                document_id = hashlib.md5(file_content).hexdigest()
            
            # 이미 처리된 문서인지 확인
            if document_id in self.processed_documents:
                logger.info(f"Document {document_id} already processed")
                return document_id
            
            # 마크다운 콘텐츠 처리
            processed_data = self.content_processor.process_markdown(file_path)
            
            # 청킹
            chunks = self.chunker.chunk_by_content_type(processed_data)
            chunks = self.chunker.create_overlapping_chunks(chunks)
            
            logger.info(f"Created {len(chunks)} chunks")
            logger.info(f"Content types: {[c.get('content_type', 'unknown') for c in chunks]}")
            
            # 전체 텍스트 결합 (Late Chunking용)
            full_text = '\n\n'.join([chunk['text'] for chunk in chunks])
            
            # 텍스트 길이 확인 및 자동 분할 처리
            text_tokens = len(self.tokenizer.tokenize(full_text))
            if text_tokens > self.max_length:
                logger.info(f"Text length ({text_tokens}) exceeds max length ({self.max_length}). Processing in segments...")
                return self._process_long_document(file_path, full_text, chunks, document_id, processed_data, start_time)
            
            # 청크 경계 정보 생성
            chunk_infos = self._get_chunk_boundaries(full_text, chunks, document_id)
            
            # Late Chunking 수행
            vector_entries = self._perform_late_chunking(full_text, chunk_infos)
            
            # FAISS에 저장
            self.vector_store.add_vectors(vector_entries)
            self.vector_store.save_index(self.index_path)
            
            # 처리 완료 기록
            self.processed_documents.add(document_id)
            
            # 문서 메타데이터 저장
            processing_time = time.time() - start_time
            self.document_metadata[document_id] = {
                'filename': os.path.basename(file_path),
                'file_path': file_path,
                'chunk_count': len(vector_entries),
                'content_types': list(set(chunk.content_type for chunk in vector_entries)),
                'latex_expressions': len(processed_data.get('latex_expressions', [])),
                'tables': len(processed_data.get('tables', [])),
                'code_blocks': len(processed_data.get('code_blocks', [])),
                'processing_time': processing_time,
                'total_tokens': text_tokens,
                'created_at': datetime.now()
            }
            
            # 통계 업데이트
            self._update_stats(vector_entries, processing_time)
            
            logger.info(f"Successfully processed document {document_id}")
            logger.info(f"Stored {len(vector_entries)} chunks in {processing_time:.2f}s")
            
            return document_id
            
        except Exception as e:
            error_msg = f"Error processing {file_path}: {str(e)}"
            logger.error(error_msg)
            self.processing_stats['errors'].append({
                'file_path': file_path,
                'error': str(e),
                'timestamp': datetime.now()
            })
            raise
    
    def _perform_late_chunking(self, full_text: str, chunk_infos: List[ChunkInfo]) -> List[VectorEntry]:
        """Late Chunking 수행"""
        vector_entries = []
        
        try:
            with torch.no_grad():
                # 전체 텍스트 토크나이징
                tokens = self._tokenize_with_positions(full_text)
                
                # GPU로 이동
                for key in tokens:
                    if isinstance(tokens[key], torch.Tensor):
                        tokens[key] = tokens[key].to(self.device)
                
                # 전체 문서 임베딩
                outputs = self.model(**tokens)
                token_embeddings = outputs.last_hidden_state[0]  # 배치 차원 제거
                
                # 각 청크에 대해 평균 풀링
                for chunk_info in tqdm(chunk_infos, desc="Embedding chunks"):
                    # 청크 토큰들에 대한 평균 풀링
                    chunk_embedding = self._mean_pool_chunk(
                        token_embeddings, 
                        chunk_info.token_start, 
                        chunk_info.token_end
                    )
                    
                    # 임베딩 정규화
                    chunk_embedding = F.normalize(chunk_embedding, p=2, dim=0)
                    # BFloat16 지원을 위해 float32로 변환
                    chunk_embedding = chunk_embedding.float()
                    chunk_embedding_np = chunk_embedding.cpu().numpy().astype(np.float32)
                    
                    # VectorEntry 생성
                    vector_entry = VectorEntry(
                        id=chunk_info.chunk_id,
                        document_id=chunk_info.document_id,
                        chunk_id=chunk_info.chunk_id,
                        text=chunk_info.text,
                        raw_text=chunk_info.raw_text,
                        embedding=chunk_embedding_np,
                        content_type=chunk_info.content_type,
                        metadata=chunk_info.metadata,
                        created_at=datetime.now()
                    )
                    
                    vector_entries.append(vector_entry)
                    
        except Exception as e:
            logger.error(f"Error in late chunking: {e}")
            raise
        
        return vector_entries
        
    def _process_long_document(self, file_path: str, full_text: str, chunks: List[Dict], 
                           document_id: str, processed_data: Dict, start_time: float) -> str:
        """긴 문서를 여러 세그먼트로 나누어 처리"""
        import math
        import time
        
        all_vector_entries = []
        segment_size = self.max_length - 1000  # 약간의 여유 공간 확보
        
        # 청크 텍스트 길이 기준으로 세그먼트 나누기
        chunk_lengths = [len(chunk['text']) for chunk in chunks]
        total_length = sum(chunk_lengths)
        
        # 세그먼트 수 계산
        total_segments = math.ceil(total_length / segment_size)
        
        logger.info(f"Splitting document into {total_segments} segments of ~{segment_size} characters each")
        
        # 청크를 세그먼트로 그룹화
        segments = []
        current_segment = []
        current_length = 0
        
        for i, chunk in enumerate(chunks):
            chunk_length = chunk_lengths[i]
            
            # 현재 세그먼트가 가득 차면 새 세그먼트 시작
            if current_length + chunk_length > segment_size and current_segment:
                segments.append(current_segment)
                current_segment = []
                current_length = 0
            
            current_segment.append(chunk)
            current_length += chunk_length
        
        # 마지막 세그먼트 추가
        if current_segment:
            segments.append(current_segment)
        
        # 각 세그먼트 처리
        for i, segment_chunks in enumerate(segments):
            logger.info(f"Processing segment {i+1}/{len(segments)}")
            
            # 세그먼트 텍스트 결합
            segment_text = '\n\n'.join([chunk['text'] for chunk in segment_chunks])
            
            # 세그먼트 ID 생성 (원본 문서 ID + 세그먼트 번호)
            segment_id = f"{document_id}_seg{i+1}"
            
            # 청크 경계 정보 생성
            chunk_infos = self._get_chunk_boundaries(segment_text, segment_chunks, segment_id)
            
            # Late Chunking 수행
            segment_vectors = self._perform_late_chunking(segment_text, chunk_infos)
            
            # 결과 병합
            all_vector_entries.extend(segment_vectors)
            
            # 세그먼트별 통계 저장
            self._update_segment_stats(segment_id, file_path, segment_chunks, i+1, len(segments))
        
        # FAISS에 저장
        self.vector_store.add_vectors(all_vector_entries)
        self.vector_store.save_index(self.index_path)
        
        # 처리 완료 기록
        self.processed_documents.add(document_id)
        
        # 문서 메타데이터 저장
        processing_time = time.time() - start_time
        self.document_metadata[document_id] = {
            'filename': os.path.basename(file_path),
            'file_path': file_path,
            'is_segmented': True,
            'segment_count': len(segments),
            'chunk_count': len(all_vector_entries),
            'content_types': list(set(entry.content_type for entry in all_vector_entries)),
            'latex_expressions': len(processed_data.get('latex_expressions', [])),
            'tables': len(processed_data.get('tables', [])),
            'code_blocks': len(processed_data.get('code_blocks', [])),
            'processing_time': processing_time,
            'created_at': datetime.now()
        }
        
        # 통계 업데이트
        self._update_stats(all_vector_entries, processing_time)
        
        logger.info(f"Successfully processed segmented document {document_id}")
        logger.info(f"Stored {len(all_vector_entries)} chunks from {len(segments)} segments in {processing_time:.2f}s")
        
        return document_id
        
    def _update_segment_stats(self, segment_id: str, file_path: str, segment_chunks: List[Dict], 
                             segment_num: int, total_segments: int):
        """세그먼트 처리 통계 저장"""
        # 콘텐츠 타입 분포 계산
        content_types = {}
        latex_count = 0
        table_count = 0
        code_count = 0
        
        for chunk in segment_chunks:
            content_type = chunk.get('content_type', 'text')
            content_types[content_type] = content_types.get(content_type, 0) + 1
            
            # 특수 콘텐츠 카운트
            if chunk.get('has_latex', False):
                latex_count += 1
            if content_type == 'table':
                table_count += 1
            if content_type == 'code':
                code_count += 1
        
        # 세그먼트 요약 저장
        self.document_metadata[segment_id] = {
            'filename': f"{os.path.basename(file_path)} (segment {segment_num}/{total_segments})",
            'chunks': len(segment_chunks),
            'content_types': content_types,
            'latex_count': latex_count,
            'table_count': table_count,
            'code_count': code_count,
            'is_segment': True,
            'segment_num': segment_num,
            'total_segments': total_segments
        }
    
    def _update_stats(self, vector_entries: List[VectorEntry], processing_time: float):
        """처리 통계 업데이트"""
        self.processing_stats['total_documents'] += 1
        self.processing_stats['total_chunks'] += len(vector_entries)
        self.processing_stats['total_processing_time'] += processing_time
        
        # 콘텐츠 타입별 통계
        for entry in vector_entries:
            content_type = entry.content_type
            if content_type not in self.processing_stats['content_type_stats']:
                self.processing_stats['content_type_stats'][content_type] = 0
            self.processing_stats['content_type_stats'][content_type] += 1
    
    def batch_process_files(self, file_paths: List[str], continue_on_error: bool = True) -> Dict[str, str]:
        """여러 파일 배치 처리"""
        results = {}
        
        logger.info(f"Starting batch processing of {len(file_paths)} files")
        
        for i, file_path in enumerate(file_paths):
            try:
                logger.info(f"Processing file {i+1}/{len(file_paths)}: {file_path}")
                document_id = self.process_markdown_file(file_path)
                results[file_path] = document_id
                
            except Exception as e:
                logger.error(f"Failed to process {file_path}: {e}")
                if continue_on_error:
                    results[file_path] = f"ERROR: {str(e)}"
                    continue
                else:
                    raise
        
        # 배치 처리 완료 로그
        successful = len([r for r in results.values() if not r.startswith("ERROR:")])
        failed = len(results) - successful
        
        logger.info(f"Batch processing completed: {successful} successful, {failed} failed")
        
        return results
    
    def get_processing_stats(self) -> Dict:
        """처리 통계 반환"""
        stats = self.processing_stats.copy()
        
        # 평균 처리 시간 계산
        if stats['total_documents'] > 0:
            stats['avg_processing_time'] = stats['total_processing_time'] / stats['total_documents']
            stats['avg_chunks_per_doc'] = stats['total_chunks'] / stats['total_documents']
        else:
            stats['avg_processing_time'] = 0
            stats['avg_chunks_per_doc'] = 0
        
        # 벡터 저장소 통계 추가
        stats['vector_store_stats'] = self.vector_store.get_stats()
        
        return stats
    
    def get_document_summary(self, document_id: str) -> Dict:
        """문서 요약 정보 반환"""
        if document_id not in self.document_metadata:
            return {'error': f'Document {document_id} not found'}
        
        doc_meta = self.document_metadata[document_id]
        
        # 벡터 저장소에서 해당 문서의 청크들 가져오기
        doc_chunks = []
        for chunk_id, metadata in self.vector_store.metadata_store.items():
            if metadata['document_id'] == document_id:
                doc_chunks.append(metadata)
        
        # 콘텐츠 타입별 분포
        content_type_counts = {}
        for chunk in doc_chunks:
            ctype = chunk['content_type']
            content_type_counts[ctype] = content_type_counts.get(ctype, 0) + 1
        
        return {
            'document_id': document_id,
            'filename': doc_meta['filename'],
            'file_path': doc_meta['file_path'],
            'total_chunks': len(doc_chunks),
            'content_type_distribution': content_type_counts,
            'latex_expressions': doc_meta.get('latex_expressions', 0),
            'tables': doc_meta.get('tables', 0),
            'code_blocks': doc_meta.get('code_blocks', 0),
            'processing_time': doc_meta.get('processing_time', 0),
            'total_tokens': doc_meta.get('total_tokens', 0),
            'created_at': doc_meta['created_at']
        }
    
    def export_document_chunks(self, document_id: str, output_file: str = None) -> str:
        """특정 문서의 청크들을 JSON으로 내보내기"""
        if document_id not in self.document_metadata:
            raise ValueError(f"Document {document_id} not found")
        
        if output_file is None:
            filename = self.document_metadata[document_id]['filename']
            output_file = f"{filename}_chunks.json"
        
        # 해당 문서의 청크들 수집
        doc_chunks = []
        for chunk_id, metadata in self.vector_store.metadata_store.items():
            if metadata['document_id'] == document_id:
                doc_chunks.append({
                    'chunk_id': chunk_id,
                    'text': metadata['text'],
                    'raw_text': metadata['raw_text'],
                    'content_type': metadata['content_type'],
                    'metadata': metadata['metadata']
                })
        
        # JSON으로 저장
        export_data = {
            'document_id': document_id,
            'document_metadata': self.document_metadata[document_id],
            'chunk_count': len(doc_chunks),
            'chunks': doc_chunks
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
        
        logger.info(f"Exported {len(doc_chunks)} chunks to {output_file}")
        return output_file
    
    def cleanup(self):
        """메모리 정리"""
        if hasattr(self, 'model'):
            del self.model
        if hasattr(self, 'tokenizer'):
            del self.tokenizer
        
        torch.cuda.empty_cache()
        logger.info("Cleaned up model and freed GPU memory")



def main():
    parser = argparse.ArgumentParser(description="Qwen3 Late Chunking for Mixed Content")
    parser.add_argument("--input-file", help="Input markdown file path")
    parser.add_argument("--index-path", default="faiss_index.faiss", help="FAISS index path")
    parser.add_argument("--chunk-size", type=int, default=1000, help="Chunk size in characters")
    parser.add_argument("--overlap-size", type=int, default=100, help="Overlap size in characters")
    parser.add_argument("--preserve-latex", action="store_true", default=True, help="Preserve LaTeX expressions")
    parser.add_argument("--batch", nargs="+", help="Batch process multiple files")
    parser.add_argument("--export-chunks", help="Export chunks to JSON file")
    parser.add_argument("--stats", action="store_true", help="Show processing statistics")
    parser.add_argument("--search", action="store_true", help="Search mode - query the index")
    
    args = parser.parse_args()
    
    # 검색 모드
    if args.search:
        # 인덱스 파일 경로 확인
        if not os.path.exists(args.index_path):
            print(f"오류: 인덱스 파일을 찾을 수 없습니다: {args.index_path}")
            print("올바른 인덱스 파일 경로를 --index-path 옵션으로 지정하세요.")
            return
        
        print(f"\n===== FAISS 벡터 검색 모드 =====")
        print(f"인덱스 파일: {args.index_path}")
        print("종료하려면 'exit' 또는 'quit'를 입력하세요.\n")
        
        while True:
            try:
                query = input("\n검색 쿼리를 입력하세요: ")
                if query.lower() in ['exit', 'quit']:
                    print("검색을 종료합니다.")
                    break
                
                if not query.strip():
                    continue
                
                print(f"\n'{query}' 검색 중...")
                results = search_vectors(query, args.index_path, top_k=5)
                
                if not results:
                    print("검색 결과가 없습니다.")
                    continue
                
                print(f"\n검색 결과 ({len(results)}개):")
                for i, result in enumerate(results):
                    print(f"\n{i+1}. 유사도: {result['score']:.4f}")
                    print(f"   문서 ID: {result['document_id']}")
                    print(f"   청크 ID: {result['chunk_id']}")
                    print(f"   콘텐츠 타입: {result['content_type']}")
                    print(f"   텍스트: {result['text']}")
            
            except KeyboardInterrupt:
                print("\n검색이 중단되었습니다.")
                break
            except Exception as e:
                print(f"\n오류 발생: {str(e)}")
        
        return
    
    # 입력 파일이 없는 경우
    if not args.input_file and not args.batch:
        parser.print_help()
        print("\n오류: 입력 파일을 지정하거나 --batch 옵션을 사용하세요.")
        print("또는 --search 옵션을 사용하여 검색 모드로 실행하세요.")
        return
    
    # Late Chunker 초기화
    chunker = Qwen3LateChunker(
        chunk_size=args.chunk_size,
        overlap_size=args.overlap_size,
        preserve_latex=args.preserve_latex,
        index_path=args.index_path
    )
    
    try:
        if args.batch:
            # 배치 처리
            results = chunker.batch_process_files(args.batch)
            
            print("Batch Processing Results:")
            for file_path, result in results.items():
                if result.startswith("ERROR:"):
                    print(f"❌ {file_path}: {result}")
                else:
                    print(f"✅ {file_path}: {result}")
        
        elif args.input_file:
            # 단일 파일 처리
            document_id = chunker.process_markdown_file(args.input_file)
            print(f"Processed document: {document_id}")
            
            # 문서 요약 출력
            summary = chunker.get_document_summary(document_id)
            print(f"\nDocument Summary:")
            print(f"- Filename: {summary['filename']}")
            print(f"- Total chunks: {summary['total_chunks']}")
            print(f"- Content types: {summary['content_type_distribution']}")
            print(f"- LaTeX expressions: {summary['latex_expressions']}")
            print(f"- Tables: {summary['tables']}")
            print(f"- Code blocks: {summary['code_blocks']}")
            print(f"- Processing time: {summary['processing_time']:.2f}s")
            
            # 청크 내보내기
            if args.export_chunks:
                output_file = chunker.export_document_chunks(document_id, args.export_chunks)
                print(f"Exported chunks to: {output_file}")
        
        # 처리 통계 출력
        if args.stats:
            stats = chunker.get_processing_stats()
            print(f"\nProcessing Statistics:")
            print(f"- Total documents: {stats['total_documents']}")
            print(f"- Total chunks: {stats['total_chunks']}")
            print(f"- Average processing time: {stats['avg_processing_time']:.2f}s")
            print(f"- Average chunks per document: {stats['avg_chunks_per_doc']:.1f}")
            print(f"- Content type distribution: {stats['content_type_stats']}")
            print(f"- Vector store: {stats['vector_store_stats']['total_vectors']} vectors")
    
    finally:
        # 정리
        chunker.cleanup()

if __name__ == "__main__":
    main()
    