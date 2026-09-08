# 到梦空间 · 自动报名工作台

本地"客户端式"工作台：低频轮询 → 挑选「线上」报名中活动 → 自动报名 → QQ 邮箱 + Windows 气泡通知。
基于到梦空间 APP v4.9.5 官方接口协议实现，**已用真实账号在真实服务器全链路验证**。

```
运行形态        入口                                           说明
桌面模式(推荐)   双击 start_desktop.bat                        独立 App 窗口（无地址栏），关闭窗口引擎继续后台跑
工作台网页版     双击 start_dashboard.bat 或访问 127.0.0.1:8921 浏览器操作
独立 exe         dist\DreamDMK\DreamDMK.exe                   免 Python；加 --app 参数为桌面模式
无头 CLI         venv\Scripts\python main.py                   服务器/无界面场景
```
> 端口已被占用时重复启动会自动进入"附加模式"：不重复启动引擎，只打开窗口/页面。
> 开机自启 = 登录后自动以桌面模式（--app）拉起（注册表 HKCU Run: DreamDMKWorkbench）。

## 快速开始（源码运行）

1. 安装依赖：`venv\Scripts\python -m pip install -r requirements.txt`（若无 venv 先 `python -m venv venv`）
2. 编辑 `config.yaml`：账号、规则关键词、QQ 邮箱授权码
3. 双击 **start_dashboard.bat** —— 自动打开工作台，引擎随即常驻运行
4. 需要常驻免开窗：工作台「设置」页勾选 *登录 Windows 后自动启动工作台*（写注册表自启）

## 工作台功能（四个页签）

| 页签 | 功能 |
|---|---|
| 总览 | 引擎启停/立即扫描、下一轮倒计时、统计、7 日报名趋势、实时事件流（SSE） |
| 运行记录 | 全部事件时间线：轮次/命中/报名/邮件/异常，按结果着色 |
| 活动档案 | 每个活动最终状态：成功/已报名过/不可报/重试中/观察中，附服务端返回码 |
| 设置 | 图形化编辑：轮询频率/自动开关/关键词规则/账号/QQ邮箱/自启/试运行，保存即热更新 |

另有：深色/浅色主题切换（右上 ◐）、Windows 气泡通知（报名成功/失败即时弹出）、托盘图标（双击回到页面）。

## 规则说明（挑选"线上"活动）

- 只处理 `status=3`（报名中）的新条目
- 标题含 `rules.name_include` 任一关键词 → 命中（默认 `["线上"]`）
- 标题不含时查一次活动详情，含 `rules.detail_kw`（默认 线上/online，匹配活动名/地点/标签）→ 命中
- `rules.name_exclude` 黑名单优先级最高
- 命中 → 随机延迟 2~6 秒 → 提交报名 → QQ 邮件 + 气泡通知
- 结果去重落 sqlite：成功/终态（不在报名期、跨院系、已报名过）不重复尝试

## 打包独立 exe

```
venv\Scripts\python build_exe.py
```
产出 `dist\DreamDMK\DreamDMK.exe`（含 web 前端资源；config.yaml/token.json 自动复制到同目录）。
整个 `dist\DreamDMK` 文件夹可拷到任意位置使用。注意：exe 可能被杀毒软件误报（自动操作类程序通病），需加白名单。

## Release：下载与发布

**给使用者（怎么拿到成品）：**
- 到 GitHub Releases 页面下载 `dreamdmk-desktop-win-x64.zip`（桌面应用，推荐）或 `dreamdmk-backend-exe.zip`（轻量绿色版）
- 解压后双击 `DreamDMK.exe`（桌面版）或 `dist 内 DreamDMK.exe`（绿色版）即可运行
- 首次使用：按同目录/解压根部的说明填写 `config.yaml`（到梦账号 + QQ 邮箱 SMTP 授权码），填完重启应用生效
- 更新：桌面应用启动后自动检查最新 Release，发现新版可一键「下载并更新」，重启即完成替换（**config/token/报名记录全部保留**）

**给维护者（怎么发布新版本）：**
1. 修改 `app_shell/package.json` 的 `version`（如 `1.3.1`）
2. `venv\Scripts\python build_exe.py` 重建后端
3. `venv\Scripts\python assemble_app.py` 重组桌面应用
4. `venv\Scripts\python make_release.py` 自动产出**净身发布包**（剔除真实凭据/登录态/记录，config.yaml 换占位模板）到 `dist\release\`
5. 在 GitHub Releases 新建 Release：tag 用 `v1.3.1`，上传 `dist\release\` 下的 zip

**约定与提醒：**
- **资产命名**：桌面版必须为 `dreamdmk-desktop` 开头的 `.zip`（应用内更新器按名字识别，勿改名）
- tag 与本地 `package.json` 版本一致时更新检查静默跳过；更高版本才会提示
- 发布包已自动净身；本地使用的 `config.yaml`（含真实密码/授权码）永远不要上传到仓库或压缩包

## 工程结构

```
5idream-auto/
├── dashboard.py  工作台服务（HTTP+SSE，纯标准库，127.0.0.1 回环）
├── engine.py     引擎层（线程化常驻/事件流/状态快照/热更新配置）
├── dmkj.py       协议层（RSA+AES 加密链 + 签名，勿改动）
├── mailer.py     QQ 邮箱 SMTP 通知
├── notify.py     Windows 托盘气泡（ctypes 零依赖）
├── main.py       无头 CLI（引擎同源）
├── build_exe.py  PyInstaller 打包脚本
├── assemble_app.py  Electron 桌面应用组装
├── make_release.py  净身发布包生成（自动化）
├── web/          工作台前端（深色主题，无构建依赖）
├── config.yaml   全部配置（含明文密码，勿外传）
├── logs/         运行日志 dashboard.log / bot.log
├── token.json    登录态缓存（自动生成，勿外传）
└── state.sqlite  去重与事件库（自动生成）
```

## 服务端常见返回码

| code | 含义 | 机器人处置 |
|---|---|---|
| 100 | 成功 | ✅ 通知 |
| 2000011 | 已报名过 | ✅ 记为成功不重复 |
| 2000166 | 不在报名时间段 | 终态归档 |
| 2000004 | 非本学院学生 | 终态归档 |
| 2000000 | 活动不存在 | 终态归档 |
| 11001/11002/-2000 | 签名/参数/风控（协议层） | 按轮重试至上限 |

> 陷阱备忘：请求头 standardUA 若带空 `jPushId` 键会被风控统一拒绝 -2000；无真实
> 极光推送注册时该键必须整体省略（dmkj.py 已处理）。详情接口需带 `schoolId`。

## 风险与提醒

- 使用你自己的账号按官方接口协议操作，但自动化行为可能违反平台章程/学校二课堂
  规则，账号风险自负；请保持低频默认（15 分钟 ±5 抖动），UI 设置页亦可调。
- 仅监听 127.0.0.1，前端不回显密码（设置页留空=不修改）。
- 平台协议改版时按 `recon/` 中记录的逆向过程与常量来源排查更新。
