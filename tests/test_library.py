from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import sqlite3

from news_radio.collector import NewsCollector
from news_radio.library import NewsLibrary


SOURCE = {"id": "example", "name": "Example", "enabled": True, "language": "en", "feed_url": "https://example.com/feed"}


def article(url="https://example.com/story", days=0, title="Qwen model"):
    return {"url": url, "title": title, "summary": "A model announcement",
            "published_at": (datetime.now(timezone.utc) - timedelta(days=days, hours=1)).isoformat(),
            "updated_at": None}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.library = NewsLibrary(self.directory)

    def test_repeated_collection_deduplicates_and_survives_restart(self):
        self.library.save_source("example", [article()])
        self.library.save_source("example", [article()])
        result = NewsLibrary(self.directory).news([SOURCE])
        self.assertEqual(result["total_count"], 1)

    def test_strict_range_excludes_old_future_and_undated_items(self):
        undated = {**article("https://example.com/undated"), "published_at": None}
        self.library.save_source("example", [article(), article("https://example.com/old", 4),
                                             article("https://example.com/future", -3), undated])
        result = self.library.news([SOURCE], time_range="day")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["undated_count"], 1)
        unlimited = self.library.news([SOURCE], time_range="")
        self.assertEqual(unlimited["count"], 3)
        self.assertTrue(any(not item["published_at"] for item in unlimited["results"]))

    def test_disabled_or_removed_source_hides_saved_articles(self):
        self.library.save_source("example", [article()])
        self.assertEqual(self.library.news([{**SOURCE, "enabled": False}])["count"], 0)
        self.assertEqual(self.library.news([])["count"], 0)

    def test_filters_use_source_language_and_text_without_losing_accents(self):
        self.library.save_source("example", [article(title="Regulación de inteligencia artificial")])
        self.assertEqual(self.library.news([SOURCE], query="regulacion")["count"], 1)
        self.assertEqual(self.library.news([SOURCE], language="es")["count"], 0)

    def test_failed_update_retains_previous_articles_and_success_date(self):
        self.library.save_source("example", [article()])
        previous = self.library.statuses()["example"]["last_success_at"]
        self.library.fail_source("example", "HTTP 503")
        self.assertEqual(self.library.news([SOURCE])["count"], 1)
        status = self.library.statuses()["example"]
        self.assertEqual(status["last_success_at"], previous)
        self.assertEqual(status["error"], "HTTP 503")

    def test_duplicate_url_retains_multiple_origins(self):
        self.library.save_source("example", [article()])
        self.library.save_source("second", [article()])
        result = self.library.news([SOURCE, {**SOURCE, "id": "second", "name": "Second"}])
        self.assertEqual(result["count"], 1)
        self.assertEqual(set(result["results"][0]["sources"]), {"Example", "Second"})

    def test_bluesky_without_rss_is_available_but_separate_from_web(self):
        social = {**SOURCE, "id": "social", "feed_url": None, "connector": "bluesky_author",
                  "actor": "person.example", "platform": "bluesky"}
        post = {**article(), "author": "A researcher", "linked_url": "https://example.com/paper", "content_kind": "social_post"}
        self.library.save_source("social", [post])
        self.assertEqual(self.library.news([social], platform="web")["count"], 0)
        result = self.library.news([social], platform="bluesky")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["author"], "A researcher")
        self.assertEqual(result["results"][0]["content_kind"], "social_post")

    def test_changed_source_filters_also_apply_to_previously_saved_posts(self):
        self.library.save_source("example", [article()])
        self.assertEqual(self.library.news([{**SOURCE, "require_link": True}])["count"], 0)
        self.assertEqual(self.library.news([{**SOURCE, "keywords": ["unrelated"]}])["count"], 0)
        self.assertEqual(self.library.news([SOURCE])["count"], 1)

    def test_migration_preserves_the_existing_news_library(self):
        other = self.directory / "legacy"
        other.mkdir()
        db = sqlite3.connect(other / "news.sqlite3")
        db.execute("""CREATE TABLE articles(id TEXT PRIMARY KEY, url TEXT UNIQUE, title TEXT,
                      summary TEXT, published_at TEXT, updated_at TEXT, discovered_at TEXT, last_seen_at TEXT)""")
        db.execute("INSERT INTO articles VALUES ('old', 'https://example.com/old', 'Existing news', '', NULL, NULL, '2026-10-10', '2026-10-10')")
        db.execute("CREATE TABLE article_sources(article_id TEXT, source_id TEXT, PRIMARY KEY(article_id,source_id))")
        db.execute("INSERT INTO article_sources VALUES ('old','example')")
        db.commit()
        db.close()
        result = NewsLibrary(other).news([SOURCE], time_range="")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["title"], "Existing news")
        self.assertEqual(result["results"][0]["content_kind"], "article")

    @patch("news_radio.collector.load_sources")
    @patch("news_radio.collector.fetch_source")
    def test_rate_limit_is_respected_even_when_refresh_is_requested_again(self, fetch, catalog):
        catalog.return_value = [SOURCE]
        fetch.side_effect = HTTPError(SOURCE["feed_url"], 429, "Too many requests", {"Retry-After": "3600"}, None)
        collector = NewsCollector(self.library)
        collector.collect_once()
        collector.collect_once()
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(collector.status()["sources"][0]["state"], "rate_limited")

    @patch("news_radio.collector.load_sources")
    @patch("news_radio.collector.fetch_source")
    def test_one_broken_source_does_not_block_others(self, fetch, catalog):
        catalog.return_value = [SOURCE, {**SOURCE, "id": "broken"}]
        def retrieve(source):
            if source["id"] == "broken":
                raise ValueError("Invalid RSS")
            return [article()]
        fetch.side_effect = retrieve
        NewsCollector(self.library).collect_once()
        self.assertEqual(self.library.news([SOURCE])["count"], 1)
        self.assertEqual(self.library.statuses()["broken"]["error"], "Invalid RSS")


if __name__ == "__main__":
    unittest.main()
