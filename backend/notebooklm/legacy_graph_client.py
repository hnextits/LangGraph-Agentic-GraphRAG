#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Neo4j GraphDB 클라이언트 — Deep Graph Traversal + 인제스트."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

try:
    from neo4j import GraphDatabase
except Exception as exc:
    GraphDatabase = None  # type: ignore
    _import_error = exc
else:
    _import_error = None

logger = logging.getLogger(__name__)


class Neo4jGraphClient:
    """Neo4j에 연결해 다중 hop 경로를 조회하고 그래프 데이터를 인제스트하는 클라이언트."""

    def __init__(self, config) -> None:
        if GraphDatabase is None:
            raise ImportError(
                "neo4j 드라이버를 찾을 수 없습니다. 'pip install neo4j'로 설치하세요."
            ) from _import_error

        self.uri = getattr(config, "NEO4J_URI", "bolt://127.0.0.1:7687")
        user = getattr(config, "NEO4J_USER", "")
        password = getattr(config, "NEO4J_PASSWORD", "")
        auth = (user, password) if user else None

        logger.info("Neo4jGraphClient 연결 초기화: %s", self.uri)
        self.driver = GraphDatabase.driver(self.uri, auth=auth)

    # ------------------------------------------------------------------
    # 연결 종료
    # ------------------------------------------------------------------
    def close(self) -> None:
        if hasattr(self, "driver") and self.driver:
            try:
                self.driver.close()
            except Exception:
                logger.exception("Neo4jGraphClient 종료 중 오류")

    # ------------------------------------------------------------------
    # 데이터 인제스트 (.graph.json → Neo4j)
    # ------------------------------------------------------------------
    def ingest_graph_json(self, graph_json: Dict[str, Any]) -> Dict[str, int]:
        """.graph.json 데이터를 Neo4j에 MERGE로 업서트.

        Returns:
            {"entities": N, "relations": N} — 업서트된 건수
        """
        doc_id = graph_json.get("document_id", "")
        entities = graph_json.get("entities", [])
        relations = graph_json.get("relations", [])

        ent_count = 0
        rel_count = 0

        with self.driver.session() as session:
            # 엔티티 MERGE
            for ent in entities:
                ent_id = ent.get("entity_id") or ent.get("name") or "Unknown"
                name = ent.get("name") or ent_id
                etype = ent.get("type", "")
                try:
                    session.run(
                        "MERGE (e:Entity {id: $id}) "
                        "SET e.name = $name, e.type = $type, e.doc_id = $doc_id",
                        id=ent_id, name=name, type=etype, doc_id=doc_id,
                    )
                    ent_count += 1
                except Exception as exc:
                    logger.error("Neo4j entity MERGE 실패 (%s): %s", ent_id, exc)

            # 관계 MERGE
            for rel in relations:
                src = rel.get("source_id") or rel.get("source", "")
                tgt = rel.get("target_id") or rel.get("target", "")
                relation = rel.get("relationship") or rel.get("relation", "related_to")
                if not src or not tgt:
                    continue
                try:
                    session.run(
                        "MATCH (a:Entity {id: $src}), (b:Entity {id: $tgt}) "
                        "MERGE (a)-[r:RELATED {relation: $relation}]->(b) "
                        "SET r.doc_id = $doc_id",
                        src=src, tgt=tgt, relation=relation, doc_id=doc_id,
                    )
                    rel_count += 1
                except Exception as exc:
                    logger.error("Neo4j relation MERGE 실패 (%s->%s): %s", src, tgt, exc)

        logger.info("Neo4j 인제스트 완료: entities=%d, relations=%d (doc=%s)",
                    ent_count, rel_count, doc_id)
        return {"entities": ent_count, "relations": rel_count}

    # ------------------------------------------------------------------
    # Deep Graph Traversal (≥6-hop Cypher 쿼리)
    # ------------------------------------------------------------------
    def query_paths(
        self,
        query_text: str,
        max_hops: int = 6,
        max_paths: int = 20,
        max_start_nodes: int = 10,
    ) -> List[Dict[str, Any]]:
        """질문 텍스트의 키워드로 시작 노드를 찾고 multi-hop 경로를 탐색."""
        if not query_text:
            return []

        # 영문/숫자만 추출하여 키워드 생성 (한국어·특수문자 제거)
        ascii_only = re.sub(r'[^a-zA-Z0-9\s]', ' ', query_text)
        terms = [t.lower() for t in ascii_only.split() if len(t) >= 3]
        if not terms:
            logger.warning("Neo4j query_paths: 유효한 영문 키워드 없음 (원본: %s)", query_text[:80])
            return []

        cypher = """
        UNWIND $terms AS term
        MATCH (start:Entity)-[:RELATED]-()  
        WHERE toLower(start.name) CONTAINS term
        WITH DISTINCT start
        LIMIT $max_start_nodes
        MATCH path = (start)-[:RELATED*1..6]-(end:Entity)
        WITH DISTINCT nodes(path) AS ns, relationships(path) AS rs
        RETURN ns, rs
        LIMIT $max_paths
        """

        params = {
            "terms": terms,
            "max_start_nodes": max(1, max_start_nodes),
            "max_paths": max(1, max_paths),
        }

        try:
            with self.driver.session() as session:
                result = session.run(cypher, params)
                paths: List[Dict[str, Any]] = []
                for record in result:
                    nodes = record["ns"]
                    rels = record["rs"]
                    paths.append({
                        "nodes": [self._normalize_node(n) for n in nodes],
                        "relations": [self._normalize_relation(r) for r in rels],
                    })
                logger.info("Neo4j deep traversal: %d 경로 발견 (terms=%s)", len(paths), terms)
                return paths
        except Exception as exc:
            logger.error("Neo4j query_paths 실패: %s", exc)
            return []

    # ------------------------------------------------------------------
    # 정규화 헬퍼
    # ------------------------------------------------------------------
    def _normalize_node(self, node) -> Dict[str, Any]:
        properties = dict(node)
        return {
            "id": properties.get("id", ""),
            "name": properties.get("name", ""),
            "type": properties.get("type", ""),
            "doc_id": properties.get("doc_id", ""),
            "labels": list(getattr(node, "labels", [])),
        }

    def _normalize_relation(self, rel) -> Dict[str, Any]:
        properties = dict(rel)
        return {
            "type": getattr(rel, "type", "RELATED"),
            "relation": properties.get("relation", ""),
            "doc_id": properties.get("doc_id", ""),
        }


# 하위 호환 alias (legacy_graph_ingestor 등에서 기존 이름으로 import)
LegacyGraphClient = Neo4jGraphClient

__all__ = ["Neo4jGraphClient", "LegacyGraphClient"]
