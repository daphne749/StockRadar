import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import json
import os
import requests
import urllib.parse
import socket
import urllib3.util.connection as urllib3_cn

# === 1. 網頁全域設定與手機端按鈕優化 ===
st.set_page_config(page_title="專業波段選股系統", page_icon="📈", layout="wide")

st.markdown("""
<style>
.stButton>button {border-radius: 8px; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

st.title("📈 雙引擎波段選股雷達")
st.markdown("💰 **資金風控**：每單 30,000 TWD | 🎯 **核心策略**：20MA 回調買入 + 30% 停利 + 智慧情境監控")

# === Telegram 推播核心模組 (強制 IPv4 穩定通道 + 自動重試) ===
def get_tg_credentials():
    token = st.session_state.get("custom_tg_token", "")
    chat_id = st.session_state.get("custom_tg_chat_id", "")
    if not token:
        try:
            token = st.secrets.get("TG_BOT_TOKEN", "")
        except Exception:
            token = ""
    if not chat_id:
        try:
            chat_id = str(st.secrets.get("TG_CHAT_ID", ""))
        except Exception:
            chat_id = ""
    return token.strip(), chat_id.strip()

def send_telegram_msg(text):
    token, chat_id = get_tg_credentials()
    if not token or not chat_id:
        return False, "尚未設定 TG_BOT_TOKEN 或 TG_CHAT_ID"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    orig_family = urllib3_cn.allowed_gai_family
    urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
    try:
        for attempt in range(2):
            try:
                res = requests.post(url, json=payload, timeout=25)
                data = res.json()
                if res.status_code == 200 and data.get("ok"):
                    return True, "推播成功"
                return False, f"Telegram 拒絕發送：{data.get('description', '未知錯誤')}"
            except requests.exceptions.Timeout:
                if attempt == 0:
                    continue
                return False, "連線逾時（已自動重試 2 次），請稍後再按一次測試"
            except Exception as e:
                return False, f"連線異常：{e}"
    finally:
        urllib3_cn.allowed_gai_family = orig_family

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
        "3324": "雙鴻", "1504": "東元", "1605": "華新", "2609": "陽明", "2618": "長榮航",
        "2368": "金像電", "2449": "京元電子", "3661": "世芯-KY", "3443": "創意"
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

# === 3.5 AI 基本面深度篩選與研究助理模組 ===
@st.cache_data(ttl=43200)
def get_tw_monthly_revenue(stock_id):
    start_date = (datetime.date.today() - datetime.timedelta(days=450)).strftime("%Y-%m-%d")
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id={stock_id}&start_date={start_date}"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get("msg") == "success" and len(res.get("data", [])) > 0:
            df = pd.DataFrame(res["data"])
            latest = df.iloc[-1]
            rev = latest.get("revenue", 0)
            yoy = latest.get("revenue_year_growth", None)
            year_month = f"{latest.get('revenue_year')}年{latest.get('revenue_month')}月"
            
            if yoy is None and len(df) >= 13:
                prev_year_rev = df.iloc[-13].get("revenue", 0)
                if prev_year_rev > 0:
                    yoy = ((rev - prev_year_rev) / prev_year_rev) * 100
            return {
                "最新期別": year_month,
                "月營收(億)": round(rev / 1e8, 2),
                "營收年增率(%)": round(yoy, 2) if yoy is not None else None
            }
    except:
        pass
    return None

@st.cache_data(ttl=43200)
def screen_fundamental_stocks(is_tw=True):
    pool = ["2330.TW", "2454.TW", "2308.TW", "2382.TW", "3017.TW", "1519.TW", "2345.TW", "2368.TW", "3324.TW", "2449.TW"] if is_tw else ["NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "AMD", "AVGO", "VRT", "PLTR", "CRWD"]
    results = []
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    for ticker in pool:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            eps_ttm = info.get("trailingEps", None)
            gross_margin = info.get("grossMargins", None)
            op_margin = info.get("operatingMargins", None)
            debt_to_equity = info.get("debtToEquity", None)
            rev_growth_yf = info.get("revenueGrowth", None)
            
            gm_pct = round(gross_margin * 100, 2) if gross_margin is not None else None
            op_pct = round(op_margin * 100, 2) if op_margin is not None else None
            dte_val = round(debt_to_equity, 2) if debt_to_equity is not None else None
            
            stock_id = ticker.replace(".TW", "")
            if is_tw:
                name = TW_STOCK_NAMES.get(stock_id, info.get("shortName", stock_id))
                rev_data = get_tw_monthly_revenue(stock_id)
                if rev_data and rev_data["營收年增率(%)"] is not None:
                    rev_str = f"{rev_data['月營收(億)']} 億台幣 ({rev_data['最新期別']})"
                    yoy_val = rev_data["營收年增率(%)"]
                    source_str = "FinMind (月營收) / Yahoo Finance (財報指標)"
                else:
                    rev_str = "依最新季報"
                    yoy_val = round(rev_growth_yf * 100, 2) if rev_growth_yf is not None else 0
                    source_str = "Yahoo Finance (季報與TTM數據)"
            else:
                name = info.get("shortName", ticker)
                rev_str = "依最新季報 (美股無月營收制度)"
                yoy_val = round(rev_growth_yf * 100, 2) if rev_growth_yf is not None else 0
                source_str = "Yahoo Finance (SEC 季報/年報 TTM 數據)"
            
            if eps_ttm and eps_ttm > 0 and yoy_val and yoy_val > 5 and op_pct and op_pct > 10:
                news_text = fetch_news_text(ticker, is_tw)
                
                reasons = []
                if yoy_val > 20: reasons.append(f"營收年增率高達 {yoy_val}%，展現強勁的市場需求與出貨動能")
                else: reasons.append(f"營收年增率維持 {yoy_val}% 穩健成長")
                if gm_pct and gm_pct > 40: reasons.append(f"毛利率達 {gm_pct}%，顯示產品具備高度定價權或技術護城河")
                if op_pct and op_pct > 20: reasons.append(f"營業利益率達 {op_pct}%，本業獲利能力與費用控管極佳")
                if "AI" in news_text or "伺服器" in news_text or "晶片" in news_text:
                    reasons.append("近期市場新聞指出公司受惠於 AI 算力、雲端基建或先進製程規格升級趨勢")
                
                risks = []
                if dte_val and dte_val > 100:
                    risks.append(f"負債權益比 (Debt/Equity) 達 {dte_val}%，財務槓桿偏高，需留意高利率環境下的利息負擔")
                elif dte_val is None:
                    risks.append("公開資料庫暫缺最新負債比率細節，需防範隱藏性財務槓桿風險")
                else:
                    risks.append(f"目前負債權益比為 {dte_val}%，財務結構尚屬穩健，惟需留意終端客戶拉貨是否出現季節性放緩")
                
                fwd_pe = info.get("forwardPE", 0)
                if fwd_pe and fwd_pe > 25:
                    risks.append(f"遠期本益比達 {round(fwd_pe, 1)} 倍，市場已反映部分樂觀預期，若未來營收增速放緩恐面臨估值修正")
                if is_tw:
                    risks.append("外銷導向產業需持續留意新台幣匯率波動對毛利率的潛在侵蝕")

                checks = [
                    "下一次法說會或財報會議中，管理層對下一季毛利率與資本支出的最新指引 (Guidance)。",
                    "營收成長是否來自實質終端需求擴大，而非客戶端短期提前拉貨（需交叉比對存貨週轉天數變化）。",
                    "近期是否有可轉換公司債 (CB) 轉換、大股東申報轉讓，或高額資本支出導致自由現金流轉負的狀況。"
                ]
                
                results.append({
                    "ticker": stock_id if is_tw else ticker,
                    "full_ticker": ticker,
                    "name": name,
                    "rev_str": rev_str,
                    "yoy": f"{yoy_val}%",
                    "eps_ttm": f"{eps_ttm:.2f}",
                    "gm": f"{gm_pct}%" if gm_pct is not None else "N/A",
                    "opm": f"{op_pct}%" if op_pct is not None else "N/A",
                    "debt": f"負債權益比 {dte_val}%" if dte_val is not None else "需查閱財報附註",
                    "reasons": "；".join(reasons) + "。",
                    "risks": "；".join(risks) + "。",
                    "checks": checks,
                    "date": today_str,
                    "source": source_str
                })
        except:
            continue
    return results

def call_gemini_research_assistant(api_key, stock_data_list, market_name):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    prompt = f"""
請你扮演一位專業的台美股研究助理，根據最近一期月營收、年增率、近四季 EPS、毛利率、營業利益率及負債狀況，篩選出基本面值得進一步研究的{market_name}。請列出股票代號、公司名稱、最新可查證的數據、成長原因、潛在風險，以及還要確認的資訊。請註明資料日期與來源，不要只因為股價上漲就判定它有潛力。

以下是系統今日即時從公開資料庫抓取並初步篩選出的真實基本面數據 JSON：
{json.dumps(stock_data_list, ensure_ascii=False, indent=2)}

請嚴格根據上述真實數據（切勿自行編造數字），用台灣繁體中文撰寫深度的研究助理分析報告。
"""
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
        if res.status_code == 200:
            return res.json()["candidates"][0]["content"]["parts"][0]["text"]
        return f"⚠️ AI 連線失敗 (狀態碼 {res.status_code})，請確認 API Key 是否正確。"
    except Exception as e:
        return f"⚠️ 呼叫 AI 時發生錯誤：{e}"

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

# === 7. 介面呈現 (五大整合分頁) ===
tab_ai_rec, tab_tw, tab_us, tab_alerts, tab_tearsheet = st.tabs([
    "🤖 AI 潛力股推薦",
    "🇹🇼 台股波段雷達", 
    "🇺🇸 美股波段雷達", 
    "🔔 智慧趨勢提醒與健檢", 
    "📄 一鍵個股簡報"
])

# ----------------- 分頁 0：AI 基本面潛力股推薦 -----------------
with tab_ai_rec:
    st.header("🤖 專業台美股基本面研究助理")
    st.markdown("""
    <div style="background-color: #262730; padding: 15px; border-radius: 8px; border: 1px solid #4f4f4f; margin-bottom: 20px;">
        <span style="font-size: 1.05em; font-weight: bold; color: #00cc96;">📋 研究助理篩選準則（每次開啟自動更新）：</span><br>
        <span style="color: #d1d1d1;">
        本模組嚴格依據<b>最近一期月營收、年增率、近四季 EPS、毛利率、營業利益率及負債狀況</b>進行客觀量化篩選，<b>絕不因為股價短期上漲就判定具備潛力</b>。<br>
        系統已自動為您過濾出「營收年增 > 5%」、「近四季 EPS > 0」且「營業利益率 > 10%」之基本面績優標的：
        </span>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("🔑 進階設定：連結 Gemini API 啟動深度 AI 推理（選填）"):
        gemini_key = st.text_input("輸入 Gemini API Key（留空則使用系統內建量化研究報告）", type="password")

    with st.spinner("研究助理正在調閱台美股最新財報、月營收與負債數據..."):
        tw_picks = screen_fundamental_stocks(is_tw=True)
        us_picks = screen_fundamental_stocks(is_tw=False)

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        if st.button("🔄 強制重新抓取最新財報", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with col_r2:
        if st.button("📲 將今日潛力股推播至 Telegram", use_container_width=True):
            msg_lines = [f"<b>🤖 AI 基本面潛力股日報 ({datetime.date.today()})</b>\n"]
            if tw_picks:
                msg_lines.append("<b>🇹🇼 台股篩選名單：</b>")
                for item in tw_picks:
                    msg_lines.append(f"• <b>{item['ticker']} {item['name']}</b>：年增 {item['yoy']}｜EPS {item['eps_ttm']}｜毛利 {item['gm']}｜營益 {item['opm']}")
            if us_picks:
                msg_lines.append("\n<b>🇺🇸 美股篩選名單：</b>")
                for item in us_picks:
                    msg_lines.append(f"• <b>{item['ticker']} ({item['name']})</b>：年增 {item['yoy']}｜EPS ${item['eps_ttm']}｜毛利 {item['gm']}｜營益 {item['opm']}")
            if not tw_picks and not us_picks:
                msg_lines.append("今日暫無符合嚴格基本面條件之標的。")
            ok, status_msg = send_telegram_msg("\n".join(msg_lines))
            if ok: st.success("✅ 已成功推播至您的 Telegram！")
            else: st.error(f"❌ {status_msg}")

    st.subheader("🇹🇼 台股基本面潛力研究名單")
    if gemini_key and tw_picks:
        with st.spinner("🤖 AI 研究助理正在撰寫台股深度報告..."):
            st.markdown(call_gemini_research_assistant(gemini_key, tw_picks, "台股"))
    elif tw_picks:
        for item in tw_picks:
            checks_html = "".join([f"<li>{c}</li>" for c in item["checks"]])
            st.markdown(f"""
            <div style="border-left: 5px solid #ff4b4b; padding: 15px; background-color: #1e1e1e; border-radius: 8px; margin-bottom: 16px;">
                <h4 style="margin-top: 0; color: #ff4b4b;">📌 {item['ticker']} {item['name']}</h4>
                <p style="margin-bottom: 8px;"><b>📊 最新可查證數據：</b><br>
                • <b>最近期營收：</b>{item['rev_str']} (年增率 <b>{item['yoy']}</b>)<br>
                • <b>獲利能力：</b>近四季 EPS <b>{item['eps_ttm']} 元</b> ｜ 毛利率 <b>{item['gm']}</b> ｜ 營業利益率 <b>{item['opm']}</b><br>
                • <b>負債狀況：</b>{item['debt']}</p>
                <p style="margin-bottom: 8px;"><b>🚀 成長原因：</b><span style="color:#00cc96;">{item['reasons']}</span></p>
                <p style="margin-bottom: 8px;"><b>⚠️ 潛在風險：</b><span style="color:#ffc107;">{item['risks']}</span></p>
                <div style="background-color: #2b2b2b; padding: 10px; border-radius: 5px; margin-top: 8px;">
                    <b style="color: #63b3ed;">🔍 還要確認的資訊：</b>
                    <ul style="margin-top: 5px; margin-bottom: 0; padding-left: 20px; color: #d1d1d1;">
                        {checks_html}
                    </ul>
                </div>
                <div style="text-align: right; margin-top: 6px;"><small style="color: gray;">📅 資料檢索日期：{item['date']} ｜ 📚 資料來源：{item['source']}</small></div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("目前候選池中暫無同時滿足所有嚴格基本面條件的台股。")

    st.markdown("---")
    st.subheader("🇺🇸 美股基本面潛力研究名單")
    if gemini_key and us_picks:
        with st.spinner("🤖 AI 研究助理正在撰寫美股深度報告..."):
            st.markdown(call_gemini_research_assistant(gemini_key, us_picks, "美股"))
    elif us_picks:
        for item in us_picks:
            checks_html = "".join([f"<li>{c}</li>" for c in item["checks"]])
            st.markdown(f"""
            <div style="border-left: 5px solid #00cc96; padding: 15px; background-color: #1e1e1e; border-radius: 8px; margin-bottom: 16px;">
                <h4 style="margin-top: 0; color: #00cc96;">📌 {item['ticker']} ({item['name']})</h4>
                <p style="margin-bottom: 8px;"><b>📊 最新可查證數據：</b><br>
                • <b>最近期營收表現：</b>{item['rev_str']} (年增率 <b>{item['yoy']}</b>)<br>
                • <b>獲利能力：</b>近四季 EPS <b>${item['eps_ttm']}</b> ｜ 毛利率 <b>{item['gm']}</b> ｜ 營業利益率 <b>{item['opm']}</b><br>
                • <b>負債狀況：</b>{item['debt']}</p>
                <p style="margin-bottom: 8px;"><b>🚀 成長原因：</b><span style="color:#00cc96;">{item['reasons']}</span></p>
                <p style="margin-bottom: 8px;"><b>⚠️ 潛在風險：</b><span style="color:#ffc107;">{item['risks']}</span></p>
                <div style="background-color: #2b2b2b; padding: 10px; border-radius: 5px; margin-top: 8px;">
                    <b style="color: #63b3ed;">🔍 還要確認的資訊：</b>
                    <ul style="margin-top: 5px; margin-bottom: 0; padding-left: 20px; color: #d1d1d1;">
                        {checks_html}
                    </ul>
                </div>
                <div style="text-align: right; margin-top: 6px;"><small style="color: gray;">📅 資料檢索日期：{item['date']} ｜ 📚 資料來源：{item['source']}</small></div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("目前候選池中暫無同時滿足所有嚴格基本面條件的美股。")

# ----------------- 分頁 1：台股波段雷達 -----------------
with tab_tw:
    st.header("🇹🇼 台股波段雷達")
    
    st.markdown("""
    <div style="background-color: #262730; padding: 15px; border-radius: 8px; border: 1px solid #4f4f4f; margin-bottom: 20px;">
        <span style="font-size: 1.1em; font-weight: bold; color: #ff4b4b;">核心策略：20MA 回調買入法 + 多因子濾網</span><br>
        <span style="color: #d1d1d1;">這套雷達旨在幫您避開「追高被套」的風險，專門尋找<b>大趨勢保護下，剛好拉回支撐</b>的潛力股。</span><br><br>
        <span style="font-weight: bold; color: #ffffff;">🔍 動態掃描的篩選條件包含：</span><br>
        <span style="color: #d1d1d1;">
        1. <b>技術面 (隱藏多頭)</b>：股票必須在季線 (60MA) 之上，近一個月只溫和上漲 (0~15%)，且今天剛好回踩或緊貼月線 (20MA)，風險極低。<br>
        2. <b>籌碼面 (大人照顧)</b>：自動串接 FinMind，可透過下方滑桿自訂過濾出近期外資或投信正在偷偷佈局的股票。<br>
        3. <b>基本面 (估值評估)</b>：自動計算遠期本益比 (Forward PE)，幫您判斷現在買進是便宜、合理還是偏貴。<br>
        4. <b>消息面 (未來潛力)</b>：掃描最新新聞，偵測是否具備「成長、創新高、受惠」等題材，即使技術面破線也會給予關注提醒。
        </span>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("📌 自選觀察清單 (紅漲綠跌)")
    c_in, c_btn = st.columns([3, 1])
    with c_in:
        new_tw = st.text_input("新增台股", placeholder="輸入代號 (例如: 2317.TW)", label_visibility="collapsed", key="add_tw_input")
    with c_btn:
        if st.button("➕ 新增", key="btn_add_tw", use_container_width=True):
            if new_tw:
                tk = new_tw.upper()
                if not tk.endswith(".TW"): tk += ".TW"
                if tk not in st.session_state['watchlists']['TW']:
                    st.session_state['watchlists']['TW'].append(tk)
                    save_json(DB_WATCHLISTS, st.session_state['watchlists'])
                    st.rerun()

    tw_data = [analyze_stock_master(t, is_tw=True) for t in st.session_state['watchlists']['TW']]
    tw_overview = [d["overview"] for d in tw_data if d]
    
    if tw_overview:
        df_tw_view = pd.DataFrame(tw_overview)
