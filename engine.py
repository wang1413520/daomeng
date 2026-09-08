#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎层：到梦空间自动报名机器人核心（线程化、事件流、可被 CLI / Dashboard 共用）

- 逻辑与旧版 main.py Bot 完全一致（报名/筛选/熔断/去重）
- 新增：events 事件入库（log/cycle/hit/signup/mail）+ 订阅回调（推给 Web 控制台）
- 新增：start()/stop()/trigger() 线程化常驻循环 + snapshot() 状态快照
"""
import datetime
import json
import logging
import os
import random
import sqlite3
import sys
import threading
import time

import yaml

from dmkj import Api
from mailer import Mailer


def _app_dir():
    """源码目录；PyInstaller 冻结后为 exe 所在目录（配置/数据放旁边）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE = _app_dir()
TOKEN_FILE = os.path.join(BASE, "token.json")
log = logging.getLogger("bot")

TERMINAL_CODES = {"2000000", "2000011", "2000166", "2000004"}
TERMINAL_TEXT = ("已报", "重复报名", "不在活动规定", "不能报名", "活动不存在",
                 "已结束", "不是这个学院", "不是本学院")


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fmt_range(s):
    """'2026.09.08 12:10-2026.09.09 13:00' -> '09-08 12:10 ~ 09-09 13:00'"""
    try:
        parts = [x.strip() for x in str(s).split("-")]
        if len(parts) == 2:
            out = []
            for p in parts:
                seg = p.split()
                if len(seg) == 2:
                    d = seg[0].split(".")[-2:]
                    out.append("%s-%s %s" % (d[0], d[1], seg[1][:5]))
            if len(out) == 2:
                return " ~ ".join(out)
    except Exception:
        pass
    return str(s or "—")


def format_signup_mail(kind, name, aid, p, msg=""):
    """结果邮件：带活动画像。kind: success / terminal / retry
    p: {joindate,startdate,org,quota,category,online}"""
    status = {"success": "✅ 已报名成功",
              "terminal": "❌ 不可报名",
              "retry": "❌ 报名失败（将按上限自动重试）"}.get(kind, "—")
    subj = {"success": "【到梦空间】报名成功",
            "terminal": "【到梦空间】报名不可行",
            "retry": "【到梦空间】报名失败"}[kind]
    act_time = "%s%s" % (p.get("startdate", "—"),
                         "（线上）" if p.get("online") else "")
    body = "时间：%s\n活动ID：%s\n报名时间：%s\n活动时间：%s\n组织方：%s\n名额：%s\n分类：%s\n状态：%s" % (
        now_str()[:16], aid, p.get("joindate", "—"), act_time,
        p.get("org", "—"), p.get("quota", "—"), p.get("category", "—"), status)
    if msg:
        body += "\n服务器消息：%s" % str(msg)[:200]
    return ("%s - \"%s\"" % (subj, name), body)


