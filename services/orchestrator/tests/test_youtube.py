import unittest

from news_orchestrator.youtube_health import ProgressClock
from news_orchestrator.youtube_media import command


class YoutubeCommandTests(unittest.TestCase):
    def test_live_video_copy_and_continuous_audio(self):
        args = command('http://127.0.0.1/live.m3u8', 'rtmps://a.rtmps.youtube.com:443/live2/example-key')
        self.assertEqual(args[args.index('-c:v') + 1], 'copy')
        self.assertEqual(args[args.index('-c:a') + 1], 'aac')
        audio = args[args.index('-af') + 1]
        self.assertIn('async=1:', audio)
        self.assertIn('asetpts=N/SR/TB', audio)
        self.assertEqual(args[args.index('-ar') + 1], '48000')
        self.assertIn('-re', args)
        self.assertEqual(args[args.index('-verifyhost') + 1], 'a.rtmps.youtube.com')

    def test_offline_verification_has_no_network_output(self):
        args = command('/tmp/playlist.m3u8', '/tmp/output.flv', realtime=False)
        self.assertNotIn('-re', args)
        self.assertNotIn('-reconnect', args)
        self.assertNotIn('-tls_verify', args)
        self.assertEqual(args[-1], '/tmp/output.flv')


class ProgressClockTests(unittest.TestCase):
    def test_realtime_over_many_transitions(self):
        clock = ProgressClock(0)
        for second in range(1801):
            clock.observe(second * 1_000_000, second * 30000, tick=second)
            self.assertEqual(clock.problem(second), '')
        self.assertEqual(clock.metrics(1800), {'media_rate': 1.0, 'lag_seconds': 0})

    def test_sustained_slow_progress_is_detected(self):
        clock = ProgressClock(0)
        for second in range(71):
            clock.observe(second * 500000, second * 15000, tick=second)
        self.assertIn('velocidad', clock.problem(70))
        self.assertEqual(clock.metrics(70)['media_rate'], 0.5)

    def test_stalled_media(self):
        clock = ProgressClock(0)
        clock.observe(0, 100, tick=0)
        self.assertIn('no ha avanzado', clock.problem(46))

    def test_transport_stall_even_if_clock_advances(self):
        clock = ProgressClock(0)
        for second in range(47):
            clock.observe(second * 1_000_000, 100, tick=second)
        self.assertIn('no ha enviado datos', clock.problem(46))

    def test_timestamp_rewind(self):
        clock = ProgressClock(0)
        clock.observe(100_000_000, 100, tick=0)
        clock.observe(90_000_000, 200, tick=1)
        self.assertIn('retrocedió', clock.problem(1))

    def test_accumulated_delay_after_recovery(self):
        clock = ProgressClock(0)
        clock.observe(0, 100, tick=0)
        # A 25 s input pause, followed by real-time delivery, is still late.
        for second in range(1, 56):
            clock.observe(max(0, second - 25) * 1_000_000, second * 10000, tick=second)
        self.assertTrue(clock.problem(55))

    def test_startup_and_small_jitter_are_tolerated(self):
        clock = ProgressClock(0)
        self.assertEqual(clock.problem(10), '')
        for second in range(11, 180):
            clock.observe((second - 11) * 1_000_000, second * 10000, tick=second)
        self.assertEqual(clock.problem(179), '')


if __name__ == '__main__':
    unittest.main()
