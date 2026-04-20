# display_service/manager.py
# Consumer de los 3 buses SHM (radar, lpr, npu). Maneja el LED.
import os
import tempfile
import threading
import time
from queue import Queue, Empty, Full
from typing import Optional, Dict, Any, Tuple, Union
from datetime import datetime

try:
    from PIL import Image as PILImage
    from PIL import ImageDraw, ImageFont
except Exception:
    PILImage = None
    ImageDraw = None
    ImageFont = None

# === LED controller (para mostrar la placa y cambiar programas) ===
from .led.led_controller_handler import (
    send_text_over_tcp,
    send_select_program_single,
    send_gif_over_tcp,
    TextMode, TextColor, TextFontSize, TextAlign,
)

# === Configuración desde config.ini ===
try:
    from shared.config_loader import (
        read_ini,
        get_str,
        get_int,
        get_float,
        get_bool,
        resolve_ini_path,
    )
    _ini = read_ini(apply_env_overrides=True)

    POLL_SLEEP = get_float(_ini, "DISPLAY_MANAGER", "POLL_SLEEP", 0.02) or 0.02
    QUEUE_MAXSIZE = get_int(_ini, "DISPLAY_MANAGER", "QUEUE_MAXSIZE", 128) or 128
    SPEED_LIMIT_KMPH = get_int(_ini, "DISPLAY_MANAGER", "SPEED_LIMIT_KMPH", 60)
    SHOW_PLATE_PIC = get_bool(_ini, "DISPLAY_MANAGER", "SHOW_PLATE_PIC", False)
    SHOW_PLATE_SCENE = get_bool(_ini, "DISPLAY_MANAGER", "SHOW_PLATE_SCENE", False)
    SHOW_PLATE_SPEED = get_bool(_ini, "DISPLAY_MANAGER", "SHOW_PLATE_SPEED", False)
    SHOW_PLATE_TIME = max(0.1, get_float(_ini, "DISPLAY_MANAGER", "SHOW_PLATE_TIME", 3.0) or 3.0)
    SHOW_SPEED_TIME = max(0.1, get_float(_ini, "DISPLAY_MANAGER", "SHOW_SPEED_TIME", 3.0) or 3.0)
    SPEED_IDLE_TIMEOUT_S = max(0.5, get_float(_ini, "DISPLAY_MANAGER", "SPEED_IDLE_TIMEOUT_S", 3.0) or 3.0)
    PLATE_GIF_BUDGET_S = max(0.5, get_float(_ini, "DISPLAY_MANAGER", "PLATE_GIF_BUDGET_S", 3.0) or 3.0)
    PLATE_COOLDOWN_S = max(0.0, get_float(_ini, "DISPLAY_MANAGER", "PLATE_COOLDOWN_S", 1.0) or 1.0)
    SHOW_PLATE_TEXT = get_bool(_ini, "DISPLAY_MANAGER", "SHOW_PLATE_TEXT", True)
    REQUIRE_ACK = get_bool(_ini, "DISPLAY_MANAGER", "REQUIRE_ACK", True)
    DISPLAY_WIDTH = get_int(_ini, "DISPLAY_MANAGER", "DISPLAY_WIDTH", 0) or 0
    DISPLAY_HEIGHT = get_int(_ini, "DISPLAY_MANAGER", "DISPLAY_HEIGHT", 0) or 0

    mode_str  = get_str(_ini, "DISPLAY_MANAGER", "MODE", "DRAW")
    color_str = get_str(_ini, "DISPLAY_MANAGER", "COLOR", "GREEN")
    _font_val = get_int(_ini, "DISPLAY_MANAGER", "SHOW_PLATE_FONT_SIZE", 24)
    align_str = get_str(_ini, "DISPLAY_MANAGER", "ALIGN", "CENTER")

    PLATE_SPEED = 0  # sin animación

    _font_val = _font_val if _font_val in (8, 12, 16, 24, 32, 40, 48, 56) else 24
    plate_font_number_str = get_str(_ini, "DISPLAY_MANAGER", "PLATE_NUMBER_FONT", None)
    PLATE_PREFIX = get_str(_ini, "DISPLAY_MANAGER", "PLATE_PREFIX", "PLACA ")
    AUTO_FIT_PLATE = bool(get_bool(_ini, "DISPLAY_MANAGER", "AUTO_FIT_PLATE", False))

    if SPEED_LIMIT_KMPH is not None and SPEED_LIMIT_KMPH <= 0:
        SPEED_LIMIT_KMPH = None

    print(f"[DISPLAY_MANAGER] Configuración cargada desde config.ini")
    print(f"[DISPLAY_MANAGER] ✅ MODE={mode_str}, SPEED=0, PREFIX='{PLATE_PREFIX}'")
    print(f"[DISPLAY_MANAGER] SHOW_PLATE_TIME={SHOW_PLATE_TIME}s (placa en pantalla)")
    print(f"[DISPLAY_MANAGER] SHOW_PLATE_PIC={SHOW_PLATE_PIC}, SHOW_PLATE_SCENE={SHOW_PLATE_SCENE}, SHOW_PLATE_SPEED={SHOW_PLATE_SPEED}, SHOW_PLATE_TEXT={SHOW_PLATE_TEXT}")
    print(f"[DISPLAY_MANAGER] REQUIRE_ACK={REQUIRE_ACK}")
    print(f"[DISPLAY_MANAGER] DISPLAY_SIZE={DISPLAY_WIDTH}x{DISPLAY_HEIGHT} px (fit antes de enviar)" if (DISPLAY_WIDTH and DISPLAY_HEIGHT) else "[DISPLAY_MANAGER] DISPLAY_SIZE=sin redimensionar")

