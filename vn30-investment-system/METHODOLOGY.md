# Phương pháp, giả định và giới hạn

Tài liệu này phân biệt nền tảng đã triển khai (config/schema/health) với phương
pháp sẽ thực thi ở giai đoạn analysis/backtest. Chưa có kết quả lợi suất hoặc điểm
xếp hạng thật; các ngưỡng cấu hình là giả định nghiên cứu, không phải dữ liệu thị trường.

## Chấm điểm chuẩn

`S = 0.45 × FA + 0.35 × TA + 0.20 × NEWS`, mỗi thành phần và S thuộc [0,100].
Điểm không đại diện cho xác suất tăng giá hoặc tỷ suất lợi nhuận dự kiến.
Công cụ hỗ trợ phân tích, không phải khuyến nghị đầu tư.

Chuẩn hóa tuyến tính có chặn: `x = clip((value - lower) / (upper - lower), 0, 1)`;
điểm chỉ tiêu là `100*x` nếu càng cao càng tốt, `100*(1-x)` nếu càng thấp càng tốt.
Không thay thế đầu vào thiếu bằng 0. Chỉ khi mọi chỉ tiêu chấm điểm bắt buộc của
thành phần có giá trị hợp lệ mới tính trung bình theo trọng số đã cấu hình.
Các chỉ tiêu bổ sung ngoài bộ chấm điểm có thể N/A nhưng phải giải thích.

Điều kiện số lượng 250 phiên/4 quý/1 tin trong 30 ngày là **điều kiện cần**.
Tính tăng trưởng YoY quý còn cần quý cùng kỳ năm trước; tăng trưởng TTM cần lịch sử
dài hơn 4 quý. Một nguồn trả đủ 4 quý không tự động đủ tính mọi chỉ tiêu. Mẫu số
không dương khiến YoY, P/E, nợ/EBITDA hoặc CFO/lợi nhuận không có ý nghĩa theo công
thức thông thường: ghi N/A, không tự diễn giải thành mức tăng trưởng cao.

Giá trị tiền tệ chuẩn VND; tỷ lệ chuẩn dạng phần (0.15 = 15%), định giá/vòng quay là
số lần. Không tự đoán đơn vị từ độ lớn. Nếu nguồn chỉ ghi đơn vị hợp nhất/riêng lẻ
thì đó là phạm vi báo cáo, không phải đơn vị VND. Định giá so lịch sử phải dùng các
giá trị đã được biết ở thời điểm phân tích, không dùng trung vị tính từ dữ liệu tương lai.

## TA và NEWS

TA dự kiến dùng MA20/50/200, RSI14 theo Wilder, MACD12/26/9, tỷ lệ khối lượng
20/60 phiên và ATR14/giá. Định nghĩa và giá tham chiếu sẽ được test ở giai đoạn 3.
RSI tuyến tính trong config hiện là giả định momentum, chưa mô hình hóa riêng
vùng quá mua. Không kết luận mô hình có hiệu quả dự báo trước khi backtest.

NEWS dự kiến phân loại rule-based từ từ khóa cấu hình, có confidence, mức ảnh
hưởng sự kiện và độ mới `exp(-ln(2)*age_days/half_life_days)`. Ngày tuổi âm bị loại.
Các nhãn xác suất/confidence do rule-based không phải xác suất thống kê đã hiệu chuẩn.
Không bắt buộc LLM ở phiên bản đầu. Nếu thêm LLM sau này, phải cache theo hash nội
dung + version classifier, ghi confidence và có fallback.

Tin chỉ được lưu tiêu đề, URL, ngày xuất bản và tóm tắt tự viết; không tải/lưu toàn
văn để bù dữ liệu thiếu. RSS hiện tại không được coi là kho tin quá khứ. Kiểm tra
robots trước truy cập; nếu chính sách không đọc được hoặc cấm thì dừng nguồn đó.

## Thiếu dữ liệu và bảng xếp hạng

`COMPLETE`: đạt mọi điều kiện dữ liệu, thành phần chấm điểm và universe đã xác minh.
`PARTIAL_ANALYSIS`: có phân tích hữu ích nhưng thiếu một điều kiện/thành phần,
tổng điểm là NULL, đưa bảng phụ. `INSUFFICIENT_DATA`: không đủ phân tích hợp lệ,
đưa bảng phụ cùng nguyên nhân. Schema đã lưu được các trạng thái này; điều kiện
engine cụ thể và test xếp hạng sẽ có ở giai đoạn 3.

