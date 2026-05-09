"""
Telegram alert dispatcher. Optional — disabled by default.

Configure via env: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID. If either is
missing, alerts no-op (printed to stdout instead).
"""

import logging
import os
from typing import Optional

import requests


log = logging.getLogger("orchestrator.alerts")


class TelegramAlerter:
    def __init__(self, enabled: bool = False,
                 bot_token_env: str = "TELEGRAM_BOT_TOKEN",
                 chat_id_env: str = "TELEGRAM_CHAT_ID"):
        self._enabled = enabled
        self._token = os.environ.get(bot_token_env)
        self._chat_id = os.environ.get(chat_id_env)
        if enabled and (not self._token or not self._chat_id):
            log.warning("Telegram alerts enabled but creds missing — falling back to stdout")
            self._enabled = False

    def alert_entry(self, signal_meta: dict, primary_id: str):
        self._send(f"🟢 Entry · {signal_meta.get('strategy')} · "
                   f"{signal_meta.get('direction')} {signal_meta.get('asset')} · "
                   f"order={primary_id}")

    def alert_close(self, strategy: str, asset: str, pnl_pct: float):
        emoji = "🟦" if pnl_pct >= 0 else "🟥"
        self._send(f"{emoji} Close · {strategy} {asset} · pnl={pnl_pct:+.2f}%")

    def alert_error(self, where: str, err: str):
        self._send(f"⚠️ Error in {where}: {err}")

    def alert_kill_switch(self, reason: str):
        self._send(f"🛑 KILL SWITCH ACTIVATED · reason: {reason}")

    def _send(self, text: str):
        if not self._enabled:
            print(f"[ALERT] {text}")
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
                timeout=5,
            )
        except Exception as e:
            log.error("Telegram send failed: %s", e)
