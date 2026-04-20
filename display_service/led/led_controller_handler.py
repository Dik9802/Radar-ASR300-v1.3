# led_controller_handler.py – Construcción y envío de mensajes (usa led_controller_socket para I/O)
import os
import socket
import struct
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Tuple, Optional
from enum import IntEnum
from datetime import datetime

try:
    from PIL import Image
except Exception:
    Image = None

from .led_controller_constants import (
    ID_CODE, CARD_ID, FLAGS, TIMEOUT_SECONDS,
    WINDOW_NO, MODE, SPEED, CHUNK_SIZE, GIF_OFFSET_Y,
)

# === Cargar configuración de display ===
try:
    from shared.config_loader import read_ini, get_int
    _ini = read_ini(apply_env_overrides=True)
    LED_DISPLAY_WIDTH = get_int(_ini, "DISPLAY_MANAGER", "DISPLAY_WIDTH", 0) or 0
    LED_DISPLAY_HEIGHT = get_int(_ini, "DISPLAY_MANAGER", "DISPLAY_HEIGHT", 0) or 0
    print(f"[LED_HANDLER] Configuración de display cargada: {LED_DISPLAY_WIDTH}x{LED_DISPLAY_HEIGHT}")
except Exception as e:
    LED_DISPLAY_WIDTH = 0
    LED_DISPLAY_HEIGHT = 0
    print(f"[LED_HANDLER] Error cargando config de display: {e}, usando 0x0")

# <<< Capa de transporte >>>
from .led_controller_socket import (
    ensure_connected, is_connected, close_connection, verify_connection,
    tcp_session,
)

# === UTILIDADES DE LOG DETALLADO ===
def _ts_str() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def _thread_info() -> str:
    return f"[HILO:{threading.current_thread().name}]"

def _log_function_entry(func_name: str, **kwargs):
    """Log de entrada a función con parámetros"""
    params = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
    print(f"[{_ts_str()}] {_thread_info()} [LED_HANDLER] >>> INICIANDO {func_name}({params})")

def _log_function_exit(func_name: str, result=None, duration_ms=None):
    """Log de salida de función con resultado"""
    duration_str = f" [{duration_ms:.1f}ms]" if duration_ms else ""
    result_str = f" -> {result}" if result is not None else ""
    print(f"[{_ts_str()}] {_thread_info()} [LED_HANDLER] <<< COMPLETADO {func_name}{result_str}{duration_str}")

def _log_network_operation(operation: str, details: str):
    """Log de operaciones de red"""
    print(f"[{_ts_str()}] {_thread_info()} [LED_NETWORK] {operation}: {details}")

def _hex_frame(data: bytes, max_display: int = 512) -> str:
    """Formatea bytes como hex (xx xx xx ...). Si excede max_display, trunca y añade '(+N bytes)'."""
    n = len(data)
    show = data[:max_display]
    hex_str = " ".join(f"{b:02x}" for b in show)
    if n > max_display:
        hex_str += f" ... (+{n - max_display} bytes)"
    return f"{hex_str}  [{n} bytes]"

def _log_ack_details(acks: List[dict], expected_count: int):
    """Log detallado de ACKs recibidos"""
    print(f"[{_ts_str()}] {_thread_info()} [LED_ACK] Esperados: {expected_count}, Recibidos: {len(acks)}")
    for i, ack in enumerate(acks):
        status = "OK" if ack.get('rr', 1) == 0 else "ERROR"
        checksum_status = "OK" if ack.get('checksum_ok', False) else "FAIL"
        print(f"[{_ts_str()}] {_thread_info()} [LED_ACK] ACK[{i}]: status={status}, "
              f"po={ack.get('po', '?')}, tp={ack.get('tp', '?')}, checksum={checksum_status}, "
              f"rr=0x{ack.get('rr', 0):02X}")

# =========================
# Enums (texto Rich3)
# =========================
class TextMode(IntEnum):
    DRAW = 0
    IMMEDIATE = 1
    COVER = 2

