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
        self.last_error = None
        if self.enabled and not self._ready:
            log.warning("邮件配置不完整（from/auth_code/to 需全部填写并开启QQ邮箱SMTP），通知功能暂不可用")

    def send(self, subject: str, body: str) -> bool:
        self.last_error = None
        if not self._ready:
            missing = [k for k, v in (("from_addr", self.from_addr), ("auth_code", self.auth_code),
                                      ("to_addr", ",".join(self.to_addrs))) if not v]
            self.last_error = "配置不完整，缺少: %s（检查设置页邮箱项）" % ", ".join(missing)
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
        except smtplib.SMTPAuthenticationError as e:
            self.last_error = "SMTP 认证失败(code %s)：授权码错误或未开启 SMTP 服务" % e.smtp_code
            log.error("[通知] 邮件发送失败: %s", e)
            return False
        except smtplib.SMTPRecipientsRefused as e:
            self.last_error = "收件地址被拒绝：%s（检查 to_addr 格式）" % (list(e.recipients)[:1])
            log.error("[通知] 邮件发送失败: %s", e)
            return False
        except smtplib.SMTPSenderRefused as e:
            self.last_error = "发件地址被拒绝(code %s)：from_addr 必须与授权码所属 QQ 一致" % e.smtp_code
            log.error("[通知] 邮件发送失败: %s", e)
            return False
        except smtplib.SMTPServerDisconnected:
            self.last_error = ("SMTP 服务器断开了连接：多为授权码错误或未开启 SMTP 服务，"
                               "请确认 auth_code 是 16 位授权码且与 from_addr 为同一个 QQ")
            log.error("[通知] 邮件发送失败: 服务器断开连接")
            return False
        except (TimeoutError, OSError) as e:
            self.last_error = "网络/连接错误：%s（检查网络或稍后重试）" % str(e)[:120]
            log.error("[通知] 邮件发送失败: %s", e)
            return False
        except Exception as e:
            self.last_error = "发送异常：%s" % str(e)[:200]
            log.error("[通知] 邮件发送失败: %s", e)
            return False
