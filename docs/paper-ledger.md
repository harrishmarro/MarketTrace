# Paper-order ledger and risk controls

`paper.ledger.Ledger` is a transactional, local SQLite prototype for simulated
long-only orders. It does not place live orders, connect to a broker, authenticate
a person or supply market prices. No private account state or saved trading
database is distributed with the code.

## Units and trusted inputs

Money and prices are integer minor units: US cents for `US`, or INR paise for
`IN`. Quantities are positive integer shares; fractional shares and booleans are
rejected. The two market cash accounts are separate; no currency conversion or
combined account value is inferred.

Times are caller-supplied integer Unix seconds. The caller is responsible for a
trusted clock, quote origin, market availability and valid symbol identity. A
quote age check is not price-feed authentication. Daily grouping uses the
exchange-local date, not a certified session/holiday or market-hours calendar.

## Order lifecycle

1. Initialize pretend cash once and configure per-order/daily risk limits.
2. For buys, configure the portfolio limits and capture a trusted session-start
   equity baseline. Mark every existing holding with a sufficiently fresh price.
3. `propose` records a pending order, entry-price bounds, creation time and expiry.
   Proposing an order does not fill it or reserve its cash or shares.
4. `decide` requires an explicit boolean approval or rejection. An approval
   rechecks the current quote, limits and portfolio before changing balances.
5. Successful fills atomically update cash, whole-share holdings, order status
   and the unique fill record. Validation errors roll back the transaction.
   A decision on an already decided order is rejected.

An approval at or after expiry records `expired`; a price outside entry bounds
records `invalidated`. Neither fills. Risk failures leave the proposal pending
so a caller can reject it or reassess before expiry. Rejection needs no quote.
Decisions before a recorded proposal creation time are rejected.

## Risk behavior

| Check | Behavior |
| --- | --- |
| Per-order money/share limits | Enforced again at fill time, using the approved quote |
| Daily gross value and fill count | Cumulative across all buys and sells in that market/date; split orders do not bypass them |
| Cash and holdings | Overspending and short-selling are rejected |
| Quote age and bounds | Stale/future quotes cannot fill; entry bounds must still hold |
| Kill switch | Halts both buy and sell fills, while allowing rejection; reconfiguring limits does not silently clear it |
| Concentration | A new buy cannot exceed the configured per-symbol value share of marked equity |
| Daily equity loss | A buy is blocked when current equity falls below its immutable daily baseline by the configured amount |
| Missing portfolio evidence | Missing/stale/future marks, absent portfolio policy or missing daily baseline block new buys |

Concentration is checked per symbol, not across corporate groups. The loss check
includes unrealized marked losses and realized balance changes, but is not a
trailing high-water drawdown or a latched daily halt: buys can become eligible
again if equity recovers. Sells bypass concentration and loss checks, but still
face the kill switch and other risk/cash/holding limits. There is no automatic
liquidation. Risk-limit values are test settings, not recommended trading limits.

## Synthetic example

This example uses invented quotes, artificial timestamps and pretend balances.
The explicit approval is part of the example; it is not a trading recommendation.

```python
from paper.ledger import Ledger

ledger = Ledger()  # In-memory state; no existing account is loaded.
try:
    ledger.seed_cash('US', 100000)
    ledger.configure_limits('US', max_value=25000, max_shares=2,
                            daily_value=50000, daily_trades=5)
    ledger.configure_portfolio_limits('US', concentration_bps=2500,
                                      daily_loss=10000)
    ledger.capture_day_start('US', 100)
    order = ledger.propose('US', 'SYNTHETIC', 'buy', 1, 9900, 10100,
                           now=100, expires=160)
    status = ledger.decide(order, approve=True, now=110,
                           price=10000, quote_at=110)
    assert status == 'filled'
    assert ledger.snapshot()['cash'][0]['amount'] == 90000
finally:
    ledger.db.close()
```

Use a local path such as `local-output/paper.sqlite` for persistence and create
its parent directory first. Local database files are excluded by Git. On opening
an older ledger, a missing `created_at` column is added without inventing times
for existing orders. A legacy pending order with no creation time cannot fill:
reject it and create a new proposal, or let it expire. Existing fill history is
retained. Back up local research databases before upgrading code.

## Verification and boundaries

```bash
python -m unittest discover -s paper -p 'test_*.py' -v
```

All paper tests are offline and use synthetic prices, in-memory state or temporary
databases. They verify mechanics, not real-time feed behavior or strategy returns.
No third-party Python dependency is needed beyond an available IANA timezone
database.

This ledger does not yet account for brokerage, taxes, settlement delays,
dividend entitlement/receivables, corporate actions, executable spreads/slippage
or multiple broker accounts. Its immediate cash/holding changes are a simplified
paper convention. It is separate from forecasting evaluation: no model signal
automatically creates or approves an order. Passing tests does not release a
real-data strategy, demonstrate profitability or establish production readiness.
