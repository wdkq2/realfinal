import os
import re
import gradio as gr
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import threading
import schedule
import time
import json
import hashlib
import openai


DART_API_KEY = (
    os.getenv("DART_API_KEY")
    or "4bada9597f370d2896444b492c3a92ff9c2d8f96"
)
TRADE_API_KEY = os.getenv(
    "TRADE_API_KEY", "PShKdxdOkJXLjBKTVLAbh2c2V5RrX3klIRXv"
)
TRADE_API_SECRET = os.getenv(
    "TRADE_API_SECRET",
    "Vt/gy4uGEAhWT2Tn0DE6IK2u+CBt752yHht/VXcjJUk7NzgZkx3lVoSDHvj/G2+RZNxBBjxEn2ReYQKquoh5BJi9f4KKomsYxJ3cyQ6noTyb0ep1OHD/xIe3w2Y9h+eb0PG7hxwhZBmWwPO6VQq9KRXZockUH5qNTbDosA6mfbKssmxWL2o=",
)
TRADE_API_URL = os.getenv(
    "TRADE_API_URL", "https://openapivts.koreainvestment.com:29443"
)

TRADE_ACCOUNT = os.getenv("TRADE_ACCOUNT", "50139411")

TRADE_PRODUCT_CODE = os.getenv("TRADE_PRODUCT_CODE", "01")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")


scenarios = []
news_log = []
portfolio = {}
trade_history = []
current_scenario = None
_token_cache = {}
TOKEN_BUFFER_SECONDS = 60


def scenario_table_data():
    """Return list representation of scenarios for a Dataframe."""
    return [[s["time"], s["desc"], s["symbol"], s["qty"], s["keywords"]] for s in scenarios]


def scenario_options():
    """Dropdown options for selecting a scenario."""
    return [f"{i}. {s['desc']}" for i, s in enumerate(scenarios)]


