"""Ghép các clip Muse thành video cuối bằng ffmpeg, theo file CSV gen video.

  python ghep.py --csv <bo-video>/gen-video.csv [--out <bo-video>/video/final.mp4]

Cột CSV dùng tới: luu_tai (clip), dung_giay (độ dài mong muốn của clip trong video cuối; trống = giữ nguyên),
che_do (tang_toc = tăng tốc cả clip cho vừa dung_giay, cat = giữ tốc độ và cắt phần đầu clip).
Mọi clip được đưa về 1080x1920, 30 fps; clip không có tiếng thì chèn khoảng lặng.
"""
import argparse
import csv
import json
import os
import subprocess
import sys


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                          "-of", "json", path], capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    return float(info["format"]["duration"]), has_audio


def atempo_chain(speed):
    # atempo chỉ nhận 0.5-2.0 mỗi tầng
    parts = []
    while speed > 2.0:
        parts.append("atempo=2.0")
        speed /= 2.0
    parts.append(f"atempo={speed:.4f}")
    return ",".join(parts)


def build(csv_path, out):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    csv_dir = os.path.dirname(os.path.abspath(csv_path))
    cmd = ["ffmpeg", "-y", "-v", "error"]
    filters, labels = [], []
    for i, row in enumerate(rows):
        clip = os.path.join(csv_dir, row.get("luu_tai") or os.path.join("video", f"doan{row['stt']}.mp4"))
        if not os.path.exists(clip):
            sys.exit(f"thiếu clip: {clip}")
        dur, has_audio = probe(clip)
        target = float(row["dung_giay"]) if row.get("dung_giay") else dur
        mode = row.get("che_do") or "tang_toc"
        cmd += ["-i", clip]
        if mode == "cat":
            v = f"[{i}:v]trim=0:{target},setpts=PTS-STARTPTS"
            a = f"[{i}:a]atrim=0:{target},asetpts=PTS-STARTPTS"
        else:
            speed = dur / target
            v = f"[{i}:v]setpts=PTS/{speed:.4f}"
            a = f"[{i}:a]{atempo_chain(speed)},asetpts=PTS-STARTPTS"
        v += ",scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1"
        if not has_audio:
            a = f"anullsrc=r=44100:cl=stereo,atrim=0:{target}"
        filters.append(f"{v}[v{i}]")
        filters.append(f"{a},aformat=sample_rates=44100:channel_layouts=stereo[a{i}]")
        labels.append(f"[v{i}][a{i}]")
        print(f"  clip {row['stt']}: {dur:.1f}s -> {target:.1f}s ({mode})")
    filters.append(f"{''.join(labels)}concat=n={len(rows)}:v=1:a=1[v][a]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    subprocess.run(cmd, check=True)
    print(f"đã ghép {out} ({probe(out)[0]:.1f}s)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.csv)), "video", "final.mp4")
    build(a.csv, out)


if __name__ == "__main__":
    main()
