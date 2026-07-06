#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매일 아침 주식 데일리 리포트 생성 + 카카오톡 발송
- 데이터: yfinance (밸류에이션/펀더멘털/매크로)
- 분석: Claude API (최신 뉴스 + 예정 이벤트 + 밸류에이션 판단, 웹검색 사용)
- 출력: HTML 리포트(docs/index.html, GitHub Pages) + 카카오톡 나에게 보내기
"""

import os
import json
import datetime
import zoneinfo

import yfinance as yf
import anthropic

from kakao import send_kakao_memo

# =========================================================================
#  설정  ── 여기만 수정하면 됩니다
# =========================================================================

# 보유 종목: 티커 -> (수량, 평균단가 USD).  평단 0 이면 P&L 계산 생략
HOLDINGS = {
    "SPCX": {"shares": 49,   "avg": 154.71},
    "CBRS": {"shares": 57,   "avg": 219.2135},
    "GNTA": {"shares": 4266, "avg": 2.1362},
    "ORCL": {"shares": 71,   "avg": 186.3747},
    "RDW":  {"shares": 399,  "avg": 20.34},
    "SNDK": {"shares": 2,    "avg": 2073.90},
    "INTC": {"shares": 51,   "avg": 128.71},
    "HPE":  {"shares": 147,  "avg": 50.99},
}

# 매크로 지표: 표시이름 -> yfinance 티커
MACRO = {
    "S&P500":   "^GSPC",
    "나스닥":    "^IXIC",
    "VIX":      "^VIX",
    "美10년물":  "^TNX",
    "달러인덱스": "DX-Y.NYB",
    "USD/KRW":  "KRW=X",
    "코스피":    "^KS11",
}

CLAUDE_MODEL = "claude-sonnet-5"   # 더 깊은 분석 원하면 "claude-opus-4-8"
# 리포트가 게시될 공개 URL (카톡 버튼 링크). GitHub Pages 주소로 교체하세요.
REPORT_URL = os.environ.get("REPORT_URL", "https://example.github.io/stock-daily-report/")

KST = zoneinfo.ZoneInfo("Asia/Seoul")


# =========================================================================
#  1. 데이터 수집
# =========================================================================

def _pct(cur, prev):
    if not cur or not prev:
        return None
    return (cur - prev) / prev * 100


def fetch_quote(ticker):
    """가격 + 등락률만 가볍게."""
    tk = yf.Ticker(ticker)
    try:
        fi = tk.fast_info
        price = fi.get("last_price") or fi.get("lastPrice")
        prev = fi.get("previous_close") or fi.get("previousClose")
    except Exception:
        price = prev = None
    if price is None:
        try:
            h = tk.history(period="2d")
            if len(h) >= 2:
                price = float(h["Close"].iloc[-1])
                prev = float(h["Close"].iloc[-2])
            elif len(h) == 1:
                price = float(h["Close"].iloc[-1])
        except Exception:
            pass
    return price, _pct(price, prev)


def fetch_fundamentals(ticker, holding=None):
    """밸류에이션 + 펀더멘털 + 최근 뉴스 헤드라인 + 다음 실적일."""
    tk = yf.Ticker(ticker)
    info = {}
    try:
        info = tk.info or {}
    except Exception:
        info = {}

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
    if price is None:
        price, chg = fetch_quote(ticker)
    else:
        chg = _pct(price, prev)

    data = {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or ticker,
        "price": price,
        "change_pct": chg,
        "currency": info.get("currency", "USD"),
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "pbr": info.get("priceToBook"),
        "psr": info.get("priceToSalesTrailing12Months"),
        "profit_margin": info.get("profitMargins"),
        "gross_margin": info.get("grossMargins"),
        "revenue_growth": info.get("revenueGrowth"),
        "roe": info.get("returnOnEquity"),
        "total_cash": info.get("totalCash"),
        "total_debt": info.get("totalDebt"),
        "ev": info.get("enterpriseValue"),
        "week52_high": info.get("fiftyTwoWeekHigh"),
        "week52_low": info.get("fiftyTwoWeekLow"),
        "target_mean": info.get("targetMeanPrice"),
        "recommendation": info.get("recommendationKey"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
    }

    # 다음 실적일
    try:
        cal = tk.calendar
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                data["next_earnings"] = str(ed[0] if isinstance(ed, list) else ed)
    except Exception:
        pass

    # 최근 뉴스 헤드라인 (yfinance)
    news = []
    try:
        for n in (tk.news or [])[:5]:
            content = n.get("content", n)
            title = content.get("title") or n.get("title")
            pub = (content.get("provider") or {}).get("displayName") if isinstance(content.get("provider"), dict) else n.get("publisher")
            if title:
                news.append({"title": title, "publisher": pub})
    except Exception:
        pass
    data["news"] = news

    # 보유 손익
    if holding and holding.get("avg") and price:
        shares, avg = holding["shares"], holding["avg"]
        data["shares"] = shares
        data["avg"] = avg
        data["market_value"] = price * shares
        data["unrealized"] = (price - avg) * shares
        data["unrealized_pct"] = (price - avg) / avg * 100

    return data


def fetch_macro():
    out = {}
    for label, tk in MACRO.items():
        price, chg = fetch_quote(tk)
        out[label] = {"price": price, "change_pct": chg}
    return out


# =========================================================================
#  2. Claude 분석 (최신 뉴스 + 예정 이벤트 + 밸류에이션 판단)
# =========================================================================

def build_analysis(holdings_data, macro_data):
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용
    today = datetime.datetime.now(KST).strftime("%Y년 %m월 %d일")

    payload = {
        "date": today,
        "macro": macro_data,
        "holdings": [
            {k: v for k, v in h.items() if k != "news"} | {"news_headlines": [n["title"] for n in h.get("news", [])]}
            for h in holdings_data
        ],
    }

    system = (
        "너는 개인 투자자를 위한 한국어 주식 애널리스트다. 전달받은 실시간 수치와 "
        "웹검색 결과를 바탕으로, 오늘자 데일리 리포트를 작성한다. 과장·확신을 피하고 "
        "근거와 함께 균형 잡힌 시각을 제시한다. 투자 권유가 아니라 판단 재료를 정리한다."
    )

    prompt = f"""아래는 오늘 기준 보유 종목의 실시간 데이터다. 이걸 바탕으로 리포트를 써라.

