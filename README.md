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


## V3.1 — Lưu tín hiệu và dữ liệu dòng tiền theo giờ

**Thiết kế đã thêm, chưa xác nhận workflow đã chạy thành công trên GitHub Actions.**
Bản Streamlit Cloud không có ổ đĩa bền vững, nên workflow riêng trên GitHub cố gắng chạy mỗi giờ (phút 13 UTC), thu thập dữ liệu công khai trên OKX và MEXC cho 15 coin theo danh sách cố định.

- Dữ liệu OI hiện tại được lưu vào data/flow/YYYY-MM.jsonl, khóa duy nhất theo giờ UTC + sàn + coin, không ghi đè lần đầu trong cùng giờ.
- OI OKX sử dụng oiUsd khi có; MEXC ước tính USD = số hợp đồng * contractSize * giá. Đơn vị được ghi trong bản ghi, không cộng trực tiếp giữa sàn.
- Mẫu mua/bán Spot mỗi lần chụp sử dụng tập giao dịch gần nhất, ghi rõ số lượng và khoảng thời gian. **Đây không phải CVD đầy đủ cho giờ đó**.
- Dữ liệu tín hiệu của cùng bộ quy tắc dashboard được ghi vào data/signals/YYYY-MM.jsonl cùng lúc, sử dụng nến 1H đã đóng. Không tự động đặt lệnh.
- Dashboard hiển thị OI thay đổi xấp xỉ 4 giờ chỉ khi có hai quan sát cùng sàn/cặp/đơn vị cách nhau 3–5 giờ. Giá sau khoảng 4H là giá snapshot, không dùng để chứng minh chạm TP trước SL.
- Tín hiệu, dữ liệu, hoặc API lỗi được bỏ qua và ghi lại trong GitHub Actions; không thay dữ liệu thiếu bằng 0.
- GitHub Actions schedule có thể bị trễ, tạm dừng, hoặc thất bại do IP API. Workflow chạy ở github-hosted runner có thể khác IP so với Streamlit Cloud. Nếu không có dữ liệu mới trong 3 giờ, Dashboard cảnh báo dữ liệu cũ.
- Repo public lưu các mẫu **dữ liệu thị trường công khai**, không lưu API key hay tài khoản giao dịch.

### Bật lịch ghi tự động

1. Mở GitHub -> repository -> **Actions** -> workflow **Archive public market-flow snapshots**.
2. Chọn **Run workflow** thủ công lần đầu để thử kết nối và ghi file. Quan sát run xanh, phần log WARN nếu API lỗi.
3. Nếu push dữ liệu thất bại do không có quyền, vào **Settings -> Actions -> General -> Workflow permissions**, cho phép **Read and write permissions** (nếu tổ chức cho phép).
4. Kiểm tra đã xuất hiện các file data/flow/YYYY-MM.jsonl và data/signals/YYYY-MM.jsonl. Sau 4–5 lần chạy thành công mới có thể thấy OI ~4H.
5. Mỗi lần thêm file lên main có thể khiến Streamlit Cloud cập nhật/redeploy lại.

### Kiểm thử

Workflow **Validate Pre-Pump Scanner V3** chạy compileall và unittest đối với các thư viện V3.1. Chỉ coi hoạt động ổn định khi có workflow xanh và quan sát các giờ lưu thực tế. Dữ liệu lịch sử mới bắt đầu từ lần thu thập thành công đầu tiên, không hồi tố.


## V3.2 — Pre-Pump Confirmation (sơ bộ, không phải dự báo xác suất)

Trên Dashboard, bảng **V3.2 — PRE-PUMP CONFIRMATION** đứng trước bảng Top Coin. Mỗi coin chỉ được đưa vào danh sách đồng thuận sơ bộ khi đồng thời có:

- Cấu trúc kỹ thuật đang tích lũy / nén lâu ưu tiên / vừa breakout còn lực tiếp diễn trên ít nhất hai sàn.
- Bản ghi OI/Spot **không quá 2,5 giờ** tại thời điểm kiểm tra.
- Mỗi sàn có quan sát OI cùng đơn vị khoảng 3–5 giờ trước, mức OI tăng tối thiểu **+3%**.
- Mỗi sàn có **mẫu giao dịch Spot** tối thiểu 50 trades, mẫu kéo dài tối thiểu 0,25 phút, và imbalance mua chủ động ít nhất **+10%**. Mẫu này không đại diện cho toàn bộ 4 giờ.
- Hai sàn **đều** đạt mọi điều kiện nói trên; hai tín hiệu đơn lẻ hoặc khác pha không được cộng điểm.

