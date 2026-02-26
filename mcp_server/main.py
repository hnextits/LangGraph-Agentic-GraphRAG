#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MCP (Model Context Protocol) 서버 - Tool 실행 서비스."""
from __future__ import annotations

import ast
import logging
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MCP Tool Server", version="1.0.0")


# ============================================================================
# Request/Response Models
# ============================================================================

class ToolExecuteRequest(BaseModel):
    """Tool 실행 요청."""
    inputs: Dict[str, Any]


class ToolExecuteResponse(BaseModel):
    """Tool 실행 응답."""
    status: str  # "ok" | "error" | "not_implemented"
    result: Any = None
    message: str = ""


class ToolInfo(BaseModel):
    """Tool 정보."""
    name: str
    description: str
    parameters: Dict[str, Any]


class ToolListResponse(BaseModel):
    """Tool 목록 응답."""
    tools: List[ToolInfo]


class HealthResponse(BaseModel):
    """헬스 체크 응답."""
    status: str
    version: str


# ============================================================================
# Tool Implementations
# ============================================================================

def execute_calculator(inputs: Dict[str, Any]) -> ToolExecuteResponse:
    """계산기 Tool - AST 기반 안전한 수식 평가."""
    expression = inputs.get("expression", "")
    
    if not expression:
        return ToolExecuteResponse(
            status="error",
            message="계산할 식이 없습니다."
        )
    
    try:
        node = ast.parse(expression, mode="eval")
        result = _eval_ast(node.body)
        return ToolExecuteResponse(
            status="ok",
            result=result,
            message=f"{expression} = {result}"
        )
    except Exception as exc:
        return ToolExecuteResponse(
            status="error",
            message=f"계산 오류: {exc}",
            result=None
        )


def _eval_ast(node: ast.AST) -> float:
    """AST 노드를 안전하게 평가."""
    if isinstance(node, ast.BinOp):
        left = _eval_ast(node.left)
        right = _eval_ast(node.right)
        
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("0으로 나눌 수 없습니다")
            return left / right
        if isinstance(node.op, ast.Pow):
            return left ** right
        if isinstance(node.op, ast.Mod):
            return left % right
    
    if isinstance(node, ast.UnaryOp):
        operand = _eval_ast(node.operand)
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.USub):
            return -operand
    
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    
    raise ValueError(f"지원하지 않는 수식입니다: {ast.dump(node)}")


def execute_sql(inputs: Dict[str, Any]) -> ToolExecuteResponse:
    """SQL 실행기 - 현재는 스텁."""
    return ToolExecuteResponse(
        status="not_implemented",
        message="SQL 실행기는 아직 구현되지 않았습니다.",
        result={"sql": inputs.get("sql") or inputs.get("raw_query", "")}
    )


def execute_api_caller(inputs: Dict[str, Any]) -> ToolExecuteResponse:
    """API 호출기 - 현재는 스텁."""
    return ToolExecuteResponse(
        status="not_implemented",
        message="API 호출기는 아직 구현되지 않았습니다.",
        result={"request": inputs}
    )


def execute_code_runner(inputs: Dict[str, Any]) -> ToolExecuteResponse:
    """코드 실행기 - 현재는 스텁."""
    return ToolExecuteResponse(
        status="not_implemented",
        message="코드 실행기는 아직 구현되지 않았습니다.",
        result={"snippet": inputs.get("snippet") or inputs.get("prompt", "")}
    )


# ============================================================================
# Tool Registry
# ============================================================================

TOOL_REGISTRY = {
    "calculator": {
        "executor": execute_calculator,
        "info": ToolInfo(
            name="calculator",
            description="수학 계산을 수행합니다. AST 기반 안전한 평가를 사용합니다.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "계산할 수식 (예: '2+3*4')"
                    }
                },
                "required": ["expression"]
            }
        )
    },
    "sql_executor": {
        "executor": execute_sql,
        "info": ToolInfo(
            name="sql_executor",
            description="SQL 쿼리를 실행합니다 (현재 스텁).",
            parameters={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "실행할 SQL 쿼리"
                    }
                },
                "required": ["sql"]
            }
        )
    },
    "api_caller": {
        "executor": execute_api_caller,
        "info": ToolInfo(
            name="api_caller",
            description="외부 API를 호출합니다 (현재 스텁).",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "API 호출 요청"
                    }
                },
                "required": ["prompt"]
            }
        )
    },
    "code_runner": {
        "executor": execute_code_runner,
        "info": ToolInfo(
            name="code_runner",
            description="코드를 실행합니다 (현재 스텁).",
            parameters={
                "type": "object",
                "properties": {
                    "snippet": {
                        "type": "string",
                        "description": "실행할 코드 스니펫"
                    }
                },
                "required": ["snippet"]
            }
        )
    }
}


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """헬스 체크 엔드포인트."""
    return HealthResponse(status="ok", version="1.0.0")


@app.get("/tools", response_model=ToolListResponse)
async def list_tools():
    """사용 가능한 Tool 목록 조회."""
    tools = [tool_data["info"] for tool_data in TOOL_REGISTRY.values()]
    logger.info("Tool 목록 조회: %d개", len(tools))
    return ToolListResponse(tools=tools)


@app.post("/tools/{tool_name}/execute", response_model=ToolExecuteResponse)
async def execute_tool(tool_name: str, request: ToolExecuteRequest):
    """Tool 실행."""
    if tool_name not in TOOL_REGISTRY:
        logger.warning("알 수 없는 Tool: %s", tool_name)
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    
    tool_data = TOOL_REGISTRY[tool_name]
    executor = tool_data["executor"]
    
    try:
        logger.info("Tool 실행: %s, inputs=%s", tool_name, request.inputs)
        response = executor(request.inputs)
        logger.info("Tool 실행 완료: %s, status=%s", tool_name, response.status)
        return response
    except Exception as exc:
        logger.exception("Tool 실행 중 예외: %s", tool_name)
        return ToolExecuteResponse(
            status="error",
            message=f"Tool 실행 중 예외 발생: {exc}"
        )


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
