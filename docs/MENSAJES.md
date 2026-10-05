# Catálogo de mensajes

Generado por `python scripts/show_messages.py` con los manejadores reales, una base en memoria
y un reloj fijo: **sábado 3 de octubre de 2026, 3:30 pm** (México). Las áreas son las iniciales
(Universidad, Proyectos, Iglesia, Personal). Los textos se muestran como los recibe Telegram:
HTML con solo `<b>`, `<i>` y `<code>` (la consola quita las etiquetas). Cada fila de botones
va en una línea, como `[Etiqueta]`; `---` separa mensajes distintos de una misma respuesta.
«(edita el mismo mensaje)» es una edición: la captura es UN solo mensaje (la tarjeta) que cambia
de texto y de botones en cada paso; una edición sin botones lo deja como constancia final.
No incluye la salida de `scripts/dev_remind_me.py` ni los errores de configuración del arranque.

## Bandeja (mensaje libre)

Cualquier texto que no es un comando se guarda al instante como tarea sin área y se pregunta qué es.

_Mensaje libre: pregunta de tipo._

```text
<b>¿Qué es?</b>

Comprar leche
[Tarea][Recordatorio]
[Nota][Cancelar]
```

_Se elige Tarea: la tarjeta se edita y pasa a la pregunta de área, con el tipo ya elegido._

```text
(edita el mismo mensaje)
<b>¿En qué área va?</b>

Comprar leche

Tipo: Tarea
[Universidad][Proyectos]
[Iglesia][Personal]
[Sin área][Cancelar]
```

_Se elige un área: la misma tarjeta queda como constancia._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

Comprar leche

Área: Personal
```

_Cancelar en cualquier pregunta: la tarea sigue en la bandeja._

```text
(edita el mismo mensaje)
<b>Cancelado</b>

Comprar leche

Sigue en tu bandeja como tarea.
```

_Nota guardada con su área._

```text
(edita el mismo mensaje)
<b>Nota guardada</b>

La clave del wifi es larga

Área: Universidad
```

_Sin áreas disponibles no se pregunta el área._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

Comprar leche
```

_Recordatorio con fecha clara: edición del área y confirmación con Cambiar/Deshacer._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

Llevar tarea

Cuándo: domingo 4 de octubre, 8:00 am
Área: Universidad
[Cambiar][Deshacer]
```

_Deshacer: el recordatorio se cancela y la tarea vuelve a la bandeja._

```text
(edita el mismo mensaje)
<b>Deshecho</b> · Llevar tarea · vuelve a tu bandeja como tarea
```

_Cambiar: se deshace y se vuelve a preguntar la fecha._

```text
(edita el mismo mensaje)
<b>¿Cuándo?</b>

Llevar tarea

Tipo: Recordatorio
Área: Universidad

Pulsa una opción o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5".
[Hoy 6:00 pm][Mañana 9:00 am]
[Mejor como tarea][Cancelar]
```

_Se responde la fecha escribiéndola._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

Llevar tarea

Cuándo: lunes 5 de octubre, 10:00 am
Área: Universidad
[Cambiar][Deshacer]
```

_Fecha sin hora: la confirmación avisa de la hora por defecto._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

Llevar tarea

Cuándo: domingo 4 de octubre, 9:00 am (hora por defecto)
[Cambiar][Deshacer]
```

_Repetición: vista previa con la próxima fecha, sin guardar todavía._

```text
(edita el mismo mensaje)
<b>¿Guardo esta repetición?</b>

Regar plantas

Repetición: Cada lunes
Próxima: lunes 5 de octubre, 7:00 pm
[Guardar][Cancelar]
```

_Guardar la repetición: confirmación._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

Regar plantas

Repetición: Cada lunes
Próxima: lunes 5 de octubre, 7:00 pm
[Cambiar][Deshacer]
```

_Un texto que empieza por «recordar/recuérdame» salta la pregunta de tipo._

```text
<b>¿En qué área va?</b>

Recuérdame llamar a mamá

Tipo: Recordatorio
[Universidad][Proyectos]
[Iglesia][Personal]
[Sin área][Cancelar]
```

_Sin fecha: pregunta ¿cuándo? con opciones rápidas y «Mejor como tarea»._

```text
(edita el mismo mensaje)
<b>¿Cuándo?</b>

Llamar a mamá

Tipo: Recordatorio

Pulsa una opción o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5".
[Hoy 6:00 pm][Mañana 9:00 am]
[Mejor como tarea][Cancelar]
```

