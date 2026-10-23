"""Optional cross-process inference slot shared with the local TTS project."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import time


@contextmanager
def inference_slot():
    filename = os.environ.get("AI_RUNTIME_LOCK")
    if not filename:
        yield
        return
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as lock:
        deadline = time.monotonic() + 1800
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Se agotó la espera del turno de IA local.")
                time.sleep(0.5)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
