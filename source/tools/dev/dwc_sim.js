#!/usr/bin/env node
// tools/dev/dwc_sim.js -- a real DuetWebControl 3.6 in the browser against a pretend DSF, for the service page (environment E2, proof of concept).
//
//   node tools/dev/dwc_sim.js --api http://127.0.0.1:8765 [--port 8766] [--dwc dist/sim/dwc] [--lang es|en] [--dark]
//
// It serves the compiled DWC (the dist/ folder a build of the page leaves in the DWC clone, copied to dist/sim/dwc by tools/dev/sim_build.py: the page is
// a chunk of that same build, so DWC loads it as one of its built-in plugins) and speaks the part of the SBC protocol DWC needs
// (@duet3d/connectors RestConnector): /machine/connect, the WebSocket /machine (the whole object model, then one patch per "OK"), the files of the SD
// card under /machine/file and /machine/directory, /machine/code (recorded, never sent anywhere). The API of the service
// (/machine/WorkshopService/api) and the control surface (/__dev/...) are passed on to tools/dev/api_server.py, which also owns the object model
// (GET /__dev/model: a change there reaches the browser as a patch) and the SD folder.
// Local only: it listens on 127.0.0.1 and only ever calls the API server on 127.0.0.1.
// Needs the DWC 3.6 clone with node_modules for the `ws` package ($TALLER_DWC_SRC_36 or ~/Projects/dwc-src), read only.
"use strict";
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { createRequire } = require("module");

const arg = (name, fallback) => { const i = process.argv.indexOf("--" + name); return i < 0 ? fallback : process.argv[i + 1]; };
const flag = (name) => process.argv.includes("--" + name);
const ROOT = path.join(__dirname, "..", "..");
const API = new URL(arg("api", "http://127.0.0.1:8765"));
const PORT = Number(arg("port", "8766"));
const DWC_DIST = path.resolve(ROOT, arg("dwc", "dist/sim/dwc"));
const LANG = arg("lang", "es");
const DARK = flag("dark");
const CLONE = process.env.TALLER_DWC_SRC_36 || path.join(os.homedir(), "Projects", "dwc-src");
const PLUGIN = "WorkshopService";
const POLL_MS = 400;

if (API.hostname !== "127.0.0.1" && API.hostname !== "localhost") { console.error("dwc_sim: the API server must be on this computer (got " + API.hostname + ")"); process.exit(2); }
if (!fs.existsSync(path.join(DWC_DIST, "index.html"))) { console.error("dwc_sim: no compiled DWC in " + DWC_DIST + " (run python tools/dev/sim_build.py)"); process.exit(2); }
const wsPackage = createRequire(path.join(CLONE, "package.json"))("ws");
const WebSocketServer = wsPackage.WebSocketServer || wsPackage.Server;   // the name depends on the version DWC brings

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
  ".png": "image/png", ".ico": "image/x-icon", ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".eot": "application/vnd.ms-fontobject", ".map": "application/json" };
const codes = [];       // what DWC asked the board to run: recorded, answered with an empty reply
const unknown = [];     // requests this simulator has no answer for (to see what is missing)
let sdRoot = null;      // the SD folder of the API server (the files the service writes are the ones DWC reads)
let model = null;       // the last object model read from the API server
const clients = new Set();

// ---- the API server ----
function apiRequest(method, urlPath, headers, body) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: "127.0.0.1", port: API.port, path: urlPath, method, headers: headers || {} }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on("error", reject);
    if (body && body.length) req.write(body);
    req.end();
  });
}
const apiJson = async (urlPath) => JSON.parse((await apiRequest("GET", urlPath)).body.toString("utf8"));

