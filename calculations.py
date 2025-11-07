"""Portfolio calculations for the Binance dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


QUOTE_ASSETS = [
    "USDT",
    "BUSD",
    "FDUSD",
    "TUSD",
    "USDC",
    "BTC",
    "BNB",
    "ETH",
    "TRY",
    "EUR",
]


@dataclass
class SymbolPosition:
    asset: str
    quantity: float
    average_buy_price: float
    invested: float
    current_price: float
    current_value: float
    unrealized_pnl: float
    roi_pct: float
    realized_pnl: float


@dataclass
class PortfolioSummary:
    total_invested: float
    total_value: float
    net_unrealized: float
    realized_pnl: float


def split_symbol(symbol: str) -> Tuple[str, str]:
    symbol = symbol.upper()
    for quote in QUOTE_ASSETS:
        if symbol.endswith(quote):
            return symbol[: -len(quote)], quote
    raise ValueError(f"Unable to infer base asset for symbol {symbol}")


def aggregate_positions(*sources: Iterable[dict]) -> Dict[str, float]:
    holdings: Dict[str, float] = {}
    for source in sources:
        for entry in source:
            asset = entry.get("asset")
            if not asset:
                continue
            qty = float(entry.get("quantity") or entry.get("free") or entry.get("amount") or 0)
            qty += float(entry.get("locked", 0))
            holdings[asset] = holdings.get(asset, 0.0) + qty
    return {asset: qty for asset, qty in holdings.items() if qty > 0}


def compute_symbol_trade_stats(symbol: str, trades: List[dict]) -> Tuple[float, float, float]:
    if not trades:
        return 0.0, 0.0, 0.0
    base_asset, quote_asset = split_symbol(symbol)
    position_qty = 0.0
    position_cost = 0.0
    realized_pnl = 0.0
    for trade in sorted(trades, key=lambda t: t.get("time", 0)):
        qty = float(trade["qty"])
        price = float(trade["price"])
        is_buy = trade.get("isBuyer", True)
        fee_quote = float(trade.get("commission")) if trade.get("commissionAsset") == quote_asset else 0.0
        fee_base = float(trade.get("commission")) if trade.get("commissionAsset") == base_asset else 0.0
        if is_buy:
            effective_qty = qty - fee_base
            cost = (qty * price) + fee_quote
            position_qty += effective_qty
            position_cost += cost
        else:
            sell_qty = min(qty, position_qty)
            if sell_qty <= 0:
                continue
            avg_cost = position_cost / position_qty if position_qty else 0.0
            proceeds = (sell_qty * price) - fee_quote
            realized_pnl += proceeds - (avg_cost * sell_qty)
            position_qty -= sell_qty
            position_cost -= avg_cost * sell_qty
    average_price = position_cost / position_qty if position_qty else 0.0
    return average_price, position_cost, realized_pnl


def build_portfolio_rows(
    holdings: Dict[str, float],
    price_map: Dict[str, float],
    trade_lookup: Dict[str, List[dict]],
    quote_symbol: str = "USDT",
) -> Tuple[List[SymbolPosition], PortfolioSummary]:
    rows: List[SymbolPosition] = []
    total_invested = 0.0
    total_value = 0.0
    realized_total = 0.0

    # Build helper to fetch the proper ticker pair
    def match_symbol(asset: str) -> str | None:
        preferred = f"{asset}{quote_symbol}"
        if preferred in price_map:
            return preferred
        for sym in price_map:
            if sym.startswith(asset):
                return sym
        return None

    for asset, qty in holdings.items():
        symbol = match_symbol(asset)
        if not symbol:
            continue
        current_price = price_map.get(symbol, 0.0)
        average_price, invested, realized_pnl = compute_symbol_trade_stats(symbol, trade_lookup.get(symbol, []))
        if invested == 0 and average_price == 0:
            invested = qty * current_price
        current_value = qty * current_price
        unrealized = current_value - invested
        roi_pct = (unrealized / invested * 100) if invested else 0.0
        rows.append(
            SymbolPosition(
                asset=asset,
                quantity=qty,
                average_buy_price=average_price,
                invested=invested,
                current_price=current_price,
                current_value=current_value,
                unrealized_pnl=unrealized,
                roi_pct=roi_pct,
                realized_pnl=realized_pnl,
            )
        )
        total_invested += invested
        total_value += current_value
        realized_total += realized_pnl

    summary = PortfolioSummary(
        total_invested=total_invested,
        total_value=total_value,
        net_unrealized=total_value - total_invested,
        realized_pnl=realized_total,
    )
    return rows, summary


def evaluate_alerts(rows: List[SymbolPosition], strategies: Dict[str, dict]) -> List[str]:
    alerts: List[str] = []
    for row in rows:
        strat = strategies.get(row.asset.upper())
        if not strat:
            continue
        price = row.current_price
        lb1 = strat.get("low_buy_1")
        lb2 = strat.get("low_buy_2")
        hs1 = strat.get("high_sell_1")
        hs2 = strat.get("high_sell_2")
        if lb1 and price <= lb1:
            alerts.append(f"{row.asset} reached Low Buy 1 at {price:.4f} <= {lb1}")
        if lb2 and price <= lb2:
            alerts.append(f"{row.asset} reached Low Buy 2 at {price:.4f} <= {lb2}")
        if hs1 and price >= hs1:
            alerts.append(f"{row.asset} hit High Sell 1 at {price:.4f} >= {hs1}")
        if hs2 and price >= hs2:
            alerts.append(f"{row.asset} hit High Sell 2 at {price:.4f} >= {hs2}")
    return alerts
