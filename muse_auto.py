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
CONFIG = os.path.join(ROOT, "config.json")
# config.json "browser": "opera" (mặc định) hoặc "chrome"; mỗi trình duyệt một profile và một cổng debug riêng.
# "profile"/"port" chọn profile khác (vd. chrome-profile-2, cổng 9335) để đăng nhập tài khoản Muse khác
_CFG = json.load(open(CONFIG, encoding="utf-8"))
BROWSER = _CFG.get("browser", "opera")
PROFILE_NAME = _CFG.get("profile", f"{BROWSER}-profile")
PROFILE = os.path.join(ROOT, PROFILE_NAME)
PORT = int(_CFG.get("port", 9334 if BROWSER == "chrome" else 9333))


def opera_exe():
    base = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Opera")
    versions = sorted(glob.glob(os.path.join(base, "*", "opera.exe")))
    return versions[-1] if versions else os.path.join(base, "opera.exe")


def chrome_exe():
    for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                 os.environ.get("LOCALAPPDATA", "")):
        path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
        if os.path.exists(path):
            return path
    sys.exit("Không tìm thấy chrome.exe")


def cdp_ready():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
        return True
    except OSError:
        return False


def start_opera(url):
    if not cdp_ready():
        subprocess.Popen([chrome_exe() if BROWSER == "chrome" else opera_exe(), f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
                          "--disable-quic", "--disable-background-timer-throttling",
                          "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
                          "--no-first-run", "--no-default-browser-check", url])
        for _ in range(60):
            if cdp_ready():
                break
            time.sleep(0.5)
        else:
            sys.exit(f"Không kết nối được {BROWSER} (cổng debug không mở).")


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
    print(f"{BROWSER} đã mở. Đăng nhập Muse (Opera: bật VPN nếu bị chặn IP). Phiên được lưu trong {PROFILE_NAME}/")


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


# Tìm ô video nằm SAU tin nhắn chứa `anchor` và TRƯỚC tin yêu cầu kế tiếp (dòng "Khung hình ĐẦU:").
# Không so "trước/sau khi gửi": khung chat Muse chỉ dựng các tin đang hiển thị, ô video cũ load muộn
# sẽ bị tưởng là mới (đã từng tải nhầm clip của tập trước).
TILES_AFTER_JS = """([anchor, pick, sel, ph, marker]) => {
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const hits = []; let n;
  while ((n = w.nextNode())) if (n.nodeValue.includes(anchor)) hits.push(n);
  if (!hits.length) return {found: false, tiles: []};
  const a = pick === 'last' ? hits[hits.length - 1] : hits[0];
  let stop = null;
  const w2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while ((n = w2.nextNode())) {
    if (n !== a && (a.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING) && n.nodeValue.includes(marker)) { stop = n; break; }
  }
  const inside = e => (a.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING) &&
                      (!stop || (stop.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_PRECEDING));
  const holders = [...document.querySelectorAll(ph)].filter(inside);
  if (holders.length) holders[0].scrollIntoView({block: 'center'});
  let undelivered = 0;
  const w3 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while ((n = w3.nextNode())) if (n.nodeValue.includes('Delivery not confirmed') && inside(n)) undelivered++;
  return {found: true, undelivered, generating: holders.length > 0, tiles: [...document.querySelectorAll(sel)].filter(inside).map(t => {
    const v = t.querySelector('video') || t.parentElement.querySelector('video');
    return {label: t.getAttribute('aria-label') || '', src: v ? (v.currentSrc || v.src || '') : ''};
  })};
}"""
MARKER = "Khung hình ĐẦU:"


def file_md5(data):
    import hashlib
    return hashlib.md5(data).hexdigest()


