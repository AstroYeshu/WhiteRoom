# SPEC — Asistente personal por Telegram

> Se construye por fases. Cada fase se implementa en una sesión limpia de Claude Code
> (`/clear` entre fases). Lee `CLAUDE.md` primero. Implementa solo la fase pedida.

## 1. Objetivo

Bot privado de Telegram (un solo usuario) que corre 24/7 en una Raspberry Pi 4 como asistente
de vida diaria. Prioridades, en orden:

1. **Los recordatorios siempre suenan**, aunque falle cualquier API de IA.
2. **Anotar cuesta ≤ 5 segundos y casi sin teclear**: el usuario escribe solo la cosa; el sistema decide
   el tipo y el área, o pregunta con botones si duda.
3. **El saldo siempre es correcto** (cálculo determinista, nunca por IA).
4. **Costo de IA de unos pocos dólares al mes**, medido y con tope.

## 2. Contexto del usuario

Estudiante universitario con proyectos personales y actividades de iglesia. Idioma: español.
Áreas iniciales (editables): `universidad`, `proyectos`, `iglesia`, `personal`.
Zona horaria configurable (`TZ_NAME`).

## 3. Principio de diseño: tres capas

| Capa | Quién | Responsabilidad |
|---|---|---|
| Reflejo | **Jev** (TypeSafe) o Claude Haiku como alternativa | Decidir *qué es* (tipo) y *de qué área*. Solo elige entre opciones; no escribe texto |
| Reglas | **Código propio** | Fechas, montos, saldos, recordatorios, quitar tareas, permisos |
| Razonamiento | **Claude (Haiku)** | Solo cuando hay que *escribir*: nombrar una categoría nueva, paquetes de contexto, modo chat |

Orden de resolución al capturar un mensaje libre: **reglas aprendidas → clasificador (Jev/Haiku) → preguntar al usuario con botones**.

### 3.1 Canales y portabilidad (Telegram hoy, WhatsApp quizá después)

El núcleo no sabe en qué plataforma corre. Todo lo saliente pasa por una interfaz:

```python
@dataclass
class Choice:
    id: str  # corto, p. ej. "done:42"
    label: str


class Channel(Protocol):
    async def send_text(self, to: str, text: str, kind: str = "reply") -> None: ...
    async def send_choices(
        self, to: str, text: str, choices: list[Choice], kind: str = "reply"
    ) -> None: ...
    async def edit_text(self, to: str, message_ref: str, text: str) -> None: ...  # sin botones
```

- `kind` es `reply`, `reminder` o `briefing`: deja que cada canal decida CÓMO enviar (WhatsApp necesitará
  plantillas aprobadas cuando esté fuera de su ventana de 24 h).
- Los "botones" de este documento son `Choice`: Telegram los dibuja como botones inline, la consola como
  lista numerada y un futuro canal de WhatsApp como botones de respuesta (máx. 3) o lista.
- Entrada: cada canal convierte lo recibido en `IncomingMessage(channel, user_ref, text)` o
  `IncomingChoice(channel, user_ref, choice_id, message_ref)` y llama a `bot.handlers`. `message_ref` es el mensaje
  que llevaba el botón (None si el canal no puede editar; entonces se responde con un mensaje nuevo). Pulsar un botón
  EDITA ese mensaje con `edit_text` (texto nuevo, sin teclado).
- **Sin emojis ni pictogramas** en ningún mensaje ni etiqueta (`Choice.label`, textos, consola): cada canal
  decide cómo adornar, y WhatsApp o una consola sin fuentes no deben depender de ellos. Etiquetas en texto:
  `Hecho`, `+10 min`, `+1 h`, `Mañana 9:00`, `Cancelar`. Lo vigila `tests/test_no_pictograms.py` (AST).
