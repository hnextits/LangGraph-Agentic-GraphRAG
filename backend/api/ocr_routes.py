"""
OCR Vision API 라우트
LazyModelManager를 통해 OCR Vision 서버를 자동으로 관리
"""

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter()


class OCRRequest(BaseModel):
    """OCR 요청 모델"""
    input_folder: str
    output_folder: Optional[str] = None
    batch_size: Optional[int] = 64
    max_tokens: Optional[int] = 32768


class OCRResponse(BaseModel):
    """OCR 응답 모델"""
    status: str
    message: str
    output_file: Optional[str] = None
    processed_images: int = 0
    elapsed_time: float = 0.0


@router.post("/ocr/process", response_model=OCRResponse)
async def process_ocr(request: Request, ocr_request: OCRRequest):
    """
    OCR 처리 엔드포인트
    LazyModelManager를 통해 OCR Vision Engine을 자동으로 로드하고 작업 완료 후 자동 종료
    """
    try:
        # LazyModelManager에서 OCR Vision Engine 획득
        model_manager = request.app.state.model_manager
        
        logger.info(f"OCR 작업 시작: {ocr_request.input_folder}")
        
        # OCR Vision Engine 자동 로드 (필요 시)
        with model_manager.session("ocr_vision_engine") as ocr_manager:
            logger.info(f"OCR Vision Engine 획득 완료")
            
            # OCR 처리 실행
            result = await asyncio.to_thread(
                run_ocr_processing,
                ocr_manager,
                ocr_request.input_folder,
                ocr_request.output_folder,
                ocr_request.batch_size,
                ocr_request.max_tokens
            )
            
            return OCRResponse(**result)
        
        # with 블록을 벗어나면 자동으로 release되고 idle_timeout 후 엔진 종료
        
    except FileNotFoundError as e:
        logger.error(f"OCR 처리 실패 (파일 없음): {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"OCR 처리 중 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"OCR 처리 실패: {str(e)}")


def run_ocr_processing(
    ocr_manager,
    input_folder: str,
    output_folder: Optional[str],
    batch_size: int,
    max_tokens: int
) -> dict:
    """
    OCR 처리 실행 (동기 함수)
    inference.py의 process_image_folder를 직접 호출
    """
    import time
    from pathlib import Path
    
    # inference.py 모듈 임포트
    from nextits_data.pipe.main_pipe.ocr_pipe.inference import (
        collect_image_files,
        create_batches,
        process_image_batch,
        save_results,
        cleanup_engine_cache,
        _log
    )
    
    backend_path = Path(__file__).resolve().parent.parent
    
    total_t0 = time.time()
    
    # 기본 출력 폴더 설정
    if output_folder is None:
        output_folder = str(backend_path / "nextits_data" / "Results" / "4.OCR_results")
    
    _log("=== OCR Vision Processing (Offline Engine via LazyModelManager) ===")
    _log(f"Input folder: {input_folder}")
    _log(f"Output folder: {output_folder}")
    _log(f"Batch size: {batch_size}")
    
    # 입력 폴더 확인
    input_path = Path(input_folder)
    if not input_path.exists():
        raise FileNotFoundError(f"입력 폴더가 존재하지 않습니다: {input_folder}")
    
    # 이미지 파일 수집
    supported_extensions = [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"]
    image_files = collect_image_files(input_folder, supported_extensions)
    
    if not image_files:
        raise ValueError("처리할 이미지 파일이 없습니다")
    
    # 엔진 가져오기
    engine = ocr_manager.engine
    config = ocr_manager.get_config()
    config["batch_size"] = batch_size
    config["max_new_tokens"] = max_tokens
    
    # 배치 생성
    batches = create_batches(image_files, batch_size)
    
    # 각 배치 처리
    all_results = []
    for i, batch in enumerate(batches):
        _log(f"\n--- Processing batch {i+1}/{len(batches)} ---")
        _log(f"Progress: {len(all_results)}/{len(image_files)} images completed")
        batch_offset = len(all_results)
        batch_results = process_image_batch(
            engine,
            config,
            batch,
            batch_offset=batch_offset,
            total_images=len(image_files),
            progress_callback=None
        )
        all_results.extend(batch_results)
    
    # 결과 저장
    input_folder_name = Path(input_folder).name
    _log(f"\n--- Saving {len(all_results)} results to single MD file ---")
    save_results(all_results, output_folder, input_folder_name)
    
    # 엔진 캐시 정리
    cleanup_engine_cache()
    
    elapsed = time.time() - total_t0
    output_file = f"{output_folder}/{input_folder_name}.md"
    
    _log("=== Processing completed ===")
    _log(f"Results saved as: {output_file}")
    _log(f"Total elapsed: {elapsed:.1f}s")
    
    return {
        "status": "success",
        "message": "OCR 처리 완료",
        "output_file": output_file,
        "processed_images": len(all_results),
        "elapsed_time": elapsed
    }


@router.get("/ocr/status")
async def get_ocr_status(request: Request):
    """OCR Vision Engine 상태 확인"""
    try:
        model_manager = request.app.state.model_manager
        
        # 엔진이 로드되어 있는지 확인
        if "ocr_vision_engine" not in model_manager._models:
            return {
                "status": "not_registered",
                "message": "OCR Vision Engine이 등록되지 않았습니다"
            }
        
        lazy_model = model_manager._models["ocr_vision_engine"]
        
        if lazy_model._instance is None:
            return {
                "status": "idle",
                "message": "OCR Vision Engine이 대기 중입니다 (로드되지 않음)"
            }
        
        ocr_manager = lazy_model._instance
        is_loaded = ocr_manager.is_loaded()
        
        return {
            "status": "loaded" if is_loaded else "error",
            "message": "OCR Vision Engine이 로드되어 있습니다" if is_loaded else "엔진 오류",
            "model": ocr_manager.get_config()["model"],
            "ref_count": lazy_model._ref_count
        }
        
    except Exception as e:
        logger.error(f"OCR 상태 확인 중 오류: {e}")
        return {
            "status": "error",
            "message": f"상태 확인 실패: {str(e)}"
        }
