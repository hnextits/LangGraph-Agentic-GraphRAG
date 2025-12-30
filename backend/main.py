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
from api import routes as api_routes
from api.routes import router as api_router
# from api.summary_routes import router as summary_router
from api.pause_api import router as pause_router
# from api.chat import router as chat_router
from api.mindmap_routes import router as mindmap_router
from services.model_manager import LazyModelManager
from services.rag_service import build_rag_pipeline, cleanup_rag_pipeline

model_manager = LazyModelManager()

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
    애플리케이션 시작 시 기본 상태를 설정합니다.
    모든 모델은 LazyModelManager를 통해 필요할 때 로드됩니다.
    """
    # 실행 중인 작업을 저장할 딕셔너리 초기화
    app.state.running_tasks = {}

    # 작업 상태 관리를 위한 전역 변수들을 app.state에 초기화
    app.state.tasks = api_routes.tasks
    app.state.task_status = api_routes.task_status
    app.state.task_cache = api_routes.task_cache
    app.state.task_cache_timestamps = api_routes.task_cache_timestamps
    logger.info("실행 작업 관리자(running_tasks)가 초기화되었습니다.")

    def register_models():
        from api.routes import build_answer_generator
        from skill.mindmap.mindmap_generator import MindMapGenerator

        if "rag_pipeline" not in model_manager._models:
            model_manager.register(
                "rag_pipeline",
                build_rag_pipeline,
                cleanup_rag_pipeline,
                idle_timeout=20,
            )
        if "answer_generator" not in model_manager._models:
            model_manager.register(
                "answer_generator",
                build_answer_generator,
                lambda gen: getattr(gen, "cleanup_model", lambda: None)(),
                idle_timeout=20,
            )
        if "mindmap_generator" not in model_manager._models:
            model_manager.register(
                "mindmap_generator",
                MindMapGenerator,
                lambda gen: getattr(gen, "shutdown", lambda: None)(),
                idle_timeout=20,
            )

    register_models()
    app.state.model_manager = model_manager
    logger.info("LazyModelManager에 모델 등록 완료 (모든 모델은 Lazy Loading 지원)")

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
app.include_router(mindmap_router)

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
