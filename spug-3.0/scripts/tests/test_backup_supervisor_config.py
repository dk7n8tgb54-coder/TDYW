import configparser
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR_CONFIG = PROJECT_ROOT / "docker" / "config" / "supervisord.conf"


class BackupSupervisorConfigTests(unittest.TestCase):
    def test_writer_programs_have_graceful_stop_limits(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(SUPERVISOR_CONFIG, encoding="utf-8")

        api_programs = ("spug-api", "spug-api-upload", "spug-ws", "spug-worker")
        celery_programs = (
            "spug-celery",
            "spug-celery-cleanup",
            "spug-celery-merge",
            "spug-celery-batch",
            "spug-celery-thumbnail",
            "spug-celery-radio-license",
        )
        for name in api_programs:
            section = parser[f"program:{name}"]
            self.assertEqual(section["stopsignal"], "TERM")
            self.assertGreaterEqual(int(section["stopwaitsecs"]), 300)
            self.assertEqual(section["stopasgroup"], "true")
            self.assertEqual(section["killasgroup"], "true")

        for name in celery_programs:
            section = parser[f"program:{name}"]
            self.assertEqual(section["stopsignal"], "TERM")
            self.assertGreaterEqual(int(section["stopwaitsecs"]), 900)
            self.assertEqual(section["stopasgroup"], "true")
            self.assertEqual(section["killasgroup"], "true")

        beat = parser["program:spug-celery-beat"]
        self.assertEqual(beat["stopsignal"], "TERM")
        self.assertGreaterEqual(int(beat["stopwaitsecs"]), 60)


if __name__ == "__main__":
    unittest.main()
