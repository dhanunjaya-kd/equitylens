"""Builds tests/fixtures/indicators_ref.json: reference values for the chart indicators from the `ta` library
(bukosabino/ta) and plain pandas formulas. Run once by a developer:  pip install ta pandas  ;  python tests/make_indicator_ref.py"""
import json
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd
import ta

rnd = random.Random(42)
bars, p = [], 100.0
for i in range(700):
    o = p * (1 + rnd.gauss(0, 0.004))
    c = o * (1 + rnd.gauss(0.0003, 0.015))
    h = max(o, c) * (1 + abs(rnd.gauss(0, 0.006)))
    l = min(o, c) * (1 - abs(rnd.gauss(0, 0.006)))
    v = int(rnd.uniform(5e5, 3e6))
    bars.append({"o": round(o, 4), "h": round(h, 4), "l": round(l, 4), "c": round(c, 4), "v": v})
    p = c
df = pd.DataFrame(bars)
o, h, l, c, v = df.o, df.h, df.l, df.c, df.v.astype(float)


def wma(s, n):
    w = np.arange(1, n + 1)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def tv_sar(b, start=0.02, inc=0.02, mx=0.2):
    """TradingView's documented Pine implementation of ta.sar, transcribed (the `ta` library differs from TradingView here)."""
    out = [float("nan")] * len(b)
    result = max_min = acc = None
    below = None
    for i in range(1, len(b)):
        first = False
        if i == 1:
            if b[1]["c"] > b[0]["c"]:
                below, max_min, result = True, b[1]["h"], b[0]["l"]
            else:
                below, max_min, result = False, b[1]["l"], b[0]["h"]
            first, acc = True, start
        result = result + acc * (max_min - result)
        if below:
            if result > b[i]["l"]:
                first, below, result, max_min, acc = True, False, max(b[i]["h"], max_min), b[i]["l"], start
        else:
            if result < b[i]["h"]:
                first, below, result, max_min, acc = True, True, min(b[i]["l"], max_min), b[i]["h"], start
        if not first:
            if below:
                if b[i]["h"] > max_min:
                    max_min, acc = b[i]["h"], min(acc + inc, mx)
            elif b[i]["l"] < max_min:
                max_min, acc = b[i]["l"], min(acc + inc, mx)
        if below:
            result = min(result, b[i - 1]["l"])
            if i > 1:
                result = min(result, b[i - 2]["l"])
        else:
            result = max(result, b[i - 1]["h"])
            if i > 1:
                result = max(result, b[i - 2]["h"])
        out[i] = result
    return out


