"""
radar-service/main.py

Servicio TCP del radar. Publica velocidades al canal SHM 'radar'.

Uso:
    python -m radar_service.main     # desde Python/
"""
from __future__ import annotations

import signal
import sys
import time

print("[RADAR-SERVICE] Iniciando...")


def main() -> None:
    from .tcp_listener import start_radar_manager

    start_radar_manager()

    def _shutdown(signum, frame):
        print(f"[RADAR-SERVICE] Señal {signum}, cerrando...")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    print("[RADAR-SERVICE] ✅ Listo. Publicando al canal SHM 'radar'.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
