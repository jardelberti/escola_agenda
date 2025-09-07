FROM python:3.11-slim
WORKDIR /app
RUN pip install gunicorn
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
ENV DOCKER_ENV=1
CMD ["gunicorn", "--workers=2", "--bind=0.0.0.0:5000", "app:app"]