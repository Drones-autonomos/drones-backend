FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema requeridas para algunas librerías
RUN apt-get update && apt-get install -y gcc default-libmysqlclient-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Si estás usando pipeno o poetry, puedes ajustarlo aquí
RUN pip install uvicorn fastapi pydantic psycopg2-binary sqlalchemy alembic dronekit 

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
