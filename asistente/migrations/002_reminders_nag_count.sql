-- Reenvíos de los recordatorios con priority=2 ("insistir"): cuántas veces se han reenviado.
ALTER TABLE reminders ADD COLUMN nag_count INTEGER NOT NULL DEFAULT 0;
