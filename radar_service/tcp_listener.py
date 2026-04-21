"""
radar_tcp.py — Servidor TCP para radares de velocidad.

Escucha conexiones TCP del radar, extrae la velocidad según el protocolo del modelo
configurado y la publica al display_manager. Incluye rate-limit por actualización
y soporte para múltiples modelos de radar (LDTR20, STALKER, TSR20).

Configuración (config.ini):
    [RADAR_TCP]:
        MODEL, LISTEN_IP, LISTEN_PORT, ADD_NOISE, LOG_RX, UPDATE_MIN_DELTA_MS.
    [RADAR_SIMULATOR]:
        ON               Si true, envía velocidades simuladas periódicas (se superpone al radar físico).
        INTERVAL_MS       Intervalo en ms entre envíos del simulador.
        MAX_SPEED         Velocidad máxima (km/h) del simulador.
        MIN_SPEED         Velocidad mínima (km/h) del simulador.

API pública:
    get_last_speed()       -> (speed, ts_ms)  Última velocidad y timestamp.
    get_system_speed()     -> speed           Solo la última velocidad.
    get_last_speed_ts_ms() -> ts_ms           Solo el timestamp.
    extract_speed(line)    -> speed | None    Parsea una línea (modelo actual).
    start_radar_manager()  -> Thread          Arranca el servidor TCP en un hilo independiente.
"""
import random
import socket
import threading
import time
from typing import Optional, Tuple, Callable

# -----------------------------------------------------------------------------
# Configuración desde config.ini [RADAR_TCP] y [RADAR_SIMULATOR]
# -----------------------------------------------------------------------------
try:
    from shared.config_loader import read_ini, get_str, get_int, get_bool, get_float, get_listen_config
    config = read_ini(apply_env_overrides=True)
    HOST, PORT = get_listen_config(config, "RADAR_TCP", "0.0.0.0", 12345)
    MODEL = (get_str(config, "RADAR_TCP", "MODEL", "LDTR20") or "LDTR20").strip().upper()
    ADD_NOISE = get_bool(config, "RADAR_TCP", "ADD_NOISE", False)
    LOG_RX = get_bool(config, "RADAR_TCP", "LOG_RX", True)
    UPDATE_MIN_DELTA_MS = get_int(config, "RADAR_TCP", "UPDATE_MIN_DELTA_MS", 1000)
    SIMULATOR_ON = get_bool(config, "RADAR_SIMULATOR", "ON", False)
    SIMULATOR_INTERVAL_MS = get_int(config, "RADAR_SIMULATOR", "INTERVAL_MS", 2000) or 2000
    _sim_max = get_float(config, "RADAR_SIMULATOR", "MAX_SPEED", 120.0)
    _sim_min = get_float(config, "RADAR_SIMULATOR", "MIN_SPEED", 20.0)
    SIMULATOR_MAX_SPEED = float(_sim_max) if _sim_max is not None else 120.0
    SIMULATOR_MIN_SPEED = float(_sim_min) if _sim_min is not None else 20.0
except Exception:
    HOST = "0.0.0.0"
    PORT = 12345
    MODEL = "LDTR20"
    ADD_NOISE = False
    LOG_RX = True
    UPDATE_MIN_DELTA_MS = 1000
    SIMULATOR_ON = False
    SIMULATOR_INTERVAL_MS = 2000
    SIMULATOR_MAX_SPEED = 120.0
    SIMULATOR_MIN_SPEED = 20.0

# -----------------------------------------------------------------------------
# Parsers por modelo de radar
# -----------------------------------------------------------------------------
# Cada parser recibe una línea de texto y devuelve la velocidad en km/h o None
# si la línea no contiene una medición válida.

def _parse_ldtr20(line: str) -> Optional[float]:
    """
    Extrae la velocidad de una línea de texto enviada por el radar LDTR20.

    El dispositivo envía líneas en formato 'V+XXX.X' (ej. 'V+002.3', 'V+85.0').
    Solo se considera válida si empieza por 'V+'; el resto se interpreta como
    float en km/h. Cualquier otra línea o error de conversión devuelve None.

    Args:
        line: Cadena cruda recibida por TCP (puede contener \\r, \\n, espacios).

    Returns:
        Velocidad en km/h como float, o None si la línea no es una medición válida.
    """
    try:
        s = line.strip().replace("\r", "").replace("\n", "")
        if s.startswith("V+"):
            return float(s[2:])
        return None
    except Exception:
        return None


