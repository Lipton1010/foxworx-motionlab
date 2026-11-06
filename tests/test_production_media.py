import importlib.util
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave

SPEC = importlib.util.spec_from_file_location('production_media', Path(__file__).resolve().parents[1] / 'desktop' / 'production_media.py')
media = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(media)


class TimelineTests(unittest.TestCase):
    def test_fractional_timeline_reflows_cues(self):
        result = media.build_timeline([{'id': 'a', 'seconds': '1/3'}, {'id': 'b', 'seconds': '2/3'}], 24,
                                      [{'shot_id': 'b', 'offset': '1/6', 'seconds': '1/2'}])
        self.assertEqual(result['frames'], 24)
        self.assertEqual(result['cues'][0]['start_sample'], 24000)
        self.assertEqual(result['cues'][0]['end_sample'], 48000)
        ntsc = media.build_timeline([{'id': 'x', 'seconds': '1001/1000'}], '30000/1001')
        self.assertEqual(ntsc['frames'], 30)

    def test_audio_sample_timing_is_independent_of_video_frames(self):
        result = media.build_timeline([{'id': 'a', 'seconds': 6}], cues=[
            {'shot_id': 'a', 'offset': '.65', 'seconds': '60800/24000'}])
        cue = result['cues'][0]
        self.assertEqual(cue['start_sample'], 31200)
        self.assertEqual(cue['end_sample'], 152800)
        with self.assertRaises(ValueError):
            media.build_timeline([{'id': 'a', 'seconds': 1}], cues=[
                {'shot_id': 'a', 'offset': '1/96000', 'seconds': '.5'}])

    def test_bad_timing(self):
        for shots in ([{'id': 'a', 'seconds': 0}], [{'id': 'a', 'seconds': 0.01}],
                      [{'id': 'a', 'seconds': 'NaN'}], [{'id': 'a', 'seconds': 1}, {'id': 'a', 'seconds': 1}]):
            with self.assertRaises(ValueError):
                media.build_timeline(shots)
        with self.assertRaises(ValueError):
            media.build_timeline([{'id': 'a', 'seconds': 1}], cues=[{'shot_id': 'a', 'offset': '.75', 'seconds': '.5'}])

    def test_word_checks_preserve_intent(self):
        self.assertTrue(media.compare_words('Hey! That’s our light.', "hey, that's our light")['ok'])
        self.assertFalse(media.compare_words('No, no, come back.', 'No, come back.')['ok'])
        self.assertFalse(media.compare_words('Go home then stop.', 'Stop then go home.')['ok'])
        result = media.compare_words('Oh stop! This is my kingdom!', 'Stop! This is my kingdom.')
        self.assertFalse(result['ok'])
        self.assertEqual(result['changes'][0]['intended'], ['oh'])
        self.assertEqual(result['intended'], 'Oh stop! This is my kingdom!')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'installed ffmpeg required')
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.wav = cls.root / 'gaps.wav'
        rate = 8000
        samples = [int(10000 * math.sin(2 * math.pi * 440 * i / rate)) if i < rate or i >= 2 * rate else 0 for i in range(3 * rate)]
        with wave.open(str(cls.wav), 'wb') as out:
            out.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            out.writeframes(struct.pack('<' + 'h' * len(samples), *samples))
        cls.video = cls.root / 'fixture.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x48:r=24:d=3',
                        '-i', str(cls.wav), '-c:v', 'ffv1', '-c:a', 'pcm_s16le', str(cls.video)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_clean_and_broken_media(self):
        expected = dict(duration=3, frames=72, fps=24, width=64, height=48, audio_rate=8000, channels=1)
        self.assertTrue(media.validate_media(self.video, expected, full_decode=True)['ok'])
        self.assertEqual(media.validate_media(self.video, {})['sha256'], hashlib.sha256(self.video.read_bytes()).hexdigest())
        broken = media.validate_media(self.video, dict(expected, duration=4, frames=96))
        self.assertFalse(broken['ok'])
        self.assertTrue(any('duration:' in error for error in broken['errors']))
        self.assertTrue(any('frames:' in error for error in broken['errors']))

    def test_silence_and_declared_exception(self):
        report = media.detect_audio_gaps(self.wav, min_duration=.4)
        self.assertFalse(report['ok'])
        self.assertEqual(report['sha256'], hashlib.sha256(self.wav.read_bytes()).hexdigest())
        self.assertAlmostEqual(report['unplanned'][0][0], 1, places=2)
        self.assertTrue(media.detect_audio_gaps(self.wav, [[.99, 2.01]], min_duration=.4)['ok'])
        self.assertFalse(media.detect_audio_gaps(self.wav, [[1, 1.4]], min_duration=.4)['ok'])

    def test_bad_configuration_and_missing_audio(self):
        for expected in ({'fps': 'NaN'}, {'width': 1.5}, {'audio_rate': -1}, {'typo': 3}):
            with self.assertRaises(ValueError):
                media.validate_media(self.video, expected)
        with self.assertRaises(ValueError):
            media.detect_audio_gaps(self.wav, [[2, 1]])
        for value in ('NaN', 'Infinity', True):
            with self.assertRaises(ValueError):
                media.detect_audio_gaps(self.wav, noise_db=value)

    def test_clean_audio_and_trailing_silence(self):
        for name, silent, expected in [('tone', False, True), ('silent', True, False)]:
            path = self.root / (name + '.wav')
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'anullsrc=r=8000:cl=mono' if silent else 'sine=frequency=440:sample_rate=8000',
                            '-t', '1', str(path)], check=True)
            self.assertEqual(media.detect_audio_gaps(path)['ok'], expected)
        self.assertTrue(media.detect_audio_gaps(self.root / 'silent.wav', [[0, 1]])['ok'])

    def test_cli_reports_without_overwrite(self):
        spec, report = self.root / 'spec.json', self.root / 'report.json'
        spec.write_text(json.dumps({'media': str(self.video), 'expected': {'duration': 3},
                                    'word_checks': [{'intended': 'Oh stop', 'transcript': 'stop'}]}))
        self.assertEqual(media.main([str(spec), '--report', str(report)]), 1)
        before = report.read_bytes()
        with self.assertRaises(SystemExit):
            media.main([str(spec), '--report', str(report)])
        self.assertEqual(report.read_bytes(), before)
        for empty in ({}, {'word_checks': []}):
            spec.write_text(json.dumps(empty))
            with self.assertRaises(SystemExit):
                media.main([str(spec), '--report', str(self.root / 'unused.json')])
            self.assertFalse((self.root / 'unused.json').exists())


if __name__ == '__main__':
    unittest.main()
