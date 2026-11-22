"""Read AVI track headers without scanning or decoding the video payload."""
import importlib.util
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'addons/plugin.video.webshare.available'


def load(name):
    spec = importlib.util.spec_from_file_location('avi_test_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


streams, matching = load('streams'), load('matching')


def chunk(kind, payload):
    return kind + struct.pack('<I', len(payload)) + payload + b'\x00' * (len(payload) & 1)


def stream(kind, fmt, codec=b'\x00'*4, lang=0, name=b''):
    header = bytearray(56)
    header[:8] = kind + codec
    struct.pack_into('<H', header, 14, lang)
    result = chunk(b'strh', header) + chunk(b'strf', fmt)
    if name:
        result += chunk(b'strn', name + b'\x00')
    return chunk(b'LIST', b'strl' + result)


def video(width=1920, height=1080, codec=b'XVID'):
    return struct.pack('<IiiHH4sIiiII', 40, width, height, 1, 24, codec, 0, 0, 0, 0, 0)


def audio(tag=0x55, channels=2, rate=48000):
    return struct.pack('<HHIIHH', tag, channels, rate, 16000, 1, 16)


def hdrl(tracks):
    main = bytearray(56)
    struct.pack_into('<I', main, 24, len(tracks))
    return chunk(b'LIST', b'hdrl' + chunk(b'avih', main) + b''.join(tracks))


def avi(tracks, prefix=b''):
    body = b'AVI ' + prefix + hdrl(tracks) + chunk(b'LIST', b'movi' + chunk(b'00dc', b'video'))
    return b'RIFF' + struct.pack('<I', len(body)) + body


class Reader:
    def __init__(self, data):
        self.data, self.size, self.bytes, self.reads = data, len(data), 0, []

    def read(self, offset, length):
        self.reads.append((offset, length))
        if offset < 0 or offset + length > len(self.data):
            raise streams.ProbeError('fixture out of bounds')
        self.bytes += length
        return self.data[offset:offset+length]


class AviStreamsTests(unittest.TestCase):
    def test_xvid_mp3_and_actual_dimensions_are_read_without_media_payload(self):
        data = avi([stream(b'vids', video()), stream(b'auds', audio())])
        reader = Reader(data)
        result = streams.inspect(reader)
        self.assertEqual((result['state'], result['container']), ('verified', 'avi'))
        image, sound = result['tracks']
        self.assertEqual((image['width'], image['height'], image['codec']), (1920, 1080, 'V_MPEG4/ISO/ASP'))
        self.assertEqual((sound['codec'], sound['channels'], sound['samplerate']), ('A_MPEG/L3', 2, 48000))
        self.assertEqual(sound['language'], 'und')
        movi = data.index(b'movi') + 4
        self.assertTrue(all(start + count <= movi for start, count in reader.reads))
        candidate = {'name':'S03E04 CZ.avi', 'streams':result}
        self.assertEqual(matching.source_attributes(candidate)['quality'], '1920×1080')
        self.assertEqual(matching.source_attributes(candidate)['codec'], 'MPEG-4')
        self.assertEqual(matching.source_summary(candidate), 'Zvuk: ? MP3 2ch • Titulky: —')

    def test_language_tags_multiple_audio_tracks_and_subtitle_stream_are_preserved(self):
        result = streams.inspect(Reader(avi([
            stream(b'vids', video(codec=b'H264')),
            stream(b'auds', audio(0x2000, 6), lang=0x0405),
            stream(b'auds', audio(0x55), name=b'English'),
            stream(b'txts', b'', name=b'lang=cs'),
        ])))
        self.assertEqual([row['language'] for row in result['tracks']], ['und', 'cs', 'en', 'cs'])
        summary = matching.source_summary({'streams':result})
        self.assertIn('CZ AC3 6ch', summary)
        self.assertIn('EN MP3 2ch', summary)
        self.assertIn('Titulky: CZ', summary)

    def test_unknown_language_is_not_guessed_from_filename_or_arbitrary_stream_name(self):
        for name in (b'', b'Englishman commentary', b'Track 1'):
            result = streams.inspect(Reader(avi([stream(b'vids',video()), stream(b'auds',audio(),name=name)])))
            self.assertEqual(result['tracks'][1]['language'], 'und')
            self.assertIn('Zvuk: ? MP3', matching.source_summary({'name':'CZ EN S03E04.avi','streams':result}))

    def test_extensible_pcm_audio_and_negative_bitmap_height(self):
        guid = struct.pack('<I', 1) + b'\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71'
        fmt = audio(0xfffe, 6) + struct.pack('<HHI', 22, 16, 0x3f) + guid
        result = streams.inspect(Reader(avi([stream(b'vids',video(height=-1080)), stream(b'auds',fmt)])))
        self.assertEqual(result['tracks'][0]['height'], 1080)
        self.assertEqual(result['tracks'][1]['codec'], 'PCM')
        self.assertEqual(result['tracks'][1]['channels'], 6)

    def test_xsub_in_bitmap_codec_is_counted_as_subtitle_not_another_video(self):
        result = streams.inspect(Reader(avi([stream(b'vids',video()), stream(b'vids',video(codec=b'DXSB'))])))
        self.assertEqual([row['type'] for row in result['tracks']], ['video','subtitle'])
        self.assertEqual(result['tracks'][1]['codec'], 'XSub')

    def test_odd_sized_chunks_are_padded_and_skipped(self):
        result = streams.inspect(Reader(avi([stream(b'vids',video()), stream(b'auds',audio(),name=b'cs')], chunk(b'JUNK',b'123'))))
        self.assertEqual(result['tracks'][1]['language'], 'cs')

    def test_large_padding_is_skipped_by_offset_without_reading_it(self):
        gap = 50*1024*1024
        headers = hdrl([stream(b'vids',video()), stream(b'auds',audio())])
        first = b'RIFF' + struct.pack('<I', 4 + 8 + gap + len(headers)) + b'AVI JUNK' + struct.pack('<I', gap)
        segments = [(0,first), (20+gap, headers)]
        class SparseReader:
            size = 20 + gap + len(headers)
            bytes = 0
            def read(self, offset, length):
                self.bytes += length
                for start, data in segments:
                    if start <= offset and offset + length <= start + len(data):
                        return data[offset-start:offset-start+length]
                raise AssertionError('Attempted to read padding or media data')
        reader = SparseReader()
        self.assertEqual(streams.inspect(reader)['container'], 'avi')
        self.assertLess(reader.bytes, 1024)

    def test_missing_truncated_ambiguous_and_oversized_headers_fail_closed(self):
        valid = avi([stream(b'vids',video()), stream(b'auds',audio())])
        malformed = [valid[:35], avi([stream(b'vids', b'bad')]),
                     avi([stream(b'vids',video()), stream(b'auds',b'bad')]),
                     avi([stream(b'vids',video()), stream(b'auds',audio(0xfffe))]),
                     b'RIFF'+struct.pack('<I',16)+b'AVI LIST'+struct.pack('<I',4)+b'movi']
        broken = bytearray(valid)
        struct.pack_into('<I', broken, broken.index(b'avih')+8+24, 3)
        malformed.append(bytes(broken))
        broken = bytearray(valid)
        struct.pack_into('<I', broken, broken.index(b'strh')+4, 0xffffffff)
        malformed.append(bytes(broken))
        for data in malformed:
            with self.subTest(length=len(data)):
                with self.assertRaises(streams.ProbeError):
                    streams.inspect(Reader(data))

    def test_riff_wave_does_not_masquerade_as_avi(self):
        with self.assertRaises(streams.ProbeError):
            streams.inspect(Reader(b'RIFF'+struct.pack('<I',8)+b'WAVEjunk'))

    def test_oversized_metadata_is_rejected_before_its_payload_is_read(self):
        metadata_size = 1024**2 + 4
        class HeaderOnlyReader:
            size = 8 + 4 + 8 + metadata_size
            prefix = b'RIFF' + struct.pack('<I', size-8) + b'AVI LIST' + struct.pack('<I', 1024**2 + 4) + b'hdrl'
            def read(self, offset, length):
                if offset + length > len(self.prefix):
                    raise AssertionError('Oversized metadata was read')
                return self.prefix[offset:offset+length]
        with self.assertRaisesRegex(streams.ProbeError, 'metadata bounds'):
            streams.inspect(HeaderOnlyReader())

    def test_duplicate_stream_headers_are_rejected(self):
        header = bytearray(56)
        header[:4] = b'vids'
        duplicate = chunk(b'LIST', b'strl' + chunk(b'strh',header)*2 + chunk(b'strf',video()))
        with self.assertRaisesRegex(streams.ProbeError, 'ambiguous'):
            streams.inspect(Reader(avi([duplicate])))


if __name__ == '__main__':
    unittest.main()
