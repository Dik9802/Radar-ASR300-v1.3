"""
lpr-service/main.py

Flask HTTP que recibe alarmas de la cámara LPR Hikvision, decodifica imágenes
y publica placas al canal SHM 'lpr'.

Uso:
    python -m lpr_service.main
"""
from __future__ import annotations

import signal
import sys
import time

print("[LPR-SERVICE] Iniciando...")


def main() -> None:
    from .queue_manager import start_lpr_queue_manager
    from .web_server import start_lpr_web_server

    try:
        start_lpr_queue_manager()
    except Exception as e:
        print(f"[LPR-SERVICE] Error iniciando queue manager: {e}")

    start_lpr_web_server()

    def _shutdown(signum, frame):
        print(f"[LPR-SERVICE] Señal {signum}, cerrando...")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    print("[LPR-SERVICE] ✅ Listo. Publicando al canal SHM 'lpr'.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
