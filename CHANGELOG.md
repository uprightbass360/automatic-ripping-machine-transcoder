# Changelog

## [0.2.0](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/compare/v0.1.0...v0.2.0) (2026-02-15)


### Features

* Add ARM setup automation script ([c00d34c](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/c00d34c38e8848a3724c9c99ec7a5b2c28fa597d))
* Add audio CD passthrough to music folder ([ee49572](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/ee49572c0ef44c4aacf39c786e8f32ecff27cdf3))
* Add authentication and security improvements ([12f8a35](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/12f8a35ad7839812d639a85e40cd2b3118c520eb))
* Add comprehensive test suite and fix documentation ([e6c9b7a](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/e6c9b7ace7711908242b3bab8601d0a1ba070276))
* add config persistence model and psutil dependency ([39aefd7](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/39aefd7c923cfb7cf412c93d7f7824d80f97f978))
* add GPU auto-detection, config management, and system monitoring ([94db4fa](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/94db4fa42df444f8e71c26a351c390d097461e1d))
* Add media metadata to output folder and file names ([6b1fb39](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/6b1fb39bd00ce4424a29d5fd91dd0cf707e53531))
* Add multi-GPU support (AMD VAAPI/AMF, Intel QSV, software) ([6964d2a](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/6964d2ad440d92f92f7786ce0bb43ee0ed179552))
* Add optical drive watcher for ARM container auto-restart ([27bde1f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/27bde1f5a59b5e41423e09666220e47ebf4c694c))
* Add resolution-based preset selection for all GPU backends ([717cb67](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/717cb67ad869b75a60d0fbbc5f60b2e0387054dc))
* add rotating file logging and log viewer API ([84f8c5e](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/84f8c5e4460aac9e00a941142698f45eb9aa433a))
* Add security infrastructure and validation (Phase 1) ([76f93a5](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/76f93a54dd5a8ba733ba2b266488d6698f73c452))
* Add stable optical drive symlink script ([6334854](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/63348548fb8c363de888b8c7181281537c13403f))
* enhance ARM notification script with raw path support ([98188ef](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/98188ef18d21a8cf7e40b6bba70a90c3e20d71f3))
* Use local scratch storage to avoid heavy I/O on NFS ([09c2954](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/09c29540cc6ee687bae61b7ea4c98f7ff0b10918))


### Bug Fixes

* Add worker 503 guards, graceful shutdown, and import cleanup ([f06e1b9](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/f06e1b97ce7a51b767b468870bcca7b6eb196b72))
* Apprise webhook compatibility and ARM integration config ([83a6b49](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/83a6b495cae5be9b100623c9f61cb135c1780597))
* Correct HandBrake preset name to match built-in presets ([eba50a2](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/eba50a21d6bca3a7c0e264a1fabe73e2398bd62a))
* Create render group in Intel and AMD Dockerfiles ([b089af6](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/b089af6b5eaa56609efef80d8302c75d7be3d1b7))
* Increase drive watcher debounce default to 60s ([9520288](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/95202881ce91ceb4cab763cc1757d58b8e9fa14c))
* Install HandBrake from PPA instead of Alpine multi-stage copy ([d3f3322](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/d3f33224af53c63fa9691af021d05c02338c6ab9))
* Make audio passthrough source cleanup non-fatal ([a43383e](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/a43383e8fbdacb9b1e628b037193705f280f6c97))
* Pass all application settings through Docker compose environment ([0dbb17f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/0dbb17f1936fffe763526b7e0d3c90f548a16a97))
* Prevent restart loop by checking device visibility in container ([0d76b52](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/0d76b522010109900ea1b9a109a0d147dc9636be))
* Re-resolve source path after stabilization when no files found ([2f50791](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/2f50791c6db9e6ce04c7b5f3c9af8fab1f4e8319))
* Replace device visibility check with container uptime check ([4023f52](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/4023f52789ca37d559193a8259cedff100db8064))
* Resolve ARM subdirectory paths for ripped media ([a28403f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/a28403f10c1d156cbe70bd89a066b510ab6aa3f7))
* Short-lived DB sessions, progress rate limiting, stream mapping, and disk space checks ([c0e200b](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/c0e200b593721a92fb104f14f4aa8f1f31fd1df5))
* Update Intel Dockerfile for Debian Trixie package names ([50bccb6](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/50bccb6c6b616784a43a8b39ccdab22251d7b6f1))
* Use copy instead of move for audio passthrough ([d5302e5](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/d5302e5af3ffcb8dcc81ecbe29a3728f84b7f880))
* Use extracted media title for job naming and graceful cleanup ([5f44c76](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/5f44c76776908ceb8449db007a2c97009f659ae2))
* Use Ubuntu universe repo for HandBrake instead of PPA ([912bcef](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/912bcef1b06f178d6d459e251abab503cc0d64c5))

## Changelog