_Se elige una opción rápida: confirmación._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

Llamar a mamá

Cuándo: domingo 4 de octubre, 9:00 am
[Cambiar][Deshacer]
```

_Mejor como tarea: queda como tarea con el área ya elegida, sin recordatorio._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

Llamar al dentista

Área: Iglesia
```

_En ¿cuándo?, un texto que no es fecha es una captura nueva: la tarjeta vieja queda «Sin terminar» y se abre otra._

```text
(edita el mismo mensaje)
<b>Sin terminar</b>

Llamar al dentista

Sigue en tu bandeja como tarea.
---
<b>¿Qué es?</b>

Comprar leche
[Tarea][Recordatorio]
[Nota][Cancelar]
```

_Botón de una pregunta vieja: se ignora._

```text
(edita el mismo mensaje)
<b>Aviso</b> · Esa opción ya no está disponible.
```

_La opción «Hoy 6:00 pm» se pulsó cuando ya había pasado._

```text
(edita el mismo mensaje)
<b>¿Cuándo?</b>

Llamar al dentista

Tipo: Recordatorio

Esa hora ya pasó. Pulsa una opción o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5".
[Mañana 9:00 am]
[Mejor como tarea][Cancelar]
```


## Preguntas del parser de fechas (recordatorios)

Se llega con «Recordatorio» y un área; aquí se muestra solo la pregunta que sale.

_Hora o cita bíblica (time_or_verse)._

```text
(edita el mismo mensaje)
<b>¿Eso es una hora o una cita bíblica?</b>

Llamar a Juan 3:30

Tipo: Recordatorio
[Es una cita]
[Otra fecha][Cancelar]
```

_Persona o día (name_or_day)._

```text
(edita el mismo mensaje)
<b>¿«Domingo» es una persona o el día de la semana?</b>

Llamar a Domingo

Tipo: Recordatorio
[Es un nombre]
[Otra fecha][Cancelar]
```

_Hora con punto (dotted_time)._

```text
(edita el mismo mensaje)
<b>¿Es una hora? Escríbela con dos puntos (por ejemplo 7:30).</b>

7.30 dentista

Tipo: Recordatorio
[Otra fecha][Cancelar]
```

_Número pegado al día (number_after_day)._

```text
(edita el mismo mensaje)
<b>¿Ese número es la hora o forma parte del texto? Escribe la hora completa.</b>

7 dentista

Tipo: Recordatorio
[Otra fecha][Cancelar]
```

_Fecha que no entiende (unsupported_date): opciones rápidas._

```text
(edita el mismo mensaje)
<b>No entiendo esa fecha. ¿Qué día quieres?</b>

Pagar renta

Tipo: Recordatorio
[Hoy 6:00 pm][Mañana 9:00 am]
[Otra fecha][Cancelar]
```

_Repetición que no sabe hacer (unrecognized_recurrence)._

```text
(edita el mismo mensaje)
<b>Esa repetición no está entre las que sé hacer (todos los días, cada lunes, de lunes a viernes).</b>

Cada mes pagar renta

Tipo: Recordatorio
[Solo una vez…]
[Otra fecha][Cancelar]
```

_Medianoche dudosa (ambiguous_time)._

```text
(edita el mismo mensaje)
<b>¿Medianoche de qué día?</b>

Cena

Tipo: Recordatorio
[mañana, 12:00 am][lun 5 oct, 12:00 am]
[Otra fecha][Cancelar]
```

_Hora dudosa, dos lecturas (ambiguous_meridiem)._

```text
(edita el mismo mensaje)
<b>¿A las 9 am o pm?</b>

Llevar tarea

Tipo: Recordatorio
[mañana, 9:00 am][mañana, 9:00 pm]
[Otra fecha][Cancelar]
```

_Hora dudosa, un solo candidato futuro (ambiguous_meridiem)._

```text
(edita el mismo mensaje)
<b>¿A las 8:00 pm?</b>

Llevar tarea

Tipo: Recordatorio
[hoy, 8:00 pm]
[Otra fecha][Cancelar]
```

_Hora que ya pasó, con alternativa (past)._

```text
(edita el mismo mensaje)
<b>Esa fecha ya pasó. ¿La dejo para domingo 4 de octubre, 10:00 am?</b>

Llevar tarea

Tipo: Recordatorio
[mañana, 10:00 am]
[Otra fecha][Cancelar]
```

