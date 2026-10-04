# Plan de la Fase 1 — Núcleo determinista (sin LLM)

Aprobado por el dueño. Marcar cada bloque al completarlo. **Corte principal de sesión: después del 5b.**

## Reglas de diseño acordadas
- Reloj inyectado (`now: Clock`) en todo lo que dependa del tiempo.
- `core/reminders.py` no importa `llm/`, `classify/`, `anthropic` ni `telegram` (test AST transitivo).
- Entrega "al menos una vez": un aviso puede duplicarse si el proceso muere entre enviar y marcar `sent`, nunca perderse.
- **Reintentos de envío**
  - Errores transitorios (red, timeout, Telegram caído): espera creciente a nivel de CANAL
    (`min(30 s · 2^(fallos−1), 5 min)`), corta-circuito al primer fallo del tick, SIN tocar `fire_at`, horizonte de
    24 h desde `first_failed_at`. Al volver el canal salen todos con "(retrasado)".
  - Errores permanentes (bot bloqueado, chat no encontrado): se detiene, se registra el tipo (nunca el texto) y se
    marca en `/recordatorios`.
  - El canal traduce sus errores a `TransientChannelError` / `PermanentChannelError` (en `channels/base.py`);
    el motor no conoce la librería de Telegram.
  - Parado = `stop_reason` no nulo (migración 004; ya no hay centinela). La espera entre intentos vive en memoria;
    el horizonte, en la base.
- **rrule**: marcar `sent` e insertar la siguiente en UNA transacción. Re-disparar una fila pospuesta o reenviada NO
  crea otra siguiente. Si un recordatorio repetido se rinde, la serie continúa.
- Hacer/descartar/posponer una tarea cancela sus recordatorios pendientes (incluidos los de preparación).
- `/pendientes` con botones Hecha / Descartar (Posponer queda para la Fase 3).
- Fecha pasada en el texto: se pregunta; nunca se crean recordatorios en el pasado.
- Bandeja: al elegir Recordatorio la tarea de bandeja no queda duplicada.
- El tick no puede solaparse consigo mismo (`asyncio.Lock` + `max_instances`/coalesce en el job).
- Migración `002`: `ALTER TABLE reminders ADD COLUMN nag_count INTEGER NOT NULL DEFAULT 0`.
- Parser de repetición (lista cerrada): "todos los días [hora]", "cada <día> [hora]", "de lunes a viernes [hora]";
  siempre se muestra la interpretación y la próxima fecha antes de guardar.
- Gracia de "(retrasado)": 2 min.

## Decisión: parser de fechas propio (sin `dateparser`)
`dateparser 1.4.3` devolvía fechas incorrectas SIN avisar en español (p. ej. "mañana 8am" → 15:30, "pasado mañana" → mañana,
"el viernes a las 5 pm" → viernes pasado, "tomar leche de la mañana" → inventa mañana). Ninguna configuración era fiable;
5 de 18 frases de prueba no las resolvía ninguna. Ver la tabla de evidencia en la conversación del 2026-10-03.

Reglas del parser (gramática cerrada; lo que no encaja entero → se pregunta, nunca se adivina):
1. La confirmación muestra siempre la fecha resuelta con día de la semana y botones [✏ Cambiar] [↩ Deshacer]
   (`format_when` aquí; los botones en el bloque 7).
2. "mañana" es el día salvo que vaya precedido de `la / esta / cada / toda` ("de la mañana", "por la mañana").
   Un periodo sin hora ("mañana por la mañana") → pregunta.
