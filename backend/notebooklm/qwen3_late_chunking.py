#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import json
import logging
from typing import List, Dict, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import torch
import markdown
from bs4 import BeautifulSoup
import argparse
from tqdm import tqdm
from datetime import datetime
import hashlib
import uuid

# 💡 Sentence Transformers와 Weaviate 클라이언트 임포트
from shared_embedding import shared_embedding
import weaviate
from weaviate.util import generate_uuid5

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# 💡 Weaviate 및 Config 설정
# =============================================================================

class RAGConfig:
    """Weaviate 연결 및 클래스 이름 설정"""
    def __init__(self):
        self.WEAVIATE_URL = "http://127.0.0.1:8080"
        self.WEAVIATE_TEXT_CLASS = "TextDocument"
        self.WEAVIATE_DOCUMENT_CLASS = "Document" 

    def get_weaviate_client(self) -> weaviate.Client | None:
        """Weaviate 클라이언트를 초기화하고 반환합니다."""
        try:
            client = weaviate.Client(url=self.WEAVIATE_URL)
            if client.is_live():
                return client
            else:
                logger.error(f"Weaviate is not live at {self.WEAVIATE_URL}")
                return None
        except Exception as e:
            logger.error(f"Weaviate 클라이언트 초기화 중 오류 발생: {str(e)}")
            return None

def create_schema(client: weaviate.Client):
    """필요한 Weaviate 스키마를 생성합니다. (참조 순서에 맞춰 Document를 먼저 생성)"""
    config = RAGConfig()
    text_class = {
        "class": config.WEAVIATE_TEXT_CLASS,
        "description": "Text chunks and their embeddings.",
        "vectorizer": "none", 
        "moduleConfig": {
            "text2vec-contextionary": {
                "skip": True
            }
        },
        "properties": [
            {"name": "text", "dataType": ["text"]},
            {"name": "title", "dataType": ["text"]},
            {"name": "source", "dataType": ["text"]},
            {"name": "page_num", "dataType": ["int"]},
            {"name": "chunk_id", "dataType": ["text"]},
            {"name": "metadata", "dataType": ["object"], "nestedProperties": [
                {"name": "document_id", "dataType": ["text"]},
                {"name": "content_type", "dataType": ["text"]},
                {"name": "file_path", "dataType": ["text"]}
            ]},
            # 💡 Document 클래스를 참조
            {"name": "hasDocument", "dataType": [config.WEAVIATE_DOCUMENT_CLASS]}
        ]
    }
    document_class = {
        "class": config.WEAVIATE_DOCUMENT_CLASS,
        "description": "Original document metadata.",
        "vectorizer": "none",
        "moduleConfig": {
            "text2vec-contextionary": {
                "skip": True
            }
        },
        "properties": [
            {"name": "filename", "dataType": ["text"]},
            {"name": "file_path", "dataType": ["text"]},
            {"name": "file_type", "dataType": ["text"]},
        ]
    }

    try:
        # 💡 수정: Document 클래스를 먼저 생성 (참조되는 클래스)
        if not client.schema.exists(document_class['class']):
            client.schema.create_class(document_class)
            logger.info(f"Created schema class: {document_class['class']}")
            
        # 💡 수정: TextDocument 클래스를 나중에 생성 (참조하는 클래스)
        if not client.schema.exists(text_class['class']):
            client.schema.create_class(text_class)
            logger.info(f"Created schema class: {text_class['class']}")
            
    except Exception as e:
        logger.error(f"Weaviate 스키마 생성 중 오류 발생: {str(e)}")
# -----------------------------------------------------------------------


# =============================================================================
# 데이터 구조 및 프로세서 클래스 (이전과 동일)
# =============================================================================