except Exception as _e:
    print(f"[DISPLAY_MANAGER] Error cargando config.ini: {_e}, usando valores por defecto")
    POLL_SLEEP = 0.02
    QUEUE_MAXSIZE = 128
    SPEED_LIMIT_KMPH: Optional[float] = 60
    SHOW_PLATE_PIC = False
    SHOW_PLATE_SCENE = False
    SHOW_PLATE_SPEED = False
    SHOW_PLATE_TIME = 3.0
    SHOW_SPEED_TIME = 3.0
    SPEED_IDLE_TIMEOUT_S = 3.0
    PLATE_GIF_BUDGET_S = 3.0
    PLATE_COOLDOWN_S = 1.0
    SHOW_PLATE_TEXT = True
    REQUIRE_ACK = True
    DISPLAY_WIDTH = 0
    DISPLAY_HEIGHT = 0
    mode_str  = "DRAW"
    color_str = "GREEN"
    _font_val = 24
    align_str = "CENTER"
    PLATE_SPEED = 0
    plate_font_number_str = None
    PLATE_PREFIX = "PLACA "
    AUTO_FIT_PLATE = False

# Mapas string → enums
MODE_MAP = {"DRAW": TextMode.DRAW, "IMMEDIATE": TextMode.IMMEDIATE, "COVER": TextMode.COVER}
COLOR_MAP = {
    "RED": TextColor.RED, "GREEN": TextColor.GREEN, "YELLOW": TextColor.YELLOW,
    "BLUE": TextColor.BLUE, "PURPLE": TextColor.PURPLE, "CYAN": TextColor.CYAN, "WHITE": TextColor.WHITE
}
# Mapa de tamaño de fuente: solo números (8, 12, 16, 24, 32, 40, 48, 56)
FONT_SIZE_MAP = {
    8: TextFontSize.SIZE_8PX, 12: TextFontSize.SIZE_12PX, 16: TextFontSize.SIZE_16PX,
    24: TextFontSize.SIZE_24PX, 32: TextFontSize.SIZE_32PX, 40: TextFontSize.SIZE_40PX,
    48: TextFontSize.SIZE_48PX, 56: TextFontSize.SIZE_56PX
}

def _font_size_from_config(val) -> TextFontSize:
    """Convierte valor de config (número o string) a TextFontSize. Solo números: 8, 12, 16, 24, 32, 40, 48, 56."""
    try:
        n = int(val) if val is not None else 16
        return FONT_SIZE_MAP.get(n, TextFontSize.SIZE_16PX)
    except (ValueError, TypeError):
        return TextFontSize.SIZE_16PX
ALIGN_MAP = {"LEFT": TextAlign.LEFT, "CENTER": TextAlign.CENTER, "RIGHT": TextAlign.RIGHT}

PLATE_MODE  = TextMode.DRAW  # Siempre DRAW, no es opcional
PLATE_COLOR = COLOR_MAP.get(color_str, TextColor.GREEN)
PLATE_FONT  = _font_size_from_config(_font_val)
PLATE_ALIGN = ALIGN_MAP.get(align_str, TextAlign.CENTER)
PLATE_FONT_NUMBER = _font_size_from_config(plate_font_number_str) if plate_font_number_str is not None else PLATE_FONT

print(f"[DISPLAY_MANAGER] Configuración aplicada: SHOW_PLATE_TIME={SHOW_PLATE_TIME}, "
      f"PLATE_PREFIX='{PLATE_PREFIX}', SPEED_LIMIT_KMPH={SPEED_LIMIT_KMPH}")
print(f"[DISPLAY_MANAGER] MODE={PLATE_MODE.name}({PLATE_MODE.value}), SPEED={PLATE_SPEED}")

# ---------------- Colas internas ----------------
_placas_q: Queue = Queue(maxsize=QUEUE_MAXSIZE)
_velocidades_q: Queue = Queue(maxsize=QUEUE_MAXSIZE)

# ---------------- Modo de operación ----------------
# "radar" = procesa velocidades/placas normalmente
# "text" = ignora velocidades/placas, mantiene mensaje personalizado
_display_mode: str = "radar"
_display_mode_lock = threading.Lock()

# Ruta al config.ini para persistencia del estado.
# Debe coincidir con la misma resolución que usa read_ini().
try:
    _CONFIG_INI_PATH = str(resolve_ini_path())
except Exception:
    _CONFIG_INI_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.ini")

def _save_display_state(mode: str, text_params: dict = None):
    """Guarda el estado del display en config.ini"""
    try:
        import configparser
        config = configparser.ConfigParser()
        config.read(_CONFIG_INI_PATH, encoding='utf-8')
        
        if 'DISPLAY_STATE' not in config:
            config['DISPLAY_STATE'] = {}
        
        config['DISPLAY_STATE']['MODE'] = mode
        
        if text_params:
            config['DISPLAY_STATE']['TEXT_MESSAGE'] = text_params.get('text', '')
            config['DISPLAY_STATE']['TEXT_COLOR'] = text_params.get('color', 'GREEN')
            config['DISPLAY_STATE']['TEXT_FONT_SIZE'] = str(text_params.get('font_size', 16))
            config['DISPLAY_STATE']['TEXT_ALIGN'] = text_params.get('align', 'CENTER')
            config['DISPLAY_STATE']['TEXT_MODE'] = text_params.get('mode', 'DRAW')
            config['DISPLAY_STATE']['TEXT_SPEED'] = str(text_params.get('speed', 0))
            config['DISPLAY_STATE']['TEXT_STAY_TIME'] = str(text_params.get('stay_time', 10))
        elif mode == "radar":
            # Limpiar mensaje cuando se vuelve a modo radar
            config['DISPLAY_STATE']['TEXT_MESSAGE'] = ''
        
        with open(_CONFIG_INI_PATH, 'w', encoding='utf-8') as f:
            config.write(f)
        
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] 💾 Estado guardado en config.ini: MODE={mode}")
    except Exception as e:
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ❌ Error guardando estado: {e}")

