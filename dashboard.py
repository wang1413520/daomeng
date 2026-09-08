#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""到梦空间 · 本地控制台服务（客户端 V1）
纯标准库实现：HTTP + SSE 实时事件 + 内嵌引擎线程
默认 http://127.0.0.1:8921  （仅本机回环）

用法:
  python dashboard.py            # 启动并自动打开浏览器
  python dashboard.py --no-open  # 启动不弹浏览器
  python dashboard.py --no-engine# 只开面板不自动启动引擎
"""
import argparse
import json
import logging
import mimetypes
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)
WEB_DIR = os.path.join(getattr(sys, "_MEIPASS", BASE), "web") if getattr(sys, "frozen", False) \
    else os.path.join(BASE, "web")
sys.path.insert(0, BASE)

from engine import Engine, load_cfg  # noqa: E402
from mailer import Mailer  # noqa: E402

log = logging.getLogger("bot.dash")
MASK = "********"


class Hub:
    """SSE 广播中枢：engine 事件 -> 所有订阅队列"""

    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def push(self, event: dict):
        with self._lock:
            for q in list(self._subs):
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass  # 客户端太慢则丢弃，前端会从 /api/events 补拉


def deep_merge(old, new):
    """旧配置为基础深合并：只覆盖 new 中出现的键（保留未提交的默认段）"""
    out = dict(old)
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def cfg_apply_masked(dash, newcfg):
    """保存配置：密码/授权码打码或留空时保留旧值，然后写盘并热更新"""
    old = dash.cfg
    for sec, key in (("account", "password"), ("mail", "auth_code")):
        v = newcfg.get(sec, {}).get(key)
        if v in (None, "", MASK):
            newcfg.setdefault(sec, {})[key] = old.get(sec, {}).get(key, "")
    dash.cfg = deep_merge(old, newcfg)
    with open(dash.cfg_path, "w", encoding="utf-8") as f:
        yaml_safe_dump(dash.cfg, f)
    dash.engine.reload_config(dash.cfg)
    log.info("配置已保存并热更新")
    return True


class Dash:
    def __init__(self, cfg_path, dry=False, auto_engine=True):
        self.cfg_path = cfg_path
        self.cfg = load_cfg(cfg_path)
        self.hub = Hub()
        self.engine = Engine(self.cfg, dry_run=dry)
        self.engine.on_event(self.hub.push)
        self.auto_engine = auto_engine
        self.dash_cfg = self.cfg.get("dashboard", {})
        self.port = int(self.dash_cfg.get("port", 8921))
        self.balloon = None
        self.started = time.time()
        log.info("Dashboard 初始化完成，端口 %d", self.port)

    # ---------------- 系统通知 ----------------
    def start_notifier(self):
        try:
            from notify import balloon
            self.balloon = balloon("http://127.0.0.1:%d" % self.port)

            def on_signup(ev):
                if ev.get("type") == "signup" and ev.get("level") in ("success", "error"):
                    title = "到梦·报名成功" if ev["level"] == "success" else "到梦·报名失败"
                    if self.balloon:
                        self.balloon.show(title, (ev.get("title") or "")[:120])

            self.engine.on_event(on_signup)
            log.info("系统气泡通知已启用")
        except Exception as e:
            log.warning("系统通知不可用: %s", e)

    # ---------------- HTTP API ----------------
    def send_json(self, h, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        h.send_response(status)
        h.send_header("Content-Type", "application/json; charset=utf-8")
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        h.wfile.write(body)

    def send_static(self, h, name):
        if name in ("", "/"):
            name = "index.html"
        name = os.path.normpath(name.lstrip("/"))
        if name.startswith("..") or "\\" in name:
            self.send_json(h, {"error": "bad path"}, 400)
            return
        path = os.path.join(WEB_DIR, name)
        if not os.path.isfile(path):
            self.send_json(h, {"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            body = f.read()
        h.send_response(200)
        h.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        h.wfile.write(body)

    def read_json(self, h):
        ln = int(h.headers.get("Content-Length") or 0)
        if ln <= 0:
            return {}
        try:
            return json.loads(h.rfile.read(ln).decode("utf-8"))
        except Exception:
            return {}

    # 配置读写（密码字段打码往返）
    def cfg_sanitized(self):
        import copy
        c = copy.deepcopy(self.cfg)
        if c.get("account", {}).get("password"):
            c["account"]["password"] = MASK
        if c.get("mail", {}).get("auth_code"):
            c["mail"]["auth_code"] = MASK
        return c

    def handle_api(self, h, path, method, query):
        import urllib.parse
        if path == "/api/state":
            self.send_json(h, self.engine.snapshot())

        elif path == "/api/events":
            after = int(query.get("after", ["0"])[0] or 0)
            rows = self.engine.store.events_after(after, limit=500)
            self.send_json(h, {"rows": rows, "next": (rows[-1]["id"] if rows else after)})

        elif path == "/api/records":
            types = ["hit", "signup", "cycle", "mail", "state", "error"]
            rows = self.engine.store.events_recent(types=types, limit=300)
            self.send_json(h, {"rows": rows})

        elif path == "/api/archive":
            self.send_json(h, {"rows": self.engine.store.archive()})

        elif path == "/api/trend":
            days = int(query.get("days", ["7"])[0])
            self.send_json(h, {"days": self.engine.store.trend(days)})

        elif path == "/api/config" and method == "GET":
            self.send_json(h, {"cfg": self.cfg_sanitized()})

        elif path == "/api/config" and method == "POST":
            body = self.read_json(h)
            if "cfg" in body:
                cfg_apply_masked(self, body["cfg"])
            self.send_json(h, {"ok": True})

        elif path == "/api/control" and method == "POST":
            body = self.read_json(h)
            act = body.get("action")
            if act == "start":
                ok = self.engine.start()
                self.send_json(h, {"ok": True, "started": ok})
            elif act == "stop":
                ok = self.engine.stop()
                self.send_json(h, {"ok": True, "stopped": ok})
            elif act == "cycle":
                ok = self.engine.trigger()
                self.send_json(h, {"ok": True, "triggered": ok})
            else:
                self.send_json(h, {"error": "unknown action"}, 400)

        elif path == "/api/mailtest" and method == "POST":
            m = Mailer(self.cfg.get("mail", {}))
            ok = m.send("【到梦空间】控制台测试通知",
                        "时间：%s\n内容：QQ 邮箱通知链路正常。" %
                        time.strftime("%Y-%m-%d %H:%M:%S"))
            self.send_json(h, {"ok": ok})

        elif path == "/api/account/apply" and method == "POST":
            body = self.read_json(h)
            phone = str(body.get("phone", "")).strip()
            pwd = str(body.get("password", "") or "").strip()
            old_phone = str(self.cfg.get("account", {}).get("phone", "")).strip()
            old_pwd = str(self.cfg.get("account", {}).get("password", ""))
            if not phone:
                self.send_json(h, {"ok": False, "msg": "手机号不能为空"}, 400)
                return
            eff_pwd = pwd if pwd else old_pwd
            if not eff_pwd:
                self.send_json(h, {"ok": False, "msg": "未设置过密码且本次未填写，无法验证"})
                return
            ok, info = self.engine.probe_login(phone, eff_pwd)
            if not ok:
                self.send_json(h, {"ok": False, "msg": info})
                return
            # 验证通过：先落盘（改手机号；密码仅在用户本次填写新值时更新）
            cfg_upd = {"account": {"phone": phone}}
            if pwd and pwd != old_pwd:
                cfg_upd["account"]["password"] = pwd
            cfg_apply_masked(self, cfg_upd)
            self.engine.install_session(info)
            self.send_json(h, {"ok": True, "msg": "账号已切换", "session": {
                "name": info.get("name"), "school": info.get("school")}})

        elif path == "/api/notifytest" and method == "POST":
            ok = False
            if self.balloon:
                ok = bool(self.balloon.show("到梦空间 · 工作台", "系统气泡通知链路正常"))
            self.send_json(h, {"ok": ok})

        elif path == "/api/autostart" and method == "GET":
            self.send_json(h, autostart_get())

        elif path == "/api/autostart" and method == "POST":
            body = self.read_json(h)
            ok = autostart_set(bool(body.get("enabled")))
            self.send_json(h, {"ok": ok, **autostart_get()})

        elif path == "/api/stream":
            self.handle_sse(h)

        elif path == "/api/handled":
            rows = self.engine.store.query(
                "SELECT aid,name,ok,attempts,code,msg,ts FROM handled ORDER BY ts DESC LIMIT 200")
            self.send_json(h, {"rows": [dict(zip(
                ["aid", "name", "ok", "attempts", "code", "msg", "ts"], r)) for r in rows]})

        else:
            self.send_json(h, {"error": "not found", "path": path}, 404)

    def handle_sse(self, h):
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream; charset=utf-8")
        h.send_header("Cache-Control", "no-store")
        h.send_header("Connection", "keep-alive")
        h.end_headers()
        q = self.hub.subscribe()
        try:
            while True:
                try:
                    ev = q.get(timeout=12)
                    line = json.dumps(ev, ensure_ascii=False)
                    h.wfile.write(("data: " + line + "\n\n").encode("utf-8"))
                    h.wfile.flush()
                except queue.Empty:
                    h.wfile.write(b": keepalive\n\n")
                    h.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.hub.unsubscribe(q)

    # ---------------- 请求分发 ----------------
    def dispatch(self, h):
        import urllib.parse
        parsed = urllib.parse.urlparse(h.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        method = h.command

        if path.startswith("/api/"):
            try:
                self.handle_api(h, path, method, qs)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                log.exception("API 处理失败 %s %s", method, path)
                try:
                    self.send_json(h, {"error": str(e)}, 500)
                except Exception:
                    pass
            return
        # 静态资源（含首页）
        self.send_static(h, path)


# ---------------- 开机自启（HKCU Run） ----------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DreamDMKWorkbench"


def _autostart_cmd():
    if getattr(sys, "frozen", False):
        return '"%s" --no-open' % sys.executable
    py = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(py):
        py = sys.executable
    return '"%s" "%s" --no-open' % (py, os.path.abspath(__file__))


def autostart_get():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, RUN_NAME)
        return {"enabled": True, "cmd": val}
    except Exception:
        return {"enabled": False, "cmd": None}


def autostart_set(enabled):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _autostart_cmd())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        log.error("开机自启设置失败: %s", e)
        return False


def make_handler(dash: Dash):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass  # 静默访问日志

        def do_GET(self):
            dash.dispatch(self)

        def do_POST(self):
            dash.dispatch(self)

    return Handler


def setup_logging(level="INFO"):
    from logging.handlers import RotatingFileHandler
    os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    fh = RotatingFileHandler(os.path.join(BASE, "logs", "dashboard.log"),
                             maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                      "%Y-%m-%d %H:%M:%S"))
    root.addHandler(ch)
    root.addHandler(fh)


class DashServer(ThreadingHTTPServer):
    """独占端口绑定（Windows 下 SO_REUSEADDR 会允许双绑定导致双引擎，必须关闭）"""
    allow_reuse_address = False


def open_app_window(url):
    """以 App 模式（独立进程+独立窗口、无地址栏）打开工作台。
    使用专属 user-data-dir，避免被并入已开着的 Edge 标签页。"""
    try:
        edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        if os.path.isfile(edge):
            prof = os.path.join(BASE, ".edge-app")
            os.makedirs(prof, exist_ok=True)
            subprocess.Popen([edge,
                              "--user-data-dir=" + prof,
                              "--no-first-run", "--no-default-browser-check",
                              "--app=" + url])
            log.info("以独立 App 窗口打开: %s", url)
            return True
    except Exception as e:
        log.warning("Edge App 窗口启动失败: %s", e)
    webbrowser.open(url)  # 兜底：普通浏览器
    return False


def main():
    ap = argparse.ArgumentParser(description="到梦空间控制台（本地 Web 客户端）")
    ap.add_argument("-c", "--config", default=os.path.join(BASE, "config.yaml"))
    ap.add_argument("--port", type=int, default=None, help="覆盖端口（默认读 config dashboard.port）")
    ap.add_argument("--no-open", action="store_true", help="启动后不自动打开浏览器")
    ap.add_argument("--no-engine", action="store_true", help="只开面板，不自动启动引擎")
    ap.add_argument("--dry-run", action="store_true", help="引擎以试运行模式启动")
    ap.add_argument("--app", action="store_true",
                    help="桌面模式：以独立 App 窗口打开（服务已在跑时仅开窗，不重复启动）")
    args = ap.parse_args()

    dash = Dash(args.config, dry=args.dry_run, auto_engine=not args.no_engine)
    if args.port:
        dash.port = args.port
    if not os.path.isdir(WEB_DIR):
        sys.exit("缺少 web/ 目录（前端资源）")

    url = "http://127.0.0.1:%d" % dash.port
    try:
        srv = DashServer(("127.0.0.1", dash.port), make_handler(dash))
    except OSError:
        # 端口被占用：已有实例在跑（自启/手动）。附加模式：仅打开窗口/页面。
        log.warning("端口 %d 已有工作台服务在运行，进入附加模式", dash.port)
        dash.engine.stop()
        if args.app:
            open_app_window(url)
        elif not args.no_open:
            webbrowser.open(url)
        return
    srv.daemon_threads = True
    log.info("控制台已就绪: %s", url)
    dash.start_notifier()

    if dash.auto_engine:
        dash.engine.start()

    if args.app:
        threading.Timer(0.8, open_app_window, args=(url,)).start()
    elif not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        log.info("收到停止信号")
    finally:
        dash.engine.stop()
        srv.server_close()
        log.info("控制台已退出")


def yaml_safe_dump(cfg, f):
    import yaml
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


if __name__ == "__main__":
    import logging as _lg
    _lg.getLogger().handlers.clear()
    setup_logging()
    main()
