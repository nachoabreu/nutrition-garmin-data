#!/bin/bash
# Carga credenciales desde ~/.garmin_env (fuera de Drive, permisos 600)
ENV_FILE="$HOME/.garmin_env"
if [ ! -f "$ENV_FILE" ]; then
    echo "❌  No se encontró $ENV_FILE con las credenciales."
    exit 1
fi
set -a
source "$ENV_FILE"
set +a

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/garmin_daily.py" "$@"