class TextColor(IntEnum):
    RED = 1
    GREEN = 2
    YELLOW = 3
    BLUE = 4
    PURPLE = 5
    CYAN = 6
    WHITE = 7

class TextFontSize(IntEnum):
    SIZE_8PX = 0
    SIZE_12PX = 1
    SIZE_16PX = 2
    SIZE_24PX = 3
    SIZE_32PX = 4
    SIZE_40PX = 5
    SIZE_48PX = 6
    SIZE_56PX = 7

class TextAlign(IntEnum):
    LEFT = 0
    CENTER = 1
    RIGHT = 2

class TextEffect(IntEnum):
    """Efectos especiales para texto e imágenes (Special effect for text and picture)"""
    DRAW = 0
    OPEN_FROM_LEFT = 1
    OPEN_FROM_RIGHT = 2
    OPEN_FROM_CENTER_H = 3          # Horizontal
    OPEN_FROM_CENTER_V = 4          # Vertical
    SHUTTER_V = 5                   # Vertical
    MOVE_LEFT = 6
    MOVE_RIGHT = 7
    MOVE_UP = 8
    MOVE_DOWN = 9
    SCROLL_UP = 10
    SCROLL_LEFT = 11
    SCROLL_RIGHT = 12
    FLICKER = 13
    CONTINUOUS_SCROLL_LEFT = 14
    CONTINUOUS_SCROLL_RIGHT = 15
    SHUTTER_H = 16                  # Horizontal
    CLOCKWISE_OPEN = 17
    ANTICLOCKWISE_OPEN = 18
    WINDMILL = 19
    WINDMILL_ANTICLOCKWISE = 20
    RECTANGLE_FORTH = 21
    RECTANGLE_ENTAD = 22
    QUADRANGLE_FORTH = 23
    QUADRANGLE_ENTAD = 24
    CIRCLE_FORTH = 25
    CIRCLE_ENTAD = 26
    OPEN_FROM_LEFT_UP = 27
    OPEN_FROM_RIGHT_UP = 28
    OPEN_FROM_LEFT_BOTTOM = 29
    OPEN_FROM_RIGHT_BOTTOM = 30
    BEVEL_OPEN = 31
    ANTIBEVEL_OPEN = 32
    ENTER_FROM_LEFT_UP = 33
    ENTER_FROM_RIGHT_UP = 34
    ENTER_FROM_LEFT_BOTTOM = 35
    ENTER_FROM_RIGHT_BOTTOM = 36
    BEVEL_ENTER = 37
    ANTIBEVEL_ENTER = 38
    ZEBRA_H = 39                    # Horizontal zebra crossing
    ZEBRA_V = 40                    # Vertical zebra crossing
    MOSAIC_BIG = 41
    MOSAIC_SMALL = 42
    RADIATION_UP = 43
    RADIATION_DOWN = 44
    AMASS = 45
    DROP = 46
    COMBINATION_H = 47              # Horizontal
    COMBINATION_V = 48              # Vertical
    BACKOUT = 49
    SCREWING_IN = 50
    CHESSBOARD_H = 51               # Horizontal
    CHESSBOARD_V = 52               # Vertical
    CONTINUOUS_SCROLL_UP = 53
    CONTINUOUS_SCROLL_DOWN = 54
    # 55, 56 = Reserved
    GRADUAL_BIGGER_UP = 57
    GRADUAL_SMALLER_DOWN = 58
    # 59 = Reserved
    GRADUAL_BIGGER_V = 60           # Vertical
    FLICKER_H = 61                  # Horizontal
    FLICKER_V = 62                  # Vertical
    SNOW = 63
    SCROLL_DOWN = 64
    SCROLL_LEFT_TO_RIGHT = 65
    OPEN_TOP_TO_BOTTOM = 66
    SECTOR_EXPAND = 67
    # 68 = Reserved
    ZEBRA_CROSSING_H = 69           # Horizontal
    ZEBRA_CROSSING_V = 70           # Vertical
    RANDOM = 255                    # Efecto aleatorio

