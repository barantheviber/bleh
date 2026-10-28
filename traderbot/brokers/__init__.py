"""Brokers: the built-in simulated account and Alpaca (paper or live)."""

from .base import Account, Broker, BrokerError, Order, Position  # noqa: F401


def create(settings, price_source):
    """The broker the settings ask for. `price_source(symbols) -> {sym: price}`
    feeds the simulator's fills and valuations."""
    from . import alpaca
    if settings.get("broker") == "alpaca":
        key, secret = settings.secret("alpaca_key_id"), settings.secret("alpaca_secret")
        if not key or not secret:
            raise BrokerError("Alpaca anahtarları girilmemiş (Ayarlar sekmesi)")
        paper = bool(settings.get("alpaca_paper"))
        if not paper and not settings.get("live_confirmed"):
            raise BrokerError("Canlı hesap onaylanmadı: Ayarlar'da canlı işlemi onaylayın")
        return alpaca.AlpacaBroker(key, secret, paper=paper)
    return create_sim(settings, price_source)


def create_sim(settings, price_source):
    """The built-in simulated account, whatever broker the settings name."""
    from . import sim
    from .. import paths
    return sim.SimBroker(paths.path("sim_account.json"), price_source,
                         start_cash=float(settings.get("sim_cash") or 10000.0),
                         slippage_bps=float(settings.get("sim_slippage_bps") or 0.0))
