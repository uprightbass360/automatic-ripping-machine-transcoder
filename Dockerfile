FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

# Install system dependencies and HandBrake CLI from PPA
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    mediainfo \
    curl \
    libva2 \
    libva-drm2 \
    libdrm2 \
    software-properties-common \
    && add-apt-repository -y ppa:stebbins/handbrake-releases \
    && apt-get update \
    && apt-get install -y --no-install-recommends handbrake-cli \
    && apt-get remove -y software-properties-common \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -s /bin/bash transcoder

# Setup Python environment
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ /app/
COPY presets/ /config/presets/

# Create data directories
RUN mkdir -p /data/raw /data/completed /data/work /data/db \
    && chown -R transcoder:transcoder /data /app /config

USER transcoder

EXPOSE 5000

CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
