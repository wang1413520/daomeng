# -*- coding: utf-8 -*-
"""组装 Electron 桌面应用（无需 asar/electron-builder）：
   dist/DreamDMK-Desktop/
     DreamDMK.exe                <- electron.exe（改名）
     *.dll / locales/ 等运行时
     resources/app/
       package.json  main.js  icon.ico
       backend/DreamDMK.exe      <- PyInstaller 后端（dashboard+引擎+前端）
"""
import os
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
ELEC_DIST = os.path.join(BASE, ".electron-tool", "node_modules", "electron", "dist")
PYI_DIST = os.path.join(BASE, "dist", "DreamDMK")          # PyInstaller 后端
OUT = os.path.join(BASE, "dist", "DreamDMK-Desktop")
APP_SRC = os.path.join(BASE, "app_shell")
ICO = os.path.join(BASE, "app_assets", "icon.ico")

for p, what in ((ELEC_DIST, "Electron 运行时"), (PYI_DIST, "PyInstaller 后端"),
                (APP_SRC, "app_shell"), (ICO, "icon.ico")):
    if not os.path.exists(p):
        raise SystemExit("缺少 %s: %s（先跑 build_exe.py / 安装 electron）" % (what, p))

if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)
print("[1/3] 复制 Electron 运行时…")
for name in os.listdir(ELEC_DIST):
    s = os.path.join(ELEC_DIST, name)
    d = os.path.join(OUT, name)
    if os.path.isdir(s):
        shutil.copytree(s, d, ignore=shutil.ignore_patterns("*.pyc"))
    else:
        shutil.copy2(s, d)
exe = os.path.join(OUT, "electron.exe")
renamed = os.path.join(OUT, "DreamDMK.exe")
if os.path.exists(exe) and not os.path.exists(renamed):
    os.rename(exe, renamed)

print("[2/3] 复制后端到 resources/app/backend …")
appdir = os.path.join(OUT, "resources", "app")
shutil.copytree(PYI_DIST, os.path.join(appdir, "backend"))

print("[3/3] 写入外壳 resources/app …")
for f in ("package.json", "main.js"):
    shutil.copy2(os.path.join(APP_SRC, f), os.path.join(appdir, f))
shutil.copy2(ICO, os.path.join(appdir, "icon.ico"))

sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(OUT) for f in fs)
print("完成：", os.path.join(OUT, "DreamDMK.exe"), " 总计 %.0f MB" % (sz / 1048576))
print("双击 DreamDMK.exe 即为独立桌面应用（自带后端，无需 Python/Node）")
