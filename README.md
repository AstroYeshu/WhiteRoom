# Asistente personal por Telegram

Bot de Telegram de un solo usuario (recordatorios, tareas, notas, cuentas y resumen diario),
pensado para una Raspberry Pi 4. El diseño completo está en `SPEC.md`; las reglas de trabajo,
en `CLAUDE.md`; el estado del proyecto, en `docs/STATUS.md`.

**Estado:** Fase 1 (núcleo determinista, sin IA): bandeja de mensajes libres, tareas, notas,
áreas, recordatorios (con repetición y avisos de preparación) y los comandos `/hoy`, `/pendientes`,
`/recordatorios`, `/recordar`, `/tarea`, `/nota`, `/areas`, `/nuevaarea`, `/estado` y `/ayuda`.

## Instalación en la laptop (desarrollo)

Necesitas Python 3.11 o más reciente y git.

```
git clone <URL-del-repositorio> WhiteRoom
cd WhiteRoom
python -m venv venv
venv\Scripts\activate          # Windows  (en Linux o macOS: source venv/bin/activate)
pip install -r requirements-dev.txt
```

Probar sin Telegram ni claves (consola; no usa red, no lee `.env`, guarda en `data/dry_run.db`):

```
python -m asistente.main --dry-run
```

Escribe mensajes y mira las respuestas; `/salir` termina.

Pruebas y estilo:

```
pytest -q                 # suite completa (~35 s)
pytest -q -m "not slow"   # suite rápida (~20 s): sin barridos largos ni pruebas de hooks
ruff check .
ruff format .
```

Las pruebas lentas llevan el marcador `slow` (registrado en `pyproject.toml`).

## Hooks de git en dos niveles (opcionales)

El repositorio trae dos hooks (`.githooks/`; usan `venv/Scripts/python` en Windows o `venv/bin/python` en Linux):

- **pre-commit** (rápido): `ruff check .` y `pytest -q -m "not slow"`. Bloquea el commit si alguno falla.
- **pre-push** (completo): `pytest -q`, la suite entera. Bloquea el push si falla.

Para activarlos, una vez por clon:

```
python scripts/install_hooks.py
```

Solo cambia la configuración local de este repositorio (`git config core.hooksPath .githooks`). Para desactivarlos:
`git config --unset core.hooksPath`.

## Desarrollo y producción: dos bots, dos bases

Nunca uses el mismo bot ni la misma base en la laptop y en la Raspberry Pi. Si lo haces, los dos
procesos se pelean por los mismos mensajes y los datos de prueba se mezclan con los reales.

| | Desarrollo (laptop) | Producción (Raspberry Pi) |
|---|---|---|
| Bot de Telegram | uno de pruebas (créalo con @BotFather) | el bot de verdad (otro token, otro @BotFather) |
| `TELEGRAM_BOT_TOKEN` | el token del bot de pruebas | el token del bot real |
| `ALLOWED_USER_ID` | tu ID numérico | el mismo (eres tú) |
| `BOT_ENV` | `dev` | `prod` |
| `DB_PATH` | `data/asistente.db` (en la laptop) | `data/asistente.db` (en la Pi) |
| `.env` | el de la laptop | otro, creado a mano en la Pi |

Cada máquina tiene su propio `.env` (nunca se sube a git) y su propia carpeta `data/`. `BOT_ENV`
solo se muestra en `/estado` para que sepas con qué bot hablas; no cambia el comportamiento.

Para ejecutar con Telegram en la laptop:

1. Copia `.env.example` a `.env` y completa `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_ID`, `TZ_NAME`
   (p. ej. `America/Mexico_City`), `CURRENCY_CODE` y `BOT_ENV=dev`. Pon los comentarios en su
   propia línea, no al final de una línea de valor.
2. `python scripts/check_env.py` (debe decir OK en todo, o AVISO).
3. `python -m asistente.main`

## Despliegue en Raspberry Pi

Probado en el diseño para Raspberry Pi OS de 64 bits (Bookworm, que trae Python 3.11). Los
comandos asumen el usuario `pi` y el proyecto en `/home/pi/WhiteRoom`; cámbialos si los tuyos son
otros.

### 1. Hora y zona horaria

Los recordatorios dependen de que la hora del sistema sea correcta.

```
timedatectl set-ntp true
sudo timedatectl set-timezone America/Mexico_City
timedatectl                      # "System clock synchronized: yes" y la zona correcta
```

### 2. Código y entorno virtual

