#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""검색 로직 (Vector, CrossRef, GraphDB)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from weaviate.classes.query import Filter, MetadataQuery, QueryReference

logger = logging.getLogger(__name__)

class VectorRetriever:
    """Vector 기반 검색 (Path 1: BM25 단일 홉)."""

    _KO_JOSA_RE = re.compile(
        r"(은|는|이|가|을|를|의|에|에서|로|으로|와|과|도|만|까지|부터|에게|한테|께"
        r"|라|이라|란|이란|처럼|같이|보다|마다|밖에|뿐|조차|마저|야|이야|요|이요"
        r"|하고|이고|며|이며|든지|이든지|나|이나|라도|이라도|대로|뭔데|인데|인가|일까)$"
    )

    @staticmethod
    def _preprocess_bm25_query(query: str) -> str:
        """BM25 검색용 쿼리 전처리: 한국어 조사 제거 + 핵심 키워드 추출."""
        eng_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]+", query)
        ko_tokens = re.findall(r"[가-힣]+", query)
        cleaned_ko = []
        for tok in ko_tokens:
            stripped = VectorRetriever._KO_JOSA_RE.sub("", tok)
            if stripped and len(stripped) >= 2:
                cleaned_ko.append(stripped)
        tokens = eng_tokens + cleaned_ko
        result = " ".join(tokens) if tokens else query
        return result

    @staticmethod
    def _build_doc_filter(allowed_doc_ids: Optional[List[str]]):
        """allowed_doc_ids로 Weaviate document_id 필터 생성."""
        if not allowed_doc_ids:
            return None
        if len(allowed_doc_ids) == 1:
            return Filter.by_property("document_id").equal(allowed_doc_ids[0])
        return Filter.by_property("document_id").contains_any(allowed_doc_ids)

    @staticmethod
    def search_entities(graph_manager, query: str, limit: int = 5,
                       allowed_doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """BM25 기반 엔티티 검색."""
        if not graph_manager:
            return []
        try:
            collection = graph_manager.client.collections.get(
                graph_manager.ENTITY_CLASS.name
            )
            doc_filter = VectorRetriever._build_doc_filter(allowed_doc_ids)
            bm25_query = VectorRetriever._preprocess_bm25_query(query)
            logger.debug("BM25 엔티티 검색: '%s' → '%s'", query, bm25_query)
            response = collection.query.bm25(
                query=bm25_query,
                limit=limit,
                filters=doc_filter,
                return_metadata=MetadataQuery(score=True)
            )
            results = []
            for obj in response.objects:
                props = obj.properties or {}
                props.setdefault("bm25_score", getattr(obj.metadata, "score", None))
                results.append(props)
            return results
        except Exception as exc:
            logger.warning("엔티티 검색 실패: %s", exc)
            return []

    @staticmethod
    def search_events(graph_manager, query: str, limit: int = 5,
                     allowed_doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """BM25 기반 이벤트 검색."""
        if not graph_manager:
            return []
        try:
            collection = graph_manager.client.collections.get(
                graph_manager.EVENT_CLASS.name
            )
            doc_filter = VectorRetriever._build_doc_filter(allowed_doc_ids)
            bm25_query = VectorRetriever._preprocess_bm25_query(query)
            response = collection.query.bm25(
                query=bm25_query,
                limit=limit,
                filters=doc_filter,
                return_metadata=MetadataQuery(score=True)
            )
            results = []
            for obj in response.objects:
                props = obj.properties or {}
                props.setdefault("bm25_score", getattr(obj.metadata, "score", None))
                results.append(props)
            return results
        except Exception as exc:
            logger.warning("이벤트 검색 실패: %s", exc)
            return []

    @staticmethod
    def search_relations(graph_manager, entities: List[Dict[str, Any]],
                        events: List[Dict[str, Any]], limit: int = 10,
                        allowed_doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """관계 검색."""
        if not graph_manager:
            return []
        try:
            collection = graph_manager.client.collections.get(
                graph_manager.RELATION_CLASS.name
            )
            doc_filter = VectorRetriever._build_doc_filter(allowed_doc_ids)
            response = collection.query.fetch_objects(limit=limit, filters=doc_filter)
            results = []
            for obj in response.objects:
                props = obj.properties or {}
                results.append(props)
            return results
        except Exception as exc:
            logger.warning("관계 검색 실패: %s", exc)
            return []

    @staticmethod
    def search(graph_manager, query: str, max_hops: int,
               allowed_doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """BM25 기반 엔티티/이벤트 검색.

        Args:
            graph_manager: GraphSchemaManager 인스턴스
            query: 검색 쿼리
            max_hops: 최대 홉 수 (Vector는 단일 홉이므로 무시)
            allowed_doc_ids: 문서 필터

        Returns:
            {"entities": [...], "events": [...], "relations": [...]}
        """
        logger.info("VectorRetriever: BM25 검색 시작 (query='%s')", query[:50])
        entities = VectorRetriever.search_entities(graph_manager, query, limit=5, allowed_doc_ids=allowed_doc_ids)
        events = VectorRetriever.search_events(graph_manager, query, limit=5, allowed_doc_ids=allowed_doc_ids)
        relations = VectorRetriever.search_relations(graph_manager, entities, events, limit=10, allowed_doc_ids=allowed_doc_ids)
        logger.info("VectorRetriever: 검색 완료 (entities=%d, events=%d, relations=%d)",
                   len(entities), len(events), len(relations))
        return {"entities": entities, "events": events, "relations": relations}

class CrossRefRetriever:
    """Cross-Reference 기반 멀티홉 탐색 (Path 2)."""

    @staticmethod
    def get_entity_uuids_by_bm25(graph_manager, query: str, limit: int = 10,
                                 allowed_doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """BM25로 시드 엔티티를 검색하고 UUID + properties를 반환."""
        if not graph_manager:
            return []
        try:
            collection = graph_manager.client.collections.get(
                graph_manager.ENTITY_CLASS.name
            )
            doc_filter = VectorRetriever._build_doc_filter(allowed_doc_ids)
            bm25_query = VectorRetriever._preprocess_bm25_query(query)
            response = collection.query.bm25(
                query=bm25_query,
                limit=limit,
                filters=doc_filter,
                return_metadata=MetadataQuery(score=True),
            )
            results = []
            for obj in response.objects:
                props = obj.properties or {}
                props["_uuid"] = str(obj.uuid)
                props.setdefault("bm25_score", getattr(obj.metadata, "score", None))
                results.append(props)
            return results
        except Exception as exc:
            logger.warning("시드 엔티티 BM25 검색 실패: %s", exc)
            return []

    @staticmethod
    def crossref_traverse(graph_manager, seed_uuids: List[str], max_hops: int = 3,
                         allowed_doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Weaviate Cross-Reference를 따라 멀티홉 탐색."""
        if not graph_manager:
            return {"entities": [], "events": [], "relations": []}

        rel_collection = graph_manager.client.collections.get(
            graph_manager.RELATION_CLASS.name
        )
        doc_filter = VectorRetriever._build_doc_filter(allowed_doc_ids)

        visited_entity_uuids: set = set(seed_uuids)
        all_entities: List[Dict[str, Any]] = []
        all_events: List[Dict[str, Any]] = []
        all_relations: List[Dict[str, Any]] = []
        frontier_uuids = list(seed_uuids)

        for hop in range(max_hops):
            if not frontier_uuids:
                break

            next_frontier: List[str] = []

            try:
                response = rel_collection.query.fetch_objects(
                    limit=50,
                    filters=doc_filter,
                    return_references=[
                        QueryReference(
                            link_on="source",
                            return_properties=["text", "document_id"],
                        ),
                        QueryReference(
                            link_on="target",
                            return_properties=["text", "document_id"],
                        ),
                        QueryReference(
                            link_on="event",
                            return_properties=["text", "document_id"],
                        ),
                    ],
                )
            except Exception as exc:
                logger.warning("Cross-Reference 관계 탐색 실패 (hop %d): %s", hop, exc)
                break

            for rel_obj in response.objects:
                rel_props = rel_obj.properties or {}
                source_refs = rel_obj.references.get("source", None) if rel_obj.references else None
                target_refs = rel_obj.references.get("target", None) if rel_obj.references else None

                src_uuid = None
                tgt_uuid = None
                src_name = "?"
                tgt_name = "?"

                if source_refs and hasattr(source_refs, "objects") and source_refs.objects:
                    src_obj = source_refs.objects[0]
                    src_uuid = str(src_obj.uuid)
                    src_name = (src_obj.properties or {}).get("text", "?")

                if target_refs and hasattr(target_refs, "objects") and target_refs.objects:
                    tgt_obj = target_refs.objects[0]
                    tgt_uuid = str(tgt_obj.uuid)
                    tgt_name = (tgt_obj.properties or {}).get("text", "?")

                is_connected = (
                    (src_uuid and src_uuid in visited_entity_uuids)
                    or (tgt_uuid and tgt_uuid in visited_entity_uuids)
                )
                if not is_connected:
                    continue

                all_relations.append({
                    "relation": rel_props.get("text", "related_to"),
                    "source_name": src_name,
                    "target_name": tgt_name,
                    "document_id": rel_props.get("document_id", ""),
                })

                if src_uuid and src_uuid not in visited_entity_uuids:
                    visited_entity_uuids.add(src_uuid)
                    next_frontier.append(src_uuid)
                    all_entities.append({"name": src_name, "document_id": rel_props.get("document_id", "")})

                if tgt_uuid and tgt_uuid not in visited_entity_uuids:
                    visited_entity_uuids.add(tgt_uuid)
                    next_frontier.append(tgt_uuid)
                    all_entities.append({"name": tgt_name, "document_id": rel_props.get("document_id", "")})

            frontier_uuids = next_frontier
            logger.info("CrossRef hop %d: 새 엔티티 %d개, 관계 %d개", hop, len(next_frontier), len(all_relations))

        return {"entities": all_entities, "events": all_events, "relations": all_relations}

    @staticmethod
    def search(graph_manager, query: str, max_hops: int,
               allowed_doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Cross-Reference 기반 멀티홉 탐색.

        Args:
            graph_manager: GraphSchemaManager 인스턴스
            query: 검색 쿼리
            max_hops: 최대 홉 수
            allowed_doc_ids: 문서 필터

        Returns:
            {"entities": [...], "events": [...], "relations": [...]}
        """
        logger.info("CrossRefRetriever: 멀티홉 탐색 시작 (query='%s', max_hops=%d)", query[:50], max_hops)
        seed_entities = CrossRefRetriever.get_entity_uuids_by_bm25(graph_manager, query, limit=10, allowed_doc_ids=allowed_doc_ids)
        seed_uuids = [e.get("_uuid") for e in seed_entities if e.get("_uuid")]
        if not seed_uuids:
            logger.info("CrossRefRetriever: 시드 엔티티 없음")
            return {"entities": [], "events": [], "relations": []}
        result = CrossRefRetriever.crossref_traverse(graph_manager, seed_uuids, max_hops, allowed_doc_ids)
        logger.info("CrossRefRetriever: 탐색 완료 (entities=%d, events=%d, relations=%d)",
                   len(result["entities"]), len(result["events"]), len(result["relations"]))
        return result

class GraphDBRetriever:
    """Neo4j Cypher 기반 Deep Graph 탐색 (Path 3)."""

    @staticmethod
    def search(neo4j_client, query: str, max_hops: int,
               allowed_doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Neo4j Cypher 기반 Deep Graph 탐색.

        Args:
            neo4j_client: Neo4j 클라이언트 인스턴스
            query: 검색 쿼리
            max_hops: 최대 홉 수
            allowed_doc_ids: 문서 필터

        Returns:
            {"entities": [...], "events": [...], "relations": [...]}
        """
        logger.info("GraphDBRetriever: Neo4j Cypher 탐색 시작 (query='%s', max_hops=%d)", query[:50], max_hops)
        if not neo4j_client:
            logger.warning("GraphDBRetriever: Neo4j 클라이언트 없음")
            return {"entities": [], "events": [], "relations": []}

        entities = []
        relations = []
        events = []

        try:
            # Neo4j Deep Graph Traversal
            paths = neo4j_client.query_paths(
                query_text=query,
                max_hops=max_hops,
                max_paths=20,
                max_start_nodes=10,
            )
            
            # 경로 결과를 엔티티/관계 형태로 변환
            for path in paths:
                for node in path.get("nodes", []):
                    entities.append({
                        "name": node.get("name", "?"),
                        "type": node.get("type", ""),
                        "document_id": node.get("document_id", ""),
                    })
                for rel in path.get("relationships", []):
                    relations.append({
                        "source_name": rel.get("source", "?"),
                        "relation": rel.get("type", "related_to"),
                        "target_name": rel.get("target", "?"),
                    })

            logger.info("GraphDBRetriever: 탐색 완료 (entities=%d, relations=%d)", len(entities), len(relations))
        except Exception as exc:
            logger.warning("GraphDBRetriever: Neo4j 쿼리 실패: %s", exc)

        return {"entities": entities, "events": events, "relations": relations}
