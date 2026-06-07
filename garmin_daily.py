#!/usr/bin/env python3
"""
garmin_daily.py — Extrae estadísticas diarias de Garmin Connect y las guarda como JSON.

Uso:
    python garmin_daily.py [YYYY-MM-DD]   (default: hoy)

Variables de entorno requeridas:
    GARMIN_EMAIL    — email de tu cuenta Garmin Connect
    GARMIN_PASSWORD — contraseña de Garmin Connect

Opcional:
    GARMIN_TOKENSTORE — directorio para guardar tokens de sesión (default: ~/.garmin_tokens)
    CALORIES_IN       — calorías consumidas hoy (default: 0, completar manualmente)
    CITY              — ciudad para clima (default: Barros Blancos, Canelones, Uruguay)
"""

import os
import sys
import json
import logging
from datetime import date, timedelta
from pathlib import Path

try:
    from garminconnect import Garmin, GarminConnectAuthenticationError
except ImportError:
    sys.exit("❌  Instalá la librería: pip install garminconnect")

logging.basicConfig(level=logging.WARNING)

# ─── helpers ──────────────────────────────────────────────────────────────────

def safe(d, *keys, default=None):
    """Navega un dict anidado con seguridad."""
    val = d
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k)
        if val is None:
            return default
    return val

def secs_to_min(secs):
    if secs is None:
        return None
    return round(secs / 60)

def meters_to_km(m):
    if m is None:
        return None
    return round(m / 1000, 2)

def sleep_quality_label(score):
    if score is None:
        return None
    if score >= 90: return "excelente"
    if score >= 75: return "bueno"
    if score >= 60: return "regular"
    return "malo"

def hrv_status_label(s):
    if not s:
        return None
    mapping = {
        "BALANCED": "equilibrado", "LOW": "bajo",
        "UNBALANCED": "desequilibrado", "POOR": "pobre", "GOOD": "bueno",
    }
    return mapping.get(str(s).upper(), str(s).lower())

def vo2_rating_label(v):
    if v is None: return None
    if v >= 52: return "superior"
    if v >= 45: return "excelente"
    if v >= 38: return "bueno"
    if v >= 31: return "moderado"
    return "bajo"

# ─── autenticación ────────────────────────────────────────────────────────────

def get_client():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    tokenstore = os.environ.get("GARMIN_TOKENSTORE", str(Path.home() / ".garmin_tokens"))

    if not email or not password:
        sys.exit("❌  Definí GARMIN_EMAIL y GARMIN_PASSWORD como variables de entorno.")

    client = Garmin(email=email, password=password)
    token_path = Path(tokenstore)
    token_path.mkdir(parents=True, exist_ok=True)

    try:
        client.login(str(token_path))
        print("✓ Sesión restaurada desde tokens guardados")
    except Exception:
        print("⟳ Autenticando con usuario/contraseña...")
        try:
            client.login()
            client.garth.dump(str(token_path))
            print(f"✓ Tokens guardados en {token_path}")
        except GarminConnectAuthenticationError as e:
            sys.exit(f"❌  Error de autenticación: {e}")

    return client

# ─── llamadas a la API ────────────────────────────────────────────────────────

def fetch_all(client, target_date: date) -> dict:
    date_str = target_date.isoformat()
    yesterday_str = (target_date - timedelta(days=1)).isoformat()

    calls = {
        "stats":           lambda: client.get_stats(date_str),
        "heart_rates":     lambda: client.get_heart_rates(date_str),
        "sleep":           lambda: client.get_sleep_data(date_str),
        "hrv":             lambda: client.get_hrv_data(date_str),
        "stress":          lambda: client.get_stress_data(date_str),
        "body_battery":    lambda: client.get_body_battery(yesterday_str, date_str),
        "respiration":     lambda: client.get_respiration_data(date_str),
        "spo2":            lambda: client.get_spo2_data(date_str),
        "activities":      lambda: client.get_activities_by_date(date_str, date_str),
        "max_metrics":     lambda: client.get_max_metrics(date_str),
        "recent_gps":      lambda: client.get_activities(0, 10),  # para extraer coords GPS
        # "skin_temp": not available in this garminconnect version
    }

    results = {}
    for name, fn in calls.items():
        try:
            results[name] = fn()
            print(f"  ✓ {name}")
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            results[name] = None

    return results

# ─── construcción del JSON ────────────────────────────────────────────────────