Không đủ nguồn OI, Spot, thiếu lịch sử, dữ liệu cũ, lỗi API, hay chỉ có một sàn -> **CHƯA XÁC NHẬN**. Tại nút mở rộng, xem lý do của từng mã. Điểm kỹ thuật V3.1 không bị sửa hoặc dùng để giả làm xác suất.

Đây là bộ lọc thử nghiệm, không tự đặt lệnh, không chứng minh có cá voi tích trữ, không có full Spot CVD và chưa được backtest độc lập. Cần tiếp tục thu thập mẫu mới và kiểm chứng trước khi sử dụng vốn thật.


## V3.2.1 — OKX HTTP 429 và cảnh báo DOGE nén trong xu hướng giảm

- Sửa việc yêu cầu nến lịch sử OKX: **mỗi trang tối đa 100 nến**, phân trang bằng after; trước đây một số trang yêu cầu tới 300 và phần cuối còn tạo truy vấn 1 nến. OKX giới hạn endpoint history-candles theo IP.
- Bổ sung tốc độ yêu cầu tối thiểu cách nhau ~0,24 giây trên cùng tiến trình, tối đa 3 lần thử khi gặp HTTP 429, tôn trọng Retry-After trong giới hạn an toàn và giảm số luồng đồng thời từ 6 xuống 3 cho scan, từ 4 xuống 2 cho backtest. Có cache nến 10 phút theo symbol/lookback. **Không bảo đảm hết 429** nếu nhiều người dùng hoặc host chia sẻ IP.
- HTTP 451/403 của Binance/Bybit là chặn truy cập tại máy chủ và không được né chặn. Các endpoint lỗi được ghi rõ, không giả mạo dữ liệu.
- Bộ điểm gốc giữ nguyên để so sánh các nghiên cứu đã thực hiện. Thêm cảnh báo **giá dưới EMA50 đang giảm** (EMA50 hiện dưới EMA50 cách 12 nến 1H) để nhận diện trường hợp nén giá sau giảm mạnh; bảng tổng hợp hạ nhóm ưu tiên trình bày, và Pre-Pump Confirmation không xác nhận các sàn có cảnh báo này. EMA50 không chứng minh đáy thị trường.
- Nếu thiếu dữ liệu để xác định xu hướng, không được kết luận chắc chắn có pump. Không sử dụng để giao dịch tự động.


## Giao diện đơn giản — 3 trạng thái (V3.2.2)

Màn hình chính hiển thị **một bảng coin**, gộp theo mã, với đúng ba trạng thái dễ quan sát:

1. **Nén trong xu hướng giảm:** Có cảnh báo giá dưới EMA50 và EMA50 đang đi xuống. Không coi đây là Pre-Pump đã xác nhận.
2. **Tích lũy — có dấu hiệu đảo chiều:** Setup tích lũy hoặc breakout sớm không có cảnh báo xu hướng giảm; **mới là nhóm theo dõi**, chưa chứng minh đảo chiều.
3. **Breakout — dòng tiền xác nhận:** Có breakout kỹ thuật tiếp diễn, và bộ kiểm tra V3.2 xác nhận sơ bộ OI + Spot mẫu đồng thuận tối thiểu hai sàn. Không phải dự báo chắc chắn hay xác suất thắng.

Những coin chưa đủ điều kiện lọc không xuất hiện ở bảng chính. Phần trạng thái kết nối, bảng Pre-Pump cũ, OI, nhật ký, kiểm định và lỗi API vẫn có thể xem tại **Phân tích nâng cao**, mặc định đóng. Giữ nguyên bộ điểm và dữ liệu nghiên cứu; đây chỉ là thay đổi giao diện và phân loại theo quy tắc.


## MEXC Fast-Mover — tìm biến động sớm 5–15 phút

Giao diện giữ nguyên một bảng chính với 3 trạng thái. Mở mục **MEXC FAST-MOVER** ngay dưới bảng để chạy quét độc lập. Bấm **QUÉT BIẾN ĐỘNG NHANH MEXC**.

