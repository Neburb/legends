"""A dispatch never invents or increments a version."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from manual_version import choose_version


class ManualVersionTests(unittest.TestCase):
    def test_explicit_newer_version_is_kept(self):
        self.assertEqual(choose_version('0.0.75', ['v0.0.74', 'v0.0.73']), '0.0.75')
        self.assertEqual(choose_version('0.0.1', []), '0.0.1')

    def test_existing_or_older_version_is_rejected(self):
        for candidate in ('0.0.74', '0.0.73'):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                choose_version(candidate, ['v0.0.74'])

    def test_invalid_source_version_is_rejected(self):
        for candidate in ('v0.0.75', '0.0.75-preview', '0.0', None):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                choose_version(candidate, ['v0.0.74'])


if __name__ == '__main__':
    unittest.main()
