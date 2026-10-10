# Hệ thống phân tích cơ hội đầu tư cổ phiếu VN30

Dự án phục vụ bài tập giữa kỳ: phân tích tài chính (FA), kỹ thuật (TA), tin tức,
xếp hạng các mã đủ dữ liệu và xuất PDF; kiểm chứng phương pháp bằng backtest.

**Trạng thái hiện tại: giai đoạn 1 — khảo sát và nền tảng.** Có mã cấu hình, schema
SQLite, hợp đồng provider, kiểm tra nguồn và kiểm thử. **Chưa có dashboard, API
phân tích, PDF hoặc backtest chạy được.** Các chức năng này triển khai tuần tự ở
giai đoạn 2–8, theo yêu cầu kiểm thử sau từng giai đoạn trong đề.

Công cụ hỗ trợ phân tích, không phải khuyến nghị đầu tư. Điểm không đại diện cho
xác suất tăng giá hoặc tỷ suất lợi nhuận dự kiến.

## 1. Dành cho người chưa biết code

Trên máy đã kiểm tra, Python 3.12.3 có sẵn trong `C:\Users\ADMIN\.venv`.
Lệnh `py` chưa nhận bản Python này và lệnh `python` ngoài môi trường ảo trỏ tới
Windows App Store. **Không cần cài lại Python trên máy này.** Các script đã dùng
đúng môi trường dùng chung, không thay đổi PATH của Windows.

1. Mở thư mục `vn30-investment-system` bằng File Explorer.
2. Nhấp đúp `KIEM_TRA.cmd` để chạy kiểm thử offline, lint và khởi tạo SQLite.
3. Khi thành công, cửa sổ hiển thị các kiểm thử đạt và `Schema ready: 15 tables`.
   File cơ sở dữ liệu nằm trong `data\vn30.sqlite3`; khởi tạo không chèn dữ liệu giả.
4. Để kiểm tra nguồn online, mở thư mục dự án, gõ `powershell` vào thanh địa chỉ
   File Explorer và Enter; chạy lệnh bên dưới.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_checks.ps1 -Online
