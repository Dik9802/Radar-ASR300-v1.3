# lpr-service

Servicio HTTP que recibe alarmas de la cámara LPR Hikvision y publica placas al bus SHM.

## Entrada
- HTTP `0.0.0.0:8899/` (o el puerto que use la cámara Hikvision)
- JSON Hikvision (estructura `AlarmInfoPlate.result.PlateResult...`)

## Salida
- Canal SHM `lpr` (producer)
- Formato: `{"kind":"plate", "plate": str, "plate_pic_path": str?, "scene_pic_path": str?, "ts_ms": int, "source":"lpr"}`
- Imágenes JPEG guardadas en `plate_pic/` y `scene_pic/` (compartidas entre servicios)

## Arranque
```
python -m lpr_service.main
```

## Archivos a migrar aquí (desde Python/)
- `lpr_cam_web_server.py` → `web_server.py` (solo rutas LPR, sin `/npu`)
- `lpr_decoder.py` → `decoder.py` (reemplazar `publish_placa` → `bus.publish`)
- `lpr_queue_manager.py` → `queue_manager.py`
- crear `main.py`

## Dependencias
- `shared.shm_bus`, `shared.config_loader`, `shared.plate_pipeline` (para guardar imágenes)
- Opcional: `shared.sftp_client` si este servicio también sube a SFTP
