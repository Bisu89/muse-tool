# Muse Auto

Tool chạy 4 bước:

1. **Gen ảnh bằng GPT qua Codex** (`gpt_anh.py`): dùng tài khoản ChatGPT đang đăng nhập trong extension Codex
   của VS Code, không cần API key.
2. **Gen video bằng Muse** (`muse_auto.py`): gửi ảnh và prompt cho Muse qua khung chat web, rồi tải từng clip về.
3. **Ghép** (`ghep.py`): tăng tốc hoặc cắt từng clip theo CSV, đưa về 1080×1920, 30 fps, rồi nối thành `video/final.mp4`.
4. **QA** (`qa.py`): kiểm tra kỹ thuật, sau đó cho **GPT và Claude** chấm điểm theo cùng một thang, xuất báo cáo.

Thả **thư mục bộ video** vào `4-tu-dong-het.bat` để chạy cả 4 bước liền nhau. Bước nào đã có kết quả
(ảnh, clip) thì tool bỏ qua.

## Quy trình làm một video mới (đã chạy thực tế với tập bàn chai resin)

1. **Phân tích video gốc.** Trích contact sheet bằng ffmpeg rồi viết danh sách nhịp có giây.
   Cảnh nào có chuyển cảnh lớn (ví dụ xưởng sang ban đêm) thì tách thành clip riêng.
2. **Gửi nội dung cho chủ dự án duyệt**, chờ trả lời đồng ý rõ ràng rồi mới gen.
3. **Viết 2 file CSV:**
   - Mỗi clip có một ảnh khung đầu và một ảnh khung cuối.
   - Ảnh khung cuối của clip trước chính là ảnh khung đầu của clip sau, để hai clip nối liền nhau.
   - Đặt tiền tố riêng cho tên file của mỗi tập (ví dụ `bt2-`). Muse từng nhầm khi gặp tên file trùng với một tập cũ.
4. **Gen ảnh** (`gpt_anh.py`), rồi **xem lại từng ảnh**: nhân vật, góc máy, số lượng đồ vật. Ảnh nào sai thì xóa
   ảnh đó rồi gen lại.
5. **Chép video gốc thành `goc.mp4`** trong thư mục bộ video để QA có cái so sánh.
6. Chạy `python muse_auto.py auto --dir <bo-video>`. Tool chạy tiếp Muse, ghép rồi QA. Mỗi clip Muse mất khoảng 2–5 phút.
7. **Đọc `video/qa/qa-report.md`.** Dưới 70 điểm thì sửa prompt của clip lỗi nặng nhất, xóa clip đó và `final.mp4`,
   rồi chạy lại `auto`. Tool chỉ gen lại những clip còn thiếu.
8. Chốt bản cuối thì dọn ảnh nháp, clip nháp và thư mục `qa/`, chỉ giữ `final.mp4`.

## Viết prompt để Muse ra video tốt

Rút ra từ bản đầu (QA 66/100) và các lỗi đã gặp:

- **Ít đồ vật thì AI xếp đúng hơn.** Với 22 chai, Muse xếp chồng chai và tự thêm chai. Với 12 chai, ghi rõ
  "EXACTLY 12 ..., one per slot, no stacking" thì Muse làm đúng hơn.
- **Ghi rõ vật lý của thao tác.** Ví dụ khi bóc khuôn: phải lật úp khuôn xuống bàn rồi mới bóc silicon. Resin rót lên
  trên chai rồi dâng đều, không rót vào lỗ giữa.
- **Ghi mốc giây cho từng thao tác** (0–4s, 4–10s) và thêm câu "The video must start exactly like the start-frame
  image and end exactly like the end-frame image".
- **Giữ mặt nhân vật trong khung hình** ("keep the woman's face in frame"). QA đã trừ điểm khi mặt bị cắt.
- **Clip cảnh kết hoặc cảnh khoe thành phẩm nên dài 8 giây trở lên.** Nén cảnh này còn 5 giây thì mất cú quay vòng.
- Muse xuất video 704×1248. `ghep.py` phóng lên 1080×1920.

## Bước 2: Muse

Tool gửi lần lượt từng dòng trong file CSV cho **Muse** (muse.ai, trợ lý AI của Meta) qua khung chat web.
Mỗi dòng sẽ được xử lý như sau:

