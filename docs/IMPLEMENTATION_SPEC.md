# ARM Transcoder - Security & Quality Improvements Specification

**Version:** 2.0
**Date:** February 6, 2026
**Status:** Implementation Required

## Overview

This specification addresses critical security vulnerabilities, high-priority bugs, and code quality issues identified in the initial codebase review. All changes maintain backward compatibility with existing deployments where possible.

---

## 1. Critical Security Fixes

### 1.1 Path Traversal Protection

**Issue:** User-controlled webhook input directly used in file paths
**Severity:** Critical
**Impact:** Arbitrary file system access

**Implementation:**
- Add `PathValidator` utility class to sanitize and validate all paths
- Use `Path.resolve()` to normalize paths and check they're within allowed directories
- Reject paths containing `..`, absolute paths, or symbolic links outside allowed dirs
- Add `validate_source_path()` method to verify paths before queuing jobs

**Files Modified:**
- `src/utils.py` (new file)
- `src/main.py` (webhook handler)
- `src/transcoder.py` (path validation before processing)

**Test Cases:**
- Path with `../` sequences
- Absolute paths
- Symbolic links outside allowed directories
- Windows-style paths with backslashes

### 1.2 Webhook Input Validation

**Issue:** No validation on webhook payloads
**Severity:** Critical
**Impact:** Memory exhaustion, database overflow, type errors

**Implementation:**
- Use Pydantic `WebhookPayload` model for all webhook requests
- Add field validators: max string lengths, allowed characters
- Implement request size limits (10KB max)
- Add FastAPI `Request` body size validator

**Validation Rules:**
- `title`: max 500 chars, alphanumeric + spaces + common punctuation
- `body`: max 2000 chars
- `path`: max 1000 chars, validated against path traversal
- `job_id`: max 50 chars, alphanumeric + hyphens
- Reject requests > 10KB

**Files Modified:**
- `src/models.py` (add validators)
- `src/main.py` (use validated model)

### 1.3 Command Injection Prevention

**Issue:** Unvalidated environment variables used in subprocess calls
**Severity:** Critical
**Impact:** Arbitrary command execution

**Implementation:**
- Create allowlist of valid HandBrake preset names
- Validate `video_encoder` against known encoder list
- Add `CommandValidator` class to sanitize all subprocess arguments
- Use absolute paths for all binaries

**Files Modified:**
- `src/config.py` (add validation)
- `src/transcoder.py` (validate before subprocess)
- `src/utils.py` (CommandValidator)

---

## 2. High Priority Fixes

### 2.1 FFmpeg Stream Mapping

**Issue:** No explicit stream mapping, may drop audio tracks
**Severity:** High
**Impact:** Data loss (missing audio/subtitle tracks)

**Implementation:**
- Add `-map 0` to include all streams
- For audio: `-map 0:a -map 0:s?` (all audio, optional subtitles)
- Add fallback logic if specific mappings fail
- Log which streams are being processed

**Files Modified:**
- `src/transcoder.py` (_transcode_file_ffmpeg)

### 2.2 Worker Race Condition

**Issue:** Worker may be None during startup/shutdown
**Severity:** High
**Impact:** Application crashes

**Implementation:**
- Add `WorkerState` enum (STARTING, RUNNING, STOPPING, STOPPED)
- Add worker readiness check before accepting webhooks
- Return 503 Service Unavailable if worker not ready
- Add mutex lock for worker state transitions

**Files Modified:**
- `src/main.py` (readiness check)
- `src/transcoder.py` (state management)

### 2.3 Database Session Management

**Issue:** Long-running sessions held during transcode
**Severity:** High
**Impact:** Database locks, session timeouts

**Implementation:**
- Refactor to use short-lived sessions for each DB operation
- Create `update_job_status()` helper that opens/closes session
- Implement progress update batching (only update DB every 5% change)
- Add connection pool configuration

**Files Modified:**
- `src/database.py` (helper functions)
- `src/transcoder.py` (session management)

### 2.4 Progress Update Optimization

**Issue:** Excessive database writes on same progress value
**Severity:** High
**Impact:** Database contention, performance degradation

**Implementation:**
- Track `_last_committed_progress` per job
- Only commit when progress increases by >= 5%
- Use single UPDATE query instead of fetch + update
- Add progress update rate limiting (max 1 update per 10 seconds)

**Files Modified:**
- `src/transcoder.py` (progress tracking)

---

## 3. Medium Priority Fixes

### 3.1 Deprecated API Replacements

**Issue:** Using deprecated `datetime.utcnow()`
**Severity:** Medium
**Impact:** Future Python version compatibility

**Implementation:**
- Replace all `datetime.utcnow()` with `datetime.now(timezone.utc)`
- Add timezone to all datetime columns
- Use timezone-aware datetimes throughout

