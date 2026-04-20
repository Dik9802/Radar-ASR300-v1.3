"""Vistas del panel de configuración del Radar ASR300P."""
import json
import logging

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

VALID_COLORS = ["RED", "GREEN", "YELLOW", "BLUE", "PURPLE", "CYAN", "WHITE"]
VALID_FONT_SIZES = [8, 12, 16, 24, 32, 40, 48, 56]


def _get_config_values():
    """Lee los valores actuales de SHOW_PLATE_* desde display_manager (en memoria)."""
    try:
        from display_service.manager import get_plate_display_config
        return get_plate_display_config()
    except Exception as e:
        logger.warning("No se pudo leer display_manager, leyendo desde config.ini: %s", e)
        from shared.config_loader import read_ini, get_bool
        ini = read_ini(apply_env_overrides=False)
        return {
            "show_plate_pic": get_bool(ini, "DISPLAY_MANAGER", "SHOW_PLATE_PIC", False),
            "show_plate_scene": get_bool(ini, "DISPLAY_MANAGER", "SHOW_PLATE_SCENE", False),
            "show_plate_text": get_bool(ini, "DISPLAY_MANAGER", "SHOW_PLATE_TEXT", True),
        }


def _get_display_state():
    """Lee el estado actual del display (modo, mensaje, color, font_size)."""
    try:
        from display_service.manager import get_display_mode, get_saved_text_params
        mode = get_display_mode()
        text_params = get_saved_text_params() or {}
        return {
            "mode": mode,
            "text_message": text_params.get("text", ""),
            "text_color": text_params.get("color", "GREEN"),
            "text_font_size": int(text_params.get("font_size", 24)),
        }
    except Exception as e:
        logger.warning("No se pudo leer display state, leyendo desde config.ini: %s", e)
        from shared.config_loader import read_ini, get_str, get_int
        ini = read_ini(apply_env_overrides=False)
        return {
            "mode": get_str(ini, "DISPLAY_STATE", "MODE", "radar") or "radar",
            "text_message": get_str(ini, "DISPLAY_STATE", "TEXT_MESSAGE", "") or "",
            "text_color": get_str(ini, "DISPLAY_STATE", "TEXT_COLOR", "GREEN") or "GREEN",
            "text_font_size": get_int(ini, "DISPLAY_STATE", "TEXT_FONT_SIZE", 24) or 24,
        }


def dashboard(request):
    """Página principal del panel."""
    config = _get_config_values()
    display_state = _get_display_state()
    return render(request, "panel/dashboard.html", {
        "config": config,
        "display_state": display_state,
        "valid_colors": VALID_COLORS,
        "valid_font_sizes": VALID_FONT_SIZES,
    })


@require_http_methods(["POST"])
def api_plate_config(request):
    """API para seleccionar qué mostrar al detectar placa (mutuamente excluyente)."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON inválido"}, status=400)

    selected = data.get("selected")
    valid_options = {"show_plate_pic", "show_plate_scene", "show_plate_text"}
    if selected not in valid_options:
        return JsonResponse({"error": f"Opción inválida: {selected}"}, status=400)

    # Mutuamente excluyente: activar el seleccionado, desactivar los demás
    new_values = {k: (k == selected) for k in valid_options}

    # 1) Persistir en config.ini
    try:
        from shared.config_loader import save_config_value
        for key, value in new_values.items():
            save_config_value("DISPLAY_MANAGER", key, str(value).lower())
    except Exception as e:
        logger.error("Error guardando en config.ini: %s", e)
        return JsonResponse({"error": f"Error guardando config: {e}"}, status=500)

    # 2) Actualizar globals en memoria (hot-reload)
    try:
        from display_service.manager import update_plate_display_config
        updated = update_plate_display_config(**new_values)
    except Exception as e:
        logger.warning("display_manager no disponible para hot-reload: %s", e)
        updated = new_values

    return JsonResponse({"ok": True, "config": updated})


@require_http_methods(["POST"])
def api_display_mode(request):
    """API para cambiar el modo del display (radar/text/picture)."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON inválido"}, status=400)

    mode = data.get("mode", "").lower().strip()
    if mode not in ("radar", "text"):
        return JsonResponse({"error": f"Modo inválido: {mode}"}, status=400)

    try:
        from display_service.manager import set_display_mode, get_display_mode
        set_display_mode(mode)

        # Cuando se cambia a radar, llamar al endpoint Flask /mode/radar
        # para detener el _resend_loop que re-envía texto periódicamente
        if mode == "radar":
            try:
                import urllib.request
                from shared.config_loader import read_ini, get_int
                ini = read_ini(apply_env_overrides=False)
                display_port = get_int(ini, "LED_CONTROLLER_WEBSERVER", "LISTEN_PORT", 8081)
                url = f"http://127.0.0.1:{display_port}/mode/radar"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    resp.read()
                logger.info("Resend thread detenido via Flask /mode/radar")
            except Exception as e:
                logger.warning("No se pudo detener resend thread via Flask: %s", e)

        return JsonResponse({"ok": True, "mode": get_display_mode()})
    except Exception as e:
        logger.error("Error cambiando modo: %s", e)
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["POST"])
def api_display_text(request):
    """API para enviar texto al display LED y cambiar a modo texto."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON inválido"}, status=400)

    text = data.get("text", "").strip()
    if not text:
        return JsonResponse({"error": "Se requiere 'text'"}, status=400)

    color = data.get("color", "GREEN").upper()
    if color not in VALID_COLORS:
        color = "GREEN"

    font_size = data.get("font_size", 24)
    try:
        font_size = int(font_size)
    except (ValueError, TypeError):
        font_size = 24
    if font_size not in VALID_FONT_SIZES:
        font_size = 24

    # 1) Cambiar a modo texto
    try:
        from display_service.manager import set_mode_texto, save_text_message_state
        set_mode_texto()
    except Exception as e:
        logger.warning("No se pudo cambiar a modo texto: %s", e)

    # 2) Enviar al display LED via el endpoint Flask existente (display_web_server en :8081)
    try:
        import urllib.request
        import urllib.parse
        from shared.config_loader import read_ini, get_int
        ini = read_ini(apply_env_overrides=False)
        display_port = get_int(ini, "LED_CONTROLLER_WEBSERVER", "LISTEN_PORT", 8081)

        params = urllib.parse.urlencode({
            "text": text,
            "color": color,
            "font_size": font_size,
            "align": "CENTER",
            "speed": 1,
            "stay_time": 10,
        })
        url = f"http://127.0.0.1:{display_port}/custom_text_message?{params}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode())

        return JsonResponse({"ok": True, "display_response": result})
    except Exception as e:
        # Fallback: al menos guardar en config.ini
        try:
            from display_service.manager import save_text_message_state
            save_text_message_state({
                "text": text, "color": color, "font_size": str(font_size),
                "align": "CENTER", "mode": "DRAW", "speed": 1, "stay_time": 10,
            })
        except Exception:
            pass
        logger.error("Error enviando texto al display: %s", e)
        return JsonResponse({
            "ok": False,
            "warning": "Texto guardado pero no se pudo enviar al display",
            "error": str(e),
        })
