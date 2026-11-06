"""Clean photo slideshow with instrumental BGM and no speech or graphic overlays."""

from array import array
import contextlib
import math
from pathlib import Path
import random
import subprocess
import sys
import wave

from PIL import Image, ImageOps


def make_original_bgm(path, duration, sample_rate=22050):
    """Synthesize a simple 96 BPM instrumental loop; no samples or external songs."""
    if duration <= 0:
        raise ValueError("BGM duration must be positive")
    rng = random.Random(2026)
    beat = 60 / 96
    chords = ((60, 64, 67, 71), (57, 60, 64, 67), (53, 57, 60, 64), (55, 59, 62, 67))
    melody = (76, 79, 81, 79, 76, 74, 72, 74)
    frequency = lambda note: 440 * 2 ** ((note - 69) / 12)
    samples = array("h")
    for i in range(round(duration * sample_rate)):
        t = i / sample_rate
        beat_index = int(t / beat)
        phase = t % beat
        chord = chords[(beat_index // 8) % len(chords)]
        chord_phase = (t % (8 * beat)) / (8 * beat)
        pad = sum(math.sin(2 * math.pi * frequency(n) * t) for n in chord) * 0.028
        pad *= math.sin(math.pi * chord_phase) ** 0.25
        pluck = math.sin(2 * math.pi * frequency(melody[beat_index % len(melody)]) * t) * math.exp(-phase * 8) * 0.07
        bass = math.sin(2 * math.pi * frequency(chord[0] - 24) * t) * math.exp(-phase * 6) * 0.10
        kick = math.sin(2 * math.pi * 55 * phase) * math.exp(-phase * 25) * 0.13
        hat = rng.uniform(-1, 1) * math.exp(-phase * 85) * 0.025
        fade = min(1, t / 0.08, max(0, duration - t) / 0.15)
        samples.append(round(max(-0.95, min(0.95, (pad + pluck + bass + kick + hat) * fade)) * 32767))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())
    return Path(path)


def photo_frame(image, progress, index):
    ease = 0.5 - 0.5 * math.cos(math.pi * progress)
    zoom = 1.00 + 0.05 * (ease if index % 2 == 0 else 1 - ease)
    width, height = 1080 / zoom, 1920 / zoom
    x = (1080 - width) / 2
    y = (1920 - height) / 2
    return image.transform((1080, 1920), Image.Transform.EXTENT,
                           (x, y, x + width, y + height), resample=Image.Resampling.BICUBIC)


def render_lookbook(images, bgm, final, scene_seconds=5, fps=30):
    if not images or not 0 < scene_seconds <= 30:
        raise ValueError("圖片不可空白，每幕秒數需介於 0～30 秒")
    frame_count = max(1, round(scene_seconds * fps))
    duration = len(images) * frame_count / fps
    loaded = []
    for path in images:
        with Image.open(path) as image:
            loaded.append(ImageOps.fit(image.convert("RGB"), (1080, 1920), method=Image.Resampling.LANCZOS))
    fade = min(1.0, duration / 4)
    final = Path(final)
    log = final.parent / "render.log"
    command = ["ffmpeg", "-hide_banner", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", "1080x1920", "-r", str(fps), "-i", "-", "-stream_loop", "-1", "-i", str(bgm),
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-b:a", "160k",
               "-af", f"volume=0.65,afade=t=in:st=0:d={fade},afade=t=out:st={duration-fade}:d={fade}",
               "-t", str(duration), "-movflags", "+faststart", str(final)]
    transition = min(round(0.35 * fps), frame_count // 3)
    with log.open("wb") as stderr:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=stderr)
        try:
            for index, image in enumerate(loaded):
                next_frame = photo_frame(loaded[index + 1], 0, index + 1) if index + 1 < len(loaded) else None
                for frame_index in range(frame_count):
                    frame = photo_frame(image, frame_index / max(1, frame_count - 1), index)
                    remaining = frame_count - 1 - frame_index
                    if next_frame is not None and transition and remaining < transition:
                        alpha = 0.5 - 0.5 * math.cos(math.pi * (1 - remaining / transition))
                        frame = Image.blend(frame, next_frame, alpha)
                    process.stdin.write(frame.tobytes())
        finally:
            with contextlib.suppress(BrokenPipeError):
                process.stdin.close()
            process.wait()
    if process.returncode:
        raise RuntimeError(f"FFmpeg 合成失敗，請查看 {log.name}")
    return duration
