# Use the official slim image (recommended)
FROM python:3.11-slim

# Avoid generation of .pyc files and buffer issues
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    FLASK_ENV=production

# Install system deps needed for building common Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential gcc libpq-dev curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
# Assumes requirements.txt is at repo root
COPY requirements.txt /app/requirements.txt

# Install Python deps
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app code (assumes app.py, templates/, static/ live next to this Dockerfile)
COPY . /app

# Create a non-root user to run the app (safer)
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 5000

# Optional healthcheck (exec runs as appuser)
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 CMD curl -f http://localhost:5000/health || exit 1

# Run with gunicorn. This assumes your Flask app object is `app` inside app.py (module path "app:app").
# If your app module or variable differs, change "app:app" accordingly.
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
