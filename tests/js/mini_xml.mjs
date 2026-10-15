// A small XML parser for the Node tests of js/engine/ccda_labs.js: DEV ONLY, nothing in app/ loads it.
//
// In the browser the engine gets its Document from `new DOMParser().parseFromString(text, 'application/xml')`. Node has no DOMParser and
// the repo takes no npm dependency, so the vectors (tests/js/gen_ccda_labs_vectors.mjs, tests/js/run_vectors.mjs) and the page harness
// (tests/js/ccda_labs_page.mjs) hand the engine this stand-in through its `parseXml` option. It implements only the part of the DOM
// the engine reads, with the same names and the same answers a browser gives for it:
//   document.documentElement, document.getElementsByTagName(name)
//   element.localName, .namespaceURI, .prefix, .tagName, .children (the child ELEMENTS), .getAttribute(qname), .getAttributeNS(ns, local)
// and, like a browser, it does not throw on a malformed document: it returns a document whose root is a <parsererror> element
// (Firefox's shape), which is what the engine looks for. Like the engine's own rule it never accepts a DTD: <!DOCTYPE and <!ENTITY are
// errors here (a browser would not fetch anything either, but the engine refuses such a file before it ever gets this far).
//
// It checks what XML 1.0 asks of a document the engine could be given: one root element, matching end tags, quoted attribute values
// without "<", no duplicate attributes, only the five predefined entities and numeric references, declared namespace prefixes, an XML
// declaration only at the very start, nothing but whitespace, comments and processing instructions outside the root.
const XMLNS = 'http://www.w3.org/2000/xmlns/';
const XML_NS = 'http://www.w3.org/XML/1998/namespace';
const PARSER_ERROR_NS = 'http://www.mozilla.org/newlayout/xml/parsererror.xml';

class XmlError extends Error {}

class Element {
  constructor(qname, namespaceURI, attrs, parent) {
    const i = qname.indexOf(':');
    this.tagName = qname;
    this.prefix = i < 0 ? null : qname.slice(0, i);
    this.localName = i < 0 ? qname : qname.slice(i + 1);
    this.namespaceURI = namespaceURI;
    this.parentElement = parent;
    this.children = [];
    this._attrs = attrs;
  }

  getAttribute(qname) {
    const a = this._attrs.find((x) => x.name === qname);
    return a ? a.value : null;
  }

  getAttributeNS(ns, local) {
    const a = this._attrs.find((x) => x.local === local && x.ns === (ns || null));
    return a ? a.value : null;
  }

  hasAttribute(qname) {
    return this.getAttribute(qname) !== null;
  }
}

class Document {
  constructor(documentElement) {
    this.documentElement = documentElement;
  }

  getElementsByTagName(qname) {
    const out = [];
    const stack = [this.documentElement];
    while (stack.length) {
      const el = stack.pop();
      if (qname === '*' || el.tagName === qname) out.push(el);
      for (let i = el.children.length - 1; i >= 0; i--) stack.push(el.children[i]);
    }
    return out;
  }
}

function errorDocument(message) {
  const root = new Element('parsererror', PARSER_ERROR_NS, [], null);
  root.message = message;
  return new Document(root);
}

const NAME = /[A-Za-z_][A-Za-z0-9_.-]*(?::[A-Za-z_][A-Za-z0-9_.-]*)?/y;
const PREDEFINED = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" };

// The text with its references resolved, or an XmlError (an unknown entity, a bad numeric reference).
function decode(text) {
  return text.replace(/&(#x[0-9A-Fa-f]+|#[0-9]+|[A-Za-z][A-Za-z0-9]*);/g, (all, ref) => {
    if (ref[0] === '#') {
      const code = ref[1] === 'x' ? parseInt(ref.slice(2), 16) : parseInt(ref.slice(1), 10);
      if (!(code === 9 || code === 10 || code === 13 || (code >= 0x20 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff) && code !== 0xfffe && code !== 0xffff))) throw new XmlError(`bad character reference ${all}`);
      return String.fromCodePoint(code);
    }
    if (!(ref in PREDEFINED)) throw new XmlError(`undefined entity ${all}`);
    return PREDEFINED[ref];
  });
}

function parse(text) {
  try {
    return parseOrThrow(String(text));
  } catch (e) {
    if (!(e instanceof XmlError)) throw e;
    return errorDocument(e.message);
  }
}

