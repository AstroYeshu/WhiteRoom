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
1. La confirmación muestra siempre la fecha resuelta con día de la semana y botones [Cambiar] [Deshacer]
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
   - Horas en palabras y minutos hablados (regla 12): "a las 8 y media / y cuarto / y 15 / y cinco",
     "menos cuarto / menos 10", "la una", "las dos…las doce", "mediodía / medio día". "12 am" y "medianoche"
     preguntan (`ambiguous_time`) con las dos medianoches futuras como candidatos.
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
10. **"Domingo" como nombre propio (REVISADA 2026-10-03, regla 5 del segundo encargo).** Solo aplica a "domingo": los
    otros seis días nunca son nombres. Sin determinante (`el / este / esta / próximo / que viene / para el`) se PREGUNTA
    (`name_or_day`) SOLO si: (a) va precedido de "a" o "con", con cualquier capitalización ("llamar a domingo",
    "cenar con Domingo"); (b) tiene mayúscula inicial a mitad de frase ("regalo para Domingo"); (c) está al inicio
    seguido de me / te / le / nos / les / se ("Domingo me presta el carro"). En cualquier otro caso es fecha
    ("ensayo domingo 5pm", "domingo 20:00", "Domingo ensayo 5pm"). Un texto todo en mayúsculas se evalúa como si
    fuera minúscula ("LLAMAR A DOMINGO" pregunta por (a); "MISA DOMINGO 10 AM" es fecha). Con determinante es fecha
    con cualquier capitalización. Nunca se asume "hoy". Si hay otro día claro ("llamar a Domingo mañana a las 5 pm"),
    manda ese día y el título conserva "Domingo".
11. **Título**: se quita el verbo inicial `recordar / recordarme / recuérdame` (y un `que`/`de` que lo siga) solo si hay
    fecha y queda algo más: "recordar mañana 8am llevar tarea de cálculo" → "llevar tarea de cálculo". Sin fecha el título
    no se toca ("recordar mi contraseña").
12. **Horas en palabras y marcadores (2º encargo, regla 2-3).** Marcadores `a. m.`, `p. m.`, `a.m.`, `a m`, `AM` (con
    espacios y puntos); "la una", "las dos…las doce", "mediodía", "medio día", "medianoche"; "y cuarto / y media / y N",
    "menos cuarto / menos N". Una sola expresión regular para toda hora (`_RE_CLOCK`); un número suelto sin "a las",
    sin `:` y sin marcador NO es hora.
13. **Citas bíblicas (regla 1).** Lista cerrada: los 66 libros en español (con numerados: `1 Juan`, `2 Corintios`,
    `Salmo/Salmos`) y abreviaturas habituales (Jn, Mt, Lc, Ro, 1Co…). "Libro cap:vers" (también "3:16-18") no es hora,
    con o sin día, y se queda en el título. Se pregunta `time_or_verse` ("¿hora o cita?") cuando: el nombre es uno de
    Juan, Mateo, Marcos, Lucas, Santiago, Daniel, Samuel, Tito, Timoteo, Josué, va precedido de "a" o "con" y sigue un
    `H:MM` ("llamar a Juan 3:30"); es una abreviatura que coincide con una palabra común (Mi, Mal, Os, Is, Am, Ex,
    Sal, Rey); o es `H:MM` suelto tras una palabra con mayúscula a mitad de frase ("reunión con Pedro 3:30 mañana").
14. **Números sueltos (reglas 4 y 6).** "7.30" pregunta (`dotted_time`) si hay día o "a las"; un número pegado tras un
    día ("mañana 7 dentista", "el domingo 11 cumpleaños de mamá") pregunta (`number_after_day`). No aplica si el número
    es parte de una hora o de "N de mes", ni si va tras la hora ("el viernes a las 5 pm 2 cosas").