class PictureEffect(IntEnum):
    """Efectos de imagen (Picture effect code)"""
    CENTER = 0
    ZOOM = 1
    STRETCH = 2
    TILE = 3

# =========================
# Utiles binarios
# =========================
def u16_le(v: int) -> bytes: return struct.pack('<H', v & 0xFFFF)
def u16_be(v: int) -> bytes: return struct.pack('>H', v & 0xFFFF)
def u32_le(v: int) -> bytes: return struct.pack('<I', v & 0xFFFFFFFF)
def u32_be(v: int) -> bytes: return struct.pack('>I', v & 0xFFFFFFFF)

def checksum(inner: bytes) -> bytes:
    return u16_le(sum(inner) & 0xFFFF)

# =========================
# Building: CC=0x03 (GIF)
# =========================
def build_cc03_header(
    window_no: int,
    mode: int,
    speed: int,
    stay_time_s: int,
    image_format: int = 1,
    x: int = 0,
    y: int = 0,
) -> bytes:
    return (
        bytes([0x03, window_no & 0xFF, mode & 0xFF, speed & 0xFF]) +
        u16_be(stay_time_s) +
        bytes([image_format & 0xFF]) +
        u16_be(x) + u16_be(y)
    )

def chunk_cc(cc_header: bytes, body: bytes, chunk_size: int) -> List[bytes]:
    room = max(0, chunk_size - len(cc_header))
    parts = [cc_header + body[:room]]
    off = room
    while off < len(body):
        parts.append(body[off:off+chunk_size])
        off += chunk_size
    return parts

def build_network_packet(idcode: int, card_id: int, flags: int, cc_chunk: bytes, po: int, tp: int) -> bytes:
    inner = (
        bytes([0x68, 0x32, card_id & 0xFF, 0x7B, flags & 0xFF]) +
        u16_le(len(cc_chunk)) +
        bytes([po & 0xFF, tp & 0xFF]) +
        cc_chunk
    )
    net_len = u16_le(len(inner) + 2)
    hdr = u32_be(idcode) + net_len + b'\x00\x00'
    return hdr + inner + checksum(inner)


def build_network_packet_legacy(idcode: int, card_id: int, flags: int, cc_chunk: bytes) -> bytes:
    """Formato que usa el programa externo que funciona: 4B len, 4B cc_len, sin po/tp."""
    inner = (
        bytes([0x68, 0x32, card_id & 0xFF, 0x7B, flags & 0xFF]) +
        u32_le(len(cc_chunk)) +
        cc_chunk
    )
    total_len = len(inner) + 2
    hdr = u32_be(idcode) + u32_le(total_len)
    return hdr + inner + checksum(inner)

def build_packets_for_gif(gif_path: str, stay_time_s: int) -> Tuple[List[bytes], int, int]:
    data = Path(gif_path).read_bytes()
    if not (len(data) >= 13 and data[:6] in (b"GIF89a", b"GIF87a")):
        raise ValueError("El archivo no es un GIF válido (GIF87a/GIF89a).")
    w, h = struct.unpack('<HH', data[6:10])
    cc_header = build_cc03_header(WINDOW_NO, MODE, SPEED, stay_time_s, 1, x=0, y=GIF_OFFSET_Y)
    parts = chunk_cc(cc_header, data, chunk_size=CHUNK_SIZE)
    tp = len(parts) - 1
    packets = [build_network_packet(ID_CODE, CARD_ID, FLAGS, p, i, tp) for i, p in enumerate(parts)]
    return packets, w, h

# =========================
# ACK helpers (lectura)
# =========================
def read_one_network_packet(session) -> bytes:
    _log_network_operation("READ_ACK", f"Esperando paquete con timeout {TIMEOUT_SECONDS}s")
    session.set_timeout(TIMEOUT_SECONDS)
    start_time = time.time()
    
    head = session.recv_exact(8)  # ID(4) + NetLen(2 LE) + Res(2)
    net_len = struct.unpack('<H', head[4:6])[0]
    inner = session.recv_exact(net_len)
    
    duration_ms = (time.time() - start_time) * 1000
    _log_network_operation("READ_ACK", f"Paquete recibido en {duration_ms:.1f}ms, tamaño={len(head + inner)} bytes")
    
    return head + inner

