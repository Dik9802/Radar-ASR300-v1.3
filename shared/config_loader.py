# shared/config_loader.py
"""
Lee config.ini y expone helpers tipados (get_str, get_int, get_float, get_bool...).
Soporta comentarios inline con ';' y '#'.

Busca config.ini en este orden:
  1. Argumento `config_path` o env var CONFIG_INI
  2. Junto a este archivo (shared/config.ini)
  3. En el parent de shared/ (Python/config.ini)  ← ubicación real del proyecto
  4. Directorio de trabajo actual
"""
from __future__ import annotations

import os
import configparser
from pathlib import Path
from typing import Optional, Tuple


def resolve_ini_path(config_path: Optional[str] = None, config_name: str = "config.ini") -> Path:
    candidates = []
    if config_path:
        candidates.append(Path(config_path))
    envp = os.getenv("CONFIG_INI")
    if envp:
        candidates.append(Path(envp))
    here = Path(__file__).resolve().parent
    candidates.append(here / config_name)           # shared/config.ini
    candidates.append(here.parent / config_name)    # Python/config.ini (parent)
    candidates.append(Path.cwd() / config_name)
    for p in candidates:
        if p and p.is_file():
            return p
    raise FileNotFoundError(
        f"No se encontró {config_name}. Busqué en: {[str(p) for p in candidates]}"
    )


def read_ini(
    config_path: Optional[str] = None,
    config_name: str = "config.ini",
    apply_env_overrides: bool = False,
) -> configparser.ConfigParser:
    path = resolve_ini_path(config_path, config_name=config_name)
    ini = configparser.ConfigParser(
        interpolation=configparser.ExtendedInterpolation(),
        inline_comment_prefixes=(";", "#"),
    )
    with path.open("r", encoding="utf-8") as f:
        ini.read_file(f)

    if apply_env_overrides:
        if "HTTP_CLIENT_BASE_URL" in os.environ:
            if not ini.has_section("HTTP_CLIENT"):
                ini.add_section("HTTP_CLIENT")
            ini.set("HTTP_CLIENT", "BASE_URL", os.environ["HTTP_CLIENT_BASE_URL"])
    return ini


def _ensure_section(ini: configparser.ConfigParser, section: str) -> configparser.SectionProxy:
    if section not in ini:
        raise KeyError(f"No existe la sección [{section}] en config.ini")
    return ini[section]


def _clean_value(value: str) -> str:
    for sep in (";", "#"):
        if sep in value:
            value = value.split(sep, 1)[0]
    return value.strip()


def get_str(ini, section, option, default=None, *, required=False):
    try:
        s = _ensure_section(ini, section)
        if option in s and s.get(option) is not None:
            return _clean_value(s.get(option))
    except KeyError:
        pass
    if required and default is None:
        raise ValueError(f"Falta la clave '{option}' en [{section}] y no hay default.")
    return default


def get_int(ini, section, option, default=None, *, required=False):
    try:
        s = _ensure_section(ini, section)
        if option in s:
            try:
                value_str = _clean_value(s.get(option))
                if value_str.lower().startswith("0x"):
                    return int(value_str, 16)
                return int(value_str)
            except Exception as e:
                raise ValueError(f"'{option}' en [{section}] no es int válido: {e}")
    except KeyError:
        pass
    if required and default is None:
        raise ValueError(f"Falta la clave '{option}' en [{section}] y no hay default.")
    return default


def get_float(ini, section, option, default=None, *, required=False):
    try:
        s = _ensure_section(ini, section)
        if option in s:
            try:
                return float(_clean_value(s.get(option)))
            except Exception as e:
                raise ValueError(f"'{option}' en [{section}] no es float válido: {e}")
    except KeyError:
        pass
    if required and default is None:
        raise ValueError(f"Falta la clave '{option}' en [{section}] y no hay default.")
    return default


def get_bool(ini, section, option, default=None, *, required=False):
    try:
        s = _ensure_section(ini, section)
        if option in s:
            try:
                v = _clean_value(s.get(option)).lower()
                if v in ("true", "1", "yes", "on"):
                    return True
                if v in ("false", "0", "no", "off"):
                    return False
                raise ValueError(f"Valor booleano no reconocido: '{v}'")
            except Exception as e:
                raise ValueError(f"'{option}' en [{section}] no es bool válido: {e}")
    except KeyError:
        pass
    if required and default is None:
        raise ValueError(f"Falta la clave '{option}' en [{section}] y no hay default.")
    return default


def get_listen_config(ini, section: str, default_ip="0.0.0.0", default_port=8080) -> Tuple[str, int]:
    try:
        listen_ip = get_str(ini, section, "LISTEN_IP", default_ip) or default_ip
        listen_port = get_int(ini, section, "LISTEN_PORT", default_port) or default_port
        return listen_ip, listen_port
    except KeyError:
        return default_ip, default_port


def section_dict(ini, section):
    try:
        s = _ensure_section(ini, section)
        return {k: v for k, v in s.items()}
    except KeyError:
        return {}


def save_config_value(section: str, key: str, value: str, config_path: Optional[str] = None) -> None:
    path = resolve_ini_path(config_path)
    cfg = configparser.ConfigParser()
    cfg.read(str(path), encoding="utf-8")
    if section not in cfg:
        cfg.add_section(section)
    cfg.set(section, key, value)
    with open(str(path), "w", encoding="utf-8") as f:
        cfg.write(f)
