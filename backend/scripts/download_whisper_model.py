"""Download Whisper model weights with resume + SHA256 check.

Usage (from backend/):
  python -m scripts.download_whisper_model
  python -m scripts.download_whisper_model --model base
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import urllib.request
from pathlib import Path

# Official URLs from openai-whisper
_MODELS: dict[str, str] = {
    "tiny": "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt",
    "base": "https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt",
    "small": "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt",
}


def _cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "whisper"


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def download_model(name: str, *, force: bool = False, retries: int = 8) -> Path:
    if name not in _MODELS:
        raise SystemExit(f"unknown model: {name}; choose from {list(_MODELS)}")
    url = _MODELS[name]
    expected = url.rstrip("/").split("/")[-2]
    root = _cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{name}.pt"
    part = root / f"{name}.pt.part"

    if target.exists() and not force:
        digest = _sha256_file(target)
        if digest == expected:
            print(f"[ok] {target} checksum match")
            return target
        print(f"[bad] {target} checksum mismatch, removing")
        target.unlink(missing_ok=True)

    if force:
        target.unlink(missing_ok=True)
        part.unlink(missing_ok=True)

    for attempt in range(1, retries + 1):
        try:
            existing = part.stat().st_size if part.exists() else 0
            headers = {"User-Agent": "whisper-download/1.0"}
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
                print(f"[try {attempt}/{retries}] resume from {existing} bytes")
            else:
                print(f"[try {attempt}/{retries}] download {name} …")

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                # 206 = partial; 200 = full (ignore Range)
                mode = "ab" if resp.status == 206 and existing > 0 else "wb"
                if mode == "wb" and existing > 0:
                    print("[info] server ignored Range, rewriting")
                    existing = 0
                total = resp.headers.get("Content-Length")
                total_i = int(total) + (existing if mode == "ab" else 0) if total else None
                done = existing if mode == "ab" else 0
                with part.open(mode) as out:
                    while True:
                        buf = resp.read(256 * 1024)
                        if not buf:
                            break
                        out.write(buf)
                        done += len(buf)
                        if total_i:
                            pct = 100.0 * done / total_i
                            print(f"\r  {done}/{total_i} ({pct:.1f}%)", end="", flush=True)
                print()

            digest = _sha256_file(part)
            if digest != expected:
                print(f"[bad] checksum {digest[:12]}… != {expected[:12]}…, will retry")
                # keep partial only if size suspiciously small; otherwise delete
                if part.stat().st_size < 50_000_000:
                    part.unlink(missing_ok=True)
                time.sleep(min(2 * attempt, 15))
                continue

            part.replace(target)
            print(f"[ok] saved {target}")
            return target
        except Exception as e:
            print(f"[err] {e}")
            time.sleep(min(2 * attempt, 15))

    raise SystemExit(f"failed to download {name} after {retries} tries")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="base", choices=list(_MODELS))
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    download_model(args.model, force=args.force)


if __name__ == "__main__":
    main()
