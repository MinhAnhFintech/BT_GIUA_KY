# Báo cáo giai đoạn 1 — 09/10/2026

## Kết quả có thể kiểm tra tại máy

Đã tạo folder/mã nền tảng tại `vn30-investment-system`. Môi trường Windows 11,
Python 3.12.3 có sẵn ở `%USERPROFILE%\.venv`; không tạo venv dự án. Launcher `py`
không nhận bản Python có sẵn, đã khắc phục bằng kích hoạt venv và executable đúng.
Vnstock 4.0.9 / Vnai 2.6.2 đáp ứng mức tối thiểu trong onboarding. `pip check` đã
báo không có dependency bị hỏng.

Config 6 file đã validate, SQLite có 15 bảng và test dùng DB tạm riêng. Không chèn
giá/tin/tài chính giả vào DB sản phẩm. Mẫu thử trực tiếp FPT chỉ dùng kiểm tra nguồn;
không tính điểm thật hoặc xuất báo cáo đầu tư từ mẫu 11 phiên này.

Kiểm thử cuối: **36 passed**, Ruff lint/format đạt, launcher PowerShell kiểm thử
offline chạy thành công. CI đã cấu hình nhưng chưa chạy trên GitHub; không báo CI
remote đã pass. Các test hiện xác minh nền tảng/config/schema/health/SDK contracts,
chưa thay thế test engine phân tích, PDF hoặc backtest ở các giai đoạn sau.

## (a) Nguồn hoạt động / không hoạt động

Thời điểm kết thúc phép thử: **09:57:08 ngày 09/10/2026, UTC+7**.
Kết quả gốc ở `data/source_health.json`, timestamp UTC
`2026-10-09T02:57:08.579163+00:00`, kèm version thư viện/config và hash từng phản hồi.

| Phép thử | Kết quả | Dữ liệu nhận được | Điều chưa xác minh |
|---|---|---|---|
| Vnstock/KBS — universe | OK | 30 mã, có đủ 6 ứng viên mặc định | Ngày hiệu lực, thông báo gốc HOSE, lịch sử |
| Vnstock/KBS — giá FPT | OK | 11 phiên, ngày mới nhất 09/10/2026 | Phiên hôm nay đã hoàn tất, đơn vị, adjusted/corporate actions |
| Vnstock/KBS — BCTC FPT | OK | 143 dòng chỉ tiêu, 4 kỳ Q3/2025 đến Q2/2026 | Ngày công bố, revisions/vintage, đơn vị tiền, đủ chỉ tiêu 6 ngành |
| Vnstock/KBS — hồ sơ FPT | OK | 1 hồ sơ có symbol/as_of_date | Mapping và đối soát trường doanh nghiệp |
| Vnstock/KBS — tin FPT | OK | 1 dòng, title/publish_time/url | Timestamp, URL gốc/độ phủ lịch sử/khớp mã |
| VnExpress RSS kinh doanh | OK | 60 mục có title/link/pubDate; robots đã cho phép phép thử | Lọc 6 mã, tóm tắt tự viết, kho tin lịch sử |

Không có nguồn bắt buộc nào còn FAIL sau sửa adapter ở lần thử cuối. Lần đầu có
lỗi cách gọi `Market.equity` và yêu cầu cột `unit` không đúng schema mặc định;
đã đối chiếu SDK cài thực và chạy lại thành công. Điều này chứng minh cần test
schema trực tiếp thay vì chỉ dựa ví dụ README của SDK.

**Chưa xác minh** nguồn HOSE chứa toàn bộ danh sách có ngày hiệu lực tại các kỳ
quá khứ; chưa kiểm tra benchmark VN30/VNINDEX, corporate actions, lịch giao dịch
hoặc coverage FA/news của MWG/HPG/VCB/SSI/VNM. Những mục này không được báo OK.
Một factsheet HOSE/top-10 không đủ bằng chứng cho cả 30 thành viên.

Đây là sáu phép thử trên chủ yếu hai nguồn KBS và VnExpress, không phải sáu nguồn
độc lập. `backtest_ready=false` được ghi rõ trong JSON. Chưa có API key nên không
xác minh tier, không mặc định kết luận tài khoản sponsor hoặc community.

## Repo tham khảo và khả năng tái sử dụng

