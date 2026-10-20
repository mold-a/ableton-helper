/* Ableton Helper chat UI. Vanilla JS (ES2019), no dependencies. Needs lib.js (window.AbLib). */
(function () {
  "use strict";
  var L = window.AbLib;

  // Optional override for the backend origin: index.html?server=http://127.0.0.1:8765
  var BASE = "";
  try {
    var qs = new URLSearchParams(location.search).get("server");
    if (qs && /^https?:\/\/[^\s]+$/.test(qs)) BASE = qs.replace(/\/+$/, "");
  } catch (e) { /* ignore */ }

  var LS_CONV = "abhelper.conversation_id";
  var POLL_MS = 5000;

  var $ = function (id) { return document.getElementById(id); };
  var el = {
    chat: $("chat"), empty: $("empty"), messages: $("messages"), suggestions: $("suggestions"),
    composer: $("composer"), input: $("input"), send: $("btn-send"), stop: $("btn-stop"),
    newChat: $("btn-new"), settingsBtn: $("btn-settings"),
    stLive: $("st-live"), stAi: $("st-ai"),
    settings: $("settings"), settingsClose: $("settings-close"), settingsForm: $("settings-form"),
    cfgKey: $("cfg-key"), cfgKeyState: $("cfg-key-state"), cfgModel: $("cfg-model"),
    cfgModelCustom: $("cfg-model-custom"), cfgEffort: $("cfg-effort"), cfgBridge: $("cfg-bridge"),
    cfgSaved: $("cfg-saved"), cfgSave: $("cfg-save")
  };

  var state = {
    conversationId: lsGet(LS_CONV) || null,
    streaming: false,
    abort: null,
    lastUserText: "",
    status: null,
    turn: null // current assistant turn
  };

  /* ---------- storage ---------- */
  function lsGet(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { if (v === null) window.localStorage.removeItem(k); else window.localStorage.setItem(k, v); } catch (e) { /* ignore */ } }

  /* ---------- DOM helpers ---------- */
  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function nearBottom() {
    var c = el.chat;
    return c.scrollHeight - c.scrollTop - c.clientHeight < 80;
  }
  function scrollDown(force) {
    if (force || state.stick) el.chat.scrollTop = el.chat.scrollHeight;
  }
  el.chat.addEventListener("scroll", function () { state.stick = nearBottom(); });
  state.stick = true;

  function updateEmpty() {
    el.empty.hidden = el.messages.children.length > 0;
  }

  /* ---------- messages ---------- */
  function addUser(text) {
    var m = h("div", "msg user", text);
    el.messages.appendChild(m);
    updateEmpty();
    state.stick = true;
    scrollDown(true);
  }

  function newTurn() {
    state.turn = { text: null, bubble: null, tools: {}, gotText: false, raf: 0 };
    return state.turn;
  }

  function ensureBubble() {
    var t = state.turn;
    if (!t.bubble) {
      t.bubble = h("div", "msg assistant streaming");
      t.text = "";
      el.messages.appendChild(t.bubble);
      updateEmpty();
    }
    return t.bubble;
  }

  function renderBubble() {
    var t = state.turn;
    if (!t || !t.bubble) return;
    t.raf = 0;
    t.bubble.innerHTML = L.renderMarkdown(t.text); // safe: renderMarkdown escapes all model text
    scrollDown();
  }

  function closeBubble() {
    var t = state.turn;
    if (!t || !t.bubble) return;
    if (t.raf) { cancelAnimationFrame(t.raf); t.raf = 0; }
    renderBubble();
    t.bubble.classList.remove("streaming");
    if (!t.text.trim()) t.bubble.remove();
    t.bubble = null;
    t.text = null;
  }

  function onTextDelta(ev) {
    var t = state.turn;
    if (typeof ev.text !== "string" || !ev.text) return;
    ensureBubble();
    t.gotText = true;
    t.text += ev.text;
    if (!t.raf) t.raf = requestAnimationFrame(renderBubble);
  }

  function onToolStart(ev) {
    var t = state.turn;
    closeBubble();
    var id = ev.id || ("t" + Math.random().toString(36).slice(2));
    var wrap = h("div", "tool running");
    var head = h("button", "tool-head");
    head.type = "button";
    head.setAttribute("aria-expanded", "false");
    var icon = h("span", "tool-icon");
    icon.appendChild(h("span", "spinner"));
    var label = h("span", "tool-label", L.toolLabel(ev.name));
    var summary = h("span", "tool-summary", "");
    var caret = h("span", "tool-caret", "›");
    head.appendChild(icon); head.appendChild(label); head.appendChild(summary); head.appendChild(caret);
    var details = h("pre", "tool-details");
    details.hidden = true;
    details.textContent = ev.input && Object.keys(ev.input).length ? "Вход:\n" + L.prettyJson(ev.input) : "";
    head.addEventListener("click", function () {
      var open = details.hidden;
      if (open && !details.textContent) return;
      details.hidden = !open;
      wrap.classList.toggle("open", open);
      head.setAttribute("aria-expanded", String(open));
    });
    wrap.appendChild(head); wrap.appendChild(details);
    el.messages.appendChild(wrap);
    t.tools[id] = { wrap: wrap, icon: icon, summary: summary, details: details, input: ev.input, name: ev.name };
    updateEmpty();
    scrollDown();
  }

  function onToolResult(ev) {
    var t = state.turn;
    var rec = t.tools[ev.id];
    if (!rec) { // result without a start (should not happen) — create a chip on the fly
      onToolStart({ id: ev.id, name: ev.name, input: null });
      rec = t.tools[ev.id];
    }
    var ok = ev.ok !== false;
    rec.wrap.classList.remove("running");
    rec.wrap.classList.add(ok ? "ok" : "bad");
    rec.icon.textContent = ok ? "✓" : "✕";
    rec.summary.textContent = ev.summary ? "— " + L.truncate(ev.summary, 240) : "";
    var parts = [];
    if (rec.input && Object.keys(rec.input).length) parts.push("Вход:\n" + L.prettyJson(rec.input));
    if (ev.data !== undefined && ev.data !== null) parts.push("Результат:\n" + L.prettyJson(ev.data));
    rec.details.textContent = parts.join("\n\n");
    scrollDown();
  }

  function finishRunningTools(failed) {
    var t = state.turn;
    if (!t) return;
    Object.keys(t.tools).forEach(function (id) {
      var r = t.tools[id];
      if (r.wrap.classList.contains("running")) {
        r.wrap.classList.remove("running");
        r.wrap.classList.add("bad");
        r.icon.textContent = "✕";
        r.summary.textContent = failed ? "— прервано" : "";
      }
    });
  }

  function addNotice(title, body, opts) {
    opts = opts || {};
    var n = h("div", "notice" + (opts.info ? " info" : ""));
    n.setAttribute("role", "alert");
    n.appendChild(h("strong", null, title));
    if (body) n.appendChild(h("div", null, body));
    if (opts.steps) {
      var ol = h("ol");
      opts.steps.forEach(function (s) { ol.appendChild(h("li", null, s)); });
      n.appendChild(ol);
    }
    (opts.buttons || []).forEach(function (b) {
      var btn = h("button", "btn", b.label);
      btn.type = "button";
      btn.addEventListener("click", b.onClick);
      n.appendChild(btn);
    });
    el.messages.appendChild(n);
    updateEmpty();
    state.stick = true;
    scrollDown(true);
    return n;
  }

  function onError(ev) {
    closeBubble();
    finishRunningTools(true);
    var code = ev.code || "internal";
    var msg = ev.message || "Что-то пошло не так.";
    if (code === "llm_not_configured") {
      addNotice("Не настроен AI", "Чтобы я мог отвечать, укажите API-ключ Anthropic в настройках.", {
        buttons: [{ label: "Открыть настройки", onClick: openSettings }]
      });
    } else if (code === "bridge_offline") {
      addNotice("Нет связи с Ableton Live", msg, {
        steps: [
          "Установите Remote Script: python scripts/install_remote_script.py",
          "В Live откройте Settings (Preferences) → Link, Tempo & MIDI и выберите Control Surface «AbletonHelper».",
          "Input/Output оставьте None, затем повторите запрос."
        ]
      });
    } else if (code === "llm_error") {
      addNotice("Ошибка языковой модели", msg);
    } else {
      addNotice("Ошибка", msg);
    }
  }

  /* ---------- sending ---------- */
  function setStreaming(on) {
    state.streaming = on;
    el.input.disabled = on;
    el.send.hidden = on;
    el.stop.hidden = !on;
    if (!on) setTimeout(function () { try { el.input.focus(); } catch (e) { /* ignore */ } }, 0);
  }

  function handleEvent(ev) {
    if (!ev || typeof ev !== "object") return;
    switch (ev.type) {
      case "conversation":
        if (ev.conversation_id) { state.conversationId = ev.conversation_id; lsSet(LS_CONV, ev.conversation_id); }
        break;
      case "text_delta": onTextDelta(ev); break;
      case "tool_start": onToolStart(ev); break;
      case "tool_result": onToolResult(ev); break;
      case "done":
        if (!state.turn.gotText && typeof ev.text === "string" && ev.text.trim()) {
          onTextDelta({ text: ev.text });
        }
        closeBubble();
        break;
      case "error": onError(ev); break;
      default: break; // unknown / raw / stream_end — ignore
    }
  }

  function send(text) {
    text = (text || "").trim();
    if (!text || state.streaming) return;
    state.lastUserText = text;
    addUser(text);
    el.input.value = "";
    autosize();
    newTurn();
    setStreaming(true);

    var ctrl = new AbortController();
    state.abort = ctrl;
    var aborted = false;
    var gotAny = false;
    var body = { message: text };
    if (state.conversationId) body.conversation_id = state.conversationId;

    fetch(BASE + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(body),
      signal: ctrl.signal
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.text().then(function (t) {
          var detail = "";
          try { var j = JSON.parse(t); detail = j.detail || j.message || ""; } catch (e) { detail = t; }
          throw new Error("HTTP " + resp.status + (detail ? ": " + L.truncate(typeof detail === "string" ? detail : L.prettyJson(detail), 300) : ""));
        });
      }
      if (!resp.body || !resp.body.getReader) throw new Error("Браузер не поддерживает потоковый ответ.");
      var reader = resp.body.getReader();
      var decoder = new TextDecoder("utf-8");
      var parser = L.createSSEParser();
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) {
            parser.feed(decoder.decode()).concat(parser.flush()).forEach(function (ev) { gotAny = true; handleEvent(ev); });
            return;
          }
          parser.feed(decoder.decode(r.value, { stream: true })).forEach(function (ev) { gotAny = true; handleEvent(ev); });
          return pump();
        });
      }
      return pump();
    }).catch(function (err) {
      if (err && err.name === "AbortError") { aborted = true; return; }
      closeBubble();
      finishRunningTools(true);
      addNotice("Нет связи с сервером",
        (gotAny ? "Соединение оборвалось. " : "") + "Проверьте, что запущен «abhelper serve». " + (err && err.message ? "(" + err.message + ")" : ""),
        { buttons: [{ label: "Повторить", onClick: function () { if (!state.streaming) send(state.lastUserText); } }] });
    }).then(function () {
      if (aborted) {
        if (state.turn && state.turn.bubble) {
          var s = h("div", "stopped", "Остановлено.");
          state.turn.bubble.appendChild(s);
          state.turn.bubble.classList.remove("streaming");
          state.turn.bubble = null;
        } else {
          var m = h("div", "msg assistant");
          m.appendChild(h("span", "stopped", "Остановлено."));
          el.messages.appendChild(m);
        }
        finishRunningTools(true);
      } else {
        closeBubble();
        finishRunningTools(false);
      }
      state.abort = null;
      setStreaming(false);
      pollStatus();
    });
  }

  el.composer.addEventListener("submit", function (e) { e.preventDefault(); send(el.input.value); });
  el.input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      send(el.input.value);
    }
  });
  function autosize() {
    el.input.style.height = "auto";
    el.input.style.height = Math.min(el.input.scrollHeight, 140) + "px";
  }
  el.input.addEventListener("input", autosize);
  el.stop.addEventListener("click", function () { if (state.abort) state.abort.abort(); });

  el.newChat.addEventListener("click", function () {
    if (state.abort) state.abort.abort();
    var id = state.conversationId;
    state.conversationId = null;
    lsSet(LS_CONV, null);
    el.messages.textContent = "";
    state.turn = null;
    updateEmpty();
    if (id) {
      fetch(BASE + "/api/reset", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: id })
      }).catch(function () { /* server may be down; local state is already cleared */ });
    }
    try { el.input.focus(); } catch (e) { /* ignore */ }
  });

  /* ---------- suggestions ---------- */
  function renderSuggestions(items) {
    el.suggestions.textContent = "";
    items.forEach(function (s) {
      var b = h("button", "chip-btn", s);
      b.type = "button";
      b.addEventListener("click", function () { send(s); });
      el.suggestions.appendChild(b);
    });
  }
  function loadSuggestions() {
    renderSuggestions(L.DEFAULT_SUGGESTIONS);
    fetch(BASE + "/api/suggestions").then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (j && Array.isArray(j.items) && j.items.length) {
        renderSuggestions(j.items.filter(function (x) { return typeof x === "string"; }).slice(0, 12));
      }
    }).catch(function () { /* keep defaults */ });
  }

  /* ---------- status ---------- */
  function setDot(wrap, st, tip) {
    wrap.firstChild.setAttribute("data-state", st);
    wrap.title = tip;
    wrap.setAttribute("aria-label", tip);
  }
  function applyStatus(s) {
    state.status = s;
    var b = (s && s.bridge) || {};
    var l = (s && s.llm) || {};
    if (!s) {
      setDot(el.stLive, "unknown", "Live: нет данных (сервер недоступен)");
      setDot(el.stAi, "unknown", "AI: нет данных (сервер недоступен)");
      return;
    }
    setDot(el.stLive, b.connected ? "ok" : "bad",
      b.connected
        ? "Live подключён. Версия Live: " + (b.live_version || "?") + ", Remote Script: " + (b.script_version || "?")
        : "Live не подключён: включите Control Surface «AbletonHelper» в настройках Live");
    setDot(el.stAi, l.configured ? "ok" : "warn",
      l.configured ? "AI настроен. Модель: " + (l.model || "?") : "AI не настроен: нужен API-ключ (шестерёнка)");
  }
  function pollStatus() {
    fetch(BASE + "/api/status", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("status " + r.status); return r.json(); })
      .then(applyStatus)
      .catch(function () { applyStatus(null); });
  }

  /* ---------- settings ---------- */
  var KNOWN_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"];
  var lastFocus = null;

  function openSettings() {
    lastFocus = document.activeElement;
    el.cfgSaved.textContent = ""; el.cfgSaved.className = "save-state";
    el.cfgKey.value = "";
    el.settings.hidden = false;
    fetch(BASE + "/api/config").then(function (r) { if (!r.ok) throw new Error(); return r.json(); }).then(fillSettings)
      .catch(function () { el.cfgSaved.textContent = "Не удалось загрузить настройки."; el.cfgSaved.className = "save-state err"; });
    el.cfgKey.focus();
  }
  function closeSettings() {
    el.settings.hidden = true;
    el.cfgKey.value = "";
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) { /* ignore */ } }
  }
  function fillSettings(c) {
    var model = c.model || KNOWN_MODELS[0];
    if (KNOWN_MODELS.indexOf(model) >= 0) {
      el.cfgModel.value = model; el.cfgModelCustom.hidden = true; el.cfgModelCustom.value = "";
    } else {
      el.cfgModel.value = "__custom__"; el.cfgModelCustom.hidden = false; el.cfgModelCustom.value = model;
    }
    el.cfgEffort.value = ["low", "medium", "high"].indexOf(c.effort) >= 0 ? c.effort : "medium";
    el.cfgKeyState.textContent = c.api_key_set ? "Ключ сохранён. Оставьте поле пустым, чтобы не менять." : "Ключ не задан.";
    el.cfgKeyState.className = "hint" + (c.api_key_set ? " good" : "");
    el.cfgKey.placeholder = c.api_key_set ? "•••••••• (ключ сохранён)" : "sk-ant-…";
    el.cfgBridge.textContent = c.bridge_host ? "Мост Live: " + c.bridge_host + ":" + c.bridge_port : "";
  }
  el.cfgModel.addEventListener("change", function () {
    el.cfgModelCustom.hidden = el.cfgModel.value !== "__custom__";
    if (!el.cfgModelCustom.hidden) el.cfgModelCustom.focus();
  });
  el.settingsBtn.addEventListener("click", openSettings);
  el.settingsClose.addEventListener("click", closeSettings);
  el.settings.addEventListener("mousedown", function (e) { if (e.target === el.settings) closeSettings(); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !el.settings.hidden) closeSettings();
  });
  el.settingsForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var payload = {};
    var key = el.cfgKey.value.trim();
    if (key) payload.api_key = key;
    var model = el.cfgModel.value === "__custom__" ? el.cfgModelCustom.value.trim() : el.cfgModel.value;
    if (model) payload.model = model;
    payload.effort = el.cfgEffort.value;
    el.cfgSave.disabled = true;
    el.cfgSaved.textContent = ""; el.cfgSaved.className = "save-state";
    fetch(BASE + "/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }).then(function (c) {
      el.cfgKey.value = "";
      fillSettings(c);
      el.cfgSaved.textContent = "Сохранено";
      pollStatus();
    }).catch(function (err) {
      el.cfgSaved.textContent = "Ошибка сохранения: " + (err && err.message ? err.message : "");
      el.cfgSaved.className = "save-state err";
    }).then(function () { el.cfgSave.disabled = false; });
  });

  /* ---------- init ---------- */
  loadSuggestions();
  pollStatus();
  setInterval(function () { if (!document.hidden) pollStatus(); }, POLL_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) pollStatus(); });
  updateEmpty();
  autosize();
  try { el.input.focus(); } catch (e) { /* ignore */ }
})();
