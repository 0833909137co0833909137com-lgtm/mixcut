#!/usr/bin/env python3
"""Match each narration sentence to the most fitting library material.

Usage:
    .venv/bin/python match.py --library ./library --sentences sentences.json --out plan.json

Encodes sentences with CLIP's text encoder, cosine-similarity against the
material embeddings, then greedy assignment with rules:
  - never reuse the same material twice in a row (unless library has 1 item)
  - prefer materials not used in the last 3 picks when the library is big enough
Writes plan.json: [{start, end, text, material_id, material_path, score}]
Review/edit plan.json before rendering; render.py consumes it as-is.
"""
import argparse
import json
import os

import numpy as np
from util import model_path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True)
    ap.add_argument("--sentences", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="ViT-B-32")
    ap.add_argument("--pretrained", default=model_path())
    ap.add_argument("--topk", type=int, default=1,
                    help="sample pick from top-k matches (1=best only, >1 for diverse variants)")
    ap.add_argument("--seed", type=int, default=0,
                    help="random seed for variant sampling")
    ap.add_argument("--avoid", nargs="*", default=[],
                    help="prior plan.json files; materials used there are down-weighted")
    args = ap.parse_args(argv)

    import torch
    import open_clip

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, _ = open_clip.create_model_and_transforms(
        args.model, pretrained=args.pretrained, device=device)
    model.eval()
    tokenizer = open_clip.get_tokenizer(args.model)

    idx = np.load(os.path.join(args.library, "index.npz"))
    ids = [str(x) for x in idx["ids"]]
    mat_embs = idx["embeddings"]  # already L2-normalized
    meta = {m["id"]: m for m in json.load(open(os.path.join(args.library, "meta.json"),
                                              encoding="utf-8"))}

    sentences = json.load(open(args.sentences, encoding="utf-8"))
    texts = [s["text"] for s in sentences]

    with torch.no_grad():
        toks = tokenizer(texts).to(device)
        tfeats = model.encode_text(toks)
        tfeats = tfeats / tfeats.norm(dim=-1, keepdim=True)
        sims = (tfeats.cpu().numpy() @ mat_embs.T)  # (S, M)

    # materials used in prior variants -> penalize to force cross-video diversity
    used_before = set()
    for ap_ in args.avoid:
        try:
            for p in json.load(open(ap_, encoding="utf-8")):
                used_before.add(p["material_id"])
        except (OSError, ValueError):
            pass
    if used_before:
        print(f"[match] avoiding {len(used_before)} materials used in prior variants", flush=True)

    rng = np.random.default_rng(args.seed)
    n_mat = len(ids)
    plan, recent = [], []
    for i, s in enumerate(sentences):
        # penalize cross-variant reuse (keeps per-video dup rate low)
        scores = sims[i].copy()
        for m in range(n_mat):
            if ids[m] in used_before:
                scores[m] *= 0.25
        ranking = list(np.argsort(-scores))
        # candidate pool: top-k, minus recent-use violations
        pool = []
        for m in ranking[:max(args.topk, 1)]:
            if n_mat > 1 and m == (recent[-1] if recent else -1):
                continue  # no immediate repeat
            if n_mat >= len(sentences) + 2 and m in recent[-3:]:
                continue  # spread usage when library is big
            pool.append(m)
        if not pool:
            pool = ranking[:max(args.topk, 1)]
        # weighted sample by penalized similarity (higher score = more likely)
        w = np.array([max(0.01, scores[m]) for m in pool])
        w = w / w.sum()
        pick = int(rng.choice(pool, p=w)) if len(pool) > 1 else pool[0]
        mid = ids[pick]
        m = meta[mid]
        plan.append({
            "start": s["start"], "end": s["end"], "text": s["text"],
            "material_id": mid,
            "material_path": m["path"],
            "material_kind": m["kind"],
            "src_start": m.get("src_start", 0.0),
            "src_end": m.get("src_end", 0.0),
            "score": round(float(sims[i][pick]), 3),
        })
        recent.append(pick)

    json.dump(plan, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[match] done -> {args.out}\n")
    print(f"{'#' :<3} {'time' :<13} {'score' :<6} {'material' :<28} sentence")
    for i, p in enumerate(plan):
        print(f"{i+1:<3} {p['start']:.1f}-{p['end']:.1f}  {p['score']:<6} "
              f"{p['material_id']:<28} {p['text'][:60]}")
    print("\n[match] review plan.json and edit material_id/path if needed, then render.")


if __name__ == "__main__":
    main()
