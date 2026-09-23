# log_analyzer.py
# [수정]: 로그 시간 형식 오류 수정 (밀리초 %f 추가)
# [수정 2]: 정규표현식 오류 수정 (] - [ 구분자 및 '현재 손익' 키워드 추가)

import glob
import re
import pandas as pd
from datetime import datetime

def parse_pnl_logs():
    """
    logs/ 폴더 내의 모든 .log 파일에서 
    평가손익(%) 데이터를 파싱하여 DataFrame으로 반환합니다.
    """
    
    # --- [★수정★] ---
    # 1. ] \s+-\s+ [ : [시간]과 [티커] 사이의 " - " 구분자를 정확히 인식하도록 수정
    # 2. (?:평가손익|현재 손익): '평가손익' 또는 '현재 손익' 두 키워드를 모두 찾도록 수정
    # 3. ([-]?\d+(\.\d+)?)% : PNL 퍼센트가 정수(0%)일 경우도 인식하도록 수정
    log_pattern = re.compile(
        r'\[(.*?)\]\s+-\s+\[(KRW-\w+)\].*?(?:평가손익|현재 손익): .*? \(([-]?\d+(\.\d+)?)%\)'
    )
    # --- [★수정 완료★] ---
    
    data = []
    log_files = glob.glob("logs/*.log") # logs 폴더의 모든 .log 파일
    
    if not log_files:
        print("분석할 로그 파일이 'logs/' 폴더에 없습니다.")
        return pd.DataFrame()

    for file_path in log_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    match = log_pattern.search(line)
                    if match:
                        try:
                            # 1. 시간 파싱
                            time_str = match.group(1)
                            
                            # 봇 로그 시간 형식이 두 가지로 기록될 수 있음:
                            # 1) YYYY-MM-DD HH:MM:%S,fff (밀리초 포함)
                            # 2) YYYY-MM-DD HH:MM:%S (밀리초 미포함)
                            parsed = None
                            for fmt in ('%Y-%m-%d %H:%M:%S,%f', '%Y-%m-%d %H:%M:%S'):
                                try:
                                    parsed = datetime.strptime(time_str, fmt)
                                    break
                                except ValueError:
                                    continue
                            if parsed is None:
                                raise ValueError(f"time format not matched: {time_str}")
                            log_time = parsed
                            
                            # 2. 티커
                            ticker = match.group(2)
                            
                            # 3. PNL (퍼센트)
                            pnl_percent = float(match.group(3)) # group 3이 -9.85 또는 0 등을 반환
                            
                            data.append({
                                'time': log_time,
                                'ticker': ticker,
                                'pnl_percent': pnl_percent
                            })
                        except (ValueError, IndexError) as e:
                            # 시간 파싱 실패 등 예외 처리
                            print(f"로그 라인 파싱 실패 (시간 형식 오류?): {line.strip()} | 오류: {e}")
                            pass
        except Exception as e:
            print(f"파일 {file_path} 읽기 오류: {e}")

    if not data:
        print("로그에서 유효한 PNL 데이터를 파싱하지 못했습니다.")
        return pd.DataFrame()

    # 데이터프레임 생성 및 정렬
    df = pd.DataFrame(data)
    df = df.sort_values(by='time').reset_index(drop=True)
    return df

if __name__ == '__main__':
    # 스크립트를 직접 실행할 때 테스트
    df = parse_pnl_logs()
    if not df.empty:
        print(f"총 {len(df)}개의 PNL 데이터를 찾았습니다.")
        print(df.tail()) # 마지막 5개 데이터 출력
        print("\n--- 티커별 최근 데이터 ---")
        print(df.groupby('ticker').last())
    else:
        print("파싱된 데이터가 없습니다.")