- **Solo `channels/telegram.py` importa la librería de Telegram.** `core/` y `bot/` jamás.
- `core/reminders.py` y `core/briefing.py` reciben el `Channel` por inyección (se prueban con un canal falso).
- Para un futuro adaptador de WhatsApp (NO implementar ahora): requiere webhook HTTPS público con verificación
  de firma (p. ej. mediante un túnel de salida); mensajes libres solo dentro de la ventana de 24 h y plantillas
  aprobadas fuera de ella; sin conversación abierta con LLM (política de Meta sobre asistentes de propósito
  general), así que `/chat` queda solo en Telegram; Telegram sigue siendo el canal principal.

## 4. Stack

- Python 3.11+
- `python-telegram-bot` (v20+, asíncrono, con extra `job-queue`) — modo **long polling** (sin puertos abiertos)
- `sqlite3` de la biblioteca estándar, modo WAL
- `anthropic` (SDK oficial) para Haiku
- `httpx` para Jev
- `python-dateutil` (solo para `rrule`). Las fechas en español las interpreta un parser propio de gramática cerrada
  (`parsing/dates.py`): se descartó `dateparser` porque devolvía fechas incorrectas sin avisar (ver `docs/PLAN_FASE1.md`).
- `python-dotenv`, `pytest`, `ruff`
- Fijar versiones en `requirements.txt` tras instalar. Preguntar antes de añadir otra dependencia.

## 5. Estructura de carpetas

```
asistente/
├─ CLAUDE.md
├─ SPEC.md
├─ README.md
├─ requirements.txt
├─ .env.example
├─ .gitignore                 # .env, data/, venv/, __pycache__/
├─ asistente/
│  ├─ main.py                 # arranque: config, DB, bot, jobs
│  ├─ config.py               # lee y valida .env
│  ├─ db.py                   # conexión SQLite + runner de migraciones
│  ├─ migrations/001_init.sql
│  ├─ timeutil.py             # UTC <-> zona local, horas de silencio, reloj inyectable
│  ├─ channels/
│  │  ├─ base.py              # Protocol Channel, Choice, IncomingMessage, IncomingChoice
│  │  ├─ console.py           # canal de consola (--dry-run y pruebas)
│  │  └─ telegram.py          # ÚNICO módulo que importa la librería de Telegram
│  ├─ bot/                    # conversación independiente de la plataforma
│  │  ├─ auth.py              # filtro ALLOWED_USER_ID
│  │  ├─ handlers.py          # handle_message / handle_choice (comandos y mensajes libres)
│  │  └─ choices.py           # opciones como datos (Choice), no como botones de una plataforma
│  ├─ core/
│  │  ├─ capture.py           # pipeline de captura de mensajes libres
│  │  ├─ tasks.py
│  │  ├─ notes.py
│  │  ├─ reminders.py         # motor: tick, snooze, rrule, silencio
│  │  ├─ briefing.py          # resumen diario y revisión semanal
│  │  ├─ ledger.py            # libro de cuentas
│  │  └─ context_pack.py      # paquetes de contexto para claude.ai
│  ├─ classify/
│  │  ├─ base.py              # Protocol Classifier + dataclass Classification
│  │  ├─ rules.py             # reglas aprendidas
│  │  ├─ jev.py
│  │  ├─ haiku.py
│  │  └─ decide.py            # regla de decisión por confianza
│  ├─ llm/claude.py           # cliente Anthropic + registro de uso/costo
│  └─ parsing/
│     ├─ dates.py             # parser propio de fechas/horas en español (gramática cerrada, sin dateparser)
│     ├─ recurrence.py        # "todos los días", "cada viernes", "de lunes a viernes" -> rrule
│     └─ amounts.py           # regex de montos
├─ scripts/
│  ├─ eval_classifier.py
│  └─ backup_db.sh
├─ deploy/asistente.service   # unidad systemd
├─ data/                      # (ignorado por git) asistente.db, backups/
└─ tests/
```

## 6. Configuración (`.env.example`)