- Dùng ticker Futures MEXC (24H turnover, change24) để chọn nhóm có thanh khoản, nhóm tăng vừa phải và một phần nhóm tăng mạnh. Đây là *mẫu* tối đa 15–70 hợp đồng, không quét toàn sàn, không đảm bảo tìm mọi coin.
- Tải nến Futures **Min5 đã đóng**, tính biến động 5m, 15m, 1H; RVOL 15 phút (trung bình 3 nến gần nhất so với trung bình 36 nến trước đó), turnover 15 phút và mức vượt vùng đỉnh gần nhất.
- **Tăng tốc sớm — theo dõi**: RVOL ít nhất 1,7 lần, turnover 15m ít nhất 15.000 USDT, biến động 15m từ +0,4% đến +4%, 1H từ +0,6% đến +7%; giá gần/đã vượt vùng đỉnh cũ và giá 24H chưa tăng trên 18%.
- **Volume tăng — chờ phá cản**: Có volume bất thường, giá bắt đầu tăng nhưng chưa đầy đủ điều kiện trên.
- **Đã pump — tránh mua đuổi**: Giá tăng quá xa trong 5m/15m/1H hoặc +25% trong 24H. Đây là cảnh báo truy đuổi, không phải lệnh Short.
- Chỉ hiện các hợp đồng có ít nhất 40 nến Min5 hợp lệ; lỗi API xuất hiện trong mục chẩn đoán, không tạo dữ liệu giả. Điểm hoạt động 0–100 là quy tắc thủ công chưa hiệu chỉnh, không phải xác suất pump.
- **Quan trọng:** Fast-Mover hiện **quét thủ công** khi bạn nhấn nút, không tự giám sát liên tục hay gửi thông báo đẩy. Nếu MEXC đổi API / chặn hosting thì có thể không có kết quả. API có giới hạn tốc độ; chọn 35 hợp đồng lúc đầu.
- Danh sách loại trừ tài sản cổ phiếu theo mã còn hạn chế; không có bảo đảm 100% hợp đồng là crypto.


## V3.3 — Toàn thị trường MEXC: gia tốc giá 5/15/60 phút

Bộ theo dõi mới dùng một yêu cầu ticker MEXC Futures toàn sàn mỗi lần thu thập và một yêu cầu metadata; không giới hạn top 15 coin trước khi phân tích. Giữ hợp đồng USDT được phép và turnover 24H >= 100.000 USDT, trừ một số mã cổ phiếu trong danh sách loại trừ sơ bộ (không phải phân loại tài sản chính thức).

GitHub Actions workflow **MEXC five-minute price acceleration watch** (.github/workflows/mexc-velocity.yml) lên lịch mỗi 5 phút và có nút Run workflow chạy tay. GitHub Actions có thể chạy trễ, bỏ lượt hoặc bị giới hạn theo IP; không phải hệ thống live từng giây.

Lưu snapshot tại data/mexc_velocity/history.json (tối đa 28 mốc gần nhất) và bảng kết quả tại data/mexc_velocity/latest.json. Cần đủ snapshot theo thời gian để tính đúng biến động 5 phút, 15 phút và 1 giờ. Khi thiếu mốc, để trống, không tự suy đoán.

Trạng thái:
- MỚI TĂNG TỐC — THEO DÕI: giá 5m tăng >=0,35%; 15m tăng 0,7–4%; 24h chưa tăng quá 18%; 1H chưa quá +8% nếu đủ dữ liệu.
- ĐANG NHÍCH LÊN — CHỜ XÁC NHẬN: tăng tối thiểu 0,4% trong 15 phút nhưng chưa đủ tiêu chuẩn tăng tốc.
- ĐÃ TĂNG NÓNG — KHÔNG MUA ĐUỔI: 24H >=+25%, 15m >+7% hoặc 1H >=+12%. Không phải tín hiệu bán khống.

Chỉ dùng giá ở các lần chụp, không dùng CVD, không thể biết đỉnh/đáy giữa các lần. Tín hiệu chưa backtest và điểm không phải xác suất pump. Màn hình chính hiển thị tối đa 15 coin mới tăng tốc; các nhóm khác được thu gọn. Nếu dữ liệu cũ hơn 11 phút, báo cảnh báo và không nên coi là tín hiệu đang diễn ra.

