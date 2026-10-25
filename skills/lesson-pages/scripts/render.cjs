// Render TeX with KaTeX and highlight code with highlight.js at write time.
// lesson_pages.py runs this with a JSON request on stdin and reads a JSON reply on stdout:
//   {"items": [{"kind": "tex", "source": "...", "display": true},
//              {"kind": "code", "source": "...", "lang": "python", "symbols": {"m_i": 1}}]}
//   -> {"items": [{"html": "..."} | {"error": "..."}]}
// Only the vendored copies under assets/vendor are loaded; pages never load these libraries.
"use strict";
const fs = require("fs");
const path = require("path");

const vendor = path.join(__dirname, "..", "assets", "vendor");
const katex = require(path.join(vendor, "katex", "katex.min.js"));
const hljs = require(path.join(vendor, "highlight", "highlight.min.js"));

const CLASS_LIST = /^(?:lp-s[1-4]|lp-hl|lp-t[1-6])$/;
const STEP_LIST = /^[0-9]+(?:-[0-9]+)?$/;
const INLINE_COLOR = /(?:^|[;"\s])(?:background-|border-)?color:\s*([^;"]+)/g;
// KaTeX paints commands it may not run in errorColor instead of throwing, even inside \phantom; this value marks them.
const REFUSED = "#0a0b0c";
const LANGUAGE_ALIASES = { cuda: "cpp", cu: "cpp", triton: "python", py: "python", sh: "bash", console: "shell" };

function macros() {
  return {
    "\\sA": "\\htmlClass{lp-s1}{#1}",
    "\\sB": "\\htmlClass{lp-s2}{#1}",
    "\\sC": "\\htmlClass{lp-s3}{#1}",
    "\\sD": "\\htmlClass{lp-s4}{#1}",
    "\\hl": "\\htmlClass{lp-hl}{#1}",
    "\\tA": "\\htmlClass{lp-t1}{#1}",
    "\\tB": "\\htmlClass{lp-t2}{#1}",
    "\\tC": "\\htmlClass{lp-t3}{#1}",
    "\\tD": "\\htmlClass{lp-t4}{#1}",
    "\\tE": "\\htmlClass{lp-t5}{#1}",
    "\\tF": "\\htmlClass{lp-t6}{#1}",
    "\\step": "\\htmlData{show=#1}{#2}",
  };
}

// Only the symbol, highlight and anatomy-term classes and step lists may reach the HTML; no links, ids, styles or other data attributes.
function trust(context) {
  if (context.command === "\\htmlClass") return CLASS_LIST.test(context.class || "");
  if (context.command === "\\htmlData") {
    const keys = Object.keys(context.attributes || {});
    return keys.length === 1 && keys[0] === "data-show" && STEP_LIST.test(context.attributes["data-show"]);
  }
  return false;
}

function renderTex(item) {
  const rendered = katex.renderToString(item.source, {
    displayMode: !!item.display,
    output: "htmlAndMathml",
    throwOnError: true,
    strict: "ignore",
    trust: trust,
    macros: macros(),
    maxSize: 20,
    maxExpand: 500,
    errorColor: REFUSED,
  });
  if (rendered.toLowerCase().indexOf(REFUSED) >= 0) {
    throw new Error("TeX uses a command that is not allowed here (links, images, ids, styles or other classes)");
  }
  for (const style of rendered.match(/style="[^"]*"/g) || []) {
    for (const match of style.matchAll(INLINE_COLOR)) {
      if (!/^(?:transparent|inherit|currentcolor)$/i.test(match[1].trim())) {
        throw new Error("TeX uses a command that is not allowed here or a fixed color; color symbols with \\sA to \\sD and highlight with \\hl");
      }
    }
  }
  return rendered;
}

function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Wrap whole-word identifiers in the symbol color of their formula counterpart, outside strings and comments.
function colorSymbols(htmlText, symbols) {
  const names = Object.keys(symbols || {}).sort((a, b) => b.length - a.length);
  if (!names.length) return htmlText;
  const word = new RegExp("(^|[^\\p{L}\\p{N}_$])(" + names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")(?![\\p{L}\\p{N}_$])", "gu");
  const skip = [];
  return htmlText.replace(/(<span class="([^"]*)">)|(<\/span>)|([^<]+)/g, (match, open, cls, close, text) => {
    if (open) { skip.push(/\bhljs-(?:string|comment|meta|doctag|regexp)\b/.test(cls)); return match; }
    if (close) { skip.pop(); return match; }
    if (skip.some(Boolean)) return match;
    return text.split(/(&[A-Za-z0-9#]+;)/).map((part, index) => index % 2 ? part
      : part.replace(word, (all, before, name) => before + '<var class="lp-s' + symbols[name] + '">' + name + "</var>")).join("");
  });
}

function renderCode(item) {
  const asked = String(item.lang || "").toLowerCase();
  const language = LANGUAGE_ALIASES[asked] || asked;
  if (!hljs.getLanguage(language)) {
    throw new Error("highlight.js here does not know data-lang=\"" + asked + "\"; use one of " + hljs.listLanguages().join(", ") + ", cuda or triton, or drop data-lang");
  }
  const highlighted = language === "plaintext" ? escapeHtml(item.source) : hljs.highlight(item.source, { language: language, ignoreIllegals: true }).value;
  return colorSymbols(highlighted, item.symbols);
}

function main() {
  const request = JSON.parse(fs.readFileSync(0, "utf8"));
  const items = (request.items || []).map((item) => {
    try {
      if (item.kind === "tex") return { html: renderTex(item) };
      if (item.kind === "code") return { html: renderCode(item) };
      return { error: "unknown item kind " + item.kind };
    } catch (error) {
      return { error: String(error && error.message ? error.message : error) };
    }
  });
  process.stdout.write(JSON.stringify({ items: items, katex: katex.version, highlight: hljs.versionString }));
}

main();
