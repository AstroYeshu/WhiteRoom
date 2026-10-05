# Asistente personal por Telegram (Raspberry Pi 4)

Bot de Telegram de UN solo usuario: recordatorios, tareas, notas, libro de cuentas y resumen diario.
El diseño completo está en `SPEC.md`. Implementa SOLO la fase que se te pida, nada más.
Comandos, pruebas y ritmo de trabajo en detalle: `docs/FLUJO.md`.

## Comandos
- Probar sin Telegram ni APIs: `python -m asistente.main --dry-run` (úsalo siempre; las claves reales las usa solo el dueño).
- Tests: `pytest -q`. Lint y formato: `ruff check .` y `ruff format .`.

## Reglas duras (no negociables)
- Dinero: SIEMPRE enteros en centavos (`amount_cents`). Nunca `float`.
- Tiempo: guardar todo en UTC (ISO-8601). Convertir a la zona del usuario solo al mostrar (`zoneinfo`).
- Jev y Claude NUNCA calculan ni ven saldos. El saldo lo calcula SQL.
- Nada se borra: soft delete (`status` / `voided`). Migraciones solo hacia adelante.
- Solo se atiende a `ALLOWED_USER_ID`; a cualquier otro, silencio total.
- Secretos solo desde `.env` (ignorado por git). Nunca en código, commits ni logs. No leas el `.env` real.
- NO usar `ANTHROPIC_API_KEY`: la clave del bot es `ASSISTANT_ANTHROPIC_KEY` y se pasa explícitamente al
  cliente (`Anthropic(api_key=...)`); si no, Claude Code cobra por API en vez de la suscripción.
- Toda llamada externa (Telegram, Anthropic, TypeSafe) lleva timeout y fallback. Anotar algo NUNCA puede
  fallar por culpa de un servicio externo. Los recordatorios funcionan sin LLM.
- No registrar el texto de los mensajes del usuario a nivel INFO (privacidad); registrar IDs.
- Nunca termines procesos por nombre (`taskkill /IM`, `pkill`); solo el PID que lanzaste tú.

## Convenciones
- Python 3.11+, type hints, `pathlib`. Sin rutas ni comandos específicos de un SO (desarrollo en Windows,
  producción en Linux ARM64).
- Identificadores en inglés; comentarios, docstrings y mensajes al usuario en español, sin emojis ni
  pictogramas (lo vigila `tests/test_no_pictograms.py`).
- Lógica de negocio en `core/`; conversación en `bot/`; la plataforma solo en `channels/`, detrás de la
  interfaz `Channel` (SPEC 3.1). Solo `channels/telegram.py` importa la librería de Telegram.
  Una función, una responsabilidad.
- Antes de añadir una dependencia, pregunta.
- Tests con pytest para toda lógica de dinero, fechas, recordatorios y decisiones de clasificación.
- Todo cambio en canales o callbacks se prueba también con objetos reales de la librería
  (`Update.de_json`), no solo con falsos.

## Flujo de trabajo (resumen)
- Al empezar: lee `docs/STATUS.md` y `git log -n 10`. Plan primero: propón el plan y espera aprobación.
- La prueba se escribe y se ve fallar antes del código. Cada mutación crítica falla con al menos 2 pruebas.
- Antes de cada commit, `pytest -q` y `ruff check .` con código 0, sin pipes (hook opcional: `scripts/install_hooks.py`).
  Commits pequeños; sin push.
- Alcance: solo lo pedido; lo demás a `docs/BACKLOG.md`. Al terminar un bloque, actualiza
  `docs/STATUS.md` y `docs/DECISIONS.md`.
- Al parar: "RESUMEN PARA REVISIÓN" de máx. 20 líneas. Explica el código nuevo en lenguaje simple.
- Si algo del SPEC es ambiguo o no está verificado, no adivines: consulta la documentación o pregunta.
