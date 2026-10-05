# BACKLOG — ideas aparcadas

Sin compromiso ni fecha. Nada de aquí se implementa sin que el dueño lo pida. Hallazgos fuera de alcance, aquí.

## Ideas grandes
- **Complementos experimentales** (SPEC y PDF, sección 14).
- **WhatsApp** como canal secundario (solo tras la Fase 3 y respetando SPEC 3.1).
- **Correo** (solo lectura, `gmail.readonly`).
- **Modo docente.**

## Deuda conocida (detalle en `docs/PLAN_FASE1.md`)
- **M4:** una serie diaria a las 02:30 en zonas con horario de verano se corre a las 03:30 y se queda ahí.
- **M11:** Mañana en una serie diaria de las 8:00 hace que suenen dos avisos mañana (serie + pospuesto).
- **M12:** +10 min pulsado a las 21:55 sale a las 07:00 "(retrasado)" sin avisar.
- **M14:** si Telegram aceptó el mensaje pero la respuesta no llegó a tiempo, el aviso llega dos veces.
- **M15:** las horas se comparan como texto; un `CHECK` sobre el formato de `fire_at_utc` lo blindaría.

## Parser
- "1ro / 1º / 1er / primero de noviembre" hoy pregunta (`unsupported_date`); soportarlo es trivial.
- "mañana por la mañana" reconocido como hora (hoy pregunta `unrecognized_time`).

## Operación
- Bajar el ruido de logs del scheduler (hoy, dos líneas cada 30 s).

## Preguntas del parser (surgido en el bloque 7a)
- Las preguntas sin candidatos que dependen de reinterpretar el texto (`time_or_verse` «Es una hora», `name_or_day` «El
  domingo (fecha)», `dotted_time`, `number_after_day`, `unrecognized_recurrence` «Todos los días / Cada {día}») se
  muestran hoy con texto + [Escribir otra fecha] [Cancelar] (y [sin fecha] donde aplica); los botones que re-interpretan
  necesitan que el parser devuelva candidatos.
- `today_or_tomorrow` sin candidatos: hoy se pide escribir el día con la hora; el plan quería armar los dos días y luego
  preguntar la hora.


## Diseños aprobados, pendientes de construir tras una semana de uso
Aprobados por el dueño; no se construyen hasta que haya usado el bot una semana. Sin cambiar el motor de avisos salvo lo indicado.

### a) `/recordatorios`, formato E
- **Secciones, en este orden:** En espera, Hoy, Mañana, Esta semana, Más adelante, Detenidos.
- **Lista numerada** (una sola numeración) con un botón por número, como en `/pendientes`.
- **Detalle** de un recordatorio: [Cambiar fecha] [Cancelar] [Volver]. En series NO aparece [Cambiar fecha].
- **[Deshacer]** tras cancelar (patrón de Deshacer de la captura).
- **[Reintentar]** en los detenidos (llama a `reminders.reactivate`).
- **Motor:** nueva función `reschedule_reminder` en `core/reminders.py` (cambia `fire_at_utc`, reinicia intentos y `stop_reason`, nada se borra).

### b) Aviso del recordatorio, formato B
- **Cuerpo:** título «Recordatorio», el texto, «hora · Área» y los botones [Hecho] [Posponer].
- **Posponer** abre: [+10 min] [+1 h] [Mañana 9:00 am] (o «Hoy» en vez de «Mañana» antes de las 05:00) [Elegir hora] [Volver].
- **Variantes** en cursiva: «Retrasado» (umbral actual de 2 min) y «Aviso 2 de 3» (reintentos).
- **Compatibilidad:** los ids viejos `rem_done`, `rem_snooze` y `rem_tomorrow` siguen funcionando (mensajes ya enviados con botones viejos).

## Surgido en el commit de estilo (capitalización)
- La descripción de un área se muestra tal cual la escribió el dueño (no pasa por `cap_first`): decidir si también debe capitalizarse al mostrar.
- Dos áreas que ya chocaban entre sí antes de la migración 006 (sin distinguir acentos o mayúsculas) quedan ambas como estaban; no hay herramienta para fusionarlas (nada se borra).
