-- Esquema inicial. Todas las marcas de tiempo son TEXT ISO-8601 en UTC. Nada se borra.
PRAGMA foreign_keys = ON;

CREATE TABLE areas (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL,            -- se usa como "criteria" para Jev: redactarla bien importa
  archived    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);

CREATE TABLE tasks (
  id                  INTEGER PRIMARY KEY,
  title               TEXT NOT NULL,
  area_id             INTEGER REFERENCES areas(id),   -- NULL = sin área
  due_at_utc          TEXT,
  status              TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','done','postponed','dropped')),
  postponed_until_utc TEXT,
  source_text         TEXT,                           -- lo que el usuario escribió originalmente
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  closed_at           TEXT
);

CREATE TABLE reminders (
  id            INTEGER PRIMARY KEY,
  task_id       INTEGER REFERENCES tasks(id),
  text          TEXT NOT NULL,
  area_id       INTEGER REFERENCES areas(id),
  fire_at_utc   TEXT NOT NULL,
  rrule         TEXT,                                 -- RFC 5545, p. ej. FREQ=WEEKLY;BYDAY=SU
  priority      INTEGER NOT NULL DEFAULT 1 CHECK (priority IN (1,2)),  -- 2 = insistir
  status        TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','sent','done','cancelled')),
  snooze_count  INTEGER NOT NULL DEFAULT 0,
  attempts      INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  last_fired_at TEXT
);
CREATE INDEX idx_reminders_due ON reminders(status, fire_at_utc);

CREATE TABLE notes (
  id         INTEGER PRIMARY KEY,
  text       TEXT NOT NULL,
  area_id    INTEGER REFERENCES areas(id),
  created_at TEXT NOT NULL,
  archived   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE accounts (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,                    -- efectivo, tarjeta, ahorro...
  created_at TEXT NOT NULL
);

CREATE TABLE ledger (
  id           INTEGER PRIMARY KEY,
  ts_utc       TEXT NOT NULL,
  account_id   INTEGER NOT NULL REFERENCES accounts(id),
  kind         TEXT NOT NULL CHECK (kind IN ('expense','income','adjustment')),
  amount_cents INTEGER NOT NULL,                      -- con signo: gasto < 0, ingreso > 0
  category     TEXT,
  note         TEXT,
  voided       INTEGER NOT NULL DEFAULT 0,
  CHECK ((kind = 'expense' AND amount_cents < 0)
      OR (kind = 'income'  AND amount_cents > 0)
      OR  kind = 'adjustment')
);

CREATE TABLE classification_log (
  id               INTEGER PRIMARY KEY,
  ts_utc           TEXT NOT NULL,
  text_norm        TEXT NOT NULL,
  source           TEXT NOT NULL CHECK (source IN ('rule','jev','haiku','user')),
  pred_kind        TEXT, pred_kind_conf REAL,
  pred_area        TEXT, pred_area_conf REAL,
  latency_ms       INTEGER,
  final_kind       TEXT, final_area TEXT,
  user_corrected   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE learned_rules (
  id         INTEGER PRIMARY KEY,
  text_norm  TEXT NOT NULL UNIQUE,                    -- texto normalizado sin fechas ni números
  kind       TEXT NOT NULL,
  area_id    INTEGER REFERENCES areas(id),
  hits       INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE usage_log (
  id            INTEGER PRIMARY KEY,
  ts_utc        TEXT NOT NULL,
  provider      TEXT NOT NULL,                        -- anthropic | typesafe
  model         TEXT,
  input_tokens  INTEGER, output_tokens INTEGER,
  cost_usd_est  REAL
);

-- Valores iniciales de settings.
INSERT INTO settings (key, value) VALUES
  ('briefing_time', '07:30'),
  ('quiet_start', '22:00'),
  ('quiet_end', '07:00'),
  ('auto_threshold', '0.80'),
  ('ask_threshold', '0.50'),
  ('default_morning_time', '09:00'),
  ('daily_proactive_cap', '6'),
  ('ledger_auto_save', '0');

-- Áreas iniciales (editables). La descripción es el "criteria" que lee el clasificador.
INSERT INTO areas (name, description, created_at) VALUES
  ('universidad',
   'Clases, tareas escolares, exámenes, trabajos y entregas de materias, estudiar, ' ||
   'trámites de la universidad y asuntos con profesores o compañeros de clase.',
   strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
  ('proyectos',
   'Proyectos personales propios que no son de la universidad: programar, apps, diseño, ' ||
   'ideas para construir, repositorios, herramientas y experimentos.',
   strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
  ('iglesia',
   'Actividades de la iglesia: servicios y reuniones, ministerio, grupo de jóvenes, oración, ' ||
   'estudio bíblico, preparar mensajes o cantos, voluntariado y eventos de la comunidad.',
   strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
  ('personal',
   'Vida diaria personal: salud, ejercicio, familia, amigos, casa, compras, citas, trámites ' ||
   'y ocio; todo lo que no encaja en universidad, proyectos ni iglesia.',
   strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));
