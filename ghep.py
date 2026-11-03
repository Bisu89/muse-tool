"""Ghép các clip Muse thành video cuối bằng ffmpeg, theo file CSV gen video.

  python ghep.py --csv <bo-video>/gen-video.csv [--out <bo-video>/video/final.mp4]

Cột CSV dùng tới: luu_tai (clip), dung_giay (độ dài mong muốn của clip trong video cuối; trống = giữ nguyên),
che_do (tang_toc = tăng tốc cả clip cho vừa dung_giay, cat = giữ tốc độ và cắt phần đầu clip).
--xfade GIÂY: chuyển cảnh mờ chồng giữa các clip (để cú cắt thời gian không trông như đồ vật tự hiện ra); mặc định nối thẳng.
Mọi clip được đưa về 30 fps và cùng khung với clip đầu: dọc 1080x1920, hoặc ngang 1920x1080 nếu clip đầu là ngang.
Clip không có tiếng thì chèn khoảng lặng.
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


def frame_size(path):
    """(rộng, cao) đích: ngang 1920x1080 nếu clip là ngang, còn lại dọc 1080x1920."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "json", path], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    return (1920, 1080) if s["width"] > s["height"] else (1080, 1920)


def atempo_chain(speed):
    # atempo chỉ nhận 0.5-2.0 mỗi tầng
    parts = []
    while speed > 2.0:
        parts.append("atempo=2.0")
        speed /= 2.0
    parts.append(f"atempo={speed:.4f}")
    return ",".join(parts)


def build(csv_path, out, xfade=0.0):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    csv_dir = os.path.dirname(os.path.abspath(csv_path))
    cmd = ["ffmpeg", "-y", "-v", "error"]
    filters, labels, lens = [], [], []
    size = None
    for i, row in enumerate(rows):
        clip = os.path.join(csv_dir, row.get("luu_tai") or os.path.join("video", f"doan{row['stt']}.mp4"))
        if not os.path.exists(clip):
            sys.exit(f"thiếu clip: {clip}")
        dur, has_audio = probe(clip)
        size = size or frame_size(clip)
        # QA từng clip có thể yêu cầu bỏ phần cuối bị lỗi (cat_den), cắt trước rồi mới tăng tốc
        qa_json = os.path.splitext(clip)[0] + ".qa.json"
        cut = None
        if os.path.exists(qa_json):
            with open(qa_json, encoding="utf-8") as f:
                cut = json.load(f).get("cat_den")
        # cột cat_tu / cat_den trong CSV (chủ dự án chọn tay) ưu tiên hơn cat_den do QA đề xuất
        if row.get("cat_den"):
            cut = float(row["cat_den"])
        start = float(row["cat_tu"]) if row.get("cat_tu") else 0.0
        end = min(dur, float(cut)) if cut else dur
        dur = end - start
        target = float(row["dung_giay"]) if row.get("dung_giay") else dur
        mode = row.get("che_do") or "tang_toc"
        cmd += ["-i", clip]
        if mode == "cat":
            target = min(target, dur)
            v = f"[{i}:v]trim={start}:{start + target},setpts=PTS-STARTPTS"
            a = f"[{i}:a]atrim={start}:{start + target},asetpts=PTS-STARTPTS"
        else:
            speed = dur / target
            v = f"[{i}:v]trim={start}:{end},setpts=(PTS-STARTPTS)/{speed:.4f}"
            a = f"[{i}:a]atrim={start}:{end},asetpts=PTS-STARTPTS,{atempo_chain(speed)}"
        w, h = size
        v += f",scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=30,setsar=1"
        if not has_audio:
            a = f"anullsrc=r=44100:cl=stereo,atrim=0:{target}"
        filters.append(f"{v}[v{i}]")
        filters.append(f"{a},aformat=sample_rates=44100:channel_layouts=stereo[a{i}]")
        labels.append(f"[v{i}][a{i}]")
        lens.append(target)
        print(f"  clip {row['stt']}: {start:.1f}-{end:.1f}s ({dur:.1f}s) -> {target:.1f}s ({mode})")
    if xfade > 0 and len(rows) > 1:
        # mỗi chỗ nối chồng xfade giây: offset = độ dài đã ghép trừ xfade
        v_prev, a_prev, total = "[v0]", "[a0]", lens[0]
        for i in range(1, len(rows)):
            d = min(xfade, lens[i - 1] / 2, lens[i] / 2)
            v_out = "[v]" if i == len(rows) - 1 else f"[vx{i}]"
            a_out = "[a]" if i == len(rows) - 1 else f"[ax{i}]"
            filters.append(f"{v_prev}[v{i}]xfade=transition=fade:duration={d:.3f}:offset={total - d:.3f}{v_out}")
            filters.append(f"{a_prev}[a{i}]acrossfade=d={d:.3f}{a_out}")
            v_prev, a_prev, total = v_out, a_out, total + lens[i] - d
    else:
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
    ap.add_argument("--xfade", type=float, default=0.0, help="giây chuyển cảnh mờ giữa các clip (mặc định 0 = nối thẳng)")
    a = ap.parse_args()
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.csv)), "video", "final.mp4")
    build(a.csv, out, a.xfade)


if __name__ == "__main__":
    main()
