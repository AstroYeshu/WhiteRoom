# STATUS — dónde estamos

**Norte:** un recordatorio creado desde Telegram suena a su hora en la Raspberry Pi.

## Fase y bloque
Fase 1 (núcleo determinista, sin LLM). Bloques 0–6 terminados; bloque 7 en curso: 7a (bandeja) y 7b (comandos) HECHOS; sigue 7c (am/pm, "el N" y aviso de recuperación).
Detalle del plan: `docs/PLAN_FASE1.md`. Decisiones: `docs/DECISIONS.md`. Ideas aparcadas: `docs/BACKLOG.md`.

## Hecho
- Bloques 0–5b: plan, dependencias, silencio, parser propio de fechas, áreas/tareas/notas, motor de recordatorios.
- Revisión de robustez (M2, M3, M6–M10, M13, migración 004) y endurecimiento del parser (reglas 12–18).
- Bloque 6 TERMINADO (8 commits, `e72ca06`..`d3061ca`): errores de Telegram traducidos (M1), scheduler de 30 s,
  botones que editan el mensaje, etiqueta "Hoy 9:00", un bucle de asyncio por módulo, `scripts/dev_remind_me.py`.
- Bloque 6 verificado a mano en Telegram real (informado por el dueño): aviso normal, +10 min, doble pulsación,
  recuperación tras caída y caída de red.
- Estado de pruebas al cerrar el bloque 6: `pytest -q` 1017 passed, 2 xfailed; `ruff check .` limpio.

- Bloque 7a TERMINADO: bandeja de mensajes libres con estado en memoria (`bot/conversation.py`, `bot/inbox.py`,
  `bot/ui.py`), preguntas del parser como botones, Deshacer/Cambiar (`tasks.convert_to_reminder`,
  `undo_reminder_conversion`, `reopen_converted`). Ver DECISIONS.md.

- Rediseño de mensajes (en pausa el 7c): corte 1 HECHO (`formato.py`, HTML con reintento en texto plano, aviso de
  recordatorio en cuadrícula, instantánea de `docs/MENSAJES.md`). Corte 2 HECHO (captura en una tarjeta: un solo mensaje que
  evoluciona; `edit_text` con botones y distribución). Corte 3 HECHO (`/pendientes` en un solo mensaje numerado, `/hoy`, `/recordatorios`
  con detenidos aparte, `/areas`, `/ayuda` agrupada; aviso breve para botones viejos). El 7c sigue en pausa.

## Pruebas del corte 3 (rediseño de mensajes)
- `tests/test_vistas.py` (nuevo, 74 pruebas): /hoy, /pendientes (un solo mensaje, números, Hecha/Descartar/Volver, reinicio, tarea cerrada),
  /recordatorios, /areas, /ayuda, extraños, escape de texto y privacidad en logs. La tabla de lo que se quitó de `test_commands.py` y quién lo
  cubre está en `docs/COBERTURA_CORTE3.md`.
- `/ayuda`: `test_ayuda_esta_agrupada_por_tipo_de_comando` compara el texto exacto (Anotar, Consultar, Áreas, Otros) y que no aparezca /papelera.
- `tests/test_formato.py` (+57 líneas): `screen`, `section`, `bullet`, `numbered`, `pending_list`, `HELP`.
- Mutaciones sobre `commands.py` (pruebas: test_vistas + test_commands + test_formato), fallos por mutación:
  | Mutación | Fallos |
  |---|---|
  | /hoy: `fire > day_end` (aviso a las 00:00 exactas cuenta como hoy) | 1 (tras añadir la prueba; antes 0) |
  | /hoy: «vencida» también para hoy | 3 |
  | /pendientes: 11 tareas en vez de 10 | 1 |
  | botón: pierde el filtro de área | 1 |
  | botón: acepta una tarea ya cerrada | 1 |
  | /hoy: bandeja también con filtro | 1 |
  | /hoy: no marca detenidos | 1 |
  | tarea cerrada: sin aviso breve | 3 |
  Esta tabla la rehice yo en una sesión nueva; la original del corte 3 nunca llegó a STATUS.md.

## Pruebas del corte 2 (rediseño de mensajes), una línea por archivo
- `tests/test_card.py` (nuevo, 29 pruebas): un solo mensaje por captura (tarea, nota, recordatorio, Cambiar, pregunta del parser, los tres
  comandos, vista previa, repetición, fecha límite, /nuevaarea), dos capturas = dos mensajes, Cancelar, Mejor como tarea, «Sin terminar»,
  botón viejo (tarjeta viva, muerta, reinicio), doble pulsación, Deshacer/Cambiar repetidos, canal sin edición, edición que falla, aviso breve.
- `tests/test_telegram_html.py` (+11): referencias de mensaje, editar con botones y distribución, «not modified» = éxito, `False` si falla,
  reintento en texto plano con botones, consola que edita.
- `tests/test_telegram_buttons.py` (+4): aviso breve en `answer`, sin aviso, manejador que falla, consola.
- `tests/test_commands.py` (12 esperados cambiados): /recordar (vista previa, sin fecha, candidato), /tarea (área, a mitad de otra),
  /nuevaarea (pregunta, omitir, cancelar, nombre ocupado) y fecha límite (pregunta, Sí, No): textos de tarjeta y vocabulario «guardado».
