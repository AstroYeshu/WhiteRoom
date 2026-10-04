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

