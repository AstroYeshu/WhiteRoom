# Catálogo de mensajes

Generado por `python scripts/show_messages.py` con los manejadores reales, una base en memoria
y un reloj fijo: **sábado 3 de octubre de 2026, 3:30 pm** (México). Las áreas son las iniciales
(universidad, proyectos, iglesia, personal). Los textos se muestran como los recibe Telegram:
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

comprar leche
[Tarea][Recordatorio]
[Nota][Cancelar]
```

_Se elige Tarea: la tarjeta se edita y pasa a la pregunta de área, con el tipo ya elegido._

```text
(edita el mismo mensaje)
<b>¿En qué área va?</b>

comprar leche

Tipo: Tarea
[universidad][proyectos]
[iglesia][personal]
[Sin área][Cancelar]
```

_Se elige un área: la misma tarjeta queda como constancia._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

comprar leche

Área: personal
```

_Cancelar en cualquier pregunta: la tarea sigue en la bandeja._

```text
(edita el mismo mensaje)
<b>Cancelado</b>

comprar leche

Sigue en tu bandeja como tarea.
```

_Nota guardada con su área._

```text
(edita el mismo mensaje)
<b>Nota guardada</b>

la clave del wifi es larga

Área: universidad
```

_Sin áreas disponibles no se pregunta el área._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

comprar leche
```

_Recordatorio con fecha clara: edición del área y confirmación con Cambiar/Deshacer._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

llevar tarea

Cuándo: domingo 4 de octubre, 8:00 am
Área: universidad
[Cambiar][Deshacer]
```

_Deshacer: el recordatorio se cancela y la tarea vuelve a la bandeja._

```text
(edita el mismo mensaje)
<b>Deshecho</b> · llevar tarea · vuelve a tu bandeja como tarea
```

_Cambiar: se deshace y se vuelve a preguntar la fecha._

```text
(edita el mismo mensaje)
<b>¿Cuándo?</b>

llevar tarea

Tipo: Recordatorio
Área: universidad

Pulsa una opción o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5".
[Hoy 6:00 pm][Mañana 9:00 am]
[Mejor como tarea][Cancelar]
```

_Se responde la fecha escribiéndola._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

llevar tarea

Cuándo: lunes 5 de octubre, 10:00 am
Área: universidad
[Cambiar][Deshacer]
```

_Fecha sin hora: la confirmación avisa de la hora por defecto._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

llevar tarea

Cuándo: domingo 4 de octubre, 9:00 am (hora por defecto)
[Cambiar][Deshacer]
```

_Repetición: vista previa con la próxima fecha, sin guardar todavía._

```text
(edita el mismo mensaje)
<b>¿Guardo esta repetición?</b>

regar plantas

Repetición: Cada lunes
Próxima: lunes 5 de octubre, 7:00 pm
[Guardar][Cancelar]
```

_Guardar la repetición: confirmación._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

regar plantas

Repetición: Cada lunes
Próxima: lunes 5 de octubre, 7:00 pm
[Cambiar][Deshacer]
```

_Un texto que empieza por «recordar/recuérdame» salta la pregunta de tipo._

```text
<b>¿En qué área va?</b>

recuérdame llamar a mamá

Tipo: Recordatorio
[universidad][proyectos]
[iglesia][personal]
[Sin área][Cancelar]
```

_Sin fecha: pregunta ¿cuándo? con opciones rápidas y «Mejor como tarea»._

```text
(edita el mismo mensaje)
<b>¿Cuándo?</b>

llamar a mamá

Tipo: Recordatorio

Pulsa una opción o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5".
[Hoy 6:00 pm][Mañana 9:00 am]
[Mejor como tarea][Cancelar]
```

_Se elige una opción rápida: confirmación._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

llamar a mamá

Cuándo: domingo 4 de octubre, 9:00 am
[Cambiar][Deshacer]
```

_Mejor como tarea: queda como tarea con el área ya elegida, sin recordatorio._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

llamar al dentista

