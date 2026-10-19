#!/usr/bin/env python3
"""MixCut 语义匹配混剪 - 本地桌面版.

Source: .venv/bin/python gui.py
Frozen (.app): double-click.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import index_library
import run_batch
from util import is_frozen, user_data_dir

AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")

if is_frozen():
    DATA = user_data_dir()
    DEF_LIB = os.path.join(DATA, "library")
    DEF_AUD = os.path.join(DATA, "media")
    DEF_OUT = os.path.join(DATA, "output")
else:
    DEF_LIB = os.path.join(HERE, "library")
    DEF_AUD = os.path.join(HERE, "media")
    DEF_OUT = os.path.join(HERE, "output")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("语义匹配混剪 · 本地版")
        self.geometry("760x620")
        self.log_q = queue.Queue()
        self._build()
        self.after(120, self._pump_log)

    def _build(self):
        pad = {"padx": 10, "pady": 6}
        f = ttk.Frame(self)
        f.pack(fill="x", **pad)

        ttk.Label(f, text="视频素材库").grid(row=0, column=0, sticky="w")
        self.lib_var = tk.StringVar(value=DEF_LIB)
        ttk.Entry(f, textvariable=self.lib_var, width=52).grid(row=0, column=1, sticky="we")
        ttk.Button(f, text="选择", command=self._pick_lib).grid(row=0, column=2)
        ttk.Button(f, text="重建索引", command=self._reindex).grid(row=0, column=3)

        ttk.Label(f, text="口播音频文件夹").grid(row=1, column=0, sticky="w")
        self.aud_var = tk.StringVar(value=DEF_AUD)
        ttk.Entry(f, textvariable=self.aud_var, width=52).grid(row=1, column=1, sticky="we")
        ttk.Button(f, text="选择", command=self._pick_aud).grid(row=1, column=2)
        self.aud_count = ttk.Label(f, text="")
        self.aud_count.grid(row=1, column=3)

        p = ttk.Frame(self)
        p.pack(fill="x", **pad)
        ttk.Label(p, text="目标成片数量").grid(row=0, column=0, sticky="w")
        self.count_var = tk.IntVar(value=5)
        ttk.Spinbox(p, from_=1, to=100, textvariable=self.count_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(p, text="去重阈值").grid(row=0, column=2, sticky="w", padx=(20, 0))
        self.dup_var = tk.StringVar(value="0%")
        ttk.Combobox(p, textvariable=self.dup_var, values=["0%", "10%", "20%", "30%"],
                     width=8, state="readonly").grid(row=0, column=3, sticky="w")
        ttk.Label(p, text="字幕风格").grid(row=0, column=4, sticky="w", padx=(20, 0))
        self.style_var = tk.StringVar(value="pop")
        ttk.Combobox(p, textvariable=self.style_var, values=["pop", "clean"],
                     width=8, state="readonly").grid(row=0, column=5, sticky="w")

        o = ttk.Frame(self)
        o.pack(fill="x", **pad)
        ttk.Label(o, text="输出文件夹").grid(row=0, column=0, sticky="w")
        self.out_var = tk.StringVar(value=DEF_OUT)
        ttk.Entry(o, textvariable=self.out_var, width=52).grid(row=0, column=1, sticky="we")
        ttk.Button(o, text="选择", command=self._pick_out).grid(row=0, column=2)
        ttk.Button(o, text="打开", command=self._open_out).grid(row=0, column=3)

        a = ttk.Frame(self)
        a.pack(fill="x", **pad)
        self.go_btn = ttk.Button(a, text="▶  开始生成", command=self._start)
        self.go_btn.pack(side="left")
        ttk.Button(a, text="打开输出文件夹", command=self._open_out).pack(side="left", padx=10)
        self.status = ttk.Label(a, text="就绪")
        self.status.pack(side="right")

        self.log = scrolledtext.ScrolledText(self, height=16, state="disabled")
        self.log.pack(fill="both", expand=True, padx=10, pady=6)

        r = ttk.Frame(self)
        r.pack(fill="x", **pad)
        ttk.Label(r, text="成片去重报告").pack(side="left")
        self.tree = ttk.Treeview(r, columns=("dup", "keep"), show="headings", height=5)
        self.tree.heading("dup", text="最高重复率")
        self.tree.heading("keep", text="保留")
        self.tree.column("dup", width=100)
        self.tree.column("keep", width=60)
        self.tree.pack(fill="x", expand=True)

        f.columnconfigure(1, weight=1)
        o.columnconfigure(1, weight=1)
        self._refresh_aud_count()

    # ---- helpers ----
    def _log(self, msg):
        self.log_q.put(msg)

    def _pump_log(self):
        while True:
            try:
                msg = self.log_q.get_nowait()
            except queue.Empty:
                break
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(120, self._pump_log)

    def _pick_lib(self):
        d = filedialog.askdirectory(initialdir=self.lib_var.get())
        if d:
            self.lib_var.set(d)

    def _pick_aud(self):
        d = filedialog.askdirectory(initialdir=self.aud_var.get())
        if d:
            self.aud_var.set(d)
            self._refresh_aud_count()

    def _refresh_aud_count(self):
        d = self.aud_var.get()
        n = sum(1 for f in os.listdir(d) if f.lower().endswith(AUDIO_EXTS)) if os.path.isdir(d) else 0
        self.aud_count.config(text=f"{n} 个音频")

    def _pick_out(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get())
        if d:
            self.out_var.set(d)

    def _open_out(self):
        d = self.out_var.get()
        os.makedirs(d, exist_ok=True)
        _open(d)

    def _reindex(self):
        lib = self.lib_var.get()
        if not os.path.isdir(lib):
            return messagebox.showerror("错误", "素材库文件夹不存在")
        self.go_btn.config(state="disabled")
        threading.Thread(target=self._do_reindex, args=(lib,), daemon=True).start()

    def _do_reindex(self, lib):
        try:
            self.status.config(text="索引中…")
            index_library.main(["--library", lib])
            self.status.config(text="索引完成")
            self._log("[gui] 素材库索引已重建")
            messagebox.showinfo("完成", "素材库索引已重建")
        except Exception as e:
            messagebox.showerror("失败", str(e))
        finally:
            self.go_btn.config(state="normal")

    def _start(self):
        lib, auddir, outdir = self.lib_var.get(), self.aud_var.get(), self.out_var.get()
        if not os.path.isdir(lib):
            return messagebox.showerror("错误", "素材库文件夹不存在")
        audios = []
        for fn in sorted(os.listdir(auddir)):
            if fn.lower().endswith(AUDIO_EXTS):
                base = os.path.splitext(fn)[0]
                job = {"audio": os.path.join(auddir, fn)}
                sp = os.path.join(auddir, base + ".txt")
                if os.path.exists(sp):
                    job["script"] = sp
                audios.append(job)
        if not audios:
            return messagebox.showerror("错误", "音频文件夹里没有音频文件")
        manifest = {
            "library": lib, "style": self.style_var.get(), "output": outdir,
            "target_count": int(self.count_var.get()),
            "dup_threshold": float(self.dup_var.get().strip("%") ) / 100.0,
            "topk": 3, "audios": audios,
        }
        mp = os.path.join(outdir, "manifest.json")
        os.makedirs(outdir, exist_ok=True)
        json.dump(manifest, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        self.go_btn.config(state="disabled")
        for row in self.tree.get_children():
            self.tree.delete(row)
        threading.Thread(target=self._do_run, args=(mp,), daemon=True).start()

    def _do_run(self, manifest):
        try:
            self.status.config(text="生成中…")
            run_batch.main(["--manifest", manifest])
            self.status.config(text="完成")
            self._show_report(os.path.join(self.out_var.get(), "dedup_report.json"))
            messagebox.showinfo("完成", "全部成片已生成，去重报告见下方列表")
        except Exception as e:
            messagebox.showerror("失败", str(e))
            self.status.config(text="失败")
        finally:
            self.go_btn.config(state="normal")

    def _show_report(self, path):
        if not os.path.exists(path):
            return
        for r in json.load(open(path, encoding="utf-8")):
            self.tree.insert("", "end", text=r["name"],
                             values=(f"{r['max_dup_rate']:.0%}", "✓" if r["kept"] else "✗"))


def _open(path):
    if sys.platform == "darwin":
        subprocess.run(["open", path])
    elif os.name == "nt":
        os.startfile(path)
    else:
        subprocess.run(["xdg-open", path])


if __name__ == "__main__":
    App().mainloop()
