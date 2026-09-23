# test_auto_upbit — 업비트 자동매매 봇

Streamlit 기반 업비트(pyupbit) 자동매매 봇. RSI/MACD/BBANDS/Stoch/ATR/EMA/ADX/Supertrend/Aroon/TSI/MFI/OBV
지표와 바이낸스 펀딩비(ccxt)를 조합한 점수제 매매 로직. 코인별 가중치(`STRATEGY_WEIGHTS_BY_COIN`) 지원.

## 구조
- `app.py` — Streamlit UI + 메인 루프 (`bot.run_once()`를 60초 간격으로 호출, `st.rerun()`으로 폴링)
- `trade_bot.py` — `TradingBot` 클래스. 지표 계산(`get_trading_data`), 매매 판단(`run_once`),
  UI용 종합판단(`get_comprehensive_judgment`), 코인 스캐너(`score_single_ticker_with_change`,
  `analyze_and_recommend_coins`)
- `config.py` / `config.json` — 설정 로드/저장. `DEFAULT_CONFIG`와 병합. API 키도 `config.json`에 평문 저장됨.
- `binance_fetcher.py` — 바이낸스 선물 펀딩비 조회 (ccxt, 5분 캐시)
- `7차(5차 완성)/` — 이전 버전 스냅샷 (비교용, 활성 코드 아님)

## 환경 / 의존성
- 설치된 `streamlit==1.41.1`. `st.button`/`st.dataframe`/`st.plotly_chart`에 **`width='stretch'`
  문자열 sizing API를 쓰지 말 것** — 이 버전엔 없음 (`st.button`은 즉시 `TypeError`, `st.dataframe`은
  `width`가 int 전용이라 오동작, `st.plotly_chart`는 `**kwargs`로 조용히 삼켜짐). 항상
  `use_container_width=True`를 사용할 것 (2026-09-23에 9곳 전부 이 패턴으로 통일함, 커밋 `ca65610`).
  streamlit을 업그레이드하지 않는 한 이 규칙 유지.

## API 키 취급
로컬 환경에서는 `config.json`에 업비트 API 키가 평문으로 있음. **사용자가 이 환경을 로컬에서 혼자만
사용**하기로 확인했으므로 로컬 파일 자체의 키 로테이션/시크릿 분리는 불필요 — 다시 제안하지 말 것.
단, 이 저장소는 GitHub `leeyonsei78/auto_upbit`(public)에 push되므로 `config.json`,
`trade_history.json`, `logs/`, `__pycache__`는 `.gitignore`로 반드시 제외해야 함(이미 적용됨).
설정 템플릿은 `config.example.json`(키 필드 빈 문자열)으로 제공. **`config.json`을 절대 `git add`/커밋하지
말 것.**

## GitHub
- Remote: `https://github.com/leeyonsei78/auto_upbit.git` (main 브랜치, public)
- 로컬 git identity가 global 기준 `Sdapaul <sdapaul@example.com>`로 되어 있음 (gh 인증 계정은
  `leeyonsei78`이라 push는 정상 동작하지만 커밋 author 표시가 다름) — 사용자가 요청하기 전에는
  건드리지 않음

## 로직 검증 이력 (2026-09-23)
전체 매매 로직을 실행 기반으로 검증. 발견된 이슈와 상태:

### ✅ 수정 완료 (2026-09-23, 커밋 f0d5c2e, GitHub push 완료)
1. **Stoch 신호 완전 무효화** — `trade_bot.py` (당시 788행, run_once 전용 회귀) —
   `d_latest = latest_candle[stoch_k_col]` 오타로 `k_latest == d_latest`가 되어
   Stoch 매수/매도 조건이 항상 False였음. `stoch_d_col`로 수정 완료.
2. `BUY_AMOUNT_KRW`를 5,100원 → 15,000원으로 상향. 추가로 비율 매도/부분 손절 시 계산된
   수량이 5,000원 미만이면 전량 매도로 자동 승격하는 안전장치를 익절/부분손절/분석매도
   3개 지점에 추가 (`trade_bot.py`).
3. 손절/익절 체크를 `is_new_candle` 게이트에서 분리, 매 사이클(60초)마다 실행하도록 변경
   (`trade_bot.py`, 기존 610/648행).
5. 상승 다이버전스 판정 오류 수정: `prev_peak_idx` → `prev_trough_idx` (`_find_divergence`).

(번호 4는 API 키 평문 노출 — 로컬 단독 사용 확인으로 코드 변경 불필요, 아래 "API 키 취급" 참고)

### 🟠 High (미해결)
6. 물타기 직후 같은 사이클에서 바로 매도 로직을 통과할 수 있음 (position 객체 공유, buy_time 미갱신).
   매수 trade_result가 매도 결과로 덮어써져 거래내역 누락 가능. 미해결.
7. 봇 재시작 시 `stop_loss_price`/`target_price`/`highest_price`/`buy_time`이 전부 None으로 초기화됨
   (`_initialize_state_from_upbit`). `USE_ATR_SLTP=true`인데 익절 분기가 `not use_atr_sltp` 조건이라
   재시작 후 보유 포지션은 트레일링 스탑 외 익절 수단이 없음. 미해결.
8. `DYNAMIC_WEIGHT_ADJUSTMENT`의 `strong_trend`/`weak_trend` 배수 키(`ADX_BUY_SCORE`,
   `SUPERTREND_BUY_SCORE` 등)가 실제 가중치 딕셔너리 키(`ADX_TREND_SCORE`, `SUPER_TREND_BUY_SCORE`)와
   불일치 → 추세강도 기반 동적 조정이 전부 no-op. 미해결.
9. 매수 수량 계산이 수수료 미반영 (`buy_volume = buy_amount_krw / price`). 미해결.

### 🟡 Medium (미해결)
- R:R 필터가 상수(`ATR_TP_MULTIPLIER/ATR_SL_MULTIPLIER=1.5`)라 사실상 무의미 (`:1102`)
- 스캐너의 Aroon "직전값"이 25캔들 전 값이라 교차 감지 아님 (`:1685`)
- `get_comprehensive_judgment`의 점수식이 `run_once`와 달라 UI "종합판단"과 실제 매매 근거 불일치
- `config.py` `DEFAULT_CONFIG.copy()`가 얕은 복사라 중첩 dict 오염 가능
- `app.py:999` `tab_run.is_active`는 존재하지 않는 속성 (`DeltaGenerator.__getattr__`가 함수 반환 →
  조건이 항상 참으로 평가됨, 크래시는 없음)
- 트레일링 스탑 발동 조건이 `highest_price > average_buy_price`뿐이라 손실 구간에서도 매도될 수 있음
- `change_1h`/`change_24h`가 `TIME_INTERVAL`과 무관하게 캔들 인덱스 고정
- RSI 과매수+거래량 급증 시 `sell_score += 0`인데 sell_reasons에는 기록됨 (로그 혼란)
- `binance_fetcher.py`가 캐시 미스마다 `fetch_markets()` 전체 조회, Streamlit 메인 스레드에서 블로킹

전체 상세 근거(실행 검증 결과 포함)는 해당 대화 세션 기록 참고. 다음 작업 시 위 목록에서
**"미해결"** 항목 중 어디까지 진행할지 사용자에게 확인.
