"""
display-service/main.py

Arranca:
  - 3 consumidores SHM (canales radar, lpr, npu)
  - El loop del display manager (envía al LED)
  - El servidor web del display (puerto 8081)

Uso:
    python -m display_service.main        # desde Python/
"""
from __future__ import annotations

import logging
import signal
import sys
import time

print("[DISPLAY-SERVICE] Iniciando...")

# Silenciar logs verbosos
for name in ("paramiko", "paramiko.transport", "urllib3", "requests"):
    logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    from .manager import start_display_manager, init_display_mode_from_config
    from .web_server import start_display_web_server

    # Modo inicial (radar/text/picture) desde config.ini
    try:
        init_display_mode_from_config()
    except Exception as e:
        print(f"[DISPLAY-SERVICE] ⚠ no se pudo cargar modo inicial: {e}")

    # Consumer loop + 3 consumidores SHM
    start_display_manager()

    # Servidor web (control manual del display)
    start_display_web_server()

    # Signal handlers para apagado limpio
    def _shutdown(signum, frame):
        print(f"[DISPLAY-SERVICE] Señal {signum}, cerrando...")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    print("[DISPLAY-SERVICE] ✅ Listo. Esperando eventos del bus SHM...")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
