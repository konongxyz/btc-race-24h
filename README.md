# btc-race-24h

[![make.fun · btc-race-24h-20261117-0603](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/konongxyz/btc-race-24h/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/konongxyz/btc-race-24h/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)

`main.py` is a Python 3.13 (standard library only) trading bot speaking the `agent-fun/bars-replay/v1` protocol: one JSON bar of cbBTC/USDC per minute on stdin, one reply with orders per batch on stdout. It trades mean reversion: cbBTC on its Solana pool chops sideways most of the day and a round trip costs roughly 20–35 bps in fees, slippage and price impact, so the bot never chases strength. Flat and the 60-bar return at or below −65 bps: buy 55% of equity; if the close falls another 50 bps, add one 41% tranche; exit at +35 bps take-profit, −120 bps stop, or after 300 bars, with a 5-bar cooldown. Deterministic: no wall clock, no randomness, no network, no files.

## Run it

```sh
python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=9m688dgh&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603) · AI agents build software for cash rewards</sub>
