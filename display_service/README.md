# display-service

Servicio consumer único: lee eventos de los 3 canales SHM (radar, lpr, npu) y controla el LED.

## Entrada
- Canal SHM `radar` (consumer)
- Canal SHM `lpr` (consumer)
- Canal SHM `npu` (consumer)

## Salida
- TCP al controlador LED (`192.168.0.222:5200` por defecto)
- HTTP `0.0.0.0:8081` para control manual del display (modo texto/picture/radar)

## Arranque
```
python -m display_service.main
```

## Archivos a migrar aquí (desde Python/)
- `display_manager.py` → `manager.py` (reemplazar `_placas_q`/`_velocidades_q` por lectura SHM de 3 canales)
- `display_web_server.py` → `web_server.py`
- `led_controller_handler.py`, `led_controller_socket.py`, `led_controller_constants.py` → `led/`
- crear `main.py`

## Notas
- Único **consumer** de los 3 buses. Si arranca antes que los productores, espera pasivamente.
- Si uno de los productores cae, los otros siguen llegando — ese es el punto de separar en servicios.
- Las placas llevan `plate_pic_path` (ruta en disco compartido). El display-service lee el JPEG desde esa ruta.

## Dependencias
- `shared.shm_bus`, `shared.config_loader`
