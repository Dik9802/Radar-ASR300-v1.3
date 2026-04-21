from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Union

from shared.plate_pipeline import (
    PLATE_PIC_FOLDER,
    SCENE_PIC_FOLDER,
    make_plate_event,
    save_plate_image_b64,
)
from shared.zmq_bus import EventBus, CHANNEL_LPR

logger = logging.getLogger("lpr_decoder")

_bus: Optional[EventBus] = None


def _get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus(CHANNEL_LPR, role="producer")
    return _bus


@dataclass
class DecoderStats:
    received: int = 0
    published: int = 0
    errors: int = 0
    last_plate: Optional[str] = None
    last_timestamp_ms: Optional[int] = None
    seen_plates: Dict[str, int] = field(default_factory=dict)


class LPRDecoder:
    """Decoder autonomo para payloads Hikvision LPR."""

    def __init__(self) -> None:
        self.stats = DecoderStats()

    def _ensure_dict(self, event: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(event, dict):
            return event
        if isinstance(event, str):
            try:
                parsed = json.loads(event)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def _extract_plate_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        alarm = payload.get("AlarmInfoPlate")
        if not isinstance(alarm, dict):
            return {}
        result = alarm.get("result")
        if not isinstance(result, dict):
            return {}
        plate_result = result.get("PlateResult")
        return plate_result if isinstance(plate_result, dict) else {}

    def _extract_plate(self, payload: Dict[str, Any]) -> str:
        plate_result = self._extract_plate_result(payload)
        plate = plate_result.get("license")
        return plate.strip() if isinstance(plate, str) else ""

    def _extract_images(self, payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        plate_result = self._extract_plate_result(payload)
        plate_img = plate_result.get("imageFragmentFile")
        full_img = plate_result.get("imageFile")
        return (
            plate_img if isinstance(plate_img, str) else None,
            full_img if isinstance(full_img, str) else None,
        )

    def handle_event(self, event: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        payload = self._ensure_dict(event)
        self.stats.received += 1

        if not payload:
            self.stats.errors += 1
            return {"status": "ERROR", "ok": False, "message": "payload JSON invalido"}

        plate = self._extract_plate(payload)
        if not plate:
            self.stats.errors += 1
            return {"status": "ERROR", "ok": False, "message": "placa no encontrada"}

        now_ms = int(time.time() * 1000)
        plate_img_b64, full_img_b64 = self._extract_images(payload)

        plate_pic_path = save_plate_image_b64(
            plate_img_b64,
            plate,
            PLATE_PIC_FOLDER,
            "p",
            "jpg",
            auto_crop=False,
        )
        scene_pic_path = save_plate_image_b64(
            full_img_b64,
            plate,
            SCENE_PIC_FOLDER,
            "s",
            "jpg",
            auto_crop=False,
        )

        event_payload = make_plate_event(
            plate=plate,
            source="lpr",
            ts_ms=now_ms,
            plate_pic_path=plate_pic_path,
            scene_pic_path=scene_pic_path,
        )

        try:
            _get_bus().publish(event_payload)
        except Exception as exc:
            self.stats.errors += 1
            logger.exception("Error publicando placa al bus")
            return {
                "status": "ERROR",
                "ok": False,
                "message": f"bus publish failed: {exc}",
                "plate": plate,
            }

        self.stats.published += 1
        self.stats.last_plate = plate
        self.stats.last_timestamp_ms = now_ms
        self.stats.seen_plates[plate] = self.stats.seen_plates.get(plate, 0) + 1

        return {
            "status": "OK",
            "ok": True,
            "plate": plate,
            "published": True,
            "timestamp_ms": now_ms,
            "images_found": {
                "plate_image": bool(plate_img_b64),
                "full_image": bool(full_img_b64),
            },
            "images_saved": {
                "plate_saved": bool(plate_pic_path),
                "frame_saved": bool(scene_pic_path),
            },
        }


_DECODER = LPRDecoder()


def handle_lpr_event(event: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    try:
        return _DECODER.handle_event(event)
    except Exception as exc:
        logger.exception("Error critico en handle_lpr_event")
        return {
            "status": "ERROR",
            "ok": False,
            "message": f"Error critico: {exc}",
            "timestamp_ms": int(time.time() * 1000),
        }


def procesar_payload_alarm(event: Union[str, Dict[str, Any]], **kwargs) -> Dict[str, Any]:
    return handle_lpr_event(event)


def get_decoder_stats() -> Dict[str, Any]:
    return {
        "received": _DECODER.stats.received,
        "published": _DECODER.stats.published,
        "errors": _DECODER.stats.errors,
        "last_plate": _DECODER.stats.last_plate,
        "last_timestamp_ms": _DECODER.stats.last_timestamp_ms,
        "seen_plates": dict(_DECODER.stats.seen_plates),
    }
