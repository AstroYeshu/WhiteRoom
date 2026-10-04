# Plan de la Fase 1 — Núcleo determinista (sin LLM)

Aprobado por el dueño. Marcar cada bloque al completarlo. **Corte principal de sesión: después del 5b.**

## Reglas de diseño acordadas
- Reloj inyectado (`now: Clock`) en todo lo que dependa del tiempo.
- `core/reminders.py` no importa `llm/`, `classify/`, `anthropic` ni `telegram` (test AST transitivo).
- Entrega "al menos una vez": un aviso puede duplicarse si el proceso muere entre enviar y marcar `sent`, nunca perderse.
- **Reintentos de envío**
  - Errores transitorios (red, timeout, Telegram caído): reintento con espera creciente calculada desde `attempts`
    (`min(30 s · 2^attempts, 15 min)`), SIN tocar `fire_at`, sin rendirse durante 24 h. Al volver el canal salen
    todos con "(retrasado)".
  - Errores permanentes (bot bloqueado, chat no encontrado): se detiene, se registra el tipo (nunca el texto) y se
    marca en `/recordatorios`.
  - El canal traduce sus errores a `TransientChannelError` / `PermanentChannelError` (en `channels/base.py`);
    el motor no conoce la librería de Telegram.
  - Parado = `attempts >= STOPPED_ATTEMPTS` (centinela; evita otra migración). La espera entre intentos vive en memoria.
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

## Decisiones de implementación (a revisar)
2. **Estado "detenido" = `attempts = 1000`** (`STOPPED_ATTEMPTS`), un valor centinela, para no añadir otra migración.
   `Reminder.stopped` lo expone; el recordatorio sigue `pending` y `/recordatorios` lo marcará. Cubre error permanente
   y agotar las 24 h. Si es de una serie, la siguiente ocurrencia se crea igual.
3. **Reintentos**: espera `min(30 s · 2^(n−1), 900 s)` → 30, 60, 120, 240, 480, 900, 900… **Tope máximo: 15 min**.
   Se rinde tras 100 intentos fallidos seguidos (≈ 25 h de espera acumulada). La espera cuenta intentos, no horas de
   reloj: el silencio nocturno (que salta ticks de prioridad 1) puede alargar algo ese plazo; se prefiere eso a rendirse antes.
   La espera entre intentos vive en memoria: al reiniciar el proceso se reintenta de inmediato.
4. **Bandeja → recordatorio**: el recordatorio se crea con `task_id = NULL` y la tarea de bandeja pasa a `dropped`
   (así no se duplica y la cascada no lo cancela). En la Fase 3, `/papelera` mostrará esas tareas descartadas por
   conversión; habrá que decidir cómo distinguirlas (no hay columna para marcarlas).
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
- [ ] 7. Bandeja, comandos, `/hoy`, `/pendientes` con Hecha/Descartar; botones de `ambiguous_meridiem` (dos opciones)
  y "Cambiar a am/pm" cuando `meridiem_inferred` — `Fase 1: bandeja y comandos`
- [ ] 8. README, verificación final y manual en `--dry-run` — `Fase 1: documentación y verificación`
