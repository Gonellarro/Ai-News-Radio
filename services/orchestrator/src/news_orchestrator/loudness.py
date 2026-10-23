"""Measure and normalize narration before adding music or presentation silence."""

import json
import math
from pathlib import Path
import re
import time

from news_orchestrator import config, media


def profile(settings):
    if not settings["voice_normalization_enabled"]:
        return None
    return {"method": "loudnorm-two-pass-v1",
            "integrated_lufs": float(settings["voice_loudness_lufs"]),
            "true_peak_dbtp": float(settings["voice_true_peak_dbtp"]),
            "range_lu": float(settings["voice_loudness_range_lu"])}


def statistics(path):
    matches = re.findall(r'\{\s*"input_i"\s*:[^{}]*\}', Path(path).read_text(errors="replace"))
    if not matches:
        raise RuntimeError("FFmpeg no devolvió la medición de volumen de la locución.")
    value = json.loads(matches[-1])
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset",
                "output_i", "output_tp", "output_lra", "output_thresh"):
        if not math.isfinite(float(value[key])):
            raise RuntimeError("No se puede normalizar una locución silenciosa o con volumen no medible.")
    return value


def normalize(source, target, wanted, stop):
    """Use one measurement pass and a measured gain/limiting pass, without AI.

    Measure in the final stereo layout so mono TTS and stereo playback share
    the same loudness target. FFmpeg can fall back to dynamic normalization
    when a uniform gain cannot satisfy the range and true-peak limits.
    """
    source, target = Path(source), Path(target)
    started = time.monotonic()
    common = ["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info", "-y",
              "-threads", "1", "-filter_threads", "1", "-i", str(source), "-map", "0:a:0", "-vn"]
    audio_format = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    loudnorm = (f"loudnorm=I={wanted['integrated_lufs']}:TP={wanted['true_peak_dbtp']}:"
                f"LRA={wanted['range_lu']}:print_format=json")
    measurement_log = target.parent / "loudness-measure.log"
    media.run(common + ["-af", f"{audio_format},{loudnorm}", "-f", "null", "-"], measurement_log, stop)
    measured = statistics(measurement_log)
    fields = {"measured_I": "input_i", "measured_TP": "input_tp", "measured_LRA": "input_lra",
              "measured_thresh": "input_thresh", "offset": "target_offset"}
    options = ":".join(f"{option}={float(measured[key])}" for option, key in fields.items())
    output_log = target.parent / "loudness-render.log"
    media.run(common + ["-af", f"{audio_format},{loudnorm}:{options}:linear=true",
                        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(target)], output_log, stop)
    output = statistics(output_log)
    report = {"target": wanted, "elapsed_seconds": round(time.monotonic() - started, 3),
              "input_lufs": float(measured["input_i"]), "input_true_peak_dbtp": float(measured["input_tp"]),
              "output_lufs": float(output["output_i"]), "output_true_peak_dbtp": float(output["output_tp"]),
              "mode": output["normalization_type"]}
    config.atomic_json(target.parent / "loudness.json", report)
    return report
