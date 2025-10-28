from decouple import Config as DecoupleConfig, RepositoryEnv
import os
from pathlib import Path

# .env 파일 경로를 현재 파일 기준으로 설정
env_path = Path(__file__).parent / '.env'
config_loader = DecoupleConfig(RepositoryEnv(str(env_path)))

class Config:
    """Configuration for the Mindmap Generator application."""
    # SGLang Local Model Configuration
    SGLANG_MODEL_PATH = config_loader.get('SGLANG_MODEL_PATH', 'Qwen/Qwen3-8B')
    SGLANG_DEVICE = config_loader.get('SGLANG_DEVICE', 'cuda:0')
    SGLANG_MEM_FRACTION = float(config_loader.get('SGLANG_MEM_FRACTION', '0.5'))
    SGLANG_MAX_TOKENS = 8192
    TOKEN_BUFFER = 500

    # Weaviate Configuration
    WEAVIATE_URL = config_loader('WEAVIATE_URL', default='http://127.0.0.1:8080')
    WEAVIATE_API_KEY = config_loader('WEAVIATE_API_KEY', default=None)
    WEAVIATE_CLASS_NAME = config_loader('WEAVIATE_CLASS_NAME', default='Segment')
    WEAVIATE_VECTORIZER = config_loader('WEAVIATE_VECTORIZER', default='text2vec-model2vec')
