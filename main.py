#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""到梦空间自动报名机器人 · CLI（无头模式）

用法:
  python main.py                     # 常驻运行（Ctrl+C 停止）
  python main.py --once              # 只跑一个轮次后退出
  python main.py --once --dry-run    # 试运行：只探测与模拟，不提交报名

图形界面请运行 start_dashboard.bat 或 python dashboard.py
"""
import argparse
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE, "logs")


def setup_logging(level):
    os.makedirs(LOG_DIR, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    fh = RotatingFileHandler(os.path.join(LOG_DIR, "bot.log"), maxBytes=2 * 1024 * 1024,
                             backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                      "%Y-%m-%d %H:%M:%S"))
    root.addHandler(ch)
    root.addHandler(fh)


def main():
    ap = argparse.ArgumentParser(description="到梦空间自动报名机器人")
    ap.add_argument("-c", "--config", default=os.path.join(BASE, "config.yaml"))
    ap.add_argument("--once", action="store_true", help="只运行一个轮次")
    ap.add_argument("--dry-run", action="store_true", help="试运行：不提交真实报名")
    args = ap.parse_args()

    from engine import Engine, load_cfg  # 延迟导入，便于无依赖环境打印友好错误

    cfg = load_cfg(args.config)
    setup_logging(cfg.get("log_level", "INFO"))
    log = logging.getLogger("bot")
    dry = args.dry_run or bool(cfg.get("dry_run", False))
    if dry:
        log.warning("当前为试运行模式（dry_run）：不会提交真实报名")
    engine = Engine(cfg, dry_run=dry)
    if args.once:
        engine.run_cycle_safe()
        log.info("--once 结束")
    else:
        log.info("常驻模式启动。Ctrl+C 停止")
        engine.start()
        try:
            while engine._thread and engine._thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("收到停止信号，退出")
            engine.stop()


if __name__ == "__main__":
    main()