def parse_return_packet(pkt: bytes) -> dict:
    net_len = struct.unpack('<H', pkt[4:6])[0]
    inner = pkt[8:8+net_len]
    if len(inner) < 11:
        raise ValueError("ACK muy corto")
    pt, ct, card_id, cmd, rr = inner[0], inner[1], inner[2], inner[3], inner[4]
    ll = struct.unpack('<H', inner[5:7])[0]
    po, tp = inner[7], inner[8]
    chk_ok = (inner[-2:] == checksum(inner[:-2]))
    return {
        'pt': pt, 'ct': ct, 'card_id': card_id, 'cmd': cmd, 'rr': rr,
        'll': ll, 'po': po, 'tp': tp, 'checksum_ok': chk_ok
    }

# =========================
# Envío (usa capa de socket)
# =========================
_led_send_lock = threading.Lock()  # Mutex: un solo hilo envía a la controladora a la vez

def send_packets_over_tcp(packets: List[bytes], require_ack: bool) -> List[dict]:
    """
    Conecta al controlador, envía todos los paquetes, lee ACKs si aplica, y se desconecta.
    No mantiene conexión persistente. Manejo de excepciones: ante error TCP retorna lista vacía.
    """
    start_time = time.time()
    _log_function_entry("send_packets_over_tcp", 
                       packet_count=len(packets), 
                       require_ack=require_ack, 
                       flags=f"0x{FLAGS:02X}")
    
    acks: List[dict] = []
    
    # Mutex se mantiene hasta que la transmisión termine: ACK recibido o timeout 500ms, y conexión cerrada.
    # _send_packets_inner bloquea hasta que tcp_session cierre el socket (en su finally).
    t_lock_wait = time.time()
    _log_network_operation("MUTEX", "Esperando _led_send_lock...")
    with _led_send_lock:
        t_lock_held = time.time()
        _log_network_operation("MUTEX", f"Mutex adquirido (espera={(t_lock_held-t_lock_wait)*1000:.0f}ms)")
        try:
            _send_packets_inner(packets, require_ack, acks)
            # Aquí la transmisión ya terminó (ACK o timeout) y tcp_session cerró la conexión
        except (OSError, ConnectionError, TimeoutError, socket.timeout, BrokenPipeError) as e:
            _log_network_operation("ERROR", f"Excepción TCP (no se cuelga): {type(e).__name__}: {e}")
        except Exception as e:
            _log_network_operation("ERROR", f"Excepción inesperada: {type(e).__name__}: {e}")
        _log_network_operation("MUTEX", f"Mutex liberado (transmisión terminada, conexión cerrada, en_mutex={(time.time()-t_lock_held)*1000:.0f}ms)")
    
    duration_ms = (time.time() - start_time) * 1000
    _log_function_exit("send_packets_over_tcp", 
                      result=f"{len(acks)} ACKs recibidos", 
                      duration_ms=duration_ms)
    return acks


