"""Machine + code identity for the Step-0 declaration (task 6.2, Rules 24/53).

Best-effort by design: an exotic or locked-down machine must still be able to
play, so every probe degrades to "unknown" rather than raising. Stdlib only —
no psutil — and the GPU probe shells out with a short timeout because a missing
driver must never hang a match start.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess

UNKNOWN = "unknown"


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def gpu_info() -> tuple[str, str]:
    """(gpu_type, vram_gb) — 'unknown' when no driver is exposed."""
    if shutil.which("nvidia-smi"):
        raw = _run(["nvidia-smi", "--query-gpu=name,memory.total",
                    "--format=csv,noheader"])
        if raw:
            name, _, mem = raw.splitlines()[0].partition(",")
            return name.strip() or UNKNOWN, mem.strip() or UNKNOWN
    return UNKNOWN, UNKNOWN


def code_commit() -> str:
    """The exact commit that played this game — Rule 53 requires declaring it."""
    return _run(["git", "rev-parse", "HEAD"]) or UNKNOWN


def hardware_spec() -> dict:
    """Fields per the book's Step-0 payload; never raises."""
    gpu_type, vram = gpu_info()
    try:
        ram_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1)
    except (AttributeError, ValueError, OSError):
        ram_gb = UNKNOWN
    return {
        "os": f"{platform.system()} {platform.release()}".strip() or UNKNOWN,
        "cpu_type": platform.processor() or platform.machine() or UNKNOWN,
        "cpu_cores": os.cpu_count() or UNKNOWN,
        "cpu_freq_mhz": UNKNOWN,          # stdlib exposes no portable frequency
        "ram_gb": ram_gb,
        "gpu_type": gpu_type,
        "gpu_cores_or_cuda": "CUDA (core count not exposed by driver)"
                             if gpu_type != UNKNOWN else UNKNOWN,
        "vram_gb": vram,
    }
