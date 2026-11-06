// Run with Node and jsdom available on NODE_PATH (test-only dependency).
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const { renderMarkdown } = require("../app/static/markdown.js");

function render(source) {
  global.document = new JSDOM("<!doctype html><div id='target'></div>").window.document;
  const target = document.querySelector("#target");
  renderMarkdown(target, source);
  return target;
}

test("headings, emphasis, lists, quotes, code and tables", () => {
  const target = render("## 建议\n\n1. **先休息**\n2. 运行 `python app.py`\n\n> *慢慢来*，~~不用急~~\n\n```python\nprint(\"hello\")\n```\n\n| 项目 | 状态 |\n| --- | --- |\n| 睡眠 | 良好 |\n\n---");
  assert.equal(target.querySelector("h2").textContent, "建议");
  assert.equal(target.querySelectorAll("ol > li").length, 2);
  assert.equal(target.querySelector("strong").textContent, "先休息");
  assert.equal(target.querySelector("li code").textContent, "python app.py");
  assert.equal(target.querySelector("blockquote em").textContent, "慢慢来");
  assert.equal(target.querySelector("del").textContent, "不用急");
  assert.equal(target.querySelector("pre code").textContent, 'print("hello")');
  assert.equal(target.querySelectorAll("tbody td").length, 2);
  assert.ok(target.querySelector("hr"));
});

test("untrusted HTML and unsafe URLs never create executable elements", () => {
  const source = '<img src=x onerror=alert(1)>\n<script>alert(1)</script>\n[危险](javascript:alert(1))\n[数据](data:text/html,evil)\n[安全](https://example.com)';
  const target = render(source);
  assert.equal(target.querySelectorAll("img, script, iframe").length, 0);
  assert.ok(target.textContent.includes('<img src=x onerror=alert(1)>'));
  assert.equal(target.querySelectorAll("a").length, 1);
  assert.equal(target.querySelector("a").href, "https://example.com/");
  assert.equal(target.querySelector("a").rel, "noopener noreferrer");
});

test("every streaming prefix is safe and final output matches history render", () => {
  const source = '## 建议\n\n**先休息**\n\n```python\nprint("hello")\n```\n\n[链接](https://example.com)';
  const target = render("");
  for (let length = 0; length <= source.length; length++) {
    renderMarkdown(target, source.slice(0, length));
    assert.equal(target.querySelectorAll("script, img").length, 0);
  }
  assert.equal(target.innerHTML, render(source).innerHTML);
});

test("nested lists, ordered starts, line breaks and literal code", () => {
  const target = render('3. **第一步**\n   - 子项\n4. 第二步\n\n普通文字\n下一行\n\n`**不是粗体**`');
  assert.equal(target.querySelector("ol").getAttribute("start"), "3");
  assert.equal(target.querySelector("ol ul li").textContent, "子项");
  assert.ok(target.querySelector("p br"));
  assert.equal(target.querySelector("code").textContent, "**不是粗体**");
  assert.equal(target.querySelector("code strong"), null);
});
