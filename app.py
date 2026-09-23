# app.py - [최종 수정본] MFI/OBV/펀딩비 설정 및 차트 추가
# [수정] st.session_state를 사용하여 로그 분석 결과가 유지되도록 수정
# [수정 2] 347행 f-string 문법 오류 수정
# [수정 3] 834행 update_live_data 함수 NameError (obv_col) 수정
# [★수정 4★] trade_history.json 파일 로드 및 저장 기능 추가
# [★수정 5★] 'ValueError: Invalid format string' 로그 오류 수정
# [★수정 6★] 'use_container_width' 경고를 'width'로 수정
# [★수정 7★] SyntaxError (코드가 잘림) 복구 및 논문 반영 로직(app.py) 적용
# [★수정 8★] 펀딩비 "N/A" 오류의 실제 원인을 표시하도록 수정
# [★수정 9★] 'binance_fetcher' is not defined (NameError) 오류 수정
# [★수정 10★] 보유 현황 중복 표시 버그 수정
# [★수정 11★] 실시간 손익/차트 깜빡임(flickering) 버그 수정
# [★수정 12★] 깜빡임/UI 멈춤 버그의 근본 원인(Scope) 수정

import streamlit as st
import pandas as pd
import time
from datetime import datetime
import json
import config
from trade_bot import TradingBot 
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pyupbit
import os
import logging
import sys 
import copy
import glob
import log_analyzer
import binance_fetcher  # [★수정 9★] 펀딩비 모듈 import 추가

# -----------------------------------------------------------------------------
# 0. [★신규★] 거래 내역 파일 설정 및 헬퍼 함수
# -----------------------------------------------------------------------------
TRADE_HISTORY_FILE = "trade_history.json"

def load_trade_history():
    """
    trade_history.json 파일에서 거래 내역을 로드합니다.
    """
    try:
        if os.path.exists(TRADE_HISTORY_FILE):
            with open(TRADE_HISTORY_FILE, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
                # [★데이터 검증 추가★]
                # 파일은 있으나 비어있는 경우
                if not history_data:
                    return []
                # 일부 항목에 ticker가 없는 경우를 대비
                for item in history_data:
                    if 'ticker' not in item:
                        item['ticker'] = 'UNKNOWN' # 누락된 티커 처리
                return history_data
    except json.JSONDecodeError:
        print(f"경고: {TRADE_HISTORY_FILE} 파일이 손상되었습니다. 새 파일로 시작합니다.")
        return []
    except Exception as e:
        print(f"거래 내역({TRADE_HISTORY_FILE}) 로드 실패: {e}")
    return []

def save_trade_history(history_list):
    """
    현재 거래 내역(list)을 trade_history.json 파일에 저장합니다.
    """
    try:
        with open(TRADE_HISTORY_FILE, 'w', encoding='utf-8') as f:
            # datetime 객체를 JSON으로 저장하기 위해 default=str 사용
            json.dump(history_list, f, indent=4, default=str) 
    except Exception as e:
        print(f"거래 내역({TRADE_HISTORY_FILE}) 저장 실패: {e}")
        # add_log는 logger.info를 호출하므로, 여기서는 print만 사용
        print(f"🔥 거래 내역 파일 저장 실패: {e}")

# -----------------------------------------------------------------------------
# 1. 로거 설정 및 유틸리티 함수 (★수정됨: 로그 포맷 오류 및 UI 핸들러 수정)
# -----------------------------------------------------------------------------
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR): os.makedirs(LOG_DIR)

# [★신규★] 밀리초(ms)를 지원하는 커스텀 포맷터
class MillisecondFormatter(logging.Formatter):
    """Custom formatter to include milliseconds."""
    def formatTime(self, record, datefmt=None):
        if datefmt:
            ct = datetime.fromtimestamp(record.created)
            if '%f' in datefmt:
                 # .%f를 .fff (3자리)로 변경하여 3자리 밀리초만 표시
                 s = ct.strftime(datefmt.replace('%f', '%f')[:-3]) 
            else:
                 s = ct.strftime(datefmt)
            return s
        else:
            return super().formatTime(record, datefmt)

# 로거를 전역으로 한 번만 가져옵니다.
logger = logging.getLogger("trade_bot_logger")
logger.setLevel(logging.INFO)
# [★수정★] 핸들러 중복 추가 방지를 위해 로거의 기존 핸들러 제거 (스크립트 재실행 시)
if logger.hasHandlers():
    logger.handlers.clear()

# [★신규★] Streamlit UI에 로그를 전송하는 핸들러 (클래스를 밖으로 이동)
class StreamlitLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            if 'logs' in st.session_state:
                st.session_state.logs.insert(0, msg)
                # 로그 최대 500줄 유지
                st.session_state.logs = st.session_state.logs[:500] 
        except Exception:
            pass # st.session_state 접근 실패 등 예외 처리

def setup_logging():
    """
    파일 로거와 Streamlit UI 로거를 설정합니다.
    (날짜가 바뀌면 자동으로 새 파일 핸들러로 교체합니다.)
    """
    today_str = datetime.now().strftime('%Y-%m-%d')
    log_file_name = f"{today_str}.log"
    log_file_path = os.path.join(LOG_DIR, log_file_name)
    
    # [★수정★] 로그 포맷: 밀리초를 포함
    datefmt_str = '%Y-%m-%d %H:%M:%S,%f'
    log_format = '[%(asctime)s] - %(message)s'
    
    found_file_handler = False
    found_ui_handler = False

    # 1. 현재 핸들러 확인 (날짜 지난 핸들러 제거)
    for handler in logger.handlers[:]: # 복사본 순회
        if isinstance(handler, logging.FileHandler):
            if handler.baseFilename == log_file_path:
                found_file_handler = True
            else:
                # 날짜가 지난 파일 핸들러는 제거
                handler.close()
                logger.removeHandler(handler)
        elif isinstance(handler, StreamlitLogHandler):
            found_ui_handler = True
            
    # 2. 파일 핸들러가 없으면 (날짜가 바뀌었거나 처음 시작) 추가
    if not found_file_handler:
        file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
        # [★수정★] 커스텀 포맷터 사용
        file_handler.setFormatter(MillisecondFormatter(log_format, datefmt=datefmt_str))
        logger.addHandler(file_handler)

    # 3. UI 핸들러가 없으면 추가
    if not found_ui_handler:
        ui_handler = StreamlitLogHandler()
        # [★수정★] 커스텀 포맷터 사용
        ui_handler.setFormatter(MillisecondFormatter(log_format, datefmt=datefmt_str))
        logger.addHandler(ui_handler)

