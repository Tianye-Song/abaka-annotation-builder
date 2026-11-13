"""Generate the synthetic sample data for the example projects.

The outputs are committed, so you only need this to regenerate them.
Requirements: macOS (`say` + `afconvert` for speech) and Pillow (images).

    python scripts/make_samples.py
"""
from __future__ import annotations

import random
import subprocess
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATE = 16000

# ------------------------------------------------------------------ audio
DIALOGUES = [
    [("A", "Hi, is this the front desk?"), ("B", "Yes it is. How can I help you today?"), ("A", "My room key stopped working.")],
    [("A", "Did you finish the quarterly report?"), ("B", "Almost. I just need the sales numbers."), ("A", "I will send them after lunch.")],
    [("B", "Welcome back. The usual coffee?"), ("A", "Yes please, but make it a large today."), ("B", "Coming right up.")],
    [("A", "What time does the next train leave?"), ("B", "In about twelve minutes, from platform four.")],
    [("B", "Can you hear me now?"), ("A", "Barely. You keep cutting out."), ("B", "Let me move closer to the window."), ("A", "Much better.")],
    [("A", "I think we should test the new release on Friday."), ("B", "Friday is risky. How about Wednesday instead?")],
]
VOICES = {"A": "Samantha", "B": "Daniel"}


def tts(text: str, voice: str, tmp: Path) -> bytes:
    aiff, wav = tmp / "x.aiff", tmp / "x.wav"
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1", str(aiff), str(wav)], check=True)
    with wave.open(str(wav)) as w:
        return w.readframes(w.getnframes())


def make_audio() -> None:
    out = ROOT / "projects" / "speaker-turns" / "data"
    out.mkdir(parents=True, exist_ok=True)
    silence = lambda s: b"\x00\x00" * int(RATE * s)  # noqa: E731
    with tempfile.TemporaryDirectory() as t:
        for n, dialogue in enumerate(DIALOGUES, 1):
            frames = silence(0.4)
            for speaker, text in dialogue:
                frames += tts(text, VOICES[speaker], Path(t)) + silence(0.5)
            with wave.open(str(out / f"dialogue_{n:02d}.wav"), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
                w.writeframes(frames)
    print(f"wrote {len(DIALOGUES)} clips to {out}")


# ------------------------------------------------------------------ images
def make_images() -> None:
    from PIL import Image, ImageDraw

    out = ROOT / "projects" / "street-objects" / "data"
    out.mkdir(parents=True, exist_ok=True)
    W, H = 640, 400
    for n in range(1, 8):
        rnd = random.Random(n)
        img = Image.new("RGB", (W, H), (150 + rnd.randint(0, 60), 200, 235))
        d = ImageDraw.Draw(img)
        sx = rnd.randint(450, 560)
        d.ellipse((sx, 30, sx + 60, 90), fill=(255, 215, 90))  # sun
        d.rectangle((0, 280, W, H), fill=(95, 95, 100))  # road
        d.rectangle((0, 260, W, 282), fill=(120, 170, 90))  # verge
        for x in range(0, W, 80):
            d.rectangle((x + 10, 335, x + 50, 341), fill=(240, 240, 240))
        for _ in range(rnd.randint(1, 3)):  # trees
            x = rnd.randint(20, W - 80)
            d.rectangle((x + 25, 190, x + 37, 265), fill=(110, 75, 40))
            d.ellipse((x, 120, x + 62, 210), fill=(50, 130 + rnd.randint(0, 40), 60))
        for _ in range(rnd.randint(1, 2)):  # people
            x = rnd.randint(30, W - 40)
            d.ellipse((x, 205, x + 18, 223), fill=(230, 190, 160))
            d.rectangle((x + 4, 223, x + 14, 255), fill=(rnd.randint(40, 200), 60, 140))
            d.line((x + 6, 255, x + 2, 275), fill=(40, 40, 40), width=3)
            d.line((x + 12, 255, x + 16, 275), fill=(40, 40, 40), width=3)
        for _ in range(rnd.randint(1, 3)):  # cars
            x, y = rnd.randint(0, W - 130), rnd.randint(290, 330)
            color = tuple(rnd.randint(40, 230) for _ in range(3))
            d.rounded_rectangle((x, y, x + 120, y + 35), 8, fill=color)
            d.rounded_rectangle((x + 25, y - 22, x + 90, y + 2), 6, fill=color)
            d.rectangle((x + 32, y - 17, x + 83, y - 2), fill=(200, 230, 250))
            for wx in (x + 15, x + 85):
                d.ellipse((wx, y + 25, wx + 22, y + 47), fill=(25, 25, 25))
        img.save(out / f"street_{n:02d}.png", optimize=True)
    print(f"wrote 7 images to {out}")


if __name__ == "__main__":
    make_audio()
    make_images()
