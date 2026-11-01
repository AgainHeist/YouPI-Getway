"""The dubbing pipeline: nine real stages, one honest progress value each.

Design rules:
  * The uploaded file is never modified; all work happens on derived files.
  * Every stage can run on its own (the granular API endpoints) and is
    idempotent, so a failed render can be retried without re-transcribing.
  * Progress is computed from completed work units, never from a timer.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ..engines.asr import ASRError, ScriptASR, available_asr, build_asr
from ..engines.diarize import (
    DiarizerError,
    available_diarizers,
    build_diarizer,
    diarization_quality,
    speaker_label,
)
from ..engines.media import (
    MediaError,
    audio_duration,
    convert_audio,
    decode_to_numpy,
    extract_audio,
    probe,
    write_wav,
)
from ..engines.separate import build_separator
from ..engines.translate import TranslateError, build_translator
from ..engines.tts import TTSError, assign_speaker_voices, build_tts, default_voice_for
from ..models import Segment
from . import languages as lang_mod
from . import mix as mix_mod
from . import render as render_mod
from . import repo
from .srt import parse_subtitles, read_subtitles, write_srt

log = logging.getLogger("bhashaflix.pipeline")

STAGE_SPANS: dict[str, tuple[float, float]] = {
    "extracting_audio": (3.0, 11.0),
    "transcribing": (11.0, 34.0),
    "identifying_speakers": (34.0, 44.0),
    "translating": (44.0, 62.0),
    "generating_voices": (62.0, 82.0),
    "synchronizing_audio": (82.0, 91.0),
    "rendering": (91.0, 99.5),
}

AUTO_SEQUENCE_BEFORE_VOICE = ["extracting_audio", "transcribing", "identifying_speakers", "translating"]
AUTO_SEQUENCE = AUTO_SEQUENCE_BEFORE_VOICE + ["generating_voices", "synchronizing_audio", "rendering"]


class StageFailure(RuntimeError):
    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


@dataclass
class JobPaths:
    root: Path
    source: Path
    work: Path
    out: Path
    tts: Path

    @classmethod
    def for_job(cls, job: dict) -> "JobPaths":
        root = Path(job["dir"])
        return cls(
            root=root,
            source=root / "source",
            work=root / "work",
            out=root / "out",
            tts=root / "work" / "tts",
        )


_job_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def job_lock(job_id: str) -> threading.Lock:
    with _locks_guard:
        return _job_locks.setdefault(job_id, threading.Lock())


class Pipeline:
    def __init__(self, job: dict):
        self.job = job
        self.job_id = job["id"]
        self.paths = JobPaths.for_job(job)
        self.options: dict = job.get("options") or {}

    # ------------------------------------------------------------------ util --
    @property
    def target_lang(self) -> str:
        return (self.job.get("target_lang") or "hi").lower()

    @property
    def declared_source_lang(self) -> str:
        return (self.job.get("source_lang") or "auto").lower()

    def audio_stream_index(self) -> int:
        return int(self.options.get("audio_stream", 0) or 0)

    def source_file(self) -> Path:
        for path in sorted(self.paths.source.iterdir()):
            if path.suffix.lower() in {".mp4", ".mkv", ".mov", ".m4v", ".webm"}:
                return path
        raise StageFailure("INTERNAL_ERROR", "The uploaded file is missing from storage.")

    def media_info(self) -> dict:
        cache = self.paths.work / "media.json"
        if cache.exists():
            return json.loads(cache.read_text())
        info = probe(self.source_file()).to_dict()
        self.paths.work.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(info, indent=2))
        return info

    def duration(self) -> float:
        return float(self.media_info().get("duration") or 0.0)

    def progress(self, stage: str, fraction: float, message: str | None = None) -> None:
        start, end = STAGE_SPANS.get(stage, (0.0, 100.0))
        fraction = max(0.0, min(1.0, float(fraction)))
        overall = start + (end - start) * fraction
        repo.mark_stage(self.job_id, stage, overall, message)
        self.job = repo.get_job(self.job_id) or self.job

    def note(self, message: str, level: str = "info", stage: str | None = None) -> None:
        repo.add_event(self.job_id, stage or self.job.get("stage", "queued"), message, level=level)
        log.info("[%s] %s", self.job_id[:8], message)

    def find_sidecar(self, kind: str) -> Path | None:
        """Look for a user-provided subtitle file (source or translated)."""
        for path in sorted(self.paths.source.glob("*")):
            name = path.name.lower()
            if path.suffix.lower() not in {".srt", ".vtt"}:
                continue
            if kind == "source" and ("." + self.target_lang + ".") not in name and "_source" in name:
                return path
            if kind == "source" and name.startswith("source"):
                return path
            if kind == "translated" and (name.startswith("translated") or f".{self.target_lang}." in name):
                return path
        return None

    # ------------------------------------------------------------- stage 2 ----
    def extract_audio(self) -> dict:
        self.progress("extracting_audio", 0.05, "Inspecting the uploaded file with FFprobe/PyAV.")
        info = self.media_info()
        if not info.get("audio_streams"):
            raise StageFailure("NO_AUDIO_STREAM", "The uploaded file has no audio track.")
        audio_index = self.audio_stream_index()
        source = self.source_file()
        full = self.paths.work / "audio_full.wav"
        self.progress("extracting_audio", 0.3, "Extracting the original audio track (unchanged samples).")
        extract_audio(
            source, full,
            stream_index=audio_index,
            sample_rate=settings.work_sample_rate,
            channels=2,
        )
        self.progress("extracting_audio", 0.75, "Preparing a 16 kHz mono copy for speech recognition.")
        asr_wav = self.paths.work / "audio_asr.wav"
        convert_audio(full, asr_wav, sample_rate=settings.asr_sample_rate, channels=1)
        duration = float(info.get("duration") or audio_duration(full))
        result = {
            "audio_full": str(full),
            "audio_asr": str(asr_wav),
            "duration": round(duration, 3),
            "sample_rate": settings.work_sample_rate,
            "source_audio_stream": audio_index,
            "source_audio_channels": (info["audio_streams"][audio_index].get("channels")
                                      if len(info["audio_streams"]) > audio_index else None),
        }
        self.progress("extracting_audio", 1.0, f"Audio extracted ({duration:.1f}s of dialogue to analyse).")
        repo.update_job(self.job_id, artifacts={**(self.job.get("artifacts") or {}), "audio": result})
        return result

    # ------------------------------------------------------------- stage 3 ----
    def transcribe(self) -> list[Segment]:
        if self.job.get("input_mode") == "manual":
            if repo.segments_available(self.job_id):
                segments = repo.get_segments(self.job_id)
                self.note(f"Using {len(segments)} dialogue lines entered in the studio (manual mode).")
                self.progress("transcribing", 1.0, "Dialogue supplied manually — nothing to transcribe.")
                return segments
            raise StageFailure(
                "STAGE_OUT_OF_ORDER",
                "This project is in manual mode but no dialogue lines exist yet.",
                "Open the studio, add or import your lines, save, then run translation.",
            )

        asr_wav = self.paths.work / "audio_asr.wav"
        if not asr_wav.exists():
            self.extract_audio()
        source_sidecar = self.find_sidecar("source")
        cues = read_subtitles(source_sidecar) if source_sidecar else None
        mode = self.job.get("input_mode") or "auto"
        self.progress("transcribing", 0.05, "Loading the speech-recognition engine.")
        if cues:
            engine = ScriptASR(cues)
            self.note(f"Using imported subtitles '{source_sidecar.name}' as the dialogue source.")
        elif mode == "subtitles" and not cues:
            raise StageFailure(
                "ASR_UNAVAILABLE",
                "This project is set to 'imported subtitles' but no subtitle file was uploaded.",
                "Upload an SRT/VTT file, or switch the project to automatic transcription.",
            )
        else:
            try:
                engine = build_asr(self.options.get("asr_engine"))
            except ASRError as exc:
                raise StageFailure(exc.code, str(exc), exc.hint) from exc

        self.progress("transcribing", 0.15, f"Transcribing with {engine.name}.")
        try:
            result = engine.transcribe(asr_wav, language=None if self.declared_source_lang == "auto" else self.declared_source_lang)
        except ASRError as exc:
            raise StageFailure(exc.code, str(exc), exc.hint) from exc
        except MemoryError as exc:  # pragma: no cover
            raise StageFailure("OUT_OF_MEMORY", "Speech recognition ran out of memory.") from exc
        except Exception as exc:  # pragma: no cover - model specific
            raise StageFailure("TRANSCRIBE_FAILED", f"Speech recognition failed: {exc}") from exc

        if not result.segments:
            raise StageFailure(
                "NO_DIALOGUE",
                "No speech was detected in this clip.",
                "Check that the clip actually contains dialogue, or import subtitles manually.",
            )
        detected = (result.language or "unknown").lower()
        if detected not in {"unknown", ""} and not lang_mod.is_supported(detected):
            self.note(
                f"Detected language '{detected}' is not in the BhashaFlix catalogue; "
                "continuing but translation may be unavailable.",
                level="warning",
            )
        self.progress("transcribing", 0.8, f"Detected {detected} — building {len(result.segments)} dialogue lines.")

        segments = [
            Segment(
                id=i,
                start=float(s["start"]),
                end=max(float(s["end"]), float(s["start"]) + 0.2),
                text=(s.get("text") or "").strip(),
                confidence=s.get("confidence"),
            )
            for i, s in enumerate(result.segments)
        ]
        repo.replace_segments(self.job_id, segments)
        artifacts = dict(self.job.get("artifacts") or {})
        artifacts["asr"] = {
            "engine": result.engine,
            "detected_language": detected,
            "language_probability": result.language_probability,
            "language_source": result.language_source,
            "segment_count": len(segments),
            "origin": "imported-subtitles" if cues else "asr",
        }
        updates: dict = {"artifacts": artifacts}
        if self.declared_source_lang in {"auto", ""} and lang_mod.is_supported(detected):
            updates["source_lang"] = detected
        repo.update_job(self.job_id, **updates)
        self.job = repo.get_job(self.job_id) or self.job
        self.progress("transcribing", 1.0, f"Transcribed {len(segments)} lines ({result.engine}).")
        return segments

    # ------------------------------------------------------------- stage 4 ----
    def identify_speakers(self) -> list[dict]:
        segments = repo.get_segments(self.job_id)
        if not segments:
            raise StageFailure("STAGE_OUT_OF_ORDER", "Transcribe the dialogue before identifying speakers.")
        manual = (self.options.get("speakers_manual") or {})
        if manual:
            assignments = [manual.get(str(s.id), manual.get(s.speaker, speaker_label(0))) for s in segments]
            from ..engines.diarize import normalize_assignments

            assignments = normalize_assignments(assignments)
            for seg, speaker in zip(segments, assignments):
                seg.speaker = speaker
            repo.replace_segments(self.job_id, segments)
            speakers = self._speaker_summary(assignments, segments)
            self.progress("identifying_speakers", 1.0, "Speaker labels were set manually.")
            repo.update_job(self.job_id, speakers=speakers)
            return speakers

        self.progress("identifying_speakers", 0.1, "Analysing voice characteristics per line.")
        try:
            diarizer = build_diarizer(self.options.get("diarize_engine"))
            result = diarizer.run(
                self.paths.work / "audio_asr.wav",
                [{"start": s.start, "end": s.end, "id": s.id, "text": s.text} for s in segments],
            )
        except DiarizerError as exc:
            raise StageFailure(exc.code, str(exc), exc.hint) from exc
        except MemoryError as exc:  # pragma: no cover
            raise StageFailure("OUT_OF_MEMORY", "Speaker identification ran out of memory.") from exc
        except Exception as exc:  # pragma: no cover
            log.exception("diarization failed")
            raise StageFailure("INTERNAL_ERROR", f"Speaker identification failed: {exc}") from exc

        for seg, speaker in zip(segments, result.assignments):
            seg.speaker = speaker
        repo.replace_segments(self.job_id, segments)
        speakers = result.speakers or self._speaker_summary(result.assignments, segments)

        # Suggest a voice per speaker now so the studio has something to show.
        try:
            speakers = assign_speaker_voices(speakers, self.target_lang, engine=self.options.get("tts_engine"))
        except TTSError as exc:
            self.note(f"Voice suggestion unavailable: {exc}", level="warning")

        quality = diarization_quality(result.assignments, [{"start": s.start, "end": s.end} for s in segments])
        artifacts = dict(self.job.get("artifacts") or {})
        artifacts["diarization"] = {
            "engine": result.engine,
            "confidence": result.confidence,
            "warnings": result.warnings,
            "quality": quality,
        }
        repo.update_job(self.job_id, speakers=speakers, artifacts=artifacts)
        self.job = repo.get_job(self.job_id) or self.job
        self.progress(
            "identifying_speakers", 1.0,
            f"{len(speakers)} speaker(s) identified with {result.engine}.",
        )
        return speakers

    def _speaker_summary(self, assignments: list[str], segments: list[Segment]) -> list[dict]:
        counts: dict[str, int] = {}
        for value in assignments:
            counts[value] = counts.get(value, 0) + 1
        return [
            {
                "id": speaker,
                "label": "Speaker " + str(int(speaker.split("_")[-1])),
                "gender": "unknown",
                "pitch_hz": None,
                "segments": count,
                "voice": "",
            }
            for speaker, count in sorted(counts.items())
        ]

    # ------------------------------------------------------------- stage 5 ----
    def translate(self) -> list[Segment]:
        segments = repo.get_segments(self.job_id)
        if not segments:
            raise StageFailure("STAGE_OUT_OF_ORDER", "Transcribe the dialogue before translating.")
        source_lang = (self.job.get("source_lang") or "auto").lower()
        target_lang = self.target_lang
        if not lang_mod.is_supported(target_lang):
            raise StageFailure(
                "UNSUPPORTED_LANGUAGE",
                f"'{target_lang}' is not a supported target language.",
                "Pick a language from /api/languages.",
            )
        if source_lang in {"auto", "unknown"}:
            source_lang, confidence = lang_mod.detect_text_language(" ".join(s.text for s in segments))
            self.note(f"Source language inferred from the dialogue text: {source_lang} ({confidence:.0%}).")

        # 1) user supplied a translated subtitle file
        translated_sidecar = self.find_sidecar("translated")
        if translated_sidecar:
            cues = read_subtitles(translated_sidecar)
            aligned = _align_translation(segments, cues)
            for seg, text in zip(segments, aligned):
                seg.translated_text = text
            repo.replace_segments(self.job_id, segments)
            artifacts = dict(self.job.get("artifacts") or {})
            artifacts["translation"] = {"engine": "imported-subtitles", "file": translated_sidecar.name}
            repo.update_job(self.job_id, artifacts=artifacts)
            self.progress("translating", 1.0, f"Applied imported translation ({translated_sidecar.name}).")
            return segments

        # 2) already translated by the user in the studio
        if all((s.translated_text or "").strip() for s in segments):
            self.progress("translating", 1.0, "Using the translations already edited in the studio.")
            return segments

        self.progress("translating", 0.05, f"Loading a {source_lang} -> {target_lang} translator.")
        try:
            translator = build_translator(
                self.options.get("translate_engine"), src=source_lang, tgt=target_lang
            )
        except TranslateError as exc:
            raise StageFailure(exc.code, str(exc), exc.hint) from exc

        texts = [s.text for s in segments]
        batch = 16
        out: list[str] = []
        try:
            for i in range(0, len(texts), batch):
                chunk = texts[i:i + batch]
                result = translator.translate_batch(chunk, source_lang, target_lang)
                if len(result.texts) != len(chunk):
                    raise StageFailure("TRANSLATE_FAILED", "The translator returned a mismatched number of lines.")
                out.extend(result.texts)
                self.progress(
                    "translating",
                    0.1 + 0.85 * min(1.0, (i + len(chunk)) / max(1, len(texts))),
                    f"Translated {min(i + len(chunk), len(texts))}/{len(texts)} lines.",
                )
        except StageFailure:
            raise
        except TranslateError as exc:
            raise StageFailure(exc.code, str(exc), exc.hint) from exc
        except MemoryError as exc:  # pragma: no cover
            raise StageFailure("OUT_OF_MEMORY", "Translation ran out of memory.") from exc
        except Exception as exc:  # pragma: no cover
            raise StageFailure("TRANSLATE_FAILED", f"Translation failed: {exc}") from exc

        for seg, text in zip(segments, out):
            seg.translated_text = (text or "").strip()
        repo.replace_segments(self.job_id, segments)
        artifacts = dict(self.job.get("artifacts") or {})
        artifacts["translation"] = {
            "engine": translator.name,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }
        repo.update_job(self.job_id, artifacts=artifacts, source_lang=source_lang)
        self.job = repo.get_job(self.job_id) or self.job
        self.progress("translating", 1.0, f"Translated {len(segments)} lines with {translator.name}.")
        return segments

    # ------------------------------------------------------------- stage 6 ----
    def generate_voices(self) -> list[dict]:
        segments = repo.get_segments(self.job_id)
        if not segments:
            raise StageFailure("STAGE_OUT_OF_ORDER", "Translate the dialogue before generating voices.")
        missing = [s.id for s in segments if not (s.translated_text or "").strip()]
        if missing:
            raise StageFailure(
                "TRANSLATE_FAILED",
                f"{len(missing)} line(s) have no translated text yet (first: line {missing[0] + 1}).",
                "Run translation, or fill in the missing lines in the studio.",
            )
        target_lang = self.target_lang
        voice_map = dict(self.options.get("voice_map") or {})
        speakers = list(self.job.get("speakers") or [])
        try:
            tts = build_tts(self.options.get("tts_engine"))
        except TTSError as exc:
            raise StageFailure(exc.code, str(exc), exc.hint) from exc

        available_voices = {v.id for v in tts.voices(target_lang)}
        if not available_voices:
            raise StageFailure(
                "TTS_UNAVAILABLE",
                f"The installed TTS engine '{tts.name}' has no voice for '{target_lang}'.",
                "Install a Piper/XTTS voice for this language, or pick another target language.",
            )

        speaker_ids = []
        for seg in segments:
            if seg.speaker not in speaker_ids:
                speaker_ids.append(seg.speaker)
        if not speakers:
            speakers = [{"id": sid, "label": "Speaker " + sid.split("_")[-1], "gender": "unknown",
                         "voice": ""} for sid in speaker_ids]
        # honour explicit overrides, then auto-assign the rest
        for speaker in speakers:
            if speaker["id"] in voice_map:
                speaker["voice"] = voice_map[speaker["id"]]
        try:
            speakers = assign_speaker_voices(speakers, target_lang, engine=tts.name)
        except TTSError as exc:
            raise StageFailure(exc.code, str(exc), exc.hint) from exc
        # speakers present in segments but missing from the summary
        for sid in speaker_ids:
            if not any(s["id"] == sid for s in speakers):
                speakers.append({"id": sid, "label": "Speaker " + sid.split("_")[-1],
                                 "gender": "unknown", "voice": ""})
        for speaker in speakers:
            if not speaker.get("voice"):
                speaker["voice"] = default_voice_for(target_lang, speaker.get("gender", "unknown"), engine=tts.name)
            if speaker["voice"] not in available_voices:
                self.note(
                    f"Voice '{speaker['voice']}' is not available for {target_lang}; using the engine default.",
                    level="warning",
                )
                speaker["voice"] = default_voice_for(target_lang, speaker.get("gender", "unknown"), engine=tts.name)

        voice_by_speaker = {s["id"]: s["voice"] for s in speakers}
        self.paths.tts.mkdir(parents=True, exist_ok=True)
        total = len(segments)
        failed: list[str] = []
        for index, seg in enumerate(segments):
            raw = self.paths.tts / f"seg_{seg.id:05d}_raw.wav"
            fitted = self.paths.tts / f"seg_{seg.id:05d}.wav"
            voice = voice_by_speaker.get(seg.speaker) or default_voice_for(target_lang)
            text = seg.translated_text.strip()
            try:
                tts.synthesize(text, target_lang, voice, raw)
                natural = audio_duration(raw)
                if natural <= 0.05:
                    raise TTSError("TTS_FAILED", "The engine returned an empty clip.")
                tempo, overflow = mix_mod.compute_tempo(natural, seg.duration)
                path, fitted_duration = mix_mod.fit_clip(
                    raw, seg.duration, tempo, fitted, sample_rate=settings.dub_sample_rate
                )
                seg.tts_duration = round(natural, 3)
                seg.tempo = tempo
                seg.flags = [f for f in seg.flags if f != "tts_failed"]
                if overflow:
                    seg.flags.append("time_compressed")
                seg.flags.append(f"voice:{voice}")
                self.note(
                    f"Line {seg.id + 1}: {natural:.2f}s of speech fitted into {seg.duration:.2f}s "
                    f"(tempo {tempo:.2f}x, voice {voice}).",
                )
            except (TTSError, MediaError) as exc:
                seg.flags = [f for f in seg.flags if not f.startswith("voice:")]
                seg.flags.append("tts_failed")
                failed.append(f"line {seg.id + 1}: {exc}")
                log.warning("TTS failed for line %s: %s", seg.id + 1, exc)
            self.progress(
                "generating_voices",
                (index + 1) / total,
                f"Generated {index + 1}/{total} dialogue lines.",
            )
        repo.replace_segments(self.job_id, segments)
        repo.update_job(self.job_id, speakers=speakers)
        self.job = repo.get_job(self.job_id) or self.job
        if failed and len(failed) == total:
            raise StageFailure(
                "TTS_FAILED",
                "Every line failed to synthesize.",
                failed[0] if failed else None,
            )
        if failed:
            repo.add_note(self.job_id, {
                "kind": "warning",
                "message": f"{len(failed)} line(s) could not be voiced and will be silent in the dub.",
                "detail": failed[:5],
            })
        self.progress("generating_voices", 1.0, f"Voiced {total - len(failed)}/{total} lines with {tts.name}.")
        return speakers

    # ------------------------------------------------------------- stage 7 ----
    def synchronize_audio(self) -> dict:
        segments = repo.get_segments(self.job_id)
        if not segments:
            raise StageFailure("STAGE_OUT_OF_ORDER", "Generate the voices before synchronizing audio.")
        duration = self.duration()
        if duration <= 0:
            raise StageFailure("MEDIA_ERROR", "The source duration is unknown.")
        self.progress("synchronizing_audio", 0.1, "Separating dialogue from music and effects.")

        audio_full = self.paths.work / "audio_full.wav"
        if not audio_full.exists():
            self.extract_audio()
        info = self.media_info()
        channels = None
        audio_index = self.audio_stream_index()
        if len(info.get("audio_streams", [])) > audio_index:
            channels = info["audio_streams"][audio_index].get("channels")
        mono_source = channels == 1

        separator = build_separator(self.options.get("separate"))
        separation = None
        warnings: list[str] = []
        if separator is None:
            raise StageFailure(
                "RENDER_FAILED",
                "No audio separator could be loaded.",
                "Install demucs, or set BFLIX_SEPARATE_ENGINE=center-suppression / ducking.",
            )
        try:
            separation = separator.run(audio_full, self.paths.work, mono_source=mono_source)
        except MediaError as exc:
            self.note(f"Separation failed ({exc}); falling back to ducking.", level="warning")
            from ..engines.separate import DuckingSeparator

            separation = DuckingSeparator().run(audio_full, self.paths.work, mono_source=mono_source)
        warnings.extend(separation.warnings)

        self.progress("synchronizing_audio", 0.45, "Aligning dubbed lines to the original timestamps.")
        clips: list[mix_mod.FittedClip] = []
        for seg in segments:
            fitted = self.paths.tts / f"seg_{seg.id:05d}.wav"
            natural = seg.tts_duration or 0.0
            clips.append(
                mix_mod.FittedClip(
                    segment_id=seg.id,
                    start=seg.start,
                    end=seg.end,
                    slot=seg.duration,
                    natural=natural,
                    tempo=seg.tempo or 1.0,
                    placed_end=seg.end,
                    clipped=False,
                    path=fitted if fitted.exists() else None,
                )
            )
        dialogue_track, clips, mix_warnings = mix_mod.build_dialogue_track(
            [{"id": s.id, "start": s.start, "end": s.end} for s in segments],
            clips,
            duration,
            sample_rate=settings.dub_sample_rate,
            work_dir=self.paths.work,
        )
        warnings.extend(mix_warnings)
        for seg, clip in zip(segments, clips):
            if clip.clipped:
                if "time_compressed" not in seg.flags:
                    seg.flags.append("time_compressed")
            elif "time_compressed" in seg.flags and not clip.clipped:
                pass
        repo.replace_segments(self.job_id, segments)

        dialogue_path = self.paths.work / "dialogue_track.wav"
        write_wav(dialogue_path, dialogue_track, settings.dub_sample_rate, channels=1)

        self.progress("synchronizing_audio", 0.75, "Mixing the new dialogue with the preserved background.")
        background, bg_rate = decode_to_numpy(separation.background_path, channels=2, sample_rate=settings.dub_sample_rate)
        duck = bool(self.options.get("duck", separation.dialogue_removed))
        mixed, mix_metrics = mix_mod.mix_tracks(
            background, dialogue_track, sample_rate=settings.dub_sample_rate, duck=duck
        )
        final_audio = self.paths.work / "dubbed_mix.wav"
        mix_mod.write_mix(final_audio, mixed, settings.dub_sample_rate)

        overlapped = sum(1 for a, b in zip(clips, clips[1:]) if a.placed_end > b.start + 0.001)
        if overlapped:
            warnings.append(f"{overlapped} line(s) still touch the next line; the mixer trimmed them to avoid overlap.")

        details = {
            "engine": separation.engine,
            "quality": separation.quality,
            "dialogue_removed": separation.dialogue_removed,
            "warnings": warnings,
            "metrics": {**mix_metrics, **separation.metrics, "overlaps": overlapped},
            "dialogue_track": str(dialogue_path),
            "mixed_audio": str(final_audio),
            "duration": round(duration, 3),
        }
        artifacts = dict(self.job.get("artifacts") or {})
        artifacts["sync"] = details
        repo.update_job(self.job_id, artifacts=artifacts)
        self.job = repo.get_job(self.job_id) or self.job
        for warning in warnings:
            repo.add_note(self.job_id, {"kind": "warning", "message": warning})
        self.progress(
            "synchronizing_audio", 1.0,
            f"Audio synchronized — background kept with {separation.engine} ({separation.quality} quality).",
        )
        return details

    # ------------------------------------------------------------- stage 8 ----
    def render(self) -> dict:
        segments = repo.get_segments(self.job_id)
        if not segments:
            raise StageFailure("STAGE_OUT_OF_ORDER", "Nothing to render yet.")
        mixed = self.paths.work / "dubbed_mix.wav"
        if not mixed.exists():
            self.synchronize_audio()
        self.progress("rendering", 0.1, "Writing subtitle tracks.")
        source_lang = (self.job.get("source_lang") or "auto").lower()
        cues = [
            {"start": s.start, "end": s.end, "text": s.text, "translated_text": s.translated_text}
            for s in segments
        ]
        subtitles = {}
        if self.options.get("write_subtitles", True):
            subtitles["source"] = write_srt(self.paths.out / f"dialogue_{source_lang or 'source'}.srt", cues, translated=False)
            subtitles["translated"] = write_srt(self.paths.out / f"dialogue_{self.target_lang}.srt", cues, translated=True)
            vtt = self.paths.out / f"dialogue_{self.target_lang}.vtt"
            from .srt import to_vtt

            vtt.write_text(to_vtt(cues, translated=True), encoding="utf-8")
            subtitles["translated_vtt"] = vtt

        self.progress("rendering", 0.35, "Muxing the original video stream with the new audio (video copied, not re-encoded).")
        try:
            result = render_mod.render(
                source=self.source_file(),
                dubbed_audio=mixed,
                out_dir=self.paths.out,
                target_lang=self.target_lang,
                source_lang=source_lang if source_lang not in {"auto", "unknown"} else "und",
                audio_stream_index=self.audio_stream_index(),
                duration=self.duration(),
                subtitles={k: v for k, v in subtitles.items() if not k.endswith("_vtt")},
            )
        except MediaError as exc:
            raise StageFailure(exc.code, str(exc), exc.hint) from exc
        except Exception as exc:  # pragma: no cover
            raise StageFailure("RENDER_FAILED", f"Rendering failed: {exc}") from exc

        self.progress("rendering", 0.9, "Verifying that the video frames are byte-identical to the upload.")
        audio_only = None
        try:
            audio_only = render_mod.render_audio_only(
                dub_audio=mixed, out_dir=self.paths.out, target_lang=self.target_lang
            )
        except MediaError as exc:
            log.warning("audio-only export failed: %s", exc)
            result.warnings.append("The audio-only export could not be created; the video downloads are complete.")

        artifacts = dict(self.job.get("artifacts") or {})
        artifacts["render"] = {
            "dubbed": str(result.dubbed_path),
            "original_audio": str(result.original_audio_path),
            "mkv": str(result.mkv_path) if result.mkv_path else None,
            "audio_only": str(audio_only) if audio_only else None,
            "subtitles": {k: str(v) for k, v in result.subtitles.items()},
            "subtitles_vtt": str(subtitles["translated_vtt"]) if "translated_vtt" in subtitles else None,
            "warnings": result.warnings,
            "size_bytes": result.dubbed_path.stat().st_size,
        }
        notes = list(self.job.get("notes") or [])
        for warning in result.warnings:
            notes.append({"kind": "warning", "message": warning})
        repo.update_job(
            self.job_id,
            artifacts=artifacts,
            verification=result.verification,
            notes=notes[-40:],
        )
        self.job = repo.get_job(self.job_id) or self.job
        if result.verification.get("video_identical") is False:
            raise StageFailure(
                "RENDER_FAILED",
                "The rendered picture does not match the original. The output was discarded.",
            )
        self.progress("rendering", 1.0, "Final render complete and verified.")
        return artifacts["render"]

    # --------------------------------------------------------------- runner --
    def run_stage(self, stage: str) -> dict:
        if stage == "analyze":
            info = self.media_info()
            self.extract_audio()
            return info
        if stage == "extract_audio":
            return self.extract_audio()
        if stage == "transcribe":
            segments = self.transcribe()
            return {"segments": len(segments)}
        if stage == "speakers":
            return {"speakers": self.identify_speakers()}
        if stage == "translate":
            return {"translated": len(self.translate())}
        if stage == "generate_voice":
            return {"speakers": self.generate_voices()}
        if stage == "synchronize":
            return self.synchronize_audio()
        if stage == "render":
            return self.render()
        raise StageFailure("STAGE_OUT_OF_ORDER", f"Unknown stage '{stage}'.")


def _align_translation(segments: list[Segment], cues: list[dict]) -> list[str]:
    """Match translated cues to source lines (by index, then by time)."""
    if len(cues) == len(segments):
        return [c["text"] for c in cues]
    out: list[str] = []
    for seg in segments:
        midpoint = (seg.start + seg.end) / 2.0
        best = None
        best_overlap = 0.0
        for cue in cues:
            overlap = min(cue["end"], seg.end) - max(cue["start"], seg.start)
            if overlap > best_overlap:
                best, best_overlap = cue, overlap
        if best is None:
            best = min(cues, key=lambda c: abs((c["start"] + c["end"]) / 2.0 - midpoint))
        out.append(best["text"])
    return out


# --------------------------------------------------------------------------- #
# public entry points used by the API and the worker
# --------------------------------------------------------------------------- #
def run_full_job(job_id: str, *, stages: list[str] | None = None, force: bool = False) -> dict:
    job = repo.get_job(job_id)
    if not job:
        raise StageFailure("JOB_NOT_FOUND", "Project not found.")
    pipeline = Pipeline(job)
    with job_lock(job_id):
        try:
            repo.update_job(job_id, status="running", error=None)
            pipeline.job = repo.get_job(job_id) or job
            if not pipeline.paths.work.joinpath("audio_full.wav").exists():
                pipeline.progress("extracting_audio", 0.0, "Starting.")
            sequence = stages or AUTO_SEQUENCE
            done = set((repo.get_job(job_id) or {}).get("stages_done") or [])

            def should_run(stage: str) -> bool:
                # Skip a stage only when its result is already on disk and the
                # caller did not explicitly ask for a re-run.
                if force or stage not in done:
                    return True
                pipeline.note(f"Skipping {stage}: already completed for this project.")
                return False

            if "extracting_audio" in sequence and (force or not pipeline.paths.work.joinpath("audio_full.wav").exists() or "extracting_audio" not in done):
                pipeline.extract_audio()
            if "transcribing" in sequence and should_run("transcribing"):
                pipeline.transcribe()
            if "identifying_speakers" in sequence and should_run("identifying_speakers"):
                pipeline.identify_speakers()
            if "translating" in sequence and should_run("translating"):
                pipeline.translate()
            if "generating_voices" in sequence and should_run("generating_voices"):
                pipeline.generate_voices()
            if "synchronizing_audio" in sequence and (force or "synchronizing_audio" not in done or not pipeline.paths.work.joinpath("dubbed_mix.wav").exists()):
                pipeline.synchronize_audio()
            if "rendering" in sequence and (force or not pipeline.paths.out.joinpath(f"bhashaflix_{pipeline.target_lang}.mp4").exists()):
                pipeline.render()
            # A sequence that ends with a successful render *is* a finished dub,
            # whether it came from the one-shot flow or the granular endpoints.
            if "rendering" in sequence or sequence == AUTO_SEQUENCE:
                repo.finish_job(job_id, status="completed")
                repo.add_event(
                    job_id, "completed",
                    "Dubbing finished. Original video stream verified unchanged.",
                    progress=100,
                )
            return repo.get_job(job_id) or {}
        except StageFailure as exc:
            log.warning("job %s failed at %s: %s", job_id, exc.code, exc)
            repo.finish_job(
                job_id,
                status="failed",
                error={"code": exc.code, "message": exc.message, "hint": exc.hint},
            )
            repo.add_event(job_id, job.get("stage", "failed"), exc.message, level="error")
            raise
        except MemoryError:  # pragma: no cover
            repo.finish_job(job_id, status="failed", error={"code": "OUT_OF_MEMORY", "message": "Out of memory."})
            raise StageFailure("OUT_OF_MEMORY", "The server ran out of memory.")
        except Exception as exc:  # pragma: no cover
            log.exception("unexpected failure in job %s", job_id)
            repo.finish_job(
                job_id,
                status="failed",
                error={"code": "INTERNAL_ERROR", "message": str(exc)},
            )
            raise StageFailure("INTERNAL_ERROR", str(exc))


def capabilities() -> dict:
    from ..engines.separate import available_separators
    from ..engines.tts import available_tts
    from ..engines.translate import available_translators

    tts_engines = available_tts()
    return {
        "asr": available_asr(),
        "diarize": available_diarizers(),
        "translate": available_translators(),
        "tts": tts_engines,
        "separate": available_separators(),
        "languages": {
            "targets": [lang["code"] for lang in lang_mod.target_languages()],
            "sources": [lang["code"] for lang in lang_mod.source_languages()],
        },
        "notes": [
            "Dubbing quality depends on the models installed on THIS backend; the UI never simulates a stage.",
            "Static hosting (Cloudflare Pages) cannot run these models. Point the frontend at a GPU/CPU worker.",
        ],
    }