ref = {
    "sma20": ta.trend.SMAIndicator(c, 20).sma_indicator(),
    "ema20": ta.trend.EMAIndicator(c, 20).ema_indicator(),
    "ema50": ta.trend.EMAIndicator(c, 50).ema_indicator(),
    "wma20": ta.trend.WMAIndicator(c, 20).wma(),
    "hma20": wma(2 * wma(c, 10) - wma(c, 20), 4),
    "dema20": 2 * c.ewm(span=20, adjust=False).mean() - c.ewm(span=20, adjust=False).mean().ewm(span=20, adjust=False).mean(),
    "tema20": (lambda e1: 3 * e1 - 3 * e1.ewm(span=20, adjust=False).mean() + e1.ewm(span=20, adjust=False).mean().ewm(span=20, adjust=False).mean())(c.ewm(span=20, adjust=False).mean()),
    "vwma20": (c * v).rolling(20).sum() / v.rolling(20).sum(),
    "smma20": c.ewm(alpha=1 / 20, adjust=False).mean(),
    "kama": ta.momentum.KAMAIndicator(c, 10, 2, 30).kama(),
    "rsi": ta.momentum.RSIIndicator(c, 14).rsi(),
    "stoch_k": ta.momentum.StochasticOscillator(h, l, c, 14, 3).stoch_signal(),
    "stochrsi_k": ta.momentum.StochRSIIndicator(c, 14, 3, 3).stochrsi_k() * 100,
    "macd": ta.trend.MACD(c, 26, 12, 9).macd(),
    "macd_signal": ta.trend.MACD(c, 26, 12, 9).macd_signal(),
    "ppo": ta.momentum.PercentagePriceOscillator(c, 26, 12, 9).ppo(),
    "cci": ta.trend.CCIIndicator(h, l, c, 20, 0.015).cci(),
    "willr": ta.momentum.WilliamsRIndicator(h, l, c, 14).williams_r(),
    "roc": ta.momentum.ROCIndicator(c, 12).roc(),
    "mom": c - c.shift(10),
    "ao": ta.momentum.AwesomeOscillatorIndicator(h, l, 5, 34).awesome_oscillator(),
    "tsi": ta.momentum.TSIIndicator(c, 25, 13).tsi(),
    "uo": ta.momentum.UltimateOscillator(h, l, c, 7, 14, 28).ultimate_oscillator(),
    "cmo": (lambda d: 100 * (d.clip(lower=0).rolling(14).sum() - (-d).clip(lower=0).rolling(14).sum()) / d.abs().rolling(14).sum())(c.diff()),
    "trix": ta.trend.TRIXIndicator(c, 15).trix(),
    "bb_u": ta.volatility.BollingerBands(c, 20, 2).bollinger_hband(),
    "bb_l": ta.volatility.BollingerBands(c, 20, 2).bollinger_lband(),
    "bbpct": ta.volatility.BollingerBands(c, 20, 2).bollinger_pband(),
    "bbw": ta.volatility.BollingerBands(c, 20, 2).bollinger_wband(),
    "atr": ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range(),
    "stdev": c.rolling(20).std(ddof=0),
    "hv": np.log(c / c.shift(1)).rolling(20).std(ddof=0) * math.sqrt(252) * 100,
    "chop": 100 * np.log10(pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1).rolling(14).sum()
                           / (h.rolling(14).max() - l.rolling(14).min())) / math.log10(14),
    "dc_u": ta.volatility.DonchianChannel(h, l, c, 20).donchian_channel_hband(),
    "dc_l": ta.volatility.DonchianChannel(h, l, c, 20).donchian_channel_lband(),
    "kc_u": ta.volatility.KeltnerChannel(h, l, c, 20, 10, original_version=False, multiplier=2).keltner_channel_hband(),
    "adx": ta.trend.ADXIndicator(h, l, c, 14).adx(),
    "adx_pos": ta.trend.ADXIndicator(h, l, c, 14).adx_pos(),
    "vi_pos": ta.trend.VortexIndicator(h, l, c, 14).vortex_indicator_pos(),
    "vi_neg": ta.trend.VortexIndicator(h, l, c, 14).vortex_indicator_neg(),
    "psar": pd.Series(tv_sar(bars)),
    "ichi_conv": ta.trend.IchimokuIndicator(h, l, 9, 26, 52, visual=False).ichimoku_conversion_line(),
    "ichi_base": ta.trend.IchimokuIndicator(h, l, 9, 26, 52, visual=False).ichimoku_base_line(),
    "linreg": c.rolling(50).apply(lambda y: np.polyval(np.polyfit(np.arange(50), y, 1), 49), raw=True),
    "obv_diff": ta.volume.OnBalanceVolumeIndicator(c, v).on_balance_volume().diff(),
    "ad": ta.volume.AccDistIndexIndicator(h, l, c, v).acc_dist_index(),
    "cmf": ta.volume.ChaikinMoneyFlowIndicator(h, l, c, v, 20).chaikin_money_flow(),
    "mfi": ta.volume.MFIIndicator(h, l, c, v, 14).money_flow_index(),
    "fi": ta.volume.ForceIndexIndicator(c, v, 13).force_index(),
    "eom": ta.volume.EaseOfMovementIndicator(h, l, v, 14).sma_ease_of_movement(),
    "pvt_diff": ta.volume.VolumePriceTrendIndicator(c, v).volume_price_trend().diff(),
    "vo": 100 * (v.ewm(span=5, adjust=False).mean() - v.ewm(span=10, adjust=False).mean()) / v.ewm(span=10, adjust=False).mean(),
}
out = {"bars": bars, "ref": {k: [None if (x is None or (isinstance(x, float) and math.isnan(x))) else round(float(x), 10) for x in s] for k, s in ref.items()}}
Path(__file__).with_name("fixtures").joinpath("indicators_ref.json").write_text(json.dumps(out))
print("wrote", len(ref), "reference series")