def add_log(message):
    """
    오늘 날짜에 맞는 로그 파일 + Streamlit UI에 로그를 기록합니다.
    """
    try:
        # [★수정★] 로깅 전에 핸들러가 올바르게 설정되었는지 확인/설정
        setup_logging() 
        logger.info(message)
    except Exception as e:
        print(f"로그 기록 중 오류 발생: {e}")
        print(f"원본 메시지: {message}")

# -----------------------------------------------------------------------------
# 2. Streamlit 세션 상태 초기화
# -----------------------------------------------------------------------------
if 'bot' not in st.session_state:
    st.session_state.bot = None
if 'bot_status' not in st.session_state:
    st.session_state.bot_status = "stopped" # running, stopping
if 'logs' not in st.session_state:
    st.session_state.logs = [] # UI 표시용 로그
if 'last_log_time' not in st.session_state:
    st.session_state.last_log_time = datetime.now()

# [★수정★] 거래 내역을 파일에서 로드
if 'trade_history' not in st.session_state:
    st.session_state.trade_history = load_trade_history() 

if 'krw_balance' not in st.session_state:
    st.session_state.krw_balance = 0
if 'total_assets' not in st.session_state:
    st.session_state.total_assets = 0
if 'pnl_df' not in st.session_state: # [★추가★] 로그 분석 데이터 저장용
    st.session_state.pnl_df = None
    
# -----------------------------------------------------------------------------
# 3. Streamlit UI 구성
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide")
st.title("💰 업비트 자동매매 봇 대시보드 (다중 코인 + 위험지표)")
st.caption(f"최종 수정: 2025-11-04 | 신규 지표(MFI, OBV, 펀딩비) 및 로그 분석/거래내역 저장 기능 추가")

# [★갱신 주기★] 60초 간격 갱신은 실행 블록 하단의 time.sleep + st.rerun으로 처리합니다.

