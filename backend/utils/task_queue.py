import asyncio
import subprocess
import logging
import time
import os
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
            started_at = self.current_task.get("started_at")
            elapsed_seconds = None
            if started_at:
                try:
                    elapsed_seconds = int((datetime.now() - started_at).total_seconds())
                except Exception:
                    elapsed_seconds = None
            return {
                "task_id": task_id,
                "status": "processing",
                "wait_count": 0,
                "message": "현재 GPU에서 처리 중입니다.",
                "started_at": started_at.isoformat() if started_at else None,
                "elapsed_seconds": elapsed_seconds,
                "stdout": self.current_task.get("stdout"),
                "stderr": self.current_task.get("stderr"),
            }

        # 큐에서 대기 중인 작업 확인
        for i, task in enumerate(queue_list):
            if task["task_id"] == task_id:
                wait_count = i + 1
                status = "pending"
                break
        
        if status == "pending":
            # pending 상태에서는 아직 subprocess가 시작되지 않아 보통 출력이 없지만,
            # 혹시라도 task 객체에 출력이 누적된 케이스가 있으면 함께 노출
            pending_task = None
            for task in queue_list:
                if task.get("task_id") == task_id:
                    pending_task = task
                    break
            return {
                "task_id": task_id,
                "status": "pending",
                "wait_count": wait_count,
                "message": f"대기 순번 {wait_count}번입니다. 잠시만 기다려 주세요.",
                "stdout": (pending_task or {}).get("stdout"),
                "stderr": (pending_task or {}).get("stderr"),
            }
        
        # 히스토리에서 완료/실패 여부 확인
        for task in reversed(self.task_history):
            if task["task_id"] == task_id:
                return {
                    "task_id": task_id,
                    "status": task["status"],
                    "wait_count": 0,
                    "message": "처리가 완료되었거나 실패했습니다.",
                    "error": task.get("error"),
                    "stdout": task.get("stdout"),
                    "stderr": task.get("stderr"),
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
            task["stdout"] = ""
            task["stderr"] = ""
            
            task_id = task["task_id"]
            cmd = task["command"]
            
            logger.info(f"[{task_id}] Starting task: {' '.join(cmd)}")

            try:
                # 타임아웃 설정 (예: 20분)
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

                async def _drain_stream(stream, key: str):
                    if stream is None:
                        return
                    max_chars = 20000
                    try:
                        # NOTE: readline()은 출력이 '\n'으로 끝나지 않으면 업데이트가
                        # 멈춘 것처럼 보일 수 있음(tqdm/progress bar/일부 라이브러리 출력).
                        # chunk read로 바꾸어 실시간 tail을 보장.
                        while True:
                            chunk = await stream.read(1024)
                            if not chunk:
                                break
                            try:
                                decoded = chunk.decode(errors="replace")
                            except Exception:
                                decoded = str(chunk)
                            current = task.get(key) or ""
                            current += decoded
                            if len(current) > max_chars:
                                current = current[-max_chars:]
                            task[key] = current
                    except Exception:
                        return

                stdout_task = asyncio.create_task(_drain_stream(process.stdout, "stdout"))
                stderr_task = asyncio.create_task(_drain_stream(process.stderr, "stderr"))
                
                try:
                    await asyncio.wait_for(process.wait(), timeout=1200)

                    # 남아있는 출력 drain 완료 대기
                    try:
                        await asyncio.wait_for(stdout_task, timeout=5)
                    except Exception:
                        stdout_task.cancel()
                    try:
                        await asyncio.wait_for(stderr_task, timeout=5)
                    except Exception:
                        stderr_task.cancel()

                    # 최종적으로 strip (processing 중 tail 제공을 위해 본문은 유지되었고, 완료 시 깔끔하게 정리)
                    if isinstance(task.get("stdout"), str):
                        task["stdout"] = task["stdout"].strip()
                    if isinstance(task.get("stderr"), str):
                        task["stderr"] = task["stderr"].strip()

                    # 성공이어도 출력이 있으면 로그로 남겨 원인 파악을 쉽게 함
                    if task.get("stdout"):
                        logger.info(
                            f"[{task_id}] Subprocess stdout (first 2000 chars): {task['stdout'][:2000]}"
                        )
                    if task.get("stderr"):
                        logger.warning(
                            f"[{task_id}] Subprocess stderr (first 2000 chars): {task['stderr'][:2000]}"
                        )
                    
                    if process.returncode == 0:
                        task["status"] = "completed"
                        logger.info(f"[{task_id}] Task completed successfully.")
                    else:
                        task["status"] = "failed"
                        full_err = task.get("stderr", "")
                        summary = ""
                        if full_err:
                            summary = full_err.splitlines()[0].strip() if full_err.splitlines() else full_err.strip()
                            if len(summary) > 500:
                                summary = summary[:500]
                        task["error"] = summary or f"Task failed with return code {process.returncode}"
                        logger.error(f"[{task_id}] Task failed with return code {process.returncode}: {task['error']}")
                
                except asyncio.TimeoutError:
                    process.kill()
                    stdout_task.cancel()
                    stderr_task.cancel()
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
