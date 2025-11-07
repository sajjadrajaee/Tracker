"""Binance API interactions and persistence helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

BINANCE_API_BASE = "https://api.binance.com"
TIMEOUT_SECONDS = 15


class BinanceClient:
    """Thin Binance REST client with the endpoints required for the dashboard."""

    def __init__(self, api_key: str, api_secret: str, base_url: str = BINANCE_API_BASE):
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.base_url = base_url.rstrip("/")

    # ---- HTTP helpers -------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key}

    def _sign(self, query: str) -> str:
        return hmac.new(self.api_secret, query.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: Optional[dict] = None, signed: bool = False):
        params = params or {}
        query = urlencode(params, doseq=True)
        url = f"{self.base_url}{path}"
        if signed:
            params_with_ts = {**params, "timestamp": int(time.time() * 1000)}
            query = urlencode(params_with_ts, doseq=True)
            signature = self._sign(query)
            query = f"{query}&signature={signature}"
        if query:
            url = f"{url}?{query}"
        response = requests.request(method, url, headers=self._headers() if signed else None, timeout=TIMEOUT_SECONDS)
        if response.status_code == 401:
            raise RuntimeError("Binance API rejected credentials. Please verify your API key/secret and IP whitelist.")
        if not response.ok:
            raise RuntimeError(f"Binance API error {response.status_code}: {response.text}")
        return response.json()

    # ---- Public endpoints ---------------------------------------------
    def get_symbol_prices(self) -> Dict[str, float]:
        data = self._request("GET", "/api/v3/ticker/price")
        return {item["symbol"]: float(item["price"]) for item in data}

    # ---- Private endpoints --------------------------------------------
    def get_spot_balances(self) -> List[dict]:
        payload = self._request("GET", "/sapi/v1/capital/config/getall", signed=True)
        balances: List[dict] = []
        for entry in payload:
            total = float(entry.get("free", 0)) + float(entry.get("locked", 0))
            if total <= 0:
                continue
            balances.append({
                "asset": entry["coin"],
                "free": float(entry.get("free", 0)),
                "locked": float(entry.get("locked", 0)),
            })
        return balances

    def get_staking_positions(self) -> List[dict]:
        positions: List[dict] = []
        for product in ("STAKING", "LENDING", "LENDING_DAILY", "LENDING_FIXED"):
            try:
                data = self._request(
                    "POST",
                    "/sapi/v1/staking/productPosition",
                    params={"product": product},
                    signed=True,
                )
            except Exception as exc:  # noqa: BLE001 - degrade gracefully
                logger.debug("Unable to fetch %s positions: %s", product, exc)
                continue
            for item in data or []:
                amount = float(item.get("amount", 0))
                if amount <= 0:
                    continue
                positions.append({
                    "asset": item.get("asset"),
                    "amount": amount,
                    "product": product,
                })
        return positions

    def get_auto_invest_positions(self) -> List[dict]:
        try:
            data = self._request("GET", "/sapi/v1/lending/auto-invest/positions", signed=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Auto-invest positions unavailable: %s", exc)
            return []
        positions: List[dict] = []
        for item in data.get("positions", []):
            asset = item.get("targetAsset")
            amount = float(item.get("totalAmount", 0))
            if amount > 0:
                positions.append({"asset": asset, "amount": amount, "product": "AUTO_INVEST"})
        return positions

    def get_dual_invest_positions(self) -> List[dict]:
        try:
            data = self._request("GET", "/sapi/v1/lending/dual/daily/product/list", signed=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Dual investment info unavailable: %s", exc)
            return []
        positions: List[dict] = []
        for item in data:
            asset = item.get("underlying")
            amount = float(item.get("subscriptionAmount", 0))
            if amount > 0:
                positions.append({"asset": asset, "amount": amount, "product": "DUAL_INVEST"})
        return positions

    def get_symbol_trades(self, symbol: str, limit: int = 1000) -> List[dict]:
        return self._request(
            "GET",
            "/api/v3/myTrades",
            params={"symbol": symbol, "limit": limit},
            signed=True,
        )


# ---- Strategy persistence ----------------------------------------------

def load_strategies(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_strategies(path: Path, strategies: Dict[str, dict]) -> None:
    path.write_text(json.dumps(strategies, indent=2, sort_keys=True))


# ---- Alerts -------------------------------------------------------------

def send_telegram_alert(token: Optional[str], chat_id: Optional[str], message: str) -> None:
    if not token or not chat_id:
        logger.info("Telegram credentials missing; skipping alert: %s", message)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    try:
        response = requests.post(url, json=payload, timeout=TIMEOUT_SECONDS)
        if not response.ok:
            logger.warning("Telegram API error %s: %s", response.status_code, response.text)
    except requests.RequestException as exc:
        logger.warning("Unable to send Telegram alert: %s", exc)
