"""Transactional paper-order prototype. Values are integer minor currency units.

Caller supplies trusted UTC times and fresh reference quotes. This core is not
an authenticated API or a production price feed. No live execution is possible.
"""
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo


class Ledger:
    def __init__(self, path=':memory:'):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS cash(market TEXT PRIMARY KEY, amount INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS holdings(market TEXT, symbol TEXT, qty INTEGER NOT NULL,
            PRIMARY KEY(market, symbol));
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, market TEXT, symbol TEXT,
            side TEXT, qty INTEGER, low INTEGER, high INTEGER, expires INTEGER, status TEXT,
            created_at INTEGER);
        CREATE TABLE IF NOT EXISTS fills(order_id TEXT PRIMARY KEY, price INTEGER, at INTEGER);
        CREATE TABLE IF NOT EXISTS limits(market TEXT PRIMARY KEY, max_value INTEGER,
            max_shares INTEGER, daily_value INTEGER, daily_trades INTEGER, halted INTEGER);
        CREATE TABLE IF NOT EXISTS portfolio_limits(market TEXT PRIMARY KEY,
            concentration_bps INTEGER, daily_loss INTEGER);
        CREATE TABLE IF NOT EXISTS marks(market TEXT, symbol TEXT, price INTEGER, at INTEGER,
            PRIMARY KEY(market,symbol));
        CREATE TABLE IF NOT EXISTS day_equity(market TEXT, day TEXT, amount INTEGER,
            PRIMARY KEY(market,day));
        ''')
        # Older research ledgers lack proposal timestamps. Preserve those rows;
        # never invent a creation time that would allow a legacy proposal to fill.
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(orders)')}
        if 'created_at' not in columns:
            self.db.execute('ALTER TABLE orders ADD COLUMN created_at INTEGER')

    def configure_portfolio_limits(self, market, *, concentration_bps, daily_loss):
        if market not in ('IN', 'US'):
            raise ValueError('Unsupported market')
        self.integer(concentration_bps, 1)
        self.integer(daily_loss, 1)
        if concentration_bps > 10000:
            raise ValueError('Concentration cannot exceed 100 percent')
        self.db.execute('INSERT INTO portfolio_limits VALUES (?,?,?) ON CONFLICT(market) '
                        'DO UPDATE SET concentration_bps=excluded.concentration_bps, '
                        'daily_loss=excluded.daily_loss', (market, concentration_bps, daily_loss))

    def mark(self, market, symbol, price, at):
        if market not in ('IN', 'US') or not isinstance(symbol, str) or not symbol:
            raise ValueError('Invalid market or symbol')
        self.integer(price, 1)
        self.integer(at)
        self.db.execute('INSERT INTO marks VALUES (?,?,?,?) ON CONFLICT(market,symbol) '
                        'DO UPDATE SET price=excluded.price, at=excluded.at WHERE excluded.at>=marks.at',
                        (market, symbol, price, at))

    def equity(self, market, now, max_age=5, reference=None):
        cash = self.db.execute('SELECT amount FROM cash WHERE market=?', (market,)).fetchone()
        if cash is None:
            raise ValueError('Account not initialized')
        total = cash[0]
        values = {}
        for row in self.db.execute('SELECT symbol,qty FROM holdings WHERE market=? AND qty>0', (market,)):
            symbol = row['symbol']
            if reference is not None and symbol == reference[0]:
                price = reference[1]
            else:
                quote = self.db.execute('SELECT price,at FROM marks WHERE market=? AND symbol=?',
                                        (market, symbol)).fetchone()
                if quote is None or quote['at'] > now or now - quote['at'] > max_age:
                    raise ValueError('Fresh marks required for all open positions')
                price = quote['price']
            values[symbol] = row['qty'] * price
            total += values[symbol]
        return total, values

    def capture_day_start(self, market, now, max_age=5):
        """Trusted session worker must call at session start before processing orders.

        Immutable for the exchange-local date. No reset or cash-flow support.
        """
        self.integer(now)
        self.integer(max_age)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            amount, _ = self.equity(market, now, max_age)
            self.db.execute('INSERT INTO day_equity VALUES (?,?,?)',
                            (market, self.trading_date(now, market).isoformat(), amount))
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def check_portfolio(self, order, price, now, max_age):
        # A sale only reduces an existing long holding; holdings checks run below.
        if order['side'] == 'sell':
            return
        market = order['market']
        policy = self.db.execute('SELECT * FROM portfolio_limits WHERE market=?', (market,)).fetchone()
        baseline = self.db.execute('SELECT amount FROM day_equity WHERE market=? AND day=?',
                                   (market, self.trading_date(now, market).isoformat())).fetchone()
        if policy is None or baseline is None:
            raise ValueError('Portfolio limits and session baseline required')
        total, positions = self.equity(market, now, max_age, (order['symbol'], price))
        if baseline[0] - total >= policy['daily_loss']:
            raise ValueError('Daily equity loss limit reached; new buys blocked')
        projected = positions.get(order['symbol'], 0) + order['qty'] * price
        if total <= 0 or projected * 10000 > total * policy['concentration_bps']:
            raise ValueError('Projected company concentration exceeded')

    def configure_limits(self, market, *, max_value, max_shares, daily_value, daily_trades):
        if market not in ('IN', 'US'):
            raise ValueError('Unsupported market')
        for value in (max_value, max_shares, daily_value, daily_trades):
            self.integer(value, 1)
        self.db.execute('INSERT INTO limits VALUES (?,?,?,?,?,0) ON CONFLICT(market) '
                        'DO UPDATE SET max_value=excluded.max_value, max_shares=excluded.max_shares, '
                        'daily_value=excluded.daily_value, daily_trades=excluded.daily_trades',
                        (market, max_value, max_shares, daily_value, daily_trades))

    def halt(self, market, enabled=True):
        if type(enabled) is not bool:
            raise ValueError('Explicit boolean required')
        result = self.db.execute('UPDATE limits SET halted=? WHERE market=?', (int(enabled), market))
        if result.rowcount != 1:
            raise ValueError('Limits not configured')

    @staticmethod
    def trading_date(timestamp, market):
        zone = 'Asia/Kolkata' if market == 'IN' else 'America/New_York'
        return datetime.fromtimestamp(timestamp, ZoneInfo(zone)).date()

    def check_limits(self, order, price, now):
        limits = self.db.execute('SELECT * FROM limits WHERE market=?', (order['market'],)).fetchone()
        if limits is None:
            raise ValueError('Risk limits must be configured before filling')
        if limits['halted']:
            raise ValueError('Paper trading halted')
        value = price * order['qty']
        if value > limits['max_value'] or order['qty'] > limits['max_shares']:
            raise ValueError('Order value or share limit exceeded')
        day = self.trading_date(now, order['market'])
        rows = self.db.execute('SELECT o.qty,f.price,f.at FROM fills f JOIN orders o '
                               'ON o.id=f.order_id WHERE o.market=?', (order['market'],))
        previous = [r for r in rows if self.trading_date(r['at'], order['market']) == day]
        if sum(r['qty'] * r['price'] for r in previous) + value > limits['daily_value']:
            raise ValueError('Cumulative daily traded value exceeded')
        if len(previous) + 1 > limits['daily_trades']:
            raise ValueError('Daily trade count exceeded')

    @staticmethod
    def integer(value, minimum=0):
        if type(value) is not int or value < minimum:
            raise ValueError('Expected integer within allowed range')
        return value

    def seed_cash(self, market, amount):
        if market not in ('IN', 'US'):
            raise ValueError('Unsupported market')
        self.integer(amount)
        # Initialization only: never overwrite an existing account balance.
        self.db.execute('INSERT INTO cash VALUES (?, ?)', (market, amount))

    def propose(self, market, symbol, side, qty, low, high, now, expires):
        if market not in ('IN', 'US') or side not in ('buy', 'sell'):
            raise ValueError('Invalid market or side')
        if not isinstance(symbol, str) or not symbol or len(symbol) > 32:
            raise ValueError('Invalid symbol')
        for value in (qty, low, high):
            self.integer(value, 1)
        self.integer(now)
        self.integer(expires)
        if high < low or expires <= now:
            raise ValueError('Invalid entry range or expiry')
        if self.db.execute('SELECT 1 FROM cash WHERE market=?', (market,)).fetchone() is None:
            raise ValueError('Account not initialized')
        order_id = str(uuid.uuid4())
        self.db.execute('INSERT INTO orders '
                        '(id,market,symbol,side,qty,low,high,expires,status,created_at) '
                        'VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (order_id, market, symbol, side, qty, low, high, expires, 'pending', now))
        return order_id

    def decide(self, order_id, approve, now, price=None, quote_at=None, max_age=5):
        if type(approve) is not bool:
            raise ValueError('Explicit boolean decision required')
        self.integer(now)
        self.integer(max_age)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            order = self.db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            if order is None or order['status'] != 'pending':
                raise ValueError('Order is missing or already decided')
            if order['created_at'] is not None and now < order['created_at']:
                raise ValueError('Decision predates proposal')
            if not approve:
                status = 'rejected'
            elif now >= order['expires']:
                status = 'expired'
            else:
                if order['created_at'] is None:
                    raise ValueError('Legacy proposal has no creation timestamp; reject and re-propose')
                self.integer(price, 1)
                self.integer(quote_at)
                if quote_at > now or now - quote_at > max_age:
                    raise ValueError('Stale or future quote; no fill')
                if not order['low'] <= price <= order['high']:
                    status = 'invalidated'
                else:
                    self.check_limits(order, price, now)
                    self.check_portfolio(order, price, now, max_age)
                    market, symbol, qty = order['market'], order['symbol'], order['qty']
                    cash = self.db.execute('SELECT amount FROM cash WHERE market=?', (market,)).fetchone()[0]
                    held = self.db.execute('SELECT qty FROM holdings WHERE market=? AND symbol=?',
                                           (market, symbol)).fetchone()
                    held = held[0] if held else 0
                    delta = qty if order['side'] == 'buy' else -qty
                    next_cash = cash - delta * price
                    if next_cash < 0 or held + delta < 0:
                        raise ValueError('Insufficient cash or shares')
                    self.db.execute('UPDATE cash SET amount=? WHERE market=?', (next_cash, market))
                    self.db.execute('INSERT INTO holdings VALUES (?,?,?) ON CONFLICT(market,symbol) '
                                    'DO UPDATE SET qty=excluded.qty', (market, symbol, held + delta))
                    self.db.execute('INSERT INTO fills VALUES (?,?,?)', (order_id, price, now))
                    status = 'filled'
            self.db.execute('UPDATE orders SET status=? WHERE id=?', (status, order_id))
            self.db.execute('COMMIT')
            return status
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def snapshot(self):
        return {table: [dict(row) for row in self.db.execute('SELECT * FROM ' + table)]
                for table in ('cash', 'holdings', 'orders', 'fills')}
