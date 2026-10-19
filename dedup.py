#!/usr/bin/env python3
"""Duplicate-rate report and filtering for generated videos.

Usage:
    .venv/bin/python dedup.py --plans output/job1/plan.json output/job2/plan.json \\
        --out report.json [--threshold 0.0] [--history-dir published/]

Each plan's used footage is modeled as (material, src_start, src_end) ranges.
dup(A,B) = seconds of A's footage also used by B / A's total seconds.
A video is kept when its max dup rate against every other video (and
history) <= threshold. Threshold 0.0 = zero duplication.
"""
import argparse
import glob
import json
import os


def plan_atoms(plan):
    """Flatten a plan into (parent_material, start, end) source ranges."""
    atoms = []
    total = 0.0
    for i, p in enumerate(plan):
        dur = p.get("slot_dur") or (plan[i + 1]["start"] - p["start"] if i + 1 < len(plan) else 0)
        if dur <= 0:
            dur = p["end"] - p["start"]
        total += dur
        parent = p.get("parent") or p["material_id"].split("#")[0]
        s0 = float(p.get("src_start", 0.0))
        atoms.append((parent, s0, s0 + dur, p["material_kind"]))
    return atoms, total


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def dup_rate(atoms_a, total_a, atoms_b):
    """Fraction of A's footage seconds also covered by B's ranges."""
    if total_a <= 0:
        return 0.0
    ov = 0.0
    for pa, a0, a1, ka in atoms_a:
        for pb, b0, b1, kb in atoms_b:
            if pa != pb:
                continue
            if ka == "image" or kb == "image":
                ov += min(a1 - a0, b1 - b0)  # same image counts fully
            else:
                ov += overlap(a0, a1, b0, b1)
    return min(1.0, ov / total_a)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=0.0)
    ap.add_argument("--history-dir", default=None,
                    help="dir with previously published plan.json files to dedup against")
    args = ap.parse_args(argv)

    items = []
    for pp in args.plans:
        plan = json.load(open(pp, encoding="utf-8"))
        # stash slot durations for stable computation
        for i, p in enumerate(plan):
            nxt = plan[i + 1]["start"] if i + 1 < len(plan) else None
            p["slot_dur"] = (nxt - p["start"]) if nxt else (p["end"] - p["start"])
        atoms, total = plan_atoms(plan)
        items.append({"plan_path": pp, "name": os.path.basename(os.path.dirname(pp)),
                      "atoms": atoms, "total": total})

    history = []
    if args.history_dir:
        for hp in glob.glob(os.path.join(args.history_dir, "*", "plan.json")):
            plan = json.load(open(hp, encoding="utf-8"))
            for i, p in enumerate(plan):
                nxt = plan[i + 1]["start"] if i + 1 < len(plan) else None
                p["slot_dur"] = (nxt - p["start"]) if nxt else (p["end"] - p["start"])
            atoms, total = plan_atoms(plan)
            history.append({"name": os.path.basename(os.path.dirname(hp)),
                            "atoms": atoms, "total": total})

    report = []
    for i, it in enumerate(items):
        worst, worst_vs = 0.0, None
        for j, other in enumerate(items):
            if i == j:
                continue
            d = dup_rate(it["atoms"], it["total"], other["atoms"])
            if d > worst:
                worst, worst_vs = d, other["name"]
        for h in history:
            d = dup_rate(it["atoms"], it["total"], h["atoms"])
            if d > worst:
                worst, worst_vs = d, h["name"] + " (history)"
        keep = worst <= args.threshold + 1e-9
        report.append({"name": it["name"], "plan_path": it["plan_path"],
                       "max_dup_rate": round(worst, 3),
                       "worst_vs": worst_vs, "kept": keep})

    json.dump(report, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[dedup] threshold={args.threshold:.0%}\n")
    print(f"{'video':<24} {'max dup':<9} {'vs':<24} keep")
    kept = 0
    for r in report:
        print(f"{r['name']:<24} {r['max_dup_rate']:<9.0%} {str(r['worst_vs']):<24} "
              f"{'YES' if r['kept'] else 'no'}")
        kept += r["kept"]
    print(f"\n[dedup] {kept}/{len(report)} kept -> {args.out}")


if __name__ == "__main__":
    main()