_Día igual al de hoy (same_weekday)._

```text
(edita el mismo mensaje)
<b>Hoy es ese día: ¿hoy o en 7 días?</b>

Llamar

Tipo: Recordatorio
[sáb 10 oct, 9:00 am]
[Otra fecha][Cancelar]
```

_Pasada la medianoche, «mañana» dudoso (today_or_tomorrow)._

```text
(edita el mismo mensaje)
<b>Ya pasó la medianoche: ¿«mañana» es hoy o mañana?</b>

Llevar tarea

Tipo: Recordatorio
[hoy, 8:00 am][mañana, 8:00 am]
[Otra fecha][Cancelar]
```

_Cualquier otra duda (texto genérico)._

```text
(edita el mismo mensaje)
<b>No pude entender la fecha o la hora; escríbela de otra forma.</b>

Por la mañana llevar tarea

Tipo: Recordatorio
[Otra fecha][Cancelar]
```


## Aviso de recordatorio y sus botones

Lo que sale cuando el motor envía un recordatorio (tipo de envío `reminder`).

_Aviso a su hora, con el área entre corchetes._

```text
<b>Llevar tarea</b>

Recordatorio · Universidad
[Hecho][+10 min]
[+1 h][Mañana 9:00 am]
```

_Hecho._

```text
(edita el mismo mensaje)
<b>Hecho</b> · Llevar tarea
```

_+10 min: se reprograma para hoy._

```text
(edita el mismo mensaje)
<b>Pospuesto</b> · Llamar a mamá · hoy, 3:41 pm
```

_Mañana 9:00 am: se reprograma para el día siguiente (día completo en la confirmación)._

```text
(edita el mismo mensaje)
<b>Pospuesto</b> · Llamar a mamá · domingo 4 de octubre, 9:00 am
```

_Pulsar otra vez un botón de un aviso que ya no está activo._

```text
(edita el mismo mensaje)
<b>Hecho</b> · Llamar a mamá
```

_Botón de un recordatorio que no existe._

```text
(edita el mismo mensaje)
<b>Aviso</b> · Este recordatorio ya no está activo.
```

_Aviso que salió tarde (caída, silencio o canal caído): «(retrasado)»._

```text
<b>Llamar a mamá</b>

Recordatorio <i>(retrasado)</i>
[Hecho][+10 min]
[+1 h][Mañana 9:00 am]
```

_De madrugada (antes de las 5:00) el botón dice «Hoy 9:00 am» en lugar de «Mañana 9:00 am»._

```text
<b>Revisar el horno</b>

Recordatorio
[Hecho][+10 min]
[+1 h][Hoy 9:00 am]
```

_Aviso de preparación, un día antes de la fecha de una tarea._

```text
<b>Mañana vence: entregar proyecto</b>

Recordatorio · Universidad
[Hecho][+10 min]
[+1 h][Mañana 9:00 am]
```

_Aviso de preparación, una hora antes._

```text
<b>En 1 hora vence: entregar proyecto</b>

Recordatorio · Universidad
[Hecho][+10 min]
[+1 h][Mañana 9:00 am]
```


## /hoy [área]

_Sin nada para hoy: estado vacío._

```text
<b>Hoy · sábado 3 de octubre</b>

Nada para hoy: no hay tareas que venzan ni recordatorios.
```

_Sin nada para hoy, pero con tareas en la bandeja._

```text
<b>Hoy · sábado 3 de octubre</b>

Nada para hoy: no hay tareas que venzan ni recordatorios.

1 en bandeja sin área
```

_Con secciones, tareas vencidas y de hoy, recordatorios de hoy y la línea de bandeja._

```text
<b>Hoy · sábado 3 de octubre</b>

<b>Tareas</b>
- Pagar luz · vencida vie 2 oct, 5:00 pm
- Entregar informe · hoy, 5:00 pm · Universidad

<b>Recordatorios</b>
- hoy, 6:00 pm · Llamar a mamá

2 en bandeja sin área
```

_Filtrado por área (sin la línea de bandeja)._

```text
<b>Hoy · sábado 3 de octubre · Universidad</b>

<b>Tareas</b>
- Entregar informe · hoy, 5:00 pm
```

_Área que no existe._

```text
<b>Aviso</b> · No encuentro el área «inventada». Escribe /areas para ver las que hay.
```


## /pendientes [área]