def iso_now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def load_cfg(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("poll", {})
    cfg.setdefault("rules", {})
    cfg.setdefault("signup", {})
    cfg.setdefault("mail", {})
    cfg.setdefault("dashboard", {"port": 8921})
    return cfg


def mask_phone(p):
    p = str(p)
    return p[:3] + "****" + p[-4:] if len(p) >= 7 else "****"


def _locked(fn):
    """使 Store 方法线程安全（引擎线程 / HTTP 线程共用连接）"""

    def wrap(self, *a, **k):
        with self._lock:
            return fn(self, *a, **k)

    return wrap


class Store:
    """sqlite：handled=报名处理结果；seen=检查过不合规活动；events=控制台事件流"""

    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS handled("
            "aid TEXT PRIMARY KEY, name TEXT, ok INT DEFAULT 0,"
            "attempts INT DEFAULT 0, code TEXT, msg TEXT, ts TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS seen(aid TEXT PRIMARY KEY, ts TEXT)")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS events("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, type TEXT, level TEXT,"
            "title TEXT, aid TEXT, detail TEXT)")
        try:
            self.conn.execute("ALTER TABLE seen ADD COLUMN name TEXT")
        except Exception:
            pass  # 已存在
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_id ON events(id)")
        self.conn.commit()

    @_locked
    def get(self, aid):
        cur = self.conn.execute(
            "SELECT aid,name,ok,attempts,code,msg,ts FROM handled WHERE aid=?", (aid,))
        row = cur.fetchone()
        return {"aid": row[0], "name": row[1], "ok": row[2], "attempts": row[3],
                "code": row[4], "msg": row[5], "ts": row[6]} if row else None

    @_locked
    def record(self, aid, name, ok, code, msg):
        row = self.get(aid)
        attempts = (row["attempts"] + 1) if row else 1
        self.conn.execute(
            "INSERT INTO handled(aid,name,ok,attempts,code,msg,ts) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(aid) DO UPDATE SET name=excluded.name, ok=excluded.ok,"
            "attempts=excluded.attempts, code=excluded.code, msg=excluded.msg, ts=excluded.ts",
            (aid, name, 1 if ok else 0, attempts, code, msg, now_str()))
        self.conn.commit()
        return attempts

    @_locked
    def is_seen(self, aid):
        return self.conn.execute("SELECT 1 FROM seen WHERE aid=?", (aid,)).fetchone() is not None

    @_locked
    def mark_seen(self, aid, name=""):
        self.conn.execute(
            "INSERT INTO seen(aid,ts,name) VALUES(?,?,?) "
            "ON CONFLICT(aid) DO UPDATE SET ts=excluded.ts, "
            "name=CASE WHEN seen.name IS NULL OR seen.name='' THEN excluded.name ELSE seen.name END",
            (aid, now_str(), str(name)[:300]))
        self.conn.commit()

    @_locked
    def stats(self):
        cur = self.conn.execute(
            "SELECT SUM(ok), COUNT(*), (SELECT COUNT(*) FROM seen) FROM handled")
        ok, total, seen = cur.fetchone()
        today = self.conn.execute(
            "SELECT COUNT(*) FROM handled WHERE ok=1 AND ts LIKE ?",
            (datetime.date.today().strftime("%Y-%m-%d") + "%",)).fetchone()[0]
        return {"ok": ok or 0, "total": total or 0, "seen": seen or 0, "ok_today": today}

    # ---------- 事件流 ----------
    @_locked
    def record_event(self, etype, level, title, aid=None, detail=None):
        try:
            cur = self.conn.execute(
                "INSERT INTO events(ts,type,level,title,aid,detail) VALUES(?,?,?,?,?,?)",
                (now_str(), etype, level, str(title)[:500], aid,
                 json.dumps(detail, ensure_ascii=False) if detail is not None else None))
            self.conn.commit()
            self._trim()
            return cur.lastrowid
        except Exception:
            log.warning("事件入库失败(type=%s)", etype, exc_info=False)
            return None

    @_locked
    def query(self, sql, args=()):
        """通用查询（HTTP 线程安全），返回 list[tuple]"""
        return self.conn.execute(sql, args).fetchall()

    @_locked
    def archive(self, limit=400):
        """活动档案：handled(处理过) + seen(观察中) 合并，按最近时间倒序"""
        rows = self.conn.execute(
            "SELECT 'handled' AS kind, aid, name, ts, code, msg, ok, attempts FROM handled "
            "UNION ALL "
            "SELECT 'seen', aid, name, ts, '', '', -1, 0 FROM seen "
            "ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [{"kind": r[0], "aid": r[1], "name": r[2], "ts": r[3], "code": r[4],
                 "msg": r[5], "ok": r[6], "attempts": r[7]} for r in rows]

    @_locked
    def _trim(self):
        try:
            self.conn.execute(
                "DELETE FROM events WHERE id <= "
                "(SELECT MAX(id)-3000 FROM events) AND (SELECT COUNT(*) FROM events) > 3000")
            self.conn.commit()
        except Exception:
            pass

    @_locked
    def events_after(self, after_id, limit=300):
        cur = self.conn.execute(
            "SELECT id,ts,type,level,title,aid,detail FROM events "
            "WHERE id>? ORDER BY id ASC LIMIT ?", (after_id, limit))
        return [{"id": r[0], "ts": r[1], "type": r[2], "level": r[3],
                 "title": r[4], "aid": r[5], "detail": r[6]} for r in cur.fetchall()]

    @_locked
    def events_recent(self, types=None, limit=200):
        sql = "SELECT id,ts,type,level,title,aid,detail FROM events"
        args = []
        if types:
            sql += " WHERE type IN (%s)" % ",".join("?" * len(types))
            args = list(types)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        cur = self.conn.execute(sql, args)
        return [{"id": r[0], "ts": r[1], "type": r[2], "level": r[3],
                 "title": r[4], "aid": r[5], "detail": r[6]} for r in cur.fetchall()]

    @_locked
    def trend(self, days=7):
        out = []
        today = datetime.date.today()
        for i in range(days - 1, -1, -1):
            d = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            total = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE type='signup' AND ts LIKE ?",
                (d + "%",)).fetchone()[0]
            ok = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE type='signup' AND level='success' AND ts LIKE ?",
                (d + "%",)).fetchone()[0]
            out.append({"date": d, "signups": total, "success": ok})
        return out


