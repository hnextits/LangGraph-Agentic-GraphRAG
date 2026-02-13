"""
OCR Vision Engine 관리자 (SGLang Offline Engine 사용)
LazyModelManager와 통합하여 필요 시 자동으로 엔진을 로드하고 유휴 시 종료
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class OCRVisionManager:
    """OCR Vision Engine 관리 클래스 (Offline Engine 방식)"""
    
    def __init__(self):
        self.config = {
            "model": "ChatDOC/OCRFlux-3B",
            "batch_size": 32,
            "max_new_tokens": 8192,
            "engine_mem_fraction": 0.18,
            "tensor_parallel_size": 1,
            "enable_cuda_graph": True,
            "enable_cross_page_merge": False,
            "supported_image_extensions": [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"]
        }
        self.engine = None
        
    def load_engine(self):
        """SGLang Offline Engine 로드"""
        if self.engine is not None:
            logger.info("OCR Vision Engine already loaded")
            return self.engine
        
        try:
            # inference.py의 get_ocrflux_engine 사용
            from backend.nextits_data.pipe.main_pipe.ocr_pipe.inference import get_ocrflux_engine
            
            logger.info("Loading OCR Vision Engine (Offline)...")
            self.engine = get_ocrflux_engine(self.config)
            logger.info("✅ OCR Vision Engine loaded successfully")
            return self.engine
            
        except Exception as e:
            logger.error(f"Failed to load OCR Vision Engine: {e}", exc_info=True)
            raise
    
    def cleanup(self):
        """엔진 정리 (메모리 해제)"""
        if self.engine is None:
            return
        
        try:
            from backend.nextits_data.pipe.main_pipe.ocr_pipe.inference import shutdown_engine
            
            logger.info("Shutting down OCR Vision Engine...")
            shutdown_engine()
            self.engine = None
            logger.info("✅ OCR Vision Engine shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during OCR Vision Engine cleanup: {e}")
    
    def get_config(self):
        """설정 반환"""
        return self.config
    
    def is_loaded(self) -> bool:
        """엔진이 로드되어 있는지 확인"""
        return self.engine is not None


def build_ocr_vision_manager() -> OCRVisionManager:
    """OCR Vision Manager 빌더 함수 (LazyModelManager용)"""
    manager = OCRVisionManager()
    manager.load_engine()  # 엔진 로드
    return manager


def cleanup_ocr_vision_manager(manager: OCRVisionManager) -> None:
    """OCR Vision Manager 정리 함수 (LazyModelManager용)"""
    manager.cleanup()
