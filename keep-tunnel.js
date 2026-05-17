#!/usr/bin/env node
// keep-tunnel.js — Cloudflare tunnel auto-starter that notifies Render of URL changes
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
    const req = http.request('http://localhost:' + PORT + '/v1/models', { method: 'GET', timeout: 2000 }, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.end();
  });
}

function notifyRender(apiUrl) {
  return new Promise((resolve) => {
    var urlObj;
    try { urlObj = new URL('/api/ai/configure', RENDER_APP_URL); } catch(e) { resolve(false); return; }
    var data = JSON.stringify({ api_base: apiUrl });
    var mod = urlObj.protocol === 'https:' ? https : http;
    var req = mod.request(urlObj, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
      timeout: 10000,
    }, function(res) {
      var body = '';
      res.on('data', function(chunk) { body += chunk; });
      res.on('end', function() {
        if (res.statusCode === 200) {
          console.log('[keep-tunnel] Render notified successfully:', body.trim());
          resolve(true);
        } else {
          console.log('[keep-tunnel] Render responded with', res.statusCode);
          resolve(false);
        }
      });
    });
    req.on('error', function(e) { console.error('[keep-tunnel] Failed to notify Render:', e.message); resolve(false); });
    req.on('timeout', function() { req.destroy(); resolve(false); });
    req.write(data);
    req.end();
  });
}

async function startTunnel() {
  while (true) {
    var qvacUp = await checkQvac();
    if (!qvacUp) {
      console.log('[keep-tunnel] QVAC not running on port', PORT, '- waiting...');
      await new Promise(function(r) { setTimeout(r, 5000); });
      continue;
    }

    console.log('[keep-tunnel] QVAC is up, starting Cloudflare tunnel...');
    var cf = spawn('cloudflared', ['tunnel', '--url', 'http://localhost:' + PORT], { stdio: ['ignore', 'pipe', 'pipe'] });

    var url = '';
    cf.stderr.on('data', function(data) {
      var str = data.toString();
      var match = str.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/);
      if (match) {
        url = match[0];
        var apiUrl = url + '/v1';
        console.log('[keep-tunnel] Tunnel URL:', url);
        console.log('[keep-tunnel] Set AI_API_BASE to:', apiUrl);
        fs.writeFileSync(LOG_FILE, apiUrl);
        notifyRender(apiUrl);
      }
    });

    await new Promise(function(resolve) {
      cf.on('close', function(code) {
        console.log('[keep-tunnel] Tunnel died (exit', code, '), restarting in 3s...');
        url = '';
        fs.writeFileSync(LOG_FILE, '');
        setTimeout(resolve, 3000);
      });
      cf.on('error', function(err) {
        console.error('[keep-tunnel] Error:', err.message);
        setTimeout(resolve, 3000);
      });
    });
  }
}

startTunnel();
