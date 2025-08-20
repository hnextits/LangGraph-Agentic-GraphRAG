import torch
import os
from pathlib import Path

class PathConfig:
    '''경로 설정을 중앙화하는 클래스'''
    
    def __init__(self):
        # 기본 경로는 backend 디렉토리를 기준으로 설정
        self.BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ''))
        
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
            print(f"[INFO] 디렉토리 확인: {directory}")

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
        self.model = "Qwen/Qwen3-4B"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"        
        self.chunk_len = 3600 # 크롤링 데이터 나눠서 요약할 크기