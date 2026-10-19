# 语义匹配混剪 · 本地版

口播音频 + 视频素材库 → AI 按句子语义匹配画面 → 字幕模板 → N 条成片 → 去重筛选。
全本地运行，基于 GitHub 开源项目整合：faster-whisper、open_clip、ffmpeg。无需 API Key，不花钱。

## 桌面版（推荐）

```bash
.venv/bin/python gui.py
```

- 视频素材库：选文件夹 → 点"重建索引"（长视频自动切成 8 秒子片段各自建索引）
- 口播音频文件夹：把 mp3/wav 丢进去，同名 txt 放口播文案（可选，用于校正字幕）
- 目标成片数量：比如 10
- 去重阈值：0% = 零重复（每条成片的重复率都会算出来列在报告里）
- 字幕风格：pop（爆款黄字）/ clean（简约白字）
- 点"开始生成"，成片进输出文件夹，通过筛选的在 `kept/` 里

## 命令行

```bash
# 1. 素材库建索引（加新素材后重跑）
.venv/bin/python index_library.py --library ./library
# 可选：library/tags.json 给素材写一句话描述，匹配更准
# {"KD-CG-121.jpg": "red polka dot gift bag"}

# 2. 写 manifest.json
{
  "library": "./library", "style": "pop", "output": "./output",
  "target_count": 10, "dup_threshold": 0.0, "topk": 3,
  "audios": [
    {"audio": "./media/voice01.mp3", "script": "./media/voice01.txt"},
    {"audio": "./media/voice02.mp3"}
  ]
}

# 3. 跑批
.venv/bin/python run_batch.py --manifest manifest.json
# 输出：output/<name>/final.mp4 + plan.json（配对表，可改完单独重渲染）
#       output/dedup_report.json（每条片子的最高重复率+和谁重复）
#       output/kept/（通过去重筛选的成片）
```

## 工作原理

1. **索引**：素材库每个视频/图片抽帧 → CLIP 图文向量；长视频按 8 秒窗口切分子片段各自向量化
2. **切句**：whisper 把口播切成带时间轴的句子（有文案 txt 则对齐校正文字）
3. **匹配**：每句文案的 CLIP 文本向量 ↔ 素材向量余弦相似度，挑最贴的画面；多变体时从 top-k 采样 + 避开已用素材，保证条条不一样
4. **渲染**：按句子时长剪接（图片给慢推镜），ASS 字幕模板烧录，9:16 输出
5. **去重**：两两计算素材源重叠秒数/总时长，超过阈值的成片被筛掉，报告列出每条的最高重复率

## 给朋友用的说明

- Mac 版：下载 MixCut-mac-arm64.dmg，拖进 Applications，双击运行
- 素材越多、文案差异越大，去重 0% 越容易达成；素材太少时可放宽阈值
- 英文文案匹配效果最好；中文文案可换多语言 CLIP 模型
