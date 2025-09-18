import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv
import torch

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 프로젝트 루트 디렉토리 찾기
BACKEND_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = BACKEND_DIR.parent

# 백엔드 .env 파일 로드 (로컬 개발용)
# Jenkins에서 설정한 환경변수가 .env 파일보다 우선합니다.
ENV_PATH = BACKEND_DIR / '.env'
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
    logger.info(f"백엔드 .env 파일 로드됨: {ENV_PATH}")
else:
    logger.info(f"백엔드 .env 파일을 찾을 수 없음. 환경 변수를 사용합니다: {ENV_PATH}")

class PathConfig:
    '''경로 설정을 중앙화하는 클래스'''
    
    def __init__(self):
        # 기본 경로는 backend 디렉토리를 기준으로 설정
        self.BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
        
        # 저장 경로 설정 - 상대경로 사용
        self.NEXTITS_DATA_DIR = os.path.join(self.BASE_DIR, 'nextits_data')
        self.DOC_DIR = os.path.join(self.NEXTITS_DATA_DIR, 'doc')
        self.RESULTS_DIR = os.path.join(self.NEXTITS_DATA_DIR, 'Results')
        self.OCR_RESULTS_DIR = os.path.join(self.RESULTS_DIR, '3.OCR_results')
        
        # 크롤링 데이터 저장 경로 - 마크다운 파일을 바로 doc 디렉토리에 저장
        # 하위 디렉토리 없이 바로 저장
        self.SNIPPET_DIR = self.DOC_DIR
        self.CLEAN_MD_DIR = self.DOC_DIR
        self.NAMUWIKI_DIR = self.DOC_DIR
        self.WIKIPEDIA_DIR = self.DOC_DIR
        
        # 디렉토리 생성
        self.ensure_directories()
    
    def ensure_directories(self):
        '''필요한 모든 디렉토리가 존재하는지 확인하고 없으면 생성합니다.'''
        directories = [
            self.DOC_DIR,
            self.RESULTS_DIR,
            self.OCR_RESULTS_DIR
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            logger.info(f"[INFO] 디렉토리 확인: {directory}")

class SearchEngineConfig:
    '''Google Search Engine 시스템 설정 '''
    
    def __init__(self):
        # Google Search API 설정 (사용 시에만 연결)
        self.ENABLE_GOOGLE_SEARCH = True  # Google Search API 사용 여부
        self.API_KEY = "REMOVED_SECRET"
        self.CX_ID = "f00b2a2eaff4b4fbf"
        # 연결 관리 설정
        self.CONNECTION_TIMEOUT = 10  # 연결 타임아웃 (초)
        self.READ_TIMEOUT = 30  # 읽기 타임아웃 (초)
        self.CLOSE_CONNECTION = True  # 요청 후 연결 즉시 종료
        self.model = "Qwen/Qwen3-4B-Instruct-2507"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"        
        self.chunk_len = 3600 # 크롤링 데이터 나눠서 요약할 크기


# notebooklm/config.py에서 RAGConfig 임포트
sys.path.append(os.path.join(BACKEND_DIR, "notebooklm"))
from notebooklm.config import RAGConfig

# 환경 변수 설정
HOST = '0.0.0.0'  # 모든 네트워크 인터페이스에서 수신
PORT = int(os.getenv('PORT', '5000'))

# RAG 시스템 경로 설정
RAG_SYSTEM_PATH = os.getenv('RAG_SYSTEM_PATH', '../notebooklm')

# RAG 시스템 경로를 sys.path에 추가하여 내부 모듈 import가 가능하도록 함
if RAG_SYSTEM_PATH and RAG_SYSTEM_PATH not in sys.path:
    sys.path.append(RAG_SYSTEM_PATH) # 맨 뒤에 추가하여 config 충돌 방지
    logger.info(f"RAG 시스템 경로 추가: {RAG_SYSTEM_PATH}")

# 기타 설정
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 't')
