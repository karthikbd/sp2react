// Allow-list HTML sanitizer for legacy Content Editor / Script Editor markup.
// The input is read into tags and text, and only allowed tags and attributes are written back out, with every
// attribute value re-escaped. Nothing the browser could run (scripts, event handlers, svg, javascript: URLs,
// CSS expressions) can survive, however it is spelled, because the output is built rather than filtered.

const ALLOWED_TAGS = new Set([
  "a", "abbr", "address", "b", "big", "blockquote", "br", "caption", "center", "cite", "code", "col", "colgroup",
  "dd", "del", "dfn", "div", "dl", "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins",
  "kbd", "li", "mark", "nobr", "ol", "p", "pre", "q", "s", "samp", "small", "span", "strike", "strong", "sub", "sup",
  "table", "tbody", "td", "tfoot", "th", "thead", "tr", "tt", "u", "ul", "var", "wbr",
]);
const VOID_TAGS = new Set(["br", "col", "hr", "img", "wbr"]);
// dropped together with everything inside them
const DROP_WITH_CONTENT = new Set([
  "script", "style", "iframe", "frame", "frameset", "object", "embed", "applet", "noscript", "noembed", "noframes",
  "template", "textarea", "title", "xmp", "plaintext", "svg", "math", "select", "option", "form", "button", "head",
]);
const GLOBAL_ATTRS = new Set(["class", "id", "title", "style", "align", "valign", "dir", "lang", "width", "height",
  "bgcolor", "color", "face", "size", "border", "nowrap"]);
const TAG_ATTRS: Record<string, Set<string>> = {
  a: new Set(["href", "target", "name", "rel"]),
  img: new Set(["src", "alt", "hspace", "vspace"]),
  table: new Set(["cellpadding", "cellspacing", "summary", "frame", "rules"]),
  td: new Set(["colspan", "rowspan", "headers", "scope", "abbr"]),
  th: new Set(["colspan", "rowspan", "headers", "scope", "abbr"]),
  col: new Set(["span"]),
  colgroup: new Set(["span"]),
  ol: new Set(["start", "type", "reversed"]),
  ul: new Set(["type"]),
  li: new Set(["value", "type"]),
  q: new Set(["cite"]),
  blockquote: new Set(["cite"]),
  del: new Set(["cite", "datetime"]),
  ins: new Set(["cite", "datetime"]),
};
const URL_ATTRS = new Set(["href", "src", "cite"]);
const SAFE_SCHEMES = new Set(["http", "https", "mailto", "tel"]);
const NAMED: Record<string, string> = {
  amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: "\u00a0", colon: ":", tab: "\t", newline: "\n",
  sol: "/", lpar: "(", rpar: ")", semi: ";", comma: ",", period: ".", excl: "!", num: "#", percnt: "%",
  copy: "\u00a9", reg: "\u00ae", ndash: "\u2013", mdash: "\u2014", hellip: "\u2026", laquo: "\u00ab", raquo: "\u00bb",
};

export function decodeEntities(s: string): string {
  return s.replace(/&(#[xX][0-9a-fA-F]+|#[0-9]+|[A-Za-z][A-Za-z0-9]*);?/g, (m, body: string) => {
    if (body[0] === "#") {
      const code = body[1] === "x" || body[1] === "X" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
      return code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff) ? String.fromCodePoint(code) : "\ufffd";
    }
    const v = NAMED[body.toLowerCase()];
    return v !== undefined ? v : m;
  });
}

