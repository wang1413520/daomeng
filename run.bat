@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  到梦空间自动报名机器人
echo  试运行(不报名): venv\Scripts\python main.py --once --dry-run
echo  Ctrl+C 停止常驻进程
echo ============================================
venv\Scripts\python.exe main.py %*
pause
