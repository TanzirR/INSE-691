"""A dependency-free stock API and chat demo for beginners.

Run:
    python simple_stock_demo.py

Then open http://127.0.0.1:8765. The script uses only Python's standard
library and retrieves US stock data from Alpaca's Market Data API.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


HOST = "127.0.0.1"
PORT = 8765
DEFAULT_SYMBOL = "AAPL"
ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks/{symbol}"
SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
SYMBOL_IN_MESSAGE = re.compile(r"(?<![A-Za-z0-9])\$?([A-Z][A-Z0-9.-]{0,9})(?![A-Za-z0-9])")
POPULAR_STOCKS = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "META": "Meta",
    "TSLA": "Tesla",
}
PERSONAL_GOALS = {
    "long_term_growth": "Long-term growth (5+ years)",
    "short_term_growth": "Short-term growth (under 1 year)",
    "capital_preservation": "Protect capital",
    "income": "Generate income",
}
RISK_LEVELS = {
    "low": "Low - avoid large price swings",
    "moderate": "Moderate - accept some volatility",
    "high": "High - accept large price swings",
}
DEFAULT_GOAL = "long_term_growth"
DEFAULT_RISK = "moderate"
DEFAULT_AI_PROVIDER = "gemini"
AI_PROVIDERS = {
    "gemini": {
        "label": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-3.5-flash-lite",
        "models": {
            "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite",
            "gemini-3.7-flash": "Gemini 3.7 Flash",
            "gemini-3.8-flash": "Gemini 3.8 Flash",
        },
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-flash",
        "models": {
            "deepseek-v4-flash": "DeepSeek V4 Flash",
        },
    },
}


def moving_average(values: list[float], days: int) -> float:
    return sum(values[-days:]) / days


def normalize_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper().lstrip("$")
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("Enter a valid stock symbol, such as AAPL, MSFT, or BRK-B.")
    return symbol


def validate_profile(personal_goal: str, risk_tolerance: str) -> tuple[str, str]:
    if personal_goal not in PERSONAL_GOALS:
        raise ValueError("Choose a valid personal goal.")
    if risk_tolerance not in RISK_LEVELS:
        raise ValueError("Choose a valid risk tolerance.")
    return personal_goal, risk_tolerance


def resolve_ai_choice(provider: str, model: str | None = None) -> tuple[str, str, dict[str, Any]]:
    provider = provider.strip().lower()
    if provider not in AI_PROVIDERS:
        raise ValueError("Choose Gemini or DeepSeek as the AI provider.")
    provider_config = AI_PROVIDERS[provider]
    selected_model = (model or provider_config["default_model"]).strip()
    if selected_model not in provider_config["models"]:
        raise ValueError(f"Choose a valid {provider_config['label']} model.")
    return provider, selected_model, provider_config


def extract_symbol(message: str) -> str | None:
    """Find an intentional stock reference without treating normal words as tickers."""
    lower_message = message.lower()
    for symbol, company in POPULAR_STOCKS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(symbol.lower())}(?![a-z0-9])", lower_message):
            return symbol
        if re.search(rf"(?<![a-z]){re.escape(company.lower())}(?![a-z])", lower_message):
            return symbol

    dollar_symbol = re.search(r"\$([A-Za-z][A-Za-z0-9.-]{0,9})", message)
    if dollar_symbol:
        return normalize_symbol(dollar_symbol.group(1))

    ignored_words = {"A", "I", "API", "ETF", "RSI", "SMA", "USD", "HELP", "STOCK"}
    matches = SYMBOL_IN_MESSAGE.findall(message)
    return next((item for item in matches if item not in ignored_words), None)


def load_local_env() -> None:
    """Load simple KEY=VALUE entries without adding python-dotenv."""
    project_dir = Path(__file__).parent
    env_paths = (
        project_dir / ".env.local",
        project_dir / ".env",
        project_dir.parent / ".env",
    )
    for env_path in env_paths:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


def alpaca_credentials() -> tuple[str, str]:
    load_local_env()
    api_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID", "")
    secret_key = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise RuntimeError(
            "Alpaca credentials are missing. Set ALPACA_API_KEY and "
            "ALPACA_SECRET_KEY in your environment or the project .env file."
        )
    return api_key, secret_key


def alpaca_get(path: str, params: dict[str, str]) -> dict[str, Any]:
    api_key, secret_key = alpaca_credentials()
    url = f"{ALPACA_DATA_URL.format(symbol=path)}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
            "User-Agent": "SimpleStockDemo/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
            detail = error_payload.get("message", f"HTTP {exc.code}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = f"HTTP {exc.code}"
        if exc.code == 401:
            raise RuntimeError("The Alpaca credentials are invalid. Check the project .env file.") from exc
        if exc.code == 403:
            raise RuntimeError("This Alpaca account cannot access the selected feed. The demo uses the free IEX feed.") from exc
        if exc.code == 404:
            raise ValueError("Alpaca could not find that stock.") from exc
        raise RuntimeError(f"Alpaca returned an error: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Could not reach Alpaca. Check your connection and try again.") from exc


def recommendation_decision(
    stock: dict[str, Any],
    personal_goal: str,
    risk_tolerance: str,
) -> tuple[str, str]:
    """Apply the same visible teaching policy before asking the language model."""
    advice = stock["advice"]
    if personal_goal == "income":
        return "WAIT", "The available data does not include dividends or cash distributions, so it cannot test an income goal."
    if personal_goal == "capital_preservation" or risk_tolerance == "low":
        if stock["volatility"] >= 0.20 or advice["score"] <= 0:
            return "AVOID", "A single stock with this recent volatility does not fit the selected defensive profile."
        return "WAIT", "The price signal is positive, but price history alone is too narrow for a capital-preservation decision."
    if advice["score"] >= 2:
        return "CONSIDER", "The recent trend is positive and the selected profile accepts the observed price risk."
    if advice["score"] <= -2:
        return "AVOID", "The recent trend is weak, so the stock does not currently fit the selected growth goal."
    return "WAIT", "The indicators are mixed and do not offer a clear profile match."


def ask_llm(
    message: str,
    stock: dict[str, Any],
    personal_goal: str,
    risk_tolerance: str,
    history: list[dict[str, str]] | None = None,
    provider: str = DEFAULT_AI_PROVIDER,
    model: str | None = None,
) -> str:
    """Ask an OpenAI-compatible model using only the supplied Alpaca snapshot."""
    load_local_env()
    provider, model, provider_config = resolve_ai_choice(provider, model)
    api_key_env = provider_config["api_key_env"]
    api_key = os.getenv(api_key_env, "")
    if not api_key:
        raise RuntimeError(f"{api_key_env} is missing from the project .env file.")

    base_url = provider_config["base_url"].rstrip("/")
    safe_history = []
    for item in (history or [])[-6:]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            safe_history.append({"role": role, "content": content[:1500]})

    market_context = {
        "symbol": stock["symbol"],
        "company": stock["name"],
        "price": stock["price"],
        "currency": stock["currency"],
        "change_from_previous_close": stock["change_pct"],
        "sma_5": stock["sma5"],
        "sma_20": stock["sma20"],
        "return_20_trading_days": stock["return_20d"],
        "annualized_volatility_estimate": stock["volatility"],
        "rule_signal": stock["advice"]["label"],
        "rule_signal_reasons": stock["advice"]["reasons"],
        "market_data_time": stock["updated_at"],
        "market_data_source": stock["data_source"],
    }
    investor_profile = {
        "personal_goal": PERSONAL_GOALS[personal_goal],
        "stated_risk_tolerance": RISK_LEVELS[risk_tolerance],
    }
    required_decision, policy_reason = recommendation_decision(stock, personal_goal, risk_tolerance)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a beginner-friendly US stock teaching assistant. Answer in clear, natural English. "
                "Use only the market data supplied in the latest user message; do not invent news, company "
                "fundamentals, forecasts, or real-time facts. Explain your reasoning and uncertainty in two to "
                "five short sentences and stay under 100 words. Do not use markdown headings or lists. You may "
                "give a profile-based educational recommendation, but never promise returns or provide order "
                "quantities and execution instructions. When the user asks for a recommendation, begin with "
                "exactly one of: 'Recommendation: CONSIDER.', 'Recommendation: WAIT.', or "
                "'Recommendation: AVOID.' Then explain how the stock fits the stated goal and risk tolerance. "
                "The latest user message includes a required_recommendation produced by the demo's transparent "
                "teaching policy. Use that exact label and do not replace it with a softer or stronger label. "
                "Treat the two profile selections as user-provided, not as a complete suitability assessment. "
                "If the supplied data cannot support the requested judgment, recommend WAIT and name the missing data. "
                "For an income goal, always recommend WAIT because the supplied data has no dividend or distribution information. "
                "For a capital-preservation goal, do not recommend CONSIDER because short-term single-stock price data cannot establish capital safety."
            ),
        },
        *safe_history,
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": message,
                    "selected_investor_profile": investor_profile,
                    "alpaca_market_data": market_context,
                    "required_recommendation": required_decision,
                    "teaching_policy_reason": policy_reason,
                },
                ensure_ascii=False,
            ),
        },
    ]
    request_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 250,
        "stream": False,
    }
    if provider == "deepseek":
        request_payload["thinking"] = {"type": "disabled"}
    body = json.dumps(request_payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SimpleStockDemo/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        reply = str(payload["choices"][0]["message"]["content"]).strip()
        if not reply:
            raise RuntimeError("The language model returned an empty answer.")
        recommendation_words = ("recommend", "should i", "buy", "consider", "suitable", "fit my")
        if any(word in message.lower() for word in recommendation_words):
            required_prefix = f"Recommendation: {required_decision}."
            if not reply.startswith(required_prefix):
                raise RuntimeError("The language model did not follow the teaching policy recommendation.")
        return reply
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
            if isinstance(error_payload, list) and error_payload:
                error_payload = error_payload[0]
            error = error_payload.get("error", {}) if isinstance(error_payload, dict) else {}
            detail = error.get("message") if isinstance(error, dict) else str(error)
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = None
        raise RuntimeError(detail or f"The language model returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("The language model is temporarily unavailable.") from exc


def fetch_stock(symbol: str) -> dict[str, Any]:
    """Retrieve recent daily bars and derive a few beginner-friendly metrics."""
    symbol = normalize_symbol(symbol)
    encoded_symbol = urllib.parse.quote(symbol)
    start = (datetime.now(timezone.utc) - timedelta(days=190)).date().isoformat()
    bars_payload = alpaca_get(
        f"{encoded_symbol}/bars",
        {
            "timeframe": "1Day",
            "start": start,
            "limit": "1000",
            "adjustment": "raw",
            "feed": "iex",
            "sort": "asc",
        },
    )
    snapshot = alpaca_get(f"{encoded_symbol}/snapshot", {"feed": "iex"})
    bars = bars_payload.get("bars") or []
    closes = [float(bar["c"]) for bar in bars if bar.get("c") is not None]
    if len(closes) < 21:
        raise RuntimeError(f"{symbol} does not have enough recent history for this demo.")

    latest_trade = snapshot.get("latestTrade") or {}
    daily_bar = snapshot.get("dailyBar") or {}
    previous_daily_bar = snapshot.get("prevDailyBar") or {}
    price = float(latest_trade.get("p") or daily_bar.get("c") or closes[-1])
    previous_close = float(previous_daily_bar.get("c") or closes[-2])
    change = price - previous_close
    change_pct = change / previous_close if previous_close else 0.0
    sma5 = moving_average(closes, 5)
    sma20 = moving_average(closes, 20)
    return_20d = price / closes[-21] - 1
    daily_returns = [current / previous - 1 for previous, current in zip(closes[-21:-1], closes[-20:]) if previous]
    volatility = statistics.stdev(daily_returns) * math.sqrt(252) if len(daily_returns) > 1 else 0.0

    market_time = latest_trade.get("t") or daily_bar.get("t")
    try:
        updated_at = datetime.fromisoformat(str(market_time).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        updated_at = "Unknown"

    stock = {
        "symbol": bars_payload.get("symbol") or symbol,
        "name": POPULAR_STOCKS.get(symbol, symbol),
        "currency": "USD",
        "exchange": "IEX",
        "price": round(price, 2),
        "previous_close": round(previous_close, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 4),
        "sma5": round(sma5, 2),
        "sma20": round(sma20, 2),
        "return_20d": round(return_20d, 4),
        "volatility": round(volatility, 4),
        "updated_at": updated_at,
        "data_source": "Alpaca Market Data API (IEX)",
    }
    stock["advice"] = build_advice(stock)
    return stock


def build_advice(stock: dict[str, Any]) -> dict[str, Any]:
    """Create an explainable teaching signal, not personalized financial advice."""
    score = 0
    reasons: list[str] = []

    if stock["price"] >= stock["sma20"]:
        score += 1
        reasons.append("The price is above its 20-day average")
    else:
        score -= 1
        reasons.append("The price is below its 20-day average")

    if stock["sma5"] >= stock["sma20"]:
        score += 1
        reasons.append("The 5-day average is above the 20-day average")
    else:
        score -= 1
        reasons.append("The 5-day average is below the 20-day average")

    if stock["return_20d"] > 0.02:
        score += 1
        reasons.append("The stock gained more than 2% over 20 trading days")
    elif stock["return_20d"] < -0.02:
        score -= 1
        reasons.append("The stock lost more than 2% over 20 trading days")
    else:
        reasons.append("The price changed little over 20 trading days")

    if score >= 2:
        label = "Bullish watch"
        action = "The short-term trend is positive. A beginner could watch it or consider a small, gradual position instead of chasing a sharp rise."
        tone = "positive"
    elif score <= -2:
        label = "Cautious"
        action = "The short-term trend is weak. It may be better to wait for the price to stabilize before considering a new position."
        tone = "negative"
    else:
        label = "Neutral"
        action = "The signals do not agree. Waiting for a clearer trend may be more sensible."
        tone = "neutral"

    return {
        "label": label,
        "action": action,
        "score": score,
        "tone": tone,
        "reasons": reasons,
        "disclaimer": "This is a teaching example based on historical prices, not personalized financial advice.",
    }


def rule_based_reply(
    message: str,
    stock: dict[str, Any],
    personal_goal: str,
    risk_tolerance: str,
) -> str:
    symbol = stock["symbol"]
    advice = stock["advice"]
    lower_message = message.lower()
    asks_for_recommendation = any(
        word in lower_message
        for word in ("recommend", "should i", "buy", "consider", "suitable", "fit my")
    )
    if asks_for_recommendation:
        decision, reason = recommendation_decision(stock, personal_goal, risk_tolerance)
        return (
            f"Recommendation: {decision}. {reason} This is a limited teaching judgment based on the selected "
            f"goal ({PERSONAL_GOALS[personal_goal]}) and risk tolerance ({RISK_LEVELS[risk_tolerance]})."
        )
    if any(word in lower_message for word in ("risk", "volatile", "volatility", "safe")):
        risk_level = "high" if stock["volatility"] >= 0.35 else "moderate" if stock["volatility"] >= 0.20 else "relatively low"
        return (
            f"{symbol}'s annualized volatility, estimated from the last 20 trading days, is "
            f"about {stock['volatility']:.1%}. This demo classifies that as {risk_level} volatility. "
            "It measures recent price movement, not the largest possible future loss."
        )
    if any(word in lower_message for word in ("average", "sma", "why", "reason", "explain")):
        return (
            f"I use three simple signals: the current price ({stock['price']:.2f}), the 5-day average "
            f"({stock['sma5']:.2f}), and the 20-day average ({stock['sma20']:.2f}). I also check the "
            f"20-day return ({stock['return_20d']:+.1%}). Together, they produce a {advice['label'].lower()} signal."
        )
    return (
        f"{symbol} is trading at {stock['price']:.2f} {stock['currency']}, "
        f"{stock['change_pct']:+.2%} from the previous close. The simple signal is "
        f"{advice['label'].lower()}. {advice['action']}"
    )


def answer_chat(
    message: str,
    current_symbol: str = DEFAULT_SYMBOL,
    personal_goal: str = DEFAULT_GOAL,
    risk_tolerance: str = DEFAULT_RISK,
    history: list[dict[str, str]] | None = None,
    provider: str = DEFAULT_AI_PROVIDER,
    model: str | None = None,
) -> dict[str, Any]:
    message = message.strip()
    if not message:
        raise ValueError("Enter a question.")
    personal_goal, risk_tolerance = validate_profile(personal_goal, risk_tolerance)

    mentioned = extract_symbol(message)
    symbol = normalize_symbol(mentioned or current_symbol or DEFAULT_SYMBOL)
    provider, model, provider_config = resolve_ai_choice(provider, model)
    stock = fetch_stock(symbol)
    advice = stock["advice"]
    try:
        reply = ask_llm(
            message,
            stock,
            personal_goal,
            risk_tolerance,
            history,
            provider,
            model,
        )
        mode = "ai"
    except RuntimeError:
        model_label = provider_config["models"][model]
        reply = f"{model_label} could not answer. Try another model or check its API key. " + rule_based_reply(
            message,
            stock,
            personal_goal,
            risk_tolerance,
        )
        mode = "rules"

    return {
        "reply": reply,
        "stock": stock,
        "disclaimer": (
            "This recommendation uses only your two selections and recent price data. "
            "It is an educational demo, not a complete suitability assessment or professional financial advice."
        ),
        "mode": mode,
        "ai": {
            "provider": provider_config["label"],
            "model": provider_config["models"][model],
        },
        "profile": {
            "personal_goal": PERSONAL_GOALS[personal_goal],
            "risk_tolerance": RISK_LEVELS[risk_tolerance],
        },
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stock Starter</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17211b;
      --muted: #66706a;
      --line: #dce4de;
      --paper: #ffffff;
      --canvas: #f4f7f4;
      --green: #146c43;
      --green-soft: #e5f4eb;
      --red: #a23b35;
      --red-soft: #fbe9e7;
      --amber: #815d13;
      --amber-soft: #fff3d6;
      --shadow: 0 18px 50px rgba(27, 48, 35, .09);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 8%, rgba(84, 160, 112, .12), transparent 28rem),
        var(--canvas);
      font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
    }
    button, input, select { font: inherit; }
    .shell { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 42px 0; }
    header { display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 24px; }
    .eyebrow { color: var(--green); font-weight: 750; font-size: 13px; letter-spacing: .08em; }
    h1 { font-size: clamp(30px, 5vw, 50px); letter-spacing: -.045em; line-height: 1.05; margin: 8px 0 10px; }
    header p { color: var(--muted); margin: 0; max-width: 600px; }
    .source { color: var(--muted); font-size: 12px; white-space: nowrap; }
    .layout { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(320px, .85fr); gap: 18px; }
    .panel { background: rgba(255,255,255,.94); border: 1px solid var(--line); border-radius: 22px; box-shadow: var(--shadow); }
    .market { padding: 24px; }
    .search { display: flex; gap: 10px; margin-bottom: 26px; }
    .quick-stocks { display: flex; flex-wrap: wrap; gap: 8px; margin: -14px 0 26px; }
    .stock-chip { color: #415048; background: #edf2ee; border: 1px solid #d9e2db; padding: 7px 10px; font-size: 12px; font-weight: 700; }
    .stock-chip:hover { color: var(--green); background: var(--green-soft); filter: none; }
    input, select { width: 100%; border: 1px solid #cbd5cd; border-radius: 12px; padding: 12px 14px; color: var(--ink); background: white; outline: none; }
    input:focus, select:focus { border-color: var(--green); box-shadow: 0 0 0 3px rgba(20,108,67,.12); }
    button { border: 0; border-radius: 12px; padding: 12px 18px; color: white; background: var(--green); cursor: pointer; font-weight: 700; white-space: nowrap; }
    button:hover { filter: brightness(.94); }
    button:disabled { cursor: wait; opacity: .65; }
    .stock-head { display: flex; justify-content: space-between; gap: 20px; align-items: start; }
    .symbol { font-size: 14px; color: var(--muted); font-weight: 700; }
    .price { font-size: clamp(38px, 6vw, 58px); line-height: 1; letter-spacing: -.045em; margin: 7px 0 8px; font-variant-numeric: tabular-nums; }
    .change { font-weight: 750; }
    .positive-text { color: var(--green); }
    .negative-text { color: var(--red); }
    .neutral-text { color: var(--amber); }
    .badge { display: inline-block; border-radius: 999px; padding: 8px 12px; font-size: 14px; font-weight: 800; }
    .badge.positive { color: var(--green); background: var(--green-soft); }
    .badge.negative { color: var(--red); background: var(--red-soft); }
    .badge.neutral { color: var(--amber); background: var(--amber-soft); }
    .metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 28px 0 22px; }
    .metric { padding: 15px; background: #f7f9f7; border: 1px solid #e5eae6; border-radius: 14px; }
    .metric span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }
    .metric strong { font-size: 18px; font-variant-numeric: tabular-nums; }
    .advice { padding: 18px; border-radius: 16px; background: #f7f9f7; }
    .advice h2 { margin: 0 0 8px; font-size: 18px; }
    .advice p { margin: 0 0 12px; }
    .reasons { margin: 0; padding-left: 20px; color: #465149; }
    .meta { border-top: 1px solid var(--line); margin-top: 20px; padding-top: 14px; color: var(--muted); font-size: 12px; }
    .chat { min-height: 620px; display: flex; flex-direction: column; overflow: hidden; }
    .chat-title { padding: 20px 20px 14px; border-bottom: 1px solid var(--line); }
    .chat-title h2 { margin: 0; font-size: 18px; }
    .chat-title p { color: var(--muted); font-size: 13px; margin: 3px 0 0; }
    .ai-status { display: inline-block; margin-top: 9px; padding: 4px 8px; border-radius: 999px; color: var(--green); background: var(--green-soft); font-size: 11px; font-weight: 800; }
    .ai-grid { display: grid; grid-template-columns: .8fr 1.2fr; gap: 9px; margin-top: 14px; }
    .ai-note { color: var(--muted); font-size: 11px; margin: 6px 0 0; }
    .profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; margin-top: 14px; }
    .profile-field label { display: block; margin-bottom: 5px; color: var(--muted); font-size: 11px; font-weight: 750; }
    .profile-field select { padding: 9px 10px; font-size: 12px; }
    .recommend-button { width: 100%; margin-top: 9px; padding: 10px 14px; }
    .messages { flex: 1; min-height: 360px; max-height: 500px; overflow: auto; padding: 18px; display: flex; flex-direction: column; gap: 12px; }
    .message { max-width: 88%; padding: 11px 13px; border-radius: 14px; white-space: pre-wrap; }
    .message.bot { align-self: flex-start; background: #eff3f0; border-bottom-left-radius: 4px; }
    .message.user { align-self: flex-end; color: white; background: var(--green); border-bottom-right-radius: 4px; }
    .chat-form { display: flex; gap: 8px; padding: 14px; border-top: 1px solid var(--line); }
    .chat-form button { padding-inline: 15px; }
    .error { color: var(--red); }
    .loading { color: var(--muted); animation: pulse 1.1s infinite alternate; }
    @keyframes pulse { to { opacity: .45; } }
    @media (max-width: 820px) {
      .shell { width: min(100% - 20px, 660px); padding: 24px 0; }
      header { display: block; }
      .source { margin-top: 10px; }
      .layout { grid-template-columns: 1fr; }
      .chat { min-height: 520px; }
    }
    @media (max-width: 500px) {
      .market { padding: 17px; }
      .stock-head { display: block; }
      .badge { margin-top: 14px; }
      .metrics { grid-template-columns: 1fr; }
      .ai-grid { grid-template-columns: 1fr; }
      .profile-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <div class="eyebrow">NO EXTRA PYTHON PACKAGES</div>
        <h1>Stock Starter</h1>
        <p>Enter a US stock symbol to see its price, moving averages, and a simple explanation.</p>
      </div>
      <div class="source">IEX market data · For teaching only</div>
    </header>

    <div class="layout">
      <section class="panel market" aria-label="Stock overview">
        <form class="search" id="search-form">
          <input id="symbol-input" value="AAPL" maxlength="10" autocomplete="off" aria-label="US stock symbol" placeholder="Try AAPL">
          <button id="search-button">View</button>
        </form>
        <div class="quick-stocks" aria-label="Popular stocks">
          <button class="stock-chip" type="button" data-symbol="AAPL">Apple · AAPL</button>
          <button class="stock-chip" type="button" data-symbol="MSFT">Microsoft · MSFT</button>
          <button class="stock-chip" type="button" data-symbol="NVDA">NVIDIA · NVDA</button>
          <button class="stock-chip" type="button" data-symbol="AMZN">Amazon · AMZN</button>
          <button class="stock-chip" type="button" data-symbol="GOOGL">Alphabet · GOOGL</button>
          <button class="stock-chip" type="button" data-symbol="META">Meta · META</button>
          <button class="stock-chip" type="button" data-symbol="TSLA">Tesla · TSLA</button>
        </div>
        <div id="stock-content"><p class="loading">Loading market data…</p></div>
      </section>

      <section class="panel chat" aria-label="Stock chat assistant">
        <div class="chat-title">
          <h2>Get a profile-based recommendation</h2>
          <p>Choose a goal and the level of price risk you can accept.</p>
          <span class="ai-status" id="ai-status">Gemini + live Alpaca context</span>
          <div class="ai-grid">
            <div class="profile-field">
              <label for="ai-provider">AI provider</label>
              <select id="ai-provider">
                <option value="gemini" selected>Gemini</option>
                <option value="deepseek">DeepSeek</option>
              </select>
            </div>
            <div class="profile-field">
              <label for="ai-model">AI model</label>
              <select id="ai-model"></select>
            </div>
          </div>
          <p class="ai-note" id="ai-note"></p>
          <div class="profile-grid">
            <div class="profile-field">
              <label for="personal-goal">Personal goal</label>
              <select id="personal-goal">
                <option value="long_term_growth">Long-term growth (5+ years)</option>
                <option value="short_term_growth">Short-term growth (under 1 year)</option>
                <option value="capital_preservation">Protect capital</option>
                <option value="income">Generate income</option>
              </select>
            </div>
            <div class="profile-field">
              <label for="risk-tolerance">Risk tolerance</label>
              <select id="risk-tolerance">
                <option value="low">Low - avoid large swings</option>
                <option value="moderate" selected>Moderate - accept some volatility</option>
                <option value="high">High - accept large swings</option>
              </select>
            </div>
          </div>
          <button class="recommend-button" id="recommend-button" type="button">Get my recommendation</button>
        </div>
        <div class="messages" id="messages" aria-live="polite">
          <div class="message bot">Choose your goal and risk tolerance, then ask a question or get a direct recommendation for the selected stock.</div>
        </div>
        <form class="chat-form" id="chat-form">
          <input id="chat-input" autocomplete="off" aria-label="Chat message" placeholder="Analyze NVDA">
          <button id="send-button">Send</button>
        </form>
      </section>
    </div>
  </main>

  <script>
    const stockContent = document.querySelector('#stock-content');
    const symbolInput = document.querySelector('#symbol-input');
    const messages = document.querySelector('#messages');
    const personalGoal = document.querySelector('#personal-goal');
    const riskTolerance = document.querySelector('#risk-tolerance');
    const aiProvider = document.querySelector('#ai-provider');
    const aiModel = document.querySelector('#ai-model');
    const aiStatus = document.querySelector('#ai-status');
    const aiNote = document.querySelector('#ai-note');
    const recommendButton = document.querySelector('#recommend-button');
    let currentSymbol = 'AAPL';
    let chatHistory = [];

    const aiOptions = {
      gemini: {
        label: 'Gemini',
        note: 'These Gemini models support free-tier use. Account and rate limits apply.',
        models: [
          ['gemini-3.5-flash-lite', 'Gemini 3.5 Flash-Lite - fastest'],
          ['gemini-3.7-flash', 'Gemini 3.7 Flash'],
          ['gemini-3.8-flash', 'Gemini 3.8 Flash - most capable']
        ]
      },
      deepseek: {
        label: 'DeepSeek',
        note: 'DeepSeek requires a DeepSeek API key and available API credit.',
        models: [['deepseek-v4-flash', 'DeepSeek V4 Flash']]
      }
    };

    const escapeHtml = value => String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
    const percent = value => `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;

    function updateAiModels() {
      const option = aiOptions[aiProvider.value];
      aiModel.innerHTML = option.models.map(([value, label]) =>
        `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`
      ).join('');
      aiStatus.textContent = `${option.label} + live Alpaca context`;
      aiNote.textContent = option.note;
      chatHistory = [];
    }

    function renderStock(stock) {
      currentSymbol = stock.symbol;
      symbolInput.value = stock.symbol;
      const direction = stock.change_pct > 0 ? 'positive-text' : stock.change_pct < 0 ? 'negative-text' : 'neutral-text';
      stockContent.innerHTML = `
        <div class="stock-head">
          <div>
            <div class="symbol">${escapeHtml(stock.name)} · ${escapeHtml(stock.symbol)}</div>
            <div class="price">${stock.price.toFixed(2)}</div>
            <div class="change ${direction}">${stock.change >= 0 ? '+' : ''}${stock.change.toFixed(2)} (${percent(stock.change_pct)}) ${escapeHtml(stock.currency)}</div>
          </div>
          <span class="badge ${escapeHtml(stock.advice.tone)}">${escapeHtml(stock.advice.label)}</span>
        </div>
        <div class="metrics">
          <div class="metric"><span>5-day average</span><strong>${stock.sma5.toFixed(2)}</strong></div>
          <div class="metric"><span>20-day average</span><strong>${stock.sma20.toFixed(2)}</strong></div>
          <div class="metric"><span>20-day return</span><strong>${percent(stock.return_20d)}</strong></div>
        </div>
        <div class="advice">
          <h2>What it means</h2>
          <p>${escapeHtml(stock.advice.action)}</p>
          <ul class="reasons">${stock.advice.reasons.map(reason => `<li>${escapeHtml(reason)}</li>`).join('')}</ul>
        </div>
        <div class="meta">${escapeHtml(stock.advice.disclaimer)}<br>Updated: ${escapeHtml(stock.updated_at)} · Source: ${escapeHtml(stock.data_source)}</div>`;
    }

    function showError(error) {
      stockContent.innerHTML = `<p class="error">${escapeHtml(error.message || error)}</p>`;
    }

    async function loadStock(symbol) {
      stockContent.innerHTML = '<p class="loading">Loading market data…</p>';
      const response = await fetch(`/api/stock?symbol=${encodeURIComponent(symbol)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not load the stock');
      renderStock(data);
      return data;
    }

    function addMessage(text, role) {
      const node = document.createElement('div');
      node.className = `message ${role}`;
      node.textContent = text;
      messages.appendChild(node);
      messages.scrollTop = messages.scrollHeight;
      return node;
    }

    document.querySelector('#search-form').addEventListener('submit', async event => {
      event.preventDefault();
      const button = document.querySelector('#search-button');
      button.disabled = true;
      try { await loadStock(symbolInput.value); } catch (error) { showError(error); }
      finally { button.disabled = false; }
    });

    document.querySelectorAll('.stock-chip').forEach(button => {
      button.addEventListener('click', async () => {
        symbolInput.value = button.dataset.symbol;
        try { await loadStock(button.dataset.symbol); } catch (error) { showError(error); }
      });
    });

    [personalGoal, riskTolerance, aiModel].forEach(select => {
      select.addEventListener('change', () => { chatHistory = []; });
    });
    aiProvider.addEventListener('change', updateAiModels);

    recommendButton.addEventListener('click', () => {
      const input = document.querySelector('#chat-input');
      input.value = 'Based on my selected goal and risk tolerance, what do you recommend for this stock?';
      document.querySelector('#chat-form').requestSubmit();
    });

    document.querySelector('#chat-form').addEventListener('submit', async event => {
      event.preventDefault();
      const input = document.querySelector('#chat-input');
      const button = document.querySelector('#send-button');
      const message = input.value.trim();
      if (!message) return;
      addMessage(message, 'user');
      input.value = '';
      button.disabled = true;
      recommendButton.disabled = true;
      const waiting = addMessage('Checking the latest market data…', 'bot');
      try {
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            message,
            symbol: currentSymbol,
            personal_goal: personalGoal.value,
            risk_tolerance: riskTolerance.value,
            ai_provider: aiProvider.value,
            ai_model: aiModel.value,
            history: chatHistory
          })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Could not answer');
        waiting.textContent = `${data.reply}\n\nAI: ${data.ai.model}\n${data.disclaimer}`;
        chatHistory.push({role: 'user', content: message}, {role: 'assistant', content: data.reply});
        chatHistory = chatHistory.slice(-6);
        renderStock(data.stock);
      } catch (error) {
        waiting.textContent = error.message || 'I could not answer that right now.';
        waiting.classList.add('error');
      } finally { button.disabled = false; recommendButton.disabled = false; input.focus(); }
    });

    updateAiModels();
    loadStock(currentSymbol).catch(showError);
  </script>
</body>
</html>
"""


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self.send_payload(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
            return
        if parsed.path == "/api/stock":
            symbol = urllib.parse.parse_qs(parsed.query).get("symbol", [DEFAULT_SYMBOL])[0]
            self.run_json(lambda: fetch_stock(symbol))
            return
        self.send_json(404, {"error": "Page not found."})

    def do_POST(self) -> None:
        if self.path != "/api/chat":
            self.send_json(404, {"error": "API endpoint not found."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > 20_000:
                raise ValueError("The message is too long.")
            payload = json.loads(self.rfile.read(content_length) or b"{}")
            history = payload.get("history", [])
            if not isinstance(history, list):
                history = []
            self.run_json(
                lambda: answer_chat(
                    str(payload.get("message", "")),
                    str(payload.get("symbol", DEFAULT_SYMBOL)),
                    str(payload.get("personal_goal", DEFAULT_GOAL)),
                    str(payload.get("risk_tolerance", DEFAULT_RISK)),
                    history,
                    str(payload.get("ai_provider", DEFAULT_AI_PROVIDER)),
                    str(payload.get("ai_model", "")) or None,
                )
            )
        except json.JSONDecodeError:
            self.send_json(400, {"error": "The request body is not valid JSON."})

    def run_json(self, operation: Any) -> None:
        try:
            self.send_json(200, operation())
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self.send_json(503, {"error": str(exc)})
        except Exception:
            self.send_json(500, {"error": "The demo hit an unexpected error. Try again shortly."})

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_payload(status, "application/json; charset=utf-8", body)

    def send_payload(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def self_test() -> None:
    sample = {
        "price": 110.0,
        "sma5": 108.0,
        "sma20": 100.0,
        "return_20d": 0.08,
    }
    advice = build_advice(sample)
    assert advice["label"] == "Bullish watch"
    assert advice["score"] == 3
    sample["symbol"] = "TEST"
    sample["volatility"] = 0.30
    sample["advice"] = advice
    assert rule_based_reply("What do you recommend?", sample, "income", "moderate").startswith("Recommendation: WAIT.")
    assert rule_based_reply("Should I buy?", sample, "capital_preservation", "low").startswith("Recommendation: AVOID.")
    weak_sample = {**sample, "advice": {**advice, "score": -3}}
    assert recommendation_decision(weak_sample, "long_term_growth", "moderate")[0] == "AVOID"
    assert validate_profile("long_term_growth", "high") == ("long_term_growth", "high")
    assert resolve_ai_choice("gemini", "gemini-3.7-flash")[1] == "gemini-3.7-flash"
    assert resolve_ai_choice("deepseek")[1] == "deepseek-v4-flash"
    try:
        resolve_ai_choice("gemini", "made-up-model")
    except ValueError:
        pass
    else:
        raise AssertionError("An unsupported AI model was accepted")
    assert normalize_symbol(" brk-b ") == "BRK-B"
    assert extract_symbol("How risky is MSFT?") == "MSFT"
    assert extract_symbol("Would this stock suit me?") is None
    assert extract_symbol("Tell me about Apple") == "AAPL"
    assert extract_symbol("Analyze $amd") == "AMD"
    try:
        normalize_symbol("AAPL<script>")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid symbol was accepted")
    print("Self-test passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the dependency-free stock chat demo")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    server = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Stock demo is running at {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open_new(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDemo stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
