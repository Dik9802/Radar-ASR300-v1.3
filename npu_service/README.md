# npu-service

Servicio HTTP que recibe placas de la cámara NPU y publica al bus SHM.

## Entrada
- HTTP `0.0.0.0:8898/npu` (puerto propio, separado del LPR)
- JSON:
```json
{
  "plate": "ABC123",
  "plate_image_b64": "...",
  "vehicle_image_b64": "...",
  "image_format": "jpg"
}
```

## Salida
- Canal SHM `npu` (producer)
- Formato: `{"kind":"plate", "plate": str, "plate_pic_path": str?, "scene_pic_path": str?, "ts_ms": int, "source":"npu"}`
- Imágenes decodificadas y guardadas en `plate_pic/` y `scene_pic/` (con auto-crop amarillo para la placa).

## Arranque
```
python -m npu_service.main
```

## Archivos a migrar aquí (desde Python/)
- endpoint `/npu` de `lpr_cam_web_server.py` → `web_server.py`
- `npu_decoder.py` → `decoder.py` (reemplazar `publish_plate_to_display` → `bus.publish`)
- `npu_queue_manager.py` → `queue_manager.py`
- crear `main.py`

## Dependencias
- `shared.shm_bus`, `shared.config_loader`, `shared.plate_pipeline`
