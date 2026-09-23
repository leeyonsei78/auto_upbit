# config.py
# 봇의 모든 기본 설정과 JSON 파일 로드/저장 기능을 담당합니다.
# [★논문 반영 수정★] STRATEGY_WEIGHTS를 STRATEGY_WEIGHTS_BY_COIN으로 변경

import json
import os

CONFIG_FILE_PATH = "config.json"

# -----------------------------------------------------------------------------
# 1. 기본 설정값 (DEFAULTS)
# -----------------------------------------------------------------------------
# 이 값들은 config.json 파일이 없거나, 파일에 특정 키가 없을 때 사용됩니다.

DEFAULT_CONFIG = {
    # --- 1. API 키 ---
    "ACCESS_KEY": "",
    "SECRET_KEY": "",

    # --- 2. 기본 매매 설정 ---
    "TICKERS": ["KRW-BTC", "KRW-ETH", "KRW-SOL"],
    "BUY_AMOUNT_KRW": 10000,
    "TIME_INTERVAL": "minute60",
    "MAX_TRADES_PER_DAY": 10,

    # --- 3. 매도 및 물타기 ---
    "SELL_METHOD": "all",
    "SELL_RATIO": 100.0,
    "USE_HIGHER_AVG_DOWN_SCORE": True,
    "AVG_DOWN_SCORE_MULTIPLIER": 1.1,

    # --- 4. 익절 및 리스크 관리 ---
    "USE_PROFIT_TAKE": True,
    "PROFIT_TAKE_PERCENT": 7.0,
    "USE_AUTO_STOP_LOSS_SELL": True,
    "LOSS_CUT_PERCENT": -10.0,
    "USE_PARTIAL_STOP_LOSS": False,
    "PARTIAL_STOP_LOSS_RATIO": 10.0,
    "VOLATILITY_STOP_PERCENT": -3.0,
    # [★개선 3★] 트레일링 스탑 설정
    "USE_TRAILING_STOP": True,
    "TRAILING_STOP_PERCENT": 5.0,  # 최고가 대비 5% 하락 시 매도

    # --- 5. ATR (고급) ---
    "USE_ATR_SLTP": False,

    # --- 6. 신규 지표 (MFI, OBV, FR) ---
    "USE_MFI_SCORE": True,
    "OBV_MA_PERIOD": 20,
    "USE_OBV_SCORE": True,
    "USE_FUNDING_RATE_FILTER": True,
    "FUNDING_RATE_THRESHOLD": 0.075,

    # --- 7. 점수 및 필터 ---
    "USE_HTF_FILTER": False,
    "USE_VOLATILITY_FILTER": False,
    "ENTRY_COOLDOWN_HOURS": 3,
    "MIN_HOLD_HOURS": 12,
    "BUY_PROTECTION_HOURS": 6,
    
    # --- 봇 내부 로직용 설정 ---
    "USE_LIQUIDITY_FILTER": False,
    "USE_EMA_TREND_SCORE": True,
    "EMA_TREND_PERIOD": 50,
    "EMA_TREND_SCORE_WEIGHT": 15,
    "HTF_INTERVALS": ["minute240"],
    "FEE_FACTOR": 0.001, # (매수/매도 수수료 합 0.1%)
    "USE_DYNAMIC_SIZING": False,
    "RISK_PER_TRADE_PERCENT": 1.0,
    "MAX_BUY_RATIO_PER_TRADE": 0.25,
    "RECOMMEND_TOP_PERCENTAGE": 20,

    # --- 매매 점수 (THRESHOLDS) ---
    "SCORE_THRESHOLDS": {
        "BUY": 65,
        "SELL": 95
    },

    # --- [★논문 반영 수정★] ---
    # 전략 가중치 (WEIGHTS) - 코인별 설정
    "STRATEGY_WEIGHTS_BY_COIN": {
        # "default": 이 목록에 없는 모든 코인이 사용할 기본값
        "default": {
            "RSI_BUY_SCORE": 40,
            "RSI_SELL_SCORE": 40,
            "BBANDS_BUY_SCORE": 40,
            "BBANDS_SELL_SCORE": 40,
            "MACD_BUY_SCORE": 20,
            "MACD_SELL_SCORE": 20,
            "STOCH_BUY_SCORE": 30,
            "STOCH_SELL_SCORE": 30,
            "VOLUME_BUY_SCORE": 25,
            "VOLUME_SELL_SCORE": 0, 
            
            # 신규 지표 가중치
            "MFI_BUY_SCORE": 15,
            "MFI_SELL_SCORE": 15,
            "OBV_BUY_SCORE": 10,
            "OBV_SELL_SCORE": 10,
            "FUNDING_RATE_SELL_SCORE": 20
        },
        
        # "KRW-BTC": 비트코인 전용 가중치 (default 값을 덮어씁니다)
        "KRW-BTC": {
            "RSI_BUY_SCORE": 50,      # 예: 비트코인은 RSI 신뢰도를 높임
            "MFI_BUY_SCORE": 5        # 예: 비트코인은 MFI 신뢰도를 낮춤
        },
        
        # "KRW-SOL": 솔라나 전용 가중치
        "KRW-SOL": {
            "RSI_BUY_SCORE": 10,      # 예: 솔라나는 RSI 신뢰도를 낮춤
            "MFI_BUY_SCORE": 30       # 예: 솔라나는 MFI 신뢰도를 높임
        }
    },
    # --- [★수정 완료★] ---


    # --- 전략 상세 기준값 (THRESHOLDS) ---
    "STRATEGY_THRESHOLDS": {
        "RSI_LOW": 30.0,
        "RSI_HIGH": 70.0,
        "STOCH_LOW": 20.0,
        "STOCH_HIGH": 80.0,
        "VOLUME_SPIKE_MULTIPLIER": 1.5,
        "VOLUME_MA_PERIOD": 20,
        
        # 유동성 필터 (기본 비활성화)
        "MAX_SPREAD_PERCENT": 0.5,
        "MIN_ORDERBOOK_DEPTH_KRW": 1000000,
        
        # 변동성 필터 (기본 비활성화)
        "MIN_ATR_PERCENT": 0.3,
        "MIN_VOLUME_RATIO": 0.3,

        # ATR SL/TP
        "ATR_SL_MULTIPLIER": 2.0,
        "ATR_TP_MULTIPLIER": 3.0,
        "MIN_REWARD_RISK_RATIO": 1.5,

        # MFI
        "MFI_HIGH": 80.0,
        "MFI_LOW": 20.0
    },

    # --- [★논문 반영 2단계★] 동적 가중치 조정 설정 ---
    "DYNAMIC_WEIGHT_ADJUSTMENT": {
        "enabled": True,
        "volatility_threshold": 3.0,  # ATR % 기준 (이 값 이상이면 고변동성)
        "low_volatility_threshold": 1.0,  # ATR % 기준 (이 값 이하면 저변동성)
        
        # 고변동성 시 가중치 조정 (변동성이 높을 때)
        "high_volatility_multipliers": {
            "ATR_BUY_SCORE": 1.5,      # 변동성 높을 때 ATR 가중치 1.5배
            "ATR_SELL_SCORE": 1.5,
            "RSI_BUY_SCORE": 0.8,      # 변동성 높을 때 RSI 가중치 0.8배
            "RSI_SELL_SCORE": 0.8,
            "BBANDS_BUY_SCORE": 1.2,    # 볼린저 밴드 가중치 증가
            "BBANDS_SELL_SCORE": 1.2,
            "MACD_BUY_SCORE": 1.1,      # MACD 가중치 약간 증가
            "MACD_SELL_SCORE": 1.1,
            "STOCH_BUY_SCORE": 0.9,
            "STOCH_SELL_SCORE": 0.9
        },
        
        # 저변동성 시 가중치 조정 (변동성이 낮을 때)
        "low_volatility_multipliers": {
            "RSI_BUY_SCORE": 1.2,       # 변동성 낮을 때 RSI 가중치 증가
            "RSI_SELL_SCORE": 1.2,
            "STOCH_BUY_SCORE": 1.2,
            "STOCH_SELL_SCORE": 1.2,
            "ATR_BUY_SCORE": 0.7,       # 변동성 낮을 때 ATR 가중치 감소
            "ATR_SELL_SCORE": 0.7,
            "MACD_BUY_SCORE": 1.1,
            "MACD_SELL_SCORE": 1.1
        },
        
        # 거래량 패턴에 따른 가중치 조정
        "volume_spike_multipliers": {
            "VOLUME_BUY_SCORE": 1.3,    # 거래량 급증 시 거래량 지표 가중치 증가
            "VOLUME_SELL_SCORE": 1.3
        },
        
        # 추세 강도에 따른 가중치 조정 (ADX 기준)
        "trend_strength_multipliers": {
            "strong_trend_threshold": 25.0,  # ADX 25 이상이면 강한 추세
            "weak_trend_threshold": 20.0,   # ADX 20 미만이면 약한 추세
            "strong_trend": {
                "ADX_BUY_SCORE": 1.5,
                "ADX_SELL_SCORE": 1.5,
                "EMA_TREND_SCORE": 1.3,
                "SUPERTREND_BUY_SCORE": 1.4,
                "SUPERTREND_SELL_SCORE": 1.4
            },
            "weak_trend": {
                "ADX_BUY_SCORE": 0.7,
                "ADX_SELL_SCORE": 0.7,
                "RSI_BUY_SCORE": 1.2,
                "RSI_SELL_SCORE": 1.2,
                "STOCH_BUY_SCORE": 1.2,
                "STOCH_SELL_SCORE": 1.2
            }
        }
    }
}

