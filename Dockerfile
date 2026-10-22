# Vue 只在构建时需要 Node。
FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Use an official Python runtime as a parent image
FROM python:3.11-slim-trixie

# Set environment variables to prevent Python from buffering stdout/stderr
# This is to ensure print statements appear in Docker logs
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
# This is the directory where the application code is located
# We're not using /app here because users will mount their own volumes to /app with `docker run -i -t --rm -v ./:/app`
# If we use /app here, then the local python files will override the ones in the container
# Basically, we're using /app_src and /app to split code and user local files
WORKDIR /app_src

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy only the requirements first to leverage Docker layer caching
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Add the rest of the application code
COPY . .
COPY --from=frontend /frontend/dist /app_src/frontend/dist

# Set the working directory to /app
WORKDIR /app

# Copy and configure the entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set the entrypoint script as the default command
ENTRYPOINT ["/entrypoint.sh"]
