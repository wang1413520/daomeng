# -*- coding: utf-8 -*-
"""到梦空间 APP v4.9.5 协议层（服务端验证通过的加密链）：

明文JSON(含timestamp+signToken, 键排序, 无空格, 值全为字符串)
  -> AES-CBC-PKCS5(key=随机16位session_key, iv=ReIV)   -> 段0
  -> session_key 经 RSA-1024-PKCS1_v1_5 加密            -> 段1
  -> d = base64(段0) + base64(段1)  （每60字符插空格）

signToken = MD5( SHA512hex(参数JSON)[1::2][0::2] ).hexdigest().upper()
参数JSON = 全部参数(不含signToken, 含timestamp) 键排序后紧凑序列化，值均为字符串
"""
import base64
import hashlib
import json
import os
import random
import string
import time
import urllib.parse
import urllib.request

import pyDes
from Crypto.Cipher import AES

# ---- 常量（逆向自 4.9.5，服务器实测有效） ----
API_HOST = "https://appdmkj.5idream.net"
APP_VERSION = "4.9.5"

AES_IV_RE = b"1628092121312213"          # 请求加密 IV (ReIV)
AES_IV_PL = b"9618953120112110"          # 明文 IV (PlIV，未用)
RSA_N_HEX = ("9eed813259ad13f963176bcab53d04a8d8dd79e85cfa73588dd162cc9b9747d4a05d1a8fd"
             "11ce7cb38186729bfdd82f6b24141df2b3b021f0d0f9bca4d1120e11554e5fd79dd8373b8"
             "025f8bf17a03e463dea876bc4862e8ad19cb38f864ea74e4aa53ef15735801dc8fcd3e98e7"
             "5ef5133d50d8515c5b88d40d3a39b055f6ab")
RSA_E = 65537
DES_KEY = b"51434574"                    # 密码 DES-ECB 密钥

_CHARS = string.ascii_letters + string.digits
_N_BYTES = bytes.fromhex(RSA_N_HEX)
_N_INT = int.from_bytes(_N_BYTES, "big")
_RSA_BLOCK = 128


# ---------------- 基础工具 ----------------
def pwd_encrypt(pwd: str) -> str:
    """DES-ECB + PKCS5 -> 大写 HEX"""
    k = pyDes.des(DES_KEY, pyDes.ECB, padmode=pyDes.PAD_PKCS5)
    return k.encrypt(pwd, padmode=pyDes.PAD_PKCS5).hex().upper()


def rand_session_key() -> str:
    return "".join(random.choice(_CHARS) for _ in range(16))


def fastjson(d: dict) -> str:
    """键排序、无空格、非 ascii 原样、值字符串"""
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def b64_spaces(s: str) -> str:
    """base64 文本每 60 字符插空格"""
    return " ".join(s[i:i + 60] for i in range(0, len(s), 60))