15. **Fechas con aspecto de fecha (regla 7).** Se soporta "el N" (siguiente ocurrencia, hoy cuenta; solo si lo que
    sigue es fin de texto, puntuación, "a las" u hora), "N de mes" y "en N días/semanas". Preguntan
    `unsupported_date`: "el 20 de este mes", "1ro/1º/1er/primero de noviembre", "en N meses/años", "próximo mes",
    "fin de mes", "la semana que viene", "esta semana", y "el N" seguido de una palabra ("el 5 dentista",
    "el 3 de espadas"). `el 40` → `invalid_date`.
16. **Candidatos am/pm sin día (regla 9).** Sin día y sin marcador, se calcula la próxima ocurrencia futura de CADA
    lectura (am y pm). Si la am llega antes que la pm, o la hora es de 5 a 11, se pregunta con las dos (ordenadas)
    aunque la hora sea de 1 a 4 ("a las 4" a las 23:00 → 04:00 y 16:00). Si la pm llega primero y la hora es de 1 a 4,
    queda la tarde con `meridiem_inferred`. Con día explícito rige la regla 3; un candidato único ("hoy a las 8" a las
    15:30) sigue siendo `ask` con ese candidato, nunca `ok`.
17. **"Mañana" de madrugada (regla 10).** Entre las 00:00 y las 05:00 locales (05:00 ya no), "mañana" pregunta
    `today_or_tomorrow` con los dos candidatos futuros ("mañana a las 8 am" a las 00:40 → hoy 08:00 o mañana 08:00); con una
    hora am/pm dudosa se pregunta primero el día y no hay candidatos. Si la lectura de hoy ya pasó, no hay duda. No aplica
    a "pasado mañana". "mañana por la mañana" no se reconoce como hora y sigue preguntando `unrecognized_time`.
18. **29 de febrero (regla 11).** Siempre la siguiente fecha bisiesta REAL (2028 → 2032; 2096 → 2104, porque 2100 no
    es bisiesto). Si el 29/02 de hoy ya pasó a la hora por defecto, se pregunta `past` con el candidato 2032-02-29.
Pruebas: tablas con reloj fijo (sáb 2026-10-03 15:30, México): frases con falsos positivos, horas 1–12 con y sin
marcador y `H:MM` suelto, la matriz 7 días × 3 capitalizaciones × 5 contextos para "Domingo", la tabla adversarial
(`tests/test_dates_adversarial.py`, ~250 casos) y el barrido de reloj (`tests/test_dates_sweep.py`).
`python scripts/show_parse_table.py` imprime frase / reloj / resultado real de la tabla adversarial.

Recurrencia (`parsing/recurrence.py`, lista cerrada): "todos los días [hora]", "cada día [hora]", "diario/diaria [hora]",
"cada <día> [hora]", "todos los <días> [hora]" (lunes…domingos) y "de lunes a viernes [hora]".
Devuelve `rrule` + primera ocurrencia futura; el handler muestra interpretación y próxima fecha antes de guardar.
`next_occurrence(rrule, scheduled, after, tz)` calcula desde la hora programada (la usa también el motor, sin deriva, DST-seguro).
**Regla 8:** si aparece `todos los / todas las / cada / diario / semanal / mensual / quincenal / anual` y no se entiende
como serie, se pregunta `unrecognized_recurrence`; NUNCA se guarda un aviso único. La constante compartida
(`RE_RECURRENCE_KEYWORD`, `has_recurrence_keyword`) vive en `dates.py` y la usan `dates.py` y `recurrence.py`. "diario"
precedido de mi/mis/el/un/del/su/tu es un sustantivo y no cuenta ("escribir en mi diario mañana"). El flujo del handler
es `parse_schedule` (en `recurrence.py`): PRIMERO la repetición, LUEGO la fecha suelta; devuelve `none / once / series / ask`.

