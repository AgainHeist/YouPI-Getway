# Honest limits

This file exists because dubbing tools are usually sold with promises the hardware cannot keep.
Everything below is measured on this codebase, not guessed.

## Picture

- The video stream is copied with `-c:v copy`. We verify it two ways in the test suite: the
  compressed-stream md5 and per-frame `framemd5` hashes of input vs output must match exactly.
- If a source container cannot hold its video codec in MP4 (rare), FFmpeg refuses the copy and the
  render fails with `RENDER_FAILED` — it never silently re-encodes.
- We do not touch resolution, frame rate, colour metadata, rotation or chapters.
- Subtitles are *added* as separate tracks/files; nothing is burned in by default.

## Sound

1. **Separation is the weakest link on a free machine.**
   - With **Demucs**: instrumental stem quality is good, but faint dialogue bleed can remain in dense
     mixes, and it needs ~2 GB RAM plus torch.
   - Without Demucs: stereo centre extraction removes what is centre-panned. Dialogue normally is,
     but so are bass and mono instruments, so those lose energy. The UI shows a warning and the
     measured `center_energy_ratio`.
   - **Mono source**: separation is impossible without ML. The fallback keeps the original mix and
     ducks it under the dub, which means the old voice is faintly audible. We say this in the job's
     warnings instead of pretending.

2. **Timing is a compromise, by design.**
   - Translated speech rarely has the same duration. Lines are time-stretched up to `1.45×`
     (configurable) and allowed to overrun their cue by 0.3 s.
   - If it still does not fit, the line is truncated with a fade and flagged `time_compressed`.
   - Two lines never overlap; a line may be trimmed to protect the next one.
   - We never retime the video to make the audio fit.

3. **Voices are not actors.**
   - eSpeak NG (bundled) is intelligible but robotic; it has no emotion model.
   - XTTS-v2 is much better and supports Hindi, but its licence is **non-commercial** and it is not
     a voice clone of the original performer — by design.
   - Voice cloning is disabled by default and requires the operator to enable it; impersonating a
     real performer without permission is not permitted.

4. **Loudness** is peak-limited, not professionally mastered. A dialogue-gain and ducking value are
   exposed in the environment for tuning.

## Language coverage

- Whisper handles ~99 languages for ASR; translation depends on the engine:
  - NLLB-200 covers Hindi, Bengali, Tamil, Telugu, Urdu, Marathi, Bhojpuri and 200 more.
  - Argos is per-pair and much weaker; LibreTranslate/LLM depend on the endpoint you configure.
- **Bhojpuri** is script-identical to Hindi. Text heuristics cannot separate them; only a model like
  NLLB can. The UI offers it as a target, but the *source* detection will usually say Hindi.
- TTS coverage is the real bottleneck: eSpeak NG covers Hindi, Bengali, Tamil, Telugu, Urdu, etc.;
  XTTS-v2 covers 17 major languages; Piper depends on the voices you download.

## Compute and cost

- A 9-second 640×360 clip, 4 dialogue lines: **~2 s** end-to-end on one CPU core with eSpeak NG
  (measured in this repo's test suite).
- Scaling is roughly linear in duration and quadratic-ish in resolution for the analysis stages.
  A 2-hour 1080p film with Whisper `medium`, NLLB and Demucs is a GPU job measured in hours.
- Free containers (512 MB) will OOM on Demucs and on Whisper `medium`. The API returns
  `OUT_OF_MEMORY`, not a fake success.
- There is **no** configuration in which "unlimited free GPU" exists. The default limits (15 min,
  512 MB) are conservative on purpose.

## What is deliberately *not* implemented

- No torrent/streaming-site integration, no catalogue, no DRM circumvention.
- No "automatic movie downloader" — you bring a file you own.
- No simulated jobs, no seeded fake progress, no placeholder download files.
- No client-side API keys: the browser never sees a model credential.

## Measured guarantees in the test suite

| Guarantee | Test |
|---|---|
| Video stream byte-identical | `test_full_pipeline_keeps_original_video_and_dubs_hindi` (`md5` + `framemd5`) |
| Dubbed speech exists inside every cue | `test_dubbed_speech_is_actually_present_and_synced` |
| No dialogue after the last cue | same test |
| Centre dialogue suppressed, wide music kept | `test_center_suppression_removes_centre_dialogue_tone` |
| Mono source produces a warning, not a lie | `test_mono_source_is_honest_about_ducking` |
| Missing ASR/translation fails with a hint | `test_missing_asr_engine_fails_honestly`, `test_missing_translator_fails_honestly` |
| Original upload never modified | `test_original_file_is_never_modified` |
| Progress is monotonic and real | `test_job_progress_is_monotonic` |
| Two voices → two stable speaker IDs | `test_two_voices_get_two_speaker_ids` |
| Upload validation rejects bad input | `test_api.py` (extension, fake MP4, unsupported language) |
