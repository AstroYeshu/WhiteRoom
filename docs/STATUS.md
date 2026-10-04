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

## Siguiente (3 pasos)
1. Cortes 2 y 3 del rediseño de mensajes (ver arriba). El bloque 7b ya está HECHO (comandos `/hoy`, `/pendientes`,
   `/recordatorios`, `/recordar`, `/tarea` con fecha límite, `/nota`, `/areas`, `/nuevaarea`, `/ayuda`; `/papelera` queda
   para la Fase 3).
2. Bloque 7c: "Cambiar a am/pm", "el N" con candidato, aviso de recuperación (migración 005 `stop_notified_at`).
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
