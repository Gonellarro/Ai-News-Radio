"""One background collector, independent from the optional search service."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

from news_radio.catalog import load_sources, source_is_ready
from news_radio.connectors import fetch_source
from news_radio.feeds import parse_date
from news_radio.library import NewsLibrary


class NewsCollector:
    def __init__(self, library: NewsLibrary):
        self.library = library
        self.interval = max(60, int(os.environ.get("NEWS_RADIO_REFRESH_SECONDS", "1800")))
        self.reddit_interval = max(self.interval, int(os.environ.get("NEWS_RADIO_REDDIT_INTERVAL_SECONDS", "7200")))
        self.reddit_gap = max(60, int(os.environ.get("NEWS_RADIO_REDDIT_REQUEST_GAP_SECONDS", "1800")))
        self.reddit_cooldown = max(self.reddit_gap, int(os.environ.get("NEWS_RADIO_REDDIT_COOLDOWN_SECONDS", "21600")))
        self.requested = threading.Event()
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.last_error = ""

    @property
    def refreshing(self):
        return self.requested.is_set() or self.lock.locked()

    def request_refresh(self):
        self.requested.set()

    def start(self):
        self.request_refresh()
        threading.Thread(target=self._run, name="source-collector", daemon=True).start()

    def stop(self):
        self.stopping.set()
        self.requested.set()

    def _run(self):
        while not self.stopping.is_set():
            self.requested.wait(self.interval)
            if self.stopping.is_set():
                break
            with self.lock:
                self.requested.clear()
                try:
                    self.collect_once()
                    self.last_error = ""
                except Exception as exc:
                    self.last_error = str(exc)
                    logging.exception("Source collection failed")

    def collect_once(self):
        statuses = self.library.statuses()
        catalog = load_sources()
        self._honor_reddit_history(catalog, statuses)
        reddit_state = self.library.platform_status("reddit")
        now = datetime.now(timezone.utc).isoformat()
        due = [s for s in catalog if s["enabled"] and source_is_ready(s)
               and self._next_check(s, statuses.get(s["id"], {}), reddit_state) <= now]
        # One request per Reddit-wide slot; rotate the oldest source first.
        reddit = sorted((s for s in due if s.get("platform") == "reddit"),
                        key=lambda s: statuses.get(s["id"], {}).get("last_attempt_at", ""))[:1]
        sources = [s for s in due if s.get("platform") != "reddit"] + reddit
        if reddit:
            self.library.record_platform_request("reddit", now)
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(fetch_source, source): source for source in sources}
            for job in as_completed(jobs):
                source = jobs[job]
                try:
                    self.library.save_source(source["id"], job.result())
                    if source.get("platform") == "reddit":
                        self.library.clear_platform_limit("reddit")
                except Exception as exc:
                    attempted_at = datetime.now(timezone.utc).isoformat()
                    retry_at = None
                    if isinstance(exc, HTTPError) and exc.code == 429:
                        retry_at = self._retry_at(exc.headers.get("Retry-After") if exc.headers else None)
                        if source.get("platform") == "reddit":
                            retry_at = max(retry_at, self._reddit_pause_until(attempted_at))
                            self.library.pause_platform("reddit", attempted_at, retry_at)
                    self.library.fail_source(source["id"], str(exc), retry_at, attempted_at=attempted_at)
                    logging.warning("Source %s: %s", source["id"], exc)
                    if isinstance(exc, HTTPError):
                        exc.close()

    def _source_interval(self, source):
        default = self.reddit_interval if source.get("platform") == "reddit" else self.interval
        return max(default, source.get("refresh_seconds", default))

    def _next_check(self, source, record, reddit_state):
        values = [record.get("next_retry_at") or ""]
        attempted = parse_date(record.get("last_attempt_at") or "")
        if attempted:
            values.append((datetime.fromisoformat(attempted) + timedelta(seconds=self._source_interval(source))).isoformat())
        if source.get("platform") == "reddit":
            values.append(reddit_state.get("cooldown_until") or "")
            last_request = parse_date(reddit_state.get("last_request_at") or "")
            if last_request:
                values.append((datetime.fromisoformat(last_request) + timedelta(seconds=self.reddit_gap)).isoformat())
        return max(values)

    def _reddit_pause_until(self, attempted_at):
        failures = self.library.platform_status("reddit").get("rate_limit_failures", 0)
        delay = min(self.reddit_cooldown * (2 ** min(failures, 2)), max(86400, self.reddit_cooldown))
        return (datetime.fromisoformat(attempted_at) + timedelta(seconds=delay)).isoformat()

    def _honor_reddit_history(self, catalog, statuses):
        """Import recorded requests/429s once; restarting never clears a pause."""
        reddit_ids = {s["id"] for s in catalog if s.get("platform") == "reddit"}
        history = [record for key, record in statuses.items() if key in reddit_ids]
        if not history:
            return
        latest_request = max(record["last_attempt_at"] for record in history)
        state = self.library.platform_status("reddit")
        if latest_request > (state.get("last_request_at") or ""):
            self.library.record_platform_request("reddit", latest_request)
        limits = [record for record in history if "429" in (record.get("error") or "")
                  and record["last_attempt_at"] > (state.get("last_rate_limit_at") or "")]
        if limits:
            latest = max(limits, key=lambda record: record["last_attempt_at"])
            until = max(latest.get("next_retry_at") or "", self._reddit_pause_until(latest["last_attempt_at"]))
            self.library.pause_platform("reddit", latest["last_attempt_at"], until)

    def _retry_at(self, header):
        now = datetime.now(timezone.utc)
        try:
            return (now + timedelta(seconds=max(60, int(header)))).isoformat()
        except (TypeError, ValueError):
            parsed = parse_date(header or "")
            return max(parsed, (now + timedelta(seconds=60)).isoformat()) if parsed else (
                now + timedelta(seconds=self.interval)).isoformat()

    def status(self):
        saved = self.library.statuses()
        reddit_state = self.library.platform_status("reddit")
        now = datetime.now(timezone.utc).isoformat()
        sources = []
        for source in load_sources():
            record = dict(source)
            record.update(saved.get(source["id"], {}))
            record["available"] = source_is_ready(source)
            record["refresh_seconds"] = self._source_interval(source)
            record["next_check_at"] = self._next_check(source, record, reddit_state)
            if source.get("platform") == "reddit" and (reddit_state.get("cooldown_until") or "") > now:
                record["next_retry_at"] = max(record.get("next_retry_at") or "", reddit_state["cooldown_until"])
                record["limit_scope"] = "reddit"
            if not source["enabled"]:
                record["state"] = "disabled"
            elif not source_is_ready(source):
                record["state"] = "missing_feed"
            elif record.get("next_retry_at") and record["next_retry_at"] > now:
                record["state"] = "rate_limited"
            elif record.get("error"):
                record["state"] = "error"
            elif record.get("last_success_at"):
                record["state"] = "ok"
            else:
                record["state"] = "pending"
            sources.append(record)
        return {"sources": sources, "refreshing": self.refreshing,
                "refresh_seconds": self.interval, "error": self.last_error}
