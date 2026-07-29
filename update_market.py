#!/usr/bin/env python3
"""K-Pattern Radar 시세 수집 · 지표 계산 · 판단 생성 스크립트.

무료 공개 시세만 사용한다. 실행하면 live-data.json 과 history.json 을 갱신한다.
python update_market.py            정상 수집
python update_market.py --sample   네트워크 없이 샘플 데이터 생성(화면 점검용)
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
LIVE_FILE = ROOT / "live-data.json"
HISTORY_FILE = ROOT / "history.json"
SCHEMA_VERSION = 3
HISTORY_KEEP_DAYS = 180

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

INDEXES = [
    {"market": "KOSPI", "name": "코스피", "yahoo": "^KS11", "naver": "KOSPI"},
    {"market": "KOSDAQ", "name": "코스닥", "yahoo": "^KQ11", "naver": "KOSDAQ"},
]

# 분석 대상 20개 대표 종목. 종목을 바꾸려면 이 목록만 수정하면 된다.
UNIVERSE = [
    {"code": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "반도체"},
    {"code": "000660", "name": "SK하이닉스", "market": "KOSPI", "sector": "반도체"},
    {"code": "373220", "name": "LG에너지솔루션", "market": "KOSPI", "sector": "2차전지"},
    {"code": "207940", "name": "삼성바이오로직스", "market": "KOSPI", "sector": "바이오"},
    {"code": "005380", "name": "현대차", "market": "KOSPI", "sector": "자동차"},
    {"code": "000270", "name": "기아", "market": "KOSPI", "sector": "자동차"},
    {"code": "068270", "name": "셀트리온", "market": "KOSPI", "sector": "바이오"},
    {"code": "105560", "name": "KB금융", "market": "KOSPI", "sector": "금융"},
    {"code": "055550", "name": "신한지주", "market": "KOSPI", "sector": "금융"},
    {"code": "035420", "name": "NAVER", "market": "KOSPI", "sector": "인터넷"},
    {"code": "035720", "name": "카카오", "market": "KOSPI", "sector": "인터넷"},
    {"code": "051910", "name": "LG화학", "market": "KOSPI", "sector": "화학"},
    {"code": "012450", "name": "한화에어로스페이스", "market": "KOSPI", "sector": "방산"},
    {"code": "034020", "name": "두산에너빌리티", "market": "KOSPI", "sector": "원자력·발전"},
    {"code": "042660", "name": "한화오션", "market": "KOSPI", "sector": "조선"},
    {"code": "247540", "name": "에코프로비엠", "market": "KOSDAQ", "sector": "2차전지"},
    {"code": "086520", "name": "에코프로", "market": "KOSDAQ", "sector": "2차전지"},
    {"code": "196170", "name": "알테오젠", "market": "KOSDAQ", "sector": "바이오"},
    {"code": "058470", "name": "리노공업", "market": "KOSDAQ", "sector": "반도체부품"},
    {"code": "028300", "name": "HLB", "market": "KOSDAQ", "sector": "바이오"},
]

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://finance.naver.com/",
})
errors: list[dict] = []


def note_error(item: str, message: str) -> None:
    errors.append({"item": item, "message": message[:180]})
    print(f"  ! {item}: {message[:180]}", file=sys.stderr)


# ---------------------------------------------------------------- 시세 수집


def _clean(bars: list[dict]) -> list[dict]:
    out = [b for b in bars if b.get("close")]
    out.sort(key=lambda b: b["date"])
    return out


def from_yahoo(symbol: str) -> dict | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    res = session.get(url, params={"range": "1y", "interval": "1d"}, timeout=15)
    res.raise_for_status()
    result = (res.json().get("chart") or {}).get("result") or []
    if not result:
        raise ValueError("빈 응답")
    r = result[0]
    meta, q = r.get("meta", {}), (r.get("indicators", {}).get("quote") or [{}])[0]
    stamps = r.get("timestamp") or []
    bars = []
    for i, ts in enumerate(stamps):
        bars.append({
            "date": datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d"),
            "close": q.get("close", [None] * len(stamps))[i],
            "volume": q.get("volume", [None] * len(stamps))[i] or 0,
            "high": q.get("high", [None] * len(stamps))[i],
            "low": q.get("low", [None] * len(stamps))[i],
        })
    bars = _clean(bars)
    if len(bars) < 130:
        raise ValueError(f"일봉 부족({len(bars)}일)")
    price = meta.get("regularMarketPrice") or bars[-1]["close"]
    quote_ts = meta.get("regularMarketTime")
    return {
        "bars": bars,
        "price": float(price),
        "prev_close": float(meta.get("chartPreviousClose") or meta.get("previousClose") or bars[-2]["close"]),
        "quote_time": datetime.fromtimestamp(quote_ts, KST).isoformat() if quote_ts else bars[-1]["date"],
        "volume_today": bars[-1]["volume"],
        "provider": "Yahoo Finance",
    }


def from_naver(symbol: str) -> dict | None:
    """네이버의 비공식 공개 JSON. 종목코드(예: 005930)와 지수 심볼(KOSPI, KOSDAQ) 모두 지원한다."""
    end = datetime.now(KST).strftime("%Y%m%d")
    start = (datetime.now(KST) - timedelta(days=560)).strftime("%Y%m%d")
    url = "https://api.finance.naver.com/siseJson.naver"
    res = session.get(
        url,
        params={"symbol": symbol, "requestType": 1, "startTime": start, "endTime": end, "timeframe": "day"},
        timeout=15,
    )
    res.raise_for_status()
    text = res.text.strip()
    if not text or text[0] not in "[{":
        raise ValueError(f"예상치 못한 응답(앞 40자): {text[:40]!r}")
    rows = json.loads(text.replace("'", '"'))
    bars = []
    for row in rows[1:]:
        try:
            bars.append({
                "date": f"{row[0][:4]}-{row[0][4:6]}-{row[0][6:8]}",
                "close": float(row[4]),
                "volume": float(row[5]),
                "high": float(row[2]),
                "low": float(row[3]),
            })
        except (IndexError, TypeError, ValueError):
            continue
    bars = _clean(bars)
    if len(bars) < 130:
        raise ValueError(f"일봉 부족({len(bars)}일)")
    return {
        "bars": bars,
        "price": bars[-1]["close"],
        "prev_close": bars[-2]["close"],
        "quote_time": bars[-1]["date"],
        "volume_today": bars[-1]["volume"],
        "provider": "네이버 금융",
    }


def from_stooq(code: str) -> dict | None:
    res = session.get(f"https://stooq.com/q/d/l/?s={code.lower()}.kr&i=d", timeout=15)
    res.raise_for_status()
    lines = res.text.strip().splitlines()
    if len(lines) < 130 or not lines[0].lower().startswith("date"):
        raise ValueError("CSV 형식 아님")
    bars = []
    for line in lines[1:]:
        p = line.split(",")
        try:
            bars.append({
                "date": p[0], "close": float(p[4]), "volume": float(p[5]),
                "high": float(p[2]), "low": float(p[3]),
            })
        except (IndexError, ValueError):
            continue
    bars = _clean(bars)
    if len(bars) < 130:
        raise ValueError(f"일봉 부족({len(bars)}일)")
    return {
        "bars": bars,
        "price": bars[-1]["close"],
        "prev_close": bars[-2]["close"],
        "quote_time": bars[-1]["date"],
        "volume_today": bars[-1]["volume"],
        "provider": "Stooq",
    }


def fetch_index(label: str, meta: dict) -> dict | None:
    """지수는 네이버(symbol=KOSPI/KOSDAQ) → 야후 순으로 시도한다.
    GitHub Actions 서버 IP가 야후에 막히는 경우가 잦아 네이버를 먼저 쓴다."""
    attempts = [("Naver", lambda: from_naver(meta["naver"])), ("Yahoo", lambda: from_yahoo(meta["yahoo"]))]
    return _try_all(label, attempts)


def fetch_stock(label: str, code: str, yahoo_symbol: str) -> dict | None:
    """종목은 네이버 → Stooq → 야후 순으로 시도한다."""
    attempts = [
        ("Naver", lambda: from_naver(code)),
        ("Stooq", lambda: from_stooq(code)),
        ("Yahoo", lambda: from_yahoo(yahoo_symbol)),
    ]
    return _try_all(label, attempts)


def _try_all(label: str, attempts: list[tuple[str, object]]) -> dict | None:
    fails = []
    for source, fn in attempts:
        source_error = ""
        for retry in range(2):
            try:
                data = fn()
                if data:
                    if fails:
                        print(f"  · {label}: {' / '.join(fails)} 실패 후 {source}로 수집 성공", file=sys.stderr)
                    return data
            except Exception as exc:  # noqa: BLE001 - 어떤 실패든 다음 소스로 넘어간다
                source_error = f"{source} {type(exc).__name__}: {exc}"
                time.sleep(1.0 * (retry + 1))
        fails.append(source_error)
    note_error(label, " · ".join(fails) or "알 수 없는 실패")
    return None


# ---------------------------------------------------------------- 지표 계산


def sma(values: list[float], n: int) -> float | None:
    return sum(values[-n:]) / n if len(values) >= n else None


def rsi(values: list[float], n: int = 14) -> float:
    if len(values) < n + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(-n, 0):
        diff = values[i] - values[i - 1]
        gains += max(diff, 0.0)
        losses += max(-diff, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return round(100 - 100 / (1 + rs), 1)


def atr_ratio(bars: list[dict], n: int = 14) -> float:
    rows = bars[-n:]
    spans = [(b["high"] - b["low"]) / b["close"] for b in rows if b.get("high") and b.get("low") and b["close"]]
    return sum(spans) / len(spans) if spans else 0.03


def regime_of(price: float, ma20, ma60, ma120) -> str:
    mas = [m for m in (ma20, ma60, ma120) if m]
    if not mas:
        return "NEUTRAL"
    above = sum(1 for m in mas if price > m)
    if above == len(mas) and (not ma20 or not ma60 or ma20 >= ma60):
        return "RISK_ON"
    if above == 0:
        return "RISK_OFF"
    return "NEUTRAL"


def build_market(meta: dict, raw: dict) -> dict:
    closes = [b["close"] for b in raw["bars"]]
    price = raw["price"]
    ma20, ma60, ma120 = sma(closes, 20), sma(closes, 60), sma(closes, 120)
    prev = raw["prev_close"] or closes[-2]
    ret20 = price / closes[-21] - 1 if len(closes) > 21 else 0.0
    return {
        "market": meta["market"],
        "name": meta["name"],
        "close": round(price, 2),
        "prev_close": round(prev, 2),
        "change": round(price - prev, 2),
        "change_pct": round(price / prev - 1, 6) if prev else 0.0,
        "ma20": round(ma20, 2) if ma20 else None,
        "ma60": round(ma60, 2) if ma60 else None,
        "ma120": round(ma120, 2) if ma120 else None,
        "return_20d": round(ret20, 6),
        "regime": regime_of(price, ma20, ma60, ma120),
        "quote_time": raw["quote_time"],
        "series": [round(c, 2) for c in closes[-30:]],
        "provider": raw["provider"],
    }


def detect_pattern(price: float, closes: list[float], ma20, ma60, vol_ratio: float) -> tuple[str, str]:
    high20 = max(closes[-21:-1]) if len(closes) > 21 else price
    if price >= high20 and vol_ratio >= 1.2:
        return "BREAKOUT", "TRIGGERED"
    if ma20 and ma60 and ma20 > ma60 and price > ma60 and price <= ma20 * 1.02:
        return "PULLBACK", "RETEST"
    if ma20 and ma60 and price > ma20 > ma60:
        return "UPTREND", "FORMING"
    if ma20 and ma60 and price < ma20 < ma60:
        return "DOWNTREND", "FAILED"
    return "NO_CLEAR_SIGNAL", "WATCH"


def build_stock(meta: dict, raw: dict, market: dict) -> dict:
    bars = raw["bars"]
    closes = [b["close"] for b in bars]
    vols = [b["volume"] or 0 for b in bars]
    price = raw["price"]
    prev = raw["prev_close"] or closes[-2]
    ma20, ma60, ma120 = sma(closes, 20), sma(closes, 60), sma(closes, 120)
    r14 = rsi(closes)
    ret20 = price / closes[-21] - 1 if len(closes) > 21 else 0.0
    avg_vol = sma(vols[:-1], 20) or 0
    vol_ratio = (raw["volume_today"] or vols[-1]) / avg_vol if avg_vol else 1.0
    rel = ret20 - market["return_20d"]
    pattern, status = detect_pattern(price, closes, ma20, ma60, vol_ratio)
    atr = min(max(atr_ratio(bars), 0.015), 0.06)

    # 진입·손절·목표 구간
    entry_low = round(min(price, ma20 or price) * 0.985, 1)
    entry_high = round(max(price, (ma20 or price) * 1.01) * 1.005, 1)
    atr_stop = entry_low * (1 - atr * 1.5)
    ma_stop = (ma60 or 0) * 0.985
    # 60일선 바로 아래가 손절 자리로 더 가까우면 그쪽을 쓴다(손실 폭을 줄이기 위해서다).
    stop = round(max(atr_stop, ma_stop) if 0 < ma_stop < entry_low else atr_stop, 1)
    target = round(entry_high * (1 + atr * 4.0), 1)
    risk = max(entry_high - stop, 1e-9)
    reward = max(target - entry_high, 0.0)
    rr = round(reward / risk, 2)

    # 점수 (합계 100점)
    trend = 0.0
    if ma20 and price > ma20:
        trend += 9
    if ma60 and price > ma60:
        trend += 8
    if ma120 and price > ma120:
        trend += 4
    if ma20 and ma60 and ma20 > ma60:
        trend += 4

    momentum = min(12.0, max(0.0, ret20 * 100)) if ret20 > 0 else 0.0
    if 45 <= r14 <= 68:
        momentum += 8
    elif 35 <= r14 < 45 or 68 < r14 <= 74:
        momentum += 4
    momentum = min(momentum, 20.0)

    relative = min(15.0, max(0.0, 7.5 + rel * 60))
    volume = min(15.0, max(0.0, (vol_ratio - 0.6) * 12)) if vol_ratio else 0.0
    pattern_score = {"BREAKOUT": 15, "PULLBACK": 12, "UPTREND": 9, "NO_CLEAR_SIGNAL": 4, "DOWNTREND": 0}[pattern]
    risk_score = min(10.0, max(0.0, (rr - 0.8) * 6))

    components = {
        "trend": round(trend, 1), "momentum": round(momentum, 1), "relative": round(relative, 1),
        "volume": round(volume, 1), "pattern": float(pattern_score), "risk": round(risk_score, 1),
    }
    score = round(sum(components.values()), 1)
    grade = "S" if score >= 85 else "A" if score >= 75 else "B" if score >= 60 else "C" if score >= 45 else "D"

    reasons, risks, checklist = [], [], []
    if ma20 and ma60 and price > ma20 > ma60:
        reasons.append("현재가가 20일선과 60일선 위에 있어 중기 추세가 살아 있습니다.")
    if rel > 0:
        reasons.append(f"최근 20일 수익률이 {market['market']} 지수보다 {rel * 100:.1f}%p 앞섭니다.")
    if vol_ratio >= 1.3:
        reasons.append(f"거래량이 평소의 {vol_ratio:.1f}배로 늘며 관심이 붙었습니다.")
    if pattern == "BREAKOUT":
        reasons.append("최근 20일 고점을 거래량과 함께 넘어섰습니다.")
    elif pattern == "PULLBACK":
        reasons.append("상승 추세 중 20일선 부근까지 눌린 자리입니다.")
    if not reasons:
        reasons.append("현재 가격·거래량에서 뚜렷하게 좋은 신호는 찾지 못했습니다.")

    if r14 >= 70:
        risks.append(f"RSI가 {r14}로 과열 구간이라 단기 조정이 나올 수 있습니다.")
    if market["regime"] == "RISK_OFF":
        risks.append(f"{market['market']} 지수가 주요 이동평균선 아래여서 시장 전체가 불리합니다.")
    if rr < 1.5:
        risks.append(f"손익비가 {rr}로 낮아, 맞아도 얻는 것이 적고 틀리면 손실이 큽니다.")
    if ma60 and price < ma60:
        risks.append("60일선 아래라 중기 추세가 이미 꺾였을 수 있습니다.")
    if vol_ratio < 0.7:
        risks.append("거래량이 평소보다 적어 신호의 신뢰도가 낮습니다.")
    risks.append("이 판단은 가격과 거래량만 봅니다. 실적·공시·환율 충격은 반영되지 않습니다.")

    checklist = [
        "최근 공시와 실적 발표 일정을 확인하세요.",
        f"현재가가 진입 구간({entry_low:,.0f}~{entry_high:,.0f})에 들어와 있는지 보세요.",
        f"손절 기준 {stop:,.0f}을 미리 정해두고 지킬 수 있는지 생각하세요.",
        "한 번에 전액이 아니라 나누어 접근하세요.",
    ]

    tradeable = score >= 75 and rr >= 1.5 and vol_ratio >= 0.8 and pattern in ("BREAKOUT", "PULLBACK", "UPTREND")
    if market["regime"] == "RISK_OFF":
        tradeable = tradeable and score >= 85

    if pattern == "DOWNTREND" or (ma60 and price < ma60 and score < 45):
        action, label = "SELL_REVIEW", "신규 매수 제외"
        summary = "하락 추세가 확인되어 새로 사기에 적절하지 않습니다. 보유 중이라면 손절 기준을 점검하세요."
        confidence = "높음"
    elif tradeable and r14 < 75:
        action, label = "BUY_REVIEW", "매수 검토"
        summary = f"조건이 겹친 후보입니다. 다만 지금 사라는 뜻이 아니라 {entry_low:,.0f}~{entry_high:,.0f} 구간을 지켜보라는 뜻입니다."
        confidence = "보통" if score < 85 else "높음"
    else:
        action, label = "WAIT", "관망"
        summary = "근거가 충분히 모이지 않았습니다. 기다리는 것도 돈을 지키는 투자 행동입니다."
        confidence = "보통"

    return {
        "code": meta["code"], "name": meta["name"], "market": meta["market"], "sector": meta["sector"],
        "price": round(price, 1), "prev_close": round(prev, 1),
        "change_pct": round(price / prev - 1, 6) if prev else 0.0,
        "ma20": round(ma20, 1) if ma20 else None,
        "ma60": round(ma60, 1) if ma60 else None,
        "ma120": round(ma120, 1) if ma120 else None,
        "rsi14": r14, "return_20d": round(ret20, 6), "relative_strength": round(rel, 6),
        "volume_ratio": round(vol_ratio, 2), "pattern": pattern, "status": status,
        "entry_low": entry_low, "entry_high": entry_high, "stop": stop, "target": target,
        "risk_reward": rr, "score": score, "grade": grade, "components": components,
        "quote_time": raw["quote_time"], "provider": raw["provider"],
        "series": [round(c, 1) for c in closes[-30:]],
        "decision": {
            "action": action, "label": label, "summary": summary, "confidence": confidence,
            "reasons": reasons[:4], "risks": risks[:4], "checklist": checklist,
        },
    }


# ---------------------------------------------------------------- 판단 기록


def update_history(stocks: list[dict], now: datetime) -> dict:
    try:
        history = json.loads(HISTORY_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        history = {"schema_version": SCHEMA_VERSION, "records": []}
    records = history.get("records", [])
    today = now.strftime("%Y-%m-%d")
    prices = {s["code"]: s["price"] for s in stocks}

    snapshot = {
        "date": today,
        "items": [
            {"code": s["code"], "name": s["name"], "action": s["decision"]["action"],
             "score": s["score"], "price": s["price"]}
            for s in stocks
        ],
    }
    records = [r for r in records if r.get("date") != today] + [snapshot]
    records.sort(key=lambda r: r["date"])
    cutoff = (now - timedelta(days=HISTORY_KEEP_DAYS)).strftime("%Y-%m-%d")
    records = [r for r in records if r["date"] >= cutoff]

    # 과거 판단의 이후 성과를 현재가 기준으로 다시 계산한다.
    for record in records:
        age = (now.date() - datetime.strptime(record["date"], "%Y-%m-%d").date()).days
        for item in record["items"]:
            now_price = prices.get(item["code"])
            if now_price and item.get("price"):
                item["forward_return"] = round(now_price / item["price"] - 1, 6)
        record["age_days"] = age

    history["schema_version"] = SCHEMA_VERSION
    history["records"] = records
    history["updated_at"] = now.isoformat()
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return history


def summarize_history(history: dict) -> dict:
    """14일 이상 지난 '매수 검토' 판단들의 이후 수익률을 집계한다."""
    graded = []
    for record in history.get("records", []):
        if record.get("age_days", 0) < 14:
            continue
        for item in record["items"]:
            if item.get("action") == "BUY_REVIEW" and "forward_return" in item:
                graded.append(item["forward_return"])
    if not graded:
        return {"count": 0, "note": "판단 기록이 14일 이상 쌓이면 이 자리에 성과가 표시됩니다."}
    wins = sum(1 for g in graded if g > 0)
    return {
        "count": len(graded),
        "win_rate": round(wins / len(graded), 4),
        "avg_return": round(sum(graded) / len(graded), 6),
        "best": round(max(graded), 6),
        "worst": round(min(graded), 6),
        "note": "매수 검토 판단 이후 현재까지의 단순 수익률입니다. 진입 시점·수수료·세금은 반영되지 않았습니다.",
    }


# ---------------------------------------------------------------- 샘플 생성


def sample_raw(seed: int, base: float, drift: float = 0.0) -> dict:
    rnd = random.Random(seed)
    closes, price = [], base
    for _ in range(260):
        price *= 1 + rnd.gauss(0.0004 + drift, 0.016)
        closes.append(round(price, 1))
    today = datetime.now(KST)
    bars = []
    for i, c in enumerate(closes):
        day = today - timedelta(days=len(closes) - i)
        bars.append({"date": day.strftime("%Y-%m-%d"), "close": c, "volume": rnd.randint(300000, 9000000),
                     "high": round(c * 1.012, 1), "low": round(c * 0.988, 1)})
    return {"bars": bars, "price": closes[-1], "prev_close": closes[-2],
            "quote_time": today.isoformat(), "volume_today": bars[-1]["volume"], "provider": "샘플"}


# ---------------------------------------------------------------- 메인


def market_state(now: datetime) -> str:
    if now.weekday() >= 5:
        return "CLOSED"
    minutes = now.hour * 60 + now.minute
    return "OPEN" if 9 * 60 <= minutes <= 15 * 60 + 30 else "CLOSED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="네트워크 없이 샘플 데이터 생성")
    args = parser.parse_args()
    now = datetime.now(KST)
    sample = args.sample

    markets, stocks = [], []
    for meta in INDEXES:
        raw = sample_raw(hash(meta["market"]) % 9999, 2600.0) if sample else fetch_index(meta["name"], meta)
        if not raw:
            print(f"지수 {meta['name']} 수집 실패. 기존 파일을 유지하고 종료합니다.", file=sys.stderr)
            return 1
        markets.append(build_market(meta, raw))

    by_market = {m["market"]: m for m in markets}
    for i, meta in enumerate(UNIVERSE):
        if sample:
            raw = sample_raw(i * 37 + 5, 20000 + i * 4200, 0.0016 if i % 3 == 0 else -0.0008 if i % 3 == 1 else 0.0)
        else:
            yahoo_symbol = f"{meta['code']}.{'KS' if meta['market'] == 'KOSPI' else 'KQ'}"
            raw = fetch_stock(meta["name"], meta["code"], yahoo_symbol)
        if not raw:
            continue
        stocks.append(build_stock(meta, raw, by_market[meta["market"]]))
        if not sample:
            time.sleep(0.4)

    if len(stocks) < len(UNIVERSE) * 0.6:
        print(f"종목 수집이 {len(stocks)}개뿐이라 파일을 갱신하지 않습니다.", file=sys.stderr)
        return 1

    history = update_history(stocks, now)
    providers = sorted({s["provider"] for s in stocks} | {m["provider"] for m in markets})
    state = market_state(now)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "data_as_of": max(m["quote_time"] for m in markets),
        "market_state": state,
        "sample": sample,
        "source": {
            "provider": " · ".join(providers),
            "latency": "샘플 데이터" if sample else "무료 공개 시세 · 최대 20분 지연될 수 있음",
            "note": "거래소 실시간 시세가 아니라 무료 공개 지연 시세입니다.",
        },
        "markets": markets,
        "stocks": stocks,
        "history_summary": summarize_history(history),
        "errors": errors,
    }
    LIVE_FILE.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"완료: 지수 {len(markets)}개, 종목 {len(stocks)}개, 경고 {len(errors)}건 → {LIVE_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
