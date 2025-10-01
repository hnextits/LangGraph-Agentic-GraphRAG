#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Weaviate 유틸리티 함수 - 스키마 생성 및 관리
"""

import logging
import weaviate
from typing import Dict, Any, List, Optional
from config import RAGConfig

# 로깅 설정
logger = logging.getLogger(__name__)

def create_schema(client, recreate: bool = False) -> bool:
    """
    Weaviate 스키마 생성
    
    Args:
        client: Weaviate 클라이언트 인스턴스
    
    Returns:
        bool: 성공 여부
    """
    config = RAGConfig()
    
    if client is None:
        logger.error("Weaviate 클라이언트가 None입니다.")
        return False
    
    try:
        # Weaviate 버전 확인
        import weaviate
        weaviate_version = weaviate.__version__
        is_v4 = not weaviate_version.startswith('3.')
        
        # 기존 스키마 확인 및 삭제 (recreate=True인 경우)
        if recreate:
            logger.warning("기존 스키마를 삭제하고 새로 생성합니다.")
            client.schema.delete_all()

        if is_v4:
            # v4 API
            existing_collections = client.collections.list_all()
            existing_classes = [collection.name for collection in existing_collections]
        else:
            # v3 API
            schema = client.schema.get()
            existing_classes = [cls['class'] for cls in schema.get('classes', [])]
        
        # 원본 문서 클래스 생성 (파일 단위)
        if "Document" not in existing_classes:
            if is_v4:
                # v4 API
                document_properties = {
                    "filename": {
                        "description": "파일 이름",
                        "dataType": ["text"],
                        "indexFilterable": True,
                        "indexSearchable": True
                    },
                    "file_path": {
                        "description": "파일 경로",
                        "dataType": ["text"],
                        "indexFilterable": True,
                        "indexSearchable": True
                    },
                    "file_type": {
                        "description": "파일 타입 (pdf, docx, txt 등)",
                        "dataType": ["text"],
                        "indexFilterable": True,
                        "indexSearchable": True
                    },
                    "upload_date": {
                        "description": "업로드 날짜",
                        "dataType": ["date"]
                    },
                    "file_size": {
                        "description": "파일 크기 (바이트)",
                        "dataType": ["int"]
                    },
                    "metadata": {
                        "description": "추가 메타데이터",
                        "dataType": ["object"]
                    }
                }
                
                client.collections.create(
                    name="Document",
                    description="원본 문서 파일 정보",
                    properties=document_properties
                )
            else:
                # v3 API
                document_class = {
                    "class": "Document",
                    "description": "원본 문서 파일 정보",
                    "properties": [
                        {
                            "name": "filename",
                            "dataType": ["text"],
                            "description": "파일 이름",
                            "indexInverted": True
                        },
                        {
                            "name": "file_path",
                            "dataType": ["text"],
                            "description": "파일 경로",
                            "indexInverted": True
                        },
                        {
                            "name": "file_type",
                            "dataType": ["text"],
                            "description": "파일 타입 (pdf, docx, txt 등)",
                            "indexInverted": True
                        },
                        {
                            "name": "upload_date",
                            "dataType": ["date"],
                            "description": "업로드 날짜"
                        },
                        {
                            "name": "file_size",
                            "dataType": ["int"],
                            "description": "파일 크기 (바이트)"
                        },
                        {
                            "name": "metadata",
                            "dataType": ["object"],
                            "description": "추가 메타데이터",
                            "nestedProperties": [
                                {"name": "document_id", "dataType": ["text"]},
                                {"name": "content_type", "dataType": ["text"]},
                                {"name": "file_path", "dataType": ["text"]},
                                {"name": "created_at", "dataType": ["date"]},
                                {"name": "raw_text", "dataType": ["text"]}
                            ]
                        },
                        {
                            "name": "belongsTo",
                            "dataType": ["Document"],
                            "description": "이 텍스트가 속한 원본 문서"
                        }
                    ]
                }
                
                client.schema.create_class(document_class)
            
            logger.info("원본 문서 클래스 생성 완료: Document")
        else:
            logger.info("원본 문서 클래스가 이미 존재합니다: Document")
        
        # 텍스트 문서 클래스 생성 (청크 단위)
        if config.WEAVIATE_TEXT_CLASS not in existing_classes:
            if is_v4:
                # v4 API
                text_properties = {
                    "text": {
                        "description": "문서 텍스트 내용",
                        "dataType": ["text"],
                        "indexSearchable": True
                    },
                    "title": {
                        "description": "문서 제목",
                        "dataType": ["text"],
                        "indexSearchable": True
                    },
                    "source": {
                        "description": "문서 출처",
                        "dataType": ["text"],
                        "indexFilterable": True
                    },
                    "page_num": {
                        "description": "페이지 번호",
                        "dataType": ["int"],
                        "indexFilterable": True
                    },
                    "chunk_id": {
                        "description": "청크 고유 ID",
                        "dataType": ["text"],
                        "indexFilterable": True,
                        "indexSearchable": True
                    },
                    "metadata": {
                        "description": "추가 메타데이터",
                        "dataType": ["object"],
                        "nestedProperties": [
                            {"name": "document_id", "dataType": ["text"]},
                            {"name": "content_type", "dataType": ["text"]}
                        ]
                    }
                    # v4에서는 관계를 다르게 정의해야 함
                }
                
                # 벡터 인덱스 설정
                vector_config = {
                    "vectorizer": "none"  # 외부 벡터 사용
                }
                
                client.collections.create(
                    name=config.WEAVIATE_TEXT_CLASS,
                    description="텍스트 문서 저장을 위한 클래스",
                    properties=text_properties,
                    vector_index_config=vector_config
                )
                
                # 관계 설정 (선택사항)
                try:
                    text_collection = client.collections.get(config.WEAVIATE_TEXT_CLASS)
                    document_collection = client.collections.get("Document")
                    
                    # 관계 추가 - 현재 v4에서는 직접적인 관계 정의가 다름
                    # 추후 필요한 경우 관계 정의 추가
                except Exception as e:
                    logger.warning(f"관계 정의 실패: {str(e)}")
            else:
                # v3 API
                text_class = {
                    "class": config.WEAVIATE_TEXT_CLASS,
                    "description": "텍스트 문서 저장을 위한 클래스",
                    "vectorizer": "none",  # 외부에서 생성된 벡터를 사용합니다.
                    "properties": [
                        {
                            "name": "text",
                            "dataType": ["text"],
                            "description": "문서 텍스트 내용"
                        },
                        {
                            "name": "title",
                            "dataType": ["text"],
                            "description": "문서 제목"
                        },
                        {
                            "name": "source",
                            "dataType": ["text"],
                            "description": "문서 출처"
                        },
                        {
                            "name": "page_num",
                            "dataType": ["int"],
                            "description": "페이지 번호"
                        },
                        {
                            "name": "chunk_id",
                            "dataType": ["text"],
                            "description": "청크 고유 ID",
                            "indexInverted": True
                        },
                        {
                            "name": "metadata",
                            "dataType": ["object"],
                            "description": "추가 메타데이터",
                            "nestedProperties": [
                                {"name": "document_id", "dataType": ["text"]},
                                {"name": "content_type", "dataType": ["text"]}
                            ]
                        },
                        {
                            "name": "belongsTo",
                            "dataType": ["Document"],
                            "description": "이 텍스트가 속한 원본 문서"
                        }
                    ]
                }
                
                client.schema.create_class(text_class)
            
            logger.info(f"텍스트 문서 클래스 생성 완료: {config.WEAVIATE_TEXT_CLASS}")
        else:
            logger.info(f"텍스트 문서 클래스가 이미 존재합니다: {config.WEAVIATE_TEXT_CLASS}")
        
        # 이미지 문서 클래스 생성
        if config.WEAVIATE_IMAGE_CLASS not in existing_classes:
            if is_v4:
                # v4 API
                image_properties = {
                    "caption": {
                        "description": "이미지 캡션",
                        "dataType": ["text"],
                        "indexSearchable": True
                    },
                    "title": {
                        "description": "이미지 제목",
                        "dataType": ["text"],
                        "indexSearchable": True
                    },
                    "file_path": {
                        "description": "이미지 파일 경로",
                        "dataType": ["text"],
                        "indexFilterable": True
                    },
                    "content_type": {
                        "description": "콘텐츠 타입 (image, chart 등)",
                        "dataType": ["text"],
                        "indexFilterable": True
                    },
                    "image_id": {
                        "description": "이미지 고유 ID",
                        "dataType": ["text"],
                        "indexFilterable": True,
                        "indexSearchable": True
                    },
                    "tags": {
                        "description": "이미지 태그",
                        "dataType": ["text[]"]
                    },
                    "metadata": {
                        "description": "추가 메타데이터",
                        "dataType": ["object"],
                        "nestedProperties": [
                            {"name": "document_id", "dataType": ["text"]},
                            {"name": "content_type", "dataType": ["text"]},
                            {"name": "file_path", "dataType": ["text"]}
                        ]
                    }
                    # v4에서는 관계를 다르게 정의해야 함
                }
                
                # 벡터 인덱스 설정
                vector_config = {
                    "vectorizer": "none"  # 외부 벡터 사용
                }
                
                client.collections.create(
                    name=config.WEAVIATE_IMAGE_CLASS,
                    description="이미지 문서 저장을 위한 클래스",
                    properties=image_properties,
                    vector_index_config=vector_config
                )
                
                # 관계 설정 (선택사항)
                try:
                    image_collection = client.collections.get(config.WEAVIATE_IMAGE_CLASS)
                    document_collection = client.collections.get("Document")
                    
                    # 관계 추가 - 현재 v4에서는 직접적인 관계 정의가 다름
                    # 추후 필요한 경우 관계 정의 추가
                except Exception as e:
                    logger.warning(f"관계 정의 실패: {str(e)}")
            else:
                # v3 API
                image_class = {
                    "class": config.WEAVIATE_IMAGE_CLASS,
                    "description": "이미지 문서 저장을 위한 클래스",
                    "vectorizer": config.WEAVIATE_VECTORIZER,
                    "moduleConfig": {
                        config.WEAVIATE_VECTORIZER: {
                            "vectorizeClassName": True
                        }
                    },
                    "properties": [
                        {
                            "name": "caption",
                            "dataType": ["text"],
                            "description": "이미지 캡션",
                            "moduleConfig": {
                                config.WEAVIATE_VECTORIZER: {
                                    "skip": False,
                                    "vectorizePropertyName": False
                                }
                            }
                        },
                        {
                            "name": "title",
                            "dataType": ["text"],
                            "description": "이미지 제목",
                            "moduleConfig": {
                                config.WEAVIATE_VECTORIZER: {
                                    "skip": False,
                                    "vectorizePropertyName": False
                                }
                            }
                        },
                        {
                            "name": "file_path",
                            "dataType": ["text"],
                            "description": "이미지 파일 경로",
                            "moduleConfig": {
                                config.WEAVIATE_VECTORIZER: {
                                    "skip": True
                                }
                            }
                        },
                        {
                            "name": "content_type",
                            "dataType": ["text"],
                            "description": "콘텐츠 타입 (image, chart 등)",
                            "moduleConfig": {
                                config.WEAVIATE_VECTORIZER: {
                                    "skip": True
                                }
                            }
                        },
                        {
                            "name": "image_id",
                            "dataType": ["text"],
                            "description": "이미지 고유 ID",
                            "indexInverted": True,
                            "moduleConfig": {
                                config.WEAVIATE_VECTORIZER: {
                                    "skip": True
                                }
                            }
                        },
                        {
                            "name": "tags",
                            "dataType": ["text[]"],
                            "description": "이미지 태그",
                            "moduleConfig": {
                                config.WEAVIATE_VECTORIZER: {
                                    "skip": True
                                }
                            }
                        },
                        {
                            "name": "metadata",
                            "dataType": ["object"],
                            "description": "추가 메타데이터",
                            "nestedProperties": [
                                {"name": "document_id", "dataType": ["text"]},
                                {"name": "content_type", "dataType": ["text"]},
                                {"name": "file_path", "dataType": ["text"]}
                            ]
                        },
                        {
                            "name": "belongsTo",
                            "dataType": ["Document"],
                            "description": "이 이미지가 속한 원본 문서"
                        }
                    ]
                }
                
                client.schema.create_class(image_class)
            
            logger.info(f"이미지 문서 클래스 생성 완료: {config.WEAVIATE_IMAGE_CLASS}")
        else:
            logger.info(f"이미지 문서 클래스가 이미 존재합니다: {config.WEAVIATE_IMAGE_CLASS}")
            
        return True
        
        return True
    
    except Exception as e:
        logger.error(f"Weaviate 스키마 생성 중 오류 발생: {str(e)}")
        return False

def add_document(client, document_info: Dict[str, Any]) -> str:
    """
    원본 문서 추가 (파일 단위)
    
    Args:
        client: Weaviate 클라이언트 인스턴스
        document_info: 문서 정보
    
    Returns:
        str: 생성된 문서 UUID
    """
    try:
        # Weaviate 버전 확인
        import weaviate
        weaviate_version = weaviate.__version__
        is_v4 = not weaviate_version.startswith('3.')
        
        # 파일 정보 추출
        filename = document_info.get("filename", "")
        file_path = document_info.get("file_path", "")
        file_type = document_info.get("file_type", "")
        file_size = document_info.get("file_size", 0)
        metadata = document_info.get("metadata", {})
        
        # 파일 타입이 없는 경우 파일 확장자에서 추출
        if not file_type and file_path:
            import os
            _, ext = os.path.splitext(file_path)
            if ext:
                file_type = ext[1:].lower()  # 점(.) 제거
        
        # 현재 날짜 추가
        import datetime
        upload_date_obj = document_info.get("upload_date", datetime.datetime.now(datetime.timezone.utc))
        if isinstance(upload_date_obj, datetime.datetime):
            if upload_date_obj.tzinfo is None:
                upload_date_obj = upload_date_obj.astimezone(datetime.timezone.utc)
            upload_date = upload_date_obj.isoformat()
        else:
            upload_date = upload_date_obj
        
        # 문서 객체 생성
        document_uuid = None
        
        if is_v4:
            # v4 API
            document_collection = client.collections.get("Document")
            
            properties = {
                "filename": filename,
                "file_path": file_path,
                "file_type": file_type,
                "file_size": file_size,
                "upload_date": upload_date,
                "metadata": metadata
            }
            
            # 문서 추가
            document_object = document_collection.data.insert(properties)
            document_uuid = document_object.uuid
        else:
            # v3 API
            document_uuid = client.data_object.create(
                data_object={
                    "filename": filename,
                    "file_path": file_path,
                    "file_type": file_type,
                    "file_size": file_size,
                    "upload_date": upload_date,
                    "metadata": metadata
                },
                class_name="Document"
            )
        
        logger.info(f"문서 추가 완료: {filename}, UUID: {document_uuid}")
        return document_uuid
    
    except Exception as e:
        logger.error(f"문서 추가 중 오류 발생: {str(e)}")
        raise

def batch_import_text_documents(client, documents: List[Dict[str, Any]], document_uuid: str = None) -> bool:
    """
    텍스트 문서를 배치로 Weaviate에 임포트
    
    Args:
        client: Weaviate 클라이언트 인스턴스
        documents: 임포트할 문서 리스트
        document_uuid: 연결할 원본 문서 UUID (선택사항)
    
    Returns:
        bool: 성공 여부
    """
    config = RAGConfig()
    
    try:
        # Weaviate 버전 확인
        import weaviate
        weaviate_version = weaviate.__version__
        is_v4 = not weaviate_version.startswith('3.')
        
        if is_v4:
            # v4 API
            text_collection = client.collections.get(config.WEAVIATE_TEXT_CLASS)
            
            # 배치 객체 생성
            with text_collection.batch.dynamic() as batch:
                batch.batch_size = config.WEAVIATE_BATCH_SIZE
                
                for i, doc in enumerate(documents):
                    # 청크 ID 생성 (없는 경우)
                    chunk_id = doc.get("chunk_id", f"chunk_{i}_{hash(doc.get('text', '')[:50])}")  # 텍스트 앞부분으로 해시 생성
                    
                    properties = {
                        "text": doc.get("text", ""),
                        "title": doc.get("title", ""),
                        "source": doc.get("source", ""),
                        "page_num": doc.get("page_num", 0),
                        "chunk_id": chunk_id,
                        "metadata": doc.get("metadata", {})
                    }
                    
                    # 벡터가 있는 경우 사용
                    vector = doc.get("embedding")
                    
                    # 관계 설정 - v4에서는 관계를 다르게 설정해야 함
                    # 현재는 관계 설정 없이 문서만 추가
                    
                    # 객체 추가
                    batch.add_object(
                        properties=properties,
                        vector=vector
                    )
        else:
            # v3 API
            with client.batch as batch:
                batch.batch_size = config.WEAVIATE_BATCH_SIZE
                
                for i, doc in enumerate(documents):
                    # 청크 ID 생성 (없는 경우)
                    chunk_id = doc.get("chunk_id", f"chunk_{i}_{hash(doc.get('text', '')[:50])}")  # 텍스트 앞부분으로 해시 생성
                    
                    properties = {
                        "text": doc.get("text", ""),
                        "title": doc.get("title", ""),
                        "source": doc.get("source", ""),
                        "page_num": doc.get("page_num", 0),
                        "chunk_id": chunk_id,
                        "metadata": doc.get("metadata", {})
                    }
                    
                    # 벡터가 있는 경우 사용, 없으면 Weaviate가 자동 생성
                    vector = doc.get("embedding")
                    
                    # UUID 생성 (선택사항)
                    uuid = None
                    
                    # 원본 문서와의 관계 설정
                    references = None
                    if document_uuid:
                        references = {
                            "belongsTo": [
                                {
                                    "beacon": f"weaviate://localhost/Document/{document_uuid}"
                                }
                            ]
                        }
                    
                    # 객체 추가
                    if references:
                        # 관계가 있는 경우
                        batch.add_data_object(
                            data_object=properties,
                            class_name=config.WEAVIATE_TEXT_CLASS,
                            uuid=uuid,
                            vector=vector
                        )
                        
                        # 관계 정보 별도 추가
                        try:
                            # 추가된 객체의 UUID 가져오기
                            result = client.query.get(config.WEAVIATE_TEXT_CLASS, ["chunk_id"]).with_where({
                                "path": ["chunk_id"],
                                "operator": "Equal",
                                "valueString": chunk_id
                            }).do()
                            
                            if "data" in result and "Get" in result["data"]:
                                items = result["data"]["Get"].get(config.WEAVIATE_TEXT_CLASS, [])
                                if items and len(items) > 0:
                                    # 객체 UUID
                                    object_uuid = items[0].get("_additional", {}).get("id")
                                    if object_uuid:
                                        # 관계 추가
                                        client.data_object.reference.add(
                                            from_uuid=object_uuid,
                                            from_property_name="belongsTo",
                                            to_uuid=document_uuid
                                        )
                        except Exception as ref_err:
                            logger.warning(f"관계 추가 중 오류: {str(ref_err)}")
                    else:
                        # 관계가 없는 경우
                        batch.add_data_object(
                            data_object=properties,
                            class_name=config.WEAVIATE_TEXT_CLASS,
                            uuid=uuid,
                            vector=vector
                        )
        
        logger.info(f"{len(documents)}개의 텍스트 문서를 배치로 추가했습니다.")
        return True
        
    except Exception as e:
        logger.error(f"텍스트 문서 배치 임포트 중 오류 발생: {str(e)}")
        return False

def batch_import_image_documents(client: weaviate.Client, documents: List[Dict[str, Any]], document_uuid: str = None) -> bool:
    """
    이미지 문서를 배치로 Weaviate에 임포트
    
    Args:
        client: Weaviate 클라이언트 인스턴스
        documents: 임포트할 문서 리스트
        document_uuid: 연결할 원본 문서 UUID (선택사항)
    
    Returns:
        bool: 성공 여부
    """
    config = RAGConfig()
    
    try:
        with client.batch as batch:
            batch.batch_size = config.WEAVIATE_BATCH_SIZE
            
            for i, doc in enumerate(documents):
                # 이미지 ID 생성 (없는 경우)
                image_id = doc.get("image_id", f"img_{i}_{hash(doc.get('file_path', ''))}")  # 파일 경로로 해시 생성
                
                properties = {
                    "caption": doc.get("caption", ""),
                    "title": doc.get("title", ""),
                    "file_path": doc.get("file_path", ""),
                    "content_type": doc.get("content_type", "image"),
                    "image_id": image_id,
                    "tags": doc.get("tags", []),
                    "metadata": doc.get("metadata", {})
                }
                
                # 벡터가 있는 경우 사용, 없으면 Weaviate가 자동 생성
                vector = doc.get("embedding")
                
                # UUID 생성 (선택사항)
                uuid = None
                
                # 원본 문서와의 관계 설정
                references = None
                if document_uuid:
                    references = {
                        "belongsTo": [
                            {
                                "beacon": f"weaviate://localhost/Document/{document_uuid}"
                            }
                        ]
                    }
                
                batch.add_data_object(
                    data_object=properties,
                    class_name=config.WEAVIATE_IMAGE_CLASS,
                    vector=vector,
                    uuid=uuid,
                    references=references
                )
        
        logger.info(f"{len(documents)}개의 이미지 문서 임포트 완료")
        return True
    
    except Exception as e:
        logger.error(f"이미지 문서 배치 임포트 중 오류 발생: {str(e)}")
        return False

def delete_document(client: weaviate.Client, document_uuid: str) -> bool:
    """
    문서와 관련된 모든 데이터 삭제
    
    Args:
        client: Weaviate 클라이언트 인스턴스
        document_uuid: 삭제할 문서 UUID
    
    Returns:
        bool: 성공 여부
    """
    config = RAGConfig()
    
    try:
        # 1. 문서와 관련된 텍스트 청크 삭제
        # GraphQL을 사용하여 문서와 관련된 텍스트 청크 검색
        text_query = {
            "query": f"""
            {{  
                Get {{  
                    {config.WEAVIATE_TEXT_CLASS} (where: {{  
                        path: "belongsTo.beacon",  
                        operator: Equal,  
                        valueString: "{document_uuid}"  
                    }}) {{  
                        _additional {{  
                            id  
                        }}  
                    }}  
                }}  
            }}  
            """
        }
        
        text_result = client.query.raw(text_query)
        
        if "data" in text_result and "Get" in text_result["data"]:
            text_chunks = text_result["data"]["Get"].get(config.WEAVIATE_TEXT_CLASS, [])
            for chunk in text_chunks:
                chunk_id = chunk.get("_additional", {}).get("id")
                if chunk_id:
                    client.data_object.delete(chunk_id, config.WEAVIATE_TEXT_CLASS)
                    logger.info(f"텍스트 청크 삭제 완료: {chunk_id}")
        
        # 2. 문서와 관련된 이미지 삭제
        image_query = {
            "query": f"""
            {{  
                Get {{  
                    {config.WEAVIATE_IMAGE_CLASS} (where: {{  
                        path: "belongsTo.beacon",  
                        operator: Equal,  
                        valueString: "{document_uuid}"  
                    }}) {{  
                        _additional {{  
                            id  
                        }}  
                    }}  
                }}  
            }}  
            """
        }
        
        image_result = client.query.raw(image_query)
        
        if "data" in image_result and "Get" in image_result["data"]:
            images = image_result["data"]["Get"].get(config.WEAVIATE_IMAGE_CLASS, [])
            for image in images:
                image_id = image.get("_additional", {}).get("id")
                if image_id:
                    client.data_object.delete(image_id, config.WEAVIATE_IMAGE_CLASS)
                    logger.info(f"이미지 삭제 완료: {image_id}")
        
        # 3. 문서 자체 삭제
        client.data_object.delete(document_uuid, "Document")
        logger.info(f"문서 삭제 완료: {document_uuid}")
        
        return True
    
    except Exception as e:
        logger.error(f"문서 삭제 중 오류 발생: {str(e)}")
        return False

def delete_document_by_filename(client: weaviate.Client, filename: str) -> bool:
    """
    파일명으로 문서와 관련된 모든 데이터 삭제
    
    Args:
        client: Weaviate 클라이언트 인스턴스
        filename: 삭제할 문서 파일명
    
    Returns:
        bool: 성공 여부
    """
    try:
        # 파일명으로 문서 검색
        query = {
            "query": f"""
            {{  
                Get {{  
                    Document (where: {{  
                        path: ["filename"],  
                        operator: Equal,  
                        valueString: "{filename}"  
                    }}) {{  
                        _additional {{  
                            id  
                        }}  
                    }}  
                }}  
            }}  
            """
        }
        
        result = client.query.raw(query)
        
        if "data" in result and "Get" in result["data"]:
            documents = result["data"]["Get"].get("Document", [])
            for doc in documents:
                doc_id = doc.get("_additional", {}).get("id")
                if doc_id:
                    # 각 문서와 관련된 모든 데이터 삭제
                    delete_document(client, doc_id)
            
            return True
        else:
            logger.warning(f"파일명 '{filename}'에 해당하는 문서를 찾을 수 없습니다.")
            return False
    
    except Exception as e:
        logger.error(f"파일명으로 문서 삭제 중 오류 발생: {str(e)}")
        return False

def migrate_faiss_to_weaviate(client: weaviate.Client, faiss_index_dir: str) -> bool:
    """
    FAISS 인덱스를 Weaviate로 마이그레이션
    
    Args:
        client: Weaviate 클라이언트 인스턴스
        faiss_index_dir: FAISS 인덱스 디렉토리
    
    Returns:
        bool: 성공 여부
    """
    import os
    import pickle
    import numpy as np
    
    config = RAGConfig()
    
    try:
        # 텍스트 메타데이터 로드
        text_metadata_path = os.path.join(faiss_index_dir, 'text_index_metadata.pkl')
        if os.path.exists(text_metadata_path):
            with open(text_metadata_path, 'rb') as f:
                text_metadata = pickle.load(f)
            
            # 메타데이터 형식 변환
            text_documents = []
            metadata_store = text_metadata.get('metadata_store', {})
            
            # 문서별로 그룹화
            documents_by_source = {}
            
            for doc_id, doc_data in metadata_store.items():
                source = doc_data.get('metadata', {}).get('source', '')
                if not source:
                    source = "unknown_source"
                
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
            
            # 각 문서별로 처리
            for source, docs in documents_by_source.items():
                # 문서 정보 추출
                filename = os.path.basename(source) if source != "unknown_source" else "unknown_document"
                
                # 문서 추가
                document_info = {
                    "filename": filename,
                    "file_path": source,
                    "file_type": os.path.splitext(filename)[1][1:] if os.path.splitext(filename)[1] else "",
                    "metadata": {"source": source}
                }
                
                try:
                    # 문서 추가
                    document_uuid = add_document(client, document_info)
                    
                    # 텍스트 청크 추가
                    batch_import_text_documents(client, docs, document_uuid)
                    logger.info(f"문서 '{filename}'의 {len(docs)}개 텍스트 청크 임포트 완료")
                except Exception as e:
                    logger.error(f"문서 '{filename}' 처리 중 오류: {str(e)}")
        
        # 이미지 메타데이터 로드
        image_metadata_path = os.path.join(faiss_index_dir, 'image_metadata.pkl')
        if os.path.exists(image_metadata_path):
            with open(image_metadata_path, 'rb') as f:
                image_metadata = pickle.load(f)
            
            # 이미지를 문서별로 그룹화
            images_by_source = {}
            
            for img_data in image_metadata:
                source = img_data.get('source', '')
                if not source:
                    source = "unknown_source"
                
                if source not in images_by_source:
                    images_by_source[source] = []
                
                doc = {
                    "caption": img_data.get('caption', ''),
                    "title": img_data.get('title', ''),
                    "file_path": img_data.get('file_path', ''),
                    "content_type": img_data.get('con_type', 'image'),
                    "tags": img_data.get('tags', []),
                    "metadata": {
                        "page_num": img_data.get('page_num'),
                        "source": source
                    },
                    "embedding": img_data.get('embedding')
                }
                images_by_source[source].append(doc)
            
            # 각 문서별로 처리
            for source, images in images_by_source.items():
                # 문서 검색
                query = {
                    "query": f"""
                    {{  
                        Get {{  
                            Document (where: {{  
                                path: ["file_path"],  
                                operator: Equal,  
                                valueString: "{source}"  
                            }}) {{  
                                _additional {{  
                                    id  
                                }}  
                            }}  
                        }}  
                    }}  
                    """
                }
                
                result = client.query.raw(query)
                document_uuid = None
                
                if "data" in result and "Get" in result["data"]:
                    documents = result["data"]["Get"].get("Document", [])
                    if documents:
                        document_uuid = documents[0].get("_additional", {}).get("id")
                
                # 문서가 없는 경우 생성
                if not document_uuid:
                    filename = os.path.basename(source) if source != "unknown_source" else "unknown_document"
                    document_info = {
                        "filename": filename,
                        "file_path": source,
                        "file_type": os.path.splitext(filename)[1][1:] if os.path.splitext(filename)[1] else "",
                        "metadata": {"source": source}
                    }
                    document_uuid = add_document(client, document_info)
                
                # 이미지 추가
                batch_import_image_documents(client, images, document_uuid)
                logger.info(f"문서 '{source}'의 {len(images)}개 이미지 임포트 완료")
        
        return True
    
    except Exception as e:
        logger.error(f"FAISS에서 Weaviate로 마이그레이션 중 오류 발생: {str(e)}")
        return False

if __name__ == "__main__":
    # 스키마 생성 테스트
    config = RAGConfig()
    client = config.get_weaviate_client()
    
    if client:
        create_schema(client)
        
        # 마이그레이션 테스트 (필요시)
        # migrate_faiss_to_weaviate(client, config.INDEX_DIR)