def _send_packets_inner(packets: List[bytes], require_ack: bool, acks: List[dict]) -> None:
    """Cuerpo de send_packets_over_tcp (para manejo de excepciones en la capa superior).
    Siempre espera ACK; si llega, tcp_session cierra inmediatamente; si no, espera 500ms."""
    t_inner = time.time()
    ack_received_ref = [False]  # True si llegaron todos los ACKs esperados → cierre inmediato
    _log_network_operation("TCP", "Entrando a tcp_session (connect)...")
    with tcp_session(ack_received_ref) as session:
        _log_network_operation("TCP", f"Conectado. Enviando {len(packets)} paquetes (t={(time.time()-t_inner)*1000:.0f}ms)")
        # Enviar todos los paquetes
        _log_network_operation("SEND", f"Enviando {len(packets)} paquetes...")
        for i, pkt in enumerate(packets):
            packet_start = time.time()
            session.sendall(pkt)
            packet_duration = (time.time() - packet_start) * 1000
            _log_network_operation("SEND", f"Paquete {i}/{len(packets)-1} enviado en {packet_duration:.1f}ms, tamaño={len(pkt)} bytes")
            _log_network_operation("TX_HEX", _hex_frame(pkt))

        # Manejo de ACKs: siempre esperamos (FLAGS=0x01). Si llegan todos → cierre inmediato.
        if (FLAGS & 0x01):
            _log_network_operation("ACK", f"Esperando ACKs (timeout={TIMEOUT_SECONDS}s)...")
            expected = len(packets)
            deadline = time.time() + TIMEOUT_SECONDS
            ack_count = 0
            while time.time() < deadline:
                if len(acks) >= expected:
                    break
                try:
                    rpkt = read_one_network_packet(session)
                    ack = parse_return_packet(rpkt)
                    acks.append(ack)
                    ack_count += 1
                    
                    status = "OK" if ack.get('rr', 1) == 0 else f"ERROR(0x{ack.get('rr', 0):02X})"
                    _log_network_operation("ACK", f"ACK {ack_count} recibido: {status}, po={ack.get('po')}, tp={ack.get('tp')}")
                    
                except Exception as e:
                    _log_network_operation("ACK", f"Error leyendo ACK: {e}")
                    break
            
            if len(acks) >= expected:
                ack_received_ref[0] = True  # Cierre inmediato al salir de tcp_session
        
            _log_ack_details(acks, expected)
            ok_count = sum(1 for a in acks if a.get("rr", 1) == 0)
            if len(acks) >= expected and ok_count == len(acks):
                _log_network_operation("ACK", f"ACKs confirmados: {len(acks)}/{expected} → cierre inmediato")
            elif len(acks) < expected:
                _log_network_operation("ACK", f"ACKs incompletos: {len(acks)}/{expected} → espera 500ms antes de cerrar")
            else:
                _log_network_operation("ACK", f"ACKs con error: {ok_count}/{len(acks)} OK")
        else:
            _log_network_operation("ACK", "FLAGS sin bit ACK, esperando 500ms antes de cerrar")
        _log_network_operation("TCP", f"tcp_session terminando (total={(time.time()-t_inner)*1000:.0f}ms)")

# =========================
# Alto nivel: GIF
# =========================
def _resize_and_convert_to_gif(src_path: str, target_w: int, target_h: int) -> str:
    """Redimensiona imagen para que encaje (fit) en target_w x target_h, centra en canvas negro, guarda como GIF.
    Retorna path al GIF temporal. Si ya tiene el tamaño exacto, copia sin reconvertir (evita artefactos en bordes)."""
    if Image is None:
        raise ValueError("PIL no está disponible para redimensionar/convertir.")
    
    from PIL import Image as PILImage
    
    im = PILImage.open(src_path)
    orig_w, orig_h = im.size
    if orig_w == target_w and orig_h == target_h and im.mode == "P":
        im.close()
        import shutil
        fd, tmp_path = tempfile.mkstemp(suffix=".gif")
        os.close(fd)
        shutil.copy2(src_path, tmp_path)
        print(f"[{_ts_str()}] [LED_HANDLER] GIF ya {target_w}x{target_h}, usando sin reconvertir", flush=True)
        return tmp_path
    
    im = im.convert("RGB")
    scale = min(target_w / orig_w, target_h / orig_h)
    new_w = max(1, int(orig_w * scale))
    new_h = max(1, int(orig_h * scale))
    
    resampler = getattr(getattr(PILImage, "Resampling", None), "LANCZOS", PILImage.LANCZOS)
    resized = im.resize((new_w, new_h), resampler)
    im.close()
    
    canvas = PILImage.new("RGB", (target_w, target_h), (0, 0, 0))
    dx = (target_w - new_w) // 2
    dy = (target_h - new_h) // 2
    canvas.paste(resized, (dx, dy))
    resized.close()
    
    try:
        canvas = canvas.quantize(colors=256)
    except Exception:
        canvas = canvas.convert("P", palette=PILImage.ADAPTIVE, colors=256)
    fd, tmp_path = tempfile.mkstemp(suffix=".gif")
    os.close(fd)
    canvas.save(tmp_path, format="GIF")
    canvas.close()
    
    print(f"[{_ts_str()}] [LED_HANDLER] Imagen redimensionada: {orig_w}x{orig_h} -> {new_w}x{new_h} en canvas {target_w}x{target_h}", flush=True)
    return tmp_path


