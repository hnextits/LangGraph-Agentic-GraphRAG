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


class PathConfig:
    '''경로 설정을 중앙화하는 클래스'''
    
    def __init__(self):
        # 기본 경로는 backend 디렉토리를 기준으로 설정
        self.BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
        
        # 저장 경로 설정 - 상대경로 사용
        self.NEXTITS_DATA_DIR = os.path.join(self.BASE_DIR, 'nextits_data')
        self.DOC_DIR = os.path.join(self.NEXTITS_DATA_DIR, 'doc')
        self.RESULTS_DIR = os.path.join(self.NEXTITS_DATA_DIR, 'Results')
        self.OCR_RESULTS_DIR = os.path.join(self.RESULTS_DIR, '4.OCR_results')
        

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

# notebooklm/config.py에서 RAGConfig 임포트
# RAGConfig에 Search 설정도 통합되어 있음
notebooklm_path = os.path.join(BACKEND_DIR, "notebooklm")
if notebooklm_path not in sys.path:
    sys.path.insert(0, notebooklm_path)

from config import RAGConfig

# 환경 변수 설정
HOST = '0.0.0.0'  # 모든 네트워크 인터페이스에서 수신
PORT = int(os.getenv('PORT', '8505'))

# RAG 시스템 경로 설정
RAG_SYSTEM_PATH = os.getenv('RAG_SYSTEM_PATH', '../notebooklm')

# RAG 시스템 경로를 sys.path에 추가하여 내부 모듈 import가 가능하도록 함
if RAG_SYSTEM_PATH and RAG_SYSTEM_PATH not in sys.path:
    sys.path.append(RAG_SYSTEM_PATH) # 맨 뒤에 추가하여 config 충돌 방지
    logger.info(f"RAG 시스템 경로 추가: {RAG_SYSTEM_PATH}")

# 기타 설정
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 't')
