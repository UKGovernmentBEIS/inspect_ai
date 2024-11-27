var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key2, value) => key2 in obj ? __defProp(obj, key2, { enumerable: true, configurable: true, writable: true, value }) : obj[key2] = value;
var __publicField = (obj, key2, value) => __defNormalProp(obj, typeof key2 !== "symbol" ? key2 + "" : key2, value);
(function polyfill() {
  const relList = document.createElement("link").relList;
  if (relList && relList.supports && relList.supports("modulepreload")) {
    return;
  }
  for (const link2 of document.querySelectorAll('link[rel="modulepreload"]')) {
    processPreload(link2);
  }
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type !== "childList") {
        continue;
      }
      for (const node of mutation.addedNodes) {
        if (node.tagName === "LINK" && node.rel === "modulepreload") processPreload(node);
      }
    }
  }).observe(document, {
    childList: true,
    subtree: true
  });
  function getFetchOpts(link2) {
    const fetchOpts = {};
    if (link2.integrity) fetchOpts.integrity = link2.integrity;
    if (link2.referrerPolicy) fetchOpts.referrerPolicy = link2.referrerPolicy;
    if (link2.crossOrigin === "use-credentials") fetchOpts.credentials = "include";
    else if (link2.crossOrigin === "anonymous") fetchOpts.credentials = "omit";
    else fetchOpts.credentials = "same-origin";
    return fetchOpts;
  }
  function processPreload(link2) {
    if (link2.ep) return;
    link2.ep = true;
    const fetchOpts = getFetchOpts(link2);
    fetch(link2.href, fetchOpts);
  }
})();
var n$2, l$1, u$1, i$2, o$1, r$2, f$1, e$3, c$2, s$1, h$1 = {}, v$1 = [], p$1 = /acit|ex(?:s|g|n|p|$)|rph|grid|ows|mnc|ntw|ine[ch]|zoo|^ord|itera/i, y$1 = Array.isArray;
function d$1(n2, l2) {
  for (var u2 in l2) n2[u2] = l2[u2];
  return n2;
}
function w$1(n2) {
  n2 && n2.parentNode && n2.parentNode.removeChild(n2);
}
function _(l2, u2, t2) {
  var i, o2, r2, f2 = {};
  for (r2 in u2) "key" == r2 ? i = u2[r2] : "ref" == r2 ? o2 = u2[r2] : f2[r2] = u2[r2];
  if (arguments.length > 2 && (f2.children = arguments.length > 3 ? n$2.call(arguments, 2) : t2), "function" == typeof l2 && null != l2.defaultProps) for (r2 in l2.defaultProps) void 0 === f2[r2] && (f2[r2] = l2.defaultProps[r2]);
  return g(l2, f2, i, o2, null);
}
function g(n2, t2, i, o2, r2) {
  var f2 = { type: n2, props: t2, key: i, ref: o2, __k: null, __: null, __b: 0, __e: null, __d: void 0, __c: null, constructor: void 0, __v: null == r2 ? ++u$1 : r2, __i: -1, __u: 0 };
  return null == r2 && null != l$1.vnode && l$1.vnode(f2), f2;
}
function m$2() {
  return { current: null };
}
function b(n2) {
  return n2.children;
}
function k$1(n2, l2) {
  this.props = n2, this.context = l2;
}
function x$1(n2, l2) {
  if (null == l2) return n2.__ ? x$1(n2.__, n2.__i + 1) : null;
  for (var u2; l2 < n2.__k.length; l2++) if (null != (u2 = n2.__k[l2]) && null != u2.__e) return u2.__e;
  return "function" == typeof n2.type ? x$1(n2) : null;
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
function S(n2) {
  (!n2.__d && (n2.__d = true) && i$2.push(n2) && !M.__r++ || o$1 !== l$1.debounceRendering) && ((o$1 = l$1.debounceRendering) || r$2)(M);
}
function M() {
  var n2, u2, t2, o2, r2, e2, c2, s2;
  for (i$2.sort(f$1); n2 = i$2.shift(); ) n2.__d && (u2 = i$2.length, o2 = void 0, e2 = (r2 = (t2 = n2).__v).__e, c2 = [], s2 = [], t2.__P && ((o2 = d$1({}, r2)).__v = r2.__v + 1, l$1.vnode && l$1.vnode(o2), O(t2.__P, o2, r2, t2.__n, t2.__P.namespaceURI, 32 & r2.__u ? [e2] : null, c2, null == e2 ? x$1(r2) : e2, !!(32 & r2.__u), s2), o2.__v = r2.__v, o2.__.__k[o2.__i] = o2, j$1(c2, o2, s2), o2.__e != e2 && C$1(o2)), i$2.length > u2 && i$2.sort(f$1));
  M.__r = 0;
}
function P$1(n2, l2, u2, t2, i, o2, r2, f2, e2, c2, s2) {
  var a2, p2, y2, d2, w2, _2 = t2 && t2.__k || v$1, g2 = l2.length;
  for (u2.__d = e2, $(u2, l2, _2), e2 = u2.__d, a2 = 0; a2 < g2; a2++) null != (y2 = u2.__k[a2]) && (p2 = -1 === y2.__i ? h$1 : _2[y2.__i] || h$1, y2.__i = a2, O(n2, y2, p2, i, o2, r2, f2, e2, c2, s2), d2 = y2.__e, y2.ref && p2.ref != y2.ref && (p2.ref && E(p2.ref, null, y2), s2.push(y2.ref, y2.__c || d2, y2)), null == w2 && null != d2 && (w2 = d2), 65536 & y2.__u || p2.__k === y2.__k ? e2 = I(y2, e2, n2) : "function" == typeof y2.type && void 0 !== y2.__d ? e2 = y2.__d : d2 && (e2 = d2.nextSibling), y2.__d = void 0, y2.__u &= -196609);
  u2.__d = e2, u2.__e = w2;
}
function $(n2, l2, u2) {
  var t2, i, o2, r2, f2, e2 = l2.length, c2 = u2.length, s2 = c2, a2 = 0;
  for (n2.__k = [], t2 = 0; t2 < e2; t2++) null != (i = l2[t2]) && "boolean" != typeof i && "function" != typeof i ? (r2 = t2 + a2, (i = n2.__k[t2] = "string" == typeof i || "number" == typeof i || "bigint" == typeof i || i.constructor == String ? g(null, i, null, null, null) : y$1(i) ? g(b, { children: i }, null, null, null) : void 0 === i.constructor && i.__b > 0 ? g(i.type, i.props, i.key, i.ref ? i.ref : null, i.__v) : i).__ = n2, i.__b = n2.__b + 1, o2 = null, -1 !== (f2 = i.__i = L(i, u2, r2, s2)) && (s2--, (o2 = u2[f2]) && (o2.__u |= 131072)), null == o2 || null === o2.__v ? (-1 == f2 && a2--, "function" != typeof i.type && (i.__u |= 65536)) : f2 !== r2 && (f2 == r2 - 1 ? a2-- : f2 == r2 + 1 ? a2++ : (f2 > r2 ? a2-- : a2++, i.__u |= 65536))) : i = n2.__k[t2] = null;
  if (s2) for (t2 = 0; t2 < c2; t2++) null != (o2 = u2[t2]) && 0 == (131072 & o2.__u) && (o2.__e == n2.__d && (n2.__d = x$1(o2)), N(o2, o2));
}
function I(n2, l2, u2) {
  var t2, i;
  if ("function" == typeof n2.type) {
    for (t2 = n2.__k, i = 0; t2 && i < t2.length; i++) t2[i] && (t2[i].__ = n2, l2 = I(t2[i], l2, u2));
    return l2;
  }
  n2.__e != l2 && (l2 && n2.type && !u2.contains(l2) && (l2 = x$1(n2)), u2.insertBefore(n2.__e, l2 || null), l2 = n2.__e);
  do {
    l2 = l2 && l2.nextSibling;
  } while (null != l2 && 8 === l2.nodeType);
  return l2;
}
function L(n2, l2, u2, t2) {
  var i = n2.key, o2 = n2.type, r2 = u2 - 1, f2 = u2 + 1, e2 = l2[u2];
  if (null === e2 || e2 && i == e2.key && o2 === e2.type && 0 == (131072 & e2.__u)) return u2;
  if (("function" != typeof o2 || o2 === b || i) && t2 > (null != e2 && 0 == (131072 & e2.__u) ? 1 : 0)) for (; r2 >= 0 || f2 < l2.length; ) {
    if (r2 >= 0) {
      if ((e2 = l2[r2]) && 0 == (131072 & e2.__u) && i == e2.key && o2 === e2.type) return r2;
      r2--;
    }
    if (f2 < l2.length) {
      if ((e2 = l2[f2]) && 0 == (131072 & e2.__u) && i == e2.key && o2 === e2.type) return f2;
      f2++;
    }
  }
  return -1;
}
function T$1(n2, l2, u2) {
  "-" === l2[0] ? n2.setProperty(l2, null == u2 ? "" : u2) : n2[l2] = null == u2 ? "" : "number" != typeof u2 || p$1.test(l2) ? u2 : u2 + "px";
}
function A$1(n2, l2, u2, t2, i) {
  var o2;
  n: if ("style" === l2) if ("string" == typeof u2) n2.style.cssText = u2;
  else {
    if ("string" == typeof t2 && (n2.style.cssText = t2 = ""), t2) for (l2 in t2) u2 && l2 in u2 || T$1(n2.style, l2, "");
    if (u2) for (l2 in u2) t2 && u2[l2] === t2[l2] || T$1(n2.style, l2, u2[l2]);
  }
  else if ("o" === l2[0] && "n" === l2[1]) o2 = l2 !== (l2 = l2.replace(/(PointerCapture)$|Capture$/i, "$1")), l2 = l2.toLowerCase() in n2 || "onFocusOut" === l2 || "onFocusIn" === l2 ? l2.toLowerCase().slice(2) : l2.slice(2), n2.l || (n2.l = {}), n2.l[l2 + o2] = u2, u2 ? t2 ? u2.u = t2.u : (u2.u = e$3, n2.addEventListener(l2, o2 ? s$1 : c$2, o2)) : n2.removeEventListener(l2, o2 ? s$1 : c$2, o2);
  else {
    if ("http://www.w3.org/2000/svg" == i) l2 = l2.replace(/xlink(H|:h)/, "h").replace(/sName$/, "s");
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
      return l$1.event && (u2 = l$1.event(u2)), "handleEvent" in t2 ? t2.handleEvent(u2) : t2(u2);
    }
  };
}
function O(n2, u2, t2, i, o2, r2, f2, e2, c2, s2) {
  var a2, h2, v2, p2, w2, _2, g2, m2, x, C2, S2, M2, $2, I2, H, L2, T2 = u2.type;
  if (void 0 !== u2.constructor) return null;
  128 & t2.__u && (c2 = !!(32 & t2.__u), r2 = [e2 = u2.__e = t2.__e]), (a2 = l$1.__b) && a2(u2);
  n: if ("function" == typeof T2) try {
    if (m2 = u2.props, x = "prototype" in T2 && T2.prototype.render, C2 = (a2 = T2.contextType) && i[a2.__c], S2 = a2 ? C2 ? C2.props.value : a2.__ : i, t2.__c ? g2 = (h2 = u2.__c = t2.__c).__ = h2.__E : (x ? u2.__c = h2 = new T2(m2, S2) : (u2.__c = h2 = new k$1(m2, S2), h2.constructor = T2, h2.render = V), C2 && C2.sub(h2), h2.props = m2, h2.state || (h2.state = {}), h2.context = S2, h2.__n = i, v2 = h2.__d = true, h2.__h = [], h2._sb = []), x && null == h2.__s && (h2.__s = h2.state), x && null != T2.getDerivedStateFromProps && (h2.__s == h2.state && (h2.__s = d$1({}, h2.__s)), d$1(h2.__s, T2.getDerivedStateFromProps(m2, h2.__s))), p2 = h2.props, w2 = h2.state, h2.__v = u2, v2) x && null == T2.getDerivedStateFromProps && null != h2.componentWillMount && h2.componentWillMount(), x && null != h2.componentDidMount && h2.__h.push(h2.componentDidMount);
    else {
      if (x && null == T2.getDerivedStateFromProps && m2 !== p2 && null != h2.componentWillReceiveProps && h2.componentWillReceiveProps(m2, S2), !h2.__e && (null != h2.shouldComponentUpdate && false === h2.shouldComponentUpdate(m2, h2.__s, S2) || u2.__v === t2.__v)) {
        for (u2.__v !== t2.__v && (h2.props = m2, h2.state = h2.__s, h2.__d = false), u2.__e = t2.__e, u2.__k = t2.__k, u2.__k.some(function(n3) {
          n3 && (n3.__ = u2);
        }), M2 = 0; M2 < h2._sb.length; M2++) h2.__h.push(h2._sb[M2]);
        h2._sb = [], h2.__h.length && f2.push(h2);
        break n;
      }
      null != h2.componentWillUpdate && h2.componentWillUpdate(m2, h2.__s, S2), x && null != h2.componentDidUpdate && h2.__h.push(function() {
        h2.componentDidUpdate(p2, w2, _2);
      });
    }
    if (h2.context = S2, h2.props = m2, h2.__P = n2, h2.__e = false, $2 = l$1.__r, I2 = 0, x) {
      for (h2.state = h2.__s, h2.__d = false, $2 && $2(u2), a2 = h2.render(h2.props, h2.state, h2.context), H = 0; H < h2._sb.length; H++) h2.__h.push(h2._sb[H]);
      h2._sb = [];
    } else do {
      h2.__d = false, $2 && $2(u2), a2 = h2.render(h2.props, h2.state, h2.context), h2.state = h2.__s;
    } while (h2.__d && ++I2 < 25);
    h2.state = h2.__s, null != h2.getChildContext && (i = d$1(d$1({}, i), h2.getChildContext())), x && !v2 && null != h2.getSnapshotBeforeUpdate && (_2 = h2.getSnapshotBeforeUpdate(p2, w2)), P$1(n2, y$1(L2 = null != a2 && a2.type === b && null == a2.key ? a2.props.children : a2) ? L2 : [L2], u2, t2, i, o2, r2, f2, e2, c2, s2), h2.base = u2.__e, u2.__u &= -161, h2.__h.length && f2.push(h2), g2 && (h2.__E = h2.__ = null);
  } catch (n3) {
    if (u2.__v = null, c2 || null != r2) {
      for (u2.__u |= c2 ? 160 : 128; e2 && 8 === e2.nodeType && e2.nextSibling; ) e2 = e2.nextSibling;
      r2[r2.indexOf(e2)] = null, u2.__e = e2;
    } else u2.__e = t2.__e, u2.__k = t2.__k;
    l$1.__e(n3, u2, t2);
  }
  else null == r2 && u2.__v === t2.__v ? (u2.__k = t2.__k, u2.__e = t2.__e) : u2.__e = z$1(t2.__e, u2, t2, i, o2, r2, f2, c2, s2);
  (a2 = l$1.diffed) && a2(u2);
}
function j$1(n2, u2, t2) {
  u2.__d = void 0;
  for (var i = 0; i < t2.length; i++) E(t2[i], t2[++i], t2[++i]);
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
function z$1(u2, t2, i, o2, r2, f2, e2, c2, s2) {
  var a2, v2, p2, d2, _2, g2, m2, b2 = i.props, k2 = t2.props, C2 = t2.type;
  if ("svg" === C2 ? r2 = "http://www.w3.org/2000/svg" : "math" === C2 ? r2 = "http://www.w3.org/1998/Math/MathML" : r2 || (r2 = "http://www.w3.org/1999/xhtml"), null != f2) {
    for (a2 = 0; a2 < f2.length; a2++) if ((_2 = f2[a2]) && "setAttribute" in _2 == !!C2 && (C2 ? _2.localName === C2 : 3 === _2.nodeType)) {
      u2 = _2, f2[a2] = null;
      break;
    }
  }
  if (null == u2) {
    if (null === C2) return document.createTextNode(k2);
    u2 = document.createElementNS(r2, C2, k2.is && k2), c2 && (l$1.__m && l$1.__m(t2, f2), c2 = false), f2 = null;
  }
  if (null === C2) b2 === k2 || c2 && u2.data === k2 || (u2.data = k2);
  else {
    if (f2 = f2 && n$2.call(u2.childNodes), b2 = i.props || h$1, !c2 && null != f2) for (b2 = {}, a2 = 0; a2 < u2.attributes.length; a2++) b2[(_2 = u2.attributes[a2]).name] = _2.value;
    for (a2 in b2) if (_2 = b2[a2], "children" == a2) ;
    else if ("dangerouslySetInnerHTML" == a2) p2 = _2;
    else if (!(a2 in k2)) {
      if ("value" == a2 && "defaultValue" in k2 || "checked" == a2 && "defaultChecked" in k2) continue;
      A$1(u2, a2, null, _2, r2);
    }
    for (a2 in k2) _2 = k2[a2], "children" == a2 ? d2 = _2 : "dangerouslySetInnerHTML" == a2 ? v2 = _2 : "value" == a2 ? g2 = _2 : "checked" == a2 ? m2 = _2 : c2 && "function" != typeof _2 || b2[a2] === _2 || A$1(u2, a2, _2, b2[a2], r2);
    if (v2) c2 || p2 && (v2.__html === p2.__html || v2.__html === u2.innerHTML) || (u2.innerHTML = v2.__html), t2.__k = [];
    else if (p2 && (u2.innerHTML = ""), P$1(u2, y$1(d2) ? d2 : [d2], t2, i, o2, "foreignObject" === C2 ? "http://www.w3.org/1999/xhtml" : r2, f2, e2, f2 ? f2[0] : i.__k && x$1(i, 0), c2, s2), null != f2) for (a2 = f2.length; a2--; ) w$1(f2[a2]);
    c2 || (a2 = "value", "progress" === C2 && null == g2 ? u2.removeAttribute("value") : void 0 !== g2 && (g2 !== u2[a2] || "progress" === C2 && !g2 || "option" === C2 && g2 !== b2[a2]) && A$1(u2, a2, g2, b2[a2], r2), a2 = "checked", void 0 !== m2 && m2 !== u2[a2] && A$1(u2, a2, m2, b2[a2], r2));
  }
  return u2;
}
function E(n2, u2, t2) {
  try {
    if ("function" == typeof n2) {
      var i = "function" == typeof n2.__u;
      i && n2.__u(), i && null == u2 || (n2.__u = n2(u2));
    } else n2.current = u2;
  } catch (n3) {
    l$1.__e(n3, t2);
  }
}
function N(n2, u2, t2) {
  var i, o2;
  if (l$1.unmount && l$1.unmount(n2), (i = n2.ref) && (i.current && i.current !== n2.__e || E(i, null, u2)), null != (i = n2.__c)) {
    if (i.componentWillUnmount) try {
      i.componentWillUnmount();
    } catch (n3) {
      l$1.__e(n3, u2);
    }
    i.base = i.__P = null;
  }
  if (i = n2.__k) for (o2 = 0; o2 < i.length; o2++) i[o2] && N(i[o2], u2, t2 || "function" != typeof n2.type);
  t2 || w$1(n2.__e), n2.__c = n2.__ = n2.__e = n2.__d = void 0;
}
function V(n2, l2, u2) {
  return this.constructor(n2, u2);
}
function q$1(u2, t2, i) {
  var o2, r2, f2, e2;
  l$1.__ && l$1.__(u2, t2), r2 = (o2 = "function" == typeof i) ? null : t2.__k, f2 = [], e2 = [], O(t2, u2 = (!o2 && i || t2).__k = _(b, null, [u2]), r2 || h$1, h$1, t2.namespaceURI, !o2 && i ? [i] : r2 ? null : t2.firstChild ? n$2.call(t2.childNodes) : null, f2, !o2 && i ? i : r2 ? r2.__e : t2.firstChild, o2, e2), j$1(f2, u2, e2);
}
n$2 = v$1.slice, l$1 = { __e: function(n2, l2, u2, t2) {
  for (var i, o2, r2; l2 = l2.__; ) if ((i = l2.__c) && !i.__) try {
    if ((o2 = i.constructor) && null != o2.getDerivedStateFromError && (i.setState(o2.getDerivedStateFromError(n2)), r2 = i.__d), null != i.componentDidCatch && (i.componentDidCatch(n2, t2 || {}), r2 = i.__d), r2) return i.__E = i;
  } catch (l3) {
    n2 = l3;
  }
  throw n2;
} }, u$1 = 0, k$1.prototype.setState = function(n2, l2) {
  var u2;
  u2 = null != this.__s && this.__s !== this.state ? this.__s : this.__s = d$1({}, this.state), "function" == typeof n2 && (n2 = n2(d$1({}, u2), this.props)), n2 && d$1(u2, n2), null != n2 && this.__v && (l2 && this._sb.push(l2), S(this));
}, k$1.prototype.forceUpdate = function(n2) {
  this.__v && (this.__e = true, n2 && this.__h.push(n2), S(this));
}, k$1.prototype.render = b, i$2 = [], r$2 = "function" == typeof Promise ? Promise.prototype.then.bind(Promise.resolve()) : setTimeout, f$1 = function(n2, l2) {
  return n2.__v.__b - l2.__v.__b;
}, M.__r = 0, e$3 = 0, c$2 = F(false), s$1 = F(true);
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
function getDefaultExportFromCjs(x) {
  return x && x.__esModule && Object.prototype.hasOwnProperty.call(x, "default") ? x["default"] : x;
}
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
        encode: function encode2(tokens) {
          if (tokens instanceof Token2) {
            return new Token2(tokens.type, encode2(tokens.content), tokens.alias);
          } else if (Array.isArray(tokens)) {
            return tokens.map(encode2);
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
        clone: function deepClone(o2, visited) {
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
                  clone2[key2] = deepClone(o2[key2], visited);
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
              o2.forEach(function(v2, i) {
                clone2[i] = deepClone(v2, visited);
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
          } catch (err2) {
            var src = (/at [^(\r\n]*\((.*):[^:]+:[^:]+\)$/i.exec(err2.stack) || [])[1];
            if (src) {
              var scripts = document.getElementsByTagName("script");
              for (var i in scripts) {
                if (scripts[i].src == src) {
                  return scripts[i];
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
          for (var i in o2) {
            if (o2.hasOwnProperty(i)) {
              callback.call(o2, i, o2[i], type || i);
              var property = o2[i];
              var propertyType = _2.util.type(property);
              if (propertyType === "Object" && !visited[objId(property)]) {
                visited[objId(property)] = true;
                DFS(property, callback, null, visited);
              } else if (propertyType === "Array" && !visited[objId(property)]) {
                visited[objId(property)] = true;
                DFS(property, callback, i, visited);
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
        for (var i = 0, element; element = env.elements[i++]; ) {
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
        var code2 = element.textContent;
        var env = {
          element,
          language,
          grammar,
          code: code2
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
      highlight: function(text2, grammar, language) {
        var env = {
          code: text2,
          grammar,
          language
        };
        _2.hooks.run("before-tokenize", env);
        if (!env.grammar) {
          throw new Error('The language "' + env.language + '" has no grammar.');
        }
        env.tokens = _2.tokenize(env.code, env.grammar);
        _2.hooks.run("after-tokenize", env);
        return Token2.stringify(_2.util.encode(env.tokens), env.language);
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
      tokenize: function(text2, grammar) {
        var rest = grammar.rest;
        if (rest) {
          for (var token2 in rest) {
            grammar[token2] = rest[token2];
          }
          delete grammar.rest;
        }
        var tokenList = new LinkedList();
        addAfter(tokenList, tokenList.head, text2);
        matchGrammar(text2, tokenList, grammar, tokenList.head, 0);
        return toArray2(tokenList);
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
          for (var i = 0, callback; callback = callbacks[i++]; ) {
            callback(env);
          }
        }
      },
      Token: Token2
    };
    _self2.Prism = _2;
    function Token2(type, content, alias, matchedStr) {
      this.type = type;
      this.content = content;
      this.alias = alias;
      this.length = (matchedStr || "").length | 0;
    }
    Token2.stringify = function stringify3(o2, language) {
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
    function matchPattern(pattern, pos2, text2, lookbehind) {
      pattern.lastIndex = pos2;
      var match2 = pattern.exec(text2);
      if (match2 && lookbehind && match2[1]) {
        var lookbehindLength = match2[1].length;
        match2.index += lookbehindLength;
        match2[0] = match2[0].slice(lookbehindLength);
      }
      return match2;
    }
    function matchGrammar(text2, tokenList, grammar, startNode, startPos, rematch) {
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
            if (tokenList.length > text2.length) {
              return;
            }
            if (str instanceof Token2) {
              continue;
            }
            var removeCount = 1;
            var match2;
            if (greedy) {
              match2 = matchPattern(pattern, pos2, text2, lookbehind);
              if (!match2 || match2.index >= text2.length) {
                break;
              }
              var from = match2.index;
              var to = match2.index + match2[0].length;
              var p2 = pos2;
              p2 += currentNode.value.length;
              while (from >= p2) {
                currentNode = currentNode.next;
                p2 += currentNode.value.length;
              }
              p2 -= currentNode.value.length;
              pos2 = p2;
              if (currentNode.value instanceof Token2) {
                continue;
              }
              for (var k2 = currentNode; k2 !== tokenList.tail && (p2 < to || typeof k2.value === "string"); k2 = k2.next) {
                removeCount++;
                p2 += k2.value.length;
              }
              removeCount--;
              str = text2.slice(pos2, p2);
              match2.index -= pos2;
            } else {
              match2 = matchPattern(pattern, 0, str, lookbehind);
              if (!match2) {
                continue;
              }
            }
            var from = match2.index;
            var matchStr = match2[0];
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
            var wrapped = new Token2(token2, inside ? _2.tokenize(matchStr, inside) : matchStr, alias, matchStr);
            currentNode = addAfter(tokenList, removeFrom, wrapped);
            if (after) {
              addAfter(tokenList, currentNode, after);
            }
            if (removeCount > 1) {
              var nestedRematch = {
                cause: token2 + "," + j2,
                reach
              };
              matchGrammar(text2, tokenList, grammar, currentNode.prev, pos2, nestedRematch);
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
    function addAfter(list2, node, value) {
      var next = node.next;
      var newNode = { value, prev: node, next };
      node.next = newNode;
      next.prev = newNode;
      list2.length++;
      return newNode;
    }
    function removeRange(list2, node, count) {
      var next = node.next;
      for (var i = 0; i < count && next !== list2.tail; i++) {
        next = next.next;
      }
      node.next = next;
      next.prev = node;
      list2.length -= i;
    }
    function toArray2(list2) {
      var array = [];
      var node = list2.head.next;
      while (node !== list2.tail) {
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
          var code2 = message.code;
          var immediateClose = message.immediateClose;
          _self2.postMessage(_2.highlight(code2, _2.languages[lang2], lang2));
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
    function loadFile(src, success, error2) {
      var xhr = new XMLHttpRequest();
      xhr.open("GET", src, true);
      xhr.onreadystatechange = function() {
        if (xhr.readyState == 4) {
          if (xhr.status < 400 && xhr.responseText) {
            success(xhr.responseText);
          } else {
            if (xhr.status >= 400) {
              error2(FAILURE_MESSAGE(xhr.status, xhr.statusText));
            } else {
              error2(FAILURE_EMPTY_MESSAGE);
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
        var code2 = pre.appendChild(document.createElement("CODE"));
        code2.textContent = LOADING_MESSAGE;
        var src = pre.getAttribute("data-src");
        var language = env.language;
        if (language === "none") {
          var extension = (/\.(\w+)$/.exec(src) || [, "none"])[1];
          language = EXTENSIONS[extension] || extension;
        }
        Prism2.util.setLanguage(code2, language);
        Prism2.util.setLanguage(pre, language);
        var autoloader = Prism2.plugins.autoloader;
        if (autoloader) {
          autoloader.loadLanguages(language);
        }
        loadFile(
          src,
          function(text2) {
            pre.setAttribute(STATUS_ATTR, STATUS_LOADED);
            var range = parseRange(pre.getAttribute("data-range"));
            if (range) {
              var lines = text2.split(/\r\n?|\n/g);
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
              text2 = lines.slice(start2, end2).join("\n");
              if (!pre.hasAttribute("data-start")) {
                pre.setAttribute("data-start", String(start2 + 1));
              }
            }
            code2.textContent = text2;
            Prism2.highlightElement(code2);
          },
          function(error2) {
            pre.setAttribute(STATUS_ATTR, STATUS_FAILED);
            code2.textContent = error2;
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
        for (var i = 0, element; element = elements[i++]; ) {
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
                } catch (err2) {
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
                var _options$action = options.action, action = _options$action === void 0 ? "copy" : _options$action, container = options.container, target = options.target, text2 = options.text;
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
                if (text2) {
                  return actions_copy(text2, {
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
                for (var i = 0; i < props.length; i++) {
                  var descriptor = props[i];
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
                var attribute2 = "data-clipboard-".concat(suffix);
                if (!element.hasAttribute(attribute2)) {
                  return;
                }
                return element.getAttribute(attribute2);
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
                    var text2 = actions_default({
                      action,
                      container: this.container,
                      target: this.target(trigger),
                      text: this.text(trigger)
                    });
                    this.emit(text2 ? "success" : "error", {
                      action,
                      text: text2,
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
              function E2() {
              }
              E2.prototype = {
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
                  var i = 0;
                  var len = evtArr.length;
                  for (i; i < len; i++) {
                    evtArr[i].fn.apply(evtArr[i].ctx, data);
                  }
                  return this;
                },
                off: function(name, callback) {
                  var e2 = this.e || (this.e = {});
                  var evts = e2[name];
                  var liveEvents = [];
                  if (evts && callback) {
                    for (var i = 0, len = evts.length; i < len; i++) {
                      if (evts[i].fn !== callback && evts[i].fn._ !== callback)
                        liveEvents.push(evts[i]);
                    }
                  }
                  liveEvents.length ? e2[name] = liveEvents : delete e2[name];
                  return this;
                }
              };
              module2.exports = E2;
              module2.exports.TinyEmitter = E2;
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
var reference$1 = "reference";
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
      Object.keys(attributes).forEach(function(attribute2) {
        element.removeAttribute(attribute2);
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
var max$1 = Math.max;
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
  var x = (clientRect.left + (addVisualOffsets && visualViewport ? visualViewport.offsetLeft : 0)) / scaleX;
  var y2 = (clientRect.top + (addVisualOffsets && visualViewport ? visualViewport.offsetTop : 0)) / scaleY;
  var width = clientRect.width / scaleX;
  var height = clientRect.height / scaleY;
  return {
    width,
    height,
    top: y2,
    right: x + width,
    bottom: y2 + height,
    left: x,
    x,
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
function within(min$1, value, max2) {
  return max$1(min$1, min(value, max2));
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
  var x = _ref.x, y2 = _ref.y;
  var dpr = win.devicePixelRatio || 1;
  return {
    x: round(x * dpr) / dpr || 0,
    y: round(y2 * dpr) / dpr || 0
  };
}
function mapToStyles(_ref2) {
  var _Object$assign2;
  var popper2 = _ref2.popper, popperRect = _ref2.popperRect, placement = _ref2.placement, variation = _ref2.variation, offsets = _ref2.offsets, position = _ref2.position, gpuAcceleration = _ref2.gpuAcceleration, adaptive = _ref2.adaptive, roundOffsets = _ref2.roundOffsets, isFixed = _ref2.isFixed;
  var _offsets$x = offsets.x, x = _offsets$x === void 0 ? 0 : _offsets$x, _offsets$y = offsets.y, y2 = _offsets$y === void 0 ? 0 : _offsets$y;
  var _ref3 = typeof roundOffsets === "function" ? roundOffsets({
    x,
    y: y2
  }) : {
    x,
    y: y2
  };
  x = _ref3.x;
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
      x -= offsetX - popperRect.width;
      x *= gpuAcceleration ? 1 : -1;
    }
  }
  var commonStyles = Object.assign({
    position
  }, adaptive && unsetSides);
  var _ref4 = roundOffsets === true ? roundOffsetsByDPR({
    x,
    y: y2
  }, getWindow(popper2)) : {
    x,
    y: y2
  };
  x = _ref4.x;
  y2 = _ref4.y;
  if (gpuAcceleration) {
    var _Object$assign;
    return Object.assign({}, commonStyles, (_Object$assign = {}, _Object$assign[sideY] = hasY ? "0" : "", _Object$assign[sideX] = hasX ? "0" : "", _Object$assign.transform = (win.devicePixelRatio || 1) <= 1 ? "translate(" + x + "px, " + y2 + "px)" : "translate3d(" + x + "px, " + y2 + "px, 0)", _Object$assign));
  }
  return Object.assign({}, commonStyles, (_Object$assign2 = {}, _Object$assign2[sideY] = hasY ? y2 + "px" : "", _Object$assign2[sideX] = hasX ? x + "px" : "", _Object$assign2.transform = "", _Object$assign2));
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
  var x = 0;
  var y2 = 0;
  if (visualViewport) {
    width = visualViewport.width;
    height = visualViewport.height;
    var layoutViewport = isLayoutViewport();
    if (layoutViewport || !layoutViewport && strategy === "fixed") {
      x = visualViewport.offsetLeft;
      y2 = visualViewport.offsetTop;
    }
  }
  return {
    width,
    height,
    x: x + getWindowScrollBarX(element),
    y: y2
  };
}
function getDocumentRect(element) {
  var _element$ownerDocumen;
  var html = getDocumentElement(element);
  var winScroll = getWindowScroll(element);
  var body = (_element$ownerDocumen = element.ownerDocument) == null ? void 0 : _element$ownerDocumen.body;
  var width = max$1(html.scrollWidth, html.clientWidth, body ? body.scrollWidth : 0, body ? body.clientWidth : 0);
  var height = max$1(html.scrollHeight, html.clientHeight, body ? body.scrollHeight : 0, body ? body.clientHeight : 0);
  var x = -winScroll.scrollLeft + getWindowScrollBarX(element);
  var y2 = -winScroll.scrollTop;
  if (getComputedStyle$1(body || html).direction === "rtl") {
    x += max$1(html.clientWidth, body ? body.clientWidth : 0) - width;
  }
  return {
    width,
    height,
    x,
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
function listScrollParents(element, list2) {
  var _element$ownerDocumen;
  if (list2 === void 0) {
    list2 = [];
  }
  var scrollParent = getScrollParent(element);
  var isBody = scrollParent === ((_element$ownerDocumen = element.ownerDocument) == null ? void 0 : _element$ownerDocumen.body);
  var win = getWindow(scrollParent);
  var target = isBody ? [win].concat(win.visualViewport || [], isScrollParent(scrollParent) ? scrollParent : []) : scrollParent;
  var updatedList = list2.concat(target);
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
    accRect.top = max$1(rect.top, accRect.top);
    accRect.right = min(rect.right, accRect.right);
    accRect.bottom = min(rect.bottom, accRect.bottom);
    accRect.left = max$1(rect.left, accRect.left);
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
  var altContext = elementContext === popper ? reference$1 : popper;
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
  for (var i = 0; i < placements2.length; i++) {
    var placement = placements2[i];
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
  var _data$state$placement = data[state.placement], x = _data$state$placement.x, y2 = _data$state$placement.y;
  if (state.modifiersData.popperOffsets != null) {
    state.modifiersData.popperOffsets.x += x;
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
    var max2 = offset2 - overflow[altSide];
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
    var preventedOffset = within(tether ? min(min$1, tetherMin) : min$1, offset2, tether ? max$1(max2, tetherMax) : max2);
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
  var map2 = /* @__PURE__ */ new Map();
  var visited = /* @__PURE__ */ new Set();
  var result = [];
  modifiers.forEach(function(modifier) {
    map2.set(modifier.name, modifier);
  });
  function sort(modifier) {
    visited.add(modifier.name);
    var requires = [].concat(modifier.requires || [], modifier.requiresIfExists || []);
    requires.forEach(function(dep) {
      if (!visited.has(dep)) {
        var depModifier = map2.get(dep);
        if (depModifier) {
          sort(depModifier);
        }
      }
    });
    result.push(modifier);
  }
  modifiers.forEach(function(modifier) {
    if (!visited.has(modifier.name)) {
      sort(modifier);
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
function debounce$1(fn2) {
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
  var _generatorOptions = generatorOptions, _generatorOptions$def = _generatorOptions.defaultModifiers, defaultModifiers2 = _generatorOptions$def === void 0 ? [] : _generatorOptions$def, _generatorOptions$def2 = _generatorOptions.defaultOptions, defaultOptions2 = _generatorOptions$def2 === void 0 ? DEFAULT_OPTIONS : _generatorOptions$def2;
  return function createPopper2(reference2, popper2, options) {
    if (options === void 0) {
      options = defaultOptions2;
    }
    var state = {
      placement: "bottom",
      orderedModifiers: [],
      options: Object.assign({}, DEFAULT_OPTIONS, defaultOptions2),
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
        state.options = Object.assign({}, defaultOptions2, state.options, options2);
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
      update: debounce$1(function() {
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
  reference: reference$1,
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
    selector = selector.replace(/#([^\s"#']+)/g, (match2, id) => `#${CSS.escape(id)}`);
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
const getNextActiveElement = (list2, activeElement, shouldGetNext, isCycleAllowed) => {
  const listLength = list2.length;
  let index = list2.indexOf(activeElement);
  if (index === -1) {
    return !shouldGetNext && isCycleAllowed ? list2[listLength - 1] : list2[0];
  }
  index += shouldGetNext ? 1 : -1;
  if (isCycleAllowed) {
    index = (index + listLength) % listLength;
  }
  return list2[Math.max(0, Math.min(index, listLength - 1))];
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
  _getConfig(config2) {
    config2 = this._mergeConfigObj(config2);
    config2 = this._configAfterMerge(config2);
    this._typeCheckConfig(config2);
    return config2;
  }
  _configAfterMerge(config2) {
    return config2;
  }
  _mergeConfigObj(config2, element) {
    const jsonConfig = isElement(element) ? Manipulator.getDataAttribute(element, "config") : {};
    return {
      ...this.constructor.Default,
      ...typeof jsonConfig === "object" ? jsonConfig : {},
      ...isElement(element) ? Manipulator.getDataAttributes(element) : {},
      ...typeof config2 === "object" ? config2 : {}
    };
  }
  _typeCheckConfig(config2, configTypes = this.constructor.DefaultType) {
    for (const [property, expectedTypes] of Object.entries(configTypes)) {
      const value = config2[property];
      const valueType = isElement(value) ? "element" : toType(value);
      if (!new RegExp(expectedTypes).test(valueType)) {
        throw new TypeError(`${this.constructor.NAME.toUpperCase()}: Option "${property}" provided type "${valueType}" but expected type "${expectedTypes}".`);
      }
    }
  }
}
const VERSION = "5.3.3";
class BaseComponent extends Config {
  constructor(element, config2) {
    super();
    element = getElement(element);
    if (!element) {
      return;
    }
    this._element = element;
    this._config = this._getConfig(config2);
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
  _getConfig(config2) {
    config2 = this._mergeConfigObj(config2, this._element);
    config2 = this._configAfterMerge(config2);
    this._typeCheckConfig(config2);
    return config2;
  }
  // Static
  static getInstance(element) {
    return Data.get(getElement(element), this.DATA_KEY);
  }
  static getOrCreateInstance(element, config2 = {}) {
    return this.getInstance(element) || new this(element, typeof config2 === "object" ? config2 : null);
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
  static jQueryInterface(config2) {
    return this.each(function() {
      const data = Alert.getOrCreateInstance(this);
      if (typeof config2 !== "string") {
        return;
      }
      if (data[config2] === void 0 || config2.startsWith("_") || config2 === "constructor") {
        throw new TypeError(`No method named "${config2}"`);
      }
      data[config2](this);
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
  static jQueryInterface(config2) {
    return this.each(function() {
      const data = Button.getOrCreateInstance(this);
      if (config2 === "toggle") {
        data[config2]();
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
  constructor(element, config2) {
    super();
    this._element = element;
    if (!element || !Swipe.isSupported()) {
      return;
    }
    this._config = this._getConfig(config2);
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
  constructor(element, config2) {
    super(element, config2);
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
  _configAfterMerge(config2) {
    config2.defaultInterval = config2.interval;
    return config2;
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
  static jQueryInterface(config2) {
    return this.each(function() {
      const data = Carousel.getOrCreateInstance(this, config2);
      if (typeof config2 === "number") {
        data.to(config2);
        return;
      }
      if (typeof config2 === "string") {
        if (data[config2] === void 0 || config2.startsWith("_") || config2 === "constructor") {
          throw new TypeError(`No method named "${config2}"`);
        }
        data[config2]();
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
  constructor(element, config2) {
    super(element, config2);
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
  _configAfterMerge(config2) {
    config2.toggle = Boolean(config2.toggle);
    config2.parent = getElement(config2.parent);
    return config2;
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
  static jQueryInterface(config2) {
    const _config = {};
    if (typeof config2 === "string" && /show|hide/.test(config2)) {
      _config.toggle = false;
    }
    return this.each(function() {
      const data = Collapse.getOrCreateInstance(this, _config);
      if (typeof config2 === "string") {
        if (typeof data[config2] === "undefined") {
          throw new TypeError(`No method named "${config2}"`);
        }
        data[config2]();
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
  constructor(element, config2) {
    super(element, config2);
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
  _getConfig(config2) {
    config2 = super._getConfig(config2);
    if (typeof config2.reference === "object" && !isElement(config2.reference) && typeof config2.reference.getBoundingClientRect !== "function") {
      throw new TypeError(`${NAME$a.toUpperCase()}: Option "reference" provided type "object" without a required "getBoundingClientRect" method.`);
    }
    return config2;
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
  static jQueryInterface(config2) {
    return this.each(function() {
      const data = Dropdown.getOrCreateInstance(this, config2);
      if (typeof config2 !== "string") {
        return;
      }
      if (typeof data[config2] === "undefined") {
        throw new TypeError(`No method named "${config2}"`);
      }
      data[config2]();
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
  constructor(config2) {
    super();
    this._config = this._getConfig(config2);
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
  _configAfterMerge(config2) {
    config2.rootElement = getElement(config2.rootElement);
    return config2;
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
  constructor(config2) {
    super();
    this._config = this._getConfig(config2);
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
  constructor(element, config2) {
    super(element, config2);
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
  static jQueryInterface(config2, relatedTarget) {
    return this.each(function() {
      const data = Modal.getOrCreateInstance(this, config2);
      if (typeof config2 !== "string") {
        return;
      }
      if (typeof data[config2] === "undefined") {
        throw new TypeError(`No method named "${config2}"`);
      }
      data[config2](relatedTarget);
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
  constructor(element, config2) {
    super(element, config2);
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
  static jQueryInterface(config2) {
    return this.each(function() {
      const data = Offcanvas.getOrCreateInstance(this, config2);
      if (typeof config2 !== "string") {
        return;
      }
      if (data[config2] === void 0 || config2.startsWith("_") || config2 === "constructor") {
        throw new TypeError(`No method named "${config2}"`);
      }
      data[config2](this);
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
const allowedAttribute = (attribute2, allowedAttributeList) => {
  const attributeName = attribute2.nodeName.toLowerCase();
  if (allowedAttributeList.includes(attributeName)) {
    if (uriAttributes.has(attributeName)) {
      return Boolean(SAFE_URL_PATTERN.test(attribute2.nodeValue));
    }
    return true;
  }
  return allowedAttributeList.filter((attributeRegex) => attributeRegex instanceof RegExp).some((regex2) => regex2.test(attributeName));
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
    for (const attribute2 of attributeList) {
      if (!allowedAttribute(attribute2, allowedAttributes)) {
        element.removeAttribute(attribute2.nodeName);
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
  constructor(config2) {
    super();
    this._config = this._getConfig(config2);
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
    return Object.values(this._config.content).map((config2) => this._resolvePossibleFunction(config2)).filter(Boolean);
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
    for (const [selector, text2] of Object.entries(this._config.content)) {
      this._setContent(templateWrapper, text2, selector);
    }
    const template = templateWrapper.children[0];
    const extraClass = this._resolvePossibleFunction(this._config.extraClass);
    if (extraClass) {
      template.classList.add(...extraClass.split(" "));
    }
    return template;
  }
  // Private
  _typeCheckConfig(config2) {
    super._typeCheckConfig(config2);
    this._checkContent(config2.content);
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
  constructor(element, config2) {
    if (typeof Popper === "undefined") {
      throw new TypeError("Bootstrap's tooltips require Popper (https://popper.js.org)");
    }
    super(element, config2);
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
  _getConfig(config2) {
    const dataAttributes = Manipulator.getDataAttributes(this._element);
    for (const dataAttribute of Object.keys(dataAttributes)) {
      if (DISALLOWED_ATTRIBUTES.has(dataAttribute)) {
        delete dataAttributes[dataAttribute];
      }
    }
    config2 = {
      ...dataAttributes,
      ...typeof config2 === "object" && config2 ? config2 : {}
    };
    config2 = this._mergeConfigObj(config2);
    config2 = this._configAfterMerge(config2);
    this._typeCheckConfig(config2);
    return config2;
  }
  _configAfterMerge(config2) {
    config2.container = config2.container === false ? document.body : getElement(config2.container);
    if (typeof config2.delay === "number") {
      config2.delay = {
        show: config2.delay,
        hide: config2.delay
      };
    }
    if (typeof config2.title === "number") {
      config2.title = config2.title.toString();
    }
    if (typeof config2.content === "number") {
      config2.content = config2.content.toString();
    }
    return config2;
  }
  _getDelegateConfig() {
    const config2 = {};
    for (const [key2, value] of Object.entries(this._config)) {
      if (this.constructor.Default[key2] !== value) {
        config2[key2] = value;
      }
    }
    config2.selector = false;
    config2.trigger = "manual";
    return config2;
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
  static jQueryInterface(config2) {
    return this.each(function() {
      const data = Tooltip.getOrCreateInstance(this, config2);
      if (typeof config2 !== "string") {
        return;
      }
      if (typeof data[config2] === "undefined") {
        throw new TypeError(`No method named "${config2}"`);
      }
      data[config2]();
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
  static jQueryInterface(config2) {
    return this.each(function() {
      const data = Popover.getOrCreateInstance(this, config2);
      if (typeof config2 !== "string") {
        return;
      }
      if (typeof data[config2] === "undefined") {
        throw new TypeError(`No method named "${config2}"`);
      }
      data[config2]();
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
  constructor(element, config2) {
    super(element, config2);
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
  _configAfterMerge(config2) {
    config2.target = getElement(config2.target) || document.body;
    config2.rootMargin = config2.offset ? `${config2.offset}px 0px -30%` : config2.rootMargin;
    if (typeof config2.threshold === "string") {
      config2.threshold = config2.threshold.split(",").map((value) => Number.parseFloat(value));
    }
    return config2;
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
  static jQueryInterface(config2) {
    return this.each(function() {
      const data = ScrollSpy.getOrCreateInstance(this, config2);
      if (typeof config2 !== "string") {
        return;
      }
      if (data[config2] === void 0 || config2.startsWith("_") || config2 === "constructor") {
        throw new TypeError(`No method named "${config2}"`);
      }
      data[config2]();
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
  _setAttributeIfNotExists(element, attribute2, value) {
    if (!element.hasAttribute(attribute2)) {
      element.setAttribute(attribute2, value);
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
  static jQueryInterface(config2) {
    return this.each(function() {
      const data = Tab.getOrCreateInstance(this);
      if (typeof config2 !== "string") {
        return;
      }
      if (data[config2] === void 0 || config2.startsWith("_") || config2 === "constructor") {
        throw new TypeError(`No method named "${config2}"`);
      }
      data[config2]();
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
  constructor(element, config2) {
    super(element, config2);
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
  static jQueryInterface(config2) {
    return this.each(function() {
      const data = Toast.getOrCreateInstance(this, config2);
      if (typeof config2 === "string") {
        if (typeof data[config2] === "undefined") {
          throw new TypeError(`No method named "${config2}"`);
        }
        data[config2](this);
      }
    });
  }
}
enableDismissTrigger(Toast);
defineJQueryPlugin(Toast);
var t$1, r$1, u, i$1, o = 0, f = [], c$1 = l$1, e$1 = c$1.__b, a = c$1.__r, v = c$1.diffed, l = c$1.__c, m = c$1.unmount, s = c$1.__;
function d(n2, t2) {
  c$1.__h && c$1.__h(r$1, n2, o || t2), o = 0;
  var u2 = r$1.__H || (r$1.__H = { __: [], __h: [] });
  return n2 >= u2.__.length && u2.__.push({}), u2.__[n2];
}
function h(n2) {
  return o = 1, p(D, n2);
}
function p(n2, u2, i) {
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
      var i2 = o2.__c.props !== n3;
      return u3.forEach(function(n4) {
        if (n4.__N) {
          var t3 = n4.__[0];
          n4.__ = n4.__N, n4.__N = void 0, t3 !== n4.__[0] && (i2 = true);
        }
      }), c2 && c2.call(this, n3, t2, r2) || i2;
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
  var i = d(t$1++, 3);
  !c$1.__s && C(i.__H, u2) && (i.__ = n2, i.i = u2, r$1.__H.__h.push(i));
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
  var i = (r$1 = n2.__c).__H;
  i && (u === r$1 ? (i.__h = [], r$1.__h = [], i.__.forEach(function(n3) {
    n3.__N && (n3.__ = n3.__N), n3.i = n3.__N = void 0;
  })) : (i.__h.forEach(z), i.__h.forEach(B), i.__h = [], t$1 = 0)), u = r$1;
}, c$1.diffed = function(n2) {
  v && v(n2);
  var t2 = n2.__c;
  t2 && t2.__H && (t2.__H.__h.length && (1 !== f.push(t2) && i$1 === c$1.requestAnimationFrame || ((i$1 = c$1.requestAnimationFrame) || w)(j)), t2.__H.__.forEach(function(n3) {
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
const inputString = (input) => {
  if (typeof input === "string") {
    return [input];
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
function formatNoDecimal(num) {
  if (typeof num !== "number") {
    return num;
  }
  const rounded = Math.round(num);
  return rounded.toFixed(0);
}
function formatNumber(num) {
  return num.toLocaleString(navigator.language, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 5
  });
}
function formatDateTime(date) {
  const options = {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true
  };
  return new Intl.DateTimeFormat(void 0, options).format(date);
}
function formatDuration(start2, end2) {
  const durationMs = end2.getTime() - start2.getTime();
  const durationSec = durationMs / 1e3;
  return formatTime(durationSec);
}
const filename = (path) => {
  const pathparts = path.split("/");
  const basename = pathparts.slice(-1)[0];
  const match2 = basename.match(/(.*)\.\S+$/);
  if (match2) {
    return match2[1];
  } else {
    return path;
  }
};
const dirname = (path) => {
  const pathparts = path.split("/");
  if (pathparts.length > 1) {
    pathparts.pop();
  }
  return pathparts.join("/");
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
function debounce(func, wait, options = {}) {
  let timeout, context, args, result;
  let lastCallTime = null;
  const later = () => {
    const last = Date.now() - lastCallTime;
    if (last < wait && last >= 0) {
      timeout = setTimeout(later, wait - last);
    } else {
      timeout = null;
      if (!options.leading) {
        result = func.apply(context, args);
        if (!timeout) context = args = null;
      }
    }
  };
  return function() {
    context = this;
    args = arguments;
    lastCallTime = Date.now();
    const callNow = options.leading && !timeout;
    if (!timeout) {
      timeout = setTimeout(later, wait);
    }
    if (callNow) {
      result = func.apply(context, args);
      context = args = null;
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
  approve: "bi bi-shield",
  approvals: {
    approve: "bi bi-shield-check",
    reject: "bi bi-shield-x",
    terminate: "bi bi-shield-exclamation",
    escalate: "bi bi-box-arrow-up",
    modify: "bi bi-pencil-square"
  },
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
  fork: "bi bi-signpost-split",
  info: "bi bi-info-circle",
  input: "bi bi-terminal",
  inspect: "bi bi-gear",
  json: "bi bi-filetype-json",
  limits: {
    messages: "bi bi-chat-right-text",
    context: "bi bi-person-workspace",
    operator: "bi bi-person-workspace",
    tokens: "bi bi-list",
    time: "bi bi-stopwatch"
  },
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
  refresh: "bi bi-arrow-clockwise",
  role: {
    user: "bi bi-person",
    system: "bi bi-cpu",
    assistant: "bi bi-robot",
    tool: "bi bi-tools",
    unknown: "bi bi-patch-question"
  },
  running: "bi bi-stars",
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
  },
  tertiary: {
    color: "var(--bs-tertiary-color)"
  }
};
const ErrorPanel = ({ id, classes, title, error: error2 }) => {
  const emptyStyle = {
    display: "flex",
    flex: "0 0 content",
    alignItems: "center",
    justifyContent: "center"
  };
  const message = error2.message;
  const stack2 = error2.stack;
  return m$1`
    <div style=${{ overflowY: "auto", height: "100vh" }}>
      <div
        ...${{ id }}
        class="${classes ? classes : ""}"
        style=${{
    ...emptyStyle,
    flexDirection: "column",
    minHeight: "10rem",
    marginTop: "4rem",
    marginBottom: "4em",
    width: "100vw"
  }}
      >
        <div style=${{ ...emptyStyle, fontSize: FontSize.larger }}>
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
    marginTop: "1rem",
    border: "solid 1px var(--bs-border-color)",
    borderRadius: "var(--bs-border-radius)",
    padding: "1em",
    maxWidth: "80%"
  }}
        >
          <div>
            Error: ${message || ""}
            ${stack2 && error2.displayStack !== false && m$1`
              <pre
                style=${{ fontSize: FontSize.smaller, whiteSpace: "pre-wrap" }}
              >
            <code>
              at ${stack2}
            </code>
          </pre>
            `}
          </div>
        </div>
      </div>
    </div>
  `;
};
class AppErrorBoundary extends k$1 {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError(error2) {
    return { hasError: true, error: error2 };
  }
  componentDidCatch(error2, errorInfo) {
    console.log({ error: error2, errorInfo });
  }
  render() {
    if (this.state.hasError) {
      console.error({ e: this.state.error });
      return m$1`<${ErrorPanel}
        title="An unexpected error occurred."
        error="${this.state.error}"
      />`;
    }
    return this.props.children;
  }
}
const ProgressBar = ({ style, containerStyle, animating }) => {
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
    ...containerStyle,
    background: "#ffffff00"
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
    paddingTop: "0.5rem",
    height: "3.6em"
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
      <div style=${{ marginTop: "3.6em", zIndex: 3 }}>
        <${ProgressBar} animating=${loading} style=${{ marginTop: "-2px" }} />
      </div>
      <ul
        class="list-group"
        style=${{ flexGrow: 1, overflowY: "auto", marginTop: "-3px" }}
      >
        ${logs.files.map((file, index) => {
    var _a2, _b2, _c, _d, _e, _f, _g, _h, _i;
    const active = index === selectedIndex ? " active" : "";
    const logHeader = logHeaders[file.name];
    const hyperparameters = logHeader ? {
      ...(_a2 = logHeader.plan) == null ? void 0 : _a2.config,
      ...(_b2 = logHeader.eval) == null ? void 0 : _b2.task_args
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
              <div
                style=${{
      marginTop: "1em",
      ...ApplicationStyles.threeLineClamp
    }}
              >
                <small class="mb-1">
                  ${hyperparameters ? Object.keys(hyperparameters).map((key2) => {
      const val = hyperparameters[key2];
      if (Array.isArray(val) || typeof val === "object") {
        return `${key2}: ${JSON.stringify(val)}`;
      } else {
        return `${key2}: ${val}`;
      }
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
  var _a2, _b2;
  switch (logHeader == null ? void 0 : logHeader.status) {
    case "error":
      return m$1`<${StatusError} message="Error" />`;
    case "cancelled":
      return m$1`<${StatusCancelled} message="Cancelled" />`;
    case "started":
      return m$1`<${StatusRunning} message="Running" />`;
    default:
      if (((_a2 = logHeader == null ? void 0 : logHeader.results) == null ? void 0 : _a2.scores) && ((_b2 = logHeader.results) == null ? void 0 : _b2.scores.length) > 0) {
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
  return m$1`<div
    style=${{
    marginTop: "0.2em",
    fontSize: FontSize.small,
    ...TextStyle.label,
    ...TextStyle.secondary
  }}
  >
    ${message}
  </div>`;
};
const StatusRunning = ({ message }) => {
  return m$1` <div
    style=${{
    display: "grid",
    gridTemplateColumns: "max-content max-content",
    columnGap: "0.5em",
    marginTop: "0.3em",
    fontSize: FontSize.small,
    ...TextStyle.secondary,
    ...TextStyle.label
  }}
  >
    <div>${message}</div>
  </div>`;
};
const StatusError = ({ message }) => {
  return m$1`<div
    style=${{
    color: "var(--bs-danger)",
    marginTop: "0.2em",
    fontSize: FontSize.small,
    ...TextStyle.label
  }}
  >
    ${message}
  </div>`;
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
  classes,
  scrollPosition,
  setScrollPosition,
  children
}) => {
  const tabContentsId = computeTabContentsId(id, index);
  const tabContentsRef = A();
  y(() => {
    setTimeout(() => {
      if (scrollPosition !== void 0 && tabContentsRef.current && tabContentsRef.current.scrollTop !== scrollPosition) {
        tabContentsRef.current.scrollTop = scrollPosition;
      }
    }, 0);
  });
  const onScroll = q(
    (e2) => {
      setScrollPosition(e2.srcElement.scrollTop);
    },
    [setScrollPosition]
  );
  return m$1`<div
    id="${tabContentsId}"
    ref=${tabContentsRef}
    class="tab-pane show${selected ? " active" : ""}${classes ? ` ${classes}` : ""}"
    style=${{
    flex: "1",
    overflowY: scrollable === void 0 || scrollable ? "auto" : "hidden",
    ...style
  }}
    onscroll=${onScroll}
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
    padding: "0.25rem 0.5rem",
    borderTopLeftRadius: "var(--bs-border-radius)",
    borderTopRightRadius: "var(--bs-border-radius)",
    ...TextStyle.label,
    fontSize: FontSize.small,
    fontWeight: 500,
    marginTop: "2px",
    marginBottom: "-1px"
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
  return m$1`<div
    class="${classes || ""}"
    ...${{ id }}
    style=${{
    display: "grid",
    gridTemplateColumns: "max-content auto",
    columnGap: "0em",
    padding: "0.5em 0.5em 0.5em 0.5em",
    fontSize: FontSize.small,
    fontWeight: 600,
    ...TextStyle.label,
    ...style
  }}
  >
    ${icon ? m$1`<i
          class="${icon}"
          style=${{
    paddingRight: "0.2rem"
  }}
        ></i>` : m$1`<span
          style=${{
    paddingRight: "0.2rem"
  }}
        ></span>`}
    ${label ? label : ""} ${children}
  </div> `;
};
const CardBody = ({ id, classes, style, children }) => {
  return m$1`<div
    class="${classes || ""}"
    ...${{ id }}
    style=${{
    backgroundColor: "var(--bs-body-bg)",
    border: "solid 1px var(--bs-light-border-subtle)",
    borderRadius: "var(--bs-border-radius)",
    margin: "0 8px 8px 8px",
    padding: "0.5em",
    ...style
  }}
  >
    ${children}
  </div>`;
};
const Card = ({ id, classes, style, children }) => {
  return m$1`
    <div
      class="${classes || ""}"
      ...${{ id }}
      style=${{
    backgroundColor: "var(--bs-light-bg-subtle)",
    border: "solid 1px var(--bs-light-border-subtle)",
    borderRadius: "var(--bs-border-radius)",
    marginBottom: "1.5em",
    ...style
  }}
    >
      ${children}
    </div>
  `;
};
var e, t, r = {
  exports: {}
};
e = r, t = function(e2, t2) {
  Object.defineProperty(t2, "__esModule", {
    value: true
  }), t2.ANSIOutput = t2.ANSIColor = t2.ANSIFont = t2.ANSIStyle = void 0;
  let r2 = 0;
  const n2 = () => ("" + ++r2).padStart(16, "0");
  var o2, i, s2, a2, u2, l2, g2;
  (function(e3) {
    e3.Bold = "ansiBold", e3.Dim = "ansiDim", e3.Italic = "ansiItalic", e3.Underlined = "ansiUnderlined", e3.SlowBlink = "ansiSlowBlink", e3.RapidBlink = "ansiRapidBlink", e3.Hidden = "ansiHidden", e3.CrossedOut = "ansiCrossedOut", e3.Fraktur = "ansiFraktur", e3.DoubleUnderlined = "ansiDoubleUnderlined", e3.Framed = "ansiFramed", e3.Encircled = "ansiEncircled", e3.Overlined = "ansiOverlined", e3.Superscript = "ansiSuperscript", e3.Subscript = "ansiSubscript";
  })(o2 || (t2.ANSIStyle = o2 = {})), function(e3) {
    e3.AlternativeFont1 = "ansiAlternativeFont1", e3.AlternativeFont2 = "ansiAlternativeFont2", e3.AlternativeFont3 = "ansiAlternativeFont3", e3.AlternativeFont4 = "ansiAlternativeFont4", e3.AlternativeFont5 = "ansiAlternativeFont5", e3.AlternativeFont6 = "ansiAlternativeFont6", e3.AlternativeFont7 = "ansiAlternativeFont7", e3.AlternativeFont8 = "ansiAlternativeFont8", e3.AlternativeFont9 = "ansiAlternativeFont9";
  }(i || (t2.ANSIFont = i = {})), function(e3) {
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
      for (let e3 = this._outputLines.length; e3 < this._outputLine + 1; e3++) this._outputLines.push(new d2());
      this._buffer && (this._outputLines[this._outputLine].insert(this._buffer, this._outputColumn, this._sgrState), this._outputColumn += this._buffer.length, this._buffer = "");
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
      e3 && (this._outputColumn = Math.max(this._outputColumn - k2(e3[1], 1, 1), 0));
    }
    processCUP() {
      const e3 = this._controlSequence.match(/^([0-9]*)(?:;?([0-9]*))H$/);
      e3 && (this._outputLine = k2(e3[1], 1, 1) - 1, this._outputColumn = k2(e3[2], 1, 1) - 1);
    }
    processED() {
      const e3 = this._controlSequence.match(/^([0-9]*)J$/);
      if (e3) switch (p2(e3[1], 0)) {
        case 0:
          this._outputLines[this._outputLine].clearToEndOfLine(this._outputColumn);
          for (let e4 = this._outputLine + 1; e4 < this._outputLines.length; e4++) this._outputLines[e4].clearEntireLine();
          break;
        case 1:
          this._outputLines[this._outputLine].clearToBeginningOfLine(this._outputColumn);
          for (let e4 = 0; e4 < this._outputLine; e4++) this._outputLines[e4].clearEntireLine();
          break;
        case 2:
          for (let e4 = 0; e4 < this._outputLines.length; e4++) this._outputLines[e4].clearEntireLine();
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
          if (r3 + 1 !== t3.length) switch (t3[++r3]) {
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
            e3.setFont(i.AlternativeFont1);
            break;
          case a2.AlternativeFont2:
            e3.setFont(i.AlternativeFont2);
            break;
          case a2.AlternativeFont3:
            e3.setFont(i.AlternativeFont3);
            break;
          case a2.AlternativeFont4:
            e3.setFont(i.AlternativeFont4);
            break;
          case a2.AlternativeFont5:
            e3.setFont(i.AlternativeFont5);
            break;
          case a2.AlternativeFont6:
            e3.setFont(i.AlternativeFont6);
            break;
          case a2.AlternativeFont7:
            e3.setFont(i.AlternativeFont7);
            break;
          case a2.AlternativeFont8:
            e3.setFont(i.AlternativeFont8);
            break;
          case a2.AlternativeFont9:
            e3.setFont(i.AlternativeFont9);
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
      if (this._backgroundColor && !this._foregroundColor) switch (this._backgroundColor) {
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
        const i3 = this._outputRuns[o4];
        if (e3 < n3 + i3.text.length) {
          t3 = i3, r3 = o4;
          break;
        }
        n3 += i3.text.length;
      }
      if (void 0 === t3 || void 0 === r3) return;
      const o3 = e3 - n3, i2 = " ".repeat(this._totalLength - e3), s3 = [];
      if (o3) {
        const e4 = t3.text.slice(0, o3);
        s3.push(new B2(e4, t3.sgrState)), s3.push(new B2(i2));
      } else s3.push(new B2(i2));
      this.outputRuns.splice(r3, this._outputRuns.length - r3, ...s3);
    }
    clearToBeginningOfLine(e3) {
      if (0 === (e3 = Math.max(e3, 0))) return;
      if (e3 >= this._totalLength) return void this.clearEntireLine();
      let t3, r3, n3 = 0;
      for (let o4 = this._outputRuns.length - 1; o4 >= 0; o4--) {
        const i3 = this._outputRuns[o4];
        if (e3 >= n3 - i3.text.length) {
          t3 = i3, r3 = o4;
          break;
        }
        n3 -= i3.text.length;
      }
      if (void 0 === t3 || void 0 === r3) return;
      const o3 = n3 - e3, i2 = " ".repeat(e3), s3 = [new B2(i2)];
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
        const i3 = t3 - o3, s4 = [];
        if (i3) {
          const t4 = this._outputRuns[n3], o4 = t4.text.slice(0, i3);
          c2.equivalent(t4.sgrState, r3) ? s4.push(new B2(o4 + e3, r3)) : (s4.push(new B2(o4, t4.sgrState)), s4.push(new B2(e3, r3)));
        } else s4.push(new B2(e3, r3));
        return this.outputRuns.splice(n3, 1, ...s4), void (this._totalLength = o3 + i3 + e3.length);
      }
      let i2, s3 = this._totalLength;
      for (let r4 = this._outputRuns.length - 1; r4 >= 0; r4--) {
        const n4 = this._outputRuns[r4];
        if (t3 + e3.length > s3 - n4.text.length) {
          i2 = r4;
          break;
        }
        s3 -= n4.text.length;
      }
      if (void 0 === i2) return void this._outputRuns.push(new B2(e3, r3));
      const a3 = [], u3 = t3 - o3;
      if (u3) {
        const e4 = this._outputRuns[n3], t4 = e4.text.slice(0, u3);
        a3.push(new B2(t4, e4.sgrState));
      }
      a3.push(new B2(e3, r3));
      const l3 = s3 - (t3 + e3.length);
      if (l3) {
        const e4 = this._outputRuns[i2], t4 = e4.text.slice(-l3);
        a3.push(new B2(t4, e4.sgrState));
      }
      this._outputRuns.splice(n3, i2 - n3 + 1, ...a3), this._outputRuns.length > 1 && (this._outputRuns = B2.optimizeOutputRuns(this._outputRuns)), this._totalLength = this._outputRuns.reduce((e4, t4) => e4 + t4.text.length, 0);
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
const ANSIDisplay = ({ output, style }) => {
  const ansiOutput = new n.ANSIOutput();
  ansiOutput.processOutput(output);
  let firstOutput = false;
  return m$1`<div class="ansi-display" style=${{ ...style }}>
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
const Buckets = {
  first: 0,
  intermediate: 10,
  final: 1e3
};
const decodeCache = {};
function getDecodeCache(exclude) {
  let cache = decodeCache[exclude];
  if (cache) {
    return cache;
  }
  cache = decodeCache[exclude] = [];
  for (let i = 0; i < 128; i++) {
    const ch3 = String.fromCharCode(i);
    cache.push(ch3);
  }
  for (let i = 0; i < exclude.length; i++) {
    const ch3 = exclude.charCodeAt(i);
    cache[ch3] = "%" + ("0" + ch3.toString(16).toUpperCase()).slice(-2);
  }
  return cache;
}
function decode$1(string, exclude) {
  if (typeof exclude !== "string") {
    exclude = decode$1.defaultChars;
  }
  const cache = getDecodeCache(exclude);
  return string.replace(/(%[a-f0-9]{2})+/gi, function(seq) {
    let result = "";
    for (let i = 0, l2 = seq.length; i < l2; i += 3) {
      const b1 = parseInt(seq.slice(i + 1, i + 3), 16);
      if (b1 < 128) {
        result += cache[b1];
        continue;
      }
      if ((b1 & 224) === 192 && i + 3 < l2) {
        const b2 = parseInt(seq.slice(i + 4, i + 6), 16);
        if ((b2 & 192) === 128) {
          const chr = b1 << 6 & 1984 | b2 & 63;
          if (chr < 128) {
            result += "��";
          } else {
            result += String.fromCharCode(chr);
          }
          i += 3;
          continue;
        }
      }
      if ((b1 & 240) === 224 && i + 6 < l2) {
        const b2 = parseInt(seq.slice(i + 4, i + 6), 16);
        const b3 = parseInt(seq.slice(i + 7, i + 9), 16);
        if ((b2 & 192) === 128 && (b3 & 192) === 128) {
          const chr = b1 << 12 & 61440 | b2 << 6 & 4032 | b3 & 63;
          if (chr < 2048 || chr >= 55296 && chr <= 57343) {
            result += "���";
          } else {
            result += String.fromCharCode(chr);
          }
          i += 6;
          continue;
        }
      }
      if ((b1 & 248) === 240 && i + 9 < l2) {
        const b2 = parseInt(seq.slice(i + 4, i + 6), 16);
        const b3 = parseInt(seq.slice(i + 7, i + 9), 16);
        const b4 = parseInt(seq.slice(i + 10, i + 12), 16);
        if ((b2 & 192) === 128 && (b3 & 192) === 128 && (b4 & 192) === 128) {
          let chr = b1 << 18 & 1835008 | b2 << 12 & 258048 | b3 << 6 & 4032 | b4 & 63;
          if (chr < 65536 || chr > 1114111) {
            result += "����";
          } else {
            chr -= 65536;
            result += String.fromCharCode(55296 + (chr >> 10), 56320 + (chr & 1023));
          }
          i += 9;
          continue;
        }
      }
      result += "�";
    }
    return result;
  });
}
decode$1.defaultChars = ";/?:@&=+$,#";
decode$1.componentChars = "";
const encodeCache = {};
function getEncodeCache(exclude) {
  let cache = encodeCache[exclude];
  if (cache) {
    return cache;
  }
  cache = encodeCache[exclude] = [];
  for (let i = 0; i < 128; i++) {
    const ch3 = String.fromCharCode(i);
    if (/^[0-9a-z]$/i.test(ch3)) {
      cache.push(ch3);
    } else {
      cache.push("%" + ("0" + i.toString(16).toUpperCase()).slice(-2));
    }
  }
  for (let i = 0; i < exclude.length; i++) {
    cache[exclude.charCodeAt(i)] = exclude[i];
  }
  return cache;
}
function encode$1(string, exclude, keepEscaped) {
  if (typeof exclude !== "string") {
    keepEscaped = exclude;
    exclude = encode$1.defaultChars;
  }
  if (typeof keepEscaped === "undefined") {
    keepEscaped = true;
  }
  const cache = getEncodeCache(exclude);
  let result = "";
  for (let i = 0, l2 = string.length; i < l2; i++) {
    const code2 = string.charCodeAt(i);
    if (keepEscaped && code2 === 37 && i + 2 < l2) {
      if (/^[0-9a-f]{2}$/i.test(string.slice(i + 1, i + 3))) {
        result += string.slice(i, i + 3);
        i += 2;
        continue;
      }
    }
    if (code2 < 128) {
      result += cache[code2];
      continue;
    }
    if (code2 >= 55296 && code2 <= 57343) {
      if (code2 >= 55296 && code2 <= 56319 && i + 1 < l2) {
        const nextCode = string.charCodeAt(i + 1);
        if (nextCode >= 56320 && nextCode <= 57343) {
          result += encodeURIComponent(string[i] + string[i + 1]);
          i++;
          continue;
        }
      }
      result += "%EF%BF%BD";
      continue;
    }
    result += encodeURIComponent(string[i]);
  }
  return result;
}
encode$1.defaultChars = ";/?:@&=+$,-_.!~*'()#";
encode$1.componentChars = "-_.!~*'()";
function format$1(url) {
  let result = "";
  result += url.protocol || "";
  result += url.slashes ? "//" : "";
  result += url.auth ? url.auth + "@" : "";
  if (url.hostname && url.hostname.indexOf(":") !== -1) {
    result += "[" + url.hostname + "]";
  } else {
    result += url.hostname || "";
  }
  result += url.port ? ":" + url.port : "";
  result += url.pathname || "";
  result += url.search || "";
  result += url.hash || "";
  return result;
}
function Url() {
  this.protocol = null;
  this.slashes = null;
  this.auth = null;
  this.port = null;
  this.hostname = null;
  this.hash = null;
  this.search = null;
  this.pathname = null;
}
const protocolPattern = /^([a-z0-9.+-]+:)/i;
const portPattern = /:[0-9]*$/;
const simplePathPattern = /^(\/\/?(?!\/)[^\?\s]*)(\?[^\s]*)?$/;
const delims = ["<", ">", '"', "`", " ", "\r", "\n", "	"];
const unwise = ["{", "}", "|", "\\", "^", "`"].concat(delims);
const autoEscape = ["'"].concat(unwise);
const nonHostChars = ["%", "/", "?", ";", "#"].concat(autoEscape);
const hostEndingChars = ["/", "?", "#"];
const hostnameMaxLen = 255;
const hostnamePartPattern = /^[+a-z0-9A-Z_-]{0,63}$/;
const hostnamePartStart = /^([+a-z0-9A-Z_-]{0,63})(.*)$/;
const hostlessProtocol = {
  javascript: true,
  "javascript:": true
};
const slashedProtocol = {
  http: true,
  https: true,
  ftp: true,
  gopher: true,
  file: true,
  "http:": true,
  "https:": true,
  "ftp:": true,
  "gopher:": true,
  "file:": true
};
function urlParse(url, slashesDenoteHost) {
  if (url && url instanceof Url) return url;
  const u2 = new Url();
  u2.parse(url, slashesDenoteHost);
  return u2;
}
Url.prototype.parse = function(url, slashesDenoteHost) {
  let lowerProto, hec, slashes;
  let rest = url;
  rest = rest.trim();
  if (!slashesDenoteHost && url.split("#").length === 1) {
    const simplePath = simplePathPattern.exec(rest);
    if (simplePath) {
      this.pathname = simplePath[1];
      if (simplePath[2]) {
        this.search = simplePath[2];
      }
      return this;
    }
  }
  let proto = protocolPattern.exec(rest);
  if (proto) {
    proto = proto[0];
    lowerProto = proto.toLowerCase();
    this.protocol = proto;
    rest = rest.substr(proto.length);
  }
  if (slashesDenoteHost || proto || rest.match(/^\/\/[^@\/]+@[^@\/]+/)) {
    slashes = rest.substr(0, 2) === "//";
    if (slashes && !(proto && hostlessProtocol[proto])) {
      rest = rest.substr(2);
      this.slashes = true;
    }
  }
  if (!hostlessProtocol[proto] && (slashes || proto && !slashedProtocol[proto])) {
    let hostEnd = -1;
    for (let i = 0; i < hostEndingChars.length; i++) {
      hec = rest.indexOf(hostEndingChars[i]);
      if (hec !== -1 && (hostEnd === -1 || hec < hostEnd)) {
        hostEnd = hec;
      }
    }
    let auth, atSign;
    if (hostEnd === -1) {
      atSign = rest.lastIndexOf("@");
    } else {
      atSign = rest.lastIndexOf("@", hostEnd);
    }
    if (atSign !== -1) {
      auth = rest.slice(0, atSign);
      rest = rest.slice(atSign + 1);
      this.auth = auth;
    }
    hostEnd = -1;
    for (let i = 0; i < nonHostChars.length; i++) {
      hec = rest.indexOf(nonHostChars[i]);
      if (hec !== -1 && (hostEnd === -1 || hec < hostEnd)) {
        hostEnd = hec;
      }
    }
    if (hostEnd === -1) {
      hostEnd = rest.length;
    }
    if (rest[hostEnd - 1] === ":") {
      hostEnd--;
    }
    const host = rest.slice(0, hostEnd);
    rest = rest.slice(hostEnd);
    this.parseHost(host);
    this.hostname = this.hostname || "";
    const ipv6Hostname = this.hostname[0] === "[" && this.hostname[this.hostname.length - 1] === "]";
    if (!ipv6Hostname) {
      const hostparts = this.hostname.split(/\./);
      for (let i = 0, l2 = hostparts.length; i < l2; i++) {
        const part = hostparts[i];
        if (!part) {
          continue;
        }
        if (!part.match(hostnamePartPattern)) {
          let newpart = "";
          for (let j2 = 0, k2 = part.length; j2 < k2; j2++) {
            if (part.charCodeAt(j2) > 127) {
              newpart += "x";
            } else {
              newpart += part[j2];
            }
          }
          if (!newpart.match(hostnamePartPattern)) {
            const validParts = hostparts.slice(0, i);
            const notHost = hostparts.slice(i + 1);
            const bit = part.match(hostnamePartStart);
            if (bit) {
              validParts.push(bit[1]);
              notHost.unshift(bit[2]);
            }
            if (notHost.length) {
              rest = notHost.join(".") + rest;
            }
            this.hostname = validParts.join(".");
            break;
          }
        }
      }
    }
    if (this.hostname.length > hostnameMaxLen) {
      this.hostname = "";
    }
    if (ipv6Hostname) {
      this.hostname = this.hostname.substr(1, this.hostname.length - 2);
    }
  }
  const hash2 = rest.indexOf("#");
  if (hash2 !== -1) {
    this.hash = rest.substr(hash2);
    rest = rest.slice(0, hash2);
  }
  const qm = rest.indexOf("?");
  if (qm !== -1) {
    this.search = rest.substr(qm);
    rest = rest.slice(0, qm);
  }
  if (rest) {
    this.pathname = rest;
  }
  if (slashedProtocol[lowerProto] && this.hostname && !this.pathname) {
    this.pathname = "";
  }
  return this;
};
Url.prototype.parseHost = function(host) {
  let port = portPattern.exec(host);
  if (port) {
    port = port[0];
    if (port !== ":") {
      this.port = port.substr(1);
    }
    host = host.substr(0, host.length - port.length);
  }
  if (host) {
    this.hostname = host;
  }
};
const mdurl = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ Object.defineProperty({
  __proto__: null,
  decode: decode$1,
  encode: encode$1,
  format: format$1,
  parse: urlParse
}, Symbol.toStringTag, { value: "Module" }));
const Any = /[\0-\uD7FF\uE000-\uFFFF]|[\uD800-\uDBFF][\uDC00-\uDFFF]|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?:[^\uD800-\uDBFF]|^)[\uDC00-\uDFFF]/;
const Cc = /[\0-\x1F\x7F-\x9F]/;
const regex$1 = /[\xAD\u0600-\u0605\u061C\u06DD\u070F\u0890\u0891\u08E2\u180E\u200B-\u200F\u202A-\u202E\u2060-\u2064\u2066-\u206F\uFEFF\uFFF9-\uFFFB]|\uD804[\uDCBD\uDCCD]|\uD80D[\uDC30-\uDC3F]|\uD82F[\uDCA0-\uDCA3]|\uD834[\uDD73-\uDD7A]|\uDB40[\uDC01\uDC20-\uDC7F]/;
const P = /[!-#%-\*,-\/:;\?@\[-\]_\{\}\xA1\xA7\xAB\xB6\xB7\xBB\xBF\u037E\u0387\u055A-\u055F\u0589\u058A\u05BE\u05C0\u05C3\u05C6\u05F3\u05F4\u0609\u060A\u060C\u060D\u061B\u061D-\u061F\u066A-\u066D\u06D4\u0700-\u070D\u07F7-\u07F9\u0830-\u083E\u085E\u0964\u0965\u0970\u09FD\u0A76\u0AF0\u0C77\u0C84\u0DF4\u0E4F\u0E5A\u0E5B\u0F04-\u0F12\u0F14\u0F3A-\u0F3D\u0F85\u0FD0-\u0FD4\u0FD9\u0FDA\u104A-\u104F\u10FB\u1360-\u1368\u1400\u166E\u169B\u169C\u16EB-\u16ED\u1735\u1736\u17D4-\u17D6\u17D8-\u17DA\u1800-\u180A\u1944\u1945\u1A1E\u1A1F\u1AA0-\u1AA6\u1AA8-\u1AAD\u1B5A-\u1B60\u1B7D\u1B7E\u1BFC-\u1BFF\u1C3B-\u1C3F\u1C7E\u1C7F\u1CC0-\u1CC7\u1CD3\u2010-\u2027\u2030-\u2043\u2045-\u2051\u2053-\u205E\u207D\u207E\u208D\u208E\u2308-\u230B\u2329\u232A\u2768-\u2775\u27C5\u27C6\u27E6-\u27EF\u2983-\u2998\u29D8-\u29DB\u29FC\u29FD\u2CF9-\u2CFC\u2CFE\u2CFF\u2D70\u2E00-\u2E2E\u2E30-\u2E4F\u2E52-\u2E5D\u3001-\u3003\u3008-\u3011\u3014-\u301F\u3030\u303D\u30A0\u30FB\uA4FE\uA4FF\uA60D-\uA60F\uA673\uA67E\uA6F2-\uA6F7\uA874-\uA877\uA8CE\uA8CF\uA8F8-\uA8FA\uA8FC\uA92E\uA92F\uA95F\uA9C1-\uA9CD\uA9DE\uA9DF\uAA5C-\uAA5F\uAADE\uAADF\uAAF0\uAAF1\uABEB\uFD3E\uFD3F\uFE10-\uFE19\uFE30-\uFE52\uFE54-\uFE61\uFE63\uFE68\uFE6A\uFE6B\uFF01-\uFF03\uFF05-\uFF0A\uFF0C-\uFF0F\uFF1A\uFF1B\uFF1F\uFF20\uFF3B-\uFF3D\uFF3F\uFF5B\uFF5D\uFF5F-\uFF65]|\uD800[\uDD00-\uDD02\uDF9F\uDFD0]|\uD801\uDD6F|\uD802[\uDC57\uDD1F\uDD3F\uDE50-\uDE58\uDE7F\uDEF0-\uDEF6\uDF39-\uDF3F\uDF99-\uDF9C]|\uD803[\uDEAD\uDF55-\uDF59\uDF86-\uDF89]|\uD804[\uDC47-\uDC4D\uDCBB\uDCBC\uDCBE-\uDCC1\uDD40-\uDD43\uDD74\uDD75\uDDC5-\uDDC8\uDDCD\uDDDB\uDDDD-\uDDDF\uDE38-\uDE3D\uDEA9]|\uD805[\uDC4B-\uDC4F\uDC5A\uDC5B\uDC5D\uDCC6\uDDC1-\uDDD7\uDE41-\uDE43\uDE60-\uDE6C\uDEB9\uDF3C-\uDF3E]|\uD806[\uDC3B\uDD44-\uDD46\uDDE2\uDE3F-\uDE46\uDE9A-\uDE9C\uDE9E-\uDEA2\uDF00-\uDF09]|\uD807[\uDC41-\uDC45\uDC70\uDC71\uDEF7\uDEF8\uDF43-\uDF4F\uDFFF]|\uD809[\uDC70-\uDC74]|\uD80B[\uDFF1\uDFF2]|\uD81A[\uDE6E\uDE6F\uDEF5\uDF37-\uDF3B\uDF44]|\uD81B[\uDE97-\uDE9A\uDFE2]|\uD82F\uDC9F|\uD836[\uDE87-\uDE8B]|\uD83A[\uDD5E\uDD5F]/;
const regex = /[\$\+<->\^`\|~\xA2-\xA6\xA8\xA9\xAC\xAE-\xB1\xB4\xB8\xD7\xF7\u02C2-\u02C5\u02D2-\u02DF\u02E5-\u02EB\u02ED\u02EF-\u02FF\u0375\u0384\u0385\u03F6\u0482\u058D-\u058F\u0606-\u0608\u060B\u060E\u060F\u06DE\u06E9\u06FD\u06FE\u07F6\u07FE\u07FF\u0888\u09F2\u09F3\u09FA\u09FB\u0AF1\u0B70\u0BF3-\u0BFA\u0C7F\u0D4F\u0D79\u0E3F\u0F01-\u0F03\u0F13\u0F15-\u0F17\u0F1A-\u0F1F\u0F34\u0F36\u0F38\u0FBE-\u0FC5\u0FC7-\u0FCC\u0FCE\u0FCF\u0FD5-\u0FD8\u109E\u109F\u1390-\u1399\u166D\u17DB\u1940\u19DE-\u19FF\u1B61-\u1B6A\u1B74-\u1B7C\u1FBD\u1FBF-\u1FC1\u1FCD-\u1FCF\u1FDD-\u1FDF\u1FED-\u1FEF\u1FFD\u1FFE\u2044\u2052\u207A-\u207C\u208A-\u208C\u20A0-\u20C0\u2100\u2101\u2103-\u2106\u2108\u2109\u2114\u2116-\u2118\u211E-\u2123\u2125\u2127\u2129\u212E\u213A\u213B\u2140-\u2144\u214A-\u214D\u214F\u218A\u218B\u2190-\u2307\u230C-\u2328\u232B-\u2426\u2440-\u244A\u249C-\u24E9\u2500-\u2767\u2794-\u27C4\u27C7-\u27E5\u27F0-\u2982\u2999-\u29D7\u29DC-\u29FB\u29FE-\u2B73\u2B76-\u2B95\u2B97-\u2BFF\u2CE5-\u2CEA\u2E50\u2E51\u2E80-\u2E99\u2E9B-\u2EF3\u2F00-\u2FD5\u2FF0-\u2FFF\u3004\u3012\u3013\u3020\u3036\u3037\u303E\u303F\u309B\u309C\u3190\u3191\u3196-\u319F\u31C0-\u31E3\u31EF\u3200-\u321E\u322A-\u3247\u3250\u3260-\u327F\u328A-\u32B0\u32C0-\u33FF\u4DC0-\u4DFF\uA490-\uA4C6\uA700-\uA716\uA720\uA721\uA789\uA78A\uA828-\uA82B\uA836-\uA839\uAA77-\uAA79\uAB5B\uAB6A\uAB6B\uFB29\uFBB2-\uFBC2\uFD40-\uFD4F\uFDCF\uFDFC-\uFDFF\uFE62\uFE64-\uFE66\uFE69\uFF04\uFF0B\uFF1C-\uFF1E\uFF3E\uFF40\uFF5C\uFF5E\uFFE0-\uFFE6\uFFE8-\uFFEE\uFFFC\uFFFD]|\uD800[\uDD37-\uDD3F\uDD79-\uDD89\uDD8C-\uDD8E\uDD90-\uDD9C\uDDA0\uDDD0-\uDDFC]|\uD802[\uDC77\uDC78\uDEC8]|\uD805\uDF3F|\uD807[\uDFD5-\uDFF1]|\uD81A[\uDF3C-\uDF3F\uDF45]|\uD82F\uDC9C|\uD833[\uDF50-\uDFC3]|\uD834[\uDC00-\uDCF5\uDD00-\uDD26\uDD29-\uDD64\uDD6A-\uDD6C\uDD83\uDD84\uDD8C-\uDDA9\uDDAE-\uDDEA\uDE00-\uDE41\uDE45\uDF00-\uDF56]|\uD835[\uDEC1\uDEDB\uDEFB\uDF15\uDF35\uDF4F\uDF6F\uDF89\uDFA9\uDFC3]|\uD836[\uDC00-\uDDFF\uDE37-\uDE3A\uDE6D-\uDE74\uDE76-\uDE83\uDE85\uDE86]|\uD838[\uDD4F\uDEFF]|\uD83B[\uDCAC\uDCB0\uDD2E\uDEF0\uDEF1]|\uD83C[\uDC00-\uDC2B\uDC30-\uDC93\uDCA0-\uDCAE\uDCB1-\uDCBF\uDCC1-\uDCCF\uDCD1-\uDCF5\uDD0D-\uDDAD\uDDE6-\uDE02\uDE10-\uDE3B\uDE40-\uDE48\uDE50\uDE51\uDE60-\uDE65\uDF00-\uDFFF]|\uD83D[\uDC00-\uDED7\uDEDC-\uDEEC\uDEF0-\uDEFC\uDF00-\uDF76\uDF7B-\uDFD9\uDFE0-\uDFEB\uDFF0]|\uD83E[\uDC00-\uDC0B\uDC10-\uDC47\uDC50-\uDC59\uDC60-\uDC87\uDC90-\uDCAD\uDCB0\uDCB1\uDD00-\uDE53\uDE60-\uDE6D\uDE70-\uDE7C\uDE80-\uDE88\uDE90-\uDEBD\uDEBF-\uDEC5\uDECE-\uDEDB\uDEE0-\uDEE8\uDEF0-\uDEF8\uDF00-\uDF92\uDF94-\uDFCA]/;
const Z = /[ \xA0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]/;
const ucmicro = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ Object.defineProperty({
  __proto__: null,
  Any,
  Cc,
  Cf: regex$1,
  P,
  S: regex,
  Z
}, Symbol.toStringTag, { value: "Module" }));
const htmlDecodeTree = new Uint16Array(
  // prettier-ignore
  'ᵁ<Õıʊҝջאٵ۞ޢߖࠏ੊ઑඡ๭༉༦჊ረዡᐕᒝᓃᓟᔥ\0\0\0\0\0\0ᕫᛍᦍᰒᷝ὾⁠↰⊍⏀⏻⑂⠤⤒ⴈ⹈⿎〖㊺㘹㞬㣾㨨㩱㫠㬮ࠀEMabcfglmnoprstu\\bfms¦³¹ÈÏlig耻Æ䃆P耻&䀦cute耻Á䃁reve;䄂Āiyx}rc耻Â䃂;䐐r;쀀𝔄rave耻À䃀pha;䎑acr;䄀d;橓Āgp¡on;䄄f;쀀𝔸plyFunction;恡ing耻Å䃅Ācs¾Ãr;쀀𝒜ign;扔ilde耻Ã䃃ml耻Ä䃄ЀaceforsuåûþėĜĢħĪĀcrêòkslash;或Ŷöø;櫧ed;挆y;䐑ƀcrtąċĔause;戵noullis;愬a;䎒r;쀀𝔅pf;쀀𝔹eve;䋘còēmpeq;扎܀HOacdefhilorsuōőŖƀƞƢƵƷƺǜȕɳɸɾcy;䐧PY耻©䂩ƀcpyŝŢźute;䄆Ā;iŧŨ拒talDifferentialD;慅leys;愭ȀaeioƉƎƔƘron;䄌dil耻Ç䃇rc;䄈nint;戰ot;䄊ĀdnƧƭilla;䂸terDot;䂷òſi;䎧rcleȀDMPTǇǋǑǖot;抙inus;抖lus;投imes;抗oĀcsǢǸkwiseContourIntegral;戲eCurlyĀDQȃȏoubleQuote;思uote;怙ȀlnpuȞȨɇɕonĀ;eȥȦ户;橴ƀgitȯȶȺruent;扡nt;戯ourIntegral;戮ĀfrɌɎ;愂oduct;成nterClockwiseContourIntegral;戳oss;樯cr;쀀𝒞pĀ;Cʄʅ拓ap;才րDJSZacefiosʠʬʰʴʸˋ˗ˡ˦̳ҍĀ;oŹʥtrahd;椑cy;䐂cy;䐅cy;䐏ƀgrsʿ˄ˇger;怡r;憡hv;櫤Āayː˕ron;䄎;䐔lĀ;t˝˞戇a;䎔r;쀀𝔇Āaf˫̧Ācm˰̢riticalȀADGT̖̜̀̆cute;䂴oŴ̋̍;䋙bleAcute;䋝rave;䁠ilde;䋜ond;拄ferentialD;慆Ѱ̽\0\0\0͔͂\0Ѕf;쀀𝔻ƀ;DE͈͉͍䂨ot;惜qual;扐blèCDLRUVͣͲ΂ϏϢϸontourIntegraìȹoɴ͹\0\0ͻ»͉nArrow;懓Āeo·ΤftƀARTΐΖΡrrow;懐ightArrow;懔eåˊngĀLRΫτeftĀARγιrrow;柸ightArrow;柺ightArrow;柹ightĀATϘϞrrow;懒ee;抨pɁϩ\0\0ϯrrow;懑ownArrow;懕erticalBar;戥ǹABLRTaВЪаўѿͼrrowƀ;BUНОТ憓ar;椓pArrow;懵reve;䌑eft˒к\0ц\0ѐightVector;楐eeVector;楞ectorĀ;Bљњ憽ar;楖ightǔѧ\0ѱeeVector;楟ectorĀ;BѺѻ懁ar;楗eeĀ;A҆҇护rrow;憧ĀctҒҗr;쀀𝒟rok;䄐ࠀNTacdfglmopqstuxҽӀӄӋӞӢӧӮӵԡԯԶՒ՝ՠեG;䅊H耻Ð䃐cute耻É䃉ƀaiyӒӗӜron;䄚rc耻Ê䃊;䐭ot;䄖r;쀀𝔈rave耻È䃈ement;戈ĀapӺӾcr;䄒tyɓԆ\0\0ԒmallSquare;旻erySmallSquare;斫ĀgpԦԪon;䄘f;쀀𝔼silon;䎕uĀaiԼՉlĀ;TՂՃ橵ilde;扂librium;懌Āci՗՚r;愰m;橳a;䎗ml耻Ë䃋Āipժկsts;戃onentialE;慇ʀcfiosօֈ֍ֲ׌y;䐤r;쀀𝔉lledɓ֗\0\0֣mallSquare;旼erySmallSquare;斪Ͱֺ\0ֿ\0\0ׄf;쀀𝔽All;戀riertrf;愱cò׋؀JTabcdfgorstר׬ׯ׺؀ؒؖ؛؝أ٬ٲcy;䐃耻>䀾mmaĀ;d׷׸䎓;䏜reve;䄞ƀeiy؇،ؐdil;䄢rc;䄜;䐓ot;䄠r;쀀𝔊;拙pf;쀀𝔾eater̀EFGLSTصلَٖٛ٦qualĀ;Lؾؿ扥ess;招ullEqual;执reater;檢ess;扷lantEqual;橾ilde;扳cr;쀀𝒢;扫ЀAacfiosuڅڋږڛڞڪھۊRDcy;䐪Āctڐڔek;䋇;䁞irc;䄤r;愌lbertSpace;愋ǰگ\0ڲf;愍izontalLine;攀Āctۃۅòکrok;䄦mpńېۘownHumðįqual;扏܀EJOacdfgmnostuۺ۾܃܇܎ܚܞܡܨ݄ݸދޏޕcy;䐕lig;䄲cy;䐁cute耻Í䃍Āiyܓܘrc耻Î䃎;䐘ot;䄰r;愑rave耻Ì䃌ƀ;apܠܯܿĀcgܴܷr;䄪inaryI;慈lieóϝǴ݉\0ݢĀ;eݍݎ戬Āgrݓݘral;戫section;拂isibleĀCTݬݲomma;恣imes;恢ƀgptݿރވon;䄮f;쀀𝕀a;䎙cr;愐ilde;䄨ǫޚ\0ޞcy;䐆l耻Ï䃏ʀcfosuެ޷޼߂ߐĀiyޱ޵rc;䄴;䐙r;쀀𝔍pf;쀀𝕁ǣ߇\0ߌr;쀀𝒥rcy;䐈kcy;䐄΀HJacfosߤߨ߽߬߱ࠂࠈcy;䐥cy;䐌ppa;䎚Āey߶߻dil;䄶;䐚r;쀀𝔎pf;쀀𝕂cr;쀀𝒦րJTaceflmostࠥࠩࠬࡐࡣ঳সে্਷ੇcy;䐉耻<䀼ʀcmnpr࠷࠼ࡁࡄࡍute;䄹bda;䎛g;柪lacetrf;愒r;憞ƀaeyࡗ࡜ࡡron;䄽dil;䄻;䐛Āfsࡨ॰tԀACDFRTUVarࡾࢩࢱࣦ࣠ࣼयज़ΐ४Ānrࢃ࢏gleBracket;柨rowƀ;BR࢙࢚࢞憐ar;懤ightArrow;懆eiling;挈oǵࢷ\0ࣃbleBracket;柦nǔࣈ\0࣒eeVector;楡ectorĀ;Bࣛࣜ懃ar;楙loor;挊ightĀAV࣯ࣵrrow;憔ector;楎Āerँगeƀ;AVउऊऐ抣rrow;憤ector;楚iangleƀ;BEतथऩ抲ar;槏qual;抴pƀDTVषूौownVector;楑eeVector;楠ectorĀ;Bॖॗ憿ar;楘ectorĀ;B॥०憼ar;楒ightáΜs̀EFGLSTॾঋকঝঢভqualGreater;拚ullEqual;扦reater;扶ess;檡lantEqual;橽ilde;扲r;쀀𝔏Ā;eঽা拘ftarrow;懚idot;䄿ƀnpw৔ਖਛgȀLRlr৞৷ਂਐeftĀAR০৬rrow;柵ightArrow;柷ightArrow;柶eftĀarγਊightáοightáϊf;쀀𝕃erĀLRਢਬeftArrow;憙ightArrow;憘ƀchtਾੀੂòࡌ;憰rok;䅁;扪Ѐacefiosuਗ਼੝੠੷੼અઋ઎p;椅y;䐜Ādl੥੯iumSpace;恟lintrf;愳r;쀀𝔐nusPlus;戓pf;쀀𝕄cò੶;䎜ҀJacefostuણધભીଔଙඑ඗ඞcy;䐊cute;䅃ƀaey઴હાron;䅇dil;䅅;䐝ƀgswે૰଎ativeƀMTV૓૟૨ediumSpace;怋hiĀcn૦૘ë૙eryThiî૙tedĀGL૸ଆreaterGreateòٳessLesóੈLine;䀊r;쀀𝔑ȀBnptଢନଷ଺reak;恠BreakingSpace;䂠f;愕ڀ;CDEGHLNPRSTV୕ୖ୪୼஡௫ఄ౞಄ದ೘ൡඅ櫬Āou୛୤ngruent;扢pCap;扭oubleVerticalBar;戦ƀlqxஃஊ஛ement;戉ualĀ;Tஒஓ扠ilde;쀀≂̸ists;戄reater΀;EFGLSTஶஷ஽௉௓௘௥扯qual;扱ullEqual;쀀≧̸reater;쀀≫̸ess;批lantEqual;쀀⩾̸ilde;扵umpń௲௽ownHump;쀀≎̸qual;쀀≏̸eĀfsఊధtTriangleƀ;BEచఛడ拪ar;쀀⧏̸qual;括s̀;EGLSTవశ఼ౄోౘ扮qual;扰reater;扸ess;쀀≪̸lantEqual;쀀⩽̸ilde;扴estedĀGL౨౹reaterGreater;쀀⪢̸essLess;쀀⪡̸recedesƀ;ESಒಓಛ技qual;쀀⪯̸lantEqual;拠ĀeiಫಹverseElement;戌ghtTriangleƀ;BEೋೌ೒拫ar;쀀⧐̸qual;拭ĀquೝഌuareSuĀbp೨೹setĀ;E೰ೳ쀀⊏̸qual;拢ersetĀ;Eഃആ쀀⊐̸qual;拣ƀbcpഓതൎsetĀ;Eഛഞ쀀⊂⃒qual;抈ceedsȀ;ESTലള഻െ抁qual;쀀⪰̸lantEqual;拡ilde;쀀≿̸ersetĀ;E൘൛쀀⊃⃒qual;抉ildeȀ;EFT൮൯൵ൿ扁qual;扄ullEqual;扇ilde;扉erticalBar;戤cr;쀀𝒩ilde耻Ñ䃑;䎝܀Eacdfgmoprstuvලෂ෉෕ෛ෠෧෼ขภยา฿ไlig;䅒cute耻Ó䃓Āiy෎ීrc耻Ô䃔;䐞blac;䅐r;쀀𝔒rave耻Ò䃒ƀaei෮ෲ෶cr;䅌ga;䎩cron;䎟pf;쀀𝕆enCurlyĀDQฎบoubleQuote;怜uote;怘;橔Āclวฬr;쀀𝒪ash耻Ø䃘iŬื฼de耻Õ䃕es;樷ml耻Ö䃖erĀBP๋๠Āar๐๓r;怾acĀek๚๜;揞et;掴arenthesis;揜Ҁacfhilors๿ງຊຏຒດຝະ໼rtialD;戂y;䐟r;쀀𝔓i;䎦;䎠usMinus;䂱Āipຢອncareplanåڝf;愙Ȁ;eio຺ູ໠໤檻cedesȀ;EST່້໏໚扺qual;檯lantEqual;扼ilde;找me;怳Ādp໩໮uct;戏ortionĀ;aȥ໹l;戝Āci༁༆r;쀀𝒫;䎨ȀUfos༑༖༛༟OT耻"䀢r;쀀𝔔pf;愚cr;쀀𝒬؀BEacefhiorsu༾གྷཇའཱིྦྷྪྭ႖ႩႴႾarr;椐G耻®䂮ƀcnrཎནབute;䅔g;柫rĀ;tཛྷཝ憠l;椖ƀaeyཧཬཱron;䅘dil;䅖;䐠Ā;vླྀཹ愜erseĀEUྂྙĀlq྇ྎement;戋uilibrium;懋pEquilibrium;楯r»ཹo;䎡ghtЀACDFTUVa࿁࿫࿳ဢဨၛႇϘĀnr࿆࿒gleBracket;柩rowƀ;BL࿜࿝࿡憒ar;懥eftArrow;懄eiling;按oǵ࿹\0စbleBracket;柧nǔည\0နeeVector;楝ectorĀ;Bဝသ懂ar;楕loor;挋Āerိ၃eƀ;AVဵံြ抢rrow;憦ector;楛iangleƀ;BEၐၑၕ抳ar;槐qual;抵pƀDTVၣၮၸownVector;楏eeVector;楜ectorĀ;Bႂႃ憾ar;楔ectorĀ;B႑႒懀ar;楓Āpuႛ႞f;愝ndImplies;楰ightarrow;懛ĀchႹႼr;愛;憱leDelayed;槴ڀHOacfhimoqstuფჱჷჽᄙᄞᅑᅖᅡᅧᆵᆻᆿĀCcჩხHcy;䐩y;䐨FTcy;䐬cute;䅚ʀ;aeiyᄈᄉᄎᄓᄗ檼ron;䅠dil;䅞rc;䅜;䐡r;쀀𝔖ortȀDLRUᄪᄴᄾᅉownArrow»ОeftArrow»࢚ightArrow»࿝pArrow;憑gma;䎣allCircle;战pf;쀀𝕊ɲᅭ\0\0ᅰt;戚areȀ;ISUᅻᅼᆉᆯ斡ntersection;抓uĀbpᆏᆞsetĀ;Eᆗᆘ抏qual;抑ersetĀ;Eᆨᆩ抐qual;抒nion;抔cr;쀀𝒮ar;拆ȀbcmpᇈᇛሉላĀ;sᇍᇎ拐etĀ;Eᇍᇕqual;抆ĀchᇠህeedsȀ;ESTᇭᇮᇴᇿ扻qual;檰lantEqual;扽ilde;承Tháྌ;我ƀ;esሒሓሣ拑rsetĀ;Eሜም抃qual;抇et»ሓրHRSacfhiorsሾቄ቉ቕ቞ቱቶኟዂወዑORN耻Þ䃞ADE;愢ĀHc቎ቒcy;䐋y;䐦Ābuቚቜ;䀉;䎤ƀaeyብቪቯron;䅤dil;䅢;䐢r;쀀𝔗Āeiቻ኉ǲኀ\0ኇefore;戴a;䎘Ācn኎ኘkSpace;쀀  Space;怉ldeȀ;EFTካኬኲኼ戼qual;扃ullEqual;扅ilde;扈pf;쀀𝕋ipleDot;惛Āctዖዛr;쀀𝒯rok;䅦ૡዷጎጚጦ\0ጬጱ\0\0\0\0\0ጸጽ፷ᎅ\0᏿ᐄᐊᐐĀcrዻጁute耻Ú䃚rĀ;oጇገ憟cir;楉rǣጓ\0጖y;䐎ve;䅬Āiyጞጣrc耻Û䃛;䐣blac;䅰r;쀀𝔘rave耻Ù䃙acr;䅪Ādiፁ፩erĀBPፈ፝Āarፍፐr;䁟acĀekፗፙ;揟et;掵arenthesis;揝onĀ;P፰፱拃lus;抎Āgp፻፿on;䅲f;쀀𝕌ЀADETadps᎕ᎮᎸᏄϨᏒᏗᏳrrowƀ;BDᅐᎠᎤar;椒ownArrow;懅ownArrow;憕quilibrium;楮eeĀ;AᏋᏌ报rrow;憥ownáϳerĀLRᏞᏨeftArrow;憖ightArrow;憗iĀ;lᏹᏺ䏒on;䎥ing;䅮cr;쀀𝒰ilde;䅨ml耻Ü䃜ҀDbcdefosvᐧᐬᐰᐳᐾᒅᒊᒐᒖash;披ar;櫫y;䐒ashĀ;lᐻᐼ抩;櫦Āerᑃᑅ;拁ƀbtyᑌᑐᑺar;怖Ā;iᑏᑕcalȀBLSTᑡᑥᑪᑴar;戣ine;䁼eparator;杘ilde;所ThinSpace;怊r;쀀𝔙pf;쀀𝕍cr;쀀𝒱dash;抪ʀcefosᒧᒬᒱᒶᒼirc;䅴dge;拀r;쀀𝔚pf;쀀𝕎cr;쀀𝒲Ȁfiosᓋᓐᓒᓘr;쀀𝔛;䎞pf;쀀𝕏cr;쀀𝒳ҀAIUacfosuᓱᓵᓹᓽᔄᔏᔔᔚᔠcy;䐯cy;䐇cy;䐮cute耻Ý䃝Āiyᔉᔍrc;䅶;䐫r;쀀𝔜pf;쀀𝕐cr;쀀𝒴ml;䅸ЀHacdefosᔵᔹᔿᕋᕏᕝᕠᕤcy;䐖cute;䅹Āayᕄᕉron;䅽;䐗ot;䅻ǲᕔ\0ᕛoWidtè૙a;䎖r;愨pf;愤cr;쀀𝒵௡ᖃᖊᖐ\0ᖰᖶᖿ\0\0\0\0ᗆᗛᗫᙟ᙭\0ᚕ᚛ᚲᚹ\0ᚾcute耻á䃡reve;䄃̀;Ediuyᖜᖝᖡᖣᖨᖭ戾;쀀∾̳;房rc耻â䃢te肻´̆;䐰lig耻æ䃦Ā;r²ᖺ;쀀𝔞rave耻à䃠ĀepᗊᗖĀfpᗏᗔsym;愵èᗓha;䎱ĀapᗟcĀclᗤᗧr;䄁g;樿ɤᗰ\0\0ᘊʀ;adsvᗺᗻᗿᘁᘇ戧nd;橕;橜lope;橘;橚΀;elmrszᘘᘙᘛᘞᘿᙏᙙ戠;榤e»ᘙsdĀ;aᘥᘦ戡ѡᘰᘲᘴᘶᘸᘺᘼᘾ;榨;榩;榪;榫;榬;榭;榮;榯tĀ;vᙅᙆ戟bĀ;dᙌᙍ抾;榝Āptᙔᙗh;戢»¹arr;捼Āgpᙣᙧon;䄅f;쀀𝕒΀;Eaeiop዁ᙻᙽᚂᚄᚇᚊ;橰cir;橯;扊d;手s;䀧roxĀ;e዁ᚒñᚃing耻å䃥ƀctyᚡᚦᚨr;쀀𝒶;䀪mpĀ;e዁ᚯñʈilde耻ã䃣ml耻ä䃤Āciᛂᛈoninôɲnt;樑ࠀNabcdefiklnoprsu᛭ᛱᜰ᜼ᝃᝈ᝸᝽០៦ᠹᡐᜍ᤽᥈ᥰot;櫭Ācrᛶ᜞kȀcepsᜀᜅᜍᜓong;扌psilon;䏶rime;怵imĀ;e᜚᜛戽q;拍Ŷᜢᜦee;抽edĀ;gᜬᜭ挅e»ᜭrkĀ;t፜᜷brk;掶Āoyᜁᝁ;䐱quo;怞ʀcmprtᝓ᝛ᝡᝤᝨausĀ;eĊĉptyv;榰séᜌnoõēƀahwᝯ᝱ᝳ;䎲;愶een;扬r;쀀𝔟g΀costuvwឍឝឳេ៕៛៞ƀaiuបពរðݠrc;旯p»፱ƀdptឤឨឭot;樀lus;樁imes;樂ɱឹ\0\0ើcup;樆ar;昅riangleĀdu៍្own;施p;斳plus;樄eåᑄåᒭarow;植ƀako៭ᠦᠵĀcn៲ᠣkƀlst៺֫᠂ozenge;槫riangleȀ;dlr᠒᠓᠘᠝斴own;斾eft;旂ight;斸k;搣Ʊᠫ\0ᠳƲᠯ\0ᠱ;斒;斑4;斓ck;斈ĀeoᠾᡍĀ;qᡃᡆ쀀=⃥uiv;쀀≡⃥t;挐Ȁptwxᡙᡞᡧᡬf;쀀𝕓Ā;tᏋᡣom»Ꮜtie;拈؀DHUVbdhmptuvᢅᢖᢪᢻᣗᣛᣬ᣿ᤅᤊᤐᤡȀLRlrᢎᢐᢒᢔ;敗;敔;敖;敓ʀ;DUduᢡᢢᢤᢦᢨ敐;敦;敩;敤;敧ȀLRlrᢳᢵᢷᢹ;敝;敚;敜;教΀;HLRhlrᣊᣋᣍᣏᣑᣓᣕ救;敬;散;敠;敫;敢;敟ox;槉ȀLRlrᣤᣦᣨᣪ;敕;敒;攐;攌ʀ;DUduڽ᣷᣹᣻᣽;敥;敨;攬;攴inus;抟lus;択imes;抠ȀLRlrᤙᤛᤝ᤟;敛;敘;攘;攔΀;HLRhlrᤰᤱᤳᤵᤷ᤻᤹攂;敪;敡;敞;攼;攤;攜Āevģ᥂bar耻¦䂦Ȁceioᥑᥖᥚᥠr;쀀𝒷mi;恏mĀ;e᜚᜜lƀ;bhᥨᥩᥫ䁜;槅sub;柈Ŭᥴ᥾lĀ;e᥹᥺怢t»᥺pƀ;Eeįᦅᦇ;檮Ā;qۜۛೡᦧ\0᧨ᨑᨕᨲ\0ᨷᩐ\0\0᪴\0\0᫁\0\0ᬡᬮ᭍᭒\0᯽\0ᰌƀcpr᦭ᦲ᧝ute;䄇̀;abcdsᦿᧀᧄ᧊᧕᧙戩nd;橄rcup;橉Āau᧏᧒p;橋p;橇ot;橀;쀀∩︀Āeo᧢᧥t;恁îړȀaeiu᧰᧻ᨁᨅǰ᧵\0᧸s;橍on;䄍dil耻ç䃧rc;䄉psĀ;sᨌᨍ橌m;橐ot;䄋ƀdmnᨛᨠᨦil肻¸ƭptyv;榲t脀¢;eᨭᨮ䂢räƲr;쀀𝔠ƀceiᨽᩀᩍy;䑇ckĀ;mᩇᩈ朓ark»ᩈ;䏇r΀;Ecefms᩟᩠ᩢᩫ᪤᪪᪮旋;槃ƀ;elᩩᩪᩭ䋆q;扗eɡᩴ\0\0᪈rrowĀlr᩼᪁eft;憺ight;憻ʀRSacd᪒᪔᪖᪚᪟»ཇ;擈st;抛irc;抚ash;抝nint;樐id;櫯cir;槂ubsĀ;u᪻᪼晣it»᪼ˬ᫇᫔᫺\0ᬊonĀ;eᫍᫎ䀺Ā;qÇÆɭ᫙\0\0᫢aĀ;t᫞᫟䀬;䁀ƀ;fl᫨᫩᫫戁îᅠeĀmx᫱᫶ent»᫩eóɍǧ᫾\0ᬇĀ;dኻᬂot;橭nôɆƀfryᬐᬔᬗ;쀀𝕔oäɔ脀©;sŕᬝr;愗Āaoᬥᬩrr;憵ss;朗Ācuᬲᬷr;쀀𝒸Ābpᬼ᭄Ā;eᭁᭂ櫏;櫑Ā;eᭉᭊ櫐;櫒dot;拯΀delprvw᭠᭬᭷ᮂᮬᯔ᯹arrĀlr᭨᭪;椸;椵ɰ᭲\0\0᭵r;拞c;拟arrĀ;p᭿ᮀ憶;椽̀;bcdosᮏᮐᮖᮡᮥᮨ截rcap;橈Āauᮛᮞp;橆p;橊ot;抍r;橅;쀀∪︀Ȁalrv᮵ᮿᯞᯣrrĀ;mᮼᮽ憷;椼yƀevwᯇᯔᯘqɰᯎ\0\0ᯒreã᭳uã᭵ee;拎edge;拏en耻¤䂤earrowĀlrᯮ᯳eft»ᮀight»ᮽeäᯝĀciᰁᰇoninôǷnt;戱lcty;挭ঀAHabcdefhijlorstuwz᰸᰻᰿ᱝᱩᱵᲊᲞᲬᲷ᳻᳿ᴍᵻᶑᶫᶻ᷆᷍rò΁ar;楥Ȁglrs᱈ᱍ᱒᱔ger;怠eth;愸òᄳhĀ;vᱚᱛ怐»ऊūᱡᱧarow;椏aã̕Āayᱮᱳron;䄏;䐴ƀ;ao̲ᱼᲄĀgrʿᲁr;懊tseq;橷ƀglmᲑᲔᲘ耻°䂰ta;䎴ptyv;榱ĀirᲣᲨsht;楿;쀀𝔡arĀlrᲳᲵ»ࣜ»သʀaegsv᳂͸᳖᳜᳠mƀ;oș᳊᳔ndĀ;ș᳑uit;晦amma;䏝in;拲ƀ;io᳧᳨᳸䃷de脀÷;o᳧ᳰntimes;拇nø᳷cy;䑒cɯᴆ\0\0ᴊrn;挞op;挍ʀlptuwᴘᴝᴢᵉᵕlar;䀤f;쀀𝕕ʀ;emps̋ᴭᴷᴽᵂqĀ;d͒ᴳot;扑inus;戸lus;戔quare;抡blebarwedgåúnƀadhᄮᵝᵧownarrowóᲃarpoonĀlrᵲᵶefôᲴighôᲶŢᵿᶅkaro÷གɯᶊ\0\0ᶎrn;挟op;挌ƀcotᶘᶣᶦĀryᶝᶡ;쀀𝒹;䑕l;槶rok;䄑Ādrᶰᶴot;拱iĀ;fᶺ᠖斿Āah᷀᷃ròЩaòྦangle;榦Āci᷒ᷕy;䑟grarr;柿ऀDacdefglmnopqrstuxḁḉḙḸոḼṉṡṾấắẽỡἪἷὄ὎὚ĀDoḆᴴoôᲉĀcsḎḔute耻é䃩ter;橮ȀaioyḢḧḱḶron;䄛rĀ;cḭḮ扖耻ê䃪lon;払;䑍ot;䄗ĀDrṁṅot;扒;쀀𝔢ƀ;rsṐṑṗ檚ave耻è䃨Ā;dṜṝ檖ot;檘Ȁ;ilsṪṫṲṴ檙nters;揧;愓Ā;dṹṺ檕ot;檗ƀapsẅẉẗcr;䄓tyƀ;svẒẓẕ戅et»ẓpĀ1;ẝẤĳạả;怄;怅怃ĀgsẪẬ;䅋p;怂ĀgpẴẸon;䄙f;쀀𝕖ƀalsỄỎỒrĀ;sỊị拕l;槣us;橱iƀ;lvỚớở䎵on»ớ;䏵ȀcsuvỪỳἋἣĀioữḱrc»Ḯɩỹ\0\0ỻíՈantĀglἂἆtr»ṝess»Ṻƀaeiἒ἖Ἒls;䀽st;扟vĀ;DȵἠD;橸parsl;槥ĀDaἯἳot;打rr;楱ƀcdiἾὁỸr;愯oô͒ĀahὉὋ;䎷耻ð䃰Āmrὓὗl耻ë䃫o;悬ƀcipὡὤὧl;䀡sôծĀeoὬὴctatioîՙnentialåչৡᾒ\0ᾞ\0ᾡᾧ\0\0ῆῌ\0ΐ\0ῦῪ \0 ⁚llingdotseñṄy;䑄male;晀ƀilrᾭᾳ῁lig;耀ﬃɩᾹ\0\0᾽g;耀ﬀig;耀ﬄ;쀀𝔣lig;耀ﬁlig;쀀fjƀaltῙ῜ῡt;晭ig;耀ﬂns;斱of;䆒ǰ΅\0ῳf;쀀𝕗ĀakֿῷĀ;vῼ´拔;櫙artint;樍Āao‌⁕Ācs‑⁒α‚‰‸⁅⁈\0⁐β•‥‧‪‬\0‮耻½䂽;慓耻¼䂼;慕;慙;慛Ƴ‴\0‶;慔;慖ʴ‾⁁\0\0⁃耻¾䂾;慗;慜5;慘ƶ⁌\0⁎;慚;慝8;慞l;恄wn;挢cr;쀀𝒻ࢀEabcdefgijlnorstv₂₉₟₥₰₴⃰⃵⃺⃿℃ℒℸ̗ℾ⅒↞Ā;lٍ₇;檌ƀcmpₐₕ₝ute;䇵maĀ;dₜ᳚䎳;檆reve;䄟Āiy₪₮rc;䄝;䐳ot;䄡Ȁ;lqsؾق₽⃉ƀ;qsؾٌ⃄lanô٥Ȁ;cdl٥⃒⃥⃕c;檩otĀ;o⃜⃝檀Ā;l⃢⃣檂;檄Ā;e⃪⃭쀀⋛︀s;檔r;쀀𝔤Ā;gٳ؛mel;愷cy;䑓Ȁ;Eajٚℌℎℐ;檒;檥;檤ȀEaesℛℝ℩ℴ;扩pĀ;p℣ℤ檊rox»ℤĀ;q℮ℯ檈Ā;q℮ℛim;拧pf;쀀𝕘Āci⅃ⅆr;愊mƀ;el٫ⅎ⅐;檎;檐茀>;cdlqr׮ⅠⅪⅮⅳⅹĀciⅥⅧ;檧r;橺ot;拗Par;榕uest;橼ʀadelsↄⅪ←ٖ↛ǰ↉\0↎proø₞r;楸qĀlqؿ↖lesó₈ií٫Āen↣↭rtneqq;쀀≩︀Å↪ԀAabcefkosy⇄⇇⇱⇵⇺∘∝∯≨≽ròΠȀilmr⇐⇔⇗⇛rsðᒄf»․ilôکĀdr⇠⇤cy;䑊ƀ;cwࣴ⇫⇯ir;楈;憭ar;意irc;䄥ƀalr∁∎∓rtsĀ;u∉∊晥it»∊lip;怦con;抹r;쀀𝔥sĀew∣∩arow;椥arow;椦ʀamopr∺∾≃≞≣rr;懿tht;戻kĀlr≉≓eftarrow;憩ightarrow;憪f;쀀𝕙bar;怕ƀclt≯≴≸r;쀀𝒽asè⇴rok;䄧Ābp⊂⊇ull;恃hen»ᱛૡ⊣\0⊪\0⊸⋅⋎\0⋕⋳\0\0⋸⌢⍧⍢⍿\0⎆⎪⎴cute耻í䃭ƀ;iyݱ⊰⊵rc耻î䃮;䐸Ācx⊼⊿y;䐵cl耻¡䂡ĀfrΟ⋉;쀀𝔦rave耻ì䃬Ȁ;inoܾ⋝⋩⋮Āin⋢⋦nt;樌t;戭fin;槜ta;愩lig;䄳ƀaop⋾⌚⌝ƀcgt⌅⌈⌗r;䄫ƀelpܟ⌏⌓inåގarôܠh;䄱f;抷ed;䆵ʀ;cfotӴ⌬⌱⌽⍁are;愅inĀ;t⌸⌹戞ie;槝doô⌙ʀ;celpݗ⍌⍐⍛⍡al;抺Āgr⍕⍙eróᕣã⍍arhk;樗rod;樼Ȁcgpt⍯⍲⍶⍻y;䑑on;䄯f;쀀𝕚a;䎹uest耻¿䂿Āci⎊⎏r;쀀𝒾nʀ;EdsvӴ⎛⎝⎡ӳ;拹ot;拵Ā;v⎦⎧拴;拳Ā;iݷ⎮lde;䄩ǫ⎸\0⎼cy;䑖l耻ï䃯̀cfmosu⏌⏗⏜⏡⏧⏵Āiy⏑⏕rc;䄵;䐹r;쀀𝔧ath;䈷pf;쀀𝕛ǣ⏬\0⏱r;쀀𝒿rcy;䑘kcy;䑔Ѐacfghjos␋␖␢␧␭␱␵␻ppaĀ;v␓␔䎺;䏰Āey␛␠dil;䄷;䐺r;쀀𝔨reen;䄸cy;䑅cy;䑜pf;쀀𝕜cr;쀀𝓀஀ABEHabcdefghjlmnoprstuv⑰⒁⒆⒍⒑┎┽╚▀♎♞♥♹♽⚚⚲⛘❝❨➋⟀⠁⠒ƀart⑷⑺⑼rò৆òΕail;椛arr;椎Ā;gঔ⒋;檋ar;楢ॣ⒥\0⒪\0⒱\0\0\0\0\0⒵Ⓔ\0ⓆⓈⓍ\0⓹ute;䄺mptyv;榴raîࡌbda;䎻gƀ;dlࢎⓁⓃ;榑åࢎ;檅uo耻«䂫rЀ;bfhlpst࢙ⓞⓦⓩ⓫⓮⓱⓵Ā;f࢝ⓣs;椟s;椝ë≒p;憫l;椹im;楳l;憢ƀ;ae⓿─┄檫il;椙Ā;s┉┊檭;쀀⪭︀ƀabr┕┙┝rr;椌rk;杲Āak┢┬cĀek┨┪;䁻;䁛Āes┱┳;榋lĀdu┹┻;榏;榍Ȁaeuy╆╋╖╘ron;䄾Ādi═╔il;䄼ìࢰâ┩;䐻Ȁcqrs╣╦╭╽a;椶uoĀ;rนᝆĀdu╲╷har;楧shar;楋h;憲ʀ;fgqs▋▌উ◳◿扤tʀahlrt▘▤▷◂◨rrowĀ;t࢙□aé⓶arpoonĀdu▯▴own»њp»०eftarrows;懇ightƀahs◍◖◞rrowĀ;sࣴࢧarpoonó྘quigarro÷⇰hreetimes;拋ƀ;qs▋ও◺lanôবʀ;cdgsব☊☍☝☨c;檨otĀ;o☔☕橿Ā;r☚☛檁;檃Ā;e☢☥쀀⋚︀s;檓ʀadegs☳☹☽♉♋pproøⓆot;拖qĀgq♃♅ôউgtò⒌ôছiíলƀilr♕࣡♚sht;楼;쀀𝔩Ā;Eজ♣;檑š♩♶rĀdu▲♮Ā;l॥♳;楪lk;斄cy;䑙ʀ;achtੈ⚈⚋⚑⚖rò◁orneòᴈard;楫ri;旺Āio⚟⚤dot;䅀ustĀ;a⚬⚭掰che»⚭ȀEaes⚻⚽⛉⛔;扨pĀ;p⛃⛄檉rox»⛄Ā;q⛎⛏檇Ā;q⛎⚻im;拦Ѐabnoptwz⛩⛴⛷✚✯❁❇❐Ānr⛮⛱g;柬r;懽rëࣁgƀlmr⛿✍✔eftĀar০✇ightá৲apsto;柼ightá৽parrowĀlr✥✩efô⓭ight;憬ƀafl✶✹✽r;榅;쀀𝕝us;樭imes;樴š❋❏st;戗áፎƀ;ef❗❘᠀旊nge»❘arĀ;l❤❥䀨t;榓ʀachmt❳❶❼➅➇ròࢨorneòᶌarĀ;d྘➃;業;怎ri;抿̀achiqt➘➝ੀ➢➮➻quo;怹r;쀀𝓁mƀ;egল➪➬;檍;檏Ābu┪➳oĀ;rฟ➹;怚rok;䅂萀<;cdhilqrࠫ⟒☹⟜⟠⟥⟪⟰Āci⟗⟙;檦r;橹reå◲mes;拉arr;楶uest;橻ĀPi⟵⟹ar;榖ƀ;ef⠀भ᠛旃rĀdu⠇⠍shar;楊har;楦Āen⠗⠡rtneqq;쀀≨︀Å⠞܀Dacdefhilnopsu⡀⡅⢂⢎⢓⢠⢥⢨⣚⣢⣤ઃ⣳⤂Dot;戺Ȁclpr⡎⡒⡣⡽r耻¯䂯Āet⡗⡙;時Ā;e⡞⡟朠se»⡟Ā;sျ⡨toȀ;dluျ⡳⡷⡻owîҌefôएðᏑker;斮Āoy⢇⢌mma;権;䐼ash;怔asuredangle»ᘦr;쀀𝔪o;愧ƀcdn⢯⢴⣉ro耻µ䂵Ȁ;acdᑤ⢽⣀⣄sôᚧir;櫰ot肻·Ƶusƀ;bd⣒ᤃ⣓戒Ā;uᴼ⣘;横ţ⣞⣡p;櫛ò−ðઁĀdp⣩⣮els;抧f;쀀𝕞Āct⣸⣽r;쀀𝓂pos»ᖝƀ;lm⤉⤊⤍䎼timap;抸ఀGLRVabcdefghijlmoprstuvw⥂⥓⥾⦉⦘⧚⧩⨕⨚⩘⩝⪃⪕⪤⪨⬄⬇⭄⭿⮮ⰴⱧⱼ⳩Āgt⥇⥋;쀀⋙̸Ā;v⥐௏쀀≫⃒ƀelt⥚⥲⥶ftĀar⥡⥧rrow;懍ightarrow;懎;쀀⋘̸Ā;v⥻ే쀀≪⃒ightarrow;懏ĀDd⦎⦓ash;抯ash;抮ʀbcnpt⦣⦧⦬⦱⧌la»˞ute;䅄g;쀀∠⃒ʀ;Eiop඄⦼⧀⧅⧈;쀀⩰̸d;쀀≋̸s;䅉roø඄urĀ;a⧓⧔普lĀ;s⧓ସǳ⧟\0⧣p肻 ଷmpĀ;e௹ఀʀaeouy⧴⧾⨃⨐⨓ǰ⧹\0⧻;橃on;䅈dil;䅆ngĀ;dൾ⨊ot;쀀⩭̸p;橂;䐽ash;怓΀;Aadqsxஒ⨩⨭⨻⩁⩅⩐rr;懗rĀhr⨳⨶k;椤Ā;oᏲᏰot;쀀≐̸uiöୣĀei⩊⩎ar;椨í஘istĀ;s஠டr;쀀𝔫ȀEest௅⩦⩹⩼ƀ;qs஼⩭௡ƀ;qs஼௅⩴lanô௢ií௪Ā;rஶ⪁»ஷƀAap⪊⪍⪑rò⥱rr;憮ar;櫲ƀ;svྍ⪜ྌĀ;d⪡⪢拼;拺cy;䑚΀AEadest⪷⪺⪾⫂⫅⫶⫹rò⥦;쀀≦̸rr;憚r;急Ȁ;fqs఻⫎⫣⫯tĀar⫔⫙rro÷⫁ightarro÷⪐ƀ;qs఻⪺⫪lanôౕĀ;sౕ⫴»శiíౝĀ;rవ⫾iĀ;eచథiäඐĀpt⬌⬑f;쀀𝕟膀¬;in⬙⬚⬶䂬nȀ;Edvஉ⬤⬨⬮;쀀⋹̸ot;쀀⋵̸ǡஉ⬳⬵;拷;拶iĀ;vಸ⬼ǡಸ⭁⭃;拾;拽ƀaor⭋⭣⭩rȀ;ast୻⭕⭚⭟lleì୻l;쀀⫽⃥;쀀∂̸lint;樔ƀ;ceಒ⭰⭳uåಥĀ;cಘ⭸Ā;eಒ⭽ñಘȀAait⮈⮋⮝⮧rò⦈rrƀ;cw⮔⮕⮙憛;쀀⤳̸;쀀↝̸ghtarrow»⮕riĀ;eೋೖ΀chimpqu⮽⯍⯙⬄୸⯤⯯Ȁ;cerല⯆ഷ⯉uå൅;쀀𝓃ortɭ⬅\0\0⯖ará⭖mĀ;e൮⯟Ā;q൴൳suĀbp⯫⯭å೸åഋƀbcp⯶ⰑⰙȀ;Ees⯿ⰀഢⰄ抄;쀀⫅̸etĀ;eഛⰋqĀ;qണⰀcĀ;eലⰗñസȀ;EesⰢⰣൟⰧ抅;쀀⫆̸etĀ;e൘ⰮqĀ;qൠⰣȀgilrⰽⰿⱅⱇìௗlde耻ñ䃱çృiangleĀlrⱒⱜeftĀ;eచⱚñదightĀ;eೋⱥñ೗Ā;mⱬⱭ䎽ƀ;esⱴⱵⱹ䀣ro;愖p;怇ҀDHadgilrsⲏⲔⲙⲞⲣⲰⲶⳓⳣash;抭arr;椄p;쀀≍⃒ash;抬ĀetⲨⲬ;쀀≥⃒;쀀>⃒nfin;槞ƀAetⲽⳁⳅrr;椂;쀀≤⃒Ā;rⳊⳍ쀀<⃒ie;쀀⊴⃒ĀAtⳘⳜrr;椃rie;쀀⊵⃒im;쀀∼⃒ƀAan⳰⳴ⴂrr;懖rĀhr⳺⳽k;椣Ā;oᏧᏥear;椧ቓ᪕\0\0\0\0\0\0\0\0\0\0\0\0\0ⴭ\0ⴸⵈⵠⵥ⵲ⶄᬇ\0\0ⶍⶫ\0ⷈⷎ\0ⷜ⸙⸫⸾⹃Ācsⴱ᪗ute耻ó䃳ĀiyⴼⵅrĀ;c᪞ⵂ耻ô䃴;䐾ʀabios᪠ⵒⵗǈⵚlac;䅑v;樸old;榼lig;䅓Ācr⵩⵭ir;榿;쀀𝔬ͯ⵹\0\0⵼\0ⶂn;䋛ave耻ò䃲;槁Ābmⶈ෴ar;榵Ȁacitⶕ⶘ⶥⶨrò᪀Āir⶝ⶠr;榾oss;榻nå๒;槀ƀaeiⶱⶵⶹcr;䅍ga;䏉ƀcdnⷀⷅǍron;䎿;榶pf;쀀𝕠ƀaelⷔ⷗ǒr;榷rp;榹΀;adiosvⷪⷫⷮ⸈⸍⸐⸖戨rò᪆Ȁ;efmⷷⷸ⸂⸅橝rĀ;oⷾⷿ愴f»ⷿ耻ª䂪耻º䂺gof;抶r;橖lope;橗;橛ƀclo⸟⸡⸧ò⸁ash耻ø䃸l;折iŬⸯ⸴de耻õ䃵esĀ;aǛ⸺s;樶ml耻ö䃶bar;挽ૡ⹞\0⹽\0⺀⺝\0⺢⺹\0\0⻋ຜ\0⼓\0\0⼫⾼\0⿈rȀ;astЃ⹧⹲຅脀¶;l⹭⹮䂶leìЃɩ⹸\0\0⹻m;櫳;櫽y;䐿rʀcimpt⺋⺏⺓ᡥ⺗nt;䀥od;䀮il;怰enk;怱r;쀀𝔭ƀimo⺨⺰⺴Ā;v⺭⺮䏆;䏕maô੶ne;明ƀ;tv⺿⻀⻈䏀chfork»´;䏖Āau⻏⻟nĀck⻕⻝kĀ;h⇴⻛;愎ö⇴sҀ;abcdemst⻳⻴ᤈ⻹⻽⼄⼆⼊⼎䀫cir;樣ir;樢Āouᵀ⼂;樥;橲n肻±ຝim;樦wo;樧ƀipu⼙⼠⼥ntint;樕f;쀀𝕡nd耻£䂣Ԁ;Eaceinosu່⼿⽁⽄⽇⾁⾉⾒⽾⾶;檳p;檷uå໙Ā;c໎⽌̀;acens່⽙⽟⽦⽨⽾pproø⽃urlyeñ໙ñ໎ƀaes⽯⽶⽺pprox;檹qq;檵im;拨iíໟmeĀ;s⾈ຮ怲ƀEas⽸⾐⽺ð⽵ƀdfp໬⾙⾯ƀals⾠⾥⾪lar;挮ine;挒urf;挓Ā;t໻⾴ï໻rel;抰Āci⿀⿅r;쀀𝓅;䏈ncsp;怈̀fiopsu⿚⋢⿟⿥⿫⿱r;쀀𝔮pf;쀀𝕢rime;恗cr;쀀𝓆ƀaeo⿸〉〓tĀei⿾々rnionóڰnt;樖stĀ;e【】䀿ñἙô༔઀ABHabcdefhilmnoprstux぀けさすムㄎㄫㅇㅢㅲㆎ㈆㈕㈤㈩㉘㉮㉲㊐㊰㊷ƀartぇおがròႳòϝail;検aròᱥar;楤΀cdenqrtとふへみわゔヌĀeuねぱ;쀀∽̱te;䅕iãᅮmptyv;榳gȀ;del࿑らるろ;榒;榥å࿑uo耻»䂻rր;abcfhlpstw࿜ガクシスゼゾダッデナp;極Ā;f࿠ゴs;椠;椳s;椞ë≝ð✮l;楅im;楴l;憣;憝Āaiパフil;椚oĀ;nホボ戶aló༞ƀabrョリヮrò៥rk;杳ĀakンヽcĀekヹ・;䁽;䁝Āes㄂㄄;榌lĀduㄊㄌ;榎;榐Ȁaeuyㄗㄜㄧㄩron;䅙Ādiㄡㄥil;䅗ì࿲âヺ;䑀Ȁclqsㄴㄷㄽㅄa;椷dhar;楩uoĀ;rȎȍh;憳ƀacgㅎㅟངlȀ;ipsླྀㅘㅛႜnåႻarôྩt;断ƀilrㅩဣㅮsht;楽;쀀𝔯ĀaoㅷㆆrĀduㅽㅿ»ѻĀ;l႑ㆄ;楬Ā;vㆋㆌ䏁;䏱ƀgns㆕ㇹㇼht̀ahlrstㆤㆰ㇂㇘㇤㇮rrowĀ;t࿜ㆭaéトarpoonĀduㆻㆿowîㅾp»႒eftĀah㇊㇐rrowó࿪arpoonóՑightarrows;應quigarro÷ニhreetimes;拌g;䋚ingdotseñἲƀahm㈍㈐㈓rò࿪aòՑ;怏oustĀ;a㈞㈟掱che»㈟mid;櫮Ȁabpt㈲㈽㉀㉒Ānr㈷㈺g;柭r;懾rëဃƀafl㉇㉊㉎r;榆;쀀𝕣us;樮imes;樵Āap㉝㉧rĀ;g㉣㉤䀩t;榔olint;樒arò㇣Ȁachq㉻㊀Ⴜ㊅quo;怺r;쀀𝓇Ābu・㊊oĀ;rȔȓƀhir㊗㊛㊠reåㇸmes;拊iȀ;efl㊪ၙᠡ㊫方tri;槎luhar;楨;愞ൡ㋕㋛㋟㌬㌸㍱\0㍺㎤\0\0㏬㏰\0㐨㑈㑚㒭㒱㓊㓱\0㘖\0\0㘳cute;䅛quï➺Ԁ;Eaceinpsyᇭ㋳㋵㋿㌂㌋㌏㌟㌦㌩;檴ǰ㋺\0㋼;檸on;䅡uåᇾĀ;dᇳ㌇il;䅟rc;䅝ƀEas㌖㌘㌛;檶p;檺im;择olint;樓iíሄ;䑁otƀ;be㌴ᵇ㌵担;橦΀Aacmstx㍆㍊㍗㍛㍞㍣㍭rr;懘rĀhr㍐㍒ë∨Ā;oਸ਼਴t耻§䂧i;䀻war;椩mĀin㍩ðnuóñt;朶rĀ;o㍶⁕쀀𝔰Ȁacoy㎂㎆㎑㎠rp;景Āhy㎋㎏cy;䑉;䑈rtɭ㎙\0\0㎜iäᑤaraì⹯耻­䂭Āgm㎨㎴maƀ;fv㎱㎲㎲䏃;䏂Ѐ;deglnprካ㏅㏉㏎㏖㏞㏡㏦ot;橪Ā;q኱ኰĀ;E㏓㏔檞;檠Ā;E㏛㏜檝;檟e;扆lus;樤arr;楲aròᄽȀaeit㏸㐈㐏㐗Āls㏽㐄lsetmé㍪hp;樳parsl;槤Ādlᑣ㐔e;挣Ā;e㐜㐝檪Ā;s㐢㐣檬;쀀⪬︀ƀflp㐮㐳㑂tcy;䑌Ā;b㐸㐹䀯Ā;a㐾㐿槄r;挿f;쀀𝕤aĀdr㑍ЂesĀ;u㑔㑕晠it»㑕ƀcsu㑠㑹㒟Āau㑥㑯pĀ;sᆈ㑫;쀀⊓︀pĀ;sᆴ㑵;쀀⊔︀uĀbp㑿㒏ƀ;esᆗᆜ㒆etĀ;eᆗ㒍ñᆝƀ;esᆨᆭ㒖etĀ;eᆨ㒝ñᆮƀ;afᅻ㒦ְrť㒫ֱ»ᅼaròᅈȀcemt㒹㒾㓂㓅r;쀀𝓈tmîñiì㐕aræᆾĀar㓎㓕rĀ;f㓔ឿ昆Āan㓚㓭ightĀep㓣㓪psiloîỠhé⺯s»⡒ʀbcmnp㓻㕞ሉ㖋㖎Ҁ;Edemnprs㔎㔏㔑㔕㔞㔣㔬㔱㔶抂;櫅ot;檽Ā;dᇚ㔚ot;櫃ult;櫁ĀEe㔨㔪;櫋;把lus;檿arr;楹ƀeiu㔽㕒㕕tƀ;en㔎㕅㕋qĀ;qᇚ㔏eqĀ;q㔫㔨m;櫇Ābp㕚㕜;櫕;櫓c̀;acensᇭ㕬㕲㕹㕻㌦pproø㋺urlyeñᇾñᇳƀaes㖂㖈㌛pproø㌚qñ㌗g;晪ڀ123;Edehlmnps㖩㖬㖯ሜ㖲㖴㗀㗉㗕㗚㗟㗨㗭耻¹䂹耻²䂲耻³䂳;櫆Āos㖹㖼t;檾ub;櫘Ā;dሢ㗅ot;櫄sĀou㗏㗒l;柉b;櫗arr;楻ult;櫂ĀEe㗤㗦;櫌;抋lus;櫀ƀeiu㗴㘉㘌tƀ;enሜ㗼㘂qĀ;qሢ㖲eqĀ;q㗧㗤m;櫈Ābp㘑㘓;櫔;櫖ƀAan㘜㘠㘭rr;懙rĀhr㘦㘨ë∮Ā;oਫ਩war;椪lig耻ß䃟௡㙑㙝㙠ዎ㙳㙹\0㙾㛂\0\0\0\0\0㛛㜃\0㜉㝬\0\0\0㞇ɲ㙖\0\0㙛get;挖;䏄rë๟ƀaey㙦㙫㙰ron;䅥dil;䅣;䑂lrec;挕r;쀀𝔱Ȁeiko㚆㚝㚵㚼ǲ㚋\0㚑eĀ4fኄኁaƀ;sv㚘㚙㚛䎸ym;䏑Ācn㚢㚲kĀas㚨㚮pproø዁im»ኬsðኞĀas㚺㚮ð዁rn耻þ䃾Ǭ̟㛆⋧es膀×;bd㛏㛐㛘䃗Ā;aᤏ㛕r;樱;樰ƀeps㛡㛣㜀á⩍Ȁ;bcf҆㛬㛰㛴ot;挶ir;櫱Ā;o㛹㛼쀀𝕥rk;櫚á㍢rime;怴ƀaip㜏㜒㝤dåቈ΀adempst㜡㝍㝀㝑㝗㝜㝟ngleʀ;dlqr㜰㜱㜶㝀㝂斵own»ᶻeftĀ;e⠀㜾ñम;扜ightĀ;e㊪㝋ñၚot;旬inus;樺lus;樹b;槍ime;樻ezium;揢ƀcht㝲㝽㞁Āry㝷㝻;쀀𝓉;䑆cy;䑛rok;䅧Āio㞋㞎xô᝷headĀlr㞗㞠eftarro÷ࡏightarrow»ཝऀAHabcdfghlmoprstuw㟐㟓㟗㟤㟰㟼㠎㠜㠣㠴㡑㡝㡫㢩㣌㣒㣪㣶ròϭar;楣Ācr㟜㟢ute耻ú䃺òᅐrǣ㟪\0㟭y;䑞ve;䅭Āiy㟵㟺rc耻û䃻;䑃ƀabh㠃㠆㠋ròᎭlac;䅱aòᏃĀir㠓㠘sht;楾;쀀𝔲rave耻ù䃹š㠧㠱rĀlr㠬㠮»ॗ»ႃlk;斀Āct㠹㡍ɯ㠿\0\0㡊rnĀ;e㡅㡆挜r»㡆op;挏ri;旸Āal㡖㡚cr;䅫肻¨͉Āgp㡢㡦on;䅳f;쀀𝕦̀adhlsuᅋ㡸㡽፲㢑㢠ownáᎳarpoonĀlr㢈㢌efô㠭ighô㠯iƀ;hl㢙㢚㢜䏅»ᏺon»㢚parrows;懈ƀcit㢰㣄㣈ɯ㢶\0\0㣁rnĀ;e㢼㢽挝r»㢽op;挎ng;䅯ri;旹cr;쀀𝓊ƀdir㣙㣝㣢ot;拰lde;䅩iĀ;f㜰㣨»᠓Āam㣯㣲rò㢨l耻ü䃼angle;榧ހABDacdeflnoprsz㤜㤟㤩㤭㦵㦸㦽㧟㧤㧨㧳㧹㧽㨁㨠ròϷarĀ;v㤦㤧櫨;櫩asèϡĀnr㤲㤷grt;榜΀eknprst㓣㥆㥋㥒㥝㥤㦖appá␕othinçẖƀhir㓫⻈㥙opô⾵Ā;hᎷ㥢ïㆍĀiu㥩㥭gmá㎳Ābp㥲㦄setneqĀ;q㥽㦀쀀⊊︀;쀀⫋︀setneqĀ;q㦏㦒쀀⊋︀;쀀⫌︀Āhr㦛㦟etá㚜iangleĀlr㦪㦯eft»थight»ၑy;䐲ash»ံƀelr㧄㧒㧗ƀ;beⷪ㧋㧏ar;抻q;扚lip;拮Ābt㧜ᑨaòᑩr;쀀𝔳tré㦮suĀbp㧯㧱»ജ»൙pf;쀀𝕧roð໻tré㦴Ācu㨆㨋r;쀀𝓋Ābp㨐㨘nĀEe㦀㨖»㥾nĀEe㦒㨞»㦐igzag;榚΀cefoprs㨶㨻㩖㩛㩔㩡㩪irc;䅵Ādi㩀㩑Ābg㩅㩉ar;機eĀ;qᗺ㩏;扙erp;愘r;쀀𝔴pf;쀀𝕨Ā;eᑹ㩦atèᑹcr;쀀𝓌ૣណ㪇\0㪋\0㪐㪛\0\0㪝㪨㪫㪯\0\0㫃㫎\0㫘ៜ៟tré៑r;쀀𝔵ĀAa㪔㪗ròσrò৶;䎾ĀAa㪡㪤ròθrò৫að✓is;拻ƀdptឤ㪵㪾Āfl㪺ឩ;쀀𝕩imåឲĀAa㫇㫊ròώròਁĀcq㫒ីr;쀀𝓍Āpt៖㫜ré។Ѐacefiosu㫰㫽㬈㬌㬑㬕㬛㬡cĀuy㫶㫻te耻ý䃽;䑏Āiy㬂㬆rc;䅷;䑋n耻¥䂥r;쀀𝔶cy;䑗pf;쀀𝕪cr;쀀𝓎Ācm㬦㬩y;䑎l耻ÿ䃿Ԁacdefhiosw㭂㭈㭔㭘㭤㭩㭭㭴㭺㮀cute;䅺Āay㭍㭒ron;䅾;䐷ot;䅼Āet㭝㭡træᕟa;䎶r;쀀𝔷cy;䐶grarr;懝pf;쀀𝕫cr;쀀𝓏Ājn㮅㮇;怍j;怌'.split("").map((c2) => c2.charCodeAt(0))
);
const xmlDecodeTree = new Uint16Array(
  // prettier-ignore
  "Ȁaglq	\x1Bɭ\0\0p;䀦os;䀧t;䀾t;䀼uot;䀢".split("").map((c2) => c2.charCodeAt(0))
);
var _a$1;
const decodeMap = /* @__PURE__ */ new Map([
  [0, 65533],
  // C1 Unicode control character reference replacements
  [128, 8364],
  [130, 8218],
  [131, 402],
  [132, 8222],
  [133, 8230],
  [134, 8224],
  [135, 8225],
  [136, 710],
  [137, 8240],
  [138, 352],
  [139, 8249],
  [140, 338],
  [142, 381],
  [145, 8216],
  [146, 8217],
  [147, 8220],
  [148, 8221],
  [149, 8226],
  [150, 8211],
  [151, 8212],
  [152, 732],
  [153, 8482],
  [154, 353],
  [155, 8250],
  [156, 339],
  [158, 382],
  [159, 376]
]);
const fromCodePoint$1 = (
  // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition, node/no-unsupported-features/es-builtins
  (_a$1 = String.fromCodePoint) !== null && _a$1 !== void 0 ? _a$1 : function(codePoint) {
    let output = "";
    if (codePoint > 65535) {
      codePoint -= 65536;
      output += String.fromCharCode(codePoint >>> 10 & 1023 | 55296);
      codePoint = 56320 | codePoint & 1023;
    }
    output += String.fromCharCode(codePoint);
    return output;
  }
);
function replaceCodePoint(codePoint) {
  var _a2;
  if (codePoint >= 55296 && codePoint <= 57343 || codePoint > 1114111) {
    return 65533;
  }
  return (_a2 = decodeMap.get(codePoint)) !== null && _a2 !== void 0 ? _a2 : codePoint;
}
var CharCodes;
(function(CharCodes2) {
  CharCodes2[CharCodes2["NUM"] = 35] = "NUM";
  CharCodes2[CharCodes2["SEMI"] = 59] = "SEMI";
  CharCodes2[CharCodes2["EQUALS"] = 61] = "EQUALS";
  CharCodes2[CharCodes2["ZERO"] = 48] = "ZERO";
  CharCodes2[CharCodes2["NINE"] = 57] = "NINE";
  CharCodes2[CharCodes2["LOWER_A"] = 97] = "LOWER_A";
  CharCodes2[CharCodes2["LOWER_F"] = 102] = "LOWER_F";
  CharCodes2[CharCodes2["LOWER_X"] = 120] = "LOWER_X";
  CharCodes2[CharCodes2["LOWER_Z"] = 122] = "LOWER_Z";
  CharCodes2[CharCodes2["UPPER_A"] = 65] = "UPPER_A";
  CharCodes2[CharCodes2["UPPER_F"] = 70] = "UPPER_F";
  CharCodes2[CharCodes2["UPPER_Z"] = 90] = "UPPER_Z";
})(CharCodes || (CharCodes = {}));
const TO_LOWER_BIT = 32;
var BinTrieFlags;
(function(BinTrieFlags2) {
  BinTrieFlags2[BinTrieFlags2["VALUE_LENGTH"] = 49152] = "VALUE_LENGTH";
  BinTrieFlags2[BinTrieFlags2["BRANCH_LENGTH"] = 16256] = "BRANCH_LENGTH";
  BinTrieFlags2[BinTrieFlags2["JUMP_TABLE"] = 127] = "JUMP_TABLE";
})(BinTrieFlags || (BinTrieFlags = {}));
function isNumber(code2) {
  return code2 >= CharCodes.ZERO && code2 <= CharCodes.NINE;
}
function isHexadecimalCharacter(code2) {
  return code2 >= CharCodes.UPPER_A && code2 <= CharCodes.UPPER_F || code2 >= CharCodes.LOWER_A && code2 <= CharCodes.LOWER_F;
}
function isAsciiAlphaNumeric(code2) {
  return code2 >= CharCodes.UPPER_A && code2 <= CharCodes.UPPER_Z || code2 >= CharCodes.LOWER_A && code2 <= CharCodes.LOWER_Z || isNumber(code2);
}
function isEntityInAttributeInvalidEnd(code2) {
  return code2 === CharCodes.EQUALS || isAsciiAlphaNumeric(code2);
}
var EntityDecoderState;
(function(EntityDecoderState2) {
  EntityDecoderState2[EntityDecoderState2["EntityStart"] = 0] = "EntityStart";
  EntityDecoderState2[EntityDecoderState2["NumericStart"] = 1] = "NumericStart";
  EntityDecoderState2[EntityDecoderState2["NumericDecimal"] = 2] = "NumericDecimal";
  EntityDecoderState2[EntityDecoderState2["NumericHex"] = 3] = "NumericHex";
  EntityDecoderState2[EntityDecoderState2["NamedEntity"] = 4] = "NamedEntity";
})(EntityDecoderState || (EntityDecoderState = {}));
var DecodingMode;
(function(DecodingMode2) {
  DecodingMode2[DecodingMode2["Legacy"] = 0] = "Legacy";
  DecodingMode2[DecodingMode2["Strict"] = 1] = "Strict";
  DecodingMode2[DecodingMode2["Attribute"] = 2] = "Attribute";
})(DecodingMode || (DecodingMode = {}));
class EntityDecoder {
  constructor(decodeTree, emitCodePoint, errors2) {
    this.decodeTree = decodeTree;
    this.emitCodePoint = emitCodePoint;
    this.errors = errors2;
    this.state = EntityDecoderState.EntityStart;
    this.consumed = 1;
    this.result = 0;
    this.treeIndex = 0;
    this.excess = 1;
    this.decodeMode = DecodingMode.Strict;
  }
  /** Resets the instance to make it reusable. */
  startEntity(decodeMode) {
    this.decodeMode = decodeMode;
    this.state = EntityDecoderState.EntityStart;
    this.result = 0;
    this.treeIndex = 0;
    this.excess = 1;
    this.consumed = 1;
  }
  /**
   * Write an entity to the decoder. This can be called multiple times with partial entities.
   * If the entity is incomplete, the decoder will return -1.
   *
   * Mirrors the implementation of `getDecoder`, but with the ability to stop decoding if the
   * entity is incomplete, and resume when the next string is written.
   *
   * @param string The string containing the entity (or a continuation of the entity).
   * @param offset The offset at which the entity begins. Should be 0 if this is not the first call.
   * @returns The number of characters that were consumed, or -1 if the entity is incomplete.
   */
  write(str, offset2) {
    switch (this.state) {
      case EntityDecoderState.EntityStart: {
        if (str.charCodeAt(offset2) === CharCodes.NUM) {
          this.state = EntityDecoderState.NumericStart;
          this.consumed += 1;
          return this.stateNumericStart(str, offset2 + 1);
        }
        this.state = EntityDecoderState.NamedEntity;
        return this.stateNamedEntity(str, offset2);
      }
      case EntityDecoderState.NumericStart: {
        return this.stateNumericStart(str, offset2);
      }
      case EntityDecoderState.NumericDecimal: {
        return this.stateNumericDecimal(str, offset2);
      }
      case EntityDecoderState.NumericHex: {
        return this.stateNumericHex(str, offset2);
      }
      case EntityDecoderState.NamedEntity: {
        return this.stateNamedEntity(str, offset2);
      }
    }
  }
  /**
   * Switches between the numeric decimal and hexadecimal states.
   *
   * Equivalent to the `Numeric character reference state` in the HTML spec.
   *
   * @param str The string containing the entity (or a continuation of the entity).
   * @param offset The current offset.
   * @returns The number of characters that were consumed, or -1 if the entity is incomplete.
   */
  stateNumericStart(str, offset2) {
    if (offset2 >= str.length) {
      return -1;
    }
    if ((str.charCodeAt(offset2) | TO_LOWER_BIT) === CharCodes.LOWER_X) {
      this.state = EntityDecoderState.NumericHex;
      this.consumed += 1;
      return this.stateNumericHex(str, offset2 + 1);
    }
    this.state = EntityDecoderState.NumericDecimal;
    return this.stateNumericDecimal(str, offset2);
  }
  addToNumericResult(str, start2, end2, base2) {
    if (start2 !== end2) {
      const digitCount = end2 - start2;
      this.result = this.result * Math.pow(base2, digitCount) + parseInt(str.substr(start2, digitCount), base2);
      this.consumed += digitCount;
    }
  }
  /**
   * Parses a hexadecimal numeric entity.
   *
   * Equivalent to the `Hexademical character reference state` in the HTML spec.
   *
   * @param str The string containing the entity (or a continuation of the entity).
   * @param offset The current offset.
   * @returns The number of characters that were consumed, or -1 if the entity is incomplete.
   */
  stateNumericHex(str, offset2) {
    const startIdx = offset2;
    while (offset2 < str.length) {
      const char = str.charCodeAt(offset2);
      if (isNumber(char) || isHexadecimalCharacter(char)) {
        offset2 += 1;
      } else {
        this.addToNumericResult(str, startIdx, offset2, 16);
        return this.emitNumericEntity(char, 3);
      }
    }
    this.addToNumericResult(str, startIdx, offset2, 16);
    return -1;
  }
  /**
   * Parses a decimal numeric entity.
   *
   * Equivalent to the `Decimal character reference state` in the HTML spec.
   *
   * @param str The string containing the entity (or a continuation of the entity).
   * @param offset The current offset.
   * @returns The number of characters that were consumed, or -1 if the entity is incomplete.
   */
  stateNumericDecimal(str, offset2) {
    const startIdx = offset2;
    while (offset2 < str.length) {
      const char = str.charCodeAt(offset2);
      if (isNumber(char)) {
        offset2 += 1;
      } else {
        this.addToNumericResult(str, startIdx, offset2, 10);
        return this.emitNumericEntity(char, 2);
      }
    }
    this.addToNumericResult(str, startIdx, offset2, 10);
    return -1;
  }
  /**
   * Validate and emit a numeric entity.
   *
   * Implements the logic from the `Hexademical character reference start
   * state` and `Numeric character reference end state` in the HTML spec.
   *
   * @param lastCp The last code point of the entity. Used to see if the
   *               entity was terminated with a semicolon.
   * @param expectedLength The minimum number of characters that should be
   *                       consumed. Used to validate that at least one digit
   *                       was consumed.
   * @returns The number of characters that were consumed.
   */
  emitNumericEntity(lastCp, expectedLength) {
    var _a2;
    if (this.consumed <= expectedLength) {
      (_a2 = this.errors) === null || _a2 === void 0 ? void 0 : _a2.absenceOfDigitsInNumericCharacterReference(this.consumed);
      return 0;
    }
    if (lastCp === CharCodes.SEMI) {
      this.consumed += 1;
    } else if (this.decodeMode === DecodingMode.Strict) {
      return 0;
    }
    this.emitCodePoint(replaceCodePoint(this.result), this.consumed);
    if (this.errors) {
      if (lastCp !== CharCodes.SEMI) {
        this.errors.missingSemicolonAfterCharacterReference();
      }
      this.errors.validateNumericCharacterReference(this.result);
    }
    return this.consumed;
  }
  /**
   * Parses a named entity.
   *
   * Equivalent to the `Named character reference state` in the HTML spec.
   *
   * @param str The string containing the entity (or a continuation of the entity).
   * @param offset The current offset.
   * @returns The number of characters that were consumed, or -1 if the entity is incomplete.
   */
  stateNamedEntity(str, offset2) {
    const { decodeTree } = this;
    let current = decodeTree[this.treeIndex];
    let valueLength = (current & BinTrieFlags.VALUE_LENGTH) >> 14;
    for (; offset2 < str.length; offset2++, this.excess++) {
      const char = str.charCodeAt(offset2);
      this.treeIndex = determineBranch(decodeTree, current, this.treeIndex + Math.max(1, valueLength), char);
      if (this.treeIndex < 0) {
        return this.result === 0 || // If we are parsing an attribute
        this.decodeMode === DecodingMode.Attribute && // We shouldn't have consumed any characters after the entity,
        (valueLength === 0 || // And there should be no invalid characters.
        isEntityInAttributeInvalidEnd(char)) ? 0 : this.emitNotTerminatedNamedEntity();
      }
      current = decodeTree[this.treeIndex];
      valueLength = (current & BinTrieFlags.VALUE_LENGTH) >> 14;
      if (valueLength !== 0) {
        if (char === CharCodes.SEMI) {
          return this.emitNamedEntityData(this.treeIndex, valueLength, this.consumed + this.excess);
        }
        if (this.decodeMode !== DecodingMode.Strict) {
          this.result = this.treeIndex;
          this.consumed += this.excess;
          this.excess = 0;
        }
      }
    }
    return -1;
  }
  /**
   * Emit a named entity that was not terminated with a semicolon.
   *
   * @returns The number of characters consumed.
   */
  emitNotTerminatedNamedEntity() {
    var _a2;
    const { result, decodeTree } = this;
    const valueLength = (decodeTree[result] & BinTrieFlags.VALUE_LENGTH) >> 14;
    this.emitNamedEntityData(result, valueLength, this.consumed);
    (_a2 = this.errors) === null || _a2 === void 0 ? void 0 : _a2.missingSemicolonAfterCharacterReference();
    return this.consumed;
  }
  /**
   * Emit a named entity.
   *
   * @param result The index of the entity in the decode tree.
   * @param valueLength The number of bytes in the entity.
   * @param consumed The number of characters consumed.
   *
   * @returns The number of characters consumed.
   */
  emitNamedEntityData(result, valueLength, consumed) {
    const { decodeTree } = this;
    this.emitCodePoint(valueLength === 1 ? decodeTree[result] & ~BinTrieFlags.VALUE_LENGTH : decodeTree[result + 1], consumed);
    if (valueLength === 3) {
      this.emitCodePoint(decodeTree[result + 2], consumed);
    }
    return consumed;
  }
  /**
   * Signal to the parser that the end of the input was reached.
   *
   * Remaining data will be emitted and relevant errors will be produced.
   *
   * @returns The number of characters consumed.
   */
  end() {
    var _a2;
    switch (this.state) {
      case EntityDecoderState.NamedEntity: {
        return this.result !== 0 && (this.decodeMode !== DecodingMode.Attribute || this.result === this.treeIndex) ? this.emitNotTerminatedNamedEntity() : 0;
      }
      case EntityDecoderState.NumericDecimal: {
        return this.emitNumericEntity(0, 2);
      }
      case EntityDecoderState.NumericHex: {
        return this.emitNumericEntity(0, 3);
      }
      case EntityDecoderState.NumericStart: {
        (_a2 = this.errors) === null || _a2 === void 0 ? void 0 : _a2.absenceOfDigitsInNumericCharacterReference(this.consumed);
        return 0;
      }
      case EntityDecoderState.EntityStart: {
        return 0;
      }
    }
  }
}
function getDecoder(decodeTree) {
  let ret = "";
  const decoder = new EntityDecoder(decodeTree, (str) => ret += fromCodePoint$1(str));
  return function decodeWithTrie(str, decodeMode) {
    let lastIndex = 0;
    let offset2 = 0;
    while ((offset2 = str.indexOf("&", offset2)) >= 0) {
      ret += str.slice(lastIndex, offset2);
      decoder.startEntity(decodeMode);
      const len = decoder.write(
        str,
        // Skip the "&"
        offset2 + 1
      );
      if (len < 0) {
        lastIndex = offset2 + decoder.end();
        break;
      }
      lastIndex = offset2 + len;
      offset2 = len === 0 ? lastIndex + 1 : lastIndex;
    }
    const result = ret + str.slice(lastIndex);
    ret = "";
    return result;
  };
}
function determineBranch(decodeTree, current, nodeIdx, char) {
  const branchCount = (current & BinTrieFlags.BRANCH_LENGTH) >> 7;
  const jumpOffset = current & BinTrieFlags.JUMP_TABLE;
  if (branchCount === 0) {
    return jumpOffset !== 0 && char === jumpOffset ? nodeIdx : -1;
  }
  if (jumpOffset) {
    const value = char - jumpOffset;
    return value < 0 || value >= branchCount ? -1 : decodeTree[nodeIdx + value] - 1;
  }
  let lo = nodeIdx;
  let hi = lo + branchCount - 1;
  while (lo <= hi) {
    const mid = lo + hi >>> 1;
    const midVal = decodeTree[mid];
    if (midVal < char) {
      lo = mid + 1;
    } else if (midVal > char) {
      hi = mid - 1;
    } else {
      return decodeTree[mid + branchCount];
    }
  }
  return -1;
}
const htmlDecoder = getDecoder(htmlDecodeTree);
getDecoder(xmlDecodeTree);
function decodeHTML(str, mode = DecodingMode.Legacy) {
  return htmlDecoder(str, mode);
}
function _class$1(obj) {
  return Object.prototype.toString.call(obj);
}
function isString$1(obj) {
  return _class$1(obj) === "[object String]";
}
const _hasOwnProperty = Object.prototype.hasOwnProperty;
function has(object, key2) {
  return _hasOwnProperty.call(object, key2);
}
function assign$1(obj) {
  const sources = Array.prototype.slice.call(arguments, 1);
  sources.forEach(function(source2) {
    if (!source2) {
      return;
    }
    if (typeof source2 !== "object") {
      throw new TypeError(source2 + "must be object");
    }
    Object.keys(source2).forEach(function(key2) {
      obj[key2] = source2[key2];
    });
  });
  return obj;
}
function arrayReplaceAt(src, pos2, newElements) {
  return [].concat(src.slice(0, pos2), newElements, src.slice(pos2 + 1));
}
function isValidEntityCode(c2) {
  if (c2 >= 55296 && c2 <= 57343) {
    return false;
  }
  if (c2 >= 64976 && c2 <= 65007) {
    return false;
  }
  if ((c2 & 65535) === 65535 || (c2 & 65535) === 65534) {
    return false;
  }
  if (c2 >= 0 && c2 <= 8) {
    return false;
  }
  if (c2 === 11) {
    return false;
  }
  if (c2 >= 14 && c2 <= 31) {
    return false;
  }
  if (c2 >= 127 && c2 <= 159) {
    return false;
  }
  if (c2 > 1114111) {
    return false;
  }
  return true;
}
function fromCodePoint(c2) {
  if (c2 > 65535) {
    c2 -= 65536;
    const surrogate1 = 55296 + (c2 >> 10);
    const surrogate2 = 56320 + (c2 & 1023);
    return String.fromCharCode(surrogate1, surrogate2);
  }
  return String.fromCharCode(c2);
}
const UNESCAPE_MD_RE = /\\([!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~])/g;
const ENTITY_RE = /&([a-z#][a-z0-9]{1,31});/gi;
const UNESCAPE_ALL_RE = new RegExp(UNESCAPE_MD_RE.source + "|" + ENTITY_RE.source, "gi");
const DIGITAL_ENTITY_TEST_RE = /^#((?:x[a-f0-9]{1,8}|[0-9]{1,8}))$/i;
function replaceEntityPattern(match2, name) {
  if (name.charCodeAt(0) === 35 && DIGITAL_ENTITY_TEST_RE.test(name)) {
    const code2 = name[1].toLowerCase() === "x" ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
    if (isValidEntityCode(code2)) {
      return fromCodePoint(code2);
    }
    return match2;
  }
  const decoded = decodeHTML(match2);
  if (decoded !== match2) {
    return decoded;
  }
  return match2;
}
function unescapeMd(str) {
  if (str.indexOf("\\") < 0) {
    return str;
  }
  return str.replace(UNESCAPE_MD_RE, "$1");
}
function unescapeAll(str) {
  if (str.indexOf("\\") < 0 && str.indexOf("&") < 0) {
    return str;
  }
  return str.replace(UNESCAPE_ALL_RE, function(match2, escaped, entity2) {
    if (escaped) {
      return escaped;
    }
    return replaceEntityPattern(match2, entity2);
  });
}
const HTML_ESCAPE_TEST_RE = /[&<>"]/;
const HTML_ESCAPE_REPLACE_RE = /[&<>"]/g;
const HTML_REPLACEMENTS = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;"
};
function replaceUnsafeChar(ch3) {
  return HTML_REPLACEMENTS[ch3];
}
function escapeHtml(str) {
  if (HTML_ESCAPE_TEST_RE.test(str)) {
    return str.replace(HTML_ESCAPE_REPLACE_RE, replaceUnsafeChar);
  }
  return str;
}
const REGEXP_ESCAPE_RE = /[.?*+^$[\]\\(){}|-]/g;
function escapeRE$1(str) {
  return str.replace(REGEXP_ESCAPE_RE, "\\$&");
}
function isSpace(code2) {
  switch (code2) {
    case 9:
    case 32:
      return true;
  }
  return false;
}
function isWhiteSpace(code2) {
  if (code2 >= 8192 && code2 <= 8202) {
    return true;
  }
  switch (code2) {
    case 9:
    case 10:
    case 11:
    case 12:
    case 13:
    case 32:
    case 160:
    case 5760:
    case 8239:
    case 8287:
    case 12288:
      return true;
  }
  return false;
}
function isPunctChar(ch3) {
  return P.test(ch3) || regex.test(ch3);
}
function isMdAsciiPunct(ch3) {
  switch (ch3) {
    case 33:
    case 34:
    case 35:
    case 36:
    case 37:
    case 38:
    case 39:
    case 40:
    case 41:
    case 42:
    case 43:
    case 44:
    case 45:
    case 46:
    case 47:
    case 58:
    case 59:
    case 60:
    case 61:
    case 62:
    case 63:
    case 64:
    case 91:
    case 92:
    case 93:
    case 94:
    case 95:
    case 96:
    case 123:
    case 124:
    case 125:
    case 126:
      return true;
    default:
      return false;
  }
}
function normalizeReference(str) {
  str = str.trim().replace(/\s+/g, " ");
  if ("ẞ".toLowerCase() === "Ṿ") {
    str = str.replace(/ẞ/g, "ß");
  }
  return str.toLowerCase().toUpperCase();
}
const lib$1 = { mdurl, ucmicro };
const utils = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ Object.defineProperty({
  __proto__: null,
  arrayReplaceAt,
  assign: assign$1,
  escapeHtml,
  escapeRE: escapeRE$1,
  fromCodePoint,
  has,
  isMdAsciiPunct,
  isPunctChar,
  isSpace,
  isString: isString$1,
  isValidEntityCode,
  isWhiteSpace,
  lib: lib$1,
  normalizeReference,
  unescapeAll,
  unescapeMd
}, Symbol.toStringTag, { value: "Module" }));
function parseLinkLabel(state, start2, disableNested) {
  let level, found, marker, prevPos;
  const max2 = state.posMax;
  const oldPos = state.pos;
  state.pos = start2 + 1;
  level = 1;
  while (state.pos < max2) {
    marker = state.src.charCodeAt(state.pos);
    if (marker === 93) {
      level--;
      if (level === 0) {
        found = true;
        break;
      }
    }
    prevPos = state.pos;
    state.md.inline.skipToken(state);
    if (marker === 91) {
      if (prevPos === state.pos - 1) {
        level++;
      } else if (disableNested) {
        state.pos = oldPos;
        return -1;
      }
    }
  }
  let labelEnd = -1;
  if (found) {
    labelEnd = state.pos;
  }
  state.pos = oldPos;
  return labelEnd;
}
function parseLinkDestination(str, start2, max2) {
  let code2;
  let pos2 = start2;
  const result = {
    ok: false,
    pos: 0,
    str: ""
  };
  if (str.charCodeAt(pos2) === 60) {
    pos2++;
    while (pos2 < max2) {
      code2 = str.charCodeAt(pos2);
      if (code2 === 10) {
        return result;
      }
      if (code2 === 60) {
        return result;
      }
      if (code2 === 62) {
        result.pos = pos2 + 1;
        result.str = unescapeAll(str.slice(start2 + 1, pos2));
        result.ok = true;
        return result;
      }
      if (code2 === 92 && pos2 + 1 < max2) {
        pos2 += 2;
        continue;
      }
      pos2++;
    }
    return result;
  }
  let level = 0;
  while (pos2 < max2) {
    code2 = str.charCodeAt(pos2);
    if (code2 === 32) {
      break;
    }
    if (code2 < 32 || code2 === 127) {
      break;
    }
    if (code2 === 92 && pos2 + 1 < max2) {
      if (str.charCodeAt(pos2 + 1) === 32) {
        break;
      }
      pos2 += 2;
      continue;
    }
    if (code2 === 40) {
      level++;
      if (level > 32) {
        return result;
      }
    }
    if (code2 === 41) {
      if (level === 0) {
        break;
      }
      level--;
    }
    pos2++;
  }
  if (start2 === pos2) {
    return result;
  }
  if (level !== 0) {
    return result;
  }
  result.str = unescapeAll(str.slice(start2, pos2));
  result.pos = pos2;
  result.ok = true;
  return result;
}
function parseLinkTitle(str, start2, max2, prev_state) {
  let code2;
  let pos2 = start2;
  const state = {
    // if `true`, this is a valid link title
    ok: false,
    // if `true`, this link can be continued on the next line
    can_continue: false,
    // if `ok`, it's the position of the first character after the closing marker
    pos: 0,
    // if `ok`, it's the unescaped title
    str: "",
    // expected closing marker character code
    marker: 0
  };
  if (prev_state) {
    state.str = prev_state.str;
    state.marker = prev_state.marker;
  } else {
    if (pos2 >= max2) {
      return state;
    }
    let marker = str.charCodeAt(pos2);
    if (marker !== 34 && marker !== 39 && marker !== 40) {
      return state;
    }
    start2++;
    pos2++;
    if (marker === 40) {
      marker = 41;
    }
    state.marker = marker;
  }
  while (pos2 < max2) {
    code2 = str.charCodeAt(pos2);
    if (code2 === state.marker) {
      state.pos = pos2 + 1;
      state.str += unescapeAll(str.slice(start2, pos2));
      state.ok = true;
      return state;
    } else if (code2 === 40 && state.marker === 41) {
      return state;
    } else if (code2 === 92 && pos2 + 1 < max2) {
      pos2++;
    }
    pos2++;
  }
  state.can_continue = true;
  state.str += unescapeAll(str.slice(start2, pos2));
  return state;
}
const helpers = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ Object.defineProperty({
  __proto__: null,
  parseLinkDestination,
  parseLinkLabel,
  parseLinkTitle
}, Symbol.toStringTag, { value: "Module" }));
const default_rules = {};
default_rules.code_inline = function(tokens, idx, options, env, slf) {
  const token2 = tokens[idx];
  return "<code" + slf.renderAttrs(token2) + ">" + escapeHtml(token2.content) + "</code>";
};
default_rules.code_block = function(tokens, idx, options, env, slf) {
  const token2 = tokens[idx];
  return "<pre" + slf.renderAttrs(token2) + "><code>" + escapeHtml(tokens[idx].content) + "</code></pre>\n";
};
default_rules.fence = function(tokens, idx, options, env, slf) {
  const token2 = tokens[idx];
  const info = token2.info ? unescapeAll(token2.info).trim() : "";
  let langName = "";
  let langAttrs = "";
  if (info) {
    const arr = info.split(/(\s+)/g);
    langName = arr[0];
    langAttrs = arr.slice(2).join("");
  }
  let highlighted;
  if (options.highlight) {
    highlighted = options.highlight(token2.content, langName, langAttrs) || escapeHtml(token2.content);
  } else {
    highlighted = escapeHtml(token2.content);
  }
  if (highlighted.indexOf("<pre") === 0) {
    return highlighted + "\n";
  }
  if (info) {
    const i = token2.attrIndex("class");
    const tmpAttrs = token2.attrs ? token2.attrs.slice() : [];
    if (i < 0) {
      tmpAttrs.push(["class", options.langPrefix + langName]);
    } else {
      tmpAttrs[i] = tmpAttrs[i].slice();
      tmpAttrs[i][1] += " " + options.langPrefix + langName;
    }
    const tmpToken = {
      attrs: tmpAttrs
    };
    return `<pre><code${slf.renderAttrs(tmpToken)}>${highlighted}</code></pre>
`;
  }
  return `<pre><code${slf.renderAttrs(token2)}>${highlighted}</code></pre>
`;
};
default_rules.image = function(tokens, idx, options, env, slf) {
  const token2 = tokens[idx];
  token2.attrs[token2.attrIndex("alt")][1] = slf.renderInlineAsText(token2.children, options, env);
  return slf.renderToken(tokens, idx, options);
};
default_rules.hardbreak = function(tokens, idx, options) {
  return options.xhtmlOut ? "<br />\n" : "<br>\n";
};
default_rules.softbreak = function(tokens, idx, options) {
  return options.breaks ? options.xhtmlOut ? "<br />\n" : "<br>\n" : "\n";
};
default_rules.text = function(tokens, idx) {
  return escapeHtml(tokens[idx].content);
};
default_rules.html_block = function(tokens, idx) {
  return tokens[idx].content;
};
default_rules.html_inline = function(tokens, idx) {
  return tokens[idx].content;
};
function Renderer() {
  this.rules = assign$1({}, default_rules);
}
Renderer.prototype.renderAttrs = function renderAttrs(token2) {
  let i, l2, result;
  if (!token2.attrs) {
    return "";
  }
  result = "";
  for (i = 0, l2 = token2.attrs.length; i < l2; i++) {
    result += " " + escapeHtml(token2.attrs[i][0]) + '="' + escapeHtml(token2.attrs[i][1]) + '"';
  }
  return result;
};
Renderer.prototype.renderToken = function renderToken(tokens, idx, options) {
  const token2 = tokens[idx];
  let result = "";
  if (token2.hidden) {
    return "";
  }
  if (token2.block && token2.nesting !== -1 && idx && tokens[idx - 1].hidden) {
    result += "\n";
  }
  result += (token2.nesting === -1 ? "</" : "<") + token2.tag;
  result += this.renderAttrs(token2);
  if (token2.nesting === 0 && options.xhtmlOut) {
    result += " /";
  }
  let needLf = false;
  if (token2.block) {
    needLf = true;
    if (token2.nesting === 1) {
      if (idx + 1 < tokens.length) {
        const nextToken = tokens[idx + 1];
        if (nextToken.type === "inline" || nextToken.hidden) {
          needLf = false;
        } else if (nextToken.nesting === -1 && nextToken.tag === token2.tag) {
          needLf = false;
        }
      }
    }
  }
  result += needLf ? ">\n" : ">";
  return result;
};
Renderer.prototype.renderInline = function(tokens, options, env) {
  let result = "";
  const rules = this.rules;
  for (let i = 0, len = tokens.length; i < len; i++) {
    const type = tokens[i].type;
    if (typeof rules[type] !== "undefined") {
      result += rules[type](tokens, i, options, env, this);
    } else {
      result += this.renderToken(tokens, i, options);
    }
  }
  return result;
};
Renderer.prototype.renderInlineAsText = function(tokens, options, env) {
  let result = "";
  for (let i = 0, len = tokens.length; i < len; i++) {
    switch (tokens[i].type) {
      case "text":
        result += tokens[i].content;
        break;
      case "image":
        result += this.renderInlineAsText(tokens[i].children, options, env);
        break;
      case "html_inline":
      case "html_block":
        result += tokens[i].content;
        break;
      case "softbreak":
      case "hardbreak":
        result += "\n";
        break;
    }
  }
  return result;
};
Renderer.prototype.render = function(tokens, options, env) {
  let result = "";
  const rules = this.rules;
  for (let i = 0, len = tokens.length; i < len; i++) {
    const type = tokens[i].type;
    if (type === "inline") {
      result += this.renderInline(tokens[i].children, options, env);
    } else if (typeof rules[type] !== "undefined") {
      result += rules[type](tokens, i, options, env, this);
    } else {
      result += this.renderToken(tokens, i, options, env);
    }
  }
  return result;
};
function Ruler() {
  this.__rules__ = [];
  this.__cache__ = null;
}
Ruler.prototype.__find__ = function(name) {
  for (let i = 0; i < this.__rules__.length; i++) {
    if (this.__rules__[i].name === name) {
      return i;
    }
  }
  return -1;
};
Ruler.prototype.__compile__ = function() {
  const self2 = this;
  const chains = [""];
  self2.__rules__.forEach(function(rule) {
    if (!rule.enabled) {
      return;
    }
    rule.alt.forEach(function(altName) {
      if (chains.indexOf(altName) < 0) {
        chains.push(altName);
      }
    });
  });
  self2.__cache__ = {};
  chains.forEach(function(chain) {
    self2.__cache__[chain] = [];
    self2.__rules__.forEach(function(rule) {
      if (!rule.enabled) {
        return;
      }
      if (chain && rule.alt.indexOf(chain) < 0) {
        return;
      }
      self2.__cache__[chain].push(rule.fn);
    });
  });
};
Ruler.prototype.at = function(name, fn2, options) {
  const index = this.__find__(name);
  const opt = options || {};
  if (index === -1) {
    throw new Error("Parser rule not found: " + name);
  }
  this.__rules__[index].fn = fn2;
  this.__rules__[index].alt = opt.alt || [];
  this.__cache__ = null;
};
Ruler.prototype.before = function(beforeName, ruleName, fn2, options) {
  const index = this.__find__(beforeName);
  const opt = options || {};
  if (index === -1) {
    throw new Error("Parser rule not found: " + beforeName);
  }
  this.__rules__.splice(index, 0, {
    name: ruleName,
    enabled: true,
    fn: fn2,
    alt: opt.alt || []
  });
  this.__cache__ = null;
};
Ruler.prototype.after = function(afterName, ruleName, fn2, options) {
  const index = this.__find__(afterName);
  const opt = options || {};
  if (index === -1) {
    throw new Error("Parser rule not found: " + afterName);
  }
  this.__rules__.splice(index + 1, 0, {
    name: ruleName,
    enabled: true,
    fn: fn2,
    alt: opt.alt || []
  });
  this.__cache__ = null;
};
Ruler.prototype.push = function(ruleName, fn2, options) {
  const opt = options || {};
  this.__rules__.push({
    name: ruleName,
    enabled: true,
    fn: fn2,
    alt: opt.alt || []
  });
  this.__cache__ = null;
};
Ruler.prototype.enable = function(list2, ignoreInvalid) {
  if (!Array.isArray(list2)) {
    list2 = [list2];
  }
  const result = [];
  list2.forEach(function(name) {
    const idx = this.__find__(name);
    if (idx < 0) {
      if (ignoreInvalid) {
        return;
      }
      throw new Error("Rules manager: invalid rule name " + name);
    }
    this.__rules__[idx].enabled = true;
    result.push(name);
  }, this);
  this.__cache__ = null;
  return result;
};
Ruler.prototype.enableOnly = function(list2, ignoreInvalid) {
  if (!Array.isArray(list2)) {
    list2 = [list2];
  }
  this.__rules__.forEach(function(rule) {
    rule.enabled = false;
  });
  this.enable(list2, ignoreInvalid);
};
Ruler.prototype.disable = function(list2, ignoreInvalid) {
  if (!Array.isArray(list2)) {
    list2 = [list2];
  }
  const result = [];
  list2.forEach(function(name) {
    const idx = this.__find__(name);
    if (idx < 0) {
      if (ignoreInvalid) {
        return;
      }
      throw new Error("Rules manager: invalid rule name " + name);
    }
    this.__rules__[idx].enabled = false;
    result.push(name);
  }, this);
  this.__cache__ = null;
  return result;
};
Ruler.prototype.getRules = function(chainName) {
  if (this.__cache__ === null) {
    this.__compile__();
  }
  return this.__cache__[chainName] || [];
};
function Token(type, tag, nesting) {
  this.type = type;
  this.tag = tag;
  this.attrs = null;
  this.map = null;
  this.nesting = nesting;
  this.level = 0;
  this.children = null;
  this.content = "";
  this.markup = "";
  this.info = "";
  this.meta = null;
  this.block = false;
  this.hidden = false;
}
Token.prototype.attrIndex = function attrIndex(name) {
  if (!this.attrs) {
    return -1;
  }
  const attrs = this.attrs;
  for (let i = 0, len = attrs.length; i < len; i++) {
    if (attrs[i][0] === name) {
      return i;
    }
  }
  return -1;
};
Token.prototype.attrPush = function attrPush(attrData) {
  if (this.attrs) {
    this.attrs.push(attrData);
  } else {
    this.attrs = [attrData];
  }
};
Token.prototype.attrSet = function attrSet(name, value) {
  const idx = this.attrIndex(name);
  const attrData = [name, value];
  if (idx < 0) {
    this.attrPush(attrData);
  } else {
    this.attrs[idx] = attrData;
  }
};
Token.prototype.attrGet = function attrGet(name) {
  const idx = this.attrIndex(name);
  let value = null;
  if (idx >= 0) {
    value = this.attrs[idx][1];
  }
  return value;
};
Token.prototype.attrJoin = function attrJoin(name, value) {
  const idx = this.attrIndex(name);
  if (idx < 0) {
    this.attrPush([name, value]);
  } else {
    this.attrs[idx][1] = this.attrs[idx][1] + " " + value;
  }
};
function StateCore(src, md, env) {
  this.src = src;
  this.env = env;
  this.tokens = [];
  this.inlineMode = false;
  this.md = md;
}
StateCore.prototype.Token = Token;
const NEWLINES_RE = /\r\n?|\n/g;
const NULL_RE = /\0/g;
function normalize(state) {
  let str;
  str = state.src.replace(NEWLINES_RE, "\n");
  str = str.replace(NULL_RE, "�");
  state.src = str;
}
function block(state) {
  let token2;
  if (state.inlineMode) {
    token2 = new state.Token("inline", "", 0);
    token2.content = state.src;
    token2.map = [0, 1];
    token2.children = [];
    state.tokens.push(token2);
  } else {
    state.md.block.parse(state.src, state.md, state.env, state.tokens);
  }
}
function inline(state) {
  const tokens = state.tokens;
  for (let i = 0, l2 = tokens.length; i < l2; i++) {
    const tok = tokens[i];
    if (tok.type === "inline") {
      state.md.inline.parse(tok.content, state.md, state.env, tok.children);
    }
  }
}
function isLinkOpen$1(str) {
  return /^<a[>\s]/i.test(str);
}
function isLinkClose$1(str) {
  return /^<\/a\s*>/i.test(str);
}
function linkify$1(state) {
  const blockTokens = state.tokens;
  if (!state.md.options.linkify) {
    return;
  }
  for (let j2 = 0, l2 = blockTokens.length; j2 < l2; j2++) {
    if (blockTokens[j2].type !== "inline" || !state.md.linkify.pretest(blockTokens[j2].content)) {
      continue;
    }
    let tokens = blockTokens[j2].children;
    let htmlLinkLevel = 0;
    for (let i = tokens.length - 1; i >= 0; i--) {
      const currentToken = tokens[i];
      if (currentToken.type === "link_close") {
        i--;
        while (tokens[i].level !== currentToken.level && tokens[i].type !== "link_open") {
          i--;
        }
        continue;
      }
      if (currentToken.type === "html_inline") {
        if (isLinkOpen$1(currentToken.content) && htmlLinkLevel > 0) {
          htmlLinkLevel--;
        }
        if (isLinkClose$1(currentToken.content)) {
          htmlLinkLevel++;
        }
      }
      if (htmlLinkLevel > 0) {
        continue;
      }
      if (currentToken.type === "text" && state.md.linkify.test(currentToken.content)) {
        const text2 = currentToken.content;
        let links = state.md.linkify.match(text2);
        const nodes = [];
        let level = currentToken.level;
        let lastPos = 0;
        if (links.length > 0 && links[0].index === 0 && i > 0 && tokens[i - 1].type === "text_special") {
          links = links.slice(1);
        }
        for (let ln = 0; ln < links.length; ln++) {
          const url = links[ln].url;
          const fullUrl = state.md.normalizeLink(url);
          if (!state.md.validateLink(fullUrl)) {
            continue;
          }
          let urlText = links[ln].text;
          if (!links[ln].schema) {
            urlText = state.md.normalizeLinkText("http://" + urlText).replace(/^http:\/\//, "");
          } else if (links[ln].schema === "mailto:" && !/^mailto:/i.test(urlText)) {
            urlText = state.md.normalizeLinkText("mailto:" + urlText).replace(/^mailto:/, "");
          } else {
            urlText = state.md.normalizeLinkText(urlText);
          }
          const pos2 = links[ln].index;
          if (pos2 > lastPos) {
            const token2 = new state.Token("text", "", 0);
            token2.content = text2.slice(lastPos, pos2);
            token2.level = level;
            nodes.push(token2);
          }
          const token_o = new state.Token("link_open", "a", 1);
          token_o.attrs = [["href", fullUrl]];
          token_o.level = level++;
          token_o.markup = "linkify";
          token_o.info = "auto";
          nodes.push(token_o);
          const token_t = new state.Token("text", "", 0);
          token_t.content = urlText;
          token_t.level = level;
          nodes.push(token_t);
          const token_c = new state.Token("link_close", "a", -1);
          token_c.level = --level;
          token_c.markup = "linkify";
          token_c.info = "auto";
          nodes.push(token_c);
          lastPos = links[ln].lastIndex;
        }
        if (lastPos < text2.length) {
          const token2 = new state.Token("text", "", 0);
          token2.content = text2.slice(lastPos);
          token2.level = level;
          nodes.push(token2);
        }
        blockTokens[j2].children = tokens = arrayReplaceAt(tokens, i, nodes);
      }
    }
  }
}
const RARE_RE = /\+-|\.\.|\?\?\?\?|!!!!|,,|--/;
const SCOPED_ABBR_TEST_RE = /\((c|tm|r)\)/i;
const SCOPED_ABBR_RE = /\((c|tm|r)\)/ig;
const SCOPED_ABBR = {
  c: "©",
  r: "®",
  tm: "™"
};
function replaceFn(match2, name) {
  return SCOPED_ABBR[name.toLowerCase()];
}
function replace_scoped(inlineTokens) {
  let inside_autolink = 0;
  for (let i = inlineTokens.length - 1; i >= 0; i--) {
    const token2 = inlineTokens[i];
    if (token2.type === "text" && !inside_autolink) {
      token2.content = token2.content.replace(SCOPED_ABBR_RE, replaceFn);
    }
    if (token2.type === "link_open" && token2.info === "auto") {
      inside_autolink--;
    }
    if (token2.type === "link_close" && token2.info === "auto") {
      inside_autolink++;
    }
  }
}
function replace_rare(inlineTokens) {
  let inside_autolink = 0;
  for (let i = inlineTokens.length - 1; i >= 0; i--) {
    const token2 = inlineTokens[i];
    if (token2.type === "text" && !inside_autolink) {
      if (RARE_RE.test(token2.content)) {
        token2.content = token2.content.replace(/\+-/g, "±").replace(/\.{2,}/g, "…").replace(/([?!])…/g, "$1..").replace(/([?!]){4,}/g, "$1$1$1").replace(/,{2,}/g, ",").replace(/(^|[^-])---(?=[^-]|$)/mg, "$1—").replace(/(^|\s)--(?=\s|$)/mg, "$1–").replace(/(^|[^-\s])--(?=[^-\s]|$)/mg, "$1–");
      }
    }
    if (token2.type === "link_open" && token2.info === "auto") {
      inside_autolink--;
    }
    if (token2.type === "link_close" && token2.info === "auto") {
      inside_autolink++;
    }
  }
}
function replace(state) {
  let blkIdx;
  if (!state.md.options.typographer) {
    return;
  }
  for (blkIdx = state.tokens.length - 1; blkIdx >= 0; blkIdx--) {
    if (state.tokens[blkIdx].type !== "inline") {
      continue;
    }
    if (SCOPED_ABBR_TEST_RE.test(state.tokens[blkIdx].content)) {
      replace_scoped(state.tokens[blkIdx].children);
    }
    if (RARE_RE.test(state.tokens[blkIdx].content)) {
      replace_rare(state.tokens[blkIdx].children);
    }
  }
}
const QUOTE_TEST_RE = /['"]/;
const QUOTE_RE = /['"]/g;
const APOSTROPHE = "’";
function replaceAt(str, index, ch3) {
  return str.slice(0, index) + ch3 + str.slice(index + 1);
}
function process_inlines(tokens, state) {
  let j2;
  const stack2 = [];
  for (let i = 0; i < tokens.length; i++) {
    const token2 = tokens[i];
    const thisLevel = tokens[i].level;
    for (j2 = stack2.length - 1; j2 >= 0; j2--) {
      if (stack2[j2].level <= thisLevel) {
        break;
      }
    }
    stack2.length = j2 + 1;
    if (token2.type !== "text") {
      continue;
    }
    let text2 = token2.content;
    let pos2 = 0;
    let max2 = text2.length;
    OUTER:
      while (pos2 < max2) {
        QUOTE_RE.lastIndex = pos2;
        const t2 = QUOTE_RE.exec(text2);
        if (!t2) {
          break;
        }
        let canOpen = true;
        let canClose = true;
        pos2 = t2.index + 1;
        const isSingle = t2[0] === "'";
        let lastChar = 32;
        if (t2.index - 1 >= 0) {
          lastChar = text2.charCodeAt(t2.index - 1);
        } else {
          for (j2 = i - 1; j2 >= 0; j2--) {
            if (tokens[j2].type === "softbreak" || tokens[j2].type === "hardbreak") break;
            if (!tokens[j2].content) continue;
            lastChar = tokens[j2].content.charCodeAt(tokens[j2].content.length - 1);
            break;
          }
        }
        let nextChar = 32;
        if (pos2 < max2) {
          nextChar = text2.charCodeAt(pos2);
        } else {
          for (j2 = i + 1; j2 < tokens.length; j2++) {
            if (tokens[j2].type === "softbreak" || tokens[j2].type === "hardbreak") break;
            if (!tokens[j2].content) continue;
            nextChar = tokens[j2].content.charCodeAt(0);
            break;
          }
        }
        const isLastPunctChar = isMdAsciiPunct(lastChar) || isPunctChar(String.fromCharCode(lastChar));
        const isNextPunctChar = isMdAsciiPunct(nextChar) || isPunctChar(String.fromCharCode(nextChar));
        const isLastWhiteSpace = isWhiteSpace(lastChar);
        const isNextWhiteSpace = isWhiteSpace(nextChar);
        if (isNextWhiteSpace) {
          canOpen = false;
        } else if (isNextPunctChar) {
          if (!(isLastWhiteSpace || isLastPunctChar)) {
            canOpen = false;
          }
        }
        if (isLastWhiteSpace) {
          canClose = false;
        } else if (isLastPunctChar) {
          if (!(isNextWhiteSpace || isNextPunctChar)) {
            canClose = false;
          }
        }
        if (nextChar === 34 && t2[0] === '"') {
          if (lastChar >= 48 && lastChar <= 57) {
            canClose = canOpen = false;
          }
        }
        if (canOpen && canClose) {
          canOpen = isLastPunctChar;
          canClose = isNextPunctChar;
        }
        if (!canOpen && !canClose) {
          if (isSingle) {
            token2.content = replaceAt(token2.content, t2.index, APOSTROPHE);
          }
          continue;
        }
        if (canClose) {
          for (j2 = stack2.length - 1; j2 >= 0; j2--) {
            let item = stack2[j2];
            if (stack2[j2].level < thisLevel) {
              break;
            }
            if (item.single === isSingle && stack2[j2].level === thisLevel) {
              item = stack2[j2];
              let openQuote;
              let closeQuote;
              if (isSingle) {
                openQuote = state.md.options.quotes[2];
                closeQuote = state.md.options.quotes[3];
              } else {
                openQuote = state.md.options.quotes[0];
                closeQuote = state.md.options.quotes[1];
              }
              token2.content = replaceAt(token2.content, t2.index, closeQuote);
              tokens[item.token].content = replaceAt(
                tokens[item.token].content,
                item.pos,
                openQuote
              );
              pos2 += closeQuote.length - 1;
              if (item.token === i) {
                pos2 += openQuote.length - 1;
              }
              text2 = token2.content;
              max2 = text2.length;
              stack2.length = j2;
              continue OUTER;
            }
          }
        }
        if (canOpen) {
          stack2.push({
            token: i,
            pos: t2.index,
            single: isSingle,
            level: thisLevel
          });
        } else if (canClose && isSingle) {
          token2.content = replaceAt(token2.content, t2.index, APOSTROPHE);
        }
      }
  }
}
function smartquotes(state) {
  if (!state.md.options.typographer) {
    return;
  }
  for (let blkIdx = state.tokens.length - 1; blkIdx >= 0; blkIdx--) {
    if (state.tokens[blkIdx].type !== "inline" || !QUOTE_TEST_RE.test(state.tokens[blkIdx].content)) {
      continue;
    }
    process_inlines(state.tokens[blkIdx].children, state);
  }
}
function text_join(state) {
  let curr, last;
  const blockTokens = state.tokens;
  const l2 = blockTokens.length;
  for (let j2 = 0; j2 < l2; j2++) {
    if (blockTokens[j2].type !== "inline") continue;
    const tokens = blockTokens[j2].children;
    const max2 = tokens.length;
    for (curr = 0; curr < max2; curr++) {
      if (tokens[curr].type === "text_special") {
        tokens[curr].type = "text";
      }
    }
    for (curr = last = 0; curr < max2; curr++) {
      if (tokens[curr].type === "text" && curr + 1 < max2 && tokens[curr + 1].type === "text") {
        tokens[curr + 1].content = tokens[curr].content + tokens[curr + 1].content;
      } else {
        if (curr !== last) {
          tokens[last] = tokens[curr];
        }
        last++;
      }
    }
    if (curr !== last) {
      tokens.length = last;
    }
  }
}
const _rules$2 = [
  ["normalize", normalize],
  ["block", block],
  ["inline", inline],
  ["linkify", linkify$1],
  ["replacements", replace],
  ["smartquotes", smartquotes],
  // `text_join` finds `text_special` tokens (for escape sequences)
  // and joins them with the rest of the text
  ["text_join", text_join]
];
function Core() {
  this.ruler = new Ruler();
  for (let i = 0; i < _rules$2.length; i++) {
    this.ruler.push(_rules$2[i][0], _rules$2[i][1]);
  }
}
Core.prototype.process = function(state) {
  const rules = this.ruler.getRules("");
  for (let i = 0, l2 = rules.length; i < l2; i++) {
    rules[i](state);
  }
};
Core.prototype.State = StateCore;
function StateBlock(src, md, env, tokens) {
  this.src = src;
  this.md = md;
  this.env = env;
  this.tokens = tokens;
  this.bMarks = [];
  this.eMarks = [];
  this.tShift = [];
  this.sCount = [];
  this.bsCount = [];
  this.blkIndent = 0;
  this.line = 0;
  this.lineMax = 0;
  this.tight = false;
  this.ddIndent = -1;
  this.listIndent = -1;
  this.parentType = "root";
  this.level = 0;
  const s2 = this.src;
  for (let start2 = 0, pos2 = 0, indent = 0, offset2 = 0, len = s2.length, indent_found = false; pos2 < len; pos2++) {
    const ch3 = s2.charCodeAt(pos2);
    if (!indent_found) {
      if (isSpace(ch3)) {
        indent++;
        if (ch3 === 9) {
          offset2 += 4 - offset2 % 4;
        } else {
          offset2++;
        }
        continue;
      } else {
        indent_found = true;
      }
    }
    if (ch3 === 10 || pos2 === len - 1) {
      if (ch3 !== 10) {
        pos2++;
      }
      this.bMarks.push(start2);
      this.eMarks.push(pos2);
      this.tShift.push(indent);
      this.sCount.push(offset2);
      this.bsCount.push(0);
      indent_found = false;
      indent = 0;
      offset2 = 0;
      start2 = pos2 + 1;
    }
  }
  this.bMarks.push(s2.length);
  this.eMarks.push(s2.length);
  this.tShift.push(0);
  this.sCount.push(0);
  this.bsCount.push(0);
  this.lineMax = this.bMarks.length - 1;
}
StateBlock.prototype.push = function(type, tag, nesting) {
  const token2 = new Token(type, tag, nesting);
  token2.block = true;
  if (nesting < 0) this.level--;
  token2.level = this.level;
  if (nesting > 0) this.level++;
  this.tokens.push(token2);
  return token2;
};
StateBlock.prototype.isEmpty = function isEmpty(line2) {
  return this.bMarks[line2] + this.tShift[line2] >= this.eMarks[line2];
};
StateBlock.prototype.skipEmptyLines = function skipEmptyLines(from) {
  for (let max2 = this.lineMax; from < max2; from++) {
    if (this.bMarks[from] + this.tShift[from] < this.eMarks[from]) {
      break;
    }
  }
  return from;
};
StateBlock.prototype.skipSpaces = function skipSpaces(pos2) {
  for (let max2 = this.src.length; pos2 < max2; pos2++) {
    const ch3 = this.src.charCodeAt(pos2);
    if (!isSpace(ch3)) {
      break;
    }
  }
  return pos2;
};
StateBlock.prototype.skipSpacesBack = function skipSpacesBack(pos2, min2) {
  if (pos2 <= min2) {
    return pos2;
  }
  while (pos2 > min2) {
    if (!isSpace(this.src.charCodeAt(--pos2))) {
      return pos2 + 1;
    }
  }
  return pos2;
};
StateBlock.prototype.skipChars = function skipChars(pos2, code2) {
  for (let max2 = this.src.length; pos2 < max2; pos2++) {
    if (this.src.charCodeAt(pos2) !== code2) {
      break;
    }
  }
  return pos2;
};
StateBlock.prototype.skipCharsBack = function skipCharsBack(pos2, code2, min2) {
  if (pos2 <= min2) {
    return pos2;
  }
  while (pos2 > min2) {
    if (code2 !== this.src.charCodeAt(--pos2)) {
      return pos2 + 1;
    }
  }
  return pos2;
};
StateBlock.prototype.getLines = function getLines(begin, end2, indent, keepLastLF) {
  if (begin >= end2) {
    return "";
  }
  const queue = new Array(end2 - begin);
  for (let i = 0, line2 = begin; line2 < end2; line2++, i++) {
    let lineIndent = 0;
    const lineStart = this.bMarks[line2];
    let first = lineStart;
    let last;
    if (line2 + 1 < end2 || keepLastLF) {
      last = this.eMarks[line2] + 1;
    } else {
      last = this.eMarks[line2];
    }
    while (first < last && lineIndent < indent) {
      const ch3 = this.src.charCodeAt(first);
      if (isSpace(ch3)) {
        if (ch3 === 9) {
          lineIndent += 4 - (lineIndent + this.bsCount[line2]) % 4;
        } else {
          lineIndent++;
        }
      } else if (first - lineStart < this.tShift[line2]) {
        lineIndent++;
      } else {
        break;
      }
      first++;
    }
    if (lineIndent > indent) {
      queue[i] = new Array(lineIndent - indent + 1).join(" ") + this.src.slice(first, last);
    } else {
      queue[i] = this.src.slice(first, last);
    }
  }
  return queue.join("");
};
StateBlock.prototype.Token = Token;
const MAX_AUTOCOMPLETED_CELLS = 65536;
function getLine(state, line2) {
  const pos2 = state.bMarks[line2] + state.tShift[line2];
  const max2 = state.eMarks[line2];
  return state.src.slice(pos2, max2);
}
function escapedSplit(str) {
  const result = [];
  const max2 = str.length;
  let pos2 = 0;
  let ch3 = str.charCodeAt(pos2);
  let isEscaped = false;
  let lastPos = 0;
  let current = "";
  while (pos2 < max2) {
    if (ch3 === 124) {
      if (!isEscaped) {
        result.push(current + str.substring(lastPos, pos2));
        current = "";
        lastPos = pos2 + 1;
      } else {
        current += str.substring(lastPos, pos2 - 1);
        lastPos = pos2;
      }
    }
    isEscaped = ch3 === 92;
    pos2++;
    ch3 = str.charCodeAt(pos2);
  }
  result.push(current + str.substring(lastPos));
  return result;
}
function table(state, startLine, endLine, silent) {
  if (startLine + 2 > endLine) {
    return false;
  }
  let nextLine = startLine + 1;
  if (state.sCount[nextLine] < state.blkIndent) {
    return false;
  }
  if (state.sCount[nextLine] - state.blkIndent >= 4) {
    return false;
  }
  let pos2 = state.bMarks[nextLine] + state.tShift[nextLine];
  if (pos2 >= state.eMarks[nextLine]) {
    return false;
  }
  const firstCh = state.src.charCodeAt(pos2++);
  if (firstCh !== 124 && firstCh !== 45 && firstCh !== 58) {
    return false;
  }
  if (pos2 >= state.eMarks[nextLine]) {
    return false;
  }
  const secondCh = state.src.charCodeAt(pos2++);
  if (secondCh !== 124 && secondCh !== 45 && secondCh !== 58 && !isSpace(secondCh)) {
    return false;
  }
  if (firstCh === 45 && isSpace(secondCh)) {
    return false;
  }
  while (pos2 < state.eMarks[nextLine]) {
    const ch3 = state.src.charCodeAt(pos2);
    if (ch3 !== 124 && ch3 !== 45 && ch3 !== 58 && !isSpace(ch3)) {
      return false;
    }
    pos2++;
  }
  let lineText = getLine(state, startLine + 1);
  let columns = lineText.split("|");
  const aligns = [];
  for (let i = 0; i < columns.length; i++) {
    const t2 = columns[i].trim();
    if (!t2) {
      if (i === 0 || i === columns.length - 1) {
        continue;
      } else {
        return false;
      }
    }
    if (!/^:?-+:?$/.test(t2)) {
      return false;
    }
    if (t2.charCodeAt(t2.length - 1) === 58) {
      aligns.push(t2.charCodeAt(0) === 58 ? "center" : "right");
    } else if (t2.charCodeAt(0) === 58) {
      aligns.push("left");
    } else {
      aligns.push("");
    }
  }
  lineText = getLine(state, startLine).trim();
  if (lineText.indexOf("|") === -1) {
    return false;
  }
  if (state.sCount[startLine] - state.blkIndent >= 4) {
    return false;
  }
  columns = escapedSplit(lineText);
  if (columns.length && columns[0] === "") columns.shift();
  if (columns.length && columns[columns.length - 1] === "") columns.pop();
  const columnCount = columns.length;
  if (columnCount === 0 || columnCount !== aligns.length) {
    return false;
  }
  if (silent) {
    return true;
  }
  const oldParentType = state.parentType;
  state.parentType = "table";
  const terminatorRules = state.md.block.ruler.getRules("blockquote");
  const token_to = state.push("table_open", "table", 1);
  const tableLines = [startLine, 0];
  token_to.map = tableLines;
  const token_tho = state.push("thead_open", "thead", 1);
  token_tho.map = [startLine, startLine + 1];
  const token_htro = state.push("tr_open", "tr", 1);
  token_htro.map = [startLine, startLine + 1];
  for (let i = 0; i < columns.length; i++) {
    const token_ho = state.push("th_open", "th", 1);
    if (aligns[i]) {
      token_ho.attrs = [["style", "text-align:" + aligns[i]]];
    }
    const token_il = state.push("inline", "", 0);
    token_il.content = columns[i].trim();
    token_il.children = [];
    state.push("th_close", "th", -1);
  }
  state.push("tr_close", "tr", -1);
  state.push("thead_close", "thead", -1);
  let tbodyLines;
  let autocompletedCells = 0;
  for (nextLine = startLine + 2; nextLine < endLine; nextLine++) {
    if (state.sCount[nextLine] < state.blkIndent) {
      break;
    }
    let terminate = false;
    for (let i = 0, l2 = terminatorRules.length; i < l2; i++) {
      if (terminatorRules[i](state, nextLine, endLine, true)) {
        terminate = true;
        break;
      }
    }
    if (terminate) {
      break;
    }
    lineText = getLine(state, nextLine).trim();
    if (!lineText) {
      break;
    }
    if (state.sCount[nextLine] - state.blkIndent >= 4) {
      break;
    }
    columns = escapedSplit(lineText);
    if (columns.length && columns[0] === "") columns.shift();
    if (columns.length && columns[columns.length - 1] === "") columns.pop();
    autocompletedCells += columnCount - columns.length;
    if (autocompletedCells > MAX_AUTOCOMPLETED_CELLS) {
      break;
    }
    if (nextLine === startLine + 2) {
      const token_tbo = state.push("tbody_open", "tbody", 1);
      token_tbo.map = tbodyLines = [startLine + 2, 0];
    }
    const token_tro = state.push("tr_open", "tr", 1);
    token_tro.map = [nextLine, nextLine + 1];
    for (let i = 0; i < columnCount; i++) {
      const token_tdo = state.push("td_open", "td", 1);
      if (aligns[i]) {
        token_tdo.attrs = [["style", "text-align:" + aligns[i]]];
      }
      const token_il = state.push("inline", "", 0);
      token_il.content = columns[i] ? columns[i].trim() : "";
      token_il.children = [];
      state.push("td_close", "td", -1);
    }
    state.push("tr_close", "tr", -1);
  }
  if (tbodyLines) {
    state.push("tbody_close", "tbody", -1);
    tbodyLines[1] = nextLine;
  }
  state.push("table_close", "table", -1);
  tableLines[1] = nextLine;
  state.parentType = oldParentType;
  state.line = nextLine;
  return true;
}
function code(state, startLine, endLine) {
  if (state.sCount[startLine] - state.blkIndent < 4) {
    return false;
  }
  let nextLine = startLine + 1;
  let last = nextLine;
  while (nextLine < endLine) {
    if (state.isEmpty(nextLine)) {
      nextLine++;
      continue;
    }
    if (state.sCount[nextLine] - state.blkIndent >= 4) {
      nextLine++;
      last = nextLine;
      continue;
    }
    break;
  }
  state.line = last;
  const token2 = state.push("code_block", "code", 0);
  token2.content = state.getLines(startLine, last, 4 + state.blkIndent, false) + "\n";
  token2.map = [startLine, state.line];
  return true;
}
function fence(state, startLine, endLine, silent) {
  let pos2 = state.bMarks[startLine] + state.tShift[startLine];
  let max2 = state.eMarks[startLine];
  if (state.sCount[startLine] - state.blkIndent >= 4) {
    return false;
  }
  if (pos2 + 3 > max2) {
    return false;
  }
  const marker = state.src.charCodeAt(pos2);
  if (marker !== 126 && marker !== 96) {
    return false;
  }
  let mem = pos2;
  pos2 = state.skipChars(pos2, marker);
  let len = pos2 - mem;
  if (len < 3) {
    return false;
  }
  const markup = state.src.slice(mem, pos2);
  const params = state.src.slice(pos2, max2);
  if (marker === 96) {
    if (params.indexOf(String.fromCharCode(marker)) >= 0) {
      return false;
    }
  }
  if (silent) {
    return true;
  }
  let nextLine = startLine;
  let haveEndMarker = false;
  for (; ; ) {
    nextLine++;
    if (nextLine >= endLine) {
      break;
    }
    pos2 = mem = state.bMarks[nextLine] + state.tShift[nextLine];
    max2 = state.eMarks[nextLine];
    if (pos2 < max2 && state.sCount[nextLine] < state.blkIndent) {
      break;
    }
    if (state.src.charCodeAt(pos2) !== marker) {
      continue;
    }
    if (state.sCount[nextLine] - state.blkIndent >= 4) {
      continue;
    }
    pos2 = state.skipChars(pos2, marker);
    if (pos2 - mem < len) {
      continue;
    }
    pos2 = state.skipSpaces(pos2);
    if (pos2 < max2) {
      continue;
    }
    haveEndMarker = true;
    break;
  }
  len = state.sCount[startLine];
  state.line = nextLine + (haveEndMarker ? 1 : 0);
  const token2 = state.push("fence", "code", 0);
  token2.info = params;
  token2.content = state.getLines(startLine + 1, nextLine, len, true);
  token2.markup = markup;
  token2.map = [startLine, state.line];
  return true;
}
function blockquote(state, startLine, endLine, silent) {
  let pos2 = state.bMarks[startLine] + state.tShift[startLine];
  let max2 = state.eMarks[startLine];
  const oldLineMax = state.lineMax;
  if (state.sCount[startLine] - state.blkIndent >= 4) {
    return false;
  }
  if (state.src.charCodeAt(pos2) !== 62) {
    return false;
  }
  if (silent) {
    return true;
  }
  const oldBMarks = [];
  const oldBSCount = [];
  const oldSCount = [];
  const oldTShift = [];
  const terminatorRules = state.md.block.ruler.getRules("blockquote");
  const oldParentType = state.parentType;
  state.parentType = "blockquote";
  let lastLineEmpty = false;
  let nextLine;
  for (nextLine = startLine; nextLine < endLine; nextLine++) {
    const isOutdented = state.sCount[nextLine] < state.blkIndent;
    pos2 = state.bMarks[nextLine] + state.tShift[nextLine];
    max2 = state.eMarks[nextLine];
    if (pos2 >= max2) {
      break;
    }
    if (state.src.charCodeAt(pos2++) === 62 && !isOutdented) {
      let initial = state.sCount[nextLine] + 1;
      let spaceAfterMarker;
      let adjustTab;
      if (state.src.charCodeAt(pos2) === 32) {
        pos2++;
        initial++;
        adjustTab = false;
        spaceAfterMarker = true;
      } else if (state.src.charCodeAt(pos2) === 9) {
        spaceAfterMarker = true;
        if ((state.bsCount[nextLine] + initial) % 4 === 3) {
          pos2++;
          initial++;
          adjustTab = false;
        } else {
          adjustTab = true;
        }
      } else {
        spaceAfterMarker = false;
      }
      let offset2 = initial;
      oldBMarks.push(state.bMarks[nextLine]);
      state.bMarks[nextLine] = pos2;
      while (pos2 < max2) {
        const ch3 = state.src.charCodeAt(pos2);
        if (isSpace(ch3)) {
          if (ch3 === 9) {
            offset2 += 4 - (offset2 + state.bsCount[nextLine] + (adjustTab ? 1 : 0)) % 4;
          } else {
            offset2++;
          }
        } else {
          break;
        }
        pos2++;
      }
      lastLineEmpty = pos2 >= max2;
      oldBSCount.push(state.bsCount[nextLine]);
      state.bsCount[nextLine] = state.sCount[nextLine] + 1 + (spaceAfterMarker ? 1 : 0);
      oldSCount.push(state.sCount[nextLine]);
      state.sCount[nextLine] = offset2 - initial;
      oldTShift.push(state.tShift[nextLine]);
      state.tShift[nextLine] = pos2 - state.bMarks[nextLine];
      continue;
    }
    if (lastLineEmpty) {
      break;
    }
    let terminate = false;
    for (let i = 0, l2 = terminatorRules.length; i < l2; i++) {
      if (terminatorRules[i](state, nextLine, endLine, true)) {
        terminate = true;
        break;
      }
    }
    if (terminate) {
      state.lineMax = nextLine;
      if (state.blkIndent !== 0) {
        oldBMarks.push(state.bMarks[nextLine]);
        oldBSCount.push(state.bsCount[nextLine]);
        oldTShift.push(state.tShift[nextLine]);
        oldSCount.push(state.sCount[nextLine]);
        state.sCount[nextLine] -= state.blkIndent;
      }
      break;
    }
    oldBMarks.push(state.bMarks[nextLine]);
    oldBSCount.push(state.bsCount[nextLine]);
    oldTShift.push(state.tShift[nextLine]);
    oldSCount.push(state.sCount[nextLine]);
    state.sCount[nextLine] = -1;
  }
  const oldIndent = state.blkIndent;
  state.blkIndent = 0;
  const token_o = state.push("blockquote_open", "blockquote", 1);
  token_o.markup = ">";
  const lines = [startLine, 0];
  token_o.map = lines;
  state.md.block.tokenize(state, startLine, nextLine);
  const token_c = state.push("blockquote_close", "blockquote", -1);
  token_c.markup = ">";
  state.lineMax = oldLineMax;
  state.parentType = oldParentType;
  lines[1] = state.line;
  for (let i = 0; i < oldTShift.length; i++) {
    state.bMarks[i + startLine] = oldBMarks[i];
    state.tShift[i + startLine] = oldTShift[i];
    state.sCount[i + startLine] = oldSCount[i];
    state.bsCount[i + startLine] = oldBSCount[i];
  }
  state.blkIndent = oldIndent;
  return true;
}
function hr(state, startLine, endLine, silent) {
  const max2 = state.eMarks[startLine];
  if (state.sCount[startLine] - state.blkIndent >= 4) {
    return false;
  }
  let pos2 = state.bMarks[startLine] + state.tShift[startLine];
  const marker = state.src.charCodeAt(pos2++);
  if (marker !== 42 && marker !== 45 && marker !== 95) {
    return false;
  }
  let cnt = 1;
  while (pos2 < max2) {
    const ch3 = state.src.charCodeAt(pos2++);
    if (ch3 !== marker && !isSpace(ch3)) {
      return false;
    }
    if (ch3 === marker) {
      cnt++;
    }
  }
  if (cnt < 3) {
    return false;
  }
  if (silent) {
    return true;
  }
  state.line = startLine + 1;
  const token2 = state.push("hr", "hr", 0);
  token2.map = [startLine, state.line];
  token2.markup = Array(cnt + 1).join(String.fromCharCode(marker));
  return true;
}
function skipBulletListMarker(state, startLine) {
  const max2 = state.eMarks[startLine];
  let pos2 = state.bMarks[startLine] + state.tShift[startLine];
  const marker = state.src.charCodeAt(pos2++);
  if (marker !== 42 && marker !== 45 && marker !== 43) {
    return -1;
  }
  if (pos2 < max2) {
    const ch3 = state.src.charCodeAt(pos2);
    if (!isSpace(ch3)) {
      return -1;
    }
  }
  return pos2;
}
function skipOrderedListMarker(state, startLine) {
  const start2 = state.bMarks[startLine] + state.tShift[startLine];
  const max2 = state.eMarks[startLine];
  let pos2 = start2;
  if (pos2 + 1 >= max2) {
    return -1;
  }
  let ch3 = state.src.charCodeAt(pos2++);
  if (ch3 < 48 || ch3 > 57) {
    return -1;
  }
  for (; ; ) {
    if (pos2 >= max2) {
      return -1;
    }
    ch3 = state.src.charCodeAt(pos2++);
    if (ch3 >= 48 && ch3 <= 57) {
      if (pos2 - start2 >= 10) {
        return -1;
      }
      continue;
    }
    if (ch3 === 41 || ch3 === 46) {
      break;
    }
    return -1;
  }
  if (pos2 < max2) {
    ch3 = state.src.charCodeAt(pos2);
    if (!isSpace(ch3)) {
      return -1;
    }
  }
  return pos2;
}
function markTightParagraphs(state, idx) {
  const level = state.level + 2;
  for (let i = idx + 2, l2 = state.tokens.length - 2; i < l2; i++) {
    if (state.tokens[i].level === level && state.tokens[i].type === "paragraph_open") {
      state.tokens[i + 2].hidden = true;
      state.tokens[i].hidden = true;
      i += 2;
    }
  }
}
function list(state, startLine, endLine, silent) {
  let max2, pos2, start2, token2;
  let nextLine = startLine;
  let tight = true;
  if (state.sCount[nextLine] - state.blkIndent >= 4) {
    return false;
  }
  if (state.listIndent >= 0 && state.sCount[nextLine] - state.listIndent >= 4 && state.sCount[nextLine] < state.blkIndent) {
    return false;
  }
  let isTerminatingParagraph = false;
  if (silent && state.parentType === "paragraph") {
    if (state.sCount[nextLine] >= state.blkIndent) {
      isTerminatingParagraph = true;
    }
  }
  let isOrdered;
  let markerValue;
  let posAfterMarker;
  if ((posAfterMarker = skipOrderedListMarker(state, nextLine)) >= 0) {
    isOrdered = true;
    start2 = state.bMarks[nextLine] + state.tShift[nextLine];
    markerValue = Number(state.src.slice(start2, posAfterMarker - 1));
    if (isTerminatingParagraph && markerValue !== 1) return false;
  } else if ((posAfterMarker = skipBulletListMarker(state, nextLine)) >= 0) {
    isOrdered = false;
  } else {
    return false;
  }
  if (isTerminatingParagraph) {
    if (state.skipSpaces(posAfterMarker) >= state.eMarks[nextLine]) return false;
  }
  if (silent) {
    return true;
  }
  const markerCharCode = state.src.charCodeAt(posAfterMarker - 1);
  const listTokIdx = state.tokens.length;
  if (isOrdered) {
    token2 = state.push("ordered_list_open", "ol", 1);
    if (markerValue !== 1) {
      token2.attrs = [["start", markerValue]];
    }
  } else {
    token2 = state.push("bullet_list_open", "ul", 1);
  }
  const listLines = [nextLine, 0];
  token2.map = listLines;
  token2.markup = String.fromCharCode(markerCharCode);
  let prevEmptyEnd = false;
  const terminatorRules = state.md.block.ruler.getRules("list");
  const oldParentType = state.parentType;
  state.parentType = "list";
  while (nextLine < endLine) {
    pos2 = posAfterMarker;
    max2 = state.eMarks[nextLine];
    const initial = state.sCount[nextLine] + posAfterMarker - (state.bMarks[nextLine] + state.tShift[nextLine]);
    let offset2 = initial;
    while (pos2 < max2) {
      const ch3 = state.src.charCodeAt(pos2);
      if (ch3 === 9) {
        offset2 += 4 - (offset2 + state.bsCount[nextLine]) % 4;
      } else if (ch3 === 32) {
        offset2++;
      } else {
        break;
      }
      pos2++;
    }
    const contentStart = pos2;
    let indentAfterMarker;
    if (contentStart >= max2) {
      indentAfterMarker = 1;
    } else {
      indentAfterMarker = offset2 - initial;
    }
    if (indentAfterMarker > 4) {
      indentAfterMarker = 1;
    }
    const indent = initial + indentAfterMarker;
    token2 = state.push("list_item_open", "li", 1);
    token2.markup = String.fromCharCode(markerCharCode);
    const itemLines = [nextLine, 0];
    token2.map = itemLines;
    if (isOrdered) {
      token2.info = state.src.slice(start2, posAfterMarker - 1);
    }
    const oldTight = state.tight;
    const oldTShift = state.tShift[nextLine];
    const oldSCount = state.sCount[nextLine];
    const oldListIndent = state.listIndent;
    state.listIndent = state.blkIndent;
    state.blkIndent = indent;
    state.tight = true;
    state.tShift[nextLine] = contentStart - state.bMarks[nextLine];
    state.sCount[nextLine] = offset2;
    if (contentStart >= max2 && state.isEmpty(nextLine + 1)) {
      state.line = Math.min(state.line + 2, endLine);
    } else {
      state.md.block.tokenize(state, nextLine, endLine, true);
    }
    if (!state.tight || prevEmptyEnd) {
      tight = false;
    }
    prevEmptyEnd = state.line - nextLine > 1 && state.isEmpty(state.line - 1);
    state.blkIndent = state.listIndent;
    state.listIndent = oldListIndent;
    state.tShift[nextLine] = oldTShift;
    state.sCount[nextLine] = oldSCount;
    state.tight = oldTight;
    token2 = state.push("list_item_close", "li", -1);
    token2.markup = String.fromCharCode(markerCharCode);
    nextLine = state.line;
    itemLines[1] = nextLine;
    if (nextLine >= endLine) {
      break;
    }
    if (state.sCount[nextLine] < state.blkIndent) {
      break;
    }
    if (state.sCount[nextLine] - state.blkIndent >= 4) {
      break;
    }
    let terminate = false;
    for (let i = 0, l2 = terminatorRules.length; i < l2; i++) {
      if (terminatorRules[i](state, nextLine, endLine, true)) {
        terminate = true;
        break;
      }
    }
    if (terminate) {
      break;
    }
    if (isOrdered) {
      posAfterMarker = skipOrderedListMarker(state, nextLine);
      if (posAfterMarker < 0) {
        break;
      }
      start2 = state.bMarks[nextLine] + state.tShift[nextLine];
    } else {
      posAfterMarker = skipBulletListMarker(state, nextLine);
      if (posAfterMarker < 0) {
        break;
      }
    }
    if (markerCharCode !== state.src.charCodeAt(posAfterMarker - 1)) {
      break;
    }
  }
  if (isOrdered) {
    token2 = state.push("ordered_list_close", "ol", -1);
  } else {
    token2 = state.push("bullet_list_close", "ul", -1);
  }
  token2.markup = String.fromCharCode(markerCharCode);
  listLines[1] = nextLine;
  state.line = nextLine;
  state.parentType = oldParentType;
  if (tight) {
    markTightParagraphs(state, listTokIdx);
  }
  return true;
}
function reference(state, startLine, _endLine, silent) {
  let pos2 = state.bMarks[startLine] + state.tShift[startLine];
  let max2 = state.eMarks[startLine];
  let nextLine = startLine + 1;
  if (state.sCount[startLine] - state.blkIndent >= 4) {
    return false;
  }
  if (state.src.charCodeAt(pos2) !== 91) {
    return false;
  }
  function getNextLine(nextLine2) {
    const endLine = state.lineMax;
    if (nextLine2 >= endLine || state.isEmpty(nextLine2)) {
      return null;
    }
    let isContinuation = false;
    if (state.sCount[nextLine2] - state.blkIndent > 3) {
      isContinuation = true;
    }
    if (state.sCount[nextLine2] < 0) {
      isContinuation = true;
    }
    if (!isContinuation) {
      const terminatorRules = state.md.block.ruler.getRules("reference");
      const oldParentType = state.parentType;
      state.parentType = "reference";
      let terminate = false;
      for (let i = 0, l2 = terminatorRules.length; i < l2; i++) {
        if (terminatorRules[i](state, nextLine2, endLine, true)) {
          terminate = true;
          break;
        }
      }
      state.parentType = oldParentType;
      if (terminate) {
        return null;
      }
    }
    const pos3 = state.bMarks[nextLine2] + state.tShift[nextLine2];
    const max3 = state.eMarks[nextLine2];
    return state.src.slice(pos3, max3 + 1);
  }
  let str = state.src.slice(pos2, max2 + 1);
  max2 = str.length;
  let labelEnd = -1;
  for (pos2 = 1; pos2 < max2; pos2++) {
    const ch3 = str.charCodeAt(pos2);
    if (ch3 === 91) {
      return false;
    } else if (ch3 === 93) {
      labelEnd = pos2;
      break;
    } else if (ch3 === 10) {
      const lineContent = getNextLine(nextLine);
      if (lineContent !== null) {
        str += lineContent;
        max2 = str.length;
        nextLine++;
      }
    } else if (ch3 === 92) {
      pos2++;
      if (pos2 < max2 && str.charCodeAt(pos2) === 10) {
        const lineContent = getNextLine(nextLine);
        if (lineContent !== null) {
          str += lineContent;
          max2 = str.length;
          nextLine++;
        }
      }
    }
  }
  if (labelEnd < 0 || str.charCodeAt(labelEnd + 1) !== 58) {
    return false;
  }
  for (pos2 = labelEnd + 2; pos2 < max2; pos2++) {
    const ch3 = str.charCodeAt(pos2);
    if (ch3 === 10) {
      const lineContent = getNextLine(nextLine);
      if (lineContent !== null) {
        str += lineContent;
        max2 = str.length;
        nextLine++;
      }
    } else if (isSpace(ch3)) ;
    else {
      break;
    }
  }
  const destRes = state.md.helpers.parseLinkDestination(str, pos2, max2);
  if (!destRes.ok) {
    return false;
  }
  const href = state.md.normalizeLink(destRes.str);
  if (!state.md.validateLink(href)) {
    return false;
  }
  pos2 = destRes.pos;
  const destEndPos = pos2;
  const destEndLineNo = nextLine;
  const start2 = pos2;
  for (; pos2 < max2; pos2++) {
    const ch3 = str.charCodeAt(pos2);
    if (ch3 === 10) {
      const lineContent = getNextLine(nextLine);
      if (lineContent !== null) {
        str += lineContent;
        max2 = str.length;
        nextLine++;
      }
    } else if (isSpace(ch3)) ;
    else {
      break;
    }
  }
  let titleRes = state.md.helpers.parseLinkTitle(str, pos2, max2);
  while (titleRes.can_continue) {
    const lineContent = getNextLine(nextLine);
    if (lineContent === null) break;
    str += lineContent;
    pos2 = max2;
    max2 = str.length;
    nextLine++;
    titleRes = state.md.helpers.parseLinkTitle(str, pos2, max2, titleRes);
  }
  let title;
  if (pos2 < max2 && start2 !== pos2 && titleRes.ok) {
    title = titleRes.str;
    pos2 = titleRes.pos;
  } else {
    title = "";
    pos2 = destEndPos;
    nextLine = destEndLineNo;
  }
  while (pos2 < max2) {
    const ch3 = str.charCodeAt(pos2);
    if (!isSpace(ch3)) {
      break;
    }
    pos2++;
  }
  if (pos2 < max2 && str.charCodeAt(pos2) !== 10) {
    if (title) {
      title = "";
      pos2 = destEndPos;
      nextLine = destEndLineNo;
      while (pos2 < max2) {
        const ch3 = str.charCodeAt(pos2);
        if (!isSpace(ch3)) {
          break;
        }
        pos2++;
      }
    }
  }
  if (pos2 < max2 && str.charCodeAt(pos2) !== 10) {
    return false;
  }
  const label = normalizeReference(str.slice(1, labelEnd));
  if (!label) {
    return false;
  }
  if (silent) {
    return true;
  }
  if (typeof state.env.references === "undefined") {
    state.env.references = {};
  }
  if (typeof state.env.references[label] === "undefined") {
    state.env.references[label] = { title, href };
  }
  state.line = nextLine;
  return true;
}
const block_names = [
  "address",
  "article",
  "aside",
  "base",
  "basefont",
  "blockquote",
  "body",
  "caption",
  "center",
  "col",
  "colgroup",
  "dd",
  "details",
  "dialog",
  "dir",
  "div",
  "dl",
  "dt",
  "fieldset",
  "figcaption",
  "figure",
  "footer",
  "form",
  "frame",
  "frameset",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "head",
  "header",
  "hr",
  "html",
  "iframe",
  "legend",
  "li",
  "link",
  "main",
  "menu",
  "menuitem",
  "nav",
  "noframes",
  "ol",
  "optgroup",
  "option",
  "p",
  "param",
  "search",
  "section",
  "summary",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "title",
  "tr",
  "track",
  "ul"
];
const attr_name = "[a-zA-Z_:][a-zA-Z0-9:._-]*";
const unquoted = "[^\"'=<>`\\x00-\\x20]+";
const single_quoted = "'[^']*'";
const double_quoted = '"[^"]*"';
const attr_value = "(?:" + unquoted + "|" + single_quoted + "|" + double_quoted + ")";
const attribute = "(?:\\s+" + attr_name + "(?:\\s*=\\s*" + attr_value + ")?)";
const open_tag = "<[A-Za-z][A-Za-z0-9\\-]*" + attribute + "*\\s*\\/?>";
const close_tag = "<\\/[A-Za-z][A-Za-z0-9\\-]*\\s*>";
const comment = "<!---?>|<!--(?:[^-]|-[^-]|--[^>])*-->";
const processing = "<[?][\\s\\S]*?[?]>";
const declaration = "<![A-Za-z][^>]*>";
const cdata = "<!\\[CDATA\\[[\\s\\S]*?\\]\\]>";
const HTML_TAG_RE = new RegExp("^(?:" + open_tag + "|" + close_tag + "|" + comment + "|" + processing + "|" + declaration + "|" + cdata + ")");
const HTML_OPEN_CLOSE_TAG_RE = new RegExp("^(?:" + open_tag + "|" + close_tag + ")");
const HTML_SEQUENCES = [
  [/^<(script|pre|style|textarea)(?=(\s|>|$))/i, /<\/(script|pre|style|textarea)>/i, true],
  [/^<!--/, /-->/, true],
  [/^<\?/, /\?>/, true],
  [/^<![A-Z]/, />/, true],
  [/^<!\[CDATA\[/, /\]\]>/, true],
  [new RegExp("^</?(" + block_names.join("|") + ")(?=(\\s|/?>|$))", "i"), /^$/, true],
  [new RegExp(HTML_OPEN_CLOSE_TAG_RE.source + "\\s*$"), /^$/, false]
];
function html_block(state, startLine, endLine, silent) {
  let pos2 = state.bMarks[startLine] + state.tShift[startLine];
  let max2 = state.eMarks[startLine];
  if (state.sCount[startLine] - state.blkIndent >= 4) {
    return false;
  }
  if (!state.md.options.html) {
    return false;
  }
  if (state.src.charCodeAt(pos2) !== 60) {
    return false;
  }
  let lineText = state.src.slice(pos2, max2);
  let i = 0;
  for (; i < HTML_SEQUENCES.length; i++) {
    if (HTML_SEQUENCES[i][0].test(lineText)) {
      break;
    }
  }
  if (i === HTML_SEQUENCES.length) {
    return false;
  }
  if (silent) {
    return HTML_SEQUENCES[i][2];
  }
  let nextLine = startLine + 1;
  if (!HTML_SEQUENCES[i][1].test(lineText)) {
    for (; nextLine < endLine; nextLine++) {
      if (state.sCount[nextLine] < state.blkIndent) {
        break;
      }
      pos2 = state.bMarks[nextLine] + state.tShift[nextLine];
      max2 = state.eMarks[nextLine];
      lineText = state.src.slice(pos2, max2);
      if (HTML_SEQUENCES[i][1].test(lineText)) {
        if (lineText.length !== 0) {
          nextLine++;
        }
        break;
      }
    }
  }
  state.line = nextLine;
  const token2 = state.push("html_block", "", 0);
  token2.map = [startLine, nextLine];
  token2.content = state.getLines(startLine, nextLine, state.blkIndent, true);
  return true;
}
function heading(state, startLine, endLine, silent) {
  let pos2 = state.bMarks[startLine] + state.tShift[startLine];
  let max2 = state.eMarks[startLine];
  if (state.sCount[startLine] - state.blkIndent >= 4) {
    return false;
  }
  let ch3 = state.src.charCodeAt(pos2);
  if (ch3 !== 35 || pos2 >= max2) {
    return false;
  }
  let level = 1;
  ch3 = state.src.charCodeAt(++pos2);
  while (ch3 === 35 && pos2 < max2 && level <= 6) {
    level++;
    ch3 = state.src.charCodeAt(++pos2);
  }
  if (level > 6 || pos2 < max2 && !isSpace(ch3)) {
    return false;
  }
  if (silent) {
    return true;
  }
  max2 = state.skipSpacesBack(max2, pos2);
  const tmp = state.skipCharsBack(max2, 35, pos2);
  if (tmp > pos2 && isSpace(state.src.charCodeAt(tmp - 1))) {
    max2 = tmp;
  }
  state.line = startLine + 1;
  const token_o = state.push("heading_open", "h" + String(level), 1);
  token_o.markup = "########".slice(0, level);
  token_o.map = [startLine, state.line];
  const token_i = state.push("inline", "", 0);
  token_i.content = state.src.slice(pos2, max2).trim();
  token_i.map = [startLine, state.line];
  token_i.children = [];
  const token_c = state.push("heading_close", "h" + String(level), -1);
  token_c.markup = "########".slice(0, level);
  return true;
}
function lheading(state, startLine, endLine) {
  const terminatorRules = state.md.block.ruler.getRules("paragraph");
  if (state.sCount[startLine] - state.blkIndent >= 4) {
    return false;
  }
  const oldParentType = state.parentType;
  state.parentType = "paragraph";
  let level = 0;
  let marker;
  let nextLine = startLine + 1;
  for (; nextLine < endLine && !state.isEmpty(nextLine); nextLine++) {
    if (state.sCount[nextLine] - state.blkIndent > 3) {
      continue;
    }
    if (state.sCount[nextLine] >= state.blkIndent) {
      let pos2 = state.bMarks[nextLine] + state.tShift[nextLine];
      const max2 = state.eMarks[nextLine];
      if (pos2 < max2) {
        marker = state.src.charCodeAt(pos2);
        if (marker === 45 || marker === 61) {
          pos2 = state.skipChars(pos2, marker);
          pos2 = state.skipSpaces(pos2);
          if (pos2 >= max2) {
            level = marker === 61 ? 1 : 2;
            break;
          }
        }
      }
    }
    if (state.sCount[nextLine] < 0) {
      continue;
    }
    let terminate = false;
    for (let i = 0, l2 = terminatorRules.length; i < l2; i++) {
      if (terminatorRules[i](state, nextLine, endLine, true)) {
        terminate = true;
        break;
      }
    }
    if (terminate) {
      break;
    }
  }
  if (!level) {
    return false;
  }
  const content = state.getLines(startLine, nextLine, state.blkIndent, false).trim();
  state.line = nextLine + 1;
  const token_o = state.push("heading_open", "h" + String(level), 1);
  token_o.markup = String.fromCharCode(marker);
  token_o.map = [startLine, state.line];
  const token_i = state.push("inline", "", 0);
  token_i.content = content;
  token_i.map = [startLine, state.line - 1];
  token_i.children = [];
  const token_c = state.push("heading_close", "h" + String(level), -1);
  token_c.markup = String.fromCharCode(marker);
  state.parentType = oldParentType;
  return true;
}
function paragraph(state, startLine, endLine) {
  const terminatorRules = state.md.block.ruler.getRules("paragraph");
  const oldParentType = state.parentType;
  let nextLine = startLine + 1;
  state.parentType = "paragraph";
  for (; nextLine < endLine && !state.isEmpty(nextLine); nextLine++) {
    if (state.sCount[nextLine] - state.blkIndent > 3) {
      continue;
    }
    if (state.sCount[nextLine] < 0) {
      continue;
    }
    let terminate = false;
    for (let i = 0, l2 = terminatorRules.length; i < l2; i++) {
      if (terminatorRules[i](state, nextLine, endLine, true)) {
        terminate = true;
        break;
      }
    }
    if (terminate) {
      break;
    }
  }
  const content = state.getLines(startLine, nextLine, state.blkIndent, false).trim();
  state.line = nextLine;
  const token_o = state.push("paragraph_open", "p", 1);
  token_o.map = [startLine, state.line];
  const token_i = state.push("inline", "", 0);
  token_i.content = content;
  token_i.map = [startLine, state.line];
  token_i.children = [];
  state.push("paragraph_close", "p", -1);
  state.parentType = oldParentType;
  return true;
}
const _rules$1 = [
  // First 2 params - rule name & source. Secondary array - list of rules,
  // which can be terminated by this one.
  ["table", table, ["paragraph", "reference"]],
  ["code", code],
  ["fence", fence, ["paragraph", "reference", "blockquote", "list"]],
  ["blockquote", blockquote, ["paragraph", "reference", "blockquote", "list"]],
  ["hr", hr, ["paragraph", "reference", "blockquote", "list"]],
  ["list", list, ["paragraph", "reference", "blockquote"]],
  ["reference", reference],
  ["html_block", html_block, ["paragraph", "reference", "blockquote"]],
  ["heading", heading, ["paragraph", "reference", "blockquote"]],
  ["lheading", lheading],
  ["paragraph", paragraph]
];
function ParserBlock() {
  this.ruler = new Ruler();
  for (let i = 0; i < _rules$1.length; i++) {
    this.ruler.push(_rules$1[i][0], _rules$1[i][1], { alt: (_rules$1[i][2] || []).slice() });
  }
}
ParserBlock.prototype.tokenize = function(state, startLine, endLine) {
  const rules = this.ruler.getRules("");
  const len = rules.length;
  const maxNesting = state.md.options.maxNesting;
  let line2 = startLine;
  let hasEmptyLines = false;
  while (line2 < endLine) {
    state.line = line2 = state.skipEmptyLines(line2);
    if (line2 >= endLine) {
      break;
    }
    if (state.sCount[line2] < state.blkIndent) {
      break;
    }
    if (state.level >= maxNesting) {
      state.line = endLine;
      break;
    }
    const prevLine = state.line;
    let ok = false;
    for (let i = 0; i < len; i++) {
      ok = rules[i](state, line2, endLine, false);
      if (ok) {
        if (prevLine >= state.line) {
          throw new Error("block rule didn't increment state.line");
        }
        break;
      }
    }
    if (!ok) throw new Error("none of the block rules matched");
    state.tight = !hasEmptyLines;
    if (state.isEmpty(state.line - 1)) {
      hasEmptyLines = true;
    }
    line2 = state.line;
    if (line2 < endLine && state.isEmpty(line2)) {
      hasEmptyLines = true;
      line2++;
      state.line = line2;
    }
  }
};
ParserBlock.prototype.parse = function(src, md, env, outTokens) {
  if (!src) {
    return;
  }
  const state = new this.State(src, md, env, outTokens);
  this.tokenize(state, state.line, state.lineMax);
};
ParserBlock.prototype.State = StateBlock;
function StateInline(src, md, env, outTokens) {
  this.src = src;
  this.env = env;
  this.md = md;
  this.tokens = outTokens;
  this.tokens_meta = Array(outTokens.length);
  this.pos = 0;
  this.posMax = this.src.length;
  this.level = 0;
  this.pending = "";
  this.pendingLevel = 0;
  this.cache = {};
  this.delimiters = [];
  this._prev_delimiters = [];
  this.backticks = {};
  this.backticksScanned = false;
  this.linkLevel = 0;
}
StateInline.prototype.pushPending = function() {
  const token2 = new Token("text", "", 0);
  token2.content = this.pending;
  token2.level = this.pendingLevel;
  this.tokens.push(token2);
  this.pending = "";
  return token2;
};
StateInline.prototype.push = function(type, tag, nesting) {
  if (this.pending) {
    this.pushPending();
  }
  const token2 = new Token(type, tag, nesting);
  let token_meta = null;
  if (nesting < 0) {
    this.level--;
    this.delimiters = this._prev_delimiters.pop();
  }
  token2.level = this.level;
  if (nesting > 0) {
    this.level++;
    this._prev_delimiters.push(this.delimiters);
    this.delimiters = [];
    token_meta = { delimiters: this.delimiters };
  }
  this.pendingLevel = this.level;
  this.tokens.push(token2);
  this.tokens_meta.push(token_meta);
  return token2;
};
StateInline.prototype.scanDelims = function(start2, canSplitWord) {
  const max2 = this.posMax;
  const marker = this.src.charCodeAt(start2);
  const lastChar = start2 > 0 ? this.src.charCodeAt(start2 - 1) : 32;
  let pos2 = start2;
  while (pos2 < max2 && this.src.charCodeAt(pos2) === marker) {
    pos2++;
  }
  const count = pos2 - start2;
  const nextChar = pos2 < max2 ? this.src.charCodeAt(pos2) : 32;
  const isLastPunctChar = isMdAsciiPunct(lastChar) || isPunctChar(String.fromCharCode(lastChar));
  const isNextPunctChar = isMdAsciiPunct(nextChar) || isPunctChar(String.fromCharCode(nextChar));
  const isLastWhiteSpace = isWhiteSpace(lastChar);
  const isNextWhiteSpace = isWhiteSpace(nextChar);
  const left_flanking = !isNextWhiteSpace && (!isNextPunctChar || isLastWhiteSpace || isLastPunctChar);
  const right_flanking = !isLastWhiteSpace && (!isLastPunctChar || isNextWhiteSpace || isNextPunctChar);
  const can_open = left_flanking && (canSplitWord || !right_flanking || isLastPunctChar);
  const can_close = right_flanking && (canSplitWord || !left_flanking || isNextPunctChar);
  return { can_open, can_close, length: count };
};
StateInline.prototype.Token = Token;
function isTerminatorChar(ch3) {
  switch (ch3) {
    case 10:
    case 33:
    case 35:
    case 36:
    case 37:
    case 38:
    case 42:
    case 43:
    case 45:
    case 58:
    case 60:
    case 61:
    case 62:
    case 64:
    case 91:
    case 92:
    case 93:
    case 94:
    case 95:
    case 96:
    case 123:
    case 125:
    case 126:
      return true;
    default:
      return false;
  }
}
function text(state, silent) {
  let pos2 = state.pos;
  while (pos2 < state.posMax && !isTerminatorChar(state.src.charCodeAt(pos2))) {
    pos2++;
  }
  if (pos2 === state.pos) {
    return false;
  }
  if (!silent) {
    state.pending += state.src.slice(state.pos, pos2);
  }
  state.pos = pos2;
  return true;
}
const SCHEME_RE = /(?:^|[^a-z0-9.+-])([a-z][a-z0-9.+-]*)$/i;
function linkify(state, silent) {
  if (!state.md.options.linkify) return false;
  if (state.linkLevel > 0) return false;
  const pos2 = state.pos;
  const max2 = state.posMax;
  if (pos2 + 3 > max2) return false;
  if (state.src.charCodeAt(pos2) !== 58) return false;
  if (state.src.charCodeAt(pos2 + 1) !== 47) return false;
  if (state.src.charCodeAt(pos2 + 2) !== 47) return false;
  const match2 = state.pending.match(SCHEME_RE);
  if (!match2) return false;
  const proto = match2[1];
  const link2 = state.md.linkify.matchAtStart(state.src.slice(pos2 - proto.length));
  if (!link2) return false;
  let url = link2.url;
  if (url.length <= proto.length) return false;
  url = url.replace(/\*+$/, "");
  const fullUrl = state.md.normalizeLink(url);
  if (!state.md.validateLink(fullUrl)) return false;
  if (!silent) {
    state.pending = state.pending.slice(0, -proto.length);
    const token_o = state.push("link_open", "a", 1);
    token_o.attrs = [["href", fullUrl]];
    token_o.markup = "linkify";
    token_o.info = "auto";
    const token_t = state.push("text", "", 0);
    token_t.content = state.md.normalizeLinkText(url);
    const token_c = state.push("link_close", "a", -1);
    token_c.markup = "linkify";
    token_c.info = "auto";
  }
  state.pos += url.length - proto.length;
  return true;
}
function newline(state, silent) {
  let pos2 = state.pos;
  if (state.src.charCodeAt(pos2) !== 10) {
    return false;
  }
  const pmax = state.pending.length - 1;
  const max2 = state.posMax;
  if (!silent) {
    if (pmax >= 0 && state.pending.charCodeAt(pmax) === 32) {
      if (pmax >= 1 && state.pending.charCodeAt(pmax - 1) === 32) {
        let ws = pmax - 1;
        while (ws >= 1 && state.pending.charCodeAt(ws - 1) === 32) ws--;
        state.pending = state.pending.slice(0, ws);
        state.push("hardbreak", "br", 0);
      } else {
        state.pending = state.pending.slice(0, -1);
        state.push("softbreak", "br", 0);
      }
    } else {
      state.push("softbreak", "br", 0);
    }
  }
  pos2++;
  while (pos2 < max2 && isSpace(state.src.charCodeAt(pos2))) {
    pos2++;
  }
  state.pos = pos2;
  return true;
}
const ESCAPED = [];
for (let i = 0; i < 256; i++) {
  ESCAPED.push(0);
}
"\\!\"#$%&'()*+,./:;<=>?@[]^_`{|}~-".split("").forEach(function(ch3) {
  ESCAPED[ch3.charCodeAt(0)] = 1;
});
function escape$2(state, silent) {
  let pos2 = state.pos;
  const max2 = state.posMax;
  if (state.src.charCodeAt(pos2) !== 92) return false;
  pos2++;
  if (pos2 >= max2) return false;
  let ch1 = state.src.charCodeAt(pos2);
  if (ch1 === 10) {
    if (!silent) {
      state.push("hardbreak", "br", 0);
    }
    pos2++;
    while (pos2 < max2) {
      ch1 = state.src.charCodeAt(pos2);
      if (!isSpace(ch1)) break;
      pos2++;
    }
    state.pos = pos2;
    return true;
  }
  let escapedStr = state.src[pos2];
  if (ch1 >= 55296 && ch1 <= 56319 && pos2 + 1 < max2) {
    const ch22 = state.src.charCodeAt(pos2 + 1);
    if (ch22 >= 56320 && ch22 <= 57343) {
      escapedStr += state.src[pos2 + 1];
      pos2++;
    }
  }
  const origStr = "\\" + escapedStr;
  if (!silent) {
    const token2 = state.push("text_special", "", 0);
    if (ch1 < 256 && ESCAPED[ch1] !== 0) {
      token2.content = escapedStr;
    } else {
      token2.content = origStr;
    }
    token2.markup = origStr;
    token2.info = "escape";
  }
  state.pos = pos2 + 1;
  return true;
}
function backtick(state, silent) {
  let pos2 = state.pos;
  const ch3 = state.src.charCodeAt(pos2);
  if (ch3 !== 96) {
    return false;
  }
  const start2 = pos2;
  pos2++;
  const max2 = state.posMax;
  while (pos2 < max2 && state.src.charCodeAt(pos2) === 96) {
    pos2++;
  }
  const marker = state.src.slice(start2, pos2);
  const openerLength = marker.length;
  if (state.backticksScanned && (state.backticks[openerLength] || 0) <= start2) {
    if (!silent) state.pending += marker;
    state.pos += openerLength;
    return true;
  }
  let matchEnd = pos2;
  let matchStart;
  while ((matchStart = state.src.indexOf("`", matchEnd)) !== -1) {
    matchEnd = matchStart + 1;
    while (matchEnd < max2 && state.src.charCodeAt(matchEnd) === 96) {
      matchEnd++;
    }
    const closerLength = matchEnd - matchStart;
    if (closerLength === openerLength) {
      if (!silent) {
        const token2 = state.push("code_inline", "code", 0);
        token2.markup = marker;
        token2.content = state.src.slice(pos2, matchStart).replace(/\n/g, " ").replace(/^ (.+) $/, "$1");
      }
      state.pos = matchEnd;
      return true;
    }
    state.backticks[closerLength] = matchStart;
  }
  state.backticksScanned = true;
  if (!silent) state.pending += marker;
  state.pos += openerLength;
  return true;
}
function strikethrough_tokenize(state, silent) {
  const start2 = state.pos;
  const marker = state.src.charCodeAt(start2);
  if (silent) {
    return false;
  }
  if (marker !== 126) {
    return false;
  }
  const scanned = state.scanDelims(state.pos, true);
  let len = scanned.length;
  const ch3 = String.fromCharCode(marker);
  if (len < 2) {
    return false;
  }
  let token2;
  if (len % 2) {
    token2 = state.push("text", "", 0);
    token2.content = ch3;
    len--;
  }
  for (let i = 0; i < len; i += 2) {
    token2 = state.push("text", "", 0);
    token2.content = ch3 + ch3;
    state.delimiters.push({
      marker,
      length: 0,
      // disable "rule of 3" length checks meant for emphasis
      token: state.tokens.length - 1,
      end: -1,
      open: scanned.can_open,
      close: scanned.can_close
    });
  }
  state.pos += scanned.length;
  return true;
}
function postProcess$1(state, delimiters) {
  let token2;
  const loneMarkers = [];
  const max2 = delimiters.length;
  for (let i = 0; i < max2; i++) {
    const startDelim = delimiters[i];
    if (startDelim.marker !== 126) {
      continue;
    }
    if (startDelim.end === -1) {
      continue;
    }
    const endDelim = delimiters[startDelim.end];
    token2 = state.tokens[startDelim.token];
    token2.type = "s_open";
    token2.tag = "s";
    token2.nesting = 1;
    token2.markup = "~~";
    token2.content = "";
    token2 = state.tokens[endDelim.token];
    token2.type = "s_close";
    token2.tag = "s";
    token2.nesting = -1;
    token2.markup = "~~";
    token2.content = "";
    if (state.tokens[endDelim.token - 1].type === "text" && state.tokens[endDelim.token - 1].content === "~") {
      loneMarkers.push(endDelim.token - 1);
    }
  }
  while (loneMarkers.length) {
    const i = loneMarkers.pop();
    let j2 = i + 1;
    while (j2 < state.tokens.length && state.tokens[j2].type === "s_close") {
      j2++;
    }
    j2--;
    if (i !== j2) {
      token2 = state.tokens[j2];
      state.tokens[j2] = state.tokens[i];
      state.tokens[i] = token2;
    }
  }
}
function strikethrough_postProcess(state) {
  const tokens_meta = state.tokens_meta;
  const max2 = state.tokens_meta.length;
  postProcess$1(state, state.delimiters);
  for (let curr = 0; curr < max2; curr++) {
    if (tokens_meta[curr] && tokens_meta[curr].delimiters) {
      postProcess$1(state, tokens_meta[curr].delimiters);
    }
  }
}
const r_strikethrough = {
  tokenize: strikethrough_tokenize,
  postProcess: strikethrough_postProcess
};
function emphasis_tokenize(state, silent) {
  const start2 = state.pos;
  const marker = state.src.charCodeAt(start2);
  if (silent) {
    return false;
  }
  if (marker !== 95 && marker !== 42) {
    return false;
  }
  const scanned = state.scanDelims(state.pos, marker === 42);
  for (let i = 0; i < scanned.length; i++) {
    const token2 = state.push("text", "", 0);
    token2.content = String.fromCharCode(marker);
    state.delimiters.push({
      // Char code of the starting marker (number).
      //
      marker,
      // Total length of these series of delimiters.
      //
      length: scanned.length,
      // A position of the token this delimiter corresponds to.
      //
      token: state.tokens.length - 1,
      // If this delimiter is matched as a valid opener, `end` will be
      // equal to its position, otherwise it's `-1`.
      //
      end: -1,
      // Boolean flags that determine if this delimiter could open or close
      // an emphasis.
      //
      open: scanned.can_open,
      close: scanned.can_close
    });
  }
  state.pos += scanned.length;
  return true;
}
function postProcess(state, delimiters) {
  const max2 = delimiters.length;
  for (let i = max2 - 1; i >= 0; i--) {
    const startDelim = delimiters[i];
    if (startDelim.marker !== 95 && startDelim.marker !== 42) {
      continue;
    }
    if (startDelim.end === -1) {
      continue;
    }
    const endDelim = delimiters[startDelim.end];
    const isStrong = i > 0 && delimiters[i - 1].end === startDelim.end + 1 && // check that first two markers match and adjacent
    delimiters[i - 1].marker === startDelim.marker && delimiters[i - 1].token === startDelim.token - 1 && // check that last two markers are adjacent (we can safely assume they match)
    delimiters[startDelim.end + 1].token === endDelim.token + 1;
    const ch3 = String.fromCharCode(startDelim.marker);
    const token_o = state.tokens[startDelim.token];
    token_o.type = isStrong ? "strong_open" : "em_open";
    token_o.tag = isStrong ? "strong" : "em";
    token_o.nesting = 1;
    token_o.markup = isStrong ? ch3 + ch3 : ch3;
    token_o.content = "";
    const token_c = state.tokens[endDelim.token];
    token_c.type = isStrong ? "strong_close" : "em_close";
    token_c.tag = isStrong ? "strong" : "em";
    token_c.nesting = -1;
    token_c.markup = isStrong ? ch3 + ch3 : ch3;
    token_c.content = "";
    if (isStrong) {
      state.tokens[delimiters[i - 1].token].content = "";
      state.tokens[delimiters[startDelim.end + 1].token].content = "";
      i--;
    }
  }
}
function emphasis_post_process(state) {
  const tokens_meta = state.tokens_meta;
  const max2 = state.tokens_meta.length;
  postProcess(state, state.delimiters);
  for (let curr = 0; curr < max2; curr++) {
    if (tokens_meta[curr] && tokens_meta[curr].delimiters) {
      postProcess(state, tokens_meta[curr].delimiters);
    }
  }
}
const r_emphasis = {
  tokenize: emphasis_tokenize,
  postProcess: emphasis_post_process
};
function link(state, silent) {
  let code2, label, res, ref;
  let href = "";
  let title = "";
  let start2 = state.pos;
  let parseReference = true;
  if (state.src.charCodeAt(state.pos) !== 91) {
    return false;
  }
  const oldPos = state.pos;
  const max2 = state.posMax;
  const labelStart = state.pos + 1;
  const labelEnd = state.md.helpers.parseLinkLabel(state, state.pos, true);
  if (labelEnd < 0) {
    return false;
  }
  let pos2 = labelEnd + 1;
  if (pos2 < max2 && state.src.charCodeAt(pos2) === 40) {
    parseReference = false;
    pos2++;
    for (; pos2 < max2; pos2++) {
      code2 = state.src.charCodeAt(pos2);
      if (!isSpace(code2) && code2 !== 10) {
        break;
      }
    }
    if (pos2 >= max2) {
      return false;
    }
    start2 = pos2;
    res = state.md.helpers.parseLinkDestination(state.src, pos2, state.posMax);
    if (res.ok) {
      href = state.md.normalizeLink(res.str);
      if (state.md.validateLink(href)) {
        pos2 = res.pos;
      } else {
        href = "";
      }
      start2 = pos2;
      for (; pos2 < max2; pos2++) {
        code2 = state.src.charCodeAt(pos2);
        if (!isSpace(code2) && code2 !== 10) {
          break;
        }
      }
      res = state.md.helpers.parseLinkTitle(state.src, pos2, state.posMax);
      if (pos2 < max2 && start2 !== pos2 && res.ok) {
        title = res.str;
        pos2 = res.pos;
        for (; pos2 < max2; pos2++) {
          code2 = state.src.charCodeAt(pos2);
          if (!isSpace(code2) && code2 !== 10) {
            break;
          }
        }
      }
    }
    if (pos2 >= max2 || state.src.charCodeAt(pos2) !== 41) {
      parseReference = true;
    }
    pos2++;
  }
  if (parseReference) {
    if (typeof state.env.references === "undefined") {
      return false;
    }
    if (pos2 < max2 && state.src.charCodeAt(pos2) === 91) {
      start2 = pos2 + 1;
      pos2 = state.md.helpers.parseLinkLabel(state, pos2);
      if (pos2 >= 0) {
        label = state.src.slice(start2, pos2++);
      } else {
        pos2 = labelEnd + 1;
      }
    } else {
      pos2 = labelEnd + 1;
    }
    if (!label) {
      label = state.src.slice(labelStart, labelEnd);
    }
    ref = state.env.references[normalizeReference(label)];
    if (!ref) {
      state.pos = oldPos;
      return false;
    }
    href = ref.href;
    title = ref.title;
  }
  if (!silent) {
    state.pos = labelStart;
    state.posMax = labelEnd;
    const token_o = state.push("link_open", "a", 1);
    const attrs = [["href", href]];
    token_o.attrs = attrs;
    if (title) {
      attrs.push(["title", title]);
    }
    state.linkLevel++;
    state.md.inline.tokenize(state);
    state.linkLevel--;
    state.push("link_close", "a", -1);
  }
  state.pos = pos2;
  state.posMax = max2;
  return true;
}
function image(state, silent) {
  let code2, content, label, pos2, ref, res, title, start2;
  let href = "";
  const oldPos = state.pos;
  const max2 = state.posMax;
  if (state.src.charCodeAt(state.pos) !== 33) {
    return false;
  }
  if (state.src.charCodeAt(state.pos + 1) !== 91) {
    return false;
  }
  const labelStart = state.pos + 2;
  const labelEnd = state.md.helpers.parseLinkLabel(state, state.pos + 1, false);
  if (labelEnd < 0) {
    return false;
  }
  pos2 = labelEnd + 1;
  if (pos2 < max2 && state.src.charCodeAt(pos2) === 40) {
    pos2++;
    for (; pos2 < max2; pos2++) {
      code2 = state.src.charCodeAt(pos2);
      if (!isSpace(code2) && code2 !== 10) {
        break;
      }
    }
    if (pos2 >= max2) {
      return false;
    }
    start2 = pos2;
    res = state.md.helpers.parseLinkDestination(state.src, pos2, state.posMax);
    if (res.ok) {
      href = state.md.normalizeLink(res.str);
      if (state.md.validateLink(href)) {
        pos2 = res.pos;
      } else {
        href = "";
      }
    }
    start2 = pos2;
    for (; pos2 < max2; pos2++) {
      code2 = state.src.charCodeAt(pos2);
      if (!isSpace(code2) && code2 !== 10) {
        break;
      }
    }
    res = state.md.helpers.parseLinkTitle(state.src, pos2, state.posMax);
    if (pos2 < max2 && start2 !== pos2 && res.ok) {
      title = res.str;
      pos2 = res.pos;
      for (; pos2 < max2; pos2++) {
        code2 = state.src.charCodeAt(pos2);
        if (!isSpace(code2) && code2 !== 10) {
          break;
        }
      }
    } else {
      title = "";
    }
    if (pos2 >= max2 || state.src.charCodeAt(pos2) !== 41) {
      state.pos = oldPos;
      return false;
    }
    pos2++;
  } else {
    if (typeof state.env.references === "undefined") {
      return false;
    }
    if (pos2 < max2 && state.src.charCodeAt(pos2) === 91) {
      start2 = pos2 + 1;
      pos2 = state.md.helpers.parseLinkLabel(state, pos2);
      if (pos2 >= 0) {
        label = state.src.slice(start2, pos2++);
      } else {
        pos2 = labelEnd + 1;
      }
    } else {
      pos2 = labelEnd + 1;
    }
    if (!label) {
      label = state.src.slice(labelStart, labelEnd);
    }
    ref = state.env.references[normalizeReference(label)];
    if (!ref) {
      state.pos = oldPos;
      return false;
    }
    href = ref.href;
    title = ref.title;
  }
  if (!silent) {
    content = state.src.slice(labelStart, labelEnd);
    const tokens = [];
    state.md.inline.parse(
      content,
      state.md,
      state.env,
      tokens
    );
    const token2 = state.push("image", "img", 0);
    const attrs = [["src", href], ["alt", ""]];
    token2.attrs = attrs;
    token2.children = tokens;
    token2.content = content;
    if (title) {
      attrs.push(["title", title]);
    }
  }
  state.pos = pos2;
  state.posMax = max2;
  return true;
}
const EMAIL_RE = /^([a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*)$/;
const AUTOLINK_RE = /^([a-zA-Z][a-zA-Z0-9+.-]{1,31}):([^<>\x00-\x20]*)$/;
function autolink(state, silent) {
  let pos2 = state.pos;
  if (state.src.charCodeAt(pos2) !== 60) {
    return false;
  }
  const start2 = state.pos;
  const max2 = state.posMax;
  for (; ; ) {
    if (++pos2 >= max2) return false;
    const ch3 = state.src.charCodeAt(pos2);
    if (ch3 === 60) return false;
    if (ch3 === 62) break;
  }
  const url = state.src.slice(start2 + 1, pos2);
  if (AUTOLINK_RE.test(url)) {
    const fullUrl = state.md.normalizeLink(url);
    if (!state.md.validateLink(fullUrl)) {
      return false;
    }
    if (!silent) {
      const token_o = state.push("link_open", "a", 1);
      token_o.attrs = [["href", fullUrl]];
      token_o.markup = "autolink";
      token_o.info = "auto";
      const token_t = state.push("text", "", 0);
      token_t.content = state.md.normalizeLinkText(url);
      const token_c = state.push("link_close", "a", -1);
      token_c.markup = "autolink";
      token_c.info = "auto";
    }
    state.pos += url.length + 2;
    return true;
  }
  if (EMAIL_RE.test(url)) {
    const fullUrl = state.md.normalizeLink("mailto:" + url);
    if (!state.md.validateLink(fullUrl)) {
      return false;
    }
    if (!silent) {
      const token_o = state.push("link_open", "a", 1);
      token_o.attrs = [["href", fullUrl]];
      token_o.markup = "autolink";
      token_o.info = "auto";
      const token_t = state.push("text", "", 0);
      token_t.content = state.md.normalizeLinkText(url);
      const token_c = state.push("link_close", "a", -1);
      token_c.markup = "autolink";
      token_c.info = "auto";
    }
    state.pos += url.length + 2;
    return true;
  }
  return false;
}
function isLinkOpen(str) {
  return /^<a[>\s]/i.test(str);
}
function isLinkClose(str) {
  return /^<\/a\s*>/i.test(str);
}
function isLetter(ch3) {
  const lc = ch3 | 32;
  return lc >= 97 && lc <= 122;
}
function html_inline(state, silent) {
  if (!state.md.options.html) {
    return false;
  }
  const max2 = state.posMax;
  const pos2 = state.pos;
  if (state.src.charCodeAt(pos2) !== 60 || pos2 + 2 >= max2) {
    return false;
  }
  const ch3 = state.src.charCodeAt(pos2 + 1);
  if (ch3 !== 33 && ch3 !== 63 && ch3 !== 47 && !isLetter(ch3)) {
    return false;
  }
  const match2 = state.src.slice(pos2).match(HTML_TAG_RE);
  if (!match2) {
    return false;
  }
  if (!silent) {
    const token2 = state.push("html_inline", "", 0);
    token2.content = match2[0];
    if (isLinkOpen(token2.content)) state.linkLevel++;
    if (isLinkClose(token2.content)) state.linkLevel--;
  }
  state.pos += match2[0].length;
  return true;
}
const DIGITAL_RE = /^&#((?:x[a-f0-9]{1,6}|[0-9]{1,7}));/i;
const NAMED_RE = /^&([a-z][a-z0-9]{1,31});/i;
function entity(state, silent) {
  const pos2 = state.pos;
  const max2 = state.posMax;
  if (state.src.charCodeAt(pos2) !== 38) return false;
  if (pos2 + 1 >= max2) return false;
  const ch3 = state.src.charCodeAt(pos2 + 1);
  if (ch3 === 35) {
    const match2 = state.src.slice(pos2).match(DIGITAL_RE);
    if (match2) {
      if (!silent) {
        const code2 = match2[1][0].toLowerCase() === "x" ? parseInt(match2[1].slice(1), 16) : parseInt(match2[1], 10);
        const token2 = state.push("text_special", "", 0);
        token2.content = isValidEntityCode(code2) ? fromCodePoint(code2) : fromCodePoint(65533);
        token2.markup = match2[0];
        token2.info = "entity";
      }
      state.pos += match2[0].length;
      return true;
    }
  } else {
    const match2 = state.src.slice(pos2).match(NAMED_RE);
    if (match2) {
      const decoded = decodeHTML(match2[0]);
      if (decoded !== match2[0]) {
        if (!silent) {
          const token2 = state.push("text_special", "", 0);
          token2.content = decoded;
          token2.markup = match2[0];
          token2.info = "entity";
        }
        state.pos += match2[0].length;
        return true;
      }
    }
  }
  return false;
}
function processDelimiters(delimiters) {
  const openersBottom = {};
  const max2 = delimiters.length;
  if (!max2) return;
  let headerIdx = 0;
  let lastTokenIdx = -2;
  const jumps = [];
  for (let closerIdx = 0; closerIdx < max2; closerIdx++) {
    const closer = delimiters[closerIdx];
    jumps.push(0);
    if (delimiters[headerIdx].marker !== closer.marker || lastTokenIdx !== closer.token - 1) {
      headerIdx = closerIdx;
    }
    lastTokenIdx = closer.token;
    closer.length = closer.length || 0;
    if (!closer.close) continue;
    if (!openersBottom.hasOwnProperty(closer.marker)) {
      openersBottom[closer.marker] = [-1, -1, -1, -1, -1, -1];
    }
    const minOpenerIdx = openersBottom[closer.marker][(closer.open ? 3 : 0) + closer.length % 3];
    let openerIdx = headerIdx - jumps[headerIdx] - 1;
    let newMinOpenerIdx = openerIdx;
    for (; openerIdx > minOpenerIdx; openerIdx -= jumps[openerIdx] + 1) {
      const opener = delimiters[openerIdx];
      if (opener.marker !== closer.marker) continue;
      if (opener.open && opener.end < 0) {
        let isOddMatch = false;
        if (opener.close || closer.open) {
          if ((opener.length + closer.length) % 3 === 0) {
            if (opener.length % 3 !== 0 || closer.length % 3 !== 0) {
              isOddMatch = true;
            }
          }
        }
        if (!isOddMatch) {
          const lastJump = openerIdx > 0 && !delimiters[openerIdx - 1].open ? jumps[openerIdx - 1] + 1 : 0;
          jumps[closerIdx] = closerIdx - openerIdx + lastJump;
          jumps[openerIdx] = lastJump;
          closer.open = false;
          opener.end = closerIdx;
          opener.close = false;
          newMinOpenerIdx = -1;
          lastTokenIdx = -2;
          break;
        }
      }
    }
    if (newMinOpenerIdx !== -1) {
      openersBottom[closer.marker][(closer.open ? 3 : 0) + (closer.length || 0) % 3] = newMinOpenerIdx;
    }
  }
}
function link_pairs(state) {
  const tokens_meta = state.tokens_meta;
  const max2 = state.tokens_meta.length;
  processDelimiters(state.delimiters);
  for (let curr = 0; curr < max2; curr++) {
    if (tokens_meta[curr] && tokens_meta[curr].delimiters) {
      processDelimiters(tokens_meta[curr].delimiters);
    }
  }
}
function fragments_join(state) {
  let curr, last;
  let level = 0;
  const tokens = state.tokens;
  const max2 = state.tokens.length;
  for (curr = last = 0; curr < max2; curr++) {
    if (tokens[curr].nesting < 0) level--;
    tokens[curr].level = level;
    if (tokens[curr].nesting > 0) level++;
    if (tokens[curr].type === "text" && curr + 1 < max2 && tokens[curr + 1].type === "text") {
      tokens[curr + 1].content = tokens[curr].content + tokens[curr + 1].content;
    } else {
      if (curr !== last) {
        tokens[last] = tokens[curr];
      }
      last++;
    }
  }
  if (curr !== last) {
    tokens.length = last;
  }
}
const _rules = [
  ["text", text],
  ["linkify", linkify],
  ["newline", newline],
  ["escape", escape$2],
  ["backticks", backtick],
  ["strikethrough", r_strikethrough.tokenize],
  ["emphasis", r_emphasis.tokenize],
  ["link", link],
  ["image", image],
  ["autolink", autolink],
  ["html_inline", html_inline],
  ["entity", entity]
];
const _rules2 = [
  ["balance_pairs", link_pairs],
  ["strikethrough", r_strikethrough.postProcess],
  ["emphasis", r_emphasis.postProcess],
  // rules for pairs separate '**' into its own text tokens, which may be left unused,
  // rule below merges unused segments back with the rest of the text
  ["fragments_join", fragments_join]
];
function ParserInline() {
  this.ruler = new Ruler();
  for (let i = 0; i < _rules.length; i++) {
    this.ruler.push(_rules[i][0], _rules[i][1]);
  }
  this.ruler2 = new Ruler();
  for (let i = 0; i < _rules2.length; i++) {
    this.ruler2.push(_rules2[i][0], _rules2[i][1]);
  }
}
ParserInline.prototype.skipToken = function(state) {
  const pos2 = state.pos;
  const rules = this.ruler.getRules("");
  const len = rules.length;
  const maxNesting = state.md.options.maxNesting;
  const cache = state.cache;
  if (typeof cache[pos2] !== "undefined") {
    state.pos = cache[pos2];
    return;
  }
  let ok = false;
  if (state.level < maxNesting) {
    for (let i = 0; i < len; i++) {
      state.level++;
      ok = rules[i](state, true);
      state.level--;
      if (ok) {
        if (pos2 >= state.pos) {
          throw new Error("inline rule didn't increment state.pos");
        }
        break;
      }
    }
  } else {
    state.pos = state.posMax;
  }
  if (!ok) {
    state.pos++;
  }
  cache[pos2] = state.pos;
};
ParserInline.prototype.tokenize = function(state) {
  const rules = this.ruler.getRules("");
  const len = rules.length;
  const end2 = state.posMax;
  const maxNesting = state.md.options.maxNesting;
  while (state.pos < end2) {
    const prevPos = state.pos;
    let ok = false;
    if (state.level < maxNesting) {
      for (let i = 0; i < len; i++) {
        ok = rules[i](state, false);
        if (ok) {
          if (prevPos >= state.pos) {
            throw new Error("inline rule didn't increment state.pos");
          }
          break;
        }
      }
    }
    if (ok) {
      if (state.pos >= end2) {
        break;
      }
      continue;
    }
    state.pending += state.src[state.pos++];
  }
  if (state.pending) {
    state.pushPending();
  }
};
ParserInline.prototype.parse = function(str, md, env, outTokens) {
  const state = new this.State(str, md, env, outTokens);
  this.tokenize(state);
  const rules = this.ruler2.getRules("");
  const len = rules.length;
  for (let i = 0; i < len; i++) {
    rules[i](state);
  }
};
ParserInline.prototype.State = StateInline;
function reFactory(opts) {
  const re = {};
  opts = opts || {};
  re.src_Any = Any.source;
  re.src_Cc = Cc.source;
  re.src_Z = Z.source;
  re.src_P = P.source;
  re.src_ZPCc = [re.src_Z, re.src_P, re.src_Cc].join("|");
  re.src_ZCc = [re.src_Z, re.src_Cc].join("|");
  const text_separators = "[><｜]";
  re.src_pseudo_letter = "(?:(?!" + text_separators + "|" + re.src_ZPCc + ")" + re.src_Any + ")";
  re.src_ip4 = "(?:(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)";
  re.src_auth = "(?:(?:(?!" + re.src_ZCc + "|[@/\\[\\]()]).)+@)?";
  re.src_port = "(?::(?:6(?:[0-4]\\d{3}|5(?:[0-4]\\d{2}|5(?:[0-2]\\d|3[0-5])))|[1-5]?\\d{1,4}))?";
  re.src_host_terminator = "(?=$|" + text_separators + "|" + re.src_ZPCc + ")(?!" + (opts["---"] ? "-(?!--)|" : "-|") + "_|:\\d|\\.-|\\.(?!$|" + re.src_ZPCc + "))";
  re.src_path = "(?:[/?#](?:(?!" + re.src_ZCc + "|" + text_separators + `|[()[\\]{}.,"'?!\\-;]).|\\[(?:(?!` + re.src_ZCc + "|\\]).)*\\]|\\((?:(?!" + re.src_ZCc + "|[)]).)*\\)|\\{(?:(?!" + re.src_ZCc + '|[}]).)*\\}|\\"(?:(?!' + re.src_ZCc + `|["]).)+\\"|\\'(?:(?!` + re.src_ZCc + "|[']).)+\\'|\\'(?=" + re.src_pseudo_letter + "|[-])|\\.{2,}[a-zA-Z0-9%/&]|\\.(?!" + re.src_ZCc + "|[.]|$)|" + (opts["---"] ? "\\-(?!--(?:[^-]|$))(?:-*)|" : "\\-+|") + // allow `,,,` in paths
  ",(?!" + re.src_ZCc + "|$)|;(?!" + re.src_ZCc + "|$)|\\!+(?!" + re.src_ZCc + "|[!]|$)|\\?(?!" + re.src_ZCc + "|[?]|$))+|\\/)?";
  re.src_email_name = '[\\-;:&=\\+\\$,\\.a-zA-Z0-9_][\\-;:&=\\+\\$,\\"\\.a-zA-Z0-9_]*';
  re.src_xn = "xn--[a-z0-9\\-]{1,59}";
  re.src_domain_root = // Allow letters & digits (http://test1)
  "(?:" + re.src_xn + "|" + re.src_pseudo_letter + "{1,63})";
  re.src_domain = "(?:" + re.src_xn + "|(?:" + re.src_pseudo_letter + ")|(?:" + re.src_pseudo_letter + "(?:-|" + re.src_pseudo_letter + "){0,61}" + re.src_pseudo_letter + "))";
  re.src_host = "(?:(?:(?:(?:" + re.src_domain + ")\\.)*" + re.src_domain + "))";
  re.tpl_host_fuzzy = "(?:" + re.src_ip4 + "|(?:(?:(?:" + re.src_domain + ")\\.)+(?:%TLDS%)))";
  re.tpl_host_no_ip_fuzzy = "(?:(?:(?:" + re.src_domain + ")\\.)+(?:%TLDS%))";
  re.src_host_strict = re.src_host + re.src_host_terminator;
  re.tpl_host_fuzzy_strict = re.tpl_host_fuzzy + re.src_host_terminator;
  re.src_host_port_strict = re.src_host + re.src_port + re.src_host_terminator;
  re.tpl_host_port_fuzzy_strict = re.tpl_host_fuzzy + re.src_port + re.src_host_terminator;
  re.tpl_host_port_no_ip_fuzzy_strict = re.tpl_host_no_ip_fuzzy + re.src_port + re.src_host_terminator;
  re.tpl_host_fuzzy_test = "localhost|www\\.|\\.\\d{1,3}\\.|(?:\\.(?:%TLDS%)(?:" + re.src_ZPCc + "|>|$))";
  re.tpl_email_fuzzy = "(^|" + text_separators + '|"|\\(|' + re.src_ZCc + ")(" + re.src_email_name + "@" + re.tpl_host_fuzzy_strict + ")";
  re.tpl_link_fuzzy = // Fuzzy link can't be prepended with .:/\- and non punctuation.
  // but can start with > (markdown blockquote)
  "(^|(?![.:/\\-_@])(?:[$+<=>^`|｜]|" + re.src_ZPCc + "))((?![$+<=>^`|｜])" + re.tpl_host_port_fuzzy_strict + re.src_path + ")";
  re.tpl_link_no_ip_fuzzy = // Fuzzy link can't be prepended with .:/\- and non punctuation.
  // but can start with > (markdown blockquote)
  "(^|(?![.:/\\-_@])(?:[$+<=>^`|｜]|" + re.src_ZPCc + "))((?![$+<=>^`|｜])" + re.tpl_host_port_no_ip_fuzzy_strict + re.src_path + ")";
  return re;
}
function assign(obj) {
  const sources = Array.prototype.slice.call(arguments, 1);
  sources.forEach(function(source2) {
    if (!source2) {
      return;
    }
    Object.keys(source2).forEach(function(key2) {
      obj[key2] = source2[key2];
    });
  });
  return obj;
}
function _class(obj) {
  return Object.prototype.toString.call(obj);
}
function isString(obj) {
  return _class(obj) === "[object String]";
}
function isObject(obj) {
  return _class(obj) === "[object Object]";
}
function isRegExp(obj) {
  return _class(obj) === "[object RegExp]";
}
function isFunction(obj) {
  return _class(obj) === "[object Function]";
}
function escapeRE(str) {
  return str.replace(/[.?*+^$[\]\\(){}|-]/g, "\\$&");
}
const defaultOptions = {
  fuzzyLink: true,
  fuzzyEmail: true,
  fuzzyIP: false
};
function isOptionsObj(obj) {
  return Object.keys(obj || {}).reduce(function(acc, k2) {
    return acc || defaultOptions.hasOwnProperty(k2);
  }, false);
}
const defaultSchemas = {
  "http:": {
    validate: function(text2, pos2, self2) {
      const tail = text2.slice(pos2);
      if (!self2.re.http) {
        self2.re.http = new RegExp(
          "^\\/\\/" + self2.re.src_auth + self2.re.src_host_port_strict + self2.re.src_path,
          "i"
        );
      }
      if (self2.re.http.test(tail)) {
        return tail.match(self2.re.http)[0].length;
      }
      return 0;
    }
  },
  "https:": "http:",
  "ftp:": "http:",
  "//": {
    validate: function(text2, pos2, self2) {
      const tail = text2.slice(pos2);
      if (!self2.re.no_http) {
        self2.re.no_http = new RegExp(
          "^" + self2.re.src_auth + // Don't allow single-level domains, because of false positives like '//test'
          // with code comments
          "(?:localhost|(?:(?:" + self2.re.src_domain + ")\\.)+" + self2.re.src_domain_root + ")" + self2.re.src_port + self2.re.src_host_terminator + self2.re.src_path,
          "i"
        );
      }
      if (self2.re.no_http.test(tail)) {
        if (pos2 >= 3 && text2[pos2 - 3] === ":") {
          return 0;
        }
        if (pos2 >= 3 && text2[pos2 - 3] === "/") {
          return 0;
        }
        return tail.match(self2.re.no_http)[0].length;
      }
      return 0;
    }
  },
  "mailto:": {
    validate: function(text2, pos2, self2) {
      const tail = text2.slice(pos2);
      if (!self2.re.mailto) {
        self2.re.mailto = new RegExp(
          "^" + self2.re.src_email_name + "@" + self2.re.src_host_strict,
          "i"
        );
      }
      if (self2.re.mailto.test(tail)) {
        return tail.match(self2.re.mailto)[0].length;
      }
      return 0;
    }
  }
};
const tlds_2ch_src_re = "a[cdefgilmnoqrstuwxz]|b[abdefghijmnorstvwyz]|c[acdfghiklmnoruvwxyz]|d[ejkmoz]|e[cegrstu]|f[ijkmor]|g[abdefghilmnpqrstuwy]|h[kmnrtu]|i[delmnoqrst]|j[emop]|k[eghimnprwyz]|l[abcikrstuvy]|m[acdeghklmnopqrstuvwxyz]|n[acefgilopruz]|om|p[aefghklmnrstwy]|qa|r[eosuw]|s[abcdeghijklmnortuvxyz]|t[cdfghjklmnortvwz]|u[agksyz]|v[aceginu]|w[fs]|y[et]|z[amw]";
const tlds_default = "biz|com|edu|gov|net|org|pro|web|xxx|aero|asia|coop|info|museum|name|shop|рф".split("|");
function resetScanCache(self2) {
  self2.__index__ = -1;
  self2.__text_cache__ = "";
}
function createValidator(re) {
  return function(text2, pos2) {
    const tail = text2.slice(pos2);
    if (re.test(tail)) {
      return tail.match(re)[0].length;
    }
    return 0;
  };
}
function createNormalizer() {
  return function(match2, self2) {
    self2.normalize(match2);
  };
}
function compile(self2) {
  const re = self2.re = reFactory(self2.__opts__);
  const tlds2 = self2.__tlds__.slice();
  self2.onCompile();
  if (!self2.__tlds_replaced__) {
    tlds2.push(tlds_2ch_src_re);
  }
  tlds2.push(re.src_xn);
  re.src_tlds = tlds2.join("|");
  function untpl(tpl) {
    return tpl.replace("%TLDS%", re.src_tlds);
  }
  re.email_fuzzy = RegExp(untpl(re.tpl_email_fuzzy), "i");
  re.link_fuzzy = RegExp(untpl(re.tpl_link_fuzzy), "i");
  re.link_no_ip_fuzzy = RegExp(untpl(re.tpl_link_no_ip_fuzzy), "i");
  re.host_fuzzy_test = RegExp(untpl(re.tpl_host_fuzzy_test), "i");
  const aliases = [];
  self2.__compiled__ = {};
  function schemaError(name, val) {
    throw new Error('(LinkifyIt) Invalid schema "' + name + '": ' + val);
  }
  Object.keys(self2.__schemas__).forEach(function(name) {
    const val = self2.__schemas__[name];
    if (val === null) {
      return;
    }
    const compiled = { validate: null, link: null };
    self2.__compiled__[name] = compiled;
    if (isObject(val)) {
      if (isRegExp(val.validate)) {
        compiled.validate = createValidator(val.validate);
      } else if (isFunction(val.validate)) {
        compiled.validate = val.validate;
      } else {
        schemaError(name, val);
      }
      if (isFunction(val.normalize)) {
        compiled.normalize = val.normalize;
      } else if (!val.normalize) {
        compiled.normalize = createNormalizer();
      } else {
        schemaError(name, val);
      }
      return;
    }
    if (isString(val)) {
      aliases.push(name);
      return;
    }
    schemaError(name, val);
  });
  aliases.forEach(function(alias) {
    if (!self2.__compiled__[self2.__schemas__[alias]]) {
      return;
    }
    self2.__compiled__[alias].validate = self2.__compiled__[self2.__schemas__[alias]].validate;
    self2.__compiled__[alias].normalize = self2.__compiled__[self2.__schemas__[alias]].normalize;
  });
  self2.__compiled__[""] = { validate: null, normalize: createNormalizer() };
  const slist = Object.keys(self2.__compiled__).filter(function(name) {
    return name.length > 0 && self2.__compiled__[name];
  }).map(escapeRE).join("|");
  self2.re.schema_test = RegExp("(^|(?!_)(?:[><｜]|" + re.src_ZPCc + "))(" + slist + ")", "i");
  self2.re.schema_search = RegExp("(^|(?!_)(?:[><｜]|" + re.src_ZPCc + "))(" + slist + ")", "ig");
  self2.re.schema_at_start = RegExp("^" + self2.re.schema_search.source, "i");
  self2.re.pretest = RegExp(
    "(" + self2.re.schema_test.source + ")|(" + self2.re.host_fuzzy_test.source + ")|@",
    "i"
  );
  resetScanCache(self2);
}
function Match(self2, shift) {
  const start2 = self2.__index__;
  const end2 = self2.__last_index__;
  const text2 = self2.__text_cache__.slice(start2, end2);
  this.schema = self2.__schema__.toLowerCase();
  this.index = start2 + shift;
  this.lastIndex = end2 + shift;
  this.raw = text2;
  this.text = text2;
  this.url = text2;
}
function createMatch(self2, shift) {
  const match2 = new Match(self2, shift);
  self2.__compiled__[match2.schema].normalize(match2, self2);
  return match2;
}
function LinkifyIt(schemas, options) {
  if (!(this instanceof LinkifyIt)) {
    return new LinkifyIt(schemas, options);
  }
  if (!options) {
    if (isOptionsObj(schemas)) {
      options = schemas;
      schemas = {};
    }
  }
  this.__opts__ = assign({}, defaultOptions, options);
  this.__index__ = -1;
  this.__last_index__ = -1;
  this.__schema__ = "";
  this.__text_cache__ = "";
  this.__schemas__ = assign({}, defaultSchemas, schemas);
  this.__compiled__ = {};
  this.__tlds__ = tlds_default;
  this.__tlds_replaced__ = false;
  this.re = {};
  compile(this);
}
LinkifyIt.prototype.add = function add(schema, definition) {
  this.__schemas__[schema] = definition;
  compile(this);
  return this;
};
LinkifyIt.prototype.set = function set(options) {
  this.__opts__ = assign(this.__opts__, options);
  return this;
};
LinkifyIt.prototype.test = function test(text2) {
  this.__text_cache__ = text2;
  this.__index__ = -1;
  if (!text2.length) {
    return false;
  }
  let m2, ml, me, len, shift, next, re, tld_pos, at_pos;
  if (this.re.schema_test.test(text2)) {
    re = this.re.schema_search;
    re.lastIndex = 0;
    while ((m2 = re.exec(text2)) !== null) {
      len = this.testSchemaAt(text2, m2[2], re.lastIndex);
      if (len) {
        this.__schema__ = m2[2];
        this.__index__ = m2.index + m2[1].length;
        this.__last_index__ = m2.index + m2[0].length + len;
        break;
      }
    }
  }
  if (this.__opts__.fuzzyLink && this.__compiled__["http:"]) {
    tld_pos = text2.search(this.re.host_fuzzy_test);
    if (tld_pos >= 0) {
      if (this.__index__ < 0 || tld_pos < this.__index__) {
        if ((ml = text2.match(this.__opts__.fuzzyIP ? this.re.link_fuzzy : this.re.link_no_ip_fuzzy)) !== null) {
          shift = ml.index + ml[1].length;
          if (this.__index__ < 0 || shift < this.__index__) {
            this.__schema__ = "";
            this.__index__ = shift;
            this.__last_index__ = ml.index + ml[0].length;
          }
        }
      }
    }
  }
  if (this.__opts__.fuzzyEmail && this.__compiled__["mailto:"]) {
    at_pos = text2.indexOf("@");
    if (at_pos >= 0) {
      if ((me = text2.match(this.re.email_fuzzy)) !== null) {
        shift = me.index + me[1].length;
        next = me.index + me[0].length;
        if (this.__index__ < 0 || shift < this.__index__ || shift === this.__index__ && next > this.__last_index__) {
          this.__schema__ = "mailto:";
          this.__index__ = shift;
          this.__last_index__ = next;
        }
      }
    }
  }
  return this.__index__ >= 0;
};
LinkifyIt.prototype.pretest = function pretest(text2) {
  return this.re.pretest.test(text2);
};
LinkifyIt.prototype.testSchemaAt = function testSchemaAt(text2, schema, pos2) {
  if (!this.__compiled__[schema.toLowerCase()]) {
    return 0;
  }
  return this.__compiled__[schema.toLowerCase()].validate(text2, pos2, this);
};
LinkifyIt.prototype.match = function match(text2) {
  const result = [];
  let shift = 0;
  if (this.__index__ >= 0 && this.__text_cache__ === text2) {
    result.push(createMatch(this, shift));
    shift = this.__last_index__;
  }
  let tail = shift ? text2.slice(shift) : text2;
  while (this.test(tail)) {
    result.push(createMatch(this, shift));
    tail = tail.slice(this.__last_index__);
    shift += this.__last_index__;
  }
  if (result.length) {
    return result;
  }
  return null;
};
LinkifyIt.prototype.matchAtStart = function matchAtStart(text2) {
  this.__text_cache__ = text2;
  this.__index__ = -1;
  if (!text2.length) return null;
  const m2 = this.re.schema_at_start.exec(text2);
  if (!m2) return null;
  const len = this.testSchemaAt(text2, m2[2], m2[0].length);
  if (!len) return null;
  this.__schema__ = m2[2];
  this.__index__ = m2.index + m2[1].length;
  this.__last_index__ = m2.index + m2[0].length + len;
  return createMatch(this, 0);
};
LinkifyIt.prototype.tlds = function tlds(list2, keepOld) {
  list2 = Array.isArray(list2) ? list2 : [list2];
  if (!keepOld) {
    this.__tlds__ = list2.slice();
    this.__tlds_replaced__ = true;
    compile(this);
    return this;
  }
  this.__tlds__ = this.__tlds__.concat(list2).sort().filter(function(el, idx, arr) {
    return el !== arr[idx - 1];
  }).reverse();
  compile(this);
  return this;
};
LinkifyIt.prototype.normalize = function normalize2(match2) {
  if (!match2.schema) {
    match2.url = "http://" + match2.url;
  }
  if (match2.schema === "mailto:" && !/^mailto:/i.test(match2.url)) {
    match2.url = "mailto:" + match2.url;
  }
};
LinkifyIt.prototype.onCompile = function onCompile() {
};
const maxInt = 2147483647;
const base = 36;
const tMin = 1;
const tMax = 26;
const skew = 38;
const damp = 700;
const initialBias = 72;
const initialN = 128;
const delimiter = "-";
const regexPunycode = /^xn--/;
const regexNonASCII = /[^\0-\x7F]/;
const regexSeparators = /[\x2E\u3002\uFF0E\uFF61]/g;
const errors = {
  "overflow": "Overflow: input needs wider integers to process",
  "not-basic": "Illegal input >= 0x80 (not a basic code point)",
  "invalid-input": "Invalid input"
};
const baseMinusTMin = base - tMin;
const floor = Math.floor;
const stringFromCharCode = String.fromCharCode;
function error(type) {
  throw new RangeError(errors[type]);
}
function map(array, callback) {
  const result = [];
  let length = array.length;
  while (length--) {
    result[length] = callback(array[length]);
  }
  return result;
}
function mapDomain(domain, callback) {
  const parts = domain.split("@");
  let result = "";
  if (parts.length > 1) {
    result = parts[0] + "@";
    domain = parts[1];
  }
  domain = domain.replace(regexSeparators, ".");
  const labels = domain.split(".");
  const encoded = map(labels, callback).join(".");
  return result + encoded;
}
function ucs2decode(string) {
  const output = [];
  let counter = 0;
  const length = string.length;
  while (counter < length) {
    const value = string.charCodeAt(counter++);
    if (value >= 55296 && value <= 56319 && counter < length) {
      const extra = string.charCodeAt(counter++);
      if ((extra & 64512) == 56320) {
        output.push(((value & 1023) << 10) + (extra & 1023) + 65536);
      } else {
        output.push(value);
        counter--;
      }
    } else {
      output.push(value);
    }
  }
  return output;
}
const ucs2encode = (codePoints) => String.fromCodePoint(...codePoints);
const basicToDigit = function(codePoint) {
  if (codePoint >= 48 && codePoint < 58) {
    return 26 + (codePoint - 48);
  }
  if (codePoint >= 65 && codePoint < 91) {
    return codePoint - 65;
  }
  if (codePoint >= 97 && codePoint < 123) {
    return codePoint - 97;
  }
  return base;
};
const digitToBasic = function(digit, flag) {
  return digit + 22 + 75 * (digit < 26) - ((flag != 0) << 5);
};
const adapt = function(delta, numPoints, firstTime) {
  let k2 = 0;
  delta = firstTime ? floor(delta / damp) : delta >> 1;
  delta += floor(delta / numPoints);
  for (; delta > baseMinusTMin * tMax >> 1; k2 += base) {
    delta = floor(delta / baseMinusTMin);
  }
  return floor(k2 + (baseMinusTMin + 1) * delta / (delta + skew));
};
const decode = function(input) {
  const output = [];
  const inputLength = input.length;
  let i = 0;
  let n2 = initialN;
  let bias = initialBias;
  let basic = input.lastIndexOf(delimiter);
  if (basic < 0) {
    basic = 0;
  }
  for (let j2 = 0; j2 < basic; ++j2) {
    if (input.charCodeAt(j2) >= 128) {
      error("not-basic");
    }
    output.push(input.charCodeAt(j2));
  }
  for (let index = basic > 0 ? basic + 1 : 0; index < inputLength; ) {
    const oldi = i;
    for (let w2 = 1, k2 = base; ; k2 += base) {
      if (index >= inputLength) {
        error("invalid-input");
      }
      const digit = basicToDigit(input.charCodeAt(index++));
      if (digit >= base) {
        error("invalid-input");
      }
      if (digit > floor((maxInt - i) / w2)) {
        error("overflow");
      }
      i += digit * w2;
      const t2 = k2 <= bias ? tMin : k2 >= bias + tMax ? tMax : k2 - bias;
      if (digit < t2) {
        break;
      }
      const baseMinusT = base - t2;
      if (w2 > floor(maxInt / baseMinusT)) {
        error("overflow");
      }
      w2 *= baseMinusT;
    }
    const out = output.length + 1;
    bias = adapt(i - oldi, out, oldi == 0);
    if (floor(i / out) > maxInt - n2) {
      error("overflow");
    }
    n2 += floor(i / out);
    i %= out;
    output.splice(i++, 0, n2);
  }
  return String.fromCodePoint(...output);
};
const encode = function(input) {
  const output = [];
  input = ucs2decode(input);
  const inputLength = input.length;
  let n2 = initialN;
  let delta = 0;
  let bias = initialBias;
  for (const currentValue of input) {
    if (currentValue < 128) {
      output.push(stringFromCharCode(currentValue));
    }
  }
  const basicLength = output.length;
  let handledCPCount = basicLength;
  if (basicLength) {
    output.push(delimiter);
  }
  while (handledCPCount < inputLength) {
    let m2 = maxInt;
    for (const currentValue of input) {
      if (currentValue >= n2 && currentValue < m2) {
        m2 = currentValue;
      }
    }
    const handledCPCountPlusOne = handledCPCount + 1;
    if (m2 - n2 > floor((maxInt - delta) / handledCPCountPlusOne)) {
      error("overflow");
    }
    delta += (m2 - n2) * handledCPCountPlusOne;
    n2 = m2;
    for (const currentValue of input) {
      if (currentValue < n2 && ++delta > maxInt) {
        error("overflow");
      }
      if (currentValue === n2) {
        let q2 = delta;
        for (let k2 = base; ; k2 += base) {
          const t2 = k2 <= bias ? tMin : k2 >= bias + tMax ? tMax : k2 - bias;
          if (q2 < t2) {
            break;
          }
          const qMinusT = q2 - t2;
          const baseMinusT = base - t2;
          output.push(
            stringFromCharCode(digitToBasic(t2 + qMinusT % baseMinusT, 0))
          );
          q2 = floor(qMinusT / baseMinusT);
        }
        output.push(stringFromCharCode(digitToBasic(q2, 0)));
        bias = adapt(delta, handledCPCountPlusOne, handledCPCount === basicLength);
        delta = 0;
        ++handledCPCount;
      }
    }
    ++delta;
    ++n2;
  }
  return output.join("");
};
const toUnicode = function(input) {
  return mapDomain(input, function(string) {
    return regexPunycode.test(string) ? decode(string.slice(4).toLowerCase()) : string;
  });
};
const toASCII = function(input) {
  return mapDomain(input, function(string) {
    return regexNonASCII.test(string) ? "xn--" + encode(string) : string;
  });
};
const punycode = {
  /**
   * A string representing the current Punycode.js version number.
   * @memberOf punycode
   * @type String
   */
  "version": "2.3.1",
  /**
   * An object of methods to convert from JavaScript's internal character
   * representation (UCS-2) to Unicode code points, and back.
   * @see <https://mathiasbynens.be/notes/javascript-encoding>
   * @memberOf punycode
   * @type Object
   */
  "ucs2": {
    "decode": ucs2decode,
    "encode": ucs2encode
  },
  "decode": decode,
  "encode": encode,
  "toASCII": toASCII,
  "toUnicode": toUnicode
};
const cfg_default = {
  options: {
    // Enable HTML tags in source
    html: false,
    // Use '/' to close single tags (<br />)
    xhtmlOut: false,
    // Convert '\n' in paragraphs into <br>
    breaks: false,
    // CSS language prefix for fenced blocks
    langPrefix: "language-",
    // autoconvert URL-like texts to links
    linkify: false,
    // Enable some language-neutral replacements + quotes beautification
    typographer: false,
    // Double + single quotes replacement pairs, when typographer enabled,
    // and smartquotes on. Could be either a String or an Array.
    //
    // For example, you can use '«»„“' for Russian, '„“‚‘' for German,
    // and ['«\xA0', '\xA0»', '‹\xA0', '\xA0›'] for French (including nbsp).
    quotes: "“”‘’",
    /* “”‘’ */
    // Highlighter function. Should return escaped HTML,
    // or '' if the source string is not changed and should be escaped externaly.
    // If result starts with <pre... internal wrapper is skipped.
    //
    // function (/*str, lang*/) { return ''; }
    //
    highlight: null,
    // Internal protection, recursion limit
    maxNesting: 100
  },
  components: {
    core: {},
    block: {},
    inline: {}
  }
};
const cfg_zero = {
  options: {
    // Enable HTML tags in source
    html: false,
    // Use '/' to close single tags (<br />)
    xhtmlOut: false,
    // Convert '\n' in paragraphs into <br>
    breaks: false,
    // CSS language prefix for fenced blocks
    langPrefix: "language-",
    // autoconvert URL-like texts to links
    linkify: false,
    // Enable some language-neutral replacements + quotes beautification
    typographer: false,
    // Double + single quotes replacement pairs, when typographer enabled,
    // and smartquotes on. Could be either a String or an Array.
    //
    // For example, you can use '«»„“' for Russian, '„“‚‘' for German,
    // and ['«\xA0', '\xA0»', '‹\xA0', '\xA0›'] for French (including nbsp).
    quotes: "“”‘’",
    /* “”‘’ */
    // Highlighter function. Should return escaped HTML,
    // or '' if the source string is not changed and should be escaped externaly.
    // If result starts with <pre... internal wrapper is skipped.
    //
    // function (/*str, lang*/) { return ''; }
    //
    highlight: null,
    // Internal protection, recursion limit
    maxNesting: 20
  },
  components: {
    core: {
      rules: [
        "normalize",
        "block",
        "inline",
        "text_join"
      ]
    },
    block: {
      rules: [
        "paragraph"
      ]
    },
    inline: {
      rules: [
        "text"
      ],
      rules2: [
        "balance_pairs",
        "fragments_join"
      ]
    }
  }
};
const cfg_commonmark = {
  options: {
    // Enable HTML tags in source
    html: true,
    // Use '/' to close single tags (<br />)
    xhtmlOut: true,
    // Convert '\n' in paragraphs into <br>
    breaks: false,
    // CSS language prefix for fenced blocks
    langPrefix: "language-",
    // autoconvert URL-like texts to links
    linkify: false,
    // Enable some language-neutral replacements + quotes beautification
    typographer: false,
    // Double + single quotes replacement pairs, when typographer enabled,
    // and smartquotes on. Could be either a String or an Array.
    //
    // For example, you can use '«»„“' for Russian, '„“‚‘' for German,
    // and ['«\xA0', '\xA0»', '‹\xA0', '\xA0›'] for French (including nbsp).
    quotes: "“”‘’",
    /* “”‘’ */
    // Highlighter function. Should return escaped HTML,
    // or '' if the source string is not changed and should be escaped externaly.
    // If result starts with <pre... internal wrapper is skipped.
    //
    // function (/*str, lang*/) { return ''; }
    //
    highlight: null,
    // Internal protection, recursion limit
    maxNesting: 20
  },
  components: {
    core: {
      rules: [
        "normalize",
        "block",
        "inline",
        "text_join"
      ]
    },
    block: {
      rules: [
        "blockquote",
        "code",
        "fence",
        "heading",
        "hr",
        "html_block",
        "lheading",
        "list",
        "reference",
        "paragraph"
      ]
    },
    inline: {
      rules: [
        "autolink",
        "backticks",
        "emphasis",
        "entity",
        "escape",
        "html_inline",
        "image",
        "link",
        "newline",
        "text"
      ],
      rules2: [
        "balance_pairs",
        "emphasis",
        "fragments_join"
      ]
    }
  }
};
const config = {
  default: cfg_default,
  zero: cfg_zero,
  commonmark: cfg_commonmark
};
const BAD_PROTO_RE = /^(vbscript|javascript|file|data):/;
const GOOD_DATA_RE = /^data:image\/(gif|png|jpeg|webp);/;
function validateLink(url) {
  const str = url.trim().toLowerCase();
  return BAD_PROTO_RE.test(str) ? GOOD_DATA_RE.test(str) : true;
}
const RECODE_HOSTNAME_FOR = ["http:", "https:", "mailto:"];
function normalizeLink(url) {
  const parsed = urlParse(url, true);
  if (parsed.hostname) {
    if (!parsed.protocol || RECODE_HOSTNAME_FOR.indexOf(parsed.protocol) >= 0) {
      try {
        parsed.hostname = punycode.toASCII(parsed.hostname);
      } catch (er) {
      }
    }
  }
  return encode$1(format$1(parsed));
}
function normalizeLinkText(url) {
  const parsed = urlParse(url, true);
  if (parsed.hostname) {
    if (!parsed.protocol || RECODE_HOSTNAME_FOR.indexOf(parsed.protocol) >= 0) {
      try {
        parsed.hostname = punycode.toUnicode(parsed.hostname);
      } catch (er) {
      }
    }
  }
  return decode$1(format$1(parsed), decode$1.defaultChars + "%");
}
function MarkdownIt(presetName, options) {
  if (!(this instanceof MarkdownIt)) {
    return new MarkdownIt(presetName, options);
  }
  if (!options) {
    if (!isString$1(presetName)) {
      options = presetName || {};
      presetName = "default";
    }
  }
  this.inline = new ParserInline();
  this.block = new ParserBlock();
  this.core = new Core();
  this.renderer = new Renderer();
  this.linkify = new LinkifyIt();
  this.validateLink = validateLink;
  this.normalizeLink = normalizeLink;
  this.normalizeLinkText = normalizeLinkText;
  this.utils = utils;
  this.helpers = assign$1({}, helpers);
  this.options = {};
  this.configure(presetName);
  if (options) {
    this.set(options);
  }
}
MarkdownIt.prototype.set = function(options) {
  assign$1(this.options, options);
  return this;
};
MarkdownIt.prototype.configure = function(presets) {
  const self2 = this;
  if (isString$1(presets)) {
    const presetName = presets;
    presets = config[presetName];
    if (!presets) {
      throw new Error('Wrong `markdown-it` preset "' + presetName + '", check name');
    }
  }
  if (!presets) {
    throw new Error("Wrong `markdown-it` preset, can't be empty");
  }
  if (presets.options) {
    self2.set(presets.options);
  }
  if (presets.components) {
    Object.keys(presets.components).forEach(function(name) {
      if (presets.components[name].rules) {
        self2[name].ruler.enableOnly(presets.components[name].rules);
      }
      if (presets.components[name].rules2) {
        self2[name].ruler2.enableOnly(presets.components[name].rules2);
      }
    });
  }
  return this;
};
MarkdownIt.prototype.enable = function(list2, ignoreInvalid) {
  let result = [];
  if (!Array.isArray(list2)) {
    list2 = [list2];
  }
  ["core", "block", "inline"].forEach(function(chain) {
    result = result.concat(this[chain].ruler.enable(list2, true));
  }, this);
  result = result.concat(this.inline.ruler2.enable(list2, true));
  const missed = list2.filter(function(name) {
    return result.indexOf(name) < 0;
  });
  if (missed.length && !ignoreInvalid) {
    throw new Error("MarkdownIt. Failed to enable unknown rule(s): " + missed);
  }
  return this;
};
MarkdownIt.prototype.disable = function(list2, ignoreInvalid) {
  let result = [];
  if (!Array.isArray(list2)) {
    list2 = [list2];
  }
  ["core", "block", "inline"].forEach(function(chain) {
    result = result.concat(this[chain].ruler.disable(list2, true));
  }, this);
  result = result.concat(this.inline.ruler2.disable(list2, true));
  const missed = list2.filter(function(name) {
    return result.indexOf(name) < 0;
  });
  if (missed.length && !ignoreInvalid) {
    throw new Error("MarkdownIt. Failed to disable unknown rule(s): " + missed);
  }
  return this;
};
MarkdownIt.prototype.use = function(plugin) {
  const args = [this].concat(Array.prototype.slice.call(arguments, 1));
  plugin.apply(plugin, args);
  return this;
};
MarkdownIt.prototype.parse = function(src, env) {
  if (typeof src !== "string") {
    throw new Error("Input data should be a String");
  }
  const state = new this.core.State(src, this, env);
  this.core.process(state);
  return state.tokens;
};
MarkdownIt.prototype.render = function(src, env) {
  env = env || {};
  return this.renderer.render(this.parse(src, env), this.options, env);
};
MarkdownIt.prototype.parseInline = function(src, env) {
  const state = new this.core.State(src, this, env);
  state.inlineMode = true;
  this.core.process(state);
  return state.tokens;
};
MarkdownIt.prototype.renderInline = function(src, env) {
  env = env || {};
  return this.renderer.render(this.parseInline(src, env), this.options, env);
};
const MarkdownDiv = (props) => {
  const { markdown, style, contentRef } = props;
  const escaped = markdown ? escape$1(markdown) : "";
  const preRendered = preRenderText(escaped);
  const protectedText = protectMarkdown(preRendered);
  let renderedHtml = protectedText;
  try {
    const md = MarkdownIt({
      breaks: true,
      html: true
    });
    renderedHtml = md.render(protectedText);
  } catch (ex) {
    console.log("Unable to markdown render content");
    console.error(ex);
  }
  const unescaped = unprotectMarkdown(renderedHtml);
  const withCode = unescapeCodeHtmlEntities(unescaped);
  const markup = { __html: withCode };
  return m$1`<div
    ref=${contentRef}
    dangerouslySetInnerHTML=${markup}
    style=${style}
    class="${props.class ? `${props.class} ` : ""}markdown-content"
  />`;
};
const kLetterListPattern = /^([a-zA-Z][).]\s.*?)$/gm;
const kCommonmarkReferenceLinkPattern = /\[([^\]]*)\]: (?!http)(.*)/g;
const preRenderText = (txt) => {
  txt = txt.replace(/^[\u200B\u200C\u200D\u200E\u200F\uFEFF]/, "");
  return txt.replaceAll(
    kLetterListPattern,
    "<p style='margin-bottom: 0.2em;'>$1</p>"
  );
};
const protectMarkdown = (txt) => {
  return txt.replaceAll(
    kCommonmarkReferenceLinkPattern,
    "(open:767A125E)$1(close:767A125E) $2 "
  );
};
const unprotectMarkdown = (txt) => {
  txt = txt.replaceAll("(open:767A125E)", "[");
  txt = txt.replaceAll("(close:767A125E)", "]");
  return txt;
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
    function(match2, starttag, content, endtag) {
      return starttag + content.replace(
        /&(?:amp|lt|gt|quot|#39|#x2F|#x5C|#96);/g,
        function(entity2) {
          return htmlEntities[entity2] || entity2;
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
  for (var i = 0; i < toBeCopied.length; i++) {
    inside[toBeCopied[i]] = Prism2.languages.bash[toBeCopied[i]];
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
const ExpandablePanel = ({
  collapse,
  border,
  lines = 15,
  style,
  children
}) => {
  const [collapsed, setCollapsed] = h(collapse);
  const [showToggle, setShowToggle] = h(false);
  const contentsRef = A();
  const observerRef = A();
  y(() => {
    setCollapsed(collapse);
  }, [children, collapse]);
  const refreshCollapse = q(() => {
    if (collapse && contentsRef.current) {
      const isScrollable = contentsRef.current.offsetHeight < contentsRef.current.scrollHeight;
      setShowToggle(isScrollable);
    }
  }, [collapse, setShowToggle, contentsRef]);
  y(() => {
    refreshCollapse();
  }, [children]);
  y(() => {
    observerRef.current = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          refreshCollapse();
        }
      });
    });
    if (contentsRef.current) {
      observerRef.current.observe(contentsRef.current);
    }
    return () => {
      if (observerRef.current && contentsRef.current) {
        observerRef.current.unobserve(contentsRef.current);
      }
    };
  }, [contentsRef, observerRef]);
  let contentsStyle = { fontSize: FontSize.base };
  if (collapse && collapsed) {
    contentsStyle = {
      ...contentsStyle,
      maxHeight: `${lines}em`,
      overflow: "hidden"
    };
  }
  if (border) {
    contentsStyle.border = "solid var(--bs-light-border-subtle) 1px";
  }
  if (!showToggle) {
    contentsStyle.marginBottom = "1em";
  }
  return m$1`<div
      class="expandable-panel"
      ref=${contentsRef}
      style=${{ ...contentsStyle, ...style }}
    >
      ${children}
    </div>
    ${showToggle ? m$1`<${MoreToggle}
          collapsed=${collapsed}
          setCollapsed=${setCollapsed}
          border=${!border}
          style=${style}
        />` : ""}`;
};
const MoreToggle = ({ collapsed, border, setCollapsed, style }) => {
  const text2 = collapsed ? "more" : "less";
  const icon = collapsed ? ApplicationIcons["expand-down"] : ApplicationIcons.collapse.up;
  const topStyle = {
    display: "flex",
    marginBottom: "0.5em",
    ...style
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
          <i class="${icon}" /> ${text2}
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
  view,
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
  return m$1`<div>
    ${icon}
    ${!view || view.title ? m$1`<code style=${{ fontSize: FontSize.small }}
          >${(view == null ? void 0 : view.title) || functionCall}</code
        >` : ""}
    <div>
      <div style=${{ marginLeft: `${codeIndent}` }}>
        <${ToolInput}
          type=${inputType}
          contents=${input}
          view=${view}
          style=${{ marginBottom: "1em" }}
        />
        ${output ? m$1`
              <${ExpandablePanel} collapse=${true} border=${true} lines=${15}>
              <${MessageContent} contents=${output} />
              </${ExpandablePanel}>` : ""}
      </div>
    </div>
  </div>`;
};
const ToolInput = ({ type, contents, view, style }) => {
  if (!contents) {
    return "";
  }
  if (view) {
    const toolInputRef = A(
      /** @type {HTMLElement|null} */
      null
    );
    y(() => {
      if (toolInputRef.current) {
        for (const child of toolInputRef.current.base.children) {
          if (child.tagName === "PRE") {
            const childChild = child.firstElementChild;
            if (childChild && childChild.tagName === "CODE") {
              const hasLanguageClass = Array.from(childChild.classList).some(
                (className) => className.startsWith("language-")
              );
              if (hasLanguageClass) {
                child.classList.add("tool-output");
                Prism$1.highlightElement(childChild);
              }
            }
          }
        }
      }
    }, [toolInputRef.current]);
    return m$1`<${MarkdownDiv}
      markdown=${view.content}
      ref=${toolInputRef}
      style=${style}
    />`;
  } else {
    const toolInputRef = A(
      /** @type {HTMLElement|null} */
      null
    );
    y(() => {
      const tokens = Prism$1.languages[type];
      if (toolInputRef.current && tokens) {
        let resolvedContents = contents;
        if (typeof contents === "object" || Array.isArray(contents)) {
          resolvedContents = JSON.stringify(contents);
        }
        const html = Prism$1.highlight(resolvedContents, tokens, type);
        toolInputRef.current.innerHTML = html;
      }
    }, [toolInputRef.current, contents, type, view]);
    return m$1`<pre
      class="tool-output"
      style=${{
      padding: "0.5em",
      marginTop: "0.25em",
      marginBottom: "1rem",
      ...style
    }}
    >
        <code ref=${toolInputRef} class="sourceCode${type ? ` language-${type}` : ""}" style=${{
      overflowWrap: "anywhere",
      whiteSpace: "pre-wrap"
    }}>
          ${contents}
          </code>
      </pre>`;
  }
};
const ToolOutput = ({ output, style }) => {
  if (!output) {
    return "";
  }
  const outputs = [];
  if (Array.isArray(output)) {
    output.forEach((out) => {
      if (out.type === "text") {
        outputs.push(
          m$1`<${ToolTextOutput} text=${out.text} style=${style} />`
        );
      } else {
        if (out.image.startsWith("data:")) {
          outputs.push(
            m$1`<img
              src="${out.image}"
              style=${{
              maxWidth: "100%",
              border: "solid var(--bs-border-color) 1px",
              ...style
            }}
            />`
          );
        } else {
          outputs.push(
            m$1`<${ToolTextOutput}
              text=${String(out.image)}
              style=${style}
            />`
          );
        }
      }
    });
  } else {
    outputs.push(
      m$1`<${ToolTextOutput} text=${String(output)} style=${style} />`
    );
  }
  return m$1`<div style=${{ display: "grid" }}>${outputs}</div>`;
};
const ToolTextOutput = ({ text: text2, style }) => {
  return m$1`<pre
    style=${{
    marginLeft: "2px",
    padding: "0.5em 0.5em 0.5em 0.5em",
    whiteSpace: "pre-wrap",
    marginBottom: "0",
    ...style
  }}
  >
    <code class="sourceCode" style=${{ wordWrap: "anywhere" }}>
      ${text2.trim()}
      </code>
  </pre>`;
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
        if (content) {
          const renderer = messageRenderers[content.type];
          if (renderer) {
            return renderer.render(content, index === contents.length - 1);
          } else {
            console.error(`Unknown message content type '${content.type}'`);
          }
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
      return m$1`<${ToolOutput} output=${content.content} />`;
    }
  }
};
const ChatView = ({
  id,
  messages,
  toolCallStyle,
  style,
  indented,
  numbered = true
}) => {
  const resolvedMessages = [];
  for (const message of messages) {
    if (message.role === "tool") {
      if (resolvedMessages.length > 0) {
        const msg = resolvedMessages[resolvedMessages.length - 1];
        msg.toolMessages.push(message);
      }
    } else {
      resolvedMessages.push({ message, toolMessages: [] });
    }
  }
  const systemMessages = [];
  const collapsedMessages = resolvedMessages.map((resolved) => {
    if (resolved.message.role === "system") {
      systemMessages.push(resolved.message);
    }
    return resolved;
  }).filter((resolved) => {
    return resolved.message.role !== "system";
  });
  const systemContent = [];
  for (const systemMessage2 of systemMessages) {
    const contents = Array.isArray(systemMessage2.content) ? systemMessage2.content : [systemMessage2.content];
    systemContent.push(...contents.map(normalizeContent));
  }
  const systemMessage = {
    role: "system",
    content: systemContent,
    source: "input"
  };
  if (systemMessage && systemMessage.content.length > 0) {
    collapsedMessages.unshift({ message: systemMessage });
  }
  const result = m$1`
    <div style=${style}>
      ${collapsedMessages.map((msg, index) => {
    if (collapsedMessages.length > 1 && numbered) {
      return m$1` <div
            style=${{
        display: "grid",
        gridTemplateColumns: "max-content auto",
        columnGap: "0.4em"
      }}
          >
            <div
              style=${{
        fontSize: FontSize.smaller,
        ...TextStyle.secondary,
        marginTop: "0.1em"
      }}
            >
              ${index + 1}
            </div>
            <${ChatMessage}
              id=${`${id}-chat-messages`}
              message=${msg.message}
              toolMessages=${msg.toolMessages}
              indented=${indented}
              toolCallStyle=${toolCallStyle}
            />
          </div>`;
    } else {
      return m$1` <${ChatMessage}
            id=${`${id}-chat-messages`}
            message=${msg.message}
            toolMessages=${msg.toolMessages}
            indented=${indented}
            toolCallStyle=${toolCallStyle}
          />`;
    }
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
const ChatMessage = ({
  id,
  message,
  toolMessages,
  indented,
  toolCallStyle
}) => {
  const collapse = message.role === "system";
  return m$1`
    <div
      class="${message.role}"
      style=${{
    fontSize: FontSize.base,
    fontWeight: "300",
    paddingBottom: ".5em",
    marginLeft: "0",
    marginRight: "0",
    opacity: message.role === "system" ? "0.7" : "1",
    whiteSpace: "normal"
  }}
    >
      <div style=${{
    display: "grid",
    gridTemplateColumns: "max-content auto",
    columnGap: "0.3em",
    fontWeight: "500",
    marginBottom: "0.5em",
    ...TextStyle.label
  }}>
        <i class="${iconForMsg(message)}"></i>
        ${message.role}
      </div>
      <div style=${{ marginLeft: indented ? "1.1rem" : "0", paddingBottom: indented ? "0.8rem" : "0" }}>
      <${ExpandablePanel} collapse=${collapse}>
        <${MessageContents}
          key=${`${id}-contents`}
          message=${message}
          toolMessages=${toolMessages}
          toolCallStyle=${toolCallStyle}
        />
      </${ExpandablePanel}>
      </div>
    </div>
  `;
};
const MessageContents = ({ message, toolMessages, toolCallStyle }) => {
  if (message.role === "assistant" && message.tool_calls && message.tool_calls.length) {
    const result = [];
    if (message.content) {
      result.push(
        m$1`<div style=${{ marginBottom: "1em" }}>
          <${MessageContent} contents=${message.content} />
        </div>`
      );
    }
    const toolCalls = message.tool_calls.map((tool_call, idx) => {
      const { input, functionCall, inputType } = resolveToolInput(
        tool_call.function,
        tool_call.arguments
      );
      let toolMessage;
      if (tool_call.id) {
        toolMessage = toolMessages.find((msg) => {
          return msg.tool_call_id === tool_call.id;
        });
      } else {
        toolMessage = toolMessages[idx];
      }
      const resolvedToolOutput = resolveToolMessage(toolMessage);
      if (toolCallStyle === "compact") {
        return m$1`<code>tool: ${functionCall}</code>`;
      } else {
        return m$1`<${ToolCallView}
          functionCall=${functionCall}
          input=${input}
          inputType=${inputType}
          output=${resolvedToolOutput}
        />`;
      }
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
  if (msg.role === "user") {
    return ApplicationIcons.role.user;
  } else if (msg.role === "system") {
    return ApplicationIcons.role.system;
  } else if (msg.role === "tool") {
    return ApplicationIcons.role.tool;
  } else if (msg.role === "assistant") {
    return ApplicationIcons.role.assistant;
  } else {
    return ApplicationIcons.role.unknown;
  }
};
const resolveToolMessage = (toolMessage) => {
  if (!toolMessage) {
    return void 0;
  }
  const content = toolMessage.error !== null && toolMessage.error ? toolMessage.error.message : toolMessage.content;
  if (typeof content === "string") {
    return [
      {
        type: "tool",
        content
      }
    ];
  } else {
    return content.map((con) => {
      if (typeof content === "string") {
        return {
          type: "tool",
          content
        };
      } else if (con.type === "text") {
        return {
          content,
          type: "tool"
        };
      } else if (con.type === "image") {
        return {
          content,
          type: "tool"
        };
      }
    });
  }
};
const NavPills = ({ children }) => {
  const [activeItem, setActiveItem] = h(children[0].props["title"]);
  const NavPill = ({ title, activeItem: activeItem2, setActiveItem: setActiveItem2 }) => {
    const active = activeItem2 === title;
    return m$1` <li class="nav-item">
      <button
        type="button"
        role="tab"
        aria-selected=${active}
        style=${{
      minWidth: "4rem",
      ...TextStyle.label,
      fontSize: FontSize.small,
      padding: "0.1rem  0.6rem",
      borderRadius: "var(--bs-border-radius)"
    }}
        class="nav-link ${active ? "active " : ""}"
        onclick=${() => {
      setActiveItem2(title);
    }}
      >
        ${title}
      </button>
    </li>`;
  };
  const navPills = children.map((nav, idx) => {
    var _a2;
    const title = typeof nav === "object" ? ((_a2 = nav["props"]) == null ? void 0 : _a2.title) || `Tab ${idx}` : `Tab ${idx}`;
    return m$1`<${NavPill}
      title=${title}
      activeItem=${activeItem}
      setActiveItem=${setActiveItem}
    />`;
  });
  const navBodies = children.map((child) => {
    var _a2;
    return m$1` <div
      style=${{
      display: ((_a2 = child["props"]) == null ? void 0 : _a2.title) === activeItem ? "block" : "none"
    }}
    >
      ${child}
    </div>`;
  });
  return m$1`<ul
      class="nav nav-pills card-header-pills"
      style=${{ marginRight: "0" }}
      role="tablist"
      aria-orientation="horizontal"
    >
      ${navPills}
    </ul>
    ${navBodies}`;
};
const ChatMessageRenderer = {
  bucket: Buckets.first,
  canRender: (entry) => {
    var _a2, _b2;
    const val = entry.value;
    return Array.isArray(val) && val.length > 0 && ((_a2 = val[0]) == null ? void 0 : _a2.role) !== void 0 && ((_b2 = val[0]) == null ? void 0 : _b2.content) !== void 0;
  },
  render: (id, entry) => {
    return {
      rendered: m$1`
        <${NavPills}>
        <${ChatSummary} title="Last Turn" id=${id} messages=${entry.value} />
        <${ChatView} title="All" id=${id} messages=${entry.value} />
        </${NavPills}>
        `
    };
  }
};
const ChatSummary = ({ id, messages }) => {
  const summaryMessages = [];
  for (const message of messages.slice().reverse()) {
    summaryMessages.unshift(message);
    if (message.role === "user") {
      break;
    }
  }
  return m$1`<${ChatView} id=${id} messages=${summaryMessages} />`;
};
const RenderedContent = ({ id, entry }) => {
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
    const { rendered } = renderer.render(id, entry);
    if (rendered !== void 0) {
      value = rendered;
    }
  }
  return m$1`${value}`;
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
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "boolean";
    },
    render: (id, entry) => {
      entry.value = entry.value.toString();
      return contentRenderers.String.render(id, entry);
    }
  },
  Number: {
    bucket: Buckets.intermediate,
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
    render: (id, entry) => {
      const arrayMap = {};
      entry.value.forEach((entry2, index) => {
        arrayMap[`[${index}]`] = entry2;
      });
      const arrayRendered = m$1`<${MetaDataView}
        id=${id}
        style=${{ fontSize: FontSize.small }}
        entries="${arrayMap}"
        tableOptions="borderless,sm"
        compact
      />`;
      return { rendered: arrayRendered };
    }
  },
  ChatMessage: ChatMessageRenderer,
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
  web_browser: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      var _a2;
      return typeof entry.value === "string" && ((_a2 = entry.name) == null ? void 0 : _a2.startsWith("web_browser"));
    },
    render: (_id, entry) => {
      return {
        rendered: m$1`<pre style=${{ whiteSpace: "pre-wrap" }}>
${entry.value}</pre
        >`
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
  Image: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "string" && entry.value.startsWith("data:image/");
    },
    render: (id, entry) => {
      return {
        rendered: m$1`<img src=${entry.value} />`
      };
    }
  },
  Object: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object";
    },
    render: (id, entry) => {
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
  let coercedEntries;
  if (entries) {
    if (Array.isArray(entries)) {
      coercedEntries = entries;
    } else {
      coercedEntries = Object.entries(entries || {}).map(([key2, value]) => {
        return { name: key2, value };
      });
    }
  }
  const entryEls = (coercedEntries || []).map((entry, index) => {
    const id2 = `${baseId}-value-${index}`;
    return m$1`<tr class="${baseId}-row">
      <td
        class="${baseId}-key"
        style=${{ ...cellStyle, ...cellKeyStyle, ...cellKeyTextStyle }}
      >
        ${entry.name}
      </td>
      <td class="${baseId}-value" style=${{ ...cellStyle, ...cellValueStyle }}>
        <${RenderedContent} id=${id2} entry=${entry} />
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
const PlanCard = ({ evalSpec, evalPlan, scores }) => {
  return m$1`
    <${Card}>
      <${CardHeader} icon=${ApplicationIcons.config} label="Config"/>
      <${CardBody} id="${kPlanCardBodyId}" style=${{
    paddingTop: "0",
    paddingBottom: "0"
  }}>
      
        <${PlanDetailView}
          evaluation=${evalSpec}
          plan=${evalPlan}
          scores=${scores}
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
const ScorerDetailView = ({ name, scores, params }) => {
  if (scores.length > 1) {
    params["scores"] = scores;
  }
  return m$1`<${DetailStep}
    icon=${ApplicationIcons.scorer}
    name=${name}
    params=${params}
    style=${planItemStyle}
  />`;
};
const DatasetDetailView = ({ dataset, style }) => {
  const filtered = Object.fromEntries(
    Object.entries(dataset).filter(([key2]) => key2 !== "sample_ids")
  );
  if (!dataset || Object.keys(filtered).length === 0) {
    return m$1`<span style=${{ ...planItemStyle, ...style }}
      >No dataset information available</span
    >`;
  }
  return m$1`<${MetaDataView}
    entries="${filtered}"
    tableOptions="borderless,sm"
    style=${{ ...planItemStyle, ...style }}
  />`;
};
const SolversDetailView = ({ steps }) => {
  const separator = m$1` <div style=${{ ...planItemStyle, ...planSepStyle }}>
    <i class="${ApplicationIcons.arrows.right}"></i>
  </div>`;
  const details = steps == null ? void 0 : steps.map((step, index) => {
    return m$1`
      <${DetailStep} name=${step.solver} style=${planItemStyle} />
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
const DetailStep = ({ icon, name, params, style }) => {
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
          style=${{ fontSize: FontSize.small }}
        />`}
      </div>
    </div>
  `;
};
const PlanDetailView = ({ evaluation, plan, scores }) => {
  if (!evaluation) {
    return "";
  }
  const config2 = (evaluation == null ? void 0 : evaluation.config) || {};
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
  if (evaluation.tags) {
    taskInformation["Tags"] = evaluation.tags.join(", ");
  }
  if (evaluation == null ? void 0 : evaluation.model) {
    config2["model"] = evaluation.model;
  }
  if (evaluation == null ? void 0 : evaluation.model_base_url) {
    config2["model_base_url"] = evaluation.model_base_url;
  }
  if (evaluation == null ? void 0 : evaluation.sandbox) {
    config2["sandbox"] = evaluation.sandbox[0];
    if (evaluation.sandbox[1]) {
      config2["sandbox_config"] = evaluation.sandbox[1];
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
    contents: m$1`<${DatasetDetailView} dataset=${evaluation.dataset} />`
  });
  taskColumns.push({
    title: "Plan",
    style: wideColumnStyle,
    contents: m$1` <${SolversDetailView} steps=${steps} /> `
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
    config2,
    metadata
  );
  const configColumnStyle = cols === 1 ? oneColumnStyle : twoColumnStyle;
  metadataColumns.push({
    title: "Task Information",
    style: configColumnStyle,
    contents: m$1`
      <${MetaDataView}
        style=${planMetadataStyle}
        classes="task-title-deets-grid"
        entries="${taskInformation}"
        tableOptions="borderless,sm"
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
        />
      `
    });
  }
  if (config2 && Object.keys(config2).length > 0) {
    metadataColumns.push({
      title: "Configuration",
      style: configColumnStyle,
      contents: m$1`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-configuration"
          entries="${config2}"
          tableOptions="sm"
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
        />
      `
    });
  }
  return m$1`
    <div style=${{ paddingTop: "0", paddingBottom: "1em", marginLeft: "0" }}>
      <div
        style=${{
    display: "grid",
    gridTemplateColumns: `repeat(${taskColumns.length}, auto)`,
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
const MessageBand = ({ message, hidden, setHidden, type }) => {
  const bgColor = type === "info" ? "var(--bs-light)" : "var(--bs-" + type + "-bg-subtle)";
  const color = "var(--bs-" + type === "info" ? "secondary" : "undefined-text-emphasis)";
  return m$1`
    <div
      style=${{
    gridTemplateColumns: "max-content auto max-content",
    alignItems: "center",
    columnGap: "0.5em",
    fontSize: FontSize.small,
    color,
    background: bgColor,
    borderBottom: "solid 1px var(--bs-light-border-subtle)",
    padding: "0.3em 1em",
    display: hidden ? "none" : "grid"
  }}
    >
      <i class=${ApplicationIcons.logging[type]} />
      ${message}
      <button
        title="Close"
        style=${{
    fontSize: FontSize["title-secondary"],
    margin: "0",
    padding: "0",
    color: "var(--bs-" + type + "-text-emphasis)",
    height: FontSize["title-secondary"],
    lineHeight: FontSize["title-secondary"]
  }}
        class="btn"
        onclick=${() => {
    setHidden(true);
  }}
      >
        <i class=${ApplicationIcons.close}></i>
      </button>
    </div>
  `;
};
const LargeModal = (props) => {
  const {
    id,
    title,
    detail,
    detailTools,
    footer,
    onkeyup,
    visible,
    onHide,
    showProgress,
    children,
    initialScrollPositionRef,
    setInitialScrollPosition,
    warning,
    warningHidden,
    setWarningHidden
  } = props;
  const modalFooter = footer ? m$1`<div class="modal-footer">${footer}</div>` : "";
  const scrollRef = A();
  y(() => {
    if (scrollRef.current) {
      setTimeout(() => {
        if (scrollRef.current.scrollTop !== (initialScrollPositionRef == null ? void 0 : initialScrollPositionRef.current)) {
          scrollRef.current.scrollTop = initialScrollPositionRef == null ? void 0 : initialScrollPositionRef.current;
        }
      }, 0);
    }
  }, []);
  const onScroll = q(
    (e2) => {
      setInitialScrollPosition(e2.srcElement.scrollTop);
    },
    [setInitialScrollPosition]
  );
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
      onclick=${() => {
    onHide();
  }}
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
    style=${{
    borderRadius: "var(--bs-border-radius)",
    display: visible ? "block" : "none"
  }}
    tabindex=${visible ? 0 : void 0}
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
        <${ProgressBar}
          animating=${showProgress}
          containerStyle=${{
    marginBottom: "-2px",
    backgroundColor: "var(--bs-body-bg)"
  }}
        />

        ${warning ? m$1`<${MessageBand}
              message=${warning}
              hidden=${warningHidden}
              setHidden=${setWarningHidden}
              type="warning"
            />` : ""}
        <div class="modal-body" ref=${scrollRef} onscroll=${onScroll}>
          ${children}
        </div>
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
function escapeSelector(id) {
  return id.replace(/([ #.;,?!+*~'":^$[\]()=>|/\\])/g, "\\$1");
}
const isVscode = () => {
  const bodyEl = document.querySelector("body");
  return !!bodyEl.getAttributeNames().find((attr) => {
    return attr.includes("data-vscode-");
  });
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
  var _a2, _b2, _c;
  if (!sampleDescriptor) {
    return "";
  }
  const scoreInput = inputString(sample.input);
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
                markdown=${answer}
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

      ${explanation && explanation !== answer ? m$1` <table
            class="table"
            style=${{ width: "100%", marginBottom: "0" }}
          >
            <thead>
              <tr>
                <th
                  style=${{
    paddingBottom: "0",
    paddingLeft: "0",
    ...labelStyle,
    fontWeight: "400"
  }}
                >
                  Explanation
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style=${{ paddingLeft: "0" }}>
                  <${MarkdownDiv}
                    markdown=${arrayToString(explanation)}
                    style=${{ paddingLeft: "0" }}
                    class="no-last-para-padding"
                  />
                </td>
              </tr>
            </tbody>
          </table>` : ""}
      ${((_a2 = sample == null ? void 0 : sample.score) == null ? void 0 : _a2.metadata) && Object.keys((_b2 = sample == null ? void 0 : sample.score) == null ? void 0 : _b2.metadata).length > 0 ? m$1` <table
            class="table"
            style=${{ width: "100%", marginBottom: "0" }}
          >
            <thead>
              <tr>
                <th
                  style=${{
    paddingBottom: "0",
    paddingLeft: "0",
    ...labelStyle,
    fontWeight: "400"
  }}
                >
                  Metadata
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style=${{ paddingLeft: "0" }}>
                  <${MetaDataView}
                    id="task-sample-score-metadata"
                    classes="tab-pane"
                    entries="${(_c = sample == null ? void 0 : sample.score) == null ? void 0 : _c.metadata}"
                    style=${{ marginTop: "1em" }}
                  />
                </td>
              </tr>
            </tbody>
          </table>` : ""}
    </div>
  `;
};
const EventPanel = ({
  id,
  classes,
  title,
  subTitle,
  text: text2,
  icon,
  titleColor,
  collapse,
  style,
  titleStyle,
  children
}) => {
  const hasCollapse = collapse !== void 0;
  const [collapsed, setCollapsed] = h(!!collapse);
  const [selectedNav, setSelectedNav] = h("");
  const filteredArrChildren = T(() => {
    const arrChildren = Array.isArray(children) ? children : [children];
    return arrChildren.filter((child) => !!child);
  }, [children]);
  y(() => {
    setSelectedNav(pillId(0));
  }, [filteredArrChildren]);
  const pillId = (index) => {
    return `${id}-nav-pill-${index}`;
  };
  const gridColumns2 = [];
  if (hasCollapse) {
    gridColumns2.push("minmax(0, max-content)");
  }
  if (icon) {
    gridColumns2.push("max-content");
  }
  gridColumns2.push("minmax(0, max-content)");
  if (subTitle) {
    gridColumns2.push("minmax(0, max-content)");
  }
  gridColumns2.push("auto");
  gridColumns2.push("minmax(0, max-content)");
  gridColumns2.push("minmax(0, max-content)");
  const titleEl = title || icon || filteredArrChildren.length > 1 ? m$1`<div
          title=${subTitle}
          style=${{
    display: "grid",
    gridTemplateColumns: gridColumns2.join(" "),
    columnGap: "0.3em",
    fontSize: FontSize.small,
    cursor: hasCollapse ? "pointer" : void 0
  }}
        >
          ${hasCollapse ? m$1`<i
                onclick=${() => {
    setCollapsed(!collapsed);
  }}
                class=${collapsed ? ApplicationIcons.chevron.right : ApplicationIcons.chevron.down}
              />` : ""}
          ${icon ? m$1`<i
                class=${icon || ApplicationIcons.metadata}
                style=${{
    ...TextStyle.secondary,
    color: titleColor ? titleColor : "",
    ...titleStyle
  }}
                onclick=${() => {
    setCollapsed(!collapsed);
  }}
              />` : ""}
          <div
            style=${{
    ...TextStyle.label,
    ...TextStyle.secondary,
    color: titleColor ? titleColor : "",
    ...titleStyle
  }}
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
            style=${{
    justifySelf: "end",
    ...TextStyle.secondary,
    marginRight: "0.2em"
  }}
            onclick=${() => {
    setCollapsed(!collapsed);
  }}
          >
            ${collapsed ? text2 : ""}
          </div>
          <div
            style=${{
    justifySelf: "end",
    display: "flex",
    flexDirection: "columns"
  }}
          >
            ${(!hasCollapse || !collapsed) && filteredArrChildren && filteredArrChildren.length > 1 ? m$1` <${EventNavs}
                  navs=${filteredArrChildren.map((child, index) => {
    var _a2;
    const defaultTitle = `Tab ${index}`;
    const title2 = child && typeof child === "object" ? ((_a2 = child["props"]) == null ? void 0 : _a2.name) || defaultTitle : defaultTitle;
    return {
      id: `eventpanel-${id}-${index}`,
      title: title2,
      target: pillId(index)
    };
  })}
                  selectedNav=${selectedNav}
                  setSelectedNav=${setSelectedNav}
                />` : ""}
          </div>
        </div>` : "";
  const card = m$1` <div
    id=${id}
    style=${{
    padding: "0.625rem",
    marginBottom: "0.625rem",
    border: "solid 1px var(--bs-light-border-subtle)",
    borderRadius: "var(--bs-border-radius)",
    ...style
  }}
    class=${classes || void 0}
  >
    ${titleEl}
    <div
      class="tab-content"
      style=${{
    padding: "0",
    display: !hasCollapse || !collapsed ? "inherit" : "none"
  }}
    >
      ${filteredArrChildren == null ? void 0 : filteredArrChildren.map((child, index) => {
    const id2 = pillId(index);
    return m$1`<div
          id=${id2}
          class="tab-pane show ${id2 === selectedNav ? "active" : ""}"
        >
          ${child}
        </div>`;
  })}
    </div>
  </div>`;
  return card;
};
const EventNavs = ({ navs, selectedNav, setSelectedNav }) => {
  return m$1`<ul
    class="nav nav-pills card-header-pills"
    style=${{ marginRight: "0" }}
    role="tablist"
    aria-orientation="horizontal"
  >
    ${navs.map((nav, index) => {
    return m$1`<${EventNav}
        active=${index === 0}
        id=${nav.id}
        target=${nav.target}
        title=${nav.title}
        selectedNav=${selectedNav}
        setSelectedNav=${setSelectedNav}
      />`;
  })}
  </ul>`;
};
const EventNav = ({ target, title, selectedNav, setSelectedNav }) => {
  const active = target === selectedNav;
  return m$1`<li class="nav-item">
    <button
      type="button"
      role="tab"
      aria-controls=${target}
      aria-selected=${active}
      style=${{
    minWidth: "4rem",
    ...TextStyle.label,
    fontSize: FontSize.small,
    padding: "0.1rem  0.6rem",
    borderRadius: "var(--bs-border-radius)"
  }}
      class="nav-link ${active ? "active " : ""}"
      onclick=${() => {
    setSelectedNav(target);
  }}
    >
      ${title}
    </button>
  </li>`;
};
const MetaDataGrid = ({ id, entries, classes, style, plain }) => {
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
        <${RenderedContent} id=${id2} entry=${entry} />
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
const isNumeric = (n2) => {
  return !isNaN(parseFloat(n2)) && isFinite(n2);
};
const toArray = (val) => {
  if (Array.isArray(val)) {
    return val;
  } else {
    return [val];
  }
};
const SampleInitEventView = ({ id, event, style }) => {
  const stateObj = event.state;
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
      <pre style=${{ background: "var(--bs-light)", borderRadius: "var(--bs-border-radius)" }}><code class="sourceCode" >${event.sample.setup}</code></pre>
      </${EventSection}>
  `);
  }
  return m$1`
  <${EventPanel} id=${id} style=${style} title="Sample" icon=${ApplicationIcons.sample} subTitle=${formatDateTime(new Date(event.timestamp))}>
    <div name="Sample" style=${{ margin: "1em 0em" }}>
      <${ChatView} messages=${stateObj["messages"]}/>
      <div>
        ${event.sample.choices ? event.sample.choices.map((choice, index) => {
    return m$1`<div>
                  ${String.fromCharCode(65 + index)}) ${choice}
                </div>`;
  }) : ""}
        ${sections.length > 0 ? m$1`
                <div
                  style=${{
    display: "flex",
    flexWrap: "wrap",
    gap: "1em",
    overflowWrap: "break-word"
  }}
                >
                  ${sections}
                </div>
              ` : ""}
        <${EventSection} title="Target">
          ${toArray(event.sample.target).map((target) => {
    return m$1`<div>${target}</div>`;
  })}
        </${EventSection}>
      </div>
    </div>
    ${event.sample.metadata && Object.keys(event.sample.metadata).length > 0 ? m$1`<${MetaDataGrid} name="Metadata" style=${{ margin: "0.5em 0" }} entries=${event.sample.metadata} />` : ""}

  </${EventPanel}>`;
};
const system_msg_added_sig = {
  type: "system_message",
  signature: {
    remove: ["/messages/0/source"],
    replace: ["/messages/0/role", "/messages/0/content"],
    add: ["/messages/1"]
  },
  render: (_changes, resolvedState) => {
    const message = resolvedState["messages"][0];
    return m$1`<${ChatView}
      id="system_msg_event_preview"
      messages=${[message]}
    />`;
  }
};
const kToolPattern = "/tools/(\\d+)";
const use_tools = {
  type: "use_tools",
  signature: {
    add: ["/tools/0"],
    replace: ["/tool_choice"],
    remove: []
  },
  render: (changes, resolvedState) => {
    return renderTools(changes, resolvedState);
  }
};
const add_tools = {
  type: "add_tools",
  signature: {
    add: [kToolPattern],
    replace: [],
    remove: []
  },
  render: (changes, resolvedState) => {
    return renderTools(changes, resolvedState);
  }
};
const renderTools = (changes, resolvedState) => {
  const toolIndexes = [];
  for (const change of changes) {
    const match2 = change.path.match(kToolPattern);
    if (match2) {
      toolIndexes.push(match2[1]);
    }
  }
  const toolName = (toolChoice) => {
    if (typeof toolChoice === "object" && toolChoice) {
      return toolChoice["name"];
    } else {
      return toolChoice;
    }
  };
  const toolsInfo = {};
  const hasToolChoice = changes.find((change) => {
    return change.path.startsWith("/tool_choice");
  });
  if (resolvedState.tool_choice && hasToolChoice) {
    toolsInfo["Tool Choice"] = toolName(resolvedState.tool_choice);
  }
  if (resolvedState.tools.length > 0) {
    if (toolIndexes.length === 0) {
      toolsInfo["Tools"] = m$1`<${Tools}
        toolDefinitions=${resolvedState.tools}
      />`;
    } else {
      const filtered = resolvedState.tools.filter((_2, index) => {
        return toolIndexes.includes(index.toString());
      });
      toolsInfo["Tools"] = m$1`<${Tools} toolDefinitions=${filtered} />`;
    }
  }
  return m$1`
    <div
      style=${{
    display: "grid",
    gridTemplateColumns: "max-content max-content",
    columnGap: "1rem",
    margin: "0"
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
};
const RenderableChangeTypes = [
  system_msg_added_sig,
  use_tools,
  add_tools
];
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
        const error2 = new Error(`${this.name} failed`);
        error2.noResult = true;
        throw error2;
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
const lengthMatrix = function(array1, array2, match2, context) {
  const len1 = array1.length;
  const len2 = array2.length;
  let x, y2;
  const matrix = new Array(len1 + 1);
  for (x = 0; x < len1 + 1; x++) {
    matrix[x] = new Array(len2 + 1);
    for (y2 = 0; y2 < len2 + 1; y2++) {
      matrix[x][y2] = 0;
    }
  }
  matrix.match = match2;
  for (x = 1; x < len1 + 1; x++) {
    for (y2 = 1; y2 < len2 + 1; y2++) {
      if (match2(array1, array2, x - 1, y2 - 1, context)) {
        matrix[x][y2] = matrix[x - 1][y2 - 1] + 1;
      } else {
        matrix[x][y2] = Math.max(matrix[x - 1][y2], matrix[x][y2 - 1]);
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
const get = function(array1, array2, match2, context) {
  const innerContext = context || {};
  const matrix = lengthMatrix(array1, array2, match2 || defaultMatch, innerContext);
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
const compare = {
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
  toRemove = toRemove.sort(compare.numerically);
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
  toInsert = toInsert.sort(compare.numericallyBy("index"));
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
  var _a2;
  if (!cachedDiffPatch) {
    let instance;
    if ((_a2 = options === null || options === void 0 ? void 0 : options.textDiff) === null || _a2 === void 0 ? void 0 : _a2.diffMatchPatch) {
      instance = new options.textDiff.diffMatchPatch();
    } else {
      if (!required) {
        return null;
      }
      const error2 = new Error("The diff-match-patch library was not provided. Pass the library in through the options or use the `jsondiffpatch/with-text-diffs` entry-point.");
      error2.diff_match_patch_not_found = true;
      throw error2;
    }
    cachedDiffPatch = {
      diff: function(txt1, txt2) {
        return instance.patch_toText(instance.patch_make(txt1, txt2));
      },
      patch: function(txt1, patch) {
        const results = instance.patch_apply(instance.patch_fromText(patch), txt1);
        for (let i = 0; i < results[1].length; i++) {
          if (!results[1][i]) {
            const error2 = new Error("text patch failed");
            error2.textPatchFailed = true;
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
  let i;
  let l2;
  let line2;
  let lineTmp;
  let header = null;
  const headerRegex = /^@@ +-(\d+),(\d+) +\+(\d+),(\d+) +@@$/;
  let lineHeader;
  const lines = delta.split("\n");
  for (i = 0, l2 = lines.length; i < l2; i++) {
    line2 = lines[i];
    const lineStart = line2.slice(0, 1);
    if (lineStart === "@") {
      header = headerRegex.exec(line2);
      lineHeader = i;
      lines[lineHeader] = "@@ -" + header[3] + "," + header[4] + " +" + header[1] + "," + header[2] + " @@";
    } else if (lineStart === "+") {
      lines[i] = "-" + lines[i].slice(1);
      if (lines[i - 1].slice(0, 1) === "+") {
        lineTmp = lines[i];
        lines[i] = lines[i - 1];
        lines[i - 1] = lineTmp;
      }
    } else if (lineStart === "-") {
      lines[i] = "+" + lines[i].slice(1);
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
  typeFormattterErrorFormatter(context, err2, delta, leftValue, key2, leftKey, movedFrom) {
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
    } catch (err2) {
      this.typeFormattterErrorFormatter(context, err2, delta, leftValue, key2, leftKey, movedFrom);
      if (typeof console !== "undefined" && console.error) {
        console.error(err2.stack);
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
    for (let i = 0, l2 = lines.length; i < l2; i++) {
      const line2 = lines[i];
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
  typeFormattterErrorFormatter(context, err2) {
    context.out(`<pre class="jsondiffpatch-error">${err2}</pre>`);
  }
  formatValue(context, value) {
    context.out(`<pre>${htmlEscape(JSON.stringify(value, null, 2))}</pre>`);
  }
  formatTextDiffString(context, value) {
    const lines = this.parseTextDiff(value);
    context.out('<ul class="jsondiffpatch-textdiff">');
    for (let i = 0, l2 = lines.length; i < l2; i++) {
      const line2 = lines[i];
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
function htmlEscape(text2) {
  let html = text2;
  const replacements = [
    [/&/g, "&amp;"],
    [/</g, "&lt;"],
    [/>/g, "&gt;"],
    [/'/g, "&apos;"],
    [/"/g, "&quot;"]
  ];
  for (let i = 0; i < replacements.length; i++) {
    html = html.replace(replacements[i][0], replacements[i][1]);
  }
  return html;
}
const adjustArrows = function jsondiffpatchHtmlFormatterAdjustArrows(nodeArg) {
  const node = nodeArg || document;
  const getElementText = ({ textContent, innerText }) => textContent || innerText;
  const eachByQuery = (el, query, fn2) => {
    const elems = el.querySelectorAll(query);
    for (let i = 0, l2 = elems.length; i < l2; i++) {
      fn2(elems[i]);
    }
  };
  const eachChildren = ({ children }, fn2) => {
    for (let i = 0, l2 = children.length; i < l2; i++) {
      fn2(children[i], i);
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
    } catch (err2) {
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
const StateDiffView = ({ before, after, style }) => {
  const state_diff = diff(sanitizeKeys(before), sanitizeKeys(after));
  const html_result = format(state_diff) || "Unable to render differences";
  return m$1`<div
    dangerouslySetInnerHTML=${{ __html: unescapeNewlines(html_result) }}
    style=${{ ...style }}
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
function sanitizeKeys(obj) {
  if (typeof obj !== "object" || obj === null) {
    return obj;
  }
  if (Array.isArray(obj)) {
    return obj.map(sanitizeKeys);
  }
  return Object.fromEntries(
    Object.entries(obj).map(([key2, value]) => [
      key2.replace(/</g, "&lt;").replace(/>/g, "&gt;"),
      sanitizeKeys(value)
    ])
  );
}
const StateEventView = ({ id, event, style }) => {
  const summary = summarizeChanges(event.changes);
  const [before, after] = synthesizeComparable(event.changes);
  const tabs = [
    m$1`<${StateDiffView}
      before=${before}
      after=${after}
      name="Diff"
      style=${{ margin: "1em 0em" }}
    />`
  ];
  const changePreview = generatePreview(event.changes, structuredClone(after));
  if (changePreview) {
    tabs.unshift(
      m$1`<div name="Summary" style=${{ margin: "1em 0em", width: "100%" }}>
        ${changePreview}
      </div>`
    );
  }
  const title = event.event === "state" ? "State Updated" : "Store Updated";
  return m$1`
  <${EventPanel} id=${id} title="${title}" subTitle=${formatDateTime(new Date(event.timestamp))} text=${tabs.length === 1 ? summary : void 0} collapse=${changePreview === void 0 ? true : void 0} style=${style}>
    ${tabs}
  </${EventPanel}>`;
};
const generatePreview = (changes, resolvedState) => {
  const results = [];
  for (const changeType of RenderableChangeTypes) {
    const requiredMatchCount = changeType.signature.remove.length + changeType.signature.replace.length + changeType.signature.add.length;
    let matchingOps = 0;
    for (const change of changes) {
      if (changeType.signature[change.op] && changeType.signature[change.op].length > 0) {
        changeType.signature[change.op].forEach((signature) => {
          if (change.path.match(signature)) {
            matchingOps++;
          }
        });
      }
    }
    if (matchingOps === requiredMatchCount) {
      results.push(changeType.render(changes, resolvedState));
      break;
    }
  }
  return results.length > 0 ? results : void 0;
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
const synthesizeComparable = (changes) => {
  const before = {};
  const after = {};
  for (const change of changes) {
    switch (change.op) {
      case "add":
        initializeArrays(before, change.path);
        initializeArrays(after, change.path);
        setPath(after, change.path, change.value);
        break;
      case "copy":
        setPath(before, change.path, change.value);
        setPath(after, change.path, change.value);
        break;
      case "move":
        setPath(before, change.from, change.value);
        setPath(after, change.path, change.value);
        break;
      case "remove":
        setPath(before, change.path, change.value);
        break;
      case "replace":
        setPath(before, change.path, change.replaced);
        setPath(after, change.path, change.value);
        break;
    }
  }
  return [before, after];
};
function setPath(target, path, value) {
  const keys = parsePath(path);
  let current = target;
  for (let i = 0; i < keys.length - 1; i++) {
    const key2 = keys[i];
    if (!(key2 in current)) {
      current[key2] = isArrayIndex(keys[i + 1]) ? [] : {};
    }
    current = current[key2];
  }
  const lastKey = keys[keys.length - 1];
  current[lastKey] = value;
}
function initializeArrays(target, path) {
  const keys = parsePath(path);
  let current = target;
  for (let i = 0; i < keys.length - 1; i++) {
    const key2 = keys[i];
    const nextKey = keys[i + 1];
    if (isArrayIndex(nextKey)) {
      current[key2] = initializeArray(current[key2], nextKey);
    } else {
      current[key2] = initializeObject(current[key2]);
    }
    current = current[key2];
  }
  const lastKey = keys[keys.length - 1];
  if (isArrayIndex(lastKey)) {
    initializeArray(current, lastKey);
  }
}
function parsePath(path) {
  return path.split("/").filter(Boolean);
}
function isArrayIndex(key2) {
  return /^\d+$/.test(key2);
}
function initializeArray(current, nextKey) {
  if (!Array.isArray(current)) {
    current = [];
  }
  const nextKeyIndex = parseInt(nextKey, 10);
  while (current.length < nextKeyIndex) {
    current.push("");
  }
  return current;
}
function initializeObject(current) {
  return current ?? {};
}
const StepEventView = ({ event, children, style }) => {
  const descriptor = stepDescriptor(event);
  const title = descriptor.name || `${event.type ? event.type + ": " : "Step: "}${event.name}`;
  const text2 = summarize(children);
  return m$1`<${EventPanel}
    id=${`step-${event.name}`}
    classes="transcript-step"
    title="${title}"
    subTitle=${formatDateTime(new Date(event.timestamp))}
    icon=${descriptor.icon}
    style=${{ ...descriptor.style, ...style }}
    titleStyle=${{ ...descriptor.titleStyle }}
    collapse=${false}
    text=${text2}
  >
    <${TranscriptComponent}
      id=${`step-${event.name}-transcript`}
      eventNodes=${children}
    />
  </EventPanel>
  `;
};
const summarize = (children) => {
  if (children.length === 0) {
    return "(no events)";
  }
  const formatEvent = (event, count) => {
    if (count === 1) {
      return `${count} ${event} event`;
    } else {
      return `${count} ${event} events`;
    }
  };
  const typeCount = {};
  children.forEach((child) => {
    const currentCount = typeCount[child.event.event] || 0;
    typeCount[child.event.event] = currentCount + 1;
  });
  const numberOfTypes = Object.keys(typeCount).length;
  if (numberOfTypes < 3) {
    return Object.keys(typeCount).map((key2) => {
      return formatEvent(key2, typeCount[key2]);
    }).join(", ");
  }
  if (children.length === 1) {
    return "1 event";
  } else {
    return `${children.length} events`;
  }
};
const rootStepStyle = {};
const rootTitleStyle = {
  fontWeight: "600"
};
const stepDescriptor = (event) => {
  const rootStepDescriptor = {
    style: rootStepStyle,
    endSpace: true,
    titleStyle: rootTitleStyle
  };
  if (event.type === "solver") {
    switch (event.name) {
      case "chain_of_thought":
        return {
          ...rootStepDescriptor
        };
      case "generate":
        return {
          ...rootStepDescriptor
        };
      case "self_critique":
        return {
          ...rootStepDescriptor
        };
      case "system_message":
        return {
          ...rootStepDescriptor
        };
      case "use_tools":
        return {
          ...rootStepDescriptor
        };
      case "multiple_choice":
        return {
          ...rootStepDescriptor
        };
      default:
        return {
          ...rootStepDescriptor
        };
    }
  } else if (event.type === "scorer") {
    return {
      ...rootStepDescriptor
    };
  } else {
    switch (event.name) {
      case "sample_init":
        return {
          ...rootStepDescriptor,
          name: "Sample Init"
        };
      default:
        return {
          style: {},
          endSpace: false,
          titleStyle: {}
        };
    }
  }
};
const SubtaskEventView = ({ id, event, style, depth }) => {
  const transcript = event.events.length > 0 ? m$1`<${TranscriptView}
          id="${id}-subtask"
          name="Transcript"
          events=${event.events}
          depth=${depth + 1}
        />` : "";
  const body = event.type === "fork" ? m$1`
          <div title="Summary" style=${{ width: "100%", margin: "0.5em 0em" }}>
            <div style=${{ ...TextStyle.label }}>Inputs</div>
            <div style=${{ marginBottom: "1em" }}>
              <${Rendered} values=${event.input} />
            </div>
            <div style=${{ ...TextStyle.label }}>Transcript</div>
            ${transcript}
          </div>
        ` : m$1`
          <${SubtaskSummary}
            name="Summary"
            input=${event.input}
            result=${event.result}
          />
          ${transcript}
        `;
  const type = event.type === "fork" ? "Fork" : "Subtask";
  return m$1`
    <${EventPanel} id=${id} title="${type}: ${event.name}" subTitle=${formatDateTime(new Date(event.timestamp))} style=${style} collapse=${false}>
      ${body}
    </${EventPanel}>`;
};
const SubtaskSummary = ({ input, result }) => {
  result = typeof result === "object" ? result : { result };
  return m$1` <div
    style=${{
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) max-content minmax(0, 1fr)",
    columnGap: "1em",
    margin: "0.5em 0"
  }}
  >
    <div style=${{ ...TextStyle.label }}>Input</div>
    <div style=${{ fontSize: FontSize.large, padding: "0 2em" }}></div>
    <div style=${{ ...TextStyle.label }}>Output</div>
    <${Rendered} values=${input} />
    <div style=${{ fontSize: FontSize["title-secondary"], padding: "0 2em" }}>
      <i class="${ApplicationIcons.arrows.right}" />
    </div>
    <div>
      <${Rendered} values=${result} />
    </div>
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
const ModelTokenTable = ({ model_usage, style }) => {
  return m$1`
  <${TokenTable} style=${style}>
    <${TokenHeader}/>
    <tbody>
    ${Object.keys(model_usage).map((key2) => {
    return m$1`<${TokenRow} model=${key2} usage=${model_usage[key2]} />`;
  })}
    </tbody>
  </${TokenTable}>
  `;
};
const TokenTable = ({ style, children }) => {
  return m$1`<table
    class="table table-sm"
    style=${{
    width: "100%",
    fontSize: FontSize.smaller,
    marginTop: "0.7rem",
    ...style
  }}
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
const UsageCard = ({ stats }) => {
  if (!stats) {
    return "";
  }
  const totalDuration = formatDuration(
    new Date(stats.started_at),
    new Date(stats.completed_at)
  );
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
  if (!usage) {
    return "";
  }
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
const ModelEventView = ({ id, event, style }) => {
  var _a2, _b2;
  const totalUsage = (_a2 = event.output.usage) == null ? void 0 : _a2.total_tokens;
  const subtitle = totalUsage ? `(${formatNumber(totalUsage)} tokens)` : "";
  const outputMessages = (_b2 = event.output.choices) == null ? void 0 : _b2.map((choice) => {
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
  const userMessages = [];
  for (const msg of event.input.slice().reverse()) {
    if (msg.role === "user") {
      userMessages.push(msg);
    } else {
      break;
    }
  }
  return m$1`
  <${EventPanel} id=${id} title="Model Call: ${event.model} ${subtitle}"  subTitle=${formatDateTime(new Date(event.timestamp))} icon=${ApplicationIcons.model} style=${style}>
  
    <div name="Summary" style=${{ margin: "0.5em 0" }}>
    <${ChatView}
      id="${id}-model-output"
      messages=${[...userMessages, ...outputMessages || []]}
      style=${{ paddingTop: "1em" }}
      numbered=${false}
      toolCallStyle="compact"
      />
    </div>

    <div name="All" style=${{ margin: "0.5em 0" }}>

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

    ${event.call ? m$1`<${APIView} name="API" call=${event.call} style=${{ margin: "0.5em 0", width: "100%" }} />` : ""}
   
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
  y(() => {
    if (codeRef.current) {
      codeRef.current.innerHTML = Prism$1.highlight(
        sourceCode,
        Prism$1.languages.javascript,
        "javacript"
      );
    }
  }, [codeRef.current, contents]);
  return m$1`<div>
    <pre
      style=${{
    background: "var(--bs-light)",
    width: "100%",
    padding: "0.5em",
    borderRadius: "var(--bs-border-radius)"
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
    gridTemplateColumns: "max-content auto",
    columnGap: "1em",
    rowGap: "0.5em"
  }}
  >
    ${toolEls}
  </div>`;
};
const EventRow = ({ title, icon, style, children }) => {
  const contentEl = title ? m$1`<div
        style=${{
    marginLeft: "0.5em",
    display: "grid",
    gridTemplateColumns: "max-content max-content minmax(0, 1fr)",
    columnGap: "0.5em",
    fontSize: FontSize.small
  }}
      >
        <i class=${icon || ApplicationIcons.metadata} />
        <div style=${{ ...TextStyle.label }}>${title}</div>
        <div>${children}</div>
      </div>` : "";
  const card = m$1` <div
    class="card"
    style=${{
    padding: "0.4em",
    marginBottom: "0.4em",
    border: "solid 1px var(--bs-light-border-subtle)",
    borderRadius: "var(--bs-border-radius)",
    ...style
  }}
  >
    ${contentEl}
  </div>`;
  return card;
};
const LoggerEventView = ({ id, event, style }) => {
  return m$1`
  <${EventRow} 
    id=${id}
    title=${event.message.level} 
    icon=${ApplicationIcons.logging[event.message.level.toLowerCase()]}  
    style=${style}
  >
  <div
    style=${{ width: "100%", display: "grid", gridTemplateColumns: "1fr max-content", columnGap: "1em", fontSize: FontSize.base }}
  >
    <div style=${{ fontSize: FontSize.smaller }}>${event.message.message}</div>
    <div style=${{ fontSize: FontSize.smaller, ...TextStyle.secondary }}>${event.message.filename}:${event.message.lineno}</div>
  </div>
  </${EventRow}>`;
};
const kPrismRenderMaxSize = 25e4;
const JSONPanel = ({ id, json, data, simple, style }) => {
  const sourceCode = json || JSON.stringify(data, void 0, 2);
  const codeRef = A();
  if (codeRef.current) {
    if (sourceCode.length < kPrismRenderMaxSize) {
      codeRef.current.innerHTML = Prism$1.highlight(
        sourceCode,
        Prism$1.languages.javascript,
        "javacript"
      );
    } else {
      const textNode = document.createTextNode(sourceCode);
      codeRef.current.innerText = "";
      codeRef.current.appendChild(textNode);
    }
  }
  return m$1`<div>
    <pre
      style=${{
    background: simple ? void 0 : "var(--bs-light)",
    width: "100%",
    padding: "0.5em",
    borderRadius: simple ? void 0 : "var(--bs-border-radius)",
    ...style
  }}
    >
    <code 
      id=${id}
      ref=${codeRef}
      class="sourceCode-json" 
      style=${{
    fontSize: FontSize.small,
    whiteSpace: "pre-wrap",
    wordWrap: "anywhere"
  }}>
    </code>
    </pre>
  </div>`;
};
const InfoEventView = ({ id, event, style }) => {
  const panels = [];
  if (typeof event.data === "string") {
    panels.push(
      m$1`<${MarkdownDiv}
        markdown=${event.data}
        style=${{ margin: "0.5em 0" }}
      />`
    );
  } else {
    panels.push(
      m$1`<${JSONPanel} data=${event.data} style=${{ margin: "0.5em 0" }} />`
    );
  }
  return m$1`
  <${EventPanel} id=${id} title="Info" subTitle=${formatDateTime(new Date(event.timestamp))} icon=${ApplicationIcons.info} style=${style}>
    ${panels}
  </${EventPanel}>`;
};
const ScoreEventView = ({ id, event, style }) => {
  const resolvedTarget = event.target ? Array.isArray(event.target) ? event.target.join("\n") : event.target : void 0;
  return m$1`
  <${EventPanel} id=${id} title="Score" subTitle=${formatDateTime(new Date(event.timestamp))} icon=${ApplicationIcons.scorer} style=${style}>
  
    <div
      name="Explanation"
      style=${{ display: "grid", gridTemplateColumns: "max-content auto", columnGap: "1em", margin: "0.5em 0" }}
    >
      ${event.target ? m$1` <div
                style=${{
    gridColumn: "1 / -1",
    borderBottom: "solid 1px var(--bs-light-border-subtle"
  }}
              ></div>
              <div style=${{ ...TextStyle.label }}>Target</div>
              <div><${MarkdownDiv} markdown=${resolvedTarget} /></div>` : ""}
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Answer</div>
      <div><${MarkdownDiv} markdown=${event.score.answer}/></div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Explanation</div>
      <div><${MarkdownDiv} markdown=${event.score.explanation}/></div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Score</div>  
      <div>${renderScore(event.score.value)}</div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
    </div>
    ${event.score.metadata ? m$1`<div name="Metadata">
            <${MetaDataGrid}
              entries=${event.score.metadata}
              compact=${true}
              style=${{ margin: "0.5em 0" }}
            />
          </div>` : void 0}
  </${EventPanel}>`;
};
const renderScore = (value) => {
  if (Array.isArray(value)) {
    return m$1`<${MetaDataGrid} entries=${value} />`;
  } else if (typeof value === "object") {
    return m$1`<${MetaDataGrid} entries=${value} />`;
  } else {
    return value;
  }
};
const ApprovalEventView = ({ id, event, style }) => {
  return m$1`
  <${EventRow}
      id=${id}
      title="${decisionLabel(event.decision)}"
      icon=${decisionIcon(event.decision)}  
      style=${style}
    >
    ${event.explanation}
  </${EventRow}>`;
};
const decisionLabel = (decision) => {
  switch (decision) {
    case "approve":
      return "Approved";
    case "reject":
      return "Rejected";
    case "terminate":
      return "Terminated";
    case "escalate":
      return "Escalated";
    case "modify":
      return "Modified";
    default:
      return decision;
  }
};
const decisionIcon = (decision) => {
  switch (decision) {
    case "approve":
      return ApplicationIcons.approvals.approve;
    case "reject":
      return ApplicationIcons.approvals.reject;
    case "terminate":
      return ApplicationIcons.approvals.terminate;
    case "escalate":
      return ApplicationIcons.approvals.escalate;
    case "modify":
      return ApplicationIcons.approvals.modify;
    default:
      return ApplicationIcons.approve;
  }
};
const ToolEventView = ({ id, event, style, depth }) => {
  const { input, functionCall, inputType } = resolveToolInput(
    event.function,
    event.arguments
  );
  const approvalEvent = event.events.find((e2) => {
    return e2.event === "approval";
  });
  const title = `Tool: ${event.function}`;
  return m$1`
  <${EventPanel} id=${id} title="${title}" subTitle=${formatDateTime(new Date(event.timestamp))} icon=${ApplicationIcons.solvers.use_tools} style=${style}>  
  <div name="Summary" style=${{ margin: "0.5em 0" }}>
    <${ToolCallView}
      functionCall=${functionCall}
      input=${input}
      inputType=${inputType}
      output=${event.result}
      mode="compact"
      view=${event.view}
      />
      ${approvalEvent ? m$1`<${ApprovalEventView}
              id="${id}-approval"
              event=${approvalEvent}
              style=${{ border: "none", padding: 0, marginBottom: 0 }}
            />` : ""}
  </div>
    ${event.events.length > 0 ? m$1`<${TranscriptView}
            id="${id}-subtask"
            name="Transcript"
            events=${event.events}
            depth=${depth + 1}
          />` : ""}
  </${EventPanel}>`;
};
const ErrorEventView = ({ id, event, style }) => {
  return m$1`
  <${EventPanel} id=${id} title="Error" subTitle=${formatDateTime(new Date(event.timestamp))} icon=${ApplicationIcons.error} style=${style}>
    <${ANSIDisplay} output=${event.error.traceback_ansi} style=${{ fontSize: "clamp(0.5rem, calc(0.25em + 1vw), 0.8rem)", margin: "0.5em 0" }}/>
  </${EventPanel}>`;
};
const InputEventView = ({ id, event, style }) => {
  return m$1`
  <${EventPanel} id=${id} title="Input" subTitle=${formatDateTime(new Date(event.timestamp))} icon=${ApplicationIcons.input} style=${style}>
    <${ANSIDisplay} output=${event.input_ansi} style=${{ fontSize: "clamp(0.4rem, 1.15vw, 0.9rem)", ...style }}/>
  </${EventPanel}>`;
};
const SampleLimitEventView = ({ id, event, style }) => {
  const resolve_title = (type) => {
    switch (type) {
      case "context":
        return "Context Limit Exceeded";
      case "time":
        return "Time Limit Execeeded";
      case "message":
        return "Message Limit Exceeded";
      case "token":
        return "Token Limit Exceeded";
      case "operator":
        return "Operator Canceled";
    }
  };
  const resolve_icon = (type) => {
    switch (type) {
      case "context":
        return ApplicationIcons.limits.context;
      case "time":
        return ApplicationIcons.limits.time;
      case "message":
        return ApplicationIcons.limits.messages;
      case "token":
        return ApplicationIcons.limits.tokens;
      case "operator":
        return ApplicationIcons.limits.operator;
    }
  };
  const title = resolve_title(event.type);
  const icon = resolve_icon(event.type);
  return m$1`
  <${EventPanel} id=${id} title=${title} icon=${icon} style=${style}>
    ${event.message}
  </${EventPanel}>`;
};
class EventNode {
  /**
   * Create an EventNode.
   * @param { import("../../types/log").SampleInitEvent | import("../../types/log").SampleLimitEvent | import("../../types/log").StateEvent | import("../../types/log").StoreEvent | import("../../types/log").ModelEvent | import("../../types/log").LoggerEvent | import("../../types/log").InfoEvent | import("../../types/log").StepEvent | import("../../types/log").SubtaskEvent| import("../../types/log").ScoreEvent | import("../../types/log").ToolEvent | import("../../types/log").InputEvent | import("../../types/log").ErrorEvent | import("../../types/log").ApprovalEvent } event - This event.
   * @param {number} depth - the depth of this item
   */
  constructor(event, depth) {
    this.event = event;
    this.children = [];
    this.depth = depth;
  }
}
const TranscriptView = ({ id, events, depth = 0 }) => {
  const resolvedEvents = fixupEventStream(events);
  const eventNodes = treeifyEvents(resolvedEvents, depth);
  return m$1` <${TranscriptComponent} id=${id} eventNodes=${eventNodes} /> `;
};
const TranscriptComponent = ({ id, eventNodes, style }) => {
  const rows = eventNodes.map((eventNode, index) => {
    const toggleStyle = {};
    if (eventNode.depth % 2 == 0) {
      toggleStyle.backgroundColor = "var(--bs-light-bg-subtle)";
    } else {
      toggleStyle.backgroundColor = "var(--bs-body-bg)";
    }
    if (index === eventNodes.length - 1) {
      toggleStyle.marginBottom = "0";
    } else if (eventNode.depth === 0) {
      toggleStyle.marginBottom = "1.5em";
    }
    const row = m$1`
      <${RenderedEventNode}
        id=${`${id}-event${index}`}
        node=${eventNode}
        style=${{
      ...toggleStyle,
      ...style
    }}
      />
    `;
    return row;
  });
  return m$1`<div
    id=${id}
    key=${id}
    style=${{
    fontSize: FontSize.small,
    display: "grid",
    margin: "0.5em 0 0 0",
    width: "100%"
  }}
  >
    ${rows}
  </div>`;
};
const RenderedEventNode = ({ id, node, style }) => {
  switch (node.event.event) {
    case "sample_init":
      return m$1`<${SampleInitEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;
    case "sample_limit":
      return m$1`<${SampleLimitEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;
    case "info":
      return m$1`<${InfoEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;
    case "logger":
      return m$1`<${LoggerEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;
    case "model":
      return m$1`<${ModelEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;
    case "score":
      return m$1`<${ScoreEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;
    case "state":
      return m$1`<${StateEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;
    case "step":
      return m$1`<${StepEventView}
        id=${id}
        event=${node.event}
        children=${node.children}
        style=${style}
      />`;
    case "store":
      return m$1`<${StateEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;
    case "subtask":
      return m$1`<${SubtaskEventView}
        id=${id}
        event=${node.event}
        style=${style}
        depth=${node.depth}
      />`;
    case "tool":
      return m$1`<${ToolEventView}
        id=${id}
        event=${node.event}
        style=${style}
        depth=${node.depth}
      />`;
    case "input":
      return m$1`<${InputEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;
    case "error":
      return m$1`<${ErrorEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;
    case "approval":
      return m$1`<${ApprovalEventView}
        id=${id}
        event=${node.event}
        style=${style}
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
      name: "sample_init",
      pending: false
    });
    fixedUp.splice(initEventIndex + 2, 0, {
      timestamp: initEvent.timestamp,
      event: "step",
      action: "end",
      type: null,
      name: "sample_init",
      pending: false
    });
  }
  return fixedUp;
};
function treeifyEvents(events, depth) {
  const rootNodes = [];
  const stack2 = [];
  const pushNode = (event) => {
    const node = new EventNode(event, stack2.length + depth);
    if (stack2.length > 0) {
      const parentNode = stack2[stack2.length - 1];
      parentNode.children.push(node);
    } else {
      rootNodes.push(node);
    }
    return node;
  };
  events.forEach((event) => {
    if (event.event === "step" && event.action === "begin") {
      const node = pushNode(event);
      stack2.push(node);
    } else if (event.event === "step" && event.action === "end") {
      if (stack2.length > 0) {
        stack2.pop();
      }
    } else {
      pushNode(event);
    }
  });
  return rootNodes;
}
const SampleTranscript = ({ id, evalEvents }) => {
  return m$1`<${TranscriptView} id=${id} events=${evalEvents} />`;
};
const SampleError = ({ message, align, style }) => {
  align = align || "center";
  return m$1`<div
    style=${{
    color: "var(--bs-danger)",
    display: "grid",
    gridTemplateColumns: "1fr",
    alignContent: align,
    justifyItems: "center",
    ...style
  }}
  >
    <i
      class=${ApplicationIcons.error}
      style=${{
    fontSize: FontSize.small,
    lineHeight: FontSize.small,
    height: FontSize.small
  }}
    />
    <div style=${{ maxWidth: "300px", ...ApplicationStyles.lineClamp(2) }}>
      ${errorType(message)}
    </div>
  </div>`;
};
const FlatSampleError = ({ message, style }) => {
  return m$1`<div
    style=${{
    color: "var(--bs-danger)",
    display: "grid",
    gridTemplateColumns: "max-content max-content",
    columnGap: "0.2em",
    ...style
  }}
  >
    <i
      class=${ApplicationIcons.error}
      style=${{
    fontSize: FontSize.base,
    lineHeight: FontSize.base,
    height: FontSize.base
  }}
    />
    <div
      style=${{
    fontSize: FontSize.base,
    lineHeight: FontSize.base,
    height: FontSize.base
  }}
    >
      ${errorType(message)}
    </div>
  </div>`;
};
const errorType = (message) => {
  if (!message) {
    return "Error";
  }
  if (message.includes("(")) {
    return message.split("(")[0];
  }
  return "Error";
};
const printHtml = (html, css) => {
  const printWindow = window.open("", "", "height=600,width=800");
  printWindow.document.write("<html><head><title>Print</title>");
  printWindow.document.write(`
          <link rel="stylesheet" crossorigin="" href="./assets/index.css">
          <style>
            @media print {
              ${css}
            }
          </style>
        `);
  printWindow.document.write("</head><body>");
  printWindow.document.write(html);
  printWindow.document.write("</body></html>");
  printWindow.document.close();
  printWindow.onload = function() {
    printWindow.focus();
    printWindow.print();
    printWindow.close();
  };
};
const printHeadingHtml = () => {
  const task = document.getElementById("task-title").innerText;
  const model = document.getElementById("task-model").innerText;
  const time = document.getElementById("task-created").innerText;
  const headingHtml = `
<div style="display: grid; grid-template-columns: repeat(3, 1fr); column-gap: 0.5em; margin-bottom: 2em; justify-content: space-between; border-bottom: solid 1px silver;">
<div style="font-weight: 600">${task}</div>
<div style="text-align: center;">${model}</div>
<div style="text-align: right;">${time}</div>
</div>`;
  return headingHtml;
};
const kEvalWorkspaceTabId = "eval-tab";
const kJsonWorkspaceTabId = "json-tab";
const kInfoWorkspaceTabId = "plan-tab";
const kSampleMessagesTabId = `sample-display-messages`;
const kSampleTranscriptTabId = `sample-display-transcript`;
const kSampleScoringTabId = `sample-display-scoring`;
const kSampleMetdataTabId = `sample-display-metadata`;
const kSampleErrorTabId = `sample-display-error`;
const kSampleJsonTabId = `sample-display-json`;
const kScoreTypePassFail = "passfail";
const kScoreTypeCategorical = "categorical";
const kScoreTypeNumeric = "numeric";
const kScoreTypeOther = "other";
const kScoreTypeObject = "object";
const kSampleAscVal = "sample-asc";
const kSampleDescVal = "sample-desc";
const kEpochAscVal = "epoch-asc";
const kEpochDescVal = "epoch-desc";
const kScoreAscVal = "score-asc";
const kScoreDescVal = "score-desc";
const kDefaultSort = kSampleAscVal;
const InlineSampleDisplay = ({
  id,
  sample,
  sampleStatus,
  sampleError,
  sampleDescriptor,
  selectedTab,
  setSelectedTab
}) => {
  return m$1`<div style=${{ flexDirection: "row", width: "100%" }}>
    <${ProgressBar}
      animating=${sampleStatus === "loading"}
      containerStyle=${{
    background: "var(--bs-body-bg)"
  }}
    />
    <div style=${{ margin: "1em 1em 1em 1em" }}>
      ${sampleError ? m$1`<${ErrorPanel}
            title="Unable to load sample"
            error=${sampleError}
          />` : m$1` <${SampleDisplay}
            id=${id}
            sample=${sample}
            sampleDescriptor=${sampleDescriptor}
            selectedTab=${selectedTab}
            setSelectedTab=${setSelectedTab}
          />`}
    </div>
  </div>`;
};
const SampleDisplay = ({
  id,
  sample,
  sampleDescriptor,
  selectedTab,
  setSelectedTab
}) => {
  const baseId = `sample-dialog`;
  if (!sample) {
    return m$1`<${EmptyPanel} />`;
  }
  const onSelectedTab = (e2) => {
    const id2 = e2.currentTarget.id;
    setSelectedTab(id2);
    return false;
  };
  const tabs = [
    m$1`
    <${TabPanel} id=${kSampleMessagesTabId} classes="sample-tab" title="Messages" onSelected=${onSelectedTab} selected=${selectedTab === kSampleMessagesTabId}>
      <${ChatView} 
        key=${`${baseId}-chat-${id}`} 
        id=${`${baseId}-chat-${id}`} 
        messages=${sample.messages} 
        style=${{ paddingLeft: ".8em", paddingTop: "1em" }}
        indented=${true}
      />
    </${TabPanel}>`
  ];
  if (sample.events && sample.events.length > 0) {
    tabs.unshift(m$1`
      <${TabPanel} id=${kSampleTranscriptTabId} classes="sample-tab" title="Transcript" onSelected=${onSelectedTab} selected=${selectedTab === kSampleTranscriptTabId || selectedTab === void 0} scrollable=${false}>
        <${SampleTranscript} key=${`${baseId}-transcript-display-${id}`} id=${`${baseId}-transcript-display-${id}`} evalEvents=${sample.events}/>
      </${TabPanel}>`);
  }
  const scorerNames = Object.keys(sample.scores);
  if (scorerNames.length === 1) {
    tabs.push(m$1`
      <${TabPanel} id=${kSampleScoringTabId} classes="sample-tab" title="Scoring" onSelected=${onSelectedTab} selected=${selectedTab === kSampleScoringTabId}>
        <${SampleScoreView}
          sample=${sample}
          sampleDescriptor=${sampleDescriptor}
          scorer=${Object.keys(sample.scores)[0]}
          style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}
        />
      </${TabPanel}>`);
  } else {
    for (const scorer of Object.keys(sample.scores)) {
      const tabId = `score-${scorer}`;
      tabs.push(m$1`
        <${TabPanel} id="${tabId}" classes="sample-tab" title="${scorer}" onSelected=${onSelectedTab} selected=${selectedTab === tabId}>
          <${SampleScoreView}
            sample=${sample}
            sampleDescriptor=${sampleDescriptor}
            scorer=${scorer}
            style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}
          />
        </${TabPanel}>`);
    }
  }
  const sampleMetadatas = metadataViewsForSample(`${baseId}-${id}`, sample);
  if (sampleMetadatas.length > 0) {
    tabs.push(
      m$1`
      <${TabPanel} 
          id=${kSampleMetdataTabId} 
          classes="sample-tab"
          title="Metadata" 
          onSelected=${onSelectedTab} 
          selected=${selectedTab === kSampleMetdataTabId}>
         <div style=${{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: "1em", paddingLeft: "0.8em", marginTop: "1em" }}> 
          ${sampleMetadatas}
        </div>
      </${TabPanel}>`
    );
  }
  if (sample.error) {
    tabs.push(
      m$1`
      <${TabPanel} 
          id=${kSampleErrorTabId} 
          classes="sample-tab"
          title="Error" 
          onSelected=${onSelectedTab} 
          selected=${selectedTab === kSampleErrorTabId}>
         <div style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}> 
          <${ANSIDisplay} output=${sample.error.traceback_ansi} style=${{ fontSize: FontSize.small, margin: "1em 0" }}/>
        </div>
      </${TabPanel}>`
    );
  }
  tabs.push(m$1`<${TabPanel} 
          id=${kSampleJsonTabId} 
          classes="sample-tab"
          title="JSON" 
          onSelected=${onSelectedTab} 
          selected=${selectedTab === kSampleJsonTabId}>
         <div style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}> 
          <${JSONPanel} data=${sample} simple=${true}/>
        </div>
      </${TabPanel}>`);
  const tabsetId = `task-sample-details-tab-${id}`;
  const targetId = `${tabsetId}-content`;
  const printSample = () => {
    const targetTabEl = document.querySelector(
      `#${escapeSelector(targetId)} .sample-tab.tab-pane.show.active`
    );
    if (targetTabEl) {
      const targetEl = targetTabEl.firstElementChild;
      if (targetEl) {
        const headingId = `sample-heading-${id}`;
        const headingEl = document.getElementById(headingId);
        const headingHtml = printHeadingHtml();
        const css = `
        html { font-size: 9pt }
        /* Allow content to break anywhere without any forced page breaks */
        * {
          break-inside: auto;  /* Let elements break anywhere */
          page-break-inside: auto;  /* Legacy support */
          break-before: auto;
          page-break-before: auto;
          break-after: auto;
          page-break-after: auto;
        }
        /* Specifically disable all page breaks for divs */
        div {
          break-inside: auto;
          page-break-inside: auto;
        }
        body > .transcript-step {
          break-inside: avoid;
        }
        body{
          -webkit-print-color-adjust:exact !important;
          print-color-adjust:exact !important;
        }
        /* Allow preformatted text and code blocks to break across pages */
        pre, code {
            white-space: pre-wrap; /* Wrap long lines instead of keeping them on one line */
            overflow-wrap: break-word; /* Ensure long words are broken to fit within the page */
            break-inside: auto; /* Allow page breaks inside the element */
            page-break-inside: auto; /* Older equivalent */
        }

        /* Additional control for long lines within code/preformatted blocks */
        pre {
            word-wrap: break-word; /* Break long words if needed */
        }    
            
        `;
        printHtml(
          [headingHtml, headingEl.outerHTML, targetEl.innerHTML].join("\n"),
          css
        );
      }
    }
  };
  const tools = [];
  if (!isVscode()) {
    tools.push(
      m$1`<${ToolButton}
        name=${m$1`Print`}
        icon="${ApplicationIcons.copy}"
        onclick="${printSample}"
      />`
    );
  }
  return m$1`<${SampleSummary}
    id=${id}
    sample=${sample}
    sampleDescriptor=${sampleDescriptor}/>

  <${TabSet} id=${tabsetId} styles=${{
    tabs: {
      fontSize: FontSize.base
    },
    tabBody: { paddingBottom: "1em" }
  }}
    tools=${tools}>
    ${tabs}
  </${TabSet}>`;
};
const metadataViewsForSample = (id, sample) => {
  const sampleMetadatas = [];
  if (sample.model_usage && Object.keys(sample.model_usage).length > 0) {
    sampleMetadatas.push(m$1`
      <${Card}>
        <${CardHeader} label="Usage"/>
        <${CardBody}>
          <${ModelTokenTable} model_usage=${sample.model_usage} style=${{ marginTop: 0 }}/>
        </${CardBody}>
      </${Card}>`);
  }
  if (Object.keys(sample == null ? void 0 : sample.metadata).length > 0) {
    sampleMetadatas.push(
      m$1`
      <${Card}>
        <${CardHeader} label="Metadata"/>
        <${CardBody}>
          <${MetaDataView}
            id="task-sample-metadata-${id}"
            classes="tab-pane"
            entries="${sample == null ? void 0 : sample.metadata}"
            style=${{ marginTop: "0" }}
          />
        </${CardBody}>
        </${Card}>`
    );
  }
  if (Object.keys(sample == null ? void 0 : sample.store).length > 0) {
    sampleMetadatas.push(
      m$1`
      <${Card}>
        <${CardHeader} label="Store"/>
        <${CardBody}>
          <${MetaDataView}
            id="task-sample-store-${id}"
            classes="tab-pane"
            entries="${sample == null ? void 0 : sample.store}"
            style=${{ marginTop: "0" }}
          />
        </${CardBody}>
      </${Card}>`
    );
  }
  return sampleMetadatas;
};
const SampleSummary = ({ id, sample, style, sampleDescriptor }) => {
  const input = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.normalized.input) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.normalized.input) : 0;
  const target = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.normalized.target) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.normalized.target) : 0;
  const answer = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.normalized.answer) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.normalized.answer) : 0;
  const limitSize = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.normalized.limit) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.normalized.limit) : 0;
  const idSize = Math.max(
    2,
    Math.min(10, sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.raw.id)
  );
  const scoreInput = inputString(sample.input);
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
    size: `${idSize}em`
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
            markdown=${fullAnswer}
            style=${{ paddingLeft: "0" }}
            class="no-last-para-padding"
          />` : "",
      size: `${answer}fr`,
      clamp: true
    });
  }
  if (sample.limit && limitSize > 0) {
    columns.push({
      label: "Limit",
      value: sample.limit.type,
      size: `${limitSize}fr`,
      center: true
    });
  }
  columns.push({
    label: "Score",
    value: sample.error ? m$1`<${FlatSampleError}
          message=${sample.error.message}
          style=${{ marginTop: "0.4rem" }}
        />` : sampleDescriptor == null ? void 0 : sampleDescriptor.selectedScore(sample).render(),
    size: "minmax(2em, auto)",
    center: true
  });
  return m$1`
    <div
      id=${`sample-heading-${id}`}
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
const SampleDialog = ({
  id,
  title,
  sample,
  sampleDescriptor,
  nextSample,
  prevSample,
  sampleStatus,
  sampleError,
  showingSampleDialog,
  setShowingSampleDialog,
  selectedTab,
  setSelectedTab,
  sampleScrollPositionRef,
  setSampleScrollPosition
}) => {
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
        case "Escape":
          setShowingSampleDialog(false);
          break;
      }
    },
    [prevSample, nextSample]
  );
  const children = T(() => {
    return sampleError ? m$1`<${ErrorPanel} title="Sample Error" error=${sampleError} />` : m$1`<${SampleDisplay}
          id=${id}
          sample=${sample}
          sampleDescriptor=${sampleDescriptor}
          selectedTab=${selectedTab}
          setSelectedTab=${setSelectedTab}
        />`;
  }, [id, sample, sampleDescriptor, selectedTab, setSelectedTab, sampleError]);
  const onHide = q(() => {
    setShowingSampleDialog(false);
  }, [setShowingSampleDialog]);
  return m$1`
    <${LargeModal} 
      id=${id} 
      detail=${title}
      detailTools=${tools}
      onkeyup=${handleKeyUp}   
      visible=${showingSampleDialog}
      onHide=${onHide}
      showProgress=${sampleStatus === "loading"}
      initialScrollPositionRef=${sampleScrollPositionRef}
      setInitialScrollPosition=${setSampleScrollPosition}
    >
        ${children}
    </${LargeModal}>`;
};
const STYLE_INNER = "position:relative; overflow:hidden; width:100%; min-height:100%;";
const STYLE_CONTENT = "position:absolute; top:0; left:0; height:100%; width:100%; overflow:visible;";
class VirtualList extends k$1 {
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
  const [hidden, setHidden] = h(false);
  y(() => {
    setHidden(false);
  }, [items]);
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
  const renderRow = (item) => {
    if (item.type === "sample") {
      return m$1`
        <${SampleRow}
          id=${item.number}
          index=${item.index}
          sample=${item.data}
          height=${kSampleHeight}
          sampleDescriptor=${sampleDescriptor}
          selected=${selectedIndex === item.index}
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
  const onkeydown = q(
    (e2) => {
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
          showSample(selectedIndex);
          e2.preventDefault();
          e2.stopPropagation();
          return false;
      }
    },
    [selectedIndex]
  );
  const listStyle = { ...style, flex: "1", overflowY: "auto", outline: "none" };
  const { limit, answer } = gridColumns(sampleDescriptor);
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
    <div>${answer !== "0" ? "Answer" : ""}</div>
    <div>${limit !== "0" ? "Limit" : ""}</div>
    <div style=${{ justifySelf: "center" }}>Score</div>
  </div>`;
  const sampleCount = items == null ? void 0 : items.reduce((prev, current) => {
    if (current.type === "sample") {
      return prev + 1;
    } else {
      return prev;
    }
  }, 0);
  const footerRow = m$1` <div
    style=${{
    borderTop: "solid var(--bs-light-border-subtle) 1px",
    background: "var(--bs-light-bg-subtle)",
    fontSize: FontSize.smaller,
    display: "grid",
    gridTemplateColumns: "max-content",
    justifyContent: "end",
    alignContent: "end",
    padding: "0.2em 1em"
  }}
  >
    <div>${sampleCount} Samples</div>
  </div>`;
  const errorCount = items == null ? void 0 : items.reduce((previous, item) => {
    if (item.data.error) {
      return previous + 1;
    } else {
      return previous;
    }
  }, 0);
  const limitCount = items == null ? void 0 : items.reduce((previous, item) => {
    if (item.data.limit) {
      return previous + 1;
    } else {
      return previous;
    }
  }, 0);
  const percentError = errorCount / sampleCount * 100;
  const percentLimit = limitCount / sampleCount * 100;
  const warningMessage = errorCount > 0 ? `INFO: ${errorCount} of ${sampleCount} samples (${formatNoDecimal(percentError)}%) had errors and were not scored.` : limitCount ? `INFO: ${limitCount} of ${sampleCount} samples (${formatNoDecimal(percentLimit)}%) completed due to exceeding a limit.` : void 0;
  const warningRow = warningMessage ? m$1`<${MessageBand}
        message=${warningMessage}
        hidden=${hidden}
        setHidden=${setHidden}
        type="info"
      />` : "";
  return m$1` <div
    style=${{ display: "flex", flexDirection: "column", width: "100%" }}
  >
    ${warningRow} ${headerRow}
    <${VirtualList}
      ref=${listRef}
      data=${items}
      tabIndex="0"
      renderRow=${renderRow}
      onkeydown=${onkeydown}
      rowMap=${rowMap}
      style=${listStyle}
    />
    ${footerRow}
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
    showSample(index);
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
      <div
        class="sample-id"
        style=${{ ...cellStyle, ...ApplicationStyles.threeLineClamp }}
      >
        ${sample.id}
      </div>
      <div
        class="sample-input"
        style=${{
    ...ApplicationStyles.threeLineClamp,
    wordWrap: "anywhere",
    ...cellStyle
  }}
      >
        ${inputString(sample.input).join(" ")}
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
                markdown=${sampleDescriptor == null ? void 0 : sampleDescriptor.selectedScorer(sample).answer()}
                style=${{ paddingLeft: "0" }}
                class="no-last-para-padding"
              />
            ` : ""}
      </div>
      <div
        class="sample-limit"
        style=${{
    fontSize: FontSize.small,
    ...ApplicationStyles.threeLineClamp,
    ...cellStyle
  }}
      >
        ${sample.limit}
      </div>

      <div
        style=${{
    fontSize: FontSize.small,
    ...cellStyle,
    display: "flex",
    justifySelf: "center"
  }}
      >
        ${sample.error ? m$1`<${SampleError} message=${sample.error} />` : sampleDescriptor == null ? void 0 : sampleDescriptor.selectedScore(sample).render()}
      </div>
    </div>
  `;
};
const gridColumnStyles = (sampleDescriptor) => {
  const { input, target, answer, limit, id, score } = gridColumns(sampleDescriptor);
  return {
    gridGap: "10px",
    gridTemplateColumns: `${id} ${input} ${target} ${answer} ${limit} ${score}`,
    paddingLeft: "1rem",
    paddingRight: "1rem"
  };
};
const gridColumns = (sampleDescriptor) => {
  const input = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.normalized.input) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.normalized.input) : 0;
  const target = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.normalized.target) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.normalized.target) : 0;
  const answer = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.normalized.answer) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.normalized.answer) : 0;
  const limit = (sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.normalized.limit) > 0 ? Math.max(0.15, sampleDescriptor.messageShape.normalized.limit) : 0;
  const id = Math.max(2, Math.min(10, sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.raw.id));
  const score = Math.max(
    3,
    Math.min(10, sampleDescriptor == null ? void 0 : sampleDescriptor.messageShape.raw.score)
  );
  const frSize = (val) => {
    if (val === 0) {
      return "0";
    } else {
      return `${val}fr`;
    }
  };
  return {
    input: frSize(input),
    target: frSize(target),
    answer: frSize(answer),
    limit: frSize(limit),
    id: `${id}rem`,
    score: `${score}rem`
  };
};
const SamplesTab = ({
  task_id,
  sample,
  samples,
  sampleMode,
  groupBy,
  groupByOrder,
  sampleDescriptor,
  selectedScore,
  sampleStatus,
  sampleError,
  selectedSampleIndex,
  setSelectedSampleIndex,
  showingSampleDialog,
  setShowingSampleDialog,
  selectedSampleTab,
  setSelectedSampleTab,
  sampleScrollPositionRef,
  setSampleScrollPosition
}) => {
  const [items, setItems] = h([]);
  const [sampleItems, setSampleItems] = h([]);
  const sampleListRef = A(
    /** @type {HTMLElement|null} */
    null
  );
  const sampleDialogRef = A(
    /** @type {HTMLElement|null} */
    null
  );
  const showSample = q(
    (index2) => {
      setSelectedSampleIndex(index2);
      setShowingSampleDialog(true);
    },
    [sampleDialogRef]
  );
  y(() => {
    if (showingSampleDialog) {
      setTimeout(() => {
        sampleDialogRef.current.base.focus();
      }, 0);
    } else {
      setTimeout(() => {
        if (sampleListRef.current) {
          sampleListRef.current.base.focus();
        }
      }, 0);
    }
  }, [showingSampleDialog]);
  y(() => {
    const sampleProcessor = getSampleProcessor(
      samples,
      groupBy,
      groupByOrder,
      sampleDescriptor
    );
    const items2 = samples.flatMap((sample2, index2) => {
      const results = [];
      const previousSample2 = index2 !== 0 ? samples[index2 - 1] : void 0;
      const items3 = sampleProcessor(sample2, index2, previousSample2);
      results.push(...items3);
      return results;
    });
    setItems(items2);
    setSampleItems(
      items2.filter((item) => {
        return item.type === "sample";
      })
    );
  }, [samples, groupBy, groupByOrder, sampleDescriptor]);
  const nextSampleIndex = q(() => {
    if (selectedSampleIndex < sampleItems.length - 1) {
      return selectedSampleIndex + 1;
    } else {
      return -1;
    }
  }, [selectedSampleIndex, items]);
  const previousSampleIndex = q(() => {
    return selectedSampleIndex > 0 ? selectedSampleIndex - 1 : -1;
  }, [selectedSampleIndex, items]);
  const nextSample = q(() => {
    const next = nextSampleIndex();
    if (sampleStatus !== "loading" && next > -1) {
      setSelectedSampleIndex(next);
    }
  }, [selectedSampleIndex, samples, sampleStatus, nextSampleIndex]);
  const previousSample = q(() => {
    const prev = previousSampleIndex();
    if (sampleStatus !== "loading" && prev > -1) {
      setSelectedSampleIndex(prev);
    }
  }, [selectedSampleIndex, samples, sampleStatus, previousSampleIndex]);
  const elements = [];
  if (sampleMode === "single") {
    elements.push(
      m$1` <${InlineSampleDisplay}
        key=${`${task_id}-single-sample`}
        id="sample-display"
        sample=${sample}
        sampleStatus=${sampleStatus}
        sampleError=${sampleError}
        sampleDescriptor=${sampleDescriptor}
        selectedTab=${selectedSampleTab}
        setSelectedTab=${setSelectedSampleTab}
      />`
    );
  } else if (sampleMode === "many") {
    elements.push(
      m$1`<${SampleList}
        listRef=${sampleListRef}
        items=${items}
        sampleDescriptor=${sampleDescriptor}
        selectedIndex=${selectedSampleIndex}
        setSelectedIndex=${setSelectedSampleIndex}
        selectedScore=${selectedScore}
        nextSample=${nextSample}
        prevSample=${previousSample}
        showSample=${showSample}
      />`
    );
  } else {
    elements.push(m$1`<${EmptyPanel} />`);
  }
  const title = selectedSampleIndex > -1 && sampleItems.length > selectedSampleIndex ? sampleItems[selectedSampleIndex].label : "";
  const index = selectedSampleIndex > -1 && sampleItems.length > selectedSampleIndex ? sampleItems[selectedSampleIndex].index : -1;
  elements.push(m$1`
    <${SampleDialog}
      id=${(sample == null ? void 0 : sample.id) || ""}
      ref=${sampleDialogRef}
      task=${task_id}
      title=${title}
      index=${index}
      sample=${sample}
      sampleStatus=${sampleStatus}
      sampleError=${sampleError}
      sampleDescriptor=${sampleDescriptor}
      showingSampleDialog=${showingSampleDialog}
      setShowingSampleDialog=${setShowingSampleDialog}
      selectedTab=${selectedSampleTab}
      setSelectedTab=${setSelectedSampleTab}
      nextSample=${nextSample}
      prevSample=${previousSample}
      sampleScrollPositionRef=${sampleScrollPositionRef}
      setSampleScrollPosition=${setSampleScrollPosition}
    />
  `);
  return elements;
};
const getSampleProcessor = (samples, groupBy, groupByOrder, sampleDescriptor) => {
  if (groupBy == "epoch") {
    return groupByEpoch(samples, sampleDescriptor, groupByOrder);
  } else if (groupBy === "sample") {
    return groupBySample(samples, sampleDescriptor, groupByOrder);
  } else {
    return noGrouping(samples, groupByOrder);
  }
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
    if (typeof a2.id === "string") {
      if (order2 === "asc") {
        return String(a2.id).localeCompare(String(b2.id));
      } else {
        return String(b2.id).localeCompare(String(a2.id));
      }
    } else {
      if (order2 === "asc") {
        return Number(a2.id) - Number(b2.id);
      } else {
        return Number(b2.id) - Number(b2.id);
      }
    }
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
const asyncJsonParse = async (text2) => {
  const blob = new Blob([kWorkerCode], { type: "application/javascript" });
  const blobURL = URL.createObjectURL(blob);
  const worker = new Worker(blobURL);
  try {
    const result = new Promise((resolve, reject) => {
      worker.onmessage = function(e2) {
        if (e2.data.success) {
          resolve(e2.data.result);
        } else {
          reject(new Error(e2.data.error));
        }
      };
      worker.onerror = function(error2) {
        reject(new Error(error2.message));
      };
    });
    worker.postMessage({ scriptContent: kJson5ScriptBase64, text: text2 });
    return await result;
  } finally {
    worker.terminate();
    URL.revokeObjectURL(blobURL);
  }
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
async function download_file$1(filename2, filecontents) {
  const blob = new Blob([filecontents], { type: "text/plain" });
  const link2 = document.createElement("a");
  link2.href = URL.createObjectURL(blob);
  link2.download = filename2;
  document.body.appendChild(link2);
  link2.click();
  document.body.removeChild(link2);
}
const loaded_time = Date.now();
let last_eval_time = 0;
async function client_events$1() {
  const params = new URLSearchParams();
  params.append("loaded_time", String(loaded_time.valueOf()));
  params.append("last_eval_time", String(last_eval_time.valueOf()));
  return (await api$1("GET", `/api/events?${params.toString()}`)).parsed;
}
async function eval_logs$1() {
  const logs = await api$1("GET", `/api/logs`);
  last_eval_time = Date.now();
  return logs.parsed;
}
async function eval_log$1(file, headerOnly) {
  return await api$1(
    "GET",
    `/api/logs/${encodeURIComponent(file)}?header-only=${headerOnly}`
  );
}
async function eval_log_size$1(file) {
  return (await api$1("GET", `/api/log-size/${encodeURIComponent(file)}`)).parsed;
}
async function eval_log_bytes$1(file, start2, end2) {
  return await api_bytes(
    "GET",
    `/api/log-bytes/${encodeURIComponent(file)}?start=${start2}&end=${end2}`
  );
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
    const text2 = await response.text();
    return {
      parsed: await asyncJsonParse(text2),
      raw: text2
    };
  } else if (response.status !== 200) {
    const message = await response.text() || response.statusText;
    const error2 = new Error(`Error: ${response.status}: ${message})`);
    throw error2;
  } else {
    throw new Error(`${response.status} - ${response.statusText} `);
  }
}
async function api_bytes(method, path) {
  const headers = {
    Accept: "application/octet-stream",
    Pragma: "no-cache",
    Expires: "0",
    ["Cache-Control"]: "no-cache"
  };
  const response = await fetch(`${path}`, { method, headers });
  if (response.ok) {
    const buffer2 = await response.arrayBuffer();
    return new Uint8Array(buffer2);
  } else if (response.status !== 200) {
    const message = await response.text() || response.statusText;
    const error2 = new Error(`Error: ${response.status}: ${message})`);
    throw error2;
  } else {
    throw new Error(`${response.status} - ${response.statusText} `);
  }
}
async function open_log_file$1() {
}
const browserApi = {
  client_events: client_events$1,
  eval_logs: eval_logs$1,
  eval_log: eval_log$1,
  eval_log_size: eval_log_size$1,
  eval_log_bytes: eval_log_bytes$1,
  eval_log_headers: eval_log_headers$1,
  download_file: download_file$1,
  open_log_file: open_log_file$1
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
var parse = function parse2(text2, reviver) {
  source = String(text2);
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
      for (let i = 0; i < value.length; i++) {
        const key2 = String(i);
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
  const err2 = new SyntaxError(message);
  err2.lineNumber = line;
  err2.columnNumber = column;
  return err2;
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
    for (let i = 0; i < value2.length; i++) {
      const c2 = value2[i];
      switch (c2) {
        case "'":
        case '"':
          quotes[c2]++;
          product += c2;
          continue;
        case "\0":
          if (util.isDigit(value2[i + 1])) {
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
    for (let i = firstChar.length; i < key2.length; i++) {
      if (!util.isIdContinueChar(String.fromCodePoint(key2.codePointAt(i)))) {
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
    for (let i = 0; i < value2.length; i++) {
      const propertyString = serializeProperty(String(i), value2);
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
var kMethodEvalLogSize = "eval_log_size";
var kMethodEvalLogBytes = "eval_log_bytes";
var kMethodEvalLogHeaders = "eval_log_headers";
function webViewJsonRpcClient(vscode2) {
  var target = {
    postMessage: function(data) {
      vscode2.postMessage(data);
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
let _vscodeApi = void 0;
const getVscodeApi = () => {
  if (window.acquireVsCodeApi) {
    if (_vscodeApi == void 0) {
      _vscodeApi = window.acquireVsCodeApi();
    }
    return _vscodeApi;
  } else {
    return void 0;
  }
};
const vscodeClient = webViewJsonRpcClient(getVscodeApi());
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
    if (capabilities == null ? void 0 : capabilities.webWorkers) {
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
async function eval_log_size(file) {
  return await vscodeClient(kMethodEvalLogSize, [file]);
}
async function eval_log_bytes(file, start2, end2) {
  return await vscodeClient(kMethodEvalLogBytes, [file, start2, end2]);
}
async function eval_log_headers(files) {
  const response = await vscodeClient(kMethodEvalLogHeaders, [files]);
  if (response) {
    return lib.parse(response);
  } else {
    return void 0;
  }
}
async function download_file() {
  throw Error("Downloading files is not supported in VS Code");
}
async function open_log_file(url, log_dir) {
  const msg = {
    type: "displayLogFile",
    url,
    log_dir
  };
  getVscodeApi().postMessage(msg);
}
const vscodeApi = {
  client_events,
  eval_logs,
  eval_log,
  eval_log_size,
  eval_log_bytes,
  eval_log_headers,
  download_file,
  open_log_file
};
var ch2 = {};
var wk = function(c2, id, msg, transfer, cb) {
  var w2 = new Worker(ch2[id] || (ch2[id] = URL.createObjectURL(new Blob([
    c2 + ';addEventListener("error",function(e){e=e.error;postMessage({$e$:[e.message,e.code,e.stack]})})'
  ], { type: "text/javascript" }))));
  w2.onmessage = function(e2) {
    var d2 = e2.data, ed = d2.$e$;
    if (ed) {
      var err2 = new Error(ed[0]);
      err2["code"] = ed[1];
      err2.stack = ed[2];
      cb(err2, null);
    } else
      cb(null, d2);
  };
  w2.postMessage(msg, transfer);
  return w2;
};
var u8 = Uint8Array, u16 = Uint16Array, i32 = Int32Array;
var fleb = new u8([
  0,
  0,
  0,
  0,
  0,
  0,
  0,
  0,
  1,
  1,
  1,
  1,
  2,
  2,
  2,
  2,
  3,
  3,
  3,
  3,
  4,
  4,
  4,
  4,
  5,
  5,
  5,
  5,
  0,
  /* unused */
  0,
  0,
  /* impossible */
  0
]);
var fdeb = new u8([
  0,
  0,
  0,
  0,
  1,
  1,
  2,
  2,
  3,
  3,
  4,
  4,
  5,
  5,
  6,
  6,
  7,
  7,
  8,
  8,
  9,
  9,
  10,
  10,
  11,
  11,
  12,
  12,
  13,
  13,
  /* unused */
  0,
  0
]);
var clim = new u8([16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]);
var freb = function(eb, start2) {
  var b2 = new u16(31);
  for (var i = 0; i < 31; ++i) {
    b2[i] = start2 += 1 << eb[i - 1];
  }
  var r2 = new i32(b2[30]);
  for (var i = 1; i < 30; ++i) {
    for (var j2 = b2[i]; j2 < b2[i + 1]; ++j2) {
      r2[j2] = j2 - b2[i] << 5 | i;
    }
  }
  return { b: b2, r: r2 };
};
var _a = freb(fleb, 2), fl = _a.b, revfl = _a.r;
fl[28] = 258, revfl[258] = 28;
var _b = freb(fdeb, 0), fd = _b.b;
var rev = new u16(32768);
for (var i = 0; i < 32768; ++i) {
  var x = (i & 43690) >> 1 | (i & 21845) << 1;
  x = (x & 52428) >> 2 | (x & 13107) << 2;
  x = (x & 61680) >> 4 | (x & 3855) << 4;
  rev[i] = ((x & 65280) >> 8 | (x & 255) << 8) >> 1;
}
var hMap = function(cd, mb, r2) {
  var s2 = cd.length;
  var i = 0;
  var l2 = new u16(mb);
  for (; i < s2; ++i) {
    if (cd[i])
      ++l2[cd[i] - 1];
  }
  var le = new u16(mb);
  for (i = 1; i < mb; ++i) {
    le[i] = le[i - 1] + l2[i - 1] << 1;
  }
  var co;
  if (r2) {
    co = new u16(1 << mb);
    var rvb = 15 - mb;
    for (i = 0; i < s2; ++i) {
      if (cd[i]) {
        var sv = i << 4 | cd[i];
        var r_1 = mb - cd[i];
        var v2 = le[cd[i] - 1]++ << r_1;
        for (var m2 = v2 | (1 << r_1) - 1; v2 <= m2; ++v2) {
          co[rev[v2] >> rvb] = sv;
        }
      }
    }
  } else {
    co = new u16(s2);
    for (i = 0; i < s2; ++i) {
      if (cd[i]) {
        co[i] = rev[le[cd[i] - 1]++] >> 15 - cd[i];
      }
    }
  }
  return co;
};
var flt = new u8(288);
for (var i = 0; i < 144; ++i)
  flt[i] = 8;
for (var i = 144; i < 256; ++i)
  flt[i] = 9;
for (var i = 256; i < 280; ++i)
  flt[i] = 7;
for (var i = 280; i < 288; ++i)
  flt[i] = 8;
var fdt = new u8(32);
for (var i = 0; i < 32; ++i)
  fdt[i] = 5;
var flrm = /* @__PURE__ */ hMap(flt, 9, 1);
var fdrm = /* @__PURE__ */ hMap(fdt, 5, 1);
var max = function(a2) {
  var m2 = a2[0];
  for (var i = 1; i < a2.length; ++i) {
    if (a2[i] > m2)
      m2 = a2[i];
  }
  return m2;
};
var bits = function(d2, p2, m2) {
  var o2 = p2 / 8 | 0;
  return (d2[o2] | d2[o2 + 1] << 8) >> (p2 & 7) & m2;
};
var bits16 = function(d2, p2) {
  var o2 = p2 / 8 | 0;
  return (d2[o2] | d2[o2 + 1] << 8 | d2[o2 + 2] << 16) >> (p2 & 7);
};
var shft = function(p2) {
  return (p2 + 7) / 8 | 0;
};
var slc = function(v2, s2, e2) {
  if (s2 == null || s2 < 0)
    s2 = 0;
  if (e2 == null || e2 > v2.length)
    e2 = v2.length;
  return new u8(v2.subarray(s2, e2));
};
var ec = [
  "unexpected EOF",
  "invalid block type",
  "invalid length/literal",
  "invalid distance",
  "stream finished",
  "no stream handler",
  ,
  "no callback",
  "invalid UTF-8 data",
  "extra field too long",
  "date not in range 1980-2099",
  "filename too long",
  "stream finishing",
  "invalid zip data"
  // determined by unknown compression method
];
var err = function(ind, msg, nt) {
  var e2 = new Error(msg || ec[ind]);
  e2.code = ind;
  if (Error.captureStackTrace)
    Error.captureStackTrace(e2, err);
  if (!nt)
    throw e2;
  return e2;
};
var inflt = function(dat, st, buf, dict) {
  var sl = dat.length, dl = dict ? dict.length : 0;
  if (!sl || st.f && !st.l)
    return buf || new u8(0);
  var noBuf = !buf;
  var resize = noBuf || st.i != 2;
  var noSt = st.i;
  if (noBuf)
    buf = new u8(sl * 3);
  var cbuf = function(l3) {
    var bl = buf.length;
    if (l3 > bl) {
      var nbuf = new u8(Math.max(bl * 2, l3));
      nbuf.set(buf);
      buf = nbuf;
    }
  };
  var final = st.f || 0, pos2 = st.p || 0, bt = st.b || 0, lm = st.l, dm = st.d, lbt = st.m, dbt = st.n;
  var tbts = sl * 8;
  do {
    if (!lm) {
      final = bits(dat, pos2, 1);
      var type = bits(dat, pos2 + 1, 3);
      pos2 += 3;
      if (!type) {
        var s2 = shft(pos2) + 4, l2 = dat[s2 - 4] | dat[s2 - 3] << 8, t2 = s2 + l2;
        if (t2 > sl) {
          if (noSt)
            err(0);
          break;
        }
        if (resize)
          cbuf(bt + l2);
        buf.set(dat.subarray(s2, t2), bt);
        st.b = bt += l2, st.p = pos2 = t2 * 8, st.f = final;
        continue;
      } else if (type == 1)
        lm = flrm, dm = fdrm, lbt = 9, dbt = 5;
      else if (type == 2) {
        var hLit = bits(dat, pos2, 31) + 257, hcLen = bits(dat, pos2 + 10, 15) + 4;
        var tl = hLit + bits(dat, pos2 + 5, 31) + 1;
        pos2 += 14;
        var ldt = new u8(tl);
        var clt = new u8(19);
        for (var i = 0; i < hcLen; ++i) {
          clt[clim[i]] = bits(dat, pos2 + i * 3, 7);
        }
        pos2 += hcLen * 3;
        var clb = max(clt), clbmsk = (1 << clb) - 1;
        var clm = hMap(clt, clb, 1);
        for (var i = 0; i < tl; ) {
          var r2 = clm[bits(dat, pos2, clbmsk)];
          pos2 += r2 & 15;
          var s2 = r2 >> 4;
          if (s2 < 16) {
            ldt[i++] = s2;
          } else {
            var c2 = 0, n2 = 0;
            if (s2 == 16)
              n2 = 3 + bits(dat, pos2, 3), pos2 += 2, c2 = ldt[i - 1];
            else if (s2 == 17)
              n2 = 3 + bits(dat, pos2, 7), pos2 += 3;
            else if (s2 == 18)
              n2 = 11 + bits(dat, pos2, 127), pos2 += 7;
            while (n2--)
              ldt[i++] = c2;
          }
        }
        var lt = ldt.subarray(0, hLit), dt = ldt.subarray(hLit);
        lbt = max(lt);
        dbt = max(dt);
        lm = hMap(lt, lbt, 1);
        dm = hMap(dt, dbt, 1);
      } else
        err(1);
      if (pos2 > tbts) {
        if (noSt)
          err(0);
        break;
      }
    }
    if (resize)
      cbuf(bt + 131072);
    var lms = (1 << lbt) - 1, dms = (1 << dbt) - 1;
    var lpos = pos2;
    for (; ; lpos = pos2) {
      var c2 = lm[bits16(dat, pos2) & lms], sym = c2 >> 4;
      pos2 += c2 & 15;
      if (pos2 > tbts) {
        if (noSt)
          err(0);
        break;
      }
      if (!c2)
        err(2);
      if (sym < 256)
        buf[bt++] = sym;
      else if (sym == 256) {
        lpos = pos2, lm = null;
        break;
      } else {
        var add2 = sym - 254;
        if (sym > 264) {
          var i = sym - 257, b2 = fleb[i];
          add2 = bits(dat, pos2, (1 << b2) - 1) + fl[i];
          pos2 += b2;
        }
        var d2 = dm[bits16(dat, pos2) & dms], dsym = d2 >> 4;
        if (!d2)
          err(3);
        pos2 += d2 & 15;
        var dt = fd[dsym];
        if (dsym > 3) {
          var b2 = fdeb[dsym];
          dt += bits16(dat, pos2) & (1 << b2) - 1, pos2 += b2;
        }
        if (pos2 > tbts) {
          if (noSt)
            err(0);
          break;
        }
        if (resize)
          cbuf(bt + 131072);
        var end2 = bt + add2;
        if (bt < dt) {
          var shift = dl - dt, dend = Math.min(dt, end2);
          if (shift + bt < 0)
            err(3);
          for (; bt < dend; ++bt)
            buf[bt] = dict[shift + bt];
        }
        for (; bt < end2; ++bt)
          buf[bt] = buf[bt - dt];
      }
    }
    st.l = lm, st.p = lpos, st.b = bt, st.f = final;
    if (lm)
      final = 1, st.m = lbt, st.d = dm, st.n = dbt;
  } while (!final);
  return bt != buf.length && noBuf ? slc(buf, 0, bt) : buf.subarray(0, bt);
};
var et = /* @__PURE__ */ new u8(0);
var mrg = function(a2, b2) {
  var o2 = {};
  for (var k2 in a2)
    o2[k2] = a2[k2];
  for (var k2 in b2)
    o2[k2] = b2[k2];
  return o2;
};
var wcln = function(fn2, fnStr, td2) {
  var dt = fn2();
  var st = fn2.toString();
  var ks = st.slice(st.indexOf("[") + 1, st.lastIndexOf("]")).replace(/\s+/g, "").split(",");
  for (var i = 0; i < dt.length; ++i) {
    var v2 = dt[i], k2 = ks[i];
    if (typeof v2 == "function") {
      fnStr += ";" + k2 + "=";
      var st_1 = v2.toString();
      if (v2.prototype) {
        if (st_1.indexOf("[native code]") != -1) {
          var spInd = st_1.indexOf(" ", 8) + 1;
          fnStr += st_1.slice(spInd, st_1.indexOf("(", spInd));
        } else {
          fnStr += st_1;
          for (var t2 in v2.prototype)
            fnStr += ";" + k2 + ".prototype." + t2 + "=" + v2.prototype[t2].toString();
        }
      } else
        fnStr += st_1;
    } else
      td2[k2] = v2;
  }
  return fnStr;
};
var ch = [];
var cbfs = function(v2) {
  var tl = [];
  for (var k2 in v2) {
    if (v2[k2].buffer) {
      tl.push((v2[k2] = new v2[k2].constructor(v2[k2])).buffer);
    }
  }
  return tl;
};
var wrkr = function(fns, init, id, cb) {
  if (!ch[id]) {
    var fnStr = "", td_1 = {}, m2 = fns.length - 1;
    for (var i = 0; i < m2; ++i)
      fnStr = wcln(fns[i], fnStr, td_1);
    ch[id] = { c: wcln(fns[m2], fnStr, td_1), e: td_1 };
  }
  var td2 = mrg({}, ch[id].e);
  return wk(ch[id].c + ";onmessage=function(e){for(var k in e.data)self[k]=e.data[k];onmessage=" + init.toString() + "}", id, td2, cbfs(td2), cb);
};
var bInflt = function() {
  return [u8, u16, i32, fleb, fdeb, clim, fl, fd, flrm, fdrm, rev, ec, hMap, max, bits, bits16, shft, slc, err, inflt, inflateSync, pbf, gopt];
};
var guze = function() {
  return [gzs, gzl];
};
var zule = function() {
  return [zls];
};
var pbf = function(msg) {
  return postMessage(msg, [msg.buffer]);
};
var gopt = function(o2) {
  return o2 && {
    out: o2.size && new u8(o2.size),
    dictionary: o2.dictionary
  };
};
var cbify = function(dat, opts, fns, init, id, cb) {
  var w2 = wrkr(fns, init, id, function(err2, dat2) {
    w2.terminate();
    cb(err2, dat2);
  });
  w2.postMessage([dat, opts], opts.consume ? [dat.buffer] : []);
  return function() {
    w2.terminate();
  };
};
var gzs = function(d2) {
  if (d2[0] != 31 || d2[1] != 139 || d2[2] != 8)
    err(6, "invalid gzip data");
  var flg = d2[3];
  var st = 10;
  if (flg & 4)
    st += (d2[10] | d2[11] << 8) + 2;
  for (var zs = (flg >> 3 & 1) + (flg >> 4 & 1); zs > 0; zs -= !d2[st++])
    ;
  return st + (flg & 2);
};
var gzl = function(d2) {
  var l2 = d2.length;
  return (d2[l2 - 4] | d2[l2 - 3] << 8 | d2[l2 - 2] << 16 | d2[l2 - 1] << 24) >>> 0;
};
var zls = function(d2, dict) {
  if ((d2[0] & 15) != 8 || d2[0] >> 4 > 7 || (d2[0] << 8 | d2[1]) % 31)
    err(6, "invalid zlib data");
  if ((d2[1] >> 5 & 1) == +!dict)
    err(6, "invalid zlib data: " + (d2[1] & 32 ? "need" : "unexpected") + " dictionary");
  return (d2[1] >> 3 & 4) + 2;
};
function inflate(data, opts, cb) {
  if (!cb)
    cb = opts, opts = {};
  if (typeof cb != "function")
    err(7);
  return cbify(data, opts, [
    bInflt
  ], function(ev) {
    return pbf(inflateSync(ev.data[0], gopt(ev.data[1])));
  }, 1, cb);
}
function inflateSync(data, opts) {
  return inflt(data, { i: 2 }, opts && opts.out, opts && opts.dictionary);
}
function gunzip(data, opts, cb) {
  if (!cb)
    cb = opts, opts = {};
  if (typeof cb != "function")
    err(7);
  return cbify(data, opts, [
    bInflt,
    guze,
    function() {
      return [gunzipSync];
    }
  ], function(ev) {
    return pbf(gunzipSync(ev.data[0], ev.data[1]));
  }, 3, cb);
}
function gunzipSync(data, opts) {
  var st = gzs(data);
  if (st + 8 > data.length)
    err(6, "invalid gzip data");
  return inflt(data.subarray(st, -8), { i: 2 }, opts && opts.out || new u8(gzl(data)), opts && opts.dictionary);
}
function unzlib(data, opts, cb) {
  if (!cb)
    cb = opts, opts = {};
  if (typeof cb != "function")
    err(7);
  return cbify(data, opts, [
    bInflt,
    zule,
    function() {
      return [unzlibSync];
    }
  ], function(ev) {
    return pbf(unzlibSync(ev.data[0], gopt(ev.data[1])));
  }, 5, cb);
}
function unzlibSync(data, opts) {
  return inflt(data.subarray(zls(data, opts && opts.dictionary), -4), { i: 2 }, opts && opts.out, opts && opts.dictionary);
}
function decompress(data, opts, cb) {
  if (!cb)
    cb = opts, opts = {};
  if (typeof cb != "function")
    err(7);
  return data[0] == 31 && data[1] == 139 && data[2] == 8 ? gunzip(data, opts, cb) : (data[0] & 15) != 8 || data[0] >> 4 > 7 || (data[0] << 8 | data[1]) % 31 ? inflate(data, opts, cb) : unzlib(data, opts, cb);
}
var td = typeof TextDecoder != "undefined" && /* @__PURE__ */ new TextDecoder();
var tds = 0;
try {
  td.decode(et, { stream: true });
  tds = 1;
} catch (e2) {
}
class FileSizeLimitError extends Error {
  /**
   * Creates a new FileSizeLimitError.
   *
   * @param {string} file - The name of the file that caused the error.
   * @param {number} maxBytes - The maximum allowed size for the file, in bytes.
   */
  constructor(file, maxBytes) {
    super(
      `File "${file}" exceeds the maximum size (${maxBytes} bytes) and cannot be loaded.`
    );
    this.name = "FileSizeLimitError";
    this.file = file;
    this.maxBytes = maxBytes;
  }
}
const openRemoteZipFile = async (url, fetchContentLength = fetchSize, fetchBytes = fetchRange) => {
  const contentLength = await fetchContentLength(url);
  const eocdrBuffer = await fetchBytes(
    url,
    contentLength - 22,
    contentLength - 1
  );
  const eocdrView = new DataView(eocdrBuffer.buffer);
  const centralDirOffset = eocdrView.getUint32(16, true);
  const centralDirSize = eocdrView.getUint32(12, true);
  const centralDirBuffer = await fetchBytes(
    url,
    centralDirOffset,
    centralDirOffset + centralDirSize - 1
  );
  const centralDirectory = parseCentralDirectory(centralDirBuffer);
  return {
    centralDirectory,
    readFile: async (file, maxBytes) => {
      const entry = centralDirectory.get(file);
      if (!entry) {
        throw new Error(`File not found: ${file}`);
      }
      const headerSize = 30;
      const headerData = await fetchBytes(
        url,
        entry.fileOffset,
        entry.fileOffset + headerSize - 1
      );
      const filenameLength = headerData[26] + (headerData[27] << 8);
      const extraFieldLength = headerData[28] + (headerData[29] << 8);
      const totalSizeToFetch = headerSize + filenameLength + extraFieldLength + entry.compressedSize;
      if (maxBytes && totalSizeToFetch > maxBytes) {
        throw new FileSizeLimitError(file, maxBytes);
      }
      const fileData = await fetchBytes(
        url,
        entry.fileOffset,
        entry.fileOffset + totalSizeToFetch - 1
      );
      const zipFileEntry = await parseZipFileEntry(file, fileData);
      if (zipFileEntry.compressionMethod === 0) {
        return zipFileEntry.data;
      } else if (zipFileEntry.compressionMethod === 8) {
        const results = await decompressAsync(zipFileEntry.data, {
          size: zipFileEntry.uncompressedSize
        });
        return results;
      } else {
        throw new Error(`Unsupported compressionMethod for file ${file}`);
      }
    }
  };
};
const fetchSize = async (url) => {
  const response = await fetch(`${url}`, { method: "HEAD" });
  const contentLength = Number(response.headers.get("Content-Length"));
  return contentLength;
};
const fetchRange = async (url, start2, end2) => {
  const response = await fetch(`${url}`, {
    headers: { Range: `bytes=${start2}-${end2}` }
  });
  const arrayBuffer = await response.arrayBuffer();
  return new Uint8Array(arrayBuffer);
};
const decompressAsync = async (data, opts) => {
  return new Promise((resolve, reject) => {
    decompress(data, opts, (err2, result) => {
      if (err2) {
        reject(err2);
      } else {
        resolve(result);
      }
    });
  });
};
const parseZipFileEntry = async (file, rawData) => {
  const view = new DataView(rawData.buffer);
  let offset2 = 0;
  const signature = view.getUint32(offset2, true);
  if (signature !== 67324752) {
    throw new Error(`Invalid ZIP entry signature for ${file}`);
  }
  offset2 += 4;
  const versionNeeded = view.getUint16(offset2, true);
  offset2 += 2;
  const bitFlag = view.getUint16(offset2, true);
  offset2 += 2;
  const compressionMethod = view.getUint16(offset2, true);
  offset2 += 2;
  offset2 += 4;
  const crc32 = view.getUint32(offset2, true);
  offset2 += 4;
  const compressedSize = view.getUint32(offset2, true);
  offset2 += 4;
  const uncompressedSize = view.getUint32(offset2, true);
  offset2 += 4;
  const filenameLength = view.getUint16(offset2, true);
  offset2 += 2;
  const extraFieldLength = view.getUint16(offset2, true);
  offset2 += 2;
  offset2 += filenameLength + extraFieldLength;
  const data = rawData.subarray(offset2, offset2 + compressedSize);
  return {
    versionNeeded,
    bitFlag,
    compressionMethod,
    crc32,
    compressedSize,
    uncompressedSize,
    filenameLength,
    extraFieldLength,
    data
  };
};
const parseCentralDirectory = (buffer2) => {
  let offset2 = 0;
  const view = new DataView(buffer2.buffer);
  const entries = /* @__PURE__ */ new Map();
  while (offset2 < buffer2.length) {
    if (view.getUint32(offset2, true) !== 33639248) break;
    const filenameLength = view.getUint16(offset2 + 28, true);
    const extraFieldLength = view.getUint16(offset2 + 30, true);
    const fileCommentLength = view.getUint16(offset2 + 32, true);
    const filename2 = new TextDecoder().decode(
      buffer2.subarray(offset2 + 46, offset2 + 46 + filenameLength)
    );
    const entry = {
      filename: filename2,
      compressionMethod: view.getUint16(offset2 + 10, true),
      compressedSize: view.getUint32(offset2 + 20, true),
      uncompressedSize: view.getUint32(offset2 + 24, true),
      fileOffset: view.getUint32(offset2 + 42, true)
    };
    entries.set(filename2, entry);
    offset2 += 46 + filenameLength + extraFieldLength + fileCommentLength;
  }
  return entries;
};
function simpleHttpApi(log_dir, log_file) {
  const resolved_log_dir = log_dir.replace(" ", "+");
  const resolved_log_path = log_file ? log_file.replace(" ", "+") : void 0;
  return simpleHttpAPI({
    log_file: resolved_log_path,
    log_dir: resolved_log_dir
  });
}
function simpleHttpAPI(logInfo) {
  const log_file = logInfo.log_file;
  const log_dir = logInfo.log_dir;
  const cache = log_file_cache(log_file);
  async function open_log_file2() {
  }
  return {
    client_events: async () => {
      return Promise.resolve([]);
    },
    eval_logs: async () => {
      const headers = await fetchLogHeaders(log_dir);
      if (headers) {
        const logRecord = headers.parsed;
        const logs = Object.keys(logRecord).map((key2) => {
          return {
            name: joinURI(log_dir, key2),
            task: logRecord[key2].eval.task,
            task_id: logRecord[key2].eval.task_id
          };
        });
        return Promise.resolve({
          files: logs
        });
      } else if (log_file) {
        let evalLog = cache.get();
        if (!evalLog) {
          const response = await fetchLogFile(log_file);
          cache.set(response.parsed);
          evalLog = response.parsed;
        }
        const result = {
          name: log_file,
          task: evalLog.eval.task,
          task_id: evalLog.eval.task_id
        };
        return {
          files: [result]
        };
      } else {
        throw new Error(
          `Failed to load a manifest files using the directory: ${log_dir}. Please be sure you have deployed a manifest file (logs.json).`
        );
      }
    },
    eval_log: async (file) => {
      const response = await fetchLogFile(file);
      cache.set(response.parsed);
      return response;
    },
    eval_log_size: async (log_file2) => {
      return await fetchSize(log_file2);
    },
    eval_log_bytes: async (log_file2, start2, end2) => {
      return await fetchRange(log_file2, start2, end2);
    },
    eval_log_headers: async (files) => {
      const headers = await fetchLogHeaders(log_dir);
      if (headers) {
        const keys = Object.keys(headers.parsed);
        const result = [];
        files.forEach((file) => {
          const fileKey = keys.find((key2) => {
            return file.endsWith(key2);
          });
          if (fileKey) {
            result.push(headers.parsed[fileKey]);
          }
        });
        return result;
      } else if (log_file) {
        let evalLog = cache.get();
        if (!evalLog) {
          const response = await fetchLogFile(log_file);
          cache.set(response.parsed);
          evalLog = response.parsed;
        }
        return [evalLog];
      } else {
        throw new Error(
          `Failed to load a manifest files using the directory: ${log_dir}. Please be sure you have deployed a manifest file (logs.json).`
        );
      }
    },
    download_file: download_file$1,
    open_log_file: open_log_file2
  };
}
async function fetchFile(url, parse3, handleError) {
  const safe_url = encodePathParts(url);
  const response = await fetch(`${safe_url}`, { method: "GET" });
  if (response.ok) {
    const text2 = await response.text();
    return {
      parsed: await parse3(text2),
      raw: text2
    };
  } else if (response.status !== 200) {
    if (handleError && handleError(response)) {
      return void 0;
    }
    const message = await response.text() || response.statusText;
    const error2 = new Error(`${response.status}: ${message})`);
    throw error2;
  } else {
    throw new Error(`${response.status} - ${response.statusText} `);
  }
}
const fetchLogFile = async (file) => {
  return fetchFile(file, async (text2) => {
    const log = await asyncJsonParse(text2);
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
    return log;
  });
};
const fetchLogHeaders = async (log_dir) => {
  const logs = await fetchFile(
    log_dir + "/logs.json",
    async (text2) => {
      return await asyncJsonParse(text2);
    },
    (response) => {
      if (response.status === 404) {
        return true;
      }
    }
  );
  return logs;
};
function joinURI(...segments) {
  return segments.map((segment) => segment.replace(/(^\/+|\/+$)/g, "")).join("/");
}
const log_file_cache = (log_file) => {
  if (!log_file) {
    return {
      set: () => {
      },
      get: () => {
        return void 0;
      }
    };
  }
  let cache_file;
  return {
    set: (log_file2) => {
      cache_file = log_file2;
    },
    get: () => {
      return cache_file;
    }
  };
};
function encodePathParts(url) {
  if (!url) return url;
  try {
    const fullUrl = new URL(url);
    fullUrl.pathname = fullUrl.pathname.split("/").map(
      (segment) => segment ? encodeURIComponent(decodeURIComponent(segment)) : ""
    ).join("/");
    return fullUrl.toString();
  } catch {
    return url.split("/").map(
      (segment) => segment ? encodeURIComponent(decodeURIComponent(segment)) : ""
    ).join("/");
  }
}
class AsyncQueue {
  /**
   * Creates an instance of AsyncQueue.
   * @param {number} [concurrentLimit=6] - The maximum number of tasks that can run concurrently.
   */
  constructor(concurrentLimit = 6) {
    this.concurrentLimit = concurrentLimit;
    this.queue = [];
    this.runningCount = 0;
  }
  /**
   * Adds a task to the queue and runs it if the concurrency limit allows.
   * @param {Function} task - The task to be executed asynchronously. This should be a function that returns a promise.
   * @returns {Promise<*>} - A promise that resolves with the result of the task or rejects if the task throws an error.
   */
  async enqueue(task) {
    return new Promise((resolve, reject) => {
      this.queue.push(async () => {
        try {
          const result = await task();
          resolve(result);
        } catch (error2) {
          reject(error2);
        } finally {
          this.runningCount--;
          this.runNext();
        }
      });
      if (this.runningCount < this.concurrentLimit) {
        this.runNext();
      }
    });
  }
  /**
   * Runs the next task in the queue if there are available slots for concurrent execution.
   * @private
   */
  runNext() {
    if (this.queue.length > 0 && this.runningCount < this.concurrentLimit) {
      const task = this.queue.shift();
      if (task) {
        this.runningCount++;
        task();
      }
    }
  }
}
const MAX_BYTES = 12582912;
const openRemoteLogFile = async (api2, url, concurrency) => {
  const queue = new AsyncQueue(concurrency);
  const remoteZipFile = await openRemoteZipFile(
    `${encodeURIComponent(url)}`,
    api2.eval_log_size,
    api2.eval_log_bytes
  );
  const readJSONFile = async (file, maxBytes) => {
    try {
      const data = await remoteZipFile.readFile(file, maxBytes);
      const textDecoder = new TextDecoder("utf-8");
      const jsonString = textDecoder.decode(data);
      return asyncJsonParse(jsonString);
    } catch (error2) {
      if (error2 instanceof FileSizeLimitError) {
        throw error2;
      } else {
        throw new Error(
          `Failed to read or parse file ${file}: ${error2.message}`
        );
      }
    }
  };
  const listSamples = async () => {
    return Array.from(remoteZipFile.centralDirectory.keys()).filter(
      (filename2) => filename2.startsWith("samples/") && filename2.endsWith(".json")
    ).map((filename2) => {
      const [sampleId, epochStr] = filename2.split("/")[1].split("_epoch_");
      return {
        sampleId,
        epoch: parseInt(epochStr.split(".")[0], 10)
      };
    });
  };
  const readSample = async (sampleId, epoch) => {
    const sampleFile = `samples/${sampleId}_epoch_${epoch}.json`;
    if (remoteZipFile.centralDirectory.has(sampleFile)) {
      return readJSONFile(sampleFile, MAX_BYTES);
    } else {
      console.log({ dir: remoteZipFile.centralDirectory });
      throw new Error(
        `Unable to read sample file ${sampleFile} - it is not present in the manifest.`
      );
    }
  };
  const readHeader = async () => {
    if (remoteZipFile.centralDirectory.has("header.json")) {
      return readJSONFile("header.json");
    } else {
      const evalSpec = await readJSONFile("_journal/start.json");
      return {
        status: "started",
        eval: evalSpec.eval,
        plan: evalSpec.plan
      };
    }
  };
  const readFallbackSummaries = async () => {
    const summaryFiles = Array.from(
      remoteZipFile.centralDirectory.keys()
    ).filter(
      (filename2) => filename2.startsWith("_journal/summaries/") && filename2.endsWith(".json")
    );
    const summaries = [];
    const errors2 = [];
    await Promise.all(
      summaryFiles.map(
        (filename2) => queue.enqueue(async () => {
          try {
            const partialSummary = await readJSONFile(filename2);
            summaries.push(...partialSummary);
          } catch (error2) {
            errors2.push(error2);
          }
        })
      )
    );
    if (errors2.length > 0) {
      console.error(
        `Encountered ${errors2.length} errors while reading summary files:`,
        errors2
      );
    }
    return summaries;
  };
  const readSampleSummaries = async () => {
    if (remoteZipFile.centralDirectory.has("summaries.json")) {
      return await readJSONFile("summaries.json");
    } else {
      return readFallbackSummaries();
    }
  };
  return {
    readHeader,
    readLogSummary: async () => {
      const [header, sampleSummaries] = await Promise.all([
        readHeader(),
        readSampleSummaries()
      ]);
      const result = {
        status: header.status,
        eval: header.eval,
        plan: header.plan,
        results: header.results,
        stats: header.stats,
        error: header.error,
        sampleSummaries
      };
      return result;
    },
    readSample,
    /**
     * Reads the complete log file.
     * @returns {Promise<import("../types/log").EvalLog>} The complete log data.
     */
    readCompleteLog: async () => {
      const [evalLog, samples] = await Promise.all([
        readHeader(),
        listSamples().then(
          (sampleIds) => Promise.all(
            sampleIds.map(({ sampleId, epoch }) => readSample(sampleId, epoch))
          )
        )
      ]);
      return {
        status: evalLog.status,
        eval: evalLog.eval,
        plan: evalLog.plan,
        results: evalLog.results,
        stats: evalLog.stats,
        error: evalLog.error,
        samples
      };
    }
  };
};
const isEvalFile = (file) => {
  return file.endsWith(".eval");
};
class SampleSizeLimitedExceededError extends Error {
  /**
   * Creates a new SizeLimitedExceededError.
   *
   * @param {string | number} id - The name of the file that caused the error.
   * @param {number} epoch - The name of the file that caused the error.
   * @param {number} maxBytes - The maximum allowed size for the file, in bytes.
   */
  constructor(id, epoch, maxBytes) {
    super(
      `Sample ${id} in epoch ${epoch} exceeds the maximum supported size (${maxBytes / 1024 / 1024}MB) and cannot be loaded.`
    );
    this.name = "SampleSizeLimitedExceededError";
    this.id = id;
    this.epoch = epoch;
    this.maxBytes = maxBytes;
    this.displayStack = false;
  }
}
const clientApi = (api2) => {
  let current_log = void 0;
  let current_path = void 0;
  const loadedEvalFile = {
    file: void 0,
    remoteLog: void 0
  };
  const remoteEvalFile = async (log_file, cached = false) => {
    if (!cached || loadedEvalFile.file !== log_file) {
      loadedEvalFile.file = log_file;
      loadedEvalFile.remoteLog = await openRemoteLogFile(api2, log_file, 5);
    }
    return loadedEvalFile.remoteLog;
  };
  const get_log = async (log_file, cached = false) => {
    if (!cached || log_file !== current_path || !current_log) {
      if (pending_log_promise) {
        return pending_log_promise;
      }
      pending_log_promise = api2.eval_log(log_file, 100).then((log) => {
        current_log = log;
        current_path = log_file;
        pending_log_promise = null;
        return log;
      }).catch((err2) => {
        pending_log_promise = null;
        throw err2;
      });
      return pending_log_promise;
    }
    return current_log;
  };
  let pending_log_promise = null;
  const get_log_summary = async (log_file) => {
    var _a2;
    if (isEvalFile(log_file)) {
      const remoteLogFile = await remoteEvalFile(log_file);
      return await remoteLogFile.readLogSummary();
    } else {
      const logContents = await get_log(log_file);
      const sampleSummaries = logContents.parsed.samples ? (_a2 = logContents.parsed.samples) == null ? void 0 : _a2.map((sample) => {
        var _a3;
        return {
          id: sample.id,
          epoch: sample.epoch,
          input: sample.input,
          target: sample.target,
          scores: sample.scores,
          metadata: sample.metadata,
          error: (_a3 = sample.error) == null ? void 0 : _a3.message
        };
      }) : [];
      const parsed = logContents.parsed;
      return {
        version: parsed.version,
        status: parsed.status,
        eval: parsed.eval,
        plan: parsed.plan,
        results: parsed.results,
        stats: parsed.stats,
        error: parsed.error,
        sampleSummaries
      };
    }
  };
  const get_log_sample = async (log_file, id, epoch) => {
    if (isEvalFile(log_file)) {
      const remoteLogFile = await remoteEvalFile(log_file, true);
      try {
        const sample = await remoteLogFile.readSample(id, epoch);
        return sample;
      } catch (error2) {
        if (error2 instanceof FileSizeLimitError) {
          throw new SampleSizeLimitedExceededError(id, epoch, error2.maxBytes);
        } else {
          throw error2;
        }
      }
    } else {
      const logContents = await get_log(log_file, true);
      if (logContents.parsed.samples && logContents.parsed.samples.length > 0) {
        return logContents.parsed.samples.find((sample) => {
          return sample.id === id && sample.epoch === epoch;
        });
      }
    }
    return void 0;
  };
  const get_eval_log_header = async (log_file) => {
    const remoteLogFile = await openRemoteLogFile(api2, log_file, 5);
    return remoteLogFile.readHeader();
  };
  const get_log_headers = async (log_files) => {
    const eval_files = {};
    const json_files = {};
    let index = 0;
    for (const file of log_files) {
      if (isEvalFile(file)) {
        eval_files[file] = index;
      } else {
        json_files[file] = index;
      }
      index++;
    }
    const evalLogHeadersPromises = Object.keys(eval_files).map(
      (file) => get_eval_log_header(file).then((header) => ({
        index: eval_files[file],
        // Store original index
        header
      }))
    );
    const jsonLogHeadersPromise = api2.eval_log_headers(Object.keys(json_files)).then(
      (headers2) => headers2.map((header, i) => ({
        index: json_files[Object.keys(json_files)[i]],
        // Store original index
        header
      }))
    );
    const headers = await Promise.all([
      ...evalLogHeadersPromises,
      jsonLogHeadersPromise
    ]);
    const orderedHeaders = headers.flat().sort((a2, b2) => a2.index - b2.index);
    return orderedHeaders.map(({ header }) => header);
  };
  return {
    client_events: () => {
      return api2.client_events();
    },
    get_log_paths: () => {
      return api2.eval_logs();
    },
    get_log_headers: (log_files) => {
      return get_log_headers(log_files);
    },
    get_log_summary,
    get_log_sample,
    open_log_file: (log_file, log_dir) => {
      return api2.open_log_file(log_file, log_dir);
    },
    download_file: (download_file2, file_contents) => {
      return api2.download_file(download_file2, file_contents);
    }
  };
};
const resolveApi = () => {
  if (getVscodeApi()) {
    return clientApi(vscodeApi);
  } else {
    const scriptEl = document.getElementById("log_dir_context");
    if (scriptEl) {
      const data = JSON.parse(scriptEl.textContent);
      if (data.log_dir || data.log_file) {
        const log_dir2 = data.log_dir || dirname(data.log_file);
        const api2 = simpleHttpApi(log_dir2, data.log_file);
        return clientApi(api2);
      }
    }
    const urlParams = new URLSearchParams(window.location.search);
    const log_file = urlParams.get("log_file");
    const log_dir = urlParams.get("log_dir");
    if (log_file || log_dir) {
      const api2 = simpleHttpApi(log_dir, log_file);
      return clientApi(api2);
    }
    return clientApi(browserApi);
  }
};
const api = resolveApi();
const DownloadButton = ({ label, fileName, fileContents }) => {
  return m$1`<button
    class="btn btn-outline-primary"
    style=${{ fontSize: FontSize.small, marginTop: "3em" }}
    onclick=${async () => {
    await api.download_file(fileName, fileContents);
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
const kJsonMaxSize = 1e7;
const JsonTab = ({ logFileName, capabilities, json }) => {
  const renderedContent = [];
  if (json.length > kJsonMaxSize && capabilities.downloadFiles) {
    const file = `${filename(logFileName)}.json`;
    renderedContent.push(
      m$1`<${DownloadPanel}
        message="Log file raw JSON is too large to render."
        buttonLabel="Download JSON File"
        logFile=${logFileName}
        fileName=${file}
        fileContents=${json}
      />`
    );
  } else {
    return m$1` <div
      style=${{
      padding: "0.5rem",
      fontSize: FontSize.small,
      width: "100%"
    }}
    >
      <${JSONPanel} id="task-json-contents" json=${json} simple=${true} />
    </div>`;
  }
};
const EpochFilter = ({ epochs, epoch, setEpoch }) => {
  const options = ["all"];
  for (let i = 1; i <= epochs; i++) {
    options.push(i + "");
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
const SortFilter = ({ sampleDescriptor, sort, setSort, epochs }) => {
  var _a2;
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
  if ((_a2 = sampleDescriptor == null ? void 0 : sampleDescriptor.scoreDescriptor) == null ? void 0 : _a2.compare) {
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
        value=${sort}
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
const byEpoch = (sort) => {
  return sort === kEpochAscVal || sort === kEpochDescVal;
};
const bySample = (sort) => {
  return sort === kSampleAscVal || sort === kSampleDescVal;
};
const sortSamples = (sort, samples, samplesDescriptor) => {
  const sortedSamples = samples.sort((a2, b2) => {
    switch (sort) {
      case kSampleAscVal:
        if (isNumeric(a2.id) && isNumeric(b2.id)) {
          return Number(a2.id) - Number(b2.id);
        } else {
          return String(a2.id).localeCompare(String(b2.id));
        }
      case kSampleDescVal:
        if (isNumeric(a2.id) && isNumeric(b2.id)) {
          return Number(b2.id) - Number(a2.id);
        } else {
          return String(b2.id).localeCompare(String(a2.id));
        }
      case kEpochAscVal:
        return a2.epoch - b2.epoch;
      case kEpochDescVal:
        return b2.epoch - a2.epoch;
      case kScoreAscVal:
        return samplesDescriptor.scoreDescriptor.compare(
          samplesDescriptor.selectedScore(a2).value,
          samplesDescriptor.selectedScore(b2).value
        );
      case kScoreDescVal:
        return samplesDescriptor.scoreDescriptor.compare(
          samplesDescriptor.selectedScore(b2).value,
          samplesDescriptor.selectedScore(a2).value
        );
    }
  });
  return {
    sorted: sortedSamples,
    order: sort === kSampleAscVal || sort === kEpochAscVal || sort === kScoreAscVal ? "asc" : "desc"
  };
};
const SampleFilter = ({ descriptor, filter, filterChanged }) => {
  var _a2;
  const updateCategoryValue = (e2) => {
    const val = e2.currentTarget.value;
    if (val === "all") {
      filterChanged({});
    } else {
      filterChanged({
        value: val,
        type: kScoreTypeCategorical
      });
    }
  };
  switch ((_a2 = descriptor == null ? void 0 : descriptor.scoreDescriptor) == null ? void 0 : _a2.scoreType) {
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
        onChange=${updateCategoryValue}
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
        onChange=${updateCategoryValue}
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
          onInput=${(e2) => {
        filterChanged({
          value: e2.currentTarget.value,
          type: kScoreTypeNumeric
        });
      }}
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
        onChange=${updateCategoryValue}
      />`;
    }
    default: {
      return void 0;
    }
  }
};
const SelectFilter = ({ value, options, onChange }) => {
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
        onChange=${onChange}
      >
        ${options.map((option) => {
    return m$1`<option value="${option.value}">${option.text}</option>`;
  })}
      </select>
    </div>
  `;
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
    sort,
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
      sort=${sort}
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
    let iEl = e2.target;
    if (iEl.tagName === "BUTTON") {
      iEl = iEl.firstChild;
    }
    console.log({ iEl });
    if (iEl) {
      if (iEl) {
        iEl.className = `${ApplicationIcons.confirm} primary`;
        setTimeout(() => {
          iEl.className = ApplicationIcons.copy;
        }, 1250);
      }
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
const SecondaryBar = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  samples,
  status,
  style
}) => {
  if (!evalSpec || status !== "success") {
    return "";
  }
  const staticColStyle = {
    flexShrink: "0"
  };
  const epochs = evalSpec.config.epochs || 1;
  const hyperparameters = {
    ...evalPlan == null ? void 0 : evalPlan.config,
    ...evalSpec.task_args
  };
  const hasConfig = Object.keys(hyperparameters).length > 0;
  const values = [];
  values.push({
    size: "minmax(12%, auto)",
    value: m$1`<${LabeledValue} label="Dataset" style=${staticColStyle}>
    <${DatasetSummary}
      dataset=${evalSpec.dataset}
      samples=${samples}
      epochs=${epochs} />
  </${LabeledValue}>
`
  });
  const label = (evalResults == null ? void 0 : evalResults.scores.length) > 1 ? "Scorers" : "Scorer";
  values.push({
    size: "minmax(12%, auto)",
    value: m$1`<${LabeledValue} label="${label}" style=${staticColStyle} style=${{ justifySelf: hasConfig ? "left" : "center" }}>
    <${ScorerSummary} 
      scorers=${evalResults == null ? void 0 : evalResults.scores} />
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
  const totalDuration = formatDuration(
    new Date(evalStats.started_at),
    new Date(evalStats.completed_at)
  );
  values.push({
    size: "minmax(12%, auto)",
    value: m$1`
      <${LabeledValue} label="Duration" style=${{ justifySelf: "right" }}>
        ${totalDuration}
      </${LabeledValue}>`
  });
  return m$1`
    <${ExpandablePanel} style=${{ margin: "0", ...style }} collapse=${true} lines=${4}>
    <div
      style=${{
    margin: "0",
    padding: "0.2em 1em 0.2em 1em",
    display: "grid",
    gridColumnGap: "1em",
    borderTop: "1px solid var(--bs-border-color)",
    gridTemplateColumns: `${values.map((val) => {
      return val.size;
    }).join(" ")}`
  }}
    >
      ${values.map((val) => {
    return val.value;
  })}
    </div>
    </${ExpandablePanel}>
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
    const val = params[key2];
    if (Array.isArray(val) || typeof val === "object") {
      return `${key2}: ${JSON.stringify(val)}`;
    } else {
      return `${key2}: ${val}`;
    }
  });
  if (paraValues.length > 0) {
    return m$1`<code style=${{ padding: 0, color: "var(--bs-body-color)" }}
      >${paraValues.join(", ")}</code
    >`;
  } else {
    return "";
  }
};
const Navbar = ({
  file,
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  samples,
  showToggle,
  offcanvas,
  status
}) => {
  const toggleOffCanClass = offcanvas ? "" : " d-md-none";
  const logFileName = file ? filename(file) : "";
  const task = evalSpec == null ? void 0 : evalSpec.task;
  const model = evalSpec == null ? void 0 : evalSpec.model;
  const results = evalResults;
  const created = evalSpec == null ? void 0 : evalSpec.created;
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
          ${showToggle ? m$1`<button
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
                id="task-title"
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
                id="task-model"
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

        <div id="task-created" style=${{ display: "none" }}>${created}</div>

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
          evalSpec=${evalSpec}
          evalPlan=${evalPlan}
          evalResults=${evalResults}
          evalStats=${evalStats}
          samples=${samples}
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
      style=${{ fontSize: FontSize.large, marginRight: "0.3em" }}
    />
    cancelled (${sampleCount} ${sampleCount === 1 ? "sample" : "samples"})
  </div>`;
};
const RunningPanel = () => {
  return m$1`
    <div
      style=${{
    marginTop: "0.5em",
    display: "inline-grid",
    gridTemplateColumns: "max-content max-content"
  }}
    >
      <div>
        <i class=${ApplicationIcons.running} />
      </div>
      <div
        style=${{
    marginLeft: "0.3em",
    paddingTop: "0.2em",
    fontSize: FontSize.smaller,
    ...TextStyle.label,
    ...TextStyle.secondary
  }}
      >
        Running
      </div>
    </div>
  `;
};
const ResultsPanel = ({ results }) => {
  var _a2, _b2;
  if (((_a2 = results == null ? void 0 : results.scores) == null ? void 0 : _a2.length) === 1) {
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
      ${metrics.map((metric, i) => {
      return m$1`<${VerticalMetric} metric=${metric} isFirst=${i === 0} />`;
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
      ${(_b2 = results == null ? void 0 : results.scores) == null ? void 0 : _b2.map((score, index) => {
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
const TaskErrorCard = ({ evalError }) => {
  return m$1`
    <${Card}>
      <${CardHeader} icon=${ApplicationIcons.error} label="Task Failed: ${evalError.message}"></${CardHeader}>
      <${CardBody} style=${{ fontSize: FontSize.smaller }}>
        <${ANSIDisplay} output=${evalError.traceback_ansi} style=${{ fontSize: "clamp(0.2rem, calc(0.2em + .93vw), 0.9rem)" }}/>
      </${CardBody}>
    </${Card}>
  `;
};
const WorkSpace = ({
  task_id,
  evalStatus,
  logFileName,
  evalError,
  evalSpec,
  evalVersion,
  evalPlan,
  evalStats,
  evalResults,
  samples,
  sampleMode,
  selectedSample,
  groupBy,
  groupByOrder,
  showToggle,
  refreshLog,
  capabilities,
  offcanvas,
  samplesDescriptor,
  selectedSampleIndex,
  setSelectedSampleIndex,
  showingSampleDialog,
  setShowingSampleDialog,
  selectedSampleTab,
  setSelectedSampleTab,
  sampleStatus,
  sampleError,
  sort,
  setSort,
  epochs,
  epoch,
  setEpoch,
  filter,
  setFilter,
  score,
  setScore,
  scores,
  selectedTab,
  setSelectedTab,
  sampleScrollPositionRef,
  setSampleScrollPosition,
  workspaceTabScrollPositionRef,
  setWorkspaceTabScrollPosition
}) => {
  const divRef = A(
    /** @type {HTMLElement|null} */
    null
  );
  if (!evalSpec) {
    return "";
  }
  const [hidden, setHidden] = h(false);
  y(() => {
    setHidden(false);
  }, [logFileName]);
  y(() => {
    if (divRef.current) {
      divRef.current.scrollTop = 0;
    }
  }, [divRef, task_id]);
  const resolvedTabs = T(() => {
    const resolvedTabs2 = {};
    if (evalStatus !== "error" && sampleMode !== "none") {
      resolvedTabs2.samples = {
        id: kEvalWorkspaceTabId,
        scrollable: samples.length === 1,
        label: (samples == null ? void 0 : samples.length) > 1 ? "Samples" : "Sample",
        content: () => {
          return m$1` <${SamplesTab}
            task_id=${task_id}
            selectedScore=${score}
            sample=${selectedSample}
            sampleStatus=${sampleStatus}
            sampleError=${sampleError}
            showingSampleDialog=${showingSampleDialog}
            setShowingSampleDialog=${setShowingSampleDialog}
            samples=${samples}
            sampleMode=${sampleMode}
            groupBy=${groupBy}
            groupByOrder=${groupByOrder}
            selectedSampleIndex=${selectedSampleIndex}
            setSelectedSampleIndex=${setSelectedSampleIndex}
            sampleDescriptor=${samplesDescriptor}
            selectedSampleTab=${selectedSampleTab}
            setSelectedSampleTab=${setSelectedSampleTab}
            filter=${filter}
            sort=${sort}
            epoch=${epoch}
            sampleScrollPositionRef=${sampleScrollPositionRef}
            setSampleScrollPosition=${setSampleScrollPosition}
          />`;
        },
        tools: () => {
          if (sampleMode === "single") {
            return "";
          }
          const sampleTools = [
            m$1`<${SampleTools}
              epoch=${epoch}
              epochs=${epochs}
              setEpoch=${setEpoch}
              filter=${filter}
              filterChanged=${setFilter}
              sort=${sort}
              setSort=${setSort}
              score=${score}
              setScore=${setScore}
              scores=${scores}
              sampleDescriptor=${samplesDescriptor}
            />`
          ];
          if (evalStatus === "started") {
            sampleTools.push(
              m$1`<${ToolButton}
                name=${m$1`Refresh`}
                icon="${ApplicationIcons.refresh}"
                onclick="${refreshLog}"
              />`
            );
          }
          return sampleTools;
        }
      };
    }
    resolvedTabs2.config = {
      id: kInfoWorkspaceTabId,
      label: "Info",
      scrollable: true,
      content: () => {
        var _a2;
        const infoCards = [];
        infoCards.push([
          m$1`<${PlanCard}
            evalSpec=${evalSpec}
            evalPlan=${evalPlan}
            scores=${evalResults == null ? void 0 : evalResults.scores}
          />`
        ]);
        if (evalStatus !== "started") {
          infoCards.push(m$1`<${UsageCard} stats=${evalStats} />`);
        }
        if (evalStatus === "error" && evalError) {
          infoCards.unshift(m$1`<${TaskErrorCard} evalError=${evalError} />`);
        }
        const warnings = [];
        if ((!samples || samples.length === 0) && ((_a2 = evalSpec == null ? void 0 : evalSpec.dataset) == null ? void 0 : _a2.samples) > 0 && evalStatus === "success") {
          warnings.push(
            m$1`<${MessageBand}
              message="Unable to display samples (this evaluation log may be too large)."
              hidden=${hidden}
              setHidden=${setHidden}
              type="warning"
            />`
          );
        }
        return m$1` <div style=${{ width: "100%" }}>
          ${warnings}
          <div style=${{ padding: "0.5em 1em 0 1em", width: "100%" }}>
            ${infoCards}
          </div>
        </div>`;
      }
    };
    resolvedTabs2.json = {
      id: kJsonWorkspaceTabId,
      label: "JSON",
      scrollable: true,
      content: () => {
        const evalHeader = {
          version: evalVersion,
          status: evalStatus,
          eval: evalSpec,
          plan: evalPlan,
          error: evalError,
          results: evalResults,
          stats: evalStats
        };
        const json = JSON.stringify(evalHeader, null, 2);
        return m$1`<${JsonTab}
          logFileName=${logFileName}
          json=${json}
          capabilities=${capabilities}
          selected=${selectedTab === kJsonWorkspaceTabId}
        />`;
      },
      tools: () => {
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
    };
    const copyFeedback = (e2) => {
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
    };
    return resolvedTabs2;
  }, [
    evalStatus,
    sampleMode,
    samples,
    task_id,
    score,
    selectedSample,
    sampleStatus,
    sampleError,
    showingSampleDialog,
    setShowingSampleDialog,
    groupBy,
    groupByOrder,
    selectedSampleIndex,
    setSelectedSampleIndex,
    samplesDescriptor,
    selectedSampleTab,
    setSelectedSampleTab,
    filter,
    sort,
    epoch,
    sampleScrollPositionRef,
    setSampleScrollPosition,
    epochs,
    setEpoch,
    setFilter,
    setSort,
    setScore,
    scores,
    evalSpec,
    evalPlan,
    evalResults,
    evalStats,
    evalError,
    logFileName,
    capabilities,
    selectedTab
  ]);
  return m$1`<${WorkspaceDisplay}
    logFileName=${logFileName}
    divRef=${divRef}
    evalSpec=${evalSpec}
    evalPlan=${evalPlan}
    evalResults=${evalResults}
    evalStats=${evalStats}
    samples=${samples}
    status=${evalStatus}
    tabs=${resolvedTabs}
    selectedTab=${selectedTab}
    showToggle=${showToggle}
    offcanvas=${offcanvas}
    setSelectedTab=${setSelectedTab}
    workspaceTabScrollPositionRef=${workspaceTabScrollPositionRef}
    setWorkspaceTabScrollPosition=${setWorkspaceTabScrollPosition}
  />`;
};
const WorkspaceDisplay = ({
  logFileName,
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  samples,
  status,
  showToggle,
  selectedTab,
  tabs,
  setSelectedTab,
  divRef,
  offcanvas,
  workspaceTabScrollPositionRef,
  setWorkspaceTabScrollPosition
}) => {
  if (evalSpec === void 0) {
    return m$1`<${EmptyPanel} />`;
  } else {
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
    const onScroll = q(
      debounce((id, position) => {
        setWorkspaceTabScrollPosition(id, position);
      }, 100),
      [setWorkspaceTabScrollPosition]
    );
    const onSelected = q(
      (e2) => {
        const id = e2.currentTarget.id;
        setSelectedTab(id);
      },
      [setSelectedTab]
    );
    const tabPanels = T(() => {
      return Object.keys(tabs).map((key2) => {
        const tab = tabs[key2];
        return m$1`<${TabPanel}
        id=${tab.id}
        title="${tab.label}"
        onSelected=${onSelected}
        selected=${selectedTab === tab.id}
        scrollable=${!!tab.scrollable}
        scrollPosition=${workspaceTabScrollPositionRef.current[tab.id]}
        setScrollPosition=${q(
          (position) => {
            onScroll(tab.id, position);
          },
          [onScroll]
        )}
        >
          ${tab.content()}
        </${TabPanel}>`;
      });
    }, [tabs]);
    return m$1`
    
    
    <${Navbar}
      evalSpec=${evalSpec}
      evalPlan=${evalPlan}
      evalResults=${evalResults}
      evalStats=${evalStats}
      samples=${samples}
      status=${status}
      file=${logFileName}
      showToggle=${showToggle}
      
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
        borderRadius: "var(--bs-border-radius)",
        fontWeight: 600
      }
    }} >
            ${tabPanels}
            </${TabSet}>
            </div>
          </div>`;
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
    zIndex: "1060",
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
const createsSamplesDescriptor = (scorers, samples, epochs, selectedScore) => {
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
    scoreDescriptor = categorizer.describe(uniqScoreValues, uniqScoreTypes);
    if (scoreDescriptor) {
      break;
    }
  }
  const sizes = samples.reduce(
    (previous, current) => {
      var _a2;
      const text2 = inputString(current.input).join(" ");
      const scoreText = scoreValue(current) ? String(scoreValue(current)) : "";
      previous[0] = Math.min(Math.max(previous[0], text2.length), 300);
      previous[1] = Math.min(
        Math.max(previous[1], arrayToString(current.target).length),
        300
      );
      previous[2] = Math.min(
        Math.max(
          previous[2],
          ((_a2 = scoreAnswer(current, selectedScore == null ? void 0 : selectedScore.name)) == null ? void 0 : _a2.length) || 0
        ),
        300
      );
      previous[3] = Math.min(
        Math.max(previous[3], current.limit ? current.limit.length : 0),
        50
      );
      previous[4] = Math.min(
        Math.max(previous[4], String(current.id).length),
        10
      );
      previous[5] = Math.min(Math.max(previous[5], scoreText.length), 30);
      return previous;
    },
    [0, 0, 0, 0, 0, 0]
  );
  const maxSizes = {
    input: Math.min(sizes[0], 300),
    target: Math.min(sizes[1], 300),
    answer: Math.min(sizes[2], 300),
    limit: Math.min(sizes[3], 50),
    id: Math.min(sizes[4], 10),
    score: Math.min(sizes[4], 30)
  };
  const base2 = maxSizes.input + maxSizes.target + maxSizes.answer + maxSizes.limit + maxSizes.id + maxSizes.score || 1;
  const messageShape = {
    raw: {
      input: sizes[0],
      target: sizes[1],
      answer: sizes[2],
      limit: sizes[3],
      id: sizes[4],
      score: sizes[5]
    },
    normalized: {
      input: maxSizes.input / base2,
      target: maxSizes.target / base2,
      answer: maxSizes.answer / base2,
      limit: maxSizes.limit / base2,
      id: maxSizes.id / base2,
      score: maxSizes.score / base2
    }
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
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values, types) => {
      if (values.length === 2 && types.length === 1 && types[0] === "boolean") {
        return booleanScoreCategorizer();
      }
    }
  },
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values) => {
      if ((values.length === 1 || values.length === 2) && values.every((val) => {
        return val === 1 || val === 0;
      })) {
        return booleanScoreCategorizer();
      }
    }
  },
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values, types) => {
      if (types[0] === "string" && types.length === 1 && values.length < 5 && !values.find((val) => {
        return val !== "I" && val !== "C" && val !== "P" && val !== "N";
      })) {
        return passFailScoreCategorizer(values);
      }
    }
  },
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values, types) => {
      if (values.length < 10 && types.length === 1 && types[0] === "string") {
        return {
          scoreType: kScoreTypeCategorical,
          categories: values,
          compare: (a2, b2) => {
            return String(a2).localeCompare(String(b2));
          },
          render: (score) => {
            return score;
          }
        };
      }
    }
  },
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values, types) => {
      if (types.length !== 0 && types[0] === "number") {
        const onlyNumeric = values.filter((val) => {
          return typeof val === "number";
        });
        return {
          scoreType: kScoreTypeNumeric,
          min: Math.min(...onlyNumeric),
          max: Math.max(...onlyNumeric),
          compare: (a2, b2) => {
            if (typeof a2 === "number" && typeof b2 === "number") {
              return a2 - b2;
            } else {
              console.warn(
                "Comparing non-numerics using a nuermic score descriptor"
              );
              return 0;
            }
          },
          render: (score) => {
            return formatDecimalNoTrailingZeroes(Number(score));
          }
        };
      }
    }
  },
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
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
          compare: () => {
            return 0;
          },
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
    /**
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    // @ts-ignore
    describe: () => {
      return {
        scoreType: kScoreTypeOther,
        compare: () => {
          return 0;
        },
        render: (score) => {
          return m$1`<${RenderedContent}
            id="other-score-value"
            entry=${{ value: score }}
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
    compare: (a2, b2) => {
      return Number(a2.value) - Number(b2.value);
    },
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
      const sort = order2.indexOf(a2.value) - order2.indexOf(b2.value);
      return sort;
    }
  };
};
const resolveAttachments = (value, attachments) => {
  const kContentProtocol = "tc://";
  const kAttachmentProtocol = "attachment://";
  if (Array.isArray(value)) {
    return value.map((v2) => resolveAttachments(v2, attachments));
  } else if (value && typeof value === "object") {
    const resolvedObject = {};
    for (const key2 of Object.keys(value)) {
      resolvedObject[key2] = resolveAttachments(value[key2], attachments);
    }
    return resolvedObject;
  } else if (typeof value === "string") {
    if (value.startsWith(kContentProtocol)) {
      value = value.replace(kContentProtocol, kAttachmentProtocol);
    }
    if (value.startsWith(kAttachmentProtocol)) {
      return attachments[value.replace(kAttachmentProtocol, "")];
    }
  }
  return value;
};
const filterFnForType = (filter) => {
  if (filter.type) {
    return filterFnsForType[filter.type];
  } else {
    return void 0;
  }
};
const filterCategory = (descriptor, sample, value) => {
  const score = descriptor.selectedScore(sample);
  if (typeof score.value === "string") {
    return score.value.toLowerCase() === (value == null ? void 0 : value.toLowerCase());
  } else if (typeof score.value === "object") {
    return JSON.stringify(score.value) == value;
  } else {
    return String(score.value) === value;
  }
};
const filterText = (descriptor, sample, value) => {
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
        return String(score.value) === value;
      }
    }
  }
};
const filterFnsForType = {
  [kScoreTypeCategorical]: filterCategory,
  [kScoreTypeNumeric]: filterText
};
function App({
  api: api2,
  initialState: initialState2 = void 0,
  saveInitialState = void 0,
  pollForLogs = true
}) {
  var _a2, _b2, _c, _d, _e, _f, _g, _h, _i, _j, _k, _l, _m;
  const [logs, setLogs] = h(
    (initialState2 == null ? void 0 : initialState2.logs) || { log_dir: "", files: [] }
  );
  const [selectedLogIndex, setSelectedLogIndex] = h(
    (initialState2 == null ? void 0 : initialState2.selectedLogIndex) !== void 0 ? initialState2.selectedLogIndex : -1
  );
  const [logHeaders, setLogHeaders] = h((initialState2 == null ? void 0 : initialState2.logHeaders) || {});
  const [headersLoading, setHeadersLoading] = h(
    (initialState2 == null ? void 0 : initialState2.headersLoading) || false
  );
  const [selectedLog, setSelectedLog] = h(
    (initialState2 == null ? void 0 : initialState2.selectedLog) || {
      contents: void 0,
      name: void 0
    }
  );
  const [selectedWorkspaceTab, setSelectedWorkspaceTab] = h(
    (initialState2 == null ? void 0 : initialState2.selectedWorkspaceTab) || kEvalWorkspaceTabId
  );
  const [selectedSampleIndex, setSelectedSampleIndex] = h(
    (initialState2 == null ? void 0 : initialState2.selectedSampleIndex) !== void 0 ? initialState2.selectedSampleIndex : -1
  );
  const [selectedSample, setSelectedSample] = h(
    initialState2 == null ? void 0 : initialState2.selectedSample
  );
  const [sampleStatus, setSampleStatus] = h(initialState2 == null ? void 0 : initialState2.sampleStatus);
  const [sampleError, setSampleError] = h(initialState2 == null ? void 0 : initialState2.sampleError);
  const [selectedSampleTab, setSelectedSampleTab] = h(
    initialState2 == null ? void 0 : initialState2.selectedSampleTab
  );
  const sampleScrollPosition = A((initialState2 == null ? void 0 : initialState2.sampleScrollPosition) || 0);
  const loadingSampleIndexRef = A(null);
  const workspaceTabScrollPosition = A(
    (initialState2 == null ? void 0 : initialState2.workspaceTabScrollPosition) || {}
  );
  const [showingSampleDialog, setShowingSampleDialog] = h(
    initialState2 == null ? void 0 : initialState2.showingSampleDialog
  );
  const [status, setStatus] = h(
    (initialState2 == null ? void 0 : initialState2.status) || {
      loading: true,
      error: void 0
    }
  );
  const [capabilities, setCapabilities] = h(
    (initialState2 == null ? void 0 : initialState2.capabilities) || {
      downloadFiles: true,
      webWorkers: true
    }
  );
  const [offcanvas, setOffcanvas] = h((initialState2 == null ? void 0 : initialState2.offcanvas) || false);
  const [showFind, setShowFind] = h((initialState2 == null ? void 0 : initialState2.showFind) || false);
  const [filter, setFilter] = h((initialState2 == null ? void 0 : initialState2.filter) || {});
  const [epoch, setEpoch] = h((initialState2 == null ? void 0 : initialState2.epoch) || "all");
  const [sort, setSort] = h((initialState2 == null ? void 0 : initialState2.sort) || kDefaultSort);
  const [scores, setScores] = h((initialState2 == null ? void 0 : initialState2.scores) || []);
  const [score, setScore] = h(initialState2 == null ? void 0 : initialState2.score);
  const [filteredSamples, setFilteredSamples] = h(
    (initialState2 == null ? void 0 : initialState2.filteredSamples) || []
  );
  const [groupBy, setGroupBy] = h((initialState2 == null ? void 0 : initialState2.groupBy) || "none");
  const [groupByOrder, setGroupByOrder] = h(
    (initialState2 == null ? void 0 : initialState2.groupByOrder) || "asc"
  );
  const afterBodyElements = [];
  const saveState = q(() => {
    const state = {
      logs,
      selectedLogIndex,
      logHeaders,
      headersLoading,
      selectedLog,
      selectedSampleIndex,
      selectedWorkspaceTab,
      selectedSample,
      sampleStatus,
      sampleError,
      selectedSampleTab,
      showingSampleDialog,
      status,
      capabilities,
      offcanvas,
      showFind,
      filter,
      epoch,
      sort,
      scores,
      score,
      filteredSamples,
      groupBy,
      groupByOrder,
      sampleScrollPosition: sampleScrollPosition.current,
      workspaceTabScrollPosition: workspaceTabScrollPosition.current
    };
    if (saveInitialState) {
      saveInitialState(state);
    }
  }, [
    logs,
    selectedLogIndex,
    logHeaders,
    headersLoading,
    selectedLog,
    selectedSampleIndex,
    selectedWorkspaceTab,
    selectedSample,
    sampleStatus,
    sampleError,
    selectedSampleTab,
    showingSampleDialog,
    status,
    capabilities,
    offcanvas,
    showFind,
    filter,
    epoch,
    sort,
    scores,
    score,
    filteredSamples,
    groupBy,
    groupByOrder
  ]);
  const saveStateRef = A(saveState);
  y(() => {
    saveStateRef.current = saveState;
  }, [saveState]);
  const setSampleScrollPosition = q(
    debounce((position) => {
      sampleScrollPosition.current = position;
      saveStateRef.current();
    }, 1e3),
    []
  );
  const setWorkspaceTabScrollPosition = q(
    debounce((tab, position) => {
      if (workspaceTabScrollPosition.current[tab] !== position) {
        workspaceTabScrollPosition.current = {
          ...workspaceTabScrollPosition.current,
          [tab]: position
        };
        saveStateRef.current();
      }
    }, 1e3),
    []
  );
  y(() => {
    saveStateRef.current();
  }, [
    logs,
    selectedLogIndex,
    logHeaders,
    headersLoading,
    selectedLog,
    selectedSampleIndex,
    selectedWorkspaceTab,
    selectedSample,
    sampleStatus,
    sampleError,
    selectedSampleTab,
    showingSampleDialog,
    status,
    capabilities,
    offcanvas,
    showFind,
    filter,
    epoch,
    sort,
    scores,
    score,
    filteredSamples,
    groupBy,
    groupByOrder
  ]);
  const handleSampleShowingDialog = q(
    (show) => {
      setShowingSampleDialog(show);
      if (!show) {
        setSelectedSample(void 0);
        setSelectedSampleTab(void 0);
      }
    },
    [
      setShowingSampleDialog,
      setSelectedSample,
      setSelectedSampleTab,
      selectedSample
    ]
  );
  y(() => {
    var _a3;
    const samples = ((_a3 = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _a3.sampleSummaries) || [];
    const filtered = samples.filter((sample) => {
      if (epoch && epoch !== "all") {
        if (epoch !== sample.epoch + "") {
          return false;
        }
      }
      const filterFn = filterFnForType(filter);
      if (filterFn && filter.value) {
        return filterFn(samplesDescriptor, sample, filter.value);
      } else {
        return true;
      }
    });
    const { sorted, order: order2 } = sortSamples(sort, filtered, samplesDescriptor);
    let grouping = "none";
    if ((samplesDescriptor == null ? void 0 : samplesDescriptor.epochs) > 1) {
      if (byEpoch(sort) || epoch !== "all") {
        grouping = "epoch";
      } else if (bySample(sort)) {
        grouping = "sample";
      }
    }
    setFilteredSamples(sorted);
    setGroupBy(grouping);
    setGroupByOrder(order2);
  }, [selectedLog, filter, sort, epoch]);
  const samplesDescriptor = T(() => {
    var _a3, _b3, _c2, _d2;
    return createsSamplesDescriptor(
      scores,
      (_a3 = selectedLog.contents) == null ? void 0 : _a3.sampleSummaries,
      ((_d2 = (_c2 = (_b3 = selectedLog.contents) == null ? void 0 : _b3.eval) == null ? void 0 : _c2.config) == null ? void 0 : _d2.epochs) || 1,
      score
    );
  }, [selectedLog, scores, score]);
  const refreshSampleTab = q(
    (sample) => {
      if (selectedSampleTab === void 0) {
        const defaultTab = sample.events && sample.events.length > 0 ? kSampleTranscriptTabId : kSampleMessagesTabId;
        setSelectedSampleTab(defaultTab);
      }
    },
    [selectedSampleTab, showingSampleDialog]
  );
  const mainAppRef = A();
  y(() => {
    if (!selectedLog || selectedSampleIndex === -1) {
      setSelectedSample(void 0);
      return;
    }
    if (loadingSampleIndexRef.current === selectedSampleIndex) {
      return;
    }
    if (!showingSampleDialog && selectedLog.contents.sampleSummaries.length > 1) {
      return;
    }
    if (selectedSampleIndex < filteredSamples.length) {
      const summary = filteredSamples[selectedSampleIndex];
      if (selectedSample && selectedSample.id === summary.id && selectedSample.epoch === summary.epoch) {
        return;
      }
      loadingSampleIndexRef.current = selectedSampleIndex;
      setSampleStatus("loading");
      setSampleError(void 0);
      api2.get_log_sample(selectedLog.name, summary.id, summary.epoch).then((sample) => {
        if (sample.transcript) {
          sample.events = sample.transcript.events;
          sample.attachments = sample.transcript.content;
        }
        sample.attachments = sample.attachments || {};
        sample.input = resolveAttachments(sample.input, sample.attachments);
        sample.messages = resolveAttachments(
          sample.messages,
          sample.attachments
        );
        sample.events = resolveAttachments(sample.events, sample.attachments);
        sample.attachments = {};
        sampleScrollPosition.current = 0;
        setSelectedSample(sample);
        refreshSampleTab(sample);
        setSampleStatus("ok");
        loadingSampleIndexRef.current = null;
      }).catch((e2) => {
        setSampleStatus("error");
        setSampleError(e2);
        sampleScrollPosition.current = 0;
        setSelectedSample(void 0);
        loadingSampleIndexRef.current = null;
      });
    }
  }, [
    selectedSample,
    selectedSampleIndex,
    showingSampleDialog,
    selectedLog,
    filteredSamples,
    setSelectedSample,
    setSampleStatus,
    setSampleError
  ]);
  y(() => {
    const loadHeaders = async () => {
      setHeadersLoading(true);
      const chunkSize = 8;
      const fileLists = [];
      for (let i = 0; i < logs.files.length; i += chunkSize) {
        let chunk = logs.files.slice(i, i + chunkSize).map((log) => log.name);
        fileLists.push(chunk);
      }
      try {
        for (const fileList of fileLists) {
          const headers = await api2.get_log_headers(fileList);
          setLogHeaders((prev) => {
            const updatedHeaders = {};
            headers.forEach((header, index) => {
              const logFile = fileList[index];
              updatedHeaders[logFile] = header;
            });
            return { ...prev, ...updatedHeaders };
          });
          if (headers.length === chunkSize) {
            await sleep(5e3);
          }
        }
      } catch (e2) {
        console.log(e2);
        setStatus({ loading: false, error: e2 });
      }
      setHeadersLoading(false);
    };
    loadHeaders();
  }, [logs, setStatus, setLogHeaders, setHeadersLoading]);
  const resetWorkspace = q(
    /**
     * @param {import("./api/Types.mjs").EvalSummary} log
     */
    (log) => {
      const hasSamples = !!log.sampleSummaries && log.sampleSummaries.length > 0;
      const showSamples = log.status !== "error" && hasSamples;
      setSelectedWorkspaceTab(
        showSamples ? kEvalWorkspaceTabId : kInfoWorkspaceTabId
      );
      const scorer = defaultScorer(log);
      const scorers = defaultScorers(log);
      setScores(scorers);
      setScore(scorer);
      setEpoch("all");
      setFilter({});
      setSort(kDefaultSort);
      setSelectedSampleTab(void 0);
      setSelectedSample(void 0);
      if (showSamples) {
        setSelectedSampleIndex(0);
      } else {
        setSelectedSampleIndex(-1);
      }
      workspaceTabScrollPosition.current = {};
    },
    [setSelectedWorkspaceTab]
  );
  y(() => {
    const loadSpecificLog = async () => {
      const targetLog = logs.files[selectedLogIndex];
      if (targetLog && (!selectedLog || selectedLog.name !== targetLog.name)) {
        try {
          setStatus({ loading: true, error: void 0 });
          const logContents = await loadLog(targetLog.name);
          if (logContents) {
            const log = logContents;
            setSelectedLog({
              contents: log,
              name: targetLog.name
            });
            resetWorkspace(log);
            setStatus({ loading: false, error: void 0 });
          }
        } catch (e2) {
          console.log(e2);
          setStatus({ loading: false, error: e2 });
        }
      } else if (logs.log_dir && logs.files.length === 0) {
        setStatus({
          loading: false,
          error: new Error(
            `No log files to display in the directory ${logs.log_dir}. Are you sure this is the correct log directory?`
          )
        });
      }
    };
    loadSpecificLog();
  }, [
    selectedLogIndex,
    logs,
    capabilities,
    selectedLog,
    setSelectedLog,
    setStatus
  ]);
  const loadLogs = async () => {
    try {
      const result = await api2.get_log_paths();
      return result;
    } catch (e2) {
      console.log(e2);
      setStatus({ loading: false, error: e2 });
    }
  };
  const loadLog = async (logFileName) => {
    try {
      const logContents = await api2.get_log_summary(logFileName);
      return logContents;
    } catch (e2) {
      console.log(e2);
      setStatus({ loading: false, error: e2 });
    }
  };
  const refreshLog = q(async () => {
    try {
      setStatus({ loading: true, error: void 0 });
      const targetLog = logs.files[selectedLogIndex];
      const logContents = await loadLog(targetLog.name);
      if (logContents) {
        const log = logContents;
        if (log.status !== "started") {
          setLogHeaders((prev) => {
            const updatedState = { ...prev };
            const freshHeaders = {
              eval: log.eval,
              plan: log.plan,
              results: log.results,
              stats: log.stats,
              status: log.status,
              version: log.version
            };
            updatedState[targetLog.name] = freshHeaders;
            return updatedState;
          });
        }
        setSelectedLog({
          contents: log,
          name: targetLog.name
        });
        resetWorkspace(log);
        setStatus({ loading: false, error: void 0 });
      }
    } catch (e2) {
      console.log(e2);
      setStatus({ loading: false, error: e2 });
    }
  }, [logs, selectedLogIndex, setStatus, setSelectedLog, setLogHeaders]);
  const showLogFile = q(
    async (logUrl) => {
      const index = logs.files.findIndex((val) => {
        return logUrl.endsWith(val.name);
      });
      if (index > -1) {
        setSelectedLogIndex(index);
      } else {
        const result = await loadLogs();
        const idx = result.files.findIndex((file) => {
          return logUrl.endsWith(file.name);
        });
        setLogs(result);
        setSelectedLogIndex(idx > -1 ? idx : 0);
      }
    },
    [logs, setSelectedLogIndex, setLogs]
  );
  const refreshLogList = q(async () => {
    const currentLog = logs.files[selectedLogIndex > -1 ? selectedLogIndex : 0];
    const refreshedLogs = await loadLogs();
    const newIndex = refreshedLogs.files.findIndex((file) => {
      return currentLog.name.endsWith(file.name);
    });
    setLogs(refreshedLogs);
    setSelectedLogIndex(newIndex);
  }, [logs, selectedLogIndex, setSelectedLogIndex, setLogs]);
  const onMessage = T(() => {
    return async (e2) => {
      const type = e2.data.type || e2.data.message;
      switch (type) {
        case "updateState": {
          if (e2.data.url) {
            const decodedUrl = decodeURIComponent(e2.data.url);
            showLogFile(decodedUrl);
          }
          break;
        }
        case "backgroundUpdate": {
          const decodedUrl = decodeURIComponent(e2.data.url);
          const log_dir = e2.data.log_dir;
          const isFocused = document.hasFocus();
          if (!isFocused) {
            if (log_dir === logs.log_dir) {
              showLogFile(decodedUrl);
            } else {
              api2.open_log_file(e2.data.url, e2.data.log_dir);
            }
          } else {
            refreshLogList();
          }
          break;
        }
      }
    };
  }, [logs, showLogFile, refreshLogList]);
  y(() => {
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
    };
  }, [onMessage]);
  y(() => {
    const loadLogsAndState = async () => {
      const urlParams = new URLSearchParams(window.location.search);
      const extensionVersionEl = document.querySelector(
        'meta[name="inspect-extension:version"]'
      );
      const extensionVersion = extensionVersionEl ? extensionVersionEl.getAttribute("content") : void 0;
      if (isVscode()) {
        if (!extensionVersion) {
          setCapabilities({ downloadFiles: false, webWorkers: false });
        }
      }
      setOffcanvas(true);
      const logPath = urlParams.get("task_file");
      const resolvedLogPath = logPath ? logPath.replace(" ", "+") : logPath;
      const load = resolvedLogPath ? async () => {
        return {
          log_dir: "",
          files: [{ name: resolvedLogPath }]
        };
      } : loadLogs;
      const embeddedState = document.getElementById("logview-state");
      if (embeddedState) {
        const state = JSON.parse(embeddedState.textContent);
        onMessage({ data: state });
      } else {
        const result = await load();
        setLogs(result);
        const log_file = urlParams.get("log_file");
        if (log_file) {
          const index = result.files.findIndex((val) => {
            return log_file.endsWith(val.name);
          });
          if (index > -1) {
            setSelectedLogIndex(index);
          }
        } else if (selectedLogIndex === -1) {
          setSelectedLogIndex(0);
        }
      }
      new ClipboardJS(".clipboard-button,.copy-button");
      if (pollForLogs) {
        setInterval(() => {
          api2.client_events().then(async (events) => {
            if (events.includes("reload")) {
              window.location.reload();
            }
            if (events.includes("refresh-evals")) {
              const logs2 = await load();
              setLogs(logs2);
              setSelectedLogIndex(0);
            }
          });
        }, 1e3);
      }
    };
    loadLogsAndState();
  }, []);
  const fullScreen = logs.files.length === 1 && !logs.log_dir;
  const sidebar = !fullScreen && selectedLog.contents ? m$1`
          <${Sidebar}
            logs=${logs}
            logHeaders=${logHeaders}
            loading=${headersLoading}
            offcanvas=${offcanvas}
            selectedIndex=${selectedLogIndex}
            onSelectedIndexChanged=${(index) => {
    setSelectedLogIndex(index);
    var myOffcanvas = document.getElementById("sidebarOffCanvas");
    var bsOffcanvas = Offcanvas.getInstance(myOffcanvas);
    if (bsOffcanvas) {
      bsOffcanvas.hide();
    }
  }}
          />
        ` : "";
  const fullScreenClz = fullScreen ? " full-screen" : "";
  const offcanvasClz = offcanvas ? " off-canvas" : "";
  const hideFind = q(() => {
    clearDocumentSelection();
    if (showFind) {
      setShowFind(false);
    }
  }, [showFind, setShowFind]);
  const showToggle = logs.files.length > 1 || logs.log_dir;
  const sampleMode = ((_a2 = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _a2.sampleSummaries) === void 0 || selectedLog.contents.sampleSummaries.length === 0 ? "none" : selectedLog.contents.sampleSummaries.length === 1 ? "single" : "many";
  return m$1`
    <${AppErrorBoundary}>
    ${sidebar}
    <div ref=${mainAppRef} class="app-main-grid${fullScreenClz}${offcanvasClz}" tabIndex="0" onKeyDown=${(e2) => {
    if (!getVscodeApi()) {
      return;
    }
    if ((e2.ctrlKey || e2.metaKey) && e2.key === "f") {
      setShowFind(true);
    } else if (e2.key === "Escape") {
      hideFind();
    }
  }}>
      ${showFind ? m$1`<${FindBand} hideBand=${hideFind} />` : ""}
      <${ProgressBar} animating=${status.loading}  containerStyle=${{
    background: "var(--bs-light)",
    marginBottom: "-1px"
  }}/>
      ${status.error ? m$1`<${ErrorPanel}
              title="An error occurred while loading this task."
              error=${status.error}
            />` : m$1`<${WorkSpace}
              task_id=${(_c = (_b2 = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _b2.eval) == null ? void 0 : _c.task_id}
              logFileName=${selectedLog == null ? void 0 : selectedLog.name}
              evalStatus=${(_d = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _d.status}
              evalError=${(_e = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _e.error}
              evalVersion=${(_f = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _f.version}
              evalSpec=${(_g = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _g.eval}
              evalPlan=${(_h = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _h.plan}
              evalStats=${(_i = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _i.stats}
              evalResults=${(_j = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _j.results}
              showToggle=${showToggle}
              samples=${filteredSamples}
              sampleMode=${sampleMode}
              groupBy=${groupBy}
              groupByOrder=${groupByOrder}
              sampleStatus=${sampleStatus}
              sampleError=${sampleError}
              samplesDescriptor=${samplesDescriptor}
              refreshLog=${refreshLog}
              offcanvas=${offcanvas}
              capabilities=${capabilities}
              selected=${selectedLogIndex}
              selectedSample=${selectedSample}
              selectedSampleIndex=${selectedSampleIndex}
              setSelectedSampleIndex=${setSelectedSampleIndex}
              showingSampleDialog=${showingSampleDialog}
              setShowingSampleDialog=${handleSampleShowingDialog}
              selectedTab=${selectedWorkspaceTab}
              setSelectedTab=${setSelectedWorkspaceTab}
              selectedSampleTab=${selectedSampleTab}
              setSelectedSampleTab=${setSelectedSampleTab}
              sort=${sort}
              setSort=${setSort}
              epochs=${(_m = (_l = (_k = selectedLog == null ? void 0 : selectedLog.contents) == null ? void 0 : _k.eval) == null ? void 0 : _l.config) == null ? void 0 : _m.epochs}
              epoch=${epoch}
              setEpoch=${setEpoch}
              filter=${filter}
              setFilter=${setFilter}
              score=${score}
              setScore=${setScore}
              scores=${scores}
              sampleScrollPositionRef=${sampleScrollPosition}
              setSampleScrollPosition=${setSampleScrollPosition}
              workspaceTabScrollPositionRef=${workspaceTabScrollPosition}
              setWorkspaceTabScrollPosition=${setWorkspaceTabScrollPosition}
            />`}
    </div>
    ${afterBodyElements}
    </${AppErrorBoundary}>
  `;
}
const defaultScorer = (log) => {
  var _a2, _b2, _c;
  const scorer = ((_a2 = log.results) == null ? void 0 : _a2.scores[0]) ? {
    name: (_b2 = log.results) == null ? void 0 : _b2.scores[0].name,
    scorer: (_c = log.results) == null ? void 0 : _c.scores[0].scorer
  } : log.sampleSummaries.length > 0 ? {
    name: Object.keys(log.sampleSummaries[0].scores)[0],
    scorer: Object.keys(log.sampleSummaries[0].scores)[0]
  } : void 0;
  return scorer;
};
const defaultScorers = (log) => {
  var _a2, _b2;
  if ((_a2 = log.results) == null ? void 0 : _a2.scores) {
    return (((_b2 = log.results) == null ? void 0 : _b2.scores) || []).map((score) => {
      return {
        name: score.name,
        scorer: score.scorer
      };
    }).reduce((accum, scorer) => {
      if (!accum.find((sc) => {
        return scorer.scorer === sc.scorer && scorer.name === sc.name;
      })) {
        accum.push(scorer);
      }
      return accum;
    }, []);
  } else if (log.sampleSummaries && log.sampleSummaries.length > 0) {
    return Object.keys(log.sampleSummaries[0].scores).map((key2) => {
      return {
        name: key2,
        scorer: key2
      };
    });
  } else {
    return [];
  }
};
const vscode = getVscodeApi();
let initialState = void 0;
if (vscode) {
  initialState = vscode.getState();
}
q$1(m$1`<${App}
    api=${api}
    initialState=${initialState}
    saveInitialState=${throttle((state) => {
  const vscode2 = getVscodeApi();
  if (vscode2) {
    vscode2.setState(state);
  }
}, 1e3)}
  />`, document.getElementById("app"));
//# sourceMappingURL=index.js.map
