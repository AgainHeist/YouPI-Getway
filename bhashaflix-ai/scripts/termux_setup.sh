#!/data/data/com.termux/files/usr/bin/bash
# BhashaFlix AI — one-shot Termux setup.
#
#   bash scripts/termux_setup.sh
#
# It installs the Android packages we actually use, then the Python bits, then
# tells you (honestly) what will and will not run on a phone.  Nothing here
# needs root, and every step is idempotent — safe to re-run.
set -u

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }

# The script must run from inside bhashaflix-ai/ (where backend/ and requirements-*.txt live).
if [ ! -f "backend/app.py" ]; then
  warn "Run this from the bhashaflix-ai folder (I cannot see backend/app.py here)."
  cat <<'FIX'
  cd ~
  rm -rf YouPI-Getway                                    # remove the main-branch clone, if any
  git clone -b arena/b2c2def4-youpi-getway https://github.com/AgainHeist/YouPI-Getway
  cd YouPI-Getway/bhashaflix-ai
  bash scripts/termux_setup.sh
FIX
  exit 1
fi

if [ ! -d "/data/data/com.termux/files/usr" ]; then
  warn "This does not look like Termux. On a normal Linux box use: pip install -r requirements.txt"
fi

say "1/5 Android packages"
# Install one by one: a single unknown name would abort the whole list.
for pkg in python ffmpeg espeak git binutils clang make pkg-config; do
  if pkg install -y "$pkg" >/dev/null 2>&1; then
    ok "$pkg"
  else
    warn "$pkg not available from your mirror (continuing)"
  fi
done
# Prebuilt numpy for Android; building it from source takes hours on a phone.
for pkg in python-numpy rust libopenblas; do
  if pkg install -y "$pkg" >/dev/null 2>&1; then
    ok "$pkg (prebuilt)"
  else
    warn "$pkg not on this mirror"
  fi
done

say "2/5 sanity checks"
for bin in python ffmpeg espeak; do
  if command -v "$bin" >/dev/null 2>&1; then
    ok "$bin -> $(command -v "$bin")"
  else
    warn "$bin is missing; the app will report the matching stage as unavailable"
  fi
done
python -c 'import sys; print("python", sys.version.split()[0])' || exit 1

say "3/5 Python packages (this can take 10-20 minutes if pydantic-core builds from source)"
pip install --upgrade pip >/dev/null 2>&1 || true
if ! pip install -r requirements-termux.txt; then
  warn "pip failed. Most often it is pydantic-core needing Rust, or numpy needing"
  warn "openblas. Try:  pkg install rust && pip install --no-build-isolation pydantic-core"
  warn "then re-run this script. If it still fails, run the server on a laptop and"
  warn "open its address from this phone instead — see the README section"
  warn "'Run it on your phone (Termux)'."
  exit 1
fi

# Optional nicety: system espeak-ng is used automatically; the wheel is only a
# fallback if your mirror has no `espeak` package.
python - <<'PY' || true
try:
    from backend.engines.tts import locate_espeak
    lib, data = locate_espeak()
    print(f"[ok] espeak library: {lib or 'NOT FOUND'}\n[ok] espeak data   : {data or 'bundled/default'}")
    if not lib:
        print("[!] no espeak library: install `espeak` (Termux) or `pip install espeakng-loader`")
except Exception as exc:  # pragma: no cover - setup helper
    print(f"[!] could not check espeak yet: {exc}")
PY

say "4/5 what will run on this phone"
cat <<'TXT'
  works   : upload, analysis, manual / imported subtitles, eSpeak voices,
            stereo centre-suppression, FFmpeg render (-c:v copy), player, download
  missing : Whisper, NLLB, XTTS-v2, Demucs (they need torch + RAM/GPU)
            -> ASR/translation stages will honestly report "not installed";
               type the dialogue (input_mode=manual) or upload subtitles.
TXT

say "5/5 start the server"
cat <<'TXT'
  cd bhashaflix-ai
  python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
  # phone browser:  http://localhost:8000
  # other devices :  http://<phone-lan-ip>:8000

  Fill the dashboard with two finished demo projects (in a second session):
  python scripts/seed_demo_library.py
TXT
