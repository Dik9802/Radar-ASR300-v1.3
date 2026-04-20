# npu_queue_manager.py
"""
Gestor de cola para el endpoint /npu con workers consumidores.
Mismo patrón que lpr_queue_manager: el handler HTTP encola y responde
inmediatamente; workers en paralelo decodifican base64, guardan imágenes
y publican la placa al display.
"""
from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from .decoder import procesar_payload_npu
    NPU_DECODER_AVAILABLE = True
except ImportError:
    NPU_DECODER_AVAILABLE = False
    procesar_payload_npu = None

try:
    from shared.config_loader import read_ini, get_bool, get_int
    _config = read_ini(apply_env_overrides=True)
    NPU_QUEUE_WORKERS = get_int(_config, "NPU_QUEUE", "WORKERS", 2)
    NPU_QUEUE_MAX_SIZE = get_int(_config, "NPU_QUEUE", "MAX_SIZE", 100)
    ENABLE_NPU_QUEUE = get_bool(_config, "NPU_QUEUE", "ENABLED", True)
    print(f"[NPU_QUEUE] Config - Workers: {NPU_QUEUE_WORKERS}, Max Size: {NPU_QUEUE_MAX_SIZE}, Enabled: {ENABLE_NPU_QUEUE}")
except Exception as e:
    print(f"[NPU_QUEUE] Error cargando config.ini, usando defaults: {e}")
    NPU_QUEUE_WORKERS = 2
    NPU_QUEUE_MAX_SIZE = 100
    ENABLE_NPU_QUEUE = True


def _ts_str() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class NPUQueueManager:
    def __init__(self, num_workers: int = NPU_QUEUE_WORKERS, max_size: int = NPU_QUEUE_MAX_SIZE):
        self.task_queue: queue.Queue = queue.Queue(maxsize=max_size)
        self.num_workers = num_workers
        self.workers: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._active = False
        self.stats = {
            "queued": 0,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "rejected": 0,
            "queue_size": 0,
        }
        self._stats_lock = threading.Lock()

    def start(self):
        if not NPU_DECODER_AVAILABLE:
            print("[NPU_QUEUE] ERROR: NPU decoder no disponible")
            return
        if self._active:
            print("[NPU_QUEUE] Ya está ejecutándose")
            return
        self._stop_event.clear()
        self._active = True
        for i in range(self.num_workers):
            t = threading.Thread(
                target=self._worker_main,
                name=f"NPUWorker-{i}",
                daemon=True,
            )
            self.workers.append(t)
            t.start()
        print(f"[NPU_QUEUE] Iniciados {self.num_workers} worker(s)")

    def stop(self, wait: bool = True):
        if not self._active:
            return
        self._stop_event.set()
        for _ in range(len(self.workers)):
            try:
                self.task_queue.put(None, timeout=1.0)
            except queue.Full:
                pass
        if wait:
            for t in self.workers:
                try:
                    t.join(timeout=5.0)
                except Exception:
                    pass
        self.workers.clear()
        self._active = False
        print("[NPU_QUEUE] Workers detenidos")

    def enqueue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._active:
            if NPU_DECODER_AVAILABLE:
                return procesar_payload_npu(payload)
            return {"status": "ERROR", "message": "NPU queue no disponible"}
        try:
            self.task_queue.put_nowait(payload)
            with self._stats_lock:
                self.stats["queued"] += 1
                self.stats["queue_size"] = self.task_queue.qsize()
            print(f"[{_ts_str()}] [NPU_QUEUE] Placa encolada (cola={self.task_queue.qsize()})")
            return {
                "status": "QUEUED",
                "plate": (payload.get("plate") or "").strip(),
                "queue_size": self.task_queue.qsize(),
            }
        except queue.Full:
            with self._stats_lock:
                self.stats["rejected"] += 1
            print(f"[{_ts_str()}] [NPU_QUEUE] Cola llena, procesando directo (fallback)")
            if NPU_DECODER_AVAILABLE:
                return procesar_payload_npu(payload)
            return {"status": "ERROR", "message": "Cola llena y decoder no disponible"}

    def _worker_main(self):
        name = threading.current_thread().name
        print(f"[{_ts_str()}] [NPU_QUEUE] {name} iniciado")
        while not self._stop_event.is_set():
            try:
                try:
                    payload = self.task_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                if payload is None:
                    break
                try:
                    print(f"[{_ts_str()}] [NPU_QUEUE] {name} procesando placa...")
                    result = procesar_payload_npu(payload)
                    with self._stats_lock:
                        self.stats["processed"] += 1
                        self.stats["queue_size"] = self.task_queue.qsize()
                        if result.get("status") == "OK":
                            self.stats["success"] += 1
                        else:
                            self.stats["failed"] += 1
                    print(f"[{_ts_str()}] [NPU_QUEUE] {name} completado: {result.get('status')}")
                except Exception as e:
                    print(f"[{_ts_str()}] [NPU_QUEUE] {name} ERROR: {e}")
                    import traceback
                    traceback.print_exc()
                    with self._stats_lock:
                        self.stats["processed"] += 1
                        self.stats["failed"] += 1
                        self.stats["queue_size"] = self.task_queue.qsize()
                finally:
                    self.task_queue.task_done()
            except Exception as e:
                print(f"[{_ts_str()}] [NPU_QUEUE] {name} excepción en bucle: {e}")
                time.sleep(0.1)
        print(f"[{_ts_str()}] [NPU_QUEUE] {name} detenido")

    def get_stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            return {
                "active": self._active,
                "workers": len(self.workers),
                "queue_size": self.task_queue.qsize(),
                **self.stats,
            }


_npu_queue_manager: Optional[NPUQueueManager] = None


def start_npu_queue_manager(num_workers: Optional[int] = None,
                            max_size: Optional[int] = None) -> Optional[NPUQueueManager]:
    global _npu_queue_manager
    if not ENABLE_NPU_QUEUE:
        print("[NPU_QUEUE] Deshabilitado por configuración")
        return None
    if not NPU_DECODER_AVAILABLE:
        print("[NPU_QUEUE] ERROR: NPU decoder no disponible")
        return None
    if _npu_queue_manager is None:
        _npu_queue_manager = NPUQueueManager(
            num_workers=num_workers or NPU_QUEUE_WORKERS,
            max_size=max_size or NPU_QUEUE_MAX_SIZE,
        )
    _npu_queue_manager.start()
    return _npu_queue_manager


def stop_npu_queue_manager():
    global _npu_queue_manager
    if _npu_queue_manager:
        _npu_queue_manager.stop()
        _npu_queue_manager = None


def enqueue_npu_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    global _npu_queue_manager
    if _npu_queue_manager and _npu_queue_manager._active:
        return _npu_queue_manager.enqueue(payload)
    if NPU_DECODER_AVAILABLE:
        return procesar_payload_npu(payload)
    return {"status": "ERROR", "message": "NPU queue no disponible"}


def get_npu_queue_stats() -> Dict[str, Any]:
    global _npu_queue_manager
    if _npu_queue_manager:
        return _npu_queue_manager.get_stats()
    return {"active": False, "workers": 0, "queue_size": 0}