def build_garmin(r: dict) -> dict:
    stats      = r.get("stats") or {}
    hr_data    = r.get("heart_rates") or {}
    sleep_root = r.get("sleep") or {}
    sleep      = sleep_root.get("dailySleepDTO") or {}
    hrv_root   = r.get("hrv") or {}
    activities = r.get("activities") or []
    max_m      = r.get("max_metrics") or {}

    # HRV summary — distintos formatos según versión de API
    if isinstance(hrv_root, dict):
        hrv_sum = hrv_root.get("hrvSummary") or hrv_root
    else:
        hrv_sum = {}

    # HR máximo del día desde la lista de lecturas
    hr_values = hr_data.get("heartRateValues") or []
    day_max_hr = None
    if hr_values:
        valid = [v[1] for v in hr_values if isinstance(v, (list, tuple)) and len(v) > 1 and v[1]]
        day_max_hr = max(valid) if valid else None

    # Tipo de actividad
    act_type = "ninguna"
    if activities:
        act_type = safe(activities[0], "activityType", "typeKey") or "ninguna"

    # VO2 max
    vo2 = None
    if isinstance(max_m, list) and max_m:
        raw = safe(max_m[0], "generic", "vo2MaxPreciseValue") or safe(max_m[0], "generic", "vo2MaxValue")
        vo2 = round(raw) if raw else None
    elif isinstance(max_m, dict):
        raw = max_m.get("vo2MaxPreciseValue") or max_m.get("vo2MaxValue")
        vo2 = round(raw) if raw else None

    # Skin temp — viene en el root de sleep_data (no en dailySleepDTO)
    skin_change = sleep_root.get("avgSkinTempDeviationC")

    # HR nocturno — está en el root de sleep_data como avgHeartRate
    hr_noc = sleep.get("avgHeartRate") or sleep_root.get("restingHeartRate")

    # Restless moments — en el root de sleep_data como lista
    restless_list = sleep_root.get("sleepRestlessMoments") or []
    restless_count = len(restless_list) if isinstance(restless_list, list) else None

    # Body battery gain durante el sueño — en el root de sleep_data
    bb_gain = sleep_root.get("bodyBatteryChange")

    # Sleep score
    sleep_score_val = (
        safe(sleep, "sleepScores", "overall", "value")
        or sleep.get("sleepScore")
    )

    return {
        "active_kcal":                    stats.get("activeKilocalories"),
        "steps":                          stats.get("totalSteps"),
        "distance_km":                    meters_to_km(stats.get("totalDistanceMeters")),
        "activity_type":                  act_type,
        "intensity_minutes_moderate":     stats.get("moderateIntensityMinutes"),
        "intensity_minutes_high":         stats.get("vigorousIntensityMinutes"),
        "resting_hr_bpm":                 stats.get("restingHeartRate"),
        "hr_nocturnal_avg_bpm":           hr_noc,
        "hr_max_bpm":                     day_max_hr or stats.get("maxHeartRate"),
        "hrv_ms":                         hrv_sum.get("lastNight5MinHigh") or hrv_sum.get("lastNightAvg"),
        "hrv_7day_avg_ms":                hrv_sum.get("weeklyAvg"),
        "hrv_5min_max_ms":                hrv_sum.get("lastNight5MinHigh"),
        "hrv_rmssd_ms":                   hrv_sum.get("rmssd") or hrv_sum.get("lastNightAvg"),
        "hrv_sdrr_ms":                    hrv_sum.get("sdrr"),
        "hrv_status":                     hrv_status_label(hrv_sum.get("hrvStatus") or hrv_sum.get("status")),
        "sleep_score":                    sleep_score_val,
        "sleep_quality":                  sleep_quality_label(sleep_score_val),
        "sleep_duration_min":             secs_to_min(sleep.get("sleepTimeSeconds")),
        "sleep_deep_min":                 secs_to_min(sleep.get("deepSleepSeconds")),
        "sleep_light_min":                secs_to_min(sleep.get("lightSleepSeconds")),
        "sleep_rem_min":                  secs_to_min(sleep.get("remSleepSeconds")),
        "sleep_awake_min":                secs_to_min(sleep.get("awakeSleepSeconds")),
        "sleep_restless_moments":         restless_count,
        "sleep_body_battery_gain":        bb_gain,
        "spo2_avg_pct":                   sleep.get("averageSpO2Value"),
        "spo2_nocturnal_pct":             sleep.get("averageSpO2HRSleep"),
        "spo2_min_pct":                   sleep.get("lowestSpO2Value"),
        "respiration_awake_avg_brpm":     sleep.get("avgWakingRespirationValue"),
        "respiration_min_brpm":           sleep.get("lowestRespirationValue"),
        "respiration_max_brpm":           sleep.get("highestRespirationValue"),
        "respiration_nocturnal_avg_brpm": sleep.get("avgSleepRespirationValue"),
        "vo2_max":                        vo2,
        "vo2_max_rating":                 vo2_rating_label(vo2),
        "skin_temp_change_c":             round(skin_change, 1) if skin_change is not None else None,
        "body_battery_high":              stats.get("bodyBatteryHighestValue"),
        "body_battery_low":               stats.get("bodyBatteryLowestValue"),
    }