function escapeText(s: string): string {
  return s.replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttr(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** True for relative URLs and http(s)/mailto/tel; also data: images for img src. */
export function safeUrl(value: string, allowDataImage = false): boolean {
  // browsers ignore control characters and whitespace inside a scheme ("java\tscript:")
  const v = value.replace(/[\u0000-\u0020\u007f-\u009f\u00a0\u1680\u2000-\u200f\u2028\u2029\u202f\u205f\u3000\ufeff]/g, "").toLowerCase();
  const m = v.match(/^([a-z][a-z0-9+.\-]*):/);
  if (!m) return !v.startsWith("\\\\") && !v.startsWith("/\\");
  if (SAFE_SCHEMES.has(m[1])) return true;
  return allowDataImage && /^data:image\/(png|gif|jpe?g|webp|bmp);base64,[a-z0-9+/=]*$/.test(v);
}

function safeStyle(value: string): boolean {
  const v = value.replace(/\\[0-9a-fA-F]{1,6}\s?/g, "?").replace(/[\s\\]/g, "").toLowerCase();
  if (/expression\(|javascript:|vbscript:|behavior:|-moz-binding|@import|<\/?\w/.test(v)) return false;
  for (const m of v.matchAll(/url\((['"]?)(.*?)\1\)/g)) {
    if (!safeUrl(m[2], true)) return false;
  }
  return true;
}

function cleanAttr(tag: string, name: string, raw: string): string | null {
  if (!(GLOBAL_ATTRS.has(name) || TAG_ATTRS[tag]?.has(name))) return null;
  const value = decodeEntities(raw);
  if (URL_ATTRS.has(name) && !safeUrl(value, tag === "img" && name === "src")) return null;
  if (name === "style" && !safeStyle(value)) return null;
  if (name === "target" && !/^_(blank|self|parent|top)$/i.test(value)) return null;
  return value;
}

interface Tag { end: boolean; name: string; attrs: [string, string][]; next: number }

function readTag(html: string, i: number): Tag | null {
  // i points at "<"; returns null when this "<" does not start a tag (then it is text)
  let j = i + 1;
  const end = html[j] === "/";
  if (end) j++;
  const nm = /^[A-Za-z][^\s/>\u0000]*/.exec(html.slice(j, j + 64));
  if (!nm) return null;
  const name = nm[0].toLowerCase();
  j += nm[0].length;
  const attrs: [string, string][] = [];
  const n = html.length;
  while (j < n) {
    while (j < n && /[\s/]/.test(html[j])) j++;
    if (j >= n || html[j] === ">") break;
    let k = j;
    while (k < n && !/[\s/>=]/.test(html[k])) k++;
    if (k === j) k++;                             // a lone "=" : skip it
    const an = html.slice(j, k).toLowerCase();
    j = k;
    while (j < n && /\s/.test(html[j])) j++;
    let value = "";
    if (html[j] === "=") {
      j++;
      while (j < n && /\s/.test(html[j])) j++;
      const q = html[j];
      if (q === '"' || q === "'") {
        const close = html.indexOf(q, j + 1);
        value = html.slice(j + 1, close < 0 ? n : close);
        j = close < 0 ? n : close + 1;
      } else {
        let k2 = j;
        while (k2 < n && !/[\s>]/.test(html[k2])) k2++;
        value = html.slice(j, k2);
        j = k2;
      }
    }
    if (an && !attrs.some(([x]) => x === an)) attrs.push([an, value]);
  }
  return { end, name, attrs, next: Math.min(j + 1, n) };
}

export function sanitizeHtml(html: string): string {
  const out: string[] = [];
  const n = html.length;
  let i = 0;
  while (i < n) {
    const lt = html.indexOf("<", i);
    if (lt < 0) { out.push(escapeText(html.slice(i))); break; }
    if (lt > i) out.push(escapeText(html.slice(i, lt)));
    i = lt;
    if (html.startsWith("<!--", i)) {                 // comment (also conditional comments)
      const close = html.indexOf("-->", i + 4);
      i = close < 0 ? n : close + 3;
      continue;
    }
    if (html[i + 1] === "!" || html[i + 1] === "?") {  // doctype, CDATA, processing instruction
      const close = html.indexOf(">", i + 2);
      i = close < 0 ? n : close + 1;
      continue;
    }
    const tag = readTag(html, i);
    if (!tag) { out.push("&lt;"); i++; continue; }
    i = tag.next;
    if (!tag.end && DROP_WITH_CONTENT.has(tag.name)) {
      const re = new RegExp(`</${tag.name}[\\s/>]`, "ig");
      re.lastIndex = i;
      const m = re.exec(html);
      if (!m) { i = n; continue; }
      const close = html.indexOf(">", m.index);
      i = close < 0 ? n : close + 1;
      continue;
    }
    if (!ALLOWED_TAGS.has(tag.name)) continue;      // unknown tag: drop the tag, keep its text
    if (tag.end) {
      if (!VOID_TAGS.has(tag.name)) out.push(`</${tag.name}>`);
      continue;
    }
    const blank = tag.name === "a" && tag.attrs.some(([an, av]) => an === "target" && decodeEntities(av).toLowerCase() === "_blank");
    const attrs: string[] = [];
    for (const [an, av] of tag.attrs) {
      if (blank && an === "rel") continue;
      const v = cleanAttr(tag.name, an, av);
      if (v !== null) attrs.push(` ${an}="${escapeAttr(v)}"`);
    }
    if (blank) attrs.push(' rel="noopener noreferrer"');
    out.push(`<${tag.name}${attrs.join("")}>`);
  }
  return out.join("");
}
