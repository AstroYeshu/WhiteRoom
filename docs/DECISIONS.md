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

## Bandeja (bloque 7a): guardar primero, preguntar después
Un mensaje libre se guarda al instante como tarea sin área; luego se pregunta tipo, área y (recordatorio) fecha. El estado
a medias vive en MEMORIA (`bot/conversation.py`, un solo flujo): caduca a los 10 min SIN actividad y se pierde al
reiniciar, sin consecuencias porque la tarea ya está guardada. Cada pregunta nueva RENUEVA el id del flujo (los botones
llevan `in:FLUJO:ACCION[:ARG]`): los botones de una pregunta ya contestada, de un flujo descartado o tras un reinicio
quedan inertes («Esa opción ya no está disponible»). Un texto cuenta como respuesta a «¿cuándo?» solo si el parser lo
entiende como fecha (`once`, `series` o `ask` salvo `name_or_day`/`time_or_verse`); si no, es una captura nueva y el
flujo anterior se suelta avisando (su tarea sigue en la bandeja). Orden: tipo -> área -> fecha, para crear el
recordatorio una sola vez con su área. Un texto que empieza por recordar/recordarme/recuérdame/recuérdenme salta la
pregunta de tipo. Descartado: guardar el recordatorio antes de preguntar el área (obligaría a editarlo después).

## Convertir y deshacer en UNA transacción
`tasks.convert_to_reminder` cierra la tarea de bandeja (`close_as_converted`) y crea el recordatorio (sin `task_id`) en la
misma transacción; con fecha pasada no queda nada hecho. `tasks.undo_reminder_conversion` cancela el recordatorio (solo si
sigue `pending`) y reabre la tarea (`reopen_converted`, limpia `closed_reason` y `closed_at`) en una transacción; si el
recordatorio ya no está pendiente, «ya no se puede deshacer». Los botones Deshacer/Cambiar (`un:`/`ch:RECORDATORIO:TAREA`)
viven en la base, no en la memoria: funcionan tras un reinicio. Cambiar = Deshacer + «¿cuándo?» conservando área y texto.
La nota se crea y LUEGO se cierra la tarea (dos pasos): el peor caso es una nota duplicada, nunca una pérdida.

## Un candidato único nunca se guarda en silencio
`ok` se guarda y confirma con día de la semana y [Cambiar][Deshacer]; `ask` (incluso con un solo candidato) pide pulsar el
candidato. La opción se revisa al PULSAR: si ya pasó, no se crea y se vuelve a preguntar. Una repetición se previsualiza
con [Guardar][Cancelar] antes de guardar. «¿Cuándo?» ofrece [Hoy 18:00 (solo si es futuro)] [Mañana 9:00] [Cancelar].

## «¿Cuándo?» invita a escribir y ofrece «Mejor como tarea»
La pregunta «¿Cuándo?» (y la de «hora pasada») dice «o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5"» y trae
[Mejor como tarea]: deja la entrada como tarea con el área ya elegida, sin recordatorio. Solo en «¿Cuándo?», no en las
preguntas con candidatos. La confirmación de una fecha sin hora dice «9:00 am (hora por defecto)» (con am/pm, como el
resto de `format_when`). Regla de respuesta: un texto es respuesta a «¿cuándo?» si `parse_schedule` lo entiende (`once`,
`series` o `ask` salvo `name_or_day`/`time_or_verse`); `none` es captura nueva y avisa. Se usa `parse_schedule` y no
`parse_when` a secas para que «todos los lunes…» también cuente como respuesta.

## `TICK_SECONDS` configurable (5-60, por defecto 30)
El ritmo del tick sale de `.env` (`Settings.tick_seconds`) y llega a `run_polling` / `serve`. Fuera de 5-60 o no entero:
`ConfigError` (no se adivina). El motor no conoce el ritmo: la espera entre reintentos (30, 60, 120, 240, 300 s) y el
umbral de «(retrasado)» (2 min) son tiempos, no vueltas; pruebas con ticks de 10 y de 30 s dan los mismos instantes.
El logger `apscheduler` sube a WARNING (con un tick de 30 s eran dos líneas INFO por tick); `asistente.*` no se toca.
Descartado: subir todo el registro a WARNING (ocultaría nuestros errores y avisos útiles).

## Mensajes sin emojis ni pictogramas
Ningún texto al usuario (botones, mensajes, confirmaciones, consola) lleva emojis ni pictogramas: etiquetas `Hecho`,
`+10 min`, `+1 h`, `Mañana 9:00` (o `Hoy 9:00` antes de las 05:00; la etiqueta lleva SIEMPRE la hora), mensajes
`Recordatorio: {texto}`, `Hecho: {texto}`, `Pospuesto para {día hora}: {texto}`. `tests/test_no_pictograms.py` recorre con
`ast` las constantes de texto de `asistente/` y `scripts/` (docstrings y f-strings incluidos) y falla ante símbolos
(So/Sm/Sk), selectores de variación, ZWJ o marcos de teclado; permite tildes, eñe, `¿ ¡ « » …` y el grado `°`.
Descartado: una lista fija de emojis (se le escaparía el siguiente).

## Comandos del bloque 7b
`bot/commands.py` (un `Ctx` y el texto tras el comando). `/hoy [área]`: tareas abiertas vencidas o de hoy y recordatorios
pendientes de hoy; el día termina a las 00:00 LOCALES de mañana (no a medianoche UTC); la línea «N en bandeja sin área»
solo sale sin filtro y con N > 0. `/pendientes [área]`: un mensaje por tarea (hasta 10) con [Hecha] [Descartar] (`tk_done:ID`,
`tk_drop:ID`); pulsar dos veces o sobre una tarea ya cerrada edita con «Esta tarea ya no está abierta», sin error.
`/recordatorios`: todos los pendientes (hasta 20), con área, repetición y, si están detenidos, el motivo en lenguaje claro;
un código que no conocemos se muestra como «motivo desconocido» y el código crudo va solo al log (nivel WARNING, con el id
del recordatorio, nunca el texto). `/recordar` guarda primero en la bandeja y SIEMPRE muestra la interpretación y la próxima
fecha con [Guardar] [Cancelar] antes de crear el recordatorio (el texto libre, en cambio, guarda y ofrece Cambiar/Deshacer).
`/tarea` y `/nota` solo preguntan el área (no interpretan fechas). `/nuevaarea` valida el nombre ANTES de preguntar la
descripción ([Omitir] la deja vacía) y `/areas` marca «(sin descripción)». Las áreas pueden tener descripción vacía
(`create_area` ya no la exige); el nombre es único sin distinguir mayúsculas ni acentos y las áreas archivadas también
reservan el suyo. Un texto que llega mientras se espera la descripción del área SIEMPRE es la descripción (los comandos
no); si pasan 10 minutos se vuelve a tratar como captura nueva.