# --- [사이드바] ---
with st.sidebar:
    st.header("⚙️ 봇 설정")
    
    # 1. API 키 (필수)
    with st.expander("🔑 1. 업비트 API 키 (필수)", expanded=True):
        access_key = st.text_input("Access Key", type="password", value=config.UPBIT_ACCESS_KEY)
        secret_key = st.text_input("Secret Key", type="password", value=config.UPBIT_SECRET_KEY)

    # 2. 기본 설정
    with st.expander("⏱️ 2. 기본 매매 설정", expanded=True):
        all_tickers = ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE", "KRW-AVAX", "KRW-ADA", "KRW-LINK", "KRW-DOT", "KRW-MATIC"]
        default_tickers = config.TICKERS if config.TICKERS else ["KRW-BTC", "KRW-ETH", "KRW-SOL"]
        selected_tickers = st.multiselect(
            "거래할 코인 목록 (다중 선택 가능)", 
            all_tickers, 
            default=default_tickers
        )
        
        buy_amount_krw = st.number_input("1회 매수 금액 (KRW)", min_value=5000, value=config.BUY_AMOUNT_KRW, step=1000)
        time_interval = st.selectbox("분석할 캔들 시간 (Time Interval)", 
                                     ['minute60', 'minute240', 'day', 'minute30', 'minute15', 'minute5', 'minute3', 'minute1'], 
                                     index=config.TIME_INTERVALS.index(config.TIME_INTERVAL) if config.TIME_INTERVAL in config.TIME_INTERVALS else 0)
        max_trades_per_day = st.number_input("일일 최대 매매 횟수 (0=무제한)", min_value=0, value=config.MAX_TRADES_PER_DAY, step=1)
        
    # 3. 매매 방식
    with st.expander("📈 3. 매도 및 물타기 방식", expanded=True):
        st.write("--- 일반 매도 방식 (익절/분석) ---")
        sell_method = st.radio("매도 방식", ['all', 'ratio'], 
                               index=0 if config.SELL_METHOD == 'all' else 1, 
                               captions=["신호 발생 시 전량 매도", "신호 발생 시 설정 비율(%)만큼 부분 매도"])
        sell_ratio = st.slider("매도 비율 (%)", min_value=1.0, max_value=100.0, 
                               value=config.SELL_RATIO, step=1.0, 
                               disabled=(sell_method == 'all'))
        
        st.write("--- 추가 매수(물타기) 설정 ---")
        use_higher_avg_down_score = st.checkbox("물타기(추가 매수)시 더 높은 점수 요구", value=config.USE_HIGHER_AVG_DOWN_SCORE)
        avg_down_score_multiplier = st.slider("물타기 점수 가중치 (배수)", min_value=1.0, max_value=2.0, 
                                              value=config.AVG_DOWN_SCORE_MULTIPLIER, step=0.1,
                                              disabled=(not use_higher_avg_down_score))

    # 4. 익절 및 리스크 관리
    with st.expander("🛡️ 4. 익절 및 리스크 관리", expanded=True):
        use_profit_take = st.checkbox("수익률 기반 익절 사용", value=config.USE_PROFIT_TAKE)
        profit_take_percent = st.number_input("익절 수익률 (%)", min_value=0.1, value=config.PROFIT_TAKE_PERCENT, step=0.1,
                                              disabled=(not use_profit_take))
        
        st.write("--- 트레일링 스탑 (수익 보호) ---")
        use_trailing_stop = st.checkbox("트레일링 스탑 사용", value=config.USE_TRAILING_STOP)
        trailing_stop_percent = st.number_input("트레일링 스탑 하락률 (%)", min_value=1.0, max_value=20.0, 
                                                value=config.TRAILING_STOP_PERCENT, step=0.5,
                                                disabled=(not use_trailing_stop),
                                                help="최고가 대비 이 퍼센트만큼 하락 시 매도")
        
        st.write("--- 자동 손절 (리스크 관리) ---")
        use_auto_stop_loss_sell = st.checkbox("자동 손절 매도 기능 사용", value=config.USE_AUTO_STOP_LOSS_SELL)
        loss_cut_percent = st.number_input("손실 제한선 (%)", min_value=-100.0, max_value=-0.1, value=config.LOSS_CUT_PERCENT, step=0.1,
                                           disabled=(not use_auto_stop_loss_sell))
        
        use_partial_stop_loss = st.checkbox("손실 제한시 '부분 매도' 사용", 
                                            value=config.USE_PARTIAL_STOP_LOSS,
                                            disabled=(not use_auto_stop_loss_sell))
        partial_stop_loss_ratio = st.slider("부분 손절 매도 비율 (%)", min_value=1.0, max_value=100.0, 
                                             value=config.PARTIAL_STOP_LOSS_RATIO, step=1.0,
                                             disabled=(not use_auto_stop_loss_sell or not use_partial_stop_loss))
        
        volatility_stop_percent = st.number_input("변동성 위험 감지 (%)", min_value=-100.0, max_value=-0.1, value=config.VOLATILITY_STOP_PERCENT, step=0.1,
                                                  disabled=(not use_auto_stop_loss_sell),
                                                  help="단일 캔들(설정한 시간) 기준, 시가 대비 종가가 이 비율(%) 이상 하락하면 손절 (예: -5.0)")
        
    # 5. ATR/SLTP (고급 전략)
    with st.expander("🎯 5. ATR 기반 동적 익절/손절 (고급)", expanded=False):
        use_atr_sltp = st.checkbox("ATR 기반 동적 익절/손절 사용", value=config.USE_ATR_SLTP, 
                                   help="활성화 시, 위의 '수익률 기반 익절/손절' 설정은 무시됩니다.")
        atr_sl_multiplier = st.number_input("ATR 손절 배수 (SL)", min_value=0.1, value=config.STRATEGY_THRESHOLDS.get('ATR_SL_MULTIPLIER', 2.0), step=0.1)
        atr_tp_multiplier = st.number_input("ATR 익절 배수 (TP)", min_value=0.1, value=config.STRATEGY_THRESHOLDS.get('ATR_TP_MULTIPLIER', 3.0), step=0.1)
        min_reward_risk_ratio = st.number_input("최소 손익비 (R:R)", min_value=0.1, value=config.STRATEGY_THRESHOLDS.get('MIN_REWARD_RISK_RATIO', 1.5), step=0.1)

    # 6. 신규 지표 (MFI, OBV, FR) (★논문 반영 수정★)
    with st.expander("🔬 6. 신규 지표 설정 (MFI, OBV, 펀딩비)", expanded=False):
        st.write("--- MFI (자금 흐름 지수) ---")
        use_mfi_score = st.checkbox("MFI 지표 점수 사용", value=config.USE_MFI_SCORE)
        mfi_high = st.slider("MFI 과매수 기준 (매도)", 50.0, 100.0, float(config.STRATEGY_THRESHOLDS.get('MFI_HIGH', 80.0)), 1.0, disabled=not use_mfi_score)
        mfi_low = st.slider("MFI 과매도 기준 (매수)", 0.0, 50.0, float(config.STRATEGY_THRESHOLDS.get('MFI_LOW', 20.0)), 1.0, disabled=not use_mfi_score)
        
        # [★논문 반영 수정★] config.py에서 'STRATEGY_WEIGHTS_BY_COIN'의 'default' 값을 읽어옴
        mfi_buy_score = st.slider("MFI 매수 점수 (default)", 0, 50, config.STRATEGY_WEIGHTS_BY_COIN.get('default', {}).get('MFI_BUY_SCORE', 15), 1, disabled=not use_mfi_score)
        mfi_sell_score = st.slider("MFI 매도 점수 (default)", 0, 50, config.STRATEGY_WEIGHTS_BY_COIN.get('default', {}).get('MFI_SELL_SCORE', 15), 1, disabled=not use_mfi_score)

        st.write("--- OBV (누적 거래량) ---")
        use_obv_score = st.checkbox("OBV 추세 점수 사용", value=config.USE_OBV_SCORE)
        obv_ma_period = st.slider("OBV 이동평균선 기간", 5, 50, config.OBV_MA_PERIOD, 1, disabled=not use_obv_score)
        obv_buy_score = st.slider("OBV 매수 점수 (default)", 0, 50, config.STRATEGY_WEIGHTS_BY_COIN.get('default', {}).get('OBV_BUY_SCORE', 10), 1, disabled=not use_obv_score)
        obv_sell_score = st.slider("OBV 매도 점수 (default)", 0, 50, config.STRATEGY_WEIGHTS_BY_COIN.get('default', {}).get('OBV_SELL_SCORE', 10), 1, disabled=not use_obv_score)
        
        st.write("--- 펀딩 비율 (Binance 선물) ---")
        use_funding_rate_filter = st.checkbox("펀딩비 과열 필터 사용 (매도)", value=config.USE_FUNDING_RATE_FILTER)
        funding_rate_threshold = st.number_input("펀딩비 과열 기준 (%)", min_value=0.01, max_value=0.5, 
                                                 value=config.FUNDING_RATE_THRESHOLD, step=0.001, format="%.3f",
                                                 disabled=not use_funding_rate_filter,
                                                 help="바이낸스 선물 펀딩비가 이 값(예: 0.075%)을 초과하면 '과열'로 간주합니다.")
        funding_rate_sell_score = st.slider("펀딩비 매도 점수 (default)", 0, 50, config.STRATEGY_WEIGHTS_BY_COIN.get('default', {}).get('FUNDING_RATE_SELL_SCORE', 20), 1, disabled=not use_funding_rate_filter)

    # 7. 점수 및 필터 (기존 6번)
    with st.expander("⚖️ 7. 매매 점수 및 필터 (기존 6번)", expanded=False):
        buy_score_threshold = st.slider("최소 매수 점수 (BUY)", min_value=10, max_value=200, value=config.SCORE_THRESHOLDS['BUY'], step=5)
        sell_score_threshold = st.slider("최소 매도 점수 (SELL)", min_value=10, max_value=200, value=config.SCORE_THRESHOLDS['SELL'], step=5)
        
        st.write("--- 매수 필터 ---")
        use_htf_filter = st.checkbox("상위 시간 프레임(HTF) 필터 사용", value=config.USE_HTF_FILTER,
                                     help="매수 신호 발생 시, 4시간봉(minute240) 추세가 하락이면 매수 안함")
        use_volatility_filter = st.checkbox("변동성 및 거래량 필터 사용", value=config.USE_VOLATILITY_FILTER,
                                          help="최소 ATR, 최소 거래량(MA대비) 필터 활성화")
        
        st.write("--- 매매 타이밍 필터 ---")
        entry_cooldown_hours = st.slider("매도 후 재진입 대기 시간 (시간)", 0, 24, config.ENTRY_COOLDOWN_HOURS, 1)
        min_hold_hours = st.slider("최소 보유 시간 (시간)", 0, 48, config.MIN_HOLD_HOURS, 1,
                                   help="매수 후 최소 이 시간 동안은 '분석 기반 매도'를 실행하지 않음 (손절/익절은 실행됨)")
        buy_protection_hours = st.slider("매수 후 보호 기간 (시간)", 0, 24, getattr(config, 'BUY_PROTECTION_HOURS', 0), 1,
                                        help="매수 후 이 시간 동안은 매도 신호를 무시합니다 (저점 매수 후 상승 대기)")


    # --- 설정 저장 버튼 ---
    if st.button("💾 설정 저장", type="primary", use_container_width=True): # [★수정 6★]
        new_config = {
            'ACCESS_KEY': access_key,
            'SECRET_KEY': secret_key,
            'TICKERS': selected_tickers, 
            'BUY_AMOUNT_KRW': buy_amount_krw,
            'TIME_INTERVAL': time_interval,
            'MAX_TRADES_PER_DAY': max_trades_per_day,
            'SELL_METHOD': sell_method,
            'SELL_RATIO': sell_ratio,
            'USE_HIGHER_AVG_DOWN_SCORE': use_higher_avg_down_score,
            'AVG_DOWN_SCORE_MULTIPLIER': avg_down_score_multiplier,
            'USE_PROFIT_TAKE': use_profit_take,
            'PROFIT_TAKE_PERCENT': profit_take_percent,
            'USE_AUTO_STOP_LOSS_SELL': use_auto_stop_loss_sell,
            'LOSS_CUT_PERCENT': loss_cut_percent,
            'USE_PARTIAL_STOP_LOSS': use_partial_stop_loss, 
            'PARTIAL_STOP_LOSS_RATIO': partial_stop_loss_ratio, 
            'VOLATILITY_STOP_PERCENT': volatility_stop_percent,
            'USE_TRAILING_STOP': use_trailing_stop,
            'TRAILING_STOP_PERCENT': trailing_stop_percent,
            'USE_ATR_SLTP': use_atr_sltp,
            'USE_HTF_FILTER': use_htf_filter,
            'USE_VOLATILITY_FILTER': use_volatility_filter,
            'ENTRY_COOLDOWN_HOURS': entry_cooldown_hours,
            'MIN_HOLD_HOURS': min_hold_hours,
            'BUY_PROTECTION_HOURS': buy_protection_hours,
            
            'USE_MFI_SCORE': use_mfi_score,
            'OBV_MA_PERIOD': obv_ma_period,
            'USE_OBV_SCORE': use_obv_score,
            'USE_FUNDING_RATE_FILTER': use_funding_rate_filter,
            'FUNDING_RATE_THRESHOLD': funding_rate_threshold,
        }
        
        cfg_data = config.get_config_data() 
        cfg_data.update(new_config) 
        
        cfg_data['STRATEGY_THRESHOLDS']['ATR_SL_MULTIPLIER'] = atr_sl_multiplier
        cfg_data['STRATEGY_THRESHOLDS']['ATR_TP_MULTIPLIER'] = atr_tp_multiplier
        cfg_data['STRATEGY_THRESHOLDS']['MIN_REWARD_RISK_RATIO'] = min_reward_risk_ratio
        cfg_data['SCORE_THRESHOLDS']['BUY'] = buy_score_threshold
        cfg_data['SCORE_THRESHOLDS']['SELL'] = sell_score_threshold
        
        # (MFI / OBV / FR)
        cfg_data['STRATEGY_THRESHOLDS']['MFI_HIGH'] = mfi_high
        cfg_data['STRATEGY_THRESHOLDS']['MFI_LOW'] = mfi_low
        
        # [★논문 반영 수정★] 사이드바 설정은 'default' 가중치에 저장합니다.
        if 'STRATEGY_WEIGHTS_BY_COIN' not in cfg_data: # 혹시 모를 키 오류 방지
            cfg_data['STRATEGY_WEIGHTS_BY_COIN'] = {'default': {}}
        if 'default' not in cfg_data['STRATEGY_WEIGHTS_BY_COIN']:
            cfg_data['STRATEGY_WEIGHTS_BY_COIN']['default'] = {}
            
        cfg_data['STRATEGY_WEIGHTS_BY_COIN']['default']['MFI_BUY_SCORE'] = mfi_buy_score
        cfg_data['STRATEGY_WEIGHTS_BY_COIN']['default']['MFI_SELL_SCORE'] = mfi_sell_score
        cfg_data['STRATEGY_WEIGHTS_BY_COIN']['default']['OBV_BUY_SCORE'] = obv_buy_score
        cfg_data['STRATEGY_WEIGHTS_BY_COIN']['default']['OBV_SELL_SCORE'] = obv_sell_score
        cfg_data['STRATEGY_WEIGHTS_BY_COIN']['default']['FUNDING_RATE_SELL_SCORE'] = funding_rate_sell_score
        
        try:
            config.save_config(cfg_data) 
            st.success("설정이 config.json 파일에 저장되었습니다!")
            
            if st.session_state.bot and st.session_state.bot_status == "running":
                config.load_config(force_reload=True) 
                st.session_state.bot.config = config.get_config_data() 
                st.toast("봇이 실행 중입니다. 새 설정이 즉시 적용되었습니다.")
                
        except Exception as e:
            st.error(f"설정 저장 중 오류 발생: {e}")

