FROM python:3.11-slim

WORKDIR /app

# Install dependencies in a separate layer so Docker cache survives source changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY *.py ./

# Non-root user for security; owns /app so SQLite DB can be created at runtime
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "tracker.py"]
