
"""Nifty sector momentum engine. Primary history source: official Nifty Indices site.
The Nifty Indices historical-data POST endpoint is undocumented and may change.
The program fails closed: it does not substitute a 52-week high for an ATH.
"""
from __future__ import annotations
import json, math, os, time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import requests

BASE = "https://www.niftyindices.com"
HIST_PAGE = BASE + "/reports/historical-data"
HIST_API = BASE + "/Backpage.aspx/getHistoricaldatatabletoString"
NSE_ARCHIVE = "https://archives.nseindia.com/content/indices/ind_close_all_{date}.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": BASE, "Referer": HIST_PAGE,
    "Content-Type": "application/json; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}
NEAR_ATH, MIN_SCORE = 10.0, 80.0
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def get_history(index_name: str, start="01-Jan-1995", end=None) -> pd.DataFrame:
    end = end or date.today().strftime("%d-%b-%Y")
    # Warm session/cookies from the official historical data page.
    page = SESSION.get(HIST_PAGE, timeout=30)
    page.raise_for_status()
    payload = {"cinfo": json.dumps({
        "name": index_name, "startDate": start, "endDate": end, "indexName": index_name
    })}
    last = None
    for attempt in range(3):
        try:
            r = SESSION.post(HIST_API, json=payload, timeout=45)
            r.raise_for_status()
            body = r.json()
            raw = body.get("d")
            if not raw:
                raise ValueError(f"Empty official history response for {index_name}")
            rows = json.loads(raw) if isinstance(raw, str) else raw
            df = pd.DataFrame(rows)
            date_col = next((c for c in ["HistoricalDate", "Date", "date"] if c in df.columns), None)
            close_col = next((c for c in ["CLOSE", "Close", "close"] if c in df.columns), None)
            if not date_col or not close_col:
                raise ValueError(f"Unexpected official history schema for {index_name}: {list(df.columns)}")
            out = pd.DataFrame({
                "date": pd.to_datetime(df[date_col], errors="coerce", dayfirst=True),
                "close": pd.to_numeric(df[close_col].astype(str).str.replace(",", ""), errors="coerce")
            }).dropna().drop_duplicates("date").sort_values("date")
            if len(out) < 260:
                raise ValueError(f"Insufficient history for {index_name}: {len(out)} rows")
            return out.reset_index(drop=True)
        except Exception as e:
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Could not retrieve verified history for {index_name}: {last}")