<data>
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
</data>

각 종목(CBRS, ORCL, GNTA, RDW)에 대해 **웹검색으로 오늘~최근 며칠의 실제 뉴스와 앞으로 예정된 이벤트(실적발표·컨퍼런스·규제·록업해제 등)를 직접 확인**해서 반영하라. 뉴스가 없으면 "특이 뉴스 없음"이라고 명시하라.

다음 형식의 **한국어 마크다운**으로만 출력하라. 맨 첫 줄은 반드시 `SUMMARY:` 로 시작하는 100자 이내 한 줄 요약(카톡용)으로 쓴다.

SUMMARY: (전체 한 줄 총평 - 예: "ORCL 강세 지속·GNTA 변동성 확대, 매크로는 금리 하락 우호")

## 📈 매크로 브리핑
- 오늘 지수/금리/환율 흐름을 3~4줄로. 내 종목에 주는 함의 중심.

## 종목별 분석
각 종목마다:
### 티커 — 회사명
- **주가/손익**: 현재가, 등락, (있으면) 내 평단 대비 손익 한 줄
- **밸류에이션**: PER·PBR·PSR을 섹터 맥락에서 해석. 적자/성장주라 PER이 의미 없으면 그 점을 명확히 하고 PSR·현금소진·EV/매출 등 대안 지표로 판단. "싸다/적정/비싸다"를 근거와 함께.
- **최신 뉴스**: 웹검색 기반 실제 뉴스 (없으면 "특이 뉴스 없음")
- **예정 이벤트**: 다음 실적일·촉매 (알 수 있으면)
- **한 줄 판단**: 밸류에이션+뉴스 종합 코멘트

## 🧭 오늘의 종합 판단
- 포트폴리오 관점 2~3줄. 주목할 리스크/체크포인트.

숫자는 반드시 <data>의 실제 값을 쓰고, 없는 값은 "N/A"로. 확정적 매수/매도 지시는 하지 마라."""

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
    )

    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return text.strip()


# =========================================================================
#  3. HTML 렌더링
# =========================================================================

def _fmt(v, suffix="", pct=False, money=False):
    if v is None:
        return "N/A"
    try:
        if money:
            if abs(v) >= 1e9:
                return f"${v/1e9:.2f}B"
            if abs(v) >= 1e6:
                return f"${v/1e6:.1f}M"
            return f"${v:,.0f}"
        if pct:
            return f"{v*100:.1f}%" if abs(v) < 5 else f"{v:.1f}%"
        return f"{v:,.2f}{suffix}"
    except Exception:
        return str(v)


def render_html(analysis_md, holdings_data, macro_data):
    try:
        import markdown
        body = markdown.markdown(analysis_md, extensions=["extra", "nl2br"])
    except Exception:
        body = "<pre>" + analysis_md.replace("<", "&lt;") + "</pre>"

    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    # 스냅샷 테이블
    rows = ""
    for h in holdings_data:
        chg = h.get("change_pct")
        color = "#16a34a" if (chg or 0) >= 0 else "#dc2626"
        pnl = h.get("unrealized_pct")
        pnl_html = f'<span style="color:{"#16a34a" if (pnl or 0)>=0 else "#dc2626"}">{pnl:+.1f}%</span>' if pnl is not None else "—"
        rows += f"""<tr>
          <td><b>{h['ticker']}</b></td>
          <td>{_fmt(h.get('price'))}</td>
          <td style="color:{color}">{(f"{chg:+.2f}%" if chg is not None else "N/A")}</td>
          <td>{pnl_html}</td>
          <td>{_fmt(h.get('trailing_pe'))}</td>
          <td>{_fmt(h.get('pbr'))}</td>
          <td>{_fmt(h.get('psr'))}</td>
          <td>{_fmt(h.get('market_cap'), money=True)}</td>
        </tr>"""

    macro_row = ""
    for k, v in macro_data.items():
        chg = v.get("change_pct")
        color = "#16a34a" if (chg or 0) >= 0 else "#dc2626"
        macro_row += f'<span class="chip">{k} <b>{_fmt(v.get("price"))}</b> <span style="color:{color}">{(f"{chg:+.2f}%" if chg is not None else "")}</span></span>'

    return f"""<!doctype html><html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>주식 데일리 리포트 · {now}</title>
