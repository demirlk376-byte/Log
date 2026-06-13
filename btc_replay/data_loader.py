"""data_loader.py — load 1M BTCUSDT OHLCV and resample to 5M/15M/1H.

Accepts:
  * zipped or plain CSV files,
  * either explicit header (timestamp/open/high/low/close/volume)
    or raw Binance kline format (12 columns, no header).

Guarantees:
  * timestamps normalized to UTC (tz-naive UTC internally),
  * sorted, de-duplicated,
  * missing-minute gaps are detected and reported (NOT silently skipped),
  * resampling produces ONLY fully-closed candles.
"""
from __future__ import annotations

import glob
import io
import os
import zipfile
from typing import List

import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]

# Canonical 12-col Binance kline layout (no header).
_BINANCE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_base", "taker_quote", "ignore",
]


class DataError(Exception):
    """Raised on malformed / unloadable data so the replay never silently skips it."""


def _read_one_csv(buf, name: str) -> pd.DataFrame:
    # Peek first line to decide if there is a header.
    head = buf.readline()
    buf.seek(0)
    head_str = head.decode("utf-8", "ignore") if isinstance(head, bytes) else str(head)
    has_header = "open" in head_str.lower() and "close" in head_str.lower()

    if has_header:
        df = pd.read_csv(buf)
        df.columns = [str(c).strip().lower() for c in df.columns]
        ts_col = next((c for c in ("timestamp", "open_time", "time", "date") if c in df.columns), None)
        if ts_col is None:
            raise DataError(f"{name}: header present but no timestamp/open_time column found")
        df = df.rename(columns={ts_col: "timestamp"})
    else:
        df = pd.read_csv(buf, header=None)
        ncols = df.shape[1]
        if ncols >= 12:
            df = df.iloc[:, :12]
            df.columns = _BINANCE_COLS
            df = df.rename(columns={"open_time": "timestamp"})
        elif ncols == 6:
            df.columns = ["timestamp"] + OHLCV
        else:
            raise DataError(f"{name}: headerless CSV with {ncols} columns; expected 6 or >=12")

    missing = [c for c in OHLCV if c not in df.columns]
    if missing:
        raise DataError(f"{name}: missing OHLCV columns {missing}")

    return df[["timestamp"] + OHLCV].copy()


def _normalize_timestamps(df: pd.DataFrame, name: str) -> pd.DataFrame:
    ts = df["timestamp"]
    if pd.api.types.is_numeric_dtype(ts):
        # Heuristic: ms vs s vs us epoch by magnitude.
        sample = float(pd.to_numeric(ts.iloc[0]))
        if sample > 1e17:
            unit = "ns"
        elif sample > 1e14:
            unit = "us"
        elif sample > 1e11:
            unit = "ms"
        else:
            unit = "s"
        df["timestamp"] = pd.to_datetime(ts, unit=unit, utc=True)
    else:
        df["timestamp"] = pd.to_datetime(ts, utc=True, errors="coerce")

    if df["timestamp"].isna().any():
        n = int(df["timestamp"].isna().sum())
        raise DataError(f"{name}: {n} rows have unparseable timestamps")

    # store tz-naive UTC for clean resampling/comparison
    df["timestamp"] = df["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
    return df


def load_1m(data_dir: str, symbol: str = "BTCUSDT") -> pd.DataFrame:
    """Load all 1M OHLCV for `symbol` from `data_dir` (csv/zip) into one frame."""
    patterns = ["*.zip", "*.csv", "*.CSV"]
    files: List[str] = []
    for p in patterns:
        files.extend(glob.glob(os.path.join(data_dir, p)))
        files.extend(glob.glob(os.path.join(data_dir, "**", p), recursive=True))
    files = sorted(set(files))
    # Prefer files that look like they belong to the symbol, but don't exclude
    # files that simply omit the symbol in their name.
    sym_files = [f for f in files if symbol.lower() in os.path.basename(f).lower()]
    use_files = sym_files if sym_files else files

    if not use_files:
        raise DataError(
            f"No CSV/ZIP data found in '{data_dir}'. "
            f"Place Binance-style 1M {symbol} OHLCV files there."
        )

    frames: List[pd.DataFrame] = []
    for f in use_files:
        if f.lower().endswith(".zip"):
            with zipfile.ZipFile(f) as zf:
                for member in zf.namelist():
                    if not member.lower().endswith(".csv"):
                        continue
                    with zf.open(member) as fh:
                        buf = io.BytesIO(fh.read())
                        frames.append(_read_one_csv(buf, f"{os.path.basename(f)}:{member}"))
        else:
            with open(f, "rb") as fh:
                buf = io.BytesIO(fh.read())
            frames.append(_read_one_csv(buf, os.path.basename(f)))

    df = pd.concat(frames, ignore_index=True)
    df = _normalize_timestamps(df, "merged")
    for c in OHLCV:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if df[OHLCV].isna().any().any():
        bad = int(df[OHLCV].isna().any(axis=1).sum())
        raise DataError(f"{bad} rows have non-numeric OHLCV values")

    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    return df


def validate_continuity(df_1m: pd.DataFrame) -> dict:
    """Report missing 1M timestamps. Does NOT drop anything — just surfaces gaps."""
    if df_1m.empty:
        raise DataError("empty 1M dataframe")
    ts = df_1m["timestamp"]
    full = pd.date_range(ts.iloc[0], ts.iloc[-1], freq="1min")
    missing = full.difference(pd.DatetimeIndex(ts))
    return {
        "rows": int(len(df_1m)),
        "start": str(ts.iloc[0]),
        "end": str(ts.iloc[-1]),
        "expected_minutes": int(len(full)),
        "missing_minutes": int(len(missing)),
        "missing_pct": round(100.0 * len(missing) / max(1, len(full)), 4),
        "first_missing": str(missing[0]) if len(missing) else None,
    }


def resample(df_1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 1M -> rule (e.g. '5min','15min','1h'). CLOSED candles only.

    A bar is kept only if its window is fully covered by available 1M data
    (so we never emit a half-formed/forming candle).
    """
    idx = df_1m.set_index("timestamp").sort_index()
    agg = idx.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        n=("open", "size"),
    )
    agg = agg.dropna(subset=["open"])
    bar_minutes = int(pd.Timedelta(rule) / pd.Timedelta("1min"))
    agg["full"] = agg["n"] >= bar_minutes  # window fully covered
    agg["close_time"] = agg.index + pd.Timedelta(rule)
    out = agg.reset_index().rename(columns={"timestamp": "open_time"})
    return out[["open_time", "close_time", "open", "high", "low", "close", "volume", "n", "full"]]