Đã đọc [repo](https://github.com/Tumiqa/vn-annual-report-miner), README và
[pyproject](https://github.com/Tumiqa/vn-annual-report-miner/blob/main/pyproject.toml).
Cấu trúc Python ở `src/arminer`, có scripts/tests/UI và quy trình khai phá báo cáo,
mapping chỉ tiêu, nguồn/hash. Có thể tham khảo cách tách module và cách gắn dữ liệu
với báo cáo gốc. Metadata kỳ/năm cần bổ sung ngày công bố/vintage để phục vụ PIT.
Không sao chép nội dung bài báo hoặc báo cáo. Giới hạn truy cập: trang tree sâu
`src/arminer` không tải được bằng browser; chưa review implementation OCR/extractor
và chưa tái sử dụng mã của repo. Phần này là tham khảo thiết kế, không tuyên bố
đã xác minh chất lượng dữ liệu/thư viện của tác giả.

Tài liệu API chính thức: [Vnstock Reference](https://vnstocks.com/docs/vnstock/tra-cuu-thong-tin-tham-chieu-reference)
và [README Vnstock](https://github.com/thinh-vu/vnstock/blob/main/README.md).
Đã kiểm tra call signatures trong SDK cài trên máy vì ví dụ public không hoàn toàn
khớp API method/property. Mã checker chạy đúng ở Vnstock 4.0.9.

## (b) Giả định đã đặt

1. Bắt đầu với 6 ứng viên theo đề; membership hiện tại được KBS quan sát trả về,
   chưa dùng thay cho xác minh lịch sử/HOSE. Không tự thay mã mẫu.
2. SQLite đủ cho 5–10 mã; React/FastAPI và ReportLab triển khai sau. Giai đoạn 1
   không dựng dashboard/PDF bằng dữ liệu fixture.
3. Ngưỡng FA/TA ban đầu là nghiên cứu, đặt trong YAML có version; chưa tối ưu hiệu suất.
4. Cần đủ mọi chỉ tiêu bắt buộc của bộ chấm điểm ngành; thiếu dữ liệu giữ N/A,
   tổng S NULL, không có xếp hạng chính giả bằng phần điểm còn lại.
5. BCTC không có publication date có thể dùng lag bảo thủ 45/90 ngày, phải có cờ.
   Strict PIT còn cần vintage xác minh; lag không chữa revision bias.
6. NEWS hiện tại dùng rule-based, không cần khóa LLM. `S_full` backtest chưa khả dụng
   nếu không có lịch sử tin; dùng chế độ riêng `S_ex_news` khi đủ FA/TA PIT.
7. Strict backtest phải có dated universe, điều chỉnh/corporate actions và lịch sàn.
   Thiếu nguồn không được tự dựng dữ liệu; mặc định từ chối mode nghiêm ngặt.
8. Phí/thuế/T+2/lô là cấu hình mô phỏng theo đề, cần đối chiếu quy định và cách
   tính của nguồn/broker nếu đem áp dụng ngoài bài tập.

## (c) Điểm cần chốt trước khi dùng dữ liệu lịch sử ở giai đoạn tiếp theo

Không có câu hỏi bắt buộc để tiếp tục xây data layer công khai. Bạn đã chọn kiểm
tra nguồn miễn phí; mặc định giữ 6 mã, công thức chuẩn và không cài sponsor.

Các lựa chọn ảnh hưởng độ phủ cần chốt khi triển khai backtest:

- Khoảng thời gian backtest mong muốn; chưa tự ấn định mốc bắt đầu/kết thúc.
- Nếu miễn phí thiếu lịch sử tài chính/ngày công bố/snapshot VN30, có chấp nhận
  nhập nguồn CSV có provenance và ngày công bố hoặc dùng gói sponsor do bạn có
  quyền truy cập không? Không mua/cài gói tài trợ tự động.
- Nếu không có snapshot/vintage lịch sử, có muốn thêm fixed-universe backtest
  minh họa, ghi rõ bias và tách khỏi strict mode? Mặc định hiện tại không bật.

Các lựa chọn này không thay thế bằng chứng dữ liệu. Chỉ có thể báo fullstack/
backtest hoàn tất sau giai đoạn 2–8 và checklist end-to-end đạt.
