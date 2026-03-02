import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from area_join_notifier import _next_poll_interval  # noqa: E402


class AreaJoinNotifierTests(unittest.TestCase):
    def test_next_poll_interval_resets_to_base_when_not_rate_limited(self):
        self.assertEqual(_next_poll_interval(2, 6, False), 2)

    def test_next_poll_interval_doubles_when_rate_limited_and_caps_at_ten(self):
        self.assertEqual(_next_poll_interval(2, 2, True), 4)
        self.assertEqual(_next_poll_interval(2, 6, True), 10)
        self.assertEqual(_next_poll_interval(5, 5, True), 10)


if __name__ == "__main__":
    unittest.main()
