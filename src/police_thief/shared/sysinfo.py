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
import sys

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


def _windows_ram_gb() -> float | str:
    """Physical RAM via ctypes (stdlib) when os.sysconf is unavailable."""
    try:
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = _MemStatus()
        stat.dwLength = ctypes.sizeof(_MemStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return round(stat.ullTotalPhys / 1e9, 1)
    except Exception:
        pass
    return UNKNOWN


def _windows_cpu_brand() -> str:
    """CPU brand string from the registry (stdlib winreg), else ''."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        try:
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return str(value).strip()
        finally:
            winreg.CloseKey(key)
    except Exception:
        return ""


def detailed_hardware_spec() -> dict:
    """hardware_spec() enriched with real Windows values where the portable
    stdlib probes read 'unknown'. Additive and best-effort (never raises); the
    ahk-yosi path keeps using the plain hardware_spec()."""
    spec = hardware_spec()
    if platform.system() == "Windows":
        if spec.get("ram_gb") in (UNKNOWN, None):
            spec["ram_gb"] = _windows_ram_gb()
        brand = _windows_cpu_brand()
        if brand:
            spec["cpu_type"] = brand
        # platform.release() reports "10" even on Windows 11; use the build number
        # (>= 22000 == Windows 11) so the reported OS is accurate.
        rel = platform.release()
        try:
            build = getattr(sys, "getwindowsversion", lambda: None)()
            if build is not None and build.build >= 22000 and rel == "10":
                rel = "11"
        except Exception:
            pass
        spec["os"] = f"Windows {rel} (build {platform.version()})"
    return spec
