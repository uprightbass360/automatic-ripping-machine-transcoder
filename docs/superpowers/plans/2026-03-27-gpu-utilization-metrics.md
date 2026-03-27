# GPU Utilization Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose live GPU utilization (percent, VRAM, temperature, encoder activity) through the `/system/stats` API endpoint, with vendor-specific collection per Docker image layer.

**Architecture:** A new `gpu_monitor.py` module implements a base `GpuMonitor` protocol and three vendor backends (`NvidiaMonitor`, `AmdMonitor`, `IntelMonitor`). A factory function reads the `GPU_VENDOR` env var (set by each Dockerfile layer) to instantiate the correct monitor. The `/system/stats` endpoint calls `monitor.snapshot()` and includes the result as a `gpu` key (or `null` for CPU-only).

**Tech Stack:** Python subprocess (nvidia-smi, intel_gpu_top), sysfs file reads (AMD), FastAPI, pytest with unittest.mock

**Breaking Changes:** None. The `/system/stats` response gains a new `gpu` key. Existing fields are unchanged. Docker images gain a `GPU_VENDOR` env var but it defaults to empty (CPU-only), so existing deployments are unaffected.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/gpu_monitor.py` | GPU monitoring: base protocol, NVIDIA/AMD/Intel backends, factory |
| Modify | `src/config.py` | Add `gpu_vendor` setting |
| Modify | `src/main.py:78-114` | Instantiate monitor at startup, wire into `/system/stats` |
| Modify | `src/main.py:190-236` | Add `gpu` field to stats response |
| Modify | `Dockerfile.nvidia:1-7` | Add `ENV GPU_VENDOR=nvidia` |
| Modify | `Dockerfile.amd:1-7` | Add `ENV GPU_VENDOR=amd` |
| Modify | `Dockerfile.intel:1-7` | Add `ENV GPU_VENDOR=intel`, install `intel-gpu-tools` |
| Modify | `docker-compose.intel.yml` | Add `cap_add: [PERFMON]` |
| Create | `tests/test_gpu_monitor.py` | Unit tests for all GPU monitor backends + factory |
| Modify | `tests/test_main_coverage.py:252-345` | Update `/system/stats` tests to assert `gpu` key |

---

### Task 1: Add `gpu_vendor` to Settings

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: Add gpu_vendor field to Settings**

In `src/config.py`, add to the `Settings` class after the `log_level_libraries` field:

```python
# GPU monitoring
gpu_vendor: str = Field(
    "",
    description="GPU vendor for monitoring: nvidia, amd, intel, or empty for CPU-only. "
                "Set automatically by Docker image layer (Dockerfile.nvidia/amd/intel).",
)
```

- [ ] **Step 2: Verify config loads**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -c "import sys; sys.path.insert(0, 'src'); from config import settings; print(settings.gpu_vendor)"`
Expected: empty string (no GPU_VENDOR env set)

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "feat: add gpu_vendor setting for GPU monitoring selection"
```

---

### Task 2: Create `gpu_monitor.py` with tests (TDD)

**Files:**
- Create: `src/gpu_monitor.py`
- Create: `tests/test_gpu_monitor.py`

#### 2a: Define the snapshot schema and base monitor

- [ ] **Step 1: Write test for GpuSnapshot and null monitor**

Create `tests/test_gpu_monitor.py`:

```python
"""Tests for gpu_monitor — vendor-specific GPU utilization backends."""

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from gpu_monitor import GpuSnapshot, create_gpu_monitor


class TestGpuSnapshot:
    """GpuSnapshot dataclass basics."""

    def test_default_values(self):
        snap = GpuSnapshot(vendor="test")
        assert snap.vendor == "test"
        assert snap.utilization_percent is None
        assert snap.memory_used_mb is None
        assert snap.memory_total_mb is None
        assert snap.temperature_c is None
        assert snap.encoder_percent is None

    def test_to_dict(self):
        snap = GpuSnapshot(vendor="nvidia", utilization_percent=45.0, temperature_c=65.0)
        d = snap.to_dict()
        assert d["vendor"] == "nvidia"
        assert d["utilization_percent"] == 45.0
        assert d["memory_used_mb"] is None
        assert d["temperature_c"] == 65.0


