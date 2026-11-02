"""Muse Auto: gửi lần lượt từng dòng trong file CSV cho Muse (muse.ai) qua khung chat web,
chờ Muse trả video rồi tải về. Chạy bằng Opera + Playwright, xem README.md.

Opera chạy với profile riêng (opera-profile/) nên chỉ cần đăng nhập Muse một lần.

  python muse_auto.py login                      # mở Opera để đăng nhập Muse (bật VPN của Opera nếu cần)
  python muse_auto.py run --csv <file.csv> --dry # gán ảnh + soạn tin nhắn nhưng KHÔNG gửi
  python muse_auto.py run --csv <file.csv>       # gửi thật, chờ video và tải về
  python muse_auto.py inspect --now              # chụp trang Muse khi giao diện đổi, để sửa selector

Selector của trang Muse nằm trong config.json.
"""
import argparse
import base64
import csv
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(ROOT, "opera-profile")
CONFIG = os.path.join(ROOT, "config.json")
PORT = 9333


def opera_exe():
    base = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Opera")
    versions = sorted(glob.glob(os.path.join(base, "*", "opera.exe")))
    return versions[-1] if versions else os.path.join(base, "opera.exe")


def cdp_ready():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
        return True
    except OSError:
        return False


def start_opera(url):
    if not cdp_ready():
        subprocess.Popen([opera_exe(), f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
                          "--disable-quic", "--disable-background-timer-throttling",
                          "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
                          "--no-first-run", "--no-default-browser-check", url])
        for _ in range(60):
            if cdp_ready():
                break
            time.sleep(0.5)
        else:
            sys.exit("Không kết nối được Opera (cổng debug không mở).")


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def connect(p, url):
    start_opera(url)
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return browser, ctx, page


def cmd_login(cfg):
    start_opera(cfg["url"])
    print("Opera đã mở. Bật VPN Opera nếu bị chặn IP, đăng nhập Muse. Phiên được lưu trong opera-profile/")


def cmd_inspect(cfg, out, now):
    with sync_playwright() as p:
        _, _, page = connect(p, cfg["url"])
        if not now:
            input("Mở tới trang tạo video trên Muse rồi bấm Enter ở đây... ")
        page = page.context.pages[-1]
        items = page.evaluate("""() => [...document.querySelectorAll(
            'input, textarea, button, [contenteditable=true], [role=button], video, select')].map(e => ({
              tag: e.tagName.toLowerCase(), type: e.type || '', id: e.id, name: e.name || '',
              cls: (e.className && e.className.baseVal === undefined ? e.className : '').slice(0, 80),
              placeholder: e.placeholder || '', aria: e.getAttribute('aria-label') || '',
              text: (e.innerText || '').trim().slice(0, 60), accept: e.accept || '',
              testid: e.getAttribute('data-testid') || '', src: (e.src || '').slice(0, 80)}))""")
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "muse-elements.json"), "w", encoding="utf-8") as f:
            json.dump({"url": page.url, "elements": items}, f, ensure_ascii=False, indent=1)
        with open(os.path.join(out, "muse-page.html"), "w", encoding="utf-8") as f:
            f.write(page.content())
        page.screenshot(path=os.path.join(out, "muse-page.png"), full_page=True)
        print(f"Đã lưu {len(items)} phần tử + ảnh chụp + HTML vào {out}")


def tile_labels(page, sel):
    return set(page.eval_on_selector_all(sel, "els => els.map(e => e.getAttribute('aria-label') || '')"))


def save_video(page, src, dest):
    if src.startswith("blob:"):
        b64 = page.evaluate("""async src => { const b = await (await fetch(src)).blob();
            return await new Promise(r => { const f = new FileReader();
              f.onload = () => r(f.result.split(',')[1]); f.readAsDataURL(b); }); }""", src)
        data = base64.b64decode(b64)
    else:
        data = page.request.get(src, timeout=300_000).body()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    print(f"  đã lưu {dest} ({len(data) // 1024} KB)")