// ---- object model patches (DSF sends only what changed; an array of objects goes item by item, {} for an item that did not change) ----
// The data a plugin publishes is the exception: DWC replaces the value of a key, it does not merge it, so a key that changed goes whole.
function diff(before, after, depth, inPlugins) {
  if (before === after) return undefined;
  if (inPlugins && depth === 4) return JSON.stringify(before) === JSON.stringify(after) ? undefined : after;   // plugins.<id>.data.<key>
  if (Array.isArray(after)) {
    if (!Array.isArray(before) || !after.every((v) => v && typeof v === "object" && !Array.isArray(v))) return JSON.stringify(before) === JSON.stringify(after) ? undefined : after;
    const items = after.map((v, i) => { const d = diff(before[i], v, (depth || 0) + 1, inPlugins); return d === undefined ? {} : d; });
    return before.length === after.length && items.every((d) => Object.keys(d).length === 0) ? undefined : items;
  }
  if (after && typeof after === "object") {
    if (!before || typeof before !== "object" || Array.isArray(before)) return after;
    const out = {};
    Object.keys(after).forEach((k) => { const d = diff(before[k], after[k], (depth || 0) + 1, depth ? inPlugins : k === "plugins"); if (d !== undefined) out[k] = d; });
    Object.keys(before).forEach((k) => { if (!(k in after)) out[k] = null; });
    return Object.keys(out).length ? out : undefined;
  }
  return after;
}

async function pollModel() {
  try {
    model = await apiJson("/__dev/model");
    clients.forEach(pushPatch);
  } catch (e) { /* the API server is restarting: keep the last model */ }
}

function pushPatch(client) {
  if (!client.ready || !model) return;
  const patch = diff(client.sent, model);
  if (patch === undefined) return;
  client.ready = false;
  client.sent = model;
  client.ws.send(JSON.stringify(patch));
}