1. Đính kèm ảnh (khung đầu, khung cuối, ảnh tham chiếu).
2. Soạn tin nhắn gồm prompt và mô tả âm thanh.
3. Bấm gửi.
4. Chờ Muse trả video trong chat.
5. Tải video về thư mục đã chỉ định.

Tool điều khiển **Opera** bằng Playwright. Opera của tool dùng profile riêng (`opera-profile/`),
tách biệt với Opera bạn dùng hằng ngày. Bạn chỉ cần đăng nhập Muse một lần.

## Cài đặt (một lần)

```
pip install -r requirements.txt
```

Không cần chạy `playwright install`, vì tool dùng Opera có sẵn trên máy
(`%LOCALAPPDATA%\Programs\Opera`).

## Đăng nhập (một lần)

1. Chạy `1-dang-nhap.bat`. Cửa sổ Opera của tool sẽ mở ra.
2. **Nếu Muse chặn IP:** vào `opera://settings/vpn` trong chính cửa sổ đó và bật VPN của Opera.
   Profile của tool sẽ nhớ cài đặt này.
3. Vào `https://muse.ai`, đăng nhập bằng số điện thoại hoặc email và nhập mã xác nhận.
   Vào tới khung chat là xong.

Phiên đăng nhập được lưu trong `opera-profile/`. Không chia sẻ thư mục này cho người khác,
vì nó chứa phiên đăng nhập tài khoản của bạn.

## Chuẩn bị một bộ video

Mỗi bộ video là một thư mục gồm:

```
<bo-video>/
├── gen-anh.csv       ← (tùy chọn) danh sách ảnh cần gen, xem mau/gen-anh.csv; tên file phải chứa "anh"
├── gen-video.csv     ← kịch bản, mỗi dòng 1 clip, xem mau/gen-video.csv; tên file phải chứa "video"
├── anh/              ← ảnh gen ra hoặc ảnh bạn tự bỏ vào (tên file phải khớp với CSV)
└── video/            ← tool tự tạo, video tải về nằm ở đây
```

### Các cột trong CSV gen ảnh

Ảnh được gen theo thứ tự `stt`. Ảnh sau có thể gửi kèm ảnh trước làm tham chiếu.

| Cột | Bắt buộc | Ý nghĩa |
|---|---|---|
| `stt` | có | Số thứ tự |
| `ten_file` | có | Tên file ảnh, sẽ lưu vào `anh/<ten_file>` |
| `prompt` | có | Mô tả ảnh (tiếng Anh cho kết quả tốt nhất) |
| `ty_le` | | `9:16`, `16:9`, `1:1`... |
| `gui_kem` | | Ảnh tham chiếu trong `anh/`; nhiều ảnh thì ngăn cách bằng `;` |
| `luu_tai` | | Ghi đè nơi lưu ảnh |