class TestCreateGpuMonitor:
    """Factory function selects correct backend by GPU_VENDOR."""

    def test_empty_vendor_returns_none(self):
        monitor = create_gpu_monitor("")
        assert monitor is None

    def test_unknown_vendor_returns_none(self):
        monitor = create_gpu_monitor("potato")
        assert monitor is None

    def test_nvidia_vendor(self):
        from gpu_monitor import NvidiaMonitor
        monitor = create_gpu_monitor("nvidia")
        assert isinstance(monitor, NvidiaMonitor)

    def test_amd_vendor(self):
        from gpu_monitor import AmdMonitor
        monitor = create_gpu_monitor("amd")
        assert isinstance(monitor, AmdMonitor)

    def test_intel_vendor(self):
        from gpu_monitor import IntelMonitor
        monitor = create_gpu_monitor("intel")
        assert isinstance(monitor, IntelMonitor)

    def test_case_insensitive(self):
        from gpu_monitor import NvidiaMonitor
        monitor = create_gpu_monitor("NVIDIA")
        assert isinstance(monitor, NvidiaMonitor)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/test_gpu_monitor.py::TestGpuSnapshot -v 2>&1 | head -20`
Expected: FAIL — `ModuleNotFoundError: No module named 'gpu_monitor'`

- [ ] **Step 3: Write minimal gpu_monitor.py skeleton**

Create `src/gpu_monitor.py`:

```python
"""
GPU utilization monitoring — vendor-specific backends.

Each Docker image layer sets GPU_VENDOR (nvidia/amd/intel).
The factory ``create_gpu_monitor`` reads that value and returns the
appropriate backend, or ``None`` for CPU-only images.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GpuSnapshot:
    """Point-in-time GPU metrics.  Fields are None when unavailable."""

    vendor: str
    utilization_percent: Optional[float] = None
    memory_used_mb: Optional[float] = None
    memory_total_mb: Optional[float] = None
    temperature_c: Optional[float] = None
    encoder_percent: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


class NvidiaMonitor:
    """NVIDIA GPU monitoring via nvidia-smi."""

    def snapshot(self) -> GpuSnapshot:
        return GpuSnapshot(vendor="nvidia")


class AmdMonitor:
    """AMD GPU monitoring via sysfs."""

    def snapshot(self) -> GpuSnapshot:
        return GpuSnapshot(vendor="amd")


class IntelMonitor:
    """Intel GPU monitoring via intel_gpu_top."""

    def snapshot(self) -> GpuSnapshot:
        return GpuSnapshot(vendor="intel")


def create_gpu_monitor(vendor: str) -> Optional[NvidiaMonitor | AmdMonitor | IntelMonitor]:
    """Factory: return the monitor for *vendor*, or None for CPU-only."""
    vendor = vendor.strip().lower()
    if vendor == "nvidia":
        return NvidiaMonitor()
    if vendor == "amd":
        return AmdMonitor()
    if vendor == "intel":
        return IntelMonitor()
    return None
```

- [ ] **Step 4: Run tests to verify skeleton passes**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/test_gpu_monitor.py::TestGpuSnapshot tests/test_gpu_monitor.py::TestCreateGpuMonitor -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/gpu_monitor.py tests/test_gpu_monitor.py
git commit -m "feat: add gpu_monitor skeleton with snapshot dataclass and factory"
```

---

#### 2b: NVIDIA backend

- [ ] **Step 6: Write NVIDIA snapshot tests**

Append to `tests/test_gpu_monitor.py`:

```python
class TestNvidiaMonitor:
    """NvidiaMonitor uses nvidia-smi subprocess."""

    def test_snapshot_success(self):
        from gpu_monitor import NvidiaMonitor
        monitor = NvidiaMonitor()
        csv_output = "45, 1024, 8192, 65, 78\n"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = csv_output
        with patch("gpu_monitor.subprocess.run", return_value=mock_result) as mock_run:
            snap = monitor.snapshot()
            mock_run.assert_called_once()
            assert snap.vendor == "nvidia"
            assert snap.utilization_percent == 45.0
            assert snap.memory_used_mb == 1024.0
            assert snap.memory_total_mb == 8192.0
            assert snap.temperature_c == 65.0
            assert snap.encoder_percent == 78.0

    def test_snapshot_nvidia_smi_failure(self):
        from gpu_monitor import NvidiaMonitor
        monitor = NvidiaMonitor()
        with patch("gpu_monitor.subprocess.run", side_effect=FileNotFoundError):
            snap = monitor.snapshot()
            assert snap.vendor == "nvidia"
            assert snap.utilization_percent is None

    def test_snapshot_nvidia_smi_nonzero_exit(self):
        from gpu_monitor import NvidiaMonitor
        monitor = NvidiaMonitor()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("gpu_monitor.subprocess.run", return_value=mock_result):
            snap = monitor.snapshot()
            assert snap.utilization_percent is None

    def test_snapshot_nvidia_smi_bad_csv(self):
        from gpu_monitor import NvidiaMonitor
        monitor = NvidiaMonitor()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not,enough,fields\n"
        with patch("gpu_monitor.subprocess.run", return_value=mock_result):
            snap = monitor.snapshot()
            assert snap.utilization_percent is None

    def test_snapshot_nvidia_smi_timeout(self):
        from gpu_monitor import NvidiaMonitor
        monitor = NvidiaMonitor()
        with patch("gpu_monitor.subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 5)):
            snap = monitor.snapshot()
            assert snap.utilization_percent is None
```

`import subprocess` is already in the test file header from Step 1.

- [ ] **Step 7: Run NVIDIA tests — expect failures**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/test_gpu_monitor.py::TestNvidiaMonitor -v`
Expected: FAIL — snapshot returns stub values

- [ ] **Step 8: Implement NvidiaMonitor.snapshot()**

Replace the `NvidiaMonitor` class in `src/gpu_monitor.py`:

```python
class NvidiaMonitor:
    """NVIDIA GPU monitoring via nvidia-smi."""

    _CMD = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,utilization.encoder",
        "--format=csv,noheader,nounits",
    ]

    def snapshot(self) -> GpuSnapshot:
        try:
            result = subprocess.run(
                self._CMD, capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return GpuSnapshot(vendor="nvidia")
            parts = result.stdout.strip().split(",")
            if len(parts) < 5:
                return GpuSnapshot(vendor="nvidia")
            return GpuSnapshot(
                vendor="nvidia",
                utilization_percent=float(parts[0]),
                memory_used_mb=float(parts[1]),
                memory_total_mb=float(parts[2]),
                temperature_c=float(parts[3]),
                encoder_percent=float(parts[4]),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("nvidia-smi unavailable: %s", exc)
            return GpuSnapshot(vendor="nvidia")
        except (ValueError, IndexError) as exc:
            logger.debug("nvidia-smi parse error: %s", exc)
            return GpuSnapshot(vendor="nvidia")
```

- [ ] **Step 9: Run NVIDIA tests — expect pass**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/test_gpu_monitor.py::TestNvidiaMonitor -v`
Expected: All PASS

- [ ] **Step 10: Commit**

```bash
git add src/gpu_monitor.py tests/test_gpu_monitor.py
git commit -m "feat: implement NvidiaMonitor with nvidia-smi backend"
```

---

#### 2c: AMD backend

- [ ] **Step 11: Write AMD snapshot tests**

Append to `tests/test_gpu_monitor.py`:

```python
class TestAmdMonitor:
    """AmdMonitor reads sysfs gpu_busy_percent and VRAM files."""

    def _make_sysfs(self, tmp_path, gpu_busy="45", vram_used=None, vram_total=None, temp=None):
        """Create a fake /sys/class/drm/card0/device/ tree."""
        device = tmp_path / "card0" / "device"
        device.mkdir(parents=True)
        (device / "gpu_busy_percent").write_text(gpu_busy)
        if vram_used is not None:
            (device / "mem_info_vram_used").write_text(str(vram_used))
        if vram_total is not None:
            (device / "mem_info_vram_total").write_text(str(vram_total))
        hwmon = device / "hwmon" / "hwmon0"
        hwmon.mkdir(parents=True)
        if temp is not None:
            (hwmon / "temp1_input").write_text(str(temp))
        return tmp_path

    def test_snapshot_success(self, tmp_path):
        from gpu_monitor import AmdMonitor
        sysfs = self._make_sysfs(
            tmp_path, gpu_busy="45",
            vram_used=1073741824, vram_total=8589934592,
            temp=65000,
        )
        monitor = AmdMonitor(sysfs_path=str(sysfs))
        snap = monitor.snapshot()
        assert snap.vendor == "amd"
        assert snap.utilization_percent == 45.0
        assert snap.memory_used_mb == pytest.approx(1024.0, rel=0.1)
        assert snap.memory_total_mb == pytest.approx(8192.0, rel=0.1)
        assert snap.temperature_c == pytest.approx(65.0)

    def test_snapshot_no_sysfs(self):
        from gpu_monitor import AmdMonitor
        monitor = AmdMonitor(sysfs_path="/nonexistent/path")
        snap = monitor.snapshot()
        assert snap.vendor == "amd"
        assert snap.utilization_percent is None

    def test_snapshot_partial_sysfs(self, tmp_path):
        """Only gpu_busy_percent present, no VRAM or temp."""
        from gpu_monitor import AmdMonitor
        sysfs = self._make_sysfs(tmp_path, gpu_busy="80")
        monitor = AmdMonitor(sysfs_path=str(sysfs))
        snap = monitor.snapshot()
        assert snap.utilization_percent == 80.0
        assert snap.memory_used_mb is None
        assert snap.temperature_c is None

    def test_snapshot_bad_gpu_busy_value(self, tmp_path):
        from gpu_monitor import AmdMonitor
        sysfs = self._make_sysfs(tmp_path, gpu_busy="not_a_number")
        monitor = AmdMonitor(sysfs_path=str(sysfs))
        snap = monitor.snapshot()
        assert snap.utilization_percent is None
```

- [ ] **Step 12: Run AMD tests — expect failures**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/test_gpu_monitor.py::TestAmdMonitor -v`
Expected: FAIL

- [ ] **Step 13: Implement AmdMonitor.snapshot()**

Replace the `AmdMonitor` class in `src/gpu_monitor.py`:

```python
class AmdMonitor:
    """AMD GPU monitoring via sysfs (amdgpu kernel driver)."""

    def __init__(self, sysfs_path: str = "/sys/class/drm"):
        self._sysfs = Path(sysfs_path)

    def _read_sysfs(self, *parts: str) -> Optional[str]:
        try:
            return (self._sysfs / Path(*parts)).read_text().strip()
        except (FileNotFoundError, OSError):
            return None

    def _find_card_device(self) -> Optional[Path]:
        """Find the first card with an amdgpu gpu_busy_percent file."""
        try:
            for card in sorted(self._sysfs.glob("card[0-9]*")):
                if (card / "device" / "gpu_busy_percent").exists():
                    return card / "device"
        except OSError:
            pass
        return None

    def snapshot(self) -> GpuSnapshot:
        device = self._find_card_device()
        if device is None:
            return GpuSnapshot(vendor="amd")

        rel = device.relative_to(self._sysfs)

        util = None
        raw = self._read_sysfs(str(rel), "gpu_busy_percent")
        if raw is not None:
            try:
                util = float(raw)
            except ValueError:
                pass

        mem_used = None
        raw = self._read_sysfs(str(rel), "mem_info_vram_used")
        if raw is not None:
            try:
                mem_used = round(int(raw) / 1048576, 1)
            except ValueError:
                pass

        mem_total = None
        raw = self._read_sysfs(str(rel), "mem_info_vram_total")
        if raw is not None:
            try:
                mem_total = round(int(raw) / 1048576, 1)
            except ValueError:
                pass

        temp = None
        try:
            for hwmon in sorted((device / "hwmon").iterdir()):
                temp_file = hwmon / "temp1_input"
                if temp_file.exists():
                    temp = round(int(temp_file.read_text().strip()) / 1000, 1)
                    break
        except (FileNotFoundError, OSError, ValueError):
            pass

        return GpuSnapshot(
            vendor="amd",
            utilization_percent=util,
            memory_used_mb=mem_used,
            memory_total_mb=mem_total,
            temperature_c=temp,
        )
```

- [ ] **Step 14: Run AMD tests — expect pass**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/test_gpu_monitor.py::TestAmdMonitor -v`
Expected: All PASS

- [ ] **Step 15: Commit**

```bash
git add src/gpu_monitor.py tests/test_gpu_monitor.py
git commit -m "feat: implement AmdMonitor with sysfs backend"
```

---

#### 2d: Intel backend

- [ ] **Step 16: Write Intel snapshot tests**

Append to `tests/test_gpu_monitor.py`:

```python
class TestIntelMonitor:
    """IntelMonitor uses intel_gpu_top -J subprocess."""

    def test_snapshot_success(self):
        from gpu_monitor import IntelMonitor
        monitor = IntelMonitor()
        json_output = json.dumps({
            "period": {"duration": 1000.0, "unit": "ms"},
            "engines": {
                "Render/3D": {"busy": 12.3},
                "Blitter": {"busy": 0.0},
                "Video": {"busy": 78.5},
                "VideoEnhance": {"busy": 5.0},
            },
        }) + "\n"
        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = json_output
        mock_proc.poll.return_value = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = MagicMock()
        with patch("gpu_monitor.subprocess.Popen", return_value=mock_proc):
            snap = monitor.snapshot()
            assert snap.vendor == "intel"
            assert snap.utilization_percent == pytest.approx(12.3)
            assert snap.encoder_percent == pytest.approx(78.5)

    def test_snapshot_intel_gpu_top_missing(self):
        from gpu_monitor import IntelMonitor
        monitor = IntelMonitor()
        with patch("gpu_monitor.subprocess.Popen", side_effect=FileNotFoundError):
            snap = monitor.snapshot()
            assert snap.vendor == "intel"
            assert snap.utilization_percent is None

    def test_snapshot_intel_gpu_top_bad_json(self):
        from gpu_monitor import IntelMonitor
        monitor = IntelMonitor()
        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = "not json\n"
        mock_proc.poll.return_value = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = MagicMock()
        with patch("gpu_monitor.subprocess.Popen", return_value=mock_proc):
            snap = monitor.snapshot()
            assert snap.utilization_percent is None

    def test_snapshot_intel_gpu_top_empty_output(self):
        from gpu_monitor import IntelMonitor
        monitor = IntelMonitor()
        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = ""
        mock_proc.poll.return_value = 1
        mock_proc.kill = MagicMock()
        mock_proc.wait = MagicMock()
        with patch("gpu_monitor.subprocess.Popen", return_value=mock_proc):
            snap = monitor.snapshot()
            assert snap.utilization_percent is None

    def test_snapshot_intel_gpu_top_timeout(self):
        from gpu_monitor import IntelMonitor
        monitor = IntelMonitor()
        with patch("gpu_monitor.subprocess.Popen", side_effect=OSError("permission denied")):
            snap = monitor.snapshot()
            assert snap.utilization_percent is None
```

- [ ] **Step 17: Run Intel tests — expect failures**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/test_gpu_monitor.py::TestIntelMonitor -v`
Expected: FAIL

- [ ] **Step 18: Implement IntelMonitor.snapshot()**

Replace the `IntelMonitor` class in `src/gpu_monitor.py`:

```python
class IntelMonitor:
    """Intel GPU monitoring via intel_gpu_top -J."""

    _CMD = ["intel_gpu_top", "-J", "-s", "500", "-o", "-"]

    def snapshot(self) -> GpuSnapshot:
        proc = None
        try:
            proc = subprocess.Popen(
                self._CMD, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            line = proc.stdout.readline()
            if not line:
                return GpuSnapshot(vendor="intel")
            # Some versions emit JSON array wrapper or comma separators
            line = line.lstrip("[,").rstrip(",]\n").strip()
            if not line:
                return GpuSnapshot(vendor="intel")
            data = json.loads(line)
            engines = data.get("engines", {})
            render = engines.get("Render/3D", {}).get("busy")
            video = engines.get("Video", {}).get("busy")
            return GpuSnapshot(
                vendor="intel",
                utilization_percent=render,
                encoder_percent=video,
            )
        except (FileNotFoundError, OSError) as exc:
            logger.debug("intel_gpu_top unavailable: %s", exc)
            return GpuSnapshot(vendor="intel")
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.debug("intel_gpu_top parse error: %s", exc)
            return GpuSnapshot(vendor="intel")
        finally:
            if proc is not None:
                proc.kill()
                proc.wait()
```

- [ ] **Step 19: Run Intel tests — expect pass**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/test_gpu_monitor.py::TestIntelMonitor -v`
Expected: All PASS

- [ ] **Step 20: Commit**

```bash
git add src/gpu_monitor.py tests/test_gpu_monitor.py
git commit -m "feat: implement IntelMonitor with intel_gpu_top backend"
```

---

### Task 3: Wire GPU monitor into main.py

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_main_coverage.py`

- [ ] **Step 1: Write tests for gpu field in /system/stats**

Add to `tests/test_main_coverage.py` inside `TestSystemStatsEndpoint`:

```python
    @pytest.mark.asyncio
    async def test_system_stats_includes_gpu_null_when_no_monitor(self, client):
        """GPU field is null when no GPU monitor is configured."""
        ac, _ = client
        mock_mem = MagicMock()
        mock_mem.total = 17179869184
        mock_mem.used = 8589934592
        mock_mem.available = 8589934592
        mock_mem.percent = 50.0

        with patch("main.psutil.cpu_percent", return_value=10.0), \
             patch("main.psutil.sensors_temperatures", return_value={}), \
             patch("main.psutil.virtual_memory", return_value=mock_mem), \
             patch("main.psutil.disk_usage", side_effect=FileNotFoundError), \
             patch("main._gpu_monitor", None):
            response = await ac.get("/system/stats")
            data = response.json()
            assert data["gpu"] is None

    @pytest.mark.asyncio
    async def test_system_stats_includes_gpu_snapshot(self, client):
        """GPU field contains snapshot when monitor is configured."""
        ac, _ = client
        mock_mem = MagicMock()
        mock_mem.total = 17179869184
        mock_mem.used = 8589934592
        mock_mem.available = 8589934592
        mock_mem.percent = 50.0

        mock_monitor = MagicMock()
        mock_snap = {
            "vendor": "nvidia",
            "utilization_percent": 45.0,
            "memory_used_mb": 1024.0,
            "memory_total_mb": 8192.0,
            "temperature_c": 65.0,
            "encoder_percent": 78.0,
        }
        mock_monitor.snapshot.return_value = MagicMock(to_dict=MagicMock(return_value=mock_snap))

        with patch("main.psutil.cpu_percent", return_value=10.0), \
             patch("main.psutil.sensors_temperatures", return_value={}), \
             patch("main.psutil.virtual_memory", return_value=mock_mem), \
             patch("main.psutil.disk_usage", side_effect=FileNotFoundError), \
             patch("main._gpu_monitor", mock_monitor):
            response = await ac.get("/system/stats")
            data = response.json()
            assert data["gpu"]["vendor"] == "nvidia"
            assert data["gpu"]["utilization_percent"] == 45.0
            assert data["gpu"]["encoder_percent"] == 78.0

    @pytest.mark.asyncio
    async def test_system_stats_gpu_snapshot_exception(self, client):
        """GPU field is null when monitor.snapshot() raises."""
        ac, _ = client
        mock_mem = MagicMock()
        mock_mem.total = 17179869184
        mock_mem.used = 8589934592
        mock_mem.available = 8589934592
        mock_mem.percent = 50.0

        mock_monitor = MagicMock()
        mock_monitor.snapshot.side_effect = RuntimeError("GPU hung")

        with patch("main.psutil.cpu_percent", return_value=10.0), \
             patch("main.psutil.sensors_temperatures", return_value={}), \
             patch("main.psutil.virtual_memory", return_value=mock_mem), \
             patch("main.psutil.disk_usage", side_effect=FileNotFoundError), \
             patch("main._gpu_monitor", mock_monitor):
            response = await ac.get("/system/stats")
            assert response.json()["gpu"] is None
```

- [ ] **Step 2: Run tests — expect failures**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/test_main_coverage.py::TestSystemStatsEndpoint::test_system_stats_includes_gpu_null_when_no_monitor -v`
Expected: FAIL

- [ ] **Step 3: Modify main.py — add monitor global and wire startup**

In `src/main.py`, add import at top (after existing imports):

```python
from gpu_monitor import create_gpu_monitor
```

After the `worker` global (line 75), add:

```python
_gpu_monitor: object | None = None
```

In the `lifespan` function, after `worker = TranscodeWorker(gpu_support=gpu_support)` (line 94), add:

```python
    global _gpu_monitor
    _gpu_monitor = create_gpu_monitor(settings.gpu_vendor)
    if _gpu_monitor:
        logger.info("GPU monitor active: %s", settings.gpu_vendor)
```

- [ ] **Step 4: Modify /system/stats to include gpu field**

In `src/main.py`, in the `get_system_stats()` function, add before the `return` statement:

```python
    gpu_data = None
    if _gpu_monitor is not None:
        try:
            gpu_data = _gpu_monitor.snapshot().to_dict()
        except Exception:
            pass
```

And add `"gpu": gpu_data,` to the return dict (after the `"storage"` key).

- [ ] **Step 5: Run tests — expect pass**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/test_main_coverage.py::TestSystemStatsEndpoint -v`
Expected: All PASS (including existing tests — they should still pass since `gpu_monitor` global defaults to None)

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main_coverage.py
git commit -m "feat: wire GPU monitor into /system/stats endpoint"
```

---

### Task 4: Docker image layers

**Files:**
- Modify: `Dockerfile.nvidia`
- Modify: `Dockerfile.amd`
- Modify: `Dockerfile.intel`
- Modify: `docker-compose.intel.yml`

- [ ] **Step 1: Add GPU_VENDOR to Dockerfile.nvidia**

Append before the final line (or at end):

```dockerfile
ENV GPU_VENDOR=nvidia
```

- [ ] **Step 2: Add GPU_VENDOR to Dockerfile.amd**

Append after the RUN block:

```dockerfile
ENV GPU_VENDOR=amd
```

- [ ] **Step 3: Update Dockerfile.intel — add GPU_VENDOR and intel-gpu-tools**

Replace the RUN block and add env:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    intel-media-va-driver libvpl2 intel-gpu-tools \
    && rm -rf /var/lib/apt/lists/*

ENV GPU_VENDOR=intel
```

- [ ] **Step 4: Add CAP_PERFMON to docker-compose.intel.yml**

Add after `group_add` block in `docker-compose.intel.yml`:

```yaml
    cap_add:
      - PERFMON
```

- [ ] **Step 5: Add /sys mount for AMD docker-compose**

The AMD sysfs monitor needs `/sys` readable (entries under `/sys/class/drm/` are symlinks into `/sys/devices/`, so we must mount the whole `/sys` tree). Add a read-only volume to `docker-compose.amd.yml` in the `volumes` section:

```yaml
      - /sys:/sys:ro
```

- [ ] **Step 6: Commit**

```bash
git add Dockerfile.nvidia Dockerfile.amd Dockerfile.intel docker-compose.amd.yml docker-compose.intel.yml
git commit -m "feat: set GPU_VENDOR env in Docker layers, add intel-gpu-tools and capabilities"
```

---

### Task 5: Full test suite + coverage check

- [ ] **Step 1: Run full test suite**

Run: `cd /home/upb/src/automatic-ripping-machine-transcoder && python3 -m pytest tests/ -v --cov=src --cov-report=term-missing 2>&1 | tail -40`
Expected: All tests pass, no regressions

- [ ] **Step 2: Check new file coverage**

Verify `gpu_monitor.py` has >90% coverage in the report. If any uncovered lines, add targeted tests.

- [ ] **Step 3: Run security check — no secrets, no injection vectors**

Review: `gpu_monitor.py` uses only hardcoded command arrays (no shell=True, no user input in commands). sysfs reads use Path objects with no user-controlled segments. Confirm no issues.

- [ ] **Step 4: Commit any coverage gap fixes**

Only if needed.

---

### Task 6: Create PR

- [ ] **Step 1: Push branch and create PR**

```bash
git push -u origin feat/gpu-utilization-metrics
```

PR title: `feat: expose GPU utilization metrics in /system/stats`

PR body should cover:
- What: New `gpu` field in `/system/stats` with vendor-specific GPU metrics
- How: `GPU_VENDOR` env var set by Docker layers, factory pattern selects backend
- Backends: nvidia-smi (NVIDIA), sysfs (AMD), intel_gpu_top (Intel)
- Breaking changes: None — additive API change, new optional env var
- Docker changes: Dockerfile.intel gains `intel-gpu-tools`, compose.intel gains `cap_add: [PERFMON]`, compose.amd gains `/sys/class/drm` mount