function parseOrThrow(s) {
  let i = 0;
  const fail = (why) => { throw new XmlError(`${why} at ${i}`); };
  const stack = []; // open elements
  let root = null;
  const base = new Map([['xml', XML_NS]]);
  const scopeStack = []; // the namespace prefixes in scope inside each open element

  if (s.startsWith('<?xml') && /^<\?xml[\s?]/.test(s)) {
    const end = s.indexOf('?>');
    if (end < 0) fail('unterminated XML declaration');
    if (!/^<\?xml\s+version\s*=\s*(["'])1\.[0-9]+\1(\s+encoding\s*=\s*(["'])[A-Za-z][A-Za-z0-9._-]*\3)?(\s+standalone\s*=\s*(["'])(yes|no)\5)?\s*\?>/.test(s.slice(0, end + 2))) fail('bad XML declaration');
    i = end + 2;
  }

  while (i < s.length) {
    if (s[i] !== '<') { // character data
      const next = s.indexOf('<', i);
      const end = next < 0 ? s.length : next;
      const chunk = s.slice(i, end);
      if (chunk.includes(']]>')) fail('"]]>" in text');
      decode(chunk); // an undefined entity is an error even in text we do not keep
      if (!stack.length && chunk.trim()) fail('text outside the root element');
      i = end;
      continue;
    }
    if (s.startsWith('<!--', i)) {
      const end = s.indexOf('-->', i + 4);
      if (end < 0) fail('unterminated comment');
      if (s.slice(i + 4, end).includes('--')) fail('"--" in a comment');
      i = end + 3;
    } else if (s.startsWith('<![CDATA[', i)) {
      if (!stack.length) fail('CDATA outside the root element');
      const end = s.indexOf(']]>', i + 9);
      if (end < 0) fail('unterminated CDATA');
      i = end + 3;
    } else if (s.startsWith('<?', i)) {
      const end = s.indexOf('?>', i + 2);
      if (end < 0) fail('unterminated processing instruction');
      if (/^<\?xml[\s?]/i.test(s.slice(i, i + 6))) fail('XML declaration not at the start');
      i = end + 2;
    } else if (s.startsWith('<!', i)) {
      fail('a DTD, DOCTYPE or ENTITY is not accepted');
    } else if (s.startsWith('</', i)) {
      NAME.lastIndex = i + 2;
      const m = NAME.exec(s);
      if (!m) fail('bad end tag');
      i = NAME.lastIndex;
      while (/\s/.test(s[i] || '')) i++;
      if (s[i] !== '>') fail('bad end tag');
      i++;
      const open = stack.pop();
      scopeStack.pop();
      if (!open || open.tagName !== m[0]) fail(`end tag ${m[0]} does not match`);
    } else { // a start tag
      NAME.lastIndex = i + 1;
      const m = NAME.exec(s);
      if (!m) fail('bad start tag');
      const qname = m[0];
      i = NAME.lastIndex;
      const raw = [];
      let selfClosing = false;
      for (;;) {
        const space = /\s*/y;
        space.lastIndex = i;
        space.exec(s);
        const hadSpace = space.lastIndex > i;
        i = space.lastIndex;
        if (s[i] === '>') { i++; break; }
        if (s[i] === '/' && s[i + 1] === '>') { i += 2; selfClosing = true; break; }
        if (!hadSpace) fail('attributes need a space before them');
        NAME.lastIndex = i;
        const a = NAME.exec(s);
        if (!a) fail('bad attribute name');
        i = NAME.lastIndex;
        const eq = /\s*=\s*/y;
        eq.lastIndex = i;
        if (!eq.exec(s)) fail('attribute without a value');
        i = eq.lastIndex;
        const quote = s[i];
        if (quote !== '"' && quote !== "'") fail('unquoted attribute value');
        const end = s.indexOf(quote, i + 1);
        if (end < 0) fail('unterminated attribute value');
        const value = s.slice(i + 1, end);
        if (value.includes('<')) fail('"<" in an attribute value');
        if (raw.some((r) => r.name === a[0])) fail(`duplicate attribute ${a[0]}`);
        raw.push({ name: a[0], value: decode(value).replace(/[\t\n\r]/g, ' ') });
        i = end + 1;
      }
      // namespace declarations first, then the element's and the attributes' own namespaces
      const scope = new Map(scopeStack.length ? scopeStack[scopeStack.length - 1] : base);
      for (const a of raw) {
        if (a.name === 'xmlns') scope.set('', a.value);
        else if (a.name.startsWith('xmlns:')) scope.set(a.name.slice(6), a.value);
      }
      const colon = qname.indexOf(':');
      const prefix = colon < 0 ? '' : qname.slice(0, colon);
      if (prefix && !scope.has(prefix)) fail(`undeclared prefix ${prefix}`);
      const attrs = raw.map((a) => {
        const c = a.name.indexOf(':');
        const isDecl = a.name === 'xmlns' || a.name.startsWith('xmlns:');
        const p = c < 0 ? '' : a.name.slice(0, c);
        if (!isDecl && p && !scope.has(p)) fail(`undeclared prefix ${p}`);
        return { name: a.name, local: c < 0 ? a.name : a.name.slice(c + 1), ns: isDecl ? XMLNS : p ? scope.get(p) : null, value: a.value };
      });
      const parent = stack[stack.length - 1] || null;
      if (!parent && root) fail('more than one root element');
      const el = new Element(qname, scope.get(prefix) || null, attrs, parent);
      if (parent) parent.children.push(el); else root = el;
      if (!selfClosing) {
        stack.push(el);
        scopeStack.push(scope);
      }
    }
  }
  if (stack.length) fail(`unclosed element ${stack[stack.length - 1].tagName}`);
  if (!root) fail('no root element');
  return new Document(root);
}

export { parse, Element, Document };