def build_message(row, cfg):
    def names(col):
        return [n.strip() for n in row.get(col, "").split(";") if n.strip()]
    lines = [
        f"Gen 1 video theo yêu cầu dưới đây ({cfg.get('video_spec', 'dọc 9:16, 10 giây')}).",
        f"- Khung hình ĐẦU: dùng đúng ảnh {', '.join(names('khung_dau'))}.",
        f"- Khung hình CUỐI: dùng đúng ảnh {', '.join(names('khung_cuoi'))}.",
    ]
    if names("anh_tham_chieu"):
        lines.append(f"- Ảnh tham chiếu (giữ đúng nhân vật/chất liệu): {', '.join(names('anh_tham_chieu'))}.")
    if row.get("am_thanh"):
        lines.append(f"- Âm thanh: {row['am_thanh']}")
    lines += ["- Prompt:", row["prompt"], "", cfg.get("reply_hint", "Xong thì gửi lại file mp4 trong chat.")]
    return "\n".join(lines)


def clear_composer(page, sel):
    rm = page.locator(sel["remove_attachment"])
    for _ in range(20):
        if not rm.count():
            break
        try:
            rm.first.click(force=True, timeout=3000)
        except Exception:
            pass  # nút bị gỡ khỏi DOM giữa chừng do hiệu ứng; vòng sau thử lại
        page.wait_for_timeout(500)
    page.locator(sel["message"]).fill("")


def run_row(page, cfg, row, img_dir, dry):
    sel = cfg["selectors"]
    page.bring_to_front()
    page.wait_for_selector(sel["message"], timeout=60_000)
    clear_composer(page, sel)

    names = []
    for col in ("khung_dau", "khung_cuoi", "anh_tham_chieu"):
        names += [n.strip() for n in row.get(col, "").split(";") if n.strip() and n.strip() not in names]
    paths = [os.path.join(img_dir, n) for n in names]
    missing = [x for x in paths if not os.path.exists(x)]
    if missing and not dry:
        raise FileNotFoundError(f"thiếu ảnh: {missing}")
    paths = [x for x in paths if os.path.exists(x)]
    if paths:
        page.set_input_files(sel["attach_input"], paths)
        page.wait_for_timeout(cfg.get("upload_wait_ms", 8000))

    box = page.locator(sel["message"])
    box.fill(build_message(row, cfg))

    if dry:
        shot = os.path.join(ROOT, "_inspect", f"dry-{row['stt']}.png")
        os.makedirs(os.path.dirname(shot), exist_ok=True)
        page.screenshot(path=shot)
        print(f"  --dry: đã gán {len(paths)} ảnh (thiếu {len(missing)}) + tin nhắn, KHÔNG gửi. Ảnh chụp: {shot}")
        clear_composer(page, sel)
        return False
    before = tile_labels(page, sel["result_tile"])
    box.press(sel.get("send_key", "Enter"))
    print("  đã gửi cho Muse, đang chờ video...")
    deadline = time.time() + cfg.get("timeout_min", 40) * 60
    while time.time() < deadline:
        page.wait_for_timeout(15_000)
        new = [t for t in tile_labels(page, sel["result_tile"]) - before if t]
        if new:
            tile = page.locator(f'{sel["result_tile"]}[aria-label="{new[0]}"]')
            page.wait_for_timeout(5000)
            src = tile.evaluate("t => { const v = t.querySelector('video') || t.parentElement.querySelector('video');"
                                " return v ? (v.currentSrc || v.src) : ''; }")
            save_video(page, src, row["luu_tai"])
            return True
    raise TimeoutError("quá thời gian chờ Muse trả video")


def muse_page(ctx, url):
    for pg in ctx.pages:
        if "muse.ai" in pg.url:
            return pg
    pg = ctx.new_page()
    pg.goto(url)
    return pg


