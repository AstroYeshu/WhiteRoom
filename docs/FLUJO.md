# Flujo de trabajo (detalle)

`CLAUDE.md` guarda las reglas; aquí está el cómo.

## Comandos
- Entorno: `python -m venv venv` y `pip install -r requirements-dev.txt` (en Linux, `requirements.txt`).
- Ejecutar sin Telegram ni APIs (consola, sin secretos): `python -m asistente.main --dry-run`. Úsalo siempre para probar; las claves
  reales las usa solo el dueño, en su propia terminal.
- Ejecutar con Telegram: `python -m asistente.main`. Verificar el entorno: `python scripts/check_env.py`.
- Tests: `pytest -q`. Lint y formato: `ruff check .` y `ruff format .`.

## Pruebas
- Prueba antes del código: se escribe y se ve fallar. Si no se pudo, se dice y se hace una mutación después.
- Mutaciones: reintroduce el error a propósito; cada mutación crítica debe hacer fallar al menos 2 pruebas.
- Antes de cada commit, `pytest -q` y `ruff check .` con código 0, sin cortar su salida con un pipe. Si pytest se cuelga, usa
  `faulthandler_timeout` y busca la causa. Nunca termines procesos por nombre (`taskkill /IM`, `pkill`): solo el PID que lanzaste.
- Canales y callbacks: además de los falsos, objetos reales de la librería (`Update.de_json`), ver `tests/test_telegram_real.py`.
  El cableado de `main._handlers` lo vigila `tests/test_main_wiring.py`.
- Inyecta el reloj (`now()`) para probar el tiempo.

## Ritmo
- Al empezar: lee `docs/STATUS.md` y `git log -n 10` antes de planificar. Plan primero: propón el plan y espera aprobación.
- Alcance: solo lo pedido; lo demás va a `docs/BACKLOG.md`. Preguntas al dueño: `docs/PREGUNTAS.md`.
- Commits pequeños y descriptivos; antes de cada uno, revisa `git diff --stat`. Sin `git push` salvo que se pida.
- Al terminar cada bloque: actualiza `docs/STATUS.md` y `docs/DECISIONS.md`; muestra la salida real de `pytest -q` y `ruff check .`.
- Al terminar cada tarea, explica en lenguaje simple qué hace el código nuevo y por qué (el dueño está aprendiendo).
- Al parar: "RESUMEN PARA REVISIÓN" de máx. 20 líneas (commits, pruebas, decisiones que requieren visto bueno, dudas abiertas y lo
  que NO se hizo).
- Si algo del SPEC es ambiguo o no está verificado (p. ej. la API de Jev), no adivines: consulta la documentación oficial o pregunta.
