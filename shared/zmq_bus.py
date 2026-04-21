"""
zmq_bus.py — Bus de eventos entre servicios vía PyZMQ (patrón PUB/SUB).

Reemplazo drop-in de shared/shm_bus.py. Mantiene la misma API pública
(`EventBus(channel, role)`, `.publish()`, `.read()`, `.read_blocking()`,
`.close()`, `.unlink()`) para no tocar el código de los servicios.

Ventajas vs SHM:
  - Multi-productor nativo: 2 radar_service por accidente no corrompen nada.
  - Cola interna con HWM configurable: mensajes se acumulan hasta que el
    subscriber los drena, en vez de sobrescribir en ring buffer.
  - Desacople total: productor no necesita saber si hay consumers.
  - Transport flexible: tcp://127.0.0.1 hoy, tcp://otra_ip mañana.

Trade-offs vs SHM:
  - Latencia ~200-500 µs (vs ~15 µs). Invisible al usuario final.
  - Slow-joiner: si el consumer conecta tarde, pierde mensajes publicados antes.
  - Requiere libzmq + pyzmq (ya instalado).

Uso (idéntico a shm_bus):
    from shared.zmq_bus import EventBus, CHANNEL_RADAR
    bus = EventBus(CHANNEL_RADAR, role="producer")
    bus.publish({"kind": "speed", "speed": 45.0, "ts_ms": 1776...})

    bus = EventBus(CHANNEL_RADAR, role="consumer")
    while True:
        evt = bus.read_blocking()
        handle(evt)

Puertos configurables en config.ini sección [ZMQ]:
    radar_port = 5555
    lpr_port   = 5556
    npu_port   = 5557
    host       = 127.0.0.1
    rcv_hwm    = 1000
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import zmq


# ---------- Configuración ----------
try:
    from shared.config_loader import read_ini, get_str, get_int
    _cfg = read_ini(apply_env_overrides=True)
    ZMQ_HOST = get_str(_cfg, "ZMQ", "HOST", "127.0.0.1") or "127.0.0.1"
    ZMQ_RADAR_PORT = get_int(_cfg, "ZMQ", "RADAR_PORT", 5555) or 5555
    ZMQ_LPR_PORT = get_int(_cfg, "ZMQ", "LPR_PORT", 5556) or 5556
    ZMQ_NPU_PORT = get_int(_cfg, "ZMQ", "NPU_PORT", 5557) or 5557
    ZMQ_RCV_HWM = get_int(_cfg, "ZMQ", "RCV_HWM", 1000) or 1000
except Exception as _e:
    print(f"[ZMQ_BUS] Error cargando [ZMQ] del config, usando defaults: {_e}")
    ZMQ_HOST = "127.0.0.1"
    ZMQ_RADAR_PORT = 5555
    ZMQ_LPR_PORT = 5556
    ZMQ_NPU_PORT = 5557
    ZMQ_RCV_HWM = 1000


# ---------- Nombres de canales (compat con shm_bus) ----------
CHANNEL_RADAR = "radar"
CHANNEL_LPR = "lpr"
CHANNEL_NPU = "npu"


_CHANNEL_PORTS = {
    CHANNEL_RADAR: ZMQ_RADAR_PORT,
    CHANNEL_LPR: ZMQ_LPR_PORT,
    CHANNEL_NPU: ZMQ_NPU_PORT,
}


class BusClosed(Exception):
    """El bus se cerró explícitamente."""


class PayloadTooLarge(Exception):
    """Payload excede límite razonable (1 MB)."""


# Límite sano; ZMQ técnicamente permite mucho más.
_MAX_PAYLOAD_BYTES = 1_048_576  # 1 MB


# Una sola Context por proceso (patrón recomendado de pyzmq).
_ctx: Optional[zmq.Context] = None


def _get_ctx() -> zmq.Context:
    global _ctx
    if _ctx is None:
        _ctx = zmq.Context.instance()
    return _ctx


class EventBus:
    """Bus PUB/SUB. `role='producer'` hace bind, `role='consumer'` hace connect.

    Un solo EventBus por canal por proceso para mantener la simetría con la
    API de shm_bus.
    """

    def __init__(self, channel: str, role: str) -> None:
        if channel not in _CHANNEL_PORTS:
            raise ValueError(
                f"Canal desconocido: {channel!r}. "
                f"Usar uno de {list(_CHANNEL_PORTS.keys())}"
            )
        if role not in ("producer", "consumer"):
            raise ValueError(f"role debe ser 'producer' o 'consumer', no {role!r}")

        self.channel = channel
        self.role = role
        self._port = _CHANNEL_PORTS[channel]
        self._addr = f"tcp://{ZMQ_HOST}:{self._port}"
        self._ctx = _get_ctx()
        self._closed = False

        if role == "producer":
            self._sock = self._ctx.socket(zmq.PUB)
            # SNDHWM: si el consumer es lento, mensajes viejos se descartan
            # en el productor (evita bloqueos). Es lo que queremos.
            self._sock.setsockopt(zmq.SNDHWM, ZMQ_RCV_HWM)
            # LINGER=0: al cerrar, no esperar a que lleguen mensajes pendientes.
            self._sock.setsockopt(zmq.LINGER, 0)
            self._sock.bind(self._addr)
            # Slow-joiner mitigation: dar tiempo al OS a publicar el bind
            # antes de permitir publish() inmediato.
            time.sleep(0.1)
            print(f"[ZMQ_BUS] Producer bind {self._addr} (canal {channel!r})")

        else:  # consumer
            self._sock = self._ctx.socket(zmq.SUB)
            self._sock.setsockopt(zmq.RCVHWM, ZMQ_RCV_HWM)
            self._sock.setsockopt(zmq.LINGER, 0)
            # Suscribirse a TODOS los topics del canal (no usamos topics
            # internos por ahora — un canal = un socket).
            self._sock.setsockopt(zmq.SUBSCRIBE, b"")
            self._sock.connect(self._addr)
            print(f"[ZMQ_BUS] Consumer connect {self._addr} (canal {channel!r})")

    # ---------- API pública (compat shm_bus) ----------

    def publish(self, event: Dict[str, Any]) -> int:
        """Publica un evento dict-serializable. Retorna bytes publicados.

        No bloquea: si el HWM está lleno, ZMQ descarta mensajes según política
        de conflate/drop (con SNDHWM, los mensajes se encolan internamente).
        """
        if self._closed:
            raise BusClosed("Bus cerrado")
        if self.role != "producer":
            raise RuntimeError("publish solo desde role='producer'")

        # send_json internamente hace json.dumps + encode. Rápido.
        try:
            # NOBLOCK para no bloquear si HWM lleno: descarta o lanza zmq.Again.
            self._sock.send_json(event, flags=zmq.NOBLOCK)
        except zmq.Again:
            # HWM lleno: tiramos el mensaje. Mejor perder que bloquear al productor.
            print(f"[ZMQ_BUS] WARNING canal={self.channel}: HWM lleno, mensaje descartado")
            return 0
        # No hay forma directa de saber bytes; retornamos tamaño aproximado.
        return len(str(event))

    def read(self) -> Optional[Dict[str, Any]]:
        """Lee un evento sin bloquear. None si la cola está vacía."""
        if self._closed:
            raise BusClosed("Bus cerrado")
        if self.role != "consumer":
            raise RuntimeError("read solo desde role='consumer'")

        try:
            return self._sock.recv_json(flags=zmq.NOBLOCK)
        except zmq.Again:
            return None

    def read_blocking(self, poll_interval: float = 0.001) -> Dict[str, Any]:
        """Bloquea hasta recibir un evento.

        `poll_interval` se mantiene por compat con shm_bus pero se ignora:
        ZMQ bloquea nativo en recv(), no hace polling.
        """
        if self._closed:
            raise BusClosed("Bus cerrado")
        if self.role != "consumer":
            raise RuntimeError("read_blocking solo desde role='consumer'")

        return self._sock.recv_json()

    def close(self) -> None:
        """Cierra el socket de este bus. Idempotente."""
        if self._closed:
            return
        try:
            self._sock.close(linger=0)
        except Exception:
            pass
        self._closed = True

    def unlink(self) -> None:
        """Compat con shm_bus.unlink(): en ZMQ no hay recurso persistente
        que desenlazar — cerrar el socket basta. Se deja como alias de close().
        """
        self.close()


__all__ = [
    "EventBus",
    "BusClosed",
    "PayloadTooLarge",
    "CHANNEL_RADAR",
    "CHANNEL_LPR",
    "CHANNEL_NPU",
]
