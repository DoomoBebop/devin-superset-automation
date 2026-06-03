FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONPATH=/app/src
ENV METRICS_PATH=/app/data/devin_metrics.json

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["python", "src/webhook.py"]
