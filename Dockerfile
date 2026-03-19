# syntax=docker/dockerfile:1
FROM python:3.14.3-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# Запускаем Gunicorn с 4 воркерами (можно настроить под ваше железо)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:app"]