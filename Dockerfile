# Dockerfile
FROM python:3.11-slim

# system deps for many python packages and pillow etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# set workdir
WORKDIR /app

# copy only what we need first for caching
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# copy app code
COPY . .

# create a non-root user for safety (optional)
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=5000
EXPOSE 5000

# Use Gunicorn with 4 workers (adjust as needed)
# `-b 0.0.0.0:5000` binds to container port 5000
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:5000", "app:app", "--worker-class", "gthread", "--threads", "4"]
