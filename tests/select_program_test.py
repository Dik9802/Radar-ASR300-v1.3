#!/usr/bin/env python3
"""
select_program_test.py — Cambia al programa #20 del display LED.
Uso: python select_program_test.py
"""
from display_service.led.led_controller_handler import (
    send_select_program_single,
    build_packets_for_select_program_single,
)


def main():
    program = 20
    
    packets = build_packets_for_select_program_single(program_number=program, save_to_flash=False)
    for i, pkt in enumerate(packets):
        hex_str = " ".join(f"{b:02x}" for b in pkt)
        print(f"TX[{i}] ({len(pkt)} bytes): {hex_str}")
    
    print(f"Seleccionando programa #{program}...")
    acks = send_select_program_single(
        program_number=program,
        save_to_flash=False,
        require_ack=False,
    )
    
    ok = sum(1 for a in acks if a.get("rr", 1) == 0)
    if acks and ok == len(acks):
        print(f"OK: Programa {program} seleccionado ({len(acks)} ACK(s))")
    elif acks:
        print(f"Parcial: {ok}/{len(acks)} ACKs OK")
    else:
        print("Sin ACKs")


if __name__ == "__main__":
    main()
