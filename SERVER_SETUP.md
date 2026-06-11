# Server Setup — nutrition-garmin-data

Configuración del servidor AWS Lightsail para correr el extractor de datos Garmin diariamente y subir los JSON a Google Drive de forma automática.

---

## Servidor

| Parámetro | Valor |
|---|---|
| Provider | AWS Lightsail |
| IP | `63.178.52.9` |
| OS | Ubuntu 22.04 |
| Timezone | UTC |
| Usuario | `ubuntu` |
| SSH key | `~/.ssh/nacho-lightsail-operator-mac.pem` |

Conectarse:
```bash
ssh lightsail-operator-dev
# o directamente:
ssh -i ~/.ssh/nacho-lightsail-operator-mac.pem ubuntu@63.178.52.9
```

---

## Agregar un usuario nuevo

Solo 3 pasos. No hay que tocar código.

### 1. Crear la carpeta y config del usuario

```bash
mkdir -p ~/.garmin_users/<nombre>/garmin_tokens
chmod 700 ~/.garmin_users/<nombre>

cat > ~/.garmin_users/<nombre>/config.env << 'EOF'
USER_NAME="<nombre>"
GARMIN_EMAIL="email@ejemplo.com"
GARMIN_PASSWORD="contraseña"
GARMIN_TOKENSTORE="/home/ubuntu/.garmin_users/<nombre>/garmin_tokens"
DRIVE_PATH="gdrive_<nombre>:Carpeta/subcarpeta"
TMB_KCAL="1650"
ACTIVE="true"
# CALORIES_IN="2000"
EOF
chmod 600 ~/.garmin_users/<nombre>/config.env
```

### 2. Autorizar su Google Drive con rclone

En la Mac local:
```bash
rclone authorize "drive"
# El usuario autoriza en el browser con SU cuenta de Google
# Copiar el token JSON que aparece
```

En el servidor, agregar al final de `~/.config/rclone/rclone.conf`:
```ini
[gdrive_<nombre>]
type = drive
scope = drive
token = {"access_token":"...","refresh_token":"...","expiry":"..."}
team_drive =
```

Verificar:
```bash
rclone lsd gdrive_<nombre>:
```

### 3. Probar

```bash
bash ~/nutrition-garmin-data/run_garmin_server.sh <nombre> 2026-06-01
```

A partir de ese momento el cron lo levanta automáticamente junto a todos los demás usuarios.

### Pausar un usuario sin borrarlo

```bash
# Editar su config.env y cambiar:
ACTIVE="false"
```

### Estructura de archivos por usuario

```
~/.garmin_users/
    nacho/
        config.env          # credenciales + config (chmod 600)
        garmin_tokens/      # tokens de sesión Garmin (aislados)
    otro_usuario/
        config.env
        garmin_tokens/

~/logs/
    nacho/garmin.log        # log separado por usuario
    otro_usuario/garmin.log
```

---

## Instalación

### 1. Clonar el repo

```bash
cd ~
git clone https://github.com/nachoabreu/nutrition-garmin-data.git
```

### 2. Instalar dependencia Python

```bash
python3 -m pip install garminconnect
```

### 3. Credenciales Garmin

Crear `~/.garmin_env` con permisos 600 — **nunca subir al repo**:

```bash
cat > ~/.garmin_env << 'EOF'
GARMIN_EMAIL="tu@email.com"
GARMIN_PASSWORD="tu_contraseña"
GARMIN_TOKENSTORE="/home/ubuntu/.garmin_tokens"
TMB_KCAL="1650"
# CALORIES_IN="2000"  # descomentar si querés incluir calorías consumidas
EOF
chmod 600 ~/.garmin_env
```

### 4. Instalar rclone

```bash
curl -s https://rclone.org/install.sh | sudo bash
```

### 5. Configurar rclone con Google Drive

El servidor no tiene browser, así que la autorización OAuth se hace en la Mac local:

**En la Mac:**
```bash
brew install rclone
rclone authorize "drive"
# Autorizar en el browser con la cuenta de Google correcta
# Copiar el token JSON que aparece en la terminal
```

**En el servidor**, crear `~/.config/rclone/rclone.conf`:
```ini
[gdrive]
type = drive
scope = drive
token = {"access_token":"...","token_type":"Bearer","refresh_token":"...","expiry":"..."}
team_drive =
```

Verificar acceso:
```bash
rclone lsd gdrive:
rclone lsd "gdrive:Salud/nutrition"
```

---

## Script del servidor

