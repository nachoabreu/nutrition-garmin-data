#!/usr/bin/env python3
"""
garmin_cron_controller.py

Corre cada 30 minutos (via cron). Detecta el timezone local del usuario
a partir de las coordenadas GPS de su última actividad Garmin, y ejecuta
el script principal si la hora local está entre las 22:00 y las 24:00.

Dentro de esa ventana corre cada 30 minutos y PISA el mismo archivo JSON
del día, acumulando los datos más recientes hasta la medianoche.

Lógica:
  1. Obtener lat/lon de la última actividad con GPS de Garmin
  2. Detectar timezone desde esas coordenadas (timezonefinder)
  3. Calcular hora local actual en ese timezone
  4. Si está entre 22:00 y 24:00 → ejecutar y pisar el JSON existente
  5. Fuera de esa ventana → salir sin hacer nada
"""

import os, subprocess
from datetime import datetime
from pathlib import Path

# ─── config ──────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path("/home/ubuntu/nutrition-garmin-data")
LOG         = Path("/home/ubuntu/logs/garmin_cron_controller.log")
WINDOW_START = 22   # hora local desde la que empieza a correr
WINDOW_END   = 24   # hora local hasta la que corre (24 = medianoche)
DEFAULT_TZ   = "America/Montevideo"

# ─── helpers ─────────────────────────────────────────────────────────────────

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def get_gps_from_garmin() -> tuple:
    """Autentica en Garmin y devuelve lat/lon de la última actividad con GPS."""
    try:
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

        log("Sin GPS en actividades recientes — usando Montevideo por defecto")
        return -34.89, -56.05

    except Exception as e:
        log(f"Error obteniendo GPS: {e} — usando default")
        return -34.89, -56.05

def get_timezone(lat: float, lon: float) -> str:
    try:
        from timezonefinder import TimezoneFinder
        tz = TimezoneFinder().timezone_at(lat=lat, lng=lon)
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
            return datetime.now(pytz.timezone(tz_name))
        except Exception as e:
            log(f"Error obteniendo hora local: {e} — usando UTC")
            return datetime.utcnow()

def in_window(local_dt: datetime) -> bool:
    """True si la hora local está entre WINDOW_START y WINDOW_END."""
    h = local_dt.hour + local_dt.minute / 60
    return WINDOW_START <= h < WINDOW_END

# ─── main ────────────────────────────────────────────────────────────────────

def main():
    Path("/home/ubuntu/logs").mkdir(parents=True, exist_ok=True)

    lat, lon = get_gps_from_garmin()
    tz_name  = get_timezone(lat, lon)
    local_dt = get_local_time(tz_name)

    log(f"Timezone: {tz_name} | Hora local: {local_dt.strftime('%H:%M')} | Ventana: {WINDOW_START:02d}:00–{WINDOW_END:02d}:00")

    if not in_window(local_dt):
        log("Fuera de la ventana horaria — sin acción")
        return

    # Fecha local — puede diferir de la fecha UTC del servidor
    local_date = local_dt.strftime("%Y-%m-%d")
    log(f"✅ Dentro de la ventana — ejecutando garmin_daily.py para {local_date}")

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
        return

    # Subir JSON a Drive — rclone copy pisa el archivo existente automáticamente
    json_file = SCRIPT_DIR / f"garmin_{local_date}.json"
    if json_file.exists():
        upload = subprocess.run(
            ["rclone", "copy", str(json_file), "gdrive:Salud/nutrition"],
            capture_output=True, text=True,
        )
        if upload.returncode == 0:
            log(f"✅ Drive actualizado: garmin_{local_date}.json")
        else:
            log(f"❌ Error subiendo a Drive: {upload.stderr}")
    else:
        log(f"❌ JSON no encontrado: {json_file}")

if __name__ == "__main__":
    main()
