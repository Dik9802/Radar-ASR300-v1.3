"""
shm_bus.py — Bus de eventos entre servicios vía memoria compartida (SPSC).

Diseño:
  - Un buffer SHM por productor (radar, lpr, npu). Cada buffer es un ring
    circular con slots de tamaño fijo.
  - SPSC lock-free: un productor y un consumer por canal. Sin locks — la
    sincronización se hace con un contador de secuencia global y una
    doble validación (seq_begin/seq_end) que detecta lecturas desgarradas.
  - Latencia ~10–50 µs en Linux. Polling con sleep(0.001) en el consumer.

Uso:
    # Productor (radar-service):
    from shared.shm_bus import EventBus
    bus = EventBus("radar", role="producer")
    bus.publish({"speed": 45.0, "ts_ms": 1776..., "kind": "speed"})

    # Consumer (display-service):
    bus = EventBus("radar", role="consumer")
    while True:
        evt = bus.read()
        if evt is None:
            time.sleep(0.001)
            continue
        handle(evt)

Payload: dict serializable a JSON, máx 488 bytes. Para placas, enviar
solo la ruta del .jpg (que ya está en disco compartido), NO la imagen
en base64 — reventaría el slot.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import time
from multiprocessing import shared_memory
from typing import Any, Dict, Optional

# Layout del buffer SHM:
#
#   [header: 16 bytes]                        offset 0
#   [slot 0: SLOT_SIZE bytes]                 offset 16
#   [slot 1: SLOT_SIZE bytes]
#   ...
#   [slot NUM_SLOTS-1]
#
# Header:
#   uint64  seq_next    próximo número de secuencia a publicar (monotónico)
#   uint64  _reserved   reservado (alineación)
#
# Slot (512 bytes):
#   uint32  seq_begin   seq cuando empieza la escritura
#   uint64  ts_ms       timestamp del evento
#   uint16  length      longitud del payload en bytes
#   uint16  _pad
#   bytes   payload     UTF-8 JSON (hasta PAYLOAD_MAX)
#   ...padding...
#   uint32  seq_end     seq cuando termina la escritura (igual a seq_begin
#                       si la escritura fue completa)
#
# Un consumer puede detectar una "lectura desgarrada" (torn read)
# comparando seq_begin con seq_end — si no coinciden, el productor
# sobrescribió el slot mientras leíamos: la lectura se descarta.

HEADER_SIZE = 16
SLOT_SIZE = 512
PAYLOAD_OFFSET = 16   # dentro del slot: tras seq_begin(4) + ts_ms(8) + length(2) + pad(2)
SEQ_END_OFFSET = SLOT_SIZE - 4
PAYLOAD_MAX = SEQ_END_OFFSET - PAYLOAD_OFFSET  # = 492
NUM_SLOTS = 64  # buffer de 64 eventos por canal
TOTAL_SIZE = HEADER_SIZE + NUM_SLOTS * SLOT_SIZE


def _shm_name(channel: str) -> str:
    """Nombre del bloque SHM en el sistema. En Linux aparece en /dev/shm/."""
    return f"radar_sbc_bus_{channel}"


class BusClosed(Exception):
    pass


class PayloadTooLarge(Exception):
    pass


class EventBus:
    """Bus SPSC entre un productor y un consumer sobre un canal nombrado."""

    def __init__(self, channel: str, role: str):
        if role not in ("producer", "consumer"):
            raise ValueError("role must be 'producer' or 'consumer'")
        self.channel = channel
        self.role = role
        self._name = _shm_name(channel)
        self._shm: Optional[shared_memory.SharedMemory] = None
        self._local_last_seq: int = 0  # último seq consumido (solo consumer)
        self._attach()

    def _attach(self) -> None:
        if self.role == "producer":
            try:
                self._shm = shared_memory.SharedMemory(
                    name=self._name, create=True, size=TOTAL_SIZE
                )
                # Inicializa header a cero
                struct.pack_into("<QQ", self._shm.buf, 0, 0, 0)
                print(f"[SHM_BUS] Canal '{self.channel}' creado "
                      f"(name={self._name}, size={TOTAL_SIZE}b, slots={NUM_SLOTS})")
            except FileExistsError:
                # Ya existía: nos adjuntamos al existente (p. ej. tras reinicio)
                self._shm = shared_memory.SharedMemory(name=self._name, create=False)
                print(f"[SHM_BUS] Canal '{self.channel}' ya existía, reutilizando")
        else:
            # Consumer: intenta adjuntarse; si no existe, lo crea vacío.
            # Así puede arrancar antes que los productores — cualquier
            # productor que llegue después se adjunta con FileExistsError.
            try:
                self._shm = shared_memory.SharedMemory(
                    name=self._name, create=False
                )
                print(f"[SHM_BUS] Consumer enlazado a '{self.channel}' (existía)")
            except FileNotFoundError:
                self._shm = shared_memory.SharedMemory(
                    name=self._name, create=True, size=TOTAL_SIZE
                )
                struct.pack_into("<QQ", self._shm.buf, 0, 0, 0)
                print(f"[SHM_BUS] Consumer creó canal '{self.channel}' "
                      f"(esperando productores)")
            # Posiciónate en el último seq publicado — no replayear backlog
            seq_next, = struct.unpack_from("<Q", self._shm.buf, 0)
            self._local_last_seq = seq_next

    def publish(self, event: Dict[str, Any]) -> int:
        """Publica un evento. Devuelve el seq asignado. Solo productor."""
        if self.role != "producer":
            raise RuntimeError("publish() solo en el productor")
        if self._shm is None:
            raise BusClosed()

        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > PAYLOAD_MAX:
            raise PayloadTooLarge(
                f"payload {len(payload)}b excede PAYLOAD_MAX={PAYLOAD_MAX}b"
            )

        # Reserva el siguiente seq
        seq_next, = struct.unpack_from("<Q", self._shm.buf, 0)
        new_seq = seq_next + 1
        slot_idx = new_seq % NUM_SLOTS
        offset = HEADER_SIZE + slot_idx * SLOT_SIZE
        seq32 = new_seq & 0xFFFFFFFF
        ts_ms = int(event.get("ts_ms", time.time() * 1000))

        # Escribe: seq_begin → cabecera → payload → seq_end
        struct.pack_into("<I", self._shm.buf, offset, seq32)
        struct.pack_into("<Q", self._shm.buf, offset + 4, ts_ms)
        struct.pack_into("<H", self._shm.buf, offset + 12, len(payload))
        self._shm.buf[offset + PAYLOAD_OFFSET:offset + PAYLOAD_OFFSET + len(payload)] = payload
        # zero trailing bytes hasta seq_end para no dejar basura
        tail_start = offset + PAYLOAD_OFFSET + len(payload)
        tail_end = offset + SEQ_END_OFFSET
        if tail_start < tail_end:
            self._shm.buf[tail_start:tail_end] = b"\x00" * (tail_end - tail_start)
        struct.pack_into("<I", self._shm.buf, offset + SEQ_END_OFFSET, seq32)

        # Publica el seq (vuelve visible el evento al consumer)
        struct.pack_into("<Q", self._shm.buf, 0, new_seq)
        return new_seq

    def read(self) -> Optional[Dict[str, Any]]:
        """Intenta leer el próximo evento. None si no hay nada nuevo."""
        if self.role != "consumer":
            raise RuntimeError("read() solo en el consumer")
        if self._shm is None:
            raise BusClosed()

        current_seq, = struct.unpack_from("<Q", self._shm.buf, 0)
        if current_seq <= self._local_last_seq:
            return None

        next_seq = self._local_last_seq + 1

        # Overrun: el productor nos pasó por encima más de NUM_SLOTS veces.
        # El slot más viejo que aún es válido es current_seq - NUM_SLOTS + 1.
        oldest_valid = current_seq - NUM_SLOTS + 1
        dropped = 0
        if next_seq < oldest_valid:
            dropped = oldest_valid - next_seq
            next_seq = oldest_valid
            print(f"[SHM_BUS] Canal '{self.channel}' OVERRUN: "
                  f"{dropped} eventos perdidos", file=sys.stderr)

        slot_idx = next_seq % NUM_SLOTS
        offset = HEADER_SIZE + slot_idx * SLOT_SIZE
        seq32_expected = next_seq & 0xFFFFFFFF

        seq_begin, = struct.unpack_from("<I", self._shm.buf, offset)
        if seq_begin != seq32_expected:
            # El productor ya sobrescribió este slot, seguimos sin avanzar
            # para reintentar en la próxima llamada.
            self._local_last_seq = next_seq - 1
            return None

        ts_ms, = struct.unpack_from("<Q", self._shm.buf, offset + 4)
        length, = struct.unpack_from("<H", self._shm.buf, offset + 12)
        if length > PAYLOAD_MAX:
            # Slot corrupto
            self._local_last_seq = next_seq
            return None
        payload = bytes(self._shm.buf[offset + PAYLOAD_OFFSET:offset + PAYLOAD_OFFSET + length])
        seq_end, = struct.unpack_from("<I", self._shm.buf, offset + SEQ_END_OFFSET)

        if seq_end != seq32_expected:
            # Torn read: el productor reescribió el slot mientras leíamos.
            # No avanzamos: reintento en la siguiente llamada (con el nuevo dato).
            return None

        self._local_last_seq = next_seq
        try:
            return json.loads(payload.decode("utf-8"))
        except Exception as e:
            print(f"[SHM_BUS] Canal '{self.channel}' JSON inválido en seq={next_seq}: {e}",
                  file=sys.stderr)
            return None

    def read_blocking(self, poll_interval: float = 0.001) -> Dict[str, Any]:
        """Bloquea hasta que haya un evento, haciendo polling cada poll_interval."""
        while True:
            evt = self.read()
            if evt is not None:
                return evt
            time.sleep(poll_interval)

    def stats(self) -> Dict[str, int]:
        if self._shm is None:
            return {"seq_next": 0, "local_last_seq": self._local_last_seq}
        seq_next, = struct.unpack_from("<Q", self._shm.buf, 0)
        return {
            "seq_next": seq_next,
            "local_last_seq": self._local_last_seq,
            "pending": max(0, seq_next - self._local_last_seq),
        }

    def close(self) -> None:
        if self._shm is not None:
            try:
                self._shm.close()
            except Exception:
                pass
            self._shm = None

    def unlink(self) -> None:
        """Elimina el bloque SHM del sistema (solo llamar al apagar el servicio productor)."""
        if self._shm is not None:
            name = self._shm.name
            try:
                self._shm.close()
            except Exception:
                pass
            try:
                shared_memory.SharedMemory(name=name, create=False).unlink()
            except Exception:
                pass
            self._shm = None

    def __enter__(self) -> "EventBus":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ── Canales bien conocidos ──────────────────────────────────────────────
# Mantener sincronizado con los productores/consumers.
CHANNEL_RADAR = "radar"     # {"kind":"speed", "speed": float, "ts_ms": int}
CHANNEL_LPR = "lpr"         # {"kind":"plate", "plate": str, "plate_pic_path": str?,
                            #  "scene_pic_path": str?, "ts_ms": int, "source": "lpr"}
CHANNEL_NPU = "npu"         # igual que LPR, source="npu"