Un solo mensaje: lista numerada y un botón por número; el mismo mensaje muestra la tarea elegida y vuelve a la lista.

_Sin tareas._

```text
<b>Pendientes (0)</b>

No tienes tareas pendientes. Todo al día.
```

_Lista numerada con un botón por número._

```text
<b>Pendientes (4)</b>

1. Pagar luz · vie 2 oct, 5:00 pm
2. Entregar informe · Universidad · hoy, 5:00 pm
3. Regar plantas · Personal · mañana, 9:00 am
4. Comprar pan
[1][2][3][4]
```

_Se pulsa un número: la tarea en el mismo mensaje._

```text
(edita el mismo mensaje)
<b>Pagar luz</b>

Vence: vie 2 oct, 5:00 pm

¿Qué hago con esta tarea?
[Hecha][Descartar]
[Volver]
```

_Hecha: vuelve a la lista actualizada._

```text
(edita el mismo mensaje)
<b>Pendientes (3)</b>

1. Entregar informe · Universidad · hoy, 5:00 pm
2. Regar plantas · Personal · mañana, 9:00 am
3. Comprar pan

<b>Hecha</b> · Pagar luz
[1][2][3]
```

_Otra tarea, Descartar._

```text
(edita el mismo mensaje)
<b>Regar plantas</b>

Área: Personal
Vence: mañana, 9:00 am

¿Qué hago con esta tarea?
[Hecha][Descartar]
[Volver]
```

_Descartar: vuelve a la lista actualizada._

```text
(edita el mismo mensaje)
<b>Pendientes (2)</b>

1. Entregar informe · Universidad · hoy, 5:00 pm
2. Comprar pan

<b>Descartada</b> · Regar plantas
[1][2]
```

_Volver sin hacer nada._

```text
(edita el mismo mensaje)
<b>Entregar informe</b>

Área: Universidad
Vence: hoy, 5:00 pm

¿Qué hago con esta tarea?
[Hecha][Descartar]
[Volver]
---
(edita el mismo mensaje)
<b>Pendientes (2)</b>

1. Entregar informe · Universidad · hoy, 5:00 pm
2. Comprar pan
[1][2]
```

_Botón de una tarea que ya no está abierta: aviso breve y la lista se actualiza._

```text
(edita el mismo mensaje)
<b>Pendientes (0)</b>

No tienes tareas pendientes. Todo al día.
```

_Filtrado por área._

```text
<b>Pendientes · Universidad (1)</b>

1. Entregar informe · hoy, 5:00 pm
[1]
```

_Más de 10 tareas: se muestran 10 y se dice cuántas faltan._

```text
<b>Pendientes (13)</b>

1. Tarea 1
2. Tarea 2
3. Tarea 3
4. Tarea 4
5. Tarea 5
6. Tarea 6
7. Tarea 7
8. Tarea 8
9. Tarea 9
10. Tarea 10

y 3 más: filtra por área (/pendientes nombre)
[1][2][3][4][5]
[6][7][8][9][10]
```


## /recordatorios

_Sin recordatorios pendientes._

```text
<b>Recordatorios</b>

No tienes recordatorios pendientes.
```

_Lista de pendientes, con área y repetición._

```text
<b>Recordatorios</b>

<b>Pendientes (3)</b>
- hoy, 6:00 pm · Llamar a mamá
- mañana, 8:00 am · Llevar tarea · Universidad
- mañana, 10:00 am · Ir a la iglesia · Iglesia · Cada domingo
```

_Con detenidos: motivo conocido y motivo desconocido._

```text
<b>Recordatorios</b>

<b>Pendientes (1)</b>
- mañana, 10:00 am · Ir a la iglesia · Iglesia · Cada domingo

<b>Detenidos (2)</b>
- hoy, 6:00 pm · Llamar a mamá · Motivo: el bot está bloqueado en tu chat
- mañana, 8:00 am · Llevar tarea · Universidad · Motivo: motivo desconocido
```

_Todos los motivos de detención que se explican._

