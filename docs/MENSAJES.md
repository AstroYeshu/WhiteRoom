# Catálogo de mensajes

Generado por `python scripts/show_messages.py` con los manejadores reales, una base en memoria
y un reloj fijo: **sábado 3 de octubre de 2026, 3:30 pm** (México). Las áreas son las iniciales
(universidad, proyectos, iglesia, personal). Cada botón va en su propia fila, como `[Etiqueta]`;
`---` separa mensajes distintos de una misma respuesta. «(reemplaza el mensaje del botón)» es
una edición: el texto sustituye al mensaje que llevaba los botones, sin teclado.
No incluye la salida de `scripts/dev_remind_me.py` ni los errores de configuración del arranque.

## Bandeja (mensaje libre)

Cualquier texto que no es un comando se guarda al instante como tarea sin área y se pregunta qué es.

_Mensaje libre: pregunta de tipo._

```text
Guardado en tu bandeja: «comprar leche»
¿Qué es?
[Tarea]
[Recordatorio]
[Nota]
[Cancelar]
```

_Se elige Tarea: la elección queda en el mensaje y llega la pregunta de área._

```text
(reemplaza el mensaje del botón)
Tarea
---
¿En qué área va?
[universidad]
[proyectos]
[iglesia]
[personal]
[Sin área]
[Cancelar]
```

_Se elige un área: la tarea queda guardada._

```text
(reemplaza el mensaje del botón)
Tarea guardada en personal: «comprar leche»
```

_Cancelar en cualquier pregunta: la tarea sigue en la bandeja._

```text
(reemplaza el mensaje del botón)
Cancelado. «comprar leche» sigue en tu bandeja como tarea.
```

_Nota guardada con su área._

```text
(reemplaza el mensaje del botón)
Nota guardada en universidad: «la clave del wifi es larga»
```

_Sin áreas disponibles no se pregunta el área._

```text
(reemplaza el mensaje del botón)
Tarea
---
(reemplaza el mensaje del botón)
Tarea guardada: «comprar leche»
```

_Recordatorio con fecha clara: edición del área y confirmación con Cambiar/Deshacer._

```text
(reemplaza el mensaje del botón)
Área: universidad
---
Listo: «llevar tarea»
Cuándo: domingo 4 de octubre, 8:00 am
Área: universidad
[Cambiar]
[Deshacer]
```

_Deshacer: el recordatorio se cancela y la tarea vuelve a la bandeja._

```text
(reemplaza el mensaje del botón)
Deshecho. «llevar tarea» vuelve a tu bandeja como tarea.
```

_Cambiar: se deshace y se vuelve a preguntar la fecha._

```text
(reemplaza el mensaje del botón)
Cambiando «llevar tarea»
---
¿Cuándo? Pulsa una opción o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5".
[Hoy 18:00]
[Mañana 9:00]
[Mejor como tarea]
[Cancelar]
```

_Se responde la fecha escribiéndola._

```text
Listo: «llevar tarea»
Cuándo: lunes 5 de octubre, 10:00 am
Área: universidad
[Cambiar]
[Deshacer]
```

_Fecha sin hora: la confirmación avisa de la hora por defecto._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
Listo: «llevar tarea»
Cuándo: domingo 4 de octubre, 9:00 am (hora por defecto)
[Cambiar]
[Deshacer]
```

_Repetición: vista previa con la próxima fecha, sin guardar todavía._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
Repetición: Cada lunes: «regar plantas»
Próxima: lunes 5 de octubre, 7:00 pm
¿La guardo?
[Guardar]
[Cancelar]
```

_Guardar la repetición: confirmación._

```text
(reemplaza el mensaje del botón)
Listo: lunes 5 de octubre, 7:00 pm
---
Listo: «regar plantas»
Repetición: Cada lunes
Próxima: lunes 5 de octubre, 7:00 pm
[Cambiar]
[Deshacer]
```

