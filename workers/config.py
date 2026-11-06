"""
Shared configuration loaded from .env
All workers import from here — single source of truth.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths & Automatic .venv Bootstrap ─────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent

# Ensure project root, .venv/bin, ./bin, and .venv site-packages are always active
# even if the user starts uvicorn/celery from another conda/venv environment.
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

for _sp in sorted((ROOT_DIR / ".venv" / "lib").glob("python*/site-packages")):
    if _sp.is_dir() and str(_sp) not in sys.path:
        sys.path.insert(1, str(_sp))

_extra_bins = [
    str(ROOT_DIR / ".venv" / "bin"),
    str(ROOT_DIR / "bin"),
    str(Path.home() / ".local" / "bin"),
]
_curr_path = os.environ.get("PATH", "")
for _b in reversed(_extra_bins):
    if Path(_b).is_dir() and _b not in _curr_path.split(os.pathsep):
        _curr_path = f"{_b}{os.pathsep}{_curr_path}" if _curr_path else _b
os.environ["PATH"] = _curr_path

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", ROOT_DIR / "output"))
FFMPEG_PATH = os.getenv("FFMPEG_PATH", str(ROOT_DIR / "bin" / "ffmpeg"))

# ── LLM ───────────────────────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
ENABLE_CRITIC_PASS = os.getenv("ENABLE_CRITIC_PASS", "false").lower() in ("1", "true", "yes")

# ── Whisper (GPU primary: cuda/float16, automatic fallback to cpu/int8) ──────
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "float16")
WHISPER_FALLBACK_DEVICE = "cpu"
WHISPER_FALLBACK_COMPUTE = "int8"

# ── Pipeline ──────────────────────────────────────────────────────────────────
CLIP_MIN_DURATION = int(os.getenv("CLIP_MIN_DURATION", "20"))
CLIP_MAX_DURATION = int(os.getenv("CLIP_MAX_DURATION", "90"))
TOP_N_CLIPS = int(os.getenv("TOP_N_CLIPS", "10"))
MAX_VIDEO_HOURS = float(os.getenv("MAX_VIDEO_HOURS", "3"))

# ── Target output format (GPU NVENC primary, CPU libx264 fallback) ────────────
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
OUTPUT_GPU_CODEC = os.getenv("OUTPUT_GPU_CODEC", "h264_nvenc")
OUTPUT_GPU_PRESET = os.getenv("OUTPUT_GPU_PRESET", "p4")
OUTPUT_CODEC = os.getenv("OUTPUT_CODEC", "libx264")
OUTPUT_PRESET = os.getenv("OUTPUT_PRESET", "fast")
OUTPUT_AUDIO_CODEC = "aac"
OUTPUT_AUDIO_BITRATE = "128k"

# ── Smart Reframing (Phase 2) ─────────────────────────────────────────────────
MODELS_DIR = ROOT_DIR / "models"
REFRAME_SAMPLE_FPS = float(os.getenv("REFRAME_SAMPLE_FPS", "2.0"))
REFRAME_MAX_PAN_SPEED = float(os.getenv("REFRAME_MAX_PAN_SPEED", "0.15"))  # max 15% width / sec
REFRAME_DEADBAND = float(os.getenv("REFRAME_DEADBAND", "0.04"))            # 4% width movement deadband
REFRAME_EMA_ALPHA = float(os.getenv("REFRAME_EMA_ALPHA", "0.20"))          # motion smoothing weight
REFRAME_DEFAULT_LAYOUT = os.getenv("REFRAME_DEFAULT_LAYOUT", "vertical")   # vertical, blur_bg, split_screen