def _load_display_state() -> dict:
    """Carga el estado del display desde config.ini (usa config_loader para manejar comentarios inline)."""
    try:
        from shared.config_loader import read_ini, get_str, get_int
        config = read_ini(apply_env_overrides=False)
        
        if 'DISPLAY_STATE' not in config:
            return {'mode': 'radar', 'text_params': None}
        
        mode = (get_str(config, 'DISPLAY_STATE', 'MODE', 'radar') or 'radar').lower().strip()
        if mode == 'texto':
            mode = 'text'  # Normalizar a inglés
        text_message = (get_str(config, 'DISPLAY_STATE', 'TEXT_MESSAGE', '') or '').strip()
        
        text_params = None
        if mode == 'text' and text_message:
            font_size_val = get_int(config, 'DISPLAY_STATE', 'TEXT_FONT_SIZE', 16)
            if font_size_val is None:
                font_size_val = 16
            text_params = {
                'text': text_message,
                'color': get_str(config, 'DISPLAY_STATE', 'TEXT_COLOR', 'GREEN') or 'GREEN',
                'font_size': font_size_val,
                'align': get_str(config, 'DISPLAY_STATE', 'TEXT_ALIGN', 'CENTER') or 'CENTER',
                'mode': get_str(config, 'DISPLAY_STATE', 'TEXT_MODE', 'DRAW') or 'DRAW',
                'speed': get_int(config, 'DISPLAY_STATE', 'TEXT_SPEED', 0) or 0,
                'stay_time': get_int(config, 'DISPLAY_STATE', 'TEXT_STAY_TIME', 10) or 10
            }
        
        return {'mode': mode, 'text_params': text_params}
    except Exception as e:
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ❌ Error cargando estado: {e}")
        return {'mode': 'radar', 'text_params': None}

def save_text_message_state(text_params: dict):
    """Guarda el mensaje de texto actual y cambia el modo a 'text'"""
    _save_display_state("text", text_params)


def update_plate_display_config(show_pic: Optional[bool] = None,
                                 show_scene: Optional[bool] = None,
                                 show_text: Optional[bool] = None) -> dict:
    """Actualiza los globals SHOW_PLATE_* en caliente (sin reiniciar).
    Retorna el estado actualizado."""
    global SHOW_PLATE_PIC, SHOW_PLATE_SCENE, SHOW_PLATE_TEXT
    if show_pic is not None:
        SHOW_PLATE_PIC = bool(show_pic)
    if show_scene is not None:
        SHOW_PLATE_SCENE = bool(show_scene)
    if show_text is not None:
        SHOW_PLATE_TEXT = bool(show_text)
    return {
        "show_plate_pic": SHOW_PLATE_PIC,
        "show_plate_scene": SHOW_PLATE_SCENE,
        "show_plate_text": SHOW_PLATE_TEXT,
    }


def get_plate_display_config() -> dict:
    """Retorna el estado actual de los globals SHOW_PLATE_*."""
    return {
        "show_plate_pic": SHOW_PLATE_PIC,
        "show_plate_scene": SHOW_PLATE_SCENE,
        "show_plate_text": SHOW_PLATE_TEXT,
    }

def get_display_mode() -> str:
    """Retorna el modo actual del display: 'radar', 'text' o 'picture'"""
    with _display_mode_lock:
        return _display_mode

def set_display_mode(mode: str, save_state: bool = True) -> str:
    """Cambia el modo del display. Retorna el modo anterior."""
    global _display_mode
    mode = mode.lower().strip()
    if mode == "texto":
        mode = "text"  # Normalizar a inglés
    if mode not in ("radar", "text", "picture"):
        raise ValueError(f"Modo inválido: {mode}. Usar 'radar', 'text' o 'picture'")
    with _display_mode_lock:
        previous = _display_mode
        _display_mode = mode
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🔄 MODO CAMBIADO: {previous} → {mode}")
        if save_state:
            _save_display_state(mode)
        return previous

def set_mode_texto(save_state: bool = True) -> str:
    """Cambia a modo texto (ignora velocidades/placas)"""
    return set_display_mode("text", save_state)

def set_mode_picture(save_state: bool = True) -> str:
    """Cambia a modo picture (ignora velocidades/placas)"""
    return set_display_mode("picture", save_state)

def set_mode_radar(save_state: bool = True) -> str:
    """Cambia a modo radar (procesa velocidades/placas normalmente)"""
    return set_display_mode("radar", save_state)

def get_saved_text_params() -> dict:
    """Retorna los parámetros del mensaje de texto guardado, o None si no hay"""
    state = _load_display_state()
    return state.get('text_params')

def init_display_mode_from_config():
    """Inicializa el modo del display desde config.ini (llamar al inicio)"""
    global _display_mode
    state = _load_display_state()
    mode = state.get('mode', 'radar')
    with _display_mode_lock:
        _display_mode = mode
    print(f"[{_ts_str()}] [DISPLAY_MANAGER] 📂 Modo inicial cargado desde config.ini: {mode}")
    return state

# ---------------- Utilidades ----------------
def _now_ms() -> int: return int(time.time() * 1000)
def _ts_str() -> str: return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def _fmt_ts(ts_ms: Optional[int]) -> str:
    if ts_ms is None: return "None"
    try:
        return datetime.fromtimestamp(ts_ms/1000.0).strftime("%H:%M:%S.%f")[:-3]
    except Exception:
        return str(ts_ms)

# ---------------- Determinación de programa por velocidad ----------------
# Velocidad < límite: programa = velocidad + 1 (ej: 50 km/h → 51)
# Velocidad ≥ límite: programa = 100 + velocidad (ej: 80 km/h → 180)
def _get_program_for_speed(speed: float) -> int:
    """
    Determina qué número de programa enviar basado en la velocidad.
    - Por debajo del umbral (< limit): programa = velocidad + 1
    - Por encima del umbral (>= limit): programa = 100 + velocidad
    """
    limit = SPEED_LIMIT_KMPH or 60
    speed_int = int(round(speed))

    if speed >= limit:
        program_number = 100 + speed_int
    else:
        program_number = speed_int + 1

    return program_number

def _log_program_decision(speed: float, program: int, reason: str):
    """Loguea la decisión de programa tomada"""
    color_type = "ROJO (100+vel)" if (SPEED_LIMIT_KMPH and speed >= SPEED_LIMIT_KMPH) else "VERDE (vel+1)"
    
    print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🎯 DECISIÓN DE PROGRAMA:")
    print(f"    • Velocidad: {speed} km/h")
    print(f"    • Fórmula: {color_type}")
    print(f"    • Programa calculado: {program}")
    print(f"    • Límite configurado: {SPEED_LIMIT_KMPH} km/h")
    print(f"    • Razón: {reason}")

