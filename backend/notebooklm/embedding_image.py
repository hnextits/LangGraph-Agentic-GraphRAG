### 명령어 cd /home/nextits2/.conda/envs/workbox
### python embedding_image.py --json data/combined_metadata_2.json --type image
### python embedding_image.py --json data/test_text_2.json --type text

# python /home/jeonghs/workspace/nextitslm/backend/notebooklm/embedding_image.py --type image --recreate

import os
import re
import json
import time
import numpy as np
import requests
import torch
import logging
import hashlib
import uuid
import weaviate
from datetime import datetime
from typing import List, Dict, Tuple, Any, Optional
from weaviate.util import generate_uuid5
from PIL import Image
from transformers import AutoTokenizer, AutoModel, AutoProcessor
from tqdm import tqdm
from shared_embedding import shared_embedding

# config.py 파일이 있는 디렉토리를 sys.path에 추가
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import RAGConfig
from weaviate_utils import create_schema, batch_import_text_documents

# 로깅 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

class VectorDBService:
    """
    RAG 시스템을 위한 벡터 DB 서비스
    이미지와 텍스트 메타데이터를 위한 별도의 FAISS 인덱스를 관리하며, 
    임베딩 생성 및 벡터 DB 저장/검색 기능을 제공합니다.
    """
    def __init__(self, 
                 model_name="Qwen/Qwen3-Embedding-4B",
                 device=None,
                 vector_dimension=2560,
                 recreate_schema=False,
                 content_type="image"):
        """
        벡터 DB 서비스 초기화 - Weaviate 기반
        
        Args:
            model_name: 사용할 멀티모달 모델 이름
            device: 사용할 디바이스 (None이면 자동 감지)
            vector_dimension: 벡터 차원 수
            recreate_schema: True이면 기존 스키마를 삭제하고 새로 생성
        """
        # RAG 구성 가져오기
        self.config = RAGConfig()
        
        # 기본 설정
        self.model_name = model_name
        self.device = device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        self.vector_dimension = vector_dimension
        self.recreate_schema = recreate_schema
        self.content_type = content_type
        self.embedding_model = shared_embedding
        
        # Weaviate는 DB에 직접 메타데이터를 저장하므로 로컬 리스트가 필요 없습니다.
        
        
        # Weaviate 클라이언트 초기화
        self.client = self.config.get_weaviate_client()
        if not self.client:
            logger.error("Weaviate 클라이언트를 초기화할 수 없습니다.")
            raise RuntimeError("Weaviate 클라이언트 초기화 실패")
            
        # Weaviate 스키마 초기화
        self._init_schema(self.content_type)

        # 공유 임베딩 모델 인스턴스 초기화
    

    
    def _init_schema(self, content_type: str):
        """Weaviate 스키마 초기화 (v4 API)"""
        from weaviate.classes.config import Configure, Property, DataType
        
        try:
            # 텍스트 문서 스키마 처리
            text_class_name = self.config.WEAVIATE_TEXT_CLASS
            if content_type == 'text' and self.recreate_schema and self.client.collections.exists(text_class_name):
                logger.warning(f"기존 텍스트 클래스 '{text_class_name}'를 삭제합니다.")
                self.client.collections.delete(text_class_name)
            create_schema(self.client, recreate=False)

            # 이미지 클래스 스키마 처리
            image_class_name = self.config.WEAVIATE_IMAGE_CLASS
            if content_type == 'image' and self.recreate_schema and self.client.collections.exists(image_class_name):
                logger.warning(f"기존 이미지 클래스 '{image_class_name}'를 삭제합니다.")
                self.client.collections.delete(image_class_name)

            if not self.client.collections.exists(image_class_name):
                logger.info(f"'{image_class_name}' 클래스를 새로 생성합니다.")
                self.client.collections.create(
                    name=image_class_name,
                    description="이미지 메타데이터와 임베딩을 저장하는 클래스",
                    vectorizer_config=Configure.Vectorizer.none(),
                    properties=[
                        Property(name="title", data_type=DataType.TEXT),
                        Property(name="caption", data_type=DataType.TEXT),
                        Property(name="text", data_type=DataType.TEXT),
                        Property(name="image_path", data_type=DataType.TEXT),
                        Property(name="page_num", data_type=DataType.INT),
                        Property(name="con_type", data_type=DataType.TEXT),
                        Property(name="metadata", data_type=DataType.OBJECT,
                            nested_properties=[
                                Property(name="document_id", data_type=DataType.TEXT),
                                Property(name="content_type", data_type=DataType.TEXT),
                                Property(name="file_path", data_type=DataType.TEXT)
                            ]
                        ),
                        Property(name="tags", data_type=DataType.TEXT_ARRAY)
                    ]
                )
                logger.info(f"이미지 클래스 '{image_class_name}' 생성 완료")
            else:
                logger.info(f"이미지 클래스 '{image_class_name}'가 이미 존재합니다.")

            logger.info("Weaviate 스키마 초기화 완료")
            
        except Exception as e:
            logger.error(f"Weaviate 스키마 초기화 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    def generate_text_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        SharedEmbeddingModel을 사용하여 텍스트 임베딩 생성

        Args:
            text: 임베딩할 텍스트

        Returns:
            텍스트 임베딩 벡터 (numpy 배열) 또는 실패 시 None
        """
        if not text or not isinstance(text, str) or not text.strip():
            logger.warning("임베딩할 텍스트가 비어있어 건너뜁니다.")
            return None

        try:
            # SharedEmbeddingModel의 generate_embedding 메서드 사용
            embedding = self.embedding_model.generate_embedding(
                text.strip(),
                normalize=True  # SharedEmbeddingModel에서는 normalize를 사용함
            )
            # numpy 배열 반환 확인
            if embedding is not None:
                return embedding
            else:
                logger.error("임베딩 생성 결과가 None입니다.")
                return None
        except Exception as e:
            logger.error(f"임베딩 생성 중 오류 발생: {e}", exc_info=True)
            return None
    
    
    def add_to_index(self, embedding: np.ndarray, metadata: Dict[str, Any], content_type: str = "image"):
        """
        이미지 및 차트 메타데이터 임베딩과 메타데이터를 Weaviate에 추가
        
        Args:
            embedding: 추가할 임베딩 벡터
            metadata: 해당 임베딩의 메타데이터
            content_type: 콘텐츠 유형 ("image" 또는 "chart")
            
        Returns:
            추가 성공 여부 (bool)
        """
        # 이미지와 차트 모두 동일한 클래스에 추가 (con_type으로 구분)
        if content_type not in ["image", "chart"]:
            logger.error(f"이 시스템은 이미지와 차트 메타데이터만 지원합니다. 현재 유형: {content_type}")
            return False
            
        try:
            # 1D 배열로 변환 (Weaviate는 1D 배열 형태의 리스트 기대)
            if len(embedding.shape) > 1:
                embedding = embedding.flatten()
            
            # NaN/Inf 값 검사
            if not np.isfinite(embedding).all():
                logger.warning("경고: 임베딩에 NaN 또는 Inf 값이 포함되어 있습니다. 이 항목은 건너뚽니다.")
                return False
            
            # 정규화
            norm = np.linalg.norm(embedding)
            if norm > 1e-10:  # 0으로 나누기 방지
                embedding = embedding / norm
            
            # 이미지 클래스 이름 가져오기
            image_class_name = self.config.WEAVIATE_IMAGE_CLASS
            
            # 이미지 경로를 기반으로 결정론적 UUID 생성
            image_path = metadata.get("image_path", "") or metadata.get("file_path", "")
            if not image_path:
                logger.error("UUID를 생성할 이미지 경로가 없어 이 항목을 건너뜁니다.")
                return False
            object_uuid = generate_uuid5(image_path)
                
            # con_type 설정 (없으면)
            if 'con_type' not in metadata:
                metadata['con_type'] = content_type
                
            # page_num을 정수형으로 변환
            page_num = metadata.get("page_num", 0)
            if isinstance(page_num, str):
                try:
                    page_num = int(page_num)
                except (ValueError, TypeError):
                    page_num = 0
            
            # metadata에서 필요한 필드만 추출
            filtered_metadata = {
                "document_id": metadata.get("id", ""),
                "content_type": metadata.get("con_type", content_type),
                "file_path": image_path,
                "text": metadata.get("text", "") # text 필드 추가
            }
            
            # 데이터 객체 준비
            data_object = {
                "title": metadata.get("title", ""),
                "caption": metadata.get("caption", ""),
                "text": metadata.get("text", ""),
                "image_path": image_path,
                "page_num": page_num,  # 정수형으로 변환된 page_num 사용
                "con_type": metadata.get("con_type", content_type),
                "metadata": filtered_metadata  # 필터링된 메타데이터 사용
            }
            
            # 태그가 있으면 추가
            if "tags" in metadata and isinstance(metadata["tags"], list):
                data_object["tags"] = metadata["tags"]
                
            # Weaviate에 객체 추가 (v4 API)
            try:
                collection = self.client.collections.get(image_class_name)
                collection.data.insert(
                    properties=data_object,
                    uuid=object_uuid,
                    vector=embedding.tolist()
                )
                logger.info(f"이미지 객체 추가 완료: ID {object_uuid}")
                return True
            except Exception as insert_error:
                logger.error(f"Weaviate 객체 추가 오류: {insert_error}")
                return False
            
        except Exception as e:
            logger.error(f"Weaviate에 항목 추가 중 오류 발생: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    
    def _process_image_data(self, data, image_base_path="static"):
        """
        이미지 메타데이터 처리 및 Weaviate 인덱싱 - 개선된 버전
        임베딩 차별화를 위한 텍스트 처리 및 메타데이터 활용 강화
        """
        indexed_count = 0
        skipped_count = 0
        empty_text_count = 0
        
        logger.info(f"이미지 메타데이터 처리 시작: 총 {len(data)}개 항목")
        
        # 배치 처리를 위한 준비
        batch_size = 10  # 배치 크기 설정
        current_batch = []
        
        for item in tqdm(data, desc="이미지 메타데이터 처리"):
            try:
                if 'metadata' in item:
                    metadata = item['metadata'].copy()
                else:
                    metadata = item.copy()
                
                # 고유 ID 확인 (없으면 생성)
                item_id = metadata.get('id', '')
                if not item_id:
                    item_id = str(uuid.uuid4())  # 전체 UUID 사용 (Weaviate에 적합)
                    metadata['id'] = item_id
                
                # 이미지 경로 확인
                image_path = metadata.get('file_path') or metadata.get('image_path')
                if not image_path or not os.path.exists(image_path):
                    logger.warning(f"[건너뚰기] 이미지 파일을 찾을 수 없음: {item_id}")
                    skipped_count += 1
                    continue
                
                # ================================================================= #
                # 텍스트 및 메타데이터 추출 및 전처리 (개선된 버전)
                # ================================================================= #
                
                # 1. 필요한 필드만 추출 (title, page_num, file_path, text)
                text = metadata.get('text', '')
                text = text.strip() if isinstance(text, str) else ''
                
                title = metadata.get('title', '')
                title = title.strip() if isinstance(title, str) else ''
                
                page_num = metadata.get('page_num', 0)  # 숫자로 변환
                if not isinstance(page_num, int):
                    try:
                        page_num = int(page_num) if page_num else 0
                    except (ValueError, TypeError):
                        page_num = 0
                        
                file_path = image_path  # 이미 위에서 추출한 image_path 사용
                
                # 2. text 필드가 비어있는 경우 바로 건너뚰기
                if not text:
                    logger.warning(f"[건너뚰기] ID {item_id}: text 필드가 비어있음")
                    empty_text_count += 1
                    continue
                
                # 3. 텍스트 정규화
                # 공백 및 특수문자 정규화
                text = re.sub(r'\s+', ' ', text).strip()
                
                # 텍스트 해시 생성 (로깅용)
                text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
                
                # 4. 텍스트 보강 - 제목이 있고 본문에 제목이 포함되지 않은 경우 제목을 텍스트 앞에 추가
                if title and title not in text:
                    # 제목을 텍스트 앞에 추가하여 중요도 강화
                    text = f"{title}\n\n{text}"
                
                # ================================================================= #
                
                # 임베딩 생성
                logger.debug(f"ID {item_id} 임베딩 생성 시작: 텍스트 길이 {len(text)}자")
                embedding = self.generate_text_embedding(text)
                
                # 임베딩 유효성 검사
                if embedding is None or not np.any(embedding):
                    logger.warning(f"[경고] ID {item_id}: 유효하지 않은 임베딩 생성됨")
                    skipped_count += 1
                    continue
                
                # con_type 설정 - 기존 con_type이 있으면 유지, 없으면 타입 추론
                if 'con_type' not in metadata:
                    # 파일명이나 경로에 'chart'가 포함되어 있으면 chart 타입으로 설정
                    if 'chart' in image_path.lower() or ('title' in metadata and 'chart' in metadata.get('title', '').lower()):
                        metadata['con_type'] = 'chart'
                    else:
                        metadata['con_type'] = 'image'
                
                # 임베딩 통계 계산 (디버깅용)
                embedding_norm = np.linalg.norm(embedding)
                embedding_mean = np.mean(embedding)
                embedding_std = np.std(embedding)
                logger.debug(f"ID {item_id} 임베딩 생성 완료: 노름={embedding_norm:.4f}, 평균={embedding_mean:.4f}, 표준편차={embedding_std:.4f}")
                
                # Weaviate에 추가할 데이터 객체 준비
                content_type = metadata.get('con_type', 'image')
                
                # 인덱스에 추가
                if self.add_to_index(embedding, metadata, content_type):
                    indexed_count += 1
                    if indexed_count % 10 == 0:
                        logger.info(f"진행 상황: {indexed_count}개 인덱싱 완료 (타입: {content_type})")

            except Exception as e:
                import traceback
                logger.error(f"이미지 메타데이터 처리 중 오류 발생: {str(e)}")
                logger.error(f"문제 항목: {item.get('metadata', {}).get('id', 'unknown')}")
                logger.error(traceback.format_exc())
                skipped_count += 1
        
        # 처리 결과 요약
        logger.info(f"이미지 메타데이터 인덱싱 완료: 총 {len(data)}개 중 {indexed_count}개 성공, {skipped_count}개 건너뚰")
        logger.info(f"건너뚰 이유: 빈 텍스트 {empty_text_count}개, 오류 {skipped_count - empty_text_count}개")
        
        return indexed_count
    
    def process_json_data(self, json_path, image_base_path="static", append_mode=True, content_type="image"):
        """
        이미지 및 차트 메타데이터 JSON 파일을 처리하여 벡터 DB에 저장
        파일 경로나 디렉토리 경로를 받아 처리
        
        Args:
            json_path: JSON 파일 경로 또는 JSON 파일이 있는 디렉토리 경로
            image_base_path: 이미지 파일 기본 경로 (사용되지 않음)
            append_mode: True이면 기존 인덱스에 추가, False이면 덮어쓰기
            content_type: 처리할 데이터 유형 ("image" 또는 "chart")
            
        Returns:
            인덱싱된 항목 수
        """
        if content_type not in ["image", "chart"]:
            raise ValueError("이 시스템은 이미지와 차트 메타데이터 처리를 지원합니다. content_type='image' 또는 'chart'를 사용하세요.")
        
        # 경로 존재 확인
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"경로를 찾을 수 없습니다: {json_path}")
        
        # 디렉토리인지 파일인지 확인
        total_indexed = 0
        if os.path.isdir(json_path):
            print(f"디렉토리 처리 시작: {json_path}")
            json_files = [os.path.join(json_path, f) for f in os.listdir(json_path) 
                         if f.lower().endswith('.json')]
            
            if not json_files:
                print(f"경고: {json_path} 디렉토리에 JSON 파일이 없습니다.")
                return 0
                
            print(f"발견된 JSON 파일 수: {len(json_files)}")
            
            # 처음 파일은 append_mode 적용, 나머지는 무조건 추가
            for i, json_file in enumerate(json_files):
                print(f"\n[{i+1}/{len(json_files)}] 파일 처리 중: {os.path.basename(json_file)}")
                current_append_mode = append_mode if i == 0 else True
                try:
                    indexed = self._process_single_json_file(json_file, image_base_path, current_append_mode, content_type)
                    total_indexed += indexed
                except Exception as e:
                    print(f"경고: {json_file} 처리 중 오류 발생: {str(e)}")
                    import traceback
                    traceback.print_exc()
            
            return total_indexed
        else:
            # 단일 파일 처리
            return self._process_single_json_file(json_path, image_base_path, append_mode, content_type)
    
    def process_directory_recursively(self, dir_path, append_mode=True):
        """
        디렉토리를 재귀적으로 탐색하며 모든 파일을 처리
        """
        total_indexed = 0
        for root, _, files in os.walk(dir_path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    if file.lower().endswith('.json'):
                        print(f"Processing JSON file: {file_path}")
                        indexed = self._process_single_json_file(file_path, '', append_mode, 'image')
                        total_indexed += indexed
                        append_mode = True  # 첫 파일 이후에는 항상 추가 모드
                    elif file.lower().endswith('.txt'):
                        print(f"Processing text file: {file_path}")
                        with open(file_path, 'r', encoding='utf-8') as f:
                            text_content = f.read()
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            text_content = f.read()
                        metadata = {
                            'source': file_path,
                            'type': 'text',
                            'title': os.path.basename(file_path)
                        }
                        if self.add_text_embedding(text_content, metadata):
                            total_indexed += 1

                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
                    import traceback
                    traceback.print_exc()

        return total_indexed




    def add_text_embedding(self, text, metadata):
        """
        주어진 텍스트에 대한 임베딩을 생성하고 DB에 추가
        """
        if not text or not isinstance(text, str):
            print("Warning: Invalid text for embedding. Skipping.")
            return False

        try:
            embedding = self.generate_text_embedding(text)
            if embedding is None:
                return False
            if isinstance(embedding, list):
                embedding = np.array(embedding, dtype=np.float32)
            if embedding is None:
                return False

            # 임베딩 유효성 검사
            if embedding is None or not np.any(embedding):
                print(f"[경고] 유효하지 않은 임베딩 생성됨")
                return False

            # 임베딩 통계 계산 (디버깅용)
            embedding_norm = np.linalg.norm(embedding)
            embedding_mean = np.mean(embedding)
            embedding_std = np.std(embedding)
            
            print(f"텍스트 임베딩 생성 완료: 노름={embedding_norm:.4f}, 평균={embedding_mean:.4f}, 표준편차={embedding_std:.4f}")
            
            # 메타데이터 정리 및 추가 정보
            metadata['text'] = text[:500] + ('...' if len(text) > 500 else '')  # 설명 필드 추가 (잘라서)
            metadata['embedding'] = embedding  # 임베딩 벡터 저장 (검색 시 활용)
            
            # 인덱스에 추가
            if self.add_to_index(embedding, metadata, "text"):
                print(f"텍스트 인덱싱 완료: {metadata.get('source', 'unknown')}")
                return True
            else:
                return False
        except Exception as e:
            print(f"Error adding text embedding: {e}")
            return False

    def _process_single_json_file(self, json_file_path, image_base_path="static", append_mode=True, content_type="image"):
        """
        이미지 및 차트 메타데이터 JSON 파일을 처리하여 벡터 DB에 저장
        
        Args:
            json_file_path: JSON 파일 경로
            image_base_path: 이미지 파일 기본 경로 (사용되지 않음)
            append_mode: True이면 기존 인덱스에 추가, False이면 덮어쓰기
            content_type: 처리할 데이터 유형 ("image" 또는 "chart")
            
        Returns:
            인덱싱된 항목 수
        """
        # 데이터 로드
        print(f"데이터 파일 로드 중: {json_file_path}")
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"JSON 파일 로드 완료: {json_file_path}")
        except Exception as e:
            raise ValueError(f"JSON 파일 로드 실패: {str(e)}")
        
        # 이미지 메타데이터 추출
        
        # 데이터 구조 확인
        items = []
        
        # 데이터 구조 분석 및 처리
        if isinstance(data, dict) and "metadata" in data:
            print("JSON 구조: metadata 키 포함 (객체 형태)")
            # metadata 내의 각 아이템 처리
            for key, item in data["metadata"].items():
                item["id"] = key
                items.append(item)
        elif isinstance(data, list):
            print("JSON 구조: 배열 형태")
            # 배열 내 각 항목 처리
            for item_obj in data:
                # 각 항목에 metadata 키가 있는지 확인
                if isinstance(item_obj, dict) and "metadata" in item_obj:
                    item = item_obj["metadata"]
                    # id가 없으면 임의로 생성
                    if "id" not in item:
                        item["id"] = f"item_{len(items)}"
                    items.append(item)
                elif isinstance(item_obj, dict):
                    # metadata 키가 없으면 항목 자체를 사용
                    # id가 없으면 임의로 생성
                    if "id" not in item_obj:
                        item_obj["id"] = f"item_{len(items)}"
                    items.append(item_obj)
        else:
            print("JSON 형식 오류: 지원되지 않는 형식입니다. 객체 내 'metadata' 필드 또는 배열 형태여야 합니다.")
            return 0
        
        print(f"처리할 항목 수: {len(items)}")
        
        # 이미지 메타데이터 처리
        if content_type != "image" and content_type != "chart":
            raise ValueError("이 시스템은 이미지와 차트 메타데이터 처리를 지원합니다.")
        
        if not append_mode:
            # 덮어쓰기 모드인 경우 Weaviate 클래스 재생성
            logger.info("스키마 재생성 모드")
            # 스키마 재생성 플래그를 설정하고 스키마 초기화
            self.recreate_schema = True
            self._init_schema(content_type)
        
        # 이미지 데이터 처리
        indexed_count = self._process_image_data(items, image_base_path)
        
        # Weaviate는 자동으로 저장하므로 별도의 저장 과정이 필요 없음
        if indexed_count > 0:
            logger.info(f"Weaviate에 {indexed_count}개 항목 인덱싱 완료")
        
        return indexed_count
    
    def get_text_embedding(self, text: str) -> np.ndarray:
        """
        텍스트 임베딩 생성 (RAG 시스템에서 사용)
        
        Args:
            text: 임베딩할 텍스트
            
        Returns:
            텍스트 임베딩 벡터 (numpy 배열)
        """
        return self.generate_text_embedding(text)
        
    def get_image_embedding(self, image_path: str) -> np.ndarray:
        """
        이미지 임베딩 생성 (RAG 시스템에서 사용)
        
        Args:
            image_path: 이미지 파일 경로
            
        Returns:
            이미지 임베딩 벡터 (numpy 배열)
        """
        return self.generate_image_embedding(image_path)
        
    def search_in_index(self, query_embedding, content_type="image", top_k=5):
        """
        Weaviate를 사용하여 유사도 검색 수행 (기존 FAISS/PyTorch 방식에서 마이그레이션)
        
        Args:
            query_embedding: 검색 쿼리 임베딩
            content_type: 검색할 콘텐츠 유형 ("이미지"만 지원)
            top_k: 반환할 최대 결과 수
            
        Returns:
            (distances, indices): 거리와 인덱스의 튜플 (기존 FAISS 호환성 유지)
        """
        import numpy as np
        
        if content_type != "image":
            raise ValueError("이 시스템은 이미지 메타데이터 처리만 지원합니다.")
        
        # Weaviate 사용 여부 확인
        use_weaviate = True
        
        if use_weaviate:
            try:
                # Weaviate 클라이언트 초기화
                from config import RAGConfig
                config = RAGConfig()
                client = config.get_weaviate_client()
                
                if not client:
                    logger.warning("Weaviate 클라이언트를 초기화할 수 없습니다. FAISS 방식으로 폴백합니다.")
                    # FAISS 방식으로 폴백
                    if hasattr(self, 'image_index'):
                        return self.image_index.search(query_embedding.astype('float32'), top_k)
                    else:
                        return np.array([]), np.array([])
                
                # 쿼리 임베딩을 리스트로 변환
                if len(query_embedding.shape) == 1:
                    query_vector = query_embedding.tolist()
                else:
                    query_vector = query_embedding[0].tolist()
                
                # Weaviate 벡터 검색 수행 (v4 API)
                collection = client.collections.get(config.WEAVIATE_IMAGE_CLASS)
                
                response = collection.query.near_vector(
                    near_vector=query_vector,
                    limit=top_k,
                    return_metadata=['distance'],
                    return_properties=["file_path", "caption", "image_id", "content_type"]
                )
                
                # 결과 파싱 및 FAISS 형식으로 변환
                distances = []
                indices = []
                
                for i, obj in enumerate(response.objects):
                    # Weaviate의 distance를 가져오기
                    distance = obj.metadata.distance if obj.metadata.distance is not None else 1.0
                    # 거리를 유사도 점수로 변환 (1 - 거리)
                    similarity = 1.0 - distance if distance <= 1.0 else 0.0
                    
                    # image_id에서 인덱스 추출 (예: "img_42_..." -> 42)
                    image_id = obj.properties.get("image_id", f"img_{i}_unknown")
                    try:
                        index = int(image_id.split("_")[1])
                    except (IndexError, ValueError):
                        index = i
                    
                    distances.append(similarity)
                    indices.append(index)
                    
                    logger.debug(f"Weaviate 검색 결과 {i+1}: ID={obj.uuid}, 유사도={similarity:.4f}")
                
                # FAISS 형식과 호환되도록 numpy 배열로 변환
                if not distances:  # 결과가 없으면 빈 배열 반환
                    return np.array([]), np.array([])
                    
                client.close()
                return np.array(distances), np.array(indices)
                
            except Exception as e:
                logger.error(f"Weaviate 검색 중 오류 발생: {str(e)}")
                # 오류 발생 시 빈 결과 반환
                return np.array([]), np.array([])
            
            
    def search_images(self, query: str, top_k: int = 5, content_type: str = None) -> List[Dict]:
        """
        이미지 검색 - 텍스트 쿼리를 사용하여 Weaviate에서 이미지 메타데이터 검색
        
        Args:
            query: 검색 쿼리 텍스트
            top_k: 반환할 결과 수
            content_type: 콘텐츠 타입 필터 ("image" 또는 "chart", None이면 모든 타입)
            
        Returns:
            검색 결과 목록
        """
        if not self.client:
            logger.error("Weaviate 클라이언트가 초기화되지 않았습니다.")
            return []
        
        try:
            # 쿼리 임베딩 생성
            query_embedding = self.generate_text_embedding(query)
            
            # 이미지 클래스 이름 가져오기 (v4 API)
            image_class_name = self.config.WEAVIATE_IMAGE_CLASS
            collection = self.client.collections.get(image_class_name)
            
            # 콘텐츠 타입 필터 적용
            filters = None
            if content_type:
                from weaviate.classes.query import Filter
                filters = Filter.by_property("con_type").equal(content_type)
            
            # 벡터 검색 실행
            response = collection.query.near_vector(
                near_vector=query_embedding.tolist(),
                limit=top_k,
                filters=filters,
                return_metadata=['distance'],
                return_properties=["title", "caption", "text", "image_path", "page_num", "con_type", "metadata"]
            )
            
            # 결과 처리
            processed_results = []
            for i, obj in enumerate(response.objects):
                # 거리를 유사도 점수로 변환 (1 - 거리)
                distance = obj.metadata.distance if obj.metadata.distance is not None else 1.0
                similarity_score = 1.0 - distance if distance <= 1.0 else 0.0
                
                processed_results.append({
                    'score': similarity_score,
                    'index': i,
                    'title': obj.properties.get("title", ""),
                    'caption': obj.properties.get("caption", ""),
                    'text': obj.properties.get("text", ""),
                    'image_path': obj.properties.get("image_path", ""),
                    'page_num': obj.properties.get("page_num", 0),
                    'con_type': obj.properties.get("con_type", "image"),
                    'metadata': obj.properties.get("metadata", {})
                })
            
            return processed_results
            
        except Exception as e:
            logger.error(f"이미지 검색 중 오류 발생: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []
            
    def check_weaviate_status(self) -> bool:
        """
        Weaviate 연결 및 스키마 상태 확인
        
        Returns:
            연결 및 스키마 상태 정상 여부
        """
        try:
            if not self.client:
                logger.error("Weaviate 클라이언트가 초기화되지 않았습니다.")
                return False
            
            # Weaviate 서버 상태 확인 (v4 API)
            if not self.client.is_ready():
                logger.error("Weaviate 서버에 연결할 수 없습니다.")
                return False
            
            logger.info("Weaviate 서버 연결 정상")
            
            # 이미지 클래스 존재 확인
            image_class_name = self.config.WEAVIATE_IMAGE_CLASS
            class_exists = self.client.collections.exists(image_class_name)
            
            if not class_exists:
                logger.warning(f"이미지 클래스 {image_class_name}가 존재하지 않습니다. 스키마를 초기화해야 합니다.")
                return False
            
            # 클래스에 저장된 객체 수 확인
            try:
                collection = self.client.collections.get(image_class_name)
                result = collection.aggregate.over_all(total_count=True)
                count = result.total_count
                logger.info(f"이미지 클래스 {image_class_name}에 {count}개의 객체가 저장되어 있습니다.")
            except Exception as count_error:
                logger.warning(f"객체 수 확인 중 오류: {count_error}")
            
            return True
            
        except Exception as e:
            logger.error(f"Weaviate 상태 확인 중 오류 발생: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
            
    def load_index(self):
        """
        Weaviate의 연결 상태를 확인합니다.
        Weaviate는 실시간으로 데이터를 다루므로 별도의 "로드" 과정이 필요 없습니다.
        이 메서드는 시스템 시작 시 DB 연결을 확인하는 용도로 사용됩니다.
        """
        logger.info("Weaviate 연결 상태 확인 중...")
        is_ready = self.check_weaviate_status()
        if is_ready:
            logger.info("Weaviate가 준비되었습니다.")
        else:
            logger.error("Weaviate 준비에 실패했습니다. 설정을 확인하세요.")
        return is_ready

# 사용 예시
if __name__ == "__main__":
    import argparse

    # 명령행 인수 처리
    parser = argparse.ArgumentParser(description="이미지 및 텍스트 데이터 임베딩 및 Weaviate 저장 시스템")
    parser.add_argument("--json", "-j", help="처리할 JSON 파일 경로 또는 디렉토리")
    parser.add_argument("--model", "-m", default="Qwen/Qwen3-Embedding-4B", help="사용할 임베딩 모델 이름")
    parser.add_argument("--recreate", action="store_true", help="기존 Weaviate 스키마를 삭제하고 새로 생성합니다.")
    parser.add_argument("--type", "-t", choices=["image", "text"], default="image", help="처리할 데이터 유형 (image 또는 text)")
    parser.add_argument("--delete-type", "-dt", choices=["image", "text"], help="삭제할 스키마의 데이터 유형 (image 또는 text)")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그를 출력합니다.")

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # 벡터 DB 서비스 초기화
    vector_db_service = VectorDBService(
        model_name=args.model,
        recreate_schema=args.recreate,
        content_type=args.type
    )

    # JSON 파일 또는 디렉토리 처리
    if args.json:
        try:
            # --recreate 플래그가 있으면 append_mode는 False, 아니면 True
            append_mode = not args.recreate
            
            if os.path.isdir(args.json):
                indexed_count = vector_db_service.process_directory_recursively(
                    args.json,
                    append_mode=append_mode
                )
            else:
                indexed_count = vector_db_service.process_json_data(
                    args.json, 
                    append_mode=append_mode,
                    content_type=args.type
                )
            
            if indexed_count > 0:
                logger.info(f"총 {indexed_count}개의 항목을 성공적으로 인덱싱했습니다.")
            else:
                logger.warning("인덱싱된 항목이 없습니다. 입력 데이터를 확인하세요.")

        except Exception as e:
            logger.error(f"데이터 처리 중 심각한 오류 발생: {e}", exc_info=True)
    
    # 사용법 안내
    if not args.json:
        parser.print_help()
        print("\n예시:")
        print("  # 이미지 메타데이터 JSON 파일 처리 (기존 스키마에 추가)")
        print("  python embedding_image.py --json /path/to/image_metadata.json --type image")
        print("\n  # 디렉토리 내의 모든 JSON/TXT 파일 재귀적으로 처리 (스키마 재생성)")
        print("  python embedding_image.py --json /home/jeonghs/workspace/nextitslm/backend/nextits_data/Results/5.Completion_results/image --recreate")
