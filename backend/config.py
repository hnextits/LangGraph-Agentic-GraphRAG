import os
import sys
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

try:
    import torch  # type: ignore
except Exception:  # pragma: no cover - torch는 선택적 의존성
    torch = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 경로 및 .env 로드
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = BACKEND_DIR.parent

for env_path in [PROJECT_ROOT / ".env", BACKEND_DIR / ".env"]:
    if env_path.exists():
        load_dotenv(env_path, override=False)

# notebooklm/config.py에서 RAGConfig 임포트
# RAGConfig에 Search 설정도 통합되어 있음
from notebooklm.config import RAGConfig

@dataclass(frozen=True)
class AppConfig:
    """FastAPI 서버 및 공용 설정."""

    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8505"))
    debug: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "t")
    rag_system_path: Optional[str] = os.getenv("RAG_SYSTEM_PATH", "../notebooklm")


APP_CONFIG = AppConfig()

# RAG 시스템 경로를 sys.path에 추가하여 내부 모듈 import가 가능하도록 함
if APP_CONFIG.rag_system_path and APP_CONFIG.rag_system_path not in sys.path:
    sys.path.append(APP_CONFIG.rag_system_path)
    logger.info("RAG 시스템 경로 추가: %s", APP_CONFIG.rag_system_path)

# 기존 하위 호환용 상수 유지
HOST = APP_CONFIG.host
PORT = APP_CONFIG.port
DEBUG = APP_CONFIG.debug