```
TELEGRAM_BOT_TOKEN=
ALLOWED_USER_ID=                  # tu ID numérico de Telegram
ASSISTANT_ANTHROPIC_KEY=          # NO llamarla ANTHROPIC_API_KEY (ver CLAUDE.md)
CLAUDE_MODEL_FAST=claude-haiku-4-5-20251001
TYPESAFE_API_KEY=                 # opcional; si falta se usa Haiku
TYPESAFE_BASE_URL=https://api.typesafe.ai
CLASSIFIER=rules+jev              # rules+jev | rules+haiku
TZ_NAME=                          # zona IANA, p. ej. America/Mexico_City
CURRENCY_CODE=                    # p. ej. MXN, USD
DB_PATH=data/asistente.db
MONTHLY_API_BUDGET_USD=8          # tope de gasto en IA; al superarlo se desactivan las rutas con LLM
DRY_RUN=0                         # equivale al flag --dry-run (multiplataforma)
LOG_LEVEL=INFO
```

## 7. Modelo de datos (`migrations/001_init.sql`)

Todas las marcas de tiempo son TEXT ISO-8601 en **UTC**. Nada se borra.

```sql
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
  -- closed_reason TEXT se añade en la migración 004 (ver nota bajo la tabla)
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
  attempts      INTEGER NOT NULL DEFAULT 0,           -- fallos de envío seguidos de ESTA fila (ver 8.3)
  created_at    TEXT NOT NULL,
  last_fired_at TEXT
  -- nag_count INTEGER NOT NULL DEFAULT 0 se añade en la migración 002 (reenvíos de priority=2)
  -- first_failed_at, stopped_at, stop_reason (TEXT, NULL) se añaden en la migración 004
);
CREATE INDEX idx_reminders_due ON reminders(status, fire_at_utc);

-- Migración 004 (hacia adelante):
--   reminders.first_failed_at  inicio de la racha de fallos pasajeros (horizonte de 24 h, ver 8.3);
--                              se borra al enviar bien o al posponer.
--   reminders.stopped_at       cuándo se detuvo el envío. NO NULO significa "ya se generó la siguiente
--                              ocurrencia de la serie" (se crea en la misma transacción que la
--                              parada); se CONSERVA al reactivar, para no generar otra.
--   reminders.stop_reason      código estable: 'permanent:<motivo>', 'horizon:<motivo>' o 'legacy'
--                              (motivos: bot_blocked, chat_not_found, message_too_long, bad_request:<tipo>,
--                              telegram_error:<Clase>, unexpected:<Tipo>; nunca texto del usuario).
--                              NULL = no detenido. Un detenido es el que tiene stop_reason no nulo.
--   tasks.closed_reason        'discarded' | 'converted_to_reminder' | 'converted_to_note'.
--                              Las conversiones de bandeja son status='dropped' (no 'done', para no
--                              inflar las hechas); /papelera y los reportes filtran por 'discarded'.
--   Se elimina el centinela attempts=1000: las filas con ese valor pasan a stop_reason='legacy'.

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
-- Valores iniciales: briefing_time=07:30, quiet_start=22:00, quiet_end=07:00,
-- auto_threshold=0.80, ask_threshold=0.50, default_morning_time=09:00,
-- daily_proactive_cap=6, ledger_auto_save=0
-- (migración 003) meridiem_ask_range=5-11: horas sin am/pm que se preguntan en vez de adivinarse

CREATE TABLE usage_log (
  id            INTEGER PRIMARY KEY,
  ts_utc        TEXT NOT NULL,
  provider      TEXT NOT NULL,                        -- anthropic | typesafe
  model         TEXT,
  input_tokens  INTEGER, output_tokens INTEGER,
  cost_usd_est  REAL
);
```

Saldo por cuenta (la ÚNICA forma de calcularlo):

```sql
SELECT a.name, SUM(l.amount_cents) AS balance_cents
FROM ledger l JOIN accounts a ON a.id = l.account_id
WHERE l.voided = 0 GROUP BY a.id;
```

