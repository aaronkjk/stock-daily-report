# 📊 주식 데일리 리포트 → 카카오톡 자동 발송

매일 아침 08:00(KST)에 보유 종목의 **밸류에이션(PER/PBR/PSR)·펀더멘털·매크로·최신 뉴스·예정 이벤트·AI 밸류에이션 판단**을 정리해서 **카카오톡 '나에게 보내기'**로 받아보는 자동화입니다.

- 데이터: `yfinance`
- 분석: Claude API (웹검색으로 실시간 뉴스/이벤트 반영)
- 리포트: HTML → GitHub Pages 게시
- 발송: 카톡 요약(200자) + [전문 보기] 버튼
- 실행: GitHub Actions cron (서버·PC 켜둘 필요 없음, 무료)

> ⚠️ 참고자료용 자동 리포트이며 투자 자문·매매 권유가 아닙니다.

---

## 준비물 3개

| 시크릿 | 용도 | 발급처 |
|---|---|---|
| `ANTHROPIC_API_KEY` | AI 분석 | console.anthropic.com |
| `KAKAO_REST_API_KEY` | 카톡 발송 | developers.kakao.com |
| `KAKAO_REFRESH_TOKEN` | 카톡 인증 | 아래 3단계에서 발급 |

---

## STEP 1. GitHub 저장소 만들기

1. 이 폴더를 새 **GitHub 저장소**로 올립니다(비공개 OK).
2. 저장소 **Settings → Pages** 에서 Source를 `main 브랜치 / docs 폴더`로 설정.
   → 공개 주소가 생깁니다: `https://<아이디>.github.io/<저장소>/`
   이 주소가 카톡 버튼이 열 **리포트 전문 URL**입니다.

## STEP 2. Anthropic API 키

1. console.anthropic.com → API Keys → 키 생성.
2. (뒤 STEP 4에서 GitHub Secret으로 저장)

## STEP 3. 카카오 앱 + refresh token (가장 번거로운 부분, 한 번만)

1. **developers.kakao.com → 내 애플리케이션 → 앱 만들기.**
2. **앱 키**에서 `REST API 키` 복사.
3. **카카오 로그인** → 활성화 **ON**, **Redirect URI** 등록
   (테스트용으로 `https://localhost` 아무거나 하나).
4. **카카오 로그인 → 동의항목**에서 **"카카오톡 메시지 전송"(`talk_message`)** 을 사용 설정.
5. **플랫폼 → Web**에 STEP 1의 Pages 도메인(`https://<아이디>.github.io`) 등록
   (버튼 링크가 열리려면 필요).
6. 브라우저 주소창에 아래를 넣고 로그인·동의 (대문자 2곳 교체):
   ```
   https://kauth.kakao.com/oauth/authorize?client_id=REST_API_키&redirect_uri=https://localhost&response_type=code&scope=talk_message
   ```
7. 리다이렉트된 주소 `https://localhost/?code=XXXXX` 에서 **code 값 복사**.
8. 로컬에서 refresh token 발급:
   ```bash
   pip install requests
   REST_API_KEY=REST_API_키 REDIRECT_URI=https://localhost python get_token.py XXXXX
   ```
   출력된 **refresh_token** 을 복사.

> 카카오 refresh token은 약 2개월 유효합니다. 만료 전 자동으로 새 토큰이 로그에 찍히면
> (Actions 로그 확인) GitHub Secret을 갱신하세요. 만료되면 6~7단계만 다시 하면 됩니다.

## STEP 4. GitHub Secrets 등록

저장소 **Settings → Secrets and variables → Actions → New repository secret** 로 등록:

| 이름 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | STEP 2의 키 |
| `KAKAO_REST_API_KEY` | STEP 3의 REST API 키 |
| `KAKAO_REFRESH_TOKEN` | STEP 3의 refresh token |
| `REPORT_URL` | `https://<아이디>.github.io/<저장소>/` |
| `KAKAO_CLIENT_SECRET` | (앱에서 client secret을 켰다면) 아니면 생략 |

## STEP 5. 테스트 & 가동

1. 저장소 **Actions** 탭 → `daily-stock-report` → **Run workflow** (수동 실행).
2. 성공하면 카톡 '나와의 채팅'에 리포트 요약이 도착, [전문 보기] 버튼으로 웹 리포트 확인.
3. 이후 **매일 08:00(KST) 자동 발송**됩니다.

---

## 자주 하는 커스터마이징 (`report.py` 상단)

- **종목 변경**: `HOLDINGS` 딕셔너리 수정 (티커/수량/평단). 평단 넣으면 손익도 표시.
- **매크로 지표 변경**: `MACRO` 딕셔너리.
- **분석 모델**: `CLAUDE_MODEL` → 더 깊은 분석은 `"claude-opus-4-8"`.
- **발송 시각**: `.github/workflows/daily-report.yml` 의 cron 수정.
  `0 23 * * *`(매일 08시) → 평일만 원하면 `0 23 * * 0-4`(월~금 아침).

## 비용 대략

- GitHub Actions: 하루 1회, 무료 한도 내.
- Claude API: 하루 1회 분석 + 웹검색 → 월 몇 달러 수준(모델·검색량에 따라).
- 카카오/yfinance: 무료.

## 알려진 제약

- 카톡 텍스트 메시지는 **최대 200자** → 상세 내용은 웹 리포트로, 카톡은 요약+링크.
- GitHub Actions 스케줄은 서버 부하 시 수 분~수십 분 지연될 수 있음(정시 보장 X).
- 08:00 KST 리포트는 **직전 미국장 마감** 기준. 주말/월요일 아침은 금요일 종가가 표시됨.
- `yfinance`는 비공식 데이터라 일부 지표가 `N/A`로 빌 수 있음(특히 적자·소형주 PER).
