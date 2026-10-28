"""The trader-skill tools behind the 13F, News and Congress tabs.

Thin wrappers over the vendored scripts in traderbot/skills: they choose the
inputs, call the skill's own functions, and turn its errors into one
ServiceError type the UI can show. `offline` points a call at a folder of
saved responses (the tests use the skill's fixtures).
"""

import datetime as _dt
import json
import os
import re

from . import paths
from .skills import edgar13f, news, ptr

PLACEHOLDER = "you@example.com"


class ServiceError(Exception):
    pass


def sec_user_agent(text):
    """The SEC User-Agent ("Your Name you@example.com") or a clear error.
    SEC refuses anonymous programs, so the user's own name and email are needed."""
    ua = (text or "").strip()
    if not ua or "@" not in ua or PLACEHOLDER in ua:
        raise ServiceError("SEC kimliği gerekli: Ayarlar'a 'Ad Soyad eposta@ornek.com' "
                           "biçiminde kendi adınızı ve e-postanızı yazın (SEC kuralı).")
    return ua


# ---------------------------------------------------------------- 13F copycat

def find_filers(query, ua=None, offline=None):
    """Bundled well-known filers first, then (with a User-Agent) EDGAR's search."""
    query = (query or "").strip()
    if not query:
        return []
    hits = [dict(f, source="bundled") for f in edgar13f.find_bundled(query)]
    if ua or offline:
        known = {h["cik"] for h in hits}
        try:
            fetcher = edgar13f.Fetcher(ua, offline=offline)
            hits += [dict(h, source="sec") for h in edgar13f.search_sec(fetcher, query)
                     if h["cik"] not in known]
        except edgar13f.EdgarError as exc:
            if not hits:
                raise ServiceError(str(exc))
    return hits


def holdings(cik, ua, combine=True, offline=None):
    """The latest 13F-HR: {"meta", "positions", "total"}."""
    fetcher = edgar13f.Fetcher(ua if offline else sec_user_agent(ua), offline=offline)
    try:
        meta, rows, _ = edgar13f.load_quarter(fetcher, cik)
        index = _ticker_index(fetcher, meta)
        overrides = edgar13f.load_overrides([edgar13f.CLASSES])
        positions, total = edgar13f.build(meta, rows, index, overrides, {}, combine=combine)
    except edgar13f.EdgarError as exc:
        raise ServiceError(str(exc))
    return {"meta": meta, "positions": positions, "total": total}


def quarter_diff(cik, ua, offline=None):
    """What changed since the previous quarter: {"meta", "changes"}."""
    fetcher = edgar13f.Fetcher(ua if offline else sec_user_agent(ua), offline=offline)
    try:
        meta, rows, _ = edgar13f.load_quarter(fetcher, cik)
        pmeta, prior, _ = edgar13f.load_quarter(fetcher, cik, before=meta["period"])
        index = _ticker_index(fetcher, meta)
        overrides = edgar13f.load_overrides([edgar13f.CLASSES])
        cur, _ = edgar13f.aggregate(rows)
        pri, _ = edgar13f.aggregate(prior)
        edgar13f.resolve_tickers(cur, index, overrides)
        edgar13f.resolve_tickers(pri, index, overrides)
    except edgar13f.EdgarError as exc:
        raise ServiceError(str(exc))
    meta["prior_period"] = pmeta["period"]
    return {"meta": meta, "changes": edgar13f.diff(cur, pri)}


def copy_targets(result, top=10, min_pct=0.0, exclude=()):
    """trader-copycat's targets.json document for a holdings() result."""
    meta = result["meta"]
    try:
        weights, skipped = edgar13f.copy_weights(result["positions"], top=top or None,
                                                 min_pct=min_pct, exclude=exclude)
    except edgar13f.EdgarError as exc:
        raise ServiceError(str(exc))
    return {"source": "%s 13F-HR, quarter ending %s, filed %s (accession %s)" % (
        meta.get("filer"), meta.get("period"), meta.get("filed"), meta.get("accession")),
        "as_of": meta.get("period"), "filed": meta.get("filed"), "cik": meta.get("cik"),
        "weights": weights, "skipped": skipped, "caveats": edgar13f.CAVEATS}


def _ticker_index(fetcher, meta):
    try:
        return edgar13f.ticker_index(fetcher)
    except edgar13f.EdgarError as exc:
        meta.setdefault("notes", []).append("Tickers by name skipped: %s" % exc)
        return None


# ---------------------------------------------------------------- news

def headlines(tickers, ua=None, hours=48, state_path=None, offline=None, now=None):
    """Yahoo headlines and (with a SEC User-Agent) 8-K filings for tickers,
    newest first, each tagged with what it touches. Returns (items, notes)."""
    watch = {t.upper(): None for t in tickers if t}
    if not watch:
        return [], ["İzlenecek sembol yok"]
    state_path = state_path or paths.path("news_state.json")
    state = news.load_json(state_path) or {}
    notes = []
    use_sec = bool(ua or offline)
    if not use_sec:
        notes.append("SEC 8-K dosyaları atlandı: Ayarlar'a SEC kimliği girin")
    fetcher = news.Fetcher(ua, offline=offline)
    items = news.collect(fetcher, watch, state, sec=use_sec, errors=notes)
    items = news.dedupe(news.tag(items, watch))
    now = now or _dt.datetime.now(_dt.timezone.utc)
    shown = news.select(items, state, now, hours=hours, show_all=True)
    news.remember(items, state, now)
    try:
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass
    return shown, notes


# ---------------------------------------------------------------- Congress

def congress_filings(year=None, members=None, since=None, offline=None):
    """House Periodic Transaction Reports, newest first."""
    year = year or _dt.date.today().year
    try:
        rows = ptr.load_index(year, offline=offline)
    except ptr.PtrError as exc:
        raise ServiceError(str(exc))
    members = [m for m in (members or []) if m.strip()]
    return ptr.select(rows, members=members or None, kind="P", since=since)


def read_ptr(doc_id, year, filed=None, pdf_dir=None):
    """Download one PTR and parse it when pdftotext is installed; else the
    PDF path is returned so the UI can open it."""
    pdf_dir = pdf_dir or paths.path("ptr_pdfs", "x")[:-2]
    if not re.fullmatch(r"\d{5,12}", str(doc_id)):
        raise ServiceError("Geçersiz belge numarası: %s" % doc_id)
    try:
        path, report = ptr._fetch_and_read(str(doc_id), int(year), pdf_dir, filed)
    except ptr.PtrError as exc:
        raise ServiceError(str(exc))
    return {"pdf": path, "report": report,
            "text": ptr.render_report(report) if report else None}


def open_target(path_or_url):
    return path_or_url if "://" in path_or_url else "file:///" + os.path.abspath(path_or_url)