def send_gif_over_tcp(gif_path: str, stay_time_s: int, require_ack: bool = True) -> List[dict]:
    t_gif = time.time()
    _log_network_operation("GIF", "send_gif_over_tcp INICIO")
    _log_function_entry("send_gif_over_tcp", 
                       gif_path=gif_path, 
                       stay_time_s=stay_time_s, 
                       require_ack=require_ack)
    
    tmp_to_delete = None
    
    # SIEMPRE redimensionar si tenemos configuración de display y PIL disponible
    print(f"[{_ts_str()}] [LED_HANDLER] send_gif_over_tcp: LED_DISPLAY={LED_DISPLAY_WIDTH}x{LED_DISPLAY_HEIGHT}, PIL={'OK' if Image else 'NO'}", flush=True)
    if LED_DISPLAY_WIDTH > 0 and LED_DISPLAY_HEIGHT > 0 and Image is not None:
        try:
            _log_network_operation("GIF", "_resize_and_convert_to_gif INICIO")
            tmp_to_delete = _resize_and_convert_to_gif(gif_path, LED_DISPLAY_WIDTH, LED_DISPLAY_HEIGHT)
            _log_network_operation("GIF", f"_resize_and_convert_to_gif FIN (+{(time.time()-t_gif)*1000:.0f}ms)")
            gif_path = tmp_to_delete
        except Exception as e:
            print(f"[{_ts_str()}] [LED_HANDLER] ⚠ Error redimensionando imagen: {e}", flush=True)
    else:
        print(f"[{_ts_str()}] [LED_HANDLER] ⚠ NO se redimensiona: WIDTH={LED_DISPLAY_WIDTH}, HEIGHT={LED_DISPLAY_HEIGHT}, PIL={Image}", flush=True)
        # Sin redimensionamiento: verificar si es GIF y convertir si no
        try:
            with open(gif_path, "rb") as f:
                head = f.read(6)
            is_gif = head in (b"GIF89a", b"GIF87a")
        except Exception:
            is_gif = False

        if not is_gif:
            if Image is None:
                raise ValueError("El archivo no es GIF y PIL no está disponible para convertir.")
            tmp_gif_path = os.path.splitext(gif_path)[0] + "_converted.gif"
            from PIL import Image as PILImage
            with PILImage.open(gif_path) as img:
                img.save(tmp_gif_path, format="GIF")
            gif_path = tmp_gif_path
            tmp_to_delete = tmp_gif_path
            print(f"[INFO] Archivo convertido a GIF: {gif_path}", flush=True)

    try:
        t_build = time.time()
        _log_network_operation("GIF", "build_packets_for_gif INICIO")
        packets, w, h = build_packets_for_gif(gif_path, stay_time_s)
        _log_network_operation("GIF", f"build_packets_for_gif FIN: {len(packets)} paquetes (+{(time.time()-t_build)*1000:.0f}ms)")
        print(f"", flush=True)
        print(f"╔══════════════════════════════════════════════════════════════╗", flush=True)
        print(f"║ GIF ENVIANDO: {w}x{h} píxeles → {len(packets)} paquetes", flush=True)
        print(f"║ CONFIG: LED_DISPLAY_WIDTH={LED_DISPLAY_WIDTH}, LED_DISPLAY_HEIGHT={LED_DISPLAY_HEIGHT}", flush=True)
        print(f"╚══════════════════════════════════════════════════════════════╝", flush=True)
        
        _log_network_operation("GIF", f"send_packets_over_tcp INICIO (total hasta aquí: {(time.time()-t_gif)*1000:.0f}ms)")
        result = send_packets_over_tcp(packets, require_ack=require_ack)
        _log_network_operation("GIF", f"send_gif_over_tcp FIN (+{(time.time()-t_gif)*1000:.0f}ms total)")
        return result
    finally:
        if tmp_to_delete and os.path.isfile(tmp_to_delete):
            try:
                os.remove(tmp_to_delete)
            except Exception:
                pass

