import os
import logging
import uvicorn
import sys
from pathlib import Path
import threading

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse

running_tasks = {} 


# 현재 작업 디렉토리를 sys.path에 추가하여 모듈 검색 경로에 포함
# 이렇게 하면 'search_test' 같은 로컬 패키지를 찾을 수 있습니다.

# 현재 디렉토리를 가장 우선순위로 추가
if "." not in sys.path:
    sys.path.insert(0, ".")

# skill 경로를 시스템 경로에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), 'skill'))

# 설정 가져오기 - 절대 경로 사용
import importlib.util
spec = importlib.util.spec_from_file_location("backend_config", os.path.join(os.path.dirname(__file__), "config.py"))
backend_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend_config)

# 설정에서 필요한 변수 가져오기
HOST = backend_config.HOST
PORT = backend_config.PORT

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API 라우터 가져오기
from api.routes import router as api_router
# from api.summary_routes import router as summary_router
from api.pause_api import router as pause_router
# from api.chat import router as chat_router
from services.rag_service import initialize_rag_pipeline

# FastAPI 앱 초기화
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.title = "챗봇 API"

@app.on_event("startup")
def startup_event():
    """
    애플리케이션 시작 시 RAG 파이프라인을 초기화하고, 실행 중인 작업을 관리할 상태를 설정합니다.
    """
    # 실행 중인 작업을 저장할 딕셔너리 초기화
    # key: task_id (str), value: threading.Event 객체
    app.state.running_tasks = {}

    # 작업 상태 관리를 위한 전역 변수들을 app.state에 초기화
    app.state.tasks = {}
    app.state.task_status = {}
    app.state.task_cache = {}
    app.state.task_cache_timestamps = {}
    logger.info("실행 작업 관리자(running_tasks)가 초기화되었습니다.")

    logger.info("RAG 파이프라인 초기화를 시작합니다...")
    app.state.rag_pipeline = initialize_rag_pipeline()
    if app.state.rag_pipeline:
        logger.info("RAG 파이프라인이 성공적으로 초기화되어 app.state.rag_pipeline에 할당되었습니다.")
    else:
        logger.error("RAG 파이프라인 초기화에 실패했습니다.")

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 포함
app.include_router(api_router)
# app.include_router(summary_router)
app.include_router(pause_router, prefix="/api")
# app.include_router(chat_router)

# 서버 실행 설정
if __name__ == "__main__":
    print(f"서버 시작: http://{HOST}:{PORT}")
    print(f"API 문서: http://{HOST}:{PORT}/docs")
    
    # 서버 실행
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False
    )
