# Radar-ASR300-v1.3

Sistema de fiscalización de tráfico (radar + LPR/NPU + display LED) basado en microservicios Python, desplegado sobre Orange Pi Zero 3. Esta versión (v1.3) migra el bus de eventos de memoria compartida (SHM) a **PyZMQ PUB/SUB** y añade lógica *source-aware* para placas provenientes de cámara NPU.

## Qué se hizo en esta versión

### 1. Migración del bus interno: SHM → ZMQ PUB/SUB
El bus de eventos entre servicios (`shared/shm_bus.py`) era un ring buffer en memoria compartida POSIX. Se reemplazó por un bus ZMQ PUB/SUB (`shared/zmq_bus.py`) manteniendo la misma API pública (`EventBus(channel, role)`, `publish()`, `read()`, `read_blocking()`, `close()`, `unlink()`), por lo que la migración fue drop-in sobre los 4 servicios.

**Motivación:** permitir multi-productor nativo (dos `radar_service` corriendo por accidente no corrompen estado), cola interna con HWM configurable en vez de sobrescritura de ring buffer, desacoplamiento total entre productor y consumers, y transporte flexible (tcp local hoy, tcp a otra IP mañana).

**Trade-offs aceptados:** latencia sube de ~15 µs a ~200–500 µs (invisible al usuario final), y el patrón *slow-joiner* de ZMQ implica que un consumer que conecta tarde pierde los mensajes anteriores.

### 2. Lógica *source-aware* en display_service
El gate `SHOW_PLATE_SPEED` (que descarta placas sin velocidad reciente del radar) solo aplica a placas con `source="lpr"`. Las placas con `source="npu"` se muestran aunque el radar no haya reportado velocidad, porque la NPU opera como cámara autónoma sin dependencia del radar.

Implementado propagando el campo `source` desde el hilo consumer hacia el manager y añadiendo el check en `display_service/manager.py`.

### 3. Ajustes de tiempo y calidad visual (heredado de v1.2)
- `show_plate_time = 1` s, `delay_before_close_ms = 500` → total ~1.5 s por placa.
- `FLAGS = 0x01` (ACK por paquete) para evitar distorsión por pérdida en envíos sin ACK.
- `auto_crop = False` en NPU decoder: la NPU ya entrega la placa al tamaño final (96×38 para carros, 90×60 para motos); el auto-crop amarillo previo dejaba tiras estrechas que el display escalaba con artefactos.
- Resize con `scale = min(1.0, scale_w, scale_h)` para prevenir upscaling (imágenes pequeñas ya no se inflan).

## Arquitectura

```
  ┌──────────────┐   TCP 2222    ┌───────────────┐   ZMQ 5555    ┌─────────────────┐
  │ Radar ASR300 │ ────────────▶ │ radar_service │ ────────────▶ │                 │
  └──────────────┘   (LDTR20)    └───────────────┘   canal radar │                 │
                                                                 │                 │
  ┌──────────────┐   HTTP 8899   ┌───────────────┐   ZMQ 5556    │ display_service │───▶ Pantalla LED
  │ Cámara LPR   │ ────────────▶ │ lpr_service   │ ────────────▶ │  (manager +     │    (TCP 5200)
  │ (Hikvision)  │   (JSON)      └───────────────┘   canal lpr   │   LED driver)   │
  └──────────────┘                                               │                 │
                                                                 │                 │
  ┌──────────────┐   HTTP 8898   ┌───────────────┐   ZMQ 5557    │                 │
  │ Cámara NPU   │ ────────────▶ │ npu_service   │ ────────────▶ │                 │
  └──────────────┘   (JSON b64)  └───────────────┘   canal npu   └─────────────────┘
```

### Servicios

| Servicio | Entrada | Salida | Rol |
|---|---|---|---|
| `radar_service` | TCP `:2222` (tramas LDTR20 `V+XXX.X`) | ZMQ PUB `tcp://127.0.0.1:5555` | Parsea velocidades del radar y las publica |
| `lpr_service` | HTTP `:8899` (JSON Hikvision) | ZMQ PUB `tcp://127.0.0.1:5556` | Recibe placas vía webhook, guarda imágenes, publica evento |
| `npu_service` | HTTP `:8898` (JSON b64) | ZMQ PUB `tcp://127.0.0.1:5557` | Recibe placas de cámara NPU, guarda imágenes, publica evento |
| `display_service` | ZMQ SUB ×3 canales + HTTP `:8081` (API) | TCP `192.168.0.222:5200` (LED) | Renderiza velocidad/placa y la envía al controlador LED |

### Canales ZMQ

Configurados en `config.ini` sección `[ZMQ]`:

```ini
[ZMQ]
host = 127.0.0.1
radar_port = 5555
lpr_port   = 5556
npu_port   = 5557
rcv_hwm    = 1000
```

Cada productor hace `bind` en su puerto y cada consumer (display) hace `connect` y se suscribe a todos los topics (`SUBSCRIBE = b""`). `SNDHWM`/`RCVHWM = 1000` con descarte en el productor (`NOBLOCK`) para nunca bloquearlo.

## Estructura del repositorio

```
Radar-ASR300-v1.3/
├── config.ini                  # Configuración central (ZMQ, puertos, LED, etc.)
├── create_postgres_db.sql      # Script DDL de la base de datos
├── shared/
│   ├── zmq_bus.py              # Bus PUB/SUB (nuevo)
│   ├── shm_bus.py              # Bus SHM (legado, no se usa)
│   ├── plate_pipeline.py       # Helpers de persistencia y evento de placa
│   └── config_loader.py        # Lectura de config.ini con overrides por ENV
├── radar_service/              # Listener TCP del radar
├── lpr_service/                # Webhook Hikvision + queue_manager
├── npu_service/                # Webhook NPU + queue_manager
├── display_service/            # Manager + driver LED + web server de monitor
├── web_panel/                  # Panel Django (Postgres) para historial
├── plate_pic/  scene_pic/      # Imágenes persistidas (ignoradas por git)
└── tests/
```

## Ejecución

```bash
# (Windows) evitar UnicodeEncodeError en prints con emoji:
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

python -m radar_service.main    &
python -m lpr_service.main      &
python -m npu_service.main      &
python -m display_service.main  &
```

El orden no es crítico gracias al `time.sleep(0.1)` post-bind en el productor, pero conviene arrancar los productores antes que el consumer para minimizar el *slow-joiner*.

## Parámetros relevantes

| Sección | Clave | Efecto |
|---|---|---|
| `[LED_CONTROLLER]` | `flags = 0x01` | Pide ACK por paquete al LED (evita distorsión por paquete perdido) |
| `[LED_CONTROLLER]` | `delay_before_close_ms = 500` | Espera ms antes de cerrar TCP tras enviar GIF |
| `[DISPLAY_MANAGER]` | `show_plate_time = 1` | Segundos que la placa permanece visible (tras TCP) |
| `[DISPLAY_MANAGER]` | `show_plate_speed = true` | Exige velocidad ≤10 s para mostrar placa LPR (NPU exento) |
| `[DISPLAY_MANAGER]` | `speed_limit_kmph = 30` | Umbral para color de velocidad (verde/rojo) |
| `[ZMQ]` | `rcv_hwm = 1000` | Tamaño de cola interna antes de descartar |

## Historial de commits relevantes

- `feat: migracion SHM -> ZMQ PUB/SUB y logica source-aware para NPU` — v1.3
- `Initial commit: Radar ASR300P microservices` — snapshot inicial limpio desde v1.2
