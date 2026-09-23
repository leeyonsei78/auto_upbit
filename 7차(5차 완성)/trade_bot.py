# trade_bot.py - [최종 통합본]
# [★논문 반영 수정★]: 코인별 가중치(STRATEGY_WEIGHTS_BY_COIN)를 읽도록 수정
#
# 업비트(pyupbit) + 바이낸스(ccxt) 연동
# 신규 지표: OBV, MFI, 펀딩 비율(Funding Rate) 추가
# [수정]: OBV 컬럼명('OBV_' -> 'OBV') 참조 오류 수정
# [수정 2]: OBV EMA 계산 시 pandas_ta 컬럼명 충돌 오류 수정
# [수정 3]: OBV EMA 계산 실패 시 None 대신 raise e로 변경 (봇 중지 방지)
# [수정 4]: get_trading_data/score_single...에서 ATRr 컬럼 조회 로직 수정

import pyupbit
import pandas_ta as ta
import pandas as pd
from datetime import datetime, date
import config 
import time 
from scipy.signal import find_peaks 
import binance_fetcher # [★추가★] 바이낸스 펀딩비 모듈

class TradingBot:
    def __init__(self, config_data):
        self.config = config_data
        self.upbit = self._connect_upbit()
        self.positions = {}
        self.last_processed_time = {} 
        self.current_ticker_index = 0
        self.daily_trade_count = 0
        self.last_trade_date = date.today() 
        self._initialize_state_from_upbit()

    def _connect_upbit(self):
        try:
            access = self.config.get('ACCESS_KEY')
            secret = self.config.get('SECRET_KEY')
            if not access or not secret: return None
            return pyupbit.Upbit(access, secret)
        except Exception: return None

    def _initialize_state_from_upbit(self):
        # (원본 유지)
        if not self.upbit:
            print("업비트 미연결로 잔고 동기화 스킵.")
            return
        try:
            configured_tickers = self.config.get('TICKERS', [])
            if not configured_tickers:
                print("설정된 TICKERS 목록이 비어있습니다.")
                return
            configured_coin_codes = {t.split('-')[1] for t in configured_tickers}
            all_balances = self.upbit.get_balances()
            found_coins = set()
            if all_balances:
                for item in all_balances:
                    coin_code = item['currency']
                    if coin_code in configured_coin_codes:
                        balance = float(item.get('balance', '0'))
                        avg_price = float(item.get('avg_buy_price', '0'))
                        ticker = f"KRW-{coin_code}" 
                        if balance > 0:
                            self.positions[ticker] = {
                                'total_volume': balance,
                                'average_buy_price': avg_price,
                                'total_buy_cost': balance * avg_price,
                                'buy_time': None, 'last_sell_time': None, 
                                'stop_loss_price': None, 'target_price': None,
                            }
                            print(f"🔄 봇 재시작: {ticker} 잔고 {balance:.8f}개 (평단 {avg_price:,.0f} KRW) 복원.")
                            found_coins.add(ticker)
            for ticker in configured_tickers:
                if ticker not in found_coins:
                    self.positions[ticker] = {
                        'total_volume': 0, 'average_buy_price': 0, 'total_buy_cost': 0,
                        'buy_time': None, 'last_sell_time': None, 
                        'stop_loss_price': None, 'target_price': None,
                    }
                    print(f"🔄 봇 재시작: {ticker} 보유 잔고가 없어 0으로 초기화합니다.")
        except Exception as e:
            print(f"전체 잔고 동기화 중 오류 발생: {e}")
            self.positions = {}
        
        self.last_processed_time = {} 

    def get_balance(self, ticker):
        if self.upbit: return self.upbit.get_balance(ticker)
        return 0

    # --- [★논문 반영 수정★] ---
    def _get_weights_for_ticker(self, cfg, ticker):
        """
        설정(cfg)에서 해당 ticker에 맞는 가중치 딕셔너리를 반환합니다.
        코인별 설정이 없으면 'default' 설정을 반환합니다.
        (config.py의 'STRATEGY_WEIGHTS_BY_COIN' 항목 참조)
        """
        # config.py 또는 config.json에서 새 구조를 읽어옵니다.
        all_weights_config = cfg.get('STRATEGY_WEIGHTS_BY_COIN', {})
        
        # 1. 'default' 가중치를 기본값으로 로드합니다.
        final_weights = all_weights_config.get('default', {}).copy()
        
        # 2. 이 코인('ticker')만의 특정 가중치가 있는지 확인합니다.
        coin_specific_weights = all_weights_config.get(ticker, {})
        
        # 3. 기본값에 코인별 특정 가중치를 덮어씁니다.
        final_weights.update(coin_specific_weights)
        
        if not final_weights:
             print(f"경고: [{ticker}] 가중치 설정을 찾을 수 없습니다. config의 'STRATEGY_WEIGHTS_BY_COIN'을 확인하세요.")
             # 비어있는 경우, 기존 STRATEGY_WEIGHTS를 한번 더 찾아봅니다. (하위 호환)
             final_weights = cfg.get('STRATEGY_WEIGHTS', {}).copy()

        return final_weights
    # --- [★수정 완료★] ---

    # --- ★★★ [수정됨] MFI, OBV 지표 추가 ★★★ ---
    def get_trading_data(self, ticker):
        try:
            interval = self.config.get('TIME_INTERVAL', 'minute60')
            # MFI, OBV 계산을 위해 캔들 수 200개로 증가
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=200) 
            if df is None or df.empty: 
                print(f"[{ticker}] get_ohlcv 데이터 없음.")
                return None
            
            # (기존 지표)
            try: df.ta.rsi(close='close', length=14, append=True)
            except Exception as e: print(f"[{ticker}] (get_data) RSI 계산 오류: {e}")
            try: df.ta.macd(close='close', fast=12, slow=26, signal=9, append=True)
            except Exception as e: print(f"[{ticker}] (get_data) MACD 계산 오류: {e}")
            try: df.ta.bbands(close='close', length=20, std=2, append=True)
            except Exception as e: print(f"[{ticker}] (get_data) BBANDS 계산 오류: {e}")
            try: df.ta.stoch(high='high', low='low', close='close', append=True)
            except Exception as e: print(f"[{ticker}] (get_data) STOCH 계산 오류: {e}")
            try: df.ta.atr(high='high', low='low', close='close', length=14, append=True)
            except Exception as e: print(f"[{ticker}] (get_data) ATR 계산 오류: {e}")
            try:
                ema_period = self.config.get('EMA_TREND_PERIOD', 50)
                df.ta.ema(close='close', length=ema_period, append=True)
            except Exception as e: print(f"[{ticker}] (get_data) EMA 계산 오류: {e}")
            
            # --- [★신규 지표 추가★] ---
            # MFI (Money Flow Index)
            try:
                df.ta.mfi(high='high', low='low', close='close', volume='volume', length=14, append=True)
            except Exception as e: print(f"[{ticker}] (get_data) MFI 계산 오류: {e}")
            
            # OBV (On-Balance Volume)
            try:
                df.ta.obv(close='close', volume='volume', append=True)
                # OBV의 이동평균선 계산 (app.py 설정값)
                obv_ma_period = self.config.get('OBV_MA_PERIOD', 20)

                # --- [★수정★] 'OBV_' 필터가 'OBV' 컬럼을 찾지 못하는 오류 수정 ---
                obv_col = None
                for col in df.columns:
                    if col == 'OBV': # pandas_ta v0.3.14b0 기준, 'OBV'로 생성됨
                        obv_col = col
                        break
                
                if obv_col is None:
                    # 'OBV'가 없으면, 'OBV_'로 시작하는 컬럼을 다시 시도 (예: OBV_...)
                    obv_cols = [col for col in df.columns if col.startswith('OBV') and 'EMA' not in col]
                    if obv_cols:
                        obv_col = obv_cols[0]
                    else:
                        raise Exception("OBV 컬럼('OBV')을 찾을 수 없습니다.") # 에러 발생시켜 catch로 넘김
                
                # --- [★수정★] append=True와 col=... 인자 충돌로 인한 오류 수정 ---
                # OBV EMA를 별도로 계산하고, 원하는 이름으로 컬럼에 직접 할당
                obv_ema = df.ta.ema(close=df[obv_col], length=obv_ma_period) 
                if obv_ema is not None:
                    df[f"OBV_EMA_{obv_ma_period}"] = obv_ema
                else:
                    raise Exception("OBV EMA 계산 실패 (결과가 None입니다.)")
                # --- [★수정 완료★] ---
                
            except Exception as e: 
                print(f"[{ticker}] (get_data) OBV 계산 오류: {e}")
                # --- [★수정★] 오류 발생 시 상위로 전파 (봇 중지 방지) ---
                raise e 
            # --- [★추가 완료★] ---

            try:
                volume_ma_period = self.config['STRATEGY_THRESHOLDS'].get('VOLUME_MA_PERIOD', 20)
                df['volume_ma'] = df['volume'].rolling(window=volume_ma_period).mean()
                df['volume_ma_5'] = df['volume'].rolling(window=5).mean()
            except Exception as e: print(f"[{ticker}] (get_data) 거래량 MA 계산 오류: {e}")

            df_dropped = df.dropna()
            if df_dropped.empty:
                print(f"[{ticker}] dropna() 후 데이터 없음. (원본 {len(df)}행)")
                return None

            return df_dropped
        
        except Exception as e:
            print(f"[{ticker}] 전체 데이터 조회 오류: {e}")
            return None
    
    # (원본 유지)
    def _find_divergence(self, df, price_col, indicator_col, lookback_period=40, order=5):
        try:
            if len(df) < lookback_period: return None
            df_slice = df.iloc[-lookback_period:]
            indicator_peaks, _ = find_peaks(df_slice[indicator_col], distance=order)
            if len(indicator_peaks) >= 2:
                last_peak_idx = indicator_peaks[-1]; prev_peak_idx = indicator_peaks[-2]
                if (df_slice.iloc[last_peak_idx][indicator_col] < df_slice.iloc[prev_peak_idx][indicator_col] and
                    df_slice.iloc[last_peak_idx][price_col] > df_slice.iloc[prev_peak_idx][price_col]):
                    return 'bearish'
            indicator_troughs, _ = find_peaks(-df_slice[indicator_col], distance=order)
            if len(indicator_troughs) >= 2:
                last_trough_idx = indicator_troughs[-1]; prev_trough_idx = indicator_troughs[-2]
                if (df_slice.iloc[last_trough_idx][indicator_col] > df_slice.iloc[prev_peak_idx][indicator_col] and
                    df_slice.iloc[last_trough_idx][price_col] < df_slice.iloc[prev_peak_idx][price_col]):
                    return 'bullish'
            return None
        except Exception as e: return None

    # (원본 유지)
    def _get_htf_trend(self, ticker, interval, ema_period=20):
        try:
            df_htf = pyupbit.get_ohlcv(ticker, interval=interval, count=ema_period + 5)
            if df_htf is None or len(df_htf) < ema_period:
                return 'neutral' 
            
            df_htf.ta.ema(close='close', length=ema_period, append=True)
            ema_col = df_htf.filter(like=f'EMA_{ema_period}').columns[0]
            latest = df_htf.iloc[-1]
            
            if latest['close'] > latest[ema_col]:
                return 'up'
            elif latest['close'] < latest[ema_col]:
                return 'down'
            else:
                return 'neutral'
        except Exception as e:
            print(f"[{ticker}] HTF({interval}) 조회 오류: {e}")
            return 'neutral' 

    # (원본 유지)
    def _check_liquidity(self, ticker):
        try:
            max_spread = self.config['STRATEGY_THRESHOLDS'].get('MAX_SPREAD_PERCENT', 0.5)
            min_depth = self.config['STRATEGY_THRESHOLDS'].get('MIN_ORDERBOOK_DEPTH_KRW', 1000000)

            orderbook = pyupbit.get_orderbook(ticker=ticker)
            if not orderbook or not orderbook.get('orderbook_units'):
                return False, "호가북 조회 실패"

            top_ask = orderbook['orderbook_units'][0]['ask_price']
            top_bid = orderbook['orderbook_units'][0]['bid_price']
            
            spread_percent = ((top_ask - top_bid) / top_ask) * 100
            if spread_percent > max_spread:
                return False, f"스프레드 과다 ({spread_percent:.2f}%)"
            
            top_bid_value = top_bid * orderbook['orderbook_units'][0]['bid_size']
            if top_bid_value < min_depth:
                 return False, f"호가 깊이 부족 ({top_bid_value:,.0f}원)"

            return True, "양호"
        except Exception as e:
            print(f"[{ticker}] 유동성 체크 오류: {e}")
            return False, f"유동성 체크 오류: {e}"

    # --- ★★★ [수정됨] run_once (펀딩비, MFI, OBV 로직 추가) ★★★ ---
    def run_once(self):
        # --- [★수정★] config.load_config()가 None을 반환할 경우(파일 손상 등)에 대한 방어 코드 ---
        new_config = config.load_config()
        if new_config is not None:
            self.config = new_config
        # else: new_config가 None이면 (파일 읽기 실패), 기존 self.config (메모리에 로드된 값)를 그대로 사용합니다.
        # -----------------------------------------------------------------
        
        if not self.upbit: return "업비트 미연결 상태", None, False, ""
        
        today = date.today()
        if today != self.last_trade_date:
            print(f"--- 날짜 변경 ({self.last_trade_date} -> {today}), 일일 거래 횟수 초기화 ---")
            self.daily_trade_count = 0
            self.last_trade_date = today
        
        max_trades = self.config.get('MAX_TRADES_PER_DAY', 999) 
        if self.daily_trade_count >= max_trades:
            return f"일일 최대 거래 횟수({max_trades}회) 도달. 신규 거래 중단.", None, False, ""

        tickers = self.config.get('TICKERS', [])
        if not tickers:
            return "거래할 Tickers 목록이 비어있습니다.", None, False, ""
            
        if self.current_ticker_index >= len(tickers): self.current_ticker_index = 0
        ticker = tickers[self.current_ticker_index]
        self.current_ticker_index = (self.current_ticker_index + 1) % len(tickers)
        
        # --- [★추가★] 펀딩비 조회 ---
        funding_rate, fr_status = None, "N/A"
        if self.config.get('USE_FUNDING_RATE_FILTER', True):
            try:
                funding_rate, fr_status = binance_fetcher.get_binance_funding_rate(ticker)
            except Exception as e:
                print(f"[{ticker}] 펀딩비 조회 모듈 에러: {e}")
                fr_status = f"모듈 에러: {e}"
        # --- [★추가 완료★] ---

        if self.config.get('USE_LIQUIDITY_FILTER', False):
            is_liquid, reason = self._check_liquidity(ticker)
            if not is_liquid:
                return f"[{ticker}] 유동성 부족으로 스킵: {reason}", None, False, ""

        df = self.get_trading_data(ticker)
        if df is None or len(df) < 3: 
            return f"[{ticker}] 데이터 조회 실패 (캔들 수: {len(df) if df is not None else 0})", None, False, ""

        latest_candle = df.iloc[-1] 
        previous_candle = df.iloc[-2] 
        latest_candle_time = latest_candle.name 
        last_processed = self.last_processed_time.get(ticker)
        
        is_new_candle = False
        if last_processed != latest_candle_time:
            is_new_candle = True
            self.last_processed_time[ticker] = latest_candle_time

        position = self.positions.get(ticker, {
            'total_volume': 0, 'average_buy_price': 0, 'total_buy_cost': 0,
            'buy_time': None, 'last_sell_time': None,
            'stop_loss_price': None, 'target_price': None,
        })
        
        price = latest_candle['close'] 
        
        unrealized_pnl_percent = 0; unrealized_pnl_krw = 0
        if position['total_volume'] > 0 and position['average_buy_price'] > 0:
            price_diff = (price - position['average_buy_price'])
            unrealized_pnl_percent = (price_diff / position['average_buy_price']) * 100 
            unrealized_pnl_krw = price_diff * position['total_volume']
        
        use_atr_sltp = self.config.get('USE_ATR_SLTP', False)
        use_profit_take = self.config.get('USE_PROFIT_TAKE', False)
        profit_take_percent = self.config.get('PROFIT_TAKE_PERCENT', 100.0)
        atr_target_price = position.get('target_price')

        tp_triggered = False
        tp_reason = ""
        
        # 1. (익절 체크) (원본 유지)
        if position['total_volume'] > 0 and is_new_candle:
            if use_atr_sltp and atr_target_price and price >= atr_target_price:
                tp_triggered = True
                tp_reason = f"ATR 동적 익절가({atr_target_price:,.0f}원) 도달"
            elif not use_atr_sltp and use_profit_take and unrealized_pnl_percent >= profit_take_percent:
                 tp_triggered = True
                 tp_reason = f"수익률 익절({profit_take_percent}%) 도달"

        if tp_triggered:
            coin_code = ticker.split('-')[1]; balance = self.get_balance(coin_code)
            if balance > 0 and balance * price > 5000:
                sell_method = self.config.get('SELL_METHOD', 'all'); sell_ratio = self.config.get('SELL_RATIO', 100)
                available_volume = min(balance, position['total_volume']) if position['total_volume'] > 0 else balance
                sell_volume = available_volume * (sell_ratio / 100.0) if sell_method == 'ratio' else available_volume
                if sell_volume * price > 5000:
                    profit = (price - position['average_buy_price']) * sell_volume
                    pnl_percent = unrealized_pnl_percent; sell_info = f"{sell_ratio}%({sell_volume:.8f}개)" if sell_method == 'ratio' else "전량"
                    log_msg = f"💰 [{ticker} 익절 매도 ({sell_info})] 이유: [{tp_reason}] | 현재가: {price:,.0f} | 실현 손익: {profit:,.0f}원 ({pnl_percent:.2f}%)"
                    self.upbit.sell_market_order(ticker, sell_volume) 
                    trade_result = {'time': datetime.now(), 'ticker': ticker, 'side': 'sell', 'price': price, 'volume': sell_volume, 'profit': profit, 'avg_buy_price': position['average_buy_price'], 'reason': tp_reason}
                    
                    self.daily_trade_count += 1 
                    position['last_sell_time'] = latest_candle_time 
                    
                    if sell_method == 'all' or (position['total_volume'] - sell_volume < 1e-9):
                        self.positions[ticker] = {'total_volume': 0, 'average_buy_price': 0, 'total_buy_cost': 0, 'buy_time': None, 'last_sell_time': position['last_sell_time'], 'stop_loss_price': None, 'target_price': None}
                    else:
                        position['total_volume'] -= sell_volume
                        position['total_buy_cost'] = position['total_volume'] * position['average_buy_price']
                    return log_msg, trade_result, False, "" 
        
        # --- ★★★ 2. (손절 체크) (부분 손절 로직 포함된 최신 버전 유지) ★★★ ---
        if position['total_volume'] > 0 and is_new_candle:
            sl_reason = ""
            
            atr_stop_price = position.get('stop_loss_price')
            if use_atr_sltp and atr_stop_price and price <= atr_stop_price:
                sl_reason = f"ATR 동적 손절가({atr_stop_price:,.0f}원) 도달"
            
            loss_cut_percent = self.config.get('LOSS_CUT_PERCENT', -100.0)
            if not sl_reason and unrealized_pnl_percent <= loss_cut_percent:
                sl_reason = f"손실 제한선({loss_cut_percent}%) 도달 (현재 {unrealized_pnl_percent:.2f}%)"

            change_percent = ((latest_candle['close'] - latest_candle['open']) / latest_candle['open']) * 100
            volatility_threshold = self.config.get('VOLATILITY_STOP_PERCENT', -100.0)
            if not sl_reason and change_percent <= volatility_threshold:
                sl_reason = f"변동성 위험 감지! 1시간 내 {change_percent:.2f}% 급락 (기준: {volatility_threshold}%)"
            
            if sl_reason and self.config.get('USE_AUTO_STOP_LOSS_SELL', True):
                coin_code = ticker.split('-')[1]; balance = self.get_balance(coin_code)
                if balance > 0 and balance * price > 5000:
                    
                    available_volume = min(balance, position['total_volume']) if position['total_volume'] > 0 else balance
                    
                    # app.py에서 설정한 부분 손절 값 가져오기
                    use_partial_sl = self.config.get('USE_PARTIAL_STOP_LOSS', False)
                    partial_sl_ratio_percent = self.config.get('PARTIAL_STOP_LOSS_RATIO', 10)
                    
                    is_full_sell = not use_partial_sl 
                    sell_volume = 0
                    sell_info = ""

                    if is_full_sell:
                        sell_volume = available_volume
                        sell_info = "전량"
                    else:
                        sell_ratio = partial_sl_ratio_percent / 100.0
                        sell_volume = available_volume * sell_ratio
                        sell_info = f"부분 손절 {partial_sl_ratio_percent}%"

                    if sell_volume * price > 5000:
                        profit = (price - position['average_buy_price']) * sell_volume
                        pnl_percent = unrealized_pnl_percent
                        
                        log_msg = f"🚨 [{ticker} 자동 손절 매도 ({sell_info})] 이유: [{sl_reason}] | 현재가: {price:,.0f} | 실현 손익: {profit:,.0f}원 ({pnl_percent:.2f}%)"
                        self.upbit.sell_market_order(ticker, sell_volume) 
                        trade_result = {'time': datetime.now(), 'ticker': ticker, 'side': 'sell', 'price': price, 'volume': sell_volume, 'profit': profit, 'avg_buy_price': position['average_buy_price'], 'reason': sl_reason}
                        
                        self.daily_trade_count += 1 
                        position['last_sell_time'] = latest_candle_time 
                        
                        if is_full_sell or (position['total_volume'] - sell_volume < 1e-9):
                            self.positions[ticker] = {'total_volume': 0, 'average_buy_price': 0, 'total_buy_cost': 0, 'buy_time': None, 'last_sell_time': position['last_sell_time'], 'stop_loss_price': None, 'target_price': None}
                        else:
                            position['total_volume'] -= sell_volume
                            position['total_buy_cost'] = position['total_volume'] * position['average_buy_price']
                        
                        return log_msg, trade_result, False, "" 
                    else:
                        return f"[{ticker}] 손절 조건 도달: {sl_reason} | (최소 주문 금액 미달, 봇 정지)", None, True, sl_reason
                else:
                    return f"[{ticker}] 손절 조건 도달: {sl_reason} | (잔고 부족, 봇 정지)", None, True, sl_reason
            
            elif sl_reason: 
                return f"[{ticker}] 리스크 감지 (손절 대기): {sl_reason} | 현재 손익: {unrealized_pnl_percent:.2f}%", None, True, sl_reason


        # --- [★수정★] 3. (지표 분석) MFI, OBV 컬럼 추가 ---
        try:
            # (기존 지표)
            rsi_col = df.filter(like='RSI_').columns[0]
            macd_col = df.filter(like='MACD_').columns[0]
            bbl_col = df.filter(like='BBL_').columns[0]
            bbu_col = df.filter(like='BBU_').columns[0]
            stoch_k_col = df.filter(like='STOCHk_').columns[0]
            stoch_d_col = df.filter(like='STOCHd_').columns[0]
            
            # --- [★수정★] ATRr 컬럼 조회 로직 ---
            atr_col = None
            if not df.filter(like='ATRr_').columns.empty:
                atr_col = df.filter(like='ATRr_').columns[0]
            elif not df.filter(like='ATR_').columns.empty:
                atr_col = df.filter(like='ATR_').columns[0]
            else:
                raise IndexError("ATR (ATRr_ or ATR_) 컬럼을 찾을 수 없습니다.")
            # --- [★수정 완료★] ---

            ema_period = self.config.get('EMA_TREND_PERIOD', 50)
            ema_col = df.filter(like=f'EMA_{ema_period}').columns[0]

            if not df.filter(like='MACDs_MOM_').columns.empty:
                macds_col = df.filter(like='MACDs_MOM_').columns[0]
            elif not df.filter(like='MACDs_').columns.empty:
                macds_col = df.filter(like='MACDs_').columns[0]
            else:
                raise IndexError("MACD Signal (MACDs) 컬럼을 찾을 수 없습니다.")
                
            # --- [★신규 지표 컬럼★] ---
            mfi_col = df.filter(like='MFI_').columns[0]
            
            # --- [★수정★] 'OBV_' 필터가 'OBV' 컬럼을 찾지 못하는 오류 수정 ---
            obv_col = None
            for col in df.columns:
                if col == 'OBV':
                    obv_col = col
                    break
            
            if obv_col is None:
                obv_cols = [col for col in df.columns if col.startswith('OBV') and 'EMA' not in col]
                if obv_cols:
                    obv_col = obv_cols[0]
                else:
                    raise IndexError("OBV 컬럼('OBV')을 찾을 수 없습니다.")
            # --- [★수정 완료★] ---

            obv_ma_period = self.config.get('OBV_MA_PERIOD', 20)
            obv_ma_col = df.filter(like=f'OBV_EMA_{obv_ma_period}').columns[0]
            # --- [★추가 완료★] ---
                
        except IndexError as e: 
            print(f"[{ticker}] (run_once) 누락된 보조지표 컬럼이 있습니다. 현재 컬럼 목록: {list(df.columns)}. 오류: {e}")
            return f"[{ticker}] 보조지표 컬럼 찾기 실패", None, False, ""
        
        # (기존 분석)
        rsi_divergence = self._find_divergence(df, 'close', rsi_col, lookback_period=40, order=5)
        is_volume_fading = latest_candle['volume'] < latest_candle['volume_ma_5']
        current_volume = latest_candle['volume']; volume_ma = latest_candle['volume_ma'] 
        volume_spike_multiplier = self.config['STRATEGY_THRESHOLDS'].get('VOLUME_SPIKE_MULTIPLIER', 1.5)
        is_volume_spike = current_volume > (volume_ma * volume_spike_multiplier) if not pd.isna(volume_ma) else False
        
        # (기존 지표 값)
        rsi_val, macd_val, macds_val = latest_candle[rsi_col], latest_candle[macd_col], latest_candle[macds_col]
        bbl_val, bbu_val = latest_candle[bbl_col], latest_candle[bbu_col]
        k_latest, d_latest = latest_candle[stoch_k_col], latest_candle[stoch_d_col]
        k_previous, d_previous = previous_candle[stoch_k_col], previous_candle[stoch_d_col]
        latest_atr = latest_candle[atr_col] 
        latest_ema = latest_candle[ema_col] 

        # --- [★신규 지표 값★] ---
        mfi_val = latest_candle[mfi_col]
        latest_obv = latest_candle[obv_col] # [수정] obv_col 변수 사용
        latest_obv_ma = latest_candle[obv_ma_col]
        # --- [★추가 완료★] ---

        # --- [★논문 반영 수정★] 4. (점수 계산) ---
        buy_score, sell_score = 0, 0; buy_reasons, sell_reasons = [], []
        
        # [★수정★] 코인별 가중치를 가져옵니다.
        cfg_w = self._get_weights_for_ticker(self.config, ticker) 
        cfg_t = self.config['STRATEGY_THRESHOLDS'] 
        # --- [★수정 완료★] ---

        # (Buy Signals - 기존)
        is_oversold = rsi_val < cfg_t['RSI_LOW']
        if is_oversold:
            if is_volume_fading: 
                buy_score += cfg_w.get('RSI_BUY_SCORE', 0) # .get()으로 안전하게 접근
                buy_reasons.append(f"RSI 과매도({rsi_val:.1f})+거래량 감소")
            else: 
                buy_score += cfg_w.get('RSI_BUY_SCORE', 0) / 2 
                buy_reasons.append(f"RSI 과매도({rsi_val:.1f})")
        if price < bbl_val: 
            buy_score += cfg_w.get('BBANDS_BUY_SCORE', 0)
            buy_reasons.append(f"볼린저 하단 ({price:,.0f} < {bbl_val:,.0f})") 
        if macd_val > macds_val: 
            buy_score += cfg_w.get('MACD_BUY_SCORE', 0)
            buy_reasons.append(f"MACD GC ({macd_val:.2f} > {macds_val:.2f})") 
        if k_previous < d_previous and k_latest > d_latest and k_latest < cfg_t['STOCH_LOW']: 
            buy_score += cfg_w.get('STOCH_BUY_SCORE', 0)
            buy_reasons.append(f"Stoch GC@OS({k_latest:.1f})")
        if rsi_divergence == 'bullish':
            buy_score += 40 # 다이버전스는 고정 점수 (혹은 cfg_w에 추가)
            buy_reasons.append("RSI 상승 다이버전스")
        if is_volume_spike and not is_oversold: 
            buy_score += cfg_w.get('VOLUME_BUY_SCORE', 0)
            buy_reasons.append(f"거래량 급증(x{current_volume/volume_ma:.1f})") 

        # (Sell Signals - 기존)
        is_overbought = rsi_val > cfg_t['RSI_HIGH']
        if is_overbought:
            if is_volume_spike:
                sell_score += 0 
                sell_reasons.append(f"RSI 과매수({rsi_val:.1f})+거래량 급증")
            elif is_volume_fading:
                sell_score += cfg_w.get('RSI_SELL_SCORE', 40)
                sell_reasons.append(f"RSI 과매수({rsi_val:.1f})+거래량 감소")
            else: 
                sell_score += cfg_w.get('RSI_SELL_SCORE', 40) / 2
                sell_reasons.append(f"RSI 과매수({rsi_val:.1f})")
        if price > bbu_val: 
            sell_score += cfg_w.get('BBANDS_SELL_SCORE', 40)
            sell_reasons.append(f"볼린저 상단 ({price:,.0f} > {bbu_val:,.0f})") 
        if macd_val < macds_val: 
            sell_score += cfg_w.get('MACD_SELL_SCORE', 20)
            sell_reasons.append(f"MACD DC ({macd_val:.2f} < {macds_val:.2f})") 
        if k_previous > d_previous and k_latest < d_latest and k_latest > cfg_t['STOCH_HIGH']: 
            sell_score += cfg_w.get('STOCH_SELL_SCORE', 0)
            sell_reasons.append(f"Stoch DC@OB({k_latest:.1f})")
        if rsi_divergence == 'bearish':
            sell_score += 60
            sell_reasons.append("RSI 하락 다이버전스")

        # (EMA 추세 점수 - 기존)
        if self.config.get('USE_EMA_TREND_SCORE', True):
            ema_weight = self.config.get('EMA_TREND_SCORE_WEIGHT', 15)
            if price > latest_ema: # 상승 추세
                buy_score += ema_weight
                sell_score -= ema_weight 
                buy_reasons.append(f"EMA({ema_period}) 상승추세")
            elif price < latest_ema: # 하락 추세
                buy_score -= ema_weight 
                sell_score += ema_weight
                sell_reasons.append(f"EMA({ema_period}) 하락추세")
        
        # --- [★신규 지표 점수★] ---
        
        # MFI 점수
        if self.config.get('USE_MFI_SCORE', True):
            mfi_high = cfg_t.get('MFI_HIGH', 80)
            mfi_low = cfg_t.get('MFI_LOW', 20)
            if mfi_val > mfi_high: # 과매수
                sell_score += cfg_w.get('MFI_SELL_SCORE', 15)
                sell_reasons.append(f"MFI 과매수({mfi_val:.1f})")
            if mfi_val < mfi_low: # 과매도
                buy_score += cfg_w.get('MFI_BUY_SCORE', 15)
                buy_reasons.append(f"MFI 과매도({mfi_val:.1f})")

        # OBV 점수
        if self.config.get('USE_OBV_SCORE', True):
            if latest_obv > latest_obv_ma: # 거래량 상승 추세
                buy_score += cfg_w.get('OBV_BUY_SCORE', 10)
                buy_reasons.append(f"OBV 상승추세(>MA{obv_ma_period})")
            elif latest_obv < latest_obv_ma: # 거래량 하락 추세
                sell_score += cfg_w.get('OBV_SELL_SCORE', 10)
                sell_reasons.append(f"OBV 하락추세(<MA{obv_ma_period})")

        # 펀딩비 점수 (위험 감지)
        fr_str = "N/A" # 로그에 표시할 문자열
        if self.config.get('USE_FUNDING_RATE_FILTER', True) and funding_rate is not None:
            fr_threshold_percent = self.config.get('FUNDING_RATE_THRESHOLD', 0.075)
            # app.py에서 0.075(%)로 받으므로 100으로 나눠서 실제 비율(0.00075)로 변환
            fr_threshold_raw = fr_threshold_percent / 100.0 
            
            funding_rate_percent = funding_rate * 100
            fr_str = f"{funding_rate_percent:.4f}%" # 로그용

            if funding_rate > fr_threshold_raw: # 펀딩비 과열 (롱 과열 -> 하락 위험)
                sell_score += cfg_w.get('FUNDING_RATE_SELL_SCORE', 20)
                sell_reasons.append(f"펀딩비 과열(>{fr_threshold_percent}%)")
        elif funding_rate is None and fr_status != "N/A":
            fr_str = fr_status # "API 오류" 등
        # --- [★신규 점수 완료★] ---

        reasons_log = ""
        if buy_reasons: reasons_log += f" | 매수신호: [{', '.join(buy_reasons)}]"
        if sell_reasons: reasons_log += f" | 매도신호: [{', '.join(sell_reasons)}]"
        
        log_status = "새 캔들 분석" if is_new_candle else "기존 캔들 모니터링"
        
        # --- [★수정★] 로그 메시지에 MFI, FR 추가 ---
        log_msg = f"[{ticker}] ({latest_candle_time.strftime('%Y-%m-%d %H:%M')}) {log_status} | 현재가: {price:,.0f} | RSI: {rsi_val:.1f} | MFI: {mfi_val:.1f} | FR: {fr_str} | EMA: {latest_ema:,.0f} | 매수점수: {int(buy_score)} | 매도점수: {int(sell_score)}{reasons_log}"
        
        if position['total_volume'] > 0 and position['average_buy_price'] > 0: 
            log_msg += f" | 보유: {position['total_volume']:.8f}개 | 평단: {position['average_buy_price']:,.0f} | 평가손익: {unrealized_pnl_krw:,.0f}원 ({unrealized_pnl_percent:.2f}%)"
        elif position['total_volume'] > 0:
             log_msg += f" | 보유: {position['total_volume']:.8f}개 | (평단 정보 없음)"

        # 5. (매매 실행) (원본 유지)
        trade_result = None
        
        passes_buy_filters = True
        filter_reasons = []
        is_first_buy = position['total_volume'] == 0 

        if self.config.get('USE_HTF_FILTER', False):
            htf_intervals = self.config.get('HTF_INTERVALS', ['minute240']) 
            htf_trend_aligned = True
            for interval in htf_intervals:
                htf_trend = self._get_htf_trend(ticker, interval)
                if htf_trend == 'down': 
                    htf_trend_aligned = False
                    break
            if not htf_trend_aligned:
                passes_buy_filters = False
                filter_reasons.append(f"HTF({interval}) 하락")

        if self.config.get('USE_VOLATILITY_FILTER', False):
            min_atr_percent = cfg_t.get('MIN_ATR_PERCENT', 0.5) 
            atr_percent = (latest_atr / price) * 100
            if atr_percent < min_atr_percent:
                passes_buy_filters = False
                filter_reasons.append(f"변동성 낮음(ATR {atr_percent:.2f}%)")
            
            min_volume_ratio = cfg_t.get('MIN_VOLUME_RATIO', 0.5) 
            if volume_ma > 0 and current_volume < (volume_ma * min_volume_ratio):
                 passes_buy_filters = False
                 filter_reasons.append(f"거래량 부족(MA 대비 {current_volume/volume_ma:.1f})")

        stop_loss_price, target_price = None, None
        if use_atr_sltp:
            sl_multiplier = cfg_t.get('ATR_SL_MULTIPLIER', 2.0)
            tp_multiplier = cfg_t.get('ATR_TP_MULTIPLIER', 3.0)
            sl_distance = latest_atr * sl_multiplier
            tp_distance = latest_atr * tp_multiplier
            fee_factor = self.config.get('FEE_FACTOR', 0.001) 
            stop_loss_price = price - sl_distance
            target_price = price + tp_distance + (price * fee_factor) 
            
            if sl_distance > 0:
                rr_ratio = tp_distance / sl_distance
                min_rr = cfg_t.get('MIN_REWARD_RISK_RATIO', 1.5)
                if rr_ratio < min_rr:
                    passes_buy_filters = False
                    filter_reasons.append(f"R:R 비율 낮음({rr_ratio:.1f}:1)")
            else:
                passes_buy_filters = False
                filter_reasons.append("ATR=0 (R:R 계산 불가)")
        
        cooldown_hours = self.config.get('ENTRY_COOLDOWN_HOURS', 0)
        last_sell_time = position.get('last_sell_time')
        if cooldown_hours > 0 and last_sell_time:
            if latest_candle_time < (last_sell_time + pd.Timedelta(hours=cooldown_hours)):
                passes_buy_filters = False
                filter_reasons.append("진입 쿨다운")

        # 5-1. 점수 기반 매수 (물타기 점수 가중치 적용)
        
        base_buy_threshold = self.config['SCORE_THRESHOLDS']['BUY']
        buy_threshold_met = False
        required_score = base_buy_threshold
        
        if is_first_buy:
            if buy_score >= base_buy_threshold:
                buy_threshold_met = True
        elif self.config.get('USE_HIGHER_AVG_DOWN_SCORE', True):
            multiplier = self.config.get('AVG_DOWN_SCORE_MULTIPLIER', 1.2)
            required_score = base_buy_threshold * multiplier
            if buy_score >= required_score:
                buy_threshold_met = True
            else:
                filter_reasons.append(f"물타기 점수 미달({int(buy_score)}/{int(required_score)})")
        else: 
            if buy_score >= base_buy_threshold:
                buy_threshold_met = True

        if (buy_threshold_met and 
            is_new_candle and 
            passes_buy_filters):
            
            krw = self.get_balance("KRW")
            
            buy_amount_krw = 0
            if self.config.get('USE_DYNAMIC_SIZING', False) and use_atr_sltp and (price - stop_loss_price) > 0:
                risk_per_trade_percent = self.config.get('RISK_PER_TRADE_PERCENT', 1.0)
                account_risk_krw = krw * (risk_per_trade_percent / 100.0)
                sl_distance_krw = price - stop_loss_price
                position_size_coin = account_risk_krw / sl_distance_krw
                buy_amount_krw = position_size_coin * price
                max_buy_ratio = self.config.get('MAX_BUY_RATIO_PER_TRADE', 0.25)
                buy_amount_krw = min(buy_amount_krw, krw * max_buy_ratio)
            else: 
                buy_amount_krw = self.config['BUY_AMOUNT_KRW']
            
            if krw >= buy_amount_krw and buy_amount_krw >= 5000: 
                buy_action_str = "신규 매수" if is_first_buy else f"추가 매수(물타기, {int(required_score)}점)"
                reasons_str = ", ".join(buy_reasons)
                log_msg = f"✅ [{ticker} {buy_action_str} 실행] 이유: [{reasons_str}] | 현재가: {price:,.0f} | 매수액: {buy_amount_krw:,.0f}원"
                if use_atr_sltp:
                    log_msg += f" | TP: {target_price:,.0f} | SL: {stop_loss_price:,.0f}"
                    
                self.upbit.buy_market_order(ticker, buy_amount_krw)
                buy_volume = buy_amount_krw / price 
                self.daily_trade_count += 1 
                
                if is_first_buy:
                    self.positions[ticker] = {
                        'total_volume': buy_volume, 'average_buy_price': price, 'total_buy_cost': buy_amount_krw,
                        'buy_time': latest_candle_time, 'last_sell_time': None,
                        'stop_loss_price': stop_loss_price, 'target_price': target_price,
                    }
                else:
                    new_total_cost = position['total_buy_cost'] + buy_amount_krw
                    new_total_volume = position['total_volume'] + buy_volume
                    new_avg_price = new_total_cost / new_total_volume
                    self.positions[ticker]['total_volume'] = new_total_volume
                    self.positions[ticker]['average_buy_price'] = new_avg_price
                    self.positions[ticker]['total_buy_cost'] = new_total_cost
                    log_msg += f" | (물타기 완료) 새 평단: {new_avg_price:,.0f} KRW, 총 보유: {new_total_volume:.8f}개"

                trade_result = {'time': datetime.now(), 'ticker': ticker, 'side': 'buy', 'price': price, 'volume': buy_volume, 'reason': reasons_str}
            
            elif position['total_volume'] > 0:
                 log_msg += f" | (추가 매수 신호, KRW 잔고 부족)"
            else:
                 log_msg += f" | (신규 매수 신호, KRW 잔고 부족)"
        
        elif (buy_score >= base_buy_threshold and 
              is_new_candle and 
              (not passes_buy_filters or not buy_threshold_met)):
            log_msg += f" | (매수 신호, 필터 미통과: {', '.join(filter_reasons)})"


        # 5-2. 점수 기반 매도 (원본 유지)
        min_hold_hours = self.config.get('MIN_HOLD_HOURS', 0)
        buy_time = position.get('buy_time')
        passes_sell_filters = True
        
        if min_hold_hours > 0 and buy_time:
             if latest_candle_time < (buy_time + pd.Timedelta(hours=min_hold_hours)):
                passes_sell_filters = False
                filter_reasons.append(f"최소 보유시간({min_hold_hours}h) 미도래")

        if (sell_score >= self.config['SCORE_THRESHOLDS']['SELL'] and 
            position['total_volume'] > 0 and 
            is_new_candle and
            passes_sell_filters):
            
            coin_code = ticker.split('-')[1]; balance = self.get_balance(coin_code)
            avg_buy_price_for_profit = position['average_buy_price'] if position['average_buy_price'] > 0 else price
            
            if balance > 0 and balance * price > 5000:
                sell_method = self.config.get('SELL_METHOD', 'all'); sell_ratio = self.config.get('SELL_RATIO', 100)
                available_volume = min(balance, position['total_volume']) if position['total_volume'] > 0 else balance
                sell_volume = available_volume * (sell_ratio / 100.0) if sell_method == 'ratio' else available_volume
                
                if sell_volume * price > 5000:
                    reasons_str = ", ".join(sell_reasons); 
                    profit = (price - avg_buy_price_for_profit) * sell_volume
                    pnl_percent = ((price - avg_buy_price_for_profit) / avg_buy_price_for_profit) * 100 if avg_buy_price_for_profit > 0 else 0
                    sell_info = f"{sell_ratio}%({sell_volume:.8f}개)" if sell_method == 'ratio' else "전량"
                    
                    log_msg = f"🛑 [{ticker} 분석 기반 매도 ({sell_info})] 이유: [{reasons_str}] | 현재가: {price:,.0f} | 실현 손익: {profit:,.0f}원 ({pnl_percent:.2f}%)"
                    self.upbit.sell_market_order(ticker, sell_volume)
                    trade_result = {'time': datetime.now(), 'ticker': ticker, 'side': 'sell', 'price': price, 'volume': sell_volume, 'profit': profit, 'avg_buy_price': avg_buy_price_for_profit, 'reason': reasons_str}
                    
                    self.daily_trade_count += 1 
                    position['last_sell_time'] = latest_candle_time 
                    
                    if sell_method == 'all' or (position['total_volume'] - sell_volume < 1e-9): 
                        self.positions[ticker] = {'total_volume': 0, 'average_buy_price': 0, 'total_buy_cost': 0, 'buy_time': None, 'last_sell_time': position['last_sell_time'], 'stop_loss_price': None, 'target_price': None}
                    else: 
                        position['total_volume'] -= sell_volume
                        position['total_buy_cost'] = position['total_volume'] * position['average_buy_price']
                else: log_msg += f" | [{ticker}] 매도 신호, 최소 주문 금액(5,000원) 미만"
        
        elif (sell_score >= self.config['SCORE_THRESHOLDS']['SELL'] and 
              position['total_volume'] > 0 and 
              is_new_candle and
              not passes_sell_filters):
             log_msg += f" | (매도 신호, 필터 미통과: {', '.join(filter_reasons)})"
        
        elif (buy_score >= required_score or sell_score >= self.config['SCORE_THRESHOLDS']['SELL']) and not is_new_candle: 
             log_msg += f" | (매매 점수 도달, 새 캔들 대기 중)"

        return log_msg, trade_result, False, ""

    # --- ★★★ [수정됨] get_comprehensive_judgment (MFI, OBV, FR 추가) ★★★ ---
    def get_comprehensive_judgment(self, ticker):
        try:
            # 펀딩비 먼저 조회
            funding_rate, fr_status = None, "N/A"
            if self.config.get('USE_FUNDING_RATE_FILTER', True):
                try:
                    funding_rate, fr_status = binance_fetcher.get_binance_funding_rate(ticker)
                except Exception as e:
                    fr_status = f"FR 조회 실패: {e}"

            # 업비트 데이터 조회 및 지표 계산
            df = self.get_trading_data(ticker) 
            if df is None or len(df) < 2: return {'judgment': '데이터 부족', 'signal_strength': '알 수 없음', 'confidence': 0, 'buy_score': 0, 'sell_score': 0, 'conditions_met': 0, 'total_conditions': 0}
            latest = df.iloc[-1]; previous = df.iloc[-2]; price = latest['close']

            try:
                # (기존 지표)
                rsi_col = df.filter(like='RSI_').columns[0]
                macd_col = df.filter(like='MACD_').columns[0]
                bbl_col = df.filter(like='BBL_').columns[0]
                bbu_col = df.filter(like='BBU_').columns[0]
                stoch_k_col = df.filter(like='STOCHk_').columns[0]
                stoch_d_col = df.filter(like='STOCHd_').columns[0]
                ema_period = self.config.get('EMA_TREND_PERIOD', 50)
                ema_col = df.filter(like=f'EMA_{ema_period}').columns[0]

                if not df.filter(like='MACDs_MOM_').columns.empty:
                    macds_col = df.filter(like='MACDs_MOM_').columns[0]
                elif not df.filter(like='MACDs_').columns.empty:
                    macds_col = df.filter(like='MACDs_').columns[0]
                else: raise IndexError("MACD Signal (MACDs) 컬럼을 찾을 수 없습니다.")

                # (신규 지표)
                mfi_col = df.filter(like='MFI_').columns[0]
                
                # --- [★수정★] 'OBV_' 필터가 'OBV' 컬럼을 찾지 못하는 오류 수정 ---
                obv_col = None
                for col in df.columns:
                    if col == 'OBV':
                        obv_col = col
                        break
                
                if obv_col is None:
                    obv_cols = [col for col in df.columns if col.startswith('OBV') and 'EMA' not in col]
                    if obv_cols:
                        obv_col = obv_cols[0]
                    else:
                         raise IndexError("OBV 컬럼('OBV')을 찾을 수 없습니다.")
                # --- [★수정 완료★] ---
                
                obv_ma_period = self.config.get('OBV_MA_PERIOD', 20)
                obv_ma_col = df.filter(like=f'OBV_EMA_{obv_ma_period}').columns[0]

            except IndexError as e:
                print(f"[{ticker}] (get_judgment) 누락된 보조지표 컬럼. 현재 컬럼 목록: {list(df.columns)}. 오류: {e}")
                return {'judgment': '분석 오류', 'signal_strength': '알 수 없음', 'confidence': 0, 'buy_score': 0, 'sell_score': 0, 'conditions_met': 0, 'total_conditions': 0, 'error': f'보조지표 컬럼 찾기 실패. 오류: {e}'}

            # (기존 값)
            rsi_val, macd_val, macds_val = latest[rsi_col], latest[macd_col], latest[macds_col]; bbl_val, bbu_val = latest[bbl_col], latest[bbu_col]; k_latest, d_latest = latest[stoch_k_col], latest[stoch_d_col]; k_previous, d_previous = previous[stoch_k_col], previous[stoch_d_col]
            current_volume = latest['volume']; volume_ma = latest['volume_ma']
            volume_spike_multiplier = self.config['STRATEGY_THRESHOLDS'].get('VOLUME_SPIKE_MULTIPLIER', 1.5)
            is_volume_spike = current_volume > (volume_ma * volume_spike_multiplier) if not pd.isna(volume_ma) else False
            latest_ema = latest[ema_col]
            
            # (신규 값)
            mfi_val = latest[mfi_col]
            latest_obv = latest[obv_col] # [수정] obv_col 변수 사용
            latest_obv_ma = latest[obv_ma_col]

            # --- [★논문 반영 수정★] ---
            # [★수정★] 코인별 가중치를 가져옵니다.
            cfg_w = self._get_weights_for_ticker(self.config, ticker)
            cfg_t = self.config['STRATEGY_THRESHOLDS'] 
            # --- [★수정 완료★] ---
            
            buy_conditions = []; buy_score = 0
            if rsi_val < cfg_t['RSI_LOW']: buy_conditions.append("RSI 과매도"); buy_score += cfg_w.get('RSI_BUY_SCORE', 0)
            if price < bbl_val: buy_conditions.append("볼린저밴드 하단"); buy_score += cfg_w.get('BBANDS_BUY_SCORE', 0)
            if macd_val > macds_val: buy_conditions.append("MACD 골든크로스"); buy_score += cfg_w.get('MACD_BUY_SCORE', 0)
            if k_previous < d_previous and k_latest > d_latest and k_latest < cfg_t['STOCH_LOW']: buy_conditions.append("스토캐스틱 과매도권 골든크로스"); buy_score += cfg_w.get('STOCH_BUY_SCORE', 0)
            if is_volume_spike: buy_conditions.append("거래량 급증"); buy_score += cfg_w.get('VOLUME_BUY_SCORE', 0)
            
            sell_conditions = []; sell_score = 0
            if rsi_val > cfg_t['RSI_HIGH']: sell_conditions.append("RSI 과매수"); sell_score += cfg_w.get('RSI_SELL_SCORE', 0)
            if price > bbu_val: sell_conditions.append("볼린저밴드 상단"); sell_score += cfg_w.get('BBANDS_SELL_SCORE', 0)
            if macd_val < macds_val: sell_conditions.append("MACD 데드크로스"); sell_score += cfg_w.get('MACD_SELL_SCORE', 0)
            if k_previous > d_previous and k_latest < d_latest and k_latest > cfg_t['STOCH_HIGH']: sell_conditions.append("스토캐스틱 과매수권 데드크로스"); sell_score += cfg_w.get('STOCH_SELL_SCORE', 0)
            if is_volume_spike: sell_conditions.append("거래량 급증"); sell_score += cfg_w.get('VOLUME_SELL_SCORE', 0)

            if self.config.get('USE_EMA_TREND_SCORE', True):
                ema_weight = self.config.get('EMA_TREND_SCORE_WEIGHT', 15)
                if price > latest_ema:
                    buy_conditions.append(f"EMA({ema_period}) 상승추세"); buy_score += ema_weight
                elif price < latest_ema:
                    sell_conditions.append(f"EMA({ema_period}) 하락추세"); sell_score += ema_weight

            # --- [★신규 지표 점수★] ---
            if self.config.get('USE_MFI_SCORE', True):
                if mfi_val > cfg_t.get('MFI_HIGH', 80): 
                    sell_conditions.append(f"MFI 과매수({mfi_val:.1f})"); sell_score += cfg_w.get('MFI_SELL_SCORE', 15)
                if mfi_val < cfg_t.get('MFI_LOW', 20): 
                    buy_conditions.append(f"MFI 과매도({mfi_val:.1f})"); buy_score += cfg_w.get('MFI_BUY_SCORE', 15)

            if self.config.get('USE_OBV_SCORE', True):
                if latest_obv > latest_obv_ma: 
                    buy_conditions.append(f"OBV 상승추세(>MA{obv_ma_period})"); buy_score += cfg_w.get('OBV_BUY_SCORE', 10)
                elif latest_obv < latest_obv_ma: 
                    sell_conditions.append(f"OBV 하락추세(<MA{obv_ma_period})"); sell_score += cfg_w.get('OBV_SELL_SCORE', 10)

            fr_str = "N/A"
            if self.config.get('USE_FUNDING_RATE_FILTER', True) and funding_rate is not None:
                fr_threshold_percent = self.config.get('FUNDING_RATE_THRESHOLD', 0.075)
                fr_threshold_raw = fr_threshold_percent / 100.0 
                fr_str = f"{(funding_rate * 100):.4f}%"
                if funding_rate > fr_threshold_raw: 
                    sell_conditions.append(f"펀딩비 과열(>{fr_threshold_percent}%)"); sell_score += cfg_w.get('FUNDING_RATE_SELL_SCORE', 20)
            elif funding_rate is None and fr_status != "N/A":
                fr_str = fr_status
            # --- [★신규 점수 완료★] ---
            
            total_conditions = len(buy_conditions) + len(sell_conditions); conditions_met = len(buy_conditions) if buy_score > sell_score else len(sell_conditions)
            if buy_score > sell_score: judgment = "롱 진입 고려"; signal_strength = self._get_signal_strength(buy_score, self.config['SCORE_THRESHOLDS']['BUY']); confidence = min(100, (buy_score / self.config['SCORE_THRESHOLDS']['BUY']) * 100)
            elif sell_score > buy_score: judgment = "숏 진입 고려"; signal_strength = self._get_signal_strength(sell_score, self.config['SCORE_THRESHOLDS']['SELL']); confidence = min(100, (sell_score / self.config['SCORE_THRESHOLDS']['SELL']) * 100)
            else: judgment = "중립 (대기 권장)"; signal_strength = "약한 신호"; confidence = 50
            
            # app.py의 분석 탭에 표시할 추가 정보
            extra_info = {
                'mfi': f"{mfi_val:.1f}",
                'obv_signal': "상승" if latest_obv > latest_obv_ma else "하락",
                'funding_rate': fr_str
            }

            return {'judgment': judgment, 'signal_strength': signal_strength, 'confidence': round(confidence, 1), 'buy_score': buy_score, 'sell_score': sell_score, 'conditions_met': conditions_met, 'total_conditions': total_conditions, 'buy_conditions': buy_conditions, 'sell_conditions': sell_conditions, 'extra_info': extra_info}
        
        except Exception as e: 
            return {'judgment': '분석 오류', 'signal_strength': '알 수 없음', 'confidence': 0, 'buy_score': 0, 'sell_score': 0, 'conditions_met': 0, 'total_conditions': 0, 'error': str(e)}

    # (원본 유지)
    def _get_signal_strength(self, score, threshold):
        ratio = score / threshold
        if ratio >= 1.2: return "강한 신호"
        elif ratio >= 1.0: return "보통 신호"
        elif ratio >= 0.7: return "약한 신호"
        else: return "매우 약한 신호"

    # --- ★★★ [수정됨] score_single_ticker_with_change (MFI, OBV 추가) ★★★ ---
    # (참고: 이 함수는 대량 조회를 하므로 속도 문제로 펀딩비는 제외합니다)
    def score_single_ticker_with_change(self, ticker, cfg):
        try:
            interval = cfg.get('TIME_INTERVAL', 'minute60')
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=200) # 넉넉하게 200개
            if df is None or df.empty: return None

            try: df.ta.rsi(close='close', length=14, append=True)
            except Exception as e: print(f"[{ticker}] (score) RSI 계산 오류: {e}")
            try: df.ta.macd(close='close', fast=12, slow=26, signal=9, append=True)
            except Exception as e: print(f"[{ticker}] (score) MACD 계산 오류: {e}")
            try: df.ta.bbands(close='close', length=20, std=2, append=True)
            except Exception as e: print(f"[{ticker}] (score) BBANDS 계산 오류: {e}")
            try: df.ta.stoch(high='high', low='low', close='close', append=True)
            except Exception as e: print(f"[{ticker}] (score) STOCH 계산 오류: {e}")
            try: df.ta.atr(high='high', low='low', close='close', length=14, append=True)
            except Exception as e: print(f"[{ticker}] (score) ATR 계산 오류: {e}")
            try:
                ema_period = cfg.get('EMA_TREND_PERIOD', 50)
                df.ta.ema(close='close', length=ema_period, append=True)
            except Exception as e: print(f"[{ticker}] (score) EMA 계산 오류: {e}")
            
            # --- [★신규 지표 추가 (MFI, OBV)★] ---
            try:
                df.ta.mfi(high='high', low='low', close='close', volume='volume', length=14, append=True)
            except Exception as e: print(f"[{ticker}] (score) MFI 계산 오류: {e}")
            try:
                df.ta.obv(close='close', volume='volume', append=True)
                obv_ma_period = cfg.get('OBV_MA_PERIOD', 20)
                
                # --- [★수정★] 'OBV_' 필터가 'OBV' 컬럼을 찾지 못하는 오류 수정 ---
                obv_col = None
                for col in df.columns:
                    if col == 'OBV':
                        obv_col = col
                        break
                
                if obv_col is None:
                    obv_cols = [col for col in df.columns if col.startswith('OBV') and 'EMA' not in col]
                    if obv_cols:
                        obv_col = obv_cols[0]
                    else:
                         raise Exception("OBV 컬럼('OBV')을 찾을 수 없습니다.")
                
                # --- [★수정★] append=True와 col=... 인자 충돌로 인한 오류 수정 ---
                # OBV EMA를 별도로 계산하고, 원하는 이름으로 컬럼에 직접 할당
                obv_ema = df.ta.ema(close=df[obv_col], length=obv_ma_period) 
                if obv_ema is not None:
                    df[f"OBV_EMA_{obv_ma_period}"] = obv_ema
                else:
                    raise Exception("OBV EMA 계산 실패 (결과가 None입니다.)")
                # --- [★수정 완료★] ---
            except Exception as e: 
                print(f"[{ticker}] (score) OBV 계산 오류: {e}")
                # --- [★수정★] 오류 발생 시 상위로 전파 (봇 중지 방지) ---
                raise e
            # --- [★추가 완료★] ---
            
            try:
                volume_ma_period = cfg['STRATEGY_THRESHOLDS'].get('VOLUME_MA_PERIOD', 20)
                df['volume_ma'] = df['volume'].rolling(window=volume_ma_period).mean()
            except Exception as e: print(f"[{ticker}] (score) 거래량 MA 계산 오류: {e}")

            df = df.dropna() 
            if df.empty or len(df) < 25: return None
            
            latest = df.iloc[-1]; previous = df.iloc[-2]
            one_hour_ago = df.iloc[-2]
            twenty_four_hours_ago = df.iloc[-25]
            change_1h = ((latest['close'] - one_hour_ago['close']) / one_hour_ago['close']) * 100 if one_hour_ago['close'] != 0 else 0
            change_24h = ((latest['close'] - twenty_four_hours_ago['close']) / twenty_four_hours_ago['close']) * 100 if twenty_four_hours_ago['close'] != 0 else 0
            
            try:
                # (기존 컬럼)
                rsi_col = df.filter(like='RSI_').columns[0]
                macd_col = df.filter(like='MACD_').columns[0]
                bbl_col = df.filter(like='BBL_').columns[0]
                bbu_col = df.filter(like='BBU_').columns[0]
                stoch_k_col = df.filter(like='STOCHk_').columns[0]
                stoch_d_col = df.filter(like='STOCHd_').columns[0]
                
                # --- [★수정★] ATRr 컬럼 조회 로직 ---
                atr_col = None
                if not df.filter(like='ATRr_').columns.empty:
                    atr_col = df.filter(like='ATRr_').columns[0]
                elif not df.filter(like='ATR_').columns.empty:
                    atr_col = df.filter(like='ATR_').columns[0]
                else:
                    raise IndexError("ATR (ATRr_ or ATR_) 컬럼을 찾을 수 없습니다.")
                # --- [★수정 완료★] ---

                ema_period = cfg.get('EMA_TREND_PERIOD', 50)
                ema_col = df.filter(like=f'EMA_{ema_period}').columns[0]
                
                if not df.filter(like='MACDs_MOM_').columns.empty:
                    macds_col = df.filter(like='MACDs_MOM_').columns[0]
                elif not df.filter(like='MACDs_').columns.empty:
                    macds_col = df.filter(like='MACDs_').columns[0]
                else: raise IndexError("MACD Signal (MACDs) 컬럼을 찾을 수 없습니다.")

                # (신규 컬럼)
                mfi_col = df.filter(like='MFI_').columns[0]

                # --- [★수정★] 'OBV_' 필터가 'OBV' 컬럼을 찾지 못하는 오류 수정 ---
                obv_col = None
                for col in df.columns:
                    if col == 'OBV':
                        obv_col = col
                        break
                
                if obv_col is None:
                    obv_cols = [col for col in df.columns if col.startswith('OBV') and 'EMA' not in col]
                    if obv_cols:
                        obv_col = obv_cols[0]
                    else:
                         raise IndexError("OBV 컬럼('OBV')을 찾을 수 없습니다.")
                # --- [★수정 완료★] ---
                
                obv_ma_period = cfg.get('OBV_MA_PERIOD', 20)
                obv_ma_col = df.filter(like=f'OBV_EMA_{obv_ma_period}').columns[0]

            except IndexError as e:
                print(f"[{ticker}] (score) 누락된 보조지표 컬럼. 현재 컬럼 목록: {list(df.columns)}. 오류: {e}")
                return None
            
            # --- [★논문 반영 수정★] ---
            thr = cfg['STRATEGY_THRESHOLDS']
            # [★수정★] 코인별 가중치를 가져옵니다.
            w = self._get_weights_for_ticker(cfg, ticker) 
            score = 0; reasons = []
            # --- [★수정 완료★] ---
            
            # (기존 값)
            rsi_val = latest[rsi_col]; macd_val, macds_val = latest[macd_col], latest[macds_col]; price = latest['close']
            bbl_val, bbu_val = latest[bbl_col], latest[bbu_col]; k_latest, d_latest = latest[stoch_k_col], latest[stoch_d_col]
            k_prev, d_prev = previous[stoch_k_col], previous[stoch_d_col]
            latest_ema = latest[ema_col]

            # (신규 값)
            mfi_val = latest[mfi_col]
            latest_obv = latest[obv_col] # [수정] obv_col 변수 사용
            latest_obv_ma = latest[obv_ma_col]
            
            # (기존 점수)
            if rsi_val < thr.get('RSI_LOW', 30): score += w.get('RSI_BUY_SCORE', 40); reasons.append('RSI 과매도')
            if rsi_val > thr.get('RSI_HIGH', 70): score -= w.get('RSI_SELL_SCORE', 40); reasons.append('RSI 과매수')
            if price < bbl_val: score += w.get('BBANDS_BUY_SCORE', 40); reasons.append('볼밴 하단')
            if price > bbu_val: score -= w.get('BBANDS_SELL_SCORE', 40); reasons.append('볼밴 상단')
            if macd_val > macds_val: score += w.get('MACD_BUY_SCORE', 20); reasons.append('MACD GC')
            if macd_val < macds_val: score -= w.get('MACD_SELL_SCORE', 20); reasons.append('MACD DC')
            if k_prev < d_prev and k_latest > d_latest and k_latest < thr.get('STOCH_LOW', 20): score += w.get('STOCH_BUY_SCORE', 30); reasons.append('Stoch GC@OS')
            if k_prev > d_prev and k_latest < d_latest and k_latest > thr.get('STOCH_HIGH', 80): score -= w.get('STOCH_SELL_SCORE', 30); reasons.append('Stoch DC@OB')
            volume_ma = latest['volume_ma']
            if not pd.isna(volume_ma) and latest['volume'] > volume_ma * thr.get('VOLUME_SPIKE_MULTIPLIER', 1.5): score += w.get('VOLUME_BUY_SCORE', 25); reasons.append('거래량 급증')
            if cfg.get('USE_EMA_TREND_SCORE', True):
                ema_weight = cfg.get('EMA_TREND_SCORE_WEIGHT', 15)
                if price > latest_ema:
                    score += ema_weight; reasons.append(f'EMA({ema_period}) 상승')
                elif price < latest_ema:
                    score -= ema_weight; reasons.append(f'EMA({ema_period}) 하락')

            # --- [★신규 지표 점수 (MFI, OBV)★] ---
            if cfg.get('USE_MFI_SCORE', True):
                if mfi_val > thr.get('MFI_HIGH', 80): 
                    score -= w.get('MFI_SELL_SCORE', 15); reasons.append(f'MFI 과매수')
                if mfi_val < thr.get('MFI_LOW', 20): 
                    score += w.get('MFI_BUY_SCORE', 15); reasons.append(f'MFI 과매도')
            
            if cfg.get('USE_OBV_SCORE', True):
                if latest_obv > latest_obv_ma: 
                    score += w.get('OBV_BUY_SCORE', 10); reasons.append(f'OBV 상승')
                elif latest_obv < latest_obv_ma: 
                    score -= w.get('OBV_SELL_SCORE', 10); reasons.append(f'OBV 하락')
            # --- [★신규 점수 완료★] ---
            
            atr_percent = (latest[atr_col] / price) * 100 if price > 0 else 0 
            
            return {'ticker': ticker, 'score': int(score), 'change_1h': round(float(change_1h), 2), 'change_24h': round(float(change_24h), 2), 'rsi': round(float(rsi_val), 1), 'mfi': round(float(mfi_val), 1), 'stoch_k': round(float(k_latest), 1), 'price': float(price), 'atr_pct': round(float(atr_percent), 2), 'reasons': ", ".join(reasons)}
        except Exception as e: 
            print(f"[{ticker}] score_single_ticker_with_change 전체 오류: {e}")
            return None

    # (원본 유지)
    def analyze_and_recommend_coins(self, cfg):
        top_percentage = cfg.get('RECOMMEND_TOP_PERCENTAGE', 20) 
        all_krw_tickers = []
        ticker_trade_volumes = []
        try:
            all_krw_tickers = pyupbit.get_tickers(fiat="KRW")
            if not all_krw_tickers: print("업비트 KRW 마켓 티커 목록 조회 실패"); return pd.DataFrame([])
            print(f"총 {len(all_krw_tickers)}개의 KRW 마켓 코인 확인. 각 코인 정보 조회 시작...")
            
            # (속도 개선을 위해 pyupbit.get_current_price로 거래대금 일괄 조회)
            all_tickers_info = pyupbit.get_current_price(all_krw_tickers)
            if not all_tickers_info:
                 print("  경고: get_current_price()로 티커 정보 조회 실패. 개별 조회로 전환합니다.")
                 # (기존 로직: 개별 조회)
                 for i, ticker in enumerate(all_krw_tickers):
                    try:
                        df_daily = pyupbit.get_ohlcv(ticker, interval="day", count=1) 
                        if df_daily is not None and not df_daily.empty:
                            trade_volume_24h = df_daily.iloc[-1]['value']
                            ticker_trade_volumes.append({'market': ticker, 'acc_trade_price_24h': trade_volume_24h})
                        else: print(f"  경고: {ticker} 일봉 데이터 조회 실패")
                        time.sleep(0.11) # Rate limit
                    except Exception as e:
                        print(f"  오류: {ticker} 정보 조회 중 오류 발생 - {e}")
                        time.sleep(0.11)
            else:
                 # (개선된 로직: 일괄 조회)
                 print("  (정보 일괄 조회 성공. 24시간 거래대금 기준 필터링)")
                 for ticker, info in all_tickers_info.items():
                     trade_volume_24h = info.get('acc_trade_price_24h', 0)
                     ticker_trade_volumes.append({'market': ticker, 'acc_trade_price_24h': trade_volume_24h})

            if not ticker_trade_volumes: print("거래대금 정보를 가진 코인을 찾지 못했습니다."); return pd.DataFrame([])
            sorted_tickers = sorted(ticker_trade_volumes, key=lambda x: x['acc_trade_price_24h'], reverse=True)
            top_n = int(len(sorted_tickers) * (top_percentage / 100)); top_n = max(1, top_n) 
            top_volume_tickers = [t['market'] for t in sorted_tickers[:top_n]] 
            print(f"거래량 상위 {top_percentage}% ({top_n}개) 코인 선별 완료. 상세 분석 시작...")
            print(f"대상 코인: {top_volume_tickers}")
        except Exception as e:
            print(f"거래량 상위 코인 필터링 중 오류: {e}"); return pd.DataFrame([])
        
        rows = []
        for i, t in enumerate(top_volume_tickers): 
            # (Rate Limit 준수)
            if i > 0: time.sleep(0.11) 
            r = self.score_single_ticker_with_change(t, cfg)
            if r is not None: rows.append(r)

        if not rows: print("분석 결과 데이터가 없습니다."); return pd.DataFrame([])
        df = pd.DataFrame(rows); df = df.sort_values(by='score', ascending=False).reset_index(drop=True)
        # (표시 컬럼에 mfi 추가)
        cols = ['ticker', 'score', 'change_1h', 'change_24h', 'rsi', 'mfi', 'stoch_k', 'atr_pct', 'price', 'reasons'] 
        df = df[[c for c in cols if c in df.columns]]
        return df