### Preguntas del parser → texto y botones (para el bloque 7)
`WhenResult.reason` / `ScheduleResult.reason`. Los candidatos vienen ya resueltos (UTC); el handler solo los formatea
con `format_when`. Un botón por candidato más [Escribir otra fecha] [Cancelar]. El texto original ya está en la bandeja.
| Código | Texto al usuario | Botones |
|---|---|---|
| `time_or_verse` | «¿"{H:MM}" es una hora o una cita bíblica?» | [Es una hora] [Es una cita (sin fecha)] |
| `name_or_day` | «¿"Domingo" es una persona o el día de la semana?» | [El domingo ({fecha})] [Es un nombre (sin fecha)] |
| `dotted_time` | «¿"{7.30}" es la hora 7:30? Escríbela con dos puntos.» | [{7:30 am}] [{7:30 pm}] [Otra hora] |
| `number_after_day` | «¿"{7}" es la hora o forma parte del texto?» | [Es la hora: {7:00 am} / {7:00 pm}] [Es parte del texto ({día} a las {09:00})] |
| `unsupported_date` | «No entiendo "{expresión}". ¿Qué día quieres?» | **Si es "el N": el candidato ya resuelto** [{fecha del próximo día N}] + [Escribir otra fecha]; si no, [Hoy] [Mañana] [Elegir fecha] |
| `unrecognized_recurrence` | «"{expresión}" no está entre las repeticiones que sé hacer (todos los días, cada lunes, de lunes a viernes).» | [Todos los días] [Cada {día}] [Solo una vez…] [Escribirlo de nuevo] |
| `ambiguous_time` | «¿Medianoche de {hoy/mañana} o de {día siguiente}?» | un botón por candidato: [{lun 5 oct 00:00}] [{mar 6 oct 00:00}] |
| `ambiguous_meridiem` | «¿A las {8} de la mañana o de la noche?» (con 1 solo candidato: «¿A las 8 pm?» y [Otra hora]) | un botón por candidato: [{8:00 am}] [{8:00 pm}] |
| `past` | «Esa fecha ya pasó. ¿La dejo para {alternativa}?» | [{candidato}] (si lo hay) [Otra fecha] [Cancelar] |
| `today_or_tomorrow` | «Ya pasó la medianoche: ¿"mañana" es hoy ({fecha}) o mañana ({fecha})?» | [Hoy {fecha}] [Mañana {fecha}] (sin candidatos: el handler arma los dos días y luego pregunta la hora) |
| `same_weekday` | «Hoy es {día}: ¿hoy o en 7 días?» | [Hoy {fecha}] [En 7 días {fecha}] |
| `two_dates`, `unrecognized_time`, `invalid_date`, `invalid_time` | «No pude entender la fecha/hora; escríbela de otra forma.» | [Escribir otra fecha] [Cancelar] |

Notas para el bloque 7:
- Las preguntas de "el N" (`unsupported_date`, `past`) **deben traer el candidato ya resuelto** (próximo día N del mes), no
  pedirle la fecha completa al usuario. Hoy `unsupported_date` no calcula candidatos; es trabajo del handler/parser en ese bloque.
- **Mejora menor pendiente:** "1ro / 1º / 1er / primero de noviembre" hoy pregunta (`unsupported_date`); soportarlos es trivial
  (ordinal + "de mes") y se deja para después.

## Plan de pruebas del motor (FakeClock + FakeChannel + SQLite en memoria)
1. Único: a T−1 s no sale; a T sale una vez (`kind="reminder"`, 4 botones); `sent` + `last_fired_at`; no se repite.
2. +10 min / +1 h / Mañana (`default_morning_time` local): `pending`, `snooze_count+1`, sale a su hora.
3. Semanal sin deriva: disparo tardío, la siguiente cae en la hora exacta; 10 repeticiones sin desfase; cruce de horario de verano.
4. Silencio: se retiene y sale a `quiet_end` con "(retrasado)" en orden; `priority=2` pasa; bordes 22:00/07:00.
5. Recuperación tras caída: vencidos de 1 h, 1 día y 3 días salen todos "(retrasado)" en orden; semanal vencido 3 semanas envía uno.
6. **Canal caído 10 min**: transitorio → reintentos con espera creciente sin tocar `fire_at`; al volver salen todos
   con "(retrasado)", ninguno se pierde. Permanente → se detiene, queda marcado, los demás siguen. Rendición a las 24 h.
