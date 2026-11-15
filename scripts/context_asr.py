#!/usr/bin/env python3
"""Local Qwen3-ASR 0.6B with context, auditable chunks and safe resumption.

Input is mono 16 kHz PCM WAV. Optional speech intervals guide chunk boundaries;
all audio remains covered. This creates a draft, not a proofread transcript.
"""
from __future__ import annotations
import argparse
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import wave
import numpy as np


def norm(value):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', value).lower()


def context_echo(text, context):
    raw_context = context
    text, context = norm(text), norm(context)
    single_term = any(len(text) >= 3 and text == norm(term) for term in raw_context.split())
    return bool(context and (single_term or (len(text) >= 6 and
                (text in context or SequenceMatcher(None, text, context).ratio() > .72))))


def format_time(seconds):
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def make_ranges(duration, intervals, target=10.0, max_duration=14.0):
    """Partition the entire audio, choosing boundaries in known inter-speech gaps."""
    points = []
    items = sorted(intervals, key=lambda v: (v['start'], v['end']))
    for left, right in zip(items, items[1:]):
        if right['start'] >= left['end']:
            points.append((left['end'] + right['start']) / 2)
    ranges = []
    start = 0.0
    while duration - start > max_duration:
        candidates = [x for x in points if start + 5 <= x <= min(duration - 3, start + max_duration)]
        if candidates:
            cut = min(candidates, key=lambda x: abs(x - start - target))
            boundary_kind = 'speech_gap'
        else:
            cut = min(start + target, duration)
            overlapping = [x for x in items if x['start'] < cut < x['end']]
            alternatives = [point for x in overlapping for point in (x['start'], x['end'])
                            if start + 2 <= point <= min(duration - 1, start + max_duration + 2)
                            and not any(y['start'] < point < y['end'] for y in items)]
            if alternatives:
                cut = min(alternatives, key=lambda point: abs(point - cut))
                boundary_kind = 'speech_edge'
            else:
                boundary_kind = 'fixed_fallback'
        if cut <= start:
            raise ValueError('invalid chunk boundary')
        ranges.append({'start': round(start, 3), 'end': round(cut, 3), 'boundary': boundary_kind})
        start = round(cut, 3)
    ranges.append({'start': round(start, 3), 'end': round(duration, 3), 'boundary': 'end'})
    if abs(ranges[0]['start']) > .001 or abs(ranges[-1]['end'] - duration) > .002:
        raise ValueError('audio not fully covered')
    for a, b in zip(ranges, ranges[1:]):
        if abs(a['end'] - b['start']) > .001:
            raise ValueError('gap between chunks')
    return ranges


def load_intervals(path):
    if not path:
        return []
    p = Path(path)
    if p.suffix == '.jsonl':
        raw = [json.loads(line) for line in p.read_text(encoding='utf8').splitlines() if line.strip()]
    else:
        raw = json.loads(p.read_text(encoding='utf8'))
        if isinstance(raw, dict):
            raw = raw.get('segments', raw.get('ranges', []))
    unique = {}
    for x in raw:
        if 'start' not in x or 'end' not in x:
            continue
        start, end = float(x['start']), float(x['end'])
        if 0 <= start < end:
            unique[(round(start, 3), round(end, 3))] = {'start': start, 'end': end}
    return list(unique.values())


def context_for(start, end, ranges):
    terms = []
    for part in ranges:
        if part['end'] > start and part['start'] < end:
            for word in part['terms']:
                if word not in terms:
                    terms.append(word)
    return ' '.join(terms)


