# 本地术语提示识别

先阅读课件的文字、图表及代码；按视频时间范围整理与当段相关的术语，不要使用幻觉式补全。`context.json` 例子：

```json
{"ranges":[{"start":0,"end":600,"terms":["Visium","Stereo-seq","bin","spot"]},{"start":600,"end":1200,"terms":["SAW","StereoMap","Stereopy"]}]}
```

先检查项目的环境说明，优先使用已有的独立环境；缺少时安装 `mlx-qwen3-asr==0.4.4`，配置本地 0.6B MLX 模型。模型路径与课程缓存应由调用者指定，不修改、删除或覆盖共享模型和原视频。将视频音轨提取为与视频时间轴对齐的 16kHz、单声道、16-bit PCM WAV；检查音频起止和总时长（必要时用 `aresample=async=1:first_pts=0` 和 `apad` 处理时间差），不要默认为两者自动对齐。

```sh
python scripts/context_asr.py --audio lecture.wav --model /path/to/qwen3-asr-0.6b-mlx --context-file context.json --work-dir /path/to/task-cache
```

如已有同一视频的语音分段 JSON/JSONL，可用 `--boundaries` 提供时间边界以在句间切段；它仅供选切点，不使用旧字幕作为新识别结果。音频从头到尾连续覆盖，审计记录标出必要的固定切点。

脚本输出每段时间、实际 context、原始识别及状态；同一输入和参数可续跑。脚本默认中文；由 GPT 根据实际讲解自行选择语言，英语讲解时主动传 `--language English`，中文讲解带英文术语时继续使用中文。此脚本不会自动检测语言；判断需要结合音频样本与资料，必要时比较短片段。语言改变后不可复用旧检查点。完全数字静音不送模型；怀疑照抄术语时重跑无术语版本并保留两份，输出仅供内部核查的 `.待内部复核.srt` 并以退出码 2 停止。它不能识别所有幻觉，也不能判断可疑语音是否真的读出了术语；不要因低音量或关键词匹配而丢弃讲话。

该脚本单次运行只接受一种语言，不会自动逐段切换。确实需要按长时段切换时，分别处理各时段并使用独立检查点；将时间、术语表和分段边界换算回原视频绝对时间，检查接续、重叠及完整覆盖后再合并，禁止把相对时间直接当作原视频时间。

在 GPT 结合对应课件、截图、代码和上下文逐段校对后，为每个原始分段保留 index、start、end、text，并设置 `review_status` 为 `reviewed`、`uncertain`、`non_speech`、`digital_silence` 或 `filler_only`；只有 `uncertain` 设置 `uncertain: true`；对长句内的具体疑难内容，以 `uncertain_spans` 数组填写在该段原文中各自唯一出现的短句，页面只在该短句旁放播放按钮。以 JSONL 保存全部分段，再运行 `python scripts/export_reviewed_srt.py --source 逐段原始识别.jsonl --reviewed 逐段校对.jsonl --output 课程.srt`。没有信息量的口头填充词可删除；仅有填充词的分段标为 `filler_only` 并记录原因，脚本会检查原文确实不含其他文字。脚本核对时间范围、分段数量和空文本，避免不经说明地丢掉原识别内容。以视频与字幕同名的本地副本或链接让 course2md 使用 `--transcript-source subtitle` 截图和导入。不要在原始视频目录写入、覆盖现有字幕。SRT 是分段级时间，不等同于逐词对齐；关键画面切换时需要检查。每处最终仍无法确定的文本旁提供播放该段原音的按钮；不要把机器检测差异直接变成用户待听辨。

生成讲义：`python scripts/render_lecture.py --structured course2md/exports/structured.json --reviewed 逐段校对.jsonl --video 原视频.mp4 --output 图文讲义.html --title 课程名称`。图片等宽、字幕在下；标记为 uncertain 的具体文本旁提供播放对应视频片段的按钮。输出与视频保持可访问的相对位置，通过检查文件和链接确认依赖，无需播放音视频。
