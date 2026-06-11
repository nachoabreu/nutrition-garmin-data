#!/usr/bin/env python3
"""
garmin_cron_controller.py

Corre cada 30 minutos (via cron). Itera sobre todos los usuarios en
~/.garmin_users/ y para cada uno:

  1. Lee su config.env (credenciales, Drive path, TMB, etc.)
  2. Salta si ACTIVE != "true"
  3. Obtiene lat/lon de su última actividad GPS en Garmin
  4. Detecta el timezone de esas coordenadas (timezonefinder, offline)
  5. Si la hora local está entre 22:00 y 24:00 → ejecuta garmin_daily.py
     con la fecha local y sube el JSON a su Drive personal
  6. Cada usuario tiene su propio log en ~/logs/<usuario>/garmin.log

Para agregar un usuario:
  1. Crear ~/.garmin_users/<nombre>/config.env  (ver formato abajo)
  2. Crear el remote de rclone: rclone config  →  nombre: gdrive_<nombre>
  3. Listo — el controller lo levanta automáticamente

Formato config.env:
  USER_NAME="nombre"
  GARMIN_EMAIL="..."
  GARMIN_PASSWORD="..."
  GARMIN_TOKENSTORE="/home/ubuntu/.garmin_users/<nombre>/garmin_tokens"
  DRIVE_PATH="gdrive_<nombre>:Carpeta/subcarpeta"
  TMB_KCAL="1650"
  ACTIVE="true"
  # CALORIES_IN="2000"
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

# ─── config global ────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path("/home/ubuntu/nutrition-garmin-data")
USERS_DIR    = Path.home() / ".garmin_users"
LOGS_DIR     = Path.home() / "logs"
WINDOW_START = 22    # hora local desde la que empieza a correr
WINDOW_END   = 24    # hora local hasta la que corre (24 = medianoche)
DEFAULT_TZ   = "America/Montevideo"

# ─── helpers ─────────────────────────────────────────────────────────────────

def get_logger(user_name: str):
    """Devuelve una función de log específica para el usuario."""
    log_dir = LOGS_DIR / user_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "garmin.log"

    def log(msg):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{user_name}] {msg}"
        print(line)
        with open(log_file, "a") as f:
            f.write(line + "\n")

    return log

def load_config(config_path: Path) -> dict:
    """Carga un config.env como diccionario."""
    config = {}
    for line in config_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            config[k.strip()] = v.strip().strip('"')
    return config

def get_gps_from_garmin(config: dict, log) -> tuple:
    """Autenticar en Garmin del usuario y obtener lat/lon de la última actividad con GPS."""
    try:
        env = {**os.environ, **config}
        from garminconnect import Garmin
        client = Garmin(email=config["GARMIN_EMAIL"], password=config["GARMIN_PASSWORD"])
        client.login(config["GARMIN_TOKENSTORE"])

        activities = client.get_activities(0, 10)
        for act in activities:
            lat = act.get("startLatitude")
            lon = act.get("startLongitude")
            if lat and lon:
                act_type = (act.get("activityType") or {}).get("typeKey", "?")
                act_date = act.get("startTimeLocal", "")[:10]
                log(f"GPS: {lat:.4f}, {lon:.4f} ({act_type} {act_date})")
                return lat, lon

        log("Sin GPS en actividades recientes — usando Montevideo por defecto")
        return -34.89, -56.05

    except Exception as e:
        log(f"Error obteniendo GPS: {e} — usando default")
        return -34.89, -56.05

def get_timezone(lat: float, lon: float, log) -> str:
    try:
        from timezonefinder import TimezoneFinder
        tz = TimezoneFinder().timezone_at(lat=lat, lng=lon)
        return tz or DEFAULT_TZ
    except Exception as e:
        log(f"Error detectando timezone: {e} — usando {DEFAULT_TZ}")
        return DEFAULT_TZ

def get_local_time(tz_name: str, log) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        try:
            import pytz
            return datetime.now(pytz.timezone(tz_name))
        except Exception as e:
            log(f"Error obteniendo hora local: {e} — usando UTC")
            return datetime.utcnow()

def in_window(local_dt: datetime) -> bool:
    h = local_dt.hour + local_dt.minute / 60
    return WINDOW_START <= h < WINDOW_END

# ─── proceso por usuario ──────────────────────────────────────────────────────

def run_for_user(user_dir: Path):
    config_path = user_dir / "config.env"
    if not config_path.exists():
        return

    config = load_config(config_path)
    user_name = config.get("USER_NAME", user_dir.name)
    log = get_logger(user_name)

    # Verificar si está activo
    if config.get("ACTIVE", "true").lower() != "true":
        log("Usuario inactivo (ACTIVE=false) — saltando")
        return

    lat, lon   = get_gps_from_garmin(config, log)
    tz_name    = get_timezone(lat, lon, log)
    local_dt   = get_local_time(tz_name, log)

    log(f"Timezone: {tz_name} | Hora local: {local_dt.strftime('%H:%M')} | Ventana: {WINDOW_START:02d}:00–{WINDOW_END:02d}:00")

    if not in_window(local_dt):
        log("Fuera de la ventana horaria — sin acción")
        return

    local_date = local_dt.strftime("%Y-%m-%d")
    log(f"✅ Dentro de la ventana — ejecutando garmin_daily.py para {local_date}")

    # Preparar entorno para garmin_daily.py
    env = {
        **os.environ,
        "GARMIN_EMAIL":     config["GARMIN_EMAIL"],
        "GARMIN_PASSWORD":  config["GARMIN_PASSWORD"],
        "GARMIN_TOKENSTORE": config["GARMIN_TOKENSTORE"],
        "TMB_KCAL":         config.get("TMB_KCAL", "1650"),
    }
    if "CALORIES_IN" in config:
        env["CALORIES_IN"] = config["CALORIES_IN"]

    result = subprocess.run(
        ["python3", str(SCRIPT_DIR / "garmin_daily.py"), local_date],
        env=env,
        capture_output=True,
        text=True,
    )

    if result.stdout:
        log(result.stdout.strip())
    if result.stderr:
        log(f"STDERR: {result.stderr.strip()}")

    if result.returncode != 0:
        log(f"❌ Error en garmin_daily.py (código {result.returncode})")
        return

    # Subir JSON al Drive del usuario — rclone pisa el archivo existente
    json_file  = SCRIPT_DIR / f"garmin_{local_date}.json"
    drive_path = config.get("DRIVE_PATH", "")
    if not drive_path:
        log("❌ DRIVE_PATH no configurado en config.env")
        return

    if json_file.exists():
        upload = subprocess.run(
            ["rclone", "copy", str(json_file), drive_path],
            capture_output=True, text=True,
        )
        if upload.returncode == 0:
            log(f"✅ Drive actualizado: garmin_{local_date}.json → {drive_path}")
        else:
            log(f"❌ Error subiendo a Drive: {upload.stderr.strip()}")
    else:
        log(f"❌ JSON no encontrado: {json_file}")

# ─── main ────────────────────────────────────────────────────────────────────

def main():
    if not USERS_DIR.exists():
        print(f"[ERROR] Directorio de usuarios no encontrado: {USERS_DIR}")
        return

    user_dirs = sorted([d for d in USERS_DIR.iterdir() if d.is_dir()])
    if not user_dirs:
        print(f"[ERROR] No hay usuarios configurados en {USERS_DIR}")
        return

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Procesando {len(user_dirs)} usuario(s): {[d.name for d in user_dirs]}")

    for user_dir in user_dirs:
        try:
            run_for_user(user_dir)
        except Exception as e:
            print(f"[ERROR] Fallo inesperado procesando {user_dir.name}: {e}")

if __name__ == "__main__":
    main()
