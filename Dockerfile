# Multi-stage build for smaller final image
FROM python:3.14-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy only dependency files first for better layer caching
COPY pyproject.toml ./

# Install dependencies using uv
RUN uv pip install --system --no-cache -r pyproject.toml

# Final stage - minimal runtime image
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy only necessary application files
COPY app/ ./app/
COPY run.py ./

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    # Create instance directory with proper permissions
    mkdir -p instance && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app/instance

# Use non-root user
USER appuser

# Expose port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=run.py \
    FLASK_ENV=production \
    PYTHONUNBUFFERED=1

# Run the application with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "run:app"]