# --- [메인 대시보드] ---
col1, col2, col3 = st.columns([1.5, 1, 1])

with col1:
    st.subheader("🤖 봇 제어")
    
    c1, c2 = st.columns(2)
    # [★수정 6★]
    if c1.button("▶️ 봇 시작", use_container_width=True, type="primary", disabled=(st.session_state.bot_status == "running")):
        
        if not access_key or not secret_key:
            st.error("API 키를 먼저 입력하고 저장하세요.")
        elif not selected_tickers: 
            st.error("거래할 코인을 1개 이상 선택하세요.")
        else:
            st.session_state.bot_status = "running"
            add_log("🤖 봇을 시작합니다.")
            
            try:
                bot_config_data = config.load_config(force_reload=True) 
                
                if not bot_config_data['TICKERS']:
                     st.error("설정에 거래할 코인이 없습니다. 사이드바에서 설정 후 [설정 저장]을 누르세요.")
                     st.session_state.bot_status = "stopped"
                else:
                    st.session_state.bot = TradingBot(bot_config_data)
                    st.toast(f"봇이 {len(bot_config_data['TICKERS'])}개 코인으로 시작되었습니다.")
                    
                    if st.session_state.bot.upbit:
                        balance_krw = st.session_state.bot.get_balance("KRW")
                        st.session_state.krw_balance = balance_krw
                        add_log(f"연결 성공. 원화 잔고: {balance_krw:,.0f} KRW")
                    else:
                         add_log("업비트 연결 실패. API 키를 확인하세요.")
                         st.session_state.bot_status = "stopped"
                    
                    st.rerun() 
                    
            except Exception as e:
                st.error(f"봇 생성 중 오류 발생: {e}")
                add_log(f"오류: 봇 생성 실패. {e}")
                st.session_state.bot_status = "stopped"

    # [★수정 6★]
    if c2.button("⏹️ 봇 정지", use_container_width=True, type="secondary", disabled=(st.session_state.bot_status != "running")):
        st.session_state.bot_status = "stopping"
        add_log("🤖 봇을 정지 중입니다...")
        st.toast("봇이 정지 신호를 받았습니다. 현재 작업을 완료하고 종료합니다.")
        st.rerun()
        
    status_indicator = "🟢 실행 중" if st.session_state.bot_status == "running" else \
                       "🟡 정지 중..." if st.session_state.bot_status == "stopping" else \
                       "🔴 중지됨"
    st.markdown(f"**현재 상태:** {status_indicator}")

