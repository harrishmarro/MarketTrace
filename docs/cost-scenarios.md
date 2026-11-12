# Historical delivery-equity cost scenarios

`daily_data.trade_costs` estimates the charges on one hypothetical NSE
delivery-equity buy leg and one sale leg. It adapts the saved research
calculator into a standalone, standard-library API and command-line tool.
It reads no market dataset, private release or account database, and writes
JSON to standard output.

The supported schedule is **April 1 through December 31, 2023, inclusive**.
Earlier and later dates are rejected. This is a historical delivery-equity
reference, not a current fee quote, intraday-equity calculator, options model,
contract note or profitability backtest. It does not add fees to ledger fills.

## Run a synthetic scenario

From the repository root, with Python 3.12:

```bash
python -m daily_data.trade_costs \
  --buy-notional 100000 \
  --sell-notional 100000 \
  --day 2023-06-01 \
  --brokerage-per-order 20 \
  --dp-fee-ex-gst 20 \
  --slippage-bps-each-side 5
```

These are invented scenario values. Brokerage and depository-participant (DP)
fees are user-supplied assumptions, not broker quotes. Brokerage applies once
to each leg; the DP fee applies once on the sale. One basis point is 0.01%.

All monetary inputs are **INR rupees**, not the paper ledger's integer paise.
The default brokerage, DP and slippage inputs are zero to isolate the reference
charges; this does not assert that an account can trade without those costs.
`--day` selects the historical rate schedule. It does not set execution dates,
establish actual delivery settlement or classify a same-day trade as delivery.

For the equal INR 100,000 legs in this example:

| Component | INR estimate |
| --- | ---: |
| STT on both legs | 200 |
| Stamp duty on the buy | 15 |
| First-tier exchange charges on both legs | 6.5 |
| SEBI turnover fees | 0.2 |
| IPFT contribution | 0.2 |
| Declared brokerage, two orders | 40 |
| Declared DP fee, one sale | 20 |
| GST estimate on the stated taxable base | 12.042 |
| Declared slippage, five basis points per leg | 100 |
| **Total** | **393.942** |

With all optional scenarios zero, the reference total is INR 223.142. These
continuous, pre-rounding amounts are calculation examples, not invoice totals.

## Python API

```python
from decimal import Decimal
from daily_data.trade_costs import round_trip

result = round_trip('100000', '100000', '2023-06-01',
                    brokerage_per_order='20', dp_fee_ex_gst='20',
                    slippage_bps_each_side='5')
assert Decimal(result['total_cost_inr']) == Decimal('393.942')
assert result['profitability_evaluated'] is False
assert result['ledger_fees_posted'] is False
```

Use decimal strings or `Decimal` values when exact input decimals matter.
Finite native integers and floats are also accepted; floats are interpreted
through their decimal string representation. Booleans, negative/nonfinite
values and zero buy/sale notionals are rejected. Optional charges may be zero.
Dates must be canonical `YYYY-MM-DD` strings within the supported interval.

Each numeric input is bounded to 1e15, at most 28 stored significant digits and
at most 12 decimal places. These API limits prevent unbounded decimal scenarios.
An isolated 80-digit decimal context preserves component arithmetic and makes
ratios independent of caller precision, rounding and decimal traps. Results
remain decimal strings; recurring ratios are limited to that precision.

The result includes component costs, total INR, total as a fraction of the buy
notional, basis points of the buy notional, schedule bounds, assumptions and
omissions. The basis-point denominator is the buy notional, not total turnover.

## Historical rate basis

The source links below explain the reference assumptions. The module retains
these links in `SOURCES`; it never fetches them while calculating.

| Reference assumption | Rate and application | Primary source |
| --- | --- | --- |
| Delivery-equity STT | 0.1% on each leg | [NSE levies](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies) |
| Delivery stamp duty | 0.015% of buy value | [NSE stamp duty](https://www.nseindia.com/static/invest/first-time-investor-stamp-duty-charges-taxes), effective July 1, 2020 |
| Cash-market exchange first volume tier | INR 3.25 per lakh on each leg | [NSE/FA/61137](https://nsearchives.nseindia.com/content/circulars/FA61137.pdf), March 14, 2024: existing rate before its April 2024 change |
| SEBI turnover fee | 0.0001% on each leg | [NSE levies](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies) |
| Cash-equity IPFT contribution | INR 10 per crore on each leg | [NSE release](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/PR%20NSE%20rolls%20back%20increase%20in%20transaction%20charges.pdf), March 24, 2023 |
| GST estimate | 18% of exchange, SEBI, IPFT, declared brokerage and DP charges | [NSE stock-broker GST rate](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies); the combined taxable base is an explicit scenario assumption |

Rates can depend on transaction classification, broker/member tier, account
terms and invoice treatment. The first-tier exchange rate is not every member's
effective rate. The exact GST base and broker/DP charges need comparison with
the applicable contract note. The calculator applies no daily STT/VWAP rounding,
minimum fee, broker cap or per-invoice tax rounding.

Personal capital-gains/dividend taxes, financing, account concessions, unlisted
broker charges, price impact, additional spread and settlement/auction failures
are omitted. Slippage is a declared sensitivity, not observed execution evidence.
Dividend/corporate-action cash flows and settlement timing are not simulated.

## Verification and strategy boundary

```bash
python -m unittest daily_data.test_trade_costs daily_data.test_cost_scenarios -v
```

Tests use synthetic notionals and empty temporary directories. They check
hand-calculated components/totals, unequal legs, buyer-only stamp duty, schedule
edges, invalid inputs, decimal-context isolation and CLI operation without
private research files or generated output files.

`assert_strategy_ready(release, execution_review)` retains the existing strict
caller-flag check: a forecast-only release or missing/literal-nonboolean review
flags fail. Supplying `True` values does not authenticate supporting evidence or
create strategy approval. The cost CLI does not call or grant that gate.

The [paper ledger](paper-ledger.md) still uses simplified immediate balance
changes. This separate estimator does not debit its cash, change holdings or
measure returns. Economic accounting and executable-fill evidence are required
before any claim about after-cost strategy performance.