def course2md_running():
    """Yield between chunks if another course2md process is active."""
    result = subprocess.run(['/bin/ps', '-Ao', 'comm='], capture_output=True, text=True, check=True)
    return any(Path(line.strip()).name == 'course2md' for line in result.stdout.splitlines())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--audio', required=True, help='16 kHz mono signed 16-bit WAV')
    ap.add_argument('--model', required=True, help='local Qwen3-ASR 0.6B MLX model directory')
    ap.add_argument('--context-file', required=True, help='JSON object with ranges of {start,end,terms}')
    ap.add_argument('--boundaries', help='optional speech interval JSON or JSONL; only used to guide cuts')
    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--yield-to-course2md', action='store_true', help='exit 75 at a checkpoint when another course2md is running')
    args = ap.parse_args()
    out = Path(args.work_dir); out.mkdir(parents=True, exist_ok=True)
    audio = Path(args.audio).resolve(); model = Path(args.model).resolve()
    ctx_path = Path(args.context_file).resolve()
    ctx_data = json.loads(ctx_path.read_text(encoding='utf8'))
    contexts = ctx_data['ranges']
    for c in contexts:
        if not (0 <= float(c['start']) < float(c['end'])) or not isinstance(c['terms'], list):
            raise ValueError('invalid context range')
    with wave.open(str(audio), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('Expected mono 16-bit 16 kHz PCM WAV')
        sample_rate, sample_count = wav.getframerate(), wav.getnframes()
    duration = sample_count / sample_rate
    intervals = load_intervals(args.boundaries)
    ranges = make_ranges(duration, intervals)
    stat = audio.stat()
    identity = {'format_version': 1, 'audio':str(audio), 'size':stat.st_size, 'mtime_ns':stat.st_mtime_ns,
                'model':str(model), 'context_sha256':hashlib.sha256(ctx_path.read_bytes()).hexdigest(),
                'ranges':ranges}
    fingerprint = hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    state = out/'运行配置.json'; journal = out/'逐段原始识别.jsonl'
    if state.exists():
        old = json.loads(state.read_text(encoding='utf8'))
        if old.get('fingerprint') != fingerprint:
            raise ValueError('Existing checkpoint belongs to a different input/configuration')
    else:
        state.write_text(json.dumps({'fingerprint':fingerprint,'identity':identity},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    completed = {}
    if journal.exists():
        for line in journal.read_text(encoding='utf8').splitlines():
            if line.strip():
                row = json.loads(line); completed[row['index']] = row
    if any(i < 0 or i >= len(ranges) for i in completed):
        raise ValueError('Invalid checkpoint index')
    print(json.dumps({'stage':'prepared','duration':duration,'ranges':len(ranges),'resumed':len(completed)},ensure_ascii=False),flush=True)
    if args.yield_to_course2md and course2md_running():
        print(json.dumps({'stage':'yield','reason':'another course2md process is running'},ensure_ascii=False),flush=True)
        return 75
    from mlx_qwen3_asr import Session
    session = Session(model=str(model))
    with wave.open(str(audio), 'rb') as wav, journal.open('a', encoding='utf8') as log:
        for i, span in enumerate(ranges):
            if i in completed:
                continue
            if args.yield_to_course2md and course2md_running():
                print(json.dumps({'stage':'yield','done':len(completed),'total':len(ranges)},ensure_ascii=False),flush=True)
                return 75
            first=round(span['start']*sample_rate); last=min(sample_count,round(span['end']*sample_rate))
            wav.setpos(first); pcm=np.frombuffer(wav.readframes(last-first),dtype='<i2')
            if len(pcm) != last-first:
                raise RuntimeError('Incomplete WAV read')
            context=context_for(span['start'],span['end'],contexts)
            row={'index':i,**span,'context':context}
            if not np.any(pcm):
                row.update({'text':'','status':'digital_silence'})
            else:
                data=(pcm.astype(np.float32)/32768.0,sample_rate)
                text=session.transcribe(data,context=context,language='Chinese').text.strip()
                row['text']=text
                if context_echo(text,context):
                    row['without_context']=session.transcribe(data,context='',language='Chinese').text.strip()
                    row['status']='review_context_echo'
                else:
                    row['status']='needs_gpt_proofreading'
            log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush();completed[i]=row
            if (i+1)%20==0 or i+1==len(ranges):
                print(json.dumps({'stage':'transcribe','done':len(completed),'total':len(ranges),'time':round(span['end'],1)},ensure_ascii=False),flush=True)
    records=[completed[i] for i in range(len(ranges))]
    pending=sum(r['status']=='review_context_echo' for r in records)
    srt=[]
    for row in records:
        text=row.get('without_context',row['text']) if row['status']=='review_context_echo' else row['text']
        if text:
            srt.append(f'{len(srt)+1}\n{format_time(row["start"])} --> {format_time(row["end"])}\n{text}\n')
    outname='识别草稿_待内部复核.srt' if pending else '识别草稿.srt'
    (out/outname).write_text('\n'.join(srt),encoding='utf8')
    report={'duration':duration,'ranges':len(records),'context_echo':pending,
            'covered_seconds':round(sum(x['end']-x['start'] for x in records),3),
            'fallback_boundaries':sum(x['boundary']=='fixed_fallback' for x in records),
            'warning':'自动识别草稿；需结合课件逐段校对。可疑回显须先内部核查；两版均保留。'}
    (out/'识别审计.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'stage':'done',**report,'srt':str(out/outname)},ensure_ascii=False),flush=True)
    return 2 if pending else 0

if __name__ == '__main__':
    raise SystemExit(main())