Área: iglesia
```

_En ¿cuándo?, un texto que no es fecha es una captura nueva: la tarjeta vieja queda «Sin terminar» y se abre otra._

```text
(edita el mismo mensaje)
<b>Sin terminar</b>

llamar al dentista

Sigue en tu bandeja como tarea.
---
<b>¿Qué es?</b>

comprar leche
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

llamar al dentista

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

llamar a Juan 3:30

Tipo: Recordatorio
[Es una cita]
[Otra fecha][Cancelar]
```

_Persona o día (name_or_day)._

```text
(edita el mismo mensaje)
<b>¿«Domingo» es una persona o el día de la semana?</b>

llamar a Domingo

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

pagar renta

Tipo: Recordatorio
[Hoy 6:00 pm][Mañana 9:00 am]
[Otra fecha][Cancelar]
```

_Repetición que no sabe hacer (unrecognized_recurrence)._

```text
(edita el mismo mensaje)
<b>Esa repetición no está entre las que sé hacer (todos los días, cada lunes, de lunes a viernes).</b>

cada mes pagar renta

Tipo: Recordatorio
[Solo una vez…]
[Otra fecha][Cancelar]
```

_Medianoche dudosa (ambiguous_time)._

```text
(edita el mismo mensaje)
<b>¿Medianoche de qué día?</b>

cena

Tipo: Recordatorio
[mañana, 12:00 am][lun 5 oct, 12:00 am]
[Otra fecha][Cancelar]
```

_Hora dudosa, dos lecturas (ambiguous_meridiem)._

```text
(edita el mismo mensaje)
<b>¿A las 9 am o pm?</b>

llevar tarea

Tipo: Recordatorio
[mañana, 9:00 am][mañana, 9:00 pm]
[Otra fecha][Cancelar]
```

_Hora dudosa, un solo candidato futuro (ambiguous_meridiem)._

```text
(edita el mismo mensaje)
<b>¿A las 8:00 pm?</b>

llevar tarea

Tipo: Recordatorio
[hoy, 8:00 pm]
[Otra fecha][Cancelar]
```

_Hora que ya pasó, con alternativa (past)._

```text
(edita el mismo mensaje)
<b>Esa fecha ya pasó. ¿La dejo para domingo 4 de octubre, 10:00 am?</b>

llevar tarea

Tipo: Recordatorio
[mañana, 10:00 am]
[Otra fecha][Cancelar]
```

_Día igual al de hoy (same_weekday)._

```text
(edita el mismo mensaje)
<b>Hoy es ese día: ¿hoy o en 7 días?</b>

llamar

Tipo: Recordatorio
[sáb 10 oct, 9:00 am]
[Otra fecha][Cancelar]
```

_Pasada la medianoche, «mañana» dudoso (today_or_tomorrow)._

```text
(edita el mismo mensaje)
<b>Ya pasó la medianoche: ¿«mañana» es hoy o mañana?</b>

llevar tarea

Tipo: Recordatorio
[hoy, 8:00 am][mañana, 8:00 am]
[Otra fecha][Cancelar]
```

_Cualquier otra duda (texto genérico)._

```text
(edita el mismo mensaje)
<b>No pude entender la fecha o la hora; escríbela de otra forma.</b>

por la mañana llevar tarea

Tipo: Recordatorio
[Otra fecha][Cancelar]
```


## Aviso de recordatorio y sus botones

Lo que sale cuando el motor envía un recordatorio (tipo de envío `reminder`).

_Aviso a su hora, con el área entre corchetes._

```text
<b>llevar tarea</b>