## 8. Comportamientos

### 8.1 Captura de mensajes libres (`core/capture.py`)

Todo mensaje que no sea comando entra a este pipeline:

1. Normalizar (minúsculas, sin acentos, espacios). **Guardar siempre primero** el texto original en
   una bandeja de entrada (tarea sin área) para que nada se pierda si algo falla después.
2. Interpretar fecha/hora con `parsing/recurrence.py::parse_schedule` (gramática cerrada, zona `TZ_NAME`): PRIMERO la
   repetición ("todos los lunes a las 7 pm", "cada día", "diario", "de lunes a viernes"), LUEGO la fecha suelta
   (`parsing/dates.py`). Si hay 0 fechas → sin fecha. **Principio: lo que parece fecha u hora y no se entendió se
   pregunta; nunca se descarta en silencio, y un recordatorio con la hora equivocada es peor que ninguno.**
   Se pregunta (con candidatos ya resueltos cuando los hay) si: hay más de una fecha u hora; la hora es dudosa
   (am/pm sin marcador de 5 a 11, o sin día cuando la lectura am llega antes que la pm; "12 am", "medianoche"; "7.30";
   un número suelto tras un día); la fecha ya pasó o es ambigua ("el viernes" siendo viernes, "mañana" entre las 00:00
   y las 05:00); la fecha no está soportada ("el 20 de este mes", "en 3 meses", "1ro de noviembre"); una palabra de
   repetición no encaja en la lista ("cada mes", "semanal": nunca se guarda un aviso único); "Juan 3:30" podría ser
   una hora o una cita; "domingo" podría ser un nombre ("llamar a Domingo"). Las citas bíblicas ("Juan 3:16") nunca
   son hora. El 29 de febrero va al siguiente año bisiesto real. Los códigos de pregunta y sus botones están en
   `docs/PLAN_FASE1.md` (bloque 7).
   La confirmación muestra siempre la fecha resuelta con día de la semana y botones [Cambiar] [Deshacer].
   Deuda conocida: horas inexistentes o repetidas por el horario de verano (ver el plan).
3. Extraer montos con regex (`parsing/amounts.py`). Si hay más de un número candidato → preguntar.
4. Clasificar (8.2).
5. Crear la entidad (tarea, recordatorio, nota o gasto) y responder compacto:
   `Tarea · universidad · vie 17:00   [Cambiar] [Deshacer]`.
6. Si el tipo es recordatorio y no hay hora válida: preguntar "¿Cuándo?" con botones rápidos
   (Hoy 6 pm · Mañana {default_morning_time} · Elegir...).

### 8.2 Clasificación (`classify/`)

Interfaz común (`Protocol`): `classify(text: str, areas: list[Area]) -> Classification` con
`kind`, `kind_conf`, `area`, `area_conf`, `source`, `latency_ms`. Se elige la implementación por
`CLASSIFIER`. Debe ser intercambiable sin tocar el resto del sistema.

**Orden:** (a) `rules.py` coincidencia exacta con `learned_rules` → resuelve sin llamadas externas;
(b) Jev, o Haiku si Jev no está configurado o falla; (c) preguntar.

**Jev** (`classify/jev.py`):
- `POST {TYPESAFE_BASE_URL}/v1/systemone`. **Verifica la ruta y el encabezado de autenticación en
  https://docs.typesafe.ai/api con una llamada real. No los adivines.**
- Cuerpo: `state` (solo el texto del mensaje), `model: "jev-latest"`, `questions`:
  - `tipo`: `choice` con criterios `task`, `reminder`, `note`, `expense`, `income` (descripciones en español).
  - `area`: `choice` con un criterio por cada fila **no archivada** de `areas` (usando su `description`)
    más `none`: "No encaja claramente en ninguna de las anteriores".
