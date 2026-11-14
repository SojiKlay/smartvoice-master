"""Main STT orchestrator — ties audio loading, transcription, and diarization together."""

import os
import hashlib
import json
import math
import time
import uuid
from pathlib import Path

import requests

from smartvoice import processing_control
from smartvoice.config import WHISPER_BACKEND, WHISPER_MODEL, api_settings
from smartvoice.stt.audio import load_audio_16k, denoise
from smartvoice.stt.transcribe import is_standard_model, transcribe_fw, transcribe_hf, unload_model
from smartvoice.stt.diarize import diarize_words, _normalize_speaker_label

# ── Mock data for testing without GPU ─────────────────────────────────────

MOCK_DIARIZED = [
    [
        {"speaker": "Speaker 0", "text": "สวัสดีครับ นี่คือ Omazz ยินดีให้บริการครับ", "start": 0.5, "end": 3.2},
        {"speaker": "Speaker 1", "text": "สวัสดีค่ะ พอดีว่าที่นอนที่สั่งไปมีปัญหาค่ะ", "start": 3.8, "end": 7.1},
        {"speaker": "Speaker 0", "text": "ขอโทษด้วยนะครับ ขอทราบหมายเลขคำสั่งซื้อได้เลยครับ", "start": 7.5, "end": 11.0},
        {"speaker": "Speaker 1", "text": "หมายเลข OZ-12345 ค่ะ มันยุบตรงกลางเลยค่ะ", "start": 11.4, "end": 14.8},
    ],
    [
        {"speaker": "Speaker 0", "text": "สวัสดีครับ Omazz บริการครับ มีอะไรให้ช่วยไหมครับ", "start": 0.3, "end": 3.5},
        {"speaker": "Speaker 1", "text": "อยากสอบถามโปรโมชันที่นอนรุ่นใหม่ค่ะ มีส่วนลดไหม", "start": 4.0, "end": 7.2},
        {"speaker": "Speaker 0", "text": "มีครับ ตอนนี้ลด 20% สำหรับรุ่น Premium ครับ", "start": 7.6, "end": 10.5},
        {"speaker": "Speaker 1", "text": "โอเคขอบคุณค่ะ จะลองดูก่อนนะคะ", "start": 10.9, "end": 13.0},
    ],
]


def _use_mock() -> bool:
    return os.getenv("MOCK_STT", "false").lower() == "true"


def _mock_transcribe_diarized(file_path: str) -> list[dict]:
    filename = os.path.basename(file_path).lower()
    idx = sum(ord(c) for c in filename) % len(MOCK_DIARIZED)
    return MOCK_DIARIZED[idx]


def _select_backend() -> str:
    if WHISPER_BACKEND in ("transformers", "hf"):
        return "transformers"
    if WHISPER_BACKEND in ("faster-whisper", "faster_whisper", "fw"):
        return "faster-whisper"
    return "faster-whisper" if is_standard_model() else "transformers"


def _decoded_span_seconds(words: list[dict]) -> float:
    if not words:
        return 0.0
    starts = [float(word.get("start", 0.0) or 0.0) for word in words]
    ends = [float(word.get("end", word.get("start", 0.0)) or 0.0) for word in words]
    return max(ends) - min(starts)


def _transcript_quality_summary(words: list[dict], audio_duration_s: float) -> str:
    span_s = _decoded_span_seconds(words)
    words_per_sec = len(words) / max(audio_duration_s, 1.0)
    coverage = span_s / max(audio_duration_s, 1.0)
    return (
        f"words={len(words)}, decoded_span={span_s:.1f}s/{audio_duration_s:.1f}s, "
        f"coverage={coverage:.2f}, words_per_sec={words_per_sec:.2f}"
    )


def _looks_incomplete_transcript(words: list[dict], audio_duration_s: float) -> bool:
    if not words:
        return True
    if audio_duration_s <= 0:
        return False
    span_s = _decoded_span_seconds(words)
    if audio_duration_s >= 45 and span_s < max(20.0, audio_duration_s * 0.55):
        return True
    if audio_duration_s >= 120 and len(words) < max(120, int(audio_duration_s * 0.9)):
        return True
    return False


# ── Public API ────────────────────────────────────────────────────────────

