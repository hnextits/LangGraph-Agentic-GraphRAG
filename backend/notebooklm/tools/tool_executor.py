#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tool 실행 및 로컬 fallback 구현."""
from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any, Dict, Literal, Optional

from .mcp_client import MCPClient

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Tool 실행을 담당하는 클래스. MCP 서버 우선, fallback으로 로컬 실행."""

    def __init__(self, mcp_base_url: Optional[str] = None, enable_mcp: bool = True):
        """
        Args:
            mcp_base_url: MCP 서버 URL
            enable_mcp: MCP 서버 사용 여부
        """
        self.enable_mcp = enable_mcp
        self.mcp_client = MCPClient(base_url=mcp_base_url) if enable_mcp else None
        self.mcp_available = False
        
        if self.mcp_client:
            self.mcp_available = self.mcp_client.health_check()
            if self.mcp_available:
                logger.info("MCP 서버 연결 성공")
            else:
                logger.warning("MCP 서버 연결 실패 → 로컬 fallback 사용")

    def classify_intent(
        self, 
        query: str,
        llm_endpoint: Optional[str] = None,
        llm_model: str = "default",
    ) -> Literal["knowledge", "calculation", "database", "api_call", "code_exec"]:
        """쿼리 의도 분류 (LLM 우선, fallback으로 규칙 기반).
        
        Args:
            query: 사용자 질문
            llm_endpoint: LLM 엔드포인트 (hop classifier와 동일)
            llm_model: LLM 모델명
            
        Returns:
            의도 카테고리
        """
        # 1차: LLM 기반 분류
        if llm_endpoint:
            llm_intent = self._classify_intent_llm(query, llm_endpoint, llm_model)
            if llm_intent:
                return llm_intent
        
        # 2차: 규칙 기반 fallback
        return self._classify_intent_heuristic(query)

    def _classify_intent_llm(
        self, 
        query: str, 
        endpoint: str, 
        model: str,
    ) -> Optional[Literal["knowledge", "calculation", "database", "api_call", "code_exec"]]:
        """LLM을 사용한 의도 분류."""
        system_prompt = (
            "You are a query intent classifier. Given a user question, classify it into ONE of these categories:\n"
            "- knowledge: General knowledge/information retrieval questions\n"
            "- calculation: Math/arithmetic calculations\n"
            "- database: SQL queries or database operations\n"
            "- api_call: External API requests\n"
            "- code_exec: Code execution requests\n\n"
            "Output ONLY the category name. No explanation."
        )
        
        try:
            import requests
            resp = requests.post(
                f"{endpoint}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query},
                    ],
                    "max_tokens": 16,
                    "temperature": 0.0,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                timeout=10,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip().lower()
            
            # 응답에서 카테고리 추출
            valid_intents = ["knowledge", "calculation", "database", "api_call", "code_exec"]
            for intent in valid_intents:
                if intent in text:
                    logger.info("LLM 의도 분류: query='%s' → %s", query[:40], intent)
                    return intent
            
            logger.warning("LLM 의도 분류 파싱 실패: raw='%s'", text)
        except Exception as exc:
            logger.warning("LLM 의도 분류 실패: %s", exc)
        
        return None

    def _classify_intent_heuristic(
        self, 
        query: str,
    ) -> Literal["knowledge", "calculation", "database", "api_call", "code_exec"]:
        """규칙 기반 의도 분류 (fallback)."""
        q = query.lower()
        has_numbers = bool(re.search(r"\d", q))
        
        calc_keywords = ["sum", "plus", "minus", "곱", "더해", "빼", "계산", "나눠", "%", "^", "×", "÷"]
        sql_keywords = ["sql", "select", "join", "database", "쿼리", "테이블", "insert", "update", "delete"]
        api_keywords = ["api", "endpoint", "request", "curl", "http", "호출", "fetch"]
        code_keywords = ["code", "python", "script", "실행", "run", "function", "에러", "execute"]

        if any(kw in q for kw in calc_keywords) and has_numbers:
            return "calculation"
        if any(kw in q for kw in sql_keywords):
            return "database"
        if any(kw in q for kw in api_keywords):
            return "api_call"
        if any(kw in q for kw in code_keywords):
            return "code_exec"
        
        return "knowledge"

    def map_intent_to_tool(self, intent: str) -> str:
        """의도를 Tool 이름으로 매핑."""
        mapping = {
            "calculation": "calculator",
            "database": "sql_executor",
            "api_call": "api_caller",
            "code_exec": "code_runner",
        }
        return mapping.get(intent, "")

    def prepare_tool_inputs(self, intent: str, query: str) -> Dict[str, Any]:
        """Tool 입력 파라미터 준비."""
        if intent == "calculation":
            expression = self._extract_math_expression(query)
            return {"expression": expression, "raw_query": query}
        if intent == "database":
            return {"sql": query, "raw_query": query}
        if intent == "api_call":
            return {"prompt": query}
        if intent == "code_exec":
            return {"snippet": query}
        return {"prompt": query}

    def _extract_math_expression(self, text: str) -> str:
        """텍스트에서 수식 추출."""
        cleaned = re.sub(r"[^0-9+\-*/().%^]", " ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def execute_tool(self, tool_name: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Tool 실행 (MCP 우선, fallback으로 로컬).
        
        Args:
            tool_name: Tool 이름
            inputs: Tool 입력
            
        Returns:
            {"status": "ok"|"error", "result": ..., "message": ...}
        """
        # MCP 서버 사용 가능하면 MCP로 실행
        if self.mcp_available and self.mcp_client:
            result = self.mcp_client.call_tool(tool_name, inputs)
            if result.get("status") != "error":
                return result
            logger.warning("MCP Tool 실행 실패 → 로컬 fallback: tool=%s", tool_name)
        
        # 로컬 fallback
        return self._execute_local(tool_name, inputs)

    def _execute_local(self, tool_name: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """로컬에서 Tool 실행 (fallback)."""
        if tool_name == "calculator":
            return self._execute_calculator(inputs.get("expression", ""))
        if tool_name == "sql_executor":
            return self._execute_sql_stub(inputs)
        if tool_name == "api_caller":
            return self._execute_api_stub(inputs)
        if tool_name == "code_runner":
            return self._execute_code_stub(inputs)
        
        return {"status": "error", "message": f"알 수 없는 Tool: {tool_name}"}

    def _execute_calculator(self, expression: str) -> Dict[str, Any]:
        """계산기 Tool (로컬 구현)."""
        if not expression:
            return {"status": "error", "message": "계산할 식이 없습니다."}
        
        try:
            node = ast.parse(expression, mode="eval")
            value = self._eval_ast(node.body)
            return {"status": "ok", "result": value, "expression": expression}
        except Exception as exc:
            return {"status": "error", "message": str(exc), "expression": expression}

    def _eval_ast(self, node: ast.AST) -> float:
        """AST 기반 안전한 수식 평가."""
        if isinstance(node, ast.BinOp):
            left = self._eval_ast(node.left)
            right = self._eval_ast(node.right)
            
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return left ** right
            if isinstance(node.op, ast.Mod):
                return left % right
        
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_ast(node.operand)
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.USub):
                return -operand
        
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        
        raise ValueError("지원하지 않는 수식입니다.")

    def _execute_sql_stub(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """SQL 실행기 스텁 (추후 구현)."""
        return {
            "status": "not_implemented",
            "message": "SQL 실행기는 아직 구현되지 않았습니다.",
            "sql": inputs.get("sql") or inputs.get("raw_query", ""),
        }

    def _execute_api_stub(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """API 호출기 스텁 (추후 구현)."""
        return {
            "status": "not_implemented",
            "message": "API 호출기는 아직 구현되지 않았습니다.",
            "request": inputs,
        }

    def _execute_code_stub(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """코드 실행기 스텁 (추후 구현)."""
        return {
            "status": "not_implemented",
            "message": "코드 실행기는 아직 구현되지 않았습니다.",
            "snippet": inputs.get("snippet") or inputs.get("prompt", ""),
        }

    def summarize_result(self, result: Any) -> str:
        """Tool 실행 결과 요약."""
        if result is None:
            return "(툴 결과 없음)"
        if isinstance(result, (str, int, float)):
            return str(result)
        try:
            return json.dumps(result, ensure_ascii=False)[:400]
        except Exception:
            return str(result)[:400]