**Files Modified:**
- `src/transcoder.py` (all datetime usages)
- `src/models.py` (DateTime column defaults)

### 3.2 Concurrent Processing Implementation

**Issue:** `max_concurrent` setting unused
**Severity:** Medium
**Impact:** Misleading configuration

**Implementation:**
- Implement semaphore-based concurrency limiting
- Use `asyncio.Semaphore(max_concurrent)` to control parallel jobs
- Add concurrent job tracking to stats endpoint
- Document GPU NVENC session limits (GTX 1660: 3 sessions)

**Files Modified:**
- `src/transcoder.py` (concurrency control)
- `src/config.py` (documentation)

### 3.3 Docker Dependencies

**Issue:** HandBrake dependencies may be incomplete
**Severity:** Medium
**Impact:** Runtime failures

**Implementation:**
- Option A: Install HandBrake via apt in nvidia/cuda image
- Option B: Copy all deps identified via `ldd`
- Add runtime check on startup to verify HandBrakeCLI works

**Files Modified:**
- `Dockerfile` (dependency installation)
- `src/transcoder.py` (startup check)

### 3.4 Graceful Shutdown

**Issue:** Active transcodes killed on shutdown
**Severity:** Medium
**Impact:** Partial files, wasted work

**Implementation:**
- Implement graceful shutdown with configurable timeout (default 300s)
- Worker finishes current job before exiting
- Set job status to PENDING if interrupted
- Log shutdown progress

**Files Modified:**
- `src/main.py` (lifespan shutdown)
- `src/transcoder.py` (shutdown handler)

### 3.5 Code Organization

**Issue:** Imports inside functions, unused imports
**Severity:** Low
**Impact:** Code clarity

**Implementation:**
- Move all imports to module level
- Remove unused `BackgroundTasks` import
- Organize imports: stdlib, third-party, local
- Run `isort` and `black` for formatting

**Files Modified:**
- All `.py` files

### 3.6 Hardcoded Values

**Issue:** Magic numbers throughout code
**Severity:** Low
**Impact:** Maintainability

**Implementation:**
- Create constants file with named values:
  - `STABILIZE_CHECK_INTERVAL = 5  # seconds`
  - `PROGRESS_UPDATE_THRESHOLD = 5  # percent`
  - `NVENC_PRESET_DEFAULT = "p4"`
  - `SHUTDOWN_TIMEOUT = 300  # seconds`

**Files Modified:**
- `src/constants.py` (new file)
- All files using magic numbers

---

## 4. Missing Features

### 4.1 API Authentication

**Implementation:**
- Add API key authentication via header
- Support multiple API keys (read-only vs admin)
- Admin key required for delete/retry operations
- Read-only key for stats/list operations
- Anonymous access disabled by default

**Configuration:**
```python
api_keys: list[dict] = [
    {"key": "admin_key", "permissions": ["read", "write", "admin"]},
    {"key": "readonly_key", "permissions": ["read"]}
]
```

**Files:**
- `src/auth.py` (new file)
- `src/main.py` (add dependencies)
- `src/config.py` (API key config)

### 4.2 Rate Limiting

**Implementation:**
- Use `slowapi` for rate limiting
- Webhook endpoint: 10 requests/minute per IP
- API endpoints: 60 requests/minute per API key
- Return 429 Too Many Requests when exceeded

**Files:**
- `requirements.txt` (add slowapi)
- `src/main.py` (rate limit decorators)

### 4.3 Metrics & Monitoring

**Implementation:**
- Add `/metrics` endpoint for Prometheus
- Track metrics:
  - Total jobs processed
  - Success/failure rates
  - Average transcode time
  - Current queue depth
  - GPU utilization (via nvidia-smi)
  - Disk space remaining

**Files:**
- `requirements.txt` (add prometheus-client)
- `src/metrics.py` (new file)
- `src/main.py` (metrics endpoint)

### 4.4 Job Cancellation

**Implementation:**
- Add `CANCELLED` job status
- Add `/jobs/{id}/cancel` endpoint
- Kill subprocess for cancelled jobs
- Clean up partial output files
- Update database status

**Files:**
- `src/models.py` (add CANCELLED status)
- `src/main.py` (cancel endpoint)
- `src/transcoder.py` (cancel handler)

### 4.5 Retry Limits

**Implementation:**
- Add `retry_count` column to TranscodeJobDB
- Max 3 retries per job by default (configurable)
- Exponential backoff between retries (1min, 5min, 15min)
- Mark as permanently failed after max retries

**Files:**
- `src/models.py` (add retry_count)
- `src/main.py` (retry logic)

### 4.6 Disk Space Checks

**Implementation:**
- Check available disk space before starting job
- Estimate required space: source_size * 0.6 (reasonable compression)
- Fail job immediately if insufficient space
- Add minimum free space requirement (10GB default)
- Add disk space to health check endpoint

