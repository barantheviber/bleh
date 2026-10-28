"""What every broker offers the bot and the UI.

Orders use Alpaca's place_stock_order shape, the same one trader-budget,
trader-rebalance and trader-risk produce: {"symbol", "side", "qty" or
"notional", "type", "time_in_force"} with numbers as strings.
"""


class BrokerError(Exception):
    """A broker refused or failed; the message is shown to the user as is."""


class Account(object):
    __slots__ = ("cash", "equity", "buying_power", "currency", "paper", "status", "broker")

    def __init__(self, cash, equity, buying_power=None, currency="USD", paper=True,
                 status="ACTIVE", broker=""):
        self.cash = float(cash)
        self.equity = float(equity)
        self.buying_power = float(cash if buying_power is None else buying_power)
        self.currency, self.paper, self.status, self.broker = currency, paper, status, broker

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


class Position(object):
    __slots__ = ("symbol", "qty", "avg_price", "price")

    def __init__(self, symbol, qty, avg_price, price=None):
        self.symbol = symbol
        self.qty = float(qty)
        self.avg_price = float(avg_price)
        self.price = None if price is None else float(price)

    @property
    def market_value(self):
        return self.qty * (self.price if self.price is not None else self.avg_price)

    @property
    def unrealized_pl(self):
        if self.price is None:
            return 0.0
        return self.qty * (self.price - self.avg_price)

    @property
    def unrealized_pct(self):
        if not self.avg_price or self.price is None:
            return 0.0
        return self.price / self.avg_price - 1.0

    def as_dict(self):
        d = {k: getattr(self, k) for k in self.__slots__}
        d.update(market_value=self.market_value, unrealized_pl=self.unrealized_pl)
        return d


FINAL = {"filled", "canceled", "expired", "rejected", "done_for_day", "replaced"}


class Order(object):
    __slots__ = ("id", "client_id", "symbol", "side", "qty", "notional", "type", "tif",
                 "status", "filled_qty", "filled_avg_price", "created_at", "filled_at", "note")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))
        self.filled_qty = float(self.filled_qty or 0)

    @property
    def done(self):
        return self.status in FINAL

    @property
    def filled_value(self):
        if not self.filled_qty or self.filled_avg_price is None:
            return 0.0
        return self.filled_qty * float(self.filled_avg_price)

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


class Broker(object):
    name = "base"
    paper = True

    @property
    def label(self):
        return "%s (%s)" % (self.name, "kağıt" if self.paper else "CANLI")

    def account(self):
        raise NotImplementedError

    def positions(self):
        raise NotImplementedError

    def submit(self, order):
        raise NotImplementedError

    def get_order(self, order_id):
        raise NotImplementedError

    def orders(self, limit=100):
        raise NotImplementedError

    def cancel_all(self):
        raise NotImplementedError

    def close_all(self):
        raise NotImplementedError

    def is_open(self):
        """Whether US stocks can trade now (None if the broker cannot say)."""
        return None

    def portfolio(self):
        """The account in trader-skill's portfolio.json shape:
        {"cash": n, "positions": [{"ticker", "shares"}]}"""
        acct = self.account()
        return {"cash": acct.cash,
                "positions": [{"ticker": p.symbol, "shares": p.qty} for p in self.positions()
                              if abs(p.qty) > 1e-12]}
