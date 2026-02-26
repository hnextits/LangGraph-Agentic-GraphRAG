# MCP Tool Server

MCP (Model Context Protocol) 서버는 LangGraph RAG 시스템의 Tool Calling을 담당하는 독립 서비스입니다.

## 기능

- **Calculator**: AST 기반 안전한 수식 평가
- **SQL Executor**: SQL 쿼리 실행 (스텁)
- **API Caller**: 외부 API 호출 (스텁)
- **Code Runner**: 코드 실행 (스텁)

## 설치 및 실행

```bash
cd mcp_server
pip install -r requirements.txt

# 서버 시작 (기본 포트: 8001)
python main.py

# 또는 uvicorn 직접 실행
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

## API 엔드포인트

### Health Check
```bash
GET /health
```

### Tool 목록 조회
```bash
GET /tools
```

### Tool 실행
```bash
POST /tools/{tool_name}/execute
Content-Type: application/json

{
  "inputs": {
    "expression": "2+3*4"  # calculator의 경우
  }
}
```

## 예제

### Calculator 사용
```bash
curl -X POST http://localhost:8001/tools/calculator/execute \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"expression": "10 + 20 * 3"}}'
```

응답:
```json
{
  "status": "ok",
  "result": 70.0,
  "message": "10 + 20 * 3 = 70.0"
}
```

## 환경 변수

LangGraph RAG 시스템의 `config.py`에서 다음 설정:

```python
MCP_SERVER_ENABLED = True
MCP_SERVER_URL = "http://localhost:8001"
MCP_TIMEOUT = 30
```

## 새 Tool 추가하기

1. `main.py`에 executor 함수 작성
2. `TOOL_REGISTRY`에 등록
3. 재시작

```python
def execute_my_tool(inputs: Dict[str, Any]) -> ToolExecuteResponse:
    # 구현
    return ToolExecuteResponse(status="ok", result=...)

TOOL_REGISTRY["my_tool"] = {
    "executor": execute_my_tool,
    "info": ToolInfo(...)
}
```
