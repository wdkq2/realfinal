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

### Feature search
The "특징 검색" tab forwards your prompt to OpenAI with the system message:
"너는 주식전문가야. 상대방 주식에 대한 고민에 대해 자세한 답변을 한글로 해줘." The model replies in Korean with detailed advice.

### Scenario storage
The "시나리오 저장소" tab lists all scenarios and completed trades. Select a scenario and press **뉴스 검색** to view related headlines, then **접기** to hide the results.

n
### News API
To fetch news headlines, set the following environment variables for Naver's open API:

```
export NAVER_CLIENT_ID=<your id>
export NAVER_CLIENT_SECRET=<your secret>
```
