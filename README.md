# ARM Transcoder

GPU-accelerated transcoding service for [Automatic Ripping Machine](https://github.com/automatic-ripping-machine/automatic-ripping-machine).

Offloads transcoding from your ARM ripper to a separate GPU-equipped server. Supports NVIDIA NVENC, AMD VAAPI/AMF, Intel Quick Sync, and software encoding.

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/uprightbass360/automatic-ripping-machine-transcoder.git
cd arm-transcoder
cp .env.example .env
nano .env  # Set NFS_RAW_PATH and NFS_COMPLETED_PATH

# 2. Start the service
#    NVIDIA GPU:
docker compose up -d
#    AMD GPU:
#    docker compose -f docker-compose.amd.yml up -d
#    Intel QSV:
#    docker compose -f docker-compose.intel.yml up -d

# 3. Configure ARM ripper (on the ARM machine)
#    Edit arm.yaml:
#      SKIP_TRANSCODE: true
#      RIPMETHOD: "mkv"
#      DELRAWFILES: false
#      JSON_URL: "http://TRANSCODER_IP:5000/webhook/arm"

# 4. Verify
curl http://localhost:5000/health
curl http://localhost:5000/stats
```

For Proxmox LXC deployment, see [docs/proxmox-lxc-setup.md](docs/proxmox-lxc-setup.md).

## Architecture

```
┌─────────────────────────────────────┐      ┌─────────────────────────────────────┐
│         ARM Ripper Machine          │      │       GPU Transcode Machine         │
│                                     │      │                                     │
│  ┌─────────────────────────────┐   │      │   ┌─────────────────────────────┐   │
│  │     ARM Container           │   │      │   │     arm-transcoder          │   │
│  │     (MakeMKV only)          │   │      │   │     (GPU Transcoding)       │   │
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
- Hardware-accelerated transcoding: NVIDIA NVENC, AMD VAAPI/AMF, Intel Quick Sync
- Queue management with SQLite persistence
- REST API for job monitoring and management
- API key authentication with role-based access (admin/readonly)
- Input validation and path traversal protection
- Automatic source cleanup after successful transcode
- Pre-configured HandBrake presets for NVENC
- Pagination support on job listings
- Retry limits with tracking
- Disk space pre-checks

## Requirements

- Docker (with GPU runtime for hardware encoding)
- GPU with hardware encoding support:
  - **NVIDIA**: NVIDIA Container Toolkit + NVENC-capable GPU
  - **AMD**: Radeon GPU with VAAPI support + `/dev/dri` device passthrough
  - **Intel**: Quick Sync capable CPU/GPU
  - **Software**: No GPU required (slower)
- NFS (or similar) shared storage between machines
- ARM configured to skip transcoding (`SKIP_TRANSCODE: true`)

## Configuration

### Docker Environment Variables (.env)

These variables are used in `docker-compose.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `NFS_RAW_PATH` | *(required)* | Host path to ARM's raw output (NFS mount) |
| `NFS_COMPLETED_PATH` | *(required)* | Host path for completed transcodes |
| `WEBHOOK_PORT` | 5000 | Port exposed on host |
| `WEBHOOK_SECRET` | *(empty)* | Secret for webhook authentication |
| `LOG_LEVEL` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `TZ` | America/New_York | Container timezone |

### Application Settings

These are set inside the container via `docker-compose.yml` (defaults work for Docker):

| Variable | Default | Description |
|----------|---------|-------------|
| `RAW_PATH` | /data/raw | Path to raw MKV files inside container |
| `COMPLETED_PATH` | /data/completed | Path for completed transcodes inside container |
| `VIDEO_ENCODER` | nvenc_h265 | Video encoder (see [Encoder Options](#encoder-options)) |
| `VIDEO_QUALITY` | 22 | Quality (0-51, lower = better) |
| `AUDIO_ENCODER` | copy | Audio handling (`copy`, `aac`, `ac3`, `eac3`, `flac`, `mp3`) |
| `SUBTITLE_MODE` | all | Subtitle handling (`all`, `none`, `first`) |
| `DELETE_SOURCE` | true | Remove source after successful transcode |
| `HANDBRAKE_PRESET` | NVENC H.265 1080p | HandBrake preset name |
| `MAX_CONCURRENT` | 1 | Max concurrent transcodes (1 recommended for single GPU) |
| `STABILIZE_SECONDS` | 60 | Seconds to wait for source files to stop changing |
| `MAX_RETRY_COUNT` | 3 | Maximum retry attempts for failed jobs (0-10) |
| `MINIMUM_FREE_SPACE_GB` | 10 | Minimum free disk space required (GB) |
| `REQUIRE_API_AUTH` | false | Require API key for endpoints |
| `API_KEYS` | *(empty)* | Comma-separated API keys (see [Authentication](docs/AUTHENTICATION.md)) |

See `.env.example` for the full template.

### Encoder Options

| GPU | Encoder | Description |
|-----|---------|-------------|
| NVIDIA | `nvenc_h265` / `hevc_nvenc` | NVENC H.265 (best compression) |
| NVIDIA | `nvenc_h264` / `h264_nvenc` | NVENC H.264 (broader compatibility) |
| AMD | `vaapi_h265` / `hevc_vaapi` | VAAPI H.265 (Linux, recommended for AMD) |
| AMD | `vaapi_h264` / `h264_vaapi` | VAAPI H.264 (Linux) |
| AMD | `amf_h265` / `hevc_amf` | AMF H.265 |
| AMD | `amf_h264` / `h264_amf` | AMF H.264 |
| Intel | `qsv_h265` / `hevc_qsv` | Quick Sync H.265 |
| Intel | `qsv_h264` / `h264_qsv` | Quick Sync H.264 |
| None | `x265` | Software H.265 (slow, no GPU needed) |
| None | `x264` | Software H.264 (slow, no GPU needed) |

### HandBrake Presets

Pre-configured presets in `presets/nvenc_presets.json`:

- **NVENC H.265 1080p** - Best compression, modern compatibility
- **NVENC H.265 4K** - For 4K/UHD content
- **NVENC H.264 1080p** - Broader device compatibility

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | None | Health check |
| `/webhook/arm` | POST | Webhook secret | Receive ARM notifications |
| `/jobs` | GET | API key | List jobs (supports `?status=` filter, `?limit=`, `?offset=`) |
| `/jobs/{id}/retry` | POST | Admin API key | Retry a failed job |
| `/jobs/{id}` | DELETE | Admin API key | Delete a job |
| `/stats` | GET | API key | Transcoding statistics |

When `REQUIRE_API_AUTH=false` (default), API key auth is bypassed. See [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) for details.

## ARM Webhook Integration

ARM sends notifications via the `JSON_URL` setting. The transcoder accepts two formats:

**Apprise format** (default ARM notifications):
```json
{
  "title": "ARM notification",
  "body": "Rip of Movie Title (2024) complete",
  "type": "info"
}
```

**Custom format** (via ARM's `BASH_SCRIPT`):
```json
{
  "title": "Movie Title",
  "path": "Movie Title (2024)",
  "job_id": "123",
  "status": "success"
}
```

The transcoder extracts the title and looks for files in `RAW_PATH/<directory name>/`.

## Testing

The project includes 202 tests covering unit, integration, and security testing.

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run all tests
python -m pytest tests/ -v
```

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_utils.py` | 33 | PathValidator, CommandValidator, disk space, title cleaning |
| `test_models.py` | 24 | Pydantic validation, enums, data models |
| `test_auth.py` | 23 | API key auth, webhook secret, config validation |
| `test_api.py` | 15 | All API endpoints via async HTTP client |
| `test_security.py` | 31 | Path traversal, injection, payload attacks, auth bypass |
| `test_transcoder.py` | 16 | NVENC detection, file discovery, output paths, cleanup |
| `test_integration.py` | 24 | Full pipeline: job lifecycle, retry/delete, startup restore |

## Directory Structure

```
arm-transcoder/
├── docker-compose.yml          # NVIDIA GPU orchestration
├── docker-compose.amd.yml      # AMD GPU orchestration
├── docker-compose.intel.yml    # Intel QSV orchestration
├── docker-compose.dev.yml      # Development (no GPU)
├── docker-compose.security.yml # Security-hardened compose
├── Dockerfile                  # NVIDIA container build
├── Dockerfile.amd              # AMD VAAPI container build
├── Dockerfile.intel            # Intel QSV container build
├── Dockerfile.dev              # Development container build
├── requirements.txt            # Python dependencies
├── requirements-test.txt       # Test dependencies
├── .env.example                # Environment template
├── pytest.ini                  # Test configuration
├── src/
│   ├── main.py                 # FastAPI application & endpoints
│   ├── config.py               # Settings management
│   ├── models.py               # Pydantic & SQLAlchemy models
│   ├── database.py             # SQLite async setup
│   ├── transcoder.py           # Background transcode worker
│   ├── auth.py                 # API key authentication
│   ├── utils.py                # Path/command validators, utilities
│   └── constants.py            # Named constants & validation lists
├── tests/
│   ├── conftest.py             # Shared test fixtures
│   ├── test_utils.py           # Validator & utility tests
│   ├── test_models.py          # Data model tests
│   ├── test_auth.py            # Auth & config tests
│   ├── test_api.py             # API endpoint tests
│   ├── test_security.py        # Security attack tests
│   ├── test_transcoder.py      # Worker unit tests
│   └── test_integration.py     # Full pipeline tests
├── docs/
│   ├── IMPLEMENTATION_SPEC.md  # Improvement roadmap
│   ├── AUTHENTICATION.md       # Auth setup guide
│   └── proxmox-lxc-setup.md   # Proxmox deployment
├── config/
│   └── arm/
│       └── arm.yaml            # ARM config overlay
├── presets/
│   └── nvenc_presets.json      # HandBrake presets
└── scripts/
    ├── create-proxmox-lxc.sh   # Proxmox LXC setup
    └── install-lxc.sh          # LXC installation
```

## Monitoring

```bash
# View logs
docker compose logs -f arm-transcoder

# Check queue and stats
curl http://localhost:5000/stats

# List jobs (with optional filters)
curl http://localhost:5000/jobs
curl http://localhost:5000/jobs?status=failed
curl http://localhost:5000/jobs?limit=10&offset=0
```

## Troubleshooting

### GPU Not Detected

**NVIDIA** - Verify container toolkit:
```bash
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

**AMD** - Verify VAAPI device and drivers:
```bash
# Check device exists on host
ls -la /dev/dri/renderD128

# Test inside container
docker compose -f docker-compose.amd.yml exec arm-transcoder vainfo
```

**Intel QSV** - Verify Quick Sync:
```bash
# Check device exists on host
ls -la /dev/dri/renderD128

# Test inside container
docker compose -f docker-compose.intel.yml exec arm-transcoder vainfo
```

### Webhook Not Receiving

1. Check ARM logs for notification attempts
2. Verify network connectivity between machines
3. Check `JSON_URL` in ARM config matches transcoder address
4. If using `WEBHOOK_SECRET`, ensure ARM sends `X-Webhook-Secret` header

### Transcode Fails

1. Check job error: `curl http://localhost:5000/jobs?status=failed`
2. Verify source files exist in `RAW_PATH`
3. Check HandBrake supports the source format
4. Verify sufficient disk space (default minimum: 10GB free)

### Authentication Errors

See [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) for setup and troubleshooting.

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.
