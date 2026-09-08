@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  到梦空间 · 自动报名工作台（桌面模式）
echo  以独立 App 窗口打开（无地址栏，像原生程序）
echo  关闭窗口不会停止引擎；再次运行本文件可重新开窗
echo ============================================
start "" venv\Scripts\pythonw.exe dashboard.py --app