# Estado local de la última velocidad recibida por el bus 'radar'.
# Se actualiza en _radar_consumer_thread (abajo).
_last_radar_speed: Optional[float] = None
_last_radar_ts_ms: Optional[int] = None
_radar_state_lock = threading.Lock()

# Timestamp (time.time()) hasta el cual el sistema debe ignorar las
# velocidades entrantes del bus (mientras hay una placa visible en el LED).
# Setear desde el _consumer_loop cuando procesa una placa.
_plate_busy_until: float = 0.0


def _get_last_speed_ts_ms_safe() -> Optional[int]:
    with _radar_state_lock:
        return _last_radar_ts_ms


def _get_last_speed_safe() -> Optional[float]:
    with _radar_state_lock:
        return _last_radar_speed

def _get_plate_color_for_speed(speed: Optional[float]) -> TextColor:
    """Color del texto según velocidad: verde si < límite, rojo si >= límite (igual que los dígitos)."""
    if speed is None:
        return TextColor.GREEN
    limit = SPEED_LIMIT_KMPH or 60
    return TextColor.RED if speed >= limit else TextColor.GREEN

# ---------------- Estado actual del LED (para logging) ----------------
# Refleja lo último que se envió al LED. Útil para depurar qué "debería"
# verse en pantalla en cada momento (independiente del busy timer).
_led_state: str = "unknown"      # "unknown" | "idle" | "plate:XXX" | "speed:N"
_led_state_lock = threading.Lock()
_led_state_set_at: float = 0.0


def _set_led_state(state: str) -> None:
    """Actualiza el estado reportado del LED y lo loguea."""
    global _led_state, _led_state_set_at
    with _led_state_lock:
        previous = _led_state
        _led_state = state
        _led_state_set_at = time.time()
    arrow = f"{previous} → {state}" if previous != state else f"{state} (mismo)"
    print(f"[{_ts_str()}] [DISPLAY_MANAGER] 📺 LED muestra: {arrow}")


def _get_led_state() -> Tuple[str, float]:
    with _led_state_lock:
        return _led_state, _led_state_set_at


# ---------------- Envío al LED (único punto de salida) ----------------
def _run_idle_now(reason: str = "") -> None:
    """Envía el programa IDLE (1) al LED. Único punto de envío de idle.
    Llamado por el _consumer_loop cuando las colas están vacías y expiró
    el tiempo de permanencia de lo último mostrado."""
    try:
        send_select_program_single(1, save_to_flash=False, require_ack=True)
        _set_led_state("idle")
        tag = f" ({reason})" if reason else ""
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] IDLE enviado{tag}")
    except Exception as e:
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ERROR enviando IDLE: {e}")


def _send_picture_sync(
    picture_path: str,
    picture_time_s: int,
    delete_after_send: Optional[str] = None,
) -> None:
    """Envía la imagen al LED de forma SÍNCRONA (bloquea ~2.5s mientras se
    transfiere el GIF). El envío síncrono es clave: cuando retorna, la
    imagen ya está visible en el LED, y recién ahí el consumer_loop arranca
    plate_end_time. El IDLE posterior lo emite el propio consumer_loop."""
    t0 = time.time()
    try:
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] Enviando imagen al LED: '{picture_path}' ({picture_time_s}s)")
        _log_timing("SYNC: ANTES send_gif_over_tcp", t0)
        send_gif_over_tcp(picture_path, stay_time_s=picture_time_s, require_ack=True)
        _log_timing("SYNC: DESPUÉS send_gif_over_tcp", t0)
    except Exception as e:
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ❌ ERROR enviando imagen al LED: {e}")
    finally:
        if delete_after_send and os.path.isfile(delete_after_send):
            try:
                os.remove(delete_after_send)
            except Exception:
                pass

# ---------------- Helpers de cola ----------------
def _offer(q: Queue, item: Any) -> None:
    try:
        q.put_nowait(item)
    except Full:
        try:
            discarded = q.get_nowait()  # descarta el más antiguo
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] ⚠  Cola llena, descartando: {discarded}")
        except Empty:
            pass
        q.put_nowait(item)

# ---------------- Envío de placa ----------------
def _auto_font_for_plate(txt: str) -> TextFontSize:
    n = len(txt.strip())
    if n <= 6: return TextFontSize.SIZE_40PX
    if n <= 8: return TextFontSize.SIZE_32PX
    return TextFontSize.SIZE_24PX

def _resolve_image_path(path: Optional[str], folder: str) -> Optional[str]:
    """Normaliza ruta y, si no existe, prueba plate_pic/scene_pic + basename desde cwd."""
    s = (path or "").strip()
    if not s:
        return None
    normalized = os.path.normpath(os.path.abspath(s))
    if os.path.isfile(normalized):
        return normalized
    base = os.path.basename(normalized)
    fallback = os.path.normpath(os.path.join(os.getcwd(), folder, base))
    if os.path.isfile(fallback):
        return fallback
    return None


def _log_timing(label: str, t0: float = None):
    """Log con timestamp para depurar congelamientos."""
    now = time.time()
    elapsed = f"+{(now - t0)*1000:.0f}ms" if t0 else "inicio"
    print(f"[{_ts_str()}] [TIMING] {label} {elapsed}", flush=True)