def aes_cbc_pkcs5(plain: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(plain)


def _pkcs7(b: bytes) -> bytes:
    pad = 16 - len(b) % 16
    return b + bytes([pad]) * pad


def rsa_pkcs1_v1_5(data: bytes) -> bytes:
    """RSA-1024 PKCS1_v1_5 type2 加密（117 字节内单块）"""
    if len(data) > _RSA_BLOCK - 11:
        raise ValueError("RSA 数据过长")
    ps_len = _RSA_BLOCK - 3 - len(data)
    ps = b""
    while len(ps) < ps_len:
        chunk = os.urandom(ps_len - len(ps))
        ps += chunk.replace(b"\x00", b"")
    em = b"\x00\x02" + ps + b"\x00" + data
    m = int.from_bytes(em, "big")
    return pow(m, RSA_E, _N_INT).to_bytes(_RSA_BLOCK, "big")


def sign_token(params: dict) -> str:
    """SHA512hex -> [1::2] -> [0::2] -> MD5 大写"""
    s = fastjson(params)
    h = hashlib.sha512(s.encode("utf-8")).hexdigest()
    mid = h[1::2][0::2]
    return hashlib.md5(mid.encode("utf-8")).hexdigest().upper()


def make_d(params: dict) -> str:
    """timestamp + signToken -> 整包 AES/RSA 加密 -> d 值"""
    allp = dict(params)
    allp["timestamp"] = str(int(time.time() * 1000))
    allp["signToken"] = sign_token(allp)          # 签名不含 signToken 自身
    plain = fastjson(allp).encode("utf-8")

    skey = rand_session_key()
    seg0 = aes_cbc_pkcs5(_pkcs7(plain), skey.encode("utf-8"), AES_IV_RE)
    seg1 = rsa_pkcs1_v1_5(skey.encode("utf-8"))

    b0 = base64.b64encode(seg0).decode("ascii")
    b1 = base64.b64encode(seg1).decode("ascii")
    inner = b0.rstrip("=") + "==" + b1
    return base64.b64encode(inner.encode("ascii")).decode("ascii")


def standard_ua() -> str:
    ts = int(100 * time.time())
    dev = {
        "channelName": "dmkj_Android",
        "countryCode": "CN",
        "createTime": ts,
        "device": "Xiaomi Redmi Note 5",
        "hardware": "qcom",
        "modifyTime": ts,
        "operator": "%E6%9C%AA%E7%9F%A5",
        "screenResolution": "1080-2116",
        "startTime": ts + 19606523,
        "sysVersion": "Android 29 10",
        "system": "android",
        "uuid": "7d0cf0129b38459089f12d963dd9a769",
        "version": APP_VERSION,
    }
    # 注意：无真实极光推送注册时 header 绝不能带 jPushId 键（空值会被风控判 -2000）
    return json.dumps(dev, separators=(",", ":"))


# ---------------- API 客户端 ----------------
class Api:
    """v2 API 客户端：params 值全部字符串；token 等由调用方传入"""

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.school_id = ""  # 登录后由 login() 自动填充
        self.headers = {
            "standardUA": standard_ua(),
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "okhttp/3.11.0",
            "Connection": "Keep-Alive",
        }

    def _post(self, path: str, params: dict) -> dict:
        d = make_d(params)
        body = "d=" + urllib.parse.quote(d, safe="")
        req = urllib.request.Request(API_HOST + path, data=body.encode("utf-8"), method="POST")
        for k, v in self.headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8-sig", "ignore"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8-sig", "ignore")
            try:
                return json.loads(raw)   # 部分错误以 HTTP 4xx + JSON 返回
            except Exception:
                raise

    # ---- 登录（无 token/uid） ----
    def login(self, account: str, pwd: str) -> dict:
        res = self._post("/v2/login/phone", {
            "account": account,
            "pwd": pwd_encrypt(pwd),
            "version": APP_VERSION,
        })
        if str(res.get("code", "")) == "100":
            d = res.get("data") or {}
            self.school_id = str(d.get("schoolId", ""))
        return res

    # ---- 活动列表（join_flag="1" 可报名中） ----
    def activities(self, token: str, uid: str, page: int = 1, keyword: str = "",
                   join_flag: str = "", status: str = "", jpush: str = "") -> dict:
        p = {
            "catalogId": "", "catalogId2": "", "endTime": "",
            "joinEndTime": "", "joinFlag": join_flag, "joinStartTime": "",
            "keyword": keyword, "level": "", "page": str(page),
            "sort": "", "specialFlag": "", "startTime": "", "status": status,
        }
        return self._post("/v2/activity/activities", self._base(token, uid, jpush, p))

    # ---- 活动详情（需 schoolId） ----
    def activity_detail(self, token: str, uid: str, aid: str, jpush: str = "") -> dict:
        p = {"activityId": aid}
        if self.school_id:
            p["schoolId"] = self.school_id
        return self._post("/v2/activity/detail", self._base(token, uid, jpush, p))

    # ---- 我的活动 ----
    def my_activities(self, token: str, uid: str, page: int = 1, jpush: str = "") -> dict:
        p = {"keyword": "", "page": str(page), "type": "1"}
        if self.school_id:
            p["schoolId"] = self.school_id
        return self._post("/v2/activity/mime/list", self._base(token, uid, jpush, p))

    # ---- 报名提交 ----
    def signup_submit(self, token: str, uid: str, aid: str, remark: str = "",
                      jpush: str = "") -> dict:
        p = {"activityId": aid, "data": "[]", "remark": remark}
        return self._post("/v2/signup/submit", self._base(token, uid, jpush, p))

    # ---- 取消报名 ----
    def signup_cancel(self, token: str, uid: str, signup_id: str, jpush: str = "") -> dict:
        return self._post("/v2/signup/cancel",
                          self._base(token, uid, jpush, {"signUpId": signup_id}))

    @staticmethod
    def _base(token: str, uid: str, jpush: str, biz: dict) -> dict:
        p = {"token": token, "uid": uid, "version": APP_VERSION}
        if jpush:
            p["jPushId"] = jpush
        p.update(biz)
        return p
