#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SGLang 기반 Hop 분류기."""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Optional

try:  # pragma: no cover - optional dependency guard
    import openai
except Exception as exc:  # pragma: no cover
    raise ImportError("openai 패키지가 필요합니다. 'pip install openai'로 설치하세요.") from exc

logger = logging.getLogger(__name__)


class HopClassifier:
    """SGLang OpenAI 호환 서버를 호출해 hop 복잡도를 추정."""

    def __init__(self, config) -> None:
        self.config = config
        self.model_name = config.HOP_CLASSIFIER_MODEL
        self.max_new_tokens = max(4, int(config.HOP_CLASSIFIER_MAX_TOKENS or 8))
        self.endpoint = config.HOP_CLASSIFIER_SGLANG_ENDPOINT.rstrip("/")
        self.api_key = config.HOP_CLASSIFIER_API_KEY or "EMPTY"
        self.timeout = int(getattr(config, "HOP_CLASSIFIER_TIMEOUT", 15))

        self._client: Optional[openai.Client] = None
        self._client_lock = threading.Lock()

    # ------------------------------------------------------------------
    def _ensure_client(self) -> None:
        import requests as _req
        from notebooklm.sglang_server_manager import sglang_manager

        # 클라이언트가 있어도 서버 생존 확인
        if self._client is not None:
            try:
                resp = _req.get(f"{self.endpoint}/health", timeout=3)
                if resp.status_code == 200:
                    sglang_manager.touch("generator")
                    return
            except Exception:
                pass
            self._client = None  # 서버 죽었으면 클라이언트 리셋

        with self._client_lock:
            if self._client is not None:
                return

            # 서버가 꺼져있으면 자동 기동
            try:
                resp = _req.get(f"{self.endpoint}/health", timeout=3)
                if resp.status_code != 200:
                    raise ConnectionError
                sglang_manager.touch("generator")
            except Exception:
                logger.info("HopClassifier: generator 서버 미기동 → acquire 시도")
                try:
                    if sglang_manager.acquire("generator"):
                        sglang_manager.release("generator")
                except Exception as e:
                    logger.error("HopClassifier: generator 자동 기동 실패: %s", e)

            logger.info(
                "HopClassifier용 SGLang 클라이언트를 초기화합니다. endpoint=%s",
                self.endpoint,
            )
            self._client = openai.Client(
                base_url=self.endpoint,
                api_key=self.api_key or "EMPTY",
                timeout=self.timeout,
            )

    # ------------------------------------------------------------------
    def estimate_hops(self, query: str) -> int:
        """질문을 받고 hop 추정값(1~8)을 반환."""
        if not query:
            return 1

        self._ensure_client()
        assert self._client is not None

        prompt = self._build_prompt(query)
        try:
            response = self._client.completions.create(
                model=self.model_name,
                prompt=prompt,
                max_tokens=self.max_new_tokens,
                temperature=0.0,
                top_p=1.0,
                stop=["\n"],
            )
            answer_text = response.choices[0].text.strip() if response.choices else ""
        except Exception as exc:  # pragma: no cover - 네트워크 안전장치
            logger.warning("HopClassifier SGLang 호출 실패: %s", exc, exc_info=True)
            return self._fallback_estimate(query)

        hop_value = self._parse_hop_from_text(answer_text)
        if hop_value is None:
            logger.info(
                "HopClassifier 응답 파싱 실패 → fallback 사용 | query='%s' | raw='%s'",
                query[:80], answer_text,
            )
            return self._fallback_estimate(query)

        final_hop = max(1, min(8, hop_value))
        logger.info(
            "HopClassifier 결과: hop=%d | query='%s' | raw='%s'",
            final_hop, query[:80], answer_text,
        )
        return final_hop

    # ------------------------------------------------------------------
    def _build_prompt(self, query: str) -> str:
        instructions = (
            "당신은 질문의 복잡도를 판단하는 분석가입니다. "
            "다음 질문을 이해하는 데 필요한 hop 수(연쇄 추론 단계 수)를 1에서 8 사이의 정수로 추정하세요. "
            "답변은 반드시 JSON 형식으로만 출력하며, 예시는 {\"hop_estimate\": 2} 입니다. \n"
        )
        return f"{instructions}질문: {query}\nJSON: "

    def _parse_hop_from_text(self, text: str) -> Optional[int]:
        text = text.strip()
        try:
            json_match = re.search(r"\{.*?\}", text)
            if json_match:
                payload = json.loads(json_match.group(0))
                value = int(payload.get("hop_estimate", 1))
                return value
        except Exception:  # pragma: no cover - 안전장치
            logger.debug("JSON 파싱 실패: %s", text, exc_info=True)

        digit_match = re.search(r"([1-8])", text)
        if digit_match:
            return int(digit_match.group(1))
        return None

    def _fallback_estimate(self, query: str) -> int:
        """간단한 휴리스틱 (토큰 길이 기반) 백업."""
        length = len(query or "")
        if length > 500:
            return 6
        if length > 200:
            return 4
        if length > 80:
            return 3
        return 1


__all__ = ["HopClassifier"]
