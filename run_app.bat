@echo off
echo Starting Streamlit app...

:: 1. Navigate to the folder where this batch file is located
cd /d "%~dp0"

:: 2. Activate the standard Python virtual environment
call .\.venv\Scripts\activate.bat

:: 3. Run the app
streamlit run main.py

pause