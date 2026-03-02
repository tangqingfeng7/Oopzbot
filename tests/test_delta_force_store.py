import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import database  # noqa: E402
from plugins._delta_force_store import DeltaForceStore  # noqa: E402


class DeltaForceStoreTests(unittest.TestCase):
    def test_store_reads_and_updates_active_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            with patch.object(database, "DB_PATH", db_path):
                database.init_database()
                store = DeltaForceStore()

                self.assertIsNone(store.get_active_token("u1"))

                store.set_active_token("u1", "tok-1")
                self.assertEqual(store.get_active_token("u1"), "tok-1")

                accounts = [
                    {"frameworkToken": "tok-2", "isValid": True},
                    {"frameworkToken": "tok-3", "isValid": True},
                ]
                self.assertEqual(store.choose_active_token("u1", accounts), "tok-2")
                self.assertEqual(store.get_active_token("u1"), "tok-2")


if __name__ == "__main__":
    unittest.main()
