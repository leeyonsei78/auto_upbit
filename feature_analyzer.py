# feature_analyzer.py
# [★논문 반영 1단계★] 특징 상관관계 분석 모듈
# 지표 간 상관관계를 분석하여 중복 지표 제거 및 가중치 조정 제안

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional

class FeatureAnalyzer:
    """
    지표 간 상관관계를 분석하여 중복 지표를 식별하고,
    특징 선택을 최적화하는 클래스
    """
    
    def __init__(self, correlation_threshold: float = 0.8):
        """
        Args:
            correlation_threshold: 상관관계 임계값 (기본 0.8)
                                   이 값 이상이면 중복 지표로 간주
        """
        self.correlation_threshold = correlation_threshold
        self.correlation_matrix = None
        self.duplicate_pairs = []
        self.recommended_features = []
    
    def analyze_correlations(self, df: pd.DataFrame, indicator_cols: List[str]) -> Dict:
        """
        지표 간 상관관계를 분석합니다.
        
        Args:
            df: OHLCV 데이터프레임 (지표 포함)
            indicator_cols: 분석할 지표 컬럼명 리스트
        
        Returns:
            분석 결과 딕셔너리
        """
        if df is None or df.empty:
            return {'error': '데이터프레임이 비어있습니다.'}
        
        # 지표 컬럼만 필터링 (NaN이 너무 많은 컬럼 제외)
        available_cols = []
        for col in indicator_cols:
            if col in df.columns:
                non_null_ratio = df[col].notna().sum() / len(df)
                if non_null_ratio > 0.5:  # 50% 이상 데이터가 있어야 분석
                    available_cols.append(col)
        
        if len(available_cols) < 2:
            return {'error': '분석 가능한 지표가 부족합니다 (최소 2개 필요).'}
        
        # 상관관계 계산
        self.correlation_matrix = df[available_cols].corr()
        
        # 중복 지표 쌍 찾기
        self.duplicate_pairs = []
        for i, col1 in enumerate(available_cols):
            for col2 in available_cols[i+1:]:
                corr = abs(self.correlation_matrix.loc[col1, col2])
                if not pd.isna(corr) and corr >= self.correlation_threshold:
                    self.duplicate_pairs.append({
                        'indicator1': col1,
                        'indicator2': col2,
                        'correlation': corr,
                        'recommendation': self._recommend_feature_to_keep(col1, col2, df)
                    })
        
        # 추천 특징 선택 (중복 제거)
        self.recommended_features = self._select_recommended_features(available_cols)
        
        return {
            'correlation_matrix': self.correlation_matrix,
            'duplicate_pairs': self.duplicate_pairs,
            'recommended_features': self.recommended_features,
            'total_indicators': len(available_cols),
            'duplicate_count': len(self.duplicate_pairs)
        }
    
    def _recommend_feature_to_keep(self, col1: str, col2: str, df: pd.DataFrame) -> str:
        """
        두 지표 중 어떤 것을 유지할지 추천합니다.
        기준: 변동성이 더 크고, 결측치가 적은 지표
        """
        def get_score(col):
            if col not in df.columns:
                return -1
            data = df[col].dropna()
            if len(data) < 10:
                return -1
            # 변동성 (표준편차) + 데이터 완성도
            std_score = data.std() if not data.empty else 0
            completeness = len(data) / len(df)
            return std_score * completeness
        
        score1 = get_score(col1)
        score2 = get_score(col2)
        
        if score1 > score2:
            return f"{col1} 유지 권장 (변동성/완성도 우수)"
        elif score2 > score1:
            return f"{col2} 유지 권장 (변동성/완성도 우수)"
        else:
            return f"{col1} 또는 {col2} (동일 수준)"
    
    def _select_recommended_features(self, all_cols: List[str]) -> List[str]:
        """
        중복을 제거한 추천 특징 리스트를 생성합니다.
        """
        if not self.duplicate_pairs:
            return all_cols
        
        # 중복 쌍에서 제거할 지표들
        to_remove = set()
        for pair in self.duplicate_pairs:
            # 두 지표 중 하나는 제거 (일단 첫 번째 유지, 두 번째 제거)
            # 실제로는 더 정교한 로직 필요하지만, 단순화
            to_remove.add(pair['indicator2'])
        
        recommended = [col for col in all_cols if col not in to_remove]
        return recommended if recommended else all_cols
    
    def get_feature_importance(self, df: pd.DataFrame, target_col: str, 
                               indicator_cols: List[str]) -> Dict[str, float]:
        """
        각 지표가 목표 변수(예: 가격 변화율)에 미치는 영향력을 계산합니다.
        
        Args:
            df: 데이터프레임
            target_col: 목표 변수 컬럼명 (예: 'price_change_pct')
            indicator_cols: 분석할 지표 컬럼명 리스트
        
        Returns:
            지표별 중요도 딕셔너리
        """
        if target_col not in df.columns:
            return {}
        
        importance = {}
        target_data = df[target_col].dropna()
        
        for col in indicator_cols:
            if col not in df.columns:
                continue
            
            indicator_data = df[col].dropna()
            if len(indicator_data) < 10:
                continue
            
            # 공통 인덱스로 정렬
            common_idx = target_data.index.intersection(indicator_data.index)
            if len(common_idx) < 10:
                continue
            
            target_common = target_data.loc[common_idx]
            indicator_common = indicator_data.loc[common_idx]
            
            # 상관관계의 절댓값을 중요도로 사용
            corr = abs(target_common.corr(indicator_common))
            if not pd.isna(corr):
                importance[col] = corr
        
        # 중요도 정렬
        sorted_importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))
        return sorted_importance
    
    def suggest_weight_adjustments(self, correlation_result: Dict, 
                                   current_weights: Dict[str, float]) -> Dict[str, float]:
        """
        상관관계 분석 결과를 바탕으로 가중치 조정을 제안합니다.
        
        Args:
            correlation_result: analyze_correlations()의 결과
            current_weights: 현재 가중치 딕셔너리
        
        Returns:
            조정된 가중치 딕셔너리
        """
        adjusted_weights = current_weights.copy()
        
        # 중복 지표 쌍이 있으면 가중치 분산
        if correlation_result.get('duplicate_pairs'):
            for pair in correlation_result['duplicate_pairs']:
                col1, col2 = pair['indicator1'], pair['indicator2']
                
                # 가중치 키 이름 추론 (예: 'RSI_14' -> 'RSI_BUY_SCORE')
                weight_key1 = self._find_weight_key(col1, current_weights)
                weight_key2 = self._find_weight_key(col2, current_weights)
                
                if weight_key1 and weight_key2:
                    # 중복 지표의 가중치를 합쳐서 분배
                    total_weight = (adjusted_weights.get(weight_key1, 0) + 
                                   adjusted_weights.get(weight_key2, 0))
                    # 더 중요한 지표에 60%, 덜 중요한 지표에 40% 할당
                    adjusted_weights[weight_key1] = total_weight * 0.6
                    adjusted_weights[weight_key2] = total_weight * 0.4
        
        return adjusted_weights
    
    def _find_weight_key(self, indicator_col: str, weights: Dict) -> Optional[str]:
        """
        지표 컬럼명에서 가중치 키를 찾습니다.
        예: 'RSI_14' -> 'RSI_BUY_SCORE'
        """
        indicator_name = indicator_col.split('_')[0].upper()
        
        # 일반적인 매핑
        mapping = {
            'RSI': 'RSI',
            'MACD': 'MACD',
            'BBL': 'BBANDS',
            'BBU': 'BBANDS',
            'STOCHK': 'STOCH',
            'STOCHD': 'STOCH',
            'MFI': 'MFI',
            'OBV': 'OBV',
            'ADX': 'ADX',
            'SUPERT': 'SUPERTREND',
            'AROONU': 'AROON',
            'AROOND': 'AROON',
            'TSI': 'TSI'
        }
        
        prefix = None
        for key, value in mapping.items():
            if indicator_name.startswith(key):
                prefix = value
                break
        
        if not prefix:
            return None
        
        # BUY/SELL 가중치 키 찾기
        for key in weights.keys():
            if prefix in key:
                return key
        
        return None

