import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, List

try:
    import weaviate
    from weaviate.classes.config import Configure, Property, DataType, ReferenceProperty
    from weaviate.classes.query import Filter
    from weaviate.util import generate_uuid5
except Exception:
    weaviate = None
    Configure = Property = DataType = ReferenceProperty = Filter = Any

from notebooklm.config import RAGConfig

logger = logging.getLogger(__name__)

@dataclass
class GraphClassDef:
    name: str
    description: str

class GraphSchemaManager:
    ENTITY_CLASS = GraphClassDef(name="GraphEntity", description="LLM-extracted entities")
    EVENT_CLASS = GraphClassDef(name="GraphEvent", description="LLM-extracted 사건/활동")
    RELATION_CLASS = GraphClassDef(name="GraphRelation", description="엔티티 간 관계 레코드")

    def __init__(self, config: Optional[RAGConfig] = None) -> None:
        self.config = config or RAGConfig()
        if weaviate is None:
            raise RuntimeError("weaviate-client 미설치: pip install weaviate-client==4.*")
        self.client = self.config.get_weaviate_client()

        # Neo4j 클라이언트 (optional — 실패해도 Weaviate만 사용)
        self.neo4j_client = None
        try:
            from notebooklm.legacy_graph_client import Neo4jGraphClient
            self.neo4j_client = Neo4jGraphClient(self.config)
            logger.info("Neo4j 클라이언트 초기화 완료")
        except Exception as exc:
            logger.warning("Neo4j 클라이언트 초기화 실패 (Weaviate만 사용): %s", exc)

    def _ensure_relation_properties(self) -> None:
        collection = self.client.collections.get(self.RELATION_CLASS.name)
        config = collection.config.get()
        existing_refs = {r.name for r in config.references}
        
        required = {
            "source": ReferenceProperty(name="source", target_collection=self.ENTITY_CLASS.name),
            "target": ReferenceProperty(name="target", target_collection=self.ENTITY_CLASS.name),
            "event": ReferenceProperty(name="event", target_collection=self.EVENT_CLASS.name),
        }
        
        for key, prop in required.items():
            if key not in existing_refs:
                collection.config.add_reference(prop)
                logger.info(f"Added reference '{key}' to {self.RELATION_CLASS.name}")

    # metadata nested property에 허용된 키 목록
    _METADATA_KEYS = {"document_id", "chunk_id", "name", "type", "raw_text", "source", "entity_id"}

    def _safe_metadata(self, raw: dict) -> dict:
        """nested property에 정의된 키만 남기고 필터링"""
        return {k: v for k, v in raw.items() if k in self._METADATA_KEYS and v is not None}

    def upsert_metadata(self, graph_json: Dict[str, Any], doc_uuid: Optional[str] = None) -> None:
        """안정적인 ID 매핑을 사용하여 그래프 데이터를 업서트"""
        doc_id = graph_json.get("document_id") or ""
        entities = graph_json.get("entities") or []
        events = graph_json.get("events") or []
        relations = graph_json.get("relations") or []

        # 1. 엔티티 업서트 및 'entity_id -> weaviate_uuid' 매핑 맵 구축
        entity_uuid_map = self._upsert_entities_with_map(entities, doc_uuid=doc_uuid, doc_id=doc_id)
        
        # 2. 이벤트 업서트 (필요 시)
        self._upsert_objects(self.EVENT_CLASS.name, events, doc_id=doc_id)

        # 3. 인덱싱 동기화를 위한 대기 (1.5초로 상향)
        time.sleep(1.5)

        # 4. 구축된 매핑 맵을 사용하여 관계 업서트
        self._upsert_relations_with_map(relations, entity_uuid_map, doc_id=doc_id)

        # 5. Neo4j 동기화
        if self.neo4j_client:
            try:
                self.neo4j_client.ingest_graph_json(graph_json)
            except Exception as exc:
                logger.error("Neo4j 동기화 실패: %s", exc)

    def _upsert_entities_with_map(self, entities: list[dict], doc_uuid: Optional[str] = None, doc_id: str = "") -> Dict[str, str]:
        if not entities:
            return {}
        
        collection = self.client.collections.get(self.ENTITY_CLASS.name)
        id_map = {}

        with collection.batch.fixed_size(batch_size=50) as batch:
            for ent in entities:
                raw_id = str(ent.get("entity_id") or ent.get("name") or "Unknown").strip()
                display_name = str(ent.get("name") or raw_id).strip()
                
                obj_uuid = generate_uuid5(raw_id)
                id_map[raw_id] = str(obj_uuid)
                
                properties = {
                    "document_id": ent.get("document_id") or doc_id,
                    "chunk_id": ent.get("chunk_id"),
                    "text": display_name,
                    "metadata": self._safe_metadata(ent),
                }
                
                references = {}
                if doc_uuid:
                    references["source_document"] = doc_uuid
                
                batch.add_object(
                    properties=properties, 
                    uuid=obj_uuid,
                    references=references
                )
        
        failed = collection.batch.failed_objects
        if failed:
            logger.error(f"Entity batch failed ({len(failed)} objects): {failed[0].message}")
        else:
            logger.info(f"Entity batch 성공: {len(entities)}건 업서트")
            
        return id_map

    def _upsert_relations_with_map(self, relations: list[dict], id_map: Dict[str, str], doc_id: str = "") -> None:
        if not relations:
            return
        
        collection = self.client.collections.get(self.RELATION_CLASS.name)
        
        with collection.batch.fixed_size(batch_size=50) as batch:
            for rel in relations:
                # extractor에서 만든 source_id / target_id 우선 사용
                src_key = str(rel.get("source_id") or rel.get("source")).strip()
                tgt_key = str(rel.get("target_id") or rel.get("target")).strip()
                
                # 매핑 맵 확인
                src_uuid = id_map.get(src_key)
                tgt_uuid = id_map.get(tgt_key)
                
                # 방어 로직: 소스나 타겟 중 하나라도 실제 DB에 들어가지 않았다면 관계 생성을 건너뜀
                if not src_uuid or not tgt_uuid:
                    logger.debug(f"Skipping relation due to missing ref: {src_key} -> {tgt_key}")
                    continue

                properties = {
                    "document_id": rel.get("document_id") or doc_id,
                    "chunk_id": rel.get("chunk_id"),
                    "text": rel.get("relationship") or rel.get("relation") or "related_to",
                    "metadata": self._safe_metadata(rel),
                }
                
                references = {
                    "source": src_uuid,
                    "target": tgt_uuid
                }
                
                batch.add_object(properties=properties, references=references)
        
        if collection.batch.failed_objects:
            logger.error(f"Relation batch failed: {collection.batch.failed_objects[0].message}")

    def _upsert_objects(self, class_name: str, objects: list[dict], doc_id: str = "") -> None:
        if not objects: return
        collection = self.client.collections.get(class_name)
        with collection.batch.dynamic() as batch:
            for obj in objects:
                name_val = str(obj.get("name") or obj.get("title") or "Unknown").strip()
                batch.add_object(
                    properties={
                        "text": name_val,
                        "document_id": obj.get("document_id") or doc_id,
                        "chunk_id": obj.get("chunk_id"),
                        "metadata": self._safe_metadata(obj),
                    },
                    uuid=generate_uuid5(name_val)
                )
        failed = collection.batch.failed_objects
        if failed:
            logger.error(f"{class_name} batch failed ({len(failed)}): {failed[0].message}")
        else:
            logger.info(f"{class_name} batch 성공: {len(objects)}건 업서트")

    def ensure_graph_schema(self) -> None:
        self._ensure_class(self.ENTITY_CLASS)
        self._ensure_class(self.EVENT_CLASS)
        self._ensure_class(self.RELATION_CLASS)
        self._ensure_relation_properties()

    def _ensure_class(self, class_def: GraphClassDef) -> None:
        if self.client.collections.exists(class_def.name):
            return
        
        metadata_nested = [
            Property(name="document_id", data_type=DataType.TEXT),
            Property(name="chunk_id", data_type=DataType.INT),
            Property(name="name", data_type=DataType.TEXT),
            Property(name="type", data_type=DataType.TEXT),
            Property(name="raw_text", data_type=DataType.TEXT),
            Property(name="source", data_type=DataType.TEXT),
        ]
        
        props = [
            Property(name="document_id", data_type=DataType.TEXT),
            Property(name="chunk_id", data_type=DataType.INT),
            Property(name="text", data_type=DataType.TEXT),
            Property(name="metadata", data_type=DataType.OBJECT, nested_properties=metadata_nested),
        ]

        references = []
        if class_def.name == self.ENTITY_CLASS.name:
            references.append(ReferenceProperty(name="source_document", target_collection="TextDocument"))

        self.client.collections.create(
            name=class_def.name,
            properties=props,
            references=references,
            vectorizer_config=Configure.Vectorizer.none()
        )

    def ingest_metadata_file(self, file_path: Path, doc_uuid: Optional[str] = None) -> None:
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        self.ensure_graph_schema()
        self.upsert_metadata(data, doc_uuid=doc_uuid)

    def ingest_metadata_dir(self, directory: Path, doc_uuid_map: Optional[Dict[str, str]] = None) -> None:
        directory = Path(directory)
        if not directory.exists(): return
        doc_uuid_map = doc_uuid_map or {}
        
        for file_path in directory.glob("*.graph.json"):
            try:
                # 'lecture_01.graph.json' -> 'lecture_01'
                doc_id = file_path.name.replace(".graph.json", "")
                target_uuid = doc_uuid_map.get(doc_id)
                
                self.ingest_metadata_file(file_path, doc_uuid=target_uuid)
                logger.info(f"성공: {file_path.name} (TextDocument Ref: {target_uuid})")
            except Exception as exc:
                logger.error(f"실패: {file_path.name} -> {exc}")

    def close(self) -> None:
        self.client.close()
        if self.neo4j_client:
            try:
                self.neo4j_client.close()
            except Exception:
                pass

__all__ = ["GraphSchemaManager"]