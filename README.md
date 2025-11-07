# Binance Portfolio Tracker

Streamlit dashboard that connects to the Binance REST API to aggregate spot balances, staking/Earn products, Auto-Invest, and Dual Investment positions. It calculates per-asset cost basis, unrealized and realized P&L, ROI %, and provides editing for custom buy/sell strategy levels with Telegram alerts.

## Project layout

```
.
├── app.py               # Streamlit UI entry-point
├── calculations.py      # Portfolio math utilities
├── config.py            # App configuration + .env handling
├── data_fetch.py        # Binance + Telegram helpers + strategy persistence
├── requirements.txt     # Python dependencies
└── strategies.json      # Sample trading strategy levels
```

## Local setup

1. Create a virtual environment and install requirements:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Provide credentials (environment variables or `.env` file):
   ```
   BINANCE_API_KEY=your_key
   BINANCE_API_SECRET=your_secret
   TELEGRAM_BOT_TOKEN=optional
   TELEGRAM_CHAT_ID=optional
   ```
3. Run Streamlit:
   ```bash
   streamlit run app.py
   ```

## Streamlit Cloud deployment

1. Push this repo to GitHub (e.g. `https://github.com/BryanGonsalves/Binance-Portfolio-Tracker`).
2. Sign in to [share.streamlit.io](https://share.streamlit.io/) and deploy a new app pointing to `app.py` on the main branch.
3. In the Streamlit workspace, open **Settings → Secrets** and add:
   ```toml
   BINANCE_API_KEY = "your_key"
   BINANCE_API_SECRET = "your_secret"
   TELEGRAM_BOT_TOKEN = "optional"
   TELEGRAM_CHAT_ID = "optional"
   ```
4. (Optional) If you want editable strategy defaults at first boot, upload a `strategies.json` file in the repo or edit from the UI and click **Save Strategies**.

Streamlit Cloud automatically runs `pip install -r requirements.txt` and launches `streamlit run app.py` at deploy time.

## Error handling

- Missing API keys or invalid responses show user-friendly messages instead of crashing the app.
- Telegram alerts are skipped gracefully if credentials are absent or the API call fails.

## Exporting data

Use the **Download CSV** button inside the dashboard to export the current view to Excel/Sheets.