3. **Hora sin am/pm (APROBADA, 2026-10-03; sustituye al pivote 7).** Reloj fijo sáb 2026-10-03 15:30, "mañana" = domingo 4:
   | Texto | Resultado | `meridiem_inferred` |
   |---|---|---|
   | con am/pm, "de la mañana/tarde/noche/madrugada" o 24 h (13–23, 0, `08:30`) | se respeta | no |
   | mañana a las 12 | 12:00 pm (mediodía) | no |
   | mañana a las 12 am / 12 de la noche | PREGUNTA (`ambiguous_time`): ¿medianoche de hoy o de mañana? | — |
   | mañana a las 1 / 2 / 3 / 4 (y `H:MM` suelto, p. ej. `3:30`) | 1:00 pm … 4:00 pm | **sí** |
   | mañana a las 5 … 11 (y `H:MM` suelto, p. ej. `6:30`) | PREGUNTA (`ambiguous_meridiem`) con las dos lecturas ya resueltas, p. ej. 9:00 am / 9:00 pm | — |
   - El rango que se pregunta es `meridiem_ask_range` (por defecto `5-11`): el parser lo recibe como parámetro y vive en
     `settings` (migración 003, ya aplicada; `core/settings.get_meridiem_ask_range`). Por debajo del rango se asume tarde,
     por encima mañana. Debe cumplir 1 ≤ bajo ≤ alto ≤ 11.
   - Las opciones de `ambiguous_meridiem` solo incluyen lecturas FUTURAS (hoy a las 15:30, "a las 8" ofrece solo 8 pm);
     si ninguna es futura, se pregunta por el pasado (`past`) con la alternativa de mañana.
   - Combinada con "el sábado" siendo sábado: primero se pregunta el día (`same_weekday`) y la hora después.
   - `H:MM` suelto (sin "a las"/am/pm) solo cuenta si el texto trae también un día ("Juan 3:16" no es hora).
   - "a las 8 y media / y cuarto" se entienden; "menos cuarto", "medianoche" → pregunta.
   - El texto ya está en la bandeja cuando se pregunta, así que no se pierde nada.
   - **Para el bloque 7:** mostrar `ambiguous_meridiem` como dos botones (las dos opciones) y, cuando `meridiem_inferred`,
     el botón "Cambiar a am/pm" en la confirmación.
4. Día de la semana igual al de hoy ("el viernes" siendo viernes) → pregunta (hoy / en 7 días).
   "próximo viernes" siendo viernes → +7; "este viernes" siendo viernes → hoy.
5. Fecha/hora ya pasada → pregunta (con la alternativa futura más natural); jamás se crea en el pasado.
6. Día/mes sin año = siguiente ocurrencia (hoy cuenta). "29 de febrero" → siguiente año bisiesto. Fecha inexistente
   ("31 de abril") → pregunta. `d/m` suelto solo con "el" delante (evita "1/2 kilo"); con año se acepta sin "el".
7. Dos fechas, dos horas, hora dudosa o con restos sin entender ("8:30 menos cuarto") → pregunta.
8. Sin hora → `default_morning_time` (`has_time=False`, para avisar "hora por defecto").
9. "en N minutos/horas" (instante exacto), "en N días/semanas" (día a `default_morning_time`). "estudiar 2 horas" no es fecha.
10. **"Domingo" como nombre propio (CORREGIDO 2026-10-03).** La heurística aplica SOLO a "Domingo": los otros seis
    días con mayúscula (el Viernes, Martes a las 5...) siguen siendo fecha. "Domingo" es nombre si va con mayúscula
    a mitad de frase y SIN `el / este / esta / próximo / que viene` ("llamar a Domingo", "salir con Domingo",
    "regalo para Domingo"). Con determinante es fecha con cualquier capitalización ("el Domingo", "este DOMINGO",
    "Domingo que viene"). Al inicio del texto es fecha. Si todo el texto está en mayúsculas, la capitalización no
    informa y también es fecha. Si se descarta un "Domingo" como nombre y queda una hora ("llamar a Domingo a las 5"),
    se PREGUNTA (`name_or_day`); nunca se asume "hoy". Si hay otro día ("llamar a Domingo mañana a las 5 pm"), manda ese día.
11. **Título**: se quita el verbo inicial `recordar / recordarme / recuérdame` (y un `que`/`de` que lo siga) solo si hay
    fecha y queda algo más: "recordar mañana 8am llevar tarea de cálculo" → "llevar tarea de cálculo". Sin fecha el título
    no se toca ("recordar mi contraseña").
Pruebas: tablas con reloj fijo (sáb 2026-10-03 15:30, México): frases con falsos positivos, horas 1–12 con y sin
marcador y `H:MM` suelto, y la matriz 7 días × 3 capitalizaciones × 5 contextos para "Domingo".

Recurrencia (`parsing/recurrence.py`, lista cerrada): "todos los días [hora]", "cada <día> [hora]", "de lunes a viernes [hora]".
Devuelve `rrule` + primera ocurrencia futura; el handler muestra interpretación y próxima fecha antes de guardar.
`next_occurrence(rrule, scheduled, after, tz)` calcula desde la hora programada (la usa también el motor, sin deriva, DST-seguro).

