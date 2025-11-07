"""Application configuration utilities for Binance portfolio dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import json
import os

DEFAULT_STRATEGIES_FILE = Path("strategies.json")


def _load_env_file(env_path: Path) -> dict[str, str]:
    """Minimal .env reader to avoid extra dependencies."""
    if not env_path.exists():
        return {}
    env: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


@dataclass
class AppConfig:
    """Holds secrets and file locations used across the app."""

    binance_api_key: str
    binance_api_secret: str
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    strategies_file: Path = DEFAULT_STRATEGIES_FILE

    @classmethod
    def load(cls, strategies_file: Path | None = None) -> "AppConfig":
        env = {**os.environ}
        env.update(_load_env_file(Path(".env")))

        api_key = env.get("BINANCE_API_KEY", "").strip()
        api_secret = env.get("BINANCE_API_SECRET", "").strip()
        telegram_token = env.get("TELEGRAM_BOT_TOKEN") or None
        telegram_chat_id = env.get("TELEGRAM_CHAT_ID") or None

        if not api_key or not api_secret:
            raise RuntimeError(
                "Missing Binance API credentials. Set BINANCE_API_KEY and BINANCE_API_SECRET "
                "environment variables or .env entries."
            )

        strategies_path = Path(strategies_file) if strategies_file else DEFAULT_STRATEGIES_FILE
        return cls(
            binance_api_key=api_key,
            binance_api_secret=api_secret,
            telegram_bot_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
            strategies_file=strategies_path,
        )


def ensure_strategies_file(path: Path) -> None:
    """Create a default strategies file if it does not exist."""
    if path.exists():
        return
    default_payload = {
        "BTC": {
            "low_buy_1": 0.0,
            "low_buy_2": 0.0,
            "high_sell_1": 0.0,
            "high_sell_2": 0.0,
        }
    }
    path.write_text(json.dumps(default_payload, indent=2))
