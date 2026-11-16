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
