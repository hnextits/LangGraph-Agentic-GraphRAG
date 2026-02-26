#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""품질 평가 로직."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class QualityEvaluator:
    """검색 결과 품질 평가."""
    
    def __init__(self, endpoint: str, model: str, timeout: int = 30):
        """
        Args:
            endpoint: Observer LLM 엔드포인트
            model: 모델명
            timeout: 타임아웃 (초)
        """
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
    
    @staticmethod
    def evaluate(config, query: str, entities: List[Dict[str, Any]],
                events: List[Dict[str, Any]], relations: List[Dict[str, Any]]) -> float:
        """Observer LLM을 사용한 검색 결과 품질 평가.

        Args:
            config: RAGConfig 인스턴스
            query: 사용자 쿼리
            entities: 검색된 엔티티 목록
            events: 검색된 이벤트 목록
            relations: 검색된 관계 목록

        Returns:
            품질 점수 (0.0 ~ 1.0)
        """
        if not (entities or events or relations):
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

        endpoint = getattr(config, "HOP_CLASSIFIER_SGLANG_ENDPOINT", None)
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
            import requests
            import re
            resp = requests.post(
                f"{endpoint}/v1/chat/completions",
                json={
                    "model": getattr(config, "HOP_CLASSIFIER_MODEL", "default"),
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
