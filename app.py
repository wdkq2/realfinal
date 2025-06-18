import os
import base64
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
openai_key = OPENAI_API_KEY

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")


scenarios = []
news_log = []
portfolio = {}
trade_history = []
current_scenario = None
advice_log = []
_token_cache = {}
TOKEN_BUFFER_SECONDS = 60


def set_openai_key(key):
    """Update the OpenAI API key from user input."""
    global openai_key
    openai_key = key.strip()
    return "API key set"


def scenario_table_data():
    """Return list representation of scenarios for a Dataframe."""
    return [[s["time"], s["desc"], s["symbol"], s["qty"], s["keywords"]] for s in scenarios]


def scenario_options():
    """Dropdown options for selecting a scenario."""
    return [f"{i}. {s['desc']}" for i, s in enumerate(scenarios)]


def advice_table_data():
    """Return list representation of advice log."""
    return [[a["time"], a["text"]] for a in advice_log]


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
    table_update = gr.update(value=scenario_table_data())
    dropdown_update = gr.update(choices=scenario_options(), value=None)
    return msg, table_update, dropdown_update

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
    params = {"q": keywords, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
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


def get_advice():
    """Call OpenAI with trade history and store the advice."""
    if not openai_key:
        return (
            "OPENAI_API_KEY가 설정되지 않았습니다.",
            gr.update(value=advice_table_data()),
            "",
        )
    if not trade_history:
        return (
            "거래 기록이 없습니다.",
            gr.update(value=advice_table_data()),
            "",
        )

    summary_lines = [
        f"{h['time']} {h['scenario']} {h['name']}({h['symbol']}) {h['qty']}주 총액 {h['total']}원"
        for h in trade_history
    ]
    summary = "\n".join(summary_lines)
    system_prompt = (
        "위는 사용자가 어떤 시나리오를 가지고 어떤 종목을 얼마나 샀는지의 기록입니다. "
        "해당 기록을 살펴보고, 해당 사용자의 투자 성향을 파악하세요. 해당 성향에 따라 투자자에게 조언과 투자자가 관심있을만한 주식과 이유를 설명해주세요."
    )
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": summary}]
    try:
        if hasattr(openai, "OpenAI"):
            client = openai.OpenAI(api_key=openai_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                timeout=10,
            )
        else:
            openai.api_key = openai_key
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=messages,
                timeout=10,
            )
        advice = resp.choices[0].message.content.strip()
    except Exception as e:
        advice = f"OpenAI error: {e}"
    advice_log.append(
        {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "text": advice}
    )
    table_update = gr.update(value=advice_table_data())
    return advice, table_update, advice




def search_codes(prompt, image_path):
    """Send the user's prompt and optional image to OpenAI."""
    if not openai_key:
        return "OPENAI_API_KEY가 설정되지 않았습니다."
    try:
        if hasattr(openai, "OpenAI"):
            client = openai.OpenAI(api_key=openai_key)
            if image_path:
                with open(image_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                content = []
                if prompt:
                    content.append({"type": "text", "text": prompt})
                else:
                    content.append({"type": "text", "text": "이미지를 설명해줘."})
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
                messages = [{"role": "user", "content": content}]
                model = "gpt-4o-mini"
            else:
                messages = [
                    {"role": "system", "content": "당신은 주식 전문가입니다. 사용자가 물어보는 주식에 대한 질문의 의도를 파악하세요. 만약 사진이 첨부되면 해당 사진을 사용자가 이해할 수 있게 쉽게 설명하세요. 그외에는 사용자 질문에 대한 간단한 설명과 추천 주식과 이유를 제공하세요."},
                    {"role": "user", "content": prompt},
                ]
                model = "gpt-4o-mini"

            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                timeout=10,
            )
        else:
            openai.api_key = openai_key
            if image_path:
                return "현재 openai 패키지가 이미지 입력을 지원하지 않습니다."
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "당신은 주식 전문가입니다. 사용자가 물어보는 주식에 대한 질문의 의도를 파악하세요. 만약 사진이 첨부되면 해당 사진을 사용자가 이해할 수 있게 쉽게 설명하세요. 그외에는 사용자 질문에 대한 간단한 설명과 추천 주식과 이유를 제공하세요."}, {"role": "user", "content": prompt}],

                timeout=10,
            )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"OpenAI error: {e}"

with gr.Blocks() as demo:
    gr.Markdown("## 간단한 로보 어드바이저 예제")
    with gr.Tab("시나리오 저장소"):
        history_table = gr.Dataframe(headers=["시간", "시나리오", "종목", "이름", "수량", "가격", "총액"], interactive=False)
        scenario_table = gr.Dataframe(headers=["시간", "시나리오", "종목", "수량", "키워드"], interactive=False, value=scenario_table_data())
        scenario_select = gr.Dropdown(label="시나리오 선택", choices=scenario_options())
        news_show_btn = gr.Button("뉴스 검색")
        news_close_btn = gr.Button("접기")
        scenario_news = gr.Textbox(label="뉴스 결과", visible=False)
        advice_btn = gr.Button("주식투자 조언받기")
        advice_result = gr.Textbox(label="조언 결과")
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
        openai_key_input = gr.Textbox(label="OpenAI API Key", type="password")
        set_key_btn = gr.Button("키 설정")
        key_status = gr.Textbox(label="상태", interactive=False)
        set_key_btn.click(set_openai_key, openai_key_input, key_status)
        feature_query = gr.Textbox(label="검색 프롬프트")
        image_input = gr.Image(label="JPG 업로드", type="filepath")
        search_btn = gr.Button("검색")
        results = gr.Textbox(label="검색 결과")
        search_btn.click(search_codes, [feature_query, image_input], results)

    with gr.Tab("조언 기록"):
        advice_table = gr.Dataframe(headers=["시간", "조언"], interactive=False, value=advice_table_data())
        advice_last = gr.Textbox(label="최근 조언", interactive=False)

    advice_btn.click(get_advice, None, [advice_result, advice_table, advice_last])

    gr.Markdown(
        "NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET을 설정하면 네이버 뉴스 API를 사용합니다. 또한 DART_API_KEY와 TRADE_API_KEY, TRADE_API_URL을 지정하면 실거래 API를 호출합니다."

    )

if __name__ == "__main__":
    threading.Thread(target=run_scheduler, daemon=True).start()
    demo.launch(share=True)
