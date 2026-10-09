# Double-check workflow và Definition of Done

## Giai đoạn 1

- [x] Đọc README/cấu trúc/pyproject repo tham khảo; ghi giới hạn chưa review module sâu.
- [x] Xác minh môi trường: Windows 11, Python 3.12.3, venv dùng chung có sẵn.
- [x] Cập nhật pip, Vnstock/Vnai và công cụ kiểm thử trong môi trường đúng.
- [x] Không ghi tài liệu/skill của provider xuống project; tắt agent setup.
- [x] Người dùng chọn nguồn công khai, không gửi API key vào chat.
- [x] Config version/hash, công thức chuẩn 45/35/20, missing không đổi trọng số.
- [x] Bộ chỉ tiêu 6 ngành và giả định backtest riêng được cấu hình.
- [x] Schema có publication/availability/revision, raw/adjusted tách biệt, nguồn/hash.
- [x] Source checker kiểm tra phản hồi thật, schema, robots, timeout, output UTF-8.
- [x] Các source probe đã chạy tại máy; report JSON có timestamp/hash/version.
- [x] Test nền tảng/schema/health và lint chạy đạt.
- [x] README có hướng dẫn cho người không biết code, script double-click trên Windows.
- [x] Có METHODOLOGY, ARCHITECTURE, giới hạn nghiên cứu và checklist còn thiếu.

## Double-check các điểm dễ làm sai

| Rủi ro | Cách xử lý hiện tại | Việc cần hoàn tất |
|---|---|---|
| py/PATH không nhận Python | Dùng `.venv` tồn tại, kích hoạt trước mọi lệnh | Không cần sửa PATH toàn máy |
| Thiếu = 0 / dồn trọng số | Config và constraint DB chặn | Test engine scoring/ranking ở giai đoạn 3 |
| Dùng report period như publication | Schema có 3 ngày riêng và revision | Adapter/query PIT và backtest tests |
| Backfill số sửa vào quá khứ | Giữ revision, vintage_verified | Bằng chứng vintage thật/nguồn bổ sung |
| Danh sách VN30 hiện tại thành lịch sử | Source warning current-only | Snapshot có hiệu lực/announced_at từ nguồn gốc |
| Giá ngày hôm nay chưa đóng phiên | Source health không xác minh phiên hoàn tất | Lịch sàn + thời điểm đóng + bỏ phiên dở |
| adjusted close dùng khớp lệnh | Schema raw và adjusted riêng | Corporate actions/trade simulation |
| RSS hiện tại là kho tin lịch sử | Gắn warning, S_full chưa khả dụng | Kho tin timestamp đáng tin |
| API ký hiệu khác README SDK | Đối chiếu mã SDK cài thực và gọi live thành công | Pin/version adapters khi hoàn thiện |
| Schema tài chính không có cột unit mặc định | Ghi unit chưa xác minh, không tự đoán | Chuẩn hóa dựa bằng chứng provider |
| Tin rule-based bị coi là xác suất | Ghi phương pháp và giới hạn trong methodology | Test dedup, confidence/event mapping |
| Health OK bị hiểu là đủ backtest | Luôn `backtest_ready=false` ở stage 1 | Kiểm tra prerequisites ở stage 7 |

## Definition of Done cho toàn hệ thống — chưa đạt

- [ ] Adapter giá/FA/news cho 6 mã, incremental và migration Alembic.
- [ ] Universe tại ngày phân tích, loại mã không hợp lệ và gợi ý cùng ngành.
- [ ] Quality checks đầy đủ: phiên thiếu, biên độ, KL=0, cân BCTC, đơn vị, sự kiện.
- [ ] TA/FA/news/ranking thực, giải thích từng raw value → score → weight → contribution.
- [ ] FastAPI, job nền, endpoint đầy đủ, integration tests.
- [ ] PDF tiếng Việt, nguồn/thời điểm/đơn vị/footer, đối soát số DB và PDF.
- [ ] UI đủ 6 trang và mọi thao tác chạy từ giao diện, trạng thái lỗi/trống rõ.
- [ ] Backtest chống look-ahead/revision/survivorship và tests phí/thuế/T+2/lô.
- [ ] Benchmark/IC/tertiles/random baseline/walk-forward/seed/hashes và warnings mẫu nhỏ.
- [ ] Lần refresh thứ hai chỉ tải mới, timing và so sánh thực.
- [ ] Docker hoặc hai lệnh khởi động backend/frontend đã được test.
- [ ] Test end-to-end chọn → refresh → analysis → ranking → PDF → backtest.

Không đánh dấu hoàn thành dựa trên file/folder placeholder. Giữ các mục còn thiếu
để giai đoạn 2–8 được nghiệm thu đúng phạm vi, sau khi kiểm thử từng giai đoạn.