def _parse_stalker(line: str) -> Optional[float]:
    """
    Parser para radar STALKER (placeholder).

    Actualmente siempre devuelve None. Implementar cuando se conozca el protocolo
    del dispositivo (estructura de las líneas, prefijos, unidades). La firma debe
    mantenerse: recibe una línea y devuelve velocidad en km/h o None.

    Args:
        line: Línea de texto recibida por TCP.

    Returns:
        None hasta que se implemente el protocolo.
    """
    # TODO: implementar cuando se tenga especificación
    return None


def _parse_tsr20(line: str) -> Optional[float]:
    """
    Parser para radar TSR20 (placeholder).

    Actualmente siempre devuelve None. Implementar cuando se conozca el protocolo
    del dispositivo. La firma debe mantenerse: recibe una línea y devuelve
    velocidad en km/h o None.

    Args:
        line: Línea de texto recibida por TCP.

    Returns:
        None hasta que se implemente el protocolo.
    """
    # TODO: implementar cuando se tenga especificación
    return None


# Registro: modelo -> función parser
_PARSERS: dict[str, Callable[[str], Optional[float]]] = {
    "LDTR20": _parse_ldtr20,
    "STALKER": _parse_stalker,
    "TSR20": _parse_tsr20,
}


def _get_parser(model: str) -> Callable[[str], Optional[float]]:
    """
    Obtiene la función de parseo asociada al modelo de radar.

    Busca en el registro _PARSERS. Si el modelo no existe (ej. typo en config),
    se usa _parse_ldtr20 como fallback para no romper el servidor.

    Args:
        model: Nombre del modelo en mayúsculas (LDTR20, STALKER, TSR20).

    Returns:
        Función que acepta str y devuelve Optional[float] (velocidad en km/h).
    """
    p = _PARSERS.get(model)
    if p is not None:
        return p
    return _parse_ldtr20


_extract_speed = _get_parser(MODEL)
print(f"[radar_tcp] Modelo: {MODEL} (parser: {_extract_speed.__name__})", flush=True)

# -----------------------------------------------------------------------------
# Estado global (thread-safe)
# -----------------------------------------------------------------------------
_last_speed: Optional[float] = None
_last_speed_ts_ms: Optional[int] = None
_lock = threading.RLock()


def _now_ms() -> int:
    """
    Timestamp actual en milisegundos desde epoch.

    Se usa para marcar cuándo se recibió cada velocidad y para el rate-limit
    (UPDATE_MIN_DELTA_MS). Consistente con el resto del sistema (display_manager,
    lpr_decoder usan ts_ms).
    """
    return int(time.time() * 1000)


def _ts_str() -> str:
    """
    Cadena de hora actual en formato HH:MM:SS.mmm para mensajes de log.

    Ejemplo: "14:32:01.423". Útil para correlacionar eventos en consola.
    """
    return time.strftime("%H:%M:%S.") + f"{int((time.time()*1000)%1000):03d}"


def _maybe_update(speed: float, now_ms: int) -> bool:
    """
    Actualiza el estado global de velocidad solo si se cumple el rate-limit.

    Evita saturar el display con actualizaciones demasiado seguidas. Solo escribe
    _last_speed y _last_speed_ts_ms si:
    - Nunca se había actualizado, o
    - Han pasado al menos UPDATE_MIN_DELTA_MS ms desde la última actualización.
    Si no se actualiza, la nueva medición se descarta (se ignora).

    Args:
        speed: Velocidad en km/h a guardar.
        now_ms: Timestamp en ms de la medición (normalmente _now_ms()).

    Returns:
        True si se actualizó el estado; False si se ignoró por rate-limit.
    """
    with _lock:
        global _last_speed, _last_speed_ts_ms
        if _last_speed_ts_ms is None or (now_ms - _last_speed_ts_ms) >= UPDATE_MIN_DELTA_MS:
            _last_speed = speed
            _last_speed_ts_ms = now_ms
            return True
        return False


def _force_update(speed: float, now_ms: int) -> None:
    """
    Actualiza siempre el estado global de velocidad (sin rate-limit).

    Usado por el simulador para inyectar velocidades periódicas que se superponen
    a las del radar físico. Ambas fuentes pueden actualizar _last_speed.
    """
    with _lock:
        global _last_speed, _last_speed_ts_ms
        _last_speed = speed
        _last_speed_ts_ms = now_ms