def wait_video(page, cfg, row, anchor, pick):
    """Chờ ô video Muse trả lời cho tin nhắn `anchor`, tải về row['luu_tai']; bỏ qua file trùng clip khác."""
    sel = cfg["selectors"]
    dest = row["luu_tai"]
    others = {}
    for f in glob.glob(os.path.join(os.path.dirname(dest), "*.mp4")):
        if os.path.abspath(f) != os.path.abspath(dest):
            with open(f, "rb") as fh:
                others[file_md5(fh.read())] = os.path.basename(f)
    rejected = set()
    deadline = time.time() + cfg.get("timeout_min", 40) * 60
    flagged_at = None
    while time.time() < deadline:
        r = page.evaluate(TILES_AFTER_JS, [anchor, pick, sel["result_tile"], sel["result_placeholder"], MARKER])
        # Muse báo "Delivery not confirmed" (mạng chập chờn) thì AI không nhận được yêu cầu (cả ảnh lẫn prompt):
        # báo cho run_row gửi lại nguyên tin yêu cầu kèm ảnh. Nhắn "render lại" không kèm ảnh thì Muse không gen được.
        if r.get("undelivered", 0) and not r.get("generating") and not any(t["src"] for t in r["tiles"]):
            if flagged_at is None:
                flagged_at = time.time()
            elif time.time() - flagged_at >= 30:
                raise DeliveryFailed(anchor)
        else:
            flagged_at = None
        for t in r["tiles"]:
            if not t["src"] or t["label"] in rejected:
                continue
            data = fetch_video(page, t["src"])
            dup = others.get(file_md5(data))
            if dup:
                print(f"  bỏ qua {t['label'][20:]}: trùng với {dup}")
                rejected.add(t["label"])
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
            print(f"  đã lưu {dest} ({len(data) // 1024} KB)")
            return True
        page.wait_for_timeout(15_000)
    raise TimeoutError("quá thời gian chờ Muse trả video")


class DeliveryFailed(Exception):
    """Muse báo 'Delivery not confirmed' cho tin yêu cầu và không gen gì."""


def fetch_video(page, src):
    if src.startswith("blob:"):
        b64 = page.evaluate("""async src => { const b = await (await fetch(src)).blob();
            return await new Promise(r => { const f = new FileReader();
              f.onload = () => r(f.result.split(',')[1]); f.readAsDataURL(b); }); }""", src)
        return base64.b64decode(b64)
    return page.request.get(src, timeout=300_000).body()


def build_message(row, cfg, job=""):
    def names(col):
        return [n.strip() for n in row.get(col, "").split(";") if n.strip()]
    lines = [
        f"Gen 1 video theo yêu cầu dưới đây ({cfg.get('video_spec', 'dọc 9:16, 10 giây')}). Mã việc: {job}",
        f"- {MARKER} dùng đúng ảnh {', '.join(names('khung_dau'))}.",
    ]
    if names("khung_cuoi"):
        lines.append(f"- Khung hình CUỐI: dùng đúng ảnh {', '.join(names('khung_cuoi'))}.")
    else:
        lines.append("- Không có khung hình cuối cố định: diễn biến và máy quay làm đúng theo prompt.")
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
    """Gửi 1 clip; Muse báo 'Delivery not confirmed' thì gửi lại nguyên tin (ảnh + prompt, mã việc mới)."""
    for attempt in range(cfg.get("delivery_retries", 3) + 1):
        try:
            return send_row(page, cfg, row, img_dir, dry)
        except DeliveryFailed:
            if attempt >= cfg.get("delivery_retries", 3):
                raise RuntimeError("Muse báo 'Delivery not confirmed' quá số lần gửi lại")
            print(f"  Muse báo 'Delivery not confirmed', gửi lại nguyên yêu cầu kèm ảnh (lần {attempt + 1})")


