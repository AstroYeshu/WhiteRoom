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

## `/tarea` con fecha límite
Solo `/tarea` (no el texto libre ni `/nota`): si `parse_when` devuelve una fecha CLARA (`ok`), después del área se pregunta
«¿Es la fecha límite de «título»?» con [Sí] [No] [Cancelar]. Sí: el título queda sin la fecha, `due_at_utc` se fija con
`tasks.set_due` (crea los avisos de preparación) y `source_text` conserva lo escrito. No: la tarea queda con el texto
completo y sin fecha. Si el parser duda (am/pm, "el N", etc.) o no hay fecha, no se pregunta nada: no se adivina.

## Rediseño de mensajes, corte 1: `formato.py`, HTML y reintento en texto plano
`formato.py` (funciones puras) arma textos y distribución de botones. Marcado mínimo: `<b>`, `<i>`, `<code>`. `Html` es un
`str` "ya seguro"; los constructores (`bold`, `italic`, `code`, `block`, `paragraphs`, `state_line`, `aviso`) escapan todo lo
que no sea `Html`, así que olvidarse de `esc()` no es posible por esa vía. Los canales aplican `to_html` al enviar: un `str`
plano (los flujos que aún no migran a `format.py`) se escapa y se ve literal; un `Html` pasa tal cual. La consola usa `plain`.
Telegram envía con `parse_mode=HTML`; con `cant_parse_entities` reintenta UNA vez en texto plano (también al editar); si el
texto plano falla, es permanente como antes. Interfaz `Channel`: `send_choices(..., layout)` con los botones por fila como dato
(sin él, uno por fila); la consola lo ignora. El aviso de recordatorio: contenido en negrita, línea en blanco, «Recordatorio ·
área» y «(retrasado)» en cursiva; los botones van en cuadrícula 2 por 2 (Hecho, +10 min, +1 h, Mañana 9:00). Resultados de
los botones: línea de estado («Hecho · texto», «Pospuesto · texto · hoy, 3:40 pm», «Ya no está activo · texto»). Errores y
avisos generales con un solo formato («Aviso · …»). Fechas: `fecha_corta` en botones (los candidatos del parser ya la usan) y
`fecha_larga` solo en confirmaciones. Etiquetas de botón de 22 caracteres como máximo (`label()` corta con «…»; «Es una cita»
y «Es un nombre» sin «(sin fecha)»). Presentación en el motor: `core/reminders.py` importa `reminder_notice` y `REMINDER_LAYOUT`
de `formato.py` (módulo hoja, sin dependencias de la conversación); la lógica del motor no cambió, solo `format_reminder_text`
(ahora delega) y un argumento `layout` en el envío. `docs/MENSAJES.md` se regenera con `scripts/show_messages.py` y una
prueba de instantánea (`tests/test_messages_catalog.py`) falla si se desactualiza; esa prueba también hace cumplir 22 caracteres
por etiqueta, HTML válido y filas de a lo sumo 2 botones. Descartado: escapar a mano en cada manejador (se olvida) y bloquear
el HTML por completo (perdería la jerarquía).

## `formato.py` y `choices.py` son módulos neutrales (capas)
`bot/format.py` pasó a `asistente/formato.py` y `bot/choices.py` a `asistente/choices.py`: `core/` ya no importa nada de
`bot/` (la conversación depende del núcleo, no al revés). Ambos módulos no importan, ni de forma transitiva, `bot/`, `core/`,
`classify/`, `llm/`, `anthropic` ni `telegram`; lo verifica `tests/test_arquitectura_capas.py` (AST transitivo, también para
cada archivo de `core/`). El test de `reminders.py` sin LLM sigue igual. Reemplaza lo dicho sobre la importación hacia arriba
en el corte 1.

## Rediseño de mensajes, corte 2: la captura es una tarjeta (un solo mensaje que evoluciona)
Un mensaje libre (o `/tarea`, `/nota`, `/recordar`) abre UN mensaje del bot; cada paso lo edita en su lugar: tipo, área, fecha o
pregunta del parser, vista previa y confirmación final. Interfaz `Channel`: `send_text`/`send_choices` devuelven la referencia del
mensaje (Telegram: `message_id`; consola: `None`), y `edit_text(to, ref, text, choices=None, layout=None) -> bool` acepta botones y
distribución y devuelve `False` si no pudo editar; entonces el flujo manda un mensaje nuevo y esa pasa a ser la tarjeta (consola, o
Telegram con un mensaje muy viejo). La consola imprime "[editado]" con las opciones y las numera. Botones viejos: la tarjeta viva
guarda su `message_ref`; un botón de un flujo ya renovado que cae en ESA tarjeta se ignora en silencio (si se contestara, pisaría la
pregunta vigente), uno que cae en una tarjeta muerta (otra captura, reinicio, caducidad) la edita a «Aviso · Esa opción ya no está
disponible.». Lo mismo con un segundo toque en Deshacer/Cambiar. Un mensaje nuevo a mitad de una tarjeta la EDITA a «Sin terminar» (la
tarea sigue en la bandeja) en vez de mandar un aviso aparte. Cambiar continúa en el mismo mensaje. Preguntas del parser: título en
negrita, candidatos de 2 por fila con `fecha_corta` y, abajo, [Otra fecha] [Cancelar]. Distribución como dato: `tail_layout` (filas de 2,
los últimos botones juntos en la fila final). Vocabulario: «… guardado/guardada» («Tarea guardada», «Nota guardada», «Recordatorio
guardado», «Área guardada»); «Escribir otra fecha» pasó a «Otra fecha». `/nuevaarea` usa la misma tarjeta (la descripción es el texto
siguiente). Descartado: mantener el mensaje nuevo por paso (deja un rastro de fragmentos) y contestar a los botones viejos de la
tarjeta viva (borraría la pregunta en curso).

