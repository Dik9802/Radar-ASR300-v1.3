"""
Prueba rápida de shm_bus: un productor y un consumer en subprocesos distintos.

Uso:
    python test_shm_bus.py producer
    python test_shm_bus.py consumer
    python test_shm_bus.py benchmark   # todo en un solo proceso
"""
import os
import sys
import time

# Permite ejecutar desde c:/Git/Radar-ASR300P-SBC/Python/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.shm_bus import EventBus, CHANNEL_RADAR


def producer():
    bus = EventBus(CHANNEL_RADAR, role="producer")
    try:
        i = 0
        while True:
            ts = int(time.time() * 1000)
            bus.publish({"kind": "speed", "speed": float(i % 120), "ts_ms": ts, "n": i})
            print(f"[PROD] seq={i+1} speed={i % 120}")
            i += 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[PROD] cerrando; unlinking SHM")
        bus.unlink()


def consumer():
    bus = EventBus(CHANNEL_RADAR, role="consumer")
    try:
        while True:
            evt = bus.read_blocking(poll_interval=0.001)
            print(f"[CONS] recibido: {evt}")
    except KeyboardInterrupt:
        print("\n[CONS] cerrando")
        bus.close()


def benchmark():
    """Mide latencia y throughput con productor+consumer en el mismo proceso."""
    prod = EventBus("bench", role="producer")
    cons = EventBus("bench", role="consumer")

    N = 10000
    start = time.perf_counter()
    for i in range(N):
        prod.publish({"n": i, "ts_ms": int(time.time() * 1000)})
        got = cons.read()
        assert got is not None, f"perdimos evento {i}"
        assert got["n"] == i, f"orden roto: esperado {i}, recibido {got['n']}"
    elapsed = time.perf_counter() - start

    lat_us = (elapsed / N) * 1e6
    tput = N / elapsed
    print(f"{N} round-trips en {elapsed:.3f}s")
    print(f"  latencia pub+read: {lat_us:.2f} µs")
    print(f"  throughput: {tput:.0f} msg/s")

    cons.close()
    prod.unlink()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "benchmark"
    if mode == "producer":
        producer()
    elif mode == "consumer":
        consumer()
    elif mode == "benchmark":
        benchmark()
    else:
        print(f"modo desconocido: {mode}")
        sys.exit(1)