- `tests/test_inbox_flow.py` (9 esperados cambiados + 2 por doble pulsación): Otra fecha, mensaje nuevo a mitad, doble pulsación, texto
  sin fecha, hora dudosa, invitación a escribir, hora pasada, Mejor como tarea, botones de la pregunta anterior.
- `tests/test_hostile_flows.py`: el arnés `TgBot` simula `message_id` y ediciones (sin pruebas nuevas).
- `tests/test_main.py` (1): el dry-run muestra «¿Qué es?» en la tarjeta.
- `tests/botkit.py` y `tests/fakes.py`: arnés con referencias, ediciones con botones, `editable` y avisos breves.

## Kit de despliegue (bloque 8 adelantado; el 7c sigue en pausa)
- 2a HECHO: `deploy/asistente.service`, `.gitattributes` (`*.sh`, `*.service`, `*.sql` con LF) y `.env.example` sin comentarios al final de
  línea (systemd no los admite). Pruebas en `tests/test_deploy_files.py`. 
- 2b HECHO: `scripts/backup_db.py` (API `sqlite3.backup`, 14 días, código de salida) con `tests/test_backup_db.py` (17 pruebas); SPEC actualizado.
- 2c HECHO: `scripts/check_env.py` (Python, tzdata y zona, variables, base escribible, paquetes, `.env` sin comentarios al final, reloj) con
  `tests/test_check_env.py` (30 pruebas). Mutaciones: 15, cada una mata 1 prueba (NTP, 2). `config.REQUIRED_VARS` ahora es público.
- 2d HECHO: `/estado` (`core/runtime.py`, `RuntimeStatus` solo en memoria; el motor anota el último tick sin escribir en la base),
  `BOT_ENV` (dev|prod) en config, `.env.example`, `/ayuda`, catálogo y SPEC. `tests/test_estado.py` (49 pruebas); 20 mutaciones, todas
  matadas (la mayoría por 1-4 pruebas; el catálogo `docs/MENSAJES.md` regenerado).
- 2e HECHO: README reescrito (laptop, dev/prod con dos bots y dos bases, despliegue en la Pi, actualizar, restaurar, checklist de aceptación);
  `tests/test_readme.py` (5 pruebas) vigila que lo que menciona exista. Kit de despliegue COMPLETO; falta solo la verificación real en la Pi (checklist).

- Auditoría SPEC contra código HECHA: `docs/AUDITORIA.md` (13 discrepancias, casi todas de SPEC desactualizado; sin cambios de código).
- Preguntas abiertas para el dueño: `docs/PREGUNTAS.md`.

- BUG corregido (botones de Telegram daban `TypeError`): `handle_choice` no aceptaba `runtime` y `main._handlers` se lo pasaba (lo introduje en 2d).
  Nuevo `tests/test_telegram_real.py` (13 pruebas, `Update.de_json` + `Application` real) y el error de Telegram ahora registra tipo y 5 líneas de traza.

- Tras el bug de los botones: guarda estructural `tests/test_main_wiring.py`, CLAUDE.md a 45 líneas (detalle en `docs/FLUJO.md`), respaldo con mínimo de 7
  y nunca el último, reloj de `check_env` contra `timedatectl` y último commit, UTF-8 en los scripts, `time-sync.target` en la unidad.

- Etiquetas para la Fase 2: cada captura completada deja una fila `source='user'` en `classification_log` (`tests/test_classification_log.py`, 35 pruebas;
  17 mutaciones, todas con 2 o más fallos).

- Auditoría: las 13 discrepancias resueltas (la 7 y la 10 por decisión del dueño; SPEC actualizado). Abiertas en `docs/PREGUNTAS.md`: el `.env` real y activar o no el hook de pre-commit (`.githooks/`, sin activar: tarda ~2 min).

- `classification_log.capture_id` (migración 005): una fila por captura, ligada a la tarea de bandeja; «Cambiar» actualiza la misma fila con
  `user_corrected=1`. `scripts/eval_classifier.py` resume las etiquetas (una por captura). 16 mutaciones, todas con 2 o más fallos.

- Suite lenta diagnosticada y arreglada: pasó de ~10 s a 110-124 s porque cada `TelegramChannel(...)` crea 2 clientes httpx y cada uno carga el
  almacén de certificados (~0,4 s en Windows; ~130 construcciones = ~84 s de «setup»). `tests/conftest.py` comparte un contexto SSL
  (solo en pruebas): suite completa 118 s -> ~30-37 s, misma cobertura (1717 pruebas). Marcador `slow` (11 barridos de fecha, menos «semana-mexico»,
  y `test_hooks.py`, 46): `pytest -q -m "not slow"` ~19 s (1660 pruebas).
- Hooks en dos niveles, SIN activar: pre-commit = `ruff check .` + suite rápida; pre-push = `pytest -q`. `install_hooks.py` instala ambos
  (exige que existan los dos). 22 mutaciones sobre hooks e instalador, todas con 2 o más fallos. Pregunta 2 de `docs/PREGUNTAS.md` actualizada.
