"""Shared helpers: resource paths that work both from source and from a
PyInstaller-frozen .app, plus bundled ffmpeg / fonts lookup."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def is_frozen():
    return getattr(sys, "frozen", False)


def base_dir():
    """Dir holding bundled resources (models/, styles.yaml, fonts, ffmpeg)."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", HERE)
    return HERE


def resource_path(*parts):
    return os.path.join(base_dir(), *parts)


def ffmpeg_bin():
    bundled = resource_path("bin", "ffmpeg")
    if os.path.exists(bundled):
        return bundled
    return "ffmpeg"


def ffprobe_bin():
    bundled = resource_path("bin", "ffprobe")
    if os.path.exists(bundled):
        return bundled
    return "ffprobe"


def model_path():
    return resource_path("models", "clip-vit-b32-laion.bin")


def styles_path():
    return resource_path("styles.yaml")


def user_data_dir():
    """Writable dirs for the desktop app (library/media/output defaults)."""
    if is_frozen():
        d = os.path.expanduser("~/MixCut")
    else:
        d = HERE
    os.makedirs(d, exist_ok=True)
    return d


def setup_fonts():
    """Make bundled fonts visible to ffmpeg's libass via fontconfig."""
    fdir = resource_path("fonts")
    if os.path.isdir(fdir) and not os.environ.get("FONTCONFIG_PATH"):
        os.environ["FONTCONFIG_PATH"] = fdir
