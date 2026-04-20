# led_controller_socket.py — Capa de transporte TCP efímera (conectar → enviar → desconectar)
import socket
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from .led_controller_constants import HOST, PORT, TIMEOUT_SECONDS, DELAY_BEFORE_CLOSE_S


class LedSession:
    """Sesión TCP efímera: conecta, permite sendall/recv_exact, se cierra al salir del contexto."""

    def __init__(self, sock: socket.socket, host: str, port: int, timeout_s: float):
        self._sock = sock
        self.host = host
        self.port = port
        self._timeout_s = timeout_s

    def sendall(self, data: bytes) -> None:
        self._sock.sendall(data)

    def recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Socket cerrado por el peer")
            buf += chunk
        return bytes(buf)

    def set_timeout(self, seconds: float) -> None:
        self._sock.settimeout(seconds)

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass
        self._sock = None


@contextmanager
def tcp_session(ack_received_ref=None):
    """
    Context manager: conecta al controlador LED, cede una sesión para envío/recepción,
    y desconecta automáticamente al salir.
    ack_received_ref: lista mutable [bool]. Si se pasa y ack_received_ref[0]==True al salir,
    se cierra inmediatamente. Si False o no se pasa, se espera DELAY_BEFORE_CLOSE_S antes de cerrar.
    """
    sock = None
    session = None
    try:
        t_conn = time.time()
        print(f"[LED TCP] [{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] [TIMING] create_connection INICIO", flush=True)
        sock = socket.create_connection((HOST, PORT), timeout=TIMEOUT_SECONDS)
        sock.settimeout(TIMEOUT_SECONDS)
        print(f"[LED TCP] [{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] [TIMING] create_connection OK (+{(time.time()-t_conn)*1000:.0f}ms)", flush=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[LED TCP] [{timestamp}] Conectado a {HOST}:{PORT}", flush=True)
        session = LedSession(sock, HOST, PORT, TIMEOUT_SECONDS)
        yield session
    except Exception as e:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[LED TCP] [{timestamp}] Error conectando/enviando al Controlador LED ({HOST}:{PORT}): {e}", flush=True)
        raise
    finally:
        try:
            # Si llegó ACK: cerrar inmediatamente. Si no: esperar 500ms antes de cerrar.
            if ack_received_ref is None or not ack_received_ref[0]:
                if DELAY_BEFORE_CLOSE_S > 0:
                    print(f"[LED TCP] Sin ACK o timeout: esperando {DELAY_BEFORE_CLOSE_S*1000:.0f}ms antes de cerrar", flush=True)
                    time.sleep(DELAY_BEFORE_CLOSE_S)
            else:
                print(f"[LED TCP] ACK recibido: cerrando conexión inmediatamente", flush=True)
            if session is not None and getattr(session, "_sock", None) is not None:
                session._sock.close()
            print(f"[LED TCP] Desconectado de {HOST}:{PORT}", flush=True)
        except Exception:
            pass


# ---------- API de compatibilidad (para led_controller_handler y main) ----------
# Con el modo efímero no hay conexión persistente; estas funciones son no-ops o stubs.
def ensure_connected(blocking: bool = True) -> bool:
    """No-op: la conexión se abre por transacción en tcp_session()."""
    return True


def is_connected() -> bool:
    """Siempre False: no mantenemos conexión persistente."""
    return False


def verify_connection() -> bool:
    """Siempre False: no hay conexión abierta entre transacciones."""
    return False


def close_connection() -> None:
    """No-op: no hay conexión persistente que cerrar."""
    pass