- Respuesta: `answers.<pregunta>.choice`, `.probabilities`, `.confidence`.
- Timeout 3 s. Cualquier error → fallback a Haiku o a "preguntar". Registrar latencia.
- Enviar SOLO el texto del mensaje. Nunca saldos ni datos del libro de cuentas.
- Los ejemplos oficiales están en inglés: validar el rendimiento en español (ver `scripts/eval_classifier.py`).

**Haiku** (`classify/haiku.py`): prompt de sistema corto y estable (se cachea); responde SOLO JSON con
`kind`, `area` y una confianza 0-1; validar con `json.loads` y try/except; `max_tokens` bajo.

**Regla de decisión** (`classify/decide.py`), aplicada a tipo y a área por separado:

```python
def decide(choice, confidence, probabilities, auto=0.80, ask=0.50):
    if choice != "none" and confidence >= auto:
        return ("auto", choice)
    if choice == "none" or confidence < ask:
        return ("new_or_ask", None)  # ofrecer categoría nueva / elegir
    top2 = [
        k
        for k, _ in sorted(probabilities.items(), key=lambda kv: kv[1], reverse=True)
        if k != "none"
    ][:2]
    return ("ask", top2)  # botones con las dos más probables
```

Los umbrales viven en `settings` y se calibran con datos reales. Si hay que preguntar por tipo y
por área, hacerlo en UN solo mensaje.

**Categoría nueva:** botones [Crear nueva] [Elegir existente] [Dejar sin área]. Si elige crear, una
llamada a Haiku propone `{"name", "description"}` (o el usuario escribe el nombre). Se confirma con
botones y se inserta en `areas`; desde la siguiente petición ya forma parte de los `criteria`.

**Aprendizaje:** cada confirmación o corrección escribe en `classification_log`. Tras 3
confirmaciones idénticas del mismo `text_norm` (sin fechas ni números) se crea una fila en
`learned_rules`.

**`scripts/eval_classifier.py`:** lee `classification_log` con etiquetas finales, ejecuta cada
clasificador disponible y reporta exactitud, matriz de confusión, latencia media y calibración
(exactitud por tramo de confianza). Sirve para comparar Jev contra Haiku con datos propios.

### 8.3 Motor de recordatorios (`core/reminders.py`)

- Un job repetitivo cada 30 s consulta `reminders` con `status='pending' AND fire_at_utc <= now()`.
- **Silencio**: dentro de `quiet_start`–`quiet_end` se retienen, salvo `priority=2`. Al terminar
  el silencio salen en orden, con la etiqueta "(retrasado)".
- **Mensaje**: `Recordatorio: {text} [{área}]` con botones `Hecho · +10 min · +1 h · Mañana 9:00`.
  `Mañana 9:00` va a `default_morning_time` del día siguiente; antes de las 05:00 locales va a HOY a esa hora
  (si todavía no pasó). En ese caso la etiqueta del botón es `Hoy 9:00` (la hora de `default_morning_time`).
- **Reloj**: el motor relee el reloj en cada envío; el silencio, el "(retrasado)" y las horas registradas
  usan la hora de ESE envío, no la del inicio del tick (un canal lento no los falsea).
- **Antes de enviar**: se relee la fila; si ya no sigue `pending` (o `sent`, en una insistencia) con la misma
  `fire_at_utc`, no se envía.
- **Tras enviar**: marcar `sent` y `last_fired_at` solo si la fila sigue `pending` con la misma `fire_at_utc`
  (se comprueban las filas afectadas). Si el usuario canceló o pospuso mientras se enviaba, no se pisa su acción:
  sin siguiente de serie y sin insistencia.