def _resize_image_to_fit(src_path: str, add_title: bool = True) -> Tuple[str, Optional[str]]:
    """Redimensiona la imagen. Si add_title=True: texto PLATE_PREFIX arriba, imagen abajo.
    Si add_title=False (ej. SHOW_PLATE_SCENE): imagen completa sin texto.
    Devuelve (path_a_usar, path_a_eliminar) — si no se procesa, path_a_eliminar es None."""
    t0 = time.time()
    _log_timing("_resize_image_to_fit INICIO", t0)
    print(f"[{_ts_str()}] [DISPLAY_MANAGER] _resize_image_to_fit llamado: src={src_path}, add_title={add_title}, DISPLAY={DISPLAY_WIDTH}x{DISPLAY_HEIGHT}, PIL={'OK' if PILImage else 'NO'}")
    if not (DISPLAY_WIDTH > 0 and DISPLAY_HEIGHT > 0):
        _log_timing("_resize_image_to_fit SKIP (sin DISPLAY)", t0)
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ⚠ DISPLAY_WIDTH o DISPLAY_HEIGHT no configurados, no se redimensiona")
        return (src_path, None)
    if PILImage is None:
        _log_timing("_resize_image_to_fit SKIP (sin PIL)", t0)
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ⚠ PIL no disponible, no se puede redimensionar")
        return (src_path, None)
    if not os.path.isfile(src_path):
        _log_timing("_resize_image_to_fit SKIP (archivo no existe)", t0)
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ⚠ Archivo no existe: {src_path}")
        return (src_path, None)
    try:
        im = PILImage.open(src_path)
        im = im.convert("RGB")
        w, h = im.size
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] Imagen original: {w}x{h}")

        # Sin título: solo redimensionar y guardar, sin canvas ni texto (evita daño en borde superior)
        if not add_title:
            scale_w = DISPLAY_WIDTH / w
            scale_h = DISPLAY_HEIGHT / h
            # Clamp a 1.0: solo escalar hacia abajo si excede el display.
            # La NPU ya entrega imágenes al tamaño final; upscaling degrada calidad.
            scale = min(1.0, scale_w, scale_h)
            nw = max(1, int(w * scale))
            nh = max(1, int(h * scale))
            resampler = getattr(getattr(PILImage, "Resampling", None), "LANCZOS", PILImage.LANCZOS)
            resized = im.resize((nw, nh), resampler)
            im.close()
            try:
                out = resized.quantize(colors=256)
            except Exception:
                out = resized.convert("P", palette=PILImage.ADAPTIVE, colors=256)
            fd, tmp = tempfile.mkstemp(suffix=".gif")
            os.close(fd)
            out.save(tmp, format="GIF")
            resized.close()
            _log_timing("_resize_image_to_fit FIN (sin título, solo resize)", t0)
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] ✅ Imagen {w}x{h} -> {nw}x{nh} (sin título, directo), guardado: {tmp}")
            return (tmp, tmp)
        
        titulo_height = 0
        font = None
        font_size = 32
        if add_title:
            texto = PLATE_PREFIX.strip() if PLATE_PREFIX else "PLACA"
            # Calcular fuente para que "PLACA" abarque todo el ancho horizontal
            if ImageFont is not None and ImageDraw is not None:
                tmp_canvas = PILImage.new("RGB", (DISPLAY_WIDTH, 10), (0, 0, 0))
                tmp_draw = ImageDraw.Draw(tmp_canvas)
                for try_size in range(24, min(120, DISPLAY_HEIGHT), 2):
                    try:
                        f = ImageFont.truetype("arial.ttf", try_size)
                    except Exception:
                        try:
                            f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", try_size)
                        except Exception:
                            try:
                                f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", try_size)
                            except Exception:
                                f = ImageFont.load_default()
                                break
                    bbox = tmp_draw.textbbox((0, 0), texto, font=f)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    font = f
                    font_size = try_size
                    titulo_height = th + 4
                    if tw >= DISPLAY_WIDTH - 4:
                        break
            titulo_height = titulo_height or 32 if add_title else 0

        # Separación entre título e imagen para evitar que se toquen
        title_image_gap = 12 if add_title else 0
        espacio_imagen = DISPLAY_HEIGHT - titulo_height - title_image_gap
        scale_w = DISPLAY_WIDTH / w
        scale_h = espacio_imagen / h
        # Clamp a 1.0: la NPU entrega la imagen en su tamaño final (p. ej. 96×38).
        # Solo escalamos hacia abajo si no cabe; upscaling pixelaba la placa.
        scale = min(1.0, scale_w, scale_h)
        nw = max(1, int(w * scale))
        nh = max(1, int(h * scale))
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] Scale={scale:.4f}, nuevo tamaño: {nw}x{nh}, espacio_imagen={espacio_imagen}px, título={titulo_height}px")
        
        resampler = getattr(getattr(PILImage, "Resampling", None), "LANCZOS", PILImage.LANCZOS)
        resized = im.resize((nw, nh), resampler)
        im.close()
        
        canvas = PILImage.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), (0, 0, 0))
        dx = (DISPLAY_WIDTH - nw) // 2
        if add_title:
            dy = DISPLAY_HEIGHT - nh  # Alineada abajo (debajo del título)
        else:
            dy = (DISPLAY_HEIGHT - nh) // 2  # Centrada verticalmente
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] Imagen en ({dx},{dy}), {'centrada' if not add_title else 'alineada bottom'}")
        canvas.paste(resized, (dx, dy))
        resized.close()
        
        if add_title and ImageDraw is not None and font is not None:
            draw = ImageDraw.Draw(canvas)
            texto = PLATE_PREFIX.strip() if PLATE_PREFIX else "PLACA"
            if font:
                bbox = draw.textbbox((0, 0), texto, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            else:
                tw, th = len(texto) * 6, 10
            tx = (DISPLAY_WIDTH - tw) // 2
            ty = 2  # Margen superior para evitar recorte del borde del texto
            draw.text((tx, ty), texto, fill=(255, 255, 255), font=font)
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] Texto '{texto}' en ({tx},{ty}), tamaño={tw}x{th}, font={font_size}px (abarque horizontal)")
        
        # Convertir a P (paleta 256 colores). quantize suele dar mejor resultado en bordes que convert.
        try:
            canvas = canvas.quantize(colors=256)
        except Exception:
            canvas = canvas.convert("P", palette=PILImage.ADAPTIVE, colors=256)
        fd, tmp = tempfile.mkstemp(suffix=".gif")
        os.close(fd)
        canvas.save(tmp, format="GIF")
        _log_timing("_resize_image_to_fit FIN (PIL done)", t0)
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ✅ Imagen {w}x{h} -> {nw}x{nh}, título={titulo_height}px -> final {DISPLAY_WIDTH}x{DISPLAY_HEIGHT}, guardado: {tmp}")
        return (tmp, tmp)
    except Exception as e:
        import traceback
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ❌ Redimensionado fallido ({src_path}): {e}")
        traceback.print_exc()
        return (src_path, None)