Recordatorio · universidad
[Hecho][+10 min]
[+1 h][Mañana 9:00 am]
```

_Hecho._

```text
(edita el mismo mensaje)
<b>Hecho</b> · llevar tarea
```

_+10 min: se reprograma para hoy._

```text
(edita el mismo mensaje)
<b>Pospuesto</b> · llamar a mamá · hoy, 3:41 pm
```

_Mañana 9:00 am: se reprograma para el día siguiente (día completo en la confirmación)._

```text
(edita el mismo mensaje)
<b>Pospuesto</b> · llamar a mamá · domingo 4 de octubre, 9:00 am
```

_Pulsar otra vez un botón de un aviso que ya no está activo._

```text
(edita el mismo mensaje)
<b>Hecho</b> · llamar a mamá
```

_Botón de un recordatorio que no existe._

```text
(edita el mismo mensaje)
<b>Aviso</b> · Este recordatorio ya no está activo.
```

_Aviso que salió tarde (caída, silencio o canal caído): «(retrasado)»._

```text
<b>llamar a mamá</b>

Recordatorio <i>(retrasado)</i>
[Hecho][+10 min]
[+1 h][Mañana 9:00 am]
```

_De madrugada (antes de las 5:00) el botón dice «Hoy 9:00 am» en lugar de «Mañana 9:00 am»._

```text
<b>revisar el horno</b>

Recordatorio
[Hecho][+10 min]
[+1 h][Hoy 9:00 am]
```

_Aviso de preparación, un día antes de la fecha de una tarea._

```text
<b>Mañana vence: entregar proyecto</b>

Recordatorio · universidad
[Hecho][+10 min]
[+1 h][Mañana 9:00 am]
```

_Aviso de preparación, una hora antes._

```text
<b>En 1 hora vence: entregar proyecto</b>

