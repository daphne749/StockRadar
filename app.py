import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import json
import os
import base64
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

# === GitHub 雲端雙向同步模組 ===
def get_github_config():
    try:
        token = str(st.secrets.get("GITHUB_TOKEN", "")).strip()
        repo = str(st.secrets.get("GITHUB_REPO", "daphne749/StockRadar")).strip()
        return token, repo
    except Exception:
        return "", "daphne749/StockRadar"

def load_json_sync(file_path, default_data):
    token, repo = get_github_config()
    if token:
        url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                content_b64 = res.json().get("content", "")
                decoded = base64.b64decode(content_b64).decode("utf-8")
                return json.loads(decoded)
        except Exception:
            pass
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_data

def save_json_sync(file_path, data):
    # 先寫入本機暫存
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    # 若有設定 GITHUB_TOKEN，同步寫回 GitHub
    token, repo = get_github_config()
    if not token:
        return False, "僅儲存於暫存區（尚未設定 GITHUB_TOKEN）"

    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        sha = None
        get_res = requests.get(url, headers=headers, timeout=10)
        if get_res.status_code == 200:
            sha = get_res.json().get("sha")

        content_str = json.dumps(data, ensure_ascii=False, indent=4)
        content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
        payload = {
            "message": f"Update {file_path} via StockRadar Web",
            "content": content_b64
        }
        if sha:
            payload["sha"] = sha

        put_res = requests.put(url, headers=headers, json=payload, timeout=12)
        if put_res.status_code in (200, 201):
            return True, "已自動同步至 GitHub 排程清單"
        return False, f"GitHub 同步失敗 ({put_res.status_code})"
    except Exception as e:
        return False, f"GitHub 同步異常：{e}"

# === Discord Webhook 推播核心模組 (自動分段 + 強制 IPv4 穩定通道) ===
def get_discord_webhook():
    url = st.session_state.get("custom_discord_url", "")
    if not url:
        try:
            url = st.secrets.get("DISCORD_WEBHOOK_URL", "")
        except Exception:
            url = ""
    return str(url).strip()

def _split_discord_chunks(text, limit=1900):
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

def send_discord_msg(text):
    webhook_url = get_discord_webhook()
    if not webhook_url:
        return False, "尚未設定 DISCORD_WEBHOOK_URL"
    if not webhook_url.startswith("http"):
        return False, "Webhook 網址格式不正確，請確認以 https://discord.com/api/webhooks/ 開頭"

    orig_family = urllib3_cn.allowed_gai_family
    urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
    try:
        for chunk in _split_discord_chunks(text):
            res = requests.post(
                webhook_url,
                json={"content": chunk, "username": "StockRadar 選股雷達"},
                timeout=15
            )
            if res.status_code not in (200, 204):
                return False, f"Discord 拒絕發送 (狀態碼 {res.status_code})：{res.text[:120]}"
        return True, "推播成功"
    except requests.exceptions.Timeout:
        return False, "連線逾時，請稍後再試一次"
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
    except Exception:
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

if 'user_config' not in st.session_state:
    st.session_state['user_config'] = load_json_sync(DB_ALERTS, {})

if 'watchlists' not in st.session_state:
    default_wl = {"TW": ["2330.TW", "2454.TW", "2603.TW", "1519.TW"], "US": ["AAPL", "MSFT", "NVDA", "COIN"]}
    st.session_state['watchlists'] = load_json_sync(DB_WATCHLISTS, default_wl)

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
    search_term = ticker.replace(".TW", "").replace(".TWO", "") + (" 股票" if is_tw else " stock news")
    query = urllib.parse.quote(search_term)
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW"
    try:
        res = requests.get(url, timeout=3)
        return res.text
    except Exception:
        return ""

def check_future_potential(news_text, eps_growth):
    keywords = ["受惠", "成長", "訂單", "創新高", "潛力", "看好", "升評", "AI", "轉型", "突破", "大增", "爆發"]
    score = sum(news_text.count(kw) for kw in keywords)
    if score >= 5 or eps_growth > 20: return "🔥 題材熱絡 (具未來性)"
    elif score >= 2: return "🟡 具備話題"
    return "⚪ 暫無明顯題材"