with col2:
    st.subheader("💰 보유 자산")
    krw_balance = st.session_state.get('krw_balance', 0)
    total_assets = st.session_state.get('total_assets', krw_balance)
    st.metric("원화 (KRW)", f"{krw_balance:,.0f} 원")

with col3:
    st.subheader("📈 실시간 손익 (추정)")
    # [★수정 12★] placeholder를 세션에 1회만 생성하여 재사용
    if 'placeholder_pnl' not in st.session_state:
        st.session_state.placeholder_pnl = st.empty()
    placeholder_pnl = st.session_state.placeholder_pnl
    # [★깜빡임 수정★] 봇 실행 시 '0원'으로 초기화되는 코드를 삭제합니다. (주석 처리)
    # 이 코드는 파일 맨 아래 'else' 블록으로 이동하여 봇이 중지되었을 때만 실행됩니다.
    # placeholder_pnl.metric("총 평가손익", "0 원 (0.00%)") 


# --- [탭] ---
tab_run, tab_analysis, tab_pick, tab_history, tab_report, tab_risk_analysis, tab_log = st.tabs([
    "실행 & 차트", "실시간 분석/추천", "코인 추천", "거래 내역", "투자 보고서", 
    "📊 손익/위험 분석", 
    "실시간 로그"
])

# --- [탭 1: 실행 & 차트] ---
with tab_run:
    st.subheader("📈 실시간 차트 및 현황")
    
    current_config_tickers = config.TICKERS
    if not current_config_tickers:
        st.warning("사이드바 [2. 기본 매매 설정]에서 거래할 코인을 1개 이상 선택하고 [설정 저장]을 눌러주세요.")
    else:
        chart_tickers_list = st.session_state.bot.config['TICKERS'] if (st.session_state.bot and st.session_state.bot.config.get('TICKERS')) else current_config_tickers
        
        if not chart_tickers_list:
             st.warning("거래할 코인 목록이 비어있습니다. 사이드바에서 설정 후 저장해주세요.")
        else:
            selected_chart_ticker = st.selectbox("차트로 볼 코인 선택", chart_tickers_list, index=0, key="chart_ticker_select")
            
            if selected_chart_ticker:
                # [★수정 12★] placeholder들을 세션에 1회만 생성하여 재사용
                if 'chart_placeholder' not in st.session_state:
                    st.session_state.chart_placeholder = st.empty()
                if 'position_placeholder' not in st.session_state:
                    st.session_state.position_placeholder = st.empty()
                if 'indicator_placeholder' not in st.session_state:
                    st.session_state.indicator_placeholder = st.empty()
                chart_placeholder = st.session_state.chart_placeholder
                position_placeholder = st.session_state.position_placeholder
                indicator_placeholder = st.session_state.indicator_placeholder
            else:
                st.warning("차트를 표시할 코인을 선택해주세요.")

# --- [탭 2: 실시간 분석/추천] ---
with tab_analysis:
    st.subheader("🔍 실시간 개별 코인 분석")
    st.info("현재 설정된 시간 간격(Time Interval) 기준으로 개별 코인의 기술적 지표와 매매 점수를 실시간으로 분석합니다.")
    
    analysis_ticker = st.selectbox("분석할 코인 선택", all_tickers, index=0, key="analysis_ticker_select")
    
    if st.button("📈 분석 실행", key="analysis_button"):
        if not st.session_state.bot:
            try:
                temp_bot_config = config.load_config(force_reload=True)
                temp_bot = TradingBot(temp_bot_config)
                if not temp_bot.upbit:
                    st.error("업비트 연결 실패. API 키를 확인하세요.")
                    temp_bot = None
            except Exception as e:
                st.error(f"분석 모듈 로드 실패: {e}")
                temp_bot = None
        else:
            temp_bot = st.session_state.bot 

        if temp_bot:
            with st.spinner(f"{analysis_ticker} 코인을 분석 중입니다..."):
                try:
                    judgment_data = temp_bot.get_comprehensive_judgment(analysis_ticker)
                    
                    if judgment_data['judgment'] == '데이터 부족' or judgment_data['judgment'] == '분석 오류':
                        st.error(f"데이터가 부족하거나 분석 중 오류가 발생했습니다. (오류: {judgment_data.get('error', 'N/A')})")
                    else:
                        st.markdown(f"#### {analysis_ticker} 분석 결과 ({datetime.now().strftime('%H:%M:%S')})")
                        
                        j_col1, j_col2, j_col3, j_col4 = st.columns(4)
                        j_col1.metric("종합 판단", judgment_data['judgment'])
                        j_col2.metric("신호 강도", judgment_data['signal_strength'])
                        j_col3.metric("매수 점수", f"{int(judgment_data['buy_score'])}")
                        j_col4.metric("매도 점수", f"{int(judgment_data['sell_score'])}")
                        
                        if 'extra_info' in judgment_data:
                            st.markdown("---")
                            e_col1, e_col2, e_col3 = st.columns(3)
                            e_col1.metric("MFI (자금 흐름)", judgment_data['extra_info'].get('mfi', 'N/A'))
                            e_col2.metric("OBV (거래량 추세)", judgment_data['extra_info'].get('obv_signal', 'N/A'))
                            e_col3.metric("펀딩 비율 (위험도)", judgment_data['extra_info'].get('funding_rate', 'N/A'))
                        
                        st.markdown("---")
                        b_col, s_col = st.columns(2)
                        with b_col:
                            st.markdown("##### 🟢 매수 신호 근거")
                            if judgment_data['buy_conditions']:
                                for reason in judgment_data['buy_conditions']:
                                    st.success(f"- {reason}")
                            else:
                                st.caption("매수 신호 없음")
                        with s_col:
                            st.markdown("##### 🔴 매도 신호 근거")
                            if judgment_data['sell_conditions']:
                                for reason in judgment_data['sell_conditions']:
                                    st.error(f"- {reason}")
                            else:
                                st.caption("매도 신호 없음")

                except Exception as e:
                    st.error(f"코인 분석 중 예외 발생: {e}")
        else:
            st.error("봇이 초기화되지 않았습니다. API 키를 확인하세요.")


