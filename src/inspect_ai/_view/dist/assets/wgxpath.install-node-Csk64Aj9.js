import { o } from "./chunk-DfAF0w94.js";
const e = globalThis;
var n = o(((exports$1, n2) => {
  (function() {
    var e2 = this;
    function t(e3) {
      var t2 = typeof e3;
      if (t2 == `object`) if (e3) {
        if (e3 instanceof Array) return `array`;
        if (e3 instanceof Object) return t2;
        var n3 = Object.prototype.toString.call(e3);
        if (n3 == `[object Window]`) return `object`;
        if (n3 == `[object Array]` || typeof e3.length == `number` && e3.splice !== void 0 && e3.propertyIsEnumerable !== void 0 && !e3.propertyIsEnumerable(`splice`)) return `array`;
        if (n3 == `[object Function]` || e3.call !== void 0 && e3.propertyIsEnumerable !== void 0 && !e3.propertyIsEnumerable(`call`)) return `function`;
      } else return `null`;
      else if (t2 == `function` && e3.call === void 0) return `object`;
      return t2;
    }
    function r(e3) {
      return typeof e3 == `string`;
    }
    function i(e3, t2, n3) {
      return e3.call.apply(e3.bind, arguments);
    }
    function a(e3, t2, n3) {
      if (!e3) throw Error();
      if (2 < arguments.length) {
        var r2 = Array.prototype.slice.call(arguments, 2);
        return function() {
          var n4 = Array.prototype.slice.call(arguments);
          return Array.prototype.unshift.apply(n4, r2), e3.apply(t2, n4);
        };
      }
      return function() {
        return e3.apply(t2, arguments);
      };
    }
    function o2(e3, t2, n3) {
      return o2 = Function.prototype.bind && Function.prototype.bind.toString().indexOf(`native code`) != -1 ? i : a, o2.apply(null, arguments);
    }
    function s(e3, t2) {
      var n3 = Array.prototype.slice.call(arguments, 1);
      return function() {
        var t3 = n3.slice();
        return t3.push.apply(t3, arguments), e3.apply(this, t3);
      };
    }
    function c(e3) {
      var t2 = D;
      function n3() {
      }
      n3.prototype = t2.prototype, e3.G = t2.prototype, e3.prototype = new n3(), e3.prototype.constructor = e3, e3.F = function(e4, n4, r2) {
        for (var i2 = Array(arguments.length - 2), a2 = 2; a2 < arguments.length; a2++) i2[a2 - 2] = arguments[a2];
        return t2.prototype[n4].apply(e4, i2);
      };
    }
    var l = String.prototype.trim ? function(e3) {
      return e3.trim();
    } : function(e3) {
      return e3.replace(/^[\s\xa0]+|[\s\xa0]+$/g, ``);
    };
    function u(e3, t2) {
      return e3.indexOf(t2) != -1;
    }
    function ee(e3, t2) {
      return e3 < t2 ? -1 : e3 > t2 ? 1 : 0;
    }
    var d = Array.prototype.indexOf ? function(e3, t2, n3) {
      return Array.prototype.indexOf.call(e3, t2, n3);
    } : function(e3, t2, n3) {
      if (n3 = n3 == null ? 0 : 0 > n3 ? Math.max(0, e3.length + n3) : n3, r(e3)) return r(t2) && t2.length == 1 ? e3.indexOf(t2, n3) : -1;
      for (; n3 < e3.length; n3++) if (n3 in e3 && e3[n3] === t2) return n3;
      return -1;
    }, f = Array.prototype.forEach ? function(e3, t2, n3) {
      Array.prototype.forEach.call(e3, t2, n3);
    } : function(e3, t2, n3) {
      for (var i2 = e3.length, a2 = r(e3) ? e3.split(``) : e3, o3 = 0; o3 < i2; o3++) o3 in a2 && t2.call(n3, a2[o3], o3, e3);
    }, te = Array.prototype.filter ? function(e3, t2, n3) {
      return Array.prototype.filter.call(e3, t2, n3);
    } : function(e3, t2, n3) {
      for (var i2 = e3.length, a2 = [], o3 = 0, s2 = r(e3) ? e3.split(``) : e3, c2 = 0; c2 < i2; c2++) if (c2 in s2) {
        var l2 = s2[c2];
        t2.call(n3, l2, c2, e3) && (a2[o3++] = l2);
      }
      return a2;
    }, p = Array.prototype.reduce ? function(e3, t2, n3, r2) {
      return r2 && (t2 = o2(t2, r2)), Array.prototype.reduce.call(e3, t2, n3);
    } : function(e3, t2, n3, r2) {
      var i2 = n3;
      return f(e3, function(n4, a2) {
        i2 = t2.call(r2, i2, n4, a2, e3);
      }), i2;
    }, ne = Array.prototype.some ? function(e3, t2, n3) {
      return Array.prototype.some.call(e3, t2, n3);
    } : function(e3, t2, n3) {
      for (var i2 = e3.length, a2 = r(e3) ? e3.split(``) : e3, o3 = 0; o3 < i2; o3++) if (o3 in a2 && t2.call(n3, a2[o3], o3, e3)) return true;
      return false;
    };
    function re(e3, t2) {
      var n3;
      a: {
        n3 = e3.length;
        for (var i2 = r(e3) ? e3.split(``) : e3, a2 = 0; a2 < n3; a2++) if (a2 in i2 && t2.call(void 0, i2[a2], a2, e3)) {
          n3 = a2;
          break a;
        }
        n3 = -1;
      }
      return 0 > n3 ? null : r(e3) ? e3.charAt(n3) : e3[n3];
    }
    function ie(e3) {
      return Array.prototype.concat.apply(Array.prototype, arguments);
    }
    function ae(e3, t2, n3) {
      return 2 >= arguments.length ? Array.prototype.slice.call(e3, t2) : Array.prototype.slice.call(e3, t2, n3);
    }
    var m;
    a: {
      var oe = e2.navigator;
      if (oe) {
        var se = oe.userAgent;
        if (se) {
          m = se;
          break a;
        }
      }
      m = ``;
    }
    var ce = u(m, `Opera`) || u(m, `OPR`), h = u(m, `Trident`) || u(m, `MSIE`), le = u(m, `Edge`), ue = u(m, `Gecko`) && !(u(m.toLowerCase(), `webkit`) && !u(m, `Edge`)) && !(u(m, `Trident`) || u(m, `MSIE`)) && !u(m, `Edge`), de = u(m.toLowerCase(), `webkit`) && !u(m, `Edge`);
    function fe() {
      var t2 = e2.document;
      return t2 ? t2.documentMode : void 0;
    }
    var g;
    a: {
      var pe = ``, me = (function() {
        var e3 = m;
        if (ue) return /rv\:([^\);]+)(\)|;)/.exec(e3);
        if (le) return /Edge\/([\d\.]+)/.exec(e3);
        if (h) return /\b(?:MSIE|rv)[: ]([^\);]+)(\)|;)/.exec(e3);
        if (de) return /WebKit\/(\S+)/.exec(e3);
        if (ce) return /(?:Version)[ \/]?(\S+)/.exec(e3);
      })();
      if (me && (pe = me ? me[1] : ``), h) {
        var he = fe();
        if (he != null && he > parseFloat(pe)) {
          g = String(he);
          break a;
        }
      }
      g = pe;
    }
    var ge = {};
    function _e(e3) {
      if (!ge[e3]) {
        for (var t2 = 0, n3 = l(String(g)).split(`.`), r2 = l(String(e3)).split(`.`), i2 = Math.max(n3.length, r2.length), a2 = 0; t2 == 0 && a2 < i2; a2++) {
          var o3 = n3[a2] || ``, s2 = r2[a2] || ``, c2 = /(\d*)(\D*)/g, u2 = /(\d*)(\D*)/g;
          do {
            var d2 = c2.exec(o3) || [``, ``, ``], f2 = u2.exec(s2) || [``, ``, ``];
            if (d2[0].length == 0 && f2[0].length == 0) break;
            t2 = ee(d2[1].length == 0 ? 0 : parseInt(d2[1], 10), f2[1].length == 0 ? 0 : parseInt(f2[1], 10)) || ee(d2[2].length == 0, f2[2].length == 0) || ee(d2[2], f2[2]);
          } while (t2 == 0);
        }
        ge[e3] = 0 <= t2;
      }
    }
    var ve = e2.document, _ = ve && h ? fe() || (ve.compatMode == `CSS1Compat` ? parseInt(g, 10) : 5) : void 0, v = h && !(9 <= Number(_)), ye = h && !(8 <= Number(_));
    function y(e3, t2, n3, r2) {
      this.a = e3, this.nodeName = n3, this.nodeValue = r2, this.nodeType = 2, this.parentNode = this.ownerElement = t2;
    }
    function be(e3, t2) {
      var n3 = ye && t2.nodeName == `href` ? e3.getAttribute(t2.nodeName, 2) : t2.nodeValue;
      return new y(t2, e3, t2.nodeName, n3);
    }
    function b(e3) {
      var t2 = null, n3 = e3.nodeType;
      if (n3 == 1 && (t2 = e3.textContent, t2 = t2 == null || t2 == null ? e3.innerText : t2, t2 = t2 == null || t2 == null ? `` : t2), typeof t2 != `string`) if (v && e3.nodeName.toLowerCase() == `title` && n3 == 1) t2 = e3.text;
      else if (n3 == 9 || n3 == 1) {
        e3 = n3 == 9 ? e3.documentElement : e3.firstChild;
        for (var n3 = 0, r2 = [], t2 = ``; e3; ) {
          do
            e3.nodeType != 1 && (t2 += e3.nodeValue), v && e3.nodeName.toLowerCase() == `title` && (t2 += e3.text), r2[n3++] = e3;
          while (e3 = e3.firstChild);
          for (; n3 && !(e3 = r2[--n3].nextSibling); ) ;
        }
      } else t2 = e3.nodeValue;
      return `` + t2;
    }
    function x(e3, t2, n3) {
      if (t2 === null) return true;
      try {
        if (!e3.getAttribute) return false;
      } catch {
        return false;
      }
      return ye && t2 == `class` && (t2 = `className`), n3 == null ? !!e3.getAttribute(t2) : e3.getAttribute(t2, 2) == n3;
    }
    function S(e3, t2, n3, i2, a2) {
      return (v ? xe : Se).call(null, e3, t2, r(n3) ? n3 : null, r(i2) ? i2 : null, a2 || new C());
    }
    function xe(e3, t2, n3, r2, i2) {
      if (e3 instanceof W || e3.b == 8 || n3 && e3.b === null) {
        var a2 = t2.all;
        if (!a2 || (e3 = Ee(e3), e3 != `*` && (a2 = t2.getElementsByTagName(e3), !a2))) return i2;
        if (n3) {
          for (var o3 = [], s2 = 0; t2 = a2[s2++]; ) x(t2, n3, r2) && o3.push(t2);
          a2 = o3;
        }
        for (s2 = 0; t2 = a2[s2++]; ) e3 == `*` && t2.tagName == `!` || w(i2, t2);
        return i2;
      }
      return Te(e3, t2, n3, r2, i2), i2;
    }
    function Se(e3, t2, n3, r2, i2) {
      return t2.getElementsByName && r2 && n3 == `name` && !h ? (t2 = t2.getElementsByName(r2), f(t2, function(t3) {
        e3.a(t3) && w(i2, t3);
      })) : t2.getElementsByClassName && r2 && n3 == `class` ? (t2 = t2.getElementsByClassName(r2), f(t2, function(t3) {
        t3.className == r2 && e3.a(t3) && w(i2, t3);
      })) : e3 instanceof z ? Te(e3, t2, n3, r2, i2) : t2.getElementsByTagName && (t2 = t2.getElementsByTagName(e3.f()), f(t2, function(e4) {
        x(e4, n3, r2) && w(i2, e4);
      })), i2;
    }
    function Ce(e3, t2, n3, r2, i2) {
      var a2;
      if ((e3 instanceof W || e3.b == 8 || n3 && e3.b === null) && (a2 = t2.childNodes)) {
        var o3 = Ee(e3);
        return o3 != `*` && (a2 = te(a2, function(e4) {
          return e4.tagName && e4.tagName.toLowerCase() == o3;
        }), !a2) ? i2 : (n3 && (a2 = te(a2, function(e4) {
          return x(e4, n3, r2);
        })), f(a2, function(e4) {
          o3 == `*` && (e4.tagName == `!` || o3 == `*` && e4.nodeType != 1) || w(i2, e4);
        }), i2);
      }
      return we(e3, t2, n3, r2, i2);
    }
    function we(e3, t2, n3, r2, i2) {
      for (t2 = t2.firstChild; t2; t2 = t2.nextSibling) x(t2, n3, r2) && e3.a(t2) && w(i2, t2);
      return i2;
    }
    function Te(e3, t2, n3, r2, i2) {
      for (t2 = t2.firstChild; t2; t2 = t2.nextSibling) x(t2, n3, r2) && e3.a(t2) && w(i2, t2), Te(e3, t2, n3, r2, i2);
    }
    function Ee(e3) {
      if (e3 instanceof z) {
        if (e3.b == 8) return `!`;
        if (e3.b === null) return `*`;
      }
      return e3.f();
    }
    !ue && !h || h && 9 <= Number(_) || ue && _e(`1.9.1`), h && _e(`9`);
    function De(e3, t2) {
      if (!e3 || !t2) return false;
      if (e3.contains && t2.nodeType == 1) return e3 == t2 || e3.contains(t2);
      if (e3.compareDocumentPosition !== void 0) return e3 == t2 || !!(e3.compareDocumentPosition(t2) & 16);
      for (; t2 && e3 != t2; ) t2 = t2.parentNode;
      return t2 == e3;
    }
    function Oe(t2, n3) {
      if (t2 == n3) return 0;
      if (t2.compareDocumentPosition) return t2.compareDocumentPosition(n3) & 2 ? 1 : -1;
      if (h && !(9 <= Number(_))) {
        if (t2.nodeType == 9) return -1;
        if (n3.nodeType == 9) return 1;
      }
      if (`sourceIndex` in t2 || t2.parentNode && `sourceIndex` in t2.parentNode) {
        var r2 = t2.nodeType == 1, i2 = n3.nodeType == 1;
        if (r2 && i2) return t2.sourceIndex - n3.sourceIndex;
        var a2 = t2.parentNode, o3 = n3.parentNode;
        return a2 == o3 ? Ae(t2, n3) : !r2 && De(a2, n3) ? -1 * ke(t2, n3) : !i2 && De(o3, t2) ? ke(n3, t2) : (r2 ? t2.sourceIndex : a2.sourceIndex) - (i2 ? n3.sourceIndex : o3.sourceIndex);
      }
      return i2 = t2.nodeType == 9 ? t2 : t2.ownerDocument || t2.document, r2 = i2.createRange(), r2.selectNode(t2), r2.collapse(true), i2 = i2.createRange(), i2.selectNode(n3), i2.collapse(true), r2.compareBoundaryPoints(e2.Range.START_TO_END, i2);
    }
    function ke(e3, t2) {
      var n3 = e3.parentNode;
      if (n3 == t2) return -1;
      for (var r2 = t2; r2.parentNode != n3; ) r2 = r2.parentNode;
      return Ae(r2, e3);
    }
    function Ae(e3, t2) {
      for (var n3 = t2; n3 = n3.previousSibling; ) if (n3 == e3) return -1;
      return 1;
    }
    function C() {
      this.b = this.a = null, this.l = 0;
    }
    function je(e3) {
      this.node = e3, this.a = this.b = null;
    }
    function Me(e3, t2) {
      if (!e3.a) return t2;
      if (!t2.a) return e3;
      for (var n3 = e3.a, r2 = t2.a, i2 = null, a2 = null, o3 = 0; n3 && r2; ) {
        var a2 = n3.node, s2 = r2.node;
        a2 == s2 || a2 instanceof y && s2 instanceof y && a2.a == s2.a ? (a2 = n3, n3 = n3.a, r2 = r2.a) : 0 < Oe(n3.node, r2.node) ? (a2 = r2, r2 = r2.a) : (a2 = n3, n3 = n3.a), (a2.b = i2) ? i2.a = a2 : e3.a = a2, i2 = a2, o3++;
      }
      for (a2 = n3 || r2; a2; ) a2.b = i2, i2 = i2.a = a2, o3++, a2 = a2.a;
      return e3.b = i2, e3.l = o3, e3;
    }
    function Ne(e3, t2) {
      var n3 = new je(t2);
      n3.a = e3.a, e3.b ? e3.a.b = n3 : e3.a = e3.b = n3, e3.a = n3, e3.l++;
    }
    function w(e3, t2) {
      var n3 = new je(t2);
      n3.b = e3.b, e3.a ? e3.b.a = n3 : e3.a = e3.b = n3, e3.b = n3, e3.l++;
    }
    function Pe(e3) {
      return (e3 = e3.a) ? e3.node : null;
    }
    function Fe(e3) {
      return (e3 = Pe(e3)) ? b(e3) : ``;
    }
    function T(e3, t2) {
      return new Ie(e3, !!t2);
    }
    function Ie(e3, t2) {
      this.f = e3, this.b = (this.c = t2) ? e3.b : e3.a, this.a = null;
    }
    function E(e3) {
      var t2 = e3.b;
      if (t2 == null) return null;
      var n3 = e3.a = t2;
      return e3.b = e3.c ? t2.b : t2.a, n3.node;
    }
    function D(e3) {
      this.i = e3, this.b = this.g = false, this.f = null;
    }
    function O(e3) {
      return `
  ` + e3.toString().split(`
`).join(`
  `);
    }
    function Le(e3, t2) {
      e3.g = t2;
    }
    function Re(e3, t2) {
      e3.b = t2;
    }
    function k(e3, t2) {
      var n3 = e3.a(t2);
      return n3 instanceof C ? +Fe(n3) : +n3;
    }
    function A(e3, t2) {
      var n3 = e3.a(t2);
      return n3 instanceof C ? Fe(n3) : `` + n3;
    }
    function j(e3, t2) {
      var n3 = e3.a(t2);
      return n3 instanceof C ? !!n3.l : !!n3;
    }
    function M(e3, t2, n3) {
      D.call(this, e3.i), this.c = e3, this.h = t2, this.o = n3, this.g = t2.g || n3.g, this.b = t2.b || n3.b, this.c == Ve && (n3.b || n3.g || n3.i == 4 || n3.i == 0 || !t2.f ? t2.b || t2.g || t2.i == 4 || t2.i == 0 || !n3.f || (this.f = { name: n3.f.name, s: t2 }) : this.f = { name: t2.f.name, s: n3 });
    }
    c(M);
    function N(e3, t2, n3, r2, i2) {
      t2 = t2.a(r2), n3 = n3.a(r2);
      var a2;
      if (t2 instanceof C && n3 instanceof C) {
        for (t2 = T(t2), r2 = E(t2); r2; r2 = E(t2)) for (i2 = T(n3), a2 = E(i2); a2; a2 = E(i2)) if (e3(b(r2), b(a2))) return true;
        return false;
      }
      if (t2 instanceof C || n3 instanceof C) {
        t2 instanceof C ? (i2 = t2, r2 = n3) : (i2 = n3, r2 = t2), a2 = T(i2);
        for (var o3 = typeof r2, s2 = E(a2); s2; s2 = E(a2)) {
          switch (o3) {
            case `number`:
              s2 = +b(s2);
              break;
            case `boolean`:
              s2 = !!b(s2);
              break;
            case `string`:
              s2 = b(s2);
              break;
            default:
              throw Error(`Illegal primitive type for comparison.`);
          }
          if (i2 == t2 && e3(s2, r2) || i2 == n3 && e3(r2, s2)) return true;
        }
        return false;
      }
      return i2 ? typeof t2 == `boolean` || typeof n3 == `boolean` ? e3(!!t2, !!n3) : typeof t2 == `number` || typeof n3 == `number` ? e3(+t2, +n3) : e3(t2, n3) : e3(+t2, +n3);
    }
    M.prototype.a = function(e3) {
      return this.c.m(this.h, this.o, e3);
    }, M.prototype.toString = function() {
      var e3 = `Binary Expression: ` + this.c, e3 = e3 + O(this.h);
      return e3 += O(this.o);
    };
    function ze(e3, t2, n3, r2) {
      this.a = e3, this.w = t2, this.i = n3, this.m = r2;
    }
    ze.prototype.toString = function() {
      return this.a;
    };
    var Be = {};
    function P(e3, t2, n3, r2) {
      if (Be.hasOwnProperty(e3)) throw Error(`Binary operator already created: ` + e3);
      return e3 = new ze(e3, t2, n3, r2), Be[e3.toString()] = e3;
    }
    P(`div`, 6, 1, function(e3, t2, n3) {
      return k(e3, n3) / k(t2, n3);
    }), P(`mod`, 6, 1, function(e3, t2, n3) {
      return k(e3, n3) % k(t2, n3);
    }), P(`*`, 6, 1, function(e3, t2, n3) {
      return k(e3, n3) * k(t2, n3);
    }), P(`+`, 5, 1, function(e3, t2, n3) {
      return k(e3, n3) + k(t2, n3);
    }), P(`-`, 5, 1, function(e3, t2, n3) {
      return k(e3, n3) - k(t2, n3);
    }), P(`<`, 4, 2, function(e3, t2, n3) {
      return N(function(e4, t3) {
        return e4 < t3;
      }, e3, t2, n3);
    }), P(`>`, 4, 2, function(e3, t2, n3) {
      return N(function(e4, t3) {
        return e4 > t3;
      }, e3, t2, n3);
    }), P(`<=`, 4, 2, function(e3, t2, n3) {
      return N(function(e4, t3) {
        return e4 <= t3;
      }, e3, t2, n3);
    }), P(`>=`, 4, 2, function(e3, t2, n3) {
      return N(function(e4, t3) {
        return e4 >= t3;
      }, e3, t2, n3);
    });
    var Ve = P(`=`, 3, 2, function(e3, t2, n3) {
      return N(function(e4, t3) {
        return e4 == t3;
      }, e3, t2, n3, true);
    });
    P(`!=`, 3, 2, function(e3, t2, n3) {
      return N(function(e4, t3) {
        return e4 != t3;
      }, e3, t2, n3, true);
    }), P(`and`, 2, 2, function(e3, t2, n3) {
      return j(e3, n3) && j(t2, n3);
    }), P(`or`, 1, 2, function(e3, t2, n3) {
      return j(e3, n3) || j(t2, n3);
    });
    function F(e3, t2, n3) {
      this.a = e3, this.b = t2 || 1, this.f = n3 || 1;
    }
    function I(e3, t2) {
      if (t2.a.length && e3.i != 4) throw Error(`Primary expression must evaluate to nodeset if filter has predicate(s).`);
      D.call(this, e3.i), this.c = e3, this.h = t2, this.g = e3.g, this.b = e3.b;
    }
    c(I), I.prototype.a = function(e3) {
      return e3 = this.c.a(e3), et(this.h, e3);
    }, I.prototype.toString = function() {
      var e3 = `Filter:` + O(this.c);
      return e3 += O(this.h);
    };
    function L(e3, t2) {
      if (t2.length < e3.A) throw Error(`Function ` + e3.j + ` expects at least` + e3.A + ` arguments, ` + t2.length + ` given`);
      if (e3.v !== null && t2.length > e3.v) throw Error(`Function ` + e3.j + ` expects at most ` + e3.v + ` arguments, ` + t2.length + ` given`);
      e3.B && f(t2, function(t3, n3) {
        if (t3.i != 4) throw Error(`Argument ` + n3 + ` to function ` + e3.j + ` is not of type Nodeset: ` + t3);
      }), D.call(this, e3.i), this.h = e3, this.c = t2, Le(this, e3.g || ne(t2, function(e4) {
        return e4.g;
      })), Re(this, e3.D && !t2.length || e3.C && !!t2.length || ne(t2, function(e4) {
        return e4.b;
      }));
    }
    c(L), L.prototype.a = function(e3) {
      return this.h.m.apply(null, ie(e3, this.c));
    }, L.prototype.toString = function() {
      var e3 = `Function: ` + this.h;
      if (this.c.length) var t2 = p(this.c, function(e4, t3) {
        return e4 + O(t3);
      }, `Arguments:`), e3 = e3 + O(t2);
      return e3;
    };
    function He(e3, t2, n3, r2, i2, a2, o3, s2, c2) {
      this.j = e3, this.i = t2, this.g = n3, this.D = r2, this.C = i2, this.m = a2, this.A = o3, this.v = s2 === void 0 ? o3 : s2, this.B = !!c2;
    }
    He.prototype.toString = function() {
      return this.j;
    };
    var Ue = {};
    function R(e3, t2, n3, r2, i2, a2, o3, s2) {
      if (Ue.hasOwnProperty(e3)) throw Error(`Function already created: ` + e3 + `.`);
      Ue[e3] = new He(e3, t2, n3, r2, false, i2, a2, o3, s2);
    }
    R(`boolean`, 2, false, false, function(e3, t2) {
      return j(t2, e3);
    }, 1), R(`ceiling`, 1, false, false, function(e3, t2) {
      return Math.ceil(k(t2, e3));
    }, 1), R(`concat`, 3, false, false, function(e3, t2) {
      return p(ae(arguments, 1), function(t3, n3) {
        return t3 + A(n3, e3);
      }, ``);
    }, 2, null), R(`contains`, 2, false, false, function(e3, t2, n3) {
      return u(A(t2, e3), A(n3, e3));
    }, 2), R(`count`, 1, false, false, function(e3, t2) {
      return t2.a(e3).l;
    }, 1, 1, true), R(`false`, 2, false, false, function() {
      return false;
    }, 0), R(`floor`, 1, false, false, function(e3, t2) {
      return Math.floor(k(t2, e3));
    }, 1), R(`id`, 4, false, false, function(e3, t2) {
      function n3(e4) {
        if (v) {
          var t3 = i2.all[e4];
          if (t3) {
            if (t3.nodeType && e4 == t3.id) return t3;
            if (t3.length) return re(t3, function(t4) {
              return e4 == t4.id;
            });
          }
          return null;
        }
        return i2.getElementById(e4);
      }
      var r2 = e3.a, i2 = r2.nodeType == 9 ? r2 : r2.ownerDocument, r2 = A(t2, e3).split(/\s+/), a2 = [];
      f(r2, function(e4) {
        e4 = n3(e4), !e4 || 0 <= d(a2, e4) || a2.push(e4);
      }), a2.sort(Oe);
      var o3 = new C();
      return f(a2, function(e4) {
        w(o3, e4);
      }), o3;
    }, 1), R(`lang`, 2, false, false, function() {
      return false;
    }, 1), R(`last`, 1, true, false, function(e3) {
      if (arguments.length != 1) throw Error(`Function last expects ()`);
      return e3.f;
    }, 0), R(`local-name`, 3, false, true, function(e3, t2) {
      var n3 = t2 ? Pe(t2.a(e3)) : e3.a;
      return n3 ? n3.localName || n3.nodeName.toLowerCase() : ``;
    }, 0, 1, true), R(`name`, 3, false, true, function(e3, t2) {
      var n3 = t2 ? Pe(t2.a(e3)) : e3.a;
      return n3 ? n3.nodeName.toLowerCase() : ``;
    }, 0, 1, true), R(`namespace-uri`, 3, true, false, function() {
      return ``;
    }, 0, 1, true), R(`normalize-space`, 3, false, true, function(e3, t2) {
      return (t2 ? A(t2, e3) : b(e3.a)).replace(/[\s\xa0]+/g, ` `).replace(/^\s+|\s+$/g, ``);
    }, 0, 1), R(`not`, 2, false, false, function(e3, t2) {
      return !j(t2, e3);
    }, 1), R(`number`, 1, false, true, function(e3, t2) {
      return t2 ? k(t2, e3) : +b(e3.a);
    }, 0, 1), R(`position`, 1, true, false, function(e3) {
      return e3.b;
    }, 0), R(`round`, 1, false, false, function(e3, t2) {
      return Math.round(k(t2, e3));
    }, 1), R(`starts-with`, 2, false, false, function(e3, t2, n3) {
      return t2 = A(t2, e3), e3 = A(n3, e3), t2.lastIndexOf(e3, 0) == 0;
    }, 2), R(`string`, 3, false, true, function(e3, t2) {
      return t2 ? A(t2, e3) : b(e3.a);
    }, 0, 1), R(`string-length`, 1, false, true, function(e3, t2) {
      return (t2 ? A(t2, e3) : b(e3.a)).length;
    }, 0, 1), R(`substring`, 3, false, false, function(e3, t2, n3, r2) {
      if (n3 = k(n3, e3), isNaN(n3) || n3 == 1 / 0 || n3 == -1 / 0 || (r2 = r2 ? k(r2, e3) : 1 / 0, isNaN(r2) || r2 === -1 / 0)) return ``;
      n3 = Math.round(n3) - 1;
      var i2 = Math.max(n3, 0);
      return e3 = A(t2, e3), r2 == 1 / 0 ? e3.substring(i2) : e3.substring(i2, n3 + Math.round(r2));
    }, 2, 3), R(`substring-after`, 3, false, false, function(e3, t2, n3) {
      return t2 = A(t2, e3), e3 = A(n3, e3), n3 = t2.indexOf(e3), n3 == -1 ? `` : t2.substring(n3 + e3.length);
    }, 2), R(`substring-before`, 3, false, false, function(e3, t2, n3) {
      return t2 = A(t2, e3), e3 = A(n3, e3), e3 = t2.indexOf(e3), e3 == -1 ? `` : t2.substring(0, e3);
    }, 2), R(`sum`, 1, false, false, function(e3, t2) {
      for (var n3 = T(t2.a(e3)), r2 = 0, i2 = E(n3); i2; i2 = E(n3)) r2 += +b(i2);
      return r2;
    }, 1, 1, true), R(`translate`, 3, false, false, function(e3, t2, n3, r2) {
      t2 = A(t2, e3), n3 = A(n3, e3);
      var i2 = A(r2, e3);
      for (e3 = {}, r2 = 0; r2 < n3.length; r2++) {
        var a2 = n3.charAt(r2);
        a2 in e3 || (e3[a2] = i2.charAt(r2));
      }
      for (n3 = ``, r2 = 0; r2 < t2.length; r2++) a2 = t2.charAt(r2), n3 += a2 in e3 ? e3[a2] : a2;
      return n3;
    }, 3), R(`true`, 2, false, false, function() {
      return true;
    }, 0);
    function z(e3, t2) {
      switch (this.h = e3, this.c = t2 === void 0 ? null : t2, this.b = null, e3) {
        case `comment`:
          this.b = 8;
          break;
        case `text`:
          this.b = 3;
          break;
        case `processing-instruction`:
          this.b = 7;
          break;
        case `node`:
          break;
        default:
          throw Error(`Unexpected argument`);
      }
    }
    function We(e3) {
      return e3 == `comment` || e3 == `text` || e3 == `processing-instruction` || e3 == `node`;
    }
    z.prototype.a = function(e3) {
      return this.b === null || this.b == e3.nodeType;
    }, z.prototype.f = function() {
      return this.h;
    }, z.prototype.toString = function() {
      var e3 = `Kind Test: ` + this.h;
      return this.c === null || (e3 += O(this.c)), e3;
    };
    function Ge(e3) {
      this.b = e3, this.a = 0;
    }
    function Ke(e3) {
      e3 = e3.match(qe);
      for (var t2 = 0; t2 < e3.length; t2++) Je.test(e3[t2]) && e3.splice(t2, 1);
      return new Ge(e3);
    }
    var qe = /\$?(?:(?![0-9-\.])(?:\*|[\w-\.]+):)?(?![0-9-\.])(?:\*|[\w-\.]+)|\/\/|\.\.|::|\d+(?:\.\d*)?|\.\d+|"[^"]*"|'[^']*'|[!<>]=|\s+|./g, Je = /^\s/;
    function B(e3, t2) {
      return e3.b[e3.a + (t2 || 0)];
    }
    function V(e3) {
      return e3.b[e3.a++];
    }
    function H(e3) {
      return e3.b.length <= e3.a;
    }
    function U(e3) {
      D.call(this, 3), this.c = e3.substring(1, e3.length - 1);
    }
    c(U), U.prototype.a = function() {
      return this.c;
    }, U.prototype.toString = function() {
      return `Literal: ` + this.c;
    };
    function W(e3, t2) {
      this.j = e3.toLowerCase();
      var n3 = this.j == `*` ? `*` : `http://www.w3.org/1999/xhtml`;
      this.c = t2 ? t2.toLowerCase() : n3;
    }
    W.prototype.a = function(e3) {
      var t2 = e3.nodeType;
      return t2 != 1 && t2 != 2 ? false : (t2 = e3.localName === void 0 ? e3.nodeName : e3.localName, this.j != `*` && this.j != t2.toLowerCase() ? false : this.c == `*` ? true : this.c == (e3.namespaceURI ? e3.namespaceURI.toLowerCase() : `http://www.w3.org/1999/xhtml`));
    }, W.prototype.f = function() {
      return this.j;
    }, W.prototype.toString = function() {
      return `Name Test: ` + (this.c == `http://www.w3.org/1999/xhtml` ? `` : this.c + `:`) + this.j;
    };
    function Ye(e3, t2) {
      if (D.call(this, e3.i), this.h = e3, this.c = t2, this.g = e3.g, this.b = e3.b, this.c.length == 1) {
        var n3 = this.c[0];
        n3.u || n3.c != rt || (n3 = n3.o, n3.f() != `*` && (this.f = { name: n3.f(), s: null }));
      }
    }
    c(Ye);
    function G() {
      D.call(this, 4);
    }
    c(G), G.prototype.a = function(e3) {
      var t2 = new C();
      return e3 = e3.a, e3.nodeType == 9 ? w(t2, e3) : w(t2, e3.ownerDocument), t2;
    }, G.prototype.toString = function() {
      return `Root Helper Expression`;
    };
    function Xe() {
      D.call(this, 4);
    }
    c(Xe), Xe.prototype.a = function(e3) {
      var t2 = new C();
      return w(t2, e3.a), t2;
    }, Xe.prototype.toString = function() {
      return `Context Helper Expression`;
    };
    function Ze(e3) {
      return e3 == `/` || e3 == `//`;
    }
    Ye.prototype.a = function(e3) {
      var t2 = this.h.a(e3);
      if (!(t2 instanceof C)) throw Error(`Filter expression must evaluate to nodeset.`);
      e3 = this.c;
      for (var n3 = 0, r2 = e3.length; n3 < r2 && t2.l; n3++) {
        var i2 = e3[n3], a2 = T(t2, i2.c.a), o3;
        if (i2.g || i2.c != ot) if (i2.g || i2.c != ct) for (o3 = E(a2), t2 = i2.a(new F(o3)); (o3 = E(a2)) != null; ) o3 = i2.a(new F(o3)), t2 = Me(t2, o3);
        else o3 = E(a2), t2 = i2.a(new F(o3));
        else {
          for (o3 = E(a2); (t2 = E(a2)) && (!o3.contains || o3.contains(t2)) && t2.compareDocumentPosition(o3) & 8; o3 = t2) ;
          t2 = i2.a(new F(o3));
        }
      }
      return t2;
    }, Ye.prototype.toString = function() {
      var e3 = `Path Expression:` + O(this.h);
      if (this.c.length) {
        var t2 = p(this.c, function(e4, t3) {
          return e4 + O(t3);
        }, `Steps:`);
        e3 += O(t2);
      }
      return e3;
    };
    function Qe(e3) {
      D.call(this, 4), this.c = e3, Le(this, ne(this.c, function(e4) {
        return e4.g;
      })), Re(this, ne(this.c, function(e4) {
        return e4.b;
      }));
    }
    c(Qe), Qe.prototype.a = function(e3) {
      var t2 = new C();
      return f(this.c, function(n3) {
        if (n3 = n3.a(e3), !(n3 instanceof C)) throw Error(`Path expression must evaluate to NodeSet.`);
        t2 = Me(t2, n3);
      }), t2;
    }, Qe.prototype.toString = function() {
      return p(this.c, function(e3, t2) {
        return e3 + O(t2);
      }, `Union Expression:`);
    };
    function $e(e3, t2) {
      this.a = e3, this.b = !!t2;
    }
    function et(e3, t2, n3) {
      for (n3 ||= 0; n3 < e3.a.length; n3++) for (var r2 = e3.a[n3], i2 = T(t2), a2 = t2.l, o3, s2 = 0; o3 = E(i2); s2++) {
        var c2 = e3.b ? a2 - s2 : s2 + 1;
        if (o3 = r2.a(new F(o3, c2, a2)), typeof o3 == `number`) c2 = c2 == o3;
        else if (typeof o3 == `string` || typeof o3 == `boolean`) c2 = !!o3;
        else if (o3 instanceof C) c2 = 0 < o3.l;
        else throw Error(`Predicate.evaluate returned an unexpected type.`);
        if (!c2) {
          c2 = i2, o3 = c2.f;
          var l2 = c2.a;
          if (!l2) throw Error(`Next must be called at least once before remove.`);
          var u2 = l2.b, l2 = l2.a;
          u2 ? u2.a = l2 : o3.a = l2, l2 ? l2.b = u2 : o3.b = u2, o3.l--, c2.a = null;
        }
      }
      return t2;
    }
    $e.prototype.toString = function() {
      return p(this.a, function(e3, t2) {
        return e3 + O(t2);
      }, `Predicates:`);
    };
    function K(e3, t2, n3, r2) {
      D.call(this, 4), this.c = e3, this.o = t2, this.h = n3 || new $e([]), this.u = !!r2, t2 = this.h, t2 = 0 < t2.a.length ? t2.a[0].f : null, e3.b && t2 && (e3 = t2.name, e3 = v ? e3.toLowerCase() : e3, this.f = { name: e3, s: t2.s });
      a: {
        for (e3 = this.h, t2 = 0; t2 < e3.a.length; t2++) if (n3 = e3.a[t2], n3.g || n3.i == 1 || n3.i == 0) {
          e3 = true;
          break a;
        }
        e3 = false;
      }
      this.g = e3;
    }
    c(K), K.prototype.a = function(e3) {
      var t2 = e3.a, n3 = null, n3 = this.f, r2 = null, i2 = null, a2 = 0;
      if (n3 && (r2 = n3.name, i2 = n3.s ? A(n3.s, e3) : null, a2 = 1), this.u) if (this.g || this.c != it) if (e3 = T(new K(at, new z(`node`)).a(e3)), t2 = E(e3)) for (n3 = this.m(t2, r2, i2, a2); (t2 = E(e3)) != null; ) n3 = Me(n3, this.m(t2, r2, i2, a2));
      else n3 = new C();
      else n3 = S(this.o, t2, r2, i2), n3 = et(this.h, n3, a2);
      else n3 = this.m(e3.a, r2, i2, a2);
      return n3;
    }, K.prototype.m = function(e3, t2, n3, r2) {
      return e3 = this.c.f(this.o, e3, t2, n3), e3 = et(this.h, e3, r2);
    }, K.prototype.toString = function() {
      var e3 = `Step:` + O(`Operator: ` + (this.u ? `//` : `/`));
      if (this.c.j && (e3 += O(`Axis: ` + this.c)), e3 += O(this.o), this.h.a.length) {
        var t2 = p(this.h.a, function(e4, t3) {
          return e4 + O(t3);
        }, `Predicates:`);
        e3 += O(t2);
      }
      return e3;
    };
    function tt(e3, t2, n3, r2) {
      this.j = e3, this.f = t2, this.a = n3, this.b = r2;
    }
    tt.prototype.toString = function() {
      return this.j;
    };
    var nt = {};
    function q(e3, t2, n3, r2) {
      if (nt.hasOwnProperty(e3)) throw Error(`Axis already created: ` + e3);
      return t2 = new tt(e3, t2, n3, !!r2), nt[e3] = t2;
    }
    q(`ancestor`, function(e3, t2) {
      for (var n3 = new C(), r2 = t2; r2 = r2.parentNode; ) e3.a(r2) && Ne(n3, r2);
      return n3;
    }, true), q(`ancestor-or-self`, function(e3, t2) {
      var n3 = new C(), r2 = t2;
      do
        e3.a(r2) && Ne(n3, r2);
      while (r2 = r2.parentNode);
      return n3;
    }, true);
    var rt = q(`attribute`, function(e3, t2) {
      var n3 = new C(), r2 = e3.f();
      if (r2 == `style` && v && t2.style) return w(n3, new y(t2.style, t2, `style`, t2.style.cssText)), n3;
      var i2 = t2.attributes;
      if (i2) if (e3 instanceof z && e3.b === null || r2 == `*`) for (var r2 = 0, a2; a2 = i2[r2]; r2++) v ? a2.nodeValue && w(n3, be(t2, a2)) : w(n3, a2);
      else (a2 = i2.getNamedItem(r2)) && (v ? a2.nodeValue && w(n3, be(t2, a2)) : w(n3, a2));
      return n3;
    }, false), it = q(`child`, function(e3, t2, n3, i2, a2) {
      return (v ? Ce : we).call(null, e3, t2, r(n3) ? n3 : null, r(i2) ? i2 : null, a2 || new C());
    }, false, true);
    q(`descendant`, S, false, true);
    var at = q(`descendant-or-self`, function(e3, t2, n3, r2) {
      var i2 = new C();
      return x(t2, n3, r2) && e3.a(t2) && w(i2, t2), S(e3, t2, n3, r2, i2);
    }, false, true), ot = q(`following`, function(e3, t2, n3, r2) {
      var i2 = new C();
      do
        for (var a2 = t2; a2 = a2.nextSibling; ) x(a2, n3, r2) && e3.a(a2) && w(i2, a2), i2 = S(e3, a2, n3, r2, i2);
      while (t2 = t2.parentNode);
      return i2;
    }, false, true);
    q(`following-sibling`, function(e3, t2) {
      for (var n3 = new C(), r2 = t2; r2 = r2.nextSibling; ) e3.a(r2) && w(n3, r2);
      return n3;
    }, false), q(`namespace`, function() {
      return new C();
    }, false);
    var st = q(`parent`, function(e3, t2) {
      var n3 = new C();
      if (t2.nodeType == 9) return n3;
      if (t2.nodeType == 2) return w(n3, t2.ownerElement), n3;
      var r2 = t2.parentNode;
      return e3.a(r2) && w(n3, r2), n3;
    }, false), ct = q(`preceding`, function(e3, t2, n3, r2) {
      var i2 = new C(), a2 = [];
      do
        a2.unshift(t2);
      while (t2 = t2.parentNode);
      for (var o3 = 1, s2 = a2.length; o3 < s2; o3++) {
        var c2 = [];
        for (t2 = a2[o3]; t2 = t2.previousSibling; ) c2.unshift(t2);
        for (var l2 = 0, u2 = c2.length; l2 < u2; l2++) t2 = c2[l2], x(t2, n3, r2) && e3.a(t2) && w(i2, t2), i2 = S(e3, t2, n3, r2, i2);
      }
      return i2;
    }, true, true);
    q(`preceding-sibling`, function(e3, t2) {
      for (var n3 = new C(), r2 = t2; r2 = r2.previousSibling; ) e3.a(r2) && Ne(n3, r2);
      return n3;
    }, true);
    var lt = q(`self`, function(e3, t2) {
      var n3 = new C();
      return e3.a(t2) && w(n3, t2), n3;
    }, false);
    function J(e3) {
      D.call(this, 1), this.c = e3, this.g = e3.g, this.b = e3.b;
    }
    c(J), J.prototype.a = function(e3) {
      return -k(this.c, e3);
    }, J.prototype.toString = function() {
      return `Unary Expression: -` + O(this.c);
    };
    function ut(e3) {
      D.call(this, 1), this.c = e3;
    }
    c(ut), ut.prototype.a = function() {
      return this.c;
    }, ut.prototype.toString = function() {
      return `Number: ` + this.c;
    };
    function dt(e3, t2) {
      this.a = e3, this.b = t2;
    }
    function ft(e3) {
      for (var t2, n3 = []; ; ) {
        Y(e3, `Missing right hand side of binary expression.`), t2 = yt(e3);
        var r2 = V(e3.a);
        if (!r2) break;
        var i2 = (r2 = Be[r2] || null) && r2.w;
        if (!i2) {
          e3.a.a--;
          break;
        }
        for (; n3.length && i2 <= n3[n3.length - 1].w; ) t2 = new M(n3.pop(), n3.pop(), t2);
        n3.push(t2, r2);
      }
      for (; n3.length; ) t2 = new M(n3.pop(), n3.pop(), t2);
      return t2;
    }
    function Y(e3, t2) {
      if (H(e3.a)) throw Error(t2);
    }
    function pt(e3, t2) {
      var n3 = V(e3.a);
      if (n3 != t2) throw Error(`Bad token, expected: ` + t2 + ` got: ` + n3);
    }
    function mt(e3) {
      if (e3 = V(e3.a), e3 != `)`) throw Error(`Bad token: ` + e3);
    }
    function ht(e3) {
      if (e3 = V(e3.a), 2 > e3.length) throw Error(`Unclosed literal string`);
      return new U(e3);
    }
    function gt(e3) {
      var t2, n3 = [], r2;
      if (Ze(B(e3.a))) {
        if (t2 = V(e3.a), r2 = B(e3.a), t2 == `/` && (H(e3.a) || r2 != `.` && r2 != `..` && r2 != `@` && r2 != `*` && !/(?![0-9])[\w]/.test(r2))) return new G();
        r2 = new G(), Y(e3, `Missing next location step.`), t2 = _t(e3, t2), n3.push(t2);
      } else {
        a: {
          switch (t2 = B(e3.a), r2 = t2.charAt(0), r2) {
            case `$`:
              throw Error(`Variable reference not allowed in HTML XPath`);
            case `(`:
              V(e3.a), t2 = ft(e3), Y(e3, `unclosed "("`), pt(e3, `)`);
              break;
            case `"`:
            case `'`:
              t2 = ht(e3);
              break;
            default:
              if (isNaN(+t2)) if (!We(t2) && /(?![0-9])[\w]/.test(r2) && B(e3.a, 1) == `(`) {
                for (t2 = V(e3.a), t2 = Ue[t2] || null, V(e3.a), r2 = []; B(e3.a) != `)` && (Y(e3, `Missing function argument list.`), r2.push(ft(e3)), B(e3.a) == `,`); ) V(e3.a);
                Y(e3, `Unclosed function argument list.`), mt(e3), t2 = new L(t2, r2);
              } else {
                t2 = null;
                break a;
              }
              else t2 = new ut(+V(e3.a));
          }
          B(e3.a) == `[` && (r2 = new $e(vt(e3)), t2 = new I(t2, r2));
        }
        if (t2) if (Ze(B(e3.a))) r2 = t2;
        else return t2;
        else t2 = _t(e3, `/`), r2 = new Xe(), n3.push(t2);
      }
      for (; Ze(B(e3.a)); ) t2 = V(e3.a), Y(e3, `Missing next location step.`), t2 = _t(e3, t2), n3.push(t2);
      return new Ye(r2, n3);
    }
    function _t(e3, t2) {
      var n3, r2, i2;
      if (t2 != `/` && t2 != `//`) throw Error(`Step op should be "/" or "//"`);
      if (B(e3.a) == `.`) return r2 = new K(lt, new z(`node`)), V(e3.a), r2;
      if (B(e3.a) == `..`) return r2 = new K(st, new z(`node`)), V(e3.a), r2;
      var a2;
      if (B(e3.a) == `@`) a2 = rt, V(e3.a), Y(e3, `Missing attribute name`);
      else if (B(e3.a, 1) == `::`) {
        if (!/(?![0-9])[\w]/.test(B(e3.a).charAt(0))) throw Error(`Bad token: ` + V(e3.a));
        if (n3 = V(e3.a), a2 = nt[n3] || null, !a2) throw Error(`No axis with name: ` + n3);
        V(e3.a), Y(e3, `Missing node name`);
      } else a2 = it;
      if (n3 = B(e3.a), /(?![0-9])[\w\*]/.test(n3.charAt(0))) if (B(e3.a, 1) == `(`) {
        if (!We(n3)) throw Error(`Invalid node type: ` + n3);
        if (n3 = V(e3.a), !We(n3)) throw Error(`Invalid type name: ` + n3);
        pt(e3, `(`), Y(e3, `Bad nodetype`), i2 = B(e3.a).charAt(0);
        var o3 = null;
        (i2 == `"` || i2 == `'`) && (o3 = ht(e3)), Y(e3, `Bad nodetype`), mt(e3), n3 = new z(n3, o3);
      } else if (n3 = V(e3.a), i2 = n3.indexOf(`:`), i2 == -1) n3 = new W(n3);
      else {
        var o3 = n3.substring(0, i2), s2;
        if (o3 == `*`) s2 = `*`;
        else if (s2 = e3.b(o3), !s2) throw Error(`Namespace prefix not declared: ` + o3);
        n3 = n3.substr(i2 + 1), n3 = new W(n3, s2);
      }
      else throw Error(`Bad token: ` + V(e3.a));
      return i2 = new $e(vt(e3), a2.a), r2 || new K(a2, n3, i2, t2 == `//`);
    }
    function vt(e3) {
      for (var t2 = []; B(e3.a) == `[`; ) {
        V(e3.a), Y(e3, `Missing predicate expression.`);
        var n3 = ft(e3);
        t2.push(n3), Y(e3, `Unclosed predicate expression.`), pt(e3, `]`);
      }
      return t2;
    }
    function yt(e3) {
      if (B(e3.a) == `-`) return V(e3.a), new J(yt(e3));
      var t2 = gt(e3);
      if (B(e3.a) != `|`) e3 = t2;
      else {
        for (t2 = [t2]; V(e3.a) == `|`; ) Y(e3, `Missing next union location path.`), t2.push(gt(e3));
        e3.a.a--, e3 = new Qe(t2);
      }
      return e3;
    }
    function bt(e3) {
      switch (e3.nodeType) {
        case 1:
          return s(St, e3);
        case 9:
          return bt(e3.documentElement);
        case 11:
        case 10:
        case 6:
        case 12:
          return xt;
        default:
          return e3.parentNode ? bt(e3.parentNode) : xt;
      }
    }
    function xt() {
      return null;
    }
    function St(e3, t2) {
      if (e3.prefix == t2) return e3.namespaceURI || `http://www.w3.org/1999/xhtml`;
      var n3 = e3.getAttributeNode(`xmlns:` + t2);
      return n3 && n3.specified ? n3.value || null : e3.parentNode && e3.parentNode.nodeType != 9 ? St(e3.parentNode, t2) : null;
    }
    function Ct(e3, n3) {
      if (!e3.length) throw Error(`Empty XPath expression.`);
      var r2 = Ke(e3);
      if (H(r2)) throw Error(`Invalid XPath expression.`);
      n3 ? t(n3) == `function` || (n3 = o2(n3.lookupNamespaceURI, n3)) : n3 = function() {
        return null;
      };
      var i2 = ft(new dt(r2, n3));
      if (!H(r2)) throw Error(`Bad token: ` + V(r2));
      this.evaluate = function(e4, t2) {
        var n4 = i2.a(new F(e4));
        return new X(n4, t2);
      };
    }
    function X(e3, t2) {
      if (t2 == 0) if (e3 instanceof C) t2 = 4;
      else if (typeof e3 == `string`) t2 = 2;
      else if (typeof e3 == `number`) t2 = 1;
      else if (typeof e3 == `boolean`) t2 = 3;
      else throw Error(`Unexpected evaluation result.`);
      if (t2 != 2 && t2 != 1 && t2 != 3 && !(e3 instanceof C)) throw Error(`value could not be converted to the specified type`);
      this.resultType = t2;
      var n3;
      switch (t2) {
        case 2:
          this.stringValue = e3 instanceof C ? Fe(e3) : `` + e3;
          break;
        case 1:
          this.numberValue = e3 instanceof C ? +Fe(e3) : +e3;
          break;
        case 3:
          this.booleanValue = e3 instanceof C ? 0 < e3.l : !!e3;
          break;
        case 4:
        case 5:
        case 6:
        case 7:
          var r2 = T(e3);
          n3 = [];
          for (var i2 = E(r2); i2; i2 = E(r2)) n3.push(i2 instanceof y ? i2.a : i2);
          this.snapshotLength = e3.l, this.invalidIteratorState = false;
          break;
        case 8:
        case 9:
          r2 = Pe(e3), this.singleNodeValue = r2 instanceof y ? r2.a : r2;
          break;
        default:
          throw Error(`Unknown XPathResult type.`);
      }
      var a2 = 0;
      this.iterateNext = function() {
        if (t2 != 4 && t2 != 5) throw Error(`iterateNext called with wrong result type`);
        return a2 >= n3.length ? null : n3[a2++];
      }, this.snapshotItem = function(e4) {
        if (t2 != 6 && t2 != 7) throw Error(`snapshotItem called with wrong result type`);
        return e4 >= n3.length || 0 > e4 ? null : n3[e4];
      };
    }
    X.ANY_TYPE = 0, X.NUMBER_TYPE = 1, X.STRING_TYPE = 2, X.BOOLEAN_TYPE = 3, X.UNORDERED_NODE_ITERATOR_TYPE = 4, X.ORDERED_NODE_ITERATOR_TYPE = 5, X.UNORDERED_NODE_SNAPSHOT_TYPE = 6, X.ORDERED_NODE_SNAPSHOT_TYPE = 7, X.ANY_UNORDERED_NODE_TYPE = 8, X.FIRST_ORDERED_NODE_TYPE = 9;
    function wt(e3) {
      this.lookupNamespaceURI = bt(e3);
    }
    function Tt(t2, n3) {
      var r2 = t2 || e2, i2 = r2.Document && r2.Document.prototype || r2.document;
      (!i2.evaluate || n3) && (r2.XPathResult = X, i2.evaluate = function(e3, t3, n4, r3) {
        return new Ct(e3, n4).evaluate(t3, r3);
      }, i2.createExpression = function(e3, t3) {
        return new Ct(e3, t3);
      }, i2.createNSResolver = function(e3) {
        return new wt(e3);
      });
    }
    var Z = [`wgxpath`, `install`], Q = e2;
    Z[0] in Q || !Q.execScript || Q.execScript(`var ` + Z[0]);
    for (var $; Z.length && ($ = Z.shift()); ) Z.length || Tt === void 0 ? Q = Q[$] ? Q[$] : Q[$] = {} : Q[$] = Tt;
    n2.exports.install = Tt, n2.exports.XPathResultType = { ANY_TYPE: 0, NUMBER_TYPE: 1, STRING_TYPE: 2, BOOLEAN_TYPE: 3, UNORDERED_NODE_ITERATOR_TYPE: 4, ORDERED_NODE_ITERATOR_TYPE: 5, UNORDERED_NODE_SNAPSHOT_TYPE: 6, ORDERED_NODE_SNAPSHOT_TYPE: 7, ANY_UNORDERED_NODE_TYPE: 8, FIRST_ORDERED_NODE_TYPE: 9 };
  }).call(e);
}));
const wgxpath_installNodeCsk64Aj9 = n();
export {
  wgxpath_installNodeCsk64Aj9 as default
};
//# sourceMappingURL=wgxpath.install-node-Csk64Aj9.js.map