class Engine:
    """线程化引擎：常驻轮询/筛选/报名，事件回馈给订阅者"""

    def __init__(self, cfg: dict, dry_run: bool = False):
        self.cfg = cfg
        self.dry_run = dry_run or bool(cfg.get("dry_run", False))
        self.api = Api(timeout=int(cfg.get("poll", {}).get("timeout_sec", 20)))
        self.store = Store(os.path.join(BASE, cfg.get("state_db", "state.sqlite")))
        self.mail = Mailer(cfg.get("mail", {}))
        self.session = None
        self.consec_fail = 0
        self.detail_cache = {}
        self._profile_cache = {}
        self.listeners = []          # callable(event dict) 事件订阅（Web 推送）
        self._stop_evt = threading.Event()
        self._wake_evt = threading.Event()
        self._thread = None
        self.next_run_at = None
        self.last_cycle_at = None
        self.cycle_count = 0
        self.last_cycle = None       # 最近一轮摘要 dict
        self.started_at = None
        self.manual_run = False
        self.fatal = False

    # ---------------- 事件 ----------------
    def on_event(self, cb):
        self.listeners.append(cb)

    def emit(self, etype, level, title, aid=None, detail=None):
        eid = self.store.record_event(etype, level, title, aid, detail)
        ev = {"id": eid, "ts": now_str(), "type": etype, "level": level,
              "title": str(title)[:500], "aid": aid, "detail": detail}
        for cb in self.listeners:
            try:
                cb(ev)
            except Exception:
                pass
        return ev

    # ---------------- 登录态 ----------------
    def _load_saved(self):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("token") and d.get("uid"):
                self.session = d
                return True
        except Exception:
            pass
        return False

    def _save_session(self):
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(self.session, f, ensure_ascii=False)

    def login(self):
        acc = str(self.cfg["account"]["phone"]).strip()
        pwd = self.cfg["account"]["password"]
        res = self.api.login(acc, pwd)
        if str(res.get("code", "")) == "100":
            d = res.get("data") or {}
            self.session = {"token": d["token"], "uid": str(d["uid"]),
                            "name": d.get("name", ""), "schoolId": str(d.get("schoolId", "")),
                            "schoolName": d.get("schoolName", "")}
            self._save_session()
            log.info("登录成功：%s (uid=%s, schoolId=%s)", self.session["name"],
                     self.session["uid"], self.session["schoolId"])
            self.emit("state", "ok", "登录成功：%s" % self.session["name"])
            return
        raise RuntimeError("登录失败 code=%s msg=%s" % (res.get("code"), res.get("msg") or res))

    def ensure_session(self):
        if self.session and not self.session.get("schoolName"):
            # 老版本 token.json 缺元数据：重登一次补齐（仅首次）
            self.login()
            return
        if self.session:
            return
        if not self._load_saved():
            self.login()
        elif not self.session.get("schoolName"):
            self.login()
        else:
            log.info("复用本地登录态 (uid=%s)", self.session["uid"])
            self.emit("state", "ok", "复用本地登录态 (uid=%s)" % self.session["uid"])

    # ---------------- 账号切换（供设置页使用） ----------------
    def probe_login(self, phone, pwd):
        """用给定凭据独立试登录（不污染当前会话）。返回 (ok, info/err)"""
        try:
            res = self.api.login(str(phone).strip(), pwd)
        except Exception as e:
            return False, "网络错误：%s" % e
        code = str(res.get("code", ""))
        if code == "100":
            d = res.get("data") or {}
            return True, {"name": d.get("name", ""), "school": d.get("schoolName", ""),
                          "uid": str(d.get("uid", "")), "schoolId": str(d.get("schoolId", "")),
                          "token": d.get("token", "")}
        raw = res.get("msg") or (res.get("actionSheet") or {}).get("content") or ""
        return False, "登录失败 code=%s %s" % (code, str(raw)[:120])

    def install_session(self, info):
        """把已验证的登录结果装为当前会话（清旧态、写 token.json、广播事件）"""
        self.session = {"token": info["token"], "uid": info["uid"],
                        "name": info.get("name", ""), "schoolId": info.get("schoolId", ""),
                        "schoolName": info.get("school", "")}
        self.consec_fail = 0
        self.fatal = False
        try:
            self._save_session()
        except Exception:
            pass
        log.info("账号已切换：%s (%s)", self.session["name"], self.session["uid"])
        self.emit("state", "ok", "账号已切换：%s（%s）" % (self.session["name"], info.get("school", "")))

    # ---------------- 请求封装 ----------------
    def _call(self, fn_name, *args):
        self.api.school_id = (self.session or {}).get("schoolId", "")
        retries = int(self.cfg.get("poll", {}).get("max_retries", 3))
        backoff = int(self.cfg.get("poll", {}).get("retry_backoff_base", 30))
        last_err = None
        for attempt in range(retries + 2):
            try:
                res = getattr(self.api, fn_name)(self.session["token"], self.session["uid"], *args)
                if str(res.get("code", "")) == "400" and attempt == 0:
                    log.warning("登录态失效，重新登录")
                    self.login()
                    continue
                return res
            except Exception as e:
                last_err = e
                if attempt < retries + 1:
                    wait = backoff * (2 ** min(attempt, 4)) + random.uniform(0, 5)
                    log.warning("请求失败(%s)，%ds 后重试", e, int(wait))
                    time.sleep(wait)
        raise RuntimeError("请求持续失败: %s" % last_err)

    # ---------------- 发现 ----------------
    @staticmethod
    def _text_of(*vals):
        return " ".join(str(v) for v in vals if isinstance(v, str))

    def discover(self):
        pages = int(self.cfg.get("poll", {}).get("max_pages", 2))
        found, seen_aids = [], set()
        for page in range(1, pages + 1):
            res = self._call("activities", page, "", "", "")
            data = res.get("data") or {}
            lst = data.get("list") or []
            for it in lst:
                if not isinstance(it, dict) or "aid" not in it:
                    continue
                aid = str(it["aid"])
                if aid in seen_aids:
                    continue
                seen_aids.add(aid)
                if str(it.get("status", "")) == "3":
                    found.append(it)
            log.info("第 %d 页 %d 条，其中报名中 %d", page, len(lst),
                     sum(1 for x in lst if isinstance(x, dict) and str(x.get("status", "")) == "3"))
            if len(lst) == 0:
                break
        log.info("本轮发现报名中活动 %d 个", len(found))
        return found

    # ---------------- 挑选 ----------------
    def _kw_match(self, text):
        rules = self.cfg.get("rules", {})
        inc = [str(x) for x in rules.get("name_include", []) if str(x)]
        exc = [str(x) for x in rules.get("name_exclude", []) if str(x)]
        if exc and any(w in text for w in exc):
            return False, "命中排除词"
        if inc and not any(w in text for w in inc):
            return False, "无包含词"
        return True, ""

    def _detail_online(self, item):
        rules = self.cfg.get("rules", {})
        if not rules.get("detail_check", True):
            return False
        aid = str(item["aid"])
        if aid in self.detail_cache:
            return self.detail_cache[aid]
        try:
            res = self._call("activity_detail", aid)
            dd = res.get("data") or {}
            kw = [str(x).lower() for x in rules.get("detail_kw", ["线上", "online"]) if str(x)]
            text = self._text_of(dd.get("activityName"), dd.get("address"),
                                 dd.get("labelname"), dd.get("joinWayDesc"))
            hit = bool(kw) and any(w in text.lower() for w in kw)
            self.detail_cache[aid] = hit
            if hit:
                log.info("详情命中线上特征: %s [%s] address=%s", dd.get("activityName"), aid,
                         str(dd.get("address"))[:40])
            return hit
        except Exception as e:
            log.warning("详情查询失败 %s: %s", aid, e)
            return False

    def _matches(self, item):
        aid = str(item["aid"])
        name = item.get("name", "")
        hit, why = self._kw_match(name)
        if hit:
            return True
        if self._detail_online(item):
            return True
        self.store.mark_seen(aid, name)
        return False

    # ---------------- 报名 ----------------
    def _fetch_profile(self, aid):
        """取活动画像（详情接口）；失败返回空 dict，不阻断主流程"""
        try:
            if aid in self._profile_cache:
                return self._profile_cache[aid]
            res = self._call("activity_detail", aid)
            dd = (res.get("data") or {}) if str(res.get("code", "")) == "100" else {}
            text = " ".join(str(x) for x in (dd.get("address"), dd.get("activityName"),
                                             dd.get("joinWayDesc")) if isinstance(x, str))
            jm = int(dd.get("joinmaxnum") or dd.get("applyJoinMaxNum") or 0)
            jn = int(dd.get("joinNum") or 0)
            p = {
                "joindate": _fmt_range(dd.get("joindate")),
                "startdate": _fmt_range(dd.get("startdate")),
                "org": dd.get("outname") or dd.get("collegename") or dd.get("schoolname") or "—",
                "quota": ("%s/%s" % (jn, jm)) if jm > 0 else ("不限" if jn else "—"),
                "category": dd.get("catalog2name") or dd.get("catalog1name") or "—",
                "online": "线上" in text,
            }
            self._profile_cache[aid] = p
            return p
        except Exception as e:
            log.warning("画像获取失败 %s: %s", aid, e)
            return {}

    def _signup(self, item):
        aid = str(item["aid"])
        name = str(item.get("name", aid))
        row = self.store.get(aid)
        if row and row["ok"]:
            log.info("跳过 %s [%s]：此前已处理(ok)", name, aid)
            return
        max_try = int(self.cfg.get("signup", {}).get("max_fail_retries", 3))
        if row and row["attempts"] >= max_try:
            log.info("跳过 %s [%s]：已达重试上限", name, aid)
            return

        lo, hi = (int(x) for x in self.cfg.get("rules", {}).get("signup_wait_sec", [2, 6]))
        log.info("命中候选：%s [%s]，%.1fs 后提交…", name, aid, random.uniform(lo, hi))
        time.sleep(random.uniform(lo, hi))

        if self.dry_run or not self.cfg.get("signup", {}).get("auto", True):
            log.info("【试运行/未启用自动报名】不提交: %s [%s]", name, aid)
            self.store.record(aid, name, False, "-", "dry_run")
            self.emit("signup", "warn", "试运行·命中不提交：%s" % name, aid,
                      {"ok": False, "dry": True, "code": "-", "msg": "dry_run"})
            return

        res = self._call("signup_submit", aid)
        code = str(res.get("code", ""))
        raw_msg = res.get("msg") or res.get("result") or ""
        if not raw_msg:
            try:
                raw_msg = (res.get("actionSheet") or {}).get("content", "")
            except Exception:
                pass
        msg_s = str(raw_msg)[:200]

        if code == "100":
            attempts = self.store.record(aid, name, True, code, msg_s)
            log.info("★★ 报名成功：%s [%s]", name, aid)
            self.emit("signup", "success", "报名成功：%s" % name, aid,
                      {"ok": True, "code": code, "msg": msg_s, "attempts": attempts})
            self.mail.send(*format_signup_mail("success", name, aid,
                                               self._fetch_profile(aid), msg_s))
        elif code == "2000011" or "已报" in msg_s or "重复报名" in msg_s:
            self.store.record(aid, name, True, code, "已报名过")
            log.info("此前已报名过：%s [%s]（记入成功，不再重复）", name, aid)
            self.emit("signup", "info", "已报名过：%s" % name, aid,
                      {"ok": True, "code": code, "msg": "已报名过"})
        elif code in TERMINAL_CODES or any(t in msg_s for t in TERMINAL_TEXT):
            attempts = self.store.record(aid, name, False, code, msg_s)
            log.info("不可报名（终态）：%s [%s] code=%s msg=%s", name, aid, code, msg_s)
            self.emit("signup", "warn", "不可报名：%s" % name, aid,
                      {"ok": False, "terminal": True, "code": code, "msg": msg_s,
                       "attempts": attempts})
            if attempts == 1:
                self.mail.send(*format_signup_mail("terminal", name, aid,
                                                   self._fetch_profile(aid), msg_s))
        else:
            attempts = self.store.record(aid, name, False, code, msg_s)
            log.info("报名失败（将按上限重试）：%s [%s] code=%s msg=%s", name, aid, code, msg_s)
            self.emit("signup", "error", "报名失败：%s" % name, aid,
                      {"ok": False, "terminal": False, "code": code, "msg": msg_s,
                       "attempts": attempts})
            if attempts == 1:
                self.mail.send(*format_signup_mail("retry", name, aid,
                                                   self._fetch_profile(aid), msg_s))

    # ---------------- 轮次 ----------------
    def cycle(self):
        """执行一轮扫描+报名，返回摘要 dict（旧版 main.py 逻辑等价迁移）"""
        t0 = time.time()
        self.ensure_session()
        items = self.discover()
        self.detail_cache = {}
        self._profile_cache = {}
        hits = []
        for it in items:
            try:
                if self._matches(it):
                    hits.append(it)
            except Exception as e:
                log.warning("筛选异常 %s: %s", it.get("aid"), e)
        log.info("符合挑选规则的活动 %d 个", len(hits))
        for it in hits:
            try:
                self.emit("hit", "info", "命中候选：%s" % it.get("name"), str(it["aid"]),
                          {"status": "3"})
                self._signup(it)
            except Exception as e:
                log.warning("报名环节异常 %s: %s", it.get("aid"), e)
        stats = self.store.stats()
        log.info("本轮结束（成功%d/处理%d/待观察%d）", stats["ok"], stats["total"], stats["seen"])
        summary = {"found": len(items), "hits": len(hits), "stats": stats,
                   "elapsed": round(time.time() - t0, 1)}
        self.last_cycle = summary
        self.last_cycle_at = time.time()
        self.cycle_count += 1
        self.emit("cycle", "info",
                  "轮次 #%d 完成：发现 %d 个报名中 · 命中 %d · 累计成功 %d"
                  % (self.cycle_count, len(items), len(hits), stats["ok"]),
                  detail={"cycle": self.cycle_count, "found": len(items),
                          "hits": len(hits), "elapsed": summary["elapsed"]})
        return summary

    def run_cycle_safe(self):
        """带熔断保护的单轮执行（供线程/手动调用）"""
        try:
            self.cycle()
            self.consec_fail = 0
            self.fatal = False
        except Exception as e:
            self.consec_fail += 1
            wait = min(1800, 30 * (2 ** min(self.consec_fail, 5)))
            log.error("本轮异常：%s（连续第 %d 次，%ds 后继续）", e, self.consec_fail, wait)
            self.emit("error", "error", "本轮异常：%s" % e,
                      detail={"consec": self.consec_fail})
            if self.consec_fail >= 5:
                self.fatal = True
            self._sleep_until(time.time() + wait)

    # ---------------- 线程化常驻 ----------------
    def _sleep_until(self, until):
        while time.time() < until:
            if self._stop_evt.is_set():
                return False
            time.sleep(0.5)
        return True

    def _loop(self):
        log.info("常驻引擎启动（线程 %s）", threading.current_thread().name)
        self.emit("state", "ok", "引擎已启动")
        while not self._stop_evt.is_set():
            self.manual_run = False
            self.run_cycle_safe()
            if self._stop_evt.is_set():
                break
            poll = self.cfg.get("poll", {})
            base = int(poll.get("interval_sec", 900))
            jitter = int(poll.get("jitter_sec", 300))
            wait = max(60, base + random.uniform(-jitter, jitter))
            self.next_run_at = time.time() + wait
            log.info("休眠 %.0f 秒后进入下一轮", wait)
            # 等待：可被 stop() / trigger() 打断
            if self._wake_evt.wait(wait):
                self._wake_evt.clear()
                log.info("收到手动触发，立即执行下一轮")
            else:
                self.next_run_at = None
        log.info("常驻引擎已停止")
        self.emit("state", "warn", "引擎已停止")

    def start(self):
        if self._thread and self._thread.is_alive():
            return False
        self._stop_evt.clear()
        self._wake_evt.clear()
        self.started_at = time.time()
        self.next_run_at = None
        self._thread = threading.Thread(target=self._loop, name="engine", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if not (self._thread and self._thread.is_alive()):
            self._stop_evt.clear()
            return False
        self._stop_evt.set()
        self._wake_evt.set()
        self._thread.join(timeout=8)
        self.next_run_at = None
        return True

    def trigger(self):
        """手动触发一轮（立即执行）"""
        if self._thread and self._thread.is_alive():
            self._wake_evt.set()
            return True
        # 未在跑：前台跑一轮
        threading.Thread(target=self.run_cycle_safe, name="manual", daemon=True).start()
        return True

    # ---------------- 配置 ----------------
    def reload_config(self, cfg=None):
        if cfg is None:
            cfg = load_cfg(os.path.join(BASE, "config.yaml"))
        self.cfg = cfg
        self.mail = Mailer(cfg.get("mail", {}))
        self.api = Api(timeout=int(cfg.get("poll", {}).get("timeout_sec", 20)))
        log.info("配置已热更新")

    # ---------------- 快照（给 UI/API） ----------------
    def snapshot(self):
        stats = self.store.stats()
        running = bool(self._thread and self._thread.is_alive())
        s = {
            "app": "dream-dashboard",
            "version": "1.0.0",
            "running": running,
            "dry_run": self.dry_run,
            "auto": bool(self.cfg.get("signup", {}).get("auto", True)),
            "fatal": bool(self.fatal),
            "consec_fail": self.consec_fail,
            "interval_sec": int(self.cfg.get("poll", {}).get("interval_sec", 900)),
            "started_at": self.started_at,
            "next_run_at": self.next_run_at,
            "last_cycle_at": self.last_cycle_at,
            "cycle_count": self.cycle_count,
            "last_cycle": self.last_cycle,
            "stats": stats,
            "session": ({"name": self.session.get("name", ""),
                         "school": self.session.get("schoolName", ""),
                         "uid": self.session.get("uid", "")}
                        if self.session else None),
            "account_phone": mask_phone(self.cfg["account"]["phone"]),
            "mail_ready": bool(self.mail._ready) if hasattr(self.mail, "_ready") else False,
        }
        return s