- **Fallos de envío**: el canal distingue dos clases de error.
  - *Transitorios* (red, timeout, Telegram caído): la espera es del CANAL, no de cada fila:
    `min(30 s · 2^(fallos−1), 5 min)` (30, 60, 120, 240, 300, 300…), en memoria. Al primer fallo transitorio
    de un tick no se intenta ninguno más (corta-circuito). Sin tocar `fire_at`. El **horizonte es de 24 h
    desde `first_failed_at`** (en la base: reiniciar el proceso no lo reinicia; se borra al enviar bien o
    al posponer). Los que esperaban turno empiezan su horizonte cuando el canal falla; los futuros y los de
    prioridad 1 retenidos por el silencio (que no se intentaron enviar) no lo gastan. Agotado, se detiene con
    `horizon:<motivo>`. Al volver el canal salen con "(retrasado)" y ninguno se pierde.
  - *Permanentes* (bot bloqueado, chat no encontrado): se detiene esa fila (los demás siguen) con
    `permanent:<motivo>`, el log registra el tipo de error (nunca el texto) y se marca en `/recordatorios`.
  - Un detenido queda `pending` con `stop_reason`, `stopped_at` y `stopped` verdadero; no sale solo. Se puede
    reactivar (función del motor `reactivate`; la UI llega en el bloque 7): limpia motivo, intentos y horizonte
    y, si su hora pasó, sale "(retrasado)". Reactivar una fila de serie NO crea otra siguiente: `stopped_at`
    no nulo ya significa que se generó.
- **Repetición**: si hay `rrule`, calcular la siguiente ocurrencia **a partir de la hora programada, no de
  `now()`** (evita deriva). Marcar `sent` e insertar la siguiente fila es UNA sola transacción. Re-disparar una
  fila pospuesta o reenviada NO crea otra siguiente. Si un recordatorio repetido se rinde, la serie continúa:
  detener la fila e insertar la siguiente también es UNA transacción.
- **Insistencia**: `priority=2` se reenvía cada 15 min, hasta 3 veces (`nag_count`), si no se pulsa Hecho.
  Un reenvío solo toca la fila si sigue en `sent`: hecho, cancelado o pospuesto durante el envío no se pisa.
- **Tareas**: hacer, descartar o posponer una tarea cancela sus recordatorios pendientes (también los de preparación).
  Crear una tarea con fecha, o cambiar su fecha, es UNA transacción con sus avisos de preparación (o se hace todo
  o nada); cambiar la fecha de una tarea pospuesta también rehace sus avisos.
- **Fechas pasadas**: nunca se crea un recordatorio en el pasado; se pregunta.
- **Sin solapamiento**: un tick no empieza si el anterior sigue en curso.
- **Arranque tras caída**: los vencidos se disparan con "(retrasado)"; no se pierden.
- **Sin LLM**: este módulo no importa nada de `llm/` ni `classify/`.
- **Aviso automático de preparación**: toda tarea con `due_at_utc` genera recordatorios 1 día antes
  y 1 hora antes (si esas horas aún no pasaron).
- Tope diario `daily_proactive_cap` aplica a mensajes proactivos NO críticos (nunca a recordatorios).

### 8.4 Resumen diario y "¿quitas alguna?" (`core/briefing.py`)

A `briefing_time`:
1. **Mensaje 1 — resumen por área**: vencidas, de hoy, recordatorios de hoy, y elementos de la bandeja
   con más de 2 días sin resolver.
2. **Mensaje 2 — ¿Quitas alguna?**: hasta 10 tareas numeradas con botones por tarea
   `Hecha · Posponer · Descartar`. "Posponer" ofrece mañana / elegir fecha. "Descartar" es
   soft delete (`status='dropped'`).
3. Si el usuario no responde, **silencio**: no se insiste.
4. Referencias en texto libre: "quita la 2 y la 4" por regex de números; "ya hice lo de cálculo" por una
   pregunta `choice` de Jev cuyas opciones son los títulos de las tareas abiertas (si la confianza es
   baja, mostrar las dos más probables).
5. `/papelera`: tareas descartadas de los últimos 14 días con botón [Restaurar].
6. **Revisión semanal** (domingo por la noche): lo que quedó abierto y lo pospuesto.