def _send_plate_to_led(item: Dict[str, Any]) -> None:
    """Envía la placa al LED de forma SÍNCRONA.
    - Si SHOW_PLATE_PIC o SHOW_PLATE_SCENE → envía solo la imagen (prevalece).
    - Si no, y SHOW_PLATE_TEXT → envía texto.
    - En cualquier caso retorna cuando el LED ya está mostrando la placa.
    El IDLE posterior lo emite el _consumer_loop (único punto de envío)."""
    plate = (item.get("plate") or "").strip()
    if not plate:
        return
    raw_plate = (item.get("plate_pic_path") or "").strip() or None
    raw_scene = (item.get("scene_pic_path") or "").strip() or None
    plate_pic_path = _resolve_image_path(raw_plate, "plate_pic")
    scene_pic_path = _resolve_image_path(raw_scene, "scene_pic")

    # Imagen de detección: SHOW_PLATE_PIC gana sobre SHOW_PLATE_SCENE si ambos
    # están activos. Si está el flag pero el archivo no se resolvió, cae a texto.
    detection_img_path = None
    if SHOW_PLATE_PIC:
        detection_img_path = plate_pic_path
    elif SHOW_PLATE_SCENE:
        detection_img_path = scene_pic_path
    if (SHOW_PLATE_PIC or SHOW_PLATE_SCENE) and not detection_img_path and (raw_plate or raw_scene):
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] Imagen no encontrada (plate_pic={bool(raw_plate)}, scene_pic={bool(raw_scene)}); se usará texto si SHOW_PLATE_TEXT=true.")

    stay_s = max(1, int(round(SHOW_PLATE_TIME)))

    try:
        # Rama IMAGEN — prevalece sobre texto.
        if detection_img_path:
            _log_timing("PLACA CON FOTO: _send_plate_to_led inicio", time.time())
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] Enviando imagen ({stay_s}s): {detection_img_path}")
            # plate_pic lleva título "PLACA"; scene_pic se envía completa.
            add_title = (detection_img_path == plate_pic_path)
            path_to_send, path_to_del = _resize_image_to_fit(detection_img_path, add_title=add_title)
            _send_picture_sync(path_to_send, stay_s, delete_after_send=path_to_del)
            return

        # Rama TEXTO — solo si SHOW_PLATE_TEXT=true.
        if not SHOW_PLATE_TEXT:
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] SHOW_PLATE_TEXT=false y sin imagen: nada que enviar.")
            return

        text = f"{PLATE_PREFIX.strip()} {plate}" if PLATE_PREFIX else plate
        last_speed = _get_last_speed_safe()
        plate_color = _get_plate_color_for_speed(last_speed)
        color_label = "ROJO" if plate_color == TextColor.RED else "VERDE"
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ENVIANDO TEXTO: '{text}' (color={color_label}, vel={last_speed}, stay={stay_s}s)")

        send_text_over_tcp(
            text=text,
            mode=PLATE_MODE,
            color_code=plate_color,
            font_size_code=TextFontSize.SIZE_40PX,
            align=PLATE_ALIGN,
            speed=PLATE_SPEED,
            stay_time_s=stay_s,
            require_ack=True,
        )
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] LED TEXT ENVIADO: '{text}'", flush=True)

    except Exception as e:
        print(f"[{_ts_str()}] [DISPLAY_MANAGER] ERROR ENVIANDO PLACA AL LED: {e}", flush=True)