7. Insistencia `priority=2`: +15 min, +30 min, 3 veces máx., la detiene (`nag_count`).
8. Preparación: 1 día / 1 h antes solo si no han pasado.
9. AST: sin imports de `llm`/`classify`/`anthropic`/`telegram` (transitivo) + test del detector.
10. rrule + snooze: sin duplicados ni deriva; re-disparo de fila pospuesta no crea otra; rendirse no corta la serie; atomicidad.
11. Cancelación en cascada al hacer/descartar/posponer tarea.
12. Fecha pasada → pregunta, nunca crea recordatorio.
13. Tick sin solapamiento.
14. `is_quiet_hour`: normal, cruce de medianoche, bordes, `start==end`, zonas.

## Estado (2026-10-03): bloques 0 a 6 HECHOS — `pytest -q`: 1017 passed, 2 xfailed; `ruff check .`: limpio
(El bloque 6 está descrito en su viñeta de más abajo; pendientes: 7 y 8.)

### Estado anterior (bloques 0 a 5b) — `pytest -q`: 526 passed
Además: regla 3 nueva (migración 003 con `meridiem_ask_range`), corrección de "Domingo" y verbo inicial del título.
Pendientes: 6, 7 y 8.
Revisión de robustez (antes del bloque 6) HECHA: M2, migración 004, M3/M6/M13, códigos de detención, M7, M8, M9, M10 y M5
(un commit cada uno, con la prueba escrita antes; `pytest -q`: 584 passed; `ruff check .`: limpio). Pendiente: M1 (inicio del
bloque 6) y la deuda conocida de abajo.
Endurecimiento del parser (2º encargo, antes del bloque 6; reglas 12-18 y la regla 8 de repeticiones) HECHO en commits
pequeños con la prueba escrita antes: citas bíblicas, marcadores y horas en palabras, "7.30" y números sueltos, "domingo"
(dos veces), fechas no soportadas / "el N" / 29 de febrero, repeticiones + `parse_schedule`, "diario" sustantivo, candidatos
am/pm sin día y "mañana" de madrugada, barrido de reloj y deuda de horario de verano. `pytest -q`: 880 passed, 2 xfailed;
`ruff check .`: limpio. Tabla de frases ejecutadas: `python scripts/show_parse_table.py`.

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
5. **"Domingo" como posible nombre propio** (regla 10 del parser, revisada): pregunta `name_or_day` solo tras "a"/"con", con
   mayúscula a mitad de frase o al inicio seguido de me/te/le/nos/les/se; con determinante siempre es fecha (el defecto
   anterior, que descartaba "el Domingo", ya no existe).
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
- [x] 6. Scheduler (`on_tick`, tick al arrancar) y botones de recordatorio — HECHO (2026-10-03), 6 commits:
  M1a (traducción de errores y `RetryAfter`), M1b (aislamiento de recordatorios rotos), M1c (ajustes: sin categoría
  por evidencia, códigos saneados, anti-bloqueo), scheduler, botones, cuelgue de pytest y `scripts/dev_remind_me.py`.
  - **Scheduler.** `run_polling(on_message, on_choice, on_tick)`. Telegram: `job_queue.run_repeating(interval=30,
    first=0, job_kwargs={"max_instances": 1, "coalesce": True})`; `first=0` ES el tick de arranque (recuperación tras
    caída: Telegram no puede enviar antes de que `run_polling` inicialice el bot). Consola: tarea asyncio con el mismo
    ritmo (un tick al empezar), cancelada al salir. `run_tick_safely` (en `channels/base.py`) registra solo el tipo
    de error y no mata el job. `main.py` conecta `ReminderEngine.tick` con el reloj real (`build_engine`).
  - **Botones.** `rem_done:ID`, `rem_snooze:ID:10|60`, `rem_tomorrow:ID`. `handle_choice(choice, channel,
    allowed_user_id, conn, now, tz_name)` valida el id (entero ASCII, minutos solo 10 o 60; un id mal formado se
    responde como opción vieja y no toca nada), edita el mensaje SIN teclado y conserva el texto del recordatorio:
    `Hecho: {texto}`, `Pospuesto para {hoy, 3:40 pm | domingo 4 de octubre, 9:00 am}: {texto}`,
    `Recordatorio: {texto} (ya no está activo)` (pulsar dos veces, cancelado, ya pospuesto) o «Este recordatorio ya no está
    activo.» si el id no existe. Sin `message_ref` (consola) se manda un mensaje nuevo en vez de editar.
    «Activo» = `sent` para posponer (lo que ya exigía el motor) y `pending`/`sent` para Hecho.
  - **Canal.** `Channel.edit_text(to, message_ref, text)` (SPEC 3.1) e `IncomingChoice.message_ref`. En Telegram:
    "message is not modified" no es error; cualquier otro fallo al editar o al responder (`answer`) se registra por
    tipo y no impide la acción. El dueño SIEMPRE recibe `answer`; un extraño, nada.
  - **Etiqueta «Mañana».** `reminders.tomorrow_target` es la única fuente de la acción y de `tomorrow_label`
    («Mañana 9:00» / «Hoy 9:00» antes de las 05:00 locales, con `default_morning_time`); hay una prueba que recorre
    el día entero y exige que etiqueta y acción nunca discrepen. La etiqueta se fija al ENVIAR: si se pulsa tras las
    05:00 con la etiqueta «Hoy 9:00», la acción manda a mañana y el texto de confirmación lo dice con el día completo.
  - **Cuelgue de pytest en Windows.** `tests/test_reminders_outage.py` usa un solo bucle por módulo (`asyncio.Runner`).
    Medido: ANTES 9 de 20 corridas del archivo se colgaban (tope de 45 s); DESPUÉS 0 de 20, y 4 corridas completas de
    `pytest -q` sin cuelgue. Los demás archivos siguen usando `asyncio.run`; si reaparece, aplicar el mismo patrón.
  - **`scripts/dev_remind_me.py`** `N ["texto"] [--urgente]`: crea el recordatorio en `DB_PATH` con el motor (sin LLM,
    sin secretos), avisa si la hora cae en silencio. Se probó solo con bases temporales, nunca con la real.
