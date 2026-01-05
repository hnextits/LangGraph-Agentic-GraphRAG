import asyncio
import subprocess
import logging
import time
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger("task_queue")
logger.setLevel(logging.INFO)

class GPUTaskQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.worker_task = None
        self.current_task = None
        self.task_history: List[Dict[str, Any]] = []
        self.max_history = 50

    async def add_task(self, task_info: Dict[str, Any]):
        """
        task_info structure:
        {
            "task_id": str,
            "session_id": str,
            "command": List[str],
            "created_at": datetime,
            "status": str (pending/processing/completed/failed)
        }
        """
        task_info["status"] = "pending"
        task_info["queued_at"] = datetime.now()
        await self.queue.put(task_info)
        self.task_history.append(task_info)
        if len(self.task_history) > self.max_history:
            self.task_history.pop(0)
        
        logger.info(f"Task {task_info['task_id']} added to queue. Queue size: {self.queue.qsize()}")
        return self.get_queue_status(task_info["task_id"])

    def get_queue_status(self, task_id: str) -> Dict[str, Any]:
        """특정 작업의 대기 순번 및 상태 조회"""
        queue_list = list(self.queue._queue)
        wait_count = 0
        status = "unknown"
        
        # 현재 실행 중인 작업 확인
        if self.current_task and self.current_task["task_id"] == task_id:
            return {
                "task_id": task_id,
                "status": "processing",
                "wait_count": 0,
                "message": "현재 GPU에서 처리 중입니다."
            }

        # 큐에서 대기 중인 작업 확인
        for i, task in enumerate(queue_list):
            if task["task_id"] == task_id:
                wait_count = i + 1
                status = "pending"
                break
        
        if status == "pending":
            return {
                "task_id": task_id,
                "status": "pending",
                "wait_count": wait_count,
                "message": f"대기 순번 {wait_count}번입니다. 잠시만 기다려 주세요."
            }
        
        # 히스토리에서 완료/실패 여부 확인
        for task in reversed(self.task_history):
            if task["task_id"] == task_id:
                return {
                    "task_id": task_id,
                    "status": task["status"],
                    "wait_count": 0,
                    "message": "처리가 완료되었거나 실패했습니다.",
                    "error": task.get("error")
                }

        return {"task_id": task_id, "status": "not_found", "wait_count": 0}

    async def start_worker(self):
        if self.worker_task is None:
            self.worker_task = asyncio.create_task(self._worker())
            logger.info("GPU Task Queue Worker started.")

    async def _worker(self):
        while True:
            task = await self.queue.get()
            self.current_task = task
            task["status"] = "processing"
            task["started_at"] = datetime.now()
            
            task_id = task["task_id"]
            cmd = task["command"]
            
            logger.info(f"[{task_id}] Starting task: {' '.join(cmd)}")
            
            try:
                # 타임아웃 설정 (예: 20분)
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=1200)
                    
                    if process.returncode == 0:
                        task["status"] = "completed"
                        logger.info(f"[{task_id}] Task completed successfully.")
                    else:
                        task["status"] = "failed"
                        error_msg = stderr.decode().strip()
                        task["error"] = error_msg
                        logger.error(f"[{task_id}] Task failed with return code {process.returncode}: {error_msg}")
                
                except asyncio.TimeoutError:
                    process.kill()
                    task["status"] = "failed"
                    task["error"] = "Timeout: 작업 시간이 20분을 초과하여 중단되었습니다."
                    logger.error(f"[{task_id}] Task timed out and killed.")
            
            except Exception as e:
                task["status"] = "failed"
                task["error"] = str(e)
                logger.error(f"[{task_id}] Unexpected error during task execution: {e}")
            
            finally:
                task["finished_at"] = datetime.now()
                self.current_task = None
                self.queue.task_done()

# 싱글톤 인스턴스
gpu_task_queue = GPUTaskQueue()
