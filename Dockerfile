FROM python:3.11-slim

# Instala o cliente do PostgreSQL e curl para healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install gunicorn
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 5000
ENV DOCKER_ENV=1
CMD ["gunicorn", "--workers=2", "--bind=0.0.0.0:5000", "--timeout", "60", "app:app"]