_Un texto que empieza por «recordar/recuérdame» salta la pregunta de tipo._

```text
Guardado en tu bandeja: «recuérdame llamar a mamá»
¿En qué área va?
[universidad]
[proyectos]
[iglesia]
[personal]
[Sin área]
[Cancelar]
```

_Sin fecha: pregunta ¿cuándo? con opciones rápidas y «Mejor como tarea»._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
¿Cuándo? Pulsa una opción o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5".
[Hoy 18:00]
[Mañana 9:00]
[Mejor como tarea]
[Cancelar]
```

_Se elige una opción rápida: confirmación._

```text
(reemplaza el mensaje del botón)
Listo: domingo 4 de octubre, 9:00 am
---
Listo: «llamar a mamá»
Cuándo: domingo 4 de octubre, 9:00 am
[Cambiar]
[Deshacer]
```

_Mejor como tarea: queda como tarea con el área ya elegida, sin recordatorio._

```text
(reemplaza el mensaje del botón)
Tarea guardada en iglesia: «llamar al dentista»
```

_En ¿cuándo?, «Escribir otra»/texto: si lo escrito no es una fecha, es una captura nueva y se avisa._

```text
Dejé sin terminar lo anterior; sigue en tu bandeja como tarea.
---
Guardado en tu bandeja: «comprar leche»
¿Qué es?
[Tarea]
[Recordatorio]
[Nota]
[Cancelar]
```

_Botón de una pregunta vieja: se ignora._

```text
(reemplaza el mensaje del botón)
Esa opción ya no está disponible.
```

_La opción «Hoy 18:00» se pulsó cuando ya había pasado._

```text
(reemplaza el mensaje del botón)
Esa hora ya pasó.
---
Esa hora ya pasó. ¿Cuándo? Pulsa una opción o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5".
[Mañana 9:00]
[Mejor como tarea]
[Cancelar]
```


## Preguntas del parser de fechas (recordatorios)

Se llega con «Recordatorio» y un área; aquí se muestra solo la pregunta que sale.

_Hora o cita bíblica (time_or_verse)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
¿Eso es una hora o una cita bíblica?
[Es una cita (sin fecha)]
[Escribir otra fecha]
[Cancelar]
```

_Persona o día (name_or_day)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
¿«Domingo» es una persona o el día de la semana?
[Es un nombre (sin fecha)]
[Escribir otra fecha]
[Cancelar]
```

_Hora con punto (dotted_time)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
¿Es una hora? Escríbela con dos puntos (por ejemplo 7:30).
[Escribir otra fecha]
[Cancelar]
```

_Número pegado al día (number_after_day)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
¿Ese número es la hora o forma parte del texto? Escribe la hora completa.
[Escribir otra fecha]
[Cancelar]
```

_Fecha que no entiende (unsupported_date): opciones rápidas._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
No entiendo esa fecha. ¿Qué día quieres?
[Hoy 18:00]
[Mañana 9:00]
[Escribir otra fecha]
[Cancelar]
```

_Repetición que no sabe hacer (unrecognized_recurrence)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
Esa repetición no está entre las que sé hacer (todos los días, cada lunes, de lunes a viernes).
[Solo una vez…]
[Escribir otra fecha]
[Cancelar]
```

_Medianoche dudosa (ambiguous_time)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
¿Medianoche de qué día?
[domingo 4 de octubre, 12:00 am]
[lunes 5 de octubre, 12:00 am]
[Escribir otra fecha]
[Cancelar]
```

_Hora dudosa, dos lecturas (ambiguous_meridiem)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
¿A las 9 am o pm?
[domingo 4 de octubre, 9:00 am]
[domingo 4 de octubre, 9:00 pm]
[Escribir otra fecha]
[Cancelar]
```

_Hora dudosa, un solo candidato futuro (ambiguous_meridiem)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
¿A las 8:00 pm?
[sábado 3 de octubre, 8:00 pm]
[Escribir otra fecha]
[Cancelar]
```

