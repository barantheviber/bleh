"""Scripts from the trader-skill pack, copied unchanged.

Source: https://github.com/Jakeschincariol/trader-skill at commit 5189e79
(MIT License, Copyright (c) 2026 Jake Schincariol; see LICENSE in this folder).

  edgar13f.py   trader-copycat: 13F-HR holdings, quarter diff, copy weights
  news.py       trader-news: Yahoo headlines and SEC 8-K feeds
  ptr.py        trader-pelosi: House Periodic Transaction Reports index
  size.py       trader-budget: budget sizing with cash buffer and cap
  check.py      trader-risk: pre-trade PASS/BLOCK checks
  rebalance.py  trader-rebalance: drift band rebalancing plan

TraderBot calls their functions in-process (see traderbot/services.py and
traderbot/engine.py); the files are kept byte-identical so updates from the
upstream pack can be copied over.
"""
