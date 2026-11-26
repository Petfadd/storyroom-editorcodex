"""Every cut lands on its exact frame: picture, sound bite, and a person's photo.

A real 3-shot film is rendered: narration over a 30 fps clip, a sound bite from a clip
at another rate, narration again. Every source frame carries its own frame number in
its brightness, so each output frame can be traced back to the exact source frame.
"""
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image

from documentary_final_renderer import render
from documentary_storyboard import prepare

FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H = 128, 72
SCRIPT = '''Beat: 001
Type: NARRATION (VOICE OVER)
Narration State: PLAYING
Narration Clock: 00:00:00,000 --> 00:00:02,000
Footage Audio: MUTED (0%)
Video File: S01.mp4
Source IN: 00:00:00,000
Source OUT: 00:00:02,000
On-screen Caption: None
Beat: 002
Type: DOCUMENTARY SOUND BITE
Narration State: PAUSED (Suspended at 00:00:02,000)
Footage Audio: UNMUTED (100% Live Speech)
Video File: S02.mp4
Source IN: 00:00:03,000
Source OUT: 00:00:05,000
Duration: 00:00:02,000
Speaker: Not verified
On-screen Caption: None
Beat: 003
Type: NARRATION (VOICE OVER)
Narration State: RESUMING
Narration Clock: 00:00:02,000 --> 00:00:04,000
Footage Audio: MUTED (0%)
Video File: S01.mp4
Source IN: 00:00:02,000
Source OUT: 00:00:04,000
On-screen Caption: None
'''


def make_clip(path, rate, chroma):
    subprocess.run([FF, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=black:s={W}x{H}:r={rate}:d=10', '-f', 'lavfi',
                    '-i', 'sine=frequency=880:duration=10:sample_rate=48000', '-vf',
                    f"format=yuv444p,geq=lum='16+mod(N,240)':cb={chroma}:cr=128", '-c:v', 'libx264', '-qp', '0',
                    '-pix_fmt', 'yuv444p', '-c:a', 'aac', '-shortest', str(path)], check=True)


def frames_of(path):
    raw = subprocess.run([FF, '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'yuv444p', '-'],
                         capture_output=True).stdout
    size = W * H * 3
    out = []
    for i in range(len(raw) // size):
        f = np.frombuffer(raw[i * size:(i + 1) * size], dtype=np.uint8).reshape(3, H, W)
        out.append((int(round(f[0].mean())) - 16, int(round(f[1].mean())),
                    int(round(f[2][H // 2 - 4:H // 2 + 4, W // 2 - 4:W // 2 + 4].mean()))))
    return out


class CutPrecisionTest(unittest.TestCase):
    def film(self, bite_rate, with_photo=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for f in ('sources', 'inputs', 'renders', 'people'):
            (root / f).mkdir()
        subprocess.run([FF, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4:sample_rate=48000',
                        '-c:a', 'pcm_s16le', str(root / 'inputs/voice.wav')], check=True)
        make_clip(root / 'sources/a.mp4', '30', 60)
        make_clip(root / 'sources/b.mp4', bite_rate, 200)
        Image.new('RGB', (400, 300), (255, 0, 0)).save(root / 'people/j.png')
        p = {'profile': 'documentary', 'edit_mode': 'documentary', 'scenes': [], 'production_script': {'text': SCRIPT},
             'voiceover': {'path': 'inputs/voice.wav', 'name': 'voice.wav', 'duration': 4},
             'srt': {'blocks': [{'number': 1, 'start_ms': 0, 'end_ms': 2000, 'text': 'Jane Doe was here' if with_photo else 'One'},
                                {'number': 2, 'start_ms': 2000, 'end_ms': 4000, 'text': 'Jane Doe again' if with_photo else 'Two'}]},
             'people': [{'id': 'j', 'name': 'Jane Doe', 'role': 'Victim', 'aliases': [], 'show': True, 'photo_over_video': True,
                         'photo': {'path': 'people/j.png', 'uploaded': 1}}] if with_photo else [],
             # Frame-exact check: a still photo, no entrance or camera move, no name graphic.
             'person_overlay_settings': {'photo_opening': 'always', 'show_label': False, 'enabled': True,
                                         'photo_motion': 'none', 'cinematic_name_intro': False},
             'assets': [{'id': 'a', 'name': 'S01.mp4', 'original_name': 'S01.mp4', 'kind': 'video', 'path': 'sources/a.mp4',
                         'duration': 10, 'revision': 'v'},
                        {'id': 'b', 'name': 'S02.mp4', 'original_name': 'S02.mp4', 'kind': 'video', 'path': 'sources/b.mp4',
                         'duration': 10, 'revision': 'w'}]}
        p, plan = prepare(p, root, [], [], False, lambda _: True)
        out = root / 'renders/out.mp4'
        result = render(root, p, plan, out, W, H)
        return result, frames_of(out)

    def check_picture(self, result, frames, bite_rate):
        fps, r2 = Fraction(result['fps']), Fraction(bite_rate)
        self.assertEqual(len(frames), 180)
        for k, (n, chroma, cr) in enumerate(frames):
            if cr > 190:
                continue                                     # under the photo
            t = Fraction(k) / fps
            want = ('S01', round(t * 30)) if t < 2 else ('S02', round((1 + t) * r2)) if t < 4 else ('S01', round((t - 2) * 30))
            got = 'S01' if chroma < 128 else 'S02'
            d = (n - want[1]) % 240
            self.assertEqual(got, want[0], f'frame {k}')
            self.assertLessEqual(min(d, 240 - d), 0 if want[0] == 'S01' or r2 == fps else 1, f'frame {k}: source frame')

    def test_same_rate_cuts_on_the_exact_frame(self):
        result, frames = self.film('30')
        self.check_picture(result, frames, '30')

    def test_mixed_rates_are_conformed_without_moving_a_cut(self):
        for rate in ('25', '30000/1001', '60'):
            with self.subTest(rate=rate):
                result, frames = self.film(rate)
                self.assertEqual(result['fps'], '30')
                self.check_picture(result, frames, rate)

    def test_a_photo_covers_its_lines_exactly_and_never_the_bite(self):
        result, frames = self.film('30', with_photo=True)
        on = [k for k, f in enumerate(frames) if f[2] > 190]
        self.assertEqual(on, list(range(0, 60)) + list(range(120, 180)))
        self.check_picture(result, frames, '30')


if __name__ == '__main__':
    unittest.main()
