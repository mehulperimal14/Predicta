# PREDICTA 2.0 – Production Container (Universal PaaS & Docker)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production \
    PORT=5000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend, frontend, models, and configuration
COPY backend /app/backend
COPY frontend /app/frontend
COPY ml_model /app/ml_model

# Pre-generate demonstration datasets inside container
RUN python /app/backend/synthetic_generator.py

# Create non-root user (UID 1000 for standard Docker / Hugging Face Spaces compatibility)
RUN useradd -m -u 1000 predicta && \
    mkdir -p /app/backend/uploads /app/backend/sample_data /app/backend/instance && \
    chown -R predicta:predicta /app

USER predicta

EXPOSE 5000 7860 8080

WORKDIR /app/backend

# Support dynamic PORT binding for Render, Railway, Fly.io, HF Spaces, Heroku
CMD ["sh", "-c", "gunicorn -w 2 --bind 0.0.0.0:${PORT:-5000} --timeout 120 app:app"]
