# -*- coding: utf-8 -*-
"""打包工作台为独立 exe（PyInstaller，onedir，无控制台窗口）

用法:  venv\\Scripts\\python build_exe.py
产出:  dist\\DreamDMK\\DreamDMK.exe   （双击即用，config.yaml 放同目录）
"""
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
VENV_SP = os.path.join(BASE, "venv", "Lib", "site-packages")
TMP = os.path.join(BASE, ".build_tmp")
os.makedirs(TMP, exist_ok=True)


def _install_wheel(pkg, pick_keyword):
    idx = "https://pypi.tuna.tsinghua.edu.cn/simple/%s/" % pkg
    html = urllib.request.urlopen(idx, timeout=40).read().decode("utf-8", "ignore")
    cand = []
    for m in re.finditer(r'href="([^"]+)"', html):
        href = m.group(1).split("#")[0]
        fn = href.split("/")[-1]
        if (fn.endswith(".whl") and (pick_keyword in fn)) or (
                pkg == "pywin32-ctypes" and fn.endswith("py3-none-any.whl")):
            cand.append(urllib.parse.urljoin(idx, href))
    if not cand:
        sys.exit("未找到 %s wheel" % pkg)
    url = sorted(cand)[-1]
    fn = os.path.basename(url)
    path = os.path.join(TMP, fn)
    if not os.path.exists(path):
        print("  下载", fn)
        with urllib.request.urlopen(url, timeout=240) as r, open(path, "wb") as f:
            shutil.copyfileobj(r, f)
    print("  安装到 venv site-packages …")
    with zipfile.ZipFile(path) as z:
        z.extractall(VENV_SP)


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        print("[1/4] PyInstaller 已就绪", PyInstaller.__version__)
    except Exception:
        print("[1/4] 下载 PyInstaller（清华镜像）…")
        _install_wheel("pyinstaller", "py3-none-win_amd64")
        import PyInstaller
        print("  PyInstaller", PyInstaller.__version__, "OK")
    try:
        import win32ctypes  # noqa: F401
    except Exception:
        print("  安装 pywin32-ctypes …")
        _install_wheel("pywin32-ctypes", "")
        import win32ctypes  # noqa: F401
        print("  pywin32-ctypes OK")


def build():
    print("[2/4] 开始打包（首次约 1-3 分钟）…")
    web_src = os.path.join(BASE, "web")
    py = os.path.join(BASE, "venv", "Scripts", "python.exe")
    cmd = [
        py, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--noconsole",
        "--name", "DreamDMK",
        "--add-data", web_src + os.pathsep + "web",
        "--distpath", os.path.join(BASE, "dist"),
        "--workpath", os.path.join(TMP, "work"),
        "--specpath", TMP,
        os.path.join(BASE, "dashboard.py"),
    ]
    r = subprocess.run(cmd, cwd=BASE)
    if r.returncode != 0:
        sys.exit("PyInstaller 失败")
    dist = os.path.join(BASE, "dist", "DreamDMK")
    print("[3/4] 复制运行配置到产物目录…")
    for f in ("config.yaml", "token.json"):
        src = os.path.join(BASE, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dist, f))
    print("[4/4] 完成：", os.path.join(dist, "DreamDMK.exe"))
    print("     使用：把 dist\\DreamDMK 整个文件夹拷到任意位置，双击 DreamDMK.exe")
    print("     （配置/数据/日志都会生成在 exe 同目录，不要放进 Program Files）")


if __name__ == "__main__":
    ensure_pyinstaller()
    build()