## Aviso breve para un botón de un paso viejo (answer_callback_query)
`on_choice` devuelve el aviso breve con que se responde a la pulsación (o `None`): Telegram lo muestra con
`answer_callback_query(text=...)` (se responde DESPUÉS de atender el botón y siempre, aunque el manejador falle); la consola lo imprime
entre paréntesis. Reglas: un botón de un paso viejo sobre la tarjeta VIVA responde «Esa opción ya no aplica» sin crear ni editar
mensajes; el MISMO botón que se acaba de atender (`Conversation.last_press_id`, doble pulsación, también en Guardar y Deshacer) no
responde nada; un botón en una tarjeta muerta (otra captura, reinicio, caducidad) edita esa tarjeta a «Aviso · Esa opción ya no está
disponible.». Un doble toque en Guardar ya no pisa la confirmación con sus botones Cambiar/Deshacer.

## Rediseño de mensajes, corte 3: vistas de consulta
Todas con `formato.py` (`screen`, `section`, `bullet`, `numbered`, `pending_list`, `HELP`), sin armar strings en los manejadores; los usos
incorrectos y los errores de los comandos salen como «Aviso · …». `/pendientes` es UN mensaje: «Pendientes (N)» en negrita, lista numerada
(máx. 10; «y N más: filtra por área (/pendientes nombre)») con título · área · `fecha_corta`, y un botón por número (los números van de
a 5 por fila: excepción a la regla de 2, la prueba del catálogo la admite solo para dígitos). Pulsar un número muestra la tarea en el MISMO
mensaje con [Hecha] [Descartar] / [Volver]; tras Hecha o Descartar vuelve a la lista ya actualizada con una línea de estado
(«Hecha · título»). Los ids no guardan estado en memoria (`pd:VERBO:ÁREA[:TAREA]`: abrir, hecha, descartar, volver), así que sobreviven a un
reinicio y conservan el filtro de área. Una tarea que ya no está abierta (cerrada desde otro lado, doble Hecha) responde con el aviso breve
«Esa opción ya no aplica» Y refresca la lista para que desaparezca; un id mal formado solo responde el aviso. `/hoy`: «Hoy · sábado 3 de
octubre» (+ área), secciones en negrita «Tareas» y «Recordatorios» con `fecha_corta` (las vencidas con «vencida»), estado vacío cuidado y la
línea «N en bandeja sin área» solo sin filtro. `/recordatorios`: «Pendientes (n)» y, aparte, «Detenidos (m)» con «Motivo: …» en lenguaje
claro; un código desconocido sale como «motivo desconocido» y el crudo solo al log. `/areas` marca «sin descripción»; `/ayuda` está agrupada
(Anotar, Consultar, Áreas, Otros). Se quitaron `tk_done`/`tk_drop` (un mensaje por tarea).

## Cobertura del corte 3
Se compararon las 30 pruebas quitadas de `test_commands.py` con `test_vistas.py` (`docs/COBERTURA_CORTE3.md`). Huecos reales cerrados: aviso a las 00:00 exactas en /hoy, escape de texto en /hoy y /recordatorios, y privacidad en logs de los botones de /pendientes. Las pruebas de uso de /tarea, /nota y /nuevaarea solo verifican el prefijo «Aviso · Escribe /comando», no el ejemplo completo (decisión: el ejemplo cambia a menudo).

## Kit de despliegue: unidad systemd
`deploy/asistente.service` usa `EnvironmentFile` (lo pidió el dueño) con marcadores `<USUARIO>` y `<RUTA_PROYECTO>`. Como systemd no quita comentarios al final de línea, el `.env.example` los lleva en líneas propias y una prueba lo vigila. `.gitattributes` fuerza LF en `*.sh`, `*.service` y `*.sql`; `git add --renormalize .` no cambió nada (el índice ya era LF).

