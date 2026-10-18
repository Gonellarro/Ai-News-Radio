"""Collection budgets and persisted pauses, with all network calls mocked."""

from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from news_radio.collector import NewsCollector
from news_radio.library import NewsLibrary


REDDIT = [{"id": f"reddit-{i}", "name": f"Reddit {i}", "platform": "reddit", "enabled": True,
           "feed_url": f"https://www.reddit.com/r/test{i}/new/.rss"} for i in range(4)]
ARTICLE = {"url": "https://example.com/post", "title": "New model", "summary": "A post",
           "published_at": None, "updated_at": None}


class CollectionPolicyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.library = NewsLibrary(folder.name)

    @patch("news_radio.collector.load_sources", return_value=REDDIT)
    @patch("news_radio.collector.fetch_source", return_value=[ARTICLE])
    def test_one_reddit_request_per_slot_and_no_repeat_after_restart(self, fetch, catalog):
        NewsCollector(self.library).collect_once()
        NewsCollector(self.library).collect_once()
        self.assertEqual(fetch.call_count, 1)
        first = fetch.call_args.args[0]["id"]
        later = datetime.now(timezone.utc) + timedelta(minutes=31)
        with patch("news_radio.collector.datetime", wraps=datetime) as clock:
            clock.now.return_value = later
            NewsCollector(self.library).collect_once()
        self.assertEqual(fetch.call_count, 2)
        self.assertNotEqual(first, fetch.call_args.args[0]["id"])

    @patch("news_radio.collector.load_sources", return_value=REDDIT)
    @patch("news_radio.collector.fetch_source")
    def test_429_pauses_every_reddit_flow_and_backoff_grows_without_restart_reset(self, fetch, catalog):
        fetch.side_effect = HTTPError(REDDIT[0]["feed_url"], 429, "Too Many Requests", {"Retry-After": "1"}, None)
        before = datetime.now(timezone.utc)
        NewsCollector(self.library).collect_once()
        state = self.library.platform_status("reddit")
        until = datetime.fromisoformat(state["cooldown_until"])
        self.assertGreaterEqual(until, before + timedelta(hours=6))
        self.assertEqual(state["rate_limit_failures"], 1)
        restarted = NewsCollector(self.library)
        restarted.collect_once()
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(self.library.platform_status("reddit")["rate_limit_failures"], 1)
        self.assertTrue(all(s["state"] == "rate_limited" for s in restarted.status()["sources"]))
        later = until + timedelta(minutes=1)
        with patch("news_radio.collector.datetime", wraps=datetime) as clock:
            clock.now.return_value = later
            restarted.collect_once()
        state = self.library.platform_status("reddit")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(state["rate_limit_failures"], 2)
        self.assertGreaterEqual(datetime.fromisoformat(state["cooldown_until"]), later + timedelta(hours=12))

    @patch("news_radio.collector.load_sources", return_value=REDDIT)
    @patch("news_radio.collector.fetch_source")
    def test_preexisting_429_is_honored_before_any_new_network_request(self, fetch, catalog):
        attempted = datetime.now(timezone.utc) - timedelta(minutes=2)
        self.library.fail_source("reddit-1", "HTTP Error 429: Too Many Requests", attempted_at=attempted.isoformat())
        NewsCollector(self.library).collect_once()
        fetch.assert_not_called()
        self.assertGreaterEqual(datetime.fromisoformat(self.library.platform_status("reddit")["cooldown_until"]),
                                attempted + timedelta(hours=6))

    @patch("news_radio.collector.load_sources", return_value=REDDIT)
    @patch("news_radio.collector.fetch_source")
    def test_longer_server_retry_after_is_never_shortened(self, fetch, catalog):
        fetch.side_effect = HTTPError(REDDIT[0]["feed_url"], 429, "Too Many Requests", {"Retry-After": "172800"}, None)
        before = datetime.now(timezone.utc)
        NewsCollector(self.library).collect_once()
        self.assertGreaterEqual(datetime.fromisoformat(self.library.platform_status("reddit")["cooldown_until"]),
                                before + timedelta(days=2))

    @patch("news_radio.collector.fetch_source")
    def test_recent_cached_sources_do_not_refetch_on_startup_or_manual_refresh(self, fetch):
        source = {"id": "web", "enabled": True, "feed_url": "https://example.com/feed"}
        self.library.save_source("web", [ARTICLE])
        with patch("news_radio.collector.load_sources", return_value=[source]):
            collector = NewsCollector(self.library)
            collector.collect_once()
            collector.request_refresh()
            collector.collect_once()
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
