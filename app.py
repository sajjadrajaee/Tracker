"""Streamlit UI for the Binance portfolio dashboard."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd
import plotly.express as px
import streamlit as st

from calculations import (
    aggregate_positions,
    build_portfolio_rows,
    evaluate_alerts,
    split_symbol,
)
from config import AppConfig, ensure_strategies_file
from data_fetch import (
    BinanceClient,
    load_strategies,
    save_strategies,
    send_telegram_alert,
)

st.set_page_config(page_title="Binance Portfolio Dashboard", layout="wide")


def guess_symbol(asset: str, price_map: Dict[str, float], preferred_quote: str) -> str | None:
    asset = asset.upper()
    quotes = [preferred_quote, "USDT", "BUSD", "FDUSD", "TUSD", "BTC", "BNB", "ETH"]
    for quote in quotes:
        symbol = f"{asset}{quote}"
        if symbol in price_map:
            return symbol
    for symbol in price_map:
        if symbol.startswith(asset):
            return symbol
    return None


def format_currency(value: float) -> str:
    if abs(value) >= 1:
        return f"${value:,.2f}"
    return f"${value:,.6f}"


def load_portfolio_data(client: BinanceClient):
    spot = client.get_spot_balances()
    staking = client.get_staking_positions()
    auto = client.get_auto_invest_positions()
    dual = client.get_dual_invest_positions()
    prices = client.get_symbol_prices()
    return spot, staking, auto, dual, prices


def main() -> None:
    st.title("Binance Portfolio Dashboard")
    st.caption("Live view of balances, cost basis, and strategy alerts.")

    try:
        config = AppConfig.load()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    ensure_strategies_file(config.strategies_file)
    client = BinanceClient(config.binance_api_key, config.binance_api_secret)

    with st.sidebar:
        st.header("Controls")
        quote_symbol = st.selectbox("Preferred quote asset", ["USDT", "BUSD", "FDUSD", "TUSD", "BTC", "BNB"], index=0)
        if st.button("Refresh data"):
            st.experimental_rerun()

    try:
        with st.spinner("Fetching balances and prices from Binance..."):
            spot, staking, auto, dual, price_map = load_portfolio_data(client)
    except Exception as exc:  # noqa: BLE001 - show user-friendly error
        st.error(f"Unable to fetch data from Binance: {exc}")
        st.stop()

    holdings = aggregate_positions(spot, staking, auto, dual)
    if not holdings:
        st.info("No holdings detected for the connected Binance account.")
        st.stop()

    symbols: Dict[str, str] = {}
    for asset in holdings:
        symbol = guess_symbol(asset, price_map, quote_symbol)
        if symbol:
            symbols[asset] = symbol
    if not symbols:
        st.warning("Unable to match holdings with Binance tickers. Please ensure you hold markets quoted in your preferred quote asset.")
        st.stop()

    trade_lookup: Dict[str, List[dict]] = {}
    for asset, symbol in symbols.items():
        try:
            trades = client.get_symbol_trades(symbol)
        except Exception:
            trades = []
        try:
            base, quote = split_symbol(symbol)
        except ValueError:
            base, quote = asset, quote_symbol
        for trade in trades:
            trade["baseAsset"] = base
            trade["quoteAsset"] = quote
        trade_lookup[symbol] = trades

    rows, summary = build_portfolio_rows(holdings, price_map, trade_lookup, quote_symbol=quote_symbol)
    df = pd.DataFrame([row.__dict__ for row in rows])

    cols = st.columns(4)
    cols[0].metric("Total Invested", format_currency(summary.total_invested))
    cols[1].metric("Total Value", format_currency(summary.total_value))
    cols[2].metric("Unrealized P&L", format_currency(summary.net_unrealized))
    cols[3].metric("Realized P&L", format_currency(summary.realized_pnl))

    st.subheader("Portfolio Overview")
    if df.empty:
        st.info("No portfolio data to display.")
    else:
        df_display = df.copy()
        df_display.rename(columns={
            "asset": "Asset",
            "quantity": "Quantity",
            "average_buy_price": "Avg. Buy",
            "invested": "Invested",
            "current_price": "Price",
            "current_value": "Value",
            "unrealized_pnl": "Unrealized P&L",
            "roi_pct": "ROI %",
            "realized_pnl": "Realized P&L",
        }, inplace=True)
        formatters = {
            "Quantity": "{:.6f}".format,
            "Avg. Buy": "{:.4f}".format,
            "Invested": "${:,.2f}".format,
            "Price": "{:.4f}".format,
            "Value": "${:,.2f}".format,
            "Unrealized P&L": "${:,.2f}".format,
            "Realized P&L": "${:,.2f}".format,
            "ROI %": "{:.2f}%".format,
        }

        def pnl_color(val):
            color = "green" if val > 0 else "red" if val < 0 else "black"
            return f"color: {color}"

        styled = df_display.style.format(formatters).applymap(pnl_color, subset=["Unrealized P&L", "ROI %", "Realized P&L"])
        st.dataframe(styled, use_container_width=True)

        csv_bytes = df_display.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download CSV",
            data=csv_bytes,
            file_name="binance_portfolio.csv",
            mime="text/csv",
        )

    st.subheader("Allocation")
    if not df.empty:
        fig = px.pie(df, names="asset", values="current_value", hole=0.3)
        st.plotly_chart(fig, use_container_width=True)

    if rows:
        best = max(rows, key=lambda r: r.roi_pct)
        worst = min(rows, key=lambda r: r.roi_pct)
        gain_col, loss_col = st.columns(2)
        gain_col.success(f"Top Gainer: {best.asset} ({best.roi_pct:.2f}% | {format_currency(best.unrealized_pnl)})")
        loss_col.error(f"Top Loser: {worst.asset} ({worst.roi_pct:.2f}% | {format_currency(worst.unrealized_pnl)})")

    strategies = load_strategies(config.strategies_file)
    st.subheader("Trading Strategy Levels")
    if not strategies:
        st.caption("Add strategy rows below to start tracking buy/sell targets.")
    strategy_df = pd.DataFrame.from_dict(strategies, orient="index").fillna(0.0)
    strategy_df.index.name = "Asset"
    edited = st.data_editor(
        strategy_df,
        use_container_width=True,
        num_rows="dynamic",
        key="strategy_editor",
    )
    strategies_payload: Dict[str, dict] = {}
    if not edited.empty:
        for asset, row in edited.iterrows():
            if asset is None or asset == "":
                continue
            asset_key = str(asset).upper()
            strategies_payload[asset_key] = {
                "low_buy_1": float(row.get("low_buy_1", 0) or 0),
                "low_buy_2": float(row.get("low_buy_2", 0) or 0),
                "high_sell_1": float(row.get("high_sell_1", 0) or 0),
                "high_sell_2": float(row.get("high_sell_2", 0) or 0),
            }
    if st.button("Save Strategies"):
        save_strategies(config.strategies_file, strategies_payload)
        st.success("Strategies saved.")

    alerts = evaluate_alerts(rows, strategies_payload or strategies)
    if alerts:
        st.warning("\n".join(alerts))
        if "sent_alerts" not in st.session_state:
            st.session_state.sent_alerts = set()
        for message in alerts:
            if message in st.session_state.sent_alerts:
                continue
            send_telegram_alert(config.telegram_bot_token, config.telegram_chat_id, message)
            st.session_state.sent_alerts.add(message)
    else:
        st.caption("No strategy alerts triggered.")

    st.sidebar.markdown("---")
    st.sidebar.caption("Export, update strategies, or adjust quote asset to tailor the dashboard.")


if __name__ == "__main__":
    main()
