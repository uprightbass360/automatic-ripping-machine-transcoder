# ARM Transcoder

> **Created:** February 6, 2026

GPU-accelerated transcoding service for [Automatic Ripping Machine](https://github.com/automatic-ripping-machine/automatic-ripping-machine).

This service allows you to offload transcoding from your ARM ripper machine to a separate GPU-equipped server, improving ripping throughput and utilizing hardware encoding.

## Deployment Options

| Method | Best For | GPU Access |
|--------|----------|------------|
| **Proxmox LXC** | Existing Proxmox setup with GPU passthrough | Direct device passthrough |
| **Docker** | Standalone Linux with NVIDIA Container Toolkit | nvidia-docker runtime |

## Architecture

```
┌─────────────────────────────────────┐      ┌─────────────────────────────────────┐
│         ARM Ripper Machine          │      │       GPU Transcode Machine         │
│                                     │      │                                     │
│  ┌─────────────────────────────┐   │      │   ┌─────────────────────────────┐   │
│  │     ARM Container           │   │      │   │     arm-transcoder          │   │
│  │     (MakeMKV only)          │   │      │   │     (HandBrake + NVENC)     │   │
│  └──────────────┬──────────────┘   │      │   └──────────────┬──────────────┘   │
│                 │                  │      │                  │                  │
│                 │ webhook          │      │                  │                  │
│                 ▼                  │      │                  ▼                  │
│  ┌──────────────────────────────────┴──────┴──────────────────────────────────┐ │
│  │                         NFS Shared Storage                                  │ │
│  │  /raw/           - MakeMKV output (read by transcoder)                     │ │
│  │  /completed/     - Final transcoded files                                  │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Features

- Webhook receiver for ARM job completion notifications
- NVIDIA NVENC hardware-accelerated transcoding
- Queue management with SQLite persistence
- REST API for job monitoring and management
- **Simple header-based authentication** (API keys)
- **Input validation** to prevent security issues
- Automatic source cleanup after successful transcode
- Pre-configured HandBrake presets for NVENC
- Pagination support on job listings
- Retry limits with tracking

## Requirements

- Docker with NVIDIA Container Toolkit
- NVIDIA GPU with NVENC support
- NFS (or similar) shared storage between machines
- ARM configured to skip transcoding

## Quick Start

### Option A: Proxmox LXC (Recommended for Proxmox users)

See [docs/proxmox-lxc-setup.md](docs/proxmox-lxc-setup.md) for detailed instructions.

```bash
# On Proxmox host - create and configure LXC
./scripts/create-proxmox-lxc.sh 108 192.168.0.88

# Inside the LXC - install NVIDIA driver (same version as host)
wget https://us.download.nvidia.com/XFree86/Linux-x86_64/580.119.02/NVIDIA-Linux-x86_64-580.119.02.run
./NVIDIA-Linux-x86_64-580.119.02.run --no-kernel-module

# Install arm-transcoder
./install-lxc.sh
nano /etc/arm-transcoder.env
systemctl start arm-transcoder
```

### Option B: Docker (Standalone Linux)

```bash
git clone https://github.com/uprightbass360/automatic-ripping-machine-transcoder.git
cd arm-transcoder

cp .env.example .env
nano .env

docker compose up -d
```

### Configure ARM Ripper

Update your ARM's `arm.yaml`:

```yaml
SKIP_TRANSCODE: true
RIPMETHOD: "mkv"
DELRAWFILES: false
JSON_URL: "http://TRANSCODER_IP:5000/webhook/arm"
```

### Verify

```bash
curl http://localhost:5000/health
curl http://localhost:5000/stats
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NFS_RAW_PATH` | - | Path to ARM's raw output (NFS mount) |
| `NFS_COMPLETED_PATH` | - | Path for completed transcodes |
| `WEBHOOK_PORT` | 5000 | Port for webhook receiver |
| `HANDBRAKE_PRESET` | NVENC H.265 1080p | HandBrake preset name |
| `VIDEO_ENCODER` | nvenc_h265 | Video encoder |
| `VIDEO_QUALITY` | 22 | Quality (lower = better) |
| `AUDIO_ENCODER` | copy | Audio handling |
| `DELETE_SOURCE` | true | Remove source after transcode |

See `.env.example` for full list.

### HandBrake Presets

Pre-configured presets in `presets/nvenc_presets.json`:

- **NVENC H.265 1080p** - Best compression, modern compatibility
- **NVENC H.265 4K** - For 4K/UHD content
- **NVENC H.264 1080p** - Broader device compatibility

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/webhook/arm` | POST | Receive ARM notifications |
| `/jobs` | GET | List all jobs |
| `/jobs?status=pending` | GET | Filter jobs by status |
| `/jobs/{id}/retry` | POST | Retry a failed job |
| `/jobs/{id}` | DELETE | Delete a job |
| `/stats` | GET | Transcoding statistics |

## ARM Webhook Integration

ARM sends notifications via the `JSON_URL` setting. The transcoder expects:

```json
{
  "title": "ARM notification - Rip of Movie Title (2024) complete",
  "body": "Rip of Movie Title (2024) complete",
  "type": "info"
}
```

The transcoder extracts the title and looks for files in `RAW_PATH/Movie Title (2024)/`.

## Directory Structure

```
arm-transcoder/
├── docker-compose.yml    # Container orchestration
├── Dockerfile           # Container build
├── requirements.txt     # Python dependencies
├── .env.example        # Environment template
├── src/
│   ├── main.py         # FastAPI application
│   ├── config.py       # Settings management
│   ├── models.py       # Data models
│   ├── database.py     # SQLite setup
│   └── transcoder.py   # Transcode worker
├── config/
│   └── arm/
│       └── arm.yaml    # ARM config overlay
└── presets/
    └── nvenc_presets.json  # HandBrake presets
```

## Monitoring

### View Logs

```bash
docker compose logs -f arm-transcoder
```

### Check Queue

```bash
curl http://localhost:5000/stats
```

### List Jobs

```bash
curl http://localhost:5000/jobs
```

## Troubleshooting

### GPU Not Detected

Verify NVIDIA container toolkit:
```bash
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

### Webhook Not Receiving

1. Check ARM logs for notification attempts
2. Verify network connectivity between machines
3. Check `JSON_URL` in ARM config matches transcoder address

### Transcode Fails

1. Check job error in API: `curl http://localhost:5000/jobs`
2. Verify source files exist in `RAW_PATH`
3. Check HandBrake supports the source format

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.
