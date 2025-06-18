# roboadivser

A simple robo advisor example providing a web interface for scenario-based investment and feature search. See `app.py` for the implementation. To clone the repository with the `work` branch if it exists, run `python clone_repo.py <repo_url>`.

## Running
1. Install the requirements:
   ```bash
   pip install -r requirements.txt
   ```
2. Launch the app:
   ```bash
   python app.py
   ```
   The app uses Gradio and will print a public URL when `share=True`.

Set `OPENAI_API_KEY` in your environment or enter it in the **특징 검색** tab

before searching for stocks. The key is kept in memory only. Ensure that your
environment allows outbound connections to `api.openai.com`; otherwise OpenAI
requests will fail with a timeout error.

You can also upload a JPG image in the same tab to have GPT describe the
picture.

### Feature search
The "특징 검색" tab forwards your prompt to OpenAI with the system message:
"당신은 주식 전문가입니다. 사용자가 물어보는 주식에 대한 질문의 의도를 파악하세요. 만약 사진이 첨부되면 해당 사진을 사용자가 이해할 수 있게 쉽게 설명하세요. 그외에는 사용자 질문에 대한 간단한 설명과 추천 주식과 이유를 제공하세요." Responses are generated with the `gpt-4o-mini` model.

### Scenario storage
The "시나리오 저장소" tab lists all scenarios and completed trades. After you add scenarios in the "시나리오 투자" tab, the dropdown in this tab will refresh so you can pick a scenario and press **뉴스 검색** to view related headlines. Use **접기** to hide the results.

You can also press **주식투자 조언받기** to send your trade history to OpenAI and receive personalized investment advice. Each reply is stored in the new **조언 기록** tab.

### 조언 기록
The "조언 기록" tab displays all advice returned by OpenAI so you can review past recommendations.

### News API
To fetch news headlines, set the following environment variables for Naver's open API:

```
export NAVER_CLIENT_ID=<your id>
export NAVER_CLIENT_SECRET=<your secret>
```
If these variables are not set, the app falls back to Google News RSS using Korean search parameters so results should appear for most keywords.
