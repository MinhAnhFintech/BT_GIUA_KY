# Kiểm tra workflow và tình trạng hoàn thành

## Kiểm chứng đã chạy

- Windows 11, Python 3.12.3 trong `%USERPROFILE%\.venv`, Node.js 22.
- Vnstock 4.0.9; Vnai 2.6.2. Xác thực Vnstock trước đó trả gói Community/Free.
- Cache giá thật hiện có 498 phiên cho MWG, HPG, VCB, SSI, VNM và 598 phiên FPT,
  từ provider KBS, kèm provenance từng bản ghi. Đây là dữ liệu đã nạp trước khi VCI
  được chọn làm nguồn mặc định.
- Provider VCI được kiểm tra sau lần đổi cấu hình: 15 phiên giá FPT trong khoảng
  14 ngày, báo cáo tài chính và tin FPT. Đơn vị/giờ công bố vẫn chưa xác minh.
- Workflow cục bộ chạy trên SQLite/cache thật: phân tích 6 mã, PDF tổng hợp, PDF
  FPT, tải cả hai PDF và phục vụ giao diện đã build.
- Backtest trên cache thật trả `UNAVAILABLE`, không lợi suất/đường vốn giả, và đưa
  15 điều kiện/dữ liệu còn thiếu.
- `python -m pytest -q`: 68 passed. Ruff lint/format: passed. React/TypeScript
  production build: passed.

## Trạng thái từng phần

| Phần | Kết quả hiện tại | Giới hạn cần biết |
|---|---|---|
| Provider VCI | Giá/BCTC/tin lấy bằng SDK đã cài; lưu provenance/cache | Không công bố đơn vị BCTC hay vintage ngày công bố chưa xác minh |
| Giá lịch sử | Tải theo khoảng ngày, giới hạn `count` tăng theo số ngày | Chưa xác minh corporate actions/giá điều chỉnh; đơn vị giá còn cờ nguồn |
| Dữ liệu cơ bản | Nạp báo cáo quý và năm; lỗi từng báo cáo độc lập | Ngày công bố hiện suy luận theo thời điểm tải; chưa đủ vintage PIT |
| Tin | Lưu tiêu đề, URL, thời gian, khử trùng, chấm rule-based | Nguồn không tạo kho tin lịch sử có timestamp đã kiểm định |
| VN30 | Lấy thành viên hiện tại và cache ngày quan sát | Không coi danh sách hiện nay là thành phần lịch sử |
| Chất lượng | Giá OHLC, bản ghi trùng, thiếu/không hữu hạn, volume và bước nhảy được kiểm tra/audit | Bước nhảy chỉ là cảnh báo rà soát; chưa có lịch HOSE/corporate actions chính thức |
| Phân tích | FA/TA/tin, trạng thái thiếu, giải thích và provenance | Điểm ngành chỉ đủ với dữ liệu phù hợp; thiếu một thành phần thì S là NULL |
| PDF | Font tiếng Việt, xếp hạng phụ/chính, chi tiết, đồ thị giá/MA và đóng góp điểm | Chưa có nến/benchmark và định giá lịch sử đầy đủ |
| UI/API | Sáu trang React, dashboard production được phục vụ tại cổng 8000 | Job nền phụ thuộc một tiến trình local; không chạy nhiều worker SQLite |
| Simulator | Lệnh khớp phiên kế tiếp, lô 100, phí/thuế, thanh khoản và T+2; có test tổng hợp | Không được dùng kết quả fixtures như lợi nhuận thị trường |
| Backtest nghiên cứu | API rà prerequisites PIT/survivorship và phản hồi an toàn | Chưa có tín hiệu lịch sử đã kiểm toán, benchmark, IC, walk-forward hay random baseline |

## Các bước chạy và kiểm chứng

1. Mở `CHAY_UNG_DUNG.cmd`, rồi mở `http://127.0.0.1:8000`.
2. Chọn 5–10 mã VN30, lưu, chạy **Cập nhật dữ liệu** và đợi job hoàn thành.
3. Chạy **Phân tích**, xem hạng chính/phụ và các cờ chất lượng.
4. Xuất PDF tổng hợp/PDF mã; đối chiếu ngày, config, nguồn và trạng thái dữ liệu.
5. Chạy backtest. Chỉ có lợi suất khi prerequisites đã xác minh; hiện dự kiến là
   `UNAVAILABLE` cho dữ liệu hiện có.
6. Mở `/docs` để kiểm tra OpenAPI. Lệnh `python -m scripts.smoke_local` chạy lại
   workflow trên DB/cache thật và sẽ lưu thêm PDF.

Khi phân tích trong ngày hiện tại trước 16:00 giờ Việt Nam, giá ngày đang chạy bị
bỏ qua; mốc 16:00 là khoảng đệm cấu hình, không thay cho lịch đóng phiên HOSE đã
kiểm chứng. Dữ liệu lịch sử chỉ được đưa vào PIT khi `available_at` cho phép; việc
tải lại hôm nay không chứng minh bản ghi đã được biết trong quá khứ.

Chưa hoàn tất toàn bộ đề: Alembic migration, lịch sử cổ tức/chia tách đã xác minh,
snapshot thành phần VN30 có ngày hiệu lực, benchmark/IC/walk-forward, và phiên bản
backtest tạo tín hiệu point-in-time. Không dùng hệ thống làm khuyến nghị mua bán.

