#!/usr/bin/env python3
"""
garmin_cron_controller.py

Corre cada 30 minutos (via cron). Detecta el timezone local del usuario
a partir de las coordenadas GPS de su última actividad Garmin, y ejecuta
el script principal si la hora local es 22:30 (±15 min) y no corrió hoy.

Lógica:
  1. Obtener lat/lon de la última actividad con GPS de Garmin
  2. Detectar timezone desde esas coordenadas (timezonefinder)
  3. Calcular hora local actual en ese timezone
  4. Si está entre 22:15 y 22:45 y no corrió hoy → ejecutar
  5. Si ya corrió hoy → salir sin hacer nada
"""

import os, sys, json, subprocess
from datetime import datetime, date
from pathlib import Path

# ─── config ──────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path("/home/ubuntu/nutrition-garmin-data")
LOCKFILE     = Path("/home/ubuntu/logs/garmin_last_run.txt")  # contiene la fecha del último run
LOG          = Path("/home/ubuntu/logs/garmin_cron_controller.log")
TARGET_HOUR  = 22
TARGET_MIN   = 30
WINDOW_MIN   = 15  # ±15 minutos de ventana de ejecución
DEFAULT_TZ   = "America/Montevideo"

# ─── helpers ─────────────────────────────────────────────────────────────────

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def already_ran_today():
    if not LOCKFILE.exists():
        return False
    last = LOCKFILE.read_text().strip()
    return last == date.today().isoformat()

def mark_ran_today():
    LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    LOCKFILE.write_text(date.today().isoformat())

def get_gps_from_garmin() -> tuple:
    """Autenticar en Garmin y obtener lat/lon de la última actividad con GPS."""
    try:
        # Cargar credenciales
        env_file = Path.home() / ".garmin_env"
        env = {}
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"')

        os.environ.update(env)

        from garminconnect import Garmin
        token_path = env.get("GARMIN_TOKENSTORE", str(Path.home() / ".garmin_tokens"))
        client = Garmin(email=env["GARMIN_EMAIL"], password=env["GARMIN_PASSWORD"])
        client.login(token_path)

        activities = client.get_activities(0, 10)
        for act in activities:
            lat = act.get("startLatitude")
            lon = act.get("startLongitude")
            if lat and lon:
                act_type = (act.get("activityType") or {}).get("typeKey", "?")
                act_date = act.get("startTimeLocal", "")[:10]
                log(f"GPS encontrado: {lat:.4f}, {lon:.4f} ({act_type} {act_date})")
                return lat, lon

        log("No se encontraron actividades con GPS — usando coordenadas de Uruguay por defecto")
        return -34.89, -56.05  # Montevideo

    except Exception as e:
        log(f"Error obteniendo GPS de Garmin: {e} — usando default")
        return -34.89, -56.05

def get_timezone(lat: float, lon: float) -> str:
    try:
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        tz = tf.timezone_at(lat=lat, lng=lon)
        return tz or DEFAULT_TZ
    except Exception as e:
        log(f"Error detectando timezone: {e} — usando {DEFAULT_TZ}")
        return DEFAULT_TZ

def get_local_time(tz_name: str) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        try:
            import pytz
            tz = pytz.timezone(tz_name)
            return datetime.now(tz)
        except Exception as e:
            log(f"Error obteniendo hora local: {e}")
            return datetime.utcnow()

def is_target_window(local_dt: datetime) -> bool:
    target_minutes = TARGET_HOUR * 60 + TARGET_MIN
    current_minutes = local_dt.hour * 60 + local_dt.minute
    return abs(current_minutes - target_minutes) <= WINDOW_MIN

# ─── main ────────────────────────────────────────────────────────────────────

def main():
    Path("/home/ubuntu/logs").mkdir(parents=True, exist_ok=True)

    if already_ran_today():
        log("Ya corrió hoy — saliendo")
        return

    lat, lon  = get_gps_from_garmin()
    tz_name   = get_timezone(lat, lon)
    local_dt  = get_local_time(tz_name)

    log(f"Timezone detectado: {tz_name} | Hora local: {local_dt.strftime('%H:%M')} | Target: {TARGET_HOUR:02d}:{TARGET_MIN:02d} ±{WINDOW_MIN}min")

    if not is_target_window(local_dt):
        log("Fuera de la ventana horaria — esperando próxima verificación")
        return

    # Usar la fecha LOCAL (no la del servidor en UTC)
    local_date = local_dt.strftime("%Y-%m-%d")
    log(f"✅ Dentro de la ventana — ejecutando garmin_daily.py para fecha local {local_date}")
    mark_ran_today()

    result = subprocess.run(
        ["python3", str(SCRIPT_DIR / "garmin_daily.py"), local_date],
        env={**os.environ},
        capture_output=True,
        text=True,
    )

    if result.stdout:
        log(result.stdout.strip())
    if result.stderr:
        log(f"STDERR: {result.stderr.strip()}")

    if result.returncode != 0:
        log(f"❌ Script terminó con error (código {result.returncode})")
        # Borrar el lockfile para que reintente en 30 min
        LOCKFILE.unlink(missing_ok=True)
        return

    # Subir JSON a Drive (usar fecha local, no UTC del servidor)
    run_date = local_date
    json_file = SCRIPT_DIR / f"garmin_{run_date}.json"
    if json_file.exists():
        upload = subprocess.run(
            ["rclone", "copy", str(json_file), "gdrive:Salud/nutrition"],
            capture_output=True, text=True,
        )
        if upload.returncode == 0:
            log(f"✅ Subido a Drive: garmin_{run_date}.json")
        else:
            log(f"❌ Error subiendo a Drive: {upload.stderr}")
    else:
        log(f"❌ JSON no encontrado: {json_file}")

if __name__ == "__main__":
    main()
