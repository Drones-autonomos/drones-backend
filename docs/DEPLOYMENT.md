# Despliegue con Docker

Esta guía cubre cómo construir y desplegar la API usando Docker, tanto para entornos de staging como producción.

---

## Índice

- [Desarrollo local con Docker Compose](#desarrollo-local-con-docker-compose)
- [Dockerfile](#dockerfile)
- [Despliegue completo con Docker Compose](#despliegue-completo-con-docker-compose)
- [Variables de entorno en producción](#variables-de-entorno-en-producción)
- [Verificar que todo funciona](#verificar-que-todo-funciona)

---

## Desarrollo local con Docker Compose

La forma más rápida de tener la base de datos lista:

```bash
# Levantar solo PostgreSQL
docker-compose up -d

# Ver el estado
docker-compose ps

# Ver logs de la DB
docker-compose logs -f db

# Detener
docker-compose down

# Detener y eliminar el volumen de datos (¡borra todos los datos!)
docker-compose down -v
```

La DB queda disponible en `localhost:5432` con:

```ini
DATABASE_URL=postgresql://drone_user:drone_password@localhost:5432/drone_db
```

---

## Dockerfile

El `Dockerfile` actual en la raíz del proyecto:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

> **Nota:** El Dockerfile actual instala dependencias directamente via `pip install` en el `RUN`. Se recomienda actualizar para usar `requirements.txt` (ya hecho en el ejemplo de arriba).

### Construir la imagen

```bash
docker build -t drones-backend:latest .
```

### Correr el contenedor manualmente

```bash
docker run -d \
  --name drones-backend \
  -p 8000:8000 \
  --env-file .env \
  drones-backend:latest
```

---

## Despliegue completo con Docker Compose

Para un despliegue completo (API + DB), usa este `docker-compose.yml` de producción:

```yaml
services:
  db:
    image: postgres:15-alpine
    restart: always
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build: .
    restart: always
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
    depends_on:
      db:
        condition: service_healthy
    command: >
      sh -c "alembic upgrade head &&
             uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4"

volumes:
  postgres_data:
```

Levantar todo:

```bash
docker-compose up -d --build
```

---

## Variables de entorno en producción

En producción **nunca uses el `.env.example` directamente**. Configura las variables a través del entorno del servidor o un gestor de secretos.

```bash
# Opción 1: exportar en el shell
export DATABASE_URL="postgresql://..."
export SECRET_KEY="$(openssl rand -hex 32)"

# Opción 2: archivo .env en el servidor (no en el repo)
scp .env.prod usuario@servidor:/path/drones-backend/.env

# Opción 3: secrets de GitHub Actions / Docker Swarm / K8s
```

### Checklist de producción

- [ ] `SECRET_KEY` es aleatoria y tiene al menos 32 caracteres
- [ ] `DATABASE_URL` apunta a la DB de producción
- [ ] El `.env` **no está** en el repositorio de Git
- [ ] `DEBUG=False` (o variable equivalente)
- [ ] PostgreSQL tiene contraseña fuerte y no expone el puerto 5432 públicamente
- [ ] Se aplican las migraciones (`alembic upgrade head`) antes de arrancar

---

## Verificar que todo funciona

```bash
# Health check básico
curl http://localhost:8000/
# Respuesta esperada: {"status":"ok","message":"API Drones Autónomos activa"}

# Ver rutas disponibles
curl http://localhost:8000/openapi.json | python3 -m json.tool | grep '"path"'

# Abrir Swagger UI en el navegador
open http://localhost:8000/docs     # macOS
xdg-open http://localhost:8000/docs # Linux
```