@st.cache_data(ttl=1800)
def get_finmind_chips(ticker, days=5):
    if not (ticker.endswith(".TW") or ticker.endswith(".TWO")):
        return {"外資買賣超": 0, "投信買賣超": 0, "狀態": "美股不適用"}
    stock_id = ticker.replace(".TW", "").replace(".TWO", "")
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
    except Exception:
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
    except Exception:
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
            
            stock_id = ticker.replace(".TW", "").replace(".TWO", "")
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
        except Exception:
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

# === 4. 整合分析引擎 (已加入空值防呆保護) ===
@st.cache_data(ttl=1800)
def analyze_stock_master(ticker, is_tw=True, max_price=99999, min_foreign=0, min_trust=0, filter_stealth=False):
    stock = yf.Ticker(ticker)
    try:
        df = stock.history(period="6mo")
        if df is None or df.empty:
            return None
        df = df.dropna(subset=["Close"])
        if len(df) < 60:
            return None
    except Exception:
        return None
        
    latest_price = float(df.iloc[-1]["Close"])
    if pd.isna(latest_price) or latest_price <= 0 or latest_price > max_price:
        return None
        
    df = calculate_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    prev_close = float(prev["Close"])
    pct_change = ((latest_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
    month_return = float(latest["Return_20d"]) if not pd.isna(latest["Return_20d"]) else 0.0
    ma20 = float(latest["MA20"]) if not pd.isna(latest["MA20"]) else latest_price
    ma60 = float(latest["MA60"]) if not pd.isna(latest["MA60"]) else latest_price

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
    except Exception:
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

    display_ticker = ticker.replace(".TW", "").replace(".TWO", "")
    if is_tw:
        stock_name = TW_STOCK_NAMES.get(display_ticker, "")
        if stock_name:
            display_ticker = f"{display_ticker} {stock_name}"

    return {
        "overview": {
            "標的": display_ticker,
            "收盤價": latest_price, 
            "單日漲跌(%)": pct_change,
            "近一月漲跌(%)": month_return,
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

# === 5. 智慧情境警報引擎 (已加入空值防呆保護) ===
def generate_smart_alert(ticker, user_settings):
    stock = yf.Ticker(ticker)
    try:
        df = stock.history(period="6mo")
        if df is None or df.empty:
            return None
        df = df.dropna(subset=["Close"])
        if len(df) < 60:
            return None
    except Exception:
        return None
    
    df = calculate_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    price = float(latest["Close"])
    if pd.isna(price) or price <= 0:
        return None
    ma20 = float(latest["MA20"]) if not pd.isna(latest["MA20"]) else price
    low_10 = float(latest["Low_10"]) if not pd.isna(latest["Low_10"]) else price
    vol_ma5 = float(latest["Vol_MA5"]) if not pd.isna(latest["Vol_MA5"]) else 0.0
    vol_surge = (float(latest["Volume"]) > (vol_ma5 * 1.3)) if vol_ma5 > 0 else False
    rsi_val = float(latest["RSI"]) if not pd.isna(latest["RSI"]) else 0.0
    
    status = user_settings.get("status", "observing") 
    cost = float(user_settings.get("cost", 0.0))
    note = user_settings.get("note", "")
    target_price = float(user_settings.get("target_price", 0.0))
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
        elif price > ma20 and vol_surge and rsi_val > 50:
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
        if st.button("📲 將今日潛力股推播至 Discord", use_container_width=True):
            msg_lines = [f"**🤖 AI 基本面潛力股日報 ({datetime.date.today()})**\n"]
            if tw_picks:
                msg_lines.append("**🇹🇼 台股篩選名單：**")
                for item in tw_picks:
                    msg_lines.append(f"• **{item['ticker']} {item['name']}**：年增 {item['yoy']}｜EPS {item['eps_ttm']}｜毛利 {item['gm']}｜營益 {item['opm']}")
            if us_picks:
                msg_lines.append("\n**🇺🇸 美股篩選名單：**")
                for item in us_picks:
                    msg_lines.append(f"• **{item['ticker']} ({item['name']})**：年增 {item['yoy']}｜EPS ${item['eps_ttm']}｜毛利 {item['gm']}｜營益 {item['opm']}")
            if not tw_picks and not us_picks:
                msg_lines.append("今日暫無符合嚴格基本面條件之標的。")
            ok, status_msg = send_discord_msg("\n".join(msg_lines))
            if ok: st.success("✅ 已成功推播至您的 Discord！")
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
        new_tw = st.text_input("新增台股", placeholder="輸入代號 (上市加 .TW、上櫃加 .TWO，例: 2317.TW)", label_visibility="collapsed", key="add_tw_input")
    with c_btn:
        if st.button("➕ 新增", key="btn_add_tw", use_container_width=True):
            if new_tw:
                tk = new_tw.strip().upper()
                if not (tk.endswith(".TW") or tk.endswith(".TWO")): tk += ".TW"
                if tk not in st.session_state['watchlists']['TW']:
                    st.session_state['watchlists']['TW'].append(tk)
                    save_json_sync(DB_WATCHLISTS, st.session_state['watchlists'])
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
                        code = t.split(' ')[0]
                        st.session_state['watchlists']['TW'] = [
                            x for x in st.session_state['watchlists']['TW']
                            if not x.startswith(code + ".")
                        ]
                    save_json_sync(DB_WATCHLISTS, st.session_state['watchlists'])
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

    col1, col2 = st.columns(2)
    with col1: max_price_tw = st.number_input("最高股價 (台幣)", value=150, step=10, key="max_tw")
    with col2: min_foreign = st.slider("外資近5日買超 > (張)", 0, 5000, 0, 500)
    
    col3, col4 = st.columns(2)
    with col3: min_trust = st.slider("投信近5日買超 > (張)", 0, 2000, 0, 100)
    with col4:
        st.write("")
        stealth_only = st.checkbox("只抓隱藏多頭", value=True, key="stealth_tw")
        
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
                
                dc_lines = [f"**🇹🇼 台股波段雷達掃描結果 ({datetime.date.today()})**\n"]
                for r in scan_res:
                    dc_lines.append(f"• **{r['標的']}**｜現價 {r['收盤價']:.2f}｜{r['綜合決策']}｜停損 {r['防守停損']:.2f} / 停利 {r['停利目標']:.2f}")
                ok, s_msg = send_discord_msg("\n".join(dc_lines))
                if ok: st.toast("📲 已同步推播台股掃描結果至 Discord！")
            else:
                st.info("💡 今日掃描池中，沒有符合技術面買點的股票。")

# ----------------- 分頁 2：美股波段雷達 -----------------
with tab_us:
    st.header("🇺🇸 美股波段雷達")
    
    st.markdown("""
    <div style="background-color: #262730; padding: 15px; border-radius: 8px; border: 1px solid #4f4f4f; margin-bottom: 20px;">
        <span style="font-size: 1.1em; font-weight: bold; color: #00cc96;">核心策略：20MA 回調買入法 + 多因子濾網</span><br>
        <span style="color: #d1d1d1;">這套雷達旨在幫您避開「追高被套」的風險，專門尋找<b>大趨勢保護下，剛好拉回支撐</b>的潛力美股。</span><br><br>
        <span style="font-weight: bold; color: #ffffff;">🔍 動態掃描的篩選條件包含：</span><br>
        <span style="color: #d1d1d1;">
        1. <b>技術面 (隱藏多頭)</b>：勾選「只抓隱藏多頭」時，專門鎖定在季線 (60MA) 之上、近一月溫和上漲 (0~15%) 且緊貼月線 (20MA) 的標的；<b>取消勾選則會放寬限制並一併掃描熱門權值股</b>。<br>
        2. <b>基本面 (估值評估)</b>：自動計算遠期本益比 (Forward PE)，幫您判斷現在買進是便宜、合理還是偏貴。<br>
        3. <b>消息面 (未來潛力)</b>：掃描最新新聞，偵測是否具備「成長、創新高、受惠」等題材，即使技術面破線也會給予關注提醒。
        </span>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("📌 自選觀察清單 (綠漲紅跌)")
    c_in_us, c_btn_us = st.columns([3, 1])
    with c_in_us:
        new_us = st.text_input("新增美股", placeholder="輸入代號 (例如: TSLA)", label_visibility="collapsed", key="add_us_input")
    with c_btn_us:
        if st.button("➕ 新增", key="btn_add_us", use_container_width=True):
            if new_us:
                tk = new_us.strip().upper()
                if tk not in st.session_state['watchlists']['US']:
                    st.session_state['watchlists']['US'].append(tk)
                    save_json_sync(DB_WATCHLISTS, st.session_state['watchlists'])
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
                    save_json_sync(DB_WATCHLISTS, st.session_state['watchlists'])
                    st.session_state.us_edit_key += 1
                    st.rerun()
            with col_n_us:
                if st.button("❌ 取消", use_container_width=True, key="us_del_no"):
                    st.session_state.us_edit_key += 1
                    st.rerun()
    else:
        st.info("美股觀察清單目前為空，請從上方輸入代號新增。")

    st.markdown("---")
    st.subheader("🔍 市場動態掃描 (隱藏多頭 / 熱門權值股)")
    
    col_u1, col_u2 = st.columns([1, 1])
    with col_u1:
        max_price_us = st.number_input("最高股價 (美元)", value=1000, step=50, key="max_us")
    with col_u2:
        st.write("")
        stealth_only_us = st.checkbox("只抓隱藏多頭", value=True, key="stealth_us", help="取消勾選時，將放寬技術面條件並一併抓取 NVDA、AAPL、MSFT 等熱門股")

    scan_us_btn = st.button("🚀 執行美股動態掃描", type="primary", use_container_width=True)

    if scan_us_btn:
        with st.spinner("掃描美股板塊與計算中..."):
            US_NICHE_POOL = ["FOUR", "VRT", "ONON", "CELH", "ELF", "UBER", "HOOD", "RDDT", "WING", "DKNG", "PLTR", "DDOG", "CRWD", "ARM"]
            US_HOT_POOL = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "AMD", "NFLX", "MU", "ORCL", "CRM", "TSM"]
            
            scan_pool_us = US_NICHE_POOL if stealth_only_us else list(dict.fromkeys(US_NICHE_POOL + US_HOT_POOL))
            scan_res_us, eps_res_us = [], []
            for t in scan_pool_us:
                res = analyze_stock_master(t, is_tw=False, max_price=max_price_us, filter_stealth=stealth_only_us)
                if res:
                    scan_res_us.append(res["overview"])
                    eps_res_us.append(res["eps_details"])
            
            if scan_res_us:
                mode_label = "隱藏多頭" if stealth_only_us else "全池含熱門股"
                st.success(f"✅ 掃描完成（{mode_label}），共篩選出 {len(scan_res_us)} 檔標的！")
                st.dataframe(
                    pd.DataFrame(scan_res_us).style.map(color_us, subset=['單日漲跌(%)', '近一月漲跌(%)']), 
                    use_container_width=True, hide_index=True
                )
                with st.expander("📊 點擊展開 EPS 獲利分析表"):
                    st.table(pd.DataFrame(eps_res_us))
                
                dc_lines_us = [f"**🇺🇸 美股波段雷達掃描結果 ({datetime.date.today()}｜{mode_label})**\n"]
                for r in scan_res_us:
                    dc_lines_us.append(f"• **{r['標的']}**｜現價 ${r['收盤價']:.2f}｜{r['綜合決策']}｜停損 ${r['防守停損']:.2f} / 停利 ${r['停利目標']:.2f}")
                ok, s_msg = send_discord_msg("\n".join(dc_lines_us))
                if ok: st.toast("📲 已同步推播美股掃描結果至 Discord！")
            else:
                st.info("💡 今日市場無符合條件的標的（可嘗試取消勾選「只抓隱藏多頭」以檢視熱門股）。")

# ----------------- 分頁 3：智慧趨勢提醒與健檢 -----------------
with tab_alerts:
    st.header("🧠 情境式智慧趨勢監控與持股健檢")
    st.markdown("設定專屬監控標的，系統會在技術面達標、或到達特定日期/價格時跳出具體行動建議並同步推播至 Discord。")
    
    # Discord 與 GitHub 同步狀態區塊
    with st.expander("📲 Discord 推播與 GitHub 排程同步狀態", expanded=False):
        cur_webhook = get_discord_webhook()
        gh_token, gh_repo = get_github_config()
        if cur_webhook:
            st.success("✅ 已讀取 Discord Webhook 連線設定")
        else:
            st.warning("⚠️ 尚未讀取到 `DISCORD_WEBHOOK_URL`，請於 Streamlit Secrets 設定。")
        
        if gh_token:
            st.success(f"☁️ 已啟用 GitHub 自動同步（`{gh_repo}`），網頁修改將自動套用至每日盤後排程")
        else:
            st.info("💡 尚未設定 `GITHUB_TOKEN`，目前修改僅存在網頁暫存區，不會同步到每日盤後排程。")

        in_webhook = st.text_input("Discord Webhook 網址 (若已設 Secrets 可留空)", type="password", key="dc_url_in")
        if in_webhook:
            st.session_state["custom_discord_url"] = in_webhook
            
        if st.button("📨 發送 Discord 測試訊息", use_container_width=True):
            ok, msg = send_discord_msg("🔔 **波段選股雷達連線測試成功！**\n您的智慧趨勢提醒與策略掃描訊號已準備就緒。")
            if ok: st.success("✅ 測試訊息已發送！請查看您的 Discord 頻道通知。")
            else: st.error(f"❌ 發送失敗：{msg}")

    st.subheader("⚙️ 新增 / 編輯監控規則")
    with st.form("alert_config_form"):
        ticker_input = st.text_input("股票代號 (台股上市加 .TW、上櫃加 .TWO，美股直接輸入)", placeholder="例如: 2603.TW 或 NVDA")
        status_input = st.radio("交易目的", ["準備進場 (尚未持有)", "停利/風險管理 (已持有)"])
        cost_input = st.number_input("持有平均成本 (空手請填 0)", min_value=0.0, step=1.0)
        note_input = st.text_area("個人紀律筆記", placeholder="例如：等下週四法說會開完再決定。")
        
        enable_date = st.checkbox("設定日期提醒")
        date_input = st.date_input("選擇提醒日", value=datetime.date.today()) if enable_date else None
        target_price_input = st.number_input("到達特定價格提醒 (0代表不設定)", min_value=0.0, step=1.0)
        
        if st.form_submit_button("💾 儲存監控規則並同步排程", use_container_width=True):
            if ticker_input:
                ticker = ticker_input.strip().upper()
                st.session_state['user_config'][ticker] = {
                    "status": "holding" if "已持有" in status_input else "observing",
                    "cost": cost_input, "note": note_input, "target_price": target_price_input,
                    "reminder_date": date_input.strftime("%Y-%m-%d") if enable_date else ""
                }
                ok_sync, sync_msg = save_json_sync(DB_ALERTS, st.session_state['user_config'])
                if ok_sync:
                    st.success(f"✅ 已更新 {ticker} 的監控規則！（{sync_msg}）")
                else:
                    st.warning(f"已更新 {ticker}，但：{sync_msg}")

    # 目前監控清單管理（含一鍵刪除）
    st.markdown("---")
    st.subheader("📋 目前監控清單管理")
    config = st.session_state['user_config']
    if not config:
        st.info("目前沒有監控中的標的。請從上方表單新增。")
    else:
        for tk, s in list(config.items()):
            code = tk.replace(".TW", "").replace(".TWO", "")
            tk_label = f"{tk} {TW_STOCK_NAMES[code]}" if (tk.endswith(".TW") or tk.endswith(".TWO")) and code in TW_STOCK_NAMES else tk
            status_str = "已持有" if s.get("status") == "holding" else "觀察中"
            cost_str = f"成本 {s.get('cost', 0)}" if s.get("cost", 0) > 0 else "空手"
            target_str = f"目標價 {s.get('target_price', 0)}" if s.get("target_price", 0) > 0 else "無目標價"
            date_str = f"提醒日 {s.get('reminder_date')}" if s.get("reminder_date") else ""
            note_str = f"｜📝 {s.get('note')}" if s.get("note") else ""

            c_info, c_del = st.columns([5, 1])
            with c_info:
                st.markdown(f"**{tk_label}** 〔{status_str}〕｜{cost_str}｜{target_str} {date_str}{note_str}")
            with c_del:
                if st.button("🗑️ 刪除", key=f"del_alert_{tk}", use_container_width=True):
                    del st.session_state['user_config'][tk]
                    ok_sync, sync_msg = save_json_sync(DB_ALERTS, st.session_state['user_config'])
                    st.toast(f"已刪除 {tk}（{sync_msg}）")
                    st.rerun()

    st.markdown("---")
    st.subheader("📩 趨勢通知與多維健檢中心")
    if config:
        auto_push_dc = st.checkbox("📲 掃描觸發警報時自動推播至 Discord", value=True)
        if st.button("🔄 立即執行全盤掃描與健檢", type="primary", use_container_width=True):
            with st.spinner("正在進行多面向情境診斷..."):
                alerts_found = 0
                dc_alert_messages = []
                for ticker, settings in config.items():
                    alert_data = generate_smart_alert(ticker, settings)
                    
                    if alert_data:
                        alerts_found += 1
                        border_color = "#ff4b4b" if "風險" in alert_data["目前階段"] else "#00cc96" if "確認" in alert_data["目前階段"] else "#ffc107"
                        
                        custom_html = ""
                        custom_dc = ""
                        if alert_data.get("自訂觸發項目"):
                            for msg in alert_data["自訂觸發項目"]:
                                custom_html += f"<div style='color: #ffc107; font-weight: bold; margin-bottom: 5px;'>{msg}</div>"
                                custom_dc += f"\n{msg}"
                                
                        note_text = alert_data.get('個人筆記', '')
                        note_html = f"<i style='color: #bbb;'>{note_text}</i>" if note_text else "<i style='color: #666;'>無</i>"

                        display_ticker_alert = ticker.replace(".TW", "").replace(".TWO", "")
                        if (".TW" in ticker or ".TWO" in ticker) and display_ticker_alert in TW_STOCK_NAMES:
                            display_ticker_alert = f"{display_ticker_alert} {TW_STOCK_NAMES[display_ticker_alert]}"

                        dc_block = (
                            f"**🚨 {display_ticker_alert} - {alert_data['目前階段']}**{custom_dc}\n"
                            f"• **發生什麼事：**{alert_data['發生什麼事']}\n"
                            f"• **🎯 建議下一步：**{alert_data['建議下一步']}\n"
                            f"• **⚠️ 失效條件：**{alert_data['失效條件']}\n"
                            f"• **📝 決策筆記：**{note_text if note_text else '無'}"
                        )
                        dc_alert_messages.append(dc_block)

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
                elif auto_push_dc and dc_alert_messages:
                    full_dc_text = f"**🔔 智慧趨勢監控警報 ({datetime.date.today()})**\n\n" + "\n\n━━━━━━━━━━\n\n".join(dc_alert_messages)
                    ok, msg = send_discord_msg(full_dc_text)
                    if ok: st.success("📲 已自動將上述觸發警報推播至您的 Discord！")
                    else: st.warning(f"⚠️ Discord 自動推播未完成：{msg}")

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
            stock = yf.Ticker(ts_ticker.strip().upper())
            info = stock.info
            
            base_ticker = ts_ticker.strip().upper().replace(".TW", "").replace(".TWO", "")
            if (".TW" in ts_ticker.upper() or ".TWO" in ts_ticker.upper()) and base_ticker in TW_STOCK_NAMES:
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
            news_html = fetch_news_text(ts_ticker, ".TW" in ts_ticker.upper() or ".TWO" in ts_ticker.upper())
            if any(k in news_html for k in ["創新高", "大增", "看好", "受惠"]): 
                st.success("雷達偵測到近期包含「創新高、大增、看好」等正面關鍵字。")
            elif any(k in news_html for k in ["衰退", "下修", "轉虧"]): 
                st.error("雷達偵測到近期包含「衰退、下修」等保守關鍵字。")
            else: 
                st.write("近期新聞情緒平穩。")
