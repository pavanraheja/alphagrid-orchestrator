# alphagrid-orchestrator

A production pattern for safely deploying autonomous decision systems that act on real-world resources.

When a decision system can move money, send messages, allocate compute, or trigger any irreversible side-effect, you need a layer between the decision engine and execution. Otherwise a model bug becomes a wallet bug, a prompt regression becomes a compliance incident, a deploy becomes an outage.

This is the orchestration layer pattern I extracted from AlphaGrid — the production system I built and operate to route signals from autonomous trading systems to live execution.

## Why this exists

Three things happen the moment you put an autonomous system in production:

1. **A small failure becomes an unbounded one.** The decision engine doesn't know its blast radius — it just emits signals. Without a guarded layer, one bad signal can blow through the day's risk budget.
2. **Promotion becomes ad-hoc.** Once you have more than one strategy, the question of "is this one ready for live?" stops having an obvious answer. People start eyeballing it. People are bad at this.
3. **Audits become impossible.** When something does go wrong, you need to know exactly which signal fired, which gate it passed, which gate it failed, and what executed. If that telemetry isn't built in from day one, you don't get to add it after the incident.

This pattern handles all three. It's small (one Flask service, ~300 lines of pattern code), opinionated about safety, and deliberately boring.

## What's in here

```
alphagrid-orchestrator/
├── orchestrator/
│   ├── main.py            Flask app — signal endpoint, kill switch, status
│   ├── risk_guardian.py   Drawdown-kill, loss caps, conflict + duplicate guards
│   ├── promotion.py       Staged-promotion gate (shadow → paper → live)
│   ├── dispatch.py        Two-stage entry; execution adapter interface
│   ├── adapters.py        MockAdapter for demos and tests
│   └── alerts.py          Telegram alert dispatcher
├── examples/
│   └── example_strategy.py  Sample upstream signal producer
├── config/
│   └── example_config.yaml
├── tests/
│   └── test_risk_guardian.py
├── requirements.txt
├── LICENSE                 MIT
└── README.md
```

## The pattern in one diagram

```
  Upstream                    Orchestrator                     Execution
  decision    ──signal──▶    ┌──────────────────────┐    ──▶   adapter
  systems                    │ Risk Guardian         │          (Mock here;
                             │ ─ drawdown-kill       │           Binance,
  (one per                   │ ─ loss caps           │           webhook,
  strategy)                  │ ─ conflict gate       │           wallet,
                             │ ─ duplicate gate      │           etc., in
                             │ ─ kill switch         │           production)
                             │                       │
                             │ Promotion Gate        │
                             │ ─ shadow → paper      │
                             │ ─ paper → live        │
                             │                       │
                             │ Dispatcher            │
                             │ ─ two-stage entry     │
                             │ ─ retry-safe          │
                             └──────────┬────────────┘
                                        │
                             ┌──────────▼────────────┐
                             │ Telegram alerts on    │
                             │ entry / close / error │
                             └───────────────────────┘
```

## Quick start

```bash
git clone https://github.com/pavanraheja/alphagrid-orchestrator
cd alphagrid-orchestrator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the orchestrator (uses MockAdapter — no real execution)
python -m orchestrator.main

# In another terminal: send a sample signal
python examples/example_strategy.py
```

## Configuration

`config/example_config.yaml` has every knob exposed:

```yaml
risk:
  max_drawdown_pct: 15        # account-level circuit breaker
  per_strategy_loss_cap_pct: 5
  conflict_gate: true         # block opposite-direction same-asset trades
  duplicate_gate: true        # block re-entry for same asset+direction+strategy

streams:
  example_strategy:
    enabled: false            # default off — must promote explicitly
    capital: 100
    max_concurrent: 2
    promotion_state: shadow   # shadow | paper | live
    gates:
      min_trades: 15
      min_wr_pct: 50
      min_pf: 1.5

alerts:
  telegram:
    enabled: false
    bot_token_env: TELEGRAM_BOT_TOKEN
    chat_id_env: TELEGRAM_CHAT_ID
```

## Said no to

- **Manual promotion overrides.** Every promotion is gate-driven. If someone wants to skip a gate, they edit the config and the change is logged — there is no command to bypass.
- **Execution adapter coupling.** The orchestrator does not know about Binance, your wallet, or your message queue. It speaks to an `ExecutionAdapter` interface. The reference implementation is `MockAdapter`. Production adapters are out of scope for this repo (and stay private for security).
- **Hidden state.** Risk guardian state, promotion state, and outcome history are stored in JSON on disk after every change. If the process dies, recovery is straightforward.
- **A clever architecture.** This is one Flask service, a handful of small modules, and a few hundred lines of pattern code. The cleverness is in the discipline of what's gated, not in the code.

## What this isn't

- This is **not a trading bot.** It is an orchestration pattern. You can run trading strategies through it, content moderation, deployment automation, robotic control — anywhere autonomous decisions need a guarded path to action.
- This is **not the production version** of AlphaGrid. The production version has more execution adapters, more strategy hooks, and more telemetry. Those stay in a private repo because exposing them publicly is a security risk for the running system.
- This is **not a framework.** It's a pattern. Read it, adapt it, replace anything that doesn't fit your domain.

## Background

I built AlphaGrid in early 2026 to route signals from a portfolio of autonomous trading strategies into live execution. The first production run had a retry bug that double-filled an order. After fixing it, I extracted the safety pattern that should have prevented it in the first place. This repo is that pattern, generalised.

More context at [pavan.blog](https://pavan.blog) — see *Systems I've Shipped* on the [/work](https://pavan.blog/work) page.

## License

MIT. See [LICENSE](LICENSE).
