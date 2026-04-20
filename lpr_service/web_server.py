# lpr_service/web_server.py
"""
Flask que recibe alarmas de la cámara LPR Hikvision (puerto 8899 por default).
Acepta POST en cualquier path raíz (la Hikvision a veces postea a la IP como path).
"""
from __future__ import annotations

import datetime
import json
import threading

from flask import Flask, request, jsonify

from shared.config_loader import read_ini, get_listen_config

try:
    from .queue_manager import enqueue_plate_event, get_lpr_queue_stats
    LPR_QUEUE_AVAILABLE = True
    print("[LPR WEB] LPR Queue Manager disponible - procesamiento asíncrono")
except ImportError:
    from .decoder import procesar_payload_alarm  # fallback síncrono
    enqueue_plate_event = None  # type: ignore
    get_lpr_queue_stats = None  # type: ignore
    LPR_QUEUE_AVAILABLE = False
    print("[LPR WEB] LPR Queue Manager no disponible - procesamiento síncrono")

try:
    _config = read_ini(apply_env_overrides=True)
    DEFAULT_LISTEN_IP, DEFAULT_LISTEN_PORT = get_listen_config(
        _config, "LPR_CAM_WEBSERVER", "0.0.0.0", 8899
    )
    print(f"[LPR WEB] Config cargada: {DEFAULT_LISTEN_IP}:{DEFAULT_LISTEN_PORT}")
except Exception as e:
    print(f"[LPR WEB] Error config, usando defaults: {e}")
    DEFAULT_LISTEN_IP = "0.0.0.0"
    DEFAULT_LISTEN_PORT = 8899


def create_app() -> Flask:
    app = Flask(__name__)

    def _handle_post():
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[{ts}] [LPR] POST {request.path} desde {request.remote_addr}")
        try:
            payload = request.get_json(force=True)
            if not payload:
                return jsonify({"status": "ERROR", "message": "Payload JSON inválido"}), 400

            if LPR_QUEUE_AVAILABLE and enqueue_plate_event:
                result = enqueue_plate_event(payload)
            else:
                result = procesar_payload_alarm(payload, esperar_hilos=False)
            ok = result.get("status") in ("OK", "QUEUED")
            return jsonify(result), (200 if ok else 400)
        except Exception as e:
            print(f"[LPR] Error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "ERROR", "message": str(e)}), 500

    @app.post("/")
    def recibir_root():
        return _handle_post()

    @app.route("/<path:subpath>", methods=["POST"])
    def recibir_cualquier_path(subpath):
        # La cámara Hikvision a veces postea a /192.168.0.XXX o a la IP del server
        return _handle_post()

    @app.route("/health", methods=["GET"])
    def health():
        resp = {"status": "OK", "service": "lpr", "ts": datetime.datetime.now().isoformat()}
        if LPR_QUEUE_AVAILABLE and get_lpr_queue_stats:
            try:
                resp["queue_stats"] = get_lpr_queue_stats()
            except Exception:
                pass
        return jsonify(resp)

    return app


def start_lpr_web_server(host: str = None, port: int = None) -> threading.Thread:
    host = host or DEFAULT_LISTEN_IP
    port = port or DEFAULT_LISTEN_PORT

    def run_server():
        try:
            app = create_app()
            print(f"[LPR WEB] Iniciando servidor en {host}:{port}")
            app.run(host=host, port=port, debug=False, threaded=True)
        except Exception as e:
            print(f"[LPR WEB] Error iniciando servidor: {e}")

    t = threading.Thread(target=run_server, daemon=True, name="lpr-web-server")
    t.start()
    print(f"[LPR WEB] Servidor iniciado en hilo ({host}:{port})")
    return t
