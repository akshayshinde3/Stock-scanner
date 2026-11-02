FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces requires port 7860
EXPOSE 7860

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:7860 --workers 1 --threads 4 --timeout 120 app:app"]