Lưu ý:
- Ảnh nào đã có thì tool bỏ qua. Muốn gen lại thì xóa ảnh đó hoặc dùng `--force`.
- Một ảnh bị lỗi thì tool dừng, vì các ảnh sau thường cần ảnh trước làm tham chiếu.
- Mỗi ảnh mất khoảng 1 phút và khoảng 12–15 nghìn token trong gói ChatGPT của bạn.
- Codex giữ một bản sao của mỗi ảnh trong `%USERPROFILE%\.codex\generated_images\`. Thư mục này có thể xóa định kỳ.

```
python gpt_anh.py --csv "<bo-video>\gen-anh.csv" [--only 2 3] [--force] [--dry]
```

### Các cột trong CSV gen video

| Cột | Bắt buộc | Ý nghĩa |
|---|---|---|
| `stt` | có | Số thứ tự clip, dùng với `--only` |
| `prompt` | có | Mô tả cảnh |
| `doan` | | Tên đoạn, chỉ để in ra màn hình |
| `khung_dau` | | Ảnh dùng làm khung hình đầu |
| `khung_cuoi` | | Ảnh dùng làm khung hình cuối |
| `anh_tham_chieu` | | Ảnh tham chiếu; nhiều ảnh thì ngăn cách bằng `;` |
| `am_thanh` | | Mô tả nhạc và âm thanh |
| `luu_tai` | | Nơi lưu mp4. Đường dẫn tương đối được tính theo thư mục chứa CSV. Để trống thì mặc định là `video/doan<stt>.mp4` |
| `dung_giay` | | Độ dài của clip này trong video cuối (bước ghép). Để trống thì giữ nguyên độ dài |
| `che_do` | | `tang_toc` (mặc định): tăng tốc cả clip cho vừa `dung_giay`. `cat`: giữ tốc độ, chỉ lấy phần đầu clip |

Tool đính kèm tất cả ảnh vào một tin nhắn, rồi ghi rõ ảnh nào là khung đầu, ảnh nào là khung cuối,
ảnh nào là tham chiếu. Câu chốt cuối tin nhắn và mô tả chung về video nằm trong `config.json`
(`reply_hint`, `video_spec`).

## Chạy

1. **Chạy thử trước:** kéo file CSV thả vào `2-chay-thu.bat`. Tool gán ảnh và soạn tin nhắn trong
   Opera, chụp màn hình vào `_inspect/dry-<stt>.png`, rồi **xóa đi mà không gửi**. Chạy thử không tốn lượt gen.
2. **Chạy thật:** kéo file CSV thả vào `3-chay-that.bat`. Tool gửi lần lượt từng dòng và chờ video
   (tối đa `timeout_min` phút cho mỗi clip), rồi tải về.

3. **Chạy cả hai bước:** kéo **thư mục** bộ video thả vào `4-tu-dong-het.bat`. Tool gen ảnh còn thiếu,
   sau đó gửi Muse. Nếu bước gen ảnh lỗi, tool dừng lại và không gửi Muse.

Bạn cũng có thể gõ lệnh trực tiếp:

```
python muse_auto.py auto --dir "D:\bo-video" --dry    # xem trước cả 2 bước, không gen gì
python muse_auto.py auto --dir "D:\bo-video"
python muse_auto.py run --csv "D:\bo-video\gen-video.csv" --dry
python muse_auto.py run --csv "D:\bo-video\gen-video.csv" --only 2      # chỉ chạy clip số 2
python muse_auto.py run --csv "..." --force                              # tạo lại kể cả khi đã có video
python muse_auto.py run --csv "..." --anh "D:\anh-khac"                  # dùng thư mục ảnh khác
```

Những điều nên biết khi chạy thật:

- Clip nào đã có file mp4 thì tool bỏ qua. Nhờ vậy nếu chạy lại sau khi bị lỗi, tool chỉ làm tiếp những clip còn thiếu.
- **Khi có lỗi, tool dừng lại và không tự gửi lại**, vì mỗi lần gửi là Muse gen thêm một video.
  Ảnh chụp lúc lỗi được lưu cạnh video với tên `doan<stt>-loi.png`.
- Muse là trợ lý AI nên đôi khi nó sẽ hỏi lại hoặc xin duyệt (tab Approvals) thay vì gửi video ngay.
  Khi đó bạn trả lời Muse trực tiếp trên cửa sổ Opera, tool vẫn tiếp tục chờ video.
- Khi tool đang chạy, đừng gõ vào khung chat Muse trong cửa sổ đó.

## Bước 3: ghép

```
python ghep.py --csv "<bo-video>\gen-video.csv" [--out "<bo-video>\video\final.mp4"]
```

Âm thanh được tăng tốc theo hình bằng `atempo`, nên cao độ giữ nguyên. Clip không có tiếng thì được chèn khoảng lặng.

## Bước 4: QA (GPT + Claude chấm điểm)

```
python qa.py --video "<bo-video>\video\final.mp4" --ref "<bo-video>\goc.mp4" --csv "<bo-video>\gen-video.csv"
python qa.py --video "..." --chi gpt        # chỉ cho một bên chấm
```

- **Kiểm tra kỹ thuật** (tự động, không tốn token): độ phân giải 1080×1920, fps từ 24 trở lên, thời lượng 8–90 giây,
  có âm thanh (lớn hơn -50 dB).
- **Contact sheet:** 20 khung hình đều nhau của video cần chấm, và của video gốc nếu có `--ref`.
- **Hai bên chấm độc lập:**
  - GPT chấm qua `codex exec`, dùng tài khoản ChatGPT.
  - Claude chấm qua `claude.exe -p` của extension Claude Code.
- **Thang điểm:** 7 tiêu chí, mỗi tiêu chí 1–10, quy về thang 100. **Đạt khi điểm trung bình hai bên từ 70 trở lên
  và phần kỹ thuật đạt hết.**

| Tiêu chí | Chấm cái gì |
|---|---|
| kich_ban | Đủ nhịp, đúng thứ tự |
| nhat_quan | Nhân vật, đồ vật, bối cảnh giữ nguyên giữa các clip |
| chan_thuc | Lỗi AI: tay méo, vật biến dạng hoặc tự nhân lên |
| chuyen_canh | Chỗ nối clip, nhịp timelapse |
| hinh_anh | Bố cục 9:16, ánh sáng, độ nét |
| giong_goc | Giống video gốc |
| hap_dan | Hook mở đầu, cao trào cuối cho Reels |

- **Kết quả nằm trong `video/qa/`:**
  - `qa-report.md`: bảng điểm, nhận xét, lỗi kèm số ô và số giây, việc nên sửa trước.
  - `qa.json`, `gpt-raw.txt`, `claude-raw.txt`.
- QA chỉ nhìn ảnh tĩnh, nên chưa đánh giá được độ mượt chuyển động và âm thanh. Bạn vẫn nên xem lại video trước khi đăng.

## Xử lý sự cố

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| muse.ai báo lỗi `ERR_QUIC_PROTOCOL_ERROR` hoặc chuyển vòng vòng qua Facebook | IP bị chặn | Bật VPN trong `opera://settings/vpn` ở cửa sổ Opera của tool |
| Codex: "Codex chạy xong nhưng không thấy file ảnh" kèm `moderation_blocked` / `sexual` | Bộ lọc an toàn của OpenAI chặn ảnh đầu ra | Chỉ gửi kèm ảnh nhân vật góc trực diện, tả tư thế đứng thẳng, thêm "modest, wholesome family-friendly". Không dùng từ tả cơ thể |
| Muse đã trả lời "xong" nhưng tool vẫn chờ; trong chat ô video là khung xám hoặc báo "Video not found" | Cửa sổ Opera bị thu nhỏ nên Opera ngừng vẽ trang (bản cũ chưa có cờ chống) | Mở cửa sổ Opera lên và cuộn tới video. Bản hiện tại đã mở Opera kèm cờ chống tạm dừng, nên thu nhỏ không còn ảnh hưởng |
| Muse dùng nhầm ảnh của tập cũ | Tên file trùng với tập trước | Đặt tiền tố riêng cho tên file mỗi tập |
| Tool báo không tìm thấy ô nhập hoặc nút | Muse đổi giao diện | Xem mục bên dưới |

