#!/usr/bin/env python3
"""Render the final video from a match plan.

Usage:
    .venv/bin/python render.py --plan plan.json --audio voice.mp3 \
        --out final.mp4 --style pop [--styles styles.yaml]

Each plan entry becomes one clip trimmed to its narration slot
(slot extends to the next sentence start so video never gaps).
Images get a slow Ken Burns zoom; videos are trimmed/looped.
Subtitles are burned in from an ASS template (see styles.yaml).
"""
import argparse
import json
import os
import subprocess
from util import ffmpeg_bin, ffprobe_bin, setup_fonts
import sys

import yaml

W, H, FPS = 1080, 1920, 30


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("CMD FAILED:", " ".join(cmd), file=sys.stderr)
        print(r.stderr[-2000:], file=sys.stderr)
        raise SystemExit(1)


def probe_duration(path):
    out = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def available_font(preferred):
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=15)
        fams = out.stdout.lower()
        for f in [preferred, "DejaVu Sans", "Arial"]:
            if f.lower() in fams:
                return f
    except (OSError, subprocess.SubprocessError):
        pass
    return "DejaVu Sans"  # bundled with the app


def ass_time(sec):
    h = int(sec // 3600); m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(sentences, style, font):
    st = style
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: main,{font},{st['size']},{st['primary']},{st['primary']},{st['outline']},{st['back']},{-1 if st.get('bold') else 0},0,0,0,100,100,0,0,1,{st['outline_width']},{st.get('shadow', 0)},{st.get('alignment', 2)},30,30,{st.get('margin_v', 90)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for s in sentences:
        txt = s["text"].replace("\n", " ")
        lines.append(f"Dialogue: 0,{ass_time(s['start'])},{ass_time(s['end'])},main,,0,0,0,,{txt}")
    return "\n".join(lines)


def make_segment(src, kind, dur, seg_path, src_start=0.0, src_end=0.0):
    frames = max(1, int(round(dur * FPS)))
    if kind == "image":
        vf = (f"scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,"
              f"zoompan=z='1+0.10*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps={FPS}")
        run([ffmpeg_bin(), "-y", "-i", src, "-vf", vf,
             "-frames:v", str(frames), "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-preset", "veryfast", seg_path])
    else:
        vdur = probe_duration(src)
        pre = []
        # video_seg: use the matched window; plain video: middle slice
        ss = src_start if src_end > src_start else max(0.0, (vdur - dur) / 2)
        avail = vdur - ss
        if avail < dur:
            pre = ["-stream_loop", "3"]
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},fps={FPS}")
        run([ffmpeg_bin(), "-y", *pre, "-ss", f"{ss:.2f}", "-t", f"{dur:.2f}", "-i", src,
             "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-preset", "veryfast", seg_path])


def main(argv=None):
    setup_fonts()
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--style", default="pop")
    ap.add_argument("--styles", default="styles.yaml")
    args = ap.parse_args(argv)

    plan = json.load(open(args.plan, encoding="utf-8"))
    styles = yaml.safe_load(open(args.styles, encoding="utf-8"))["styles"]
    if args.style not in styles:
        raise SystemExit(f"unknown style '{args.style}', available: {list(styles)}")
    style = styles[args.style]
    font = available_font(style.get("font", "Arial"))
    print(f"[render] style={args.style} font={font}", flush=True)

    audio_dur = probe_duration(args.audio)
    workdir = os.path.join(os.path.dirname(os.path.abspath(args.out)), ".segs")
    os.makedirs(workdir, exist_ok=True)

    # slot durations: extend each clip to next sentence start (no gaps)
    slots = []
    for i, p in enumerate(plan):
        end = plan[i + 1]["start"] if i + 1 < len(plan) else audio_dur
        slots.append(max(0.5, end - p["start"]))

    seg_files = []
    for i, (p, dur) in enumerate(zip(plan, slots)):
        seg = os.path.join(workdir, f"seg{i:03d}.mp4")
        print(f"[render] clip {i+1}/{len(plan)} {p['material_id']} "
              f"({p['material_kind']}, {dur:.1f}s, score {p['score']})", flush=True)
        make_segment(p["material_path"], p["material_kind"], dur, seg,
                     p.get("src_start", 0.0), p.get("src_end", 0.0))
        seg_files.append(seg)

    lst = os.path.join(workdir, "list.txt")
    with open(lst, "w") as f:
        for s in seg_files:
            f.write(f"file '{s}'\n")
    combined = os.path.join(workdir, "combined.mp4")
    run([ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c", "copy", combined])

    ass_path = os.path.join(workdir, "subs.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(build_ass(plan, style, font))

    print("[render] muxing audio + burning subtitles ...", flush=True)
    run([ffmpeg_bin(), "-y", "-i", combined, "-i", args.audio,
         "-vf", f"ass={ass_path}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
         "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
         args.out])

    # cleanup intermediates (keep plan/ass for inspection)
    for s in seg_files + [combined, lst]:
        os.remove(s)
    print(f"[render] done -> {args.out} ({probe_duration(args.out):.1f}s)")


if __name__ == "__main__":
    main()
