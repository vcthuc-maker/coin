# Pre-Pump Scanner Web

Web scanner theo yêu cầu cho Binance, Bybit, OKX và MEXC (public perpetual market data).

## Triển khai Streamlit Community Cloud

1. Vào https://share.streamlit.io/ và đăng nhập GitHub.
2. Chọn **Create app** / **Deploy a public app from GitHub**.
3. Repository: `vcthuc-maker/coin`, branch: `main`, entrypoint: `app.py`.
4. Chọn Python 3.12 nếu được yêu cầu và bấm Deploy.
5. Nhấn **QUÉT NGAY** để tải dữ liệu.

## Chạy local

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Ứng dụng không cần API key và không gửi lệnh giao dịch. Điểm dựa trên quy tắc (tối đa 90); chưa phải mô hình AI và không phải xác suất tăng giá. Một số API có thể chặn IP máy chủ hosting.

## V2.2 — Nén lâu và breakout tiếp diễn (4H)

Dashboard có hai bảng mới:

- **Nén lâu — chuẩn bị breakout:** Đếm các nến 1H đã đóng liên tục thỏa đồng thời Bollinger Band Width tương đối hẹp (so với 48 giờ trước đó) và biên độ 8H không quá 6%. Ưu tiên khi nén ít nhất 12 giờ, volume tăng tốc, giá chưa tăng nóng và nằm gần kháng cự.
- **Vừa breakout — khả năng tiếp diễn:** Tìm breakout của đỉnh 24H trong 4 nến 1H gần nhất, volume nến breakout >= 1.5 lần trung bình 48 nến trước, có ít nhất 6 nến nén trước breakout và giá hiện tại vẫn giữ gần vùng phá vỡ; kiểm tra RSI, mức tăng và RVOL để tránh mua đuổi.

Ngưỡng là **heuristic thử nghiệm**, chưa có backtest và không phải xác suất tăng giá trong 4 giờ. Không có bảo đảm pump hay dữ liệu OI/Spot CVD. Thời gian nén là số giờ đo được từ dữ liệu nến gần đây, không khẳng định tích lũy thực của cá voi. Một số hợp đồng tài sản truyền thống vẫn có thể chưa được phân loại đúng. Bản Streamlit Cloud quét thủ công và không giám sát liên tục.

## V2.4 — Accuracy Tracker (kiểm định hồi tưởng)

Sau khi **QUÉT NGAY**, mở phần **PRE-PUMP ACCURACY TRACKER** và bấm **CHẠY KIỂM ĐỊNH 4H**. Chọn chốt lời, cắt lỗ, phí/trượt giá và số hợp đồng mẫu. Mỗi tín hiệu được tính bằng dữ liệu nến 1H đã đóng tại thời điểm lịch sử, giá vào ở mở cửa nến kế tiếp. Nếu cùng một nến chạm cả TP và SL, giả định SL khớp trước. Khoảng thời gian mỗi hợp đồng cách nhau ít nhất bốn giờ để giảm chồng lặp.

Bảng thống kê: tổng tín hiệu, tỷ lệ đạt mục tiêu trước stop, lợi nhuận trung bình sau chi phí giả định, profit factor, phân loại nhóm nén lâu/breakout và tải CSV chi tiết. Nếu dữ liệu không đủ hoặc không có tín hiệu, không tính tỷ lệ đúng.

**Cảnh báo:** Đây là kiểm định hồi tưởng có rủi ro điều chỉnh tham số trên cùng tập dữ liệu, KHÔNG phải kiểm định ngoài mẫu, không có nhật ký tín hiệu liên tục 24/7. Streamlit Community Cloud có thể ngủ/khởi động lại; dữ liệu kết quả nằm trong phiên trình duyệt, không lưu bền vững. Số nến gần nhất qua API có hạn; chỉ số không đủ để xác nhận win rate thực tế. Phí mặc định 0,25% gồm ước tính phí + trượt giá hai chiều, chưa tính funding hay độ sâu sổ lệnh.

## V2.5 — Mở rộng dữ liệu Accuracy Tracker

Phần quét thị trường tiếp tục sử dụng lịch sử ngắn. Khi bấm **CHẠY KIỂM ĐỊNH 4H**, chương trình yêu cầu đến **600 nến 1H đã đóng cho mỗi cặp sàn–coin**. OKX sử dụng API history-candles với phân trang theo `after`, MEXC sử dụng tham số start/end; Binance và Bybit dùng endpoint nến tương ứng nhưng vẫn phụ thuộc quyền truy cập từ máy chủ. Mục **Kiểm tra độ phủ dữ liệu kiểm định** hiển thị số nến và số tín hiệu thực tế thu được từng cặp.

Nếu dữ liệu nến đủ nhưng không có sự kiện, đó là kết quả **không tìm thấy mẫu thỏa bộ lọc** — không được tính tỷ lệ đúng bằng 0%. Kiểm định vẫn là hồi tưởng, không phải chứng minh độ chính xác của dự báo và không thay thế kiểm định ngoài mẫu. Nếu hosting bị giới hạn IP/API, phần mềm báo lỗi và không tạo dữ liệu giả.
