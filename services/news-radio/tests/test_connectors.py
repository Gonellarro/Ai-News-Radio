import unittest
from unittest.mock import patch

from news_radio.connectors import fetch_source, matches_keywords, matches_source, parse_bluesky


POST = {"uri": "at://did:plc:person/app.bsky.feed.post/abc123",
        "author": {"did": "did:plc:person", "displayName": "Researcher", "handle": "person.example"},
        "record": {"text": "New LLM research", "createdAt": "2026-10-16T10:00:00Z"},
        "indexedAt": "2026-10-17T15:00:00Z",
        "embed": {"external": {"uri": "https://example.com/paper?utm_source=bsky"}}}


class SocialConnectorTests(unittest.TestCase):
    def test_bluesky_preserves_post_author_link_and_original_time(self):
        result = parse_bluesky({"feed": [{"post": POST}]})[0]
        self.assertEqual(result["author"], "Researcher")
        self.assertEqual(result["published_at"], "2026-10-16T10:00:00+00:00")
        self.assertEqual(result["url"], "https://bsky.app/profile/did:plc:person/post/abc123")
        self.assertEqual(result["linked_url"], "https://example.com/paper")

    def test_reposts_replies_duplicates_and_wrong_author_uri_are_excluded(self):
        reply = {**POST, "record": {**POST["record"], "reply": {"parent": {}}}}
        wrong_uri = {**POST, "uri": "at://did:plc:imposter/app.bsky.feed.post/abc123"}
        data = {"feed": [{"post": POST}, {"post": POST}, {"post": POST, "reason": {"type": "repost"}},
                         {"post": reply}, {"post": wrong_uri}]}
        self.assertEqual(len(parse_bluesky(data)), 1)

    def test_indexing_time_does_not_replace_missing_publication_time(self):
        post = {**POST, "record": {"text": "New LLM research"}}
        self.assertIsNone(parse_bluesky({"feed": [{"post": post}]})[0]["published_at"])

    def test_keywords_match_words_and_phrases_not_substrings(self):
        self.assertFalse(matches_keywords({"title": "A chair", "summary": "sailing"}, ["AI"]))
        self.assertTrue(matches_keywords({"title": "#AI research", "summary": ""}, ["AI"]))
        self.assertTrue(matches_keywords({"title": "Análisis de inteligencia artificial", "summary": ""}, ["inteligencia artificial"]))
        self.assertTrue(matches_keywords({"title": "[R] A paper", "summary": ""}, ["[R]"]))

    def test_source_can_require_a_shared_link(self):
        article = {"title": "New model", "summary": "A question", "linked_url": ""}
        self.assertFalse(matches_source(article, {"require_link": True}))
        self.assertTrue(matches_source({**article, "linked_url": "https://example.com/paper"}, {"require_link": True}))

    @patch("news_radio.connectors.fetch_rss")
    def test_mastodon_tag_post_retains_handle_from_canonical_post_url(self, fetch):
        fetch.return_value = [{"url": "https://social.example/@researcher/123", "title": "AI paper", "summary": "Research"}]
        result = fetch_source({"platform": "mastodon", "feed_url": "https://social.example/tags/ai.rss"})
        self.assertEqual(result[0]["author"], "@researcher@social.example")

    @patch("news_radio.connectors._bluesky_json")
    def test_author_and_topic_use_distinct_public_endpoints(self, fetch):
        fetch.return_value = {"feed": [{"post": POST}]}
        source = {"connector": "bluesky_author", "actor": "person.example", "platform": "bluesky"}
        self.assertEqual(len(fetch_source(source)), 1)
        self.assertEqual(fetch.call_args.args[0], "app.bsky.feed.getAuthorFeed")
        self.assertEqual(fetch.call_args.args[1]["actor"], "person.example")
        source = {"connector": "bluesky_feed", "feed": "at://did:plc:person/app.bsky.feed.generator/ml", "platform": "bluesky"}
        fetch_source(source)
        self.assertEqual(fetch.call_args.args[0], "app.bsky.feed.getFeed")


if __name__ == "__main__":
    unittest.main()
