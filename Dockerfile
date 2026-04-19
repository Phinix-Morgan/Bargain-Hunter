# Use a lightweight Python 3.11 foundation
FROM python:3.11-slim

# Prevent Python from writing .pyc files and force stdout logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory
WORKDIR /app

# Copy the requirements file first to leverage Docker layer caching
COPY requirements.txt .

# Install core Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium engine and its required Linux system libraries
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy the rest of the application code
COPY . .

# Expose the standard Render web port
EXPOSE 10000

# Boot the application using Gunicorn
# Using 1 worker and multiple threads is ideal for Playwright's memory footprint
CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:10000", "--workers", "1", "--threads", "4", "--timeout", "120"]