// ---- the SD card ----
function sdPath(name) {
  const rel = decodeURIComponent(name).replace(/^\d+:\/*/, "").replace(/\\/g, "/");
  const full = path.resolve(sdRoot, rel);
  if (full !== sdRoot && !full.startsWith(sdRoot + path.sep)) throw new Error("outside the SD folder");
  return full;
}
const stamp = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);

function defaultSettings() {
  // DWC keeps its settings on the SD: the page is one of the plugins of this build, switched on here; language and theme as asked
  return JSON.stringify({ main: { language: LANG, darkTheme: DARK, enabledPlugins: [PLUGIN], settingsStorageLocal: false, lastHostname: "127.0.0.1:" + PORT }, machine: { enabledPlugins: [] } });
}

function readBody(req) {
  return new Promise((resolve) => { const chunks = []; req.on("data", (c) => chunks.push(c)); req.on("end", () => resolve(Buffer.concat(chunks))); });
}

const send = (res, status, body, type) => { res.writeHead(status, { "Content-Type": type || "application/json", "Cache-Control": "no-store" }); res.end(body === undefined ? "" : typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body)); };

async function machine(req, res, url) {
  const rest = url.pathname.slice("/machine/".length);
  if (rest === "connect") return send(res, 200, { sessionKey: "sim-session" });
  if (rest === "disconnect" || rest === "noop") return send(res, 204);
  if (rest === "model") return send(res, 200, model || {});
  if (rest === "code" && req.method === "POST") {
    codes.push({ t: new Date().toISOString().slice(11, 19), code: (await readBody(req)).toString("utf8") });
    return send(res, 200, "", "text/plain");
  }
  if (rest.startsWith(PLUGIN + "/")) {   // the API of the service: passed on as it came
    const body = await readBody(req);
    const headers = Object.assign({}, req.headers, { host: "127.0.0.1:" + API.port });
    const out = await apiRequest(req.method, "/machine/" + rest + url.search, headers, body);
    res.writeHead(out.status, { "Content-Type": out.headers["content-type"] || "application/json", "Cache-Control": "no-store" });
    return res.end(out.body);
  }
  if (rest.startsWith("file/")) {
    const full = sdPath(rest.slice(5));
    if (req.method === "GET") {
      if (!fs.existsSync(full) || fs.statSync(full).isDirectory()) return send(res, 404, "");
      return send(res, 200, fs.readFileSync(full), "application/octet-stream");
    }
    if (req.method === "PUT") { fs.mkdirSync(path.dirname(full), { recursive: true }); fs.writeFileSync(full, await readBody(req)); return send(res, 201); }
    if (req.method === "DELETE") { fs.rmSync(full, { recursive: true, force: true }); return send(res, 204); }
  }
  if (rest.startsWith("directory/")) {
    const full = sdPath(rest.slice(10));
    if (req.method === "PUT") { fs.mkdirSync(full, { recursive: true }); return send(res, 201); }
    if (!fs.existsSync(full)) return send(res, 404, "");
    return send(res, 200, fs.readdirSync(full, { withFileTypes: true }).map((e) => { const s = fs.statSync(path.join(full, e.name)); return { type: e.isDirectory() ? "d" : "f", name: e.name, size: s.size, date: stamp(s.mtime) }; }));
  }
  if (rest.startsWith("fileinfo/")) return send(res, 404, "");
  unknown.push(req.method + " " + url.pathname);
  send(res, 404, "");
}

function staticFile(req, res, url) {
  let rel = decodeURIComponent(url.pathname).replace(/^\/+/, "");
  let full = path.resolve(DWC_DIST, rel);
  if (!full.startsWith(DWC_DIST)) return send(res, 403, "");
  // DWC routes in the address bar (/Plugins/WorkshopService): any path that is not a file is the application
  if (!rel || !fs.existsSync(full) || fs.statSync(full).isDirectory()) {
    if (path.extname(rel)) return send(res, 404, "");
    full = path.join(DWC_DIST, "index.html");
  }
  send(res, 200, fs.readFileSync(full), TYPES[path.extname(full).toLowerCase()] || "application/octet-stream");
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://127.0.0.1");
  try {
    if (!["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(req.socket.remoteAddress)) return send(res, 403, "");
    if (url.pathname.startsWith("/rr_")) return send(res, 404, "");            // not a standalone board: DWC goes on to the SBC connector
    if (url.pathname === "/__sim/state") return send(res, 200, { codes, unknown, clients: clients.size, sd: sdRoot, dwc: DWC_DIST, api: API.href });
    if (url.pathname.startsWith("/__dev/")) {
      const body = await readBody(req);
      const out = await apiRequest(req.method, url.pathname + url.search, { "content-type": "application/json", "content-length": String(body.length) }, body);
      return send(res, out.status, out.body);
    }
    if (url.pathname.startsWith("/machine/")) return await machine(req, res, url);
    staticFile(req, res, url);
  } catch (e) {
    send(res, 502, { error: String(e && e.message || e) });
  }
});

const wss = new WebSocketServer({ noServer: true });
server.on("upgrade", (req, socket, head) => {
  const url = new URL(req.url, "http://127.0.0.1");
  if (url.pathname !== "/machine") return socket.destroy();
  wss.handleUpgrade(req, socket, head, (ws) => {
    const client = { ws, ready: false, sent: model };
    clients.add(client);
    ws.send(JSON.stringify(model || {}));          // the first message is the whole object model
    ws.on("message", (data) => {
      const text = data.toString();
      if (text === "PING\n") return ws.send("PONG\n");
      if (text === "OK\n") { client.ready = true; pushPatch(client); }
    });
    ws.on("close", () => clients.delete(client));
    ws.on("error", () => clients.delete(client));
  });
});

(async () => {
  const state = await apiJson("/__dev/state");
  sdRoot = path.resolve(state.data_root, "sd");
  const settings = path.join(sdRoot, "sys", "dwc-settings.json");
  fs.mkdirSync(path.dirname(settings), { recursive: true });
  fs.writeFileSync(settings, defaultSettings());
  await pollModel();
  setInterval(pollModel, POLL_MS);
  server.listen(PORT, "127.0.0.1", () => console.log("dwc sim: http://127.0.0.1:" + server.address().port + "/Plugins/" + PLUGIN + "  (api " + API.origin + ", sd " + sdRoot + ")"));
})().catch((e) => { console.error("dwc_sim: cannot reach the API server at " + API.origin + ": " + (e && e.message || e)); process.exit(1); });