def _simulator_loop() -> None:
    """
    Bucle del simulador: cada SIMULATOR_INTERVAL_MS ms envía una velocidad en
    secuencia desde MIN_SPEED hasta MAX_SPEED (inclusive), luego reinicia a MIN_SPEED.
    Si el modo display es "texto", el simulador no envía (queda desactivado).
    """
    interval_s = max(0.1, SIMULATOR_INTERVAL_MS / 1000.0)
    min_s = min(SIMULATOR_MIN_SPEED, SIMULATOR_MAX_SPEED)
    max_s = max(SIMULATOR_MIN_SPEED, SIMULATOR_MAX_SPEED)
    speed = min_s
    while True:
        try:
            time.sleep(interval_s)
            # El display-service filtra modo texto/picture por su cuenta;
            # el radar siempre publica al bus.
            speed_val = round(speed, 1)
            now_ms = _now_ms()
            _force_update(speed_val, now_ms)
            _publish_speed_safe(speed_val, now_ms)
            if LOG_RX:
                print(f"[{_ts_str()}] [radar_tcp] SIMULATOR spd={speed_val} ts={now_ms}", flush=True)
            speed += 1
            if speed > max_s:
                speed = min_s
        except Exception as e:
            print(f"[radar_tcp] Simulador error: {e}", flush=True)
            time.sleep(1.0)


# Bus SHM — se inicializa en start_radar_manager()
_bus = None


def _publish_speed_safe(speed: float, ts_ms: int) -> None:
    """Publica la velocidad al canal 'radar' del bus SHM."""
    global _bus
    if _bus is None:
        # Primer uso: adjuntar/crear el canal
        from shared.zmq_bus import EventBus, CHANNEL_RADAR
        _bus = EventBus(CHANNEL_RADAR, role="producer")
    try:
        print(f"[{_ts_str()}] [RADAR_TCP] VELOCIDAD RECIBIDA: {speed} km/h -> bus", flush=True)
        _bus.publish({"kind": "speed", "speed": float(speed), "ts_ms": int(ts_ms)})
        print(f"[{_ts_str()}] [RADAR_TCP] Velocidad {speed} km/h publicada en bus", flush=True)
    except Exception as e:
        print(f"[{_ts_str()}] [RADAR_TCP] Error publicando velocidad: {e}", flush=True)


def get_last_speed() -> Tuple[Optional[float], Optional[int]]:
    """
    Consulta la última velocidad aceptada y su timestamp.

    Es thread-safe. Útil para el LPR (asociar velocidad a una placa) y para
    comprobar si hay radar reciente antes de mostrar la placa en el LED.

    Returns:
        (speed, ts_ms): velocidad en km/h y timestamp ms. (None, None) si aún
        no se ha recibido ninguna medición válida.
    """
    with _lock:
        return _last_speed, _last_speed_ts_ms


def get_system_speed() -> Optional[float]:
    """
    Devuelve solo la última velocidad en km/h.

    Equivalente a get_last_speed()[0]. Se mantiene por compatibilidad con
    código que ya usaba esta función.
    """
    with _lock:
        return _last_speed


def get_last_speed_ts_ms() -> Optional[int]:
    """
    Devuelve el timestamp en ms de la última actualización de velocidad.

    El display_manager lo usa para saber si la velocidad es "reciente" (p. ej.
    ≤ 10 s) antes de mostrar una placa; si no hay radar reciente, la placa
    no se muestra.
    """
    with _lock:
        return _last_speed_ts_ms


def extract_speed(data_str: str) -> Optional[float]:
    """
    Parsea una línea de texto y extrae la velocidad según el modelo de radar.

    Usa el parser correspondiente a MODEL (config.ini). Útil para pruebas
    o para procesar datos fuera del servidor TCP. No modifica estado global.

    Args:
        data_str: Línea cruda (ej. 'V+085.3' para LDTR20).

    Returns:
        Velocidad en km/h o None si la línea no es una medición válida.
    """
    return _extract_speed(data_str)


