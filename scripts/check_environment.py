#!/usr/bin/env python3
"""Read-only inventory of the local course transcription environment."""
import argparse
import importlib.metadata
import json
import platform
from pathlib import Path
import shutil
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--work-dir', type=Path, required=True, help='existing directory where task cache will be created')
    p.add_argument('--model', type=Path, help='local Qwen3-ASR 0.6B model directory')
    p.add_argument('--course2md', type=Path, help='course2md executable')
    a = p.parse_args()
    free = shutil.disk_usage(a.work_dir).free if a.work_dir.is_dir() else None
    try:
        version = importlib.metadata.version('mlx-qwen3-asr')
    except importlib.metadata.PackageNotFoundError:
        version = None
    model_files = [p.name for p in a.model.iterdir()] if a.model and a.model.is_dir() else []
    def binary(name):
        available = shutil.which(name)
        bundled = a.course2md.parent / name if a.course2md else None
        return available or (str(bundled) if bundled and bundled.is_file() else None)
    result = {
        'platform': platform.platform(), 'machine': platform.machine(), 'python': sys.executable,
        'free_bytes': free, 'work_dir': str(a.work_dir),
        'ffmpeg': binary('ffmpeg'), 'ffprobe': binary('ffprobe'),
        'course2md': str(a.course2md) if a.course2md and a.course2md.is_file() else shutil.which('course2md'),
        'mlx_qwen3_asr_version': version,
        'model': str(a.model) if a.model and a.model.is_dir() else None,
        'model_has_config': 'config.json' in model_files,
        'model_has_safetensors': any(name.endswith('.safetensors') for name in model_files),
        'note': 'Inventory only; does not load model, validate speech recognition, or establish whether a GPU is free.'
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
