#!/usr/bin/env python3
"""
select_program_cc09_test.py — Prueba selección de programa #20 usando CC=0x09.
Formato CC=0x09: 09 [options] u16_be(1) + u16_be(program) -> 09 00 00 01 00 14
Uso: python select_program_cc09_test.py
"""
import struct
from display_service.led.led_controller_constants import ID_CODE, FLAGS
from display_service.led.led_controller_handler import (
    build_network_packet_legacy,
    send_packets_over_tcp,
)


def u16_be(v: int) -> bytes:
    return struct.pack(">H", v & 0xFFFF)


def build_cc09_program_packet(program_number: int, save_to_flash: bool = False) -> bytes:
    """CC=0x09: header 09 [opt] u16_be(1) + body u16_be(program)."""
    options = 0x01 if save_to_flash else 0x00
    cc_header = bytes([0x09, options & 0xFF]) + u16_be(1)
    body = u16_be(int(program_number) & 0xFFFF)
    cc_chunk = cc_header + body
    return build_network_packet_legacy(ID_CODE, 0x01, FLAGS, cc_chunk)


def main():
    program = 20
    packet = build_cc09_program_packet(program, save_to_flash=False)
    hex_str = " ".join(f"{b:02x}" for b in packet)
    print(f"CC=0x09 — Seleccionando programa #{program}")
    print(f"TX ({len(packet)} bytes): {hex_str}")
    print()

    acks = send_packets_over_tcp([packet], require_ack=False)

    ok = sum(1 for a in acks if a.get("rr", 1) == 0)
    if acks and ok == len(acks):
        print(f"OK: Programa {program} seleccionado ({len(acks)} ACK(s))")
    elif acks:
        print(f"Parcial: {ok}/{len(acks)} ACKs OK")
    else:
        print("Sin ACKs (puede que el controlador no soporte CC=0x09)")


if __name__ == "__main__":
    main()
