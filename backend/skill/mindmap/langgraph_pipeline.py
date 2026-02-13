#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LangGraph 기반 Mindmap 생성 파이프라인."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:  # LangGraph는 선택적 의존성
    from langgraph.graph import StateGraph, END  # type: ignore
    from langgraph.checkpoint.memory import MemorySaver  # type: ignore
except Exception:  # pragma: no cover
    StateGraph = END = MemorySaver = None  # type: ignore

from .mindmap_generator import MindMapGenerationError
from .mindmap_generator import generate_mindmap_for_api

logger = logging.getLogger(__name__)


@dataclass
class MindmapWorkflowState:
    document_content: str
    request_id: Optional[str]
    max_topics: int
    plan: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    generation_result: Dict[str, Any] = field(default_factory=dict)


class LangGraphMindmapPipeline:
    """Mindmap 생성을 LangGraph StateGraph로 감싼 스켈레톤."""

    def __init__(self) -> None:
        self.checkpointer = MemorySaver() if MemorySaver else None
        if StateGraph is None:
            logger.warning("LangGraph가 설치되지 않아 Mindmap 워크플로우를 비활성화합니다.")
            self.workflow = None
        else:
            self.workflow = self._build_workflow()

    def _build_workflow(self):
        graph = StateGraph(MindmapWorkflowState)

        def planner(state: MindmapWorkflowState) -> MindmapWorkflowState:
            if not state.plan:
                state.plan.extend(
                    [
                        "문서 내용을 적재하고 요청 ID 확정",
                        "MindMapGenerator를 호출해 NotebookLM 스타일 Mindmap 생성",
                        "Mermaid/HTML/Markdown 산출물 패키징",
                    ]
                )
            return state

        def generator_node(state: MindmapWorkflowState) -> MindmapWorkflowState:
            try:
                result = asyncio.run(
                    generate_mindmap_for_api(
                        document_content=state.document_content,
                        request_id=state.request_id or "mindmap_request",
                        max_topics=state.max_topics,
                    )
                )
                state.generation_result = result
                state.notes.append("Mindmap 생성 완료")
            except MindMapGenerationError as exc:
                logger.error("Mindmap 생성 실패: %s", exc)
                state.notes.append(f"Mindmap 생성 실패: {exc}")
            except Exception as exc:  # pragma: no cover - 예외 진단용
                logger.exception("예상치 못한 Mindmap 오류")
                state.notes.append(f"예상치 못한 오류: {exc}")
            return state

        def finalizer(state: MindmapWorkflowState) -> MindmapWorkflowState:
            result = state.generation_result
            if not result:
                return state
            result.setdefault("notes", []).extend(state.notes)
            result.setdefault("plan", list(state.plan))
            state.generation_result = result
            return state

        graph.add_node("planner", planner)
        graph.add_node("generator", generator_node)
        graph.add_node("finalizer", finalizer)
        graph.add_edge("planner", "generator")
        graph.add_edge("generator", "finalizer")
        graph.add_edge("finalizer", END)
        graph.set_entry_point("planner")
        compiled = graph.compile(checkpointer=self.checkpointer) if self.checkpointer else graph.compile()
        logger.info("Mindmap 워크플로우 초기화 완료 (체크포인터: %s)", "MemorySaver" if self.checkpointer else "없음")
        return compiled

    def run(
        self,
        document_content: str,
        request_id: Optional[str] = None,
        max_topics: int = 8,
    ) -> Dict[str, Any]:
        if not self.workflow:
            raise RuntimeError("LangGraph Mindmap 워크플로우가 초기화되지 않았습니다.")
        state = MindmapWorkflowState(
            document_content=document_content,
            request_id=request_id,
            max_topics=max_topics,
        )
        result_state = self.workflow.invoke(state)
        return result_state.generation_result
