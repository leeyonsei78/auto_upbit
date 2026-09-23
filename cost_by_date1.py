import pyupbit

ticker = "KRW-BTC"
target_date = "2025-12-29 09:00:00" # 크리스마스

# count=1 이므로 딱 한 줄만 가져옵니다.
df = pyupbit.get_ohlcv(ticker, interval="day", to=target_date, count=1)

# 데이터가 잘 왔는지 확인하기 위해 인덱스(시간)와 컬럼(가격)을 따로 변수에 담습니다.
date_time = df.index[0]       # 날짜/시간 (인덱스)
high_price = df['high'].iloc[0]    # 고가
low_price = df['low'].iloc[0]      # 저가

# 출력 (보기 좋게 정리)
print(f"기준 시간: {date_time}")
print(f"📈 고가: {high_price:,.0f}원") # ,.0f는 천단위 쉼표 붙이는 서식
print(f"📉 저가: {low_price:,.0f}원")

# (앞부분에 df를 가져오는 코드는 그대로 유지한다고 가정)
# 예: df = pyupbit.get_ohlcv("KRW-BTC", interval="day", count=1)

# 1. 캔들의 기준 시간 가져오기 (DataFrame의 인덱스가 시간입니다)
# 0번째 줄의 시간을 문자열로 변환
time_str = str(df.index[0])

# 2. 가격 데이터 가져오기 (경고 해결을 위해 .iloc 사용)
open_price = df['open'].iloc[0]   # 시가
high_price = df['high'].iloc[0]   # 고가
low_price  = df['low'].iloc[0]    # 저가
close_price = df['close'].iloc[0] # 종가

# 3. 결과 출력 (가격 + 시간)
print(f"시가: {open_price} ({time_str})")
print(f"고가: {high_price} ({time_str})")
print(f"저가: {low_price}  ({time_str})")
print(f"종가: {close_price} ({time_str})")