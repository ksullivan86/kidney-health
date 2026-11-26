/* Kidney Diet Log — reading a recipe: the browser twin of app/recipe_import/parse.py (design note 30 §3).

   The server reads web pages; the demo uses these functions on its built-in sample recipe and on pasted ingredients, and the
   iPhone app with no server on a page it fetched (ldJsonBlocks, pageRecipe). Pure functions, no DOM, no I/O: a page is only a
   string here. Tests: tests/data/lists_recipes_vectors.json and recipe_page_vectors.json (generated from the server's own code)
   through `node tests/js/run_vectors.mjs`. Entities: numeric ones as HTML 5 says, and the HTML 4 names (the server knows every
   HTML 5 name).

   Exposes KH.recipeImport = { MAX_LINES, MAX_BLOCKS, MAX_BLOCK_CHARS, ldJsonBlocks, pageRecipe, MAX_LINE_CHARS, MAX_STEPS, MAX_STEP_CHARS, textOf, findRecipe, yieldOf, splitStep, stepsOf,
   ingredientLines, isHeading, linesOfText, recipeFromJsonld, normaliseLine, takeQuantity, takeUnit, parseLine, stem, searchTerms,
   servingQuantity, recipeServings }. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  const MAX_LINES = 60;
  const MAX_LINE_CHARS = 300;
  const MAX_NAME_CHARS = 200;
  const MAX_STEPS = 20;
  const MAX_STEP_CHARS = 500;
  const MAX_TEXT_CHARS = 4000;
  const MAX_DEPTH = 6;
  const MAX_SERVINGS_MADE = 100;

  // ---- Text ----
  const TAG = /<[^<>]*>/g; // twin of parse._TAG
  const SPACE = /\s+/g;
  const PY_SPACES = /[^\S\uFEFF]+/g; // Python's \s for text read from a page (JavaScript's \s also takes U+FEFF)
  const SPACE_BEFORE_MARK = / ([.,;:!?)])/g;
  const CONTROL = /[\u0000-\u001f\u007f-\u009f]/g;
  // Entities (twin of Python's html.unescape): numeric references with the HTML 5 rules for invalid ones, and named ones from
  // the HTML 4 list plus &apos; and the capital forms, with the legacy names that work without a ";" (longest first, as in HTML 5).
  // A name outside this list stays as typed; Python knows every HTML 5 name (tests/data/recipe_page_vectors.json pins the list).
  const ENTITY_TABLE = 'AElig:c6 AMP:26 Aacute:c1 Acirc:c2 Agrave:c0 Alpha:391 Aring:c5 Atilde:c3 Auml:c4 Beta:392 COPY:a9 Ccedil:c7 '
    + 'Chi:3a7 Dagger:2021 Delta:394 ETH:d0 Eacute:c9 Ecirc:ca Egrave:c8 Epsilon:395 Eta:397 Euml:cb GT:3e Gamma:393 '
    + 'Iacute:cd Icirc:ce Igrave:cc Iota:399 Iuml:cf Kappa:39a LT:3c Lambda:39b Mu:39c Ntilde:d1 Nu:39d OElig:152 '
    + 'Oacute:d3 Ocirc:d4 Ograve:d2 Omega:3a9 Omicron:39f Oslash:d8 Otilde:d5 Ouml:d6 Phi:3a6 Pi:3a0 Prime:2033 Psi:3a8 '
    + 'QUOT:22 REG:ae Rho:3a1 Scaron:160 Sigma:3a3 THORN:de Tau:3a4 Theta:398 Uacute:da Ucirc:db Ugrave:d9 Upsilon:3a5 '
    + 'Uuml:dc Xi:39e Yacute:dd Yuml:178 Zeta:396 aacute:e1 acirc:e2 acute:b4 aelig:e6 agrave:e0 alefsym:2135 alpha:3b1 '
    + 'amp:26 and:2227 ang:2220 apos:27 aring:e5 asymp:2248 atilde:e3 auml:e4 bdquo:201e beta:3b2 brvbar:a6 bull:2022 '
    + 'cap:2229 ccedil:e7 cedil:b8 cent:a2 chi:3c7 circ:2c6 clubs:2663 cong:2245 copy:a9 crarr:21b5 cup:222a curren:a4 '
    + 'dArr:21d3 dagger:2020 darr:2193 deg:b0 delta:3b4 diams:2666 divide:f7 eacute:e9 ecirc:ea egrave:e8 empty:2205 '
    + 'emsp:2003 ensp:2002 epsilon:3b5 equiv:2261 eta:3b7 eth:f0 euml:eb euro:20ac exist:2203 fnof:192 forall:2200 '
    + 'frac12:bd frac14:bc frac34:be frasl:2044 gamma:3b3 ge:2265 gt:3e hArr:21d4 harr:2194 hearts:2665 hellip:2026 '
    + 'iacute:ed icirc:ee iexcl:a1 igrave:ec image:2111 infin:221e int:222b iota:3b9 iquest:bf isin:2208 iuml:ef '
    + 'kappa:3ba lArr:21d0 lambda:3bb lang:27e8 laquo:ab larr:2190 lceil:2308 ldquo:201c le:2264 lfloor:230a lowast:2217 '
    + 'loz:25ca lrm:200e lsaquo:2039 lsquo:2018 lt:3c macr:af mdash:2014 micro:b5 middot:b7 minus:2212 mu:3bc nabla:2207 '
    + 'nbsp:a0 ndash:2013 ne:2260 ni:220b not:ac notin:2209 nsub:2284 ntilde:f1 nu:3bd oacute:f3 ocirc:f4 oelig:153 '
    + 'ograve:f2 oline:203e omega:3c9 omicron:3bf oplus:2295 or:2228 ordf:aa ordm:ba oslash:f8 otilde:f5 otimes:2297 '
    + 'ouml:f6 para:b6 part:2202 permil:2030 perp:22a5 phi:3c6 pi:3c0 piv:3d6 plusmn:b1 pound:a3 prime:2032 prod:220f '
    + 'prop:221d psi:3c8 quot:22 rArr:21d2 radic:221a rang:27e9 raquo:bb rarr:2192 rceil:2309 rdquo:201d real:211c reg:ae '
    + 'rfloor:230b rho:3c1 rlm:200f rsaquo:203a rsquo:2019 sbquo:201a scaron:161 sdot:22c5 sect:a7 shy:ad sigma:3c3 '
    + 'sigmaf:3c2 sim:223c spades:2660 sub:2282 sube:2286 sum:2211 sup:2283 sup1:b9 sup2:b2 sup3:b3 supe:2287 szlig:df '
    + 'tau:3c4 there4:2234 theta:3b8 thetasym:3d1 thinsp:2009 thorn:fe tilde:2dc times:d7 trade:2122 uArr:21d1 uacute:fa '
    + 'uarr:2191 ucirc:fb ugrave:f9 uml:a8 upsih:3d2 upsilon:3c5 uuml:fc weierp:2118 xi:3be yacute:fd yen:a5 yuml:ff '
    + 'zeta:3b6 zwj:200d zwnj:200c';
  const LEGACY_NAMES = 'AElig AMP Aacute Acirc Agrave Aring Atilde Auml COPY Ccedil ETH Eacute Ecirc Egrave Euml GT Iacute Icirc Igrave '
    + 'Iuml LT Ntilde Oacute Ocirc Ograve Oslash Otilde Ouml QUOT REG THORN Uacute Ucirc Ugrave Uuml Yacute aacute acirc '
    + 'acute aelig agrave amp aring atilde auml brvbar ccedil cedil cent copy curren deg divide eacute ecirc egrave eth '
    + 'euml frac12 frac14 frac34 gt iacute icirc iexcl igrave iquest iuml laquo lt macr micro middot nbsp not ntilde '
    + 'oacute ocirc ograve ordf ordm oslash otilde ouml para plusmn pound quot raquo reg sect shy sup1 sup2 sup3 szlig '
    + 'thorn times uacute ucirc ugrave uml uuml yacute yen yuml';
  const ENTITIES = new Map(ENTITY_TABLE.split(' ').map((pair) => { const [k, v] = pair.split(':'); return [`${k};`, String.fromCodePoint(parseInt(v, 16))]; }));
  for (const k of LEGACY_NAMES.split(' ')) ENTITIES.set(k, ENTITIES.get(`${k};`));
  const INVALID_CHARREFS = { 0x00: '�', 0x0d: '\r', 0x80: '€', 0x81: '\x81', 0x82: '‚', 0x83: 'ƒ', 0x84: '„',
    0x85: '…', 0x86: '†', 0x87: '‡', 0x88: 'ˆ', 0x89: '‰', 0x8a: 'Š', 0x8b: '‹', 0x8c: 'Œ',
    0x8d: '\x8d', 0x8e: 'Ž', 0x8f: '\x8f', 0x90: '\x90', 0x91: '‘', 0x92: '’', 0x93: '“', 0x94: '”',
    0x95: '•', 0x96: '–', 0x97: '—', 0x98: '˜', 0x99: '™', 0x9a: 'š', 0x9b: '›', 0x9c: 'œ',
    0x9d: '\x9d', 0x9e: 'ž', 0x9f: 'Ÿ' };
  const invalidCodepoint = (n) => (n >= 0x1 && n <= 0x8) || n === 0xb || (n >= 0xe && n <= 0x1f) || (n >= 0x7f && n <= 0x9f)
    || (n >= 0xfdd0 && n <= 0xfdef) || (n & 0xfffe) === 0xfffe;
  const CHARREF = /&(#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\t\n\f <&#;]{1,32};?)/g; // html._charref
  function unescapeHtml(text) {
    if (!text.includes('&')) return text;
    return text.replace(CHARREF, (all, s) => {
      if (s[0] === '#') {
        const hex = s[1] === 'x' || s[1] === 'X';
        const digits = s.slice(hex ? 2 : 1).replace(/;$/, '');
        const n = hex ? parseInt(digits, 16) : parseInt(digits, 10);
        if (Object.prototype.hasOwnProperty.call(INVALID_CHARREFS, n)) return INVALID_CHARREFS[n];
        if ((n >= 0xd800 && n <= 0xdfff) || !(n <= 0x10ffff)) return '�';
        if (invalidCodepoint(n)) return '';
        return String.fromCodePoint(n);
      }
      if (ENTITIES.has(s)) return ENTITIES.get(s);
      const cps = Array.from(s); // the longest name that is a whole entity, then the rest as typed
      for (let x = cps.length - 1; x > 1; x -= 1) {
        const head = cps.slice(0, x).join('');
        if (ENTITIES.has(head)) return ENTITIES.get(head) + cps.slice(x).join('');
      }
      return `&${s}`;
    });
  }
  // Python counts and strips by code point and has its own idea of white space (no U+FEFF; str.isspace).
  const PY_SPACE = '\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
  const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, 'g');
  const pyStrip = (s) => s.replace(PY_STRIP, '');
  const ASTRAL = /[\uD800-\uDBFF][\uDC00-\uDFFF]/;
  const cpLen = (s) => (ASTRAL.test(s) ? Array.from(s).length : s.length);
  const cpSlice = (s, n) => (s.length <= n || !ASTRAL.test(s) ? s.slice(0, n) : Array.from(s).slice(0, n).join(''));
  const isStr = (v) => typeof v === 'string';
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  function textOf(value) {
    if (!isStr(value) && !isNum(value)) return '';
    let text = cpSlice(String(value), MAX_TEXT_CHARS);
    text = unescapeHtml(text.replace(TAG, ' '));
    text = text.replace(CONTROL, ' ');
    return pyStrip(text.replace(PY_SPACES, ' ').replace(SPACE_BEFORE_MARK, '$1'));
  }
  const isObj = (v) => v != null && typeof v === 'object' && !Array.isArray(v);

  // ---- The page (twin of parse.ld_json_blocks, which reads it with Python's html.parser) ----
  // Used on the iPhone, which reads the page itself (design note 30 §3.3; ARCHITECTURE.md "Device mode"). A small port of
  // html.parser's tokenizer (Python 3.13): the same tags, comments, declarations and raw-text elements, so the same
  // The JSON-LD script blocks (type "application/ld+json") are found. Nothing goes into a document and nothing on the page runs: the page is
  // only a string here, and each block is read with JSON.parse.
  const MAX_BLOCKS = 20;
  const MAX_BLOCK_CHARS = 1048576;
  const CDATA_ELEMENTS = ['script', 'style', 'xmp', 'iframe', 'noembed', 'noframes'];
  const RCDATA_ELEMENTS = ['textarea', 'title'];
  const STARTTAGOPEN = /<[a-zA-Z]/y;
  const ENDTAGOPEN = /<\/[a-zA-Z]/y;
  const COMMENTCLOSE = /--!?>/g;
  const COMMENTABRUPTCLOSE = /-?>/y;
  const TAGFIND = /([a-zA-Z][^\t\n\r\f />]*)(?:[\t\n\r\f ]|\/(?!>))*/y;
  const ATTRFIND = /((?<=['"\t\n\r\f /])[^\t\n\r\f />][^\t\n\r\f /=>]*)([\t\n\r\f ]*=[\t\n\r\f ]*('[^']*'|"[^"]*"|(?!['"])[^>\t\n\r\f ]*))?(?:[\t\n\r\f ]|\/(?!>))*/y;
  const LOCATETAGEND = /[a-zA-Z][^\t\n\r\f />]*[\t\n\r\f /]*(?:(?<=['"\t\n\r\f /])[^\t\n\r\f />][^\t\n\r\f /=>]*(?:[\t\n\r\f ]*=[\t\n\r\f ]*(?:'[^']*'|"[^"]*"|(?!['"])[^>\t\n\r\f ]*))?[\t\n\r\f /]*)*>?/y;
  const ATTR_CHARREF = /&(#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*)[;=]?/g;
  function at(re, text, i) { re.lastIndex = i; return re.exec(text); }
  // html.parser._unescape_attrvalue: numeric references always, a name only when it is a whole entity and not followed by "=".
  const unescapeAttr = (value) => value.replace(ATTR_CHARREF, (ref) => (ref.startsWith('&#') || (!ref.endsWith('=') && ENTITIES.has(ref.slice(1)))
    ? unescapeHtml(ref) : ref));

  class LdJsonReader {
    constructor() {
      this.raw = '';
      this.cdata = null; // the raw-text element we are in (html.parser cdata_elem)
      this.endOf = null; // its end tag: "<", "/", the name, then space, "/" or ">"; any case of ASCII letters
      this.blocks = [];
      this.buf = null;
      this.size = 0;
    }
    // The handlers of parse._LdJson
    starttag(tag, attrs) {
      if (tag !== 'script' || this.blocks.length >= MAX_BLOCKS) return;
      const found = attrs.find(([k]) => k === 'type');
      const kind = found ? found[1] || '' : '';
      if (pyStrip(kind.split(';')[0]).toLowerCase() === 'application/ld+json') { this.buf = []; this.size = 0; }
    }
    data(text) {
      if (this.buf !== null && this.size <= MAX_BLOCK_CHARS) { this.buf.push(text); this.size += cpLen(text); }
    }
    endtag(tag) {
      if (tag === 'script' && this.buf !== null) {
        if (this.size <= MAX_BLOCK_CHARS) this.blocks.push(this.buf.join(''));
        this.buf = null;
      }
    }
    setCdata(tag) { this.cdata = tag; this.endOf = tag === 'plaintext' ? null : new RegExp(`<\/${tag}(?=[\\t\\n\\r\\f />])`, 'gi'); }
    // HTMLParser.goahead with convert_charrefs=True (text outside raw-text elements is not needed here, so it is not unescaped)
    goahead(end) {
      const raw = this.raw;
      const n = raw.length;
      let i = 0;
      while (i < n) {
        let j;
        if (!this.cdata) {
          j = raw.indexOf('<', i);
          if (j < 0) {
            const from = Math.max(i, n - 34);
            const amp = raw.lastIndexOf('&');
            if (amp >= from && !/[\t\n\r\f ;]/.test(raw.slice(amp))) break;
            j = n;
          }
        } else if (this.cdata === 'plaintext') {
          j = n;
        } else {
          const m = at(this.endOf, raw, i);
          if (!m) break;
          j = m.index;
        }
        if (i < j) this.data(raw.slice(i, j));
        i = j;
        if (i === n) break;
        let k;
        if (at(STARTTAGOPEN, raw, i)) k = this.parseStarttag(i);
        else if (raw.startsWith('<\/', i)) k = this.parseEndtag(i);
        else if (raw.startsWith('<\u0021--', i)) k = this.parseComment(i);
        else if (raw.startsWith('<?', i)) k = this.parseUntil(i, '>', 2);
        else if (raw.startsWith('<!', i)) k = this.parseDeclaration(i);
        else if (i + 1 < n || end) { this.data('<'); k = i + 1; } else break;
        if (k < 0) {
          if (!end) break;
          if (!at(STARTTAGOPEN, raw, i) && raw.startsWith('<\/', i) && i + 2 === n) this.data('<\/');
          k = n; // the rest is a comment, a declaration or an unfinished tag
        }
        i = k;
      }
      if (end && i < n) { this.data(raw.slice(i, n)); i = n; }
      this.raw = raw.slice(i);
    }
    parseUntil(i, close, skip) { const pos = this.raw.indexOf(close, i + skip); return pos < 0 ? -1 : pos + close.length; }
    parseComment(i) {
      const raw = this.raw;
      let m = at(COMMENTABRUPTCLOSE, raw, i + 4);
      if (!m) { m = at(COMMENTCLOSE, raw, i + 4); if (!m) return -1; }
      return m.index + m[0].length;
    }
    parseDeclaration(i) {
      const raw = this.raw;
      if (raw.startsWith('<\u0021--', i)) return this.parseComment(i);
      if (raw.startsWith('<![CDATA[', i)) return this.parseUntil(i, ']]>', 9);
      if (raw.slice(i, i + 9).toLowerCase() === '<!doctype') return this.parseUntil(i, '>', 9);
      return this.parseUntil(i, '>', 2); // a bogus comment
    }
    parseStarttag(i) {
      const raw = this.raw;
      const whole = at(LOCATETAGEND, raw, i + 1);
      const endpos = whole.index + whole[0].length;
      if (raw[endpos - 1] !== '>') return -1;
      const name = at(TAGFIND, raw, i + 1);
      let k = name.index + name[0].length;
      const tag = name[1].toLowerCase();
      const attrs = [];
      while (k < endpos) {
        const m = at(ATTRFIND, raw, k);
        if (!m) break;
        let value = m[2] ? m[3] : null;
        if (value && ((value[0] === "'" && value.endsWith("'")) || (value[0] === '"' && value.endsWith('"')))) value = value.slice(1, -1);
        if (value) value = unescapeAttr(value);
        attrs.push([m[1].toLowerCase(), value]);
        k = m.index + m[0].length;
      }
      const rest = pyStrip(raw.slice(k, endpos));
      if (rest !== '>' && rest !== '/>') { this.data(raw.slice(i, endpos)); return endpos; }
      if (rest.endsWith('/>')) { this.starttag(tag, attrs); this.endtag(tag); return endpos; }
      this.starttag(tag, attrs);
      if (CDATA_ELEMENTS.includes(tag) || tag === 'plaintext' || RCDATA_ELEMENTS.includes(tag)) this.setCdata(tag);
      return endpos;
    }
    parseEndtag(i) {
      const raw = this.raw;
      if (raw.indexOf('>', i + 2) < 0) return -1;
      if (!at(ENDTAGOPEN, raw, i)) return raw[i + 2] === '>' ? i + 3 : this.parseUntil(i, '>', 2);
      const whole = at(LOCATETAGEND, raw, i + 2);
      const j = whole.index + whole[0].length;
      if (raw[j - 1] !== '>') return -1;
      this.endtag(at(TAGFIND, raw, i + 2)[1].toLowerCase());
      this.cdata = null; this.endOf = null;
      return j;
    }
  }
  // Python's json.loads also takes NaN, Infinity and -Infinity; here they are read as null (a yield or text of them is empty).
  function jsonLoads(text) {
    try { return [true, JSON.parse(text)]; } catch (e) { /* below */ }
    if (!/NaN|Infinity/.test(text)) return [false, null];
    const fixed = text.replace(/"(?:[^"\\]|\\.)*"|-?Infinity|NaN/g, (t) => (t[0] === '"' ? t : 'null'));
    try { return [true, JSON.parse(fixed)]; } catch (e) { return [false, null]; }
  }
  /** The JSON values of the page's application/ld+json scripts; a block that is not JSON is left out. */
  function ldJsonBlocks(page) {
    const reader = new LdJsonReader();
    try {
      reader.raw = String(page || '');
      reader.goahead(false);
      reader.goahead(true);
    } catch (e) { /* as the server: what was read so far counts */ }
    const out = [];
    for (const block of reader.blocks) { const [ok, value] = jsonLoads(pyStrip(block)); if (ok) out.push(value); }
    return out;
  }
  /** The first Recipe in the page's blocks (app/recipe_import/api.py from_page), or null. */
  function pageRecipe(page) {
    for (const block of ldJsonBlocks(page)) { const found = findRecipe(block); if (found) return found; }
    return null;
  }

  // ---- The page's Recipe ----
  function isRecipe(node) {
    if (!isObj(node)) return false;
    const kinds = Array.isArray(node['@type']) ? node['@type'] : [node['@type']];
    return kinds.some((k) => isStr(k) && k.split('/').pop().split(':').pop() === 'Recipe');
  }
  function findRecipe(node, depth = 0) {
    if (depth > MAX_DEPTH) return null;
    if (Array.isArray(node)) {
      for (const item of node.slice(0, 200)) { const found = findRecipe(item, depth + 1); if (found) return found; }
      return null;
    }
    if (!isObj(node)) return null;
    if (isRecipe(node)) return node;
    for (const key of ['@graph', 'mainEntity']) {
      if (key in node) { const found = findRecipe(node[key], depth + 1); if (found) return found; }
    }
    return null;
  }
  function yieldOf(value) {
    if (Array.isArray(value)) {
      for (const item of value.slice(0, 10)) { const got = yieldOf(item); if (got != null) return got; }
      return null;
    }
    let n;
    if (typeof value === 'number') n = value;
    else if (isStr(value)) {
      const m = /[0-9]+(?:\.[0-9]+)?/.exec(value.slice(0, 200));
      if (!m) return null;
      n = parseFloat(m[0]);
    } else return null;
    if (!Number.isFinite(n) || !(n > 0 && n <= MAX_SERVINGS_MADE)) return null;
    return n;
  }
  function splitStep(text) {
    if (cpLen(text) <= MAX_STEP_CHARS) return [text];
    // By code point, as Python does: a text with emoji is counted the same on both sides.
    const out = [];
    let current = [];
    for (const part of text.split(/(?<=[.!?])[^\S\uFEFF]+/)) {
      let sentence = Array.from(part);
      while (sentence.length > MAX_STEP_CHARS) {
        let cut = sentence.lastIndexOf(' ', MAX_STEP_CHARS);
        cut = cut > 0 ? cut : MAX_STEP_CHARS;
        if (current.length) { out.push(current.join('')); current = []; }
        out.push(pyStrip(sentence.slice(0, cut).join('')));
        sentence = Array.from(pyStrip(sentence.slice(cut).join('')));
      }
      if (!sentence.length) continue;
      if (current.length && current.length + 1 + sentence.length <= MAX_STEP_CHARS) current = [...current, ' ', ...sentence];
      else { if (current.length) out.push(current.join('')); current = sentence; }
    }
    if (current.length) out.push(current.join(''));
    return out.filter(Boolean);
  }
  function stepTexts(node, depth, out) {
    if (depth > MAX_DEPTH || out.length > 200) return;
    if (isStr(node)) { for (const part of node.split('\n')) { const t = textOf(part); if (t) out.push(t); } return; }
    if (Array.isArray(node)) { for (const item of node.slice(0, 200)) stepTexts(item, depth + 1, out); return; }
    if (!isObj(node)) return;
    if ('itemListElement' in node) { stepTexts(node.itemListElement, depth + 1, out); return; }
    const t = textOf(node.text) || textOf(node.name);
    if (t) out.push(t);
  }
  function stepsOf(value) {
    const texts = [];
    stepTexts(value, 0, texts);
    const steps = [];
    for (const t of texts) steps.push(...splitStep(t));
    return [steps.slice(0, MAX_STEPS), steps.length > MAX_STEPS];
  }
  function ingredientLines(value) {
    const items = Array.isArray(value) ? value : isStr(value) ? [value] : [];
    const lines = [];
    for (const item of items.slice(0, 500)) { const t = textOf(item); if (t) lines.push(cpSlice(t, MAX_LINE_CHARS)); }
    return [lines.slice(0, MAX_LINES), lines.length > MAX_LINES];
  }
  function isHeading(line) { return line.endsWith(':') && !/[0-9]/.test(line); }
  function linesOfText(text) {
    const lines = (text || '').split('\n').map((raw) => normaliseLine(raw).slice(0, MAX_LINE_CHARS)).filter((l) => l && !isHeading(l));
    return [lines.slice(0, MAX_LINES), lines.length > MAX_LINES];
  }
  function recipeFromJsonld(recipe) {
    const name = pyStrip(cpSlice(textOf(recipe.name), MAX_NAME_CHARS)) || null;
    const rawLines = recipe.recipeIngredient != null ? recipe.recipeIngredient : recipe.ingredients;
    const [lines, linesCut] = ingredientLines(rawLines);
    const [steps, stepsCut] = stepsOf(recipe.recipeInstructions);
    return { name, servings_made: yieldOf(recipe.recipeYield), steps, steps_cut: stepsCut, lines, lines_cut: linesCut };
  }

  // ---- Ingredient lines ----
  const FRACTION_CHARS = { '½': '1/2', '⅓': '1/3', '⅔': '2/3', '¼': '1/4', '¾': '3/4', '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
    '⅙': '1/6', '⅚': '5/6', '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8' };
  const FRACTION_RE = new RegExp(`([0-9]?)([${Object.keys(FRACTION_CHARS).join('')}])`, 'g');
  const NUMBER_WORDS = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, half: 0.5 };
  const ARTICLE_WORDS = ['a', 'an'];
  const UNITS = {
    fl_oz: ['fluid ounces', 'fluid ounce', 'fl. oz', 'fl oz', 'floz'],
    g: ['grams', 'gram', 'gms', 'gm', 'gr', 'g'],
    kg: ['kilograms', 'kilogram', 'kgs', 'kg'],
    oz: ['ounces', 'ounce', 'oz'],
    lb: ['pounds', 'pound', 'lbs', 'lb'],
    ml: ['millilitres', 'milliliters', 'millilitre', 'milliliter', 'mls', 'ml'],
    l: ['litres', 'liters', 'litre', 'liter', 'l'],
    cup: ['cups', 'cup', 'c'],
    tbsp: ['tablespoons', 'tablespoon', 'tbsps', 'tbsp', 'tbs', 'tbl'],
    tsp: ['teaspoons', 'teaspoon', 'tsps', 'tsp'],
    pinch: ['pinches', 'pinch'],
    dash: ['dashes', 'dash'],
    clove: ['cloves', 'clove'],
    slice: ['slices', 'slice'],
    piece: ['pieces', 'piece'],
    can: ['cans', 'can', 'tins', 'tin'],
  };
  const UNIT_WORDS = Object.entries(UNITS).flatMap(([u, ws]) => ws.map((w) => [w, u]))
    .sort((a, b) => (b[0].length - a[0].length) || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  const CONTAINERS = ['cans', 'can', 'tins', 'tin', 'packages', 'package', 'pkgs', 'pkg', 'jars', 'jar', 'bags', 'bag', 'boxes', 'box',
    'cartons', 'carton', 'bottles', 'bottle', 'packets', 'packet', 'containers', 'container'];
  const MASS_G = { g: 1.0, kg: 1000.0, oz: 28.349523125, lb: 453.59237 };
  const VOLUME_ML = { ml: 1.0, l: 1000.0, cup: 236.5882365, tbsp: 14.78676478125, tsp: 4.92892159375, fl_oz: 29.5735295625 };
  const COUNT_UNITS = ['piece', 'slice', 'clove', 'can'];
  const has = (obj, k) => k != null && Object.prototype.hasOwnProperty.call(obj, k);

  const NUM = '[0-9]{1,3}(?:,[0-9]{3})+(?![0-9])|[0-9]+(?:\\.[0-9]+|,[0-9]{1,2}(?![0-9]))?'; // "1,000", "1.5", "1,5"
  const THOUSANDS = /^[0-9]{1,3}(?:,[0-9]{3})+$/;
  const QTY = new RegExp(`^(?:([0-9]+)\\s+([0-9]+)\\s*/\\s*([0-9]+)|([0-9]+)\\s*/\\s*([0-9]+)|(${NUM}))`);
  const RANGE_WORDS = ['-', '–', '—', 'to', 'or'];
  const PARENS = /\([^()]*\)/g; // twin of parse._PARENS
  // twin of parse._range_end: where a range's second number starts, or null (no regex, so spaces cannot make it slow)
  function rangeEnd(rest) {
    const s = rest.trimStart();
    const start = rest.length - s.length;
    for (const sep of RANGE_WORDS) {
      if (!s.startsWith(sep)) continue;
      const after = s.slice(sep.length);
      const tail = after.trimStart();
      if (tail && '0123456789'.includes(tail[0])) return start + sep.length + after.length - tail.length;
    }
    return null;
  }
  // twin of parse._leading_word: [word, end] for ASCII letters followed by a word break, end past the spaces after it
  function leadingWord(text) {
    const m = /^[A-Za-z]+/.exec(text);
    if (!m) return null;
    const end = m[0].length;
    if (end < text.length && /\w/.test(text[end])) return null;
    const after = text.slice(end);
    return [m[0], end + after.length - after.trimStart().length];
  }
  const BULLET = /^[\s\-*•▢□☐·]+/;

  function normaliseLine(raw) {
    let text = (raw || '').replace(CONTROL, ' ').replace(SPACE, ' ').trim();
    text = text.replace(BULLET, '');
    text = text.replace(FRACTION_RE, (all, digit, ch) => (digit ? `${digit} ` : '') + FRACTION_CHARS[ch]);
    return text.replace(/⁄/g, '/').replace(SPACE, ' ').trim();
  }
  function numberOf(m) {
    if (m[1] !== undefined) { const den = parseInt(m[3], 10); return den ? parseInt(m[1], 10) + parseInt(m[2], 10) / den : null; }
    if (m[4] !== undefined) { const den = parseInt(m[5], 10); return den ? parseInt(m[4], 10) / den : null; }
    return parseFloat(THOUSANDS.test(m[6]) ? m[6].replace(/,/g, '') : m[6].replace(',', '.'));
  }
  function takeQuantity(text) {
    const m = QTY.exec(text);
    if (!m) return [null, text];
    const value = numberOf(m);
    let rest = text.slice(m[0].length);
    const ranged = rangeEnd(rest);
    if (ranged != null) {
      const second = QTY.exec(rest.slice(ranged));
      if (second) rest = rest.slice(ranged + second[0].length);
    }
    return [value, rest.replace(/^\s+/, '')];
  }
  function takeUnit(text) {
    const low = text.toLowerCase();
    for (const [word, unit] of UNIT_WORDS) {
      if (!low.startsWith(word)) continue;
      let after = low.slice(word.length);
      if (after.startsWith('.')) after = after.slice(1);
      if (after === '' || ' ,;)/'.includes(after[0])) {
        let rest = text.slice(text.length - after.length).replace(/^\s+/, '');
        if (rest.toLowerCase().startsWith('of ')) rest = rest.slice(3).replace(/^\s+/, '');
        return [unit, rest];
      }
    }
    return [null, text];
  }
  function wordNumber(text) {
    const found = leadingWord(text);
    if (!found) return [null, text, false];
    const word = found[0].toLowerCase();
    if (has(NUMBER_WORDS, word)) return [NUMBER_WORDS[word], text.slice(found[1]), false];
    if (ARTICLE_WORDS.includes(word)) return [1, text.slice(found[1]), true];
    return [null, text, false];
  }
  function packageSize(text) {
    const m = /^\([^()]*\)/.exec(text);
    const inner = m ? m[0].slice(1, -1).trim() : text;
    let rest = m ? text.slice(m[0].length).trimStart() : '';
    let [size, after] = takeQuantity(inner);
    if (size == null) return null;
    if (after.startsWith('-')) after = after.slice(1).replace(/^\s+/, '');
    let unit;
    [unit, after] = takeUnit(after);
    if (unit == null || (!has(MASS_G, unit) && !has(VOLUME_ML, unit))) return null;
    if (!m) rest = after;
    else if (after.trim()) return null;
    const word = leadingWord(rest);
    if (!word || !CONTAINERS.includes(word[0].toLowerCase())) return null;
    return [size, unit, rest.slice(word[1])];
  }
  function stripChars(text, chars) {
    let a = 0, b = text.length;
    while (a < b && chars.includes(text[a])) a += 1;
    while (b > a && chars.includes(text[b - 1])) b -= 1;
    return text.slice(a, b);
  }
  function parseLine(raw) {
    const text = normaliseLine(raw).slice(0, MAX_LINE_CHARS);
    let [amount, rest] = takeQuantity(text);
    let article = false;
    if (amount == null) [amount, rest, article] = wordNumber(text);
    let unit = null;
    if (amount != null) {
      const pkg = packageSize(rest);
      if (pkg) { const [size, u, r] = pkg; unit = u; rest = r; amount *= size; } else {
        [unit, rest] = takeUnit(rest);
        if (unit == null && article) { amount = null; rest = text; } else if (unit != null && rest.startsWith('/')) {
          const [other, after1] = takeQuantity(rest.slice(1).replace(/^\s+/, ''));
          const [otherUnit, after2] = other != null ? takeUnit(after1) : [null, after1];
          if (otherUnit != null) rest = after2;
        }
      }
    } else { unit = null; rest = text; }
    const comma = rest.indexOf(',');
    const head = comma < 0 ? rest : rest.slice(0, comma);
    const tail = comma < 0 ? '' : rest.slice(comma + 1);
    let food = stripChars(head.replace(PARENS, ' ').replace(SPACE, ' '), ' .;:-');
    let note = tail.trim() || null;
    if (!food && note) { food = note; note = null; }
    return { text, amount, unit, food_text: food, note };
  }

  // ---- Search words ----
  const DROP_PHRASES = ['to taste', 'for serving', 'for garnish', 'for frying', 'as needed', 'if desired', 'plus more', 'at room temperature',
    'or more', 'optional', 'divided'];
  const STOP_WORDS = new Set([
    'of', 'and', 'the', 'a', 'an', 'with', 'without', 'into', 'in', 'for', 'to', 'about', 'plus', 'more', 'taste', 'some',
    'fresh', 'freshly', 'large', 'medium', 'small', 'extra', 'big', 'chopped', 'diced', 'minced', 'sliced', 'grated', 'shredded',
    'peeled', 'crushed', 'finely', 'roughly', 'coarsely', 'thinly', 'thickly', 'cut', 'cubed', 'cubes', 'pieces', 'piece',
    'halved', 'quartered', 'trimmed', 'rinsed', 'drained', 'packed', 'softened', 'melted', 'beaten', 'boneless', 'skinless',
    'uncooked', 'raw', 'organic', 'ripe', 'clove', 'cloves', 'sprig', 'sprigs', 'handful', 'pinch', 'dash', 'heaping', 'level',
    'generous', 'good', 'quality', 'can', 'cans', 'package', 'jar', 'bunch', 'head', 'stalk', 'stalks', 'inch', 'inches', 'few',
    'dried', 'virgin', 'lean', 'bone', 'skin',
  ]);
  const WORD = /[a-zà-ÿ]+/g;
  function stem(word) {
    if (word.length > 4 && word.endsWith('ies')) return word.slice(0, -3);
    if (word.length > 4 && word.endsWith('oes')) return word.slice(0, -2);
    if (['ches', 'shes', 'sses', 'xes'].some((e) => word.endsWith(e))) return word.slice(0, -2);
    if (word.length > 3 && word.endsWith('s') && !['ss', 'us', 'is'].some((e) => word.endsWith(e))) return word.slice(0, -1);
    return word;
  }
  function searchTerms(foodText) {
    let text = (foodText || '').toLowerCase();
    text = text.replace(PARENS, ' ');
    text = text.split(',')[0].split('/')[0];
    const or = /\bor\b/.exec(text);
    if (or) text = text.slice(0, or.index);
    for (const phrase of DROP_PHRASES) text = text.split(phrase).join(' ');
    let words = [];
    for (const raw of text.match(WORD) || []) {
      if (STOP_WORDS.has(raw) || raw.length < 2) continue;
      const w = stem(raw);
      if (!words.includes(w)) words.push(w);
    }
    words = words.slice(-5);
    if (!words.length) return [];
    const out = [];
    for (const q of [words.join(' '), words.slice(-2).join(' '), words[words.length - 1], words[0]]) if (!out.includes(q)) out.push(q);
    return out;
  }

  // ---- Amounts ----
  const SERVING_VOLUME = [['fl oz', 'fl_oz'], ['fluid ounce', 'fl_oz'], ['cups', 'cup'], ['cup', 'cup'], ['tablespoon', 'tbsp'],
    ['tbsp', 'tbsp'], ['teaspoon', 'tsp'], ['tsp', 'tsp'], ['ml', 'ml']];
  const MASS_WORDS = ['oz', 'ounce', 'g', 'gram', 'grams', 'lb', 'pound', 'kg'];
  function servingQuantity(desc) {
    const [qty, rest] = takeQuantity(normaliseLine(desc || ''));
    if (qty == null || !(qty > 0)) return null;
    return [qty, rest.toLowerCase()];
  }
  const round2 = (v) => Math.floor(v * 100 + 0.5) / 100;
  function recipeServings(amount, unit, desc, servingG) {
    if (amount == null || !(amount > 0) || !Number.isFinite(amount)) return null;
    let servings = null;
    if (has(MASS_G, unit)) {
      const grams = Number(servingG || 0);
      if (grams > 0) servings = amount * MASS_G[unit] / grams;
    } else if (has(VOLUME_ML, unit)) {
      const q = servingQuantity(desc);
      if (q) {
        const [qty, rest] = q;
        const hit = SERVING_VOLUME.find(([w]) => rest.startsWith(w));
        if (hit) servings = amount * VOLUME_ML[unit] / (qty * VOLUME_ML[hit[1]]);
      }
    } else if (unit == null || COUNT_UNITS.includes(unit)) {
      const q = servingQuantity(desc);
      if (q) {
        const [qty, rest] = q;
        const m = /^[a-zà-ÿ]+/.exec(rest);
        const word = m ? m[0] : '';
        const fits = unit == null ? (!!word && !MASS_WORDS.includes(word) && !SERVING_VOLUME.some(([w]) => rest.startsWith(w)))
          : stem(word) === unit;
        if (fits) servings = amount / qty;
      }
    }
    if (servings == null) return null;
    const r = round2(servings);
    return r >= 0.01 && r <= 1000 ? r : null;
  }

  KH.recipeImport = { MAX_LINES, MAX_BLOCKS, MAX_BLOCK_CHARS, ldJsonBlocks, pageRecipe, MAX_LINE_CHARS, MAX_STEPS, MAX_STEP_CHARS, textOf, findRecipe, yieldOf, splitStep, stepsOf,
    ingredientLines, isHeading, linesOfText, recipeFromJsonld, normaliseLine, takeQuantity, takeUnit, parseLine, stem, searchTerms,
    servingQuantity, recipeServings };
})();
