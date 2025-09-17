from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import logging

# 로거 설정
logger = logging.getLogger(__name__)

# API 라우터 설정
router = APIRouter()

# 전역 취소 상태 관리
cancel_state = {
    "cancelled_processes": set(),  # 취소된 프로세스 ID 집합
}

class CancelRequest(BaseModel):
    process_ids: List[str]  # 취소할 프로세스 ID 목록

class CancelResponse(BaseModel):
    cancelled_processes: list
    message: str

@router.get("/cancel/status", response_model=CancelResponse)
async def get_cancel_status():
    """
    현재 취소된 프로세스 목록을 반환합니다.
    """
    return CancelResponse(
        cancelled_processes=list(cancel_state["cancelled_processes"]),
        message="취소된 프로세스 목록입니다."
    )

@router.post("/cancel", response_model=CancelResponse)
async def cancel_processes(request: CancelRequest):
    """
    지정된 프로세스를 취소합니다.
    취소된 프로세스는 더 이상 실행되지 않습니다.
    """
    global cancel_state
    
    if not request.process_ids:
        raise HTTPException(status_code=400, detail="취소할 프로세스 ID 목록이 필요합니다.")
    
    for process_id in request.process_ids:
        cancel_state["cancelled_processes"].add(process_id)
    
    logger.info(f"프로세스 취소됨: {request.process_ids}")
    
    return CancelResponse(
        cancelled_processes=list(cancel_state["cancelled_processes"]),
        message=f"{len(request.process_ids)}개의 프로세스가 취소되었습니다."
    )

def is_cancelled(process_id: str) -> bool:
    """
    특정 프로세스가 취소되었는지 확인합니다.
    """
    return process_id in cancel_state["cancelled_processes"]

# --- 이 부분이 추가되었습니다 ---
def cancel_task(task_id: str):
    """
    특정 task_id를 취소 상태로 설정합니다.
    routes.py에서 직접 호출하기 위한 함수입니다.
    """
    global cancel_state
    cancel_state["cancelled_processes"].add(task_id)
    logger.info(f"Task cancellation requested via function call: {task_id}")