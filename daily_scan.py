import os
import json
import socket
import datetime
import requests
import pandas as pd
import yfinance as yf
import urllib3.util.connection as urllib3_cn

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "")
DB_ALERTS = "user_alerts_config.json"

TW_BROAD_POOL = [
    "1504.TW", "1519.TW", "1605.TW", "2313.TW", "2368.TW",
    "2520.TW", "2609.TW", "2618.TW", "3017.TW", "3231.TW",
    "3324.TW", "8996.TW", "9958.TW", "2308.TW", "2376.TW"
]
US_BROAD_POOL = [
    "FOUR", "VRT", "ONON", "CELH", "ELF", "UBER", "HOOD",
    "RDDT", "WING", "DKNG", "PLTR", "DDOG", "CRWD", "ARM"
]

def _split_chunks(text, limit=1900):
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks

def send_discord(text):
    if not WEBHOOK_URL:
        print("❌ 未設定 DISCORD_WEBHOOK_URL")
        return
    orig_family = urllib3_cn.allowed_gai_family
    urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
    try:
        for chunk in _split_chunks(text):
            res = requests.post(
                WEBHOOK_URL,
                json={"content": chunk, "username": "StockRadar 盤後排程"},
                timeout=15
            )
            if res.status_code not in (200, 204):
                print(f"❌ Discord 發送失敗 ({res.status_code}): {res.text[:120]}")
    finally:
        urllib3_cn.allowed_gai_family = orig_family

def get_tw_names():
    try:
        res = requests.get("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo", timeout=5).json()
        if res.get("msg") == "success" and "data" in res:
            df = pd.DataFrame(res["data"])
            return dict(zip(df["stock_id"].astype(str), df["stock_name"]))
    except Exception:
        pass
    return {}

def calculate_indicators(df):
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()
    df["Vol_MA5"] = df["Volume"].rolling(5).mean()
    df["Low_10"] = df["Low"].rolling(10).min()
    df["Return_20d"] = (df["Close"] / df["Close"].shift(20) - 1) * 100
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))
    return df

def check_stealth_radar(pool, is_tw, tw_names):
    hits = []
    for ticker in pool:
        try:
            df = yf.Ticker(ticker).history(period="6mo")
            if len(df) < 60:
                continue
            df = calculate_indicators(df)
            latest = df.iloc[-1]
            price = float(latest["Close"])
            ma20 = float(latest["MA20"])
            ma60 = float(latest["MA60"])
            ret_20d = float(latest["Return_20d"])

            is_long_uptrend = price > ma60
            near_support = (ma20 * 0.98) <= price <= (ma20 * 1.05)
            is_stealth = 0 < ret_20d <= 15

            if is_long_uptrend and near_support and is_stealth:
                code = ticker.replace(".TW", "").replace(".TWO", "")
                label = f"{code} {tw_names.get(code, '')}".strip() if is_tw else ticker
                curr = "" if is_tw else "$"
                hits.append(
                    f"• **{label}**｜現價 {curr}{price:.2f}｜月線支撐 {curr}{ma20:.2f}｜停損 {curr}{ma20*0.97:.2f} / 停利 {curr}{price*1.30:.2f}"
                )
        except Exception:
            continue
    return hits