_Hora que ya pasó, con alternativa (past)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
Esa fecha ya pasó. ¿La dejo para domingo 4 de octubre, 10:00 am?
[domingo 4 de octubre, 10:00 am]
[Escribir otra fecha]
[Cancelar]
```

_Día igual al de hoy (same_weekday)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
Hoy es ese día: ¿hoy o en 7 días?
[sábado 10 de octubre, 9:00 am]
[Escribir otra fecha]
[Cancelar]
```

_Pasada la medianoche, «mañana» dudoso (today_or_tomorrow)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
Ya pasó la medianoche: ¿«mañana» es hoy o mañana?
[domingo 4 de octubre, 8:00 am]
[lunes 5 de octubre, 8:00 am]
[Escribir otra fecha]
[Cancelar]
```

_Cualquier otra duda (texto genérico)._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
No pude entender la fecha o la hora; escríbela de otra forma.
[Escribir otra fecha]
[Cancelar]
```


## Aviso de recordatorio y sus botones

Lo que sale cuando el motor envía un recordatorio (tipo de envío `reminder`).

_Aviso a su hora, con el área entre corchetes._

```text
Recordatorio: llevar tarea [universidad]
[Hecho]
[+10 min]
[+1 h]
[Mañana 9:00]
```

_Hecho._

```text
(reemplaza el mensaje del botón)
Hecho: llevar tarea
```

_+10 min: se reprograma para hoy._

```text
(reemplaza el mensaje del botón)
Pospuesto para hoy, 3:41 pm: llamar a mamá
```

_Mañana 9:00: se reprograma para el día siguiente (día completo en la confirmación)._

```text
(reemplaza el mensaje del botón)
Pospuesto para domingo 4 de octubre, 9:00 am: llamar a mamá
```

_Pulsar otra vez un botón de un aviso que ya no está activo._

```text
(reemplaza el mensaje del botón)
Hecho: llamar a mamá
```

_Botón de un recordatorio que no existe._

```text
(reemplaza el mensaje del botón)
Este recordatorio ya no está activo.
```

_Aviso que salió tarde (caída, silencio o canal caído): «(retrasado)»._

```text
Recordatorio: llamar a mamá (retrasado)
[Hecho]
[+10 min]
[+1 h]
[Mañana 9:00]
```

_De madrugada (antes de las 5:00) el botón dice «Hoy 9:00» en lugar de «Mañana 9:00»._

```text
Recordatorio: revisar el horno
[Hecho]
[+10 min]
[+1 h]
[Hoy 9:00]
```

_Aviso de preparación, un día antes de la fecha de una tarea._

```text
Recordatorio: Mañana vence: entregar proyecto [universidad]
[Hecho]
[+10 min]
[+1 h]
[Mañana 9:00]
```

_Aviso de preparación, una hora antes._

```text
Recordatorio: En 1 hora vence: entregar proyecto [universidad]
[Hecho]
[+10 min]
[+1 h]
[Mañana 9:00]
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
(reemplaza el mensaje del botón)
Hecha: regar plantas
```

_Descartar._

```text
(reemplaza el mensaje del botón)
Descartada: comprar pan
```

_Pulsar otra vez sobre una tarea ya cerrada._

```text
(reemplaza el mensaje del botón)
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
Guardado en tu bandeja: «mañana 8am llevar tarea»
¿En qué área va?
[universidad]
[proyectos]
[iglesia]
[personal]
[Sin área]
[Cancelar]
```

_Vista previa antes de guardar._

```text
(reemplaza el mensaje del botón)
Área: universidad
---
Recordatorio: «llevar tarea»
Cuándo: domingo 4 de octubre, 8:00 am
Área: universidad
¿Lo guardo?
[Guardar]
[Cancelar]
```

_Guardar: confirmación._

