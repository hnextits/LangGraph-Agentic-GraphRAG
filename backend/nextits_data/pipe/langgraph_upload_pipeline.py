#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LangGraph 기반 업로드/인덱싱 파이프라인 (Vector-Graph Hybrid 연결 적용)"""
from __future__ import annotations

import logging
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from langgraph.graph import StateGraph, END  # type: ignore
    from langgraph.checkpoint.memory import MemorySaver  # type: ignore
except Exception:
    StateGraph = END = MemorySaver = None  # type: ignore

from notebooklm.config import RAGConfig
from notebooklm.embedding_text import process_markdown_files
from notebooklm.graph_schema import GraphSchemaManager
from notebooklm.legacy_graph_ingestor import LegacyGraphIngestor
from notebooklm.shared_embedding import shared_embedding

from .neo4j_manager import Neo4jManager

from .llm_metadata_extractor import LLMMetadataExtractor
from .run_file_processor import (
    process_file,
    run_layout_detection,
    run_ocr_processing,
    run_image_pipeline,
)

logger = logging.getLogger(__name__)

@dataclass
class UploadWorkflowState:
    file_names: List[str]
    session_id: Optional[str]
    plan: List[str] = field(default_factory=list)
    processed_files: List[str] = field(default_factory=list)
    metadata_files: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    raw_files: List[Path] = field(default_factory=list)
    doc_dir: Optional[Path] = None
    results_base: Optional[Path] = None

