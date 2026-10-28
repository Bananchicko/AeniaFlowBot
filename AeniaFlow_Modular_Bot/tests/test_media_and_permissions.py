from __future__ import annotations
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiogram.types import Message
from aeniaflow.handlers.commands import media_tools
from aeniaflow.core.helpers import download_file
from aeniaflow.handlers.system.business import business_message_update
from aeniaflow.core.ai_service import text, actor_id, AIUnavailable
from aeniaflow.core import ai_service


def msg():
    return SimpleNamespace(
        reply_to_message=None,
        answer_audio=AsyncMock(),
        answer_video=AsyncMock(),
        answer_voice=AsyncMock(),
        answer_video_note=AsyncMock(),
        answer_animation=AsyncMock(),
    )


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
@pytest.mark.parametrize("mode,rate", [("speed", 1.5), ("voice", 1.2)])
async def test_audio_conversion_real_ffmpeg(tmp_path, monkeypatch, mode, rate):
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as out:
        out.setparams((1, 2, 22050, 22050, "NONE", "not compressed"))
        out.writeframes(
            b"".join(
                struct.pack("<h", int(10000 * math.sin(i * 440 * 2 * math.pi / 22050))) for i in range(22050)
            )
        )
    monkeypatch.setattr(media_tools, "download_file", AsyncMock(return_value=str(source)))
    message = msg()
    message.reply_to_message = SimpleNamespace(
        voice=None, audio=SimpleNamespace(file_id="audio"), video=None, animation=None
    )
    sizes = []

    async def capture(file, **kwargs):
        sizes.append(Path(file.path).stat().st_size)

    message.answer_audio.side_effect = capture
    message.answer_voice.side_effect = capture
    await media_tools.convert(message, AsyncMock(), mode, rate)
    assert sizes and sizes[0] > 100
    assert not source.exists()
    assert not list(tmp_path.glob("*.out.*"))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
async def test_silent_video_speed_works_without_audio_stream(tmp_path, monkeypatch):
    source = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=1",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=20,
    )
    monkeypatch.setattr(media_tools, "download_file", AsyncMock(return_value=str(source)))
    message = msg()
    message.reply_to_message = SimpleNamespace(
        voice=None, audio=None, video=SimpleNamespace(file_id="video"), animation=None
    )
    await media_tools.convert(message, AsyncMock(), "speed", 1.5)
    message.answer_video.assert_awaited_once()
    assert not list(tmp_path.glob("*.mp4*"))


async def test_download_enforces_limit_before_transfer():
    bot = AsyncMock()
    bot.get_file.return_value = SimpleNamespace(file_path="file", file_size=21 * 1024 * 1024)
    with pytest.raises(ValueError):
        await download_file(bot, "huge")
    bot.download_file.assert_not_awaited()


async def test_download_failure_removes_temporary_file(monkeypatch, tmp_path):
    import aeniaflow.core.helpers as helpers

    actual = helpers.tempfile.NamedTemporaryFile
    monkeypatch.setattr(
        helpers.tempfile, "NamedTemporaryFile", lambda **kwargs: actual(dir=tmp_path, **kwargs)
    )
    bot = AsyncMock()
    bot.get_file.return_value = SimpleNamespace(file_path="file", file_size=1)
    bot.download_file.side_effect = RuntimeError("connection lost")
    with pytest.raises(RuntimeError):
        await download_file(bot, "file")
    assert list(tmp_path.glob("*.bin")) == []


async def test_business_autoreply_durable_cooldown_and_literal_text(repository):
    repository.save_connection("business", 42, True, True)
    repository.save_autoreply(42, enabled=True, reply_text="<b>Literal</b> & text")
    message = Message.model_validate(
        {
            "message_id": 1,
            "date": 1000,
            "chat": {"id": 99, "type": "private"},
            "from": {"id": 99, "is_bot": False, "first_name": "Customer"},
            "business_connection_id": "business",
            "text": "hello",
        }
    )
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status="member")
    await business_message_update(message, bot)
    await business_message_update(message, bot)
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["parse_mode"] is None
    assert repository.last_reply("business", 99) > 0


async def test_ai_quota_applies_before_network_and_errors_restore_quota(repository, monkeypatch):
    from openai import APIConnectionError

    monkeypatch.setattr(
        ai_service,
        "settings",
        SimpleNamespace(openai_api_key="placeholder", openai_model="test", ai_daily_limit=1),
    )
    api = AsyncMock()
    api.responses.create.return_value = SimpleNamespace(output_text="Answer")
    manager = AsyncMock()
    manager.__aenter__.return_value = api
    monkeypatch.setattr(ai_service, "AsyncOpenAI", lambda **kwargs: manager)
    token = actor_id.set(42)
    try:
        assert await text("question", "instruction") == "Answer"
        with pytest.raises(AIUnavailable):
            await text("again", "instruction")
        api.responses.create.assert_awaited_once()
    finally:
        actor_id.reset(token)
    token = actor_id.set(43)
    api.responses.create.side_effect = APIConnectionError(request=SimpleNamespace())
    try:
        with pytest.raises(AIUnavailable):
            await text("fail", "instruction")
        assert repository.conn.execute("SELECT count FROM usage WHERE user_id=43").fetchone()[0] == 0
    finally:
        actor_id.reset(token)
