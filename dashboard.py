"""Live Streamlit dashboard backed by durable local CSV data."""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import SETTINGS


st.set_page_config(page_title="IoT Lab 2 · Giám sát cảm biến", page_icon="🌡️", layout="wide")
st.title("Giám sát cảm biến IoT")
st.caption("ESP32 DevKit V1 · PIR · DHT22 · LED · MQTT · InfluxDB | Tự làm mới mỗi 5 giây")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        result = pd.read_csv(path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, OSError):
        return pd.DataFrame()
    if "time" in result:
        result["time"] = pd.to_datetime(result["time"], utc=True, errors="coerce")
        result = result.dropna(subset=["time"]).sort_values("time")
    return result


def gauge(value: float, title: str, suffix: str, lower: float, upper: float, color: str) -> go.Figure:
    figure = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"suffix": suffix, "font": {"size": 25}},
        title={"text": title, "font": {"size": 16}},
        gauge={"axis": {"range": [lower, upper]}, "bar": {"color": color},
               "bgcolor": "#e9eff4", "borderwidth": 0},
    ))
    figure.update_layout(height=220, margin=dict(l=18, r=18, t=35, b=10))
    return figure


def line_chart(frame: pd.DataFrame, fields: list[str], labels: dict[str, str], title: str) -> go.Figure:
    figure = go.Figure()
    colors = ["#e85d5d", "#3b82f6", "#eab308"]
    for index, field in enumerate(fields):
        if field in frame:
            figure.add_trace(go.Scatter(x=frame["time"], y=frame[field], mode="lines+markers", name=labels.get(field, field), line={"color": colors[index % len(colors)]}))
    figure.update_layout(title=title, height=390, xaxis_title="Thời gian (UTC)", hovermode="x unified", margin=dict(l=20, r=20, t=45, b=20))
    return figure


@st.fragment(run_every="5s")
def live_dashboard() -> None:
    raw_path = SETTINGS.data_dir / SETTINGS.raw_csv_name
    sample_path = SETTINGS.data_dir / SETTINGS.sample_csv_name
    real = read_csv(raw_path)
    if not real.empty:
        raw = real
        source = "Dữ liệu MQTT thực (CSV cục bộ)"
    else:
        raw = read_csv(sample_path)
        source = f"Dữ liệu mô phỏng từ {SETTINGS.sample_csv_name}"
    if raw.empty:
        st.info("Chưa có dữ liệu. Chạy `python mqtt_to_influxdb.py` và Wokwi, hoặc `python data_preprocessing.py` để tạo mẫu minh họa.")
        return

    devices = sorted(raw["device_id"].dropna().unique().tolist())
    chosen = st.selectbox("Thiết bị", devices)
    raw = raw[raw["device_id"] == chosen].copy()
    if "DEMO" in chosen:
        source = "Dữ liệu mô phỏng gửi qua MQTT (thiết bị DEMO)"
    for field in ("temperature", "humidity", "motion", "rssi"):
        raw[field] = pd.to_numeric(raw[field], errors="coerce")
    latest = raw.iloc[-1]
    latest_local = latest["time"].tz_convert("Asia/Bangkok").strftime("%d/%m/%Y %H:%M:%S")
    st.caption(f"Nguồn: {source} · {len(raw)} bản ghi · Mới nhất: {latest_local} (ICT)")

    cards = st.columns(4)
    values = [
        ("Nhiệt độ", "temperature", "°C", -40, 60, "#e85d5d"),
        ("Độ ẩm", "humidity", "%RH", 0, 100, "#3b82f6"),
        ("RSSI", "rssi", " dBm", -120, 0, "#10b981"),
    ]
    for card, (label, field, unit, lower, upper, color) in zip((cards[0], cards[1], cards[3]), values):
        value = latest[field]
        with card:
            if pd.notna(value):
                st.plotly_chart(gauge(float(value), label, unit, lower, upper, color), width="stretch", key=f"gauge-{field}")
            else:
                st.metric(label, "N/A")
    with cards[2]:
        motion = latest["motion"]
        st.metric("PIR / LED", "Phát hiện chuyển động · LED sáng" if motion == 1 else "Không có chuyển động · LED tắt")
        st.caption("1 = phát hiện, 0 = không phát hiện")

    tab_env, tab_motion, tab_compare, tab_stats = st.tabs(["Nhiệt độ & độ ẩm", "PIR & RSSI", "Thô và đã xử lý", "Thống kê & bản ghi"])
    with tab_env:
        st.plotly_chart(line_chart(raw, ["temperature", "humidity"], {"temperature": "Nhiệt độ (°C)", "humidity": "Độ ẩm (%RH)"}, "Dữ liệu cảm biến theo thời gian"), width="stretch")
    with tab_motion:
        motion_chart = go.Figure(go.Scatter(x=raw["time"], y=raw["motion"], mode="lines+markers", line={"shape": "hv", "color": "#eab308"}, name="PIR"))
        motion_chart.update_layout(title="Trạng thái chuyển động", height=330, yaxis={"tickvals": [0, 1], "ticktext": ["Không", "Có"], "range": [-0.1, 1.1]}, xaxis_title="Thời gian (UTC)")
        st.plotly_chart(motion_chart, width="stretch")
        st.plotly_chart(line_chart(raw, ["rssi"], {"rssi": "RSSI (dBm)"}, "Tín hiệu Wi-Fi"), width="stretch")
    with tab_compare:
        processed = read_csv(SETTINGS.data_dir / SETTINGS.processed_csv_name)
        if processed.empty:
            st.info("Chạy `python data_preprocessing.py` để tạo dữ liệu đã xử lý.")
        else:
            processed = processed[processed["device_id"] == chosen]
            if processed.empty:
                st.info("Chưa có dữ liệu xử lý cho thiết bị này.")
            else:
                compare = go.Figure()
                compare.add_trace(go.Scatter(x=raw["time"], y=raw["temperature"], name="Nhiệt độ thô", mode="lines", line={"color": "#b7c2d0", "width": 1}))
                compare.add_trace(go.Scatter(x=processed["time"], y=processed["temperature"], name="Nhiệt độ sau xử lý (trung bình 1 phút)", mode="lines+markers", line={"color": "#e85d5d", "width": 3}))
                compare.update_layout(height=420, xaxis_title="Thời gian (UTC)", yaxis_title="°C", hovermode="x unified")
                st.plotly_chart(compare, width="stretch")
                if "motion_events" in processed:
                    st.bar_chart(processed.set_index("time")["motion_events"], y_label="Lượt bắt đầu chuyển động / phút")
                st.caption("Dữ liệu đã xử lý cập nhật khi chạy lại data_preprocessing.py.")
    with tab_stats:
        st.subheader("Thống kê dữ liệu thô")
        st.dataframe(raw[["temperature", "humidity", "motion", "rssi"]].describe(), width="stretch")
        processed = read_csv(SETTINGS.data_dir / SETTINGS.processed_csv_name)
        if not processed.empty:
            processed = processed[processed["device_id"] == chosen]
            if not processed.empty:
                st.subheader("Thống kê dữ liệu đã xử lý")
                st.dataframe(processed[["temperature", "humidity", "motion_ratio", "motion_events", "rssi"]].describe(), width="stretch")
        st.subheader("20 bản ghi gần nhất")
        st.dataframe(raw.sort_values("time", ascending=False).head(20), width="stretch", hide_index=True)


live_dashboard()
