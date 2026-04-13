"""
Tests for config.py - settings validation, preset discovery, GPU auto-resolution,
and config override loading.
"""

import json
import os
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text

from config import (
    Settings,
    UPDATABLE_KEYS,
    GPU_PRESET_DEFAULTS,
    detect_best_gpu,
    get_presets_by_file,
    get_available_presets,
    get_preset_files,
)
from models import Base, ConfigOverrideDB


# ─── Settings Validation ─────────────────────────────────────────────────────


class TestSettingsValidation:
    """Tests for Settings field validators."""

    def test_valid_video_encoder(self):
        s = Settings(video_encoder="x265")
        assert s.video_encoder == "x265"

    def test_invalid_video_encoder_rejected(self):
        with pytest.raises(Exception, match="Invalid video encoder"):
            Settings(video_encoder="nonexistent_encoder")

    def test_valid_audio_encoder(self):
        s = Settings(audio_encoder="aac")
        assert s.audio_encoder == "aac"

    def test_invalid_audio_encoder_rejected(self):
        with pytest.raises(Exception, match="Invalid audio encoder"):
            Settings(audio_encoder="bad_audio")

    def test_valid_subtitle_mode(self):
        s = Settings(subtitle_mode="none")
        assert s.subtitle_mode == "none"

    def test_invalid_subtitle_mode_rejected(self):
        with pytest.raises(Exception, match="Invalid subtitle mode"):
            Settings(subtitle_mode="invalid_mode")

    def test_log_level_uppercase_normalization(self):
        s = Settings(log_level="debug")
        assert s.log_level == "DEBUG"

    def test_log_level_libraries_uppercase(self):
        s = Settings(log_level_libraries="error")
        assert s.log_level_libraries == "ERROR"

    def test_invalid_log_level_rejected(self):
        with pytest.raises(Exception, match="Invalid log level"):
            Settings(log_level="TRACE")


# ─── Preset Discovery ────────────────────────────────────────────────────────


class TestGetPresetsByFile:
    """Tests for get_presets_by_file()."""

    def test_returns_empty_when_dir_missing(self, tmp_path):
        from config import settings

        with patch.object(settings, "preset_path", str(tmp_path / "nonexistent")):
            result = get_presets_by_file()
            assert result == {}

    def test_finds_presets_in_json_files(self, tmp_path):
        from config import settings

        preset_data = {
            "PresetList": [
                {"PresetName": "My Preset 1080p"},
                {"PresetName": "My Preset 4K"},
            ]
        }
        (tmp_path / "custom.json").write_text(json.dumps(preset_data))

        with patch.object(settings, "preset_path", str(tmp_path)):
            result = get_presets_by_file()
            assert len(result) == 1
            key = list(result.keys())[0]
            assert "custom.json" in key
            assert "My Preset 1080p" in result[key]
            assert "My Preset 4K" in result[key]

    def test_skips_invalid_json(self, tmp_path):
        from config import settings

        (tmp_path / "bad.json").write_text("not valid json {{{")

        with patch.object(settings, "preset_path", str(tmp_path)):
            result = get_presets_by_file()
            assert result == {}

    def test_skips_files_without_presets(self, tmp_path):
        from config import settings

        (tmp_path / "empty.json").write_text(json.dumps({"PresetList": []}))

        with patch.object(settings, "preset_path", str(tmp_path)):
            result = get_presets_by_file()
            assert result == {}

    def test_skips_presets_without_name(self, tmp_path):
        from config import settings

        preset_data = {
            "PresetList": [
                {"PresetName": ""},
                {"OtherField": "value"},
                {"PresetName": "Valid Preset"},
            ]
        }
        (tmp_path / "mixed.json").write_text(json.dumps(preset_data))

        with patch.object(settings, "preset_path", str(tmp_path)):
            result = get_presets_by_file()
            key = list(result.keys())[0]
            assert result[key] == ["Valid Preset"]

    def test_multiple_files(self, tmp_path):
        from config import settings

        (tmp_path / "a.json").write_text(json.dumps({
            "PresetList": [{"PresetName": "Preset A"}]
        }))
        (tmp_path / "b.json").write_text(json.dumps({
            "PresetList": [{"PresetName": "Preset B"}]
        }))

        with patch.object(settings, "preset_path", str(tmp_path)):
            result = get_presets_by_file()
            assert len(result) == 2
            all_names = []
            for names in result.values():
                all_names.extend(names)
            assert "Preset A" in all_names
            assert "Preset B" in all_names


class TestGetAvailablePresets:
    """Tests for get_available_presets()."""

    def test_returns_flat_list(self, tmp_path):
        from config import settings

        (tmp_path / "file1.json").write_text(json.dumps({
            "PresetList": [{"PresetName": "P1"}, {"PresetName": "P2"}]
        }))
        (tmp_path / "file2.json").write_text(json.dumps({
            "PresetList": [{"PresetName": "P3"}]
        }))

        with patch.object(settings, "preset_path", str(tmp_path)):
            result = get_available_presets()
            assert len(result) == 3
            assert set(result) == {"P1", "P2", "P3"}

    def test_returns_empty_when_no_presets(self, tmp_path):
        from config import settings

        with patch.object(settings, "preset_path", str(tmp_path / "nonexistent")):
            result = get_available_presets()
            assert result == []


