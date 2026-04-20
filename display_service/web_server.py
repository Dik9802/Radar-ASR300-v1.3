# display_web_server.py
# Servidor web para enviar mensajes al display LED
from flask import Flask, request, jsonify
import datetime
import threading
import time
import base64
import tempfile
import os

# Cargar intervalo de reenvÃ­o desde config.ini
try:
    from shared.config_loader import read_ini, get_int
    _config = read_ini(apply_env_overrides=True)
    TEXT_MODE_RESEND_INTERVAL = get_int(_config, "DISPLAY_MANAGER", "TEXT_MODE_RESEND_INTERVAL", 15)
    print(f"[DISPLAY WEB] TEXT_MODE_RESEND_INTERVAL={TEXT_MODE_RESEND_INTERVAL}s (desde config.ini)")
except Exception as e:
    TEXT_MODE_RESEND_INTERVAL = 15
    print(f"[DISPLAY WEB] Error cargando TEXT_MODE_RESEND_INTERVAL: {e}, usando default: {TEXT_MODE_RESEND_INTERVAL}s")

# Estado del contenido para reenvio periodico (texto o imagen)
_resend_lock = threading.Lock()
_resend_content = None  # Dict con parametros del contenido (type='text' o 'picture')
_resend_running = False
_resend_thread = None
_resend_stop_event = None

def _get_timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def _resend_loop(stop_event):
    """Hilo que reenvia el contenido cada TEXT_MODE_RESEND_INTERVAL segundos."""
    global _resend_running, _resend_content

    print(f"[{_get_timestamp()}] [DISPLAY WEB] Hilo de reenvio iniciado (cada {TEXT_MODE_RESEND_INTERVAL}s)")

    while True:
        if stop_event.wait(TEXT_MODE_RESEND_INTERVAL):
            print(f"[{_get_timestamp()}] [DISPLAY WEB] Hilo de reenvio detenido")
            break

        with _resend_lock:
            if stop_event.is_set() or not _resend_running:
                print(f"[{_get_timestamp()}] [DISPLAY WEB] Hilo de reenvio detenido")
                break
            content = _resend_content

        if content is None:
            continue

        try:
            from .led.led_controller_handler import send_text_over_tcp, send_gif_over_tcp, TextMode

            content_type = content.get("type", "text")
            if content_type == "text":
                print(f"[{_get_timestamp()}] [DISPLAY WEB] Reenviando texto: '{content['text']}'")
                send_text_over_tcp(
                    text=content["text"],
                    mode=TextMode.DRAW,
                    color_code=content["color"],
                    font_size_code=content["font_size"],
                    align=content["align"],
                    speed=content["speed"],
                    stay_time_s=content["stay_time"],
                    require_ack=True,
                    effect=content.get("effect", None),
                )
                print(f"[{_get_timestamp()}] [DISPLAY WEB] Texto reenviado correctamente")
            elif content_type == "picture":
                print(f"[{_get_timestamp()}] [DISPLAY WEB] Reenviando imagen ({content['size_bytes']} bytes)")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as tmp_file:
                    tmp_file.write(content["image_bytes"])
                    tmp_path = tmp_file.name
                try:
                    send_gif_over_tcp(
                        gif_path=tmp_path,
                        stay_time_s=content["stay_time"],
                        require_ack=True,
                    )
                    print(f"[{_get_timestamp()}] [DISPLAY WEB] Imagen reenviada correctamente")
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[{_get_timestamp()}] [DISPLAY WEB] Error reenviando contenido: {e}")

def _start_resend_thread(content_params: dict):
    """Inicia el hilo de reenvio periodico para texto o imagen."""
    global _resend_content, _resend_running, _resend_thread, _resend_stop_event

    content_type = content_params.get("type", "text")

    with _resend_lock:
        _resend_content = content_params

        if _resend_running and _resend_thread and _resend_thread.is_alive():
            print(f"[{_get_timestamp()}] [DISPLAY WEB] Reenvio actualizado ({content_type})")
            return

        _resend_running = True
        _resend_stop_event = threading.Event()
        _resend_thread = threading.Thread(
            target=_resend_loop,
            args=(_resend_stop_event,),
            daemon=True,
            name="content-resend",
        )
        _resend_thread.start()
        print(f"[{_get_timestamp()}] [DISPLAY WEB] Reenvio activado ({content_type}, cada {TEXT_MODE_RESEND_INTERVAL}s)")