```text
(reemplaza el mensaje del botón)
Listo: domingo 4 de octubre, 8:00 am
---
Listo: «llevar tarea»
Cuándo: domingo 4 de octubre, 8:00 am
Área: universidad
[Cambiar]
[Deshacer]
```

_Con repetición: vista previa con la próxima fecha._

```text
(reemplaza el mensaje del botón)
Área: ninguna
---
Repetición: Cada lunes: «regar plantas»
Próxima: lunes 5 de octubre, 7:00 pm
¿La guardo?
[Guardar]
[Cancelar]
```

_Con una duda del parser: se elige el candidato y luego se muestra la vista previa._

```text
(reemplaza el mensaje del botón)
Elegido: domingo 4 de octubre, 9:00 pm
---
Recordatorio: «llevar tarea»
Cuándo: domingo 4 de octubre, 9:00 pm
¿Lo guardo?
[Guardar]
[Cancelar]
```


## /tarea

_Sin texto._

```text
Escribe /tarea seguido de la tarea, por ejemplo: /tarea comprar pan
```

_Con texto: pregunta solo el área._

```text
Guardado en tu bandeja: «comprar pan»
¿En qué área va?
[universidad]
[proyectos]
[iglesia]
[personal]
[Sin área]
[Cancelar]
```

_Área elegida._

```text
(reemplaza el mensaje del botón)
Tarea guardada en personal: «comprar pan»
```

_Con una fecha clara en el texto: pregunta si es la fecha límite._

```text
(reemplaza el mensaje del botón)
Área: universidad
---
¿Es la fecha límite de «entregar informe»?
Fecha: viernes 9 de octubre, 9:00 am (hora por defecto)
[Sí]
[No]
[Cancelar]
```

_Sí: título sin la fecha, con fecha de vencimiento._

```text
(reemplaza el mensaje del botón)
Tarea guardada en universidad: «entregar informe» (vence: viernes 9 de octubre, 9:00 am)
```

_No: queda con el texto completo y sin fecha._

```text
(reemplaza el mensaje del botón)
Tarea guardada en universidad: «entregar informe el viernes»
```


## /nota

_Sin texto._

```text
Escribe /nota seguido de la nota, por ejemplo: /nota la clave del wifi está en el router
```

_Con texto: pregunta solo el área._

```text
Guardado en tu bandeja: «la clave del wifi»
¿En qué área va?
[universidad]
[proyectos]
[iglesia]
[personal]
[Sin área]
[Cancelar]
```

_Área elegida._

```text
(reemplaza el mensaje del botón)
Nota guardada en personal: «la clave del wifi»
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
¿Qué cubre «Salud»? Escribe una descripción corta u omítela.
[Omitir]
[Cancelar]
```

_Se escribe la descripción._

```text
Área creada: Salud
```

_Omitir: el área queda sin descripción._

```text
(reemplaza el mensaje del botón)
Área creada: Deportes (sin descripción)
```

_Cancelar._

```text
(reemplaza el mensaje del botón)
Cancelado. No se creó el área.
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
No conozco ese comando. Escribe /ayuda para ver los disponibles.
```

_Botón desconocido o mal formado._

```text
Esa opción ya no está disponible.
```

_Botón de la bandeja de un flujo que ya no existe._

```text
(reemplaza el mensaje del botón)
Esa opción ya no está disponible.
```

_Botón de tarea que no existe._

```text
(reemplaza el mensaje del botón)
Esa opción ya no está disponible.
```

_Deshacer/Cambiar cuando el recordatorio ya no está pendiente._

```text
(reemplaza el mensaje del botón)
Ya no se puede deshacer ni cambiar: ese recordatorio ya no está pendiente.
```

_Un comando a mitad de otra pregunta no la descarta; otro flujo nuevo sí, y avisa._

```text
Dejé sin terminar la creación del área.
---
Guardado en tu bandeja: «sacar copias»
¿En qué área va?
[universidad]
[proyectos]
[iglesia]
[personal]
[Sin área]
[Cancelar]
```
