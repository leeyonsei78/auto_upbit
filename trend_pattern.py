# trend_pattern.py
# [★논문 반영 3단계★] 시계열 패턴 인식 모듈
# 지표의 추세 패턴을 감지하여 더 정확한 매매 타이밍 포착

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from scipy.signal import find_peaks

class TrendPatternDetector:
    """
    시계열 데이터에서 추세 패턴을 감지하는 클래스
    """
    
    def __init__(self, lookback_periods: int = 5):
        """
        Args:
            lookback_periods: 패턴 분석에 사용할 과거 기간 수
        """
        self.lookback_periods = lookback_periods
    
    def detect_trend_pattern(self, df: pd.DataFrame, indicator_col: str, 
                            periods: Optional[int] = None) -> Dict:
        """
        지표의 추세 패턴을 감지합니다.
        
        Args:
            df: 데이터프레임
            indicator_col: 분석할 지표 컬럼명
            periods: 분석할 기간 수 (기본값: self.lookback_periods)
        
        Returns:
            패턴 정보 딕셔너리
        """
        if df is None or df.empty or indicator_col not in df.columns:
            return {'pattern': 'unknown', 'strength': 0, 'confidence': 0}
        
        periods = periods or self.lookback_periods
        recent_data = df[indicator_col].tail(periods).dropna()
        
        if len(recent_data) < 3:
            return {'pattern': 'insufficient_data', 'strength': 0, 'confidence': 0}
        
        # 1. 단순 추세 (상승/하락/횡보)
        trend_direction = self._detect_simple_trend(recent_data)
        
        # 2. 추세 강도
        trend_strength = self._calculate_trend_strength(recent_data)
        
        # 3. 가속도/감속도
        acceleration = self._detect_acceleration(recent_data)
        
        # 4. 반전 신호
        reversal_signals = self._detect_reversal_signals(df, indicator_col)
        
        # 5. 패턴 종합 판단
        pattern_type = self._classify_pattern(trend_direction, trend_strength, acceleration)
        
        return {
            'pattern': pattern_type,
            'direction': trend_direction,
            'strength': trend_strength,
            'acceleration': acceleration,
            'reversal_signals': reversal_signals,
            'confidence': min(100, int(trend_strength * 100))
        }
    
    def _detect_simple_trend(self, data: pd.Series) -> str:
        """
        단순 상승/하락/횡보 추세 감지
        """
        if len(data) < 2:
            return 'unknown'
        
        # 최근 N개 포인트의 변화율 계산
        changes = data.diff().dropna()
        positive_changes = (changes > 0).sum()
        negative_changes = (changes < 0).sum()
        total_changes = len(changes)
        
        if total_changes == 0:
            return 'sideways'
        
        positive_ratio = positive_changes / total_changes
        
        if positive_ratio >= 0.7:
            return 'uptrend'
        elif positive_ratio <= 0.3:
            return 'downtrend'
        else:
            return 'sideways'
    
    def _calculate_trend_strength(self, data: pd.Series) -> float:
        """
        추세 강도를 0~1 사이 값으로 계산
        """
        if len(data) < 2:
            return 0.0
        
        # 선형 회귀의 기울기를 사용하여 추세 강도 측정
        x = np.arange(len(data))
        y = data.values
        
        # 단순 선형 회귀
        slope = np.polyfit(x, y, 1)[0]
        
        # 정규화 (데이터 범위에 따라)
        data_range = y.max() - y.min()
        if data_range == 0:
            return 0.0
        
        normalized_slope = abs(slope) / data_range
        
        # 0~1 사이로 제한
        return min(1.0, normalized_slope * 10)
    
    def _detect_acceleration(self, data: pd.Series) -> str:
        """
        추세의 가속도/감속도 감지
        """
        if len(data) < 3:
            return 'constant'
        
        # 2차 미분 (가속도)
        first_diff = data.diff().dropna()
        second_diff = first_diff.diff().dropna()
        
        if len(second_diff) == 0:
            return 'constant'
        
        avg_acceleration = second_diff.mean()
        
        if avg_acceleration > 0:
            return 'accelerating'
        elif avg_acceleration < 0:
            return 'decelerating'
        else:
            return 'constant'
    
    def _detect_reversal_signals(self, df: pd.DataFrame, indicator_col: str) -> Dict:
        """
        반전 신호 감지 (다이버전스, 과매수/과매도 등)
        """
        if len(df) < 20 or indicator_col not in df.columns:
            return {'bullish_divergence': False, 'bearish_divergence': False}
        
        # 가격 데이터 찾기
        price_col = 'close' if 'close' in df.columns else None
        if not price_col:
            return {'bullish_divergence': False, 'bearish_divergence': False}
        
        # 최근 40개 캔들로 다이버전스 검사
        lookback = min(40, len(df))
        df_slice = df.tail(lookback)
        
        # 피크/바닥 찾기
        indicator_data = df_slice[indicator_col].dropna()
        price_data = df_slice[price_col].dropna()
        
        if len(indicator_data) < 10 or len(price_data) < 10:
            return {'bullish_divergence': False, 'bearish_divergence': False}
        
        # 피크 찾기
        peaks, _ = find_peaks(indicator_data, distance=max(3, len(indicator_data)//10))
        troughs, _ = find_peaks(-indicator_data, distance=max(3, len(indicator_data)//10))
        
        bullish_div = False
        bearish_div = False
        
        # 상승 다이버전스: 지표는 하락, 가격은 상승
        if len(troughs) >= 2:
            last_trough = troughs[-1]
            prev_trough = troughs[-2]
            
            if (indicator_data.iloc[last_trough] > indicator_data.iloc[prev_trough] and
                price_data.iloc[last_trough] < price_data.iloc[prev_trough]):
                bullish_div = True
        
        # 하락 다이버전스: 지표는 상승, 가격은 하락
        if len(peaks) >= 2:
            last_peak = peaks[-1]
            prev_peak = peaks[-2]
            
            if (indicator_data.iloc[last_peak] < indicator_data.iloc[prev_peak] and
                price_data.iloc[last_peak] > price_data.iloc[prev_peak]):
                bearish_div = True
        
        return {
            'bullish_divergence': bullish_div,
            'bearish_divergence': bearish_div
        }
    
    def _classify_pattern(self, direction: str, strength: float, acceleration: str) -> str:
        """
        패턴 종합 분류
        """
        if direction == 'uptrend':
            if strength > 0.7:
                if acceleration == 'accelerating':
                    return 'strong_accelerating_uptrend'
                elif acceleration == 'decelerating':
                    return 'strong_decelerating_uptrend'
                else:
                    return 'strong_uptrend'
            else:
                return 'weak_uptrend'
        
        elif direction == 'downtrend':
            if strength > 0.7:
                if acceleration == 'accelerating':
                    return 'strong_accelerating_downtrend'
                elif acceleration == 'decelerating':
                    return 'strong_decelerating_downtrend'
                else:
                    return 'strong_downtrend'
            else:
                return 'weak_downtrend'
        
        else:
            return 'sideways'
    
    def detect_multi_indicator_pattern(self, df: pd.DataFrame, 
                                      indicator_cols: List[str]) -> Dict:
        """
        여러 지표의 패턴을 종합 분석합니다.
        
        Args:
            df: 데이터프레임
            indicator_cols: 분석할 지표 컬럼명 리스트
        
        Returns:
            종합 패턴 분석 결과
        """
        patterns = {}
        for col in indicator_cols:
            if col in df.columns:
                patterns[col] = self.detect_trend_pattern(df, col)
        
        # 패턴 일치도 계산
        if not patterns:
            return {'consensus': 'unknown', 'agreement_ratio': 0}
        
        # 방향성 일치도
        directions = [p['direction'] for p in patterns.values() if 'direction' in p]
        if directions:
            uptrend_count = directions.count('uptrend')
            downtrend_count = directions.count('downtrend')
            total = len(directions)
            
            if uptrend_count / total >= 0.6:
                consensus = 'uptrend'
                agreement_ratio = uptrend_count / total
            elif downtrend_count / total >= 0.6:
                consensus = 'downtrend'
                agreement_ratio = downtrend_count / total
            else:
                consensus = 'mixed'
                agreement_ratio = max(uptrend_count, downtrend_count) / total
        else:
            consensus = 'unknown'
            agreement_ratio = 0
        
        return {
            'individual_patterns': patterns,
            'consensus': consensus,
            'agreement_ratio': agreement_ratio,
            'total_indicators': len(patterns)
        }