### 8.5 Libro de cuentas (`core/ledger.py`)

- Guardar siempre `amount_cents` entero. Gasto negativo, ingreso positivo (lo valida el `CHECK`).
- Mensaje tipo "gasté 85 en tacos con tarjeta": tipo por clasificador, monto por regex, cuenta y
  categoría por botones o por coincidencia con cuentas existentes.
- **Confirmación con botones** (Guardar / Editar / Cancelar) antes de escribir. Tras 20
  confirmaciones sin editar, ofrecer `ledger_auto_save`; siempre con botón **Deshacer**.
- `/deshacer` marca `voided=1` en el último movimiento (nunca `DELETE`).
- `/saldo` muestra el saldo por cuenta y el total, calculado con la consulta de la sección 7.
- `/ajuste <cuenta> <monto real>` inserta un movimiento `adjustment` por la diferencia, para que el
  libro coincida con la realidad y se vea cuánto se olvida anotar.
- Ni Jev ni Claude reciben saldos. El usuario no conecta ningún banco.

### 8.6 Contexto para Claude (Fase 5)

- `/contexto <área>`: arma un `.md` con la descripción del área, tareas abiertas (con fechas), notas
  recientes (20) y recordatorios próximos. **Sin dinero** salvo que se pida explícitamente.
- Se envía como documento. Si el texto ocupa ≤ ~1500 caracteres, se añade además un botón con enlace
  `https://claude.ai/new?q=<texto URL-encoded>` (precarga el prompt; no lo envía automáticamente).
- `/chat <área>`: modo conversación en Telegram con ese contexto cargado, usando Haiku. `/fin` sale
  del modo. Es de una sola vía respecto a claude.ai: el bot no ve lo que pase allí.

### 8.7 Costos y tope

- Cada llamada a Anthropic/TypeSafe escribe en `usage_log`.
- `/costos` muestra hoy, mes y estimación de cierre de mes.
- Si el mes supera `MONTHLY_API_BUDGET_USD`: se desactivan las rutas con LLM, el bot sigue
  funcionando con reglas, botones y recordatorios, y avisa una sola vez.

## 9. Comandos (no usan LLM salvo indicación)

`/start` · `/ayuda` · `/hoy [área]` · `/pendientes [área]` · `/recordatorios` · `/tarea <texto>` ·
`/nota <texto>` · `/recordar <texto>` · `/areas` · `/nuevaarea` · `/papelera` · `/saldo` ·
`/deshacer` · `/ajuste` · `/costos` · `/contexto <área>` (Fase 5) · `/chat <área>` (Fase 5, usa LLM)

## 10. Fases y criterios de aceptación

Cada fase termina con: tests en verde, `ruff check .` limpio, commit y la secuencia de verificación manual.

### Fase 0 — Esqueleto
Config, runner de migraciones, `001_init.sql`, interfaz `Channel` con `ConsoleChannel` y `TelegramChannel`
(sección 3.1), filtro de autenticación, `/start`, `/ayuda`, tests, y el modo
`--dry-run` (lee mensajes de la consola y usa clasificadores falsos; no conecta con Telegram ni con ninguna API
y no requiere ningún secreto).
- Un mensaje de un ID no autorizado no recibe respuesta alguna.
- `pytest -q` pasa. La base se crea con el esquema completo y las áreas iniciales.
- `python -m asistente.main --dry-run` arranca y responde en consola SIN ningún secreto configurado.
- Claude Code construye y prueba todo con `--dry-run` y tests; las claves reales las usa solo el dueño.
- Un test verifica que ningún módulo fuera de `channels/telegram.py` importa la librería de Telegram.

### Fase 1 — Núcleo determinista (sin ningún LLM)
Áreas, tareas, notas, recordatorios, parser de fechas propio (sin `dateparser`), motor de recordatorios, `/hoy`, `/pendientes`.
Mensaje libre → bandeja con botones manuales [Tarea][Recordatorio][Nota] + elegir área.
- Pruebas con reloj falso: recordatorio único dispara a su hora; +10 min reprograma; semanal con `rrule`
  genera la siguiente sin deriva; silencio retiene y libera; vencidos tras "caída" se disparan.