def handle_tcp_connection(client_socket: socket.socket) -> None:
    """
    Atiende a un único cliente TCP conectado al radar.

    Bucle infinito hasta que el cliente cierra la conexión:
    1. Recibe hasta 1024 bytes y decodifica como UTF-8.
    2. Partiendo por \\n, trata cada línea con el parser del modelo.
    3. Si hay velocidad válida: opcionalmente añade ruido (ADD_NOISE), aplica
       rate-limit (_maybe_update) y, si se actualizó, publica al display_manager
       y opcionalmente loguea (LOG_RX).
    4. Ante excepciones, loguea y espera 50 ms antes de seguir.

    Se llama desde start_radar_tcp_server por cada accept(). No devuelve hasta
    que el socket se cierra.
    """
    # Configurar timeout para evitar bloqueos indefinidos
    try:
        client_socket.settimeout(30.0)  # 30 segundos de timeout
    except Exception:
        pass
    
    parser = _get_parser(MODEL)
    while True:
        try:
            data = client_socket.recv(1024)
            if not data:
                return
            text = data.decode("utf-8", errors="ignore")
            for raw_line in text.replace("\r", "\n").split("\n"):
                line = raw_line.strip()
                if not line:
                    continue
                spd = parser(line)
                if spd is not None and ADD_NOISE:
                    spd = spd + random.randint(-1, 1)  # Ruido ±1 km/h (entero)
                now_ms = _now_ms()
                updated = (spd is not None) and _maybe_update(spd, now_ms)
                if updated:
                    _publish_speed_safe(spd, now_ms)
                if LOG_RX and updated:
                    print(f"[{_ts_str()}] [radar_tcp] UPDATE spd={spd} ts={now_ms}", flush=True)
        except socket.timeout:
            # Timeout esperado - el cliente no envió datos en el tiempo esperado
            print(f"[radar_tcp] Timeout en conexión TCP (cliente inactivo)", flush=True)
            return  # Cerrar conexión si hay timeout
        except (ConnectionError, OSError) as e:
            # Errores de conexión - cliente desconectado
            print(f"[radar_tcp] Cliente desconectado: {e}", flush=True)
            return
        except Exception as e:
            print(f"[radar_tcp] Error en conexión TCP: {e}", flush=True)
            time.sleep(0.05)


def start_radar_tcp_server(host: str = None, port: int = None) -> None:
    """
    Arranca el servidor TCP que escucha conexiones del radar (bloqueante).

    Crea un socket, hace bind en (host, port), listen(5) y un bucle accept.
    Por cada cliente: llama handle_tcp_connection, cierra el socket del cliente
    y vuelve a accept. Solo sale con KeyboardInterrupt o error crítico; en
    ese caso cierra el socket del servidor.

    Atiende un solo cliente a la vez; si el radar se desconecta, el siguiente
    connect() será el mismo u otro dispositivo. host/port usan HOST/PORT de
    config si no se pasan.
    """
    host = host or HOST
    port = port or PORT
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Configurar timeout para accept() - evita bloqueos indefinidos
    server_socket.settimeout(5.0)  # Timeout de 5 segundos para permitir verificación periódica
    server_socket.bind((host, port))
    server_socket.listen(5)
    print(f"[radar_tcp] Servidor TCP ({MODEL}) en {host}:{port}...", flush=True)
    try:
        while True:
            try:
                client_socket, client_addr = server_socket.accept()
                print(f"[radar_tcp] Conexión de {client_addr}", flush=True)
                handle_tcp_connection(client_socket)
                try:
                    client_socket.close()
                except Exception:
                    pass
                print(f"[radar_tcp] Desconectado {client_addr}", flush=True)
            except socket.timeout:
                # Timeout esperado en accept() - continuar el bucle
                continue
            except Exception as e:
                print(f"[radar_tcp] Error aceptando: {e}", flush=True)
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("[radar_tcp] Servidor detenido.", flush=True)
    finally:
        try:
            server_socket.close()
        except Exception:
            pass


def start_radar_manager(host: str = None, port: int = None) -> threading.Thread:
    """
    Arranca el servidor TCP del radar en un hilo independiente.

    Siempre lanza un hilo daemon que ejecuta start_radar_tcp_server, retorna
    de inmediato y devuelve el Thread. El servidor nunca bloquea el hilo actual.
    Si SIMULATOR_ON está habilitado en config, además arranca un hilo simulador
    que envía velocidades periódicas (se superpone al radar físico).

    host/port por defecto desde config.ini [RADAR_TCP].
    """
    t = threading.Thread(
        target=start_radar_tcp_server,
        kwargs={"host": host, "port": port},
        daemon=True,
        name="radar-tcp-server",
    )
    t.start()
    print(f"[radar_tcp] Servidor lanzado ({MODEL}) en {host or HOST}:{port or PORT}", flush=True)
    if SIMULATOR_ON:
        sim_thread = threading.Thread(
            target=_simulator_loop,
            daemon=True,
            name="radar-simulator",
        )
        sim_thread.start()
        print(f"[radar_tcp] Simulador activo: intervalo={SIMULATOR_INTERVAL_MS} ms, "
              f"velocidad [{SIMULATOR_MIN_SPEED}, {SIMULATOR_MAX_SPEED}] km/h", flush=True)
    return t