# =========================
# Building/alto nivel: Texto Rich3 (CC=0x02)
# =========================
def build_cc02_header_legacy(
    window_no: int,
    mode: int,
    align: int,
    speed: int,
    stay_time_s: int,
    font_size_code: int = 0,
) -> bytes:
    """CC02 en 7 bytes: 02, w, mode, align, speed, font_size, stay. Byte 5 = tamaño de fuente (0-7)."""
    return bytes([0x02, window_no & 0xFF, mode & 0xFF, align & 0xFF, speed & 0xFF, font_size_code & 0x0F, stay_time_s & 0xFF])

def encode_rich3_text(text: str, color_code: int, font_size_code: int, style_byte: Optional[int] = None) -> bytes:
    hdr_byte = (style_byte & 0xFF) if style_byte is not None else ((color_code & 0x0F) << 4) | (font_size_code & 0x0F)
    out = bytearray()
    for ch in text:
        cp = ord(ch)
        hi = (cp >> 8) & 0xFF
        lo = cp & 0xFF
        out += bytes([hdr_byte, hi, lo])
    out += b'\x00\x00\x00'
    return bytes(out)

def build_packets_for_text(
    text: str,
    effect: int,
    color_code: int,
    font_size_code: int,
    align: int,
    speed: int,
    stay_time_s: int,
    window_no: int,
    chunk_size: int = CHUNK_SIZE,
) -> List[bytes]:
    CARD_ID_LEGACY = 0x01
    stay_b = max(1, min(255, int(stay_time_s)))
    speed_b = max(1, min(100, int(speed))) if speed > 0 else 1
    cc_header = build_cc02_header_legacy(window_no, effect, align, speed_b, stay_b, font_size_code)
    body = encode_rich3_text(text, color_code, font_size_code)
    cc_chunk = cc_header + body
    return [build_network_packet_legacy(ID_CODE, CARD_ID_LEGACY, FLAGS, cc_chunk)]

def send_text_over_tcp(
    text: str,
    mode: TextMode,
    color_code: TextColor,
    font_size_code: TextFontSize,
    align: TextAlign,
    speed: int,
    stay_time_s: int,
    require_ack: bool = True,
    effect: int = None,
) -> List[dict]:
    """
    Envía texto al display LED.
    
    Args:
        text: Texto a mostrar
        mode: Modo de texto (DRAW, IMMEDIATE, COVER) - usado si effect es None
        color_code: Color del texto
        font_size_code: Tamaño de fuente
        align: Alineación
        speed: Velocidad de animación (1-100, menor = más rápido)
        stay_time_s: Tiempo en pantalla (segundos)
        require_ack: Esperar confirmación
        effect: Efecto especial (TextEffect). Si se especifica, ignora mode.
    """
    # Usar effect si se especifica, sino usar mode
    effect_code = effect if effect is not None else int(mode)
    effect_name = f"effect={effect_code}" if effect is not None else f"mode={mode.name if hasattr(mode, 'name') else mode}"
    
    # Obtener nombres para logging (soporta tanto enums como enteros)
    color_name = color_code.name if hasattr(color_code, 'name') else str(color_code)
    font_name = font_size_code.name if hasattr(font_size_code, 'name') else str(font_size_code)
    align_name = align.name if hasattr(align, 'name') else str(align)
    
    _log_function_entry("send_text_over_tcp", 
                       text=f"'{text}'", 
                       effect=effect_name, 
                       color=color_name, 
                       font=font_name, 
                       align=align_name,
                       speed=speed,
                       stay_time_s=stay_time_s,
                       require_ack=require_ack)
    
    packets = build_packets_for_text(
        text,
        effect_code, int(color_code), int(font_size_code), int(align),
        speed, stay_time_s, window_no=0
    )
    
    print(f'[{_ts_str()}] {_thread_info()} [LED_HANDLER] TEXT "{text}" → {len(packets)} paquetes, font={font_name}({int(font_size_code)}), {effect_name}, stay={stay_time_s}s', flush=True)
    
    result = send_packets_over_tcp(packets, require_ack=require_ack)
    
    _log_function_exit("send_text_over_tcp", 
                      result=f"Texto enviado, {len(result)} ACKs")
    
    return result