```text
<b>Recordatorios</b>

<b>Pendientes (1)</b>
- mañana, 10:00 am · Ir a la iglesia · Iglesia · Cada domingo

<b>Detenidos (11)</b>
- hoy, 6:00 pm · Llamar a mamá · Motivo: el bot está bloqueado en tu chat
- mañana, 8:00 am · Llevar tarea · Universidad · Motivo: motivo desconocido
- lun 5 oct, 8:00 am · Permanent:chat_not_found · Motivo: no se encontró tu chat
- lun 5 oct, 8:00 am · Permanent:message_too_long · Motivo: el mensaje era demasiado largo
- lun 5 oct, 8:00 am · Permanent:bad_request:cant_parse_entities · Motivo: Telegram no pudo leer el formato del texto
- lun 5 oct, 8:00 am · Permanent:bad_request:empty_text · Motivo: el texto estaba vacío
- lun 5 oct, 8:00 am · Permanent:bad_request:button_data_invalid · Motivo: un botón no era válido
- lun 5 oct, 8:00 am · Permanent:bad_request:other · Motivo: Telegram rechazó el mensaje
- lun 5 oct, 8:00 am · Horizon:telegram_down · Motivo: Telegram no respondió durante 24 horas
- lun 5 oct, 8:00 am · Legacy · Motivo: se detuvo en una versión anterior
- lun 5 oct, 8:00 am · permanent:unexpected:KeyError · Motivo: error inesperado al enviar
```


## /recordar

_Sin texto._

```text
<b>Aviso</b> · Escribe /recordar seguido de qué y cuándo, por ejemplo: /recordar mañana 8 am llevar tarea
```

_Con texto: se guarda en la bandeja y pregunta el área._

```text
<b>¿En qué área va?</b>

Mañana 8am llevar tarea

Tipo: Recordatorio
[Universidad][Proyectos]
[Iglesia][Personal]
[Sin área][Cancelar]
```

_Vista previa antes de guardar._

```text
(edita el mismo mensaje)
<b>¿Guardo este recordatorio?</b>

Llevar tarea

Cuándo: domingo 4 de octubre, 8:00 am
Área: Universidad
[Guardar][Cancelar]
```

_Guardar: confirmación._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

Llevar tarea

Cuándo: domingo 4 de octubre, 8:00 am
Área: Universidad
[Cambiar][Deshacer]
```

_Con repetición: vista previa con la próxima fecha._

```text
(edita el mismo mensaje)
<b>¿Guardo esta repetición?</b>

Regar plantas

Repetición: Cada lunes
Próxima: lunes 5 de octubre, 7:00 pm
[Guardar][Cancelar]
```

_Con una duda del parser: se elige el candidato y luego se muestra la vista previa._

```text
(edita el mismo mensaje)
<b>¿Guardo este recordatorio?</b>

Llevar tarea

Cuándo: domingo 4 de octubre, 9:00 pm
[Guardar][Cancelar]
```


## /tarea

_Sin texto._

```text
<b>Aviso</b> · Escribe /tarea seguido de la tarea, por ejemplo: /tarea comprar pan
```

_Con texto: pregunta solo el área._

```text
<b>¿En qué área va?</b>

Comprar pan

Tipo: Tarea
[Universidad][Proyectos]
[Iglesia][Personal]
[Sin área][Cancelar]
```

_Área elegida._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

Comprar pan

Área: Personal
```

_Con una fecha clara en el texto: pregunta si es la fecha límite._

```text
(edita el mismo mensaje)
<b>¿Es la fecha límite?</b>

Entregar informe

Tipo: Tarea
Área: Universidad
Fecha: viernes 9 de octubre, 9:00 am (hora por defecto)
[Sí][No]
[Cancelar]
```

_Sí: título sin la fecha, con fecha de vencimiento._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

Entregar informe

Área: Universidad
Vence: viernes 9 de octubre, 9:00 am (hora por defecto)
```

_No: queda con el texto completo y sin fecha._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

Entregar informe el viernes

Área: Universidad
```


## /nota

_Sin texto._

```text
<b>Aviso</b> · Escribe /nota seguido de la nota, por ejemplo: /nota la clave del wifi está en el router
```

_Con texto: pregunta solo el área._

```text
<b>¿En qué área va?</b>

La clave del wifi

Tipo: Nota
[Universidad][Proyectos]
[Iglesia][Personal]
[Sin área][Cancelar]
```

_Área elegida._

```text
(edita el mismo mensaje)
<b>Nota guardada</b>

La clave del wifi

Área: Personal
```


## /areas y /nuevaarea

_Lista de áreas._

```text
<b>Áreas (4)</b>

- Universidad
- Proyectos
- Iglesia
- Personal
```

_Un área sin descripción se marca._

```text
<b>Áreas (5)</b>

- Universidad
- Proyectos
- Iglesia
- Personal
- Salud · sin descripción
```