def get_access_token():
    """Retrieve an access token for the trading API using /oauth2/tokenP."""
    global _token_cache
    now = datetime.utcnow()
    if _token_cache and now < _token_cache.get("expires_at", now):
        return _token_cache.get("access_token")

    token_url = f"{TRADE_API_URL}/oauth2/tokenP"
    payload = {
        "grant_type": "client_credentials",
        "appkey": TRADE_API_KEY,
        "appsecret": TRADE_API_SECRET,
    }
    try:
        r = requests.post(
            token_url,

            headers={"Content-Type": "application/json; charset=UTF-8"},
            json=payload,

            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        token = data.get("access_token")
        expires = int(data.get("expires_in", 0))
        if token:
            _token_cache = {
                "access_token": token,
                "expires_at": now + timedelta(seconds=max(expires - TOKEN_BUFFER_SECONDS, 0)),
            }
        return token

    except Exception as e:
        print("Token error", e)
        return None


def make_hashkey(data):
    """Compute hash key using the hashkey endpoint."""
    url = f"{TRADE_API_URL}/uapi/hashkey"
    try:
        r = requests.post(
            url,
            headers={
                "content-type": "application/json; charset=utf-8",
                "appkey": TRADE_API_KEY,
                "appsecret": TRADE_API_SECRET,
            },
            json=data,
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("HASH")
    except Exception as e:
        print("Hashkey error", e)
        body = json.dumps(data, separators=(",", ":"))
        return hashlib.sha256(body.encode()).hexdigest()



# sample financial data for dividend yield calculation (예시)
sample_financials = [
    {"corp_name": "삼성전자", "symbol": "005930", "corp_code": "005930", "dps": 361, "price": 70000, "per": 12.3},
    {"corp_name": "현보사", "symbol": "005380", "corp_code": "005380", "dps": 3000, "price": 200000, "per": 8.5},
    {"corp_name": "NAVER", "symbol": "035420", "corp_code": "035420", "dps": 667, "price": 150000, "per": 20.1},
    {"corp_name": "카카오", "symbol": "035720", "corp_code": "035720", "dps": 0, "price": 60000, "per": 40.2},
    {"corp_name": "LG화학", "symbol": "051910", "corp_code": "051910", "dps": 12000, "price": 350000, "per": 15.0},
]


def search_stocks_openai(prompt):
    """Return a list of stock codes from OpenAI based on the prompt."""

    if not OPENAI_API_KEY:
        return []
    openai.api_key = OPENAI_API_KEY
    system = (
        "You are a financial assistant. Answer only with a JSON array of five 6-digit Korean stock codes."
    )
    user = (
        f"{prompt}에 맞는 국내 주식 5개를 찾아줘. "
        "해당 주식의 6자리 종목코드를 JSON 배열로만 제공해줘."
        " 대답은 오로지 종목코드만 줘야해."
    )

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            timeout=10,
        )
        text = resp.choices[0].message.content.strip()
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            codes = re.findall(r"\b\d{6}\b", text)
            if codes:
                return [{"code": c} for c in codes]
    except Exception as e:
        print("OpenAI error", e)
    return []


def get_stock_per(code):
    """Fetch stock name and PER from Naver's mobile API."""
    url = f"https://m.stock.naver.com/api/stock/{code}/integration"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
        data = r.json()
        name = data.get("stockName", code)
        per = None
        for item in data.get("totalInfos", []):
            if item.get("field") == "per":
                per = item.get("value")
        return {"name": name, "code": code, "per": per}
    except Exception as e:
        print("Naver API error", e)
        for item in sample_financials:
            if item["symbol"] == code:
                return {"name": item["corp_name"], "code": code, "per": item.get("per")}
        return {"name": code, "code": code, "per": None}




def get_stock_info(symbol):
    """Return stock name and current price using the trade API when possible."""
    token = get_access_token()
    if token:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": TRADE_API_KEY,
            "appsecret": TRADE_API_SECRET,
            "tr_id": "FHKST01010100",
            "custtype": "P",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,

        }
        try:
            r = requests.get(
                f"{TRADE_API_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=headers,
                params=params,
                timeout=10,
            )
            r.raise_for_status()
            out = r.json().get("output", {})
            name = out.get("hts_kor_isnm", symbol)
            price = int(float(out.get("stck_prpr", 0)))
            return {"name": name, "price": price}
        except Exception as e:
            print("Price error", e)

    # fallback to Naver mobile API when trade API call fails
    try:
        r = requests.get(
            f"https://m.stock.naver.com/api/stock/{symbol}/integration",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        name = data.get("stockName", symbol)
        price = int(float(data.get("closePrice", 0)))
        return {"name": name, "price": price}
    except Exception as e:
        print("Naver price error", e)

    for item in sample_financials:
        if item["symbol"] == symbol:
            return {"name": item["corp_name"], "price": item["price"]}
    return {"name": symbol, "price": 0}

# Add scenario and record investment


def add_scenario(desc, qty, keywords, symbol):
    global current_scenario
    info = get_stock_info(symbol)
    try:
        q = int(float(qty))
    except ValueError:
        return "수량이 잘못되었습니다."
    scenario = {
        "desc": desc,
        "qty": q,
        "keywords": keywords,
        "symbol": symbol,
        "name": info.get("name", symbol),
        "price": info.get("price", 0),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    current_scenario = scenario
    scenarios.append(scenario)
    schedule.every().day.at("08:00").do(check_news, scenario)
    total = scenario["price"] * q
    msg = (

        f"{scenario['name']} 현재가 {scenario['price']:,}원\n"
        f"주문수량 {q}주\n총 금액 {total:,}원\n'매매 실행'을 누르세요"

    )
    return msg, scenario_table_data(), scenario_options()


# Fetch latest news from Google News


def fetch_news(keywords):
    """Return the top 3 news articles for the given keywords."""
    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        url = "https://openapi.naver.com/v1/search/news.json"
        params = {"query": keywords, "display": 3, "sort": "date"}
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            return f"Request error: {e}"
        items = data.get("items", [])
        if not items:
            return "No news found"
        return "\n\n".join(f"{i.get('title')}\n{i.get('link')}" for i in items)

    api_key = os.getenv("NEWS_API_KEY")
    if api_key:
        url = (
            f"https://newsapi.org/v2/everything?q={keywords}&language=en&sortBy=publishedAt&apiKey={api_key}"
        )
        try:
            r = requests.get(url, timeout=10)
            data = r.json()
        except Exception as e:
            return f"Request error: {e}"
        articles = data.get("articles", [])[:3]
        if not articles:
            return "No news found"
        return "\n\n".join(
            f"{a.get('title')}\n{a.get('url')}" for a in articles
        )

    url = "https://news.google.com/rss/search"
    params = {"q": keywords, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    try:
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    except Exception as e:
        return f"Request error: {e}"
    root = ET.fromstring(r.text)
    items = root.findall("./channel/item")
    output = []
    for item in items[:3]:
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        output.append(f"{title}\n{link}")
    return "\n\n".join(output) if output else "No news found"


def check_news(scenario):
    news = fetch_news(scenario["keywords"])
    news_log.append({"scenario": scenario["desc"], "news": news, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    print(f"News update for {scenario['desc']}:\n{news}")


def show_scenario_news(choice):
    """Fetch news for the selected scenario."""
    if not choice:
        return gr.update(visible=True, value="시나리오를 선택하세요.")
    try:
        idx = int(choice.split(".")[0])
        sc = scenarios[idx]
    except (ValueError, IndexError):
        return gr.update(visible=True, value="Invalid selection")
    news = fetch_news(sc["keywords"])
    return gr.update(visible=True, value=news)


def hide_news():
    return gr.update(value="", visible=False)



def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)



def execute_trade(symbol, qty):
    """Send an order to the trading API using the Korea Investment mock endpoint."""
    try:
        q = int(float(qty))
    except ValueError:
        return "Invalid quantity"

    token = get_access_token()
    if not token:
        return "Failed to get access token"

    body = {
        "CANO": TRADE_ACCOUNT,
        "ACNT_PRDT_CD": TRADE_PRODUCT_CODE,
        "PDNO": symbol,
        "ORD_DVSN": "01",  # market order
        "ORD_QTY": str(q),
        "ORD_UNPR": "0",
    }
    hashkey = make_hashkey(body)
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": TRADE_API_KEY,
        "appsecret": TRADE_API_SECRET,
        "tr_id": "VTTC0012U",
        "custtype": "P",
        "hashkey": hashkey,
    }
    try:
        resp = requests.post(
            f"{TRADE_API_URL}/uapi/domestic-stock/v1/trading/order-cash",
            json=body,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        portfolio[symbol] = portfolio.get(symbol, 0) + q
        msg = data.get("msg1", "trade executed")
        return f"{msg} 현재 보유 {portfolio[symbol]}주"

    except requests.exceptions.HTTPError as e:
        err = resp.text if 'resp' in locals() else str(e)
        return f"Trade error: {e} {err}"

    except Exception as e:
        return f"Trade error: {e}"


def trade_current():
    """Execute trade for the current scenario and record history."""
    global current_scenario
    if not current_scenario:
        data = [[h["time"], h["scenario"], h["symbol"], h["name"], h["qty"], h["price"], h["total"]] for h in trade_history]
        return "시나리오가 없습니다.", data
    msg = execute_trade(current_scenario["symbol"], current_scenario["qty"])
    if not msg.startswith("Trade error") and not msg.startswith("Failed"):
        total = current_scenario["price"] * current_scenario["qty"]
        trade_history.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "scenario": current_scenario["desc"],
            "symbol": current_scenario["symbol"],
            "name": current_scenario["name"],
            "qty": current_scenario["qty"],
            "price": current_scenario["price"],
            "total": total,
        })
        current_scenario = None
    data = [[h["time"], h["scenario"], h["symbol"], h["name"], h["qty"], h["price"], h["total"]] for h in trade_history]
    return msg, data




def search_codes(prompt):
    """Query OpenAI with the prompt and show stock info for each returned code."""
    stocks = search_stocks_openai(prompt)
    if not stocks:
        return "검색 결과가 없습니다."
    lines = []
    for s in stocks:
        if isinstance(s, dict):
            code = s.get("code") or s.get("symbol")
        else:
            code = str(s)
        if not code:
            continue
        info = get_stock_info(code)
        per_info = get_stock_per(code)
        line = f"{info['name']}({code}) 현재가 {info['price']:,}원"
        if per_info.get('per') is not None:
            line += f" PER {per_info['per']}"
        lines.append(line)
    return "\n".join(lines) if lines else "검색 결과가 없습니다."

with gr.Blocks() as demo:
    gr.Markdown("## 간단한 로보 어드바이저 예제")
    with gr.Tab("시나리오 저장소"):
        history_table = gr.Dataframe(headers=["시간", "시나리오", "종목", "이름", "수량", "가격", "총액"], interactive=False)
        scenario_table = gr.Dataframe(headers=["시간", "시나리오", "종목", "수량", "키워드"], interactive=False, value=scenario_table_data())
        scenario_select = gr.Dropdown(label="시나리오 선택", choices=scenario_options())
        news_show_btn = gr.Button("뉴스 검색")
        news_close_btn = gr.Button("접기")
        scenario_news = gr.Textbox(label="뉴스 결과", visible=False)
        news_show_btn.click(show_scenario_news, scenario_select, scenario_news)
        news_close_btn.click(hide_news, None, scenario_news)


    with gr.Tab("시나리오 투자"):
        scenario_text = gr.Textbox(label="시나리오 내용")
        quantity = gr.Textbox(label="주문 수량")
        symbol = gr.Textbox(label="종목 코드")
        keywords = gr.Textbox(label="뉴스 검색 키워드")
        add_btn = gr.Button("시나리오 추가")
        scenario_out = gr.Textbox(label="상태")
        add_btn.click(add_scenario, [scenario_text, quantity, keywords, symbol], [scenario_out, scenario_table, scenario_select])

        trade_btn = gr.Button("매매 실행")
        trade_result = gr.Textbox(label="매매 결과")
        trade_btn.click(trade_current, None, [trade_result, history_table])

        news_btn = gr.Button("최신 뉴스 확인")
        news_out = gr.Textbox(label="뉴스 결과")
        news_btn.click(fetch_news, keywords, news_out)
    with gr.Tab("특징 검색"):
        feature_query = gr.Textbox(label="검색 프롬프트")
        search_btn = gr.Button("종목 검색")
        results = gr.Textbox(label="검색 결과")
        search_btn.click(search_codes, feature_query, results)

    gr.Markdown(
        "NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET을 설정하면 네이버 뉴스 API를 사용합니다. 또한 DART_API_KEY와 TRADE_API_KEY, TRADE_API_URL을 지정하면 실거래 API를 호출합니다."

    )

if __name__ == "__main__":
    threading.Thread(target=run_scheduler, daemon=True).start()
    demo.launch(share=True)
