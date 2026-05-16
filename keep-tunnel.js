#!/usr/bin/env node
// keep-tunnel.js — Auto-restarting localtunnel that notifies the Render app of URL changes
const { spawn } = require('child_process');
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');

const PORT = 11435;
const LOG_FILE = path.join(__dirname, 'tunnel_url.txt');
const RENDER_APP_URL = process.env.RENDER_APP_URL || 'https://project-manager-vqcr.onrender.com';

function checkQvac() {
  return new Promise((resolve) => {
    const req = http.request(`http://localhost:${PORT}/v1/models`, { method: 'GET', timeout: 2000 }, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.end();
  });
}

function notifyRender(apiUrl) {
  return new Promise((resolve) => {
    const url = new URL('/api/ai/configure', RENDER_APP_URL);
    const data = JSON.stringify({ api_base: apiUrl });
    const mod = url.protocol === 'https:' ? https : http;
    const req = mod.request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
      timeout: 10000,
    }, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        if (res.statusCode === 200) {
          console.log('[keep-tunnel] Render notified successfully:', body.trim());
          resolve(true);
        } else {
          console.log('[keep-tunnel] Render responded with', res.statusCode);
          resolve(false);
        }
      });
    });
    req.on('error', (e) => { console.error('[keep-tunnel] Failed to notify Render:', e.message); resolve(false); });
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.write(data);
    req.end();
  });
}

async function startTunnel() {
  while (true) {
    const qvacUp = await checkQvac();
    if (!qvacUp) {
      console.log('[keep-tunnel] QVAC not running on port', PORT, '- waiting...');
      await new Promise(r => setTimeout(r, 5000));
      continue;
    }

    console.log('[keep-tunnel] QVAC is up, starting tunnel...');
    const lt = spawn('lt', ['--port', String(PORT)], { stdio: ['ignore', 'pipe', 'pipe'] });

    let url = '';
    lt.stdout.on('data', async (data) => {
      const match = data.toString().match(/https:\/\/[a-z0-9-]+\.loca\.lt/);
      if (match) {
        url = match[0];
        const apiUrl = url + '/v1';
        console.log('[keep-tunnel] Tunnel URL:', url);
        console.log('[keep-tunnel] Set AI_API_BASE to:', apiUrl);
        fs.writeFileSync(LOG_FILE, apiUrl);

        // Immediately notify the Render app
        console.log('[keep-tunnel] Notifying Render app...');
        const ok = await notifyRender(apiUrl);
        if (ok) {
          console.log('[keep-tunnel] Render is now using the new tunnel URL. AI should work!');
        }
      }
    });

    lt.stderr.on('data', (data) => {
      console.error('[keep-tunnel] stderr:', data.toString().trim());
    });

    await new Promise((resolve) => {
      lt.on('close', (code) => {
        console.log('[keep-tunnel] Tunnel died (exit', code, '), restarting in 3s...');
        url = '';
        fs.writeFileSync(LOG_FILE, '');
        setTimeout(resolve, 3000);
      });
      lt.on('error', (err) => {
        console.error('[keep-tunnel] Error:', err.message);
        setTimeout(resolve, 3000);
      });
    });
  }
}

startTunnel();
