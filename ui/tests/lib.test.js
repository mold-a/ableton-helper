"use strict";
const test = require("node:test");
const assert = require("node:assert");
const lib = require("../lib.js");

function ev(obj) { return "data: " + JSON.stringify(obj) + "\n\n"; }

test("SSE: single complete event", () => {
  const p = lib.createSSEParser();
  const out = p.feed(ev({ type: "text_delta", text: "привет" }));
  assert.deepStrictEqual(out, [{ type: "text_delta", text: "привет" }]);
});

test("SSE: event split across chunks at arbitrary points", () => {
  const full = ev({ type: "conversation", conversation_id: "abc" }) + ev({ type: "text_delta", text: "x" });
  for (let cut = 1; cut < full.length; cut++) {
    const p = lib.createSSEParser();
    const got = [].concat(p.feed(full.slice(0, cut)), p.feed(full.slice(cut)));
    assert.strictEqual(got.length, 2, "cut at " + cut);
    assert.strictEqual(got[0].conversation_id, "abc");
    assert.strictEqual(got[1].text, "x");
  }
});

test("SSE: split exactly between the two newlines of the separator", () => {
  const p = lib.createSSEParser();
  assert.deepStrictEqual(p.feed('data: {"type":"done","text":"ok"}\n'), []);
  assert.deepStrictEqual(p.feed("\n"), [{ type: "done", text: "ok" }]);
});

test("SSE: several events in one chunk, CRLF line endings", () => {
  const p = lib.createSSEParser();
  const chunk = 'data: {"type":"a"}\r\n\r\ndata: {"type":"b"}\r\n\r\n';
  assert.deepStrictEqual(p.feed(chunk).map((e) => e.type), ["a", "b"]);
});

test("SSE: multi-line data is joined with newline (valid JSON whitespace)", () => {
  const p = lib.createSSEParser();
  const out = p.feed('data: {"type":"text_delta",\ndata: "text":"a"}\n\n');
  assert.deepStrictEqual(out, [{ type: "text_delta", text: "a" }]);
});

test("SSE: comments / keep-alives ignored, non-JSON becomes raw", () => {
  const p = lib.createSSEParser();
  assert.deepStrictEqual(p.feed(": ping\n\n"), []);
  assert.deepStrictEqual(p.feed("data: hello\n\n"), [{ type: "raw", data: "hello" }]);
});

test("SSE: unicode, emoji and escaped content survive", () => {
  const p = lib.createSSEParser();
  const text = "Баян 🎹 — «тёплый» звук\nвторая строка";
  const out = p.feed(ev({ type: "text_delta", text }));
  assert.strictEqual(out[0].text, text);
});

test("SSE: bytes split inside a multi-byte char decode correctly via TextDecoder stream", () => {
  const bytes = Buffer.from(ev({ type: "text_delta", text: "Баян" }), "utf8");
  const dec = new TextDecoder("utf-8");
  const p = lib.createSSEParser();
  let got = [];
  for (let i = 0; i < bytes.length; i++) {
    got = got.concat(p.feed(dec.decode(bytes.subarray(i, i + 1), { stream: true })));
  }
  assert.strictEqual(got.length, 1);
  assert.strictEqual(got[0].text, "Баян");
});

test("SSE: flush parses trailing block without final blank line", () => {
  const p = lib.createSSEParser();
  assert.deepStrictEqual(p.feed('data: {"type":"done"}\n'), []);
  assert.deepStrictEqual(p.flush(), [{ type: "done" }]);
  assert.deepStrictEqual(p.flush(), []);
});

test("markdown: escapes HTML (XSS)", () => {
  const html = lib.renderMarkdown('<img src=x onerror=alert(1)> <script>alert(1)</script>');
  assert.ok(!/<img/i.test(html));
  assert.ok(!/<script/i.test(html));
  assert.ok(html.includes("&lt;img"));
  assert.ok(html.includes("&lt;script&gt;"));
});

test("markdown: escaping inside bold, code and lists", () => {
  const html = lib.renderMarkdown("**<b onclick=1>x</b>** `<i>` \n- <u>item</u>\n```\n<div onload=1>\n```");
  assert.ok(!/<b onclick/i.test(html));
  assert.ok(!/<u>/i.test(html));
  assert.ok(!/<div/i.test(html));
  assert.ok(!/<i>/i.test(html));
  assert.ok(html.includes("<strong>&lt;b onclick=1&gt;x&lt;/b&gt;</strong>"));
});

test("markdown: quotes in attribute-like text are escaped; no links are generated", () => {
  const html = lib.renderMarkdown('[x](javascript:alert(1)) "q" \'s\'');
  assert.ok(!/<a\b/i.test(html));
  assert.ok(html.includes("&quot;q&quot;"));
});

test("markdown: bold, italic, inline code", () => {
  assert.strictEqual(lib.renderMarkdown("a **b** `c` *d*"), "<p>a <strong>b</strong> <code>c</code> <em>d</em></p>");
});

test("markdown: code content is not formatted", () => {
  assert.strictEqual(lib.renderMarkdown("`**x**`"), "<p><code>**x**</code></p>");
});

test("markdown: unordered and ordered lists, line breaks, paragraphs", () => {
  const html = lib.renderMarkdown("Шаги:\n1. Один\n2. Два\n\n- a\n- b\nстрока1\nстрока2");
  assert.ok(html.includes("<ol><li>Один</li><li>Два</li></ol>"));
  assert.ok(html.includes("<ul><li>a</li><li>b</li></ul>"));
  assert.ok(html.includes("<p>строка1<br>строка2</p>"));
});

test("markdown: headings are small, fenced code preserved, unclosed fence ok", () => {
  assert.ok(lib.renderMarkdown("## Заголовок").startsWith("<h4>"));
  assert.strictEqual(lib.renderMarkdown("```\na\n b\n```"), "<pre><code>a\n b</code></pre>");
  assert.strictEqual(lib.renderMarkdown("```\nx"), "<pre><code>x</code></pre>");
});

test("markdown: empty / null input", () => {
  assert.strictEqual(lib.renderMarkdown(""), "");
  assert.strictEqual(lib.renderMarkdown(null), "");
});

test("toolLabel: known and unknown names", () => {
  assert.strictEqual(lib.toolLabel("create_sound"), "Создаю звук");
  assert.strictEqual(lib.toolLabel("get_track_details"), "Смотрю дорожку");
  assert.strictEqual(lib.toolLabel("something_new"), "something_new");
  assert.strictEqual(lib.toolLabel("constructor"), "constructor");
  assert.strictEqual(Object.keys(lib.TOOL_LABELS).length, 15);
});
