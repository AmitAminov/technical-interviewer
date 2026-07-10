"""Tier-1 of the 2-tier realistic avatar: a seamless *idle* animation loop.

The realistic avatar used to be Wav2Lip lip-sync on a single *frozen* portrait —
correct mouth, dead everything-else. This module pre-renders (once per character,
cached to disk) a short seamless looping video in which the *whole head* drifts
with a subtle, life-like motion: a slow elliptical sway plus a gentle "breathing"
scale. Because the entire portrait is warped as one, the eyes, nose and every
other feature move together with the head — not just the mouth.

Tier-2 (`service.py`) then runs the existing Wav2Lip mouth-sync *on top of* this
looping video instead of the still image. Wav2Lip's `datagen` cycles the face
frames with `i % len(frames)`, so the idle loop is repeated for the full length
of each spoken line at zero extra per-line cost — the loop is generated once and
its face-detection is cached like any other input.

The motion is a pure CPU affine warp (OpenCV) of the source image: no GPU, no
extra model, no extra venv. It is intentionally *subtle* — enough to read as
"alive", small enough to stay clear of the uncanny valley. Learned blinks / gaze
would need a neural idle generator (e.g. LivePortrait); this is the safe,
self-contained tier that ships today.

CLI:
    python idle_loop.py <image> <out.mp4> [seconds] [fps]
"""
from __future__ import annotations

import math
import os
import sys
from typing import Optional

import cv2
import numpy as np

# Defaults tuned for a ~768x1024 3:4 portrait. Amplitudes are deliberately small:
# the goal is "quietly alive", not "bobbing head". A full sine period over the
# loop makes frame[N-1] -> frame[0] as smooth as any interior step, so the loop
# is seamless even though Wav2Lip wraps it with a hard `i % len(frames)`.
DEFAULT_SECONDS = 2.4
DEFAULT_FPS = 25.0
# Sway: elliptical translation of the whole head (pixels), rotation (degrees).
SWAY_X_PX = 5.0
SWAY_Y_PX = 3.0
SWAY_ROT_DEG = 0.7
# Breathing: tiny scale oscillation. Two periods per loop so it stays seamless
# and reads as a slow breath rather than a zoom.
BREATH_SCALE = 0.006


def _affine_for_phase(w: int, h: int, phase: float) -> np.ndarray:
    """Affine matrix for one loop phase in [0, 2*pi).

    Elliptical sway (translation), a small out-of-phase rotation, and a
    two-cycle breathing scale — all periodic in `phase`, so phase 0 and phase
    2*pi produce identical transforms and the loop closes seamlessly.
    """
    dx = SWAY_X_PX * math.sin(phase)
    dy = SWAY_Y_PX * math.sin(phase + math.pi / 2.0)  # quarter-cycle lag -> ellipse
    rot = SWAY_ROT_DEG * math.sin(phase + math.pi / 4.0)
    scale = 1.0 + BREATH_SCALE * math.sin(2.0 * phase)

    center = (w / 2.0, h / 2.0)
    m = cv2.getRotationMatrix2D(center, rot, scale)
    m[0, 2] += dx
    m[1, 2] += dy
    return m


def generate_idle_loop(
    image_path: str,
    out_mp4: str,
    seconds: float = DEFAULT_SECONDS,
    fps: float = DEFAULT_FPS,
) -> str:
    """Render a seamless idle-motion loop from a still portrait.

    Pure CPU. Overwrites `out_mp4`. Returns the output path. Raises on unreadable
    input or if no video writer backend is available.
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"could not read image: {image_path}")
    h, w = img.shape[:2]
    n_frames = max(2, int(round(seconds * fps)))

    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
    tmp = out_mp4 + ".tmp.mp4"
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        raise RuntimeError("cv2.VideoWriter failed to open (no mp4v backend?)")

    try:
        for i in range(n_frames):
            phase = 2.0 * math.pi * (i / n_frames)
            m = _affine_for_phase(w, h, phase)
            # BORDER_REFLECT hides the sub-pixel edge the warp exposes, so the
            # frame never shows a black seam even though the head has shifted.
            frame = cv2.warpAffine(
                img, m, (w, h),
                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101,
            )
            writer.write(frame)
    finally:
        writer.release()

    # Atomic-ish swap so a reader never sees a half-written file.
    if os.path.exists(out_mp4):
        os.remove(out_mp4)
    os.replace(tmp, out_mp4)
    return out_mp4


def idle_path_for(idle_dir: str, character: str) -> str:
    """Cache path for a character's idle loop (keyed by image basename)."""
    stem = os.path.splitext(os.path.basename(character))[0]
    return os.path.join(idle_dir, f"{stem}.mp4")


def ensure_idle_loop(
    image_path: str,
    idle_dir: str,
    character: str,
    seconds: float = DEFAULT_SECONDS,
    fps: float = DEFAULT_FPS,
) -> Optional[str]:
    """Return the cached idle loop for `character`, generating it if missing.

    Returns the path on success, or None if generation failed (caller should
    fall back to the still image).
    """
    out = idle_path_for(idle_dir, character)
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    try:
        return generate_idle_loop(image_path, out, seconds=seconds, fps=fps)
    except Exception:  # noqa: BLE001 - never let idle-gen break the pipeline
        return None


def main() -> None:
    image, out = sys.argv[1], sys.argv[2]
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_SECONDS
    fps = float(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_FPS
    path = generate_idle_loop(image, out, seconds=seconds, fps=fps)
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps_read = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    print(f"idle loop: {path}  frames={n}  fps={fps_read:.1f}")


if __name__ == "__main__":
    main()