def build_garmin_context(r: dict) -> dict:
    stats        = r.get("stats") or {}
    stress_root  = r.get("stress") or {}
    body_battery = r.get("body_battery") or []

    # Stress: stats tiene desglose completo con duración en segundos
    stress_avg        = stats.get("averageStressLevel")
    stress_rest_min   = secs_to_min(stats.get("restStressDuration"))
    stress_low_min    = secs_to_min(stats.get("lowStressDuration"))
    stress_medium_min = secs_to_min(stats.get("mediumStressDuration"))
    stress_high_min   = secs_to_min(stats.get("highStressDuration"))

    # Fallback si stats no tiene stress (raro, pero posible)
    if stress_avg is None:
        if isinstance(stress_root, list):
            values = [v[1] for v in stress_root if isinstance(v, (list, tuple)) and len(v) > 1 and v[1] is not None and v[1] >= 0]
            stress_avg = round(sum(values) / len(values)) if values else None
        elif isinstance(stress_root, dict):
            stress_avg = stress_root.get("overallStressLevel") or stress_root.get("avgStressLevel")

    # Body battery — usar los valores de stats que son más precisos
    bb_start = stats.get("bodyBatteryAtWakeTime")
    bb_end   = stats.get("bodyBatteryMostRecentValue")
    bb_high  = stats.get("bodyBatteryHighestValue")
    bb_low   = stats.get("bodyBatteryLowestValue")

    # Fallback con body_battery list si stats no tiene
    if bb_start is None and isinstance(body_battery, list) and body_battery:
        items = sorted(body_battery, key=lambda x: x[0] if isinstance(x, (list, tuple)) else x.get("startTimestampGMT", ""))
        first, last = items[0], items[-1]
        if isinstance(first, dict):
            bb_start = first.get("charged") or first.get("bodyBatteryLevel")
            bb_end   = last.get("charged") or last.get("bodyBatteryLevel")
        elif isinstance(first, (list, tuple)) and len(first) > 1:
            bb_start = first[1]
            bb_end   = last[1]

    return {
        "stress_avg_1_100":   stress_avg,
        "stress_rest_min":    stress_rest_min,
        "stress_low_min":     stress_low_min,
        "stress_medium_min":  stress_medium_min,
        "stress_high_min":    stress_high_min,
        "body_battery_start": bb_start,
        "body_battery_end":   bb_end,
        "body_battery_high":  bb_high,
        "body_battery_low":   bb_low,
        "stress_source":      "garmin_auto",
    }

def fetch_weather(city: str) -> dict:
    """Clima via Open-Meteo (gratuito, sin API key)."""
    try:
        import urllib.request, urllib.parse
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=es"
        with urllib.request.urlopen(geo_url, timeout=5) as resp:
            geo = json.loads(resp.read())
        loc = geo["results"][0]
        lat, lon = loc["latitude"], loc["longitude"]

        wx_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code"
            f"&forecast_days=1"
        )
        with urllib.request.urlopen(wx_url, timeout=5) as resp:
            wx = json.loads(resp.read())
        cur = wx["current"]

        # Mapeo básico de weather_code WMO → descripción
        wmo = {
            0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
            45: "niebla", 51: "llovizna leve", 61: "lluvia leve", 63: "lluvia moderada",
            71: "nieve leve", 80: "chubascos", 95: "tormenta",
        }
        code = cur.get("weather_code", 0)
        desc = wmo.get(code, f"código {code}")

        return {
            "temperature_c": cur.get("temperature_2m"),
            "humidity_pct":  cur.get("relative_humidity_2m"),
            "conditions":    desc,
            "source":        "open_meteo",
        }
    except Exception as e:
        print(f"  ✗ weather: {e}")
        return {"temperature_c": 0, "humidity_pct": 0, "conditions": "", "source": "auto_fetched"}

HOME_CITY    = "Barros Blancos"
HOME_COUNTRY = "Uruguay"