# --- [탭 3: 코인 추천] ---
with tab_pick:
    st.subheader("🏆 거래량 상위 코인 스크리너")
    st.info("업비트 KRW 마켓 전체의 24시간 거래량 상위 코인을 스캔하고, 현재 설정된 전략으로 점수를 매깁니다.")
    
    scan_top_percentage = st.slider("거래량 상위 N% 스캔", min_value=1.0, max_value=100.0, value=20.0, step=1.0)
    
    if st.button("🔍 스캔 시작", key="scan_button"):
        if not st.session_state.bot:
            try:
                temp_bot_config = config.load_config(force_reload=True)
                temp_bot_config['RECOMMEND_TOP_PERCENTAGE'] = scan_top_percentage
                temp_bot = TradingBot(temp_bot_config)
                if not temp_bot.upbit:
                    st.error("업비트 연결 실패. API 키를 확인하세요.")
                    temp_bot = None
            except Exception as e:
                st.error(f"분석 모듈 로드 실패: {e}")
                temp_bot = None
        else:
            temp_bot_config = copy.deepcopy(st.session_state.bot.config)
            temp_bot_config['RECOMMEND_TOP_PERCENTAGE'] = scan_top_percentage
            temp_bot = TradingBot(temp_bot_config) 

        if temp_bot:
            with st.spinner(f"거래량 상위 {scan_top_percentage}% 코인을 스캔 중입니다... (최대 1~2분 소요)"):
                try:
                    recommend_df = temp_bot.analyze_and_recommend_coins(temp_bot_config)
                    
                    if recommend_df is None or recommend_df.empty:
                        st.warning("스캔 결과가 없습니다. (API 오류 또는 데이터 부족)")
                    else:
                        st.success(f"총 {len(recommend_df)}개 코인 스캔 완료! (점수 내림차순 정렬)")
                        
                        def style_dataframe(df):
                            def style_score(score):
                                color = 'green' if score > 0 else 'red' if score < 0 else 'gray'
                                return f'color: {color}; font-weight: bold;'
                            def style_change(change):
                                color = 'green' if change > 0 else 'red' if change < 0 else 'gray'
                                return f'color: {color};'
                            
                            styled_df = df.style.map(style_score, subset=['score']) \
                                            .map(style_change, subset=['change_1h', 'change_24h']) \
                                            .format({
                                                'change_1h': '{:.2f}%',
                                                'change_24h': '{:.2f}%',
                                                'rsi': '{:.1f}',
                                                'mfi': '{:.1f}',
                                                'stoch_k': '{:.1f}',
                                                'atr_pct': '{:.2f}%',
                                                'price': '{:,.0f} 원'
                                            })
                            return styled_df

                        st.dataframe(style_dataframe(recommend_df), use_container_width=True)
                        
                except Exception as e:
                    st.error(f"코인 스캔 중 예외 발생: {e}")
                    st.exception(e) 
        else:
            st.error("봇이 초기화되지 않았습니다. API 키를 확인하세요.")


# --- [탭 4: 거래 내역] ---
with tab_history:
    st.subheader("📑 거래 내역 (Bot)")
    st.info("봇이 실행된 이후 발생한 실제 매매 내역입니다. (앱 재시작 시 trade_history.json에서 로드)")
    
    if not st.session_state.trade_history:
        st.caption("아직 거래 내역이 없습니다.")
    else:
        history_df = pd.DataFrame(st.session_state.trade_history)
        history_df['time'] = pd.to_datetime(history_df['time']).dt.strftime('%Y-%m-%d %H:%M:%S')
        history_df = history_df.sort_values(by='time', ascending=False)
        
        display_cols = ['time', 'ticker', 'side', 'price', 'volume', 'profit', 'reason', 'avg_buy_price']
        final_cols = [col for col in display_cols if col in history_df.columns]
        history_df = history_df[final_cols]
        
        st.dataframe(history_df.style.format({
            'price': '{:,.0f}',
            'volume': '{:.8f}',
            'profit': '{:,.0f}',
            'avg_buy_price': '{:,.0f}'
        }), use_container_width=True, height=500)


# --- [탭 5: 투자 보고서] ---
with tab_report:
    st.subheader("📈 투자 보고서 (간이)")
    
    history_df = pd.DataFrame(st.session_state.trade_history)
    
    if history_df.empty:
        st.warning("거래 내역이 없어 보고서를 생성할 수 없습니다.")
    else:
        history_df['profit'] = history_df['profit'].fillna(0)
        total_profit = history_df['profit'].sum()
        
        sells = history_df[history_df['side'] == 'sell']
        win_trades = len(sells[sells['profit'] > 0])
        total_sell_trades = len(sells)
        win_rate = (win_trades / total_sell_trades) * 100 if total_sell_trades > 0 else 0
        
        buys = history_df[history_df['side'] == 'buy']
        
        c1, c2, c3 = st.columns(3)
        c1.metric("총 실현 손익 (매도 기준)", f"{total_profit:,.0f} 원")
        c2.metric("총 매매 횟수", f"{len(history_df)} 회", f"매수 {len(buys)} / 매도 {len(sells)}")
        c3.metric("승률 (매도 기준)", f"{win_rate:.2f} %", f"{win_trades} 승 / {total_sell_trades - win_trades} 패")
        
        if 'ticker' in history_df.columns:
            st.markdown("---")
            st.markdown("#### 🪙 코인별 실현 손익")
            profit_by_ticker = history_df.groupby('ticker')['profit'].sum().sort_values(ascending=False)
            st.dataframe(profit_by_ticker.apply(lambda x: f"{x:,.0f} 원"), use_container_width=True)
            
            st.markdown("---")
            st.markdown("#### 🧭 전략별 실현 손익 (매도 사유 기준)")
            if 'reason' in sells.columns:
                profit_by_reason = sells.groupby('reason')['profit'].sum().sort_values(ascending=False)
                st.dataframe(profit_by_reason.apply(lambda x: f"{x:,.0f} 원"), use_container_width=True)
            else:
                st.caption("매도 사유(reason) 데이터가 없습니다.")
        else:
            st.warning("거래 내역에 'ticker' 정보가 없어 코인별 분석을 스킵합니다.")


