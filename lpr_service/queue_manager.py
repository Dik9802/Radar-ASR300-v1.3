# lpr_queue_manager.py
"""
Gestor de cola para procesamiento de placas LPR con workers consumidores.
Permite procesar múltiples placas concurrentemente sin bloquear el servidor HTTP.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

# Importar el decoder
try:
    from .decoder import _DECODER
    LPR_DECODER_AVAILABLE = True
except ImportError:
    LPR_DECODER_AVAILABLE = False
    _DECODER = None

# Configuración desde config.ini
try:
    from shared.config_loader import read_ini, get_int, get_bool
    config = read_ini(apply_env_overrides=True)
    
    LPR_QUEUE_WORKERS = get_int(config, "LPR_QUEUE", "WORKERS", 3)
    ENABLE_LPR_QUEUE = get_bool(config, "LPR_QUEUE", "ENABLED", True)
    LPR_QUEUE_MAX_SIZE = get_int(config, "LPR_QUEUE", "MAX_SIZE", 100)
    
    print(f"[LPR_QUEUE] Configuración cargada - Workers: {LPR_QUEUE_WORKERS}, Max Size: {LPR_QUEUE_MAX_SIZE}")
except Exception as e:
    print(f"[LPR_QUEUE] Error cargando config.ini, usando valores por defecto: {e}")
    LPR_QUEUE_WORKERS = 3
    ENABLE_LPR_QUEUE = True
    LPR_QUEUE_MAX_SIZE = 100

def _ts_str() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

class LPRQueueManager:
    """
    Gestor de cola para procesamiento de placas LPR.
    Encola eventos de placas y los procesa con workers en paralelo.
    """
    def __init__(self, num_workers: int = LPR_QUEUE_WORKERS, max_size: int = LPR_QUEUE_MAX_SIZE):
        self.task_queue = queue.Queue(maxsize=max_size)
        self.num_workers = num_workers
        self.workers: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._active = False
        self.stats = {
            'queued': 0,
            'processed': 0,
            'success': 0,
            'failed': 0,
            'queue_size': 0,
            'rejected': 0  # Rechazadas por cola llena
        }
        self._stats_lock = threading.Lock()
    
    def start(self):
        """Inicia los workers de procesamiento"""
        if not LPR_DECODER_AVAILABLE:
            print("[LPR_QUEUE] ERROR: LPR Decoder no disponible")
            return
        
        if self._active:
            print("[LPR_QUEUE] Ya está ejecutándose")
            return
        
        self._stop_event.clear()
        self._active = True
        
        for i in range(self.num_workers):
            t = threading.Thread(
                target=self._worker_main, 
                name=f"LPRWorker-{i}", 
                daemon=True
            )
            self.workers.append(t)
            t.start()
        
        print(f"[LPR_QUEUE] Iniciados {self.num_workers} worker(s) para procesamiento de placas")
    
    def stop(self, wait: bool = True):
        """Detiene los workers"""
        if not self._active:
            return
        
        self._stop_event.set()
        # Enviar señales de parada a todos los workers
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
        print("[LPR_QUEUE] Workers detenidos")
    
    def enqueue_plate(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Encola un evento de placa para procesamiento asíncrono.
        Retorna inmediatamente con un resultado que indica si se encoló correctamente.
        """
        if not self._active:
            # Si la cola no está activa, procesar directamente (modo síncrono)
            if LPR_DECODER_AVAILABLE:
                return _DECODER.handle_event(event)
            else:
                return {
                    "status": "ERROR",
                    "ok": False,
                    "message": "LPR Queue no disponible"
                }
        
        try:
            # Intentar encolar (no bloqueante si la cola está llena)
            self.task_queue.put_nowait(event)
            
            with self._stats_lock:
                self.stats['queued'] += 1
                self.stats['queue_size'] = self.task_queue.qsize()
            
            print(f"[{_ts_str()}] [LPR_QUEUE] Placa encolada (cola={self.task_queue.qsize()})")
            
            return {
                "status": "QUEUED",
                "ok": True,
                "message": "Placa encolada para procesamiento",
                "queue_size": self.task_queue.qsize()
            }
        
        except queue.Full:
            # Cola llena, rechazar
            with self._stats_lock:
                self.stats['rejected'] += 1
            
            print(f"[{_ts_str()}] [LPR_QUEUE] ERROR: Cola llena, rechazando placa")
            
            # Intentar procesar directamente como fallback
            if LPR_DECODER_AVAILABLE:
                print(f"[{_ts_str()}] [LPR_QUEUE] Procesando directamente (fallback)")
                return _DECODER.handle_event(event)
            else:
                return {
                    "status": "ERROR",
                    "ok": False,
                    "message": "Cola llena y decoder no disponible"
                }
    
    def _worker_main(self):
        """Bucle principal del worker que procesa placas de la cola"""
        worker_name = threading.current_thread().name
        print(f"[{_ts_str()}] [LPR_QUEUE] {worker_name} iniciado")
        
        while not self._stop_event.is_set():
            try:
                # Obtener tarea de la cola (con timeout para poder verificar stop_event)
                try:
                    event = self.task_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Señal de parada
                if event is None:
                    break
                
                # Procesar la placa
                try:
                    print(f"[{_ts_str()}] [LPR_QUEUE] {worker_name} procesando placa...")
                    result = _DECODER.handle_event(event)
                    
                    with self._stats_lock:
                        self.stats['processed'] += 1
                        self.stats['queue_size'] = self.task_queue.qsize()
                        
                        if result.get('ok', False):
                            self.stats['success'] += 1
                        else:
                            self.stats['failed'] += 1
                    
                    print(f"[{_ts_str()}] [LPR_QUEUE] {worker_name} completado: {result.get('status', 'UNKNOWN')}")
                
                except Exception as e:
                    print(f"[{_ts_str()}] [LPR_QUEUE] {worker_name} ERROR procesando placa: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    with self._stats_lock:
                        self.stats['processed'] += 1
                        self.stats['failed'] += 1
                        self.stats['queue_size'] = self.task_queue.qsize()
                
                finally:
                    # Marcar tarea como completada
                    self.task_queue.task_done()
            
            except Exception as e:
                print(f"[{_ts_str()}] [LPR_QUEUE] {worker_name} Error en bucle principal: {e}")
                time.sleep(0.1)
        
        print(f"[{_ts_str()}] [LPR_QUEUE] {worker_name} detenido")
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas de la cola"""
        with self._stats_lock:
            return {
                'active': self._active,
                'workers': len(self.workers),
                'queue_size': self.task_queue.qsize(),
                'queued': self.stats['queued'],
                'processed': self.stats['processed'],
                'success': self.stats['success'],
                'failed': self.stats['failed'],
                'rejected': self.stats['rejected']
            }

# Instancia global del queue manager
_lpr_queue_manager: Optional[LPRQueueManager] = None

def start_lpr_queue_manager(num_workers: int = None, max_size: int = None) -> LPRQueueManager:
    """Inicia el queue manager de LPR"""
    global _lpr_queue_manager
    
    if not ENABLE_LPR_QUEUE:
        print("[LPR_QUEUE] Deshabilitado por configuración")
        return None
    
    if not LPR_DECODER_AVAILABLE:
        print("[LPR_QUEUE] ERROR: LPR Decoder no disponible")
        return None
    
    if _lpr_queue_manager is None:
        num_workers = num_workers or LPR_QUEUE_WORKERS
        max_size = max_size or LPR_QUEUE_MAX_SIZE
        _lpr_queue_manager = LPRQueueManager(num_workers=num_workers, max_size=max_size)
    
    _lpr_queue_manager.start()
    return _lpr_queue_manager

def stop_lpr_queue_manager():
    """Detiene el queue manager de LPR"""
    global _lpr_queue_manager
    if _lpr_queue_manager:
        _lpr_queue_manager.stop()
        _lpr_queue_manager = None

def enqueue_plate_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Encola un evento de placa para procesamiento"""
    global _lpr_queue_manager
    if _lpr_queue_manager and _lpr_queue_manager._active:
        return _lpr_queue_manager.enqueue_plate(event)
    else:
        # Modo síncrono si la cola no está activa
        if LPR_DECODER_AVAILABLE:
            return _DECODER.handle_event(event)
        else:
            return {
                "status": "ERROR",
                "ok": False,
                "message": "LPR Queue no disponible"
            }

def get_lpr_queue_stats() -> Dict[str, Any]:
    """Obtiene estadísticas de la cola LPR"""
    global _lpr_queue_manager
    if _lpr_queue_manager:
        return _lpr_queue_manager.get_stats()
    else:
        return {
            'active': False,
            'workers': 0,
            'queue_size': 0
        }
