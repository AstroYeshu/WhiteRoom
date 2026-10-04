# Preguntas abiertas para el dueño

1. **Tu `.env` real y systemd.** `EnvironmentFile=` de systemd no quita los comentarios al final de línea
   (`ALLOWED_USER_ID=123   # mi id` se lee como el valor «123   # mi id»). El `.env.example` ya no los lleva, pero no
   leí tu `.env` real: si copiaste el ejemplo viejo y dejaste esos comentarios, quítalos antes de usar el servicio en la Pi.
   (`scripts/check_env.py` lo detecta: punto «Archivo .env».)

2. **Auditoría 7: ¿dónde vive la captura?** El SPEC dice `core/capture.py`; el código la tiene en `bot/inbox.py` (mezcla conversación y
   lógica). Opciones: (a) el SPEC adopta el nombre real, o (b) se mueve a `core/` lo que no sea conversación. No toqué ni el SPEC ni el código.
3. **Auditoría 10: «¿Quitas alguna?» de la Fase 3.** El SPEC pide botones por tarea (`Hecha · Posponer · Descartar`); `/pendientes` ya usa
   lista numerada, un botón por número y `Hecha · Descartar · Volver` en el mismo mensaje. ¿Reutilizamos el patrón de `/pendientes` (con Posponer
   como botón nuevo) o se mantiene el del SPEC? Hay que decidirlo antes de la Fase 3.
4. **`time-sync.target` en la Pi.** Lo añadí a la unidad con el comentario «verificar en la Pi»: confirma con `systemctl list-units --type=target | grep time-sync`.
