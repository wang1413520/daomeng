# -*- coding: utf-8 -*-
"""Windows 托盘图标 + 气泡通知（ctypes 纯标准库，零第三方依赖）

- 常驻独立线程创建隐藏窗口与托盘图标
- show(title, text)：弹出系统气泡
- 双击托盘图标可打开工作台页面
"""
import ctypes
import logging
import threading
import webbrowser
from ctypes import wintypes

log = logging.getLogger("bot.notify")

try:
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    _WIN_OK = True
except Exception:
    _WIN_OK = False

if _WIN_OK:
    NIM_ADD = 0x00000000
    NIM_MODIFY = 0x00000001
    NIM_DELETE = 0x00000002
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NIF_INFO = 0x00000010
    WM_USER = 0x0400
    NIN_BALLOONUSERCLICK = WM_USER + 5
    WM_LBUTTONDBLCLK = 0x0203
    IDI_APPLICATION = 32512

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]


class _Balloon:
    def __init__(self, url):
        self.url = url
        self._h = None
        self._nid = None

    def start(self):
        if not _WIN_OK:
            return
        threading.Thread(target=self._run, name="balloon", daemon=True).start()

    def _proc(self, hwnd, msg, wp, lp):
        try:
            cb = getattr(self, "_cb_msg", None)
            if cb is not None and msg == cb:
                if lp in (NIN_BALLOONUSERCLICK, WM_LBUTTONDBLCLK):
                    webbrowser.open(self.url)
        except Exception:
            pass
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _run(self):
        try:
            self._cb = WNDPROC(self._proc)  # 持有引用防 GC
            self._cb_msg = WM_USER + 1
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._cb
            wc.hInstance = kernel32.GetModuleHandleW(None)
            wc.lpszClassName = "DreamDMKNotify"
            user32.RegisterClassExW(ctypes.byref(wc))

            hwnd = user32.CreateWindowExW(0, "DreamDMKNotify", "dmk", 0, 0, 0, 0, 0,
                                          None, None, wc.hInstance, None)
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = self._cb_msg
            nid.hIcon = user32.LoadIconW(None, IDI_APPLICATION)
            nid.szTip = "到梦空间 · 自动报名工作台"
            ok = shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
            if not ok:
                log.warning("托盘图标创建失败")
                return
            self._h, self._nid = hwnd, nid
            log.info("托盘通知线程已就绪")
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            log.warning("托盘通知不可用: %s", e)

    def show(self, title, text):
        if not (_WIN_OK and self._nid is not None):
            return False
        try:
            self._nid.uFlags = NIF_INFO
            self._nid.szInfoTitle = (title or "")[:63]
            self._nid.szInfo = (text or "")[:255]
            self._nid.dwInfoFlags = 0x00000004  # NIIF_USER 风格(纯文本)
            return bool(shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid)))
        except Exception as e:
            log.warning("气泡通知失败: %s", e)
            return False


_inst = None
_lock = threading.Lock()


def balloon(url="http://127.0.0.1:8921"):
    """获取全局单例并确保线程已启动"""
    global _inst
    with _lock:
        if _inst is None:
            _inst = _Balloon(url)
            _inst.start()
        return _inst
