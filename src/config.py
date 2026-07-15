"""Central configuration. All env-driven; see .env.example."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ASR model locations: explicit env var > InkVoice checkout on this machine >
# ./models (populated by scripts/fetch_models.py on a fresh machine).
_INKVOICE_ROOT = Path("V:/AI/Netriq InkVoice/spikes")
_LOCAL_MODELS = PROJECT_ROOT / "models"


def _model_dir(env_key: str, inkvoice_rel: str, local_rel: str) -> Path:
    if os.environ.get(env_key):
        return Path(os.environ[env_key])
    ink = _INKVOICE_ROOT / inkvoice_rel
    if ink.is_dir():
        return ink
    return _LOCAL_MODELS / local_rel


OFFLINE_MODEL_DIR = _model_dir(
    "REQPILOT_OFFLINE_MODEL_DIR",
    "m0_asr/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
    "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
)
STREAMING_MODEL_DIR = _model_dir(
    "REQPILOT_STREAMING_MODEL_DIR",
    "streaming_zipformer/sherpa-onnx-streaming-zipformer-en-2023-06-21",
    "sherpa-onnx-streaming-zipformer-en-2023-06-21",
)

SAMPLE_RATE = 16000

PROVIDER = os.environ.get("REQPILOT_PROVIDER", "groq")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")

HOST = os.environ.get("REQPILOT_HOST", "127.0.0.1")
PORT = int(os.environ.get("REQPILOT_PORT", "8765"))
DATA_DIR = Path(os.environ.get("REQPILOT_DATA_DIR", str(PROJECT_ROOT / "data")))

# Intelligence engine cadence (see ARCHITECTURE.md)
ENGINE_MIN_SECONDS_BETWEEN_PASSES = 15.0
ENGINE_TRIGGER_NEW_CONTENT_SECONDS = 25.0
ENGINE_TRIGGER_NEW_UTTERANCES = 6