## Plan de pruebas del motor (FakeClock + FakeChannel + SQLite en memoria)
1. Único: a T−1 s no sale; a T sale una vez (`kind="reminder"`, 4 botones); `sent` + `last_fired_at`; no se repite.
2. +10 min / +1 h / Mañana (`default_morning_time` local): `pending`, `snooze_count+1`, sale a su hora.
3. Semanal sin deriva: disparo tardío, la siguiente cae en la hora exacta; 10 repeticiones sin desfase; cruce de horario de verano.
4. Silencio: se retiene y sale a `quiet_end` con "(retrasado)" en orden; `priority=2` pasa; bordes 22:00/07:00.
5. Recuperación tras caída: vencidos de 1 h, 1 día y 3 días salen todos "(retrasado)" en orden; semanal vencido 3 semanas envía uno.
6. **Canal caído 10 min**: transitorio → reintentos con espera creciente sin tocar `fire_at`; al volver salen todos
   con "(retrasado)", ninguno se pierde. Permanente → se detiene, queda marcado, los demás siguen. Rendición a las 24 h.
7. Insistencia `priority=2`: +15 min, +30 min, 3 veces máx., ✅ la detiene (`nag_count`).
8. Preparación: 1 día / 1 h antes solo si no han pasado.
9. AST: sin imports de `llm`/`classify`/`anthropic`/`telegram` (transitivo) + test del detector.
10. rrule + snooze: sin duplicados ni deriva; re-disparo de fila pospuesta no crea otra; rendirse no corta la serie; atomicidad.
11. Cancelación en cascada al hacer/descartar/posponer tarea.
12. Fecha pasada → pregunta, nunca crea recordatorio.
13. Tick sin solapamiento.
14. `is_quiet_hour`: normal, cruce de medianoche, bordes, `start==end`, zonas.

## Estado (2026-10-03): bloques 0 a 5b HECHOS — `pytest -q`: 526 passed; `ruff check .`: limpio
Además: regla 3 nueva (migración 003 con `meridiem_ask_range`), corrección de "Domingo" y verbo inicial del título.
Pendientes: 6, 7 y 8.
Revisión de robustez (commits M1-M10, antes del bloque 6): hechos M2, migración 004, M3/M6/M13 y códigos de detención;
el resto (M7, M8, M9, M10, M5) se marca abajo al completarse.

## Decisiones de implementación (a revisar)
2. **Estado "detenido" = `stop_reason` no nulo** (migración 004; sustituye al centinela `attempts = 1000`).
   `Reminder.stopped` lo expone; el recordatorio sigue `pending` y `/recordatorios` lo marcará. Cubre error permanente
   y agotar las 24 h. `stop_reason` es un CÓDIGO estable (`permanent:bot_blocked`, `horizon:telegram_down`, `legacy`);
   el texto para el usuario lo pone la UI en el bloque 7. `stopped_at` no nulo = "ya se generó la siguiente de la serie"
   (se crea en la misma transacción que la parada) y se conserva al reactivar (`reactivate`, función del motor sin UI
   aún), así reactivar no crea otra siguiente (M13).
3. **Reintentos (M3/M6)**: la espera es del CANAL: `min(30 s · 2^(fallos−1), 300 s)` → 30, 60, 120, 240, 300, 300…
   **Tope máximo: 5 min**; al primer fallo pasajero del tick no se intentan los demás. El **horizonte de 24 h** cuenta
   desde `reminders.first_failed_at` (en la base): reiniciar el proceso no lo reinicia; se borra al enviar bien o al
   posponer. Los que esperaban turno lo empiezan cuando el canal falla; los futuros y los de prioridad 1 retenidos por
   el silencio (no se intentaron enviar) no lo gastan. Lo único en memoria es la espera del canal: al reiniciar se
   reintenta de inmediato. `attempts` cuenta los fallos seguidos de esa fila (informativo).
4. **Bandeja → recordatorio/nota**: el recordatorio se crea con `task_id = NULL` y la tarea de bandeja se cierra con
   `tasks.close_as_converted`: `status='dropped'` + `closed_reason='converted_to_reminder'|'converted_to_note'` (no
   `done`: falsearía los conteos de hechas). `/papelera` y los reportes filtran `closed_reason='discarded'`, así las
   conversiones no aparecen como descartadas. La cascada no cancela el recordatorio (no lleva `task_id`).
