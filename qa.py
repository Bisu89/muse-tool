"""QA video: kiểm tra kỹ thuật bằng ffprobe + cho GPT (Codex) và Claude chấm theo cùng một thang điểm.

  python qa.py --video <final.mp4> [--ref <video-goc.mp4>] [--csv <gen-video.csv>] [--chi gpt|claude]

Kết quả: thư mục qa/ cạnh video, gồm contact sheet, qa.json và qa-report.md.
"""
import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys

TIEU_CHI = [
    ("kich_ban", "Bám kịch bản: đủ các nhịp, đúng thứ tự, đúng nội dung từng clip"),
    ("nhat_quan", "Nhất quán: nhân vật, đồ vật, bối cảnh giữ nguyên giữa các clip"),
    ("chan_thuc", "Chân thực: không lỗi AI (tay/ngón méo, vật biến dạng, xuất hiện/biến mất vô lý, chữ lạ)"),
    ("chuyen_canh", "Chuyển cảnh: chỗ nối giữa các clip mượt, nhịp timelapse hợp lý"),
    ("hinh_anh", "Hình ảnh: bố cục dọc 9:16, ánh sáng, độ nét, màu"),
    ("giong_goc", "Giống video gốc: ý tưởng, các bước, khung cảnh, kết quả cuối (nếu có video gốc)"),
    ("hap_dan", "Hấp dẫn cho Reels/TikTok: hook mở đầu, cao trào/kết quả cuối đáng xem"),
]
DAT = 70  # điểm đạt trên thang 100
SO_O = 20


def find_exe(pattern):
    found = sorted(glob.glob(os.path.join(os.environ["USERPROFILE"], ".vscode", "extensions", pattern)),
                   key=os.path.getmtime)
    return found[-1] if found else None


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def ky_thuat(video):
    info = probe(video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    num, den = v["r_frame_rate"].split("/")
    dur = float(info["format"]["duration"])
    vol = subprocess.run(["ffmpeg", "-i", video, "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", vol)
    checks = {
        "do_phan_giai": (f"{v['width']}x{v['height']}", v["width"] == 1080 and v["height"] == 1920),
        "fps": (f"{float(num) / float(den):.0f}", float(num) / float(den) >= 24),
        "thoi_luong": (f"{dur:.1f}s", 8 <= dur <= 90),
        "am_thanh": (f"{m.group(1)} dB" if m else "không có", bool(m) and float(m.group(1)) > -50),
    }
    return dur, checks


def contact_sheet(video, out, dur):
    fps = SO_O / dur
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vf",
                    f"fps={fps:.4f},scale=270:-1,tile=5x4:padding=4:color=white", "-frames:v", "1", out], check=True)


def build_prompt(sheet, ref_sheet, dur, ref_dur, script):
    tc = "\n".join(f"- {k}: {d}" for k, d in TIEU_CHI)
    parts = [
        "Bạn là người kiểm duyệt chất lượng (QA) video ngắn AI cho Reels/TikTok. Chấm khắt khe, công bằng.",
        f"Ảnh '{os.path.basename(sheet)}' là contact sheet của VIDEO CẦN CHẤM: {SO_O} khung hình đều nhau theo "
        f"thời gian, đọc từ trái sang phải, trên xuống dưới, video dài {dur:.1f}s (mỗi ô ~{dur / SO_O:.1f}s).",
    ]
    if ref_sheet:
        parts.append(f"Ảnh '{os.path.basename(ref_sheet)}' là contact sheet của VIDEO GỐC cần làm theo "
                     f"({ref_dur:.1f}s), cùng cách đọc.")
    else:
        parts.append("Không có video gốc: tiêu chí giong_goc chấm theo mức bám ý tưởng kịch bản.")
    if script:
        parts.append("Kịch bản đã duyệt (từng clip):\n" + script)
    parts += [
        "Chấm từng tiêu chí từ 1 đến 10 (10 = hoàn hảo, 5 = dùng được nhưng lỗi rõ, 1 = hỏng):", tc,
        "Trả lời DUY NHẤT một khối JSON hợp lệ, không thêm chữ nào khác, theo dạng:",
        '{"diem": {"kich_ban": 0, "nhat_quan": 0, "chan_thuc": 0, "chuyen_canh": 0, "hinh_anh": 0, '
        '"giong_goc": 0, "hap_dan": 0}, "nhan_xet": {"kich_ban": "...", "...": "..."}, '
        '"loi_cu_the": ["mô tả lỗi kèm ô số mấy / giây thứ mấy"], "sua_gi_truoc": ["việc nên sửa, quan trọng nhất trước"]}',
        "Viết nhận xét bằng tiếng Việt, ngắn gọn.",
    ]
    return "\n\n".join(parts)


def parse_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("không tìm thấy JSON trong câu trả lời")
    data = json.loads(m.group(0))
    for k, _ in TIEU_CHI:
        data["diem"][k] = max(1, min(10, int(data["diem"].get(k, 0) or 1)))
    data["tong"] = round(sum(data["diem"].values()) * 100 / (10 * len(TIEU_CHI)))
    return data


