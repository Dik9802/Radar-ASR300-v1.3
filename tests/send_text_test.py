#!/usr/bin/env python3
"""
send_text_test.py — Envía texto de prueba al display LED.
Uso:
    python send_text_test.py
    python send_text_test.py "Mi texto de prueba"
"""
import sys
from display_service.led.led_controller_handler import (
    send_text_over_tcp,
    TextMode,
    TextColor,
    TextFontSize,
    TextAlign,
)


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "WMZ186"
    
    print(f"Enviando texto: '{text}'")
    acks = send_text_over_tcp(
        text=text,
        mode=TextMode.DRAW,
        color_code=TextColor.GREEN,
        font_size_code=TextFontSize.SIZE_48PX,
        align=TextAlign.CENTER,
        speed=5,
        stay_time_s=10,
        require_ack=False,
    )
    
    ok = sum(1 for a in acks if a.get("rr", 1) == 0)
    if acks and ok == len(acks):
        print(f"OK: {len(acks)} ACK(s) recibido(s)")
    elif acks:
        print(f"Parcial: {ok}/{len(acks)} ACKs OK")
    else:
        print("Sin ACKs")


if __name__ == "__main__":
    main()
