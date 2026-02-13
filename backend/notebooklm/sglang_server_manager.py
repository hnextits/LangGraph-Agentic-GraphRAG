#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
SGLang 서버 프로세스 관리 모듈 (LazyLoading 방식).

모든 SGLang 서버(생성기, 임베딩, 리랭커 등)를 필요 시에만 기동하고,
유휴 시간이 지나면 자동으로 종료하여 GPU 메모리를 해제합니다.

사용법:
    # 서버 설정 등록 (main.py lifespan에서)
    sglang_manager.register_server("generator", model_path=..., port=30000, device="cuda:0")

    # 서버 사용 (각 컴포넌트에서) - 필요 시 자동 기동
    sglang_manager.acquire("generator")   # 서버 기동 + 타이머 리셋
    ...  # API 호출
    sglang_manager.release("generator")   # 유휴 타이머 시작
"""

import os
import sys
import time
import logging
import subprocess
import threading
import requests
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class _ServerEntry:
    """개별 SGLang 서버의 상태를 관리합니다."""

    def __init__(
        self,
        name: str,
        model_path: str,
        port: int,
        device: str = "cuda:0",
        extra_args: Optional[list] = None,
        idle_timeout: int = 300,
        wait_timeout: int = 300,
        mem_fraction: Optional[float] = None,
    ):
        self.name = name
        self.model_path = model_path
        self.port = port
        self.device = device
        self.extra_args = extra_args or []
        self.idle_timeout = idle_timeout
        self.wait_timeout = wait_timeout
        self.mem_fraction = mem_fraction

        self.process: Optional[subprocess.Popen] = None
        self.active_users = 0
        self.last_release_time: Optional[float] = None
        self.lock = threading.Lock()


class SGLangServerManager:
    """
    SGLang 서버 프로세스들을 LazyLoading 방식으로 관리합니다.

    - register_server(): 서버 설정만 등록 (기동하지 않음)
    - acquire(): 서버가 필요할 때 호출 → 미기동이면 자동 기동
    - release(): 사용 완료 시 호출 → 유휴 타이머 시작
    - 유휴 타이머 만료 시 자동 종료하여 GPU 메모리 해제
    """

    def __init__(self):
        self._servers: Dict[str, _ServerEntry] = {}
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # 서버 등록
    # ------------------------------------------------------------------
    def register_server(
        self,
        name: str,
        model_path: str,
        port: int,
        device: str = "cuda:0",
        extra_args: Optional[list] = None,
        idle_timeout: int = 300,
        wait_timeout: int = 300,
        mem_fraction: Optional[float] = None,
    ):
        """
        서버 설정을 등록합니다. 실제 기동은 acquire() 시 수행됩니다.

        Args:
            name: 서버 식별 이름
            model_path: HuggingFace 모델 경로
            port: 서버 포트
            device: CUDA 디바이스
            extra_args: 추가 CLI 인자
            idle_timeout: 유휴 시 자동 종료까지의 시간 (초)
            wait_timeout: 서버 기동 대기 시간 (초)
            mem_fraction: GPU 메모리 할당 비율 (0.0~1.0, None이면 SGLang 기본값)
        """
        entry = _ServerEntry(
            name=name,
            model_path=model_path,
            port=port,
            device=device,
            extra_args=extra_args,
            idle_timeout=idle_timeout,
            wait_timeout=wait_timeout,
            mem_fraction=mem_fraction,
        )
        self._servers[name] = entry
        logger.info(
            f"SGLang 서버 '{name}' 등록 완료 (LazyLoading, "
            f"idle_timeout={idle_timeout}s, port={port}, device={device})"
        )

    # ------------------------------------------------------------------
    # acquire / release
    # ------------------------------------------------------------------
    def acquire(self, name: str) -> bool:
        """
        서버를 사용하기 전에 호출합니다.
        서버가 미기동이면 자동으로 기동합니다.

        Returns:
            서버가 정상 사용 가능하면 True
        """
        entry = self._servers.get(name)
        if entry is None:
            logger.error(f"SGLang 서버 '{name}'이 등록되지 않았습니다.")
            return False

        with entry.lock:
            entry.active_users += 1
            entry.last_release_time = None  # 유휴 타이머 취소

            if self._is_process_alive(entry):
                logger.debug(f"SGLang 서버 '{name}' 이미 실행 중 (users={entry.active_users})")
                return True

            # 서버 기동
            logger.info(f"SGLang 서버 '{name}' LazyLoading 기동 시작...")
            success = self._launch(entry)
            if not success:
                entry.active_users -= 1
            return success

    def release(self, name: str):
        """
        서버 사용 완료 시 호출합니다.
        active_users가 0이 되면 유휴 타이머를 시작합니다.
        """
        entry = self._servers.get(name)
        if entry is None:
            return

        with entry.lock:
            entry.active_users = max(0, entry.active_users - 1)
            if entry.active_users == 0:
                entry.last_release_time = time.time()
                logger.info(
                    f"SGLang 서버 '{name}' 유휴 상태 진입 "
                    f"(idle_timeout={entry.idle_timeout}s)"
                )

        # 클린업 스레드가 없으면 시작
        self._ensure_cleanup_thread()

    def touch(self, name: str):
        """
        서버의 idle timer를 리셋합니다.
        API 호출 시마다 호출하여 서버가 사용 중임을 알립니다.
        acquire/release 쌍 없이도 idle timeout을 연장할 수 있습니다.
        """
        entry = self._servers.get(name)
        if entry is None:
            return
        with entry.lock:
            if entry.last_release_time is not None:
                entry.last_release_time = time.time()

    # ------------------------------------------------------------------
    # 서버 기동 / 종료
    # ------------------------------------------------------------------
    def _launch(self, entry: _ServerEntry) -> bool:
        """서버를 subprocess로 기동합니다. (lock 내부에서 호출)"""
        gpu_id = entry.device.replace("cuda:", "") if entry.device.startswith("cuda:") else "0"
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = gpu_id

        cmd = [
            sys.executable, "-m", "sglang.launch_server",
            "--model-path", entry.model_path,
            "--port", str(entry.port),
            "--host", "0.0.0.0",
        ]
        if entry.mem_fraction is not None:
            cmd.extend(["--mem-fraction-static", str(entry.mem_fraction)])
        cmd.extend(entry.extra_args)

        logger.info(f"SGLang 서버 '{entry.name}' 기동: GPU={gpu_id}, Port={entry.port}")

        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            entry.process = proc

            endpoint = f"http://localhost:{entry.port}"
            if self._wait_for_server(endpoint, timeout=entry.wait_timeout):
                logger.info(
                    f"SGLang 서버 '{entry.name}' 준비 완료 "
                    f"(PID={proc.pid}, Port={entry.port})"
                )
                return True
            else:
                # 타임아웃 시 프로세스 로그 캡처
                proc_log = ""
                try:
                    if proc.stdout and proc.stdout.readable():
                        import select
                        while select.select([proc.stdout], [], [], 0)[0]:
                            line = proc.stdout.readline()
                            if not line:
                                break
                            proc_log += line
                except Exception:
                    pass
                logger.error(
                    f"SGLang 서버 '{entry.name}' 타임아웃 ({entry.wait_timeout}s)"
                )
                if proc_log:
                    # 마지막 2000자만 출력
                    logger.error(
                        f"SGLang 서버 '{entry.name}' 프로세스 로그 (마지막 2000자):\n"
                        f"{proc_log[-2000:]}"
                    )
                self._kill(entry)
                return False

        except Exception as e:
            logger.error(f"SGLang 서버 '{entry.name}' 기동 실패: {e}")
            return False

    def _kill(self, entry: _ServerEntry):
        """프로세스를 안전하게 종료합니다."""
        proc = entry.process
        if proc is None:
            return
        if proc.poll() is not None:
            entry.process = None
            return

        logger.info(f"SGLang 서버 '{entry.name}' 종료 중 (PID={proc.pid})...")
        try:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning(f"SGLang 서버 '{entry.name}' SIGTERM 타임아웃, SIGKILL")
                proc.kill()
                proc.wait(timeout=5)
        except Exception as e:
            logger.error(f"SGLang 서버 '{entry.name}' 종료 오류: {e}")
        finally:
            entry.process = None
            logger.info(f"SGLang 서버 '{entry.name}' 종료 완료 (GPU 메모리 해제)")

    def _wait_for_server(self, endpoint: str, timeout: int = 300) -> bool:
        """서버가 /health에 응답할 때까지 대기합니다."""
        health_url = f"{endpoint}/health"
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = requests.get(health_url, timeout=3)
                if resp.status_code == 200:
                    return True
            except (requests.ConnectionError, requests.Timeout):
                pass
            time.sleep(2)
        return False

    def _is_process_alive(self, entry: _ServerEntry) -> bool:
        return entry.process is not None and entry.process.poll() is None

    # ------------------------------------------------------------------
    # 유휴 서버 자동 종료 스레드
    # ------------------------------------------------------------------
    def _ensure_cleanup_thread(self):
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            return
        self._stop_event.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="sglang-cleanup"
        )
        self._cleanup_thread.start()

    def _cleanup_loop(self):
        """주기적으로 유휴 서버를 확인하고 종료합니다."""
        while not self._stop_event.is_set():
            now = time.time()
            for entry in self._servers.values():
                with entry.lock:
                    if (
                        entry.active_users == 0
                        and entry.last_release_time is not None
                        and self._is_process_alive(entry)
                        and (now - entry.last_release_time) >= entry.idle_timeout
                    ):
                        logger.info(
                            f"SGLang 서버 '{entry.name}' 유휴 타임아웃 "
                            f"({entry.idle_timeout}s) → 자동 종료"
                        )
                        self._kill(entry)
                        entry.last_release_time = None

            # 모든 서버가 종료되었으면 스레드 종료
            any_alive = any(
                self._is_process_alive(e) for e in self._servers.values()
            )
            if not any_alive:
                break

            self._stop_event.wait(timeout=10)  # 10초마다 체크

    # ------------------------------------------------------------------
    # 전체 종료 / 상태 확인
    # ------------------------------------------------------------------
    def shutdown_all(self):
        """모든 SGLang 서버를 즉시 종료합니다."""
        self._stop_event.set()
        logger.info("모든 SGLang 서버를 종료합니다...")
        for entry in self._servers.values():
            with entry.lock:
                self._kill(entry)
        logger.info("모든 SGLang 서버 종료 완료")

    def shutdown_server(self, name: str):
        """특정 서버를 즉시 종료합니다."""
        entry = self._servers.get(name)
        if entry:
            with entry.lock:
                self._kill(entry)

    def is_running(self, name: str) -> bool:
        entry = self._servers.get(name)
        return entry is not None and self._is_process_alive(entry)

    def get_status(self) -> Dict[str, dict]:
        status = {}
        for name, entry in self._servers.items():
            alive = self._is_process_alive(entry)
            status[name] = {
                "running": alive,
                "pid": entry.process.pid if alive else None,
                "port": entry.port,
                "model": entry.model_path,
                "device": entry.device,
                "active_users": entry.active_users,
                "idle_timeout": entry.idle_timeout,
            }
        return status


# 전역 싱글톤 인스턴스
sglang_manager = SGLangServerManager()
