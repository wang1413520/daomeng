# -*- coding: utf-8 -*-
"""组装 Electron 桌面应用（无需 electron-builder）：
   dist/DreamDMK-Desktop/
     DreamDMK.exe                <- electron.exe（改名）
     *.dll / locales/ 等运行时
     resources/
       app.asar             <- 主代码(package.json/main.js/updater.js) 打包
       backend/DreamDMK.exe <- PyInstaller 后端（dashboard+引擎+前端）
       updater_apply.ps1    <- 更新替换脚本
       icon.ico             <- 窗口图标
"""
import os
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
TMPDIR = os.path.join(BASE, ".build_tmp")
os.makedirs(TMPDIR, exist_ok=True)
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

print("[2/4] 复制后端到 resources/backend …")
RES = os.path.join(OUT, "resources")
shutil.copytree(PYI_DIST, os.path.join(RES, "backend"))

print("[3/4] 打包主代码为 resources/app.asar …")
asar_src = os.path.join(TMPDIR, "app_asar_src")
if os.path.isdir(asar_src):
    shutil.rmtree(asar_src)
os.makedirs(asar_src)
for f in ("package.json", "main.js", "updater.js"):
    shutil.copy2(os.path.join(APP_SRC, f), os.path.join(asar_src, f))
asar_dir_old = os.path.join(RES, "app")
if os.path.isdir(asar_dir_old):
    shutil.rmtree(asar_dir_old, ignore_errors=True)
# 更新脚本与图标放资源根（供子进程/窗口使用，不入 asar）
shutil.copy2(os.path.join(APP_SRC, "updater_apply.ps1"), os.path.join(RES, "updater_apply.ps1"))
shutil.copy2(ICO, os.path.join(RES, "icon.ico"))

ASAR_JS = os.path.join(TMPDIR, "pack_asar.js")
code = ("var asar=require('@electron/asar');"
        "asar.createPackage('%s','%s').then(function(){console.log('asar ok')})"
        % (asar_src.replace("\\", "\\\\").replace("'", "\\'"),
           os.path.join(RES, "app.asar").replace("\\", "\\\\").replace("'", "\\'")))
with open(ASAR_JS, "w", encoding="utf-8") as f:
    f.write(code)
import subprocess
env = dict(os.environ)
env["NODE_PATH"] = os.path.join(BASE, ".electron-tool", "node_modules")
r = subprocess.run(["node", ASAR_JS], env=env, capture_output=True, text=True)
if r.returncode != 0 or "asar ok" not in r.stdout:
    raise SystemExit("asar 打包失败: %s %s" % (r.stdout, r.stderr))
shutil.rmtree(asar_src, ignore_errors=True)
print("  -> resources/app.asar 已生成")

sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(OUT) for f in fs)
print("完成：", os.path.join(OUT, "DreamDMK.exe"), " 总计 %.0f MB" % (sz / 1048576))
print("双击 DreamDMK.exe 即为独立桌面应用（自带后端，无需 Python/Node）")