class TestGetPresetFiles:
    """Tests for get_preset_files()."""

    def test_returns_file_paths(self, tmp_path):
        from config import settings

        (tmp_path / "custom.json").write_text(json.dumps({
            "PresetList": [{"PresetName": "Test"}]
        }))

        with patch.object(settings, "preset_path", str(tmp_path)):
            result = get_preset_files()
            assert len(result) == 1
            assert "custom.json" in result[0]


# ─── GPU Detection ───────────────────────────────────────────────────────────


class TestDetectBestGpu:
    """Tests for detect_best_gpu()."""

    def test_cpu_only_image_skips_gpu_detection(self, monkeypatch):
        """CPU-only image (no GPU_VENDOR) always returns software."""
        monkeypatch.delenv("GPU_VENDOR", raising=False)
        gpu = {"handbrake_nvenc": True, "ffmpeg_nvenc_h265": True}
        assert detect_best_gpu(gpu) == "software"

    def test_detects_nvenc_via_handbrake(self, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "nvidia")
        gpu = {"handbrake_nvenc": True, "ffmpeg_nvenc_h265": False}
        assert detect_best_gpu(gpu) == "nvenc"

    def test_detects_nvenc_via_ffmpeg(self, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "nvidia")
        gpu = {"handbrake_nvenc": False, "ffmpeg_nvenc_h265": True}
        assert detect_best_gpu(gpu) == "nvenc"

    def test_detects_qsv(self, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "intel")
        gpu = {"handbrake_nvenc": False, "ffmpeg_nvenc_h265": False, "ffmpeg_qsv_h265": True}
        assert detect_best_gpu(gpu) == "qsv"

    def test_detects_vcn_via_amf(self, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "amd")
        gpu = {
            "handbrake_nvenc": False,
            "ffmpeg_nvenc_h265": False,
            "ffmpeg_qsv_h265": False,
            "ffmpeg_amf_h265": True,
        }
        assert detect_best_gpu(gpu) == "vcn"

    def test_detects_vcn_via_vaapi(self, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "amd")
        gpu = {
            "handbrake_nvenc": False,
            "ffmpeg_nvenc_h265": False,
            "ffmpeg_qsv_h265": False,
            "ffmpeg_amf_h265": False,
            "ffmpeg_vaapi_h265": True,
        }
        assert detect_best_gpu(gpu) == "vcn"

    def test_falls_back_to_software(self, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "nvidia")
        gpu = {
            "handbrake_nvenc": False,
            "ffmpeg_nvenc_h265": False,
            "ffmpeg_qsv_h265": False,
            "ffmpeg_amf_h265": False,
            "ffmpeg_vaapi_h265": False,
        }
        assert detect_best_gpu(gpu) == "software"

    def test_empty_dict_falls_back_to_software(self, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "nvidia")
        assert detect_best_gpu({}) == "software"

    def test_nvenc_takes_priority_over_qsv(self, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "nvidia")
        gpu = {
            "handbrake_nvenc": True,
            "ffmpeg_qsv_h265": True,
        }
        assert detect_best_gpu(gpu) == "nvenc"


# ─── Config Override Loading ─────────────────────────────────────────────────