@dataclass
class ChunkInfo:
    """청크 정보 구조체"""
    chunk_id: str
    text: str
    raw_text: str
    start_pos: int
    end_pos: int
    token_start: int
    token_end: int
    chunk_index: int
    document_id: str
    content_type: str
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
    def __init__(self):
        self.md_parser = markdown.Markdown(extensions=['fenced_code', 'tables'])
        self.latex_patterns = {
            'inline_paren': re.compile(r'\\\((.*?)\\\)', re.DOTALL),
            'inline_dollar': re.compile(r'\$([^$]+)\$'),
            'display_bracket': re.compile(r'\\\[(.*?)\\]', re.DOTALL),
            'display_dollar': re.compile(r'\$\$(.*?)\$\$', re.DOTALL),
        }
        self.table_pattern = re.compile(r'<table.*?</table>', re.DOTALL | re.IGNORECASE)
        self.code_pattern = re.compile(r'```.*?```', re.DOTALL)

    def process_markdown(self, file_path: str) -> Dict[str, Any]:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        html = self.md_parser.convert(content)
        soup = BeautifulSoup(html, 'html.parser')
        sections = []
        for element in soup.find_all(['p', 'li', 'pre', 'blockquote', 'table']):
            text = element.get_text().strip()
            if not text:
                continue
            raw_text = str(element)
            content_type = self._identify_content_type(raw_text)
            sections.append({
                'text': text,
                'raw_text': raw_text,
                'content_type': content_type,
                'metadata': {}
            })
        return {'sections': sections, 'raw_content': content}

    def _identify_content_type(self, text: str) -> str:
        if any(pattern.search(text) for pattern in self.latex_patterns.values()):
            return 'latex'
        if self.table_pattern.search(text):
            return 'table'
        if self.code_pattern.search(text):
            return 'code'
        return 'text'

class EnhancedSemanticChunker:
    def __init__(self, max_chunk_size: int = 1000, overlap_size: int = 100):
        self.max_chunk_size = max_chunk_size
        self.overlap_size = overlap_size

    def chunk_by_content_type(self, processed_data: Dict[str, Any]) -> List[Dict]:
        sections = processed_data['sections']
        chunks = []
        current_chunk_text = ""
        current_chunk_raw = ""
        for section in sections:
            if len(current_chunk_text) + len(section['text']) > self.max_chunk_size:
                if current_chunk_text:
                    chunks.append({'text': current_chunk_text, 'raw_text': current_chunk_raw, 'content_type': 'mixed'})
                current_chunk_text = section['text']
                current_chunk_raw = section['raw_text']
            else:
                current_chunk_text += "\n\n" + section['text']
                current_chunk_raw += "\n\n" + section['raw_text']
        if current_chunk_text:
            chunks.append({'text': current_chunk_text, 'raw_text': current_chunk_raw, 'content_type': 'mixed'})
        return chunks

class WeaviateVectorStore:
    """Weaviate 기반 벡터 저장소 (배치 저장 로직 포함)"""
    def __init__(self):
        self.config = RAGConfig()
        self.client = None
        self._init_client()

    def _init_client(self):
        self.client = self.config.get_weaviate_client()
        if self.client:
            logger.info(f"Initialized Weaviate client: {self.config.WEAVIATE_URL}")
        else:
            logger.warning("Weaviate 클라이언트 초기화 실패. 데이터 저장이 불가능합니다.")

    def add_vectors(self, vectors: List[VectorEntry]):
        if not vectors or not self.client:
            logger.warning("Weaviate 클라이언트가 초기화되지 않았거나 벡터가 없습니다. 데이터베이스 저장을 건너뜁니다.")
            return
        
        # 1. 문서 메타데이터 저장 및 UUID 생성
        first_vec = vectors[0]
        metadata = first_vec.metadata
        file_path = metadata.get('file_path', '')
        filename = os.path.basename(file_path) if file_path else f"doc_{first_vec.document_id[:8]}"
        
        document_object = {
            "filename": filename,
            "file_path": file_path,
            "file_type": os.path.splitext(filename)[1][1:] if os.path.splitext(filename)[1] else "",
        }
        document_uuid = generate_uuid5(first_vec.document_id)
        
        try:
            # Weaviate에 문서 객체 저장
            self.client.data_object.create(
                data_object=document_object,
                class_name=self.config.WEAVIATE_DOCUMENT_CLASS,
                uuid=document_uuid
            )
            logger.info(f"Added Document object: {document_uuid}")
        except Exception as e:
            # UUID 충돌 시 여기서 오류 발생 (이미 문서 객체가 존재하는 경우)
            logger.error(f"Weaviate에 문서 객체 저장 중 오류 발생 (UUID: {document_uuid}): {str(e)}")
            # 충돌이 발생하더라도 청크 저장을 계속 진행하도록 하려면 return을 제거할 수 있지만,
            # 현재는 충돌을 명확히 확인하는 것이 중요하므로 유지합니다.
            return 
            
        # 2. 배치 API를 사용하여 청크 데이터 저장
        text_class_name = self.config.WEAVIATE_TEXT_CLASS
        
        with self.client.batch as batch:
            batch.configure(
                batch_size=100,
                dynamic=True,
            )
            
            for vec in tqdm(vectors, desc="Adding chunks to Weaviate batch"):
                text_chunk_object = {
                    "text": vec.text,
                    "title": metadata.get('title', ''),
                    "source": file_path,
                    "page_num": metadata.get('page_num', 0),
                    "chunk_id": vec.chunk_id,
                    "metadata": {
                        "document_id": vec.document_id,
                        "content_type": vec.content_type,
                        **metadata
                    },
                }
                
                reference = {
                    "hasDocument": [
                        {
                            "beacon": f"weaviate://localhost/{self.config.WEAVIATE_DOCUMENT_CLASS}/{document_uuid}"
                        }
                    ]
                }
                text_chunk_object.update(reference)
                
                batch.add_data_object(
                    data_object=text_chunk_object,
                    class_name=text_class_name,
                    uuid=generate_uuid5(vec.chunk_id),
                    vector=vec.embedding.tolist()
                )
        
        logger.info(f"Successfully added {len(vectors)} chunk vectors to Weaviate for document {document_uuid}.")

