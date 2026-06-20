"""Render a recording to a real video file (.mp4 / .webm / .gif / ...).

`render_video(recording, out)` replays a `.cast` / `.ttyrec` / `.ans` / `.3a` recording into a
terminal, rasterizes each moment with the same chrome-free grid renderer the compositor uses,
and pipes the frames to ffmpeg. The render is *deterministic and faster-than-real-time*: it
feeds the recording's timestamped events up to each video frame's time, so a 10 s recording
becomes 10 s of video without waiting 10 s -- and the timing matches the original.

ffmpeg is resolved from a system `ffmpeg` on PATH or, failing that, the bundled binary from the
`imageio-ffmpeg` package (the `video` extra: `pip install 'tappty[video]'`). The container/codec
follow the output extension. Needs the `gui` (pygame) and `ansi` (pyte) extras too.
"""
from __future__ import annotations

import codecs
import os
import shutil
import subprocess


def _ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:  # fall back to the binary the imageio-ffmpeg wheel bundles
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class VideoWriter:
    """Streams raw RGB frames to ffmpeg, encoding to `path` (format by extension)."""

    def __init__(self, path, width, height, fps):
        exe = _ffmpeg_exe()
        if not exe:
            raise RuntimeError(
                "rendering to video needs ffmpeg -- install it on PATH (apt install ffmpeg / "
                "brew install ffmpeg) or run  pip install 'tappty[video]'  for a bundled build"
            )
        ext = os.path.splitext(path)[1].lower()
        args = [exe, "-y", "-loglevel", "error",
                "-f", "rawvideo", "-pixel_format", "rgb24",
                "-video_size", f"{width}x{height}", "-framerate", str(fps), "-i", "-"]
        if ext == ".gif":  # build + apply an optimized palette for a clean GIF
            args += ["-vf", "split[a][b];[a]palettegen[p];[b][p]paletteuse"]
        else:
            args += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p"]
            if ext in (".mp4", ".m4v", ".mov"):
                args += ["-movflags", "+faststart"]
        args.append(path)
        self._proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, frame):
        try:
            self._proc.stdin.write(frame)
        except BrokenPipeError:
            pass  # ffmpeg exited early; close() surfaces its stderr

    def close(self):
        if self._proc.stdin:
            self._proc.stdin.close()
        err = self._proc.stderr.read() if self._proc.stderr else b""
        if self._proc.wait() != 0:
            raise RuntimeError("ffmpeg failed:\n" + err.decode("utf-8", "replace").strip()[-800:])


def render_video(recording, out_path, fps=30, font_size=18, font_path=None, zoom=1.0,
                 speed=1.0, tail=1.0, max_seconds=None, crop=None):
    """Render `recording` (a .cast/.ttyrec/.ans/.3a path) to `out_path` (a video file).

    Options:
      fps          output frame rate.
      font_size    glyph size in points -- the main size/zoom control.
      font_path    a .ttf to render with (defaults to the bundled DejaVu Sans Mono).
      zoom         scale the finished frame by this factor (crisp nearest-neighbor, e.g. 2.0
                   for a sharp 2x video) without re-rendering glyphs.
      speed        playback speed multiplier (2 = twice as fast).
      tail         hold the final frame for this many seconds.
      max_seconds  cap the duration (required for a never-ending source).
      crop         `(col, row, cols, rows)` -- render only that region of the grid (area of
                   interest) instead of the whole screen.

    Returns `out_path`."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # rasterize off-screen
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    import pygame

    from tappty import compositor
    from tappty.pyte_terminal import PyteTerminal
    from tappty.session import Session
    from tappty.source import replay_source

    src = replay_source(recording, speed=1.0, loop=False)  # we do the timing ourselves
    term = PyteTerminal(src.width, src.height)
    sess = Session(term)  # used only for its snapshot() of the grid
    events = list(src._events())  # [(abs_seconds, data), ...]
    wire = getattr(src, "encoding", None)  # byte sources (ttyrec) decode; text sources don't
    decoder = codecs.getincrementaldecoder(wire)("replace") if wire else None

    end = events[-1][0] if events else 0.0
    span = end / max(speed, 1e-9) + tail
    if max_seconds is not None:
        span = min(span, max_seconds)
    nframes = max(1, int(span * fps) + 1)

    pygame.init()
    fp = font_path or (compositor.FONT_PATH if os.path.exists(compositor.FONT_PATH) else None)
    font = pygame.font.Font(fp, font_size)
    cw, chh = font.size("M")[0], font.get_linesize()
    if crop:  # area of interest: just this cell region, panned to its top-left
        col, row, ccols, crows = crop
        cols, rows, pan = ccols, crows, (col, row)
    else:
        cols, rows, pan = term.cols, term.rows, None
    width, height = cols * cw, rows * chh
    out_w, out_h = max(1, round(width * zoom)), max(1, round(height * zoom))
    surface = pygame.Surface((width, height))
    glyphs = {}
    writer = VideoWriter(out_path, out_w, out_h, fps)
    try:
        ei = 0
        for i in range(nframes):
            rec_t = (i / fps) * speed
            while ei < len(events) and events[ei][0] <= rec_t:
                data = events[ei][1]
                term.write(decoder.decode(data.encode("latin-1")) if decoder else data)
                ei += 1
            surface.fill(compositor.BG)
            blink_on = (i // max(1, fps // 2)) % 2 == 0  # ~1 Hz blink phase
            compositor.draw_terminal(surface, (0, 0, width, height), sess.snapshot(),
                                     font, glyphs, pan=pan, blink_on=blink_on)
            frame = pygame.transform.scale(surface, (out_w, out_h)) if zoom != 1.0 else surface
            writer.write(pygame.image.tobytes(frame, "RGB"))
    finally:
        writer.close()
        pygame.quit()
    return out_path