```

Lệnh này kiểm thử trước rồi gọi nguồn công khai. JSON kết quả ở
`data\source_health.json`, có nguồn, thời điểm lấy, hash phản hồi, schema, ngày dữ
liệu mới nhất nếu xác định được và cảnh báo. `OK` chỉ xác nhận phép thử nguồn đã
đạt, không xác nhận đủ dữ liệu để chấm điểm hay backtest.

`ExecutionPolicy Bypass` trong các launcher chỉ áp dụng cho tiến trình đang mở,
không sửa chính sách Windows toàn máy. Mã nguồn script đọc được trong `scripts/`.

Trên máy mới: cài Python 3.11 hoặc 3.12 từ
[python.org](https://www.python.org/downloads/windows/), chọn **Add Python to PATH**,
sau đó nhấp đúp `CAI_DAT.cmd`. Script tạo hoặc dùng lại `%USERPROFILE%\.venv`, cài
thư viện và kiểm thử; không tự tải/chạy trình cài Python.

## 2. Cách chạy bằng lệnh

Mở PowerShell tại thư mục dự án. Mỗi cửa sổ mới phải kích hoạt môi trường:

```powershell
& "$env:USERPROFILE\.venv\Scripts\Activate.ps1"
$env:PYTHONUTF8 = '1'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m scripts.init_db
python -m scripts.data_source_check --as-of 2026-10-09
```

Nếu máy chưa cài thư viện:

```powershell
python -m pip install -U pip
python -m pip install -e '.[dev]' --extra-index-url https://vnstocks.com/api/simple
```

macOS/Linux, dùng môi trường chung theo hướng dẫn onboarding:

```bash
python3 -m venv ~/.venv  # chỉ chạy nếu chưa có môi trường
source ~/.venv/bin/activate
python -m pip install -e '.[dev]' --extra-index-url https://vnstocks.com/api/simple
make test
make lint
make init-db
make check-sources
```

Google Colab: dùng Python của notebook, không tạo/kích hoạt venv. Nếu sau này dùng
Jupyter trên máy cá nhân, đăng ký `ipykernel` trong môi trường chung rồi chọn kernel
**Python (Vnstock)**; hiện dự án chưa cung cấp notebook.

Các lệnh API, `npm run dev` và `docker compose up` **chưa khả dụng ở giai đoạn 1**.
Hướng dẫn hai tiến trình backend/frontend và Docker sẽ bổ sung khi các module đó
đã được triển khai và kiểm thử, không có dịch vụ Docker giả để báo hoàn thành.

## 3. API key và bảo mật

Bạn đã chọn kiểm tra nguồn công khai trước, nên chưa cần khóa. Nếu cần cấp quyền
Community/Sponsor, lấy khóa tại <https://vnstocks.com/account#api-key>:

1. Sao chép `.env.example` thành `.env` nếu file chưa có.
2. Mở `.env` bằng Notepad và điền `VNSTOCK_API_KEY="khóa của bạn"`.
3. Giữ hai biến tắt ghi agent/skill xuống đĩa. Không gửi khóa vào chat hoặc Git.

`.env`, dữ liệu và PDF được gitignore. Checker chỉ ghi `api_key_present`, không
ghi khóa, header xác thực hoặc nội dung lỗi SDK có thể chứa khóa. Hiện checker
**không xác minh gói tài trợ**; `tier=NOT_AUTHENTICATED` là chưa thực hiện xác thực,
không phải kết luận tài khoản thuộc gói nào. Cài gói sponsor là bước riêng sau khi
phát hiện tier và có yêu cầu của người dùng.

Không gọi `setup_agent`, `enable_agent`, `register_user` hoặc tải/lưu skill trong
workflow kiểm tra nguồn. SDK có thể ghi metadata vận hành của chính nó dưới
`~/.vnstock`; đây không phải nội dung skill hay tài liệu độc quyền. Trên môi trường
hạn chế quyền ghi, SDK có thể báo lỗi metadata dù truy vấn nguồn vẫn hoạt động.

## 4. Cấu trúc thư mục

```text
vn30-investment-system/
├── config/               6 file YAML có version và hash
├── backend/app/
│   ├── core/             loader cấu hình, timer
│   ├── data/             hợp đồng provider, source health
│   ├── db/               15 bảng SQLAlchemy, SQLite WAL/foreign keys
│   ├── analysis/         dành cho giai đoạn 3
│   ├── api/              dành cho giai đoạn 4
│   ├── jobs/             dành cho giai đoạn 4
│   ├── reports/          dành cho giai đoạn 5
│   └── backtest/         dành cho giai đoạn 7
├── backend/tests/        fixture tổng hợp có nhãn, không dùng trong sản phẩm
├── frontend/             thiết kế React, triển khai ở giai đoạn 6
├── scripts/              init_db, data_source_check, launcher PowerShell
├── docs/                 kiến trúc, khảo sát nguồn, checklist
├── data/                 SQLite và kết quả kiểm tra online, gitignored
├── reports_out/          PDF tương lai, gitignored
├── METHODOLOGY.md
├── Makefile
└── pyproject.toml
```

Workflow CI nằm ở `.github/workflows/vn30-foundation.yml` tại **gốc repository cha**,
vì project này là thư mục con trong repository bài tập. CI chỉ kiểm thử offline;
không phụ thuộc thị trường mở cửa, API key hoặc nguồn bên ngoài còn truy cập được.

## 5. Cấu hình và ý nghĩa hệ thống

| File | Nội dung |
|---|---|
| `universe.yaml` | 6 ứng viên FPT/MWG/HPG/VCB/SSI/VNM; chọn 5–10 mã |
| `scoring.yaml` | Công thức 45% FA + 35% TA + 20% NEWS, TA và news parameters |
| `sector_metrics.yaml` | Bộ chỉ tiêu riêng 6 ngành, trọng số, đơn vị, hướng điểm |
| `data_requirements.yaml` | 250 phiên, 4 quý, 1 tin/30 ngày, độ trễ công bố và quality |
| `sources.yaml` | Nguồn công khai, timeout, nhịp gọi, mã dùng để kiểm tra nguồn |
| `backtest.yaml` | Chi phí, lô, settlement, benchmark, seed và chế độ ex-news riêng |

Loader kiểm tra version, số mã, trùng mã, bộ chỉ tiêu ngành, tổng trọng số, khoảng
chuẩn hóa và tham số backtest cơ bản. Công thức chuẩn không được đổi. Khi thay
đổi ngưỡng nghiên cứu phải tăng version và kiểm thử lại; hash nội dung giúp phát
hiện thay đổi kể cả khi người dùng quên tăng version.

Thiếu dữ liệu không thành 0 và không dồn trọng số. Schema lưu điểm thiếu bằng
`NULL`, chặn tổng điểm của mã `PARTIAL_ANALYSIS`/`INSUFFICIENT_DATA`. Engine chấm
điểm/xếp hạng sẽ triển khai ở giai đoạn 3; hiện chưa tính điểm đầu tư thật.

## 6. Kiểm thử và cách đọc kết quả nguồn

Kiểm thử tập trung vào các lỗi có ảnh hưởng: thay công thức, dồn trọng số khi
thiếu dữ liệu, timestamp không có timezone, giá âm, dữ liệu giá tương lai, revision
tài chính tương lai, foreign keys và không truy cập RSS khi robots chặn/lỗi.
Fixture được gắn `SYNTHETIC_TEST_ONLY` hoặc ghi rõ trong docstring; không được lưu
vào DB sản phẩm hoặc dùng tạo dashboard/PDF.

Mã thoát checker: `0` = mọi nguồn bắt buộc đạt phép thử; `1` = có nguồn bắt buộc lỗi.
Nguồn tùy chọn lỗi vẫn xuất hiện trong JSON. `latest_data_date=null` nghĩa là chưa
xác minh được ngày, tuyệt đối không hiểu là dữ liệu mới nhất hôm nay. Checker chỉ
thử giá/hồ sơ/tài chính/tin của **FPT**, không chứng minh độ phủ toàn bộ 6 mã.

Chi tiết khảo sát và kết quả xác minh tại máy này: [docs/STAGE1.md](docs/STAGE1.md).
Kế hoạch và hợp đồng API: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Phương pháp/giả định: [METHODOLOGY.md](METHODOLOGY.md).
Theo dõi Definition of Done: [docs/WORKFLOW_REVIEW.md](docs/WORKFLOW_REVIEW.md).

## 7. Xử lý lỗi thường gặp

- `py` báo không có Python: trên máy này dùng `KIEM_TRA.cmd` hoặc kích hoạt
  `%USERPROFILE%\.venv`; không dựa vào `py` để chạy.
- `ModuleNotFoundError`: kiểm tra đã kích hoạt venv trong cửa sổ hiện tại và chạy
  cài đặt theo mục 2; không dùng pip hệ thống.
- PowerShell chặn script: dùng launcher `.cmd` đã cung cấp; không cần đổi policy
  toàn máy hoặc chạy Windows bằng quyền Administrator.
- Nguồn timeout/schema đổi: xem `reason` trong JSON; không gán dữ liệu rỗng thành
  điểm 0, không dùng số liệu fixture thay thế. Sửa adapter và kiểm thử lại.
- Ký tự tiếng Việt bị lỗi: đặt `$env:PYTHONUTF8='1'`; launcher và checker đã đặt
  UTF-8. Các file mã nguồn/tài liệu đều mã hóa UTF-8.
- Không đủ lịch sử tài chính/tin/VN30: ghi thiếu dữ liệu và cần bổ sung nguồn có
  provenance; không chạy backtest chuẩn bằng dữ liệu suy đoán.

## 8. Lộ trình còn lại

| Giai đoạn | Sản phẩm và kiểm thử bắt buộc |
|---|---|
| 1 | Khảo sát, config, schema, checker và test nền tảng — đã triển khai |
| 2 | Adapter dữ liệu chuẩn hóa, snapshots VN30, incremental, quality, Alembic |
| 3 | Chỉ báo TA/FA/NEWS, breakdown, ranking, test missing-data |
| 4 | FastAPI/OpenAPI, job nền, lỗi rõ ràng và integration test |
| 5 | PDF tổng hợp và từng mã; font tiếng Việt, đối soát DB |
| 6 | Dashboard React tiếng Việt, kết nối API, loading/error/empty |
| 7 | Backtest/PIT, chi phí/T+2/lô, benchmark, walk-forward, trang UI |
| 8 | Docker, kiểm thử end-to-end, tối ưu, hướng dẫn vận hành hoàn chỉnh |

Sau từng giai đoạn phải chạy test và cập nhật tài liệu trước khi đi tiếp. Fullstack
chỉ được coi là hoàn tất khi checklist giai đoạn 8 đã đạt, không dựa vào số folder.
