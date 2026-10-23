import unittest

from news_radio.feeds import normalize_url, parse_feed


class FeedParsingTests(unittest.TestCase):
    def test_rss_guid_permalink_and_original_date(self):
        items = parse_feed(b'''<rss><channel><item>
            <title>New &amp; open</title><guid isPermaLink="true">https://example.com/news?utm_source=rss</guid>
            <description>&lt;p&gt;A model&lt;/p&gt;</description><pubDate>Fri, 16 Oct 2026 19:00:00 +0200</pubDate>
            </item></channel></rss>''', "https://example.com/feed")
        self.assertEqual(items[0]["url"], "https://example.com/news")
        self.assertEqual(items[0]["published_at"], "2026-10-16T17:00:00+00:00")
        self.assertEqual(items[0]["summary"], "A model")

    def test_atom_uses_article_not_self_link_and_keeps_dates_separate(self):
        items = parse_feed(b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
            <title>Announcement</title><link rel="self" href="https://example.com/api/1"/>
            <link rel="alternate" href="/story"/><published>2026-10-10T10:00:00Z</published>
            <updated>2026-10-16T10:00:00Z</updated></entry></feed>''', "https://example.com/feed")
        self.assertEqual(items[0]["url"], "https://example.com/story")
        self.assertTrue(items[0]["published_at"].startswith("2026-10-10"))
        self.assertTrue(items[0]["updated_at"].startswith("2026-10-16"))

    def test_update_only_does_not_invent_publication_date(self):
        items = parse_feed(b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
            <title>Updated story</title><link href="https://example.com/story"/>
            <updated>2026-10-16T10:00:00Z</updated></entry></feed>''', "https://example.com/feed")
        self.assertIsNone(items[0]["published_at"])

    def test_rdf_namespace_and_empty_feeds(self):
        items = parse_feed(b'''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
            <item><title>Paper</title><link>https://example.com/paper</link>
            <dc:date>2026-10-16T10:00:00Z</dc:date></item></rdf:RDF>''', "https://example.com/feed")
        self.assertEqual(len(items), 1)
        self.assertIsNotNone(items[0]["published_at"])
        self.assertEqual(parse_feed(b"<rss><channel/></rss>", "https://example.com"), [])

    def test_invalid_feed_is_a_failure_instead_of_successful_empty_update(self):
        with self.assertRaises(ValueError):
            parse_feed(b"<html><body>Access denied</body></html>", "https://example.com")

    def test_tracking_removed_but_meaningful_query_preserved(self):
        self.assertEqual(normalize_url("https://EXAMPLE.com/article?id=12&utm_source=rss#top"),
                         "https://example.com/article?id=12")

    def test_titleless_mastodon_post_preserves_author_and_link(self):
        items = parse_feed(b'''<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
            <link>https://social.example/@person/123</link><dc:creator>Researcher</dc:creator>
            <description>&lt;p&gt;New LLM paper &lt;a href="https://arxiv.org/abs/1234"&gt;read it&lt;/a&gt;&lt;/p&gt;</description>
            <pubDate>Fri, 16 Oct 2026 19:00:00 GMT</pubDate></item></channel></rss>''', "https://social.example/feed")
        self.assertEqual(items[0]["title"], "New LLM paper read it")
        self.assertEqual(items[0]["author"], "Researcher")
        self.assertEqual(items[0]["linked_url"], "https://arxiv.org/abs/1234")
        self.assertEqual(items[0]["url"], "https://social.example/@person/123")

    def test_reddit_atom_content_keeps_thread_and_shared_link_distinct(self):
        items = parse_feed(b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>[R] New paper</title>
            <author><name>/u/researcher</name><uri>https://www.reddit.com/user/researcher</uri></author>
            <link href="https://www.reddit.com/r/MachineLearning/comments/123"/>
            <content type="html">&lt;a href="https://www.reddit.com/user/researcher"&gt;author&lt;/a&gt;
                &lt;a href="https://example.com/paper"&gt;[link]&lt;/a&gt;</content>
            <published>2026-10-16T10:00:00Z</published></entry></feed>''', "https://www.reddit.com/feed")
        self.assertEqual(items[0]["author"], "/u/researcher")
        self.assertEqual(items[0]["linked_url"], "https://example.com/paper")
        self.assertIn("/comments/", items[0]["url"])
        self.assertTrue(items[0]["summary"])


if __name__ == "__main__":
    unittest.main()
