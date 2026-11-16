import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from streamlit.testing.v1 import AppTest

from smartvoice import audit, auth, config, db, env_settings, file_manager, ollama_client, preflight, processing_control
from smartvoice.stt import orchestrator


def response(data, status=200):
    result = Mock(status_code=status)
    result.json.return_value = data
    return result


@pytest.fixture
def api_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "typhoon")
    monkeypatch.setenv("STT_PROVIDER", "pyannote_api")
    monkeypatch.setenv("TYPHOON_API_KEY", "test-typhoon")
    monkeypatch.setenv("PYANNOTE_API_KEY", "test-pyannote")
    monkeypatch.setenv("MOCK_STT", "false")


def test_typhoon_uses_chat_completions_and_configurable_model(api_env, monkeypatch):
    monkeypatch.setenv("TYPHOON_MODEL", "typhoon-v2.1-12b-instruct")
    post = Mock(return_value=response({"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]}))
    monkeypatch.setattr(requests, "post", post)
    assert json.loads(ollama_client.chat("system", "user", json_mode=True)) == {"ok": True}
    args, kwargs = post.call_args
    assert args[0] == "https://api.opentyphoon.ai/v1/chat/completions"
    assert kwargs["json"]["model"] == "typhoon-v2.1-12b-instruct"
    assert "options" not in kwargs["json"]
    assert kwargs["headers"]["Authorization"] == "Bearer test-typhoon"


def test_missing_key_fails_before_network(api_env, monkeypatch):
    monkeypatch.delenv("TYPHOON_API_KEY")
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(ValueError, match="TYPHOON_API_KEY"):
        ollama_client.chat("system", "user")
    post.assert_not_called()


def test_truncated_llm_output_is_not_accepted(api_env, monkeypatch):
    monkeypatch.setattr(requests, "post", Mock(return_value=response({"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]})))
    with pytest.raises(RuntimeError, match="truncated"):
        ollama_client.chat("system", "user")


def test_api_stt_upload_poll_and_cache(api_env, monkeypatch, tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"RIFF-test")
    turns = [{"speaker": "SPEAKER_00", "text": "สวัสดีค่ะ", "start": 0.0, "end": 1.0}]
    post = Mock(side_effect=[response({"url": "https://storage.example/upload"}), response({"jobId": "job-1"})])
    put = Mock(return_value=response({}))
    get = Mock(return_value=response({"status": "succeeded", "output": {"turnLevelTranscription": turns}}))
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "put", put)
    monkeypatch.setattr(requests, "get", get)
    assert not hasattr(orchestrator, "_real_transcribe_diarized")
    result = orchestrator.transcribe_diarized(str(audio))
    assert result == [{"speaker": "Speaker 0", "text": "สวัสดีค่ะ", "start": 0.0, "end": 1.0}]
    assert post.call_args.kwargs["json"]["transcriptionConfig"]["model"] == "faster-whisper-large-v3-turbo"
    assert "Authorization" not in put.call_args.kwargs["headers"]
    assert orchestrator.transcribe_diarized(str(audio)) == result
    assert post.call_count == 2
    assert get.call_count == 1


def test_api_stt_failure_is_not_empty_success(api_env, monkeypatch, tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"test")
    monkeypatch.setattr(requests, "post", Mock(side_effect=[response({"url": "https://storage.example/upload"}), response({"jobId": "job-2"})]))
    monkeypatch.setattr(requests, "put", Mock(return_value=response({})))
    monkeypatch.setattr(requests, "get", Mock(return_value=response({"status": "failed", "output": {"error": "private transcript"}})))
    with pytest.raises(RuntimeError, match="failed") as error:
        orchestrator.transcribe_diarized(str(audio))
    assert "private transcript" not in str(error.value)


def test_readiness_in_api_mode_does_not_require_ollama(api_env, monkeypatch):
    monkeypatch.setattr(preflight, "MOCK_STT", False)
    monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("readiness must not call network")))
    assert preflight.get_llm_readiness()[0]
    assert preflight.get_pyannote_access_readiness()[0]


def test_invalid_provider_rejected(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "typo")
    with pytest.raises(ValueError, match="STT_PROVIDER"):
        config.api_settings()


def test_api_errors_do_not_become_neutral_sentiment(api_env, monkeypatch):
    monkeypatch.setattr(requests, "post", Mock(return_value=response({}, status=429)))
    with pytest.raises(ollama_client.APIError, match="429"):
        ollama_client.analyze_sentiment("Customer: ไม่พอใจค่ะ")


def test_invalid_json_does_not_become_successful_analysis(api_env, monkeypatch):
    monkeypatch.setattr(requests, "post", Mock(return_value=response({"choices": [{"message": {"content": "not JSON"}, "finish_reason": "stop"}]})))
    with pytest.raises(ollama_client.APIError):
        ollama_client.analyze_sentiment("Customer: สวัสดีค่ะ")


def test_api_keys_are_redacted():
    assert audit.redact({"TYPHOON_API_KEY": "secret", "PYANNOTE_API_KEY": "secret"}) == {
        "TYPHOON_API_KEY": "***", "PYANNOTE_API_KEY": "***",
    }


def test_audio_removal_also_removes_api_checkpoint(tmp_path):
    audio = tmp_path / "call.wav"
    cache = tmp_path / "call.wav.smartvoice-api.json"
    audio.write_bytes(b"audio")
    cache.write_text("{}")
    assert file_manager.remove_audio_file(str(audio))
    assert not audio.exists() and not cache.exists()


def test_poll_network_failure_resumes_saved_job(api_env, monkeypatch, tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"test")
    post = Mock(side_effect=[response({"url": "https://storage.example/upload"}), response({"jobId": "resume-1"})])
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "put", Mock(return_value=response({})))
    monkeypatch.setattr(requests, "get", Mock(side_effect=requests.Timeout("signed-secret-url")))
    with pytest.raises(RuntimeError, match="timed out") as error:
        orchestrator.transcribe_diarized(str(audio))
    assert "signed-secret-url" not in str(error.value)
    monkeypatch.setattr(requests, "get", Mock(return_value=response({"status": "succeeded", "output": {
        "turnLevelTranscription": [{"speaker": "SPEAKER_01", "text": "ที่นอนค่ะ", "start": 1, "end": 2}],
    }})))
    assert orchestrator.transcribe_diarized(str(audio))[0]["speaker"] == "Speaker 1"
    assert post.call_count == 2


def test_uncertain_submission_is_not_automatically_repeated(api_env, monkeypatch, tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"test")
    post = Mock(side_effect=[response({"url": "https://storage.example/upload"}), requests.Timeout()])
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "put", Mock(return_value=response({})))
    with pytest.raises(RuntimeError):
        orchestrator.transcribe_diarized(str(audio))
    with pytest.raises(RuntimeError, match="unknown status"):
        orchestrator.transcribe_diarized(str(audio))
    assert post.call_count == 2


@pytest.mark.parametrize("turn", [
    {"start": 2, "end": 1, "text": "คำ", "speaker": "SPEAKER_00"},
    {"start": float("nan"), "end": 1, "text": "คำ", "speaker": "SPEAKER_00"},
    {"start": 0, "end": 1, "text": "คำ", "speaker": None},
])
def test_api_invalid_timestamps_and_speakers_rejected(turn):
    with pytest.raises(RuntimeError, match="invalid transcript"):
        orchestrator._api_segments({"turnLevelTranscription": [turn]})


def test_cancellation_prevents_audio_upload(api_env, monkeypatch, tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"test")
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(processing_control, "check", Mock(side_effect=processing_control.ProcessingCancelled()))
    with pytest.raises(processing_control.ProcessingCancelled):
        orchestrator.transcribe_diarized(str(audio))
    post.assert_not_called()


@pytest.mark.parametrize("legacy", [False, True])
def test_settings_saves_api_choices_without_exposing_keys(api_env, monkeypatch, tmp_path, legacy):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    values = {"STT_PROVIDER": "pyannote_api", "LLM_PROVIDER": "typhoon", "TYPHOON_MODEL": "typhoon-v2.1-12b-instruct"}
    if legacy:
        values.update(STT_PROVIDER="local", LLM_PROVIDER="ollama")
        monkeypatch.setenv("STT_PROVIDER", "local")
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(env_settings, "read_env", lambda: values)
    save = Mock()
    monkeypatch.setattr(env_settings, "write_env", save)
    monkeypatch.setattr(preflight, "run_preflight_checks", lambda: [])
    app = AppTest.from_file(str(Path("pages/4_Settings.py").resolve()))
    user_id, error = auth.create_user("tester", "synthetic-password", "Admin", "Tester")
    assert user_id is not None and error is None
    app.session_state["current_user"] = "Tester"
    app.session_state["current_user_role"] = "Admin"
    app.session_state["current_username"] = "tester"
    app.session_state["current_user_id"] = user_id
    app.session_state["current_user_source"] = "db"
    app.run(timeout=20)
    assert not app.exception
    app.text_input(key="_api_secret_TYPHOON_API_KEY").set_value("new-secret")
    next(button for button in app.button if button.label == "บันทึกการตั้งค่า").click()
    app.run(timeout=20)
    assert not app.exception
    saved = save.call_args.args[0]
    assert saved["TYPHOON_API_KEY"] == "new-secret"
    assert saved["TYPHOON_MODEL"] == "typhoon-v2.1-12b-instruct"
    assert saved["STT_PROVIDER"] == "pyannote_api"
    assert saved["LLM_PROVIDER"] == "typhoon"
    assert not any(key.startswith(("WHISPER_", "OLLAMA_")) or key == "HF_TOKEN" for key in saved)
    assert not any(widget.label in {"Whisper model", "Backend", "Device", "Compute", "Ollama model", "HuggingFace token"} for kind in (app.selectbox, app.text_input) for widget in kind)
    assert "new-secret" not in " ".join(item.value for item in app.caption)
    assert not any("ไม่พบ GPU" in item.value for item in app.warning)


def test_unsupported_speech_model_rejected_before_upload(api_env, monkeypatch, tmp_path):
    monkeypatch.setenv("PYANNOTE_API_MODEL", "community-1")
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(ValueError, match="precision-2"):
        orchestrator.transcribe_diarized(str(tmp_path / "unused.wav"))
    post.assert_not_called()


def test_missing_speech_key_prevents_upload(api_env, monkeypatch, tmp_path):
    monkeypatch.delenv("PYANNOTE_API_KEY")
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(ValueError, match="PYANNOTE_API_KEY"):
        orchestrator.transcribe_diarized(str(tmp_path / "unused.wav"))
    post.assert_not_called()