def _stop_resend_thread():
    """Detiene el hilo de reenvio periodico."""
    global _resend_running, _resend_content, _resend_stop_event

    with _resend_lock:
        _resend_running = False
        _resend_content = None
        if _resend_stop_event is not None:
            _resend_stop_event.set()
        print(f"[{_get_timestamp()}] [DISPLAY WEB] Reenvio periodico desactivado")

def get_resend_status() -> dict:
    """Retorna el estado actual del reenvÃ­o periÃ³dico"""
    with _resend_lock:
        content_type = _resend_content.get('type', 'text') if _resend_content else None
        if _resend_content and content_type == 'text':
            current_content = _resend_content.get('text')
        elif _resend_content and content_type == 'picture':
            current_content = f"imagen ({_resend_content.get('size_bytes', 0)} bytes)"
        else:
            current_content = None
        return {
            "active": _resend_running,
            "type": content_type,
            "interval_seconds": TEXT_MODE_RESEND_INTERVAL,
            "current_content": current_content
        }

# Importar el controlador LED
try:
    from .led.led_controller_handler import (
        send_text_over_tcp,
        send_gif_over_tcp,
        send_select_program_single,
        TextMode, TextColor, TextFontSize, TextAlign, TextEffect
    )
    LED_CONTROLLER_AVAILABLE = True
    print("[DISPLAY WEB] LED Controller disponible")
except ImportError as e:
    LED_CONTROLLER_AVAILABLE = False
    print(f"[DISPLAY WEB] LED Controller no disponible: {e}")

# Importar control de modo del display manager
try:
    from .manager import (
        get_display_mode,
        set_mode_texto,
        set_mode_picture,
        set_mode_radar,
        save_text_message_state,
        get_saved_text_params,
        init_display_mode_from_config
    )
    DISPLAY_MODE_AVAILABLE = True
    print("[DISPLAY WEB] Display Mode Control disponible")
except ImportError as e:
    DISPLAY_MODE_AVAILABLE = False
    print(f"[DISPLAY WEB] Display Mode Control no disponible: {e}")

# ConfiguraciÃ³n desde config.ini
try:
    from shared.config_loader import read_ini, get_listen_config
    config = read_ini(apply_env_overrides=True)
    DEFAULT_LISTEN_IP, DEFAULT_LISTEN_PORT = get_listen_config(config, "LED_CONTROLLER_WEBSERVER", "0.0.0.0", 8081)
    print(f"[DISPLAY WEB] ConfiguraciÃ³n cargada desde config.ini: {DEFAULT_LISTEN_IP}:{DEFAULT_LISTEN_PORT}")
