import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class LazyModel:
    """단일 모델 리소스를 지연 로딩/해제하는 헬퍼."""

    def __init__(self,
                 name: str,
                 build_fn: Callable[[], Any],
                 cleanup_fn: Optional[Callable[[Any], None]] = None,
                 idle_timeout: float = 60.0):
        self._name = name
        self._build_fn = build_fn
        self._cleanup_fn = cleanup_fn
        self._idle_timeout = idle_timeout

        self._lock = threading.RLock()
        self._instance: Any = None
        self._ref_count = 0
        self._idle_timer: Optional[threading.Timer] = None

    def acquire(self) -> Any:
        with self._lock:
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
            if self._instance is None:
                logger.info("LazyModel[%s] 최초 로딩 시작", self._name)
                self._instance = self._build_fn()
                logger.info("LazyModel[%s] 로딩 완료", self._name)
            self._ref_count += 1
            return self._instance

    def release(self) -> None:
        with self._lock:
            if self._ref_count == 0:
                return

            self._ref_count -= 1
            if self._ref_count == 0:
                self._schedule_idle_unload()

    def force_unload(self) -> None:
        with self._lock:
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
            self._unload_locked()

    def _schedule_idle_unload(self) -> None:
        if self._idle_timeout <= 0:
            self._unload_locked()
            return

        if self._idle_timer:
            self._idle_timer.cancel()

        self._idle_timer = threading.Timer(self._idle_timeout, self._idle_timeout_handler)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _idle_timeout_handler(self) -> None:
        with self._lock:
            if self._ref_count == 0:
                self._unload_locked()
            if self._idle_timer:
                self._idle_timer = None

    def _unload_locked(self) -> None:
        if self._instance is None:
            return

        logger.info("LazyModel[%s] 언로드 진행", self._name)
        if self._cleanup_fn:
            try:
                self._cleanup_fn(self._instance)
            except Exception:
                logger.exception("LazyModel[%s] cleanup 실패", self._name)

        self._instance = None
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None


class LazyModelManager:
    """모델 리소스의 lazy load/unload를 관리하는 매니저."""

    def __init__(self):
        self._models: Dict[str, LazyModel] = {}
        self._lock = threading.Lock()

    def register(self,
                 name: str,
                 builder: Callable[[], Any],
                 cleanup: Optional[Callable[[Any], None]] = None,
                 idle_timeout: float = 60.0) -> None:
        with self._lock:
            if name in self._models:
                raise ValueError(f"이미 등록된 모델입니다: {name}")
            self._models[name] = LazyModel(name, builder, cleanup, idle_timeout)
            logger.info("LazyModelManager에 '%s' 등록 완료", name)

    def acquire(self, name: str) -> Any:
        return self._get_model(name).acquire()

    def release(self, name: str) -> None:
        self._get_model(name).release()

    @contextmanager
    def session(self, name: str):
        model = self._get_model(name)
        instance = model.acquire()
        try:
            yield instance
        finally:
            model.release()

    def shutdown_all(self) -> None:
        with self._lock:
            for model in self._models.values():
                model.force_unload()

    def _get_model(self, name: str) -> LazyModel:
        with self._lock:
            if name not in self._models:
                raise KeyError(f"등록되지 않은 모델입니다: {name}")
            return self._models[name]