# -----------------------------------------------------------------------------
# 2. 전역 변수 (메모리 캐시)
# -----------------------------------------------------------------------------
# app.py와 trade_bot.py가 공유할 설정값 (메모리에 캐시)
_config_cache = None

# app.py 사이드바에서 사용할 리스트
TIME_INTERVALS = ['minute60', 'minute240', 'day', 'minute30', 'minute15', 'minute5', 'minute3', 'minute1']


# -----------------------------------------------------------------------------
# 3. 설정 파일 로드/저장 함수
# -----------------------------------------------------------------------------

def load_config(force_reload=False):
    """
    config.json 파일에서 설정을 읽어와 전역 _config_cache에 저장합니다.
    이미 캐시가 있으면 캐시를 반환합니다.
    """
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache

    # 1. config.json 파일이 있는지 확인
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
                loaded_settings = json.load(f)
            
            # 2. 기본값과 병합 (json에 없는 새 설정키 추가)
            _config_cache = DEFAULT_CONFIG.copy()
            _config_cache.update(loaded_settings) # 로드한 값으로 덮어쓰기
            
            # [★논문 반영 수정★] 하위 호환성: 옛날 config.json(STRATEGY_WEIGHTS)을 읽었을 경우
            if "STRATEGY_WEIGHTS" in _config_cache and "STRATEGY_WEIGHTS_BY_COIN" not in _config_cache:
                print("경고: 옛 'STRATEGY_WEIGHTS' 설정을 발견했습니다. 'STRATEGY_WEIGHTS_BY_COIN' 구조로 변환합니다.")
                _config_cache["STRATEGY_WEIGHTS_BY_COIN"] = {
                    "default": _config_cache["STRATEGY_WEIGHTS"]
                }
                # (새 구조로 저장하기 위해 save 호출을 권장하지만, 일단 로드만 진행)
            
            print(f"설정 로드 완료: {CONFIG_FILE_PATH}")
            
        except Exception as e:
            print(f"경고: {CONFIG_FILE_PATH} 파일 읽기 실패. 기본 설정으로 시작합니다. 오류: {e}")
            _config_cache = DEFAULT_CONFIG.copy()
    else:
        # 3. 파일이 없으면 기본 설정으로 시작하고, 새 파일을 저장
        print(f"경고: {CONFIG_FILE_PATH} 파일이 없어 기본 설정으로 시작합니다.")
        _config_cache = DEFAULT_CONFIG.copy()
        try:
            save_config(_config_cache)
            print(f"기본 설정으로 {CONFIG_FILE_PATH} 파일을 생성했습니다.")
        except Exception as e:
            print(f"오류: {CONFIG_FILE_PATH} 파일 생성 실패. {e}")

    return _config_cache

