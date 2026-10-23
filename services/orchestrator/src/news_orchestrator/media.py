from datetime import datetime
import json
from pathlib import Path
import subprocess
import textwrap


FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
                             "-of", "json", str(path)], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError("No se pudo leer el vídeo terminado.")
    value = json.loads(result.stdout)
    if float(value.get("format", {}).get("duration", 0)) <= 0:
        raise RuntimeError("El vídeo no tiene duración válida.")
    return value


def card(directory, channel, title, source, published):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "channel.txt").write_text(channel[:90], encoding="utf-8")
    lines = textwrap.wrap(title, width=46, break_long_words=True) or [title]
    if len(lines) > 4:
        lines = lines[:4]
        lines[-1] = lines[-1][:42].rstrip() + "…"
    (directory / "title.txt").write_text("\n".join(lines), encoding="utf-8")
    date = datetime.fromisoformat(published).strftime("%d/%m/%Y · %H:%M UTC") if published else "EMISIÓN LOCAL"
    (directory / "source.txt").write_text(source[:100], encoding="utf-8")
    (directory / "date.txt").write_text(date, encoding="utf-8")
    def text(filename, size, color, x, y):
        return f"drawtext=fontfile={FONT}:textfile={directory / filename}:expansion=none:fontsize={size}:fontcolor={color}:x={x}:y={y}:line_spacing=14"
    return ",".join(["drawbox=x=0:y=0:w=1280:h=8:color=0x83dfc9:t=fill",
                     "drawbox=x=50:y=102:w=1180:h=2:color=0x35465c:t=fill",
                     text("channel.txt", 26, "0x83dfc9", 60, 49), text("title.txt", 43, "white", 60, 195),
                     text("source.txt", 23, "0xc1cddd", 60, 590), text("date.txt", 21, "0x91a6be", 60, 645)])


def run(command, log_path, stop):
    with Path(log_path).open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                if stop.wait(0.5):
                    raise InterruptedError("Preparación detenida al reiniciar.")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if process.returncode:
            raise RuntimeError("Falló FFmpeg: " + Path(log_path).read_text(errors="replace")[-1500:])


def render(directory, article, title, channel, stop, fallback=False, visual=None, audio_path=None, copy_audio=False):
    directory = Path(directory)
    target = directory / "video.mp4"
    if target.is_file():
        return probe(target)
    temporary = directory / "video.part.mp4"
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-filter_threads", "1",
               "-threads", "1"]
    if visual and not fallback:
        from news_orchestrator import cards
        poster = cards.render(directory, article, title, channel, visual)
        command += ["-loop", "1", "-framerate", "25", "-i", str(poster)]
        filters = None
    else:
        filters = card(directory, channel, title, article.get("source_name", "Preparando las próximas noticias"), article.get("published_at", ""))
        command += ["-f", "lavfi", "-i", "color=c=0x121c2c:s=1280x720:r=25"]
    if fallback:
        command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "12"]
    else:
        command += ["-i", str(audio_path or directory / "audio.wav"), "-shortest"]
    command += ["-map", "0:v:0", "-map", "1:a:0"]
    if filters:
        command += ["-vf", filters]
    command += ["-c:v", "libx264", "-preset", "veryfast",
                "-tune", "stillimage", "-threads", "1", "-crf", "24", "-pix_fmt", "yuv420p", "-r", "25", "-g", "50",
                "-keyint_min", "50", "-sc_threshold", "0"]
    if copy_audio:
        command += ["-c:a", "copy"]
    else:
        command += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
    command += ["-movflags", "+faststart", str(temporary)]
    run(command, directory / "render.log", stop)
    info = probe(temporary)
    codecs = {stream["codec_type"]: stream["codec_name"] for stream in info["streams"]}
    if codecs.get("video") != "h264" or codecs.get("audio") != "aac":
        raise RuntimeError("El vídeo no tiene el formato de la parrilla.")
    temporary.replace(target)
    return info


def segments(directory, prefix="clip-"):
    """Package the finished clip once. Broadcasting only publishes prepared segments."""
    directory = Path(directory)
    manifest = directory / "clip.m3u8"
    marker = directory / "segment-profile-v2"
    if not manifest.is_file() or not marker.is_file():
        result = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(directory / "video.mp4"),
                                 "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-f", "hls", "-hls_time", "4",
                                 "-hls_playlist_type", "vod", "-hls_flags", "independent_segments+temp_file",
                                 "-hls_segment_options", "mpegts_flags=+initial_discontinuity+resend_headers",
                                 "-hls_segment_filename", str(directory / f"{prefix}%05d.ts"), str(manifest)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            manifest.unlink(missing_ok=True)
            raise RuntimeError("No se pudo preparar la emisión: " + result.stderr[-1500:])
        marker.write_text("mpegts initial discontinuity\n")
    items, duration = [], None
    for line in manifest.read_text().splitlines():
        if line.startswith("#EXTINF:"):
            duration = float(line.split(":", 1)[1].rstrip(","))
        elif line and not line.startswith("#"):
            if Path(line).name != line or not line.startswith("clip-") or not line.endswith(".ts"):
                raise RuntimeError("Nombre de segmento no válido.")
            if duration is None or not 0 < duration <= 8 or not (directory / line).is_file():
                raise RuntimeError("Segmento incompleto o duración no válida.")
            items.append({"path": directory / line, "duration": duration})
            duration = None
    if not items:
        raise RuntimeError("El vídeo no contiene segmentos para emitir.")
    return items