<style>
  :root{{--bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--muted:#94a3b8;--accent:#38bdf8;--border:#334155}}
  *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);
    font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;line-height:1.7}}
  .wrap{{max-width:820px;margin:0 auto;padding:24px 18px 80px}}
  h1{{font-size:22px;margin:0 0 4px}} .meta{{color:var(--muted);font-size:13px;margin-bottom:20px}}
  .chips{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:20px}}
  .chip{{background:var(--card);border:1px solid var(--border);border-radius:8px;
    padding:5px 10px;font-size:12px}}
  table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;
    overflow:hidden;font-size:13px;margin-bottom:24px}}
  th,td{{padding:9px 8px;text-align:right;border-bottom:1px solid var(--border)}}
  th:first-child,td:first-child{{text-align:left}}
  th{{background:#172033;color:var(--muted);font-weight:600;font-size:12px}}
  .report h2{{font-size:18px;margin:26px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--border)}}
  .report h3{{font-size:15px;margin:18px 0 6px;color:var(--accent)}}
  .report ul{{padding-left:18px;margin:6px 0}} .report li{{margin:3px 0}}
  .report strong{{color:#fff}}
  .disc{{margin-top:40px;padding:14px;background:#172033;border-radius:8px;
    color:var(--muted);font-size:12px;line-height:1.6}}
  a{{color:var(--accent)}}
</style></head><body><div class="wrap">
  <h1>📊 주식 데일리 리포트</h1>
  <div class="meta">{now} · 자동 생성</div>
  <div class="chips">{macro_row}</div>
  <table>
    <tr><th>종목</th><th>현재가</th><th>전일비</th><th>내손익</th><th>PER</th><th>PBR</th><th>PSR</th><th>시총</th></tr>
    {rows}
  </table>
  <div class="report">{body}</div>
  <div class="disc">
    본 리포트는 yfinance 데이터와 AI 분석으로 자동 생성된 개인용 참고자료이며,
    투자 자문·매매 권유가 아닙니다. 데이터는 지연·오류가 있을 수 있으니 투자 판단과
    책임은 본인에게 있습니다.
  </div>
</div></body></html>"""


# =========================================================================
#  4. 메인
# =========================================================================

def build_kakao_summary(analysis_md, holdings_data):
    """카톡 텍스트(200자 제한) 생성."""
    # SUMMARY: 라인 추출
    summary = ""
    for line in analysis_md.splitlines():
        if line.strip().upper().startswith("SUMMARY:"):
            summary = line.split(":", 1)[1].strip()
            break

    date = datetime.datetime.now(KST).strftime("%m/%d")
    quote_bits = []
    for h in holdings_data:
        chg = h.get("change_pct")
        c = f"{chg:+.1f}%" if chg is not None else "-"
        quote_bits.append(f"{h['ticker']} {c}")
    quotes = " ".join(quote_bits)

    text = f"📊 {date} 데일리 리포트\n{quotes}"
    if summary:
        text += f"\n🔎 {summary}"
    text += "\n전문은 아래 버튼 →"

    # 200자 안전 컷
    if len(text) > 195:
        text = text[:192] + "…"
    return text


def main():
    print("[1/4] 데이터 수집 중...")
    holdings_data = [fetch_fundamentals(t, HOLDINGS[t]) for t in HOLDINGS]
    macro_data = fetch_macro()

    print("[2/4] Claude 분석 중...")
    try:
        analysis_md = build_analysis(holdings_data, macro_data)
    except Exception as e:
        analysis_md = f"SUMMARY: 분석 생성 실패\n\n> 분석 단계 오류: {e}\n\n스냅샷 데이터만 표시합니다."
        print("  분석 실패:", e)

    print("[3/4] HTML 리포트 생성 중...")
    html = render_html(analysis_md, holdings_data, macro_data)
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("[4/4] 카카오톡 발송 중...")
    text = build_kakao_summary(analysis_md, holdings_data)
    try:
        send_kakao_memo(text, link_url=REPORT_URL, button_title="전문 보기")
        print("  발송 완료")
    except Exception as e:
        print("  카톡 발송 실패:", e)

    print("완료.")


if __name__ == "__main__":
    main()
