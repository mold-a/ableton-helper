/* Ableton Helper UI — pure helpers (no DOM). Loaded by index.html, tested by node --test. */
(function (root) {
  "use strict";

  var TOOL_LABELS = {
    create_sound: "Создаю звук",
    design_custom_sound: "Проектирую звук",
    search_sound_library: "Ищу в библиотеке звуков",
    search_live_browser: "Ищу пресеты в браузере Live",
    get_session_overview: "Смотрю сет",
    get_device_parameters: "Читаю параметры",
    set_device_parameters: "Настраиваю параметры",
    load_device: "Добавляю устройство",
    create_midi_clip: "Пишу MIDI-клип",
    transport: "Транспорт",
    undo_last_action: "Отменяю",
    search_ableton_help: "Ищу в справке",
    search_knowledge: "Ищу в базе знаний",
    adjust_sound: "Подстраиваю звук",
    rename_track: "Переименовываю дорожку",
    delete_track: "Удаляю дорожку",
    get_track_details: "Смотрю дорожку"
  };

  var DEFAULT_SUGGESTIONS = [
    "Хочу звук баяна",
    "Сделай тёплый аналоговый пэд",
    "Жирный бас для техно",
    "Как включить Warp у сэмпла?",
    "Добавь реверб на выбранную дорожку"
  ];

  function toolLabel(name) {
    return Object.prototype.hasOwnProperty.call(TOOL_LABELS, name) ? TOOL_LABELS[name] : (name || "Действие");
  }

  function escapeHtml(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /* Inline markdown on ALREADY-ESCAPED text. Only produces <strong>, <em>, <code>. */
  function renderInline(escaped) {
    var codes = [];
    // protect inline code first
    var s = escaped.replace(/`([^`\n]+)`/g, function (_, c) {
      codes.push(c);
      return "\u0000" + (codes.length - 1) + "\u0000";
    });
    s = s.replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[\s(])\*([^*\s][^*\n]*?)\*(?=$|[\s).,;:!?])/g, "$1<em>$2</em>");
    s = s.replace(/\u0000(\d+)\u0000/g, function (_, i) {
      return "<code>" + codes[Number(i)] + "</code>";
    });
    return s;
  }

  /*
   * Lightweight, safe markdown -> HTML.
   * The input is HTML-escaped first, so the only tags in the output are the ones produced here.
   * Supports: paragraphs, line breaks, headings (#), bullet and numbered lists, code fences, bold, italic, inline code.
   */
  function renderMarkdown(text) {
    var src = String(text === null || text === undefined ? "" : text).replace(/\r\n?/g, "\n");
    var lines = src.split("\n");
    var out = [];
    var para = [];
    var list = null; // {type: "ul"|"ol", items: []}
    var i = 0;

    function flushPara() {
      if (para.length) {
        out.push("<p>" + para.map(function (l) { return renderInline(escapeHtml(l)); }).join("<br>") + "</p>");
        para = [];
      }
    }
    function flushList() {
      if (list) {
        out.push("<" + list.type + ">" + list.items.map(function (it) { return "<li>" + it + "</li>"; }).join("") + "</" + list.type + ">");
        list = null;
      }
    }

    while (i < lines.length) {
      var line = lines[i];
      var m;
      if ((m = /^\s*```/.exec(line))) {
        flushPara(); flushList();
        var code = [];
        i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) { code.push(lines[i]); i++; }
        i++; // closing fence (or EOF)
        out.push("<pre><code>" + escapeHtml(code.join("\n")) + "</code></pre>");
        continue;
      }
      if (/^\s*$/.test(line)) { flushPara(); flushList(); i++; continue; }
      if ((m = /^(#{1,3})\s+(.*)$/.exec(line))) {
        flushPara(); flushList();
        var lvl = m[1].length + 2; // h3..h5 inside a bubble
        out.push("<h" + lvl + ">" + renderInline(escapeHtml(m[2])) + "</h" + lvl + ">");
        i++; continue;
      }
      if ((m = /^\s*[-*•]\s+(.*)$/.exec(line))) {
        flushPara();
        if (!list || list.type !== "ul") { flushList(); list = { type: "ul", items: [] }; }
        list.items.push(renderInline(escapeHtml(m[1])));
        i++; continue;
      }
      if ((m = /^\s*\d+[.)]\s+(.*)$/.exec(line))) {
        flushPara();
        if (!list || list.type !== "ol") { flushList(); list = { type: "ol", items: [] }; }
        list.items.push(renderInline(escapeHtml(m[1])));
        i++; continue;
      }
      flushList();
      para.push(line);
      i++;
    }
    flushPara(); flushList();
    return out.join("");
  }

  /*
   * Incremental SSE parser. feed(chunk) accepts a string (decode bytes with TextDecoder({stream:true}) first).
   * Events are separated by a blank line; a "data:" field may span several lines (joined with "\n").
   * Lines starting with ":" are comments (keep-alive). Returns an array of parsed objects for the chunk.
   * Non-JSON payloads are returned as {type:"raw", data:"..."}.
   */
  function createSSEParser() {
    var buffer = "";

    function parseBlock(block) {
      var dataLines = [];
      var evName = null;
      var lines = block.split("\n");
      for (var k = 0; k < lines.length; k++) {
        var ln = lines[k];
        if (!ln || ln.charAt(0) === ":") continue;
        var idx = ln.indexOf(":");
        var field = idx === -1 ? ln : ln.slice(0, idx);
        var val = idx === -1 ? "" : ln.slice(idx + 1);
        if (val.charAt(0) === " ") val = val.slice(1);
        if (field === "data") dataLines.push(val);
        else if (field === "event") evName = val;
      }
      if (!dataLines.length) return null;
      var payload = dataLines.join("\n");
      if (payload === "[DONE]") return { type: "stream_end" };
      try {
        var obj = JSON.parse(payload);
        if (obj && typeof obj === "object" && !obj.type && evName) obj.type = evName;
        return obj;
      } catch (e) {
        return { type: "raw", data: payload };
      }
    }

    return {
      feed: function (chunk) {
        buffer += String(chunk).replace(/\r\n?/g, "\n");
        var events = [];
        var pos;
        while ((pos = buffer.indexOf("\n\n")) !== -1) {
          var block = buffer.slice(0, pos);
          buffer = buffer.slice(pos + 2);
          var ev = parseBlock(block);
          if (ev !== null && ev !== undefined) events.push(ev);
        }
        return events;
      },
      /* call at end of stream: parses a trailing block lacking the final blank line */
      flush: function () {
        var rest = buffer;
        buffer = "";
        if (!rest.trim()) return [];
        var ev = parseBlock(rest);
        return ev ? [ev] : [];
      }
    };
  }

  function prettyJson(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (e) {
      return String(value);
    }
  }

  function truncate(s, n) {
    s = String(s === null || s === undefined ? "" : s);
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  var api = {
    TOOL_LABELS: TOOL_LABELS,
    DEFAULT_SUGGESTIONS: DEFAULT_SUGGESTIONS,
    toolLabel: toolLabel,
    escapeHtml: escapeHtml,
    renderInline: renderInline,
    renderMarkdown: renderMarkdown,
    createSSEParser: createSSEParser,
    prettyJson: prettyJson,
    truncate: truncate
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AbLib = api;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
