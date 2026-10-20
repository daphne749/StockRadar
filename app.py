import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import json
import os
import requests
import urllib.parse

# === 1. 網頁全域設定與手機端按鈕優化 ===
st.set_page_config(page_title="專業波段選股系統", page_icon="📈", layout="wide")

st.markdown("""
<style>
.stButton>button {border-radius: 8px; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

st.title("📈 雙引擎波段選股雷達")
st.markdown("💰 **資金風控**：每單 30,000 TWD | 🎯 **核心策略**：20MA 回調買入 + 30% 停利 + 智慧情境監控")

# === 內建台股中文名稱全自動動態字典 ===
@st.cache_data(ttl=86400) 
def get_all_tw_stock_names():
    url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get("msg") == "success" and "data" in res:
            df = pd.DataFrame(res["data"])
            return dict(zip(df['stock_id'].astype(str), df['stock_name']))
    except:
        pass
    return {
        "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2308": "台達電", "2382": "廣達",
        "2303": "聯電", "2881": "富邦金", "2891": "中信金", "2603": "長榮", "3231": "緯創",
        "2345": "智邦", "2356": "英業達", "2376": "技嘉", "1519": "華城", "3017": "奇鋐",
        "3324": "雙鴻", "1504": "東元", "1605": "華新", "2609": "陽明", "2618": "長榮航"
    }

TW_STOCK_NAMES = get_all_tw_stock_names()

# === 2. 記憶體資料庫與 UI 狀態控制 ===
DB_ALERTS = "user_alerts_config.json"
DB_WATCHLISTS = "watchlists.json"

def load_json(file_path, default_data):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f: return json.load(f)
    return default_data

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

if 'user_config' not in st.session_state:
    st.session_state['user_config'] = load_json(DB_ALERTS, {})

if 'watchlists' not in st.session_state:
    default_wl = {"TW": ["2330.TW", "2454.TW", "2603.TW", "1519.TW"], "US": ["AAPL", "MSFT", "NVDA", "COIN"]}
    st.session_state['watchlists'] = load_json(DB_WATCHLISTS, default_wl)

if 'tw_edit_key' not in st.session_state: st.session_state.tw_edit_key = 0
if 'us_edit_key' not in st.session_state: st.session_state.us_edit_key = 0

# === 3. 核心指標與新聞探勘模組 ===
def calculate_indicators(df):
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA60"] = df["Close"].rolling(60).mean()
    df["Vol_MA5"] = df["Volume"].rolling(5).mean()
    df["High_10"] = df["High"].rolling(10).max()
    df["Low_10"] = df["Low"].rolling(10).min()
    df["Return_20d"] = (df["Close"] / df["Close"].shift(20) - 1) * 100
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def fetch_news_text(ticker, is_tw):
    search_term = ticker.replace(".TW", "") + (" 股票" if is_tw else " stock news")
    query = urllib.parse.quote(search_term)
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW"
    try:
        res = requests.get(url, timeout=3)
        return res.text
    except:
        return ""

def check_future_potential(news_text, eps_growth):
    keywords = ["受惠", "成長", "訂單", "創新高", "潛力", "看好", "升評", "AI", "轉型", "突破", "大增", "爆發"]
    score = sum(news_text.count(kw) for kw in keywords)
    if score >= 5 or eps_growth > 20: return "🔥 題材熱絡 (具未來性)"
    elif score >= 2: return "🟡 具備話題"
    return "⚪ 暫無明顯題材"

@st.cache_data(ttl=1800)
def get_finmind_chips(ticker, days=5):
    if not ticker.endswith(".TW"): return {"外資買賣超": 0, "投信買賣超": 0, "狀態": "美股不適用"}
    stock_id = ticker.replace(".TW", "")
    start_date = (datetime.date.today() - datetime.timedelta(days=days+6)).strftime("%Y-%m-%d")
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={stock_id}&start_date={start_date}"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get("msg") == "success" and len(res.get("data", [])) > 0:
            df_chips = pd.DataFrame(res["data"])
            recent_dates = df_chips['date'].unique()[-days:]
            df_chips = df_chips[df_chips['date'].isin(recent_dates)]
            foreign = int(df_chips[df_chips["name"] == "外資及陸資(不含外資自營商)"]["buy_sell"].sum() // 1000)
            trust = int(df_chips[df_chips["name"] == "投信"]["buy_sell"].sum() // 1000)
            status = "🔥 大人連買" if (foreign + trust) > 500 else "🧊 遭逢調節" if (foreign + trust) < -500 else "⚪ 籌碼中性"
            return {"外資近5日(張)": foreign, "投信近5日(張)": trust, "狀態": status}
    except:
        pass
    return {"外資近5日(張)": 0, "投信近5日(張)": 0, "狀態": "無資料/頻率限制"}

# === 4. 整合分析引擎 ===
@st.cache_data(ttl=1800)
def analyze_stock_master(ticker, is_tw=True, max_price=99999, min_foreign=0, min_trust=0, filter_stealth=False):
    stock = yf.Ticker(ticker)
    try:
        df = stock.history(period="6mo")
        if len(df) < 60: return None
    except: return None
        
    latest_price = df.iloc[-1]["Close"]
    if latest_price > max_price: return None
        
    df = calculate_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    pct_change = ((latest_price - prev["Close"]) / prev["Close"]) * 100
    month_return = latest["Return_20d"]
    ma20 = latest["MA20"]
    ma60 = latest["MA60"]

    if filter_stealth:
        is_long_uptrend = latest_price > ma60
        near_support = (ma20 * 0.98) <= latest_price <= (ma20 * 1.05)
        is_stealth = 0 < month_return <= 15
        if not (is_long_uptrend and is_stealth and near_support): 
            return None

    chips = get_finmind_chips(ticker) if is_tw else {"狀態": "不適用"}
    if is_tw:
        if chips.get("外資近5日(張)", 0) < min_foreign or chips.get("投信近5日(張)", 0) < min_trust:
            return None

    try:
        info = stock.info
        trailing_eps = info.get("trailingEps", 0)
        forward_eps = info.get("forwardEps", 0)
        forward_pe = info.get("forwardPE", 0)
    except:
        trailing_eps, forward_eps, forward_pe = 0, 0, 0

    eps_growth = ((forward_eps - trailing_eps) / trailing_eps) * 100 if (trailing_eps and forward_eps and trailing_eps > 0) else 0

    if not forward_pe or forward_pe <= 0: valuation = "⚪ 缺乏資料"
    elif forward_pe < 15: valuation = "🟢 便宜 (PE<15)"
    elif 15 <= forward_pe <= 25: valuation = "🟡 合理 (PE 15-25)"
    else: valuation = "🔴 偏貴 (PE>25)"

    news_text = fetch_news_text(ticker, is_tw)
    future_topic = check_future_potential(news_text, eps_growth)
    
    is_long_uptrend = latest_price > ma60
    near_support = (ma20 * 0.98) <= latest_price <= (ma20 * 1.05)
    is_stealth = 0 < month_return <= 15
    too_high = latest_price > (ma20 * 1.10)

    decision = ""
    if is_long_uptrend and is_stealth and near_support: decision = "🌟 隱藏多頭 (墊高+近支撐)"
    elif is_long_uptrend and near_support: decision = "🎯 標準回調 (試錯買點)"
    elif too_high: decision = "👀 話題偏高 (等回檔)" if "🔥" in future_topic else "⚠️ 漲幅過大 (勿追高)"
    elif latest_price < ma20: decision = "👀 具潛力破線 (列觀察)" if "🔥" in future_topic else "🔴 跌破防守 (停損/觀望)"
    else: decision = "🟢 偏多震盪"

    affordable_shares = int(30000 // latest_price) if is_tw else round((30000 / 32) / latest_price, 2)

    display_ticker = ticker.replace(".TW", "")
    if is_tw:
        stock_name = TW_STOCK_NAMES.get(display_ticker, "")
        if stock_name:
            display_ticker = f"{display_ticker} {stock_name}"

    return {
        "overview": {
            "標的": display_ticker,
            "收盤價": float(latest_price), 
            "單日漲跌(%)": float(pct_change),
            "近一月漲跌(%)": float(month_return) if not pd.isna(month_return) else 0.0,
            "綜合決策": decision,
            "估值評估": valuation,
            "籌碼狀態": chips.get("狀態"),
            "防守停損": float(ma20 * 0.97),
            "停利目標": float(latest_price * 1.30),
            "建議買進股數": affordable_shares
        },
        "eps_details": {
            "標的": display_ticker,
            "過去4季 EPS": round(trailing_eps, 2) if trailing_eps else "N/A",
            "明年預估 EPS": round(forward_eps, 2) if forward_eps else "N/A",
            "EPS 預估年增率": f"{round(eps_growth, 2)}%" if eps_growth else "N/A",
            "遠期本益比": round(forward_pe, 2) if forward_pe else "N/A",
            "未來性評估": future_topic
        }
    }

# === 5. 智慧情境警報引擎 ===
def generate_smart_alert(ticker, user_settings):
    stock = yf.Ticker(ticker)
    try:
        df = stock.history(period="6mo")
        if len(df) < 60: return None
    except: return None
    
    df = calculate_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    price = latest["Close"]
    ma20 = latest["MA20"]
    low_10 = latest["Low_10"]
    vol_surge = latest["Volume"] > (latest["Vol_MA5"] * 1.3)
    
    status = user_settings.get("status", "observing") 
    cost = user_settings.get("cost", 0.0)
    note = user_settings.get("note", "")
    target_price = user_settings.get("target_price", 0.0)
    reminder_date_str = user_settings.get("reminder_date", "")
    
    alert = None
    time_str = df.index[-1].strftime("%Y-%m-%d (日線)")

    if status == "holding" and cost > 0:
        stop_loss = cost * 0.9  
        if price < stop_loss or price < ma20:
            alert = {
                "發生什麼事": f"股價 ({price:.2f}) 跌破設定的防守線或 20 日均線 ({ma20:.2f})。",
                "目前階段": "🔴 持股風險升高 (趨勢轉弱)",
                "為什麼提醒": "股價跌破重要趨勢支撐，原本的多頭格局受到破壞。",
                "建議下一步": "請檢查目前持股風險、原定停損條件及部位大小。這是風險提醒，不代表必須立即殺出，請先評估自身承受度。",
                "失效條件": "若三日內能帶量強勢站回 20 日均線之上，則危機解除。"
            }
        elif price > ma20 and vol_surge and latest["Close"] > prev["High"]:
            alert = {
                "發生什麼事": f"股價帶量突破前日高點，且維持在均線之上。",
                "目前階段": "🟢 趨勢轉強 (加碼評估)",
                "為什麼提醒": "出現明顯的右側轉強訊號，趨勢向上確立。",
                "建議下一步": "可評估是否符合你的加碼計畫；請同時確認距離停損位置的幅度與新增部位的風險。",
                "失效條件": "若接下來兩日無量下跌跌破今日低點，則轉強訊號失效。"
            }

    if status == "observing":
        near_low = price <= (low_10 * 1.03) 
        if near_low and latest["Close"] >= prev["Close"] and latest["Low"] >= prev["Low"]:
            alert = {
                "發生什麼事": f"股價 ({price:.2f}) 接近近期低點，且連續兩日未再創新低。",
                "目前階段": "🟡 初步止跌 (觀察中)",
                "為什麼提醒": "低點暫時守住，K 線出現止跌抵抗，但趨勢反轉尚未確認。",
                "建議下一步": "可觀察是否能帶量突破短期下降趨勢線。建議先觀察，不急著摸底買進。",
                "失效條件": "若收盤跌破近期低點，則止跌失敗，重啟跌勢。"
            }
        elif price > ma20 and vol_surge and latest["RSI"] > 50:
            alert = {
                "發生什麼事": f"股價帶量突破 20 日均線，且 RSI 站上 50 多空分界。",
                "目前階段": "🎯 反彈確認 (可評估進場)",
                "為什麼提醒": "價格已突破近期整理區間，且成交量配合放大，動能指標改善。",
                "建議下一步": "可評估小量進場試單。請先確認失效條件，並將停損設於突破起漲點下方。",
                "失效條件": "跌回 20 日均線之下，或爆歷史巨量卻收長黑 K。"
            }

    custom_triggers = []
    if reminder_date_str:
        target_date = datetime.datetime.strptime(reminder_date_str, "%Y-%m-%d").date()
        if datetime.date.today() >= target_date:
            custom_triggers.append(f"📅 **日期觸發**：您設定的關鍵觀察日 ({reminder_date_str}) 已到達！")
            
    if target_price > 0:
        if status == "observing" and price <= target_price:
            custom_triggers.append(f"💰 **價格觸發**：已回檔至您設定的預期進場價 ({target_price} 元)！")
        elif status == "holding" and price >= target_price:
            custom_triggers.append(f"💰 **價格觸發**：已達到您設定的停利目標價 ({target_price} 元)！")

    if custom_triggers and alert is None:
        alert = {
            "發生什麼事": "達到您自訂的特殊追蹤條件，目前技術面呈現盤整或無重大突發訊號。",
            "目前階段": "🔔 自訂條件觸發",
            "為什麼提醒": "依據您的個人設定強制跳出通知。",
            "建議下一步": "請檢閱您的個人筆記，依預定計畫評估操作。",
            "失效條件": "無"
        }

    if alert is not None:
        alert["時間與週期"] = time_str
        alert["個人筆記"] = note
        alert["自訂觸發項目"] = custom_triggers

    return alert

# === 6. 色彩渲染器 ===
def color_tw(val):
    if isinstance(val, (int, float)):
        color = '#ff4b4b' if val > 0 else '#00cc96' if val < 0 else 'gray' 
        return f'color: {color}; font-weight: bold;'
    return ''

def color_us(val):
    if isinstance(val, (int, float)):
        color = '#00cc96' if val > 0 else '#ff4b4b' if val < 0 else 'gray' 
        return f'color: {color}; font-weight: bold;'
    return ''

# === 7. 介面呈現 (四大整合分頁) ===
tab_tw, tab_us, tab_alerts, tab_tearsheet = st.tabs([
    "🇹🇼 台股波段雷達", 
    "🇺🇸 美股波段雷達", 
    "🔔 智慧趨勢提醒與健檢", 
    "📄 一鍵個股簡報"
])

# ----------------- 分頁 1：台股波段雷達 -----------------
with tab_tw:
    st.header("🇹🇼 台股波段雷達")
    
    st.subheader("📌 自選觀察清單 (紅漲綠跌)")
    c_in, c_btn = st.columns([3, 1])
    with c_in:
        new_tw = st.text_input("新增台股", placeholder="輸入代號 (例如: 2317.TW)", label_visibility="collapsed", key="add_tw_input")
    with c_btn:
        if st.button("➕ 新增", key="btn_add_tw", use_container_width=True):
            if new_tw:
                tk = new_tw.upper()
                if tk not in st.session_state['watchlists']['TW']:
                    st.session_state['watchlists']['TW'].append(tk)
                    save_json(DB_WATCHLISTS, st.session_state['watchlists'])
                    st.rerun()

    tw_data = [analyze_stock_master(t, is_tw=True) for t in st.session_state['watchlists']['TW']]
    tw_overview = [d["overview"] for d in tw_data if d]
    
    if tw_overview:
        df_tw_view = pd.DataFrame(tw_overview)
        df_tw_view.insert(0, "🗑️ 刪除", False)
        
        edited_tw = st.data_editor(
            df_tw_view.style.map(color_tw, subset=['單日漲跌(%)', '近一月漲跌(%)']),
            use_container_width=True,
            hide_index=True,
            key=f"tw_editor_{st.session_state.tw_edit_key}",
            column_config={
                "🗑️ 刪除": st.column_config.CheckboxColumn("刪除", default=False),
                "收盤價": st.column_config.NumberColumn(format="%.2f"),
                "單日漲跌(%)": st.column_config.NumberColumn(format="%.2f"),
                "近一月漲跌(%)": st.column_config.NumberColumn(format="%.2f"),
                "防守停損": st.column_config.NumberColumn(format="%.2f"),
                "停利目標": st.column_config.NumberColumn(format="%.2f"),
            },
            disabled=[col for col in df_tw_view.columns if col != "🗑️ 刪除"]
        )
        
        deleted_tw = edited_tw[edited_tw["🗑️ 刪除"] == True]
        if not deleted_tw.empty:
            del_list = deleted_tw["標的"].tolist()
            st.warning(f"⚠️ 確定要從觀察清單中刪除 **{', '.join(del_list)}** 嗎？")
            col_y, col_n = st.columns(2)
            with col_y:
                if st.button("✅ 確認刪除", use_container_width=True, key="tw_del_yes"):
                    for t in del_list:
                        tk_full = f"{t.split(' ')[0]}.TW"
                        if tk_full in st.session_state['watchlists']['TW']:
                            st.session_state['watchlists']['TW'].remove(tk_full)
                    save_json(DB_WATCHLISTS, st.session_state['watchlists'])
                    st.session_state.tw_edit_key += 1 
                    st.rerun()
            with col_n:
                if st.button("❌ 取消", use_container_width=True, key="tw_del_no"):
                    st.session_state.tw_edit_key += 1 
                    st.rerun()
    else:
        st.info("台股觀察清單目前為空，請從上方輸入代號新增。")

    st.markdown("---")
    st.subheader("🔍 市場動態掃描 (非主流・隱藏多頭・籌碼共振)")
    
    # 策略說明展開區
    with st.expander("💡 了解本系統的台股選股邏輯與策略"):
        st.markdown("""
        **本系統核心策略：20MA 回調買入法 + 多因子濾網**
        這套雷達旨在幫您避開「追高被套」的風險，專門尋找**大趨勢保護下，剛好拉回支撐**的潛力股。

        🔍 **動態掃描的篩選條件包含：**
        1. **技術面 (隱藏多頭)**：股票必須在季線 (60MA) 之上，近一個月只溫和上漲 (0~15%)，且今天剛好回踩或緊貼月線 (20MA)，風險極低。
        2. **籌碼面 (大人照顧)**：自動串接 FinMind，可透過下方滑桿自訂過濾出近期外資或投信正在偷偷佈局的股票。
        3. **基本面 (估值評估)**：自動計算遠期本益比 (Forward PE)，幫您判斷現在買進是便宜、合理還是偏貴。
        4. **消息面 (未來潛力)**：掃描最新新聞，偵測是否具備「成長、創新高、受惠」等題材，即使技術面破線也會給予關注提醒。
        """)

    col1, col2 = st.columns(2)
    with col1: max_price_tw = st.number_input("最高股價 (台幣)", value=150, step=10, key="max_tw")
    with col2: min_foreign = st.slider("外資近5日買超 > (張)", 0, 5000, 0, 500)
    
    col3, col4 = st.columns(2)
    with col3: min_trust = st.slider("投信近5日買超 > (張)", 0, 2000, 0, 100)
    with col4:
        st.write("")
        stealth_only = st.checkbox("只抓隱藏多頭", value=True)
        
    if st.button("🚀 執行台股動態掃描", type="primary", use_container_width=True):
        with st.spinner("掃描市場與計算中..."):
            TW_BROAD_POOL = ["1504.TW", "1519.TW", "1605.TW", "2313.TW", "2368.TW", "2520.TW", "2609.TW", "2618.TW", "3017.TW", "3231.TW", "3324.TW", "8996.TW", "9958.TW", "2308.TW", "2376.TW"]
            scan_res, eps_res = [], []
            for t in TW_BROAD_POOL:
                res = analyze_stock_master(t, is_tw=True, max_price=max_price_tw, min_foreign=min_foreign, min_trust=min_trust, filter_stealth=stealth_only)
                if res:
                    scan_res.append(res["overview"])
                    eps_res.append(res["eps_details"])
            
            if scan_res:
                st.success(f"✅ 發現優質標的！")
                st.dataframe(
                    pd.DataFrame(scan_res).style.map(color_tw, subset=['單日漲跌(%)', '近一月漲跌(%)']),
                    use_container_width=True, hide_index=True
                )
                with st.expander("📊 點擊展開 EPS 獲利分析表"):
                    st.table(pd.DataFrame(eps_res))
            else:
                st.info("💡 今日掃描池中，沒有符合技術面買點的股票。")

# ----------------- 分頁 2：美股波段雷達 -----------------
with tab_us:
    st.header("🇺🇸 美股波段雷達")
    
    st.subheader("📌 自選觀察清單 (綠漲紅跌)")
    c_in_us, c_btn_us = st.columns([3, 1])
    with c_in_us:
        new_us = st.text_input("新增美股", placeholder="輸入代號 (例如: TSLA)", label_visibility="collapsed", key="add_us_input")
    with c_btn_us:
        if st.button("➕ 新增", key="btn_add_us", use_container_width=True):
            if new_us:
                tk = new_us.upper()
                if tk not in st.session_state['watchlists']['US']:
                    st.session_state['watchlists']['US'].append(tk)
                    save_json(DB_WATCHLISTS, st.session_state['watchlists'])
                    st.rerun()

    us_data = [analyze_stock_master(t, is_tw=False) for t in st.session_state['watchlists']['US']]
    us_overview = [d["overview"] for d in us_data if d]
    
    if us_overview:
        df_us_view = pd.DataFrame(us_overview)
        df_us_view.insert(0, "🗑️ 刪除", False)
        
        edited_us = st.data_editor(
            df_us_view.style.map(color_us, subset=['單日漲跌(%)', '近一月漲跌(%)']),
            use_container_width=True,
            hide_index=True,
            key=f"us_editor_{st.session_state.us_edit_key}",
            column_config={
                "🗑️ 刪除": st.column_config.CheckboxColumn("刪除", default=False),
                "收盤價": st.column_config.NumberColumn(format="%.2f"),
                "單日漲跌(%)": st.column_config.NumberColumn(format="%.2f"),
                "近一月漲跌(%)": st.column_config.NumberColumn(format="%.2f"),
                "防守停損": st.column_config.NumberColumn(format="%.2f"),
                "停利目標": st.column_config.NumberColumn(format="%.2f"),
            },
            disabled=[col for col in df_us_view.columns if col != "🗑️ 刪除"]
        )
        
        deleted_us = edited_us[edited_us["🗑️ 刪除"] == True]
        if not deleted_us.empty:
            del_list_us = deleted_us["標的"].tolist()
            st.warning(f"⚠️ 確定要從觀察清單中刪除 **{', '.join(del_list_us)}** 嗎？")
            col_y_us, col_n_us = st.columns(2)
            with col_y_us:
                if st.button("✅ 確認刪除", use_container_width=True, key="us_del_yes"):
                    for t in del_list_us:
                        if t in st.session_state['watchlists']['US']:
                            st.session_state['watchlists']['US'].remove(t)
                    save_json(DB_WATCHLISTS, st.session_state['watchlists'])
                    st.session_state.us_edit_key += 1
                    st.rerun()
            with col_n_us:
                if st.button("❌ 取消", use_container_width=True, key="us_del_no"):
                    st.session_state.us_edit_key += 1
                    st.rerun()
    else:
        st.info("美股觀察清單目前為空，請從上方輸入代號新增。")

    st.markdown("---")
    st.subheader("🔍 市場動態掃描 (中小型・非熱門巨頭・隱藏多頭)")
    
    # 策略說明展開區
    with st.expander("💡 了解本系統的美股選股邏輯與策略"):
        st.markdown("""
        **本系統核心策略：20MA 回調買入法 + 基本面題材濾網**
        這套雷達旨在幫您避開「追高被套」的風險，專門尋找**大趨勢保護下，剛好拉回支撐**的潛力美股。

        🔍 **動態掃描的篩選條件包含：**
        1. **技術面 (隱藏多頭)**：嚴格要求大趨勢偏多 (站上季線)，且近一個月漲幅溫和不透支 (0~15%)，目前價格剛好回調至 20 日線 (月線) 附近的安全邊際。
        2. **基本面 (EPS與估值)**：自動為您換算遠期本益比，評估目前股價是便宜還是偏貴，並於詳細表格列出預估 EPS 成長率。
        3. **消息面 (未來潛力)**：背景掃描最新外電新聞，偵測是否具備 AI、突破、升評 (upgrade) 等催化劑題材，發掘未來的潛力飆股。
        """)

    col_u1, col_u2 = st.columns([1, 1])
    with col_u1: max_price_us = st.number_input("最高股價 (美元)", value=150, step=10, key="max_us")
    with col_u2: 
        st.write("")
        scan_us_btn = st.button("🚀 執行美股動態掃描", type="primary", use_container_width=True)

    if scan_us_btn:
        with st.spinner("掃描板塊與計算中..."):
            US_BROAD_POOL = ["FOUR", "VRT", "ONON", "CELH", "ELF", "UBER", "HOOD", "RDDT", "WING", "DKNG", "PLTR", "DDOG", "CRWD", "ARM"]
            scan_res_us, eps_res_us = [], []
            for t in US_BROAD_POOL:
                res = analyze_stock_master(t, is_tw=False, max_price=max_price_us, filter_stealth=True)
                if res:
                    scan_res_us.append(res["overview"])
                    eps_res_us.append(res["eps_details"])
            
            if scan_res_us:
                st.success("✅ 發現潛力美股！")
                st.dataframe(
                    pd.DataFrame(scan_res_us).style.map(color_us, subset=['單日漲跌(%)', '近一月漲跌(%)']), 
                    use_container_width=True, hide_index=True
                )
                with st.expander("📊 點擊展開 EPS 獲利分析表"):
                    st.table(pd.DataFrame(eps_res_us))
            else:
                st.info("💡 今日市場無符合條件的標的。")

# ----------------- 分頁 3：智慧趨勢提醒與健檢 -----------------
with tab_alerts:
    st.header("🧠 情境式智慧趨勢監控與持股健檢")
    st.markdown("設定專屬監控標的，系統會在技術面達標、或到達特定日期/價格時跳出具體行動建議。")
    
    st.subheader("⚙️ 新增 / 編輯監控規則")
    with st.form("alert_config_form"):
        ticker_input = st.text_input("股票代號 (台股請加 .TW)", placeholder="例如: 2603.TW")
        status_input = st.radio("交易目的", ["準備進場 (尚未持有)", "停利/風險管理 (已持有)"])
        cost_input = st.number_input("持有平均成本 (空手請填 0)", min_value=0.0, step=1.0)
        note_input = st.text_area("個人紀律筆記", placeholder="例如：等下週四法說會開完再決定。")
        
        enable_date = st.checkbox("設定日期提醒")
        date_input = st.date_input("選擇提醒日", value=datetime.date.today()) if enable_date else None
        target_price_input = st.number_input("到達特定價格提醒 (0代表不設定)", min_value=0.0, step=1.0)
        
        if st.form_submit_button("💾 儲存監控規則與筆記", use_container_width=True):
            if ticker_input:
                ticker = ticker_input.upper()
                st.session_state['user_config'][ticker] = {
                    "status": "holding" if "已持有" in status_input else "observing",
                    "cost": cost_input, "note": note_input, "target_price": target_price_input,
                    "reminder_date": date_input.strftime("%Y-%m-%d") if enable_date else ""
                }
                save_json(DB_ALERTS, st.session_state['user_config'])
                st.success(f"已更新 {ticker} 的監控規則！")
                
    st.markdown("---")
    st.subheader("📩 趨勢通知與多維健檢中心")
    config = st.session_state['user_config']
    if not config: 
        st.info("目前沒有監控中的標的。請從上方新增設定。")
    else:
        if st.button("🔄 立即執行全盤掃描與健檢", type="primary", use_container_width=True):
            with st.spinner("正在進行多面向情境診斷..."):
                alerts_found = 0
                for ticker, settings in config.items():
                    alert_data = generate_smart_alert(ticker, settings)
                    
                    if alert_data:
                        alerts_found += 1
                        border_color = "#ff4b4b" if "風險" in alert_data["目前階段"] else "#00cc96" if "確認" in alert_data["目前階段"] else "#ffc107"
                        
                        custom_html = ""
                        if alert_data.get("自訂觸發項目"):
                            for msg in alert_data["自訂觸發項目"]:
                                custom_html += f"<div style='color: #ffc107; font-weight: bold; margin-bottom: 5px;'>{msg}</div>"
                                
                        note_text = alert_data.get('個人筆記', '')
                        note_html = f"<i style='color: #bbb;'>{note_text}</i>" if note_text else "<i style='color: #666;'>無</i>"

                        display_ticker_alert = ticker.replace(".TW", "")
                        if ".TW" in ticker and display_ticker_alert in TW_STOCK_NAMES:
                            display_ticker_alert = f"{display_ticker_alert} {TW_STOCK_NAMES[display_ticker_alert]}"

                        st.markdown(f"""
                        <div style="border-left: 5px solid {border_color}; padding: 15px; background-color: #1e1e1e; border-radius: 8px; margin-bottom: 20px;">
                            <h4 style="margin-top: 0; color: {border_color};">{display_ticker_alert} - {alert_data['目前階段']}</h4>
                            {custom_html}
                            <ul style="margin-top: 10px; margin-bottom: 10px; padding-left: 20px;">
                                <li><b>發生什麼事：</b>{alert_data['發生什麼事']}</li>
                                <li><b>為什麼提醒：</b>{alert_data['為什麼提醒']}</li>
                                <li><b>🎯 建議下一步：</b><span style="color:#00cc96;">{alert_data['建議下一步']}</span></li>
                                <li><b>⚠️ 失效條件：</b><span style="color:#ff4b4b;">{alert_data['失效條件']}</span></li>
                            </ul>
                            <div style="background-color: #2b2b2b; padding: 10px; border-radius: 5px; margin-top: 10px; border: 1px dashed #555;">
                                <span style="color: #00cc96; font-weight: bold;">📝 當時的決策筆記：</span><br>
                                {note_html}
                            </div>
                            <div style="text-align: right; margin-top: 5px;"><small style="color: gray;">更新基準：{alert_data.get('時間與週期', '')}</small></div>
                        </div>
                        """, unsafe_allow_html=True)
                        
                if alerts_found == 0: 
                    st.success("✅ 掃描完畢。您監控的股票走勢符合預期，且未達自訂觸發條件。")

# ----------------- 分頁 4：一鍵個股簡報 -----------------
with tab_tearsheet:
    st.header("📄 機構級一鍵個股快照")
    st.markdown("輸入代號，自動產出結構化簡報。")
    
    c_ts_in, c_ts_btn = st.columns([3, 1])
    with c_ts_in:
        ts_ticker = st.text_input("輸入股票代號", placeholder="例如: 2330.TW", label_visibility="collapsed")
    with c_ts_btn:
        ts_submit = st.button("📊 生成", use_container_width=True)

    if ts_submit and ts_ticker:
        with st.spinner("彙整全球資料庫中..."):
            stock = yf.Ticker(ts_ticker.upper())
            info = stock.info
            
            base_ticker = ts_ticker.upper().replace(".TW", "")
            if ".TW" in ts_ticker.upper() and base_ticker in TW_STOCK_NAMES:
                name = TW_STOCK_NAMES[base_ticker]
            else:
                name = info.get("longName", info.get("shortName", ts_ticker))
                
            sector = info.get("sector", "無資料")
            industry = info.get("industry", "無資料")
            summary = info.get("longBusinessSummary", "暫無業務簡介資料。")
            pe = info.get("trailingPE", "N/A")
            fwd_pe = info.get("forwardPE", "N/A")
            eps = info.get("trailingEps", "N/A")
            dividend = info.get("dividendYield", 0) * 100 if info.get("dividendYield") else "N/A"
            high_52 = info.get("fiftyTwoWeekHigh", "N/A")
            low_52 = info.get("fiftyTwoWeekLow", "N/A")
            current_price = info.get("currentPrice", info.get("previousClose", "N/A"))
            
            st.markdown(f"## 🏢 {name} ({ts_ticker.upper()})")
            st.markdown(f"**板塊 / 產業：** {sector} / {industry}")
            
            c1, c2 = st.columns(2)
            c1.metric("目前報價", f"{current_price}")
            c2.metric("近四季 EPS", f"{eps}")
            c3, c4 = st.columns(2)
            c3.metric("本益比 (PE)", f"{round(pe, 2) if isinstance(pe, float) else pe}")
            c4.metric("殖利率", f"{round(dividend, 2)}%" if isinstance(dividend, float) else "N/A")
            
            st.markdown("### 📋 業務概覽")
            st.info(summary)
            
            st.markdown("### 📈 估值與價格位階")
            st.write(f"- **52週高點 / 低點**：{high_52} / {low_52}")
            st.write(f"- **遠期本益比 (Forward PE)**：{round(fwd_pe, 2) if isinstance(fwd_pe, float) else fwd_pe}")
            
            st.markdown("### 📰 近期市場關鍵字偵測")
            news_html = fetch_news_text(ts_ticker, ".TW" in ts_ticker)
            if any(k in news_html for k in ["創新高", "大增", "看好", "受惠"]): 
                st.success("雷達偵測到近期包含「創新高、大增、看好」等正面關鍵字。")
            elif any(k in news_html for k in ["衰退", "下修", "轉虧"]): 
                st.error("雷達偵測到近期包含「衰退、下修」等保守關鍵字。")
            else: 
                st.write("近期新聞情緒平穩。")
