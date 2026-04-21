# ARM Transcoder Webhook Payload Spec

ARM sends a JSON webhook to the transcoder when a rip completes. The transcoder uses this payload to determine what to transcode and how to name output files.

**ARM is the single source of truth for naming.** The transcoder should use `folder_name` and `title_name` from the payload directly - it should never invent its own names.

## Endpoint

```
POST /webhook/arm
Content-Type: application/json
X-Webhook-Secret: <optional secret>
```

## Payload Schema

### Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Notification title (e.g. "Rip complete") |
| `body` | string | Notification body text |
| `type` | string | Always `"info"` |
| `path` | string | Raw directory basename (e.g. `"My Movie (2024)"`) |
| `job_id` | string | ARM job ID |
| `video_type` | string | `"movie"`, `"series"`, or `"music"` |
| `year` | string | Release year |
| `disctype` | string | `"bluray"`, `"bluray4k"`, or `"dvd"` |
| `status` | string | Job status at time of notification |
| `poster_url` | string | Poster image URL (from OMDb/TMDb) |
| `folder_name` | string | Pre-rendered output folder path from ARM's naming engine. May contain `/` for nested dirs (e.g. `"Kolchak- The Night Stalker/Season 01"`). Each segment is already sanitized for filesystem use. |
| `title_name` | string | Pre-rendered job-level output filename (sanitized). Used as fallback when tracks don't have individual names. |
| `multi_title` | boolean | Present and `true` when the job has multiple distinct titles (e.g. TV episodes). Absent when `false`. |
| `config_overrides` | object \| null | Optional per-job preset + override. Shape: `{"preset_slug": "<slug>", "overrides": {"shared": {...}, "tiers": {"dvd": {...}, "bluray": {...}, "uhd": {...}}}, "delete_source": bool, "output_extension": "mkv"}`. All fields optional; omit the whole object for defaults. |
| `tracks` | array | Per-track manifest. Always present when job has tracks. |

### Track manifest (`tracks[]`)

Each entry in the `tracks` array describes one ripped track file.

| Field | Type | Description |
|-------|------|-------------|
| `track_number` | string | Track number on the disc (e.g. `"0"`, `"1"`) |
| `title` | string | Display title for this track. **Precedence**: `episode_name` > `track.title` > `job.title`. For matched series episodes, this is the episode name. |
| `year` | string | Track-level year override, or job year |
| `video_type` | string | Track-level type override, or job type |
| `filename` | string | Source MKV filename in the raw directory (e.g. `"Show Disc 1_t00.mkv"`) |
| `has_custom_title` | boolean | `true` if the track has a per-track title or custom filename |
| `folder_name` | string | Pre-rendered output folder for this track. May differ per track for series (e.g. different seasons). |
| `title_name` | string | Pre-rendered output filename for this track (sanitized, no extension). The transcoder should use this as-is. |
| `episode_number` | string | Episode number (e.g. `"6"`). Empty string if not a matched episode. |
| `episode_name` | string | Episode name from TVDB (e.g. `"Firefall"`). Empty string if not matched. |

### Title field precedence

The `title` field in each track entry follows this precedence:

1. `episode_name` - when the track has been matched to a TVDB episode
2. `track.title` - when set by auto-match or manual override
3. `job.title` - fallback to the show/movie name

This ensures that manual episode corrections in the UI are always reflected in the webhook, even if an earlier auto-match set a different `track.title`.

### Naming contract

The `title_name` field is the **authoritative output filename** for each track. It is pre-rendered by ARM's naming engine using the configured patterns (`TV_TITLE_PATTERN`, `MOVIE_TITLE_PATTERN`, etc.) and sanitized for filesystem use.

The transcoder should:
- Use `title_name` as the output filename (adding the extension)
- Use `folder_name` as the output subdirectory
- Never apply its own naming logic to matched tracks
- Only generate names for scratch/temp files during transcoding

### Unmatched tracks

Tracks without episode assignments have:
- `episode_number`: `""`
- `episode_name`: `""`
- `has_custom_title`: `false`
- `title_name`: fallback format like `"Show Name - Track 5"` (not `S01E` format)

These are typically disc extras (menus, trailers, featurettes). The transcoder should still transcode them using the provided `title_name`.

## Example payload

```json
{
  "title": "Rip complete",
  "body": "Kolchak: The Night Stalker ripped successfully",
  "type": "info",
  "path": "Kolchak: The Night Stalker",
  "job_id": "73",
  "video_type": "series",
  "year": "1974",
  "disctype": "bluray4k",
  "status": "waiting_transcode",
  "poster_url": "https://example.com/poster.jpg",
  "folder_name": "Kolchak- The Night Stalker/Season 01",
  "title_name": "Kolchak- The Night Stalker S01E06",
  "multi_title": true,
  "tracks": [
    {
      "track_number": "0",
      "title": "Firefall",
      "year": "1974",
      "video_type": "series",
      "filename": "Kolchak The Night Stalker Disc 2_t00.mkv",
      "has_custom_title": true,
      "folder_name": "Kolchak- The Night Stalker/Season 01",
      "title_name": "Firefall S01E06",
      "episode_number": "6",
      "episode_name": "Firefall"
    },
    {
      "track_number": "3",
      "title": "Kolchak: The Night Stalker",
      "year": "1974",
      "video_type": "series",
      "filename": "Kolchak The Night Stalker Disc 2_t03.mkv",
      "has_custom_title": false,
      "folder_name": "Kolchak- The Night Stalker/Season 01",
      "title_name": "Kolchak- The Night Stalker - Track 3",
      "episode_number": "",
      "episode_name": ""
    }
  ]
}
```
