"""Publish prepared HLS segments in real time, independently of AI production."""

from collections import deque
from datetime import datetime, timezone
import fcntl
import json
import logging
import os
import signal
import threading
import time

from news_orchestrator import config, lifetime, media
from news_orchestrator.store import Store, now


class Broadcast:
    def __init__(self):
        config.DATA.mkdir(parents=True, exist_ok=True)
        self.live = config.DATA / "hls"
        self.live.mkdir(exist_ok=True)
        self.instance = (config.DATA / "broadcast.lock").open("a+")
        fcntl.flock(self.instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.store = Store(config.DATA)
        self.stop = threading.Event()
        self.last_id = self.store.state("playing_id")
        self.next_tick = None
        try:
            state = json.loads((self.live / "state.json").read_text())
            self.entries = deque([entry for entry in state["entries"] if (self.live / entry["name"]).is_file()], maxlen=24)
            self.sequence = state["sequence"]
            self.discontinuity = state["discontinuity"]
        except (OSError, ValueError, KeyError):
            self.entries = deque(maxlen=24)
            self.sequence = int(time.time())
            self.discontinuity = 0

    def heartbeat(self, title, job_id, error=""):
        config.atomic_json(config.DATA / "broadcast.json", {"updated_at": now(), "title": title, "job_id": job_id,
                                                            "error": error, "output": "local", "sequence": self.sequence})

    def fallback(self, settings):
        directory = config.DATA / "continuity"
        media.render(directory, {"source_name": "Emisión local · preparación automática"},
                     "Preparando las próximas noticias", settings["channel_name"], self.stop, fallback=True)
        return media.segments(directory)

    def publish(self, segment, first):
        if first:
            self.discontinuity += 1
        name = f"segment-{self.sequence:012d}.ts"
        destination = self.live / name
        if destination.exists():
            destination.unlink()
        os.link(segment["path"], destination)
        self.entries.append({"sequence": self.sequence, "name": name, "duration": segment["duration"],
                             "discontinuity": self.discontinuity, "break": first, "date": now()})
        self.sequence += 1
        window = list(self.entries)[-12:]
        first_entry = window[0]
        baseline = first_entry["discontinuity"] - int(first_entry["break"])
        lines = ["#EXTM3U", "#EXT-X-VERSION:6", "#EXT-X-TARGETDURATION:8", "#EXT-X-INDEPENDENT-SEGMENTS",
                 f"#EXT-X-MEDIA-SEQUENCE:{first_entry['sequence']}", f"#EXT-X-DISCONTINUITY-SEQUENCE:{baseline}"]
        for entry in window:
            if entry["break"]:
                lines.append("#EXT-X-DISCONTINUITY")
            lines += ["#EXT-X-PROGRAM-DATE-TIME:" + entry["date"], f"#EXTINF:{entry['duration']:.6f},", entry["name"]]
        # Persist sequence allocation before exposing it in the live manifest.
        config.atomic_json(self.live / "state.json", {"sequence": self.sequence, "discontinuity": self.discontinuity,
                                                      "entries": list(self.entries)})
        temporary = self.live / "index.tmp"
        temporary.write_text("\n".join(lines) + "\n")
        temporary.replace(self.live / "index.m3u8")
        keep = {entry["name"] for entry in self.entries}
        for path in self.live.glob("segment-*.ts"):
            if path.name not in keep:
                path.unlink(missing_ok=True)

    def run(self):
        order = deque()
        last_order = None
        while not self.stop.is_set():
            try:
                with lifetime.locked():
                    settings = config.load()
                    playlist = self.store.playlist()
                    active = {job["id"]: job for job in playlist if (config.DATA / "media" / job["id"] / "video.mp4").is_file()}
                    desired = tuple(active)
                    if desired != last_order:
                        order = deque(desired)
                        if self.last_id in order:
                            order.rotate(-list(order).index(self.last_id)-1)
                        last_order = desired
                    with self.store.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        from news_orchestrator.playlist_control import state, put
                        next_id = state(db, "next_play_id")
                        if next_id:
                            put(db, "next_play_id", None)
                            if next_id in active:
                                order = deque(i for i in order if i != next_id)
                                order.appendleft(next_id)
                    if not order:
                        order.extend(active)
                    while order and order[0] not in active:
                        order.popleft()
                    if not order and active:
                        order.extend(active)
                    if order:
                        job_id = order.popleft()
                        job = active[job_id]
                        title = job["result"]["title"]
                        segments = media.segments(config.DATA / "media" / job_id)
                    else:
                        job_id = None
                        title = "Preparando las próximas noticias"
                        segments = self.fallback(settings)
                    # Claim before releasing the lifetime lock, so cleanup cannot
                    # remove a just-selected clip before its first segment.
                    self.store.set_state("playing_id", job_id)
                for index, segment in enumerate(segments):
                    if self.stop.is_set():
                        break
                    if self.next_tick is None or self.next_tick < time.monotonic() - 8:
                        self.next_tick = time.monotonic()
                    self.publish(segment, first=index == 0)
                    self.next_tick += segment["duration"]
                    while not self.stop.is_set() and time.monotonic() < self.next_tick:
                        self.heartbeat(title, job_id)
                        self.stop.wait(min(1, max(0, self.next_tick - time.monotonic())))
                self.last_id = job_id
            except InterruptedError:
                break
            except Exception as exc:
                logging.exception("Local broadcast failed")
                self.heartbeat("Recuperando la emisión local", None, str(exc)[:1500])
                self.stop.wait(2)


def main():
    logging.basicConfig(level=logging.INFO)
    broadcast = Broadcast()
    signal.signal(signal.SIGTERM, lambda *_: broadcast.stop.set())
    signal.signal(signal.SIGINT, lambda *_: broadcast.stop.set())
    broadcast.run()


if __name__ == "__main__":
    main()