```
sudo apt update && sudo apt install -y git python3-venv
cd /home/pi
git clone <URL-del-repositorio> WhiteRoom
cd WhiteRoom
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 3. Configuración

```
cp .env.example .env
nano .env                        # token del bot REAL, ALLOWED_USER_ID, TZ_NAME, CURRENCY_CODE, BOT_ENV=prod
chmod 600 .env
venv/bin/python scripts/check_env.py
```

`check_env.py` imprime una línea por punto (OK, AVISO o FALLA) y nunca muestra los valores de
tus variables. No sigas si hay algún FALLA.

### 4. Servicio (systemd)

Copia la unidad y cambia `<USUARIO>` y `<RUTA_PROYECTO>` por tus valores (p. ej. `pi` y
`/home/pi/WhiteRoom`):

```
sudo cp deploy/asistente.service /etc/systemd/system/asistente.service
sudo nano /etc/systemd/system/asistente.service
sudo systemctl daemon-reload
sudo systemctl enable --now asistente
systemctl status asistente
journalctl -u asistente -f       # logs en vivo (Ctrl+C para salir)
```

En el chat con el bot escribe `/estado`: debe decir `Entorno: prod`, un ciclo reciente y el
esquema de la base.

### 5. Respaldo diario

```
crontab -e
```

Añade la línea (todos los días a las 3:15 am; borra los de 14 días o más, pero siempre quedan los 7 más recientes, en `data/backups/`):

```
15 3 * * * cd /home/pi/WhiteRoom && venv/bin/python scripts/backup_db.py >> data/backup.log 2>&1
```

Prueba una vez a mano: `venv/bin/python scripts/backup_db.py` debe imprimir "Respaldo listo" y
terminar con código 0 (`echo $?`). Copia de vez en cuando `data/backups/` fuera de la tarjeta SD.

## Cómo actualizar

```
cd /home/pi/WhiteRoom
git pull
venv/bin/pip install -r requirements.txt
venv/bin/python scripts/check_env.py
sudo systemctl restart asistente
journalctl -u asistente -n 50 --no-pager
```

Las migraciones de la base se aplican solas al arrancar (solo hacia adelante).

## Cómo restaurar un respaldo

Los respaldos son archivos `data/backups/asistente-AAAA-MM-DD.db`. Restaurar reemplaza la base
actual: lo que se anotó después de la fecha del respaldo se pierde de esa base (queda guardado
en `data/descartado/`, por si acaso).

```
sudo systemctl stop asistente
cd /home/pi/WhiteRoom
mkdir -p data/descartado
mv data/asistente.db* data/descartado/        # base, y sus archivos -wal y -shm si existen
cp data/backups/asistente-2026-10-04.db data/asistente.db     # elige la fecha
sudo systemctl start asistente
```

Mover también los archivos `-wal` y `-shm` es importante: un `-wal` viejo junto a una base
restaurada la dañaría. Después escribe `/estado` y revisa `/recordatorios`.

## Checklist de aceptación en la Pi

Marca cada punto en la Pi real, con el servicio activo.

- [ ] `check_env.py` sin ningún FALLA y `systemctl status asistente` en `active (running)`.
- [ ] `/estado` responde `Entorno: prod` y un `Último ciclo` de hace menos de 1 minuto.
- [ ] **Recordatorio normal:** `/recordar en 2 minutos probar` llega a su hora (hasta 30 s tarde, que es el tick).
- [ ] **Reinicio de la Pi:** crea un recordatorio para dentro de 5 minutos, ejecuta `sudo reboot`; al volver, sin tocar nada,
  el servicio está activo y el recordatorio llega (con "(retrasado)" si ya pasó su hora).
- [ ] **Corte de red:** con un recordatorio pendiente, desconecta el cable o el Wi-Fi hasta pasada su hora; el bot no se cae
  (`systemctl status`), y al volver la red el aviso llega en pocos minutos y una sola vez.
- [ ] **Corte de luz:** con un recordatorio pendiente, desconecta la corriente (con la Pi encendida) y vuelve a conectarla;
  el servicio arranca solo y el recordatorio llega; revisa `/recordatorios` y `/estado` (esquema y tamaño de la base normales).
- [ ] **Extraños:** otra cuenta de Telegram escribe al bot y no recibe ninguna respuesta.
- [ ] **Respaldo:** `venv/bin/python scripts/backup_db.py` termina con código 0 y deja un archivo en `data/backups/`.
- [ ] `journalctl -u asistente` no muestra el texto de tus mensajes ni el token del bot.
