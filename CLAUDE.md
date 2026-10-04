# Asistente personal por Telegram (Raspberry Pi 4)

Bot de Telegram de UN solo usuario: recordatorios, tareas, notas, libro de cuentas y resumen diario.
El diseño completo está en `SPEC.md`. Implementa SOLO la fase que se te pida, nada más.

## Comandos
- Entorno: `python -m venv venv` y `pip install -r requirements.txt`
- Ejecutar: `python -m asistente.main`
- Ejecutar sin Telegram ni APIs (consola, sin secretos): `python -m asistente.main --dry-run`
  (úsalo siempre para probar; las claves reales las usa solo el dueño, en su propia terminal)
- Tests: `pytest -q`
- Lint y formato: `ruff check .` y `ruff format .`

## Reglas duras (no negociables)
- Dinero: SIEMPRE enteros en centavos (`amount_cents`). Nunca `float`.
- Tiempo: guardar todo en UTC (ISO-8601). Convertir a la zona del usuario solo al mostrar (`zoneinfo`).
- Jev y Claude NUNCA calculan ni ven saldos. El saldo lo calcula SQL.
- Nada se borra: soft delete (`status` / `voided`). Migraciones solo hacia adelante.
- Solo se atiende a `ALLOWED_USER_ID`; a cualquier otro, silencio total.
- Secretos solo desde `.env` (ignorado por git). Nunca en código, commits ni logs.
- NO usar el nombre `ANTHROPIC_API_KEY`: la clave del bot es `ASSISTANT_ANTHROPIC_KEY` y se pasa
  explícitamente al cliente (`Anthropic(api_key=...)`). Si no, Claude Code cobra por API en vez de la suscripción.
- Toda llamada externa (Telegram, Anthropic, TypeSafe) lleva timeout y fallback. Anotar algo
  NUNCA puede fallar por culpa de un servicio externo.
- Los recordatorios funcionan sin LLM.
- No registrar el texto de los mensajes del usuario a nivel INFO (privacidad); registrar IDs.

## Convenciones
- Python 3.11+, type hints, `pathlib`. Sin rutas ni comandos específicos de un SO
  (desarrollo en Windows, producción en Linux ARM64).
- Identificadores en inglés; comentarios, docstrings y mensajes al usuario en español.
- Lógica de negocio en `core/`; conversación en `bot/`; la plataforma (consola, Telegram, un posible
  WhatsApp futuro) solo en `channels/`, detrás de la interfaz `Channel` (SPEC 3.1).
  Solo `channels/telegram.py` importa la librería de Telegram. Una función, una responsabilidad.
- Antes de añadir una dependencia, pregunta.
- Tests con pytest para toda lógica de dinero, fechas, recordatorios y decisiones de clasificación.
  Inyecta el reloj (`now()`) para poder probar el tiempo.

## Flujo de trabajo
- Plan primero: propón el plan y espera aprobación antes de escribir código.
- Tras cada bloque de cambios corre `pytest -q` y `ruff check .` y muestra la salida real.
- Commits pequeños y descriptivos cuando un bloque esté verificado.
- Al terminar cada tarea, explica en lenguaje simple qué hace el código nuevo y por qué
  (el dueño está aprendiendo; no asumas que conoce el patrón).
- Si algo del SPEC es ambiguo o no está verificado (p. ej. la API de Jev), no adivines:
  consulta la documentación oficial o pregunta.
