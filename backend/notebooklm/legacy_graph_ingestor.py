#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Legacy GraphDB(Neo4j) 업서트를 담당하는 헬퍼."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from notebooklm.legacy_graph_client import LegacyGraphClient

logger = logging.getLogger(__name__)


class LegacyGraphIngestor:
    """LLM 추출 그래프 JSON을 Neo4j에 업서트하는 유틸."""

    def __init__(self, config) -> None:
        self.config = config
        if not getattr(config, "LEGACY_GRAPH_ENABLED", False):
            raise RuntimeError("LEGACY_GRAPH_ENABLED=False 상태에서는 LegacyGraphIngestor를 사용할 수 없습니다.")
        self.client = LegacyGraphClient(config)
        self._constraints_ensured = False

    # ------------------------------------------------------------------
    def ingest_metadata_file(self, file_path: Path) -> None:
        data = Path(file_path).read_text(encoding="utf-8")
        import json

        payload = json.loads(data)
        self.ingest_metadata(payload)

    def ingest_metadata(self, graph_json: Dict[str, Any]) -> None:
        entities = graph_json.get("entities") or []
        events = graph_json.get("events") or []
        relations = graph_json.get("relations") or []
        document_id = graph_json.get("document_id") or "unknown_doc"

        logger.info(
            "LegacyGraphIngestor: ingest document=%s entities=%d events=%d relations=%d",
            document_id,
            len(entities),
            len(events),
            len(relations),
        )

        with self.client.driver.session() as session:
            if not self._constraints_ensured:
                session.execute_write(self._ensure_constraints)
                self._constraints_ensured = True
            session.execute_write(self._upsert_bundle, document_id, entities, events, relations)

    # ------------------------------------------------------------------
    @staticmethod
    def _ensure_constraints(tx) -> None:  # type: ignore[no-untyped-def]
        statements = [
            "CREATE CONSTRAINT entity_uuid IF NOT EXISTS FOR (e:Entity) REQUIRE e.uuid IS UNIQUE",
            "CREATE CONSTRAINT event_uuid IF NOT EXISTS FOR (e:Event) REQUIRE e.uuid IS UNIQUE",
            "CREATE CONSTRAINT relation_uuid IF NOT EXISTS FOR ()-[r:RELATION]-() REQUIRE r.uuid IS UNIQUE",
        ]
        for stmt in statements:
            tx.run(stmt)

    # ------------------------------------------------------------------
    @staticmethod
    def _upsert_bundle(tx, document_id: str, entities, events, relations) -> None:  # type: ignore[no-untyped-def]
        for entity in entities:
            LegacyGraphIngestor._upsert_node(
                tx,
                label="Entity",
                data=entity,
                fallback_prefix=f"{document_id}:entity",
            )
        for event in events:
            LegacyGraphIngestor._upsert_node(
                tx,
                label="Event",
                data=event,
                fallback_prefix=f"{document_id}:event",
            )
        for rel in relations:
            LegacyGraphIngestor._upsert_relation(tx, rel, document_id)

    @staticmethod
    def _normalize_uuid(data: Dict[str, Any], fallback_prefix: str) -> str:
        for key in ("uuid", "id", "document_id"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        name = data.get("name") or data.get("title") or fallback_prefix
        return f"{fallback_prefix}:{name}"

    @staticmethod
    def _upsert_node(tx, label: str, data: Dict[str, Any], fallback_prefix: str) -> None:  # type: ignore[no-untyped-def]
        uuid = LegacyGraphIngestor._normalize_uuid(data, fallback_prefix)
        properties = {k: v for k, v in data.items() if v is not None}
        properties.setdefault("name", data.get("name") or data.get("title") or data.get("label"))
        tx.run(
            f"MERGE (n:{label} {{uuid: $uuid}})"
            " SET n += $props",
            uuid=uuid,
            props=properties,
        )

    @staticmethod
    def _upsert_relation(tx, rel: Dict[str, Any], document_id: str) -> None:  # type: ignore[no-untyped-def]
        source_id = rel.get("source") or rel.get("source_id")
        target_id = rel.get("target") or rel.get("target_id")
        if not source_id or not target_id:
            logger.debug("LegacyGraphIngestor: relation source/target 없음 -> 건너뜀: %s", rel)
            return
        relation_type = rel.get("relation") or rel.get("type") or "RELATED_TO"
        uuid = rel.get("uuid") or rel.get("id") or f"{document_id}:rel:{source_id}->{target_id}:{relation_type}"
        properties = {k: v for k, v in rel.items() if v is not None}
        properties.setdefault("document_id", document_id)

        tx.run(
            "MATCH (s:Entity {uuid: $source_id})"
            " MATCH (t:Entity {uuid: $target_id})"
            f" MERGE (s)-[r:{LegacyGraphIngestor._sanitize_rel_type(relation_type)} {{uuid: $uuid}}]->(t)"
            " SET r += $props",
            source_id=source_id,
            target_id=target_id,
            uuid=uuid,
            props=properties,
        )

    @staticmethod
    def _sanitize_rel_type(value: str) -> str:
        cleaned = value.upper().strip().replace(" ", "_")
        if not cleaned.isidentifier():
            return "RELATION"
        return cleaned

    # ------------------------------------------------------------------
    def close(self) -> None:
        if self.client:
            self.client.close()


__all__ = ["LegacyGraphIngestor"]
