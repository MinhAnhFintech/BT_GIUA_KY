# Giao diện nghiên cứu VN30

React + TypeScript + Vite, giao diện tiếng Việt thích ứng máy tính và điện thoại.
Sáu màn hình: xếp hạng, chi tiết cổ phiếu, chọn danh mục, backtest, PDF và chất lượng dữ liệu.
Giao diện chỉ hiển thị dữ liệu từ API; không có dữ liệu giá hoặc điểm minh họa.

Khởi động backend tại http://127.0.0.1:8000, sau đó chạy trong thư mục này:

    npm install
    npm run dev

Mở http://127.0.0.1:5173. Vite chuyển tiếp /api tới backend.
Nhấn Cập nhật dữ liệu để tải vào SQLite, chờ hoàn thành rồi Chạy phân tích.
Phân tích chỉ đọc cache; hệ thống theo dõi tác vụ nền tự động.
Kiểm tra bản phát hành: npm run build. Kết quả nằm trong dist/.
Backend có thể phục vụ dist/ để sử dụng giao diện sau khi build.

Backtest thể hiện rõ trạng thái chưa đủ dữ liệu lịch sử xác minh thay vì sinh kết quả giả.
Phông chữ hệ thống được dùng nếu Google Fonts không truy cập được.
