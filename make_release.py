# -*- coding: utf-8 -*-
"""制作净身发布 zip：拷贝桌面应用/后端 → 剔除真实凭据与用户数据 → 压缩
产出: dist/release/dreamdmk-desktop-win-x64.zip / dreamdmk-backend-exe.zip
"""
import os
import shutil
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(BASE, ".release-stage")
OUT = os.path.join(BASE, "dist", "release")
TPL = os.path.join(BASE, ".publish", "dreamdmk-workbench", "config.yaml.example")

os.makedirs(OUT, exist_ok=True)
if os.path.isdir(STAGE):
    shutil.rmtree(STAGE)


def scrub(root):
    """清除所有真实凭据/用户数据，config.yaml 换成占位模板"""
    for dirpath, dirnames, filenames in os.walk(root):
        for f in list(filenames):
            low = f.lower()
            if low in ("token.json", "state.sqlite") or low.endswith(".log") or low in ("config.yaml",):
                p = os.path.join(dirpath, f)
                try:
                    os.remove(p)
                    print("  -", os.path.relpath(p, root))
                except OSError:
                    pass
        for d in list(dirnames):
            if d.lower() in (".data", ".update", "logs", "__pycache__", ".electron-app", ".publish"):
                p = os.path.join(dirpath, d)
                shutil.rmtree(p, ignore_errors=True)
                print("  -", os.path.relpath(p, root))


def build(name, src, want_cfg_template, cfg_at_root=False):
    dst = os.path.join(STAGE, name)
    print("[1/3]", name, "拷贝中…")
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".update", ".data"))
    print("[2/3]", name, "净身中…")
    scrub(dst)
    if want_cfg_template:
        # 后端绿色版：配置文件在包根目录；桌面版：在 resources/backend
        cfg_dst = os.path.join(dst, "config.yaml") if cfg_at_root \
            else os.path.join(dst, "resources", "backend", "config.yaml")
        if os.path.isfile(TPL) and os.path.isdir(os.path.dirname(cfg_dst)):
            shutil.copy2(TPL, cfg_dst)
            print("  + config.yaml <- 占位模板 ->", cfg_dst)
        else:
            print("  !!! 模板未写入:", cfg_dst)
    zip_path = os.path.join(OUT, name + ".zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    print("[3/3]", name, "压缩中（较大，请耐心）…")
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Compress-Archive -Path '" + dst + "\\*' -DestinationPath '" + zip_path + "' -CompressionLevel Optimal -Force"])
    if r.returncode != 0:
        raise SystemExit(name + " 压缩失败")
    sz = os.path.getsize(zip_path)
    print("完成:", zip_path, "%.0f MB" % (sz / 1048576))


build("dreamdmk-desktop-win-x64",
      os.path.join(BASE, "dist", "DreamDMK-Desktop"), want_cfg_template=True)
build("dreamdmk-backend-exe",
      os.path.join(BASE, "dist", "DreamDMK"), want_cfg_template=True, cfg_at_root=True)
shutil.rmtree(STAGE, ignore_errors=True)
print("ALL DONE")
