@echo off
cd /d "%~dp0"
python -u python_latency_test.py --backend p100r %*
if errorlevel 1 pause