class TestLoadConfigOverrides:
    """Tests for load_config_overrides()."""

    @pytest_asyncio.fixture
    async def override_db(self, tmp_dirs):
        """Create a test database with config_overrides table."""
        db_path = tmp_dirs["db_path"]
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield engine, session_factory

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_loads_string_override(self, override_db):
        engine, session_factory = override_db
        from config import settings, load_config_overrides

        async with session_factory() as session:
            session.add(ConfigOverrideDB(key="video_encoder", value="x264"))
            await session.commit()

        # Mock get_db to use our test session factory
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_get_db():
            async with session_factory() as session:
                yield session

        original = settings.video_encoder
        try:
            with patch("database.get_db", mock_get_db):
                await load_config_overrides()
            assert settings.video_encoder == "x264"
        finally:
            settings.video_encoder = original

    @pytest.mark.asyncio
    async def test_loads_bool_override(self, override_db):
        engine, session_factory = override_db
        from config import settings, load_config_overrides

        async with session_factory() as session:
            session.add(ConfigOverrideDB(key="delete_source", value="false"))
            await session.commit()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_get_db():
            async with session_factory() as session:
                yield session

        original = settings.delete_source
        try:
            with patch("database.get_db", mock_get_db):
                await load_config_overrides()
            assert settings.delete_source is False
        finally:
            settings.delete_source = original

    @pytest.mark.asyncio
    async def test_loads_int_override(self, override_db):
        engine, session_factory = override_db
        from config import settings, load_config_overrides

        async with session_factory() as session:
            session.add(ConfigOverrideDB(key="max_concurrent", value="4"))
            await session.commit()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_get_db():
            async with session_factory() as session:
                yield session

        original = settings.max_concurrent
        try:
            with patch("database.get_db", mock_get_db):
                await load_config_overrides()
            assert settings.max_concurrent == 4
        finally:
            settings.max_concurrent = original

    @pytest.mark.asyncio
    async def test_loads_float_override(self, override_db):
        engine, session_factory = override_db
        from config import settings, load_config_overrides

        async with session_factory() as session:
            session.add(ConfigOverrideDB(key="minimum_free_space_gb", value="25.5"))
            await session.commit()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_get_db():
            async with session_factory() as session:
                yield session

        original = settings.minimum_free_space_gb
        try:
            with patch("database.get_db", mock_get_db):
                await load_config_overrides()
            assert settings.minimum_free_space_gb == pytest.approx(25.5)
        finally:
            settings.minimum_free_space_gb = original

    @pytest.mark.asyncio
    async def test_skips_non_updatable_key(self, override_db):
        engine, session_factory = override_db
        from config import settings, load_config_overrides

        async with session_factory() as session:
            session.add(ConfigOverrideDB(key="db_path", value="/evil/path"))
            await session.commit()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_get_db():
            async with session_factory() as session:
                yield session

        original = settings.db_path
        with patch("database.get_db", mock_get_db):
            await load_config_overrides()
        assert settings.db_path == original

    @pytest.mark.asyncio
    async def test_skips_invalid_value(self, override_db):
        engine, session_factory = override_db
        from config import settings, load_config_overrides

        async with session_factory() as session:
            session.add(ConfigOverrideDB(key="max_concurrent", value="not_a_number"))
            await session.commit()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_get_db():
            async with session_factory() as session:
                yield session

        original = settings.max_concurrent
        try:
            with patch("database.get_db", mock_get_db):
                await load_config_overrides()
            # Should not have changed since "not_a_number" can't be cast to int
            assert settings.max_concurrent == original
        finally:
            settings.max_concurrent = original


# ─── GPU Auto-Resolution ─────────────────────────────────────────────────────


class TestAutoResolveGpuDefaults:
    """Tests for auto_resolve_gpu_defaults()."""

    @pytest_asyncio.fixture
    async def gpu_db(self, tmp_dirs):
        """Create a test database for GPU auto-resolution tests."""
        db_path = tmp_dirs["db_path"]
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield engine, session_factory

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_applies_nvenc_defaults(self, gpu_db, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "nvidia")
        engine, session_factory = gpu_db
        from config import settings, auto_resolve_gpu_defaults

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_get_db():
            async with session_factory() as session:
                yield session

        originals = {
            "video_encoder": settings.video_encoder,
            "handbrake_preset": settings.handbrake_preset,
            "handbrake_preset_4k": settings.handbrake_preset_4k,
            "handbrake_preset_dvd": settings.handbrake_preset_dvd,
        }
        try:
            gpu_support = {"handbrake_nvenc": True}
            with patch("database.get_db", mock_get_db):
                await auto_resolve_gpu_defaults(gpu_support)
            assert settings.video_encoder == "nvenc_h265"
            assert settings.handbrake_preset == "H.265 NVENC 1080p"
            assert settings.handbrake_preset_4k == "H.265 NVENC 2160p 4K"
            assert settings.handbrake_preset_dvd == "H.265 NVENC 1080p"
        finally:
            for key, val in originals.items():
                setattr(settings, key, val)

    @pytest.mark.asyncio
    async def test_respects_user_overrides(self, gpu_db, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "nvidia")
        engine, session_factory = gpu_db
        from config import settings, auto_resolve_gpu_defaults

        # Insert a user override for video_encoder
        async with session_factory() as session:
            session.add(ConfigOverrideDB(key="video_encoder", value="x264"))
            await session.commit()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_get_db():
            async with session_factory() as session:
                yield session

        originals = {
            "video_encoder": settings.video_encoder,
            "handbrake_preset": settings.handbrake_preset,
        }
        try:
            gpu_support = {"handbrake_nvenc": True}
            with patch("database.get_db", mock_get_db):
                await auto_resolve_gpu_defaults(gpu_support)
            # video_encoder should NOT be changed (user override exists)
            assert settings.video_encoder == originals["video_encoder"]
            # handbrake_preset should be changed (no user override)
            assert settings.handbrake_preset == "H.265 NVENC 1080p"
        finally:
            for key, val in originals.items():
                setattr(settings, key, val)

    @pytest.mark.asyncio
    async def test_software_fallback(self, gpu_db, monkeypatch):
        monkeypatch.setenv("GPU_VENDOR", "nvidia")
        engine, session_factory = gpu_db
        from config import settings, auto_resolve_gpu_defaults

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_get_db():
            async with session_factory() as session:
                yield session

        originals = {
            "video_encoder": settings.video_encoder,
            "handbrake_preset": settings.handbrake_preset,
        }
        try:
            gpu_support = {}  # No GPU
            with patch("database.get_db", mock_get_db):
                await auto_resolve_gpu_defaults(gpu_support)
            assert settings.video_encoder == "x265"
            assert settings.handbrake_preset == "H.265 MKV 1080p30"
        finally:
            for key, val in originals.items():
                setattr(settings, key, val)
