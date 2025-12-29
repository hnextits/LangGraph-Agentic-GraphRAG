#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Weaviate 유틸리티 함수 - 스키마 생성 및 관리
"""

import logging
import hashlib
from pathlib import Path
import weaviate
from typing import Dict, Any, List, Optional, Set
from weaviate.util import generate_uuid5
# 로깅 설정
logger = logging.getLogger(__name__)
# [수정] config 임포트 방식을 routes.py와 유사하게 변경 시도
try:
    from config import RAGConfig
    logger.info("weaviate_utils: config.py에서 RAGConfig 로드 성공.")
except ImportError:
    logger.error("weaviate_utils: config.py를 찾을 수 없습니다. 임시 RAGConfig를 사용합니다.")
    class RAGConfig:
        WEAVIATE_URL = "http://127.0.0.1:8080" # 기본값 설정
        WEAVIATE_TEXT_CLASS = "TextDocument"
        WEAVIATE_IMAGE_CLASS = "ImageDocument"
        WEAVIATE_VECTORIZER = "multi-modal-clip" # 기본값 설정
        WEAVIATE_BATCH_SIZE = 100 # 기본값 설정
        def get_weaviate_client(self):
            try:
                client = weaviate.Client(url=self.WEAVIATE_URL)
                if client.is_live(): return client
                else: logger.error(f"Weaviate is not live at {self.WEAVIATE_URL}"); return None
            except Exception as e:
                logger.error(f"Weaviate 클라이언트 초기화 중 오류 발생: {str(e)}"); return None



# [수정] routes.py와 동일한 방식으로 기본 경로 설정
# .../backend/notebooklm/weaviate_utils.py -> .../backend/
BASE_DIR = Path(__file__).resolve().parent.parent
# .../backend/nextits_data/
NEXTITS_DATA_DIR = BASE_DIR / "nextits_data"
logger.info(f"weaviate_utils: NEXTITS_DATA_DIR 설정됨: {NEXTITS_DATA_DIR}")


def create_schema(client, recreate: bool = False) -> bool:
    """필요한 Weaviate 스키마(TextDocument, ImageDocument) 생성 (v4 API)"""
    from weaviate.classes.config import Configure, Property, DataType
    
    config = RAGConfig()

    if client is None:
        logger.error("Weaviate 클라이언트가 None입니다.")
        return False

    try:
        if recreate:
            logger.warning("기존 스키마를 삭제하고 새로 생성합니다.")
            # v4: 모든 collection 삭제
            for collection in client.collections.list_all():
                client.collections.delete(collection)

        # TextDocument collection 생성
        if not client.collections.exists(config.WEAVIATE_TEXT_CLASS):
            client.collections.create(
                name=config.WEAVIATE_TEXT_CLASS,
                description="텍스트 문서 청크",
                vectorizer_config=Configure.Vectorizer.none(),
                properties=[
                    Property(name="text", data_type=DataType.TEXT, description="문서 텍스트 내용"),
                    Property(name="title", data_type=DataType.TEXT, description="문서 제목"),
                    Property(name="source", data_type=DataType.TEXT, description="문서 출처"),
                    Property(name="page_num", data_type=DataType.INT, description="페이지 번호"),
                    Property(name="chunk_id", data_type=DataType.TEXT, description="청크 고유 ID", skip_vectorization=True, index_searchable=True),
                    Property(name="document_uuid", data_type=DataType.TEXT, description="연결된 문서 UUID"),
                    Property(name="metadata", data_type=DataType.OBJECT, description="추가 메타데이터",
                        nested_properties=[
                            Property(name="document_id", data_type=DataType.TEXT),
                            Property(name="content_type", data_type=DataType.TEXT),
                            Property(name="file_path", data_type=DataType.TEXT),
                        ]
                    ),
                ]
            )
            logger.info("스키마 클래스 생성 완료: %s", config.WEAVIATE_TEXT_CLASS)
        else:
            logger.info("%s 클래스가 이미 존재합니다", config.WEAVIATE_TEXT_CLASS)

        # ImageDocument collection 생성
        if not client.collections.exists(config.WEAVIATE_IMAGE_CLASS):
            client.collections.create(
                name=config.WEAVIATE_IMAGE_CLASS,
                description="이미지 청크",
                vectorizer_config=Configure.Vectorizer.none(),
                properties=[
                    Property(name="caption", data_type=DataType.TEXT, description="이미지 캡션"),
                    Property(name="title", data_type=DataType.TEXT, description="이미지 제목"),
                    Property(name="file_path", data_type=DataType.TEXT, description="이미지 파일 경로"),
                    Property(name="content_type", data_type=DataType.TEXT, description="콘텐츠 타입"),
                    Property(name="image_id", data_type=DataType.TEXT, description="이미지 고유 ID", skip_vectorization=True, index_searchable=True),
                    Property(name="tags", data_type=DataType.TEXT_ARRAY, description="이미지 태그"),
                    Property(name="document_uuid", data_type=DataType.TEXT, description="연결된 문서 UUID"),
                    Property(name="metadata", data_type=DataType.OBJECT, description="추가 메타데이터",
                        nested_properties=[
                            Property(name="document_id", data_type=DataType.TEXT),
                            Property(name="content_type", data_type=DataType.TEXT),
                            Property(name="file_path", data_type=DataType.TEXT),
                        ]
                    ),
                ]
            )
            logger.info("스키마 클래스 생성 완료: %s", config.WEAVIATE_IMAGE_CLASS)
        else:
            logger.info("%s 클래스가 이미 존재합니다", config.WEAVIATE_IMAGE_CLASS)

        return True

    except Exception as exc:
        logger.error("Weaviate 스키마 생성 중 오류 발생: %s", exc, exc_info=True)
        return False

def batch_import_text_documents(client, documents: List[Dict[str, Any]], document_uuid: str = None) -> bool:
    """
    텍스트 문서를 배치로 Weaviate에 임포트 (v4 API)
    """
    config = RAGConfig()

    try:
        text_collection = client.collections.get(config.WEAVIATE_TEXT_CLASS)

        with text_collection.batch.dynamic() as batch:
            for i, doc in enumerate(documents):
                chunk_id = doc.get("chunk_id", f"chunk_{i}_{hash(doc.get('text', '')[:50])}")

                properties = {
                    "text": doc.get("text", ""),
                    "title": doc.get("title", ""),
                    "source": doc.get("source", ""),
                    "page_num": doc.get("page_num", 0),
                    "chunk_id": chunk_id,
                    "document_uuid": doc.get("document_uuid") or document_uuid,
                    "metadata": doc.get("metadata", {})
                }
                vector = doc.get("embedding")

                batch.add_object(
                    properties=properties,
                    vector=vector
                )

        logger.info(f"{len(documents)}개의 텍스트 문서를 배치로 추가했습니다.")
        return True

    except Exception as e:
        logger.error(f"텍스트 문서 배치 임포트 중 오류 발생: {str(e)}", exc_info=True)
        return False

def batch_import_image_documents(client, documents: List[Dict[str, Any]], document_uuid: str = None) -> bool:
    """
    이미지 문서를 배치로 Weaviate에 임포트 (v4 API)
    """
    config = RAGConfig()

    try:
        image_collection = client.collections.get(config.WEAVIATE_IMAGE_CLASS)
        
        with image_collection.batch.dynamic() as batch:
            for i, doc in enumerate(documents):
                image_id = doc.get("image_id", f"img_{i}_{hash(doc.get('file_path', ''))}")

                properties = {
                    "caption": doc.get("caption", ""),
                    "title": doc.get("title", ""),
                    "file_path": doc.get("file_path", ""),
                    "content_type": doc.get("content_type", "image"),
                    "image_id": image_id,
                    "tags": doc.get("tags", []),
                    "document_uuid": doc.get("document_uuid") or document_uuid,
                    "metadata": doc.get("metadata", {})
                }

                vector = doc.get("embedding")

                batch.add_object(
                    properties=properties,
                    vector=vector
                )

        logger.info(f"{len(documents)}개의 이미지 문서 임포트 완료")
        return True

    except Exception as e:
        logger.error(f"이미지 문서 배치 임포트 중 오류 발생: {str(e)}", exc_info=True)
        return False

def delete_document(client, document_uuid: str) -> bool:
    """
    문서와 관련된 모든 데이터 삭제 (v4 API)
    """
    from weaviate.classes.query import Filter
    
    config = RAGConfig()
    logger.info(f"delete_document 호출됨: UUID='{document_uuid}'")

    try:
        deleted_text_count = 0
        deleted_image_count = 0
        
        # 1. 텍스트 청크 삭제
        try:
            text_collection = client.collections.get(config.WEAVIATE_TEXT_CLASS)
            result = text_collection.data.delete_many(
                where=Filter.by_property("document_uuid").equal(document_uuid)
            )
            deleted_text_count = result.matches if hasattr(result, 'matches') else 0
            logger.info(f"텍스트 청크 {deleted_text_count}개 삭제 완료 (UUID: {document_uuid})")
        except Exception as text_err:
            logger.warning(f"텍스트 청크 삭제 중 오류: {text_err}", exc_info=True)

        # 2. 이미지 삭제
        try:
            image_collection = client.collections.get(config.WEAVIATE_IMAGE_CLASS)
            result = image_collection.data.delete_many(
                where=Filter.by_property("document_uuid").equal(document_uuid)
            )
            deleted_image_count = result.matches if hasattr(result, 'matches') else 0
            logger.info(f"이미지 {deleted_image_count}개 삭제 완료 (UUID: {document_uuid})")
        except Exception as image_err:
            logger.warning(f"이미지 삭제 중 오류: {image_err}", exc_info=True)

        if deleted_text_count == 0 and deleted_image_count == 0:
            logger.warning(f"삭제할 데이터를 찾지 못했습니다. (UUID: {document_uuid})")
            return False

        logger.info(f"문서 관련 데이터 삭제 완료: {document_uuid}")
        return True

    except Exception as e:
        logger.error(f"문서 삭제 중 오류 발생: {str(e)}", exc_info=True)
        return False

def _collect_document_uuids(
    client,
    metadata_paths: List[str],
    chunk_prefix: Optional[str] = None,
) -> Set[str]:
    """주어진 metadata.file_path 또는 chunk prefix로 document_uuid 목록 조회 (v4 API)"""
    from weaviate.classes.query import Filter
    
    config = RAGConfig()
    uuids: Set[str] = set()
    
    logger.debug(f"_collect_document_uuids: 후보 경로={metadata_paths}, 청크 접두사={chunk_prefix}")
    collection = client.collections.get(config.WEAVIATE_TEXT_CLASS)

    # metadata.file_path로 검색
    for path in metadata_paths:
        if not path:
            continue
        logger.debug(f"파일 경로로 UUID 검색 시도: '{path}'")
        try:
            response = collection.query.fetch_objects(
                filters=Filter.by_property("metadata").contains_any(["file_path", path]),
                limit=10,
                return_properties=["document_uuid"]
            )
            
            for obj in response.objects:
                doc_uuid = obj.properties.get("document_uuid")
                if doc_uuid:
                    logger.info(f"파일 경로 '{path}'에서 UUID '{doc_uuid}' 찾음.")
                    uuids.add(doc_uuid)
                    break
            if uuids:
                break
        except Exception as query_err:
            logger.warning(f"metadata.file_path='{path}' 조회 중 오류: {query_err}", exc_info=True)

    # source 필드로 검색
    if not uuids:
        for path in metadata_paths:
            if not path:
                continue
            logger.debug(f"source 필드로 UUID 검색 시도: '{path}'")
            try:
                response = collection.query.fetch_objects(
                    filters=Filter.by_property("source").equal(path),
                    limit=10,
                    return_properties=["document_uuid"]
                )
                
                for obj in response.objects:
                    doc_uuid = obj.properties.get("document_uuid")
                    if doc_uuid:
                        logger.info(f"source '{path}'에서 UUID '{doc_uuid}' 찾음.")
                        uuids.add(doc_uuid)
                        break
                if uuids:
                    break
            except Exception as query_err:
                logger.warning(f"source='{path}' 조회 중 오류: {query_err}", exc_info=True)

    # chunk_id prefix로 검색
    if not uuids and chunk_prefix:
        logger.debug(f"파일 경로 검색 실패, 청크 접두사로 UUID 검색 시도: '{chunk_prefix}%'")
        try:
            response = collection.query.fetch_objects(
                filters=Filter.by_property("chunk_id").like(f"{chunk_prefix}*"),
                limit=1,
                return_properties=["document_uuid"]
            )
            
            for obj in response.objects:
                doc_uuid = obj.properties.get("document_uuid")
                if doc_uuid:
                    logger.info(f"청크 접두사 '{chunk_prefix}%'에서 UUID '{doc_uuid}' 찾음.")
                    uuids.add(doc_uuid)
                    break
        except Exception as query_err:
            logger.warning(f"chunk_id prefix '{chunk_prefix}%' 조회 중 오류: {query_err}", exc_info=True)

    logger.info(f"_collect_document_uuids: 찾은 UUID 목록={uuids}")
    return uuids


def _compute_document_uuid_from_path(file_path: str) -> Optional[str]:
    """원본 파일 경로를 기반으로 청크 삽입 시 사용한 document_uuid 계산"""
    if not file_path:
        return None

    try:
        normalized_path = str(file_path)
        document_id = hashlib.md5(normalized_path.encode("utf-8")).hexdigest()
        return str(generate_uuid5(document_id))
    except Exception as err:
        logger.warning("document_uuid 계산 실패 (path=%s): %s", file_path, err)
        return None


def delete_document_by_filename(client: weaviate.Client, filename: str) -> bool:
    """
    파일명으로 문서와 관련된 모든 데이터 삭제
    """
    logger.info(f"delete_document_by_filename 호출됨: filename='{filename}'") # <<< 로그 추가
    try:
        config = RAGConfig()
        base_name = Path(filename).stem

        # [수정] config.DATA_PATH 대신 이 파일 상단에 정의된 NEXTITS_DATA_DIR 사용
        # (routes.py와 경로 기준을 동일하게 맞춤)
        metadata_candidates = list({
            str((NEXTITS_DATA_DIR / "doc" / filename)),
            str((NEXTITS_DATA_DIR / "doc" / f"{base_name}.md")),
            str((NEXTITS_DATA_DIR / "Results" / "7.stt" / f"{base_name}.md")),
            str((NEXTITS_DATA_DIR / "Results" / "4.OCR_results" / f"{base_name}.md")),
        })
        logger.debug(f"UUID 검색을 위한 후보 경로 목록: {metadata_candidates}") # <<< 로그 추가

        document_uuids = _collect_document_uuids(client, metadata_candidates, chunk_prefix=base_name)

        if not document_uuids:
            logger.warning("파일명 '%s'에 해당하는 document_uuid를 찾지 못했습니다. (경로 후보: %s)", filename, metadata_candidates)

            computed_candidates = {
                candidate_uuid
                for candidate_uuid in (
                    _compute_document_uuid_from_path(path)
                    for path in metadata_candidates
                )
                if candidate_uuid
            }

            if computed_candidates:
                logger.info(
                    "경로 기반 UUID 계산으로 삭제를 재시도합니다. filename='%s', uuids=%s",
                    filename,
                    computed_candidates,
                )
                document_uuids.update(computed_candidates)
            else:
                return False

        deleted_any = False
        for doc_uuid in document_uuids:
            logger.info(f"파일명 '{filename}'에 대해 찾은 UUID '{doc_uuid}'의 삭제를 시도합니다.")
            if delete_document(client, doc_uuid):
                deleted_any = True
            else:
                logger.warning(f"UUID '{doc_uuid}' 삭제 실패 (파일명: {filename})") # <<< 로그 추가


        if not deleted_any:
            logger.warning("파일명 '%s'에 대해 찾은 document_uuid 삭제 실패", filename)

        return deleted_any

    except Exception as e:
        logger.error(f"파일명으로 문서 삭제 중 오류 발생: {str(e)}", exc_info=True) # 상세 오류 로깅
        return False


def get_document_uuid_map(client: weaviate.Client, filenames: List[str]) -> Dict[str, str]:
    """파일명 목록에 대해 document_uuid 매핑을 반환"""
    logger.debug(f"get_document_uuid_map 호출됨: filenames={filenames}") # <<< 로그 추가
    if not filenames or client is None:
        return {}

    config = RAGConfig()
    uuid_map: Dict[str, str] = {}

    for filename in filenames:
        base_name = Path(filename).stem

        # [수정] config.DATA_PATH 대신 이 파일 상단에 정의된 NEXTITS_DATA_DIR 사용
        metadata_candidates = list({
            str((NEXTITS_DATA_DIR / "doc" / filename)),
            str((NEXTITS_DATA_DIR / "doc" / f"{base_name}.md")),
            str((NEXTITS_DATA_DIR / "Results" / "7.stt" / f"{base_name}.md")),
            str((NEXTITS_DATA_DIR / "Results" / "4.OCR_results" / f"{base_name}.md")),
        })
        logger.debug(f"'{filename}'에 대한 UUID 검색 후보 경로: {metadata_candidates}") # <<< 로그 추가

        document_uuids = _collect_document_uuids(client, metadata_candidates, chunk_prefix=base_name)
        if document_uuids:
            found_uuid = next(iter(document_uuids))
            uuid_map[filename] = found_uuid
            logger.info(f"'{filename}'에 대한 UUID '{found_uuid}' 매핑 완료.") # <<< 로그 추가
        else:
             logger.warning(f"'{filename}'에 대한 UUID를 찾지 못했습니다.") # <<< 로그 추가


    logger.debug(f"get_document_uuid_map 결과: {uuid_map}") # <<< 로그 추가
    return uuid_map

def migrate_faiss_to_weaviate(client: weaviate.Client, faiss_index_dir: str) -> bool:
    """
    FAISS 인덱스를 Weaviate로 마이그레이션
    """
    import os
    import pickle
    import numpy as np
    import uuid
    import hashlib

    config = RAGConfig()
    logger.warning("migrate_faiss_to_weaviate 함수는 'add_document' 함수가 필요하지 않도록 수정되었으나, 테스트가 필요합니다.")

    try:
        # 텍스트 메타데이터 로드
        text_metadata_path = os.path.join(faiss_index_dir, 'text_index_metadata.pkl')
        if os.path.exists(text_metadata_path):
            with open(text_metadata_path, 'rb') as f:
                text_metadata = pickle.load(f)

            documents_by_source = {}
            metadata_store = text_metadata.get('metadata_store', {})

            for doc_id, doc_data in metadata_store.items():
                source = doc_data.get('metadata', {}).get('source', 'unknown_source')
                if source not in documents_by_source:
                    documents_by_source[source] = []

                doc = {
                    "text": doc_data.get('text', ''),
                    "title": doc_data.get('metadata', {}).get('title', ''),
                    "source": source,
                    "page_num": doc_data.get('metadata', {}).get('page_num', 0),
                    "metadata": doc_data.get('metadata', {}),
                    "embedding": doc_data.get('embedding')
                }
                documents_by_source[source].append(doc)

            for source, docs in documents_by_source.items():
                filename = os.path.basename(source)

                # 'add_document' 함수가 없으므로 UUID를 임의로 생성
                document_id = hashlib.md5(source.encode()).hexdigest()
                document_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, document_id))

                try:
                    # 텍스트 청크 추가
                    batch_import_text_documents(client, docs, document_uuid)
                    logger.info(f"문서 '{filename}'의 {len(docs)}개 텍스트 청크 임포트 완료")
                except Exception as e:
                    logger.error(f"문서 '{filename}' 처리 중 오류: {str(e)}", exc_info=True) # 상세 오류 로깅

        # ... (이미지 마이그레이션 로직) ...

        return True

    except Exception as e:
        logger.error(f"FAISS에서 Weaviate로 마이그레이션 중 오류 발생: {str(e)}", exc_info=True) # 상세 오류 로깅
        return False

if __name__ == "__main__":
    # 스키마 생성 테스트
    config = RAGConfig()
    client = config.get_weaviate_client()

    if client:
        # 이 파일 단독 실행 시 스키마 생성
        create_schema(client, recreate=False)
