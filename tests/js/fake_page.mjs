// A small stand-in for the page, enough to run one real view module in node:vm (tests/js/*_late_reply.test.mjs).
// Elements keep children, attributes, listeners, value, hidden and disabled; `$('#id')` makes the element on first use, so a
// module finds every id it expects. Selectors: '#id', 'tag', '.class', 'tag.class', and lists of them joined by commas.
export const deferred = () => {
  let resolve, reject;
  const promise = new Promise((ok, bad) => { resolve = ok; reject = bad; });
  return { promise, resolve, reject };
};
export const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); await new Promise((r) => setTimeout(r, 0)); };

export function makePage() {
  const byId = new Map();
  let active = null;
  class Text {
    constructor(t) { this.nodeType = 3; this.data = String(t); this.parent = null; }
    get textContent() { return this.data; }
  }
  class El {
    constructor(tag) {
      this.nodeType = 1; this.tag = String(tag).toLowerCase(); this.attrs = {}; this.children = []; this.handlers = {}; this.parent = null;
      this.hidden = false; this.disabled = false; this.value = ''; this.checked = false; this.open = false; this.files = null;
      this.dataset = {}; this.style = {}; this.tabIndex = 0; this.focused = false;
      const classes = new Set();
      this.classList = { add: (...c) => c.forEach((x) => classes.add(x)), remove: (...c) => c.forEach((x) => classes.delete(x)),
        toggle: (c, on) => { const want = on === undefined ? !classes.has(c) : !!on; if (want) classes.add(c); else classes.delete(c); return want; },
        contains: (c) => classes.has(c), _set: classes };
    }
    get id() { return this.attrs.id || ''; }
    set id(v) { this.attrs.id = v; }
    get className() { return [...this.classList._set].join(' '); }
    setAttribute(k, v) {
      this.attrs[k] = String(v);
      if (k === 'class') { this.classList._set.clear(); String(v).split(/\s+/).filter(Boolean).forEach((c) => this.classList._set.add(c)); }
      if (k === 'id') byId.set(String(v), this);
    }
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
    removeAttribute(k) { delete this.attrs[k]; }
    hasAttribute(k) { return k in this.attrs; }
    append(...kids) {
      for (const k of kids.flat(Infinity)) {
        if (k == null || k === false) continue;
        const node = typeof k === 'object' && k.nodeType ? k : new Text(k);
        if (node.nodeType === 11) { for (const c of [...node.children]) this.append(c); node.children = []; continue; }
        if (node.parent) node.parent.children = node.parent.children.filter((c) => c !== node);
        node.parent = this; this.children.push(node);
      }
    }
    appendChild(k) { this.append(k); return k; }
    replaceChildren(...kids) { for (const c of this.children) c.parent = null; this.children = []; this.append(...kids); }
    replaceWith(node) { const p = this.parent; if (!p) return; const i = p.children.indexOf(this); if (node.parent) node.parent.children = node.parent.children.filter((c) => c !== node); node.parent = p; p.children[i] = node; this.parent = null; }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; }
    get firstChild() { return this.children[0] || null; }
    removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parent = null; return c; }
    get lastElementChild() { const els = this.children.filter((c) => c.nodeType === 1); return els[els.length - 1] || null; }
    get isConnected() { let n = this; while (n.parent) n = n.parent; return n === root; }
    get textContent() { return this.children.map((c) => c.textContent).join(''); }
    set textContent(v) { for (const c of this.children) c.parent = null; this.children = []; if (v !== '' && v != null) this.append(String(v)); }
    addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
    removeEventListener(type, fn) { this.handlers[type] = (this.handlers[type] || []).filter((f) => f !== fn); }
    dispatchEvent(ev) { const e = ev || {}; e.target ||= this; e.currentTarget = this; for (const fn of [...(this.handlers[e.type] || [])]) fn(e); return true; }
    fire(type, extra = {}) { return this.dispatchEvent({ type, preventDefault() {}, stopPropagation() {}, ...extra }); }
    click() { if (this.disabled) return; this.fire('click'); }
    focus() { this.focused = true; active = this; }
    blur() { this.focused = false; }
    select() {}
    scrollIntoView() {}
    showModal() { this.open = true; }
    close() { if (!this.open) return; this.open = false; this.fire('close'); }
    closest() { return this.parent || this; }
    matches(sel) { return matches(this, sel); }
    querySelector(sel) { return all(this, sel)[0] || null; }
    querySelectorAll(sel) { return all(this, sel); }
    contains(node) { for (let n = node; n; n = n.parent) if (n === this) return true; return false; }
  }
  const simple = (el, sel) => {
    const m = /^([a-z0-9]*)((?:[.#][\w-]+)*)$/i.exec(sel.trim());
    if (!m) return false;
    if (m[1] && el.tag !== m[1].toLowerCase()) return false;
    for (const part of m[2].match(/[.#][\w-]+/g) || []) {
      if (part[0] === '#' && el.id !== part.slice(1)) return false;
      if (part[0] === '.' && !el.classList.contains(part.slice(1))) return false;
    }
    return true;
  };
  const matches = (el, sel) => sel.split(',').some((s) => simple(el, s));
  const all = (from, sel, out = []) => { for (const c of from.children) { if (c.nodeType !== 1) continue; if (matches(c, sel)) out.push(c); all(c, sel, out); } return out; };
  const root = new El('body');
  const $ = (sel, scope) => {
    if (scope) return scope.querySelector(sel);
    if (/^#[\w-]+$/.test(sel)) {
      const id = sel.slice(1);
      if (!byId.has(id)) { const el = new El(/input|search|code|name|servings|serving|gtin|ingredients|photo|file|^q-|^qn-/.test(id) ? 'input' : 'div'); el.setAttribute('id', id); root.append(el); }
      return byId.get(id);
    }
    return root.querySelector(sel);
  };
  const $$ = (sel, scope) => (scope || root).querySelectorAll(sel);
  const h = (tag, attrs, ...children) => {
    const el = new El(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
    el.append(...children);
    return el;
  };
  const clear = (el) => { el.replaceChildren(); return el; };
  const text = (node) => (node == null ? '' : node.textContent.replace(/\s+/g, ' ').trim());
  const find = (from, pred, out = []) => { for (const c of from.children || []) { if (c.nodeType !== 1) continue; if (pred(c)) out.push(c); find(c, pred, out); } return out; };
  const button = (from, label) => find(from, (e) => e.tag === 'button' && text(e) === label)[0] || null;
  const document = {
    createElement: (t) => new El(t), createElementNS: (_ns, t) => new El(t), createTextNode: (t) => new Text(t),
    createDocumentFragment: () => { const f = new El('#fragment'); f.nodeType = 11; return f; },
    contains: (n) => !!n && root.contains(n), querySelector: (s) => root.querySelector(s), querySelectorAll: (s) => root.querySelectorAll(s),
    addEventListener() {}, removeEventListener() {}, get activeElement() { return active; }, visibilityState: 'visible', body: root,
  };
  class Event { constructor(type, opts = {}) { this.type = type; Object.assign(this, opts); } preventDefault() {} stopPropagation() {} }
  return { El, Text, root, $, $$, h, clear, text, find, button, document, Event };
}