Recordatorio · universidad
[Hecho][+10 min]
[+1 h][Mañana 9:00 am]
```


## /hoy [área]

_Sin nada para hoy._

```text
Hoy, sábado 3 de octubre
No tienes nada para hoy.
```

_Con tareas vencidas, de hoy, recordatorios de hoy y la bandeja._

```text
Hoy, sábado 3 de octubre
Tareas:
- pagar luz (vencida: viernes 2 de octubre, 5:00 pm)
- entregar informe (hoy, 5:00 pm) [universidad]
Recordatorios:
- 6:00 pm: llamar a mamá
2 en bandeja sin área
```

_Filtrado por área (sin la línea de bandeja)._

```text
Hoy, sábado 3 de octubre
Tareas:
- entregar informe (hoy, 5:00 pm) [universidad]
```

_Área que no existe._

```text
No encuentro el área «inventada». Escribe /areas para ver las que hay.
```


## /pendientes [área]

Un mensaje por tarea, cada uno con sus botones.

_Sin tareas._

```text
No tienes tareas pendientes.
```

_Lista: encabezado y una tarea por mensaje._

```text
Pendientes (4):
---
pagar luz (vence: viernes 2 de octubre, 5:00 pm)
[Hecha]
[Descartar]
---
entregar informe [universidad] (vence: sábado 3 de octubre, 5:00 pm)
[Hecha]
[Descartar]
---
regar plantas [personal] (vence: domingo 4 de octubre, 9:00 am)
[Hecha]
[Descartar]
---
comprar pan
[Hecha]
[Descartar]
```

_Hecha._

```text
(edita el mismo mensaje)
Hecha: regar plantas
```

_Descartar._

```text
(edita el mismo mensaje)
Descartada: comprar pan
```

_Pulsar otra vez sobre una tarea ya cerrada._

```text
(edita el mismo mensaje)
Esta tarea ya no está abierta: regar plantas
```

_Filtrado por área._

```text
Pendientes (1):
---
entregar informe [universidad] (vence: sábado 3 de octubre, 5:00 pm)
[Hecha]
[Descartar]
```

_Más de 10 tareas: se muestran 10 y se avisa._

```text
Pendientes (13):
---
tarea 1
[Hecha]
[Descartar]
---
tarea 2
[Hecha]
[Descartar]
---
tarea 3
[Hecha]
[Descartar]
---
tarea 4
[Hecha]
[Descartar]
---
tarea 5
[Hecha]
[Descartar]
---
tarea 6
[Hecha]
[Descartar]
---
tarea 7
[Hecha]
[Descartar]
---
tarea 8
[Hecha]
[Descartar]
---
tarea 9
[Hecha]
[Descartar]
---
tarea 10
[Hecha]
[Descartar]
---
Hay 3 más. Filtra por área: /pendientes nombre.
```


## /recordatorios

_Sin recordatorios pendientes._

```text
No tienes recordatorios pendientes.
```

_Lista de pendientes, con área y repetición._

```text
Recordatorios pendientes (3):
- sábado 3 de octubre, 6:00 pm: llamar a mamá
- domingo 4 de octubre, 8:00 am: llevar tarea [universidad]
- domingo 4 de octubre, 10:00 am: ir a la iglesia [iglesia] (Cada domingo)
```

_Con detenidos: motivo conocido y motivo desconocido._

```text
Recordatorios pendientes (3):
- sábado 3 de octubre, 6:00 pm: llamar a mamá (detenido: el bot está bloqueado en tu chat)
- domingo 4 de octubre, 8:00 am: llevar tarea [universidad] (detenido: motivo desconocido)
- domingo 4 de octubre, 10:00 am: ir a la iglesia [iglesia] (Cada domingo)
```

_Todos los motivos de detención que se explican._

```text
Recordatorios pendientes (12):
- sábado 3 de octubre, 6:00 pm: llamar a mamá (detenido: el bot está bloqueado en tu chat)
- domingo 4 de octubre, 8:00 am: llevar tarea [universidad] (detenido: motivo desconocido)
- domingo 4 de octubre, 10:00 am: ir a la iglesia [iglesia] (Cada domingo)
- lunes 5 de octubre, 8:00 am: permanent:chat_not_found (detenido: no se encontró tu chat)
- lunes 5 de octubre, 8:00 am: permanent:message_too_long (detenido: el mensaje era demasiado largo)
- lunes 5 de octubre, 8:00 am: permanent:bad_request:cant_parse_entities (detenido: Telegram no pudo leer el formato del texto)
- lunes 5 de octubre, 8:00 am: permanent:bad_request:empty_text (detenido: el texto estaba vacío)
- lunes 5 de octubre, 8:00 am: permanent:bad_request:button_data_invalid (detenido: un botón no era válido)
- lunes 5 de octubre, 8:00 am: permanent:bad_request:other (detenido: Telegram rechazó el mensaje)
- lunes 5 de octubre, 8:00 am: horizon:telegram_down (detenido: Telegram no respondió durante 24 horas)
- lunes 5 de octubre, 8:00 am: legacy (detenido: se detuvo en una versión anterior)
- lunes 5 de octubre, 8:00 am: permanent:unexpected:KeyError (detenido: error inesperado al enviar)
```


## /recordar

_Sin texto._

```text
Escribe /recordar seguido de qué y cuándo, por ejemplo: /recordar mañana 8 am llevar tarea
```

_Con texto: se guarda en la bandeja y pregunta el área._

```text
<b>¿En qué área va?</b>

mañana 8am llevar tarea

Tipo: Recordatorio
[universidad][proyectos]
[iglesia][personal]
[Sin área][Cancelar]
```

_Vista previa antes de guardar._

```text
(edita el mismo mensaje)
<b>¿Guardo este recordatorio?</b>

llevar tarea

Cuándo: domingo 4 de octubre, 8:00 am
Área: universidad
[Guardar][Cancelar]
```

_Guardar: confirmación._

```text
(edita el mismo mensaje)
<b>Recordatorio guardado</b>

llevar tarea

Cuándo: domingo 4 de octubre, 8:00 am
Área: universidad
[Cambiar][Deshacer]
```

_Con repetición: vista previa con la próxima fecha._

```text
(edita el mismo mensaje)
<b>¿Guardo esta repetición?</b>

regar plantas

Repetición: Cada lunes
Próxima: lunes 5 de octubre, 7:00 pm
[Guardar][Cancelar]
```

_Con una duda del parser: se elige el candidato y luego se muestra la vista previa._

```text
(edita el mismo mensaje)
<b>¿Guardo este recordatorio?</b>

