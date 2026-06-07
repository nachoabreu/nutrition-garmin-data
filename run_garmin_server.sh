#!/bin/bash
# run_garmin_server.sh
#
# Wrapper para correr garmin_daily.py en el servidor y subir el JSON a Drive.
# Usado por run_garmin_server.sh directamente o por garmin_cron_controller.py.
#
# Uso:
#   bash run_garmin_server.sh           # fecha de hoy (hora local)
#   bash run_garmin_server.sh 2026-06-05  # fecha específica

set -a
source "$HOME/.garmin_env"
set +a

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVE_PATH="gdrive:Salud/nutrition"
LOG="$HOME/logs/garmin_daily.log"

mkdir -p "$HOME/logs"
echo "" >> "$LOG"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"

python3 "$SCRIPT_DIR/garmin_daily.py" "$@" >> "$LOG" 2>&1

DATE="${1:-$(date '+%Y-%m-%d')}"
JSON_FILE="$SCRIPT_DIR/garmin_${DATE}.json"

if [ -f "$JSON_FILE" ]; then
    rclone copy "$JSON_FILE" "$DRIVE_PATH" >> "$LOG" 2>&1
    echo "✅ Subido a Drive: garmin_${DATE}.json" >> "$LOG"
else
    echo "❌ JSON no encontrado: $JSON_FILE" >> "$LOG"
fi
