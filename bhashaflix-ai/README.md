# BhashaFlix AI

**Watch the same movie in your language.** BhashaFlix AI takes a movie you own, replaces *only* the
spoken dialogue with AI voices in your language, keeps the original music and sound effects, and
hands back a file whose picture is bit-for-bit identical to your upload.

```
Original (English)                    Result (Hindi dub)
─────────────────                     ──────────────────
🎬 video stream  ───────────────────► 🎬 identical video stream (copied, verified by md5)
🎙️ English dialogue                   🎙️ Hindi AI dialogue, same timestamps
🥁 music + effects  ─────────────────► 🥁 music + effects preserved (separated, then re-mixed)
                                      🔊 original audio kept as a second selectable track
```

> **The invariant:** the video is never re-encoded, cropped, retimed, regenerated or replaced.
> The renderer copies the compressed video stream (`-c:v copy`) and then fingerprints it — the
> UI shows you the matching md5 so you can check it yourself.

---

## Contents

- [What actually works (and what needs models)](#what-actually-works-and-what-needs-models)
- [Quick start](#quick-start)
- [The demo in one command](#the-demo-in-one-command)
- [The pipeline, stage by stage](#the-pipeline-stage-by-stage)
- [API](#api)
- [Interface](#interface)
- [Models, licences and honest limits](#models-licences-and-honest-limits)
- [Deployment on a ₹0 budget](#deployment-on-a-₹0-budget)
- [Tests](#tests)
- [Project layout](#project-layout)
- [Security & privacy](#security--privacy)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)

---

## What actually works (and what needs models)

BhashaFlix is built so that **every stage either runs for real or fails with a precise error**.
Nothing is simulated, no progress bar is faked, and no download is ever offered for a video that was
not produced.

| Stage | Needs | Works on a free CPU box? |
|---|---|---|
| Upload + validation (extension, magic bytes, container probe, duration, audio tracks) | FFmpeg/PyAV | ✅ always |
| Audio extraction | FFmpeg | ✅ always |
| Speech recognition | `faster-whisper` / `openai-whisper` / `vosk` **or your own subtitles** | ⚠️ model needed; subtitles path always works |
| Speaker identification | `pyannote.audio` **or** built-in MFCC clustering | ✅ built-in fallback |
| Translation | NLLB-200 / Argos / LibreTranslate / any OpenAI-compatible LLM **or your own translated subtitles** | ⚠️ model or API key needed |
| Voice generation | XTTS-v2 / Piper / **eSpeak NG (bundled, offline)** | ✅ eSpeak NG always available |
| Dialogue/background separation | Demucs **or** stereo centre extraction | ✅ centre extraction always available |
| Synchronisation + mixing | numpy + FFmpeg | ✅ always |
| Final render + fingerprint verification | FFmpeg | ✅ always |
| Playback + download | FastAPI range streaming | ✅ always |

So a completely free, model-free setup still produces a **real Hindi dub** if you supply the
dialogue (subtitle file or typed lines). The subjective voice quality of eSpeak NG is robotic; that
is stated in the UI, not hidden. Install XTTS-v2 or Piper for natural voices.

The home page and `/api/capabilities` show exactly which engines this particular backend has.

---

## Quick start

```bash
cd bhashaflix-ai
python3 -m venv .venv && source .venv/bin/activate      # optional but recommended
pip install -r requirements.txt                         # core, CPU only, ~120 MB
cp .env.example .env                                    # optional; every value has a default
make run                                                # uvicorn on 0.0.0.0:8000
```

Open <http://localhost:8000> — the FastAPI process serves both the API and the static frontend.
Interactive API docs: <http://localhost:8000/docs>.

FFmpeg is found automatically (`BFLIX_FFMPEG` → `PATH` → the static binary shipped by
`imageio-ffmpeg`). `ffprobe` is optional: when it is missing, probing falls back to PyAV/libav.

### Add the real models (optional, per hardware)

```bash
pip install faster-whisper            # speech recognition      (~1 GB model on first run)
pip install transformers torch sentencepiece   # NLLB-200 translation (~2.4 GB)
pip install coqui-tts                 # natural voices — needs COQUI_TOS_AGREED=1 (non-commercial)
pip install demucs torch              # best background separation
```

Each block is independent. Anything missing simply shows up as *not installed* in
`/api/capabilities` and its stage fails with an actionable hint if you ask for it.

---

## The demo in one command

```bash
make demo        # = python scripts/demo_e2e.py
```

It generates a 9-second test movie (a centre-panned “dialogue” tone plus wide “music” noise), uploads
it through the real HTTP API with English + Hindi subtitles, waits for the pipeline and prints the
verification:

```
  [  3.0%] extracting_audio
  [ 94.0%] rendering
  [100.0%] completed
video identical     : True
original md5        : 5d879c94be925c9c6cc3666b3037ba17
rendered md5        : 5d879c94be925c9c6cc3666b3037ba17
dialogue level      : peak -15.8 dB / mean -25.5 dB
separation          : center-suppression (medium)
speakers            : ['SPEAKER_01:espeak:hi+f3']
warning             : Centre extraction … music mixed in mono can be affected.
```

---

## The pipeline, stage by stage

| # | Stage | What the code really does |
|---|---|---|
| 1 | **Upload** | Streams to disk with a hard byte cap, validates extension + magic bytes + container probe + duration + audio tracks, creates an unguessable job id. The uploaded file is opened read-only forever after. |
| 2 | **Analysis / extraction** | `ffprobe` (or PyAV) → duration, resolution, fps, codecs, audio streams. Extracts a 48 kHz stereo working WAV and a 16 kHz mono copy for ASR. |
| 3 | **Transcription** | `faster-whisper` (VAD + beam search) → segments with timestamps, plus detected language. If you supplied subtitles, they are used instead and the detected language comes from the text. |
| 4 | **Speaker ID** | `pyannote.audio` when a token is configured, otherwise average-linkage clustering over MFCC embeddings computed with numpy. Speaker IDs are ordered by first appearance and stay stable for the whole film. Pitch is estimated per speaker only to *suggest* a male/female voice. |
| 5 | **Translation** | NLLB-200 → Argos → LibreTranslate → OpenAI-compatible LLM (server-side key) → your own translated subtitles. Batched, with progress per batch; language pair checked before starting. |
| 6 | **Voice generation** | One voice per speaker (distinct where possible), per-line synthesis, then tempo fitting. Preview any voice from the studio or `/api/voice-preview`. Voice cloning is **off by default**. |
| 7 | **Separation** | Demucs instrumental stem when installed; otherwise stereo centre extraction (per-bin coherence weighting, inverse STFT) which removes centre-panned dialogue and keeps wide/panned music; mono sources fall back to ducking *with a warning*. |
| 8 | **Synchronisation** | Every line is fitted to its original slot: tempo clamped to `0.75–1.45×`, 10 ms fades, a 0.3 s overflow tolerance, and a hard rule that two lines never overlap. Dialogue is mixed over the preserved background, ducked while somebody speaks, then peak-limited. |
| 9 | **Render** | `-map 0:v -c:v copy` + new dubbed AAC track + the original audio track; a second variant carries the original audio only (used by the player's track switch); optional MKV with soft subtitles; MP4 `+faststart` for streaming. Finally the video stream md5 of input and output are compared and stored. |
| 10 | **Playback / download** | Range-capable streaming (`206 Partial Content`) so seeking works in Android Chrome, dual-audio switching, subtitles on/off, speed, volume, resume position, and direct downloads. |

Progress is computed from completed work units (lines transcribed, lines translated, lines voiced,
files rendered) and mapped onto the nine stages — never from a timer.

---

## API

All endpoints are under `/api`. If `BFLIX_API_TOKEN` is set, send `X-API-Token: <token>` (or
`?token=` for media URLs).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/upload` | Multipart upload (`file`, optional `subtitle`, `translated_subtitle`, `target_lang`, `source_lang`, `input_mode`, `autostart`, `stop_after`, `options`). Returns `202` with the job. |
| `POST` | `/analyze` | Probe + extract audio inline; returns media metadata. |
| `POST` | `/transcribe` | Queue speech recognition (extract + transcribe). |
| `POST` | `/speakers` | Queue speaker identification. |
| `POST` | `/translate` | Queue translation. |
| `POST` | `/generate-voice` | Queue voice generation. |
| `POST` | `/render` | Queue synchronisation + final render. |
| `GET` | `/status/{job_id}` | Status, stage, progress, speakers, artifacts, verification, recent events. |
| `GET` | `/jobs/{job_id}/events` | Server-sent events: `progress`, `log`, `done`. |
| `GET` | `/download/{job_id}?kind=` | `dubbed`, `original_audio`, `mkv`, `audio_only`, `subtitle_source`, `subtitle_translated`. |
| `DELETE` | `/jobs/{job_id}` | Delete the project and every file on disk. |
| `GET` | `/jobs` | List projects (dashboard / history). |
| `GET`/`PATCH`/`PUT` | `/jobs/{job_id}/segments` | Read/edit dialogue lines (studio). |
| `POST` | `/jobs/{job_id}/voices` | Assign voices per speaker. |
| `POST` | `/jobs/{job_id}/retry` | Requeue from the first incomplete stage. |
| `GET` | `/media/{job_id}?track=` | Player stream with HTTP Range support. |
| `GET` | `/jobs/{job_id}/subtitles/{kind}.vtt` | WebVTT track for the player. |
| `GET` | `/voices?lang=hi` | Voices actually installed for that language. |
| `POST` | `/voice-preview` | Synthesize a short sample. |
| `GET` | `/languages`, `/capabilities`, `/config`, `/health` | Catalogue and honest capability report. |

Errors are always structured:

```json
{"error": {"code": "TTS_UNAVAILABLE", "message": "…", "message_hi": "…", "detail": "…", "hint": "…"}}
```

---

## Interface

Ten pages, mobile-first, dark cinematic theme, English + Hindi:

| Page | Purpose |
|---|---|
| `index.html` | Home: the invariant, the nine stages, live capability report, recent projects. |
| `upload.html` | Drag & drop, client + server validation, language pickers, dialogue source, separators, real upload progress. |
| `language.html` | Browse the catalogue, see which voices exist for each language, preview them. |
| `studio.html` | Dialogue editor: fix transcript/translation, reassign speakers, choose + preview voices, run any stage, import subtitles. |
| `status.html` | Live SSE timeline, honest error card with hint + retry, verification card. |
| `player.html` | Dubbed/original audio switch, subtitles, speed, volume, resume, fullscreen. |
| `download.html` | Every artifact that actually exists, with sizes and the md5 proof. |
| `history.html` | Dashboard: all projects, statuses, delete, open. |
| `settings.html` | Backend URL, access token, interface language, defaults, live server info. |
| `privacy.html` | Privacy, retention, copyright and model-licence facts. |

The frontend is plain HTML/CSS/JS (no build step) so it can be dropped on Cloudflare Pages as-is.

---

## Models, licences and honest limits

| Component | Default here | Licence note |
|---|---|---|
| FFmpeg | static build via `imageio-ffmpeg` | LGPL/GPL build — check the build's licence before redistribution |
| ASR | faster-whisper (Whisper weights) | MIT weights, MIT wrapper |
| Diarization | built-in MFCC clustering (fallback) | this project's code |
| Diarization | pyannote.audio | model terms must be accepted; HF token required |
| Translation | NLLB-200 | CC-BY-NC-4.0 — **non-commercial** |
| Translation | Argos Translate | MIT wrapper, model packages vary |
| TTS | eSpeak NG | GPLv3 — fine for the bundled fallback |
| TTS | XTTS-v2 | Coqui Public Model Licence — **non-commercial**, needs `COQUI_TOS_AGREED=1` |
| TTS | Piper | MIT wrapper, per-voice licences vary |
| Separation | Demucs | MIT |
| Separation | stereo centre extraction | this project's code |

**Free-tier reality**

- Static hosting (Cloudflare Pages) cannot run any of these models. It hosts the UI only.
- Colab free sessions disconnect and forbid production streaming; they are for experiments.
- Free CPU containers have ~0.5–2 vCPU. A 9-second clip renders in ~2 seconds here; a 90-minute film
  would take hours and may exceed the RAM for Demucs + Whisper `medium`.
- The default per-job limit is **15 minutes** and the default upload limit is **512 MB**; both are
  environment variables, not claims about what is free.
- Nothing in this repo promises unlimited free GPU processing.

See [`docs/HONEST_LIMITS.md`](docs/HONEST_LIMITS.md) for the full list and
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for free-tier recipes.

---

## Deployment on a ₹0 budget

Three supported shapes (details in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)):

1. **Single free container** (Render / Koyeb / Fly / HF Spaces Docker): run `uvicorn backend.app:app`;
   it serves the API *and* the UI. Simplest, one service.
2. **Split**: UI on **Cloudflare Pages** (upload the `frontend/` folder), API on a small free
   container. Set the backend URL in **Settings** (stored in `localStorage`, never hard-coded).
3. **Local + tunnel**: run on your own machine/Laptop/Colab for the heavy models, expose the API
   with a tunnel, use the Pages UI from anywhere.

Docker:

```bash
docker build -t bhashaflix-ai .
docker run -p 8000:8000 -v bhashaflix-data:/data -e BFLIX_MAX_DURATION_SEC=300 bhashaflix-ai
```

---

## Tests

```bash
make test        # 43 tests, ~20 s, no mocks
```

The suite builds real media with FFmpeg and runs the real pipeline:

- `test_pipeline.py` — full dub: 2 audio tracks, original video md5 **and per-frame hashes** identical
  to the upload, speech present inside every cue, quiet after the last cue, centre suppression
  measurably removes a centre tone while keeping wide noise, mono sources honestly downgraded to
  ducking, missing ASR/translation engines fail with hints, stage order enforced, original file bytes
  unchanged, progress monotonic.
- `test_api.py` — upload validation (wrong extension, fake MP4, unsupported language), complete
  HTTP flow (upload → status → segments → range request → download → delete), pause-for-review mode,
  manual dialogue entry, voice assignment and preview.
- `test_units.py` — SRT/VTT parsing, language identification, limits, tempo fitting, no-overlap
  placement, ducking envelope, clipping protection, clustering, MFCC/embedding, pitch estimation.
- `test_diarize.py` — two synthetic voices get two consistent speaker IDs; silence is handled.

Numbers from a run on this machine (CPU only, no GPU, no AI models installed):

```
43 passed in 18.81s
```

---

## Project layout

```
bhashaflix-ai/
├── backend/
│   ├── app.py                 FastAPI app, static hosting, retention sweeper
│   ├── config.py              every knob, env-driven
│   ├── db.py                  SQLite (WAL) schema
│   ├── models.py              stage machine, error catalogue (EN/HI)
│   ├── security.py            token auth, rate limit, path guards
│   ├── engines/               media (FFmpeg/PyAV), dsp, asr, diarize, translate, tts, separate
│   ├── services/              pipeline, repo, mix, render, streaming, subtitle, validation
│   ├── routes/                jobs.py, meta.py
│   └── workers/worker.py      in-process queue, requeues interrupted jobs
├── frontend/                  10 pages + css/ + js/ (no build step)
├── scripts/demo_e2e.py        real end-to-end demo over HTTP
├── tests/                     pytest suite (real media)
├── docs/                      ARCHITECTURE.md, DEPLOYMENT.md, HONEST_LIMITS.md
├── storage/                   jobs/ (git-ignored), SQLite db, models
├── requirements.txt           core
├── requirements-ai.txt        optional models
├── Makefile · Dockerfile · .env.example
```

---

## Security & privacy

- Uploads validated by extension, magic bytes, container probe, duration and audio-track checks;
  dangerous extensions are refused before any FFmpeg call.
- Hard byte cap while streaming (the client's `Content-Length` is never trusted).
- Job ids are 32-hex random; nothing is publicly listed; media is only served through those ids.
- `BFLIX_API_TOKEN` turns on `X-API-Token` auth for every API route; rate limiting per client IP.
- Model/API keys live only in server env vars — the browser never receives one.
- Default retention: 24 h, plus instant user deletion and a background sweeper.
- Voice cloning is disabled unless the operator explicitly enables it.
- Only process content you own or are allowed to process; this is a personal dubbing tool, not a
  streaming service.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `FFMPEG_MISSING` | Install ffmpeg or `pip install imageio-ffmpeg`, or set `BFLIX_FFMPEG`. |
| `ASR_UNAVAILABLE` with a hint listing pip commands | No speech model installed. Install one, or upload subtitles / set `input_mode=manual`. |
| `TRANSLATE_UNAVAILABLE` | Install NLLB/Argos, set `BFLIX_LLM_BASE_URL`+`BFLIX_LLM_API_KEY`, or upload translated subtitles. |
| `TTS_UNAVAILABLE` for Bhojpuri | eSpeak NG has no Bhojpuri voice; install XTTS/Piper voices or pick Hindi. |
| `DURATION_TOO_LONG` | Raise `BFLIX_MAX_DURATION_SEC` — but a long film needs real hardware. |
| Dub sounds robotic | That is eSpeak NG. Install XTTS-v2 (`COQUI_TOS_AGREED=1`) or Piper voices. |
| Old voice still audible | Source audio is mono, or separation fell back to ducking — the warning says which. |
| `video fingerprint mismatch` | Should be impossible with `-c:v copy`; treat it as a bug and do not publish the file. |
| Player shows "file missing" | The project expired (retention) or was deleted. |

---

## Roadmap

- [x] Phase 1 — responsive site, dashboard, upload, language selector, player
- [x] Phase 2 — backend, FFmpeg analysis and audio extraction with tests
- [x] Phase 3 — timestamped transcription + translation plumbing (models pluggable)
- [x] Phase 4 — speaker identification (pyannote + offline fallback) and per-speaker voices
- [x] Phase 5 — separation, mixing, synchronisation with overlap protection
- [x] Phase 6 — render with untouched video stream + md5 proof
- [x] Phase 7 — tests across languages/speakers/mono/stereo; honest error catalogue
- [ ] Chunked/resumable uploads for very large files
- [ ] Optional GPU worker split (queue in SQLite already decouples the API from the worker)
- [ ] Per-speaker voice cloning with an explicit consent record
- [ ] Automatic subtitle-quality scoring before the expensive stages

---

*Built to be honest: the interesting part is not that it dubs, it is that it never touches your
picture and never pretends a missing model worked.*
