#!/usr/bin/env python3
"""Dip-buyer bot for the agent-fun/bars-replay/v1 BTC race.

Strategy in one paragraph: cbBTC on a thin DEX pool spends most of a day
chopping sideways, and every round trip through the replay costs roughly
20-35 bps in fees, slippage and price impact, so chasing strength loses.
This bot does the opposite: it waits for a sharp one-hour dip, buys it with
part of the stack, adds a second tranche if the dip deepens, and sells the
bounce. A hard stop and a maximum hold keep a dip that turns into a slide
from doing real damage.

The bot speaks newline-delimited JSON on stdin/stdout: a hello, one batch
per minute bar, then done. It answers every batch with exactly one reply.
It is fully deterministic: no clock, no randomness, no files, no network;
the only inputs are the lines the harness sends.
"""

import json
import sys

SYMBOL = "CBBTC"

# --- strategy constants -------------------------------------------------
LOOKBACK = 60            # bars in the dip measurement (one hour of 1m bars)
DIP_BPS = 65             # buy when the last LOOKBACK return is at or below -this
TAKE_PROFIT_BPS = 35     # sell when the close is this far above the entry price
STOP_BPS = 120           # sell when the close is this far below the entry price
MAX_HOLD_BARS = 300      # sell whatever is left after this many bars in position
BASE_SHARE = 0.55        # share of equity the first tranche spends
ADD_DIP_BPS = 50         # add once when the close falls this far below entry
ADD_SHARE = 0.75         # the add spends BASE_SHARE * this of equity
COOLDOWN_BARS = 5        # batches to sit out after a filled exit
SLIPPAGE_CAP_BPS = 300   # max_slippage_bps sent with every order


class Bot:
    """All state the strategy keeps between batches."""

    def __init__(self):
        self.closes = []          # raw integer closes, oldest first
        self.min_notional = 1_000_000
        self.warmup_bars = 0
        self.seq = -1
        # position tracking: reference price is the fill-weighted average
        # entry price (raw price units) of the open position's buys.
        self.ref_price = None     # float, raw price scale
        self.ref_qty = 0          # qty accumulated at ref_price
        self.hold_bars = 0
        self.cooldown = 0
        self.added = False        # whether the scale-in tranche already fired
        self.pending = None       # (client_id, side) awaiting its fill report
        self.pending_age = 0
        self.order_no = 0

    # -- wire helpers ----------------------------------------------------
    def next_id(self, tag):
        self.order_no += 1
        return "%s%d" % (tag, self.order_no)

    # -- fill bookkeeping --------------------------------------------------
    def note_fills(self, fills, account_qty):
        for f in fills:
            if self.pending is None or f.get("client_id") != self.pending[0]:
                continue
            side = self.pending[1]
            self.pending = None
            self.pending_age = 0
            if f.get("status") != "filled":
                continue
            if side == "buy":
                price = int(f["price"])
                qty = int(f["qty"])
                if self.ref_price is None or self.ref_qty == 0:
                    self.ref_price = float(price)
                    self.ref_qty = qty
                else:
                    tot = self.ref_qty + qty
                    self.ref_price = (self.ref_price * self.ref_qty + price * qty) / tot
                    self.ref_qty = tot
                self.hold_bars = 0
            else:  # a filled sell closes the position
                self.ref_price = None
                self.ref_qty = 0
                self.hold_bars = 0
                self.added = False
                self.cooldown = COOLDOWN_BARS
        if account_qty == 0 and self.pending is None:
            # Position gone (e.g. a sell filled): keep the books honest.
            if self.ref_price is not None:
                self.ref_price = None
                self.ref_qty = 0
                self.hold_bars = 0
                self.added = False

    # -- the strategy ------------------------------------------------------
    def decide(self, batch, account):
        """Return the order list for this batch (usually empty or one order)."""
        bars = batch.get("bars") or []
        bar = None
        for b in bars:
            if b.get("symbol") == SYMBOL:
                bar = b
        positions = account.get("positions") or []
        held_qty = 0
        for p in positions:
            if p.get("symbol") == SYMBOL:
                held_qty = int(p["qty"])
        self.note_fills(batch.get("fills") or [], held_qty)

        if self.pending is not None:
            self.pending_age += 1
            if self.pending_age > 2:
                # The fill report never named our order; stop waiting on it.
                self.pending = None
                self.pending_age = 0
        if bar is None:
            return []
        close = int(bar["c"])
        self.closes.append(close)
        if self.seq < self.warmup_bars:
            return []
        if self.cooldown > 0:
            self.cooldown -= 1

        cash = int(account["cash_quote_units"])
        equity = int(account["equity_quote_units"])

        if held_qty > 0:
            self.hold_bars += 1
            if self.pending is not None:
                # An order from the last batch has not reported back yet;
                # wait for its fill instead of stacking another order.
                return []
            if self.ref_price is None:
                # We hold something our fills never priced (cannot happen in
                # practice); anchor on the current close and carry on.
                self.ref_price = float(close)
                self.ref_qty = held_qty
            ref = self.ref_price
            if close <= ref * (1.0 - STOP_BPS / 10000.0):
                return [self.sell_order(held_qty)]
            if close >= ref * (1.0 + TAKE_PROFIT_BPS / 10000.0):
                return [self.sell_order(held_qty)]
            if self.hold_bars >= MAX_HOLD_BARS:
                return [self.sell_order(held_qty)]
            if (not self.added and self.pending is None
                    and close <= ref * (1.0 - ADD_DIP_BPS / 10000.0)):
                # The dip deepened instead of bouncing: a second, larger
                # tranche buys the better price. The position's value plus
                # this spend stays within equity because the spend is capped
                # by the cash on hand.
                add = int(equity * BASE_SHARE * ADD_SHARE)
                if add > cash:
                    add = cash
                if add >= self.min_notional:
                    self.added = True
                    return [self.buy_order(add)]
            return []

        # Flat: look for the dip.
        if self.pending is not None or self.cooldown > 0:
            return []
        if len(self.closes) <= LOOKBACK:
            return []
        then = self.closes[-1 - LOOKBACK]
        if then <= 0:
            return []
        dip = (close / then - 1.0) * 10000.0
        if dip > -DIP_BPS:
            return []
        notional = int(equity * BASE_SHARE)
        if notional > cash:
            notional = cash
        if notional < self.min_notional:
            return []
        return [self.buy_order(notional)]

    def buy_order(self, notional):
        cid = self.next_id("b")
        self.pending = (cid, "buy")
        self.pending_age = 0
        return {"side": "buy", "client_id": cid, "symbol": SYMBOL,
                "notional_quote_units": str(notional),
                "max_slippage_bps": SLIPPAGE_CAP_BPS}

    def sell_order(self, qty):
        cid = self.next_id("s")
        self.pending = (cid, "sell")
        self.pending_age = 0
        return {"side": "sell", "client_id": cid, "symbol": SYMBOL,
                "qty": str(qty), "max_slippage_bps": SLIPPAGE_CAP_BPS}


def main():
    bot = Bot()
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        kind = msg.get("type")
        if kind == "hello":
            bot.min_notional = int(msg["fees"]["min_notional_quote_units"])
            bot.warmup_bars = int(msg.get("warmup_bars") or 0)
        elif kind == "batch":
            bot.seq = int(msg["seq"])
            orders = bot.decide(msg, msg["account"])
            reply = {"type": "reply", "seq": msg["seq"], "orders": orders}
            out.write(json.dumps(reply, separators=(",", ":")) + "\n")
            out.flush()
        elif kind == "done":
            return


if __name__ == "__main__":
    main()