llevar tarea

Cuándo: domingo 4 de octubre, 9:00 pm
[Guardar][Cancelar]
```


## /tarea

_Sin texto._

```text
Escribe /tarea seguido de la tarea, por ejemplo: /tarea comprar pan
```

_Con texto: pregunta solo el área._

```text
<b>¿En qué área va?</b>

comprar pan

Tipo: Tarea
[universidad][proyectos]
[iglesia][personal]
[Sin área][Cancelar]
```

_Área elegida._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

comprar pan

Área: personal
```

_Con una fecha clara en el texto: pregunta si es la fecha límite._

```text
(edita el mismo mensaje)
<b>¿Es la fecha límite?</b>

entregar informe

Tipo: Tarea
Área: universidad
Fecha: viernes 9 de octubre, 9:00 am (hora por defecto)
[Sí][No]
[Cancelar]
```

_Sí: título sin la fecha, con fecha de vencimiento._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

entregar informe

Área: universidad
Vence: viernes 9 de octubre, 9:00 am (hora por defecto)
```

_No: queda con el texto completo y sin fecha._

```text
(edita el mismo mensaje)
<b>Tarea guardada</b>

entregar informe el viernes

Área: universidad
```


## /nota

_Sin texto._

```text
Escribe /nota seguido de la nota, por ejemplo: /nota la clave del wifi está en el router
```

_Con texto: pregunta solo el área._

```text
<b>¿En qué área va?</b>

la clave del wifi

Tipo: Nota
[universidad][proyectos]
[iglesia][personal]
[Sin área][Cancelar]
```

_Área elegida._

```text
(edita el mismo mensaje)
<b>Nota guardada</b>

la clave del wifi

Área: personal
```


## /areas y /nuevaarea

_Lista de áreas._

```text
Áreas:
- universidad
- proyectos
- iglesia
- personal
```

_Un área sin descripción se marca._

```text
Áreas:
- universidad
- proyectos
- iglesia
- personal
- Salud (sin descripción)
```

_Sin áreas._

```text
No hay áreas. Crea una con /nuevaarea nombre.
```

_/nuevaarea sin nombre._

```text
Escribe /nuevaarea seguido del nombre, por ejemplo: /nuevaarea Salud
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
Ya existe un área llamada «universidad».
```

_Nombre demasiado largo._

```text
El nombre es demasiado largo (máximo 40 caracteres).
```


## /start y /ayuda

_/start._

```text
¡Hola! Soy tu asistente personal.
Escribe lo que quieras anotar y te pregunto qué es. /ayuda muestra los comandos.
```

_/ayuda._

```text
Comandos disponibles:
/hoy [área] - lo que vence hoy
/pendientes [área] - tus tareas abiertas
/recordatorios - avisos pendientes y detenidos
/recordar texto - crear un recordatorio
/tarea texto - guardar una tarea
/nota texto - guardar una nota
/areas - ver las áreas
/nuevaarea nombre - crear un área
/start - saludo
/ayuda - esta lista
Cualquier otro mensaje lo guardo en tu bandeja y te pregunto qué es.
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

_Botón de tarea que no existe._

```text
(edita el mismo mensaje)
<b>Aviso</b> · Esa opción ya no está disponible.
```

_Deshacer/Cambiar cuando el recordatorio ya no está pendiente._

```text
(edita el mismo mensaje)
<b>Aviso</b> · Ya no se puede deshacer ni cambiar: ese recordatorio ya no está pendiente.
```

_Un comando a mitad de otra pregunta no la descarta; otro flujo nuevo sí, y avisa._

```text
(edita el mismo mensaje)
<b>Sin terminar</b>

Deportes

No se creó el área.
---
<b>¿En qué área va?</b>

sacar copias

Tipo: Tarea
[universidad][proyectos]
[iglesia][personal]
[Sin área][Cancelar]
```
