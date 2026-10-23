"""Regression checks for failures of SearXNG date-filtered searches."""

import os
import unittest
from unittest.mock import patch

from news_radio.search import search_news


ARTICLE = {"title": "Qwen announcement", "url": "https://example.com/qwen", "engine": "bing news"}
FAILED = {"results": [], "unresponsive_engines": [["bing news", "parsing error"]]}


class SearchRecoveryTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"SEARXNG_GENERAL_ENGINES": "", "SEARXNG_NEWS_ENGINES": ""})
        environment.start()
        self.addCleanup(environment.stop)

    @patch("news_radio.search._fetch")
    def test_failed_dated_query_recovers_and_discloses_broader_period(self, fetch):
        fetch.side_effect = [FAILED, {"results": [ARTICLE]}]
        result = search_news("Qwen", time_range="day", language="es")
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["requested_time_range"], "day")
        self.assertEqual(result["applied_time_range"], "")
        self.assertTrue(result["notices"])
        self.assertTrue(result["diagnostics"]["initial_engine_errors"])
        self.assertEqual(result["results"][0]["published_at"], "")
        initial, retry = [call.args[0] for call in fetch.call_args_list]
        self.assertEqual(initial["time_range"], "day")
        self.assertNotIn("time_range", retry)
        self.assertEqual(retry["language"], "es")
        self.assertEqual(retry["q"], "Qwen")

    @patch("news_radio.search._fetch")
    def test_partial_success_preserves_requested_period(self, fetch):
        fetch.return_value = {"results": [ARTICLE], "unresponsive_engines": [["reuters", "HTTP error"]]}
        result = search_news("Qwen", time_range="day")
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["applied_time_range"], "day")
        self.assertEqual(result["warnings"], ["reuters: HTTP error"])

    @patch("news_radio.search._fetch")
    def test_normal_empty_search_does_not_silently_broaden_period(self, fetch):
        fetch.return_value = {"results": []}
        result = search_news("no matching topic", time_range="day")
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["applied_time_range"], "day")

    @patch("news_radio.search._fetch")
    def test_failed_recovery_stops_after_one_retry(self, fetch):
        fetch.side_effect = [FAILED, FAILED]
        result = search_news("Qwen", time_range="day")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["count"], 0)
        self.assertTrue(result["warnings"])

    @patch("news_radio.search._fetch")
    def test_undated_failure_is_not_repeated(self, fetch):
        fetch.return_value = FAILED
        result = search_news("Qwen")
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(result["fallback_used"])

    @patch.dict(os.environ, {"SEARXNG_GENERAL_ENGINES": "bing"})
    @patch("news_radio.search._fetch")
    def test_general_engine_selection_does_not_affect_news_category(self, fetch):
        fetch.return_value = {"results": [ARTICLE]}
        search_news("Qwen", category="general")
        self.assertEqual(fetch.call_args.args[0]["engines"], "bing")
        search_news("Qwen", category="news")
        self.assertNotIn("engines", fetch.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
