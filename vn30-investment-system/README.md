# Hệ thống phân tích cổ phiếu VN30

Ứng dụng local gồm dashboard React tiếng Việt, FastAPI, SQLite, phân tích FA/TA/tin
tức, giải thích điểm, xuất PDF tiếng Việt và bộ mô phỏng backtest. Không có số liệu
thị trường giả; thiếu dữ liệu được ghi N/A và lý do.

**Giới hạn:** nguồn hiện tại chưa xác minh đủ đơn vị/điều chỉnh giá, VN30 lịch sử,
ngày công bố và vintage tài chính. Backtest nghiêm ngặt trả `UNAVAILABLE` kèm lý do
khi thiếu bằng chứng. Simulator đã kiểm thử phí/thuế, lô 100, T+2 và khớp phiên kế tiếp.

## Chạy trên máy này — dành cho người chưa biết code

1. Nhấp đúp **CHAY_UNG_DUNG.cmd** để chạy backend; giữ cửa sổ mở.
2. Mở **http://127.0.0.1:8000**. Bản giao diện đã build được phục vụ trực tiếp.
3. Khi sửa giao diện, nhấp đúp **CHAY_GIAO_DIEN.cmd** rồi mở **http://127.0.0.1:5173**.
4. Vào Danh mục, chọn 5–10 mã VN30 rồi lưu; nhấn Cập nhật dữ liệu.
5. Chờ tác vụ hoàn thành rồi Chạy phân tích. Lần đầu có thể mất vài phút vì nguồn;
   giá ở các lần tiếp theo chỉ tải những ngày chưa lưu.
6. Xem bảng xếp hạng chính/phụ; nhấp mã để xem chi tiết, nguồn và các nguyên nhân
   thiếu dữ liệu. Chọn Xuất PDF tổng hợp hoặc PDF mã để tải báo cáo.
7. Trang Backtest cho nhập khoảng ngày/chế độ. Khi thiếu dữ liệu lịch sử đã xác
   minh, đọc lý do hiển thị; không coi trạng thái này là mô phỏng đã có lợi suất.
8. Trang Hệ thống hiển thị nguồn/quality/timing; Báo cáo lưu lịch sử PDF.

Đóng cửa sổ để dừng. Job, phân tích và báo cáo lưu SQLite qua restart.
Tác vụ đang chạy khi đóng ứng dụng cần gửi lại; chưa có worker tự tiếp tục qua restart.
OpenAPI nằm tại http://127.0.0.1:8000/docs. Không chạy nhiều worker với SQLite.

## Cài đặt hoặc chạy bằng lệnh

Cần Python 3.11+ và Node.js 20+. Máy này đã có Python trong môi trường dùng chung
`%USERPROFILE%\.venv`; launcher `py` ngoài venv không nhận bản đã có, không cần cài lại.
Mở PowerShell tại thư mục dự án:

```powershell
& "$env:USERPROFILE\.venv\Scripts\Activate.ps1"
python -m pip install -e '.[dev]' --extra-index-url https://vnstocks.com/api/simple
cd frontend
npm.cmd install
cd ..
```

Hai lệnh chạy (mỗi lệnh trong một cửa sổ):

```powershell
# Cửa sổ 1, tại thư mục dự án, đã kích hoạt venv
python -m uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8000
# Cửa sổ 2, tại frontend
npm.cmd run dev
```

Vite proxy `/api` tới backend. `CAI_DAT.cmd` cài thư viện trong môi trường chung;
npm vẫn cần chạy một lần nếu chưa có node_modules. Colab dùng Python notebook,
không tạo venv. Hướng dẫn giai đoạn 1 cũ được lưu ở `docs/README_STAGE1.md`.

## Có API key nhưng không lấy dữ liệu

Đã sửa lỗi chữ ký provider, phương thức updater không tồn tại, refresh chưa nối
SQLite, hàm đọc tin luôn rỗng, API tải lại nguồn mỗi lần phân tích và chọn mã không
được lưu. API key không sửa được các lỗi mã này.

SDK đang cài cần `Market().equity('FPT').ohlcv(...)`,
`Fundamental().equity('FPT').balance_sheet(...)`,
`Reference().company('FPT').info()`. Ứng dụng đọc `.env` trước khi import SDK.
Khóa trong chat không tự trở thành biến môi trường. `.env` cần có:

```dotenv
VNSTOCK_API_KEY=nhap_khoa_cua_ban_tren_may
VNSTOCK_DISABLE_AGENT_SETUP=1
VNSTOCK_AGENT_TARGETS=none
```

Không đưa khóa vào Git/mã nguồn/chat. Khóa đã gửi trong chat nên đổi tại trang tài
khoản và lưu khóa mới trên máy. Kiểm tra an toàn, không in khóa:

```powershell
python -m scripts.verify_access
python -m scripts.data_source_check
```

Free/Community không mở tính năng Sponsor hay bảo đảm nguồn còn sống/đủ lịch sử.
Auth đã xử lý `subscription=null` với `userType=free`; lỗi mạng không bị coi là Free.
Khóa gửi qua Authorization header, không qua URL. Log ứng dụng không lưu raw
exception của provider; `.env`, cache và PDF được gitignore.

## Kiểm thử

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m scripts.smoke_local  # Dùng cache thật, lưu phân tích và hai PDF
cd frontend
npm.cmd run build
```

`KIEM_TRA.cmd` kiểm tra offline. Fixture tổng hợp chỉ dùng trong tests/DB tạm,
không dùng để tạo dữ liệu sản phẩm. CI offline nằm ở repository cha.

## Hệ thống và phương pháp

6 YAML trong `config/` giữ trọng số/ngưỡng/version/hash. `data/` cung cấp provider,
cache SQLite và validation; `analysis/service.py` phân tích dữ liệu cache tại ngày;
`api/main.py` cung cấp API/job; `reports/pdf.py` nhúng font tiếng Việt;
`backtest/engine.py` kiểm tra prerequisites và mô phỏng; `frontend/` có 6 trang.
DB và selection nằm trong `data/`, PDF trong `reports_out/`.

`S = 0.45 FA + 0.35 TA + 0.20 NEWS`. Mode riêng `S_ex_news` có FA=0.5625,
TA=0.4375; không thay công thức chuẩn. Thiếu thành phần: tổng NULL, bảng phụ,
không dồn trọng số. Phân tích lọc `available_at`; giá nguồn chưa xác minh không tự
gán VND. Ngoài 6 ngành mặc định, cần cấu hình FA ngành phù hợp để có điểm đủ.

Chưa hoàn tất: Alembic nâng schema, nguồn corporate actions/lịch sàn đã xác minh,
benchmark/IC/walk-forward trên dữ liệu thật, PDF so sánh định giá và nến đầy đủ.
PDF hiện có biểu đồ giá/MA, đóng góp điểm, bảng chỉ tiêu và footer tiếng Việt.
Đọc [METHODOLOGY.md](METHODOLOGY.md), [kiến trúc](docs/ARCHITECTURE.md) và
[checklist](docs/WORKFLOW_REVIEW.md). Không coi các mục này đã đạt chỉ vì có giao diện.

Công cụ hỗ trợ phân tích, không phải khuyến nghị đầu tư. Điểm không đại diện cho
xác suất tăng giá hoặc tỷ suất lợi nhuận dự kiến.
