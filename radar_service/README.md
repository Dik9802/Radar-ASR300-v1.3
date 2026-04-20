# radar-service

Servicio TCP que recibe velocidades del radar LDTR20 y las publica al bus SHM.

## Entrada
- TCP `0.0.0.0:2222` (según `config.ini [RADAR_TCP]`)
- Trama: `V+XXX.X\n`

## Salida
- Canal SHM `radar` (producer)
- Formato: `{"kind":"speed", "speed": float, "ts_ms": int}`

## Arranque
```
python -m radar_service.main
```

## Archivos a migrar aquí (desde Python/)
- `radar_tcp.py` → `tcp_listener.py` (quitar `publish_velocidad`, reemplazar por `bus.publish`)
- crear `main.py` que arranque el listener y el bus

## Dependencias
- `shared.shm_bus`
- `shared.config_loader`