**Files:**
- `src/utils.py` (disk space functions)
- `src/transcoder.py` (pre-job check)
- `src/main.py` (health check)

### 4.7 Completion Notifications

**Implementation:**
- Support webhook callbacks on job completion
- Support email notifications via SMTP
- Support Apprise for multi-channel notifications
- Configurable per-job or global

**Configuration:**
```python
notification_webhook: str = ""  # POST on completion
notification_email: str = ""
smtp_server: str = ""
smtp_port: int = 587
```

**Files:**
- `src/config.py` (notification config)
- `src/notifications.py` (new file)
- `src/transcoder.py` (send on completion)

---

## 5. Additional Improvements

### 5.1 Logging

**Implementation:**
- Structured logging with JSON output option
- Log levels per module
- Request IDs for tracing
- Log rotation configuration
- Sensitive data masking (API keys, paths)

**Files:**
- `src/logging_config.py` (new file)
- All files (use configured logger)

### 5.2 Health Checks

**Implementation:**
Enhanced health check that verifies:
- Worker is running
- Database is accessible
- GPU is available (nvidia-smi)
- Disk space > minimum
- NFS mounts are readable/writable

**Files:**
- `src/main.py` (enhanced health endpoint)

### 5.3 Pagination

**Implementation:**
- Add `limit` and `offset` parameters to `/jobs`
- Default limit: 50
- Max limit: 500
- Return total count in response

**Files:**
- `src/main.py` (jobs endpoint)

### 5.4 Error Handling

**Implementation:**
- Catch and log all exceptions
- Never silently swallow exceptions
- Provide meaningful error messages to API users
- Add error codes for different failure types

**Files:**
- All `.py` files

---

## 6. Testing Requirements

### 6.1 Unit Tests

Required tests:
- PathValidator (all attack vectors)
- WebhookPayload validation
- Progress tracking logic
- Disk space calculations
- Retry logic with backoff

**Files:**
- `tests/test_utils.py` (new)
- `tests/test_models.py` (new)
- `tests/test_transcoder.py` (new)

### 6.2 Integration Tests

Required tests:
- Full transcode workflow
- Webhook to completion
- Job cancellation
- Graceful shutdown
- Concurrent job processing

**Files:**
- `tests/test_integration.py` (new)

### 6.3 Security Tests

Required tests:
- Path traversal attempts
- Oversized payloads
- Command injection attempts
- Rate limit enforcement
- API key validation

**Files:**
- `tests/test_security.py` (new)

---

## 7. Documentation Updates

### 7.1 README Updates

- Add security section
- Document API authentication
- Add monitoring setup guide
- Update configuration examples

### 7.2 New Documentation

- `docs/SECURITY.md` - Security best practices
- `docs/API.md` - Complete API reference
- `docs/MONITORING.md` - Prometheus integration
- `docs/TROUBLESHOOTING.md` - Common issues

---

## 8. Implementation Order

1. **Phase 1: Critical Security** (Days 1-2)
   - Path traversal protection
   - Input validation
   - Command injection prevention

2. **Phase 2: High Priority Bugs** (Days 3-4)
   - FFmpeg stream mapping
   - Race conditions
   - Database sessions
   - Progress optimization

3. **Phase 3: Medium Priority** (Days 5-6)
   - Deprecated API replacements
   - Concurrent processing
   - Graceful shutdown
   - Code cleanup

4. **Phase 4: Features** (Days 7-9)
   - Authentication
   - Rate limiting
   - Metrics
   - Job cancellation
   - Notifications

5. **Phase 5: Testing & Documentation** (Days 10-12)
   - Write tests
   - Update documentation
   - Security audit
   - Performance testing

---

## 9. Breaking Changes

The following changes may break existing deployments:

1. **API Authentication** - Existing API clients need to add API key header
2. **Webhook Validation** - Invalid webhooks now return 400 instead of being ignored
3. **Path Restrictions** - Paths outside RAW_PATH/COMPLETED_PATH are rejected

**Migration Path:**
- API keys can be disabled via `REQUIRE_API_AUTH=false` (not recommended)
- Webhook validation has backward-compatible mode for 30 days
- Add deprecation warnings for old behavior

---

## 10. Performance Targets

After implementation:

- Webhook response time: < 50ms
- Job queueing latency: < 100ms
- Database query time: < 10ms (99th percentile)
- Memory usage: < 512MB base + 200MB per concurrent job
- CPU usage (idle): < 5%
- API latency: < 20ms (excluding long-running operations)

---

## 11. Success Criteria

Implementation complete when:

- [ ] All critical/high security issues resolved
- [ ] All tests passing
- [ ] Security audit passed
- [ ] Documentation updated
- [ ] Performance targets met
- [ ] No regressions in functionality
- [ ] Backward compatibility maintained (with migration path)
