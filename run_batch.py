#!/usr/bin/env python3
"""Batch driver: voiceovers + library -> N finished videos, dedup-filtered.

Manifest (manifest.json):
{
  "library": "./library",
  "style": "pop",
  "output": "./output",
  "target_count": 10,        # 目标成片数量
  "dup_threshold": 0.0,      # 去重阈值：0.0 = 零重复
  "topk": 3,                 # 匹配时从 top-k 候选里采样，多样化
  "history_dir": null,       # 已发布成片的 plan 目录（可选，防与历史重复）
  "audios": [
    {"audio": "./media/voice01.mp3", "script": "./media/voice01.txt"},
    {"audio": "./media/voice02.mp3"}
  ]
}

Pipeline per variant: transcribe (cached per audio) -> match(topk, seed,
avoid prior variants) -> render -> dedup report -> keep only videos
under threshold.

Runs in-process so the frozen desktop app can call main() directly.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import transcribe
import match as matcher
import render as renderer
import dedup
from util import styles_path


def step(label, fn, argv):
    print(f"\n===== {label} =====", flush=True)
    print("  $", os.path.basename(fn.__name__), " ".join(
        a if len(a) < 60 else a[:57] + "..." for a in argv), flush=True)
    fn.main(argv)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    args = ap.parse_args(argv)

    m = json.load(open(args.manifest, encoding="utf-8"))
    library = os.path.abspath(m.get("library", "./library"))
    style = m.get("style", "pop")
    out_root = os.path.abspath(m.get("output", "./output"))
    target = int(m.get("target_count", 1))
    dup_threshold = float(m.get("dup_threshold", 0.0))
    topk = int(m.get("topk", 3))
    history_dir = m.get("history_dir")
    audios = m["audios"]

    # 1. transcribe each audio once
    sent_files = {}
    for a in audios:
        audio = os.path.abspath(a["audio"])
        stem = os.path.splitext(os.path.basename(audio))[0]
        sfile = os.path.join(out_root, "_cache", f"{stem}.sentences.json")
        os.makedirs(os.path.dirname(sfile), exist_ok=True)
        if not os.path.exists(sfile):
            argv = ["--audio", audio, "--out", sfile]
            if a.get("script"):
                argv += ["--script", os.path.abspath(a["script"])]
            step(f"transcribe {stem}", transcribe, argv)
        sent_files[audio] = (stem, sfile, audio)

    # 2. generate target_count variants (round-robin over audios, seeds 0..n)
    plans = []
    aud_items = list(sent_files.items())
    for vi in range(target):
        audio, (stem, sfile, apath) = aud_items[vi % len(aud_items)]
        name = f"{stem}_v{vi + 1}"
        jdir = os.path.join(out_root, name)
        os.makedirs(jdir, exist_ok=True)
        plan = os.path.join(jdir, "plan.json")
        m_argv = ["--library", library, "--sentences", sfile,
                  "--out", plan, "--topk", str(topk), "--seed", str(vi)]
        if plans:
            m_argv += ["--avoid", *plans]
        step(f"variant {vi + 1}/{target}: {name} (seed {vi})", matcher, m_argv)
        step(f"render {name}", renderer,
             ["--plan", plan, "--audio", apath,
              "--out", os.path.join(jdir, "final.mp4"),
              "--style", style, "--styles", styles_path()])
        plans.append(plan)

    # 3. dedup report + filter
    d_argv = ["--plans", *plans,
              "--out", os.path.join(out_root, "dedup_report.json"),
              "--threshold", str(dup_threshold)]
    if history_dir:
        d_argv += ["--history-dir", os.path.abspath(history_dir)]
    step("dedup", dedup, d_argv)

    # 4. collect kept videos
    kept_dir = os.path.join(out_root, "kept")
    os.makedirs(kept_dir, exist_ok=True)
    report = json.load(open(os.path.join(out_root, "dedup_report.json"),
                            encoding="utf-8"))
    kept = [r for r in report if r["kept"]]
    for r in kept:
        src = os.path.join(os.path.dirname(r["plan_path"]), "final.mp4")
        shutil.copy(src, os.path.join(kept_dir, f"{r['name']}.mp4"))
    print(f"\n[batch] target={target} kept={len(kept)} (threshold {dup_threshold:.0%})")
    print(f"[batch] kept videos -> {kept_dir}")
    if len(kept) < target:
        print(f"[batch] NOTE: only {len(kept)} passed the dup filter; "
              f"add more materials or raise dup_threshold.")
    return kept


if __name__ == "__main__":
    main()