def ask_gpt(prompt, images, work):
    exe = find_exe(os.path.join("openai.chatgpt-*", "bin", "windows-x86_64", "codex.exe"))
    if not exe:
        raise RuntimeError("không tìm thấy codex.exe")
    last = os.path.join(work, "gpt-raw.txt")
    cmd = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", work, "-o", last]
    for img in images:
        cmd += ["-i", img]
    subprocess.run(cmd, input=prompt, encoding="utf-8", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=900)
    with open(last, encoding="utf-8") as f:
        return parse_json(f.read())


def ask_claude(prompt, images, work):
    exe = find_exe(os.path.join("anthropic.claude-code-*", "resources", "native-binary", "claude.exe"))
    if not exe:
        raise RuntimeError("không tìm thấy claude.exe")
    files = "\n".join(f"- {p}" for p in images)
    full = f"Dùng công cụ Read để xem các ảnh sau trước khi chấm:\n{files}\n\n{prompt}"
    out = subprocess.run([exe, "-p", "--output-format", "text", "--allowedTools", "Read", "--add-dir", work],
                         input=full, encoding="utf-8", capture_output=True, cwd=work, timeout=900).stdout
    with open(os.path.join(work, "claude-raw.txt"), "w", encoding="utf-8") as f:
        f.write(out)
    return parse_json(out)


def report(video, dur, checks, results, out_md):
    lines = [f"# QA: {os.path.basename(video)}", "", f"Thời lượng {dur:.1f}s. Ngưỡng đạt: {DAT}/100.", "",
             "## Kiểm tra kỹ thuật", "", "| Mục | Giá trị | Đạt |", "|---|---|---|"]
    lines += [f"| {k} | {v} | {'✅' if ok else '❌'} |" for k, (v, ok) in checks.items()]
    names = list(results)
    lines += ["", "## Điểm chấm (1–10)", "", "| Tiêu chí | " + " | ".join(names) + " | TB |",
              "|---|" + "---|" * (len(names) + 1)]
    for k, d in TIEU_CHI:
        vals = [results[n]["diem"][k] for n in names]
        lines.append(f"| {d.split(':')[0]} | " + " | ".join(map(str, vals)) + f" | {sum(vals) / len(vals):.1f} |")
    tongs = [results[n]["tong"] for n in names]
    avg = sum(tongs) / len(tongs) if tongs else 0
    ky_thuat_ok = all(ok for _, ok in checks.values())
    lines.append("| **Tổng /100** | " + " | ".join(f"**{t}**" for t in tongs) + f" | **{avg:.0f}** |")
    ket = "ĐẠT" if avg >= DAT and ky_thuat_ok else "CHƯA ĐẠT"
    lines += ["", f"**Kết luận: {ket}**" + ("" if ky_thuat_ok else " (lỗi kỹ thuật)"), ""]
    for n in names:
        r = results[n]
        lines += [f"## Nhận xét của {n}", ""]
        lines += [f"- **{k}**: {r.get('nhan_xet', {}).get(k, '')}" for k, _ in TIEU_CHI]
        if r.get("loi_cu_the"):
            lines += ["", "Lỗi cụ thể:"] + [f"- {x}" for x in r["loi_cu_the"]]
        if r.get("sua_gi_truoc"):
            lines += ["", "Nên sửa trước:"] + [f"{i}. {x}" for i, x in enumerate(r["sua_gi_truoc"], 1)]
        lines.append("")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return avg, ket


def run(video, ref=None, csv_path=None, chi=None, out_dir=None):
    work = os.path.abspath(out_dir or os.path.join(os.path.dirname(os.path.abspath(video)), "qa"))
    os.makedirs(work, exist_ok=True)
    dur, checks = ky_thuat(video)
    sheet = os.path.join(work, "sheet-video.png")
    contact_sheet(video, sheet, dur)
    images, ref_sheet, ref_dur = [sheet], None, 0
    if ref:
        ref_dur = float(probe(ref)["format"]["duration"])
        ref_sheet = os.path.join(work, "sheet-goc.png")
        contact_sheet(ref, ref_sheet, ref_dur)
        images.append(ref_sheet)
    script = ""
    if csv_path:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            script = "\n".join(f"{r['stt']}. {r.get('doan', '')}: {r['prompt']}" for r in csv.DictReader(f))
    prompt = build_prompt(sheet, ref_sheet, dur, ref_dur, script)
    results = {}
    for name, fn in (("GPT", ask_gpt), ("Claude", ask_claude)):
        if chi and chi.lower() != name.lower():
            continue
        print(f"  {name} đang chấm...")
        try:
            results[name] = fn(prompt, images, work)
            print(f"  {name}: {results[name]['tong']}/100")
        except Exception as e:
            print(f"  {name} lỗi: {e}")
    with open(os.path.join(work, "qa.json"), "w", encoding="utf-8") as f:
        json.dump({"ky_thuat": checks, "ket_qua": results}, f, ensure_ascii=False, indent=1)
    avg, ket = report(video, dur, checks, results, os.path.join(work, "qa-report.md"))
    print(f"QA: {avg:.0f}/100, {ket}. Báo cáo: {os.path.join(work, 'qa-report.md')}")
    return avg, ket


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--ref", help="video gốc để so sánh")
    ap.add_argument("--csv", help="CSV gen video (kịch bản)")
    ap.add_argument("--chi", choices=["gpt", "claude"], help="chỉ cho một bên chấm")
    ap.add_argument("--out")
    a = ap.parse_args()
    run(a.video, a.ref, a.csv, a.chi, a.out)


if __name__ == "__main__":
    main()
