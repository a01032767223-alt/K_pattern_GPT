#!/usr/bin/env python3
"""Build a compact, explainable Korean-market snapshot for the static app.

Yahoo Finance is used as a zero-configuration delayed-data fallback. If
KIS_APP_KEY and KIS_APP_SECRET are available, current stock quotes are
overridden with the official Korea Investment & Securities Open API.
No order endpoint is called.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import os
import statistics
import time
import urllib.parse
import urllib.request

SEOUL_OFFSET = timezone(timedelta(hours=9))
OUTPUT = Path(__file__).with_name("live-data.json")

UNIVERSE = [
    ("005930", "삼성전자", "KOSPI", "반도체", "005930.KS"),
    ("000660", "SK하이닉스", "KOSPI", "반도체", "000660.KS"),
    ("373220", "LG에너지솔루션", "KOSPI", "2차전지", "373220.KS"),
    ("207940", "삼성바이오로직스", "KOSPI", "바이오", "207940.KS"),
    ("005380", "현대차", "KOSPI", "자동차", "005380.KS"),
    ("000270", "기아", "KOSPI", "자동차", "000270.KS"),
    ("035420", "NAVER", "KOSPI", "인터넷", "035420.KS"),
    ("035720", "카카오", "KOSPI", "인터넷", "035720.KS"),
    ("068270", "셀트리온", "KOSPI", "바이오", "068270.KS"),
    ("005490", "POSCO홀딩스", "KOSPI", "소재", "005490.KS"),
    ("105560", "KB금융", "KOSPI", "금융", "105560.KS"),
    ("055550", "신한지주", "KOSPI", "금융", "055550.KS"),
    ("012450", "한화에어로스페이스", "KOSPI", "방산", "012450.KS"),
    ("034020", "두산에너빌리티", "KOSPI", "에너지", "034020.KS"),
    ("196170", "알테오젠", "KOSDAQ", "바이오", "196170.KQ"),
    ("247540", "에코프로비엠", "KOSDAQ", "2차전지", "247540.KQ"),
    ("028300", "HLB", "KOSDAQ", "바이오", "028300.KQ"),
    ("035900", "JYP Ent.", "KOSDAQ", "엔터", "035900.KQ"),
    ("277810", "레인보우로보틱스", "KOSDAQ", "로봇", "277810.KQ"),
    ("086520", "에코프로", "KOSDAQ", "2차전지", "086520.KQ"),
]

INDEXES = [
    ("KOSPI", "^KS11"),
    ("KOSDAQ", "^KQ11"),
]


def finite(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def request_json(url: str, *, headers: dict[str, str] | None = None,
                 data: dict[str, object] | None = None, retries: int = 3) -> dict:
    body = None if data is None else json.dumps(data).encode("utf-8")
    base_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; K-Pattern-Radar/2.0)",
        "Accept": "application/json",
    }
    base_headers.update(headers or {})
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, data=body, headers=base_headers)
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            if attempt + 1 == retries:
                raise
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError("unreachable")


def yahoo_chart(symbol: str, interval: str, range_: str) -> dict:
    encoded = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        f"?interval={interval}&range={range_}&events=div%2Csplits"
    )
    payload = request_json(url)
    result = payload.get("chart", {}).get("result") or []
    if not result:
        raise RuntimeError(payload.get("chart", {}).get("error") or "empty response")
    return result[0]


def clean_series(chart: dict) -> list[dict[str, float | int]]:
    timestamps = chart.get("timestamp") or []
    quote = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
    rows: list[dict[str, float | int]] = []
    for i, stamp in enumerate(timestamps):
        close = (quote.get("close") or [None] * len(timestamps))[i]
        if close is None:
            continue
        rows.append({
            "time": int(stamp),
            "open": finite((quote.get("open") or [None] * len(timestamps))[i], finite(close)),
            "high": finite((quote.get("high") or [None] * len(timestamps))[i], finite(close)),
            "low": finite((quote.get("low") or [None] * len(timestamps))[i], finite(close)),
            "close": finite(close),
            "volume": int(finite((quote.get("volume") or [0] * len(timestamps))[i])),
        })
    return rows


def sma(values: list[float], period: int) -> float:
    return statistics.fmean(values[-period:]) if len(values) >= period else statistics.fmean(values)


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    changes = [values[i] - values[i - 1] for i in range(len(values) - period, len(values))]
    gains = statistics.fmean(max(change, 0) for change in changes)
    losses = statistics.fmean(max(-change, 0) for change in changes)
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return 100 - 100 / (1 + gains / losses)


def atr(rows: list[dict[str, float | int]], period: int = 14) -> float:
    if len(rows) < 2:
        return 0.0
    recent = rows[-(period + 1):]
    true_ranges = []
    for previous, current in zip(recent, recent[1:]):
        true_ranges.append(max(
            finite(current["high"]) - finite(current["low"]),
            abs(finite(current["high"]) - finite(previous["close"])),
            abs(finite(current["low"]) - finite(previous["close"])),
        ))
    return statistics.fmean(true_ranges) if true_ranges else 0.0


def return_n(values: list[float], sessions: int) -> float:
    if len(values) <= sessions or not values[-sessions - 1]:
        return 0.0
    return values[-1] / values[-sessions - 1] - 1


def market_regime(close: float, ma20: float, ma60: float, ma120: float) -> str:
    if close > ma20 > ma60 > ma120:
        return "RISK_ON"
    if close < ma20 < ma60 < ma120:
        return "RISK_OFF"
    return "NEUTRAL"


def build_market(name: str, symbol: str) -> dict:
    daily = clean_series(yahoo_chart(symbol, "1d", "1y"))
    minute_chart = yahoo_chart(symbol, "1m", "1d")
    minute = clean_series(minute_chart)
    if len(daily) < 60 or not minute:
        raise RuntimeError("지수 분석에 필요한 데이터가 부족합니다.")
    closes = [finite(row["close"]) for row in daily]
    current = finite(minute[-1]["close"])
    previous = finite((minute_chart.get("meta") or {}).get("chartPreviousClose"))
    if not previous and len(closes) > 1:
        previous = closes[-2]
    ma20, ma60, ma120 = sma(closes, 20), sma(closes, 60), sma(closes, 120)
    return {
        "market": name,
        "symbol": symbol,
        "close": round(current, 2),
        "previous_close": round(previous, 2),
        "change": round(current - previous, 2),
        "change_pct": round(current / previous - 1, 6) if previous else 0,
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "ma120": round(ma120, 2),
        "return20": round(return_n(closes, 20), 6),
        "return60": round(return_n(closes, 60), 6),
        "regime": market_regime(current, ma20, ma60, ma120),
        "quote_time": datetime.fromtimestamp(int(minute[-1]["time"]), SEOUL_OFFSET).isoformat(),
        "series": [round(finite(row["close"]), 2) for row in daily[-30:]],
    }


def kis_session() -> tuple[str, str, str] | None:
    key = os.getenv("KIS_APP_KEY", "").strip()
    secret = os.getenv("KIS_APP_SECRET", "").strip()
    if not key or not secret:
        return None
    payload = request_json(
        "https://openapi.koreainvestment.com:9443/oauth2/tokenP",
        data={"grant_type": "client_credentials", "appkey": key, "appsecret": secret},
    )
    token = str(payload.get("access_token", "")).strip()
    if not token:
        raise RuntimeError("KIS access token was not returned")
    return key, secret, token


def kis_quote(code: str, session: tuple[str, str, str]) -> dict:
    key, secret, token = session
    query = urllib.parse.urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
    url = (
        "https://openapi.koreainvestment.com:9443"
        "/uapi/domestic-stock/v1/quotations/inquire-price?"
        + query
    )
    payload = request_json(url, headers={
        "authorization": f"Bearer {token}",
        "appkey": key,
        "appsecret": secret,
        "tr_id": "FHKST01010100",
        "custtype": "P",
    })
    if str(payload.get("rt_cd", "0")) != "0":
        raise RuntimeError(str(payload.get("msg1") or payload.get("msg_cd") or "KIS error"))
    output = payload.get("output") or {}
    return {
        "price": finite(output.get("stck_prpr")),
        "previous_close": finite(output.get("stck_prpr")) - finite(output.get("prdy_vrss")),
        "change": finite(output.get("prdy_vrss")),
        "change_pct": finite(output.get("prdy_ctrt")) / 100,
        "volume": int(finite(output.get("acml_vol"))),
    }


def grade(score: float) -> str:
    return "S" if score >= 85 else "A" if score >= 75 else "B" if score >= 65 else "C"


def analyze_stock(item: tuple[str, str, str, str, str], market: dict,
                  session: tuple[str, str, str] | None) -> dict:
    code, name, exchange, sector, symbol = item
    daily = clean_series(yahoo_chart(symbol, "1d", "1y"))
    minute_chart = yahoo_chart(symbol, "1m", "1d")
    minute = clean_series(minute_chart)
    if len(daily) < 120 or not minute:
        raise RuntimeError("분석에 필요한 120거래일 데이터가 부족합니다.")

    closes = [finite(row["close"]) for row in daily]
    volumes = [int(row["volume"]) for row in daily]
    current = finite(minute[-1]["close"])
    previous = finite((minute_chart.get("meta") or {}).get("chartPreviousClose"))
    # Minute bars contain per-minute volume, not the day's cumulative volume.
    # The daily bar is preferred after close; the summed minute volume is a
    # safe intraday fallback.
    current_volume = max(int(daily[-1]["volume"]), sum(int(row["volume"]) for row in minute))
    provider = "YAHOO_DELAYED"

    if session:
        official = kis_quote(code, session)
        if official["price"] > 0:
            current = official["price"]
            previous = official["previous_close"]
            current_volume = official["volume"]
            provider = "KIS_REALTIME"

    if not previous:
        previous = closes[-2]
    closes[-1] = current
    ma20, ma60, ma120 = sma(closes, 20), sma(closes, 60), sma(closes, 120)
    rsi14, atr14 = rsi(closes), atr(daily)
    ret20, ret60 = return_n(closes, 20), return_n(closes, 60)
    relative = ret20 - finite(market["return20"])
    average_volume = statistics.fmean(v for v in volumes[-21:-1] if v > 0) if any(v > 0 for v in volumes[-21:-1]) else 0
    volume_ratio = current_volume / average_volume if average_volume else 1
    prior_high = max(closes[-21:-1])
    support20 = min(closes[-20:])
    resistance20 = max(closes[-20:])

    trend_score = 25 if current > ma20 > ma60 > ma120 else 18 if current > ma20 > ma60 else 11 if current > ma20 else 4
    momentum_score = 20 if ret20 > .08 and 50 <= rsi14 <= 70 else 15 if ret20 > 0 and rsi14 >= 45 else 8 if ret20 > -.05 else 3
    relative_score = 15 if relative > .08 else 11 if relative > .03 else 7 if relative >= 0 else 2
    volume_score = 15 if volume_ratio >= 1.5 and current > previous else 11 if volume_ratio >= 1.2 else 7 if volume_ratio >= .8 else 4

    breakout = current >= prior_high * 1.002 and volume_ratio >= 1.15
    pullback = ma20 > ma60 and abs(current / ma20 - 1) <= .025 and current >= ma20
    aligned = current > ma20 > ma60 > ma120
    bearish = current < ma60 and ma20 < ma60
    if breakout:
        pattern, status, pattern_score = "BREAKOUT", "TRIGGERED", 15
    elif pullback:
        pattern, status, pattern_score = "PULLBACK", "RETEST", 13
    elif aligned:
        pattern, status, pattern_score = "UPTREND", "WATCH", 10
    elif bearish:
        pattern, status, pattern_score = "DOWNTREND", "FAILED", 0
    else:
        pattern, status, pattern_score = "NO_CLEAR_SIGNAL", "FORMING", 5

    stop_candidate = min(support20 * .985, current - 1.8 * atr14)
    stop = max(current * .88, stop_candidate)
    if breakout:
        # A breakout entry belongs near the old resistance, not far below at
        # the moving average. This also makes chasing a large gap detectable.
        entry_low = max(stop * 1.03, prior_high * .99)
        entry_high = max(entry_low, min(current * 1.005, prior_high * 1.015))
    else:
        entry_low = max(stop * 1.03, min(current, ma20 * .995))
        entry_high = max(entry_low, min(current * 1.01, ma20 * 1.02))
    risk = max(entry_high - stop, current * .01)
    target = max(resistance20 * 1.01, entry_high + risk * 1.8, current + max(atr14 * 1.5, current * .02))
    rr = (target - entry_high) / risk if risk else 0
    risk_score = 10 if rr >= 2 else 8 if rr >= 1.5 else 4 if rr >= 1 else 2
    score = min(100, trend_score + momentum_score + relative_score + volume_score + pattern_score + risk_score)

    overheated = rsi14 >= 72 or (atr14 > 0 and current > ma20 + 2.5 * atr14)
    risks: list[str] = []
    if market["regime"] == "RISK_OFF":
        risks.append("시장 전체가 위험회피 구간입니다.")
    if overheated:
        risks.append("단기 과열 신호가 있어 추격 매수 위험이 큽니다.")
    if volume_ratio < 1:
        risks.append("평균보다 거래량이 적어 신호 신뢰도가 낮습니다.")
    if relative < 0:
        risks.append("시장 지수보다 최근 20일 흐름이 약합니다.")
    if rr < 1.5:
        risks.append("예상 손익비가 1.5보다 낮습니다.")

    chased = current > entry_high * 1.04
    if bearish or score < 40:
        action = "SELL_REVIEW"
        label = "신규 매수 제외"
        summary = "하락 추세가 확인되어 새로 사기에는 위험이 큽니다. 보유 중이라면 손절 기준을 점검하세요."
    elif chased:
        action = "WAIT"
        label = "추격 매수 관망"
        summary = "현재가가 적정 진입 구간을 크게 벗어났습니다. 좋은 흐름이어도 눌림을 기다리는 편이 안전합니다."
    elif overheated:
        action = "WAIT"
        label = "과열 관망"
        summary = "좋은 흐름이어도 가격이 단기간 너무 올라 추격 진입은 불리할 수 있습니다."
    elif market["regime"] == "RISK_OFF":
        action = "WAIT"
        label = "시장 위험 관망"
        summary = "종목보다 시장 전체 위험이 커서 신규 진입을 잠시 미루는 판단입니다."
    elif score >= 75 and rr >= 1.5 and volume_ratio >= .8 and status in {"TRIGGERED", "RETEST", "WATCH"}:
        action = "BUY_REVIEW"
        label = "매수 검토"
        summary = "추세·상대강도·손익비 조건이 함께 확인된 후보입니다. 진입 구간을 지켜 분할 접근을 검토하세요."
    else:
        action = "WAIT"
        label = "관망"
        summary = "좋은 조건이 아직 충분히 겹치지 않아 기다리는 편이 유리합니다."

    confidence = "높음" if score >= 85 or score < 35 else "보통" if score >= 65 or score < 50 else "낮음"
    reasons = [
        f"현재가는 20일 평균선보다 {abs(current / ma20 - 1) * 100:.1f}% {'위' if current >= ma20 else '아래'}에 있습니다.",
        f"최근 20일 수익률은 {ret20 * 100:+.1f}%, 시장 대비 상대강도는 {relative * 100:+.1f}%p입니다.",
        f"RSI는 {rsi14:.1f}, 거래량은 20일 평균의 {volume_ratio:.2f}배입니다.",
    ]
    return {
        "code": code, "name": name, "market": exchange, "sector": sector, "symbol": symbol,
        "provider": provider, "price": round(current, 2), "previous_close": round(previous, 2),
        "change": round(current - previous, 2),
        "change_pct": round(current / previous - 1, 6) if previous else 0,
        "volume": current_volume, "volume_ratio": round(volume_ratio, 3),
        "ma20": round(ma20, 2), "ma60": round(ma60, 2), "ma120": round(ma120, 2),
        "rsi14": round(rsi14, 2), "atr14": round(atr14, 2),
        "return20": round(ret20, 6), "return60": round(ret60, 6),
        "relative_strength": round(relative, 6),
        "support20": round(support20, 2), "resistance20": round(resistance20, 2),
        "pattern": pattern, "status": status, "score": round(score, 1), "grade": grade(score),
        "entry_low": round(entry_low, 2), "entry_high": round(entry_high, 2),
        "stop": round(stop, 2), "target": round(target, 2), "risk_reward": round(rr, 2),
        "components": {
            "trend": trend_score, "momentum": momentum_score, "relative": relative_score,
            "volume": volume_score, "pattern": pattern_score, "risk": risk_score,
        },
        "decision": {
            "action": action, "label": label, "confidence": confidence, "summary": summary,
            "reasons": reasons, "risks": risks or ["뚜렷한 정량 위험 신호는 없지만 공시·실적 확인이 필요합니다."],
            "checklist": [
                "최근 공시와 실적 발표 일정을 확인하세요.",
                "한 번에 전액 매수하지 말고 분할 진입을 고려하세요.",
                "손절 기준을 정한 뒤 감당 가능한 금액만 투자하세요.",
            ],
        },
        "quote_time": datetime.fromtimestamp(int(minute[-1]["time"]), SEOUL_OFFSET).isoformat(),
        "series": [round(value, 2) for value in closes[-60:]],
    }


def main() -> None:
    now = datetime.now(SEOUL_OFFSET)
    errors: list[dict[str, str]] = []
    markets: list[dict] = []
    for name, symbol in INDEXES:
        try:
            markets.append(build_market(name, symbol))
        except Exception as exc:
            errors.append({"item": name, "message": str(exc)})
    if len(markets) != 2:
        raise RuntimeError(f"KOSPI/KOSDAQ 지수 수집 실패: {errors}")

    session = None
    try:
        session = kis_session()
    except Exception as exc:
        errors.append({"item": "KIS", "message": f"공식 시세 연결 실패, 지연 시세 사용: {exc}"})

    market_map = {item["market"]: item for item in markets}
    stocks: list[dict] = []
    for item in UNIVERSE:
        try:
            stocks.append(analyze_stock(item, market_map[item[2]], session))
        except Exception as exc:
            errors.append({"item": item[0], "message": str(exc)})
        time.sleep(.12)
    if not stocks:
        raise RuntimeError("모든 종목 수집에 실패했습니다.")

    is_weekday = now.weekday() < 5
    minute = now.hour * 60 + now.minute
    market_state = "OPEN" if is_weekday and 9 * 60 <= minute <= 15 * 60 + 40 else "CLOSED"
    official_count = sum(stock["provider"] == "KIS_REALTIME" for stock in stocks)
    payload = {
        "schema_version": 2,
        "generated_at": now.isoformat(timespec="seconds"),
        "data_as_of": max(market["quote_time"] for market in markets),
        "market_state": market_state,
        "source": {
            "provider": "한국투자증권 Open API + Yahoo Finance" if official_count else "Yahoo Finance 공개 시세",
            "mode": "OFFICIAL_REALTIME" if official_count else "PUBLIC_DELAYED",
            "latency": "공식 현재가·공개 과거자료 조합" if official_count else "무료 공개 지연 시세(공급자에 따라 15분 이상 지연 가능)",
            "official_quote_count": official_count,
            "auto_refresh_minutes": 5,
            "note": "거래소 직접 배포 데이터가 아니며 주문 전 증권사 호가를 다시 확인해야 합니다.",
        },
        "markets": markets,
        "stocks": stocks,
        "errors": errors,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(stocks)} stocks, {len(errors)} warnings)")


if __name__ == "__main__":
    main()