# --- [탭 6: 손익/위험 분석] ---
with tab_risk_analysis:
    st.subheader("📊 전체 로그 기반 손익/위험 분석")
    st.info("logs 폴더 내의 모든 .log 파일을 읽어 평가 손익(%) 추세를 분석합니다. [봇 실행] 상태가 아니어도 분석할 수 있습니다.")

    if 'pnl_df' not in st.session_state:
        st.session_state.pnl_df = None

    # [★수정 6★]
    if st.button("🔄 전체 로그 분석 실행", use_container_width=True):
        with st.spinner("logs/ 폴더의 모든 로그 파일을 분석 중입니다... (데이터 양에 따라 시간이 걸릴 수 있음)"):
            try:
                st.session_state.pnl_df = log_analyzer.parse_pnl_logs()
                
                if st.session_state.pnl_df is None or st.session_state.pnl_df.empty:
                    st.warning("로그에서 '평가손익' 또는 '현재 손익' 데이터를 찾을 수 없습니다.")
                    st.session_state.pnl_df = None 
                else:
                    st.success(f"✅ 총 {len(st.session_state.pnl_df)}개의 평가손익 데이터를 분석했습니다.")
            except Exception as e:
                st.session_state.pnl_df = None
                st.error(f"로그 분석 중 오류가 발생했습니다.")
                st.exception(e) 
    
    if st.session_state.pnl_df is not None:
        pnl_df = st.session_state.pnl_df 
        
        tickers = sorted(pnl_df['ticker'].unique())
        if not tickers:
            st.warning("데이터는 있으나 유효한 티커를 찾지 못했습니다.")
        else:
            selected_ticker = st.selectbox("그래프로 볼 코인 선택", tickers, key="risk_analysis_ticker_select")
            
            if selected_ticker:
                df_ticker = pnl_df[pnl_df['ticker'] == selected_ticker].set_index('time')
                
                if df_ticker.empty:
                    st.warning(f"{selected_ticker}에 대한 PNL 데이터가 없습니다.")
                else:
                    st.markdown(f"#### 📈 {selected_ticker} 평가손익(%) 추세")
                    st.line_chart(df_ticker['pnl_percent'])
                    
                    latest_pnl = df_ticker['pnl_percent'].iloc[-1]
                    min_pnl = df_ticker['pnl_percent'].min()
                    
                    st.markdown("#### 📉 위험 요약")
                    col1, col2 = st.columns(2)
                    col1.metric("최근 평가손익", f"{latest_pnl:.2f}%")
                    col2.metric("기간 내 최저손익 (최대 손실폭)", f"{min_pnl:.2f}%", 
                                delta=f"최근 대비 {latest_pnl - min_pnl:.2f}%" if min_pnl < latest_pnl else None,
                                delta_color="inverse")
                    
                    st.markdown("#### 📋 상세 데이터 (최신순)")
                    st.dataframe(df_ticker.sort_index(ascending=False), height=300)


# --- [탭 7: 실시간 로그] ---
with tab_log:
    st.subheader("📜 실시간 로그")
    log_placeholder = st.empty()
    log_container = log_placeholder.container(height=500)
    for log_entry in st.session_state.logs:
        log_container.text(log_entry)


# -----------------------------------------------------------------------------
# 4. 봇 메인 루프 (Streamlit Auto-Rerun 활용)
# -----------------------------------------------------------------------------

# [★수정 12★] placeholder들을 인수로 받도록 함수 정의 수정
def update_live_data(bot, chart_ph, position_ph, indicator_ph):
    """
    실행&차트 탭의 차트, 보유 현황, 기술적 분석 지표를 업데이트합니다.
    """
    try:
        if not bot.config.get('TICKERS'):
            return
        ticker_to_chart = st.session_state.get("chart_ticker_select", bot.config['TICKERS'][0])
        
        df = bot.get_trading_data(ticker_to_chart)
        if df is None or df.empty:
            st.toast(f"[{ticker_to_chart}] 차트 데이터 조회 실패", icon="⚠️")
            return

        # [★수정 12★] 인수로 받은 placeholder 사용
        with chart_ph:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, 
                                row_heights=[0.7, 0.3])
            
            fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], 
                                         low=df['low'], close=df['close'], name='캔들'), 
                          row=1, col=1)
            
            bbu_col = df.filter(like='BBU_').columns[0]
            bbl_col = df.filter(like='BBL_').columns[0]
            fig.add_trace(go.Scatter(x=df.index, y=df[bbu_col], line=dict(color='gray', width=1), name='BB 상단'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df[bbl_col], line=dict(color='gray', width=1), name='BB 하단', 
                                     fill='tonexty', fillcolor='rgba(128,128,128,0.1)'), row=1, col=1)

            ema_col = df.filter(like='EMA_').columns[0]
            fig.add_trace(go.Scatter(x=df.index, y=df[ema_col], line=dict(color='orange', width=1.5), name='EMA'), row=1, col=1)

            fig.add_trace(go.Bar(x=df.index, y=df['volume'], name='거래량'), row=2, col=1)
            
            fig.update_layout(
                title=f'[{ticker_to_chart}] 실시간 차트 ({bot.config["TIME_INTERVAL"]})',
                xaxis_rangeslider_visible=False,
                height=450,
                margin=dict(l=20, r=20, t=40, b=20)
            )
            st.plotly_chart(fig, use_container_width=True)
            
        # 3. 보유 현황 업데이트
        position = bot.positions.get(ticker_to_chart, {})
        current_price = df.iloc[-1]['close']
        total_volume = position.get('total_volume', 0)
        avg_buy_price = position.get('average_buy_price', 0)
        pnl_krw = 0
        pnl_percent = 0
        
        if total_volume > 0 and avg_buy_price > 0:
            pnl_krw = (current_price - avg_buy_price) * total_volume
            pnl_percent = (pnl_krw / (avg_buy_price * total_volume)) * 100
        
        # [★수정 12★] 인수로 받은 placeholder 사용
        with position_ph.container():
            st.markdown("---")
            st.subheader(f"📊 {ticker_to_chart} 보유 현황")
            p_col1, p_col2, p_col3 = st.columns(3)
            p_col1.metric("보유 수량", f"{total_volume:.8f} 개")
            p_col2.metric("평균 매수가", f"{avg_buy_price:,.0f} 원")
            p_col3.metric("평가 손익", f"{pnl_krw:,.0f} 원", f"{pnl_percent:.2f} %")

        # 4. 기술적 분석 지표 업데이트 (MFI, OBV, FR 추가)
        # [★수정 12★] 인수로 받은 placeholder 사용
        with indicator_ph.container(): 
            st.markdown("---")
            st.markdown("#### 🔬 기술적 분석 지표 (현재)")
            
            latest = df.iloc[-1]
            i_col1, i_col2, i_col3, i_col4, i_col5, i_col6 = st.columns(6)
            
            rsi_col = df.filter(like='RSI_').columns[0]
            stoch_k_col = df.filter(like='STOCHk_').columns[0]
            mfi_col = df.filter(like='MFI_').columns[0]
            
            i_col1.metric("현재가", f"{current_price:,.0f} 원")
            i_col2.metric("RSI", f"{latest[rsi_col]:.1f}")
            i_col3.metric("MFI", f"{latest[mfi_col]:.1f}")
            i_col4.metric("Stochastic (K)", f"{latest[stoch_k_col]:.1f}")

            try:
                obv_col = None
                for col in df.columns:
                    if col == 'OBV':
                        obv_col = col
                        break
                if obv_col is None:
                    obv_col_list = [col for col in df.columns if col.startswith('OBV') and 'EMA' not in col]
                    if obv_col_list:
                        obv_col = obv_col_list[0]
                    else:
                        raise Exception("OBV 컬럼을 찾을 수 없습니다.")

                obv_ma_col = df.filter(like='OBV_EMA_').columns[0]
                obv_signal = "상승" if latest[obv_col] > latest[obv_ma_col] else "하락"
                i_col5.metric("OBV 추세", obv_signal)
            except Exception as e:
                i_col5.metric("OBV 추세", "N/A")

            try:
                fr, fr_status = binance_fetcher.get_binance_funding_rate(ticker_to_chart)
                fr_text = f"{(fr*100):.4f}%" if fr is not None else fr_status
                i_col6.metric("펀딩 비율", fr_text)
            except Exception as e:
                print(f"!!! 펀딩비 UI 표시 오류: {e}")
                i_col6.metric("펀딩 비율", f"오류: {e}")
            

    except Exception as e:
        st.toast(f"차트 업데이트 중 오류: {e}", icon="🔥")
        print(f"차트 업데이트 오류: {e}")


