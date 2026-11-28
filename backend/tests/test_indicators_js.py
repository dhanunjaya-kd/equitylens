"""The chart's indicators (frontend/src/indicators.js) against reference values from the independent `ta` library
and plain pandas formulas (tests/fixtures/indicators_ref.json, built by tests/make_indicator_ref.py).
Compared on the last 200 of 700 candles, after every average has settled. Needs Node.js; skipped without it.
python tests/test_indicators_js.py"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).with_name("fixtures") / "indicators_ref.json"

JS = r"""
import { calc } from '%s'
import fs from 'fs'
const { bars } = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const b = bars
const [stK] = calc.stoch(b), [srK] = calc.stochrsi(b), [m, ms] = calc.macd(b), [pp] = calc.ppo(b)
const [bu, , bl] = calc.bb(b), [du, , dl] = calc.donchian(b), [ku] = calc.keltner(b), [adx, pdi] = calc.adx(b)
const [vp, vn] = calc.vortex(b), [tk, kj] = calc.ichimoku(b), [tsi] = calc.tsi(b)
const diff = (a) => a.map((x, i) => (i ? x - a[i - 1] : null))
const out = {
  sma20: calc.sma(b, 20), ema20: calc.ema(b, 20), ema50: calc.ema(b, 50), wma20: calc.wma(b, 20), hma20: calc.hma(b, 20),
  dema20: calc.dema(b, 20), tema20: calc.tema(b, 20), vwma20: calc.vwma(b, 20), smma20: calc.smma(b, 20), kama: calc.kama(b),
  rsi: calc.rsi(b), stoch_k: stK, stochrsi_k: srK, macd: m, macd_signal: ms, ppo: pp, cci: calc.cci(b), willr: calc.willr(b),
  roc: calc.roc(b), mom: calc.mom(b), ao: calc.ao(b), tsi, uo: calc.uo(b), cmo: calc.cmo(b), trix: calc.trix(b),
  bb_u: bu, bb_l: bl, bbpct: calc.bbpct(b), bbw: calc.bbw(b), atr: calc.atr(b), stdev: calc.stdev(b), hv: calc.hv(b), chop: calc.chop(b),
  dc_u: du, dc_l: dl, kc_u: ku, adx, adx_pos: pdi, vi_pos: vp, vi_neg: vn, psar: calc.psar(b), ichi_conv: tk, ichi_base: kj,
  linreg: calc.linreg(b), obv_diff: diff(calc.obv(b)), ad: calc.ad(b), cmf: calc.cmf(b), mfi: calc.mfi(b), fi: calc.fi(b), eom: calc.eom(b),
  pvt_diff: diff(calc.pvt(b)), vo: calc.vo(b),
}
process.stdout.write(JSON.stringify(out))
"""


def run_js():
    node = shutil.which("node")
    if not node:
        return None
    script = Path(__file__).with_name("_ind_check.mjs")
    script.write_text(JS % (ROOT / "frontend" / "src" / "indicators.js").as_uri())
    try:
        r = subprocess.run([node, str(script), str(FIX)], capture_output=True, text=True, timeout=60)
    finally:
        script.unlink(missing_ok=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


def test_indicators_match_reference():
    got = run_js()
    if got is None:
        print("SKIP: Node.js not installed")
        return
    ref = json.loads(FIX.read_text())["ref"]
    bad = []
    for k, want in ref.items():
        mine = got[k]
        for i in range(500, 700):
            a, b = mine[i], want[i]
            if b is None:
                continue
            tol = 1e-6 + 1e-4 * abs(b)
            if a is None or abs(a - b) > tol:
                bad.append(f"{k}[{i}]: app {a} vs reference {b}")
                break
    assert not bad, "\n".join(bad)


if __name__ == "__main__":
    try:
        test_indicators_match_reference()
        print("PASS test_indicators_match_reference")
    except AssertionError as e:
        print("FAIL", e)
        sys.exit(1)
