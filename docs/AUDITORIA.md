# Auditoría de deriva: SPEC.md contra el código (2026-10-04)

Solo discrepancias reales. Tras el visto bueno del dueño se aplicaron al SPEC las marcadas «aplicado» (ver `docs/DECISIONS.md`); el código no cambió por esta auditoría. Las dos preguntas (7 y 10) quedaron resueltas por el dueño.

| # | El SPEC dice | El código hace | Resolución: SPEC cambia / código cambia / decisión del dueño |
|---|---|---|---|
| 1 | §3.1 y §8.3: botones `Mañana 9:00` y `Hoy 9:00` | `Mañana 9:00 am` y `Hoy 9:00 am` (commit `1ed5e79`, am/pm en todo) | SPEC cambia (aplicado) |
| 2 | §3.1: botones «filas de 2 como máximo» | `/pendientes` pone los números de 5 en 5 (excepción aprobada; `test_messages_catalog` la admite solo para dígitos) | SPEC cambia (aplicado) |
| 3 | §8.3: el aviso es `Recordatorio: {text} [{área}]` | Contenido en negrita y debajo `Recordatorio · área` (`formato.reminder_notice`) | SPEC cambia (aplicado) |
| 4 | §8.1 paso 5: respuesta compacta `Tarea · universidad · vie 17:00 [Cambiar] [Deshacer]` | La captura es una tarjeta que se edita: «Tarea guardada», contenido y `Área: ...` (SPEC §3.1 sí lo describe; §8.1 quedó viejo) | SPEC cambia (aplicado) |
| 5 | §8.3: «un job repetitivo cada 30 s» | El ritmo es `TICK_SECONDS` (5 a 60, por defecto 30) | SPEC cambia (aplicado) |
| 6 | §6 (`.env.example`) no tiene `TICK_SECONDS` | `config.py` y `.env.example` sí; el `.env.example` además ya no lleva comentarios al final de línea (por systemd) | SPEC cambia (aplicado) |
| 7 | §5 y §8.1: la captura vive en `core/capture.py` | No existe: está en `bot/inbox.py` (con `bot/conversation.py`, `bot/ui.py`, `bot/commands.py`); la lógica de negocio sigue en `core/` | Decisión del dueño (RESUELTA): la captura se queda en `bot/inbox.py`; SPEC actualizado; la parte pura irá en `classify/` |
| 8 | §5: `core/` = tasks, notes, reminders, briefing, ledger, context_pack | Además existen `core/areas.py`, `core/settings.py` y `core/runtime.py`; `scripts/` tiene `check_env.py`, `dev_remind_me.py`, `show_messages.py`, `show_parse_table.py`; hay `requirements-dev.txt` | SPEC cambia (aplicado) |
| 9 | §8.3: «(retrasado)» solo para lo retenido por el silencio o tras una caída | Cualquier aviso con más de 2 minutos de atraso (`LATE_GRACE`) | SPEC cambia (aplicado) |
| 10 | §8.4 punto 2: «¿Quitas alguna?» con botones por tarea `Hecha · Posponer · Descartar` | `/pendientes` ya usa otro patrón: lista numerada, un botón por número y, al abrir una, `Hecha · Descartar · Volver` en el mismo mensaje | Decisión del dueño (RESUELTA): se reutiliza el patrón de `/pendientes` (con Posponer); SPEC actualizado |
| 11 | §13: la unidad solo tiene `After=network-online.target` | La unidad añade `Wants=network-online.target` (sin él, `After` no espera a la red) | SPEC cambia (aplicado) |
| 12 | §10 Fase 0: `--dry-run` «usa clasificadores falsos» | No hay clasificadores todavía (Fase 2); el dry-run solo cambia el canal a consola y la base a `data/dry_run.db` | SPEC cambia (aplicado) |
| 13 | §9 listaba los comandos sin `/estado` | `/estado` existe (solo el dueño; ya añadido al SPEC en el paso 2d) | Ya alineado en el paso 2d |

## No son deriva (por si acaso)
Fases 2 a 5 (`classify/`, `briefing.py`, `ledger.py`, `context_pack.py`, `/papelera`, `/costos`, etc.), `anthropic` en `requirements.txt`
y `daily_proactive_cap` sin uso: el SPEC los marca como futuros. Esquema de la base, ajustes iniciales, áreas iniciales, la interfaz
`Channel`, el backoff, el horizonte de 24 h y la insistencia (15 min, 3 reenvíos) coinciden con el SPEC.