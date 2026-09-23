@echo off
rem --- 한글 깨짐 방지를 위해 UTF-8로 코드 페이지 변경 ---
chcp 65001 > nul

echo Streamlit 앱을 시작합니다...
echo.
echo 브라우저가 자동으로 열릴 것입니다.
echo (종료하려면 이 창을 닫으세요)
echo.

rem 현재 .bat 파일이 있는 폴더에서 app.py를 실행합니다.
streamlit run app.py

echo.
echo Streamlit 서버가 종료되었습니다.
pause