def rsi(series: pd.Series, period=14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    val = 100 - 100 / (1 + rs)
    return float(val.iloc[-1]) if pd.notna(val.iloc[-1]) else 50.0

def pct_rank(values: pd.Series) -> pd.Series:
    # Average percentile ranks; stable for ties.
    return values.rank(pct=True, method="average") * 100

def calc_metrics(name: str, df: pd.DataFrame) -> dict:
    c = df["close"].astype(float).reset_index(drop=True)
    if len(c) < 260:
        raise ValueError("At least 260 daily closes required")
    latest = float(c.iloc[-1])
    ath = float(c.max())
    ath_date = str(df.loc[c.idxmax(), "date"].date())
    distance = max(0.0, (ath - latest) / ath * 100.0)
    ret = {}
    for label, n in [("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252)]:
        ret[label] = float((latest / float(c.iloc[-n-1]) - 1) * 100)
    daily = c.pct_change().dropna()
    vol_1y = float(daily.tail(252).std(ddof=1) * math.sqrt(252) * 100)
    # Return/annualized volatility ratio, not a forecast.
    vol_adj_6m = ret["6m"] / vol_1y if vol_1y > 0 else 0.0
    vol_adj_12m = ret["12m"] / vol_1y if vol_1y > 0 else 0.0
    ma50 = float(c.tail(50).mean())
    ma200 = float(c.tail(200).mean())
    ma50_prev = float(c.iloc[-51:-1].mean())
    rs = rsi(c)
    return {
        "index": name, "as_of": str(df["date"].iloc[-1].date()),
        "current": round(latest, 2), "ath": round(ath, 2), "ath_date": ath_date,
        "distance_from_ath_pct": round(distance, 2),
        "return_1m_pct": round(ret["1m"], 2), "return_3m_pct": round(ret["3m"], 2),
        "return_6m_pct": round(ret["6m"], 2), "return_12m_pct": round(ret["12m"], 2),
        "volatility_1y_pct": round(vol_1y, 2),
        "vol_adj_6m": vol_adj_6m, "vol_adj_12m": vol_adj_12m,
        "rsi_14": round(rs, 1), "ma50": round(ma50, 2), "ma200": round(ma200, 2),
        "above_50dma": latest > ma50, "above_200dma": latest > ma200,
        "ma50_rising": ma50 > ma50_prev
    }

def build_scores(rows: list[dict]) -> list[dict]:
    d = pd.DataFrame(rows)
    # Percentile scores within the sector universe; positive direction is stronger.
    d["p1"] = pct_rank(d["return_1m_pct"])
    d["p3"] = pct_rank(d["return_3m_pct"])
    d["p6"] = pct_rank(d["vol_adj_6m"])
    d["p12"] = pct_rank(d["vol_adj_12m"])
    d["trend"] = (
        d["above_50dma"].astype(int) * 40 +
        d["above_200dma"].astype(int) * 40 +
        d["ma50_rising"].astype(int) * 20
    )
    # RSI: strongest confirmation in 50-70 band; penalise weak and overheated readings.
    d["rsi_score"] = (100 - (d["rsi_14"] - 60).abs() * 2.5).clip(0, 100)
    d["momentum_score"] = (
        d["p1"] * .10 + d["p3"] * .20 + d["p6"] * .25 +
        d["p12"] * .25 + d["trend"] * .15 + d["rsi_score"] * .05
    ).round(1)
    d["trend_score"] = d["trend"].round(1)
    d["shortlist"] = (
        (d["distance_from_ath_pct"] <= NEAR_ATH) &
        (d["momentum_score"] >= MIN_SCORE) &
        d["above_50dma"] & d["above_200dma"]
    )
    d = d.sort_values(["shortlist", "momentum_score", "distance_from_ath_pct"],
                      ascending=[False, False, True])
    return d.replace({np.nan: None}).to_dict(orient="records")

def fetch_nse_daily_archive(day: date) -> pd.DataFrame | None:
    """Independent official NSE close cross-check for the latest session."""
    url = NSE_ARCHIVE.format(date=day.strftime("%d%m%Y"))
    r = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    from io import StringIO
    df = pd.read_csv(StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    if not {"Index Name", "Closing Index Value"}.issubset(df.columns):
        raise ValueError("Unexpected NSE daily archive schema")
    return df


def cross_check(scored: list[dict], latest_date: str) -> None:
    """Compare latest close with NSE archive; mark each row VERIFIED / MISMATCH / UNVERIFIED."""
    try:
        arch = fetch_nse_daily_archive(date.fromisoformat(latest_date))
    except Exception as e:
        print("NSE cross-check unavailable:", e)
        arch = None
    lookup = {}
    if arch is not None:
        for _, r in arch.iterrows():
            v = pd.to_numeric(str(r["Closing Index Value"]).replace(",", ""), errors="coerce")
            if pd.notna(v):
                lookup[str(r["Index Name"]).strip().upper()] = float(v)
    for x in scored:
        ref = lookup.get(x["index"].upper())
        if ref is None:
            x["nse_check"] = "UNVERIFIED"
        else:
            x["nse_check"] = "VERIFIED" if abs(ref - x["current"]) / ref < 0.001 else "MISMATCH"

def main():
    global NEAR_ATH, MIN_SCORE
    cfg = json.load(open("config.json"))
    NEAR_ATH = float(cfg.get("near_ath_max_distance_pct", 10.0))
    MIN_SCORE = float(cfg.get("minimum_momentum_score", 80))
    rows, errors = [], []
    for name in cfg["indices"]:
        try:
            hist = get_history(name)
            rows.append(calc_metrics(name, hist))
            time.sleep(1.0)
        except Exception as e:
            errors.append({"index": name, "error": str(e)})
    if len(rows) < max(3, len(cfg["indices"]) // 2):
        raise RuntimeError(f"Only {len(rows)}/{len(cfg['indices'])} indices retrieved; refusing to publish a misleading report. Errors: {errors[:3]}")
    scored = build_scores(rows)
    # Cross-check latest date is consistent across series; stale data is never silently presented as current.
    dates = sorted({x["as_of"] for x in scored})
    latest_date = max(dates)
    for x in scored:
        x["data_status"] = "OK" if x["as_of"] == latest_date else "STALE"
    cross_check(scored, latest_date)
    result = {
        "generated_at_utc": datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_market_date": latest_date,
        "source": "Nifty Indices official historical data; NSE official daily index archive cross-check",
        "scoring_method": "Cross-sectional percentile composite: 1M 10%, 3M 20%, 6M volatility-adjusted 25%, 12M volatility-adjusted 25%, trend 15%, RSI 5%.",
        "universe_count": len(cfg["indices"]), "success_count": len(rows),
        "errors": errors, "results": scored,
        "shortlist": [x for x in scored if x["shortlist"]]
    }
    os.makedirs("docs/data", exist_ok=True)
    with open("docs/data/latest.json", "w") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    os.makedirs("docs/data/history", exist_ok=True)
    with open(f"docs/data/history/{latest_date}.json", "w") as f:
        json.dump(result, f, allow_nan=False)
    print(json.dumps({"market_date": latest_date, "success": len(rows), "errors": errors}, indent=2))
    if errors:
        # Partial results are visibly marked and workflow can notify via failure policy.
        print("WARNING: Partial universe. Do not treat rankings as complete.")

if __name__ == "__main__":
    main()
