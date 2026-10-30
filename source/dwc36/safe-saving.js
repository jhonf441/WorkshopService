'use strict';

// Copy of src/_shared/11-safe-saving.js for the Vue pages (they load before
// the JS plugins): the first one to load installs the wrapper.
// ---- Safe saving of the workshop's files (2026-10-11, request:
// "what happens if the power goes out while it is being written") ----
// The pages save their files of 0:/sys/ (buttons, cameras, zones,
// materials, Vision...) with a PUT to /machine/file: DSF writes directly
// over the file and a power cut in the middle left it cut off; when
// reading it, the page went back to the default values. Here, for all of them at
// once and without touching them:
//  - on SAVING: the current version is copied to <file>.bak, the new one goes
//    to <file>.tmp-<n> and is moved over the file in one step (rename,
//    atomic): either the whole old one or the whole new one remains;
//  - on READING a .json: if it is damaged or missing, the .bak is used (and it is
//    noted in the console) instead of falling back to the default values.
// If something in the safe path fails (old DSF), it is saved as before.
// The same code in src/_shared and vue/_shared: keep them equal.
(function workshopSavedSafe() {
  if (typeof window === "undefined" || !window.fetch || window.__workshopSavedSafe) return;
  window.__workshopSavedSafe = 1;
  var fetchOrig = window.fetch.bind(window);
  var RE_URL = /^(?:https?:\/\/[^/]+)?\/machine\/file\/([^?#]+)/;
  function pathOf(url) {
    var m = RE_URL.exec(String(url || ""));
    if (!m) return null;
    var p;
    try {
      p = decodeURIComponent(m[1]);
    } catch (e) {
      p = m[1];
    }
    // only the workshop's configuration: 0:/sys/ (not sys/config.g, which belongs to DWC/RRF)
    if (!/^0:\/sys\//.test(p) || /\/config\.g$|envio|\.tmp-\d+$|\.bak$/.test(p) || !/\.(json|g)$/.test(p)) return null;
    return p;
  }
  function cabeceras(extra) {
    var h = extra || {};
    if (window.__workshopSession) h["X-Session-Key"] = window.__workshopSession;
    return h;
  }
  function urlFile(p) {
    return "/machine/file/" + encodeURIComponent(p);
  }
  function move(since, hacia) {
    var fd = new FormData();
    fd.append("from", since);
    fd.append("to", hacia);
    fd.append("force", "true");
    return fetchOrig("/machine/file/move", { method: "POST", headers: cabeceras(), body: fd });
  }
  function jsonOk(t) {
    if (!t || !String(t).trim()) return false;
    try {
      JSON.parse(t);
      return true;
    } catch (e) {
      return false;
    }
  }
  // A file that is nowhere is remembered for a while ("nothing"): a page that rereads a .json every few seconds (the bridge, the trajectory)
  // would ask for it, and for its .bak, every time. 404 without asking for NOTHING_MS (it grows if it keeps missing). Saving the file forgets it.
  var NOTHING_MS = 10000;
  var NOTHING_MAX_MS = 300000; // 2026-10-17: before 60 s (about 100 queries / 10 min for files that do not exist); now it grows up to 5 min
  // and it is remembered between page loads (sessionStorage): reloading DWC does not ask again for what is not there
  function nothingRead(p) {
    try {
      var o = JSON.parse(window.sessionStorage.getItem("__workshopNothing:" + p) || "null");
      return o && o.until > Date.now() ? o : null;
    } catch (e) {
      return null;
    }
  }
  function nothingWrite(p, o) {
    try {
      if (o) window.sessionStorage.setItem("__workshopNothing:" + p, JSON.stringify(o));
      else window.sessionStorage.removeItem("__workshopNothing:" + p);
    } catch (e) {
      /*  without sessionStorage: only in memory */
    }
  }
  var where = {};
  function save(p, init) {
    delete where[p];
    nothingWrite(p, null);
    return saveEn(p, init);
  }
  function saveEn(p, init) {
    var tmp = p + ".tmp-" + Date.now() % 100000000;
    var isJson = /\.json$/.test(p);
    // 1) backup of what is there (if healthy)
    return fetchOrig(urlFile(p), { cache: "no-store", headers: cabeceras() })
      .then(function (r) {
        return r.ok ? r.text() : null;
      })
      .catch(function () {
        return null;
      })
      .then(function (current) {
        if (current === null || (isJson && !jsonOk(current))) return null;
        return fetchOrig(urlFile(p + ".bak"), { method: "PUT", headers: cabeceras({ "Content-Type": "application/octet-stream" }), body: current }).catch(function () {});
      })
      // 2) lo nuevo a un temporal y 3) moverlo encima en un paso
      .then(function () {
        return fetchOrig(urlFile(tmp), { method: "PUT", headers: init.headers, body: init.body });
      })
      .then(function (r) {
        if (!r.ok) throw new Error("tmp " + r.status);
        return move(tmp, p);
      })
      .then(function (r) {
        if (!r.ok) throw new Error("move " + r.status);
        return new Response(null, { status: 201, statusText: "Created" });
      })
      .catch(function (e) {
        // safe path not available: as before (and the temporary is cleaned)
        if (window.console) console.warn("[workshop] safe saving not available for " + p + " (" + (e && e.message) + "): saving directly");
        fetchOrig(urlFile(tmp), { method: "DELETE", headers: cabeceras() }).catch(function () {});
        return fetchOrig(urlFile(p), init);
      });
  }
  function noThis() {
    return new Response(null, { status: 404, statusText: "Not Found" });
  }
  function read(p, url, init) {
    var d = where[p];
    if (!d) {
      var g = nothingRead(p);
      if (g) d = where[p] = { nothing: true, ms: g.ms, until: g.until };
    }
    if (d && Date.now() < d.until) {
      if (d.nothing) return Promise.resolve(noThis());
    }
    return fetchOrig(url, init).then(function (r) {
      if (r.status !== 200 && r.status !== 404) return r;
      var pr = r.status === 200 ? r.clone().text() : Promise.resolve(null);
      return pr.then(function (t) {
        if (t !== null && jsonOk(t)) {
          delete where[p]; nothingWrite(p, null);
          return r;
        }
        // danado o ausente: probar el respaldo
        return fetchOrig(urlFile(p + ".bak"), { cache: "no-store", headers: cabeceras() })
          .then(function (rb) {
            return rb.ok ? rb.text() : null;
          })
          .then(function (tb) {
            if (tb === null || !jsonOk(tb)) {
              if (t === null && r.status === 404) {
                // it is nowhere: stop insisting for a while
                var before = where[p] && where[p].nothing ? where[p].ms : 0;
                var ms = before ? Math.min(NOTHING_MAX_MS, before * 2) : NOTHING_MS;
                where[p] = { nothing: true, ms: ms, until: Date.now() + ms };
                        nothingWrite(p, where[p]);
              }
              return r;
            }
            if (window.console) console.warn("[workshop] " + p + (t === null ? " is missing" : " is damaged") + ": used the backup " + p + ".bak");
            (window.__workshopRecovered = window.__workshopRecovered || []).push({ file: p, when: new Date().toISOString() });
            return new Response(tb, { status: 200, headers: { "Content-Type": "application/json" } });
          })
          .catch(function () {
            return r;
          });
      });
    });
  }
  window.fetch = function (resource, init) {
    var url = typeof resource === "string" ? resource : resource && resource.url;
    var metodo = String((init && init.method) || (resource && resource.method) || "GET").toUpperCase();
    var p = pathOf(url);
    if (!p || typeof resource !== "string") return fetchOrig(resource, init);
    if (metodo === "PUT") return save(p, init || {});
    if (metodo === "GET" && /\.json$/.test(p)) return read(p, resource, init);
    return fetchOrig(resource, init);
  };
})();
