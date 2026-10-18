"""Normalize and present narration, publishing assets without cutting a clip."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from news_orchestrator import config, intros, loudness, media


def profile(settings, intro=None, visual=None):
    value = {"version": 1, "intro_seconds": float(settings["audio_intro_seconds"]),
             "outro_seconds": float(settings["audio_outro_seconds"])}
    if intro:
        value.update({"version": 2, "intro_music": intro})
    normalization = loudness.profile(settings)
    if normalization:
        value.update({"version": 3, "voice_normalization": normalization})
    if visual:
        value.update({"version": 4, "visual": visual})
    value["id"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]
    return value


def current(directory, settings, intro=None, visual=None):
    directory = Path(directory)
    try:
        saved = json.loads((directory / "presentation.json").read_text())
        return (saved == profile(settings, intro, visual) and all((directory / name).is_file()
                for name in ("audio.mp3", "video.mp4", "clip.m3u8", "segment-profile-v2"))
                and (not saved.get("voice_normalization") or (directory / "loudness.json").is_file())
                and (not visual or all((directory / name).is_file() for name in ("poster.png", "visual.json"))))
    except (OSError, ValueError):
        return False


def prepare(directory, article, title, channel, settings, stop, download_source, intro=None, visual=None):
    """Always start from the original Qwen WAV, never a processed MP3/video.

    Existing segment names remain intact. The broadcaster can finish its saved
    list; its next read of clip.m3u8 sees the fully prepared replacement version.
    """
    directory = Path(directory)
    wanted = profile(settings, intro, visual)
    if current(directory, settings, intro, visual):
        return media.probe(directory / "video.mp4"), wanted
    directory.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".presentation-", dir=directory))
    try:
        try:
            previous = json.loads((directory / "presentation.json").read_text())
        except (OSError, ValueError):
            previous = {}
        audio_identity = lambda value: {k: v for k, v in value.items() if k not in {"version", "id", "visual"}}
        visual_only = (previous and audio_identity(previous) == audio_identity(wanted)
                       and all((directory / name).is_file() for name in ("audio.mp3", "video.mp4"))
                       and (not wanted.get("voice_normalization") or (directory / "loudness.json").is_file()))
        if visual_only:
            # Changing a card must not synthesize, normalize, or re-encode voice.
            os.link(directory / "audio.mp3", stage / "audio.mp3")
            if wanted.get("voice_normalization"):
                os.link(directory / "loudness.json", stage / "loudness.json")
            info = media.render(stage, article, title, channel, stop, visual=visual,
                                audio_path=directory / "video.mp4", copy_audio=True)
        else:
            info = prepare_audio(stage, directory, article, title, channel, wanted, intro, visual, stop, download_source)
        prefix = f"clip-{stage.name.removeprefix('.presentation-')}-"
        items = media.segments(stage, prefix=prefix)
        if stop.is_set():
            raise InterruptedError()
        # Unique names per build prevent replacing segment files that the live
        # broadcaster still has to publish from the previous version.
        for item in items:
            os.link(item["path"], directory / item["path"].name)
        names = ["audio.mp3", "video.mp4", "segment-profile-v2"]
        if visual:
            names += ["poster.png", "visual.json"]
        for name in names:
            (stage / name).replace(directory / name)
        (stage / "clip.m3u8").replace(directory / "clip.m3u8")
        if wanted.get("voice_normalization"):
            (stage / "loudness.json").replace(directory / "loudness.json")
        else:
            (directory / "loudness.json").unlink(missing_ok=True)
        config.atomic_json(directory / "presentation.json", wanted)
        return info, wanted
    except Exception:
        logs = [p.name + "\n" + p.read_text(errors="replace")[-1500:] for p in stage.glob("*.log")]
        if logs:
            (directory / "presentation-error.log").write_text("\n".join(logs))
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def prepare_audio(stage, directory, article, title, channel, wanted, intro, visual, stop, download_source):
    download_source(stage / "source.wav")
    if stop.is_set():
        raise InterruptedError()
    speech_path = stage / "source.wav"
    if wanted.get("voice_normalization"):
        speech_path = stage / "normalized.wav"
        loudness.normalize(stage / "source.wav", speech_path, wanted["voice_normalization"], stop)
    silence = f"adelay=delays={round(wanted['intro_seconds'] * 1000)}:all=1,apad=pad_dur={wanted['outro_seconds']}"
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-threads", "1",
               "-filter_threads", "1", "-filter_complex_threads", "1"]
    if intro:
        intro_path = directory / "intro.mp3"
        if not intro_path.is_file() or intros.digest(intro_path) != intro["sha256"]:
            raise RuntimeError("No se encuentra la copia de la intro elegida, o su contenido ha cambiado.")
        audio_format = "aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo"
        filters = (f"[0:a:0]{audio_format},asetpts=PTS-STARTPTS[music];"
                   f"[1:a:0]{audio_format},{silence},asetpts=PTS-STARTPTS[speech];"
                   "[music][speech]concat=n=2:v=0:a=1[complete]")
        command += ["-i", str(intro_path), "-i", str(speech_path),
                    "-filter_complex", filters, "-map", "[complete]"]
    else:
        command += ["-i", str(speech_path), "-af", silence]
    command += ["-c:a", "pcm_s16le", str(stage / "audio.wav")]
    media.run(command, stage / "padding.log", stop)
    media.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-threads", "1",
               "-i", str(stage / "audio.wav"), "-c:a", "libmp3lame", "-b:a", "128k", str(stage / "audio.mp3")],
              stage / "mp3.log", stop)
    return media.render(stage, article, title, channel, stop, visual=visual)