# ---------------- Loop consumidor ----------------
def _consumer_loop() -> None:
    """Consumer único de las 2 colas internas (_placas_q, _velocidades_q).
    Reglas:
      - Placa prioritaria: interrumpe velocidad al llegar.
      - Mientras una placa está visible (_plate_busy_until), todo lo demás espera.
      - Velocidad mantiene su programa en el LED hasta que llegue otra velocidad
        o el radar quede silente SPEED_IDLE_TIMEOUT_S segundos (→ IDLE).
    """
    global _plate_busy_until
    print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🚀 Hilo consumidor iniciado")
    speed_end_time = 0.0
    last_shown = "none"        # "none" | "plate" | "speed" | "idle"
    last_program_sent: Optional[int] = None   # último programa enviado al LED
    last_heartbeat = 0.0
    HEARTBEAT_S = 5.0

    while True:
        now = time.time()

        if (now - last_heartbeat) >= HEARTBEAT_S:
            last_ts = _get_last_speed_ts_ms_safe()
            age_s = "∞" if last_ts is None else f"{(_now_ms() - last_ts)/1000:.1f}s"
            led_st, led_at = _get_led_state()
            led_age = f"{(now - led_at):.1f}s" if led_at else "∞"
            print(f"[{_ts_str()}] [LOOP] ♥ led={led_st}(hace {led_age}) last_shown={last_shown} "
                  f"last_prog={last_program_sent} qvel={_velocidades_q.qsize()} "
                  f"qplate={_placas_q.qsize()} radar_age={age_s} "
                  f"plate_busy_in={max(0,_plate_busy_until - now):.2f}s "
                  f"speed_end_in={max(0,speed_end_time - now):.2f}s")
            last_heartbeat = now

        current_mode = get_display_mode()
        if current_mode in ("text", "texto", "picture"):
            mode_label = current_mode.upper()
            try:
                while True:
                    discarded = _placas_q.get_nowait()
                    print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🚫 MODO {mode_label}: Placa descartada: {discarded.get('plate', '?')}")
            except Empty:
                pass
            try:
                while True:
                    discarded = _velocidades_q.get_nowait()
                    print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🚫 MODO {mode_label}: Velocidad descartada: {discarded.get('speed', '?')} km/h")
            except Empty:
                pass
            time.sleep(POLL_SLEEP)
            continue

        # Placa visible: nada más puede entrar hasta que termine.
        if now < _plate_busy_until:
            time.sleep(POLL_SLEEP)
            continue

        # 1) PLACA primero — "imagen mata velocidad".
        try:
            item = _placas_q.get_nowait()
            t_consumer = time.time()
            _log_timing("CONSUMER: placa extraída de cola", t_consumer)
        except Empty:
            item = None

        if item is not None:
            dropped = 0
            try:
                while True:
                    newer = _placas_q.get_nowait()
                    if int(newer.get("ts_ms", 0)) >= int(item.get("ts_ms", 0)):
                        print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🗑 PLACA DESCARTADA (más vieja) '{item.get('plate', '?')}' por una más reciente '{newer.get('plate', '?')}'")
                        item = newer
                    else:
                        print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🗑 PLACA DESCARTADA (más vieja, fuera de orden) '{newer.get('plate', '?')}'")
                    dropped += 1
            except Empty:
                pass
            if dropped:
                print(f"[{_ts_str()}] [DISPLAY_MANAGER] 📦 Procesando PLACA más reciente (se descartaron {dropped}): {item}")
            else:
                print(f"[{_ts_str()}] [DISPLAY_MANAGER] 📦 Procesando PLACA de la cola: {item}")

            plate = item.get("plate")
            ts_ms = item.get("ts_ms", _now_ms())

            if SHOW_PLATE_SPEED:
                last_spd_ts = _get_last_speed_ts_ms_safe()
                if last_spd_ts is None or (_now_ms() - last_spd_ts > 10_000):
                    print(f"[{_ts_str()}] [DISPLAY_MANAGER] ❌ PLACA RECHAZADA '{plate}': "
                          f"SHOW_PLATE_SPEED=true y sin velocidad reciente (last={_fmt_ts(last_spd_ts)})")
                    time.sleep(POLL_SLEEP)
                    continue
            else:
                print(f"[{_ts_str()}] [DISPLAY_MANAGER] SHOW_PLATE_SPEED=false: mostrando placa sin exigir velocidad")

            print(f"[{_ts_str()}] [DISPLAY_MANAGER] ✅ PROCESANDO PLACA VÁLIDA '{plate}' (ts={_fmt_ts(ts_ms)})")
            # Reservar el LED ANTES del TCP: el send del GIF tarda ~2.5s y
            # durante ese tiempo el consumer_thread también debe descartar
            # placas entrantes. Se usa una estimación generosa (PLATE_GIF_BUDGET_S)
            # y después de la transferencia se reajusta al tiempo de display fijo.
            _plate_busy_until = time.time() + PLATE_GIF_BUDGET_S + SHOW_PLATE_TIME
            last_shown = "plate"
            # Drenar lo que quedaba antes de reservar el LED.
            drained_v = 0
            try:
                while True:
                    _velocidades_q.get_nowait()
                    drained_v += 1
            except Empty:
                pass
            drained_p = 0
            try:
                while True:
                    obs = _placas_q.get_nowait()
                    print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🗑 Placa previa descartada: '{obs.get('plate', '?')}'")
                    drained_p += 1
            except Empty:
                pass
            if drained_v or drained_p:
                print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🗑 Drenadas {drained_v} velocidades, {drained_p} placas antes de TX")
            speed_end_time = 0.0

            _log_timing("CONSUMER: ANTES _send_plate_to_led", t_consumer)
            _send_plate_to_led(item)  # síncrono: TCP ~2.5s, bloquea hasta que el GIF llega al LED
            _log_timing("CONSUMER: DESPUÉS _send_plate_to_led", t_consumer)
            _set_led_state(f"plate:{plate}")
            # Reajustar busy_until alineado con el stay_time_s del GIF
            # (lo que el LED internamente mantiene la imagen) + COOLDOWN
            # (para evitar que velocidades o nuevas placas tumben la placa
            # apenas expire). Durante este tiempo el consumer_thread del
            # radar y placas descarta eventos entrantes.
            stay_s = max(1, int(round(SHOW_PLATE_TIME)))
            _plate_busy_until = time.time() + stay_s + PLATE_COOLDOWN_S
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🔒 LED bloqueado {stay_s + PLATE_COOLDOWN_S:.1f}s mostrando placa '{plate}' (stay={stay_s}s + cooldown={PLATE_COOLDOWN_S}s)")

            time.sleep(POLL_SLEEP)
            continue

        # 2) VELOCIDAD.
        if now < speed_end_time:
            time.sleep(POLL_SLEEP)
            continue

        try:
            speed_item = _velocidades_q.get_nowait()
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] 📦 Procesando VELOCIDAD de la cola: {speed_item}")
        except Empty:
            speed_item = None

        if speed_item is not None:
            speed = speed_item.get("speed")
            ts_ms = speed_item.get("ts_ms", _now_ms())
            print(f"    • Velocidad: {speed} km/h")
            print(f"    • Timestamp: {_fmt_ts(ts_ms)}")

            speed_program = _get_program_for_speed(speed)
            _log_program_decision(speed, speed_program, "Programa calculado según velocidad")

            same_prog = (last_program_sent == speed_program)
            arrow = "⟳ MISMO" if same_prog else f"{last_program_sent} → "
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🎯 SPEED {speed} km/h → PROGRAMA {speed_program} ({arrow}{speed_program})")
            t_send = time.time()
            try:
                send_select_program_single(speed_program, save_to_flash=False, require_ack=True)
                last_program_sent = speed_program
                _set_led_state(f"speed:{speed}")
                dt_ms = (time.time() - t_send) * 1000
                print(f"[{_ts_str()}] [DISPLAY_MANAGER] ✅ PROGRAMA {speed_program} OK ({dt_ms:.0f}ms)")
            except Exception as e:
                print(f"[{_ts_str()}] [DISPLAY_MANAGER] ❌ ERROR programa {speed_program}: {e}")

            speed_end_time = now + SHOW_SPEED_TIME
            last_shown = "speed"
            time.sleep(POLL_SLEEP)
            continue

        # 3) Colas vacías. IDLE si algo estaba mostrándose y el radar lleva
        # SPEED_IDLE_TIMEOUT_S sin datos. Timeout medido contra la última
        # velocidad *recibida* (no mostrada): gaps normales entre mediciones
        # no disparan IDLE, evitando parpadeos.
        if last_shown in ("plate", "speed"):
            last_ts = _get_last_speed_ts_ms_safe()
            age_ms = (_now_ms() - last_ts) if last_ts is not None else None
            radar_silent = (age_ms is None) or (age_ms > (SPEED_IDLE_TIMEOUT_S * 1000))
            if radar_silent:
                age_s = "∞" if age_ms is None else f"{age_ms/1000:.1f}s"
                print(f"[{_ts_str()}] [LOOP] → IDLE (tras {last_shown}, radar_age={age_s})")
                _run_idle_now(reason=f"tras {last_shown}, radar_age={age_s}")
                last_program_sent = 1
                last_shown = "idle"

        time.sleep(POLL_SLEEP)

