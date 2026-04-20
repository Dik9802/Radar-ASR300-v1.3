# npu_service/decoder.py
"""
Parser del JSON que envía la cámara NPU. Guarda imágenes y publica la placa
al canal SHM 'npu' para que display-service la muestre.

Formato esperado del JSON:
{
  "plate": "ABC123",
  "timestamp_ms": 1734567890123,       # opcional (ignorado, usamos now())
  "plate_image_b64": "...",            # base64 puro o con prefijo data:
  "vehicle_image_b64": "...",
  "image_format": "jpg"                # opcional, default jpg
}
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from shared.plate_pipeline import (
    PLATE_PIC_FOLDER,
    SCENE_PIC_FOLDER,
    save_plate_image_b64,
    make_plate_event,
)
from shared.shm_bus import EventBus, CHANNEL_NPU

_bus: Optional[EventBus] = None


def _get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus(CHANNEL_NPU, role="producer")
    return _bus


def procesar_payload_npu(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Procesa el JSON de la cámara NPU: guarda imágenes y publica al bus."""
    if not isinstance(payload, dict):
        return {"status": "ERROR", "message": "payload no es un objeto JSON"}

    plate = (payload.get("plate") or "").strip()
    if not plate:
        return {"status": "ERROR", "message": "campo 'plate' ausente o vacío"}

    image_format = (payload.get("image_format") or "jpg").lower().strip()
    if image_format not in ("jpg", "jpeg", "png"):
        image_format = "jpg"

    # NPU ya entrega el recorte al tamaño final (96×38 para carro, 90×60 para moto).
    # No reprocesamos con auto-crop amarillo: antes recortaba aún más y dejaba
    # tiras estrechas que el display escalaba con artefactos.
    plate_pic_path = save_plate_image_b64(
        payload.get("plate_image_b64"),
        plate, PLATE_PIC_FOLDER, "p", image_format,
        auto_crop=False,
    )
    # Escena: sin auto-crop
    scene_pic_path = save_plate_image_b64(
        payload.get("vehicle_image_b64"),
        plate, SCENE_PIC_FOLDER, "s", image_format,
        auto_crop=False,
    )

    # Publica al bus; display-service lo muestra (o descarta si no hay
    # velocidad reciente, según SHOW_PLATE_SPEED).
    event = make_plate_event(
        plate=plate,
        source="npu",
        ts_ms=None,  # usamos now() del servidor
        plate_pic_path=plate_pic_path,
        scene_pic_path=scene_pic_path,
    )
    try:
        _get_bus().publish(event)
    except Exception as e:
        print(f"[NPU_DECODER] Error publicando al bus: {e}")
        return {"status": "ERROR", "message": f"bus publish failed: {e}"}

    return {
        "status": "OK",
        "plate": plate,
        "plate_image_saved": bool(plate_pic_path),
        "vehicle_image_saved": bool(scene_pic_path),
    }