def send_row(page, cfg, row, img_dir, dry):
    sel = cfg["selectors"]
    # mặc định chạy ngầm: Playwright gửi qua cổng debug nên không cần kéo cửa sổ Chrome lên trước
    if cfg.get("hien_cua_so"):
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

    job = f"#job-{int(time.time())}-{row['stt']}"
    box = page.locator(sel["message"])
    box.fill(build_message(row, cfg, job))

    if dry:
        shot = os.path.join(ROOT, "_inspect", f"dry-{row['stt']}.png")
        os.makedirs(os.path.dirname(shot), exist_ok=True)
        page.screenshot(path=shot)
        print(f"  --dry: đã gán {len(paths)} ảnh (thiếu {len(missing)}) + tin nhắn, KHÔNG gửi. Ảnh chụp: {shot}")
        clear_composer(page, sel)
        return False
    box.press(sel.get("send_key", "Enter"))
    # xác nhận tin đã thật sự lên chat (từng có lần Enter không gửi, tool ngồi chờ suông)
    for _ in range(60):
        page.wait_for_timeout(1000)
        if page.evaluate(TILES_AFTER_JS, [job, "first", sel["result_tile"], sel["result_placeholder"], MARKER])["found"] \
                and not box.input_value().strip():
            break
    else:
        raise RuntimeError("bấm gửi nhưng tin nhắn không xuất hiện trong chat")
    print(f"  đã gửi cho Muse ({job}), đang chờ video...")
    return wait_video(page, cfg, row, job, "first")


def fetch_only(page, cfg, row):
    """Không gửi gì: tìm video Muse đã trả cho lần gửi gần nhất của clip này (theo dòng khung đầu)."""
    first = row.get("khung_dau", "").split(";")[0].strip()
    print("  chỉ tải: tìm câu trả lời cho lần gửi gần nhất...")
    return wait_video(page, cfg, row, f"{MARKER} dùng đúng ảnh {first}", "last")


def last_frame_of(rows, stt, img_dir):
    """Khung đầu "@cuoi:N": trích khung hình cuối của clip N (tới cat_den nếu đã cắt) vào anh/, trả về tên file.
    Clip sau bắt đầu đúng chỗ clip trước dừng, nên không cần ảnh khung cuối ép Muse (ép thì đồ hay hiện hàng loạt)."""
    src = next(r for r in rows if r["stt"] == stt)
    cut = src.get("cat_den")
    if not cut and os.path.exists(clip_qa_path(src)):
        with open(clip_qa_path(src), encoding="utf-8") as f:
            cut = json.load(f).get("cat_den")
    if not cut:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              src["luu_tai"]], capture_output=True, text=True, check=True).stdout
        cut = float(out.strip())
    # tên mang tên tập (thư mục cha của anh/) để Muse không lẫn ảnh giữa các tập
    name = f"{os.path.basename(os.path.dirname(os.path.abspath(img_dir)))}-clip{stt}-cuoi.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(float(cut) - 0.1, 0):.2f}", "-i", src["luu_tai"],
                    "-frames:v", "1", os.path.join(img_dir, name)], check=True)
    print(f"  khung đầu = khung cuối clip {stt} (giây {float(cut):.1f}): {name}")
    return name


def clip_qa_path(row):
    return os.path.splitext(row["luu_tai"])[0] + ".qa.json"


