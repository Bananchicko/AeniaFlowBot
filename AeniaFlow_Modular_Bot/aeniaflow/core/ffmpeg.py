"""Resolve a ready executable, never mistake a source archive for an installation."""

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from config import BASE_DIR


def ffmpeg_binary():
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = BASE_DIR / path
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    for name in ("ffmpeg.exe", "ffmpeg") if os.name == "nt" else ("ffmpeg",):
        path = BASE_DIR / "bin" / name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError):
        return None


@lru_cache(maxsize=8)
def probe_ffmpeg(executable):
    if not executable:
        return {"ready": False, "detail": "FFmpeg не найден. Установите зависимости из requirements.txt."}
    try:
        version = subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=10)
        encoders = subprocess.run(
            [executable, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"ready": False, "detail": "Программа FFmpeg не запускается на этом сервере."}
    missing = [name for name in ("libx264", "libopus", "aac", "libmp3lame") if name not in encoders.stdout]
    ready = version.returncode == 0 and encoders.returncode == 0 and not missing
    return {
        "ready": ready,
        "detail": (
            (version.stdout.splitlines() or ["Неизвестная сборка"])[0][:200]
            if ready
            else "Не найдены кодеки: " + ", ".join(missing)
        ),
    }
