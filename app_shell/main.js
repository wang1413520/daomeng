'use strict';
/* 到梦空间 · 自动报名工作台 —— Electron 桌面外壳（带启动日志版） */
const { app, BrowserWindow, shell, dialog } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const PORT = parseInt(process.env.DMK_PORT || '8921', 10);
const URL = 'http://127.0.0.1:' + PORT;
const APP_DIR = __dirname;
const ICON = path.join(APP_DIR, 'icon.ico');
const LOGF = path.join(APP_DIR, '..', '..', 'electron-app.log');   // exe 同层

let win = null;
let backend = null;

function lg(msg) {
  try { fs.appendFileSync(LOGF, new Date().toISOString() + ' ' + msg + '\n'); } catch (e) { /* ignore */ }
}

function backendCandidates() {
  const cands = [];
  const bundled = path.join(APP_DIR, 'backend', 'DreamDMK.exe');
  if (fs.existsSync(bundled)) cands.push({ cmd: bundled, args: ['--no-open', '--port', String(PORT)] });
  for (const up of [1, 2, 3, 4]) {
    const root = path.resolve(APP_DIR, ...Array(up).fill('..'));
    const pyw = path.join(root, 'venv', 'Scripts', 'pythonw.exe');
    const dash = path.join(root, 'dashboard.py');
    if (fs.existsSync(pyw) && fs.existsSync(dash)) {
      cands.push({ cmd: pyw, args: [dash, '--no-open', '--port', String(PORT)] });
      break;
    }
  }
  return cands;
}

function httpGet(timeout) {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port: PORT, path: '/api/state', timeout }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

async function waitReady(ms) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (await httpGet(1500)) return true;
    await new Promise((r) => setTimeout(r, 600));
  }
  return false;
}

async function ensureBackend() {
  if (await waitReady(1200)) { lg('backend: 已有实例在跑'); return 'running'; }
  const cands = backendCandidates();
  lg('backend: 候选 ' + JSON.stringify(cands));
  if (!cands.length) return 'missing';
  const c = cands[0];
  backend = spawn(c.cmd, c.args, { windowsHide: true, stdio: 'ignore' });
  backend.on('error', (e) => lg('backend spawn error: ' + e.message));
  backend.on('exit', (code) => { lg('backend exited: ' + code); backend = null; });
  lg('backend spawned pid=' + (backend.pid || '?'));
  const ok = await waitReady(20000);
  lg('backend ready: ' + ok);
  return ok ? 'started' : 'failed';
}

function createWindow() {
  lg('createWindow');
  win = new BrowserWindow({
    width: 1420, height: 920, minWidth: 1080, minHeight: 700,
    title: '到梦空间 · 自动报名工作台',
    icon: fs.existsSync(ICON) ? ICON : undefined,
    backgroundColor: '#0a0d12',
    autoHideMenuBar: true,
    show: false,
  });
  win.loadURL(URL).catch((e) => lg('loadURL error: ' + e));
  win.once('ready-to-show', () => { lg('ready-to-show'); win.show(); });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.on('closed', () => { lg('window closed'); win = null; });
}

lg('=== boot ===');
try {
  // 用户数据目录放在应用旁（避免 %APPDATA% 权限问题/沙箱拒绝）
  app.setPath('userData', path.join(path.dirname(process.execPath), '.data'));
} catch (e) { lg('setPath userData err: ' + e); }
if (process.env.DMK_NO_SANDBOX === '1') {
  app.commandLine.appendSwitch('no-sandbox');
  app.disableHardwareAcceleration();
}
if (!app.requestSingleInstanceLock()) {
  lg('another instance, quit');
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
  });
  app.whenReady().then(async () => {
    lg('ready');
    app.setAppUserModelId('com.dreamdmk.workbench');
    const st = await ensureBackend();
    if (st === 'missing' || st === 'failed') {
      lg('startup fail: ' + st);
      dialog.showErrorBox('启动失败', st === 'missing' ? '后端缺失' : '后端未就绪，请查看 logs/dashboard.log');
      app.quit();
      return;
    }
    createWindow();
    app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
  });
  app.on('window-all-closed', () => { lg('all closed -> quit'); app.quit(); });
  app.on('before-quit', () => {
    lg('before-quit, killing backend');
    if (backend) { try { backend.kill(); } catch (e) { /* ignore */ } backend = null; }
  });
  process.on('uncaughtException', (e) => { lg('uncaught: ' + (e && e.stack || e)); });
  process.on('unhandledRejection', (e) => { lg('unhandled: ' + (e && e.stack || e)); });
}
