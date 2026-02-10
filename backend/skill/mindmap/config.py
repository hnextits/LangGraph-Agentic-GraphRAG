import os
import logging
from pathlib import Path
from decouple import Config as DecoupleConfig, RepositoryEnv, config as decouple_config

logger = logging.getLogger(__name__)

class _EnvFallback:
    """decouple.Config 대체용: 시스템 환경변수만 조회"""
    def __call__(self, key, default=None, cast=None):
        if cast is None:
            return decouple_config(key, default=default)
        return decouple_config(key, default=default, cast=cast)

    def get(self, key, default=None):
        return decouple_config(key, default=default)

# .env 파일 경로를 현재 파일 기준으로 설정
env_path = Path(__file__).parent / '.env'

if env_path.exists():
    config_loader = DecoupleConfig(RepositoryEnv(str(env_path)))
else:
    logger.warning("mindmap .env 파일을 찾을 수 없습니다. 시스템 환경변수를 사용합니다: %s", env_path)
    config_loader = _EnvFallback()

class Config:
    """Configuration for the Mindmap Generator application."""
    # SGLang Local Model Configuration
    SGLANG_MODEL_PATH = config_loader.get('SGLANG_MODEL_PATH', 'Qwen/Qwen3-30B-A3B-Instruct-2507-FP8')
    SGLANG_DEVICE = config_loader.get('SGLANG_DEVICE', 'cuda:1')
    SGLANG_MEM_FRACTION = float(config_loader.get('SGLANG_MEM_FRACTION', '0.7'))
    SGLANG_MAX_TOKENS = 8192
    TOKEN_BUFFER = 500

    # Weaviate Configuration
    WEAVIATE_URL = config_loader('WEAVIATE_URL', default='http://127.0.0.1:8080')
    WEAVIATE_API_KEY = config_loader('WEAVIATE_API_KEY', default=None)
    WEAVIATE_CLASS_NAME = config_loader('WEAVIATE_CLASS_NAME', default='Segment')
    WEAVIATE_VECTORIZER = config_loader('WEAVIATE_VECTORIZER', default='text2vec-model2vec')