`run_garmin_server.sh` hace tres cosas:
1. Carga las credenciales desde `~/.garmin_env`
2. Corre `garmin_daily.py` y genera el JSON
3. Sube el JSON a Google Drive con rclone

Los logs quedan en `~/logs/garmin_daily.log`.

Para correr manualmente:
```bash
bash ~/nutrition-garmin-data/run_garmin_server.sh           # hoy
bash ~/nutrition-garmin-data/run_garmin_server.sh 2026-06-05  # fecha específica
```

---

## Cron — ejecución automática con timezone inteligente

El cron no corre a una hora UTC fija. En cambio, `garmin_cron_controller.py` corre **cada 30 minutos** y:

1. Obtiene la última ubicación GPS de Garmin (lat/lon de la actividad más reciente con GPS)
2. Detecta el timezone de esas coordenadas con `timezonefinder` (sin API, offline)
3. Calcula la hora local actual en ese timezone
4. Si la hora local está entre **22:15 y 22:45** y no corrió hoy → ejecuta el script y sube a Drive
5. Si ya corrió hoy → sale sin hacer nada

Esto significa que **si viajás a otro país y hacés una actividad con GPS, el script se ajusta automáticamente** a la hora local del nuevo lugar.

Ver cron activo:
```bash
crontab -l
```

Configuración actual:
```
*/30 * * * * /usr/bin/python3 /home/ubuntu/nutrition-garmin-data/garmin_cron_controller.py >> /home/ubuntu/logs/garmin_cron.log 2>&1
```

Ver log del controller:
```bash
tail -50 ~/logs/garmin_cron.log
```

Correr manualmente (para testear):
```bash
python3 ~/nutrition-garmin-data/garmin_cron_controller.py
```

> **Nota:** Si querés forzar la ejecución aunque ya corrió hoy, borrá el lockfile:
> ```bash
> rm ~/logs/garmin_last_run.txt
> ```

---

## Seguridad

### UFW (firewall de Linux)

Solo permite entrada por SSH (puerto 22). Todo lo demás bloqueado.

```bash
# Ver estado
sudo ufw status verbose

# Si por alguna razón está inactivo, reactivar:
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw --force enable
```

**Auto-start al reiniciar:** ✅ habilitado (`systemctl is-enabled ufw`)

### fail2ban

Bloquea IPs que fallen SSH 3 veces en 10 minutos. Ban de 24 horas.

Configuración en `/etc/fail2ban/jail.local`:
```ini
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled  = true
port     = ssh
maxretry = 3
bantime  = 24h
```

```bash
# Ver estado
sudo fail2ban-client status sshd

# Ver IPs baneadas
sudo fail2ban-client status sshd | grep "Banned IP"
```

**Auto-start al reiniciar:** ✅ habilitado (`systemctl is-enabled fail2ban`)

> **Nota de instalación:** Ubuntu 22.04 con Python 3.12 no es compatible con fail2ban 0.11.2 del repositorio oficial de apt (`asynchat` removido en Python 3.12). Se instaló fail2ban 1.1.0 desde el [repositorio oficial de GitHub](https://github.com/fail2ban/fail2ban/releases/tag/1.1.0) copiando los archivos manualmente.

### SSH

- Autenticación por contraseña: **deshabilitada** (`/etc/ssh/sshd_config.d/60-cloudimg-settings.conf`)
- Solo entra con el archivo `.pem`
- Root login: prohibido

### Puertos expuestos

| Puerto | Servicio | Acceso |
|---|---|---|
| 22 | SSH | Solo con `.pem` |
| 53682 | rclone OAuth | Solo `127.0.0.1` — no accesible desde fuera |

### ⚠️ Deuda pendiente
- [ ] Revisar y auditar el firewall de instancia en la consola de AWS Lightsail (verificar que no haya puertos abiertos innecesariamente a nivel de AWS, más allá del UFW de Linux)

---

## Al reiniciar el servidor

Todo arranca automáticamente. No se requiere intervención manual.

| Servicio | Auto-start |
|---|---|
| UFW | ✅ enabled |
| fail2ban | ✅ enabled |
| cron (tarea 11pm) | ✅ enabled |

Verificar después de un reinicio:
```bash
sudo systemctl is-enabled ufw fail2ban cron
sudo ufw status
sudo fail2ban-client status sshd
crontab -l
```

---

## Actualizar el script

Cuando haya cambios en el repo:
```bash
cd ~/nutrition-garmin-data && git pull
```

El cron ya apunta al archivo local, no hace falta tocar nada más.