# ---------------- Consumidores del bus SHM ----------------
# Cada canal (radar/lpr/npu) tiene su hilo que lee del bus y alimenta las
# colas internas (_velocidades_q / _placas_q) con el mismo formato que usaba
# el código antiguo. Así el _consumer_loop no cambia.

from shared.shm_bus import EventBus, CHANNEL_RADAR, CHANNEL_LPR, CHANNEL_NPU

# Rate-limit de placas (cross-fuente). Antes vivía en plate_pipeline; ahora
# aquí cubre LPR + NPU con un único filtro — si llega la misma placa por
# ambos servicios, la segunda se ignora.
try:
    _PLATE_MIN_INTERVAL_S = float(_ini.get("DISPLAY_MANAGER", "MIN_INTERVAL_S", fallback="1.2"))
    _PLATE_DEBOUNCE_S = float(_ini.get("DISPLAY_MANAGER", "DEBOUNCE_S", fallback="2.5"))
except Exception:
    _PLATE_MIN_INTERVAL_S = 1.2
    _PLATE_DEBOUNCE_S = 2.5

_plate_rate_lock = threading.Lock()
_plate_last_publish_ts: float = 0.0
_plate_last_seen: Dict[str, float] = {}


def _plate_should_pass(plate: str, now_ts: float) -> Tuple[bool, str]:
    with _plate_rate_lock:
        if (now_ts - _plate_last_publish_ts) < _PLATE_MIN_INTERVAL_S:
            return False, f"min_interval {_PLATE_MIN_INTERVAL_S}s"
        if (now_ts - _plate_last_seen.get(plate, 0.0)) < _PLATE_DEBOUNCE_S:
            return False, f"debounce {_PLATE_DEBOUNCE_S}s"
        return True, "ok"


def _plate_mark_passed(plate: str, now_ts: float) -> None:
    global _plate_last_publish_ts
    with _plate_rate_lock:
        _plate_last_publish_ts = now_ts
        _plate_last_seen[plate] = now_ts


def _radar_consumer_thread() -> None:
    """Lee velocidades del bus 'radar'. Mientras haya una placa visible
    (_plate_busy_until vigente), descarta las velocidades — el sistema es
    deliberadamente 'sordo' al radar hasta que la placa termine de mostrarse.
    Así evitamos que velocidades encoladas durante la placa salgan
    inmediatamente al LED cuando expira y causen un parpadeo."""
    global _last_radar_speed, _last_radar_ts_ms
    bus = EventBus(CHANNEL_RADAR, role="consumer")
    print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🚁 Consumer bus radar activo")
    while True:
        evt = bus.read_blocking(poll_interval=0.001)
        speed = evt.get("speed")
        ts_ms = int(evt.get("ts_ms") or _now_ms())
        if speed is None:
            continue
        # Actualiza el estado local siempre (para SHOW_PLATE_SPEED y colores)
        # aunque descartemos la velocidad para el LED.
        with _radar_state_lock:
            _last_radar_speed = float(speed)
            _last_radar_ts_ms = ts_ms
        # Sordo al radar durante placa activa: no encolar.
        remaining = _plate_busy_until - time.time()
        if remaining > 0:
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🔇 Sordo al radar (placa activa, restan {remaining:.2f}s): descartada vel={speed}")
            continue
        payload = {"speed": float(speed), "ts_ms": ts_ms}
        _offer(_velocidades_q, payload)


def _plate_consumer_thread(channel: str, source_label: str) -> None:
    """Lee placas del bus y las encola (con rate-limit cross-fuente).
    Mientras haya una placa visible (_plate_busy_until vigente), descarta
    las placas entrantes — se muestra una sola placa a la vez y las que
    llegan durante su display time se botan para evitar encadenamiento
    que se ve como parpadeo."""
    bus = EventBus(channel, role="consumer")
    print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🚗 Consumer bus {channel} ({source_label}) activo")
    while True:
        evt = bus.read_blocking(poll_interval=0.001)
        plate = (evt.get("plate") or "").strip()
        if not plate:
            continue
        # Sordo a placas durante placa activa: se descarta.
        remaining = _plate_busy_until - time.time()
        if remaining > 0:
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] 🔇 Placa activa (restan {remaining:.2f}s): descartada '{plate}' ({source_label})")
            continue
        now_ts = time.time()
        ok, reason = _plate_should_pass(plate, now_ts)
        if not ok:
            print(f"[{_ts_str()}] [DISPLAY_MANAGER] RATE-LIMIT omitida '{plate}' ({source_label}): {reason}")
            continue
        _plate_mark_passed(plate, now_ts)
        payload = {
            "plate": plate,
            "ts_ms": int(evt.get("ts_ms") or _now_ms() * 1),
        }
        if evt.get("plate_pic_path"):
            payload["plate_pic_path"] = evt["plate_pic_path"]
        if evt.get("scene_pic_path"):
            payload["scene_pic_path"] = evt["scene_pic_path"]
        _offer(_placas_q, payload)


def start_shm_consumers() -> None:
    """Lanza los 3 hilos consumidores del bus SHM."""
    threading.Thread(target=_radar_consumer_thread, daemon=True, name="shm-radar").start()
    threading.Thread(target=_plate_consumer_thread, args=(CHANNEL_LPR, "lpr"),
                     daemon=True, name="shm-lpr").start()
    threading.Thread(target=_plate_consumer_thread, args=(CHANNEL_NPU, "npu"),
                     daemon=True, name="shm-npu").start()


def start_display_manager() -> threading.Thread:
    start_shm_consumers()
    t = threading.Thread(target=_consumer_loop, daemon=True, name="display-manager")
    t.start()
    print(f"[DISPLAY_MANAGER] 🚀 Display manager iniciado en hilo: {t.name}")
    print(f"[DISPLAY_MANAGER] ✅ PREFIX='{PLATE_PREFIX}', SPEED={PLATE_SPEED}, MODE={PLATE_MODE.name}")
    return t
