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
import os
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
INTRADAY_FILE = ROOT / "intraday.json"
SCHEMA_VERSION = 5
HISTORY_KEEP_DAYS = 180

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

INDEXES = [
    {"market": "KOSPI", "name": "코스피", "yahoo": "^KS11", "naver": "KOSPI"},
    {"market": "KOSDAQ", "name": "코스닥", "yahoo": "^KQ11", "naver": "KOSDAQ"},
]

FX = {"name": "원/달러 환율", "yahoo": "KRW=X"}

# 전일 미국 시장 참고 지표. 3대 지수 + 공포지수 + 국채금리 + 업종 대표 ETF.
US_INDEXES = [
    {"market": "SPX", "name": "S&P 500", "yahoo": "^GSPC", "stooq": "^spx"},
    {"market": "NASDAQ", "name": "나스닥종합", "yahoo": "^IXIC", "stooq": "^ndq"},
    {"market": "DOW", "name": "다우존스", "yahoo": "^DJI", "stooq": "^dji"},
]
US_VIX = {"name": "VIX 변동성지수", "yahoo": "^VIX", "stooq": "^vix"}
US_YIELD10Y = {"name": "美 10년물 국채금리", "yahoo": "^TNX"}
US_SECTORS = [
    {"name": "반도체(SMH)", "yahoo": "SMH", "stooq": "smh.us"},
    {"name": "금융", "yahoo": "XLF", "stooq": "xlf.us"},
    {"name": "에너지", "yahoo": "XLE", "stooq": "xle.us"},
    {"name": "헬스케어", "yahoo": "XLV", "stooq": "xlv.us"},
    {"name": "소비재", "yahoo": "XLY", "stooq": "xly.us"},
    {"name": "커뮤니케이션", "yahoo": "XLC", "stooq": "xlc.us"},
]

