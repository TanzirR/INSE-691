# Beginner Stock Agent Demo

This small teaching demo shows how an AI agent can combine live stock data with a student's goal and risk tolerance. Alpaca supplies recent US stock prices. Students can ask Gemini or DeepSeek to explain the recommendation.

The entire application is one Python file and uses only the Python standard library.

## Run the demo

1. Install Python 3.10 or newer.
2. Add your Alpaca and Gemini API keys to `.env`.
3. Run:

```bash
python simple_stock_demo.py
```

4. Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

New to Python or API keys? Follow [BEGINNER_TUTORIAL.md](BEGINNER_TUTORIAL.md) from the beginning.

## What students can try

- Select a personal goal and risk tolerance.
- Look up well-known stocks such as Apple, Microsoft, NVIDIA, Amazon, or Tesla.
- Ask the agent whether a stock fits the selected profile.
- Change the profile and compare the recommendation.
- Switch between Gemini and DeepSeek without restarting the demo.
- Compare Gemini 3.5 Flash-Lite, Gemini 3.7 Flash, and Gemini 3.8 Flash.

The recommendations are for teaching purposes. The demo uses limited market data and does not place trades.

The listed Gemini models support free-tier use, subject to account, region, and rate limits. Check the [official Gemini pricing page](https://ai.google.dev/gemini-api/docs/pricing) for current availability. DeepSeek requires a DeepSeek API key and available API credit; see the [official DeepSeek model page](https://api-docs.deepseek.com/api/list-models/).
