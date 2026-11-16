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


## V3.0 — Validation 4H / 8H / 24H và Spot flow mẫu

Ứng dụng giữ V2.5 làm mốc so sánh. Sau khi quét, chọn CHẠY KIỂM ĐỊNH V3.

- Lấy tối đa 900 nến 1H/cặp. Các cửa sổ mô phỏng cách nhau tối thiểu 24H trên mỗi cặp, dùng ít nhất 105 giờ dữ liệu để tạo tín hiệu trước khi xét tương lai.
- Vào tại giá mở nến kế tiếp. Nếu trong cùng nến chạm TP và SL, giả định chạm SL trước.
- Kiểm định 4H với TP +1%, +2%, +3%, +4%; 8H với TP +2%, +4%, +6%; 24H với TP +4%, +6%, +10%. SL mặc định -2%; chi phí giả lập hai chiều 0,25%, chưa tính funding.
- MFE là mức tăng tới đỉnh, MAE là mức giảm tới đáy trong **toàn bộ** horizon kể cả sau khi lệnh giả lập có thể đã đóng. MFE/MAE không phải P&L giao dịch thực.
- Baseline định kỳ thử các cửa sổ mẫu 24H trên cùng các cặp và khoảng thời gian, không phụ thuộc tín hiệu.
- Chia 70% thời gian đầu làm phần phát triển, 30% cuối là phần kiểm tra, có khoảng cách loại trừ 24H quanh mốc chia. Đây KHÔNG phải tập ngoài mẫu nguyên vẹn vì các quy tắc đã bị điều chỉnh dựa vào kết quả quá khứ.
- Chọn top coin hiện tại theo turnover gây thiên lệch chọn mẫu, dữ liệu thiếu tài sản đã hủy niêm yết, và các tín hiệu cùng coin trên nhiều sàn không độc lập hoàn toàn. Các kết quả chỉ mang tính thử nghiệm.

### OI và Spot taker flow tức thời

Chọn **Kiểm tra dòng tiền top 8 quan sát** để thử lấy:
- OI hiện tại từ OKX hoặc MEXC. Đơn vị OKX có thể USD/base coin; MEXC là số hợp đồng. Không so sánh trực tiếp.
- Chênh lệch giá trị mua/bán chủ động trên mẫu tối đa 100 giao dịch Spot gần nhất tại OKX hoặc 500 tại MEXC; hiển thị độ dài thời gian mẫu và số giao dịch. **Không phải Spot CVD 4H** và không được sử dụng làm bằng chứng hồi tưởng trong backtest.
- API bị từ chối hoặc cặp Spot không tồn tại được đánh dấu không khả dụng, không tự chế dữ liệu.

### Kiểm thử

GitHub Actions được cấu hình để biên dịch cú pháp và chạy test không dùng Internet trên Python 3.12 mỗi khi có push lên main. Cần kiểm tra tab **Actions** để xác nhận đã chạy xanh; mã nguồn cập nhật không có nghĩa là deploy hay kiểm thử đã thành công.

**V3 không phải AI đã huấn luyện hay chiến lược đã kiểm chứng lợi nhuận. Không tự động đặt lệnh.**