- [ ] 7. Bandeja, comandos, `/hoy`, `/pendientes` con Hecha/Descartar; botones de `ambiguous_meridiem` (dos opciones)
  y "Cambiar a am/pm" cuando `meridiem_inferred` — `Fase 1: bandeja y comandos`
  **Aviso de recuperación (una sola vez):** si hubo recordatorios detenidos (`stop_reason` no nulo) mientras el dueño
  no estaba (bot bloqueado, caída de 24 h, errores aislados), el bot avisa UNA vez, con el siguiente mensaje del dueño
  (no antes: si el canal estaba roto no se puede enviar). La marca de "ya avisado" vive en `settings` (clave nueva,
  p. ej. `recovery_notice_sent_at`, migración hacia adelante). El aviso trae un botón **Reenviar** que llama a
  `reminders.reactivate` (sale "(retrasado)"; no crea otra ocurrencia de la serie).
- [ ] 8. README, verificación final y manual en `--dry-run` — `Fase 1: documentación y verificación`

8. **Errores de Telegram (M1, bloque 6)**. Dos grupos más un tercero "por evidencia":
   - Salud del canal → `TransientChannelError`: `NetworkError`, `TimedOut`, 5xx (la librería los entrega como
     `NetworkError`), `InvalidToken` y `RetryAfter` (con `retry_after`: se espera AL MENOS eso, tope de 10 min).
   - Culpa del mensaje o del chat → `PermanentChannelError` solo para esa fila, sin corta-circuito: `Forbidden`
     (`bot_blocked`), `chat_not_found`, `message_too_long` y los `BadRequest` conocidos
     (`bad_request:cant_parse_entities | empty_text | button_data_invalid`; el resto, `bad_request:other`).
     El código NUNCA contiene el mensaje de Telegram (podría traer texto arbitrario, emojis o URLs).
   - Sin categoría (`Conflict`, `ChatMigrated`…) y excepciones que no son de Telegram →
     `UnclassifiedChannelError` / excepción cualquiera: el tick prueba con los demás. Si otro sale DESPUÉS, la
     culpa es de esa fila y se detiene (`permanent:telegram_error:<Clase>` o `permanent:unexpected:<Tipo>`); si
     ninguno sale, es pasajero. Tres fallos inesperados seguidos cortan el tick. Los que ya fallaron así (en memoria)
     van al final del siguiente tick y, si el canal entrega otros antes, se detienen: unos rotos al frente no
     dejan sin salir a los válidos.