- Verificación manual: crear "recordar mañana 8am llevar tarea de cálculo", ver que llega, probar los botones.

### Fase 2 — Clasificación ágil
`classify/*`, `decide.py`, categoría nueva, `classification_log`, reglas aprendidas, `eval_classifier.py`.
- Tests de `decide()` con casos límite de umbral.
- Con un clasificador falso: auto-asigna, pregunta y ofrece categoría nueva según la confianza.
- Un archivo `tests/fixtures/phrases_es.jsonl` con ~40 frases en español y su etiqueta esperada (el dueño las revisa).
- Verificación manual con Jev real y con Haiku sobre esas frases; comparar latencia y exactitud.

### Fase 3 — Resumen y limpieza
`briefing.py`, flujo "¿quitas alguna?", `/papelera`, revisión semanal, tope de proactivos.
- El resumen sale a la hora; "Descartar" es recuperable; sin respuesta no hay insistencia.

### Fase 4 — Dinero
`ledger.py`, `/saldo`, `/deshacer`, `/ajuste`, confirmación con botones.
- Tests: suma exacta con centavos; el `CHECK` rechaza gasto positivo; `voided` excluye de la suma.
- Ningún texto enviado a Jev/Claude contiene saldos (test que revisa los payloads).

### Fase 5 — Contexto y chat
`context_pack.py`, `/contexto`, `/chat`. Aviso claro de que la ruta del enlace es de una sola vía.

### Después (no implementar sin pedirlo)
Sincronización con Google Calendar y correo (solo lectura, `gmail.readonly`).
Adaptador de WhatsApp (Cloud API) como canal secundario, solo después de la Fase 3 y respetando la sección 3.1.

## 11. Fuera de alcance

WhatsApp, enviar mensajes o correos en nombre del usuario, borrar correo, conectar bancos,
acceso a shell, interfaz web, múltiples usuarios, notas de voz.

## 12. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Un servicio externo falla | Captura primero; clasificar después; fallback a Haiku o a preguntar |
| Fatiga de notificaciones | Horas de silencio, tope de proactivos, sin insistencia en el resumen |
| Saldo desfasado | Confirmación, `/deshacer`, `/ajuste` |
| Clasificación errónea | Botón [Cambiar], log de correcciones, `eval_classifier.py`, umbrales calibrables |
| Privacidad | Solo se envía el texto del mensaje a Jev; nunca saldos; no loguear textos a nivel INFO |
| Desgaste de la tarjeta SD | Preferir SSD por USB; WAL; respaldos diarios |
| Inyección de prompts (fases futuras con correo) | Solo lectura, contenido del correo tratado como datos, confirmación para cualquier escritura |
| Gasto de IA descontrolado | `usage_log`, `/costos`, `MONTHLY_API_BUDGET_USD` |

## 13. Despliegue en la Raspberry Pi

- Raspberry Pi OS de 64 bits, Python 3.11+, entorno virtual en `venv/`.
- Servicio `deploy/asistente.service` (systemd) con `Restart=always`, `RestartSec=5`,
  `EnvironmentFile=` apuntando al `.env` con `chmod 600`, y `After=network-online.target`.
  Activar con `sudo systemctl enable --now asistente`; logs con `journalctl -u asistente -f`.
- Sin puertos abiertos (long polling). SSH solo con llave.
- `scripts/backup_db.sh`: `sqlite3 data/asistente.db ".backup 'data/backups/asistente-$(date +%F).db'"`
  diario por cron y conservar 14 días. Copiar periódicamente fuera de la tarjeta SD.
- NTP activo; la hora del sistema debe ser correcta (los recordatorios dependen de ella).
