import os
from pathlib import Path

DATA = Path(os.environ.get("QWENTTS_DATA_DIR", "/app/data"))
VOICES = Path(os.environ.get("QWENTTS_VOICES_DIR", "/voices"))
MODEL = Path(os.environ.get("QWEN_MODEL_DIR", "/models/qwen3-tts-0.6b-base"))
WEB = Path(os.environ.get("WEB_DIR", "/app/web"))
LOCK = Path(os.environ.get("AI_RUNTIME_LOCK", "/run/local-ai/inference.lock"))
LANGUAGES = ["Spanish", "English", "French", "German", "Italian", "Portuguese", "Chinese", "Japanese", "Korean", "Russian"]


def model_ready():
    return all((MODEL / file).is_file() for file in ["ready.json", "config.json", "model.safetensors",
                                                    "speech_tokenizer/model.safetensors"])