## Deuda conocida (no se arregla en la Fase 1)
- **`retry_after` de python-telegram-bot (baja).** En la versión 22.8 `RetryAfter.retry_after` es `int` y emite
  `PTBDeprecationWarning` (en una versión mayor será `timedelta`). `channels/telegram.py::seconds_from` ya acepta
  ambos, y NO se silencian los avisos a propósito. Al actualizar la librería: revisar el aviso, quitar la
  compatibilidad con `int` si procede y comprobar `tests/test_telegram_errors.py`.
- **Parser y horario de verano (media; baja en zonas sin él).** Una hora que no existe (14 de marzo de 2027 a las 2:30 am en
  Nueva York, salto de 02:00 a 03:00) o que ocurre dos veces (1 de noviembre de 2026 a la 1:30 am) se acepta en silencio; lo
  correcto es preguntar. Dos pruebas `xfail(strict=True)` en `tests/test_dst_known_debt.py` (cuando se arregle fallarán por
  XPASS y habrá que quitar la marca). El barrido de reloj no lanza excepciones en esas horas pero omite la invariante de la
  hora escrita en los días de cambio.
- **Parser: "1ro/1º/1er/primero de noviembre"** pregunta (`unsupported_date`); soportarlo es una mejora menor.
- **Entorno de pruebas en Windows (no es del parser).** Una de cada ~6 corridas de `pytest -q` se queda colgada creando el bucle
  de asyncio (`_fallback_socketpair`/`socket.accept`) en `tests/test_reminders_outage.py`; `faulthandler_timeout = 60`
  vuelca la pila. ARREGLADO en el bloque 6 para ese archivo (un bucle por módulo; ver el bloque 6). Queda como riesgo
  en los demás archivos que usan `asyncio.run`.
- **Etiqueta «Hoy 9:00» fija al enviar.** Se calcula al enviar el aviso; si el dueño pulsa después de las 05:00, la
  acción manda a mañana y el texto de confirmación lo dice. Aceptado: el id del botón (`rem_tomorrow:ID`) no lleva la fecha.
- **M4 — deriva permanente por horario de verano (media; baja en zonas sin él).** Una serie diaria a las 02:30 en una
  zona con horario de verano pasa a las 03:30 el día del adelanto y se queda ahí, porque el ancla de `_spawn_next` es el
  `fire_at` de la fila anterior, ya corrido. Prueba futura: `FREQ=DAILY` a las 02:30 en `America/New_York` del 6 al 10 de
  marzo; el 9 y el 10 deben salir a las 02:30 locales. Arreglar antes de ofrecerlo en zonas con horario de verano.
- **M11 (baja).** Mañana en una serie diaria de las 8:00 hace que mañana suenen dos avisos: el de la serie y el
  pospuesto a las 9:00.
- **M12 (baja).** +10 min pulsado a las 21:55 sale a las 07:00 con "(retrasado)"; defendible, pero no se avisa.
- **M14 (baja).** Si Telegram aceptó el mensaje pero la respuesta no llegó a tiempo, se reintenta y llega dos veces;
  coherente con "al menos una vez".
- **M15 (baja).** Las comparaciones de horas son de texto: exigen que toda hora se escriba con `to_utc_iso`; una fila con
  `Z` o microsegundos se ordenaría mal. Defensa futura posible: `CHECK (fire_at_utc LIKE '____-__-__T__:__:__+00:00')` en
  una migración.
