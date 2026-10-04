# DECISIONS — decisiones importantes

Formato: qué · por qué · alternativas descartadas. Máx. 5 líneas. La más reciente al final.

## Parser propio de fechas, sin `dateparser`
`parsing/dates.py` con gramática cerrada. `dateparser 1.4.3` devolvía fechas incorrectas SIN avisar en español
("mañana 8am" → 15:30, "el viernes" → viernes pasado). Descartado: ajustar su configuración (5 de 18 frases
seguían mal). Lo que no encaja entero se pregunta; nunca se adivina.

## Sin el centinela `attempts = 1000`
Un recordatorio detenido se marca con `stop_reason` no nulo (migración 004). El centinela mezclaba "intentos" con
"estado" y no decía por qué se detuvo. Descartado: columna booleana sola (perdería el motivo).

## Bandeja convertida = `dropped` + `closed_reason`
Al elegir Recordatorio o Nota, la tarea de bandeja queda `status='dropped'` con
`closed_reason='converted_to_reminder|converted_to_note'`. Descartado: `done` (inflaría las hechas) y borrarla (nada se borra).

## Reintentos con horizonte de 24 h y tope de 5 min
Fallo pasajero: espera del CANAL `min(30 s · 2^(n−1), 5 min)`, corta-circuito al primer fallo del tick, horizonte de
24 h desde `first_failed_at` (en la base). Así reiniciar no lo reinicia y ningún aviso se pierde. Descartado: espera
por fila (un canal caído lo está para todos) y reintentar sin fin.

## Dinero en centavos enteros
`amount_cents` siempre entero; el saldo lo calcula SQL. Descartado: `float` (errores de redondeo) y `Decimal` en la
base. Jev y Claude nunca ven saldos.

## Recordatorios sin LLM
`core/reminders.py` no importa `llm/`, `classify/`, `anthropic` ni `telegram` (test AST transitivo). Prioridad 1 del
proyecto: suenan aunque falle cualquier API. Descartado: usar el LLM para interpretar fechas.

## Regla revisada de "domingo"
Solo "domingo" puede ser nombre propio; pregunta (`name_or_day`) únicamente tras "a"/"con", con mayúscula a mitad de
frase o al inicio seguido de me/te/le/nos/les/se. Con determinante es siempre fecha. Descartado: preguntar siempre
(demasiado ruido) y asumir "hoy".

## `edit_text` y `message_ref` en `Channel`
Pulsar un botón edita el mensaje (texto nuevo, sin teclado) en vez de mandar otro; la consola cae a un mensaje
nuevo. Un futuro WhatsApp podrá decidir. Descartado: que `bot/` conozca el `message_id` de Telegram.

## Códigos de parada con prefijo `permanent:`
`stop_reason` = `permanent:<motivo>`, `horizon:<motivo>` o `legacy`; motivos estables (`bot_blocked`, `bad_request:<tipo>`,
`telegram_error:<Clase>`, `unexpected:<Tipo>`), nunca texto del usuario ni mensaje de Telegram. Descartado: prosa
(inestable y puede filtrar texto).

## Errores desconocidos de Telegram decididos por evidencia
Sin categoría (Conflict…) o no-Telegram: el tick prueba con los demás; si otro sale DESPUÉS, la culpa es de esa fila y se
detiene; si ninguno sale, es pasajero. Tres fallos seguidos cortan el tick. Descartado: permanente por defecto
(un fallo del canal detendría todo) y transitorio por defecto (un recordatorio roto bloquearía a los demás).

## Un solo bucle de asyncio por módulo en las pruebas del motor
`asyncio.Runner` de módulo en `test_reminders_outage.py`. Crear un bucle por prueba se colgaba en Windows
(`_fallback_socketpair`): 9 de 20 corridas antes, 0 de 20 después. Descartado: reintentar la corrida a mano.

## Tick cada 30 s
Un aviso llega entre 0 y 30 s después de su hora. Simple, sin puertos ni temporizadores por fila, y la recuperación
tras caída es la misma ruta. Descartado: un temporizador por recordatorio (se pierde al reiniciar) y ticks más cortos
(más carga y más ruido en el log para la Raspberry sin ganancia real).
