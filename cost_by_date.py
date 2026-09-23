import pyupbit

# 1. 티커 설정 (예: 비트코인)
ticker = "KRW-ETH"

# 2. 특정 과거 날짜 지정 (YYYY-MM-DD 형식)
# 주의: 'to' 파라미터는 입력한 날짜의 '이전' 캔들을 가져옵니다.
# 예: 2023년 1월 1일의 가격을 보고 싶으면, to에 '2023-01-02'를 넣어야 1월 1일 데이터가 나옵니다.
target_date = "2025-11-18 09:00:00"

# 3. 데이터 조회 (interval="day"는 일봉 기준)
# count=1은 딱 하루 치만 가져온다는 뜻입니다.
df = pyupbit.get_ohlcv(ticker, interval="day", to=target_date, count=1)

print(f"[{ticker}] {target_date} 기준 과거 데이터")
print(df)

# open: 시가 (장 시작 가격)
# high: 고가 (가장 비쌌던 가격)
# low: 저가 (가장 쌌던 가격)
# close: 종가 (장 마감 가격 - 보통 이걸 그날의 가격으로 봅니다)