var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key2, value) => key2 in obj ? __defProp(obj, key2, { enumerable: true, configurable: true, writable: true, value }) : obj[key2] = value;
var __publicField = (obj, key2, value) => __defNormalProp(obj, typeof key2 !== "symbol" ? key2 + "" : key2, value);
(function polyfill() {
  const relList = document.createElement("link").relList;
  if (relList && relList.supports && relList.supports("modulepreload")) {
    return;
  }
  for (const link of document.querySelectorAll('link[rel="modulepreload"]')) {
    processPreload(link);
  }
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type !== "childList") {
        continue;
      }
      for (const node of mutation.addedNodes) {
        if (node.tagName === "LINK" && node.rel === "modulepreload")
          processPreload(node);
      }
    }
  }).observe(document, { childList: true, subtree: true });
  function getFetchOpts(link) {
    const fetchOpts = {};
    if (link.integrity) fetchOpts.integrity = link.integrity;
    if (link.referrerPolicy) fetchOpts.referrerPolicy = link.referrerPolicy;
    if (link.crossOrigin === "use-credentials")
      fetchOpts.credentials = "include";
    else if (link.crossOrigin === "anonymous") fetchOpts.credentials = "omit";
    else fetchOpts.credentials = "same-origin";
    return fetchOpts;
  }
  function processPreload(link) {
    if (link.ep)
      return;
    link.ep = true;
    const fetchOpts = getFetchOpts(link);
    fetch(link.href, fetchOpts);
  }
})();
var n$2, l$1, u$1, i$1, o$1, r$2, f$1, e$3, c$2, s$1, h$1 = {}, p$1 = [], v$1 = /acit|ex(?:s|g|n|p|$)|rph|grid|ows|mnc|ntw|ine[ch]|zoo|^ord|itera/i, y$1 = Array.isArray;
function d$1(n2, l2) {
  for (var u2 in l2) n2[u2] = l2[u2];
  return n2;
}
function w$1(n2) {
  var l2 = n2.parentNode;
  l2 && l2.removeChild(n2);
}
function _(l2, u2, t2) {
  var i2, o2, r2, f2 = {};
  for (r2 in u2) "key" == r2 ? i2 = u2[r2] : "ref" == r2 ? o2 = u2[r2] : f2[r2] = u2[r2];
  if (arguments.length > 2 && (f2.children = arguments.length > 3 ? n$2.call(arguments, 2) : t2), "function" == typeof l2 && null != l2.defaultProps) for (r2 in l2.defaultProps) void 0 === f2[r2] && (f2[r2] = l2.defaultProps[r2]);
  return g(l2, f2, i2, o2, null);
}
function g(n2, t2, i2, o2, r2) {
  var f2 = { type: n2, props: t2, key: i2, ref: o2, __k: null, __: null, __b: 0, __e: null, __d: void 0, __c: null, constructor: void 0, __v: null == r2 ? ++u$1 : r2, __i: -1, __u: 0 };
  return null == r2 && null != l$1.vnode && l$1.vnode(f2), f2;
}
function m$2() {
  return { current: null };
}
function k$1(n2) {
  return n2.children;
}
function b(n2, l2) {
  this.props = n2, this.context = l2;
}
function x(n2, l2) {
  if (null == l2) return n2.__ ? x(n2.__, n2.__i + 1) : null;
  for (var u2; l2 < n2.__k.length; l2++) if (null != (u2 = n2.__k[l2]) && null != u2.__e) return u2.__e;
  return "function" == typeof n2.type ? x(n2) : null;
}
function C$1(n2) {
  var l2, u2;
  if (null != (n2 = n2.__) && null != n2.__c) {
    for (n2.__e = n2.__c.base = null, l2 = 0; l2 < n2.__k.length; l2++) if (null != (u2 = n2.__k[l2]) && null != u2.__e) {
      n2.__e = n2.__c.base = u2.__e;
      break;
    }
    return C$1(n2);
  }
}
function M(n2) {
  (!n2.__d && (n2.__d = true) && i$1.push(n2) && !P.__r++ || o$1 !== l$1.debounceRendering) && ((o$1 = l$1.debounceRendering) || r$2)(P);
}
function P() {
  var n2, u2, t2, o2, r2, e2, c2, s2;
  for (i$1.sort(f$1); n2 = i$1.shift(); ) n2.__d && (u2 = i$1.length, o2 = void 0, e2 = (r2 = (t2 = n2).__v).__e, c2 = [], s2 = [], t2.__P && ((o2 = d$1({}, r2)).__v = r2.__v + 1, l$1.vnode && l$1.vnode(o2), O(t2.__P, o2, r2, t2.__n, t2.__P.namespaceURI, 32 & r2.__u ? [e2] : null, c2, null == e2 ? x(r2) : e2, !!(32 & r2.__u), s2), o2.__v = r2.__v, o2.__.__k[o2.__i] = o2, j$1(c2, o2, s2), o2.__e != e2 && C$1(o2)), i$1.length > u2 && i$1.sort(f$1));
  P.__r = 0;
}
function S(n2, l2, u2, t2, i2, o2, r2, f2, e2, c2, s2) {
  var a2, v2, y2, d2, w2, _2 = t2 && t2.__k || p$1, g2 = l2.length;
  for (u2.__d = e2, $(u2, l2, _2), e2 = u2.__d, a2 = 0; a2 < g2; a2++) null != (y2 = u2.__k[a2]) && "boolean" != typeof y2 && "function" != typeof y2 && (v2 = -1 === y2.__i ? h$1 : _2[y2.__i] || h$1, y2.__i = a2, O(n2, y2, v2, i2, o2, r2, f2, e2, c2, s2), d2 = y2.__e, y2.ref && v2.ref != y2.ref && (v2.ref && N(v2.ref, null, y2), s2.push(y2.ref, y2.__c || d2, y2)), null == w2 && null != d2 && (w2 = d2), 65536 & y2.__u || v2.__k === y2.__k ? e2 = I(y2, e2, n2) : "function" == typeof y2.type && void 0 !== y2.__d ? e2 = y2.__d : d2 && (e2 = d2.nextSibling), y2.__d = void 0, y2.__u &= -196609);
  u2.__d = e2, u2.__e = w2;
}
function $(n2, l2, u2) {
  var t2, i2, o2, r2, f2, e2 = l2.length, c2 = u2.length, s2 = c2, a2 = 0;
  for (n2.__k = [], t2 = 0; t2 < e2; t2++) r2 = t2 + a2, null != (i2 = n2.__k[t2] = null == (i2 = l2[t2]) || "boolean" == typeof i2 || "function" == typeof i2 ? null : "string" == typeof i2 || "number" == typeof i2 || "bigint" == typeof i2 || i2.constructor == String ? g(null, i2, null, null, null) : y$1(i2) ? g(k$1, { children: i2 }, null, null, null) : void 0 === i2.constructor && i2.__b > 0 ? g(i2.type, i2.props, i2.key, i2.ref ? i2.ref : null, i2.__v) : i2) ? (i2.__ = n2, i2.__b = n2.__b + 1, f2 = L(i2, u2, r2, s2), i2.__i = f2, o2 = null, -1 !== f2 && (s2--, (o2 = u2[f2]) && (o2.__u |= 131072)), null == o2 || null === o2.__v ? (-1 == f2 && a2--, "function" != typeof i2.type && (i2.__u |= 65536)) : f2 !== r2 && (f2 == r2 - 1 ? a2 = f2 - r2 : f2 == r2 + 1 ? a2++ : f2 > r2 ? s2 > e2 - r2 ? a2 += f2 - r2 : a2-- : f2 < r2 && a2++, f2 !== t2 + a2 && (i2.__u |= 65536))) : (o2 = u2[r2]) && null == o2.key && o2.__e && 0 == (131072 & o2.__u) && (o2.__e == n2.__d && (n2.__d = x(o2)), V(o2, o2, false), u2[r2] = null, s2--);
  if (s2) for (t2 = 0; t2 < c2; t2++) null != (o2 = u2[t2]) && 0 == (131072 & o2.__u) && (o2.__e == n2.__d && (n2.__d = x(o2)), V(o2, o2));
}
function I(n2, l2, u2) {
  var t2, i2;
  if ("function" == typeof n2.type) {
    for (t2 = n2.__k, i2 = 0; t2 && i2 < t2.length; i2++) t2[i2] && (t2[i2].__ = n2, l2 = I(t2[i2], l2, u2));
    return l2;
  }
  n2.__e != l2 && (l2 && n2.type && !u2.contains(l2) && (l2 = x(n2)), u2.insertBefore(n2.__e, l2 || null), l2 = n2.__e);
  do {
    l2 = l2 && l2.nextSibling;
  } while (null != l2 && 8 === l2.nodeType);
  return l2;
}
function L(n2, l2, u2, t2) {
  var i2 = n2.key, o2 = n2.type, r2 = u2 - 1, f2 = u2 + 1, e2 = l2[u2];
  if (null === e2 || e2 && i2 == e2.key && o2 === e2.type && 0 == (131072 & e2.__u)) return u2;
  if (t2 > (null != e2 && 0 == (131072 & e2.__u) ? 1 : 0)) for (; r2 >= 0 || f2 < l2.length; ) {
    if (r2 >= 0) {
      if ((e2 = l2[r2]) && 0 == (131072 & e2.__u) && i2 == e2.key && o2 === e2.type) return r2;
      r2--;
    }
    if (f2 < l2.length) {
      if ((e2 = l2[f2]) && 0 == (131072 & e2.__u) && i2 == e2.key && o2 === e2.type) return f2;
      f2++;
    }
  }
  return -1;
}
function T$1(n2, l2, u2) {
  "-" === l2[0] ? n2.setProperty(l2, null == u2 ? "" : u2) : n2[l2] = null == u2 ? "" : "number" != typeof u2 || v$1.test(l2) ? u2 : u2 + "px";
}
function A$1(n2, l2, u2, t2, i2) {
  var o2;
  n: if ("style" === l2) if ("string" == typeof u2) n2.style.cssText = u2;
  else {
    if ("string" == typeof t2 && (n2.style.cssText = t2 = ""), t2) for (l2 in t2) u2 && l2 in u2 || T$1(n2.style, l2, "");
    if (u2) for (l2 in u2) t2 && u2[l2] === t2[l2] || T$1(n2.style, l2, u2[l2]);
  }
  else if ("o" === l2[0] && "n" === l2[1]) o2 = l2 !== (l2 = l2.replace(/(PointerCapture)$|Capture$/i, "$1")), l2 = l2.toLowerCase() in n2 || "onFocusOut" === l2 || "onFocusIn" === l2 ? l2.toLowerCase().slice(2) : l2.slice(2), n2.l || (n2.l = {}), n2.l[l2 + o2] = u2, u2 ? t2 ? u2.u = t2.u : (u2.u = e$3, n2.addEventListener(l2, o2 ? s$1 : c$2, o2)) : n2.removeEventListener(l2, o2 ? s$1 : c$2, o2);
  else {
    if ("http://www.w3.org/2000/svg" == i2) l2 = l2.replace(/xlink(H|:h)/, "h").replace(/sName$/, "s");
    else if ("width" != l2 && "height" != l2 && "href" != l2 && "list" != l2 && "form" != l2 && "tabIndex" != l2 && "download" != l2 && "rowSpan" != l2 && "colSpan" != l2 && "role" != l2 && "popover" != l2 && l2 in n2) try {
      n2[l2] = null == u2 ? "" : u2;
      break n;
    } catch (n3) {
    }
    "function" == typeof u2 || (null == u2 || false === u2 && "-" !== l2[4] ? n2.removeAttribute(l2) : n2.setAttribute(l2, "popover" == l2 && 1 == u2 ? "" : u2));
  }
}
function F(n2) {
  return function(u2) {
    if (this.l) {
      var t2 = this.l[u2.type + n2];
      if (null == u2.t) u2.t = e$3++;
      else if (u2.t < t2.u) return;
      return t2(l$1.event ? l$1.event(u2) : u2);
    }
  };
}
function O(n2, u2, t2, i2, o2, r2, f2, e2, c2, s2) {
  var a2, h2, p2, v2, w2, _2, g2, m2, x2, C2, M2, P2, $2, I2, H, L2, T2 = u2.type;
  if (void 0 !== u2.constructor) return null;
  128 & t2.__u && (c2 = !!(32 & t2.__u), r2 = [e2 = u2.__e = t2.__e]), (a2 = l$1.__b) && a2(u2);
  n: if ("function" == typeof T2) try {
    if (m2 = u2.props, x2 = "prototype" in T2 && T2.prototype.render, C2 = (a2 = T2.contextType) && i2[a2.__c], M2 = a2 ? C2 ? C2.props.value : a2.__ : i2, t2.__c ? g2 = (h2 = u2.__c = t2.__c).__ = h2.__E : (x2 ? u2.__c = h2 = new T2(m2, M2) : (u2.__c = h2 = new b(m2, M2), h2.constructor = T2, h2.render = q$1), C2 && C2.sub(h2), h2.props = m2, h2.state || (h2.state = {}), h2.context = M2, h2.__n = i2, p2 = h2.__d = true, h2.__h = [], h2._sb = []), x2 && null == h2.__s && (h2.__s = h2.state), x2 && null != T2.getDerivedStateFromProps && (h2.__s == h2.state && (h2.__s = d$1({}, h2.__s)), d$1(h2.__s, T2.getDerivedStateFromProps(m2, h2.__s))), v2 = h2.props, w2 = h2.state, h2.__v = u2, p2) x2 && null == T2.getDerivedStateFromProps && null != h2.componentWillMount && h2.componentWillMount(), x2 && null != h2.componentDidMount && h2.__h.push(h2.componentDidMount);
    else {
      if (x2 && null == T2.getDerivedStateFromProps && m2 !== v2 && null != h2.componentWillReceiveProps && h2.componentWillReceiveProps(m2, M2), !h2.__e && (null != h2.shouldComponentUpdate && false === h2.shouldComponentUpdate(m2, h2.__s, M2) || u2.__v === t2.__v)) {
        for (u2.__v !== t2.__v && (h2.props = m2, h2.state = h2.__s, h2.__d = false), u2.__e = t2.__e, u2.__k = t2.__k, u2.__k.forEach(function(n3) {
          n3 && (n3.__ = u2);
        }), P2 = 0; P2 < h2._sb.length; P2++) h2.__h.push(h2._sb[P2]);
        h2._sb = [], h2.__h.length && f2.push(h2);
        break n;
      }
      null != h2.componentWillUpdate && h2.componentWillUpdate(m2, h2.__s, M2), x2 && null != h2.componentDidUpdate && h2.__h.push(function() {
        h2.componentDidUpdate(v2, w2, _2);
      });
    }
    if (h2.context = M2, h2.props = m2, h2.__P = n2, h2.__e = false, $2 = l$1.__r, I2 = 0, x2) {
      for (h2.state = h2.__s, h2.__d = false, $2 && $2(u2), a2 = h2.render(h2.props, h2.state, h2.context), H = 0; H < h2._sb.length; H++) h2.__h.push(h2._sb[H]);
      h2._sb = [];
    } else do {
      h2.__d = false, $2 && $2(u2), a2 = h2.render(h2.props, h2.state, h2.context), h2.state = h2.__s;
    } while (h2.__d && ++I2 < 25);
    h2.state = h2.__s, null != h2.getChildContext && (i2 = d$1(d$1({}, i2), h2.getChildContext())), x2 && !p2 && null != h2.getSnapshotBeforeUpdate && (_2 = h2.getSnapshotBeforeUpdate(v2, w2)), S(n2, y$1(L2 = null != a2 && a2.type === k$1 && null == a2.key ? a2.props.children : a2) ? L2 : [L2], u2, t2, i2, o2, r2, f2, e2, c2, s2), h2.base = u2.__e, u2.__u &= -161, h2.__h.length && f2.push(h2), g2 && (h2.__E = h2.__ = null);
  } catch (n3) {
    if (u2.__v = null, c2 || null != r2) {
      for (u2.__u |= c2 ? 160 : 32; e2 && 8 === e2.nodeType && e2.nextSibling; ) e2 = e2.nextSibling;
      r2[r2.indexOf(e2)] = null, u2.__e = e2;
    } else u2.__e = t2.__e, u2.__k = t2.__k;
    l$1.__e(n3, u2, t2);
  }
  else null == r2 && u2.__v === t2.__v ? (u2.__k = t2.__k, u2.__e = t2.__e) : u2.__e = z$1(t2.__e, u2, t2, i2, o2, r2, f2, c2, s2);
  (a2 = l$1.diffed) && a2(u2);
}
function j$1(n2, u2, t2) {
  u2.__d = void 0;
  for (var i2 = 0; i2 < t2.length; i2++) N(t2[i2], t2[++i2], t2[++i2]);
  l$1.__c && l$1.__c(u2, n2), n2.some(function(u3) {
    try {
      n2 = u3.__h, u3.__h = [], n2.some(function(n3) {
        n3.call(u3);
      });
    } catch (n3) {
      l$1.__e(n3, u3.__v);
    }
  });
}
function z$1(l2, u2, t2, i2, o2, r2, f2, e2, c2) {
  var s2, a2, p2, v2, d2, _2, g2, m2 = t2.props, k2 = u2.props, b2 = u2.type;
  if ("svg" === b2 ? o2 = "http://www.w3.org/2000/svg" : "math" === b2 ? o2 = "http://www.w3.org/1998/Math/MathML" : o2 || (o2 = "http://www.w3.org/1999/xhtml"), null != r2) {
    for (s2 = 0; s2 < r2.length; s2++) if ((d2 = r2[s2]) && "setAttribute" in d2 == !!b2 && (b2 ? d2.localName === b2 : 3 === d2.nodeType)) {
      l2 = d2, r2[s2] = null;
      break;
    }
  }
  if (null == l2) {
    if (null === b2) return document.createTextNode(k2);
    l2 = document.createElementNS(o2, b2, k2.is && k2), r2 = null, e2 = false;
  }
  if (null === b2) m2 === k2 || e2 && l2.data === k2 || (l2.data = k2);
  else {
    if (r2 = r2 && n$2.call(l2.childNodes), m2 = t2.props || h$1, !e2 && null != r2) for (m2 = {}, s2 = 0; s2 < l2.attributes.length; s2++) m2[(d2 = l2.attributes[s2]).name] = d2.value;
    for (s2 in m2) if (d2 = m2[s2], "children" == s2) ;
    else if ("dangerouslySetInnerHTML" == s2) p2 = d2;
    else if ("key" !== s2 && !(s2 in k2)) {
      if ("value" == s2 && "defaultValue" in k2 || "checked" == s2 && "defaultChecked" in k2) continue;
      A$1(l2, s2, null, d2, o2);
    }
    for (s2 in k2) d2 = k2[s2], "children" == s2 ? v2 = d2 : "dangerouslySetInnerHTML" == s2 ? a2 = d2 : "value" == s2 ? _2 = d2 : "checked" == s2 ? g2 = d2 : "key" === s2 || e2 && "function" != typeof d2 || m2[s2] === d2 || A$1(l2, s2, d2, m2[s2], o2);
    if (a2) e2 || p2 && (a2.__html === p2.__html || a2.__html === l2.innerHTML) || (l2.innerHTML = a2.__html), u2.__k = [];
    else if (p2 && (l2.innerHTML = ""), S(l2, y$1(v2) ? v2 : [v2], u2, t2, i2, "foreignObject" === b2 ? "http://www.w3.org/1999/xhtml" : o2, r2, f2, r2 ? r2[0] : t2.__k && x(t2, 0), e2, c2), null != r2) for (s2 = r2.length; s2--; ) null != r2[s2] && w$1(r2[s2]);
    e2 || (s2 = "value", void 0 !== _2 && (_2 !== l2[s2] || "progress" === b2 && !_2 || "option" === b2 && _2 !== m2[s2]) && A$1(l2, s2, _2, m2[s2], o2), s2 = "checked", void 0 !== g2 && g2 !== l2[s2] && A$1(l2, s2, g2, m2[s2], o2));
  }
  return l2;
}
function N(n2, u2, t2) {
  try {
    if ("function" == typeof n2) {
      var i2 = "function" == typeof n2.__u;
      i2 && n2.__u(), i2 && null == u2 || (n2.__u = n2(u2));
    } else n2.current = u2;
  } catch (n3) {
    l$1.__e(n3, t2);
  }
}
function V(n2, u2, t2) {
  var i2, o2;
  if (l$1.unmount && l$1.unmount(n2), (i2 = n2.ref) && (i2.current && i2.current !== n2.__e || N(i2, null, u2)), null != (i2 = n2.__c)) {
    if (i2.componentWillUnmount) try {
      i2.componentWillUnmount();
    } catch (n3) {
      l$1.__e(n3, u2);
    }
    i2.base = i2.__P = null;
  }
  if (i2 = n2.__k) for (o2 = 0; o2 < i2.length; o2++) i2[o2] && V(i2[o2], u2, t2 || "function" != typeof n2.type);
  t2 || null == n2.__e || w$1(n2.__e), n2.__c = n2.__ = n2.__e = n2.__d = void 0;
}
function q$1(n2, l2, u2) {
  return this.constructor(n2, u2);
}
function B$1(u2, t2, i2) {
  var o2, r2, f2, e2;
  l$1.__ && l$1.__(u2, t2), r2 = (o2 = "function" == typeof i2) ? null : t2.__k, f2 = [], e2 = [], O(t2, u2 = (!o2 && i2 || t2).__k = _(k$1, null, [u2]), r2 || h$1, h$1, t2.namespaceURI, !o2 && i2 ? [i2] : r2 ? null : t2.firstChild ? n$2.call(t2.childNodes) : null, f2, !o2 && i2 ? i2 : r2 ? r2.__e : t2.firstChild, o2, e2), j$1(f2, u2, e2);
}
n$2 = p$1.slice, l$1 = { __e: function(n2, l2, u2, t2) {
  for (var i2, o2, r2; l2 = l2.__; ) if ((i2 = l2.__c) && !i2.__) try {
    if ((o2 = i2.constructor) && null != o2.getDerivedStateFromError && (i2.setState(o2.getDerivedStateFromError(n2)), r2 = i2.__d), null != i2.componentDidCatch && (i2.componentDidCatch(n2, t2 || {}), r2 = i2.__d), r2) return i2.__E = i2;
  } catch (l3) {
    n2 = l3;
  }
  throw n2;
} }, u$1 = 0, b.prototype.setState = function(n2, l2) {
  var u2;
  u2 = null != this.__s && this.__s !== this.state ? this.__s : this.__s = d$1({}, this.state), "function" == typeof n2 && (n2 = n2(d$1({}, u2), this.props)), n2 && d$1(u2, n2), null != n2 && this.__v && (l2 && this._sb.push(l2), M(this));
}, b.prototype.forceUpdate = function(n2) {
  this.__v && (this.__e = true, n2 && this.__h.push(n2), M(this));
}, b.prototype.render = k$1, i$1 = [], r$2 = "function" == typeof Promise ? Promise.prototype.then.bind(Promise.resolve()) : setTimeout, f$1 = function(n2, l2) {
  return n2.__v.__b - l2.__v.__b;
}, P.__r = 0, e$3 = 0, c$2 = F(false), s$1 = F(true);
var n$1 = function(t2, s2, r2, e2) {
  var u2;
  s2[0] = 0;
  for (var h2 = 1; h2 < s2.length; h2++) {
    var p2 = s2[h2++], a2 = s2[h2] ? (s2[0] |= p2 ? 1 : 2, r2[s2[h2++]]) : s2[++h2];
    3 === p2 ? e2[0] = a2 : 4 === p2 ? e2[1] = Object.assign(e2[1] || {}, a2) : 5 === p2 ? (e2[1] = e2[1] || {})[s2[++h2]] = a2 : 6 === p2 ? e2[1][s2[++h2]] += a2 + "" : p2 ? (u2 = t2.apply(a2, n$1(t2, a2, r2, ["", null])), e2.push(u2), a2[0] ? s2[0] |= 2 : (s2[h2 - 2] = 0, s2[h2] = u2)) : e2.push(a2);
  }
  return e2;
}, t$2 = /* @__PURE__ */ new Map();
function e$2(s2) {
  var r2 = t$2.get(this);
  return r2 || (r2 = /* @__PURE__ */ new Map(), t$2.set(this, r2)), (r2 = n$1(this, r2.get(s2) || (r2.set(s2, r2 = function(n2) {
    for (var t2, s3, r3 = 1, e2 = "", u2 = "", h2 = [0], p2 = function(n3) {
      1 === r3 && (n3 || (e2 = e2.replace(/^\s*\n\s*|\s*\n\s*$/g, ""))) ? h2.push(0, n3, e2) : 3 === r3 && (n3 || e2) ? (h2.push(3, n3, e2), r3 = 2) : 2 === r3 && "..." === e2 && n3 ? h2.push(4, n3, 0) : 2 === r3 && e2 && !n3 ? h2.push(5, 0, true, e2) : r3 >= 5 && ((e2 || !n3 && 5 === r3) && (h2.push(r3, 0, e2, s3), r3 = 6), n3 && (h2.push(r3, n3, 0, s3), r3 = 6)), e2 = "";
    }, a2 = 0; a2 < n2.length; a2++) {
      a2 && (1 === r3 && p2(), p2(a2));
      for (var l2 = 0; l2 < n2[a2].length; l2++) t2 = n2[a2][l2], 1 === r3 ? "<" === t2 ? (p2(), h2 = [h2], r3 = 3) : e2 += t2 : 4 === r3 ? "--" === e2 && ">" === t2 ? (r3 = 1, e2 = "") : e2 = t2 + e2[0] : u2 ? t2 === u2 ? u2 = "" : e2 += t2 : '"' === t2 || "'" === t2 ? u2 = t2 : ">" === t2 ? (p2(), r3 = 1) : r3 && ("=" === t2 ? (r3 = 5, s3 = e2, e2 = "") : "/" === t2 && (r3 < 5 || ">" === n2[a2][l2 + 1]) ? (p2(), 3 === r3 && (h2 = h2[0]), r3 = h2, (h2 = h2[0]).push(2, 0, r3), r3 = 0) : " " === t2 || "	" === t2 || "\n" === t2 || "\r" === t2 ? (p2(), r3 = 2) : e2 += t2), 3 === r3 && "!--" === e2 && (r3 = 4, h2 = h2[0]);
    }
    return p2(), h2;
  }(s2)), r2), arguments, [])).length > 1 ? r2 : r2[0];
}
var m$1 = e$2.bind(_);
var commonjsGlobal = typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : typeof global !== "undefined" ? global : typeof self !== "undefined" ? self : {};
function getDefaultExportFromCjs(x2) {
  return x2 && x2.__esModule && Object.prototype.hasOwnProperty.call(x2, "default") ? x2["default"] : x2;
}
var clipboard = { exports: {} };
/*!
 * clipboard.js v2.0.11
 * https://clipboardjs.com/
 *
 * Licensed MIT © Zeno Rocha
 */
(function(module, exports) {
  (function webpackUniversalModuleDefinition(root2, factory) {
    module.exports = factory();
  })(commonjsGlobal, function() {
    return (
      /******/
      function() {
        var __webpack_modules__ = {
          /***/
          686: (
            /***/
            function(__unused_webpack_module, __webpack_exports__, __webpack_require__2) {
              __webpack_require__2.d(__webpack_exports__, {
                "default": function() {
                  return (
                    /* binding */
                    clipboard2
                  );
                }
              });
              var tiny_emitter = __webpack_require__2(279);
              var tiny_emitter_default = /* @__PURE__ */ __webpack_require__2.n(tiny_emitter);
              var listen = __webpack_require__2(370);
              var listen_default = /* @__PURE__ */ __webpack_require__2.n(listen);
              var src_select = __webpack_require__2(817);
              var select_default = /* @__PURE__ */ __webpack_require__2.n(src_select);
              function command(type) {
                try {
                  return document.execCommand(type);
                } catch (err) {
                  return false;
                }
              }
              var ClipboardActionCut = function ClipboardActionCut2(target) {
                var selectedText = select_default()(target);
                command("cut");
                return selectedText;
              };
              var actions_cut = ClipboardActionCut;
              function createFakeElement(value) {
                var isRTL2 = document.documentElement.getAttribute("dir") === "rtl";
                var fakeElement = document.createElement("textarea");
                fakeElement.style.fontSize = "12pt";
                fakeElement.style.border = "0";
                fakeElement.style.padding = "0";
                fakeElement.style.margin = "0";
                fakeElement.style.position = "absolute";
                fakeElement.style[isRTL2 ? "right" : "left"] = "-9999px";
                var yPosition = window.pageYOffset || document.documentElement.scrollTop;
                fakeElement.style.top = "".concat(yPosition, "px");
                fakeElement.setAttribute("readonly", "");
                fakeElement.value = value;
                return fakeElement;
              }
              var fakeCopyAction = function fakeCopyAction2(value, options) {
                var fakeElement = createFakeElement(value);
                options.container.appendChild(fakeElement);
                var selectedText = select_default()(fakeElement);
                command("copy");
                fakeElement.remove();
                return selectedText;
              };
              var ClipboardActionCopy = function ClipboardActionCopy2(target) {
                var options = arguments.length > 1 && arguments[1] !== void 0 ? arguments[1] : {
                  container: document.body
                };
                var selectedText = "";
                if (typeof target === "string") {
                  selectedText = fakeCopyAction(target, options);
                } else if (target instanceof HTMLInputElement && !["text", "search", "url", "tel", "password"].includes(target === null || target === void 0 ? void 0 : target.type)) {
                  selectedText = fakeCopyAction(target.value, options);
                } else {
                  selectedText = select_default()(target);
                  command("copy");
                }
                return selectedText;
              };
              var actions_copy = ClipboardActionCopy;
              function _typeof(obj) {
                "@babel/helpers - typeof";
                if (typeof Symbol === "function" && typeof Symbol.iterator === "symbol") {
                  _typeof = function _typeof2(obj2) {
                    return typeof obj2;
                  };
                } else {
                  _typeof = function _typeof2(obj2) {
                    return obj2 && typeof Symbol === "function" && obj2.constructor === Symbol && obj2 !== Symbol.prototype ? "symbol" : typeof obj2;
                  };
                }
                return _typeof(obj);
              }
              var ClipboardActionDefault = function ClipboardActionDefault2() {
                var options = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : {};
                var _options$action = options.action, action = _options$action === void 0 ? "copy" : _options$action, container = options.container, target = options.target, text = options.text;
                if (action !== "copy" && action !== "cut") {
                  throw new Error('Invalid "action" value, use either "copy" or "cut"');
                }
                if (target !== void 0) {
                  if (target && _typeof(target) === "object" && target.nodeType === 1) {
                    if (action === "copy" && target.hasAttribute("disabled")) {
                      throw new Error('Invalid "target" attribute. Please use "readonly" instead of "disabled" attribute');
                    }
                    if (action === "cut" && (target.hasAttribute("readonly") || target.hasAttribute("disabled"))) {
                      throw new Error(`Invalid "target" attribute. You can't cut text from elements with "readonly" or "disabled" attributes`);
                    }
                  } else {
                    throw new Error('Invalid "target" value, use a valid Element');
                  }
                }
                if (text) {
                  return actions_copy(text, {
                    container
                  });
                }
                if (target) {
                  return action === "cut" ? actions_cut(target) : actions_copy(target, {
                    container
                  });
                }
              };
              var actions_default = ClipboardActionDefault;
              function clipboard_typeof(obj) {
                "@babel/helpers - typeof";
                if (typeof Symbol === "function" && typeof Symbol.iterator === "symbol") {
                  clipboard_typeof = function _typeof2(obj2) {
                    return typeof obj2;
                  };
                } else {
                  clipboard_typeof = function _typeof2(obj2) {
                    return obj2 && typeof Symbol === "function" && obj2.constructor === Symbol && obj2 !== Symbol.prototype ? "symbol" : typeof obj2;
                  };
                }
                return clipboard_typeof(obj);
              }
              function _classCallCheck(instance, Constructor) {
                if (!(instance instanceof Constructor)) {
                  throw new TypeError("Cannot call a class as a function");
                }
              }
              function _defineProperties(target, props) {
                for (var i2 = 0; i2 < props.length; i2++) {
                  var descriptor = props[i2];
                  descriptor.enumerable = descriptor.enumerable || false;
                  descriptor.configurable = true;
                  if ("value" in descriptor) descriptor.writable = true;
                  Object.defineProperty(target, descriptor.key, descriptor);
                }
              }
              function _createClass(Constructor, protoProps, staticProps) {
                if (protoProps) _defineProperties(Constructor.prototype, protoProps);
                if (staticProps) _defineProperties(Constructor, staticProps);
                return Constructor;
              }
              function _inherits(subClass, superClass) {
                if (typeof superClass !== "function" && superClass !== null) {
                  throw new TypeError("Super expression must either be null or a function");
                }
                subClass.prototype = Object.create(superClass && superClass.prototype, { constructor: { value: subClass, writable: true, configurable: true } });
                if (superClass) _setPrototypeOf(subClass, superClass);
              }
              function _setPrototypeOf(o2, p2) {
                _setPrototypeOf = Object.setPrototypeOf || function _setPrototypeOf2(o3, p3) {
                  o3.__proto__ = p3;
                  return o3;
                };
                return _setPrototypeOf(o2, p2);
              }
              function _createSuper(Derived) {
                var hasNativeReflectConstruct = _isNativeReflectConstruct();
                return function _createSuperInternal() {
                  var Super = _getPrototypeOf(Derived), result;
                  if (hasNativeReflectConstruct) {
                    var NewTarget = _getPrototypeOf(this).constructor;
                    result = Reflect.construct(Super, arguments, NewTarget);
                  } else {
                    result = Super.apply(this, arguments);
                  }
                  return _possibleConstructorReturn(this, result);
                };
              }
              function _possibleConstructorReturn(self2, call) {
                if (call && (clipboard_typeof(call) === "object" || typeof call === "function")) {
                  return call;
                }
                return _assertThisInitialized(self2);
              }
              function _assertThisInitialized(self2) {
                if (self2 === void 0) {
                  throw new ReferenceError("this hasn't been initialised - super() hasn't been called");
                }
                return self2;
              }
              function _isNativeReflectConstruct() {
                if (typeof Reflect === "undefined" || !Reflect.construct) return false;
                if (Reflect.construct.sham) return false;
                if (typeof Proxy === "function") return true;
                try {
                  Date.prototype.toString.call(Reflect.construct(Date, [], function() {
                  }));
                  return true;
                } catch (e2) {
                  return false;
                }
              }
              function _getPrototypeOf(o2) {
                _getPrototypeOf = Object.setPrototypeOf ? Object.getPrototypeOf : function _getPrototypeOf2(o3) {
                  return o3.__proto__ || Object.getPrototypeOf(o3);
                };
                return _getPrototypeOf(o2);
              }
              function getAttributeValue(suffix, element) {
                var attribute = "data-clipboard-".concat(suffix);
                if (!element.hasAttribute(attribute)) {
                  return;
                }
                return element.getAttribute(attribute);
              }
              var Clipboard = /* @__PURE__ */ function(_Emitter) {
                _inherits(Clipboard2, _Emitter);
                var _super = _createSuper(Clipboard2);
                function Clipboard2(trigger, options) {
                  var _this;
                  _classCallCheck(this, Clipboard2);
                  _this = _super.call(this);
                  _this.resolveOptions(options);
                  _this.listenClick(trigger);
                  return _this;
                }
                _createClass(Clipboard2, [{
                  key: "resolveOptions",
                  value: function resolveOptions() {
                    var options = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : {};
                    this.action = typeof options.action === "function" ? options.action : this.defaultAction;
                    this.target = typeof options.target === "function" ? options.target : this.defaultTarget;
                    this.text = typeof options.text === "function" ? options.text : this.defaultText;
                    this.container = clipboard_typeof(options.container) === "object" ? options.container : document.body;
                  }
                  /**
                   * Adds a click event listener to the passed trigger.
                   * @param {String|HTMLElement|HTMLCollection|NodeList} trigger
                   */
                }, {
                  key: "listenClick",
                  value: function listenClick(trigger) {
                    var _this2 = this;
                    this.listener = listen_default()(trigger, "click", function(e2) {
                      return _this2.onClick(e2);
                    });
                  }
                  /**
                   * Defines a new `ClipboardAction` on each click event.
                   * @param {Event} e
                   */
                }, {
                  key: "onClick",
                  value: function onClick(e2) {
                    var trigger = e2.delegateTarget || e2.currentTarget;
                    var action = this.action(trigger) || "copy";
                    var text = actions_default({
                      action,
                      container: this.container,
                      target: this.target(trigger),
                      text: this.text(trigger)
                    });
                    this.emit(text ? "success" : "error", {
                      action,
                      text,
                      trigger,
                      clearSelection: function clearSelection() {
                        if (trigger) {
                          trigger.focus();
                        }
                        window.getSelection().removeAllRanges();
                      }
                    });
                  }
                  /**
                   * Default `action` lookup function.
                   * @param {Element} trigger
                   */
                }, {
                  key: "defaultAction",
                  value: function defaultAction(trigger) {
                    return getAttributeValue("action", trigger);
                  }
                  /**
                   * Default `target` lookup function.
                   * @param {Element} trigger
                   */
                }, {
                  key: "defaultTarget",
                  value: function defaultTarget(trigger) {
                    var selector = getAttributeValue("target", trigger);
                    if (selector) {
                      return document.querySelector(selector);
                    }
                  }
                  /**
                   * Allow fire programmatically a copy action
                   * @param {String|HTMLElement} target
                   * @param {Object} options
                   * @returns Text copied.
                   */
                }, {
                  key: "defaultText",
                  /**
                   * Default `text` lookup function.
                   * @param {Element} trigger
                   */
                  value: function defaultText(trigger) {
                    return getAttributeValue("text", trigger);
                  }
                  /**
                   * Destroy lifecycle.
                   */
                }, {
                  key: "destroy",
                  value: function destroy() {
                    this.listener.destroy();
                  }
                }], [{
                  key: "copy",
                  value: function copy(target) {
                    var options = arguments.length > 1 && arguments[1] !== void 0 ? arguments[1] : {
                      container: document.body
                    };
                    return actions_copy(target, options);
                  }
                  /**
                   * Allow fire programmatically a cut action
                   * @param {String|HTMLElement} target
                   * @returns Text cutted.
                   */
                }, {
                  key: "cut",
                  value: function cut(target) {
                    return actions_cut(target);
                  }
                  /**
                   * Returns the support of the given action, or all actions if no action is
                   * given.
                   * @param {String} [action]
                   */
                }, {
                  key: "isSupported",
                  value: function isSupported() {
                    var action = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : ["copy", "cut"];
                    var actions = typeof action === "string" ? [action] : action;
                    var support = !!document.queryCommandSupported;
                    actions.forEach(function(action2) {
                      support = support && !!document.queryCommandSupported(action2);
                    });
                    return support;
                  }
                }]);
                return Clipboard2;
              }(tiny_emitter_default());
              var clipboard2 = Clipboard;
            }
          ),
          /***/
          828: (
            /***/
            function(module2) {
              var DOCUMENT_NODE_TYPE = 9;
              if (typeof Element !== "undefined" && !Element.prototype.matches) {
                var proto = Element.prototype;
                proto.matches = proto.matchesSelector || proto.mozMatchesSelector || proto.msMatchesSelector || proto.oMatchesSelector || proto.webkitMatchesSelector;
              }
              function closest(element, selector) {
                while (element && element.nodeType !== DOCUMENT_NODE_TYPE) {
                  if (typeof element.matches === "function" && element.matches(selector)) {
                    return element;
                  }
                  element = element.parentNode;
                }
              }
              module2.exports = closest;
            }
          ),
          /***/
          438: (
            /***/
            function(module2, __unused_webpack_exports, __webpack_require__2) {
              var closest = __webpack_require__2(828);
              function _delegate(element, selector, type, callback, useCapture) {
                var listenerFn = listener.apply(this, arguments);
                element.addEventListener(type, listenerFn, useCapture);
                return {
                  destroy: function() {
                    element.removeEventListener(type, listenerFn, useCapture);
                  }
                };
              }
              function delegate(elements, selector, type, callback, useCapture) {
                if (typeof elements.addEventListener === "function") {
                  return _delegate.apply(null, arguments);
                }
                if (typeof type === "function") {
                  return _delegate.bind(null, document).apply(null, arguments);
                }
                if (typeof elements === "string") {
                  elements = document.querySelectorAll(elements);
                }
                return Array.prototype.map.call(elements, function(element) {
                  return _delegate(element, selector, type, callback, useCapture);
                });
              }
              function listener(element, selector, type, callback) {
                return function(e2) {
                  e2.delegateTarget = closest(e2.target, selector);
                  if (e2.delegateTarget) {
                    callback.call(element, e2);
                  }
                };
              }
              module2.exports = delegate;
            }
          ),
          /***/
          879: (
            /***/
            function(__unused_webpack_module, exports2) {
              exports2.node = function(value) {
                return value !== void 0 && value instanceof HTMLElement && value.nodeType === 1;
              };
              exports2.nodeList = function(value) {
                var type = Object.prototype.toString.call(value);
                return value !== void 0 && (type === "[object NodeList]" || type === "[object HTMLCollection]") && "length" in value && (value.length === 0 || exports2.node(value[0]));
              };
              exports2.string = function(value) {
                return typeof value === "string" || value instanceof String;
              };
              exports2.fn = function(value) {
                var type = Object.prototype.toString.call(value);
                return type === "[object Function]";
              };
            }
          ),
          /***/
          370: (
            /***/
            function(module2, __unused_webpack_exports, __webpack_require__2) {
              var is = __webpack_require__2(879);
              var delegate = __webpack_require__2(438);
              function listen(target, type, callback) {
                if (!target && !type && !callback) {
                  throw new Error("Missing required arguments");
                }
                if (!is.string(type)) {
                  throw new TypeError("Second argument must be a String");
                }
                if (!is.fn(callback)) {
                  throw new TypeError("Third argument must be a Function");
                }
                if (is.node(target)) {
                  return listenNode(target, type, callback);
                } else if (is.nodeList(target)) {
                  return listenNodeList(target, type, callback);
                } else if (is.string(target)) {
                  return listenSelector(target, type, callback);
                } else {
                  throw new TypeError("First argument must be a String, HTMLElement, HTMLCollection, or NodeList");
                }
              }
              function listenNode(node, type, callback) {
                node.addEventListener(type, callback);
                return {
                  destroy: function() {
                    node.removeEventListener(type, callback);
                  }
                };
              }
              function listenNodeList(nodeList, type, callback) {
                Array.prototype.forEach.call(nodeList, function(node) {
                  node.addEventListener(type, callback);
                });
                return {
                  destroy: function() {
                    Array.prototype.forEach.call(nodeList, function(node) {
                      node.removeEventListener(type, callback);
                    });
                  }
                };
              }
              function listenSelector(selector, type, callback) {
                return delegate(document.body, selector, type, callback);
              }
              module2.exports = listen;
            }
          ),
          /***/
          817: (
            /***/
            function(module2) {
              function select(element) {
                var selectedText;
                if (element.nodeName === "SELECT") {
                  element.focus();
                  selectedText = element.value;
                } else if (element.nodeName === "INPUT" || element.nodeName === "TEXTAREA") {
                  var isReadOnly = element.hasAttribute("readonly");
                  if (!isReadOnly) {
                    element.setAttribute("readonly", "");
                  }
                  element.select();
                  element.setSelectionRange(0, element.value.length);
                  if (!isReadOnly) {
                    element.removeAttribute("readonly");
                  }
                  selectedText = element.value;
                } else {
                  if (element.hasAttribute("contenteditable")) {
                    element.focus();
                  }
                  var selection = window.getSelection();
                  var range = document.createRange();
                  range.selectNodeContents(element);
                  selection.removeAllRanges();
                  selection.addRange(range);
                  selectedText = selection.toString();
                }
                return selectedText;
              }
              module2.exports = select;
            }
          ),
          /***/
          279: (
            /***/
            function(module2) {
              function E() {
              }
              E.prototype = {
                on: function(name, callback, ctx) {
                  var e2 = this.e || (this.e = {});
                  (e2[name] || (e2[name] = [])).push({
                    fn: callback,
                    ctx
                  });
                  return this;
                },
                once: function(name, callback, ctx) {
                  var self2 = this;
                  function listener() {
                    self2.off(name, listener);
                    callback.apply(ctx, arguments);
                  }
                  listener._ = callback;
                  return this.on(name, listener, ctx);
                },
                emit: function(name) {
                  var data = [].slice.call(arguments, 1);
                  var evtArr = ((this.e || (this.e = {}))[name] || []).slice();
                  var i2 = 0;
                  var len = evtArr.length;
                  for (i2; i2 < len; i2++) {
                    evtArr[i2].fn.apply(evtArr[i2].ctx, data);
                  }
                  return this;
                },
                off: function(name, callback) {
                  var e2 = this.e || (this.e = {});
                  var evts = e2[name];
                  var liveEvents = [];
                  if (evts && callback) {
                    for (var i2 = 0, len = evts.length; i2 < len; i2++) {
                      if (evts[i2].fn !== callback && evts[i2].fn._ !== callback)
                        liveEvents.push(evts[i2]);
                    }
                  }
                  liveEvents.length ? e2[name] = liveEvents : delete e2[name];
                  return this;
                }
              };
              module2.exports = E;
              module2.exports.TinyEmitter = E;
            }
          )
          /******/
        };
        var __webpack_module_cache__ = {};
        function __webpack_require__(moduleId) {
          if (__webpack_module_cache__[moduleId]) {
            return __webpack_module_cache__[moduleId].exports;
          }
          var module2 = __webpack_module_cache__[moduleId] = {
            /******/
            // no module.id needed
            /******/
            // no module.loaded needed
            /******/
            exports: {}
            /******/
          };
          __webpack_modules__[moduleId](module2, module2.exports, __webpack_require__);
          return module2.exports;
        }
        !function() {
          __webpack_require__.n = function(module2) {
            var getter = module2 && module2.__esModule ? (
              /******/
              function() {
                return module2["default"];
              }
            ) : (
              /******/
              function() {
                return module2;
              }
            );
            __webpack_require__.d(getter, { a: getter });
            return getter;
          };
        }();
        !function() {
          __webpack_require__.d = function(exports2, definition) {
            for (var key2 in definition) {
              if (__webpack_require__.o(definition, key2) && !__webpack_require__.o(exports2, key2)) {
                Object.defineProperty(exports2, key2, { enumerable: true, get: definition[key2] });
              }
            }
          };
        }();
        !function() {
          __webpack_require__.o = function(obj, prop) {
            return Object.prototype.hasOwnProperty.call(obj, prop);
          };
        }();
        return __webpack_require__(686);
      }().default
    );
  });
})(clipboard);
var clipboardExports = clipboard.exports;
const ClipboardJS = /* @__PURE__ */ getDefaultExportFromCjs(clipboardExports);
var top = "top";
var bottom = "bottom";
var right = "right";
var left = "left";
var auto = "auto";
var basePlacements = [top, bottom, right, left];
var start = "start";
var end = "end";
var clippingParents = "clippingParents";
var viewport = "viewport";
var popper = "popper";
var reference = "reference";
var variationPlacements = /* @__PURE__ */ basePlacements.reduce(function(acc, placement) {
  return acc.concat([placement + "-" + start, placement + "-" + end]);
}, []);
var placements = /* @__PURE__ */ [].concat(basePlacements, [auto]).reduce(function(acc, placement) {
  return acc.concat([placement, placement + "-" + start, placement + "-" + end]);
}, []);
var beforeRead = "beforeRead";
var read$1 = "read";
var afterRead = "afterRead";
var beforeMain = "beforeMain";
var main = "main";
var afterMain = "afterMain";
var beforeWrite = "beforeWrite";
var write = "write";
var afterWrite = "afterWrite";
var modifierPhases = [beforeRead, read$1, afterRead, beforeMain, main, afterMain, beforeWrite, write, afterWrite];
function getNodeName(element) {
  return element ? (element.nodeName || "").toLowerCase() : null;
}
function getWindow(node) {
  if (node == null) {
    return window;
  }
  if (node.toString() !== "[object Window]") {
    var ownerDocument = node.ownerDocument;
    return ownerDocument ? ownerDocument.defaultView || window : window;
  }
  return node;
}
function isElement$1(node) {
  var OwnElement = getWindow(node).Element;
  return node instanceof OwnElement || node instanceof Element;
}
function isHTMLElement(node) {
  var OwnElement = getWindow(node).HTMLElement;
  return node instanceof OwnElement || node instanceof HTMLElement;
}
function isShadowRoot(node) {
  if (typeof ShadowRoot === "undefined") {
    return false;
  }
  var OwnElement = getWindow(node).ShadowRoot;
  return node instanceof OwnElement || node instanceof ShadowRoot;
}
function applyStyles(_ref) {
  var state = _ref.state;
  Object.keys(state.elements).forEach(function(name) {
    var style = state.styles[name] || {};
    var attributes = state.attributes[name] || {};
    var element = state.elements[name];
    if (!isHTMLElement(element) || !getNodeName(element)) {
      return;
    }
    Object.assign(element.style, style);
    Object.keys(attributes).forEach(function(name2) {
      var value = attributes[name2];
      if (value === false) {
        element.removeAttribute(name2);
      } else {
        element.setAttribute(name2, value === true ? "" : value);
      }
    });
  });
}
function effect$2(_ref2) {
  var state = _ref2.state;
  var initialStyles = {
    popper: {
      position: state.options.strategy,
      left: "0",
      top: "0",
      margin: "0"
    },
    arrow: {
      position: "absolute"
    },
    reference: {}
  };
  Object.assign(state.elements.popper.style, initialStyles.popper);
  state.styles = initialStyles;
  if (state.elements.arrow) {
    Object.assign(state.elements.arrow.style, initialStyles.arrow);
  }
  return function() {
    Object.keys(state.elements).forEach(function(name) {
      var element = state.elements[name];
      var attributes = state.attributes[name] || {};
      var styleProperties = Object.keys(state.styles.hasOwnProperty(name) ? state.styles[name] : initialStyles[name]);
      var style = styleProperties.reduce(function(style2, property) {
        style2[property] = "";
        return style2;
      }, {});
      if (!isHTMLElement(element) || !getNodeName(element)) {
        return;
      }
      Object.assign(element.style, style);
      Object.keys(attributes).forEach(function(attribute) {
        element.removeAttribute(attribute);
      });
    });
  };
}
const applyStyles$1 = {
  name: "applyStyles",
  enabled: true,
  phase: "write",
  fn: applyStyles,
  effect: effect$2,
  requires: ["computeStyles"]
};
function getBasePlacement(placement) {
  return placement.split("-")[0];
}
var max = Math.max;
var min = Math.min;
var round = Math.round;
function getUAString() {
  var uaData = navigator.userAgentData;
  if (uaData != null && uaData.brands && Array.isArray(uaData.brands)) {
    return uaData.brands.map(function(item) {
      return item.brand + "/" + item.version;
    }).join(" ");
  }
  return navigator.userAgent;
}
function isLayoutViewport() {
  return !/^((?!chrome|android).)*safari/i.test(getUAString());
}
function getBoundingClientRect(element, includeScale, isFixedStrategy) {
  if (includeScale === void 0) {
    includeScale = false;
  }
  if (isFixedStrategy === void 0) {
    isFixedStrategy = false;
  }
  var clientRect = element.getBoundingClientRect();
  var scaleX = 1;
  var scaleY = 1;
  if (includeScale && isHTMLElement(element)) {
    scaleX = element.offsetWidth > 0 ? round(clientRect.width) / element.offsetWidth || 1 : 1;
    scaleY = element.offsetHeight > 0 ? round(clientRect.height) / element.offsetHeight || 1 : 1;
  }
  var _ref = isElement$1(element) ? getWindow(element) : window, visualViewport = _ref.visualViewport;
  var addVisualOffsets = !isLayoutViewport() && isFixedStrategy;
  var x2 = (clientRect.left + (addVisualOffsets && visualViewport ? visualViewport.offsetLeft : 0)) / scaleX;
  var y2 = (clientRect.top + (addVisualOffsets && visualViewport ? visualViewport.offsetTop : 0)) / scaleY;
  var width = clientRect.width / scaleX;
  var height = clientRect.height / scaleY;
  return {
    width,
    height,
    top: y2,
    right: x2 + width,
    bottom: y2 + height,
    left: x2,
    x: x2,
    y: y2
  };
}
function getLayoutRect(element) {
  var clientRect = getBoundingClientRect(element);
  var width = element.offsetWidth;
  var height = element.offsetHeight;
  if (Math.abs(clientRect.width - width) <= 1) {
    width = clientRect.width;
  }
  if (Math.abs(clientRect.height - height) <= 1) {
    height = clientRect.height;
  }
  return {
    x: element.offsetLeft,
    y: element.offsetTop,
    width,
    height
  };
}
function contains(parent, child) {
  var rootNode = child.getRootNode && child.getRootNode();
  if (parent.contains(child)) {
    return true;
  } else if (rootNode && isShadowRoot(rootNode)) {
    var next = child;
    do {
      if (next && parent.isSameNode(next)) {
        return true;
      }
      next = next.parentNode || next.host;
    } while (next);
  }
  return false;
}
function getComputedStyle$1(element) {
  return getWindow(element).getComputedStyle(element);
}
function isTableElement(element) {
  return ["table", "td", "th"].indexOf(getNodeName(element)) >= 0;
}
function getDocumentElement(element) {
  return ((isElement$1(element) ? element.ownerDocument : (
    // $FlowFixMe[prop-missing]
    element.document
  )) || window.document).documentElement;
}
function getParentNode(element) {
  if (getNodeName(element) === "html") {
    return element;
  }
  return (
    // this is a quicker (but less type safe) way to save quite some bytes from the bundle
    // $FlowFixMe[incompatible-return]
    // $FlowFixMe[prop-missing]
    element.assignedSlot || // step into the shadow DOM of the parent of a slotted node
    element.parentNode || // DOM Element detected
    (isShadowRoot(element) ? element.host : null) || // ShadowRoot detected
    // $FlowFixMe[incompatible-call]: HTMLElement is a Node
    getDocumentElement(element)
  );
}
function getTrueOffsetParent(element) {
  if (!isHTMLElement(element) || // https://github.com/popperjs/popper-core/issues/837
  getComputedStyle$1(element).position === "fixed") {
    return null;
  }
  return element.offsetParent;
}
function getContainingBlock(element) {
  var isFirefox = /firefox/i.test(getUAString());
  var isIE = /Trident/i.test(getUAString());
  if (isIE && isHTMLElement(element)) {
    var elementCss = getComputedStyle$1(element);
    if (elementCss.position === "fixed") {
      return null;
    }
  }
  var currentNode = getParentNode(element);
  if (isShadowRoot(currentNode)) {
    currentNode = currentNode.host;
  }
  while (isHTMLElement(currentNode) && ["html", "body"].indexOf(getNodeName(currentNode)) < 0) {
    var css = getComputedStyle$1(currentNode);
    if (css.transform !== "none" || css.perspective !== "none" || css.contain === "paint" || ["transform", "perspective"].indexOf(css.willChange) !== -1 || isFirefox && css.willChange === "filter" || isFirefox && css.filter && css.filter !== "none") {
      return currentNode;
    } else {
      currentNode = currentNode.parentNode;
    }
  }
  return null;
}
function getOffsetParent(element) {
  var window2 = getWindow(element);
  var offsetParent = getTrueOffsetParent(element);
  while (offsetParent && isTableElement(offsetParent) && getComputedStyle$1(offsetParent).position === "static") {
    offsetParent = getTrueOffsetParent(offsetParent);
  }
  if (offsetParent && (getNodeName(offsetParent) === "html" || getNodeName(offsetParent) === "body" && getComputedStyle$1(offsetParent).position === "static")) {
    return window2;
  }
  return offsetParent || getContainingBlock(element) || window2;
}
function getMainAxisFromPlacement(placement) {
  return ["top", "bottom"].indexOf(placement) >= 0 ? "x" : "y";
}
function within(min$1, value, max$1) {
  return max(min$1, min(value, max$1));
}
function withinMaxClamp(min2, value, max2) {
  var v2 = within(min2, value, max2);
  return v2 > max2 ? max2 : v2;
}
function getFreshSideObject() {
  return {
    top: 0,
    right: 0,
    bottom: 0,
    left: 0
  };
}
function mergePaddingObject(paddingObject) {
  return Object.assign({}, getFreshSideObject(), paddingObject);
}
function expandToHashMap(value, keys) {
  return keys.reduce(function(hashMap, key2) {
    hashMap[key2] = value;
    return hashMap;
  }, {});
}
var toPaddingObject = function toPaddingObject2(padding, state) {
  padding = typeof padding === "function" ? padding(Object.assign({}, state.rects, {
    placement: state.placement
  })) : padding;
  return mergePaddingObject(typeof padding !== "number" ? padding : expandToHashMap(padding, basePlacements));
};
function arrow(_ref) {
  var _state$modifiersData$;
  var state = _ref.state, name = _ref.name, options = _ref.options;
  var arrowElement = state.elements.arrow;
  var popperOffsets2 = state.modifiersData.popperOffsets;
  var basePlacement = getBasePlacement(state.placement);
  var axis = getMainAxisFromPlacement(basePlacement);
  var isVertical = [left, right].indexOf(basePlacement) >= 0;
  var len = isVertical ? "height" : "width";
  if (!arrowElement || !popperOffsets2) {
    return;
  }
  var paddingObject = toPaddingObject(options.padding, state);
  var arrowRect = getLayoutRect(arrowElement);
  var minProp = axis === "y" ? top : left;
  var maxProp = axis === "y" ? bottom : right;
  var endDiff = state.rects.reference[len] + state.rects.reference[axis] - popperOffsets2[axis] - state.rects.popper[len];
  var startDiff = popperOffsets2[axis] - state.rects.reference[axis];
  var arrowOffsetParent = getOffsetParent(arrowElement);
  var clientSize = arrowOffsetParent ? axis === "y" ? arrowOffsetParent.clientHeight || 0 : arrowOffsetParent.clientWidth || 0 : 0;
  var centerToReference = endDiff / 2 - startDiff / 2;
  var min2 = paddingObject[minProp];
  var max2 = clientSize - arrowRect[len] - paddingObject[maxProp];
  var center = clientSize / 2 - arrowRect[len] / 2 + centerToReference;
  var offset2 = within(min2, center, max2);
  var axisProp = axis;
  state.modifiersData[name] = (_state$modifiersData$ = {}, _state$modifiersData$[axisProp] = offset2, _state$modifiersData$.centerOffset = offset2 - center, _state$modifiersData$);
}
function effect$1(_ref2) {
  var state = _ref2.state, options = _ref2.options;
  var _options$element = options.element, arrowElement = _options$element === void 0 ? "[data-popper-arrow]" : _options$element;
  if (arrowElement == null) {
    return;
  }
  if (typeof arrowElement === "string") {
    arrowElement = state.elements.popper.querySelector(arrowElement);
    if (!arrowElement) {
      return;
    }
  }
  if (!contains(state.elements.popper, arrowElement)) {
    return;
  }
  state.elements.arrow = arrowElement;
}
const arrow$1 = {
  name: "arrow",
  enabled: true,
  phase: "main",
  fn: arrow,
  effect: effect$1,
  requires: ["popperOffsets"],
  requiresIfExists: ["preventOverflow"]
};
function getVariation(placement) {
  return placement.split("-")[1];
}
var unsetSides = {
  top: "auto",
  right: "auto",
  bottom: "auto",
  left: "auto"
};
function roundOffsetsByDPR(_ref, win) {
  var x2 = _ref.x, y2 = _ref.y;
  var dpr = win.devicePixelRatio || 1;
  return {
    x: round(x2 * dpr) / dpr || 0,
    y: round(y2 * dpr) / dpr || 0
  };
}
function mapToStyles(_ref2) {
  var _Object$assign2;
  var popper2 = _ref2.popper, popperRect = _ref2.popperRect, placement = _ref2.placement, variation = _ref2.variation, offsets = _ref2.offsets, position = _ref2.position, gpuAcceleration = _ref2.gpuAcceleration, adaptive = _ref2.adaptive, roundOffsets = _ref2.roundOffsets, isFixed = _ref2.isFixed;
  var _offsets$x = offsets.x, x2 = _offsets$x === void 0 ? 0 : _offsets$x, _offsets$y = offsets.y, y2 = _offsets$y === void 0 ? 0 : _offsets$y;
  var _ref3 = typeof roundOffsets === "function" ? roundOffsets({
    x: x2,
    y: y2
  }) : {
    x: x2,
    y: y2
  };
  x2 = _ref3.x;
  y2 = _ref3.y;
  var hasX = offsets.hasOwnProperty("x");
  var hasY = offsets.hasOwnProperty("y");
  var sideX = left;
  var sideY = top;
  var win = window;
  if (adaptive) {
    var offsetParent = getOffsetParent(popper2);
    var heightProp = "clientHeight";
    var widthProp = "clientWidth";
    if (offsetParent === getWindow(popper2)) {
      offsetParent = getDocumentElement(popper2);
      if (getComputedStyle$1(offsetParent).position !== "static" && position === "absolute") {
        heightProp = "scrollHeight";
        widthProp = "scrollWidth";
      }
    }
    offsetParent = offsetParent;
    if (placement === top || (placement === left || placement === right) && variation === end) {
      sideY = bottom;
      var offsetY = isFixed && offsetParent === win && win.visualViewport ? win.visualViewport.height : (
        // $FlowFixMe[prop-missing]
        offsetParent[heightProp]
      );
      y2 -= offsetY - popperRect.height;
      y2 *= gpuAcceleration ? 1 : -1;
    }
    if (placement === left || (placement === top || placement === bottom) && variation === end) {
      sideX = right;
      var offsetX = isFixed && offsetParent === win && win.visualViewport ? win.visualViewport.width : (
        // $FlowFixMe[prop-missing]
        offsetParent[widthProp]
      );
      x2 -= offsetX - popperRect.width;
      x2 *= gpuAcceleration ? 1 : -1;
    }
  }
  var commonStyles = Object.assign({
    position
  }, adaptive && unsetSides);
  var _ref4 = roundOffsets === true ? roundOffsetsByDPR({
    x: x2,
    y: y2
  }, getWindow(popper2)) : {
    x: x2,
    y: y2
  };
  x2 = _ref4.x;
  y2 = _ref4.y;
  if (gpuAcceleration) {
    var _Object$assign;
    return Object.assign({}, commonStyles, (_Object$assign = {}, _Object$assign[sideY] = hasY ? "0" : "", _Object$assign[sideX] = hasX ? "0" : "", _Object$assign.transform = (win.devicePixelRatio || 1) <= 1 ? "translate(" + x2 + "px, " + y2 + "px)" : "translate3d(" + x2 + "px, " + y2 + "px, 0)", _Object$assign));
  }
  return Object.assign({}, commonStyles, (_Object$assign2 = {}, _Object$assign2[sideY] = hasY ? y2 + "px" : "", _Object$assign2[sideX] = hasX ? x2 + "px" : "", _Object$assign2.transform = "", _Object$assign2));
}
function computeStyles(_ref5) {
  var state = _ref5.state, options = _ref5.options;
  var _options$gpuAccelerat = options.gpuAcceleration, gpuAcceleration = _options$gpuAccelerat === void 0 ? true : _options$gpuAccelerat, _options$adaptive = options.adaptive, adaptive = _options$adaptive === void 0 ? true : _options$adaptive, _options$roundOffsets = options.roundOffsets, roundOffsets = _options$roundOffsets === void 0 ? true : _options$roundOffsets;
  var commonStyles = {
    placement: getBasePlacement(state.placement),
    variation: getVariation(state.placement),
    popper: state.elements.popper,
    popperRect: state.rects.popper,
    gpuAcceleration,
    isFixed: state.options.strategy === "fixed"
  };
  if (state.modifiersData.popperOffsets != null) {
    state.styles.popper = Object.assign({}, state.styles.popper, mapToStyles(Object.assign({}, commonStyles, {
      offsets: state.modifiersData.popperOffsets,
      position: state.options.strategy,
      adaptive,
      roundOffsets
    })));
  }
  if (state.modifiersData.arrow != null) {
    state.styles.arrow = Object.assign({}, state.styles.arrow, mapToStyles(Object.assign({}, commonStyles, {
      offsets: state.modifiersData.arrow,
      position: "absolute",
      adaptive: false,
      roundOffsets
    })));
  }
  state.attributes.popper = Object.assign({}, state.attributes.popper, {
    "data-popper-placement": state.placement
  });
}
const computeStyles$1 = {
  name: "computeStyles",
  enabled: true,
  phase: "beforeWrite",
  fn: computeStyles,
  data: {}
};
var passive = {
  passive: true
};
function effect(_ref) {
  var state = _ref.state, instance = _ref.instance, options = _ref.options;
  var _options$scroll = options.scroll, scroll = _options$scroll === void 0 ? true : _options$scroll, _options$resize = options.resize, resize = _options$resize === void 0 ? true : _options$resize;
  var window2 = getWindow(state.elements.popper);
  var scrollParents = [].concat(state.scrollParents.reference, state.scrollParents.popper);
  if (scroll) {
    scrollParents.forEach(function(scrollParent) {
      scrollParent.addEventListener("scroll", instance.update, passive);
    });
  }
  if (resize) {
    window2.addEventListener("resize", instance.update, passive);
  }
  return function() {
    if (scroll) {
      scrollParents.forEach(function(scrollParent) {
        scrollParent.removeEventListener("scroll", instance.update, passive);
      });
    }
    if (resize) {
      window2.removeEventListener("resize", instance.update, passive);
    }
  };
}
const eventListeners = {
  name: "eventListeners",
  enabled: true,
  phase: "write",
  fn: function fn() {
  },
  effect,
  data: {}
};
var hash$1 = {
  left: "right",
  right: "left",
  bottom: "top",
  top: "bottom"
};
function getOppositePlacement(placement) {
  return placement.replace(/left|right|bottom|top/g, function(matched) {
    return hash$1[matched];
  });
}
var hash = {
  start: "end",
  end: "start"
};
function getOppositeVariationPlacement(placement) {
  return placement.replace(/start|end/g, function(matched) {
    return hash[matched];
  });
}
function getWindowScroll(node) {
  var win = getWindow(node);
  var scrollLeft = win.pageXOffset;
  var scrollTop = win.pageYOffset;
  return {
    scrollLeft,
    scrollTop
  };
}
function getWindowScrollBarX(element) {
  return getBoundingClientRect(getDocumentElement(element)).left + getWindowScroll(element).scrollLeft;
}
function getViewportRect(element, strategy) {
  var win = getWindow(element);
  var html = getDocumentElement(element);
  var visualViewport = win.visualViewport;
  var width = html.clientWidth;
  var height = html.clientHeight;
  var x2 = 0;
  var y2 = 0;
  if (visualViewport) {
    width = visualViewport.width;
    height = visualViewport.height;
    var layoutViewport = isLayoutViewport();
    if (layoutViewport || !layoutViewport && strategy === "fixed") {
      x2 = visualViewport.offsetLeft;
      y2 = visualViewport.offsetTop;
    }
  }
  return {
    width,
    height,
    x: x2 + getWindowScrollBarX(element),
    y: y2
  };
}
function getDocumentRect(element) {
  var _element$ownerDocumen;
  var html = getDocumentElement(element);
  var winScroll = getWindowScroll(element);
  var body = (_element$ownerDocumen = element.ownerDocument) == null ? void 0 : _element$ownerDocumen.body;
  var width = max(html.scrollWidth, html.clientWidth, body ? body.scrollWidth : 0, body ? body.clientWidth : 0);
  var height = max(html.scrollHeight, html.clientHeight, body ? body.scrollHeight : 0, body ? body.clientHeight : 0);
  var x2 = -winScroll.scrollLeft + getWindowScrollBarX(element);
  var y2 = -winScroll.scrollTop;
  if (getComputedStyle$1(body || html).direction === "rtl") {
    x2 += max(html.clientWidth, body ? body.clientWidth : 0) - width;
  }
  return {
    width,
    height,
    x: x2,
    y: y2
  };
}
function isScrollParent(element) {
  var _getComputedStyle = getComputedStyle$1(element), overflow = _getComputedStyle.overflow, overflowX = _getComputedStyle.overflowX, overflowY = _getComputedStyle.overflowY;
  return /auto|scroll|overlay|hidden/.test(overflow + overflowY + overflowX);
}
function getScrollParent(node) {
  if (["html", "body", "#document"].indexOf(getNodeName(node)) >= 0) {
    return node.ownerDocument.body;
  }
  if (isHTMLElement(node) && isScrollParent(node)) {
    return node;
  }
  return getScrollParent(getParentNode(node));
}
function listScrollParents(element, list) {
  var _element$ownerDocumen;
  if (list === void 0) {
    list = [];
  }
  var scrollParent = getScrollParent(element);
  var isBody = scrollParent === ((_element$ownerDocumen = element.ownerDocument) == null ? void 0 : _element$ownerDocumen.body);
  var win = getWindow(scrollParent);
  var target = isBody ? [win].concat(win.visualViewport || [], isScrollParent(scrollParent) ? scrollParent : []) : scrollParent;
  var updatedList = list.concat(target);
  return isBody ? updatedList : (
    // $FlowFixMe[incompatible-call]: isBody tells us target will be an HTMLElement here
    updatedList.concat(listScrollParents(getParentNode(target)))
  );
}
function rectToClientRect(rect) {
  return Object.assign({}, rect, {
    left: rect.x,
    top: rect.y,
    right: rect.x + rect.width,
    bottom: rect.y + rect.height
  });
}
function getInnerBoundingClientRect(element, strategy) {
  var rect = getBoundingClientRect(element, false, strategy === "fixed");
  rect.top = rect.top + element.clientTop;
  rect.left = rect.left + element.clientLeft;
  rect.bottom = rect.top + element.clientHeight;
  rect.right = rect.left + element.clientWidth;
  rect.width = element.clientWidth;
  rect.height = element.clientHeight;
  rect.x = rect.left;
  rect.y = rect.top;
  return rect;
}
function getClientRectFromMixedType(element, clippingParent, strategy) {
  return clippingParent === viewport ? rectToClientRect(getViewportRect(element, strategy)) : isElement$1(clippingParent) ? getInnerBoundingClientRect(clippingParent, strategy) : rectToClientRect(getDocumentRect(getDocumentElement(element)));
}
function getClippingParents(element) {
  var clippingParents2 = listScrollParents(getParentNode(element));
  var canEscapeClipping = ["absolute", "fixed"].indexOf(getComputedStyle$1(element).position) >= 0;
  var clipperElement = canEscapeClipping && isHTMLElement(element) ? getOffsetParent(element) : element;
  if (!isElement$1(clipperElement)) {
    return [];
  }
  return clippingParents2.filter(function(clippingParent) {
    return isElement$1(clippingParent) && contains(clippingParent, clipperElement) && getNodeName(clippingParent) !== "body";
  });
}
function getClippingRect(element, boundary, rootBoundary, strategy) {
  var mainClippingParents = boundary === "clippingParents" ? getClippingParents(element) : [].concat(boundary);
  var clippingParents2 = [].concat(mainClippingParents, [rootBoundary]);
  var firstClippingParent = clippingParents2[0];
  var clippingRect = clippingParents2.reduce(function(accRect, clippingParent) {
    var rect = getClientRectFromMixedType(element, clippingParent, strategy);
    accRect.top = max(rect.top, accRect.top);
    accRect.right = min(rect.right, accRect.right);
    accRect.bottom = min(rect.bottom, accRect.bottom);
    accRect.left = max(rect.left, accRect.left);
    return accRect;
  }, getClientRectFromMixedType(element, firstClippingParent, strategy));
  clippingRect.width = clippingRect.right - clippingRect.left;
  clippingRect.height = clippingRect.bottom - clippingRect.top;
  clippingRect.x = clippingRect.left;
  clippingRect.y = clippingRect.top;
  return clippingRect;
}
function computeOffsets(_ref) {
  var reference2 = _ref.reference, element = _ref.element, placement = _ref.placement;
  var basePlacement = placement ? getBasePlacement(placement) : null;
  var variation = placement ? getVariation(placement) : null;
  var commonX = reference2.x + reference2.width / 2 - element.width / 2;
  var commonY = reference2.y + reference2.height / 2 - element.height / 2;
  var offsets;
  switch (basePlacement) {
    case top:
      offsets = {
        x: commonX,
        y: reference2.y - element.height
      };
      break;
    case bottom:
      offsets = {
        x: commonX,
        y: reference2.y + reference2.height
      };
      break;
    case right:
      offsets = {
        x: reference2.x + reference2.width,
        y: commonY
      };
      break;
    case left:
      offsets = {
        x: reference2.x - element.width,
        y: commonY
      };
      break;
    default:
      offsets = {
        x: reference2.x,
        y: reference2.y
      };
  }
  var mainAxis = basePlacement ? getMainAxisFromPlacement(basePlacement) : null;
  if (mainAxis != null) {
    var len = mainAxis === "y" ? "height" : "width";
    switch (variation) {
      case start:
        offsets[mainAxis] = offsets[mainAxis] - (reference2[len] / 2 - element[len] / 2);
        break;
      case end:
        offsets[mainAxis] = offsets[mainAxis] + (reference2[len] / 2 - element[len] / 2);
        break;
    }
  }
  return offsets;
}
function detectOverflow(state, options) {
  if (options === void 0) {
    options = {};
  }
  var _options = options, _options$placement = _options.placement, placement = _options$placement === void 0 ? state.placement : _options$placement, _options$strategy = _options.strategy, strategy = _options$strategy === void 0 ? state.strategy : _options$strategy, _options$boundary = _options.boundary, boundary = _options$boundary === void 0 ? clippingParents : _options$boundary, _options$rootBoundary = _options.rootBoundary, rootBoundary = _options$rootBoundary === void 0 ? viewport : _options$rootBoundary, _options$elementConte = _options.elementContext, elementContext = _options$elementConte === void 0 ? popper : _options$elementConte, _options$altBoundary = _options.altBoundary, altBoundary = _options$altBoundary === void 0 ? false : _options$altBoundary, _options$padding = _options.padding, padding = _options$padding === void 0 ? 0 : _options$padding;
  var paddingObject = mergePaddingObject(typeof padding !== "number" ? padding : expandToHashMap(padding, basePlacements));
  var altContext = elementContext === popper ? reference : popper;
  var popperRect = state.rects.popper;
  var element = state.elements[altBoundary ? altContext : elementContext];
  var clippingClientRect = getClippingRect(isElement$1(element) ? element : element.contextElement || getDocumentElement(state.elements.popper), boundary, rootBoundary, strategy);
  var referenceClientRect = getBoundingClientRect(state.elements.reference);
  var popperOffsets2 = computeOffsets({
    reference: referenceClientRect,
    element: popperRect,
    strategy: "absolute",
    placement
  });
  var popperClientRect = rectToClientRect(Object.assign({}, popperRect, popperOffsets2));
  var elementClientRect = elementContext === popper ? popperClientRect : referenceClientRect;
  var overflowOffsets = {
    top: clippingClientRect.top - elementClientRect.top + paddingObject.top,
    bottom: elementClientRect.bottom - clippingClientRect.bottom + paddingObject.bottom,
    left: clippingClientRect.left - elementClientRect.left + paddingObject.left,
    right: elementClientRect.right - clippingClientRect.right + paddingObject.right
  };
  var offsetData = state.modifiersData.offset;
  if (elementContext === popper && offsetData) {
    var offset2 = offsetData[placement];
    Object.keys(overflowOffsets).forEach(function(key2) {
      var multiply = [right, bottom].indexOf(key2) >= 0 ? 1 : -1;
      var axis = [top, bottom].indexOf(key2) >= 0 ? "y" : "x";
      overflowOffsets[key2] += offset2[axis] * multiply;
    });
  }
  return overflowOffsets;
}
function computeAutoPlacement(state, options) {
  if (options === void 0) {
    options = {};
  }
  var _options = options, placement = _options.placement, boundary = _options.boundary, rootBoundary = _options.rootBoundary, padding = _options.padding, flipVariations = _options.flipVariations, _options$allowedAutoP = _options.allowedAutoPlacements, allowedAutoPlacements = _options$allowedAutoP === void 0 ? placements : _options$allowedAutoP;
  var variation = getVariation(placement);
  var placements$1 = variation ? flipVariations ? variationPlacements : variationPlacements.filter(function(placement2) {
    return getVariation(placement2) === variation;
  }) : basePlacements;
  var allowedPlacements = placements$1.filter(function(placement2) {
    return allowedAutoPlacements.indexOf(placement2) >= 0;
  });
  if (allowedPlacements.length === 0) {
    allowedPlacements = placements$1;
  }
  var overflows = allowedPlacements.reduce(function(acc, placement2) {
    acc[placement2] = detectOverflow(state, {
      placement: placement2,
      boundary,
      rootBoundary,
      padding
    })[getBasePlacement(placement2)];
    return acc;
  }, {});
  return Object.keys(overflows).sort(function(a2, b2) {
    return overflows[a2] - overflows[b2];
  });
}
function getExpandedFallbackPlacements(placement) {
  if (getBasePlacement(placement) === auto) {
    return [];
  }
  var oppositePlacement = getOppositePlacement(placement);
  return [getOppositeVariationPlacement(placement), oppositePlacement, getOppositeVariationPlacement(oppositePlacement)];
}
function flip(_ref) {
  var state = _ref.state, options = _ref.options, name = _ref.name;
  if (state.modifiersData[name]._skip) {
    return;
  }
  var _options$mainAxis = options.mainAxis, checkMainAxis = _options$mainAxis === void 0 ? true : _options$mainAxis, _options$altAxis = options.altAxis, checkAltAxis = _options$altAxis === void 0 ? true : _options$altAxis, specifiedFallbackPlacements = options.fallbackPlacements, padding = options.padding, boundary = options.boundary, rootBoundary = options.rootBoundary, altBoundary = options.altBoundary, _options$flipVariatio = options.flipVariations, flipVariations = _options$flipVariatio === void 0 ? true : _options$flipVariatio, allowedAutoPlacements = options.allowedAutoPlacements;
  var preferredPlacement = state.options.placement;
  var basePlacement = getBasePlacement(preferredPlacement);
  var isBasePlacement = basePlacement === preferredPlacement;
  var fallbackPlacements = specifiedFallbackPlacements || (isBasePlacement || !flipVariations ? [getOppositePlacement(preferredPlacement)] : getExpandedFallbackPlacements(preferredPlacement));
  var placements2 = [preferredPlacement].concat(fallbackPlacements).reduce(function(acc, placement2) {
    return acc.concat(getBasePlacement(placement2) === auto ? computeAutoPlacement(state, {
      placement: placement2,
      boundary,
      rootBoundary,
      padding,
      flipVariations,
      allowedAutoPlacements
    }) : placement2);
  }, []);
  var referenceRect = state.rects.reference;
  var popperRect = state.rects.popper;
  var checksMap = /* @__PURE__ */ new Map();
  var makeFallbackChecks = true;
  var firstFittingPlacement = placements2[0];
  for (var i2 = 0; i2 < placements2.length; i2++) {
    var placement = placements2[i2];
    var _basePlacement = getBasePlacement(placement);
    var isStartVariation = getVariation(placement) === start;
    var isVertical = [top, bottom].indexOf(_basePlacement) >= 0;
    var len = isVertical ? "width" : "height";
    var overflow = detectOverflow(state, {
      placement,
      boundary,
      rootBoundary,
      altBoundary,
      padding
    });
    var mainVariationSide = isVertical ? isStartVariation ? right : left : isStartVariation ? bottom : top;
    if (referenceRect[len] > popperRect[len]) {
      mainVariationSide = getOppositePlacement(mainVariationSide);
    }
    var altVariationSide = getOppositePlacement(mainVariationSide);
    var checks = [];
    if (checkMainAxis) {
      checks.push(overflow[_basePlacement] <= 0);
    }
    if (checkAltAxis) {
      checks.push(overflow[mainVariationSide] <= 0, overflow[altVariationSide] <= 0);
    }
    if (checks.every(function(check) {
      return check;
    })) {
      firstFittingPlacement = placement;
      makeFallbackChecks = false;
      break;
    }
    checksMap.set(placement, checks);
  }
  if (makeFallbackChecks) {
    var numberOfChecks = flipVariations ? 3 : 1;
    var _loop = function _loop2(_i2) {
      var fittingPlacement = placements2.find(function(placement2) {
        var checks2 = checksMap.get(placement2);
        if (checks2) {
          return checks2.slice(0, _i2).every(function(check) {
            return check;
          });
        }
      });
      if (fittingPlacement) {
        firstFittingPlacement = fittingPlacement;
        return "break";
      }
    };
    for (var _i = numberOfChecks; _i > 0; _i--) {
      var _ret = _loop(_i);
      if (_ret === "break") break;
    }
  }
  if (state.placement !== firstFittingPlacement) {
    state.modifiersData[name]._skip = true;
    state.placement = firstFittingPlacement;
    state.reset = true;
  }
}
const flip$1 = {
  name: "flip",
  enabled: true,
  phase: "main",
  fn: flip,
  requiresIfExists: ["offset"],
  data: {
    _skip: false
  }
};
function getSideOffsets(overflow, rect, preventedOffsets) {
  if (preventedOffsets === void 0) {
    preventedOffsets = {
      x: 0,
      y: 0
    };
  }
  return {
    top: overflow.top - rect.height - preventedOffsets.y,
    right: overflow.right - rect.width + preventedOffsets.x,
    bottom: overflow.bottom - rect.height + preventedOffsets.y,
    left: overflow.left - rect.width - preventedOffsets.x
  };
}
function isAnySideFullyClipped(overflow) {
  return [top, right, bottom, left].some(function(side) {
    return overflow[side] >= 0;
  });
}
function hide(_ref) {
  var state = _ref.state, name = _ref.name;
  var referenceRect = state.rects.reference;
  var popperRect = state.rects.popper;
  var preventedOffsets = state.modifiersData.preventOverflow;
  var referenceOverflow = detectOverflow(state, {
    elementContext: "reference"
  });
  var popperAltOverflow = detectOverflow(state, {
    altBoundary: true
  });
  var referenceClippingOffsets = getSideOffsets(referenceOverflow, referenceRect);
  var popperEscapeOffsets = getSideOffsets(popperAltOverflow, popperRect, preventedOffsets);
  var isReferenceHidden = isAnySideFullyClipped(referenceClippingOffsets);
  var hasPopperEscaped = isAnySideFullyClipped(popperEscapeOffsets);
  state.modifiersData[name] = {
    referenceClippingOffsets,
    popperEscapeOffsets,
    isReferenceHidden,
    hasPopperEscaped
  };
  state.attributes.popper = Object.assign({}, state.attributes.popper, {
    "data-popper-reference-hidden": isReferenceHidden,
    "data-popper-escaped": hasPopperEscaped
  });
}
const hide$1 = {
  name: "hide",
  enabled: true,
  phase: "main",
  requiresIfExists: ["preventOverflow"],
  fn: hide
};
function distanceAndSkiddingToXY(placement, rects, offset2) {
  var basePlacement = getBasePlacement(placement);
  var invertDistance = [left, top].indexOf(basePlacement) >= 0 ? -1 : 1;
  var _ref = typeof offset2 === "function" ? offset2(Object.assign({}, rects, {
    placement
  })) : offset2, skidding = _ref[0], distance = _ref[1];
  skidding = skidding || 0;
  distance = (distance || 0) * invertDistance;
  return [left, right].indexOf(basePlacement) >= 0 ? {
    x: distance,
    y: skidding
  } : {
    x: skidding,
    y: distance
  };
}
function offset(_ref2) {
  var state = _ref2.state, options = _ref2.options, name = _ref2.name;
  var _options$offset = options.offset, offset2 = _options$offset === void 0 ? [0, 0] : _options$offset;
  var data = placements.reduce(function(acc, placement) {
    acc[placement] = distanceAndSkiddingToXY(placement, state.rects, offset2);
    return acc;
  }, {});
  var _data$state$placement = data[state.placement], x2 = _data$state$placement.x, y2 = _data$state$placement.y;
  if (state.modifiersData.popperOffsets != null) {
    state.modifiersData.popperOffsets.x += x2;
    state.modifiersData.popperOffsets.y += y2;
  }
  state.modifiersData[name] = data;
}
const offset$1 = {
  name: "offset",
  enabled: true,
  phase: "main",
  requires: ["popperOffsets"],
  fn: offset
};
function popperOffsets(_ref) {
  var state = _ref.state, name = _ref.name;
  state.modifiersData[name] = computeOffsets({
    reference: state.rects.reference,
    element: state.rects.popper,
    strategy: "absolute",
    placement: state.placement
  });
}
const popperOffsets$1 = {
  name: "popperOffsets",
  enabled: true,
  phase: "read",
  fn: popperOffsets,
  data: {}
};
function getAltAxis(axis) {
  return axis === "x" ? "y" : "x";
}
function preventOverflow(_ref) {
  var state = _ref.state, options = _ref.options, name = _ref.name;
  var _options$mainAxis = options.mainAxis, checkMainAxis = _options$mainAxis === void 0 ? true : _options$mainAxis, _options$altAxis = options.altAxis, checkAltAxis = _options$altAxis === void 0 ? false : _options$altAxis, boundary = options.boundary, rootBoundary = options.rootBoundary, altBoundary = options.altBoundary, padding = options.padding, _options$tether = options.tether, tether = _options$tether === void 0 ? true : _options$tether, _options$tetherOffset = options.tetherOffset, tetherOffset = _options$tetherOffset === void 0 ? 0 : _options$tetherOffset;
  var overflow = detectOverflow(state, {
    boundary,
    rootBoundary,
    padding,
    altBoundary
  });
  var basePlacement = getBasePlacement(state.placement);
  var variation = getVariation(state.placement);
  var isBasePlacement = !variation;
  var mainAxis = getMainAxisFromPlacement(basePlacement);
  var altAxis = getAltAxis(mainAxis);
  var popperOffsets2 = state.modifiersData.popperOffsets;
  var referenceRect = state.rects.reference;
  var popperRect = state.rects.popper;
  var tetherOffsetValue = typeof tetherOffset === "function" ? tetherOffset(Object.assign({}, state.rects, {
    placement: state.placement
  })) : tetherOffset;
  var normalizedTetherOffsetValue = typeof tetherOffsetValue === "number" ? {
    mainAxis: tetherOffsetValue,
    altAxis: tetherOffsetValue
  } : Object.assign({
    mainAxis: 0,
    altAxis: 0
  }, tetherOffsetValue);
  var offsetModifierState = state.modifiersData.offset ? state.modifiersData.offset[state.placement] : null;
  var data = {
    x: 0,
    y: 0
  };
  if (!popperOffsets2) {
    return;
  }
  if (checkMainAxis) {
    var _offsetModifierState$;
    var mainSide = mainAxis === "y" ? top : left;
    var altSide = mainAxis === "y" ? bottom : right;
    var len = mainAxis === "y" ? "height" : "width";
    var offset2 = popperOffsets2[mainAxis];
    var min$1 = offset2 + overflow[mainSide];
    var max$1 = offset2 - overflow[altSide];
    var additive = tether ? -popperRect[len] / 2 : 0;
    var minLen = variation === start ? referenceRect[len] : popperRect[len];
    var maxLen = variation === start ? -popperRect[len] : -referenceRect[len];
    var arrowElement = state.elements.arrow;
    var arrowRect = tether && arrowElement ? getLayoutRect(arrowElement) : {
      width: 0,
      height: 0
    };
    var arrowPaddingObject = state.modifiersData["arrow#persistent"] ? state.modifiersData["arrow#persistent"].padding : getFreshSideObject();
    var arrowPaddingMin = arrowPaddingObject[mainSide];
    var arrowPaddingMax = arrowPaddingObject[altSide];
    var arrowLen = within(0, referenceRect[len], arrowRect[len]);
    var minOffset = isBasePlacement ? referenceRect[len] / 2 - additive - arrowLen - arrowPaddingMin - normalizedTetherOffsetValue.mainAxis : minLen - arrowLen - arrowPaddingMin - normalizedTetherOffsetValue.mainAxis;
    var maxOffset = isBasePlacement ? -referenceRect[len] / 2 + additive + arrowLen + arrowPaddingMax + normalizedTetherOffsetValue.mainAxis : maxLen + arrowLen + arrowPaddingMax + normalizedTetherOffsetValue.mainAxis;
    var arrowOffsetParent = state.elements.arrow && getOffsetParent(state.elements.arrow);
    var clientOffset = arrowOffsetParent ? mainAxis === "y" ? arrowOffsetParent.clientTop || 0 : arrowOffsetParent.clientLeft || 0 : 0;
    var offsetModifierValue = (_offsetModifierState$ = offsetModifierState == null ? void 0 : offsetModifierState[mainAxis]) != null ? _offsetModifierState$ : 0;
    var tetherMin = offset2 + minOffset - offsetModifierValue - clientOffset;
    var tetherMax = offset2 + maxOffset - offsetModifierValue;
    var preventedOffset = within(tether ? min(min$1, tetherMin) : min$1, offset2, tether ? max(max$1, tetherMax) : max$1);
    popperOffsets2[mainAxis] = preventedOffset;
    data[mainAxis] = preventedOffset - offset2;
  }
  if (checkAltAxis) {
    var _offsetModifierState$2;
    var _mainSide = mainAxis === "x" ? top : left;
    var _altSide = mainAxis === "x" ? bottom : right;
    var _offset = popperOffsets2[altAxis];
    var _len = altAxis === "y" ? "height" : "width";
    var _min = _offset + overflow[_mainSide];
    var _max = _offset - overflow[_altSide];
    var isOriginSide = [top, left].indexOf(basePlacement) !== -1;
    var _offsetModifierValue = (_offsetModifierState$2 = offsetModifierState == null ? void 0 : offsetModifierState[altAxis]) != null ? _offsetModifierState$2 : 0;
    var _tetherMin = isOriginSide ? _min : _offset - referenceRect[_len] - popperRect[_len] - _offsetModifierValue + normalizedTetherOffsetValue.altAxis;
    var _tetherMax = isOriginSide ? _offset + referenceRect[_len] + popperRect[_len] - _offsetModifierValue - normalizedTetherOffsetValue.altAxis : _max;
    var _preventedOffset = tether && isOriginSide ? withinMaxClamp(_tetherMin, _offset, _tetherMax) : within(tether ? _tetherMin : _min, _offset, tether ? _tetherMax : _max);
    popperOffsets2[altAxis] = _preventedOffset;
    data[altAxis] = _preventedOffset - _offset;
  }
  state.modifiersData[name] = data;
}
const preventOverflow$1 = {
  name: "preventOverflow",
  enabled: true,
  phase: "main",
  fn: preventOverflow,
  requiresIfExists: ["offset"]
};
function getHTMLElementScroll(element) {
  return {
    scrollLeft: element.scrollLeft,
    scrollTop: element.scrollTop
  };
}
function getNodeScroll(node) {
  if (node === getWindow(node) || !isHTMLElement(node)) {
    return getWindowScroll(node);
  } else {
    return getHTMLElementScroll(node);
  }
}
function isElementScaled(element) {
  var rect = element.getBoundingClientRect();
  var scaleX = round(rect.width) / element.offsetWidth || 1;
  var scaleY = round(rect.height) / element.offsetHeight || 1;
  return scaleX !== 1 || scaleY !== 1;
}
function getCompositeRect(elementOrVirtualElement, offsetParent, isFixed) {
  if (isFixed === void 0) {
    isFixed = false;
  }
  var isOffsetParentAnElement = isHTMLElement(offsetParent);
  var offsetParentIsScaled = isHTMLElement(offsetParent) && isElementScaled(offsetParent);
  var documentElement = getDocumentElement(offsetParent);
  var rect = getBoundingClientRect(elementOrVirtualElement, offsetParentIsScaled, isFixed);
  var scroll = {
    scrollLeft: 0,
    scrollTop: 0
  };
  var offsets = {
    x: 0,
    y: 0
  };
  if (isOffsetParentAnElement || !isOffsetParentAnElement && !isFixed) {
    if (getNodeName(offsetParent) !== "body" || // https://github.com/popperjs/popper-core/issues/1078
    isScrollParent(documentElement)) {
      scroll = getNodeScroll(offsetParent);
    }
    if (isHTMLElement(offsetParent)) {
      offsets = getBoundingClientRect(offsetParent, true);
      offsets.x += offsetParent.clientLeft;
      offsets.y += offsetParent.clientTop;
    } else if (documentElement) {
      offsets.x = getWindowScrollBarX(documentElement);
    }
  }
  return {
    x: rect.left + scroll.scrollLeft - offsets.x,
    y: rect.top + scroll.scrollTop - offsets.y,
    width: rect.width,
    height: rect.height
  };
}
function order(modifiers) {
  var map = /* @__PURE__ */ new Map();
  var visited = /* @__PURE__ */ new Set();
  var result = [];
  modifiers.forEach(function(modifier) {
    map.set(modifier.name, modifier);
  });
  function sort2(modifier) {
    visited.add(modifier.name);
    var requires = [].concat(modifier.requires || [], modifier.requiresIfExists || []);
    requires.forEach(function(dep) {
      if (!visited.has(dep)) {
        var depModifier = map.get(dep);
        if (depModifier) {
          sort2(depModifier);
        }
      }
    });
    result.push(modifier);
  }
  modifiers.forEach(function(modifier) {
    if (!visited.has(modifier.name)) {
      sort2(modifier);
    }
  });
  return result;
}
function orderModifiers(modifiers) {
  var orderedModifiers = order(modifiers);
  return modifierPhases.reduce(function(acc, phase) {
    return acc.concat(orderedModifiers.filter(function(modifier) {
      return modifier.phase === phase;
    }));
  }, []);
}
function debounce(fn2) {
  var pending;
  return function() {
    if (!pending) {
      pending = new Promise(function(resolve) {
        Promise.resolve().then(function() {
          pending = void 0;
          resolve(fn2());
        });
      });
    }
    return pending;
  };
}
function mergeByName(modifiers) {
  var merged = modifiers.reduce(function(merged2, current) {
    var existing = merged2[current.name];
    merged2[current.name] = existing ? Object.assign({}, existing, current, {
      options: Object.assign({}, existing.options, current.options),
      data: Object.assign({}, existing.data, current.data)
    }) : current;
    return merged2;
  }, {});
  return Object.keys(merged).map(function(key2) {
    return merged[key2];
  });
}
var DEFAULT_OPTIONS = {
  placement: "bottom",
  modifiers: [],
  strategy: "absolute"
};
function areValidElements() {
  for (var _len = arguments.length, args = new Array(_len), _key = 0; _key < _len; _key++) {
    args[_key] = arguments[_key];
  }
  return !args.some(function(element) {
    return !(element && typeof element.getBoundingClientRect === "function");
  });
}
function popperGenerator(generatorOptions) {
  if (generatorOptions === void 0) {
    generatorOptions = {};
  }
  var _generatorOptions = generatorOptions, _generatorOptions$def = _generatorOptions.defaultModifiers, defaultModifiers2 = _generatorOptions$def === void 0 ? [] : _generatorOptions$def, _generatorOptions$def2 = _generatorOptions.defaultOptions, defaultOptions = _generatorOptions$def2 === void 0 ? DEFAULT_OPTIONS : _generatorOptions$def2;
  return function createPopper2(reference2, popper2, options) {
    if (options === void 0) {
      options = defaultOptions;
    }
    var state = {
      placement: "bottom",
      orderedModifiers: [],
      options: Object.assign({}, DEFAULT_OPTIONS, defaultOptions),
      modifiersData: {},
      elements: {
        reference: reference2,
        popper: popper2
      },
      attributes: {},
      styles: {}
    };
    var effectCleanupFns = [];
    var isDestroyed = false;
    var instance = {
      state,
      setOptions: function setOptions(setOptionsAction) {
        var options2 = typeof setOptionsAction === "function" ? setOptionsAction(state.options) : setOptionsAction;
        cleanupModifierEffects();
        state.options = Object.assign({}, defaultOptions, state.options, options2);
        state.scrollParents = {
          reference: isElement$1(reference2) ? listScrollParents(reference2) : reference2.contextElement ? listScrollParents(reference2.contextElement) : [],
          popper: listScrollParents(popper2)
        };
        var orderedModifiers = orderModifiers(mergeByName([].concat(defaultModifiers2, state.options.modifiers)));
        state.orderedModifiers = orderedModifiers.filter(function(m2) {
          return m2.enabled;
        });
        runModifierEffects();
        return instance.update();
      },
      // Sync update – it will always be executed, even if not necessary. This
      // is useful for low frequency updates where sync behavior simplifies the
      // logic.
      // For high frequency updates (e.g. `resize` and `scroll` events), always
      // prefer the async Popper#update method
      forceUpdate: function forceUpdate() {
        if (isDestroyed) {
          return;
        }
        var _state$elements = state.elements, reference3 = _state$elements.reference, popper3 = _state$elements.popper;
        if (!areValidElements(reference3, popper3)) {
          return;
        }
        state.rects = {
          reference: getCompositeRect(reference3, getOffsetParent(popper3), state.options.strategy === "fixed"),
          popper: getLayoutRect(popper3)
        };
        state.reset = false;
        state.placement = state.options.placement;
        state.orderedModifiers.forEach(function(modifier) {
          return state.modifiersData[modifier.name] = Object.assign({}, modifier.data);
        });
        for (var index = 0; index < state.orderedModifiers.length; index++) {
          if (state.reset === true) {
            state.reset = false;
            index = -1;
            continue;
          }
          var _state$orderedModifie = state.orderedModifiers[index], fn2 = _state$orderedModifie.fn, _state$orderedModifie2 = _state$orderedModifie.options, _options = _state$orderedModifie2 === void 0 ? {} : _state$orderedModifie2, name = _state$orderedModifie.name;
          if (typeof fn2 === "function") {
            state = fn2({
              state,
              options: _options,
              name,
              instance
            }) || state;
          }
        }
      },
      // Async and optimistically optimized update – it will not be executed if
      // not necessary (debounced to run at most once-per-tick)
      update: debounce(function() {
        return new Promise(function(resolve) {
          instance.forceUpdate();
          resolve(state);
        });
      }),
      destroy: function destroy() {
        cleanupModifierEffects();
        isDestroyed = true;
      }
    };
    if (!areValidElements(reference2, popper2)) {
      return instance;
    }
    instance.setOptions(options).then(function(state2) {
      if (!isDestroyed && options.onFirstUpdate) {
        options.onFirstUpdate(state2);
      }
    });
    function runModifierEffects() {
      state.orderedModifiers.forEach(function(_ref) {
        var name = _ref.name, _ref$options = _ref.options, options2 = _ref$options === void 0 ? {} : _ref$options, effect2 = _ref.effect;
        if (typeof effect2 === "function") {
          var cleanupFn = effect2({
            state,
            name,
            instance,
            options: options2
          });
          var noopFn = function noopFn2() {
          };
          effectCleanupFns.push(cleanupFn || noopFn);
        }
      });
    }
    function cleanupModifierEffects() {
      effectCleanupFns.forEach(function(fn2) {
        return fn2();
      });
      effectCleanupFns = [];
    }
    return instance;
  };
}
var createPopper$2 = /* @__PURE__ */ popperGenerator();
var defaultModifiers$1 = [eventListeners, popperOffsets$1, computeStyles$1, applyStyles$1];
var createPopper$1 = /* @__PURE__ */ popperGenerator({
  defaultModifiers: defaultModifiers$1
});
var defaultModifiers = [eventListeners, popperOffsets$1, computeStyles$1, applyStyles$1, offset$1, flip$1, preventOverflow$1, arrow$1, hide$1];
var createPopper = /* @__PURE__ */ popperGenerator({
  defaultModifiers
});
const Popper = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ Object.defineProperty({
  __proto__: null,
  afterMain,
  afterRead,
  afterWrite,
  applyStyles: applyStyles$1,
  arrow: arrow$1,
  auto,
  basePlacements,
  beforeMain,
  beforeRead,
  beforeWrite,
  bottom,
  clippingParents,
  computeStyles: computeStyles$1,
  createPopper,
  createPopperBase: createPopper$2,
  createPopperLite: createPopper$1,
  detectOverflow,
  end,
  eventListeners,
  flip: flip$1,
  hide: hide$1,
  left,
  main,
  modifierPhases,
  offset: offset$1,
  placements,
  popper,
  popperGenerator,
  popperOffsets: popperOffsets$1,
  preventOverflow: preventOverflow$1,
  read: read$1,
  reference,
  right,
  start,
  top,
  variationPlacements,
  viewport,
  write
}, Symbol.toStringTag, { value: "Module" }));
/*!
  * Bootstrap v5.3.3 (https://getbootstrap.com/)
  * Copyright 2011-2024 The Bootstrap Authors (https://github.com/twbs/bootstrap/graphs/contributors)
  * Licensed under MIT (https://github.com/twbs/bootstrap/blob/main/LICENSE)
  */
const elementMap = /* @__PURE__ */ new Map();
const Data = {
  set(element, key2, instance) {
    if (!elementMap.has(element)) {
      elementMap.set(element, /* @__PURE__ */ new Map());
    }
    const instanceMap = elementMap.get(element);
    if (!instanceMap.has(key2) && instanceMap.size !== 0) {
      console.error(`Bootstrap doesn't allow more than one instance per element. Bound instance: ${Array.from(instanceMap.keys())[0]}.`);
      return;
    }
    instanceMap.set(key2, instance);
  },
  get(element, key2) {
    if (elementMap.has(element)) {
      return elementMap.get(element).get(key2) || null;
    }
    return null;
  },
  remove(element, key2) {
    if (!elementMap.has(element)) {
      return;
    }
    const instanceMap = elementMap.get(element);
    instanceMap.delete(key2);
    if (instanceMap.size === 0) {
      elementMap.delete(element);
    }
  }
};
const MAX_UID = 1e6;
const MILLISECONDS_MULTIPLIER = 1e3;
const TRANSITION_END = "transitionend";
const parseSelector = (selector) => {
  if (selector && window.CSS && window.CSS.escape) {
    selector = selector.replace(/#([^\s"#']+)/g, (match, id) => `#${CSS.escape(id)}`);
  }
  return selector;
};
const toType = (object) => {
  if (object === null || object === void 0) {
    return `${object}`;
  }
  return Object.prototype.toString.call(object).match(/\s([a-z]+)/i)[1].toLowerCase();
};
const getUID = (prefix) => {
  do {
    prefix += Math.floor(Math.random() * MAX_UID);
  } while (document.getElementById(prefix));
  return prefix;
};
const getTransitionDurationFromElement = (element) => {
  if (!element) {
    return 0;
  }
  let {
    transitionDuration,
    transitionDelay
  } = window.getComputedStyle(element);
  const floatTransitionDuration = Number.parseFloat(transitionDuration);
  const floatTransitionDelay = Number.parseFloat(transitionDelay);
  if (!floatTransitionDuration && !floatTransitionDelay) {
    return 0;
  }
  transitionDuration = transitionDuration.split(",")[0];
  transitionDelay = transitionDelay.split(",")[0];
  return (Number.parseFloat(transitionDuration) + Number.parseFloat(transitionDelay)) * MILLISECONDS_MULTIPLIER;
};
const triggerTransitionEnd = (element) => {
  element.dispatchEvent(new Event(TRANSITION_END));
};
const isElement = (object) => {
  if (!object || typeof object !== "object") {
    return false;
  }
  if (typeof object.jquery !== "undefined") {
    object = object[0];
  }
  return typeof object.nodeType !== "undefined";
};
const getElement = (object) => {
  if (isElement(object)) {
    return object.jquery ? object[0] : object;
  }
  if (typeof object === "string" && object.length > 0) {
    return document.querySelector(parseSelector(object));
  }
  return null;
};
const isVisible = (element) => {
  if (!isElement(element) || element.getClientRects().length === 0) {
    return false;
  }
  const elementIsVisible = getComputedStyle(element).getPropertyValue("visibility") === "visible";
  const closedDetails = element.closest("details:not([open])");
  if (!closedDetails) {
    return elementIsVisible;
  }
  if (closedDetails !== element) {
    const summary = element.closest("summary");
    if (summary && summary.parentNode !== closedDetails) {
      return false;
    }
    if (summary === null) {
      return false;
    }
  }
  return elementIsVisible;
};
const isDisabled = (element) => {
  if (!element || element.nodeType !== Node.ELEMENT_NODE) {
    return true;
  }
  if (element.classList.contains("disabled")) {
    return true;
  }
  if (typeof element.disabled !== "undefined") {
    return element.disabled;
  }
  return element.hasAttribute("disabled") && element.getAttribute("disabled") !== "false";
};
const findShadowRoot = (element) => {
  if (!document.documentElement.attachShadow) {
    return null;
  }
  if (typeof element.getRootNode === "function") {
    const root2 = element.getRootNode();
    return root2 instanceof ShadowRoot ? root2 : null;
  }
  if (element instanceof ShadowRoot) {
    return element;
  }
  if (!element.parentNode) {
    return null;
  }
  return findShadowRoot(element.parentNode);
};
const noop = () => {
};
const reflow = (element) => {
  element.offsetHeight;
};
const getjQuery = () => {
  if (window.jQuery && !document.body.hasAttribute("data-bs-no-jquery")) {
    return window.jQuery;
  }
  return null;
};
const DOMContentLoadedCallbacks = [];
const onDOMContentLoaded = (callback) => {
  if (document.readyState === "loading") {
    if (!DOMContentLoadedCallbacks.length) {
      document.addEventListener("DOMContentLoaded", () => {
        for (const callback2 of DOMContentLoadedCallbacks) {
          callback2();
        }
      });
    }
    DOMContentLoadedCallbacks.push(callback);
  } else {
    callback();
  }
};
const isRTL = () => document.documentElement.dir === "rtl";
const defineJQueryPlugin = (plugin) => {
  onDOMContentLoaded(() => {
    const $2 = getjQuery();
    if ($2) {
      const name = plugin.NAME;
      const JQUERY_NO_CONFLICT = $2.fn[name];
      $2.fn[name] = plugin.jQueryInterface;
      $2.fn[name].Constructor = plugin;
      $2.fn[name].noConflict = () => {
        $2.fn[name] = JQUERY_NO_CONFLICT;
        return plugin.jQueryInterface;
      };
    }
  });
};
const execute = (possibleCallback, args = [], defaultValue = possibleCallback) => {
  return typeof possibleCallback === "function" ? possibleCallback(...args) : defaultValue;
};
const executeAfterTransition = (callback, transitionElement, waitForTransition = true) => {
  if (!waitForTransition) {
    execute(callback);
    return;
  }
  const durationPadding = 5;
  const emulatedDuration = getTransitionDurationFromElement(transitionElement) + durationPadding;
  let called = false;
  const handler = ({
    target
  }) => {
    if (target !== transitionElement) {
      return;
    }
    called = true;
    transitionElement.removeEventListener(TRANSITION_END, handler);
    execute(callback);
  };
  transitionElement.addEventListener(TRANSITION_END, handler);
  setTimeout(() => {
    if (!called) {
      triggerTransitionEnd(transitionElement);
    }
  }, emulatedDuration);
};
const getNextActiveElement = (list, activeElement, shouldGetNext, isCycleAllowed) => {
  const listLength = list.length;
  let index = list.indexOf(activeElement);
  if (index === -1) {
    return !shouldGetNext && isCycleAllowed ? list[listLength - 1] : list[0];
  }
  index += shouldGetNext ? 1 : -1;
  if (isCycleAllowed) {
    index = (index + listLength) % listLength;
  }
  return list[Math.max(0, Math.min(index, listLength - 1))];
};
const namespaceRegex = /[^.]*(?=\..*)\.|.*/;
const stripNameRegex = /\..*/;
const stripUidRegex = /::\d+$/;
const eventRegistry = {};
let uidEvent = 1;
const customEvents = {
  mouseenter: "mouseover",
  mouseleave: "mouseout"
};
const nativeEvents = /* @__PURE__ */ new Set(["click", "dblclick", "mouseup", "mousedown", "contextmenu", "mousewheel", "DOMMouseScroll", "mouseover", "mouseout", "mousemove", "selectstart", "selectend", "keydown", "keypress", "keyup", "orientationchange", "touchstart", "touchmove", "touchend", "touchcancel", "pointerdown", "pointermove", "pointerup", "pointerleave", "pointercancel", "gesturestart", "gesturechange", "gestureend", "focus", "blur", "change", "reset", "select", "submit", "focusin", "focusout", "load", "unload", "beforeunload", "resize", "move", "DOMContentLoaded", "readystatechange", "error", "abort", "scroll"]);
function makeEventUid(element, uid) {
  return uid && `${uid}::${uidEvent++}` || element.uidEvent || uidEvent++;
}
function getElementEvents(element) {
  const uid = makeEventUid(element);
  element.uidEvent = uid;
  eventRegistry[uid] = eventRegistry[uid] || {};
  return eventRegistry[uid];
}
function bootstrapHandler(element, fn2) {
  return function handler(event) {
    hydrateObj(event, {
      delegateTarget: element
    });
    if (handler.oneOff) {
      EventHandler.off(element, event.type, fn2);
    }
    return fn2.apply(element, [event]);
  };
}
function bootstrapDelegationHandler(element, selector, fn2) {
  return function handler(event) {
    const domElements = element.querySelectorAll(selector);
    for (let {
      target
    } = event; target && target !== this; target = target.parentNode) {
      for (const domElement of domElements) {
        if (domElement !== target) {
          continue;
        }
        hydrateObj(event, {
          delegateTarget: target
        });
        if (handler.oneOff) {
          EventHandler.off(element, event.type, selector, fn2);
        }
        return fn2.apply(target, [event]);
      }
    }
  };
}
function findHandler(events, callable, delegationSelector = null) {
  return Object.values(events).find((event) => event.callable === callable && event.delegationSelector === delegationSelector);
}
function normalizeParameters(originalTypeEvent, handler, delegationFunction) {
  const isDelegated = typeof handler === "string";
  const callable = isDelegated ? delegationFunction : handler || delegationFunction;
  let typeEvent = getTypeEvent(originalTypeEvent);
  if (!nativeEvents.has(typeEvent)) {
    typeEvent = originalTypeEvent;
  }
  return [isDelegated, callable, typeEvent];
}
function addHandler(element, originalTypeEvent, handler, delegationFunction, oneOff) {
  if (typeof originalTypeEvent !== "string" || !element) {
    return;
  }
  let [isDelegated, callable, typeEvent] = normalizeParameters(originalTypeEvent, handler, delegationFunction);
  if (originalTypeEvent in customEvents) {
    const wrapFunction = (fn3) => {
      return function(event) {
        if (!event.relatedTarget || event.relatedTarget !== event.delegateTarget && !event.delegateTarget.contains(event.relatedTarget)) {
          return fn3.call(this, event);
        }
      };
    };
    callable = wrapFunction(callable);
  }
  const events = getElementEvents(element);
  const handlers = events[typeEvent] || (events[typeEvent] = {});
  const previousFunction = findHandler(handlers, callable, isDelegated ? handler : null);
  if (previousFunction) {
    previousFunction.oneOff = previousFunction.oneOff && oneOff;
    return;
  }
  const uid = makeEventUid(callable, originalTypeEvent.replace(namespaceRegex, ""));
  const fn2 = isDelegated ? bootstrapDelegationHandler(element, handler, callable) : bootstrapHandler(element, callable);
  fn2.delegationSelector = isDelegated ? handler : null;
  fn2.callable = callable;
  fn2.oneOff = oneOff;
  fn2.uidEvent = uid;
  handlers[uid] = fn2;
  element.addEventListener(typeEvent, fn2, isDelegated);
}
function removeHandler(element, events, typeEvent, handler, delegationSelector) {
  const fn2 = findHandler(events[typeEvent], handler, delegationSelector);
  if (!fn2) {
    return;
  }
  element.removeEventListener(typeEvent, fn2, Boolean(delegationSelector));
  delete events[typeEvent][fn2.uidEvent];
}
function removeNamespacedHandlers(element, events, typeEvent, namespace) {
  const storeElementEvent = events[typeEvent] || {};
  for (const [handlerKey, event] of Object.entries(storeElementEvent)) {
    if (handlerKey.includes(namespace)) {
      removeHandler(element, events, typeEvent, event.callable, event.delegationSelector);
    }
  }
}
function getTypeEvent(event) {
  event = event.replace(stripNameRegex, "");
  return customEvents[event] || event;
}
const EventHandler = {
  on(element, event, handler, delegationFunction) {
    addHandler(element, event, handler, delegationFunction, false);
  },
  one(element, event, handler, delegationFunction) {
    addHandler(element, event, handler, delegationFunction, true);
  },
  off(element, originalTypeEvent, handler, delegationFunction) {
    if (typeof originalTypeEvent !== "string" || !element) {
      return;
    }
    const [isDelegated, callable, typeEvent] = normalizeParameters(originalTypeEvent, handler, delegationFunction);
    const inNamespace = typeEvent !== originalTypeEvent;
    const events = getElementEvents(element);
    const storeElementEvent = events[typeEvent] || {};
    const isNamespace = originalTypeEvent.startsWith(".");
    if (typeof callable !== "undefined") {
      if (!Object.keys(storeElementEvent).length) {
        return;
      }
      removeHandler(element, events, typeEvent, callable, isDelegated ? handler : null);
      return;
    }
    if (isNamespace) {
      for (const elementEvent of Object.keys(events)) {
        removeNamespacedHandlers(element, events, elementEvent, originalTypeEvent.slice(1));
      }
    }
    for (const [keyHandlers, event] of Object.entries(storeElementEvent)) {
      const handlerKey = keyHandlers.replace(stripUidRegex, "");
      if (!inNamespace || originalTypeEvent.includes(handlerKey)) {
        removeHandler(element, events, typeEvent, event.callable, event.delegationSelector);
      }
    }
  },
  trigger(element, event, args) {
    if (typeof event !== "string" || !element) {
      return null;
    }
    const $2 = getjQuery();
    const typeEvent = getTypeEvent(event);
    const inNamespace = event !== typeEvent;
    let jQueryEvent = null;
    let bubbles = true;
    let nativeDispatch = true;
    let defaultPrevented = false;
    if (inNamespace && $2) {
      jQueryEvent = $2.Event(event, args);
      $2(element).trigger(jQueryEvent);
      bubbles = !jQueryEvent.isPropagationStopped();
      nativeDispatch = !jQueryEvent.isImmediatePropagationStopped();
      defaultPrevented = jQueryEvent.isDefaultPrevented();
    }
    const evt = hydrateObj(new Event(event, {
      bubbles,
      cancelable: true
    }), args);
    if (defaultPrevented) {
      evt.preventDefault();
    }
    if (nativeDispatch) {
      element.dispatchEvent(evt);
    }
    if (evt.defaultPrevented && jQueryEvent) {
      jQueryEvent.preventDefault();
    }
    return evt;
  }
};
function hydrateObj(obj, meta = {}) {
  for (const [key2, value] of Object.entries(meta)) {
    try {
      obj[key2] = value;
    } catch (_unused) {
      Object.defineProperty(obj, key2, {
        configurable: true,
        get() {
          return value;
        }
      });
    }
  }
  return obj;
}
function normalizeData(value) {
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  if (value === Number(value).toString()) {
    return Number(value);
  }
  if (value === "" || value === "null") {
    return null;
  }
  if (typeof value !== "string") {
    return value;
  }
  try {
    return JSON.parse(decodeURIComponent(value));
  } catch (_unused) {
    return value;
  }
}
function normalizeDataKey(key2) {
  return key2.replace(/[A-Z]/g, (chr) => `-${chr.toLowerCase()}`);
}
const Manipulator = {
  setDataAttribute(element, key2, value) {
    element.setAttribute(`data-bs-${normalizeDataKey(key2)}`, value);
  },
  removeDataAttribute(element, key2) {
    element.removeAttribute(`data-bs-${normalizeDataKey(key2)}`);
  },
  getDataAttributes(element) {
    if (!element) {
      return {};
    }
    const attributes = {};
    const bsKeys = Object.keys(element.dataset).filter((key2) => key2.startsWith("bs") && !key2.startsWith("bsConfig"));
    for (const key2 of bsKeys) {
      let pureKey = key2.replace(/^bs/, "");
      pureKey = pureKey.charAt(0).toLowerCase() + pureKey.slice(1, pureKey.length);
      attributes[pureKey] = normalizeData(element.dataset[key2]);
    }
    return attributes;
  },
  getDataAttribute(element, key2) {
    return normalizeData(element.getAttribute(`data-bs-${normalizeDataKey(key2)}`));
  }
};
class Config {
  // Getters
  static get Default() {
    return {};
  }
  static get DefaultType() {
    return {};
  }
  static get NAME() {
    throw new Error('You have to implement the static method "NAME", for each component!');
  }
  _getConfig(config) {
    config = this._mergeConfigObj(config);
    config = this._configAfterMerge(config);
    this._typeCheckConfig(config);
    return config;
  }
  _configAfterMerge(config) {
    return config;
  }
  _mergeConfigObj(config, element) {
    const jsonConfig = isElement(element) ? Manipulator.getDataAttribute(element, "config") : {};
    return {
      ...this.constructor.Default,
      ...typeof jsonConfig === "object" ? jsonConfig : {},
      ...isElement(element) ? Manipulator.getDataAttributes(element) : {},
      ...typeof config === "object" ? config : {}
    };
  }
  _typeCheckConfig(config, configTypes = this.constructor.DefaultType) {
    for (const [property, expectedTypes] of Object.entries(configTypes)) {
      const value = config[property];
      const valueType = isElement(value) ? "element" : toType(value);
      if (!new RegExp(expectedTypes).test(valueType)) {
        throw new TypeError(`${this.constructor.NAME.toUpperCase()}: Option "${property}" provided type "${valueType}" but expected type "${expectedTypes}".`);
      }
    }
  }
}
const VERSION = "5.3.3";
class BaseComponent extends Config {
  constructor(element, config) {
    super();
    element = getElement(element);
    if (!element) {
      return;
    }
    this._element = element;
    this._config = this._getConfig(config);
    Data.set(this._element, this.constructor.DATA_KEY, this);
  }
  // Public
  dispose() {
    Data.remove(this._element, this.constructor.DATA_KEY);
    EventHandler.off(this._element, this.constructor.EVENT_KEY);
    for (const propertyName of Object.getOwnPropertyNames(this)) {
      this[propertyName] = null;
    }
  }
  _queueCallback(callback, element, isAnimated = true) {
    executeAfterTransition(callback, element, isAnimated);
  }
  _getConfig(config) {
    config = this._mergeConfigObj(config, this._element);
    config = this._configAfterMerge(config);
    this._typeCheckConfig(config);
    return config;
  }
  // Static
  static getInstance(element) {
    return Data.get(getElement(element), this.DATA_KEY);
  }
  static getOrCreateInstance(element, config = {}) {
    return this.getInstance(element) || new this(element, typeof config === "object" ? config : null);
  }
  static get VERSION() {
    return VERSION;
  }
  static get DATA_KEY() {
    return `bs.${this.NAME}`;
  }
  static get EVENT_KEY() {
    return `.${this.DATA_KEY}`;
  }
  static eventName(name) {
    return `${name}${this.EVENT_KEY}`;
  }
}
const getSelector = (element) => {
  let selector = element.getAttribute("data-bs-target");
  if (!selector || selector === "#") {
    let hrefAttribute = element.getAttribute("href");
    if (!hrefAttribute || !hrefAttribute.includes("#") && !hrefAttribute.startsWith(".")) {
      return null;
    }
    if (hrefAttribute.includes("#") && !hrefAttribute.startsWith("#")) {
      hrefAttribute = `#${hrefAttribute.split("#")[1]}`;
    }
    selector = hrefAttribute && hrefAttribute !== "#" ? hrefAttribute.trim() : null;
  }
  return selector ? selector.split(",").map((sel) => parseSelector(sel)).join(",") : null;
};
const SelectorEngine = {
  find(selector, element = document.documentElement) {
    return [].concat(...Element.prototype.querySelectorAll.call(element, selector));
  },
  findOne(selector, element = document.documentElement) {
    return Element.prototype.querySelector.call(element, selector);
  },
  children(element, selector) {
    return [].concat(...element.children).filter((child) => child.matches(selector));
  },
  parents(element, selector) {
    const parents = [];
    let ancestor = element.parentNode.closest(selector);
    while (ancestor) {
      parents.push(ancestor);
      ancestor = ancestor.parentNode.closest(selector);
    }
    return parents;
  },
  prev(element, selector) {
    let previous = element.previousElementSibling;
    while (previous) {
      if (previous.matches(selector)) {
        return [previous];
      }
      previous = previous.previousElementSibling;
    }
    return [];
  },
  // TODO: this is now unused; remove later along with prev()
  next(element, selector) {
    let next = element.nextElementSibling;
    while (next) {
      if (next.matches(selector)) {
        return [next];
      }
      next = next.nextElementSibling;
    }
    return [];
  },
  focusableChildren(element) {
    const focusables = ["a", "button", "input", "textarea", "select", "details", "[tabindex]", '[contenteditable="true"]'].map((selector) => `${selector}:not([tabindex^="-"])`).join(",");
    return this.find(focusables, element).filter((el) => !isDisabled(el) && isVisible(el));
  },
  getSelectorFromElement(element) {
    const selector = getSelector(element);
    if (selector) {
      return SelectorEngine.findOne(selector) ? selector : null;
    }
    return null;
  },
  getElementFromSelector(element) {
    const selector = getSelector(element);
    return selector ? SelectorEngine.findOne(selector) : null;
  },
  getMultipleElementsFromSelector(element) {
    const selector = getSelector(element);
    return selector ? SelectorEngine.find(selector) : [];
  }
};
const enableDismissTrigger = (component, method = "hide") => {
  const clickEvent = `click.dismiss${component.EVENT_KEY}`;
  const name = component.NAME;
  EventHandler.on(document, clickEvent, `[data-bs-dismiss="${name}"]`, function(event) {
    if (["A", "AREA"].includes(this.tagName)) {
      event.preventDefault();
    }
    if (isDisabled(this)) {
      return;
    }
    const target = SelectorEngine.getElementFromSelector(this) || this.closest(`.${name}`);
    const instance = component.getOrCreateInstance(target);
    instance[method]();
  });
};
const NAME$f = "alert";
const DATA_KEY$a = "bs.alert";
const EVENT_KEY$b = `.${DATA_KEY$a}`;
const EVENT_CLOSE = `close${EVENT_KEY$b}`;
const EVENT_CLOSED = `closed${EVENT_KEY$b}`;
const CLASS_NAME_FADE$5 = "fade";
const CLASS_NAME_SHOW$8 = "show";
class Alert extends BaseComponent {
  // Getters
  static get NAME() {
    return NAME$f;
  }
  // Public
  close() {
    const closeEvent = EventHandler.trigger(this._element, EVENT_CLOSE);
    if (closeEvent.defaultPrevented) {
      return;
    }
    this._element.classList.remove(CLASS_NAME_SHOW$8);
    const isAnimated = this._element.classList.contains(CLASS_NAME_FADE$5);
    this._queueCallback(() => this._destroyElement(), this._element, isAnimated);
  }
  // Private
  _destroyElement() {
    this._element.remove();
    EventHandler.trigger(this._element, EVENT_CLOSED);
    this.dispose();
  }
  // Static
  static jQueryInterface(config) {
    return this.each(function() {
      const data = Alert.getOrCreateInstance(this);
      if (typeof config !== "string") {
        return;
      }
      if (data[config] === void 0 || config.startsWith("_") || config === "constructor") {
        throw new TypeError(`No method named "${config}"`);
      }
      data[config](this);
    });
  }
}
enableDismissTrigger(Alert, "close");
defineJQueryPlugin(Alert);
const NAME$e = "button";
const DATA_KEY$9 = "bs.button";
const EVENT_KEY$a = `.${DATA_KEY$9}`;
const DATA_API_KEY$6 = ".data-api";
const CLASS_NAME_ACTIVE$3 = "active";
const SELECTOR_DATA_TOGGLE$5 = '[data-bs-toggle="button"]';
const EVENT_CLICK_DATA_API$6 = `click${EVENT_KEY$a}${DATA_API_KEY$6}`;
class Button extends BaseComponent {
  // Getters
  static get NAME() {
    return NAME$e;
  }
  // Public
  toggle() {
    this._element.setAttribute("aria-pressed", this._element.classList.toggle(CLASS_NAME_ACTIVE$3));
  }
  // Static
  static jQueryInterface(config) {
    return this.each(function() {
      const data = Button.getOrCreateInstance(this);
      if (config === "toggle") {
        data[config]();
      }
    });
  }
}
EventHandler.on(document, EVENT_CLICK_DATA_API$6, SELECTOR_DATA_TOGGLE$5, (event) => {
  event.preventDefault();
  const button = event.target.closest(SELECTOR_DATA_TOGGLE$5);
  const data = Button.getOrCreateInstance(button);
  data.toggle();
});
defineJQueryPlugin(Button);
const NAME$d = "swipe";
const EVENT_KEY$9 = ".bs.swipe";
const EVENT_TOUCHSTART = `touchstart${EVENT_KEY$9}`;
const EVENT_TOUCHMOVE = `touchmove${EVENT_KEY$9}`;
const EVENT_TOUCHEND = `touchend${EVENT_KEY$9}`;
const EVENT_POINTERDOWN = `pointerdown${EVENT_KEY$9}`;
const EVENT_POINTERUP = `pointerup${EVENT_KEY$9}`;
const POINTER_TYPE_TOUCH = "touch";
const POINTER_TYPE_PEN = "pen";
const CLASS_NAME_POINTER_EVENT = "pointer-event";
const SWIPE_THRESHOLD = 40;
const Default$c = {
  endCallback: null,
  leftCallback: null,
  rightCallback: null
};
const DefaultType$c = {
  endCallback: "(function|null)",
  leftCallback: "(function|null)",
  rightCallback: "(function|null)"
};
class Swipe extends Config {
  constructor(element, config) {
    super();
    this._element = element;
    if (!element || !Swipe.isSupported()) {
      return;
    }
    this._config = this._getConfig(config);
    this._deltaX = 0;
    this._supportPointerEvents = Boolean(window.PointerEvent);
    this._initEvents();
  }
  // Getters
  static get Default() {
    return Default$c;
  }
  static get DefaultType() {
    return DefaultType$c;
  }
  static get NAME() {
    return NAME$d;
  }
  // Public
  dispose() {
    EventHandler.off(this._element, EVENT_KEY$9);
  }
  // Private
  _start(event) {
    if (!this._supportPointerEvents) {
      this._deltaX = event.touches[0].clientX;
      return;
    }
    if (this._eventIsPointerPenTouch(event)) {
      this._deltaX = event.clientX;
    }
  }
  _end(event) {
    if (this._eventIsPointerPenTouch(event)) {
      this._deltaX = event.clientX - this._deltaX;
    }
    this._handleSwipe();
    execute(this._config.endCallback);
  }
  _move(event) {
    this._deltaX = event.touches && event.touches.length > 1 ? 0 : event.touches[0].clientX - this._deltaX;
  }
  _handleSwipe() {
    const absDeltaX = Math.abs(this._deltaX);
    if (absDeltaX <= SWIPE_THRESHOLD) {
      return;
    }
    const direction = absDeltaX / this._deltaX;
    this._deltaX = 0;
    if (!direction) {
      return;
    }
    execute(direction > 0 ? this._config.rightCallback : this._config.leftCallback);
  }
  _initEvents() {
    if (this._supportPointerEvents) {
      EventHandler.on(this._element, EVENT_POINTERDOWN, (event) => this._start(event));
      EventHandler.on(this._element, EVENT_POINTERUP, (event) => this._end(event));
      this._element.classList.add(CLASS_NAME_POINTER_EVENT);
    } else {
      EventHandler.on(this._element, EVENT_TOUCHSTART, (event) => this._start(event));
      EventHandler.on(this._element, EVENT_TOUCHMOVE, (event) => this._move(event));
      EventHandler.on(this._element, EVENT_TOUCHEND, (event) => this._end(event));
    }
  }
  _eventIsPointerPenTouch(event) {
    return this._supportPointerEvents && (event.pointerType === POINTER_TYPE_PEN || event.pointerType === POINTER_TYPE_TOUCH);
  }
  // Static
  static isSupported() {
    return "ontouchstart" in document.documentElement || navigator.maxTouchPoints > 0;
  }
}
const NAME$c = "carousel";
const DATA_KEY$8 = "bs.carousel";
const EVENT_KEY$8 = `.${DATA_KEY$8}`;
const DATA_API_KEY$5 = ".data-api";
const ARROW_LEFT_KEY$1 = "ArrowLeft";
const ARROW_RIGHT_KEY$1 = "ArrowRight";
const TOUCHEVENT_COMPAT_WAIT = 500;
const ORDER_NEXT = "next";
const ORDER_PREV = "prev";
const DIRECTION_LEFT = "left";
const DIRECTION_RIGHT = "right";
const EVENT_SLIDE = `slide${EVENT_KEY$8}`;
const EVENT_SLID = `slid${EVENT_KEY$8}`;
const EVENT_KEYDOWN$1 = `keydown${EVENT_KEY$8}`;
const EVENT_MOUSEENTER$1 = `mouseenter${EVENT_KEY$8}`;
const EVENT_MOUSELEAVE$1 = `mouseleave${EVENT_KEY$8}`;
const EVENT_DRAG_START = `dragstart${EVENT_KEY$8}`;
const EVENT_LOAD_DATA_API$3 = `load${EVENT_KEY$8}${DATA_API_KEY$5}`;
const EVENT_CLICK_DATA_API$5 = `click${EVENT_KEY$8}${DATA_API_KEY$5}`;
const CLASS_NAME_CAROUSEL = "carousel";
const CLASS_NAME_ACTIVE$2 = "active";
const CLASS_NAME_SLIDE = "slide";
const CLASS_NAME_END = "carousel-item-end";
const CLASS_NAME_START = "carousel-item-start";
const CLASS_NAME_NEXT = "carousel-item-next";
const CLASS_NAME_PREV = "carousel-item-prev";
const SELECTOR_ACTIVE = ".active";
const SELECTOR_ITEM = ".carousel-item";
const SELECTOR_ACTIVE_ITEM = SELECTOR_ACTIVE + SELECTOR_ITEM;
const SELECTOR_ITEM_IMG = ".carousel-item img";
const SELECTOR_INDICATORS = ".carousel-indicators";
const SELECTOR_DATA_SLIDE = "[data-bs-slide], [data-bs-slide-to]";
const SELECTOR_DATA_RIDE = '[data-bs-ride="carousel"]';
const KEY_TO_DIRECTION = {
  [ARROW_LEFT_KEY$1]: DIRECTION_RIGHT,
  [ARROW_RIGHT_KEY$1]: DIRECTION_LEFT
};
const Default$b = {
  interval: 5e3,
  keyboard: true,
  pause: "hover",
  ride: false,
  touch: true,
  wrap: true
};
const DefaultType$b = {
  interval: "(number|boolean)",
  // TODO:v6 remove boolean support
  keyboard: "boolean",
  pause: "(string|boolean)",
  ride: "(boolean|string)",
  touch: "boolean",
  wrap: "boolean"
};
class Carousel extends BaseComponent {
  constructor(element, config) {
    super(element, config);
    this._interval = null;
    this._activeElement = null;
    this._isSliding = false;
    this.touchTimeout = null;
    this._swipeHelper = null;
    this._indicatorsElement = SelectorEngine.findOne(SELECTOR_INDICATORS, this._element);
    this._addEventListeners();
    if (this._config.ride === CLASS_NAME_CAROUSEL) {
      this.cycle();
    }
  }
  // Getters
  static get Default() {
    return Default$b;
  }
  static get DefaultType() {
    return DefaultType$b;
  }
  static get NAME() {
    return NAME$c;
  }
  // Public
  next() {
    this._slide(ORDER_NEXT);
  }
  nextWhenVisible() {
    if (!document.hidden && isVisible(this._element)) {
      this.next();
    }
  }
  prev() {
    this._slide(ORDER_PREV);
  }
  pause() {
    if (this._isSliding) {
      triggerTransitionEnd(this._element);
    }
    this._clearInterval();
  }
  cycle() {
    this._clearInterval();
    this._updateInterval();
    this._interval = setInterval(() => this.nextWhenVisible(), this._config.interval);
  }
  _maybeEnableCycle() {
    if (!this._config.ride) {
      return;
    }
    if (this._isSliding) {
      EventHandler.one(this._element, EVENT_SLID, () => this.cycle());
      return;
    }
    this.cycle();
  }
  to(index) {
    const items = this._getItems();
    if (index > items.length - 1 || index < 0) {
      return;
    }
    if (this._isSliding) {
      EventHandler.one(this._element, EVENT_SLID, () => this.to(index));
      return;
    }
    const activeIndex = this._getItemIndex(this._getActive());
    if (activeIndex === index) {
      return;
    }
    const order2 = index > activeIndex ? ORDER_NEXT : ORDER_PREV;
    this._slide(order2, items[index]);
  }
  dispose() {
    if (this._swipeHelper) {
      this._swipeHelper.dispose();
    }
    super.dispose();
  }
  // Private
  _configAfterMerge(config) {
    config.defaultInterval = config.interval;
    return config;
  }
  _addEventListeners() {
    if (this._config.keyboard) {
      EventHandler.on(this._element, EVENT_KEYDOWN$1, (event) => this._keydown(event));
    }
    if (this._config.pause === "hover") {
      EventHandler.on(this._element, EVENT_MOUSEENTER$1, () => this.pause());
      EventHandler.on(this._element, EVENT_MOUSELEAVE$1, () => this._maybeEnableCycle());
    }
    if (this._config.touch && Swipe.isSupported()) {
      this._addTouchEventListeners();
    }
  }
  _addTouchEventListeners() {
    for (const img of SelectorEngine.find(SELECTOR_ITEM_IMG, this._element)) {
      EventHandler.on(img, EVENT_DRAG_START, (event) => event.preventDefault());
    }
    const endCallBack = () => {
      if (this._config.pause !== "hover") {
        return;
      }
      this.pause();
      if (this.touchTimeout) {
        clearTimeout(this.touchTimeout);
      }
      this.touchTimeout = setTimeout(() => this._maybeEnableCycle(), TOUCHEVENT_COMPAT_WAIT + this._config.interval);
    };
    const swipeConfig = {
      leftCallback: () => this._slide(this._directionToOrder(DIRECTION_LEFT)),
      rightCallback: () => this._slide(this._directionToOrder(DIRECTION_RIGHT)),
      endCallback: endCallBack
    };
    this._swipeHelper = new Swipe(this._element, swipeConfig);
  }
  _keydown(event) {
    if (/input|textarea/i.test(event.target.tagName)) {
      return;
    }
    const direction = KEY_TO_DIRECTION[event.key];
    if (direction) {
      event.preventDefault();
      this._slide(this._directionToOrder(direction));
    }
  }
  _getItemIndex(element) {
    return this._getItems().indexOf(element);
  }
  _setActiveIndicatorElement(index) {
    if (!this._indicatorsElement) {
      return;
    }
    const activeIndicator = SelectorEngine.findOne(SELECTOR_ACTIVE, this._indicatorsElement);
    activeIndicator.classList.remove(CLASS_NAME_ACTIVE$2);
    activeIndicator.removeAttribute("aria-current");
    const newActiveIndicator = SelectorEngine.findOne(`[data-bs-slide-to="${index}"]`, this._indicatorsElement);
    if (newActiveIndicator) {
      newActiveIndicator.classList.add(CLASS_NAME_ACTIVE$2);
      newActiveIndicator.setAttribute("aria-current", "true");
    }
  }
  _updateInterval() {
    const element = this._activeElement || this._getActive();
    if (!element) {
      return;
    }
    const elementInterval = Number.parseInt(element.getAttribute("data-bs-interval"), 10);
    this._config.interval = elementInterval || this._config.defaultInterval;
  }
  _slide(order2, element = null) {
    if (this._isSliding) {
      return;
    }
    const activeElement = this._getActive();
    const isNext = order2 === ORDER_NEXT;
    const nextElement = element || getNextActiveElement(this._getItems(), activeElement, isNext, this._config.wrap);
    if (nextElement === activeElement) {
      return;
    }
    const nextElementIndex = this._getItemIndex(nextElement);
    const triggerEvent = (eventName) => {
      return EventHandler.trigger(this._element, eventName, {
        relatedTarget: nextElement,
        direction: this._orderToDirection(order2),
        from: this._getItemIndex(activeElement),
        to: nextElementIndex
      });
    };
    const slideEvent = triggerEvent(EVENT_SLIDE);
    if (slideEvent.defaultPrevented) {
      return;
    }
    if (!activeElement || !nextElement) {
      return;
    }
    const isCycling = Boolean(this._interval);
    this.pause();
    this._isSliding = true;
    this._setActiveIndicatorElement(nextElementIndex);
    this._activeElement = nextElement;
    const directionalClassName = isNext ? CLASS_NAME_START : CLASS_NAME_END;
    const orderClassName = isNext ? CLASS_NAME_NEXT : CLASS_NAME_PREV;
    nextElement.classList.add(orderClassName);
    reflow(nextElement);
    activeElement.classList.add(directionalClassName);
    nextElement.classList.add(directionalClassName);
    const completeCallBack = () => {
      nextElement.classList.remove(directionalClassName, orderClassName);
      nextElement.classList.add(CLASS_NAME_ACTIVE$2);
      activeElement.classList.remove(CLASS_NAME_ACTIVE$2, orderClassName, directionalClassName);
      this._isSliding = false;
      triggerEvent(EVENT_SLID);
    };
    this._queueCallback(completeCallBack, activeElement, this._isAnimated());
    if (isCycling) {
      this.cycle();
    }
  }
  _isAnimated() {
    return this._element.classList.contains(CLASS_NAME_SLIDE);
  }
  _getActive() {
    return SelectorEngine.findOne(SELECTOR_ACTIVE_ITEM, this._element);
  }
  _getItems() {
    return SelectorEngine.find(SELECTOR_ITEM, this._element);
  }
  _clearInterval() {
    if (this._interval) {
      clearInterval(this._interval);
      this._interval = null;
    }
  }
  _directionToOrder(direction) {
    if (isRTL()) {
      return direction === DIRECTION_LEFT ? ORDER_PREV : ORDER_NEXT;
    }
    return direction === DIRECTION_LEFT ? ORDER_NEXT : ORDER_PREV;
  }
  _orderToDirection(order2) {
    if (isRTL()) {
      return order2 === ORDER_PREV ? DIRECTION_LEFT : DIRECTION_RIGHT;
    }
    return order2 === ORDER_PREV ? DIRECTION_RIGHT : DIRECTION_LEFT;
  }
  // Static
  static jQueryInterface(config) {
    return this.each(function() {
      const data = Carousel.getOrCreateInstance(this, config);
      if (typeof config === "number") {
        data.to(config);
        return;
      }
      if (typeof config === "string") {
        if (data[config] === void 0 || config.startsWith("_") || config === "constructor") {
          throw new TypeError(`No method named "${config}"`);
        }
        data[config]();
      }
    });
  }
}
EventHandler.on(document, EVENT_CLICK_DATA_API$5, SELECTOR_DATA_SLIDE, function(event) {
  const target = SelectorEngine.getElementFromSelector(this);
  if (!target || !target.classList.contains(CLASS_NAME_CAROUSEL)) {
    return;
  }
  event.preventDefault();
  const carousel = Carousel.getOrCreateInstance(target);
  const slideIndex = this.getAttribute("data-bs-slide-to");
  if (slideIndex) {
    carousel.to(slideIndex);
    carousel._maybeEnableCycle();
    return;
  }
  if (Manipulator.getDataAttribute(this, "slide") === "next") {
    carousel.next();
    carousel._maybeEnableCycle();
    return;
  }
  carousel.prev();
  carousel._maybeEnableCycle();
});
EventHandler.on(window, EVENT_LOAD_DATA_API$3, () => {
  const carousels = SelectorEngine.find(SELECTOR_DATA_RIDE);
  for (const carousel of carousels) {
    Carousel.getOrCreateInstance(carousel);
  }
});
defineJQueryPlugin(Carousel);
const NAME$b = "collapse";
const DATA_KEY$7 = "bs.collapse";
const EVENT_KEY$7 = `.${DATA_KEY$7}`;
const DATA_API_KEY$4 = ".data-api";
const EVENT_SHOW$6 = `show${EVENT_KEY$7}`;
const EVENT_SHOWN$6 = `shown${EVENT_KEY$7}`;
const EVENT_HIDE$6 = `hide${EVENT_KEY$7}`;
const EVENT_HIDDEN$6 = `hidden${EVENT_KEY$7}`;
const EVENT_CLICK_DATA_API$4 = `click${EVENT_KEY$7}${DATA_API_KEY$4}`;
const CLASS_NAME_SHOW$7 = "show";
const CLASS_NAME_COLLAPSE = "collapse";
const CLASS_NAME_COLLAPSING = "collapsing";
const CLASS_NAME_COLLAPSED = "collapsed";
const CLASS_NAME_DEEPER_CHILDREN = `:scope .${CLASS_NAME_COLLAPSE} .${CLASS_NAME_COLLAPSE}`;
const CLASS_NAME_HORIZONTAL = "collapse-horizontal";
const WIDTH = "width";
const HEIGHT = "height";
const SELECTOR_ACTIVES = ".collapse.show, .collapse.collapsing";
const SELECTOR_DATA_TOGGLE$4 = '[data-bs-toggle="collapse"]';
const Default$a = {
  parent: null,
  toggle: true
};
const DefaultType$a = {
  parent: "(null|element)",
  toggle: "boolean"
};
class Collapse extends BaseComponent {
  constructor(element, config) {
    super(element, config);
    this._isTransitioning = false;
    this._triggerArray = [];
    const toggleList = SelectorEngine.find(SELECTOR_DATA_TOGGLE$4);
    for (const elem of toggleList) {
      const selector = SelectorEngine.getSelectorFromElement(elem);
      const filterElement = SelectorEngine.find(selector).filter((foundElement) => foundElement === this._element);
      if (selector !== null && filterElement.length) {
        this._triggerArray.push(elem);
      }
    }
    this._initializeChildren();
    if (!this._config.parent) {
      this._addAriaAndCollapsedClass(this._triggerArray, this._isShown());
    }
    if (this._config.toggle) {
      this.toggle();
    }
  }
  // Getters
  static get Default() {
    return Default$a;
  }
  static get DefaultType() {
    return DefaultType$a;
  }
  static get NAME() {
    return NAME$b;
  }
  // Public
  toggle() {
    if (this._isShown()) {
      this.hide();
    } else {
      this.show();
    }
  }
  show() {
    if (this._isTransitioning || this._isShown()) {
      return;
    }
    let activeChildren = [];
    if (this._config.parent) {
      activeChildren = this._getFirstLevelChildren(SELECTOR_ACTIVES).filter((element) => element !== this._element).map((element) => Collapse.getOrCreateInstance(element, {
        toggle: false
      }));
    }
    if (activeChildren.length && activeChildren[0]._isTransitioning) {
      return;
    }
    const startEvent = EventHandler.trigger(this._element, EVENT_SHOW$6);
    if (startEvent.defaultPrevented) {
      return;
    }
    for (const activeInstance of activeChildren) {
      activeInstance.hide();
    }
    const dimension = this._getDimension();
    this._element.classList.remove(CLASS_NAME_COLLAPSE);
    this._element.classList.add(CLASS_NAME_COLLAPSING);
    this._element.style[dimension] = 0;
    this._addAriaAndCollapsedClass(this._triggerArray, true);
    this._isTransitioning = true;
    const complete = () => {
      this._isTransitioning = false;
      this._element.classList.remove(CLASS_NAME_COLLAPSING);
      this._element.classList.add(CLASS_NAME_COLLAPSE, CLASS_NAME_SHOW$7);
      this._element.style[dimension] = "";
      EventHandler.trigger(this._element, EVENT_SHOWN$6);
    };
    const capitalizedDimension = dimension[0].toUpperCase() + dimension.slice(1);
    const scrollSize = `scroll${capitalizedDimension}`;
    this._queueCallback(complete, this._element, true);
    this._element.style[dimension] = `${this._element[scrollSize]}px`;
  }
  hide() {
    if (this._isTransitioning || !this._isShown()) {
      return;
    }
    const startEvent = EventHandler.trigger(this._element, EVENT_HIDE$6);
    if (startEvent.defaultPrevented) {
      return;
    }
    const dimension = this._getDimension();
    this._element.style[dimension] = `${this._element.getBoundingClientRect()[dimension]}px`;
    reflow(this._element);
    this._element.classList.add(CLASS_NAME_COLLAPSING);
    this._element.classList.remove(CLASS_NAME_COLLAPSE, CLASS_NAME_SHOW$7);
    for (const trigger of this._triggerArray) {
      const element = SelectorEngine.getElementFromSelector(trigger);
      if (element && !this._isShown(element)) {
        this._addAriaAndCollapsedClass([trigger], false);
      }
    }
    this._isTransitioning = true;
    const complete = () => {
      this._isTransitioning = false;
      this._element.classList.remove(CLASS_NAME_COLLAPSING);
      this._element.classList.add(CLASS_NAME_COLLAPSE);
      EventHandler.trigger(this._element, EVENT_HIDDEN$6);
    };
    this._element.style[dimension] = "";
    this._queueCallback(complete, this._element, true);
  }
  _isShown(element = this._element) {
    return element.classList.contains(CLASS_NAME_SHOW$7);
  }
  // Private
  _configAfterMerge(config) {
    config.toggle = Boolean(config.toggle);
    config.parent = getElement(config.parent);
    return config;
  }
  _getDimension() {
    return this._element.classList.contains(CLASS_NAME_HORIZONTAL) ? WIDTH : HEIGHT;
  }
  _initializeChildren() {
    if (!this._config.parent) {
      return;
    }
    const children = this._getFirstLevelChildren(SELECTOR_DATA_TOGGLE$4);
    for (const element of children) {
      const selected = SelectorEngine.getElementFromSelector(element);
      if (selected) {
        this._addAriaAndCollapsedClass([element], this._isShown(selected));
      }
    }
  }
  _getFirstLevelChildren(selector) {
    const children = SelectorEngine.find(CLASS_NAME_DEEPER_CHILDREN, this._config.parent);
    return SelectorEngine.find(selector, this._config.parent).filter((element) => !children.includes(element));
  }
  _addAriaAndCollapsedClass(triggerArray, isOpen) {
    if (!triggerArray.length) {
      return;
    }
    for (const element of triggerArray) {
      element.classList.toggle(CLASS_NAME_COLLAPSED, !isOpen);
      element.setAttribute("aria-expanded", isOpen);
    }
  }
  // Static
  static jQueryInterface(config) {
    const _config = {};
    if (typeof config === "string" && /show|hide/.test(config)) {
      _config.toggle = false;
    }
    return this.each(function() {
      const data = Collapse.getOrCreateInstance(this, _config);
      if (typeof config === "string") {
        if (typeof data[config] === "undefined") {
          throw new TypeError(`No method named "${config}"`);
        }
        data[config]();
      }
    });
  }
}
EventHandler.on(document, EVENT_CLICK_DATA_API$4, SELECTOR_DATA_TOGGLE$4, function(event) {
  if (event.target.tagName === "A" || event.delegateTarget && event.delegateTarget.tagName === "A") {
    event.preventDefault();
  }
  for (const element of SelectorEngine.getMultipleElementsFromSelector(this)) {
    Collapse.getOrCreateInstance(element, {
      toggle: false
    }).toggle();
  }
});
defineJQueryPlugin(Collapse);
const NAME$a = "dropdown";
const DATA_KEY$6 = "bs.dropdown";
const EVENT_KEY$6 = `.${DATA_KEY$6}`;
const DATA_API_KEY$3 = ".data-api";
const ESCAPE_KEY$2 = "Escape";
const TAB_KEY$1 = "Tab";
const ARROW_UP_KEY$1 = "ArrowUp";
const ARROW_DOWN_KEY$1 = "ArrowDown";
const RIGHT_MOUSE_BUTTON = 2;
const EVENT_HIDE$5 = `hide${EVENT_KEY$6}`;
const EVENT_HIDDEN$5 = `hidden${EVENT_KEY$6}`;
const EVENT_SHOW$5 = `show${EVENT_KEY$6}`;
const EVENT_SHOWN$5 = `shown${EVENT_KEY$6}`;
const EVENT_CLICK_DATA_API$3 = `click${EVENT_KEY$6}${DATA_API_KEY$3}`;
const EVENT_KEYDOWN_DATA_API = `keydown${EVENT_KEY$6}${DATA_API_KEY$3}`;
const EVENT_KEYUP_DATA_API = `keyup${EVENT_KEY$6}${DATA_API_KEY$3}`;
const CLASS_NAME_SHOW$6 = "show";
const CLASS_NAME_DROPUP = "dropup";
const CLASS_NAME_DROPEND = "dropend";
const CLASS_NAME_DROPSTART = "dropstart";
const CLASS_NAME_DROPUP_CENTER = "dropup-center";
const CLASS_NAME_DROPDOWN_CENTER = "dropdown-center";
const SELECTOR_DATA_TOGGLE$3 = '[data-bs-toggle="dropdown"]:not(.disabled):not(:disabled)';
const SELECTOR_DATA_TOGGLE_SHOWN = `${SELECTOR_DATA_TOGGLE$3}.${CLASS_NAME_SHOW$6}`;
const SELECTOR_MENU = ".dropdown-menu";
const SELECTOR_NAVBAR = ".navbar";
const SELECTOR_NAVBAR_NAV = ".navbar-nav";
const SELECTOR_VISIBLE_ITEMS = ".dropdown-menu .dropdown-item:not(.disabled):not(:disabled)";
const PLACEMENT_TOP = isRTL() ? "top-end" : "top-start";
const PLACEMENT_TOPEND = isRTL() ? "top-start" : "top-end";
const PLACEMENT_BOTTOM = isRTL() ? "bottom-end" : "bottom-start";
const PLACEMENT_BOTTOMEND = isRTL() ? "bottom-start" : "bottom-end";
const PLACEMENT_RIGHT = isRTL() ? "left-start" : "right-start";
const PLACEMENT_LEFT = isRTL() ? "right-start" : "left-start";
const PLACEMENT_TOPCENTER = "top";
const PLACEMENT_BOTTOMCENTER = "bottom";
const Default$9 = {
  autoClose: true,
  boundary: "clippingParents",
  display: "dynamic",
  offset: [0, 2],
  popperConfig: null,
  reference: "toggle"
};
const DefaultType$9 = {
  autoClose: "(boolean|string)",
  boundary: "(string|element)",
  display: "string",
  offset: "(array|string|function)",
  popperConfig: "(null|object|function)",
  reference: "(string|element|object)"
};
class Dropdown extends BaseComponent {
  constructor(element, config) {
    super(element, config);
    this._popper = null;
    this._parent = this._element.parentNode;
    this._menu = SelectorEngine.next(this._element, SELECTOR_MENU)[0] || SelectorEngine.prev(this._element, SELECTOR_MENU)[0] || SelectorEngine.findOne(SELECTOR_MENU, this._parent);
    this._inNavbar = this._detectNavbar();
  }
  // Getters
  static get Default() {
    return Default$9;
  }
  static get DefaultType() {
    return DefaultType$9;
  }
  static get NAME() {
    return NAME$a;
  }
  // Public
  toggle() {
    return this._isShown() ? this.hide() : this.show();
  }
  show() {
    if (isDisabled(this._element) || this._isShown()) {
      return;
    }
    const relatedTarget = {
      relatedTarget: this._element
    };
    const showEvent = EventHandler.trigger(this._element, EVENT_SHOW$5, relatedTarget);
    if (showEvent.defaultPrevented) {
      return;
    }
    this._createPopper();
    if ("ontouchstart" in document.documentElement && !this._parent.closest(SELECTOR_NAVBAR_NAV)) {
      for (const element of [].concat(...document.body.children)) {
        EventHandler.on(element, "mouseover", noop);
      }
    }
    this._element.focus();
    this._element.setAttribute("aria-expanded", true);
    this._menu.classList.add(CLASS_NAME_SHOW$6);
    this._element.classList.add(CLASS_NAME_SHOW$6);
    EventHandler.trigger(this._element, EVENT_SHOWN$5, relatedTarget);
  }
  hide() {
    if (isDisabled(this._element) || !this._isShown()) {
      return;
    }
    const relatedTarget = {
      relatedTarget: this._element
    };
    this._completeHide(relatedTarget);
  }
  dispose() {
    if (this._popper) {
      this._popper.destroy();
    }
    super.dispose();
  }
  update() {
    this._inNavbar = this._detectNavbar();
    if (this._popper) {
      this._popper.update();
    }
  }
  // Private
  _completeHide(relatedTarget) {
    const hideEvent = EventHandler.trigger(this._element, EVENT_HIDE$5, relatedTarget);
    if (hideEvent.defaultPrevented) {
      return;
    }
    if ("ontouchstart" in document.documentElement) {
      for (const element of [].concat(...document.body.children)) {
        EventHandler.off(element, "mouseover", noop);
      }
    }
    if (this._popper) {
      this._popper.destroy();
    }
    this._menu.classList.remove(CLASS_NAME_SHOW$6);
    this._element.classList.remove(CLASS_NAME_SHOW$6);
    this._element.setAttribute("aria-expanded", "false");
    Manipulator.removeDataAttribute(this._menu, "popper");
    EventHandler.trigger(this._element, EVENT_HIDDEN$5, relatedTarget);
  }
  _getConfig(config) {
    config = super._getConfig(config);
    if (typeof config.reference === "object" && !isElement(config.reference) && typeof config.reference.getBoundingClientRect !== "function") {
      throw new TypeError(`${NAME$a.toUpperCase()}: Option "reference" provided type "object" without a required "getBoundingClientRect" method.`);
    }
    return config;
  }
  _createPopper() {
    if (typeof Popper === "undefined") {
      throw new TypeError("Bootstrap's dropdowns require Popper (https://popper.js.org)");
    }
    let referenceElement = this._element;
    if (this._config.reference === "parent") {
      referenceElement = this._parent;
    } else if (isElement(this._config.reference)) {
      referenceElement = getElement(this._config.reference);
    } else if (typeof this._config.reference === "object") {
      referenceElement = this._config.reference;
    }
    const popperConfig = this._getPopperConfig();
    this._popper = createPopper(referenceElement, this._menu, popperConfig);
  }
  _isShown() {
    return this._menu.classList.contains(CLASS_NAME_SHOW$6);
  }
  _getPlacement() {
    const parentDropdown = this._parent;
    if (parentDropdown.classList.contains(CLASS_NAME_DROPEND)) {
      return PLACEMENT_RIGHT;
    }
    if (parentDropdown.classList.contains(CLASS_NAME_DROPSTART)) {
      return PLACEMENT_LEFT;
    }
    if (parentDropdown.classList.contains(CLASS_NAME_DROPUP_CENTER)) {
      return PLACEMENT_TOPCENTER;
    }
    if (parentDropdown.classList.contains(CLASS_NAME_DROPDOWN_CENTER)) {
      return PLACEMENT_BOTTOMCENTER;
    }
    const isEnd = getComputedStyle(this._menu).getPropertyValue("--bs-position").trim() === "end";
    if (parentDropdown.classList.contains(CLASS_NAME_DROPUP)) {
      return isEnd ? PLACEMENT_TOPEND : PLACEMENT_TOP;
    }
    return isEnd ? PLACEMENT_BOTTOMEND : PLACEMENT_BOTTOM;
  }
  _detectNavbar() {
    return this._element.closest(SELECTOR_NAVBAR) !== null;
  }
  _getOffset() {
    const {
      offset: offset2
    } = this._config;
    if (typeof offset2 === "string") {
      return offset2.split(",").map((value) => Number.parseInt(value, 10));
    }
    if (typeof offset2 === "function") {
      return (popperData) => offset2(popperData, this._element);
    }
    return offset2;
  }
  _getPopperConfig() {
    const defaultBsPopperConfig = {
      placement: this._getPlacement(),
      modifiers: [{
        name: "preventOverflow",
        options: {
          boundary: this._config.boundary
        }
      }, {
        name: "offset",
        options: {
          offset: this._getOffset()
        }
      }]
    };
    if (this._inNavbar || this._config.display === "static") {
      Manipulator.setDataAttribute(this._menu, "popper", "static");
      defaultBsPopperConfig.modifiers = [{
        name: "applyStyles",
        enabled: false
      }];
    }
    return {
      ...defaultBsPopperConfig,
      ...execute(this._config.popperConfig, [defaultBsPopperConfig])
    };
  }
  _selectMenuItem({
    key: key2,
    target
  }) {
    const items = SelectorEngine.find(SELECTOR_VISIBLE_ITEMS, this._menu).filter((element) => isVisible(element));
    if (!items.length) {
      return;
    }
    getNextActiveElement(items, target, key2 === ARROW_DOWN_KEY$1, !items.includes(target)).focus();
  }
  // Static
  static jQueryInterface(config) {
    return this.each(function() {
      const data = Dropdown.getOrCreateInstance(this, config);
      if (typeof config !== "string") {
        return;
      }
      if (typeof data[config] === "undefined") {
        throw new TypeError(`No method named "${config}"`);
      }
      data[config]();
    });
  }
  static clearMenus(event) {
    if (event.button === RIGHT_MOUSE_BUTTON || event.type === "keyup" && event.key !== TAB_KEY$1) {
      return;
    }
    const openToggles = SelectorEngine.find(SELECTOR_DATA_TOGGLE_SHOWN);
    for (const toggle of openToggles) {
      const context = Dropdown.getInstance(toggle);
      if (!context || context._config.autoClose === false) {
        continue;
      }
      const composedPath = event.composedPath();
      const isMenuTarget = composedPath.includes(context._menu);
      if (composedPath.includes(context._element) || context._config.autoClose === "inside" && !isMenuTarget || context._config.autoClose === "outside" && isMenuTarget) {
        continue;
      }
      if (context._menu.contains(event.target) && (event.type === "keyup" && event.key === TAB_KEY$1 || /input|select|option|textarea|form/i.test(event.target.tagName))) {
        continue;
      }
      const relatedTarget = {
        relatedTarget: context._element
      };
      if (event.type === "click") {
        relatedTarget.clickEvent = event;
      }
      context._completeHide(relatedTarget);
    }
  }
  static dataApiKeydownHandler(event) {
    const isInput = /input|textarea/i.test(event.target.tagName);
    const isEscapeEvent = event.key === ESCAPE_KEY$2;
    const isUpOrDownEvent = [ARROW_UP_KEY$1, ARROW_DOWN_KEY$1].includes(event.key);
    if (!isUpOrDownEvent && !isEscapeEvent) {
      return;
    }
    if (isInput && !isEscapeEvent) {
      return;
    }
    event.preventDefault();
    const getToggleButton = this.matches(SELECTOR_DATA_TOGGLE$3) ? this : SelectorEngine.prev(this, SELECTOR_DATA_TOGGLE$3)[0] || SelectorEngine.next(this, SELECTOR_DATA_TOGGLE$3)[0] || SelectorEngine.findOne(SELECTOR_DATA_TOGGLE$3, event.delegateTarget.parentNode);
    const instance = Dropdown.getOrCreateInstance(getToggleButton);
    if (isUpOrDownEvent) {
      event.stopPropagation();
      instance.show();
      instance._selectMenuItem(event);
      return;
    }
    if (instance._isShown()) {
      event.stopPropagation();
      instance.hide();
      getToggleButton.focus();
    }
  }
}
EventHandler.on(document, EVENT_KEYDOWN_DATA_API, SELECTOR_DATA_TOGGLE$3, Dropdown.dataApiKeydownHandler);
EventHandler.on(document, EVENT_KEYDOWN_DATA_API, SELECTOR_MENU, Dropdown.dataApiKeydownHandler);
EventHandler.on(document, EVENT_CLICK_DATA_API$3, Dropdown.clearMenus);
EventHandler.on(document, EVENT_KEYUP_DATA_API, Dropdown.clearMenus);
EventHandler.on(document, EVENT_CLICK_DATA_API$3, SELECTOR_DATA_TOGGLE$3, function(event) {
  event.preventDefault();
  Dropdown.getOrCreateInstance(this).toggle();
});
defineJQueryPlugin(Dropdown);
const NAME$9 = "backdrop";
const CLASS_NAME_FADE$4 = "fade";
const CLASS_NAME_SHOW$5 = "show";
const EVENT_MOUSEDOWN = `mousedown.bs.${NAME$9}`;
const Default$8 = {
  className: "modal-backdrop",
  clickCallback: null,
  isAnimated: false,
  isVisible: true,
  // if false, we use the backdrop helper without adding any element to the dom
  rootElement: "body"
  // give the choice to place backdrop under different elements
};
const DefaultType$8 = {
  className: "string",
  clickCallback: "(function|null)",
  isAnimated: "boolean",
  isVisible: "boolean",
  rootElement: "(element|string)"
};
class Backdrop extends Config {
  constructor(config) {
    super();
    this._config = this._getConfig(config);
    this._isAppended = false;
    this._element = null;
  }
  // Getters
  static get Default() {
    return Default$8;
  }
  static get DefaultType() {
    return DefaultType$8;
  }
  static get NAME() {
    return NAME$9;
  }
  // Public
  show(callback) {
    if (!this._config.isVisible) {
      execute(callback);
      return;
    }
    this._append();
    const element = this._getElement();
    if (this._config.isAnimated) {
      reflow(element);
    }
    element.classList.add(CLASS_NAME_SHOW$5);
    this._emulateAnimation(() => {
      execute(callback);
    });
  }
  hide(callback) {
    if (!this._config.isVisible) {
      execute(callback);
      return;
    }
    this._getElement().classList.remove(CLASS_NAME_SHOW$5);
    this._emulateAnimation(() => {
      this.dispose();
      execute(callback);
    });
  }
  dispose() {
    if (!this._isAppended) {
      return;
    }
    EventHandler.off(this._element, EVENT_MOUSEDOWN);
    this._element.remove();
    this._isAppended = false;
  }
  // Private
  _getElement() {
    if (!this._element) {
      const backdrop = document.createElement("div");
      backdrop.className = this._config.className;
      if (this._config.isAnimated) {
        backdrop.classList.add(CLASS_NAME_FADE$4);
      }
      this._element = backdrop;
    }
    return this._element;
  }
  _configAfterMerge(config) {
    config.rootElement = getElement(config.rootElement);
    return config;
  }
  _append() {
    if (this._isAppended) {
      return;
    }
    const element = this._getElement();
    this._config.rootElement.append(element);
    EventHandler.on(element, EVENT_MOUSEDOWN, () => {
      execute(this._config.clickCallback);
    });
    this._isAppended = true;
  }
  _emulateAnimation(callback) {
    executeAfterTransition(callback, this._getElement(), this._config.isAnimated);
  }
}
const NAME$8 = "focustrap";
const DATA_KEY$5 = "bs.focustrap";
const EVENT_KEY$5 = `.${DATA_KEY$5}`;
const EVENT_FOCUSIN$2 = `focusin${EVENT_KEY$5}`;
const EVENT_KEYDOWN_TAB = `keydown.tab${EVENT_KEY$5}`;
const TAB_KEY = "Tab";
const TAB_NAV_FORWARD = "forward";
const TAB_NAV_BACKWARD = "backward";
const Default$7 = {
  autofocus: true,
  trapElement: null
  // The element to trap focus inside of
};
const DefaultType$7 = {
  autofocus: "boolean",
  trapElement: "element"
};
class FocusTrap extends Config {
  constructor(config) {
    super();
    this._config = this._getConfig(config);
    this._isActive = false;
    this._lastTabNavDirection = null;
  }
  // Getters
  static get Default() {
    return Default$7;
  }
  static get DefaultType() {
    return DefaultType$7;
  }
  static get NAME() {
    return NAME$8;
  }
  // Public
  activate() {
    if (this._isActive) {
      return;
    }
    if (this._config.autofocus) {
      this._config.trapElement.focus();
    }
    EventHandler.off(document, EVENT_KEY$5);
    EventHandler.on(document, EVENT_FOCUSIN$2, (event) => this._handleFocusin(event));
    EventHandler.on(document, EVENT_KEYDOWN_TAB, (event) => this._handleKeydown(event));
    this._isActive = true;
  }
  deactivate() {
    if (!this._isActive) {
      return;
    }
    this._isActive = false;
    EventHandler.off(document, EVENT_KEY$5);
  }
  // Private
  _handleFocusin(event) {
    const {
      trapElement
    } = this._config;
    if (event.target === document || event.target === trapElement || trapElement.contains(event.target)) {
      return;
    }
    const elements = SelectorEngine.focusableChildren(trapElement);
    if (elements.length === 0) {
      trapElement.focus();
    } else if (this._lastTabNavDirection === TAB_NAV_BACKWARD) {
      elements[elements.length - 1].focus();
    } else {
      elements[0].focus();
    }
  }
  _handleKeydown(event) {
    if (event.key !== TAB_KEY) {
      return;
    }
    this._lastTabNavDirection = event.shiftKey ? TAB_NAV_BACKWARD : TAB_NAV_FORWARD;
  }
}
const SELECTOR_FIXED_CONTENT = ".fixed-top, .fixed-bottom, .is-fixed, .sticky-top";
const SELECTOR_STICKY_CONTENT = ".sticky-top";
const PROPERTY_PADDING = "padding-right";
const PROPERTY_MARGIN = "margin-right";
class ScrollBarHelper {
  constructor() {
    this._element = document.body;
  }
  // Public
  getWidth() {
    const documentWidth = document.documentElement.clientWidth;
    return Math.abs(window.innerWidth - documentWidth);
  }
  hide() {
    const width = this.getWidth();
    this._disableOverFlow();
    this._setElementAttributes(this._element, PROPERTY_PADDING, (calculatedValue) => calculatedValue + width);
    this._setElementAttributes(SELECTOR_FIXED_CONTENT, PROPERTY_PADDING, (calculatedValue) => calculatedValue + width);
    this._setElementAttributes(SELECTOR_STICKY_CONTENT, PROPERTY_MARGIN, (calculatedValue) => calculatedValue - width);
  }
  reset() {
    this._resetElementAttributes(this._element, "overflow");
    this._resetElementAttributes(this._element, PROPERTY_PADDING);
    this._resetElementAttributes(SELECTOR_FIXED_CONTENT, PROPERTY_PADDING);
    this._resetElementAttributes(SELECTOR_STICKY_CONTENT, PROPERTY_MARGIN);
  }
  isOverflowing() {
    return this.getWidth() > 0;
  }
  // Private
  _disableOverFlow() {
    this._saveInitialAttribute(this._element, "overflow");
    this._element.style.overflow = "hidden";
  }
  _setElementAttributes(selector, styleProperty, callback) {
    const scrollbarWidth = this.getWidth();
    const manipulationCallBack = (element) => {
      if (element !== this._element && window.innerWidth > element.clientWidth + scrollbarWidth) {
        return;
      }
      this._saveInitialAttribute(element, styleProperty);
      const calculatedValue = window.getComputedStyle(element).getPropertyValue(styleProperty);
      element.style.setProperty(styleProperty, `${callback(Number.parseFloat(calculatedValue))}px`);
    };
    this._applyManipulationCallback(selector, manipulationCallBack);
  }
  _saveInitialAttribute(element, styleProperty) {
    const actualValue = element.style.getPropertyValue(styleProperty);
    if (actualValue) {
      Manipulator.setDataAttribute(element, styleProperty, actualValue);
    }
  }
  _resetElementAttributes(selector, styleProperty) {
    const manipulationCallBack = (element) => {
      const value = Manipulator.getDataAttribute(element, styleProperty);
      if (value === null) {
        element.style.removeProperty(styleProperty);
        return;
      }
      Manipulator.removeDataAttribute(element, styleProperty);
      element.style.setProperty(styleProperty, value);
    };
    this._applyManipulationCallback(selector, manipulationCallBack);
  }
  _applyManipulationCallback(selector, callBack) {
    if (isElement(selector)) {
      callBack(selector);
      return;
    }
    for (const sel of SelectorEngine.find(selector, this._element)) {
      callBack(sel);
    }
  }
}
const NAME$7 = "modal";
const DATA_KEY$4 = "bs.modal";
const EVENT_KEY$4 = `.${DATA_KEY$4}`;
const DATA_API_KEY$2 = ".data-api";
const ESCAPE_KEY$1 = "Escape";
const EVENT_HIDE$4 = `hide${EVENT_KEY$4}`;
const EVENT_HIDE_PREVENTED$1 = `hidePrevented${EVENT_KEY$4}`;
const EVENT_HIDDEN$4 = `hidden${EVENT_KEY$4}`;
const EVENT_SHOW$4 = `show${EVENT_KEY$4}`;
const EVENT_SHOWN$4 = `shown${EVENT_KEY$4}`;
const EVENT_RESIZE$1 = `resize${EVENT_KEY$4}`;
const EVENT_CLICK_DISMISS = `click.dismiss${EVENT_KEY$4}`;
const EVENT_MOUSEDOWN_DISMISS = `mousedown.dismiss${EVENT_KEY$4}`;
const EVENT_KEYDOWN_DISMISS$1 = `keydown.dismiss${EVENT_KEY$4}`;
const EVENT_CLICK_DATA_API$2 = `click${EVENT_KEY$4}${DATA_API_KEY$2}`;
const CLASS_NAME_OPEN = "modal-open";
const CLASS_NAME_FADE$3 = "fade";
const CLASS_NAME_SHOW$4 = "show";
const CLASS_NAME_STATIC = "modal-static";
const OPEN_SELECTOR$1 = ".modal.show";
const SELECTOR_DIALOG = ".modal-dialog";
const SELECTOR_MODAL_BODY = ".modal-body";
const SELECTOR_DATA_TOGGLE$2 = '[data-bs-toggle="modal"]';
const Default$6 = {
  backdrop: true,
  focus: true,
  keyboard: true
};
const DefaultType$6 = {
  backdrop: "(boolean|string)",
  focus: "boolean",
  keyboard: "boolean"
};
class Modal extends BaseComponent {
  constructor(element, config) {
    super(element, config);
    this._dialog = SelectorEngine.findOne(SELECTOR_DIALOG, this._element);
    this._backdrop = this._initializeBackDrop();
    this._focustrap = this._initializeFocusTrap();
    this._isShown = false;
    this._isTransitioning = false;
    this._scrollBar = new ScrollBarHelper();
    this._addEventListeners();
  }
  // Getters
  static get Default() {
    return Default$6;
  }
  static get DefaultType() {
    return DefaultType$6;
  }
  static get NAME() {
    return NAME$7;
  }
  // Public
  toggle(relatedTarget) {
    return this._isShown ? this.hide() : this.show(relatedTarget);
  }
  show(relatedTarget) {
    if (this._isShown || this._isTransitioning) {
      return;
    }
    const showEvent = EventHandler.trigger(this._element, EVENT_SHOW$4, {
      relatedTarget
    });
    if (showEvent.defaultPrevented) {
      return;
    }
    this._isShown = true;
    this._isTransitioning = true;
    this._scrollBar.hide();
    document.body.classList.add(CLASS_NAME_OPEN);
    this._adjustDialog();
    this._backdrop.show(() => this._showElement(relatedTarget));
  }
  hide() {
    if (!this._isShown || this._isTransitioning) {
      return;
    }
    const hideEvent = EventHandler.trigger(this._element, EVENT_HIDE$4);
    if (hideEvent.defaultPrevented) {
      return;
    }
    this._isShown = false;
    this._isTransitioning = true;
    this._focustrap.deactivate();
    this._element.classList.remove(CLASS_NAME_SHOW$4);
    this._queueCallback(() => this._hideModal(), this._element, this._isAnimated());
  }
  dispose() {
    EventHandler.off(window, EVENT_KEY$4);
    EventHandler.off(this._dialog, EVENT_KEY$4);
    this._backdrop.dispose();
    this._focustrap.deactivate();
    super.dispose();
  }
  handleUpdate() {
    this._adjustDialog();
  }
  // Private
  _initializeBackDrop() {
    return new Backdrop({
      isVisible: Boolean(this._config.backdrop),
      // 'static' option will be translated to true, and booleans will keep their value,
      isAnimated: this._isAnimated()
    });
  }
  _initializeFocusTrap() {
    return new FocusTrap({
      trapElement: this._element
    });
  }
  _showElement(relatedTarget) {
    if (!document.body.contains(this._element)) {
      document.body.append(this._element);
    }
    this._element.style.display = "block";
    this._element.removeAttribute("aria-hidden");
    this._element.setAttribute("aria-modal", true);
    this._element.setAttribute("role", "dialog");
    this._element.scrollTop = 0;
    const modalBody = SelectorEngine.findOne(SELECTOR_MODAL_BODY, this._dialog);
    if (modalBody) {
      modalBody.scrollTop = 0;
    }
    reflow(this._element);
    this._element.classList.add(CLASS_NAME_SHOW$4);
    const transitionComplete = () => {
      if (this._config.focus) {
        this._focustrap.activate();
      }
      this._isTransitioning = false;
      EventHandler.trigger(this._element, EVENT_SHOWN$4, {
        relatedTarget
      });
    };
    this._queueCallback(transitionComplete, this._dialog, this._isAnimated());
  }
  _addEventListeners() {
    EventHandler.on(this._element, EVENT_KEYDOWN_DISMISS$1, (event) => {
      if (event.key !== ESCAPE_KEY$1) {
        return;
      }
      if (this._config.keyboard) {
        this.hide();
        return;
      }
      this._triggerBackdropTransition();
    });
    EventHandler.on(window, EVENT_RESIZE$1, () => {
      if (this._isShown && !this._isTransitioning) {
        this._adjustDialog();
      }
    });
    EventHandler.on(this._element, EVENT_MOUSEDOWN_DISMISS, (event) => {
      EventHandler.one(this._element, EVENT_CLICK_DISMISS, (event2) => {
        if (this._element !== event.target || this._element !== event2.target) {
          return;
        }
        if (this._config.backdrop === "static") {
          this._triggerBackdropTransition();
          return;
        }
        if (this._config.backdrop) {
          this.hide();
        }
      });
    });
  }
  _hideModal() {
    this._element.style.display = "none";
    this._element.setAttribute("aria-hidden", true);
    this._element.removeAttribute("aria-modal");
    this._element.removeAttribute("role");
    this._isTransitioning = false;
    this._backdrop.hide(() => {
      document.body.classList.remove(CLASS_NAME_OPEN);
      this._resetAdjustments();
      this._scrollBar.reset();
      EventHandler.trigger(this._element, EVENT_HIDDEN$4);
    });
  }
  _isAnimated() {
    return this._element.classList.contains(CLASS_NAME_FADE$3);
  }
  _triggerBackdropTransition() {
    const hideEvent = EventHandler.trigger(this._element, EVENT_HIDE_PREVENTED$1);
    if (hideEvent.defaultPrevented) {
      return;
    }
    const isModalOverflowing = this._element.scrollHeight > document.documentElement.clientHeight;
    const initialOverflowY = this._element.style.overflowY;
    if (initialOverflowY === "hidden" || this._element.classList.contains(CLASS_NAME_STATIC)) {
      return;
    }
    if (!isModalOverflowing) {
      this._element.style.overflowY = "hidden";
    }
    this._element.classList.add(CLASS_NAME_STATIC);
    this._queueCallback(() => {
      this._element.classList.remove(CLASS_NAME_STATIC);
      this._queueCallback(() => {
        this._element.style.overflowY = initialOverflowY;
      }, this._dialog);
    }, this._dialog);
    this._element.focus();
  }
  /**
   * The following methods are used to handle overflowing modals
   */
  _adjustDialog() {
    const isModalOverflowing = this._element.scrollHeight > document.documentElement.clientHeight;
    const scrollbarWidth = this._scrollBar.getWidth();
    const isBodyOverflowing = scrollbarWidth > 0;
    if (isBodyOverflowing && !isModalOverflowing) {
      const property = isRTL() ? "paddingLeft" : "paddingRight";
      this._element.style[property] = `${scrollbarWidth}px`;
    }
    if (!isBodyOverflowing && isModalOverflowing) {
      const property = isRTL() ? "paddingRight" : "paddingLeft";
      this._element.style[property] = `${scrollbarWidth}px`;
    }
  }
  _resetAdjustments() {
    this._element.style.paddingLeft = "";
    this._element.style.paddingRight = "";
  }
  // Static
  static jQueryInterface(config, relatedTarget) {
    return this.each(function() {
      const data = Modal.getOrCreateInstance(this, config);
      if (typeof config !== "string") {
        return;
      }
      if (typeof data[config] === "undefined") {
        throw new TypeError(`No method named "${config}"`);
      }
      data[config](relatedTarget);
    });
  }
}
EventHandler.on(document, EVENT_CLICK_DATA_API$2, SELECTOR_DATA_TOGGLE$2, function(event) {
  const target = SelectorEngine.getElementFromSelector(this);
  if (["A", "AREA"].includes(this.tagName)) {
    event.preventDefault();
  }
  EventHandler.one(target, EVENT_SHOW$4, (showEvent) => {
    if (showEvent.defaultPrevented) {
      return;
    }
    EventHandler.one(target, EVENT_HIDDEN$4, () => {
      if (isVisible(this)) {
        this.focus();
      }
    });
  });
  const alreadyOpen = SelectorEngine.findOne(OPEN_SELECTOR$1);
  if (alreadyOpen) {
    Modal.getInstance(alreadyOpen).hide();
  }
  const data = Modal.getOrCreateInstance(target);
  data.toggle(this);
});
enableDismissTrigger(Modal);
defineJQueryPlugin(Modal);
const NAME$6 = "offcanvas";
const DATA_KEY$3 = "bs.offcanvas";
const EVENT_KEY$3 = `.${DATA_KEY$3}`;
const DATA_API_KEY$1 = ".data-api";
const EVENT_LOAD_DATA_API$2 = `load${EVENT_KEY$3}${DATA_API_KEY$1}`;
const ESCAPE_KEY = "Escape";
const CLASS_NAME_SHOW$3 = "show";
const CLASS_NAME_SHOWING$1 = "showing";
const CLASS_NAME_HIDING = "hiding";
const CLASS_NAME_BACKDROP = "offcanvas-backdrop";
const OPEN_SELECTOR = ".offcanvas.show";
const EVENT_SHOW$3 = `show${EVENT_KEY$3}`;
const EVENT_SHOWN$3 = `shown${EVENT_KEY$3}`;
const EVENT_HIDE$3 = `hide${EVENT_KEY$3}`;
const EVENT_HIDE_PREVENTED = `hidePrevented${EVENT_KEY$3}`;
const EVENT_HIDDEN$3 = `hidden${EVENT_KEY$3}`;
const EVENT_RESIZE = `resize${EVENT_KEY$3}`;
const EVENT_CLICK_DATA_API$1 = `click${EVENT_KEY$3}${DATA_API_KEY$1}`;
const EVENT_KEYDOWN_DISMISS = `keydown.dismiss${EVENT_KEY$3}`;
const SELECTOR_DATA_TOGGLE$1 = '[data-bs-toggle="offcanvas"]';
const Default$5 = {
  backdrop: true,
  keyboard: true,
  scroll: false
};
const DefaultType$5 = {
  backdrop: "(boolean|string)",
  keyboard: "boolean",
  scroll: "boolean"
};
class Offcanvas extends BaseComponent {
  constructor(element, config) {
    super(element, config);
    this._isShown = false;
    this._backdrop = this._initializeBackDrop();
    this._focustrap = this._initializeFocusTrap();
    this._addEventListeners();
  }
  // Getters
  static get Default() {
    return Default$5;
  }
  static get DefaultType() {
    return DefaultType$5;
  }
  static get NAME() {
    return NAME$6;
  }
  // Public
  toggle(relatedTarget) {
    return this._isShown ? this.hide() : this.show(relatedTarget);
  }
  show(relatedTarget) {
    if (this._isShown) {
      return;
    }
    const showEvent = EventHandler.trigger(this._element, EVENT_SHOW$3, {
      relatedTarget
    });
    if (showEvent.defaultPrevented) {
      return;
    }
    this._isShown = true;
    this._backdrop.show();
    if (!this._config.scroll) {
      new ScrollBarHelper().hide();
    }
    this._element.setAttribute("aria-modal", true);
    this._element.setAttribute("role", "dialog");
    this._element.classList.add(CLASS_NAME_SHOWING$1);
    const completeCallBack = () => {
      if (!this._config.scroll || this._config.backdrop) {
        this._focustrap.activate();
      }
      this._element.classList.add(CLASS_NAME_SHOW$3);
      this._element.classList.remove(CLASS_NAME_SHOWING$1);
      EventHandler.trigger(this._element, EVENT_SHOWN$3, {
        relatedTarget
      });
    };
    this._queueCallback(completeCallBack, this._element, true);
  }
  hide() {
    if (!this._isShown) {
      return;
    }
    const hideEvent = EventHandler.trigger(this._element, EVENT_HIDE$3);
    if (hideEvent.defaultPrevented) {
      return;
    }
    this._focustrap.deactivate();
    this._element.blur();
    this._isShown = false;
    this._element.classList.add(CLASS_NAME_HIDING);
    this._backdrop.hide();
    const completeCallback = () => {
      this._element.classList.remove(CLASS_NAME_SHOW$3, CLASS_NAME_HIDING);
      this._element.removeAttribute("aria-modal");
      this._element.removeAttribute("role");
      if (!this._config.scroll) {
        new ScrollBarHelper().reset();
      }
      EventHandler.trigger(this._element, EVENT_HIDDEN$3);
    };
    this._queueCallback(completeCallback, this._element, true);
  }
  dispose() {
    this._backdrop.dispose();
    this._focustrap.deactivate();
    super.dispose();
  }
  // Private
  _initializeBackDrop() {
    const clickCallback = () => {
      if (this._config.backdrop === "static") {
        EventHandler.trigger(this._element, EVENT_HIDE_PREVENTED);
        return;
      }
      this.hide();
    };
    const isVisible2 = Boolean(this._config.backdrop);
    return new Backdrop({
      className: CLASS_NAME_BACKDROP,
      isVisible: isVisible2,
      isAnimated: true,
      rootElement: this._element.parentNode,
      clickCallback: isVisible2 ? clickCallback : null
    });
  }
  _initializeFocusTrap() {
    return new FocusTrap({
      trapElement: this._element
    });
  }
  _addEventListeners() {
    EventHandler.on(this._element, EVENT_KEYDOWN_DISMISS, (event) => {
      if (event.key !== ESCAPE_KEY) {
        return;
      }
      if (this._config.keyboard) {
        this.hide();
        return;
      }
      EventHandler.trigger(this._element, EVENT_HIDE_PREVENTED);
    });
  }
  // Static
  static jQueryInterface(config) {
    return this.each(function() {
      const data = Offcanvas.getOrCreateInstance(this, config);
      if (typeof config !== "string") {
        return;
      }
      if (data[config] === void 0 || config.startsWith("_") || config === "constructor") {
        throw new TypeError(`No method named "${config}"`);
      }
      data[config](this);
    });
  }
}
EventHandler.on(document, EVENT_CLICK_DATA_API$1, SELECTOR_DATA_TOGGLE$1, function(event) {
  const target = SelectorEngine.getElementFromSelector(this);
  if (["A", "AREA"].includes(this.tagName)) {
    event.preventDefault();
  }
  if (isDisabled(this)) {
    return;
  }
  EventHandler.one(target, EVENT_HIDDEN$3, () => {
    if (isVisible(this)) {
      this.focus();
    }
  });
  const alreadyOpen = SelectorEngine.findOne(OPEN_SELECTOR);
  if (alreadyOpen && alreadyOpen !== target) {
    Offcanvas.getInstance(alreadyOpen).hide();
  }
  const data = Offcanvas.getOrCreateInstance(target);
  data.toggle(this);
});
EventHandler.on(window, EVENT_LOAD_DATA_API$2, () => {
  for (const selector of SelectorEngine.find(OPEN_SELECTOR)) {
    Offcanvas.getOrCreateInstance(selector).show();
  }
});
EventHandler.on(window, EVENT_RESIZE, () => {
  for (const element of SelectorEngine.find("[aria-modal][class*=show][class*=offcanvas-]")) {
    if (getComputedStyle(element).position !== "fixed") {
      Offcanvas.getOrCreateInstance(element).hide();
    }
  }
});
enableDismissTrigger(Offcanvas);
defineJQueryPlugin(Offcanvas);
const ARIA_ATTRIBUTE_PATTERN = /^aria-[\w-]*$/i;
const DefaultAllowlist = {
  // Global attributes allowed on any supplied element below.
  "*": ["class", "dir", "id", "lang", "role", ARIA_ATTRIBUTE_PATTERN],
  a: ["target", "href", "title", "rel"],
  area: [],
  b: [],
  br: [],
  col: [],
  code: [],
  dd: [],
  div: [],
  dl: [],
  dt: [],
  em: [],
  hr: [],
  h1: [],
  h2: [],
  h3: [],
  h4: [],
  h5: [],
  h6: [],
  i: [],
  img: ["src", "srcset", "alt", "title", "width", "height"],
  li: [],
  ol: [],
  p: [],
  pre: [],
  s: [],
  small: [],
  span: [],
  sub: [],
  sup: [],
  strong: [],
  u: [],
  ul: []
};
const uriAttributes = /* @__PURE__ */ new Set(["background", "cite", "href", "itemtype", "longdesc", "poster", "src", "xlink:href"]);
const SAFE_URL_PATTERN = /^(?!javascript:)(?:[a-z0-9+.-]+:|[^&:/?#]*(?:[/?#]|$))/i;
const allowedAttribute = (attribute, allowedAttributeList) => {
  const attributeName = attribute.nodeName.toLowerCase();
  if (allowedAttributeList.includes(attributeName)) {
    if (uriAttributes.has(attributeName)) {
      return Boolean(SAFE_URL_PATTERN.test(attribute.nodeValue));
    }
    return true;
  }
  return allowedAttributeList.filter((attributeRegex) => attributeRegex instanceof RegExp).some((regex) => regex.test(attributeName));
};
function sanitizeHtml(unsafeHtml, allowList, sanitizeFunction) {
  if (!unsafeHtml.length) {
    return unsafeHtml;
  }
  if (sanitizeFunction && typeof sanitizeFunction === "function") {
    return sanitizeFunction(unsafeHtml);
  }
  const domParser = new window.DOMParser();
  const createdDocument = domParser.parseFromString(unsafeHtml, "text/html");
  const elements = [].concat(...createdDocument.body.querySelectorAll("*"));
  for (const element of elements) {
    const elementName = element.nodeName.toLowerCase();
    if (!Object.keys(allowList).includes(elementName)) {
      element.remove();
      continue;
    }
    const attributeList = [].concat(...element.attributes);
    const allowedAttributes = [].concat(allowList["*"] || [], allowList[elementName] || []);
    for (const attribute of attributeList) {
      if (!allowedAttribute(attribute, allowedAttributes)) {
        element.removeAttribute(attribute.nodeName);
      }
    }
  }
  return createdDocument.body.innerHTML;
}
const NAME$5 = "TemplateFactory";
const Default$4 = {
  allowList: DefaultAllowlist,
  content: {},
  // { selector : text ,  selector2 : text2 , }
  extraClass: "",
  html: false,
  sanitize: true,
  sanitizeFn: null,
  template: "<div></div>"
};
const DefaultType$4 = {
  allowList: "object",
  content: "object",
  extraClass: "(string|function)",
  html: "boolean",
  sanitize: "boolean",
  sanitizeFn: "(null|function)",
  template: "string"
};
const DefaultContentType = {
  entry: "(string|element|function|null)",
  selector: "(string|element)"
};
class TemplateFactory extends Config {
  constructor(config) {
    super();
    this._config = this._getConfig(config);
  }
  // Getters
  static get Default() {
    return Default$4;
  }
  static get DefaultType() {
    return DefaultType$4;
  }
  static get NAME() {
    return NAME$5;
  }
  // Public
  getContent() {
    return Object.values(this._config.content).map((config) => this._resolvePossibleFunction(config)).filter(Boolean);
  }
  hasContent() {
    return this.getContent().length > 0;
  }
  changeContent(content) {
    this._checkContent(content);
    this._config.content = {
      ...this._config.content,
      ...content
    };
    return this;
  }
  toHtml() {
    const templateWrapper = document.createElement("div");
    templateWrapper.innerHTML = this._maybeSanitize(this._config.template);
    for (const [selector, text] of Object.entries(this._config.content)) {
      this._setContent(templateWrapper, text, selector);
    }
    const template = templateWrapper.children[0];
    const extraClass = this._resolvePossibleFunction(this._config.extraClass);
    if (extraClass) {
      template.classList.add(...extraClass.split(" "));
    }
    return template;
  }
  // Private
  _typeCheckConfig(config) {
    super._typeCheckConfig(config);
    this._checkContent(config.content);
  }
  _checkContent(arg) {
    for (const [selector, content] of Object.entries(arg)) {
      super._typeCheckConfig({
        selector,
        entry: content
      }, DefaultContentType);
    }
  }
  _setContent(template, content, selector) {
    const templateElement = SelectorEngine.findOne(selector, template);
    if (!templateElement) {
      return;
    }
    content = this._resolvePossibleFunction(content);
    if (!content) {
      templateElement.remove();
      return;
    }
    if (isElement(content)) {
      this._putElementInTemplate(getElement(content), templateElement);
      return;
    }
    if (this._config.html) {
      templateElement.innerHTML = this._maybeSanitize(content);
      return;
    }
    templateElement.textContent = content;
  }
  _maybeSanitize(arg) {
    return this._config.sanitize ? sanitizeHtml(arg, this._config.allowList, this._config.sanitizeFn) : arg;
  }
  _resolvePossibleFunction(arg) {
    return execute(arg, [this]);
  }
  _putElementInTemplate(element, templateElement) {
    if (this._config.html) {
      templateElement.innerHTML = "";
      templateElement.append(element);
      return;
    }
    templateElement.textContent = element.textContent;
  }
}
const NAME$4 = "tooltip";
const DISALLOWED_ATTRIBUTES = /* @__PURE__ */ new Set(["sanitize", "allowList", "sanitizeFn"]);
const CLASS_NAME_FADE$2 = "fade";
const CLASS_NAME_MODAL = "modal";
const CLASS_NAME_SHOW$2 = "show";
const SELECTOR_TOOLTIP_INNER = ".tooltip-inner";
const SELECTOR_MODAL = `.${CLASS_NAME_MODAL}`;
const EVENT_MODAL_HIDE = "hide.bs.modal";
const TRIGGER_HOVER = "hover";
const TRIGGER_FOCUS = "focus";
const TRIGGER_CLICK = "click";
const TRIGGER_MANUAL = "manual";
const EVENT_HIDE$2 = "hide";
const EVENT_HIDDEN$2 = "hidden";
const EVENT_SHOW$2 = "show";
const EVENT_SHOWN$2 = "shown";
const EVENT_INSERTED = "inserted";
const EVENT_CLICK$1 = "click";
const EVENT_FOCUSIN$1 = "focusin";
const EVENT_FOCUSOUT$1 = "focusout";
const EVENT_MOUSEENTER = "mouseenter";
const EVENT_MOUSELEAVE = "mouseleave";
const AttachmentMap = {
  AUTO: "auto",
  TOP: "top",
  RIGHT: isRTL() ? "left" : "right",
  BOTTOM: "bottom",
  LEFT: isRTL() ? "right" : "left"
};
const Default$3 = {
  allowList: DefaultAllowlist,
  animation: true,
  boundary: "clippingParents",
  container: false,
  customClass: "",
  delay: 0,
  fallbackPlacements: ["top", "right", "bottom", "left"],
  html: false,
  offset: [0, 6],
  placement: "top",
  popperConfig: null,
  sanitize: true,
  sanitizeFn: null,
  selector: false,
  template: '<div class="tooltip" role="tooltip"><div class="tooltip-arrow"></div><div class="tooltip-inner"></div></div>',
  title: "",
  trigger: "hover focus"
};
const DefaultType$3 = {
  allowList: "object",
  animation: "boolean",
  boundary: "(string|element)",
  container: "(string|element|boolean)",
  customClass: "(string|function)",
  delay: "(number|object)",
  fallbackPlacements: "array",
  html: "boolean",
  offset: "(array|string|function)",
  placement: "(string|function)",
  popperConfig: "(null|object|function)",
  sanitize: "boolean",
  sanitizeFn: "(null|function)",
  selector: "(string|boolean)",
  template: "string",
  title: "(string|element|function)",
  trigger: "string"
};
class Tooltip extends BaseComponent {
  constructor(element, config) {
    if (typeof Popper === "undefined") {
      throw new TypeError("Bootstrap's tooltips require Popper (https://popper.js.org)");
    }
    super(element, config);
    this._isEnabled = true;
    this._timeout = 0;
    this._isHovered = null;
    this._activeTrigger = {};
    this._popper = null;
    this._templateFactory = null;
    this._newContent = null;
    this.tip = null;
    this._setListeners();
    if (!this._config.selector) {
      this._fixTitle();
    }
  }
  // Getters
  static get Default() {
    return Default$3;
  }
  static get DefaultType() {
    return DefaultType$3;
  }
  static get NAME() {
    return NAME$4;
  }
  // Public
  enable() {
    this._isEnabled = true;
  }
  disable() {
    this._isEnabled = false;
  }
  toggleEnabled() {
    this._isEnabled = !this._isEnabled;
  }
  toggle() {
    if (!this._isEnabled) {
      return;
    }
    this._activeTrigger.click = !this._activeTrigger.click;
    if (this._isShown()) {
      this._leave();
      return;
    }
    this._enter();
  }
  dispose() {
    clearTimeout(this._timeout);
    EventHandler.off(this._element.closest(SELECTOR_MODAL), EVENT_MODAL_HIDE, this._hideModalHandler);
    if (this._element.getAttribute("data-bs-original-title")) {
      this._element.setAttribute("title", this._element.getAttribute("data-bs-original-title"));
    }
    this._disposePopper();
    super.dispose();
  }
  show() {
    if (this._element.style.display === "none") {
      throw new Error("Please use show on visible elements");
    }
    if (!(this._isWithContent() && this._isEnabled)) {
      return;
    }
    const showEvent = EventHandler.trigger(this._element, this.constructor.eventName(EVENT_SHOW$2));
    const shadowRoot = findShadowRoot(this._element);
    const isInTheDom = (shadowRoot || this._element.ownerDocument.documentElement).contains(this._element);
    if (showEvent.defaultPrevented || !isInTheDom) {
      return;
    }
    this._disposePopper();
    const tip = this._getTipElement();
    this._element.setAttribute("aria-describedby", tip.getAttribute("id"));
    const {
      container
    } = this._config;
    if (!this._element.ownerDocument.documentElement.contains(this.tip)) {
      container.append(tip);
      EventHandler.trigger(this._element, this.constructor.eventName(EVENT_INSERTED));
    }
    this._popper = this._createPopper(tip);
    tip.classList.add(CLASS_NAME_SHOW$2);
    if ("ontouchstart" in document.documentElement) {
      for (const element of [].concat(...document.body.children)) {
        EventHandler.on(element, "mouseover", noop);
      }
    }
    const complete = () => {
      EventHandler.trigger(this._element, this.constructor.eventName(EVENT_SHOWN$2));
      if (this._isHovered === false) {
        this._leave();
      }
      this._isHovered = false;
    };
    this._queueCallback(complete, this.tip, this._isAnimated());
  }
  hide() {
    if (!this._isShown()) {
      return;
    }
    const hideEvent = EventHandler.trigger(this._element, this.constructor.eventName(EVENT_HIDE$2));
    if (hideEvent.defaultPrevented) {
      return;
    }
    const tip = this._getTipElement();
    tip.classList.remove(CLASS_NAME_SHOW$2);
    if ("ontouchstart" in document.documentElement) {
      for (const element of [].concat(...document.body.children)) {
        EventHandler.off(element, "mouseover", noop);
      }
    }
    this._activeTrigger[TRIGGER_CLICK] = false;
    this._activeTrigger[TRIGGER_FOCUS] = false;
    this._activeTrigger[TRIGGER_HOVER] = false;
    this._isHovered = null;
    const complete = () => {
      if (this._isWithActiveTrigger()) {
        return;
      }
      if (!this._isHovered) {
        this._disposePopper();
      }
      this._element.removeAttribute("aria-describedby");
      EventHandler.trigger(this._element, this.constructor.eventName(EVENT_HIDDEN$2));
    };
    this._queueCallback(complete, this.tip, this._isAnimated());
  }
  update() {
    if (this._popper) {
      this._popper.update();
    }
  }
  // Protected
  _isWithContent() {
    return Boolean(this._getTitle());
  }
  _getTipElement() {
    if (!this.tip) {
      this.tip = this._createTipElement(this._newContent || this._getContentForTemplate());
    }
    return this.tip;
  }
  _createTipElement(content) {
    const tip = this._getTemplateFactory(content).toHtml();
    if (!tip) {
      return null;
    }
    tip.classList.remove(CLASS_NAME_FADE$2, CLASS_NAME_SHOW$2);
    tip.classList.add(`bs-${this.constructor.NAME}-auto`);
    const tipId = getUID(this.constructor.NAME).toString();
    tip.setAttribute("id", tipId);
    if (this._isAnimated()) {
      tip.classList.add(CLASS_NAME_FADE$2);
    }
    return tip;
  }
  setContent(content) {
    this._newContent = content;
    if (this._isShown()) {
      this._disposePopper();
      this.show();
    }
  }
  _getTemplateFactory(content) {
    if (this._templateFactory) {
      this._templateFactory.changeContent(content);
    } else {
      this._templateFactory = new TemplateFactory({
        ...this._config,
        // the `content` var has to be after `this._config`
        // to override config.content in case of popover
        content,
        extraClass: this._resolvePossibleFunction(this._config.customClass)
      });
    }
    return this._templateFactory;
  }
  _getContentForTemplate() {
    return {
      [SELECTOR_TOOLTIP_INNER]: this._getTitle()
    };
  }
  _getTitle() {
    return this._resolvePossibleFunction(this._config.title) || this._element.getAttribute("data-bs-original-title");
  }
  // Private
  _initializeOnDelegatedTarget(event) {
    return this.constructor.getOrCreateInstance(event.delegateTarget, this._getDelegateConfig());
  }
  _isAnimated() {
    return this._config.animation || this.tip && this.tip.classList.contains(CLASS_NAME_FADE$2);
  }
  _isShown() {
    return this.tip && this.tip.classList.contains(CLASS_NAME_SHOW$2);
  }
  _createPopper(tip) {
    const placement = execute(this._config.placement, [this, tip, this._element]);
    const attachment = AttachmentMap[placement.toUpperCase()];
    return createPopper(this._element, tip, this._getPopperConfig(attachment));
  }
  _getOffset() {
    const {
      offset: offset2
    } = this._config;
    if (typeof offset2 === "string") {
      return offset2.split(",").map((value) => Number.parseInt(value, 10));
    }
    if (typeof offset2 === "function") {
      return (popperData) => offset2(popperData, this._element);
    }
    return offset2;
  }
  _resolvePossibleFunction(arg) {
    return execute(arg, [this._element]);
  }
  _getPopperConfig(attachment) {
    const defaultBsPopperConfig = {
      placement: attachment,
      modifiers: [{
        name: "flip",
        options: {
          fallbackPlacements: this._config.fallbackPlacements
        }
      }, {
        name: "offset",
        options: {
          offset: this._getOffset()
        }
      }, {
        name: "preventOverflow",
        options: {
          boundary: this._config.boundary
        }
      }, {
        name: "arrow",
        options: {
          element: `.${this.constructor.NAME}-arrow`
        }
      }, {
        name: "preSetPlacement",
        enabled: true,
        phase: "beforeMain",
        fn: (data) => {
          this._getTipElement().setAttribute("data-popper-placement", data.state.placement);
        }
      }]
    };
    return {
      ...defaultBsPopperConfig,
      ...execute(this._config.popperConfig, [defaultBsPopperConfig])
    };
  }
  _setListeners() {
    const triggers = this._config.trigger.split(" ");
    for (const trigger of triggers) {
      if (trigger === "click") {
        EventHandler.on(this._element, this.constructor.eventName(EVENT_CLICK$1), this._config.selector, (event) => {
          const context = this._initializeOnDelegatedTarget(event);
          context.toggle();
        });
      } else if (trigger !== TRIGGER_MANUAL) {
        const eventIn = trigger === TRIGGER_HOVER ? this.constructor.eventName(EVENT_MOUSEENTER) : this.constructor.eventName(EVENT_FOCUSIN$1);
        const eventOut = trigger === TRIGGER_HOVER ? this.constructor.eventName(EVENT_MOUSELEAVE) : this.constructor.eventName(EVENT_FOCUSOUT$1);
        EventHandler.on(this._element, eventIn, this._config.selector, (event) => {
          const context = this._initializeOnDelegatedTarget(event);
          context._activeTrigger[event.type === "focusin" ? TRIGGER_FOCUS : TRIGGER_HOVER] = true;
          context._enter();
        });
        EventHandler.on(this._element, eventOut, this._config.selector, (event) => {
          const context = this._initializeOnDelegatedTarget(event);
          context._activeTrigger[event.type === "focusout" ? TRIGGER_FOCUS : TRIGGER_HOVER] = context._element.contains(event.relatedTarget);
          context._leave();
        });
      }
    }
    this._hideModalHandler = () => {
      if (this._element) {
        this.hide();
      }
    };
    EventHandler.on(this._element.closest(SELECTOR_MODAL), EVENT_MODAL_HIDE, this._hideModalHandler);
  }
  _fixTitle() {
    const title = this._element.getAttribute("title");
    if (!title) {
      return;
    }
    if (!this._element.getAttribute("aria-label") && !this._element.textContent.trim()) {
      this._element.setAttribute("aria-label", title);
    }
    this._element.setAttribute("data-bs-original-title", title);
    this._element.removeAttribute("title");
  }
  _enter() {
    if (this._isShown() || this._isHovered) {
      this._isHovered = true;
      return;
    }
    this._isHovered = true;
    this._setTimeout(() => {
      if (this._isHovered) {
        this.show();
      }
    }, this._config.delay.show);
  }
  _leave() {
    if (this._isWithActiveTrigger()) {
      return;
    }
    this._isHovered = false;
    this._setTimeout(() => {
      if (!this._isHovered) {
        this.hide();
      }
    }, this._config.delay.hide);
  }
  _setTimeout(handler, timeout) {
    clearTimeout(this._timeout);
    this._timeout = setTimeout(handler, timeout);
  }
  _isWithActiveTrigger() {
    return Object.values(this._activeTrigger).includes(true);
  }
  _getConfig(config) {
    const dataAttributes = Manipulator.getDataAttributes(this._element);
    for (const dataAttribute of Object.keys(dataAttributes)) {
      if (DISALLOWED_ATTRIBUTES.has(dataAttribute)) {
        delete dataAttributes[dataAttribute];
      }
    }
    config = {
      ...dataAttributes,
      ...typeof config === "object" && config ? config : {}
    };
    config = this._mergeConfigObj(config);
    config = this._configAfterMerge(config);
    this._typeCheckConfig(config);
    return config;
  }
  _configAfterMerge(config) {
    config.container = config.container === false ? document.body : getElement(config.container);
    if (typeof config.delay === "number") {
      config.delay = {
        show: config.delay,
        hide: config.delay
      };
    }
    if (typeof config.title === "number") {
      config.title = config.title.toString();
    }
    if (typeof config.content === "number") {
      config.content = config.content.toString();
    }
    return config;
  }
  _getDelegateConfig() {
    const config = {};
    for (const [key2, value] of Object.entries(this._config)) {
      if (this.constructor.Default[key2] !== value) {
        config[key2] = value;
      }
    }
    config.selector = false;
    config.trigger = "manual";
    return config;
  }
  _disposePopper() {
    if (this._popper) {
      this._popper.destroy();
      this._popper = null;
    }
    if (this.tip) {
      this.tip.remove();
      this.tip = null;
    }
  }
  // Static
  static jQueryInterface(config) {
    return this.each(function() {
      const data = Tooltip.getOrCreateInstance(this, config);
      if (typeof config !== "string") {
        return;
      }
      if (typeof data[config] === "undefined") {
        throw new TypeError(`No method named "${config}"`);
      }
      data[config]();
    });
  }
}
defineJQueryPlugin(Tooltip);
const NAME$3 = "popover";
const SELECTOR_TITLE = ".popover-header";
const SELECTOR_CONTENT = ".popover-body";
const Default$2 = {
  ...Tooltip.Default,
  content: "",
  offset: [0, 8],
  placement: "right",
  template: '<div class="popover" role="tooltip"><div class="popover-arrow"></div><h3 class="popover-header"></h3><div class="popover-body"></div></div>',
  trigger: "click"
};
const DefaultType$2 = {
  ...Tooltip.DefaultType,
  content: "(null|string|element|function)"
};
class Popover extends Tooltip {
  // Getters
  static get Default() {
    return Default$2;
  }
  static get DefaultType() {
    return DefaultType$2;
  }
  static get NAME() {
    return NAME$3;
  }
  // Overrides
  _isWithContent() {
    return this._getTitle() || this._getContent();
  }
  // Private
  _getContentForTemplate() {
    return {
      [SELECTOR_TITLE]: this._getTitle(),
      [SELECTOR_CONTENT]: this._getContent()
    };
  }
  _getContent() {
    return this._resolvePossibleFunction(this._config.content);
  }
  // Static
  static jQueryInterface(config) {
    return this.each(function() {
      const data = Popover.getOrCreateInstance(this, config);
      if (typeof config !== "string") {
        return;
      }
      if (typeof data[config] === "undefined") {
        throw new TypeError(`No method named "${config}"`);
      }
      data[config]();
    });
  }
}
defineJQueryPlugin(Popover);
const NAME$2 = "scrollspy";
const DATA_KEY$2 = "bs.scrollspy";
const EVENT_KEY$2 = `.${DATA_KEY$2}`;
const DATA_API_KEY = ".data-api";
const EVENT_ACTIVATE = `activate${EVENT_KEY$2}`;
const EVENT_CLICK = `click${EVENT_KEY$2}`;
const EVENT_LOAD_DATA_API$1 = `load${EVENT_KEY$2}${DATA_API_KEY}`;
const CLASS_NAME_DROPDOWN_ITEM = "dropdown-item";
const CLASS_NAME_ACTIVE$1 = "active";
const SELECTOR_DATA_SPY = '[data-bs-spy="scroll"]';
const SELECTOR_TARGET_LINKS = "[href]";
const SELECTOR_NAV_LIST_GROUP = ".nav, .list-group";
const SELECTOR_NAV_LINKS = ".nav-link";
const SELECTOR_NAV_ITEMS = ".nav-item";
const SELECTOR_LIST_ITEMS = ".list-group-item";
const SELECTOR_LINK_ITEMS = `${SELECTOR_NAV_LINKS}, ${SELECTOR_NAV_ITEMS} > ${SELECTOR_NAV_LINKS}, ${SELECTOR_LIST_ITEMS}`;
const SELECTOR_DROPDOWN = ".dropdown";
const SELECTOR_DROPDOWN_TOGGLE$1 = ".dropdown-toggle";
const Default$1 = {
  offset: null,
  // TODO: v6 @deprecated, keep it for backwards compatibility reasons
  rootMargin: "0px 0px -25%",
  smoothScroll: false,
  target: null,
  threshold: [0.1, 0.5, 1]
};
const DefaultType$1 = {
  offset: "(number|null)",
  // TODO v6 @deprecated, keep it for backwards compatibility reasons
  rootMargin: "string",
  smoothScroll: "boolean",
  target: "element",
  threshold: "array"
};
class ScrollSpy extends BaseComponent {
  constructor(element, config) {
    super(element, config);
    this._targetLinks = /* @__PURE__ */ new Map();
    this._observableSections = /* @__PURE__ */ new Map();
    this._rootElement = getComputedStyle(this._element).overflowY === "visible" ? null : this._element;
    this._activeTarget = null;
    this._observer = null;
    this._previousScrollData = {
      visibleEntryTop: 0,
      parentScrollTop: 0
    };
    this.refresh();
  }
  // Getters
  static get Default() {
    return Default$1;
  }
  static get DefaultType() {
    return DefaultType$1;
  }
  static get NAME() {
    return NAME$2;
  }
  // Public
  refresh() {
    this._initializeTargetsAndObservables();
    this._maybeEnableSmoothScroll();
    if (this._observer) {
      this._observer.disconnect();
    } else {
      this._observer = this._getNewObserver();
    }
    for (const section of this._observableSections.values()) {
      this._observer.observe(section);
    }
  }
  dispose() {
    this._observer.disconnect();
    super.dispose();
  }
  // Private
  _configAfterMerge(config) {
    config.target = getElement(config.target) || document.body;
    config.rootMargin = config.offset ? `${config.offset}px 0px -30%` : config.rootMargin;
    if (typeof config.threshold === "string") {
      config.threshold = config.threshold.split(",").map((value) => Number.parseFloat(value));
    }
    return config;
  }
  _maybeEnableSmoothScroll() {
    if (!this._config.smoothScroll) {
      return;
    }
    EventHandler.off(this._config.target, EVENT_CLICK);
    EventHandler.on(this._config.target, EVENT_CLICK, SELECTOR_TARGET_LINKS, (event) => {
      const observableSection = this._observableSections.get(event.target.hash);
      if (observableSection) {
        event.preventDefault();
        const root2 = this._rootElement || window;
        const height = observableSection.offsetTop - this._element.offsetTop;
        if (root2.scrollTo) {
          root2.scrollTo({
            top: height,
            behavior: "smooth"
          });
          return;
        }
        root2.scrollTop = height;
      }
    });
  }
  _getNewObserver() {
    const options = {
      root: this._rootElement,
      threshold: this._config.threshold,
      rootMargin: this._config.rootMargin
    };
    return new IntersectionObserver((entries) => this._observerCallback(entries), options);
  }
  // The logic of selection
  _observerCallback(entries) {
    const targetElement = (entry) => this._targetLinks.get(`#${entry.target.id}`);
    const activate = (entry) => {
      this._previousScrollData.visibleEntryTop = entry.target.offsetTop;
      this._process(targetElement(entry));
    };
    const parentScrollTop = (this._rootElement || document.documentElement).scrollTop;
    const userScrollsDown = parentScrollTop >= this._previousScrollData.parentScrollTop;
    this._previousScrollData.parentScrollTop = parentScrollTop;
    for (const entry of entries) {
      if (!entry.isIntersecting) {
        this._activeTarget = null;
        this._clearActiveClass(targetElement(entry));
        continue;
      }
      const entryIsLowerThanPrevious = entry.target.offsetTop >= this._previousScrollData.visibleEntryTop;
      if (userScrollsDown && entryIsLowerThanPrevious) {
        activate(entry);
        if (!parentScrollTop) {
          return;
        }
        continue;
      }
      if (!userScrollsDown && !entryIsLowerThanPrevious) {
        activate(entry);
      }
    }
  }
  _initializeTargetsAndObservables() {
    this._targetLinks = /* @__PURE__ */ new Map();
    this._observableSections = /* @__PURE__ */ new Map();
    const targetLinks = SelectorEngine.find(SELECTOR_TARGET_LINKS, this._config.target);
    for (const anchor of targetLinks) {
      if (!anchor.hash || isDisabled(anchor)) {
        continue;
      }
      const observableSection = SelectorEngine.findOne(decodeURI(anchor.hash), this._element);
      if (isVisible(observableSection)) {
        this._targetLinks.set(decodeURI(anchor.hash), anchor);
        this._observableSections.set(anchor.hash, observableSection);
      }
    }
  }
  _process(target) {
    if (this._activeTarget === target) {
      return;
    }
    this._clearActiveClass(this._config.target);
    this._activeTarget = target;
    target.classList.add(CLASS_NAME_ACTIVE$1);
    this._activateParents(target);
    EventHandler.trigger(this._element, EVENT_ACTIVATE, {
      relatedTarget: target
    });
  }
  _activateParents(target) {
    if (target.classList.contains(CLASS_NAME_DROPDOWN_ITEM)) {
      SelectorEngine.findOne(SELECTOR_DROPDOWN_TOGGLE$1, target.closest(SELECTOR_DROPDOWN)).classList.add(CLASS_NAME_ACTIVE$1);
      return;
    }
    for (const listGroup of SelectorEngine.parents(target, SELECTOR_NAV_LIST_GROUP)) {
      for (const item of SelectorEngine.prev(listGroup, SELECTOR_LINK_ITEMS)) {
        item.classList.add(CLASS_NAME_ACTIVE$1);
      }
    }
  }
  _clearActiveClass(parent) {
    parent.classList.remove(CLASS_NAME_ACTIVE$1);
    const activeNodes = SelectorEngine.find(`${SELECTOR_TARGET_LINKS}.${CLASS_NAME_ACTIVE$1}`, parent);
    for (const node of activeNodes) {
      node.classList.remove(CLASS_NAME_ACTIVE$1);
    }
  }
  // Static
  static jQueryInterface(config) {
    return this.each(function() {
      const data = ScrollSpy.getOrCreateInstance(this, config);
      if (typeof config !== "string") {
        return;
      }
      if (data[config] === void 0 || config.startsWith("_") || config === "constructor") {
        throw new TypeError(`No method named "${config}"`);
      }
      data[config]();
    });
  }
}
EventHandler.on(window, EVENT_LOAD_DATA_API$1, () => {
  for (const spy of SelectorEngine.find(SELECTOR_DATA_SPY)) {
    ScrollSpy.getOrCreateInstance(spy);
  }
});
defineJQueryPlugin(ScrollSpy);
const NAME$1 = "tab";
const DATA_KEY$1 = "bs.tab";
const EVENT_KEY$1 = `.${DATA_KEY$1}`;
const EVENT_HIDE$1 = `hide${EVENT_KEY$1}`;
const EVENT_HIDDEN$1 = `hidden${EVENT_KEY$1}`;
const EVENT_SHOW$1 = `show${EVENT_KEY$1}`;
const EVENT_SHOWN$1 = `shown${EVENT_KEY$1}`;
const EVENT_CLICK_DATA_API = `click${EVENT_KEY$1}`;
const EVENT_KEYDOWN = `keydown${EVENT_KEY$1}`;
const EVENT_LOAD_DATA_API = `load${EVENT_KEY$1}`;
const ARROW_LEFT_KEY = "ArrowLeft";
const ARROW_RIGHT_KEY = "ArrowRight";
const ARROW_UP_KEY = "ArrowUp";
const ARROW_DOWN_KEY = "ArrowDown";
const HOME_KEY = "Home";
const END_KEY = "End";
const CLASS_NAME_ACTIVE = "active";
const CLASS_NAME_FADE$1 = "fade";
const CLASS_NAME_SHOW$1 = "show";
const CLASS_DROPDOWN = "dropdown";
const SELECTOR_DROPDOWN_TOGGLE = ".dropdown-toggle";
const SELECTOR_DROPDOWN_MENU = ".dropdown-menu";
const NOT_SELECTOR_DROPDOWN_TOGGLE = `:not(${SELECTOR_DROPDOWN_TOGGLE})`;
const SELECTOR_TAB_PANEL = '.list-group, .nav, [role="tablist"]';
const SELECTOR_OUTER = ".nav-item, .list-group-item";
const SELECTOR_INNER = `.nav-link${NOT_SELECTOR_DROPDOWN_TOGGLE}, .list-group-item${NOT_SELECTOR_DROPDOWN_TOGGLE}, [role="tab"]${NOT_SELECTOR_DROPDOWN_TOGGLE}`;
const SELECTOR_DATA_TOGGLE = '[data-bs-toggle="tab"], [data-bs-toggle="pill"], [data-bs-toggle="list"]';
const SELECTOR_INNER_ELEM = `${SELECTOR_INNER}, ${SELECTOR_DATA_TOGGLE}`;
const SELECTOR_DATA_TOGGLE_ACTIVE = `.${CLASS_NAME_ACTIVE}[data-bs-toggle="tab"], .${CLASS_NAME_ACTIVE}[data-bs-toggle="pill"], .${CLASS_NAME_ACTIVE}[data-bs-toggle="list"]`;
let Tab$1 = class Tab extends BaseComponent {
  constructor(element) {
    super(element);
    this._parent = this._element.closest(SELECTOR_TAB_PANEL);
    if (!this._parent) {
      return;
    }
    this._setInitialAttributes(this._parent, this._getChildren());
    EventHandler.on(this._element, EVENT_KEYDOWN, (event) => this._keydown(event));
  }
  // Getters
  static get NAME() {
    return NAME$1;
  }
  // Public
  show() {
    const innerElem = this._element;
    if (this._elemIsActive(innerElem)) {
      return;
    }
    const active = this._getActiveElem();
    const hideEvent = active ? EventHandler.trigger(active, EVENT_HIDE$1, {
      relatedTarget: innerElem
    }) : null;
    const showEvent = EventHandler.trigger(innerElem, EVENT_SHOW$1, {
      relatedTarget: active
    });
    if (showEvent.defaultPrevented || hideEvent && hideEvent.defaultPrevented) {
      return;
    }
    this._deactivate(active, innerElem);
    this._activate(innerElem, active);
  }
  // Private
  _activate(element, relatedElem) {
    if (!element) {
      return;
    }
    element.classList.add(CLASS_NAME_ACTIVE);
    this._activate(SelectorEngine.getElementFromSelector(element));
    const complete = () => {
      if (element.getAttribute("role") !== "tab") {
        element.classList.add(CLASS_NAME_SHOW$1);
        return;
      }
      element.removeAttribute("tabindex");
      element.setAttribute("aria-selected", true);
      this._toggleDropDown(element, true);
      EventHandler.trigger(element, EVENT_SHOWN$1, {
        relatedTarget: relatedElem
      });
    };
    this._queueCallback(complete, element, element.classList.contains(CLASS_NAME_FADE$1));
  }
  _deactivate(element, relatedElem) {
    if (!element) {
      return;
    }
    element.classList.remove(CLASS_NAME_ACTIVE);
    element.blur();
    this._deactivate(SelectorEngine.getElementFromSelector(element));
    const complete = () => {
      if (element.getAttribute("role") !== "tab") {
        element.classList.remove(CLASS_NAME_SHOW$1);
        return;
      }
      element.setAttribute("aria-selected", false);
      element.setAttribute("tabindex", "-1");
      this._toggleDropDown(element, false);
      EventHandler.trigger(element, EVENT_HIDDEN$1, {
        relatedTarget: relatedElem
      });
    };
    this._queueCallback(complete, element, element.classList.contains(CLASS_NAME_FADE$1));
  }
  _keydown(event) {
    if (![ARROW_LEFT_KEY, ARROW_RIGHT_KEY, ARROW_UP_KEY, ARROW_DOWN_KEY, HOME_KEY, END_KEY].includes(event.key)) {
      return;
    }
    event.stopPropagation();
    event.preventDefault();
    const children = this._getChildren().filter((element) => !isDisabled(element));
    let nextActiveElement;
    if ([HOME_KEY, END_KEY].includes(event.key)) {
      nextActiveElement = children[event.key === HOME_KEY ? 0 : children.length - 1];
    } else {
      const isNext = [ARROW_RIGHT_KEY, ARROW_DOWN_KEY].includes(event.key);
      nextActiveElement = getNextActiveElement(children, event.target, isNext, true);
    }
    if (nextActiveElement) {
      nextActiveElement.focus({
        preventScroll: true
      });
      Tab.getOrCreateInstance(nextActiveElement).show();
    }
  }
  _getChildren() {
    return SelectorEngine.find(SELECTOR_INNER_ELEM, this._parent);
  }
  _getActiveElem() {
    return this._getChildren().find((child) => this._elemIsActive(child)) || null;
  }
  _setInitialAttributes(parent, children) {
    this._setAttributeIfNotExists(parent, "role", "tablist");
    for (const child of children) {
      this._setInitialAttributesOnChild(child);
    }
  }
  _setInitialAttributesOnChild(child) {
    child = this._getInnerElement(child);
    const isActive = this._elemIsActive(child);
    const outerElem = this._getOuterElement(child);
    child.setAttribute("aria-selected", isActive);
    if (outerElem !== child) {
      this._setAttributeIfNotExists(outerElem, "role", "presentation");
    }
    if (!isActive) {
      child.setAttribute("tabindex", "-1");
    }
    this._setAttributeIfNotExists(child, "role", "tab");
    this._setInitialAttributesOnTargetPanel(child);
  }
  _setInitialAttributesOnTargetPanel(child) {
    const target = SelectorEngine.getElementFromSelector(child);
    if (!target) {
      return;
    }
    this._setAttributeIfNotExists(target, "role", "tabpanel");
    if (child.id) {
      this._setAttributeIfNotExists(target, "aria-labelledby", `${child.id}`);
    }
  }
  _toggleDropDown(element, open) {
    const outerElem = this._getOuterElement(element);
    if (!outerElem.classList.contains(CLASS_DROPDOWN)) {
      return;
    }
    const toggle = (selector, className) => {
      const element2 = SelectorEngine.findOne(selector, outerElem);
      if (element2) {
        element2.classList.toggle(className, open);
      }
    };
    toggle(SELECTOR_DROPDOWN_TOGGLE, CLASS_NAME_ACTIVE);
    toggle(SELECTOR_DROPDOWN_MENU, CLASS_NAME_SHOW$1);
    outerElem.setAttribute("aria-expanded", open);
  }
  _setAttributeIfNotExists(element, attribute, value) {
    if (!element.hasAttribute(attribute)) {
      element.setAttribute(attribute, value);
    }
  }
  _elemIsActive(elem) {
    return elem.classList.contains(CLASS_NAME_ACTIVE);
  }
  // Try to get the inner element (usually the .nav-link)
  _getInnerElement(elem) {
    return elem.matches(SELECTOR_INNER_ELEM) ? elem : SelectorEngine.findOne(SELECTOR_INNER_ELEM, elem);
  }
  // Try to get the outer element (usually the .nav-item)
  _getOuterElement(elem) {
    return elem.closest(SELECTOR_OUTER) || elem;
  }
  // Static
  static jQueryInterface(config) {
    return this.each(function() {
      const data = Tab.getOrCreateInstance(this);
      if (typeof config !== "string") {
        return;
      }
      if (data[config] === void 0 || config.startsWith("_") || config === "constructor") {
        throw new TypeError(`No method named "${config}"`);
      }
      data[config]();
    });
  }
};
EventHandler.on(document, EVENT_CLICK_DATA_API, SELECTOR_DATA_TOGGLE, function(event) {
  if (["A", "AREA"].includes(this.tagName)) {
    event.preventDefault();
  }
  if (isDisabled(this)) {
    return;
  }
  Tab$1.getOrCreateInstance(this).show();
});
EventHandler.on(window, EVENT_LOAD_DATA_API, () => {
  for (const element of SelectorEngine.find(SELECTOR_DATA_TOGGLE_ACTIVE)) {
    Tab$1.getOrCreateInstance(element);
  }
});
defineJQueryPlugin(Tab$1);
const NAME = "toast";
const DATA_KEY = "bs.toast";
const EVENT_KEY = `.${DATA_KEY}`;
const EVENT_MOUSEOVER = `mouseover${EVENT_KEY}`;
const EVENT_MOUSEOUT = `mouseout${EVENT_KEY}`;
const EVENT_FOCUSIN = `focusin${EVENT_KEY}`;
const EVENT_FOCUSOUT = `focusout${EVENT_KEY}`;
const EVENT_HIDE = `hide${EVENT_KEY}`;
const EVENT_HIDDEN = `hidden${EVENT_KEY}`;
const EVENT_SHOW = `show${EVENT_KEY}`;
const EVENT_SHOWN = `shown${EVENT_KEY}`;
const CLASS_NAME_FADE = "fade";
const CLASS_NAME_HIDE = "hide";
const CLASS_NAME_SHOW = "show";
const CLASS_NAME_SHOWING = "showing";
const DefaultType = {
  animation: "boolean",
  autohide: "boolean",
  delay: "number"
};
const Default = {
  animation: true,
  autohide: true,
  delay: 5e3
};
class Toast extends BaseComponent {
  constructor(element, config) {
    super(element, config);
    this._timeout = null;
    this._hasMouseInteraction = false;
    this._hasKeyboardInteraction = false;
    this._setListeners();
  }
  // Getters
  static get Default() {
    return Default;
  }
  static get DefaultType() {
    return DefaultType;
  }
  static get NAME() {
    return NAME;
  }
  // Public
  show() {
    const showEvent = EventHandler.trigger(this._element, EVENT_SHOW);
    if (showEvent.defaultPrevented) {
      return;
    }
    this._clearTimeout();
    if (this._config.animation) {
      this._element.classList.add(CLASS_NAME_FADE);
    }
    const complete = () => {
      this._element.classList.remove(CLASS_NAME_SHOWING);
      EventHandler.trigger(this._element, EVENT_SHOWN);
      this._maybeScheduleHide();
    };
    this._element.classList.remove(CLASS_NAME_HIDE);
    reflow(this._element);
    this._element.classList.add(CLASS_NAME_SHOW, CLASS_NAME_SHOWING);
    this._queueCallback(complete, this._element, this._config.animation);
  }
  hide() {
    if (!this.isShown()) {
      return;
    }
    const hideEvent = EventHandler.trigger(this._element, EVENT_HIDE);
    if (hideEvent.defaultPrevented) {
      return;
    }
    const complete = () => {
      this._element.classList.add(CLASS_NAME_HIDE);
      this._element.classList.remove(CLASS_NAME_SHOWING, CLASS_NAME_SHOW);
      EventHandler.trigger(this._element, EVENT_HIDDEN);
    };
    this._element.classList.add(CLASS_NAME_SHOWING);
    this._queueCallback(complete, this._element, this._config.animation);
  }
  dispose() {
    this._clearTimeout();
    if (this.isShown()) {
      this._element.classList.remove(CLASS_NAME_SHOW);
    }
    super.dispose();
  }
  isShown() {
    return this._element.classList.contains(CLASS_NAME_SHOW);
  }
  // Private
  _maybeScheduleHide() {
    if (!this._config.autohide) {
      return;
    }
    if (this._hasMouseInteraction || this._hasKeyboardInteraction) {
      return;
    }
    this._timeout = setTimeout(() => {
      this.hide();
    }, this._config.delay);
  }
  _onInteraction(event, isInteracting) {
    switch (event.type) {
      case "mouseover":
      case "mouseout": {
        this._hasMouseInteraction = isInteracting;
        break;
      }
      case "focusin":
      case "focusout": {
        this._hasKeyboardInteraction = isInteracting;
        break;
      }
    }
    if (isInteracting) {
      this._clearTimeout();
      return;
    }
    const nextElement = event.relatedTarget;
    if (this._element === nextElement || this._element.contains(nextElement)) {
      return;
    }
    this._maybeScheduleHide();
  }
  _setListeners() {
    EventHandler.on(this._element, EVENT_MOUSEOVER, (event) => this._onInteraction(event, true));
    EventHandler.on(this._element, EVENT_MOUSEOUT, (event) => this._onInteraction(event, false));
    EventHandler.on(this._element, EVENT_FOCUSIN, (event) => this._onInteraction(event, true));
    EventHandler.on(this._element, EVENT_FOCUSOUT, (event) => this._onInteraction(event, false));
  }
  _clearTimeout() {
    clearTimeout(this._timeout);
    this._timeout = null;
  }
  // Static
  static jQueryInterface(config) {
    return this.each(function() {
      const data = Toast.getOrCreateInstance(this, config);
      if (typeof config === "string") {
        if (typeof data[config] === "undefined") {
          throw new TypeError(`No method named "${config}"`);
        }
        data[config](this);
      }
    });
  }
}
enableDismissTrigger(Toast);
defineJQueryPlugin(Toast);
var t$1, r$1, u, i, o = 0, f = [], c$1 = l$1, e$1 = c$1.__b, a = c$1.__r, v = c$1.diffed, l = c$1.__c, m = c$1.unmount, s = c$1.__;
function d(n2, t2) {
  c$1.__h && c$1.__h(r$1, n2, o || t2), o = 0;
  var u2 = r$1.__H || (r$1.__H = { __: [], __h: [] });
  return n2 >= u2.__.length && u2.__.push({}), u2.__[n2];
}
function h(n2) {
  return o = 1, p(D, n2);
}
function p(n2, u2, i2) {
  var o2 = d(t$1++, 2);
  if (o2.t = n2, !o2.__c && (o2.__ = [D(void 0, u2), function(n3) {
    var t2 = o2.__N ? o2.__N[0] : o2.__[0], r2 = o2.t(t2, n3);
    t2 !== r2 && (o2.__N = [r2, o2.__[1]], o2.__c.setState({}));
  }], o2.__c = r$1, !r$1.u)) {
    var f2 = function(n3, t2, r2) {
      if (!o2.__c.__H) return true;
      var u3 = o2.__c.__H.__.filter(function(n4) {
        return !!n4.__c;
      });
      if (u3.every(function(n4) {
        return !n4.__N;
      })) return !c2 || c2.call(this, n3, t2, r2);
      var i3 = false;
      return u3.forEach(function(n4) {
        if (n4.__N) {
          var t3 = n4.__[0];
          n4.__ = n4.__N, n4.__N = void 0, t3 !== n4.__[0] && (i3 = true);
        }
      }), !(!i3 && o2.__c.props === n3) && (!c2 || c2.call(this, n3, t2, r2));
    };
    r$1.u = true;
    var c2 = r$1.shouldComponentUpdate, e2 = r$1.componentWillUpdate;
    r$1.componentWillUpdate = function(n3, t2, r2) {
      if (this.__e) {
        var u3 = c2;
        c2 = void 0, f2(n3, t2, r2), c2 = u3;
      }
      e2 && e2.call(this, n3, t2, r2);
    }, r$1.shouldComponentUpdate = f2;
  }
  return o2.__N || o2.__;
}
function y(n2, u2) {
  var i2 = d(t$1++, 3);
  !c$1.__s && C(i2.__H, u2) && (i2.__ = n2, i2.i = u2, r$1.__H.__h.push(i2));
}
function A(n2) {
  return o = 5, T(function() {
    return { current: n2 };
  }, []);
}
function T(n2, r2) {
  var u2 = d(t$1++, 7);
  return C(u2.__H, r2) && (u2.__ = n2(), u2.__H = r2, u2.__h = n2), u2.__;
}
function q(n2, t2) {
  return o = 8, T(function() {
    return n2;
  }, t2);
}
function j() {
  for (var n2; n2 = f.shift(); ) if (n2.__P && n2.__H) try {
    n2.__H.__h.forEach(z), n2.__H.__h.forEach(B), n2.__H.__h = [];
  } catch (t2) {
    n2.__H.__h = [], c$1.__e(t2, n2.__v);
  }
}
c$1.__b = function(n2) {
  r$1 = null, e$1 && e$1(n2);
}, c$1.__ = function(n2, t2) {
  n2 && t2.__k && t2.__k.__m && (n2.__m = t2.__k.__m), s && s(n2, t2);
}, c$1.__r = function(n2) {
  a && a(n2), t$1 = 0;
  var i2 = (r$1 = n2.__c).__H;
  i2 && (u === r$1 ? (i2.__h = [], r$1.__h = [], i2.__.forEach(function(n3) {
    n3.__N && (n3.__ = n3.__N), n3.i = n3.__N = void 0;
  })) : (i2.__h.forEach(z), i2.__h.forEach(B), i2.__h = [], t$1 = 0)), u = r$1;
}, c$1.diffed = function(n2) {
  v && v(n2);
  var t2 = n2.__c;
  t2 && t2.__H && (t2.__H.__h.length && (1 !== f.push(t2) && i === c$1.requestAnimationFrame || ((i = c$1.requestAnimationFrame) || w)(j)), t2.__H.__.forEach(function(n3) {
    n3.i && (n3.__H = n3.i), n3.i = void 0;
  })), u = r$1 = null;
}, c$1.__c = function(n2, t2) {
  t2.some(function(n3) {
    try {
      n3.__h.forEach(z), n3.__h = n3.__h.filter(function(n4) {
        return !n4.__ || B(n4);
      });
    } catch (r2) {
      t2.some(function(n4) {
        n4.__h && (n4.__h = []);
      }), t2 = [], c$1.__e(r2, n3.__v);
    }
  }), l && l(n2, t2);
}, c$1.unmount = function(n2) {
  m && m(n2);
  var t2, r2 = n2.__c;
  r2 && r2.__H && (r2.__H.__.forEach(function(n3) {
    try {
      z(n3);
    } catch (n4) {
      t2 = n4;
    }
  }), r2.__H = void 0, t2 && c$1.__e(t2, r2.__v));
};
var k = "function" == typeof requestAnimationFrame;
function w(n2) {
  var t2, r2 = function() {
    clearTimeout(u2), k && cancelAnimationFrame(t2), setTimeout(n2);
  }, u2 = setTimeout(r2, 100);
  k && (t2 = requestAnimationFrame(r2));
}
function z(n2) {
  var t2 = r$1, u2 = n2.__c;
  "function" == typeof u2 && (n2.__c = void 0, u2()), r$1 = t2;
}
function B(n2) {
  var t2 = r$1;
  n2.__c = n2.__(), r$1 = t2;
}
function C(n2, t2) {
  return !n2 || n2.length !== t2.length || t2.some(function(t3, r2) {
    return t3 !== n2[r2];
  });
}
function D(n2, t2) {
  return "function" == typeof t2 ? t2(n2) : t2;
}
const arrayToString = (val) => {
  val = Array.isArray(val) ? val : [val];
  return val.join(", ");
};
const shorteners = [/^.*(\[.+\])$/m];
const shortenCompletion = (completion) => {
  if (!completion) {
    return completion;
  }
  let shortened = void 0;
  for (const shortenPattern of shorteners) {
    const shortMatch = completion.match(shortenPattern);
    if (shortMatch && shortMatch[1]) {
      shortened = shortMatch[1];
      break;
    }
  }
  return shortened || completion;
};
const inputString = (input) => {
  if (typeof input === "string") {
    return input;
  } else {
    return input.map((inp) => {
      if (typeof inp === "string") {
        return inp;
      } else {
        const content = inp.content;
        if (typeof content === "string") {
          return content;
        } else {
          const result = content.map((con) => {
            if (con.type === "text") {
              return con.text;
            } else {
              return "";
            }
          });
          return result.join("\n");
        }
      }
    });
  }
};
const formatDataset = (name, samples, epochs) => {
  const perEpochSamples = epochs > 0 ? samples / epochs : samples;
  return `${name ? "— " : ""}${perEpochSamples + " "}${epochs > 1 ? `x ${epochs} ` : ""}${samples === 1 ? "sample" : "samples"}`;
};
const formatTime = (seconds) => {
  if (seconds < 60) {
    return `${seconds} sec`;
  } else if (seconds < 60 * 60) {
    return `${Math.floor(seconds / 60)} min ${seconds % 60} sec`;
  } else {
    return `${Math.floor(seconds / (60 * 60 * 24))} days ${Math.floor(
      seconds / 60
    )} min ${seconds % 60} sec`;
  }
};
function formatPrettyDecimal(num) {
  const numDecimalPlaces = num.toString().includes(".") ? num.toString().split(".")[1].length : 0;
  if (numDecimalPlaces === 0) {
    return num.toFixed(1);
  } else if (numDecimalPlaces > 3) {
    return num.toFixed(3);
  } else {
    return num.toString();
  }
}
function formatDecimalNoTrailingZeroes(num) {
  if (typeof num !== "number") {
    return num;
  }
  if (num.toString().includes(".")) {
    const decimal = num.toString().split(".")[1];
    const trimmed = decimal.replace(/\.?0+$/, "");
    return num.toFixed(trimmed.length);
  } else {
    return num.toFixed(0);
  }
}
function toTitleCase(str) {
  return str.split(" ").map((w2) => w2[0].toUpperCase() + w2.substr(1).toLowerCase()).join(" ");
}
function formatNumber(num) {
  return num.toLocaleString(navigator.language, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 5
  });
}
const filename = (path) => {
  const pathparts = path.split("/");
  const basename = pathparts.slice(-1)[0];
  const match = basename.match(/(.*)\.\S+$/);
  if (match) {
    return match[1];
  } else {
    return path;
  }
};
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
function throttle(func, wait, options) {
  var context, args, result;
  var timeout = null;
  var previous = 0;
  if (!options) options = {};
  var later = function() {
    previous = options.leading === false ? 0 : Date.now();
    timeout = null;
    result = func.apply(context, args);
    if (!timeout) context = args = null;
  };
  return function() {
    var now = Date.now();
    if (!previous && options.leading === false) previous = now;
    var remaining = wait - (now - previous);
    context = this;
    args = arguments;
    if (remaining <= 0 || remaining > wait) {
      if (timeout) {
        clearTimeout(timeout);
        timeout = null;
      }
      previous = now;
      result = func.apply(context, args);
      if (!timeout) context = args = null;
    } else if (!timeout && options.trailing !== false) {
      timeout = setTimeout(later, remaining);
    }
    return result;
  };
}
const clearDocumentSelection = () => {
  const sel = window.getSelection();
  if (sel) {
    if (sel.removeAllRanges) {
      sel.removeAllRanges();
    } else if (sel.empty) {
      sel.empty();
    }
  }
};
const ApplicationIcons = {
  arrows: {
    right: "bi bi-arrow-right",
    down: "bi bi-arrow-down",
    up: "bi bi-arrow-up"
  },
  caret: {
    right: "bi bi-caret-right",
    down: "bi bi-caret-down"
  },
  changes: {
    add: "bi bi-plus",
    remove: "bi bi-dash",
    replace: "bi bi-plus-slash-minus"
  },
  chevron: {
    right: "bi bi-chevron-right",
    down: "bi bi-chevron-down"
  },
  collapse: {
    all: "bi bi-arrows-collapse",
    up: "bi bi-chevron-up"
  },
  close: "bi bi-x",
  config: "bi bi-gear",
  confirm: "bi bi-check",
  copy: "bi bi-copy",
  epoch: (epoch) => {
    return `bi bi-${epoch}-circle`;
  },
  error: "bi bi-exclamation-circle",
  "expand-all": "bi bi-arrows-expand",
  "expand-down": "bi bi-chevron-down",
  info: "bi bi-info-circle",
  inspect: "bi bi-gear",
  json: "bi bi-filetype-json",
  logging: {
    notset: "bi bi-card-text",
    debug: "bi bi-bug",
    http: "bi bi-download",
    info: "bi bi-info-square",
    warning: "bi bi-exclamation-triangle",
    error: "bi bi-x-circle",
    critical: "bi bi-fire"
  },
  menu: "bi bi-list",
  messages: "bi bi-chat-right-text",
  metadata: "bi bi-table",
  model: "bi bi-grid-3x3-gap",
  "toggle-right": "bi bi-chevron-right",
  more: "bi bi-zoom-in",
  "multiple-choice": "bi bi-card-list",
  next: "bi bi-chevron-right",
  previous: "bi bi-chevron-left",
  role: {
    user: "bi bi-person",
    system: "bi bi-cpu",
    assistant: "bi bi-robot",
    tool: "bi bi-tools"
  },
  sample: "bi bi-database",
  samples: "bi bi-file-spreadsheet",
  scorer: "bi bi-calculator",
  search: "bi bi-search",
  solvers: {
    default: "bi bi-arrow-return-right",
    generate: "bi bi-share",
    chain_of_thought: "bi bi-link",
    self_critique: "bi bi-arrow-left-right",
    system_message: "bi bi-cpu",
    use_tools: "bi bi-tools"
  },
  step: "bi bi-fast-forward-btn",
  subtask: "bi bi-subtract",
  transcript: "bi bi-list-columns-reverse",
  usage: "bi bi-stopwatch"
};
const kBaseFontSize = 0.9;
const ScaleBaseFont = (scale) => {
  return `${kBaseFontSize + scale}rem`;
};
const FontSize = {
  title: ScaleBaseFont(0.6),
  "title-secondary": ScaleBaseFont(0.4),
  larger: ScaleBaseFont(0.2),
  large: ScaleBaseFont(0.1),
  base: ScaleBaseFont(0),
  small: ScaleBaseFont(-0.1),
  smaller: ScaleBaseFont(-0.1)
};
const TextStyle = {
  label: {
    textTransform: "uppercase"
  },
  secondary: {
    color: "var(--bs-secondary)"
  }
};
const ErrorPanel = ({ id, classes, title, error }) => {
  const emptyStyle = {
    display: "flex",
    flex: "0 0 content",
    alignItems: "center",
    justifyContent: "center"
  };
  const message = error.message;
  const stack2 = error.stack;
  return m$1`
    <div
      ...${{ id }}
      class="${classes ? classes : ""}"
      style=${{
    ...emptyStyle,
    flexDirection: "column",
    minHeight: "10rem",
    marginTop: "4rem"
  }}
    >
      <div style=${{ ...emptyStyle, fontSize: FontSize["title-secondary"] }}>
        <div>
          <i
            class="${ApplicationIcons.error}"
            style="${{ marginRight: "0.5rem", color: "var(--bs-red)" }}"
          ></i>
        </div>
        <div>${title || ""}</div>
      </div>
      <div
        style=${{
    display: "inline-block",
    fontSize: FontSize.smaller,
    marginTop: "3rem",
    border: "solid 1px var(--bs-border-color)",
    borderRadius: "var(--bs-border-radius)",
    padding: "1em",
    maxWidth: "80%"
  }}
      >
        <div>
          Error: ${message || ""}
          ${stack2 && m$1`
            <pre style=${{ fontSize: FontSize.smaller }}>
            <code>
              at ${stack2}
            </code>
          </pre>
          `}
        </div>
      </div>
    </div>
  `;
};
class AppErrorBoundary extends b {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, errorInfo) {
    console.log({ error, errorInfo });
  }
  render() {
    if (this.state.hasError) {
      console.log({ e: this.state.error });
      return m$1`<${ErrorPanel}
        title="An unexpected error occurred."
        error="${this.state.error}"
      />`;
    }
    return this.props.children;
  }
}
const ProgressBar = ({ style, animating }) => {
  const emptyStyle = {
    display: "flex",
    textAlign: "center",
    flex: "0 0 content",
    alignItems: "center",
    justifyContent: "center",
    border: "none",
    padding: "0",
    zIndex: 1001,
    width: "100%",
    height: "0px",
    overflow: "visible"
  };
  const progressContainerStyle = {
    width: "100%",
    height: "2px",
    background: "none"
  };
  const progressBarStyle = {
    width: "5%",
    height: "2px",
    ...style
  };
  return m$1`
    <div style=${emptyStyle} class="empty-message">
      <div
        class="progress"
        role="progressbar"
        aria-label="Basic example"
        aria-valuenow="25"
        aria-valuemin="0"
        aria-valuemax="100"
        style=${progressContainerStyle}
      >
        ${animating ? m$1`<div
              class="progress-bar left-to-right-animate"
              style=${progressBarStyle}
            ></div>` : ""}
      </div>
    </div>
  `;
};
const Sidebar = ({
  offcanvas,
  logs,
  loading,
  logHeaders,
  selectedIndex,
  onSelectedIndexChanged
}) => {
  const btnOffCanClass = offcanvas ? "" : " d-md-none";
  const sidebarOffCanClass = offcanvas ? " offcanvas" : " offcanvas-md";
  return m$1`
    <div
      class="sidebar border-end offcanvas-start${sidebarOffCanClass}"
      id="sidebarOffCanvas"
      style=${{ display: "flex", flexDirection: "column", height: "100%" }}
    >
      <div
        style=${{
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    columnGap: "0.2rem",
    alignItems: "center",
    paddingLeft: "0.5rem",
    opacity: "0.7",
    position: "fixed",
    width: "var(--sidebar-width)",
    zIndex: 10,
    borderBottom: "solid var(--bs-light-border-subtle) 1px",
    paddingBottom: "0.5rem",
    paddingTop: "0.5rem"
  }}
      >
        <${LogDirectoryTitle} log_dir=${logs.log_dir} offcanvas=${offcanvas} />
        <button
          id="sidebarToggle"
          class="btn d-inline${btnOffCanClass}"
          type="button"
          data-bs-toggle="offcanvas"
          data-bs-target="#sidebarOffCanvas"
          aria-controls="sidebarOffCanvas"
          style=${{
    padding: ".1rem",
    alignSelf: "end",
    width: "40px",
    flex: "0 0 content"
  }}
        >
          <i class=${ApplicationIcons.close}></i>
        </button>
      </div>
      <div style=${{ marginTop: "61px", zIndex: 3 }}>
        <${ProgressBar} animating=${loading} style=${{ marginTop: "-2px" }} />
      </div>
      <ul
        class="list-group"
        style=${{ flexGrow: 1, overflowY: "auto", marginTop: "-3px" }}
      >
        ${logs.files.map((file, index) => {
    var _a, _b, _c, _d, _e, _f, _g, _h, _i;
    const active = index === selectedIndex ? " active" : "";
    const logHeader = logHeaders[file.name];
    const hyperparameters = logHeader ? {
      ...(_a = logHeader.plan) == null ? void 0 : _a.config,
      ...(_b = logHeader.eval) == null ? void 0 : _b.task_args
    } : void 0;
    const model = (_c = logHeader == null ? void 0 : logHeader.eval) == null ? void 0 : _c.model;
    const dataset = (_d = logHeader == null ? void 0 : logHeader.eval) == null ? void 0 : _d.dataset;
    const uniqScorers = /* @__PURE__ */ new Set();
    (_f = (_e = logHeader == null ? void 0 : logHeader.results) == null ? void 0 : _e.scores) == null ? void 0 : _f.forEach((scorer2) => {
      uniqScorers.add(scorer2.name);
    });
    const scorer = Array.from(uniqScorers).join(",");
    const scorerLabel = Object.keys(((_g = logHeader == null ? void 0 : logHeader.results) == null ? void 0 : _g.scores) || {}).length === 1 ? "scorer" : "scorers";
    const completed = (_h = logHeader == null ? void 0 : logHeader.stats) == null ? void 0 : _h.completed_at;
    const time = completed ? new Date(completed) : void 0;
    const timeStr = time ? `${time.toDateString()}
          ${time.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    })}` : "";
    return m$1`
            <li
              class="list-group-item list-group-item-action${active}"
              onclick=${() => onSelectedIndexChanged(index)}
            >
              <div
                style=${{
      display: "flex",
      flexDirection: "row",
      justifyContent: "space-between"
    }}
              >
                <div style=${{ overflow: "hidden" }}>
                  <div
                    style=${{
      fontSize: FontSize["title-secondary"],
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis"
    }}
                  >
                    ${((_i = logHeader == null ? void 0 : logHeader.eval) == null ? void 0 : _i.task) || file.task}
                  </div>
                  <small class="mb-1" style=${{ fontSize: FontSize.small }}>
                    ${timeStr}
                  </small>

                  ${model ? m$1` <div>
                        <small
                          class="mb-1"
                          style=${{ fontSize: FontSize.small }}
                          >${model}</small
                        >
                      </div>` : ""}
                </div>
                <${EvalStatus} logHeader=${logHeader} />
              </div>
              <div style=${{ marginTop: "1em" }}>
                <small class="mb-1">
                  ${hyperparameters ? Object.keys(hyperparameters).map((key2) => {
      return `${key2}: ${hyperparameters[key2]}`;
    }).join(", ") : ""}
                </small>
              </div>
              ${(dataset || scorer) && (logHeader == null ? void 0 : logHeader.status) === "success" ? m$1`<div
                    style=${{
      display: "flex",
      justifyContent: "space-between",
      marginTop: "0em",
      fontSize: FontSize.small
    }}
                  >
                    <span>dataset: ${dataset.name || "(samples)"}</span
                    ><span>${scorerLabel}: ${scorer}</span>
                  </div>` : ""}
            </li>
          `;
  })}
      </ul>
    </div>
  `;
};
const prettyDir = (path) => {
  try {
    let url = new URL(path);
    if (url.protocol === "file:") {
      return url.pathname;
    } else {
      return path;
    }
  } catch {
    return path;
  }
};
const EvalStatus = ({ logHeader }) => {
  var _a;
  switch (logHeader.status) {
    case "error":
      return m$1`<${StatusError} message="Error" />`;
    case "cancelled":
      return m$1`<${StatusCancelled} message="Cancelled" />`;
    case "started":
      return m$1`<${StatusRunning} message="Running" />`;
    default:
      if (((_a = logHeader == null ? void 0 : logHeader.results) == null ? void 0 : _a.scores) && logHeader.results.scores.length > 0) {
        if (logHeader.results.scores.length === 1) {
          return m$1`<${SidebarScore}
            scorer=${logHeader.results.scores[0]}
          />`;
        } else {
          return m$1`<${SidebarScores} scores=${logHeader.results.scores} />`;
        }
      } else {
        return "";
      }
  }
};
const SidebarScore = ({ scorer }) => {
  return m$1`<div
    style=${{
    display: "flex",
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "flex-end"
  }}
  >
    ${Object.keys(scorer.metrics).map((metric) => {
    return m$1`
        <div
          style=${{
      display: "flex",
      flexDirection: "column",
      alignItems: "flex-end",
      marginLeft: "1em",
      marginBottom: "0.4em",
      marginTop: "0.5rem"
    }}
        >
          <div
            style=${{
      marginBottom: "-0.3em",
      fontSize: FontSize.small,
      ...TextStyle.label,
      ...TextStyle.secondary
    }}
          >
            ${scorer.metrics[metric].name}
          </div>
          ${scorer.reducer ? m$1`<div
                style=${{
      fontSize: FontSize.small,
      marginBottom: "-0.2rem"
    }}
              >
                ${scorer.reducer}
              </div>` : ""}
          <div style=${{ fontSize: FontSize["title-secondary"] }}>
            ${formatPrettyDecimal(scorer.metrics[metric].value)}
          </div>
        </div>
      `;
  })}
  </div>`;
};
const SidebarScores = ({ scores }) => {
  return m$1`<div
    style=${{
    display: "flex",
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "flex-end",
    rowGap: "1em"
  }}
  >
    ${scores.map((score) => {
    const name = score.name;
    const reducer = score.reducer;
    return m$1`
        <div
          style=${{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      marginLeft: "1em"
    }}
        >
          <div
            style=${{
      fontSize: FontSize.base,
      width: "100%",
      fontWeight: 300,
      borderBottom: "solid var(--bs-border-color) 1px",
      ...TextStyle.label,
      ...TextStyle.secondary
    }}
          >
            ${name}
          </div>
          ${reducer ? m$1` <div
                style=${{
      fontSize: FontSize.smaller,
      width: "100%",
      fontWeight: 300
    }}
              >
                ${reducer}
              </div>` : ""}
          <div
            style=${{
      fontSize: FontSize.smaller,
      display: "grid",
      gridTemplateColumns: "max-content max-content",
      gridGap: "0 0.3rem"
    }}
          >
            ${Object.keys(score.metrics).map((key2) => {
      const metric = score.metrics[key2];
      return m$1` <div
                  style=${{ ...TextStyle.label, ...TextStyle.secondary }}
                >
                  ${metric.name}
                </div>
                <div style=${{ fontWeight: "600" }}>
                  ${formatPrettyDecimal(metric.value)}
                </div>`;
    })}
          </div>
        </div>
      `;
  })}
  </div>`;
};
const StatusCancelled = ({ message }) => {
  return m$1`<div style=${{ ...TextStyle.secondary }}>${message}</div>`;
};
const StatusRunning = ({ message }) => {
  return m$1`<div class="spinner-border spinner-border-sm" role="status">
    <span class="visually-hidden">${message}</span>
  </div>`;
};
const StatusError = ({ message }) => {
  return m$1`<div style=${{ color: "var(--bs-danger)" }}>${message}</div>`;
};
const LogDirectoryTitle = ({ log_dir, offcanvas }) => {
  if (log_dir) {
    const displayDir = prettyDir(log_dir);
    return m$1`<div style=${{ display: "flex", flexDirection: "column" }}>
      <span
        style=${{
      fontSize: FontSize.smaller,
      ...TextStyle.label,
      ...TextStyle.secondary
    }}
        >Log Directory</span
      >
      <span
        title=${displayDir}
        style=${{
      fontSize: FontSize.base,
      overflow: "hidden",
      whiteSpace: "nowrap",
      textOverflow: "ellipsis"
    }}
        >${offcanvas ? displayDir : ""}</span
      >
    </div>`;
  } else {
    return m$1`<span
      style=${{
      fontSize: FontSize.title
    }}
      >${offcanvas ? "Log History" : ""}
    </span>`;
  }
};
var prism = { exports: {} };
(function(module) {
  var _self = typeof window !== "undefined" ? window : typeof WorkerGlobalScope !== "undefined" && self instanceof WorkerGlobalScope ? self : {};
  /**
   * Prism: Lightweight, robust, elegant syntax highlighting
   *
   * @license MIT <https://opensource.org/licenses/MIT>
   * @author Lea Verou <https://lea.verou.me>
   * @namespace
   * @public
   */
  var Prism2 = function(_self2) {
    var lang = /(?:^|\s)lang(?:uage)?-([\w-]+)(?=\s|$)/i;
    var uniqueId = 0;
    var plainTextGrammar = {};
    var _2 = {
      /**
       * By default, Prism will attempt to highlight all code elements (by calling {@link Prism.highlightAll}) on the
       * current page after the page finished loading. This might be a problem if e.g. you wanted to asynchronously load
       * additional languages or plugins yourself.
       *
       * By setting this value to `true`, Prism will not automatically highlight all code elements on the page.
       *
       * You obviously have to change this value before the automatic highlighting started. To do this, you can add an
       * empty Prism object into the global scope before loading the Prism script like this:
       *
       * ```js
       * window.Prism = window.Prism || {};
       * Prism.manual = true;
       * // add a new <script> to load Prism's script
       * ```
       *
       * @default false
       * @type {boolean}
       * @memberof Prism
       * @public
       */
      manual: _self2.Prism && _self2.Prism.manual,
      /**
       * By default, if Prism is in a web worker, it assumes that it is in a worker it created itself, so it uses
       * `addEventListener` to communicate with its parent instance. However, if you're using Prism manually in your
       * own worker, you don't want it to do this.
       *
       * By setting this value to `true`, Prism will not add its own listeners to the worker.
       *
       * You obviously have to change this value before Prism executes. To do this, you can add an
       * empty Prism object into the global scope before loading the Prism script like this:
       *
       * ```js
       * window.Prism = window.Prism || {};
       * Prism.disableWorkerMessageHandler = true;
       * // Load Prism's script
       * ```
       *
       * @default false
       * @type {boolean}
       * @memberof Prism
       * @public
       */
      disableWorkerMessageHandler: _self2.Prism && _self2.Prism.disableWorkerMessageHandler,
      /**
       * A namespace for utility methods.
       *
       * All function in this namespace that are not explicitly marked as _public_ are for __internal use only__ and may
       * change or disappear at any time.
       *
       * @namespace
       * @memberof Prism
       */
      util: {
        encode: function encode(tokens) {
          if (tokens instanceof Token) {
            return new Token(tokens.type, encode(tokens.content), tokens.alias);
          } else if (Array.isArray(tokens)) {
            return tokens.map(encode);
          } else {
            return tokens.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/\u00a0/g, " ");
          }
        },
        /**
         * Returns the name of the type of the given value.
         *
         * @param {any} o
         * @returns {string}
         * @example
         * type(null)      === 'Null'
         * type(undefined) === 'Undefined'
         * type(123)       === 'Number'
         * type('foo')     === 'String'
         * type(true)      === 'Boolean'
         * type([1, 2])    === 'Array'
         * type({})        === 'Object'
         * type(String)    === 'Function'
         * type(/abc+/)    === 'RegExp'
         */
        type: function(o2) {
          return Object.prototype.toString.call(o2).slice(8, -1);
        },
        /**
         * Returns a unique number for the given object. Later calls will still return the same number.
         *
         * @param {Object} obj
         * @returns {number}
         */
        objId: function(obj) {
          if (!obj["__id"]) {
            Object.defineProperty(obj, "__id", { value: ++uniqueId });
          }
          return obj["__id"];
        },
        /**
         * Creates a deep clone of the given object.
         *
         * The main intended use of this function is to clone language definitions.
         *
         * @param {T} o
         * @param {Record<number, any>} [visited]
         * @returns {T}
         * @template T
         */
        clone: function deepClone2(o2, visited) {
          visited = visited || {};
          var clone2;
          var id;
          switch (_2.util.type(o2)) {
            case "Object":
              id = _2.util.objId(o2);
              if (visited[id]) {
                return visited[id];
              }
              clone2 = /** @type {Record<string, any>} */
              {};
              visited[id] = clone2;
              for (var key2 in o2) {
                if (o2.hasOwnProperty(key2)) {
                  clone2[key2] = deepClone2(o2[key2], visited);
                }
              }
              return (
                /** @type {any} */
                clone2
              );
            case "Array":
              id = _2.util.objId(o2);
              if (visited[id]) {
                return visited[id];
              }
              clone2 = [];
              visited[id] = clone2;
              /** @type {Array} */
              /** @type {any} */
              o2.forEach(function(v2, i2) {
                clone2[i2] = deepClone2(v2, visited);
              });
              return (
                /** @type {any} */
                clone2
              );
            default:
              return o2;
          }
        },
        /**
         * Returns the Prism language of the given element set by a `language-xxxx` or `lang-xxxx` class.
         *
         * If no language is set for the element or the element is `null` or `undefined`, `none` will be returned.
         *
         * @param {Element} element
         * @returns {string}
         */
        getLanguage: function(element) {
          while (element) {
            var m2 = lang.exec(element.className);
            if (m2) {
              return m2[1].toLowerCase();
            }
            element = element.parentElement;
          }
          return "none";
        },
        /**
         * Sets the Prism `language-xxxx` class of the given element.
         *
         * @param {Element} element
         * @param {string} language
         * @returns {void}
         */
        setLanguage: function(element, language) {
          element.className = element.className.replace(RegExp(lang, "gi"), "");
          element.classList.add("language-" + language);
        },
        /**
         * Returns the script element that is currently executing.
         *
         * This does __not__ work for line script element.
         *
         * @returns {HTMLScriptElement | null}
         */
        currentScript: function() {
          if (typeof document === "undefined") {
            return null;
          }
          if ("currentScript" in document && 1 < 2) {
            return (
              /** @type {any} */
              document.currentScript
            );
          }
          try {
            throw new Error();
          } catch (err) {
            var src = (/at [^(\r\n]*\((.*):[^:]+:[^:]+\)$/i.exec(err.stack) || [])[1];
            if (src) {
              var scripts = document.getElementsByTagName("script");
              for (var i2 in scripts) {
                if (scripts[i2].src == src) {
                  return scripts[i2];
                }
              }
            }
            return null;
          }
        },
        /**
         * Returns whether a given class is active for `element`.
         *
         * The class can be activated if `element` or one of its ancestors has the given class and it can be deactivated
         * if `element` or one of its ancestors has the negated version of the given class. The _negated version_ of the
         * given class is just the given class with a `no-` prefix.
         *
         * Whether the class is active is determined by the closest ancestor of `element` (where `element` itself is
         * closest ancestor) that has the given class or the negated version of it. If neither `element` nor any of its
         * ancestors have the given class or the negated version of it, then the default activation will be returned.
         *
         * In the paradoxical situation where the closest ancestor contains __both__ the given class and the negated
         * version of it, the class is considered active.
         *
         * @param {Element} element
         * @param {string} className
         * @param {boolean} [defaultActivation=false]
         * @returns {boolean}
         */
        isActive: function(element, className, defaultActivation) {
          var no = "no-" + className;
          while (element) {
            var classList = element.classList;
            if (classList.contains(className)) {
              return true;
            }
            if (classList.contains(no)) {
              return false;
            }
            element = element.parentElement;
          }
          return !!defaultActivation;
        }
      },
      /**
       * This namespace contains all currently loaded languages and the some helper functions to create and modify languages.
       *
       * @namespace
       * @memberof Prism
       * @public
       */
      languages: {
        /**
         * The grammar for plain, unformatted text.
         */
        plain: plainTextGrammar,
        plaintext: plainTextGrammar,
        text: plainTextGrammar,
        txt: plainTextGrammar,
        /**
         * Creates a deep copy of the language with the given id and appends the given tokens.
         *
         * If a token in `redef` also appears in the copied language, then the existing token in the copied language
         * will be overwritten at its original position.
         *
         * ## Best practices
         *
         * Since the position of overwriting tokens (token in `redef` that overwrite tokens in the copied language)
         * doesn't matter, they can technically be in any order. However, this can be confusing to others that trying to
         * understand the language definition because, normally, the order of tokens matters in Prism grammars.
         *
         * Therefore, it is encouraged to order overwriting tokens according to the positions of the overwritten tokens.
         * Furthermore, all non-overwriting tokens should be placed after the overwriting ones.
         *
         * @param {string} id The id of the language to extend. This has to be a key in `Prism.languages`.
         * @param {Grammar} redef The new tokens to append.
         * @returns {Grammar} The new language created.
         * @public
         * @example
         * Prism.languages['css-with-colors'] = Prism.languages.extend('css', {
         *     // Prism.languages.css already has a 'comment' token, so this token will overwrite CSS' 'comment' token
         *     // at its original position
         *     'comment': { ... },
         *     // CSS doesn't have a 'color' token, so this token will be appended
         *     'color': /\b(?:red|green|blue)\b/
         * });
         */
        extend: function(id, redef) {
          var lang2 = _2.util.clone(_2.languages[id]);
          for (var key2 in redef) {
            lang2[key2] = redef[key2];
          }
          return lang2;
        },
        /**
         * Inserts tokens _before_ another token in a language definition or any other grammar.
         *
         * ## Usage
         *
         * This helper method makes it easy to modify existing languages. For example, the CSS language definition
         * not only defines CSS highlighting for CSS documents, but also needs to define highlighting for CSS embedded
         * in HTML through `<style>` elements. To do this, it needs to modify `Prism.languages.markup` and add the
         * appropriate tokens. However, `Prism.languages.markup` is a regular JavaScript object literal, so if you do
         * this:
         *
         * ```js
         * Prism.languages.markup.style = {
         *     // token
         * };
         * ```
         *
         * then the `style` token will be added (and processed) at the end. `insertBefore` allows you to insert tokens
         * before existing tokens. For the CSS example above, you would use it like this:
         *
         * ```js
         * Prism.languages.insertBefore('markup', 'cdata', {
         *     'style': {
         *         // token
         *     }
         * });
         * ```
         *
         * ## Special cases
         *
         * If the grammars of `inside` and `insert` have tokens with the same name, the tokens in `inside`'s grammar
         * will be ignored.
         *
         * This behavior can be used to insert tokens after `before`:
         *
         * ```js
         * Prism.languages.insertBefore('markup', 'comment', {
         *     'comment': Prism.languages.markup.comment,
         *     // tokens after 'comment'
         * });
         * ```
         *
         * ## Limitations
         *
         * The main problem `insertBefore` has to solve is iteration order. Since ES2015, the iteration order for object
         * properties is guaranteed to be the insertion order (except for integer keys) but some browsers behave
         * differently when keys are deleted and re-inserted. So `insertBefore` can't be implemented by temporarily
         * deleting properties which is necessary to insert at arbitrary positions.
         *
         * To solve this problem, `insertBefore` doesn't actually insert the given tokens into the target object.
         * Instead, it will create a new object and replace all references to the target object with the new one. This
         * can be done without temporarily deleting properties, so the iteration order is well-defined.
         *
         * However, only references that can be reached from `Prism.languages` or `insert` will be replaced. I.e. if
         * you hold the target object in a variable, then the value of the variable will not change.
         *
         * ```js
         * var oldMarkup = Prism.languages.markup;
         * var newMarkup = Prism.languages.insertBefore('markup', 'comment', { ... });
         *
         * assert(oldMarkup !== Prism.languages.markup);
         * assert(newMarkup === Prism.languages.markup);
         * ```
         *
         * @param {string} inside The property of `root` (e.g. a language id in `Prism.languages`) that contains the
         * object to be modified.
         * @param {string} before The key to insert before.
         * @param {Grammar} insert An object containing the key-value pairs to be inserted.
         * @param {Object<string, any>} [root] The object containing `inside`, i.e. the object that contains the
         * object to be modified.
         *
         * Defaults to `Prism.languages`.
         * @returns {Grammar} The new grammar object.
         * @public
         */
        insertBefore: function(inside, before, insert, root2) {
          root2 = root2 || /** @type {any} */
          _2.languages;
          var grammar = root2[inside];
          var ret = {};
          for (var token2 in grammar) {
            if (grammar.hasOwnProperty(token2)) {
              if (token2 == before) {
                for (var newToken2 in insert) {
                  if (insert.hasOwnProperty(newToken2)) {
                    ret[newToken2] = insert[newToken2];
                  }
                }
              }
              if (!insert.hasOwnProperty(token2)) {
                ret[token2] = grammar[token2];
              }
            }
          }
          var old = root2[inside];
          root2[inside] = ret;
          _2.languages.DFS(_2.languages, function(key2, value) {
            if (value === old && key2 != inside) {
              this[key2] = ret;
            }
          });
          return ret;
        },
        // Traverse a language definition with Depth First Search
        DFS: function DFS(o2, callback, type, visited) {
          visited = visited || {};
          var objId = _2.util.objId;
          for (var i2 in o2) {
            if (o2.hasOwnProperty(i2)) {
              callback.call(o2, i2, o2[i2], type || i2);
              var property = o2[i2];
              var propertyType = _2.util.type(property);
              if (propertyType === "Object" && !visited[objId(property)]) {
                visited[objId(property)] = true;
                DFS(property, callback, null, visited);
              } else if (propertyType === "Array" && !visited[objId(property)]) {
                visited[objId(property)] = true;
                DFS(property, callback, i2, visited);
              }
            }
          }
        }
      },
      plugins: {},
      /**
       * This is the most high-level function in Prism’s API.
       * It fetches all the elements that have a `.language-xxxx` class and then calls {@link Prism.highlightElement} on
       * each one of them.
       *
       * This is equivalent to `Prism.highlightAllUnder(document, async, callback)`.
       *
       * @param {boolean} [async=false] Same as in {@link Prism.highlightAllUnder}.
       * @param {HighlightCallback} [callback] Same as in {@link Prism.highlightAllUnder}.
       * @memberof Prism
       * @public
       */
      highlightAll: function(async, callback) {
        _2.highlightAllUnder(document, async, callback);
      },
      /**
       * Fetches all the descendants of `container` that have a `.language-xxxx` class and then calls
       * {@link Prism.highlightElement} on each one of them.
       *
       * The following hooks will be run:
       * 1. `before-highlightall`
       * 2. `before-all-elements-highlight`
       * 3. All hooks of {@link Prism.highlightElement} for each element.
       *
       * @param {ParentNode} container The root element, whose descendants that have a `.language-xxxx` class will be highlighted.
       * @param {boolean} [async=false] Whether each element is to be highlighted asynchronously using Web Workers.
       * @param {HighlightCallback} [callback] An optional callback to be invoked on each element after its highlighting is done.
       * @memberof Prism
       * @public
       */
      highlightAllUnder: function(container, async, callback) {
        var env = {
          callback,
          container,
          selector: 'code[class*="language-"], [class*="language-"] code, code[class*="lang-"], [class*="lang-"] code'
        };
        _2.hooks.run("before-highlightall", env);
        env.elements = Array.prototype.slice.apply(env.container.querySelectorAll(env.selector));
        _2.hooks.run("before-all-elements-highlight", env);
        for (var i2 = 0, element; element = env.elements[i2++]; ) {
          _2.highlightElement(element, async === true, env.callback);
        }
      },
      /**
       * Highlights the code inside a single element.
       *
       * The following hooks will be run:
       * 1. `before-sanity-check`
       * 2. `before-highlight`
       * 3. All hooks of {@link Prism.highlight}. These hooks will be run by an asynchronous worker if `async` is `true`.
       * 4. `before-insert`
       * 5. `after-highlight`
       * 6. `complete`
       *
       * Some the above hooks will be skipped if the element doesn't contain any text or there is no grammar loaded for
       * the element's language.
       *
       * @param {Element} element The element containing the code.
       * It must have a class of `language-xxxx` to be processed, where `xxxx` is a valid language identifier.
       * @param {boolean} [async=false] Whether the element is to be highlighted asynchronously using Web Workers
       * to improve performance and avoid blocking the UI when highlighting very large chunks of code. This option is
       * [disabled by default](https://prismjs.com/faq.html#why-is-asynchronous-highlighting-disabled-by-default).
       *
       * Note: All language definitions required to highlight the code must be included in the main `prism.js` file for
       * asynchronous highlighting to work. You can build your own bundle on the
       * [Download page](https://prismjs.com/download.html).
       * @param {HighlightCallback} [callback] An optional callback to be invoked after the highlighting is done.
       * Mostly useful when `async` is `true`, since in that case, the highlighting is done asynchronously.
       * @memberof Prism
       * @public
       */
      highlightElement: function(element, async, callback) {
        var language = _2.util.getLanguage(element);
        var grammar = _2.languages[language];
        _2.util.setLanguage(element, language);
        var parent = element.parentElement;
        if (parent && parent.nodeName.toLowerCase() === "pre") {
          _2.util.setLanguage(parent, language);
        }
        var code = element.textContent;
        var env = {
          element,
          language,
          grammar,
          code
        };
        function insertHighlightedCode(highlightedCode) {
          env.highlightedCode = highlightedCode;
          _2.hooks.run("before-insert", env);
          env.element.innerHTML = env.highlightedCode;
          _2.hooks.run("after-highlight", env);
          _2.hooks.run("complete", env);
          callback && callback.call(env.element);
        }
        _2.hooks.run("before-sanity-check", env);
        parent = env.element.parentElement;
        if (parent && parent.nodeName.toLowerCase() === "pre" && !parent.hasAttribute("tabindex")) {
          parent.setAttribute("tabindex", "0");
        }
        if (!env.code) {
          _2.hooks.run("complete", env);
          callback && callback.call(env.element);
          return;
        }
        _2.hooks.run("before-highlight", env);
        if (!env.grammar) {
          insertHighlightedCode(_2.util.encode(env.code));
          return;
        }
        if (async && _self2.Worker) {
          var worker = new Worker(_2.filename);
          worker.onmessage = function(evt) {
            insertHighlightedCode(evt.data);
          };
          worker.postMessage(JSON.stringify({
            language: env.language,
            code: env.code,
            immediateClose: true
          }));
        } else {
          insertHighlightedCode(_2.highlight(env.code, env.grammar, env.language));
        }
      },
      /**
       * Low-level function, only use if you know what you’re doing. It accepts a string of text as input
       * and the language definitions to use, and returns a string with the HTML produced.
       *
       * The following hooks will be run:
       * 1. `before-tokenize`
       * 2. `after-tokenize`
       * 3. `wrap`: On each {@link Token}.
       *
       * @param {string} text A string with the code to be highlighted.
       * @param {Grammar} grammar An object containing the tokens to use.
       *
       * Usually a language definition like `Prism.languages.markup`.
       * @param {string} language The name of the language definition passed to `grammar`.
       * @returns {string} The highlighted HTML.
       * @memberof Prism
       * @public
       * @example
       * Prism.highlight('var foo = true;', Prism.languages.javascript, 'javascript');
       */
      highlight: function(text, grammar, language) {
        var env = {
          code: text,
          grammar,
          language
        };
        _2.hooks.run("before-tokenize", env);
        if (!env.grammar) {
          throw new Error('The language "' + env.language + '" has no grammar.');
        }
        env.tokens = _2.tokenize(env.code, env.grammar);
        _2.hooks.run("after-tokenize", env);
        return Token.stringify(_2.util.encode(env.tokens), env.language);
      },
      /**
       * This is the heart of Prism, and the most low-level function you can use. It accepts a string of text as input
       * and the language definitions to use, and returns an array with the tokenized code.
       *
       * When the language definition includes nested tokens, the function is called recursively on each of these tokens.
       *
       * This method could be useful in other contexts as well, as a very crude parser.
       *
       * @param {string} text A string with the code to be highlighted.
       * @param {Grammar} grammar An object containing the tokens to use.
       *
       * Usually a language definition like `Prism.languages.markup`.
       * @returns {TokenStream} An array of strings and tokens, a token stream.
       * @memberof Prism
       * @public
       * @example
       * let code = `var foo = 0;`;
       * let tokens = Prism.tokenize(code, Prism.languages.javascript);
       * tokens.forEach(token => {
       *     if (token instanceof Prism.Token && token.type === 'number') {
       *         console.log(`Found numeric literal: ${token.content}`);
       *     }
       * });
       */
      tokenize: function(text, grammar) {
        var rest = grammar.rest;
        if (rest) {
          for (var token2 in rest) {
            grammar[token2] = rest[token2];
          }
          delete grammar.rest;
        }
        var tokenList = new LinkedList();
        addAfter(tokenList, tokenList.head, text);
        matchGrammar(text, tokenList, grammar, tokenList.head, 0);
        return toArray(tokenList);
      },
      /**
       * @namespace
       * @memberof Prism
       * @public
       */
      hooks: {
        all: {},
        /**
         * Adds the given callback to the list of callbacks for the given hook.
         *
         * The callback will be invoked when the hook it is registered for is run.
         * Hooks are usually directly run by a highlight function but you can also run hooks yourself.
         *
         * One callback function can be registered to multiple hooks and the same hook multiple times.
         *
         * @param {string} name The name of the hook.
         * @param {HookCallback} callback The callback function which is given environment variables.
         * @public
         */
        add: function(name, callback) {
          var hooks = _2.hooks.all;
          hooks[name] = hooks[name] || [];
          hooks[name].push(callback);
        },
        /**
         * Runs a hook invoking all registered callbacks with the given environment variables.
         *
         * Callbacks will be invoked synchronously and in the order in which they were registered.
         *
         * @param {string} name The name of the hook.
         * @param {Object<string, any>} env The environment variables of the hook passed to all callbacks registered.
         * @public
         */
        run: function(name, env) {
          var callbacks = _2.hooks.all[name];
          if (!callbacks || !callbacks.length) {
            return;
          }
          for (var i2 = 0, callback; callback = callbacks[i2++]; ) {
            callback(env);
          }
        }
      },
      Token
    };
    _self2.Prism = _2;
    function Token(type, content, alias, matchedStr) {
      this.type = type;
      this.content = content;
      this.alias = alias;
      this.length = (matchedStr || "").length | 0;
    }
    Token.stringify = function stringify3(o2, language) {
      if (typeof o2 == "string") {
        return o2;
      }
      if (Array.isArray(o2)) {
        var s2 = "";
        o2.forEach(function(e2) {
          s2 += stringify3(e2, language);
        });
        return s2;
      }
      var env = {
        type: o2.type,
        content: stringify3(o2.content, language),
        tag: "span",
        classes: ["token", o2.type],
        attributes: {},
        language
      };
      var aliases = o2.alias;
      if (aliases) {
        if (Array.isArray(aliases)) {
          Array.prototype.push.apply(env.classes, aliases);
        } else {
          env.classes.push(aliases);
        }
      }
      _2.hooks.run("wrap", env);
      var attributes = "";
      for (var name in env.attributes) {
        attributes += " " + name + '="' + (env.attributes[name] || "").replace(/"/g, "&quot;") + '"';
      }
      return "<" + env.tag + ' class="' + env.classes.join(" ") + '"' + attributes + ">" + env.content + "</" + env.tag + ">";
    };
    function matchPattern(pattern, pos2, text, lookbehind) {
      pattern.lastIndex = pos2;
      var match = pattern.exec(text);
      if (match && lookbehind && match[1]) {
        var lookbehindLength = match[1].length;
        match.index += lookbehindLength;
        match[0] = match[0].slice(lookbehindLength);
      }
      return match;
    }
    function matchGrammar(text, tokenList, grammar, startNode, startPos, rematch) {
      for (var token2 in grammar) {
        if (!grammar.hasOwnProperty(token2) || !grammar[token2]) {
          continue;
        }
        var patterns = grammar[token2];
        patterns = Array.isArray(patterns) ? patterns : [patterns];
        for (var j2 = 0; j2 < patterns.length; ++j2) {
          if (rematch && rematch.cause == token2 + "," + j2) {
            return;
          }
          var patternObj = patterns[j2];
          var inside = patternObj.inside;
          var lookbehind = !!patternObj.lookbehind;
          var greedy = !!patternObj.greedy;
          var alias = patternObj.alias;
          if (greedy && !patternObj.pattern.global) {
            var flags = patternObj.pattern.toString().match(/[imsuy]*$/)[0];
            patternObj.pattern = RegExp(patternObj.pattern.source, flags + "g");
          }
          var pattern = patternObj.pattern || patternObj;
          for (var currentNode = startNode.next, pos2 = startPos; currentNode !== tokenList.tail; pos2 += currentNode.value.length, currentNode = currentNode.next) {
            if (rematch && pos2 >= rematch.reach) {
              break;
            }
            var str = currentNode.value;
            if (tokenList.length > text.length) {
              return;
            }
            if (str instanceof Token) {
              continue;
            }
            var removeCount = 1;
            var match;
            if (greedy) {
              match = matchPattern(pattern, pos2, text, lookbehind);
              if (!match || match.index >= text.length) {
                break;
              }
              var from = match.index;
              var to = match.index + match[0].length;
              var p2 = pos2;
              p2 += currentNode.value.length;
              while (from >= p2) {
                currentNode = currentNode.next;
                p2 += currentNode.value.length;
              }
              p2 -= currentNode.value.length;
              pos2 = p2;
              if (currentNode.value instanceof Token) {
                continue;
              }
              for (var k2 = currentNode; k2 !== tokenList.tail && (p2 < to || typeof k2.value === "string"); k2 = k2.next) {
                removeCount++;
                p2 += k2.value.length;
              }
              removeCount--;
              str = text.slice(pos2, p2);
              match.index -= pos2;
            } else {
              match = matchPattern(pattern, 0, str, lookbehind);
              if (!match) {
                continue;
              }
            }
            var from = match.index;
            var matchStr = match[0];
            var before = str.slice(0, from);
            var after = str.slice(from + matchStr.length);
            var reach = pos2 + str.length;
            if (rematch && reach > rematch.reach) {
              rematch.reach = reach;
            }
            var removeFrom = currentNode.prev;
            if (before) {
              removeFrom = addAfter(tokenList, removeFrom, before);
              pos2 += before.length;
            }
            removeRange(tokenList, removeFrom, removeCount);
            var wrapped = new Token(token2, inside ? _2.tokenize(matchStr, inside) : matchStr, alias, matchStr);
            currentNode = addAfter(tokenList, removeFrom, wrapped);
            if (after) {
              addAfter(tokenList, currentNode, after);
            }
            if (removeCount > 1) {
              var nestedRematch = {
                cause: token2 + "," + j2,
                reach
              };
              matchGrammar(text, tokenList, grammar, currentNode.prev, pos2, nestedRematch);
              if (rematch && nestedRematch.reach > rematch.reach) {
                rematch.reach = nestedRematch.reach;
              }
            }
          }
        }
      }
    }
    function LinkedList() {
      var head = { value: null, prev: null, next: null };
      var tail = { value: null, prev: head, next: null };
      head.next = tail;
      this.head = head;
      this.tail = tail;
      this.length = 0;
    }
    function addAfter(list, node, value) {
      var next = node.next;
      var newNode = { value, prev: node, next };
      node.next = newNode;
      next.prev = newNode;
      list.length++;
      return newNode;
    }
    function removeRange(list, node, count) {
      var next = node.next;
      for (var i2 = 0; i2 < count && next !== list.tail; i2++) {
        next = next.next;
      }
      node.next = next;
      next.prev = node;
      list.length -= i2;
    }
    function toArray(list) {
      var array = [];
      var node = list.head.next;
      while (node !== list.tail) {
        array.push(node.value);
        node = node.next;
      }
      return array;
    }
    if (!_self2.document) {
      if (!_self2.addEventListener) {
        return _2;
      }
      if (!_2.disableWorkerMessageHandler) {
        _self2.addEventListener("message", function(evt) {
          var message = JSON.parse(evt.data);
          var lang2 = message.language;
          var code = message.code;
          var immediateClose = message.immediateClose;
          _self2.postMessage(_2.highlight(code, _2.languages[lang2], lang2));
          if (immediateClose) {
            _self2.close();
          }
        }, false);
      }
      return _2;
    }
    var script = _2.util.currentScript();
    if (script) {
      _2.filename = script.src;
      if (script.hasAttribute("data-manual")) {
        _2.manual = true;
      }
    }
    function highlightAutomaticallyCallback() {
      if (!_2.manual) {
        _2.highlightAll();
      }
    }
    if (!_2.manual) {
      var readyState = document.readyState;
      if (readyState === "loading" || readyState === "interactive" && script && script.defer) {
        document.addEventListener("DOMContentLoaded", highlightAutomaticallyCallback);
      } else {
        if (window.requestAnimationFrame) {
          window.requestAnimationFrame(highlightAutomaticallyCallback);
        } else {
          window.setTimeout(highlightAutomaticallyCallback, 16);
        }
      }
    }
    return _2;
  }(_self);
  if (module.exports) {
    module.exports = Prism2;
  }
  if (typeof commonjsGlobal !== "undefined") {
    commonjsGlobal.Prism = Prism2;
  }
  Prism2.languages.markup = {
    "comment": {
      pattern: /<!--(?:(?!<!--)[\s\S])*?-->/,
      greedy: true
    },
    "prolog": {
      pattern: /<\?[\s\S]+?\?>/,
      greedy: true
    },
    "doctype": {
      // https://www.w3.org/TR/xml/#NT-doctypedecl
      pattern: /<!DOCTYPE(?:[^>"'[\]]|"[^"]*"|'[^']*')+(?:\[(?:[^<"'\]]|"[^"]*"|'[^']*'|<(?!!--)|<!--(?:[^-]|-(?!->))*-->)*\]\s*)?>/i,
      greedy: true,
      inside: {
        "internal-subset": {
          pattern: /(^[^\[]*\[)[\s\S]+(?=\]>$)/,
          lookbehind: true,
          greedy: true,
          inside: null
          // see below
        },
        "string": {
          pattern: /"[^"]*"|'[^']*'/,
          greedy: true
        },
        "punctuation": /^<!|>$|[[\]]/,
        "doctype-tag": /^DOCTYPE/i,
        "name": /[^\s<>'"]+/
      }
    },
    "cdata": {
      pattern: /<!\[CDATA\[[\s\S]*?\]\]>/i,
      greedy: true
    },
    "tag": {
      pattern: /<\/?(?!\d)[^\s>\/=$<%]+(?:\s(?:\s*[^\s>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s'">=]+(?=[\s>]))|(?=[\s/>])))+)?\s*\/?>/,
      greedy: true,
      inside: {
        "tag": {
          pattern: /^<\/?[^\s>\/]+/,
          inside: {
            "punctuation": /^<\/?/,
            "namespace": /^[^\s>\/:]+:/
          }
        },
        "special-attr": [],
        "attr-value": {
          pattern: /=\s*(?:"[^"]*"|'[^']*'|[^\s'">=]+)/,
          inside: {
            "punctuation": [
              {
                pattern: /^=/,
                alias: "attr-equals"
              },
              {
                pattern: /^(\s*)["']|["']$/,
                lookbehind: true
              }
            ]
          }
        },
        "punctuation": /\/?>/,
        "attr-name": {
          pattern: /[^\s>\/]+/,
          inside: {
            "namespace": /^[^\s>\/:]+:/
          }
        }
      }
    },
    "entity": [
      {
        pattern: /&[\da-z]{1,8};/i,
        alias: "named-entity"
      },
      /&#x?[\da-f]{1,8};/i
    ]
  };
  Prism2.languages.markup["tag"].inside["attr-value"].inside["entity"] = Prism2.languages.markup["entity"];
  Prism2.languages.markup["doctype"].inside["internal-subset"].inside = Prism2.languages.markup;
  Prism2.hooks.add("wrap", function(env) {
    if (env.type === "entity") {
      env.attributes["title"] = env.content.replace(/&amp;/, "&");
    }
  });
  Object.defineProperty(Prism2.languages.markup.tag, "addInlined", {
    /**
     * Adds an inlined language to markup.
     *
     * An example of an inlined language is CSS with `<style>` tags.
     *
     * @param {string} tagName The name of the tag that contains the inlined language. This name will be treated as
     * case insensitive.
     * @param {string} lang The language key.
     * @example
     * addInlined('style', 'css');
     */
    value: function addInlined(tagName, lang) {
      var includedCdataInside = {};
      includedCdataInside["language-" + lang] = {
        pattern: /(^<!\[CDATA\[)[\s\S]+?(?=\]\]>$)/i,
        lookbehind: true,
        inside: Prism2.languages[lang]
      };
      includedCdataInside["cdata"] = /^<!\[CDATA\[|\]\]>$/i;
      var inside = {
        "included-cdata": {
          pattern: /<!\[CDATA\[[\s\S]*?\]\]>/i,
          inside: includedCdataInside
        }
      };
      inside["language-" + lang] = {
        pattern: /[\s\S]+/,
        inside: Prism2.languages[lang]
      };
      var def = {};
      def[tagName] = {
        pattern: RegExp(/(<__[^>]*>)(?:<!\[CDATA\[(?:[^\]]|\](?!\]>))*\]\]>|(?!<!\[CDATA\[)[\s\S])*?(?=<\/__>)/.source.replace(/__/g, function() {
          return tagName;
        }), "i"),
        lookbehind: true,
        greedy: true,
        inside
      };
      Prism2.languages.insertBefore("markup", "cdata", def);
    }
  });
  Object.defineProperty(Prism2.languages.markup.tag, "addAttribute", {
    /**
     * Adds an pattern to highlight languages embedded in HTML attributes.
     *
     * An example of an inlined language is CSS with `style` attributes.
     *
     * @param {string} attrName The name of the tag that contains the inlined language. This name will be treated as
     * case insensitive.
     * @param {string} lang The language key.
     * @example
     * addAttribute('style', 'css');
     */
    value: function(attrName, lang) {
      Prism2.languages.markup.tag.inside["special-attr"].push({
        pattern: RegExp(
          /(^|["'\s])/.source + "(?:" + attrName + ")" + /\s*=\s*(?:"[^"]*"|'[^']*'|[^\s'">=]+(?=[\s>]))/.source,
          "i"
        ),
        lookbehind: true,
        inside: {
          "attr-name": /^[^\s=]+/,
          "attr-value": {
            pattern: /=[\s\S]+/,
            inside: {
              "value": {
                pattern: /(^=\s*(["']|(?!["'])))\S[\s\S]*(?=\2$)/,
                lookbehind: true,
                alias: [lang, "language-" + lang],
                inside: Prism2.languages[lang]
              },
              "punctuation": [
                {
                  pattern: /^=/,
                  alias: "attr-equals"
                },
                /"|'/
              ]
            }
          }
        }
      });
    }
  });
  Prism2.languages.html = Prism2.languages.markup;
  Prism2.languages.mathml = Prism2.languages.markup;
  Prism2.languages.svg = Prism2.languages.markup;
  Prism2.languages.xml = Prism2.languages.extend("markup", {});
  Prism2.languages.ssml = Prism2.languages.xml;
  Prism2.languages.atom = Prism2.languages.xml;
  Prism2.languages.rss = Prism2.languages.xml;
  (function(Prism3) {
    var string = /(?:"(?:\\(?:\r\n|[\s\S])|[^"\\\r\n])*"|'(?:\\(?:\r\n|[\s\S])|[^'\\\r\n])*')/;
    Prism3.languages.css = {
      "comment": /\/\*[\s\S]*?\*\//,
      "atrule": {
        pattern: RegExp("@[\\w-](?:" + /[^;{\s"']|\s+(?!\s)/.source + "|" + string.source + ")*?" + /(?:;|(?=\s*\{))/.source),
        inside: {
          "rule": /^@[\w-]+/,
          "selector-function-argument": {
            pattern: /(\bselector\s*\(\s*(?![\s)]))(?:[^()\s]|\s+(?![\s)])|\((?:[^()]|\([^()]*\))*\))+(?=\s*\))/,
            lookbehind: true,
            alias: "selector"
          },
          "keyword": {
            pattern: /(^|[^\w-])(?:and|not|only|or)(?![\w-])/,
            lookbehind: true
          }
          // See rest below
        }
      },
      "url": {
        // https://drafts.csswg.org/css-values-3/#urls
        pattern: RegExp("\\burl\\((?:" + string.source + "|" + /(?:[^\\\r\n()"']|\\[\s\S])*/.source + ")\\)", "i"),
        greedy: true,
        inside: {
          "function": /^url/i,
          "punctuation": /^\(|\)$/,
          "string": {
            pattern: RegExp("^" + string.source + "$"),
            alias: "url"
          }
        }
      },
      "selector": {
        pattern: RegExp(`(^|[{}\\s])[^{}\\s](?:[^{};"'\\s]|\\s+(?![\\s{])|` + string.source + ")*(?=\\s*\\{)"),
        lookbehind: true
      },
      "string": {
        pattern: string,
        greedy: true
      },
      "property": {
        pattern: /(^|[^-\w\xA0-\uFFFF])(?!\s)[-_a-z\xA0-\uFFFF](?:(?!\s)[-\w\xA0-\uFFFF])*(?=\s*:)/i,
        lookbehind: true
      },
      "important": /!important\b/i,
      "function": {
        pattern: /(^|[^-a-z0-9])[-a-z0-9]+(?=\()/i,
        lookbehind: true
      },
      "punctuation": /[(){};:,]/
    };
    Prism3.languages.css["atrule"].inside.rest = Prism3.languages.css;
    var markup = Prism3.languages.markup;
    if (markup) {
      markup.tag.addInlined("style", "css");
      markup.tag.addAttribute("style", "css");
    }
  })(Prism2);
  Prism2.languages.clike = {
    "comment": [
      {
        pattern: /(^|[^\\])\/\*[\s\S]*?(?:\*\/|$)/,
        lookbehind: true,
        greedy: true
      },
      {
        pattern: /(^|[^\\:])\/\/.*/,
        lookbehind: true,
        greedy: true
      }
    ],
    "string": {
      pattern: /(["'])(?:\\(?:\r\n|[\s\S])|(?!\1)[^\\\r\n])*\1/,
      greedy: true
    },
    "class-name": {
      pattern: /(\b(?:class|extends|implements|instanceof|interface|new|trait)\s+|\bcatch\s+\()[\w.\\]+/i,
      lookbehind: true,
      inside: {
        "punctuation": /[.\\]/
      }
    },
    "keyword": /\b(?:break|catch|continue|do|else|finally|for|function|if|in|instanceof|new|null|return|throw|try|while)\b/,
    "boolean": /\b(?:false|true)\b/,
    "function": /\b\w+(?=\()/,
    "number": /\b0x[\da-f]+\b|(?:\b\d+(?:\.\d*)?|\B\.\d+)(?:e[+-]?\d+)?/i,
    "operator": /[<>]=?|[!=]=?=?|--?|\+\+?|&&?|\|\|?|[?*/~^%]/,
    "punctuation": /[{}[\];(),.:]/
  };
  Prism2.languages.javascript = Prism2.languages.extend("clike", {
    "class-name": [
      Prism2.languages.clike["class-name"],
      {
        pattern: /(^|[^$\w\xA0-\uFFFF])(?!\s)[_$A-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*(?=\.(?:constructor|prototype))/,
        lookbehind: true
      }
    ],
    "keyword": [
      {
        pattern: /((?:^|\})\s*)catch\b/,
        lookbehind: true
      },
      {
        pattern: /(^|[^.]|\.\.\.\s*)\b(?:as|assert(?=\s*\{)|async(?=\s*(?:function\b|\(|[$\w\xA0-\uFFFF]|$))|await|break|case|class|const|continue|debugger|default|delete|do|else|enum|export|extends|finally(?=\s*(?:\{|$))|for|from(?=\s*(?:['"]|$))|function|(?:get|set)(?=\s*(?:[#\[$\w\xA0-\uFFFF]|$))|if|implements|import|in|instanceof|interface|let|new|null|of|package|private|protected|public|return|static|super|switch|this|throw|try|typeof|undefined|var|void|while|with|yield)\b/,
        lookbehind: true
      }
    ],
    // Allow for all non-ASCII characters (See http://stackoverflow.com/a/2008444)
    "function": /#?(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*(?=\s*(?:\.\s*(?:apply|bind|call)\s*)?\()/,
    "number": {
      pattern: RegExp(
        /(^|[^\w$])/.source + "(?:" + // constant
        (/NaN|Infinity/.source + "|" + // binary integer
        /0[bB][01]+(?:_[01]+)*n?/.source + "|" + // octal integer
        /0[oO][0-7]+(?:_[0-7]+)*n?/.source + "|" + // hexadecimal integer
        /0[xX][\dA-Fa-f]+(?:_[\dA-Fa-f]+)*n?/.source + "|" + // decimal bigint
        /\d+(?:_\d+)*n/.source + "|" + // decimal number (integer or float) but no bigint
        /(?:\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*)?)?|\.\d+(?:_\d+)*)(?:[Ee][+-]?\d+(?:_\d+)*)?/.source) + ")" + /(?![\w$])/.source
      ),
      lookbehind: true
    },
    "operator": /--|\+\+|\*\*=?|=>|&&=?|\|\|=?|[!=]==|<<=?|>>>?=?|[-+*/%&|^!=<>]=?|\.{3}|\?\?=?|\?\.?|[~:]/
  });
  Prism2.languages.javascript["class-name"][0].pattern = /(\b(?:class|extends|implements|instanceof|interface|new)\s+)[\w.\\]+/;
  Prism2.languages.insertBefore("javascript", "keyword", {
    "regex": {
      pattern: RegExp(
        // lookbehind
        // eslint-disable-next-line regexp/no-dupe-characters-character-class
        /((?:^|[^$\w\xA0-\uFFFF."'\])\s]|\b(?:return|yield))\s*)/.source + // Regex pattern:
        // There are 2 regex patterns here. The RegExp set notation proposal added support for nested character
        // classes if the `v` flag is present. Unfortunately, nested CCs are both context-free and incompatible
        // with the only syntax, so we have to define 2 different regex patterns.
        /\//.source + "(?:" + /(?:\[(?:[^\]\\\r\n]|\\.)*\]|\\.|[^/\\\[\r\n])+\/[dgimyus]{0,7}/.source + "|" + // `v` flag syntax. This supports 3 levels of nested character classes.
        /(?:\[(?:[^[\]\\\r\n]|\\.|\[(?:[^[\]\\\r\n]|\\.|\[(?:[^[\]\\\r\n]|\\.)*\])*\])*\]|\\.|[^/\\\[\r\n])+\/[dgimyus]{0,7}v[dgimyus]{0,7}/.source + ")" + // lookahead
        /(?=(?:\s|\/\*(?:[^*]|\*(?!\/))*\*\/)*(?:$|[\r\n,.;:})\]]|\/\/))/.source
      ),
      lookbehind: true,
      greedy: true,
      inside: {
        "regex-source": {
          pattern: /^(\/)[\s\S]+(?=\/[a-z]*$)/,
          lookbehind: true,
          alias: "language-regex",
          inside: Prism2.languages.regex
        },
        "regex-delimiter": /^\/|\/$/,
        "regex-flags": /^[a-z]+$/
      }
    },
    // This must be declared before keyword because we use "function" inside the look-forward
    "function-variable": {
      pattern: /#?(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*(?=\s*[=:]\s*(?:async\s*)?(?:\bfunction\b|(?:\((?:[^()]|\([^()]*\))*\)|(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*)\s*=>))/,
      alias: "function"
    },
    "parameter": [
      {
        pattern: /(function(?:\s+(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*)?\s*\(\s*)(?!\s)(?:[^()\s]|\s+(?![\s)])|\([^()]*\))+(?=\s*\))/,
        lookbehind: true,
        inside: Prism2.languages.javascript
      },
      {
        pattern: /(^|[^$\w\xA0-\uFFFF])(?!\s)[_$a-z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*(?=\s*=>)/i,
        lookbehind: true,
        inside: Prism2.languages.javascript
      },
      {
        pattern: /(\(\s*)(?!\s)(?:[^()\s]|\s+(?![\s)])|\([^()]*\))+(?=\s*\)\s*=>)/,
        lookbehind: true,
        inside: Prism2.languages.javascript
      },
      {
        pattern: /((?:\b|\s|^)(?!(?:as|async|await|break|case|catch|class|const|continue|debugger|default|delete|do|else|enum|export|extends|finally|for|from|function|get|if|implements|import|in|instanceof|interface|let|new|null|of|package|private|protected|public|return|set|static|super|switch|this|throw|try|typeof|undefined|var|void|while|with|yield)(?![$\w\xA0-\uFFFF]))(?:(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*\s*)\(\s*|\]\s*\(\s*)(?!\s)(?:[^()\s]|\s+(?![\s)])|\([^()]*\))+(?=\s*\)\s*\{)/,
        lookbehind: true,
        inside: Prism2.languages.javascript
      }
    ],
    "constant": /\b[A-Z](?:[A-Z_]|\dx?)*\b/
  });
  Prism2.languages.insertBefore("javascript", "string", {
    "hashbang": {
      pattern: /^#!.*/,
      greedy: true,
      alias: "comment"
    },
    "template-string": {
      pattern: /`(?:\\[\s\S]|\$\{(?:[^{}]|\{(?:[^{}]|\{[^}]*\})*\})+\}|(?!\$\{)[^\\`])*`/,
      greedy: true,
      inside: {
        "template-punctuation": {
          pattern: /^`|`$/,
          alias: "string"
        },
        "interpolation": {
          pattern: /((?:^|[^\\])(?:\\{2})*)\$\{(?:[^{}]|\{(?:[^{}]|\{[^}]*\})*\})+\}/,
          lookbehind: true,
          inside: {
            "interpolation-punctuation": {
              pattern: /^\$\{|\}$/,
              alias: "punctuation"
            },
            rest: Prism2.languages.javascript
          }
        },
        "string": /[\s\S]+/
      }
    },
    "string-property": {
      pattern: /((?:^|[,{])[ \t]*)(["'])(?:\\(?:\r\n|[\s\S])|(?!\2)[^\\\r\n])*\2(?=\s*:)/m,
      lookbehind: true,
      greedy: true,
      alias: "property"
    }
  });
  Prism2.languages.insertBefore("javascript", "operator", {
    "literal-property": {
      pattern: /((?:^|[,{])[ \t]*)(?!\s)[_$a-zA-Z\xA0-\uFFFF](?:(?!\s)[$\w\xA0-\uFFFF])*(?=\s*:)/m,
      lookbehind: true,
      alias: "property"
    }
  });
  if (Prism2.languages.markup) {
    Prism2.languages.markup.tag.addInlined("script", "javascript");
    Prism2.languages.markup.tag.addAttribute(
      /on(?:abort|blur|change|click|composition(?:end|start|update)|dblclick|error|focus(?:in|out)?|key(?:down|up)|load|mouse(?:down|enter|leave|move|out|over|up)|reset|resize|scroll|select|slotchange|submit|unload|wheel)/.source,
      "javascript"
    );
  }
  Prism2.languages.js = Prism2.languages.javascript;
  (function() {
    if (typeof Prism2 === "undefined" || typeof document === "undefined") {
      return;
    }
    if (!Element.prototype.matches) {
      Element.prototype.matches = Element.prototype.msMatchesSelector || Element.prototype.webkitMatchesSelector;
    }
    var LOADING_MESSAGE = "Loading…";
    var FAILURE_MESSAGE = function(status, message) {
      return "✖ Error " + status + " while fetching file: " + message;
    };
    var FAILURE_EMPTY_MESSAGE = "✖ Error: File does not exist or is empty";
    var EXTENSIONS = {
      "js": "javascript",
      "py": "python",
      "rb": "ruby",
      "ps1": "powershell",
      "psm1": "powershell",
      "sh": "bash",
      "bat": "batch",
      "h": "c",
      "tex": "latex"
    };
    var STATUS_ATTR = "data-src-status";
    var STATUS_LOADING = "loading";
    var STATUS_LOADED = "loaded";
    var STATUS_FAILED = "failed";
    var SELECTOR = "pre[data-src]:not([" + STATUS_ATTR + '="' + STATUS_LOADED + '"]):not([' + STATUS_ATTR + '="' + STATUS_LOADING + '"])';
    function loadFile(src, success, error) {
      var xhr = new XMLHttpRequest();
      xhr.open("GET", src, true);
      xhr.onreadystatechange = function() {
        if (xhr.readyState == 4) {
          if (xhr.status < 400 && xhr.responseText) {
            success(xhr.responseText);
          } else {
            if (xhr.status >= 400) {
              error(FAILURE_MESSAGE(xhr.status, xhr.statusText));
            } else {
              error(FAILURE_EMPTY_MESSAGE);
            }
          }
        }
      };
      xhr.send(null);
    }
    function parseRange(range) {
      var m2 = /^\s*(\d+)\s*(?:(,)\s*(?:(\d+)\s*)?)?$/.exec(range || "");
      if (m2) {
        var start2 = Number(m2[1]);
        var comma = m2[2];
        var end2 = m2[3];
        if (!comma) {
          return [start2, start2];
        }
        if (!end2) {
          return [start2, void 0];
        }
        return [start2, Number(end2)];
      }
      return void 0;
    }
    Prism2.hooks.add("before-highlightall", function(env) {
      env.selector += ", " + SELECTOR;
    });
    Prism2.hooks.add("before-sanity-check", function(env) {
      var pre = (
        /** @type {HTMLPreElement} */
        env.element
      );
      if (pre.matches(SELECTOR)) {
        env.code = "";
        pre.setAttribute(STATUS_ATTR, STATUS_LOADING);
        var code = pre.appendChild(document.createElement("CODE"));
        code.textContent = LOADING_MESSAGE;
        var src = pre.getAttribute("data-src");
        var language = env.language;
        if (language === "none") {
          var extension = (/\.(\w+)$/.exec(src) || [, "none"])[1];
          language = EXTENSIONS[extension] || extension;
        }
        Prism2.util.setLanguage(code, language);
        Prism2.util.setLanguage(pre, language);
        var autoloader = Prism2.plugins.autoloader;
        if (autoloader) {
          autoloader.loadLanguages(language);
        }
        loadFile(
          src,
          function(text) {
            pre.setAttribute(STATUS_ATTR, STATUS_LOADED);
            var range = parseRange(pre.getAttribute("data-range"));
            if (range) {
              var lines = text.split(/\r\n?|\n/g);
              var start2 = range[0];
              var end2 = range[1] == null ? lines.length : range[1];
              if (start2 < 0) {
                start2 += lines.length;
              }
              start2 = Math.max(0, Math.min(start2 - 1, lines.length));
              if (end2 < 0) {
                end2 += lines.length;
              }
              end2 = Math.max(0, Math.min(end2, lines.length));
              text = lines.slice(start2, end2).join("\n");
              if (!pre.hasAttribute("data-start")) {
                pre.setAttribute("data-start", String(start2 + 1));
              }
            }
            code.textContent = text;
            Prism2.highlightElement(code);
          },
          function(error) {
            pre.setAttribute(STATUS_ATTR, STATUS_FAILED);
            code.textContent = error;
          }
        );
      }
    });
    Prism2.plugins.fileHighlight = {
      /**
       * Executes the File Highlight plugin for all matching `pre` elements under the given container.
       *
       * Note: Elements which are already loaded or currently loading will not be touched by this method.
       *
       * @param {ParentNode} [container=document]
       */
      highlight: function highlight(container) {
        var elements = (container || document).querySelectorAll(SELECTOR);
        for (var i2 = 0, element; element = elements[i2++]; ) {
          Prism2.highlightElement(element);
        }
      }
    };
    var logged = false;
    Prism2.fileHighlight = function() {
      if (!logged) {
        console.warn("Prism.fileHighlight is deprecated. Use `Prism.plugins.fileHighlight.highlight` instead.");
        logged = true;
      }
      Prism2.plugins.fileHighlight.highlight.apply(this, arguments);
    };
  })();
})(prism);
var prismExports = prism.exports;
const Prism$1 = /* @__PURE__ */ getDefaultExportFromCjs(prismExports);
const EmptyPanel = ({ id, classes, height, style, children }) => {
  const emptyStyle = {
    display: "flex",
    textAlign: "center",
    flex: "0 0 content",
    alignItems: "center",
    justifyContent: "center",
    height: height ? height : "10rem"
  };
  return m$1`
    <div
      ...${{ id }}
      class="${classes ? classes : ""}"
      style=${{ width: "100%" }}
    >
      <div style=${{ ...emptyStyle, ...style }}>
        <div>${children || ""}</div>
      </div>
    </div>
  `;
};
const TabSet = ({ id, type, classes, tools, styles, children }) => {
  if (!id) {
    throw new Error("Tabsets require an id to function properly");
  }
  const tabs = children;
  const tabType = type || "tabs";
  const tabSetStyle = {
    alignItems: "space-between"
  };
  return m$1`<ul
      ...${{ id }}
      class="nav nav-${tabType} ${classes ? classes : ""}"
      role="tablist"
      aria-orientation="horizontal"
      style=${{ ...tabSetStyle, ...styles.tabSet }}
    >
      <${Tabs} tabs=${tabs} type=${tabType} style=${styles.tabs} />
      <${TabTools} tools=${tools} />
    </ul>
    <${TabPanels} id=${id} tabs=${tabs} style=${styles.tabBody} />`;
};
const TabPanel = ({
  id,
  index,
  selected,
  style,
  scrollable,
  children
}) => {
  const tabContentsId = computeTabContentsId(id, index);
  return m$1`<div
    id="${tabContentsId}"
    class="tab-pane show ${selected ? "active" : ""}"
    style=${{
    flex: "1",
    overflowY: scrollable === void 0 || scrollable ? "auto" : "hidden",
    ...style
  }}
  >
    ${children}
  </div>`;
};
const Tabs = ({ tabs, type, style }) => {
  return tabs.map((tab, index) => {
    return m$1` <${Tab2}
      type=${type || "tabs"}
      tab=${tab}
      index=${index}
      style=${style}
    />`;
  });
};
const Tab2 = ({ type, tab, index, style }) => {
  const tabId = tab.props.id || computeTabId("tabset", index);
  const tabContentsId = computeTabContentsId(tab.props.id, index);
  const isActive = tab.props.selected;
  const tabStyle = {
    color: "var(--bs-body-color)",
    ...style,
    padding: "0.25rem 0.5rem"
  };
  const pillStyle = {
    ...style
  };
  return m$1`
    <li class="nav-item" role="presentation" style=${{ alignSelf: "end" }}>
      <button
        id="${tabId}"
        style=${type === "tabs" ? tabStyle : pillStyle}
        class="nav-link ${isActive ? "active" : ""}"
        data-bs-toggle="tab"
        data-bs-target="#${tabContentsId}"
        type="button"
        role="tab"
        aria-controls="${tabContentsId}"
        aria-selected="${isActive ? true : false}"
        ...${{
    onclick: (e2) => {
      tab.props.onSelected(e2);
      return false;
    }
  }}
      >
        ${tab.props.icon ? m$1`<i
              class="${tab.props.icon}"
              style=${{ marginRight: "0.5em" }}
            ></i>` : ""}
        ${tab.props.title}
      </button>
    </li>
  `;
};
const TabTools = ({ tools }) => {
  return m$1`<div
    class="tab-tools"
    style=${{
    flexBasis: "auto",
    marginLeft: "auto",
    display: "flex",
    alignItems: "center",
    justifyContent: "end",
    flexWrap: "wrap",
    rowGap: "0.3rem"
  }}
  >
    ${tools}
  </div>`;
};
const TabPanels = ({ id, tabs, style }) => {
  return m$1`<div class="tab-content" id="${id}-content" style=${{ ...style }}>
    ${tabs.map((tab, index) => {
    tab.props.index = index;
    return tab;
  })}
  </div>`;
};
const computeTabId = (id, index) => {
  return `${id}-${index}`;
};
const computeTabContentsId = (id, index) => {
  return `${id}-contents-${index}`;
};
const ToolButton = ({ name, classes, icon, onclick, ...rest }) => {
  const attr = {
    type: "button",
    class: `btn btn-tools ${classes || ""}`,
    onclick,
    ...rest
  };
  const iconEl = icon ? m$1`<i class="${icon}" style=${{ marginRight: "0.5em" }}></i>` : "";
  return _("button", attr, m$1`${iconEl}${name}`);
};
const ghCommitUrl = (origin, commit) => {
  const baseUrl = origin.replace(/\.git$/, "");
  return `${baseUrl}/commit/${commit}`;
};
const CardHeader = ({ id, icon, label, classes, style, children }) => {
  return m$1`<div class="card-header ${classes || ""}" ...${{ id, style }}>
    ${icon ? m$1`<i
          class="${icon}"
          style=${{
    paddingRight: "0.2rem"
  }}
        ></i>` : ""}
    ${label ? label : ""} ${children}
  </div> `;
};
const CardBody = ({ id, classes, style, children }) => {
  return m$1`<div class="card-body ${classes || ""}" ...${{ id, style }}>
    ${children}
  </div>`;
};
const Card = ({ id, classes, style, children }) => {
  return m$1`
    <div class="card ${classes || ""}" ...${{ id, style }}>${children}</div>
  `;
};
var e, t, r = { exports: {} };
e = r, t = function(e2, t2) {
  Object.defineProperty(t2, "__esModule", { value: true }), t2.ANSIOutput = t2.ANSIColor = t2.ANSIFont = t2.ANSIStyle = void 0;
  let r2 = 0;
  const n2 = () => ("" + ++r2).padStart(16, "0");
  var o2, i2, s2, a2, u2, l2, g2;
  (function(e3) {
    e3.Bold = "ansiBold", e3.Dim = "ansiDim", e3.Italic = "ansiItalic", e3.Underlined = "ansiUnderlined", e3.SlowBlink = "ansiSlowBlink", e3.RapidBlink = "ansiRapidBlink", e3.Hidden = "ansiHidden", e3.CrossedOut = "ansiCrossedOut", e3.Fraktur = "ansiFraktur", e3.DoubleUnderlined = "ansiDoubleUnderlined", e3.Framed = "ansiFramed", e3.Encircled = "ansiEncircled", e3.Overlined = "ansiOverlined", e3.Superscript = "ansiSuperscript", e3.Subscript = "ansiSubscript";
  })(o2 || (t2.ANSIStyle = o2 = {})), function(e3) {
    e3.AlternativeFont1 = "ansiAlternativeFont1", e3.AlternativeFont2 = "ansiAlternativeFont2", e3.AlternativeFont3 = "ansiAlternativeFont3", e3.AlternativeFont4 = "ansiAlternativeFont4", e3.AlternativeFont5 = "ansiAlternativeFont5", e3.AlternativeFont6 = "ansiAlternativeFont6", e3.AlternativeFont7 = "ansiAlternativeFont7", e3.AlternativeFont8 = "ansiAlternativeFont8", e3.AlternativeFont9 = "ansiAlternativeFont9";
  }(i2 || (t2.ANSIFont = i2 = {})), function(e3) {
    e3.Black = "ansiBlack", e3.Red = "ansiRed", e3.Green = "ansiGreen", e3.Yellow = "ansiYellow", e3.Blue = "ansiBlue", e3.Magenta = "ansiMagenta", e3.Cyan = "ansiCyan", e3.White = "ansiWhite", e3.BrightBlack = "ansiBrightBlack", e3.BrightRed = "ansiBrightRed", e3.BrightGreen = "ansiBrightGreen", e3.BrightYellow = "ansiBrightYellow", e3.BrightBlue = "ansiBrightBlue", e3.BrightMagenta = "ansiBrightMagenta", e3.BrightCyan = "ansiBrightCyan", e3.BrightWhite = "ansiBrightWhite";
  }(s2 || (t2.ANSIColor = s2 = {}));
  class h2 {
    constructor() {
      __publicField(this, "_parserState", g2.BufferingOutput);
      __publicField(this, "_controlSequence", "");
      __publicField(this, "_sgrState");
      __publicField(this, "_outputLines", []);
      __publicField(this, "_outputLine", 0);
      __publicField(this, "_outputColumn", 0);
      __publicField(this, "_buffer", "");
      __publicField(this, "_pendingNewline", false);
    }
    get outputLines() {
      return this.flushBuffer(), this._outputLines;
    }
    static processOutput(e3) {
      const t3 = new h2();
      return t3.processOutput(e3), t3.outputLines;
    }
    processOutput(e3) {
      for (let t3 = 0; t3 < e3.length; t3++) {
        this._pendingNewline && (this.flushBuffer(), this._outputLine++, this._outputColumn = 0, this._pendingNewline = false);
        const r3 = e3.charAt(t3);
        this._parserState === g2.BufferingOutput ? "\x1B" === r3 ? (this.flushBuffer(), this._parserState = g2.ControlSequenceStarted) : "" === r3 ? (this.flushBuffer(), this._parserState = g2.ParsingControlSequence) : this.processCharacter(r3) : this._parserState === g2.ControlSequenceStarted ? "[" === r3 ? this._parserState = g2.ParsingControlSequence : (this._parserState = g2.BufferingOutput, this.processCharacter(r3)) : this._parserState === g2.ParsingControlSequence && (this._controlSequence += r3, r3.match(/^[A-Za-z]$/) && this.processControlSequence());
      }
      this.flushBuffer();
    }
    flushBuffer() {
      for (let e3 = this._outputLines.length; e3 < this._outputLine + 1; e3++)
        this._outputLines.push(new d2());
      this._buffer && (this._outputLines[this._outputLine].insert(
        this._buffer,
        this._outputColumn,
        this._sgrState
      ), this._outputColumn += this._buffer.length, this._buffer = "");
    }
    processCharacter(e3) {
      switch (e3) {
        case "\n":
          this._pendingNewline = true;
          break;
        case "\r":
          this.flushBuffer(), this._outputColumn = 0;
          break;
        default:
          this._buffer += e3;
      }
    }
    processControlSequence() {
      switch (this._controlSequence.charAt(this._controlSequence.length - 1)) {
        case "A":
          this.processCUU();
          break;
        case "B":
          this.processCUD();
          break;
        case "C":
          this.processCUF();
          break;
        case "D":
          this.processCUB();
          break;
        case "H":
          this.processCUP();
          break;
        case "J":
          this.processED();
          break;
        case "K":
          this.processEL();
          break;
        case "m":
          this.processSGR();
      }
      this._controlSequence = "", this._parserState = g2.BufferingOutput;
    }
    processCUU() {
      const e3 = this._controlSequence.match(/^([0-9]*)A$/);
      e3 && (this._outputLine = Math.max(this._outputLine - k2(e3[1], 1, 1), 0));
    }
    processCUD() {
      const e3 = this._controlSequence.match(/^([0-9]*)B$/);
      e3 && (this._outputLine = this._outputLine + k2(e3[1], 1, 1));
    }
    processCUF() {
      const e3 = this._controlSequence.match(/^([0-9]*)C$/);
      e3 && (this._outputColumn = this._outputColumn + k2(e3[1], 1, 1));
    }
    processCUB() {
      const e3 = this._controlSequence.match(/^([0-9]*)D$/);
      e3 && (this._outputColumn = Math.max(
        this._outputColumn - k2(e3[1], 1, 1),
        0
      ));
    }
    processCUP() {
      const e3 = this._controlSequence.match(/^([0-9]*)(?:;?([0-9]*))H$/);
      e3 && (this._outputLine = k2(e3[1], 1, 1) - 1, this._outputColumn = k2(e3[2], 1, 1) - 1);
    }
    processED() {
      const e3 = this._controlSequence.match(/^([0-9]*)J$/);
      if (e3)
        switch (p2(e3[1], 0)) {
          case 0:
            this._outputLines[this._outputLine].clearToEndOfLine(
              this._outputColumn
            );
            for (let e4 = this._outputLine + 1; e4 < this._outputLines.length; e4++)
              this._outputLines[e4].clearEntireLine();
            break;
          case 1:
            this._outputLines[this._outputLine].clearToBeginningOfLine(
              this._outputColumn
            );
            for (let e4 = 0; e4 < this._outputLine; e4++)
              this._outputLines[e4].clearEntireLine();
            break;
          case 2:
            for (let e4 = 0; e4 < this._outputLines.length; e4++)
              this._outputLines[e4].clearEntireLine();
        }
    }
    processEL() {
      const e3 = this._controlSequence.match(/^([0-9]*)K$/);
      if (e3) {
        const t3 = this._outputLines[this._outputLine];
        switch (p2(e3[1], 0)) {
          case 0:
            t3.clearToEndOfLine(this._outputColumn);
            break;
          case 1:
            t3.clearToBeginningOfLine(this._outputColumn);
            break;
          case 2:
            t3.clearEntireLine();
        }
      }
    }
    processSGR() {
      const e3 = this._sgrState ? this._sgrState.copy() : new c2(), t3 = this._controlSequence.slice(0, -1).split(";").map((e4) => "" === e4 ? a2.Reset : parseInt(e4, 10));
      for (let r3 = 0; r3 < t3.length; r3++) {
        const n3 = () => {
          if (r3 + 1 !== t3.length)
            switch (t3[++r3]) {
              case u2.Color256: {
                if (r3 + 1 === t3.length) return;
                const e4 = t3[++r3];
                switch (e4) {
                  case l2.Black:
                    return s2.Black;
                  case l2.Red:
                    return s2.Red;
                  case l2.Green:
                    return s2.Green;
                  case l2.Yellow:
                    return s2.Yellow;
                  case l2.Blue:
                    return s2.Blue;
                  case l2.Magenta:
                    return s2.Magenta;
                  case l2.Cyan:
                    return s2.Cyan;
                  case l2.White:
                    return s2.White;
                  case l2.BrightBlack:
                    return s2.BrightBlack;
                  case l2.BrightRed:
                    return s2.BrightRed;
                  case l2.BrightGreen:
                    return s2.BrightGreen;
                  case l2.BrightYellow:
                    return s2.BrightYellow;
                  case l2.BrightBlue:
                    return s2.BrightBlue;
                  case l2.BrightMagenta:
                    return s2.BrightMagenta;
                  case l2.BrightCyan:
                    return s2.BrightCyan;
                  case l2.BrightWhite:
                    return s2.BrightWhite;
                  default:
                    if (e4 % 1 != 0) return;
                    if (e4 >= 16 && e4 <= 231) {
                      let t4 = e4 - 16, r4 = t4 % 6;
                      t4 = (t4 - r4) / 6;
                      let n4 = t4 % 6;
                      t4 = (t4 - n4) / 6;
                      let o3 = t4;
                      return r4 = Math.round(255 * r4 / 5), n4 = Math.round(255 * n4 / 5), o3 = Math.round(255 * o3 / 5), "#" + _2(o3) + _2(n4) + _2(r4);
                    }
                    if (e4 >= 232 && e4 <= 255) {
                      const t4 = Math.round((e4 - 232) / 23 * 255), r4 = _2(t4);
                      return "#" + r4 + r4 + r4;
                    }
                    return;
                }
              }
              case u2.ColorRGB: {
                const e4 = [0, 0, 0];
                for (let n4 = 0; n4 < 3 && r3 + 1 < t3.length; n4++) e4[n4] = t3[++r3];
                return "#" + _2(e4[0]) + _2(e4[1]) + _2(e4[2]);
              }
            }
        };
        switch (t3[r3]) {
          case a2.Reset:
            e3.reset();
            break;
          case a2.Bold:
            e3.setStyle(o2.Bold);
            break;
          case a2.Dim:
            e3.setStyle(o2.Dim);
            break;
          case a2.Italic:
            e3.setStyle(o2.Italic);
            break;
          case a2.Underlined:
            e3.setStyle(o2.Underlined, o2.DoubleUnderlined);
            break;
          case a2.SlowBlink:
            e3.setStyle(o2.SlowBlink, o2.RapidBlink);
            break;
          case a2.RapidBlink:
            e3.setStyle(o2.RapidBlink, o2.SlowBlink);
            break;
          case a2.Reversed:
            e3.setReversed(true);
            break;
          case a2.Hidden:
            e3.setStyle(o2.Hidden);
            break;
          case a2.CrossedOut:
            e3.setStyle(o2.CrossedOut);
            break;
          case a2.PrimaryFont:
            e3.setFont();
            break;
          case a2.AlternativeFont1:
            e3.setFont(i2.AlternativeFont1);
            break;
          case a2.AlternativeFont2:
            e3.setFont(i2.AlternativeFont2);
            break;
          case a2.AlternativeFont3:
            e3.setFont(i2.AlternativeFont3);
            break;
          case a2.AlternativeFont4:
            e3.setFont(i2.AlternativeFont4);
            break;
          case a2.AlternativeFont5:
            e3.setFont(i2.AlternativeFont5);
            break;
          case a2.AlternativeFont6:
            e3.setFont(i2.AlternativeFont6);
            break;
          case a2.AlternativeFont7:
            e3.setFont(i2.AlternativeFont7);
            break;
          case a2.AlternativeFont8:
            e3.setFont(i2.AlternativeFont8);
            break;
          case a2.AlternativeFont9:
            e3.setFont(i2.AlternativeFont9);
            break;
          case a2.Fraktur:
            e3.setStyle(o2.Fraktur);
            break;
          case a2.DoubleUnderlined:
            e3.setStyle(o2.DoubleUnderlined, o2.Underlined);
            break;
          case a2.NormalIntensity:
            e3.deleteStyles(o2.Bold, o2.Dim);
            break;
          case a2.NotItalicNotFraktur:
            e3.deleteStyles(o2.Italic, o2.Fraktur);
            break;
          case a2.NotUnderlined:
            e3.deleteStyles(o2.Underlined, o2.DoubleUnderlined);
            break;
          case a2.NotBlinking:
            e3.deleteStyles(o2.SlowBlink, o2.RapidBlink);
            break;
          case a2.ProportionalSpacing:
            break;
          case a2.NotReversed:
            e3.setReversed(false);
            break;
          case a2.Reveal:
            e3.deleteStyles(o2.Hidden);
            break;
          case a2.NotCrossedOut:
            e3.deleteStyles(o2.CrossedOut);
            break;
          case a2.ForegroundBlack:
            e3.setForegroundColor(s2.Black);
            break;
          case a2.ForegroundRed:
            e3.setForegroundColor(s2.Red);
            break;
          case a2.ForegroundGreen:
            e3.setForegroundColor(s2.Green);
            break;
          case a2.ForegroundYellow:
            e3.setForegroundColor(s2.Yellow);
            break;
          case a2.ForegroundBlue:
            e3.setForegroundColor(s2.Blue);
            break;
          case a2.ForegroundMagenta:
            e3.setForegroundColor(s2.Magenta);
            break;
          case a2.ForegroundCyan:
            e3.setForegroundColor(s2.Cyan);
            break;
          case a2.ForegroundWhite:
            e3.setForegroundColor(s2.White);
            break;
          case a2.SetForeground: {
            const t4 = n3();
            t4 && e3.setForegroundColor(t4);
            break;
          }
          case a2.DefaultForeground:
            e3.setForegroundColor();
            break;
          case a2.BackgroundBlack:
            e3.setBackgroundColor(s2.Black);
            break;
          case a2.BackgroundRed:
            e3.setBackgroundColor(s2.Red);
            break;
          case a2.BackgroundGreen:
            e3.setBackgroundColor(s2.Green);
            break;
          case a2.BackgroundYellow:
            e3.setBackgroundColor(s2.Yellow);
            break;
          case a2.BackgroundBlue:
            e3.setBackgroundColor(s2.Blue);
            break;
          case a2.BackgroundMagenta:
            e3.setBackgroundColor(s2.Magenta);
            break;
          case a2.BackgroundCyan:
            e3.setBackgroundColor(s2.Cyan);
            break;
          case a2.BackgroundWhite:
            e3.setBackgroundColor(s2.White);
            break;
          case a2.SetBackground: {
            const t4 = n3();
            t4 && e3.setBackgroundColor(t4);
            break;
          }
          case a2.DefaultBackground:
            e3.setBackgroundColor();
            break;
          case a2.ForegroundBrightBlack:
            e3.setForegroundColor(s2.BrightBlack);
            break;
          case a2.ForegroundBrightRed:
            e3.setForegroundColor(s2.BrightRed);
            break;
          case a2.ForegroundBrightGreen:
            e3.setForegroundColor(s2.BrightGreen);
            break;
          case a2.ForegroundBrightYellow:
            e3.setForegroundColor(s2.BrightYellow);
            break;
          case a2.ForegroundBrightBlue:
            e3.setForegroundColor(s2.BrightBlue);
            break;
          case a2.ForegroundBrightMagenta:
            e3.setForegroundColor(s2.BrightMagenta);
            break;
          case a2.ForegroundBrightCyan:
            e3.setForegroundColor(s2.BrightCyan);
            break;
          case a2.ForegroundBrightWhite:
            e3.setForegroundColor(s2.BrightWhite);
            break;
          case a2.BackgroundBrightBlack:
            e3.setBackgroundColor(s2.BrightBlack);
            break;
          case a2.BackgroundBrightRed:
            e3.setBackgroundColor(s2.BrightRed);
            break;
          case a2.BackgroundBrightGreen:
            e3.setBackgroundColor(s2.BrightGreen);
            break;
          case a2.BackgroundBrightYellow:
            e3.setBackgroundColor(s2.BrightYellow);
            break;
          case a2.BackgroundBrightBlue:
            e3.setBackgroundColor(s2.BrightBlue);
            break;
          case a2.BackgroundBrightMagenta:
            e3.setBackgroundColor(s2.BrightMagenta);
            break;
          case a2.BackgroundBrightCyan:
            e3.setBackgroundColor(s2.BrightCyan);
            break;
          case a2.BackgroundBrightWhite:
            e3.setBackgroundColor(s2.BrightWhite);
        }
      }
      c2.equivalent(e3, this._sgrState) || (this._sgrState = e3);
    }
  }
  t2.ANSIOutput = h2, function(e3) {
    e3[e3.Reset = 0] = "Reset", e3[e3.Bold = 1] = "Bold", e3[e3.Dim = 2] = "Dim", e3[e3.Italic = 3] = "Italic", e3[e3.Underlined = 4] = "Underlined", e3[e3.SlowBlink = 5] = "SlowBlink", e3[e3.RapidBlink = 6] = "RapidBlink", e3[e3.Reversed = 7] = "Reversed", e3[e3.Hidden = 8] = "Hidden", e3[e3.CrossedOut = 9] = "CrossedOut", e3[e3.PrimaryFont = 10] = "PrimaryFont", e3[e3.AlternativeFont1 = 11] = "AlternativeFont1", e3[e3.AlternativeFont2 = 12] = "AlternativeFont2", e3[e3.AlternativeFont3 = 13] = "AlternativeFont3", e3[e3.AlternativeFont4 = 14] = "AlternativeFont4", e3[e3.AlternativeFont5 = 15] = "AlternativeFont5", e3[e3.AlternativeFont6 = 16] = "AlternativeFont6", e3[e3.AlternativeFont7 = 17] = "AlternativeFont7", e3[e3.AlternativeFont8 = 18] = "AlternativeFont8", e3[e3.AlternativeFont9 = 19] = "AlternativeFont9", e3[e3.Fraktur = 20] = "Fraktur", e3[e3.DoubleUnderlined = 21] = "DoubleUnderlined", e3[e3.NormalIntensity = 22] = "NormalIntensity", e3[e3.NotItalicNotFraktur = 23] = "NotItalicNotFraktur", e3[e3.NotUnderlined = 24] = "NotUnderlined", e3[e3.NotBlinking = 25] = "NotBlinking", e3[e3.ProportionalSpacing = 26] = "ProportionalSpacing", e3[e3.NotReversed = 27] = "NotReversed", e3[e3.Reveal = 28] = "Reveal", e3[e3.NotCrossedOut = 29] = "NotCrossedOut", e3[e3.ForegroundBlack = 30] = "ForegroundBlack", e3[e3.ForegroundRed = 31] = "ForegroundRed", e3[e3.ForegroundGreen = 32] = "ForegroundGreen", e3[e3.ForegroundYellow = 33] = "ForegroundYellow", e3[e3.ForegroundBlue = 34] = "ForegroundBlue", e3[e3.ForegroundMagenta = 35] = "ForegroundMagenta", e3[e3.ForegroundCyan = 36] = "ForegroundCyan", e3[e3.ForegroundWhite = 37] = "ForegroundWhite", e3[e3.SetForeground = 38] = "SetForeground", e3[e3.DefaultForeground = 39] = "DefaultForeground", e3[e3.BackgroundBlack = 40] = "BackgroundBlack", e3[e3.BackgroundRed = 41] = "BackgroundRed", e3[e3.BackgroundGreen = 42] = "BackgroundGreen", e3[e3.BackgroundYellow = 43] = "BackgroundYellow", e3[e3.BackgroundBlue = 44] = "BackgroundBlue", e3[e3.BackgroundMagenta = 45] = "BackgroundMagenta", e3[e3.BackgroundCyan = 46] = "BackgroundCyan", e3[e3.BackgroundWhite = 47] = "BackgroundWhite", e3[e3.SetBackground = 48] = "SetBackground", e3[e3.DefaultBackground = 49] = "DefaultBackground", e3[e3.DisableProportionalSpacing = 50] = "DisableProportionalSpacing", e3[e3.Framed = 51] = "Framed", e3[e3.Encircled = 52] = "Encircled", e3[e3.Overlined = 53] = "Overlined", e3[e3.NotFramedNotEncircled = 54] = "NotFramedNotEncircled", e3[e3.NotOverlined = 55] = "NotOverlined", e3[e3.SetUnderline = 58] = "SetUnderline", e3[e3.DefaultUnderline = 59] = "DefaultUnderline", e3[e3.IdeogramUnderlineOrRightSideLine = 60] = "IdeogramUnderlineOrRightSideLine", e3[e3.IdeogramDoubleUnderlineOrDoubleRightSideLine = 61] = "IdeogramDoubleUnderlineOrDoubleRightSideLine", e3[e3.IdeogramOverlineOrLeftSideLine = 62] = "IdeogramOverlineOrLeftSideLine", e3[e3.IdeogramDoubleOverlineOrDoubleLeftSideLine = 63] = "IdeogramDoubleOverlineOrDoubleLeftSideLine", e3[e3.IdeogramStressMarking = 64] = "IdeogramStressMarking", e3[e3.NoIdeogramAttributes = 65] = "NoIdeogramAttributes", e3[e3.Superscript = 73] = "Superscript", e3[e3.Subscript = 74] = "Subscript", e3[e3.NotSuperscriptNotSubscript = 75] = "NotSuperscriptNotSubscript", e3[e3.ForegroundBrightBlack = 90] = "ForegroundBrightBlack", e3[e3.ForegroundBrightRed = 91] = "ForegroundBrightRed", e3[e3.ForegroundBrightGreen = 92] = "ForegroundBrightGreen", e3[e3.ForegroundBrightYellow = 93] = "ForegroundBrightYellow", e3[e3.ForegroundBrightBlue = 94] = "ForegroundBrightBlue", e3[e3.ForegroundBrightMagenta = 95] = "ForegroundBrightMagenta", e3[e3.ForegroundBrightCyan = 96] = "ForegroundBrightCyan", e3[e3.ForegroundBrightWhite = 97] = "ForegroundBrightWhite", e3[e3.BackgroundBrightBlack = 100] = "BackgroundBrightBlack", e3[e3.BackgroundBrightRed = 101] = "BackgroundBrightRed", e3[e3.BackgroundBrightGreen = 102] = "BackgroundBrightGreen", e3[e3.BackgroundBrightYellow = 103] = "BackgroundBrightYellow", e3[e3.BackgroundBrightBlue = 104] = "BackgroundBrightBlue", e3[e3.BackgroundBrightMagenta = 105] = "BackgroundBrightMagenta", e3[e3.BackgroundBrightCyan = 106] = "BackgroundBrightCyan", e3[e3.BackgroundBrightWhite = 107] = "BackgroundBrightWhite";
  }(a2 || (a2 = {})), function(e3) {
    e3[e3.Color256 = 5] = "Color256", e3[e3.ColorRGB = 2] = "ColorRGB";
  }(u2 || (u2 = {})), function(e3) {
    e3[e3.Black = 0] = "Black", e3[e3.Red = 1] = "Red", e3[e3.Green = 2] = "Green", e3[e3.Yellow = 3] = "Yellow", e3[e3.Blue = 4] = "Blue", e3[e3.Magenta = 5] = "Magenta", e3[e3.Cyan = 6] = "Cyan", e3[e3.White = 7] = "White", e3[e3.BrightBlack = 8] = "BrightBlack", e3[e3.BrightRed = 9] = "BrightRed", e3[e3.BrightGreen = 10] = "BrightGreen", e3[e3.BrightYellow = 11] = "BrightYellow", e3[e3.BrightBlue = 12] = "BrightBlue", e3[e3.BrightMagenta = 13] = "BrightMagenta", e3[e3.BrightCyan = 14] = "BrightCyan", e3[e3.BrightWhite = 15] = "BrightWhite";
  }(l2 || (l2 = {})), function(e3) {
    e3[e3.BufferingOutput = 0] = "BufferingOutput", e3[e3.ControlSequenceStarted = 1] = "ControlSequenceStarted", e3[e3.ParsingControlSequence = 2] = "ParsingControlSequence";
  }(g2 || (g2 = {}));
  class c2 {
    constructor() {
      __publicField(this, "_styles");
      __publicField(this, "_foregroundColor");
      __publicField(this, "_backgroundColor");
      __publicField(this, "_underlinedColor");
      __publicField(this, "_reversed");
      __publicField(this, "_font");
    }
    reset() {
      this._styles = void 0, this._foregroundColor = void 0, this._backgroundColor = void 0, this._underlinedColor = void 0, this._reversed = void 0, this._font = void 0;
    }
    copy() {
      const e3 = new c2();
      if (this._styles && this._styles.size) {
        const t3 = /* @__PURE__ */ new Set();
        this._styles.forEach((e4) => t3.add(e4)), e3._styles = t3;
      }
      return e3._foregroundColor = this._foregroundColor, e3._backgroundColor = this._backgroundColor, e3._underlinedColor = this._underlinedColor, e3._reversed = this._reversed, e3._font = this._font, e3;
    }
    setStyle(e3, ...t3) {
      if (this._styles) for (const e4 of t3) this._styles.delete(e4);
      else this._styles = /* @__PURE__ */ new Set();
      this._styles.add(e3);
    }
    deleteStyles(...e3) {
      if (this._styles) {
        for (const t3 of e3) this._styles.delete(t3);
        this._styles.size || (this._styles = void 0);
      }
    }
    setForegroundColor(e3) {
      this._reversed ? this._backgroundColor = e3 : this._foregroundColor = e3;
    }
    setBackgroundColor(e3) {
      this._reversed ? this._foregroundColor = e3 : this._backgroundColor = e3;
    }
    setReversed(e3) {
      e3 ? this._reversed || (this._reversed = true, this.reverseForegroundAndBackgroundColors()) : this._reversed && (this._reversed = void 0, this.reverseForegroundAndBackgroundColors());
    }
    setFont(e3) {
      this._font = e3;
    }
    static equivalent(e3, t3) {
      const r3 = (e4, t4) => t4 instanceof Set ? t4.size ? [...t4] : void 0 : t4;
      return e3 === t3 || JSON.stringify(e3, r3) === JSON.stringify(t3, r3);
    }
    get styles() {
      return this._styles ? [...this._styles] : void 0;
    }
    get foregroundColor() {
      if (this._backgroundColor && !this._foregroundColor)
        switch (this._backgroundColor) {
          case s2.Black:
          case s2.BrightBlack:
          case s2.Red:
          case s2.BrightRed:
            return s2.White;
          case s2.Green:
          case s2.BrightGreen:
          case s2.Yellow:
          case s2.BrightYellow:
          case s2.Blue:
          case s2.BrightBlue:
          case s2.Magenta:
          case s2.BrightMagenta:
          case s2.Cyan:
          case s2.BrightCyan:
          case s2.White:
          case s2.BrightWhite:
            return s2.Black;
        }
      return this._foregroundColor;
    }
    get backgroundColor() {
      return this._backgroundColor;
    }
    get underlinedColor() {
      return this._underlinedColor;
    }
    get font() {
      return this._font;
    }
    reverseForegroundAndBackgroundColors() {
      const e3 = this._foregroundColor;
      this._foregroundColor = this._backgroundColor, this._backgroundColor = e3;
    }
  }
  class d2 {
    constructor() {
      __publicField(this, "_id", n2());
      __publicField(this, "_outputRuns", []);
      __publicField(this, "_totalLength", 0);
    }
    clearEntireLine() {
      this._totalLength && (this._outputRuns = [new B2(" ".repeat(this._totalLength))]);
    }
    clearToEndOfLine(e3) {
      if ((e3 = Math.max(e3, 0)) >= this._totalLength) return;
      if (0 === e3) return void this.clearEntireLine();
      let t3, r3, n3 = 0;
      for (let o4 = 0; o4 < this._outputRuns.length; o4++) {
        const i4 = this._outputRuns[o4];
        if (e3 < n3 + i4.text.length) {
          t3 = i4, r3 = o4;
          break;
        }
        n3 += i4.text.length;
      }
      if (void 0 === t3 || void 0 === r3) return;
      const o3 = e3 - n3, i3 = " ".repeat(this._totalLength - e3), s3 = [];
      if (o3) {
        const e4 = t3.text.slice(0, o3);
        s3.push(new B2(e4, t3.sgrState)), s3.push(new B2(i3));
      } else s3.push(new B2(i3));
      this.outputRuns.splice(r3, this._outputRuns.length - r3, ...s3);
    }
    clearToBeginningOfLine(e3) {
      if (0 === (e3 = Math.max(e3, 0))) return;
      if (e3 >= this._totalLength) return void this.clearEntireLine();
      let t3, r3, n3 = 0;
      for (let o4 = this._outputRuns.length - 1; o4 >= 0; o4--) {
        const i4 = this._outputRuns[o4];
        if (e3 >= n3 - i4.text.length) {
          t3 = i4, r3 = o4;
          break;
        }
        n3 -= i4.text.length;
      }
      if (void 0 === t3 || void 0 === r3) return;
      const o3 = n3 - e3, i3 = " ".repeat(e3), s3 = [new B2(i3)];
      if (o3) {
        const e4 = t3.text.slice(-o3);
        s3.push(new B2(e4, t3.sgrState));
      }
      this.outputRuns.splice(0, this._outputRuns.length - r3, ...s3);
    }
    insert(e3, t3, r3) {
      if (!e3.length) return;
      if (t3 === this._totalLength) {
        if (this._totalLength += e3.length, this._outputRuns.length) {
          const t4 = this._outputRuns[this._outputRuns.length - 1];
          if (c2.equivalent(t4.sgrState, r3)) return void t4.appendText(e3);
        }
        return void this._outputRuns.push(new B2(e3, r3));
      }
      if (t3 > this._totalLength) {
        const n4 = " ".repeat(t3 - this._totalLength);
        if (this._totalLength += n4.length + e3.length, !r3 && this._outputRuns.length) {
          const t4 = this._outputRuns[this._outputRuns.length - 1];
          if (!t4.sgrState) return t4.appendText(n4), void t4.appendText(e3);
        }
        r3 ? (this._outputRuns.push(new B2(n4)), this._outputRuns.push(new B2(e3, r3))) : this._outputRuns.push(new B2(n4 + e3));
      }
      let n3, o3 = 0;
      for (let e4 = 0; e4 < this._outputRuns.length; e4++) {
        const r4 = this._outputRuns[e4];
        if (t3 < o3 + r4.text.length) {
          n3 = e4;
          break;
        }
        o3 += r4.text.length;
      }
      if (void 0 === n3) return void this._outputRuns.push(new B2(e3, r3));
      if (t3 + e3.length >= this._totalLength) {
        const i4 = t3 - o3, s4 = [];
        if (i4) {
          const t4 = this._outputRuns[n3], o4 = t4.text.slice(0, i4);
          c2.equivalent(t4.sgrState, r3) ? s4.push(new B2(o4 + e3, r3)) : (s4.push(new B2(o4, t4.sgrState)), s4.push(new B2(e3, r3)));
        } else s4.push(new B2(e3, r3));
        return this.outputRuns.splice(n3, 1, ...s4), void (this._totalLength = o3 + i4 + e3.length);
      }
      let i3, s3 = this._totalLength;
      for (let r4 = this._outputRuns.length - 1; r4 >= 0; r4--) {
        const n4 = this._outputRuns[r4];
        if (t3 + e3.length > s3 - n4.text.length) {
          i3 = r4;
          break;
        }
        s3 -= n4.text.length;
      }
      if (void 0 === i3) return void this._outputRuns.push(new B2(e3, r3));
      const a3 = [], u3 = t3 - o3;
      if (u3) {
        const e4 = this._outputRuns[n3], t4 = e4.text.slice(0, u3);
        a3.push(new B2(t4, e4.sgrState));
      }
      a3.push(new B2(e3, r3));
      const l3 = s3 - (t3 + e3.length);
      if (l3) {
        const e4 = this._outputRuns[i3], t4 = e4.text.slice(-l3);
        a3.push(new B2(t4, e4.sgrState));
      }
      this._outputRuns.splice(n3, i3 - n3 + 1, ...a3), this._outputRuns.length > 1 && (this._outputRuns = B2.optimizeOutputRuns(this._outputRuns)), this._totalLength = this._outputRuns.reduce(
        (e4, t4) => e4 + t4.text.length,
        0
      );
    }
    get id() {
      return this._id;
    }
    get outputRuns() {
      return this._outputRuns;
    }
  }
  class B2 {
    constructor(e3, t3) {
      __publicField(this, "_id", n2());
      __publicField(this, "_sgrState");
      __publicField(this, "_text");
      this._sgrState = t3, this._text = e3;
    }
    get sgrState() {
      return this._sgrState;
    }
    static optimizeOutputRuns(e3) {
      const t3 = [e3[0]];
      for (let r3 = 1, n3 = 0; r3 < e3.length; r3++) {
        const o3 = e3[r3];
        c2.equivalent(t3[n3].sgrState, o3.sgrState) ? t3[n3]._text += o3.text : t3[++n3] = o3;
      }
      return t3;
    }
    appendText(e3) {
      this._text += e3;
    }
    get id() {
      return this._id;
    }
    get format() {
      return this._sgrState;
    }
    get text() {
      return this._text;
    }
  }
  const k2 = (e3, t3, r3) => {
    const n3 = p2(e3, t3);
    return Math.max(n3, r3);
  }, p2 = (e3, t3) => {
    const r3 = parseInt(e3);
    return Number.isNaN(r3) ? t3 : r3;
  }, _2 = (e3) => {
    const t3 = Math.max(Math.min(255, e3), 0).toString(16);
    return 2 === t3.length ? t3 : "0" + t3;
  };
}(0, r.exports), void 0 !== t && (e.exports = t);
var n = r.exports;
const ANSIDisplay = ({ output }) => {
  const ansiOutput = new n.ANSIOutput();
  ansiOutput.processOutput(output);
  let firstOutput = false;
  return m$1`<div class="ansi-display">
    ${ansiOutput.outputLines.map((line2) => {
    firstOutput = firstOutput || !!line2.outputRuns.length;
    return m$1`<div class="ansi-display-line">
        ${!line2.outputRuns.length ? firstOutput ? m$1`<br />` : null : line2.outputRuns.map(
      (outputRun) => m$1`<${OutputRun}
                  key=${outputRun.id}
                  outputRun=${outputRun}
                />`
    )}
      </div>`;
  })}
  </div>`;
};
const kForeground = 0;
const kBackground = 1;
const OutputRun = ({ outputRun }) => {
  const computeStyles2 = (styles) => {
    let cssProperties = {};
    if (styles) {
      styles.forEach((style) => {
        switch (style) {
          case n.ANSIStyle.Bold:
            cssProperties = { ...cssProperties, ...{ fontWeight: "bold" } };
            break;
          case n.ANSIStyle.Dim:
            cssProperties = { ...cssProperties, ...{ fontWeight: "lighter" } };
            break;
          case n.ANSIStyle.Italic:
            cssProperties = { ...cssProperties, ...{ fontStyle: "italic" } };
            break;
          case n.ANSIStyle.Underlined:
            cssProperties = {
              ...cssProperties,
              ...{
                textDecorationLine: "underline",
                textDecorationStyle: "solid"
              }
            };
            break;
          case n.ANSIStyle.SlowBlink:
            cssProperties = {
              ...cssProperties,
              ...{ animation: "ansi-display-run-blink 1s linear infinite" }
            };
            break;
          case n.ANSIStyle.RapidBlink:
            cssProperties = {
              ...cssProperties,
              ...{ animation: "ansi-display-run-blink 0.5s linear infinite" }
            };
            break;
          case n.ANSIStyle.Hidden:
            cssProperties = { ...cssProperties, ...{ visibility: "hidden" } };
            break;
          case n.ANSIStyle.CrossedOut:
            cssProperties = {
              ...cssProperties,
              ...{
                textDecorationLine: "line-through",
                textDecorationStyle: "solid"
              }
            };
            break;
          case n.ANSIStyle.DoubleUnderlined:
            cssProperties = {
              ...cssProperties,
              ...{
                textDecorationLine: "underline",
                textDecorationStyle: "double"
              }
            };
            break;
        }
      });
    }
    return cssProperties;
  };
  const computeForegroundBackgroundColor = (colorType, color) => {
    switch (color) {
      case void 0:
        return {};
      case n.ANSIColor.Black:
      case n.ANSIColor.Red:
      case n.ANSIColor.Green:
      case n.ANSIColor.Yellow:
      case n.ANSIColor.Blue:
      case n.ANSIColor.Magenta:
      case n.ANSIColor.Cyan:
      case n.ANSIColor.White:
      case n.ANSIColor.BrightBlack:
      case n.ANSIColor.BrightRed:
      case n.ANSIColor.BrightGreen:
      case n.ANSIColor.BrightYellow:
      case n.ANSIColor.BrightBlue:
      case n.ANSIColor.BrightMagenta:
      case n.ANSIColor.BrightCyan:
      case n.ANSIColor.BrightWhite:
        if (colorType === kForeground) {
          return { color: `var(--${color})` };
        } else {
          return { background: `var(--${color})` };
        }
      default:
        if (colorType === kForeground) {
          return { color };
        } else {
          return { background: color };
        }
    }
  };
  const computeCSSProperties = (outputRun2) => {
    return !outputRun2.format ? {} : {
      ...computeStyles2(outputRun2.format.styles),
      ...computeForegroundBackgroundColor(
        kForeground,
        outputRun2.format.foregroundColor
      ),
      ...computeForegroundBackgroundColor(
        kBackground,
        outputRun2.format.backgroundColor
      )
    };
  };
  return m$1`<span style=${computeCSSProperties(outputRun)}
    >${outputRun.text}</span
  >`;
};
var showdown = { exports: {} };
(function(module) {
  (function() {
    function getDefaultOpts(simple) {
      var defaultOptions = {
        omitExtraWLInCodeBlocks: {
          defaultValue: false,
          describe: "Omit the default extra whiteline added to code blocks",
          type: "boolean"
        },
        noHeaderId: {
          defaultValue: false,
          describe: "Turn on/off generated header id",
          type: "boolean"
        },
        prefixHeaderId: {
          defaultValue: false,
          describe: "Add a prefix to the generated header ids. Passing a string will prefix that string to the header id. Setting to true will add a generic 'section-' prefix",
          type: "string"
        },
        rawPrefixHeaderId: {
          defaultValue: false,
          describe: 'Setting this option to true will prevent showdown from modifying the prefix. This might result in malformed IDs (if, for instance, the " char is used in the prefix)',
          type: "boolean"
        },
        ghCompatibleHeaderId: {
          defaultValue: false,
          describe: "Generate header ids compatible with github style (spaces are replaced with dashes, a bunch of non alphanumeric chars are removed)",
          type: "boolean"
        },
        rawHeaderId: {
          defaultValue: false,
          describe: `Remove only spaces, ' and " from generated header ids (including prefixes), replacing them with dashes (-). WARNING: This might result in malformed ids`,
          type: "boolean"
        },
        headerLevelStart: {
          defaultValue: false,
          describe: "The header blocks level start",
          type: "integer"
        },
        parseImgDimensions: {
          defaultValue: false,
          describe: "Turn on/off image dimension parsing",
          type: "boolean"
        },
        simplifiedAutoLink: {
          defaultValue: false,
          describe: "Turn on/off GFM autolink style",
          type: "boolean"
        },
        excludeTrailingPunctuationFromURLs: {
          defaultValue: false,
          describe: "Excludes trailing punctuation from links generated with autoLinking",
          type: "boolean"
        },
        literalMidWordUnderscores: {
          defaultValue: false,
          describe: "Parse midword underscores as literal underscores",
          type: "boolean"
        },
        literalMidWordAsterisks: {
          defaultValue: false,
          describe: "Parse midword asterisks as literal asterisks",
          type: "boolean"
        },
        strikethrough: {
          defaultValue: false,
          describe: "Turn on/off strikethrough support",
          type: "boolean"
        },
        tables: {
          defaultValue: false,
          describe: "Turn on/off tables support",
          type: "boolean"
        },
        tablesHeaderId: {
          defaultValue: false,
          describe: "Add an id to table headers",
          type: "boolean"
        },
        ghCodeBlocks: {
          defaultValue: true,
          describe: "Turn on/off GFM fenced code blocks support",
          type: "boolean"
        },
        tasklists: {
          defaultValue: false,
          describe: "Turn on/off GFM tasklist support",
          type: "boolean"
        },
        smoothLivePreview: {
          defaultValue: false,
          describe: "Prevents weird effects in live previews due to incomplete input",
          type: "boolean"
        },
        smartIndentationFix: {
          defaultValue: false,
          describe: "Tries to smartly fix indentation in es6 strings",
          type: "boolean"
        },
        disableForced4SpacesIndentedSublists: {
          defaultValue: false,
          describe: "Disables the requirement of indenting nested sublists by 4 spaces",
          type: "boolean"
        },
        simpleLineBreaks: {
          defaultValue: false,
          describe: "Parses simple line breaks as <br> (GFM Style)",
          type: "boolean"
        },
        requireSpaceBeforeHeadingText: {
          defaultValue: false,
          describe: "Makes adding a space between `#` and the header text mandatory (GFM Style)",
          type: "boolean"
        },
        ghMentions: {
          defaultValue: false,
          describe: "Enables github @mentions",
          type: "boolean"
        },
        ghMentionsLink: {
          defaultValue: "https://github.com/{u}",
          describe: "Changes the link generated by @mentions. Only applies if ghMentions option is enabled.",
          type: "string"
        },
        encodeEmails: {
          defaultValue: true,
          describe: "Encode e-mail addresses through the use of Character Entities, transforming ASCII e-mail addresses into its equivalent decimal entities",
          type: "boolean"
        },
        openLinksInNewWindow: {
          defaultValue: false,
          describe: "Open all links in new windows",
          type: "boolean"
        },
        backslashEscapesHTMLTags: {
          defaultValue: false,
          describe: "Support for HTML Tag escaping. ex: <div>foo</div>",
          type: "boolean"
        },
        emoji: {
          defaultValue: false,
          describe: "Enable emoji support. Ex: `this is a :smile: emoji`",
          type: "boolean"
        },
        underline: {
          defaultValue: false,
          describe: "Enable support for underline. Syntax is double or triple underscores: `__underline word__`. With this option enabled, underscores no longer parses into `<em>` and `<strong>`",
          type: "boolean"
        },
        ellipsis: {
          defaultValue: true,
          describe: "Replaces three dots with the ellipsis unicode character",
          type: "boolean"
        },
        completeHTMLDocument: {
          defaultValue: false,
          describe: "Outputs a complete html document, including `<html>`, `<head>` and `<body>` tags",
          type: "boolean"
        },
        metadata: {
          defaultValue: false,
          describe: "Enable support for document metadata (defined at the top of the document between `«««` and `»»»` or between `---` and `---`).",
          type: "boolean"
        },
        splitAdjacentBlockquotes: {
          defaultValue: false,
          describe: "Split adjacent blockquote blocks",
          type: "boolean"
        }
      };
      if (simple === false) {
        return JSON.parse(JSON.stringify(defaultOptions));
      }
      var ret = {};
      for (var opt in defaultOptions) {
        if (defaultOptions.hasOwnProperty(opt)) {
          ret[opt] = defaultOptions[opt].defaultValue;
        }
      }
      return ret;
    }
    function allOptionsOn() {
      var options = getDefaultOpts(true), ret = {};
      for (var opt in options) {
        if (options.hasOwnProperty(opt)) {
          ret[opt] = true;
        }
      }
      return ret;
    }
    var showdown2 = {}, parsers = {}, extensions = {}, globalOptions = getDefaultOpts(true), setFlavor = "vanilla", flavor = {
      github: {
        omitExtraWLInCodeBlocks: true,
        simplifiedAutoLink: true,
        excludeTrailingPunctuationFromURLs: true,
        literalMidWordUnderscores: true,
        strikethrough: true,
        tables: true,
        tablesHeaderId: true,
        ghCodeBlocks: true,
        tasklists: true,
        disableForced4SpacesIndentedSublists: true,
        simpleLineBreaks: true,
        requireSpaceBeforeHeadingText: true,
        ghCompatibleHeaderId: true,
        ghMentions: true,
        backslashEscapesHTMLTags: true,
        emoji: true,
        splitAdjacentBlockquotes: true
      },
      original: {
        noHeaderId: true,
        ghCodeBlocks: false
      },
      ghost: {
        omitExtraWLInCodeBlocks: true,
        parseImgDimensions: true,
        simplifiedAutoLink: true,
        excludeTrailingPunctuationFromURLs: true,
        literalMidWordUnderscores: true,
        strikethrough: true,
        tables: true,
        tablesHeaderId: true,
        ghCodeBlocks: true,
        tasklists: true,
        smoothLivePreview: true,
        simpleLineBreaks: true,
        requireSpaceBeforeHeadingText: true,
        ghMentions: false,
        encodeEmails: true
      },
      vanilla: getDefaultOpts(true),
      allOn: allOptionsOn()
    };
    showdown2.helper = {};
    showdown2.extensions = {};
    showdown2.setOption = function(key2, value) {
      globalOptions[key2] = value;
      return this;
    };
    showdown2.getOption = function(key2) {
      return globalOptions[key2];
    };
    showdown2.getOptions = function() {
      return globalOptions;
    };
    showdown2.resetOptions = function() {
      globalOptions = getDefaultOpts(true);
    };
    showdown2.setFlavor = function(name) {
      if (!flavor.hasOwnProperty(name)) {
        throw Error(name + " flavor was not found");
      }
      showdown2.resetOptions();
      var preset = flavor[name];
      setFlavor = name;
      for (var option in preset) {
        if (preset.hasOwnProperty(option)) {
          globalOptions[option] = preset[option];
        }
      }
    };
    showdown2.getFlavor = function() {
      return setFlavor;
    };
    showdown2.getFlavorOptions = function(name) {
      if (flavor.hasOwnProperty(name)) {
        return flavor[name];
      }
    };
    showdown2.getDefaultOptions = function(simple) {
      return getDefaultOpts(simple);
    };
    showdown2.subParser = function(name, func) {
      if (showdown2.helper.isString(name)) {
        if (typeof func !== "undefined") {
          parsers[name] = func;
        } else {
          if (parsers.hasOwnProperty(name)) {
            return parsers[name];
          } else {
            throw Error("SubParser named " + name + " not registered!");
          }
        }
      }
    };
    showdown2.extension = function(name, ext) {
      if (!showdown2.helper.isString(name)) {
        throw Error("Extension 'name' must be a string");
      }
      name = showdown2.helper.stdExtName(name);
      if (showdown2.helper.isUndefined(ext)) {
        if (!extensions.hasOwnProperty(name)) {
          throw Error("Extension named " + name + " is not registered!");
        }
        return extensions[name];
      } else {
        if (typeof ext === "function") {
          ext = ext();
        }
        if (!showdown2.helper.isArray(ext)) {
          ext = [ext];
        }
        var validExtension = validate2(ext, name);
        if (validExtension.valid) {
          extensions[name] = ext;
        } else {
          throw Error(validExtension.error);
        }
      }
    };
    showdown2.getAllExtensions = function() {
      return extensions;
    };
    showdown2.removeExtension = function(name) {
      delete extensions[name];
    };
    showdown2.resetExtensions = function() {
      extensions = {};
    };
    function validate2(extension, name) {
      var errMsg = name ? "Error in " + name + " extension->" : "Error in unnamed extension", ret = {
        valid: true,
        error: ""
      };
      if (!showdown2.helper.isArray(extension)) {
        extension = [extension];
      }
      for (var i2 = 0; i2 < extension.length; ++i2) {
        var baseMsg = errMsg + " sub-extension " + i2 + ": ", ext = extension[i2];
        if (typeof ext !== "object") {
          ret.valid = false;
          ret.error = baseMsg + "must be an object, but " + typeof ext + " given";
          return ret;
        }
        if (!showdown2.helper.isString(ext.type)) {
          ret.valid = false;
          ret.error = baseMsg + 'property "type" must be a string, but ' + typeof ext.type + " given";
          return ret;
        }
        var type = ext.type = ext.type.toLowerCase();
        if (type === "language") {
          type = ext.type = "lang";
        }
        if (type === "html") {
          type = ext.type = "output";
        }
        if (type !== "lang" && type !== "output" && type !== "listener") {
          ret.valid = false;
          ret.error = baseMsg + "type " + type + ' is not recognized. Valid values: "lang/language", "output/html" or "listener"';
          return ret;
        }
        if (type === "listener") {
          if (showdown2.helper.isUndefined(ext.listeners)) {
            ret.valid = false;
            ret.error = baseMsg + '. Extensions of type "listener" must have a property called "listeners"';
            return ret;
          }
        } else {
          if (showdown2.helper.isUndefined(ext.filter) && showdown2.helper.isUndefined(ext.regex)) {
            ret.valid = false;
            ret.error = baseMsg + type + ' extensions must define either a "regex" property or a "filter" method';
            return ret;
          }
        }
        if (ext.listeners) {
          if (typeof ext.listeners !== "object") {
            ret.valid = false;
            ret.error = baseMsg + '"listeners" property must be an object but ' + typeof ext.listeners + " given";
            return ret;
          }
          for (var ln in ext.listeners) {
            if (ext.listeners.hasOwnProperty(ln)) {
              if (typeof ext.listeners[ln] !== "function") {
                ret.valid = false;
                ret.error = baseMsg + '"listeners" property must be an hash of [event name]: [callback]. listeners.' + ln + " must be a function but " + typeof ext.listeners[ln] + " given";
                return ret;
              }
            }
          }
        }
        if (ext.filter) {
          if (typeof ext.filter !== "function") {
            ret.valid = false;
            ret.error = baseMsg + '"filter" must be a function, but ' + typeof ext.filter + " given";
            return ret;
          }
        } else if (ext.regex) {
          if (showdown2.helper.isString(ext.regex)) {
            ext.regex = new RegExp(ext.regex, "g");
          }
          if (!(ext.regex instanceof RegExp)) {
            ret.valid = false;
            ret.error = baseMsg + '"regex" property must either be a string or a RegExp object, but ' + typeof ext.regex + " given";
            return ret;
          }
          if (showdown2.helper.isUndefined(ext.replace)) {
            ret.valid = false;
            ret.error = baseMsg + '"regex" extensions must implement a replace string or function';
            return ret;
          }
        }
      }
      return ret;
    }
    showdown2.validateExtension = function(ext) {
      var validateExtension = validate2(ext, null);
      if (!validateExtension.valid) {
        console.warn(validateExtension.error);
        return false;
      }
      return true;
    };
    if (!showdown2.hasOwnProperty("helper")) {
      showdown2.helper = {};
    }
    showdown2.helper.isString = function(a2) {
      return typeof a2 === "string" || a2 instanceof String;
    };
    showdown2.helper.isFunction = function(a2) {
      var getType = {};
      return a2 && getType.toString.call(a2) === "[object Function]";
    };
    showdown2.helper.isArray = function(a2) {
      return Array.isArray(a2);
    };
    showdown2.helper.isUndefined = function(value) {
      return typeof value === "undefined";
    };
    showdown2.helper.forEach = function(obj, callback) {
      if (showdown2.helper.isUndefined(obj)) {
        throw new Error("obj param is required");
      }
      if (showdown2.helper.isUndefined(callback)) {
        throw new Error("callback param is required");
      }
      if (!showdown2.helper.isFunction(callback)) {
        throw new Error("callback param must be a function/closure");
      }
      if (typeof obj.forEach === "function") {
        obj.forEach(callback);
      } else if (showdown2.helper.isArray(obj)) {
        for (var i2 = 0; i2 < obj.length; i2++) {
          callback(obj[i2], i2, obj);
        }
      } else if (typeof obj === "object") {
        for (var prop in obj) {
          if (obj.hasOwnProperty(prop)) {
            callback(obj[prop], prop, obj);
          }
        }
      } else {
        throw new Error("obj does not seem to be an array or an iterable object");
      }
    };
    showdown2.helper.stdExtName = function(s2) {
      return s2.replace(/[_?*+\/\\.^-]/g, "").replace(/\s/g, "").toLowerCase();
    };
    function escapeCharactersCallback(wholeMatch, m1) {
      var charCodeToEscape = m1.charCodeAt(0);
      return "¨E" + charCodeToEscape + "E";
    }
    showdown2.helper.escapeCharactersCallback = escapeCharactersCallback;
    showdown2.helper.escapeCharacters = function(text, charsToEscape, afterBackslash) {
      var regexString = "([" + charsToEscape.replace(/([\[\]\\])/g, "\\$1") + "])";
      if (afterBackslash) {
        regexString = "\\\\" + regexString;
      }
      var regex = new RegExp(regexString, "g");
      text = text.replace(regex, escapeCharactersCallback);
      return text;
    };
    showdown2.helper.unescapeHTMLEntities = function(txt) {
      return txt.replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
    };
    var rgxFindMatchPos = function(str, left2, right2, flags) {
      var f2 = flags || "", g2 = f2.indexOf("g") > -1, x2 = new RegExp(left2 + "|" + right2, "g" + f2.replace(/g/g, "")), l2 = new RegExp(left2, f2.replace(/g/g, "")), pos2 = [], t2, s2, m2, start2, end2;
      do {
        t2 = 0;
        while (m2 = x2.exec(str)) {
          if (l2.test(m2[0])) {
            if (!t2++) {
              s2 = x2.lastIndex;
              start2 = s2 - m2[0].length;
            }
          } else if (t2) {
            if (!--t2) {
              end2 = m2.index + m2[0].length;
              var obj = {
                left: { start: start2, end: s2 },
                match: { start: s2, end: m2.index },
                right: { start: m2.index, end: end2 },
                wholeMatch: { start: start2, end: end2 }
              };
              pos2.push(obj);
              if (!g2) {
                return pos2;
              }
            }
          }
        }
      } while (t2 && (x2.lastIndex = s2));
      return pos2;
    };
    showdown2.helper.matchRecursiveRegExp = function(str, left2, right2, flags) {
      var matchPos = rgxFindMatchPos(str, left2, right2, flags), results = [];
      for (var i2 = 0; i2 < matchPos.length; ++i2) {
        results.push([
          str.slice(matchPos[i2].wholeMatch.start, matchPos[i2].wholeMatch.end),
          str.slice(matchPos[i2].match.start, matchPos[i2].match.end),
          str.slice(matchPos[i2].left.start, matchPos[i2].left.end),
          str.slice(matchPos[i2].right.start, matchPos[i2].right.end)
        ]);
      }
      return results;
    };
    showdown2.helper.replaceRecursiveRegExp = function(str, replacement, left2, right2, flags) {
      if (!showdown2.helper.isFunction(replacement)) {
        var repStr = replacement;
        replacement = function() {
          return repStr;
        };
      }
      var matchPos = rgxFindMatchPos(str, left2, right2, flags), finalStr = str, lng = matchPos.length;
      if (lng > 0) {
        var bits = [];
        if (matchPos[0].wholeMatch.start !== 0) {
          bits.push(str.slice(0, matchPos[0].wholeMatch.start));
        }
        for (var i2 = 0; i2 < lng; ++i2) {
          bits.push(
            replacement(
              str.slice(matchPos[i2].wholeMatch.start, matchPos[i2].wholeMatch.end),
              str.slice(matchPos[i2].match.start, matchPos[i2].match.end),
              str.slice(matchPos[i2].left.start, matchPos[i2].left.end),
              str.slice(matchPos[i2].right.start, matchPos[i2].right.end)
            )
          );
          if (i2 < lng - 1) {
            bits.push(str.slice(matchPos[i2].wholeMatch.end, matchPos[i2 + 1].wholeMatch.start));
          }
        }
        if (matchPos[lng - 1].wholeMatch.end < str.length) {
          bits.push(str.slice(matchPos[lng - 1].wholeMatch.end));
        }
        finalStr = bits.join("");
      }
      return finalStr;
    };
    showdown2.helper.regexIndexOf = function(str, regex, fromIndex) {
      if (!showdown2.helper.isString(str)) {
        throw "InvalidArgumentError: first parameter of showdown.helper.regexIndexOf function must be a string";
      }
      if (regex instanceof RegExp === false) {
        throw "InvalidArgumentError: second parameter of showdown.helper.regexIndexOf function must be an instance of RegExp";
      }
      var indexOf = str.substring(fromIndex || 0).search(regex);
      return indexOf >= 0 ? indexOf + (fromIndex || 0) : indexOf;
    };
    showdown2.helper.splitAtIndex = function(str, index) {
      if (!showdown2.helper.isString(str)) {
        throw "InvalidArgumentError: first parameter of showdown.helper.regexIndexOf function must be a string";
      }
      return [str.substring(0, index), str.substring(index)];
    };
    showdown2.helper.encodeEmailAddress = function(mail) {
      var encode = [
        function(ch) {
          return "&#" + ch.charCodeAt(0) + ";";
        },
        function(ch) {
          return "&#x" + ch.charCodeAt(0).toString(16) + ";";
        },
        function(ch) {
          return ch;
        }
      ];
      mail = mail.replace(/./g, function(ch) {
        if (ch === "@") {
          ch = encode[Math.floor(Math.random() * 2)](ch);
        } else {
          var r2 = Math.random();
          ch = r2 > 0.9 ? encode[2](ch) : r2 > 0.45 ? encode[1](ch) : encode[0](ch);
        }
        return ch;
      });
      return mail;
    };
    showdown2.helper.padEnd = function padEnd(str, targetLength, padString) {
      targetLength = targetLength >> 0;
      padString = String(padString || " ");
      if (str.length > targetLength) {
        return String(str);
      } else {
        targetLength = targetLength - str.length;
        if (targetLength > padString.length) {
          padString += padString.repeat(targetLength / padString.length);
        }
        return String(str) + padString.slice(0, targetLength);
      }
    };
    if (typeof console === "undefined") {
      console = {
        warn: function(msg) {
          alert(msg);
        },
        log: function(msg) {
          alert(msg);
        },
        error: function(msg) {
          throw msg;
        }
      };
    }
    showdown2.helper.regexes = {
      asteriskDashAndColon: /([*_:~])/g
    };
    showdown2.helper.emojis = {
      "+1": "👍",
      "-1": "👎",
      "100": "💯",
      "1234": "🔢",
      "1st_place_medal": "🥇",
      "2nd_place_medal": "🥈",
      "3rd_place_medal": "🥉",
      "8ball": "🎱",
      "a": "🅰️",
      "ab": "🆎",
      "abc": "🔤",
      "abcd": "🔡",
      "accept": "🉑",
      "aerial_tramway": "🚡",
      "airplane": "✈️",
      "alarm_clock": "⏰",
      "alembic": "⚗️",
      "alien": "👽",
      "ambulance": "🚑",
      "amphora": "🏺",
      "anchor": "⚓️",
      "angel": "👼",
      "anger": "💢",
      "angry": "😠",
      "anguished": "😧",
      "ant": "🐜",
      "apple": "🍎",
      "aquarius": "♒️",
      "aries": "♈️",
      "arrow_backward": "◀️",
      "arrow_double_down": "⏬",
      "arrow_double_up": "⏫",
      "arrow_down": "⬇️",
      "arrow_down_small": "🔽",
      "arrow_forward": "▶️",
      "arrow_heading_down": "⤵️",
      "arrow_heading_up": "⤴️",
      "arrow_left": "⬅️",
      "arrow_lower_left": "↙️",
      "arrow_lower_right": "↘️",
      "arrow_right": "➡️",
      "arrow_right_hook": "↪️",
      "arrow_up": "⬆️",
      "arrow_up_down": "↕️",
      "arrow_up_small": "🔼",
      "arrow_upper_left": "↖️",
      "arrow_upper_right": "↗️",
      "arrows_clockwise": "🔃",
      "arrows_counterclockwise": "🔄",
      "art": "🎨",
      "articulated_lorry": "🚛",
      "artificial_satellite": "🛰",
      "astonished": "😲",
      "athletic_shoe": "👟",
      "atm": "🏧",
      "atom_symbol": "⚛️",
      "avocado": "🥑",
      "b": "🅱️",
      "baby": "👶",
      "baby_bottle": "🍼",
      "baby_chick": "🐤",
      "baby_symbol": "🚼",
      "back": "🔙",
      "bacon": "🥓",
      "badminton": "🏸",
      "baggage_claim": "🛄",
      "baguette_bread": "🥖",
      "balance_scale": "⚖️",
      "balloon": "🎈",
      "ballot_box": "🗳",
      "ballot_box_with_check": "☑️",
      "bamboo": "🎍",
      "banana": "🍌",
      "bangbang": "‼️",
      "bank": "🏦",
      "bar_chart": "📊",
      "barber": "💈",
      "baseball": "⚾️",
      "basketball": "🏀",
      "basketball_man": "⛹️",
      "basketball_woman": "⛹️&zwj;♀️",
      "bat": "🦇",
      "bath": "🛀",
      "bathtub": "🛁",
      "battery": "🔋",
      "beach_umbrella": "🏖",
      "bear": "🐻",
      "bed": "🛏",
      "bee": "🐝",
      "beer": "🍺",
      "beers": "🍻",
      "beetle": "🐞",
      "beginner": "🔰",
      "bell": "🔔",
      "bellhop_bell": "🛎",
      "bento": "🍱",
      "biking_man": "🚴",
      "bike": "🚲",
      "biking_woman": "🚴&zwj;♀️",
      "bikini": "👙",
      "biohazard": "☣️",
      "bird": "🐦",
      "birthday": "🎂",
      "black_circle": "⚫️",
      "black_flag": "🏴",
      "black_heart": "🖤",
      "black_joker": "🃏",
      "black_large_square": "⬛️",
      "black_medium_small_square": "◾️",
      "black_medium_square": "◼️",
      "black_nib": "✒️",
      "black_small_square": "▪️",
      "black_square_button": "🔲",
      "blonde_man": "👱",
      "blonde_woman": "👱&zwj;♀️",
      "blossom": "🌼",
      "blowfish": "🐡",
      "blue_book": "📘",
      "blue_car": "🚙",
      "blue_heart": "💙",
      "blush": "😊",
      "boar": "🐗",
      "boat": "⛵️",
      "bomb": "💣",
      "book": "📖",
      "bookmark": "🔖",
      "bookmark_tabs": "📑",
      "books": "📚",
      "boom": "💥",
      "boot": "👢",
      "bouquet": "💐",
      "bowing_man": "🙇",
      "bow_and_arrow": "🏹",
      "bowing_woman": "🙇&zwj;♀️",
      "bowling": "🎳",
      "boxing_glove": "🥊",
      "boy": "👦",
      "bread": "🍞",
      "bride_with_veil": "👰",
      "bridge_at_night": "🌉",
      "briefcase": "💼",
      "broken_heart": "💔",
      "bug": "🐛",
      "building_construction": "🏗",
      "bulb": "💡",
      "bullettrain_front": "🚅",
      "bullettrain_side": "🚄",
      "burrito": "🌯",
      "bus": "🚌",
      "business_suit_levitating": "🕴",
      "busstop": "🚏",
      "bust_in_silhouette": "👤",
      "busts_in_silhouette": "👥",
      "butterfly": "🦋",
      "cactus": "🌵",
      "cake": "🍰",
      "calendar": "📆",
      "call_me_hand": "🤙",
      "calling": "📲",
      "camel": "🐫",
      "camera": "📷",
      "camera_flash": "📸",
      "camping": "🏕",
      "cancer": "♋️",
      "candle": "🕯",
      "candy": "🍬",
      "canoe": "🛶",
      "capital_abcd": "🔠",
      "capricorn": "♑️",
      "car": "🚗",
      "card_file_box": "🗃",
      "card_index": "📇",
      "card_index_dividers": "🗂",
      "carousel_horse": "🎠",
      "carrot": "🥕",
      "cat": "🐱",
      "cat2": "🐈",
      "cd": "💿",
      "chains": "⛓",
      "champagne": "🍾",
      "chart": "💹",
      "chart_with_downwards_trend": "📉",
      "chart_with_upwards_trend": "📈",
      "checkered_flag": "🏁",
      "cheese": "🧀",
      "cherries": "🍒",
      "cherry_blossom": "🌸",
      "chestnut": "🌰",
      "chicken": "🐔",
      "children_crossing": "🚸",
      "chipmunk": "🐿",
      "chocolate_bar": "🍫",
      "christmas_tree": "🎄",
      "church": "⛪️",
      "cinema": "🎦",
      "circus_tent": "🎪",
      "city_sunrise": "🌇",
      "city_sunset": "🌆",
      "cityscape": "🏙",
      "cl": "🆑",
      "clamp": "🗜",
      "clap": "👏",
      "clapper": "🎬",
      "classical_building": "🏛",
      "clinking_glasses": "🥂",
      "clipboard": "📋",
      "clock1": "🕐",
      "clock10": "🕙",
      "clock1030": "🕥",
      "clock11": "🕚",
      "clock1130": "🕦",
      "clock12": "🕛",
      "clock1230": "🕧",
      "clock130": "🕜",
      "clock2": "🕑",
      "clock230": "🕝",
      "clock3": "🕒",
      "clock330": "🕞",
      "clock4": "🕓",
      "clock430": "🕟",
      "clock5": "🕔",
      "clock530": "🕠",
      "clock6": "🕕",
      "clock630": "🕡",
      "clock7": "🕖",
      "clock730": "🕢",
      "clock8": "🕗",
      "clock830": "🕣",
      "clock9": "🕘",
      "clock930": "🕤",
      "closed_book": "📕",
      "closed_lock_with_key": "🔐",
      "closed_umbrella": "🌂",
      "cloud": "☁️",
      "cloud_with_lightning": "🌩",
      "cloud_with_lightning_and_rain": "⛈",
      "cloud_with_rain": "🌧",
      "cloud_with_snow": "🌨",
      "clown_face": "🤡",
      "clubs": "♣️",
      "cocktail": "🍸",
      "coffee": "☕️",
      "coffin": "⚰️",
      "cold_sweat": "😰",
      "comet": "☄️",
      "computer": "💻",
      "computer_mouse": "🖱",
      "confetti_ball": "🎊",
      "confounded": "😖",
      "confused": "😕",
      "congratulations": "㊗️",
      "construction": "🚧",
      "construction_worker_man": "👷",
      "construction_worker_woman": "👷&zwj;♀️",
      "control_knobs": "🎛",
      "convenience_store": "🏪",
      "cookie": "🍪",
      "cool": "🆒",
      "policeman": "👮",
      "copyright": "©️",
      "corn": "🌽",
      "couch_and_lamp": "🛋",
      "couple": "👫",
      "couple_with_heart_woman_man": "💑",
      "couple_with_heart_man_man": "👨&zwj;❤️&zwj;👨",
      "couple_with_heart_woman_woman": "👩&zwj;❤️&zwj;👩",
      "couplekiss_man_man": "👨&zwj;❤️&zwj;💋&zwj;👨",
      "couplekiss_man_woman": "💏",
      "couplekiss_woman_woman": "👩&zwj;❤️&zwj;💋&zwj;👩",
      "cow": "🐮",
      "cow2": "🐄",
      "cowboy_hat_face": "🤠",
      "crab": "🦀",
      "crayon": "🖍",
      "credit_card": "💳",
      "crescent_moon": "🌙",
      "cricket": "🏏",
      "crocodile": "🐊",
      "croissant": "🥐",
      "crossed_fingers": "🤞",
      "crossed_flags": "🎌",
      "crossed_swords": "⚔️",
      "crown": "👑",
      "cry": "😢",
      "crying_cat_face": "😿",
      "crystal_ball": "🔮",
      "cucumber": "🥒",
      "cupid": "💘",
      "curly_loop": "➰",
      "currency_exchange": "💱",
      "curry": "🍛",
      "custard": "🍮",
      "customs": "🛃",
      "cyclone": "🌀",
      "dagger": "🗡",
      "dancer": "💃",
      "dancing_women": "👯",
      "dancing_men": "👯&zwj;♂️",
      "dango": "🍡",
      "dark_sunglasses": "🕶",
      "dart": "🎯",
      "dash": "💨",
      "date": "📅",
      "deciduous_tree": "🌳",
      "deer": "🦌",
      "department_store": "🏬",
      "derelict_house": "🏚",
      "desert": "🏜",
      "desert_island": "🏝",
      "desktop_computer": "🖥",
      "male_detective": "🕵️",
      "diamond_shape_with_a_dot_inside": "💠",
      "diamonds": "♦️",
      "disappointed": "😞",
      "disappointed_relieved": "😥",
      "dizzy": "💫",
      "dizzy_face": "😵",
      "do_not_litter": "🚯",
      "dog": "🐶",
      "dog2": "🐕",
      "dollar": "💵",
      "dolls": "🎎",
      "dolphin": "🐬",
      "door": "🚪",
      "doughnut": "🍩",
      "dove": "🕊",
      "dragon": "🐉",
      "dragon_face": "🐲",
      "dress": "👗",
      "dromedary_camel": "🐪",
      "drooling_face": "🤤",
      "droplet": "💧",
      "drum": "🥁",
      "duck": "🦆",
      "dvd": "📀",
      "e-mail": "📧",
      "eagle": "🦅",
      "ear": "👂",
      "ear_of_rice": "🌾",
      "earth_africa": "🌍",
      "earth_americas": "🌎",
      "earth_asia": "🌏",
      "egg": "🥚",
      "eggplant": "🍆",
      "eight_pointed_black_star": "✴️",
      "eight_spoked_asterisk": "✳️",
      "electric_plug": "🔌",
      "elephant": "🐘",
      "email": "✉️",
      "end": "🔚",
      "envelope_with_arrow": "📩",
      "euro": "💶",
      "european_castle": "🏰",
      "european_post_office": "🏤",
      "evergreen_tree": "🌲",
      "exclamation": "❗️",
      "expressionless": "😑",
      "eye": "👁",
      "eye_speech_bubble": "👁&zwj;🗨",
      "eyeglasses": "👓",
      "eyes": "👀",
      "face_with_head_bandage": "🤕",
      "face_with_thermometer": "🤒",
      "fist_oncoming": "👊",
      "factory": "🏭",
      "fallen_leaf": "🍂",
      "family_man_woman_boy": "👪",
      "family_man_boy": "👨&zwj;👦",
      "family_man_boy_boy": "👨&zwj;👦&zwj;👦",
      "family_man_girl": "👨&zwj;👧",
      "family_man_girl_boy": "👨&zwj;👧&zwj;👦",
      "family_man_girl_girl": "👨&zwj;👧&zwj;👧",
      "family_man_man_boy": "👨&zwj;👨&zwj;👦",
      "family_man_man_boy_boy": "👨&zwj;👨&zwj;👦&zwj;👦",
      "family_man_man_girl": "👨&zwj;👨&zwj;👧",
      "family_man_man_girl_boy": "👨&zwj;👨&zwj;👧&zwj;👦",
      "family_man_man_girl_girl": "👨&zwj;👨&zwj;👧&zwj;👧",
      "family_man_woman_boy_boy": "👨&zwj;👩&zwj;👦&zwj;👦",
      "family_man_woman_girl": "👨&zwj;👩&zwj;👧",
      "family_man_woman_girl_boy": "👨&zwj;👩&zwj;👧&zwj;👦",
      "family_man_woman_girl_girl": "👨&zwj;👩&zwj;👧&zwj;👧",
      "family_woman_boy": "👩&zwj;👦",
      "family_woman_boy_boy": "👩&zwj;👦&zwj;👦",
      "family_woman_girl": "👩&zwj;👧",
      "family_woman_girl_boy": "👩&zwj;👧&zwj;👦",
      "family_woman_girl_girl": "👩&zwj;👧&zwj;👧",
      "family_woman_woman_boy": "👩&zwj;👩&zwj;👦",
      "family_woman_woman_boy_boy": "👩&zwj;👩&zwj;👦&zwj;👦",
      "family_woman_woman_girl": "👩&zwj;👩&zwj;👧",
      "family_woman_woman_girl_boy": "👩&zwj;👩&zwj;👧&zwj;👦",
      "family_woman_woman_girl_girl": "👩&zwj;👩&zwj;👧&zwj;👧",
      "fast_forward": "⏩",
      "fax": "📠",
      "fearful": "😨",
      "feet": "🐾",
      "female_detective": "🕵️&zwj;♀️",
      "ferris_wheel": "🎡",
      "ferry": "⛴",
      "field_hockey": "🏑",
      "file_cabinet": "🗄",
      "file_folder": "📁",
      "film_projector": "📽",
      "film_strip": "🎞",
      "fire": "🔥",
      "fire_engine": "🚒",
      "fireworks": "🎆",
      "first_quarter_moon": "🌓",
      "first_quarter_moon_with_face": "🌛",
      "fish": "🐟",
      "fish_cake": "🍥",
      "fishing_pole_and_fish": "🎣",
      "fist_raised": "✊",
      "fist_left": "🤛",
      "fist_right": "🤜",
      "flags": "🎏",
      "flashlight": "🔦",
      "fleur_de_lis": "⚜️",
      "flight_arrival": "🛬",
      "flight_departure": "🛫",
      "floppy_disk": "💾",
      "flower_playing_cards": "🎴",
      "flushed": "😳",
      "fog": "🌫",
      "foggy": "🌁",
      "football": "🏈",
      "footprints": "👣",
      "fork_and_knife": "🍴",
      "fountain": "⛲️",
      "fountain_pen": "🖋",
      "four_leaf_clover": "🍀",
      "fox_face": "🦊",
      "framed_picture": "🖼",
      "free": "🆓",
      "fried_egg": "🍳",
      "fried_shrimp": "🍤",
      "fries": "🍟",
      "frog": "🐸",
      "frowning": "😦",
      "frowning_face": "☹️",
      "frowning_man": "🙍&zwj;♂️",
      "frowning_woman": "🙍",
      "middle_finger": "🖕",
      "fuelpump": "⛽️",
      "full_moon": "🌕",
      "full_moon_with_face": "🌝",
      "funeral_urn": "⚱️",
      "game_die": "🎲",
      "gear": "⚙️",
      "gem": "💎",
      "gemini": "♊️",
      "ghost": "👻",
      "gift": "🎁",
      "gift_heart": "💝",
      "girl": "👧",
      "globe_with_meridians": "🌐",
      "goal_net": "🥅",
      "goat": "🐐",
      "golf": "⛳️",
      "golfing_man": "🏌️",
      "golfing_woman": "🏌️&zwj;♀️",
      "gorilla": "🦍",
      "grapes": "🍇",
      "green_apple": "🍏",
      "green_book": "📗",
      "green_heart": "💚",
      "green_salad": "🥗",
      "grey_exclamation": "❕",
      "grey_question": "❔",
      "grimacing": "😬",
      "grin": "😁",
      "grinning": "😀",
      "guardsman": "💂",
      "guardswoman": "💂&zwj;♀️",
      "guitar": "🎸",
      "gun": "🔫",
      "haircut_woman": "💇",
      "haircut_man": "💇&zwj;♂️",
      "hamburger": "🍔",
      "hammer": "🔨",
      "hammer_and_pick": "⚒",
      "hammer_and_wrench": "🛠",
      "hamster": "🐹",
      "hand": "✋",
      "handbag": "👜",
      "handshake": "🤝",
      "hankey": "💩",
      "hatched_chick": "🐥",
      "hatching_chick": "🐣",
      "headphones": "🎧",
      "hear_no_evil": "🙉",
      "heart": "❤️",
      "heart_decoration": "💟",
      "heart_eyes": "😍",
      "heart_eyes_cat": "😻",
      "heartbeat": "💓",
      "heartpulse": "💗",
      "hearts": "♥️",
      "heavy_check_mark": "✔️",
      "heavy_division_sign": "➗",
      "heavy_dollar_sign": "💲",
      "heavy_heart_exclamation": "❣️",
      "heavy_minus_sign": "➖",
      "heavy_multiplication_x": "✖️",
      "heavy_plus_sign": "➕",
      "helicopter": "🚁",
      "herb": "🌿",
      "hibiscus": "🌺",
      "high_brightness": "🔆",
      "high_heel": "👠",
      "hocho": "🔪",
      "hole": "🕳",
      "honey_pot": "🍯",
      "horse": "🐴",
      "horse_racing": "🏇",
      "hospital": "🏥",
      "hot_pepper": "🌶",
      "hotdog": "🌭",
      "hotel": "🏨",
      "hotsprings": "♨️",
      "hourglass": "⌛️",
      "hourglass_flowing_sand": "⏳",
      "house": "🏠",
      "house_with_garden": "🏡",
      "houses": "🏘",
      "hugs": "🤗",
      "hushed": "😯",
      "ice_cream": "🍨",
      "ice_hockey": "🏒",
      "ice_skate": "⛸",
      "icecream": "🍦",
      "id": "🆔",
      "ideograph_advantage": "🉐",
      "imp": "👿",
      "inbox_tray": "📥",
      "incoming_envelope": "📨",
      "tipping_hand_woman": "💁",
      "information_source": "ℹ️",
      "innocent": "😇",
      "interrobang": "⁉️",
      "iphone": "📱",
      "izakaya_lantern": "🏮",
      "jack_o_lantern": "🎃",
      "japan": "🗾",
      "japanese_castle": "🏯",
      "japanese_goblin": "👺",
      "japanese_ogre": "👹",
      "jeans": "👖",
      "joy": "😂",
      "joy_cat": "😹",
      "joystick": "🕹",
      "kaaba": "🕋",
      "key": "🔑",
      "keyboard": "⌨️",
      "keycap_ten": "🔟",
      "kick_scooter": "🛴",
      "kimono": "👘",
      "kiss": "💋",
      "kissing": "😗",
      "kissing_cat": "😽",
      "kissing_closed_eyes": "😚",
      "kissing_heart": "😘",
      "kissing_smiling_eyes": "😙",
      "kiwi_fruit": "🥝",
      "koala": "🐨",
      "koko": "🈁",
      "label": "🏷",
      "large_blue_circle": "🔵",
      "large_blue_diamond": "🔷",
      "large_orange_diamond": "🔶",
      "last_quarter_moon": "🌗",
      "last_quarter_moon_with_face": "🌜",
      "latin_cross": "✝️",
      "laughing": "😆",
      "leaves": "🍃",
      "ledger": "📒",
      "left_luggage": "🛅",
      "left_right_arrow": "↔️",
      "leftwards_arrow_with_hook": "↩️",
      "lemon": "🍋",
      "leo": "♌️",
      "leopard": "🐆",
      "level_slider": "🎚",
      "libra": "♎️",
      "light_rail": "🚈",
      "link": "🔗",
      "lion": "🦁",
      "lips": "👄",
      "lipstick": "💄",
      "lizard": "🦎",
      "lock": "🔒",
      "lock_with_ink_pen": "🔏",
      "lollipop": "🍭",
      "loop": "➿",
      "loud_sound": "🔊",
      "loudspeaker": "📢",
      "love_hotel": "🏩",
      "love_letter": "💌",
      "low_brightness": "🔅",
      "lying_face": "🤥",
      "m": "Ⓜ️",
      "mag": "🔍",
      "mag_right": "🔎",
      "mahjong": "🀄️",
      "mailbox": "📫",
      "mailbox_closed": "📪",
      "mailbox_with_mail": "📬",
      "mailbox_with_no_mail": "📭",
      "man": "👨",
      "man_artist": "👨&zwj;🎨",
      "man_astronaut": "👨&zwj;🚀",
      "man_cartwheeling": "🤸&zwj;♂️",
      "man_cook": "👨&zwj;🍳",
      "man_dancing": "🕺",
      "man_facepalming": "🤦&zwj;♂️",
      "man_factory_worker": "👨&zwj;🏭",
      "man_farmer": "👨&zwj;🌾",
      "man_firefighter": "👨&zwj;🚒",
      "man_health_worker": "👨&zwj;⚕️",
      "man_in_tuxedo": "🤵",
      "man_judge": "👨&zwj;⚖️",
      "man_juggling": "🤹&zwj;♂️",
      "man_mechanic": "👨&zwj;🔧",
      "man_office_worker": "👨&zwj;💼",
      "man_pilot": "👨&zwj;✈️",
      "man_playing_handball": "🤾&zwj;♂️",
      "man_playing_water_polo": "🤽&zwj;♂️",
      "man_scientist": "👨&zwj;🔬",
      "man_shrugging": "🤷&zwj;♂️",
      "man_singer": "👨&zwj;🎤",
      "man_student": "👨&zwj;🎓",
      "man_teacher": "👨&zwj;🏫",
      "man_technologist": "👨&zwj;💻",
      "man_with_gua_pi_mao": "👲",
      "man_with_turban": "👳",
      "tangerine": "🍊",
      "mans_shoe": "👞",
      "mantelpiece_clock": "🕰",
      "maple_leaf": "🍁",
      "martial_arts_uniform": "🥋",
      "mask": "😷",
      "massage_woman": "💆",
      "massage_man": "💆&zwj;♂️",
      "meat_on_bone": "🍖",
      "medal_military": "🎖",
      "medal_sports": "🏅",
      "mega": "📣",
      "melon": "🍈",
      "memo": "📝",
      "men_wrestling": "🤼&zwj;♂️",
      "menorah": "🕎",
      "mens": "🚹",
      "metal": "🤘",
      "metro": "🚇",
      "microphone": "🎤",
      "microscope": "🔬",
      "milk_glass": "🥛",
      "milky_way": "🌌",
      "minibus": "🚐",
      "minidisc": "💽",
      "mobile_phone_off": "📴",
      "money_mouth_face": "🤑",
      "money_with_wings": "💸",
      "moneybag": "💰",
      "monkey": "🐒",
      "monkey_face": "🐵",
      "monorail": "🚝",
      "moon": "🌔",
      "mortar_board": "🎓",
      "mosque": "🕌",
      "motor_boat": "🛥",
      "motor_scooter": "🛵",
      "motorcycle": "🏍",
      "motorway": "🛣",
      "mount_fuji": "🗻",
      "mountain": "⛰",
      "mountain_biking_man": "🚵",
      "mountain_biking_woman": "🚵&zwj;♀️",
      "mountain_cableway": "🚠",
      "mountain_railway": "🚞",
      "mountain_snow": "🏔",
      "mouse": "🐭",
      "mouse2": "🐁",
      "movie_camera": "🎥",
      "moyai": "🗿",
      "mrs_claus": "🤶",
      "muscle": "💪",
      "mushroom": "🍄",
      "musical_keyboard": "🎹",
      "musical_note": "🎵",
      "musical_score": "🎼",
      "mute": "🔇",
      "nail_care": "💅",
      "name_badge": "📛",
      "national_park": "🏞",
      "nauseated_face": "🤢",
      "necktie": "👔",
      "negative_squared_cross_mark": "❎",
      "nerd_face": "🤓",
      "neutral_face": "😐",
      "new": "🆕",
      "new_moon": "🌑",
      "new_moon_with_face": "🌚",
      "newspaper": "📰",
      "newspaper_roll": "🗞",
      "next_track_button": "⏭",
      "ng": "🆖",
      "no_good_man": "🙅&zwj;♂️",
      "no_good_woman": "🙅",
      "night_with_stars": "🌃",
      "no_bell": "🔕",
      "no_bicycles": "🚳",
      "no_entry": "⛔️",
      "no_entry_sign": "🚫",
      "no_mobile_phones": "📵",
      "no_mouth": "😶",
      "no_pedestrians": "🚷",
      "no_smoking": "🚭",
      "non-potable_water": "🚱",
      "nose": "👃",
      "notebook": "📓",
      "notebook_with_decorative_cover": "📔",
      "notes": "🎶",
      "nut_and_bolt": "🔩",
      "o": "⭕️",
      "o2": "🅾️",
      "ocean": "🌊",
      "octopus": "🐙",
      "oden": "🍢",
      "office": "🏢",
      "oil_drum": "🛢",
      "ok": "🆗",
      "ok_hand": "👌",
      "ok_man": "🙆&zwj;♂️",
      "ok_woman": "🙆",
      "old_key": "🗝",
      "older_man": "👴",
      "older_woman": "👵",
      "om": "🕉",
      "on": "🔛",
      "oncoming_automobile": "🚘",
      "oncoming_bus": "🚍",
      "oncoming_police_car": "🚔",
      "oncoming_taxi": "🚖",
      "open_file_folder": "📂",
      "open_hands": "👐",
      "open_mouth": "😮",
      "open_umbrella": "☂️",
      "ophiuchus": "⛎",
      "orange_book": "📙",
      "orthodox_cross": "☦️",
      "outbox_tray": "📤",
      "owl": "🦉",
      "ox": "🐂",
      "package": "📦",
      "page_facing_up": "📄",
      "page_with_curl": "📃",
      "pager": "📟",
      "paintbrush": "🖌",
      "palm_tree": "🌴",
      "pancakes": "🥞",
      "panda_face": "🐼",
      "paperclip": "📎",
      "paperclips": "🖇",
      "parasol_on_ground": "⛱",
      "parking": "🅿️",
      "part_alternation_mark": "〽️",
      "partly_sunny": "⛅️",
      "passenger_ship": "🛳",
      "passport_control": "🛂",
      "pause_button": "⏸",
      "peace_symbol": "☮️",
      "peach": "🍑",
      "peanuts": "🥜",
      "pear": "🍐",
      "pen": "🖊",
      "pencil2": "✏️",
      "penguin": "🐧",
      "pensive": "😔",
      "performing_arts": "🎭",
      "persevere": "😣",
      "person_fencing": "🤺",
      "pouting_woman": "🙎",
      "phone": "☎️",
      "pick": "⛏",
      "pig": "🐷",
      "pig2": "🐖",
      "pig_nose": "🐽",
      "pill": "💊",
      "pineapple": "🍍",
      "ping_pong": "🏓",
      "pisces": "♓️",
      "pizza": "🍕",
      "place_of_worship": "🛐",
      "plate_with_cutlery": "🍽",
      "play_or_pause_button": "⏯",
      "point_down": "👇",
      "point_left": "👈",
      "point_right": "👉",
      "point_up": "☝️",
      "point_up_2": "👆",
      "police_car": "🚓",
      "policewoman": "👮&zwj;♀️",
      "poodle": "🐩",
      "popcorn": "🍿",
      "post_office": "🏣",
      "postal_horn": "📯",
      "postbox": "📮",
      "potable_water": "🚰",
      "potato": "🥔",
      "pouch": "👝",
      "poultry_leg": "🍗",
      "pound": "💷",
      "rage": "😡",
      "pouting_cat": "😾",
      "pouting_man": "🙎&zwj;♂️",
      "pray": "🙏",
      "prayer_beads": "📿",
      "pregnant_woman": "🤰",
      "previous_track_button": "⏮",
      "prince": "🤴",
      "princess": "👸",
      "printer": "🖨",
      "purple_heart": "💜",
      "purse": "👛",
      "pushpin": "📌",
      "put_litter_in_its_place": "🚮",
      "question": "❓",
      "rabbit": "🐰",
      "rabbit2": "🐇",
      "racehorse": "🐎",
      "racing_car": "🏎",
      "radio": "📻",
      "radio_button": "🔘",
      "radioactive": "☢️",
      "railway_car": "🚃",
      "railway_track": "🛤",
      "rainbow": "🌈",
      "rainbow_flag": "🏳️&zwj;🌈",
      "raised_back_of_hand": "🤚",
      "raised_hand_with_fingers_splayed": "🖐",
      "raised_hands": "🙌",
      "raising_hand_woman": "🙋",
      "raising_hand_man": "🙋&zwj;♂️",
      "ram": "🐏",
      "ramen": "🍜",
      "rat": "🐀",
      "record_button": "⏺",
      "recycle": "♻️",
      "red_circle": "🔴",
      "registered": "®️",
      "relaxed": "☺️",
      "relieved": "😌",
      "reminder_ribbon": "🎗",
      "repeat": "🔁",
      "repeat_one": "🔂",
      "rescue_worker_helmet": "⛑",
      "restroom": "🚻",
      "revolving_hearts": "💞",
      "rewind": "⏪",
      "rhinoceros": "🦏",
      "ribbon": "🎀",
      "rice": "🍚",
      "rice_ball": "🍙",
      "rice_cracker": "🍘",
      "rice_scene": "🎑",
      "right_anger_bubble": "🗯",
      "ring": "💍",
      "robot": "🤖",
      "rocket": "🚀",
      "rofl": "🤣",
      "roll_eyes": "🙄",
      "roller_coaster": "🎢",
      "rooster": "🐓",
      "rose": "🌹",
      "rosette": "🏵",
      "rotating_light": "🚨",
      "round_pushpin": "📍",
      "rowing_man": "🚣",
      "rowing_woman": "🚣&zwj;♀️",
      "rugby_football": "🏉",
      "running_man": "🏃",
      "running_shirt_with_sash": "🎽",
      "running_woman": "🏃&zwj;♀️",
      "sa": "🈂️",
      "sagittarius": "♐️",
      "sake": "🍶",
      "sandal": "👡",
      "santa": "🎅",
      "satellite": "📡",
      "saxophone": "🎷",
      "school": "🏫",
      "school_satchel": "🎒",
      "scissors": "✂️",
      "scorpion": "🦂",
      "scorpius": "♏️",
      "scream": "😱",
      "scream_cat": "🙀",
      "scroll": "📜",
      "seat": "💺",
      "secret": "㊙️",
      "see_no_evil": "🙈",
      "seedling": "🌱",
      "selfie": "🤳",
      "shallow_pan_of_food": "🥘",
      "shamrock": "☘️",
      "shark": "🦈",
      "shaved_ice": "🍧",
      "sheep": "🐑",
      "shell": "🐚",
      "shield": "🛡",
      "shinto_shrine": "⛩",
      "ship": "🚢",
      "shirt": "👕",
      "shopping": "🛍",
      "shopping_cart": "🛒",
      "shower": "🚿",
      "shrimp": "🦐",
      "signal_strength": "📶",
      "six_pointed_star": "🔯",
      "ski": "🎿",
      "skier": "⛷",
      "skull": "💀",
      "skull_and_crossbones": "☠️",
      "sleeping": "😴",
      "sleeping_bed": "🛌",
      "sleepy": "😪",
      "slightly_frowning_face": "🙁",
      "slightly_smiling_face": "🙂",
      "slot_machine": "🎰",
      "small_airplane": "🛩",
      "small_blue_diamond": "🔹",
      "small_orange_diamond": "🔸",
      "small_red_triangle": "🔺",
      "small_red_triangle_down": "🔻",
      "smile": "😄",
      "smile_cat": "😸",
      "smiley": "😃",
      "smiley_cat": "😺",
      "smiling_imp": "😈",
      "smirk": "😏",
      "smirk_cat": "😼",
      "smoking": "🚬",
      "snail": "🐌",
      "snake": "🐍",
      "sneezing_face": "🤧",
      "snowboarder": "🏂",
      "snowflake": "❄️",
      "snowman": "⛄️",
      "snowman_with_snow": "☃️",
      "sob": "😭",
      "soccer": "⚽️",
      "soon": "🔜",
      "sos": "🆘",
      "sound": "🔉",
      "space_invader": "👾",
      "spades": "♠️",
      "spaghetti": "🍝",
      "sparkle": "❇️",
      "sparkler": "🎇",
      "sparkles": "✨",
      "sparkling_heart": "💖",
      "speak_no_evil": "🙊",
      "speaker": "🔈",
      "speaking_head": "🗣",
      "speech_balloon": "💬",
      "speedboat": "🚤",
      "spider": "🕷",
      "spider_web": "🕸",
      "spiral_calendar": "🗓",
      "spiral_notepad": "🗒",
      "spoon": "🥄",
      "squid": "🦑",
      "stadium": "🏟",
      "star": "⭐️",
      "star2": "🌟",
      "star_and_crescent": "☪️",
      "star_of_david": "✡️",
      "stars": "🌠",
      "station": "🚉",
      "statue_of_liberty": "🗽",
      "steam_locomotive": "🚂",
      "stew": "🍲",
      "stop_button": "⏹",
      "stop_sign": "🛑",
      "stopwatch": "⏱",
      "straight_ruler": "📏",
      "strawberry": "🍓",
      "stuck_out_tongue": "😛",
      "stuck_out_tongue_closed_eyes": "😝",
      "stuck_out_tongue_winking_eye": "😜",
      "studio_microphone": "🎙",
      "stuffed_flatbread": "🥙",
      "sun_behind_large_cloud": "🌥",
      "sun_behind_rain_cloud": "🌦",
      "sun_behind_small_cloud": "🌤",
      "sun_with_face": "🌞",
      "sunflower": "🌻",
      "sunglasses": "😎",
      "sunny": "☀️",
      "sunrise": "🌅",
      "sunrise_over_mountains": "🌄",
      "surfing_man": "🏄",
      "surfing_woman": "🏄&zwj;♀️",
      "sushi": "🍣",
      "suspension_railway": "🚟",
      "sweat": "😓",
      "sweat_drops": "💦",
      "sweat_smile": "😅",
      "sweet_potato": "🍠",
      "swimming_man": "🏊",
      "swimming_woman": "🏊&zwj;♀️",
      "symbols": "🔣",
      "synagogue": "🕍",
      "syringe": "💉",
      "taco": "🌮",
      "tada": "🎉",
      "tanabata_tree": "🎋",
      "taurus": "♉️",
      "taxi": "🚕",
      "tea": "🍵",
      "telephone_receiver": "📞",
      "telescope": "🔭",
      "tennis": "🎾",
      "tent": "⛺️",
      "thermometer": "🌡",
      "thinking": "🤔",
      "thought_balloon": "💭",
      "ticket": "🎫",
      "tickets": "🎟",
      "tiger": "🐯",
      "tiger2": "🐅",
      "timer_clock": "⏲",
      "tipping_hand_man": "💁&zwj;♂️",
      "tired_face": "😫",
      "tm": "™️",
      "toilet": "🚽",
      "tokyo_tower": "🗼",
      "tomato": "🍅",
      "tongue": "👅",
      "top": "🔝",
      "tophat": "🎩",
      "tornado": "🌪",
      "trackball": "🖲",
      "tractor": "🚜",
      "traffic_light": "🚥",
      "train": "🚋",
      "train2": "🚆",
      "tram": "🚊",
      "triangular_flag_on_post": "🚩",
      "triangular_ruler": "📐",
      "trident": "🔱",
      "triumph": "😤",
      "trolleybus": "🚎",
      "trophy": "🏆",
      "tropical_drink": "🍹",
      "tropical_fish": "🐠",
      "truck": "🚚",
      "trumpet": "🎺",
      "tulip": "🌷",
      "tumbler_glass": "🥃",
      "turkey": "🦃",
      "turtle": "🐢",
      "tv": "📺",
      "twisted_rightwards_arrows": "🔀",
      "two_hearts": "💕",
      "two_men_holding_hands": "👬",
      "two_women_holding_hands": "👭",
      "u5272": "🈹",
      "u5408": "🈴",
      "u55b6": "🈺",
      "u6307": "🈯️",
      "u6708": "🈷️",
      "u6709": "🈶",
      "u6e80": "🈵",
      "u7121": "🈚️",
      "u7533": "🈸",
      "u7981": "🈲",
      "u7a7a": "🈳",
      "umbrella": "☔️",
      "unamused": "😒",
      "underage": "🔞",
      "unicorn": "🦄",
      "unlock": "🔓",
      "up": "🆙",
      "upside_down_face": "🙃",
      "v": "✌️",
      "vertical_traffic_light": "🚦",
      "vhs": "📼",
      "vibration_mode": "📳",
      "video_camera": "📹",
      "video_game": "🎮",
      "violin": "🎻",
      "virgo": "♍️",
      "volcano": "🌋",
      "volleyball": "🏐",
      "vs": "🆚",
      "vulcan_salute": "🖖",
      "walking_man": "🚶",
      "walking_woman": "🚶&zwj;♀️",
      "waning_crescent_moon": "🌘",
      "waning_gibbous_moon": "🌖",
      "warning": "⚠️",
      "wastebasket": "🗑",
      "watch": "⌚️",
      "water_buffalo": "🐃",
      "watermelon": "🍉",
      "wave": "👋",
      "wavy_dash": "〰️",
      "waxing_crescent_moon": "🌒",
      "wc": "🚾",
      "weary": "😩",
      "wedding": "💒",
      "weight_lifting_man": "🏋️",
      "weight_lifting_woman": "🏋️&zwj;♀️",
      "whale": "🐳",
      "whale2": "🐋",
      "wheel_of_dharma": "☸️",
      "wheelchair": "♿️",
      "white_check_mark": "✅",
      "white_circle": "⚪️",
      "white_flag": "🏳️",
      "white_flower": "💮",
      "white_large_square": "⬜️",
      "white_medium_small_square": "◽️",
      "white_medium_square": "◻️",
      "white_small_square": "▫️",
      "white_square_button": "🔳",
      "wilted_flower": "🥀",
      "wind_chime": "🎐",
      "wind_face": "🌬",
      "wine_glass": "🍷",
      "wink": "😉",
      "wolf": "🐺",
      "woman": "👩",
      "woman_artist": "👩&zwj;🎨",
      "woman_astronaut": "👩&zwj;🚀",
      "woman_cartwheeling": "🤸&zwj;♀️",
      "woman_cook": "👩&zwj;🍳",
      "woman_facepalming": "🤦&zwj;♀️",
      "woman_factory_worker": "👩&zwj;🏭",
      "woman_farmer": "👩&zwj;🌾",
      "woman_firefighter": "👩&zwj;🚒",
      "woman_health_worker": "👩&zwj;⚕️",
      "woman_judge": "👩&zwj;⚖️",
      "woman_juggling": "🤹&zwj;♀️",
      "woman_mechanic": "👩&zwj;🔧",
      "woman_office_worker": "👩&zwj;💼",
      "woman_pilot": "👩&zwj;✈️",
      "woman_playing_handball": "🤾&zwj;♀️",
      "woman_playing_water_polo": "🤽&zwj;♀️",
      "woman_scientist": "👩&zwj;🔬",
      "woman_shrugging": "🤷&zwj;♀️",
      "woman_singer": "👩&zwj;🎤",
      "woman_student": "👩&zwj;🎓",
      "woman_teacher": "👩&zwj;🏫",
      "woman_technologist": "👩&zwj;💻",
      "woman_with_turban": "👳&zwj;♀️",
      "womans_clothes": "👚",
      "womans_hat": "👒",
      "women_wrestling": "🤼&zwj;♀️",
      "womens": "🚺",
      "world_map": "🗺",
      "worried": "😟",
      "wrench": "🔧",
      "writing_hand": "✍️",
      "x": "❌",
      "yellow_heart": "💛",
      "yen": "💴",
      "yin_yang": "☯️",
      "yum": "😋",
      "zap": "⚡️",
      "zipper_mouth_face": "🤐",
      "zzz": "💤",
      /* special emojis :P */
      "octocat": '<img alt=":octocat:" height="20" width="20" align="absmiddle" src="https://assets-cdn.github.com/images/icons/emoji/octocat.png">',
      "showdown": `<span style="font-family: 'Anonymous Pro', monospace; text-decoration: underline; text-decoration-style: dashed; text-decoration-color: #3e8b8a;text-underline-position: under;">S</span>`
    };
    showdown2.Converter = function(converterOptions) {
      var options = {}, langExtensions = [], outputModifiers = [], listeners = {}, setConvFlavor = setFlavor, metadata = {
        parsed: {},
        raw: "",
        format: ""
      };
      _constructor();
      function _constructor() {
        converterOptions = converterOptions || {};
        for (var gOpt in globalOptions) {
          if (globalOptions.hasOwnProperty(gOpt)) {
            options[gOpt] = globalOptions[gOpt];
          }
        }
        if (typeof converterOptions === "object") {
          for (var opt in converterOptions) {
            if (converterOptions.hasOwnProperty(opt)) {
              options[opt] = converterOptions[opt];
            }
          }
        } else {
          throw Error("Converter expects the passed parameter to be an object, but " + typeof converterOptions + " was passed instead.");
        }
        if (options.extensions) {
          showdown2.helper.forEach(options.extensions, _parseExtension);
        }
      }
      function _parseExtension(ext, name) {
        name = name || null;
        if (showdown2.helper.isString(ext)) {
          ext = showdown2.helper.stdExtName(ext);
          name = ext;
          if (showdown2.extensions[ext]) {
            console.warn("DEPRECATION WARNING: " + ext + " is an old extension that uses a deprecated loading method.Please inform the developer that the extension should be updated!");
            legacyExtensionLoading(showdown2.extensions[ext], ext);
            return;
          } else if (!showdown2.helper.isUndefined(extensions[ext])) {
            ext = extensions[ext];
          } else {
            throw Error('Extension "' + ext + '" could not be loaded. It was either not found or is not a valid extension.');
          }
        }
        if (typeof ext === "function") {
          ext = ext();
        }
        if (!showdown2.helper.isArray(ext)) {
          ext = [ext];
        }
        var validExt = validate2(ext, name);
        if (!validExt.valid) {
          throw Error(validExt.error);
        }
        for (var i2 = 0; i2 < ext.length; ++i2) {
          switch (ext[i2].type) {
            case "lang":
              langExtensions.push(ext[i2]);
              break;
            case "output":
              outputModifiers.push(ext[i2]);
              break;
          }
          if (ext[i2].hasOwnProperty("listeners")) {
            for (var ln in ext[i2].listeners) {
              if (ext[i2].listeners.hasOwnProperty(ln)) {
                listen(ln, ext[i2].listeners[ln]);
              }
            }
          }
        }
      }
      function legacyExtensionLoading(ext, name) {
        if (typeof ext === "function") {
          ext = ext(new showdown2.Converter());
        }
        if (!showdown2.helper.isArray(ext)) {
          ext = [ext];
        }
        var valid = validate2(ext, name);
        if (!valid.valid) {
          throw Error(valid.error);
        }
        for (var i2 = 0; i2 < ext.length; ++i2) {
          switch (ext[i2].type) {
            case "lang":
              langExtensions.push(ext[i2]);
              break;
            case "output":
              outputModifiers.push(ext[i2]);
              break;
            default:
              throw Error("Extension loader error: Type unrecognized!!!");
          }
        }
      }
      function listen(name, callback) {
        if (!showdown2.helper.isString(name)) {
          throw Error("Invalid argument in converter.listen() method: name must be a string, but " + typeof name + " given");
        }
        if (typeof callback !== "function") {
          throw Error("Invalid argument in converter.listen() method: callback must be a function, but " + typeof callback + " given");
        }
        if (!listeners.hasOwnProperty(name)) {
          listeners[name] = [];
        }
        listeners[name].push(callback);
      }
      function rTrimInputText(text) {
        var rsp = text.match(/^\s*/)[0].length, rgx = new RegExp("^\\s{0," + rsp + "}", "gm");
        return text.replace(rgx, "");
      }
      this._dispatch = function dispatch(evtName, text, options2, globals) {
        if (listeners.hasOwnProperty(evtName)) {
          for (var ei = 0; ei < listeners[evtName].length; ++ei) {
            var nText = listeners[evtName][ei](evtName, text, this, options2, globals);
            if (nText && typeof nText !== "undefined") {
              text = nText;
            }
          }
        }
        return text;
      };
      this.listen = function(name, callback) {
        listen(name, callback);
        return this;
      };
      this.makeHtml = function(text) {
        if (!text) {
          return text;
        }
        var globals = {
          gHtmlBlocks: [],
          gHtmlMdBlocks: [],
          gHtmlSpans: [],
          gUrls: {},
          gTitles: {},
          gDimensions: {},
          gListLevel: 0,
          hashLinkCounts: {},
          langExtensions,
          outputModifiers,
          converter: this,
          ghCodeBlocks: [],
          metadata: {
            parsed: {},
            raw: "",
            format: ""
          }
        };
        text = text.replace(/¨/g, "¨T");
        text = text.replace(/\$/g, "¨D");
        text = text.replace(/\r\n/g, "\n");
        text = text.replace(/\r/g, "\n");
        text = text.replace(/\u00A0/g, "&nbsp;");
        if (options.smartIndentationFix) {
          text = rTrimInputText(text);
        }
        text = "\n\n" + text + "\n\n";
        text = showdown2.subParser("detab")(text, options, globals);
        text = text.replace(/^[ \t]+$/mg, "");
        showdown2.helper.forEach(langExtensions, function(ext) {
          text = showdown2.subParser("runExtension")(ext, text, options, globals);
        });
        text = showdown2.subParser("metadata")(text, options, globals);
        text = showdown2.subParser("hashPreCodeTags")(text, options, globals);
        text = showdown2.subParser("githubCodeBlocks")(text, options, globals);
        text = showdown2.subParser("hashHTMLBlocks")(text, options, globals);
        text = showdown2.subParser("hashCodeTags")(text, options, globals);
        text = showdown2.subParser("stripLinkDefinitions")(text, options, globals);
        text = showdown2.subParser("blockGamut")(text, options, globals);
        text = showdown2.subParser("unhashHTMLSpans")(text, options, globals);
        text = showdown2.subParser("unescapeSpecialChars")(text, options, globals);
        text = text.replace(/¨D/g, "$$");
        text = text.replace(/¨T/g, "¨");
        text = showdown2.subParser("completeHTMLDocument")(text, options, globals);
        showdown2.helper.forEach(outputModifiers, function(ext) {
          text = showdown2.subParser("runExtension")(ext, text, options, globals);
        });
        metadata = globals.metadata;
        return text;
      };
      this.makeMarkdown = this.makeMd = function(src, HTMLParser) {
        src = src.replace(/\r\n/g, "\n");
        src = src.replace(/\r/g, "\n");
        src = src.replace(/>[ \t]+</, ">¨NBSP;<");
        if (!HTMLParser) {
          if (window && window.document) {
            HTMLParser = window.document;
          } else {
            throw new Error("HTMLParser is undefined. If in a webworker or nodejs environment, you need to provide a WHATWG DOM and HTML such as JSDOM");
          }
        }
        var doc = HTMLParser.createElement("div");
        doc.innerHTML = src;
        var globals = {
          preList: substitutePreCodeTags(doc)
        };
        clean(doc);
        var nodes = doc.childNodes, mdDoc = "";
        for (var i2 = 0; i2 < nodes.length; i2++) {
          mdDoc += showdown2.subParser("makeMarkdown.node")(nodes[i2], globals);
        }
        function clean(node) {
          for (var n2 = 0; n2 < node.childNodes.length; ++n2) {
            var child = node.childNodes[n2];
            if (child.nodeType === 3) {
              if (!/\S/.test(child.nodeValue) && !/^[ ]+$/.test(child.nodeValue)) {
                node.removeChild(child);
                --n2;
              } else {
                child.nodeValue = child.nodeValue.split("\n").join(" ");
                child.nodeValue = child.nodeValue.replace(/(\s)+/g, "$1");
              }
            } else if (child.nodeType === 1) {
              clean(child);
            }
          }
        }
        function substitutePreCodeTags(doc2) {
          var pres = doc2.querySelectorAll("pre"), presPH = [];
          for (var i3 = 0; i3 < pres.length; ++i3) {
            if (pres[i3].childElementCount === 1 && pres[i3].firstChild.tagName.toLowerCase() === "code") {
              var content = pres[i3].firstChild.innerHTML.trim(), language = pres[i3].firstChild.getAttribute("data-language") || "";
              if (language === "") {
                var classes = pres[i3].firstChild.className.split(" ");
                for (var c2 = 0; c2 < classes.length; ++c2) {
                  var matches = classes[c2].match(/^language-(.+)$/);
                  if (matches !== null) {
                    language = matches[1];
                    break;
                  }
                }
              }
              content = showdown2.helper.unescapeHTMLEntities(content);
              presPH.push(content);
              pres[i3].outerHTML = '<precode language="' + language + '" precodenum="' + i3.toString() + '"></precode>';
            } else {
              presPH.push(pres[i3].innerHTML);
              pres[i3].innerHTML = "";
              pres[i3].setAttribute("prenum", i3.toString());
            }
          }
          return presPH;
        }
        return mdDoc;
      };
      this.setOption = function(key2, value) {
        options[key2] = value;
      };
      this.getOption = function(key2) {
        return options[key2];
      };
      this.getOptions = function() {
        return options;
      };
      this.addExtension = function(extension, name) {
        name = name || null;
        _parseExtension(extension, name);
      };
      this.useExtension = function(extensionName) {
        _parseExtension(extensionName);
      };
      this.setFlavor = function(name) {
        if (!flavor.hasOwnProperty(name)) {
          throw Error(name + " flavor was not found");
        }
        var preset = flavor[name];
        setConvFlavor = name;
        for (var option in preset) {
          if (preset.hasOwnProperty(option)) {
            options[option] = preset[option];
          }
        }
      };
      this.getFlavor = function() {
        return setConvFlavor;
      };
      this.removeExtension = function(extension) {
        if (!showdown2.helper.isArray(extension)) {
          extension = [extension];
        }
        for (var a2 = 0; a2 < extension.length; ++a2) {
          var ext = extension[a2];
          for (var i2 = 0; i2 < langExtensions.length; ++i2) {
            if (langExtensions[i2] === ext) {
              langExtensions.splice(i2, 1);
            }
          }
          for (var ii = 0; ii < outputModifiers.length; ++ii) {
            if (outputModifiers[ii] === ext) {
              outputModifiers.splice(ii, 1);
            }
          }
        }
      };
      this.getAllExtensions = function() {
        return {
          language: langExtensions,
          output: outputModifiers
        };
      };
      this.getMetadata = function(raw) {
        if (raw) {
          return metadata.raw;
        } else {
          return metadata.parsed;
        }
      };
      this.getMetadataFormat = function() {
        return metadata.format;
      };
      this._setMetadataPair = function(key2, value) {
        metadata.parsed[key2] = value;
      };
      this._setMetadataFormat = function(format2) {
        metadata.format = format2;
      };
      this._setMetadataRaw = function(raw) {
        metadata.raw = raw;
      };
    };
    showdown2.subParser("anchors", function(text, options, globals) {
      text = globals.converter._dispatch("anchors.before", text, options, globals);
      var writeAnchorTag = function(wholeMatch, linkText, linkId, url, m5, m6, title) {
        if (showdown2.helper.isUndefined(title)) {
          title = "";
        }
        linkId = linkId.toLowerCase();
        if (wholeMatch.search(/\(<?\s*>? ?(['"].*['"])?\)$/m) > -1) {
          url = "";
        } else if (!url) {
          if (!linkId) {
            linkId = linkText.toLowerCase().replace(/ ?\n/g, " ");
          }
          url = "#" + linkId;
          if (!showdown2.helper.isUndefined(globals.gUrls[linkId])) {
            url = globals.gUrls[linkId];
            if (!showdown2.helper.isUndefined(globals.gTitles[linkId])) {
              title = globals.gTitles[linkId];
            }
          } else {
            return wholeMatch;
          }
        }
        url = url.replace(showdown2.helper.regexes.asteriskDashAndColon, showdown2.helper.escapeCharactersCallback);
        var result = '<a href="' + url + '"';
        if (title !== "" && title !== null) {
          title = title.replace(/"/g, "&quot;");
          title = title.replace(showdown2.helper.regexes.asteriskDashAndColon, showdown2.helper.escapeCharactersCallback);
          result += ' title="' + title + '"';
        }
        if (options.openLinksInNewWindow && !/^#/.test(url)) {
          result += ' rel="noopener noreferrer" target="¨E95Eblank"';
        }
        result += ">" + linkText + "</a>";
        return result;
      };
      text = text.replace(/\[((?:\[[^\]]*]|[^\[\]])*)] ?(?:\n *)?\[(.*?)]()()()()/g, writeAnchorTag);
      text = text.replace(
        /\[((?:\[[^\]]*]|[^\[\]])*)]()[ \t]*\([ \t]?<([^>]*)>(?:[ \t]*((["'])([^"]*?)\5))?[ \t]?\)/g,
        writeAnchorTag
      );
      text = text.replace(
        /\[((?:\[[^\]]*]|[^\[\]])*)]()[ \t]*\([ \t]?<?([\S]+?(?:\([\S]*?\)[\S]*?)?)>?(?:[ \t]*((["'])([^"]*?)\5))?[ \t]?\)/g,
        writeAnchorTag
      );
      text = text.replace(/\[([^\[\]]+)]()()()()()/g, writeAnchorTag);
      if (options.ghMentions) {
        text = text.replace(/(^|\s)(\\)?(@([a-z\d]+(?:[a-z\d.-]+?[a-z\d]+)*))/gmi, function(wm, st, escape2, mentions, username) {
          if (escape2 === "\\") {
            return st + mentions;
          }
          if (!showdown2.helper.isString(options.ghMentionsLink)) {
            throw new Error("ghMentionsLink option must be a string");
          }
          var lnk = options.ghMentionsLink.replace(/\{u}/g, username), target = "";
          if (options.openLinksInNewWindow) {
            target = ' rel="noopener noreferrer" target="¨E95Eblank"';
          }
          return st + '<a href="' + lnk + '"' + target + ">" + mentions + "</a>";
        });
      }
      text = globals.converter._dispatch("anchors.after", text, options, globals);
      return text;
    });
    var simpleURLRegex = /([*~_]+|\b)(((https?|ftp|dict):\/\/|www\.)[^'">\s]+?\.[^'">\s]+?)()(\1)?(?=\s|$)(?!["<>])/gi, simpleURLRegex2 = /([*~_]+|\b)(((https?|ftp|dict):\/\/|www\.)[^'">\s]+\.[^'">\s]+?)([.!?,()\[\]])?(\1)?(?=\s|$)(?!["<>])/gi, delimUrlRegex = /()<(((https?|ftp|dict):\/\/|www\.)[^'">\s]+)()>()/gi, simpleMailRegex = /(^|\s)(?:mailto:)?([A-Za-z0-9!#$%&'*+-/=?^_`{|}~.]+@[-a-z0-9]+(\.[-a-z0-9]+)*\.[a-z]+)(?=$|\s)/gmi, delimMailRegex = /<()(?:mailto:)?([-.\w]+@[-a-z0-9]+(\.[-a-z0-9]+)*\.[a-z]+)>/gi, replaceLink = function(options) {
      return function(wm, leadingMagicChars, link, m2, m3, trailingPunctuation, trailingMagicChars) {
        link = link.replace(showdown2.helper.regexes.asteriskDashAndColon, showdown2.helper.escapeCharactersCallback);
        var lnkTxt = link, append = "", target = "", lmc = leadingMagicChars || "", tmc = trailingMagicChars || "";
        if (/^www\./i.test(link)) {
          link = link.replace(/^www\./i, "http://www.");
        }
        if (options.excludeTrailingPunctuationFromURLs && trailingPunctuation) {
          append = trailingPunctuation;
        }
        if (options.openLinksInNewWindow) {
          target = ' rel="noopener noreferrer" target="¨E95Eblank"';
        }
        return lmc + '<a href="' + link + '"' + target + ">" + lnkTxt + "</a>" + append + tmc;
      };
    }, replaceMail = function(options, globals) {
      return function(wholeMatch, b2, mail) {
        var href = "mailto:";
        b2 = b2 || "";
        mail = showdown2.subParser("unescapeSpecialChars")(mail, options, globals);
        if (options.encodeEmails) {
          href = showdown2.helper.encodeEmailAddress(href + mail);
          mail = showdown2.helper.encodeEmailAddress(mail);
        } else {
          href = href + mail;
        }
        return b2 + '<a href="' + href + '">' + mail + "</a>";
      };
    };
    showdown2.subParser("autoLinks", function(text, options, globals) {
      text = globals.converter._dispatch("autoLinks.before", text, options, globals);
      text = text.replace(delimUrlRegex, replaceLink(options));
      text = text.replace(delimMailRegex, replaceMail(options, globals));
      text = globals.converter._dispatch("autoLinks.after", text, options, globals);
      return text;
    });
    showdown2.subParser("simplifiedAutoLinks", function(text, options, globals) {
      if (!options.simplifiedAutoLink) {
        return text;
      }
      text = globals.converter._dispatch("simplifiedAutoLinks.before", text, options, globals);
      if (options.excludeTrailingPunctuationFromURLs) {
        text = text.replace(simpleURLRegex2, replaceLink(options));
      } else {
        text = text.replace(simpleURLRegex, replaceLink(options));
      }
      text = text.replace(simpleMailRegex, replaceMail(options, globals));
      text = globals.converter._dispatch("simplifiedAutoLinks.after", text, options, globals);
      return text;
    });
    showdown2.subParser("blockGamut", function(text, options, globals) {
      text = globals.converter._dispatch("blockGamut.before", text, options, globals);
      text = showdown2.subParser("blockQuotes")(text, options, globals);
      text = showdown2.subParser("headers")(text, options, globals);
      text = showdown2.subParser("horizontalRule")(text, options, globals);
      text = showdown2.subParser("lists")(text, options, globals);
      text = showdown2.subParser("codeBlocks")(text, options, globals);
      text = showdown2.subParser("tables")(text, options, globals);
      text = showdown2.subParser("hashHTMLBlocks")(text, options, globals);
      text = showdown2.subParser("paragraphs")(text, options, globals);
      text = globals.converter._dispatch("blockGamut.after", text, options, globals);
      return text;
    });
    showdown2.subParser("blockQuotes", function(text, options, globals) {
      text = globals.converter._dispatch("blockQuotes.before", text, options, globals);
      text = text + "\n\n";
      var rgx = /(^ {0,3}>[ \t]?.+\n(.+\n)*\n*)+/gm;
      if (options.splitAdjacentBlockquotes) {
        rgx = /^ {0,3}>[\s\S]*?(?:\n\n)/gm;
      }
      text = text.replace(rgx, function(bq) {
        bq = bq.replace(/^[ \t]*>[ \t]?/gm, "");
        bq = bq.replace(/¨0/g, "");
        bq = bq.replace(/^[ \t]+$/gm, "");
        bq = showdown2.subParser("githubCodeBlocks")(bq, options, globals);
        bq = showdown2.subParser("blockGamut")(bq, options, globals);
        bq = bq.replace(/(^|\n)/g, "$1  ");
        bq = bq.replace(/(\s*<pre>[^\r]+?<\/pre>)/gm, function(wholeMatch, m1) {
          var pre = m1;
          pre = pre.replace(/^  /mg, "¨0");
          pre = pre.replace(/¨0/g, "");
          return pre;
        });
        return showdown2.subParser("hashBlock")("<blockquote>\n" + bq + "\n</blockquote>", options, globals);
      });
      text = globals.converter._dispatch("blockQuotes.after", text, options, globals);
      return text;
    });
    showdown2.subParser("codeBlocks", function(text, options, globals) {
      text = globals.converter._dispatch("codeBlocks.before", text, options, globals);
      text += "¨0";
      var pattern = /(?:\n\n|^)((?:(?:[ ]{4}|\t).*\n+)+)(\n*[ ]{0,3}[^ \t\n]|(?=¨0))/g;
      text = text.replace(pattern, function(wholeMatch, m1, m2) {
        var codeblock = m1, nextChar = m2, end2 = "\n";
        codeblock = showdown2.subParser("outdent")(codeblock, options, globals);
        codeblock = showdown2.subParser("encodeCode")(codeblock, options, globals);
        codeblock = showdown2.subParser("detab")(codeblock, options, globals);
        codeblock = codeblock.replace(/^\n+/g, "");
        codeblock = codeblock.replace(/\n+$/g, "");
        if (options.omitExtraWLInCodeBlocks) {
          end2 = "";
        }
        codeblock = "<pre><code>" + codeblock + end2 + "</code></pre>";
        return showdown2.subParser("hashBlock")(codeblock, options, globals) + nextChar;
      });
      text = text.replace(/¨0/, "");
      text = globals.converter._dispatch("codeBlocks.after", text, options, globals);
      return text;
    });
    showdown2.subParser("codeSpans", function(text, options, globals) {
      text = globals.converter._dispatch("codeSpans.before", text, options, globals);
      if (typeof text === "undefined") {
        text = "";
      }
      text = text.replace(
        /(^|[^\\])(`+)([^\r]*?[^`])\2(?!`)/gm,
        function(wholeMatch, m1, m2, m3) {
          var c2 = m3;
          c2 = c2.replace(/^([ \t]*)/g, "");
          c2 = c2.replace(/[ \t]*$/g, "");
          c2 = showdown2.subParser("encodeCode")(c2, options, globals);
          c2 = m1 + "<code>" + c2 + "</code>";
          c2 = showdown2.subParser("hashHTMLSpans")(c2, options, globals);
          return c2;
        }
      );
      text = globals.converter._dispatch("codeSpans.after", text, options, globals);
      return text;
    });
    showdown2.subParser("completeHTMLDocument", function(text, options, globals) {
      if (!options.completeHTMLDocument) {
        return text;
      }
      text = globals.converter._dispatch("completeHTMLDocument.before", text, options, globals);
      var doctype = "html", doctypeParsed = "<!DOCTYPE HTML>\n", title = "", charset = '<meta charset="utf-8">\n', lang = "", metadata = "";
      if (typeof globals.metadata.parsed.doctype !== "undefined") {
        doctypeParsed = "<!DOCTYPE " + globals.metadata.parsed.doctype + ">\n";
        doctype = globals.metadata.parsed.doctype.toString().toLowerCase();
        if (doctype === "html" || doctype === "html5") {
          charset = '<meta charset="utf-8">';
        }
      }
      for (var meta in globals.metadata.parsed) {
        if (globals.metadata.parsed.hasOwnProperty(meta)) {
          switch (meta.toLowerCase()) {
            case "doctype":
              break;
            case "title":
              title = "<title>" + globals.metadata.parsed.title + "</title>\n";
              break;
            case "charset":
              if (doctype === "html" || doctype === "html5") {
                charset = '<meta charset="' + globals.metadata.parsed.charset + '">\n';
              } else {
                charset = '<meta name="charset" content="' + globals.metadata.parsed.charset + '">\n';
              }
              break;
            case "language":
            case "lang":
              lang = ' lang="' + globals.metadata.parsed[meta] + '"';
              metadata += '<meta name="' + meta + '" content="' + globals.metadata.parsed[meta] + '">\n';
              break;
            default:
              metadata += '<meta name="' + meta + '" content="' + globals.metadata.parsed[meta] + '">\n';
          }
        }
      }
      text = doctypeParsed + "<html" + lang + ">\n<head>\n" + title + charset + metadata + "</head>\n<body>\n" + text.trim() + "\n</body>\n</html>";
      text = globals.converter._dispatch("completeHTMLDocument.after", text, options, globals);
      return text;
    });
    showdown2.subParser("detab", function(text, options, globals) {
      text = globals.converter._dispatch("detab.before", text, options, globals);
      text = text.replace(/\t(?=\t)/g, "    ");
      text = text.replace(/\t/g, "¨A¨B");
      text = text.replace(/¨B(.+?)¨A/g, function(wholeMatch, m1) {
        var leadingText = m1, numSpaces = 4 - leadingText.length % 4;
        for (var i2 = 0; i2 < numSpaces; i2++) {
          leadingText += " ";
        }
        return leadingText;
      });
      text = text.replace(/¨A/g, "    ");
      text = text.replace(/¨B/g, "");
      text = globals.converter._dispatch("detab.after", text, options, globals);
      return text;
    });
    showdown2.subParser("ellipsis", function(text, options, globals) {
      if (!options.ellipsis) {
        return text;
      }
      text = globals.converter._dispatch("ellipsis.before", text, options, globals);
      text = text.replace(/\.\.\./g, "…");
      text = globals.converter._dispatch("ellipsis.after", text, options, globals);
      return text;
    });
    showdown2.subParser("emoji", function(text, options, globals) {
      if (!options.emoji) {
        return text;
      }
      text = globals.converter._dispatch("emoji.before", text, options, globals);
      var emojiRgx = /:([\S]+?):/g;
      text = text.replace(emojiRgx, function(wm, emojiCode) {
        if (showdown2.helper.emojis.hasOwnProperty(emojiCode)) {
          return showdown2.helper.emojis[emojiCode];
        }
        return wm;
      });
      text = globals.converter._dispatch("emoji.after", text, options, globals);
      return text;
    });
    showdown2.subParser("encodeAmpsAndAngles", function(text, options, globals) {
      text = globals.converter._dispatch("encodeAmpsAndAngles.before", text, options, globals);
      text = text.replace(/&(?!#?[xX]?(?:[0-9a-fA-F]+|\w+);)/g, "&amp;");
      text = text.replace(/<(?![a-z\/?$!])/gi, "&lt;");
      text = text.replace(/</g, "&lt;");
      text = text.replace(/>/g, "&gt;");
      text = globals.converter._dispatch("encodeAmpsAndAngles.after", text, options, globals);
      return text;
    });
    showdown2.subParser("encodeBackslashEscapes", function(text, options, globals) {
      text = globals.converter._dispatch("encodeBackslashEscapes.before", text, options, globals);
      text = text.replace(/\\(\\)/g, showdown2.helper.escapeCharactersCallback);
      text = text.replace(/\\([`*_{}\[\]()>#+.!~=|:-])/g, showdown2.helper.escapeCharactersCallback);
      text = globals.converter._dispatch("encodeBackslashEscapes.after", text, options, globals);
      return text;
    });
    showdown2.subParser("encodeCode", function(text, options, globals) {
      text = globals.converter._dispatch("encodeCode.before", text, options, globals);
      text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/([*_{}\[\]\\=~-])/g, showdown2.helper.escapeCharactersCallback);
      text = globals.converter._dispatch("encodeCode.after", text, options, globals);
      return text;
    });
    showdown2.subParser("escapeSpecialCharsWithinTagAttributes", function(text, options, globals) {
      text = globals.converter._dispatch("escapeSpecialCharsWithinTagAttributes.before", text, options, globals);
      var tags = /<\/?[a-z\d_:-]+(?:[\s]+[\s\S]+?)?>/gi, comments = /<!(--(?:(?:[^>-]|-[^>])(?:[^-]|-[^-])*)--)>/gi;
      text = text.replace(tags, function(wholeMatch) {
        return wholeMatch.replace(/(.)<\/?code>(?=.)/g, "$1`").replace(/([\\`*_~=|])/g, showdown2.helper.escapeCharactersCallback);
      });
      text = text.replace(comments, function(wholeMatch) {
        return wholeMatch.replace(/([\\`*_~=|])/g, showdown2.helper.escapeCharactersCallback);
      });
      text = globals.converter._dispatch("escapeSpecialCharsWithinTagAttributes.after", text, options, globals);
      return text;
    });
    showdown2.subParser("githubCodeBlocks", function(text, options, globals) {
      if (!options.ghCodeBlocks) {
        return text;
      }
      text = globals.converter._dispatch("githubCodeBlocks.before", text, options, globals);
      text += "¨0";
      text = text.replace(/(?:^|\n)(?: {0,3})(```+|~~~+)(?: *)([^\s`~]*)\n([\s\S]*?)\n(?: {0,3})\1/g, function(wholeMatch, delim, language, codeblock) {
        var end2 = options.omitExtraWLInCodeBlocks ? "" : "\n";
        codeblock = showdown2.subParser("encodeCode")(codeblock, options, globals);
        codeblock = showdown2.subParser("detab")(codeblock, options, globals);
        codeblock = codeblock.replace(/^\n+/g, "");
        codeblock = codeblock.replace(/\n+$/g, "");
        codeblock = "<pre><code" + (language ? ' class="' + language + " language-" + language + '"' : "") + ">" + codeblock + end2 + "</code></pre>";
        codeblock = showdown2.subParser("hashBlock")(codeblock, options, globals);
        return "\n\n¨G" + (globals.ghCodeBlocks.push({ text: wholeMatch, codeblock }) - 1) + "G\n\n";
      });
      text = text.replace(/¨0/, "");
      return globals.converter._dispatch("githubCodeBlocks.after", text, options, globals);
    });
    showdown2.subParser("hashBlock", function(text, options, globals) {
      text = globals.converter._dispatch("hashBlock.before", text, options, globals);
      text = text.replace(/(^\n+|\n+$)/g, "");
      text = "\n\n¨K" + (globals.gHtmlBlocks.push(text) - 1) + "K\n\n";
      text = globals.converter._dispatch("hashBlock.after", text, options, globals);
      return text;
    });
    showdown2.subParser("hashCodeTags", function(text, options, globals) {
      text = globals.converter._dispatch("hashCodeTags.before", text, options, globals);
      var repFunc = function(wholeMatch, match, left2, right2) {
        var codeblock = left2 + showdown2.subParser("encodeCode")(match, options, globals) + right2;
        return "¨C" + (globals.gHtmlSpans.push(codeblock) - 1) + "C";
      };
      text = showdown2.helper.replaceRecursiveRegExp(text, repFunc, "<code\\b[^>]*>", "</code>", "gim");
      text = globals.converter._dispatch("hashCodeTags.after", text, options, globals);
      return text;
    });
    showdown2.subParser("hashElement", function(text, options, globals) {
      return function(wholeMatch, m1) {
        var blockText = m1;
        blockText = blockText.replace(/\n\n/g, "\n");
        blockText = blockText.replace(/^\n/, "");
        blockText = blockText.replace(/\n+$/g, "");
        blockText = "\n\n¨K" + (globals.gHtmlBlocks.push(blockText) - 1) + "K\n\n";
        return blockText;
      };
    });
    showdown2.subParser("hashHTMLBlocks", function(text, options, globals) {
      text = globals.converter._dispatch("hashHTMLBlocks.before", text, options, globals);
      var blockTags = [
        "pre",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "table",
        "dl",
        "ol",
        "ul",
        "script",
        "noscript",
        "form",
        "fieldset",
        "iframe",
        "math",
        "style",
        "section",
        "header",
        "footer",
        "nav",
        "article",
        "aside",
        "address",
        "audio",
        "canvas",
        "figure",
        "hgroup",
        "output",
        "video",
        "p"
      ], repFunc = function(wholeMatch, match, left2, right2) {
        var txt = wholeMatch;
        if (left2.search(/\bmarkdown\b/) !== -1) {
          txt = left2 + globals.converter.makeHtml(match) + right2;
        }
        return "\n\n¨K" + (globals.gHtmlBlocks.push(txt) - 1) + "K\n\n";
      };
      if (options.backslashEscapesHTMLTags) {
        text = text.replace(/\\<(\/?[^>]+?)>/g, function(wm, inside) {
          return "&lt;" + inside + "&gt;";
        });
      }
      for (var i2 = 0; i2 < blockTags.length; ++i2) {
        var opTagPos, rgx1 = new RegExp("^ {0,3}(<" + blockTags[i2] + "\\b[^>]*>)", "im"), patLeft = "<" + blockTags[i2] + "\\b[^>]*>", patRight = "</" + blockTags[i2] + ">";
        while ((opTagPos = showdown2.helper.regexIndexOf(text, rgx1)) !== -1) {
          var subTexts = showdown2.helper.splitAtIndex(text, opTagPos), newSubText1 = showdown2.helper.replaceRecursiveRegExp(subTexts[1], repFunc, patLeft, patRight, "im");
          if (newSubText1 === subTexts[1]) {
            break;
          }
          text = subTexts[0].concat(newSubText1);
        }
      }
      text = text.replace(
        /(\n {0,3}(<(hr)\b([^<>])*?\/?>)[ \t]*(?=\n{2,}))/g,
        showdown2.subParser("hashElement")(text, options, globals)
      );
      text = showdown2.helper.replaceRecursiveRegExp(text, function(txt) {
        return "\n\n¨K" + (globals.gHtmlBlocks.push(txt) - 1) + "K\n\n";
      }, "^ {0,3}<!--", "-->", "gm");
      text = text.replace(
        /(?:\n\n)( {0,3}(?:<([?%])[^\r]*?\2>)[ \t]*(?=\n{2,}))/g,
        showdown2.subParser("hashElement")(text, options, globals)
      );
      text = globals.converter._dispatch("hashHTMLBlocks.after", text, options, globals);
      return text;
    });
    showdown2.subParser("hashHTMLSpans", function(text, options, globals) {
      text = globals.converter._dispatch("hashHTMLSpans.before", text, options, globals);
      function hashHTMLSpan(html) {
        return "¨C" + (globals.gHtmlSpans.push(html) - 1) + "C";
      }
      text = text.replace(/<[^>]+?\/>/gi, function(wm) {
        return hashHTMLSpan(wm);
      });
      text = text.replace(/<([^>]+?)>[\s\S]*?<\/\1>/g, function(wm) {
        return hashHTMLSpan(wm);
      });
      text = text.replace(/<([^>]+?)\s[^>]+?>[\s\S]*?<\/\1>/g, function(wm) {
        return hashHTMLSpan(wm);
      });
      text = text.replace(/<[^>]+?>/gi, function(wm) {
        return hashHTMLSpan(wm);
      });
      text = globals.converter._dispatch("hashHTMLSpans.after", text, options, globals);
      return text;
    });
    showdown2.subParser("unhashHTMLSpans", function(text, options, globals) {
      text = globals.converter._dispatch("unhashHTMLSpans.before", text, options, globals);
      for (var i2 = 0; i2 < globals.gHtmlSpans.length; ++i2) {
        var repText = globals.gHtmlSpans[i2], limit = 0;
        while (/¨C(\d+)C/.test(repText)) {
          var num = RegExp.$1;
          repText = repText.replace("¨C" + num + "C", globals.gHtmlSpans[num]);
          if (limit === 10) {
            console.error("maximum nesting of 10 spans reached!!!");
            break;
          }
          ++limit;
        }
        text = text.replace("¨C" + i2 + "C", repText);
      }
      text = globals.converter._dispatch("unhashHTMLSpans.after", text, options, globals);
      return text;
    });
    showdown2.subParser("hashPreCodeTags", function(text, options, globals) {
      text = globals.converter._dispatch("hashPreCodeTags.before", text, options, globals);
      var repFunc = function(wholeMatch, match, left2, right2) {
        var codeblock = left2 + showdown2.subParser("encodeCode")(match, options, globals) + right2;
        return "\n\n¨G" + (globals.ghCodeBlocks.push({ text: wholeMatch, codeblock }) - 1) + "G\n\n";
      };
      text = showdown2.helper.replaceRecursiveRegExp(text, repFunc, "^ {0,3}<pre\\b[^>]*>\\s*<code\\b[^>]*>", "^ {0,3}</code>\\s*</pre>", "gim");
      text = globals.converter._dispatch("hashPreCodeTags.after", text, options, globals);
      return text;
    });
    showdown2.subParser("headers", function(text, options, globals) {
      text = globals.converter._dispatch("headers.before", text, options, globals);
      var headerLevelStart = isNaN(parseInt(options.headerLevelStart)) ? 1 : parseInt(options.headerLevelStart), setextRegexH1 = options.smoothLivePreview ? /^(.+)[ \t]*\n={2,}[ \t]*\n+/gm : /^(.+)[ \t]*\n=+[ \t]*\n+/gm, setextRegexH2 = options.smoothLivePreview ? /^(.+)[ \t]*\n-{2,}[ \t]*\n+/gm : /^(.+)[ \t]*\n-+[ \t]*\n+/gm;
      text = text.replace(setextRegexH1, function(wholeMatch, m1) {
        var spanGamut = showdown2.subParser("spanGamut")(m1, options, globals), hID = options.noHeaderId ? "" : ' id="' + headerId(m1) + '"', hLevel = headerLevelStart, hashBlock = "<h" + hLevel + hID + ">" + spanGamut + "</h" + hLevel + ">";
        return showdown2.subParser("hashBlock")(hashBlock, options, globals);
      });
      text = text.replace(setextRegexH2, function(matchFound, m1) {
        var spanGamut = showdown2.subParser("spanGamut")(m1, options, globals), hID = options.noHeaderId ? "" : ' id="' + headerId(m1) + '"', hLevel = headerLevelStart + 1, hashBlock = "<h" + hLevel + hID + ">" + spanGamut + "</h" + hLevel + ">";
        return showdown2.subParser("hashBlock")(hashBlock, options, globals);
      });
      var atxStyle = options.requireSpaceBeforeHeadingText ? /^(#{1,6})[ \t]+(.+?)[ \t]*#*\n+/gm : /^(#{1,6})[ \t]*(.+?)[ \t]*#*\n+/gm;
      text = text.replace(atxStyle, function(wholeMatch, m1, m2) {
        var hText = m2;
        if (options.customizedHeaderId) {
          hText = m2.replace(/\s?\{([^{]+?)}\s*$/, "");
        }
        var span = showdown2.subParser("spanGamut")(hText, options, globals), hID = options.noHeaderId ? "" : ' id="' + headerId(m2) + '"', hLevel = headerLevelStart - 1 + m1.length, header = "<h" + hLevel + hID + ">" + span + "</h" + hLevel + ">";
        return showdown2.subParser("hashBlock")(header, options, globals);
      });
      function headerId(m2) {
        var title, prefix;
        if (options.customizedHeaderId) {
          var match = m2.match(/\{([^{]+?)}\s*$/);
          if (match && match[1]) {
            m2 = match[1];
          }
        }
        title = m2;
        if (showdown2.helper.isString(options.prefixHeaderId)) {
          prefix = options.prefixHeaderId;
        } else if (options.prefixHeaderId === true) {
          prefix = "section-";
        } else {
          prefix = "";
        }
        if (!options.rawPrefixHeaderId) {
          title = prefix + title;
        }
        if (options.ghCompatibleHeaderId) {
          title = title.replace(/ /g, "-").replace(/&amp;/g, "").replace(/¨T/g, "").replace(/¨D/g, "").replace(/[&+$,\/:;=?@"#{}|^¨~\[\]`\\*)(%.!'<>]/g, "").toLowerCase();
        } else if (options.rawHeaderId) {
          title = title.replace(/ /g, "-").replace(/&amp;/g, "&").replace(/¨T/g, "¨").replace(/¨D/g, "$").replace(/["']/g, "-").toLowerCase();
        } else {
          title = title.replace(/[^\w]/g, "").toLowerCase();
        }
        if (options.rawPrefixHeaderId) {
          title = prefix + title;
        }
        if (globals.hashLinkCounts[title]) {
          title = title + "-" + globals.hashLinkCounts[title]++;
        } else {
          globals.hashLinkCounts[title] = 1;
        }
        return title;
      }
      text = globals.converter._dispatch("headers.after", text, options, globals);
      return text;
    });
    showdown2.subParser("horizontalRule", function(text, options, globals) {
      text = globals.converter._dispatch("horizontalRule.before", text, options, globals);
      var key2 = showdown2.subParser("hashBlock")("<hr />", options, globals);
      text = text.replace(/^ {0,2}( ?-){3,}[ \t]*$/gm, key2);
      text = text.replace(/^ {0,2}( ?\*){3,}[ \t]*$/gm, key2);
      text = text.replace(/^ {0,2}( ?_){3,}[ \t]*$/gm, key2);
      text = globals.converter._dispatch("horizontalRule.after", text, options, globals);
      return text;
    });
    showdown2.subParser("images", function(text, options, globals) {
      text = globals.converter._dispatch("images.before", text, options, globals);
      var inlineRegExp = /!\[([^\]]*?)][ \t]*()\([ \t]?<?([\S]+?(?:\([\S]*?\)[\S]*?)?)>?(?: =([*\d]+[A-Za-z%]{0,4})x([*\d]+[A-Za-z%]{0,4}))?[ \t]*(?:(["'])([^"]*?)\6)?[ \t]?\)/g, crazyRegExp = /!\[([^\]]*?)][ \t]*()\([ \t]?<([^>]*)>(?: =([*\d]+[A-Za-z%]{0,4})x([*\d]+[A-Za-z%]{0,4}))?[ \t]*(?:(?:(["'])([^"]*?)\6))?[ \t]?\)/g, base64RegExp = /!\[([^\]]*?)][ \t]*()\([ \t]?<?(data:.+?\/.+?;base64,[A-Za-z0-9+/=\n]+?)>?(?: =([*\d]+[A-Za-z%]{0,4})x([*\d]+[A-Za-z%]{0,4}))?[ \t]*(?:(["'])([^"]*?)\6)?[ \t]?\)/g, referenceRegExp = /!\[([^\]]*?)] ?(?:\n *)?\[([\s\S]*?)]()()()()()/g, refShortcutRegExp = /!\[([^\[\]]+)]()()()()()/g;
      function writeImageTagBase64(wholeMatch, altText, linkId, url, width, height, m5, title) {
        url = url.replace(/\s/g, "");
        return writeImageTag(wholeMatch, altText, linkId, url, width, height, m5, title);
      }
      function writeImageTag(wholeMatch, altText, linkId, url, width, height, m5, title) {
        var gUrls = globals.gUrls, gTitles = globals.gTitles, gDims = globals.gDimensions;
        linkId = linkId.toLowerCase();
        if (!title) {
          title = "";
        }
        if (wholeMatch.search(/\(<?\s*>? ?(['"].*['"])?\)$/m) > -1) {
          url = "";
        } else if (url === "" || url === null) {
          if (linkId === "" || linkId === null) {
            linkId = altText.toLowerCase().replace(/ ?\n/g, " ");
          }
          url = "#" + linkId;
          if (!showdown2.helper.isUndefined(gUrls[linkId])) {
            url = gUrls[linkId];
            if (!showdown2.helper.isUndefined(gTitles[linkId])) {
              title = gTitles[linkId];
            }
            if (!showdown2.helper.isUndefined(gDims[linkId])) {
              width = gDims[linkId].width;
              height = gDims[linkId].height;
            }
          } else {
            return wholeMatch;
          }
        }
        altText = altText.replace(/"/g, "&quot;").replace(showdown2.helper.regexes.asteriskDashAndColon, showdown2.helper.escapeCharactersCallback);
        url = url.replace(showdown2.helper.regexes.asteriskDashAndColon, showdown2.helper.escapeCharactersCallback);
        var result = '<img src="' + url + '" alt="' + altText + '"';
        if (title && showdown2.helper.isString(title)) {
          title = title.replace(/"/g, "&quot;").replace(showdown2.helper.regexes.asteriskDashAndColon, showdown2.helper.escapeCharactersCallback);
          result += ' title="' + title + '"';
        }
        if (width && height) {
          width = width === "*" ? "auto" : width;
          height = height === "*" ? "auto" : height;
          result += ' width="' + width + '"';
          result += ' height="' + height + '"';
        }
        result += " />";
        return result;
      }
      text = text.replace(referenceRegExp, writeImageTag);
      text = text.replace(base64RegExp, writeImageTagBase64);
      text = text.replace(crazyRegExp, writeImageTag);
      text = text.replace(inlineRegExp, writeImageTag);
      text = text.replace(refShortcutRegExp, writeImageTag);
      text = globals.converter._dispatch("images.after", text, options, globals);
      return text;
    });
    showdown2.subParser("italicsAndBold", function(text, options, globals) {
      text = globals.converter._dispatch("italicsAndBold.before", text, options, globals);
      function parseInside(txt, left2, right2) {
        return left2 + txt + right2;
      }
      if (options.literalMidWordUnderscores) {
        text = text.replace(/\b___(\S[\s\S]*?)___\b/g, function(wm, txt) {
          return parseInside(txt, "<strong><em>", "</em></strong>");
        });
        text = text.replace(/\b__(\S[\s\S]*?)__\b/g, function(wm, txt) {
          return parseInside(txt, "<strong>", "</strong>");
        });
        text = text.replace(/\b_(\S[\s\S]*?)_\b/g, function(wm, txt) {
          return parseInside(txt, "<em>", "</em>");
        });
      } else {
        text = text.replace(/___(\S[\s\S]*?)___/g, function(wm, m2) {
          return /\S$/.test(m2) ? parseInside(m2, "<strong><em>", "</em></strong>") : wm;
        });
        text = text.replace(/__(\S[\s\S]*?)__/g, function(wm, m2) {
          return /\S$/.test(m2) ? parseInside(m2, "<strong>", "</strong>") : wm;
        });
        text = text.replace(/_([^\s_][\s\S]*?)_/g, function(wm, m2) {
          return /\S$/.test(m2) ? parseInside(m2, "<em>", "</em>") : wm;
        });
      }
      if (options.literalMidWordAsterisks) {
        text = text.replace(/([^*]|^)\B\*\*\*(\S[\s\S]*?)\*\*\*\B(?!\*)/g, function(wm, lead, txt) {
          return parseInside(txt, lead + "<strong><em>", "</em></strong>");
        });
        text = text.replace(/([^*]|^)\B\*\*(\S[\s\S]*?)\*\*\B(?!\*)/g, function(wm, lead, txt) {
          return parseInside(txt, lead + "<strong>", "</strong>");
        });
        text = text.replace(/([^*]|^)\B\*(\S[\s\S]*?)\*\B(?!\*)/g, function(wm, lead, txt) {
          return parseInside(txt, lead + "<em>", "</em>");
        });
      } else {
        text = text.replace(/\*\*\*(\S[\s\S]*?)\*\*\*/g, function(wm, m2) {
          return /\S$/.test(m2) ? parseInside(m2, "<strong><em>", "</em></strong>") : wm;
        });
        text = text.replace(/\*\*(\S[\s\S]*?)\*\*/g, function(wm, m2) {
          return /\S$/.test(m2) ? parseInside(m2, "<strong>", "</strong>") : wm;
        });
        text = text.replace(/\*([^\s*][\s\S]*?)\*/g, function(wm, m2) {
          return /\S$/.test(m2) ? parseInside(m2, "<em>", "</em>") : wm;
        });
      }
      text = globals.converter._dispatch("italicsAndBold.after", text, options, globals);
      return text;
    });
    showdown2.subParser("lists", function(text, options, globals) {
      function processListItems(listStr, trimTrailing) {
        globals.gListLevel++;
        listStr = listStr.replace(/\n{2,}$/, "\n");
        listStr += "¨0";
        var rgx = /(\n)?(^ {0,3})([*+-]|\d+[.])[ \t]+((\[(x|X| )?])?[ \t]*[^\r]+?(\n{1,2}))(?=\n*(¨0| {0,3}([*+-]|\d+[.])[ \t]+))/gm, isParagraphed = /\n[ \t]*\n(?!¨0)/.test(listStr);
        if (options.disableForced4SpacesIndentedSublists) {
          rgx = /(\n)?(^ {0,3})([*+-]|\d+[.])[ \t]+((\[(x|X| )?])?[ \t]*[^\r]+?(\n{1,2}))(?=\n*(¨0|\2([*+-]|\d+[.])[ \t]+))/gm;
        }
        listStr = listStr.replace(rgx, function(wholeMatch, m1, m2, m3, m4, taskbtn, checked) {
          checked = checked && checked.trim() !== "";
          var item = showdown2.subParser("outdent")(m4, options, globals), bulletStyle = "";
          if (taskbtn && options.tasklists) {
            bulletStyle = ' class="task-list-item" style="list-style-type: none;"';
            item = item.replace(/^[ \t]*\[(x|X| )?]/m, function() {
              var otp = '<input type="checkbox" disabled style="margin: 0px 0.35em 0.25em -1.6em; vertical-align: middle;"';
              if (checked) {
                otp += " checked";
              }
              otp += ">";
              return otp;
            });
          }
          item = item.replace(/^([-*+]|\d\.)[ \t]+[\S\n ]*/g, function(wm2) {
            return "¨A" + wm2;
          });
          if (m1 || item.search(/\n{2,}/) > -1) {
            item = showdown2.subParser("githubCodeBlocks")(item, options, globals);
            item = showdown2.subParser("blockGamut")(item, options, globals);
          } else {
            item = showdown2.subParser("lists")(item, options, globals);
            item = item.replace(/\n$/, "");
            item = showdown2.subParser("hashHTMLBlocks")(item, options, globals);
            item = item.replace(/\n\n+/g, "\n\n");
            if (isParagraphed) {
              item = showdown2.subParser("paragraphs")(item, options, globals);
            } else {
              item = showdown2.subParser("spanGamut")(item, options, globals);
            }
          }
          item = item.replace("¨A", "");
          item = "<li" + bulletStyle + ">" + item + "</li>\n";
          return item;
        });
        listStr = listStr.replace(/¨0/g, "");
        globals.gListLevel--;
        if (trimTrailing) {
          listStr = listStr.replace(/\s+$/, "");
        }
        return listStr;
      }
      function styleStartNumber(list, listType) {
        if (listType === "ol") {
          var res = list.match(/^ *(\d+)\./);
          if (res && res[1] !== "1") {
            return ' start="' + res[1] + '"';
          }
        }
        return "";
      }
      function parseConsecutiveLists(list, listType, trimTrailing) {
        var olRgx = options.disableForced4SpacesIndentedSublists ? /^ ?\d+\.[ \t]/gm : /^ {0,3}\d+\.[ \t]/gm, ulRgx = options.disableForced4SpacesIndentedSublists ? /^ ?[*+-][ \t]/gm : /^ {0,3}[*+-][ \t]/gm, counterRxg = listType === "ul" ? olRgx : ulRgx, result = "";
        if (list.search(counterRxg) !== -1) {
          (function parseCL(txt) {
            var pos2 = txt.search(counterRxg), style2 = styleStartNumber(list, listType);
            if (pos2 !== -1) {
              result += "\n\n<" + listType + style2 + ">\n" + processListItems(txt.slice(0, pos2), !!trimTrailing) + "</" + listType + ">\n";
              listType = listType === "ul" ? "ol" : "ul";
              counterRxg = listType === "ul" ? olRgx : ulRgx;
              parseCL(txt.slice(pos2));
            } else {
              result += "\n\n<" + listType + style2 + ">\n" + processListItems(txt, !!trimTrailing) + "</" + listType + ">\n";
            }
          })(list);
        } else {
          var style = styleStartNumber(list, listType);
          result = "\n\n<" + listType + style + ">\n" + processListItems(list, !!trimTrailing) + "</" + listType + ">\n";
        }
        return result;
      }
      text = globals.converter._dispatch("lists.before", text, options, globals);
      text += "¨0";
      if (globals.gListLevel) {
        text = text.replace(
          /^(( {0,3}([*+-]|\d+[.])[ \t]+)[^\r]+?(¨0|\n{2,}(?=\S)(?![ \t]*(?:[*+-]|\d+[.])[ \t]+)))/gm,
          function(wholeMatch, list, m2) {
            var listType = m2.search(/[*+-]/g) > -1 ? "ul" : "ol";
            return parseConsecutiveLists(list, listType, true);
          }
        );
      } else {
        text = text.replace(
          /(\n\n|^\n?)(( {0,3}([*+-]|\d+[.])[ \t]+)[^\r]+?(¨0|\n{2,}(?=\S)(?![ \t]*(?:[*+-]|\d+[.])[ \t]+)))/gm,
          function(wholeMatch, m1, list, m3) {
            var listType = m3.search(/[*+-]/g) > -1 ? "ul" : "ol";
            return parseConsecutiveLists(list, listType, false);
          }
        );
      }
      text = text.replace(/¨0/, "");
      text = globals.converter._dispatch("lists.after", text, options, globals);
      return text;
    });
    showdown2.subParser("metadata", function(text, options, globals) {
      if (!options.metadata) {
        return text;
      }
      text = globals.converter._dispatch("metadata.before", text, options, globals);
      function parseMetadataContents(content) {
        globals.metadata.raw = content;
        content = content.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
        content = content.replace(/\n {4}/g, " ");
        content.replace(/^([\S ]+): +([\s\S]+?)$/gm, function(wm, key2, value) {
          globals.metadata.parsed[key2] = value;
          return "";
        });
      }
      text = text.replace(/^\s*«««+(\S*?)\n([\s\S]+?)\n»»»+\n/, function(wholematch, format2, content) {
        parseMetadataContents(content);
        return "¨M";
      });
      text = text.replace(/^\s*---+(\S*?)\n([\s\S]+?)\n---+\n/, function(wholematch, format2, content) {
        if (format2) {
          globals.metadata.format = format2;
        }
        parseMetadataContents(content);
        return "¨M";
      });
      text = text.replace(/¨M/g, "");
      text = globals.converter._dispatch("metadata.after", text, options, globals);
      return text;
    });
    showdown2.subParser("outdent", function(text, options, globals) {
      text = globals.converter._dispatch("outdent.before", text, options, globals);
      text = text.replace(/^(\t|[ ]{1,4})/gm, "¨0");
      text = text.replace(/¨0/g, "");
      text = globals.converter._dispatch("outdent.after", text, options, globals);
      return text;
    });
    showdown2.subParser("paragraphs", function(text, options, globals) {
      text = globals.converter._dispatch("paragraphs.before", text, options, globals);
      text = text.replace(/^\n+/g, "");
      text = text.replace(/\n+$/g, "");
      var grafs = text.split(/\n{2,}/g), grafsOut = [], end2 = grafs.length;
      for (var i2 = 0; i2 < end2; i2++) {
        var str = grafs[i2];
        if (str.search(/¨(K|G)(\d+)\1/g) >= 0) {
          grafsOut.push(str);
        } else if (str.search(/\S/) >= 0) {
          str = showdown2.subParser("spanGamut")(str, options, globals);
          str = str.replace(/^([ \t]*)/g, "<p>");
          str += "</p>";
          grafsOut.push(str);
        }
      }
      end2 = grafsOut.length;
      for (i2 = 0; i2 < end2; i2++) {
        var blockText = "", grafsOutIt = grafsOut[i2], codeFlag = false;
        while (/¨(K|G)(\d+)\1/.test(grafsOutIt)) {
          var delim = RegExp.$1, num = RegExp.$2;
          if (delim === "K") {
            blockText = globals.gHtmlBlocks[num];
          } else {
            if (codeFlag) {
              blockText = showdown2.subParser("encodeCode")(globals.ghCodeBlocks[num].text, options, globals);
            } else {
              blockText = globals.ghCodeBlocks[num].codeblock;
            }
          }
          blockText = blockText.replace(/\$/g, "$$$$");
          grafsOutIt = grafsOutIt.replace(/(\n\n)?¨(K|G)\d+\2(\n\n)?/, blockText);
          if (/^<pre\b[^>]*>\s*<code\b[^>]*>/.test(grafsOutIt)) {
            codeFlag = true;
          }
        }
        grafsOut[i2] = grafsOutIt;
      }
      text = grafsOut.join("\n");
      text = text.replace(/^\n+/g, "");
      text = text.replace(/\n+$/g, "");
      return globals.converter._dispatch("paragraphs.after", text, options, globals);
    });
    showdown2.subParser("runExtension", function(ext, text, options, globals) {
      if (ext.filter) {
        text = ext.filter(text, globals.converter, options);
      } else if (ext.regex) {
        var re = ext.regex;
        if (!(re instanceof RegExp)) {
          re = new RegExp(re, "g");
        }
        text = text.replace(re, ext.replace);
      }
      return text;
    });
    showdown2.subParser("spanGamut", function(text, options, globals) {
      text = globals.converter._dispatch("spanGamut.before", text, options, globals);
      text = showdown2.subParser("codeSpans")(text, options, globals);
      text = showdown2.subParser("escapeSpecialCharsWithinTagAttributes")(text, options, globals);
      text = showdown2.subParser("encodeBackslashEscapes")(text, options, globals);
      text = showdown2.subParser("images")(text, options, globals);
      text = showdown2.subParser("anchors")(text, options, globals);
      text = showdown2.subParser("autoLinks")(text, options, globals);
      text = showdown2.subParser("simplifiedAutoLinks")(text, options, globals);
      text = showdown2.subParser("emoji")(text, options, globals);
      text = showdown2.subParser("underline")(text, options, globals);
      text = showdown2.subParser("italicsAndBold")(text, options, globals);
      text = showdown2.subParser("strikethrough")(text, options, globals);
      text = showdown2.subParser("ellipsis")(text, options, globals);
      text = showdown2.subParser("hashHTMLSpans")(text, options, globals);
      text = showdown2.subParser("encodeAmpsAndAngles")(text, options, globals);
      if (options.simpleLineBreaks) {
        if (!/\n\n¨K/.test(text)) {
          text = text.replace(/\n+/g, "<br />\n");
        }
      } else {
        text = text.replace(/  +\n/g, "<br />\n");
      }
      text = globals.converter._dispatch("spanGamut.after", text, options, globals);
      return text;
    });
    showdown2.subParser("strikethrough", function(text, options, globals) {
      function parseInside(txt) {
        if (options.simplifiedAutoLink) {
          txt = showdown2.subParser("simplifiedAutoLinks")(txt, options, globals);
        }
        return "<del>" + txt + "</del>";
      }
      if (options.strikethrough) {
        text = globals.converter._dispatch("strikethrough.before", text, options, globals);
        text = text.replace(/(?:~){2}([\s\S]+?)(?:~){2}/g, function(wm, txt) {
          return parseInside(txt);
        });
        text = globals.converter._dispatch("strikethrough.after", text, options, globals);
      }
      return text;
    });
    showdown2.subParser("stripLinkDefinitions", function(text, options, globals) {
      var regex = /^ {0,3}\[([^\]]+)]:[ \t]*\n?[ \t]*<?([^>\s]+)>?(?: =([*\d]+[A-Za-z%]{0,4})x([*\d]+[A-Za-z%]{0,4}))?[ \t]*\n?[ \t]*(?:(\n*)["|'(](.+?)["|')][ \t]*)?(?:\n+|(?=¨0))/gm, base64Regex = /^ {0,3}\[([^\]]+)]:[ \t]*\n?[ \t]*<?(data:.+?\/.+?;base64,[A-Za-z0-9+/=\n]+?)>?(?: =([*\d]+[A-Za-z%]{0,4})x([*\d]+[A-Za-z%]{0,4}))?[ \t]*\n?[ \t]*(?:(\n*)["|'(](.+?)["|')][ \t]*)?(?:\n\n|(?=¨0)|(?=\n\[))/gm;
      text += "¨0";
      var replaceFunc = function(wholeMatch, linkId, url, width, height, blankLines, title) {
        linkId = linkId.toLowerCase();
        if (text.toLowerCase().split(linkId).length - 1 < 2) {
          return wholeMatch;
        }
        if (url.match(/^data:.+?\/.+?;base64,/)) {
          globals.gUrls[linkId] = url.replace(/\s/g, "");
        } else {
          globals.gUrls[linkId] = showdown2.subParser("encodeAmpsAndAngles")(url, options, globals);
        }
        if (blankLines) {
          return blankLines + title;
        } else {
          if (title) {
            globals.gTitles[linkId] = title.replace(/"|'/g, "&quot;");
          }
          if (options.parseImgDimensions && width && height) {
            globals.gDimensions[linkId] = {
              width,
              height
            };
          }
        }
        return "";
      };
      text = text.replace(base64Regex, replaceFunc);
      text = text.replace(regex, replaceFunc);
      text = text.replace(/¨0/, "");
      return text;
    });
    showdown2.subParser("tables", function(text, options, globals) {
      if (!options.tables) {
        return text;
      }
      var tableRgx = /^ {0,3}\|?.+\|.+\n {0,3}\|?[ \t]*:?[ \t]*(?:[-=]){2,}[ \t]*:?[ \t]*\|[ \t]*:?[ \t]*(?:[-=]){2,}[\s\S]+?(?:\n\n|¨0)/gm, singeColTblRgx = /^ {0,3}\|.+\|[ \t]*\n {0,3}\|[ \t]*:?[ \t]*(?:[-=]){2,}[ \t]*:?[ \t]*\|[ \t]*\n( {0,3}\|.+\|[ \t]*\n)*(?:\n|¨0)/gm;
      function parseStyles(sLine) {
        if (/^:[ \t]*--*$/.test(sLine)) {
          return ' style="text-align:left;"';
        } else if (/^--*[ \t]*:[ \t]*$/.test(sLine)) {
          return ' style="text-align:right;"';
        } else if (/^:[ \t]*--*[ \t]*:$/.test(sLine)) {
          return ' style="text-align:center;"';
        } else {
          return "";
        }
      }
      function parseHeaders(header, style) {
        var id = "";
        header = header.trim();
        if (options.tablesHeaderId || options.tableHeaderId) {
          id = ' id="' + header.replace(/ /g, "_").toLowerCase() + '"';
        }
        header = showdown2.subParser("spanGamut")(header, options, globals);
        return "<th" + id + style + ">" + header + "</th>\n";
      }
      function parseCells(cell, style) {
        var subText = showdown2.subParser("spanGamut")(cell, options, globals);
        return "<td" + style + ">" + subText + "</td>\n";
      }
      function buildTable(headers, cells) {
        var tb = "<table>\n<thead>\n<tr>\n", tblLgn = headers.length;
        for (var i2 = 0; i2 < tblLgn; ++i2) {
          tb += headers[i2];
        }
        tb += "</tr>\n</thead>\n<tbody>\n";
        for (i2 = 0; i2 < cells.length; ++i2) {
          tb += "<tr>\n";
          for (var ii = 0; ii < tblLgn; ++ii) {
            tb += cells[i2][ii];
          }
          tb += "</tr>\n";
        }
        tb += "</tbody>\n</table>\n";
        return tb;
      }
      function parseTable(rawTable) {
        var i2, tableLines = rawTable.split("\n");
        for (i2 = 0; i2 < tableLines.length; ++i2) {
          if (/^ {0,3}\|/.test(tableLines[i2])) {
            tableLines[i2] = tableLines[i2].replace(/^ {0,3}\|/, "");
          }
          if (/\|[ \t]*$/.test(tableLines[i2])) {
            tableLines[i2] = tableLines[i2].replace(/\|[ \t]*$/, "");
          }
          tableLines[i2] = showdown2.subParser("codeSpans")(tableLines[i2], options, globals);
        }
        var rawHeaders = tableLines[0].split("|").map(function(s2) {
          return s2.trim();
        }), rawStyles = tableLines[1].split("|").map(function(s2) {
          return s2.trim();
        }), rawCells = [], headers = [], styles = [], cells = [];
        tableLines.shift();
        tableLines.shift();
        for (i2 = 0; i2 < tableLines.length; ++i2) {
          if (tableLines[i2].trim() === "") {
            continue;
          }
          rawCells.push(
            tableLines[i2].split("|").map(function(s2) {
              return s2.trim();
            })
          );
        }
        if (rawHeaders.length < rawStyles.length) {
          return rawTable;
        }
        for (i2 = 0; i2 < rawStyles.length; ++i2) {
          styles.push(parseStyles(rawStyles[i2]));
        }
        for (i2 = 0; i2 < rawHeaders.length; ++i2) {
          if (showdown2.helper.isUndefined(styles[i2])) {
            styles[i2] = "";
          }
          headers.push(parseHeaders(rawHeaders[i2], styles[i2]));
        }
        for (i2 = 0; i2 < rawCells.length; ++i2) {
          var row = [];
          for (var ii = 0; ii < headers.length; ++ii) {
            if (showdown2.helper.isUndefined(rawCells[i2][ii])) ;
            row.push(parseCells(rawCells[i2][ii], styles[ii]));
          }
          cells.push(row);
        }
        return buildTable(headers, cells);
      }
      text = globals.converter._dispatch("tables.before", text, options, globals);
      text = text.replace(/\\(\|)/g, showdown2.helper.escapeCharactersCallback);
      text = text.replace(tableRgx, parseTable);
      text = text.replace(singeColTblRgx, parseTable);
      text = globals.converter._dispatch("tables.after", text, options, globals);
      return text;
    });
    showdown2.subParser("underline", function(text, options, globals) {
      if (!options.underline) {
        return text;
      }
      text = globals.converter._dispatch("underline.before", text, options, globals);
      if (options.literalMidWordUnderscores) {
        text = text.replace(/\b___(\S[\s\S]*?)___\b/g, function(wm, txt) {
          return "<u>" + txt + "</u>";
        });
        text = text.replace(/\b__(\S[\s\S]*?)__\b/g, function(wm, txt) {
          return "<u>" + txt + "</u>";
        });
      } else {
        text = text.replace(/___(\S[\s\S]*?)___/g, function(wm, m2) {
          return /\S$/.test(m2) ? "<u>" + m2 + "</u>" : wm;
        });
        text = text.replace(/__(\S[\s\S]*?)__/g, function(wm, m2) {
          return /\S$/.test(m2) ? "<u>" + m2 + "</u>" : wm;
        });
      }
      text = text.replace(/(_)/g, showdown2.helper.escapeCharactersCallback);
      text = globals.converter._dispatch("underline.after", text, options, globals);
      return text;
    });
    showdown2.subParser("unescapeSpecialChars", function(text, options, globals) {
      text = globals.converter._dispatch("unescapeSpecialChars.before", text, options, globals);
      text = text.replace(/¨E(\d+)E/g, function(wholeMatch, m1) {
        var charCodeToReplace = parseInt(m1);
        return String.fromCharCode(charCodeToReplace);
      });
      text = globals.converter._dispatch("unescapeSpecialChars.after", text, options, globals);
      return text;
    });
    showdown2.subParser("makeMarkdown.blockquote", function(node, globals) {
      var txt = "";
      if (node.hasChildNodes()) {
        var children = node.childNodes, childrenLength = children.length;
        for (var i2 = 0; i2 < childrenLength; ++i2) {
          var innerTxt = showdown2.subParser("makeMarkdown.node")(children[i2], globals);
          if (innerTxt === "") {
            continue;
          }
          txt += innerTxt;
        }
      }
      txt = txt.trim();
      txt = "> " + txt.split("\n").join("\n> ");
      return txt;
    });
    showdown2.subParser("makeMarkdown.codeBlock", function(node, globals) {
      var lang = node.getAttribute("language"), num = node.getAttribute("precodenum");
      return "```" + lang + "\n" + globals.preList[num] + "\n```";
    });
    showdown2.subParser("makeMarkdown.codeSpan", function(node) {
      return "`" + node.innerHTML + "`";
    });
    showdown2.subParser("makeMarkdown.emphasis", function(node, globals) {
      var txt = "";
      if (node.hasChildNodes()) {
        txt += "*";
        var children = node.childNodes, childrenLength = children.length;
        for (var i2 = 0; i2 < childrenLength; ++i2) {
          txt += showdown2.subParser("makeMarkdown.node")(children[i2], globals);
        }
        txt += "*";
      }
      return txt;
    });
    showdown2.subParser("makeMarkdown.header", function(node, globals, headerLevel) {
      var headerMark = new Array(headerLevel + 1).join("#"), txt = "";
      if (node.hasChildNodes()) {
        txt = headerMark + " ";
        var children = node.childNodes, childrenLength = children.length;
        for (var i2 = 0; i2 < childrenLength; ++i2) {
          txt += showdown2.subParser("makeMarkdown.node")(children[i2], globals);
        }
      }
      return txt;
    });
    showdown2.subParser("makeMarkdown.hr", function() {
      return "---";
    });
    showdown2.subParser("makeMarkdown.image", function(node) {
      var txt = "";
      if (node.hasAttribute("src")) {
        txt += "![" + node.getAttribute("alt") + "](";
        txt += "<" + node.getAttribute("src") + ">";
        if (node.hasAttribute("width") && node.hasAttribute("height")) {
          txt += " =" + node.getAttribute("width") + "x" + node.getAttribute("height");
        }
        if (node.hasAttribute("title")) {
          txt += ' "' + node.getAttribute("title") + '"';
        }
        txt += ")";
      }
      return txt;
    });
    showdown2.subParser("makeMarkdown.links", function(node, globals) {
      var txt = "";
      if (node.hasChildNodes() && node.hasAttribute("href")) {
        var children = node.childNodes, childrenLength = children.length;
        txt = "[";
        for (var i2 = 0; i2 < childrenLength; ++i2) {
          txt += showdown2.subParser("makeMarkdown.node")(children[i2], globals);
        }
        txt += "](";
        txt += "<" + node.getAttribute("href") + ">";
        if (node.hasAttribute("title")) {
          txt += ' "' + node.getAttribute("title") + '"';
        }
        txt += ")";
      }
      return txt;
    });
    showdown2.subParser("makeMarkdown.list", function(node, globals, type) {
      var txt = "";
      if (!node.hasChildNodes()) {
        return "";
      }
      var listItems = node.childNodes, listItemsLenght = listItems.length, listNum = node.getAttribute("start") || 1;
      for (var i2 = 0; i2 < listItemsLenght; ++i2) {
        if (typeof listItems[i2].tagName === "undefined" || listItems[i2].tagName.toLowerCase() !== "li") {
          continue;
        }
        var bullet = "";
        if (type === "ol") {
          bullet = listNum.toString() + ". ";
        } else {
          bullet = "- ";
        }
        txt += bullet + showdown2.subParser("makeMarkdown.listItem")(listItems[i2], globals);
        ++listNum;
      }
      txt += "\n<!-- -->\n";
      return txt.trim();
    });
    showdown2.subParser("makeMarkdown.listItem", function(node, globals) {
      var listItemTxt = "";
      var children = node.childNodes, childrenLenght = children.length;
      for (var i2 = 0; i2 < childrenLenght; ++i2) {
        listItemTxt += showdown2.subParser("makeMarkdown.node")(children[i2], globals);
      }
      if (!/\n$/.test(listItemTxt)) {
        listItemTxt += "\n";
      } else {
        listItemTxt = listItemTxt.split("\n").join("\n    ").replace(/^ {4}$/gm, "").replace(/\n\n+/g, "\n\n");
      }
      return listItemTxt;
    });
    showdown2.subParser("makeMarkdown.node", function(node, globals, spansOnly) {
      spansOnly = spansOnly || false;
      var txt = "";
      if (node.nodeType === 3) {
        return showdown2.subParser("makeMarkdown.txt")(node, globals);
      }
      if (node.nodeType === 8) {
        return "<!--" + node.data + "-->\n\n";
      }
      if (node.nodeType !== 1) {
        return "";
      }
      var tagName = node.tagName.toLowerCase();
      switch (tagName) {
        case "h1":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.header")(node, globals, 1) + "\n\n";
          }
          break;
        case "h2":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.header")(node, globals, 2) + "\n\n";
          }
          break;
        case "h3":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.header")(node, globals, 3) + "\n\n";
          }
          break;
        case "h4":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.header")(node, globals, 4) + "\n\n";
          }
          break;
        case "h5":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.header")(node, globals, 5) + "\n\n";
          }
          break;
        case "h6":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.header")(node, globals, 6) + "\n\n";
          }
          break;
        case "p":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.paragraph")(node, globals) + "\n\n";
          }
          break;
        case "blockquote":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.blockquote")(node, globals) + "\n\n";
          }
          break;
        case "hr":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.hr")(node, globals) + "\n\n";
          }
          break;
        case "ol":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.list")(node, globals, "ol") + "\n\n";
          }
          break;
        case "ul":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.list")(node, globals, "ul") + "\n\n";
          }
          break;
        case "precode":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.codeBlock")(node, globals) + "\n\n";
          }
          break;
        case "pre":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.pre")(node, globals) + "\n\n";
          }
          break;
        case "table":
          if (!spansOnly) {
            txt = showdown2.subParser("makeMarkdown.table")(node, globals) + "\n\n";
          }
          break;
        case "code":
          txt = showdown2.subParser("makeMarkdown.codeSpan")(node, globals);
          break;
        case "em":
        case "i":
          txt = showdown2.subParser("makeMarkdown.emphasis")(node, globals);
          break;
        case "strong":
        case "b":
          txt = showdown2.subParser("makeMarkdown.strong")(node, globals);
          break;
        case "del":
          txt = showdown2.subParser("makeMarkdown.strikethrough")(node, globals);
          break;
        case "a":
          txt = showdown2.subParser("makeMarkdown.links")(node, globals);
          break;
        case "img":
          txt = showdown2.subParser("makeMarkdown.image")(node, globals);
          break;
        default:
          txt = node.outerHTML + "\n\n";
      }
      return txt;
    });
    showdown2.subParser("makeMarkdown.paragraph", function(node, globals) {
      var txt = "";
      if (node.hasChildNodes()) {
        var children = node.childNodes, childrenLength = children.length;
        for (var i2 = 0; i2 < childrenLength; ++i2) {
          txt += showdown2.subParser("makeMarkdown.node")(children[i2], globals);
        }
      }
      txt = txt.trim();
      return txt;
    });
    showdown2.subParser("makeMarkdown.pre", function(node, globals) {
      var num = node.getAttribute("prenum");
      return "<pre>" + globals.preList[num] + "</pre>";
    });
    showdown2.subParser("makeMarkdown.strikethrough", function(node, globals) {
      var txt = "";
      if (node.hasChildNodes()) {
        txt += "~~";
        var children = node.childNodes, childrenLength = children.length;
        for (var i2 = 0; i2 < childrenLength; ++i2) {
          txt += showdown2.subParser("makeMarkdown.node")(children[i2], globals);
        }
        txt += "~~";
      }
      return txt;
    });
    showdown2.subParser("makeMarkdown.strong", function(node, globals) {
      var txt = "";
      if (node.hasChildNodes()) {
        txt += "**";
        var children = node.childNodes, childrenLength = children.length;
        for (var i2 = 0; i2 < childrenLength; ++i2) {
          txt += showdown2.subParser("makeMarkdown.node")(children[i2], globals);
        }
        txt += "**";
      }
      return txt;
    });
    showdown2.subParser("makeMarkdown.table", function(node, globals) {
      var txt = "", tableArray = [[], []], headings = node.querySelectorAll("thead>tr>th"), rows = node.querySelectorAll("tbody>tr"), i2, ii;
      for (i2 = 0; i2 < headings.length; ++i2) {
        var headContent = showdown2.subParser("makeMarkdown.tableCell")(headings[i2], globals), allign = "---";
        if (headings[i2].hasAttribute("style")) {
          var style = headings[i2].getAttribute("style").toLowerCase().replace(/\s/g, "");
          switch (style) {
            case "text-align:left;":
              allign = ":---";
              break;
            case "text-align:right;":
              allign = "---:";
              break;
            case "text-align:center;":
              allign = ":---:";
              break;
          }
        }
        tableArray[0][i2] = headContent.trim();
        tableArray[1][i2] = allign;
      }
      for (i2 = 0; i2 < rows.length; ++i2) {
        var r2 = tableArray.push([]) - 1, cols = rows[i2].getElementsByTagName("td");
        for (ii = 0; ii < headings.length; ++ii) {
          var cellContent = " ";
          if (typeof cols[ii] !== "undefined") {
            cellContent = showdown2.subParser("makeMarkdown.tableCell")(cols[ii], globals);
          }
          tableArray[r2].push(cellContent);
        }
      }
      var cellSpacesCount = 3;
      for (i2 = 0; i2 < tableArray.length; ++i2) {
        for (ii = 0; ii < tableArray[i2].length; ++ii) {
          var strLen = tableArray[i2][ii].length;
          if (strLen > cellSpacesCount) {
            cellSpacesCount = strLen;
          }
        }
      }
      for (i2 = 0; i2 < tableArray.length; ++i2) {
        for (ii = 0; ii < tableArray[i2].length; ++ii) {
          if (i2 === 1) {
            if (tableArray[i2][ii].slice(-1) === ":") {
              tableArray[i2][ii] = showdown2.helper.padEnd(tableArray[i2][ii].slice(-1), cellSpacesCount - 1, "-") + ":";
            } else {
              tableArray[i2][ii] = showdown2.helper.padEnd(tableArray[i2][ii], cellSpacesCount, "-");
            }
          } else {
            tableArray[i2][ii] = showdown2.helper.padEnd(tableArray[i2][ii], cellSpacesCount);
          }
        }
        txt += "| " + tableArray[i2].join(" | ") + " |\n";
      }
      return txt.trim();
    });
    showdown2.subParser("makeMarkdown.tableCell", function(node, globals) {
      var txt = "";
      if (!node.hasChildNodes()) {
        return "";
      }
      var children = node.childNodes, childrenLength = children.length;
      for (var i2 = 0; i2 < childrenLength; ++i2) {
        txt += showdown2.subParser("makeMarkdown.node")(children[i2], globals, true);
      }
      return txt.trim();
    });
    showdown2.subParser("makeMarkdown.txt", function(node) {
      var txt = node.nodeValue;
      txt = txt.replace(/ +/g, " ");
      txt = txt.replace(/¨NBSP;/g, " ");
      txt = showdown2.helper.unescapeHTMLEntities(txt);
      txt = txt.replace(/([*_~|`])/g, "\\$1");
      txt = txt.replace(/^(\s*)>/g, "\\$1>");
      txt = txt.replace(/^#/gm, "\\#");
      txt = txt.replace(/^(\s*)([-=]{3,})(\s*)$/, "$1\\$2$3");
      txt = txt.replace(/^( {0,3}\d+)\./gm, "$1\\.");
      txt = txt.replace(/^( {0,3})([+-])/gm, "$1\\$2");
      txt = txt.replace(/]([\s]*)\(/g, "\\]$1\\(");
      txt = txt.replace(/^ {0,3}\[([\S \t]*?)]:/gm, "\\[$1]:");
      return txt;
    });
    var root2 = this;
    if (module.exports) {
      module.exports = showdown2;
    } else {
      root2.showdown = showdown2;
    }
  }).call(commonjsGlobal);
})(showdown);
var showdownExports = showdown.exports;
showdownExports.setOption("simpleLineBreaks", true);
showdownExports.setOption("literalMidWordUnderscores", true);
const converter = new showdownExports.Converter();
const MarkdownDiv = (props) => {
  const { markdown, style } = props;
  const escaped = markdown ? escape$1(markdown) : "";
  const preRendered = preRenderText(escaped);
  const renderedHtml = converter.makeHtml(preRendered);
  const withCode = unescapeCodeHtmlEntities(renderedHtml);
  const markup = { __html: withCode };
  return m$1`<div
    dangerouslySetInnerHTML=${markup}
    style=${style}
    class="${props.class ? `${props.class} ` : ""}markdown-content"
  />`;
};
const kLetterListPattern = /^([a-zA-Z][).]\s.*?)$/gm;
const kCommonmarkReferenceLinkPattern = /\[(.*)\]:( +.+)/g;
const preRenderText = (txt) => {
  const rendered = txt.replaceAll(
    kLetterListPattern,
    "<p style='margin-bottom: 0.2em;'>$1</p>"
  );
  return rendered.replaceAll(kCommonmarkReferenceLinkPattern, "[$1]:$2");
};
const escape$1 = (content) => {
  return content.replace(/[<>&'"]/g, function(c2) {
    switch (c2) {
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case "&":
        return "&amp;";
      case "'":
        return "&apos;";
      case '"':
        return "&quot;";
    }
  });
};
function unescapeCodeHtmlEntities(str) {
  const htmlEntities = {
    "&lt;": "<",
    "&gt;": ">",
    "&amp;": "&",
    "&#x5C;": "\\",
    "&quot;": '"'
  };
  return str.replace(
    /(<code[^>]*>)([\s\S]*?)(<\/code>)/gi,
    function(match, starttag, content, endtag) {
      return starttag + content.replace(
        /&(?:amp|lt|gt|quot|#39|#x2F|#x5C|#96);/g,
        function(entity) {
          return htmlEntities[entity] || entity;
        }
      ) + endtag;
    }
  );
}
Prism.languages.python = {
  "comment": {
    pattern: /(^|[^\\])#.*/,
    lookbehind: true,
    greedy: true
  },
  "string-interpolation": {
    pattern: /(?:f|fr|rf)(?:("""|''')[\s\S]*?\1|("|')(?:\\.|(?!\2)[^\\\r\n])*\2)/i,
    greedy: true,
    inside: {
      "interpolation": {
        // "{" <expression> <optional "!s", "!r", or "!a"> <optional ":" format specifier> "}"
        pattern: /((?:^|[^{])(?:\{\{)*)\{(?!\{)(?:[^{}]|\{(?!\{)(?:[^{}]|\{(?!\{)(?:[^{}])+\})+\})+\}/,
        lookbehind: true,
        inside: {
          "format-spec": {
            pattern: /(:)[^:(){}]+(?=\}$)/,
            lookbehind: true
          },
          "conversion-option": {
            pattern: /![sra](?=[:}]$)/,
            alias: "punctuation"
          },
          rest: null
        }
      },
      "string": /[\s\S]+/
    }
  },
  "triple-quoted-string": {
    pattern: /(?:[rub]|br|rb)?("""|''')[\s\S]*?\1/i,
    greedy: true,
    alias: "string"
  },
  "string": {
    pattern: /(?:[rub]|br|rb)?("|')(?:\\.|(?!\1)[^\\\r\n])*\1/i,
    greedy: true
  },
  "function": {
    pattern: /((?:^|\s)def[ \t]+)[a-zA-Z_]\w*(?=\s*\()/g,
    lookbehind: true
  },
  "class-name": {
    pattern: /(\bclass\s+)\w+/i,
    lookbehind: true
  },
  "decorator": {
    pattern: /(^[\t ]*)@\w+(?:\.\w+)*/m,
    lookbehind: true,
    alias: ["annotation", "punctuation"],
    inside: {
      "punctuation": /\./
    }
  },
  "keyword": /\b(?:_(?=\s*:)|and|as|assert|async|await|break|case|class|continue|def|del|elif|else|except|exec|finally|for|from|global|if|import|in|is|lambda|match|nonlocal|not|or|pass|print|raise|return|try|while|with|yield)\b/,
  "builtin": /\b(?:__import__|abs|all|any|apply|ascii|basestring|bin|bool|buffer|bytearray|bytes|callable|chr|classmethod|cmp|coerce|compile|complex|delattr|dict|dir|divmod|enumerate|eval|execfile|file|filter|float|format|frozenset|getattr|globals|hasattr|hash|help|hex|id|input|int|intern|isinstance|issubclass|iter|len|list|locals|long|map|max|memoryview|min|next|object|oct|open|ord|pow|property|range|raw_input|reduce|reload|repr|reversed|round|set|setattr|slice|sorted|staticmethod|str|sum|super|tuple|type|unichr|unicode|vars|xrange|zip)\b/,
  "boolean": /\b(?:False|None|True)\b/,
  "number": /\b0(?:b(?:_?[01])+|o(?:_?[0-7])+|x(?:_?[a-f0-9])+)\b|(?:\b\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*)?)?|\B\.\d+(?:_\d+)*)(?:e[+-]?\d+(?:_\d+)*)?j?(?!\w)/i,
  "operator": /[-+%=]=?|!=|:=|\*\*?=?|\/\/?=?|<[<=>]?|>[=>]?|[&|^~]/,
  "punctuation": /[{}[\];(),.:]/
};
Prism.languages.python["string-interpolation"].inside["interpolation"].inside.rest = Prism.languages.python;
Prism.languages.py = Prism.languages.python;
(function(Prism2) {
  var envVars = "\\b(?:BASH|BASHOPTS|BASH_ALIASES|BASH_ARGC|BASH_ARGV|BASH_CMDS|BASH_COMPLETION_COMPAT_DIR|BASH_LINENO|BASH_REMATCH|BASH_SOURCE|BASH_VERSINFO|BASH_VERSION|COLORTERM|COLUMNS|COMP_WORDBREAKS|DBUS_SESSION_BUS_ADDRESS|DEFAULTS_PATH|DESKTOP_SESSION|DIRSTACK|DISPLAY|EUID|GDMSESSION|GDM_LANG|GNOME_KEYRING_CONTROL|GNOME_KEYRING_PID|GPG_AGENT_INFO|GROUPS|HISTCONTROL|HISTFILE|HISTFILESIZE|HISTSIZE|HOME|HOSTNAME|HOSTTYPE|IFS|INSTANCE|JOB|LANG|LANGUAGE|LC_ADDRESS|LC_ALL|LC_IDENTIFICATION|LC_MEASUREMENT|LC_MONETARY|LC_NAME|LC_NUMERIC|LC_PAPER|LC_TELEPHONE|LC_TIME|LESSCLOSE|LESSOPEN|LINES|LOGNAME|LS_COLORS|MACHTYPE|MAILCHECK|MANDATORY_PATH|NO_AT_BRIDGE|OLDPWD|OPTERR|OPTIND|ORBIT_SOCKETDIR|OSTYPE|PAPERSIZE|PATH|PIPESTATUS|PPID|PS1|PS2|PS3|PS4|PWD|RANDOM|REPLY|SECONDS|SELINUX_INIT|SESSION|SESSIONTYPE|SESSION_MANAGER|SHELL|SHELLOPTS|SHLVL|SSH_AUTH_SOCK|TERM|UID|UPSTART_EVENTS|UPSTART_INSTANCE|UPSTART_JOB|UPSTART_SESSION|USER|WINDOWID|XAUTHORITY|XDG_CONFIG_DIRS|XDG_CURRENT_DESKTOP|XDG_DATA_DIRS|XDG_GREETER_DATA_DIR|XDG_MENU_PREFIX|XDG_RUNTIME_DIR|XDG_SEAT|XDG_SEAT_PATH|XDG_SESSION_DESKTOP|XDG_SESSION_ID|XDG_SESSION_PATH|XDG_SESSION_TYPE|XDG_VTNR|XMODIFIERS)\\b";
  var commandAfterHeredoc = {
    pattern: /(^(["']?)\w+\2)[ \t]+\S.*/,
    lookbehind: true,
    alias: "punctuation",
    // this looks reasonably well in all themes
    inside: null
    // see below
  };
  var insideString = {
    "bash": commandAfterHeredoc,
    "environment": {
      pattern: RegExp("\\$" + envVars),
      alias: "constant"
    },
    "variable": [
      // [0]: Arithmetic Environment
      {
        pattern: /\$?\(\([\s\S]+?\)\)/,
        greedy: true,
        inside: {
          // If there is a $ sign at the beginning highlight $(( and )) as variable
          "variable": [
            {
              pattern: /(^\$\(\([\s\S]+)\)\)/,
              lookbehind: true
            },
            /^\$\(\(/
          ],
          "number": /\b0x[\dA-Fa-f]+\b|(?:\b\d+(?:\.\d*)?|\B\.\d+)(?:[Ee]-?\d+)?/,
          // Operators according to https://www.gnu.org/software/bash/manual/bashref.html#Shell-Arithmetic
          "operator": /--|\+\+|\*\*=?|<<=?|>>=?|&&|\|\||[=!+\-*/%<>^&|]=?|[?~:]/,
          // If there is no $ sign at the beginning highlight (( and )) as punctuation
          "punctuation": /\(\(?|\)\)?|,|;/
        }
      },
      // [1]: Command Substitution
      {
        pattern: /\$\((?:\([^)]+\)|[^()])+\)|`[^`]+`/,
        greedy: true,
        inside: {
          "variable": /^\$\(|^`|\)$|`$/
        }
      },
      // [2]: Brace expansion
      {
        pattern: /\$\{[^}]+\}/,
        greedy: true,
        inside: {
          "operator": /:[-=?+]?|[!\/]|##?|%%?|\^\^?|,,?/,
          "punctuation": /[\[\]]/,
          "environment": {
            pattern: RegExp("(\\{)" + envVars),
            lookbehind: true,
            alias: "constant"
          }
        }
      },
      /\$(?:\w+|[#?*!@$])/
    ],
    // Escape sequences from echo and printf's manuals, and escaped quotes.
    "entity": /\\(?:[abceEfnrtv\\"]|O?[0-7]{1,3}|U[0-9a-fA-F]{8}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{1,2})/
  };
  Prism2.languages.bash = {
    "shebang": {
      pattern: /^#!\s*\/.*/,
      alias: "important"
    },
    "comment": {
      pattern: /(^|[^"{\\$])#.*/,
      lookbehind: true
    },
    "function-name": [
      // a) function foo {
      // b) foo() {
      // c) function foo() {
      // but not “foo {”
      {
        // a) and c)
        pattern: /(\bfunction\s+)[\w-]+(?=(?:\s*\(?:\s*\))?\s*\{)/,
        lookbehind: true,
        alias: "function"
      },
      {
        // b)
        pattern: /\b[\w-]+(?=\s*\(\s*\)\s*\{)/,
        alias: "function"
      }
    ],
    // Highlight variable names as variables in for and select beginnings.
    "for-or-select": {
      pattern: /(\b(?:for|select)\s+)\w+(?=\s+in\s)/,
      alias: "variable",
      lookbehind: true
    },
    // Highlight variable names as variables in the left-hand part
    // of assignments (“=” and “+=”).
    "assign-left": {
      pattern: /(^|[\s;|&]|[<>]\()\w+(?:\.\w+)*(?=\+?=)/,
      inside: {
        "environment": {
          pattern: RegExp("(^|[\\s;|&]|[<>]\\()" + envVars),
          lookbehind: true,
          alias: "constant"
        }
      },
      alias: "variable",
      lookbehind: true
    },
    // Highlight parameter names as variables
    "parameter": {
      pattern: /(^|\s)-{1,2}(?:\w+:[+-]?)?\w+(?:\.\w+)*(?=[=\s]|$)/,
      alias: "variable",
      lookbehind: true
    },
    "string": [
      // Support for Here-documents https://en.wikipedia.org/wiki/Here_document
      {
        pattern: /((?:^|[^<])<<-?\s*)(\w+)\s[\s\S]*?(?:\r?\n|\r)\2/,
        lookbehind: true,
        greedy: true,
        inside: insideString
      },
      // Here-document with quotes around the tag
      // → No expansion (so no “inside”).
      {
        pattern: /((?:^|[^<])<<-?\s*)(["'])(\w+)\2\s[\s\S]*?(?:\r?\n|\r)\3/,
        lookbehind: true,
        greedy: true,
        inside: {
          "bash": commandAfterHeredoc
        }
      },
      // “Normal” string
      {
        // https://www.gnu.org/software/bash/manual/html_node/Double-Quotes.html
        pattern: /(^|[^\\](?:\\\\)*)"(?:\\[\s\S]|\$\([^)]+\)|\$(?!\()|`[^`]+`|[^"\\`$])*"/,
        lookbehind: true,
        greedy: true,
        inside: insideString
      },
      {
        // https://www.gnu.org/software/bash/manual/html_node/Single-Quotes.html
        pattern: /(^|[^$\\])'[^']*'/,
        lookbehind: true,
        greedy: true
      },
      {
        // https://www.gnu.org/software/bash/manual/html_node/ANSI_002dC-Quoting.html
        pattern: /\$'(?:[^'\\]|\\[\s\S])*'/,
        greedy: true,
        inside: {
          "entity": insideString.entity
        }
      }
    ],
    "environment": {
      pattern: RegExp("\\$?" + envVars),
      alias: "constant"
    },
    "variable": insideString.variable,
    "function": {
      pattern: /(^|[\s;|&]|[<>]\()(?:add|apropos|apt|apt-cache|apt-get|aptitude|aspell|automysqlbackup|awk|basename|bash|bc|bconsole|bg|bzip2|cal|cargo|cat|cfdisk|chgrp|chkconfig|chmod|chown|chroot|cksum|clear|cmp|column|comm|composer|cp|cron|crontab|csplit|curl|cut|date|dc|dd|ddrescue|debootstrap|df|diff|diff3|dig|dir|dircolors|dirname|dirs|dmesg|docker|docker-compose|du|egrep|eject|env|ethtool|expand|expect|expr|fdformat|fdisk|fg|fgrep|file|find|fmt|fold|format|free|fsck|ftp|fuser|gawk|git|gparted|grep|groupadd|groupdel|groupmod|groups|grub-mkconfig|gzip|halt|head|hg|history|host|hostname|htop|iconv|id|ifconfig|ifdown|ifup|import|install|ip|java|jobs|join|kill|killall|less|link|ln|locate|logname|logrotate|look|lpc|lpr|lprint|lprintd|lprintq|lprm|ls|lsof|lynx|make|man|mc|mdadm|mkconfig|mkdir|mke2fs|mkfifo|mkfs|mkisofs|mknod|mkswap|mmv|more|most|mount|mtools|mtr|mutt|mv|nano|nc|netstat|nice|nl|node|nohup|notify-send|npm|nslookup|op|open|parted|passwd|paste|pathchk|ping|pkill|pnpm|podman|podman-compose|popd|pr|printcap|printenv|ps|pushd|pv|quota|quotacheck|quotactl|ram|rar|rcp|reboot|remsync|rename|renice|rev|rm|rmdir|rpm|rsync|scp|screen|sdiff|sed|sendmail|seq|service|sftp|sh|shellcheck|shuf|shutdown|sleep|slocate|sort|split|ssh|stat|strace|su|sudo|sum|suspend|swapon|sync|sysctl|tac|tail|tar|tee|time|timeout|top|touch|tr|traceroute|tsort|tty|umount|uname|unexpand|uniq|units|unrar|unshar|unzip|update-grub|uptime|useradd|userdel|usermod|users|uudecode|uuencode|v|vcpkg|vdir|vi|vim|virsh|vmstat|wait|watch|wc|wget|whereis|which|who|whoami|write|xargs|xdg-open|yarn|yes|zenity|zip|zsh|zypper)(?=$|[)\s;|&])/,
      lookbehind: true
    },
    "keyword": {
      pattern: /(^|[\s;|&]|[<>]\()(?:case|do|done|elif|else|esac|fi|for|function|if|in|select|then|until|while)(?=$|[)\s;|&])/,
      lookbehind: true
    },
    // https://www.gnu.org/software/bash/manual/html_node/Shell-Builtin-Commands.html
    "builtin": {
      pattern: /(^|[\s;|&]|[<>]\()(?:\.|:|alias|bind|break|builtin|caller|cd|command|continue|declare|echo|enable|eval|exec|exit|export|getopts|hash|help|let|local|logout|mapfile|printf|pwd|read|readarray|readonly|return|set|shift|shopt|source|test|times|trap|type|typeset|ulimit|umask|unalias|unset)(?=$|[)\s;|&])/,
      lookbehind: true,
      // Alias added to make those easier to distinguish from strings.
      alias: "class-name"
    },
    "boolean": {
      pattern: /(^|[\s;|&]|[<>]\()(?:false|true)(?=$|[)\s;|&])/,
      lookbehind: true
    },
    "file-descriptor": {
      pattern: /\B&\d\b/,
      alias: "important"
    },
    "operator": {
      // Lots of redirections here, but not just that.
      pattern: /\d?<>|>\||\+=|=[=~]?|!=?|<<[<-]?|[&\d]?>>|\d[<>]&?|[<>][&=]?|&[>&]?|\|[&|]?/,
      inside: {
        "file-descriptor": {
          pattern: /^\d/,
          alias: "important"
        }
      }
    },
    "punctuation": /\$?\(\(?|\)\)?|\.\.|[{}[\];\\]/,
    "number": {
      pattern: /(^|\s)(?:[1-9]\d*|0)(?:[.,]\d+)?\b/,
      lookbehind: true
    }
  };
  commandAfterHeredoc.inside = Prism2.languages.bash;
  var toBeCopied = [
    "comment",
    "function-name",
    "for-or-select",
    "assign-left",
    "parameter",
    "string",
    "environment",
    "function",
    "keyword",
    "builtin",
    "boolean",
    "file-descriptor",
    "operator",
    "punctuation",
    "number"
  ];
  var inside = insideString.variable[1].inside;
  for (var i2 = 0; i2 < toBeCopied.length; i2++) {
    inside[toBeCopied[i2]] = Prism2.languages.bash[toBeCopied[i2]];
  }
  Prism2.languages.sh = Prism2.languages.bash;
  Prism2.languages.shell = Prism2.languages.bash;
})(Prism);
Prism.languages.json = {
  "property": {
    pattern: /(^|[^\\])"(?:\\.|[^\\"\r\n])*"(?=\s*:)/,
    lookbehind: true,
    greedy: true
  },
  "string": {
    pattern: /(^|[^\\])"(?:\\.|[^\\"\r\n])*"(?!\s*:)/,
    lookbehind: true,
    greedy: true
  },
  "comment": {
    pattern: /\/\/.*|\/\*[\s\S]*?(?:\*\/|$)/,
    greedy: true
  },
  "number": /-?\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b/i,
  "punctuation": /[{}[\],]/,
  "operator": /:/,
  "boolean": /\b(?:false|true)\b/,
  "null": {
    pattern: /\bnull\b/,
    alias: "keyword"
  }
};
Prism.languages.webmanifest = Prism.languages.json;
const ApplicationStyles = {
  moreButton: {
    maxHeight: "1.8em",
    fontSize: FontSize.smaller,
    padding: "0 0.2em 0 0.2em",
    ...TextStyle.secondary
  },
  threeLineClamp: {
    display: "-webkit-box",
    "-webkit-line-clamp": "3",
    "-webkit-box-orient": "vertical",
    overflow: "hidden"
  },
  lineClamp: (len) => {
    return {
      display: "-webkit-box",
      "-webkit-line-clamp": `${len}`,
      "-webkit-box-orient": "vertical",
      overflow: "hidden"
    };
  },
  wrapText: () => {
    return {
      whiteSpace: "nowrap",
      textOverflow: "ellipsis",
      overflow: "hidden"
    };
  },
  scoreFills: {
    green: {
      backgroundColor: "var(--bs-success)",
      borderColor: "var(--bs-success)",
      color: "var(--bs-body-bg)"
    },
    red: {
      backgroundColor: "var(--bs-danger)",
      borderColor: "var(--bs-danger)",
      color: "var(--bs-body-bg)"
    },
    orange: {
      backgroundColor: "var(--bs-orange)",
      borderColor: "var(--bs-orange)",
      color: "var(--bs-body-bg)"
    }
  }
};
const ExpandablePanel = ({ collapse, border, lines = 7, children }) => {
  const [collapsed, setCollapsed] = h(collapse);
  const [showToggle, setShowToggle] = h(false);
  const contentsRef = A();
  const observerRef = A();
  y(() => {
    setCollapsed(collapse);
  }, [children, collapse]);
  y(() => {
    const checkScrollable = () => {
      if (collapse && contentsRef.current) {
        const isScrollable = contentsRef.current.offsetHeight < contentsRef.current.scrollHeight;
        setShowToggle(isScrollable);
      }
    };
    observerRef.current = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          checkScrollable();
        }
      });
    });
    if (contentsRef.current) {
      observerRef.current.observe(contentsRef.current);
    }
    checkScrollable();
    return () => {
      if (observerRef.current && contentsRef.current) {
        observerRef.current.unobserve(contentsRef.current);
      }
    };
  }, [collapse, contentsRef, observerRef]);
  let contentsStyle = { fontSize: FontSize.base };
  if (collapse && collapsed) {
    contentsStyle = { ...contentsStyle, ...ApplicationStyles.lineClamp(lines) };
  }
  if (border) {
    contentsStyle.border = "solid var(--bs-light-border-subtle) 1px";
  }
  return m$1`<div
      class="expandable-panel"
      ref=${contentsRef}
      style=${contentsStyle}
    >
      ${children}
    </div>
    ${showToggle ? m$1`<${MoreToggle}
          collapsed=${collapsed}
          setCollapsed=${setCollapsed}
          border=${!border}
        />` : ""}`;
};
const MoreToggle = ({ collapsed, border, setCollapsed }) => {
  const text = collapsed ? "more" : "less";
  const icon = collapsed ? ApplicationIcons["expand-down"] : ApplicationIcons.collapse.up;
  const topStyle = {
    display: "flex",
    marginBottom: "0.5em"
  };
  if (border) {
    topStyle.borderTop = "solid var(--bs-light-border-subtle) 1px";
    topStyle.marginTop = "0.5em";
  } else {
    topStyle.marginTop = "0";
  }
  return m$1`
    <div style=${topStyle}>
      <div
        style=${{
    display: "inline-block",
    border: "solid var(--bs-light-border-subtle) 1px",
    borderTop: "none",
    marginLeft: "auto",
    marginRight: "1em"
  }}
      >
        <button
          class="btn"
          style=${{
    fontSize: FontSize.smaller,
    border: "none",
    padding: "0.1rem .5rem"
  }}
          onclick=${() => {
    setCollapsed(!collapsed);
  }}
        >
          <i class="${icon}" /> ${text}
        </button>
      </div>
    </div>
  `;
};
const resolveToolInput = (fn2, toolArgs) => {
  const toolName = fn2;
  const [inputKey, inputType] = extractInputMetadata(toolName);
  const { input, args } = extractInput(inputKey, toolArgs);
  const functionCall = args.length > 0 ? `${toolName}(${args.join(",")})` : toolName;
  return {
    functionCall,
    input,
    inputType
  };
};
const ToolCallView = ({
  functionCall,
  input,
  inputType,
  output,
  mode
}) => {
  const icon = mode === "compact" ? "" : m$1`<i
          class="bi bi-tools"
          style=${{
    marginRight: "0.2rem",
    opacity: "0.4"
  }}
        ></i>`;
  const codeIndent = mode === "compact" ? "" : "";
  return m$1`<p>
        ${icon}
        <code style=${{ fontSize: FontSize.small }}>${functionCall}</code>
        <div>
            <div style=${{ marginLeft: `${codeIndent}` }}>
            <${ToolInput} type=${inputType} contents=${input}/>
            ${output ? m$1`
              <${ExpandablePanel} collapse=${true} border=${true} lines=10>
              <${MessageContent} contents=${output} />
              </${ExpandablePanel}>` : ""}
            </div>
        </div>
        </p>`;
};
const ToolInput = ({ type, contents }) => {
  if (!contents) {
    return "";
  }
  const toolInputRef = A(
    /** @type {HTMLElement|null} */
    null
  );
  if (typeof contents === "object" || Array.isArray(contents)) {
    contents = JSON.stringify(contents);
  }
  T(() => {
    const tokens = Prism$1.languages[type];
    if (toolInputRef.current && tokens) {
      const html = Prism$1.highlight(contents, tokens, type);
      toolInputRef.current.innerHTML = html;
    }
  }, [toolInputRef.current, type, contents]);
  return m$1`<pre
    class="tool-output"
    style=${{
    padding: "0.5em",
    marginTop: "0.25em",
    marginBottom: "1rem"
  }}
  >
      <code ref=${toolInputRef} class="sourceCode${type ? ` language-${type}` : ""}" style=${{
    overflowWrap: "anywhere",
    whiteSpace: "pre-wrap"
  }}>
        ${contents}
        </code>
    </pre>`;
};
const ToolOutput = ({ output, style }) => {
  if (!output) {
    return "";
  }
  if (typeof output === "object" || Array.isArray(output)) {
    output = JSON.stringify(output);
  }
  return m$1`<pre
    style=${{
    marginLeft: "2px",
    padding: "0.5em 0.5em 0.5em 0.5em",
    whiteSpace: "pre-wrap",
    marginBottom: "0",
    ...style
  }}
  ><code class="sourceCode" style=${{ wordWrap: "anywhere" }}>
      ${output}
      </code></pre>`;
};
const extractInputMetadata = (toolName) => {
  if (toolName === "bash") {
    return ["cmd", "bash"];
  } else if (toolName === "python") {
    return ["code", "python"];
  } else if (toolName === "web_search") {
    return ["query", "text"];
  } else {
    return [void 0, void 0];
  }
};
const extractInput = (inputKey, args) => {
  const formatArg = (key2, value) => {
    const quotedValue = typeof value === "string" ? `"${value}"` : value;
    return `${key2}: ${quotedValue}`;
  };
  if (args) {
    if (Object.keys(args).length === 1) {
      return {
        input: args[Object.keys(args)[0]],
        args: []
      };
    } else if (args[inputKey]) {
      const input = args[inputKey];
      const filteredArgs = Object.keys(args).filter((key2) => {
        return key2 !== inputKey;
      }).map((key2) => {
        return formatArg(key2, args[key2]);
      });
      return {
        input,
        args: filteredArgs
      };
    } else {
      const formattedArgs = Object.keys(args).map((key2) => {
        return formatArg(key2, args[key2]);
      });
      return {
        input: void 0,
        args: formattedArgs
      };
    }
  }
  return {
    input: void 0,
    args: []
  };
};
const MessageContent = (props) => {
  const { contents } = props;
  if (Array.isArray(contents)) {
    return contents.map((content, index) => {
      if (typeof content === "string") {
        return messageRenderers["text"].render({
          text: content,
          index: index === contents.length - 1
        });
      } else {
        const renderer = messageRenderers[content.type];
        if (renderer) {
          return renderer.render(content, index === contents.length - 1);
        } else {
          console.error(`Unknown message content type '${content.type}'`);
        }
      }
    });
  } else {
    return messageRenderers["text"].render({ text: contents });
  }
};
const messageRenderers = {
  text: {
    render: (content, isLast) => {
      return m$1`<${MarkdownDiv}
        markdown=${content.text}
        class=${isLast ? "no-last-para-padding" : ""}
      />`;
    }
  },
  image: {
    render: (content) => {
      if (content.image.startsWith("data:")) {
        return m$1`<img
          src="${content.image}"
          style=${{
          maxWidth: "400px",
          border: "solid var(--bs-border-color) 1px"
        }}
        />`;
      } else {
        return m$1`<code>${content.image}</code>`;
      }
    }
  },
  tool: {
    render: (content) => {
      return m$1`<${ToolOutput} output=${content.text} />`;
    }
  }
};
const ChatView = ({ id, messages, style }) => {
  const toolMessages = {};
  const nonToolMessages = [];
  for (const message of messages) {
    if (message.role === "tool") {
      toolMessages[message.tool_call_id] = message;
    } else {
      nonToolMessages.push(message);
    }
  }
  const systemMessages = [];
  const collapsedMessages = nonToolMessages.map((msg) => {
    if (msg.role === "system") {
      systemMessages.push(msg);
    }
    return msg;
  }).filter((msg) => {
    return msg.role !== "system";
  });
  const systemMessage = systemMessages.reduce(
    (reduced, message) => {
      const systemContents = Array.isArray(message.content) ? message.content : [message.content];
      reduced.content.push(...systemContents.map(normalizeContent));
      return reduced;
    },
    { role: "system", content: [] }
  );
  if (systemMessage && systemMessage.content.length > 0) {
    collapsedMessages.unshift(systemMessage);
  }
  const result = m$1`
    <div style=${style}>
      ${collapsedMessages.map((msg) => {
    return m$1`<${ChatMessage}
          id=${`${id}-chat-messages`}
          message=${msg}
          toolMessages=${toolMessages}
        />`;
  })}
    </div>
  `;
  return result;
};
const normalizeContent = (content) => {
  if (typeof content === "string") {
    return {
      type: "text",
      text: content
    };
  } else {
    return content;
  }
};
const ChatMessage = ({ id, message, toolMessages }) => {
  const iconCls = iconForMsg(message);
  const icon = iconCls ? m$1`<i class="${iconCls}"></i>` : "";
  const collapse = message.role === "system";
  return m$1`
    <div
      class="container-fluid ${message.role}"
      style=${{
    fontSize: FontSize.base,
    fontWeight: "300",
    paddingBottom: ".5em",
    justifyContent: "flex-start",
    marginLeft: "0",
    marginRight: "0",
    opacity: message.role === "system" ? "0.7" : "1",
    whiteSpace: "normal"
  }}
    >
      <div class="row row-cols-2">
        <div
          class="col"
          style=${{
    flex: "0 1 1em",
    paddingLeft: "0",
    paddingRight: "0.5em",
    marginLeft: "0",
    fontWeight: "500"
  }}
        >
          ${icon}
        </div>
        <div
          class="col"
          style=${{
    flex: "1 0 auto",
    marginLeft: ".3rem",
    paddingLeft: "0"
  }}
        >
          <div style=${{ fontWeight: "500", ...TextStyle.label }}>${message.role}</div>
          <${ExpandablePanel} collapse=${collapse}>
            <${MessageContents}
              key=${`${id}-contents`}
              message=${message}
              toolMessages=${toolMessages}
            />
          </${ExpandablePanel}>
        </div>
      </div>
    </div>
  `;
};
const MessageContents = ({ message, toolMessages }) => {
  if (message.tool_calls && message.tool_calls.length) {
    const result = [];
    if (message.content) {
      result.push(
        m$1`<div style=${{ marginBottom: "1em" }}>
          <${MessageContent} contents=${message.content} />
        </div>`
      );
    }
    const toolCalls = message.tool_calls.map((tool_call) => {
      const toolMessage = toolMessages[tool_call.id];
      const { input, functionCall, inputType } = resolveToolInput(
        tool_call.function,
        tool_call.arguments
      );
      const resolvedToolOutput = resolveToolMessage(toolMessage);
      return m$1`<${ToolCallView}
        functionCall=${functionCall}
        input=${input}
        inputType=${inputType}
        output=${resolvedToolOutput}
      />`;
    });
    if (toolCalls) {
      result.push(...toolCalls);
    }
    return result;
  } else {
    return m$1`<${MessageContent} contents=${message.content} />`;
  }
};
const iconForMsg = (msg) => {
  let iconCls = ApplicationIcons.role.assistant;
  if (msg.role === "user") {
    iconCls = ApplicationIcons.role.user;
  } else if (msg.role === "system") {
    iconCls = ApplicationIcons.role.system;
  } else if (msg.role === "tool") {
    iconCls = ApplicationIcons.role.tool;
  }
  return iconCls;
};
const resolveToolMessage = (toolMessage) => {
  var _a;
  if (!toolMessage) {
    return void 0;
  }
  const content = ((_a = toolMessage.error) == null ? void 0 : _a.message) || toolMessage.tool_error || toolMessage.content;
  if (typeof content === "string") {
    return [
      {
        type: "tool",
        text: content
      }
    ];
  } else {
    return content.map((con) => {
      if (typeof content === "string") {
        return {
          type: "tool",
          text: content
        };
      } else if (con.type === "text") {
        return {
          ...con,
          type: "tool"
        };
      }
    });
  }
};
const RenderedContent = ({
  id,
  entry,
  context,
  defaultRendering,
  options
}) => {
  if (entry.value === null) {
    return "[null]";
  }
  const renderer = Object.keys(contentRenderers).map((key2) => {
    return contentRenderers[key2];
  }).sort((a2, b2) => {
    return a2.bucket - b2.bucket;
  }).find((renderer2) => {
    return renderer2.canRender(entry);
  });
  let value = entry.value;
  if (renderer) {
    const { rendered, afterBody } = renderer.render(
      id,
      entry,
      defaultRendering,
      options,
      context
    );
    if (rendered !== void 0) {
      value = rendered;
      if (afterBody !== void 0) {
        context.afterBody(afterBody);
      }
    }
  }
  return m$1`${value}`;
};
const Buckets = {
  first: 0,
  intermediate: 10,
  final: 1e3
};
const contentRenderers = {
  AnsiString: {
    bucket: Buckets.first,
    canRender: (entry) => {
      return typeof entry.value === "string" && entry.value.indexOf("\x1B") > -1;
    },
    render: (id, entry) => {
      return {
        rendered: m$1`<${ANSIDisplay} output=${entry.value} />`
      };
    }
  },
  Model: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object" && entry.value._model;
    },
    render: (_id, entry) => {
      return {
        rendered: m$1`<i class="${ApplicationIcons.model}"></i> ${entry.value._model}`
      };
    }
  },
  Boolean: {
    order: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "boolean";
    },
    render: (id, entry) => {
      entry.value = entry.value.toString();
      return contentRenderers.String.render(id, entry);
    }
  },
  Number: {
    order: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "number";
    },
    render: (id, entry) => {
      entry.value = formatNumber(entry.value);
      return contentRenderers.String.render(id, entry);
    }
  },
  String: {
    bucket: Buckets.final,
    canRender: (entry) => {
      return typeof entry.value === "string";
    },
    render: (_id, entry, defaultRendering) => {
      const rendered = defaultRendering ? defaultRendering(entry.value.trim()) : entry.value.trim();
      return {
        rendered
      };
    }
  },
  Array: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      const isArray = Array.isArray(entry.value);
      if (isArray) {
        const types = new Set(
          entry.value.map((entry2) => {
            return typeof entry2;
          })
        );
        return types.size === 1;
      } else {
        return false;
      }
    },
    render: (id, entry, _defaultRendering, _options, context) => {
      const arrayMap = {};
      entry.value.forEach((entry2, index) => {
        arrayMap[`[${index}]`] = entry2;
      });
      const arrayRendered = m$1`<${MetaDataView}
        id=${id}
        style=${{ fontSize: FontSize.small }}
        entries="${arrayMap}"
        tableOptions="borderless,sm"
        context=${context}
        compact
      />`;
      return { rendered: arrayRendered };
    }
  },
  ChatMessage: {
    bucket: Buckets.first,
    canRender: (entry) => {
      var _a, _b;
      const val = entry.value;
      return Array.isArray(val) && val.length > 0 && ((_a = val[0]) == null ? void 0 : _a.role) !== void 0 && ((_b = val[0]) == null ? void 0 : _b.content) !== void 0;
    },
    render: (_id, entry) => {
      return {
        rendered: m$1`<${ChatView} messages=${entry.value} />`
      };
    }
  },
  web_search: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object" && entry.name === "web_search";
    },
    render: (_id, entry) => {
      const results = [];
      results.push(
        m$1`<div style=${{ marginBottom: "0.5rem", fontWeight: "500" }}>
          <i class=${ApplicationIcons.search}></i> ${entry.value.query}
        </div>`
      );
      entry.value.results.forEach((result) => {
        results.push(
          m$1`<div>
            <a href="${result.url}">${result.url}</a>
          </div>`
        );
        results.push(
          m$1`<div
            style=${{ fontSize: FontSize.smaller, marginBottom: "0.5rem" }}
          >
            ${result.summary}
          </div>`
        );
      });
      return {
        rendered: results
      };
    }
  },
  Html: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object" && entry.value._html;
    },
    render: (id, entry) => {
      return {
        rendered: entry.value._html
      };
    }
  },
  Object: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object";
    },
    render: (id, entry, _defaultRendering, _options, context) => {
      const summary = [];
      const keys = Object.keys(entry.value);
      if (keys.length > 4) {
        summary.push(...keys.slice(0, 2));
        summary.push("...");
        summary.push(...keys.slice(keys.length - 2));
      } else {
        summary.push(...keys);
      }
      return {
        rendered: m$1`<${MetaDataView}
          id=${id}
          style=${{ fontSize: FontSize.smaller }}
          entries="${entry.value}"
          tableOptions="borderless,sm"
          context=${context}
          compact
        />`
      };
    }
  }
};
const MetaDataView = ({
  id,
  baseClass,
  classes,
  style,
  entries,
  tableOptions,
  context,
  expanded,
  compact
}) => {
  const baseId = baseClass || "metadataview";
  const cellStyle = compact ? { padding: "0em" } : { padding: "0.3em 0.3em 0.3em 0em" };
  const cellKeyStyle = compact ? {
    fontWeight: "400",
    paddingRight: "0.2em",
    whiteSpace: "nowrap"
  } : {
    fontWeight: "400",
    paddingRight: "1em",
    whiteSpace: "nowrap"
  };
  const cellValueStyle = {
    fontWeight: "300",
    whiteSpace: "pre-wrap",
    wordWrap: "anywhere",
    fontSize: FontSize.small
  };
  const cellKeyTextStyle = {
    fontSize: FontSize.small
  };
  tableOptions = tableOptions || "sm";
  const tblClz = (tableOptions || "").split(",").map((option) => {
    return `table-${option}`;
  });
  if (entries && !Array.isArray(entries)) {
    entries = Object.entries(entries || {}).map(([key2, value]) => {
      return { name: key2, value };
    });
  }
  const entryEls = (entries || []).map((entry, index) => {
    const id2 = `${baseId}-value-${index}`;
    return m$1`<tr class="${baseId}-row">
      <td
        class="${baseId}-key"
        style=${{ ...cellStyle, ...cellKeyStyle, ...cellKeyTextStyle }}
      >
        ${entry.name}
      </td>
      <td class="${baseId}-value" style=${{ ...cellStyle, ...cellValueStyle }}>
        <${RenderedContent}
          id=${id2}
          entry=${entry}
          context=${context}
          options=${{ expanded }}
        />
      </td>
    </tr>`;
  });
  return m$1`<table
    ...${{ id }}
    class="${classes || ""} table ${tblClz.join(" ")}"
    style=${{
    paddingLeft: "0",
    marginLeft: "0",
    marginBottom: "0.2rem",
    ...style
  }}
  >
    <thead>
      <tr>
        <th colspan="2" style="${{ padding: 0 }}"></th>
      </tr>
    </thead>
    <tbody>
      ${entryEls}
    </tbody>
  </table>`;
};
const kPlanCardBodyId = "task-plan-card-body";
const PlanCard = ({ log, context }) => {
  var _a;
  return m$1`
    <${Card}>
      <${CardHeader} icon=${ApplicationIcons.config} label="Config"/>
      <${CardBody} id="${kPlanCardBodyId}" style=${{
    paddingTop: "0",
    paddingBottom: "0",
    borderTop: "solid var(--bs-border-color) 1px"
  }}>
      
        <${PlanDetailView}
          evaluation=${log == null ? void 0 : log.eval}
          plan=${log == null ? void 0 : log.plan}
          scores=${(_a = log == null ? void 0 : log.results) == null ? void 0 : _a.scores}
          context=${context}
        />
      </${CardBody}>
    </${Card}>
  `;
};
const planItemStyle = {
  fontSize: FontSize.base,
  marginBottom: "0em"
};
const planSepStyle = {
  marginLeft: ".3em",
  marginRight: ".3em",
  marginTop: "em",
  marginBottom: "-0.1em"
};
const ScorerDetailView = ({ name, scores, params, context }) => {
  if (scores.length > 1) {
    params["scores"] = scores;
  }
  return m$1`<${DetailStep}
    icon=${ApplicationIcons.scorer}
    name=${name}
    params=${params}
    context=${context}
    style=${planItemStyle}
  />`;
};
const DatasetDetailView = ({ dataset, context, style }) => {
  if (!dataset || Object.keys(dataset).length === 0) {
    return m$1`<span style=${{ ...planItemStyle, ...style }}
      >No dataset information available</span
    >`;
  }
  return m$1`<${MetaDataView}
    entries="${dataset}"
    tableOptions="borderless,sm"
    context=${context}
    style=${{ ...planItemStyle, ...style }}
  />`;
};
const SolversDetailView = ({ steps, context }) => {
  const separator = m$1` <div style=${{ ...planItemStyle, ...planSepStyle }}>
    <i class="${ApplicationIcons.arrows.right}"></i>
  </div>`;
  const details = steps == null ? void 0 : steps.map((step, index) => {
    return m$1`
      <${DetailStep}
        name=${step.solver}
        context=${context}
        style=${planItemStyle}
      />
      ${index < steps.length - 1 ? separator : ""}
    `;
  });
  return m$1`<div
    style=${{
    display: "flex",
    flexDirection: "columns"
  }}
  >
    ${details}
  </div>`;
};
const DetailStep = ({ icon, name, params, style, context }) => {
  const iconHtml = icon ? m$1`<i class="${icon}" style=${{ marginRight: ".3em" }}></i>` : "";
  return m$1`
    <div style=${style}>
      ${iconHtml} ${name}
      <div
        style=${{
    marginLeft: "1.3rem",
    marginTop: "0.2rem",
    marginBottom: "0.3rem"
  }}
      >
        ${m$1`<${MetaDataView}
          entries="${params}"
          context=${context}
          style=${{ fontSize: FontSize.small }}
        />`}
      </div>
    </div>
  `;
};
const PlanDetailView = ({ evaluation, plan, context, scores }) => {
  if (!evaluation) {
    return "";
  }
  const config = (evaluation == null ? void 0 : evaluation.config) || {};
  const steps = plan == null ? void 0 : plan.steps;
  const metadata = evaluation == null ? void 0 : evaluation.metadata;
  const revision = evaluation == null ? void 0 : evaluation.revision;
  const packages = evaluation == null ? void 0 : evaluation.packages;
  const model_args = evaluation == null ? void 0 : evaluation.model_args;
  const task_args = evaluation == null ? void 0 : evaluation.task_args;
  const generate_config = plan == null ? void 0 : plan.config;
  const taskInformation = {
    ["Task ID"]: evaluation == null ? void 0 : evaluation.task_id,
    ["Run ID"]: evaluation == null ? void 0 : evaluation.run_id
  };
  if (revision) {
    taskInformation[`${revision.type ? `${toTitleCase(revision.type)} ` : ""}Revision`] = {
      _html: m$1`<a href="${ghCommitUrl(revision.origin, revision.commit)}"
        >${revision.commit}</a
      >`
    };
  }
  if (packages) {
    taskInformation["Inspect"] = {
      _html: m$1`${Object.keys(packages).map((key2) => {
        return `${key2} ${packages[key2]}`;
      }).join("<br/>\n")}`
    };
  }
  if (evaluation == null ? void 0 : evaluation.model) {
    config["model"] = evaluation.model;
  }
  if (evaluation == null ? void 0 : evaluation.model_base_url) {
    config["model_base_url"] = evaluation.model_base_url;
  }
  if (evaluation == null ? void 0 : evaluation.sandbox) {
    config["sandbox"] = evaluation.sandbox[0];
    if (evaluation.sandbox[1]) {
      config["sandbox_config"] = evaluation.sandbox[1];
    }
  }
  const floatingColumnStyle = {
    flex: "0 1 1",
    width: "unset",
    textAlign: "left",
    paddingLeft: "0.6rem",
    paddingRight: "0.6rem"
  };
  const wideColumnStyle = {
    flex: "1 1 1",
    width: "unset",
    paddingLeft: "0.6rem",
    paddingRight: "0.6rem"
  };
  const oneColumnStyle = {
    flex: "0 0 100%"
  };
  const twoColumnStyle = {
    flex: "0 0 50%"
  };
  const planMetadataStyle = {
    fontSize: FontSize.base
  };
  const taskColumns = [];
  taskColumns.push({
    title: "Dataset",
    style: floatingColumnStyle,
    contents: m$1`<${DatasetDetailView}
      dataset=${evaluation.dataset}
      context=${context}
    />`
  });
  taskColumns.push({
    title: "Plan",
    style: wideColumnStyle,
    contents: m$1`
      <${SolversDetailView} steps=${steps} context=${context} />
    `
  });
  if (scores) {
    const scorers = scores.reduce((accum, score) => {
      if (!accum[score.scorer]) {
        accum[score.scorer] = {
          scores: [score.name],
          params: score.params
        };
      } else {
        accum[score.scorer].scores.push(score.name);
      }
      return accum;
    }, {});
    if (Object.keys(scorers).length > 0) {
      const label = Object.keys(scorers).length === 1 ? "Scorer" : "Scorers";
      const scorerPanels = Object.keys(scorers).map((key2) => {
        return m$1`<${ScorerDetailView}
          name=${key2}
          scores=${scorers[key2].scores}
          params=${scorers[key2].params}
          context=${context}
        />`;
      });
      taskColumns.push({
        title: label,
        style: floatingColumnStyle,
        contents: scorerPanels
      });
    }
  }
  const metadataColumns = [];
  const cols = colCount(
    metadataColumns,
    task_args,
    model_args,
    config,
    metadata
  );
  const configColumnStyle = cols.length === 1 ? oneColumnStyle : twoColumnStyle;
  metadataColumns.push({
    title: "Task Information",
    style: configColumnStyle,
    contents: m$1`
      <${MetaDataView}
        style=${planMetadataStyle}
        classes="task-title-deets-grid"
        entries="${taskInformation}"
        tableOptions="borderless,sm"
        context=${context}
      />
    `
  });
  if (task_args && Object.keys(task_args).length > 0) {
    metadataColumns.push({
      title: "Task Args",
      style: configColumnStyle,
      contents: m$1`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-task-args-grid"
          entries="${task_args}"
          tableOptions="sm"
          context=${context}
        />
      `
    });
  }
  if (model_args && Object.keys(model_args).length > 0) {
    metadataColumns.push({
      title: "Model Args",
      style: configColumnStyle,
      contents: m$1`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-model-args-grid"
          entries="${model_args}"
          tableOptions="sm"
          context=${context}
        />
      `
    });
  }
  if (config && Object.keys(config).length > 0) {
    metadataColumns.push({
      title: "Configuration",
      style: configColumnStyle,
      contents: m$1`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-configuration"
          entries="${config}"
          tableOptions="sm"
          context=${context}
        />
      `
    });
  }
  if (generate_config && Object.keys(generate_config).length > 0) {
    metadataColumns.push({
      title: "Generate Config",
      style: configColumnStyle,
      contents: m$1`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-generate-configuration"
          entries="${generate_config}"
          tableOptions="sm"
          context=${context}
        />
      `
    });
  }
  if (metadata && Object.keys(metadata).length > 0) {
    metadataColumns.push({
      title: "Metadata",
      style: configColumnStyle,
      contents: m$1`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-metadata"
          entries="${metadata}"
          tableOptions="sm"
          context=${context}
        />
      `
    });
  }
  return m$1`
    <div style=${{ paddingTop: "0", paddingBottom: "1em", marginLeft: "0" }}>
      <div
        class="row"
        style=${{
    justifyContent: "space-between",
    flexWrap: "wrap",
    paddingBottom: "0.7rem",
    borderBottom: "solid 1px var(--bs-border-color)"
  }}
      >
        ${taskColumns.map((col) => {
    return m$1`<${PlanColumn} title="${col.title}" style=${col.style}>
        ${col.contents}
      </${PlanColumn}>
      `;
  })}
      </div>

      <div
        class="row"
        style=${{ justifyContent: "flex-start", flexWrap: "wrap" }}
      >
        ${metadataColumns.map((col) => {
    return m$1`<${PlanColumn} title="${col.title}" style=${col.style}>
            ${col.contents}
          </${PlanColumn}>
          `;
  })}
      </div>
    </div>
  `;
};
const colCount = (...other) => {
  let count = 0;
  for (const o2 in other) {
    if (o2 && Object.keys(o2).length > 0) {
      count++;
    }
  }
  return count;
};
const PlanColumn = ({ title, classes, style, children }) => {
  return m$1`
    <div class="${classes || ""}" ...${{ style }}>
      <div
        class="card-subheading"
        style=${{
    fontSize: FontSize.small,
    ...TextStyle.label,
    ...TextStyle.secondary,
    marginTop: "1em"
  }}
      >
        ${title}
      </div>
      ${children}
    </div>
  `;
};
const isNumeric = (n2) => {
  return !isNaN(parseFloat(n2)) && isFinite(n2);
};
const kScoreTypePassFail = "passfail";
const kScoreTypeCategorical = "categorical";
const kScoreTypeNumeric = "numeric";
const kScoreTypeOther = "other";
const kScoreTypeObject = "object";
const samplesDescriptor = (selectedScore, scorers, samples, epochs, context) => {
  if (!samples) {
    return void 0;
  }
  const score = (sample, scorer = selectedScore == null ? void 0 : selectedScore.scorer) => {
    if (sample.scores[scorer]) {
      return sample.scores[scorer];
    } else {
      return void 0;
    }
  };
  const scoreValue = (sample) => {
    if (Object.keys(sample.scores).length === 0 || !selectedScore) {
      return void 0;
    }
    if (selectedScore.scorer !== selectedScore.name && sample.scores[selectedScore.scorer] && sample.scores[selectedScore.scorer].value) {
      return sample.scores[selectedScore.scorer].value[selectedScore.name];
    } else if (sample.scores[selectedScore.name]) {
      return sample.scores[selectedScore.name].value;
    } else {
      return void 0;
    }
  };
  const scoreAnswer = (sample, scorer) => {
    if (sample) {
      const sampleScore = score(sample, scorer);
      if (sampleScore && sampleScore.answer) {
        return sampleScore.answer;
      } else if (sample.output.choices && sample.output.choices.length > 0) {
        const content = sample.output.choices[0].message.content;
        if (typeof content === "string") {
          return content;
        } else {
          return content.length > 0 ? content[0].text : "";
        }
      }
    } else {
      return void 0;
    }
  };
  const scoreExplanation = (sample, scorer) => {
    if (sample) {
      const sampleScore = score(sample, scorer);
      if (sampleScore && sampleScore.explanation) {
        return sampleScore.explanation;
      }
    }
    return void 0;
  };
  const uniqScoreValues = [
    ...new Set(
      samples.filter((sample) => !!sample.scores).filter((sample) => {
        if (!selectedScore) {
          return true;
        }
        if (selectedScore.scorer !== selectedScore.name) {
          return Object.keys(sample.scores).includes(selectedScore.scorer) && Object.keys(sample.scores[selectedScore.scorer].value).includes(
            selectedScore.name
          );
        } else {
          return Object.keys(sample.scores).includes(selectedScore.name);
        }
      }).map((sample) => {
        return scoreValue(sample);
      }).filter((value) => {
        return value !== null;
      })
    )
  ];
  const uniqScoreTypes = [
    ...new Set(uniqScoreValues.map((scoreValue2) => typeof scoreValue2))
  ];
  let scoreDescriptor;
  for (const categorizer of scoreCategorizers) {
    scoreDescriptor = categorizer.describe(
      uniqScoreValues,
      uniqScoreTypes,
      context
    );
    if (scoreDescriptor) {
      break;
    }
  }
  const sizes = samples.reduce(
    (previous, current) => {
      var _a;
      previous[0] = Math.min(
        Math.max(previous[0], inputString(current.input).length),
        300
      );
      previous[1] = Math.min(
        Math.max(previous[1], arrayToString(current.target).length),
        300
      );
      previous[2] = Math.min(
        Math.max(previous[2], ((_a = scoreAnswer(current)) == null ? void 0 : _a.length) || 0),
        300
      );
      return previous;
    },
    [0, 0, 0]
  );
  const base = sizes[0] + sizes[1] + sizes[2] || 1;
  const messageShape = {
    input: sizes[0] / base,
    target: sizes[1] / base,
    answer: sizes[2] / base
  };
  const scoreRendered = (sample) => {
    const score2 = scoreValue(sample);
    if (score2 === null || score2 === "undefined") {
      return "null";
    } else if (scoreDescriptor.render) {
      return scoreDescriptor.render(score2);
    } else {
      return score2;
    }
  };
  const scorerDescriptor = (sample, scorer) => {
    return {
      explanation: () => {
        return scoreExplanation(sample, scorer);
      },
      answer: () => {
        return scoreAnswer(sample, scorer);
      },
      scores: () => {
        if (!sample || !sample.scores) {
          return [];
        }
        const scoreNames = scorers.map((score2) => {
          return score2.name;
        });
        const sampleScorer = sample.scores[scorer];
        const scoreVal = sampleScorer.value;
        if (typeof scoreVal === "object") {
          const names = Object.keys(scoreVal);
          if (names.find((name) => {
            return !scoreNames.includes(name);
          })) {
            return [
              {
                name: scorer,
                rendered: () => {
                  return scoreDescriptor.render(scoreVal);
                }
              }
            ];
          } else {
            const scores = names.map((name) => {
              return {
                name,
                rendered: () => {
                  return scoreDescriptor.render(scoreVal[name]);
                }
              };
            });
            return scores;
          }
        } else {
          return [
            {
              name: scorer,
              rendered: () => {
                return scoreDescriptor.render(scoreVal);
              }
            }
          ];
        }
      }
    };
  };
  return {
    scoreDescriptor,
    epochs,
    messageShape,
    selectedScore: (sample) => {
      return {
        value: scoreValue(sample),
        render: () => {
          return scoreRendered(sample);
        }
      };
    },
    scorer: (sample, scorer) => {
      return scorerDescriptor(sample, scorer);
    },
    selectedScorer: (sample) => {
      return scorerDescriptor(sample, selectedScore == null ? void 0 : selectedScore.scorer);
    }
  };
};
const scoreCategorizers = [
  {
    describe: (values, types) => {
      if (values.length === 2 && types.length === 1 && types[0] === "boolean") {
        return booleanScoreCategorizer();
      }
    }
  },
  {
    describe: (values) => {
      if ((values.length === 1 || values.length === 2) && values.every((val) => {
        return val === 1 || val === 0;
      })) {
        return booleanScoreCategorizer();
      }
    }
  },
  {
    describe: (values, types) => {
      if (types[0] === "string" && types.length === 1 && values.length < 5 && !values.find((val) => {
        return val !== "I" && val !== "C" && val !== "P" && val !== "N";
      })) {
        return passFailScoreCategorizer(values);
      }
    }
  },
  {
    describe: (values, types) => {
      if (values.length < 10 && types.length === 1 && types[0] === "string") {
        return {
          scoreType: kScoreTypeCategorical,
          categories: values,
          compare: (a2, b2) => {
            return a2.localeCompare(b2);
          },
          render: (score) => {
            return score;
          }
        };
      }
    }
  },
  {
    describe: (values, types) => {
      if (types.length !== 0 && types[0] === "number") {
        return {
          scoreType: kScoreTypeNumeric,
          min: Math.min(...values),
          max: Math.max(...values),
          compare: (a2, b2) => {
            return a2 - b2;
          },
          render: (score) => {
            return formatDecimalNoTrailingZeroes(score);
          }
        };
      }
    }
  },
  {
    describe: (values, types) => {
      if (types.length !== 0 && types[0] === "object") {
        const buckets = values.map((val) => {
          return JSON.stringify(val);
        });
        const vals = new Set(buckets);
        let categories = void 0;
        if (vals.size < 10) {
          categories = Array.from(vals).map((val) => {
            return {
              val,
              text: val
            };
          });
        }
        return {
          scoreType: kScoreTypeObject,
          categories,
          render: (score) => {
            if (score === null || score === void 0) {
              return "[null]";
            }
            const scores = [];
            const keys = Object.keys(score);
            keys.forEach((key2, index) => {
              const value = score[key2];
              const formattedValue = isNumeric(value) ? formatPrettyDecimal(parseFloat(value)) : value;
              const style = {
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                marginLeft: "0.5rem"
              };
              if (index + 1 < keys.length) {
                style["paddingBottom"] = "1em";
              }
              scores.push(m$1`
                <div style=${style}>
                  <div style=${{ fontSize: FontSize.smaller, fontWeight: 300 }}>
                    ${key2}
                  </div>
                  <div style=${{ fontSize: FontSize.title, fontWeight: 600 }}>
                    ${formattedValue}
                  </div>
                </div>
              `);
            });
            return scores;
          }
        };
      }
    }
  },
  {
    describe: (values, types, context) => {
      return {
        scoreType: kScoreTypeOther,
        render: (score) => {
          return m$1`<${RenderedContent}
            id="asdasdas"
            entry=${{ value: score }}
            context=${context}
          />`;
        }
      };
    }
  }
];
const filledCircleStyle = {
  fontSize: FontSize.small,
  fontFamily: "Consola Regular",
  width: "20px",
  height: "20px",
  display: "inline-flex",
  justifyContent: "center",
  alignItems: "center",
  borderRadius: "50%",
  paddingTop: "1px"
};
const booleanScoreCategorizer = () => {
  return {
    scoreType: "boolean",
    render: (score) => {
      const scoreColorStyle = score ? ApplicationStyles.scoreFills.green : ApplicationStyles.scoreFills.red;
      return m$1`<span
        style=${{
        ...scoreColorStyle,
        ...filledCircleStyle
      }}
        >${score}</span
      >`;
    }
  };
};
const passFailScoreCategorizer = (values) => {
  const categories = [];
  if (values.includes("C")) {
    categories.push({
      val: "C",
      text: "Correct"
    });
  }
  if (values.includes("P")) {
    categories.push({
      val: "P",
      text: "Partial"
    });
  }
  if (values.includes("I")) {
    categories.push({
      val: "I",
      text: "Incorrect"
    });
  }
  if (values.includes("N")) {
    categories.push({
      val: "N",
      text: "Refusal"
    });
  }
  const order2 = ["C", "P", "I", "N"];
  return {
    scoreType: kScoreTypePassFail,
    categories,
    render: (score) => {
      if (score === "C") {
        return m$1`<span
          style=${{
          ...ApplicationStyles.scoreFills.green,
          ...filledCircleStyle
        }}
          >C</span
        >`;
      } else if (score === "I") {
        return m$1`<span
          style=${{
          ...ApplicationStyles.scoreFills.red,
          ...filledCircleStyle
        }}
          >I</span
        >`;
      } else if (score === "P") {
        return m$1`<span
          style=${{
          ...ApplicationStyles.scoreFills.orange,
          ...filledCircleStyle
        }}
          >P</span
        >`;
      } else if (score === "N") {
        return m$1`<span
          style=${{
          ...ApplicationStyles.scoreFills.red,
          ...filledCircleStyle
        }}
          >N</span
        >`;
      } else {
        return score;
      }
    },
    compare: (a2, b2) => {
      const sort2 = order2.indexOf(a2) - order2.indexOf(b2);
      return sort2;
    }
  };
};
const kSampleAscVal = "sample-asc";
const kSampleDescVal = "sample-desc";
const kEpochAscVal = "epoch-asc";
const kEpochDescVal = "epoch-desc";
const kScoreAscVal = "score-asc";
const kScoreDescVal = "score-desc";
const kDefaultSort = kSampleAscVal;
const SortFilter = ({ sampleDescriptor, sort: sort2, setSort, epochs }) => {
  var _a;
  const options = [
    { label: "sample asc", val: kSampleAscVal },
    { label: "sample desc", val: kSampleDescVal }
  ];
  if (epochs) {
    options.push({
      label: "epoch asc",
      val: kEpochAscVal
    });
    options.push({
      label: "epoch desc",
      val: kEpochDescVal
    });
  }
  if ((_a = sampleDescriptor == null ? void 0 : sampleDescriptor.scoreDescriptor) == null ? void 0 : _a.compare) {
    options.push({
      label: "score asc",
      val: kScoreAscVal
    });
    options.push({
      label: "score desc",
      val: kScoreDescVal
    });
  }
  return m$1`
    <div style=${{ display: "flex" }}>
      <span
        class="sort-filter-label"
        style=${{
    alignSelf: "center",
    fontSize: FontSize.smaller,
    ...TextStyle.label,
    ...TextStyle.secondary,
    marginRight: "0.3em",
    marginLeft: "0.2em"
  }}
        >Sort:</span
      >
      <select
        class="form-select form-select-sm"
        aria-label=".sort-filter-label"
        style=${{ fontSize: FontSize.smaller }}
        value=${sort2}
        onChange=${(e2) => {
    setSort(e2.target.value);
  }}
      >
        ${options.map((option) => {
    return m$1`<option value="${option.val}">${option.label}</option>`;
  })}
      </select>
    </div>
  `;
};
const byEpoch = (sort2) => {
  return sort2 === kEpochAscVal || sort2 === kEpochDescVal;
};
const bySample = (sort2) => {
  return sort2 === kSampleAscVal || sort2 === kSampleDescVal;
};
const sort = (sort2, samples, sampleDescriptor) => {
  const sorted = samples.sort((a2, b2) => {
    switch (sort2) {
      case kSampleAscVal:
        if (isNumeric(a2.id) && isNumeric(b2.id)) {
          return a2.id - b2.id;
        } else {
          return String(a2.id).localeCompare(String(b2.id));
        }
      case kSampleDescVal:
        if (isNumeric(a2.id) && isNumeric(b2.id)) {
          return b2.id - a2.id;
        } else {
          return String(b2.id).localeCompare(String(a2.id));
        }
      case kEpochAscVal:
        return a2.epoch - b2.epoch;
      case kEpochDescVal:
        return b2.epoch - a2.epoch;
      case kScoreAscVal:
        return sampleDescriptor.scoreDescriptor.compare(
          sampleDescriptor.selectedScore(a2).value,
          sampleDescriptor.selectedScore(b2).value
        );
      case kScoreDescVal:
        return sampleDescriptor.scoreDescriptor.compare(
          sampleDescriptor.selectedScore(b2).value,
          sampleDescriptor.selectedScore(a2).value
        );
    }
  });
  return {
    sorted,
    order: sort2 === kSampleAscVal || sort2 === kEpochAscVal || sort2 === kScoreAscVal ? "asc" : "desc"
  };
};
const LargeModal = (props) => {
  const { id, title, detail, detailTools, footer, onkeyup, children } = props;
  const modalFooter = footer ? m$1`<div class="modal-footer">${footer}</div>` : "";
  const headerEls = [];
  headerEls.push(
    m$1`<div
      class="modal-title"
      style=${{ fontSize: FontSize.smaller, flex: "1 1 auto" }}
    >
      ${title || ""}
    </div>`
  );
  if (detail) {
    headerEls.push(
      m$1`<div
        style=${{
        marginLeft: "auto",
        marginRight: "auto",
        display: "flex",
        flex: "1 1 auto",
        justifyContent: "center"
      }}
      >
        ${detailTools.left ? detailTools.left.map((tool) => {
        return m$1`<${TitleTool} ...${tool} />`;
      }) : ""}
        <div
          style=${{
        fontSize: FontSize.smaller,
        display: "flex",
        alignItems: "center"
      }}
        >
          <div>${detail}</div>
        </div>
        ${detailTools.right ? detailTools.right.map((tool) => {
        return m$1`<${TitleTool} ...${tool} />`;
      }) : ""}
      </div>`
    );
  }
  headerEls.push(m$1`<button
      type="button"
      class="btn btn-close-large-dialog"
      data-bs-dismiss="modal"
      aria-label="Close"
      style=${{
    borderWidth: "0px",
    fontSize: FontSize.larger,
    fontWeight: "300",
    padding: "0em 0.5em",
    flex: 1,
    textAlign: "right"
  }}
    >
      <${HtmlEntity}>&times;</${HtmlEntity}>
    </button>`);
  return m$1`<div
    id=${id}
    class="modal"
    tabindex="0"
    role="dialog"
    onkeyup=${onkeyup}
    style=${{ borderRadius: "none" }}
  >
    <div
      class="modal-dialog modal-dialog-scrollable"
      style=${{
    maxWidth: "100%",
    marginLeft: "var(--bs-modal-margin)",
    marginRight: "var(--bs-modal-margin)"
  }}
      role="document"
    >
      <div class="modal-content" style=${{ height: "100%" }}>
        <div
          class="modal-header"
          style=${{ padding: "0 0 0 1em", display: "flex" }}
        >
          ${headerEls}
        </div>
        <div class="modal-body">${children}</div>
        ${modalFooter}
      </div>
    </div>
  </div>`;
};
const HtmlEntity = ({ children }) => m$1`<span dangerouslySetInnerHTML=${{ __html: children }} />`;
const TitleTool = ({ label, icon, enabled, onclick }) => {
  return m$1`<button
    type="button"
    class="btn btn-outline"
    aria-label=${label}
    onclick=${onclick}
    disabled=${!enabled}
    style=${{
    paddingTop: 0,
    paddingBottom: 0,
    border: "none",
    fontSize: FontSize.small
  }}
  >
    <i class="${icon}" />
  </button>`;
};
const SampleScores = ({ sample, sampleDescriptor, scorer }) => {
  const scores = scorer ? sampleDescriptor.scorer(sample, scorer).scores() : sampleDescriptor.selectedScorer(sample).scores();
  if (scores.length === 1) {
    return scores[0].rendered();
  } else {
    const rows = scores.map((score) => {
      return m$1` <div style=${{ opacity: "0.7" }}>${score.name}</div>
        <div>${score.rendered()}</div>`;
    });
    return m$1`<div
      style=${{
      display: "grid",
      gridTemplateColumns: "max-content max-content",
      columnGap: "1em"
    }}
    >
      ${rows}
    </div>`;
  }
};
const labelStyle = {
  paddingRight: "2em",
  paddingLeft: "0",
  paddingBottom: "0",
  ...TextStyle.label,
  ...TextStyle.secondary
};
const SampleScoreView = ({
  sample,
  sampleDescriptor,
  style,
  scorer
}) => {
  if (!sampleDescriptor) {
    return "";
  }
  const scoreInput = [inputString(sample.input)];
  if (sample.choices && sample.choices.length > 0) {
    scoreInput.push("");
    scoreInput.push(
      ...sample.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      })
    );
  }
  const scorerDescriptor = sampleDescriptor.scorer(sample, scorer);
  const explanation = scorerDescriptor.explanation() || "(No Explanation)";
  const answer = scorerDescriptor.answer();
  return m$1`
    <div
      class="container-fluid"
      style=${{
    paddingTop: "1em",
    paddingLeft: "0",
    fontSize: FontSize.base,
    ...style
  }}
    >
      <div>
        <div style=${{ ...labelStyle }}>Input</div>
        <div>
          <${MarkdownDiv}
            markdown=${scoreInput.join("\n")}
            style=${{ wordBreak: "break-all" }}
          />
        </div>
      </div>

      <table
        class="table"
        style=${{ width: "100%", marginBottom: "0", marginTop: "1em" }}
      >
        <thead style=${{ borderBottomColor: "#00000000" }}>
          <tr>
            <th style=${{ ...labelStyle, fontWeight: "400" }}>Target</th>
            <th
              style=${{ ...labelStyle, paddingBottom: "0", fontWeight: "400" }}
            >
              Answer
            </th>
            <th
              style=${{
    ...labelStyle,
    paddingLeft: "2em",
    paddingBottom: "0",
    fontWeight: "400"
  }}
            >
              Score
            </th>
          </tr>
        </thead>
        <tbody style=${{ borderBottomColor: "#00000000" }}>
          <tr>
            <td
              style=${{
    paddingRight: "2em",
    paddingLeft: "0",
    paddingTop: "0"
  }}
            >
              <${MarkdownDiv}
                markdown=${arrayToString(
    arrayToString((sample == null ? void 0 : sample.target) || "none")
  )}
                style=${{ paddingLeft: "0" }}
                class="no-last-para-padding"
              />
            </td>
            <td style=${{ paddingTop: "0", paddingLeft: "0" }}>
              <${MarkdownDiv}
                class="no-last-para-padding"
                markdown=${shortenCompletion(answer)}
                style=${{ paddingLeft: "0" }}
              />
            </td>
            <td style=${{ paddingLeft: "2em", paddingTop: "0" }}>
              <${SampleScores}
                sample=${sample}
                sampleDescriptor=${sampleDescriptor}
                scorer=${scorer}
              />
            </td>
          </tr>
        </tbody>
      </table>

      ${explanation && explanation !== answer ? m$1`
        <table class="table" style=${{ width: "100%", marginBottom: "0" }}>
              <thead>
                <tr>
                  <th style=${{
    paddingBottom: "0",
    paddingLeft: "0",
    ...labelStyle,
    fontWeight: "400"
  }}>Explanation</th>
                </tr>
              </thead>
              <tbody>
                <td style=${{ paddingLeft: "0" }}>
                  <${MarkdownDiv} markdown=${arrayToString(explanation)} style=${{ paddingLeft: "0" }} class="no-last-para-padding"/>
                </td>
              </tbody>
            </table
          ` : ""}
    </div>
  `;
};
const EventPanel = ({
  id,
  title,
  text,
  icon,
  depth = 0,
  collapse,
  style,
  children
}) => {
  const arrChildren = Array.isArray(children) ? children : [children];
  const filteredArrChilden = arrChildren.filter((child) => !!child);
  const hasCollapse = collapse !== void 0;
  const [collapsed, setCollapsed] = h(!!collapse);
  const pillId = (index) => {
    return `${id}-nav-pill-${index}`;
  };
  const titleEl = title || icon || filteredArrChilden.length > 1 ? m$1`<div
          style=${{
    paddingLeft: "0.5em",
    display: "grid",
    gridTemplateColumns: "max-content minmax(0, max-content) auto minmax(0, max-content) minmax(0, max-content)",
    columnGap: "0.5em",
    fontSize: FontSize.small,
    cursor: hasCollapse ? "pointer" : void 0
  }}
        >
          ${icon ? m$1`<i
                class=${icon || ApplicationIcons.metadata}
                style=${{ ...TextStyle.secondary }}
                onclick=${() => {
    setCollapsed(!collapsed);
  }}
              />` : m$1`<div></div>`}
          <div
            style=${{ ...TextStyle.label, ...TextStyle.secondary }}
            onclick=${() => {
    setCollapsed(!collapsed);
  }}
          >
            ${title}
          </div>
          <div
            onclick=${() => {
    setCollapsed(!collapsed);
  }}
          ></div>
          <div
            style=${{ justifySelf: "end", ...TextStyle.secondary }}
            onclick=${() => {
    setCollapsed(!collapsed);
  }}
          >
            ${text}
          </div>
          <div
            style=${{
    justifySelf: "end",
    display: "flex",
    flexDirection: "columns"
  }}
          >
            ${(!hasCollapse || !collapsed) && filteredArrChilden && filteredArrChilden.length > 1 ? m$1` <${EventNavs}
                  navs=${filteredArrChilden.map((child, index) => {
    var _a;
    const defaultTitle = `Tab ${index}`;
    const title2 = child && typeof child === "object" ? ((_a = child["props"]) == null ? void 0 : _a.name) || defaultTitle : defaultTitle;
    return {
      id: `eventpanel-${id}-${index}`,
      title: title2,
      target: pillId(index)
    };
  })}
                />` : ""}
            ${hasCollapse ? m$1`<i
                  onclick=${() => {
    setCollapsed(!collapsed);
  }}
                  class=${collapsed ? ApplicationIcons.chevron.right : ApplicationIcons.chevron.down}
                />` : ""}
          </div>
        </div>` : "";
  const left_padding = 0.5 + depth * 1.5;
  const card = m$1` <div
    id=${id}
    class="card"
    style=${{
    padding: `0.5em 0.5em 0.5em ${left_padding}em`,
    marginBottom: "-1px",
    ...style
  }}
  >
    ${titleEl}
    ${!hasCollapse || !collapsed ? m$1` <div
          class="card-body tab-content"
          style=${{ padding: 0, marginLeft: "0.5em" }}
        >
          ${filteredArrChilden == null ? void 0 : filteredArrChilden.map((child, index) => {
    return m$1`<div
              id=${pillId(index)}
              class="tab-pane show ${index === 0 ? "active" : ""}"
            >
              ${child}
            </div>`;
  })}
        </div>` : ""}
  </div>`;
  return card;
};
const EventNavs = ({ navs }) => {
  return m$1`<ul
    class="nav nav-pills card-header-pills"
    style=${{
    marginRight: "0",
    alignItems: "flex-start",
    justifyContent: "flex-end"
  }}
    role="tablist"
    aria-orientation="horizontal"
  >
    ${navs.map((nav, index) => {
    return m$1`<${EventNav}
        active=${index === 0}
        id=${nav.id}
        target=${nav.target}
        title=${nav.title}
      />`;
  })}
  </ul>`;
};
const EventNav = ({ target, title, active }) => {
  return m$1`<li class="nav-item">
    <button
      data-bs-toggle="pill"
      data-bs-target="#${target}"
      type="button"
      role="tab"
      aria-controls=${target}
      aria-selected=${active}
      style=${{
    minWidth: "4rem",
    ...TextStyle.label,
    fontSize: FontSize.small,
    padding: "0.1rem  0.6rem",
    borderRadius: "3px"
  }}
      class="nav-link ${active ? "active " : ""}"
    >
      ${title}
    </button>
  </li>`;
};
const MetaDataGrid = ({
  id,
  entries,
  classes,
  context,
  style,
  expanded,
  plain
}) => {
  const baseId = "metadata-grid";
  const cellKeyStyle = {
    fontWeight: "400",
    whiteSpace: "nowrap",
    ...TextStyle.label,
    ...TextStyle.secondary
  };
  const cellValueStyle = {
    whiteSpace: "pre-wrap",
    wordWrap: "anywhere",
    fontSize: FontSize.small
  };
  const cellKeyTextStyle = {
    fontSize: FontSize.small
  };
  const entryRecords = (entries2) => {
    if (!entries2) {
      return [];
    }
    if (!Array.isArray(entries2)) {
      return Object.entries(entries2 || {}).map(([key2, value]) => {
        return { name: key2, value };
      });
    } else {
      return entries2;
    }
  };
  const entryEls = entryRecords(entries).map((entry, index) => {
    const id2 = `${baseId}-value-${index}`;
    return m$1`
      <div
        style=${{
      gridColumn: "1 / -1",
      borderBottom: `${!plain ? "solid 1px var(--bs-light-border-subtle" : ""}`
    }}
      ></div>
      <div
        class="${baseId}-key"
        style=${{ ...cellKeyStyle, ...cellKeyTextStyle }}
      >
        ${entry.name}
      </div>
      <div class="${baseId}-value" style=${{ ...cellValueStyle }}>
        <${RenderedContent}
          id=${id2}
          entry=${entry}
          context=${context}
          options=${{ expanded }}
        />
      </div>
    `;
  });
  return m$1`<div
    ...${{ id }}
    class="${classes || ""}"
    style=${{
    display: "grid",
    gridTemplateColumns: "max-content auto",
    columnGap: "1em",
    ...style
  }}
  >
    ${entryEls}
  </div>`;
};
const EventSection = ({ title, style, children }) => {
  return m$1`<div
    style=${{
    margin: "1em 0 0 0",
    ...style
  }}
  >
    <div
      style=${{
    fontSize: FontSize.smaller,
    ...TextStyle.label,
    fontWeight: 600,
    paddingBottom: "0.3em"
  }}
    >
      ${title}
    </div>
    ${children}
  </div>`;
};
const SampleInitEventView = ({ id, depth, event, stateManager }) => {
  const stateObj = event.state;
  stateManager.setState(stateObj);
  const sections = [];
  if (event.sample.files && Object.keys(event.sample.files).length > 0) {
    sections.push(m$1`<${EventSection} title="Files">
      ${Object.keys(event.sample.files).map((file) => {
      return m$1`<pre style=${{ marginBottom: "0" }}>${file}</pre>`;
    })}
      </${EventSection}>
  `);
  }
  if (event.sample.setup) {
    sections.push(m$1`<${EventSection} title="Setup">
      <pre style=${{ background: "var(--bs-light)", borderRadius: "3px" }}><code class="sourceCode" >${event.sample.setup}</code></pre>
      </${EventSection}>
  `);
  }
  return m$1`
  <${EventPanel} id=${id} depth=${depth}>
    
    <div name="Sample">
      <${ChatView} messages=${stateObj["messages"]}/>
      <div style=${{ marginLeft: "2.1em", marginBottom: "1em" }}>
        ${event.sample.choices ? event.sample.choices.map((choice, index) => {
    return m$1`<div>
                  ${String.fromCharCode(65 + index)}) ${choice}
                </div>`;
  }) : ""}
        <div style=${{ display: "flex", flexWrap: "wrap", gap: "1em", overflowWrap: "break-word" }}>
        ${sections}
        </div>
        <${EventSection} title="Target">
          ${event.sample.target}
        </${EventSection}>
      </div>
    </div>
    ${event.sample.metadata && Object.keys(event.sample.metadata).length > 0 ? m$1`<${MetaDataGrid} name="Metadata" style=${{ margin: "1em 0" }} entries=${event.sample.metadata} />` : ""}

  </${EventPanel}>`;
};
const system_msg_added_sig = {
  type: "system_message",
  signature: {
    remove: ["/messages/0/source"],
    replace: ["/messages/0/role", "/messages/0/content"],
    add: ["/messages/1"]
  },
  render: (resolvedState) => {
    const message = resolvedState["messages"][0];
    return m$1`<${ChatView}
      id="system_msg_event_preview"
      messages=${[message]}
    />`;
  }
};
const tools_choice = {
  type: "tools_choice",
  signature: {
    add: ["/tools/0"],
    replace: ["/tool_choice"],
    remove: []
  },
  render: (resolvedState) => {
    const toolsInfo = {
      "Tool Choice": resolvedState.tool_choice
    };
    if (resolvedState.tools.length > 0) {
      toolsInfo["Tools"] = m$1`<${Tools}
        toolDefinitions=${resolvedState.tools}
      />`;
    }
    return m$1`
      <div
        style=${{
      display: "grid",
      gridTemplateColumns: "max-content max-content",
      columnGap: "1rem",
      margin: "1em 0"
    }}
      >
        ${Object.keys(toolsInfo).map((key2) => {
      return m$1` <div
              style=${{
        fontSize: FontSize.smaller,
        ...TextStyle.label,
        ...TextStyle.secondary
      }}
            >
              ${key2}
            </div>
            <div style=${{ fontSize: FontSize.base }}>${toolsInfo[key2]}</div>`;
    })}
      </div>
    `;
  }
};
const RenderableChangeTypes = [system_msg_added_sig, tools_choice];
const Tools = ({ toolDefinitions }) => {
  return toolDefinitions.map((toolDefinition) => {
    const toolName = toolDefinition.name;
    const toolArgs = Object.keys(toolDefinition.parameters.properties);
    return m$1`<${Tool} toolName=${toolName} toolArgs=${toolArgs} />`;
  });
};
const Tool = ({ toolName, toolArgs }) => {
  const functionCall = toolArgs && toolArgs.length > 0 ? `${toolName}(${toolArgs.join(", ")})` : toolName;
  return m$1`<div>
    <code style=${{ fontSize: FontSize.small, padding: "0" }}
      >${functionCall}</code
    >
  </div>`;
};
class Processor {
  constructor(options) {
    this.selfOptions = options || {};
    this.pipes = {};
  }
  options(options) {
    if (options) {
      this.selfOptions = options;
    }
    return this.selfOptions;
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  pipe(name, pipeArg) {
    let pipe = pipeArg;
    if (typeof name === "string") {
      if (typeof pipe === "undefined") {
        return this.pipes[name];
      } else {
        this.pipes[name] = pipe;
      }
    }
    if (name && name.name) {
      pipe = name;
      if (pipe.processor === this) {
        return pipe;
      }
      this.pipes[pipe.name] = pipe;
    }
    pipe.processor = this;
    return pipe;
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  process(input, pipe) {
    let context = input;
    context.options = this.options();
    let nextPipe = pipe || input.pipe || "default";
    let lastPipe;
    while (nextPipe) {
      if (typeof context.nextAfterChildren !== "undefined") {
        context.next = context.nextAfterChildren;
        context.nextAfterChildren = null;
      }
      if (typeof nextPipe === "string") {
        nextPipe = this.pipe(nextPipe);
      }
      nextPipe.process(context);
      lastPipe = nextPipe;
      nextPipe = null;
      if (context) {
        if (context.next) {
          context = context.next;
          nextPipe = context.pipe || lastPipe;
        }
      }
    }
    return context.hasResult ? context.result : void 0;
  }
}
class Pipe {
  constructor(name) {
    this.name = name;
    this.filters = [];
  }
  process(input) {
    if (!this.processor) {
      throw new Error("add this pipe to a processor before using it");
    }
    const debug = this.debug;
    const length = this.filters.length;
    const context = input;
    for (let index = 0; index < length; index++) {
      const filter = this.filters[index];
      if (debug) {
        this.log(`filter: ${filter.filterName}`);
      }
      filter(context);
      if (typeof context === "object" && context.exiting) {
        context.exiting = false;
        break;
      }
    }
    if (!context.next && this.resultCheck) {
      this.resultCheck(context);
    }
  }
  log(msg) {
    console.log(`[jsondiffpatch] ${this.name} pipe, ${msg}`);
  }
  append(...args) {
    this.filters.push(...args);
    return this;
  }
  prepend(...args) {
    this.filters.unshift(...args);
    return this;
  }
  indexOf(filterName) {
    if (!filterName) {
      throw new Error("a filter name is required");
    }
    for (let index = 0; index < this.filters.length; index++) {
      const filter = this.filters[index];
      if (filter.filterName === filterName) {
        return index;
      }
    }
    throw new Error(`filter not found: ${filterName}`);
  }
  list() {
    return this.filters.map((f2) => f2.filterName);
  }
  after(filterName, ...params) {
    const index = this.indexOf(filterName);
    this.filters.splice(index + 1, 0, ...params);
    return this;
  }
  before(filterName, ...params) {
    const index = this.indexOf(filterName);
    this.filters.splice(index, 0, ...params);
    return this;
  }
  replace(filterName, ...params) {
    const index = this.indexOf(filterName);
    this.filters.splice(index, 1, ...params);
    return this;
  }
  remove(filterName) {
    const index = this.indexOf(filterName);
    this.filters.splice(index, 1);
    return this;
  }
  clear() {
    this.filters.length = 0;
    return this;
  }
  shouldHaveResult(should) {
    if (should === false) {
      this.resultCheck = null;
      return;
    }
    if (this.resultCheck) {
      return;
    }
    this.resultCheck = (context) => {
      if (!context.hasResult) {
        console.log(context);
        const error = new Error(`${this.name} failed`);
        error.noResult = true;
        throw error;
      }
    };
    return this;
  }
}
class Context {
  setResult(result) {
    this.result = result;
    this.hasResult = true;
    return this;
  }
  exit() {
    this.exiting = true;
    return this;
  }
  push(child, name) {
    child.parent = this;
    if (typeof name !== "undefined") {
      child.childName = name;
    }
    child.root = this.root || this;
    child.options = child.options || this.options;
    if (!this.children) {
      this.children = [child];
      this.nextAfterChildren = this.next || null;
      this.next = child;
    } else {
      this.children[this.children.length - 1].next = child;
      this.children.push(child);
    }
    child.next = this;
    return this;
  }
}
function cloneRegExp(re) {
  const regexMatch = /^\/(.*)\/([gimyu]*)$/.exec(re.toString());
  return new RegExp(regexMatch[1], regexMatch[2]);
}
function clone(arg) {
  if (typeof arg !== "object") {
    return arg;
  }
  if (arg === null) {
    return null;
  }
  if (Array.isArray(arg)) {
    return arg.map(clone);
  }
  if (arg instanceof Date) {
    return new Date(arg.getTime());
  }
  if (arg instanceof RegExp) {
    return cloneRegExp(arg);
  }
  const cloned = {};
  for (const name in arg) {
    if (Object.prototype.hasOwnProperty.call(arg, name)) {
      cloned[name] = clone(arg[name]);
    }
  }
  return cloned;
}
class DiffContext extends Context {
  constructor(left2, right2) {
    super();
    this.left = left2;
    this.right = right2;
    this.pipe = "diff";
  }
  setResult(result) {
    if (this.options.cloneDiffValues && typeof result === "object") {
      const clone$1 = typeof this.options.cloneDiffValues === "function" ? this.options.cloneDiffValues : clone;
      if (typeof result[0] === "object") {
        result[0] = clone$1(result[0]);
      }
      if (typeof result[1] === "object") {
        result[1] = clone$1(result[1]);
      }
    }
    return super.setResult(result);
  }
}
class PatchContext extends Context {
  constructor(left2, delta) {
    super();
    this.left = left2;
    this.delta = delta;
    this.pipe = "patch";
  }
}
class ReverseContext extends Context {
  constructor(delta) {
    super();
    this.delta = delta;
    this.pipe = "reverse";
  }
}
const diffFilter$3 = function trivialMatchesDiffFilter(context) {
  if (context.left === context.right) {
    context.setResult(void 0).exit();
    return;
  }
  if (typeof context.left === "undefined") {
    if (typeof context.right === "function") {
      throw new Error("functions are not supported");
    }
    context.setResult([context.right]).exit();
    return;
  }
  if (typeof context.right === "undefined") {
    context.setResult([context.left, 0, 0]).exit();
    return;
  }
  if (typeof context.left === "function" || typeof context.right === "function") {
    throw new Error("functions are not supported");
  }
  context.leftType = context.left === null ? "null" : typeof context.left;
  context.rightType = context.right === null ? "null" : typeof context.right;
  if (context.leftType !== context.rightType) {
    context.setResult([context.left, context.right]).exit();
    return;
  }
  if (context.leftType === "boolean" || context.leftType === "number") {
    context.setResult([context.left, context.right]).exit();
    return;
  }
  if (context.leftType === "object") {
    context.leftIsArray = Array.isArray(context.left);
  }
  if (context.rightType === "object") {
    context.rightIsArray = Array.isArray(context.right);
  }
  if (context.leftIsArray !== context.rightIsArray) {
    context.setResult([context.left, context.right]).exit();
    return;
  }
  if (context.left instanceof RegExp) {
    if (context.right instanceof RegExp) {
      context.setResult([context.left.toString(), context.right.toString()]).exit();
    } else {
      context.setResult([context.left, context.right]).exit();
    }
  }
};
diffFilter$3.filterName = "trivial";
const patchFilter$3 = function trivialMatchesPatchFilter(context) {
  if (typeof context.delta === "undefined") {
    context.setResult(context.left).exit();
    return;
  }
  context.nested = !Array.isArray(context.delta);
  if (context.nested) {
    return;
  }
  const nonNestedDelta = context.delta;
  if (nonNestedDelta.length === 1) {
    context.setResult(nonNestedDelta[0]).exit();
    return;
  }
  if (nonNestedDelta.length === 2) {
    if (context.left instanceof RegExp) {
      const regexArgs = /^\/(.*)\/([gimyu]+)$/.exec(nonNestedDelta[1]);
      if (regexArgs) {
        context.setResult(new RegExp(regexArgs[1], regexArgs[2])).exit();
        return;
      }
    }
    context.setResult(nonNestedDelta[1]).exit();
    return;
  }
  if (nonNestedDelta.length === 3 && nonNestedDelta[2] === 0) {
    context.setResult(void 0).exit();
  }
};
patchFilter$3.filterName = "trivial";
const reverseFilter$3 = function trivialReferseFilter(context) {
  if (typeof context.delta === "undefined") {
    context.setResult(context.delta).exit();
    return;
  }
  context.nested = !Array.isArray(context.delta);
  if (context.nested) {
    return;
  }
  const nonNestedDelta = context.delta;
  if (nonNestedDelta.length === 1) {
    context.setResult([nonNestedDelta[0], 0, 0]).exit();
    return;
  }
  if (nonNestedDelta.length === 2) {
    context.setResult([nonNestedDelta[1], nonNestedDelta[0]]).exit();
    return;
  }
  if (nonNestedDelta.length === 3 && nonNestedDelta[2] === 0) {
    context.setResult([nonNestedDelta[0]]).exit();
  }
};
reverseFilter$3.filterName = "trivial";
const collectChildrenDiffFilter = (context) => {
  if (!context || !context.children) {
    return;
  }
  const length = context.children.length;
  let child;
  let result = context.result;
  for (let index = 0; index < length; index++) {
    child = context.children[index];
    if (typeof child.result === "undefined") {
      continue;
    }
    result = result || {};
    result[child.childName] = child.result;
  }
  if (result && context.leftIsArray) {
    result._t = "a";
  }
  context.setResult(result).exit();
};
collectChildrenDiffFilter.filterName = "collectChildren";
const objectsDiffFilter = (context) => {
  if (context.leftIsArray || context.leftType !== "object") {
    return;
  }
  const left2 = context.left;
  const right2 = context.right;
  let name;
  let child;
  const propertyFilter = context.options.propertyFilter;
  for (name in left2) {
    if (!Object.prototype.hasOwnProperty.call(left2, name)) {
      continue;
    }
    if (propertyFilter && !propertyFilter(name, context)) {
      continue;
    }
    child = new DiffContext(left2[name], right2[name]);
    context.push(child, name);
  }
  for (name in right2) {
    if (!Object.prototype.hasOwnProperty.call(right2, name)) {
      continue;
    }
    if (propertyFilter && !propertyFilter(name, context)) {
      continue;
    }
    if (typeof left2[name] === "undefined") {
      child = new DiffContext(void 0, right2[name]);
      context.push(child, name);
    }
  }
  if (!context.children || context.children.length === 0) {
    context.setResult(void 0).exit();
    return;
  }
  context.exit();
};
objectsDiffFilter.filterName = "objects";
const patchFilter$2 = function nestedPatchFilter(context) {
  if (!context.nested) {
    return;
  }
  const nestedDelta = context.delta;
  if (nestedDelta._t) {
    return;
  }
  const objectDelta = nestedDelta;
  let name;
  let child;
  for (name in objectDelta) {
    child = new PatchContext(context.left[name], objectDelta[name]);
    context.push(child, name);
  }
  context.exit();
};
patchFilter$2.filterName = "objects";
const collectChildrenPatchFilter$1 = function collectChildrenPatchFilter(context) {
  if (!context || !context.children) {
    return;
  }
  const deltaWithChildren = context.delta;
  if (deltaWithChildren._t) {
    return;
  }
  const object = context.left;
  const length = context.children.length;
  let child;
  for (let index = 0; index < length; index++) {
    child = context.children[index];
    const property = child.childName;
    if (Object.prototype.hasOwnProperty.call(context.left, property) && child.result === void 0) {
      delete object[property];
    } else if (object[property] !== child.result) {
      object[property] = child.result;
    }
  }
  context.setResult(object).exit();
};
collectChildrenPatchFilter$1.filterName = "collectChildren";
const reverseFilter$2 = function nestedReverseFilter(context) {
  if (!context.nested) {
    return;
  }
  const nestedDelta = context.delta;
  if (nestedDelta._t) {
    return;
  }
  const objectDelta = context.delta;
  let name;
  let child;
  for (name in objectDelta) {
    child = new ReverseContext(objectDelta[name]);
    context.push(child, name);
  }
  context.exit();
};
reverseFilter$2.filterName = "objects";
const collectChildrenReverseFilter$1 = (context) => {
  if (!context || !context.children) {
    return;
  }
  const deltaWithChildren = context.delta;
  if (deltaWithChildren._t) {
    return;
  }
  const length = context.children.length;
  let child;
  const delta = {};
  for (let index = 0; index < length; index++) {
    child = context.children[index];
    const property = child.childName;
    if (delta[property] !== child.result) {
      delta[property] = child.result;
    }
  }
  context.setResult(delta).exit();
};
collectChildrenReverseFilter$1.filterName = "collectChildren";
const defaultMatch = function(array1, array2, index1, index2) {
  return array1[index1] === array2[index2];
};
const lengthMatrix = function(array1, array2, match, context) {
  const len1 = array1.length;
  const len2 = array2.length;
  let x2, y2;
  const matrix = new Array(len1 + 1);
  for (x2 = 0; x2 < len1 + 1; x2++) {
    matrix[x2] = new Array(len2 + 1);
    for (y2 = 0; y2 < len2 + 1; y2++) {
      matrix[x2][y2] = 0;
    }
  }
  matrix.match = match;
  for (x2 = 1; x2 < len1 + 1; x2++) {
    for (y2 = 1; y2 < len2 + 1; y2++) {
      if (match(array1, array2, x2 - 1, y2 - 1, context)) {
        matrix[x2][y2] = matrix[x2 - 1][y2 - 1] + 1;
      } else {
        matrix[x2][y2] = Math.max(matrix[x2 - 1][y2], matrix[x2][y2 - 1]);
      }
    }
  }
  return matrix;
};
const backtrack = function(matrix, array1, array2, context) {
  let index1 = array1.length;
  let index2 = array2.length;
  const subsequence = {
    sequence: [],
    indices1: [],
    indices2: []
  };
  while (index1 !== 0 && index2 !== 0) {
    const sameLetter = matrix.match(array1, array2, index1 - 1, index2 - 1, context);
    if (sameLetter) {
      subsequence.sequence.unshift(array1[index1 - 1]);
      subsequence.indices1.unshift(index1 - 1);
      subsequence.indices2.unshift(index2 - 1);
      --index1;
      --index2;
    } else {
      const valueAtMatrixAbove = matrix[index1][index2 - 1];
      const valueAtMatrixLeft = matrix[index1 - 1][index2];
      if (valueAtMatrixAbove > valueAtMatrixLeft) {
        --index2;
      } else {
        --index1;
      }
    }
  }
  return subsequence;
};
const get = function(array1, array2, match, context) {
  const innerContext = context || {};
  const matrix = lengthMatrix(array1, array2, match || defaultMatch, innerContext);
  return backtrack(matrix, array1, array2, innerContext);
};
const lcs = {
  get
};
const ARRAY_MOVE = 3;
function arraysHaveMatchByRef(array1, array2, len1, len2) {
  for (let index1 = 0; index1 < len1; index1++) {
    const val1 = array1[index1];
    for (let index2 = 0; index2 < len2; index2++) {
      const val2 = array2[index2];
      if (index1 !== index2 && val1 === val2) {
        return true;
      }
    }
  }
}
function matchItems(array1, array2, index1, index2, context) {
  const value1 = array1[index1];
  const value2 = array2[index2];
  if (value1 === value2) {
    return true;
  }
  if (typeof value1 !== "object" || typeof value2 !== "object") {
    return false;
  }
  const objectHash = context.objectHash;
  if (!objectHash) {
    return context.matchByPosition && index1 === index2;
  }
  context.hashCache1 = context.hashCache1 || [];
  let hash1 = context.hashCache1[index1];
  if (typeof hash1 === "undefined") {
    context.hashCache1[index1] = hash1 = objectHash(value1, index1);
  }
  if (typeof hash1 === "undefined") {
    return false;
  }
  context.hashCache2 = context.hashCache2 || [];
  let hash2 = context.hashCache2[index2];
  if (typeof hash2 === "undefined") {
    context.hashCache2[index2] = hash2 = objectHash(value2, index2);
  }
  if (typeof hash2 === "undefined") {
    return false;
  }
  return hash1 === hash2;
}
const diffFilter$2 = function arraysDiffFilter(context) {
  if (!context.leftIsArray) {
    return;
  }
  const matchContext = {
    objectHash: context.options && context.options.objectHash,
    matchByPosition: context.options && context.options.matchByPosition
  };
  let commonHead = 0;
  let commonTail = 0;
  let index;
  let index1;
  let index2;
  const array1 = context.left;
  const array2 = context.right;
  const len1 = array1.length;
  const len2 = array2.length;
  let child;
  if (len1 > 0 && len2 > 0 && !matchContext.objectHash && typeof matchContext.matchByPosition !== "boolean") {
    matchContext.matchByPosition = !arraysHaveMatchByRef(array1, array2, len1, len2);
  }
  while (commonHead < len1 && commonHead < len2 && matchItems(array1, array2, commonHead, commonHead, matchContext)) {
    index = commonHead;
    child = new DiffContext(array1[index], array2[index]);
    context.push(child, index);
    commonHead++;
  }
  while (commonTail + commonHead < len1 && commonTail + commonHead < len2 && matchItems(array1, array2, len1 - 1 - commonTail, len2 - 1 - commonTail, matchContext)) {
    index1 = len1 - 1 - commonTail;
    index2 = len2 - 1 - commonTail;
    child = new DiffContext(array1[index1], array2[index2]);
    context.push(child, index2);
    commonTail++;
  }
  let result;
  if (commonHead + commonTail === len1) {
    if (len1 === len2) {
      context.setResult(void 0).exit();
      return;
    }
    result = result || {
      _t: "a"
    };
    for (index = commonHead; index < len2 - commonTail; index++) {
      result[index] = [array2[index]];
    }
    context.setResult(result).exit();
    return;
  }
  if (commonHead + commonTail === len2) {
    result = result || {
      _t: "a"
    };
    for (index = commonHead; index < len1 - commonTail; index++) {
      result[`_${index}`] = [array1[index], 0, 0];
    }
    context.setResult(result).exit();
    return;
  }
  delete matchContext.hashCache1;
  delete matchContext.hashCache2;
  const trimmed1 = array1.slice(commonHead, len1 - commonTail);
  const trimmed2 = array2.slice(commonHead, len2 - commonTail);
  const seq = lcs.get(trimmed1, trimmed2, matchItems, matchContext);
  const removedItems = [];
  result = result || {
    _t: "a"
  };
  for (index = commonHead; index < len1 - commonTail; index++) {
    if (seq.indices1.indexOf(index - commonHead) < 0) {
      result[`_${index}`] = [array1[index], 0, 0];
      removedItems.push(index);
    }
  }
  let detectMove = true;
  if (context.options && context.options.arrays && context.options.arrays.detectMove === false) {
    detectMove = false;
  }
  let includeValueOnMove = false;
  if (context.options && context.options.arrays && context.options.arrays.includeValueOnMove) {
    includeValueOnMove = true;
  }
  const removedItemsLength = removedItems.length;
  for (index = commonHead; index < len2 - commonTail; index++) {
    const indexOnArray2 = seq.indices2.indexOf(index - commonHead);
    if (indexOnArray2 < 0) {
      let isMove = false;
      if (detectMove && removedItemsLength > 0) {
        for (let removeItemIndex1 = 0; removeItemIndex1 < removedItemsLength; removeItemIndex1++) {
          index1 = removedItems[removeItemIndex1];
          if (matchItems(trimmed1, trimmed2, index1 - commonHead, index - commonHead, matchContext)) {
            result[`_${index1}`].splice(1, 2, index, ARRAY_MOVE);
            if (!includeValueOnMove) {
              result[`_${index1}`][0] = "";
            }
            index2 = index;
            child = new DiffContext(array1[index1], array2[index2]);
            context.push(child, index2);
            removedItems.splice(removeItemIndex1, 1);
            isMove = true;
            break;
          }
        }
      }
      if (!isMove) {
        result[index] = [array2[index]];
      }
    } else {
      index1 = seq.indices1[indexOnArray2] + commonHead;
      index2 = seq.indices2[indexOnArray2] + commonHead;
      child = new DiffContext(array1[index1], array2[index2]);
      context.push(child, index2);
    }
  }
  context.setResult(result).exit();
};
diffFilter$2.filterName = "arrays";
const compare$1 = {
  numerically(a2, b2) {
    return a2 - b2;
  },
  numericallyBy(name) {
    return (a2, b2) => a2[name] - b2[name];
  }
};
const patchFilter$1 = function nestedPatchFilter2(context) {
  if (!context.nested) {
    return;
  }
  const nestedDelta = context.delta;
  if (nestedDelta._t !== "a") {
    return;
  }
  let index;
  let index1;
  const delta = nestedDelta;
  const array = context.left;
  let toRemove = [];
  let toInsert = [];
  const toModify = [];
  for (index in delta) {
    if (index !== "_t") {
      if (index[0] === "_") {
        const removedOrMovedIndex = index;
        if (delta[removedOrMovedIndex][2] === 0 || delta[removedOrMovedIndex][2] === ARRAY_MOVE) {
          toRemove.push(parseInt(index.slice(1), 10));
        } else {
          throw new Error(`only removal or move can be applied at original array indices, invalid diff type: ${delta[removedOrMovedIndex][2]}`);
        }
      } else {
        const numberIndex = index;
        if (delta[numberIndex].length === 1) {
          toInsert.push({
            index: parseInt(numberIndex, 10),
            value: delta[numberIndex][0]
          });
        } else {
          toModify.push({
            index: parseInt(numberIndex, 10),
            delta: delta[numberIndex]
          });
        }
      }
    }
  }
  toRemove = toRemove.sort(compare$1.numerically);
  for (index = toRemove.length - 1; index >= 0; index--) {
    index1 = toRemove[index];
    const indexDiff = delta[`_${index1}`];
    const removedValue = array.splice(index1, 1)[0];
    if (indexDiff[2] === ARRAY_MOVE) {
      toInsert.push({
        index: indexDiff[1],
        value: removedValue
      });
    }
  }
  toInsert = toInsert.sort(compare$1.numericallyBy("index"));
  const toInsertLength = toInsert.length;
  for (index = 0; index < toInsertLength; index++) {
    const insertion = toInsert[index];
    array.splice(insertion.index, 0, insertion.value);
  }
  const toModifyLength = toModify.length;
  let child;
  if (toModifyLength > 0) {
    for (index = 0; index < toModifyLength; index++) {
      const modification = toModify[index];
      child = new PatchContext(array[modification.index], modification.delta);
      context.push(child, modification.index);
    }
  }
  if (!context.children) {
    context.setResult(array).exit();
    return;
  }
  context.exit();
};
patchFilter$1.filterName = "arrays";
const collectChildrenPatchFilter2 = function collectChildrenPatchFilter3(context) {
  if (!context || !context.children) {
    return;
  }
  const deltaWithChildren = context.delta;
  if (deltaWithChildren._t !== "a") {
    return;
  }
  const array = context.left;
  const length = context.children.length;
  let child;
  for (let index = 0; index < length; index++) {
    child = context.children[index];
    const arrayIndex = child.childName;
    array[arrayIndex] = child.result;
  }
  context.setResult(array).exit();
};
collectChildrenPatchFilter2.filterName = "arraysCollectChildren";
const reverseFilter$1 = function arraysReverseFilter(context) {
  if (!context.nested) {
    const nonNestedDelta = context.delta;
    if (nonNestedDelta[2] === ARRAY_MOVE) {
      const arrayMoveDelta = nonNestedDelta;
      context.newName = `_${arrayMoveDelta[1]}`;
      context.setResult([
        arrayMoveDelta[0],
        parseInt(context.childName.substring(1), 10),
        ARRAY_MOVE
      ]).exit();
    }
    return;
  }
  const nestedDelta = context.delta;
  if (nestedDelta._t !== "a") {
    return;
  }
  const arrayDelta = nestedDelta;
  let name;
  let child;
  for (name in arrayDelta) {
    if (name === "_t") {
      continue;
    }
    child = new ReverseContext(arrayDelta[name]);
    context.push(child, name);
  }
  context.exit();
};
reverseFilter$1.filterName = "arrays";
const reverseArrayDeltaIndex = (delta, index, itemDelta) => {
  if (typeof index === "string" && index[0] === "_") {
    return parseInt(index.substring(1), 10);
  } else if (Array.isArray(itemDelta) && itemDelta[2] === 0) {
    return `_${index}`;
  }
  let reverseIndex = +index;
  for (const deltaIndex in delta) {
    const deltaItem = delta[deltaIndex];
    if (Array.isArray(deltaItem)) {
      if (deltaItem[2] === ARRAY_MOVE) {
        const moveFromIndex = parseInt(deltaIndex.substring(1), 10);
        const moveToIndex = deltaItem[1];
        if (moveToIndex === +index) {
          return moveFromIndex;
        }
        if (moveFromIndex <= reverseIndex && moveToIndex > reverseIndex) {
          reverseIndex++;
        } else if (moveFromIndex >= reverseIndex && moveToIndex < reverseIndex) {
          reverseIndex--;
        }
      } else if (deltaItem[2] === 0) {
        const deleteIndex = parseInt(deltaIndex.substring(1), 10);
        if (deleteIndex <= reverseIndex) {
          reverseIndex++;
        }
      } else if (deltaItem.length === 1 && parseInt(deltaIndex, 10) <= reverseIndex) {
        reverseIndex--;
      }
    }
  }
  return reverseIndex;
};
const collectChildrenReverseFilter = (context) => {
  if (!context || !context.children) {
    return;
  }
  const deltaWithChildren = context.delta;
  if (deltaWithChildren._t !== "a") {
    return;
  }
  const arrayDelta = deltaWithChildren;
  const length = context.children.length;
  let child;
  const delta = {
    _t: "a"
  };
  for (let index = 0; index < length; index++) {
    child = context.children[index];
    let name = child.newName;
    if (typeof name === "undefined") {
      name = reverseArrayDeltaIndex(arrayDelta, child.childName, child.result);
    }
    if (delta[name] !== child.result) {
      delta[name] = child.result;
    }
  }
  context.setResult(delta).exit();
};
collectChildrenReverseFilter.filterName = "arraysCollectChildren";
const diffFilter$1 = function datesDiffFilter(context) {
  if (context.left instanceof Date) {
    if (context.right instanceof Date) {
      if (context.left.getTime() !== context.right.getTime()) {
        context.setResult([context.left, context.right]);
      } else {
        context.setResult(void 0);
      }
    } else {
      context.setResult([context.left, context.right]);
    }
    context.exit();
  } else if (context.right instanceof Date) {
    context.setResult([context.left, context.right]).exit();
  }
};
diffFilter$1.filterName = "dates";
const TEXT_DIFF = 2;
const DEFAULT_MIN_LENGTH = 60;
let cachedDiffPatch = null;
function getDiffMatchPatch(options, required) {
  var _a;
  if (!cachedDiffPatch) {
    let instance;
    if ((_a = options === null || options === void 0 ? void 0 : options.textDiff) === null || _a === void 0 ? void 0 : _a.diffMatchPatch) {
      instance = new options.textDiff.diffMatchPatch();
    } else {
      if (!required) {
        return null;
      }
      const error = new Error("The diff-match-patch library was not provided. Pass the library in through the options or use the `jsondiffpatch/with-text-diffs` entry-point.");
      error.diff_match_patch_not_found = true;
      throw error;
    }
    cachedDiffPatch = {
      diff: function(txt1, txt2) {
        return instance.patch_toText(instance.patch_make(txt1, txt2));
      },
      patch: function(txt1, patch) {
        const results = instance.patch_apply(instance.patch_fromText(patch), txt1);
        for (let i2 = 0; i2 < results[1].length; i2++) {
          if (!results[1][i2]) {
            const error = new Error("text patch failed");
            error.textPatchFailed = true;
          }
        }
        return results[0];
      }
    };
  }
  return cachedDiffPatch;
}
const diffFilter = function textsDiffFilter(context) {
  if (context.leftType !== "string") {
    return;
  }
  const left2 = context.left;
  const right2 = context.right;
  const minLength = context.options && context.options.textDiff && context.options.textDiff.minLength || DEFAULT_MIN_LENGTH;
  if (left2.length < minLength || right2.length < minLength) {
    context.setResult([left2, right2]).exit();
    return;
  }
  const diffMatchPatch = getDiffMatchPatch(context.options);
  if (!diffMatchPatch) {
    context.setResult([left2, right2]).exit();
    return;
  }
  const diff2 = diffMatchPatch.diff;
  context.setResult([diff2(left2, right2), 0, TEXT_DIFF]).exit();
};
diffFilter.filterName = "texts";
const patchFilter = function textsPatchFilter(context) {
  if (context.nested) {
    return;
  }
  const nonNestedDelta = context.delta;
  if (nonNestedDelta[2] !== TEXT_DIFF) {
    return;
  }
  const textDiffDelta = nonNestedDelta;
  const patch = getDiffMatchPatch(context.options, true).patch;
  context.setResult(patch(context.left, textDiffDelta[0])).exit();
};
patchFilter.filterName = "texts";
const textDeltaReverse = function(delta) {
  let i2;
  let l2;
  let line2;
  let lineTmp;
  let header = null;
  const headerRegex = /^@@ +-(\d+),(\d+) +\+(\d+),(\d+) +@@$/;
  let lineHeader;
  const lines = delta.split("\n");
  for (i2 = 0, l2 = lines.length; i2 < l2; i2++) {
    line2 = lines[i2];
    const lineStart = line2.slice(0, 1);
    if (lineStart === "@") {
      header = headerRegex.exec(line2);
      lineHeader = i2;
      lines[lineHeader] = "@@ -" + header[3] + "," + header[4] + " +" + header[1] + "," + header[2] + " @@";
    } else if (lineStart === "+") {
      lines[i2] = "-" + lines[i2].slice(1);
      if (lines[i2 - 1].slice(0, 1) === "+") {
        lineTmp = lines[i2];
        lines[i2] = lines[i2 - 1];
        lines[i2 - 1] = lineTmp;
      }
    } else if (lineStart === "-") {
      lines[i2] = "+" + lines[i2].slice(1);
    }
  }
  return lines.join("\n");
};
const reverseFilter = function textsReverseFilter(context) {
  if (context.nested) {
    return;
  }
  const nonNestedDelta = context.delta;
  if (nonNestedDelta[2] !== TEXT_DIFF) {
    return;
  }
  const textDiffDelta = nonNestedDelta;
  context.setResult([textDeltaReverse(textDiffDelta[0]), 0, TEXT_DIFF]).exit();
};
reverseFilter.filterName = "texts";
class DiffPatcher {
  constructor(options) {
    this.processor = new Processor(options);
    this.processor.pipe(new Pipe("diff").append(collectChildrenDiffFilter, diffFilter$3, diffFilter$1, diffFilter, objectsDiffFilter, diffFilter$2).shouldHaveResult());
    this.processor.pipe(new Pipe("patch").append(collectChildrenPatchFilter$1, collectChildrenPatchFilter2, patchFilter$3, patchFilter, patchFilter$2, patchFilter$1).shouldHaveResult());
    this.processor.pipe(new Pipe("reverse").append(collectChildrenReverseFilter$1, collectChildrenReverseFilter, reverseFilter$3, reverseFilter, reverseFilter$2, reverseFilter$1).shouldHaveResult());
  }
  options(options) {
    return this.processor.options(options);
  }
  diff(left2, right2) {
    return this.processor.process(new DiffContext(left2, right2));
  }
  patch(left2, delta) {
    return this.processor.process(new PatchContext(left2, delta));
  }
  reverse(delta) {
    return this.processor.process(new ReverseContext(delta));
  }
  unpatch(right2, delta) {
    return this.patch(right2, this.reverse(delta));
  }
  clone(value) {
    return clone(value);
  }
}
let defaultInstance$1;
function diff(left2, right2) {
  if (!defaultInstance$1) {
    defaultInstance$1 = new DiffPatcher();
  }
  return defaultInstance$1.diff(left2, right2);
}
const trimUnderscore = (str) => {
  if (str.substring(0, 1) === "_") {
    return str.slice(1);
  }
  return str;
};
const arrayKeyToSortNumber = (key2) => {
  if (key2 === "_t") {
    return -1;
  } else {
    if (key2.substring(0, 1) === "_") {
      return parseInt(key2.slice(1), 10);
    } else {
      return parseInt(key2, 10) + 0.1;
    }
  }
};
const arrayKeyComparer = (key1, key2) => arrayKeyToSortNumber(key1) - arrayKeyToSortNumber(key2);
class BaseFormatter {
  format(delta, left2) {
    const context = {};
    this.prepareContext(context);
    const preparedContext = context;
    this.recurse(preparedContext, delta, left2);
    return this.finalize(preparedContext);
  }
  prepareContext(context) {
    context.buffer = [];
    context.out = function(...args) {
      this.buffer.push(...args);
    };
  }
  typeFormattterNotFound(context, deltaType) {
    throw new Error(`cannot format delta type: ${deltaType}`);
  }
  /* eslint-disable @typescript-eslint/no-unused-vars */
  typeFormattterErrorFormatter(context, err, delta, leftValue, key2, leftKey, movedFrom) {
  }
  /* eslint-enable @typescript-eslint/no-unused-vars */
  finalize({ buffer: buffer2 }) {
    if (Array.isArray(buffer2)) {
      return buffer2.join("");
    }
  }
  recurse(context, delta, left2, key2, leftKey, movedFrom, isLast) {
    const useMoveOriginHere = delta && movedFrom;
    const leftValue = useMoveOriginHere ? movedFrom.value : left2;
    if (typeof delta === "undefined" && typeof key2 === "undefined") {
      return void 0;
    }
    const type = this.getDeltaType(delta, movedFrom);
    const nodeType = type === "node" ? delta._t === "a" ? "array" : "object" : "";
    if (typeof key2 !== "undefined") {
      this.nodeBegin(context, key2, leftKey, type, nodeType, isLast);
    } else {
      this.rootBegin(context, type, nodeType);
    }
    let typeFormattter;
    try {
      typeFormattter = type !== "unknown" ? this[`format_${type}`] : this.typeFormattterNotFound(context, type);
      typeFormattter.call(this, context, delta, leftValue, key2, leftKey, movedFrom);
    } catch (err) {
      this.typeFormattterErrorFormatter(context, err, delta, leftValue, key2, leftKey, movedFrom);
      if (typeof console !== "undefined" && console.error) {
        console.error(err.stack);
      }
    }
    if (typeof key2 !== "undefined") {
      this.nodeEnd(context, key2, leftKey, type, nodeType, isLast);
    } else {
      this.rootEnd(context, type, nodeType);
    }
  }
  formatDeltaChildren(context, delta, left2) {
    this.forEachDeltaKey(delta, left2, (key2, leftKey, movedFrom, isLast) => {
      this.recurse(context, delta[key2], left2 ? left2[leftKey] : void 0, key2, leftKey, movedFrom, isLast);
    });
  }
  forEachDeltaKey(delta, left2, fn2) {
    const keys = Object.keys(delta);
    const arrayKeys = delta._t === "a";
    const moveDestinations = {};
    let name;
    if (typeof left2 !== "undefined") {
      for (name in left2) {
        if (Object.prototype.hasOwnProperty.call(left2, name)) {
          if (typeof delta[name] === "undefined" && (!arrayKeys || typeof delta[`_${name}`] === "undefined")) {
            keys.push(name);
          }
        }
      }
    }
    for (name in delta) {
      if (Object.prototype.hasOwnProperty.call(delta, name)) {
        const value = delta[name];
        if (Array.isArray(value) && value[2] === 3) {
          const movedDelta = value;
          moveDestinations[`${movedDelta[1]}`] = {
            key: name,
            value: left2 && left2[parseInt(name.substring(1), 10)]
          };
          if (this.includeMoveDestinations !== false) {
            if (typeof left2 === "undefined" && typeof delta[movedDelta[1]] === "undefined") {
              keys.push(movedDelta[1].toString());
            }
          }
        }
      }
    }
    if (arrayKeys) {
      keys.sort(arrayKeyComparer);
    } else {
      keys.sort();
    }
    for (let index = 0, length = keys.length; index < length; index++) {
      const key2 = keys[index];
      if (arrayKeys && key2 === "_t") {
        continue;
      }
      const leftKey = arrayKeys ? parseInt(trimUnderscore(key2), 10) : key2;
      const isLast = index === length - 1;
      fn2(key2, leftKey, moveDestinations[leftKey], isLast);
    }
  }
  getDeltaType(delta, movedFrom) {
    if (typeof delta === "undefined") {
      if (typeof movedFrom !== "undefined") {
        return "movedestination";
      }
      return "unchanged";
    }
    if (Array.isArray(delta)) {
      if (delta.length === 1) {
        return "added";
      }
      if (delta.length === 2) {
        return "modified";
      }
      if (delta.length === 3 && delta[2] === 0) {
        return "deleted";
      }
      if (delta.length === 3 && delta[2] === 2) {
        return "textdiff";
      }
      if (delta.length === 3 && delta[2] === 3) {
        return "moved";
      }
    } else if (typeof delta === "object") {
      return "node";
    }
    return "unknown";
  }
  parseTextDiff(value) {
    const output = [];
    const lines = value.split("\n@@ ");
    for (let i2 = 0, l2 = lines.length; i2 < l2; i2++) {
      const line2 = lines[i2];
      const lineOutput = {
        pieces: []
      };
      const location = /^(?:@@ )?[-+]?(\d+),(\d+)/.exec(line2).slice(1);
      lineOutput.location = {
        line: location[0],
        chr: location[1]
      };
      const pieces = line2.split("\n").slice(1);
      for (let pieceIndex = 0, piecesLength = pieces.length; pieceIndex < piecesLength; pieceIndex++) {
        const piece = pieces[pieceIndex];
        if (!piece.length) {
          continue;
        }
        const pieceOutput = {
          type: "context"
        };
        if (piece.substring(0, 1) === "+") {
          pieceOutput.type = "added";
        } else if (piece.substring(0, 1) === "-") {
          pieceOutput.type = "deleted";
        }
        pieceOutput.text = piece.slice(1);
        lineOutput.pieces.push(pieceOutput);
      }
      output.push(lineOutput);
    }
    return output;
  }
}
class HtmlFormatter extends BaseFormatter {
  typeFormattterErrorFormatter(context, err) {
    context.out(`<pre class="jsondiffpatch-error">${err}</pre>`);
  }
  formatValue(context, value) {
    context.out(`<pre>${htmlEscape(JSON.stringify(value, null, 2))}</pre>`);
  }
  formatTextDiffString(context, value) {
    const lines = this.parseTextDiff(value);
    context.out('<ul class="jsondiffpatch-textdiff">');
    for (let i2 = 0, l2 = lines.length; i2 < l2; i2++) {
      const line2 = lines[i2];
      context.out(`<li><div class="jsondiffpatch-textdiff-location"><span class="jsondiffpatch-textdiff-line-number">${line2.location.line}</span><span class="jsondiffpatch-textdiff-char">${line2.location.chr}</span></div><div class="jsondiffpatch-textdiff-line">`);
      const pieces = line2.pieces;
      for (let pieceIndex = 0, piecesLength = pieces.length; pieceIndex < piecesLength; pieceIndex++) {
        const piece = pieces[pieceIndex];
        context.out(`<span class="jsondiffpatch-textdiff-${piece.type}">${htmlEscape(decodeURI(piece.text))}</span>`);
      }
      context.out("</div></li>");
    }
    context.out("</ul>");
  }
  rootBegin(context, type, nodeType) {
    const nodeClass = `jsondiffpatch-${type}${nodeType ? ` jsondiffpatch-child-node-type-${nodeType}` : ""}`;
    context.out(`<div class="jsondiffpatch-delta ${nodeClass}">`);
  }
  rootEnd(context) {
    context.out(`</div>${context.hasArrows ? `<script type="text/javascript">setTimeout(${adjustArrows.toString()},10);<\/script>` : ""}`);
  }
  nodeBegin(context, key2, leftKey, type, nodeType) {
    const nodeClass = `jsondiffpatch-${type}${nodeType ? ` jsondiffpatch-child-node-type-${nodeType}` : ""}`;
    context.out(`<li class="${nodeClass}" data-key="${leftKey}"><div class="jsondiffpatch-property-name">${leftKey}</div>`);
  }
  nodeEnd(context) {
    context.out("</li>");
  }
  format_unchanged(context, delta, left2) {
    if (typeof left2 === "undefined") {
      return;
    }
    context.out('<div class="jsondiffpatch-value">');
    this.formatValue(context, left2);
    context.out("</div>");
  }
  format_movedestination(context, delta, left2) {
    if (typeof left2 === "undefined") {
      return;
    }
    context.out('<div class="jsondiffpatch-value">');
    this.formatValue(context, left2);
    context.out("</div>");
  }
  format_node(context, delta, left2) {
    const nodeType = delta._t === "a" ? "array" : "object";
    context.out(`<ul class="jsondiffpatch-node jsondiffpatch-node-type-${nodeType}">`);
    this.formatDeltaChildren(context, delta, left2);
    context.out("</ul>");
  }
  format_added(context, delta) {
    context.out('<div class="jsondiffpatch-value">');
    this.formatValue(context, delta[0]);
    context.out("</div>");
  }
  format_modified(context, delta) {
    context.out('<div class="jsondiffpatch-value jsondiffpatch-left-value">');
    this.formatValue(context, delta[0]);
    context.out('</div><div class="jsondiffpatch-value jsondiffpatch-right-value">');
    this.formatValue(context, delta[1]);
    context.out("</div>");
  }
  format_deleted(context, delta) {
    context.out('<div class="jsondiffpatch-value">');
    this.formatValue(context, delta[0]);
    context.out("</div>");
  }
  format_moved(context, delta) {
    context.out('<div class="jsondiffpatch-value">');
    this.formatValue(context, delta[0]);
    context.out(`</div><div class="jsondiffpatch-moved-destination">${delta[1]}</div>`);
    context.out(
      /* jshint multistr: true */
      `<div class="jsondiffpatch-arrow" style="position: relative; left: -34px;">
          <svg width="30" height="60" style="position: absolute; display: none;">
          <defs>
              <marker id="markerArrow" markerWidth="8" markerHeight="8"
                 refx="2" refy="4"
                     orient="auto" markerUnits="userSpaceOnUse">
                  <path d="M1,1 L1,7 L7,4 L1,1" style="fill: #339;" />
              </marker>
          </defs>
          <path d="M30,0 Q-10,25 26,50"
            style="stroke: #88f; stroke-width: 2px; fill: none; stroke-opacity: 0.5; marker-end: url(#markerArrow);"
          ></path>
          </svg>
      </div>`
    );
    context.hasArrows = true;
  }
  format_textdiff(context, delta) {
    context.out('<div class="jsondiffpatch-value">');
    this.formatTextDiffString(context, delta[0]);
    context.out("</div>");
  }
}
function htmlEscape(text) {
  let html = text;
  const replacements = [
    [/&/g, "&amp;"],
    [/</g, "&lt;"],
    [/>/g, "&gt;"],
    [/'/g, "&apos;"],
    [/"/g, "&quot;"]
  ];
  for (let i2 = 0; i2 < replacements.length; i2++) {
    html = html.replace(replacements[i2][0], replacements[i2][1]);
  }
  return html;
}
const adjustArrows = function jsondiffpatchHtmlFormatterAdjustArrows(nodeArg) {
  const node = nodeArg || document;
  const getElementText = ({ textContent, innerText }) => textContent || innerText;
  const eachByQuery = (el, query, fn2) => {
    const elems = el.querySelectorAll(query);
    for (let i2 = 0, l2 = elems.length; i2 < l2; i2++) {
      fn2(elems[i2]);
    }
  };
  const eachChildren = ({ children }, fn2) => {
    for (let i2 = 0, l2 = children.length; i2 < l2; i2++) {
      fn2(children[i2], i2);
    }
  };
  eachByQuery(node, ".jsondiffpatch-arrow", ({ parentNode, children, style }) => {
    const arrowParent = parentNode;
    const svg = children[0];
    const path = svg.children[1];
    svg.style.display = "none";
    const destination = getElementText(arrowParent.querySelector(".jsondiffpatch-moved-destination"));
    const container = arrowParent.parentNode;
    let destinationElem;
    eachChildren(container, (child) => {
      if (child.getAttribute("data-key") === destination) {
        destinationElem = child;
      }
    });
    if (!destinationElem) {
      return;
    }
    try {
      const distance = destinationElem.offsetTop - arrowParent.offsetTop;
      svg.setAttribute("height", `${Math.abs(distance) + 6}`);
      style.top = `${-8 + (distance > 0 ? 0 : distance)}px`;
      const curve = distance > 0 ? `M30,0 Q-10,${Math.round(distance / 2)} 26,${distance - 4}` : `M30,${-distance} Q-10,${Math.round(-distance / 2)} 26,4`;
      path.setAttribute("d", curve);
      svg.style.display = "";
    } catch (err) {
    }
  });
};
let defaultInstance;
function format(delta, left2) {
  if (!defaultInstance) {
    defaultInstance = new HtmlFormatter();
  }
  return defaultInstance.format(delta, left2);
}
const StateDiffView = ({ starting, ending, style }) => {
  const changes = diff(unescapeNewlines(starting), unescapeNewlines(ending));
  const html_result = format(changes);
  return m$1`<div
    dangerouslySetInnerHTML=${{ __html: unescapeNewlines(html_result) }}
    style=${{ style }}
  ></div>`;
};
function unescapeNewlines(obj) {
  if (typeof obj === "string") {
    return obj.replace(/\\n/g, "\n");
  } else if (typeof obj === "object") {
    for (let key2 in obj) {
      obj[key2] = unescapeNewlines(obj[key2]);
    }
  }
  return obj;
}
const StateEventView = ({ id, event, depth, stateManager }) => {
  const startingState = stateManager.getState();
  const resolvedState = stateManager.applyChanges(event.changes);
  const summary = summarizeChanges(event.changes);
  const tabs = [
    m$1`<${StateDiffView}
      starting=${startingState}
      ending=${resolvedState}
      name="Diff"
      style=${{ margin: "1em 0" }}
    />`
  ];
  const changePreview = generatePreview(event.changes, resolvedState);
  if (changePreview) {
    tabs.unshift(
      m$1`<div name="Summary" style=${{ margin: "1em 0" }}>
        ${changePreview}
      </div>`
    );
  }
  const title = event.event === "state" ? "State Updated" : "Store Updated";
  return m$1`
  <${EventPanel} id=${id} title="${title}" icon=${ApplicationIcons.metadata} text=${tabs.length === 1 ? summary : void 0} depth=${depth} collapse=${changePreview === void 0 ? true : void 0}>
    ${tabs}
  </${EventPanel}>`;
};
const generatePreview = (changes, resolvedState) => {
  for (const changeType of RenderableChangeTypes) {
    const requiredMatchCount = changeType.signature.remove.length + changeType.signature.replace.length + changeType.signature.add.length;
    let matchingOps = 0;
    for (const change of changes) {
      if (changeType.signature.remove.includes(change.path) || changeType.signature.replace.includes(change.path) || changeType.signature.add.includes(change.path)) {
        matchingOps++;
      }
      if (matchingOps === requiredMatchCount) {
        return changeType.render(resolvedState);
      }
    }
  }
  return void 0;
};
const summarizeChanges = (changes) => {
  const changeMap = {
    add: [],
    copy: [],
    move: [],
    replace: [],
    remove: [],
    test: []
  };
  for (const change of changes) {
    changeMap[change.op].push(change.path);
  }
  const changeList = [];
  const totalOpCount = Object.keys(changeMap).reduce((prev, current) => {
    return prev + changeMap[current].length;
  }, 0);
  if (totalOpCount > 2) {
    Object.keys(changeMap).forEach((key2) => {
      const opChanges = changeMap[key2];
      if (opChanges.length > 0) {
        changeList.push(`${key2} ${opChanges.length}`);
      }
    });
  } else {
    Object.keys(changeMap).forEach((key2) => {
      const opChanges = changeMap[key2];
      if (opChanges.length > 0) {
        changeList.push(`${key2} ${opChanges.join(", ")}`);
      }
    });
  }
  return changeList.join(", ");
};
const StepEventView = ({ depth, event }) => {
  const descriptor = stepDescriptor(event);
  if (event.action === "end") {
    if (descriptor.endSpace) {
      return m$1`<div style=${{ height: "1.5em" }}></div>`;
    } else {
      return m$1``;
    }
  }
  const title = descriptor.name || `${event.type ? event.type + ": " : "Step: "}${event.name}`;
  return m$1`<${EventPanel}
    title="${title}"
    depth=${depth}
    icon=${descriptor.icon}
    style=${descriptor.style}
  />`;
};
const rootStepStyle = {
  backgroundColor: "var(--bs-light)",
  fontWeight: "600"
};
const stepDescriptor = (event) => {
  const rootStepDescriptor = {
    style: rootStepStyle,
    endSpace: true
  };
  if (event.type === "solver") {
    switch (event.name) {
      case "chain_of_thought":
        return {
          icon: ApplicationIcons.solvers.chain_of_thought,
          ...rootStepDescriptor
        };
      case "generate":
        return {
          icon: ApplicationIcons.solvers.generate,
          ...rootStepDescriptor
        };
      case "self_critique":
        return {
          icon: ApplicationIcons.solvers.self_critique,
          ...rootStepDescriptor
        };
      case "system_message":
        return {
          icon: ApplicationIcons.solvers.system_message,
          ...rootStepDescriptor
        };
      case "use_tools":
        return {
          icon: ApplicationIcons.solvers.use_tools,
          ...rootStepDescriptor
        };
      case "multiple_choice":
        return {
          icon: ApplicationIcons["multiple-choice"],
          ...rootStepDescriptor
        };
      default:
        return {
          icon: ApplicationIcons.solvers.default,
          ...rootStepDescriptor
        };
    }
  } else if (event.type === "scorer") {
    return {
      icon: ApplicationIcons.scorer,
      ...rootStepDescriptor
    };
  } else {
    switch (event.name) {
      case "sample_init":
        return {
          icon: ApplicationIcons.sample,
          ...rootStepDescriptor,
          name: "Sample Init"
        };
      default:
        return {
          icon: ApplicationIcons.step,
          style: {},
          endSpace: false
        };
    }
  }
};
const SubtaskEventView = ({ id, depth, event, stateManager }) => {
  return m$1`
    <${EventPanel} id=${id} depth=${depth} title="Subtask: ${event.name}" icon=${ApplicationIcons.subtask}>
      <${SubtaskSummary} name="Summary"  input=${event.input} result=${event.result}/>
      ${event.events.length > 0 ? m$1`<${TranscriptView}
              id="${id}-subtask"
              name="Transcript"
              events=${event.events}
              stateManager=${stateManager}
            />` : ""}
    </${EventPanel}>`;
};
const SubtaskSummary = ({ input, result }) => {
  result = typeof result === "object" ? result : { result };
  return m$1` <div
    style=${{
    display: "grid",
    gridTemplateColumns: "minmax(0,max-content) max-content minmax(0,max-content)",
    columnGap: "1em",
    margin: "1em 0"
  }}
  >
    <div style=${{ ...TextStyle.label }}>Input</div>
    <div style=${{ fontSize: FontSize.large, padding: "0 2em" }}>
      <i class="${ApplicationIcons.arrows.right}" />
    </div>

    <div style=${{ ...TextStyle.label }}>Output</div>
    <${Rendered} values=${input} />
    <div></div>
    <${Rendered} values=${result} />
  </div>`;
};
const Rendered = ({ values }) => {
  if (Array.isArray(values)) {
    return values.map((val) => {
      return m$1`<${Rendered} values=${val} />`;
    });
  } else if (values && typeof values === "object") {
    return m$1`<${MetaDataView} entries=${values} />`;
  } else {
    return values;
  }
};
const ModelTokenTable = ({ model_usage }) => {
  return m$1`
  <${TokenTable}>
    <${TokenHeader}/>
    <tbody>
    ${Object.keys(model_usage).map((key2) => {
    return m$1`<${TokenRow} model=${key2} usage=${model_usage[key2]} />`;
  })}
    </tbody>
  </${TokenTable}>
  `;
};
const TokenTable = ({ children }) => {
  return m$1`<table
    class="table table-sm"
    style=${{ width: "100%", fontSize: FontSize.smaller, marginTop: "0.7rem" }}
  >
    ${children}
  </table>`;
};
const thStyle = {
  padding: 0,
  fontWeight: 300,
  fontSize: FontSize.small,
  ...TextStyle.label,
  ...TextStyle.secondary
};
const TokenHeader = () => {
  return m$1`<thead>
    <tr>
      <td></td>
      <td
        colspan="3"
        align="center"
        class="card-subheading"
        style=${{
    paddingBottom: "0.7rem",
    fontSize: FontSize.small,
    ...TextStyle.label,
    ...TextStyle.secondary
  }}
      >
        Tokens
      </td>
    </tr>
    <tr>
      <th style=${thStyle}>Model</th>
      <th style=${thStyle}>Usage</th>
    </tr>
  </thead>`;
};
const TokenRow = ({ model, usage }) => {
  return m$1`<tr>
    <td>${model}</td>
    <td>
      <${ModelUsagePanel} usage=${usage} />
    </td>
  </tr>`;
};
const kUsageCardBodyId = "usage-card-body";
const UsageCard = ({ stats, context }) => {
  if (!stats) {
    return "";
  }
  const totalDuration = duration(stats);
  const usageMetadataStyle = {
    fontSize: FontSize.smaller
  };
  return m$1`

    <${Card}>
      <${CardHeader} icon=${ApplicationIcons.usage} label="Usage"/>
      <${CardBody} id=${kUsageCardBodyId} style=${{
    paddingTop: "0",
    paddingBottom: "0",
    borderTop: "solid var(--bs-border-color) 1px"
  }}>
        <div style=${{
    paddingTop: "0",
    paddingBottom: "1em",
    marginLeft: "0",
    display: "flex"
  }}>

          <div style=${{ flex: "1 1 40%", marginRight: "1em" }}>
          <div style=${{ marginTop: "1em", fontSize: FontSize.smaller, ...TextStyle.label, ...TextStyle.secondary }}>Duration</div>
          <${MetaDataView}
            entries="${{
    ["Start"]: new Date(stats.started_at).toLocaleString(),
    ["End"]: new Date(stats.completed_at).toLocaleString(),
    ["Duration"]: totalDuration
  }}"
            tableOptions="borderless,sm"
            context=${context}
            style=${usageMetadataStyle}
          />
          </div>

          <div style=${{ flex: "1 1 60%" }}>
            <${ModelTokenTable} model_usage=${stats.model_usage}/>
          </div>
        </div>
      </${CardBody}>
    </${Card}>
  `;
};
const ModelUsagePanel = ({ usage }) => {
  const rows = [
    {
      label: "input",
      value: usage.input_tokens,
      secondary: false
    }
  ];
  if (usage.input_tokens_cache_read) {
    rows.push({
      label: "cache_read",
      value: usage.input_tokens_cache_read,
      secondary: true
    });
  }
  if (usage.input_tokens_cache_write) {
    rows.push({
      label: "cache_write",
      value: usage.input_tokens_cache_write,
      secondary: true
    });
  }
  rows.push({
    label: "Output",
    value: usage.output_tokens,
    secondary: false,
    bordered: true
  });
  rows.push({
    label: "---",
    value: void 0,
    secondary: false
  });
  rows.push({
    label: "Total",
    value: usage.total_tokens,
    secondary: false
  });
  return m$1` <div
    style=${{
    display: "grid",
    gridTemplateColumns: "0 auto auto",
    columnGap: "0.5em",
    fontSize: FontSize.small
  }}
  >
    ${rows.map((row) => {
    if (row.label === "---") {
      return m$1`<div
          style=${{
        gridColumn: "-1/1",
        height: "1px",
        backgroundColor: "var(--bs-light-border-subtle)"
      }}
        ></div>`;
    } else {
      return m$1`
          <div
            style=${{
        ...TextStyle.label,
        ...TextStyle.secondary,
        gridColumn: row.secondary ? "2" : "1/3"
      }}
          >
            ${row.label}
          </div>
          <div style=${{ gridColumn: "3" }}>${formatNumber(row.value)}</div>
        `;
    }
  })}
  </div>`;
};
const duration = (stats) => {
  const start2 = new Date(stats.started_at);
  const end2 = new Date(stats.completed_at);
  const durationMs = end2.getTime() - start2.getTime();
  const durationSec = durationMs / 1e3;
  return formatTime(durationSec);
};
const ModelEventView = ({ id, depth, event }) => {
  var _a, _b;
  const totalUsage = (_a = event.output.usage) == null ? void 0 : _a.total_tokens;
  const subtitle = totalUsage ? `(${formatNumber(totalUsage)} tokens)` : "";
  const outputMessages = (_b = event.output.choices) == null ? void 0 : _b.map((choice) => {
    return choice.message;
  });
  const entries = { ...event.config };
  entries["tool_choice"] = event.tool_choice;
  delete entries["max_connections"];
  const tableSectionStyle = {
    width: "fit-content",
    alignSelf: "start",
    justifySelf: "start"
  };
  return m$1`
  <${EventPanel} id=${id} depth=${depth} title="Model Call: ${event.model} ${subtitle}" icon=${ApplicationIcons.model}>
  
    <div name="Completion">
    <${ChatView}
      id="${id}-model-output"
      messages=${[...outputMessages || []]}
      style=${{ paddingTop: "1em" }}
      />
    </div>

    <div name="All" style=${{ margin: "1em 0" }}>

      <div style=${{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: "1em" }}>
      <${EventSection} title="Configuration" style=${tableSectionStyle}>
        <${MetaDataGrid} entries=${entries} plain=${true}/>
      </${EventSection}>

      <${EventSection} title="Usage" style=${tableSectionStyle}>
        <${ModelUsagePanel} usage=${event.output.usage}/>
      </${EventSection}>

      <${EventSection} title="Tools" style=${{ gridColumn: "-1/1", ...tableSectionStyle }}>
        <${ToolsConfig} tools=${event.tools}/>
      </${EventSection}>

      </div>

      <${EventSection} title="Messages">
        <${ChatView}
          id="${id}-model-input-full"
          messages=${[...event.input, ...outputMessages || []]}
          />      
      </${EventSection}>

    </div>

    ${event.call ? m$1`<${APIView} name="API" call=${event.call} style=${{ margin: "1em 0", width: "100%" }} />` : ""}
   
  </${EventPanel}>`;
};
const APIView = ({ call, style }) => {
  if (!call) {
    return "";
  }
  return m$1`<div style=${style}>

    <${EventSection} title="Request">
      <${APICodeCell} contents=${call.request} />
    </${EventSection}>
    <${EventSection} title="Response">
      <${APICodeCell} contents=${call.response} />
    </${EventSection}>

    </div>`;
};
const APICodeCell = ({ id, contents }) => {
  if (!contents) {
    return "";
  }
  const sourceCode = JSON.stringify(contents, void 0, 2);
  const codeRef = A();
  if (codeRef.current) {
    codeRef.current.innerHTML = Prism$1.highlight(
      sourceCode,
      Prism$1.languages.javascript,
      "javacript"
    );
  }
  return m$1`<div>
    <pre
      style=${{
    background: "var(--bs-light)",
    width: "100%",
    padding: "0.5em",
    borderRadius: "3px"
  }}
    >
      <code 
        id=${id} 
        ref=${codeRef}
        class="sourceCode-js" 
        style=${{
    fontSize: FontSize.small,
    whiteSpace: "pre-wrap",
    wordWrap: "anywhere"
  }}>
      </code>
      </pre>
  </div>`;
};
const ToolsConfig = ({ tools }) => {
  const toolEls = tools.map((tool) => {
    return m$1`<div style=${{ ...TextStyle.label, ...TextStyle.secondary }}>
        ${tool.name}
      </div>
      <div>${tool.description}</div>`;
  });
  return m$1`<div
    style=${{
    display: "grid",
    gridTemplateColumns: "max-content max-content",
    columnGap: "1em"
  }}
  >
    ${toolEls}
  </div>`;
};
const EventRow = ({ title, icon, depth, children }) => {
  const paddingLeft = depth * 1.5 + 0.5;
  const contentEl = title ? m$1`<div
        style=${{
    padding: `0.5em 0.5em 0.5em ${paddingLeft}em`,
    display: "grid",
    gridTemplateColumns: "max-content max-content minmax(0, 1fr)",
    columnGap: "0.5em",
    fontSize: FontSize.small
  }}
      >
        <i
          class=${icon || ApplicationIcons.metadata}
          style=${{ ...TextStyle.secondary }}
        />
        <div style=${{ ...TextStyle.label, ...TextStyle.secondary }}>
          ${title}
        </div>
        <div>${children}</div>
      </div>` : "";
  const card = m$1` <div
    class="card"
    style=${{
    padding: "0.1em 0.5em",
    marginBottom: "-1px"
  }}
  >
    ${contentEl}
  </div>`;
  return card;
};
const LoggerEventView = ({ id, depth, event }) => {
  return m$1`
  <${EventRow} 
    id=${id}
    depth=${depth}
    title=${event.message.level} 
    icon=${ApplicationIcons.logging[event.message.level.toLowerCase()]}  
  >
  <div
    style=${{ width: "100%", display: "grid", gridTemplateColumns: "1fr max-content", columnGap: "1em", fontSize: FontSize.base }}
  >
    <div style=${{ fontSize: FontSize.smaller }}>${event.message.message}</div>
    <div style=${{ fontSize: FontSize.smaller, ...TextStyle.secondary }}>${event.message.filename}:${event.message.lineno}</div>
  </div>
  </${EventRow}>`;
};
const InfoEventView = ({ id, depth, event }) => {
  return m$1`
  <${EventPanel} id=${id} depth=${depth} title="Info" icon=${ApplicationIcons.info}>
  <div
    style=${{ display: "grid", gridTemplateColumns: "auto auto" }}
  >
    <div><i class=${ApplicationIcons.logging.info} /></div>
    <div>${event.message}</div>
    <div></div>
  </div>
  </${EventPanel}>`;
};
const ScoreEventView = ({ id, depth, event }) => {
  return m$1`
  <${EventPanel} id=${id} depth=${depth} title="Score" icon=${ApplicationIcons.scorer}>
  
    <div
      name="Explanation"
      style=${{ display: "grid", gridTemplateColumns: "max-content auto", columnGap: "1em", margin: "1em 0" }}
    >
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Answer</div>
      <div>${event.score.answer}</div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Explanation</div>
      <div><${MarkdownDiv} markdown=${event.score.explanation}/></div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Score</div>  
      <div>${event.score.value}</div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
    </div>
    ${event.score.metadata ? m$1`<div name="Metadata">
            <${MetaDataGrid}
              entries=${event.score.metadata}
              compact=${true}
              style=${{ margin: "1em 0" }}
            />
          </div>` : void 0}


  </${EventPanel}>`;
};
const ToolEventView = ({ id, depth, stateManager, event }) => {
  const { input, functionCall, inputType } = resolveToolInput(
    event.function,
    event.arguments
  );
  const title = `Tool: ${event.function}`;
  return m$1`
  <${EventPanel} id=${id} depth=${depth} title="${title}" icon=${ApplicationIcons.solvers.use_tools}>
  <div name="Summary">
    <${ExpandablePanel}>
      ${event.result ? m$1`<${ToolOutput} output=${event.result} style=${{ margin: "1em 0" }} />` : m$1`<div style=${{ margin: "1em 0", fontSize: FontSize.small }}>No output</div>`}
    </${ExpandablePanel}>
  </div>
  <div name="Transcript">
    <${ToolCallView}
      functionCall=${functionCall}
      input=${input}
      inputType=${inputType}
      output=${event.result}
      mode="compact"
      />
        ${event.events.length > 0 ? m$1`<${TranscriptView}
                id="${id}-subtask"
                name="Transcript"
                events=${event.events}
                stateManager=${stateManager}
              />` : ""}

  </div>
  </${EventPanel}>`;
};
const TranscriptView = ({ id, events, stateManager }) => {
  const resolvedEvents = fixupEventStream(events);
  let depth = 0;
  const rows = resolvedEvents.map((event, index) => {
    const row = m$1`
      <div
        style=${{
      paddingTop: 0,
      paddingBottom: 0
    }}
      >
        <div>
          ${renderNode(
      `${id}-event${index}`,
      event,
      Math.max(depth - 1, 0),
      stateManager
    )}
        </div>
      </div>
    `;
    if (event.event === "step") {
      if (event.action === "end") {
        depth = depth - 1;
      } else {
        depth = depth + 1;
      }
    }
    return row;
  });
  return m$1`<div
    id=${id}
    style=${{
    fontSize: FontSize.small,
    display: "grid",
    margin: "1em 0",
    width: "100%"
  }}
  >
    ${rows}
  </div>`;
};
const renderNode = (id, event, depth, stateManager) => {
  switch (event.event) {
    case "sample_init":
      return m$1`<${SampleInitEventView}
        id=${id}
        depth=${depth}
        event=${event}
        stateManager=${stateManager}
      />`;
    case "info":
      return m$1`<${InfoEventView} id=${id} depth=${depth} event=${event} />`;
    case "logger":
      return m$1`<${LoggerEventView}
        id=${id}
        depth=${depth}
        event=${event}
      />`;
    case "model":
      return m$1`<${ModelEventView} id=${id} depth=${depth} event=${event} />`;
    case "score":
      return m$1`<${ScoreEventView} id=${id} depth=${depth} event=${event} />`;
    case "state":
      return m$1`<${StateEventView}
        id=${id}
        depth=${depth}
        event=${event}
        stateManager=${stateManager}
      />`;
    case "step":
      return m$1`<${StepEventView}
        id=${id}
        depth=${depth}
        event=${event}
        stateManager=${stateManager}
      />`;
    case "store":
      return m$1`<${StateEventView}
        id=${id}
        depth=${depth}
        event=${event}
        stateManager=${stateManager}
      />`;
    case "subtask":
      return m$1`<${SubtaskEventView}
        id=${id}
        depth=${depth}
        event=${event}
        stateManager=${stateManager}
      />`;
    case "tool":
      return m$1`<${ToolEventView}
        depth=${depth}
        id=${id}
        event=${event}
        stateManager=${stateManager}
      />`;
    default:
      return m$1``;
  }
};
const fixupEventStream = (events) => {
  const initEventIndex = events.findIndex((e2) => {
    return e2.event === "sample_init";
  });
  const initEvent = events[initEventIndex];
  const fixedUp = [...events];
  if (initEvent) {
    fixedUp.splice(initEventIndex, 0, {
      timestamp: initEvent.timestamp,
      event: "step",
      action: "begin",
      type: null,
      name: "sample_init"
    });
    fixedUp.splice(initEventIndex + 2, 0, {
      timestamp: initEvent.timestamp,
      event: "step",
      action: "end",
      type: null,
      name: "sample_init"
    });
  }
  return fixedUp;
};
/*!
 * https://github.com/Starcounter-Jack/JSON-Patch
 * (c) 2017-2022 Joachim Wester
 * MIT licensed
 */
var __extends = /* @__PURE__ */ function() {
  var extendStatics = function(d2, b2) {
    extendStatics = Object.setPrototypeOf || { __proto__: [] } instanceof Array && function(d3, b3) {
      d3.__proto__ = b3;
    } || function(d3, b3) {
      for (var p2 in b3) if (b3.hasOwnProperty(p2)) d3[p2] = b3[p2];
    };
    return extendStatics(d2, b2);
  };
  return function(d2, b2) {
    extendStatics(d2, b2);
    function __() {
      this.constructor = d2;
    }
    d2.prototype = b2 === null ? Object.create(b2) : (__.prototype = b2.prototype, new __());
  };
}();
var _hasOwnProperty = Object.prototype.hasOwnProperty;
function hasOwnProperty(obj, key2) {
  return _hasOwnProperty.call(obj, key2);
}
function _objectKeys(obj) {
  if (Array.isArray(obj)) {
    var keys_1 = new Array(obj.length);
    for (var k2 = 0; k2 < keys_1.length; k2++) {
      keys_1[k2] = "" + k2;
    }
    return keys_1;
  }
  if (Object.keys) {
    return Object.keys(obj);
  }
  var keys = [];
  for (var i2 in obj) {
    if (hasOwnProperty(obj, i2)) {
      keys.push(i2);
    }
  }
  return keys;
}
function _deepClone(obj) {
  switch (typeof obj) {
    case "object":
      return JSON.parse(JSON.stringify(obj));
    case "undefined":
      return null;
    default:
      return obj;
  }
}
function isInteger(str) {
  var i2 = 0;
  var len = str.length;
  var charCode;
  while (i2 < len) {
    charCode = str.charCodeAt(i2);
    if (charCode >= 48 && charCode <= 57) {
      i2++;
      continue;
    }
    return false;
  }
  return true;
}
function escapePathComponent(path) {
  if (path.indexOf("/") === -1 && path.indexOf("~") === -1)
    return path;
  return path.replace(/~/g, "~0").replace(/\//g, "~1");
}
function unescapePathComponent(path) {
  return path.replace(/~1/g, "/").replace(/~0/g, "~");
}
function hasUndefined(obj) {
  if (obj === void 0) {
    return true;
  }
  if (obj) {
    if (Array.isArray(obj)) {
      for (var i_1 = 0, len = obj.length; i_1 < len; i_1++) {
        if (hasUndefined(obj[i_1])) {
          return true;
        }
      }
    } else if (typeof obj === "object") {
      var objKeys = _objectKeys(obj);
      var objKeysLength = objKeys.length;
      for (var i2 = 0; i2 < objKeysLength; i2++) {
        if (hasUndefined(obj[objKeys[i2]])) {
          return true;
        }
      }
    }
  }
  return false;
}
function patchErrorMessageFormatter(message, args) {
  var messageParts = [message];
  for (var key2 in args) {
    var value = typeof args[key2] === "object" ? JSON.stringify(args[key2], null, 2) : args[key2];
    if (typeof value !== "undefined") {
      messageParts.push(key2 + ": " + value);
    }
  }
  return messageParts.join("\n");
}
var PatchError = (
  /** @class */
  function(_super) {
    __extends(PatchError2, _super);
    function PatchError2(message, name, index, operation, tree) {
      var _newTarget = this.constructor;
      var _this = _super.call(this, patchErrorMessageFormatter(message, { name, index, operation, tree })) || this;
      _this.name = name;
      _this.index = index;
      _this.operation = operation;
      _this.tree = tree;
      Object.setPrototypeOf(_this, _newTarget.prototype);
      _this.message = patchErrorMessageFormatter(message, { name, index, operation, tree });
      return _this;
    }
    return PatchError2;
  }(Error)
);
var JsonPatchError = PatchError;
var deepClone = _deepClone;
var objOps = {
  add: function(obj, key2, document2) {
    obj[key2] = this.value;
    return { newDocument: document2 };
  },
  remove: function(obj, key2, document2) {
    var removed = obj[key2];
    delete obj[key2];
    return { newDocument: document2, removed };
  },
  replace: function(obj, key2, document2) {
    var removed = obj[key2];
    obj[key2] = this.value;
    return { newDocument: document2, removed };
  },
  move: function(obj, key2, document2) {
    var removed = getValueByPointer(document2, this.path);
    if (removed) {
      removed = _deepClone(removed);
    }
    var originalValue = applyOperation(document2, { op: "remove", path: this.from }).removed;
    applyOperation(document2, { op: "add", path: this.path, value: originalValue });
    return { newDocument: document2, removed };
  },
  copy: function(obj, key2, document2) {
    var valueToCopy = getValueByPointer(document2, this.from);
    applyOperation(document2, { op: "add", path: this.path, value: _deepClone(valueToCopy) });
    return { newDocument: document2 };
  },
  test: function(obj, key2, document2) {
    return { newDocument: document2, test: _areEquals(obj[key2], this.value) };
  },
  _get: function(obj, key2, document2) {
    this.value = obj[key2];
    return { newDocument: document2 };
  }
};
var arrOps = {
  add: function(arr, i2, document2) {
    if (isInteger(i2)) {
      arr.splice(i2, 0, this.value);
    } else {
      arr[i2] = this.value;
    }
    return { newDocument: document2, index: i2 };
  },
  remove: function(arr, i2, document2) {
    var removedList = arr.splice(i2, 1);
    return { newDocument: document2, removed: removedList[0] };
  },
  replace: function(arr, i2, document2) {
    var removed = arr[i2];
    arr[i2] = this.value;
    return { newDocument: document2, removed };
  },
  move: objOps.move,
  copy: objOps.copy,
  test: objOps.test,
  _get: objOps._get
};
function getValueByPointer(document2, pointer) {
  if (pointer == "") {
    return document2;
  }
  var getOriginalDestination = { op: "_get", path: pointer };
  applyOperation(document2, getOriginalDestination);
  return getOriginalDestination.value;
}
function applyOperation(document2, operation, validateOperation, mutateDocument, banPrototypeModifications, index) {
  if (validateOperation === void 0) {
    validateOperation = false;
  }
  if (mutateDocument === void 0) {
    mutateDocument = true;
  }
  if (banPrototypeModifications === void 0) {
    banPrototypeModifications = true;
  }
  if (index === void 0) {
    index = 0;
  }
  if (validateOperation) {
    if (typeof validateOperation == "function") {
      validateOperation(operation, 0, document2, operation.path);
    } else {
      validator(operation, 0);
    }
  }
  if (operation.path === "") {
    var returnValue = { newDocument: document2 };
    if (operation.op === "add") {
      returnValue.newDocument = operation.value;
      return returnValue;
    } else if (operation.op === "replace") {
      returnValue.newDocument = operation.value;
      returnValue.removed = document2;
      return returnValue;
    } else if (operation.op === "move" || operation.op === "copy") {
      returnValue.newDocument = getValueByPointer(document2, operation.from);
      if (operation.op === "move") {
        returnValue.removed = document2;
      }
      return returnValue;
    } else if (operation.op === "test") {
      returnValue.test = _areEquals(document2, operation.value);
      if (returnValue.test === false) {
        throw new JsonPatchError("Test operation failed", "TEST_OPERATION_FAILED", index, operation, document2);
      }
      returnValue.newDocument = document2;
      return returnValue;
    } else if (operation.op === "remove") {
      returnValue.removed = document2;
      returnValue.newDocument = null;
      return returnValue;
    } else if (operation.op === "_get") {
      operation.value = document2;
      return returnValue;
    } else {
      if (validateOperation) {
        throw new JsonPatchError("Operation `op` property is not one of operations defined in RFC-6902", "OPERATION_OP_INVALID", index, operation, document2);
      } else {
        return returnValue;
      }
    }
  } else {
    if (!mutateDocument) {
      document2 = _deepClone(document2);
    }
    var path = operation.path || "";
    var keys = path.split("/");
    var obj = document2;
    var t2 = 1;
    var len = keys.length;
    var existingPathFragment = void 0;
    var key2 = void 0;
    var validateFunction = void 0;
    if (typeof validateOperation == "function") {
      validateFunction = validateOperation;
    } else {
      validateFunction = validator;
    }
    while (true) {
      key2 = keys[t2];
      if (key2 && key2.indexOf("~") != -1) {
        key2 = unescapePathComponent(key2);
      }
      if (banPrototypeModifications && (key2 == "__proto__" || key2 == "prototype" && t2 > 0 && keys[t2 - 1] == "constructor")) {
        throw new TypeError("JSON-Patch: modifying `__proto__` or `constructor/prototype` prop is banned for security reasons, if this was on purpose, please set `banPrototypeModifications` flag false and pass it to this function. More info in fast-json-patch README");
      }
      if (validateOperation) {
        if (existingPathFragment === void 0) {
          if (obj[key2] === void 0) {
            existingPathFragment = keys.slice(0, t2).join("/");
          } else if (t2 == len - 1) {
            existingPathFragment = operation.path;
          }
          if (existingPathFragment !== void 0) {
            validateFunction(operation, 0, document2, existingPathFragment);
          }
        }
      }
      t2++;
      if (Array.isArray(obj)) {
        if (key2 === "-") {
          key2 = obj.length;
        } else {
          if (validateOperation && !isInteger(key2)) {
            throw new JsonPatchError("Expected an unsigned base-10 integer value, making the new referenced value the array element with the zero-based index", "OPERATION_PATH_ILLEGAL_ARRAY_INDEX", index, operation, document2);
          } else if (isInteger(key2)) {
            key2 = ~~key2;
          }
        }
        if (t2 >= len) {
          if (validateOperation && operation.op === "add" && key2 > obj.length) {
            throw new JsonPatchError("The specified index MUST NOT be greater than the number of elements in the array", "OPERATION_VALUE_OUT_OF_BOUNDS", index, operation, document2);
          }
          var returnValue = arrOps[operation.op].call(operation, obj, key2, document2);
          if (returnValue.test === false) {
            throw new JsonPatchError("Test operation failed", "TEST_OPERATION_FAILED", index, operation, document2);
          }
          return returnValue;
        }
      } else {
        if (t2 >= len) {
          var returnValue = objOps[operation.op].call(operation, obj, key2, document2);
          if (returnValue.test === false) {
            throw new JsonPatchError("Test operation failed", "TEST_OPERATION_FAILED", index, operation, document2);
          }
          return returnValue;
        }
      }
      obj = obj[key2];
      if (validateOperation && t2 < len && (!obj || typeof obj !== "object")) {
        throw new JsonPatchError("Cannot perform operation at the desired path", "OPERATION_PATH_UNRESOLVABLE", index, operation, document2);
      }
    }
  }
}
function applyPatch(document2, patch, validateOperation, mutateDocument, banPrototypeModifications) {
  if (mutateDocument === void 0) {
    mutateDocument = true;
  }
  if (banPrototypeModifications === void 0) {
    banPrototypeModifications = true;
  }
  if (validateOperation) {
    if (!Array.isArray(patch)) {
      throw new JsonPatchError("Patch sequence must be an array", "SEQUENCE_NOT_AN_ARRAY");
    }
  }
  if (!mutateDocument) {
    document2 = _deepClone(document2);
  }
  var results = new Array(patch.length);
  for (var i2 = 0, length_1 = patch.length; i2 < length_1; i2++) {
    results[i2] = applyOperation(document2, patch[i2], validateOperation, true, banPrototypeModifications, i2);
    document2 = results[i2].newDocument;
  }
  results.newDocument = document2;
  return results;
}
function applyReducer(document2, operation, index) {
  var operationResult = applyOperation(document2, operation);
  if (operationResult.test === false) {
    throw new JsonPatchError("Test operation failed", "TEST_OPERATION_FAILED", index, operation, document2);
  }
  return operationResult.newDocument;
}
function validator(operation, index, document2, existingPathFragment) {
  if (typeof operation !== "object" || operation === null || Array.isArray(operation)) {
    throw new JsonPatchError("Operation is not an object", "OPERATION_NOT_AN_OBJECT", index, operation, document2);
  } else if (!objOps[operation.op]) {
    throw new JsonPatchError("Operation `op` property is not one of operations defined in RFC-6902", "OPERATION_OP_INVALID", index, operation, document2);
  } else if (typeof operation.path !== "string") {
    throw new JsonPatchError("Operation `path` property is not a string", "OPERATION_PATH_INVALID", index, operation, document2);
  } else if (operation.path.indexOf("/") !== 0 && operation.path.length > 0) {
    throw new JsonPatchError('Operation `path` property must start with "/"', "OPERATION_PATH_INVALID", index, operation, document2);
  } else if ((operation.op === "move" || operation.op === "copy") && typeof operation.from !== "string") {
    throw new JsonPatchError("Operation `from` property is not present (applicable in `move` and `copy` operations)", "OPERATION_FROM_REQUIRED", index, operation, document2);
  } else if ((operation.op === "add" || operation.op === "replace" || operation.op === "test") && operation.value === void 0) {
    throw new JsonPatchError("Operation `value` property is not present (applicable in `add`, `replace` and `test` operations)", "OPERATION_VALUE_REQUIRED", index, operation, document2);
  } else if ((operation.op === "add" || operation.op === "replace" || operation.op === "test") && hasUndefined(operation.value)) {
    throw new JsonPatchError("Operation `value` property is not present (applicable in `add`, `replace` and `test` operations)", "OPERATION_VALUE_CANNOT_CONTAIN_UNDEFINED", index, operation, document2);
  } else if (document2) {
    if (operation.op == "add") {
      var pathLen = operation.path.split("/").length;
      var existingPathLen = existingPathFragment.split("/").length;
      if (pathLen !== existingPathLen + 1 && pathLen !== existingPathLen) {
        throw new JsonPatchError("Cannot perform an `add` operation at the desired path", "OPERATION_PATH_CANNOT_ADD", index, operation, document2);
      }
    } else if (operation.op === "replace" || operation.op === "remove" || operation.op === "_get") {
      if (operation.path !== existingPathFragment) {
        throw new JsonPatchError("Cannot perform the operation at a path that does not exist", "OPERATION_PATH_UNRESOLVABLE", index, operation, document2);
      }
    } else if (operation.op === "move" || operation.op === "copy") {
      var existingValue = { op: "_get", path: operation.from, value: void 0 };
      var error = validate([existingValue], document2);
      if (error && error.name === "OPERATION_PATH_UNRESOLVABLE") {
        throw new JsonPatchError("Cannot perform the operation from a path that does not exist", "OPERATION_FROM_UNRESOLVABLE", index, operation, document2);
      }
    }
  }
}
function validate(sequence, document2, externalValidator) {
  try {
    if (!Array.isArray(sequence)) {
      throw new JsonPatchError("Patch sequence must be an array", "SEQUENCE_NOT_AN_ARRAY");
    }
    if (document2) {
      applyPatch(_deepClone(document2), _deepClone(sequence), externalValidator || true);
    } else {
      externalValidator = externalValidator || validator;
      for (var i2 = 0; i2 < sequence.length; i2++) {
        externalValidator(sequence[i2], i2, document2, void 0);
      }
    }
  } catch (e2) {
    if (e2 instanceof JsonPatchError) {
      return e2;
    } else {
      throw e2;
    }
  }
}
function _areEquals(a2, b2) {
  if (a2 === b2)
    return true;
  if (a2 && b2 && typeof a2 == "object" && typeof b2 == "object") {
    var arrA = Array.isArray(a2), arrB = Array.isArray(b2), i2, length, key2;
    if (arrA && arrB) {
      length = a2.length;
      if (length != b2.length)
        return false;
      for (i2 = length; i2-- !== 0; )
        if (!_areEquals(a2[i2], b2[i2]))
          return false;
      return true;
    }
    if (arrA != arrB)
      return false;
    var keys = Object.keys(a2);
    length = keys.length;
    if (length !== Object.keys(b2).length)
      return false;
    for (i2 = length; i2-- !== 0; )
      if (!b2.hasOwnProperty(keys[i2]))
        return false;
    for (i2 = length; i2-- !== 0; ) {
      key2 = keys[i2];
      if (!_areEquals(a2[key2], b2[key2]))
        return false;
    }
    return true;
  }
  return a2 !== a2 && b2 !== b2;
}
const core = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ Object.defineProperty({
  __proto__: null,
  JsonPatchError,
  _areEquals,
  applyOperation,
  applyPatch,
  applyReducer,
  deepClone,
  getValueByPointer,
  validate,
  validator
}, Symbol.toStringTag, { value: "Module" }));
/*!
 * https://github.com/Starcounter-Jack/JSON-Patch
 * (c) 2017-2021 Joachim Wester
 * MIT license
 */
var beforeDict = /* @__PURE__ */ new WeakMap();
var Mirror = (
  /** @class */
  /* @__PURE__ */ function() {
    function Mirror2(obj) {
      this.observers = /* @__PURE__ */ new Map();
      this.obj = obj;
    }
    return Mirror2;
  }()
);
var ObserverInfo = (
  /** @class */
  /* @__PURE__ */ function() {
    function ObserverInfo2(callback, observer) {
      this.callback = callback;
      this.observer = observer;
    }
    return ObserverInfo2;
  }()
);
function getMirror(obj) {
  return beforeDict.get(obj);
}
function getObserverFromMirror(mirror, callback) {
  return mirror.observers.get(callback);
}
function removeObserverFromMirror(mirror, observer) {
  mirror.observers.delete(observer.callback);
}
function unobserve(root2, observer) {
  observer.unobserve();
}
function observe(obj, callback) {
  var patches = [];
  var observer;
  var mirror = getMirror(obj);
  if (!mirror) {
    mirror = new Mirror(obj);
    beforeDict.set(obj, mirror);
  } else {
    var observerInfo = getObserverFromMirror(mirror, callback);
    observer = observerInfo && observerInfo.observer;
  }
  if (observer) {
    return observer;
  }
  observer = {};
  mirror.value = _deepClone(obj);
  if (callback) {
    observer.callback = callback;
    observer.next = null;
    var dirtyCheck = function() {
      generate(observer);
    };
    var fastCheck = function() {
      clearTimeout(observer.next);
      observer.next = setTimeout(dirtyCheck);
    };
    if (typeof window !== "undefined") {
      window.addEventListener("mouseup", fastCheck);
      window.addEventListener("keyup", fastCheck);
      window.addEventListener("mousedown", fastCheck);
      window.addEventListener("keydown", fastCheck);
      window.addEventListener("change", fastCheck);
    }
  }
  observer.patches = patches;
  observer.object = obj;
  observer.unobserve = function() {
    generate(observer);
    clearTimeout(observer.next);
    removeObserverFromMirror(mirror, observer);
    if (typeof window !== "undefined") {
      window.removeEventListener("mouseup", fastCheck);
      window.removeEventListener("keyup", fastCheck);
      window.removeEventListener("mousedown", fastCheck);
      window.removeEventListener("keydown", fastCheck);
      window.removeEventListener("change", fastCheck);
    }
  };
  mirror.observers.set(callback, new ObserverInfo(callback, observer));
  return observer;
}
function generate(observer, invertible) {
  if (invertible === void 0) {
    invertible = false;
  }
  var mirror = beforeDict.get(observer.object);
  _generate(mirror.value, observer.object, observer.patches, "", invertible);
  if (observer.patches.length) {
    applyPatch(mirror.value, observer.patches);
  }
  var temp = observer.patches;
  if (temp.length > 0) {
    observer.patches = [];
    if (observer.callback) {
      observer.callback(temp);
    }
  }
  return temp;
}
function _generate(mirror, obj, patches, path, invertible) {
  if (obj === mirror) {
    return;
  }
  if (typeof obj.toJSON === "function") {
    obj = obj.toJSON();
  }
  var newKeys = _objectKeys(obj);
  var oldKeys = _objectKeys(mirror);
  var deleted = false;
  for (var t2 = oldKeys.length - 1; t2 >= 0; t2--) {
    var key2 = oldKeys[t2];
    var oldVal = mirror[key2];
    if (hasOwnProperty(obj, key2) && !(obj[key2] === void 0 && oldVal !== void 0 && Array.isArray(obj) === false)) {
      var newVal = obj[key2];
      if (typeof oldVal == "object" && oldVal != null && typeof newVal == "object" && newVal != null && Array.isArray(oldVal) === Array.isArray(newVal)) {
        _generate(oldVal, newVal, patches, path + "/" + escapePathComponent(key2), invertible);
      } else {
        if (oldVal !== newVal) {
          if (invertible) {
            patches.push({ op: "test", path: path + "/" + escapePathComponent(key2), value: _deepClone(oldVal) });
          }
          patches.push({ op: "replace", path: path + "/" + escapePathComponent(key2), value: _deepClone(newVal) });
        }
      }
    } else if (Array.isArray(mirror) === Array.isArray(obj)) {
      if (invertible) {
        patches.push({ op: "test", path: path + "/" + escapePathComponent(key2), value: _deepClone(oldVal) });
      }
      patches.push({ op: "remove", path: path + "/" + escapePathComponent(key2) });
      deleted = true;
    } else {
      if (invertible) {
        patches.push({ op: "test", path, value: mirror });
      }
      patches.push({ op: "replace", path, value: obj });
    }
  }
  if (!deleted && newKeys.length == oldKeys.length) {
    return;
  }
  for (var t2 = 0; t2 < newKeys.length; t2++) {
    var key2 = newKeys[t2];
    if (!hasOwnProperty(mirror, key2) && obj[key2] !== void 0) {
      patches.push({ op: "add", path: path + "/" + escapePathComponent(key2), value: _deepClone(obj[key2]) });
    }
  }
}
function compare(tree1, tree2, invertible) {
  if (invertible === void 0) {
    invertible = false;
  }
  var patches = [];
  _generate(tree1, tree2, patches, "", invertible);
  return patches;
}
const duplex = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ Object.defineProperty({
  __proto__: null,
  compare,
  generate,
  observe,
  unobserve
}, Symbol.toStringTag, { value: "Module" }));
Object.assign({}, core, duplex, {
  JsonPatchError: PatchError,
  deepClone: _deepClone,
  escapePathComponent,
  unescapePathComponent
});
const initStateManager = () => {
  let state = {};
  return {
    /**
     * Retrieves the current state object.
     *
     * @returns {Object} The current state object.
     */
    getState: () => {
      return state;
    },
    /**
     * Updates the current state with a new state object.
     *
     * @param {Object} newState - The new state object to update with.
     */
    setState: (newState) => {
      state = structuredClone(newState);
    },
    /**
     * Updates the current state with a new state object.
     *
     * @param {import("../../types/log").Changes} changes - The new state object to update with.
     */
    applyChanges: (changes) => {
      state = structuredClone(state);
      changes.forEach((change) => {
        applyOperation(state, change);
      });
      return state;
    }
  };
};
const kContentProtocol = "tc://";
const SampleTranscript = ({ id, evalEvents }) => {
  const stateManager = initStateManager();
  const denormalizedEvents = resolveEventContent(evalEvents);
  return m$1`<${TranscriptView}
    id=${id}
    events=${denormalizedEvents}
    stateManager=${stateManager}
  />`;
};
const resolveEventContent = (evalEvents) => {
  return (
    /** @type {import("../types/log").Events} */
    evalEvents.events.map((e2) => {
      return resolveValue(e2, evalEvents);
    })
  );
};
const resolveValue = (value, evalEvents) => {
  if (Array.isArray(value)) {
    return value.map((v2) => resolveValue(v2, evalEvents));
  } else if (value && typeof value === "object") {
    const resolvedObject = {};
    for (const key2 of Object.keys(value)) {
      resolvedObject[key2] = resolveValue(value[key2], evalEvents);
    }
    return resolvedObject;
  } else if (typeof value === "string") {
    if (value.startsWith(kContentProtocol)) {
      return evalEvents.content[value.replace(kContentProtocol, "")];
    }
  }
  return value;
};
const InlineSampleDisplay = ({
  index,
  id,
  sample,
  sampleDescriptor,
  context
}) => {
  return m$1`<div
    style=${{ flexDirection: "row", width: "100%", margin: "1em" }}
  >
    <${SampleDisplay}
      index=${index}
      id=${id}
      sample=${sample}
      sampleDescriptor=${sampleDescriptor}
      context=${context}
    />
  </div>`;
};
const SampleDisplay = ({
  index,
  id,
  sample,
  sampleDescriptor,
  context
}) => {
  const baseId = `sample-${index}`;
  const msgTabId = `${baseId}-messages`;
  const transcriptTabId = `${baseId}-transcript`;
  const scoringTabId = `${baseId}-scoring`;
  const metdataTabId = `${baseId}-metadata`;
  y(() => {
    if (sample.transcript && sample.transcript.events.length > 0) {
      setSelectedTab(transcriptTabId);
    } else {
      setSelectedTab(msgTabId);
    }
  }, [sample]);
  const [selectedTab, setSelectedTab] = h(void 0);
  const onSelectedTab = (e2) => {
    const id2 = e2.currentTarget.id;
    setSelectedTab(id2);
    return false;
  };
  const tabs = [
    m$1`
    <${TabPanel} id=${msgTabId} title="Messages" icon=${ApplicationIcons.messages} onSelected=${onSelectedTab} selected=${selectedTab === msgTabId}>
      <${ChatView} key=${`${baseId}-chat`} id=${`${baseId}-chat`} messages=${sample.messages} style=${{ paddingLeft: ".8em", paddingTop: "1em" }}/>
    </${TabPanel}>`
  ];
  if (sample.transcript && sample.transcript.events.length > 0) {
    tabs.unshift(m$1`
      <${TabPanel} id=${transcriptTabId} title="Transcript" icon=${ApplicationIcons.transcript} onSelected=${onSelectedTab} selected=${selectedTab === transcriptTabId || selectedTab === void 0} scrollable=${false}>
        <${SampleTranscript} id=${`${baseId}-transcript`} evalEvents=${sample.transcript}/>
      </${TabPanel}>`);
  }
  const scorerNames = Object.keys(sample.scores);
  if (scorerNames.length === 1) {
    tabs.push(m$1`
      <${TabPanel} id=${scoringTabId} title="Scoring" icon=${ApplicationIcons.scorer} onSelected=${onSelectedTab} selected=${selectedTab === scoringTabId}>
        <${SampleScoreView}
          sample=${sample}
          context=${context}
          sampleDescriptor=${sampleDescriptor}
          scorer=${Object.keys(sample.scores)[0]}
          style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}
        />
      </${TabPanel}>`);
  } else {
    for (const scorer of Object.keys(sample.scores)) {
      const tabId = `score-${scorer}`;
      tabs.push(m$1`
        <${TabPanel} id="${tabId}" title="${scorer}" icon=${ApplicationIcons.scorer} onSelected=${onSelectedTab} selected=${selectedTab === tabId}>
          <${SampleScoreView}
            sample=${sample}
            context=${context}
            sampleDescriptor=${sampleDescriptor}
            scorer=${scorer}
            style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}
          />
        </${TabPanel}>`);
    }
  }
  const sampleMetadatas = metadataViewsForSample(baseId, sample, context);
  if (sampleMetadatas.length > 0) {
    tabs.push(
      m$1`
      <${TabPanel} 
          id=${metdataTabId} 
          title="Metadata" 
          icon=${ApplicationIcons.metadata}
          onSelected=${onSelectedTab} 
          selected=${selectedTab === metdataTabId}>
         <div style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}> 
        ${sampleMetadatas}
        </div>
      </${TabPanel}>`
    );
  }
  return m$1`<${SampleSummary}
    id=${sample.id}
    sample=${sample}
    sampleDescriptor=${sampleDescriptor}/>

  <${TabSet} id="task-sample-details-tab-${id}" styles=${{
    tabs: {
      fontSize: FontSize.base
    },
    tabBody: {}
  }}>
    ${tabs}
  </${TabSet}>`;
};
const metadataViewsForSample = (id, sample, context) => {
  var _a, _b, _c;
  const sampleMetadatas = [];
  if (Object.keys(sample == null ? void 0 : sample.metadata).length > 0) {
    sampleMetadatas.push(
      m$1` <${MetaDataView}
        id="task-sample-metadata-${id}"
        classes="tab-pane"
        entries="${sample == null ? void 0 : sample.metadata}"
        style=${{ marginTop: "1em" }}
        context=${context}
      />`
    );
  }
  if (((_a = sample == null ? void 0 : sample.score) == null ? void 0 : _a.metadata) && Object.keys((_b = sample == null ? void 0 : sample.score) == null ? void 0 : _b.metadata).length > 0) {
    sampleMetadatas.push(
      m$1`<${MetaDataView}
        id="task-sample-metadata-${id}"
        classes="tab-pane"
        entries="${(_c = sample == null ? void 0 : sample.score) == null ? void 0 : _c.metadata}"
        style=${{ marginTop: "1em" }}
        context=${context}
      />`
    );
  }
  return sampleMetadatas;
};
const SampleSummary = ({ id, sample, style, sampleDescriptor }) => {
  const input = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.input) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.input) : 0;
  const target = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.target) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.target) : 0;
  const answer = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.answer) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.answer) : 0;
  const scoreInput = [inputString(sample.input)];
  if (sample.choices && sample.choices.length > 0) {
    scoreInput.push("");
    scoreInput.push(
      ...sample.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      })
    );
  }
  const columns = [];
  columns.push({
    label: "Id",
    value: id,
    size: "minmax(min-content, max-content)"
  });
  columns.push({
    label: "Input",
    value: scoreInput,
    size: `${input}fr`,
    clamp: true
  });
  if (sample.target) {
    columns.push({
      label: "Target",
      value: m$1`<${MarkdownDiv}
        markdown=${arrayToString(arrayToString((sample == null ? void 0 : sample.target) || "none"))}
        style=${{ paddingLeft: "0" }}
        class="no-last-para-padding"
      />`,
      size: `${target}fr`,
      clamp: true
    });
  }
  const fullAnswer = sample && sampleDescriptor ? sampleDescriptor.selectedScorer(sample).answer() : void 0;
  if (fullAnswer) {
    columns.push({
      label: "Answer",
      value: sample ? m$1`<${MarkdownDiv}
            markdown=${arrayToString(shortenCompletion(fullAnswer))}
            style=${{ paddingLeft: "0" }}
            class="no-last-para-padding"
          />` : "",
      size: `${answer}fr`,
      clamp: true
    });
  }
  columns.push({
    label: "Score",
    value: sampleDescriptor == null ? void 0 : sampleDescriptor.selectedScore(sample).render(),
    size: "minmax(2em, auto)",
    center: true
  });
  return m$1`
    <div
      id=${`sample-${id}`}
      style=${{
    display: "grid",
    gridTemplateColumns: `${columns.map((col) => {
      return col.size;
    }).join(" ")}`,
    gridColumnGap: "0.5em",
    fontSize: FontSize.base,
    borderBottom: "solid var(--bs-border-color) 1px",
    marginBottom: "1em",
    padding: "0em 1em 1em 1em",
    ...style
  }}
    >
      ${columns.map((col) => {
    const style2 = {
      ...TextStyle.label,
      ...TextStyle.secondary,
      fontSize: FontSize.base
    };
    if (col.center) {
      style2["display"] = "flex";
      style2["justifyContent"] = "center";
    }
    return m$1`<div style=${{ ...style2 }}>${col.label}</div>`;
  })}
      ${columns.map((col) => {
    const style2 = {
      ...col.clamp ? ApplicationStyles.threeLineClamp : {}
    };
    if (col.center) {
      style2.display = "flex";
      style2.justifyContent = "center";
    }
    style2.wordWrap = "anywhere";
    return m$1`<div style=${{ ...style2 }}>${col.value}</div>`;
  })}
    </div>
  `;
};
const SampleDialog = (props) => {
  const {
    id,
    index,
    title,
    sample,
    sampleDescriptor,
    nextSample,
    prevSample,
    context
  } = props;
  if (!sample) {
    return m$1`<${LargeModal} id=${id} title="No Sample"><${EmptyPanel}>No Sample Selected</${EmptyPanel}></${LargeModal}>`;
  }
  const tools = T(() => {
    const nextTool = {
      label: "Next Sample",
      icon: ApplicationIcons.next,
      onclick: nextSample,
      enabled: !!nextSample
    };
    const prevTool = {
      label: "Previous Sample",
      icon: ApplicationIcons.previous,
      onclick: prevSample,
      enabled: !!prevSample
    };
    return {
      left: [prevTool],
      right: [nextTool]
    };
  }, [prevSample, nextSample]);
  const handleKeyUp = q(
    (e2) => {
      switch (e2.key) {
        case "ArrowRight":
          if (nextSample) {
            nextSample();
          }
          break;
        case "ArrowLeft":
          if (prevSample) {
            prevSample();
          }
          break;
      }
    },
    [prevSample, nextSample]
  );
  return m$1`
    <${LargeModal} 
      id=${id} 
      detail=${title}
      detailTools=${tools}
      onkeyup=${handleKeyUp}   
    >
    <${SampleDisplay}
      index=${index}
      id=${id}
      sample=${sample}
      sampleDescriptor=${sampleDescriptor}
      context=${context}/>
    </${LargeModal}>`;
};
const STYLE_INNER = "position:relative; overflow:hidden; width:100%; min-height:100%;";
const STYLE_CONTENT = "position:absolute; top:0; left:0; height:100%; width:100%; overflow:visible;";
class VirtualList extends b {
  constructor(props) {
    super(props);
    this.state = {
      height: 0,
      offset: 0
    };
    this.resize = this.resize.bind(this);
    this.handleScroll = throttle(this.handleScroll.bind(this), 100);
    this.containerRef = m$2();
  }
  resize() {
    if (this.state.height !== this.base.offsetHeight) {
      this.setState({ height: this.base.offsetHeight });
    }
  }
  handleScroll() {
    if (this.base) {
      this.setState({ offset: this.base.scrollTop });
    }
    if (this.props.sync) {
      this.forceUpdate();
    }
  }
  componentDidUpdate() {
    this.resize();
  }
  componentDidMount() {
    this.resize();
    window.addEventListener("resize", this.resize);
  }
  componentWillUnmount() {
    window.removeEventListener("resize", this.resize);
  }
  render({ data, rowMap, renderRow, overscanCount = 10, ...props }, { offset: offset2 = 0, height = 0 }) {
    const firstVisibleIdx = rowMap.findIndex((row) => {
      return row.start + row.height >= offset2;
    });
    const firstIndex = firstVisibleIdx > -1 ? firstVisibleIdx : 0;
    const lastVisibleIdx = rowMap.findIndex((row) => {
      return row.start + row.height >= offset2 + height;
    });
    const lastIndex = lastVisibleIdx > -1 ? lastVisibleIdx : rowMap.length - 1;
    const lastRow = rowMap[rowMap.length - 1];
    const totalHeight = lastRow ? lastRow.start + lastRow.height : 0;
    let visibleRowCount = lastIndex - firstIndex;
    if (overscanCount) {
      visibleRowCount += overscanCount;
    }
    const start2 = firstVisibleIdx;
    const end2 = Math.min(data.length, start2 + visibleRowCount);
    const selection = data.slice(start2, end2);
    const top2 = firstVisibleIdx !== -1 ? rowMap[firstVisibleIdx].start : 0;
    const rows = m$1`<div onscroll=${this.handleScroll} ...${props}>
      <div style=${`${STYLE_INNER} height:${totalHeight}px;`}>
        <div style=${`${STYLE_CONTENT} top:${top2}px;`} ref=${this.containerRef}>
          ${selection.map((item, index) => {
      const component = renderRow(item, start2 + index);
      return m$1` <div key=${`list-item-${start2 + index}`}>
              ${component}
            </div>`;
    })}
        </div>
      </div>
    </div>`;
    return rows;
  }
}
const kSampleHeight = 88;
const kSeparatorHeight = 24;
const SampleList = (props) => {
  const {
    listRef,
    items,
    sampleDescriptor,
    style,
    selectedIndex,
    setSelectedIndex,
    selectedScore,
    nextSample,
    prevSample,
    showSample
  } = props;
  if (items.length === 0) {
    return m$1`<${EmptyPanel}>No Samples</${EmptyPanel}>`;
  }
  const heightForType = (type) => {
    return type === "sample" ? kSampleHeight : kSeparatorHeight;
  };
  const rowMap = T(() => {
    return items.reduce((values, current, index) => {
      const height = heightForType(current.type);
      const previous = values.length > 0 ? values[values.length - 1] : void 0;
      const start2 = previous === void 0 ? 0 : previous.start + previous.height;
      values.push({
        index,
        height,
        start: start2
      });
      return values;
    }, []);
  }, [items]);
  y(() => {
    const listEl = listRef.current;
    if (listEl) {
      const selected = rowMap[selectedIndex];
      if (selected) {
        const itemTop = selected.start;
        const itemBottom = selected.start + selected.height;
        const scrollTop = listEl.base.scrollTop;
        const scrollBottom = scrollTop + listEl.base.offsetHeight;
        if (itemTop >= scrollTop && itemBottom <= scrollBottom) {
          return;
        }
        if (itemTop < scrollTop) {
          listEl.base.scrollTo({ top: itemTop });
          return;
        }
        if (itemBottom > scrollBottom) {
          listEl.base.scrollTo({ top: itemBottom - listEl.base.offsetHeight });
          return;
        }
      }
    }
  }, [selectedIndex, rowMap, listRef]);
  const renderRow = (item, index) => {
    if (item.type === "sample") {
      return m$1`
        <${SampleRow}
          id=${item.number}
          index=${index}
          sample=${item.data}
          height=${kSampleHeight}
          sampleDescriptor=${sampleDescriptor}
          selected=${selectedIndex === index}
          setSelected=${setSelectedIndex}
          selectedScore=${selectedScore}
          showSample=${showSample}
        />
      `;
    } else if (item.type === "separator") {
      return m$1`
        <${SeparatorRow}
          id=${`sample-group${item.number}`}
          title=${item.data}
          height=${kSeparatorHeight}
        />
      `;
    } else {
      return "";
    }
  };
  const onkeydown = (e2) => {
    switch (e2.key) {
      case "ArrowUp":
        prevSample();
        e2.preventDefault();
        e2.stopPropagation();
        return false;
      case "ArrowDown":
        nextSample();
        e2.preventDefault();
        e2.stopPropagation();
        return false;
      case "Enter":
        showSample();
        e2.preventDefault();
        e2.stopPropagation();
        return false;
    }
  };
  const listStyle = { ...style, flex: "1", overflowY: "auto", outline: "none" };
  const headerRow = m$1`<div
    style=${{
    display: "grid",
    ...gridColumnStyles(sampleDescriptor),
    fontSize: FontSize.smaller,
    ...TextStyle.label,
    ...TextStyle.secondary,
    paddingBottom: "0.3em",
    paddingTop: "0.3em",
    borderBottom: "solid var(--bs-light-border-subtle) 1px"
  }}
  >
    <div>Id</div>
    <div>Input</div>
    <div>Target</div>
    <div>Answer</div>
    <div>Score</div>
  </div>`;
  return m$1` <div
    style=${{ display: "flex", flexDirection: "column", width: "100%" }}
  >
    ${headerRow}
    <${VirtualList}
      ref=${listRef}
      data=${items}
      tabIndex="0"
      renderRow=${renderRow}
      onkeydown=${onkeydown}
      rowMap=${rowMap}
      style=${listStyle}
    />
  </div>`;
};
const SeparatorRow = ({ id, title, height }) => {
  return m$1`<div
    id=${id}
    style=${{
    padding: ".25em 1em .25em 1em",
    textTransform: "uppercase",
    ...TextStyle.secondary,
    fontSize: FontSize.smaller,
    fontWeight: 600,
    borderBottom: "solid 1px var(--bs-border-color)",
    height: `${height}px`
  }}
  >
    <div>${title}</div>
  </div>`;
};
const SampleRow = ({
  id,
  index,
  sample,
  sampleDescriptor,
  height,
  selected,
  setSelected,
  showSample
}) => {
  const selectedStyle = selected ? {
    boxShadow: "inset 0 0 0px 2px var(--bs-focus-ring-color)"
  } : {};
  const cellStyle = {
    paddingLeft: "0em",
    paddingRight: "0em"
  };
  return m$1`
    <div
      id=${`sample-${id}`}
      onclick=${() => {
    if (setSelected) {
      setSelected(index);
    }
    if (showSample) {
      showSample();
    }
  }}
      style=${{
    height: `${height}px`,
    display: "grid",
    ...gridColumnStyles(sampleDescriptor),
    paddingTop: "1em",
    paddingBottom: "1em",
    gridTemplateRows: `${height - 28}px`,
    fontSize: FontSize.base,
    borderBottom: "solid var(--bs-border-color) 1px",
    cursor: "pointer",
    ...selectedStyle,
    overflowY: "hidden"
  }}
    >
      <div class="sample-index" style=${{ ...cellStyle }}>${id}</div>
      <div
        class="sample-input"
        style=${{
    ...ApplicationStyles.threeLineClamp,
    wordWrap: "anywhere",
    ...cellStyle
  }}
      >
        ${inputString(sample.input)}
      </div>
      <div
        class="sample-target"
        style=${{
    ...ApplicationStyles.threeLineClamp,
    ...cellStyle
  }}
      >
        <${MarkdownDiv}
          markdown=${arrayToString(sample == null ? void 0 : sample.target)}
          style=${{ paddingLeft: "0" }}
          class="no-last-para-padding"
        />
      </div>
      <div
        class="sample-answer"
        style=${{
    ...ApplicationStyles.threeLineClamp,
    ...cellStyle
  }}
      >
        ${sample ? m$1`
              <${MarkdownDiv}
                markdown=${shortenCompletion(
    sampleDescriptor == null ? void 0 : sampleDescriptor.selectedScorer(sample).answer()
  )}
                style=${{ paddingLeft: "0" }}
                class="no-last-para-padding"
              />
            ` : ""}
      </div>

      <div
        style=${{
    fontSize: FontSize.small,
    ...cellStyle,
    display: "flex"
  }}
      >
        ${sampleDescriptor == null ? void 0 : sampleDescriptor.selectedScore(sample).render()}
      </div>
    </div>
  `;
};
const gridColumnStyles = (sampleDescriptor) => {
  const { input, target, answer } = gridColumns(sampleDescriptor);
  return {
    gridGap: "0.5em",
    gridTemplateColumns: `minmax(2rem, auto) ${input}fr ${target}fr ${answer}fr minmax(2rem, auto)`,
    paddingLeft: "1em",
    paddingRight: "1em"
  };
};
const gridColumns = (sampleDescriptor) => {
  const input = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.input) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.input) : 0;
  const target = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.target) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.target) : 0;
  const answer = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.answer) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.answer) : 0;
  return { input, target, answer };
};
const SamplesTab = (props) => {
  const {
    task,
    model,
    samples,
    sampleDescriptor,
    filter,
    sort: sort$1,
    epoch,
    context,
    selectedScore
    //setSelectedScore,
  } = props;
  const [selectedIndex, setSelectedIndex] = h(0);
  const [filteredSamples, setFilteredSamples] = h([]);
  const [items, setItems] = h([]);
  const sampleListRef = A();
  const sampleDialogRef = A();
  y(() => {
    setFilteredSamples(
      (samples || []).filter((sample) => {
        if (epoch && epoch !== "all") {
          if (epoch !== sample.epoch + "") {
            return false;
          }
        }
        if (filter.filterFn && filter.value) {
          return filter.filterFn(sample, filter.value);
        } else {
          return true;
        }
      })
    );
  }, [samples, filter, sort$1, epoch]);
  const showSample = q(() => {
    const dialogEl = sampleDialogRef.current;
    if (dialogEl) {
      const modal = new Modal(dialogEl.base);
      modal.show();
    }
  }, [sampleDialogRef]);
  const hideSample = q(() => {
    const dialogEl = sampleDialogRef.current;
    if (dialogEl && dialogEl.base) {
      const modal = Modal.getInstance(dialogEl.base);
      if (modal) {
        modal.hide();
      }
    }
  }, [sampleDialogRef]);
  y(() => {
    const dialogEl = sampleDialogRef.current;
    if (dialogEl) {
      dialogEl.base.addEventListener("hidden.bs.modal", () => {
        const listEl = sampleListRef.current;
        if (listEl) {
          listEl.base.focus();
        }
      });
    }
  }, [sampleDialogRef, sampleListRef]);
  y(() => {
    const { sorted, order: order2 } = sort(sort$1, filteredSamples, sampleDescriptor);
    const sampleProcessor = getSampleProcessor(
      filteredSamples,
      sort$1,
      epoch,
      order2,
      sampleDescriptor
    );
    const items2 = sorted.flatMap((sample, index) => {
      const results = [];
      const previousSample2 = index !== 0 ? sorted[index - 1] : void 0;
      const items3 = sampleProcessor(sample, index, previousSample2);
      results.push(...items3);
      return results;
    });
    setItems(items2);
    const firstSample = items2.findIndex((val) => {
      return val.type === "sample";
    });
    if (items2.length) {
      setSelectedIndex(firstSample);
    }
    return items2;
  }, [filteredSamples, sort$1, epoch, sampleDescriptor]);
  y(() => {
    hideSample();
  }, [items]);
  const nextSampleIndex = q(() => {
    for (let i2 = selectedIndex + 1; i2 < items.length; i2++) {
      if (items[i2].type === "sample") {
        return i2;
      }
    }
    return -1;
  }, [selectedIndex, items]);
  const previousSampleIndex = q(() => {
    for (let i2 = selectedIndex - 1; i2 >= 0; i2--) {
      if (items[i2].type === "sample") {
        return i2;
      }
    }
    return -1;
  }, [selectedIndex, items]);
  const nextSample = q(() => {
    const next = nextSampleIndex();
    if (next > -1) {
      setSelectedIndex(next);
    }
  }, [selectedIndex, filteredSamples, nextSampleIndex]);
  const previousSample = q(() => {
    const prev = previousSampleIndex();
    if (prev > -1) {
      setSelectedIndex(prev);
    }
  }, [selectedIndex, filteredSamples, previousSampleIndex]);
  const elements = [];
  if ((samples == null ? void 0 : samples.length) === 1 && items.length === 1) {
    elements.push(
      m$1` <${InlineSampleDisplay}
        index="0"
        key=${`${task}-single-sample`}
        id="sample-display"
        sample=${samples[0]}
        sampleDescriptor=${sampleDescriptor}
        context=${context}
      />`
    );
  } else {
    elements.push(
      m$1`<${SampleList}
        listRef=${sampleListRef}
        items=${items}
        sampleDescriptor=${sampleDescriptor}
        selectedIndex=${selectedIndex}
        setSelectedIndex=${setSelectedIndex}
        selectedScore=${selectedScore}
        nextSample=${nextSample}
        prevSample=${previousSample}
        showSample=${showSample}
      />`
    );
  }
  elements.push(m$1`
    <${SampleDialog}
      ref=${sampleDialogRef}
      task=${task}
      model=${model}
      title=${items.length > 0 ? items[selectedIndex].label : void 0}
      index=${items.length > 0 ? items[selectedIndex].number : void 0}
      sample=${items.length > 0 ? items[selectedIndex].data : void 0}
      sampleDescriptor=${sampleDescriptor}
      nextSample=${nextSample}
      prevSample=${previousSample}
      context=${context}
    />
  `);
  return elements;
};
const getSampleProcessor = (samples, sort2, epoch, order2, sampleDescriptor) => {
  if ((sampleDescriptor == null ? void 0 : sampleDescriptor.epochs) > 1) {
    if (byEpoch(sort2) || epoch !== "all") {
      return groupByEpoch(samples, sampleDescriptor, order2);
    } else if (bySample(sort2)) {
      return groupBySample(samples, sampleDescriptor, order2);
    }
  }
  return noGrouping(samples, order2);
};
const noGrouping = (samples, order2) => {
  const counter = getCounter(samples.length, 1, order2);
  return (sample, index) => {
    counter.incrementItem();
    const itemCount = counter.item();
    return [
      {
        label: `Sample ${itemCount}`,
        number: itemCount,
        index,
        data: sample,
        type: "sample"
      }
    ];
  };
};
const groupBySample = (samples, sampleDescriptor, order2) => {
  samples = samples.sort((a2, b2) => {
    return ("" + a2.id).localeCompare(b2.id);
  });
  const groupCount = samples.length / sampleDescriptor.epochs;
  const itemCount = samples.length / groupCount;
  const counter = getCounter(itemCount, groupCount, order2);
  return (sample, index, previousSample) => {
    const results = [];
    const lastId = previousSample ? previousSample.id : void 0;
    if (sample.id !== lastId) {
      counter.incrementGroup();
      results.push({
        label: `Sample ${itemCount}`,
        number: counter.group(),
        index,
        data: `Sample ${counter.group()}`,
        type: "separator"
      });
      counter.resetItem();
    }
    counter.incrementItem();
    results.push({
      label: `Sample ${counter.group()} (Epoch ${counter.item()})`,
      number: counter.item(),
      index,
      data: sample,
      type: "sample"
    });
    return results;
  };
};
const groupByEpoch = (samples, sampleDescriptor, order2) => {
  const groupCount = sampleDescriptor.epochs;
  const itemCount = samples.length / groupCount;
  const counter = getCounter(itemCount, groupCount, order2);
  return (sample, index, previousSample) => {
    const results = [];
    const lastEpoch = previousSample ? previousSample.epoch : -1;
    if (lastEpoch !== sample.epoch) {
      counter.incrementGroup();
      results.push({
        label: `Epoch ${counter.group()}`,
        number: counter.group(),
        index,
        data: `Epoch ${counter.group()}`,
        type: "separator"
      });
      counter.resetItem();
    }
    counter.incrementItem();
    results.push({
      label: `Sample ${counter.item()} (Epoch ${counter.group()})`,
      number: counter.item(),
      index,
      data: sample,
      type: "sample"
    });
    return results;
  };
};
const getCounter = (itemCount, groupCount, order2) => {
  let itemIndex = order2 !== "desc" ? 0 : itemCount + 1;
  let groupIndex = order2 !== "desc" ? 0 : groupCount + 1;
  return {
    resetItem: () => {
      itemIndex = order2 !== "desc" ? 0 : itemCount + 1;
    },
    incrementItem: () => {
      if (order2 !== "desc") {
        itemIndex++;
      } else {
        itemIndex--;
      }
    },
    incrementGroup: () => {
      if (order2 !== "desc") {
        groupIndex++;
      } else {
        groupIndex--;
      }
    },
    item: () => {
      return itemIndex;
    },
    group: () => {
      return groupIndex;
    }
  };
};
const EpochFilter = ({ epochs, epoch, setEpoch }) => {
  const options = ["all"];
  for (let i2 = 1; i2 <= epochs; i2++) {
    options.push(i2 + "");
  }
  return m$1`
    <div style=${{ display: "flex" }}>
      <span
        class="epoch-filter-label"
        style=${{
    alignSelf: "center",
    fontSize: FontSize.smaller,
    ...TextStyle.label,
    ...TextStyle.secondary,
    marginRight: "0.3em",
    marginLeft: "0.2em"
  }}
        >Epochs:</span
      >
      <select
        class="form-select form-select-sm"
        aria-label=".epoch-filter-label"
        style=${{ fontSize: FontSize.smaller }}
        value=${epoch}
        onChange=${(e2) => {
    setEpoch(e2.target.value);
  }}
      >
        ${options.map((option) => {
    return m$1`<option value="${option}">${option}</option>`;
  })}
      </select>
    </div>
  `;
};
const SampleFilter = ({ descriptor, filter, filterChanged }) => {
  var _a;
  const filterCategory = (e2) => {
    const val = e2.currentTarget.value;
    if (val === "all") {
      filterChanged({
        value: void 0,
        filterFn: void 0
      });
    } else {
      filterChanged({
        value: val,
        filterFn: (sample, value) => {
          const score = descriptor.selectedScore(sample);
          if (typeof score.value === "string") {
            return score.value.toLowerCase() === (value == null ? void 0 : value.toLowerCase());
          } else if (typeof score.value === "object") {
            return JSON.stringify(score.value) == value;
          } else {
            return score.value === value;
          }
        }
      });
    }
  };
  const filterInput = (e2) => {
    filterChanged({
      value: e2.currentTarget.value,
      filterFn: filterText(descriptor)
    });
  };
  switch ((_a = descriptor == null ? void 0 : descriptor.scoreDescriptor) == null ? void 0 : _a.scoreType) {
    case kScoreTypePassFail: {
      const options = [{ text: "All", value: "all" }];
      options.push(
        ...descriptor.scoreDescriptor.categories.map((cat) => {
          return { text: cat.text, value: cat.val };
        })
      );
      return m$1`<${SelectFilter}
        value=${filter.value || "all"}
        options=${options}
        filterFn=${filterCategory}
      />`;
    }
    case kScoreTypeCategorical: {
      const options = [{ text: "All", value: "all" }];
      options.push(
        ...descriptor.scoreDescriptor.categories.map((cat) => {
          return { text: cat, value: cat };
        })
      );
      return m$1`<${SelectFilter}
        value=${filter.value || "all"}
        options=${options}
        filterFn=${filterCategory}
      />`;
    }
    case kScoreTypeNumeric: {
      return m$1`
        <input
          type="text"
          class="form-control"
          value=${filter.value}
          placeholder="Filter Samples (score)"
          style=${{ width: "150px" }}
          onInput=${filterInput}
        />
      `;
    }
    case kScoreTypeObject: {
      if (!descriptor.scoreDescriptor.categories) {
        return "";
      }
      const options = [{ text: "All", value: "all" }];
      options.push(
        ...descriptor.scoreDescriptor.categories.map((cat) => {
          return { text: cat.text, value: cat.value };
        })
      );
      return m$1`<${SelectFilter}
        value=${filter.value || "all"}
        options=${options}
        filterFn=${filterCategory}
      />`;
    }
    default: {
      return void 0;
    }
  }
};
const SelectFilter = ({ value, options, filterFn }) => {
  return m$1`
    <div style=${{ display: "flex" }}>
      <span
        class="sample-label"
        style=${{
    alignSelf: "center",
    fontSize: FontSize.smaller,
    ...TextStyle.label,
    ...TextStyle.secondary,
    marginRight: "0.3em",
    marginLeft: "0.2em"
  }}
        >Scores:</span
      >
      <select
        class="form-select form-select-sm"
        aria-label=".sample-label"
        style=${{ fontSize: FontSize.smaller }}
        value=${value}
        onChange=${filterFn}
      >
        ${options.map((option) => {
    return m$1`<option value="${option.value}">${option.text}</option>`;
  })}
      </select>
    </div>
  `;
};
const filterText = (descriptor) => {
  return (sample, value) => {
    const score = descriptor.selectedScore(sample);
    if (!value) {
      return true;
    } else {
      if (isNumeric(value)) {
        if (typeof score.value === "number") {
          return score.value === Number(value);
        } else {
          return Number(score.value) === Number(value);
        }
      } else {
        const filters = [
          {
            prefix: ">=",
            fn: (score2, val) => {
              return score2 >= val;
            }
          },
          {
            prefix: "<=",
            fn: (score2, val) => {
              return score2 <= val;
            }
          },
          {
            prefix: ">",
            fn: (score2, val) => {
              return score2 > val;
            }
          },
          {
            prefix: "<",
            fn: (score2, val) => {
              return score2 < val;
            }
          },
          {
            prefix: "=",
            fn: (score2, val) => {
              return score2 === val;
            }
          },
          {
            prefix: "!=",
            fn: (score2, val) => {
              return score2 !== val;
            }
          }
        ];
        for (const filter of filters) {
          if (value == null ? void 0 : value.startsWith(filter.prefix)) {
            const val = value.slice(filter.prefix.length).trim();
            if (!val) {
              return true;
            }
            const num = Number(val);
            return filter.fn(score.value, num);
          }
        }
        if (typeof score.value === "string") {
          return score.value.toLowerCase() === (value == null ? void 0 : value.toLowerCase());
        } else {
          return score.value === value;
        }
      }
    }
  };
};
const SelectScorer = ({ scores, score, setScore }) => {
  const scorers = scores.reduce((accum, scorer) => {
    if (!accum.find((sc) => {
      return scorer.scorer === sc.scorer;
    })) {
      accum.push(scorer);
    }
    return accum;
  }, []);
  if (scorers.length === 1) {
    return m$1`
      <div style=${{ display: "flex" }}>
        <span
          class="select-scorer-label"
          style=${{
      alignSelf: "center",
      fontSize: FontSize.smaller,
      ...TextStyle.label,
      ...TextStyle.secondary
    }}
          >Score:</span
        >
        <${ScoreSelector}
          scores=${scores}
          selectedIndex=${scoreIndex(score, scores)}
          selectedIndexChanged=${(index) => {
      setScore(scores[index]);
    }}
        />
      </div>
    `;
  } else {
    const scorerScores = scores.filter((sc) => {
      return sc.scorer === score.scorer;
    });
    const selectors = [
      m$1`<${ScorerSelector}
        scorers=${scorers}
        selectedIndex=${scorerIndex(score, scorers)}
        selectedIndexChanged=${(index) => {
        setScore(scorers[index]);
      }}
      />`
    ];
    if (scorerScores.length > 1) {
      selectors.push(
        m$1`<${ScoreSelector}
          style=${{ marginLeft: "1em" }}
          scores=${scorerScores}
          selectedIndex=${scoreIndex(score, scorerScores)}
          selectedIndexChanged=${(index) => {
          setScore(scorerScores[index]);
        }}
        />`
      );
    }
    return m$1`
      <div style=${{ display: "flex" }}>
        <span
          class="select-scorer-label"
          style=${{
      alignSelf: "center",
      fontSize: FontSize.smaller,
      ...TextStyle.label,
      ...TextStyle.secondary,
      marginRight: "0.3em",
      marginLeft: "0.2em"
    }}
          >Scorer:</span
        >
        ${selectors}
      </div>
    `;
  }
};
const ScoreSelector = ({
  scores,
  selectedIndex,
  selectedIndexChanged,
  style
}) => {
  return m$1`<select
    class="form-select form-select-sm"
    aria-label=".select-scorer-label"
    style=${{ fontSize: FontSize.smaller, ...style }}
    value=${scores[selectedIndex].name}
    onChange=${(e2) => {
    selectedIndexChanged(e2.target.selectedIndex);
  }}
  >
    ${scores.map((score) => {
    return m$1`<option value="${score.name}">${score.name}</option>`;
  })}
  </select>`;
};
const ScorerSelector = ({ scorers, selectedIndex, selectedIndexChanged }) => {
  return m$1`<select
    class="form-select form-select-sm"
    aria-label=".epoch-filter-label"
    style=${{ fontSize: FontSize.smaller }}
    value=${scorers[selectedIndex].scorer}
    onChange=${(e2) => {
    selectedIndexChanged(e2.target.selectedIndex);
  }}
  >
    ${scorers.map((scorer) => {
    return m$1`<option value="${scorer.scorer}">${scorer.scorer}</option>`;
  })}
  </select>`;
};
const scoreIndex = (score, scores) => scores.findIndex((sc) => {
  return sc.name === score.name && sc.scorer === score.scorer;
});
const scorerIndex = (score, scores) => scores.findIndex((sc) => {
  return sc.scorer === score.scorer;
});
const SampleTools = (props) => {
  const {
    epoch,
    setEpoch,
    filter,
    filterChanged,
    sort: sort2,
    setSort,
    epochs,
    sampleDescriptor,
    score,
    setScore,
    scores
  } = props;
  const hasEpochs = epochs > 1;
  const tools = [];
  if (scores.length > 1) {
    tools.push(
      m$1`<${SelectScorer}
        scores=${scores}
        score=${score}
        setScore=${setScore}
      />`
    );
  }
  if (hasEpochs) {
    tools.push(
      m$1`<${EpochFilter}
        epoch=${epoch}
        setEpoch="${setEpoch}"
        epochs=${epochs}
      />`
    );
  }
  tools.push(
    m$1`<${SampleFilter}
      filter=${filter}
      filterChanged=${filterChanged}
      descriptor=${sampleDescriptor}
    />`
  );
  tools.push(
    m$1`<${SortFilter}
      sampleDescriptor=${sampleDescriptor}
      sort=${sort2}
      setSort=${setSort}
      epochs=${hasEpochs}
    />`
  );
  return tools;
};
const CopyButton = ({ value }) => {
  return m$1`<button
    class="copy-button"
    style=${{
    border: "none",
    backgroundColor: "inherit",
    opacity: "0.5",
    paddingTop: "0px"
  }}
    data-clipboard-text=${value}
    onclick=${(e2) => {
    const iEl = e2.target;
    if (iEl) {
      iEl.className = `${ApplicationIcons.confirm} primary`;
      setTimeout(() => {
        iEl.className = ApplicationIcons.copy;
      }, 1250);
    }
    return false;
  }}
  >
    <i class=${ApplicationIcons.copy}></i>
  </button>`;
};
const LabeledValue = ({
  label,
  style,
  valueStyle,
  layout = "column",
  children
}) => {
  const flexDirection = layout === "column" ? "column" : "row";
  return m$1` <div
    style=${{
    display: "flex",
    flexDirection,
    ...style
  }}
  >
    <div
      style=${{
    fontSize: FontSize.smaller,
    marginBottom: "-0.2rem",
    ...TextStyle.secondary,
    ...TextStyle.label
  }}
    >
      ${label}
    </div>
    <div style=${{ fontSize: FontSize.base, ...valueStyle }}>${children}</div>
  </div>`;
};
const SecondaryBar = ({ log, status, style }) => {
  var _a, _b, _c;
  if (!log || status !== "success") {
    return "";
  }
  const staticColStyle = {
    flexShrink: "0"
  };
  const epochs = log.eval.config.epochs || 1;
  const hyperparameters = {
    ...log.plan.config,
    ...log.eval.task_args
  };
  const hasConfig = Object.keys(hyperparameters).length > 0;
  const values = [];
  values.push({
    size: "minmax(12%, auto)",
    value: m$1`<${LabeledValue} label="Dataset" style=${staticColStyle}>
    <${DatasetSummary}
      dataset=${(_a = log.eval) == null ? void 0 : _a.dataset}
      samples=${log.samples}
      epochs=${epochs} />
  </${LabeledValue}>
`
  });
  const label = ((_b = log == null ? void 0 : log.results) == null ? void 0 : _b.scores.length) > 1 ? "Scorers" : "Scorer";
  values.push({
    size: "minmax(12%, auto)",
    value: m$1`<${LabeledValue} label="${label}" style=${staticColStyle} style=${{ justifySelf: hasConfig ? "center" : "right" }}>
    <${ScorerSummary} 
      scorers=${(_c = log == null ? void 0 : log.results) == null ? void 0 : _c.scores} />
  </${LabeledValue}>`
  });
  if (hasConfig) {
    values.push({
      size: "minmax(12%, auto)",
      value: m$1`<${LabeledValue} label="Config" style=${{ justifySelf: "right" }}>
      <${ParamSummary} params=${hyperparameters}/>
    </${LabeledValue}>`
    });
  }
  return m$1`
    <div
      style=${{
    margin: "0",
    padding: "0.2em 1em 0.2em 1em",
    display: "grid",
    gridColumnGap: "1em",
    borderTop: "1px solid var(--bs-border-color)",
    gridTemplateColumns: `${values.map((val) => {
      return val.size;
    }).join(" ")}`,
    ...style
  }}
    >
      ${values.map((val) => {
    return val.value;
  })}
    </div>
  `;
};
const DatasetSummary = ({ dataset, samples, epochs, style }) => {
  if (!dataset) {
    return "";
  }
  return m$1`
    <div style=${style}>
      ${dataset.name}${(samples == null ? void 0 : samples.length) ? m$1`${formatDataset(dataset.name, samples.length, epochs)}` : ""}
    </div>
  `;
};
const ScorerSummary = ({ scorers }) => {
  if (!scorers) {
    return "";
  }
  const uniqScorers = /* @__PURE__ */ new Set();
  scorers.forEach((scorer) => {
    uniqScorers.add(scorer.name);
  });
  return Array.from(uniqScorers).join(", ");
};
const ParamSummary = ({ params }) => {
  if (!params) {
    return "";
  }
  const paraValues = Object.keys(params).map((key2) => {
    return `${key2}: ${params[key2]}`;
  });
  if (paraValues.length > 0) {
    return m$1`<code style=${{ padding: 0, color: "var(--bs-body-color)" }}
      >${paraValues.join(", ")}</code
    >`;
  } else {
    return "";
  }
};
const Navbar = ({ file, logs, log, offcanvas }) => {
  var _a, _b;
  const toggleOffCanClass = offcanvas ? "" : " d-md-none";
  const logFileName = file ? filename(file) : "";
  const task = (_a = log == null ? void 0 : log.eval) == null ? void 0 : _a.task;
  const model = (_b = log == null ? void 0 : log.eval) == null ? void 0 : _b.model;
  const results = log == null ? void 0 : log.results;
  const samples = log == null ? void 0 : log.samples;
  const status = log == null ? void 0 : log.status;
  let statusPanel;
  if (status === "success") {
    statusPanel = m$1`<${ResultsPanel} results="${results}" />`;
  } else if (status === "cancelled") {
    statusPanel = m$1`<${CanceledPanel}
      sampleCount=${(samples == null ? void 0 : samples.length) || 0}
    />`;
  } else if (status === "started") {
    statusPanel = m$1`<${RunningPanel} />`;
  }
  const navbarContents = logFileName ? m$1` <div
          class="navbar-brand navbar-text mb-0"
          style=${{
    display: "flex",
    paddingTop: 0,
    marginLeft: "0.5rem",
    minWidth: "250px"
  }}
        >
          ${logs.files.length > 1 || logs.log_dir ? m$1`<button
                id="sidebarToggle"
                class="btn${toggleOffCanClass}"
                type="button"
                data-bs-toggle="offcanvas"
                data-bs-target="#sidebarOffCanvas"
                aria-controls="sidebarOffCanvas"
                style=${{
    padding: "0rem 0.1rem 0.1rem 0rem",
    display: "flex"
  }}
              >
                <i class=${ApplicationIcons.menu}></i>
              </button> ` : ""}
          <div
            style=${{
    display: "flex",
    flexDirection: "column",
    marginLeft: "0.2rem"
  }}
          >
            <div
              style=${{
    marginTop: "0.1rem",
    display: "grid",
    gridTemplateColumns: "minmax(30px,max-content) minmax(100px, max-content)"
  }}
            >
              <div
                style=${{
    fontWeight: 600,
    marginRight: "0.3rem",
    ...ApplicationStyles.wrapText()
  }}
                class="task-title"
                title=${task}
              >
                ${task}
              </div>
              <div
                style=${{
    fontSize: FontSize.base,
    paddingTop: "0.4rem",
    ...ApplicationStyles.wrapText()
  }}
                class="task-model"
                title=${model}
              >
                ${model}
              </div>
            </div>
            <div
              style=${{
    opacity: "0.7",
    marginTop: "0.1rem",
    paddingBottom: 0,
    fontSize: FontSize.small,
    display: "grid",
    gridTemplateColumns: "minmax(0,max-content) max-content"
  }}
            >
              <div
                class="navbar-secondary-text"
                style=${{
    ...ApplicationStyles.wrapText()
  }}
              >
                ${logFileName}
              </div>
              <${CopyButton} value=${file} />
            </div>
          </div>
        </div>

        <div
          class="navbar-text"
          style=${{
    justifyContent: "end",
    marginRight: "1em",
    marginBottom: "0"
  }}
        >
          ${statusPanel}
        </div>` : "";
  return m$1`
    <nav
      class="navbar sticky-top"
      style=${{
    flexWrap: "nowrap"
  }}
    >
      <div
        style=${{
    display: "grid",
    gridTemplateColumns: "1fr auto",
    width: "100%"
  }}
      >
        ${navbarContents}
        <${SecondaryBar}
          log=${log}
          status=${status}
          style=${{ gridColumn: "1/-1" }}
        />
      </div>
    </nav>
  `;
};
const CanceledPanel = ({ sampleCount }) => {
  return m$1`<div
    style=${{
    padding: "1em",
    marginTop: "0.5em",
    textTransform: "uppercase",
    fontSize: FontSize.smaller
  }}
  >
    <i
      class="${ApplicationIcons.logging.info}"
      style=${{ fontSize: FontSize.large }}
    />
    cancelled (${sampleCount} ${sampleCount === 1 ? "sample" : "samples"})
  </div>`;
};
const RunningPanel = () => {
  return m$1`<div
    style=${{
    marginTop: "0.5em",
    display: "inline-grid",
    gridTemplateColumns: "auto auto"
  }}
  >
    <div class="spinner-border spinner-border-sm" role="status"></div>
    <div
      style=${{
    marginLeft: "0.3em",
    paddingTop: "0.2em",
    fontSize: FontSize.smaller
  }}
    >
      Running
    </div>
  </div>`;
};
const ResultsPanel = ({ results }) => {
  if (results.scores.length === 1) {
    const scorers = {};
    results.scores.map((score) => {
      scorers[score.name] = Object.keys(score.metrics).map((key2) => {
        return {
          name: key2,
          value: score.metrics[key2].value,
          reducer: score.reducer
        };
      });
    });
    const metrics = Object.values(scorers)[0];
    return m$1`<div
      style=${{
      display: "flex",
      flexDirection: "row",
      flexWrap: "wrap",
      justifyContent: "end",
      height: "100%",
      alignItems: "center"
    }}
    >
      ${metrics.map((metric, i2) => {
      return m$1`<${VerticalMetric} metric=${metric} isFirst=${i2 === 0} />`;
    })}
    </div>`;
  } else {
    return m$1`<div
      style=${{
      display: "flex",
      flexDirection: "row",
      flexWrap: "wrap",
      justifyContent: "end",
      height: "100%",
      alignItems: "center",
      marginTop: "0.2rem",
      paddingBottom: "0.4rem",
      rowGap: "1em"
    }}
    >
      ${results.scores.map((score, index) => {
      return m$1`<${MultiScorerMetric}
          scorer=${score}
          isFirst=${index === 0}
        />`;
    })}
    </div>`;
  }
};
const VerticalMetric = ({ metric, isFirst }) => {
  const reducer_component = metric.reducer ? m$1` <div
        style=${{
    fontSize: FontSize.smaller,
    textAlign: "center",
    paddingTop: "0.3rem",
    marginBottom: "-0.3rem",
    ...TextStyle.label,
    ...TextStyle.secondary
  }}
      >
        ${metric.reducer}
      </div>` : "";
  return m$1`<div style=${{ paddingLeft: isFirst ? "0" : "1em" }}>
    <div
      class="vertical-metric-label"
      style=${{
    fontSize: FontSize.smaller,
    ...TextStyle.secondary,
    textAlign: "center",
    paddingTop: "0.3rem",
    marginBottom: "-0.2rem",
    ...TextStyle.label,
    ...TextStyle.secondary,
    borderBottom: "solid var(--bs-border-color) 1px"
  }}
    >
      ${metric.name}
    </div>
    ${reducer_component}
    <div
      class="vertical-metric-value"
      style=${{
    fontSize: FontSize.larger,
    fontWeight: "500",
    textAlign: "center"
  }}
    >
      ${formatPrettyDecimal(metric.value)}
    </div>
  </div>`;
};
const MultiScorerMetric = ({ scorer, isFirst }) => {
  const titleFontSize = Object.keys(scorer.metrics).length === 1 ? FontSize.larger : FontSize.base;
  const reducerFontSize = Object.keys(scorer.metrics).length === 1 ? FontSize.small : FontSize.smaller;
  const valueFontSize = Object.keys(scorer.metrics).length === 1 ? FontSize.base : FontSize.base;
  const reducer_component = scorer.reducer ? m$1`<div
        style=${{
    fontSize: reducerFontSize,
    textAlign: "center",
    marginBottom: "-0.3rem",
    ...TextStyle.label,
    ...TextStyle.secondary
  }}
      >
        ${scorer.reducer}
      </div>` : "";
  return m$1`<div style=${{ paddingLeft: isFirst ? "0" : "1.5em" }}>
    <div
      style=${{
    fontSize: titleFontSize,
    textAlign: "center",
    borderBottom: "solid var(--bs-border-color) 1px",
    marginBottom: "-0.1rem",
    ...TextStyle.label,
    ...TextStyle.secondary
  }}
      class="multi-score-label"
    >
      ${scorer.name}
    </div>
    ${reducer_component}
    <div
      style=${{
    display: "grid",
    gridTemplateColumns: "auto auto",
    gridColumnGap: "0.3rem",
    gridRowGap: "0",
    fontSize: valueFontSize
  }}
    >
      ${Object.keys(scorer.metrics).map((key2) => {
    const metric = scorer.metrics[key2];
    return m$1` <div>${metric.name}</div>
          <div style=${{ fontWeight: "600" }}>
            ${formatPrettyDecimal(metric.value)}
          </div>`;
  })}
    </div>
  </div>`;
};
const asyncJsonParse = (text) => {
  return new Promise((resolve, reject) => {
    const blob = new Blob([kWorkerCode], { type: "application/javascript" });
    const blobURL = URL.createObjectURL(blob);
    const worker = new Worker(blobURL);
    try {
      worker.onmessage = function(e2) {
        if (e2.data.success) {
          resolve(e2.data.result);
        } else {
          reject(new Error(e2.data.error));
        }
      };
      worker.onerror = function(error) {
        reject(new Error(error.message));
      };
      worker.postMessage({ scriptContent: kJson5ScriptBase64, text });
    } finally {
      worker.onterminate = function() {
        URL.revokeObjectURL(blobURL);
      };
    }
  });
};
const kWorkerCode = `
self.onmessage = function (e) {
  eval(atob(e.data.scriptContent));
  const text = e.data.text;
  try {
    const result = JSON5.parse(text);
    self.postMessage({ success: true, result });
  } catch (error) {
    self.postMessage({ success: false, error: error.message });
  }
};`;
const kJson5ScriptBase64 = `IWZ1bmN0aW9uKHUsRCl7Im9iamVjdCI9PXR5cGVvZiBleHBvcnRzJiYidW5kZWZpbmVkIiE9dHlwZW9mIG1vZHVsZT9tb2R1bGUuZXhwb3J0cz1EKCk6ImZ1bmN0aW9uIj09dHlwZW9mIGRlZmluZSYmZGVmaW5lLmFtZD9kZWZpbmUoRCk6dS5KU09ONT1EKCl9KHRoaXMsZnVuY3Rpb24oKXsidXNlIHN0cmljdCI7ZnVuY3Rpb24gdSh1LEQpe3JldHVybiB1KEQ9e2V4cG9ydHM6e319LEQuZXhwb3J0cyksRC5leHBvcnRzfXZhciBEPXUoZnVuY3Rpb24odSl7dmFyIEQ9dS5leHBvcnRzPSJ1bmRlZmluZWQiIT10eXBlb2Ygd2luZG93JiZ3aW5kb3cuTWF0aD09TWF0aD93aW5kb3c6InVuZGVmaW5lZCIhPXR5cGVvZiBzZWxmJiZzZWxmLk1hdGg9PU1hdGg/c2VsZjpGdW5jdGlvbigicmV0dXJuIHRoaXMiKSgpOyJudW1iZXIiPT10eXBlb2YgX19nJiYoX19nPUQpfSksZT11KGZ1bmN0aW9uKHUpe3ZhciBEPXUuZXhwb3J0cz17dmVyc2lvbjoiMi42LjUifTsibnVtYmVyIj09dHlwZW9mIF9fZSYmKF9fZT1EKX0pLHI9KGUudmVyc2lvbixmdW5jdGlvbih1KXtyZXR1cm4ib2JqZWN0Ij09dHlwZW9mIHU/bnVsbCE9PXU6ImZ1bmN0aW9uIj09dHlwZW9mIHV9KSx0PWZ1bmN0aW9uKHUpe2lmKCFyKHUpKXRocm93IFR5cGVFcnJvcih1KyIgaXMgbm90IGFuIG9iamVjdCEiKTtyZXR1cm4gdX0sbj1mdW5jdGlvbih1KXt0cnl7cmV0dXJuISF1KCl9Y2F0Y2godSl7cmV0dXJuITB9fSxGPSFuKGZ1bmN0aW9uKCl7cmV0dXJuIDchPU9iamVjdC5kZWZpbmVQcm9wZXJ0eSh7fSwiYSIse2dldDpmdW5jdGlvbigpe3JldHVybiA3fX0pLmF9KSxDPUQuZG9jdW1lbnQsQT1yKEMpJiZyKEMuY3JlYXRlRWxlbWVudCksaT0hRiYmIW4oZnVuY3Rpb24oKXtyZXR1cm4gNyE9T2JqZWN0LmRlZmluZVByb3BlcnR5KCh1PSJkaXYiLEE/Qy5jcmVhdGVFbGVtZW50KHUpOnt9KSwiYSIse2dldDpmdW5jdGlvbigpe3JldHVybiA3fX0pLmE7dmFyIHV9KSxFPU9iamVjdC5kZWZpbmVQcm9wZXJ0eSxvPXtmOkY/T2JqZWN0LmRlZmluZVByb3BlcnR5OmZ1bmN0aW9uKHUsRCxlKXtpZih0KHUpLEQ9ZnVuY3Rpb24odSxEKXtpZighcih1KSlyZXR1cm4gdTt2YXIgZSx0O2lmKEQmJiJmdW5jdGlvbiI9PXR5cGVvZihlPXUudG9TdHJpbmcpJiYhcih0PWUuY2FsbCh1KSkpcmV0dXJuIHQ7aWYoImZ1bmN0aW9uIj09dHlwZW9mKGU9dS52YWx1ZU9mKSYmIXIodD1lLmNhbGwodSkpKXJldHVybiB0O2lmKCFEJiYiZnVuY3Rpb24iPT10eXBlb2YoZT11LnRvU3RyaW5nKSYmIXIodD1lLmNhbGwodSkpKXJldHVybiB0O3Rocm93IFR5cGVFcnJvcigiQ2FuJ3QgY29udmVydCBvYmplY3QgdG8gcHJpbWl0aXZlIHZhbHVlIil9KEQsITApLHQoZSksaSl0cnl7cmV0dXJuIEUodSxELGUpfWNhdGNoKHUpe31pZigiZ2V0ImluIGV8fCJzZXQiaW4gZSl0aHJvdyBUeXBlRXJyb3IoIkFjY2Vzc29ycyBub3Qgc3VwcG9ydGVkISIpO3JldHVybiJ2YWx1ZSJpbiBlJiYodVtEXT1lLnZhbHVlKSx1fX0sYT1GP2Z1bmN0aW9uKHUsRCxlKXtyZXR1cm4gby5mKHUsRCxmdW5jdGlvbih1LEQpe3JldHVybntlbnVtZXJhYmxlOiEoMSZ1KSxjb25maWd1cmFibGU6ISgyJnUpLHdyaXRhYmxlOiEoNCZ1KSx2YWx1ZTpEfX0oMSxlKSl9OmZ1bmN0aW9uKHUsRCxlKXtyZXR1cm4gdVtEXT1lLHV9LGM9e30uaGFzT3duUHJvcGVydHksQj1mdW5jdGlvbih1LEQpe3JldHVybiBjLmNhbGwodSxEKX0scz0wLGY9TWF0aC5yYW5kb20oKSxsPXUoZnVuY3Rpb24odSl7dmFyIHI9RFsiX19jb3JlLWpzX3NoYXJlZF9fIl18fChEWyJfX2NvcmUtanNfc2hhcmVkX18iXT17fSk7KHUuZXhwb3J0cz1mdW5jdGlvbih1LEQpe3JldHVybiByW3VdfHwoclt1XT12b2lkIDAhPT1EP0Q6e30pfSkoInZlcnNpb25zIixbXSkucHVzaCh7dmVyc2lvbjplLnZlcnNpb24sbW9kZToiZ2xvYmFsIixjb3B5cmlnaHQ6IsKpIDIwMTkgRGVuaXMgUHVzaGthcmV2ICh6bG9pcm9jay5ydSkifSl9KSgibmF0aXZlLWZ1bmN0aW9uLXRvLXN0cmluZyIsRnVuY3Rpb24udG9TdHJpbmcpLGQ9dShmdW5jdGlvbih1KXt2YXIgcix0PSJTeW1ib2woIi5jb25jYXQodm9pZCAwPT09KHI9InNyYyIpPyIiOnIsIilfIiwoKytzK2YpLnRvU3RyaW5nKDM2KSksbj0oIiIrbCkuc3BsaXQoInRvU3RyaW5nIik7ZS5pbnNwZWN0U291cmNlPWZ1bmN0aW9uKHUpe3JldHVybiBsLmNhbGwodSl9LCh1LmV4cG9ydHM9ZnVuY3Rpb24odSxlLHIsRil7dmFyIEM9ImZ1bmN0aW9uIj09dHlwZW9mIHI7QyYmKEIociwibmFtZSIpfHxhKHIsIm5hbWUiLGUpKSx1W2VdIT09ciYmKEMmJihCKHIsdCl8fGEocix0LHVbZV0/IiIrdVtlXTpuLmpvaW4oU3RyaW5nKGUpKSkpLHU9PT1EP3VbZV09cjpGP3VbZV0/dVtlXT1yOmEodSxlLHIpOihkZWxldGUgdVtlXSxhKHUsZSxyKSkpfSkoRnVuY3Rpb24ucHJvdG90eXBlLCJ0b1N0cmluZyIsZnVuY3Rpb24oKXtyZXR1cm4iZnVuY3Rpb24iPT10eXBlb2YgdGhpcyYmdGhpc1t0XXx8bC5jYWxsKHRoaXMpfSl9KSx2PWZ1bmN0aW9uKHUsRCxlKXtpZihmdW5jdGlvbih1KXtpZigiZnVuY3Rpb24iIT10eXBlb2YgdSl0aHJvdyBUeXBlRXJyb3IodSsiIGlzIG5vdCBhIGZ1bmN0aW9uISIpfSh1KSx2b2lkIDA9PT1EKXJldHVybiB1O3N3aXRjaChlKXtjYXNlIDE6cmV0dXJuIGZ1bmN0aW9uKGUpe3JldHVybiB1LmNhbGwoRCxlKX07Y2FzZSAyOnJldHVybiBmdW5jdGlvbihlLHIpe3JldHVybiB1LmNhbGwoRCxlLHIpfTtjYXNlIDM6cmV0dXJuIGZ1bmN0aW9uKGUscix0KXtyZXR1cm4gdS5jYWxsKEQsZSxyLHQpfX1yZXR1cm4gZnVuY3Rpb24oKXtyZXR1cm4gdS5hcHBseShELGFyZ3VtZW50cyl9fSxwPWZ1bmN0aW9uKHUscix0KXt2YXIgbixGLEMsQSxpPXUmcC5GLEU9dSZwLkcsbz11JnAuUyxjPXUmcC5QLEI9dSZwLkIscz1FP0Q6bz9EW3JdfHwoRFtyXT17fSk6KERbcl18fHt9KS5wcm90b3R5cGUsZj1FP2U6ZVtyXXx8KGVbcl09e30pLGw9Zi5wcm90b3R5cGV8fChmLnByb3RvdHlwZT17fSk7Zm9yKG4gaW4gRSYmKHQ9ciksdClDPSgoRj0haSYmcyYmdm9pZCAwIT09c1tuXSk/czp0KVtuXSxBPUImJkY/dihDLEQpOmMmJiJmdW5jdGlvbiI9PXR5cGVvZiBDP3YoRnVuY3Rpb24uY2FsbCxDKTpDLHMmJmQocyxuLEMsdSZwLlUpLGZbbl0hPUMmJmEoZixuLEEpLGMmJmxbbl0hPUMmJihsW25dPUMpfTtELmNvcmU9ZSxwLkY9MSxwLkc9MixwLlM9NCxwLlA9OCxwLkI9MTYscC5XPTMyLHAuVT02NCxwLlI9MTI4O3ZhciBoLG09cCxnPU1hdGguY2VpbCx5PU1hdGguZmxvb3Isdz1mdW5jdGlvbih1KXtyZXR1cm4gaXNOYU4odT0rdSk/MDoodT4wP3k6ZykodSl9LGI9KGg9ITEsZnVuY3Rpb24odSxEKXt2YXIgZSxyLHQ9U3RyaW5nKGZ1bmN0aW9uKHUpe2lmKG51bGw9PXUpdGhyb3cgVHlwZUVycm9yKCJDYW4ndCBjYWxsIG1ldGhvZCBvbiAgIit1KTtyZXR1cm4gdX0odSkpLG49dyhEKSxGPXQubGVuZ3RoO3JldHVybiBuPDB8fG4+PUY/aD8iIjp2b2lkIDA6KGU9dC5jaGFyQ29kZUF0KG4pKTw1NTI5Nnx8ZT41NjMxOXx8bisxPT09Rnx8KHI9dC5jaGFyQ29kZUF0KG4rMSkpPDU2MzIwfHxyPjU3MzQzP2g/dC5jaGFyQXQobik6ZTpoP3Quc2xpY2UobixuKzIpOnItNTYzMjArKGUtNTUyOTY8PDEwKSs2NTUzNn0pO20obS5QLCJTdHJpbmciLHtjb2RlUG9pbnRBdDpmdW5jdGlvbih1KXtyZXR1cm4gYih0aGlzLHUpfX0pO2UuU3RyaW5nLmNvZGVQb2ludEF0O3ZhciBTPU1hdGgubWF4LHg9TWF0aC5taW4sTj1TdHJpbmcuZnJvbUNoYXJDb2RlLFA9U3RyaW5nLmZyb21Db2RlUG9pbnQ7bShtLlMrbS5GKighIVAmJjEhPVAubGVuZ3RoKSwiU3RyaW5nIix7ZnJvbUNvZGVQb2ludDpmdW5jdGlvbih1KXtmb3IodmFyIEQsZSxyLHQ9YXJndW1lbnRzLG49W10sRj1hcmd1bWVudHMubGVuZ3RoLEM9MDtGPkM7KXtpZihEPSt0W0MrK10scj0xMTE0MTExLCgoZT13KGU9RCkpPDA/UyhlK3IsMCk6eChlLHIpKSE9PUQpdGhyb3cgUmFuZ2VFcnJvcihEKyIgaXMgbm90IGEgdmFsaWQgY29kZSBwb2ludCIpO24ucHVzaChEPDY1NTM2P04oRCk6Tig1NTI5NisoKEQtPTY1NTM2KT4+MTApLEQlMTAyNCs1NjMyMCkpfXJldHVybiBuLmpvaW4oIiIpfX0pO2UuU3RyaW5nLmZyb21Db2RlUG9pbnQ7dmFyIF8sTyxqLEksVixKLE0sayxMLFQseixILCQsUixHPXtTcGFjZV9TZXBhcmF0b3I6L1tcdTE2ODBcdTIwMDAtXHUyMDBBXHUyMDJGXHUyMDVGXHUzMDAwXS8sSURfU3RhcnQ6L1tceEFBXHhCNVx4QkFceEMwLVx4RDZceEQ4LVx4RjZceEY4LVx1MDJDMVx1MDJDNi1cdTAyRDFcdTAyRTAtXHUwMkU0XHUwMkVDXHUwMkVFXHUwMzcwLVx1MDM3NFx1MDM3Nlx1MDM3N1x1MDM3QS1cdTAzN0RcdTAzN0ZcdTAzODZcdTAzODgtXHUwMzhBXHUwMzhDXHUwMzhFLVx1MDNBMVx1MDNBMy1cdTAzRjVcdTAzRjctXHUwNDgxXHUwNDhBLVx1MDUyRlx1MDUzMS1cdTA1NTZcdTA1NTlcdTA1NjEtXHUwNTg3XHUwNUQwLVx1MDVFQVx1MDVGMC1cdTA1RjJcdTA2MjAtXHUwNjRBXHUwNjZFXHUwNjZGXHUwNjcxLVx1MDZEM1x1MDZENVx1MDZFNVx1MDZFNlx1MDZFRVx1MDZFRlx1MDZGQS1cdTA2RkNcdTA2RkZcdTA3MTBcdTA3MTItXHUwNzJGXHUwNzRELVx1MDdBNVx1MDdCMVx1MDdDQS1cdTA3RUFcdTA3RjRcdTA3RjVcdTA3RkFcdTA4MDAtXHUwODE1XHUwODFBXHUwODI0XHUwODI4XHUwODQwLVx1MDg1OFx1MDg2MC1cdTA4NkFcdTA4QTAtXHUwOEI0XHUwOEI2LVx1MDhCRFx1MDkwNC1cdTA5MzlcdTA5M0RcdTA5NTBcdTA5NTgtXHUwOTYxXHUwOTcxLVx1MDk4MFx1MDk4NS1cdTA5OENcdTA5OEZcdTA5OTBcdTA5OTMtXHUwOUE4XHUwOUFBLVx1MDlCMFx1MDlCMlx1MDlCNi1cdTA5QjlcdTA5QkRcdTA5Q0VcdTA5RENcdTA5RERcdTA5REYtXHUwOUUxXHUwOUYwXHUwOUYxXHUwOUZDXHUwQTA1LVx1MEEwQVx1MEEwRlx1MEExMFx1MEExMy1cdTBBMjhcdTBBMkEtXHUwQTMwXHUwQTMyXHUwQTMzXHUwQTM1XHUwQTM2XHUwQTM4XHUwQTM5XHUwQTU5LVx1MEE1Q1x1MEE1RVx1MEE3Mi1cdTBBNzRcdTBBODUtXHUwQThEXHUwQThGLVx1MEE5MVx1MEE5My1cdTBBQThcdTBBQUEtXHUwQUIwXHUwQUIyXHUwQUIzXHUwQUI1LVx1MEFCOVx1MEFCRFx1MEFEMFx1MEFFMFx1MEFFMVx1MEFGOVx1MEIwNS1cdTBCMENcdTBCMEZcdTBCMTBcdTBCMTMtXHUwQjI4XHUwQjJBLVx1MEIzMFx1MEIzMlx1MEIzM1x1MEIzNS1cdTBCMzlcdTBCM0RcdTBCNUNcdTBCNURcdTBCNUYtXHUwQjYxXHUwQjcxXHUwQjgzXHUwQjg1LVx1MEI4QVx1MEI4RS1cdTBCOTBcdTBCOTItXHUwQjk1XHUwQjk5XHUwQjlBXHUwQjlDXHUwQjlFXHUwQjlGXHUwQkEzXHUwQkE0XHUwQkE4LVx1MEJBQVx1MEJBRS1cdTBCQjlcdTBCRDBcdTBDMDUtXHUwQzBDXHUwQzBFLVx1MEMxMFx1MEMxMi1cdTBDMjhcdTBDMkEtXHUwQzM5XHUwQzNEXHUwQzU4LVx1MEM1QVx1MEM2MFx1MEM2MVx1MEM4MFx1MEM4NS1cdTBDOENcdTBDOEUtXHUwQzkwXHUwQzkyLVx1MENBOFx1MENBQS1cdTBDQjNcdTBDQjUtXHUwQ0I5XHUwQ0JEXHUwQ0RFXHUwQ0UwXHUwQ0UxXHUwQ0YxXHUwQ0YyXHUwRDA1LVx1MEQwQ1x1MEQwRS1cdTBEMTBcdTBEMTItXHUwRDNBXHUwRDNEXHUwRDRFXHUwRDU0LVx1MEQ1Nlx1MEQ1Ri1cdTBENjFcdTBEN0EtXHUwRDdGXHUwRDg1LVx1MEQ5Nlx1MEQ5QS1cdTBEQjFcdTBEQjMtXHUwREJCXHUwREJEXHUwREMwLVx1MERDNlx1MEUwMS1cdTBFMzBcdTBFMzJcdTBFMzNcdTBFNDAtXHUwRTQ2XHUwRTgxXHUwRTgyXHUwRTg0XHUwRTg3XHUwRTg4XHUwRThBXHUwRThEXHUwRTk0LVx1MEU5N1x1MEU5OS1cdTBFOUZcdTBFQTEtXHUwRUEzXHUwRUE1XHUwRUE3XHUwRUFBXHUwRUFCXHUwRUFELVx1MEVCMFx1MEVCMlx1MEVCM1x1MEVCRFx1MEVDMC1cdTBFQzRcdTBFQzZcdTBFREMtXHUwRURGXHUwRjAwXHUwRjQwLVx1MEY0N1x1MEY0OS1cdTBGNkNcdTBGODgtXHUwRjhDXHUxMDAwLVx1MTAyQVx1MTAzRlx1MTA1MC1cdTEwNTVcdTEwNUEtXHUxMDVEXHUxMDYxXHUxMDY1XHUxMDY2XHUxMDZFLVx1MTA3MFx1MTA3NS1cdTEwODFcdTEwOEVcdTEwQTAtXHUxMEM1XHUxMEM3XHUxMENEXHUxMEQwLVx1MTBGQVx1MTBGQy1cdTEyNDhcdTEyNEEtXHUxMjREXHUxMjUwLVx1MTI1Nlx1MTI1OFx1MTI1QS1cdTEyNURcdTEyNjAtXHUxMjg4XHUxMjhBLVx1MTI4RFx1MTI5MC1cdTEyQjBcdTEyQjItXHUxMkI1XHUxMkI4LVx1MTJCRVx1MTJDMFx1MTJDMi1cdTEyQzVcdTEyQzgtXHUxMkQ2XHUxMkQ4LVx1MTMxMFx1MTMxMi1cdTEzMTVcdTEzMTgtXHUxMzVBXHUxMzgwLVx1MTM4Rlx1MTNBMC1cdTEzRjVcdTEzRjgtXHUxM0ZEXHUxNDAxLVx1MTY2Q1x1MTY2Ri1cdTE2N0ZcdTE2ODEtXHUxNjlBXHUxNkEwLVx1MTZFQVx1MTZFRS1cdTE2RjhcdTE3MDAtXHUxNzBDXHUxNzBFLVx1MTcxMVx1MTcyMC1cdTE3MzFcdTE3NDAtXHUxNzUxXHUxNzYwLVx1MTc2Q1x1MTc2RS1cdTE3NzBcdTE3ODAtXHUxN0IzXHUxN0Q3XHUxN0RDXHUxODIwLVx1MTg3N1x1MTg4MC1cdTE4ODRcdTE4ODctXHUxOEE4XHUxOEFBXHUxOEIwLVx1MThGNVx1MTkwMC1cdTE5MUVcdTE5NTAtXHUxOTZEXHUxOTcwLVx1MTk3NFx1MTk4MC1cdTE5QUJcdTE5QjAtXHUxOUM5XHUxQTAwLVx1MUExNlx1MUEyMC1cdTFBNTRcdTFBQTdcdTFCMDUtXHUxQjMzXHUxQjQ1LVx1MUI0Qlx1MUI4My1cdTFCQTBcdTFCQUVcdTFCQUZcdTFCQkEtXHUxQkU1XHUxQzAwLVx1MUMyM1x1MUM0RC1cdTFDNEZcdTFDNUEtXHUxQzdEXHUxQzgwLVx1MUM4OFx1MUNFOS1cdTFDRUNcdTFDRUUtXHUxQ0YxXHUxQ0Y1XHUxQ0Y2XHUxRDAwLVx1MURCRlx1MUUwMC1cdTFGMTVcdTFGMTgtXHUxRjFEXHUxRjIwLVx1MUY0NVx1MUY0OC1cdTFGNERcdTFGNTAtXHUxRjU3XHUxRjU5XHUxRjVCXHUxRjVEXHUxRjVGLVx1MUY3RFx1MUY4MC1cdTFGQjRcdTFGQjYtXHUxRkJDXHUxRkJFXHUxRkMyLVx1MUZDNFx1MUZDNi1cdTFGQ0NcdTFGRDAtXHUxRkQzXHUxRkQ2LVx1MUZEQlx1MUZFMC1cdTFGRUNcdTFGRjItXHUxRkY0XHUxRkY2LVx1MUZGQ1x1MjA3MVx1MjA3Rlx1MjA5MC1cdTIwOUNcdTIxMDJcdTIxMDdcdTIxMEEtXHUyMTEzXHUyMTE1XHUyMTE5LVx1MjExRFx1MjEyNFx1MjEyNlx1MjEyOFx1MjEyQS1cdTIxMkRcdTIxMkYtXHUyMTM5XHUyMTNDLVx1MjEzRlx1MjE0NS1cdTIxNDlcdTIxNEVcdTIxNjAtXHUyMTg4XHUyQzAwLVx1MkMyRVx1MkMzMC1cdTJDNUVcdTJDNjAtXHUyQ0U0XHUyQ0VCLVx1MkNFRVx1MkNGMlx1MkNGM1x1MkQwMC1cdTJEMjVcdTJEMjdcdTJEMkRcdTJEMzAtXHUyRDY3XHUyRDZGXHUyRDgwLVx1MkQ5Nlx1MkRBMC1cdTJEQTZcdTJEQTgtXHUyREFFXHUyREIwLVx1MkRCNlx1MkRCOC1cdTJEQkVcdTJEQzAtXHUyREM2XHUyREM4LVx1MkRDRVx1MkREMC1cdTJERDZcdTJERDgtXHUyRERFXHUyRTJGXHUzMDA1LVx1MzAwN1x1MzAyMS1cdTMwMjlcdTMwMzEtXHUzMDM1XHUzMDM4LVx1MzAzQ1x1MzA0MS1cdTMwOTZcdTMwOUQtXHUzMDlGXHUzMEExLVx1MzBGQVx1MzBGQy1cdTMwRkZcdTMxMDUtXHUzMTJFXHUzMTMxLVx1MzE4RVx1MzFBMC1cdTMxQkFcdTMxRjAtXHUzMUZGXHUzNDAwLVx1NERCNVx1NEUwMC1cdTlGRUFcdUEwMDAtXHVBNDhDXHVBNEQwLVx1QTRGRFx1QTUwMC1cdUE2MENcdUE2MTAtXHVBNjFGXHVBNjJBXHVBNjJCXHVBNjQwLVx1QTY2RVx1QTY3Ri1cdUE2OURcdUE2QTAtXHVBNkVGXHVBNzE3LVx1QTcxRlx1QTcyMi1cdUE3ODhcdUE3OEItXHVBN0FFXHVBN0IwLVx1QTdCN1x1QTdGNy1cdUE4MDFcdUE4MDMtXHVBODA1XHVBODA3LVx1QTgwQVx1QTgwQy1cdUE4MjJcdUE4NDAtXHVBODczXHVBODgyLVx1QThCM1x1QThGMi1cdUE4RjdcdUE4RkJcdUE4RkRcdUE5MEEtXHVBOTI1XHVBOTMwLVx1QTk0Nlx1QTk2MC1cdUE5N0NcdUE5ODQtXHVBOUIyXHVBOUNGXHVBOUUwLVx1QTlFNFx1QTlFNi1cdUE5RUZcdUE5RkEtXHVBOUZFXHVBQTAwLVx1QUEyOFx1QUE0MC1cdUFBNDJcdUFBNDQtXHVBQTRCXHVBQTYwLVx1QUE3Nlx1QUE3QVx1QUE3RS1cdUFBQUZcdUFBQjFcdUFBQjVcdUFBQjZcdUFBQjktXHVBQUJEXHVBQUMwXHVBQUMyXHVBQURCLVx1QUFERFx1QUFFMC1cdUFBRUFcdUFBRjItXHVBQUY0XHVBQjAxLVx1QUIwNlx1QUIwOS1cdUFCMEVcdUFCMTEtXHVBQjE2XHVBQjIwLVx1QUIyNlx1QUIyOC1cdUFCMkVcdUFCMzAtXHVBQjVBXHVBQjVDLVx1QUI2NVx1QUI3MC1cdUFCRTJcdUFDMDAtXHVEN0EzXHVEN0IwLVx1RDdDNlx1RDdDQi1cdUQ3RkJcdUY5MDAtXHVGQTZEXHVGQTcwLVx1RkFEOVx1RkIwMC1cdUZCMDZcdUZCMTMtXHVGQjE3XHVGQjFEXHVGQjFGLVx1RkIyOFx1RkIyQS1cdUZCMzZcdUZCMzgtXHVGQjNDXHVGQjNFXHVGQjQwXHVGQjQxXHVGQjQzXHVGQjQ0XHVGQjQ2LVx1RkJCMVx1RkJEMy1cdUZEM0RcdUZENTAtXHVGRDhGXHVGRDkyLVx1RkRDN1x1RkRGMC1cdUZERkJcdUZFNzAtXHVGRTc0XHVGRTc2LVx1RkVGQ1x1RkYyMS1cdUZGM0FcdUZGNDEtXHVGRjVBXHVGRjY2LVx1RkZCRVx1RkZDMi1cdUZGQzdcdUZGQ0EtXHVGRkNGXHVGRkQyLVx1RkZEN1x1RkZEQS1cdUZGRENdfFx1RDgwMFtcdURDMDAtXHVEQzBCXHVEQzBELVx1REMyNlx1REMyOC1cdURDM0FcdURDM0NcdURDM0RcdURDM0YtXHVEQzREXHVEQzUwLVx1REM1RFx1REM4MC1cdURDRkFcdURENDAtXHVERDc0XHVERTgwLVx1REU5Q1x1REVBMC1cdURFRDBcdURGMDAtXHVERjFGXHVERjJELVx1REY0QVx1REY1MC1cdURGNzVcdURGODAtXHVERjlEXHVERkEwLVx1REZDM1x1REZDOC1cdURGQ0ZcdURGRDEtXHVERkQ1XXxcdUQ4MDFbXHVEQzAwLVx1REM5RFx1RENCMC1cdURDRDNcdURDRDgtXHVEQ0ZCXHVERDAwLVx1REQyN1x1REQzMC1cdURENjNcdURFMDAtXHVERjM2XHVERjQwLVx1REY1NVx1REY2MC1cdURGNjddfFx1RDgwMltcdURDMDAtXHVEQzA1XHVEQzA4XHVEQzBBLVx1REMzNVx1REMzN1x1REMzOFx1REMzQ1x1REMzRi1cdURDNTVcdURDNjAtXHVEQzc2XHVEQzgwLVx1REM5RVx1RENFMC1cdURDRjJcdURDRjRcdURDRjVcdUREMDAtXHVERDE1XHVERDIwLVx1REQzOVx1REQ4MC1cdUREQjdcdUREQkVcdUREQkZcdURFMDBcdURFMTAtXHVERTEzXHVERTE1LVx1REUxN1x1REUxOS1cdURFMzNcdURFNjAtXHVERTdDXHVERTgwLVx1REU5Q1x1REVDMC1cdURFQzdcdURFQzktXHVERUU0XHVERjAwLVx1REYzNVx1REY0MC1cdURGNTVcdURGNjAtXHVERjcyXHVERjgwLVx1REY5MV18XHVEODAzW1x1REMwMC1cdURDNDhcdURDODAtXHVEQ0IyXHVEQ0MwLVx1RENGMl18XHVEODA0W1x1REMwMy1cdURDMzdcdURDODMtXHVEQ0FGXHVEQ0QwLVx1RENFOFx1REQwMy1cdUREMjZcdURENTAtXHVERDcyXHVERDc2XHVERDgzLVx1RERCMlx1RERDMS1cdUREQzRcdUREREFcdURERENcdURFMDAtXHVERTExXHVERTEzLVx1REUyQlx1REU4MC1cdURFODZcdURFODhcdURFOEEtXHVERThEXHVERThGLVx1REU5RFx1REU5Ri1cdURFQThcdURFQjAtXHVERURFXHVERjA1LVx1REYwQ1x1REYwRlx1REYxMFx1REYxMy1cdURGMjhcdURGMkEtXHVERjMwXHVERjMyXHVERjMzXHVERjM1LVx1REYzOVx1REYzRFx1REY1MFx1REY1RC1cdURGNjFdfFx1RDgwNVtcdURDMDAtXHVEQzM0XHVEQzQ3LVx1REM0QVx1REM4MC1cdURDQUZcdURDQzRcdURDQzVcdURDQzdcdUREODAtXHVEREFFXHVEREQ4LVx1REREQlx1REUwMC1cdURFMkZcdURFNDRcdURFODAtXHVERUFBXHVERjAwLVx1REYxOV18XHVEODA2W1x1RENBMC1cdURDREZcdURDRkZcdURFMDBcdURFMEItXHVERTMyXHVERTNBXHVERTUwXHVERTVDLVx1REU4M1x1REU4Ni1cdURFODlcdURFQzAtXHVERUY4XXxcdUQ4MDdbXHVEQzAwLVx1REMwOFx1REMwQS1cdURDMkVcdURDNDBcdURDNzItXHVEQzhGXHVERDAwLVx1REQwNlx1REQwOFx1REQwOVx1REQwQi1cdUREMzBcdURENDZdfFx1RDgwOFtcdURDMDAtXHVERjk5XXxcdUQ4MDlbXHVEQzAwLVx1REM2RVx1REM4MC1cdURENDNdfFtcdUQ4MENcdUQ4MUMtXHVEODIwXHVEODQwLVx1RDg2OFx1RDg2QS1cdUQ4NkNcdUQ4NkYtXHVEODcyXHVEODc0LVx1RDg3OV1bXHVEQzAwLVx1REZGRl18XHVEODBEW1x1REMwMC1cdURDMkVdfFx1RDgxMVtcdURDMDAtXHVERTQ2XXxcdUQ4MUFbXHVEQzAwLVx1REUzOFx1REU0MC1cdURFNUVcdURFRDAtXHVERUVEXHVERjAwLVx1REYyRlx1REY0MC1cdURGNDNcdURGNjMtXHVERjc3XHVERjdELVx1REY4Rl18XHVEODFCW1x1REYwMC1cdURGNDRcdURGNTBcdURGOTMtXHVERjlGXHVERkUwXHVERkUxXXxcdUQ4MjFbXHVEQzAwLVx1REZFQ118XHVEODIyW1x1REMwMC1cdURFRjJdfFx1RDgyQ1tcdURDMDAtXHVERDFFXHVERDcwLVx1REVGQl18XHVEODJGW1x1REMwMC1cdURDNkFcdURDNzAtXHVEQzdDXHVEQzgwLVx1REM4OFx1REM5MC1cdURDOTldfFx1RDgzNVtcdURDMDAtXHVEQzU0XHVEQzU2LVx1REM5Q1x1REM5RVx1REM5Rlx1RENBMlx1RENBNVx1RENBNlx1RENBOS1cdURDQUNcdURDQUUtXHVEQ0I5XHVEQ0JCXHVEQ0JELVx1RENDM1x1RENDNS1cdUREMDVcdUREMDctXHVERDBBXHVERDBELVx1REQxNFx1REQxNi1cdUREMUNcdUREMUUtXHVERDM5XHVERDNCLVx1REQzRVx1REQ0MC1cdURENDRcdURENDZcdURENEEtXHVERDUwXHVERDUyLVx1REVBNVx1REVBOC1cdURFQzBcdURFQzItXHVERURBXHVERURDLVx1REVGQVx1REVGQy1cdURGMTRcdURGMTYtXHVERjM0XHVERjM2LVx1REY0RVx1REY1MC1cdURGNkVcdURGNzAtXHVERjg4XHVERjhBLVx1REZBOFx1REZBQS1cdURGQzJcdURGQzQtXHVERkNCXXxcdUQ4M0FbXHVEQzAwLVx1RENDNFx1REQwMC1cdURENDNdfFx1RDgzQltcdURFMDAtXHVERTAzXHVERTA1LVx1REUxRlx1REUyMVx1REUyMlx1REUyNFx1REUyN1x1REUyOS1cdURFMzJcdURFMzQtXHVERTM3XHVERTM5XHVERTNCXHVERTQyXHVERTQ3XHVERTQ5XHVERTRCXHVERTRELVx1REU0Rlx1REU1MVx1REU1Mlx1REU1NFx1REU1N1x1REU1OVx1REU1Qlx1REU1RFx1REU1Rlx1REU2MVx1REU2Mlx1REU2NFx1REU2Ny1cdURFNkFcdURFNkMtXHVERTcyXHVERTc0LVx1REU3N1x1REU3OS1cdURFN0NcdURFN0VcdURFODAtXHVERTg5XHVERThCLVx1REU5Qlx1REVBMS1cdURFQTNcdURFQTUtXHVERUE5XHVERUFCLVx1REVCQl18XHVEODY5W1x1REMwMC1cdURFRDZcdURGMDAtXHVERkZGXXxcdUQ4NkRbXHVEQzAwLVx1REYzNFx1REY0MC1cdURGRkZdfFx1RDg2RVtcdURDMDAtXHVEQzFEXHVEQzIwLVx1REZGRl18XHVEODczW1x1REMwMC1cdURFQTFcdURFQjAtXHVERkZGXXxcdUQ4N0FbXHVEQzAwLVx1REZFMF18XHVEODdFW1x1REMwMC1cdURFMURdLyxJRF9Db250aW51ZTovW1x4QUFceEI1XHhCQVx4QzAtXHhENlx4RDgtXHhGNlx4RjgtXHUwMkMxXHUwMkM2LVx1MDJEMVx1MDJFMC1cdTAyRTRcdTAyRUNcdTAyRUVcdTAzMDAtXHUwMzc0XHUwMzc2XHUwMzc3XHUwMzdBLVx1MDM3RFx1MDM3Rlx1MDM4Nlx1MDM4OC1cdTAzOEFcdTAzOENcdTAzOEUtXHUwM0ExXHUwM0EzLVx1MDNGNVx1MDNGNy1cdTA0ODFcdTA0ODMtXHUwNDg3XHUwNDhBLVx1MDUyRlx1MDUzMS1cdTA1NTZcdTA1NTlcdTA1NjEtXHUwNTg3XHUwNTkxLVx1MDVCRFx1MDVCRlx1MDVDMVx1MDVDMlx1MDVDNFx1MDVDNVx1MDVDN1x1MDVEMC1cdTA1RUFcdTA1RjAtXHUwNUYyXHUwNjEwLVx1MDYxQVx1MDYyMC1cdTA2NjlcdTA2NkUtXHUwNkQzXHUwNkQ1LVx1MDZEQ1x1MDZERi1cdTA2RThcdTA2RUEtXHUwNkZDXHUwNkZGXHUwNzEwLVx1MDc0QVx1MDc0RC1cdTA3QjFcdTA3QzAtXHUwN0Y1XHUwN0ZBXHUwODAwLVx1MDgyRFx1MDg0MC1cdTA4NUJcdTA4NjAtXHUwODZBXHUwOEEwLVx1MDhCNFx1MDhCNi1cdTA4QkRcdTA4RDQtXHUwOEUxXHUwOEUzLVx1MDk2M1x1MDk2Ni1cdTA5NkZcdTA5NzEtXHUwOTgzXHUwOTg1LVx1MDk4Q1x1MDk4Rlx1MDk5MFx1MDk5My1cdTA5QThcdTA5QUEtXHUwOUIwXHUwOUIyXHUwOUI2LVx1MDlCOVx1MDlCQy1cdTA5QzRcdTA5QzdcdTA5QzhcdTA5Q0ItXHUwOUNFXHUwOUQ3XHUwOURDXHUwOUREXHUwOURGLVx1MDlFM1x1MDlFNi1cdTA5RjFcdTA5RkNcdTBBMDEtXHUwQTAzXHUwQTA1LVx1MEEwQVx1MEEwRlx1MEExMFx1MEExMy1cdTBBMjhcdTBBMkEtXHUwQTMwXHUwQTMyXHUwQTMzXHUwQTM1XHUwQTM2XHUwQTM4XHUwQTM5XHUwQTNDXHUwQTNFLVx1MEE0Mlx1MEE0N1x1MEE0OFx1MEE0Qi1cdTBBNERcdTBBNTFcdTBBNTktXHUwQTVDXHUwQTVFXHUwQTY2LVx1MEE3NVx1MEE4MS1cdTBBODNcdTBBODUtXHUwQThEXHUwQThGLVx1MEE5MVx1MEE5My1cdTBBQThcdTBBQUEtXHUwQUIwXHUwQUIyXHUwQUIzXHUwQUI1LVx1MEFCOVx1MEFCQy1cdTBBQzVcdTBBQzctXHUwQUM5XHUwQUNCLVx1MEFDRFx1MEFEMFx1MEFFMC1cdTBBRTNcdTBBRTYtXHUwQUVGXHUwQUY5LVx1MEFGRlx1MEIwMS1cdTBCMDNcdTBCMDUtXHUwQjBDXHUwQjBGXHUwQjEwXHUwQjEzLVx1MEIyOFx1MEIyQS1cdTBCMzBcdTBCMzJcdTBCMzNcdTBCMzUtXHUwQjM5XHUwQjNDLVx1MEI0NFx1MEI0N1x1MEI0OFx1MEI0Qi1cdTBCNERcdTBCNTZcdTBCNTdcdTBCNUNcdTBCNURcdTBCNUYtXHUwQjYzXHUwQjY2LVx1MEI2Rlx1MEI3MVx1MEI4Mlx1MEI4M1x1MEI4NS1cdTBCOEFcdTBCOEUtXHUwQjkwXHUwQjkyLVx1MEI5NVx1MEI5OVx1MEI5QVx1MEI5Q1x1MEI5RVx1MEI5Rlx1MEJBM1x1MEJBNFx1MEJBOC1cdTBCQUFcdTBCQUUtXHUwQkI5XHUwQkJFLVx1MEJDMlx1MEJDNi1cdTBCQzhcdTBCQ0EtXHUwQkNEXHUwQkQwXHUwQkQ3XHUwQkU2LVx1MEJFRlx1MEMwMC1cdTBDMDNcdTBDMDUtXHUwQzBDXHUwQzBFLVx1MEMxMFx1MEMxMi1cdTBDMjhcdTBDMkEtXHUwQzM5XHUwQzNELVx1MEM0NFx1MEM0Ni1cdTBDNDhcdTBDNEEtXHUwQzREXHUwQzU1XHUwQzU2XHUwQzU4LVx1MEM1QVx1MEM2MC1cdTBDNjNcdTBDNjYtXHUwQzZGXHUwQzgwLVx1MEM4M1x1MEM4NS1cdTBDOENcdTBDOEUtXHUwQzkwXHUwQzkyLVx1MENBOFx1MENBQS1cdTBDQjNcdTBDQjUtXHUwQ0I5XHUwQ0JDLVx1MENDNFx1MENDNi1cdTBDQzhcdTBDQ0EtXHUwQ0NEXHUwQ0Q1XHUwQ0Q2XHUwQ0RFXHUwQ0UwLVx1MENFM1x1MENFNi1cdTBDRUZcdTBDRjFcdTBDRjJcdTBEMDAtXHUwRDAzXHUwRDA1LVx1MEQwQ1x1MEQwRS1cdTBEMTBcdTBEMTItXHUwRDQ0XHUwRDQ2LVx1MEQ0OFx1MEQ0QS1cdTBENEVcdTBENTQtXHUwRDU3XHUwRDVGLVx1MEQ2M1x1MEQ2Ni1cdTBENkZcdTBEN0EtXHUwRDdGXHUwRDgyXHUwRDgzXHUwRDg1LVx1MEQ5Nlx1MEQ5QS1cdTBEQjFcdTBEQjMtXHUwREJCXHUwREJEXHUwREMwLVx1MERDNlx1MERDQVx1MERDRi1cdTBERDRcdTBERDZcdTBERDgtXHUwRERGXHUwREU2LVx1MERFRlx1MERGMlx1MERGM1x1MEUwMS1cdTBFM0FcdTBFNDAtXHUwRTRFXHUwRTUwLVx1MEU1OVx1MEU4MVx1MEU4Mlx1MEU4NFx1MEU4N1x1MEU4OFx1MEU4QVx1MEU4RFx1MEU5NC1cdTBFOTdcdTBFOTktXHUwRTlGXHUwRUExLVx1MEVBM1x1MEVBNVx1MEVBN1x1MEVBQVx1MEVBQlx1MEVBRC1cdTBFQjlcdTBFQkItXHUwRUJEXHUwRUMwLVx1MEVDNFx1MEVDNlx1MEVDOC1cdTBFQ0RcdTBFRDAtXHUwRUQ5XHUwRURDLVx1MEVERlx1MEYwMFx1MEYxOFx1MEYxOVx1MEYyMC1cdTBGMjlcdTBGMzVcdTBGMzdcdTBGMzlcdTBGM0UtXHUwRjQ3XHUwRjQ5LVx1MEY2Q1x1MEY3MS1cdTBGODRcdTBGODYtXHUwRjk3XHUwRjk5LVx1MEZCQ1x1MEZDNlx1MTAwMC1cdTEwNDlcdTEwNTAtXHUxMDlEXHUxMEEwLVx1MTBDNVx1MTBDN1x1MTBDRFx1MTBEMC1cdTEwRkFcdTEwRkMtXHUxMjQ4XHUxMjRBLVx1MTI0RFx1MTI1MC1cdTEyNTZcdTEyNThcdTEyNUEtXHUxMjVEXHUxMjYwLVx1MTI4OFx1MTI4QS1cdTEyOERcdTEyOTAtXHUxMkIwXHUxMkIyLVx1MTJCNVx1MTJCOC1cdTEyQkVcdTEyQzBcdTEyQzItXHUxMkM1XHUxMkM4LVx1MTJENlx1MTJEOC1cdTEzMTBcdTEzMTItXHUxMzE1XHUxMzE4LVx1MTM1QVx1MTM1RC1cdTEzNUZcdTEzODAtXHUxMzhGXHUxM0EwLVx1MTNGNVx1MTNGOC1cdTEzRkRcdTE0MDEtXHUxNjZDXHUxNjZGLVx1MTY3Rlx1MTY4MS1cdTE2OUFcdTE2QTAtXHUxNkVBXHUxNkVFLVx1MTZGOFx1MTcwMC1cdTE3MENcdTE3MEUtXHUxNzE0XHUxNzIwLVx1MTczNFx1MTc0MC1cdTE3NTNcdTE3NjAtXHUxNzZDXHUxNzZFLVx1MTc3MFx1MTc3Mlx1MTc3M1x1MTc4MC1cdTE3RDNcdTE3RDdcdTE3RENcdTE3RERcdTE3RTAtXHUxN0U5XHUxODBCLVx1MTgwRFx1MTgxMC1cdTE4MTlcdTE4MjAtXHUxODc3XHUxODgwLVx1MThBQVx1MThCMC1cdTE4RjVcdTE5MDAtXHUxOTFFXHUxOTIwLVx1MTkyQlx1MTkzMC1cdTE5M0JcdTE5NDYtXHUxOTZEXHUxOTcwLVx1MTk3NFx1MTk4MC1cdTE5QUJcdTE5QjAtXHUxOUM5XHUxOUQwLVx1MTlEOVx1MUEwMC1cdTFBMUJcdTFBMjAtXHUxQTVFXHUxQTYwLVx1MUE3Q1x1MUE3Ri1cdTFBODlcdTFBOTAtXHUxQTk5XHUxQUE3XHUxQUIwLVx1MUFCRFx1MUIwMC1cdTFCNEJcdTFCNTAtXHUxQjU5XHUxQjZCLVx1MUI3M1x1MUI4MC1cdTFCRjNcdTFDMDAtXHUxQzM3XHUxQzQwLVx1MUM0OVx1MUM0RC1cdTFDN0RcdTFDODAtXHUxQzg4XHUxQ0QwLVx1MUNEMlx1MUNENC1cdTFDRjlcdTFEMDAtXHUxREY5XHUxREZCLVx1MUYxNVx1MUYxOC1cdTFGMURcdTFGMjAtXHUxRjQ1XHUxRjQ4LVx1MUY0RFx1MUY1MC1cdTFGNTdcdTFGNTlcdTFGNUJcdTFGNURcdTFGNUYtXHUxRjdEXHUxRjgwLVx1MUZCNFx1MUZCNi1cdTFGQkNcdTFGQkVcdTFGQzItXHUxRkM0XHUxRkM2LVx1MUZDQ1x1MUZEMC1cdTFGRDNcdTFGRDYtXHUxRkRCXHUxRkUwLVx1MUZFQ1x1MUZGMi1cdTFGRjRcdTFGRjYtXHUxRkZDXHUyMDNGXHUyMDQwXHUyMDU0XHUyMDcxXHUyMDdGXHUyMDkwLVx1MjA5Q1x1MjBEMC1cdTIwRENcdTIwRTFcdTIwRTUtXHUyMEYwXHUyMTAyXHUyMTA3XHUyMTBBLVx1MjExM1x1MjExNVx1MjExOS1cdTIxMURcdTIxMjRcdTIxMjZcdTIxMjhcdTIxMkEtXHUyMTJEXHUyMTJGLVx1MjEzOVx1MjEzQy1cdTIxM0ZcdTIxNDUtXHUyMTQ5XHUyMTRFXHUyMTYwLVx1MjE4OFx1MkMwMC1cdTJDMkVcdTJDMzAtXHUyQzVFXHUyQzYwLVx1MkNFNFx1MkNFQi1cdTJDRjNcdTJEMDAtXHUyRDI1XHUyRDI3XHUyRDJEXHUyRDMwLVx1MkQ2N1x1MkQ2Rlx1MkQ3Ri1cdTJEOTZcdTJEQTAtXHUyREE2XHUyREE4LVx1MkRBRVx1MkRCMC1cdTJEQjZcdTJEQjgtXHUyREJFXHUyREMwLVx1MkRDNlx1MkRDOC1cdTJEQ0VcdTJERDAtXHUyREQ2XHUyREQ4LVx1MkRERVx1MkRFMC1cdTJERkZcdTJFMkZcdTMwMDUtXHUzMDA3XHUzMDIxLVx1MzAyRlx1MzAzMS1cdTMwMzVcdTMwMzgtXHUzMDNDXHUzMDQxLVx1MzA5Nlx1MzA5OVx1MzA5QVx1MzA5RC1cdTMwOUZcdTMwQTEtXHUzMEZBXHUzMEZDLVx1MzBGRlx1MzEwNS1cdTMxMkVcdTMxMzEtXHUzMThFXHUzMUEwLVx1MzFCQVx1MzFGMC1cdTMxRkZcdTM0MDAtXHU0REI1XHU0RTAwLVx1OUZFQVx1QTAwMC1cdUE0OENcdUE0RDAtXHVBNEZEXHVBNTAwLVx1QTYwQ1x1QTYxMC1cdUE2MkJcdUE2NDAtXHVBNjZGXHVBNjc0LVx1QTY3RFx1QTY3Ri1cdUE2RjFcdUE3MTctXHVBNzFGXHVBNzIyLVx1QTc4OFx1QTc4Qi1cdUE3QUVcdUE3QjAtXHVBN0I3XHVBN0Y3LVx1QTgyN1x1QTg0MC1cdUE4NzNcdUE4ODAtXHVBOEM1XHVBOEQwLVx1QThEOVx1QThFMC1cdUE4RjdcdUE4RkJcdUE4RkRcdUE5MDAtXHVBOTJEXHVBOTMwLVx1QTk1M1x1QTk2MC1cdUE5N0NcdUE5ODAtXHVBOUMwXHVBOUNGLVx1QTlEOVx1QTlFMC1cdUE5RkVcdUFBMDAtXHVBQTM2XHVBQTQwLVx1QUE0RFx1QUE1MC1cdUFBNTlcdUFBNjAtXHVBQTc2XHVBQTdBLVx1QUFDMlx1QUFEQi1cdUFBRERcdUFBRTAtXHVBQUVGXHVBQUYyLVx1QUFGNlx1QUIwMS1cdUFCMDZcdUFCMDktXHVBQjBFXHVBQjExLVx1QUIxNlx1QUIyMC1cdUFCMjZcdUFCMjgtXHVBQjJFXHVBQjMwLVx1QUI1QVx1QUI1Qy1cdUFCNjVcdUFCNzAtXHVBQkVBXHVBQkVDXHVBQkVEXHVBQkYwLVx1QUJGOVx1QUMwMC1cdUQ3QTNcdUQ3QjAtXHVEN0M2XHVEN0NCLVx1RDdGQlx1RjkwMC1cdUZBNkRcdUZBNzAtXHVGQUQ5XHVGQjAwLVx1RkIwNlx1RkIxMy1cdUZCMTdcdUZCMUQtXHVGQjI4XHVGQjJBLVx1RkIzNlx1RkIzOC1cdUZCM0NcdUZCM0VcdUZCNDBcdUZCNDFcdUZCNDNcdUZCNDRcdUZCNDYtXHVGQkIxXHVGQkQzLVx1RkQzRFx1RkQ1MC1cdUZEOEZcdUZEOTItXHVGREM3XHVGREYwLVx1RkRGQlx1RkUwMC1cdUZFMEZcdUZFMjAtXHVGRTJGXHVGRTMzXHVGRTM0XHVGRTRELVx1RkU0Rlx1RkU3MC1cdUZFNzRcdUZFNzYtXHVGRUZDXHVGRjEwLVx1RkYxOVx1RkYyMS1cdUZGM0FcdUZGM0ZcdUZGNDEtXHVGRjVBXHVGRjY2LVx1RkZCRVx1RkZDMi1cdUZGQzdcdUZGQ0EtXHVGRkNGXHVGRkQyLVx1RkZEN1x1RkZEQS1cdUZGRENdfFx1RDgwMFtcdURDMDAtXHVEQzBCXHVEQzBELVx1REMyNlx1REMyOC1cdURDM0FcdURDM0NcdURDM0RcdURDM0YtXHVEQzREXHVEQzUwLVx1REM1RFx1REM4MC1cdURDRkFcdURENDAtXHVERDc0XHVEREZEXHVERTgwLVx1REU5Q1x1REVBMC1cdURFRDBcdURFRTBcdURGMDAtXHVERjFGXHVERjJELVx1REY0QVx1REY1MC1cdURGN0FcdURGODAtXHVERjlEXHVERkEwLVx1REZDM1x1REZDOC1cdURGQ0ZcdURGRDEtXHVERkQ1XXxcdUQ4MDFbXHVEQzAwLVx1REM5RFx1RENBMC1cdURDQTlcdURDQjAtXHVEQ0QzXHVEQ0Q4LVx1RENGQlx1REQwMC1cdUREMjdcdUREMzAtXHVERDYzXHVERTAwLVx1REYzNlx1REY0MC1cdURGNTVcdURGNjAtXHVERjY3XXxcdUQ4MDJbXHVEQzAwLVx1REMwNVx1REMwOFx1REMwQS1cdURDMzVcdURDMzdcdURDMzhcdURDM0NcdURDM0YtXHVEQzU1XHVEQzYwLVx1REM3Nlx1REM4MC1cdURDOUVcdURDRTAtXHVEQ0YyXHVEQ0Y0XHVEQ0Y1XHVERDAwLVx1REQxNVx1REQyMC1cdUREMzlcdUREODAtXHVEREI3XHVEREJFXHVEREJGXHVERTAwLVx1REUwM1x1REUwNVx1REUwNlx1REUwQy1cdURFMTNcdURFMTUtXHVERTE3XHVERTE5LVx1REUzM1x1REUzOC1cdURFM0FcdURFM0ZcdURFNjAtXHVERTdDXHVERTgwLVx1REU5Q1x1REVDMC1cdURFQzdcdURFQzktXHVERUU2XHVERjAwLVx1REYzNVx1REY0MC1cdURGNTVcdURGNjAtXHVERjcyXHVERjgwLVx1REY5MV18XHVEODAzW1x1REMwMC1cdURDNDhcdURDODAtXHVEQ0IyXHVEQ0MwLVx1RENGMl18XHVEODA0W1x1REMwMC1cdURDNDZcdURDNjYtXHVEQzZGXHVEQzdGLVx1RENCQVx1RENEMC1cdURDRThcdURDRjAtXHVEQ0Y5XHVERDAwLVx1REQzNFx1REQzNi1cdUREM0ZcdURENTAtXHVERDczXHVERDc2XHVERDgwLVx1RERDNFx1RERDQS1cdUREQ0NcdURERDAtXHVERERBXHVERERDXHVERTAwLVx1REUxMVx1REUxMy1cdURFMzdcdURFM0VcdURFODAtXHVERTg2XHVERTg4XHVERThBLVx1REU4RFx1REU4Ri1cdURFOURcdURFOUYtXHVERUE4XHVERUIwLVx1REVFQVx1REVGMC1cdURFRjlcdURGMDAtXHVERjAzXHVERjA1LVx1REYwQ1x1REYwRlx1REYxMFx1REYxMy1cdURGMjhcdURGMkEtXHVERjMwXHVERjMyXHVERjMzXHVERjM1LVx1REYzOVx1REYzQy1cdURGNDRcdURGNDdcdURGNDhcdURGNEItXHVERjREXHVERjUwXHVERjU3XHVERjVELVx1REY2M1x1REY2Ni1cdURGNkNcdURGNzAtXHVERjc0XXxcdUQ4MDVbXHVEQzAwLVx1REM0QVx1REM1MC1cdURDNTlcdURDODAtXHVEQ0M1XHVEQ0M3XHVEQ0QwLVx1RENEOVx1REQ4MC1cdUREQjVcdUREQjgtXHVEREMwXHVEREQ4LVx1RERERFx1REUwMC1cdURFNDBcdURFNDRcdURFNTAtXHVERTU5XHVERTgwLVx1REVCN1x1REVDMC1cdURFQzlcdURGMDAtXHVERjE5XHVERjFELVx1REYyQlx1REYzMC1cdURGMzldfFx1RDgwNltcdURDQTAtXHVEQ0U5XHVEQ0ZGXHVERTAwLVx1REUzRVx1REU0N1x1REU1MC1cdURFODNcdURFODYtXHVERTk5XHVERUMwLVx1REVGOF18XHVEODA3W1x1REMwMC1cdURDMDhcdURDMEEtXHVEQzM2XHVEQzM4LVx1REM0MFx1REM1MC1cdURDNTlcdURDNzItXHVEQzhGXHVEQzkyLVx1RENBN1x1RENBOS1cdURDQjZcdUREMDAtXHVERDA2XHVERDA4XHVERDA5XHVERDBCLVx1REQzNlx1REQzQVx1REQzQ1x1REQzRFx1REQzRi1cdURENDdcdURENTAtXHVERDU5XXxcdUQ4MDhbXHVEQzAwLVx1REY5OV18XHVEODA5W1x1REMwMC1cdURDNkVcdURDODAtXHVERDQzXXxbXHVEODBDXHVEODFDLVx1RDgyMFx1RDg0MC1cdUQ4NjhcdUQ4NkEtXHVEODZDXHVEODZGLVx1RDg3Mlx1RDg3NC1cdUQ4NzldW1x1REMwMC1cdURGRkZdfFx1RDgwRFtcdURDMDAtXHVEQzJFXXxcdUQ4MTFbXHVEQzAwLVx1REU0Nl18XHVEODFBW1x1REMwMC1cdURFMzhcdURFNDAtXHVERTVFXHVERTYwLVx1REU2OVx1REVEMC1cdURFRURcdURFRjAtXHVERUY0XHVERjAwLVx1REYzNlx1REY0MC1cdURGNDNcdURGNTAtXHVERjU5XHVERjYzLVx1REY3N1x1REY3RC1cdURGOEZdfFx1RDgxQltcdURGMDAtXHVERjQ0XHVERjUwLVx1REY3RVx1REY4Ri1cdURGOUZcdURGRTBcdURGRTFdfFx1RDgyMVtcdURDMDAtXHVERkVDXXxcdUQ4MjJbXHVEQzAwLVx1REVGMl18XHVEODJDW1x1REMwMC1cdUREMUVcdURENzAtXHVERUZCXXxcdUQ4MkZbXHVEQzAwLVx1REM2QVx1REM3MC1cdURDN0NcdURDODAtXHVEQzg4XHVEQzkwLVx1REM5OVx1REM5RFx1REM5RV18XHVEODM0W1x1REQ2NS1cdURENjlcdURENkQtXHVERDcyXHVERDdCLVx1REQ4Mlx1REQ4NS1cdUREOEJcdUREQUEtXHVEREFEXHVERTQyLVx1REU0NF18XHVEODM1W1x1REMwMC1cdURDNTRcdURDNTYtXHVEQzlDXHVEQzlFXHVEQzlGXHVEQ0EyXHVEQ0E1XHVEQ0E2XHVEQ0E5LVx1RENBQ1x1RENBRS1cdURDQjlcdURDQkJcdURDQkQtXHVEQ0MzXHVEQ0M1LVx1REQwNVx1REQwNy1cdUREMEFcdUREMEQtXHVERDE0XHVERDE2LVx1REQxQ1x1REQxRS1cdUREMzlcdUREM0ItXHVERDNFXHVERDQwLVx1REQ0NFx1REQ0Nlx1REQ0QS1cdURENTBcdURENTItXHVERUE1XHVERUE4LVx1REVDMFx1REVDMi1cdURFREFcdURFREMtXHVERUZBXHVERUZDLVx1REYxNFx1REYxNi1cdURGMzRcdURGMzYtXHVERjRFXHVERjUwLVx1REY2RVx1REY3MC1cdURGODhcdURGOEEtXHVERkE4XHVERkFBLVx1REZDMlx1REZDNC1cdURGQ0JcdURGQ0UtXHVERkZGXXxcdUQ4MzZbXHVERTAwLVx1REUzNlx1REUzQi1cdURFNkNcdURFNzVcdURFODRcdURFOUItXHVERTlGXHVERUExLVx1REVBRl18XHVEODM4W1x1REMwMC1cdURDMDZcdURDMDgtXHVEQzE4XHVEQzFCLVx1REMyMVx1REMyM1x1REMyNFx1REMyNi1cdURDMkFdfFx1RDgzQVtcdURDMDAtXHVEQ0M0XHVEQ0QwLVx1RENENlx1REQwMC1cdURENEFcdURENTAtXHVERDU5XXxcdUQ4M0JbXHVERTAwLVx1REUwM1x1REUwNS1cdURFMUZcdURFMjFcdURFMjJcdURFMjRcdURFMjdcdURFMjktXHVERTMyXHVERTM0LVx1REUzN1x1REUzOVx1REUzQlx1REU0Mlx1REU0N1x1REU0OVx1REU0Qlx1REU0RC1cdURFNEZcdURFNTFcdURFNTJcdURFNTRcdURFNTdcdURFNTlcdURFNUJcdURFNURcdURFNUZcdURFNjFcdURFNjJcdURFNjRcdURFNjctXHVERTZBXHVERTZDLVx1REU3Mlx1REU3NC1cdURFNzdcdURFNzktXHVERTdDXHVERTdFXHVERTgwLVx1REU4OVx1REU4Qi1cdURFOUJcdURFQTEtXHVERUEzXHVERUE1LVx1REVBOVx1REVBQi1cdURFQkJdfFx1RDg2OVtcdURDMDAtXHVERUQ2XHVERjAwLVx1REZGRl18XHVEODZEW1x1REMwMC1cdURGMzRcdURGNDAtXHVERkZGXXxcdUQ4NkVbXHVEQzAwLVx1REMxRFx1REMyMC1cdURGRkZdfFx1RDg3M1tcdURDMDAtXHVERUExXHVERUIwLVx1REZGRl18XHVEODdBW1x1REMwMC1cdURGRTBdfFx1RDg3RVtcdURDMDAtXHVERTFEXXxcdURCNDBbXHVERDAwLVx1RERFRl0vfSxVPXtpc1NwYWNlU2VwYXJhdG9yOmZ1bmN0aW9uKHUpe3JldHVybiJzdHJpbmciPT10eXBlb2YgdSYmRy5TcGFjZV9TZXBhcmF0b3IudGVzdCh1KX0saXNJZFN0YXJ0Q2hhcjpmdW5jdGlvbih1KXtyZXR1cm4ic3RyaW5nIj09dHlwZW9mIHUmJih1Pj0iYSImJnU8PSJ6Inx8dT49IkEiJiZ1PD0iWiJ8fCIkIj09PXV8fCJfIj09PXV8fEcuSURfU3RhcnQudGVzdCh1KSl9LGlzSWRDb250aW51ZUNoYXI6ZnVuY3Rpb24odSl7cmV0dXJuInN0cmluZyI9PXR5cGVvZiB1JiYodT49ImEiJiZ1PD0ieiJ8fHU+PSJBIiYmdTw9IloifHx1Pj0iMCImJnU8PSI5Inx8IiQiPT09dXx8Il8iPT09dXx8IuKAjCI9PT11fHwi4oCNIj09PXV8fEcuSURfQ29udGludWUudGVzdCh1KSl9LGlzRGlnaXQ6ZnVuY3Rpb24odSl7cmV0dXJuInN0cmluZyI9PXR5cGVvZiB1JiYvWzAtOV0vLnRlc3QodSl9LGlzSGV4RGlnaXQ6ZnVuY3Rpb24odSl7cmV0dXJuInN0cmluZyI9PXR5cGVvZiB1JiYvWzAtOUEtRmEtZl0vLnRlc3QodSl9fTtmdW5jdGlvbiBaKCl7Zm9yKFQ9ImRlZmF1bHQiLHo9IiIsSD0hMSwkPTE7Oyl7Uj1xKCk7dmFyIHU9WFtUXSgpO2lmKHUpcmV0dXJuIHV9fWZ1bmN0aW9uIHEoKXtpZihfW0ldKXJldHVybiBTdHJpbmcuZnJvbUNvZGVQb2ludChfLmNvZGVQb2ludEF0KEkpKX1mdW5jdGlvbiBXKCl7dmFyIHU9cSgpO3JldHVybiJcbiI9PT11PyhWKyssSj0wKTp1P0orPXUubGVuZ3RoOkorKyx1JiYoSSs9dS5sZW5ndGgpLHV9dmFyIFg9e2RlZmF1bHQ6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSJcdCI6Y2FzZSJcdiI6Y2FzZSJcZiI6Y2FzZSIgIjpjYXNlIiAiOmNhc2UiXHVmZWZmIjpjYXNlIlxuIjpjYXNlIlxyIjpjYXNlIlx1MjAyOCI6Y2FzZSJcdTIwMjkiOnJldHVybiB2b2lkIFcoKTtjYXNlIi8iOnJldHVybiBXKCksdm9pZChUPSJjb21tZW50Iik7Y2FzZSB2b2lkIDA6cmV0dXJuIFcoKSxLKCJlb2YiKX1pZighVS5pc1NwYWNlU2VwYXJhdG9yKFIpKXJldHVybiBYW09dKCk7VygpfSxjb21tZW50OmZ1bmN0aW9uKCl7c3dpdGNoKFIpe2Nhc2UiKiI6cmV0dXJuIFcoKSx2b2lkKFQ9Im11bHRpTGluZUNvbW1lbnQiKTtjYXNlIi8iOnJldHVybiBXKCksdm9pZChUPSJzaW5nbGVMaW5lQ29tbWVudCIpfXRocm93IHJ1KFcoKSl9LG11bHRpTGluZUNvbW1lbnQ6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIqIjpyZXR1cm4gVygpLHZvaWQoVD0ibXVsdGlMaW5lQ29tbWVudEFzdGVyaXNrIik7Y2FzZSB2b2lkIDA6dGhyb3cgcnUoVygpKX1XKCl9LG11bHRpTGluZUNvbW1lbnRBc3RlcmlzazpmdW5jdGlvbigpe3N3aXRjaChSKXtjYXNlIioiOnJldHVybiB2b2lkIFcoKTtjYXNlIi8iOnJldHVybiBXKCksdm9pZChUPSJkZWZhdWx0Iik7Y2FzZSB2b2lkIDA6dGhyb3cgcnUoVygpKX1XKCksVD0ibXVsdGlMaW5lQ29tbWVudCJ9LHNpbmdsZUxpbmVDb21tZW50OmZ1bmN0aW9uKCl7c3dpdGNoKFIpe2Nhc2UiXG4iOmNhc2UiXHIiOmNhc2UiXHUyMDI4IjpjYXNlIlx1MjAyOSI6cmV0dXJuIFcoKSx2b2lkKFQ9ImRlZmF1bHQiKTtjYXNlIHZvaWQgMDpyZXR1cm4gVygpLEsoImVvZiIpfVcoKX0sdmFsdWU6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSJ7IjpjYXNlIlsiOnJldHVybiBLKCJwdW5jdHVhdG9yIixXKCkpO2Nhc2UibiI6cmV0dXJuIFcoKSxRKCJ1bGwiKSxLKCJudWxsIixudWxsKTtjYXNlInQiOnJldHVybiBXKCksUSgicnVlIiksSygiYm9vbGVhbiIsITApO2Nhc2UiZiI6cmV0dXJuIFcoKSxRKCJhbHNlIiksSygiYm9vbGVhbiIsITEpO2Nhc2UiLSI6Y2FzZSIrIjpyZXR1cm4iLSI9PT1XKCkmJigkPS0xKSx2b2lkKFQ9InNpZ24iKTtjYXNlIi4iOnJldHVybiB6PVcoKSx2b2lkKFQ9ImRlY2ltYWxQb2ludExlYWRpbmciKTtjYXNlIjAiOnJldHVybiB6PVcoKSx2b2lkKFQ9Inplcm8iKTtjYXNlIjEiOmNhc2UiMiI6Y2FzZSIzIjpjYXNlIjQiOmNhc2UiNSI6Y2FzZSI2IjpjYXNlIjciOmNhc2UiOCI6Y2FzZSI5IjpyZXR1cm4gej1XKCksdm9pZChUPSJkZWNpbWFsSW50ZWdlciIpO2Nhc2UiSSI6cmV0dXJuIFcoKSxRKCJuZmluaXR5IiksSygibnVtZXJpYyIsMS8wKTtjYXNlIk4iOnJldHVybiBXKCksUSgiYU4iKSxLKCJudW1lcmljIixOYU4pO2Nhc2UnIic6Y2FzZSInIjpyZXR1cm4gSD0nIic9PT1XKCksej0iIix2b2lkKFQ9InN0cmluZyIpfXRocm93IHJ1KFcoKSl9LGlkZW50aWZpZXJOYW1lU3RhcnRFc2NhcGU6ZnVuY3Rpb24oKXtpZigidSIhPT1SKXRocm93IHJ1KFcoKSk7VygpO3ZhciB1PVkoKTtzd2l0Y2godSl7Y2FzZSIkIjpjYXNlIl8iOmJyZWFrO2RlZmF1bHQ6aWYoIVUuaXNJZFN0YXJ0Q2hhcih1KSl0aHJvdyBudSgpfXorPXUsVD0iaWRlbnRpZmllck5hbWUifSxpZGVudGlmaWVyTmFtZTpmdW5jdGlvbigpe3N3aXRjaChSKXtjYXNlIiQiOmNhc2UiXyI6Y2FzZSLigIwiOmNhc2Ui4oCNIjpyZXR1cm4gdm9pZCh6Kz1XKCkpO2Nhc2UiXFwiOnJldHVybiBXKCksdm9pZChUPSJpZGVudGlmaWVyTmFtZUVzY2FwZSIpfWlmKCFVLmlzSWRDb250aW51ZUNoYXIoUikpcmV0dXJuIEsoImlkZW50aWZpZXIiLHopO3orPVcoKX0saWRlbnRpZmllck5hbWVFc2NhcGU6ZnVuY3Rpb24oKXtpZigidSIhPT1SKXRocm93IHJ1KFcoKSk7VygpO3ZhciB1PVkoKTtzd2l0Y2godSl7Y2FzZSIkIjpjYXNlIl8iOmNhc2Ui4oCMIjpjYXNlIuKAjSI6YnJlYWs7ZGVmYXVsdDppZighVS5pc0lkQ29udGludWVDaGFyKHUpKXRocm93IG51KCl9eis9dSxUPSJpZGVudGlmaWVyTmFtZSJ9LHNpZ246ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIuIjpyZXR1cm4gej1XKCksdm9pZChUPSJkZWNpbWFsUG9pbnRMZWFkaW5nIik7Y2FzZSIwIjpyZXR1cm4gej1XKCksdm9pZChUPSJ6ZXJvIik7Y2FzZSIxIjpjYXNlIjIiOmNhc2UiMyI6Y2FzZSI0IjpjYXNlIjUiOmNhc2UiNiI6Y2FzZSI3IjpjYXNlIjgiOmNhc2UiOSI6cmV0dXJuIHo9VygpLHZvaWQoVD0iZGVjaW1hbEludGVnZXIiKTtjYXNlIkkiOnJldHVybiBXKCksUSgibmZpbml0eSIpLEsoIm51bWVyaWMiLCQqKDEvMCkpO2Nhc2UiTiI6cmV0dXJuIFcoKSxRKCJhTiIpLEsoIm51bWVyaWMiLE5hTil9dGhyb3cgcnUoVygpKX0semVybzpmdW5jdGlvbigpe3N3aXRjaChSKXtjYXNlIi4iOnJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsUG9pbnQiKTtjYXNlImUiOmNhc2UiRSI6cmV0dXJuIHorPVcoKSx2b2lkKFQ9ImRlY2ltYWxFeHBvbmVudCIpO2Nhc2UieCI6Y2FzZSJYIjpyZXR1cm4geis9VygpLHZvaWQoVD0iaGV4YWRlY2ltYWwiKX1yZXR1cm4gSygibnVtZXJpYyIsMCokKX0sZGVjaW1hbEludGVnZXI6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIuIjpyZXR1cm4geis9VygpLHZvaWQoVD0iZGVjaW1hbFBvaW50Iik7Y2FzZSJlIjpjYXNlIkUiOnJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRXhwb25lbnQiKX1pZighVS5pc0RpZ2l0KFIpKXJldHVybiBLKCJudW1lcmljIiwkKk51bWJlcih6KSk7eis9VygpfSxkZWNpbWFsUG9pbnRMZWFkaW5nOmZ1bmN0aW9uKCl7aWYoVS5pc0RpZ2l0KFIpKXJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRnJhY3Rpb24iKTt0aHJvdyBydShXKCkpfSxkZWNpbWFsUG9pbnQ6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSJlIjpjYXNlIkUiOnJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRXhwb25lbnQiKX1yZXR1cm4gVS5pc0RpZ2l0KFIpPyh6Kz1XKCksdm9pZChUPSJkZWNpbWFsRnJhY3Rpb24iKSk6SygibnVtZXJpYyIsJCpOdW1iZXIoeikpfSxkZWNpbWFsRnJhY3Rpb246ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSJlIjpjYXNlIkUiOnJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRXhwb25lbnQiKX1pZighVS5pc0RpZ2l0KFIpKXJldHVybiBLKCJudW1lcmljIiwkKk51bWJlcih6KSk7eis9VygpfSxkZWNpbWFsRXhwb25lbnQ6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIrIjpjYXNlIi0iOnJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRXhwb25lbnRTaWduIil9aWYoVS5pc0RpZ2l0KFIpKXJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRXhwb25lbnRJbnRlZ2VyIik7dGhyb3cgcnUoVygpKX0sZGVjaW1hbEV4cG9uZW50U2lnbjpmdW5jdGlvbigpe2lmKFUuaXNEaWdpdChSKSlyZXR1cm4geis9VygpLHZvaWQoVD0iZGVjaW1hbEV4cG9uZW50SW50ZWdlciIpO3Rocm93IHJ1KFcoKSl9LGRlY2ltYWxFeHBvbmVudEludGVnZXI6ZnVuY3Rpb24oKXtpZighVS5pc0RpZ2l0KFIpKXJldHVybiBLKCJudW1lcmljIiwkKk51bWJlcih6KSk7eis9VygpfSxoZXhhZGVjaW1hbDpmdW5jdGlvbigpe2lmKFUuaXNIZXhEaWdpdChSKSlyZXR1cm4geis9VygpLHZvaWQoVD0iaGV4YWRlY2ltYWxJbnRlZ2VyIik7dGhyb3cgcnUoVygpKX0saGV4YWRlY2ltYWxJbnRlZ2VyOmZ1bmN0aW9uKCl7aWYoIVUuaXNIZXhEaWdpdChSKSlyZXR1cm4gSygibnVtZXJpYyIsJCpOdW1iZXIoeikpO3orPVcoKX0sc3RyaW5nOmZ1bmN0aW9uKCl7c3dpdGNoKFIpe2Nhc2UiXFwiOnJldHVybiBXKCksdm9pZCh6Kz1mdW5jdGlvbigpe3N3aXRjaChxKCkpe2Nhc2UiYiI6cmV0dXJuIFcoKSwiXGIiO2Nhc2UiZiI6cmV0dXJuIFcoKSwiXGYiO2Nhc2UibiI6cmV0dXJuIFcoKSwiXG4iO2Nhc2UiciI6cmV0dXJuIFcoKSwiXHIiO2Nhc2UidCI6cmV0dXJuIFcoKSwiXHQiO2Nhc2UidiI6cmV0dXJuIFcoKSwiXHYiO2Nhc2UiMCI6aWYoVygpLFUuaXNEaWdpdChxKCkpKXRocm93IHJ1KFcoKSk7cmV0dXJuIlwwIjtjYXNlIngiOnJldHVybiBXKCksZnVuY3Rpb24oKXt2YXIgdT0iIixEPXEoKTtpZighVS5pc0hleERpZ2l0KEQpKXRocm93IHJ1KFcoKSk7aWYodSs9VygpLEQ9cSgpLCFVLmlzSGV4RGlnaXQoRCkpdGhyb3cgcnUoVygpKTtyZXR1cm4gdSs9VygpLFN0cmluZy5mcm9tQ29kZVBvaW50KHBhcnNlSW50KHUsMTYpKX0oKTtjYXNlInUiOnJldHVybiBXKCksWSgpO2Nhc2UiXG4iOmNhc2UiXHUyMDI4IjpjYXNlIlx1MjAyOSI6cmV0dXJuIFcoKSwiIjtjYXNlIlxyIjpyZXR1cm4gVygpLCJcbiI9PT1xKCkmJlcoKSwiIjtjYXNlIjEiOmNhc2UiMiI6Y2FzZSIzIjpjYXNlIjQiOmNhc2UiNSI6Y2FzZSI2IjpjYXNlIjciOmNhc2UiOCI6Y2FzZSI5IjpjYXNlIHZvaWQgMDp0aHJvdyBydShXKCkpfXJldHVybiBXKCl9KCkpO2Nhc2UnIic6cmV0dXJuIEg/KFcoKSxLKCJzdHJpbmciLHopKTp2b2lkKHorPVcoKSk7Y2FzZSInIjpyZXR1cm4gSD92b2lkKHorPVcoKSk6KFcoKSxLKCJzdHJpbmciLHopKTtjYXNlIlxuIjpjYXNlIlxyIjp0aHJvdyBydShXKCkpO2Nhc2UiXHUyMDI4IjpjYXNlIlx1MjAyOSI6IWZ1bmN0aW9uKHUpe2NvbnNvbGUud2FybigiSlNPTjU6ICciK0Z1KHUpKyInIGluIHN0cmluZ3MgaXMgbm90IHZhbGlkIEVDTUFTY3JpcHQ7IGNvbnNpZGVyIGVzY2FwaW5nIil9KFIpO2JyZWFrO2Nhc2Ugdm9pZCAwOnRocm93IHJ1KFcoKSl9eis9VygpfSxzdGFydDpmdW5jdGlvbigpe3N3aXRjaChSKXtjYXNlInsiOmNhc2UiWyI6cmV0dXJuIEsoInB1bmN0dWF0b3IiLFcoKSl9VD0idmFsdWUifSxiZWZvcmVQcm9wZXJ0eU5hbWU6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIkIjpjYXNlIl8iOnJldHVybiB6PVcoKSx2b2lkKFQ9ImlkZW50aWZpZXJOYW1lIik7Y2FzZSJcXCI6cmV0dXJuIFcoKSx2b2lkKFQ9ImlkZW50aWZpZXJOYW1lU3RhcnRFc2NhcGUiKTtjYXNlIn0iOnJldHVybiBLKCJwdW5jdHVhdG9yIixXKCkpO2Nhc2UnIic6Y2FzZSInIjpyZXR1cm4gSD0nIic9PT1XKCksdm9pZChUPSJzdHJpbmciKX1pZihVLmlzSWRTdGFydENoYXIoUikpcmV0dXJuIHorPVcoKSx2b2lkKFQ9ImlkZW50aWZpZXJOYW1lIik7dGhyb3cgcnUoVygpKX0sYWZ0ZXJQcm9wZXJ0eU5hbWU6ZnVuY3Rpb24oKXtpZigiOiI9PT1SKXJldHVybiBLKCJwdW5jdHVhdG9yIixXKCkpO3Rocm93IHJ1KFcoKSl9LGJlZm9yZVByb3BlcnR5VmFsdWU6ZnVuY3Rpb24oKXtUPSJ2YWx1ZSJ9LGFmdGVyUHJvcGVydHlWYWx1ZTpmdW5jdGlvbigpe3N3aXRjaChSKXtjYXNlIiwiOmNhc2UifSI6cmV0dXJuIEsoInB1bmN0dWF0b3IiLFcoKSl9dGhyb3cgcnUoVygpKX0sYmVmb3JlQXJyYXlWYWx1ZTpmdW5jdGlvbigpe2lmKCJdIj09PVIpcmV0dXJuIEsoInB1bmN0dWF0b3IiLFcoKSk7VD0idmFsdWUifSxhZnRlckFycmF5VmFsdWU6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIsIjpjYXNlIl0iOnJldHVybiBLKCJwdW5jdHVhdG9yIixXKCkpfXRocm93IHJ1KFcoKSl9LGVuZDpmdW5jdGlvbigpe3Rocm93IHJ1KFcoKSl9fTtmdW5jdGlvbiBLKHUsRCl7cmV0dXJue3R5cGU6dSx2YWx1ZTpELGxpbmU6Vixjb2x1bW46Sn19ZnVuY3Rpb24gUSh1KXtmb3IodmFyIEQ9MCxlPXU7RDxlLmxlbmd0aDtEKz0xKXt2YXIgcj1lW0RdO2lmKHEoKSE9PXIpdGhyb3cgcnUoVygpKTtXKCl9fWZ1bmN0aW9uIFkoKXtmb3IodmFyIHU9IiIsRD00O0QtLSA+MDspe3ZhciBlPXEoKTtpZighVS5pc0hleERpZ2l0KGUpKXRocm93IHJ1KFcoKSk7dSs9VygpfXJldHVybiBTdHJpbmcuZnJvbUNvZGVQb2ludChwYXJzZUludCh1LDE2KSl9dmFyIHV1PXtzdGFydDpmdW5jdGlvbigpe2lmKCJlb2YiPT09TS50eXBlKXRocm93IHR1KCk7RHUoKX0sYmVmb3JlUHJvcGVydHlOYW1lOmZ1bmN0aW9uKCl7c3dpdGNoKE0udHlwZSl7Y2FzZSJpZGVudGlmaWVyIjpjYXNlInN0cmluZyI6cmV0dXJuIGs9TS52YWx1ZSx2b2lkKE89ImFmdGVyUHJvcGVydHlOYW1lIik7Y2FzZSJwdW5jdHVhdG9yIjpyZXR1cm4gdm9pZCBldSgpO2Nhc2UiZW9mIjp0aHJvdyB0dSgpfX0sYWZ0ZXJQcm9wZXJ0eU5hbWU6ZnVuY3Rpb24oKXtpZigiZW9mIj09PU0udHlwZSl0aHJvdyB0dSgpO089ImJlZm9yZVByb3BlcnR5VmFsdWUifSxiZWZvcmVQcm9wZXJ0eVZhbHVlOmZ1bmN0aW9uKCl7aWYoImVvZiI9PT1NLnR5cGUpdGhyb3cgdHUoKTtEdSgpfSxiZWZvcmVBcnJheVZhbHVlOmZ1bmN0aW9uKCl7aWYoImVvZiI9PT1NLnR5cGUpdGhyb3cgdHUoKTsicHVuY3R1YXRvciIhPT1NLnR5cGV8fCJdIiE9PU0udmFsdWU/RHUoKTpldSgpfSxhZnRlclByb3BlcnR5VmFsdWU6ZnVuY3Rpb24oKXtpZigiZW9mIj09PU0udHlwZSl0aHJvdyB0dSgpO3N3aXRjaChNLnZhbHVlKXtjYXNlIiwiOnJldHVybiB2b2lkKE89ImJlZm9yZVByb3BlcnR5TmFtZSIpO2Nhc2UifSI6ZXUoKX19LGFmdGVyQXJyYXlWYWx1ZTpmdW5jdGlvbigpe2lmKCJlb2YiPT09TS50eXBlKXRocm93IHR1KCk7c3dpdGNoKE0udmFsdWUpe2Nhc2UiLCI6cmV0dXJuIHZvaWQoTz0iYmVmb3JlQXJyYXlWYWx1ZSIpO2Nhc2UiXSI6ZXUoKX19LGVuZDpmdW5jdGlvbigpe319O2Z1bmN0aW9uIER1KCl7dmFyIHU7c3dpdGNoKE0udHlwZSl7Y2FzZSJwdW5jdHVhdG9yIjpzd2l0Y2goTS52YWx1ZSl7Y2FzZSJ7Ijp1PXt9O2JyZWFrO2Nhc2UiWyI6dT1bXX1icmVhaztjYXNlIm51bGwiOmNhc2UiYm9vbGVhbiI6Y2FzZSJudW1lcmljIjpjYXNlInN0cmluZyI6dT1NLnZhbHVlfWlmKHZvaWQgMD09PUwpTD11O2Vsc2V7dmFyIEQ9altqLmxlbmd0aC0xXTtBcnJheS5pc0FycmF5KEQpP0QucHVzaCh1KTpPYmplY3QuZGVmaW5lUHJvcGVydHkoRCxrLHt2YWx1ZTp1LHdyaXRhYmxlOiEwLGVudW1lcmFibGU6ITAsY29uZmlndXJhYmxlOiEwfSl9aWYobnVsbCE9PXUmJiJvYmplY3QiPT10eXBlb2YgdSlqLnB1c2godSksTz1BcnJheS5pc0FycmF5KHUpPyJiZWZvcmVBcnJheVZhbHVlIjoiYmVmb3JlUHJvcGVydHlOYW1lIjtlbHNle3ZhciBlPWpbai5sZW5ndGgtMV07Tz1udWxsPT1lPyJlbmQiOkFycmF5LmlzQXJyYXkoZSk/ImFmdGVyQXJyYXlWYWx1ZSI6ImFmdGVyUHJvcGVydHlWYWx1ZSJ9fWZ1bmN0aW9uIGV1KCl7ai5wb3AoKTt2YXIgdT1qW2oubGVuZ3RoLTFdO089bnVsbD09dT8iZW5kIjpBcnJheS5pc0FycmF5KHUpPyJhZnRlckFycmF5VmFsdWUiOiJhZnRlclByb3BlcnR5VmFsdWUifWZ1bmN0aW9uIHJ1KHUpe3JldHVybiBDdSh2b2lkIDA9PT11PyJKU09ONTogaW52YWxpZCBlbmQgb2YgaW5wdXQgYXQgIitWKyI6IitKOiJKU09ONTogaW52YWxpZCBjaGFyYWN0ZXIgJyIrRnUodSkrIicgYXQgIitWKyI6IitKKX1mdW5jdGlvbiB0dSgpe3JldHVybiBDdSgiSlNPTjU6IGludmFsaWQgZW5kIG9mIGlucHV0IGF0ICIrVisiOiIrSil9ZnVuY3Rpb24gbnUoKXtyZXR1cm4gQ3UoIkpTT041OiBpbnZhbGlkIGlkZW50aWZpZXIgY2hhcmFjdGVyIGF0ICIrVisiOiIrKEotPTUpKX1mdW5jdGlvbiBGdSh1KXt2YXIgRD17IiciOiJcXCciLCciJzonXFwiJywiXFwiOiJcXFxcIiwiXGIiOiJcXGIiLCJcZiI6IlxcZiIsIlxuIjoiXFxuIiwiXHIiOiJcXHIiLCJcdCI6IlxcdCIsIlx2IjoiXFx2IiwiXDAiOiJcXDAiLCJcdTIwMjgiOiJcXHUyMDI4IiwiXHUyMDI5IjoiXFx1MjAyOSJ9O2lmKERbdV0pcmV0dXJuIERbdV07aWYodTwiICIpe3ZhciBlPXUuY2hhckNvZGVBdCgwKS50b1N0cmluZygxNik7cmV0dXJuIlxceCIrKCIwMCIrZSkuc3Vic3RyaW5nKGUubGVuZ3RoKX1yZXR1cm4gdX1mdW5jdGlvbiBDdSh1KXt2YXIgRD1uZXcgU3ludGF4RXJyb3IodSk7cmV0dXJuIEQubGluZU51bWJlcj1WLEQuY29sdW1uTnVtYmVyPUosRH1yZXR1cm57cGFyc2U6ZnVuY3Rpb24odSxEKXtfPVN0cmluZyh1KSxPPSJzdGFydCIsaj1bXSxJPTAsVj0xLEo9MCxNPXZvaWQgMCxrPXZvaWQgMCxMPXZvaWQgMDtkb3tNPVooKSx1dVtPXSgpfXdoaWxlKCJlb2YiIT09TS50eXBlKTtyZXR1cm4iZnVuY3Rpb24iPT10eXBlb2YgRD9mdW5jdGlvbiB1KEQsZSxyKXt2YXIgdD1EW2VdO2lmKG51bGwhPXQmJiJvYmplY3QiPT10eXBlb2YgdClpZihBcnJheS5pc0FycmF5KHQpKWZvcih2YXIgbj0wO248dC5sZW5ndGg7bisrKXt2YXIgRj1TdHJpbmcobiksQz11KHQsRixyKTt2b2lkIDA9PT1DP2RlbGV0ZSB0W0ZdOk9iamVjdC5kZWZpbmVQcm9wZXJ0eSh0LEYse3ZhbHVlOkMsd3JpdGFibGU6ITAsZW51bWVyYWJsZTohMCxjb25maWd1cmFibGU6ITB9KX1lbHNlIGZvcih2YXIgQSBpbiB0KXt2YXIgaT11KHQsQSxyKTt2b2lkIDA9PT1pP2RlbGV0ZSB0W0FdOk9iamVjdC5kZWZpbmVQcm9wZXJ0eSh0LEEse3ZhbHVlOmksd3JpdGFibGU6ITAsZW51bWVyYWJsZTohMCxjb25maWd1cmFibGU6ITB9KX1yZXR1cm4gci5jYWxsKEQsZSx0KX0oeyIiOkx9LCIiLEQpOkx9LHN0cmluZ2lmeTpmdW5jdGlvbih1LEQsZSl7dmFyIHIsdCxuLEY9W10sQz0iIixBPSIiO2lmKG51bGw9PUR8fCJvYmplY3QiIT10eXBlb2YgRHx8QXJyYXkuaXNBcnJheShEKXx8KGU9RC5zcGFjZSxuPUQucXVvdGUsRD1ELnJlcGxhY2VyKSwiZnVuY3Rpb24iPT10eXBlb2YgRCl0PUQ7ZWxzZSBpZihBcnJheS5pc0FycmF5KEQpKXtyPVtdO2Zvcih2YXIgaT0wLEU9RDtpPEUubGVuZ3RoO2krPTEpe3ZhciBvPUVbaV0sYT12b2lkIDA7InN0cmluZyI9PXR5cGVvZiBvP2E9bzooIm51bWJlciI9PXR5cGVvZiBvfHxvIGluc3RhbmNlb2YgU3RyaW5nfHxvIGluc3RhbmNlb2YgTnVtYmVyKSYmKGE9U3RyaW5nKG8pKSx2b2lkIDAhPT1hJiZyLmluZGV4T2YoYSk8MCYmci5wdXNoKGEpfX1yZXR1cm4gZSBpbnN0YW5jZW9mIE51bWJlcj9lPU51bWJlcihlKTplIGluc3RhbmNlb2YgU3RyaW5nJiYoZT1TdHJpbmcoZSkpLCJudW1iZXIiPT10eXBlb2YgZT9lPjAmJihlPU1hdGgubWluKDEwLE1hdGguZmxvb3IoZSkpLEE9IiAgICAgICAgICAiLnN1YnN0cigwLGUpKToic3RyaW5nIj09dHlwZW9mIGUmJihBPWUuc3Vic3RyKDAsMTApKSxjKCIiLHsiIjp1fSk7ZnVuY3Rpb24gYyh1LEQpe3ZhciBlPURbdV07c3dpdGNoKG51bGwhPWUmJigiZnVuY3Rpb24iPT10eXBlb2YgZS50b0pTT041P2U9ZS50b0pTT041KHUpOiJmdW5jdGlvbiI9PXR5cGVvZiBlLnRvSlNPTiYmKGU9ZS50b0pTT04odSkpKSx0JiYoZT10LmNhbGwoRCx1LGUpKSxlIGluc3RhbmNlb2YgTnVtYmVyP2U9TnVtYmVyKGUpOmUgaW5zdGFuY2VvZiBTdHJpbmc/ZT1TdHJpbmcoZSk6ZSBpbnN0YW5jZW9mIEJvb2xlYW4mJihlPWUudmFsdWVPZigpKSxlKXtjYXNlIG51bGw6cmV0dXJuIm51bGwiO2Nhc2UhMDpyZXR1cm4idHJ1ZSI7Y2FzZSExOnJldHVybiJmYWxzZSJ9cmV0dXJuInN0cmluZyI9PXR5cGVvZiBlP0IoZSk6Im51bWJlciI9PXR5cGVvZiBlP1N0cmluZyhlKToib2JqZWN0Ij09dHlwZW9mIGU/QXJyYXkuaXNBcnJheShlKT9mdW5jdGlvbih1KXtpZihGLmluZGV4T2YodSk+PTApdGhyb3cgVHlwZUVycm9yKCJDb252ZXJ0aW5nIGNpcmN1bGFyIHN0cnVjdHVyZSB0byBKU09ONSIpO0YucHVzaCh1KTt2YXIgRD1DO0MrPUE7Zm9yKHZhciBlLHI9W10sdD0wO3Q8dS5sZW5ndGg7dCsrKXt2YXIgbj1jKFN0cmluZyh0KSx1KTtyLnB1c2godm9pZCAwIT09bj9uOiJudWxsIil9aWYoMD09PXIubGVuZ3RoKWU9IltdIjtlbHNlIGlmKCIiPT09QSl7dmFyIGk9ci5qb2luKCIsIik7ZT0iWyIraSsiXSJ9ZWxzZXt2YXIgRT0iLFxuIitDLG89ci5qb2luKEUpO2U9IltcbiIrQytvKyIsXG4iK0QrIl0ifXJldHVybiBGLnBvcCgpLEM9RCxlfShlKTpmdW5jdGlvbih1KXtpZihGLmluZGV4T2YodSk+PTApdGhyb3cgVHlwZUVycm9yKCJDb252ZXJ0aW5nIGNpcmN1bGFyIHN0cnVjdHVyZSB0byBKU09ONSIpO0YucHVzaCh1KTt2YXIgRD1DO0MrPUE7Zm9yKHZhciBlLHQsbj1yfHxPYmplY3Qua2V5cyh1KSxpPVtdLEU9MCxvPW47RTxvLmxlbmd0aDtFKz0xKXt2YXIgYT1vW0VdLEI9YyhhLHUpO2lmKHZvaWQgMCE9PUIpe3ZhciBmPXMoYSkrIjoiOyIiIT09QSYmKGYrPSIgIiksZis9QixpLnB1c2goZil9fWlmKDA9PT1pLmxlbmd0aCllPSJ7fSI7ZWxzZSBpZigiIj09PUEpdD1pLmpvaW4oIiwiKSxlPSJ7Iit0KyJ9IjtlbHNle3ZhciBsPSIsXG4iK0M7dD1pLmpvaW4obCksZT0ie1xuIitDK3QrIixcbiIrRCsifSJ9cmV0dXJuIEYucG9wKCksQz1ELGV9KGUpOnZvaWQgMH1mdW5jdGlvbiBCKHUpe2Zvcih2YXIgRD17IiciOi4xLCciJzouMn0sZT17IiciOiJcXCciLCciJzonXFwiJywiXFwiOiJcXFxcIiwiXGIiOiJcXGIiLCJcZiI6IlxcZiIsIlxuIjoiXFxuIiwiXHIiOiJcXHIiLCJcdCI6IlxcdCIsIlx2IjoiXFx2IiwiXDAiOiJcXDAiLCJcdTIwMjgiOiJcXHUyMDI4IiwiXHUyMDI5IjoiXFx1MjAyOSJ9LHI9IiIsdD0wO3Q8dS5sZW5ndGg7dCsrKXt2YXIgRj11W3RdO3N3aXRjaChGKXtjYXNlIiciOmNhc2UnIic6RFtGXSsrLHIrPUY7Y29udGludWU7Y2FzZSJcMCI6aWYoVS5pc0RpZ2l0KHVbdCsxXSkpe3IrPSJcXHgwMCI7Y29udGludWV9fWlmKGVbRl0pcis9ZVtGXTtlbHNlIGlmKEY8IiAiKXt2YXIgQz1GLmNoYXJDb2RlQXQoMCkudG9TdHJpbmcoMTYpO3IrPSJcXHgiKygiMDAiK0MpLnN1YnN0cmluZyhDLmxlbmd0aCl9ZWxzZSByKz1GfXZhciBBPW58fE9iamVjdC5rZXlzKEQpLnJlZHVjZShmdW5jdGlvbih1LGUpe3JldHVybiBEW3VdPERbZV0/dTplfSk7cmV0dXJuIEErKHI9ci5yZXBsYWNlKG5ldyBSZWdFeHAoQSwiZyIpLGVbQV0pKStBfWZ1bmN0aW9uIHModSl7aWYoMD09PXUubGVuZ3RoKXJldHVybiBCKHUpO3ZhciBEPVN0cmluZy5mcm9tQ29kZVBvaW50KHUuY29kZVBvaW50QXQoMCkpO2lmKCFVLmlzSWRTdGFydENoYXIoRCkpcmV0dXJuIEIodSk7Zm9yKHZhciBlPUQubGVuZ3RoO2U8dS5sZW5ndGg7ZSsrKWlmKCFVLmlzSWRDb250aW51ZUNoYXIoU3RyaW5nLmZyb21Db2RlUG9pbnQodS5jb2RlUG9pbnRBdChlKSkpKXJldHVybiBCKHUpO3JldHVybiB1fX19fSk7`;
async function download_file$1(_logfile, filename2, filecontents) {
  const blob = new Blob([filecontents], { type: "text/plain" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename2;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
const loaded_time = Date.now();
let last_eval_time = 0;
async function client_events$1() {
  const params = new URLSearchParams();
  params.append("loaded_time", loaded_time.valueOf());
  params.append("last_eval_time", last_eval_time.valueOf());
  return (await api$1("GET", `/api/events?${params.toString()}`)).parsed;
}
async function eval_logs$1() {
  const logs = await api$1("GET", `/api/logs`);
  last_eval_time = Date.now();
  return logs.parsed;
}
async function eval_log$1(file, headerOnly) {
  if (headerOnly) {
    return await api$1("GET", `/api/logs/${file}?header-only=true`);
  } else {
    return await api$1("GET", `/api/logs/${file}`);
  }
}
async function eval_log_headers$1(files) {
  const params = new URLSearchParams();
  for (const file of files) {
    params.append("file", file);
  }
  return (await api$1("GET", `/api/log-headers?${params.toString()}`)).parsed;
}
async function api$1(method, path, body) {
  const headers = {
    Accept: "application/json",
    Pragma: "no-cache",
    Expires: "0",
    ["Cache-Control"]: "no-cache"
  };
  const response = await fetch(`${path}`, { method, headers, body });
  if (response.ok) {
    const text = await response.text();
    return {
      parsed: await asyncJsonParse(text),
      raw: text
    };
  } else if (response.status !== 200) {
    const message = await response.text() || response.statusText;
    const error = new Error(`Error: ${response.status}: ${message})`);
    throw error;
  } else {
    throw new Error(`${response.status} - ${response.statusText} `);
  }
}
const browserApi = {
  client_events: client_events$1,
  eval_logs: eval_logs$1,
  eval_log: eval_log$1,
  eval_log_headers: eval_log_headers$1,
  download_file: download_file$1
};
var Space_Separator = /[\u1680\u2000-\u200A\u202F\u205F\u3000]/;
var ID_Start = /[\xAA\xB5\xBA\xC0-\xD6\xD8-\xF6\xF8-\u02C1\u02C6-\u02D1\u02E0-\u02E4\u02EC\u02EE\u0370-\u0374\u0376\u0377\u037A-\u037D\u037F\u0386\u0388-\u038A\u038C\u038E-\u03A1\u03A3-\u03F5\u03F7-\u0481\u048A-\u052F\u0531-\u0556\u0559\u0561-\u0587\u05D0-\u05EA\u05F0-\u05F2\u0620-\u064A\u066E\u066F\u0671-\u06D3\u06D5\u06E5\u06E6\u06EE\u06EF\u06FA-\u06FC\u06FF\u0710\u0712-\u072F\u074D-\u07A5\u07B1\u07CA-\u07EA\u07F4\u07F5\u07FA\u0800-\u0815\u081A\u0824\u0828\u0840-\u0858\u0860-\u086A\u08A0-\u08B4\u08B6-\u08BD\u0904-\u0939\u093D\u0950\u0958-\u0961\u0971-\u0980\u0985-\u098C\u098F\u0990\u0993-\u09A8\u09AA-\u09B0\u09B2\u09B6-\u09B9\u09BD\u09CE\u09DC\u09DD\u09DF-\u09E1\u09F0\u09F1\u09FC\u0A05-\u0A0A\u0A0F\u0A10\u0A13-\u0A28\u0A2A-\u0A30\u0A32\u0A33\u0A35\u0A36\u0A38\u0A39\u0A59-\u0A5C\u0A5E\u0A72-\u0A74\u0A85-\u0A8D\u0A8F-\u0A91\u0A93-\u0AA8\u0AAA-\u0AB0\u0AB2\u0AB3\u0AB5-\u0AB9\u0ABD\u0AD0\u0AE0\u0AE1\u0AF9\u0B05-\u0B0C\u0B0F\u0B10\u0B13-\u0B28\u0B2A-\u0B30\u0B32\u0B33\u0B35-\u0B39\u0B3D\u0B5C\u0B5D\u0B5F-\u0B61\u0B71\u0B83\u0B85-\u0B8A\u0B8E-\u0B90\u0B92-\u0B95\u0B99\u0B9A\u0B9C\u0B9E\u0B9F\u0BA3\u0BA4\u0BA8-\u0BAA\u0BAE-\u0BB9\u0BD0\u0C05-\u0C0C\u0C0E-\u0C10\u0C12-\u0C28\u0C2A-\u0C39\u0C3D\u0C58-\u0C5A\u0C60\u0C61\u0C80\u0C85-\u0C8C\u0C8E-\u0C90\u0C92-\u0CA8\u0CAA-\u0CB3\u0CB5-\u0CB9\u0CBD\u0CDE\u0CE0\u0CE1\u0CF1\u0CF2\u0D05-\u0D0C\u0D0E-\u0D10\u0D12-\u0D3A\u0D3D\u0D4E\u0D54-\u0D56\u0D5F-\u0D61\u0D7A-\u0D7F\u0D85-\u0D96\u0D9A-\u0DB1\u0DB3-\u0DBB\u0DBD\u0DC0-\u0DC6\u0E01-\u0E30\u0E32\u0E33\u0E40-\u0E46\u0E81\u0E82\u0E84\u0E87\u0E88\u0E8A\u0E8D\u0E94-\u0E97\u0E99-\u0E9F\u0EA1-\u0EA3\u0EA5\u0EA7\u0EAA\u0EAB\u0EAD-\u0EB0\u0EB2\u0EB3\u0EBD\u0EC0-\u0EC4\u0EC6\u0EDC-\u0EDF\u0F00\u0F40-\u0F47\u0F49-\u0F6C\u0F88-\u0F8C\u1000-\u102A\u103F\u1050-\u1055\u105A-\u105D\u1061\u1065\u1066\u106E-\u1070\u1075-\u1081\u108E\u10A0-\u10C5\u10C7\u10CD\u10D0-\u10FA\u10FC-\u1248\u124A-\u124D\u1250-\u1256\u1258\u125A-\u125D\u1260-\u1288\u128A-\u128D\u1290-\u12B0\u12B2-\u12B5\u12B8-\u12BE\u12C0\u12C2-\u12C5\u12C8-\u12D6\u12D8-\u1310\u1312-\u1315\u1318-\u135A\u1380-\u138F\u13A0-\u13F5\u13F8-\u13FD\u1401-\u166C\u166F-\u167F\u1681-\u169A\u16A0-\u16EA\u16EE-\u16F8\u1700-\u170C\u170E-\u1711\u1720-\u1731\u1740-\u1751\u1760-\u176C\u176E-\u1770\u1780-\u17B3\u17D7\u17DC\u1820-\u1877\u1880-\u1884\u1887-\u18A8\u18AA\u18B0-\u18F5\u1900-\u191E\u1950-\u196D\u1970-\u1974\u1980-\u19AB\u19B0-\u19C9\u1A00-\u1A16\u1A20-\u1A54\u1AA7\u1B05-\u1B33\u1B45-\u1B4B\u1B83-\u1BA0\u1BAE\u1BAF\u1BBA-\u1BE5\u1C00-\u1C23\u1C4D-\u1C4F\u1C5A-\u1C7D\u1C80-\u1C88\u1CE9-\u1CEC\u1CEE-\u1CF1\u1CF5\u1CF6\u1D00-\u1DBF\u1E00-\u1F15\u1F18-\u1F1D\u1F20-\u1F45\u1F48-\u1F4D\u1F50-\u1F57\u1F59\u1F5B\u1F5D\u1F5F-\u1F7D\u1F80-\u1FB4\u1FB6-\u1FBC\u1FBE\u1FC2-\u1FC4\u1FC6-\u1FCC\u1FD0-\u1FD3\u1FD6-\u1FDB\u1FE0-\u1FEC\u1FF2-\u1FF4\u1FF6-\u1FFC\u2071\u207F\u2090-\u209C\u2102\u2107\u210A-\u2113\u2115\u2119-\u211D\u2124\u2126\u2128\u212A-\u212D\u212F-\u2139\u213C-\u213F\u2145-\u2149\u214E\u2160-\u2188\u2C00-\u2C2E\u2C30-\u2C5E\u2C60-\u2CE4\u2CEB-\u2CEE\u2CF2\u2CF3\u2D00-\u2D25\u2D27\u2D2D\u2D30-\u2D67\u2D6F\u2D80-\u2D96\u2DA0-\u2DA6\u2DA8-\u2DAE\u2DB0-\u2DB6\u2DB8-\u2DBE\u2DC0-\u2DC6\u2DC8-\u2DCE\u2DD0-\u2DD6\u2DD8-\u2DDE\u2E2F\u3005-\u3007\u3021-\u3029\u3031-\u3035\u3038-\u303C\u3041-\u3096\u309D-\u309F\u30A1-\u30FA\u30FC-\u30FF\u3105-\u312E\u3131-\u318E\u31A0-\u31BA\u31F0-\u31FF\u3400-\u4DB5\u4E00-\u9FEA\uA000-\uA48C\uA4D0-\uA4FD\uA500-\uA60C\uA610-\uA61F\uA62A\uA62B\uA640-\uA66E\uA67F-\uA69D\uA6A0-\uA6EF\uA717-\uA71F\uA722-\uA788\uA78B-\uA7AE\uA7B0-\uA7B7\uA7F7-\uA801\uA803-\uA805\uA807-\uA80A\uA80C-\uA822\uA840-\uA873\uA882-\uA8B3\uA8F2-\uA8F7\uA8FB\uA8FD\uA90A-\uA925\uA930-\uA946\uA960-\uA97C\uA984-\uA9B2\uA9CF\uA9E0-\uA9E4\uA9E6-\uA9EF\uA9FA-\uA9FE\uAA00-\uAA28\uAA40-\uAA42\uAA44-\uAA4B\uAA60-\uAA76\uAA7A\uAA7E-\uAAAF\uAAB1\uAAB5\uAAB6\uAAB9-\uAABD\uAAC0\uAAC2\uAADB-\uAADD\uAAE0-\uAAEA\uAAF2-\uAAF4\uAB01-\uAB06\uAB09-\uAB0E\uAB11-\uAB16\uAB20-\uAB26\uAB28-\uAB2E\uAB30-\uAB5A\uAB5C-\uAB65\uAB70-\uABE2\uAC00-\uD7A3\uD7B0-\uD7C6\uD7CB-\uD7FB\uF900-\uFA6D\uFA70-\uFAD9\uFB00-\uFB06\uFB13-\uFB17\uFB1D\uFB1F-\uFB28\uFB2A-\uFB36\uFB38-\uFB3C\uFB3E\uFB40\uFB41\uFB43\uFB44\uFB46-\uFBB1\uFBD3-\uFD3D\uFD50-\uFD8F\uFD92-\uFDC7\uFDF0-\uFDFB\uFE70-\uFE74\uFE76-\uFEFC\uFF21-\uFF3A\uFF41-\uFF5A\uFF66-\uFFBE\uFFC2-\uFFC7\uFFCA-\uFFCF\uFFD2-\uFFD7\uFFDA-\uFFDC]|\uD800[\uDC00-\uDC0B\uDC0D-\uDC26\uDC28-\uDC3A\uDC3C\uDC3D\uDC3F-\uDC4D\uDC50-\uDC5D\uDC80-\uDCFA\uDD40-\uDD74\uDE80-\uDE9C\uDEA0-\uDED0\uDF00-\uDF1F\uDF2D-\uDF4A\uDF50-\uDF75\uDF80-\uDF9D\uDFA0-\uDFC3\uDFC8-\uDFCF\uDFD1-\uDFD5]|\uD801[\uDC00-\uDC9D\uDCB0-\uDCD3\uDCD8-\uDCFB\uDD00-\uDD27\uDD30-\uDD63\uDE00-\uDF36\uDF40-\uDF55\uDF60-\uDF67]|\uD802[\uDC00-\uDC05\uDC08\uDC0A-\uDC35\uDC37\uDC38\uDC3C\uDC3F-\uDC55\uDC60-\uDC76\uDC80-\uDC9E\uDCE0-\uDCF2\uDCF4\uDCF5\uDD00-\uDD15\uDD20-\uDD39\uDD80-\uDDB7\uDDBE\uDDBF\uDE00\uDE10-\uDE13\uDE15-\uDE17\uDE19-\uDE33\uDE60-\uDE7C\uDE80-\uDE9C\uDEC0-\uDEC7\uDEC9-\uDEE4\uDF00-\uDF35\uDF40-\uDF55\uDF60-\uDF72\uDF80-\uDF91]|\uD803[\uDC00-\uDC48\uDC80-\uDCB2\uDCC0-\uDCF2]|\uD804[\uDC03-\uDC37\uDC83-\uDCAF\uDCD0-\uDCE8\uDD03-\uDD26\uDD50-\uDD72\uDD76\uDD83-\uDDB2\uDDC1-\uDDC4\uDDDA\uDDDC\uDE00-\uDE11\uDE13-\uDE2B\uDE80-\uDE86\uDE88\uDE8A-\uDE8D\uDE8F-\uDE9D\uDE9F-\uDEA8\uDEB0-\uDEDE\uDF05-\uDF0C\uDF0F\uDF10\uDF13-\uDF28\uDF2A-\uDF30\uDF32\uDF33\uDF35-\uDF39\uDF3D\uDF50\uDF5D-\uDF61]|\uD805[\uDC00-\uDC34\uDC47-\uDC4A\uDC80-\uDCAF\uDCC4\uDCC5\uDCC7\uDD80-\uDDAE\uDDD8-\uDDDB\uDE00-\uDE2F\uDE44\uDE80-\uDEAA\uDF00-\uDF19]|\uD806[\uDCA0-\uDCDF\uDCFF\uDE00\uDE0B-\uDE32\uDE3A\uDE50\uDE5C-\uDE83\uDE86-\uDE89\uDEC0-\uDEF8]|\uD807[\uDC00-\uDC08\uDC0A-\uDC2E\uDC40\uDC72-\uDC8F\uDD00-\uDD06\uDD08\uDD09\uDD0B-\uDD30\uDD46]|\uD808[\uDC00-\uDF99]|\uD809[\uDC00-\uDC6E\uDC80-\uDD43]|[\uD80C\uD81C-\uD820\uD840-\uD868\uD86A-\uD86C\uD86F-\uD872\uD874-\uD879][\uDC00-\uDFFF]|\uD80D[\uDC00-\uDC2E]|\uD811[\uDC00-\uDE46]|\uD81A[\uDC00-\uDE38\uDE40-\uDE5E\uDED0-\uDEED\uDF00-\uDF2F\uDF40-\uDF43\uDF63-\uDF77\uDF7D-\uDF8F]|\uD81B[\uDF00-\uDF44\uDF50\uDF93-\uDF9F\uDFE0\uDFE1]|\uD821[\uDC00-\uDFEC]|\uD822[\uDC00-\uDEF2]|\uD82C[\uDC00-\uDD1E\uDD70-\uDEFB]|\uD82F[\uDC00-\uDC6A\uDC70-\uDC7C\uDC80-\uDC88\uDC90-\uDC99]|\uD835[\uDC00-\uDC54\uDC56-\uDC9C\uDC9E\uDC9F\uDCA2\uDCA5\uDCA6\uDCA9-\uDCAC\uDCAE-\uDCB9\uDCBB\uDCBD-\uDCC3\uDCC5-\uDD05\uDD07-\uDD0A\uDD0D-\uDD14\uDD16-\uDD1C\uDD1E-\uDD39\uDD3B-\uDD3E\uDD40-\uDD44\uDD46\uDD4A-\uDD50\uDD52-\uDEA5\uDEA8-\uDEC0\uDEC2-\uDEDA\uDEDC-\uDEFA\uDEFC-\uDF14\uDF16-\uDF34\uDF36-\uDF4E\uDF50-\uDF6E\uDF70-\uDF88\uDF8A-\uDFA8\uDFAA-\uDFC2\uDFC4-\uDFCB]|\uD83A[\uDC00-\uDCC4\uDD00-\uDD43]|\uD83B[\uDE00-\uDE03\uDE05-\uDE1F\uDE21\uDE22\uDE24\uDE27\uDE29-\uDE32\uDE34-\uDE37\uDE39\uDE3B\uDE42\uDE47\uDE49\uDE4B\uDE4D-\uDE4F\uDE51\uDE52\uDE54\uDE57\uDE59\uDE5B\uDE5D\uDE5F\uDE61\uDE62\uDE64\uDE67-\uDE6A\uDE6C-\uDE72\uDE74-\uDE77\uDE79-\uDE7C\uDE7E\uDE80-\uDE89\uDE8B-\uDE9B\uDEA1-\uDEA3\uDEA5-\uDEA9\uDEAB-\uDEBB]|\uD869[\uDC00-\uDED6\uDF00-\uDFFF]|\uD86D[\uDC00-\uDF34\uDF40-\uDFFF]|\uD86E[\uDC00-\uDC1D\uDC20-\uDFFF]|\uD873[\uDC00-\uDEA1\uDEB0-\uDFFF]|\uD87A[\uDC00-\uDFE0]|\uD87E[\uDC00-\uDE1D]/;
var ID_Continue = /[\xAA\xB5\xBA\xC0-\xD6\xD8-\xF6\xF8-\u02C1\u02C6-\u02D1\u02E0-\u02E4\u02EC\u02EE\u0300-\u0374\u0376\u0377\u037A-\u037D\u037F\u0386\u0388-\u038A\u038C\u038E-\u03A1\u03A3-\u03F5\u03F7-\u0481\u0483-\u0487\u048A-\u052F\u0531-\u0556\u0559\u0561-\u0587\u0591-\u05BD\u05BF\u05C1\u05C2\u05C4\u05C5\u05C7\u05D0-\u05EA\u05F0-\u05F2\u0610-\u061A\u0620-\u0669\u066E-\u06D3\u06D5-\u06DC\u06DF-\u06E8\u06EA-\u06FC\u06FF\u0710-\u074A\u074D-\u07B1\u07C0-\u07F5\u07FA\u0800-\u082D\u0840-\u085B\u0860-\u086A\u08A0-\u08B4\u08B6-\u08BD\u08D4-\u08E1\u08E3-\u0963\u0966-\u096F\u0971-\u0983\u0985-\u098C\u098F\u0990\u0993-\u09A8\u09AA-\u09B0\u09B2\u09B6-\u09B9\u09BC-\u09C4\u09C7\u09C8\u09CB-\u09CE\u09D7\u09DC\u09DD\u09DF-\u09E3\u09E6-\u09F1\u09FC\u0A01-\u0A03\u0A05-\u0A0A\u0A0F\u0A10\u0A13-\u0A28\u0A2A-\u0A30\u0A32\u0A33\u0A35\u0A36\u0A38\u0A39\u0A3C\u0A3E-\u0A42\u0A47\u0A48\u0A4B-\u0A4D\u0A51\u0A59-\u0A5C\u0A5E\u0A66-\u0A75\u0A81-\u0A83\u0A85-\u0A8D\u0A8F-\u0A91\u0A93-\u0AA8\u0AAA-\u0AB0\u0AB2\u0AB3\u0AB5-\u0AB9\u0ABC-\u0AC5\u0AC7-\u0AC9\u0ACB-\u0ACD\u0AD0\u0AE0-\u0AE3\u0AE6-\u0AEF\u0AF9-\u0AFF\u0B01-\u0B03\u0B05-\u0B0C\u0B0F\u0B10\u0B13-\u0B28\u0B2A-\u0B30\u0B32\u0B33\u0B35-\u0B39\u0B3C-\u0B44\u0B47\u0B48\u0B4B-\u0B4D\u0B56\u0B57\u0B5C\u0B5D\u0B5F-\u0B63\u0B66-\u0B6F\u0B71\u0B82\u0B83\u0B85-\u0B8A\u0B8E-\u0B90\u0B92-\u0B95\u0B99\u0B9A\u0B9C\u0B9E\u0B9F\u0BA3\u0BA4\u0BA8-\u0BAA\u0BAE-\u0BB9\u0BBE-\u0BC2\u0BC6-\u0BC8\u0BCA-\u0BCD\u0BD0\u0BD7\u0BE6-\u0BEF\u0C00-\u0C03\u0C05-\u0C0C\u0C0E-\u0C10\u0C12-\u0C28\u0C2A-\u0C39\u0C3D-\u0C44\u0C46-\u0C48\u0C4A-\u0C4D\u0C55\u0C56\u0C58-\u0C5A\u0C60-\u0C63\u0C66-\u0C6F\u0C80-\u0C83\u0C85-\u0C8C\u0C8E-\u0C90\u0C92-\u0CA8\u0CAA-\u0CB3\u0CB5-\u0CB9\u0CBC-\u0CC4\u0CC6-\u0CC8\u0CCA-\u0CCD\u0CD5\u0CD6\u0CDE\u0CE0-\u0CE3\u0CE6-\u0CEF\u0CF1\u0CF2\u0D00-\u0D03\u0D05-\u0D0C\u0D0E-\u0D10\u0D12-\u0D44\u0D46-\u0D48\u0D4A-\u0D4E\u0D54-\u0D57\u0D5F-\u0D63\u0D66-\u0D6F\u0D7A-\u0D7F\u0D82\u0D83\u0D85-\u0D96\u0D9A-\u0DB1\u0DB3-\u0DBB\u0DBD\u0DC0-\u0DC6\u0DCA\u0DCF-\u0DD4\u0DD6\u0DD8-\u0DDF\u0DE6-\u0DEF\u0DF2\u0DF3\u0E01-\u0E3A\u0E40-\u0E4E\u0E50-\u0E59\u0E81\u0E82\u0E84\u0E87\u0E88\u0E8A\u0E8D\u0E94-\u0E97\u0E99-\u0E9F\u0EA1-\u0EA3\u0EA5\u0EA7\u0EAA\u0EAB\u0EAD-\u0EB9\u0EBB-\u0EBD\u0EC0-\u0EC4\u0EC6\u0EC8-\u0ECD\u0ED0-\u0ED9\u0EDC-\u0EDF\u0F00\u0F18\u0F19\u0F20-\u0F29\u0F35\u0F37\u0F39\u0F3E-\u0F47\u0F49-\u0F6C\u0F71-\u0F84\u0F86-\u0F97\u0F99-\u0FBC\u0FC6\u1000-\u1049\u1050-\u109D\u10A0-\u10C5\u10C7\u10CD\u10D0-\u10FA\u10FC-\u1248\u124A-\u124D\u1250-\u1256\u1258\u125A-\u125D\u1260-\u1288\u128A-\u128D\u1290-\u12B0\u12B2-\u12B5\u12B8-\u12BE\u12C0\u12C2-\u12C5\u12C8-\u12D6\u12D8-\u1310\u1312-\u1315\u1318-\u135A\u135D-\u135F\u1380-\u138F\u13A0-\u13F5\u13F8-\u13FD\u1401-\u166C\u166F-\u167F\u1681-\u169A\u16A0-\u16EA\u16EE-\u16F8\u1700-\u170C\u170E-\u1714\u1720-\u1734\u1740-\u1753\u1760-\u176C\u176E-\u1770\u1772\u1773\u1780-\u17D3\u17D7\u17DC\u17DD\u17E0-\u17E9\u180B-\u180D\u1810-\u1819\u1820-\u1877\u1880-\u18AA\u18B0-\u18F5\u1900-\u191E\u1920-\u192B\u1930-\u193B\u1946-\u196D\u1970-\u1974\u1980-\u19AB\u19B0-\u19C9\u19D0-\u19D9\u1A00-\u1A1B\u1A20-\u1A5E\u1A60-\u1A7C\u1A7F-\u1A89\u1A90-\u1A99\u1AA7\u1AB0-\u1ABD\u1B00-\u1B4B\u1B50-\u1B59\u1B6B-\u1B73\u1B80-\u1BF3\u1C00-\u1C37\u1C40-\u1C49\u1C4D-\u1C7D\u1C80-\u1C88\u1CD0-\u1CD2\u1CD4-\u1CF9\u1D00-\u1DF9\u1DFB-\u1F15\u1F18-\u1F1D\u1F20-\u1F45\u1F48-\u1F4D\u1F50-\u1F57\u1F59\u1F5B\u1F5D\u1F5F-\u1F7D\u1F80-\u1FB4\u1FB6-\u1FBC\u1FBE\u1FC2-\u1FC4\u1FC6-\u1FCC\u1FD0-\u1FD3\u1FD6-\u1FDB\u1FE0-\u1FEC\u1FF2-\u1FF4\u1FF6-\u1FFC\u203F\u2040\u2054\u2071\u207F\u2090-\u209C\u20D0-\u20DC\u20E1\u20E5-\u20F0\u2102\u2107\u210A-\u2113\u2115\u2119-\u211D\u2124\u2126\u2128\u212A-\u212D\u212F-\u2139\u213C-\u213F\u2145-\u2149\u214E\u2160-\u2188\u2C00-\u2C2E\u2C30-\u2C5E\u2C60-\u2CE4\u2CEB-\u2CF3\u2D00-\u2D25\u2D27\u2D2D\u2D30-\u2D67\u2D6F\u2D7F-\u2D96\u2DA0-\u2DA6\u2DA8-\u2DAE\u2DB0-\u2DB6\u2DB8-\u2DBE\u2DC0-\u2DC6\u2DC8-\u2DCE\u2DD0-\u2DD6\u2DD8-\u2DDE\u2DE0-\u2DFF\u2E2F\u3005-\u3007\u3021-\u302F\u3031-\u3035\u3038-\u303C\u3041-\u3096\u3099\u309A\u309D-\u309F\u30A1-\u30FA\u30FC-\u30FF\u3105-\u312E\u3131-\u318E\u31A0-\u31BA\u31F0-\u31FF\u3400-\u4DB5\u4E00-\u9FEA\uA000-\uA48C\uA4D0-\uA4FD\uA500-\uA60C\uA610-\uA62B\uA640-\uA66F\uA674-\uA67D\uA67F-\uA6F1\uA717-\uA71F\uA722-\uA788\uA78B-\uA7AE\uA7B0-\uA7B7\uA7F7-\uA827\uA840-\uA873\uA880-\uA8C5\uA8D0-\uA8D9\uA8E0-\uA8F7\uA8FB\uA8FD\uA900-\uA92D\uA930-\uA953\uA960-\uA97C\uA980-\uA9C0\uA9CF-\uA9D9\uA9E0-\uA9FE\uAA00-\uAA36\uAA40-\uAA4D\uAA50-\uAA59\uAA60-\uAA76\uAA7A-\uAAC2\uAADB-\uAADD\uAAE0-\uAAEF\uAAF2-\uAAF6\uAB01-\uAB06\uAB09-\uAB0E\uAB11-\uAB16\uAB20-\uAB26\uAB28-\uAB2E\uAB30-\uAB5A\uAB5C-\uAB65\uAB70-\uABEA\uABEC\uABED\uABF0-\uABF9\uAC00-\uD7A3\uD7B0-\uD7C6\uD7CB-\uD7FB\uF900-\uFA6D\uFA70-\uFAD9\uFB00-\uFB06\uFB13-\uFB17\uFB1D-\uFB28\uFB2A-\uFB36\uFB38-\uFB3C\uFB3E\uFB40\uFB41\uFB43\uFB44\uFB46-\uFBB1\uFBD3-\uFD3D\uFD50-\uFD8F\uFD92-\uFDC7\uFDF0-\uFDFB\uFE00-\uFE0F\uFE20-\uFE2F\uFE33\uFE34\uFE4D-\uFE4F\uFE70-\uFE74\uFE76-\uFEFC\uFF10-\uFF19\uFF21-\uFF3A\uFF3F\uFF41-\uFF5A\uFF66-\uFFBE\uFFC2-\uFFC7\uFFCA-\uFFCF\uFFD2-\uFFD7\uFFDA-\uFFDC]|\uD800[\uDC00-\uDC0B\uDC0D-\uDC26\uDC28-\uDC3A\uDC3C\uDC3D\uDC3F-\uDC4D\uDC50-\uDC5D\uDC80-\uDCFA\uDD40-\uDD74\uDDFD\uDE80-\uDE9C\uDEA0-\uDED0\uDEE0\uDF00-\uDF1F\uDF2D-\uDF4A\uDF50-\uDF7A\uDF80-\uDF9D\uDFA0-\uDFC3\uDFC8-\uDFCF\uDFD1-\uDFD5]|\uD801[\uDC00-\uDC9D\uDCA0-\uDCA9\uDCB0-\uDCD3\uDCD8-\uDCFB\uDD00-\uDD27\uDD30-\uDD63\uDE00-\uDF36\uDF40-\uDF55\uDF60-\uDF67]|\uD802[\uDC00-\uDC05\uDC08\uDC0A-\uDC35\uDC37\uDC38\uDC3C\uDC3F-\uDC55\uDC60-\uDC76\uDC80-\uDC9E\uDCE0-\uDCF2\uDCF4\uDCF5\uDD00-\uDD15\uDD20-\uDD39\uDD80-\uDDB7\uDDBE\uDDBF\uDE00-\uDE03\uDE05\uDE06\uDE0C-\uDE13\uDE15-\uDE17\uDE19-\uDE33\uDE38-\uDE3A\uDE3F\uDE60-\uDE7C\uDE80-\uDE9C\uDEC0-\uDEC7\uDEC9-\uDEE6\uDF00-\uDF35\uDF40-\uDF55\uDF60-\uDF72\uDF80-\uDF91]|\uD803[\uDC00-\uDC48\uDC80-\uDCB2\uDCC0-\uDCF2]|\uD804[\uDC00-\uDC46\uDC66-\uDC6F\uDC7F-\uDCBA\uDCD0-\uDCE8\uDCF0-\uDCF9\uDD00-\uDD34\uDD36-\uDD3F\uDD50-\uDD73\uDD76\uDD80-\uDDC4\uDDCA-\uDDCC\uDDD0-\uDDDA\uDDDC\uDE00-\uDE11\uDE13-\uDE37\uDE3E\uDE80-\uDE86\uDE88\uDE8A-\uDE8D\uDE8F-\uDE9D\uDE9F-\uDEA8\uDEB0-\uDEEA\uDEF0-\uDEF9\uDF00-\uDF03\uDF05-\uDF0C\uDF0F\uDF10\uDF13-\uDF28\uDF2A-\uDF30\uDF32\uDF33\uDF35-\uDF39\uDF3C-\uDF44\uDF47\uDF48\uDF4B-\uDF4D\uDF50\uDF57\uDF5D-\uDF63\uDF66-\uDF6C\uDF70-\uDF74]|\uD805[\uDC00-\uDC4A\uDC50-\uDC59\uDC80-\uDCC5\uDCC7\uDCD0-\uDCD9\uDD80-\uDDB5\uDDB8-\uDDC0\uDDD8-\uDDDD\uDE00-\uDE40\uDE44\uDE50-\uDE59\uDE80-\uDEB7\uDEC0-\uDEC9\uDF00-\uDF19\uDF1D-\uDF2B\uDF30-\uDF39]|\uD806[\uDCA0-\uDCE9\uDCFF\uDE00-\uDE3E\uDE47\uDE50-\uDE83\uDE86-\uDE99\uDEC0-\uDEF8]|\uD807[\uDC00-\uDC08\uDC0A-\uDC36\uDC38-\uDC40\uDC50-\uDC59\uDC72-\uDC8F\uDC92-\uDCA7\uDCA9-\uDCB6\uDD00-\uDD06\uDD08\uDD09\uDD0B-\uDD36\uDD3A\uDD3C\uDD3D\uDD3F-\uDD47\uDD50-\uDD59]|\uD808[\uDC00-\uDF99]|\uD809[\uDC00-\uDC6E\uDC80-\uDD43]|[\uD80C\uD81C-\uD820\uD840-\uD868\uD86A-\uD86C\uD86F-\uD872\uD874-\uD879][\uDC00-\uDFFF]|\uD80D[\uDC00-\uDC2E]|\uD811[\uDC00-\uDE46]|\uD81A[\uDC00-\uDE38\uDE40-\uDE5E\uDE60-\uDE69\uDED0-\uDEED\uDEF0-\uDEF4\uDF00-\uDF36\uDF40-\uDF43\uDF50-\uDF59\uDF63-\uDF77\uDF7D-\uDF8F]|\uD81B[\uDF00-\uDF44\uDF50-\uDF7E\uDF8F-\uDF9F\uDFE0\uDFE1]|\uD821[\uDC00-\uDFEC]|\uD822[\uDC00-\uDEF2]|\uD82C[\uDC00-\uDD1E\uDD70-\uDEFB]|\uD82F[\uDC00-\uDC6A\uDC70-\uDC7C\uDC80-\uDC88\uDC90-\uDC99\uDC9D\uDC9E]|\uD834[\uDD65-\uDD69\uDD6D-\uDD72\uDD7B-\uDD82\uDD85-\uDD8B\uDDAA-\uDDAD\uDE42-\uDE44]|\uD835[\uDC00-\uDC54\uDC56-\uDC9C\uDC9E\uDC9F\uDCA2\uDCA5\uDCA6\uDCA9-\uDCAC\uDCAE-\uDCB9\uDCBB\uDCBD-\uDCC3\uDCC5-\uDD05\uDD07-\uDD0A\uDD0D-\uDD14\uDD16-\uDD1C\uDD1E-\uDD39\uDD3B-\uDD3E\uDD40-\uDD44\uDD46\uDD4A-\uDD50\uDD52-\uDEA5\uDEA8-\uDEC0\uDEC2-\uDEDA\uDEDC-\uDEFA\uDEFC-\uDF14\uDF16-\uDF34\uDF36-\uDF4E\uDF50-\uDF6E\uDF70-\uDF88\uDF8A-\uDFA8\uDFAA-\uDFC2\uDFC4-\uDFCB\uDFCE-\uDFFF]|\uD836[\uDE00-\uDE36\uDE3B-\uDE6C\uDE75\uDE84\uDE9B-\uDE9F\uDEA1-\uDEAF]|\uD838[\uDC00-\uDC06\uDC08-\uDC18\uDC1B-\uDC21\uDC23\uDC24\uDC26-\uDC2A]|\uD83A[\uDC00-\uDCC4\uDCD0-\uDCD6\uDD00-\uDD4A\uDD50-\uDD59]|\uD83B[\uDE00-\uDE03\uDE05-\uDE1F\uDE21\uDE22\uDE24\uDE27\uDE29-\uDE32\uDE34-\uDE37\uDE39\uDE3B\uDE42\uDE47\uDE49\uDE4B\uDE4D-\uDE4F\uDE51\uDE52\uDE54\uDE57\uDE59\uDE5B\uDE5D\uDE5F\uDE61\uDE62\uDE64\uDE67-\uDE6A\uDE6C-\uDE72\uDE74-\uDE77\uDE79-\uDE7C\uDE7E\uDE80-\uDE89\uDE8B-\uDE9B\uDEA1-\uDEA3\uDEA5-\uDEA9\uDEAB-\uDEBB]|\uD869[\uDC00-\uDED6\uDF00-\uDFFF]|\uD86D[\uDC00-\uDF34\uDF40-\uDFFF]|\uD86E[\uDC00-\uDC1D\uDC20-\uDFFF]|\uD873[\uDC00-\uDEA1\uDEB0-\uDFFF]|\uD87A[\uDC00-\uDFE0]|\uD87E[\uDC00-\uDE1D]|\uDB40[\uDD00-\uDDEF]/;
var unicode = {
  Space_Separator,
  ID_Start,
  ID_Continue
};
var util = {
  isSpaceSeparator(c2) {
    return typeof c2 === "string" && unicode.Space_Separator.test(c2);
  },
  isIdStartChar(c2) {
    return typeof c2 === "string" && (c2 >= "a" && c2 <= "z" || c2 >= "A" && c2 <= "Z" || c2 === "$" || c2 === "_" || unicode.ID_Start.test(c2));
  },
  isIdContinueChar(c2) {
    return typeof c2 === "string" && (c2 >= "a" && c2 <= "z" || c2 >= "A" && c2 <= "Z" || c2 >= "0" && c2 <= "9" || c2 === "$" || c2 === "_" || c2 === "‌" || c2 === "‍" || unicode.ID_Continue.test(c2));
  },
  isDigit(c2) {
    return typeof c2 === "string" && /[0-9]/.test(c2);
  },
  isHexDigit(c2) {
    return typeof c2 === "string" && /[0-9A-Fa-f]/.test(c2);
  }
};
let source;
let parseState;
let stack;
let pos;
let line;
let column;
let token;
let key;
let root;
var parse = function parse2(text, reviver) {
  source = String(text);
  parseState = "start";
  stack = [];
  pos = 0;
  line = 1;
  column = 0;
  token = void 0;
  key = void 0;
  root = void 0;
  do {
    token = lex();
    parseStates[parseState]();
  } while (token.type !== "eof");
  if (typeof reviver === "function") {
    return internalize({ "": root }, "", reviver);
  }
  return root;
};
function internalize(holder, name, reviver) {
  const value = holder[name];
  if (value != null && typeof value === "object") {
    if (Array.isArray(value)) {
      for (let i2 = 0; i2 < value.length; i2++) {
        const key2 = String(i2);
        const replacement = internalize(value, key2, reviver);
        if (replacement === void 0) {
          delete value[key2];
        } else {
          Object.defineProperty(value, key2, {
            value: replacement,
            writable: true,
            enumerable: true,
            configurable: true
          });
        }
      }
    } else {
      for (const key2 in value) {
        const replacement = internalize(value, key2, reviver);
        if (replacement === void 0) {
          delete value[key2];
        } else {
          Object.defineProperty(value, key2, {
            value: replacement,
            writable: true,
            enumerable: true,
            configurable: true
          });
        }
      }
    }
  }
  return reviver.call(holder, name, value);
}
let lexState;
let buffer;
let doubleQuote;
let sign;
let c;
function lex() {
  lexState = "default";
  buffer = "";
  doubleQuote = false;
  sign = 1;
  for (; ; ) {
    c = peek();
    const token2 = lexStates[lexState]();
    if (token2) {
      return token2;
    }
  }
}
function peek() {
  if (source[pos]) {
    return String.fromCodePoint(source.codePointAt(pos));
  }
}
function read() {
  const c2 = peek();
  if (c2 === "\n") {
    line++;
    column = 0;
  } else if (c2) {
    column += c2.length;
  } else {
    column++;
  }
  if (c2) {
    pos += c2.length;
  }
  return c2;
}
const lexStates = {
  default() {
    switch (c) {
      case "	":
      case "\v":
      case "\f":
      case " ":
      case " ":
      case "\uFEFF":
      case "\n":
      case "\r":
      case "\u2028":
      case "\u2029":
        read();
        return;
      case "/":
        read();
        lexState = "comment";
        return;
      case void 0:
        read();
        return newToken("eof");
    }
    if (util.isSpaceSeparator(c)) {
      read();
      return;
    }
    return lexStates[parseState]();
  },
  comment() {
    switch (c) {
      case "*":
        read();
        lexState = "multiLineComment";
        return;
      case "/":
        read();
        lexState = "singleLineComment";
        return;
    }
    throw invalidChar(read());
  },
  multiLineComment() {
    switch (c) {
      case "*":
        read();
        lexState = "multiLineCommentAsterisk";
        return;
      case void 0:
        throw invalidChar(read());
    }
    read();
  },
  multiLineCommentAsterisk() {
    switch (c) {
      case "*":
        read();
        return;
      case "/":
        read();
        lexState = "default";
        return;
      case void 0:
        throw invalidChar(read());
    }
    read();
    lexState = "multiLineComment";
  },
  singleLineComment() {
    switch (c) {
      case "\n":
      case "\r":
      case "\u2028":
      case "\u2029":
        read();
        lexState = "default";
        return;
      case void 0:
        read();
        return newToken("eof");
    }
    read();
  },
  value() {
    switch (c) {
      case "{":
      case "[":
        return newToken("punctuator", read());
      case "n":
        read();
        literal("ull");
        return newToken("null", null);
      case "t":
        read();
        literal("rue");
        return newToken("boolean", true);
      case "f":
        read();
        literal("alse");
        return newToken("boolean", false);
      case "-":
      case "+":
        if (read() === "-") {
          sign = -1;
        }
        lexState = "sign";
        return;
      case ".":
        buffer = read();
        lexState = "decimalPointLeading";
        return;
      case "0":
        buffer = read();
        lexState = "zero";
        return;
      case "1":
      case "2":
      case "3":
      case "4":
      case "5":
      case "6":
      case "7":
      case "8":
      case "9":
        buffer = read();
        lexState = "decimalInteger";
        return;
      case "I":
        read();
        literal("nfinity");
        return newToken("numeric", Infinity);
      case "N":
        read();
        literal("aN");
        return newToken("numeric", NaN);
      case '"':
      case "'":
        doubleQuote = read() === '"';
        buffer = "";
        lexState = "string";
        return;
    }
    throw invalidChar(read());
  },
  identifierNameStartEscape() {
    if (c !== "u") {
      throw invalidChar(read());
    }
    read();
    const u2 = unicodeEscape();
    switch (u2) {
      case "$":
      case "_":
        break;
      default:
        if (!util.isIdStartChar(u2)) {
          throw invalidIdentifier();
        }
        break;
    }
    buffer += u2;
    lexState = "identifierName";
  },
  identifierName() {
    switch (c) {
      case "$":
      case "_":
      case "‌":
      case "‍":
        buffer += read();
        return;
      case "\\":
        read();
        lexState = "identifierNameEscape";
        return;
    }
    if (util.isIdContinueChar(c)) {
      buffer += read();
      return;
    }
    return newToken("identifier", buffer);
  },
  identifierNameEscape() {
    if (c !== "u") {
      throw invalidChar(read());
    }
    read();
    const u2 = unicodeEscape();
    switch (u2) {
      case "$":
      case "_":
      case "‌":
      case "‍":
        break;
      default:
        if (!util.isIdContinueChar(u2)) {
          throw invalidIdentifier();
        }
        break;
    }
    buffer += u2;
    lexState = "identifierName";
  },
  sign() {
    switch (c) {
      case ".":
        buffer = read();
        lexState = "decimalPointLeading";
        return;
      case "0":
        buffer = read();
        lexState = "zero";
        return;
      case "1":
      case "2":
      case "3":
      case "4":
      case "5":
      case "6":
      case "7":
      case "8":
      case "9":
        buffer = read();
        lexState = "decimalInteger";
        return;
      case "I":
        read();
        literal("nfinity");
        return newToken("numeric", sign * Infinity);
      case "N":
        read();
        literal("aN");
        return newToken("numeric", NaN);
    }
    throw invalidChar(read());
  },
  zero() {
    switch (c) {
      case ".":
        buffer += read();
        lexState = "decimalPoint";
        return;
      case "e":
      case "E":
        buffer += read();
        lexState = "decimalExponent";
        return;
      case "x":
      case "X":
        buffer += read();
        lexState = "hexadecimal";
        return;
    }
    return newToken("numeric", sign * 0);
  },
  decimalInteger() {
    switch (c) {
      case ".":
        buffer += read();
        lexState = "decimalPoint";
        return;
      case "e":
      case "E":
        buffer += read();
        lexState = "decimalExponent";
        return;
    }
    if (util.isDigit(c)) {
      buffer += read();
      return;
    }
    return newToken("numeric", sign * Number(buffer));
  },
  decimalPointLeading() {
    if (util.isDigit(c)) {
      buffer += read();
      lexState = "decimalFraction";
      return;
    }
    throw invalidChar(read());
  },
  decimalPoint() {
    switch (c) {
      case "e":
      case "E":
        buffer += read();
        lexState = "decimalExponent";
        return;
    }
    if (util.isDigit(c)) {
      buffer += read();
      lexState = "decimalFraction";
      return;
    }
    return newToken("numeric", sign * Number(buffer));
  },
  decimalFraction() {
    switch (c) {
      case "e":
      case "E":
        buffer += read();
        lexState = "decimalExponent";
        return;
    }
    if (util.isDigit(c)) {
      buffer += read();
      return;
    }
    return newToken("numeric", sign * Number(buffer));
  },
  decimalExponent() {
    switch (c) {
      case "+":
      case "-":
        buffer += read();
        lexState = "decimalExponentSign";
        return;
    }
    if (util.isDigit(c)) {
      buffer += read();
      lexState = "decimalExponentInteger";
      return;
    }
    throw invalidChar(read());
  },
  decimalExponentSign() {
    if (util.isDigit(c)) {
      buffer += read();
      lexState = "decimalExponentInteger";
      return;
    }
    throw invalidChar(read());
  },
  decimalExponentInteger() {
    if (util.isDigit(c)) {
      buffer += read();
      return;
    }
    return newToken("numeric", sign * Number(buffer));
  },
  hexadecimal() {
    if (util.isHexDigit(c)) {
      buffer += read();
      lexState = "hexadecimalInteger";
      return;
    }
    throw invalidChar(read());
  },
  hexadecimalInteger() {
    if (util.isHexDigit(c)) {
      buffer += read();
      return;
    }
    return newToken("numeric", sign * Number(buffer));
  },
  string() {
    switch (c) {
      case "\\":
        read();
        buffer += escape();
        return;
      case '"':
        if (doubleQuote) {
          read();
          return newToken("string", buffer);
        }
        buffer += read();
        return;
      case "'":
        if (!doubleQuote) {
          read();
          return newToken("string", buffer);
        }
        buffer += read();
        return;
      case "\n":
      case "\r":
        throw invalidChar(read());
      case "\u2028":
      case "\u2029":
        separatorChar(c);
        break;
      case void 0:
        throw invalidChar(read());
    }
    buffer += read();
  },
  start() {
    switch (c) {
      case "{":
      case "[":
        return newToken("punctuator", read());
    }
    lexState = "value";
  },
  beforePropertyName() {
    switch (c) {
      case "$":
      case "_":
        buffer = read();
        lexState = "identifierName";
        return;
      case "\\":
        read();
        lexState = "identifierNameStartEscape";
        return;
      case "}":
        return newToken("punctuator", read());
      case '"':
      case "'":
        doubleQuote = read() === '"';
        lexState = "string";
        return;
    }
    if (util.isIdStartChar(c)) {
      buffer += read();
      lexState = "identifierName";
      return;
    }
    throw invalidChar(read());
  },
  afterPropertyName() {
    if (c === ":") {
      return newToken("punctuator", read());
    }
    throw invalidChar(read());
  },
  beforePropertyValue() {
    lexState = "value";
  },
  afterPropertyValue() {
    switch (c) {
      case ",":
      case "}":
        return newToken("punctuator", read());
    }
    throw invalidChar(read());
  },
  beforeArrayValue() {
    if (c === "]") {
      return newToken("punctuator", read());
    }
    lexState = "value";
  },
  afterArrayValue() {
    switch (c) {
      case ",":
      case "]":
        return newToken("punctuator", read());
    }
    throw invalidChar(read());
  },
  end() {
    throw invalidChar(read());
  }
};
function newToken(type, value) {
  return {
    type,
    value,
    line,
    column
  };
}
function literal(s2) {
  for (const c2 of s2) {
    const p2 = peek();
    if (p2 !== c2) {
      throw invalidChar(read());
    }
    read();
  }
}
function escape() {
  const c2 = peek();
  switch (c2) {
    case "b":
      read();
      return "\b";
    case "f":
      read();
      return "\f";
    case "n":
      read();
      return "\n";
    case "r":
      read();
      return "\r";
    case "t":
      read();
      return "	";
    case "v":
      read();
      return "\v";
    case "0":
      read();
      if (util.isDigit(peek())) {
        throw invalidChar(read());
      }
      return "\0";
    case "x":
      read();
      return hexEscape();
    case "u":
      read();
      return unicodeEscape();
    case "\n":
    case "\u2028":
    case "\u2029":
      read();
      return "";
    case "\r":
      read();
      if (peek() === "\n") {
        read();
      }
      return "";
    case "1":
    case "2":
    case "3":
    case "4":
    case "5":
    case "6":
    case "7":
    case "8":
    case "9":
      throw invalidChar(read());
    case void 0:
      throw invalidChar(read());
  }
  return read();
}
function hexEscape() {
  let buffer2 = "";
  let c2 = peek();
  if (!util.isHexDigit(c2)) {
    throw invalidChar(read());
  }
  buffer2 += read();
  c2 = peek();
  if (!util.isHexDigit(c2)) {
    throw invalidChar(read());
  }
  buffer2 += read();
  return String.fromCodePoint(parseInt(buffer2, 16));
}
function unicodeEscape() {
  let buffer2 = "";
  let count = 4;
  while (count-- > 0) {
    const c2 = peek();
    if (!util.isHexDigit(c2)) {
      throw invalidChar(read());
    }
    buffer2 += read();
  }
  return String.fromCodePoint(parseInt(buffer2, 16));
}
const parseStates = {
  start() {
    if (token.type === "eof") {
      throw invalidEOF();
    }
    push();
  },
  beforePropertyName() {
    switch (token.type) {
      case "identifier":
      case "string":
        key = token.value;
        parseState = "afterPropertyName";
        return;
      case "punctuator":
        pop();
        return;
      case "eof":
        throw invalidEOF();
    }
  },
  afterPropertyName() {
    if (token.type === "eof") {
      throw invalidEOF();
    }
    parseState = "beforePropertyValue";
  },
  beforePropertyValue() {
    if (token.type === "eof") {
      throw invalidEOF();
    }
    push();
  },
  beforeArrayValue() {
    if (token.type === "eof") {
      throw invalidEOF();
    }
    if (token.type === "punctuator" && token.value === "]") {
      pop();
      return;
    }
    push();
  },
  afterPropertyValue() {
    if (token.type === "eof") {
      throw invalidEOF();
    }
    switch (token.value) {
      case ",":
        parseState = "beforePropertyName";
        return;
      case "}":
        pop();
    }
  },
  afterArrayValue() {
    if (token.type === "eof") {
      throw invalidEOF();
    }
    switch (token.value) {
      case ",":
        parseState = "beforeArrayValue";
        return;
      case "]":
        pop();
    }
  },
  end() {
  }
};
function push() {
  let value;
  switch (token.type) {
    case "punctuator":
      switch (token.value) {
        case "{":
          value = {};
          break;
        case "[":
          value = [];
          break;
      }
      break;
    case "null":
    case "boolean":
    case "numeric":
    case "string":
      value = token.value;
      break;
  }
  if (root === void 0) {
    root = value;
  } else {
    const parent = stack[stack.length - 1];
    if (Array.isArray(parent)) {
      parent.push(value);
    } else {
      Object.defineProperty(parent, key, {
        value,
        writable: true,
        enumerable: true,
        configurable: true
      });
    }
  }
  if (value !== null && typeof value === "object") {
    stack.push(value);
    if (Array.isArray(value)) {
      parseState = "beforeArrayValue";
    } else {
      parseState = "beforePropertyName";
    }
  } else {
    const current = stack[stack.length - 1];
    if (current == null) {
      parseState = "end";
    } else if (Array.isArray(current)) {
      parseState = "afterArrayValue";
    } else {
      parseState = "afterPropertyValue";
    }
  }
}
function pop() {
  stack.pop();
  const current = stack[stack.length - 1];
  if (current == null) {
    parseState = "end";
  } else if (Array.isArray(current)) {
    parseState = "afterArrayValue";
  } else {
    parseState = "afterPropertyValue";
  }
}
function invalidChar(c2) {
  if (c2 === void 0) {
    return syntaxError(`JSON5: invalid end of input at ${line}:${column}`);
  }
  return syntaxError(`JSON5: invalid character '${formatChar(c2)}' at ${line}:${column}`);
}
function invalidEOF() {
  return syntaxError(`JSON5: invalid end of input at ${line}:${column}`);
}
function invalidIdentifier() {
  column -= 5;
  return syntaxError(`JSON5: invalid identifier character at ${line}:${column}`);
}
function separatorChar(c2) {
  console.warn(`JSON5: '${formatChar(c2)}' in strings is not valid ECMAScript; consider escaping`);
}
function formatChar(c2) {
  const replacements = {
    "'": "\\'",
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "	": "\\t",
    "\v": "\\v",
    "\0": "\\0",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029"
  };
  if (replacements[c2]) {
    return replacements[c2];
  }
  if (c2 < " ") {
    const hexString = c2.charCodeAt(0).toString(16);
    return "\\x" + ("00" + hexString).substring(hexString.length);
  }
  return c2;
}
function syntaxError(message) {
  const err = new SyntaxError(message);
  err.lineNumber = line;
  err.columnNumber = column;
  return err;
}
var stringify = function stringify2(value, replacer, space) {
  const stack2 = [];
  let indent = "";
  let propertyList;
  let replacerFunc;
  let gap = "";
  let quote;
  if (replacer != null && typeof replacer === "object" && !Array.isArray(replacer)) {
    space = replacer.space;
    quote = replacer.quote;
    replacer = replacer.replacer;
  }
  if (typeof replacer === "function") {
    replacerFunc = replacer;
  } else if (Array.isArray(replacer)) {
    propertyList = [];
    for (const v2 of replacer) {
      let item;
      if (typeof v2 === "string") {
        item = v2;
      } else if (typeof v2 === "number" || v2 instanceof String || v2 instanceof Number) {
        item = String(v2);
      }
      if (item !== void 0 && propertyList.indexOf(item) < 0) {
        propertyList.push(item);
      }
    }
  }
  if (space instanceof Number) {
    space = Number(space);
  } else if (space instanceof String) {
    space = String(space);
  }
  if (typeof space === "number") {
    if (space > 0) {
      space = Math.min(10, Math.floor(space));
      gap = "          ".substr(0, space);
    }
  } else if (typeof space === "string") {
    gap = space.substr(0, 10);
  }
  return serializeProperty("", { "": value });
  function serializeProperty(key2, holder) {
    let value2 = holder[key2];
    if (value2 != null) {
      if (typeof value2.toJSON5 === "function") {
        value2 = value2.toJSON5(key2);
      } else if (typeof value2.toJSON === "function") {
        value2 = value2.toJSON(key2);
      }
    }
    if (replacerFunc) {
      value2 = replacerFunc.call(holder, key2, value2);
    }
    if (value2 instanceof Number) {
      value2 = Number(value2);
    } else if (value2 instanceof String) {
      value2 = String(value2);
    } else if (value2 instanceof Boolean) {
      value2 = value2.valueOf();
    }
    switch (value2) {
      case null:
        return "null";
      case true:
        return "true";
      case false:
        return "false";
    }
    if (typeof value2 === "string") {
      return quoteString(value2);
    }
    if (typeof value2 === "number") {
      return String(value2);
    }
    if (typeof value2 === "object") {
      return Array.isArray(value2) ? serializeArray(value2) : serializeObject(value2);
    }
    return void 0;
  }
  function quoteString(value2) {
    const quotes = {
      "'": 0.1,
      '"': 0.2
    };
    const replacements = {
      "'": "\\'",
      '"': '\\"',
      "\\": "\\\\",
      "\b": "\\b",
      "\f": "\\f",
      "\n": "\\n",
      "\r": "\\r",
      "	": "\\t",
      "\v": "\\v",
      "\0": "\\0",
      "\u2028": "\\u2028",
      "\u2029": "\\u2029"
    };
    let product = "";
    for (let i2 = 0; i2 < value2.length; i2++) {
      const c2 = value2[i2];
      switch (c2) {
        case "'":
        case '"':
          quotes[c2]++;
          product += c2;
          continue;
        case "\0":
          if (util.isDigit(value2[i2 + 1])) {
            product += "\\x00";
            continue;
          }
      }
      if (replacements[c2]) {
        product += replacements[c2];
        continue;
      }
      if (c2 < " ") {
        let hexString = c2.charCodeAt(0).toString(16);
        product += "\\x" + ("00" + hexString).substring(hexString.length);
        continue;
      }
      product += c2;
    }
    const quoteChar = quote || Object.keys(quotes).reduce((a2, b2) => quotes[a2] < quotes[b2] ? a2 : b2);
    product = product.replace(new RegExp(quoteChar, "g"), replacements[quoteChar]);
    return quoteChar + product + quoteChar;
  }
  function serializeObject(value2) {
    if (stack2.indexOf(value2) >= 0) {
      throw TypeError("Converting circular structure to JSON5");
    }
    stack2.push(value2);
    let stepback = indent;
    indent = indent + gap;
    let keys = propertyList || Object.keys(value2);
    let partial = [];
    for (const key2 of keys) {
      const propertyString = serializeProperty(key2, value2);
      if (propertyString !== void 0) {
        let member = serializeKey(key2) + ":";
        if (gap !== "") {
          member += " ";
        }
        member += propertyString;
        partial.push(member);
      }
    }
    let final;
    if (partial.length === 0) {
      final = "{}";
    } else {
      let properties;
      if (gap === "") {
        properties = partial.join(",");
        final = "{" + properties + "}";
      } else {
        let separator = ",\n" + indent;
        properties = partial.join(separator);
        final = "{\n" + indent + properties + ",\n" + stepback + "}";
      }
    }
    stack2.pop();
    indent = stepback;
    return final;
  }
  function serializeKey(key2) {
    if (key2.length === 0) {
      return quoteString(key2);
    }
    const firstChar = String.fromCodePoint(key2.codePointAt(0));
    if (!util.isIdStartChar(firstChar)) {
      return quoteString(key2);
    }
    for (let i2 = firstChar.length; i2 < key2.length; i2++) {
      if (!util.isIdContinueChar(String.fromCodePoint(key2.codePointAt(i2)))) {
        return quoteString(key2);
      }
    }
    return key2;
  }
  function serializeArray(value2) {
    if (stack2.indexOf(value2) >= 0) {
      throw TypeError("Converting circular structure to JSON5");
    }
    stack2.push(value2);
    let stepback = indent;
    indent = indent + gap;
    let partial = [];
    for (let i2 = 0; i2 < value2.length; i2++) {
      const propertyString = serializeProperty(String(i2), value2);
      partial.push(propertyString !== void 0 ? propertyString : "null");
    }
    let final;
    if (partial.length === 0) {
      final = "[]";
    } else {
      if (gap === "") {
        let properties = partial.join(",");
        final = "[" + properties + "]";
      } else {
        let separator = ",\n" + indent;
        let properties = partial.join(separator);
        final = "[\n" + indent + properties + ",\n" + stepback + "]";
      }
    }
    stack2.pop();
    indent = stepback;
    return final;
  }
};
const JSON5 = {
  parse,
  stringify
};
var lib = JSON5;
var kMethodEvalLogs = "eval_logs";
var kMethodEvalLog = "eval_log";
var kMethodEvalLogHeaders = "eval_log_headers";
function webViewJsonRpcClient(vscode) {
  var target = {
    postMessage: function(data) {
      vscode.postMessage(data);
    },
    onMessage: function(handler) {
      var onMessage = function(ev) {
        handler(ev.data);
      };
      window.addEventListener("message", onMessage);
      return function() {
        window.removeEventListener("message", onMessage);
      };
    }
  };
  var request = jsonRpcPostMessageRequestTransport(target).request;
  return request;
}
function jsonRpcPostMessageRequestTransport(target) {
  var requests = /* @__PURE__ */ new Map();
  var disconnect = target.onMessage(function(ev) {
    var response = asJsonRpcResponse(ev);
    if (response) {
      var request = requests.get(response.id);
      if (request) {
        requests["delete"](response.id);
        if (response.error) {
          request.reject(response.error);
        } else {
          request.resolve(response.result);
        }
      }
    }
  });
  return {
    request: function(method, params) {
      return new Promise(function(resolve, reject) {
        var requestId = Math.floor(Math.random() * 1e6);
        requests.set(requestId, {
          resolve,
          reject
        });
        var request = {
          jsonrpc: kJsonRpcVersion,
          id: requestId,
          method,
          params
        };
        target.postMessage(request);
      });
    },
    disconnect
  };
}
var kJsonRpcVersion = "2.0";
function isJsonRpcMessage(message) {
  var jsMessage = message;
  return jsMessage.jsonrpc !== void 0 && jsMessage.id !== void 0;
}
function asJsonRpcMessage(data) {
  if (isJsonRpcMessage(data) && data.jsonrpc === kJsonRpcVersion) {
    return data;
  } else {
    return null;
  }
}
function asJsonRpcResponse(data) {
  var message = asJsonRpcMessage(data);
  if (message) {
    return message;
  } else {
    return null;
  }
}
const vscodeApi = window.acquireVsCodeApi ? window.acquireVsCodeApi() : void 0;
const vscodeClient = webViewJsonRpcClient(vscodeApi);
async function client_events() {
  return [];
}
async function eval_logs() {
  const response = await vscodeClient(kMethodEvalLogs, []);
  if (response) {
    const parsed = lib.parse(response);
    if (Array.isArray(parsed)) {
      return {
        log_dir: "",
        files: parsed
      };
    } else {
      return parsed;
    }
  } else {
    return void 0;
  }
}
async function eval_log(file, headerOnly, capabilities) {
  const response = await vscodeClient(kMethodEvalLog, [file, headerOnly]);
  if (response) {
    let json;
    if (capabilities.webWorkers) {
      json = await asyncJsonParse(response);
    } else {
      json = lib.parse(response);
    }
    return {
      parsed: json,
      raw: response
    };
  } else {
    return void 0;
  }
}
async function eval_log_headers(files) {
  const response = await vscodeClient(kMethodEvalLogHeaders, [files]);
  if (response) {
    return lib.parse(response);
  } else {
    return void 0;
  }
}
async function download_file(logFile) {
  vscodeApi.postMessage({ type: "openWorkspaceFile", url: logFile });
}
const vscodeApi$1 = {
  client_events,
  eval_logs,
  eval_log,
  eval_log_headers,
  download_file
};
function singleFileHttpApi() {
  const urlParams = new URLSearchParams(window.location.search);
  const fetchLogPath = urlParams.get("log_file");
  if (fetchLogPath) {
    const api2 = httpApiForFile(fetchLogPath);
    return api2;
  }
}
function httpApiForFile(logFile) {
  const getContents = async () => {
    {
      const response = await fetch(`${logFile}`, { method: "GET" });
      if (response.ok) {
        const text = await response.text();
        const log = await asyncJsonParse(text);
        if (log.version === 1) {
          if (log.results) {
            log.results.scores = [];
            log.results.scorer.scorer = log.results.scorer.name;
            log.results.scores.push(log.results.scorer);
            delete log.results.scorer;
            log.results.scores[0].metrics = log.results.metrics;
            delete log.results.metrics;
            const scorerName = log.results.scores[0].name;
            log.samples.forEach((sample) => {
              sample.scores = { [scorerName]: sample.score };
              delete sample.score;
            });
          }
        }
        return {
          parsed: log,
          raw: text
        };
      } else if (response.status !== 200) {
        const message = await response.text() || response.statusText;
        const error = new Error(`Error: ${response.status}: ${message})`);
        throw error;
      } else {
        throw new Error(`${response.status} - ${response.statusText} `);
      }
    }
  };
  return {
    client_events: async () => {
      return Promise.resolve([]);
    },
    eval_logs: async () => {
      const contents = await getContents();
      const files = [
        {
          name: logFile,
          task: contents.parsed.eval.task,
          task_id: contents.parsed.eval.task_id
        }
      ];
      return Promise.resolve({
        files
      });
    },
    eval_log: async () => {
      return await getContents();
    },
    eval_log_headers: async () => {
      const contents = await getContents();
      return Promise.resolve([contents.parsed]);
    },
    download_file: download_file$1
  };
}
const api = window.acquireVsCodeApi ? vscodeApi$1 : singleFileHttpApi() || browserApi;
const DownloadButton = ({ logFile, label, fileName, fileContents }) => {
  return m$1`<button
    class="btn btn-outline-primary"
    style=${{ fontSize: FontSize.small, marginTop: "3em" }}
    onclick=${async () => {
    await api.download_file(logFile, fileName, fileContents);
  }}
  >
    ${label}
  </button>`;
};
const DownloadPanel = ({
  message,
  buttonLabel,
  logFile,
  fileName,
  fileContents
}) => {
  return m$1`<div
    style=${{
    display: "grid",
    gridTemplateRows: "content content",
    paddingTop: "3em",
    justifyItems: "center"
  }}
  >
    <div style=${{ fontSize: FontSize.small }}>${message}</div>
    <${DownloadButton}
      label=${buttonLabel}
      logFile=${logFile}
      fileName=${fileName}
      fileContents=${fileContents}
    />
  </div>`;
};
const TaskErrorCard = ({ evalError }) => {
  return m$1`
    <${Card}>
      <${CardHeader} icon=${ApplicationIcons.error} label="Task Failed: ${evalError.message}"></${CardHeader}>
      <${CardBody} style=${{ fontSize: FontSize.smaller }}>
        <${ANSIDisplay} output=${evalError.traceback_ansi}/>
      </${CardBody}>
    </${Card}>
  `;
};
const kEvalTabId = "eval-tab";
const kJsonTabId = "json-tab";
const kInfoTabId = "plan-tab";
const kPrismRenderMaxSize = 25e4;
const kJsonMaxSize = 1e7;
const WorkSpace = (props) => {
  var _a, _b;
  const divRef = A();
  const codeRef = A();
  const workspaceLog = props.log;
  const [currentTaskId, setCurrentTaskId] = h(
    (_b = (_a = workspaceLog == null ? void 0 : workspaceLog.contents) == null ? void 0 : _a.eval) == null ? void 0 : _b.run_id
  );
  const [selectedTab, setSelectedTab] = h(kEvalTabId);
  const [scores, setScores] = h([]);
  const [score, setScore] = h(void 0);
  const [samplesDesc, setSamplesDesc] = h(void 0);
  const [filter, setFilter] = h({});
  const [epoch, setEpoch] = h("all");
  const [sort2, setSort] = h(kDefaultSort);
  const [renderedCode, setRenderedCode] = h(false);
  const afterBodyElements = [];
  const context = {
    afterBody: (el) => {
      afterBodyElements.push(el);
    }
  };
  const clearSampleTools = q(() => {
    setEpoch("all");
    setFilter({});
    setSort(kDefaultSort);
  }, [setEpoch, setFilter, setSort]);
  y(() => {
    var _a2, _b2;
    if (workspaceLog.contents && ((_a2 = workspaceLog.contents.eval) == null ? void 0 : _a2.run_id) !== currentTaskId) {
      const defaultTab = ((_b2 = workspaceLog.contents) == null ? void 0 : _b2.status) !== "error" ? kEvalTabId : kInfoTabId;
      setSelectedTab(defaultTab);
      if (divRef.current) {
        divRef.current.scrollTop = 0;
      }
    }
  }, [workspaceLog, divRef, currentTaskId, setSelectedTab]);
  y(() => {
    var _a2, _b2, _c, _d;
    const scorer = ((_b2 = (_a2 = workspaceLog == null ? void 0 : workspaceLog.contents) == null ? void 0 : _a2.results) == null ? void 0 : _b2.scores[0]) ? {
      name: workspaceLog.contents.results.scores[0].name,
      scorer: workspaceLog.contents.results.scores[0].scorer
    } : void 0;
    const scorers = (((_d = (_c = workspaceLog.contents) == null ? void 0 : _c.results) == null ? void 0 : _d.scores) || []).map((score2) => {
      return {
        name: score2.name,
        scorer: score2.scorer
      };
    }).reduce((accum, scorer2) => {
      if (!accum.find((sc) => {
        return scorer2.scorer === sc.scorer && scorer2.name === sc.name;
      })) {
        accum.push(scorer2);
      }
      return accum;
    }, []);
    setScores(scorers);
    setScore(scorer);
    clearSampleTools();
    setRenderedCode(false);
  }, [workspaceLog, setScores, setScore, setEpoch, setFilter, setRenderedCode]);
  y(() => {
    clearSampleTools();
  }, [score]);
  y(() => {
    var _a2, _b2, _c, _d;
    const sampleDescriptor = samplesDescriptor(
      score,
      scores,
      (_a2 = workspaceLog.contents) == null ? void 0 : _a2.samples,
      ((_d = (_c = (_b2 = workspaceLog.contents) == null ? void 0 : _b2.eval) == null ? void 0 : _c.config) == null ? void 0 : _d.epochs) || 1,
      context
    );
    setSamplesDesc(sampleDescriptor);
  }, [workspaceLog, score, scores, setSamplesDesc]);
  y(() => {
    var _a2, _b2;
    setCurrentTaskId((_b2 = (_a2 = workspaceLog.contents) == null ? void 0 : _a2.eval) == null ? void 0 : _b2.run_id);
  }, [workspaceLog]);
  const tabs = T(() => {
    var _a2, _b2, _c, _d, _e;
    const resolvedTabs = {};
    if (((_a2 = workspaceLog.contents) == null ? void 0 : _a2.status) !== "error") {
      resolvedTabs.samples = {
        id: kEvalTabId,
        scrollable: ((_c = (_b2 = workspaceLog.contents) == null ? void 0 : _b2.samples) == null ? void 0 : _c.length) === 1,
        label: ((_e = (_d = workspaceLog.contents) == null ? void 0 : _d.samples) == null ? void 0 : _e.length) > 1 ? "Samples" : "Sample",
        content: () => {
          var _a3, _b3, _c2, _d2, _e2;
          return m$1` <${SamplesTab}
            task=${(_b3 = (_a3 = workspaceLog.contents) == null ? void 0 : _a3.eval) == null ? void 0 : _b3.task_id}
            model=${(_d2 = (_c2 = workspaceLog.contents) == null ? void 0 : _c2.eval) == null ? void 0 : _d2.model}
            selectedScore=${score}
            setSelectedScore=${setScore}
            samples=${(_e2 = workspaceLog.contents) == null ? void 0 : _e2.samples}
            sampleDescriptor=${samplesDesc}
            filter=${filter}
            sort=${sort2}
            epoch=${epoch}
            context=${context}
          />`;
        },
        tools: () => {
          var _a3, _b3, _c2, _d2, _e2;
          if (((_b3 = (_a3 = workspaceLog.contents) == null ? void 0 : _a3.samples) == null ? void 0 : _b3.length) <= 1) {
            return "";
          }
          return m$1`<${SampleTools}
            epoch=${epoch}
            epochs=${(_e2 = (_d2 = (_c2 = workspaceLog.contents) == null ? void 0 : _c2.eval) == null ? void 0 : _d2.config) == null ? void 0 : _e2.epochs}
            setEpoch=${setEpoch}
            filter=${filter}
            filterChanged=${setFilter}
            sort=${sort2}
            setSort=${setSort}
            score=${score}
            setScore=${setScore}
            scores=${scores}
            sampleDescriptor=${samplesDesc}
          />`;
        }
      };
    }
    resolvedTabs.config = {
      id: kInfoTabId,
      label: "Info",
      scrollable: true,
      content: () => {
        var _a3, _b3, _c2;
        const infoCards = [
          m$1`<${PlanCard}
            log="${workspaceLog.contents}"
            context=${context}
          />`
        ];
        if (((_a3 = workspaceLog.contents) == null ? void 0 : _a3.status) !== "started") {
          infoCards.push(
            m$1`<${UsageCard}
              stats=${(_b3 = workspaceLog.contents) == null ? void 0 : _b3.stats}
              context=${context}
            />`
          );
        }
        if (((_c2 = workspaceLog.contents) == null ? void 0 : _c2.status) === "error") {
          infoCards.unshift(
            m$1`<${TaskErrorCard} evalError=${workspaceLog.contents.error} />`
          );
        }
        return m$1`<div style=${{ padding: "0.5em 1em 0 1em", width: "100%" }}>
          ${infoCards}
        </div>`;
      }
    };
    resolvedTabs.json = {
      id: kJsonTabId,
      label: "JSON",
      scrollable: true,
      content: () => {
        const renderedContent = [];
        if (workspaceLog.raw.length > kJsonMaxSize && props.capabilities.downloadFiles) {
          const file = `${filename(workspaceLog.name)}.json`;
          renderedContent.push(
            m$1`<${DownloadPanel}
              message="Log file raw JSON is too large to render."
              buttonLabel="Download JSON File"
              logFile=${workspaceLog.name}
              fileName=${file}
              fileContents=${workspaceLog.raw}
            />`
          );
        } else {
          if (codeRef.current && !renderedCode) {
            if (workspaceLog.raw.length < kPrismRenderMaxSize) {
              codeRef.current.innerHTML = Prism$1.highlight(
                workspaceLog.raw,
                Prism$1.languages.javascript,
                "javacript"
              );
            } else {
              const textNode = document.createTextNode(workspaceLog.raw);
              codeRef.current.innerText = "";
              codeRef.current.appendChild(textNode);
            }
            setRenderedCode(true);
          }
          renderedContent.push(
            m$1`<pre>
            <code id="task-json-contents" class="sourceCode" ref=${codeRef} style=${{
              fontSize: FontSize.small,
              whiteSpace: "pre-wrap",
              wordWrap: "anywhere"
            }}>
            </code>
          </pre>`
          );
        }
        return m$1` <div
          style=${{
          padding: "1rem",
          fontSize: FontSize.small,
          width: "100%"
        }}
        >
          ${renderedContent}
        </div>`;
      },
      tools: () => {
        if (workspaceLog.raw.length > kJsonMaxSize) {
          return [];
        } else {
          return [
            m$1`<${ToolButton}
              name=${m$1`<span class="task-btn-copy-content">Copy JSON</span>`}
              icon="${ApplicationIcons.copy}"
              classes="task-btn-json-copy clipboard-button"
              data-clipboard-target="#task-json-contents"
              onclick="${copyFeedback}"
            />`
          ];
        }
      }
    };
    return resolvedTabs;
  }, [
    samplesDesc,
    workspaceLog,
    filter,
    setFilter,
    epoch,
    setEpoch,
    sort2,
    setSort,
    renderedCode,
    setRenderedCode
  ]);
  const copyFeedback = q(
    (e2) => {
      const textEl = e2.currentTarget.querySelector(".task-btn-copy-content");
      const iconEl = e2.currentTarget.querySelector("i.bi");
      if (textEl) {
        const oldText = textEl.innerText;
        const oldIconClz = iconEl.className;
        textEl.innerText = "Copied!";
        iconEl.className = `${ApplicationIcons.confirm}`;
        setTimeout(() => {
          window.getSelection().removeAllRanges();
        }, 50);
        setTimeout(() => {
          textEl.innerText = oldText;
          iconEl.className = oldIconClz;
        }, 1250);
      }
    },
    [renderedCode]
  );
  const tabTools = Object.keys(tabs).map((key2) => {
    const tab = tabs[key2];
    return tab;
  }).filter((tab) => {
    return tab.id === selectedTab;
  }).map((tab) => {
    if (tab.tools) {
      const tools = tab.tools();
      return tools;
    } else {
      return "";
    }
  });
  return m$1`<${WorkspaceDisplay}
    divRef=${divRef}
    tabs=${tabs}
    tabTools=${tabTools}
    log=${workspaceLog}
    logs=${props.logs}
    selectedTab=${selectedTab}
    fullScreen=${props.fullScreen}
    offcanvas=${props.offcanvas}
    setSelectedTab=${setSelectedTab}
    afterBodyElements=${afterBodyElements}
  />`;
};
const WorkspaceDisplay = ({
  log,
  logs,
  selectedTab,
  tabs,
  tabTools,
  setSelectedTab,
  divRef,
  afterBodyElements,
  offcanvas
}) => {
  if (log.contents === void 0) {
    return m$1`<${EmptyPanel} />`;
  } else {
    return m$1`
    
    <${Navbar}
      file=${log.name}
      logs=${logs}
      log=${log.contents}
      offcanvas=${offcanvas}
    />    
    <div ref=${divRef} class="workspace" style=${{
      paddingTop: "0rem",
      overflowY: "hidden"
    }}>
            <div
              class="log-detail"
              style=${{
      padding: "0",
      flex: 1,
      display: "flex",
      flexDirection: "column",
      overflowY: "hidden"
    }}
            >
            <${TabSet} id="log-details" tools="${tabTools}" type="pills" styles=${{
      tabSet: {
        fontSize: FontSize.smaller,
        flexWrap: "nowrap",
        padding: "0.5em 1em 0.5em 1em",
        borderBottom: "solid 1px var(--bs-border-color)",
        background: "var(--bs-light)"
      },
      tabBody: { flex: "1", overflowY: "hidden", display: "flex" },
      tabs: {
        padding: ".3rem 0.3rem .3rem 0.3rem",
        width: "5rem",
        fontSize: FontSize.smaller,
        textTransform: "uppercase",
        borderRadius: "3px",
        fontWeight: 600
      }
    }} >
              ${Object.keys(tabs).map((key2) => {
      const tab = tabs[key2];
      return m$1`<${TabPanel}
                id=${tab.id}
                title="${tab.label}"
                onSelected=${(e2) => {
        const id = e2.currentTarget.id;
        setSelectedTab(id);
      }}
                selected=${selectedTab === tab.id}
                scrollable=${!!tab.scrollable}>
                  ${tab.content()}
                </${TabPanel}>`;
    })}
            </${TabSet}>
            </div>
          </div>
          ${afterBodyElements}`;
  }
};
const FindBand = ({ hideBand }) => {
  const searchBoxRef = A();
  y(() => {
    searchBoxRef.current.focus();
  }, []);
  const searchTerm = () => {
    return searchBoxRef.current.value;
  };
  const search = (term, back) => {
    const parentExpandablePanel = (selection) => {
      let node = selection.anchorNode;
      let expandablePanelEl = void 0;
      while (node) {
        if (node.classList && node.classList.contains("expandable-panel")) {
          expandablePanelEl = node;
          break;
        }
        node = node.parentElement;
      }
      return expandablePanelEl;
    };
    const focusedElement = document.activeElement;
    const result = window.find(term, false, !!back, false, false, true, false);
    const noResultEl = window.document.getElementById(
      "inspect-find-no-results"
    );
    if (result) {
      noResultEl.style.opacity = 0;
      const selection = window.getSelection();
      if (selection.rangeCount > 0) {
        const parentPanel = parentExpandablePanel(selection);
        if (parentPanel) {
          parentPanel.style.display = "block";
          parentPanel.style["-webkit-line-clamp"] = "";
          parentPanel.style["-webkit-box-orient"] = "";
        }
        const range = selection.getRangeAt(0);
        setTimeout(() => {
          const element = range.startContainer.parentElement;
          element.scrollIntoView({
            behavior: "smooth",
            // Optional: adds a smooth scrolling animation
            block: "center"
            // Optional: scrolls so the element is centered in the view
          });
        }, 100);
      }
    } else {
      noResultEl.style.opacity = 1;
    }
    if (focusedElement) {
      focusedElement.focus();
    }
  };
  return m$1`<div
    style=${{
    position: "absolute",
    top: 0,
    right: 0,
    marginRight: "20%",
    zIndex: "1050",
    color: "var(--inspect-find-foreground)",
    backgroundColor: "var(--inspect-find-background)",
    fontSize: "0.9rem",
    display: "grid",
    gridTemplateColumns: "auto auto auto auto auto",
    columnGap: "0.2em",
    padding: "0.2rem",
    borderBottom: "solid 1px var(--bs-light-border-subtle)",
    borderLeft: "solid 1px var(--bs-light-border-subtle)",
    borderRight: "solid 1px var(--bs-light-border-subtle)",
    boxShadow: "var(--bs-box-shadow)"
  }}
  >
    <input
      type="text"
      ref=${searchBoxRef}
      style=${{
    height: "2em",
    fontSize: "0.9em",
    margin: "0.1rem",
    outline: "none",
    border: "solid 1px var(--inspect-input-border)",
    color: "var(--inspect-input-foreground)",
    background: "var(--inspect-input-background)"
  }}
      placeholder="Find"
      onkeydown=${(e2) => {
    if (e2.key === "Escape") {
      hideBand();
    } else if (e2.key === "Enter") {
      search(searchTerm());
    }
  }}
    />
    <span
      id="inspect-find-no-results"
      style=${{
    fontSize: FontSize.base,
    opacity: 0,
    marginTop: "auto",
    marginBottom: "auto",
    marginRight: "0.5em"
  }}
      >No results</span
    >
    <button
      title="Previous match"
      style=${{ padding: 0, fontSize: FontSize.larger }}
      class="btn"
      onclick=${() => {
    search(searchTerm(), true);
  }}
    >
      <i class=${ApplicationIcons.arrows.up}></i>
    </button>
    <button
      title="Next match"
      style=${{ padding: 0, fontSize: FontSize.larger }}
      class="btn"
      onclick=${() => {
    search(searchTerm());
  }}
    >
      <i class=${ApplicationIcons.arrows.down}></i>
    </button>
    <button
      title="Close"
      style=${{
    padding: 0,
    fontSize: FontSize["title-secondary"],
    marginTop: "-0.1rem",
    marginBottom: "-0.1rem"
  }}
      class="btn"
      onclick=${() => hideBand()}
    >
      <i class=${ApplicationIcons.close}></i>
    </button>
  </div>`;
};
function App({ api: api2, pollForLogs = true }) {
  const [selected, setSelected] = h(-1);
  const [pendingLog, setPendingLog] = h(void 0);
  const [logs, setLogs] = h({ log_dir: "", files: [] });
  const [logHeaders, setLogHeaders] = h({});
  const [offcanvas, setOffcanvas] = h(false);
  const [currentLog, setCurrentLog] = h({
    contents: void 0,
    name: void 0,
    raw: void 0
  });
  const [status, setStatus] = h({
    loading: true,
    error: void 0
  });
  const [headersLoading, setHeadersLoading] = h(false);
  const [capabilities, setCapabilities] = h({
    downloadFiles: true,
    webWorkers: true
  });
  const [showFind, setShowFind] = h(false);
  const mainAppRef = A();
  y(async () => {
    setHeadersLoading(true);
    const chunkSize = 12;
    const fileLists = [];
    for (let i2 = 0; i2 < logs.files.length; i2 += chunkSize) {
      let chunk = logs.files.slice(i2, i2 + chunkSize).map((log) => {
        return log.name;
      });
      fileLists.push(chunk);
    }
    try {
      for (const fileList of fileLists) {
        const headers = await api2.eval_log_headers(fileList);
        setLogHeaders((prev) => {
          const updatedHeaders = {};
          headers.forEach((header, index) => {
            const logFile = fileList[index];
            updatedHeaders[logFile] = header;
          });
          return { ...prev, ...updatedHeaders };
        });
        await sleep(5e3);
      }
    } catch (e2) {
      console.log(e2);
      setStatus({ loading: false, error: e2 });
    }
    setHeadersLoading(false);
  }, [logs, setStatus, setLogHeaders, setHeadersLoading]);
  const filteredLogs = T(() => {
    const notRunning = Object.keys(logHeaders).filter((key2) => {
      return logHeaders[key2].status !== "started";
    });
    const files = logs.files.filter((file) => {
      return notRunning.includes(file.name);
    });
    return {
      log_dir: logs.log_dir,
      files
    };
  }, [logHeaders, logs]);
  y(async () => {
    const targetLog = filteredLogs.files[selected];
    if (targetLog && (!currentLog || currentLog.name !== targetLog.name)) {
      try {
        setStatus({ loading: true, error: void 0 });
        const logContents = await api2.eval_log(
          targetLog.name,
          false,
          capabilities
        );
        if (logContents) {
          const log = logContents.parsed;
          setCurrentLog({
            contents: log,
            name: targetLog.name,
            raw: logContents.raw
          });
          setStatus({ loading: false, error: void 0 });
        }
      } catch (e2) {
        console.log(e2);
        setStatus({ loading: false, error: e2 });
      }
    }
  }, [
    selected,
    filteredLogs,
    capabilities,
    currentLog,
    setCurrentLog,
    setStatus
  ]);
  const loadLogsImpl = q(async () => {
    try {
      const result = await api2.eval_logs();
      if (result) {
        setLogs(result);
      } else {
        setLogs({ log_dir: "", files: [] });
      }
    } catch (e2) {
      console.log(e2);
      setStatus({ loading: false, error: e2 });
    }
  }, []);
  const loadLogs = q(
    throttle(() => {
      loadLogsImpl();
    }, 5e3),
    [loadLogsImpl]
  );
  y(async () => {
    if (pendingLog) {
      const index = filteredLogs.files.findIndex((val) => {
        return pendingLog.endsWith(val.name);
      });
      if (index > -1) {
        setSelected(index);
        setPendingLog(void 0);
      } else {
        if (!logs.files.find((val) => {
          return pendingLog.endsWith(val.name);
        })) {
          await loadLogs();
        }
      }
    }
  }, [pendingLog, filteredLogs, setSelected, setPendingLog, loadLogs]);
  const onMessage = T(() => {
    return async (e2) => {
      const type = e2.data.type || e2.data.message;
      switch (type) {
        case "updateState": {
          if (e2.data.url) {
            const decodedUrl = decodeURIComponent(e2.data.url);
            setPendingLog(decodedUrl);
          }
        }
      }
    };
  }, [setPendingLog]);
  y(() => {
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
    };
  }, [onMessage]);
  y(async () => {
    const urlParams = new URLSearchParams(window.location.search);
    const bodyEl = document.querySelector("body");
    const isVSCode = !!bodyEl.getAttributeNames().find((attr) => {
      return attr.includes("data-vscode-");
    });
    const extensionVersionEl = document.querySelector(
      'meta[name="inspect-extension:version"]'
    );
    const extensionVersion = extensionVersionEl ? extensionVersionEl.getAttribute("content") : void 0;
    if (isVSCode) {
      if (!extensionVersion) {
        setCapabilities({ downloadFiles: false, webWorkers: false });
      }
    }
    setOffcanvas(true);
    const logPath = urlParams.get("task_file");
    const load = logPath ? async () => {
      setLogs({
        log_dir: "",
        files: [{ name: logPath }]
      });
    } : loadLogs;
    const embeddedState = document.getElementById("logview-state");
    if (embeddedState) {
      const state = JSON.parse(embeddedState.textContent);
      onMessage({ data: state });
    } else {
      await load();
    }
    if (selected === -1 && !embeddedState) {
      setSelected(0);
    }
    new ClipboardJS(".clipboard-button,.copy-button");
    if (pollForLogs) {
      setInterval(() => {
        api2.client_events().then(async (events) => {
          if (events.includes("reload")) {
            window.location.reload(true);
          }
          if (events.includes("refresh-evals")) {
            await load();
            setSelected(0);
          }
        });
      }, 1e3);
    }
  }, []);
  const fullScreen = filteredLogs.files.length === 1 && !filteredLogs.log_dir;
  const sidebar = !fullScreen && currentLog.contents ? m$1`
          <${Sidebar}
            logs=${filteredLogs}
            logHeaders=${logHeaders}
            loading=${headersLoading}
            offcanvas=${offcanvas}
            selectedIndex=${selected}
            onSelectedIndexChanged=${(index) => {
    setSelected(index);
    var myOffcanvas = document.getElementById("sidebarOffCanvas");
    var bsOffcanvas = Offcanvas.getInstance(myOffcanvas);
    if (bsOffcanvas) {
      bsOffcanvas.hide();
    }
  }}
          />
        ` : "";
  const workspace = T(() => {
    if (status.error) {
      return m$1`<${ErrorPanel}
        title="An error occurred while loading this task."
        error=${status.error}
      />`;
    } else {
      return m$1` <${WorkSpace}
        logs=${filteredLogs}
        log=${currentLog}
        selected=${selected}
        fullScreen=${fullScreen}
        offcanvas=${offcanvas}
        capabilities=${capabilities}
        showFind=${showFind}
        setShowFind=${setShowFind}
      />`;
    }
  }, [logs, currentLog, selected, fullScreen, offcanvas, status]);
  const fullScreenClz = fullScreen ? " full-screen" : "";
  const offcanvasClz = offcanvas ? " off-canvas" : "";
  const hideFind = q(() => {
    clearDocumentSelection();
    if (showFind) {
      setShowFind(false);
    }
  }, [showFind, setShowFind]);
  return m$1`
    <${AppErrorBoundary}>
    ${sidebar}
    <div ref=${mainAppRef} class="app-main-grid${fullScreenClz}${offcanvasClz}" tabIndex="0" onKeyDown=${(e2) => {
    if (!window.acquireVsCodeApi) {
      return;
    }
    if ((e2.ctrlKey || e2.metaKey) && e2.key === "f") {
      setShowFind(true);
    } else if (e2.key === "Escape") {
      hideFind();
    }
  }}>
      ${showFind ? m$1`<${FindBand} hideBand=${hideFind} />` : ""}
      <${ProgressBar} animating=${status.loading} />
      ${workspace}
    </div>
    </${AppErrorBoundary}>
  `;
}
B$1(m$1`<${App} api=${api} />`, document.getElementById("app"));
//# sourceMappingURL=index.js.map