## Kit de despliegue: respaldo
`scripts/backup_db.py` usa `Connection.backup` (copia consistente aunque el bot escriba; abre la base en solo lectura y nunca crea una vacía), copia a un `.tmp`, verifica `PRAGMA integrity_check` y solo entonces lo mueve a `asistente-AAAA-MM-DD.db` con `os.replace` (un respaldo bueno nunca se pisa con uno malo). Retención: se borran los de 14 días o más (se conservan hoy y los 13 anteriores = 14 archivos); solo se poda si el respaldo salió bien y solo nombres con ese patrón exacto. La fecha es la del sistema (hora local de la Pi). Para respaldar fuera de la SD, `--dir`. Es la única excepción a «nada se borra»: son copias, no datos del usuario; requiere tu visto bueno.

## Kit de despliegue: check_env
`scripts/check_env.py`: cada punto imprime `OK`, `AVISO` o `FALLA` y solo `FALLA` da código 1. Nunca imprime valores: las variables se nombran y los mensajes de `ConfigError` se recortan a su primer token (el nombre). El reloj es AVISO (no FALLA) porque no hay forma segura sin red de saber la hora real: se avisa si la fecha es anterior a la de esta versión (`MIN_PLAUSIBLE_UTC`, 2026-10-01, hay que subirla de vez en cuando), si va detrás de la última migración registrada en la base, o si `timedatectl` dice que NTP no está sincronizado (en Windows no se sabe y no avisa). La base se prueba creando un archivo temporal anónimo en la carpeta existente más cercana; no crea carpetas. Un paquete en otra versión que la fijada es AVISO, uno ausente es FALLA.

## Kit de despliegue: /estado y BOT_ENV
`/estado` solo lee: `RuntimeStatus` (entorno, base, hora de arranque, hora del último tick) vive en memoria y el motor la actualiza al inicio de cada tick (también cuando el canal está en espera); la base solo se consulta (SELECT) para pendientes, detenidos, `MAX(last_fired_at)`, `MAX(version)` de migraciones y el tamaño del archivo (+ `-wal`). Nada del usuario (textos, áreas, títulos) aparece ni va al log. `BOT_ENV` es `dev` o `prod` (por defecto `dev`; otro valor es error de configuración); no cambia el comportamiento, solo se muestra. `core/runtime.py` no importa `core/reminders.py` (el motor lo importa solo para el tipo, bajo `TYPE_CHECKING`). `formato.py` sigue sin importar `core/`: el armado de la pantalla está en `commands.status`. Se añadió `/estado` a `/ayuda` (grupo Otros).

## Kit de despliegue: README
El README asume Raspberry Pi OS Bookworm (Python 3.11) y el usuario `pi`; los ejemplos usan `/home/pi/WhiteRoom`. Restaurar mueve la base y sus `-wal`/`-shm` a `data/descartado/` (no se borra nada) antes de copiar el respaldo. La checklist de aceptación en la Pi es manual y NO se ha ejecutado: no hay Pi disponible en esta sesión.

## Auditoría de deriva
`docs/AUDITORIA.md` compara SPEC y código sin arreglar nada. La mayoría de las 13 discrepancias se resuelven editando el SPEC; la única decisión de diseño pendiente es la 10 (cómo será «¿Quitas alguna?» en la Fase 3).

## Bug de los botones (TypeError) y pruebas con la librería real
Causa: en 2d (`/estado`) añadí `runtime` al diccionario `wiring` de `main._handlers`, que alimenta DOS funciones (`handle_message` y `handle_choice`), pero solo le di el parámetro a la primera. Los falsos llamaban a los manejadores directo (sin `main`) y el dry-run solo probaba mensajes, así que nada lo vio. Arreglo: `handle_choice` acepta `runtime`. Diagnóstico permanente: `describe_error` registra tipo y las últimas 5 líneas `archivo:línea en función` (sin mensaje, argumentos ni rutas). Regla nueva en CLAUDE.md: los cambios en canales o callbacks se prueban también con `Update.de_json`. `main._handlers` acepta `conversation` y `TelegramChannel` separó `_register_handlers` de `run_polling` solo para poder probarlos.

## Respaldo: retención con mínimo
La poda corre SOLO después de un respaldo nuevo creado y verificado. Se borran los de 14 días o más, pero siempre quedan los 7 más recientes (el último entre ellos): tras un mes sin respaldar no se vacía la carpeta. Si el respaldo falla (base ausente, copia dañada) no se borra nada y el código es distinto de 0; si lo único que falla es la poda, el respaldo queda hecho y el código también es distinto de 0, con el mensaje «el respaldo está hecho, pero no se pudo podar».

