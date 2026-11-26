import threading
import time
import unittest
from unittest.mock import patch

from k922_ntrip.protocol import _resolve_caster


class ResolverTests(unittest.TestCase):
    def test_blocked_system_lookup_respects_timeout_and_cancellation(self):
        for stop_early in (False, True):
            with self.subTest(stop_early=stop_early):
                stopped = threading.Event()
                release = threading.Event()
                finished = threading.Event()

                def slow_lookup(*args, **kwargs):
                    if stop_early:
                        stopped.set()
                    release.wait(3)
                    finished.set()
                    return []

                with patch("k922_ntrip.protocol.socket.getaddrinfo", side_effect=slow_lookup):
                    try:
                        error = ConnectionAbortedError if stop_early else TimeoutError
                        deadline = time.monotonic() + (5 if stop_early else 0.15)
                        with self.assertRaises(error):
                            _resolve_caster("example.test", 2101, deadline, stopped)
                    finally:
                        release.set()
                        self.assertTrue(finished.wait(2))