## Point-in-time và revision

Mỗi bản ghi nguồn có `source`, `source_url`, `fetched_at`, `as_of_date`, hash.
BCTC thêm `period_end`, `published_at`, `available_at`, `publication_inferred`,
`revision`, `vintage_verified`. Ngày cuối quý không phải ngày đã biết báo cáo.
Không có ngày công bố: dùng độ trễ 45 ngày theo quý / 90 ngày theo năm, gắn cờ
suy luận và nêu trong kết quả. Độ trễ này **không khắc phục revision bias**: số
được sửa sau này không được gán lại ngày công bố ban đầu. Dữ liệu tải hiện tại mà
không có vintage gốc không đủ điều kiện backtest point-in-time nghiêm ngặt.

`fetched_at` là ngày tải, không phải mặc định ngày công bố. Nguồn lịch sử có bằng
chứng ngày công bố/vintage có thể tải hôm nay nhưng vẫn xác lập `available_at`
trong quá khứ; nếu không có bằng chứng, không tự lùi thời điểm biết dữ liệu.

Snapshot VN30 lưu ngày hiệu lực và ngày thông báo. Danh sách trả từ API hiện tại
là quan sát tại ngày lấy, không chứng minh thành phần ở tháng/năm khác. Strict
backtest phải từ chối khi thiếu snapshot phù hợp; nếu thêm chế độ fixed-universe
minh họa, phải đặt tên riêng và cảnh báo survivorship bias, không thay default.

## Mô phỏng dự kiến ở giai đoạn 7

`S_full` dùng công thức chuẩn, chỉ khả dụng nếu có tin quá khứ được xác minh.
`S_ex_news` là chế độ riêng: FA=0.5625, TA=0.4375, không gọi là công thức chuẩn.
Không tự chuyển chế độ sau lỗi nguồn mà không ghi nhận lựa chọn và lý do.

Tín hiệu sau đóng cửa phiên t, thực thi mở cửa phiên t+1. Chỉ sử dụng phiên thực
của sở giao dịch, không thay bằng ngày làm việc hành chính. Lô 100, T+2 phiên,
phí mua/bán 0.15% mỗi chiều, thuế bán 0.1%, slippage 0.1%; tất cả có config riêng.
T+2 là mô hình bảo thủ theo phiên; lịch/giờ settlement chính xác và các mức phí
là tham số mô phỏng cần đối chiếu khi dùng, không phải khẳng định quy định mới nhất.

Chọn top-3, trọng số mục tiêu đều, nhưng trọng số thực tế có thể lệch do tiền dư,
lô, chưa đủ settlement, biên độ hoặc thanh khoản. Giá khớp dùng raw OHLC thực,
không dùng adjusted close làm giá mua. Lợi suất cần corporate actions/cổ tức được
xác minh: cổ phiếu chia tách, quyền mua và tiền cổ tức phải xử lý riêng, tránh
tính hai lần khi dùng series adjusted. Thiếu bằng chứng điều chỉnh phải từ chối
strict backtest; không dùng dữ liệu giá thô để báo total return như đã điều chỉnh.

Giới hạn giá dùng giá tham chiếu và ngày sự kiện nếu lấy được, không mặc định
so với close hôm trước vì ngày không hưởng quyền có thể thay giá tham chiếu.
Phát hiện nhảy giá >7% là cờ cần kiểm tra, không tự sửa/bỏ dòng dữ liệu.

Benchmark cần chuỗi thật VN30/VNINDEX cùng thời gian, baseline mua giữ đều và
random top-N nhiều lần với seed cố định. Thiếu benchmark: ghi unavailable, không
vẽ đường vốn giả. IC Spearman dùng score tại t và lợi suất kỳ sau, không kết hợp
điểm đã biết tương lai. Tertile/top-bottom hợp lý hơn quintile cho 6 mã.

Lưu config/hash dữ liệu/IDs đầu vào/seed/version thư viện. Chia out-of-sample hoặc
walk-forward, không tối ưu công thức 45/35/20. Với <10 mã hoặc ít kỳ, mọi kết quả
mang tính minh họa; không khẳng định có ý nghĩa thống kê hay chắc chắn có lãi.
