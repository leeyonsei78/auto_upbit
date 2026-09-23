# binance_fetcher.py
# pip install ccxt 

import ccxt
import time
from datetime import datetime

# --- 바이낸스 API 헬퍼 ---
# (API 키가 필요 없는 public data)
binance_client = ccxt.binance()

# API 호출을 줄이기 위한 간단한 캐시
# { 'BTC/USDT': (데이터, 타임스탬프) }
funding_rate_cache = {}
CACHE_DURATION_SECONDS = 300 # 5분

def get_binance_funding_rate(upbit_ticker):
    """
    업비트 티커(KRW-BTC)를 바이낸스 티커(BTC/USDT)로 변환하여
    현재 펀딩비(funding rate)를 조회합니다.
    API Rate Limit을 피하기 위해 5분간 결과를 캐시합니다.
    """
    global funding_rate_cache

    # 1. 티커 변환 (Upbit KRW-XXX -> Binance XXX/USDT)
    try:
        coin_code = upbit_ticker.split('-')[1]
        # 바이낸스 선물(PERP) 티커로 변환
        # (참고: 업비트에만 상장된 코인은 조회가 실패합니다)
        binance_perp_ticker = f"{coin_code}/USDT:USDT" 
    except Exception as e:
        return None, f"티커 변환 실패: {e}"

    # 2. 캐시 확인
    cached_data = funding_rate_cache.get(binance_perp_ticker)
    if cached_data:
        data, timestamp = cached_data
        if (time.time() - timestamp) < CACHE_DURATION_SECONDS:
            # 캐시가 유효하면 API 호출 없이 반환
            return data, "cached"

    # 3. 캐시가 없으면 API 호출
    try:
        # 바이낸스 USDT-M 선물 시장 정보 조회
        markets = binance_client.fetch_markets()
        
        # 정확한 symbol 찾기 (ccxt는 티커에 :USDT를 붙이기도 함)
        target_symbol = None
        for market in markets:
            if market['id'] == f"{coin_code}USDT" and market.get('contract', False):
                 target_symbol = market['symbol']
                 break
        
        if not target_symbol:
            # 일부 코인(XRP 등)은 ID가 다를 수 있음. 
            # 못 찾으면 입력값(binance_perp_ticker)으로 시도
            target_symbol = binance_perp_ticker
            # raise ValueError(f"{coin_code}USDT 선물을 찾을 수 없습니다.")

        # 펀딩비 조회 (fetch_funding_rate는 symbol이 필요)
        # premium_index = binance_client.fetch_premium_index(target_symbol)
        
        # 2024-05-10 ccxt 기준, fetch_funding_rate는 symbol을 받음
        fr_data = binance_client.fetch_funding_rate(symbol=target_symbol)
        
        funding_rate = fr_data.get('fundingRate')
        if funding_rate is None:
            return None, "API 응답에 fundingRate 없음"
            
        funding_rate = float(funding_rate)
        
        # 4. 캐시에 저장 및 반환
        funding_rate_cache[binance_perp_ticker] = (funding_rate, time.time())
        return funding_rate, "live"

    except (ccxt.NetworkError, ccxt.ExchangeError) as e:
        # API 에러 (네트워크, 거래소 오류)
        return None, f"Binance API 오류: {str(e)}"
    except Exception as e:
        # 기타 에러 (티커 없음, 데이터 파싱 실패 등)
        # (참고: 업비트에만 있거나 바이낸스 선물에 없는 코인은 여기서 에러)
        funding_rate_cache[binance_perp_ticker] = (None, time.time()) # 실패도 캐시
        return None, f"펀딩비 조회 실패: {str(e)}"

if __name__ == '__main__':
    # 파일 직접 실행 시 테스트
    print("--- 펀딩비 테스트 ---")
    
    ticker1 = "KRW-BTC"
    fr1, status1 = get_binance_funding_rate(ticker1)
    print(f"[{ticker1}] 펀딩비: {fr1} (상태: {status1})")
    
    ticker2 = "KRW-SOL"
    fr2, status2 = get_binance_funding_rate(ticker2)
    print(f"[{ticker2}] 펀딩비: {fr2} (상태: {status2})")

    # 캐시 테스트 (API 호출 없이 'cached'가 떠야 함)
    print("\n--- 캐시 테스트 ---")
    fr3, status3 = get_binance_funding_rate(ticker1)
    print(f"[{ticker1}] 펀딩비: {fr3} (상태: {status3})")