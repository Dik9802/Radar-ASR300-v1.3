"""
npu-service/main.py

Flask HTTP que recibe POST /npu de la cámara NPU, decodifica imágenes
y publica placas al canal SHM 'npu'.

Uso:
    python -m npu_service.main
"""
from __future__ import annotations

import signal
import sys
import time

print("[NPU-SERVICE] Iniciando...")


def main() -> None:
    from .queue_manager import start_npu_queue_manager
    from .web_server import start_npu_web_server

    start_npu_queue_manager()
    start_npu_web_server()

    def _shutdown(signum, frame):
        print(f"[NPU-SERVICE] Señal {signum}, cerrando...")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    print("[NPU-SERVICE] ✅ Listo. Publicando al canal SHM 'npu'.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