# [★수정 12★] placeholder를 인수로 받도록 함수 정의 수정
def update_global_pnl(bot, pnl_ph):
    """
    메인 대시보드의 총 평가손익 및 총 자산을 업데이트합니다.
    """
    try:
        total_pnl_krw = 0
        total_eval_krw = 0
        
        for ticker, position in bot.positions.items():
            total_volume = position.get('total_volume', 0)
            avg_buy_price = position.get('average_buy_price', 0)
            
            if total_volume > 0 and avg_buy_price > 0:
                current_price = pyupbit.get_current_price(ticker)
                if current_price:
                    pnl_krw = (current_price - avg_buy_price) * total_volume
                    total_pnl_krw += pnl_krw
                    total_eval_krw += current_price * total_volume
                else:
                    total_eval_krw += avg_buy_price * total_volume
        
        krw_balance = bot.get_balance("KRW")
        st.session_state.krw_balance = krw_balance
        
        total_assets = total_eval_krw + krw_balance
        st.session_state.total_assets = total_assets

        total_buy_cost = sum(
            p.get('total_buy_cost', 0) for p in bot.positions.values()
            if p.get('total_volume', 0) > 0
        )
        
        total_pnl_percent = (total_pnl_krw / total_buy_cost) * 100 if total_buy_cost > 0 else 0
        
        # [★수정 12★] 인수로 받은 placeholder 사용
        pnl_ph.metric(
            "총 평가손익", 
            f"{total_pnl_krw:,.0f} 원",
            f"{total_pnl_percent:.2f} %"
        )
        
    except Exception as e:
        st.toast(f"손익 업데이트 중 오류: {e}", icon="🔥")
        print(f"손익 업데이트 오류: {e}")


# --- 메인 실행 로직 ---
if st.session_state.bot_status == "running" and st.session_state.bot:
    bot_instance = st.session_state.bot
    
    try:
        log_msg, trade_result, stop_signal, stop_reason = bot_instance.run_once()
        
        if trade_result:
            st.session_state.trade_history.append(trade_result)
            save_trade_history(st.session_state.trade_history) 
            
            ticker = trade_result.get('ticker', 'N/A')
            side = trade_result.get('side', 'N/A')
            price = trade_result.get('price', 0)
            reason = trade_result.get('reason', 'N/A')
            
            new_log_msg = ""
            if side == 'buy':
                price_label = "매수 가격"
                if "매수 실행" in log_msg:
                    new_log_msg = log_msg
                else:
                     new_log_msg = f"✅ 매수 성공: [{ticker}] | {price_label}: {price:,.0f} KRW | 사유: {reason}"
            elif side == 'sell':
                if "매도" in log_msg: 
                    new_log_msg = log_msg
                else:
                    profit = trade_result.get('profit', 0)
                    new_log_msg = f"💰 매도 성공: [{ticker}] | 매도 가격: {price:,.0f} KRW | 실현손익: {profit:,.0f} KRW | 사유: {reason}"
            
            if new_log_msg:
                add_log(new_log_msg) 
            elif log_msg:
                add_log(log_msg) 
            
            st.rerun() 
        
        elif log_msg: 
            add_log(log_msg)
        
        if stop_signal:
            add_log(f"🚨 치명적 오류 또는 손절 조건 감지: {stop_reason}")
            add_log("🤖 봇을 자동으로 정지합니다.")
            st.session_state.bot_status = "stopped"
            st.session_state.bot = None
            st.rerun()

    except Exception as e:
        add_log(f"🔥 봇 실행 중 치명적 예외 발생: {e}")
        st.error(f"봇 실행 중 치명적 예외 발생: {e}")
        st.exception(e) 
        st.session_state.bot_status = "stopped"
        st.session_state.bot = None
        st.rerun()

    # --- [★수정 12★] 깜빡임 버그 수정 ---
    # 5초 타이머를 제거하고, 매 2초 루프마다 UI를 갱신합니다.
    
    # 1. 메인 대시보드 손익 업데이트 (매번)
    # placeholder_pnl은 이 루프(if 블록)보다 먼저 정의되어 접근 가능합니다.
    update_global_pnl(bot_instance, placeholder_pnl) 
    
    # 2. 실시간 차트 및 보유 현황 업데이트 (현재 탭이 활성화된 경우에만)
    if tab_run.is_active: 
        # chart_placeholder 등은 tab_run 블록 내부에 정의되어 있으므로 여기서 접근 가능합니다.
        update_live_data(bot_instance, chart_placeholder, position_placeholder, indicator_placeholder) 
    
    # 3. 60초 대기 후 페이지 갱신
    time.sleep(60)
    st.rerun()
    # --- [★수정 12 완료★] ---

elif st.session_state.bot_status == "stopping":
    st.session_state.bot = None
    st.session_state.bot_status = "stopped"
    add_log("🤖 봇이 안전하게 정지되었습니다.")
    st.rerun()

else:
    # 봇이 중지된 상태에서도 로그 핸들러는 한번 설정해줍니다.
    # (봇 시작 전 로그 표시, 봇 정지 후 로그 표시를 위해)
    try:
        setup_logging()
    except Exception as e:
        print(f"초기 로거 설정 실패: {e}")

    # [★깜빡임 수정★] 봇이 중지되었을 때만 손익을 0으로 초기화합니다.
    # 이렇게 하면 봇 실행 중 '0원'으로 깜빡이는 현상이 사라집니다.
    if st.session_state.get('placeholder_pnl'):
        st.session_state.placeholder_pnl.metric("총 평가손익", "0 원 (0.00%)")