5. **Mayúsculas en días de la semana** (regla 10 del parser): "llamar a Domingo" se toma como nombre propio. Ver el DEFECTO CONOCIDO de la regla 10: hoy también descarta "el Domingo" / "este Domingo" / "para el Domingo".
6. **Entrega "al menos una vez"**: si el proceso muere entre enviar y marcar `sent`, un aviso puede repetirse al reiniciar;
   nunca se pierde. Si falla registrar el envío (p. ej. el cálculo de la siguiente ocurrencia), se revierte todo y el
   siguiente tick lo reintenta entero (una sola transacción).
7. **Insistencia**: primer aviso + hasta 3 reenvíos cada 15 min (`nag_count`); atraviesa el silencio; los reenvíos no
   llevan "(retrasado)". Una serie genera su siguiente SOLO en el primer disparo de la fila (`last_fired_at` vacío):
   posponer o reenviar no crea otra. Los avisos de preparación llevan `task_id`; los recordatorios sueltos no, por eso
   `set_due` solo rehace los de preparación.

## Bloques (un commit por bloque)
- [x] 0. Plan y SPEC (secciones 7 y 8.3) — `Fase 1: plan y actualización del SPEC`
- [x] 1. Dependencias: `python-telegram-bot[job-queue]==22.8`, `python-dateutil` (`dateparser` se añadió y luego se retiró en el bloque 3) — `Fase 1: dependencias`
- [x] 2. `is_quiet_hour` / `next_quiet_end` + pruebas — `Fase 1: horas de silencio`
- [x] 3. `parsing/dates.py` y `parsing/recurrence.py` propios (sin dateparser) + pruebas en tabla (≥60 frases) — `Fase 1: parseo de fechas propio`
- [x] 4. Migración 002, `core/areas`, `tasks`, `notes` + pruebas — `Fase 1: áreas, tareas y notas`
- [x] 5a. Motor base: único, snooze, silencio, reintentos, AST, sin solapamiento — `Fase 1: motor de recordatorios (base)`
- [x] 5b. Motor: rrule, recuperación, insistencia, preparación, cascada — `Fase 1: motor (rrule, recuperación, insistencia)`
- **— CORTE PRINCIPAL —**
- [ ] 6. Scheduler (`on_tick`, tick al arrancar) y botones de recordatorio — `Fase 1: scheduler y botones de recordatorio`
  **Empieza por M1** (traducción de errores en `channels/telegram.py`): `Forbidden` o texto demasiado largo →
  `PermanentChannelError`; `RetryAfter` → `TransientChannelError` con la espera indicada por Telegram.
- [ ] 7. Bandeja, comandos, `/hoy`, `/pendientes` con Hecha/Descartar; botones de `ambiguous_meridiem` (dos opciones)
  y "Cambiar a am/pm" cuando `meridiem_inferred` — `Fase 1: bandeja y comandos`
- [ ] 8. README, verificación final y manual en `--dry-run` — `Fase 1: documentación y verificación`

## Deuda conocida (no se arregla en la Fase 1)
- **M4 — deriva permanente por horario de verano (media; baja en zonas sin él).** Una serie diaria a las 02:30 en una
  zona con horario de verano pasa a las 03:30 el día del adelanto y se queda ahí, porque el ancla de `_spawn_next` es el
  `fire_at` de la fila anterior, ya corrido. Prueba futura: `FREQ=DAILY` a las 02:30 en `America/New_York` del 6 al 10 de
  marzo; el 9 y el 10 deben salir a las 02:30 locales. Arreglar antes de ofrecerlo en zonas con horario de verano.
- **M11 (baja).** 🌅 Mañana en una serie diaria de las 8:00 hace que mañana suenen dos avisos: el de la serie y el
  pospuesto a las 9:00.
- **M12 (baja).** +10 min pulsado a las 21:55 sale a las 07:00 con "(retrasado)"; defendible, pero no se avisa.
- **M14 (baja).** Si Telegram aceptó el mensaje pero la respuesta no llegó a tiempo, se reintenta y llega dos veces;
  coherente con "al menos una vez".
- **M15 (baja).** Las comparaciones de horas son de texto: exigen que toda hora se escriba con `to_utc_iso`; una fila con
  `Z` o microsegundos se ordenaría mal. Defensa futura posible: `CHECK (fire_at_utc LIKE '____-__-__T__:__:__+00:00')` en
  una migración.
