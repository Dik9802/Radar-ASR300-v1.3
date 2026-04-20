# npu_service/web_server.py
"""
Flask que recibe POST /npu de la cámara NPU.
Puerto configurado en [NPU_CAM_WEBSERVER] del config.ini (default 8898).
"""
from __future__ import annotations

import datetime
import threading

from flask import Flask, request, jsonify

from shared.config_loader import read_ini, get_listen_config

try:
    from .queue_manager import enqueue_npu_event, get_npu_queue_stats
    NPU_QUEUE_AVAILABLE = True
    print("[NPU WEB] NPU Queue Manager disponible")
except ImportError:
    from .decoder import procesar_payload_npu as enqueue_npu_event  # fallback síncrono
    get_npu_queue_stats = None  # type: ignore
    NPU_QUEUE_AVAILABLE = False
    print("[NPU WEB] NPU Queue Manager no disponible - procesamiento síncrono")

try:
    _config = read_ini(apply_env_overrides=True)
    DEFAULT_LISTEN_IP, DEFAULT_LISTEN_PORT = get_listen_config(
        _config, "NPU_CAM_WEBSERVER", "0.0.0.0", 8898
    )
    print(f"[NPU WEB] Config cargada: {DEFAULT_LISTEN_IP}:{DEFAULT_LISTEN_PORT}")
except Exception as e:
    print(f"[NPU WEB] Error config, usando defaults: {e}")
    DEFAULT_LISTEN_IP = "0.0.0.0"
    DEFAULT_LISTEN_PORT = 8898


def create_app() -> Flask:
    app = Flask(__name__)

    @app.post("/npu")
    def recibir_npu():
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[{ts}] [NPU] POST /npu desde {request.remote_addr}")
        try:
            payload = request.get_json(force=True, silent=True)
            if not payload:
                return jsonify({"status": "ERROR", "message": "Payload JSON inválido"}), 400
            result = enqueue_npu_event(payload)
            ok = result.get("status") in ("OK", "QUEUED")
            return jsonify(result), (200 if ok else 400)
        except Exception as e:
            print(f"[NPU] Error procesando: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "ERROR", "message": str(e)}), 500

    @app.route("/health", methods=["GET"])
    def health():
        resp = {"status": "OK", "service": "npu", "ts": datetime.datetime.now().isoformat()}
        if NPU_QUEUE_AVAILABLE and get_npu_queue_stats:
            try:
                resp["queue_stats"] = get_npu_queue_stats()
            except Exception:
                pass
        return jsonify(resp)

    return app


def start_npu_web_server(host: str = None, port: int = None) -> threading.Thread:
    host = host or DEFAULT_LISTEN_IP
    port = port or DEFAULT_LISTEN_PORT

    def run_server():
        try:
            app = create_app()
            print(f"[NPU WEB] Iniciando servidor en {host}:{port}")
            app.run(host=host, port=port, debug=False, threaded=True)
        except Exception as e:
            print(f"[NPU WEB] Error iniciando servidor: {e}")

    t = threading.Thread(target=run_server, daemon=True, name="npu-web-server")
    t.start()
    print(f"[NPU WEB] Servidor iniciado en hilo ({host}:{port})")
    return t
