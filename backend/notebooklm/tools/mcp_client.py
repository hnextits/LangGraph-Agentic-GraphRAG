#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MCP (Model Context Protocol) 서버 클라이언트."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class MCPClient:
    """MCP 서버와 통신하여 Tool 실행을 위임하는 클라이언트."""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 30):
        """
        Args:
            base_url: MCP 서버 URL (예: http://localhost:8001)
            timeout: 요청 타임아웃 (초)
        """
        self.base_url = base_url or "http://localhost:8001"
        self.timeout = timeout
        logger.info("MCPClient 초기화: base_url=%s", self.base_url)

    def list_tools(self) -> List[Dict[str, Any]]:
        """사용 가능한 Tool 목록 조회.
        
        Returns:
            [{"name": "calculator", "description": "...", "parameters": {...}}, ...]
        """
        try:
            resp = requests.get(
                f"{self.base_url}/tools",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            tools = resp.json().get("tools", [])
            logger.info("MCP 서버로부터 %d개 Tool 목록 조회 완료", len(tools))
            return tools
        except Exception as exc:
            logger.warning("MCP Tool 목록 조회 실패: %s", exc)
            return []

    def call_tool(self, tool_name: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """MCP 서버에 Tool 실행 요청.
        
        Args:
            tool_name: 실행할 Tool 이름 (예: "calculator")
            inputs: Tool 입력 파라미터
            
        Returns:
            {"status": "ok"|"error", "result": ..., "message": ...}
        """
        try:
            resp = requests.post(
                f"{self.base_url}/tools/{tool_name}/execute",
                json={"inputs": inputs},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.info("MCP Tool 실행 완료: tool=%s status=%s", tool_name, result.get("status"))
            return result
        except requests.exceptions.Timeout:
            logger.warning("MCP Tool 실행 타임아웃: tool=%s", tool_name)
            return {
                "status": "error",
                "message": f"Tool '{tool_name}' 실행 타임아웃 ({self.timeout}초)",
            }
        except requests.exceptions.RequestException as exc:
            logger.warning("MCP Tool 실행 실패: tool=%s error=%s", tool_name, exc)
            return {
                "status": "error",
                "message": f"Tool '{tool_name}' 실행 실패: {exc}",
            }
        except Exception as exc:
            logger.exception("MCP Tool 실행 중 예외: tool=%s", tool_name)
            return {
                "status": "error",
                "message": f"Tool '{tool_name}' 실행 중 예외: {exc}",
            }

    def health_check(self) -> bool:
        """MCP 서버 헬스 체크.
        
        Returns:
            True if server is healthy, False otherwise
        """
        try:
            resp = requests.get(
                f"{self.base_url}/health",
                timeout=5,
            )
            resp.raise_for_status()
            return resp.json().get("status") == "ok"
        except Exception as exc:
            logger.warning("MCP 서버 헬스 체크 실패: %s", exc)
            return False