# =============================================================================
# Qwen3LateChunker 클래스
# =============================================================================

class Qwen3LateChunker:
    def __init__(self, chunk_size=1000, overlap_size=100):
        self.chunk_size = chunk_size
        self.overlap_size = overlap_size
        self.embedding_model = shared_embedding
        self.vector_store = WeaviateVectorStore()
        self.document_metadata = {}
    def process_markdown_file(self, file_path: str) -> str:
        start_time = datetime.now()
        document_id = self._generate_document_id(file_path)
        
        content_processor = MixedContentProcessor()
        processed_data = content_processor.process_markdown(file_path)
        
        chunker = EnhancedSemanticChunker(self.chunk_size, self.overlap_size)
        chunks = chunker.chunk_by_content_type(processed_data)
        
        chunk_infos = self._get_chunk_boundaries(file_path, processed_data['raw_content'], chunks, document_id)
        vector_entries = self._perform_late_chunking(chunk_infos)
        
        if vector_entries:
            self.vector_store.add_vectors(vector_entries)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        self.document_metadata[document_id] = {
            'filename': os.path.basename(file_path),
            'file_path': file_path,
            'processing_time': processing_time,
            'total_chunks': len(vector_entries),
            'created_at': datetime.now()
        }
        return document_id

    def _generate_document_id(self, file_path: str) -> str:
        return hashlib.md5(file_path.encode()).hexdigest()

    def _get_chunk_boundaries(self, file_path: str, full_text: str, chunks: List[Dict], document_id: str) -> List[ChunkInfo]:
        chunk_infos = []
        current_pos = 0
        
        for i, chunk in enumerate(chunks):
            chunk_text = chunk['text']
            chunk_start = full_text.find(chunk_text.strip(), current_pos)
            if chunk_start == -1:
                chunk_start = current_pos 
            
            chunk_end = chunk_start + len(chunk_text.strip())
            
            chunk_info = ChunkInfo(
                chunk_id=f"{document_id}_chunk_{i}", 
                text=chunk_text,
                raw_text=chunk.get('raw_text', chunk_text),
                start_pos=chunk_start,
                end_pos=chunk_end,
                token_start=0,
                token_end=0,
                chunk_index=i,
                document_id=document_id,
                content_type=chunk.get('content_type', 'text'),
                metadata={'file_path': file_path} 
            )
            chunk_infos.append(chunk_info)
            current_pos = chunk_end
        return chunk_infos

    def _perform_late_chunking(self, chunk_infos: List[ChunkInfo]) -> List[VectorEntry]:
        vector_entries = []
        if self.embedding_model._model is None:
             logger.error("Shared embedding model is not loaded.")
             return []

        for info in tqdm(chunk_infos, desc="Embedding chunks"):
            try:
                embedding = self.embedding_model.generate_embedding(info.text, normalize=True)
                
            except Exception as e:
                logger.error(f"Error generating embedding for chunk {info.chunk_id}: {str(e)}")
                if self.embedding_model.vector_dimension:
                     embedding = np.ones(self.embedding_model.vector_dimension) 
                else:
                    logger.error("Embedding dimension unknown, skipping chunk.")
                    continue

            entry = VectorEntry(
                id=info.chunk_id,
                document_id=info.document_id,
                chunk_id=info.chunk_id,
                text=info.text,
                raw_text=info.raw_text,
                embedding=embedding,
                content_type=info.content_type,
                metadata=info.metadata,
                created_at=datetime.now()
            )
            vector_entries.append(entry)
        return vector_entries

    def get_document_summary(self, document_id: str) -> Dict[str, Any]:
        if document_id in self.document_metadata:
            summary = self.document_metadata[document_id].copy()
            if 'created_at' in summary and isinstance(summary['created_at'], datetime):
                summary['created_at'] = summary['created_at'].isoformat()
            return summary
        return {"document_id": document_id, "status": "not_found"}