def check_smart_alerts(config, is_tw_filter, tw_names):
    alerts = []
    today = datetime.date.today()
    for ticker, settings in config.items():
        is_tw_stock = ticker.endswith(".TW") or ticker.endswith(".TWO")
        if is_tw_stock != is_tw_filter:
            continue
        try:
            df = yf.Ticker(ticker).history(period="6mo")
            if len(df) < 60:
                continue
            df = calculate_indicators(df)
            latest, prev = df.iloc[-1], df.iloc[-2]

            price = float(latest["Close"])
            ma20 = float(latest["MA20"])
            low_10 = float(latest["Low_10"])
            vol_surge = latest["Volume"] > (latest["Vol_MA5"] * 1.3)

            status = settings.get("status", "observing")
            cost = float(settings.get("cost", 0.0))
            note = settings.get("note", "")
            target_price = float(settings.get("target_price", 0.0))
            reminder_date_str = settings.get("reminder_date", "")

            stage, reason, action = None, None, None
            if status == "holding" and cost > 0:
                if price < cost * 0.9 or price < ma20:
                    stage = "🔴 持股風險升高 (趨勢轉弱)"
                    reason = f"股價 ({price:.2f}) 跌破防守線或 20MA ({ma20:.2f})"
                    action = "請檢查持股風險、原定停損條件及部位大小。"
                elif price > ma20 and vol_surge and latest["Close"] > prev["High"]:
                    stage = "🟢 趨勢轉強 (加碼評估)"
                    reason = f"股價 ({price:.2f}) 帶量突破前日高點且站穩 20MA"
                    action = "可評估是否符合加碼計畫並確認停損距離。"
            elif status == "observing":
                near_low = price <= (low_10 * 1.03)
                if price > ma20 and vol_surge and latest["RSI"] > 50:
                    stage = "🎯 反彈確認 (可評估進場)"
                    reason = f"股價 ({price:.2f}) 帶量突破 20MA 且 RSI 站上 50"
                    action = "可評估小量試單，停損設於起漲點下方。"
                elif near_low and latest["Close"] >= prev["Close"] and latest["Low"] >= prev["Low"]:
                    stage = "🟡 初步止跌 (觀察中)"
                    reason = f"股價 ({price:.2f}) 接近近期低點且連兩日未破低"
                    action = "先觀察是否帶量突破短期下降趨勢線，不急著摸底。"

            custom_hits = []
            if reminder_date_str:
                t_date = datetime.datetime.strptime(reminder_date_str, "%Y-%m-%d").date()
                if today >= t_date:
                    custom_hits.append(f"📅 日期觸發：關鍵觀察日 ({reminder_date_str}) 已到達")
            if target_price > 0:
                if status == "observing" and price <= target_price:
                    custom_hits.append(f"💰 價格觸發：現價 ({price:.2f}) 已達預期進場價 ({target_price})")
                elif status == "holding" and price >= target_price:
                    custom_hits.append(f"💰 價格觸發：現價 ({price:.2f}) 已達停利目標價 ({target_price})")

            if stage or custom_hits:
                code = ticker.replace(".TW", "").replace(".TWO", "")
                label = f"{code} {tw_names.get(code, '')}".strip() if is_tw_stock else ticker
                header = f"**🚨 {label} - {stage or '🔔 自訂條件觸發'}**"
                lines = [header]
                for ch in custom_hits:
                    lines.append(f"• {ch}")
                if reason:
                    lines.append(f"• **狀況**：{reason}")
                    lines.append(f"• **建議**：{action}")
                if note:
                    lines.append(f"• **筆記**：{note}")
                alerts.append("\n".join(lines))
        except Exception:
            continue
    return alerts

def run_market(is_tw, tw_names, config):
    today_str = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
    market_title = "🇹🇼 台股盤後自動掃描" if is_tw else "🇺🇸 美股盤後自動掃描"
    pool = TW_BROAD_POOL if is_tw else US_BROAD_POOL

    alerts = check_smart_alerts(config, is_tw, tw_names)
    radar_hits = check_stealth_radar(pool, is_tw, tw_names)

    sections = [f"**{market_title} ({today_str})**"]
    if alerts:
        sections.append("\n**🔔 個人監控警報**\n" + "\n\n".join(alerts))
    else:
        sections.append("\n🔔 個人監控清單今日無異常或價格觸發。")

    if radar_hits:
        sections.append("\n**🌟 隱藏多頭回踩 20MA 標的**\n" + "\n".join(radar_hits))
    else:
        sections.append("\n🌟 隱藏多頭掃描池今日無符合買點之標的。")

    send_discord("\n".join(sections))

if __name__ == "__main__":
    config = {}
    if os.path.exists(DB_ALERTS):
        with open(DB_ALERTS, "r", encoding="utf-8") as f:
            config = json.load(f)

    tw_names = get_tw_names()
    utc_hour = datetime.datetime.utcnow().hour

    if EVENT_NAME == "workflow_dispatch":
        run_market(True, tw_names, config)
        run_market(False, tw_names, config)
    elif 6 <= utc_hour <= 14:
        run_market(True, tw_names, config)
    else:
        run_market(False, tw_names, config)
