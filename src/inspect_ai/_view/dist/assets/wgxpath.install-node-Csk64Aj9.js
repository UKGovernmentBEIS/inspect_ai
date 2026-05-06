import { n as o } from "./chunk-DfAF0w94.js";
//#region ../../node_modules/.pnpm/mathxyjax3@0.8.3/node_modules/mathxyjax3/dist/wgxpath.install-node-Csk64Aj9.js
var e = globalThis;
var wgxpath_install_node_Csk64Aj9_default = o(((exports, n) => {
	(function() {
		var e = this;
		function t(e) {
			var t = typeof e;
			if (t == `object`) if (e) {
				if (e instanceof Array) return `array`;
				if (e instanceof Object) return t;
				var n = Object.prototype.toString.call(e);
				if (n == `[object Window]`) return `object`;
				if (n == `[object Array]` || typeof e.length == `number` && e.splice !== void 0 && e.propertyIsEnumerable !== void 0 && !e.propertyIsEnumerable(`splice`)) return `array`;
				if (n == `[object Function]` || e.call !== void 0 && e.propertyIsEnumerable !== void 0 && !e.propertyIsEnumerable(`call`)) return `function`;
			} else return `null`;
			else if (t == `function` && e.call === void 0) return `object`;
			return t;
		}
		function r(e) {
			return typeof e == `string`;
		}
		function i(e, t, n) {
			return e.call.apply(e.bind, arguments);
		}
		function a(e, t, n) {
			if (!e) throw Error();
			if (2 < arguments.length) {
				var r = Array.prototype.slice.call(arguments, 2);
				return function() {
					var n = Array.prototype.slice.call(arguments);
					return Array.prototype.unshift.apply(n, r), e.apply(t, n);
				};
			}
			return function() {
				return e.apply(t, arguments);
			};
		}
		function o(e, t, n) {
			return o = Function.prototype.bind && Function.prototype.bind.toString().indexOf(`native code`) != -1 ? i : a, o.apply(null, arguments);
		}
		function s(e, t) {
			var n = Array.prototype.slice.call(arguments, 1);
			return function() {
				var t = n.slice();
				return t.push.apply(t, arguments), e.apply(this, t);
			};
		}
		function c(e) {
			var t = D;
			function n() {}
			n.prototype = t.prototype, e.G = t.prototype, e.prototype = new n(), e.prototype.constructor = e, e.F = function(e, n, r) {
				for (var i = Array(arguments.length - 2), a = 2; a < arguments.length; a++) i[a - 2] = arguments[a];
				return t.prototype[n].apply(e, i);
			};
		}
		var l = String.prototype.trim ? function(e) {
			return e.trim();
		} : function(e) {
			return e.replace(/^[\s\xa0]+|[\s\xa0]+$/g, ``);
		};
		function u(e, t) {
			return e.indexOf(t) != -1;
		}
		function ee(e, t) {
			return e < t ? -1 : e > t ? 1 : 0;
		}
		var d = Array.prototype.indexOf ? function(e, t, n) {
			return Array.prototype.indexOf.call(e, t, n);
		} : function(e, t, n) {
			if (n = n == null ? 0 : 0 > n ? Math.max(0, e.length + n) : n, r(e)) return r(t) && t.length == 1 ? e.indexOf(t, n) : -1;
			for (; n < e.length; n++) if (n in e && e[n] === t) return n;
			return -1;
		}, f = Array.prototype.forEach ? function(e, t, n) {
			Array.prototype.forEach.call(e, t, n);
		} : function(e, t, n) {
			for (var i = e.length, a = r(e) ? e.split(``) : e, o = 0; o < i; o++) o in a && t.call(n, a[o], o, e);
		}, te = Array.prototype.filter ? function(e, t, n) {
			return Array.prototype.filter.call(e, t, n);
		} : function(e, t, n) {
			for (var i = e.length, a = [], o = 0, s = r(e) ? e.split(``) : e, c = 0; c < i; c++) if (c in s) {
				var l = s[c];
				t.call(n, l, c, e) && (a[o++] = l);
			}
			return a;
		}, p = Array.prototype.reduce ? function(e, t, n, r) {
			return r && (t = o(t, r)), Array.prototype.reduce.call(e, t, n);
		} : function(e, t, n, r) {
			var i = n;
			return f(e, function(n, a) {
				i = t.call(r, i, n, a, e);
			}), i;
		}, ne = Array.prototype.some ? function(e, t, n) {
			return Array.prototype.some.call(e, t, n);
		} : function(e, t, n) {
			for (var i = e.length, a = r(e) ? e.split(``) : e, o = 0; o < i; o++) if (o in a && t.call(n, a[o], o, e)) return !0;
			return !1;
		};
		function re(e, t) {
			var n;
			a: {
				n = e.length;
				for (var i = r(e) ? e.split(``) : e, a = 0; a < n; a++) if (a in i && t.call(void 0, i[a], a, e)) {
					n = a;
					break a;
				}
				n = -1;
			}
			return 0 > n ? null : r(e) ? e.charAt(n) : e[n];
		}
		function ie(e) {
			return Array.prototype.concat.apply(Array.prototype, arguments);
		}
		function ae(e, t, n) {
			return 2 >= arguments.length ? Array.prototype.slice.call(e, t) : Array.prototype.slice.call(e, t, n);
		}
		var m;
		a: {
			var oe = e.navigator;
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
			var t = e.document;
			return t ? t.documentMode : void 0;
		}
		var g;
		a: {
			var pe = ``, me = function() {
				var e = m;
				if (ue) return /rv\:([^\);]+)(\)|;)/.exec(e);
				if (le) return /Edge\/([\d\.]+)/.exec(e);
				if (h) return /\b(?:MSIE|rv)[: ]([^\);]+)(\)|;)/.exec(e);
				if (de) return /WebKit\/(\S+)/.exec(e);
				if (ce) return /(?:Version)[ \/]?(\S+)/.exec(e);
			}();
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
		function _e(e) {
			if (!ge[e]) {
				for (var t = 0, n = l(String(g)).split(`.`), r = l(String(e)).split(`.`), i = Math.max(n.length, r.length), a = 0; t == 0 && a < i; a++) {
					var o = n[a] || ``, s = r[a] || ``, c = /(\d*)(\D*)/g, u = /(\d*)(\D*)/g;
					do {
						var d = c.exec(o) || [
							``,
							``,
							``
						], f = u.exec(s) || [
							``,
							``,
							``
						];
						if (d[0].length == 0 && f[0].length == 0) break;
						t = ee(d[1].length == 0 ? 0 : parseInt(d[1], 10), f[1].length == 0 ? 0 : parseInt(f[1], 10)) || ee(d[2].length == 0, f[2].length == 0) || ee(d[2], f[2]);
					} while (t == 0);
				}
				ge[e] = 0 <= t;
			}
		}
		var ve = e.document, _ = ve && h ? fe() || (ve.compatMode == `CSS1Compat` ? parseInt(g, 10) : 5) : void 0, v = h && !(9 <= Number(_)), ye = h && !(8 <= Number(_));
		function y(e, t, n, r) {
			this.a = e, this.nodeName = n, this.nodeValue = r, this.nodeType = 2, this.parentNode = this.ownerElement = t;
		}
		function be(e, t) {
			var n = ye && t.nodeName == `href` ? e.getAttribute(t.nodeName, 2) : t.nodeValue;
			return new y(t, e, t.nodeName, n);
		}
		function b(e) {
			var t = null, n = e.nodeType;
			if (n == 1 && (t = e.textContent, t = t == null || t == null ? e.innerText : t, t = t == null || t == null ? `` : t), typeof t != `string`) if (v && e.nodeName.toLowerCase() == `title` && n == 1) t = e.text;
			else if (n == 9 || n == 1) {
				e = n == 9 ? e.documentElement : e.firstChild;
				for (var n = 0, r = [], t = ``; e;) {
					do
						e.nodeType != 1 && (t += e.nodeValue), v && e.nodeName.toLowerCase() == `title` && (t += e.text), r[n++] = e;
					while (e = e.firstChild);
					for (; n && !(e = r[--n].nextSibling););
				}
			} else t = e.nodeValue;
			return `` + t;
		}
		function x(e, t, n) {
			if (t === null) return !0;
			try {
				if (!e.getAttribute) return !1;
			} catch {
				return !1;
			}
			return ye && t == `class` && (t = `className`), n == null ? !!e.getAttribute(t) : e.getAttribute(t, 2) == n;
		}
		function S(e, t, n, i, a) {
			return (v ? xe : Se).call(null, e, t, r(n) ? n : null, r(i) ? i : null, a || new C());
		}
		function xe(e, t, n, r, i) {
			if (e instanceof W || e.b == 8 || n && e.b === null) {
				var a = t.all;
				if (!a || (e = Ee(e), e != `*` && (a = t.getElementsByTagName(e), !a))) return i;
				if (n) {
					for (var o = [], s = 0; t = a[s++];) x(t, n, r) && o.push(t);
					a = o;
				}
				for (s = 0; t = a[s++];) e == `*` && t.tagName == `!` || w(i, t);
				return i;
			}
			return Te(e, t, n, r, i), i;
		}
		function Se(e, t, n, r, i) {
			return t.getElementsByName && r && n == `name` && !h ? (t = t.getElementsByName(r), f(t, function(t) {
				e.a(t) && w(i, t);
			})) : t.getElementsByClassName && r && n == `class` ? (t = t.getElementsByClassName(r), f(t, function(t) {
				t.className == r && e.a(t) && w(i, t);
			})) : e instanceof z ? Te(e, t, n, r, i) : t.getElementsByTagName && (t = t.getElementsByTagName(e.f()), f(t, function(e) {
				x(e, n, r) && w(i, e);
			})), i;
		}
		function Ce(e, t, n, r, i) {
			var a;
			if ((e instanceof W || e.b == 8 || n && e.b === null) && (a = t.childNodes)) {
				var o = Ee(e);
				return o != `*` && (a = te(a, function(e) {
					return e.tagName && e.tagName.toLowerCase() == o;
				}), !a) ? i : (n && (a = te(a, function(e) {
					return x(e, n, r);
				})), f(a, function(e) {
					o == `*` && (e.tagName == `!` || o == `*` && e.nodeType != 1) || w(i, e);
				}), i);
			}
			return we(e, t, n, r, i);
		}
		function we(e, t, n, r, i) {
			for (t = t.firstChild; t; t = t.nextSibling) x(t, n, r) && e.a(t) && w(i, t);
			return i;
		}
		function Te(e, t, n, r, i) {
			for (t = t.firstChild; t; t = t.nextSibling) x(t, n, r) && e.a(t) && w(i, t), Te(e, t, n, r, i);
		}
		function Ee(e) {
			if (e instanceof z) {
				if (e.b == 8) return `!`;
				if (e.b === null) return `*`;
			}
			return e.f();
		}
		!ue && !h || h && 9 <= Number(_) || ue && _e(`1.9.1`), h && _e(`9`);
		function De(e, t) {
			if (!e || !t) return !1;
			if (e.contains && t.nodeType == 1) return e == t || e.contains(t);
			if (e.compareDocumentPosition !== void 0) return e == t || !!(e.compareDocumentPosition(t) & 16);
			for (; t && e != t;) t = t.parentNode;
			return t == e;
		}
		function Oe(t, n) {
			if (t == n) return 0;
			if (t.compareDocumentPosition) return t.compareDocumentPosition(n) & 2 ? 1 : -1;
			if (h && !(9 <= Number(_))) {
				if (t.nodeType == 9) return -1;
				if (n.nodeType == 9) return 1;
			}
			if (`sourceIndex` in t || t.parentNode && `sourceIndex` in t.parentNode) {
				var r = t.nodeType == 1, i = n.nodeType == 1;
				if (r && i) return t.sourceIndex - n.sourceIndex;
				var a = t.parentNode, o = n.parentNode;
				return a == o ? Ae(t, n) : !r && De(a, n) ? -1 * ke(t, n) : !i && De(o, t) ? ke(n, t) : (r ? t.sourceIndex : a.sourceIndex) - (i ? n.sourceIndex : o.sourceIndex);
			}
			return i = t.nodeType == 9 ? t : t.ownerDocument || t.document, r = i.createRange(), r.selectNode(t), r.collapse(!0), i = i.createRange(), i.selectNode(n), i.collapse(!0), r.compareBoundaryPoints(e.Range.START_TO_END, i);
		}
		function ke(e, t) {
			var n = e.parentNode;
			if (n == t) return -1;
			for (var r = t; r.parentNode != n;) r = r.parentNode;
			return Ae(r, e);
		}
		function Ae(e, t) {
			for (var n = t; n = n.previousSibling;) if (n == e) return -1;
			return 1;
		}
		function C() {
			this.b = this.a = null, this.l = 0;
		}
		function je(e) {
			this.node = e, this.a = this.b = null;
		}
		function Me(e, t) {
			if (!e.a) return t;
			if (!t.a) return e;
			for (var n = e.a, r = t.a, i = null, a = null, o = 0; n && r;) {
				var a = n.node, s = r.node;
				a == s || a instanceof y && s instanceof y && a.a == s.a ? (a = n, n = n.a, r = r.a) : 0 < Oe(n.node, r.node) ? (a = r, r = r.a) : (a = n, n = n.a), (a.b = i) ? i.a = a : e.a = a, i = a, o++;
			}
			for (a = n || r; a;) a.b = i, i = i.a = a, o++, a = a.a;
			return e.b = i, e.l = o, e;
		}
		function Ne(e, t) {
			var n = new je(t);
			n.a = e.a, e.b ? e.a.b = n : e.a = e.b = n, e.a = n, e.l++;
		}
		function w(e, t) {
			var n = new je(t);
			n.b = e.b, e.a ? e.b.a = n : e.a = e.b = n, e.b = n, e.l++;
		}
		function Pe(e) {
			return (e = e.a) ? e.node : null;
		}
		function Fe(e) {
			return (e = Pe(e)) ? b(e) : ``;
		}
		function T(e, t) {
			return new Ie(e, !!t);
		}
		function Ie(e, t) {
			this.f = e, this.b = (this.c = t) ? e.b : e.a, this.a = null;
		}
		function E(e) {
			var t = e.b;
			if (t == null) return null;
			var n = e.a = t;
			return e.b = e.c ? t.b : t.a, n.node;
		}
		function D(e) {
			this.i = e, this.b = this.g = !1, this.f = null;
		}
		function O(e) {
			return `
  ` + e.toString().split(`
`).join(`
  `);
		}
		function Le(e, t) {
			e.g = t;
		}
		function Re(e, t) {
			e.b = t;
		}
		function k(e, t) {
			var n = e.a(t);
			return n instanceof C ? +Fe(n) : +n;
		}
		function A(e, t) {
			var n = e.a(t);
			return n instanceof C ? Fe(n) : `` + n;
		}
		function j(e, t) {
			var n = e.a(t);
			return n instanceof C ? !!n.l : !!n;
		}
		function M(e, t, n) {
			D.call(this, e.i), this.c = e, this.h = t, this.o = n, this.g = t.g || n.g, this.b = t.b || n.b, this.c == Ve && (n.b || n.g || n.i == 4 || n.i == 0 || !t.f ? t.b || t.g || t.i == 4 || t.i == 0 || !n.f || (this.f = {
				name: n.f.name,
				s: t
			}) : this.f = {
				name: t.f.name,
				s: n
			});
		}
		c(M);
		function N(e, t, n, r, i) {
			t = t.a(r), n = n.a(r);
			var a;
			if (t instanceof C && n instanceof C) {
				for (t = T(t), r = E(t); r; r = E(t)) for (i = T(n), a = E(i); a; a = E(i)) if (e(b(r), b(a))) return !0;
				return !1;
			}
			if (t instanceof C || n instanceof C) {
				t instanceof C ? (i = t, r = n) : (i = n, r = t), a = T(i);
				for (var o = typeof r, s = E(a); s; s = E(a)) {
					switch (o) {
						case `number`:
							s = +b(s);
							break;
						case `boolean`:
							s = !!b(s);
							break;
						case `string`:
							s = b(s);
							break;
						default: throw Error(`Illegal primitive type for comparison.`);
					}
					if (i == t && e(s, r) || i == n && e(r, s)) return !0;
				}
				return !1;
			}
			return i ? typeof t == `boolean` || typeof n == `boolean` ? e(!!t, !!n) : typeof t == `number` || typeof n == `number` ? e(+t, +n) : e(t, n) : e(+t, +n);
		}
		M.prototype.a = function(e) {
			return this.c.m(this.h, this.o, e);
		}, M.prototype.toString = function() {
			var e = `Binary Expression: ` + this.c, e = e + O(this.h);
			return e += O(this.o);
		};
		function ze(e, t, n, r) {
			this.a = e, this.w = t, this.i = n, this.m = r;
		}
		ze.prototype.toString = function() {
			return this.a;
		};
		var Be = {};
		function P(e, t, n, r) {
			if (Be.hasOwnProperty(e)) throw Error(`Binary operator already created: ` + e);
			return e = new ze(e, t, n, r), Be[e.toString()] = e;
		}
		P(`div`, 6, 1, function(e, t, n) {
			return k(e, n) / k(t, n);
		}), P(`mod`, 6, 1, function(e, t, n) {
			return k(e, n) % k(t, n);
		}), P(`*`, 6, 1, function(e, t, n) {
			return k(e, n) * k(t, n);
		}), P(`+`, 5, 1, function(e, t, n) {
			return k(e, n) + k(t, n);
		}), P(`-`, 5, 1, function(e, t, n) {
			return k(e, n) - k(t, n);
		}), P(`<`, 4, 2, function(e, t, n) {
			return N(function(e, t) {
				return e < t;
			}, e, t, n);
		}), P(`>`, 4, 2, function(e, t, n) {
			return N(function(e, t) {
				return e > t;
			}, e, t, n);
		}), P(`<=`, 4, 2, function(e, t, n) {
			return N(function(e, t) {
				return e <= t;
			}, e, t, n);
		}), P(`>=`, 4, 2, function(e, t, n) {
			return N(function(e, t) {
				return e >= t;
			}, e, t, n);
		});
		var Ve = P(`=`, 3, 2, function(e, t, n) {
			return N(function(e, t) {
				return e == t;
			}, e, t, n, !0);
		});
		P(`!=`, 3, 2, function(e, t, n) {
			return N(function(e, t) {
				return e != t;
			}, e, t, n, !0);
		}), P(`and`, 2, 2, function(e, t, n) {
			return j(e, n) && j(t, n);
		}), P(`or`, 1, 2, function(e, t, n) {
			return j(e, n) || j(t, n);
		});
		function F(e, t, n) {
			this.a = e, this.b = t || 1, this.f = n || 1;
		}
		function I(e, t) {
			if (t.a.length && e.i != 4) throw Error(`Primary expression must evaluate to nodeset if filter has predicate(s).`);
			D.call(this, e.i), this.c = e, this.h = t, this.g = e.g, this.b = e.b;
		}
		c(I), I.prototype.a = function(e) {
			return e = this.c.a(e), et(this.h, e);
		}, I.prototype.toString = function() {
			var e = `Filter:` + O(this.c);
			return e += O(this.h);
		};
		function L(e, t) {
			if (t.length < e.A) throw Error(`Function ` + e.j + ` expects at least` + e.A + ` arguments, ` + t.length + ` given`);
			if (e.v !== null && t.length > e.v) throw Error(`Function ` + e.j + ` expects at most ` + e.v + ` arguments, ` + t.length + ` given`);
			e.B && f(t, function(t, n) {
				if (t.i != 4) throw Error(`Argument ` + n + ` to function ` + e.j + ` is not of type Nodeset: ` + t);
			}), D.call(this, e.i), this.h = e, this.c = t, Le(this, e.g || ne(t, function(e) {
				return e.g;
			})), Re(this, e.D && !t.length || e.C && !!t.length || ne(t, function(e) {
				return e.b;
			}));
		}
		c(L), L.prototype.a = function(e) {
			return this.h.m.apply(null, ie(e, this.c));
		}, L.prototype.toString = function() {
			var e = `Function: ` + this.h;
			if (this.c.length) var t = p(this.c, function(e, t) {
				return e + O(t);
			}, `Arguments:`), e = e + O(t);
			return e;
		};
		function He(e, t, n, r, i, a, o, s, c) {
			this.j = e, this.i = t, this.g = n, this.D = r, this.C = i, this.m = a, this.A = o, this.v = s === void 0 ? o : s, this.B = !!c;
		}
		He.prototype.toString = function() {
			return this.j;
		};
		var Ue = {};
		function R(e, t, n, r, i, a, o, s) {
			if (Ue.hasOwnProperty(e)) throw Error(`Function already created: ` + e + `.`);
			Ue[e] = new He(e, t, n, r, !1, i, a, o, s);
		}
		R(`boolean`, 2, !1, !1, function(e, t) {
			return j(t, e);
		}, 1), R(`ceiling`, 1, !1, !1, function(e, t) {
			return Math.ceil(k(t, e));
		}, 1), R(`concat`, 3, !1, !1, function(e, t) {
			return p(ae(arguments, 1), function(t, n) {
				return t + A(n, e);
			}, ``);
		}, 2, null), R(`contains`, 2, !1, !1, function(e, t, n) {
			return u(A(t, e), A(n, e));
		}, 2), R(`count`, 1, !1, !1, function(e, t) {
			return t.a(e).l;
		}, 1, 1, !0), R(`false`, 2, !1, !1, function() {
			return !1;
		}, 0), R(`floor`, 1, !1, !1, function(e, t) {
			return Math.floor(k(t, e));
		}, 1), R(`id`, 4, !1, !1, function(e, t) {
			function n(e) {
				if (v) {
					var t = i.all[e];
					if (t) {
						if (t.nodeType && e == t.id) return t;
						if (t.length) return re(t, function(t) {
							return e == t.id;
						});
					}
					return null;
				}
				return i.getElementById(e);
			}
			var r = e.a, i = r.nodeType == 9 ? r : r.ownerDocument, r = A(t, e).split(/\s+/), a = [];
			f(r, function(e) {
				e = n(e), !e || 0 <= d(a, e) || a.push(e);
			}), a.sort(Oe);
			var o = new C();
			return f(a, function(e) {
				w(o, e);
			}), o;
		}, 1), R(`lang`, 2, !1, !1, function() {
			return !1;
		}, 1), R(`last`, 1, !0, !1, function(e) {
			if (arguments.length != 1) throw Error(`Function last expects ()`);
			return e.f;
		}, 0), R(`local-name`, 3, !1, !0, function(e, t) {
			var n = t ? Pe(t.a(e)) : e.a;
			return n ? n.localName || n.nodeName.toLowerCase() : ``;
		}, 0, 1, !0), R(`name`, 3, !1, !0, function(e, t) {
			var n = t ? Pe(t.a(e)) : e.a;
			return n ? n.nodeName.toLowerCase() : ``;
		}, 0, 1, !0), R(`namespace-uri`, 3, !0, !1, function() {
			return ``;
		}, 0, 1, !0), R(`normalize-space`, 3, !1, !0, function(e, t) {
			return (t ? A(t, e) : b(e.a)).replace(/[\s\xa0]+/g, ` `).replace(/^\s+|\s+$/g, ``);
		}, 0, 1), R(`not`, 2, !1, !1, function(e, t) {
			return !j(t, e);
		}, 1), R(`number`, 1, !1, !0, function(e, t) {
			return t ? k(t, e) : +b(e.a);
		}, 0, 1), R(`position`, 1, !0, !1, function(e) {
			return e.b;
		}, 0), R(`round`, 1, !1, !1, function(e, t) {
			return Math.round(k(t, e));
		}, 1), R(`starts-with`, 2, !1, !1, function(e, t, n) {
			return t = A(t, e), e = A(n, e), t.lastIndexOf(e, 0) == 0;
		}, 2), R(`string`, 3, !1, !0, function(e, t) {
			return t ? A(t, e) : b(e.a);
		}, 0, 1), R(`string-length`, 1, !1, !0, function(e, t) {
			return (t ? A(t, e) : b(e.a)).length;
		}, 0, 1), R(`substring`, 3, !1, !1, function(e, t, n, r) {
			if (n = k(n, e), isNaN(n) || n == Infinity || n == -Infinity || (r = r ? k(r, e) : Infinity, isNaN(r) || r === -Infinity)) return ``;
			n = Math.round(n) - 1;
			var i = Math.max(n, 0);
			return e = A(t, e), r == Infinity ? e.substring(i) : e.substring(i, n + Math.round(r));
		}, 2, 3), R(`substring-after`, 3, !1, !1, function(e, t, n) {
			return t = A(t, e), e = A(n, e), n = t.indexOf(e), n == -1 ? `` : t.substring(n + e.length);
		}, 2), R(`substring-before`, 3, !1, !1, function(e, t, n) {
			return t = A(t, e), e = A(n, e), e = t.indexOf(e), e == -1 ? `` : t.substring(0, e);
		}, 2), R(`sum`, 1, !1, !1, function(e, t) {
			for (var n = T(t.a(e)), r = 0, i = E(n); i; i = E(n)) r += +b(i);
			return r;
		}, 1, 1, !0), R(`translate`, 3, !1, !1, function(e, t, n, r) {
			t = A(t, e), n = A(n, e);
			var i = A(r, e);
			for (e = {}, r = 0; r < n.length; r++) {
				var a = n.charAt(r);
				a in e || (e[a] = i.charAt(r));
			}
			for (n = ``, r = 0; r < t.length; r++) a = t.charAt(r), n += a in e ? e[a] : a;
			return n;
		}, 3), R(`true`, 2, !1, !1, function() {
			return !0;
		}, 0);
		function z(e, t) {
			switch (this.h = e, this.c = t === void 0 ? null : t, this.b = null, e) {
				case `comment`:
					this.b = 8;
					break;
				case `text`:
					this.b = 3;
					break;
				case `processing-instruction`:
					this.b = 7;
					break;
				case `node`: break;
				default: throw Error(`Unexpected argument`);
			}
		}
		function We(e) {
			return e == `comment` || e == `text` || e == `processing-instruction` || e == `node`;
		}
		z.prototype.a = function(e) {
			return this.b === null || this.b == e.nodeType;
		}, z.prototype.f = function() {
			return this.h;
		}, z.prototype.toString = function() {
			var e = `Kind Test: ` + this.h;
			return this.c === null || (e += O(this.c)), e;
		};
		function Ge(e) {
			this.b = e, this.a = 0;
		}
		function Ke(e) {
			e = e.match(qe);
			for (var t = 0; t < e.length; t++) Je.test(e[t]) && e.splice(t, 1);
			return new Ge(e);
		}
		var qe = /\$?(?:(?![0-9-\.])(?:\*|[\w-\.]+):)?(?![0-9-\.])(?:\*|[\w-\.]+)|\/\/|\.\.|::|\d+(?:\.\d*)?|\.\d+|"[^"]*"|'[^']*'|[!<>]=|\s+|./g, Je = /^\s/;
		function B(e, t) {
			return e.b[e.a + (t || 0)];
		}
		function V(e) {
			return e.b[e.a++];
		}
		function H(e) {
			return e.b.length <= e.a;
		}
		function U(e) {
			D.call(this, 3), this.c = e.substring(1, e.length - 1);
		}
		c(U), U.prototype.a = function() {
			return this.c;
		}, U.prototype.toString = function() {
			return `Literal: ` + this.c;
		};
		function W(e, t) {
			this.j = e.toLowerCase();
			var n = this.j == `*` ? `*` : `http://www.w3.org/1999/xhtml`;
			this.c = t ? t.toLowerCase() : n;
		}
		W.prototype.a = function(e) {
			var t = e.nodeType;
			return t != 1 && t != 2 ? !1 : (t = e.localName === void 0 ? e.nodeName : e.localName, this.j != `*` && this.j != t.toLowerCase() ? !1 : this.c == `*` ? !0 : this.c == (e.namespaceURI ? e.namespaceURI.toLowerCase() : `http://www.w3.org/1999/xhtml`));
		}, W.prototype.f = function() {
			return this.j;
		}, W.prototype.toString = function() {
			return `Name Test: ` + (this.c == `http://www.w3.org/1999/xhtml` ? `` : this.c + `:`) + this.j;
		};
		function Ye(e, t) {
			if (D.call(this, e.i), this.h = e, this.c = t, this.g = e.g, this.b = e.b, this.c.length == 1) {
				var n = this.c[0];
				n.u || n.c != rt || (n = n.o, n.f() != `*` && (this.f = {
					name: n.f(),
					s: null
				}));
			}
		}
		c(Ye);
		function G() {
			D.call(this, 4);
		}
		c(G), G.prototype.a = function(e) {
			var t = new C();
			return e = e.a, e.nodeType == 9 ? w(t, e) : w(t, e.ownerDocument), t;
		}, G.prototype.toString = function() {
			return `Root Helper Expression`;
		};
		function Xe() {
			D.call(this, 4);
		}
		c(Xe), Xe.prototype.a = function(e) {
			var t = new C();
			return w(t, e.a), t;
		}, Xe.prototype.toString = function() {
			return `Context Helper Expression`;
		};
		function Ze(e) {
			return e == `/` || e == `//`;
		}
		Ye.prototype.a = function(e) {
			var t = this.h.a(e);
			if (!(t instanceof C)) throw Error(`Filter expression must evaluate to nodeset.`);
			e = this.c;
			for (var n = 0, r = e.length; n < r && t.l; n++) {
				var i = e[n], a = T(t, i.c.a), o;
				if (i.g || i.c != ot) if (i.g || i.c != ct) for (o = E(a), t = i.a(new F(o)); (o = E(a)) != null;) o = i.a(new F(o)), t = Me(t, o);
				else o = E(a), t = i.a(new F(o));
				else {
					for (o = E(a); (t = E(a)) && (!o.contains || o.contains(t)) && t.compareDocumentPosition(o) & 8; o = t);
					t = i.a(new F(o));
				}
			}
			return t;
		}, Ye.prototype.toString = function() {
			var e = `Path Expression:` + O(this.h);
			if (this.c.length) {
				var t = p(this.c, function(e, t) {
					return e + O(t);
				}, `Steps:`);
				e += O(t);
			}
			return e;
		};
		function Qe(e) {
			D.call(this, 4), this.c = e, Le(this, ne(this.c, function(e) {
				return e.g;
			})), Re(this, ne(this.c, function(e) {
				return e.b;
			}));
		}
		c(Qe), Qe.prototype.a = function(e) {
			var t = new C();
			return f(this.c, function(n) {
				if (n = n.a(e), !(n instanceof C)) throw Error(`Path expression must evaluate to NodeSet.`);
				t = Me(t, n);
			}), t;
		}, Qe.prototype.toString = function() {
			return p(this.c, function(e, t) {
				return e + O(t);
			}, `Union Expression:`);
		};
		function $e(e, t) {
			this.a = e, this.b = !!t;
		}
		function et(e, t, n) {
			for (n ||= 0; n < e.a.length; n++) for (var r = e.a[n], i = T(t), a = t.l, o, s = 0; o = E(i); s++) {
				var c = e.b ? a - s : s + 1;
				if (o = r.a(new F(o, c, a)), typeof o == `number`) c = c == o;
				else if (typeof o == `string` || typeof o == `boolean`) c = !!o;
				else if (o instanceof C) c = 0 < o.l;
				else throw Error(`Predicate.evaluate returned an unexpected type.`);
				if (!c) {
					c = i, o = c.f;
					var l = c.a;
					if (!l) throw Error(`Next must be called at least once before remove.`);
					var u = l.b, l = l.a;
					u ? u.a = l : o.a = l, l ? l.b = u : o.b = u, o.l--, c.a = null;
				}
			}
			return t;
		}
		$e.prototype.toString = function() {
			return p(this.a, function(e, t) {
				return e + O(t);
			}, `Predicates:`);
		};
		function K(e, t, n, r) {
			D.call(this, 4), this.c = e, this.o = t, this.h = n || new $e([]), this.u = !!r, t = this.h, t = 0 < t.a.length ? t.a[0].f : null, e.b && t && (e = t.name, e = v ? e.toLowerCase() : e, this.f = {
				name: e,
				s: t.s
			});
			a: {
				for (e = this.h, t = 0; t < e.a.length; t++) if (n = e.a[t], n.g || n.i == 1 || n.i == 0) {
					e = !0;
					break a;
				}
				e = !1;
			}
			this.g = e;
		}
		c(K), K.prototype.a = function(e) {
			var t = e.a, n = null, n = this.f, r = null, i = null, a = 0;
			if (n && (r = n.name, i = n.s ? A(n.s, e) : null, a = 1), this.u) if (this.g || this.c != it) if (e = T(new K(at, new z(`node`)).a(e)), t = E(e)) for (n = this.m(t, r, i, a); (t = E(e)) != null;) n = Me(n, this.m(t, r, i, a));
			else n = new C();
			else n = S(this.o, t, r, i), n = et(this.h, n, a);
			else n = this.m(e.a, r, i, a);
			return n;
		}, K.prototype.m = function(e, t, n, r) {
			return e = this.c.f(this.o, e, t, n), e = et(this.h, e, r);
		}, K.prototype.toString = function() {
			var e = `Step:` + O(`Operator: ` + (this.u ? `//` : `/`));
			if (this.c.j && (e += O(`Axis: ` + this.c)), e += O(this.o), this.h.a.length) {
				var t = p(this.h.a, function(e, t) {
					return e + O(t);
				}, `Predicates:`);
				e += O(t);
			}
			return e;
		};
		function tt(e, t, n, r) {
			this.j = e, this.f = t, this.a = n, this.b = r;
		}
		tt.prototype.toString = function() {
			return this.j;
		};
		var nt = {};
		function q(e, t, n, r) {
			if (nt.hasOwnProperty(e)) throw Error(`Axis already created: ` + e);
			return t = new tt(e, t, n, !!r), nt[e] = t;
		}
		q(`ancestor`, function(e, t) {
			for (var n = new C(), r = t; r = r.parentNode;) e.a(r) && Ne(n, r);
			return n;
		}, !0), q(`ancestor-or-self`, function(e, t) {
			var n = new C(), r = t;
			do
				e.a(r) && Ne(n, r);
			while (r = r.parentNode);
			return n;
		}, !0);
		var rt = q(`attribute`, function(e, t) {
			var n = new C(), r = e.f();
			if (r == `style` && v && t.style) return w(n, new y(t.style, t, `style`, t.style.cssText)), n;
			var i = t.attributes;
			if (i) if (e instanceof z && e.b === null || r == `*`) for (var r = 0, a; a = i[r]; r++) v ? a.nodeValue && w(n, be(t, a)) : w(n, a);
			else (a = i.getNamedItem(r)) && (v ? a.nodeValue && w(n, be(t, a)) : w(n, a));
			return n;
		}, !1), it = q(`child`, function(e, t, n, i, a) {
			return (v ? Ce : we).call(null, e, t, r(n) ? n : null, r(i) ? i : null, a || new C());
		}, !1, !0);
		q(`descendant`, S, !1, !0);
		var at = q(`descendant-or-self`, function(e, t, n, r) {
			var i = new C();
			return x(t, n, r) && e.a(t) && w(i, t), S(e, t, n, r, i);
		}, !1, !0), ot = q(`following`, function(e, t, n, r) {
			var i = new C();
			do
				for (var a = t; a = a.nextSibling;) x(a, n, r) && e.a(a) && w(i, a), i = S(e, a, n, r, i);
			while (t = t.parentNode);
			return i;
		}, !1, !0);
		q(`following-sibling`, function(e, t) {
			for (var n = new C(), r = t; r = r.nextSibling;) e.a(r) && w(n, r);
			return n;
		}, !1), q(`namespace`, function() {
			return new C();
		}, !1);
		var st = q(`parent`, function(e, t) {
			var n = new C();
			if (t.nodeType == 9) return n;
			if (t.nodeType == 2) return w(n, t.ownerElement), n;
			var r = t.parentNode;
			return e.a(r) && w(n, r), n;
		}, !1), ct = q(`preceding`, function(e, t, n, r) {
			var i = new C(), a = [];
			do
				a.unshift(t);
			while (t = t.parentNode);
			for (var o = 1, s = a.length; o < s; o++) {
				var c = [];
				for (t = a[o]; t = t.previousSibling;) c.unshift(t);
				for (var l = 0, u = c.length; l < u; l++) t = c[l], x(t, n, r) && e.a(t) && w(i, t), i = S(e, t, n, r, i);
			}
			return i;
		}, !0, !0);
		q(`preceding-sibling`, function(e, t) {
			for (var n = new C(), r = t; r = r.previousSibling;) e.a(r) && Ne(n, r);
			return n;
		}, !0);
		var lt = q(`self`, function(e, t) {
			var n = new C();
			return e.a(t) && w(n, t), n;
		}, !1);
		function J(e) {
			D.call(this, 1), this.c = e, this.g = e.g, this.b = e.b;
		}
		c(J), J.prototype.a = function(e) {
			return -k(this.c, e);
		}, J.prototype.toString = function() {
			return `Unary Expression: -` + O(this.c);
		};
		function ut(e) {
			D.call(this, 1), this.c = e;
		}
		c(ut), ut.prototype.a = function() {
			return this.c;
		}, ut.prototype.toString = function() {
			return `Number: ` + this.c;
		};
		function dt(e, t) {
			this.a = e, this.b = t;
		}
		function ft(e) {
			for (var t, n = [];;) {
				Y(e, `Missing right hand side of binary expression.`), t = yt(e);
				var r = V(e.a);
				if (!r) break;
				var i = (r = Be[r] || null) && r.w;
				if (!i) {
					e.a.a--;
					break;
				}
				for (; n.length && i <= n[n.length - 1].w;) t = new M(n.pop(), n.pop(), t);
				n.push(t, r);
			}
			for (; n.length;) t = new M(n.pop(), n.pop(), t);
			return t;
		}
		function Y(e, t) {
			if (H(e.a)) throw Error(t);
		}
		function pt(e, t) {
			var n = V(e.a);
			if (n != t) throw Error(`Bad token, expected: ` + t + ` got: ` + n);
		}
		function mt(e) {
			if (e = V(e.a), e != `)`) throw Error(`Bad token: ` + e);
		}
		function ht(e) {
			if (e = V(e.a), 2 > e.length) throw Error(`Unclosed literal string`);
			return new U(e);
		}
		function gt(e) {
			var t, n = [], r;
			if (Ze(B(e.a))) {
				if (t = V(e.a), r = B(e.a), t == `/` && (H(e.a) || r != `.` && r != `..` && r != `@` && r != `*` && !/(?![0-9])[\w]/.test(r))) return new G();
				r = new G(), Y(e, `Missing next location step.`), t = _t(e, t), n.push(t);
			} else {
				a: {
					switch (t = B(e.a), r = t.charAt(0), r) {
						case `$`: throw Error(`Variable reference not allowed in HTML XPath`);
						case `(`:
							V(e.a), t = ft(e), Y(e, `unclosed "("`), pt(e, `)`);
							break;
						case `"`:
						case `'`:
							t = ht(e);
							break;
						default: if (isNaN(+t)) if (!We(t) && /(?![0-9])[\w]/.test(r) && B(e.a, 1) == `(`) {
							for (t = V(e.a), t = Ue[t] || null, V(e.a), r = []; B(e.a) != `)` && (Y(e, `Missing function argument list.`), r.push(ft(e)), B(e.a) == `,`);) V(e.a);
							Y(e, `Unclosed function argument list.`), mt(e), t = new L(t, r);
						} else {
							t = null;
							break a;
						}
						else t = new ut(+V(e.a));
					}
					B(e.a) == `[` && (r = new $e(vt(e)), t = new I(t, r));
				}
				if (t) if (Ze(B(e.a))) r = t;
				else return t;
				else t = _t(e, `/`), r = new Xe(), n.push(t);
			}
			for (; Ze(B(e.a));) t = V(e.a), Y(e, `Missing next location step.`), t = _t(e, t), n.push(t);
			return new Ye(r, n);
		}
		function _t(e, t) {
			var n, r, i;
			if (t != `/` && t != `//`) throw Error(`Step op should be "/" or "//"`);
			if (B(e.a) == `.`) return r = new K(lt, new z(`node`)), V(e.a), r;
			if (B(e.a) == `..`) return r = new K(st, new z(`node`)), V(e.a), r;
			var a;
			if (B(e.a) == `@`) a = rt, V(e.a), Y(e, `Missing attribute name`);
			else if (B(e.a, 1) == `::`) {
				if (!/(?![0-9])[\w]/.test(B(e.a).charAt(0))) throw Error(`Bad token: ` + V(e.a));
				if (n = V(e.a), a = nt[n] || null, !a) throw Error(`No axis with name: ` + n);
				V(e.a), Y(e, `Missing node name`);
			} else a = it;
			if (n = B(e.a), /(?![0-9])[\w\*]/.test(n.charAt(0))) if (B(e.a, 1) == `(`) {
				if (!We(n)) throw Error(`Invalid node type: ` + n);
				if (n = V(e.a), !We(n)) throw Error(`Invalid type name: ` + n);
				pt(e, `(`), Y(e, `Bad nodetype`), i = B(e.a).charAt(0);
				var o = null;
				(i == `"` || i == `'`) && (o = ht(e)), Y(e, `Bad nodetype`), mt(e), n = new z(n, o);
			} else if (n = V(e.a), i = n.indexOf(`:`), i == -1) n = new W(n);
			else {
				var o = n.substring(0, i), s;
				if (o == `*`) s = `*`;
				else if (s = e.b(o), !s) throw Error(`Namespace prefix not declared: ` + o);
				n = n.substr(i + 1), n = new W(n, s);
			}
			else throw Error(`Bad token: ` + V(e.a));
			return i = new $e(vt(e), a.a), r || new K(a, n, i, t == `//`);
		}
		function vt(e) {
			for (var t = []; B(e.a) == `[`;) {
				V(e.a), Y(e, `Missing predicate expression.`);
				var n = ft(e);
				t.push(n), Y(e, `Unclosed predicate expression.`), pt(e, `]`);
			}
			return t;
		}
		function yt(e) {
			if (B(e.a) == `-`) return V(e.a), new J(yt(e));
			var t = gt(e);
			if (B(e.a) != `|`) e = t;
			else {
				for (t = [t]; V(e.a) == `|`;) Y(e, `Missing next union location path.`), t.push(gt(e));
				e.a.a--, e = new Qe(t);
			}
			return e;
		}
		function bt(e) {
			switch (e.nodeType) {
				case 1: return s(St, e);
				case 9: return bt(e.documentElement);
				case 11:
				case 10:
				case 6:
				case 12: return xt;
				default: return e.parentNode ? bt(e.parentNode) : xt;
			}
		}
		function xt() {
			return null;
		}
		function St(e, t) {
			if (e.prefix == t) return e.namespaceURI || `http://www.w3.org/1999/xhtml`;
			var n = e.getAttributeNode(`xmlns:` + t);
			return n && n.specified ? n.value || null : e.parentNode && e.parentNode.nodeType != 9 ? St(e.parentNode, t) : null;
		}
		function Ct(e, n) {
			if (!e.length) throw Error(`Empty XPath expression.`);
			var r = Ke(e);
			if (H(r)) throw Error(`Invalid XPath expression.`);
			n ? t(n) == `function` || (n = o(n.lookupNamespaceURI, n)) : n = function() {
				return null;
			};
			var i = ft(new dt(r, n));
			if (!H(r)) throw Error(`Bad token: ` + V(r));
			this.evaluate = function(e, t) {
				return new X(i.a(new F(e)), t);
			};
		}
		function X(e, t) {
			if (t == 0) if (e instanceof C) t = 4;
			else if (typeof e == `string`) t = 2;
			else if (typeof e == `number`) t = 1;
			else if (typeof e == `boolean`) t = 3;
			else throw Error(`Unexpected evaluation result.`);
			if (t != 2 && t != 1 && t != 3 && !(e instanceof C)) throw Error(`value could not be converted to the specified type`);
			this.resultType = t;
			var n;
			switch (t) {
				case 2:
					this.stringValue = e instanceof C ? Fe(e) : `` + e;
					break;
				case 1:
					this.numberValue = e instanceof C ? +Fe(e) : +e;
					break;
				case 3:
					this.booleanValue = e instanceof C ? 0 < e.l : !!e;
					break;
				case 4:
				case 5:
				case 6:
				case 7:
					var r = T(e);
					n = [];
					for (var i = E(r); i; i = E(r)) n.push(i instanceof y ? i.a : i);
					this.snapshotLength = e.l, this.invalidIteratorState = !1;
					break;
				case 8:
				case 9:
					r = Pe(e), this.singleNodeValue = r instanceof y ? r.a : r;
					break;
				default: throw Error(`Unknown XPathResult type.`);
			}
			var a = 0;
			this.iterateNext = function() {
				if (t != 4 && t != 5) throw Error(`iterateNext called with wrong result type`);
				return a >= n.length ? null : n[a++];
			}, this.snapshotItem = function(e) {
				if (t != 6 && t != 7) throw Error(`snapshotItem called with wrong result type`);
				return e >= n.length || 0 > e ? null : n[e];
			};
		}
		X.ANY_TYPE = 0, X.NUMBER_TYPE = 1, X.STRING_TYPE = 2, X.BOOLEAN_TYPE = 3, X.UNORDERED_NODE_ITERATOR_TYPE = 4, X.ORDERED_NODE_ITERATOR_TYPE = 5, X.UNORDERED_NODE_SNAPSHOT_TYPE = 6, X.ORDERED_NODE_SNAPSHOT_TYPE = 7, X.ANY_UNORDERED_NODE_TYPE = 8, X.FIRST_ORDERED_NODE_TYPE = 9;
		function wt(e) {
			this.lookupNamespaceURI = bt(e);
		}
		function Tt(t, n) {
			var r = t || e, i = r.Document && r.Document.prototype || r.document;
			(!i.evaluate || n) && (r.XPathResult = X, i.evaluate = function(e, t, n, r) {
				return new Ct(e, n).evaluate(t, r);
			}, i.createExpression = function(e, t) {
				return new Ct(e, t);
			}, i.createNSResolver = function(e) {
				return new wt(e);
			});
		}
		var Z = [`wgxpath`, `install`], Q = e;
		Z[0] in Q || !Q.execScript || Q.execScript(`var ` + Z[0]);
		for (var $; Z.length && ($ = Z.shift());) Z.length || Tt === void 0 ? Q = Q[$] ? Q[$] : Q[$] = {} : Q[$] = Tt;
		n.exports.install = Tt, n.exports.XPathResultType = {
			ANY_TYPE: 0,
			NUMBER_TYPE: 1,
			STRING_TYPE: 2,
			BOOLEAN_TYPE: 3,
			UNORDERED_NODE_ITERATOR_TYPE: 4,
			ORDERED_NODE_ITERATOR_TYPE: 5,
			UNORDERED_NODE_SNAPSHOT_TYPE: 6,
			ORDERED_NODE_SNAPSHOT_TYPE: 7,
			ANY_UNORDERED_NODE_TYPE: 8,
			FIRST_ORDERED_NODE_TYPE: 9
		};
	}).call(e);
}))();
//#endregion
export { wgxpath_install_node_Csk64Aj9_default as default };

//# sourceMappingURL=wgxpath.install-node-Csk64Aj9.js.map