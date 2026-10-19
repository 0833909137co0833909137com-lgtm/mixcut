#!/usr/bin/env python3
"""Build a CLIP embedding index for the video/image material library.

Usage:
    .venv/bin/python index_library.py --library ./library

Scans the library dir for videos/images, samples frames from videos,
encodes everything with CLIP ViT-B-32 and stores normalized embeddings
in library/index.npz + library/meta.json. Re-run after adding materials.
Optional library/tags.json maps material filename -> short description
(e.g. {"KD-CG-121.jpg": "red polka dot gift bag"}) which is blended into
the embedding to improve matching.
"""
import argparse
import json
import os
import subprocess
from util import ffmpeg_bin, ffprobe_bin, model_path
import sys

import numpy as np
from PIL import Image

MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
FRAMES_PER_SEG = 3


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def probe_duration(path):
    out = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def list_media(library):
    found = []
    for root, _, files in os.walk(library):
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in MEDIA_EXTS:
                found.append(os.path.join(root, f))
    return found


def sample_frames(path, tmpdir, t0=0.0, t1=None):
    """Return list of PIL images sampled from a video (or image file).

    For videos, FRAMES_PER_SEG frames are sampled evenly inside [t0, t1].
    Long videos are split into overlapping windows by iter_segments().
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in VIDEO_EXTS:
        return [Image.open(path).convert("RGB")]
    dur = probe_duration(path)
    t1 = dur if t1 is None else min(t1, dur)
    frames = []
    for i in range(FRAMES_PER_SEG):
        t = t0 + (t1 - t0) * (i + 0.5) / FRAMES_PER_SEG
        out = os.path.join(tmpdir, f"f{i}.jpg")
        run([ffmpeg_bin(), "-y", "-ss", f"{t:.2f}", "-i", path,
             "-frames:v", "1", "-q:v", "3", out])
        frames.append(Image.open(out).convert("RGB"))
    return frames


def iter_segments(path, seg_win, seg_stride, long_threshold):
    """Yield (seg_id_suffix, t0, t1, kind) for a media file.

    Images -> single full entry. Short videos -> single full entry.
    Long videos -> overlapping windows so the matcher can pick the most
    fitting portion instead of the whole clip.
    """
    ext = os.path.splitext(path)[1].lower()
    base = os.path.basename(path)
    if ext not in VIDEO_EXTS:
        yield ("", 0.0, 0.0, "image")
        return
    dur = probe_duration(path)
    if dur <= long_threshold:
        yield ("", 0.0, dur, "video")
        return
    t = 0.0
    while t < dur - 1.0:
        t1 = min(t + seg_win, dur)
        yield (f"#t{int(t)}-{int(t1)}", t, t1, "video_seg")
        if t1 >= dur:
            break
        t += seg_stride


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True, help="material library dir")
    ap.add_argument("--model", default="ViT-B-32", help="open_clip model name")
    ap.add_argument("--pretrained", default=model_path(), help="open_clip pretrained tag")
    ap.add_argument("--seg-win", type=float, default=8.0,
                    help="sub-segment window seconds for long videos")
    ap.add_argument("--seg-stride", type=float, default=4.0,
                    help="sub-segment stride seconds for long videos")
    ap.add_argument("--long-threshold", type=float, default=12.0,
                    help="videos longer than this are split into sub-segments")
    args = ap.parse_args(argv)

    import torch
    import open_clip

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[index] loading CLIP {args.model} on {device} ...", flush=True)
    model, _, preprocess = open_clip.create_model_and_transforms(
        args.model, pretrained=args.pretrained, device=device)
    model.eval()
    tokenizer = open_clip.get_tokenizer(args.model)

    media = list_media(args.library)
    if not media:
        print("[index] no media found, abort")
        sys.exit(1)
    print(f"[index] {len(media)} materials found", flush=True)

    tags = {}
    tags_path = os.path.join(args.library, "tags.json")
    if os.path.exists(tags_path):
        tags = json.load(open(tags_path, encoding="utf-8"))
        print(f"[index] loaded {len(tags)} manual tags")

    tmpdir = os.path.join(args.library, ".tmp_frames")
    os.makedirs(tmpdir, exist_ok=True)

    ids, embs, metas = [], [], []
    with torch.no_grad():
        for idx, path in enumerate(media):
            base = os.path.basename(path)
            for seg_suffix, t0, t1, kind in iter_segments(
                    path, args.seg_win, args.seg_stride, args.long_threshold):
                frames = sample_frames(path, tmpdir, t0, t1 if kind != "image" else None)
                batch = torch.stack([preprocess(im) for im in frames]).to(device)
                feats = model.encode_image(batch)
                feats = feats / feats.norm(dim=-1, keepdim=True)
                emb = feats.mean(dim=0)
                # blend manual tag text for better matching
                tag = tags.get(base, "").strip()
                if tag:
                    toks = tokenizer([tag]).to(device)
                    tfeat = model.encode_text(toks)
                    tfeat = tfeat / tfeat.norm(dim=-1, keepdim=True)
                    emb = 0.6 * emb + 0.4 * tfeat[0]
                emb = emb / emb.norm()
                mid = base + seg_suffix
                ids.append(mid)
                embs.append(emb.cpu().numpy())
                metas.append({"id": mid, "path": os.path.abspath(path), "kind": kind,
                              "src_start": t0, "src_end": t1, "parent": base})
            print(f"[index] {idx + 1}/{len(media)} {base}", flush=True)

    np.savez(os.path.join(args.library, "index.npz"),
             ids=np.array(ids), embeddings=np.stack(embs))
    json.dump(metas,
              open(os.path.join(args.library, "meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # cleanup temp frames
    for f in os.listdir(tmpdir):
        os.remove(os.path.join(tmpdir, f))
    os.rmdir(tmpdir)
    print(f"[index] done -> {args.library}/index.npz ({len(ids)} materials)")


if __name__ == "__main__":
    main()
