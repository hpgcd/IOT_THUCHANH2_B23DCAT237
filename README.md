# Bài thực hành 2: ESP32 DevKit V1 + PIR + DHT22 + LED

ESP32 gửi nhiệt độ, độ ẩm và trạng thái chuyển động qua MQTT. Python lưu dữ liệu vào CSV và InfluxDB; Streamlit hiển thị kết quả. LED sáng khi PIR phát hiện chuyển động.

## 1. Khởi động hệ thống

Cần cài Python và Docker Desktop. Mở PowerShell tại `F:\IOT2`:

```powershell
python -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d
python mqtt_to_influxdb.py
```

Giữ cửa sổ này chạy để thu dữ liệu. Chỉ chạy **một** collector. Nếu Docker báo cổng 1883 đã được dùng, sửa `MOSQUITTO_PORT=1884` trong `.env` rồi chạy lại `docker compose up -d`.

## 2. Chạy mạch trên Wokwi

Tạo dự án ESP32 trên Wokwi, thay nội dung các file `sketch.ino`, `diagram.json`, `libraries.txt` bằng file cùng tên trong thư mục này, rồi nhấn **Play**.

| Linh kiện | Chân ESP32 |
| --- | --- |
| DHT22 SDA | D15 |
| DHT22 VCC / GND | 3V3 / GND |
| PIR OUT | D27 |
| PIR VCC / GND | VIN / GND |
| LED | D2 → điện trở 220 Ω → chân A; chân C → GND |

Trong Wokwi, nhấn **Simulate Motion** trên PIR. LED sáng khi có chuyển động. Serial Monitor cần hiện `[MQTT] Connected`, `[MQTT] Published` và JSON có `"motion":1` hoặc `"motion":0`.

## 3. Xử lý và xem dữ liệu

Mở PowerShell thứ hai tại `F:\IOT2`. Sau khi Wokwi đã gửi dữ liệu, chạy:

```powershell
python data_preprocessing.py --source influx --hours 24
streamlit run dashboard.py --server.address 127.0.0.1
```

Mở dashboard tại <http://127.0.0.1:8501>. Dữ liệu thô nằm ở `data/pir_raw_data.csv`, dữ liệu đã xử lý ở `data/pir_processed_data.csv`, độ trễ ở `data/pir_write_metrics.csv`. InfluxDB mở tại <http://127.0.0.1:8086>.

## 4. Báo cáo

- [Báo cáo Word](bao_cao/Bao_cao_Bai_2_IoT_B23DCAT237_PIR.docx)
- [Hướng dẫn chụp H1–H6](bao_cao/ANH_CAN_CHUP_PIR.md)

Báo cáo còn ô chờ ảnh và bảng số liệu DEMO. Trước khi nộp, chèn ảnh Wokwi thật và cập nhật số liệu nếu dùng dữ liệu đo mới.

Kết thúc: nhấn **Ctrl+C** ở collector và dashboard, sau đó chạy `docker compose down`.
