# led_controller_constants.py - Constantes del controlador LED desde config.ini

# Configuración desde config.ini
try:
    from shared.config_loader import read_ini, get_str, get_int, get_float, get_bool
    config = read_ini(apply_env_overrides=True)
    
    # [LED_CONTROLLER]
    HOST = get_str(config, "LED_CONTROLLER", "HOST", "192.168.0.222")
    PORT = get_int(config, "LED_CONTROLLER", "PORT", 5200)
    ID_CODE = get_int(config, "LED_CONTROLLER", "ID_CODE", 0xFFFFFFFF)
    CARD_ID = get_int(config, "LED_CONTROLLER", "CARD_ID", 0x01)
    FLAGS = get_int(config, "LED_CONTROLLER", "FLAGS", 0x01)
    TIMEOUT_SECONDS = get_int(config, "LED_CONTROLLER", "TIMEOUT_SECONDS", 2)
    RECONNECT_INTERVAL = get_float(config, "LED_CONTROLLER", "RECONNECT_INTERVAL", 5.0)
    _delay_ms = get_int(config, "LED_CONTROLLER", "DELAY_BEFORE_CLOSE_MS", 500)
    DELAY_BEFORE_CLOSE_S = (_delay_ms / 1000.0) if _delay_ms and _delay_ms > 0 else 0.0
    # [LED_LOWLEVEL_DEFAULTS] 
    WINDOW_NO = get_int(config, "LED_LOWLEVEL_DEFAULTS", "WINDOW_NO", 0)
    MODE = get_int(config, "LED_LOWLEVEL_DEFAULTS", "MODE", 0)
    SPEED = get_int(config, "LED_LOWLEVEL_DEFAULTS", "SPEED", 0)
    CHUNK_SIZE = get_int(config, "LED_LOWLEVEL_DEFAULTS", "CHUNK_SIZE", 200)
    GIF_OFFSET_Y = get_int(config, "LED_LOWLEVEL_DEFAULTS", "GIF_OFFSET_Y", 0) or 0
    print(f"[LED] Configuración cargada desde config.ini: {HOST}:{PORT}")
    
except Exception as e:
    print(f"[LED] Error cargando config.ini, usando valores por defecto: {e}")
    # Fallback a valores hardcodeados
    HOST = "192.168.0.222"
    PORT = 5200
    ID_CODE = 0xFFFFFFFF   # 4 bytes, big-endian en el paquete Network
    CARD_ID = 0x01         # 1..254, o 0xFF (broadcast)
    FLAGS = 0x01           # bit0=1 => solicitar ACK al controlador
    
    # Timeout para las operaciones TCP (segundos, entero)
    TIMEOUT_SECONDS = 2
    
    # Intervalo de reintentos de conexión (segundos, float)
    RECONNECT_INTERVAL = 5.0
    
    # Espera antes de cerrar conexión (segundos)
    DELAY_BEFORE_CLOSE_S = 0.5
    
    # Parámetros fijos para envío de GIF (CC=0x03)
    WINDOW_NO = 0   # ventana 0..7
    MODE = 0        # 0=Draw
    SPEED = 0       # puede ser ignorado por el firmware
    CHUNK_SIZE = 200 # bytes del "Packet data" por paquete
    GIF_OFFSET_Y = 8  # Desplazamiento Y para evitar borde superior dañado