except Exception as e:
    print(f"[DISPLAY WEB] Error cargando config.ini, usando valores por defecto: {e}")
    DEFAULT_LISTEN_IP = "0.0.0.0"
    DEFAULT_LISTEN_PORT = 8081


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/", methods=["GET"])
    def root():
        """InformaciÃ³n del servidor"""
        return jsonify({
            "status": "OK",
            "service": "Display LED Web Server",
            "led_controller": "available" if LED_CONTROLLER_AVAILABLE else "unavailable",
            "timestamp": datetime.datetime.now().isoformat(),
            "endpoints": {
                "GET /": "InformaciÃ³n del servidor",
                "GET /health": "Estado del servidor",
                "GET /custom_text_message": "Enviar mensaje de texto al display (params: text, color, font_size, align, mode, speed, stay_time)",
                "GET /mode": "Consultar modo actual (radar o texto)",
                "GET /mode/radar": "Cambiar a modo radar (procesa velocidades/placas)",
                "GET /mode/texto": "Cambiar a modo texto (ignora velocidades/placas)"
            }
        })

    @app.route("/health", methods=["GET"])
    def health_check():
        """Estado del servidor"""
        current_mode = get_display_mode() if DISPLAY_MODE_AVAILABLE else "unknown"
        resend_status = get_resend_status()
        return jsonify({
            "status": "OK",
            "service": "Display LED Web Server",
            "led_controller": "available" if LED_CONTROLLER_AVAILABLE else "unavailable",
            "display_mode": current_mode,
            "resend": resend_status,
            "timestamp": datetime.datetime.now().isoformat()
        })

    @app.route("/mode", methods=["GET"])
    def get_mode():
        """Consulta el modo actual del display"""
        if not DISPLAY_MODE_AVAILABLE:
            return jsonify({
                "status": "ERROR",
                "message": "Display Mode Control no disponible"
            }), 503
        
        current_mode = get_display_mode()
        resend_status = get_resend_status()
        return jsonify({
            "status": "OK",
            "mode": current_mode,
            "resend": resend_status,
            "description": "radar = procesa velocidades/placas, texto = muestra texto personalizado, picture = muestra imagen",
            "timestamp": datetime.datetime.now().isoformat()
        })

    @app.route("/mode/radar", methods=["GET"])
    def switch_to_radar():
        """Cambia al modo radar (procesa velocidades/placas normalmente)"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[{timestamp}] [DISPLAY WEB] GET /mode/radar desde {request.remote_addr}")
        
        if not DISPLAY_MODE_AVAILABLE:
            return jsonify({
                "status": "ERROR",
                "message": "Display Mode Control no disponible"
            }), 503
        
        # Detener el reenvÃ­o periÃ³dico
        _stop_resend_thread()
        
        previous_mode = set_mode_radar()
        current_mode = get_display_mode()
        
        return jsonify({
            "status": "OK",
            "message": "Modo cambiado a RADAR",
            "previous_mode": previous_mode,
            "current_mode": current_mode,
            "resend": {
                "active": False,
                "stopped": True
            },
            "description": "El display ahora procesarÃ¡ velocidades y placas del radar normalmente. ReenvÃ­o periÃ³dico detenido.",
            "timestamp": datetime.datetime.now().isoformat()
        })

    @app.route("/mode/texto", methods=["GET"])
    def switch_to_texto():
        """Cambia al modo texto (ignora velocidades/placas)"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[{timestamp}] [DISPLAY WEB] GET /mode/texto desde {request.remote_addr}")
        
        if not DISPLAY_MODE_AVAILABLE:
            return jsonify({
                "status": "ERROR",
                "message": "Display Mode Control no disponible"
            }), 503
        
        previous_mode = set_mode_texto()
        current_mode = get_display_mode()
        
        return jsonify({
            "status": "OK",
            "message": "Modo cambiado a TEXTO",
            "previous_mode": previous_mode,
            "current_mode": current_mode,
            "description": "El display ignorarÃ¡ velocidades y placas. El mensaje personalizado permanecerÃ¡ visible.",
            "timestamp": datetime.datetime.now().isoformat()
        })

    @app.route("/mode/picture", methods=["GET"])
    def switch_to_picture():
        """Cambia al modo picture (ignora velocidades/placas)"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[{timestamp}] [DISPLAY WEB] GET /mode/picture desde {request.remote_addr}")
        
        if not DISPLAY_MODE_AVAILABLE:
            return jsonify({
                "status": "ERROR",
                "message": "Display Mode Control no disponible"
            }), 503
        
        previous_mode = set_mode_picture()
        current_mode = get_display_mode()
        
        return jsonify({
            "status": "OK",
            "message": "Modo cambiado a PICTURE",
            "previous_mode": previous_mode,
            "current_mode": current_mode,
            "description": "El display ignorarÃ¡ velocidades y placas. La imagen permanecerÃ¡ visible.",
            "timestamp": datetime.datetime.now().isoformat()
        })

    @app.route("/custom_text_message", methods=["GET"])
    def custom_text_message():
        """
        EnvÃ­a un mensaje de texto personalizado al display LED.
        
        ParÃ¡metros GET:
            text: Mensaje a mostrar (requerido)
            color: RED, GREEN, YELLOW, BLUE, PURPLE, CYAN, WHITE (default: GREEN)
            font_size: 8, 12, 16, 24, 32, 40, 48, 56 (default: 16)
            align: LEFT, CENTER, RIGHT (default: CENTER)
            effect: CÃ³digo numÃ©rico del efecto 0-70 (ver lista). Si no se especifica, usa mode.
            mode: Siempre DRAW (no es opcional)
            speed: Velocidad de animaciÃ³n 1-100, menor=mÃ¡s rÃ¡pido (default: 1)
            stay_time: Segundos en pantalla (default: 10)
        
        Efectos disponibles (effect=nÃºmero):
            0=Draw, 1=Open left, 2=Open right, 6=Move left, 7=Move right,
            8=Move up, 9=Move down, 10=Scroll up, 11=Scroll left, 12=Scroll right,
            13=Flicker, 14=Continuous scroll left, 46=Drop, 63=Snow, 255=Random
        
        Ejemplos:
            /custom_text_message?text=Hola&color=GREEN&font_size=24
            /custom_text_message?text=ALERTA&color=RED&font_size=48&effect=13&speed=5
            /custom_text_message?text=INFO&font_size=32&effect=11&speed=10&stay_time=30
        """
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[{timestamp}] [DISPLAY WEB] GET /custom_text_message desde {request.remote_addr}")
        
        if not LED_CONTROLLER_AVAILABLE:
            return jsonify({
                "status": "ERROR",
                "message": "LED Controller no disponible"
            }), 503
        
        try:
            # Leer parÃ¡metros GET
            text = request.args.get("text", "")
            
            if not text:
                return jsonify({
                    "status": "ERROR",
                    "message": "Se requiere el parÃ¡metro 'text'",
                    "usage": "/custom_text_message?text=MiMensaje&color=GREEN&stay_time=10"
                }), 400
            
            # Mapeo de colores
            color_map = {
                "RED": TextColor.RED,
                "GREEN": TextColor.GREEN,
                "YELLOW": TextColor.YELLOW,
                "BLUE": TextColor.BLUE,
                "PURPLE": TextColor.PURPLE,
                "CYAN": TextColor.CYAN,
                "WHITE": TextColor.WHITE
            }
            color_str = request.args.get("color", "GREEN").upper()
            color = color_map.get(color_str, TextColor.GREEN)
            
            # TamaÃ±o de fuente: acepta nÃºmero (8, 12, 16, 24, 32, 40, 48, 56)
            font_size_map = {8: 0x00, 12: 0x01, 16: 0x02, 24: 0x03, 32: 0x04, 40: 0x05, 48: 0x06, 56: 0x07}
            font_str = request.args.get("font_size", "16").strip()
            try:
                font_num = int(font_str)
                font_size = font_size_map.get(font_num, 0x02)  # Default: 16px
            except ValueError:
                font_size = 0x02  # Default: 16px
            
            # Mapeo de alineaciÃ³n
            align_map = {
                "LEFT": TextAlign.LEFT,
                "CENTER": TextAlign.CENTER,
                "RIGHT": TextAlign.RIGHT
            }
            align_str = request.args.get("align", "CENTER").upper()
            align = align_map.get(align_str, TextAlign.CENTER)
            
            # Efecto: acepta nÃºmero (0-255) directamente
            effect_str = request.args.get("effect", "").strip()
            effect = None
            if effect_str:
                try:
                    effect = int(effect_str)
                    if effect < 0 or effect > 255:
                        effect = 0
                except ValueError:
                    effect = 0  # Si no es nÃºmero vÃ¡lido, usar DRAW (0)
            
            speed = int(request.args.get("speed", 1))
            stay_time = int(request.args.get("stay_time", 10))
            
            effect_info = f" effect={effect_str}" if effect else ""
            print(f"[DISPLAY WEB] Enviando: '{text}' | color={color_str} font={font_str}{effect_info} align={align_str} speed={speed} stay={stay_time}s")
            
            # Cambiar a modo texto (ignora velocidades/placas del radar)
            if DISPLAY_MODE_AVAILABLE:
                previous_mode = set_mode_texto()
                print(f"[DISPLAY WEB] Modo cambiado: {previous_mode} â†’ texto")
            
            # Primero enviar comando de cambio al programa 1 con persistencia
            print(f"[DISPLAY WEB] Cambiando a programa 1 con persistencia...")
            program_acks = send_select_program_single(
                program_number=1,
                save_to_flash=True,
                require_ack=True
            )
            program_success = len(program_acks) > 0 and all(ack.get('rr', 1) == 0 for ack in program_acks)
            print(f"[DISPLAY WEB] Programa 1 seleccionado: {'OK' if program_success else 'SIN CONFIRMACIÃ“N'}")
            
            # Luego enviar el mensaje al display (siempre TextMode.DRAW)
            acks = send_text_over_tcp(
                text=text,
                mode=TextMode.DRAW,
                color_code=color,
                font_size_code=font_size,
                align=align,
                speed=speed,
                stay_time_s=stay_time,
                require_ack=True,
                effect=int(effect) if effect is not None else None
            )
            
            text_success = len(acks) > 0 and all(ack.get('rr', 1) == 0 for ack in acks)
            overall_success = program_success and text_success
            
            # Guardar parÃ¡metros e iniciar reenvÃ­o periÃ³dico
            message_params = {
                'type': 'text',
                'text': text,
                'mode': TextMode.DRAW,
                'color': color,
                'font_size': font_size,
                'align': align,
                'speed': speed,
                'stay_time': stay_time,
                'effect': int(effect) if effect is not None else None
            }
            _start_resend_thread(message_params)
            
            # Guardar estado persistente en config.ini (para restaurar tras reinicio)
            if DISPLAY_MODE_AVAILABLE:
                persistent_params = {
                    'text': text,
                    'color': color_str,
                    'font_size': font_str,
                    'align': align_str,
                    'mode': 'DRAW',
                    'speed': speed,
                    'stay_time': stay_time
                }
                save_text_message_state(persistent_params)
                print(f"[DISPLAY WEB] ðŸ’¾ Estado guardado en config.ini para persistencia")
            
            current_mode = get_display_mode() if DISPLAY_MODE_AVAILABLE else "unknown"
            
            return jsonify({
                "status": "OK" if overall_success else "SENT",
                "message": f"Mensaje enviado: '{text}'",
                "display_mode": current_mode,
                "resend": {
                    "active": True,
                    "interval_seconds": TEXT_MODE_RESEND_INTERVAL
                },
                "program_change": {
                    "program": 1,
                    "persistent": True,
                    "confirmed": program_success,
                    "acks_received": len(program_acks)
                },
                "text_message": {
                    "confirmed": text_success,
                    "acks_received": len(acks)
                },
                "parameters": {
                    "text": text,
                    "color": color_str,
                    "font_size": font_str,
                    "align": align_str,
                    "effect": effect_str if effect else None,
                    "mode": "DRAW",
                    "speed": speed,
                    "stay_time": stay_time
                },
                "note": f"Display en modo TEXTO. El mensaje se reenviarÃ¡ cada {TEXT_MODE_RESEND_INTERVAL}s. Usar /mode/radar para volver al modo normal."
            })
            
        except Exception as e:
            print(f"[DISPLAY WEB] Error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                "status": "ERROR",
                "message": str(e)
            }), 500

    @app.route("/custom_image", methods=["POST"])
    def custom_image():
        """
        EnvÃ­a una imagen al display LED.
        
        Body JSON:
            image: Imagen en base64 (requerido). Formatos soportados: PNG, JPG, GIF, BMP
            stay_time: Segundos en pantalla (default: 10)
        
        Ejemplo JSON:
            {
                "image": "iVBORw0KGgoAAAANSUhEUgAAAAUA...",
                "stay_time": 15
            }
        """
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[{timestamp}] [DISPLAY WEB] POST /custom_image desde {request.remote_addr}")
        
        if not LED_CONTROLLER_AVAILABLE:
            return jsonify({
                "status": "ERROR",
                "message": "LED Controller no disponible"
            }), 503
        
        try:
            # Obtener datos del body JSON
            data = request.get_json(force=True, silent=True) or {}
            
            image_b64 = data.get("image", "")
            if not image_b64:
                return jsonify({
                    "status": "ERROR",
                    "message": "Se requiere el campo 'image' con la imagen en base64",
                    "usage": {
                        "method": "POST",
                        "content_type": "application/json",
                        "body": {
                            "image": "<base64_encoded_image>",
                            "stay_time": 10
                        }
                    }
                }), 400
            
            stay_time = int(data.get("stay_time", 10))
            
            # Decodificar base64
            try:
                # Remover prefijo data:image/... si existe
                if "," in image_b64:
                    image_b64 = image_b64.split(",", 1)[1]
                
                image_bytes = base64.b64decode(image_b64)
            except Exception as e:
                return jsonify({
                    "status": "ERROR",
                    "message": f"Error decodificando base64: {str(e)}"
                }), 400
            
            print(f"[DISPLAY WEB] Imagen recibida: {len(image_bytes)} bytes, stay_time={stay_time}s")
            
            # Guardar en archivo temporal
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as tmp_file:
                tmp_file.write(image_bytes)
                tmp_path = tmp_file.name
            
            try:
                # Cambiar a modo picture (ignora velocidades/placas del radar)
                if DISPLAY_MODE_AVAILABLE:
                    previous_mode = set_mode_picture()
                    print(f"[DISPLAY WEB] Modo cambiado: {previous_mode} â†’ picture")
                
                # Enviar programa 1 con persistencia
                print(f"[DISPLAY WEB] Cambiando a programa 1 con persistencia...")
                program_acks = send_select_program_single(
                    program_number=1,
                    save_to_flash=True,
                    require_ack=True
                )
                program_success = len(program_acks) > 0 and all(ack.get('rr', 1) == 0 for ack in program_acks)
                
                # Enviar la imagen
                acks = send_gif_over_tcp(
                    gif_path=tmp_path,
                    stay_time_s=stay_time,
                    require_ack=True
                )
                
                image_success = len(acks) > 0 and all(ack.get('rr', 1) == 0 for ack in acks)
                overall_success = program_success and image_success
                
                # Guardar parÃ¡metros de imagen e iniciar reenvÃ­o periÃ³dico
                image_params = {
                    'type': 'picture',
                    'image_bytes': image_bytes,
                    'size_bytes': len(image_bytes),
                    'stay_time': stay_time
                }
                _start_resend_thread(image_params)
                
                current_mode = get_display_mode() if DISPLAY_MODE_AVAILABLE else "unknown"
                
                return jsonify({
                    "status": "OK" if overall_success else "SENT",
                    "message": "Imagen enviada al display",
                    "display_mode": current_mode,
                    "resend": {
                        "active": True,
                        "interval_seconds": TEXT_MODE_RESEND_INTERVAL
                    },
                    "program_change": {
                        "program": 1,
                        "persistent": True,
                        "confirmed": program_success
                    },
                    "image": {
                        "size_bytes": len(image_bytes),
                        "stay_time": stay_time,
                        "confirmed": image_success,
                        "acks_received": len(acks)
                    },
                    "note": f"Display en modo PICTURE. La imagen se reenviarÃ¡ cada {TEXT_MODE_RESEND_INTERVAL}s. Usar /mode/radar para volver al modo normal."
                })
                
            finally:
                # Eliminar archivo temporal
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            
        except Exception as e:
            print(f"[DISPLAY WEB] Error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                "status": "ERROR",
                "message": str(e)
            }), 500

    return app


def _restore_display_state():
    """Restaura el estado del display desde config.ini (llamar despuÃ©s de iniciar el servidor LED)"""
    if not DISPLAY_MODE_AVAILABLE or not LED_CONTROLLER_AVAILABLE:
        print("[DISPLAY WEB] âš ï¸ No se puede restaurar estado: controladores no disponibles")
        return
    
    try:
        # Cargar estado desde config.ini
        state = init_display_mode_from_config()
        mode = state.get('mode', 'radar')
        text_params = state.get('text_params')
        
        if mode in ('text', 'texto') and text_params and text_params.get('text'):
            print(f"[{_get_timestamp()}] [DISPLAY WEB] ðŸ”„ Restaurando modo TEXTO desde config.ini...")
            print(f"[DISPLAY WEB] ðŸ“ Mensaje guardado: '{text_params['text']}'")
            
            # Mapear strings a enums
            color_map = {
                "RED": TextColor.RED, "GREEN": TextColor.GREEN, "YELLOW": TextColor.YELLOW,
                "BLUE": TextColor.BLUE, "PURPLE": TextColor.PURPLE, "CYAN": TextColor.CYAN, "WHITE": TextColor.WHITE
            }
            # Solo nÃºmeros: 8, 12, 16, 24, 32, 40, 48, 56
            font_size_map = {8: TextFontSize.SIZE_8PX, 12: TextFontSize.SIZE_12PX, 16: TextFontSize.SIZE_16PX,
                            24: TextFontSize.SIZE_24PX, 32: TextFontSize.SIZE_32PX, 40: TextFontSize.SIZE_40PX,
                            48: TextFontSize.SIZE_48PX, 56: TextFontSize.SIZE_56PX}
            try:
                fs_val = int(text_params.get('font_size', 16))
                font_size = font_size_map.get(fs_val, TextFontSize.SIZE_16PX)
            except (ValueError, TypeError):
                font_size = TextFontSize.SIZE_16PX
            
            align_map = {"LEFT": TextAlign.LEFT, "CENTER": TextAlign.CENTER, "RIGHT": TextAlign.RIGHT}
            
            color = color_map.get(text_params['color'].upper(), TextColor.GREEN)
            align = align_map.get(text_params['align'].upper(), TextAlign.CENTER)
            text_mode = TextMode.DRAW  # Siempre DRAW, no es opcional
            speed = text_params.get('speed', 0)
            stay_time = text_params.get('stay_time', 10)
            text = text_params['text']
            
            # Enviar programa 1 con persistencia
            print(f"[DISPLAY WEB] Cambiando a programa 1...")
            send_select_program_single(program_number=1, save_to_flash=True, require_ack=True)
            
            # Enviar el mensaje (siempre TextMode.DRAW)
            send_text_over_tcp(
                text=text, mode=TextMode.DRAW, color_code=color,
                font_size_code=font_size, align=align,
                speed=speed, stay_time_s=stay_time, require_ack=True
            )
            
            # Iniciar reenvÃ­o periÃ³dico
            message_params = {
                'type': 'text',
                'text': text, 'mode': TextMode.DRAW, 'color': color,
                'font_size': font_size, 'align': align,
                'speed': speed, 'stay_time': stay_time
            }
            _start_resend_thread(message_params)
            
            print(f"[{_get_timestamp()}] [DISPLAY WEB] âœ… Estado TEXTO restaurado correctamente")
        else:
            print(f"[{_get_timestamp()}] [DISPLAY WEB] ðŸ“¡ Modo RADAR activo (sin mensaje que restaurar)")
            
    except Exception as e:
        print(f"[{_get_timestamp()}] [DISPLAY WEB] âŒ Error restaurando estado: {e}")
        import traceback
        traceback.print_exc()

def start_display_web_server(host: str = None, port: int = None):
    """Inicia el servidor web para el display LED en un hilo separado"""
    if host is None:
        host = DEFAULT_LISTEN_IP
    if port is None:
        port = DEFAULT_LISTEN_PORT
        
    def run_server():
        try:
            app = create_app()
            print(f"[DISPLAY WEB] Iniciando servidor en {host}:{port}")
            
            # Restaurar estado del display despuÃ©s de un pequeÃ±o delay
            # para dar tiempo al LED controller de conectarse
            def delayed_restore():
                time.sleep(3)  # Esperar 3 segundos para que el LED estÃ© listo
                _restore_display_state()
            
            restore_thread = threading.Thread(target=delayed_restore, daemon=True, name="display-restore")
            restore_thread.start()
            
            app.run(host=host, port=port, debug=False, threaded=True)
        except Exception as e:
            print(f"[DISPLAY WEB] Error iniciando servidor: {e}")
    
    thread = threading.Thread(target=run_server, daemon=True, name="display-web-server")
    thread.start()
    print(f"[DISPLAY WEB] Servidor iniciado en hilo separado ({host}:{port})")
    return thread


if __name__ == "__main__":
    print("[DISPLAY WEB] Iniciando servidor de forma independiente...")
    app = create_app()
    app.run(host=DEFAULT_LISTEN_IP, port=DEFAULT_LISTEN_PORT, debug=True, threaded=True)