## Khi Muse đổi giao diện

Nếu tool báo không tìm thấy ô nhập hoặc nút bấm:

1. Mở khung chat Muse trong Opera của tool.
2. Chạy `python muse_auto.py inspect --now`. Tool sẽ lưu danh sách nút, HTML và ảnh chụp trang vào `_inspect/`.
3. Dựa vào đó, sửa các selector trong `config.json`:

| Khóa | Hiện tại | Là gì |
|---|---|---|
| `attach_input` | `input[type=file]` | Ô chọn file đính kèm |
| `remove_attachment` | `button[aria-label="Remove attachment"]` | Nút × trên ảnh đã đính kèm |
| `message` | `textarea[aria-label="Message"]` | Ô soạn tin nhắn |
| `send_key` | `Enter` | Phím gửi tin nhắn |
| `result_tile` | `[aria-label^="Open animated video"]` | Ô video Muse trả về |

## Ghi chú kỹ thuật

- Tool mở Opera với cổng debug `9333`, `--user-data-dir=opera-profile`, và các cờ:
  - `--disable-quic`: tránh lỗi `ERR_QUIC_PROTOCOL_ERROR`.
  - `--disable-background-timer-throttling`, `--disable-renderer-backgrounding`, `--disable-backgrounding-occluded-windows`:
    để video vẫn load khi cửa sổ bị thu nhỏ.
- Các cờ này chỉ có tác dụng khi tool **tự mở** Opera. Nếu Opera của tool đang mở sẵn từ trước, hãy đóng nó đi để
  tool mở lại.
- Tool gọi `codex.exe` và `claude.exe` có sẵn trong extension VS Code (`%USERPROFILE%\.vscode\extensions\...`),
  nên không cần cài thêm gì.
- Nếu cửa sổ Opera của tool đang mở sẵn, tool kết nối vào cửa sổ đó thay vì mở cửa sổ mới.
- Video trong chat Muse có dạng `blob:`. Tool đọc trực tiếp từ trang nên không cần bấm nút tải.
- Tự động hóa giao diện web có thể trái với điều khoản sử dụng của Muse. Bạn tự cân nhắc rủi ro bị khóa tài khoản.
