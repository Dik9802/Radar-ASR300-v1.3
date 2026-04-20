"""
send_npu_test.py — Simula un envío desde la cámara NPU al endpoint POST /npu.

Genera una imagen de placa (recorte con el texto) y una imagen de vehículo
(escena de mayor tamaño), las codifica en base64 y las envía como JSON.

Uso:
    python send_npu_test.py
    python send_npu_test.py ABC123
    python send_npu_test.py ABC123 --host 192.168.0.50 --port 8080
    python send_npu_test.py --random
"""
import argparse
import base64
import io
import random
import string
import sys
import time

import requests
from PIL import Image, ImageDraw, ImageFont


def _random_plate() -> str:
    letters = "".join(random.choices(string.ascii_uppercase, k=3))
    digits = "".join(random.choices(string.digits, k=3))
    return f"{letters}{digits}"


def _load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _make_plate_image(plate: str) -> bytes:
    """Imagen recortada tipo placa (fondo amarillo, texto negro)."""
    w, h = 400, 140
    img = Image.new("RGB", (w, h), (250, 210, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(6, 6), (w - 7, h - 7)], outline=(0, 0, 0), width=5)
    font = _load_font(90)
    bbox = draw.textbbox((0, 0), plate, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2 - bbox[0], (h - th) / 2 - bbox[1]),
              plate, fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _make_vehicle_image(plate: str) -> bytes:
    """Imagen de escena con un 'vehículo' simulado y la placa incrustada."""
    w, h = 1280, 720
    img = Image.new("RGB", (w, h), (50, 80, 120))
    draw = ImageDraw.Draw(img)
    # "suelo"
    draw.rectangle([(0, h - 120), (w, h)], fill=(80, 80, 80))
    # "vehículo"
    car_x0, car_y0, car_x1, car_y1 = 360, 220, 920, 560
    draw.rounded_rectangle([(car_x0, car_y0), (car_x1, car_y1)],
                           radius=40, fill=(200, 30, 30))
    draw.rectangle([(car_x0 + 60, car_y0 + 50),
                    (car_x1 - 60, car_y0 + 180)], fill=(120, 180, 220))
    # ruedas
    draw.ellipse([(car_x0 + 40, car_y1 - 40),
                  (car_x0 + 140, car_y1 + 60)], fill=(20, 20, 20))
    draw.ellipse([(car_x1 - 140, car_y1 - 40),
                  (car_x1 - 40, car_y1 + 60)], fill=(20, 20, 20))
    # placa incrustada
    plate_w, plate_h = 260, 80
    px0 = (car_x0 + car_x1) // 2 - plate_w // 2
    py0 = car_y1 - plate_h - 20
    draw.rectangle([(px0, py0), (px0 + plate_w, py0 + plate_h)],
                   fill=(250, 210, 30), outline=(0, 0, 0), width=3)
    font = _load_font(48)
    bbox = draw.textbbox((0, 0), plate, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((px0 + (plate_w - tw) / 2 - bbox[0],
               py0 + (plate_h - th) / 2 - bbox[1]),
              plate, fill=(0, 0, 0), font=font)
    # marca de tiempo
    stamp_font = _load_font(22)
    draw.text((16, 16), time.strftime("%Y-%m-%d %H:%M:%S"),
              fill=(255, 255, 255), font=stamp_font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simula un envío de la cámara NPU al endpoint /npu")
    parser.add_argument("plate", nargs="?", default="ABC123",
                        help="Texto de la placa (default: ABC123)")
    parser.add_argument("--random", action="store_true",
                        help="Generar una placa aleatoria")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--path", default="/npu")
    parser.add_argument("--no-plate-image", action="store_true",
                        help="No enviar plate_image_b64")
    parser.add_argument("--no-vehicle-image", action="store_true",
                        help="No enviar vehicle_image_b64")
    parser.add_argument("--save", action="store_true",
                        help="Guardar las imágenes generadas en disco")
    args = parser.parse_args()

    plate = _random_plate() if args.random else args.plate.upper().strip()
    url = f"http://{args.host}:{args.port}{args.path}"

    print(f"[TEST] Generando imágenes para placa '{plate}'...")
    plate_jpg = None if args.no_plate_image else _make_plate_image(plate)
    vehicle_jpg = None if args.no_vehicle_image else _make_vehicle_image(plate)

    if args.save:
        if plate_jpg:
            with open(f"sample_plate_{plate}.jpg", "wb") as f:
                f.write(plate_jpg)
            print(f"[TEST] Guardado sample_plate_{plate}.jpg")
        if vehicle_jpg:
            with open(f"sample_vehicle_{plate}.jpg", "wb") as f:
                f.write(vehicle_jpg)
            print(f"[TEST] Guardado sample_vehicle_{plate}.jpg")

    payload = {
        "plate": plate,
        "timestamp_ms": int(time.time() * 1000),
        "image_format": "jpg",
    }
    if plate_jpg:
        payload["plate_image_b64"] = base64.b64encode(plate_jpg).decode("ascii")
    if vehicle_jpg:
        payload["vehicle_image_b64"] = base64.b64encode(vehicle_jpg).decode("ascii")

    sizes = []
    if plate_jpg:
        sizes.append(f"plate={len(plate_jpg) // 1024} KB")
    if vehicle_jpg:
        sizes.append(f"vehicle={len(vehicle_jpg) // 1024} KB")
    print(f"[TEST] POST {url}  ({', '.join(sizes) or 'sin imágenes'})")

    try:
        resp = requests.post(url, json=payload, timeout=15)
        print(f"[TEST] HTTP {resp.status_code}")
        print(f"[TEST] Respuesta: {resp.text}")
        return 0 if resp.ok else 1
    except requests.RequestException as e:
        print(f"[TEST] ERROR de red: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