## check_env: reloj, UTF-8 y unidad
El reloj sigue siendo AVISO. Señales, en orden de peso: `timedatectl show -p NTPSynchronized --value` (si existe), la fecha del último commit (`git log -1 --format=%ct`, si hay git: el reloj no puede ir más de 5 min detrás de ella; en una Pi recién clonada con el reloj mal el commit sigue siendo del pasado real, así que lo detecta) y la última migración de la base. `MIN_PLAUSIBLE_UTC` queda solo como piso. `asistente/textio.force_utf8_output()` fuerza UTF-8 en stdout y stderr de `check_env.py` y `backup_db.py` (en Windows cp1252 deformaba los acentos). La unidad systemd añade `time-sync.target` a After y Wants con el comentario «verificar en la Pi»: no pude comprobar en una Pi real que ese target exista y se alcance en Raspberry Pi OS (con systemd-timesyncd suele existir; sin un servicio de hora que lo active, no espera nada).

## Etiquetas para la Fase 2 (sin IA)
Al completarse una tarjeta de captura se inserta en `classification_log` una fila `source='user'` (`core/classification.py`): texto normalizado (minúsculas, sin acentos, sin números, espacios colapsados; para recordatorios y fechas límite, el título ya sin la fecha), `final_kind` (task, reminder, note), `final_area` (NOMBRE del área o NULL) y `user_corrected=1` si el tipo final difiere del primero que tuvo el flujo (`Flow.first_kind`: p. ej. recordatorio detectado por el verbo y luego «Mejor como tarea», o «Cambiar» y terminar como tarea). Sin predicciones ni latencia (no hay clasificador). Puntos de registro: tarea, nota, recordatorio creado, tarea con fecha límite y «Mejor como tarea»; NO se registra al cancelar, abandonar, Deshacer ni /nuevaarea. «Cambiar» y volver a guardar añade una fila nueva (es otra decisión). Es auxiliar: si la inserción falla, la captura sigue y solo se registra el tipo del error (nunca el texto). No hay migración (la tabla ya existía).

## Auditoría: cambios aplicados al SPEC
Donde el código es lo querido se editó el SPEC: botones con am/pm (`Mañana 9:00 am`, `Hoy 9:00 am`) y excepción de los números de 5 en 5 en /pendientes (§3.1, §8.3); aviso de recordatorio con `Recordatorio · área` (§8.3); la captura como tarjeta (§8.1 paso 5); `TICK_SECONDS` (§6 y §8.3); `(retrasado)` también con más de 2 minutos de atraso (§8.3); la unidad con `Wants` y `time-sync.target` (§13); `--dry-run` sin clasificadores hasta la Fase 2 (§10); y el árbol de carpetas (§5: `textio.py`, `bot/commands.py`, `inbox.py`, `conversation.py`, `ui.py`, `core/areas.py`, `settings.py`, `runtime.py`, `classification.py` y los scripts nuevos). NO se tocó: la discrepancia 7 (¿`core/capture.py` o `bot/inbox.py`?) y la 10 («¿Quitas alguna?» de la Fase 3): quedan en `docs/PREGUNTAS.md`.

## Hook de pre-commit
`.githooks/pre-commit` (sh, LF forzado en `.gitattributes`) corre `pytest -q` y `ruff check .` midiendo cada código de salida por separado y bloquea el commit si alguno es distinto de 0; también bloquea si no encuentra el venv. `scripts/install_hooks.py` solo hace `git config core.hooksPath .githooks` en el repositorio LOCAL (nunca la configuración global). Tarda unos 110 s (la suite): más de los 60 s que se pidió vigilar, así que NO está activado en este clon; decide el dueño. Incidente: mis mutaciones del instalador (I4 e I5) escribieron una vez en la configuración real (global y de este repositorio); lo deshice y `tests/test_hooks.py` ahora aísla `GIT_CONFIG_GLOBAL` y comprueba al terminar que el repositorio real no cambió.

## classification_log.capture_id (migración 005)
El siguiente número libre era el 005 (`005_classification_capture_id.sql`): `capture_id INTEGER REFERENCES tasks(id)` más un índice ÚNICO. El 7c necesitará otra migración (`stop_notified_at`), que pasa a ser la **006** (ya anotado en SPEC y STATUS). El enlace es la tarea de bandeja de la captura; decidir otra vez la misma captura («Cambiar») hace UPSERT de su fila con `user_corrected = 1` (aunque el tipo no cambie: el dueño rehízo su decisión), y una vez en 1 no vuelve a 0. Las filas anteriores a la migración quedan con `capture_id` NULL y cuentan una a una. «Deshacer» no borra la fila (la decisión se tomó). `scripts/eval_classifier.py` (nuevo; el SPEC lo describía pero no existía) resume lo etiquetado por el dueño, una por captura, abriendo la base en solo lectura; la comparación de clasificadores queda para la Fase 2. Esto cambia lo que decía mi entrega anterior («Cambiar» añade una fila nueva).
