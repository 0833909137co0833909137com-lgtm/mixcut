#!/usr/bin/env python3
"""Transcribe a voiceover into sentence-level segments with timestamps.

Usage:
    .venv/bin/python transcribe.py --audio voice.mp3 --out sentences.json [--script script.txt]

Uses faster-whisper (tiny model, CPU int8 = fast) with word timestamps,
then groups words into sentences. If --script is given, its sentences are
aligned 1:1 to the whisper segments in order (warns on count mismatch).
Output: [{"start": float, "end": float, "text": str}]
"""
import argparse
import json
import re

SENT_END = re.compile(r"[.!?…。！？]+$")


def split_script_sentences(text):
    parts = re.split(r"(?<=[.!?…。！？])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def words_to_sentences(words, max_chars=70):
    sentences, cur, cur_start = [], [], None
    for w in words:
        if cur_start is None:
            cur_start = w["start"]
        cur.append(w)
        txt = "".join(x["word"] for x in cur).strip()
        if SENT_END.search(w["word"]) or len(txt) >= max_chars:
            sentences.append({"start": cur_start, "end": w["end"], "text": txt})
            cur, cur_start = [], None
    if cur:
        sentences.append({"start": cur_start, "end": cur[-1]["end"],
                          "text": "".join(x["word"] for x in cur).strip()})
    return sentences


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--script", default=None, help="optional script txt for text correction")
    ap.add_argument("--model", default="tiny", help="whisper model size")
    ap.add_argument("--language", default="en")
    args = ap.parse_args(argv)

    from faster_whisper import WhisperModel
    print(f"[transcribe] loading whisper {args.model} ...", flush=True)
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(args.audio, word_timestamps=True,
                                   language=args.language, beam_size=1)

    words = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"word": w.word, "start": w.start, "end": w.end})
    sentences = words_to_sentences(words)
    print(f"[transcribe] whisper -> {len(sentences)} sentences", flush=True)

    if args.script:
        script_sents = split_script_sentences(open(args.script, encoding="utf-8").read())
        if len(script_sents) != len(sentences):
            print(f"[transcribe] WARNING: script has {len(script_sents)} sentences, "
                  f"whisper found {len(sentences)}; using whisper text", flush=True)
        else:
            for s, t in zip(sentences, script_sents):
                s["text"] = t
            print("[transcribe] script text aligned to whisper timing", flush=True)

    json.dump(sentences, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[transcribe] done -> {args.out}")
    for s in sentences:
        print(f"  [{s['start']:.1f}-{s['end']:.1f}] {s['text']}")


if __name__ == "__main__":
    main()
