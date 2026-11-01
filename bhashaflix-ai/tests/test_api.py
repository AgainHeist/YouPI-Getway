"""HTTP API tests (real uploads, real worker, real renders)."""
from __future__ import annotations

import io
import time


def _wait(client, job_id, *, timeout: float = 180.0, terminal=("completed", "failed", "awaiting_input")):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/status/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in terminal:
            return last
        time.sleep(0.4)
    raise AssertionError(f"job did not finish in time: {last}")


def test_health_and_config(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["ffmpeg"], "FFmpeg must be available for the API to work"
    config = client.get("/api/config").json()
    assert config["default_target"] == "hi"
    assert ".mp4" in config["supported_upload_ext"]
    assert config["auth_required"] is False
    assert "stages" in config


def test_languages_and_capabilities(client):
    langs = client.get("/api/languages").json()
    assert "hi" in langs["targets"]
    codes = {item["code"] for item in langs["languages"]}
    assert {"hi", "en", "bho", "ta", "ja"} <= codes
    caps = client.get("/api/capabilities").json()
    for key in ("asr", "diarize", "translate", "tts", "separate"):
        assert isinstance(caps[key], list) and caps[key]
        for engine in caps[key]:
            assert "available" in engine and "reason" in engine


def test_voices_are_only_listed_when_installed(client):
    payload = client.get("/api/voices?lang=hi").json()
    if payload["engines"]:
        assert payload["catalog"].get("hi"), "an installed engine must expose Hindi voices"
        for voice in payload["catalog"]["hi"]:
            for key in ("id", "engine", "label", "gender", "sample_rate"):
                assert key in voice


def test_upload_rejects_wrong_extension(client):
    response = client.post(
        "/api/upload",
        files={"file": ("malware.exe", io.BytesIO(b"MZ\x00\x00"), "application/octet-stream")},
        data={"target_lang": "hi"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FORMAT"


def test_upload_rejects_fake_video(client):
    response = client.post(
        "/api/upload",
        files={"file": ("fake.mp4", io.BytesIO(b"not really a video" * 100), "video/mp4")},
        data={"target_lang": "hi"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CORRUPT_MEDIA"


def test_upload_rejects_unsupported_target(client, test_clip):
    response = client.post(
        "/api/upload",
        files={"file": ("movie.mp4", io.BytesIO(test_clip.read_bytes()), "video/mp4")},
        data={"target_lang": "klingon"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_LANGUAGE"


def test_full_api_flow_upload_status_render_download_delete(client, test_clip, source_srt, hindi_srt):
    response = client.post(
        "/api/upload",
        files={
            "file": ("sample_movie.mp4", io.BytesIO(test_clip.read_bytes()), "video/mp4"),
            "subtitle": ("source.srt", io.BytesIO(source_srt.read_bytes()), "text/plain"),
            "translated_subtitle": ("translated.hi.srt", io.BytesIO(hindi_srt.read_bytes()), "text/plain"),
        },
        data={
            "target_lang": "hi",
            "source_lang": "en",
            "input_mode": "subtitles",
            "autostart": "true",
            "stop_after": "",
            "options": '{"separate": "center-suppression"}',
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    job_id = body["job"]["id"]
    assert body["validation"]["duration"] > 5
    assert body["validation"]["video"]["codec"] == "h264"

    job = _wait(client, job_id, timeout=240)
    assert job["status"] == "completed", job.get("error")
    assert job["verification"]["video_identical"] is True
    assert job["artifacts"]["render"]["has_dubbed"] is True

    segments = client.get(f"/api/jobs/{job_id}/segments").json()
    assert len(segments["segments"]) == 4
    assert segments["segments"][0]["translated_text"].startswith("तुम") or segments["segments"][0]["translated_text"]

    # studio edit
    patched = client.patch(
        f"/api/jobs/{job_id}/segments/0", json={"translated_text": "तुम कहाँ जा रहे हो आज रात?"}
    )
    assert patched.status_code == 200
    assert patched.json()["segment"]["translated_text"] == "तुम कहाँ जा रहे हो आज रात?"

    # range request works (video seeking)
    ranged = client.get(f"/api/media/{job_id}?track=dubbed", headers={"Range": "bytes=0-1023"})
    assert ranged.status_code == 206
    assert ranged.headers["content-range"].startswith("bytes 0-1023/")
    assert len(ranged.content) == 1024

    # original-audio variant for the player's track switch
    original = client.get(f"/api/media/{job_id}?track=original", headers={"Range": "bytes=0-99"})
    assert original.status_code == 206

    download = client.get(f"/api/download/{job_id}?kind=dubbed")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]

    subs = client.get(f"/api/jobs/{job_id}/subtitles/translated.vtt")
    assert subs.status_code == 200 and subs.text.startswith("WEBVTT")

    deleted = client.delete(f"/api/jobs/{job_id}")
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    assert client.get(f"/api/status/{job_id}").status_code == 404


def test_status_of_unknown_job_is_404(client):
    assert client.get("/api/status/deadbeefdeadbeefdeadbeefdeadbeef").status_code == 404
    assert client.get("/api/status/not-a-valid-id").status_code == 404
    assert client.delete("/api/jobs/deadbeefdeadbeefdeadbeefdeadbeef").status_code == 404


def test_stop_after_transcribe_pauses_for_review(client, test_clip, source_srt, hindi_srt):
    response = client.post(
        "/api/upload",
        files={
            "file": ("review.mp4", io.BytesIO(test_clip.read_bytes()), "video/mp4"),
            "subtitle": ("source.srt", io.BytesIO(source_srt.read_bytes()), "text/plain"),
            "translated_subtitle": ("translated.hi.srt", io.BytesIO(hindi_srt.read_bytes()), "text/plain"),
        },
        data={"target_lang": "hi", "input_mode": "subtitles", "stop_after": "translate"},
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]
    job = _wait(client, job_id, timeout=180)
    assert job["status"] == "awaiting_input"
    segments = client.get(f"/api/jobs/{job_id}/segments").json()["segments"]
    assert len(segments) == 4
    assert all(s["translated_text"] for s in segments)
    client.delete(f"/api/jobs/{job_id}")


def test_manual_dialogue_entry_renders_without_any_ai_model(client, test_clip):
    """The fully-free path: no ASR model, no translation model, typed dialogue."""
    response = client.post(
        "/api/upload",
        files={"file": ("manual.mp4", io.BytesIO(test_clip.read_bytes()), "video/mp4")},
        data={"target_lang": "hi", "input_mode": "manual"},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]["id"]
    job = client.get(f"/api/status/{job_id}").json()
    assert job["status"] == "awaiting_input", job["status"]
    assert not job.get("error")

    put = client.put(
        f"/api/jobs/{job_id}/segments",
        json={
            "segments": [
                {"start": 0.5, "end": 2.0, "text": "Where are you going?", "translated_text": "तुम कहाँ जा रहे हो?", "speaker": "SPEAKER_01"},
                {"start": 2.5, "end": 4.0, "text": "To the market.", "translated_text": "बाज़ार जा रहा हूँ।", "speaker": "SPEAKER_02"},
            ]
        },
    )
    assert put.status_code == 200
    assert len(put.json()["segments"]) == 2

    voices = client.get("/api/voices?lang=hi").json()
    if voices["engines"]:
        first = voices["catalog"]["hi"][0]["id"]
        second = voices["catalog"]["hi"][1]["id"]
        assigned = client.post(
            f"/api/jobs/{job_id}/voices",
            json=[
                {"speaker": "SPEAKER_01", "voice": first, "gender": "male"},
                {"speaker": "SPEAKER_02", "voice": second, "gender": "female"},
            ],
        )
        assert assigned.status_code == 200
        assert len(assigned.json()["speakers"]) == 2
        preview = client.post("/api/voice-preview", json={"text": "नमस्ते", "lang": "hi", "voice": first})
        assert preview.status_code == 200
        assert preview.headers["content-type"].startswith("audio/")

        queued = client.post("/api/generate-voice", json={"job_id": job_id, "force": True})
        assert queued.status_code == 200
        job = _wait(client, job_id, timeout=180, terminal=("failed", "awaiting_input"))
        assert job["status"] == "awaiting_input", job.get("error")
        # the voice stage alone pauses the job; now render for real
        client.post("/api/render", json={"job_id": job_id, "force": True})
        job = _wait(client, job_id, timeout=240)
        assert job["status"] == "completed", job.get("error")
        assert job["verification"]["video_identical"] is True
        speakers = {s["id"]: s["voice"] for s in job["speakers"]}
        assert speakers.get("SPEAKER_01") and speakers.get("SPEAKER_02")
        assert speakers["SPEAKER_01"] != speakers["SPEAKER_02"], "two speakers must not share one voice"
    client.delete(f"/api/jobs/{job_id}")
