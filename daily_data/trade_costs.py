"""Historical NSE delivery-equity cost scenarios for April-December 2023.

Adapted from the saved research calculator. No research files, account state,
network connection or paper-ledger fee posting is required by this module.
"""
import argparse
import json
from datetime import date
from decimal import Context, Decimal, localcontext

START='2023-04-01'
END='2023-12-31'
D=Decimal
SOURCES=[
 {'source':'https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies','supports':'Delivery-equity STT 0.1% on each side; SEBI turnover 0.0001% each side; stock-broker service GST 18%'},
 {'source':'https://www.nseindia.com/static/invest/first-time-investor-stamp-duty-charges-taxes','supports':'Delivery-equity stamp duty 0.015% on buyer; effective July 1, 2020'},
 {'source':'https://nsearchives.nseindia.com/content/circulars/FA61137.pdf','supports':'Existing post-April-2023 first-volume-tier cash transaction charge Rs 3.25/lakh each side before the 2024 revision'},
 {'source':'https://nsearchives.nseindia.com/web/sites/default/files/inline-files/PR%20NSE%20rolls%20back%20increase%20in%20transaction%20charges.pdf','supports':'April 1, 2023 rollback and IPFT contribution Rs 10/crore cash-equity turnover'}
]

def amount(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('Expected a decimal number')
    try:v=D(str(value))
    except Exception as e:raise ValueError('Invalid amount') from e
    if not v.is_finite() or v<0:raise ValueError('Nonfinite or negative amount')
    if v>D('1e15') or len(v.as_tuple().digits)>28 or v.as_tuple().exponent < -12:
        raise ValueError('Amount exceeds supported magnitude or decimal precision')
    return v

def _round_trip(buy_notional,sell_notional,day,brokerage_per_order=0,dp_fee_ex_gst=0,slippage_bps_each_side=0):
    date.fromisoformat(day)
    if not START<=day<=END:raise ValueError('No reviewed cost schedule for requested date')
    buy,sell=amount(buy_notional),amount(sell_notional)
    if min(buy,sell)<=0:raise ValueError('Round trip requires positive buy and sale notionals')
    broker=amount(brokerage_per_order)*2;dp=amount(dp_fee_ex_gst);bps=amount(slippage_bps_each_side)
    turnover=buy+sell
    parts=dict(stt=turnover*D('.001'),stamp_duty=buy*D('.00015'),exchange_first_tier=turnover*D('.0000325'),sebi=turnover*D('.000001'),ipft=turnover*D('.000001'),brokerage=broker,dp_fee=dp)
    # Broker-invoiced taxable base is an explicit estimate assumption, not an
    # exact contract-note/tax calculation. STT/stamp are not included in it.
    parts['gst_estimate']=D('.18')*(parts['exchange_first_tier']+parts['sebi']+parts['ipft']+broker+dp)
    parts['slippage_scenario']=turnover*bps/D(10000)
    total=sum(parts.values(),D(0))
    return dict(day=day,schedule_start=START,schedule_end=END,currency='INR',monetary_units='rupees',buy_notional=str(buy),sell_notional=str(sell),components_inr={k:str(v) for k,v in parts.items()},total_cost_inr=str(total),cost_as_fraction_of_buy=str(total/buy),cost_bps_of_buy=str(total/buy*10000),assumptions=dict(brokerage_per_order_inr=str(broker/2),dp_fee_ex_gst_inr=str(dp),slippage_bps_each_side=str(bps),exchange_fee_tier='First-volume-tier reference, not every broker member rate',gst_base='Exchange, SEBI, IPFT, brokerage and DP fees; verify with actual contract note',rounding='Continuous pre-rounding estimate; exact daily STT/VWAP rounding not modeled',scenario='One delivery-equity buy leg and one delivery-equity sale leg; schedule date is not execution timing'),not_included=['Personal capital-gains/dividend income tax','Account-specific concessions/other broker charges','Financing, spread beyond the declared slippage scenario, impact, auction/settlement failures'],profitability_evaluated=False,ledger_fees_posted=False)


def round_trip(buy_notional, sell_notional, day, brokerage_per_order=0,
               dp_fee_ex_gst=0, slippage_bps_each_side=0):
    """Estimate two delivery legs under one historical schedule.

    ``day`` selects a fee schedule, not actual execution dates. Monetary inputs
    are INR rupees, unlike the paper ledger's integer paise. Brokerage applies
    once per leg; the DP scenario applies once to the sale. All results are
    continuous estimates without contract-note or daily STT/VWAP rounding.
    """
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError('Expected an ISO YYYY-MM-DD schedule date')
    # Bound inputs, then isolate precision, rounding and traps from the caller.
    # Component sums are exact within these bounds; ratios use 80-digit precision.
    values = [amount(v) for v in (buy_notional, sell_notional, brokerage_per_order,
                                 dp_fee_ex_gst, slippage_bps_each_side)]
    with localcontext(Context(prec=80)):
        return _round_trip(values[0], values[1], day, *values[2:])

def assert_strategy_ready(release,execution_review):
    """Check caller-supplied flags, not the authenticity of their evidence."""
    if release.get('strategy_evaluation_eligible') is not True:raise ValueError('Profitability backtest blocked: release is raw-price forecasting only')
    required=('dividend_entitlement_and_cash_timing','decision_and_executable_fill_timing','cost_schedule_and_broker_profile','position_and_cash_constraints')
    if not all(execution_review.get(k) is True for k in required):raise ValueError('Profitability backtest blocked: execution/accounting review incomplete')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--buy-notional', required=True, help='Hypothetical buy value in INR')
    parser.add_argument('--sell-notional', required=True, help='Hypothetical sale value in INR')
    parser.add_argument('--day', required=True, help='Schedule date: 2023-04-01 through 2023-12-31')
    parser.add_argument('--brokerage-per-order', default='0', help='Declared INR scenario per leg')
    parser.add_argument('--dp-fee-ex-gst', default='0', help='Declared INR scenario once on sale')
    parser.add_argument('--slippage-bps-each-side', default='0', help='Declared basis-point scenario on each leg')
    args = parser.parse_args()
    try:
        result = round_trip(args.buy_notional, args.sell_notional, args.day,
                            args.brokerage_per_order, args.dp_fee_ex_gst,
                            args.slippage_bps_each_side)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, allow_nan=False))

if __name__ == '__main__':
    main()