def save_config(settings_dict):
    """
    현재 설정(settings_dict)을 config.json 파일에 저장합니다.
    """
    global _config_cache
    try:
        with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=4)
        
        # 파일 저장 성공 시, 메모리 캐시도 업데이트
        _config_cache = settings_dict.copy()
        print(f"설정 저장 완료: {CONFIG_FILE_PATH}")
        
    except Exception as e:
        print(f"오류: {CONFIG_FILE_PATH} 파일 저장 실패. {e}")
        raise e # 오류를 app.py로 다시 전달하여 UI에 표시

def get_config_data():
    """
    현재 메모리에 캐시된 설정(_config_cache)을 반환합니다.
    캐시가 비어있으면 load_config()를 호출하여 초기화합니다.
    """
    if _config_cache is None:
        return load_config()
    return _config_cache

# -----------------------------------------------------------------------------
# 4. 모듈 로드 시, app.py에서 사용할 수 있도록 상수를 미리 로드
# -----------------------------------------------------------------------------
# (이 부분이 app.py의 사이드바 초기값 설정을 위해 필요합니다.)

print("config.py 모듈 로드 시작...")
# 1. 설정 로드 (캐시 초기화)
_config_data = load_config()

# 2. app.py가 import config 시 바로 접근할 수 있도록
#    주요 설정값을 모듈 레벨 상수로 노출
UPBIT_ACCESS_KEY = _config_data.get('ACCESS_KEY', "")
UPBIT_SECRET_KEY = _config_data.get('SECRET_KEY', "")
TICKERS = _config_data.get('TICKERS', [])
BUY_AMOUNT_KRW = _config_data.get('BUY_AMOUNT_KRW', 10000)
TIME_INTERVAL = _config_data.get('TIME_INTERVAL', 'minute60')
MAX_TRADES_PER_DAY = _config_data.get('MAX_TRADES_PER_DAY', 10)
SELL_METHOD = _config_data.get('SELL_METHOD', 'all')

