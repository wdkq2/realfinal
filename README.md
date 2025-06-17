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
The "특징 검색" tab sends your prompt directly to OpenAI. The API returns five stock codes in JSON format, which the app then uses to fetch the latest price and PER for display.
