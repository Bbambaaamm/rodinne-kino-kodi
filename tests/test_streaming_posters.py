"""The focused streaming service warms a bounded, reusable poster cache."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'addons/plugin.video.webshare.available/streaming.py'
spec = importlib.util.spec_from_file_location('tested_streaming_posters', SOURCE)
streaming = importlib.util.module_from_spec(spec)
spec.loader.exec_module(streaming)


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return self.data[:size]


class StreamingPostersTests(unittest.TestCase):
    def test_only_four_valid_images_are_downloaded_and_reused(self):
        with TemporaryDirectory() as root:
            core = type('Core', (), {'CACHE_ROOT': root, 'POSTER_BASE': 'https://image.tmdb.org/t/p/w500'})()
            records = [{'meta': {'poster_path': f'/poster-{i}.jpg'}} for i in range(6)]
            with patch.object(streaming, 'urlopen', return_value=FakeResponse(b'\xff\xd8\xff' + b'poster')) as download:
                streaming.prefetch_posters(core, records)
                self.assertEqual(download.call_count, 4)
                self.assertTrue(all(streaming.cached_poster(core, row['meta']['poster_path']) for row in records[:4]))
                self.assertFalse(streaming.cached_poster(core, records[4]['meta']['poster_path']))
                streaming.prefetch_posters(core, records)
                self.assertEqual(download.call_count, 4)

    def test_invalid_or_oversized_response_never_enters_cache(self):
        with TemporaryDirectory() as root:
            core = type('Core', (), {'CACHE_ROOT': root, 'POSTER_BASE': 'https://image.tmdb.org/t/p/w500'})()
            self.assertEqual(streaming.poster_file(core, '/../bad.jpg'), '')
            record = [{'meta': {'poster_path': '/valid.jpg'}}]
            with patch.object(streaming, 'urlopen', return_value=FakeResponse(b'not a jpeg')):
                streaming.prefetch_posters(core, record)
            self.assertFalse(streaming.cached_poster(core, '/valid.jpg'))
            with patch.object(streaming, 'urlopen', return_value=FakeResponse(b'\xff\xd8\xff' + b'x' * streaming.POSTER_BYTES)):
                streaming.prefetch_posters(core, record)
            self.assertFalse(streaming.cached_poster(core, '/valid.jpg'))


if __name__ == '__main__':
    unittest.main()