def check_and_fix(page, cfg, row, img_dir):
    """Kiểm tra clip vừa tải: đạt -> xong; lỗi chỉ ở cuối -> ghi cat_den để ghep.py cắt;
    lỗi giữa clip -> gửi lại Muse kèm cách sửa (tối đa clip_retries lần), rồi kiểm tra lại."""
    sys.path.insert(0, ROOT)
    import qa
    work = os.path.join(os.path.dirname(row["luu_tai"]), "qa")
    end_name = row.get("khung_cuoi", "").split(";")[0].strip()
    end = os.path.join(img_dir, end_name) if end_name else None
    fixes = []
    for attempt in range(cfg.get("clip_retries", 1) + 1):
        prompt = row["prompt"] + ("" if not fixes else " FIX FROM PREVIOUS ATTEMPT: " + " ".join(fixes))
        print(f"  QA clip ({cfg['clip_qa']}) đang kiểm tra...")
        res = qa.check_clip(row["luu_tai"], prompt, end, work, cfg["clip_qa"])
        res["lan_gen"] = attempt + 1
        with open(clip_qa_path(row), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        for l in res.get("loi", []):
            print(f"    - {l.get('giay')}s: {l.get('mo_ta')}")
        if res.get("dat"):
            print("  QA clip: ĐẠT" + (f", cắt ở giây {res['cat_den']:.1f}" if res.get("cat_den") else ""))
            return
        if attempt >= cfg.get("clip_retries", 1):
            print("  QA clip: CHƯA ĐẠT, hết lượt gen lại, giữ bản này")
            return
        fixes.append(res.get("sua_prompt", ""))
        print(f"  QA clip: CHƯA ĐẠT, gen lại với: {fixes[-1]}")
        old = row["luu_tai"] + f".lan{attempt + 1}.mp4"
        os.replace(row["luu_tai"], old)  # giữ bản lỗi để so, dọn khi chốt video
        run_row(page, cfg, dict(row, prompt=row["prompt"] + " FIX FROM PREVIOUS ATTEMPT: " + " ".join(fixes)),
                img_dir, False)


def find_chat_cfg(csv_dir):
    """muse-chat.json ở thư mục tập hoặc thư mục series (cha, ông): mỗi series một side chat riêng trên Muse."""
    for d in (csv_dir, os.path.dirname(csv_dir), os.path.dirname(os.path.dirname(csv_dir))):
        path = os.path.join(d, "muse-chat.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return path, json.load(f)
    return None, None


def use_series_profile(chat):
    """muse-chat.json có thể ghi "profile"/"port" riêng: mỗi series dùng profile (tài khoản Muse) của mình."""
    global PROFILE, PORT
    if chat and chat.get("profile"):
        PROFILE = os.path.join(ROOT, chat["profile"])
        PORT = int(chat.get("port", PORT))


def open_series_chat(page, cfg, chat_path, chat):
    sel = cfg["selectors"]
    if chat.get("url"):
        page.goto(chat["url"])
        page.wait_for_selector(sel["message"], timeout=60_000)
        print(f"  side chat: {chat.get('series', '')} ({chat['url']})")
        return
    page.goto(cfg["url"].rstrip("/") + "/thread/new")
    page.wait_for_selector(sel["message"], timeout=60_000)
    intro = chat.get("intro") or (
        f"Side chat này dành riêng cho series video \"{chat.get('series', '')}\". Mình sẽ gửi lần lượt từng yêu cầu "
        f"gen video, mỗi tin nhắn 1 clip kèm ảnh. Tin này chỉ để mở chat, bạn trả lời ngắn \"OK\" là được.")
    box = page.locator(sel["message"])
    box.fill(intro)
    box.press(sel.get("send_key", "Enter"))
    for _ in range(60):
        page.wait_for_timeout(1000)
        if "/thread/" in page.url and not page.url.endswith("/new"):
            break
    else:
        raise RuntimeError("không lấy được địa chỉ side chat mới")
    chat["url"] = page.url
    with open(chat_path, "w", encoding="utf-8") as f:
        json.dump(chat, f, ensure_ascii=False, indent=2)
    print(f"  đã tạo side chat cho series {chat.get('series', '')}: {page.url}")
    page.wait_for_timeout(15_000)  # để Muse trả lời "OK" xong rồi mới gửi yêu cầu đầu tiên


def muse_page(ctx, url):
    for pg in ctx.pages:
        if "muse.ai" in pg.url:
            return pg
    pg = ctx.new_page()
    pg.goto(url)
    return pg


def cmd_run(cfg, csv_path, only, dry, force, img_dir, chi_tai=False, lam_lai=False, sua=""):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    csv_dir = os.path.dirname(os.path.abspath(csv_path))
    img_dir = img_dir or os.path.join(csv_dir, "anh")
    for row in rows:
        # cột luu_tai trống hoặc là đường dẫn tương đối -> tính theo thư mục chứa CSV
        dest = row.get("luu_tai") or os.path.join("video", f"doan{row['stt']}.mp4")
        row["luu_tai"] = os.path.join(csv_dir, dest)
        os.makedirs(os.path.dirname(row["luu_tai"]), exist_ok=True)
    chat_path, chat = find_chat_cfg(csv_dir)
    use_series_profile(chat)
    with sync_playwright() as p:
        _, ctx, _ = connect(p, cfg["url"])
        # series có thể đặt video_spec / reply_hint / clip_qa riêng (ví dụ khung ngang 16:9)
        cfg = {**cfg, **{k: chat[k] for k in ("video_spec", "reply_hint", "clip_qa") if chat and k in chat}}
        # dùng lại tab đang mở sẵn side chat của series (không mở tab mới, không tải lại nếu đã đúng chat)
        same = [pg for pg in ctx.pages if chat and chat.get("url") and pg.url.startswith(chat["url"])]
        # series có side chat thì không mượn tab Muse của series khác (nhiều series dùng chung một profile): mở tab mới
        page = same[0] if same else (ctx.new_page() if chat and chat.get("url") else muse_page(ctx, cfg["url"]))
        if chat and not same:
            open_series_chat(page, cfg, chat_path, chat)
        for row in rows:
            if only and row["stt"] not in only:
                continue
            print(f"[{row['stt']}] {row.get('doan', '')}")
            if row.get("khung_dau", "").startswith("@cuoi:") and not dry:
                row["khung_dau"] = last_frame_of(rows, row["khung_dau"][6:].strip(), img_dir)
            if lam_lai and not dry:
                # chủ dự án chọn tay clip cần làm lại: gửi lại yêu cầu đầy đủ (ảnh + prompt) kèm câu sửa, rồi QA lại từ đầu.
                # câu sửa: --sua, nếu không có thì lấy sua_prompt QA đã ghi trong clipN.qa.json
                fix = sua
                if os.path.exists(clip_qa_path(row)):
                    with open(clip_qa_path(row), encoding="utf-8") as f:
                        fix = fix or json.load(f).get("sua_prompt", "")
                    os.remove(clip_qa_path(row))
                if os.path.exists(row["luu_tai"]):
                    os.replace(row["luu_tai"], row["luu_tai"] + ".truoc.mp4")
                try:
                    run_row(page, cfg, dict(row, prompt=row["prompt"] + (" FIX FROM PREVIOUS ATTEMPT: " + fix if fix else "")),
                            img_dir, False)
                    if cfg.get("clip_qa"):
                        check_and_fix(page, cfg, row, img_dir)
                except Exception as e:
                    print(f"  lỗi: {e}")
                    return False
                continue
            have = os.path.exists(row["luu_tai"]) and not force and not dry
            if have and os.path.exists(clip_qa_path(row)):
                with open(clip_qa_path(row), encoding="utf-8") as f:
                    prev = json.load(f)
                if prev.get("dat") or prev.get("lan_gen", 1) > cfg.get("clip_retries", 1):
                    print("  đã có video và đã kiểm tra, bỏ qua (dùng --force để tạo lại)")
                    continue
            try:
                if not have:
                    fetch_only(page, cfg, row) if chi_tai else run_row(page, cfg, row, img_dir, dry)
                if not dry and cfg.get("clip_qa"):
                    check_and_fix(page, cfg, row, img_dir)
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
    ap.add_argument("--chi-tai", action="store_true", help="run: không gửi, chỉ tải video Muse đã trả cho lần gửi gần nhất")
    ap.add_argument("--lam-lai", action="store_true", help="run: gen lại các clip trong --only, gửi lại ảnh + prompt kèm câu sửa")
    ap.add_argument("--sua", default="", help="run --lam-lai: câu sửa lỗi (mặc định lấy sua_prompt trong clipN.qa.json)")
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
        cmd_run(cfg, a.csv, a.only, a.dry, a.force, a.anh, a.chi_tai, a.lam_lai, a.sua)


if __name__ == "__main__":
    main()