# =============================================================================
# 벡터 검색 함수
# =============================================================================

def search_vectors(query: str, top_k: int = 5) -> List[Dict]:
    config = RAGConfig()
    client = config.get_weaviate_client()
    if not client:
        print("Weaviate 클라이언트를 초기화할 수 없습니다.")
        return []
    
    try:
        query_embedding = shared_embedding.generate_embedding(query)
        if query_embedding is None:
            raise ValueError("Query embedding generation failed.")
    except Exception as e:
        logger.error(f"Error generating query embedding: {e}")
        return []
    
    vector_search_results = (
        client.query
        .get(config.WEAVIATE_TEXT_CLASS, ["text", "metadata"])
        .with_near_vector({"vector": query_embedding.tolist()})
        .with_limit(top_k)
        .with_additional(["distance"])
        .do()
    )
    
    results = []
    text_class = config.WEAVIATE_TEXT_CLASS
    
    if "data" in vector_search_results and "Get" in vector_search_results["data"]:
        items = vector_search_results["data"]["Get"].get(text_class, [])
        for item in items:
            distance = item.get("_additional", {}).get("distance", 1.0)
            similarity_score = 1.0 - distance if 0.0 <= distance <= 1.0 else 0.0 
            
            metadata = item.get("metadata", {})
                
            results.append({
                'score': similarity_score,
                'document_id': metadata.get('document_id', ''),
                'text': item.get('text', ''),
                'content_type': metadata.get('content_type', 'text'),
            })
    return results

# =============================================================================
# Main 함수 (스키마 삭제 및 생성 순서 수정 완료)
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Qwen3 Late Chunking and Weaviate Indexing")
    parser.add_argument('--input-file', type=str, help='Input markdown file path for processing.')
    parser.add_argument('--recreate-schema', action='store_true', help='Recreate Weaviate schema.')
    parser.add_argument('--search', action='store_true', help='Interactive search mode.')
    args = parser.parse_args()

    config = RAGConfig()
    client = config.get_weaviate_client()
    
    if args.recreate_schema:
        if client:
            logger.warning(f"'{config.WEAVIATE_TEXT_CLASS}'와 '{config.WEAVIATE_DOCUMENT_CLASS}' 클래스를 재생성합니다.")
            # 참조하는 클래스(TextDocument)를 먼저 삭제
            if client.schema.exists(config.WEAVIATE_TEXT_CLASS):
                client.schema.delete_class(config.WEAVIATE_TEXT_CLASS)
                logger.info(f"클래스 삭제 완료: {config.WEAVIATE_TEXT_CLASS}")
            # 참조되는 클래스(Document)를 나중에 삭제
            if client.schema.exists(config.WEAVIATE_DOCUMENT_CLASS):
                client.schema.delete_class(config.WEAVIATE_DOCUMENT_CLASS)
                logger.info(f"클래스 삭제 완료: {config.WEAVIATE_DOCUMENT_CLASS}")
            
            # 스키마 재생성
            create_schema(client)
            logger.info("스키마 재생성이 완료되었습니다.")
        else:
            logger.error("Weaviate 클라이언트가 없어 스키마를 재생성할 수 없습니다.")
        return

    if args.search:
        while True:
            try:
                query = input("\n검색 쿼리: ")
                if query.lower() in ['exit', 'quit']:
                    break
                results = search_vectors(query)
                print(json.dumps(results, indent=2, ensure_ascii=False))
            except (KeyboardInterrupt, EOFError):
                break
        return

    if not args.input_file:
        parser.error("--input-file is required.")
        return

    try:
        if client:
            logger.info(f"Weaviate client ready at {config.WEAVIATE_URL}")
        else:
            logger.warning("Weaviate client not ready. Indexing will fail.")
        
        chunker = Qwen3LateChunker() 
        document_id = chunker.process_markdown_file(args.input_file)
        summary = chunker.get_document_summary(document_id)
        print("\nDocument Summary:")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        logger.info(f"Indexing completed. Total chunks: {summary.get('total_chunks', 0)}")
    except Exception as e:
        logger.error(f"FATAL ERROR during chunker processing: {e}")

if __name__ == "__main__":
    main()