def transcribe_diarized(file_path: str, step_callback=None) -> list[dict]:
    """Transcribe audio and diarize speakers using Whisper + Pyannote."""
    if _use_mock():
        return _mock_transcribe_diarized(file_path)
    settings = api_settings()
    if settings["stt_provider"] == "pyannote_api":
        return _api_transcribe_diarized(file_path, settings, step_callback)
    return _real_transcribe_diarized(file_path, step_callback=step_callback)


def _api_request(method: str, url: str, timeout: int, **kwargs):
    processing_control.check()
    try:
        result = getattr(requests, method)(url, timeout=(10, timeout), allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise RuntimeError("pyannoteAI connection failed or timed out; check job history before resubmitting") from None
    if not 200 <= result.status_code < 300:
        raise RuntimeError(f"pyannoteAI HTTP {result.status_code}; check key, credits and job status")
    return result


def _api_segments(output: dict) -> list[dict]:
    turns = output.get("turnLevelTranscription")
    if not isinstance(turns, list):
        raise RuntimeError("pyannoteAI response has no turnLevelTranscription")
    result = []
    for turn in turns:
        try:
            start, end = float(turn["start"]), float(turn["end"])
            text, speaker = turn["text"], turn["speaker"]
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
                raise ValueError("invalid timestamps")
            if not isinstance(text, str) or not isinstance(speaker, str) or not speaker:
                raise ValueError("invalid turn")
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("pyannoteAI returned an invalid transcript segment") from None
        if text.strip():
            result.append({"start": start, "end": end, "text": text.strip(), "speaker": _normalize_speaker_label(speaker)})
    if not result:
        raise RuntimeError("pyannoteAI returned no speech; verify the audio before retrying")
    return sorted(result, key=lambda item: item["start"])


def _save_api_state(path: Path, state: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _api_transcribe_diarized(file_path: str, settings: dict, step_callback=None) -> list[dict]:
    if not settings["pyannote_key"]:
        raise ValueError("Set PYANNOTE_API_KEY before using speech API")
    if settings["pyannote_model"] not in {"precision-2", "precision-3"}:
        raise ValueError("Combined transcription requires precision-2 or precision-3")
    if settings["stt_model"] != "faster-whisper-large-v3-turbo":
        raise ValueError("STT_API_MODEL must be faster-whisper-large-v3-turbo for this Thai Whisper backend")
    source = Path(file_path)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    signature = hashlib.sha256((digest.hexdigest() + settings["pyannote_model"] + settings["stt_model"] + settings["pyannote_key"]).encode()).hexdigest()
    cache = Path(str(source) + ".smartvoice-api.json")
    state = {}
    if cache.exists():
        try:
            state = json.loads(cache.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("invalid cache")
        except (ValueError, OSError):
            raise RuntimeError("Cannot read speech API checkpoint; inspect it before submitting another paid job") from None
    if state.get("signature") != signature:
        state = {"signature": signature}
    if "output" in state:
        return _api_segments(state["output"])
    headers = {"Authorization": f"Bearer {settings['pyannote_key']}"}
    base = "https://api.pyannote.ai/v1"
    timeout = settings["timeout"]
    if not state.get("job_id"):
        if state.get("submitting"):
            raise RuntimeError("Previous speech API submission has unknown status; inspect pyannoteAI job history before clearing the checkpoint")
        if step_callback:
            step_callback("กำลังส่งเสียงให้ Whisper และ Pyannote API")
        media = f"media://smartvoice/{uuid.uuid4().hex}"
        upload = _api_request("post", f"{base}/media/input", timeout, headers=headers, json={"url": media}).json()
        upload_url = upload.get("url", "")
        if not isinstance(upload_url, str) or not upload_url.startswith("https://"):
            raise RuntimeError("pyannoteAI returned an invalid upload URL")
        with source.open("rb") as stream:
            _api_request("put", upload_url, timeout, headers={"Content-Type": "application/octet-stream"}, data=stream)
        processing_control.check()
        state["submitting"] = True
        _save_api_state(cache, state)
        submitted = _api_request("post", f"{base}/diarize", timeout, headers=headers, json={
            "url": media,
            "model": settings["pyannote_model"],
            "transcription": True,
            "transcriptionConfig": {"model": settings["stt_model"]},
            "minSpeakers": 1,
            "maxSpeakers": 2,
        }).json()
        job_id = submitted.get("jobId")
        if not isinstance(job_id, str) or not job_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for c in job_id):
            raise RuntimeError("pyannoteAI did not return a valid jobId; inspect job history before retrying")
        state["job_id"] = job_id
        state.pop("submitting", None)
        _save_api_state(cache, state)
    if step_callback:
        step_callback("กำลังรอผลถอดเสียงและแยกผู้พูดจาก API")
    deadline = time.monotonic() + settings["job_timeout"]
    while time.monotonic() < deadline:
        processing_control.check()
        job = _api_request("get", f"{base}/jobs/{state['job_id']}", timeout, headers=headers).json()
        status = job.get("status")
        if status == "succeeded":
            output = job.get("output")
            if not isinstance(output, dict):
                raise RuntimeError("pyannoteAI returned an invalid job output")
            segments = _api_segments(output)
            state["output"] = output
            _save_api_state(cache, state)
            return segments
        if status in {"failed", "canceled"}:
            raise RuntimeError(f"pyannoteAI job {status}; inspect job history before clearing the checkpoint")
        if status not in {"pending", "created", "running"}:
            raise RuntimeError("pyannoteAI returned an unknown job status")
        for _ in range(5):
            processing_control.check()
            if time.monotonic() >= deadline:
                break
            time.sleep(1)
    raise RuntimeError("Speech API wait timed out; retry resumes the saved job without submitting again")


def _real_transcribe_diarized(file_path: str, step_callback=None) -> list[dict]:
    import datetime

    def _log(msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[STT] {ts} {msg}", flush=True)
        if step_callback:
            step_callback(msg)

    size_mb = os.path.getsize(file_path) / 1024 / 1024

    # 1. Load audio as numpy 16 kHz
    _log(f"→ โหลดเสียง {size_mb:.1f}MB → 16 kHz mono")
    audio, sr = load_audio_16k(file_path)
    audio_duration_s = len(audio) / float(sr) if sr else 0.0

    # 2. Noise reduction
    audio = denoise(audio, sr, _log)

    # 3. Transcribe — choose backend from config / model type
    backend = _select_backend()
    _log(f"→ ถอดเสียง ({WHISPER_MODEL}) ...")
    _log(f"→ ใช้ backend: {backend} (config={WHISPER_BACKEND})")
    if WHISPER_BACKEND == "auto":
        _log(f"→ เลือก backend อัตโนมัติ: {backend}")
        if backend == "transformers" and not is_standard_model():
            _log("→ auto quality mode: ใช้ transformers เพราะโมเดลนี้ไม่ใช่ native faster-whisper/CT2 model")

    if backend == "faster-whisper":
        try:
            all_words = transcribe_fw(audio, _log)
            if not all_words:
                raise RuntimeError("faster-whisper returned no words")
            _log(f"→ faster-whisper transcript stats: {_transcript_quality_summary(all_words, audio_duration_s)}")
            if _looks_incomplete_transcript(all_words, audio_duration_s):
                raise RuntimeError(
                    "faster-whisper transcript looks incomplete "
                    f"({_transcript_quality_summary(all_words, audio_duration_s)})"
                )
        except Exception as e:
            _log(f"⚠ faster-whisper คุณภาพไม่พอหรือใช้งานไม่ได้ ({e}) — fallback ไป transformers")
            unload_model()
            all_words = transcribe_hf(audio, sr, _log)
    else:
        try:
            all_words = transcribe_hf(audio, sr, _log)
            if not all_words:
                raise RuntimeError("transformers returned no words")
        except Exception as e:
            if WHISPER_BACKEND in ("transformers", "hf"):
                _log(f"✖ transformers ใช้งานไม่ได้ ({e})")
                unload_model()
                raise
            _log(f"⚠ transformers ใช้งานไม่ได้ ({e}) — fallback ไป faster-whisper")
            unload_model()
            all_words = transcribe_fw(audio, _log)

    if not all_words:
        return []

    # 3b. Free GPU — unload Whisper model before diarization
    _log("→ ปลด Whisper model ออกจาก GPU เพื่อเตรียม diarization...")
    unload_model()

    # 4. Diarize and group words by speaker
    return diarize_words(file_path, all_words, _log)
