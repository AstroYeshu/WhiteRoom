# Estilo de los mensajes

Reglas de redacción para todo lo que ve el dueño (`formato.py` las aplica; el catálogo `docs/MENSAJES.md` es la prueba).

- Las oraciones empiezan con mayúscula: "Ya existe un área llamada «Salud»."
- Las áreas empiezan con mayúscula: "Universidad", "Proyectos".
- Los días y los meses van en minúscula dentro de una frase ("vie 9 oct", "hoy, 5:00 pm"); con mayúscula solo al inicio de una línea.
- Los títulos de tareas, textos de recordatorios y notas se muestran con la primera letra en mayúscula (`cap_first`);
  lo guardado en la base no se modifica nunca (los nombres de área se normalizan al crearlos).
- Regla de `cap_first`: solo se pone en mayúscula una primera letra minúscula (tras los "¿" y "¡" iniciales), salvo que la primera
  palabra tenga otra mayúscula después de su primera letra: "iOS", "eBay", "iPhone" no se tocan; "UNAM" y "Ya" ya están bien;
  "ya" pasa a "Ya". Números y símbolos iniciales no cambian ("123 a").
- Las etiquetas llevan dos puntos: "Área: Personal", "Vence: mañana, 9:00 am".
- Sin emojis ni pictogramas (lo vigila `tests/test_no_pictograms.py`).
- Puntuación: el punto medio · separa datos de una línea; la raya — separa una aclaración.
- Los botones llevan como máximo 22 caracteres y la primera letra en mayúscula ("Mejor como tarea").
- Cambiar un texto o una etiqueta a propósito obliga a regenerar `docs/MENSAJES.md` (`python scripts/show_messages.py`).
