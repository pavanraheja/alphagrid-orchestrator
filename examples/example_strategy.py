"""
Example upstream signal producer. Sends a fake signal to a running orchestrator.

Usage (in two terminals):
    Terminal 1:  python -m orchestrator.main
    Terminal 2:  python examples/example_strategy.py
"""

import json
import sys
import requests


ORCHESTRATOR = "http://localhost:8095"


def send_signal(strategy: str = "example_strategy",
                asset: str = "BTC-PERP",
                direction: str = "long",
                size: float = 0.01,
                sl_pct: float = 1.5,
                tp_pct: float = 3.0):
    payload = {
        "strategy": strategy,
        "asset": asset,
        "direction": direction,
        "size": size,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "metadata": {"source": "example_strategy.py"},
    }
    r = requests.post(f"{ORCHESTRATOR}/signal", json=payload, timeout=5)
    print(f"POST /signal -> {r.status_code}")
    print(json.dumps(r.json(), indent=2))


def show_status():
    r = requests.get(f"{ORCHESTRATOR}/status", timeout=5)
    print("\nGET /status:")
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        show_status()
    else:
        send_signal()
        show_status()
