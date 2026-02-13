#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Graph RAG / LangGraph 워크플로우 구현.

체크포인트: 모든 노드 전환 시 MemorySaver로 상태 저장
백트래킹: GoT 확장 실패 시 이전 체크포인트로 롤백, 3-Way Retrieval 결과 불충분 시 대체 경로 탐색
"""
from __future__ import annotations

import copy
import json
import logging
import operator
import os
import re
import uuid
from typing import Any, Annotated, Dict, List, Literal, Optional, Set, TypedDict

import requests

from weaviate.classes.query import MetadataQuery, Filter, QueryReference

from notebooklm.config import RAGConfig
from notebooklm.graph_schema import GraphSchemaManager

try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
    LANGGRAPH_AVAILABLE = True
except ImportError:
    StateGraph = END = MemorySaver = None
    LANGGRAPH_AVAILABLE = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State 정의 (TypedDict - LangGraph 체크포인터 호환)
# ---------------------------------------------------------------------------
class GraphReasonerState(TypedDict, total=False):
    query: str
    plan: Annotated[list, operator.add]
    hops: Annotated[list, operator.add]
    answer_notes: Annotated[list, operator.add]
    entities: list              # 배타적 실행: 각 Path가 덮어씀
    events: list                # 배타적 실행: 각 Path가 덮어씀
    relations: list             # 배타적 실행: 각 Path가 덮어씀
    context_snippets: list
    max_hops: int
    query_history: list
    thought_steps: Annotated[list, operator.add]
    candidate_queries: list
    active_query: str
    visited_queries: set
    retrieval_path: str          # "vector" | "cross_ref" | "graph_db"
    retrieval_quality: float     # 0.0 ~ 1.0
    backtrack_count: int
    state_checkpoint_id: str     # 현재 체크포인트 식별용
    allowed_doc_ids: list        # 허용된 문서 ID 목록 (프론트 필터링용)


# ---------------------------------------------------------------------------
# 초기 상태 생성 헬퍼
# ---------------------------------------------------------------------------
def _make_initial_state(query: str, allowed_doc_ids: Optional[List[str]] = None) -> GraphReasonerState:
    return GraphReasonerState(
        query=query,
        plan=[],
        hops=[],
        answer_notes=[],
        entities=[],
        events=[],
        relations=[],
        context_snippets=[],
        max_hops=1,
        query_history=[],
        thought_steps=[],
        candidate_queries=[],
        active_query="",
        visited_queries=set(),
        retrieval_path="",
        retrieval_quality=0.0,
        backtrack_count=0,
        state_checkpoint_id="",
        allowed_doc_ids=allowed_doc_ids or [],
    )


class GraphReasoner:
    """LangGraph 기반 그래프 RAG 파이프라인.

    체크포인트: MemorySaver로 모든 노드 전환 시 상태 저장
    라우팅: Path 1/2/3 중 하나를 배타적으로 선택하여 실행
    백트래킹: 관찰자 LLM 품질 평가 후 부족하면 다른 Path로 전환
    """

    MAX_BACKTRACK = 2  # 백트래킹 최대 횟수

    def __init__(self, config: Optional[RAGConfig] = None) -> None:
        self.config = config or RAGConfig()
        self.graph_enabled = bool(getattr(self.config, "GRAPH_RAG_ENABLED", False))
        self.langgraph_enabled = bool(getattr(self.config, "LANGGRAPH_ENABLED", False)) and LANGGRAPH_AVAILABLE
        self.got_enabled = bool(getattr(self.config, "GOT_MODE_ENABLED", False))
        self.graph_manager: Optional[GraphSchemaManager] = None
        self.workflow = None
        self.checkpointer = None

        self.neo4j_client = None

        if self.graph_enabled:
            try:
                self.graph_manager = GraphSchemaManager(self.config)
                logger.info("GraphSchemaManager 초기화 완료")
                # Neo4j 클라이언트 참조 (graph_manager에서 초기화된 것 재사용)
                if self.graph_manager and self.graph_manager.neo4j_client:
                    self.neo4j_client = self.graph_manager.neo4j_client
                    logger.info("Neo4j 클라이언트 연결 완료 (Deep Graph Traversal 활성화)")
            except Exception as exc:
                logger.warning("GraphSchemaManager 초기화 실패: %s", exc)
                self.graph_enabled = False

        if self.langgraph_enabled:
            self.checkpointer = MemorySaver()
            self.workflow = self._build_workflow()

    # ------------------------------------------------------------------
    # LLM 기반 홉 분류 (HopClassifier)
    # ------------------------------------------------------------------
    def _classify_hops_llm(self, query: str) -> Optional[int]:
        """SGLang generator 서버로 쿼리 복잡도를 1~6 정수로 분류.

        Returns:
            1~6 정수 또는 None (호출 실패 시)
        """
        endpoint = getattr(self.config, "HOP_CLASSIFIER_SGLANG_ENDPOINT", None)
        if not endpoint:
            return None

        api_url = f"{endpoint}/v1/chat/completions"
        model = getattr(self.config, "HOP_CLASSIFIER_MODEL", "default")
        timeout = getattr(self.config, "HOP_CLASSIFIER_TIMEOUT", 15)
        max_tokens = getattr(self.config, "HOP_CLASSIFIER_MAX_TOKENS", 8)

        system_prompt = (
            "You are a query complexity classifier for a graph database. "
            "Given a user question, output ONLY a single integer from 1 to 6 representing the number of hops needed.\n"
            "Guidelines:\n"
            "1-2: Simple factual / definition questions (e.g. 'What is PPO?')\n"
            "3-5: Comparison, relationship, or dependency questions (e.g. 'How does SFT relate to Reward model?')\n"
            "6: Multi-step chain / pipeline / end-to-end flow questions (e.g. 'Trace the full path from A→B→C→D')\n"
            "Output ONLY the integer. No explanation."
        )

        try:
            resp = requests.post(
                api_url,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.0,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            # 닫힌 <think> 태그 제거
            text = re.sub(r'<[tT]hink>.*?</[tT]hink>', '', text, flags=re.DOTALL).strip()
            # 닫히지 않은 <think> 태그도 제거 (max_tokens로 잘린 경우)
            text = re.sub(r'<[tT]hink>.*', '', text, flags=re.DOTALL).strip()
            # 숫자만 추출
            match = re.search(r'[1-6]', text)
            if match:
                hops = int(match.group())
                logger.info("HopClassifier(LLM): query='%s' → hops=%d (raw='%s')", query[:50], hops, text)
                return hops
            logger.warning("HopClassifier(LLM): 파싱 실패 raw='%s'", text)
        except Exception as exc:
            logger.warning("HopClassifier(LLM) 호출 실패: %s", exc)
        return None

    # ------------------------------------------------------------------
    # 휴리스틱 기반 홉 분류 (fallback)
    # ------------------------------------------------------------------
    @staticmethod
    def _classify_hops_heuristic(query: str) -> int:
        """키워드/패턴 기반 복잡도 점수 → 1~6 정수."""
        q = query.lower()
        score = 0

        # 화살표 개수: 명시적 체인 표현
        arrow_count = q.count("→") + q.count("->")
        score += arrow_count * 2

        # deep 키워드 (+3점)
        deep_kw = [
            r"이어지는|흐름|전체.*경로|체인|파이프라인|단계.*거쳐",
            r"모든.*연결|병목|end.to.end|전파|순서대로",
            r"어떻게.*거쳐|경유|다단계|멀티.?홉|multi.?hop",
        ]
        for pat in deep_kw:
            if re.search(pat, q):
                score += 3

        # mid 키워드 (+2점)
        mid_kw = [
            r"비교|차이|관계|의존|영향|상호작용|연관",
            r"어떻게.*다른|versus|vs\b|trade.?off",
            r"장단점|pros.*cons|결합|통합",
        ]
        for pat in mid_kw:
            if re.search(pat, q):
                score += 2

        # 슬래시(/) 또는 쉼표로 나열된 개념 수 (+1점/개)
        concept_seps = len(re.findall(r"[/,]", q))
        score += concept_seps

        return max(1, min(6, score))

    # ------------------------------------------------------------------
    # 워크플로우 빌드 (체크포인터 + 3-Way 라우팅 + 백트래킹)
    # ------------------------------------------------------------------
    def _build_workflow(self):
        """LangGraph 워크플로우 구성.

        노드 구성:
          planner → router → vector_retriever / crossref_retriever / graphdb_retriever
                  → quality_gate → (백트래킹 or thought_expander) → aggregator

        체크포인트: MemorySaver로 모든 노드 전환 시 자동 저장
        백트래킹: quality_gate에서 결과 불충분 시 대체 경로로 재시도
        """
        if not self.langgraph_enabled or not LANGGRAPH_AVAILABLE:
            return None

        graph = StateGraph(GraphReasonerState)
        reasoner = self  # 클로저에서 self 참조

        # --- 노드 함수 정의 ---

        def planner(state: GraphReasonerState) -> dict:
            """질문 분석 및 검색 계획 수립 — 쿼리 복잡도 기반 max_hops 동적 결정"""
            updates: dict = {}
            plan_items = []
            if not state.get("plan"):
                plan_items.append("질문을 분석하고 필요한 엔티티를 식별")
                plan_items.append("관련 이벤트 및 관계 추적")
                if reasoner.got_enabled:
                    plan_items.append("GoT: 엣지 품질을 평가하여 필요시 백트래킹")

            # --- LLM + 휴리스틱 하이브리드 홉 분류 ---
            hop_cap = max(1, getattr(reasoner.config, "GRAPH_MAX_HOPS", 6))
            query = state["query"]

            # 1차: LLM 판단
            llm_hops = reasoner._classify_hops_llm(query)
            # 2차: 휴리스틱 (항상 계산 — fallback 및 로깅용)
            heuristic_hops = reasoner._classify_hops_heuristic(query)

            if llm_hops is not None:
                estimated = llm_hops
                method = "LLM"
            else:
                estimated = heuristic_hops
                method = "heuristic"

            max_hops = min(estimated, hop_cap)
            updates["max_hops"] = max_hops
            logger.info(
                "Planner: %s → estimated=%d (llm=%s, heuristic=%d), cap=%d, max_hops=%d",
                method, estimated, llm_hops, heuristic_hops, hop_cap, max_hops,
            )
            qh = list(state.get("query_history", []))
            if not qh:
                qh.append(state["query"])
            updates["query_history"] = qh
            updates["state_checkpoint_id"] = f"plan_{uuid.uuid4().hex[:8]}"
            if plan_items:
                updates["plan"] = plan_items
            return updates

        def router(state: GraphReasonerState) -> dict:
            """쿼리 복잡도에 따라 3-Way Retrieval 경로 결정 (배타적 선택).

            Condition A (≤2-hop): vector  → rag_pipeline에서 기존 벡터 검색으로 위임
            Condition B (3-5 hop): cross_ref → Weaviate Cross-Reference GraphRAG
            Condition C (≥6-hop): graph_db  → Neo4j Deep Graph Traversal

            백트래킹 시: quality_gate가 설정한 대체 경로를 사용
            """
            backtrack_count = state.get("backtrack_count", 0)

            # 백트래킹 중이면 quality_gate가 설정한 대체 경로를 사용
            if backtrack_count > 0:
                path = state.get("retrieval_path", "vector")
                logger.info("Router(백트래킹 %d회): path=%s", backtrack_count, path)
                # 백트래킹 시 이전 검색 결과 초기화 (배타적 실행)
                return {
                    "retrieval_path": path,
                    "entities": [],
                    "events": [],
                    "relations": [],
                    "answer_notes": [f"백트래킹 라우팅: {path} (backtrack={backtrack_count})"],
                }

            # 최초 라우팅: max_hops 기반
            max_hops = state.get("max_hops", 1)
            if max_hops <= 2:
                path = "vector"
            elif max_hops <= 5:
                path = "cross_ref"
            else:
                path = "graph_db"
            logger.info("Router: max_hops=%d → path=%s", max_hops, path)
            return {
                "retrieval_path": path,
                "answer_notes": [f"라우팅: {path} (max_hops={max_hops})"],
            }

        def vector_retriever(state: GraphReasonerState) -> dict:
            """Path 1: rag_pipeline에서 기존 벡터 검색(TextSearcher+리랭커)으로 위임.

            GraphReasoner 내부에서는 별도 검색/평가를 하지 않음.
            quality=1.0으로 설정하여 quality_gate를 무조건 통과.
            """
            logger.info("Vector Retriever: rag_pipeline의 기존 벡터 검색으로 위임 (GraphReasoner 내부 검색 생략)")
            return {
                "entities": [],
                "events": [],
                "relations": [],
                "hops": [],
                "retrieval_quality": 1.0,
                "answer_notes": ["Vector Retrieval: rag_pipeline 기존 벡터 검색으로 위임"],
            }

        def crossref_retriever(state: GraphReasonerState) -> dict:
            """Path 2: Weaviate Cross-Reference GraphQL 방식 멀티홉 탐색.

            1) BM25로 시드 엔티티 검색 (UUID 포함)
            2) Cross-Reference를 따라 연결된 엔티티/이벤트/관계를 멀티홉 탐색
            3) 관찰자 LLM이 전체 결과 품질 평가
            """
            query = state["query"]
            max_hops = state.get("max_hops", 3)
            doc_ids = state.get("allowed_doc_ids") or None

            # 1) BM25로 시드 엔티티 검색 (UUID 포함)
            seed_entities = reasoner._get_entity_uuids_by_bm25(
                query, limit=10, allowed_doc_ids=doc_ids
            )
            seed_uuids = [e["_uuid"] for e in seed_entities if e.get("_uuid")]
            logger.info("Cross-Ref 시드 엔티티: %d개 (BM25)", len(seed_entities))

            if not seed_uuids:
                # 시드가 없으면 빈 결과 반환
                quality = 0.0
                return {
                    "entities": [],
                    "events": [],
                    "relations": [],
                    "hops": [],
                    "retrieval_quality": quality,
                    "answer_notes": ["Cross-Ref GraphQL: 시드 엔티티 없음"],
                }

            # 2) Cross-Reference를 따라 멀티홉 탐색
            traversal = reasoner._crossref_traverse(
                seed_uuids, max_hops=max_hops, allowed_doc_ids=doc_ids
            )

            # 시드 엔티티 + 탐색된 엔티티 합치기
            all_entities = list(seed_entities) + traversal["entities"]
            all_events = traversal["events"]
            all_relations = traversal["relations"]

            logger.info(
                "Cross-Ref GraphQL 결과: 엔티티 %d (시드 %d + 탐색 %d), 이벤트 %d, 관계 %d",
                len(all_entities), len(seed_entities), len(traversal["entities"]),
                len(all_events), len(all_relations),
            )

            # 3) 관찰자 LLM이 쿼리 + 검색 결과 관련성 평가
            quality = reasoner._evaluate_quality_with_llm(
                query, all_entities, all_events, all_relations
            )

            hop_summary = (
                [f"엔티티: {e.get('name', '?')}" for e in all_entities]
                + [f"이벤트: {e.get('title', '?')}" for e in all_events]
            )
            return {
                "entities": all_entities,
                "events": all_events,
                "relations": all_relations,
                "hops": hop_summary,
                "retrieval_quality": quality,
                "answer_notes": [
                    f"Cross-Ref GraphQL: 엔티티 {len(all_entities)}, "
                    f"이벤트 {len(all_events)}, 관계 {len(all_relations)}, "
                    f"품질 {quality:.2f}"
                ],
            }

        def graphdb_retriever(state: GraphReasonerState) -> dict:
            """Path 3: Neo4j Deep Graph Traversal (≥6-hop)"""
            query = state["query"]

            if reasoner.neo4j_client is None:
                # Neo4j 미연결 시 Weaviate fallback
                logger.warning("Neo4j 미연결 → Weaviate bm25 fallback")
                doc_ids = state.get("allowed_doc_ids") or None
                entities = reasoner._search_entities(query, limit=15, allowed_doc_ids=doc_ids)
                events = reasoner._search_events(query, limit=15, allowed_doc_ids=doc_ids)
                relations = reasoner._search_relations(entities, events, limit=30, allowed_doc_ids=doc_ids)
                # 관찰자 LLM이 쿼리 + 검색 결과 관련성 평가
                quality = reasoner._evaluate_quality_with_llm(query, entities, events, relations)
                return {
                    "entities": entities, "events": events, "relations": relations,
                    "hops": [f"엔티티: {e.get('name', '?')}" for e in entities],
                    "retrieval_quality": quality,
                    "answer_notes": [f"Graph DB Fallback(Weaviate): 엔티티 {len(entities)}, 품질 {quality:.2f}"],
                }

            # Neo4j Deep Graph Traversal
            max_hops = state.get("max_hops", 6)
            paths = reasoner.neo4j_client.query_paths(
                query_text=query, max_hops=max_hops,
                max_paths=20, max_start_nodes=10,
            )

            # 경로 결과를 엔티티/관계 형태로 변환
            entities = []
            relations = []
            seen_nodes = set()
            seen_rels = set()

            for path in paths:
                for node in path.get("nodes", []):
                    nid = node.get("id", "")
                    if nid and nid not in seen_nodes:
                        seen_nodes.add(nid)
                        entities.append({
                            "name": node.get("name", ""),
                            "type": node.get("type", ""),
                            "document_id": node.get("doc_id", ""),
                        })
                for rel in path.get("relations", []):
                    rel_key = f"{rel.get('type', '')}_{rel.get('relation', '')}"
                    if rel_key not in seen_rels:
                        seen_rels.add(rel_key)
                        relations.append({
                            "relation": rel.get("relation", ""),
                            "type": rel.get("type", "RELATED"),
                        })

            # 관찰자 LLM이 쿼리 + 검색 결과 관련성 평가
            quality = reasoner._evaluate_quality_with_llm(query, entities, [], relations) if entities else 0.0

            hop_summary = [f"엔티티: {e.get('name', '?')}" for e in entities[:20]]

            logger.info("Neo4j Deep Traversal: %d 경로, %d 엔티티, %d 관계, 품질 %.2f",
                        len(paths), len(entities), len(relations), quality)

            return {
                "entities": entities,
                "events": [],
                "relations": relations,
                "hops": hop_summary,
                "retrieval_quality": quality,
                "answer_notes": [
                    f"Neo4j Deep Traversal: {len(paths)} 경로, "
                    f"{len(entities)} 엔티티, {len(relations)} 관계, 품질 {quality:.2f}"
                ],
            }

        def quality_gate(state: GraphReasonerState) -> dict:
            """검색 결과 품질 평가 및 백트래킹 판단.

            관찰자 LLM이 평가한 quality 기반으로:
            - quality >= 0.3: 통과 → aggregator로 진행
            - quality < 0.3 & 백트래킹 한도 미도달: 다른 Path로 전환
            - quality < 0.3 & 백트래킹 한도 도달: 현재 결과로 진행
            """
            quality = state.get("retrieval_quality", 0.0)
            backtrack_count = state.get("backtrack_count", 0)
            path = state.get("retrieval_path", "vector")

            if quality >= 0.3 or backtrack_count >= self.MAX_BACKTRACK:
                if backtrack_count >= self.MAX_BACKTRACK and quality < 0.3:
                    logger.info("품질 게이트 [%s]: 백트래킹 한도 도달 (quality=%.2f), 현재 결과로 진행", path, quality)
                    return {"answer_notes": [f"품질 게이트 [{path}]: 백트래킹 한도 도달 (quality={quality:.2f})"]}
                logger.info("품질 게이트 [%s]: 통과 (quality=%.2f)", path, quality)
                return {"answer_notes": [f"품질 게이트 [{path}]: 통과 (quality={quality:.2f})"]}

            # 백트래킹: 다른 Path로 전환
            fallback_order = ["vector", "cross_ref", "graph_db"]
            current_idx = fallback_order.index(path) if path in fallback_order else 0
            next_idx = (current_idx + 1) % len(fallback_order)
            next_path = fallback_order[next_idx]

            logger.info("백트래킹: %s → %s (quality=%.2f, backtrack=%d)",
                        path, next_path, quality, backtrack_count + 1)
            return {
                "retrieval_path": next_path,
                "backtrack_count": backtrack_count + 1,
                "answer_notes": [f"백트래킹: {path} → {next_path} (quality={quality:.2f})"],
            }

        def thought_expander(state: GraphReasonerState) -> dict:
            """GoT 기반 사고 확장 (백트래킹 포함)"""
            if not reasoner.got_enabled:
                return {}

            # GoT 확장 전 상태 스냅샷 (백트래킹용)
            pre_entities_count = len(state.get("entities", []))
            pre_events_count = len(state.get("events", []))

            got_result = reasoner._run_got_expansion(state)

            post_entities_count = len(got_result.get("entities", []))
            post_events_count = len(got_result.get("events", []))
            delta = (post_entities_count - pre_entities_count) + (post_events_count - pre_events_count)

            if delta == 0:
                return {
                    "answer_notes": ["GoT: 확장 실패 - 새로운 노드 없음, 기존 결과 유지"],
                    "thought_steps": got_result.get("thought_steps", []),
                }

            # entities/events/relations는 replace 방식이므로 기존 + 신규를 합쳐서 반환
            merged_entities = list(state.get("entities", [])) + got_result.get("entities", [])
            merged_events = list(state.get("events", [])) + got_result.get("events", [])
            merged_relations = list(state.get("relations", [])) + got_result.get("relations", [])
            return {
                "entities": merged_entities,
                "events": merged_events,
                "relations": merged_relations,
                "thought_steps": got_result.get("thought_steps", []),
                "candidate_queries": got_result.get("candidate_queries", []),
                "visited_queries": got_result.get("visited_queries", set()),
                "answer_notes": [f"GoT: {delta}개 노드 확장 성공"],
            }

        def aggregator(state: GraphReasonerState) -> dict:
            """최종 결과 집계 및 컨텍스트 스니펫 생성"""
            entities = state.get("entities", [])
            events = state.get("events", [])
            notes = []

            if entities or events:
                notes.append(f"최종 결과 - 엔티티 {len(entities)}개, 이벤트 {len(events)}개")
            else:
                notes.append("그래프 탐색에서 관련 노드를 찾지 못했습니다.")

            snippets = reasoner._build_context_snippets(state)
            if snippets:
                notes.append(f"컨텍스트 스니펫 {len(snippets)}건 생성")

            thought_steps = state.get("thought_steps", [])
            if reasoner.got_enabled and thought_steps:
                notes.append(f"GoT: {len(thought_steps)} 단계 추론 기록")

            backtrack_count = state.get("backtrack_count", 0)
            if backtrack_count > 0:
                notes.append(f"백트래킹 {backtrack_count}회 수행")

            return {
                "context_snippets": snippets,
                "answer_notes": notes,
            }

        # --- 라우팅 함수 ---

        def route_by_path(state: GraphReasonerState) -> str:
            """router 노드 이후 3-Way 분기"""
            path = state.get("retrieval_path", "vector")
            if path == "cross_ref":
                return "crossref_retriever"
            elif path == "graph_db":
                return "graphdb_retriever"
            return "vector_retriever"

        def route_after_quality(state: GraphReasonerState) -> str:
            """quality_gate 이후: 통과 시 다음 단계, 부족 시 router로 백트래킹"""
            quality = state.get("retrieval_quality", 0.0)
            backtrack_count = state.get("backtrack_count", 0)

            if quality >= 0.3 or backtrack_count >= self.MAX_BACKTRACK:
                if reasoner.got_enabled:
                    return "thought_expander"
                return "aggregator"
            # 백트래킹: router로 돌아가서 다른 Path 시도
            return "router"

        # --- 그래프 구성 ---
        graph.add_node("planner", planner)
        graph.add_node("router", router)
        graph.add_node("vector_retriever", vector_retriever)
        graph.add_node("crossref_retriever", crossref_retriever)
        graph.add_node("graphdb_retriever", graphdb_retriever)
        graph.add_node("quality_gate", quality_gate)
        graph.add_node("thought_expander", thought_expander)
        graph.add_node("aggregator", aggregator)

        # 엣지 연결
        graph.add_edge("planner", "router")
        graph.add_conditional_edges("router", route_by_path, {
            "vector_retriever": "vector_retriever",
            "crossref_retriever": "crossref_retriever",
            "graphdb_retriever": "graphdb_retriever",
        })
        graph.add_edge("vector_retriever", "quality_gate")
        graph.add_edge("crossref_retriever", "quality_gate")
        graph.add_edge("graphdb_retriever", "quality_gate")
        graph.add_conditional_edges("quality_gate", route_after_quality, {
            "router": "router",               # 백트래킹
            "thought_expander": "thought_expander",
            "aggregator": "aggregator",
        })
        graph.add_edge("thought_expander", "aggregator")
        graph.add_edge("aggregator", END)

        graph.set_entry_point("planner")
        compiled = graph.compile(checkpointer=self.checkpointer)
        logger.info("LangGraph 워크플로우 초기화 완료 (체크포인터: MemorySaver, 백트래킹: 최대 %d회)", self.MAX_BACKTRACK)
        return compiled

    # ------------------------------------------------------------------
    def retrieve(self, query: str, session_id: Optional[str] = None,
                 allowed_document_uuids: Optional[Set[str]] = None) -> Dict[str, Any]:
        """그래프 기반 탐색 결과를 반환."""
        payload: Dict[str, Any] = {
            "graph_rag_enabled": self.graph_enabled,
            "langgraph_enabled": self.langgraph_enabled,
            "got_enabled": self.got_enabled,
            "plan": [],
            "hops": [],
            "notes": [],
            "nodes": [],
            "relations": [],
            "context_snippets": [],
        }

        if not self.graph_enabled:
            payload["notes"].append("GRAPH_RAG_ENABLED=False")
            return payload

        # UUID → document_id(파일명) 변환
        # 프론트에서 전달하는 allowed_document_uuids는 TextDocument의 UUID이지만,
        # GraphEntity/Event/Relation은 document_id(파일명)로 저장되어 있으므로 변환 필요
        resolved_doc_ids: Optional[List[str]] = None
        if allowed_document_uuids and self.graph_manager:
            try:
                text_coll = self.graph_manager.client.collections.get("TextDocument")
                doc_id_set: set = set()
                for doc_uuid in allowed_document_uuids:
                    if not doc_uuid:
                        continue
                    try:
                        obj = text_coll.query.fetch_object_by_id(
                            doc_uuid, return_properties=["source"]
                        )
                    except Exception:
                        obj = None
                    if obj is None:
                        # fallback: document_uuid 속성으로 검색
                        resp = text_coll.query.fetch_objects(
                            filters=Filter.by_property("document_uuid").equal(doc_uuid),
                            limit=1,
                            return_properties=["source"],
                        )
                        obj = resp.objects[0] if resp.objects else None
                    if obj and getattr(obj, "properties", None):
                        src = obj.properties.get("source", "")
                        if src:
                            doc_id_set.add(os.path.splitext(os.path.basename(src))[0])
                if doc_id_set:
                    resolved_doc_ids = list(doc_id_set)
                    logger.info("UUID→doc_id 변환: %s → %s", list(allowed_document_uuids), resolved_doc_ids)
                else:
                    logger.warning("UUID→doc_id 변환 실패: 매칭되는 문서 없음")
            except Exception as exc:
                logger.warning("UUID→doc_id 변환 중 오류: %s", exc)

        try:
            result_state = self._run_workflow(
                query, allowed_doc_ids=resolved_doc_ids
            )
            payload["plan"] = list(result_state.get("plan", []))
            payload["hops"] = list(result_state.get("hops", []))
            payload["notes"].extend(result_state.get("answer_notes", []))
            payload["nodes"] = list(result_state.get("entities", []) + result_state.get("events", []))
            payload["relations"] = list(result_state.get("relations", []))
            payload["context_snippets"] = list(result_state.get("context_snippets", []))
            payload["retrieval_path"] = result_state.get("retrieval_path", "unknown")
            payload["max_hops"] = result_state.get("max_hops", 1)
            payload["retrieval_quality"] = result_state.get("retrieval_quality", 0.0)
            if result_state.get("thought_steps"):
                payload["thought_steps"] = list(result_state["thought_steps"])
            if result_state.get("backtrack_count", 0) > 0:
                payload["backtrack_count"] = result_state["backtrack_count"]
        except Exception as exc:
            logger.warning("GraphReasoner 실행 실패: %s", exc)
            payload["notes"].append(f"LangGraph 실행 실패: {exc}")

        if session_id:
            payload["notes"].append(f"session_id={session_id}")
        return payload

    # ------------------------------------------------------------------
    def close(self) -> None:
        if self.graph_manager:
            try:
                self.graph_manager.close()
            except Exception:
                logger.exception("GraphSchemaManager 정리 중 오류")

    # ------------------------------------------------------------------
    # 검색 메서드
    # ------------------------------------------------------------------
    _KO_JOSA_RE = re.compile(
        r"(은|는|이|가|을|를|의|에|에서|로|으로|와|과|도|만|까지|부터|에게|한테|께"
        r"|라|이라|란|이란|처럼|같이|보다|마다|밖에|뿐|조차|마저|야|이야|요|이요"
        r"|하고|이고|며|이며|든지|이든지|나|이나|라도|이라도|대로|뭔데|인데|인가|일까)$"
    )

    @staticmethod
    def _preprocess_bm25_query(query: str) -> str:
        """BM25 검색용 쿼리 전처리: 한국어 조사 제거 + 핵심 키워드 추출."""
        # 1. 영문 약어/단어 추출 (DPO, RLHF, PPO 등)
        eng_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]+", query)
        # 2. 한글 토큰 추출 후 조사 제거
        ko_tokens = re.findall(r"[가-힣]+", query)
        cleaned_ko = []
        for tok in ko_tokens:
            stripped = GraphReasoner._KO_JOSA_RE.sub("", tok)
            if stripped and len(stripped) >= 2:
                cleaned_ko.append(stripped)
        # 3. 합치기 (영문 우선)
        tokens = eng_tokens + cleaned_ko
        result = " ".join(tokens) if tokens else query
        return result

    @staticmethod
    def _build_doc_filter(allowed_doc_ids: Optional[List[str]]) -> Optional[Filter]:
        """allowed_doc_ids로 Weaviate document_id 필터 생성."""
        if not allowed_doc_ids:
            return None
        if len(allowed_doc_ids) == 1:
            return Filter.by_property("document_id").equal(allowed_doc_ids[0])
        return Filter.by_property("document_id").contains_any(allowed_doc_ids)

    def _search_entities(self, query: str, limit: int = 5,
                         allowed_doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not self.graph_manager:
            return []
        try:
            collection = self.graph_manager.client.collections.get(
                self.graph_manager.ENTITY_CLASS.name
            )
            doc_filter = self._build_doc_filter(allowed_doc_ids)
            bm25_query = self._preprocess_bm25_query(query)
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

    def _search_events(self, query: str, limit: int = 5,
                       allowed_doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not self.graph_manager:
            return []
        try:
            collection = self.graph_manager.client.collections.get(
                self.graph_manager.EVENT_CLASS.name
            )
            doc_filter = self._build_doc_filter(allowed_doc_ids)
            bm25_query = self._preprocess_bm25_query(query)
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

    def _search_relations(
        self,
        entities: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        limit: int = 10,
        allowed_doc_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not self.graph_manager:
            return []
        try:
            collection = self.graph_manager.client.collections.get(
                self.graph_manager.RELATION_CLASS.name
            )
            doc_filter = self._build_doc_filter(allowed_doc_ids)
            response = collection.query.fetch_objects(limit=limit, filters=doc_filter)
            results = []
            for obj in response.objects:
                props = obj.properties or {}
                results.append(props)
            return results
        except Exception as exc:
            logger.warning("관계 검색 실패: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Cross-Reference 기반 멀티홉 탐색 (Path 2 전용)
    # ------------------------------------------------------------------
    def _get_entity_uuids_by_bm25(
        self, query: str, limit: int = 10,
        allowed_doc_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """BM25로 시드 엔티티를 검색하고 UUID + properties를 반환."""
        if not self.graph_manager:
            return []
        try:
            collection = self.graph_manager.client.collections.get(
                self.graph_manager.ENTITY_CLASS.name
            )
            doc_filter = self._build_doc_filter(allowed_doc_ids)
            bm25_query = self._preprocess_bm25_query(query)
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

    def _crossref_traverse(
        self,
        seed_uuids: List[str],
        max_hops: int = 3,
        allowed_doc_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Weaviate Cross-Reference를 따라 멀티홉 탐색.

        GraphRelation의 source/target Cross-Reference를 따라가며
        연결된 엔티티와 이벤트를 수집합니다.

        Returns:
            {"entities": [...], "events": [...], "relations": [...]}
        """
        if not self.graph_manager:
            return {"entities": [], "events": [], "relations": []}

        rel_collection = self.graph_manager.client.collections.get(
            self.graph_manager.RELATION_CLASS.name
        )
        doc_filter = self._build_doc_filter(allowed_doc_ids)

        visited_entity_uuids: set = set(seed_uuids)
        all_entities: List[Dict[str, Any]] = []
        all_events: List[Dict[str, Any]] = []
        all_relations: List[Dict[str, Any]] = []
        frontier_uuids = list(seed_uuids)

        for hop in range(max_hops):
            if not frontier_uuids:
                break

            next_frontier: List[str] = []

            # GraphRelation에서 source/target Cross-Reference를 따라 탐색
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
                event_refs = rel_obj.references.get("event", None) if rel_obj.references else None

                src_uuid = None
                tgt_uuid = None
                src_name = "?"
                tgt_name = "?"

                # source Cross-Reference 확인
                if source_refs and hasattr(source_refs, "objects") and source_refs.objects:
                    src_obj = source_refs.objects[0]
                    src_uuid = str(src_obj.uuid)
                    src_name = (src_obj.properties or {}).get("text", "?")

                # target Cross-Reference 확인
                if target_refs and hasattr(target_refs, "objects") and target_refs.objects:
                    tgt_obj = target_refs.objects[0]
                    tgt_uuid = str(tgt_obj.uuid)
                    tgt_name = (tgt_obj.properties or {}).get("text", "?")

                # 현재 frontier에 속하는 관계만 수집
                is_connected = (
                    (src_uuid and src_uuid in visited_entity_uuids)
                    or (tgt_uuid and tgt_uuid in visited_entity_uuids)
                )
                if not is_connected:
                    continue

                # 관계 수집
                all_relations.append({
                    "relation": rel_props.get("text", "related_to"),
                    "source_name": src_name,
                    "target_name": tgt_name,
                    "document_id": rel_props.get("document_id", ""),
                })

                # 연결된 엔티티를 다음 frontier에 추가
                for ref_uuid, ref_name in [(src_uuid, src_name), (tgt_uuid, tgt_name)]:
                    if ref_uuid and ref_uuid not in visited_entity_uuids:
                        visited_entity_uuids.add(ref_uuid)
                        next_frontier.append(ref_uuid)
                        all_entities.append({
                            "name": ref_name,
                            "_uuid": ref_uuid,
                            "hop": hop + 1,
                        })

                # event Cross-Reference 확인
                if event_refs and hasattr(event_refs, "objects") and event_refs.objects:
                    for evt_obj in event_refs.objects:
                        evt_props = evt_obj.properties or {}
                        all_events.append({
                            "title": evt_props.get("text", "?"),
                            "document_id": evt_props.get("document_id", ""),
                        })

            frontier_uuids = next_frontier
            logger.info("Cross-Ref hop %d: 새 엔티티 %d개, 관계 %d개 누적",
                        hop + 1, len(next_frontier), len(all_relations))

        return {
            "entities": all_entities,
            "events": all_events,
            "relations": all_relations,
        }

    # ------------------------------------------------------------------
    # 품질 평가
    # ------------------------------------------------------------------
    def _evaluate_quality_with_llm(
        self,
        query: str,
        entities: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        relations: List[Dict[str, Any]],
    ) -> float:
        """Path 2/3 전용: 관찰자 LLM이 쿼리와 검색 결과의 관련성을 평가 (0.0~1.0).

        검색 결과가 아예 없으면 0.0을 즉시 반환.
        LLM 호출 실패 시 개수 기반 fallback.
        """
        total_items = len(entities) + len(events)
        if total_items == 0:
            return 0.0

        # 검색 결과 요약 생성 (토큰 절약을 위해 상위 10개만)
        snippets = []
        for e in entities[:10]:
            name = e.get("name", "?")
            etype = e.get("type", "")
            doc = e.get("document_id", "")
            snippets.append(f"[엔티티] {name} ({etype}) doc={doc}")
        for ev in events[:10]:
            title = ev.get("title", "?")
            snippets.append(f"[이벤트] {title}")
        for r in relations[:5]:
            snippets.append(f"[관계] {r.get('relation', '?')} ({r.get('type', '')})")

        context_text = "\n".join(snippets) if snippets else "(검색 결과 없음)"

        endpoint = getattr(self.config, "HOP_CLASSIFIER_SGLANG_ENDPOINT", None)
        if not endpoint:
            logger.warning("관찰자 LLM 엔드포인트 없음 → fallback 0.0")
            return 0.0

        system_prompt = (
            "You are a relevance judge. Given a user query and graph search results, "
            "rate how relevant the search results are to answering the query.\n"
            "Output ONLY a single decimal number between 0.0 and 1.0.\n"
            "0.0 = completely irrelevant, 1.0 = perfectly relevant.\n"
            "Output ONLY the number. No explanation."
        )
        user_prompt = f"Query: {query}\n\nSearch Results:\n{context_text}"

        try:
            resp = requests.post(
                f"{endpoint}/v1/chat/completions",
                json={
                    "model": getattr(self.config, "HOP_CLASSIFIER_MODEL", "default"),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 8,
                    "temperature": 0.0,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                timeout=15,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            text = re.sub(r'<[tT]hink>.*?</[tT]hink>', '', text, flags=re.DOTALL).strip()
            text = re.sub(r'<[tT]hink>.*', '', text, flags=re.DOTALL).strip()
            match = re.search(r'([01]\.?\d*)', text)
            if match:
                score = float(match.group(1))
                score = max(0.0, min(score, 1.0))
                logger.info("관찰자 LLM 품질 평가: query='%s' → %.2f (raw='%s')", query[:40], score, text)
                return score
            logger.warning("관찰자 LLM 파싱 실패: raw='%s' → fallback 0.0", text)
        except Exception as exc:
            logger.warning("관찰자 LLM 호출 실패: %s → fallback 0.0", exc)

        return 0.0

    def _maybe_adjust_edges(self, state: GraphReasonerState) -> None:
        relations = state.get("relations", [])
        if not relations:
            return
        high_density = [rel for rel in relations if rel.get("relation")]
        if len(high_density) > 5:
            pass  # 과밀 엣지 축소 로직 (향후 구현)

    # ------------------------------------------------------------------
    # 워크플로우 실행
    # ------------------------------------------------------------------
    def _run_workflow(self, query: str, allowed_doc_ids: Optional[List[str]] = None) -> GraphReasonerState:
        state = _make_initial_state(query, allowed_doc_ids=allowed_doc_ids)
        if not self.workflow:
            state["plan"] = [
                "질문을 분석하고 향후 LangGraph 워크플로우에 전달",
                "그래프 RAG 통합을 위한 스텁",
            ]
            state["answer_notes"] = ["LangGraph 워크플로우가 아직 구성되지 않았습니다."]
            return state

        try:
            # 체크포인터 사용 시 thread_id 필요
            thread_id = uuid.uuid4().hex
            config = {"configurable": {"thread_id": thread_id}}
            result_state = self.workflow.invoke(state, config=config)
            logger.info("워크플로우 완료 (thread=%s, backtrack=%d)",
                        thread_id, result_state.get("backtrack_count", 0))
            return result_state
        except Exception as exc:
            logger.warning("LangGraph 실행 실패: %s", exc)
            state["answer_notes"] = [f"LangGraph 실행 실패: {exc}"]
            return state

    def _collect_hop(self, state: GraphReasonerState, hop_idx: int, hop_query: str) -> Any:
        doc_ids = state.get("allowed_doc_ids") or None
        entities = self._search_entities(hop_query, allowed_doc_ids=doc_ids)
        events = self._search_events(hop_query, allowed_doc_ids=doc_ids)
        relations = self._search_relations(entities, events, allowed_doc_ids=doc_ids)
        if not (entities or events or relations):
            return False

        existing_entities = list(state.get("entities", []))
        existing_events = list(state.get("events", []))
        existing_relations = list(state.get("relations", []))

        added_entities = self._extend_unique(existing_entities, entities)
        added_events = self._extend_unique(existing_events, events)
        added_relations = self._extend_unique(existing_relations, relations, key_candidates=["id", "uuid", "relation"])

        # state를 직접 mutate (TypedDict는 dict이므로 가능)
        state["entities"] = existing_entities
        state["events"] = existing_events
        state["relations"] = existing_relations

        if self.got_enabled:
            self._maybe_adjust_edges(state)
        return {
            "entities": added_entities,
            "events": added_events,
            "relations": added_relations,
            "query": hop_query,
        }

    def _build_followup_query(self, state: GraphReasonerState, previous_query: str) -> str:
        candidates: List[str] = []
        relations = state.get("relations", [])
        for relation in reversed(relations[-5:]):
            for key in ["source_name", "target_name", "relation", "event_name", "source", "target"]:
                value = relation.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
        for entity in reversed(state.get("entities", [])[-5:]):
            name = entity.get("name") or entity.get("title") or entity.get("label")
            if name and name.strip():
                candidates.append(name.strip())
        for event in reversed(state.get("events", [])[-5:]):
            title = event.get("title") or event.get("name")
            if title and title.strip():
                candidates.append(title.strip())

        unique_candidates: List[str] = []
        seen = set()
        for cand in candidates:
            if cand not in seen:
                seen.add(cand)
                unique_candidates.append(cand)
            if len(unique_candidates) >= 5:
                break

        if not unique_candidates:
            return previous_query

        return " ".join(unique_candidates)

    def _extend_unique(
        self,
        existing: List[Dict[str, Any]],
        new_items: List[Dict[str, Any]],
        key_candidates: Optional[List[str]] = None,
    ) -> int:
        if not new_items:
            return 0
        signatures = {self._object_signature(item, key_candidates) for item in existing}
        added = 0
        for item in new_items:
            sig = self._object_signature(item, key_candidates)
            if sig in signatures:
                continue
            existing.append(item)
            signatures.add(sig)
            added += 1
        return added

    def _object_signature(self, item: Dict[str, Any], key_candidates: Optional[List[str]] = None) -> str:
        if key_candidates:
            for key in key_candidates:
                value = item.get(key)
                if value:
                    return str(value)
        for key in ["id", "uuid", "name", "title", "relation"]:
            value = item.get(key)
            if value:
                return str(value)
        return str(hash(json.dumps(item, sort_keys=True, ensure_ascii=False)))

    # ------------------------------------------------------------------
    # GoT 확장 (백트래킹 포함)
    # ------------------------------------------------------------------
    def _run_got_expansion(self, state: GraphReasonerState) -> GraphReasonerState:
        """GoT 기반 그래프 확장. 실패 시 이전 상태로 백트래킹."""
        max_steps = max(1, getattr(self.config, "GOT_MAX_STEPS", 3))
        candidate_queries = list(state.get("candidate_queries", []))
        visited_queries = set(state.get("visited_queries", set()))
        thought_steps = list(state.get("thought_steps", []))
        query_history = list(state.get("query_history", []))

        if not candidate_queries:
            seeds = self._extract_candidate_queries(state)
            if not seeds:
                seeds = [state.get("query", "")]
            for s in seeds:
                s = s.strip()
                if s and s not in visited_queries and s not in candidate_queries:
                    candidate_queries.append(s)

        # 확장 전 스냅샷 (백트래킹용)
        snapshot_entities = list(state.get("entities", []))
        snapshot_events = list(state.get("events", []))
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 2  # 연속 실패 시 백트래킹

        while candidate_queries and len(thought_steps) < max_steps:
            candidate = candidate_queries.pop(0).strip()
            if not candidate or candidate in visited_queries:
                continue
            visited_queries.add(candidate)
            query_history.append(candidate)
            hop_idx = len(query_history)
            collected = self._collect_hop(state, hop_idx, candidate)
            thought_record = {
                "step": len(thought_steps) + 1,
                "query": candidate,
            }
            if collected:
                thought_record["status"] = "expanded"
                thought_record["summary"] = self._summarize_thought_delta(collected)
                thought_record["delta"] = collected
                consecutive_failures = 0
                new_candidates = self._extract_candidate_queries(state)
                for nc in new_candidates:
                    nc = nc.strip()
                    if nc and nc not in visited_queries and nc not in candidate_queries:
                        candidate_queries.append(nc)
            else:
                thought_record["status"] = "no_results"
                thought_record["summary"] = "그래프 확장에서 새로운 노드를 찾지 못함"
                consecutive_failures += 1

                # 백트래킹: 연속 실패 시 스냅샷으로 복원하고 다른 후보 시도
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    thought_record["backtracked"] = True
                    thought_record["summary"] += f" → 백트래킹 (연속 {consecutive_failures}회 실패)"
                    state["entities"] = list(snapshot_entities)
                    state["events"] = list(snapshot_events)
                    consecutive_failures = 0
                    logger.info("GoT 백트래킹: 연속 실패로 스냅샷 복원")

            thought_steps.append(thought_record)

        # 결과 반영
        state["candidate_queries"] = candidate_queries
        state["visited_queries"] = visited_queries
        state["thought_steps"] = thought_steps
        state["query_history"] = query_history
        state["active_query"] = candidate if candidate_queries else ""
        return state

    def _extract_candidate_queries(self, state: GraphReasonerState, limit: int = 5) -> List[str]:
        candidates: List[str] = []
        for relation in reversed(state.get("relations", [])[-8:]):
            for key in ["source_name", "target_name", "relation", "event_name", "source", "target"]:
                value = relation.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
        for entity in reversed(state.get("entities", [])[-8:]):
            name = entity.get("name") or entity.get("title") or entity.get("label")
            if isinstance(name, str) and name.strip():
                candidates.append(name.strip())
        for event in reversed(state.get("events", [])[-8:]):
            title = event.get("title") or event.get("name")
            if isinstance(title, str) and title.strip():
                candidates.append(title.strip())

        if not candidates:
            candidates.append(state.get("query", ""))

        unique: List[str] = []
        seen = set()
        for cand in candidates:
            cand = cand.strip()
            if not cand or cand in seen:
                continue
            seen.add(cand)
            unique.append(cand)
            if len(unique) >= limit:
                break
        return unique

    def _extend_candidate_queue(self, state: GraphReasonerState, candidates: List[str]) -> None:
        cq = list(state.get("candidate_queries", []))
        vq = state.get("visited_queries", set())
        for cand in candidates:
            if not cand:
                continue
            cand = cand.strip()
            if not cand or cand in vq:
                continue
            if cand not in cq:
                cq.append(cand)
        state["candidate_queries"] = cq

    # ------------------------------------------------------------------
    # 컨텍스트 스니펫 생성
    # ------------------------------------------------------------------
    def _build_context_snippets(self, state: GraphReasonerState) -> List[str]:
        """엔티티/이벤트/관계에서 LLM에 전달할 컨텍스트 스니펫 생성 (중복 제거)"""
        snippets: List[str] = []
        seen: set = set()

        for entity in state.get("entities", []):
            name = entity.get("name", "unknown")
            etype = entity.get("type", "")
            desc = entity.get("description", "")
            snippet = f"[엔티티] {name}"
            if etype:
                snippet += f" ({etype})"
            if desc:
                snippet += f": {desc}"
            if snippet not in seen:
                seen.add(snippet)
                snippets.append(snippet)

        for event in state.get("events", []):
            title = event.get("title", "unknown")
            desc = event.get("description", "")
            snippet = f"[이벤트] {title}"
            if desc:
                snippet += f": {desc}"
            if snippet not in seen:
                seen.add(snippet)
                snippets.append(snippet)

        for relation in state.get("relations", []):
            src = relation.get("source_name", relation.get("source", "?"))
            tgt = relation.get("target_name", relation.get("target", "?"))
            rel_type = relation.get("relation", "관련")
            snippet = f"[관계] {src} --[{rel_type}]--> {tgt}"
            if snippet not in seen:
                seen.add(snippet)
                snippets.append(snippet)

        return snippets

    @staticmethod
    def _summarize_thought_delta(delta: Dict[str, Any]) -> str:
        ent = delta.get("entities", 0)
        eve = delta.get("events", 0)
        rel = delta.get("relations", 0)
        return f"엔티티 +{ent}, 이벤트 +{eve}, 관계 +{rel}"


__all__ = ["GraphReasoner", "GraphReasonerState"]
