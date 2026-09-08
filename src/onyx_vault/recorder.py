"""Non-blocking microphone capture.

Runs sounddevice on a dedicated background thread so it never blocks the asyncio
event loop, slicing the live mic feed into 5-minute (300-second) WAV chunks and
handing each finished chunk's file path to the async processing queue.
"""

from __future__ import annotations

import asyncio
import threading
import time
import wave
from pathlib import Path
from typing import Optional

import sounddevice as sd

from onyx_vault.config import CHUNK_SECONDS, TEMP_DIR

CHUNK_FRAMES = 1024
AUDIO_DTYPE = "int16"
SAMPLE_WIDTH = 2  # bytes per sample for int16
CHANNELS = 1
SAMPLE_RATE = 16000


class AudioRecorder:
    """Captures microphone audio on a background thread into rolling WAV chunks."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue[Path]"):
        self._loop = loop
        self._queue = queue
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stream: Optional[sd.RawInputStream] = None
        self.is_recording = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="onyx-recorder")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=AUDIO_DTYPE,
            blocksize=CHUNK_FRAMES,
        )
        self._stream.start()
        self.is_recording = True
        try:
            frames_per_chunk = int(SAMPLE_RATE / CHUNK_FRAMES * CHUNK_SECONDS)
            while not self._stop_event.is_set():
                frames = []
                for _ in range(frames_per_chunk):
                    if self._stop_event.is_set():
                        break
                    data, _overflowed = self._stream.read(CHUNK_FRAMES)
                    frames.append(bytes(data))

                if not frames:
                    continue

                filepath = TEMP_DIR / f"chunk_{int(time.time() * 1000)}.wav"
                self._write_wav(filepath, frames)
                asyncio.run_coroutine_threadsafe(self._queue.put(filepath), self._loop)
        finally:
            self.is_recording = False
            self._stream.stop()
            self._stream.close()

    def _write_wav(self, filepath: Path, frames: list[bytes]) -> None:
        with wave.open(str(filepath), "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(b"".join(frames))
