#!/bin/bash
# run_garmin_server.sh
#
# Corre garmin_daily.py para un usuario específico y sube el JSON a su Drive.
#
# Uso:
#   bash run_garmin_server.sh <usuario> [YYYY-MM-DD]
#
# Ejemplos:
#   bash run_garmin_server.sh nacho                  # nacho, fecha de hoy
#   bash run_garmin_server.sh nacho 2026-06-05       # nacho, fecha específica
#   bash run_garmin_server.sh laura 2026-06-05       # laura, fecha específica

set -e

USER_NAME="${1}"
DATE_ARG="${2}"

if [ -z "$USER_NAME" ]; then
    echo "❌ Uso: bash run_garmin_server.sh <usuario> [YYYY-MM-DD]"
    exit 1
fi

CONFIG_FILE="$HOME/.garmin_users/$USER_NAME/config.env"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Config no encontrada: $CONFIG_FILE"
    exit 1
fi

# Cargar config del usuario
set -a
source "$CONFIG_FILE"
set +a

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/logs/$USER_NAME"
LOG="$LOG_DIR/garmin.log"

mkdir -p "$LOG_DIR"
echo "" >> "$LOG"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') === [$USER_NAME]" >> "$LOG"

# Correr el script Python
if [ -n "$DATE_ARG" ]; then
    python3 "$SCRIPT_DIR/garmin_daily.py" "$DATE_ARG" >> "$LOG" 2>&1
    RUN_DATE="$DATE_ARG"
else
    python3 "$SCRIPT_DIR/garmin_daily.py" >> "$LOG" 2>&1
    RUN_DATE=$(date '+%Y-%m-%d')
fi

# Subir JSON al Drive del usuario
JSON_FILE="$SCRIPT_DIR/garmin_${RUN_DATE}.json"

if [ -f "$JSON_FILE" ]; then
    rclone copy "$JSON_FILE" "$DRIVE_PATH" >> "$LOG" 2>&1
    echo "✅ [$USER_NAME] Subido a Drive: garmin_${RUN_DATE}.json → $DRIVE_PATH" >> "$LOG"
    echo "✅ [$USER_NAME] Subido a Drive: garmin_${RUN_DATE}.json → $DRIVE_PATH"
else
    echo "❌ [$USER_NAME] JSON no encontrado: $JSON_FILE" >> "$LOG"
    echo "❌ [$USER_NAME] JSON no encontrado: $JSON_FILE"
fi
