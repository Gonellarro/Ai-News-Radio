"""Download an immutable official checkpoint once, outside the image."""

import json
import os
from pathlib import Path


def main():
    from huggingface_hub import snapshot_download
    directory = Path(os.environ.get("QWEN_MODEL_DIR", "/models/qwen3-tts-0.6b-base"))
    model_id = os.environ.get("QWEN_MODEL_ID", "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    revision = os.environ.get("QWEN_MODEL_REVISION", "5d83992436eae1d760afd27aff78a71d676296fc")
    directory.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=model_id, revision=revision, local_dir=directory,
                      allow_patterns=["*.json", "*.txt", "*.safetensors"], max_workers=2)
    required = ["config.json", "model.safetensors", "speech_tokenizer/config.json", "speech_tokenizer/model.safetensors"]
    if any(not (directory / filename).is_file() for filename in required):
        raise RuntimeError("La descarga no contiene todos los archivos necesarios.")
    (directory / "ready.json").write_text(json.dumps({"model_id": model_id, "revision": revision,
                                                    "files": required}, indent=2))
    print(f"Modelo disponible en {directory}", flush=True)


if __name__ == "__main__":
    main()