def cmd_run(cfg, csv_path, only, dry, force, img_dir):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    csv_dir = os.path.dirname(os.path.abspath(csv_path))
    img_dir = img_dir or os.path.join(csv_dir, "anh")
    for row in rows:
        # cột luu_tai trống hoặc là đường dẫn tương đối -> tính theo thư mục chứa CSV
        dest = row.get("luu_tai") or os.path.join("video", f"doan{row['stt']}.mp4")
        row["luu_tai"] = os.path.join(csv_dir, dest)
        os.makedirs(os.path.dirname(row["luu_tai"]), exist_ok=True)
    with sync_playwright() as p:
        _, ctx, _ = connect(p, cfg["url"])
        page = muse_page(ctx, cfg["url"])
        for row in rows:
            if only and row["stt"] not in only:
                continue
            print(f"[{row['stt']}] {row.get('doan', '')}")
            if os.path.exists(row["luu_tai"]) and not force and not dry:
                print("  đã có video, bỏ qua (dùng --force để tạo lại)")
                continue
            try:
                run_row(page, cfg, row, img_dir, dry)
            except Exception as e:
                # không gửi lại tự động: mỗi lần gửi là Muse gen thêm một video
                print(f"  lỗi: {e}")
                page.screenshot(path=os.path.splitext(row["luu_tai"])[0] + "-loi.png")
                return False
    return True


def cmd_auto(cfg, folder, dry, force):
    """Gen ảnh bằng Codex trước, đủ ảnh rồi mới gửi Muse gen video."""
    sys.path.insert(0, ROOT)
    import gpt_anh
    if not folder:
        sys.exit("cần --dir")
    csvs = glob.glob(os.path.join(folder, "*.csv"))
    anh_csv = [c for c in csvs if "anh" in os.path.basename(c).lower()]
    video_csv = [c for c in csvs if "video" in os.path.basename(c).lower()]
    if len(video_csv) != 1 or len(anh_csv) > 1:
        sys.exit(f"cần đúng 1 CSV video (*video*.csv) và tối đa 1 CSV ảnh (*anh*.csv) trong {folder}")
    if anh_csv:
        print("== Bước 1: gen ảnh bằng Codex ==")
        if not gpt_anh.run(anh_csv[0], force=force, dry=dry):
            sys.exit("Gen ảnh lỗi, dừng trước khi gửi Muse.")
    print("== Bước 2: gen video bằng Muse ==")
    if not cmd_run(cfg, video_csv[0], None, dry, force, None) or dry:
        return
    import ghep
    import qa
    final = os.path.join(folder, "video", "final.mp4")
    print("== Bước 3: ghép video ==")
    ghep.build(video_csv[0], final)
    print("== Bước 4: QA (GPT + Claude chấm điểm) ==")
    refs = glob.glob(os.path.join(folder, "goc.mp4"))
    qa.run(final, refs[0] if refs else None, video_csv[0])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["login", "inspect", "run", "auto"])
    ap.add_argument("--csv")
    ap.add_argument("--dir", help="auto: thư mục bộ video, chứa CSV gen ảnh (*anh*.csv) và CSV gen video (*video*.csv)")
    ap.add_argument("--anh", help="thư mục ảnh (mặc định: thư mục anh/ cạnh file CSV)")
    ap.add_argument("--only", nargs="*", help="chỉ chạy các stt này")
    ap.add_argument("--dry", action="store_true", help="gán ảnh + prompt nhưng không bấm tạo")
    ap.add_argument("--force", action="store_true", help="tạo lại kể cả khi đã có video")
    ap.add_argument("--now", action="store_true", help="inspect: chụp trang đang mở ngay, không chờ Enter")
    ap.add_argument("--out", default=os.path.join(ROOT, "_inspect"))
    a = ap.parse_args()
    cfg = load_config()
    if a.cmd == "login":
        cmd_login(cfg)
    elif a.cmd == "inspect":
        cmd_inspect(cfg, a.out, a.now)
    elif a.cmd == "auto":
        cmd_auto(cfg, a.dir, a.dry, a.force)
    else:
        if not a.csv:
            sys.exit("cần --csv")
        cmd_run(cfg, a.csv, a.only, a.dry, a.force, a.anh)


if __name__ == "__main__":
    main()
