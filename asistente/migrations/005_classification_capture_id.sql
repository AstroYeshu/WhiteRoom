-- Fase 1 (etiquetas para la Fase 2): una fila de `classification_log` por captura.
-- capture_id: la tarea de bandeja con la que nació la captura. «Cambiar» vuelve a decidir la misma
--             captura y ACTUALIZA su fila (user_corrected = 1) en vez de añadir otra.
--             NULL = fila sin captura (las de antes de esta migración): cada una cuenta por separado.
ALTER TABLE classification_log ADD COLUMN capture_id INTEGER REFERENCES tasks(id);

-- A lo sumo una fila por captura (los NULL no chocan entre sí en SQLite).
CREATE UNIQUE INDEX idx_classification_capture ON classification_log(capture_id);
