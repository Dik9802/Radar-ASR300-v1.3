# shared/plate_pipeline.py
"""
Helpers comunes para el procesamiento de imágenes de placas.

Usado por lpr-service y npu-service para:
  - decodificar base64 → bytes
  - auto-crop amarillo del recorte de placa (solo NPU, opcional)
  - guardar JPEG en plate_pic/ o scene_pic/
  - construir el dict del evento SHM (`make_plate_event`)

El rate-limit (min_interval + debounce) ya NO vive aquí. Lo aplica el
display-service (consumer) para tener un único filtro cross-fuente.
"""
from __future__ import annotations

import base64
import io
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

try:
    from PIL import Image
except ImportError:
    Image = None


PLATE_PIC_FOLDER = "plate_pic"
SCENE_PIC_FOLDER = "scene_pic"


def _sanitize_plate(plate: str) -> str:
    clean = "".join(c for c in plate if c.isalnum()).upper()
    return clean[:20] or "UNKNOWN"


def _generate_filename(plate: str, file_type: str, image_format: str) -> str:
    """file_type: 'p' (placa) o 's' (escena)."""
    now = datetime.now()
    fecha = now.strftime("%Y%m%d")
    hora = now.strftime("%H%M%S")
    ms = f"{now.microsecond // 1000:03d}"
    return f"{_sanitize_plate(plate)}_{fecha}_{hora}-{ms}-{file_type}.{image_format}"


def _auto_crop_yellow_plate(image_bytes: bytes) -> Optional[bytes]:
    """Recorta la región amarilla (placa colombiana). None si PIL falta o
    no encuentra suficiente amarillo."""
    if Image is None:
        return None
    try:
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = im.size
        if w < 20 or h < 20:
            return None
        hsv = im.convert("HSV")
        H, S, V = hsv.split()
        mask = Image.eval(H, lambda v: 255 if 25 <= v <= 70 else 0)
        mask_s = Image.eval(S, lambda v: 255 if v >= 70 else 0)
        mask_v = Image.eval(V, lambda v: 255 if v >= 100 else 0)
        from PIL import ImageChops
        mask = ImageChops.multiply(mask, mask_s)
        mask = ImageChops.multiply(mask, mask_v)
        bbox = mask.getbbox()
        if not bbox:
            return None
        x0, y0, x1, y1 = bbox
        area_ratio = ((x1 - x0) * (y1 - y0)) / float(w * h)
        if area_ratio < 0.05:
            return None
        pad_x = max(1, (x1 - x0) // 40)
        pad_y = max(1, (y1 - y0) // 20)
        x0 = max(0, x0 - pad_x)
        y0 = max(0, y0 - pad_y)
        x1 = min(w, x1 + pad_x)
        y1 = min(h, y1 + pad_y)
        cropped = im.crop((x0, y0, x1, y1))
        out = io.BytesIO()
        cropped.save(out, format="JPEG", quality=92)
        print(f"[PLATE_PIPELINE] Auto-crop amarillo: {w}x{h} -> {x1 - x0}x{y1 - y0}")
        return out.getvalue()
    except Exception as e:
        print(f"[PLATE_PIPELINE] auto_crop falló: {e}")
        return None


def save_plate_image_b64(
    b64: Optional[str],
    plate: str,
    folder: str,
    file_type: str,
    image_format: str = "jpg",
    *,
    auto_crop: bool = False,
) -> Optional[str]:
    """Decodifica base64 y guarda la imagen. Devuelve ruta absoluta o None.

    Args:
        b64: Base64 puro o con prefijo data:image/...;base64,
        plate: Placa detectada (para nombre de archivo)
        folder: 'plate_pic' o 'scene_pic'
        file_type: 'p' o 's' (sufijo)
        image_format: 'jpg', 'jpeg' o 'png'
        auto_crop: si True, aplica auto-crop amarillo (solo tiene sentido
                   en recortes de placa colombiana).
    """
    if not b64 or not isinstance(b64, str) or len(b64) < 100:
        return None

    if b64.startswith("data:"):
        comma = b64.find(",")
        if comma != -1:
            b64 = b64[comma + 1:]

    try:
        image_data = base64.b64decode(b64, validate=True)
    except Exception as e:
        print(f"[PLATE_PIPELINE] base64 inválido: {e}")
        return None

    if len(image_data) < 100:
        print(f"[PLATE_PIPELINE] imagen demasiado pequeña: {len(image_data)} bytes")
        return None

    if auto_crop:
        cropped = _auto_crop_yellow_plate(image_data)
        if cropped:
            image_data = cropped

    try:
        folder_path = os.path.join(os.getcwd(), folder)
        os.makedirs(folder_path, exist_ok=True)
        filename = _generate_filename(plate, file_type, image_format)
        file_path = os.path.join(folder_path, filename)
        with open(file_path, "wb") as f:
            f.write(image_data)
        print(f"[PLATE_PIPELINE] Guardada: {file_path} ({len(image_data)} bytes)")
        return file_path
    except OSError as e:
        print(f"[PLATE_PIPELINE] Error escribiendo imagen: {e}")
        return None


def make_plate_event(
    plate: str,
    source: str,
    ts_ms: Optional[int] = None,
    plate_pic_path: Optional[str] = None,
    scene_pic_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Construye el dict que viaja por el bus SHM (canal 'lpr' o 'npu')."""
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
    evt: Dict[str, Any] = {
        "kind": "plate",
        "plate": plate.strip(),
        "ts_ms": int(ts_ms),
        "source": source,
    }
    if plate_pic_path:
        evt["plate_pic_path"] = plate_pic_path
    if scene_pic_path:
        evt["scene_pic_path"] = scene_pic_path
    return evt
