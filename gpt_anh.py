"""Gen ảnh bằng Codex (GPT image) theo file CSV gen ảnh, dùng tài khoản ChatGPT đang đăng nhập
trong extension Codex của VS Code (không cần API key).

  python gpt_anh.py --csv <bo-video>/gen-anh.csv [--only 1 3] [--force] [--dry]

Cột CSV: stt, ten_file, prompt (bắt buộc); ty_le, gui_kem (ảnh tham chiếu, ngăn bằng ;), luu_tai.
Ảnh lưu vào cột luu_tai, nếu trống thì vào anh/<ten_file> cạnh file CSV.
"""
import argparse
import csv
import glob
import os
import subprocess
import sys


def codex_exe():
    pattern = os.path.join(os.environ["USERPROFILE"], ".vscode", "extensions", "openai.chatgpt-*",
                           "bin", "windows-x86_64", "codex.exe")
    found = sorted(glob.glob(pattern), key=os.path.getmtime)
    if not found:
        sys.exit("Không tìm thấy codex.exe (cần extension Codex/ChatGPT của OpenAI trong VS Code).")
    return found[-1]


def load_rows(csv_path):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    csv_dir = os.path.dirname(os.path.abspath(csv_path))
    for row in rows:
        dest = row.get("luu_tai") or os.path.join("anh", row["ten_file"])
        row["luu_tai"] = os.path.join(csv_dir, dest)
    return rows


def gen_one(exe, row, img_dir):
    dest = row["luu_tai"]
    out_dir = os.path.dirname(dest)
    os.makedirs(out_dir, exist_ok=True)
    refs = [os.path.join(img_dir, n.strip()) for n in row.get("gui_kem", "").split(";") if n.strip()]
    missing = [r for r in refs if not os.path.exists(r)]
    if missing:
        raise FileNotFoundError(f"thiếu ảnh tham chiếu: {missing}")

    lines = ["Generate exactly ONE image with your image generation tool (do not write code, do not draw it yourself)."]
    if row.get("ty_le"):
        lines.append(f"Aspect ratio: {row['ty_le']}.")
    if refs:
        lines.append("Use the attached image(s) as reference: keep the same person, outfit, room, camera angle and "
                     "artwork exactly consistent with them.")
    lines += ["Image description:", row["prompt"], "",
              f"Then copy the generated PNG to this exact path (overwrite if it exists): {dest}",
              "Reply only with the final file path."]
    cmd = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "workspace-write", "-C", out_dir]
    for r in refs:
        cmd += ["-i", r]
    # prompt qua stdin: -i nhận nhiều file nên sẽ nuốt mất prompt nếu đặt sau nó
    res = subprocess.run(cmd, input="\n".join(lines), encoding="utf-8", errors="replace", capture_output=True,
                         check=False, timeout=900)
    if not os.path.exists(dest):
        log = (res.stdout or "") + (res.stderr or "")
        tail = "\n".join(l for l in log.strip().splitlines()[-15:])
        raise RuntimeError(f"Codex chạy xong nhưng không thấy file ảnh. Cuối log Codex:\n{tail}")
    print(f"  đã lưu {dest} ({os.path.getsize(dest) // 1024} KB)")


def run(csv_path, only=None, force=False, dry=False):
    rows = load_rows(csv_path)
    img_dir = os.path.join(os.path.dirname(os.path.abspath(csv_path)), "anh")
    exe = codex_exe()
    ok = True
    for row in rows:
        if only and row["stt"] not in only:
            continue
        print(f"[ảnh {row['stt']}] {row['ten_file']}")
        if os.path.exists(row["luu_tai"]) and not force:
            print("  đã có ảnh, bỏ qua (dùng --force để gen lại)")
            continue
        if dry:
            print(f"  --dry: sẽ gen, gửi kèm: {row.get('gui_kem') or '(không)'}")
            continue
        try:
            gen_one(exe, row, img_dir)
        except Exception as e:
            # dừng lại: ảnh sau thường cần ảnh trước làm tham chiếu
            print(f"  lỗi: {e}")
            ok = False
            break
    return ok


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    sys.exit(0 if run(a.csv, a.only, a.force, a.dry) else 1)


if __name__ == "__main__":
    main()
