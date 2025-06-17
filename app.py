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

TRADE_ACCOUNT = os.getenv("TRADE_ACCOUNT", "50139411-01")
TRADE_PRODUCT_CODE = os.getenv("TRADE_PRODUCT_CODE", "01")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


scenarios = []
news_log = []
portfolio = {}
trade_history = []
current_scenario = None
_token_cache = {}
TOKEN_BUFFER_SECONDS = 60


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
    """Return a list of {'name': str, 'code': str} from OpenAI."""
    if not OPENAI_API_KEY:
        return []
    openai.api_key = OPENAI_API_KEY
    system = (
        "You are a financial assistant. Respond with a JSON array of objects "
        "containing 'name' and 6-digit 'code' for Korean stocks that match the query."
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            timeout=10,
        )
        text = resp.choices[0].message.content
        return json.loads(text)
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
            "tr_id": "VTTC8434R",
            "custtype": "P",
        }
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol,
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
    for item in sample_financials:
        if item["symbol"] == symbol:
            return {"name": item["corp_name"], "price": item["price"]}
    return {"name": symbol, "price": 0}

# analyzed query state
analysis_state = {}

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
    return (
        f"{scenario['name']} 현장가 {scenario['price']:,}원\n"
        f"주문수량 {q}주\n합계 금액 {total:,}원\n'매매 실행'을 누르세요"

    )

# Fetch latest news from Google News


def fetch_news(keywords):
    """Return the top 3 news articles for the given keywords."""
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


def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# Simple feature query interpretation (placeholder)


def analyze_query(query):
    """Very naive interpretation of a natural language query."""
    m = re.search(r"배단률.*?(\d+)\D*\uc704", query)
    if m:
        n = int(m.group(1))
        analysis_state['query'] = query
        analysis_state['type'] = 'dividend'
        analysis_state['count'] = n
        return f"배단률 상위 {n}\uac1c \uae30업을 \ucc3e습니다. \ub9de습니다?"
    if "자사주" in query and "소객" in query:
        analysis_state['query'] = query
        analysis_state['type'] = 'buyback'
        return "자사주 보유가 많고 소객하지 않는 회사를 \ucc3e습니다. \ub9de습니다?"

    if "per" in query.lower() and ("저표가" in query or "낮" in query):
        analysis_state['query'] = query
        analysis_state['type'] = 'per_search'
        return "PER 기준 \uc800표가 \uc885목 10\uac1c\ub97c \ucc3e습니다. \ub9de습니다?"

    return "요청을 이해하지 \ubabb했습니다."

def dividend_rank(n):
    ranked = sorted(
        sample_financials,
        key=lambda x: (x['dps'] / x['price'] if x['price'] else 0),
        reverse=True,
    )
    out = []
    for comp in ranked[:n]:
        pct = comp['dps'] / comp['price'] * 100 if comp['price'] else 0
        out.append(f"{comp['corp_name']}({comp['symbol']}): {pct:.2f}%")
    return "\n".join(out)

# Provide example results for feature search

corp_map = {item["corp_name"]: item["corp_code"] for item in sample_financials}

def get_dart_data(name):
    """Fetch company information from the DART API."""
    code = corp_map.get(name)
    if not code:
        return "Company not found"
    try:
        resp = requests.get(
            "https://opendart.fss.or.kr/api/company.json",
            params={"crtfc_key": DART_API_KEY, "corp_code": code},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        return f"Request error: {e}"


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
        return f"{msg} 현장 보유 {portfolio[symbol]}\uc8fc"
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




def example_results(query):
    """Return search results using sample DART data."""
    return get_dart_data(query)

def perform_query(_=None):
    if analysis_state.get('type') == 'dividend':
        n = analysis_state.get('count', 0)
        return dividend_rank(n)
    elif analysis_state.get('type') == 'buyback':
        return "자사주 보유량 데이터 예시"
    elif analysis_state.get('type') == 'per_search':
        stocks = search_stocks_openai(analysis_state.get('query', ''))
        if not stocks:
            return "검색 결과가 없습니다."
        lines = []
        for s in stocks[:10]:
            code = s.get('code') or s.get('symbol')
            if not code:
                continue
            info = get_stock_per(code)
            lines.append(f"{info['name']}({info['code']}): PER {info['per']}")
        return "\n".join(lines) if lines else "결과 없음"

    return "분석된 내용이 없습니다."

with gr.Blocks() as demo:
    gr.Markdown("## 간단한 로보 어드바이저 예제")
    with gr.Tab("시나리오 저장소"):
        history_table = gr.Dataframe(headers=["시간", "시나리오", "종목", "이름", "수량", "가격", "총액"], interactive=False)

    with gr.Tab("시나리오 투자"):
        scenario_text = gr.Textbox(label="시나리오 내용")
        quantity = gr.Textbox(label="주문 수량")
        symbol = gr.Textbox(label="종목 코드")
        keywords = gr.Textbox(label="뉴스 검색 키워드")
        add_btn = gr.Button("시나리오 추가")
        scenario_out = gr.Textbox(label="상태")
        add_btn.click(add_scenario, [scenario_text, quantity, keywords, symbol], scenario_out)
        trade_btn = gr.Button("매매 실행")
        trade_result = gr.Textbox(label="매매 결과")
        trade_btn.click(trade_current, None, [trade_result, history_table])

        news_btn = gr.Button("최신 뉴스 확인")
        news_out = gr.Textbox(label="뉴스 결과")
        news_btn.click(fetch_news, keywords, news_out)
    with gr.Tab("특집 검색"):
        feature_query = gr.Textbox(label="검색 프론트")
        analyze_btn = gr.Button("프론트 해석")
        analysis = gr.Textbox(label="해석 결과")
        analyze_btn.click(analyze_query, feature_query, analysis)
        confirm_btn = gr.Button("해석 확인")
        cancel_btn = gr.Button("취소")
        results = gr.Textbox(label="검색 결과")
        confirm_btn.click(perform_query, None, results)
        cancel_btn.click(lambda: "취소되었습니다.", None, results)

    gr.Markdown(
        "NEWS_API_KEY가 있으면 뉴스API를 사용하고, DART_API_KEY및 TRADE_API_KEY, TRADE_API_URL을 설정하면 실 결상API를 호출합니다."

    )

if __name__ == "__main__":
    threading.Thread(target=run_scheduler, daemon=True).start()
    demo.launch(share=True)
