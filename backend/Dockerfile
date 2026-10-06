FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Create data directory for SQLite
RUN mkdir -p /app/data

# Expose port
EXPOSE 8000

# Run migrations then start server
CMD ["sh", "-c", "python -c 'from app.database import Base; import asyncio; from app.database import init_db; asyncio.run(init_db())' && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
