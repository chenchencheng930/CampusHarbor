/* Model output is untrusted: build DOM nodes, never interpret raw HTML. */
(function (root) {
  "use strict";

  function inline(parent, text, depth = 0) {
    if (depth > 12) { parent.append(document.createTextNode(text)); return; }
    const pattern = /\\([\\`*~\[\]])|(`+)([^`]*?)\2|\[([^\]]+)\]\(([^\s)]+)\)|(\*\*|__)(.+?)\6|(~~)(.+?)\8|(\*|_)([^\n]+?)\10/g;
    let cursor = 0;
    for (const match of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(cursor, match.index)));
      if (match[1]) parent.append(document.createTextNode(match[1]));
      else if (match[2]) {
        const code = document.createElement("code");
        code.textContent = match[3];
        parent.append(code);
      } else if (match[4]) {
        let url;
        try { url = new URL(match[5]); } catch { /* Invalid links remain text. */ }
        if (url && ["https:", "http:", "mailto:"].includes(url.protocol)) {
          const link = document.createElement("a");
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          inline(link, match[4], depth + 1);
          parent.append(link);
        } else parent.append(document.createTextNode(match[0]));
      } else {
        const node = document.createElement(match[6] ? "strong" : match[8] ? "del" : "em");
        inline(node, match[7] || match[9] || match[11], depth + 1);
        parent.append(node);
      }
      cursor = match.index + match[0].length;
    }
    parent.append(document.createTextNode(text.slice(cursor)));
  }

  const listItem = /^(\s*)([-+*]|\d+[.)])\s+(.+)$/;
  const fence = /^\s{0,3}(`{3,}|~{3,})(.*)$/;
  const heading = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*$/;
  const rule = /^\s{0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$/;
  const quote = /^\s{0,3}>\s?(.*)$/;
  const tableDivider = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;
  const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());

  function blocks(parent, lines, depth = 0) {
    if (depth > 12) { parent.append(document.createTextNode(lines.join("\n"))); return; }
    const startsBlock = (index) => fence.test(lines[index]) || heading.test(lines[index]) ||
      rule.test(lines[index]) || quote.test(lines[index]) || listItem.test(lines[index]) ||
      (lines[index].includes("|") && tableDivider.test(lines[index + 1] || ""));
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      let match = line.match(fence);
      if (match) {
        const marker = match[1];
        const language = match[2].trim();
        const body = [];
        i++;
        while (i < lines.length) {
          const closing = lines[i].match(fence);
          if (closing && closing[1][0] === marker[0] && closing[1].length >= marker.length && !closing[2].trim()) break;
          body.push(lines[i++]);
        }
        if (i < lines.length) i++;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        if (/^[\w+-]+$/.test(language)) code.className = `language-${language}`;
        code.textContent = body.join("\n");
        pre.append(code);
        parent.append(pre);
        continue;
      }
      match = line.match(heading);
      if (match) {
        const node = document.createElement(`h${match[1].length}`);
        inline(node, match[2]); parent.append(node); i++; continue;
      }
      if (rule.test(line)) { parent.append(document.createElement("hr")); i++; continue; }
      if (quote.test(line)) {
        const body = [];
        while (i < lines.length && quote.test(lines[i])) body.push(lines[i++].match(quote)[1]);
        const node = document.createElement("blockquote");
        blocks(node, body, depth + 1); parent.append(node); continue;
      }
      if (line.includes("|") && tableDivider.test(lines[i + 1] || "")) {
        const wrap = document.createElement("div");
        wrap.className = "markdown-table-scroll";
        const table = document.createElement("table");
        const head = document.createElement("thead");
        const body = document.createElement("tbody");
        const addRow = (section, values, tag) => {
          const row = document.createElement("tr");
          for (const value of values) { const cell = document.createElement(tag); inline(cell, value); row.append(cell); }
          section.append(row);
        };
        addRow(head, cells(line), "th");
        i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].includes("|")) addRow(body, cells(lines[i++]), "td");
        table.append(head, body); wrap.append(table); parent.append(wrap); continue;
      }
      match = line.match(listItem);
      if (match) {
        const indent = match[1].length;
        const ordered = /^\d/.test(match[2]);
        const list = document.createElement(ordered ? "ol" : "ul");
        if (ordered) list.setAttribute("start", String(parseInt(match[2], 10)));
        while (i < lines.length) {
          const item = lines[i].match(listItem);
          if (!item || item[1].length !== indent || /^\d/.test(item[2]) !== ordered || rule.test(lines[i])) break;
          const node = document.createElement("li");
          inline(node, item[3]); i++;
          const continuation = [];
          while (i < lines.length && lines[i].trim() && /^\s+/.test(lines[i]) && lines[i].match(/^\s*/)[0].length > indent) {
            continuation.push(lines[i++].slice(indent + 2));
          }
          if (continuation.length) blocks(node, continuation, depth + 1);
          list.append(node);
        }
        parent.append(list); continue;
      }
      const paragraph = document.createElement("p");
      inline(paragraph, lines[i++]);
      while (i < lines.length && lines[i].trim() && !startsBlock(i)) {
        paragraph.append(document.createElement("br")); inline(paragraph, lines[i++]);
      }
      parent.append(paragraph);
    }
  }

  function renderMarkdown(target, source) {
    const fragment = document.createDocumentFragment();
    blocks(fragment, String(source ?? "").replace(/\r\n?/g, "\n").split("\n"));
    target.classList.add("markdown-body");
    target.replaceChildren(fragment);
  }

  root.renderMarkdown = renderMarkdown;
  if (typeof module !== "undefined") module.exports = { renderMarkdown };
})(typeof window !== "undefined" ? window : globalThis);