# 분석 대상 40개 종목(코스피 20 · 코스닥 20). 종목을 바꾸려면 이 목록만 수정하면 된다.
UNIVERSE = [
    # --- KOSPI 20 ---
    {"code": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "반도체"},
    {"code": "000660", "name": "SK하이닉스", "market": "KOSPI", "sector": "반도체"},
    {"code": "000990", "name": "DB하이텍", "market": "KOSPI", "sector": "반도체"},
    {"code": "373220", "name": "LG에너지솔루션", "market": "KOSPI", "sector": "2차전지"},
    {"code": "006400", "name": "삼성SDI", "market": "KOSPI", "sector": "2차전지"},
    {"code": "003670", "name": "포스코퓨처엠", "market": "KOSPI", "sector": "2차전지"},
    {"code": "207940", "name": "삼성바이오로직스", "market": "KOSPI", "sector": "바이오"},
    {"code": "068270", "name": "셀트리온", "market": "KOSPI", "sector": "바이오"},
    {"code": "000100", "name": "유한양행", "market": "KOSPI", "sector": "바이오"},
    {"code": "005380", "name": "현대차", "market": "KOSPI", "sector": "자동차"},
    {"code": "000270", "name": "기아", "market": "KOSPI", "sector": "자동차"},
    {"code": "012330", "name": "현대모비스", "market": "KOSPI", "sector": "자동차"},
    {"code": "105560", "name": "KB금융", "market": "KOSPI", "sector": "금융"},
    {"code": "055550", "name": "신한지주", "market": "KOSPI", "sector": "금융"},
    {"code": "086790", "name": "하나금융지주", "market": "KOSPI", "sector": "금융"},
    {"code": "035420", "name": "NAVER", "market": "KOSPI", "sector": "인터넷"},
    {"code": "035720", "name": "카카오", "market": "KOSPI", "sector": "인터넷"},
    {"code": "377300", "name": "카카오페이", "market": "KOSPI", "sector": "인터넷"},
    {"code": "051910", "name": "LG화학", "market": "KOSPI", "sector": "화학·에너지"},
    {"code": "096770", "name": "SK이노베이션", "market": "KOSPI", "sector": "화학·에너지"},
    {"code": "010950", "name": "S-Oil", "market": "KOSPI", "sector": "화학·에너지"},
    {"code": "012450", "name": "한화에어로스페이스", "market": "KOSPI", "sector": "방산"},
    {"code": "064350", "name": "현대로템", "market": "KOSPI", "sector": "방산"},
    {"code": "079550", "name": "LIG넥스원", "market": "KOSPI", "sector": "방산"},
    {"code": "042660", "name": "한화오션", "market": "KOSPI", "sector": "조선"},
    {"code": "010140", "name": "삼성중공업", "market": "KOSPI", "sector": "조선"},
    {"code": "329180", "name": "HD현대중공업", "market": "KOSPI", "sector": "조선"},
    {"code": "034020", "name": "두산에너빌리티", "market": "KOSPI", "sector": "원자력·발전"},
    {"code": "051600", "name": "한전KPS", "market": "KOSPI", "sector": "원자력·발전"},
    {"code": "052690", "name": "한전기술", "market": "KOSPI", "sector": "원자력·발전"},
    {"code": "015760", "name": "한국전력", "market": "KOSPI", "sector": "유틸리티"},
    {"code": "036460", "name": "한국가스공사", "market": "KOSPI", "sector": "유틸리티"},
    {"code": "071320", "name": "한국지역난방공사", "market": "KOSPI", "sector": "유틸리티"},
    {"code": "003550", "name": "LG", "market": "KOSPI", "sector": "지주"},
    {"code": "028260", "name": "삼성물산", "market": "KOSPI", "sector": "지주"},
    {"code": "034730", "name": "SK", "market": "KOSPI", "sector": "지주"},
    # --- KOSDAQ (업종별 3개 이상) ---
    {"code": "247540", "name": "에코프로비엠", "market": "KOSDAQ", "sector": "2차전지"},
    {"code": "086520", "name": "에코프로", "market": "KOSDAQ", "sector": "2차전지"},
    {"code": "348370", "name": "엔켐", "market": "KOSDAQ", "sector": "2차전지"},
    {"code": "357780", "name": "솔브레인", "market": "KOSDAQ", "sector": "반도체 소재·장비"},
    {"code": "240810", "name": "원익IPS", "market": "KOSDAQ", "sector": "반도체 소재·장비"},
    {"code": "058470", "name": "리노공업", "market": "KOSDAQ", "sector": "반도체 소재·장비"},
    {"code": "095340", "name": "ISC", "market": "KOSDAQ", "sector": "반도체 소재·장비"},
    {"code": "039030", "name": "이오테크닉스", "market": "KOSDAQ", "sector": "반도체 소재·장비"},
    {"code": "067310", "name": "하나마이크론", "market": "KOSDAQ", "sector": "반도체 소재·장비"},
    {"code": "196170", "name": "알테오젠", "market": "KOSDAQ", "sector": "바이오"},
    {"code": "141080", "name": "리가켐바이오", "market": "KOSDAQ", "sector": "바이오"},
    {"code": "145020", "name": "휴젤", "market": "KOSDAQ", "sector": "바이오"},
    {"code": "214370", "name": "케어젠", "market": "KOSDAQ", "sector": "바이오"},
    {"code": "214150", "name": "클래시스", "market": "KOSDAQ", "sector": "바이오"},
    {"code": "328130", "name": "루닛", "market": "KOSDAQ", "sector": "바이오"},
    {"code": "035900", "name": "JYP Ent.", "market": "KOSDAQ", "sector": "엔터테인먼트"},
    {"code": "041510", "name": "에스엠", "market": "KOSDAQ", "sector": "엔터테인먼트"},
    {"code": "122870", "name": "와이지엔터테인먼트", "market": "KOSDAQ", "sector": "엔터테인먼트"},
    {"code": "263750", "name": "펄어비스", "market": "KOSDAQ", "sector": "게임"},
    {"code": "293490", "name": "카카오게임즈", "market": "KOSDAQ", "sector": "게임"},
    {"code": "078340", "name": "컴투스", "market": "KOSDAQ", "sector": "게임"},
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


def from_yahoo_intraday(symbol: str) -> list[dict]:
    """최근 약 5거래일의 60분봉. 진입구간·손절·목표선을 겹쳐 그리는 시간봉 차트용이다."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    res = session.get(url, params={"range": "5d", "interval": "60m"}, timeout=15)
    res.raise_for_status()
    result = (res.json().get("chart") or {}).get("result") or []
    if not result:
        raise ValueError("빈 응답")
    r = result[0]
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    stamps = r.get("timestamp") or []
    bars = []
    for i, ts in enumerate(stamps):
        c = (q.get("close") or [None] * len(stamps))[i]
        o = (q.get("open") or [None] * len(stamps))[i]
        h = (q.get("high") or [None] * len(stamps))[i]
        lo = (q.get("low") or [None] * len(stamps))[i]
        if c is None:
            continue
        bars.append({
            "t": datetime.fromtimestamp(ts, KST).isoformat(),
            "o": round(o, 2) if o else round(c, 2),
            "h": round(h, 2) if h else round(c, 2),
            "l": round(lo, 2) if lo else round(c, 2),
            "c": round(c, 2),
        })
    if len(bars) < 5:
        raise ValueError(f"시간봉 부족({len(bars)}개)")
    return bars



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


def from_stooq_symbol(symbol: str) -> dict | None:
    """Stooq CSV. symbol은 국가 접미사까지 포함한 전체 심볼(예: 005930.kr, smh.us, ^spx)."""
    res = session.get(f"https://stooq.com/q/d/l/?s={symbol.lower()}&i=d", timeout=15)
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


def from_stooq(code: str) -> dict | None:
    return from_stooq_symbol(f"{code}.kr")


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


def fetch_us(label: str, yahoo_symbol: str, stooq_symbol: str | None = None) -> dict | None:
    """미국 지수·ETF는 야후 → (있으면) Stooq 순으로 시도한다. 네이버는 해당 없음."""
    attempts = [("Yahoo", lambda: from_yahoo(yahoo_symbol))]
    if stooq_symbol:
        attempts.append(("Stooq", lambda: from_stooq_symbol(stooq_symbol)))
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


def week52_range(bars: list[dict], price: float) -> dict:
    """최근 약 1년(최대 252거래일) 구간의 최고·최저와 현재가 위치를 계산한다."""
    window = bars[-252:]
    highs = [b["high"] for b in window if b.get("high")] or [price]
    lows = [b["low"] for b in window if b.get("low")] or [price]
    hi, lo = max(highs), min(lows)
    span = max(hi - lo, 1e-9)
    return {
        "high": round(hi, 1), "low": round(lo, 1),
        "position": round((price - lo) / span, 4),          # 0=52주 최저, 1=52주 최고
        "from_high": round(price / hi - 1, 6),               # 고점 대비 (음수)
    }


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
    w52 = week52_range(bars, price)
    value_traded = price * (raw["volume_today"] or vols[-1])

    # 진입·손절·목표 구간
    entry_low = round(min(price, ma20 or price) * 0.985, 1)
    entry_high = round(max(price, (ma20 or price) * 1.01) * 1.005, 1)
    atr_stop = entry_low * (1 - atr * 1.5)
    ma_stop = (ma60 or 0) * 0.985
    # 60일선 바로 아래가 손절 자리로 더 가까우면 그쪽을 쓴다(손실 폭을 줄이기 위해서다).
    stop = round(max(atr_stop, ma_stop) if 0 < ma_stop < entry_low else atr_stop, 1)
    target1 = round(entry_high * (1 + atr * 4.0), 1)
    # 2차 목표는 1차까지의 보상폭을 추세 지속을 가정해 1.8배로 늘린 확장 목표다.
    target2 = round(entry_high + (target1 - entry_high) * 1.8, 1)
    risk = max(entry_high - stop, 1e-9)
    reward = max(target1 - entry_high, 0.0)
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
        reasons.append(f"최근 20일 수익률이 {market['name']} 지수보다 {rel * 100:.1f}%p 앞섭니다.")
    if vol_ratio >= 1.3:
        reasons.append(f"거래량이 평소의 {vol_ratio:.1f}배로 늘며 관심이 붙었습니다.")
    if pattern == "BREAKOUT":
        reasons.append("최근 20일 고점을 거래량과 함께 넘어섰습니다.")
        if w52["position"] >= 0.97:
            reasons.append("52주 신고가 부근에서 거래량을 동반한 돌파라 신뢰도가 더 높습니다.")
    elif pattern == "PULLBACK":
        reasons.append("상승 추세 중 20일선 부근까지 눌린 자리입니다.")
    if not reasons:
        reasons.append("현재 가격·거래량에서 뚜렷하게 좋은 신호는 찾지 못했습니다.")

    if r14 >= 70:
        risks.append(f"RSI가 {r14}로 과열 구간이라 단기 조정이 나올 수 있습니다.")
    if market["regime"] == "RISK_OFF":
        risks.append(f"{market['name']} 지수가 주요 이동평균선 아래여서 시장 전체가 불리합니다.")
    if rr < 1.5:
        risks.append(f"손익비가 {rr}로 낮아, 맞아도 얻는 것이 적고 틀리면 손실이 큽니다.")
    if ma60 and price < ma60:
        risks.append("60일선 아래라 중기 추세가 이미 꺾였을 수 있습니다.")
    if vol_ratio < 0.7:
        risks.append("거래량이 평소보다 적어 신호의 신뢰도가 낮습니다.")
    if w52["position"] >= 0.97 and pattern != "BREAKOUT":
        risks.append("52주 신고가 부근인데 거래량 동반 돌파는 아직 확인되지 않았습니다.")
    if w52["position"] <= 0.08:
        risks.append("52주 최저가 부근입니다. 반등이 아니라 하락이 이어지는 자리일 수 있습니다.")
    risks.append("이 판단은 가격과 거래량만 봅니다. 실적·공시·환율 충격은 반영되지 않습니다.")

    checklist = [
        "최근 공시와 실적 발표 일정을 확인하세요.",
        f"현재가가 진입 구간({entry_low:,.0f}~{entry_high:,.0f})에 들어와 있는지 보세요.",
        f"손절 기준 {stop:,.0f}을 미리 정해두고 지킬 수 있는지 생각하세요.",
        f"1차 목표 {target1:,.0f}에서 일부를 정리하고, 나머지는 2차 목표 {target2:,.0f}까지 지켜보는 방법도 흔히 씁니다.",
        f"52주 구간에서 {w52['position'] * 100:.0f}% 지점입니다. 고점·저점 부근이면 더 보수적으로 접근하세요.",
        "한 번에 전액이 아니라 나누어 접근하세요.",
    ]

    buy_bar = 85 if market["regime"] == "RISK_OFF" else 75
    tradeable = score >= buy_bar and rr >= 1.5 and vol_ratio >= 0.8 and pattern in ("BREAKOUT", "PULLBACK", "UPTREND")
    near_miss = (not tradeable) and (buy_bar - 8) <= score < buy_bar and rr >= 1.3 and pattern != "DOWNTREND"

    def buy_confidence() -> str:
        if score >= buy_bar + 10 and rr >= 2.0 and vol_ratio >= 1.2:
            return "높음"
        if score < buy_bar + 4 or vol_ratio < 1.0:
            return "낮음"
        return "보통"

    if pattern == "DOWNTREND" or (ma60 and price < ma60 and score < 45):
        action, label = "SELL_REVIEW", "신규 매수 제외"
        summary = "하락 추세가 확인되어 새로 사기에 적절하지 않습니다. 보유 중이라면 손절 기준을 점검하세요."
        confidence = "높음"
    elif tradeable and r14 < 75:
        action, label = "BUY_REVIEW", "매수 검토"
        confidence = buy_confidence()
        weak_note = " 다만 거래량이 뒷받침을 확실히 해주지는 않아 확신도는 낮게 봅니다." if confidence == "낮음" else ""
        summary = f"조건이 겹친 후보입니다. 다만 지금 사라는 뜻이 아니라 {entry_low:,.0f}~{entry_high:,.0f} 구간을 지켜보라는 뜻입니다.{weak_note}"
    elif near_miss:
        action, label = "WAIT", "관망·근접"
        summary = f"매수 기준({buy_bar}점)에 {buy_bar - score:.1f}점 못 미칩니다. 거의 다 왔지만 아직은 아닙니다. 다음 갱신에서 조건이 채워지는지 지켜보세요."
        confidence = "보통"
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
        "week52": w52, "value_traded": round(value_traded, 0),
        "entry_low": entry_low, "entry_high": entry_high, "stop": stop, "target1": target1, "target2": target2,
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


# ---------------------------------------------------------------- 참고 지표 계산


def fetch_fx(sample: bool) -> dict | None:
    """원/달러 환율. 참고용 배경지표라 실패해도 전체 갱신을 막지 않는다."""
    if sample:
        raw = sample_raw(4242, 1360.0, 0.0002)
    else:
        try:
            raw = from_yahoo(FX["yahoo"])
        except Exception as exc:  # noqa: BLE001
            note_error(FX["name"], f"{type(exc).__name__}: {exc}")
            return None
    closes = [b["close"] for b in raw["bars"]]
    prev = raw["prev_close"] or closes[-2]
    return {
        "name": FX["name"], "value": round(raw["price"], 2), "prev": round(prev, 2),
        "change_pct": round(raw["price"] / prev - 1, 6) if prev else 0.0,
        "series": [round(c, 2) for c in closes[-30:]],
        "quote_time": raw["quote_time"],
    }


def sector_ranking(stocks: list[dict]) -> list[dict]:
    """섹터별 평균 점수·상대강도로 지금 강한 업종을 가려낸다."""
    groups: dict[tuple, list[dict]] = {}
    for s in stocks:
        groups.setdefault((s["market"], s["sector"]), []).append(s)
    rows = []
    for (market, sector), items in groups.items():
        n = len(items)
        rows.append({
            "market": market, "sector": sector, "count": n,
            "avg_score": round(sum(i["score"] for i in items) / n, 1),
            "avg_relative": round(sum(i["relative_strength"] for i in items) / n, 6),
            "buy_count": sum(1 for i in items if i["decision"]["action"] == "BUY_REVIEW"),
        })
    rows.sort(key=lambda r: r["avg_score"], reverse=True)
    return rows


def market_breadth(stocks: list[dict]) -> dict:
    """오늘 상승·하락 종목 수 등 시장 폭 지표. 쏠림 없이 고르게 오르는지를 본다."""
    by_market: dict[str, dict] = {}
    for s in stocks:
        b = by_market.setdefault(s["market"], {"advancers": 0, "decliners": 0, "unchanged": 0, "above_ma20": 0, "total": 0})
        b["total"] += 1
        if s["change_pct"] > 0.0005:
            b["advancers"] += 1
        elif s["change_pct"] < -0.0005:
            b["decliners"] += 1
        else:
            b["unchanged"] += 1
        if s.get("ma20") and s["price"] > s["ma20"]:
            b["above_ma20"] += 1
    return by_market


def value_leaders(stocks: list[dict], n: int = 5) -> list[dict]:
    """거래대금 상위 종목. 점수와 무관하게 오늘 돈이 몰린 곳을 보여준다."""
    top = sorted(stocks, key=lambda s: s.get("value_traded", 0), reverse=True)[:n]
    return [{"code": s["code"], "name": s["name"], "market": s["market"],
              "value_traded": s["value_traded"], "change_pct": s["change_pct"]} for s in top]


def signal_shift(today_stocks: list[dict], history: dict) -> dict | None:
    """전일 기록과 비교해 매수·제외 신호가 늘었는지 줄었는지 알려준다."""
    records = [r for r in history.get("records", []) if r.get("age_days", 0) >= 1]
    if not records:
        return None
    prev = sorted(records, key=lambda r: r["date"])[-1]
    prev_counts: dict[str, int] = {}
    for item in prev["items"]:
        prev_counts[item["action"]] = prev_counts.get(item["action"], 0) + 1
    today_counts: dict[str, int] = {}
    for s in today_stocks:
        a = s["decision"]["action"]
        today_counts[a] = today_counts.get(a, 0) + 1
    return {
        "prev_date": prev["date"],
        "buy_delta": today_counts.get("BUY_REVIEW", 0) - prev_counts.get("BUY_REVIEW", 0),
        "sell_delta": today_counts.get("SELL_REVIEW", 0) - prev_counts.get("SELL_REVIEW", 0),
    }


# ---------------------------------------------------------------- 전일 미국 시장


def build_us_market(sample: bool) -> dict | None:
    """S&P500·나스닥·다우·VIX·10년물 금리·업종 ETF를 모아 전일 미국 시장을 요약한다.
    일부가 실패해도 얻은 것만으로 요약한다(코스피처럼 전체를 막지 않는다)."""
    indices, sectors = [], []

    for meta in US_INDEXES:
        raw = sample_raw(hash(meta["market"]) % 7777, 5200.0) if sample else fetch_us(meta["name"], meta["yahoo"], meta.get("stooq"))
        if raw:
            indices.append(build_market(meta, raw))

    vix = None
    raw = sample_raw(9911, 16.0, -0.001) if sample else fetch_us(US_VIX["name"], US_VIX["yahoo"], US_VIX.get("stooq"))
    if raw:
        closes = [b["close"] for b in raw["bars"]]
        prev = raw["prev_close"] or closes[-2]
        vix = {"value": round(raw["price"], 2), "change_pct": round(raw["price"] / prev - 1, 6) if prev else 0.0,
               "series": [round(c, 2) for c in closes[-30:]]}

    yield10y = None
    raw = sample_raw(7717, 42.0, 0.0) if sample else fetch_us(US_YIELD10Y["name"], US_YIELD10Y["yahoo"])
    if raw:
        closes = [b["close"] for b in raw["bars"]]
        prev = raw["prev_close"] or closes[-2]
        # ^TNX는 10배 스케일(예: 42.3 = 4.23%)로 제공된다.
        yield10y = {"value": round(raw["price"] / 10, 3), "change_pp": round((raw["price"] - prev) / 10, 3) if prev else 0.0}

    for meta in US_SECTORS:
        raw = sample_raw(hash(meta["name"]) % 5555, 150.0) if sample else fetch_us(meta["name"], meta["yahoo"], meta.get("stooq"))
        if raw:
            closes = [b["close"] for b in raw["bars"]]
            prev = raw["prev_close"] or closes[-2]
            sectors.append({"name": meta["name"], "change_pct": round(raw["price"] / prev - 1, 6) if prev else 0.0})

    if not indices:
        return None
    sectors.sort(key=lambda s: s["change_pct"], reverse=True)
    return {
        "indices": indices, "vix": vix, "yield10y": yield10y, "sectors": sectors,
        "briefing": build_us_briefing(indices, vix, yield10y, sectors),
        "quote_time": indices[0]["quote_time"],
    }


def build_us_briefing(indices: list[dict], vix: dict | None, yield10y: dict | None, sectors: list[dict]) -> dict:
    """계산된 수치만으로 조건부 문장을 만든다. 생성형 AI가 즉석에서 쓴 글이 아니라
    이 앱의 다른 판단과 같은 방식 — 규칙 기반 자동 요약이다."""
    by_market = {i["market"]: i for i in indices}
    spx, nasdaq, dow = by_market.get("SPX"), by_market.get("NASDAQ"), by_market.get("DOW")
    up_count = sum(1 for i in indices if i["change_pct"] > 0)
    direction = "상승" if up_count >= 2 else "하락" if up_count <= 1 and len(indices) >= 2 else "혼조"

    points = []
    if spx and nasdaq and dow:
        points.append(
            f"S&P500 {pct_kr(spx['change_pct'])}, 나스닥 {pct_kr(nasdaq['change_pct'])}, "
            f"다우 {pct_kr(dow['change_pct'])}로 3대 지수가 {direction} 마감했습니다."
        )
    if nasdaq and spx:
        gap = nasdaq["change_pct"] - spx["change_pct"]
        if abs(gap) >= 0.003:
            leader = "기술주 중심의 나스닥" if gap > 0 else "다우·S&P500 중심의 전통 업종"
            points.append(f"{leader}이 상대적으로 더 강했습니다.")

    if vix:
        level = "안정" if vix["value"] < 15 else "보통" if vix["value"] < 25 else "불안"
        points.append(f"VIX(공포지수)는 {vix['value']:.1f}로 {level} 구간입니다({pct_kr(vix['change_pct'])}).")

    if yield10y:
        if abs(yield10y["change_pp"]) >= 0.03:
            note = "성장주·고밸류 종목에는 부담" if yield10y["change_pp"] > 0 else "성장주에는 우호적"
            points.append(f"美 10년물 금리가 {yield10y['value']:.2f}%로 전일 대비 {yield10y['change_pp']:+.2f}%p 움직여 {note}일 수 있습니다.")
        else:
            points.append(f"美 10년물 금리는 {yield10y['value']:.2f}%로 큰 변화가 없었습니다.")

    if sectors:
        best, worst = sectors[0], sectors[-1]
        points.append(
            f"업종별로는 {josa(best['name'], '이', '가')} {pct_kr(best['change_pct'])}로 가장 강했고, "
            f"{josa(worst['name'], '이', '가')} {pct_kr(worst['change_pct'])}로 가장 약했습니다."
        )
        semi = next((s for s in sectors if "반도체" in s["name"]), None)
        if semi:
            if semi["change_pct"] >= 0.01:
                points.append("반도체 업종이 강했던 만큼, 삼성전자·SK하이닉스 등 코스피 반도체 대형주에 우호적인 분위기로 이어지는 경향이 있습니다.")
            elif semi["change_pct"] <= -0.01:
                points.append("반도체 업종이 약했던 만큼, 코스피 반도체 대형주도 출발이 무거울 수 있습니다.")

    if direction == "상승" and (not vix or vix["value"] < 20):
        headline = "미국 증시가 안정적으로 상승 마감했습니다"
    elif direction == "하락" and vix and vix["value"] >= 20:
        headline = "미국 증시가 하락하며 경계 심리가 커졌습니다"
    elif direction == "하락":
        headline = "미국 증시가 하락 마감했습니다"
    else:
        headline = "미국 증시는 방향을 정하지 못한 채 마감했습니다"

    points.append("코스피·코스닥은 이 흐름과 다르게 움직일 때도 많습니다. 참고 배경으로만 활용하세요.")
    return {"headline": headline, "points": points}


def josa(word: str, with_batchim: str, without_batchim: str) -> str:
    """받침 유무에 따라 조사를 붙인다. '반도체(SMH)'처럼 뒤에 괄호가 붙어도
    마지막 한글 음절을 찾아 판단한다. 한글이 없으면 받침 없는 형태를 기본으로 쓴다."""
    for ch in reversed(word):
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            has_batchim = (code - 0xAC00) % 28 != 0
            return word + (with_batchim if has_batchim else without_batchim)
    return word + without_batchim


def pct_kr(n: float) -> str:
    return f"{'+' if n >= 0 else ''}{n * 100:.2f}%"


# ---------------------------------------------------------------- 시간봉 차트(하루 2회)


def is_intraday_run(now: datetime) -> bool:
    """장 시작 전(08시대)과 장 마감 직후(15시 48분 이후)에만 시간봉을 갱신한다.
    57종목 전체의 시간봉을 20분마다 받으면 API 부담과 차단 위험이 커지기 때문이다."""
    return now.hour == 8 or (now.hour == 15 and now.minute >= 48)


def build_intraday(stocks: list[dict], sample: bool, now: datetime) -> dict:
    bars_by_code: dict[str, list[dict]] = {}
    for s in stocks:
        code, market = s["code"], s["market"]
        if sample:
            bars_by_code[code] = _sample_intraday(code, s["price"])
            continue
        yahoo_symbol = f"{code}.{'KS' if market == 'KOSPI' else 'KQ'}"
        try:
            bars_by_code[code] = from_yahoo_intraday(yahoo_symbol)
        except Exception as exc:  # noqa: BLE001 - 시간봉 실패는 표 갱신을 막지 않는다
            note_error(f"{s['name']} 시간봉", f"{type(exc).__name__}: {exc}")
        time.sleep(0.25)
    return {"schema_version": SCHEMA_VERSION, "generated_at": now.isoformat(), "sample": sample, "bars": bars_by_code}


def _sample_intraday(code: str, last_price: float) -> list[dict]:
    rnd = random.Random(hash(code) % 100000)
    now = datetime.now(KST)
    bars, price = [], last_price * 0.97
    for day_back in range(4, -1, -1):
        day = now - timedelta(days=day_back)
        if day.weekday() >= 5:
            continue
        for hour in range(9, 16):
            price *= 1 + rnd.gauss(0.0002, 0.006)
            ts = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            bars.append({"t": ts.isoformat(), "o": round(price, 1), "h": round(price * 1.004, 1),
                         "l": round(price * 0.996, 1), "c": round(price, 1)})
    if bars:
        bars[-1]["c"] = round(last_price, 1)
    return bars



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
    parser.add_argument("--intraday", action="store_true",
                        help="시각과 무관하게 시간봉을 강제로 갱신(수동 실행용)")
    args = parser.parse_args()
    now = datetime.now(KST)
    sample = args.sample
    # 수동 실행(workflow_dispatch)일 때는 몇 시든 시간봉을 함께 갱신한다.
    force_intraday = args.intraday or os.environ.get("KPR_FORCE_INTRADAY", "").strip().lower() in ("1", "true", "yes")

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

    fx = fetch_fx(sample)
    us_market = build_us_market(sample)
    history = update_history(stocks, now)
    shift = signal_shift(stocks, history)
    providers = sorted({s["provider"] for s in stocks} | {m["provider"] for m in markets})
    state = market_state(now)

    do_intraday = sample or force_intraday or is_intraday_run(now)
    if do_intraday:
        intraday = build_intraday(stocks, sample, now)
        INTRADAY_FILE.write_text(json.dumps(intraday, ensure_ascii=False, separators=(",", ":")), "utf-8")
        got = sum(1 for v in intraday["bars"].values() if v)
        print(f"시간봉 갱신: {got}/{len(stocks)}종목 → {INTRADAY_FILE.name}")

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
        "fx": fx,
        "us_market": us_market,
        "sector_ranking": sector_ranking(stocks),
        "breadth": market_breadth(stocks),
        "value_leaders": value_leaders(stocks),
        "signal_shift": shift,
        "history_summary": summarize_history(history),
        "errors": errors,
    }
    LIVE_FILE.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"완료: 지수 {len(markets)}개, 종목 {len(stocks)}개, 경고 {len(errors)}건 → {LIVE_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