Repo có thể phình to và Streamlit có thể redeploy nhiều lần nếu commit mỗi 5 phút. Khi sử dụng lâu dài nên chuyển việc lưu trữ sang database/dịch vụ nền riêng.


## Windows Portable ZIP (không cần cài Python)

Có hai cách:

1. **Bản Portable hoàn chỉnh:** mở GitHub Actions > Build Windows Portable ZIP > chọn lần chạy thành công > trong phần Artifacts tải **PrePumpScanner_Windows_x64_Portable**. File ZIP được tạo trực tiếp bởi Windows runner, có sẵn Python 3.12 nhúng, packages, mã nguồn, START.bat, HUONG_DAN.txt. Giải nén vào Windows 10/11 x64 rồi nhấp đúp START.bat. Không cần cài Python riêng. Workflow có nút Run workflow và cũng tự chạy khi script đóng gói hoặc workflow thay đổi.
2. **Bản ZIP khởi tạo (bootstrap):** file ZIP nhỏ tạo bên ngoài GitHub Actions, lần chạy START.bat đầu tiên sẽ tải code từ nhánh main, Python Windows embedded và thư viện Python về cùng thư mục. Bản này cần Internet khi chạy lần đầu, nhưng sau khi hoàn tất có thể sao chép toàn bộ thư mục sang máy Windows 64-bit khác mà không cần cài Python.

**Lưu ý:** Không coi bản ZIP đã đóng hoàn chỉnh cho tới khi workflow chạy xanh. Công cụ còn cần mạng để lấy dữ liệu thị trường, và API các sàn có thể chặn IP. File ZIP của GitHub Actions có thời hạn lưu trữ, nên tải về máy để lưu lâu dài. Các file dữ liệu GitHub mới phát sinh sau ngày build không tự đồng bộ vào bản portable.


## V3.4 — Early-Pump 1M/3M, tránh phát hiện sau bốn cây nến

**Tín hiệu quan sát, không phải dự đoán đã kiểm chứng.**
GitHub Actions MEXC five-minute price acceleration watch chạy thêm module mexc_early.py sau khi lấy ticker toàn sàn. Từ vũ trụ hợp đồng USDT có thanh khoản phù hợp, chỉ kiểm tra tối đa **24 cặp** có biến động snapshot 5m vừa xuất hiện, volume 24H cao hoặc đang tăng vừa phải; không thể phát hiện mọi coin trên MEXC. Mỗi cặp cần >=40 nến Min1 **đã đóng**, còn mới, liên tục. Lịch 5 phút vẫn có thể bỏ lỡ cú tăng xảy ra và kết thúc giữa hai lần chạy.

- Mới bật lên — 1–2 nến: nến xanh gần nhất 1 hoặc 2, giá 1M tăng 0,2–1,5%; 3M tăng 0,3–2%; RVOL 1M >=1,5; turnover 3M >=3.000 USDT; giá cách kháng cự trước (đỉnh cũ 30 phút) từ -1% đến +1,8%, tăng từ đáy 30 phút **không quá 2,5%**; 15M tăng không quá 3%, 24H chưa tăng quá 15%.
- Dòng tiền nhích lên — theo dõi: có RVOL + biến động 3M nhưng chưa đủ điều kiện sớm. **RVOL Futures không chứng minh có lực mua Spot.**
- Đã chạy xa — không mua đuổi: tăng >=5% từ đáy 30m, 15M >=6%, 3M >=3%, 24H >=25%, hoặc >=4 nến xanh liên tiếp.

Đáy và đỉnh gần đây chỉ tính từ nến đã đóng ở thời điểm phát tín hiệu, không có dùng dữ liệu tương lai. Tín hiệu chụp thời gian thực được lưu ở data/mexc_velocity/latest_early.json, hiển thị tại đầu website. Không có AI đã hiệu chỉnh xác suất. Để đánh giá hiệu quả thực cần lưu tín hiệu đầu tiên và theo dõi giá 15M, 1H, 4H sau khi ghi nhận, tránh chỉ phân tích coin đã pump.

**Vận hành:** Lịch GitHub Actions 5 phút không bảo đảm thực thi đúng giờ. Nếu xuất hiện HTTP 429 hoặc bộ quét 1M không lấy được nến hợp lệ, website báo lỗi rõ; phiên quét không tạo tín hiệu giả. Workflow Build Windows Portable ZIP cần chạy lại để chứa module mới.
