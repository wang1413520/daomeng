'use strict';
/* 到梦空间 · 自动报名工作台 —— Electron 桌面外壳（带启动日志版） */
const { app, BrowserWindow, shell, dialog } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const updater = require('./updater.js');

const REPO = 'wang1413520/daomeng';
const ASSET_PREFIX = 'dreamdmk-desktop';
let localVersion = '0.0.0';
try { localVersion = require('./package.json').version || '0.0.0'; } catch (e) { /* ignore */ }

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

// ---------- 更新检查（打包版生效；Release 资产名须为 dreamdmk-desktop*.zip） ----------
async function doUpdateCheck(manual) {
  try {
    const rel = await updater.latestRelease(REPO);
    if (!rel || !rel.tag_name) { if (manual) dialog.showMessageBox(win, { message: '当前已是最新版本 v' + localVersion, type: 'info' }); return; }
    if (!updater.isNewer(localVersion, rel.tag_name)) { if (manual) dialog.showMessageBox(win, { message: '当前已是最新版本 v' + localVersion, type: 'info' }); return; }
    const asset = updater.findAsset(rel, ASSET_PREFIX);
    if (!asset) { if (manual) dialog.showMessageBox(win, { message: '发现新版 ' + rel.tag_name + '，但未找到配套安装包资产。', type: 'warning' }); return; }
    const opt = await dialog.showMessageBox(win, {
      type: 'info',
      message: '发现新版本 ' + rel.tag_name,
      detail: '当前 v' + localVersion + ' → ' + rel.tag_name +
        '\n更新包：' + asset.name + '（' + Math.round(asset.size / 1048576) + ' MB）\n下载后需重启应用完成替换。',
      buttons: ['下载并更新', '暂不'],
      defaultId: 0, cancelId: 1,
    });
    if (opt.response !== 0) return;
    const exeDir = path.dirname(process.execPath);
    const upDir = path.join(exeDir, '.update');
    fs.mkdirSync(upDir, { recursive: true });
    const zipPath = path.join(upDir, 'new.zip');
    const newDir = path.join(upDir, 'new');
    await updater.downloadFile(asset.browser_download_url, zipPath);
    await new Promise((resolve, reject) => {
      const ps = spawn('powershell', ['-NoProfile', '-Command',
        'Expand-Archive -LiteralPath "' + zipPath + '" -DestinationPath "' + newDir + '" -Force']);
      ps.on('close', (c) => (c === 0 ? resolve() : reject(new Error('解压失败 code ' + c))));
      ps.on('error', reject);
    });
    fs.writeFileSync(path.join(upDir, 'pending.json'),
      JSON.stringify({ tag: rel.tag_name, zip: zipPath, newDir: newDir }), 'utf8');
    const go = await dialog.showMessageBox(win, {
      type: 'question',
      message: '更新包已就绪（' + rel.tag_name + '）',
      detail: '应用将退出并在数秒后自动完成替换并重新打开。请稍候，期间不要手动启动。',
      buttons: ['立即重启更新', '稍后再说'],
      defaultId: 0, cancelId: 1,
    });
    if (go.response !== 0) return;
    spawn('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', updaterPs(),
      '-AppDir', '"' + exeDir + '"', '-NewDir', '"' + newDir + '"', '-ZipPath', '"' + zipPath + '"',
      '-ExePath', '"' + process.execPath + '"', '-Pid', String(process.pid)], {
      detached: true, stdio: 'ignore', windowsHide: true,
    }).unref();
    app.quit();
  } catch (e) {
    if (manual) dialog.showMessageBox(win, { message: '检查更新失败：' + e.message, type: 'error' });
    lg('update check failed: ' + e.message);
  }
}

function ensureShortcut() {
  // 首次启动询问是否创建桌面快捷方式（便携应用默认不创建）
  try {
    const marker = path.join(app.getPath('userData'), 'firstrun.flag');
    if (fs.existsSync(marker)) return;
    fs.writeFileSync(marker, '1');
    const ico = path.join(APP_DIR, 'icon.ico');
    const ps = '$ws = New-Object -ComObject WScript.Shell; ' +
      '$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "到梦空间工作台.lnk"; ' +
      '$sc = $ws.CreateShortcut($lnk); ' +
      '$sc.TargetPath = "' + process.execPath + '"; ' +
      '$sc.WorkingDirectory = "' + path.dirname(process.execPath) + '"; ' +
      '$sc.IconLocation = "' + ico + '"; ' +
      '$sc.Description = "到梦空间 · 自动报名工作台"; $sc.Save()';
    dialog.showMessageBox(win, {
      type: 'question',
      message: '首次启动',
      detail: '是否在桌面创建快捷方式（到梦空间工作台）？\n以后也可以手动：右键 DreamDMK.exe → 发送到 → 桌面快捷方式。',
      buttons: ['创建桌面快捷方式', '不用了'],
      defaultId: 0, cancelId: 1,
    }).then((r) => {
      if (r.response !== 0) return;
      spawn('powershell', ['-NoProfile', '-Command', ps], { windowsHide: true }).on('error', () => {});
    });
  } catch (e) { lg('shortcut ask failed: ' + e.message); }
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
    setTimeout(() => { if (win && !win.isDestroyed()) ensureShortcut(); }, 2500);
    app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
    if (app.isPackaged) {
      setTimeout(() => doUpdateCheck(false), 8000);   // 启动 8 秒后静默检查更新
      lg('auto update check armed (v' + localVersion + ')');
    }
  });
  app.on('window-all-closed', () => { lg('all closed -> quit'); app.quit(); });
  app.on('before-quit', () => {
    lg('before-quit, killing backend');
    if (backend) { try { backend.kill(); } catch (e) { /* ignore */ } backend = null; }
  });
  process.on('uncaughtException', (e) => { lg('uncaught: ' + (e && e.stack || e)); });
  process.on('unhandledRejection', (e) => { lg('unhandled: ' + (e && e.stack || e)); });
}