- Filas de `classification_log` anteriores a la migración 005: NO se excluyen de `eval_classifier`; cuentan una a una (`capture_id` NULL).
- Diseños aprobados (formato E de `/recordatorios` y aviso formato B) anotados en `docs/BACKLOG.md`, para tras una semana de uso.
- Estilo, commit 1 HECHO: migración 006 (`006_capitalizar_areas.py`, la primera en Python; el ejecutor de `db.py` acepta `.sql` y `.py`)
  pone en mayúscula la primera letra de las áreas sin pisar ninguna (colisión sin distinguir mayúsculas ni acentos = se deja) y sigue a
  `classification_log.pred_area/final_area`; las áreas nuevas se normalizan al crearse; `formato.cap_first` capitaliza SOLO al mostrar
  (tarjetas, avisos, listas, botones; lo guardado no cambia). `docs/ESTILO.md` nuevo. Pruebas: `tests/test_capitalizacion.py` (80) y
  `tests/test_migration_006.py` (24); `pytest -q` 1792 passed, 29 skipped, 2 xfailed, ruff limpio. La migración del 7c pasa a ser la **007**.
- Estilo, commit 2 HECHO: listas de tareas agrupadas por área (`formato.group_tasks`, función pura y reutilizable para «¿Quitas alguna?»), en
  `/pendientes` y en la sección Tareas de `/hoy`; límite 15 (antes 10); encabezado «Sin área» al final; archivadas con tareas visibles; sin
  «[área]» en cada línea. Pruebas: `tests/test_listas_agrupadas.py` (65). Mutaciones (19), todas con 2 o más fallos; `pytest -q` 1857 passed, 29 skipped, 2 xfailed; ruff limpio.

- Pruebas omitidas: las 29 se omitían solo porque `sh` no estaba en el PATH de PowerShell (todas de `tests/test_hooks.py`). `tests/shell.py::find_sh`
  lo busca junto a Git for Windows; ahora corren en PowerShell y Git Bash (0 omitidas). `tests/test_omitidas.py` falla si el número de omitidas por marca
  deja de coincidir con `docs/FLUJO.md` (valor 0) y prohíbe `pytest.skip()`. Los hooks de pre-commit y pre-push están ACTIVOS (desde la sesión
  anterior); antes decía «sin activar».

- Listas: `/pendientes` marca lo vencido («venció vie 2 oct»), el pie sugiere filtrar solo sin filtro y `/hoy` usa viñetas «-». Mutaciones (9): 2 o más fallos cada una.

- Migración 006 AUTOCONTENIDA (solo biblioteca estándar; copia congelada de `cap_first` y `fold`), probada sobre una base con datos, atómica ante una falla a mitad e idempotente. Regla para futuras migraciones en Python en DECISIONS.

## Siguiente (3 pasos)
1. Cortes 2 y 3 del rediseño de mensajes (ver arriba). El bloque 7b ya está HECHO (comandos `/hoy`, `/pendientes`,
   `/recordatorios`, `/recordar`, `/tarea` con fecha límite, `/nota`, `/areas`, `/nuevaarea`, `/ayuda`; `/papelera` queda
   para la Fase 3).
2. Bloque 7c: "Cambiar a am/pm", "el N" con candidato, aviso de recuperación (migración 007 `stop_notified_at`: la 005 es `capture_id` y la 006 capitaliza las áreas).
3. Bloque 8: README, verificación final y manual en `--dry-run`. Fase 2 (clasificación) NO empieza sin pedirlo.

## Decisiones recientes que afectan al siguiente paso
- Los botones EDITAN el mensaje (`Channel.edit_text`, `IncomingChoice.message_ref`); sin `message_ref` se manda uno nuevo.
- Detenidos = `stop_reason` no nulo, con prefijo `permanent:` / `horizon:`; la UI traduce el código a texto.
- Aviso de recuperación (bloque 7): una sola vez (clave en `settings`), con el siguiente mensaje del dueño, botón
  "Reenviar" que llama a `reminders.reactivate`.
- `ambiguous_meridiem`: dos botones; `meridiem_inferred`: botón "Cambiar a am/pm".
- Un aviso llega entre 0 y `TICK_SECONDS` s después de su hora (`.env`, por defecto 30, entre 5 y 60). La espera de
  reintentos y el umbral de «(retrasado)» (2 min) están en segundos: no cambian con el ritmo del tick.
- `apscheduler` registra solo WARNING o más; nuestros propios errores no se filtran.

## Cómo verificar el estado
- `venv\Scripts\python -m pytest -q` (si se cuelga en Windows, repetir una vez) y `venv\Scripts\python -m ruff check .`
- `git status` y `git log --oneline -n 10`
- `python -m asistente.main --dry-run` (consola, sin secretos)
- `python scripts/dev_remind_me.py 2 --urgente` (crea un aviso en TU base real; ejecútalo tú, en tu terminal)
- `python scripts/show_parse_table.py` (tabla real del parser de fechas)
