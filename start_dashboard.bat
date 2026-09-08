@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  到梦空间 · 自动报名工作台（客户端）
echo  启动后将自动打开浏览器: http://127.0.0.1:8921
echo  关闭本窗口 = 停止控制台与引擎
echo ============================================
venv\Scripts\python.exe dashboard.py %*
