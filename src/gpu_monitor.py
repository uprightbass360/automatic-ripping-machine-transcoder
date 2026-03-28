"""Vendor-specific GPU utilization backends."""

from __future__ import annotations

import glob
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class GpuSnapshot:
    """Point-in-time GPU metrics."""

    vendor: str
    utilization_percent: Optional[float] = None
    memory_used_mb: Optional[float] = None
    memory_total_mb: Optional[float] = None
    temperature_c: Optional[float] = None
    encoder_percent: Optional[float] = None
    power_draw_w: Optional[float] = None
    power_limit_w: Optional[float] = None
    clock_core_mhz: Optional[float] = None
    clock_memory_mhz: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


class NvidiaMonitor:
    """Query GPU metrics via nvidia-smi."""

    _CMD = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,utilization.encoder,power.draw,power.limit,clocks.current.graphics,clocks.current.memory",
        "--format=csv,noheader,nounits",
    ]

    def snapshot(self) -> GpuSnapshot:
        try:
            result = subprocess.run(
                self._CMD, capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return GpuSnapshot(vendor="nvidia")
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) < 5:
                return GpuSnapshot(vendor="nvidia")

            def _float(idx: int) -> Optional[float]:
                try:
                    return float(parts[idx])
                except (IndexError, ValueError):
                    return None

            return GpuSnapshot(
                vendor="nvidia",
                utilization_percent=_float(0),
                memory_used_mb=_float(1),
                memory_total_mb=_float(2),
                temperature_c=_float(3),
                encoder_percent=_float(4),
                power_draw_w=_float(5),
                power_limit_w=_float(6),
                clock_core_mhz=_float(7),
                clock_memory_mhz=_float(8),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            return GpuSnapshot(vendor="nvidia")


class AmdMonitor:
    """Read GPU metrics from sysfs."""

    def __init__(self, sysfs_path: str = "/sys/class/drm") -> None:
        self._sysfs_path = sysfs_path

    def _find_card(self) -> Optional[Path]:
        """Find first card directory with gpu_busy_percent file."""
        pattern = f"{self._sysfs_path}/card*/device/gpu_busy_percent"
        matches = sorted(glob.glob(pattern))
        if not matches:
            return None
        # Return the device directory (parent of gpu_busy_percent)
        return Path(matches[0]).parent

    @staticmethod
    def _read_file(path: Path) -> Optional[str]:
        try:
            return path.read_text().strip()
        except OSError:
            return None

    def snapshot(self) -> GpuSnapshot:
        device = self._find_card()
        if device is None:
            return GpuSnapshot(vendor="amd")

        utilization = None
        raw = self._read_file(device / "gpu_busy_percent")
        if raw is not None:
            try:
                utilization = float(raw)
            except ValueError:
                utilization = None

        memory_used_mb = None
        raw = self._read_file(device / "mem_info_vram_used")
        if raw is not None:
            try:
                memory_used_mb = float(raw) / (1024 * 1024)
            except ValueError:
                pass

        memory_total_mb = None
        raw = self._read_file(device / "mem_info_vram_total")
        if raw is not None:
            try:
                memory_total_mb = float(raw) / (1024 * 1024)
            except ValueError:
                pass

        temperature_c = None
        temp_files = sorted(glob.glob(str(device / "hwmon" / "hwmon*" / "temp1_input")))
        if temp_files:
            raw = self._read_file(Path(temp_files[0]))
            if raw is not None:
                try:
                    temperature_c = float(raw) / 1000.0
                except ValueError:
                    pass

        # Power: hwmon power1_average (microwatts) and power1_cap (microwatts)
        power_draw = None
        power_files = sorted(glob.glob(str(device / "hwmon" / "hwmon*" / "power1_average")))
        if power_files:
            raw = self._read_file(Path(power_files[0]))
            if raw is not None:
                try:
                    power_draw = round(float(raw) / 1_000_000, 1)
                except ValueError:
                    pass

        power_limit = None
        cap_files = sorted(glob.glob(str(device / "hwmon" / "hwmon*" / "power1_cap")))
        if cap_files:
            raw = self._read_file(Path(cap_files[0]))
            if raw is not None:
                try:
                    power_limit = round(float(raw) / 1_000_000, 1)
                except ValueError:
                    pass

        # Clocks: hwmon freq1_input (Hz, core) and freq2_input (Hz, memory)
        clock_core = None
        freq1_files = sorted(glob.glob(str(device / "hwmon" / "hwmon*" / "freq1_input")))
        if freq1_files:
            raw = self._read_file(Path(freq1_files[0]))
            if raw is not None:
                try:
                    clock_core = round(float(raw) / 1_000_000, 0)
                except ValueError:
                    pass

        clock_mem = None
        freq2_files = sorted(glob.glob(str(device / "hwmon" / "hwmon*" / "freq2_input")))
        if freq2_files:
            raw = self._read_file(Path(freq2_files[0]))
            if raw is not None:
                try:
                    clock_mem = round(float(raw) / 1_000_000, 0)
                except ValueError:
                    pass

        return GpuSnapshot(
            vendor="amd",
            utilization_percent=utilization,
            memory_used_mb=memory_used_mb,
            memory_total_mb=memory_total_mb,
            temperature_c=temperature_c,
            power_draw_w=power_draw,
            power_limit_w=power_limit,
            clock_core_mhz=clock_core,
            clock_memory_mhz=clock_mem,
        )


class IntelMonitor:
    """Query GPU metrics via intel_gpu_top."""

    _CMD = ["intel_gpu_top", "-J", "-s", "500", "-o", "-"]

    def snapshot(self) -> GpuSnapshot:
        proc = None
        try:
            proc = subprocess.Popen(
                self._CMD, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            line = proc.stdout.readline()
            if not line:
                return GpuSnapshot(vendor="intel")
            # Strip leading [ or , characters for version compatibility
            line = line.lstrip("[,").strip()
            data = json.loads(line)
            engines = data.get("engines", {})
            utilization = None
            render = engines.get("Render/3D")
            if render is not None:
                utilization = float(render.get("busy", 0))
            encoder = None
            video = engines.get("Video")
            if video is not None:
                encoder = float(video.get("busy", 0))
            return GpuSnapshot(
                vendor="intel",
                utilization_percent=utilization,
                encoder_percent=encoder,
            )
        except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError):
            return GpuSnapshot(vendor="intel")
        finally:
            if proc is not None:
                try:
                    proc.kill()
                    proc.wait()
                except OSError:
                    pass


def create_gpu_monitor(vendor: str) -> Optional[NvidiaMonitor | AmdMonitor | IntelMonitor]:
    """Factory: return the appropriate monitor for the given vendor, or None."""
    v = vendor.lower()
    if v == "nvidia":
        return NvidiaMonitor()
    if v == "amd":
        return AmdMonitor()
    if v == "intel":
        return IntelMonitor()
    return None