def get_gps_from_garmin(recent_activities: list) -> dict:
    """Extrae lat/lon de la actividad con GPS más reciente (cualquier tipo outdoor).

    Sin límite de días — el usuario hará una actividad outdoor el primer día
    de viaje para actualizar las coordenadas. Mientras no haya actividad en
    otro lugar, las coords anteriores siguen siendo válidas.
    Busca en cualquier actividad que tenga lat/lon, no solo tipos predefinidos.
    """
    if not recent_activities:
        return {}
    for act in recent_activities:
        lat = act.get("startLatitude")
        lon = act.get("startLongitude")
        if not (lat and lon):
            continue
        act_type = (act.get("activityType") or {}).get("typeKey", "unknown")
        act_date = act.get("startTimeLocal", "")[:10]
        return {
            "lat": lat, "lon": lon,
            "source": "garmin_gps",
            "activity_type": act_type,
            "activity_date": act_date,
            "location_name": act.get("locationName") or "",
        }
    return {}

def detect_location_by_ip() -> dict:
    """Fallback: detecta ubicación por IP."""
    try:
        import urllib.request
        with urllib.request.urlopen("https://ipapi.co/json/", timeout=5) as resp:
            data = json.loads(resp.read())
        return {
            "lat":     data.get("latitude"),
            "lon":     data.get("longitude"),
            "city":    data.get("city", ""),
            "country": data.get("country_name", ""),
            "source":  "ip",
        }
    except Exception as e:
        print(f"  ✗ ip location: {e}")
        return {"lat": -34.75, "lon": -56.0, "city": HOME_CITY, "country": HOME_COUNTRY, "source": "default"}

def reverse_geocode(lat: float, lon: float) -> dict:
    """Convierte coordenadas en nombre de ciudad (Nominatim, sin API key)."""
    try:
        import urllib.request, urllib.parse
        url = (
            f"https://nominatim.openstreetmap.org/reverse"
            f"?lat={lat}&lon={lon}&format=json&zoom=10"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "garmin-daily-script/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        addr = data.get("address", {})
        city    = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("suburb") or ""
        country = addr.get("country") or ""
        return {"city": city, "country": country}
    except Exception:
        return {"city": "", "country": ""}

def fetch_weather_by_coords(lat: float, lon: float) -> dict:
    """Clima completo via Open-Meteo con coordenadas exactas."""
    try:
        import urllib.request
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code,"
            f"apparent_temperature,wind_speed_10m,precipitation,cloud_cover,uv_index"
            f"&daily=uv_index_max,sunrise,sunset,daylight_duration,precipitation_sum"
            f"&forecast_days=1&timezone=auto"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            wx = json.loads(resp.read())
        cur   = wx["current"]
        daily = wx["daily"]

        wmo = {
            0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
            45: "niebla", 51: "llovizna leve", 61: "lluvia leve", 63: "lluvia moderada",
            71: "nieve leve", 80: "chubascos", 95: "tormenta",
        }
        code = cur.get("weather_code", 0)
        desc = wmo.get(code, f"código {code}")

        return {
            "temperature_c":       cur.get("temperature_2m"),
            "feels_like_c":        cur.get("apparent_temperature"),
            "humidity_pct":        cur.get("relative_humidity_2m"),
            "conditions":          desc,
            "wind_speed_kmh":      cur.get("wind_speed_10m"),
            "precipitation_mm":    cur.get("precipitation"),
            "cloud_cover_pct":     cur.get("cloud_cover"),
            "uv_index_now":        cur.get("uv_index"),
            "uv_index_max_day":    daily.get("uv_index_max", [None])[0],
            "sunrise":             daily.get("sunrise", [None])[0],
            "sunset":              daily.get("sunset", [None])[0],
            "daylight_hours":      round(daily.get("daylight_duration", [0])[0] / 3600, 1),
            "precipitation_day_mm": daily.get("precipitation_sum", [None])[0],
            "source":              "open_meteo",
        }
    except Exception as e:
        print(f"  ✗ weather: {e}")
        return {"temperature_c": None, "humidity_pct": None, "conditions": "", "source": "error"}

def build_environmental(raw_data: dict, city_override=None) -> dict:
    print("  ⟳ location...")

    if city_override:
        # Ciudad manual — usar geocoding para obtener coords
        loc_source = "manual"
        geo = {}
        try:
            import urllib.request, urllib.parse
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city_override)}&count=1&language=es"
            with urllib.request.urlopen(geo_url, timeout=5) as r:
                gdata = json.loads(r.read())
            res = gdata.get("results", [{}])[0]
            geo = {"lat": res.get("latitude"), "lon": res.get("longitude")}
        except Exception:
            pass
        lat      = geo.get("lat", -34.75)
        lon      = geo.get("lon", -56.0)
        city     = city_override
        country  = ""
        traveling = False
        print(f"  ✓ location manual: {city}")
    else:
        # 1. Intentar GPS de Garmin — usa la actividad outdoor más reciente sin límite de días.
        #    Lógica: el usuario hará una actividad outdoor el primer día de viaje para
        #    "registrar" la nueva ubicación. Mientras no haya actividad en otro lugar,
        #    las coordenadas siguen siendo válidas (sigue en casa).
        recent_acts = raw_data.get("recent_gps") or []
        gps = get_gps_from_garmin(recent_acts)

        if gps:
            lat, lon   = gps["lat"], gps["lon"]
            geo        = reverse_geocode(lat, lon)
            city       = geo.get("city") or gps.get("location_name") or ""
            country    = geo.get("country") or ""
            loc_source = f"garmin_gps ({gps['activity_type']} {gps['activity_date']})"
        else:
            # 2. Fallback: IP
            ip_loc     = detect_location_by_ip()
            lat, lon   = ip_loc["lat"], ip_loc["lon"]
            city       = ip_loc["city"]
            country    = ip_loc["country"]
            loc_source = ip_loc["source"]

        # Detectar si está viajando (fuera del país de casa)
        traveling = HOME_COUNTRY.lower() not in country.lower()
        flag = "✈️ viajando" if traveling else "🏠 en casa"
        print(f"  ✓ location: {city}, {country} | {loc_source} ({flag})")

    print("  ⟳ weather...")
    weather = fetch_weather_by_coords(lat, lon)
    uv_max  = weather.get("uv_index_max_day") or 0
    print(f"  ✓ weather: {weather.get('temperature_c')}°C, {weather.get('conditions')}, UV max {uv_max}")

    # DEV NOTE — uv_exposure_min, solar_intensity_lux_h, uv_source:
    # Garmin fenix 8 Solar registra exposición UV y luz solar en el dispositivo,
    # pero a junio 2026 NO expone estos datos por ningún endpoint de Garmin Connect API.
    # Cuando Garmin los publique, buscar en /wellness-service/wellness/ o en get_stats().
    # Por ahora se marcan como "Non data, ask user" para que el sistema que consuma
    # este JSON sepa que debe pedirle el dato al usuario manualmente.
    return {
        "weather":               weather,
        "uv_exposure_min":       "Non data, ask user",
        "solar_intensity_lux_h": "Non data, ask user",
        "uv_source":             "ask user",
        "city":                  city,
        "country":               country,
        "lat":                   round(lat, 4) if lat else None,
        "lon":                   round(lon, 4) if lon else None,
        "traveling":             traveling,
        "location_source":       loc_source,
    }

