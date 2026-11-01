# Architecture

## Shape

```
                       ┌──────────────────────────────────────────┐
  browser (mobile      │  frontend/  static HTML/CSS/JS, no build  │
  first, EN/HI)  ─────►│  upload · studio · status · player · …    │
                       └───────────────┬──────────────────────────┘
                                       │ fetch / XHR / EventSource
                                       ▼
        ┌──────────────────────────────────────────────────────────────┐
        │ backend/app.py — FastAPI                                     │
        │   routes/jobs.py  upload, stages, status, SSE, media, files   │
        │   routes/meta.py  languages, capabilities, config, health     │
        │   security.py     token auth · rate limit · path guards       │
        └───────┬──────────────────────────────────┬───────────────────┘
                │ job rows (SQLite WAL)            │ artifacts on disk
                ▼                                  ▼
        ┌───────────────────────┐         ┌──────────────────────────┐
        │ workers/worker.py     │         │ storage/jobs/<id>/       │
        │ queue + N threads     │         │   source/  (untouched)   │
        │ requeues interrupted  │         │   work/    (wav, tts)    │
        └───────┬───────────────┘         │   out/     (renders)     │
                ▼                         └──────────────────────────┘
        ┌──────────────────────────────────────────────────────────────┐
        │ services/pipeline.py — nine stages, each independently callable│
        │   engines/{media,dsp,asr,diarize,translate,tts,separate}.py    │
        │   services/{mix,render,validation,srt,languages,streaming}.py  │
        └──────────────────────────────────────────────────────────────┘
```

## Why these choices

**One process, one SQLite file, one queue.** On a ₹0 tier every extra service is another thing that
sleeps, times out or costs money. SQLite in WAL mode handles the concurrency of a single-worker
prototype, and the worker requeues anything that was interrupted by a restart (and says so in the
event log). Because the queue is a table, swapping in Redis/Celery later is a one-file change.

**Engines are classes with `dependencies_ok()`.** The pipeline asks each engine whether it can run,
then picks the best available: pyannote → MFCC clustering, NLLB → Argos → LibreTranslate → LLM →
imported subtitles, XTTS → Piper → eSpeak NG, Demucs → centre extraction → ducking. Capability
reporting and engine selection therefore use the same source of truth — the UI can never claim a
model that is not installed.

**Stages are idempotent and individually callable.** The granular endpoints (`/transcribe`,
`/translate`, …) are not decoration: they let the studio re-run only what changed, which is what makes
a free, flaky, slow backend usable. `should_run()` skips a stage whose artifacts already exist unless
`force` is set.

**The picture is sacred.** `services/render.py` always maps `0:v` with `-c:v copy`, and then computes
the compressed-stream md5 of input and output (`engines/media.video_stream_md5`). The comparison is
stored in `jobs.verification`, surfaced on the status/download pages, and asserted in two tests
(including per-frame `framemd5`). A mismatch raises `RENDER_FAILED` instead of publishing the file.

**Audio work happens in numpy, not in a filter graph.** Separation, placement, ducking and mixing are
explicit arrays at 48 kHz, which makes the timing rules testable: tempo clamping, 10 ms fades,
0.3 s overflow tolerance, no overlap. FFmpeg is used where it is genuinely better (decode, resample,
`atempo` time-stretch, muxing).

**Progress is derived, never invented.** `Pipeline.progress(stage, fraction)` maps a fraction of
completed work units onto fixed stage spans (`STAGE_SPANS`), and every fraction is computed from a
real loop index. The stage list is the same one the UI renders.

## Data model (SQLite)

```
jobs(id PK, created_at, updated_at, status, stage, progress, stages_done,
     source_name/ext/bytes, source_lang, target_lang, media JSON, options JSON,
     error JSON, warning JSON, input_mode, speakers JSON, artifacts JSON,
     verification JSON, notes JSON, client_ip, deleted)
segments(job_id, idx, start_sec, end_sec, text, translated_text, speaker,
         confidence, tts_duration, tempo, flags)          PK (job_id, idx)
events(id PK, job_id, ts, stage, message, level, progress)   → SSE + log panel
voice_previews(key PK, job_id, lang, voice, path, created_at)
```

## Timing rules (the part that makes a dub feel right)

For each line, with `slot = end - start` and `natural = TTS duration`:

```
tempo       = clamp(natural / slot, 1.0, BFLIX_MAX_TEMPO)      # never slower than natural
placed_at   = max(line.start, previous_line_end + 0.02)
latest_end  = min(next_line.start - 0.02, line.end + 0.30)
max_len     = (latest_end - placed_at) * sample_rate
```

If the clip is longer than `max_len` it is truncated with a 60 ms fade and flagged `time_compressed`;
if the line would still collide with the next one, the line is trimmed, never overlapped. The mixed
result is peak-limited and de-clicked at both ends.

## Error model

One catalogue (`models.ERROR_CATALOGUE`) with an English and Hindi message per stable code, plus a
`hint` generated where the failure happens (e.g. the exact `pip install` line for a missing model).
The API wraps errors as `{"error": {...}}`, the UI renders `message_hi` when the interface is Hindi,
and the status page offers *retry* and *open studio* on the same card.

## Extension points

- **New ASR/TTS/translator/separator**: add a class with `dependencies_ok()` + the one required method,
  append it to the module's list. Nothing else changes.
- **GPU worker**: run the same image with the model env vars; the API does not care where the worker
  runs as long as the job row and the storage directory are shared.
- **Different storage**: `repo.job_dir()` is the single place that resolves a path.
- **Real auth**: replace `security.require_token` with your session/JWT middleware; every route
  already depends on it.
