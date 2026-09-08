'use strict';
/* 更新检查核心（纯 Node，可独立单测；Electron 侧只做壳）
 * 逻辑：GitHub Releases latest → 解析 tag 与资产 → 下载到本地
 */
const https = require('https');
const fs = require('fs');
const path = require('path');

const UA = 'DreamDMK-Updater/1.0';

function getRedirected(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { 'User-Agent': UA }, timeout: timeoutMs || 20000 }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        resolve(getRedirected(res.headers.location, timeoutMs));
        return;
      }
      if (res.statusCode !== 200) {
        res.resume();
        reject(new Error('HTTP ' + res.statusCode + ' @ ' + url));
        return;
      }
      resolve(res);
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(new Error('timeout')); });
  });
}

async function getJson(url) {
  const res = await getRedirected(url);
  let buf = '';
  return await new Promise((resolve, reject) => {
    res.setEncoding('utf8');
    res.on('data', (c) => (buf += c));
    res.on('end', () => {
      try { resolve(JSON.parse(buf)); } catch (e) { reject(e); }
    });
    res.on('error', reject);
  });
}

async function latestRelease(repo) {
  try {
    return await getJson('https://api.github.com/repos/' + repo + '/releases/latest');
  } catch (e) {
    return null; // 404=无 Release，网络错=静默
  }
}

function parseVersion(tag) {
  const s = String(tag || '').replace(/^v/, '').trim();
  const parts = s.split(/[.\-]/).map((x) => parseInt(x, 10));
  while (parts.length < 3) parts.push(0);
  return { raw: s, parts: parts.slice(0, 3) };
}

function isNewer(localTag, remoteTag) {
  const a = parseVersion(localTag).parts;
  const b = parseVersion(remoteTag).parts;
  return a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]) || (a[0] === b[0] && a[1] === b[1] && a[2] < b[2]);
}

function findAsset(release, namePrefix) {
  const assets = (release && release.assets) || [];
  return assets.find((a) => a.name.startsWith(namePrefix) && a.name.endsWith('.zip')) || null;
}

function downloadFile(url, dest, onProgress) {
  return new Promise((resolve, reject) => {
    getRedirected(url).then((res) => {
      const total = parseInt(res.headers['content-length'] || '0', 10);
      let got = 0;
      const out = fs.createWriteStream(dest);
      res.on('data', (chunk) => {
        got += chunk.length;
        if (onProgress && total) onProgress(got, total);
      });
      res.pipe(out);
      out.on('finish', () => { out.close(); resolve(dest); });
      out.on('error', reject);
      res.on('error', reject);
    }).catch(reject);
  });
}

module.exports = { latestRelease, parseVersion, isNewer, findAsset, downloadFile, getJson };
