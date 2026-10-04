# Preguntas abiertas para el dueño

1. **Tu `.env` real y systemd.** `EnvironmentFile=` de systemd no quita los comentarios al final de línea
   (`ALLOWED_USER_ID=123   # mi id` se lee como el valor «123   # mi id»). El `.env.example` ya no los lleva, pero no
   leí tu `.env` real: si copiaste el ejemplo viejo y dejaste esos comentarios, quítalos antes de usar el servicio en la Pi.
   (`scripts/check_env.py`, paso 2c, lo detecta.)
