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
3. **Hora sin am/pm (REGLA PROPUESTA, pendiente de tu visto bueno)**:
   - Con `am`/`pm` o `de la mañana/tarde/noche/madrugada`: se respeta (12 am y 12 de la noche → pregunta).
   - 13–23 y 0 → reloj de 24 h. Con cero inicial (`08:30`, `05:00`) → 24 h literal.
   - 12 → mediodía. **7–11 → mañana (am). 1–6 → tarde (pm).** Nadie agenda a la 1–6 am; clases a las 7–11 am.
   - La confirmación siempre muestra "am/pm", así que un error se ve y se corrige con [Cambiar].
   - `H:MM` suelto sin "a las"/am/pm (p. ej. un versículo "Juan 3:16") solo cuenta como hora si el texto trae también un día.
   - "a las 8 y media / y cuarto" se entienden; "menos cuarto", "medianoche" → pregunta.
4. Día de la semana igual al de hoy ("el viernes" siendo viernes) → pregunta (hoy / en 7 días).
   "próximo viernes" siendo viernes → +7; "este viernes" siendo viernes → hoy.
5. Fecha/hora ya pasada → pregunta (con la alternativa futura más natural); jamás se crea en el pasado.
6. Día/mes sin año = siguiente ocurrencia (hoy cuenta). "29 de febrero" → siguiente año bisiesto. Fecha inexistente
   ("31 de abril") → pregunta. `d/m` suelto solo con "el" delante (evita "1/2 kilo"); con año se acepta sin "el".
7. Dos fechas, dos horas, hora dudosa o con restos sin entender ("8:30 menos cuarto") → pregunta.
8. Sin hora → `default_morning_time` (`has_time=False`, para avisar "hora por defecto").
9. "en N minutos/horas" (instante exacto), "en N días/semanas" (día a `default_morning_time`). "estudiar 2 horas" no es fecha.
10. Un día de la semana con mayúscula a mitad de frase ("llamar a Domingo") se toma como nombre propio, no como fecha.
Pruebas: tabla con reloj fijo (sáb 2026-10-03 15:30, México), ≥ 60 frases incluidos falsos positivos.

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

## Bloques (un commit por bloque)
- [x] 0. Plan y SPEC (secciones 7 y 8.3) — `Fase 1: plan y actualización del SPEC`
- [x] 1. Dependencias: `python-telegram-bot[job-queue]==22.8`, `python-dateutil` (`dateparser` se añadió y luego se retiró en el bloque 3) — `Fase 1: dependencias`
- [x] 2. `is_quiet_hour` / `next_quiet_end` + pruebas — `Fase 1: horas de silencio`
- [x] 3. `parsing/dates.py` y `parsing/recurrence.py` propios (sin dateparser) + pruebas en tabla (≥60 frases) — `Fase 1: parseo de fechas propio`
- [x] 4. Migración 002, `core/areas`, `tasks`, `notes` + pruebas — `Fase 1: áreas, tareas y notas`
- [ ] 5a. Motor base: único, snooze, silencio, reintentos, AST, sin solapamiento — `Fase 1: motor de recordatorios (base)`
- [ ] 5b. Motor: rrule, recuperación, insistencia, preparación, cascada — `Fase 1: motor (rrule, recuperación, insistencia)`
- **— CORTE PRINCIPAL —**
- [ ] 6. Scheduler (`on_tick`, tick al arrancar) y botones de recordatorio — `Fase 1: scheduler y botones de recordatorio`
- [ ] 7. Bandeja, comandos, `/hoy`, `/pendientes` con Hecha/Descartar — `Fase 1: bandeja y comandos`
- [ ] 8. README, verificación final y manual en `--dry-run` — `Fase 1: documentación y verificación`
