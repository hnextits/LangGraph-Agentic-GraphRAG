import os
import logging
import uvicorn
import sys
import shutil
from pathlib import Path
import threading

import uuid
from fastapi import FastAPI, Request, Depends, Response
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

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션 시작 및 종료 시의 수명 주기 이벤트를 관리합니다.
    """
    # 1. Startup: 세션 데이터 초기화 (휘발성 유지)
    from notebooklm.config import RAGConfig
    config = RAGConfig()
    if config.SESSIONS_ROOT.exists():
        logger.info("서버 시작 시 이전 세션 데이터를 삭제합니다.")
        try:
            # sessions 디렉토리 자체는 남겨두고 내부 세션 폴더들만 삭제
            for session_dir in config.SESSIONS_ROOT.iterdir():
                if session_dir.is_dir():
                    shutil.rmtree(session_dir)
            logger.info("세션 데이터 초기화 완료")
        except Exception as e:
            logger.error(f"세션 데이터 초기화 중 오류: {e}")

    # 2. Startup: 실행 중인 작업을 저장할 딕셔너리 초기화
    app.state.running_tasks = {}

    # 3. Startup: 작업 상태 관리를 위한 전역 변수들을 app.state에 초기화
    app.state.tasks = api_routes.tasks
    app.state.task_status = api_routes.task_status
    app.state.task_cache = api_routes.task_cache
    app.state.task_cache_timestamps = api_routes.task_cache_timestamps
    logger.info("실행 작업 관리자(running_tasks)가 초기화되었습니다.")

    # 4. Startup: GPU 작업 큐 워커 시작
    from utils.task_queue import gpu_task_queue
    import asyncio
    asyncio.create_task(gpu_task_queue.start_worker())
    app.state.gpu_task_queue = gpu_task_queue
    logger.info("GPU 작업 큐 워커가 시작되었습니다.")

    # 5. Startup: 모델 등록 (LazyModelManager)
    def register_models():
        from api.routes import build_answer_generator
        from skill.mindmap.mindmap_generator import MindMapGenerator

        if "rag_pipeline" not in model_manager._models:
            model_manager.register(
                "rag_pipeline",
                build_rag_pipeline,
                cleanup_rag_pipeline,
                idle_timeout=60,
            )
        if "answer_generator" not in model_manager._models:
            model_manager.register(
                "answer_generator",
                build_answer_generator,
                lambda gen: getattr(gen, "cleanup_model", lambda: None)(),
                idle_timeout=60,
            )
        if "mindmap_generator" not in model_manager._models:
            model_manager.register(
                "mindmap_generator",
                MindMapGenerator,
                lambda gen: getattr(gen, "shutdown", lambda: None)(),
                idle_timeout=60,
            )

    register_models()
    app.state.model_manager = model_manager
    logger.info("LazyModelManager에 모델 등록 완료 (모든 모델은 Lazy Loading 지원)")

    # 6. SGLang 서버 등록 (LazyLoading - 필요 시 자동 기동, 유휴 시 자동 종료)
    from notebooklm.sglang_server_manager import sglang_manager
    app.state.sglang_manager = sglang_manager

    logger.info("=" * 60)
    logger.info("SGLang 서버 등록 (LazyLoading 모드)")
    logger.info("=" * 60)

    # 6-1. 생성기 서버 (cuda:0, 포트 30000)
    sglang_manager.register_server(
        name="generator",
        model_path=config.LLM_MODEL,
        port=config.SGLANG_GENERATOR_PORT,
        device=config.SGLANG_GENERATOR_DEVICE,
        extra_args=["--trust-remote-code"],
        idle_timeout=config.SGLANG_IDLE_TIMEOUT,
        mem_fraction=config.SGLANG_GENERATOR_MEM_FRACTION,
    )

    # 6-2. 임베딩 서버 (cuda:1, 포트 30001)
    sglang_manager.register_server(
        name="embedding",
        model_path=config.EMBEDDING_MODEL,
        port=config.SGLANG_EMBEDDING_PORT,
        device=config.SGLANG_EMBEDDING_DEVICE,
        extra_args=["--trust-remote-code", "--is-embedding"],
        idle_timeout=config.SGLANG_IDLE_TIMEOUT,
        mem_fraction=config.SGLANG_EMBEDDING_MEM_FRACTION,
    )

    # 6-3. 리랭커 서버 (cuda:1, 포트 30002)
    sglang_manager.register_server(
        name="reranker",
        model_path=config.RERANKER_MODEL_NAME,
        port=config.SGLANG_RERANKER_PORT,
        device=config.SGLANG_RERANKER_DEVICE,
        extra_args=[
            "--trust-remote-code",
            "--disable-cuda-graph",
            "--is-embedding",
        ],
        idle_timeout=config.SGLANG_IDLE_TIMEOUT,
        mem_fraction=config.SGLANG_RERANKER_MEM_FRACTION,
    )

    # 6-4. 리파이너 서버 (cuda:1, 포트 30003)
    sglang_manager.register_server(
        name="refiner",
        model_path=config.REFINER_MODEL,
        port=config.SGLANG_REFINER_PORT,
        device=config.SGLANG_REFINER_DEVICE,
        extra_args=["--trust-remote-code"],
        idle_timeout=config.SGLANG_IDLE_TIMEOUT,
        mem_fraction=config.SGLANG_REFINER_MEM_FRACTION,
    )

    # 6-5. 쿼리 리라이터 서버 (cuda:1, 포트 30004) — config에서 비활성화 가능
    if getattr(config, "use_query_rewriter", False):
        sglang_manager.register_server(
            name="query_rewriter",
            model_path=config.QUERY_REWRITE_MODEL_NAME,
            port=config.SGLANG_QUERY_REWRITER_PORT,
            device=config.SGLANG_QUERY_REWRITER_DEVICE,
            extra_args=["--trust-remote-code"],
            idle_timeout=config.SGLANG_IDLE_TIMEOUT,
            mem_fraction=config.SGLANG_QUERY_REWRITER_MEM_FRACTION,
        )
    else:
        logger.info("QueryRewriter 비활성화 — SGLang 서버 등록 건너뜀")

    registered_count = len(sglang_manager._servers)
    logger.info("SGLang 서버 %d개 등록 완료 (요청 시 자동 기동, 유휴 시 자동 종료)", registered_count)
    logger.info("=" * 60)

    yield  # 애플리케이션 실행 중

    # 7. Shutdown: SGLang 서버 종료
    logger.info("서버가 종료됩니다. SGLang 서버를 정리합니다...")
    sglang_manager.shutdown_all()
    logger.info("서버 종료 완료.")

# FastAPI 앱 초기화 시 lifespan 설정 적용
app = FastAPI(lifespan=lifespan)
# allow_credentials=True일 경우 allow_origins에 "*"를 사용할 수 없습니다.
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:6004",
    "http://localhost:6005",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:6004",
    "http://127.0.0.1:6005",
    "https://quantuss.hnextits.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["set-cookie"],  # 브라우저가 Set-Cookie 헤더를 볼 수 있게 노출
)

app.title = "챗봇 API"

@app.middleware("http")
async def session_middleware(request: Request, call_next):
    # 0. CORS preflight (OPTIONS) 요청은 세션 처리를 건너뜀
    if request.method == "OPTIONS":
        return await call_next(request)

    # 1. 헤더에서 세션 ID 확인 (우선순위 1)
    session_id = request.headers.get("X-Session-ID")
    
    # 2. 쿠키에서 세션 ID 확인 (우선순위 2)
    if not session_id:
        session_id = request.cookies.get("session_id")
    
    is_new_session = False
    if not session_id:
        # 서버에서 생성하지 않고 클라이언트가 생성하도록 유도하기 위해
        # 여기서는 세션 ID가 없으면 하나 생성해줌
        session_id = str(uuid.uuid4())
        is_new_session = True
        logger.info(f"New session created: {session_id} for {request.url.path}")
    
    request.state.session_id = session_id
    
    # CORS 사전 요청(OPTIONS)과 헬스체크 등은 세션 쿠키 설정을 건너뜀
    if request.method == "OPTIONS" or request.url.path in ["/health", "/metrics", "/favicon.ico"]:
        return await call_next(request)

    response = await call_next(request)
    
    # 클라이언트가 헤더로 세션 ID를 식별할 수 있도록 응답 헤더에도 포함
    response.headers["X-Session-ID"] = session_id
    
    # 쿠키 설정 (브라우저가 헤더를 처리하지 못할 경우를 대비한 백업)
    # 기존에 쿠키가 없거나 새로 생성된 경우에만 설정
    if is_new_session or not request.cookies.get("session_id"):
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            samesite="lax",
            secure=False,
            max_age=3600 * 24 * 7,
            path="/"
        )
    return response

# API 라우터 포함
app.include_router(api_router, prefix="/api/v1")
# app.include_router(summary_router)
app.include_router(pause_router, prefix="/api/v1/pause")
# app.include_router(chat_router)
app.include_router(mindmap_router, prefix="/api/v1/mindmap")

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
