# Deployment guide — free tiers, and where the money would go

BhashaFlix AI is one FastAPI process plus a static folder. That is deliberate: on a ₹0 budget you
want the fewest moving parts, and you want the heavy models to be replaceable without touching the
frontend.

## 0. What free hosting can and cannot do

| Layer | Can be free? | Reality check |
|---|---|---|
| Static UI (Cloudflare Pages, GitHub Pages, Netlify) | ✅ genuinely free | cannot run FFmpeg, Whisper, NLLB or XTTS |
| API + worker on a free container (Render free, Koyeb free, Fly pay-as-you-go, HF Spaces) | ✅ usually | sleeps when idle, 0.5–1 vCPU, 512 MB–1 GB RAM, ephemeral disk |
| GPU for Whisper/NLLB/XTTS/Demucs | ❌ not free | RunPod/Vast/Lambda by the minute, or your own machine |
| Storage | ⚠️ temporary | container disks are wiped on redeploy; plan for retention |

Anything claiming "unlimited free GPU dubbing of full movies" is not describing this repository, and
it is not describing reality either.

## 1. Single free container (recommended first deployment)

The app serves both the API and the frontend, so one service is enough.

```bash
# Render / Koyeb / Fly / any Docker host
docker build -t bhashaflix-ai .
docker run -p 8000:8000 \
  -v bhashaflix-data:/data \
  -e BFLIX_STORAGE_DIR=/data \
  -e BFLIX_MAX_UPLOAD_MB=200 \
  -e BFLIX_MAX_DURATION_SEC=300 \
  -e BFLIX_RETENTION_HOURS=12 \
  bhashaflix-ai
```

Recommended free-tier limits:

```
BFLIX_MAX_UPLOAD_MB=200        # free tiers rarely allow more
BFLIX_MAX_DURATION_SEC=300     # 5 minutes; a 24 fps 700 MB film is not going to fit
BFLIX_WORKER_THREADS=1         # avoid OOM on 512 MB instances
BFLIX_RETENTION_HOURS=12       # ephemeral disks rarely last longer anyway
BFLIX_SEPARATE_ENGINE=center-suppression   # Demucs will OOM here
BFLIX_TTS_ENGINE=espeak-ng     # XTTS needs ~2 GB RAM
```

If the instance has no persistent volume, mount one or accept that files vanish on redeploy —
that matches the retention promise anyway.

## 2. Split: Cloudflare Pages UI + remote API

This is the shape the spec asks for (static frontend on Pages, backend replaceable).

1. **Pages project**
   - Build command: *(none)*, output directory: `frontend`
   - Or drag the `frontend/` folder into the Pages dashboard.
   - `_headers` and `_redirects` are already included (security headers + clean URLs).
   - No environment variables and no secrets: the UI never holds a model key.

2. **Backend** on any container/machine, with CORS open to your Pages origin:

   ```
   BFLIX_CORS_ORIGINS=https://bhashaflix.pages.dev
   BFLIX_API_TOKEN=<openssl rand -hex 32>
   ```

   Setting a token is strongly recommended once the API is public; every request from the UI then
   carries `X-API-Token`.

3. **Point the UI at the backend**: open `settings.html`, paste the backend URL (and token), save.
   It is stored in `localStorage` only. Media URLs and SSE streams follow the same base.

## 3. Local machine or Colab for the models

Heavy models do not belong on a free container. Two honest options:

- **Your laptop/desktop**: install `requirements-ai.txt`, run `make run`, and expose it with a tunnel
  (`cloudflared tunnel --url http://localhost:8000`) so the Pages UI can reach it. Nothing is exposed
  that you did not open yourself.
- **Colab (experiment only)**: Google's terms do not allow long-running public services, sessions
  disconnect, and free GPU has no uptime guarantee. Use it to *test* one clip, not to host.

## 4. Moving to a GPU worker later

The API and the worker are already separated by a SQLite job table, so the upgrade path is:

1. Keep the API/UI where it is.
2. Run the same image on a GPU box with `BFLIX_WORKER_THREADS=2` and the model env vars set.
3. Share the storage directory (NFS/S3-mounted volume) or move the queue to Redis/Postgres.

The pipeline code does not change — engines are chosen per job by what is installed.

## 5. Environment reference

See [`.env.example`](../.env.example) — every variable, with the default and the reason.

## 6. Operational checklist

- [ ] `curl /api/health` returns `ffmpeg` not `null`
- [ ] `curl /api/capabilities` lists the engines you expect (and no more)
- [ ] Upload limit and duration limit fit the machine you actually rent
- [ ] Retention matches your storage reality
- [ ] `BFLIX_API_TOKEN` set for any public instance
- [ ] HTTPS terminated by the platform (never run the free tier over plain HTTP)
- [ ] Disk cleaned by the retention sweeper (watch `/api/health` → `queue.storage_bytes`)
