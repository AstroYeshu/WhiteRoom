# Asistente personal por Telegram

Bot de Telegram de un solo usuario (recordatorios, tareas, notas, cuentas y resumen diario),
pensado para una Raspberry Pi 4. El diseño completo está en `SPEC.md`; las reglas de trabajo,
en `CLAUDE.md`.

**Estado:** Fase 0 (esqueleto). Solo responde a `/start` y `/ayuda`.

## Instalación

```
python -m venv venv
venv/Scripts/activate        # Windows  (en Linux: source venv/bin/activate)
pip install -r requirements-dev.txt
```

## Probar sin Telegram ni claves

```
python -m asistente.main --dry-run
```

Abre una consola donde escribes mensajes y ves las respuestas. No usa red, no lee `.env`
y guarda sus datos en `data/dry_run.db`. Escribe `/salir` para terminar.

## Ejecutar con Telegram

1. Copia `.env.example` a `.env` y completa `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_ID`,
   `TZ_NAME` y `CURRENCY_CODE`. El `.env` nunca se sube a git.
2. `python -m asistente.main`

## Pruebas y estilo

```
pytest -q
ruff check .
ruff format .
```
