#!/usr/bin/env python3
"""Render a reviewed JSONL transcript and course2md screenshots as local HTML."""
from __future__ import annotations
import argparse
import base64
from bisect import bisect_right
import hashlib
import html
import json
import os
from pathlib import Path
from urllib.parse import quote


def esc(value):
    return html.escape(str(value),quote=True)


def clock(seconds):
    minutes,sec=divmod(int(seconds),60)
    return f'{minutes:02}:{sec:02}'


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--structured',required=True,help='course2md exports/structured.json')
    ap.add_argument('--reviewed',required=True,help='JSONL of start,end,text,uncertain')
    ap.add_argument('--video',required=True,help='original local video')
    ap.add_argument('--output',required=True)
    ap.add_argument('--title',required=True)
    ap.add_argument('--note',default='结合课程材料校对；未经逐句听辨，可能仍有错误。')
    args=ap.parse_args()
    source=Path(args.structured).resolve();video=Path(args.video).resolve();output=Path(args.output).resolve()
    if not video.is_file():raise FileNotFoundError(video)
    data=json.loads(source.read_text(encoding='utf8'));duration=float(data['duration']);sections=data['sections']
    if not sections:raise ValueError('No video sections')
    starts=[s['t'] for s in sections]
    if starts!=sorted(starts):raise ValueError('Video sections are out of order')
    speech=[json.loads(x) for x in Path(args.reviewed).read_text(encoding='utf8').splitlines() if x.strip()]
    speech.sort(key=lambda x:(x['start'],x['end']))
    if not speech:raise ValueError('No transcript segments')
    if any(not 0<=float(x['start'])<=float(x['end'])<=duration+.5 for x in speech):raise ValueError('Segment outside video')
    frames=source.parent.parent/'frames';images_by_hash={}
    for path in frames.glob('*.jpg'):
        images_by_hash[hashlib.sha256(path.read_bytes()).hexdigest()]=path
    images={i['id']:images_by_hash[i['sha256']] for i in data['images']}
    grouped=[[] for _ in sections]
    for row in speech:
        if row.get('text','').strip():grouped[max(0,bisect_right(starts,row['start'])-1)].append(row)
    url=quote(os.path.relpath(video,output.parent),safe='/')
    def line(row):
        text=esc(row['text'])
        if not row.get('uncertain'):return text
        start=max(0,float(row['start'])-2);end=min(duration,float(row['end'])+2)
        return (f'<span class="uncertain">【待听辨：{text}】'
                f'<button class="listen" type="button" data-start="{start:.3f}" data-end="{end:.3f}" aria-label="播放 {clock(row["start"])} 原音">▶ 听原音</button>'
                f'<a class="fallback" href="{url}#t={int(start)}" hidden>打开视频</a></span>')
    cards=[]
    for idx,sec in enumerate(sections):
        image_id=sec.get('image_id');figure=''
        if image_id:
            image=base64.b64encode(images[image_id].read_bytes()).decode('ascii')
            figure=f'<figure><button class="zoom" aria-label="放大 {clock(sec["t"])} 的画面"><img loading="lazy" src="data:image/jpeg;base64,{image}" alt="{esc(args.title)} {clock(sec["t"])} 画面"></button></figure>'
        chunks=[];current=[];size=0;last=None
        for row in grouped[idx]:
            if current and (row['start']-last>3 or size+len(row['text'])>210):chunks.append(current);current=[];size=0
            current.append(row);size+=len(row['text']);last=row['end']
        if current:chunks.append(current)
        paragraphs=[]
        for chunk in chunks:
            start=chunk[0]['start'];t=f'<a class="time" href="{url}#t={int(start)}">{clock(start)}</a>'
            paragraphs.append('<p>'+t+' '+''.join(line(x) for x in chunk)+'</p>')
        body='<div class="speech">'+''.join(paragraphs)+'</div>' if paragraphs else ''
        cards.append(f'<section class="scene"><h2><a href="{url}#t={int(sec["t"])}">{clock(sec["t"])}–{clock(sec["end"])}</a></h2>{figure}{body}</section>')
    doc='''<!doctype html><html lang="zh-Hans"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+esc(args.title)+'''</title><style>
