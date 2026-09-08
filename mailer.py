# -*- coding: utf-8 -*-
"""QQ 邮箱（SMTP SSL）通知模块"""
import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText

log = logging.getLogger("bot.mail")


class Mailer:
    def __init__(self, cfg: dict):
        self.enabled = bool(cfg.get("enabled", False))
        self.host = cfg.get("host", "smtp.qq.com")
        self.port = int(cfg.get("port", 465))
        self.from_addr = cfg.get("from_addr", "").strip()
        self.auth_code = cfg.get("auth_code", "").strip()
        raw_to = cfg.get("to_addr", "").strip()
        self.to_addrs = [x.strip() for x in raw_to.split(",") if x.strip()]
        self._ready = self.enabled and self.from_addr and self.auth_code and self.to_addrs
        if self.enabled and not self._ready:
            log.warning("邮件配置不完整（from/auth_code/to 需全部填写并开启QQ邮箱SMTP），通知功能暂不可用")

    def send(self, subject: str, body: str) -> bool:
        if not self._ready:
            log.info("[通知] 邮件未配置，跳过。内容=%s", body.replace("\n", " | "))
            return False
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = self.from_addr
            msg["To"] = ",".join(self.to_addrs)
            with smtplib.SMTP_SSL(self.host, self.port, timeout=30) as s:
                s.login(self.from_addr, self.auth_code)
                s.sendmail(self.from_addr, self.to_addrs, msg.as_string())
            log.info("[通知] 邮件已发送 -> %s : %s", self.to_addrs, subject)
            return True
        except Exception as e:
            log.error("[通知] 邮件发送失败: %s", e)
            return False
