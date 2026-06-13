#!/usr/bin/env python3
"""run_replay.py — CLI for the BTC RER-SRR v0.11.1 RAW single-engine replay.

Usage:
    python run_replay.py --data-dir ./data --symbol BTCUSDT --version v0_11_1 --out ./reports

The same signal engine that produces these results is importable by a future
live/paper-alarm bot:  from btc_replay.signal_engine import evaluate_at_5m_close
"""
from __future__ import annotations

import argparse
import json
import sys

from btc_replay import data_loader, reports
from btc_replay.config import load_config
from btc_replay.replay_engine import run_replay


def main() -> int:
    ap = argparse.ArgumentParser(description="BTC RER-SRR v0.11.1 RAW replay")
    ap.add_argument("--data-dir", default="./data")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--version", default="v0_11_1")
    ap.add_argument("--out", default="./reports")
    ap.add_argument("--config", default=None, help="optional JSON config override")
    args = ap.parse_args()

    cfg = load_config(args.config)
    cfg.data["symbol"] = args.symbol
    cfg.data["version"] = args.version

    try:
        results = run_replay(args.data_dir, cfg)
    except data_loader.DataError as e:
        # The single most important rule of the brief: do NOT fabricate.
        print("=" * 70)
        print("RELIABLE BACKTEST YAPILAMADI")
        print("=" * 70)
        print(f"Sebep: {e}")
        print()
        print("Trade log üretilemiyor çünkü gerçek 1M veri yüklenmedi.")
        print(f"Çözüm: Binance tarzı 1M {args.symbol} OHLCV CSV/ZIP dosyalarını "
              f"'{args.data_dir}' klasörüne koyup tekrar çalıştırın.")
        return 2

    summary = reports.write_all(results, cfg, args.out)

    print(json.dumps(summary, indent=2, default=str))
    print()
    if summary["filled_trade"] == 0:
        print(">>> UYARI: filled_trade = 0. RELIABLE BACKTEST YAPILAMADI "
              "(hiç dolmuş trade yok). summary.json reliability_note alanına bakın.")
    else:
        print(f">>> {summary['filled_trade']} trade dolduruldu. "
              f"net total_R (0.08% maliyet) = {summary['total_R']}.")
    print(f">>> Çıktılar: {args.out}/  (decision_log.csv, trade_log.csv, summary.json + spec raporları)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
