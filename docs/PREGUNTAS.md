# Preguntas para el dueño

## Abiertas
1. **Tu `.env` real y systemd.** `EnvironmentFile=` de systemd no quita los comentarios al final de línea
   (`ALLOWED_USER_ID=123   # mi id` se lee como el valor «123   # mi id»). El `.env.example` ya no los lleva, pero no
   leí tu `.env` real: si copiaste el ejemplo viejo y dejaste esos comentarios, quítalos antes de usar el servicio en la Pi.
   (`scripts/check_env.py` lo detecta: punto «Archivo .env».)

## Cerradas
- **Hooks de git.** Activos en este clon (pre-commit: ruff + suite rápida; pre-push: suite completa).
- **Auditoría 7: dónde vive la captura.** La captura permanece en `bot/inbox.py` y el SPEC se actualizó; la parte pura (reglas,
  clasificador, decisión) irá en `classify/`. Ver DECISIONS.md.
- **Auditoría 10: «¿Quitas alguna?».** Reutiliza el patrón de `/pendientes`: lista numerada, botones por número y detalle con Hecha,
  Descartar, Posponer y Volver. Ver DECISIONS.md.
- **`time-sync.target`.** Queda por verificar en la Pi (`systemctl list-units --type=target | grep time-sync`); la unidad ya lo trae con
  el comentario «verificar en la Pi».