class LangGraphUploadPipeline:
    """OCR 이후 텍스트 인덱싱 전 과정을 LangGraph로 감싸는 파이프라인."""

    def __init__(self, config: Optional[RAGConfig] = None) -> None:
        self.config = config or RAGConfig()
        self.checkpointer = MemorySaver() if MemorySaver else None
        if StateGraph is None:
            logger.warning("LangGraph 패키지를 찾을 수 없어 업로드 워크플로우를 비활성화합니다.")
            self.workflow = None
        else:
            self.workflow = self._build_workflow()
        self.metadata_extractor = LLMMetadataExtractor(config=self.config)
        self.graph_manager = GraphSchemaManager(self.config)
        self.legacy_ingestor = self._init_legacy_ingestor()

    def _build_workflow(self):
        graph = StateGraph(UploadWorkflowState)

        # 1. 플래너: 작업 순서 정의
        def planner(state: UploadWorkflowState) -> UploadWorkflowState:
            if not state.plan:
                state.plan.extend([
                    "파일 경로 확인", "OCR 처리", "벡터 인덱싱(UUID 생성)", "그래프 추출 및 연결"
                ])
            return state

        # 2. 준비: 경로 해소
        def prepare_node(state: UploadWorkflowState) -> UploadWorkflowState:
            doc_dir = state.doc_dir or self._resolve_doc_dir(state.session_id)
            results_base = state.results_base or self._resolve_results_base(state.session_id)
            state.doc_dir, state.results_base = doc_dir, results_base
            
            raw_files = []
            for name in state.file_names:
                candidate = Path(name)
                if not candidate.is_absolute() and doc_dir:
                    candidate = doc_dir / name
                if candidate.exists():
                    raw_files.append(candidate)
            state.raw_files = raw_files
            return state

        # 3. 변환/레이아웃/OCR (단순화하여 연결)
        def conversion_node(state: UploadWorkflowState) -> UploadWorkflowState:
            if not state.raw_files: return state
            for raw_file in state.raw_files:
                process_file(str(raw_file), skip_existing=True, resume=True, results_base=state.results_base)
            return state

        def layout_node(state: UploadWorkflowState) -> UploadWorkflowState:
            input_dir = state.results_base / "1.Converted_images"
            output_dir = state.results_base / "2.LayoutDetection"
            if input_dir.exists():
                run_layout_detection(input_dir, output_dir, skip_existing=True, resume=True)
            return state

        def ocr_node(state: UploadWorkflowState) -> UploadWorkflowState:
            input_dir = state.results_base / "1.Converted_images"
            ocr_dir = state.results_base / "4.OCR_results"
            success = run_ocr_processing(image_source_dir=input_dir, output_dir=ocr_dir, skip_existing=True, resume=True)
            if success: run_image_pipeline(results_base=state.results_base)
            return state

        def collector(state: UploadWorkflowState) -> UploadWorkflowState:
            state.processed_files = self._collect_processed_files(state)
            return state

        # 핵심 연동 노드
        def chunk_node(state: UploadWorkflowState) -> UploadWorkflowState:
            return self._run_chunk_stage(state)

        def metadata_node(state: UploadWorkflowState) -> UploadWorkflowState:
            return self._run_metadata_stage(state)

        def finalizer(state: UploadWorkflowState) -> UploadWorkflowState:
            logger.info(">>> [Pipeline] 모든 작업 완료")
            return state

        # 그래프 구조 정의
        graph.add_node("planner", planner)
        graph.add_node("prepare", prepare_node)
        graph.add_node("conversion", conversion_node)
        graph.add_node("layout", layout_node)
        graph.add_node("ocr", ocr_node)
        graph.add_node("collector", collector)
        graph.add_node("chunk", chunk_node)
        graph.add_node("metadata", metadata_node)
        graph.add_node("finalizer", finalizer)

        graph.add_edge("planner", "prepare")
        graph.add_edge("prepare", "conversion")
        graph.add_edge("conversion", "layout")
        graph.add_edge("layout", "ocr")
        graph.add_edge("ocr", "collector")
        graph.add_edge("collector", "chunk")
        graph.add_edge("chunk", "metadata")
        graph.add_edge("metadata", "finalizer")
        graph.add_edge("finalizer", END)

        graph.set_entry_point("planner")
        compiled = graph.compile(checkpointer=self.checkpointer) if self.checkpointer else graph.compile()
        logger.info("업로드 파이프라인 워크플로우 초기화 완료 (체크포인터: %s)", "MemorySaver" if self.checkpointer else "없음")
        return compiled

    def _run_chunk_stage(self, state: UploadWorkflowState) -> UploadWorkflowState:
        """벡터 DB 인덱싱 및 UUID 확정 단계"""
        if not state.processed_files:
            return state
        try:
            if not shared_embedding.is_loaded:
                shared_embedding.load_model()
            
            client = self.config.get_weaviate_client()
            try:
                # Weaviate에 Markdown 데이터 주입
                process_markdown_files(client, state.processed_files, session_id=state.session_id)
                state.notes.append("Vector Indexing 완료")
            finally:
                client.close()
        except Exception as exc:
            logger.error(f"Vector Indexing 에러: {exc}")
        return state

    def _run_metadata_stage(self, state: UploadWorkflowState) -> UploadWorkflowState:
        """Neo4j 그래프 추출 및 Vector-Graph 연결 단계 (강력한 디버깅 포함)"""
        print("\n" + "!"*60)
        print(">>> [NEO4J STEP START] 그래프 인덱싱 프로세스 진입")
        print(f">>> 처리 대상 파일: {state.processed_files}")
        print("!"*60 + "\n")

        if not state.processed_files:
            logger.warning("처리할 OCR 파일이 없어 그래프 단계를 종료합니다.")
            return state

        # 1. Weaviate UUID 조회 (연결 고리 확인)
        doc_uuid_map = {}
        try:
            client = self.config.get_weaviate_client()
            text_coll = client.collections.get("TextDocument")
            from weaviate.classes.query import Filter
            for proc_file in state.processed_files:
                doc_path = Path(proc_file)
                resp = text_coll.query.fetch_objects(
                    filters=Filter.by_property("source").like(f"*{doc_path.name}*"),
                    limit=1
                )
                if resp.objects:
                    doc_uuid_map[doc_path.stem] = str(resp.objects[0].uuid)
                    print(f"DEBUG: Found Vector UUID {resp.objects[0].uuid} for {doc_path.name}")
            client.close()
        except Exception as e:
            print(f"CRITICAL: Weaviate UUID 조회 실패: {e}")

        # 2. LLM 추출 테스트
        saved_paths = []
        for processed in state.processed_files:
            try:
                print(f"DEBUG: LLM 추출 시작 (대상: {Path(processed).name})...")
                # 이 부분이 오래 걸리거나 여기서 에러가 날 확률이 높습니다.
                _, saved_path = self.metadata_extractor.extract_from_markdown(
                    Path(processed), session_id=state.session_id
                )
                if saved_path and Path(saved_path).exists():
                    print(f"DEBUG: LLM 추출 성공! JSON 경로: {saved_path}")
                    saved_paths.append(str(saved_path))
                else:
                    print(f"ERROR: {Path(processed).name} 에 대한 JSON 결과 파일이 생성되지 않았습니다.")
            except Exception as e:
                print(f"CRITICAL: LLM 추출 도중 에러 발생: {e}")

        # 3. Neo4j 주입 테스트
        if saved_paths:
            try:
                print(f"DEBUG: Neo4j 주입 시도 (파일 수: {len(saved_paths)})...")
                # graph_manager의 Neo4j 접속 정보가 127.0.0.1와 일치하는지 확인 필수
                self.graph_manager.ingest_metadata_dir(
                    self.metadata_extractor.output_dir,
                    doc_uuid_map=doc_uuid_map
                )
                state.metadata_files = saved_paths
                print(">>> [SUCCESS] Neo4j 데이터 주입 완료!")

                # Neo4j GraphDB 업서트 (Bolt)
                self._ingest_neo4j(state.metadata_files)
            except Exception as e:
                print(f"CRITICAL: Neo4j 주입 중 실패: {e}")
        else:
            print("WARNING: 주입할 그래프 데이터(JSON)가 없어 Neo4j 작업을 건너뜁니다.")
        
        return state

    # --- 헬퍼 메서드 ---
    def _init_legacy_ingestor(self) -> Optional[LegacyGraphIngestor]:
        if not getattr(self.config, "LEGACY_GRAPH_ENABLED", False): return None
        try: return LegacyGraphIngestor(self.config)
        except: return None

    def _ingest_legacy_graph(self, metadata_paths: List[str], state: UploadWorkflowState) -> None:
        for path in metadata_paths:
            try: self.legacy_ingestor.ingest_metadata_file(Path(path))
            except: pass

    def _ingest_neo4j(self, metadata_paths: List[str]) -> None:
        if not metadata_paths:
            return
        try:
            manager = Neo4jManager()
        except Exception as exc:
            logger.error(f"Neo4jManager 초기화 실패: {exc}")
            return

        try:
            for path in metadata_paths:
                try:
                    data = json.loads(Path(path).read_text(encoding="utf-8"))
                    manager.upsert_graph(data)
                    logger.info(f"Neo4j 업서트 성공: {Path(path).name}")
                except Exception as file_exc:
                    logger.error(f"Neo4j 업서트 실패 ({path}): {file_exc}")
        finally:
            manager.close()

    def run(self, file_names: List[str], session_id: Optional[str] = None) -> UploadWorkflowState:
        if not self.workflow: raise RuntimeError("LangGraph 초기화 실패")
        state = UploadWorkflowState(file_names=file_names, session_id=session_id)
        return self.workflow.invoke(state)

    def _collect_processed_files(self, state: UploadWorkflowState) -> List[str]:
        ocr_dir = state.results_base / "4.OCR_results" if state.results_base else self.config.DATA_ROOT / "Results" / "4.OCR_results"
        files = []
        for f in state.file_names:
            candidate = ocr_dir / f"{Path(f).stem}.md"
            if candidate.exists(): files.append(str(candidate))
        return files

    def _resolve_doc_dir(self, session_id: Optional[str]) -> Path:
        return self.config.get_session_doc_dir(session_id) if session_id else self.config.DEFAULT_DOC_DIR

    def _resolve_results_base(self, session_id: Optional[str]) -> Path:
        base = self.config.DATA_ROOT / "sessions" / session_id / "Results" if session_id else self.config.DATA_ROOT / "Results"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def run_post_ocr_pipeline(self, file_names: List[str], session_id: Optional[str] = None) -> UploadWorkflowState:
        """
        OCR이 완료된 후, 텍스트 인덱싱(Vector)과 그래프 추출(Neo4j)만 별도로 실행하는 진입점.
        api/routes.py에서 호출됩니다.
        """
        logger.info(f">>> [Post-OCR] 텍스트 및 그래프 인덱싱 시작 (Session: {session_id})")
        
        doc_dir = self._resolve_doc_dir(session_id)
        results_base = self._resolve_results_base(session_id)
        
        # 1. 초기 상태 설정
        state = UploadWorkflowState(
            file_names=file_names,
            session_id=session_id,
            doc_dir=doc_dir,
            results_base=results_base,
        )
        
        # 2. OCR 결과 파일(.md) 수집
        state.processed_files = self._collect_processed_files(state)
        
        if not state.processed_files:
            logger.error(">>> [Post-OCR] 처리할 OCR 결과 파일이 없습니다.")
            return state

        # 3. 순차적 실행: Vector Indexing (Weaviate) -> Metadata Indexing (Neo4j)
        # 중요: 반드시 chunk_stage를 먼저 실행하여 UUID를 생성해야 합니다.
        state = self._run_chunk_stage(state)
        state = self._run_metadata_stage(state)
        
        # 4. 결과 요약 업데이트
        state.context.update({
            "processed_files": len(state.processed_files),
            "graph_files": len(state.metadata_files)
        })
        
        logger.info(">>> [Post-OCR] 파이프라인 최종 완료")
        return state