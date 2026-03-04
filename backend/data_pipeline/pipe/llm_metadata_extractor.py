#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import json
import logging
import re
import shutil
import textwrap
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.data_pipeline.pipe.bootstrap import ensure_backend_root, configure_logging

ensure_backend_root()
configure_logging()

import requests

try:
    from notebooklm.config import RAGConfig
except ImportError:
    RAGConfig = None

logger = logging.getLogger(__name__)

# 엔티티/관계 후처리용 상수
ANALOGY_KEYWORDS = {
    "cake", "butter", "flour", "sugar", "milk", "vanilla", "egg", "eggs",
    "baking powder", "oven", "pan", "toothpick", "frosting", "recipe",
    "batter", "ingredient", "kitchen", "bake"
}
NON_TECH_TYPES = {
    "material", "ingredient", "object", "tool", "equipment", "recipe"
}
GENERIC_RELATIONS = {
    "relates to", "relatesto", "depends on", "dependson"
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def _is_analogy_entity(name: str, etype: str) -> bool:
    norm_name = _normalize_text(name)
    norm_type = _normalize_text(etype)
    if norm_type in NON_TECH_TYPES:
        return True
    return any(keyword in norm_name for keyword in ANALOGY_KEYWORDS)


def _normalize_relation(desc: str) -> str:
    return re.sub(r"\s+", " ", desc.strip()).lower()

@dataclass
class ExtractionResult:
    document_id: str
    entities: List[Dict] = field(default_factory=list)
    events: List[Dict] = field(default_factory=list)
    relations: List[Dict] = field(default_factory=list)

_sglang_session = requests.Session()

def _get_sglang_endpoint(config) -> str:
    """SGLang 생성기 서버 엔드포인트를 반환합니다."""
    if config and hasattr(config, 'SGLANG_GENERATOR_ENDPOINT'):
        return config.SGLANG_GENERATOR_ENDPOINT
    return "http://localhost:30000"

def _get_model_name(config, model_name: str = None) -> str:
    """모델 이름을 반환합니다."""
    if model_name:
        return model_name
    if config and hasattr(config, 'GRAPH_EXTRACTOR_MODEL'):
        return config.GRAPH_EXTRACTOR_MODEL
    return 'Qwen/Qwen3-8B'

def get_runtime(model_name: str, mem_fraction: float):
    """하위 호환성 유지 - SGLang 서버 엔드포인트를 반환합니다. 미기동 시 자동 기동."""
    endpoint = "http://localhost:30000"
    logger.info(f"==> SGLang 서버 사용: {endpoint} (모델: {model_name})")

    # 서버가 꺼져있으면 자동 기동 시도
    from notebooklm.sglang_server_manager import sglang_manager
    try:
        resp = _sglang_session.get(f"{endpoint}/health", timeout=5)
        if resp.status_code == 200:
            sglang_manager.touch("generator")
            return endpoint
    except Exception:
        pass

    logger.info("==> generator 서버 미기동 → acquire로 자동 기동 시도")
    try:
        if sglang_manager.acquire("generator"):
            sglang_manager.release("generator")
    except Exception as e:
        logger.error("==> generator 자동 기동 실패: %s", e)

    return endpoint

def shutdown_runtime():
    """하위 호환성 유지 - 서버는 main.py에서 관리합니다."""
    logger.info("==> SGLang 서버는 main.py에서 관리됩니다. shutdown_runtime() 호출 무시.")

def _resolve_output_dir(*, config: Optional[Any], session_id: Optional[str]) -> Path:
    if config and session_id and hasattr(config, "get_session_results_dir"):
        return Path(config.get_session_results_dir(session_id, "8.graph_metadata"))
    if config and hasattr(config, "GRAPH_METADATA_DIR"):
        return Path(config.GRAPH_METADATA_DIR)
    fallback = Path(__file__).resolve().parent.parent / "Results" / "graph_metadata"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

def process_document(
    md_path: str | Path,
    *,
    session_id: Optional[str] = None,
    config: Optional[Any] = None,
    model_name: Optional[str] = None,
) -> tuple[ExtractionResult, Optional[Path]]:
    md_path = Path(md_path)
    if not md_path.exists():
        logger.warning("Markdown 파일을 찾을 수 없습니다: %s", md_path)
        return ExtractionResult(document_id=md_path.stem), None

    if config is None and RAGConfig:
        config = RAGConfig()

    # config에서 모델명/mem_fraction 가져오기 (하드코딩 제거)
    if not model_name:
        model_name = getattr(config, 'GRAPH_EXTRACTOR_MODEL', 'Qwen/Qwen3-8B') if config else 'Qwen/Qwen3-8B'
    mem_fraction = getattr(config, 'GRAPH_EXTRACTOR_MEM_FRACTION', 0.3) if config else 0.3
    endpoint = get_runtime(model_name, mem_fraction)
    content = md_path.read_text(encoding="utf-8")
    doc_id = md_path.stem

    # Chunking
    chunk_size = getattr(config, 'GRAPH_EXTRACTOR_CHUNK_SIZE', 800) if config else 800
    chunks = textwrap.wrap(content, chunk_size, break_long_words=False, replace_whitespace=False)

    result = ExtractionResult(document_id=doc_id)
    entity_seen: set[tuple[str, str]] = set()
    relation_seen: set[tuple[str, str, str]] = set()
    out_dir = _resolve_output_dir(config=config, session_id=session_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{doc_id}.graph.json"

    logger.info(f"==> [Graph Extraction] 시작: {doc_id} ({len(chunks)} chunks)")

    # [수정] 정규식 패턴 보강: 행 시작(^) 제한을 없애고 유연하게 매칭
    entity_pattern = re.compile(r"(ENT_\d+)\s*\|\s*([^|]+)\|\s*([^|\n]+)")
    relation_pattern = re.compile(r"(ENT_\d+)\s*->\s*(ENT_\d+)\s*\(([^)]+)\)")

    from notebooklm.sglang_server_manager import sglang_manager
    keepalive_interval = getattr(config, 'SGLANG_KEEPALIVE_INTERVAL', 20) if config else 20

    # 전체 청크 루프를 acquire로 감싸서 루프 실행 중 서버가 종료되지 않도록 보호
    sglang_manager.acquire("generator")
    try:
     for i, text in enumerate(chunks, 1):
        prompt = f"""<|im_start|>system
You are a knowledge graph extraction assistant. Output ONLY structured entity/relation lines. No explanations, no thinking, no JSON. /no_think
<|im_end|>
<|im_start|>user
Extract all named technical entities and their relationships from the following text.

Text:
{text}

Output rules:
1. Each entity: ENT_N | ActualEntityName | EntityType  (e.g. ENT_1 | RLHF | Algorithm)
2. Each relation: ENT_N -> ENT_M (description)  (e.g. ENT_1 -> ENT_2 (optimizes))
3. Number entities sequentially from ENT_1.
4. Do NOT output the word "Name" or "Type" as entity values.
5. If nothing to extract, output exactly: NONE
<|im_end|>
<|im_start|>assistant
"""

        try:
            temperature = getattr(config, 'GRAPH_EXTRACTOR_TEMPERATURE', 0.1) if config else 0.1
            max_tokens = getattr(config, 'GRAPH_EXTRACTOR_MAX_TOKENS', 1024) if config else 1024
            api_timeout = getattr(config, 'GRAPH_EXTRACTOR_API_TIMEOUT', 300) if config else 300
            retry_on_failure = getattr(config, 'GRAPH_EXTRACTOR_RETRY_ON_FAILURE', True) if config else True
            api_url = f"{endpoint}/v1/completions"

            def _call_sglang(prompt_text, timeout_sec):
                """SGLang API 호출 + keepalive 스레드. timeout 시 abort 후 ReadTimeout 발생."""
                import uuid as _uuid
                req_id = f"extractor-{_uuid.uuid4().hex}"
                payload = {
                    "model": model_name,
                    "prompt": prompt_text,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "request_id": req_id,
                }
                _stop_ka = threading.Event()
                def _keepalive(chunk_idx=i):
                    while not _stop_ka.wait(timeout=keepalive_interval):
                        sglang_manager.touch("generator")
                        logger.debug("SGLang generator keepalive touch (chunk %d)", chunk_idx)
                _ka = threading.Thread(target=_keepalive, daemon=True)
                _ka.start()
                try:
                    r = _sglang_session.post(api_url, json=payload, timeout=timeout_sec)
                    r.raise_for_status()
                    return r
                except Exception as exc:
                    # timeout 발생 시 SGLang에 abort 요청
                    try:
                        _sglang_session.post(
                            f"{endpoint}/abort",
                            json={"rid": req_id},
                            timeout=5,
                        )
                        logger.warning("Chunk %d: SGLang request aborted (rid=%s)", i, req_id)
                    except Exception:
                        pass
                    raise exc
                finally:
                    _stop_ka.set()
                    _ka.join(timeout=2)

            def _restart_generator(reason: Exception | None = None):
                msg = f"Chunk {i}: SGLang generator 재시작 (reason={reason})"
                logger.warning(msg)
                try:
                    sglang_manager.release("generator")
                except Exception as release_exc:
                    logger.error("Chunk %d: generator release 실패: %s", i, release_exc)
                try:
                    sglang_manager.shutdown_server("generator")
                except Exception as shutdown_exc:
                    logger.error("Chunk %d: generator shutdown 실패: %s", i, shutdown_exc)
                finally:
                    # 재기동 시도 (active_users 균형 유지를 위해 acquire 재호출)
                    try:
                        sglang_manager.acquire("generator")
                    except Exception as acquire_exc:
                        logger.error("Chunk %d: generator 재기동 실패: %s", i, acquire_exc)

            resp = None
            attempt = 0
            while True:
                attempt += 1
                try:
                    resp = _call_sglang(prompt, api_timeout)
                    break
                except Exception as exc:
                    logger.error("Chunk %d: SGLang 호출 실패 (attempt %d) - %s", i, attempt, exc)
                    _restart_generator(exc)
                    if not retry_on_failure or attempt >= 2:
                        logger.error("Chunk %d: 재시도 불가 또는 모두 실패, 다음 청크로 이동", i)
                        resp = None
                        break
                    logger.info("Chunk %d: generator 재시작 후 동일 청크 재시도", i)

            if resp is None:
                continue

            data = resp.json()
            output = data["choices"][0]["text"]
            output = output.strip()
            
            # 후처리 2: <think>...</think> 태그 제거
            if "</think>" in output:
                output = output.split("</think>", 1)[-1].strip()
            
            # 후처리 3: thinking 모드 자연어 프리앰블 제거 ("Okay, let's..." 등)
            # ENT_ 패턴이 있는 첫 줄 이전의 비구조화 텍스트를 제거
            output_lines = output.split('\n')
            first_ent_idx = None
            for idx, ln in enumerate(output_lines):
                if re.search(r'ENT_\d+\s*\|', ln) or re.search(r'ENT_\d+\s*->', ln):
                    first_ent_idx = idx
                    break
            if first_ent_idx is not None and first_ent_idx > 0:
                output = '\n'.join(output_lines[first_ent_idx:])

            # 후처리 4: "ENT_x" 앞에 줄바꿈 강제 삽입 (한 줄에 여러 항목이 붙어있는 경우)
            output = re.sub(r'(?<![\n\r])(?=ENT_\d+\s*\|)', '\n', output)
            output = re.sub(r'(?<![\n\r])(?=ENT_\d+\s*->)', '\n', output)
            output = re.sub(r'\n{2,}', '\n', output).strip()
            
            # 디버깅용 로그
            logger.info(f"Chunk {i} Cleaned Output (first 500 chars): {output[:500]}")

            chunk_entities = {}
            lines = output.split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.upper() in {"NONE"}:
                    continue
                if line.startswith('[') or line.lower().startswith(('here is', 'output', 'answer', 'extract', 'okay', 'let me')):
                    continue
                if not line: continue

                # 1. Entity 파싱: search를 사용하여 유연하게 찾음
                ent_match = entity_pattern.search(line)
                if ent_match:
                    raw_id = ent_match.group(1).strip()
                    name = ent_match.group(2).strip()
                    etype = ent_match.group(3).strip()
                    if '\n' in etype:
                        etype = etype.split('\n', 1)[0].strip()
                    if '(' in etype:
                        etype = etype.split('(', 1)[0].strip()
                    
                    # 지시문 키워드 및 플레이스홀더 필터링
                    if name.lower().strip() in ["name", "type", "relationship", "example",
                                          "entityname", "entitytype", "actualentityname",
                                          "relationshipdescription", "description",
                                          "...", "none", "n/a"]: 
                        continue
                    if _is_analogy_entity(name, etype):
                        continue
                    norm_key = (_normalize_text(name), _normalize_text(etype))
                    if norm_key in entity_seen:
                        chunk_entities[raw_id] = next_id = f"c{i}_{raw_id}"
                        continue
                    
                    global_id = f"c{i}_{raw_id}"
                    result.entities.append({
                        "entity_id": global_id,
                        "name": name, 
                        "type": etype, 
                        "chunk_id": i
                    })
                    entity_seen.add(norm_key)
                    chunk_entities[raw_id] = global_id

                # 2. Relation 파싱
                rel_match = relation_pattern.search(line)
                if rel_match:
                    src_id = rel_match.group(1).strip()
                    tgt_id = rel_match.group(2).strip()
                    rel_desc = rel_match.group(3).strip()
                    norm_rel = _normalize_relation(rel_desc)
                    if norm_rel in GENERIC_RELATIONS:
                        continue

                    # 현재 청크 내에서 정의된 엔티티 간의 관계만 수집
                    if src_id in chunk_entities and tgt_id in chunk_entities:
                        src_global = chunk_entities[src_id]
                        tgt_global = chunk_entities[tgt_id]
                        rel_key = (src_global, tgt_global, norm_rel)
                        if rel_key in relation_seen:
                            continue
                        result.relations.append({
                            "source_id": src_global,
                            "target_id": tgt_global,
                            "relation": rel_desc.strip(),
                            "chunk_id": i,
                            "document_id": result.document_id,
                        })
                        relation_seen.add(rel_key)

            # 매 청크마다 파일 업데이트 (중간 손실 방지)
            with out_path.open("w", encoding="utf-8") as f:
                json.dump({
                    "document_id": result.document_id,
                    "entities": result.entities,
                    "events": result.events,
                    "relations": result.relations,
                }, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Chunk {i}/{len(chunks)}: {len(chunk_entities)} entities found.")

        except Exception as e:
            logger.error(f"Chunk {i} Extraction Error: {e}")

    finally:
        sglang_manager.release("generator")

    logger.info(f"==> 추출 완료: {out_path} (총 {len(result.entities)}개 엔티티)")
    
    # GPU 메모리 해제: 런타임 종료
    shutdown_runtime()
    
    return result, out_path

class LLMMetadataExtractor:
    def __init__(self, model_name: Optional[str] = None, config: Optional[Any] = None) -> None:
        self.config = config or (RAGConfig() if RAGConfig else None)
        if self.config and not model_name and hasattr(self.config, "LLM_MODEL"):
            model_name = getattr(self.config, "LLM_MODEL")
        # 모델명 오타 주의: Qwen/Qwen3-8B가 맞는지 확인 필요 (보통 Qwen2.5-7B 등)
        self.model_name = model_name or getattr(self.config, 'GRAPH_EXTRACTOR_MODEL', 'Qwen/Qwen3-8B') if self.config else (model_name or 'Qwen/Qwen3-8B')
        self.output_dir = _resolve_output_dir(config=self.config, session_id=None)

    def _infer_session_id(self, md_path: Path) -> Optional[str]:
        parts = md_path.resolve().parts
        if "sessions" in parts:
            idx = parts.index("sessions")
            return parts[idx + 1] if len(parts) > idx + 1 else None
        return None

    def extract_from_markdown(
        self,
        md_path: Path,
        document_id: Optional[str] = None,
        save_result: bool = True,
        session_id: Optional[str] = None,
    ) -> tuple[ExtractionResult, Optional[Path]]:
        session_id = session_id or self._infer_session_id(md_path)
        result, saved_path = process_document(
            md_path,
            session_id=session_id,
            config=self.config,
            model_name=self.model_name,
        )

        if save_result and saved_path:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            target = self.output_dir / saved_path.name
            if saved_path.exists() and saved_path != target:
                shutil.copy(saved_path, target)
                saved_path = target

        return result, saved_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown_path")
    parser.add_argument("--session_id", default=None)
    args = parser.parse_args()
    process_document(args.markdown_path, session_id=args.session_id)