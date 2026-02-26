#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""경로 선택 및 라우팅 로직."""
from __future__ import annotations

import logging
import re
from typing import List

logger = logging.getLogger(__name__)


class PathSelector:
    """백트래킹 시 최적 경로 선택."""
    
    @staticmethod
    def select_best_path(query: str, max_hops: int, remaining_paths: List[str]) -> str:
        """쿼리 특성과 hop 수를 기반으로 남은 경로 중 최적의 경로를 선택.
        
        Args:
            query: 사용자 질문
            max_hops: 추정된 hop 수
            remaining_paths: 아직 시도하지 않은 경로 목록
            
        Returns:
            선택된 경로 ("vector" | "cross_ref" | "graph_db")
        """
        if not remaining_paths:
            return "vector"  # fallback
        
        # 각 경로에 대한 적합도 점수 계산
        scores = {}
        q_lower = query.lower()
        
        for path in remaining_paths:
            score = 0.0
            
            if path == "vector":
                # 단순 사실 질문, 정의 질문에 적합
                if max_hops <= 2:
                    score += 3.0
                # 키워드 기반 추가 점수
                simple_keywords = ["무엇", "what", "정의", "definition", "설명", "explain", "describe"]
                if any(kw in q_lower for kw in simple_keywords):
                    score += 1.0
                # 단일 개념 질문
                if "/" not in query and "," not in query:
                    score += 0.5
                    
            elif path == "cross_ref":
                # 중간 복잡도, 관계/비교 질문에 적합
                if 3 <= max_hops <= 5:
                    score += 3.0
                # 관계 키워드
                relation_keywords = [
                    "관계", "비교", "차이", "연관", "영향", "상호작용",
                    "relate", "compare", "difference", "connection", "impact",
                    "versus", "vs", "trade-off", "장단점", "pros", "cons"
                ]
                if any(kw in q_lower for kw in relation_keywords):
                    score += 2.0
                # 2-3개 개념 비교
                concept_count = q_lower.count("/") + q_lower.count(",")
                if 1 <= concept_count <= 3:
                    score += 1.0
                    
            elif path == "graph_db":
                # 복잡한 다단계 추론, 체인 질문에 적합
                if max_hops >= 6:
                    score += 3.0
                # 체인/경로 키워드
                chain_keywords = [
                    "경로", "흐름", "단계", "체인", "파이프라인", "전체", "모든",
                    "path", "flow", "chain", "pipeline", "end-to-end", "trace",
                    "거쳐", "경유", "순서", "과정", "process", "이어지는"
                ]
                if any(kw in q_lower for kw in chain_keywords):
                    score += 2.0
                # 화살표 패턴 (명시적 체인)
                if "→" in query or "->" in query or "=>" in query:
                    score += 1.5
                # 다수 개념 연결
                if q_lower.count("/") + q_lower.count(",") >= 3:
                    score += 1.0
            
            scores[path] = score
        
        # 가장 높은 점수의 경로 선택
        best_path = max(remaining_paths, key=lambda p: scores.get(p, 0.0))
        logger.info("경로 선택: query='%s', max_hops=%d, 점수=%s → 선택=%s",
                    query[:50], max_hops, scores, best_path)
        return best_path


class HopClassifier:
    """쿼리 복잡도 기반 홉 수 분류."""

    @staticmethod
    def classify_hops_llm(config, query: str) -> Optional[int]:
        """LLM을 사용한 쿼리 복잡도 기반 홉 수 추정.

        Args:
            config: RAGConfig 인스턴스
            query: 사용자 쿼리

        Returns:
            1~6 정수 또는 None (호출 실패 시)
        """
        endpoint = getattr(config, "HOP_CLASSIFIER_SGLANG_ENDPOINT", None)
        if not endpoint:
            return None

        api_url = f"{endpoint}/v1/chat/completions"
        model = getattr(config, "HOP_CLASSIFIER_MODEL", "default")
        timeout = getattr(config, "HOP_CLASSIFIER_TIMEOUT", 15)
        max_tokens = getattr(config, "HOP_CLASSIFIER_MAX_TOKENS", 8)

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
            import requests
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
            text = re.sub(r'<[tT]hink>.*?</[tT]hink>', '', text, flags=re.DOTALL).strip()
            text = re.sub(r'<[tT]hink>.*', '', text, flags=re.DOTALL).strip()
            match = re.search(r'[1-6]', text)
            if match:
                hops = int(match.group())
                logger.info("HopClassifier(LLM): query='%s' → hops=%d (raw='%s')", query[:50], hops, text)
                return hops
            logger.warning("HopClassifier(LLM): 파싱 실패 raw='%s'", text)
        except Exception as exc:
            logger.warning("HopClassifier(LLM) 호출 실패: %s", exc)
        return None
    
    @staticmethod
    def classify_hops_heuristic(query: str) -> int:
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