# --- [★수정★] st.slider 타입 오류 방지를 위해 float()로 명시적 변환 ---
SELL_RATIO = float(_config_data.get('SELL_RATIO', 100.0))
USE_HIGHER_AVG_DOWN_SCORE = _config_data.get('USE_HIGHER_AVG_DOWN_SCORE', True)
AVG_DOWN_SCORE_MULTIPLIER = float(_config_data.get('AVG_DOWN_SCORE_MULTIPLIER', 1.2))
USE_PROFIT_TAKE = _config_data.get('USE_PROFIT_TAKE', True)
PROFIT_TAKE_PERCENT = float(_config_data.get('PROFIT_TAKE_PERCENT', 7.0))
USE_AUTO_STOP_LOSS_SELL = _config_data.get('USE_AUTO_STOP_LOSS_SELL', True)
LOSS_CUT_PERCENT = float(_config_data.get('LOSS_CUT_PERCENT', -10.0))
USE_PARTIAL_STOP_LOSS = _config_data.get('USE_PARTIAL_STOP_LOSS', False)
PARTIAL_STOP_LOSS_RATIO = float(_config_data.get('PARTIAL_STOP_LOSS_RATIO', 10.0))
VOLATILITY_STOP_PERCENT = float(_config_data.get('VOLATILITY_STOP_PERCENT', -3.0))
# [★개선 3★] 트레일링 스탑 설정
USE_TRAILING_STOP = _config_data.get('USE_TRAILING_STOP', True)
TRAILING_STOP_PERCENT = float(_config_data.get('TRAILING_STOP_PERCENT', 5.0))
# --- [★수정 완료★] ---

USE_ATR_SLTP = _config_data.get('USE_ATR_SLTP', False)
USE_MFI_SCORE = _config_data.get('USE_MFI_SCORE', True)
OBV_MA_PERIOD = _config_data.get('OBV_MA_PERIOD', 20)
USE_OBV_SCORE = _config_data.get('USE_OBV_SCORE', True)
USE_FUNDING_RATE_FILTER = _config_data.get('USE_FUNDING_RATE_FILTER', True)

# --- [★수정★] st.number_input 타입 오류 방지를 위해 float()로 명시적 변환 ---
FUNDING_RATE_THRESHOLD = float(_config_data.get('FUNDING_RATE_THRESHOLD', 0.075))
# --- [★수정 완료★] ---

SCORE_THRESHOLDS = _config_data.get('SCORE_THRESHOLDS', {"BUY": 65, "SELL": 95})

# --- [★논문 반영 수정★] ---
# app.py가 import config 시 'STRATEGY_WEIGHTS_BY_COIN'를 참조할 수 있도록 수정
STRATEGY_WEIGHTS_BY_COIN = _config_data.get('STRATEGY_WEIGHTS_BY_COIN', {"default": {}})
# --- [★수정 완료★] ---

STRATEGY_THRESHOLDS = _config_data.get('STRATEGY_THRESHOLDS', {})
USE_HTF_FILTER = _config_data.get('USE_HTF_FILTER', False)
USE_VOLATILITY_FILTER = _config_data.get('USE_VOLATILITY_FILTER', False)
ENTRY_COOLDOWN_HOURS = _config_data.get('ENTRY_COOLDOWN_HOURS', 3)
MIN_HOLD_HOURS = _config_data.get('MIN_HOLD_HOURS', 12)
BUY_PROTECTION_HOURS = _config_data.get('BUY_PROTECTION_HOURS', 6)

print("config.py 모듈 로드 완료.")