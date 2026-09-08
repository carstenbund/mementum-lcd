"""The record sink — RGBA frames to a video file (implementation plan 0b.2).

A sink is a sibling of the DRM backend, not a new layer (proposal §14): it
receives a composited RGBA frame and sends it somewhere. This one sends it to
an encoder. The simplest useful form is piping raw frames to ffmpeg, which is
what this does — no library binding, no format guessing, one colour conversion
at the adapter and nowhere else.

Recording is not real-time (§22). A record node walks scene time in a loop and
is bound to no clock at all, so a ten-second scene takes as long as it takes and
rendering it twice produces the same file.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from mementum_node.core.framebuffer import Frame
from mementum_node.core.png import write_png

__all__ = ["FFmpegRecordSink", "PngSequenceSink", "ffmpeg_available", "ffmpeg_command"]


def ffmpeg_available(binary: str = "ffmpeg") -> bool:
    return shutil.which(binary) is not None


def ffmpeg_command(
    pattern: str, out_path: str, fps: float, binary: str = "ffmpeg", crf: int = 18
) -> list[str]:
    """The command that turns a PNG sequence into a video, so it can be printed
    when ffmpeg is missing rather than merely failing."""
    return [
        binary, "-y",
        "-framerate", f"{fps:g}",
        "-i", pattern,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", str(crf),
        out_path,
    ]


class FFmpegRecordSink:
    """Raw RGBA in, an encoded file out.

    Frames go straight down a pipe in the buffer's own layout; ffmpeg does the
    RGBA→YUV420 conversion, which is this adapter's single conversion.
    """

    wants_pixels = True

    def __init__(
        self,
        path: str,
        width: int,
        height: int,
        fps: float = 30.0,
        binary: str = "ffmpeg",
        crf: int = 18,
    ):
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.binary = binary
        self.crf = crf
        self.presented = 0
        self._process: subprocess.Popen | None = None

    def open(self) -> "FFmpegRecordSink":
        if not ffmpeg_available(self.binary):
            raise RuntimeError(
                f"{self.binary} not found. Install it (apt install ffmpeg), or record a "
                "PNG sequence with PngSequenceSink and encode later."
            )
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        self._process = subprocess.Popen(
            [
                self.binary, "-y",
                "-f", "rawvideo",
                "-pix_fmt", "rgba",
                "-s", f"{self.width}x{self.height}",
                "-framerate", f"{self.fps:g}",
                "-i", "-",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", str(self.crf),
                self.path,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self

    def present(self, frame: Frame | None, scene_time: float) -> None:
        if frame is None:
            raise ValueError("the record sink needs composited frames")
        if self._process is None:
            self.open()
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write(bytes(frame.data))
        self.presented += 1

    def close(self) -> None:
        if self._process is None:
            return
        if self._process.stdin is not None:
            self._process.stdin.close()
        self._process.wait()
        self._process = None


class PngSequenceSink:
    """Frames to numbered PNGs, plus the command that merges them.

    The fallback when ffmpeg is not installed, and useful in its own right: the
    sequence is the archival artefact and the video is a rendering of it.
    """

    wants_pixels = True

    def __init__(self, directory: str, prefix: str = "frame", fps: float = 30.0):
        self.directory = directory
        self.prefix = prefix
        self.fps = fps
        self.presented = 0
        os.makedirs(directory, exist_ok=True)

    def present(self, frame: Frame | None, scene_time: float) -> None:
        if frame is None:
            raise ValueError("the record sink needs composited frames")
        write_png(frame, os.path.join(self.directory, f"{self.prefix}_{self.presented:05d}.png"))
        self.presented += 1

    def close(self) -> None:
        pass

    @property
    def pattern(self) -> str:
        return os.path.join(self.directory, f"{self.prefix}_%05d.png")

    def merge_command(self, out_path: str, binary: str = "ffmpeg") -> list[str]:
        return ffmpeg_command(self.pattern, out_path, self.fps, binary)
