#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GraphReasoner State 정의."""
from __future__ import annotations

import operator
from typing import Any, Annotated, List, Optional, TypedDict


class GraphReasonerState(TypedDict, total=False):
    """LangGraph 워크플로우 상태."""
    query: str
    plan: Annotated[list, operator.add]
    hops: Annotated[list, operator.add]
    answer_notes: Annotated[list, operator.add]
    entities: list              # 배타적 실행: 각 Path가 덮어씀
    events: list                # 배타적 실행: 각 Path가 덮어씀
    relations: list             # 배타적 실행: 각 Path가 덮어씀
    context_snippets: list
    max_hops: int
    retrieval_path: str         # "vector" | "cross_ref" | "graph_db"
    retrieval_quality: float
    backtrack_count: int
    tried_paths: list
    allowed_doc_ids: Optional[List[str]]
    state_checkpoint_id: str
    query_history: list
    thought_steps: Annotated[list, operator.add]
    
    # Tool Calling 관련
    dispatch_target: str        # "rag" | "tool"
    selected_tool: str
    tool_inputs: dict
    tool_result: Any


def make_initial_state(
    query: str,
    allowed_document_uuids: Optional[set] = None,
) -> GraphReasonerState:
    """초기 상태 생성."""
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
        retrieval_path="vector",
        retrieval_quality=0.0,
        backtrack_count=0,
        tried_paths=[],
        allowed_doc_ids=list(allowed_document_uuids) if allowed_document_uuids else None,
        state_checkpoint_id="",
        query_history=[],
        thought_steps=[],
        dispatch_target="rag",
        selected_tool="",
        tool_inputs={},
        tool_result=None,
    )