_Sin áreas._

```text
<b>Áreas</b>

No hay áreas. Crea una con /nuevaarea nombre.
```

_/nuevaarea sin nombre._

```text
<b>Aviso</b> · Escribe /nuevaarea seguido del nombre, por ejemplo: /nuevaarea Salud
```

_Con nombre: pregunta la descripción._

```text
<b>¿Qué cubre «Salud»?</b>

Escribe una descripción corta u omítela.
[Omitir][Cancelar]
```

_Se escribe la descripción._

```text
(edita el mismo mensaje)
<b>Área guardada</b>

Salud

Ejercicio y citas médicas
```

_Omitir: el área queda sin descripción._

```text
(edita el mismo mensaje)
<b>Área guardada</b>

Deportes

Sin descripción.
```

_Cancelar._

```text
(edita el mismo mensaje)
<b>Cancelado</b>

Viajes

No se creó el área.
```

_Nombre repetido (sin distinguir mayúsculas ni acentos)._

```text
<b>Aviso</b> · Ya existe un área llamada «Universidad».
```

_Nombre demasiado largo._

```text
<b>Aviso</b> · El nombre es demasiado largo (máximo 40 caracteres).
```


## /start y /ayuda

_/start._

```text
<b>Hola, soy tu asistente personal</b>

Escribe lo que quieras anotar y te pregunto qué es. /ayuda muestra los comandos.
```

_/ayuda._

```text
<b>Ayuda</b>

<b>Anotar</b>
Escribe cualquier mensaje: lo guardo en tu bandeja y te pregunto qué es.
/tarea texto · guardar una tarea
/nota texto · guardar una nota
/recordar texto · crear un recordatorio con su fecha

<b>Consultar</b>
/hoy [área] · lo que vence hoy
/pendientes [área] · tus tareas abiertas
/recordatorios · avisos pendientes y detenidos

<b>Áreas</b>
/areas · ver las áreas
/nuevaarea nombre · crear un área

<b>Otros</b>
/estado · estado del bot
/start · saludo
/ayuda · esta lista
```


## /estado

Solo el dueño. Sin textos del usuario; el último ciclo vive en memoria.

_Recién arrancado, sin ciclos ni avisos._

```text
<b>Estado</b>

Entorno: dev
Arrancó: hoy, 1:25 pm
Encendido: 2 h 5 min
Último ciclo: todavía ninguno
Último aviso enviado: ninguno todavía
Recordatorios: 0 pendientes · 0 detenidos
Esquema: versión 6
Base de datos: no disponible
```

_Con un aviso ya enviado, un ciclo reciente y un recordatorio pendiente._

```text
<b>Estado</b>

Entorno: dev
Arrancó: hoy, 1:25 pm
Encendido: 2 h 7 min
Último ciclo: hace 12 s
Último aviso enviado: hoy, 3:32 pm
Recordatorios: 1 pendiente · 0 detenidos
Esquema: versión 6
Base de datos: no disponible
```


## Errores y avisos generales

_Comando desconocido._

```text
<b>Aviso</b> · No conozco ese comando. Escribe /ayuda para ver los disponibles.
```

_Botón desconocido o mal formado._

```text
<b>Aviso</b> · Esa opción ya no está disponible.
```

_Botón de la bandeja de un flujo que ya no existe._

```text
(edita el mismo mensaje)
<b>Aviso</b> · Esa opción ya no está disponible.
```

_Botón de /pendientes con una tarea que no existe._

```text
(edita el mismo mensaje)
<b>Pendientes (0)</b>

No tienes tareas pendientes. Todo al día.
```

_Deshacer/Cambiar cuando el recordatorio ya no está pendiente._

```text
(edita el mismo mensaje)
<b>Aviso</b> · Ya no se puede deshacer ni cambiar: ese recordatorio ya no está pendiente.
```

_Botón de un paso viejo sobre la tarjeta viva: solo un aviso breve; la pregunta sigue como estaba._

```text
(aviso breve emergente; no crea ni edita mensajes)
Esa opción ya no aplica
```

_Un comando a mitad de otra pregunta no la descarta; otro flujo nuevo sí, y avisa._

```text
(edita el mismo mensaje)
<b>Sin terminar</b>

Deportes

No se creó el área.
---
<b>¿En qué área va?</b>

Sacar copias

Tipo: Tarea
[Universidad][Proyectos]
[Iglesia][Personal]
[Sin área][Cancelar]
```
