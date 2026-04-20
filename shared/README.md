# shared

Código común entre los 4 servicios:

- [shm_bus.py](shm_bus.py) — Bus de eventos con memoria compartida (SPSC, ~14 µs round-trip)
- [test_shm_bus.py](test_shm_bus.py) — Prueba y benchmark

## Canales del bus

| Canal | Productor | Consumer | Payload |
|-------|-----------|----------|---------|
| `radar` | radar-service | display-service | `{"kind":"speed", "speed": float, "ts_ms": int}` |
| `lpr` | lpr-service | display-service | `{"kind":"plate", "plate": str, "plate_pic_path": str?, "scene_pic_path": str?, "ts_ms": int, "source":"lpr"}` |
| `npu` | npu-service | display-service | igual que lpr, `source="npu"` |

## Uso del bus

```python
from shared.shm_bus import EventBus, CHANNEL_RADAR

# Productor (radar-service, lpr-service, npu-service)
bus = EventBus(CHANNEL_RADAR, role="producer")
bus.publish({"kind": "speed", "speed": 45.0, "ts_ms": ...})

# Consumer (display-service)
bus = EventBus(CHANNEL_RADAR, role="consumer")
evt = bus.read_blocking()  # bloquea con polling de 1 ms
```

## Otros módulos que habrá que mover aquí

Cuando se porten los servicios, mover a `shared/` lo que sea común:
- `config_loader.py` — usado por los 4 servicios
- `plate_pipeline.py` — guardar imágenes, rate-limit (lo usan lpr y npu)
- `database_manager.py` — si se queda una BD común
- `led_controller_constants.py` — constantes del protocolo LED (si algo más que display lo necesita)

## Test

```
python shared/test_shm_bus.py benchmark   # un proceso, 10k round-trips
python shared/test_shm_bus.py producer    # terminal 1
python shared/test_shm_bus.py consumer    # terminal 2
```
