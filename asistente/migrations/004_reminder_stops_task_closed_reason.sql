-- Fase 1: sustituye el centinela attempts=1000 por columnas propias y registra por qué se cerró
-- una tarea.

-- first_failed_at: inicio de la racha de fallos pasajeros (horizonte de 24 h); se borra al enviar
--                  bien o al posponer.
-- stopped_at / stop_reason: el envío se detuvo (error permanente o horizonte agotado). `stopped_at`
--                  se conserva aunque se reactive (marca que la serie ya generó su siguiente).
ALTER TABLE reminders ADD COLUMN first_failed_at TEXT;
ALTER TABLE reminders ADD COLUMN stopped_at TEXT;
ALTER TABLE reminders ADD COLUMN stop_reason TEXT;

-- Los detenidos con el centinela viejo pasan al modelo nuevo.
UPDATE reminders
   SET stopped_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'),
       stop_reason = 'legacy',
       attempts = 0
 WHERE attempts >= 1000;

-- closed_reason: por qué una tarea está cerrada como 'dropped'. Las conversiones de bandeja
-- (a recordatorio o nota) son 'dropped' pero NO son descartes: /papelera y los reportes
-- filtran por closed_reason = 'discarded'.
ALTER TABLE tasks ADD COLUMN closed_reason TEXT
  CHECK (closed_reason IN ('discarded', 'converted_to_reminder', 'converted_to_note'));

UPDATE tasks SET closed_reason = 'discarded' WHERE status = 'dropped';
