# BTC RER-SRR v0.11.1 — RAW single-engine replay

Gerçek **no-lookahead** backtest/replay motoru. Backtestte çalışan `signal_engine`
ileride paper-live / alarm botta **birebir aynı** kullanılacak şekilde tasarlandı:
ayrı "backtest-only" karar mantığı yoktur.

> İlk test kapsamı: **sadece SRR-1**. Diğer setup aileleri (`SRR-2`, `RER-1`, `RER-2`)
> `config.py` içinde kapalıdır (`setups.enabled = ["SRR-1"]`).

---

## ⚠️ Veri durumu (önemli)

Bu repoya **gerçek BTCUSDT 1M CSV verisi dahil edilmedi** (sadece spec dosyaları
yüklendi). Motor hazır, ama veri olmadan **gerçek bir trade_log üretilemez**.

Görevin birincil kuralı gereği: **veri yokken özet/sonuç uydurulmaz.**
`./data` boşken `run_replay.py` çalıştırılırsa açıkça şunu yazar ve durur:

```
RELIABLE BACKTEST YAPILAMADI
```

Gerçek sonuç üretmek için Binance tarzı 1M `BTCUSDT` OHLCV dosyalarını
(`.csv` veya `.zip`) `./data/` klasörüne koyup tekrar çalıştırın.

---

## Çalıştırma

```bash
pip install -r requirements.txt
python run_replay.py --data-dir ./data --symbol BTCUSDT --version v0_11_1 --out ./reports
```

İsteğe bağlı eşik override'ı: `--config my_overrides.json` (config.py ile deep-merge edilir).

### Üretilen dosyalar

Görev brief'inin istediği birincil çıktılar:
- `decision_log.csv` — her 5M kapanışındaki karar (zengin kolonlar: h1_context, m15_zone,
  edge_id, sweep_id, entry/SL/TP1, R_abs, R_abs_bps, R_abs_ATR, TP1_R, body_ratio,
  acceptance_close_strength, opposite_wick_ratio, entry_edge_dist_band,
  acceptance_weakness_count, v10_1/v11/v11_1 sonuçları, reason_tags, duplicate/cooldown state)
- `trade_log.csv` — kolonlar: `timestamp, direction, entry, SL, TP1, RR, cost_R,
  result_R, exit_reason, exit_time, setup_reason, mfe_R, mae_R`
- `summary.json` — alanlar: `total_decisions, WATCH, CANCEL, EXECUTE_CANDIDATE,
  filled_trade, total_R, win_rate, profit_factor, max_drawdown, top_cancel_reason,
  top_sl_reason, reliability_note` (+ max_consecutive_SL, data_span, continuity)

Spec'in istediği ek raporlar:
`v0_11_1_raw_EXECUTE_log.csv`, `v0_11_1_raw_WATCH_CANCEL_log.csv`,
`v0_11_1_raw_blocked_stale_duplicate_log.csv`, `v0_11_1_raw_monthly_summary.csv`,
`v0_11_1_raw_IS_OOS_summary.csv`, `v0_11_1_raw_cost_stress.csv`,
`v0_11_1_raw_drawdown_summary.txt`.

> `summary.json` her zaman yazılır, ama hiç dolmuş trade yoksa `reliability_note`
> açıkça **"reliable backtest yapılamadı"** der; R metrikleri trade'e dayanmaz.

---

## No-lookahead garantileri

- Tüm kararlar yalnızca **kapanmış** mumlarla verilir; 1M'den 5M/15M/1H sadece
  tam (full) kapanmış mumlar üretilir (`data_loader.resample` `full` bayrağı).
- Karar anında kullanılan her TF mumu `close_time <= karar_zamanı` olanlardır.
- Karar her **5M kapanışında** verilir.
- `EXECUTE_CANDIDATE` → entry seviyesi **gerçekten gelene kadar** (retest) trade
  açılmış sayılmaz. Entry'ye dokunan ilk 1M mumda fill olur; dokunulmazsa
  `candidate_lifetime_5m` içinde **iptal** olur (trade sayılmaz).
- Fill ve TP/SL simülasyonu yalnızca **karardan sonraki** (`close_time > karar`) 1M
  mumlarıyla yapılır.
- Aynı 1M mumda hem TP hem SL görünürse **SL önce** sayılır (`bar_outcome`,
  `sl_first=True`).
- Round-trip maliyet **%0.08 (8 bps)** birincil koşuda `cost_R` olarak düşülür;
  ayrıca tam cost-stress tablosu üretilir.

## Karar zinciri (tek motor)

`signal_engine.evaluate_at_5m_close(ts, m5, m15, h1, state, cfg)`:
1. 1H context
2. 15M range/edge — `middle` → CANCEL, `unclear` → WATCH
3. 5M sweep + reclaim → Setup (entry/SL/TP1, R metrikleri)
4. **v0.10.1** Soft Acceptance (weakness_count / strict cancel)
5. **v0.11** BTC A+ Cost-Survival (normal A+, koşullu 1.8–2.0R, hard fail <1.8R)
6. **v0.11.1** No-Stale-Reentry / No Duplicate Promotion (same edge+sweep,
   cooldown=6 bar, active-setup kilidi, prior-watch reentry → WATCH)
→ `WATCH | CANCEL | EXECUTE_CANDIDATE` + `reason_tags`

## Live bot ile paylaşım

Canlı/alarm bot aynı motoru import eder:

```python
from btc_replay.signal_engine import evaluate_at_5m_close
from btc_replay.rules_v11_1 import EngineState
from btc_replay.config import load_config
```

Tüm eşikler `btc_replay/config.py` içindedir (tek yerde, override edilebilir).

## Testler

```bash
python -m pytest tests/ -q
```

- `test_rules_v10_1.py`, `test_rules_v11.py`, `test_rules_v11_1.py` — kural birim testleri
- `test_no_lookahead.py` — SL-first, kapalı-mum resample, fill'in karardan sonra olması
- `test_smoke_synthetic.py` — uçtan uca pipeline + çıktı şema doğrulaması

> `tests/_synth.py` **sentetik** veri üretir; sadece pipeline'ı doğrulamak içindir,
> gerçek piyasa verisi/sonucu değildir.