:root{font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;color:#202c2a;background:#f5f6f2}*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:2rem clamp(1rem,3vw,3rem)}header{border-bottom:2px solid #286351;padding-bottom:1rem}h1{line-height:1.25}a{color:#286351;text-underline-offset:.2em}.meta{font-size:.9rem;line-height:1.7;color:#42524e}section{border-bottom:1px solid #d8e1da;padding:1.5rem 0}h2{font:650 .85rem ui-monospace,monospace}figure{margin:0;width:100%}.zoom{display:block;width:100%;padding:0;border:0;background:none;cursor:zoom-in}.zoom img{width:100%;height:auto;display:block;border:1px solid #d8e1da}.speech{font-size:1rem;line-height:1.85;overflow-wrap:anywhere}.speech p{margin:.8em 0}.time{font-size:.8rem}.uncertain{background:#fff5db;border-radius:3px}.listen{font:inherit;font-size:.82rem;color:#215b4a;background:#e1efe8;border:1px solid #90b8a3;border-radius:1rem;padding:.12rem .55rem;margin:0 .22rem;cursor:pointer;white-space:nowrap}.listen[aria-pressed="true"]{color:#fff;background:#286351}.fallback{font-size:.75rem;white-space:nowrap}#status{font-size:.9rem;color:#844c19}dialog{max-width:98vw;max-height:96vh;border:1px solid #d8e1da}dialog::backdrop{background:#16201de0}dialog img{max-width:95vw;max-height:84vh;object-fit:contain}dialog button{display:block;margin:0 0 .5rem auto}@page{size:A4 landscape;margin:10mm}@media print{body{background:#fff}main{padding:0}section{padding:9pt 0}figure{break-inside:avoid}.speech{font-size:10pt;line-height:1.6}img{max-height:135mm;object-fit:contain}dialog,.listen,.fallback,#status{display:none}}
</style><noscript><style>.fallback[hidden]{display:inline}</style></noscript></head><body><main><header><h1>'''+esc(args.title)+'''</h1><p class="meta"><a href="'''+url+'''#t=0">打开原视频</a> · 全长 '''+clock(duration)+''' · '''+esc(args.note)+'''</p><p class="meta">标记待听辨的文字可点「听原音」。</p><p id="status" role="status" aria-live="polite"></p></header>'''+''.join(cards)+'''</main><dialog id="preview"><form method="dialog"><button>关闭</button></form><img id="full" alt=""></dialog><audio id="audio" preload="none"></audio><script>
const d=document.querySelector('#preview'),v=document.querySelector('#full');document.querySelectorAll('.zoom').forEach(b=>b.addEventListener('click',()=>{v.src=b.querySelector('img').src;v.alt=b.querySelector('img').alt;d.showModal()}));d.addEventListener('click',e=>{if(e.target===d)d.close()});const audio=document.querySelector('#audio'),status=document.querySelector('#status');let active=null,clipEnd=0;function reset(){if(active){active.textContent='▶ 听原音';active.setAttribute('aria-pressed','false');active=null}}audio.addEventListener('timeupdate',()=>{if(active&&audio.currentTime>=clipEnd){audio.pause();reset()}});audio.addEventListener('ended',reset);document.querySelectorAll('.listen').forEach(button=>button.addEventListener('click',async()=>{if(active===button&&!audio.paused){audio.pause();reset();return}audio.pause();reset();status.textContent='';const start=Number(button.dataset.start);clipEnd=Number(button.dataset.end);active=button;button.textContent='■ 停止';button.setAttribute('aria-pressed','true');try{if(!audio.src)audio.src='''+json.dumps(url,ensure_ascii=False)+''';audio.currentTime=start;await audio.play()}catch(e){reset();button.parentElement.querySelector('.fallback').hidden=false;status.textContent='原音播放失败，请点击文字旁的「打开视频」。'}}));
</script></body></html>'''
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(doc,encoding='utf8')
    print(json.dumps({'output':str(output),'segments':len(speech),'scenes':len(sections),'uncertain':sum(bool(x.get('uncertain')) for x in speech)},ensure_ascii=False))
if __name__=='__main__':main()
