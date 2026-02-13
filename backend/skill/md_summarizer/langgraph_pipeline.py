#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LangGraph 기반 Markdown Summarizer 파이프라인."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # LangGraph는 선택적 의존성
    from langgraph.graph import StateGraph, END  # type: ignore
    from langgraph.checkpoint.memory import MemorySaver  # type: ignore
except Exception:  # pragma: no cover
    StateGraph = END = MemorySaver = None  # type: ignore

from .sglang_client import SGLangClient

logger = logging.getLogger(__name__)


@dataclass
class SummarizerWorkflowState:
    file_paths: List[str]
    request_id: Optional[str]
    plan: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    documents: List[Dict[str, str]] = field(default_factory=list)
    summaries: List[Dict[str, str]] = field(default_factory=list)
    result: Dict[str, Any] = field(default_factory=dict)


class LangGraphSummarizerPipeline:
    """파일 요약을 LangGraph 노드로 감싸는 스켈레톤."""

    def __init__(self, sglang_endpoints: Optional[List[str]] = None) -> None:
        self.client = SGLangClient(sglang_endpoints)
        self.checkpointer = MemorySaver() if MemorySaver else None
        if StateGraph is None:
            logger.warning("LangGraph 패키지를 찾을 수 없어 Summarizer 워크플로우를 비활성화합니다.")
            self.workflow = None
        else:
            self.workflow = self._build_workflow()

    # ------------------------------------------------------------------
    def _build_workflow(self):
        graph = StateGraph(SummarizerWorkflowState)

        def planner(state: SummarizerWorkflowState) -> SummarizerWorkflowState:
            if not state.plan:
                state.plan.extend(
                    [
                        "요약 대상 파일 경로 검증 및 로드",
                        "각 파일을 SGLang Summarizer로 요약",
                        "결과를 Markdown/노트와 함께 패키징",
                    ]
                )
            return state

        def loader(state: SummarizerWorkflowState) -> SummarizerWorkflowState:
            documents: List[Dict[str, str]] = []
            missing: List[str] = []
            for raw_path in state.file_paths:
                path = Path(raw_path)
                if not path.exists():
                    missing.append(str(path))
                    continue
                try:
                    content = path.read_text(encoding="utf-8")
                    documents.append({"title": path.name, "content": content})
                except Exception as exc:
                    logger.warning("파일 읽기 실패 (%s): %s", path, exc)
                    missing.append(f"{path} (읽기 실패)")
            state.documents = documents
            if missing:
                state.notes.append(f"읽지 못한 파일 {len(missing)}건: {missing[:3]}...")
            if not documents:
                state.notes.append("요약할 문서를 찾지 못했습니다.")
            return state

        def summarizer_node(state: SummarizerWorkflowState) -> SummarizerWorkflowState:
            if not state.documents:
                return state
            summaries: List[Dict[str, str]] = []
            for doc in state.documents:
                try:
                    summary = self.client.generate_answer(doc["content"])
                    summaries.append({"title": doc["title"], "summary": summary})
                    state.notes.append(f"요약 완료: {doc['title']}")
                except Exception as exc:
                    logger.error("%s 요약 실패: %s", doc["title"], exc)
                    state.notes.append(f"요약 실패: {doc['title']} -> {exc}")
            state.summaries = summaries
            return state

        def finalizer(state: SummarizerWorkflowState) -> SummarizerWorkflowState:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if not state.summaries:
                state.result = {
                    "summary": "",
                    "files": state.file_paths,
                    "timestamp": timestamp,
                    "notes": state.notes,
                    "plan": state.plan,
                }
                return state

            merged = []
            for item in state.summaries:
                merged.append(f"## {item['title']}\n\n{item['summary'].strip()}")
            final_text = "\n\n---\n\n".join(merged)
            state.result = {
                "summary": final_text,
                "files": [doc["title"] for doc in state.documents],
                "timestamp": timestamp,
                "notes": state.notes,
                "plan": state.plan,
            }
            return state

        graph.add_node("planner", planner)
        graph.add_node("loader", loader)
        graph.add_node("summarizer", summarizer_node)
        graph.add_node("finalizer", finalizer)
        graph.add_edge("planner", "loader")
        graph.add_edge("loader", "summarizer")
        graph.add_edge("summarizer", "finalizer")
        graph.add_edge("finalizer", END)
        graph.set_entry_point("planner")
        compiled = graph.compile(checkpointer=self.checkpointer) if self.checkpointer else graph.compile()
        logger.info("Summarizer 워크플로우 초기화 완료 (체크포인터: %s)", "MemorySaver" if self.checkpointer else "없음")
        return compiled

    # ------------------------------------------------------------------
    def run(
        self,
        file_paths: List[str],
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.workflow:
            raise RuntimeError("LangGraph Summarizer 워크플로우가 초기화되지 않았습니다.")
        state = SummarizerWorkflowState(file_paths=file_paths, request_id=request_id)
        result_state = self.workflow.invoke(state)
        return result_state.result