def build_caloric_balance(garmin_section: dict, calories_in: int, tmb_kcal: int = 1650) -> dict:
    active_kcal  = garmin_section.get("active_kcal") or 0
    daily_target = tmb_kcal + active_kcal
    net = (calories_in - daily_target) if calories_in else 0
    return {
        "calories_in":           calories_in,
        "tmb_kcal":              tmb_kcal,
        "garmin_active_kcal":    active_kcal,
        "garmin_data_available": active_kcal > 0,
        "daily_target_kcal":     daily_target,
        "target_source":         "garmin",
        "net_balance":           net,
        "balance_note":          "",
    }

# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    # Fecha objetivo
    target_date = date.today()
    if len(sys.argv) > 1:
        try:
            target_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            sys.exit("❌  Formato de fecha inválido. Usá YYYY-MM-DD")

    city         = os.environ.get("CITY") or None  # None = auto-detectar por IP
    calories_in  = int(os.environ.get("CALORIES_IN", "0"))
    tmb_kcal     = int(os.environ.get("TMB_KCAL", "1650"))

    print(f"\n📅 Extrayendo datos Garmin para {target_date}\n")

    # Auth
    client = get_client()

    # Fetch
    print("\n🔄 Llamando endpoints de Garmin Connect...")
    raw = fetch_all(client, target_date)

    # Build
    print("\n🔧 Construyendo JSON...")
    garmin_section = build_garmin(raw)

    output = {
        "date":                  target_date.isoformat(),
        "garmin":                garmin_section,
        "garmin_context":        build_garmin_context(raw),
        "environmental_context": build_environmental(raw_data=raw, city_override=city),
        "caloric_balance":       build_caloric_balance(garmin_section, calories_in, tmb_kcal),
    }

    # Guardar JSON en la carpeta del script (Drive)
    script_dir = Path(__file__).parent
    filename   = f"garmin_{target_date.isoformat()}.json"
    outpath    = script_dir / filename
    outpath.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ JSON guardado: {outpath.absolute()}")
    print("\n--- Preview ---")
    print(json.dumps(output, ensure_ascii=False, indent=2))

    return str(outpath.absolute())

if __name__ == "__main__":
    main()
