"""Atomic progress shared by the coordinator and its serial model workers."""

import json
import time


class Progress:
    def __init__(self, directory, started=None, **context):
        self.directory = directory
        self.started = time.monotonic() if started is None else started
        self.context = context

    def __call__(self, phase, **extra):
        value = {"phase": phase, "elapsed_seconds": round(time.monotonic() - self.started, 1),
                 **self.context, **extra}
        temporary = self.directory / "progress.tmp"
        temporary.write_text(json.dumps(value, ensure_ascii=False))
        temporary.replace(self.directory / "progress.json")
        print(json.dumps(value, ensure_ascii=False), flush=True)