# =========================
# Select program (CC=0x08)
# Formato esperado: 08 00 [slot] [program]  (slot=1, program=20 -> 08 00 01 14)
# =========================
def _build_cc08_program(program_number: int, save_to_flash: bool) -> bytes:
    n = int(program_number) & 0xFF  # programa 1-255
    slot = 0x01
    return bytes([0x08, 0x00, slot & 0xFF, n & 0xFF])

def build_packets_for_select_program_single(program_number: int,
                                            save_to_flash: bool,
                                            chunk_size: int = CHUNK_SIZE) -> List[bytes]:
    if not (0 <= int(program_number) <= 0xFFFF):
        raise ValueError(f"Programa fuera de rango: {program_number} (válido: 0-{0xFFFF})")
    CARD_ID_LEGACY = 0x01
    cc_chunk = _build_cc08_program(program_number, save_to_flash)  # 08 00 XX YY
    return [build_network_packet_legacy(ID_CODE, CARD_ID_LEGACY, FLAGS, cc_chunk)]

def send_select_program_single(program_number: int,
                               save_to_flash: bool = False,
                               require_ack: bool = True) -> List[dict]:
    _log_function_entry("send_select_program_single", 
                       program_number=program_number, 
                       save_to_flash=save_to_flash, 
                       require_ack=require_ack)
    
    program_name = "IDLE" if program_number == 1 else f"PROGRAMA_{program_number}"
    packets = build_packets_for_select_program_single(program_number, save_to_flash)
    
    print(f"[{_ts_str()}] {_thread_info()} [LED_HANDLER] SELECT PROGRAMA {program_name} (0x08) → {len(packets)} paquetes; save={save_to_flash}", flush=True)
    
    result = send_packets_over_tcp(packets, require_ack=require_ack)
    
    success_count = sum(1 for ack in result if ack.get('rr', 1) == 0)
    status = f"ÉXITO ({success_count}/{len(result)} ACKs OK)" if result else "ENVIADO (sin ACK)"
    
    _log_function_exit("send_select_program_single", 
                      result=f"Programa {program_name}: {status}")
    
    return result

# (Re-export utilidades de conexión para compatibilidad con main.py)
__all__ = [
    "ensure_connected", "is_connected", "close_connection",
    "send_gif_over_tcp", "send_text_over_tcp", "send_select_program_single",
    "TextMode", "TextColor", "TextFontSize", "TextAlign", "TextEffect", "PictureEffect",
]

def start_led_manager():
    """Inicia el manager del controlador LED en un hilo separado"""
    def led_manager_thread():
        try:
            print(f"[{_ts_str()}] [LED] Iniciando conexión...")
            ensure_connected(blocking=False)
            print(f"[{_ts_str()}] [LED] Manager iniciado correctamente")
        except Exception as e:
            print(f"[{_ts_str()}] [LED] Error iniciando manager: {e}")
    
    thread = threading.Thread(target=led_manager_thread, daemon=True, name="led-manager")
    thread.start()
    print(f"[{_ts_str()}] [LED] Manager iniciado en hilo separado")
    return thread