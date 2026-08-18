//#region ../../node_modules/.pnpm/mathxyjax3@0.8.3/node_modules/mathxyjax3/dist/xypic-DrMJn58R.js
(function() {
	var e = {
		401: function(e, t) {
			MathJax._.components.global.isObject, MathJax._.components.global.combineConfig, t.PV = MathJax._.components.global.combineDefaults, MathJax._.components.global.combineWithMathJax, t.NI = MathJax._.components.global.MathJax;
		},
		771: function(e, t) {
			t.v = MathJax._.core.MmlTree.MML.MML;
		},
		376: function(e, t) {
			t.Ls = MathJax._.core.MmlTree.MmlNode.TEXCLASS, MathJax._.core.MmlTree.MmlNode.TEXCLASSNAMES, MathJax._.core.MmlTree.MmlNode.indentAttributes, t.oI = MathJax._.core.MmlTree.MmlNode.AbstractMmlNode, MathJax._.core.MmlTree.MmlNode.AbstractMmlTokenNode, MathJax._.core.MmlTree.MmlNode.AbstractMmlLayoutNode, MathJax._.core.MmlTree.MmlNode.AbstractMmlBaseNode, MathJax._.core.MmlTree.MmlNode.AbstractMmlEmptyNode, MathJax._.core.MmlTree.MmlNode.TextNode, MathJax._.core.MmlTree.MmlNode.XMLNode;
		},
		226: function(e, t) {
			MathJax._.util.BBox.BBoxStyleAdjust, t.bK = MathJax._.util.BBox.BBox;
		},
		238: function(e, t) {
			t.VK = MathJax._.input.tex.Configuration.Configuration, MathJax._.input.tex.Configuration.ConfigurationHandler, MathJax._.input.tex.Configuration.ParserConfiguration;
		},
		953: function(e, t) {
			t.Z = MathJax._.input.tex.ParseMethods.default;
		},
		166: function(e, t) {
			MathJax._.input.tex.SymbolMap.AbstractSymbolMap, MathJax._.input.tex.SymbolMap.RegExpMap, MathJax._.input.tex.SymbolMap.AbstractParseMap, MathJax._.input.tex.SymbolMap.CharacterMap, MathJax._.input.tex.SymbolMap.DelimiterMap, MathJax._.input.tex.SymbolMap.MacroMap, t.QQ = MathJax._.input.tex.SymbolMap.CommandMap, t.QM = MathJax._.input.tex.SymbolMap.EnvironmentMap;
		},
		847: function(e, t) {
			t.Z = MathJax._.input.tex.TexError.default;
		},
		789: function(e, t) {
			t.Z = MathJax._.input.tex.TexParser.default;
		},
		361: function(e, t) {
			t.Z = MathJax._.input.tex.base.BaseMethods.default;
		},
		81: function(e, t) {
			MathJax._.output.chtml.Wrapper.FONTSIZE, MathJax._.output.chtml.Wrapper.SPACE, t.wO = MathJax._.output.chtml.Wrapper.CHTMLWrapper;
		},
		748: function(e, t) {
			t.w = MathJax._.output.chtml.Wrappers_ts.CHTMLWrappers;
		},
		952: function(e, t) {
			t.y = MathJax._.output.svg.Wrapper.SVGWrapper;
		},
		84: function(e, t) {
			t.N = MathJax._.output.svg.Wrappers_ts.SVGWrappers;
		}
	}, t = {};
	function n(r) {
		var i = t[r];
		if (i !== void 0) return i.exports;
		var a = t[r] = { exports: {} };
		return e[r](a, a.exports, n), a.exports;
	}
	(function() {
		var e = n(401);
		(0, e.PV)(e.NI._, `output`, {
			common: { Wrapper: {} },
			chtml: {
				Wrapper: {},
				Wrappers_ts: {}
			},
			svg: {
				Wrapper: {},
				Wrappers_ts: {}
			}
		});
		var t = n(238), r = n(166), i = n(361), a = n(953), o = n(789), s = n(847);
		function c(e, t) {
			return console.error(e, t), new s.Z(e, t);
		}
		var l = {
			whiteSpaceRegex: /^(\s+|%[^\r\n]*(\r\n|\r|\n)?)+/,
			lengthResolution: 128,
			interpolationResolution: 5,
			machinePrecision: 1e-12
		};
		function u(e) {
			return u = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
				return typeof e;
			} : function(e) {
				return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e;
			}, u(e);
		}
		function d(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function f(e, t, n) {
			return t && d(e.prototype, t), n && d(e, n), e;
		}
		function p(e, t) {
			if (typeof t != `function` && t !== null) throw TypeError(`Super expression must either be null or a function`);
			e.prototype = Object.create(t && t.prototype, { constructor: {
				value: e,
				writable: !0,
				configurable: !0
			} }), t && m(e, t);
		}
		function m(e, t) {
			return m = Object.setPrototypeOf || function(e, t) {
				return e.__proto__ = t, e;
			}, m(e, t);
		}
		function h(e) {
			var t = function() {
				if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return !1;
				if (typeof Proxy == `function`) return !0;
				try {
					return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {}))), !0;
				} catch {
					return !1;
				}
			}();
			return function() {
				var n, r = _(e);
				if (t) {
					var i = _(this).constructor;
					n = Reflect.construct(r, arguments, i);
				} else n = r.apply(this, arguments);
				return g(this, n);
			};
		}
		function g(e, t) {
			if (t && (u(t) === `object` || typeof t == `function`)) return t;
			if (t !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
			return function(e) {
				if (e === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
				return e;
			}(e);
		}
		function _(e) {
			return _ = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
				return e.__proto__ || Object.getPrototypeOf(e);
			}, _(e);
		}
		function v(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		var y = function e() {
			v(this, e);
		}, b = function(e) {
			p(n, e);
			var t = h(n);
			function n(e) {
				var r;
				return v(this, n), (r = t.call(this)).get = e, r;
			}
			return f(n, [
				{
					key: `isEmpty`,
					get: function() {
						return !1;
					}
				},
				{
					key: `isDefined`,
					get: function() {
						return !0;
					}
				},
				{
					key: `getOrElse`,
					value: function(e) {
						return this.get;
					}
				},
				{
					key: `flatMap`,
					value: function(e) {
						return e(this.get);
					}
				},
				{
					key: `map`,
					value: function(e) {
						return new n(e(this.get));
					}
				},
				{
					key: `foreach`,
					value: function(e) {
						e(this.get);
					}
				},
				{
					key: `toString`,
					value: function() {
						return `Some(` + this.get + `)`;
					}
				}
			], [{
				key: `unapply`,
				value: function(e) {
					return new n(e.get);
				}
			}]), n;
		}(y), x = function(e) {
			p(n, e);
			var t = h(n);
			function n() {
				return v(this, n), t.call(this);
			}
			return f(n, [
				{
					key: `isEmpty`,
					get: function() {
						return !0;
					}
				},
				{
					key: `isDefined`,
					get: function() {
						return !1;
					}
				},
				{
					key: `getOrElse`,
					value: function(e) {
						return e;
					}
				},
				{
					key: `flatMap`,
					value: function(e) {
						return this;
					}
				},
				{
					key: `foreach`,
					value: function(e) {}
				},
				{
					key: `map`,
					value: function(e) {
						return this;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `None`;
					}
				}
			], [{
				key: `unapply`,
				value: function(e) {
					return new b(e);
				}
			}]), n;
		}(y);
		function S(e) {
			return S = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
				return typeof e;
			} : function(e) {
				return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e;
			}, S(e);
		}
		function C(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function w(e, t, n) {
			return t && C(e.prototype, t), n && C(e, n), e;
		}
		function T(e, t) {
			if (typeof t != `function` && t !== null) throw TypeError(`Super expression must either be null or a function`);
			e.prototype = Object.create(t && t.prototype, { constructor: {
				value: e,
				writable: !0,
				configurable: !0
			} }), t && E(e, t);
		}
		function E(e, t) {
			return E = Object.setPrototypeOf || function(e, t) {
				return e.__proto__ = t, e;
			}, E(e, t);
		}
		function D(e) {
			var t = function() {
				if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return !1;
				if (typeof Proxy == `function`) return !0;
				try {
					return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {}))), !0;
				} catch {
					return !1;
				}
			}();
			return function() {
				var n, r = te(e);
				if (t) {
					var i = te(this).constructor;
					n = Reflect.construct(r, arguments, i);
				} else n = r.apply(this, arguments);
				return ee(this, n);
			};
		}
		function ee(e, t) {
			if (t && (S(t) === `object` || typeof t == `function`)) return t;
			if (t !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
			return function(e) {
				if (e === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
				return e;
			}(e);
		}
		function te(e) {
			return te = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
				return e.__proto__ || Object.getPrototypeOf(e);
			}, te(e);
		}
		function ne(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		y.Some = b, y.None = x, y.empty = new x();
		var O = function e() {
			ne(this, e);
		}, re = function(e) {
			T(n, e);
			var t = D(n);
			function n(e, r) {
				var i;
				return ne(this, n), (i = t.call(this)).head = e, i.tail = r, i;
			}
			return w(n, [
				{
					key: `isEmpty`,
					get: function() {
						return !1;
					}
				},
				{
					key: `at`,
					value: function(e) {
						if (e < 0 || e >= this.length()) throw Error(`no such element at ` + e + `. index must be lower than ` + this.length() + `.`);
						for (var t = this, n = 0; n < e; n++) t = t.tail;
						return t.head;
					}
				},
				{
					key: `length`,
					value: function() {
						for (var e = this, t = 0; !e.isEmpty;) t++, e = e.tail;
						return t;
					}
				},
				{
					key: `prepend`,
					value: function(e) {
						return new n(e, this);
					}
				},
				{
					key: `append`,
					value: function(e) {
						var t = new n(e, O.empty);
						return this.reverse().foreach((function(e) {
							t = new n(e, t);
						})), t;
					}
				},
				{
					key: `concat`,
					value: function(e) {
						var t = e;
						return this.reverse().foreach((function(e) {
							t = new n(e, t);
						})), t;
					}
				},
				{
					key: `foldLeft`,
					value: function(e, t) {
						var n, r;
						for (n = t(e, this.head), r = this.tail; !r.isEmpty;) n = t(n, r.head), r = r.tail;
						return n;
					}
				},
				{
					key: `foldRight`,
					value: function(e, t) {
						return this.tail.isEmpty ? t(this.head, e) : t(this.head, this.tail.foldRight(e, t));
					}
				},
				{
					key: `map`,
					value: function(e) {
						return new n(e(this.head), this.tail.map(e));
					}
				},
				{
					key: `flatMap`,
					value: function(e) {
						return e(this.head).concat(this.tail.flatMap(e));
					}
				},
				{
					key: `foreach`,
					value: function(e) {
						for (var t = this; !t.isEmpty;) e(t.head), t = t.tail;
					}
				},
				{
					key: `reverse`,
					value: function() {
						var e = O.empty;
						return this.foreach((function(t) {
							e = new n(t, e);
						})), e;
					}
				},
				{
					key: `mkString`,
					value: function() {
						var e, t, r, i, a;
						switch (arguments.length) {
							case 0:
								e = t = r = ``;
								break;
							case 1:
								t = arguments[0], e = r = ``;
								break;
							case 2:
								e = arguments[0], t = arguments[1], r = ``;
								break;
							default: e = arguments[0], t = arguments[1], r = arguments[2];
						}
						for (i = e + this.head.toString(), a = this.tail; a instanceof n;) i += t + a.head.toString(), a = a.tail;
						return i += r;
					}
				},
				{
					key: `toString`,
					value: function() {
						return this.mkString(`[`, `, `, `]`);
					}
				}
			], [{
				key: `unapply`,
				value: function(e) {
					return new y.Some([e.head, e.tail]);
				}
			}]), n;
		}(O);
		O.Cons = re;
		var ie = function(e) {
			T(n, e);
			var t = D(n);
			function n() {
				return ne(this, n), t.call(this);
			}
			return w(n, [
				{
					key: `isEmpty`,
					get: function() {
						return !0;
					}
				},
				{
					key: `at`,
					value: function(e) {
						throw Error(`cannot get element from an empty list.`);
					}
				},
				{
					key: `length`,
					value: function() {
						return 0;
					}
				},
				{
					key: `prepend`,
					value: function(e) {
						return new re(e, O.empty);
					}
				},
				{
					key: `append`,
					value: function(e) {
						return new re(e, O.empty);
					}
				},
				{
					key: `concat`,
					value: function(e) {
						return e;
					}
				},
				{
					key: `foldLeft`,
					value: function(e, t) {
						return e;
					}
				},
				{
					key: `foldRight`,
					value: function(e, t) {
						return e;
					}
				},
				{
					key: `flatMap`,
					value: function(e) {
						return this;
					}
				},
				{
					key: `map`,
					value: function(e) {
						return this;
					}
				},
				{
					key: `foreach`,
					value: function(e) {}
				},
				{
					key: `reverse`,
					value: function() {
						return this;
					}
				},
				{
					key: `mkString`,
					value: function() {
						switch (arguments.length) {
							case 0:
							case 1: return ``;
							case 2: return arguments[0];
							default: return arguments[0] + arguments[2];
						}
					}
				},
				{
					key: `toString`,
					value: function() {
						return `[]`;
					}
				}
			], [{
				key: `unapply`,
				value: function(e) {
					return new y.Some(e);
				}
			}]), n;
		}(O);
		function ae(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		O.Nil = ie, O.empty = new ie(), O.fromArray = function(e) {
			var t, n;
			for (t = O.empty, n = e.length - 1; n >= 0;) t = new re(e[n], t), --n;
			return t;
		};
		var oe = function() {
			function e(t, n) {
				(function(e, t) {
					if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
				})(this, e), this.head = t, this.tail = n;
			}
			var t, n, r;
			return t = e, r = [{
				key: `unapply`,
				value: function(e) {
					return new Option.Some([e.head, e.tail]);
				}
			}], (n = [{
				key: `toString`,
				value: function() {
					return `(` + this.head + `~` + this.tail + `)`;
				}
			}]) && ae(t.prototype, n), r && ae(t, r), e;
		}();
		function se(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		function ce(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function le(e, t, n) {
			return t && ce(e.prototype, t), n && ce(e, n), e;
		}
		var ue = function() {
			function e() {
				se(this, e), this.cases = [];
			}
			return le(e, [{
				key: `Case`,
				value: function(e, t) {
					return this.cases.push([e, t]), this;
				}
			}, {
				key: `match`,
				value: function(e) {
					var t, n, r, i;
					for (t = 0, n = this.cases.length; t < n;) {
						if (e instanceof (r = this.cases[t][0]) && (i = r.unapply(e)).isDefined) return this.cases[t][1](i.get);
						t += 1;
					}
					throw new de(e);
				}
			}]), e;
		}(), de = function() {
			function e(t) {
				se(this, e), this.obj = t;
			}
			return le(e, [{
				key: `toString`,
				value: function() {
					return `MatchError(` + this.obj + `)`;
				}
			}]), e;
		}();
		function fe(e) {
			return fe = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
				return typeof e;
			} : function(e) {
				return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e;
			}, fe(e);
		}
		function pe(e, t) {
			if (typeof t != `function` && t !== null) throw TypeError(`Super expression must either be null or a function`);
			e.prototype = Object.create(t && t.prototype, { constructor: {
				value: e,
				writable: !0,
				configurable: !0
			} }), t && me(e, t);
		}
		function me(e, t) {
			return me = Object.setPrototypeOf || function(e, t) {
				return e.__proto__ = t, e;
			}, me(e, t);
		}
		function he(e) {
			var t = function() {
				if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return !1;
				if (typeof Proxy == `function`) return !0;
				try {
					return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {}))), !0;
				} catch {
					return !1;
				}
			}();
			return function() {
				var n, r = _e(e);
				if (t) {
					var i = _e(this).constructor;
					n = Reflect.construct(r, arguments, i);
				} else n = r.apply(this, arguments);
				return ge(this, n);
			};
		}
		function ge(e, t) {
			if (t && (fe(t) === `object` || typeof t == `function`)) return t;
			if (t !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
			return function(e) {
				if (e === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
				return e;
			}(e);
		}
		function _e(e) {
			return _e = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
				return e.__proto__ || Object.getPrototypeOf(e);
			}, _e(e);
		}
		function ve(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		function ye(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function be(e, t, n) {
			return t && ye(e.prototype, t), n && ye(e, n), e;
		}
		var xe = function() {
			function e(t, n) {
				ve(this, e), this.source = t, this.offset = n === void 0 ? 0 : n, this._index = null, this._line = null;
			}
			return be(e, [
				{
					key: `index`,
					value: function() {
						if (this._index !== null) return this._index;
						this._index = [], this._index.push(0);
						for (var e = 0; e < this.source.length;) this.source.charAt(e) === `
` && this._index.push(e + 1), e += 1;
						return this._index.push(this.source.length), this._index;
					}
				},
				{
					key: `line`,
					value: function() {
						var e, t, n;
						if (this._line !== null) return this._line;
						for (e = 0, t = this.index().length - 1; e + 1 < t;) n = t + e >> 1, this.offset < this.index()[n] ? t = n : e = n;
						return this._line = e + 1, this._line;
					}
				},
				{
					key: `column`,
					value: function() {
						return this.offset - this.index()[this.line() - 1] + 1;
					}
				},
				{
					key: `lineContents`,
					value: function() {
						var e, t;
						return e = this.index(), t = this.line(), this.source.substring(e[t - 1], e[t]);
					}
				},
				{
					key: `toString`,
					value: function() {
						return this.line().toString() + `.` + this.column();
					}
				},
				{
					key: `longString`,
					value: function() {
						var e, t;
						for (e = this.lineContents() + `
`, t = 0; t < this.column();) this.lineContents().charAt(t) === `	` ? e += `	` : e += ` `, t += 1;
						return e += `^`;
					}
				},
				{
					key: `isLessThan`,
					value: function(t) {
						return t instanceof e ? this.offset < t.offset : this.line() < t.line() || this.line() === t.line() && this.column() < t.column();
					}
				}
			]), e;
		}(), Se = function() {
			function e(t, n, r) {
				ve(this, e), this.source = t, this.offset = n, this.context = r;
			}
			return be(e, [
				{
					key: `first`,
					value: function() {
						return this.offset < this.source.length ? this.source.charAt(this.offset) : e.EofCh;
					}
				},
				{
					key: `rest`,
					value: function() {
						return this.offset < this.source.length ? new e(this.source, this.offset + 1, this.context) : this;
					}
				},
				{
					key: `pos`,
					value: function() {
						return new xe(this.source, this.offset);
					}
				},
				{
					key: `atEnd`,
					value: function() {
						return this.offset >= this.source.length;
					}
				},
				{
					key: `drop`,
					value: function(e) {
						var t, n;
						for (t = this, n = e; n > 0;) t = t.rest(), --n;
						return t;
					}
				}
			]), e;
		}();
		Se.EofCh = ``;
		var k = function() {
			function e() {
				ve(this, e);
			}
			return be(e, null, [
				{
					key: `parse`,
					value: function(e, t) {
						return e.apply(t);
					}
				},
				{
					key: `parseAll`,
					value: function(t, n) {
						return t.andl((function() {
							return e.eos();
						})).apply(n);
					}
				},
				{
					key: `parseString`,
					value: function(t, n) {
						var r = new Se(n, 0, { lastNoSuccess: void 0 });
						return e.parse(t, r);
					}
				},
				{
					key: `parseAllString`,
					value: function(t, n) {
						var r = new Se(n, 0, { lastNoSuccess: void 0 });
						return e.parseAll(t, r);
					}
				},
				{
					key: `_handleWhiteSpace`,
					value: function(e) {
						var t = e.context.whiteSpaceRegex, n = e.source, r = e.offset, i = t.exec(n.substring(r, n.length));
						return i === null ? r : r + i[0].length;
					}
				},
				{
					key: `literal`,
					value: function(t) {
						return new Oe((function(n) {
							var r, i, a, o, s, c;
							for (r = n.source, i = n.offset, o = 0, s = a = e._handleWhiteSpace(n); o < t.length && s < r.length && t.charAt(o) === r.charAt(s);) o += 1, s += 1;
							return o === t.length ? new we(t, n.drop(s - i)) : (c = a === r.length ? `end of source` : "`" + r.charAt(a) + `'`, new Ee("`" + t + `' expected but ` + c + ` found`, n.drop(a - i)));
						}));
					}
				},
				{
					key: `regex`,
					value: function(e) {
						if (e.toString().substring(0, 2) !== `/^`) throw "regex must start with `^' but " + e;
						return new Oe((function(t) {
							var n, r, i, a;
							return n = t.source, r = t.offset, (i = e.exec(n.substring(r, n.length))) === null ? (a = r === n.length ? `end of source` : "`" + n.charAt(r) + `'`, new Ee(`string matching regex ` + e + ` expected but ` + a + ` found`, t)) : new we(i[0], t.drop(i[0].length));
						}));
					}
				},
				{
					key: `regexLiteral`,
					value: function(t) {
						if (t.toString().substring(0, 2) !== `/^`) throw "regex must start with `^' but " + t;
						return new Oe((function(n) {
							var r, i, a, o, s;
							return r = n.source, i = n.offset, a = e._handleWhiteSpace(n), (o = t.exec(r.substring(a, r.length))) === null ? (s = a === r.length ? `end of source` : "`" + r.charAt(a) + `'`, new Ee(`string matching regex ` + t + ` expected but ` + s + ` found`, n.drop(a - i))) : new we(o[0], n.drop(a + o[0].length - i));
						}));
					}
				},
				{
					key: `eos`,
					value: function() {
						return new Oe((function(t) {
							var n, r;
							return n = t.source, t.offset, r = e._handleWhiteSpace(t), n.length === r ? new we(``, t) : new Ee("end of source expected but `" + n.charAt(r) + `' found`, t);
						}));
					}
				},
				{
					key: `commit`,
					value: function(e) {
						return new Oe((function(t) {
							var n = e()(t);
							return new ue().Case(we, (function(e) {
								return n;
							})).Case(De, (function(e) {
								return n;
							})).Case(Ee, (function(e) {
								return new De(e[0], e[1]);
							})).match(n);
						}));
					}
				},
				{
					key: `elem`,
					value: function(t) {
						return e.accept(t).named(`"` + t + `"`);
					}
				},
				{
					key: `accept`,
					value: function(t) {
						return e.acceptIf((function(e) {
							return e === t;
						}), (function(e) {
							return "`" + t + "' expected but `" + e + `' found`;
						}));
					}
				},
				{
					key: `acceptIf`,
					value: function(e, t) {
						return new Oe((function(n) {
							return e(n.first()) ? new we(n.first(), n.rest()) : new Ee(t(n.first()), n);
						}));
					}
				},
				{
					key: `failure`,
					value: function(e) {
						return new Oe((function(t) {
							return new Ee(e, t);
						}));
					}
				},
				{
					key: `err`,
					value: function(e) {
						return new Oe((function(t) {
							return new De(e, t);
						}));
					}
				},
				{
					key: `success`,
					value: function(e) {
						return new Oe((function(t) {
							return new we(e, t);
						}));
					}
				},
				{
					key: `log`,
					value: function(e, t) {
						return new Oe((function(n) {
							console.log(`trying ` + t + ` at ` + n);
							var r = e().apply(n);
							return console.log(t + ` --> ` + r), r;
						}));
					}
				},
				{
					key: `rep`,
					value: function(t) {
						var n = e.success(O.empty);
						return e.rep1(t).or((function() {
							return n;
						}));
					}
				},
				{
					key: `rep1`,
					value: function(e) {
						return new Oe((function(t) {
							var n, r, i, a;
							if (n = [], r = t, (a = (i = e()).apply(t)) instanceof we) {
								for (; a instanceof we;) n.push(a.result), r = a.next, a = i.apply(r);
								return new we(O.fromArray(n), r);
							}
							return a;
						}));
					}
				},
				{
					key: `repN`,
					value: function(t, n) {
						return t === 0 ? e.success(FP.List.empty) : new Oe((function(e) {
							var r, i, a, o;
							for (r = [], i = e, o = (a = n()).apply(i); o instanceof we;) {
								if (r.push(o.result), i = o.next, t === r.length) return new we(O.fromArray(r), i);
								o = a.apply(i);
							}
							return o;
						}));
					}
				},
				{
					key: `repsep`,
					value: function(t, n) {
						var r = e.success(O.empty);
						return e.rep1sep(t, n).or((function() {
							return r;
						}));
					}
				},
				{
					key: `rep1sep`,
					value: function(t, n) {
						return t().and(e.rep(n().andr(t))).to((function(e) {
							return new O.Cons(e.head, e.tail);
						}));
					}
				},
				{
					key: `chainl1`,
					value: function(t, n, r) {
						return t().and(e.rep(r().and(n))).to((function(e) {
							return e.tail.foldLeft(e.head, (function(e, t) {
								return t.head(e, t.tail);
							}));
						}));
					}
				},
				{
					key: `chainr1`,
					value: function(e, t, n, r) {
						return e().and(this.rep(t().and(e))).to((function(e) {
							return new O.Cons(new oe(n, e.head), e.tail).foldRight(r, (function(e, t) {
								return e.head(e.tail, t);
							}));
						}));
					}
				},
				{
					key: `opt`,
					value: function(t) {
						return t().to((function(e) {
							return new y.Some(e);
						})).or((function() {
							return e.success(y.empty);
						}));
					}
				},
				{
					key: `not`,
					value: function(e) {
						return new Oe((function(t) {
							return e().apply(t).successful ? new Ee(`Expected failure`, t) : new we(y.empty, t);
						}));
					}
				},
				{
					key: `guard`,
					value: function(e) {
						return new Oe((function(t) {
							var n = e().apply(t);
							return n.successful ? new we(n.result, t) : n;
						}));
					}
				},
				{
					key: `mkList`,
					value: function(e) {
						return new O.Cons(e.head, e.tail);
					}
				},
				{
					key: `fun`,
					value: function(e) {
						return function() {
							return e;
						};
					}
				},
				{
					key: `lazyParser`,
					value: function(t) {
						var n, r;
						return t instanceof String || typeof t == `string` ? (n = e.literal(t), function() {
							return n;
						}) : t instanceof Function ? t : t instanceof Object ? t instanceof Oe ? function() {
							return t;
						} : t instanceof RegExp ? (r = e.regexLiteral(t), function() {
							return r;
						}) : e.err(`unhandlable type`) : e.err(`unhandlable type`);
					}
				},
				{
					key: `seq`,
					value: function() {
						var t, n, r;
						if ((t = arguments.length) === 0) return e.err(`at least one element must be specified`);
						for (n = e.lazyParser(arguments[0])(), r = 1; r < t;) n = n.and(e.lazyParser(arguments[r])), r += 1;
						return n;
					}
				},
				{
					key: `or`,
					value: function() {
						var t, n, r;
						if ((t = arguments.length) === 0) return e.err(`at least one element must be specified`);
						for (n = e.lazyParser(arguments[0])(), r = 1; r < t;) n = n.or(e.lazyParser(arguments[r])), r += 1;
						return n;
					}
				}
			]), e;
		}(), Ce = function() {
			function e() {
				ve(this, e);
			}
			return be(e, [{
				key: `isEmpty`,
				value: function() {
					return !this.successful;
				}
			}, {
				key: `getOrElse`,
				value: function(e) {
					return this.isEmpty ? e() : this.get();
				}
			}]), e;
		}();
		k.ParseResult = Ce;
		var we = function(e) {
			pe(n, e);
			var t = he(n);
			function n(e, r) {
				var i;
				return ve(this, n), (i = t.call(this)).result = e, i.next = r, i;
			}
			return be(n, [
				{
					key: `successful`,
					get: function() {
						return !0;
					}
				},
				{
					key: `map`,
					value: function(e) {
						return new n(e(this.result), this.next);
					}
				},
				{
					key: `mapPartial`,
					value: function(e, t) {
						try {
							return new n(e(this.result), this.next);
						} catch (e) {
							if (e instanceof de) return new Ee(t(this.result), this.next);
							throw e;
						}
					}
				},
				{
					key: `flatMapWithNext`,
					value: function(e) {
						return e(this.result).apply(this.next);
					}
				},
				{
					key: `append`,
					value: function(e) {
						return this;
					}
				},
				{
					key: `get`,
					value: function() {
						return this.result;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `[` + this.next.pos() + `] parsed: ` + this.result;
					}
				}
			], [{
				key: `unapply`,
				value: function(e) {
					return new y.Some([e.result, e.next]);
				}
			}]), n;
		}(Ce);
		k.Success = we;
		var Te = function(e) {
			pe(n, e);
			var t = he(n);
			function n() {
				return ve(this, n), t.call(this);
			}
			return be(n, [
				{
					key: `successful`,
					get: function() {
						return !1;
					}
				},
				{
					key: `_setLastNoSuccess`,
					value: function() {
						var e = this.next.context;
						e.lastNoSuccess !== void 0 && this.next.pos().isLessThan(e.lastNoSuccess.next.pos()) || (e.lastNoSuccess = this);
					}
				},
				{
					key: `map`,
					value: function(e) {
						return this;
					}
				},
				{
					key: `mapPartial`,
					value: function(e, t) {
						return this;
					}
				},
				{
					key: `flatMapWithNext`,
					value: function(e) {
						return this;
					}
				},
				{
					key: `get`,
					value: function() {
						return k.error(`No result when parsing failed`);
					}
				}
			]), n;
		}(Ce);
		k.NoSuccess = Te;
		var Ee = function(e) {
			pe(n, e);
			var t = he(n);
			function n(e, r) {
				var i;
				return ve(this, n), (i = t.call(this)).msg = e, i.next = r, i._setLastNoSuccess(), i;
			}
			return be(n, [{
				key: `append`,
				value: function(e) {
					var t = e();
					if (t instanceof we) return t;
					if (t instanceof Te) return t.next.pos().isLessThan(this.next.pos()) ? this : t;
					throw new de(t);
				}
			}, {
				key: `toString`,
				value: function() {
					return `[` + this.next.pos() + `] failure: ` + this.msg + `

` + this.next.pos().longString();
				}
			}], [{
				key: `unapply`,
				value: function(e) {
					return new y.Some([e.msg, e.next]);
				}
			}]), n;
		}(Te);
		k.Failure = Ee;
		var De = function(e) {
			pe(n, e);
			var t = he(n);
			function n(e, r) {
				var i;
				return ve(this, n), (i = t.call(this)).msg = e, i.next = r, i._setLastNoSuccess(), i;
			}
			return be(n, [{
				key: `append`,
				value: function(e) {
					return this;
				}
			}, {
				key: `toString`,
				value: function() {
					return `[` + this.next.pos() + `] error: ` + this.msg + `

` + this.next.pos().longString();
				}
			}], [{
				key: `unapply`,
				value: function(e) {
					return new y.Some([e.msg, e.next]);
				}
			}]), n;
		}(Te);
		k.ParseError = De;
		var Oe = function() {
			function e(t) {
				ve(this, e), this.apply = t, this.name = ``;
			}
			return be(e, [
				{
					key: `named`,
					value: function(e) {
						return this.name = e, this;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `Parser (` + this.name + `)`;
					}
				},
				{
					key: `flatMap`,
					value: function(t) {
						var n = this;
						return new e((function(e) {
							return n.apply(e).flatMapWithNext(t);
						}));
					}
				},
				{
					key: `map`,
					value: function(t) {
						var n = this;
						return new e((function(e) {
							return n.apply(e).map(t);
						}));
					}
				},
				{
					key: `append`,
					value: function(t) {
						var n = this;
						return new e((function(e) {
							return n.apply(e).append((function() {
								return t().apply(e);
							}));
						}));
					}
				},
				{
					key: `and`,
					value: function(e) {
						return this.flatMap((function(t) {
							return e().map((function(e) {
								return new oe(t, e);
							}));
						})).named(`~`);
					}
				},
				{
					key: `andr`,
					value: function(e) {
						return this.flatMap((function(t) {
							return e().map((function(e) {
								return e;
							}));
						})).named(`~>`);
					}
				},
				{
					key: `andl`,
					value: function(e) {
						return this.flatMap((function(t) {
							return e().map((function(e) {
								return t;
							}));
						})).named(`<~`);
					}
				},
				{
					key: `or`,
					value: function(e) {
						return this.append(e).named(`|`);
					}
				},
				{
					key: `andOnce`,
					value: function(e) {
						var t = this;
						return new ke((function() {
							return t.flatMap((function(t) {
								return k.commit(e).map((function(e) {
									return new oe(t, e);
								}));
							})).named(`~!`);
						}));
					}
				},
				{
					key: `longestOr`,
					value: function(t) {
						var n = this;
						return new e((function(e) {
							var r, i;
							return r = n.apply(e), i = t()(e), r.successful ? i.successful ? i.next.pos().isLessThan(r.next.pos()) ? r : i : r : i.successful ? i : r instanceof De || i.next.pos().isLessThan(r.next.pos()) ? r : i;
						})).named(`|||`);
					}
				},
				{
					key: `to`,
					value: function(e) {
						return this.map(e).named(this.toString() + `^^`);
					}
				},
				{
					key: `ret`,
					value: function(t) {
						var n = this;
						return new e((function(e) {
							return n.apply(e).map((function(e) {
								return t();
							}));
						})).named(this.toString() + `^^^`);
					}
				},
				{
					key: `toIfPossible`,
					value: function(t, n) {
						n === void 0 && (n = function(e) {
							return `Constructor function not defined at ` + e;
						});
						var r = this;
						return new e((function(e) {
							return r.apply(e).mapPartial(t, n);
						})).named(this.toString() + `^?`);
					}
				},
				{
					key: `into`,
					value: function(e) {
						return this.flatMap(e);
					}
				},
				{
					key: `rep`,
					value: function() {
						var e = this;
						return k.rep((function() {
							return e;
						}));
					}
				},
				{
					key: `chain`,
					value: function(e) {
						var t, n;
						return t = this, n = function() {
							return t;
						}, k.chainl1(n, n, e);
					}
				},
				{
					key: `rep1`,
					value: function() {
						var e = this;
						return k.rep1((function() {
							return e;
						}));
					}
				},
				{
					key: `opt`,
					value: function() {
						var e = this;
						return k.opt((function() {
							return e;
						}));
					}
				}
			]), e;
		}();
		k.Parser = Oe;
		var ke = function(e) {
			pe(n, e);
			var t = he(n);
			function n(e) {
				return ve(this, n), t.call(this, e);
			}
			return be(n, [{
				key: `and`,
				value: function(e) {
					var t = this;
					return new n((function() {
						return t.flatMap((function(t) {
							return k.commit(e).map((function(e) {
								return oe(t, e);
							}));
						}));
					})).named(`~`);
				}
			}]), n;
		}(Oe);
		k.OnceParser = ke;
		var Ae = n(376), je = n(771);
		function Me(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		function Ne(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function Pe(e, t, n) {
			return t && Ne(e.prototype, t), n && Ne(e, n), e;
		}
		var Fe = function() {
			function e() {
				Me(this, e), this.userDirMap = {};
			}
			return Pe(e, [{
				key: `get`,
				value: function(e) {
					return this.userDirMap[e];
				}
			}, {
				key: `put`,
				value: function(e, t) {
					this.userDirMap[e] = t;
				}
			}]), e;
		}(), Ie = function() {
			function e() {
				Me(this, e), this.userModifierMap = {};
			}
			return Pe(e, [{
				key: `get`,
				value: function(t) {
					var n = e.embeddedModifierMap[t];
					return n === void 0 ? this.userModifierMap[t] : n;
				}
			}, {
				key: `put`,
				value: function(t, n) {
					e.embeddedModifierMap[t] === void 0 && (this.userModifierMap[t] = n);
				}
			}]), e;
		}(), A = {
			repositories: {
				modifierRepository: new Ie(),
				dirRepository: new Fe()
			},
			xypicCommandIdCounter: 0,
			xypicCommandMap: {},
			textObjectIdCounter: 0,
			wrapperOfTextObjectMap: {}
		};
		function Le(e) {
			return Le = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
				return typeof e;
			} : function(e) {
				return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e;
			}, Le(e);
		}
		function Re(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function j(e, t, n) {
			return t && Re(e.prototype, t), n && Re(e, n), e;
		}
		function M(e, t) {
			if (typeof t != `function` && t !== null) throw TypeError(`Super expression must either be null or a function`);
			e.prototype = Object.create(t && t.prototype, { constructor: {
				value: e,
				writable: !0,
				configurable: !0
			} }), t && ze(e, t);
		}
		function ze(e, t) {
			return ze = Object.setPrototypeOf || function(e, t) {
				return e.__proto__ = t, e;
			}, ze(e, t);
		}
		function N(e) {
			var t = function() {
				if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return !1;
				if (typeof Proxy == `function`) return !0;
				try {
					return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {}))), !0;
				} catch {
					return !1;
				}
			}();
			return function() {
				var n, r = Ve(e);
				if (t) {
					var i = Ve(this).constructor;
					n = Reflect.construct(r, arguments, i);
				} else n = r.apply(this, arguments);
				return Be(this, n);
			};
		}
		function Be(e, t) {
			if (t && (Le(t) === `object` || typeof t == `function`)) return t;
			if (t !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
			return function(e) {
				if (e === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
				return e;
			}(e);
		}
		function Ve(e) {
			return Ve = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
				return e.__proto__ || Object.getPrototypeOf(e);
			}, Ve(e);
		}
		function P(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		var F = function e() {
			P(this, e);
		}, He = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i) {
				var a;
				P(this, n), (a = t.call(this, e, r, i)).textMmls = i, a.texClass = Ae.Ls.ORD;
				var o = r[`data-cmd-id`];
				a.cmd = A.xypicCommandMap[o];
				for (var s = JSON.parse(r[`data-text-mml-ids`]), c = 0, l = s.length; c < l; c++) i[c].xypicTextObjectId = s[c];
				return a;
			}
			return n;
		}(Ae.oI);
		He.defaults = Ae.oI.defaults, (F.xypic = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i) {
				return P(this, n), t.call(this, e, r, i);
			}
			return j(n, [{
				key: `kind`,
				get: function() {
					return `xypic`;
				}
			}, {
				key: `toString`,
				value: function() {
					return this.kind + `(` + this.cmd + `)`;
				}
			}]), n;
		}(He)).defaults = He.defaults, je.v[F.xypic.prototype.kind] = F.xypic, F.xypic.newdir = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i) {
				return P(this, n), t.call(this, e, r, i);
			}
			return j(n, [{
				key: `kind`,
				get: function() {
					return `xypic-newdir`;
				}
			}, {
				key: `toString`,
				value: function() {
					return this.kind + `(` + this.cmd + `)`;
				}
			}]), n;
		}(He), F.xypic.newdir.defaults = He.defaults, je.v[F.xypic.newdir.prototype.kind] = F.xypic.newdir, F.xypic.includegraphics = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i) {
				return P(this, n), t.call(this, e, r, i);
			}
			return j(n, [{
				key: `kind`,
				get: function() {
					return `xypic-includegraphics`;
				}
			}, {
				key: `toString`,
				value: function() {
					return this.kind + `(` + this.cmd + `)`;
				}
			}]), n;
		}(He), F.xypic.includegraphics.defaults = He.defaults, je.v[F.xypic.includegraphics.prototype.kind] = F.xypic.includegraphics, F.PosDecor = function() {
			function e(t, n) {
				P(this, e), this.pos = t, this.decor = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.pos.toString() + ` ` + this.decor;
				}
			}]), e;
		}(), (F.Pos = function e() {
			P(this, e);
		}).Coord = function() {
			function e(t, n) {
				P(this, e), this.coord = t, this.pos2s = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.coord.toString() + ` ` + this.pos2s.mkString(` `);
				}
			}]), e;
		}(), F.Pos.Plus = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `+(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.Minus = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `-(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.Skew = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `!(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.Cover = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `.(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.Then = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `,(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.SwapPAndC = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `;(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.SetBase = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `:(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.SetYBase = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `::(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.ConnectObject = function() {
			function e(t) {
				P(this, e), this.object = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `**(` + this.object + `)`;
				}
			}]), e;
		}(), F.Pos.DropObject = function() {
			function e(t) {
				P(this, e), this.object = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `*(` + this.object + `)`;
				}
			}]), e;
		}(), F.Pos.Place = function() {
			function e(t) {
				P(this, e), this.place = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `?(` + this.place + `)`;
				}
			}]), e;
		}(), F.Pos.PushCoord = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@+(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.EvalCoordThenPop = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@-(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.LoadStack = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@=(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.DoCoord = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@@(` + this.coord + `)`;
				}
			}]), e;
		}(), F.Pos.InitStack = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@i`;
				}
			}]), e;
		}(), F.Pos.EnterFrame = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@(`;
				}
			}]), e;
		}(), F.Pos.LeaveFrame = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@)`;
				}
			}]), e;
		}(), F.Pos.SavePos = function() {
			function e(t) {
				P(this, e), this.id = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `="` + this.id + `"`;
				}
			}]), e;
		}(), F.Pos.SaveMacro = function() {
			function e(t, n) {
				P(this, e), this.macro = t, this.id = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `=(` + this.macro + ` "` + this.id + `")`;
				}
			}]), e;
		}(), F.Pos.SaveBase = function() {
			function e(t) {
				P(this, e), this.id = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `=:"` + this.id + `"`;
				}
			}]), e;
		}(), F.Pos.SaveStack = function() {
			function e(t) {
				P(this, e), this.id = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `=@"` + this.id + `"`;
				}
			}]), e;
		}(), (F.Coord = function e() {
			P(this, e);
		}).Vector = function() {
			function e(t) {
				P(this, e), this.vector = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.vector.toString();
				}
			}]), e;
		}(), F.Coord.C = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `c`;
				}
			}]), e;
		}(), F.Coord.P = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `p`;
				}
			}]), e;
		}(), F.Coord.X = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `x`;
				}
			}]), e;
		}(), F.Coord.Y = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `y`;
				}
			}]), e;
		}(), F.Coord.Id = function() {
			function e(t) {
				P(this, e), this.id = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `"` + this.id + `"`;
				}
			}]), e;
		}(), F.Coord.Group = function() {
			function e(t) {
				P(this, e), this.posDecor = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `{` + this.posDecor + `}`;
				}
			}]), e;
		}(), F.Coord.StackPosition = function() {
			function e(t) {
				P(this, e), this.number = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `s{` + this.number + `}`;
				}
			}]), e;
		}(), F.Coord.DeltaRowColumn = function() {
			function e(t, n, r) {
				P(this, e), this.prefix = t, this.dr = n, this.dc = r;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `[` + (this.prefix === `` ? `` : `"` + this.prefix + `"`) + this.dr + `,` + this.dc + `]`;
				}
			}]), e;
		}(), F.Coord.Hops = function() {
			function e(t, n) {
				P(this, e), this.prefix = t, this.hops = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `[` + (this.prefix === `` ? `` : `"` + this.prefix + `"`) + this.hops.mkString(``) + `]`;
				}
			}]), e;
		}(), F.Coord.HopsWithPlace = function() {
			function e(t, n, r) {
				P(this, e), this.prefix = t, this.hops = n, this.place = r;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `[` + (this.prefix === `` ? `` : `"` + this.prefix + `"`) + this.hops.mkString(``) + this.place + `]`;
				}
			}]), e;
		}(), (F.Vector = function e() {
			P(this, e);
		}).InCurBase = function() {
			function e(t, n) {
				P(this, e), this.x = t, this.y = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `(` + this.x + `, ` + this.y + `)`;
				}
			}]), e;
		}(), F.Vector.Abs = function() {
			function e(t, n) {
				P(this, e), this.x = t, this.y = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `<` + this.x + `, ` + this.y + `>`;
				}
			}]), e;
		}(), F.Vector.Angle = function() {
			function e(t) {
				P(this, e), this.degree = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `a(` + this.degree + `)`;
				}
			}]), e;
		}(), F.Vector.Dir = function() {
			function e(t, n) {
				P(this, e), this.dir = t, this.dimen = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `/` + this.dir + ` ` + this.dimen + `/`;
				}
			}]), e;
		}(), F.Vector.Corner = function() {
			function e(t, n) {
				P(this, e), this.corner = t, this.factor = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.corner.toString() + `(` + this.factor + `)`;
				}
			}]), e;
		}(), (F.Corner = function e() {
			P(this, e);
		}).L = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `L`;
				}
			}]), e;
		}(), F.Corner.R = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `R`;
				}
			}]), e;
		}(), F.Corner.D = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `D`;
				}
			}]), e;
		}(), F.Corner.U = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `U`;
				}
			}]), e;
		}(), F.Corner.CL = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `CL`;
				}
			}]), e;
		}(), F.Corner.CR = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `CR`;
				}
			}]), e;
		}(), F.Corner.CD = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `CD`;
				}
			}]), e;
		}(), F.Corner.CU = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `CU`;
				}
			}]), e;
		}(), F.Corner.LD = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `LD`;
				}
			}]), e;
		}(), F.Corner.RD = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `RD`;
				}
			}]), e;
		}(), F.Corner.LU = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `LU`;
				}
			}]), e;
		}(), F.Corner.RU = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `RU`;
				}
			}]), e;
		}(), F.Corner.NearestEdgePoint = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `E`;
				}
			}]), e;
		}(), F.Corner.PropEdgePoint = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `P`;
				}
			}]), e;
		}(), F.Corner.Axis = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `A`;
				}
			}]), e;
		}(), (F.Place = function() {
			function e(t, n, r, i) {
				P(this, e), this.shaveP = t, this.shaveC = n, this.factor = r, this.slide = i;
			}
			return j(e, [{
				key: `compound`,
				value: function(e) {
					return new F.Place(this.shaveP + e.shaveP, this.shaveC + e.shaveC, e.factor === void 0 ? this.factor : e.factor, e.slide);
				}
			}, {
				key: `toString`,
				value: function() {
					for (var e = ``, t = 0; t < this.shaveP; t++) e += `<`;
					for (var n = 0; n < this.shaveC; n++) e += `>`;
					return this.factor !== void 0 && (e += `(` + this.factor + `)`), this.slide.dimen.foreach((function(t) {
						e += `/` + t + `/`;
					})), e;
				}
			}]), e;
		}()).Factor = function() {
			function e(t) {
				P(this, e), this.factor = t;
			}
			return j(e, [{
				key: `isIntercept`,
				get: function() {
					return !1;
				}
			}, {
				key: `toString`,
				value: function() {
					return this.factor.toString();
				}
			}]), e;
		}(), F.Place.Intercept = function() {
			function e(t) {
				P(this, e), this.pos = t;
			}
			return j(e, [{
				key: `isIntercept`,
				get: function() {
					return !0;
				}
			}, {
				key: `toString`,
				value: function() {
					return `!{` + this.pos + `}`;
				}
			}]), e;
		}(), F.Slide = function() {
			function e(t) {
				P(this, e), this.dimen = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.dimen.getOrElse(``);
				}
			}]), e;
		}(), F.Object = function() {
			function e(t, n) {
				P(this, e), this.modifiers = t, this.object = n;
			}
			return j(e, [
				{
					key: `dirVariant`,
					value: function() {
						return this.object.dirVariant();
					}
				},
				{
					key: `dirMain`,
					value: function() {
						return this.object.dirMain();
					}
				},
				{
					key: `isDir`,
					value: function() {
						return this.object.isDir();
					}
				},
				{
					key: `toString`,
					value: function() {
						return this.modifiers.mkString() + this.object.toString();
					}
				}
			]), e;
		}(), (F.ObjectBox = function() {
			function e() {
				P(this, e);
			}
			return j(e, [
				{
					key: `isEmpty`,
					get: function() {
						return !1;
					}
				},
				{
					key: `dirVariant`,
					value: function() {}
				},
				{
					key: `dirMain`,
					value: function() {}
				},
				{
					key: `isDir`,
					value: function() {
						return !1;
					}
				}
			]), e;
		}()).Text = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).math = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `{` + this.math.toString() + `}`;
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.Empty = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `isEmpty`,
				get: function() {
					return !0;
				}
			}, {
				key: `toString`,
				value: function() {
					return `{}`;
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.Xymatrix = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).xymatrix = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return this.xymatrix.toString();
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.Txt = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				var i;
				return P(this, n), (i = t.call(this)).width = e, i.textObject = r, i;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\txt` + this.width + `{` + this.textObject.toString() + `}`;
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.Txt.Width = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return n;
		}(F.ObjectBox), F.ObjectBox.Txt.Width.Vector = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).vector = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return this.vector.toString();
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.Txt.Width.Default = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return ``;
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.WrapUpObject = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).object = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\object` + this.object.toString();
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.CompositeObject = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).objects = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\composite{` + this.objects.mkString(` * `) + `}`;
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.Xybox = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).posDecor = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\xybox{` + this.posDecor.toString() + `}`;
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.Cir = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				var i;
				return P(this, n), (i = t.call(this)).radius = e, i.cir = r, i;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\cir` + this.radius + `{` + this.cir + `}`;
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.Cir.Radius = function e() {
			P(this, e);
		}, F.ObjectBox.Cir.Radius.Vector = function() {
			function e(t) {
				P(this, e), this.vector = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.vector.toString();
				}
			}]), e;
		}(), F.ObjectBox.Cir.Radius.Default = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return ``;
				}
			}]), e;
		}(), F.ObjectBox.Cir.Cir = function e() {
			P(this, e);
		}, F.ObjectBox.Cir.Cir.Segment = function() {
			function e(t, n, r) {
				P(this, e), this.startDiag = t, this.orient = n, this.endDiag = r;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.startDiag.toString() + this.orient + this.endDiag;
				}
			}]), e;
		}(), F.ObjectBox.Cir.Cir.Full = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return ``;
				}
			}]), e;
		}(), F.ObjectBox.Dir = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				var i;
				return P(this, n), (i = t.call(this)).variant = e, i.main = r, i;
			}
			return j(n, [
				{
					key: `dirVariant`,
					value: function() {
						return this.variant;
					}
				},
				{
					key: `dirMain`,
					value: function() {
						return this.main;
					}
				},
				{
					key: `isDir`,
					value: function() {
						return !0;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `\\dir` + this.variant + `{` + this.main + `}`;
					}
				}
			]), n;
		}(F.ObjectBox), F.ObjectBox.Curve = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i) {
				var a;
				return P(this, n), (a = t.call(this)).modifiers = e, a.objects = r, a.poslist = i, a;
			}
			return j(n, [
				{
					key: `dirVariant`,
					value: function() {
						return ``;
					}
				},
				{
					key: `dirMain`,
					value: function() {
						return `-`;
					}
				},
				{
					key: `isDir`,
					value: function() {
						return !1;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `\\curve` + this.modifiers.mkString(``) + `{` + this.objects.mkString(` `) + ` ` + this.poslist.mkString(`&`) + `}`;
					}
				}
			]), n;
		}(F.ObjectBox), F.ObjectBox.Curve.Modifier = function e() {
			P(this, e);
		}, F.ObjectBox.Curve.Modifier.p = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~p`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.P = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~P`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.l = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~l`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.L = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~L`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.c = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~c`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.C = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~C`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.pc = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~pc`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.pC = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~pC`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.Pc = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~Pc`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.PC = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~PC`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.lc = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~lc`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.lC = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~lC`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.Lc = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~Lc`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.LC = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~LC`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Modifier.cC = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~cC`;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Object = function e() {
			P(this, e);
		}, F.ObjectBox.Curve.Object.Drop = function() {
			function e(t) {
				P(this, e), this.object = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~*` + this.object;
				}
			}]), e;
		}(), F.ObjectBox.Curve.Object.Connect = function() {
			function e(t) {
				P(this, e), this.object = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~**` + this.object;
				}
			}]), e;
		}(), F.ObjectBox.Curve.PosList = function e() {
			P(this, e);
		}, F.ObjectBox.Curve.PosList.CurPos = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return ``;
				}
			}]), e;
		}(), F.ObjectBox.Curve.PosList.Pos = function() {
			function e(t) {
				P(this, e), this.pos = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.pos.toString();
				}
			}]), e;
		}(), F.ObjectBox.Curve.PosList.AddStack = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~@`;
				}
			}]), e;
		}(), (F.Modifier = function e() {
			P(this, e);
		}).Vector = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).vector = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `!` + this.vector;
				}
			}]), n;
		}(F.Modifier), F.Modifier.RestoreOriginalRefPoint = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `!`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.AddOp = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				var i;
				return P(this, n), (i = t.call(this)).op = e, i.size = r, i;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return this.op.toString() + ` ` + this.size;
				}
			}]), n;
		}(F.Modifier), F.Modifier.AddOp.Grow = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `+`;
				}
			}]), e;
		}(), F.Modifier.AddOp.Shrink = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `-`;
				}
			}]), e;
		}(), F.Modifier.AddOp.Set = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `=`;
				}
			}]), e;
		}(), F.Modifier.AddOp.GrowTo = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `+=`;
				}
			}]), e;
		}(), F.Modifier.AddOp.ShrinkTo = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `-=`;
				}
			}]), e;
		}(), F.Modifier.AddOp.VactorSize = function() {
			function e(t) {
				P(this, e), this.vector = t;
			}
			return j(e, [{
				key: `isDefault`,
				get: function() {
					return !1;
				}
			}, {
				key: `toString`,
				value: function() {
					return this.vector.toString();
				}
			}]), e;
		}(), F.Modifier.AddOp.DefaultSize = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `isDefault`,
				get: function() {
					return !0;
				}
			}, {
				key: `toString`,
				value: function() {
					return ``;
				}
			}]), e;
		}(), F.Modifier.Shape = function e() {
			P(this, e);
		}, F.Modifier.Shape.Point = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[.]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.Rect = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.Alphabets = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).alphabets = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[` + this.alphabets + `]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.DefineShape = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).shape = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[` + this.shape + `]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.Circle = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[o]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.L = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[l]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.R = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[r]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.U = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[u]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.D = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[d]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.C = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[c]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.ChangeColor = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).colorName = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[` + this.colorName + `]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.CompositeModifiers = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).modifiers = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return this.modifiers.mkString(``);
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.Frame = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				var i;
				return P(this, n), (i = t.call(this)).main = e, i.options = r, i;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `[F` + this.main + this.options.mkString(``) + `]`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Shape.Frame.Radius = function() {
			function e(t) {
				P(this, e), this.vector = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `:` + this.vector;
				}
			}]), e;
		}(), F.Modifier.Shape.Frame.Color = function() {
			function e(t) {
				P(this, e), this.colorName = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `:` + this.colorName;
				}
			}]), e;
		}(), F.Modifier.Invisible = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `i`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Hidden = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `h`;
				}
			}]), n;
		}(F.Modifier), F.Modifier.Direction = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).direction = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return this.direction.toString();
				}
			}]), n;
		}(F.Modifier), (F.Direction = function e() {
			P(this, e);
		}).Compound = function() {
			function e(t, n) {
				P(this, e), this.dir = t, this.rots = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.dir.toString() + this.rots.mkString();
				}
			}]), e;
		}(), F.Direction.Diag = function() {
			function e(t) {
				P(this, e), this.diag = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.diag.toString();
				}
			}]), e;
		}(), F.Direction.Vector = function() {
			function e(t) {
				P(this, e), this.vector = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `v` + this.vector.toString();
				}
			}]), e;
		}(), F.Direction.ConstructVector = function() {
			function e(t) {
				P(this, e), this.posDecor = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `q{` + this.posDecor.toString() + `}`;
				}
			}]), e;
		}(), F.Direction.RotVector = function() {
			function e(t) {
				P(this, e), this.vector = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `:` + this.vector.toString();
				}
			}]), e;
		}(), F.Direction.RotAntiCW = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `_`;
				}
			}]), e;
		}(), F.Direction.RotCW = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `^`;
				}
			}]), e;
		}(), (F.Diag = function e() {
			P(this, e);
		}).Default = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return ``;
				}
			}]), e;
		}(), F.Diag.Angle = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.symbol;
				}
			}]), e;
		}(), F.Diag.LD = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [
				{
					key: `symbol`,
					get: function() {
						return `ld`;
					}
				},
				{
					key: `ang`,
					get: function() {
						return -3 * Math.PI / 4;
					}
				},
				{
					key: `turn`,
					value: function(e) {
						return e === `^` ? new F.Diag.RD() : new F.Diag.LU();
					}
				}
			]), n;
		}(F.Diag.Angle), F.Diag.RD = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [
				{
					key: `symbol`,
					get: function() {
						return `rd`;
					}
				},
				{
					key: `ang`,
					get: function() {
						return -Math.PI / 4;
					}
				},
				{
					key: `turn`,
					value: function(e) {
						return e === `^` ? new F.Diag.RU() : new F.Diag.LD();
					}
				}
			]), n;
		}(F.Diag.Angle), F.Diag.LU = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [
				{
					key: `symbol`,
					get: function() {
						return `lu`;
					}
				},
				{
					key: `ang`,
					get: function() {
						return 3 * Math.PI / 4;
					}
				},
				{
					key: `turn`,
					value: function(e) {
						return e === `^` ? new F.Diag.LD() : new F.Diag.RU();
					}
				}
			]), n;
		}(F.Diag.Angle), F.Diag.RU = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [
				{
					key: `symbol`,
					get: function() {
						return `ru`;
					}
				},
				{
					key: `ang`,
					get: function() {
						return Math.PI / 4;
					}
				},
				{
					key: `turn`,
					value: function(e) {
						return e === `^` ? new F.Diag.LU() : new F.Diag.RD();
					}
				}
			]), n;
		}(F.Diag.Angle), F.Diag.L = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [
				{
					key: `symbol`,
					get: function() {
						return `l`;
					}
				},
				{
					key: `ang`,
					get: function() {
						return Math.PI;
					}
				},
				{
					key: `turn`,
					value: function(e) {
						return e === `^` ? new F.Diag.D() : new F.Diag.U();
					}
				}
			]), n;
		}(F.Diag.Angle), F.Diag.R = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [
				{
					key: `symbol`,
					get: function() {
						return `r`;
					}
				},
				{
					key: `ang`,
					get: function() {
						return 0;
					}
				},
				{
					key: `turn`,
					value: function(e) {
						return e === `^` ? new F.Diag.U() : new F.Diag.D();
					}
				}
			]), n;
		}(F.Diag.Angle), F.Diag.D = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [
				{
					key: `symbol`,
					get: function() {
						return `d`;
					}
				},
				{
					key: `ang`,
					get: function() {
						return -Math.PI / 2;
					}
				},
				{
					key: `turn`,
					value: function(e) {
						return e === `^` ? new F.Diag.R() : new F.Diag.L();
					}
				}
			]), n;
		}(F.Diag.Angle), F.Diag.U = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [
				{
					key: `symbol`,
					get: function() {
						return `u`;
					}
				},
				{
					key: `ang`,
					get: function() {
						return Math.PI / 2;
					}
				},
				{
					key: `turn`,
					value: function(e) {
						return e === `^` ? new F.Diag.L() : new F.Diag.R();
					}
				}
			]), n;
		}(F.Diag.Angle), F.ObjectBox.Frame = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				var i;
				return P(this, n), (i = t.call(this)).radius = e, i.main = r, i;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\frm` + this.radius + `{` + this.main + `}`;
				}
			}]), n;
		}(F.ObjectBox), F.ObjectBox.Frame.Radius = function e() {
			P(this, e);
		}, F.ObjectBox.Frame.Radius.Vector = function() {
			function e(t) {
				P(this, e), this.vector = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.vector.toString();
				}
			}]), e;
		}(), F.ObjectBox.Frame.Radius.Default = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return ``;
				}
			}]), e;
		}(), F.Decor = function() {
			function e(t) {
				P(this, e), this.commands = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.commands.mkString(` `);
				}
			}]), e;
		}(), (F.Command = function e() {
			P(this, e);
		}).Save = function() {
			function e(t) {
				P(this, e), this.pos = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\save ` + this.pos;
				}
			}]), e;
		}(), F.Command.Restore = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\restore`;
				}
			}]), e;
		}(), F.Command.Pos = function() {
			function e(t) {
				P(this, e), this.pos = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\POS ` + this.pos;
				}
			}]), e;
		}(), F.Command.AfterPos = function() {
			function e(t, n) {
				P(this, e), this.decor = t, this.pos = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\afterPOS{` + this.decor + `} ` + this.pos;
				}
			}]), e;
		}(), F.Command.Drop = function() {
			function e(t) {
				P(this, e), this.object = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\drop ` + this.object;
				}
			}]), e;
		}(), F.Command.Connect = function() {
			function e(t) {
				P(this, e), this.object = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\connect ` + this.object;
				}
			}]), e;
		}(), F.Command.Relax = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\relax`;
				}
			}]), e;
		}(), F.Command.Ignore = function() {
			function e(t, n) {
				P(this, e), this.pos = t, this.decor = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\ignore{` + this.pos + ` ` + this.decor + `}`;
				}
			}]), e;
		}(), F.Command.ShowAST = function() {
			function e(t, n) {
				P(this, e), this.pos = t, this.decor = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\xyshowAST{` + this.pos + ` ` + this.decor + `}`;
				}
			}]), e;
		}(), F.Command.Path = function() {
			function e(t) {
				P(this, e), this.path = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\PATH ` + this.path;
				}
			}]), e;
		}(), F.Command.AfterPath = function() {
			function e(t, n) {
				P(this, e), this.decor = t, this.path = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\afterPATH{` + this.decor + `} ` + this.path;
				}
			}]), e;
		}(), F.Command.Path.Path = function() {
			function e(t) {
				P(this, e), this.pathElements = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.pathElements.mkString(`[`, `, `, `]`);
				}
			}]), e;
		}(), F.Command.Path.SetBeforeAction = function() {
			function e(t) {
				P(this, e), this.posDecor = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~={` + this.posDecor + `}`;
				}
			}]), e;
		}(), F.Command.Path.SetAfterAction = function() {
			function e(t) {
				P(this, e), this.posDecor = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~/{` + this.posDecor + `}`;
				}
			}]), e;
		}(), F.Command.Path.AddLabelNextSegmentOnly = function() {
			function e(t) {
				P(this, e), this.labels = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~<{` + this.labels + `}`;
				}
			}]), e;
		}(), F.Command.Path.AddLabelLastSegmentOnly = function() {
			function e(t) {
				P(this, e), this.labels = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~>{` + this.labels + `}`;
				}
			}]), e;
		}(), F.Command.Path.AddLabelEverySegment = function() {
			function e(t) {
				P(this, e), this.labels = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~+{` + this.labels + `}`;
				}
			}]), e;
		}(), F.Command.Path.StraightSegment = function() {
			function e(t) {
				P(this, e), this.segment = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `'` + this.segment;
				}
			}]), e;
		}(), F.Command.Path.TurningSegment = function() {
			function e(t, n) {
				P(this, e), this.turn = t, this.segment = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return "`" + this.turn + ` ` + this.segment;
				}
			}]), e;
		}(), F.Command.Path.LastSegment = function() {
			function e(t) {
				P(this, e), this.segment = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.segment.toString();
				}
			}]), e;
		}(), F.Command.Path.Turn = function e() {
			P(this, e);
		}, F.Command.Path.Turn.Diag = function() {
			function e(t, n) {
				P(this, e), this.diag = t, this.radius = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.diag.toString() + ` ` + this.radius;
				}
			}]), e;
		}(), F.Command.Path.Turn.Cir = function() {
			function e(t, n) {
				P(this, e), this.cir = t, this.radius = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.cir.toString() + ` ` + this.radius;
				}
			}]), e;
		}(), F.Command.Path.TurnRadius = function e() {
			P(this, e);
		}, F.Command.Path.TurnRadius.Default = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return ``;
				}
			}]), e;
		}(), F.Command.Path.TurnRadius.Dimen = function() {
			function e(t) {
				P(this, e), this.dimen = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `/` + this.dimen;
				}
			}]), e;
		}(), F.Command.Path.Segment = function() {
			function e(t, n, r) {
				P(this, e), this.pos = t, this.slide = n, this.labels = r;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.pos.toString() + ` ` + this.slide + ` ` + this.labels;
				}
			}]), e;
		}(), F.Command.Path.Labels = function() {
			function e(t) {
				P(this, e), this.labels = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.labels.mkString(` `);
				}
			}]), e;
		}(), F.Command.Path.Label = function e(t, n, r) {
			P(this, e), this.anchor = t, this.it = n, this.aliasOption = r;
		}, F.Command.Path.Label.Above = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i) {
				return P(this, n), t.call(this, e, r, i);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `^(` + this.anchor + ` ` + this.it + ` ` + this.aliasOption + `)`;
				}
			}]), n;
		}(F.Command.Path.Label), F.Command.Path.Label.Below = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i) {
				return P(this, n), t.call(this, e, r, i);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `_(` + this.anchor + ` ` + this.it + ` ` + this.aliasOption + `)`;
				}
			}]), n;
		}(F.Command.Path.Label), F.Command.Path.Label.At = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i) {
				return P(this, n), t.call(this, e, r, i);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `|(` + this.anchor + ` ` + this.it + ` ` + this.aliasOption + `)`;
				}
			}]), n;
		}(F.Command.Path.Label), F.Command.Ar = function() {
			function e(t, n) {
				P(this, e), this.forms = t, this.path = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\ar ` + this.forms.mkString(` `) + ` ` + this.path;
				}
			}]), e;
		}(), F.Command.Ar.Form = function e() {
			P(this, e);
		}, F.Command.Ar.Form.BuildArrow = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i, a) {
				var o;
				return P(this, n), (o = t.call(this)).variant = e, o.tailTip = r, o.stemConn = i, o.headTip = a, o;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@` + this.variant + `{` + this.tailTip.toString() + `, ` + this.stemConn.toString() + `, ` + this.headTip.toString() + `}`;
				}
			}]), n;
		}(F.Command.Ar.Form), F.Command.Ar.Form.ChangeVariant = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).variant = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@` + this.variant;
				}
			}]), n;
		}(F.Command.Ar.Form), F.Command.Ar.Form.Tip = function e() {
			P(this, e);
		}, F.Command.Ar.Form.Tip.Tipchars = function() {
			function e(t) {
				P(this, e), this.tipchars = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.tipchars;
				}
			}]), e;
		}(), F.Command.Ar.Form.Tip.Object = function() {
			function e(t) {
				P(this, e), this.object = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `*` + this.object;
				}
			}]), e;
		}(), F.Command.Ar.Form.Tip.Dir = function() {
			function e(t) {
				P(this, e), this.dir = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.dir;
				}
			}]), e;
		}(), F.Command.Ar.Form.Conn = function e() {
			P(this, e);
		}, F.Command.Ar.Form.Conn.Connchars = function() {
			function e(t) {
				P(this, e), this.connchars = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.connchars;
				}
			}]), e;
		}(), F.Command.Ar.Form.Conn.Object = function() {
			function e(t) {
				P(this, e), this.object = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `*` + this.object;
				}
			}]), e;
		}(), F.Command.Ar.Form.Conn.Dir = function() {
			function e(t) {
				P(this, e), this.dir = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.dir;
				}
			}]), e;
		}(), F.Command.Ar.Form.ChangeStem = function() {
			function e(t) {
				P(this, e), this.connchar = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@` + this.connchar;
				}
			}]), e;
		}(), F.Command.Ar.Form.DashArrowStem = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@!`;
				}
			}]), e;
		}(), F.Command.Ar.Form.CurveArrow = function() {
			function e(t, n) {
				P(this, e), this.direction = t, this.dist = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@/` + this.direction + ` ` + this.dist + `/`;
				}
			}]), e;
		}(), F.Command.Ar.Form.CurveFitToDirection = function() {
			function e(t, n) {
				P(this, e), this.outDirection = t, this.inDirection = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@(` + this.outDirection + `,` + this.inDirection + `)`;
				}
			}]), e;
		}(), F.Command.Ar.Form.CurveWithControlPoints = function() {
			function e(t) {
				P(this, e), this.coord = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return "@`{" + this.coord + `}`;
				}
			}]), e;
		}(), F.Command.Ar.Form.AddShape = function() {
			function e(t) {
				P(this, e), this.shape = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@[` + this.shape + `]`;
				}
			}]), e;
		}(), F.Command.Ar.Form.AddModifiers = function() {
			function e(t) {
				P(this, e), this.modifiers = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@*{` + this.modifiers.mkString(` `) + `}`;
				}
			}]), e;
		}(), F.Command.Ar.Form.Slide = function() {
			function e(t) {
				P(this, e), this.slideDimen = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@<` + this.slideDimen + `>`;
				}
			}]), e;
		}(), F.Command.Ar.Form.LabelAt = function() {
			function e(t, n) {
				P(this, e), this.anchor = t, this.it = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `|` + this.anchor + ` ` + this.it;
				}
			}]), e;
		}(), F.Command.Ar.Form.LabelAbove = function() {
			function e(t, n) {
				P(this, e), this.anchor = t, this.it = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `^` + this.anchor + ` ` + this.it;
				}
			}]), e;
		}(), F.Command.Ar.Form.LabelBelow = function() {
			function e(t, n) {
				P(this, e), this.anchor = t, this.it = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `_` + this.anchor + ` ` + this.it;
				}
			}]), e;
		}(), F.Command.Ar.Form.ReverseAboveAndBelow = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@?`;
				}
			}]), e;
		}(), F.Command.Xymatrix = function() {
			function e(t, n) {
				P(this, e), this.setup = t, this.rows = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\xymatrix` + this.setup + `{
` + this.rows.mkString(``, `\\\\
`, ``) + `
}`;
				}
			}]), e;
		}(), F.Command.Xymatrix.Setup = function e() {
			P(this, e);
		}, F.Command.Xymatrix.Setup.Prefix = function() {
			function e(t) {
				P(this, e), this.prefix = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `"` + this.prefix + `"`;
				}
			}]), e;
		}(), F.Command.Xymatrix.Setup.ChangeSpacing = function e(t, n) {
			P(this, e), this.addop = t, this.dimen = n;
		}, F.Command.Xymatrix.Setup.ChangeSpacing.Row = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				return P(this, n), t.call(this, e, r);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@R` + this.addop + this.dimen;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.ChangeSpacing), F.Command.Xymatrix.Setup.ChangeSpacing.Column = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				return P(this, n), t.call(this, e, r);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@C` + this.addop + this.dimen;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.ChangeSpacing), F.Command.Xymatrix.Setup.ChangeSpacing.RowAndColumn = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				return P(this, n), t.call(this, e, r);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@` + this.addop + this.dimen;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.ChangeSpacing), F.Command.Xymatrix.Setup.PretendEntrySize = function e(t) {
			P(this, e), this.dimen = t;
		}, F.Command.Xymatrix.Setup.PretendEntrySize.Height = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				return P(this, n), t.call(this, e);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@!R=` + this.dimen;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.PretendEntrySize), F.Command.Xymatrix.Setup.PretendEntrySize.Width = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				return P(this, n), t.call(this, e);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@!C=` + this.dimen;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.PretendEntrySize), F.Command.Xymatrix.Setup.PretendEntrySize.HeightAndWidth = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				return P(this, n), t.call(this, e);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@!=` + this.dimen;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.PretendEntrySize), F.Command.Xymatrix.Setup.FixGrid = function e() {
			P(this, e);
		}, F.Command.Xymatrix.Setup.FixGrid.Row = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@!R`;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.FixGrid), F.Command.Xymatrix.Setup.FixGrid.Column = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@!C`;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.FixGrid), F.Command.Xymatrix.Setup.FixGrid.RowAndColumn = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@!`;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.FixGrid), F.Command.Xymatrix.Setup.AdjustEntrySize = function e(t, n) {
			P(this, e), this.addop = t, this.dimen = n;
		}, F.Command.Xymatrix.Setup.AdjustEntrySize.Margin = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				return P(this, n), t.call(this, e, r);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@M` + this.addop + this.dimen;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.AdjustEntrySize), F.Command.Xymatrix.Setup.AdjustEntrySize.Width = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				return P(this, n), t.call(this, e, r);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@W` + this.addop + this.dimen;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.AdjustEntrySize), F.Command.Xymatrix.Setup.AdjustEntrySize.Height = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				return P(this, n), t.call(this, e, r);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `@H` + this.addop + this.dimen;
				}
			}]), n;
		}(F.Command.Xymatrix.Setup.AdjustEntrySize), F.Command.Xymatrix.Setup.AdjustLabelSep = function() {
			function e(t, n) {
				P(this, e), this.addop = t, this.dimen = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@L` + this.addop + this.dimen;
				}
			}]), e;
		}(), F.Command.Xymatrix.Setup.SetOrientation = function() {
			function e(t) {
				P(this, e), this.direction = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@` + this.direction;
				}
			}]), e;
		}(), F.Command.Xymatrix.Setup.AddModifier = function() {
			function e(t) {
				P(this, e), this.modifier = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `@*` + this.modifier;
				}
			}]), e;
		}(), F.Command.Xymatrix.Row = function() {
			function e(t) {
				P(this, e), this.entries = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.entries.mkString(` & `);
				}
			}]), e;
		}(), F.Command.Xymatrix.Entry = function e() {
			P(this, e);
		}, F.Command.Xymatrix.Entry.SimpleEntry = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i) {
				var a;
				return P(this, n), (a = t.call(this)).modifiers = e, a.objectbox = r, a.decor = i, a;
			}
			return j(n, [{
				key: `isEmpty`,
				get: function() {
					return !1;
				}
			}, {
				key: `toString`,
				value: function() {
					return this.modifiers.mkString(`**{`, ``, `}`) + ` ` + this.objectbox + ` ` + this.decor;
				}
			}]), n;
		}(F.Command.Xymatrix.Entry), F.Command.Xymatrix.Entry.ObjectEntry = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i) {
				var a;
				return P(this, n), (a = t.call(this)).object = e, a.pos = r, a.decor = i, a;
			}
			return j(n, [{
				key: `isEmpty`,
				get: function() {
					return !1;
				}
			}, {
				key: `toString`,
				value: function() {
					return `*` + this.object + ` ` + this.pos + ` ` + this.decor;
				}
			}]), n;
		}(F.Command.Xymatrix.Entry), F.Command.Xymatrix.Entry.EmptyEntry = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).decor = e, r;
			}
			return j(n, [{
				key: `isEmpty`,
				get: function() {
					return !0;
				}
			}, {
				key: `toString`,
				value: function() {
					return `` + this.decor;
				}
			}]), n;
		}(F.Command.Xymatrix.Entry), F.Command.Twocell = function() {
			function e(t, n, r) {
				P(this, e), this.twocell = t, this.switches = n, this.arrow = r;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.twocell.toString() + this.switches.mkString(``) + this.arrow;
				}
			}]), e;
		}(), F.Command.Twocell.Hops2cell = function e(t, n) {
			P(this, e), this.hops = t, this.maybeDisplace = n;
		}, F.Command.Twocell.Twocell = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				return P(this, n), t.call(this, e, r);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\xtwocell[` + this.hops + `]` + this.maybeDisplace.getOrElse(`{}`);
				}
			}]), n;
		}(F.Command.Twocell.Hops2cell), F.Command.Twocell.UpperTwocell = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				return P(this, n), t.call(this, e, r);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\xuppertwocell[` + this.hops + `]` + this.maybeDisplace.getOrElse(`{}`);
				}
			}]), n;
		}(F.Command.Twocell.Hops2cell), F.Command.Twocell.LowerTwocell = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				return P(this, n), t.call(this, e, r);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\xlowertwocell[` + this.hops + `]` + this.maybeDisplace.getOrElse(`{}`);
				}
			}]), n;
		}(F.Command.Twocell.Hops2cell), F.Command.Twocell.CompositeMap = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				return P(this, n), t.call(this, e, r);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\xcompositemap[` + this.hops + `]` + this.maybeDisplace.getOrElse(`{}`);
				}
			}]), n;
		}(F.Command.Twocell.Hops2cell), F.Command.Twocell.Switch = function e() {
			P(this, e);
		}, F.Command.Twocell.Switch.UpperLabel = function() {
			function e(t) {
				P(this, e), this.label = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `^` + this.label;
				}
			}]), e;
		}(), F.Command.Twocell.Switch.LowerLabel = function() {
			function e(t) {
				P(this, e), this.label = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `_` + this.label;
				}
			}]), e;
		}(), F.Command.Twocell.Switch.SetCurvature = function() {
			function e(t) {
				P(this, e), this.nudge = t;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.nudge.toString();
				}
			}]), e;
		}(), F.Command.Twocell.Switch.DoNotSetCurvedArrows = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\omit`;
				}
			}]), e;
		}(), F.Command.Twocell.Switch.PlaceModMapObject = function() {
			function e() {
				P(this, e);
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~!`;
				}
			}]), e;
		}(), F.Command.Twocell.Switch.ChangeHeadTailObject = function() {
			function e(t, n) {
				P(this, e), this.what = t, this.object = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~` + this.what + `{` + this.object + `}`;
				}
			}]), e;
		}(), F.Command.Twocell.Switch.ChangeCurveObject = function() {
			function e(t, n, r) {
				P(this, e), this.what = t, this.spacer = n, this.maybeObject = r;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `~` + this.what + `{` + this.spacer + (this.maybeObject.isDefined ? `~**` + this.maybeObject.get : ``) + `}`;
				}
			}]), e;
		}(), F.Command.Twocell.Label = function() {
			function e(t, n) {
				P(this, e), this.maybeNudge = t, this.labelObject = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return this.maybeNudge.toString() + this.labelObject;
				}
			}]), e;
		}(), F.Command.Twocell.Nudge = function e() {
			P(this, e);
		}, F.Command.Twocell.Nudge.Number = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).number = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `<` + this.number + `>`;
				}
			}]), n;
		}(F.Command.Twocell.Nudge), F.Command.Twocell.Nudge.Omit = function(e) {
			M(n, e);
			var t = N(n);
			function n() {
				return P(this, n), t.call(this);
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `<\\omit>`;
				}
			}]), n;
		}(F.Command.Twocell.Nudge), F.Command.Twocell.Arrow = function e() {
			P(this, e);
		}, F.Command.Twocell.Arrow.WithOrientation = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				var i;
				return P(this, n), (i = t.call(this)).tok = e, i.labelObject = r, i;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `{[` + this.tok + `] ` + this.labelObject + `}`;
				}
			}]), n;
		}(F.Command.Twocell.Arrow), F.Command.Twocell.Arrow.WithPosition = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r) {
				var i;
				return P(this, n), (i = t.call(this)).nudge = e, i.labelObject = r, i;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `{[` + this.nudge + `] ` + this.labelObject + `}`;
				}
			}]), n;
		}(F.Command.Twocell.Arrow), F.Command.Newdir = function() {
			function e(t, n) {
				P(this, e), this.dirMain = t, this.compositeObject = n;
			}
			return j(e, [{
				key: `toString`,
				value: function() {
					return `\\newdir{` + this.dirMain + `}{` + this.compositeObject + `}`;
				}
			}]), e;
		}(), F.Pos.Xyimport = function e() {
			P(this, e);
		}, F.Pos.Xyimport.TeXCommand = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i, a, o) {
				var s;
				return P(this, n), (s = t.call(this)).width = e, s.height = r, s.xOffset = i, s.yOffset = a, s.graphics = o, s;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\xyimport(` + this.width + `, ` + this.height + `)(` + this.xOffset + `, ` + this.yOffset + `){` + this.graphics + `}`;
				}
			}]), n;
		}(F.Pos.Xyimport), F.Pos.Xyimport.Graphics = function(e) {
			M(n, e);
			var t = N(n);
			function n(e, r, i, a, o) {
				var s;
				return P(this, n), (s = t.call(this)).width = e, s.height = r, s.xOffset = i, s.yOffset = a, s.graphics = o, s;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `\\xyimport(` + this.width + `, ` + this.height + `)(` + this.xOffset + `, ` + this.yOffset + `){` + this.graphics + `}`;
				}
			}]), n;
		}(F.Pos.Xyimport), F.Command.Includegraphics = function() {
			function e(t, n, r) {
				P(this, e), this.isClipped = t, this.attributeList = n, this.filepath = r;
			}
			return j(e, [{
				key: `isIncludegraphics`,
				get: function() {
					return !0;
				}
			}, {
				key: `toString`,
				value: function() {
					return `\\includegraphics` + (this.isClipped ? `*` : ``) + this.attributeList.mkString(`[`, `,`, `]`) + `{` + this.filepath + `}`;
				}
			}]), e;
		}(), F.Command.Includegraphics.Attr = function e() {
			P(this, e);
		}, F.Command.Includegraphics.Attr.Width = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).dimen = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `width=` + this.dimen;
				}
			}]), n;
		}(F.Command.Includegraphics.Attr), F.Command.Includegraphics.Attr.Height = function(e) {
			M(n, e);
			var t = N(n);
			function n(e) {
				var r;
				return P(this, n), (r = t.call(this)).dimen = e, r;
			}
			return j(n, [{
				key: `toString`,
				value: function() {
					return `height=` + this.dimen;
				}
			}]), n;
		}(F.Command.Includegraphics.Attr);
		var I = k.fun, Ue = k.elem, We = function(e) {
			return I(k.elem(e));
		}, L = k.literal, Ge = k.regex, Ke = k.regexLiteral, R = function(e) {
			return I(k.literal(e));
		}, qe = k.seq, z = k.or, Je = function(e) {
			return k.lazyParser(e)().rep();
		}, Ye = function(e) {
			return k.lazyParser(e)().rep1();
		}, Xe = function(e) {
			return k.lazyParser(e)().opt();
		}, Ze = k.success, B = function(e) {
			return function() {
				var t = e.memo;
				return t === void 0 && (t = e.memo = e()), t;
			};
		}, V = new k(), Qe = {
			xy: B((function() {
				return V.posDecor().to((function(e) {
					return e;
				}));
			})),
			xybox: B((function() {
				return L(`{`).andr(V.posDecor).andl(R(`}`)).to((function(e) {
					return e;
				}));
			})),
			xymatrixbox: B((function() {
				return V.xymatrix().to((function(e) {
					return new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty), new F.Decor(O.empty.append(e)));
				}));
			})),
			posDecor: B((function() {
				return qe(V.pos, V.decor).to((function(e) {
					return new F.PosDecor(e.head, e.tail);
				}));
			})),
			pos: B((function() {
				return qe(V.coord, Je(V.pos2)).to((function(e) {
					return new F.Pos.Coord(e.head, e.tail);
				}));
			})),
			nonemptyPos: B((function() {
				return z(qe(V.nonemptyCoord, Je(V.pos2)), qe(V.coord, Ye(V.pos2))).to((function(e) {
					return new F.Pos.Coord(e.head, e.tail);
				}));
			})),
			pos2: B((function() {
				return z(L(`+`).andr(V.coord).to((function(e) {
					return new F.Pos.Plus(e);
				})), L(`-`).andr(V.coord).to((function(e) {
					return new F.Pos.Minus(e);
				})), L(`!`).andr(V.coord).to((function(e) {
					return new F.Pos.Skew(e);
				})), L(`.`).andr(V.coord).to((function(e) {
					return new F.Pos.Cover(e);
				})), L(`,`).andr(V.coord).to((function(e) {
					return new F.Pos.Then(e);
				})), L(`;`).andr(V.coord).to((function(e) {
					return new F.Pos.SwapPAndC(e);
				})), L(`::`).andr(V.coord).to((function(e) {
					return new F.Pos.SetYBase(e);
				})), L(`:`).andr(V.coord).to((function(e) {
					return new F.Pos.SetBase(e);
				})), L(`**`).andr(V.object).to((function(e) {
					return new F.Pos.ConnectObject(e);
				})), L(`*`).andr(V.object).to((function(e) {
					return new F.Pos.DropObject(e);
				})), L(`?`).andr(V.place).to((function(e) {
					return new F.Pos.Place(e);
				})), L(`@+`).andr(V.coord).to((function(e) {
					return new F.Pos.PushCoord(e);
				})), L(`@-`).andr(V.coord).to((function(e) {
					return new F.Pos.EvalCoordThenPop(e);
				})), L(`@=`).andr(V.coord).to((function(e) {
					return new F.Pos.LoadStack(e);
				})), L(`@@`).andr(V.coord).to((function(e) {
					return new F.Pos.DoCoord(e);
				})), L(`@i`).to((function() {
					return new F.Pos.InitStack();
				})), L(`@(`).to((function() {
					return new F.Pos.EnterFrame();
				})), L(`@)`).to((function() {
					return new F.Pos.LeaveFrame();
				})), L(`=:`).andr(R(`"`)).andr(V.id).andl(We(`"`)).to((function(e) {
					return new F.Pos.SaveBase(e);
				})), L(`=@`).andr(R(`"`)).andr(V.id).andl(We(`"`)).to((function(e) {
					return new F.Pos.SaveStack(e);
				})), L(`=`).andr(R(`"`)).andr(V.id).andl(We(`"`)).to((function(e) {
					return new F.Pos.SavePos(e);
				})), L(`=`).andr(V.nonemptyCoord).andl(R(`"`)).and(V.id).andl(We(`"`)).to((function(e) {
					return new F.Pos.SaveMacro(e.head, e.tail);
				})), V.xyimport);
			})),
			coord: B((function() {
				return z(V.nonemptyCoord, Ze(`empty`).to((function() {
					return new F.Coord.C();
				})));
			})),
			nonemptyCoord: B((function() {
				return z(L(`c`).to((function() {
					return new F.Coord.C();
				})), L(`p`).to((function() {
					return new F.Coord.P();
				})), L(`x`).to((function() {
					return new F.Coord.X();
				})), L(`y`).to((function() {
					return new F.Coord.Y();
				})), V.vector().to((function(e) {
					return new F.Coord.Vector(e);
				})), L(`"`).andr(V.id).andl(We(`"`)).to((function(e) {
					return new F.Coord.Id(e);
				})), L(`{`).andr(V.posDecor).andl(R(`}`)).to((function(e) {
					return new F.Coord.Group(e);
				})), L(`s`).andr(I(Ke(/^\d/))).to((function(e) {
					return new F.Coord.StackPosition(parseInt(e));
				})), L(`s`).andr(R(`{`)).and(V.nonnegativeNumber).andl(R(`}`)).to((function(e) {
					return new F.Coord.StackPosition(e);
				})), L(`[`).andr(I(Xe(L(`"`).andr(V.id).andl(We(`"`))).to((function(e) {
					return e.getOrElse(``);
				})))).and(V.number).andl(R(`,`)).and(V.number).andl(R(`]`)).to((function(e) {
					return new F.Coord.DeltaRowColumn(e.head.head, e.head.tail, e.tail);
				})), L(`[`).andr(I(Xe(L(`"`).andr(V.id).andl(We(`"`))).to((function(e) {
					return e.getOrElse(``);
				})))).and(I(Je(Ge(/^[lrud]/)))).andl(R(`]`)).to((function(e) {
					return new F.Coord.Hops(e.head, e.tail);
				})), L(`[`).andr(I(Xe(L(`"`).andr(V.id).andl(We(`"`))).to((function(e) {
					return e.getOrElse(``);
				})))).and(I(Ye(Ge(/^[lrud]/)))).and(V.place).andl(R(`]`)).to((function(e) {
					return new F.Coord.DeltaRowColumn(e.head.head, e.head.tail, new F.Pos.Place(e.tail));
				})));
			})),
			vector: B((function() {
				return z(L(`(`).andr(V.factor).andl(R(`,`)).and(V.factor).andl(R(`)`)).to((function(e) {
					return new F.Vector.InCurBase(e.head, e.tail);
				})), L(`<`).andr(V.dimen).andl(R(`,`)).and(V.dimen).andl(R(`>`)).to((function(e) {
					return new F.Vector.Abs(e.head, e.tail);
				})), L(`<`).andr(V.dimen).andl(R(`>`)).to((function(e) {
					return new F.Vector.Abs(e, e);
				})), L(`a`).andr(R(`(`)).andr(V.number).andl(R(`)`)).to((function(e) {
					return new F.Vector.Angle(e);
				})), L(`/`).andr(V.direction).and(V.looseDimen).andl(R(`/`)).to((function(e) {
					return new F.Vector.Dir(e.head, e.tail);
				})), L(`0`).to((function(e) {
					return new F.Vector.Abs(`0mm`, `0mm`);
				})), (function() {
					return V.corner().and(I(k.opt(I(L(`(`).andr(V.factor).andl(R(`)`)))).to((function(e) {
						return e.getOrElse(1);
					})))).to((function(e) {
						return new F.Vector.Corner(e.head, e.tail);
					}));
				}));
			})),
			corner: B((function() {
				return z(Ke(/^(CL|LC)/).to((function() {
					return new F.Corner.CL();
				})), Ke(/^(CR|RC)/).to((function() {
					return new F.Corner.CR();
				})), Ke(/^(CD|DC)/).to((function() {
					return new F.Corner.CD();
				})), Ke(/^(CU|UC)/).to((function() {
					return new F.Corner.CU();
				})), Ke(/^(LD|DL)/).to((function() {
					return new F.Corner.LD();
				})), Ke(/^(RD|DR)/).to((function() {
					return new F.Corner.RD();
				})), Ke(/^(LU|UL)/).to((function() {
					return new F.Corner.LU();
				})), Ke(/^(RU|UR)/).to((function() {
					return new F.Corner.RU();
				})), L(`L`).to((function() {
					return new F.Corner.L();
				})), L(`R`).to((function() {
					return new F.Corner.R();
				})), L(`D`).to((function() {
					return new F.Corner.D();
				})), L(`U`).to((function() {
					return new F.Corner.U();
				})), L(`E`).to((function() {
					return new F.Corner.NearestEdgePoint();
				})), L(`P`).to((function() {
					return new F.Corner.PropEdgePoint();
				})), L(`A`).to((function() {
					return new F.Corner.Axis();
				})));
			})),
			place: B((function() {
				return z(L(`<`).andr(V.place).to((function(e) {
					return new F.Place(1, 0, void 0, void 0).compound(e);
				})), L(`>`).andr(V.place).to((function(e) {
					return new F.Place(0, 1, void 0, void 0).compound(e);
				})), L(`(`).andr(V.factor).andl(R(`)`)).and(V.place).to((function(e) {
					return new F.Place(0, 0, new F.Place.Factor(e.head), void 0).compound(e.tail);
				})), L(`!`).andr(R(`{`)).andr(V.pos).andl(R(`}`)).and(V.slide).to((function(e) {
					return new F.Place(0, 0, new F.Place.Intercept(e.head), e.tail);
				})), (function() {
					return V.slide().to((function(e) {
						return new F.Place(0, 0, void 0, e);
					}));
				}));
			})),
			slide: B((function() {
				return z(L(`/`).andr(V.dimen).andl(R(`/`)).to((function(e) {
					return new F.Slide(new y.Some(e));
				})), Ze(`no slide`).to((function() {
					return new F.Slide(y.empty);
				})));
			})),
			factor: B(I(Ke(/^[+\-]?(\d+(\.\d*)?|\d*\.\d+)/).to((function(e) {
				return parseFloat(e);
			})))),
			number: B(I(Ke(/^[+\-]?\d+/).to((function(e) {
				return parseInt(e);
			})))),
			nonnegativeNumber: B(I(Ke(/^\d+/).to((function(e) {
				return parseInt(e);
			})))),
			unit: B(I(Ke(/^(em|ex|px|pt|pc|in|cm|mm|mu)/).to((function(e) {
				return e;
			})))),
			dimen: B((function() {
				return V.factor().and(V.unit).to((function(e) {
					return e.head.toString() + e.tail;
				}));
			})),
			looseDimen: B((function() {
				return V.looseFactor().and(V.unit).to((function(e) {
					return e.head.toString() + e.tail;
				}));
			})),
			looseFactor: B(I(z(Ke(/^(\d \d*(\.\d*))/).to((function(e) {
				return parseFloat(e.replace(/ /, ``));
			})), Ke(/^[+\-]?(\d+(\.\d*)?|\d*\.\d+)/).to((function(e) {
				return parseFloat(e);
			}))))),
			id: B(I(Ge(/^[^"]+/))),
			object: B((function() {
				return z(Je(V.modifier).and(V.objectbox).to((function(e) {
					return new F.Object(e.head, e.tail);
				})));
			})),
			objectbox: B((function() {
				return z(V.mathText, L(`@`).andr(V.dir), L(`\\dir`).andr(V.dir), L(`\\cir`).andr(V.cirRadius).andl(R(`{`)).and(V.cir).andl(R(`}`)).to((function(e) {
					return new F.ObjectBox.Cir(e.head, e.tail);
				})), L(`\\frm`).andr(V.frameRadius).andl(R(`{`)).and(V.frameMain).andl(R(`}`)).to((function(e) {
					return new F.ObjectBox.Frame(e.head, e.tail);
				})), L(`\\object`).andr(V.object).to((function(e) {
					return new F.ObjectBox.WrapUpObject(e);
				})), L(`\\composite`).and(R(`{`)).andr(V.compositeObject).andl(R(`}`)).to((function(e) {
					return new F.ObjectBox.CompositeObject(e);
				})), L(`\\xybox`).and(R(`{`)).andr(V.posDecor).andl(R(`}`)).to((function(e) {
					return new F.ObjectBox.Xybox(e);
				})), L(`\\xymatrix`).andr(V.xymatrix).to((function(e) {
					return new F.ObjectBox.Xymatrix(e);
				})), V.txt, V.curve, Ge(/^(\\[a-zA-Z@][a-zA-Z0-9@]+)/).andl(R(`{`)).and(V.text).andl(R(`}`)).and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail;
					return V.toMath(t.head + `{` + t.tail + `}`, n);
				})));
			})),
			compositeObject: B((function() {
				return V.object().and(I(Je(L(`*`).andr(V.object)))).to((function(e) {
					return e.tail.prepend(e.head);
				}));
			})),
			mathText: B((function() {
				return L(`{`).andr(V.text).andl(We(`}`)).and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail;
					return V.toMath(`\\hbox{$\\objectstyle{` + t + `}$}`, n);
				}));
			})),
			toMath: function(e, t) {
				var n = t(e);
				return new F.ObjectBox.Text(n);
			},
			textNodeCreator: B((function() {
				return new k.Parser((function(e) {
					return new k.Success(e.context.createTextNode, e);
				}));
			})),
			text: B((function() {
				return Ge(/^[^{}\\%]*/).and((function() {
					return z(Ge(/^(\\\{|\\\}|\\%|\\)/).to((function(e) {
						return e;
					})), Ue(`{`).andr(V.text).andl(We(`}`)).to((function(e) {
						return `{` + e + `}`;
					})), Ge(/^%[^\r\n]*(\r\n|\r|\n)?/).to((function(e) {
						return ` `;
					}))).and(I(Ge(/^[^{}\\%]*/))).rep().to((function(e) {
						var t = ``;
						return e.foreach((function(e) {
							t += e.head + e.tail;
						})), t;
					}));
				})).to((function(e) {
					return e.head + e.tail;
				}));
			})),
			txt: B((function() {
				return L(`\\txt`).andr(V.txtWidth).and(I(Ge(/^(\\[a-zA-Z@][a-zA-Z0-9@]+)?/))).andl(R(`{`)).and(V.text).andl(R(`}`)).and(V.textNodeCreator).to((function(e) {
					var t, n = e.head, r = e.tail, i = n.head.head, a = n.head.tail, o = n.tail, s = o.split(`\\\\`);
					if (s.length <= 1) t = a + `{\\hbox{` + o + `}}`;
					else {
						t = `\\hbox{$\\begin{array}{c}
`;
						for (var c = 0; c < s.length; c++) t += a + `{\\hbox{` + s[c].replace(/(^[\r\n\s]+)|([\r\n\s]+$)/g, ``) + `}}`, c != s.length - 1 && (t += `\\\\
`);
						t += `\\end{array}$}`;
					}
					return new F.ObjectBox.Txt(i, V.toMath(t, r));
				}));
			})),
			txtWidth: B((function() {
				return z(L(`<`).andr(V.dimen).andl(R(`>`)).to((function(e) {
					return new F.Vector.Abs(e, e);
				})).to((function(e) {
					return new F.ObjectBox.Txt.Width.Vector(e);
				})), Ze(`default`).to((function() {
					return new F.ObjectBox.Txt.Width.Default();
				})));
			})),
			dir: B((function() {
				return Ke(/^[\^_0123]/).opt().andl(R(`{`)).and(V.dirMain).andl(R(`}`)).to((function(e) {
					return new F.ObjectBox.Dir(e.head.getOrElse(``), e.tail);
				}));
			})),
			dirMain: B((function() {
				return Ge(/^(-|\.|~|>|<|\(|\)|`|'|\||\*|\+|x|\/|o|=|:|[a-zA-Z@ ])+/).opt().to((function(e) {
					return e.getOrElse(``);
				}));
			})),
			cirRadius: B((function() {
				return z(V.vector().to((function(e) {
					return new F.ObjectBox.Cir.Radius.Vector(e);
				})), Ze(`default`).to((function() {
					return new F.ObjectBox.Cir.Radius.Default();
				})));
			})),
			frameRadius: B((function() {
				return z(V.frameRadiusVector().to((function(e) {
					return new F.ObjectBox.Frame.Radius.Vector(e);
				})), Ze(`default`).to((function() {
					return new F.ObjectBox.Frame.Radius.Default();
				})));
			})),
			frameRadiusVector: B((function() {
				return z(L(`<`).andr(V.dimen).andl(R(`,`)).and(V.dimen).andl(R(`>`)).to((function(e) {
					return new F.Vector.Abs(e.head, e.tail);
				})), L(`<`).andr(V.dimen).andl(R(`>`)).to((function(e) {
					return new F.Vector.Abs(e, e);
				})));
			})),
			frameMain: B((function() {
				return Ge(/^(((_|\^)?(\\\{|\\\}|\(|\)))|[\-=oe,\.\*]*)/);
			})),
			cir: B((function() {
				return z(V.nonemptyCir, Ze(`full`).to((function() {
					return new F.ObjectBox.Cir.Cir.Full();
				})));
			})),
			nonemptyCir: B((function() {
				return V.diag().and(I(Ke(/^[_\^]/))).and(V.diag).to((function(e) {
					return new F.ObjectBox.Cir.Cir.Segment(e.head.head, e.head.tail, e.tail);
				}));
			})),
			curve: B((function() {
				return L(`\\crv`).andr(V.curveModifier).andl(R(`{`)).and(V.curveObject).and(V.curvePoslist).andl(R(`}`)).to((function(e) {
					return new F.ObjectBox.Curve(e.head.head, e.head.tail, e.tail);
				}));
			})),
			curveModifier: B((function() {
				return Je(I(L(`~`).andr(V.curveOption)));
			})),
			curveOption: B((function() {
				return z(L(`p`).to((function() {
					return new F.ObjectBox.Curve.Modifier.p();
				})), L(`P`).to((function() {
					return new F.ObjectBox.Curve.Modifier.P();
				})), L(`l`).to((function() {
					return new F.ObjectBox.Curve.Modifier.l();
				})), L(`L`).to((function() {
					return new F.ObjectBox.Curve.Modifier.L();
				})), L(`c`).to((function() {
					return new F.ObjectBox.Curve.Modifier.c();
				})), L(`C`).to((function() {
					return new F.ObjectBox.Curve.Modifier.C();
				})), L(`pc`).to((function() {
					return new F.ObjectBox.Curve.Modifier.pc();
				})), L(`pC`).to((function() {
					return new F.ObjectBox.Curve.Modifier.pC();
				})), L(`Pc`).to((function() {
					return new F.ObjectBox.Curve.Modifier.Pc();
				})), L(`PC`).to((function() {
					return new F.ObjectBox.Curve.Modifier.PC();
				})), L(`lc`).to((function() {
					return new F.ObjectBox.Curve.Modifier.lc();
				})), L(`lC`).to((function() {
					return new F.ObjectBox.Curve.Modifier.lC();
				})), L(`Lc`).to((function() {
					return new F.ObjectBox.Curve.Modifier.Lc();
				})), L(`LC`).to((function() {
					return new F.ObjectBox.Curve.Modifier.LC();
				})), L(`cC`).to((function() {
					return new F.ObjectBox.Curve.Modifier.cC();
				})));
			})),
			curveObject: B((function() {
				return Je(z(L(`~*`).andr(V.object).to((function(e) {
					return new F.ObjectBox.Curve.Object.Drop(e);
				})), L(`~**`).andr(V.object).to((function(e) {
					return new F.ObjectBox.Curve.Object.Connect(e);
				}))));
			})),
			curvePoslist: B((function() {
				return z(L(`&`).andr(V.curvePoslist2).to((function(e) {
					return e.prepend(new F.ObjectBox.Curve.PosList.CurPos());
				})), L(`~@`).andr(R(`&`)).andr(V.curvePoslist2).to((function(e) {
					return e.prepend(new F.ObjectBox.Curve.PosList.AddStack());
				})), L(`~@`).to((function() {
					return O.empty.prepend(new F.ObjectBox.Curve.PosList.AddStack());
				})), V.pos().andl(R(`&`)).and(V.curvePoslist2).to((function(e) {
					return e.tail.prepend(new F.ObjectBox.Curve.PosList.Pos(e.head));
				})), V.nonemptyPos().to((function(e) {
					return O.empty.prepend(new F.ObjectBox.Curve.PosList.Pos(e));
				})), Ze(`empty`).to((function() {
					return O.empty;
				})));
			})),
			curvePoslist2: B((function() {
				return z(L(`&`).andr(V.curvePoslist2).to((function(e) {
					return e.prepend(new F.ObjectBox.Curve.PosList.CurPos());
				})), L(`~@`).andr(R(`&`)).andr(V.curvePoslist2).to((function(e) {
					return e.prepend(new F.ObjectBox.Curve.PosList.AddStack());
				})), L(`~@`).to((function() {
					return O.empty.prepend(new F.ObjectBox.Curve.PosList.AddStack());
				})), V.nonemptyPos().andl(R(`&`)).and(V.curvePoslist2).to((function(e) {
					return e.tail.prepend(new F.ObjectBox.Curve.PosList.Pos(e.head));
				})), V.nonemptyPos().to((function(e) {
					return O.empty.prepend(new F.ObjectBox.Curve.PosList.Pos(e));
				})), Ze(`empty`).to((function() {
					return O.empty.prepend(new F.ObjectBox.Curve.PosList.CurPos());
				})));
			})),
			modifier: B((function() {
				return z(L(`!`).andr(V.vector).to((function(e) {
					return new F.Modifier.Vector(e);
				})), L(`!`).to((function(e) {
					return new F.Modifier.RestoreOriginalRefPoint();
				})), L(`[`).andr(V.shape).andl(R(`]`)).to((function(e) {
					return e;
				})), L(`i`).to((function(e) {
					return new F.Modifier.Invisible();
				})), L(`h`).to((function(e) {
					return new F.Modifier.Hidden();
				})), V.addOp().and(V.size).to((function(e) {
					return new F.Modifier.AddOp(e.head, e.tail);
				})), V.nonemptyDirection().to((function(e) {
					return new F.Modifier.Direction(e);
				})));
			})),
			addOp: B((function() {
				return z(L(`+=`).to((function() {
					return new F.Modifier.AddOp.GrowTo();
				})), L(`-=`).to((function() {
					return new F.Modifier.AddOp.ShrinkTo();
				})), L(`+`).to((function() {
					return new F.Modifier.AddOp.Grow();
				})), L(`-`).to((function() {
					return new F.Modifier.AddOp.Shrink();
				})), L(`=`).to((function() {
					return new F.Modifier.AddOp.Set();
				})));
			})),
			size: B((function() {
				return z((function() {
					return V.vector().to((function(e) {
						return new F.Modifier.AddOp.VactorSize(e);
					}));
				}), Ze(`default size`).to((function() {
					return new F.Modifier.AddOp.DefaultSize();
				})));
			})),
			shape: B((function() {
				return z(L(`.`).to((function() {
					return new F.Modifier.Shape.Point();
				})), V.frameShape, V.alphabets().to((function(e) {
					return new F.Modifier.Shape.Alphabets(e);
				})), L(`=`).andr(V.alphabets).to((function(e) {
					return new F.Modifier.Shape.DefineShape(e);
				})), Ze(`rect`).to((function() {
					return new F.Modifier.Shape.Rect();
				})));
			})),
			frameShape: B((function() {
				return L(`F`).andr(V.frameMain).and(I(Je(L(`:`).andr(I(z(V.frameRadiusVector().to((function(e) {
					return new F.Modifier.Shape.Frame.Radius(e);
				})), V.colorName().to((function(e) {
					return new F.Modifier.Shape.Frame.Color(e);
				})))))))).to((function(e) {
					var t = e.head;
					return t === `` && (t = `-`), new F.Modifier.Shape.Frame(t, e.tail);
				}));
			})),
			alphabets: B((function() {
				return Ge(/^([a-zA-Z]+)/);
			})),
			colorName: B((function() {
				return Ge(/^([a-zA-Z][a-zA-Z0-9]*)/);
			})),
			direction: B((function() {
				return qe(V.direction0, Je(V.direction1)).to((function(e) {
					return new F.Direction.Compound(e.head, e.tail);
				}));
			})),
			direction0: B((function() {
				return z(V.direction2, V.diag().to((function(e) {
					return new F.Direction.Diag(e);
				})));
			})),
			direction1: B((function() {
				return z(L(`:`).andr(V.vector).to((function(e) {
					return new F.Direction.RotVector(e);
				})), L(`_`).to((function(e) {
					return new F.Direction.RotAntiCW();
				})), L(`^`).to((function(e) {
					return new F.Direction.RotCW();
				})));
			})),
			direction2: B((function() {
				return z(L(`v`).andr(V.vector).to((function(e) {
					return new F.Direction.Vector(e);
				})), L(`q`).andr(R(`{`)).andr(V.posDecor).andl(R(`}`)).to((function(e) {
					return new F.Direction.ConstructVector(e);
				})));
			})),
			nonemptyDirection: B((function() {
				return z(qe(V.nonemptyDirection0, Je(V.direction1)), qe(V.direction0, Ye(V.direction1))).to((function(e) {
					return new F.Direction.Compound(e.head, e.tail);
				}));
			})),
			nonemptyDirection0: B((function() {
				return z(V.direction2, V.nonemptyDiag().to((function(e) {
					return new F.Direction.Diag(e);
				})));
			})),
			diag: B((function() {
				return z(V.nonemptyDiag, Ze(`empty`).to((function(e) {
					return new F.Diag.Default();
				})));
			})),
			nonemptyDiag: B((function() {
				return z(Ke(/^(ld|dl)/).to((function(e) {
					return new F.Diag.LD();
				})), Ke(/^(rd|dr)/).to((function(e) {
					return new F.Diag.RD();
				})), Ke(/^(lu|ul)/).to((function(e) {
					return new F.Diag.LU();
				})), Ke(/^(ru|ur)/).to((function(e) {
					return new F.Diag.RU();
				})), L(`l`).to((function(e) {
					return new F.Diag.L();
				})), L(`r`).to((function(e) {
					return new F.Diag.R();
				})), L(`d`).to((function(e) {
					return new F.Diag.D();
				})), L(`u`).to((function(e) {
					return new F.Diag.U();
				})));
			})),
			decor: B((function() {
				return V.command().rep().to((function(e) {
					return new F.Decor(e);
				}));
			})),
			command: B((function() {
				return z(L(`\\ar`).andr(I(Je(V.arrowForm))).and(V.path).to((function(e) {
					return new F.Command.Ar(e.head, e.tail);
				})), L(`\\xymatrix`).andr(V.xymatrix), L(`\\PATH`).andr(V.path).to((function(e) {
					return new F.Command.Path(e);
				})), L(`\\afterPATH`).andr(R(`{`)).andr(V.decor).andl(R(`}`)).and(V.path).to((function(e) {
					return new F.Command.AfterPath(e.head, e.tail);
				})), L(`\\save`).andr(V.pos).to((function(e) {
					return new F.Command.Save(e);
				})), L(`\\restore`).to((function() {
					return new F.Command.Restore();
				})), L(`\\POS`).andr(V.pos).to((function(e) {
					return new F.Command.Pos(e);
				})), L(`\\afterPOS`).andr(R(`{`)).andr(V.decor).andl(R(`}`)).and(V.pos).to((function(e) {
					return new F.Command.AfterPos(e.head, e.tail);
				})), L(`\\drop`).andr(V.object).to((function(e) {
					return new F.Command.Drop(e);
				})), L(`\\connect`).andr(V.object).to((function(e) {
					return new F.Command.Connect(e);
				})), L(`\\relax`).to((function() {
					return new F.Command.Relax();
				})), L(`\\xyignore`).andr(R(`{`)).andr(V.pos).and(V.decor).andl(R(`}`)).to((function(e) {
					return new F.Command.Ignore(e.head, e.tail);
				})), L(`\\xyshowAST`).andr(R(`{`)).andr(V.pos).and(V.decor).andl(R(`}`)).to((function(e) {
					return new F.Command.ShowAST(e.head, e.tail);
				})), V.twocellCommand);
			})),
			arrowForm: B((function() {
				return z(L(`@`).andr(I(Ge(/^([\-\.~=:])/))).to((function(e) {
					return new F.Command.Ar.Form.ChangeStem(e);
				})), L(`@`).andr(R(`!`)).to((function(e) {
					return new F.Command.Ar.Form.DashArrowStem();
				})), L(`@`).andr(R(`/`)).andr(V.direction).and(I(Xe(V.looseDimen))).andl(R(`/`)).to((function(e) {
					return new F.Command.Ar.Form.CurveArrow(e.head, e.tail.getOrElse(`.5pc`));
				})), L(`@`).andr(R(`(`)).andr(V.direction).andl(R(`,`)).and(V.direction).andl(R(`)`)).to((function(e) {
					return new F.Command.Ar.Form.CurveFitToDirection(e.head, e.tail);
				})), L(`@`).andr(R("`")).andr(V.coord).to((function(e) {
					return new F.Command.Ar.Form.CurveWithControlPoints(e);
				})), L(`@`).andr(R(`[`)).andr(V.shape).andl(R(`]`)).to((function(e) {
					return new F.Command.Ar.Form.AddShape(e);
				})), L(`@`).andr(R(`*`)).andr(R(`{`)).andr(I(Je(V.modifier))).andl(R(`}`)).to((function(e) {
					return new F.Command.Ar.Form.AddModifiers(e);
				})), L(`@`).andr(R(`<`)).andr(V.dimen).andl(R(`>`)).to((function(e) {
					return new F.Command.Ar.Form.Slide(e);
				})), L(`|`).andr(V.anchor).and(V.it).to((function(e) {
					return new F.Command.Ar.Form.LabelAt(e.head, e.tail);
				})), L(`^`).andr(V.anchor).and(V.it).to((function(e) {
					return new F.Command.Ar.Form.LabelAbove(e.head, e.tail);
				})), L(`_`).andr(V.anchor).and(V.it).to((function(e) {
					return new F.Command.Ar.Form.LabelBelow(e.head, e.tail);
				})), L(`@`).andr(R(`?`)).to((function() {
					return new F.Command.Ar.Form.ReverseAboveAndBelow();
				})), L(`@`).andr(I(Ge(/^([\^_0123])/).opt())).and(I(Xe(V.tipConnTip))).to((function(e) {
					var t = e.head.getOrElse(``);
					if (e.tail.isDefined) {
						var n = e.tail.get;
						return new F.Command.Ar.Form.BuildArrow(t, n.tail, n.stem, n.head);
					}
					return new F.Command.Ar.Form.ChangeVariant(t);
				})));
			})),
			tipConnTip: B((function() {
				return L(`{`).andr(I(Xe(V.nonemptyTip))).and(I(Xe(V.nonemptyConn))).and(I(Xe(V.nonemptyTip))).andl(R(`}`)).to((function(e) {
					var t, n, r, i = e.head.head, a = e.head.tail, o = e.tail, s = new F.Command.Ar.Form.Tip.Tipchars(``);
					return a.isDefined || o.isDefined ? (t = i.getOrElse(s), n = a.getOrElse(new F.Command.Ar.Form.Conn.Connchars(``)), r = o.getOrElse(s)) : i.isDefined ? (t = s, n = new F.Command.Ar.Form.Conn.Connchars(`-`), r = i.getOrElse(s)) : (t = s, n = new F.Command.Ar.Form.Conn.Connchars(``), r = s), {
						tail: t,
						stem: n,
						head: r
					};
				}));
			})),
			nonemptyTip: B((function() {
				return z(Ge(/^([<>()|'`+\/a-zA-Z ]+)/).to((function(e) {
					return new F.Command.Ar.Form.Tip.Tipchars(e);
				})), L(`*`).andr(V.object).to((function(e) {
					return new F.Command.Ar.Form.Tip.Object(e);
				})), V.dir().to((function(e) {
					return new F.Command.Ar.Form.Tip.Dir(e);
				})));
			})),
			nonemptyConn: B((function() {
				return z(Ge(/^([\-\.~=:]+)/).to((function(e) {
					return new F.Command.Ar.Form.Conn.Connchars(e);
				})), L(`*`).andr(V.object).to((function(e) {
					return new F.Command.Ar.Form.Conn.Object(e);
				})), V.dir().to((function(e) {
					return new F.Command.Ar.Form.Conn.Dir(e);
				})));
			})),
			path: B((function() {
				return V.path2(O.empty).to((function(e) {
					return new F.Command.Path.Path(e);
				}));
			})),
			path2: function(e) {
				var t = B((function() {
					return V.path2(e);
				}));
				return z(V.path3().and(t).to((function(e) {
					return e.tail.prepend(e.head);
				})), qe(`~`, `{`, t, `}`).to((function(e) {
					return e.head.tail;
				})).into((function(e) {
					return V.path2(e);
				})), V.segment().to((function(e) {
					return O.empty.prepend(new F.Command.Path.LastSegment(e));
				})), Ze(e).to((function(e) {
					return e;
				})));
			},
			path3: B((function() {
				return z(qe(`~`, `=`, `{`, V.posDecor, `}`).to((function(e) {
					return new F.Command.Path.SetBeforeAction(e.head.tail);
				})), qe(`~`, `/`, `{`, V.posDecor, `}`).to((function(e) {
					return new F.Command.Path.SetAfterAction(e.head.tail);
				})), qe(`~`, `<`, `{`, V.labels, `}`).to((function(e) {
					return new F.Command.Path.AddLabelNextSegmentOnly(e.head.tail);
				})), qe(`~`, `>`, `{`, V.labels, `}`).to((function(e) {
					return new F.Command.Path.AddLabelLastSegmentOnly(e.head.tail);
				})), qe(`~`, `+`, `{`, V.labels, `}`).to((function(e) {
					return new F.Command.Path.AddLabelEverySegment(e.head.tail);
				})), qe(`'`, V.segment).to((function(e) {
					return new F.Command.Path.StraightSegment(e.tail);
				})), qe("`", V.turn, V.segment).to((function(e) {
					return new F.Command.Path.TurningSegment(e.head.tail, e.tail);
				})));
			})),
			turn: B((function() {
				return z(V.nonemptyCir().and(V.turnRadius).to((function(e) {
					return new F.Command.Path.Turn.Cir(e.head, e.tail);
				})), V.diag().and(V.turnRadius).to((function(e) {
					return new F.Command.Path.Turn.Diag(e.head, e.tail);
				})));
			})),
			turnRadius: B((function() {
				return z(L(`/`).andr(V.dimen).to((function(e) {
					return new F.Command.Path.TurnRadius.Dimen(e);
				})), Ze(`default`).to((function() {
					return new F.Command.Path.TurnRadius.Default();
				})));
			})),
			segment: B((function() {
				return V.nonemptyPos().and(V.pathSlide).and(V.labels).to((function(e) {
					return new F.Command.Path.Segment(e.head.head, e.head.tail, e.tail);
				}));
			})),
			pathSlide: B((function() {
				return z(L(`<`).andr(V.dimen).andl(R(`>`)).to((function(e) {
					return new F.Slide(new y.Some(e));
				})), Ze(`no slide`).to((function() {
					return new F.Slide(y.empty);
				})));
			})),
			labels: B((function() {
				return V.label().rep().to((function(e) {
					return new F.Command.Path.Labels(e);
				}));
			})),
			label: B((function() {
				return z(qe(`^`, V.anchor, V.it, V.alias).to((function(e) {
					return new F.Command.Path.Label.Above(new F.Pos.Place(e.head.head.tail), e.head.tail, e.tail);
				})), qe(`_`, V.anchor, V.it, V.alias).to((function(e) {
					return new F.Command.Path.Label.Below(new F.Pos.Place(e.head.head.tail), e.head.tail, e.tail);
				})), qe(`|`, V.anchor, V.it, V.alias).to((function(e) {
					return new F.Command.Path.Label.At(new F.Pos.Place(e.head.head.tail), e.head.tail, e.tail);
				})));
			})),
			anchor: B((function() {
				return z(L(`-`).andr(V.anchor).to((function(e) {
					return new F.Place(1, 1, new F.Place.Factor(.5), void 0).compound(e);
				})), V.place);
			})),
			it: B((function() {
				return Je(L(`[`).andr(V.shape).andl(R(`]`)).to((function(e) {
					return e;
				}))).and(V.it2).to((function(e) {
					return new F.Object(e.head.concat(e.tail.modifiers), e.tail.object);
				}));
			})),
			it2: B((function() {
				return z(Ke(/^[0-9a-zA-Z]/).and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail;
					return new F.Object(O.empty, V.toMath(`\\labelstyle ` + t, n));
				})), Ke(/^(\\[a-zA-Z][a-zA-Z0-9]*)/).and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail;
					return new F.Object(O.empty, V.toMath(`\\labelstyle ` + t, n));
				})), L(`{`).andr(V.text).andl(We(`}`)).and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail;
					return new F.Object(O.empty, V.toMath(`\\labelstyle ` + t, n));
				})), L(`*`).andr(V.object), L(`@`).andr(V.dir).to((function(e) {
					return new F.Object(O.empty, e);
				})));
			})),
			alias: B((function() {
				return qe(`=`, `"`, V.id, `"`).opt().to((function(e) {
					return e.map((function(e) {
						return e.head.tail;
					}));
				}));
			})),
			xymatrix: B((function() {
				return V.setup().andl(R(`{`)).and(V.rows).andl(R(`}`)).to((function(e) {
					return new F.Command.Xymatrix(e.head, e.tail);
				}));
			})),
			setup: B((function() {
				return Je(I(z(L(`"`).andr(I(Ge(/^[^"]+/))).andl(We(`"`)).to((function(e) {
					return new F.Command.Xymatrix.Setup.Prefix(e);
				})), L(`@!`).andr(I(Ge(/^[RC]/).opt().to((function(e) {
					return e.getOrElse(``);
				})))).and(I(z(Ue(`0`).to((function() {
					return `0em`;
				})), Ue(`=`).andr(V.dimen)))).to((function(e) {
					var t = e.tail;
					switch (e.head) {
						case `R`: return new F.Command.Xymatrix.Setup.PretendEntrySize.Height(t);
						case `C`: return new F.Command.Xymatrix.Setup.PretendEntrySize.Width(t);
						default: return new F.Command.Xymatrix.Setup.PretendEntrySize.HeightAndWidth(t);
					}
				})), L(`@!`).andr(I(z(Ue(`R`).to((function() {
					return new F.Command.Xymatrix.Setup.FixGrid.Row();
				})), Ue(`C`).to((function() {
					return new F.Command.Xymatrix.Setup.FixGrid.Column();
				}))).opt().to((function(e) {
					return e.getOrElse(new F.Command.Xymatrix.Setup.FixGrid.RowAndColumn());
				})))), L(`@`).andr(I(Ge(/^[MWHL]/))).and(V.addOp).and(V.dimen).to((function(e) {
					var t = e.head.tail, n = e.tail;
					switch (e.head.head) {
						case `M`: return new F.Command.Xymatrix.Setup.AdjustEntrySize.Margin(t, n);
						case `W`: return new F.Command.Xymatrix.Setup.AdjustEntrySize.Width(t, n);
						case `H`: return new F.Command.Xymatrix.Setup.AdjustEntrySize.Height(t, n);
						case `L`: return new F.Command.Xymatrix.Setup.AdjustLabelSep(t, n);
					}
				})), L(`@`).andr(V.nonemptyDirection).to((function(e) {
					return new F.Command.Xymatrix.Setup.SetOrientation(e);
				})), L(`@*[`).andr(V.shape).andl(R(`]`)).to((function(e) {
					return new F.Command.Xymatrix.Setup.AddModifier(e);
				})), L(`@*`).andr(V.addOp).and(V.size).to((function(e) {
					return new F.Command.Xymatrix.Setup.AddModifier(new F.Modifier.AddOp(e.head, e.tail));
				})), L(`@`).andr(I(Ge(/^[RC]/).opt().to((function(e) {
					return e.getOrElse(``);
				})))).and(V.addOp).and(V.dimen).to((function(e) {
					var t = e.head.tail, n = e.tail;
					switch (e.head.head) {
						case `R`: return new F.Command.Xymatrix.Setup.ChangeSpacing.Row(t, n);
						case `C`: return new F.Command.Xymatrix.Setup.ChangeSpacing.Column(t, n);
						default: return new F.Command.Xymatrix.Setup.ChangeSpacing.RowAndColumn(t, n);
					}
				})), L(`@1`).to((function() {
					return new F.Command.Xymatrix.Setup.AdjustEntrySize.Margin(new F.Modifier.AddOp.Set(), `1pc`);
				})))));
			})),
			rows: B((function() {
				return V.row().and(I(Je(L(`\\\\`).andr(V.row)))).to((function(e) {
					var t = e.tail.prepend(e.head);
					if (!t.isEmpty) {
						var n = t.at(t.length() - 1);
						n.entries.length() === 1 && n.entries.at(0).isEmpty && (t = t.reverse().tail.reverse());
					}
					return t;
				}));
			})),
			row: B((function() {
				return V.entry().and(I(Je(L(`&`).andr(V.entry)))).to((function(e) {
					return new F.Command.Xymatrix.Row(e.tail.prepend(e.head));
				}));
			})),
			entry: B((function() {
				return z(L(`*`).andr(V.object).and(V.pos).and(V.decor).to((function(e) {
					var t = e.head.head, n = e.head.tail, r = e.tail;
					return new F.Command.Xymatrix.Entry.ObjectEntry(t, n, r);
				})), V.entryModifier().rep().and(V.looseObjectbox).and(V.decor).to((function(e) {
					var t = e.head.head.foldLeft(O.empty, (function(e, t) {
						return t.concat(e);
					})), n = e.head.tail.isEmpty, r = e.head.tail.object, i = e.tail;
					return n && t.isEmpty ? new F.Command.Xymatrix.Entry.EmptyEntry(i) : new F.Command.Xymatrix.Entry.SimpleEntry(t, r, i);
				})));
			})),
			entryModifier: B((function() {
				return z(L(`**`).andr(R(`[`)).andr(V.shape).andl(R(`]`)).to((function(e) {
					return O.empty.append(e);
				})), L(`**`).andr(R(`{`)).andr(I(Je(V.modifier))).andl(R(`}`)));
			})),
			looseObjectbox: B((function() {
				return z(V.objectbox().to((function(e) {
					return {
						isEmpty: !1,
						object: e
					};
				})), Ge(/^[^\\{}%&]+/).opt().to((function(e) {
					return e.getOrElse(``);
				})).and(I(Je(z(Ue(`{`).andr(V.text).andl(We(`}`)).to((function(e) {
					return `{` + e + `}`;
				})), Ue(`\\`).andr(I((e = Ge(/^(\\|ar|xymatrix|PATH|afterPATH|save|restore|POS|afterPOS|drop|connect|xyignore|([lrud]+(twocell|uppertwocell|lowertwocell|compositemap))|xtwocell|xuppertwocell|xlowertwocell|xcompositemap)/), k.not(k.lazyParser(e))))).andr(I(Ge(/^[{}%&]/).opt().to((function(e) {
					return e.getOrElse(``);
				})))).to((function(e) {
					return `\\` + e;
				})), Ge(/^%[^\r\n]*(\r\n|\r|\n)?/).to((function(e) {
					return ` `;
				}))).and(I(Ge(/^[^\\{}%&]+/).opt().to((function(e) {
					return e.getOrElse(``);
				})))).to((function(e) {
					return e.head + e.tail;
				}))).to((function(e) {
					return e.mkString(``);
				})))).and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail, r = t.head + t.tail;
					return {
						isEmpty: r.trim().length === 0,
						object: V.toMath(`\\hbox{$\\objectstyle{` + r + `}$}`, n)
					};
				})));
				var e;
			})),
			twocellCommand: B((function() {
				return V.twocell().and(I(Je(V.twocellSwitch))).and(V.twocellArrow).to((function(e) {
					return new F.Command.Twocell(e.head.head, e.head.tail, e.tail);
				}));
			})),
			twocell: B((function() {
				return z(Ke(/^\\[lrud]+twocell/).to((function(e) {
					var t = e.substring(1, e.length - 7);
					return new F.Command.Twocell.Twocell(t, y.empty);
				})), Ke(/^\\[lrud]+uppertwocell/).to((function(e) {
					var t = e.substring(1, e.length - 12);
					return new F.Command.Twocell.UpperTwocell(t, y.empty);
				})), Ke(/^\\[lrud]+lowertwocell/).to((function(e) {
					var t = e.substring(1, e.length - 12);
					return new F.Command.Twocell.LowerTwocell(t, y.empty);
				})), Ke(/^\\[lrud]+compositemap/).to((function(e) {
					var t = e.substring(1, e.length - 12);
					return new F.Command.Twocell.CompositeMap(t, y.empty);
				})), z(L(`\\xtwocell`).to((function() {
					return F.Command.Twocell.Twocell;
				})), L(`\\xuppertwocell`).to((function() {
					return F.Command.Twocell.UpperTwocell;
				})), L(`\\xlowertwocell`).to((function() {
					return F.Command.Twocell.LowerTwocell;
				})), L(`\\xcompositemap`).to((function() {
					return F.Command.Twocell.CompositeMap;
				}))).andl(R(`[`)).and(I(Ge(/^[lrud]+/))).andl(R(`]`)).andl(R(`{`)).and(V.text).andl(R(`}`)).and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail, r = new F.Object(O.empty, V.toMath(`\\labelstyle ` + t.tail, n));
					return new t.head.head(t.head.tail, new y.Some(r));
				})));
			})),
			twocellSwitch: B((function() {
				return z(L(`^`).andr(V.twocellLabel).to((function(e) {
					return new F.Command.Twocell.Switch.UpperLabel(e);
				})), L(`_`).andr(V.twocellLabel).to((function(e) {
					return new F.Command.Twocell.Switch.LowerLabel(e);
				})), L(`\\omit`).to((function() {
					return new F.Command.Twocell.Switch.DoNotSetCurvedArrows();
				})), L(`~!`).to((function() {
					return new F.Command.Twocell.Switch.PlaceModMapObject();
				})), Ke(/^(~[`'])/).andl(R(`{`)).and(V.object).andl(R(`}`)).to((function(e) {
					var t = e.head.substring(1);
					return new F.Command.Twocell.Switch.ChangeHeadTailObject(t, e.tail);
				})), Ke(/^(~[\^_]?)/).andl(R(`{`)).and(V.object).and(I(Xe(L(`~**`).andr(V.object)))).andl(R(`}`)).to((function(e) {
					var t = e.head.head.substring(1), n = e.head.tail, r = e.tail;
					return new F.Command.Twocell.Switch.ChangeCurveObject(t, n, r);
				})), V.nudge().to((function(e) {
					return new F.Command.Twocell.Switch.SetCurvature(e);
				})));
			})),
			twocellLabel: B((function() {
				return z(Ke(/^[0-9a-zA-Z]/).and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail, r = new F.Object(O.empty, V.toMath(`\\twocellstyle ` + t, n));
					return new F.Command.Twocell.Label(y.empty, r);
				})), Ke(/^(\\[a-zA-Z][a-zA-Z0-9]*)/).and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail, r = new F.Object(O.empty, V.toMath(`\\twocellstyle ` + t, n));
					return new F.Command.Twocell.Label(y.empty, r);
				})), L(`{`).andr(I(Xe(V.nudge))).andl(R(`*`)).and(V.object).andl(R(`}`)).to((function(e) {
					return new F.Command.Twocell.Label(e.head, e.tail);
				})), L(`{`).andr(I(Xe(V.nudge))).and(V.text).andl(We(`}`)).and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail, r = new F.Object(O.empty, V.toMath(`\\twocellstyle ` + t.tail, n));
					return new F.Command.Twocell.Label(t.head, r);
				})));
			})),
			nudge: B((function() {
				return z(L(`<\\omit>`).to((function() {
					return new F.Command.Twocell.Nudge.Omit();
				})), L(`<`).andr(V.factor).andl(R(`>`)).to((function(e) {
					return new F.Command.Twocell.Nudge.Number(e);
				})));
			})),
			twocellArrow: B((function() {
				return z(L(`{`).andr(I(Ke(/^([\^_=`'"!]|\\omit)/))).and(V.twocellLabelEntry).andl(R(`}`)).to((function(e) {
					return new F.Command.Twocell.Arrow.WithOrientation(e.head, e.tail);
				})), L(`{`).andr(V.nudge).and(V.twocellLabelEntry).andl(R(`}`)).to((function(e) {
					return new F.Command.Twocell.Arrow.WithPosition(e.head, e.tail);
				})), L(`{`).andr(V.twocellLabelEntry).andl(R(`}`)).to((function(e) {
					return new F.Command.Twocell.Arrow.WithOrientation(``, e);
				})), Ze(`no arrow label`).andr(V.textNodeCreator).to((function(e) {
					return new F.Command.Twocell.Arrow.WithOrientation(``, new F.Object(O.empty, V.toMath(`\\twocellstyle{}`, e)));
				})));
			})),
			twocellLabelEntry: B((function() {
				return z(L(`*`).andr(V.object), V.text().and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail;
					return new F.Object(O.empty, V.toMath(`\\twocellstyle ` + t, n));
				})));
			})),
			newdir: B((function() {
				return L(`{`).andr(V.dirMain).andl(We(`}`)).andl(R(`{`)).and(V.compositeObject).andl(R(`}`)).to((function(e) {
					return new F.Command.Newdir(e.head, new F.ObjectBox.CompositeObject(e.tail));
				}));
			})),
			xyimport: B((function() {
				return L(`\\xyimport`).andr(R(`(`)).andr(V.factor).andl(R(`,`)).and(V.factor).andl(R(`)`)).and(I(Xe(L(`(`).andr(V.factor).andl(R(`,`)).and(V.factor).andl(R(`)`))))).andl(R(`{`)).and(I(z(L(`\\includegraphics`).andr(V.includegraphics), V.text().and(V.textNodeCreator).to((function(e) {
					var t = e.head, n = e.tail;
					return V.toMath(`\\hbox{$\\objectstyle{` + t + `}$}`, n);
				}))))).andl(R(`}`)).to((function(e) {
					var t, n, r = e.head.head.head, i = e.head.head.tail;
					e.head.tail.isDefined ? (t = e.head.tail.get.head, n = e.head.tail.get.tail) : (t = 0, n = 0);
					var a = e.tail;
					return a.isIncludegraphics === void 0 ? new F.Pos.Xyimport.TeXCommand(r, i, t, n, a) : new F.Pos.Xyimport.Graphics(r, i, t, n, a);
				}));
			})),
			includegraphics: B((function() {
				return L(`[`).andr(I(Xe(V.includegraphicsAttrList))).andl(R(`]`)).andl(R(`{`)).and(I(Ke(/^[^\s{}]+/))).andl(R(`}`)).to((function(e) {
					var t = e.head.getOrElse(O.empty), n = e.tail;
					return new F.Command.Includegraphics(!1, t, n);
				}));
			})),
			includegraphicsAttrList: B((function() {
				return V.includegraphicsAttr().and(I(Je(L(`,`).andr(V.includegraphicsAttr)))).to((function(e) {
					return e.tail.prepend(e.head);
				}));
			})),
			includegraphicsAttr: B((function() {
				return z(L(`width`).andr(R(`=`)).andr(V.dimen).to((function(e) {
					return new F.Command.Includegraphics.Attr.Width(e);
				})), L(`height`).andr(R(`=`)).andr(V.dimen).to((function(e) {
					return new F.Command.Includegraphics.Attr.Height(e);
				})));
			}))
		};
		for (var $e in Qe) V[$e] = Qe[$e];
		var et = V, tt = function(e, t) {
			return [
				e[1] * t[2] - e[2] * t[1],
				e[2] * t[0] - e[0] * t[2],
				e[0] * t[1] - e[1] * t[0]
			];
		}, nt = function(e) {
			return e < 0 ? -1 : e > 0 ? 1 : 0;
		}, rt = function(e) {
			return Math.abs(e) < l.machinePrecision ? 0 : e;
		}, H = function(e, t) {
			var n = e[t], r = function() {
				var r = n.call(this), a = function() {
					return r;
				};
				return a.reset = i, e[t] = a, r;
			}, i = function() {
				e[t] = r;
			};
			r.reset = i, i();
		}, it = function(e) {
			return Math.round(100 * e) / 100;
		};
		function at(e) {
			return at = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
				return typeof e;
			} : function(e) {
				return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e;
			}, at(e);
		}
		function ot(e, t) {
			if (typeof t != `function` && t !== null) throw TypeError(`Super expression must either be null or a function`);
			e.prototype = Object.create(t && t.prototype, { constructor: {
				value: e,
				writable: !0,
				configurable: !0
			} }), t && st(e, t);
		}
		function st(e, t) {
			return st = Object.setPrototypeOf || function(e, t) {
				return e.__proto__ = t, e;
			}, st(e, t);
		}
		function ct(e) {
			var t = function() {
				if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return !1;
				if (typeof Proxy == `function`) return !0;
				try {
					return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {}))), !0;
				} catch {
					return !1;
				}
			}();
			return function() {
				var n, r = ut(e);
				if (t) {
					var i = ut(this).constructor;
					n = Reflect.construct(r, arguments, i);
				} else n = r.apply(this, arguments);
				return lt(this, n);
			};
		}
		function lt(e, t) {
			if (t && (at(t) === `object` || typeof t == `function`)) return t;
			if (t !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
			return function(e) {
				if (e === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
				return e;
			}(e);
		}
		function ut(e) {
			return ut = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
				return e.__proto__ || Object.getPrototypeOf(e);
			}, ut(e);
		}
		function dt(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		function ft(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function pt(e, t, n) {
			return t && ft(e.prototype, t), n && ft(e, n), e;
		}
		var U = function() {
			function e() {
				dt(this, e);
			}
			return pt(e, [
				{
					key: `toRect`,
					value: function(t) {
						return new e.Rect(this.x, this.y, t);
					}
				},
				{
					key: `toPoint`,
					value: function() {
						return new e.Point(this.x, this.y);
					}
				},
				{
					key: `combineRect`,
					value: function(t) {
						return e.combineRect(this, t);
					}
				}
			], [{
				key: `combineRect`,
				value: function(e, t) {
					if (e === void 0) return t;
					if (t === void 0) return e;
					var n = -(Math.min(e.x - e.l, t.x - t.l) - e.x), r = Math.max(e.x + e.r, t.x + t.r) - e.x, i = -(Math.min(e.y - e.d, t.y - t.d) - e.y), a = Math.max(e.y + e.u, t.y + t.u) - e.y;
					return e.toRect({
						l: n,
						r,
						d: i,
						u: a
					});
				}
			}]), e;
		}();
		function mt(e) {
			return mt = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
				return typeof e;
			} : function(e) {
				return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e;
			}, mt(e);
		}
		function W(e, t) {
			if (typeof t != `function` && t !== null) throw TypeError(`Super expression must either be null or a function`);
			e.prototype = Object.create(t && t.prototype, { constructor: {
				value: e,
				writable: !0,
				configurable: !0
			} }), t && ht(e, t);
		}
		function ht(e, t) {
			return ht = Object.setPrototypeOf || function(e, t) {
				return e.__proto__ = t, e;
			}, ht(e, t);
		}
		function G(e) {
			var t = function() {
				if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return !1;
				if (typeof Proxy == `function`) return !0;
				try {
					return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {}))), !0;
				} catch {
					return !1;
				}
			}();
			return function() {
				var n, r = _t(e);
				if (t) {
					var i = _t(this).constructor;
					n = Reflect.construct(r, arguments, i);
				} else n = r.apply(this, arguments);
				return gt(this, n);
			};
		}
		function gt(e, t) {
			if (t && (mt(t) === `object` || typeof t == `function`)) return t;
			if (t !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
			return K(e);
		}
		function K(e) {
			if (e === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
			return e;
		}
		function _t(e) {
			return _t = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
				return e.__proto__ || Object.getPrototypeOf(e);
			}, _t(e);
		}
		function q(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		function vt(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function J(e, t, n) {
			return t && vt(e.prototype, t), n && vt(e, n), e;
		}
		U.Point = function(e) {
			ot(n, e);
			var t = ct(n);
			function n(e, r) {
				var i;
				return dt(this, n), (i = t.call(this)).x = e, i.y = r, i;
			}
			return pt(n, [
				{
					key: `l`,
					get: function() {
						return 0;
					}
				},
				{
					key: `r`,
					get: function() {
						return 0;
					}
				},
				{
					key: `u`,
					get: function() {
						return 0;
					}
				},
				{
					key: `d`,
					get: function() {
						return 0;
					}
				},
				{
					key: `isPoint`,
					value: function() {
						return !0;
					}
				},
				{
					key: `isRect`,
					value: function() {
						return !1;
					}
				},
				{
					key: `isCircle`,
					value: function() {
						return !1;
					}
				},
				{
					key: `edgePoint`,
					value: function(e, t) {
						return this;
					}
				},
				{
					key: `proportionalEdgePoint`,
					value: function(e, t) {
						return this;
					}
				},
				{
					key: `grow`,
					value: function(e, t) {
						var n = Math.max(0, e), r = Math.max(0, t);
						return this.toRect({
							l: n,
							r: n,
							u: r,
							d: r
						});
					}
				},
				{
					key: `toSize`,
					value: function(e, t) {
						return this.toRect({
							l: e / 2,
							r: e / 2,
							u: t / 2,
							d: t / 2
						});
					}
				},
				{
					key: `growTo`,
					value: function(e, t) {
						var n = Math.max(0, e), r = Math.max(0, t);
						return this.toRect({
							l: n / 2,
							r: n / 2,
							u: r / 2,
							d: r / 2
						});
					}
				},
				{
					key: `shrinkTo`,
					value: function(e, t) {
						return this;
					}
				},
				{
					key: `move`,
					value: function(e, t) {
						return new U.Point(e, t);
					}
				},
				{
					key: `shiftFrame`,
					value: function(e, t) {
						return this;
					}
				},
				{
					key: `rotate`,
					value: function(e) {
						return this;
					}
				},
				{
					key: `contains`,
					value: function(e) {
						return !1;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `{x:` + this.x + `, y:` + this.y + `}`;
					}
				}
			]), n;
		}(U), U.Rect = function(e) {
			ot(n, e);
			var t = ct(n);
			function n(e, r, i) {
				var a;
				return dt(this, n), (a = t.call(this)).x = e, a.y = r, a.l = i.l || 0, a.r = i.r || 0, a.u = i.u || 0, a.d = i.d || 0, a;
			}
			return pt(n, [
				{
					key: `isPoint`,
					value: function() {
						return this.l === 0 && this.r === 0 && this.u === 0 && this.d === 0;
					}
				},
				{
					key: `isRect`,
					value: function() {
						return !this.isPoint();
					}
				},
				{
					key: `isCircle`,
					value: function() {
						return !1;
					}
				},
				{
					key: `edgePoint`,
					value: function(e, t) {
						if (this.isPoint()) return this;
						var n, r = e - this.x, i = t - this.y;
						return r > 0 ? (n = i * this.r / r) > this.u ? new U.Point(this.x + this.u * r / i, this.y + this.u) : n < -this.d ? new U.Point(this.x - this.d * r / i, this.y - this.d) : new U.Point(this.x + this.r, this.y + n) : r < 0 ? (n = -i * this.l / r) > this.u ? new U.Point(this.x + this.u * r / i, this.y + this.u) : n < -this.d ? new U.Point(this.x - this.d * r / i, this.y - this.d) : new U.Point(this.x - this.l, this.y + n) : i > 0 ? new U.Point(this.x, this.y + this.u) : new U.Point(this.x, this.y - this.d);
					}
				},
				{
					key: `proportionalEdgePoint`,
					value: function(e, t) {
						if (this.isPoint()) return this;
						var n = e - this.x, r = t - this.y;
						if (Math.abs(n) < l.machinePrecision && Math.abs(r) < l.machinePrecision) return new U.Point(this.x - this.l, this.y + this.u);
						var i, a = this.l + this.r, o = this.u + this.d, s = Math.PI, c = Math.atan2(r, n);
						return -3 * s / 4 < c && c <= -s / 4 ? (i = (c + 3 * s / 4) / (s / 2), new U.Point(this.x + this.r - i * a, this.y + this.u)) : -s / 4 < c && c <= s / 4 ? (i = (c + s / 4) / (s / 2), new U.Point(this.x - this.l, this.y + this.u - i * o)) : s / 4 < c && c <= 3 * s / 4 ? (i = (c - s / 4) / (s / 2), new U.Point(this.x - this.l + i * a, this.y - this.d)) : (i = (c - (c > 0 ? 3 * s / 4 : -5 * s / 4)) / (s / 2), new U.Point(this.x + this.r, this.y - this.d + i * o));
					}
				},
				{
					key: `grow`,
					value: function(e, t) {
						return this.toRect({
							l: Math.max(0, this.l + e),
							r: Math.max(0, this.r + e),
							u: Math.max(0, this.u + t),
							d: Math.max(0, this.d + t)
						});
					}
				},
				{
					key: `toSize`,
					value: function(e, t) {
						var n, r, i, a, o = this.l + this.r, s = this.u + this.d;
						return o === 0 ? (a = e / 2, i = e / 2) : (a = e * this.l / o, i = e * this.r / o), s === 0 ? (n = t / 2, r = t / 2) : (n = t * this.u / s, r = t * this.d / s), this.toRect({
							l: a,
							r: i,
							u: n,
							d: r
						});
					}
				},
				{
					key: `growTo`,
					value: function(e, t) {
						var n = this.u, r = this.d, i = this.r, a = this.l, o = a + i, s = n + r;
						return e > o && (o === 0 ? (a = e / 2, i = e / 2) : (a = e * this.l / o, i = e * this.r / o)), t > s && (s === 0 ? (n = t / 2, r = t / 2) : (n = t * this.u / s, r = t * this.d / s)), this.toRect({
							l: a,
							r: i,
							u: n,
							d: r
						});
					}
				},
				{
					key: `shrinkTo`,
					value: function(e, t) {
						var n = this.u, r = this.d, i = this.r, a = this.l, o = a + i, s = n + r;
						return e < o && (o === 0 ? (a = e / 2, i = e / 2) : (a = e * this.l / o, i = e * this.r / o)), t < s && (s === 0 ? (n = t / 2, r = t / 2) : (n = t * this.u / s, r = t * this.d / s)), this.toRect({
							l: a,
							r: i,
							u: n,
							d: r
						});
					}
				},
				{
					key: `move`,
					value: function(e, t) {
						return new U.Rect(e, t, {
							l: this.l,
							r: this.r,
							u: this.u,
							d: this.d
						});
					}
				},
				{
					key: `shiftFrame`,
					value: function(e, t) {
						return new U.Rect(this.x, this.y, {
							l: Math.max(0, this.l - e),
							r: Math.max(0, this.r + e),
							u: Math.max(0, this.u + t),
							d: Math.max(0, this.d - t)
						});
					}
				},
				{
					key: `rotate`,
					value: function(e) {
						var t = Math.cos(e), n = Math.sin(e), r = -this.l, i = this.r, a = this.u, o = -this.d, s = {
							x: r * t - a * n,
							y: r * n + a * t
						}, c = {
							x: r * t - o * n,
							y: r * n + o * t
						}, l = {
							x: i * t - a * n,
							y: i * n + a * t
						}, u = {
							x: i * t - o * n,
							y: i * n + o * t
						};
						return this.toRect({
							l: -Math.min(s.x, c.x, l.x, u.x),
							r: Math.max(s.x, c.x, l.x, u.x),
							u: Math.max(s.y, c.y, l.y, u.y),
							d: -Math.min(s.y, c.y, l.y, u.y)
						});
					}
				},
				{
					key: `contains`,
					value: function(e) {
						var t = e.x, n = e.y;
						return t >= this.x - this.l && t <= this.x + this.r && n >= this.y - this.d && n <= this.y + this.u;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `{x:` + this.x + `, y:` + this.y + `, l:` + this.l + `, r:` + this.r + `, u:` + this.u + `, d:` + this.d + `}`;
					}
				}
			]), n;
		}(U), U.Ellipse = function(e) {
			ot(n, e);
			var t = ct(n);
			function n(e, r, i, a, o, s) {
				var c;
				return dt(this, n), (c = t.call(this)).x = e, c.y = r, c.l = i, c.r = a, c.u = o, c.d = s, c;
			}
			return pt(n, [
				{
					key: `isPoint`,
					value: function() {
						return this.r === 0 && this.l === 0 || this.u === 0 && this.d === 0;
					}
				},
				{
					key: `isRect`,
					value: function() {
						return !1;
					}
				},
				{
					key: `isCircle`,
					value: function() {
						return !this.isPoint();
					}
				},
				{
					key: `isPerfectCircle`,
					value: function() {
						return this.l === this.r && this.l === this.u && this.l === this.d;
					}
				},
				{
					key: `edgePoint`,
					value: function(e, t) {
						if (this.isPoint()) return this;
						if (this.isPerfectCircle()) {
							var n, r = e - this.x, i = t - this.y;
							return n = Math.abs(r) < l.machinePrecision && Math.abs(i) < l.machinePrecision ? -Math.PI / 2 : Math.atan2(i, r), new U.Point(this.x + this.r * Math.cos(n), this.y + this.r * Math.sin(n));
						}
						var a = this.l, o = this.r, s = this.u, c = this.d, u = this.x, d = this.y, f = u + (o - a) / 2, p = d + (s - c) / 2, m = (a + o) / 2, h = (s + c) / 2, g = -(r = e - u), _ = (i = t - d) * m, v = g * h, y = _ * _ + v * v, b = -(c = _ * f + v * p + ((r * d - i * u) * m + (m - h) * g * p)) / y, x = y * m * m - c * c;
						if (x < 0) return new U.Point(this.x, this.y - this.d);
						var S = Math.sqrt(x) / y, C = h / m, w = _ * b + v * S + f, T = C * (v * b - _ * S + p - p) + p, E = _ * b - v * S + f, D = C * (v * b + _ * S + p - p) + p, ee = nt;
						return ee(w - f) === ee(e - f) && ee(T - p) === ee(t - p) ? new U.Point(w, T) : new U.Point(E, D);
					}
				},
				{
					key: `proportionalEdgePoint`,
					value: function(e, t) {
						if (this.isPoint()) return this;
						if (this.isPerfectCircle()) {
							var n, r = e - this.x, i = t - this.y;
							return n = Math.abs(r) < l.machinePrecision && Math.abs(i) < l.machinePrecision ? -Math.PI / 2 : Math.atan2(i, r), new U.Point(this.x - this.r * Math.cos(n), this.y - this.r * Math.sin(n));
						}
						var a = this.l, o = this.r, s = this.u, c = this.d, u = this.x, d = this.y, f = u + (o - a) / 2, p = d + (s - c) / 2, m = (a + o) / 2, h = (s + c) / 2, g = -(r = e - u), _ = (i = t - d) * m, v = g * h, y = _ * _ + v * v, b = -(c = _ * f + v * p + ((r * d - i * u) * m + (m - h) * g * p)) / y, x = y * m * m - c * c;
						if (x < 0) return new U.Point(this.x, this.y - this.d);
						var S = Math.sqrt(x) / y, C = h / m, w = _ * b + v * S + f, T = C * (v * b - _ * S + p - p) + p, E = _ * b - v * S + f, D = C * (v * b + _ * S + p - p) + p;
						return sign(w - f) === sign(e - f) && sign(T - p) === sign(t - p) ? new U.Point(E, D) : new U.Point(w, T);
					}
				},
				{
					key: `grow`,
					value: function(e, t) {
						return new U.Ellipse(this.x, this.y, Math.max(0, this.l + e), Math.max(0, this.r + e), Math.max(0, this.u + t), Math.max(0, this.d + t));
					}
				},
				{
					key: `toSize`,
					value: function(e, t) {
						var n, r, i, a, o = this.l + this.r, s = this.u + this.d;
						return o === 0 ? (a = e / 2, i = e / 2) : (a = e * this.l / o, i = e * this.r / o), s === 0 ? (n = t / 2, r = t / 2) : (n = t * this.u / s, r = t * this.d / s), new U.Ellipse(this.x, this.y, a, i, n, r);
					}
				},
				{
					key: `growTo`,
					value: function(e, t) {
						var n = this.u, r = this.d, i = this.r, a = this.l, o = a + i, s = n + r;
						return e > o && (o === 0 ? (a = e / 2, i = e / 2) : (a = e * this.l / o, i = e * this.r / o)), t > s && (s === 0 ? (n = t / 2, r = t / 2) : (n = t * this.u / s, r = t * this.d / s)), new U.Ellipse(this.x, this.y, a, i, n, r);
					}
				},
				{
					key: `shrinkTo`,
					value: function(e, t) {
						var n = this.u, r = this.d, i = this.r, a = this.l, o = a + i, s = n + r;
						return e < o && (o === 0 ? (a = e / 2, i = e / 2) : (a = e * this.l / o, i = e * this.r / o)), t < s && (s === 0 ? (n = t / 2, r = t / 2) : (n = t * this.u / s, r = t * this.d / s)), new U.Ellipse(this.x, this.y, a, i, n, r);
					}
				},
				{
					key: `move`,
					value: function(e, t) {
						return new U.Ellipse(e, t, this.l, this.r, this.u, this.d);
					}
				},
				{
					key: `shiftFrame`,
					value: function(e, t) {
						return new U.Ellipse(this.x, this.y, Math.max(0, this.l - e), Math.max(0, this.r + e), Math.max(0, this.u + t), Math.max(0, this.d - t));
					}
				},
				{
					key: `rotate`,
					value: function(e) {
						return this;
					}
				},
				{
					key: `contains`,
					value: function(e) {
						var t = e.x, n = e.y;
						if (this.isPoint()) return !1;
						var r = this.l, i = this.r, a = this.u, o = this.d, s = (r + i) / 2, c = t - (this.x + (i - r) / 2), l = (n - (this.y + (a - o) / 2)) / ((a + o) / 2 / s);
						return c * c + l * l <= s * s;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `{x:` + this.x + `, y:` + this.y + `, l:` + this.l + `, r:` + this.r + `, u:` + this.u + `, d:` + this.d + `}`;
					}
				}
			]), n;
		}(U);
		var Y = function() {
			function e() {
				q(this, e);
			}
			return J(e, [{
				key: `isNone`,
				get: function() {
					return !1;
				}
			}]), e;
		}();
		function yt(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		Y.NoneShape = function(e) {
			W(n, e);
			var t = G(n);
			function n() {
				return q(this, n), t.call(this);
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {}
				},
				{
					key: `getBoundingBox`,
					value: function() {}
				},
				{
					key: `toString`,
					value: function() {
						return `NoneShape`;
					}
				},
				{
					key: `isNone`,
					get: function() {
						return !0;
					}
				}
			]), n;
		}(Y), Y.none = new Y.NoneShape(), Y.InvisibleBoxShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e) {
				var r;
				return q(this, n), (r = t.call(this)).bbox = e, r;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return this.bbox;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `InvisibleBoxShape[bbox:` + this.bbox.toString() + `]`;
					}
				}
			]), n;
		}(Y), Y.TranslateShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r, i) {
				var a;
				return q(this, n), (a = t.call(this)).dx = e, a.dy = r, a.shape = i, H(K(a), `getBoundingBox`), a;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						var t = e.createGroup(e.transformBuilder().translate(this.dx, this.dy));
						this.shape.draw(t);
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						var e = this.shape.getBoundingBox();
						if (e !== void 0) return new U.Rect(e.x + this.dx, e.y + this.dy, e);
					}
				},
				{
					key: `toString`,
					value: function() {
						return `TranslateShape[dx:` + this.dx + `, dy:` + this.dy + `, shape:` + this.shape.toString() + `]`;
					}
				}
			]), n;
		}(Y), Y.CompositeShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).foregroundShape = e, i.backgroundShape = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						this.backgroundShape.draw(e), this.foregroundShape.draw(e);
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return U.combineRect(this.foregroundShape.getBoundingBox(), this.backgroundShape.getBoundingBox());
					}
				},
				{
					key: `toString`,
					value: function() {
						return `(` + this.foregroundShape.toString() + `, ` + this.backgroundShape.toString() + `)`;
					}
				}
			]), n;
		}(Y), Y.ChangeColorShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).color = e, i.shape = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						var t = e.createChangeColorGroup(this.color);
						this.shape.draw(t);
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return this.shape.getBoundingBox();
					}
				},
				{
					key: `toString`,
					value: function() {
						return this.shape + `, color:` + this.color;
					}
				}
			]), n;
		}(Y), Y.CircleSegmentShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r, i, a, o, s, c, l, u) {
				var d;
				return q(this, n), (d = t.call(this)).x = e, d.y = r, d.sx = i, d.sy = a, d.r = o, d.large = s, d.flip = c, d.ex = l, d.ey = u, H(K(d), `getBoundingBox`), d;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						e.createSVGElement(`path`, { d: `M` + A.measure.em2px(this.sx) + `,` + A.measure.em2px(-this.sy) + ` A` + A.measure.em2px(this.r) + `,` + A.measure.em2px(this.r) + ` 0 ` + this.large + `,` + this.flip + ` ` + A.measure.em2px(this.ex) + `,` + A.measure.em2px(-this.ey) });
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return new U.Ellipse(this.x, this.y, this.r, this.r, this.r, this.r);
					}
				},
				{
					key: `toString`,
					value: function() {
						return `CircleSegmentShape[x:` + this.x + `, y:` + this.y + `, sx:` + this.sx + `, sy:` + this.sy + `, r:` + this.r + `, large:` + this.large + `, flip:` + this.flip + `, ex:` + this.ex + `, ey:` + this.ey + `]`;
					}
				}
			]), n;
		}(Y), Y.FullCircleShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r, i) {
				var a;
				return q(this, n), (a = t.call(this)).x = e, a.y = r, a.r = i, H(K(a), `getBoundingBox`), a;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						e.createSVGElement(`circle`, {
							cx: A.measure.em2px(this.x),
							cy: A.measure.em2px(-this.y),
							r: A.measure.em2px(this.r)
						});
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return new U.Ellipse(this.x, this.y, this.r, this.r, this.r, this.r);
					}
				},
				{
					key: `toString`,
					value: function() {
						return `FullCircleShape[x:` + this.x + `, y:` + this.y + `, r:` + this.r + `]`;
					}
				}
			]), n;
		}(Y), Y.RectangleShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r, i, a, o, s, c, l, u, d, f, p) {
				var m;
				return q(this, n), (m = t.call(this)).x = e, m.y = r, m.left = i, m.right = a, m.up = o, m.down = s, m.r = c, m.isDoubled = l, m.color = u, m.dasharray = d, m.fillColor = f, m.hideLine = p || !1, H(K(m), `getBoundingBox`), m;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						var t = {
							x: A.measure.em2px(this.x - this.left),
							y: -A.measure.em2px(this.y + this.up),
							width: A.measure.em2px(this.left + this.right),
							height: A.measure.em2px(this.up + this.down),
							rx: A.measure.em2px(this.r)
						};
						this.dasharray !== void 0 && (t[`stroke-dasharray`] = this.dasharray), this.hideLine ? t.stroke = `none` : this.color !== void 0 && (t.stroke = this.color), this.fillColor !== void 0 && (t.fill = this.fillColor), e.createSVGElement(`rect`, t), this.isDoubled && (t = {
							x: A.measure.em2px(this.x - this.left + A.measure.thickness),
							y: -A.measure.em2px(this.y + this.up - A.measure.thickness),
							width: A.measure.em2px(this.left + this.right - 2 * A.measure.thickness),
							height: A.measure.em2px(this.up + this.down - 2 * A.measure.thickness),
							rx: A.measure.em2px(Math.max(this.r - A.measure.thickness, 0))
						}, this.dasharray !== void 0 && (t[`stroke-dasharray`] = this.dasharray), this.hideLine ? t.stroke = `none` : this.color !== void 0 && (t.stroke = this.color), this.fillColor !== void 0 && (t.fill = this.fillColor), e.createSVGElement(`rect`, t));
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return new U.Rect(this.x, this.y, {
							l: this.left,
							r: this.right,
							u: this.up,
							d: this.down
						});
					}
				},
				{
					key: `toString`,
					value: function() {
						return `RectangleShape[x:` + this.x + `, y:` + this.y + `, left:` + this.left + `, right:` + this.right + `, up:` + this.up + `, down:` + this.down + `, r:` + this.r + `, isDouble:` + this.isDouble + `, dasharray:` + this.dasharray + `]`;
					}
				}
			]), n;
		}(Y), Y.EllipseShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r, i, a, o, s, c, l, u) {
				var d;
				return q(this, n), (d = t.call(this)).x = e, d.y = r, d.rx = i, d.ry = a, d.isDoubled = o, d.color = s, d.dasharray = c, d.fillColor = l, d.hideLine = u || !1, H(K(d), `getBoundingBox`), d;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						var t = {
							cx: A.measure.em2px(this.x),
							cy: -A.measure.em2px(this.y),
							rx: A.measure.em2px(this.rx),
							ry: A.measure.em2px(this.ry)
						};
						this.dasharray !== void 0 && (t[`stroke-dasharray`] = this.dasharray), this.hideLine ? t.stroke = `none` : this.color !== void 0 && (t.stroke = this.color), this.fillColor !== void 0 && (t.fill = this.fillColor), e.createSVGElement(`ellipse`, t), this.isDoubled && (t = {
							cx: A.measure.em2px(this.x),
							cy: -A.measure.em2px(this.y),
							rx: A.measure.em2px(Math.max(this.rx - A.measure.thickness)),
							ry: A.measure.em2px(Math.max(this.ry - A.measure.thickness))
						}, this.dasharray !== void 0 && (t[`stroke-dasharray`] = this.dasharray), this.hideLine ? t.stroke = `none` : this.color !== void 0 && (t.stroke = this.color), this.fillColor !== void 0 && (t.fill = this.fillColor), e.createSVGElement(`ellipse`, t));
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return new U.Rect(this.x, this.y, {
							l: this.rx,
							r: this.rx,
							u: this.ry,
							d: this.ry
						});
					}
				},
				{
					key: `toString`,
					value: function() {
						return `EllipseShape[x:` + this.x + `, y:` + this.y + `, rx:` + this.rx + `, ry:` + this.ry + `, isDoubled:` + this.isDoubled + `, dasharray:` + this.dasharray + `]`;
					}
				}
			]), n;
		}(Y), Y.BoxShadeShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r, i, a, o, s, c, l) {
				var u;
				return q(this, n), (u = t.call(this)).x = e, u.y = r, u.left = i, u.right = a, u.up = o, u.down = s, u.depth = c, u.color = l || `currentColor`, H(K(u), `getBoundingBox`), u;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						var t = A.measure.em2px(this.x), n = A.measure.em2px(this.y), r = A.measure.em2px(this.left), i = A.measure.em2px(this.right), a = A.measure.em2px(this.up), o = A.measure.em2px(this.down), s = A.measure.em2px(this.depth);
						e.createSVGElement(`path`, {
							d: `M` + (t - r + s) + `,` + (-n + o) + `L` + (t + i) + `,` + (-n + o) + `L` + (t + i) + `,` + (-n - a + s) + `L` + (t + i + s) + `,` + (-n - a + s) + `L` + (t + i + s) + `,` + (-n + o + s) + `L` + (t - r + s) + `,` + (-n + o + s) + `Z`,
							stroke: this.color,
							fill: this.color
						});
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return new U.Rect(this.x, this.y, {
							l: this.left,
							r: this.right + this.depth,
							u: this.up,
							d: this.down + this.depth
						});
					}
				},
				{
					key: `toString`,
					value: function() {
						return `RectangleShape[x:` + this.x + `, y:` + this.y + `, left:` + this.left + `, right:` + this.right + `, up:` + this.up + `, down:` + this.down + `, depth:` + this.depth + `]`;
					}
				}
			]), n;
		}(Y), Y.LeftBrace = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r, i, a, o, s) {
				var c;
				return q(this, n), (c = t.call(this)).x = e, c.y = r, c.up = i, c.down = a, c.degree = o, c.color = s || `currentColor`, H(K(c), `getBoundingBox`), c;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						var t, n = A.measure.oneem, r = Math.max(1.41975, this.down / n * 1.125) - .660375, i = .660375 - Math.max(1.41975, this.up / n * 1.125);
						t = `M` + A.measure.em2px(-.0675) + ` ` + A.measure.em2px(r) + `T` + A.measure.em2px(-.068625) + ` ` + A.measure.em2px(.07875 + r) + `Q` + A.measure.em2px(-.068625) + ` ` + A.measure.em2px(.190125 + r) + ` ` + A.measure.em2px(-.0585) + ` ` + A.measure.em2px(.250875 + r) + `T` + A.measure.em2px(-.01125) + ` ` + A.measure.em2px(.387 + r) + `Q` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(.55575 + r) + ` ` + A.measure.em2px(.2475) + ` ` + A.measure.em2px(.6525 + r) + `L` + A.measure.em2px(.262125) + ` ` + A.measure.em2px(.660375 + r) + `L` + A.measure.em2px(.3015) + ` ` + A.measure.em2px(.660375 + r) + `L` + A.measure.em2px(.30825) + ` ` + A.measure.em2px(.653625 + r) + `V` + A.measure.em2px(.622125 + r) + `Q` + A.measure.em2px(.30825) + ` ` + A.measure.em2px(.60975 + r) + ` ` + A.measure.em2px(.2925) + ` ` + A.measure.em2px(.60075 + r) + `Q` + A.measure.em2px(.205875) + ` ` + A.measure.em2px(.541125 + r) + ` ` + A.measure.em2px(.149625) + ` ` + A.measure.em2px(.44775 + r) + `T` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(.239625 + r) + `Q` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(.2385 + r) + ` ` + A.measure.em2px(.073125) + ` ` + A.measure.em2px(.235125 + r) + `Q` + A.measure.em2px(.068625) + ` ` + A.measure.em2px(.203625 + r) + ` ` + A.measure.em2px(.0675) + ` ` + A.measure.em2px(.041625 + r) + `L` + A.measure.em2px(.0675) + ` ` + A.measure.em2px(.75825) + `Q` + A.measure.em2px(.0675) + ` ` + A.measure.em2px(.496125) + ` ` + A.measure.em2px(.066375) + ` ` + A.measure.em2px(.486) + `Q` + A.measure.em2px(.05625) + ` ` + A.measure.em2px(.336375) + ` ` + A.measure.em2px(-.021375) + ` ` + A.measure.em2px(.212625) + `T` + A.measure.em2px(-.226125) + ` ` + A.measure.em2px(.010125) + `L` + A.measure.em2px(-.241875) + ` 0L` + A.measure.em2px(-.226125) + ` ` + A.measure.em2px(-.010125) + `Q` + A.measure.em2px(-.106875) + ` ` + A.measure.em2px(-.084375) + ` ` + A.measure.em2px(-.025875) + ` ` + A.measure.em2px(-.207) + `T` + A.measure.em2px(.066375) + ` ` + A.measure.em2px(-.486) + `Q` + A.measure.em2px(.0675) + ` ` + A.measure.em2px(-.496125) + ` ` + A.measure.em2px(.0675) + ` ` + A.measure.em2px(-.75825) + `L` + A.measure.em2px(.0675) + ` ` + A.measure.em2px(-.041625 + i) + `Q` + A.measure.em2px(.068625) + ` ` + A.measure.em2px(-.203625 + i) + ` ` + A.measure.em2px(.073125) + ` ` + A.measure.em2px(-.235125 + i) + `Q` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(-.2385 + i) + ` ` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(-.239625 + i) + `Q` + A.measure.em2px(.093375) + ` ` + A.measure.em2px(-.354375 + i) + ` ` + A.measure.em2px(.149625) + ` ` + A.measure.em2px(-.44775 + i) + `T` + A.measure.em2px(.2925) + ` ` + A.measure.em2px(-.60075 + i) + `Q` + A.measure.em2px(.30825) + ` ` + A.measure.em2px(-.60975 + i) + ` ` + A.measure.em2px(.30825) + ` ` + A.measure.em2px(-.622125 + i) + `L` + A.measure.em2px(.30825) + ` ` + A.measure.em2px(-.653625 + i) + `L` + A.measure.em2px(.3015) + ` ` + A.measure.em2px(-.660375 + i) + `L` + A.measure.em2px(.262125) + ` ` + A.measure.em2px(-.660375 + i) + `L` + A.measure.em2px(.2475) + ` ` + A.measure.em2px(-.6525 + i) + `Q` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(-.55575 + i) + ` ` + A.measure.em2px(-.01125) + ` ` + A.measure.em2px(-.387 + i) + `Q` + A.measure.em2px(-.048375) + ` ` + A.measure.em2px(-.311625 + i) + ` ` + A.measure.em2px(-.0585) + ` ` + A.measure.em2px(-.250875 + i) + `T` + A.measure.em2px(-.068625) + ` ` + A.measure.em2px(-.07875 + i) + `Q` + A.measure.em2px(-.0675) + ` ` + A.measure.em2px(i) + ` ` + A.measure.em2px(-.0675) + ` ` + A.measure.em2px(i) + `L` + A.measure.em2px(-.0675) + ` ` + A.measure.em2px(-.759375) + `V` + A.measure.em2px(-.5985) + `Q` + A.measure.em2px(-.0675) + ` ` + A.measure.em2px(-.47925) + ` ` + A.measure.em2px(-.075375) + ` ` + A.measure.em2px(-.41175) + `T` + A.measure.em2px(-.11475) + ` ` + A.measure.em2px(-.27) + `Q` + A.measure.em2px(-.133875) + ` ` + A.measure.em2px(-.2205) + ` ` + A.measure.em2px(-.160875) + ` ` + A.measure.em2px(-.17775) + `T` + A.measure.em2px(-.212625) + ` ` + A.measure.em2px(-.106875) + `T` + A.measure.em2px(-.25875) + ` ` + A.measure.em2px(-.06075) + `T` + A.measure.em2px(-.293625) + ` ` + A.measure.em2px(-.0315) + `T` + A.measure.em2px(-.307125) + ` ` + A.measure.em2px(-.02025) + `Q` + A.measure.em2px(-.30825) + ` ` + A.measure.em2px(-.019125) + ` ` + A.measure.em2px(-.30825) + ` 0T` + A.measure.em2px(-.307125) + ` ` + A.measure.em2px(.02025) + `Q` + A.measure.em2px(-.307125) + ` ` + A.measure.em2px(.021375) + ` ` + A.measure.em2px(-.284625) + ` ` + A.measure.em2px(.03825) + `T` + A.measure.em2px(-.2295) + ` ` + A.measure.em2px(.091125) + `T` + A.measure.em2px(-.162) + ` ` + A.measure.em2px(.176625) + `T` + A.measure.em2px(-.10125) + ` ` + A.measure.em2px(.30825) + `T` + A.measure.em2px(-.068625) + ` ` + A.measure.em2px(.482625) + `Q` + A.measure.em2px(-.0675) + ` ` + A.measure.em2px(.496125) + ` ` + A.measure.em2px(-.0675) + ` ` + A.measure.em2px(.759375) + `Z`, e.createSVGElement(`path`, {
							d: t,
							fill: this.color,
							stroke: this.color,
							"stroke-width": `0pt`,
							transform: `translate(` + A.measure.em2px(this.x) + `,` + A.measure.em2px(-this.y) + `) rotate(` + -this.degree + `) scale(` + n / 1.125 + `)`
						});
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						var e = A.measure.oneem;
						return new U.Rect(this.x, this.y, {
							l: .274 * e,
							r: .274 * e,
							u: Math.max(1.41975 * e / 1.125, this.up),
							d: Math.max(1.41975 * e / 1.125, this.down)
						}).rotate(this.degree * Math.PI / 180);
					}
				},
				{
					key: `toString`,
					value: function() {
						return `LeftBrace[x:` + this.x + `, y:` + this.y + `, up:` + this.up + `, down:` + this.down + `]`;
					}
				}
			]), n;
		}(Y), Y.LeftParenthesis = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r, i, a, o) {
				var s;
				return q(this, n), (s = t.call(this)).x = e, s.y = r, s.height = i, s.degree = a, s.color = o || `currentColor`, H(K(s), `getBoundingBox`), s;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						var t, n = A.measure.oneem, r = Math.max(.660375, this.height / 2 / n * 1.125) - .660375, i = -r;
						t = `M` + A.measure.em2px(-.0675) + ` ` + A.measure.em2px(r) + `T` + A.measure.em2px(-.068625) + ` ` + A.measure.em2px(.07875 + r) + `Q` + A.measure.em2px(-.068625) + ` ` + A.measure.em2px(.190125 + r) + ` ` + A.measure.em2px(-.0585) + ` ` + A.measure.em2px(.250875 + r) + `T` + A.measure.em2px(-.01125) + ` ` + A.measure.em2px(.387 + r) + `Q` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(.55575 + r) + ` ` + A.measure.em2px(.2475) + ` ` + A.measure.em2px(.6525 + r) + `L` + A.measure.em2px(.262125) + ` ` + A.measure.em2px(.660375 + r) + `L` + A.measure.em2px(.3015) + ` ` + A.measure.em2px(.660375 + r) + `L` + A.measure.em2px(.30825) + ` ` + A.measure.em2px(.653625 + r) + `V` + A.measure.em2px(.622125 + r) + `Q` + A.measure.em2px(.30825) + ` ` + A.measure.em2px(.60975 + r) + ` ` + A.measure.em2px(.2925) + ` ` + A.measure.em2px(.60075 + r) + `Q` + A.measure.em2px(.205875) + ` ` + A.measure.em2px(.541125 + r) + ` ` + A.measure.em2px(.149625) + ` ` + A.measure.em2px(.44775 + r) + `T` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(.239625 + r) + `Q` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(.2385 + r) + ` ` + A.measure.em2px(.073125) + ` ` + A.measure.em2px(.235125 + r) + `Q` + A.measure.em2px(.068625) + ` ` + A.measure.em2px(.203625 + r) + ` ` + A.measure.em2px(.0675) + ` ` + A.measure.em2px(.041625 + r) + `L` + A.measure.em2px(.0675) + ` ` + A.measure.em2px(-.041625 + i) + `Q` + A.measure.em2px(.068625) + ` ` + A.measure.em2px(-.203625 + i) + ` ` + A.measure.em2px(.073125) + ` ` + A.measure.em2px(-.235125 + i) + `Q` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(-.2385 + i) + ` ` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(-.239625 + i) + `Q` + A.measure.em2px(.093375) + ` ` + A.measure.em2px(-.354375 + i) + ` ` + A.measure.em2px(.149625) + ` ` + A.measure.em2px(-.44775 + i) + `T` + A.measure.em2px(.2925) + ` ` + A.measure.em2px(-.60075 + i) + `Q` + A.measure.em2px(.30825) + ` ` + A.measure.em2px(-.60975 + i) + ` ` + A.measure.em2px(.30825) + ` ` + A.measure.em2px(-.622125 + i) + `L` + A.measure.em2px(.30825) + ` ` + A.measure.em2px(-.653625 + i) + `L` + A.measure.em2px(.3015) + ` ` + A.measure.em2px(-.660375 + i) + `L` + A.measure.em2px(.262125) + ` ` + A.measure.em2px(-.660375 + i) + `L` + A.measure.em2px(.2475) + ` ` + A.measure.em2px(-.6525 + i) + `Q` + A.measure.em2px(.07425) + ` ` + A.measure.em2px(-.55575 + i) + ` ` + A.measure.em2px(-.01125) + ` ` + A.measure.em2px(-.387 + i) + `Q` + A.measure.em2px(-.048375) + ` ` + A.measure.em2px(-.311625 + i) + ` ` + A.measure.em2px(-.0585) + ` ` + A.measure.em2px(-.250875 + i) + `T` + A.measure.em2px(-.068625) + ` ` + A.measure.em2px(-.07875 + i) + `Q` + A.measure.em2px(-.0675) + ` ` + A.measure.em2px(i) + ` ` + A.measure.em2px(-.0675) + ` ` + A.measure.em2px(i) + `Z`, e.createSVGElement(`path`, {
							d: t,
							fill: this.color,
							stroke: this.color,
							"stroke-width": `0pt`,
							transform: `translate(` + A.measure.em2px(this.x) + `,` + A.measure.em2px(-this.y) + `) rotate(` + -this.degree + `) scale(` + n / 1.125 + `)`
						});
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						var e = A.measure.oneem;
						return new U.Rect(this.x, this.y, {
							l: .06 * e,
							r: .274 * e,
							u: Math.max(.660375 * e / 1.125, this.height / 2),
							d: Math.max(.660375 * e / 1.125, this.height / 2)
						}).rotate(this.degree * Math.PI / 180);
					}
				},
				{
					key: `toString`,
					value: function() {
						return `LeftBrace[x:` + this.x + `, y:` + this.y + `, up:` + this.up + `, down:` + this.down + `]`;
					}
				}
			]), n;
		}(Y), Y.TextShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.math = r, i.originalBBox = void 0, H(K(i), `getBoundingBox`), H(K(i), `getOriginalReferencePoint`), i;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						this._draw(e, !1);
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return this._draw(A.svgForTestLayout, !0);
					}
				},
				{
					key: `_draw`,
					value: function(e, t) {
						return e.xypicWrapper.drawTextObject(this, e, t);
					}
				},
				{
					key: `getOriginalReferencePoint`,
					value: function() {
						this.getBoundingBox();
						var e = this.originalBBox, t = this.c, n = e.H, r = e.D;
						return new U.Point(t.x, t.y - (n - r) / 2);
					}
				},
				{
					key: `toString`,
					value: function() {
						return `TextShape[c:` + this.c.toString() + `, math:` + this.math.toString() + `]`;
					}
				}
			]), n;
		}(Y), Y.ImageShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.url = r, H(K(i), `getBoundingBox`), H(K(i), `getOriginalReferencePoint`), i;
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						var t = this.c;
						e.createSVGElement(`image`, {
							x: A.measure.em2px(t.x - t.l),
							y: A.measure.em2px(-t.y - t.u),
							width: A.measure.em2px(t.l + t.r),
							height: A.measure.em2px(t.u + t.d),
							preserveAspectRatio: `none`,
							"xlink:href": this.url
						});
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return this.c;
					}
				},
				{
					key: `getOriginalReferencePoint`,
					value: function() {
						return this.c;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `ImageShape[c:` + this.c.toString() + `, height:` + this.height + `, width:` + this.width + `, url:` + this.url + `]`;
					}
				}
			]), n;
		}(Y), Y.ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n() {
				return q(this, n), t.call(this);
			}
			return J(n, [
				{
					key: `draw`,
					value: function(e) {
						var t = e.createGroup(e.transformBuilder().translate(this.c.x, this.c.y).rotateRadian(this.angle));
						this.drawDelegate(t);
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return this.c.toRect(this.getBox()).rotate(this.angle);
					}
				},
				{
					key: `toString`,
					value: function() {
						return `ArrowheadShape[c:` + this.c.toString() + `, angle:` + this.angle + `]`;
					}
				}
			]), n;
		}(Y), Y.GT2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `getBox`,
					value: function() {
						var e = A.measure.oneem;
						return {
							l: .456 * e,
							r: 0,
							d: .229 * e,
							u: .229 * e
						};
					}
				},
				{
					key: `getRadius`,
					value: function() {
						return .213 * A.measure.oneem;
					}
				},
				{
					key: `drawDelegate`,
					value: function(e) {
						var t = A.measure.oneem, n = e.createGroup(e.transformBuilder().rotateDegree(-10)), r = e.createGroup(e.transformBuilder().rotateDegree(10));
						n.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) }), r.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) });
					}
				}
			]), n;
		}(Y.ArrowheadShape), Y.GT3ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `getBox`,
					value: function() {
						var e = A.measure.oneem;
						return {
							l: .507 * e,
							r: 0,
							d: .268 * e,
							u: .268 * e
						};
					}
				},
				{
					key: `getRadius`,
					value: function() {
						return .325 * A.measure.oneem;
					}
				},
				{
					key: `drawDelegate`,
					value: function(e) {
						var t = A.measure.oneem, n = e.createGroup(e.transformBuilder().rotateDegree(-15)), r = e.createGroup(e.transformBuilder().rotateDegree(15));
						n.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`line`, {
							x1: 0,
							y1: 0,
							x2: A.measure.em2px(-.507 * t),
							y2: 0
						}), r.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) });
					}
				}
			]), n;
		}(Y.ArrowheadShape), Y.UpperGTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: .489 * e,
						r: 0,
						d: 0,
						u: .147 * e
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem;
					e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerGTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: .489 * e,
						r: 0,
						d: .147 * e,
						u: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem;
					e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.GTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: .489 * e,
						r: 0,
						d: .147 * e,
						u: .147 * e
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem;
					e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LT2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `getBox`,
					value: function() {
						var e = A.measure.oneem;
						return {
							l: 0,
							r: .456 * e,
							d: .229 * e,
							u: .229 * e
						};
					}
				},
				{
					key: `getRadius`,
					value: function() {
						return .213 * A.measure.oneem;
					}
				},
				{
					key: `drawDelegate`,
					value: function(e) {
						var t = A.measure.oneem, n = e.createGroup(e.transformBuilder().rotateDegree(10)), r = e.createGroup(e.transformBuilder().rotateDegree(-10));
						n.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) }), r.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
					}
				}
			]), n;
		}(Y.ArrowheadShape), Y.LT3ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `getBox`,
					value: function() {
						var e = A.measure.oneem;
						return {
							l: 0,
							r: .507 * e,
							d: .268 * e,
							u: .268 * e
						};
					}
				},
				{
					key: `getRadius`,
					value: function() {
						return .325 * A.measure.oneem;
					}
				},
				{
					key: `drawDelegate`,
					value: function(e) {
						var t = A.measure.oneem, n = e.createGroup(e.transformBuilder().rotateDegree(15)), r = e.createGroup(e.transformBuilder().rotateDegree(-15));
						n.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`line`, {
							x1: 0,
							y1: 0,
							x2: A.measure.em2px(.507 * t),
							y2: 0
						}), r.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
					}
				}
			]), n;
		}(Y.ArrowheadShape), Y.UpperLTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: 0,
						r: .489 * e,
						d: 0,
						u: .147 * e
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem;
					e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerLTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: 0,
						r: .489 * e,
						d: .147 * e,
						u: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem;
					e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: 0,
						r: .489 * e,
						d: .147 * e,
						u: .147 * e
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem;
					e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.UpperColumnArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: 0,
						u: A.measure.lineElementLength,
						d: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: 0,
						y2: -t
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerColumnArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: 0,
						u: 0,
						d: A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: 0,
						y2: t
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.Column2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: 0,
						u: .5 * (A.measure.lineElementLength + A.measure.thickness),
						d: .5 * (A.measure.lineElementLength + A.measure.thickness)
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(.5 * (A.measure.lineElementLength + A.measure.thickness));
					e.createSVGElement(`line`, {
						x1: 0,
						y1: t,
						x2: 0,
						y2: -t
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.Column3ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: 0,
						u: .5 * A.measure.lineElementLength + A.measure.thickness,
						d: .5 * A.measure.lineElementLength + A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(.5 * A.measure.lineElementLength + A.measure.thickness);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: t,
						x2: 0,
						y2: -t
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.ColumnArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: 0,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: t,
						x2: 0,
						y2: -t
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.UpperLParenArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: .5 * A.measure.lineElementLength,
						r: 0,
						u: A.measure.lineElementLength,
						d: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`path`, { d: `M0,0 A ` + t + `,` + t + ` 0 0,1 0,` + -2 * t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerLParenArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: .5 * A.measure.lineElementLength,
						r: 0,
						u: 0,
						d: A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`path`, { d: `M0,0 A ` + t + `,` + t + ` 0 0,0 0,` + 2 * t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LParenArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: .5 * A.measure.lineElementLength,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`path`, { d: `M` + t + `,` + -t + ` A ` + t + `,` + t + ` 0 0,0 ` + t + `,` + t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.UpperRParenArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: .5 * A.measure.lineElementLength,
						u: A.measure.lineElementLength,
						d: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`path`, { d: `M0,0 A ` + t + `,` + t + ` 0 0,0 0,` + -2 * t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerRParenArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: .5 * A.measure.lineElementLength,
						u: 0,
						d: A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`path`, { d: `M0,0 A ` + t + `,` + t + ` 0 0,1 0,` + 2 * t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.RParenArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: .5 * A.measure.lineElementLength,
						r: 0,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`path`, { d: `M` + -t + `,` + -t + ` A ` + t + `,` + t + ` 0 0,1 ` + -t + `,` + t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerBackquoteArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: .5 * A.measure.lineElementLength,
						r: 0,
						u: 0,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`path`, { d: `M0,0 A ` + t + `,` + t + ` 0 0,0 ` + -t + `,` + t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.UpperBackquoteArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: .5 * A.measure.lineElementLength,
						r: 0,
						u: .5 * A.measure.lineElementLength,
						d: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`path`, { d: `M0,0 A ` + t + `,` + t + ` 0 0,1 ` + -t + `,` + -t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerQuoteArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: .5 * A.measure.lineElementLength,
						u: 0,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`path`, { d: `M0,0 A ` + t + `,` + t + ` 0 0,1 ` + t + `,` + t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.UpperQuoteArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: .5 * A.measure.lineElementLength,
						u: .5 * A.measure.lineElementLength,
						d: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`path`, { d: `M0,0 A ` + t + `,` + t + ` 0 0,0 ` + t + `,` + -t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.AsteriskArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = 0, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: A.measure.thickness,
						r: A.measure.thickness,
						u: A.measure.thickness,
						d: A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					e.createSVGElement(`circle`, {
						cx: 0,
						cy: 0,
						r: A.measure.em2px(A.measure.thickness),
						fill: `currentColor`
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.OArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = 0, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: A.measure.thickness,
						r: A.measure.thickness,
						u: A.measure.thickness,
						d: A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					e.createSVGElement(`circle`, {
						cx: 0,
						cy: 0,
						r: A.measure.em2px(A.measure.thickness)
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.PlusArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: .5 * A.measure.lineElementLength,
						r: .5 * A.measure.lineElementLength,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.lineElementLength / 2, n = A.measure.em2px(t);
					e.createSVGElement(`line`, {
						x1: -n,
						y1: 0,
						x2: n,
						y2: 0
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: n,
						x2: 0,
						y2: -n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.XArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r + Math.PI / 4, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: .5 * A.measure.lineElementLength,
						r: .5 * A.measure.lineElementLength,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.lineElementLength / 2, n = A.measure.em2px(t);
					e.createSVGElement(`line`, {
						x1: -n,
						y1: 0,
						x2: n,
						y2: 0
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: n,
						x2: 0,
						y2: -n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.SlashArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r - Math.PI / 10, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: 0,
						u: A.measure.lineElementLength / 2,
						d: A.measure.lineElementLength / 2
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.lineElementLength / 2, n = A.measure.em2px(t);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: n,
						x2: 0,
						y2: -n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.Line3ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: A.measure.lineElementLength,
						u: A.measure.thickness,
						d: A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(A.measure.lineElementLength), n = A.measure.em2px(A.measure.thickness);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: n,
						x2: t,
						y2: n
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: t,
						y2: 0
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: -n,
						x2: t,
						y2: -n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.Line2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: A.measure.lineElementLength,
						u: .5 * A.measure.thickness,
						d: .5 * A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(.5 * A.measure.thickness), n = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: t,
						x2: n,
						y2: t
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: -t,
						x2: n,
						y2: -t
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LineArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: A.measure.lineElementLength,
						u: 0,
						d: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: t,
						y2: 0
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.Dot3ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: 0,
						u: A.measure.thickness,
						d: A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.oneem;
					var t = A.measure.em2px(A.measure.thickness), n = A.measure.em2px(A.measure.thickness), r = A.measure.dottedDasharray;
					e.createSVGElement(`line`, {
						x1: 0,
						y1: t,
						x2: n,
						y2: t,
						"stroke-dasharray": r
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: n,
						y2: 0,
						"stroke-dasharray": r
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: -t,
						x2: n,
						y2: -t,
						"stroke-dasharray": r
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.Dot2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: 0,
						u: .5 * A.measure.thickness,
						d: .5 * A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(.5 * A.measure.thickness), n = A.measure.em2px(A.measure.thickness), r = A.measure.dottedDasharray;
					e.createSVGElement(`line`, {
						x1: 0,
						y1: t,
						x2: n,
						y2: t,
						"stroke-dasharray": r
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: -t,
						x2: n,
						y2: -t,
						"stroke-dasharray": r
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.DotArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: 0,
						u: 0,
						d: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.oneem;
					var t = A.measure.em2px(A.measure.thickness), n = A.measure.dottedDasharray;
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: t,
						y2: 0,
						"stroke-dasharray": n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.Tilde3ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: -2 * A.measure.thickness,
						r: 2 * A.measure.thickness,
						u: 2 * A.measure.thickness,
						d: 2 * A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(A.measure.thickness);
					e.createSVGElement(`path`, { d: `M` + -2 * t + `,` + t + ` Q` + -t + `,0 0,` + t + ` T` + 2 * t + `,` + t + `M` + -2 * t + `,0 Q` + -t + `,` + -t + ` 0,0 T` + 2 * t + `,0M` + -2 * t + `,` + -t + ` Q` + -t + `,` + -2 * t + ` 0,` + -t + ` T` + 2 * t + `,` + -t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.Tilde2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: -2 * A.measure.thickness,
						r: 2 * A.measure.thickness,
						u: 1.5 * A.measure.thickness,
						d: 1.5 * A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(A.measure.thickness);
					e.createSVGElement(`path`, { d: `M` + -2 * t + `,` + .5 * t + ` Q` + -t + `,` + -.5 * t + ` 0,` + .5 * t + ` T` + 2 * t + `,` + .5 * t + `M` + -2 * t + `,` + -.5 * t + ` Q` + -t + `,` + -1.5 * t + ` 0,` + -.5 * t + ` T` + 2 * t + `,` + -.5 * t });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.TildeArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: -2 * A.measure.thickness,
						r: 2 * A.measure.thickness,
						u: A.measure.thickness,
						d: A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(A.measure.thickness);
					e.createSVGElement(`path`, { d: `M` + -2 * t + `,0 Q` + -t + `,` + -t + ` 0,0 T` + 2 * t + `,0` });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.TildeArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: -2 * A.measure.thickness,
						r: 2 * A.measure.thickness,
						u: A.measure.thickness,
						d: A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(A.measure.thickness);
					e.createSVGElement(`path`, { d: `M` + -2 * t + `,0 Q` + -t + `,` + -t + ` 0,0 T` + 2 * t + `,0` });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.GTGTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: .489 * e + 2 * A.measure.thickness,
						r: 0,
						d: .147 * e,
						u: .147 * e
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem, n = A.measure.thickness, r = A.measure.em2px(2 * n);
					e.createSVGElement(`path`, { d: `M` + -r + `,0 Q` + (A.measure.em2px(-.222 * t) - r) + `,` + A.measure.em2px(.02 * t) + ` ` + (A.measure.em2px(-.489 * t) - r) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M` + -r + `,0 Q` + (A.measure.em2px(-.222 * t) - r) + `,` + A.measure.em2px(-.02 * t) + ` ` + (A.measure.em2px(-.489 * t) - r) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.UpperGTGTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: .489 * e + 2 * A.measure.thickness,
						r: 0,
						d: 0,
						u: .147 * e
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem, n = A.measure.thickness, r = A.measure.em2px(2 * n);
					e.createSVGElement(`path`, { d: `M` + -r + `,0 Q` + (A.measure.em2px(-.222 * t) - r) + `,` + A.measure.em2px(-.02 * t) + ` ` + (A.measure.em2px(-.489 * t) - r) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerGTGTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: .489 * e + 2 * A.measure.thickness,
						r: 0,
						d: .147 * e,
						u: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem, n = A.measure.thickness, r = A.measure.em2px(2 * n);
					e.createSVGElement(`path`, { d: `M` + -r + `,0 Q` + (A.measure.em2px(-.222 * t) - r) + `,` + A.measure.em2px(.02 * t) + ` ` + (A.measure.em2px(-.489 * t) - r) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.GTGT2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `getBox`,
					value: function() {
						var e = A.measure.oneem;
						return {
							l: .456 * e + 2 * A.measure.thickness,
							r: 0,
							d: .229 * e,
							u: .229 * e
						};
					}
				},
				{
					key: `getRadius`,
					value: function() {
						return .213 * A.measure.oneem;
					}
				},
				{
					key: `drawDelegate`,
					value: function(e) {
						var t = A.measure.oneem, n = A.measure.thickness, r = e.createGroup(e.transformBuilder().rotateDegree(-10)), i = e.createGroup(e.transformBuilder().rotateDegree(10));
						r.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) }), i.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) });
						var a = e.createGroup(e.transformBuilder().translate(-2 * n, 0).rotateDegree(-10)), o = e.createGroup(e.transformBuilder().translate(-2 * n, 0).rotateDegree(10));
						a.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) }), o.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) });
					}
				}
			]), n;
		}(Y.ArrowheadShape), Y.GTGT3ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `getBox`,
					value: function() {
						var e = A.measure.oneem;
						return {
							l: .507 * e + 2 * A.measure.thickness,
							r: 0,
							d: .268 * e,
							u: .268 * e
						};
					}
				},
				{
					key: `getRadius`,
					value: function() {
						return .325 * A.measure.oneem;
					}
				},
				{
					key: `drawDelegate`,
					value: function(e) {
						var t = A.measure.oneem, n = A.measure.thickness, r = e.createGroup(e.transformBuilder().rotateDegree(-15)), i = e.createGroup(e.transformBuilder().rotateDegree(15));
						r.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) }), i.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) });
						var a = e.createGroup(e.transformBuilder().translate(-2 * n, 0).rotateDegree(-15)), o = e.createGroup(e.transformBuilder().translate(-2 * n, 0).rotateDegree(15));
						a.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) }), o.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`line`, {
							x1: 0,
							y1: 0,
							x2: A.measure.em2px(-.507 * t - 2 * n),
							y2: 0
						});
					}
				}
			]), n;
		}(Y.ArrowheadShape), Y.LTLTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: 0,
						r: .489 * e + 2 * A.measure.thickness,
						d: .147 * e,
						u: .147 * e
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem, n = A.measure.thickness, r = A.measure.em2px(2 * n);
					e.createSVGElement(`path`, { d: `M` + r + `,0 Q` + (A.measure.em2px(.222 * t) + r) + `,` + A.measure.em2px(-.02 * t) + ` ` + (A.measure.em2px(.489 * t) + r) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`path`, { d: `M` + r + `,0 Q` + (A.measure.em2px(.222 * t) + r) + `,` + A.measure.em2px(.02 * t) + ` ` + (A.measure.em2px(.489 * t) + r) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.UpperLTLTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: 0,
						r: .489 * e + 2 * A.measure.thickness,
						d: 0,
						u: .147 * e
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem, n = A.measure.thickness, r = A.measure.em2px(2 * n);
					e.createSVGElement(`path`, { d: `M` + r + `,0 Q` + (A.measure.em2px(.222 * t) + r) + `,` + A.measure.em2px(-.02 * t) + ` ` + (A.measure.em2px(.489 * t) + r) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerLTLTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					var e = A.measure.oneem;
					return {
						l: 0,
						r: .489 * e + 2 * A.measure.thickness,
						d: .147 * e,
						u: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem, n = A.measure.thickness, r = A.measure.em2px(2 * n);
					e.createSVGElement(`path`, { d: `M` + r + `,0 Q` + (A.measure.em2px(.222 * t) + r) + `,` + A.measure.em2px(.02 * t) + ` ` + (A.measure.em2px(.489 * t) + r) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LTLT2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `getBox`,
					value: function() {
						var e = A.measure.oneem;
						return {
							l: 0,
							r: .456 + e + 2 * A.measure.thickness,
							d: .229 * e,
							u: .229 * e
						};
					}
				},
				{
					key: `getRadius`,
					value: function() {
						return .213 * A.measure.oneem;
					}
				},
				{
					key: `drawDelegate`,
					value: function(e) {
						var t = A.measure.oneem, n = A.measure.thickness, r = e.createGroup(e.transformBuilder().translate(2 * n, 0).rotateDegree(10)), i = e.createGroup(e.transformBuilder().translate(2 * n, 0).rotateDegree(-10));
						r.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) }), i.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
						var a = e.createGroup(e.transformBuilder().rotateDegree(10)), o = e.createGroup(e.transformBuilder().rotateDegree(-10));
						a.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) }), o.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
					}
				}
			]), n;
		}(Y.ArrowheadShape), Y.LTLT3ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `getBox`,
					value: function() {
						var e = A.measure.oneem;
						return {
							l: 0,
							r: .507 * e + 2 * A.measure.thickness,
							d: .268 * e,
							u: .268 * e
						};
					}
				},
				{
					key: `getRadius`,
					value: function() {
						return .325 * A.measure.oneem;
					}
				},
				{
					key: `drawDelegate`,
					value: function(e) {
						var t = A.measure.oneem, n = A.measure.thickness, r = e.createGroup(e.transformBuilder().translate(2 * n, 0).rotateDegree(15)), i = e.createGroup(e.transformBuilder().translate(2 * n, 0).rotateDegree(-15));
						r.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) }), i.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
						var a = e.createGroup(e.transformBuilder().rotateDegree(15)), o = e.createGroup(e.transformBuilder().rotateDegree(-15));
						a.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) }), o.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`line`, {
							x1: 0,
							y1: 0,
							x2: A.measure.em2px(.507 * t + 2 * n),
							y2: 0
						});
					}
				}
			]), n;
		}(Y.ArrowheadShape), Y.ColumnColumnArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: A.measure.thickness,
						r: 0,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.thickness, n = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: n,
						x2: 0,
						y2: -n
					}), e.createSVGElement(`line`, {
						x1: -A.measure.em2px(t),
						y1: n,
						x2: -A.measure.em2px(t),
						y2: -n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.UpperColumnColumnArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: A.measure.thickness,
						r: 0,
						u: A.measure.lineElementLength,
						d: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.thickness, n = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: 0,
						y2: -n
					}), e.createSVGElement(`line`, {
						x1: -A.measure.em2px(t),
						y1: 0,
						x2: -A.measure.em2px(t),
						y2: -n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerColumnColumnArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: A.measure.thickness,
						r: 0,
						u: 0,
						d: A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.thickness, n = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: 0,
						y2: n
					}), e.createSVGElement(`line`, {
						x1: -A.measure.em2px(t),
						y1: 0,
						x2: -A.measure.em2px(t),
						y2: n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.ColumnColumn2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: A.measure.thickness,
						r: 0,
						u: .5 * (A.measure.lineElementLength + A.measure.thickness),
						d: .5 * (A.measure.lineElementLength + A.measure.thickness)
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.thickness, n = A.measure.em2px(.5 * (A.measure.lineElementLength + A.measure.thickness));
					e.createSVGElement(`line`, {
						x1: 0,
						y1: n,
						x2: 0,
						y2: -n
					}), e.createSVGElement(`line`, {
						x1: -A.measure.em2px(t),
						y1: n,
						x2: -A.measure.em2px(t),
						y2: -n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.ColumnColumn3ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: A.measure.thickness,
						r: 0,
						u: .5 * A.measure.lineElementLength + A.measure.thickness,
						d: .5 * A.measure.lineElementLength + A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.thickness, n = (t = A.measure.thickness, A.measure.em2px(.5 * A.measure.lineElementLength + A.measure.thickness));
					e.createSVGElement(`line`, {
						x1: 0,
						y1: n,
						x2: 0,
						y2: -n
					}), e.createSVGElement(`line`, {
						x1: -A.measure.em2px(t),
						y1: n,
						x2: -A.measure.em2px(t),
						y2: -n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.ColumnLineArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: A.measure.lineElementLength,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: t,
						x2: 0,
						y2: -t
					});
					var n = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: n,
						y2: 0
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.UpperColumnLineArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: A.measure.lineElementLength,
						u: A.measure.lineElementLength,
						d: 0
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: 0,
						y2: -t
					});
					var n = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: n,
						y2: 0
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LowerColumnLineArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: A.measure.lineElementLength,
						u: 0,
						d: A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.thickness;
					var t = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: 0,
						y2: t
					});
					var n = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: n,
						y2: 0
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.ColumnLine2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: A.measure.lineElementLength,
						u: .5 * (A.measure.lineElementLength + A.measure.thickness),
						d: .5 * (A.measure.lineElementLength + A.measure.thickness)
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.thickness, n = A.measure.em2px(.5 * (A.measure.lineElementLength + A.measure.thickness));
					e.createSVGElement(`line`, {
						x1: 0,
						y1: -n,
						x2: 0,
						y2: n
					});
					var r = A.measure.em2px(.5 * t), i = A.measure.em2px(A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: r,
						x2: i,
						y2: r
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: -r,
						x2: i,
						y2: -r
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.ColumnLine3ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: A.measure.lineElementLength,
						u: .5 * A.measure.lineElementLength + A.measure.thickness,
						d: .5 * A.measure.lineElementLength + A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.thickness, n = A.measure.em2px(.5 * A.measure.lineElementLength + A.measure.thickness);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: -n,
						x2: 0,
						y2: n
					});
					var r = A.measure.em2px(A.measure.lineElementLength), i = A.measure.em2px(t);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: i,
						x2: r,
						y2: i
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: 0,
						x2: r,
						y2: 0
					}), e.createSVGElement(`line`, {
						x1: 0,
						y1: -i,
						x2: r,
						y2: -i
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.GTColumnArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: .489 * A.measure.oneem,
						r: 0,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem, n = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: n,
						x2: 0,
						y2: -n
					}), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.GTGTColumnArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: .489 * A.measure.oneem + 2 * A.measure.thickness,
						r: 0,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem, n = A.measure.thickness, r = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: r,
						x2: 0,
						y2: -r
					});
					var i = A.measure.em2px(2 * n);
					e.createSVGElement(`path`, { d: `M` + -i + `,0 Q` + (A.measure.em2px(-.222 * t) - i) + `,` + A.measure.em2px(.02 * t) + ` ` + (A.measure.em2px(-.489 * t) - i) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M` + -i + `,0 Q` + (A.measure.em2px(-.222 * t) - i) + `,` + A.measure.em2px(-.02 * t) + ` ` + (A.measure.em2px(-.489 * t) - i) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.ColumnLTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: .489 * A.measure.oneem,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem, n = (A.measure.thickness, A.measure.em2px(.5 * A.measure.lineElementLength));
					e.createSVGElement(`line`, {
						x1: 0,
						y1: n,
						x2: 0,
						y2: -n
					}), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.ColumnLTLTArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: 0,
						r: .489 * A.measure.oneem + 2 * A.measure.thickness,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.oneem, n = A.measure.thickness, r = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: r,
						x2: 0,
						y2: -r
					});
					var i = A.measure.em2px(2 * n);
					e.createSVGElement(`path`, { d: `M` + i + `,0 Q` + (A.measure.em2px(.222 * t) + i) + `,` + A.measure.em2px(-.02 * t) + ` ` + (A.measure.em2px(.489 * t) + i) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`path`, { d: `M` + i + `,0 Q` + (A.measure.em2px(.222 * t) + i) + `,` + A.measure.em2px(.02 * t) + ` ` + (A.measure.em2px(.489 * t) + i) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(-.147 * t) }), e.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(.489 * t) + `,` + A.measure.em2px(.147 * t) });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.SlashSlashArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r - Math.PI / 10, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return {
						l: A.measure.thickness,
						r: 0,
						u: .5 * A.measure.lineElementLength,
						d: .5 * A.measure.lineElementLength
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					var t = A.measure.em2px(A.measure.thickness), n = A.measure.em2px(.5 * A.measure.lineElementLength);
					e.createSVGElement(`line`, {
						x1: 0,
						y1: n,
						x2: 0,
						y2: -n
					}), e.createSVGElement(`line`, {
						x1: -t,
						y1: n,
						x2: -t,
						y2: -n
					});
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LineGT2ArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [
				{
					key: `getBox`,
					value: function() {
						var e = A.measure.oneem;
						return {
							l: A.measure.lineElementLength,
							r: A.measure.lineElementLength,
							d: .229 * e,
							u: .229 * e
						};
					}
				},
				{
					key: `getRadius`,
					value: function() {
						return .213 * A.measure.oneem;
					}
				},
				{
					key: `drawDelegate`,
					value: function(e) {
						var t = A.measure.oneem, n = A.measure.lineElementLength, r = A.measure.em2px(n), i = .5 * A.measure.thickness, a = A.measure.em2px(i), o = this.getRadius(), s = A.measure.em2px(Math.sqrt(o * o - i * i)), c = e.createGroup(e.transformBuilder().translate(n, 0).rotateDegree(-10)), l = e.createGroup(e.transformBuilder().translate(n, 0).rotateDegree(10));
						c.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(-.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(-.147 * t) }), l.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-.222 * t) + `,` + A.measure.em2px(.02 * t) + ` ` + A.measure.em2px(-.489 * t) + `,` + A.measure.em2px(.147 * t) }), e.createSVGElement(`path`, { d: `M` + -r + `,` + a + ` L` + (r - s) + `,` + a + ` M` + -r + `,` + -a + ` L` + (r - s) + `,` + -a });
					}
				}
			]), n;
		}(Y.ArrowheadShape), Y.TwocellEqualityArrowheadShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r) {
				var i;
				return q(this, n), (i = t.call(this)).c = e, i.angle = r, H(K(i), `getBoundingBox`), i;
			}
			return J(n, [{
				key: `getBox`,
				value: function() {
					return A.measure.oneem, {
						l: A.measure.lineElementLength,
						r: A.measure.lineElementLength,
						d: .5 * A.measure.thickness,
						u: .5 * A.measure.thickness
					};
				}
			}, {
				key: `drawDelegate`,
				value: function(e) {
					A.measure.oneem;
					var t = A.measure.em2px(A.measure.lineElementLength), n = A.measure.em2px(.5 * A.measure.thickness);
					e.createSVGElement(`path`, { d: `M` + -t + `,` + n + ` L` + t + `,` + n + ` M` + -t + `,` + -n + ` L` + t + `,` + -n });
				}
			}]), n;
		}(Y.ArrowheadShape), Y.LineShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r, i, a, o) {
				var s;
				return q(this, n), (s = t.call(this)).line = e, s.object = r, s.main = i, s.variant = a, s.bbox = o, s.holeRanges = O.empty, s;
			}
			return J(n, [
				{
					key: `sliceHole`,
					value: function(e) {
						this.holeRanges = this.holeRanges.prepend(e);
					}
				},
				{
					key: `draw`,
					value: function(e) {
						this.line.drawLine(e, this.object, this.main, this.variant, this.holeRanges);
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return this.bbox;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `LineShape[line:` + this.line + `, object:` + this.object + `, main:` + this.main + `, variant:` + this.variant + `]`;
					}
				}
			]), n;
		}(Y), Y.CurveShape = function(e) {
			W(n, e);
			var t = G(n);
			function n(e, r, i, a) {
				var o;
				return q(this, n), (o = t.call(this)).curve = e, o.objectForDrop = r, o.objectForConnect = i, o.bbox = a, o.holeRanges = O.empty, o;
			}
			return J(n, [
				{
					key: `sliceHole`,
					value: function(e) {
						this.holeRanges = this.holeRanges.prepend(e);
					}
				},
				{
					key: `draw`,
					value: function(e) {
						this.curve.drawCurve(e, this.objectForDrop, this.objectForConnect, this.holeRanges);
					}
				},
				{
					key: `getBoundingBox`,
					value: function() {
						return this.bbox;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `CurveShape[curve` + this.curve + `, objectForDrop:` + (this.objectForDrop === void 0 ? `null` : this.objectForDrop.toString()) + `, objectForConnect:` + (this.objectForConnect === void 0 ? `null` : this.objectForConnect.toString()) + `]`;
					}
				}
			]), n;
		}(Y);
		var bt = function() {
			function e(t, n) {
				(function(e, t) {
					if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
				})(this, e), t > n ? (this.start = n, this.end = t) : (this.start = t, this.end = n);
			}
			var t, n, r;
			return t = e, (n = [
				{
					key: `difference`,
					value: function(t) {
						var n = O.empty, r = this.start, i = this.end, a = t.start, o = t.end;
						return i <= a || o <= r ? n = n.prepend(this) : r < a ? n = i <= o ? n.prepend(new e(r, a)) : (n = n.prepend(new e(r, a))).prepend(new e(o, i)) : o < i && (n = n.prepend(new e(o, i))), n;
					}
				},
				{
					key: `differenceRanges`,
					value: function(e) {
						var t = O.empty.prepend(this);
						return e.foreach((function(e) {
							t = t.flatMap((function(t) {
								return t.difference(e);
							}));
						})), t;
					}
				},
				{
					key: `toString`,
					value: function() {
						return `[` + this.start + `, ` + this.end + `]`;
					}
				}
			]) && yt(t.prototype, n), r && yt(t, r), e;
		}();
		function xt(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		var St = function() {
			function e(t, n) {
				(function(e, t) {
					if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
				})(this, e), this.shape = t, this.env = n;
			}
			var t, n, r;
			return t = e, (n = [
				{
					key: `duplicateEnv`,
					value: function() {
						var t = this.env.duplicate();
						return new e(this.shape, t);
					}
				},
				{
					key: `appendShapeToFront`,
					value: function(e) {
						e.isNone || (this.shape.isNone ? this.shape = e : this.shape = new Y.CompositeShape(e, this.shape));
					}
				},
				{
					key: `appendShapeToBack`,
					value: function(e) {
						e.isNone || (this.shape.isNone ? this.shape = e : this.shape = new Y.CompositeShape(this.shape, e));
					}
				}
			]) && xt(t.prototype, n), r && xt(t, r), e;
		}();
		function Ct(e) {
			return Ct = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
				return typeof e;
			} : function(e) {
				return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e;
			}, Ct(e);
		}
		function wt(e, t) {
			if (typeof t != `function` && t !== null) throw TypeError(`Super expression must either be null or a function`);
			e.prototype = Object.create(t && t.prototype, { constructor: {
				value: e,
				writable: !0,
				configurable: !0
			} }), t && Tt(e, t);
		}
		function Tt(e, t) {
			return Tt = Object.setPrototypeOf || function(e, t) {
				return e.__proto__ = t, e;
			}, Tt(e, t);
		}
		function Et(e) {
			var t = function() {
				if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return !1;
				if (typeof Proxy == `function`) return !0;
				try {
					return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {}))), !0;
				} catch {
					return !1;
				}
			}();
			return function() {
				var n, r = Ot(e);
				if (t) {
					var i = Ot(this).constructor;
					n = Reflect.construct(r, arguments, i);
				} else n = r.apply(this, arguments);
				return Dt(this, n);
			};
		}
		function Dt(e, t) {
			if (t && (Ct(t) === `object` || typeof t == `function`)) return t;
			if (t !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
			return function(e) {
				if (e === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
				return e;
			}(e);
		}
		function Ot(e) {
			return Ot = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
				return e.__proto__ || Object.getPrototypeOf(e);
			}, Ot(e);
		}
		function kt(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		function At(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function jt(e, t, n) {
			return t && At(e.prototype, t), n && At(e, n), e;
		}
		var Mt = function() {
			function e() {
				kt(this, e);
				var t = A.measure.length2em(`1mm`);
				this.origin = {
					x: 0,
					y: 0
				}, this.xBase = {
					x: t,
					y: 0
				}, this.yBase = {
					x: 0,
					y: t
				}, this.savedPosition = {}, this.stateStack = O.empty, this.stackFrames = O.empty, this.stack = O.empty, this.angle = 0, this.lastCurve = Q.none, this.p = this.c = e.originPosition, this.shouldCapturePos = !1, this.capturedPositions = O.empty, this.objectmargin = A.measure.objectmargin, this.objectheight = A.measure.objectheight, this.objectwidth = A.measure.objectwidth, this.labelmargin = A.measure.labelmargin;
			}
			return jt(e, [
				{
					key: `duplicate`,
					value: function() {
						var t = new e();
						return e.copyFields(this, t), t;
					}
				},
				{
					key: `saveState`,
					value: function() {
						var e = this.duplicate();
						this.stateStack = this.stateStack.prepend(e);
					}
				},
				{
					key: `restoreState`,
					value: function() {
						if (!this.stateStack.isEmpty) {
							var t = this.stateStack.head;
							this.stateStack = this.stateStack.tail, e.copyFields(t, this);
						}
					}
				},
				{
					key: `absVector`,
					value: function(e, t) {
						return {
							x: this.origin.x + e * this.xBase.x + t * this.yBase.x,
							y: this.origin.y + e * this.xBase.y + t * this.yBase.y
						};
					}
				},
				{
					key: `inverseAbsVector`,
					value: function(e, t) {
						var n = this.xBase.x, r = this.xBase.y, i = this.yBase.x, a = this.yBase.y, o = n * a - r * i, s = e - this.origin.x, c = t - this.origin.y;
						return {
							x: (a * s - i * c) / o,
							y: (-r * s + n * c) / o
						};
					}
				},
				{
					key: `setOrigin`,
					value: function(e, t) {
						this.origin = {
							x: e,
							y: t
						};
					}
				},
				{
					key: `setXBase`,
					value: function(e, t) {
						this.xBase = {
							x: e,
							y: t
						};
					}
				},
				{
					key: `setYBase`,
					value: function(e, t) {
						this.yBase = {
							x: e,
							y: t
						};
					}
				},
				{
					key: `swapPAndC`,
					value: function() {
						var e = this.p;
						this.p = this.c, this.c = e;
					}
				},
				{
					key: `enterStackFrame`,
					value: function() {
						this.stackFrames = this.stackFrames.prepend(this.stack), this.initStack();
					}
				},
				{
					key: `leaveStackFrame`,
					value: function() {
						this.stackFrames.isEmpty ? this.initStack() : (this.stack = this.stackFrames.head, this.stackFrames = this.stackFrames.tail);
					}
				},
				{
					key: `savePos`,
					value: function(e, t) {
						this.savedPosition[e] = t;
					}
				},
				{
					key: `startCapturePositions`,
					value: function() {
						this.shouldCapturePos = !0, this.capturedPositions = O.empty;
					}
				},
				{
					key: `endCapturePositions`,
					value: function() {
						this.shouldCapturePos = !1;
						var e = this.capturedPositions;
						return this.capturedPositions = O.empty, e;
					}
				},
				{
					key: `capturePosition`,
					value: function(e) {
						this.shouldCapturePos && e !== void 0 && (this.capturedPositions = this.capturedPositions.prepend(e));
					}
				},
				{
					key: `pushPos`,
					value: function(e) {
						e !== void 0 && (this.stack = this.stack.prepend(e));
					}
				},
				{
					key: `popPos`,
					value: function() {
						if (this.stack.isEmpty) throw c(`ExecutionError`, `cannot pop from the empty stack`);
						var e = this.stack.head;
						return this.stack = this.stack.tail, e;
					}
				},
				{
					key: `initStack`,
					value: function() {
						this.stack = O.empty;
					}
				},
				{
					key: `setStack`,
					value: function(e) {
						this.stack = e;
					}
				},
				{
					key: `stackAt`,
					value: function(e) {
						return this.stack.at(e);
					}
				},
				{
					key: `lookupPos`,
					value: function(e, t) {
						var n = this.savedPosition[e];
						if (n === void 0) throw c(`ExecutionError`, t === void 0 ? `<pos> "` + e + `" not defined.` : t);
						return n;
					}
				},
				{
					key: `toString`,
					value: function() {
						var e = ``;
						for (var t in this.savedPosition) this.savedPosition.hasOwnProperty(t) && (e.length > 0 && (e += `, `), e += t.toString() + `:` + this.savedPosition[t]);
						return `Env
  p:` + this.p + `
  c:` + this.c + `
  angle:` + this.angle + `
  lastCurve:` + this.lastCurve + `
  savedPosition:{` + e + `}
  origin:{x:` + this.origin.x + `, y:` + this.origin.y + `}
  xBase:{x:` + this.xBase.x + `, y:` + this.xBase.y + `}
  yBase:{x:` + this.yBase.x + `, y:` + this.yBase.y + `}
  stackFrames:` + this.stackFrames + `
  stack:` + this.stack + `
  shouldCapturePos:` + this.shouldCapturePos + `
  capturedPositions:` + this.capturedPositions;
					}
				}
			], [{
				key: `copyFields`,
				value: function(e, t) {
					for (var n in e) e.hasOwnProperty(n) && (t[n] = e[n]);
					for (var r in t.savedPosition = {}, e.savedPosition) e.savedPosition.hasOwnProperty(r) && (t.savedPosition[r] = e.savedPosition[r]);
				}
			}]), e;
		}();
		Mt.originPosition = new U.Point(0, 0);
		var X = function() {
			function e() {
				kt(this, e);
			}
			return jt(e, [
				{
					key: `velocity`,
					value: function(e) {
						var t = this.dpx(e), n = this.dpy(e);
						return Math.sqrt(t * t + n * n);
					}
				},
				{
					key: `length`,
					value: function(e) {
						if (e < 0 || e > 1) throw c(`ExecutionError`, `illegal cubic Bezier parameter t:` + e);
						this.buildLengthArray();
						var t = e * l.lengthResolution, n = Math.floor(t), r = Math.ceil(t);
						if (n === r) return this.lengthArray[n];
						var i = this.lengthArray[n];
						return i + (this.lengthArray[r] - i) / (r - n) * (t - n);
					}
				},
				{
					key: `tOfLength`,
					value: function(e) {
						this.buildLengthArray();
						var t, n, r, i = this.lengthArray;
						if (e < i[0]) return 0;
						if (e > i[i.length - 1]) return 1;
						for (var a = 0, o = i.length - 2; a <= o && (n = i[t = a + o >> 1], r = i[t + 1], !(e >= n && e <= r));) e < n ? o = t - 1 : a = t + 1;
						var s = l.lengthResolution;
						return n === r ? t / s : (t + (e - n) / (r - n)) / s;
					}
				},
				{
					key: `tOfShavedStart`,
					value: function(e) {
						if (e.isPoint()) return 0;
						var t = this.tOfIntersections(e);
						return t.length == 0 ? void 0 : Math.min.apply(Math, t);
					}
				},
				{
					key: `tOfShavedEnd`,
					value: function(e) {
						if (e.isPoint()) return 1;
						var t = this.tOfIntersections(e);
						return t.length == 0 ? void 0 : Math.max.apply(Math, t);
					}
				},
				{
					key: `shaveStart`,
					value: function(e) {
						if (e.isPoint()) return this;
						var t = this.tOfIntersections(e);
						if (t.length != 0) {
							var n = Math.min.apply(Math, t);
							return this.divide(n)[1];
						}
					}
				},
				{
					key: `shaveEnd`,
					value: function(e) {
						if (e.isPoint()) return this;
						var t = this.tOfIntersections(e);
						if (t.length != 0) {
							var n = Math.max.apply(Math, t);
							return this.divide(n)[0];
						}
					}
				},
				{
					key: `buildLengthArray`,
					value: function() {
						if (this.lengthArray === void 0) {
							var e = l.lengthResolution, t = Array(e + 1), n = 0, r = .5 / e, i = 0, a = r / 3;
							t[0] = 0, n = this.velocity(0) + 4 * this.velocity(r);
							var o = this.velocity(2 * r);
							for (t[1] = a * (n + o), i = 2; i <= e; i++) n += 2 * o + 4 * this.velocity((2 * i - 1) * r), o = this.velocity(2 * i * r), t[i] = a * (n + o);
							this.lengthArray = t;
						}
					}
				},
				{
					key: `drawParallelCurve`,
					value: function(t, n) {
						var r, i, a, o, s, c, u, d, f = this.countOfSegments() * l.interpolationResolution, p = Array(f + 1), m = Array(f + 1), h = Array(f + 1), g = Array(f + 1), _ = Array(f + 1), v = Math.PI / 2, y = n;
						for (r = 0; r <= f; r++) i = r / f, p[r] = i, a = this.angle(i), s = (o = this.position(i)).x, c = o.y, u = y * Math.cos(a + v), d = y * Math.sin(a + v), m[r] = s + u, h[r] = c + d, g[r] = s - u, _[r] = c - d;
						e.CubicBeziers.interpolation(p, m, h).drawPrimitive(t, `none`), e.CubicBeziers.interpolation(p, g, _).drawPrimitive(t, `none`);
					}
				},
				{
					key: `drawParallelDottedCurve`,
					value: function(e, t, n) {
						var r = 1 / A.measure.em, i = r / 2, a = r + t, o = this.length(1), s = Math.floor((o - r) / a), c = n;
						if (s >= 0) {
							var l, u = Math.PI / 2, d = this.startPosition();
							for (this.endPosition(), l = 0; l <= s; l++) {
								d = i + l * a;
								var f = this.tOfLength(d), p = this.angle(f), m = this.position(f), h = m.x, g = m.y, _ = c * Math.cos(p + u), v = c * Math.sin(p + u);
								e.createSVGElement(`circle`, {
									cx: A.measure.em2px(h + _),
									cy: -A.measure.em2px(g + v),
									r: .12,
									fill: `currentColor`
								}), e.createSVGElement(`circle`, {
									cx: A.measure.em2px(h - _),
									cy: -A.measure.em2px(g - v),
									r: .12,
									fill: `currentColor`
								});
							}
						}
					}
				},
				{
					key: `drawParallelDashedCurve`,
					value: function(t, n, r) {
						var i, a, o, s, c, l, u, d, f = this.length(1), p = Math.floor((f - n) / (2 * n)), m = 2 * p + 1, h = (f - n) / 2 - p * n, g = Array(p + 1), _ = Array(p + 1), v = Array(p + 1), y = Array(p + 1), b = Array(p + 1), x = Math.PI / 2, S = r;
						for (i = 0; i <= m; i++) a = this.tOfLength(h + i * n), g[i] = a, o = this.angle(a), c = (s = this.position(a)).x, l = s.y, u = S * Math.cos(o + x), d = S * Math.sin(o + x), _[i] = c + u, v[i] = l + d, y[i] = c - u, b[i] = l - d;
						e.CubicBeziers.interpolation(g, _, v).drawSkipped(t), e.CubicBeziers.interpolation(g, y, b).drawSkipped(t);
					}
				},
				{
					key: `drawSquigCurve`,
					value: function(e, t) {
						var n = A.measure.length2em(`0.15em`), r = this.length(1), i = 4 * n, a = n;
						if (r >= i) {
							var o, s, c, l, u, d, f, p, m, h = Math.floor(r / i), g = (r - h * i) / 2, _ = Math.PI / 2;
							switch (t) {
								case `3`:
									o = g, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f = `M` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p = `M` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), m = `M` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d);
									for (var v = 0; v < h; v++) o = g + i * v + n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` Q` + A.measure.em2px(c.x + 2 * u) + `,` + A.measure.em2px(-c.y - 2 * d), p += ` Q` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), m += ` Q` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), o = g + i * v + 2 * n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` ` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p += ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), m += ` ` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), o = g + i * v + 3 * n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` Q` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), p += ` Q` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), m += ` ` + A.measure.em2px(c.x - 2 * u) + `,` + A.measure.em2px(-c.y + 2 * d), o = g + i * (v + 1), s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` ` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p += ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), m += ` ` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d);
									e.createSVGElement(`path`, { d: f }), e.createSVGElement(`path`, { d: p }), e.createSVGElement(`path`, { d: m });
									break;
								case `2`:
									for (o = g, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _) / 2, d = a * Math.sin(l + _) / 2, f = `M` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p = `M` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), v = 0; v < h; v++) o = g + i * v + n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _) / 2, d = a * Math.sin(l + _) / 2, f += ` Q` + A.measure.em2px(c.x + 3 * u) + `,` + A.measure.em2px(-c.y - 3 * d), p += ` Q` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), o = g + i * v + 2 * n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _) / 2, d = a * Math.sin(l + _) / 2, f += ` ` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p += ` ` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), o = g + i * v + 3 * n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _) / 2, d = a * Math.sin(l + _) / 2, f += ` Q` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), p += ` Q` + A.measure.em2px(c.x - 3 * u) + `,` + A.measure.em2px(-c.y + 3 * d), o = g + i * (v + 1), s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _) / 2, d = a * Math.sin(l + _) / 2, f += ` ` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p += ` ` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d);
									e.createSVGElement(`path`, { d: f }), e.createSVGElement(`path`, { d: p });
									break;
								default:
									for (o = g, s = this.tOfLength(o), c = this.position(s), f = `M` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), v = 0; v < h; v++) o = g + i * v + n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` Q` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), o = g + i * v + 2 * n, s = this.tOfLength(o), c = this.position(s), f += ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), o = g + i * v + 3 * n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` Q` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), o = g + i * (v + 1), s = this.tOfLength(o), c = this.position(s), f += ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y);
									e.createSVGElement(`path`, { d: f });
							}
						}
					}
				},
				{
					key: `drawDashSquigCurve`,
					value: function(e, t) {
						var n = A.measure.thickness, r = this.length(1), i = 4 * n, a = n;
						if (r >= i) {
							var o, s, c, l, u, d, f, p, m, h = Math.floor((r - i) / 2 / i), g = (r - i) / 2 - h * i, _ = Math.PI / 2;
							switch (t) {
								case `3`:
									f = p = m = ``;
									for (var v = 0; v <= h; v++) o = g + i * v * 2, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` M` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p += ` M` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), m += ` M` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), o = g + i * v * 2 + n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` Q` + A.measure.em2px(c.x + 2 * u) + `,` + A.measure.em2px(-c.y - 2 * d), p += ` Q` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), m += ` Q` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), o = g + i * v * 2 + 2 * n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` ` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p += ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), m += ` ` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), o = g + i * v * 2 + 3 * n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` Q` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), p += ` Q` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), m += ` ` + A.measure.em2px(c.x - 2 * u) + `,` + A.measure.em2px(-c.y + 2 * d), o = g + i * (2 * v + 1), s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` ` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p += ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), m += ` ` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d);
									e.createSVGElement(`path`, { d: f }), e.createSVGElement(`path`, { d: p }), e.createSVGElement(`path`, { d: m });
									break;
								case `2`:
									for (f = p = ``, v = 0; v <= h; v++) o = g + i * v * 2, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _) / 2, d = a * Math.sin(l + _) / 2, f += ` M` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p += ` M` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), o = g + i * v * 2 + n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _) / 2, d = a * Math.sin(l + _) / 2, f += ` Q` + A.measure.em2px(c.x + 3 * u) + `,` + A.measure.em2px(-c.y - 3 * d), p += ` Q` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), o = g + i * v * 2 + 2 * n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _) / 2, d = a * Math.sin(l + _) / 2, f += ` ` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p += ` ` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), o = g + i * v * 2 + 3 * n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _) / 2, d = a * Math.sin(l + _) / 2, f += ` Q` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), p += ` Q` + A.measure.em2px(c.x - 3 * u) + `,` + A.measure.em2px(-c.y + 3 * d), o = g + i * (2 * v + 1), s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _) / 2, d = a * Math.sin(l + _) / 2, f += ` ` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), p += ` ` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d);
									e.createSVGElement(`path`, { d: f }), e.createSVGElement(`path`, { d: p });
									break;
								default:
									for (f = ``, v = 0; v <= h; v++) o = g + i * v * 2, s = this.tOfLength(o), c = this.position(s), f += ` M` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), o = g + i * v * 2 + n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` Q` + A.measure.em2px(c.x + u) + `,` + A.measure.em2px(-c.y - d), o = g + i * v * 2 + 2 * n, s = this.tOfLength(o), c = this.position(s), f += ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), o = g + i * v * 2 + 3 * n, s = this.tOfLength(o), c = this.position(s), l = this.angle(s), u = a * Math.cos(l + _), d = a * Math.sin(l + _), f += ` Q` + A.measure.em2px(c.x - u) + `,` + A.measure.em2px(-c.y + d), o = g + i * (2 * v + 1), s = this.tOfLength(o), c = this.position(s), f += ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y);
									e.createSVGElement(`path`, { d: f });
							}
						}
					}
				},
				{
					key: `drawCurve`,
					value: function(e, t, n, r) {
						if (r.isEmpty) this._drawCurve(e, t, n);
						else {
							var i = new bt(0, 1).differenceRanges(r), a = this;
							i.foreach((function(r) {
								a.slice(r.start, r.end)._drawCurve(e, t, n);
							}));
						}
					}
				},
				{
					key: `_drawCurve`,
					value: function(e, t, n) {
						var r, i = A.measure.length2em(`0.15em`);
						if (n !== void 0) {
							var a = n.dirMain(), o = n.dirVariant();
							switch (a) {
								case `=`:
									a = `-`, o = `2`;
									break;
								case `==`:
									a = `--`, o = `2`;
									break;
								case `:`:
								case `::`: a = `.`, o = `2`;
							}
							switch (a) {
								case ``: break;
								case `-`:
									switch (o) {
										case `2`:
											r = i / 2, this.drawParallelCurve(e, r);
											break;
										case `3`:
											r = i, this.drawParallelCurve(e, r), this.drawPrimitive(e, `none`);
											break;
										default: r = 0, this.drawPrimitive(e, `none`);
									}
									break;
								case `.`:
								case `..`:
									switch (o) {
										case `2`:
											r = i / 2, this.drawParallelDottedCurve(e, i, r);
											break;
										case `3`:
											r = i, this.drawParallelDottedCurve(e, i, r), this.drawPrimitive(e, A.measure.dottedDasharray);
											break;
										default: r = 0, this.drawPrimitive(e, A.measure.dottedDasharray);
									}
									break;
								case `--`:
									var s = 3 * i;
									if ((v = this.length(1)) >= s) switch (o) {
										case `2`:
											r = i / 2, this.drawParallelDashedCurve(e, s, r);
											break;
										case `3`:
											r = i, this.drawParallelDashedCurve(e, s, r);
											var c = (v - s) / 2 - Math.floor((v - s) / 2 / s) * s, l = this.tOfLength(c);
											this.divide(l)[1].drawPrimitive(e, A.measure.em2px(s) + ` ` + A.measure.em2px(s));
											break;
										default: r = 0, c = (v - s) / 2 - Math.floor((v - s) / 2 / s) * s, l = this.tOfLength(c), this.divide(l)[1].drawPrimitive(e, A.measure.em2px(s) + ` ` + A.measure.em2px(s));
									}
									break;
								case `~`:
									switch (this.drawSquigCurve(e, o), o) {
										case `2`:
											r = 1.5 * i;
											break;
										case `3`:
											r = 2 * i;
											break;
										default: r = 0;
									}
									break;
								case `~~`:
									switch (this.drawDashSquigCurve(e, o), o) {
										case `2`:
											r = 1.5 * i;
											break;
										case `3`:
											r = 2 * i;
											break;
										default: r = 0;
									}
									break;
								default:
									(b = new Mt()).c = Mt.originPosition;
									var u = new St(Y.none, b), d = n.boundingBox(u);
									if (d == null) return;
									var f, p, m = d.l, h = m + d.r;
									if (t !== void 0) {
										var g = t.boundingBox(u);
										g !== void 0 && (f = (p = g.l) + g.r);
									} else f = 0;
									var _ = h + f;
									_ == 0 && (_ = A.measure.strokeWidth);
									var v = this.length(1);
									if ((T = Math.floor(v / _)) == 0) return;
									c = (v - T * _) / 2, u = new St(Y.none, b);
									for (var y = 0; y < T; y++) E = c + y * _, t !== void 0 && (D = this.tOfLength(E + p), b.c = this.position(D), b.angle = this.angle(D), t.toDropShape(u).draw(e)), D = this.tOfLength(E + f + m), b.c = this.position(D), b.angle = this.angle(D), n.toDropShape(u).draw(e);
							}
						} else {
							var b;
							(b = new Mt()).c = Mt.originPosition, u = new St(Y.none, b);
							var x = t, S = x.boundingBox(u);
							if (S === void 0) return;
							var C = S.l + S.r, w = C;
							w == 0 && (w = A.measure.strokeWidth);
							var T;
							if (v = this.length(1), (T = Math.floor(v / w)) == 0) return;
							for (c = (v - T * w + w - C) / 2 + S.l, u = new St(Y.none, b), y = 0; y < T; y++) {
								var E = c + y * w, D = this.tOfLength(E);
								b.c = this.position(D), b.angle = 0, x.toDropShape(u).draw(e);
							}
						}
					}
				},
				{
					key: `toShape`,
					value: function(e, t, n) {
						var r, i = e.env, a = A.measure.length2em(`0.15em`), o = Y.none;
						if (n !== void 0) {
							var s = n.dirMain(), c = n.dirVariant();
							switch (s) {
								case `=`:
									s = `-`, c = `2`;
									break;
								case `==`:
									s = `--`, c = `2`;
									break;
								case `:`:
								case `::`: s = `.`, c = `2`;
							}
							switch (s) {
								case ``:
									r = 0;
									break;
								case `-`:
								case `.`:
								case `..`:
									switch (c) {
										case `2`:
											r = a / 2;
											break;
										case `3`:
											r = a;
											break;
										default: r = 0;
									}
									break;
								case `--`:
									var l = 3 * a;
									if ((h = this.length(1)) >= l) switch (c) {
										case `2`:
											r = a / 2;
											break;
										case `3`:
											r = a;
											break;
										default: r = 0;
									}
									break;
								case `~`:
								case `~~`:
									switch (c) {
										case `2`:
											r = 1.5 * a;
											break;
										case `3`:
											r = 2 * a;
											break;
										default: r = 0;
									}
									break;
								default:
									var u = n.boundingBox(e);
									if (u == null) return i.angle = 0, i.lastCurve = Q.none, Y.none;
									r = Math.max(u.u, u.d);
									var d, f = u.l + u.r;
									if (t !== void 0) {
										var p = t.boundingBox(e);
										p !== void 0 && (d = p.l + p.r, r = Math.max(r, p.u, p.d));
									} else d = 0;
									var m = f + d;
									m == 0 && (m = A.measure.strokeWidth);
									var h = this.length(1);
									return Math.floor(h / m) == 0 ? (i.angle = 0, i.lastCurve = Q.none, Y.none) : (o = new Y.CurveShape(this, t, n, this.boundingBox(r)), e.appendShapeToFront(o), o);
							}
							return r === void 0 ? Y.none : (o = new Y.CurveShape(this, t, n, this.boundingBox(r)), e.appendShapeToFront(o), o);
						}
						if (t !== void 0) {
							var g = t.boundingBox(e);
							if (g == null) return i.angle = 0, i.lastCurve = Q.none, Y.none;
							var _ = g.l + g.r;
							return _ == 0 && (_ = A.measure.strokeWidth), h = this.length(1), Math.floor(h / _) == 0 ? (i.angle = 0, i.lastCurve = Q.none, Y.none) : (r = Math.max(g.u, g.d), o = new Y.CurveShape(this, t, n, this.boundingBox(r)), e.appendShapeToFront(o), o);
						}
						return o;
					}
				}
			], [
				{
					key: `sign`,
					value: function(e) {
						return e > 0 ? 1 : e === 0 ? 0 : -1;
					}
				},
				{
					key: `solutionsOfCubicEq`,
					value: function(t, n, r, i) {
						if (t === 0) return e.solutionsOfQuadEq(n, r, i);
						var a = n / 3 / t, o = r / t, s = a * a - o / 3, c = -(i / t) / 2 + o * a / 2 - a * a * a, l = c * c - s * s * s;
						if (l === 0) {
							var u = 2 * (h = c ** (1 / 3)) - a, d = -h - a;
							return e.filterByIn0to1([u, d]);
						}
						if (l > 0) {
							var f = c + e.sign(c) * Math.sqrt(l), p = (m = e.sign(f) * Math.abs(f) ** (1 / 3)) + (h = s / m) - a;
							return e.filterByIn0to1([p]);
						}
						var m = 2 * Math.sqrt(s), h = Math.acos(2 * c / s / m), g = (u = m * Math.cos(h / 3) - a, d = m * Math.cos((h + 2 * Math.PI) / 3) - a, m * Math.cos((h + 4 * Math.PI) / 3) - a);
						return e.filterByIn0to1([
							u,
							d,
							g
						]);
					}
				},
				{
					key: `solutionsOfQuadEq`,
					value: function(t, n, r) {
						if (t === 0) return e.solutionsOfLinearEq(n, r);
						var i = n * n - 4 * r * t;
						if (i >= 0) {
							var a = Math.sqrt(i), o = (-n + a) / 2 / t, s = (-n - a) / 2 / t;
							return e.filterByIn0to1([o, s]);
						}
						return [];
					}
				},
				{
					key: `solutionsOfLinearEq`,
					value: function(t, n) {
						return t === 0 ? n === 0 ? 0 : [] : e.filterByIn0to1([-n / t]);
					}
				},
				{
					key: `filterByIn0to1`,
					value: function(e) {
						for (var t = [], n = 0; n < e.length; n++) {
							var r = e[n];
							r >= 0 && r <= 1 && t.push(r);
						}
						return t;
					}
				}
			]), e;
		}();
		X.QuadBezier = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e, r, i) {
				var a;
				kt(this, n), (a = t.call(this)).cp0 = e, a.cp1 = r, a.cp2 = i;
				var o = e.x, s = 2 * (r.x - e.x), c = i.x - 2 * r.x + e.x;
				a.px = function(e) {
					return o + e * s + e * e * c;
				}, a.dpx = function(e) {
					return s + 2 * e * c;
				};
				var l = e.y, u = 2 * (r.y - e.y), d = i.y - 2 * r.y + e.y;
				return a.py = function(e) {
					return l + e * u + e * e * d;
				}, a.dpy = function(e) {
					return u + 2 * e * d;
				}, a;
			}
			return jt(n, [
				{
					key: `startPosition`,
					value: function() {
						return this.cp0;
					}
				},
				{
					key: `endPosition`,
					value: function() {
						return this.cp2;
					}
				},
				{
					key: `position`,
					value: function(e) {
						return new U.Point(this.px(e), this.py(e));
					}
				},
				{
					key: `derivative`,
					value: function(e) {
						return new U.Point(this.dpx(e), this.dpy(e));
					}
				},
				{
					key: `angle`,
					value: function(e) {
						return Math.atan2(this.dpy(e), this.dpx(e));
					}
				},
				{
					key: `boundingBox`,
					value: function(e) {
						var t = this.maxMin(this.cp0.x, this.cp1.x, this.cp2.x, e), n = this.maxMin(this.cp0.y, this.cp1.y, this.cp2.y, e);
						if (e === 0) return new U.Rect(this.cp0.x, this.cp0.y, {
							l: this.cp0.x - t.min,
							r: t.max - this.cp0.x,
							u: n.max - this.cp0.y,
							d: this.cp0.y - n.min
						});
						var r = Math.PI / 2, i = this.cp0.x, a = this.cp0.y, o = this.cp2.x, s = this.cp2.y, c = this.angle(0) + r, l = this.angle(1) + r, u = e * Math.cos(c), d = e * Math.sin(c), f = e * Math.cos(l), p = e * Math.sin(l), m = Math.min(t.min, i + u, i - u, o + f, o - f), h = Math.max(t.max, i + u, i - u, o + f, o - f), g = Math.min(n.min, a + d, a - d, s + p, s - p), _ = Math.max(n.max, a + d, a - d, s + p, s - p);
						return new U.Rect(i, a, {
							l: i - m,
							r: h - i,
							u: _ - a,
							d: a - g
						});
					}
				},
				{
					key: `maxMin`,
					value: function(e, t, n, r) {
						var i, a;
						e > n ? (i = e, a = n) : (i = n, a = e);
						var o, s, c = rt, l = c(e), u = c(t - e), d = c(n - 2 * t + e);
						return d != 0 && (s = -u / d) > 0 && s < 1 && (o = function(e) {
							return l + 2 * e * u + e * e * d;
						}(s), i = Math.max(i, o + r, o - r), a = Math.min(a, o + r, o - r)), {
							min: a,
							max: i
						};
					}
				},
				{
					key: `divide`,
					value: function(e) {
						if (e < 0 || e > 1) throw c(`ExecutionError`, `illegal quadratic Bezier parameter t:` + e);
						var t = this.cp0.x, n = this.cp1.x, r = this.cp2.x, i = this.cp0.y, a = this.cp1.y, o = this.cp2.y, s = this.px(e), l = this.py(e), u = this.cp0, d = new U.Point(t + e * (n - t), i + e * (a - i)), f = new U.Point(s, l), p = f, m = new U.Point(n + e * (r - n), a + e * (o - a)), h = this.cp2;
						return [new X.QuadBezier(u, d, f), new X.QuadBezier(p, m, h)];
					}
				},
				{
					key: `slice`,
					value: function(e, t) {
						if (!(e >= t)) {
							if (e < 0 && (e = 0), t > 1 && (t = 1), e === 0 && t === 1) return this;
							this.cp0.x;
							var n = this.cp1.x, r = this.cp2.x, i = (this.cp0.y, this.cp1.y), a = this.cp2.y, o = this.px(e), s = this.py(e), c = n + e * (r - n), l = i + e * (a - i), u = new U.Point(o, s), d = new U.Point(o + t * (c - o), s + t * (l - s)), f = new U.Point(this.px(t), this.py(t));
							return new X.QuadBezier(u, d, f);
						}
					}
				},
				{
					key: `tOfIntersections`,
					value: function(e) {
						if (e.isPoint()) return [];
						if (e.isRect()) {
							var t, n = e.x + e.r, r = e.x - e.l, i = e.y + e.u, a = e.y - e.d, o = rt, s = this.cp0.x, c = this.cp1.x, l = this.cp2.x, u = o(s), d = o(2 * (c - s)), f = o(l - 2 * c + s), p = function(e) {
								return u + e * d + e * e * f;
							}, m = this.cp0.y, h = this.cp1.y, g = this.cp2.y, _ = o(m), v = o(2 * (h - m)), y = o(g - 2 * h + m), b = function(e) {
								return _ + e * v + e * e * y;
							}, x = [];
							t = (t = X.solutionsOfQuadEq(f, d, u - n)).concat(X.solutionsOfQuadEq(f, d, u - r));
							for (var S = 0; S < t.length; S++) (T = b(de = t[S])) >= a && T <= i && x.push(de);
							for (t = (t = X.solutionsOfQuadEq(y, v, _ - i)).concat(X.solutionsOfQuadEq(y, v, _ - a)), S = 0; S < t.length; S++) (w = p(de = t[S])) >= r && w <= n && x.push(de);
							return x;
						}
						if (e.isCircle()) {
							var C = Math.PI, w = e.x, T = e.y, E = e.l, D = e.r, ee = e.u, te = e.d, ne = w + (D - E) / 2, O = T + (ee - te) / 2, re = (n = (E + D) / 2, (ee + te) / 2), ie = C / 180, ae = new Z.Arc(ne, O, n, re, -C - ie, -C / 2 + ie), oe = new Z.Arc(ne, O, n, re, -C / 2 - ie, 0 + ie), se = new Z.Arc(ne, O, n, re, 0 - ie, C / 2 + ie), ce = new Z.Arc(ne, O, n, re, C / 2 - ie, C + ie), le = new Z.QuadBezier(this, 0, 1), ue = [];
							for (ue = (ue = (ue = (ue = ue.concat(Z.findIntersections(ae, le))).concat(Z.findIntersections(oe, le))).concat(Z.findIntersections(se, le))).concat(Z.findIntersections(ce, le)), x = [], S = 0; S < ue.length; S++) {
								var de = (ue[S][1].min + ue[S][1].max) / 2;
								x.push(de);
							}
							return x;
						}
					}
				},
				{
					key: `countOfSegments`,
					value: function() {
						return 1;
					}
				},
				{
					key: `drawPrimitive`,
					value: function(e, t) {
						var n = this.cp0, r = this.cp1, i = this.cp2;
						e.createSVGElement(`path`, {
							d: `M` + A.measure.em2px(n.x) + `,` + A.measure.em2px(-n.y) + ` Q` + A.measure.em2px(r.x) + `,` + A.measure.em2px(-r.y) + ` ` + A.measure.em2px(i.x) + `,` + A.measure.em2px(-i.y),
							"stroke-dasharray": t
						});
					}
				},
				{
					key: `toString`,
					value: function() {
						return `QuadBezier(` + this.cp0.x + `, ` + this.cp0.y + `)-(` + this.cp1.x + `, ` + this.cp1.y + `)-(` + this.cp2.x + `, ` + this.cp2.y + `)`;
					}
				}
			]), n;
		}(X), X.CubicBezier = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e, r, i, a) {
				var o;
				kt(this, n), (o = t.call(this)).cp0 = e, o.cp1 = r, o.cp2 = i, o.cp3 = a;
				var s = e.x, c = 3 * (r.x - e.x), l = 3 * (i.x - 2 * r.x + e.x), u = a.x - 3 * i.x + 3 * r.x - e.x;
				o.px = function(e) {
					return s + e * c + e * e * l + e * e * e * u;
				}, o.dpx = function(e) {
					return c + 2 * e * l + 3 * e * e * u;
				};
				var d = e.y, f = 3 * (r.y - e.y), p = 3 * (i.y - 2 * r.y + e.y), m = a.y - 3 * i.y + 3 * r.y - e.y;
				return o.py = function(e) {
					return d + e * f + e * e * p + e * e * e * m;
				}, o.dpy = function(e) {
					return f + 2 * e * p + 3 * e * e * m;
				}, o;
			}
			return jt(n, [
				{
					key: `startPosition`,
					value: function() {
						return this.cp0;
					}
				},
				{
					key: `endPosition`,
					value: function() {
						return this.cp3;
					}
				},
				{
					key: `position`,
					value: function(e) {
						return new U.Point(this.px(e), this.py(e));
					}
				},
				{
					key: `derivative`,
					value: function(e) {
						return new U.Point(this.dpx(e), this.dpy(e));
					}
				},
				{
					key: `angle`,
					value: function(e) {
						return Math.atan2(this.dpy(e), this.dpx(e));
					}
				},
				{
					key: `boundingBox`,
					value: function(e) {
						var t = this.maxMin(this.cp0.x, this.cp1.x, this.cp2.x, this.cp3.x, e), n = this.maxMin(this.cp0.y, this.cp1.y, this.cp2.y, this.cp3.y, e);
						if (e === 0) return new U.Rect(this.cp0.x, this.cp0.y, {
							l: this.cp0.x - t.min,
							r: t.max - this.cp0.x,
							u: n.max - this.cp0.y,
							d: this.cp0.y - n.min
						});
						var r = Math.PI / 2, i = this.cp0.x, a = this.cp0.y, o = this.cp3.x, s = this.cp3.y, c = this.angle(0) + r, l = this.angle(1) + r, u = e * Math.cos(c), d = e * Math.sin(c), f = e * Math.cos(l), p = e * Math.sin(l), m = Math.min(t.min, i + u, i - u, o + f, o - f), h = Math.max(t.max, i + u, i - u, o + f, o - f), g = Math.min(n.min, a + d, a - d, s + p, s - p), _ = Math.max(n.max, a + d, a - d, s + p, s - p);
						return new U.Rect(i, a, {
							l: i - m,
							r: h - i,
							u: _ - a,
							d: a - g
						});
					}
				},
				{
					key: `maxMin`,
					value: function(e, t, n, r, i) {
						var a, o;
						e > r ? (a = e, o = r) : (a = r, o = e);
						var s, c = rt, l = c(e), u = c(t - e), d = c(n - 2 * t + e), f = c(r - 3 * n + 3 * t - e), p = function(e) {
							e > 0 && e < 1 && (s = function(e) {
								return l + 3 * e * u + 3 * e * e * d + e * e * e * f;
							}(e), a = Math.max(a, s + i, s - i), o = Math.min(o, s + i, s - i));
						};
						if (f == 0) d != 0 && p(-u / d / 2);
						else {
							var m = d * d - u * f;
							m > 0 ? (p((-d + Math.sqrt(m)) / f), p((-d - Math.sqrt(m)) / f)) : m == 0 && p(-d / f);
						}
						return {
							min: o,
							max: a
						};
					}
				},
				{
					key: `divide`,
					value: function(e) {
						if (e < 0 || e > 1) throw c(`ExecutionError`, `illegal cubic Bezier parameter t:` + e);
						var t = this.cp0.x, n = this.cp1.x, r = this.cp2.x, i = this.cp3.x, a = this.cp0.y, o = this.cp1.y, s = this.cp2.y, l = this.cp3.y, u = this.px(e), d = this.py(e), f = this.cp0, p = new U.Point(t + e * (n - t), a + e * (o - a)), m = new U.Point(t + 2 * e * (n - t) + e * e * (r - 2 * n + t), a + 2 * e * (o - a) + e * e * (s - 2 * o + a)), h = new U.Point(u, d), g = h, _ = new U.Point(n + 2 * e * (r - n) + e * e * (i - 2 * r + n), o + 2 * e * (s - o) + e * e * (l - 2 * s + o)), v = new U.Point(r + e * (i - r), s + e * (l - s)), y = this.cp3;
						return [new X.CubicBezier(f, p, m, h), new X.CubicBezier(g, _, v, y)];
					}
				},
				{
					key: `slice`,
					value: function(e, t) {
						if (!(e >= t)) {
							if (e < 0 && (e = 0), t > 1 && (t = 1), e === 0 && t === 1) return this;
							this.cp0.x;
							var n = this.cp1.x, r = this.cp2.x, i = this.cp3.x, a = (this.cp0.y, this.cp1.y), o = this.cp2.y, s = this.cp3.y, c = this.px(e), l = this.py(e), u = n + 2 * e * (r - n) + e * e * (i - 2 * r + n), d = a + 2 * e * (o - a) + e * e * (s - 2 * o + a), f = r + e * (i - r), p = o + e * (s - o), m = new U.Point(c, l), h = new U.Point(c + t * (u - c), l + t * (d - l)), g = new U.Point(c + 2 * t * (u - c) + t * t * (f - 2 * u + c), l + 2 * t * (d - l) + t * t * (p - 2 * d + l)), _ = new U.Point(this.px(t), this.py(t));
							return new X.CubicBezier(m, h, g, _);
						}
					}
				},
				{
					key: `tOfIntersections`,
					value: function(e) {
						if (e.isPoint()) return [];
						if (e.isRect()) {
							var t, n = e.x + e.r, r = e.x - e.l, i = e.y + e.u, a = e.y - e.d, o = rt, s = this.cp0.x, c = this.cp1.x, l = this.cp2.x, u = this.cp3.x, d = this.cp0.y, f = this.cp1.y, p = this.cp2.y, m = this.cp3.y, h = o(s), g = o(3 * (c - s)), _ = o(3 * (l - 2 * c + s)), v = o(u - 3 * l + 3 * c - s), y = function(e) {
								return h + e * g + e * e * _ + e * e * e * v;
							}, b = o(d), x = o(3 * (f - d)), S = o(3 * (p - 2 * f + d)), C = o(m - 3 * p + 3 * f - d), w = function(e) {
								return b + e * x + e * e * S + e * e * e * C;
							}, T = [];
							t = (t = X.solutionsOfCubicEq(v, _, g, h - n)).concat(X.solutionsOfCubicEq(v, _, g, h - r));
							for (var E = 0; E < t.length; E++) (te = w(he = t[E])) >= a && te <= i && T.push(he);
							for (t = (t = X.solutionsOfCubicEq(C, S, x, b - i)).concat(X.solutionsOfCubicEq(C, S, x, b - a)), E = 0; E < t.length; E++) (ee = y(he = t[E])) >= r && ee <= n && T.push(he);
							return T;
						}
						if (e.isCircle()) {
							var D = Math.PI, ee = e.x, te = e.y, ne = e.l, O = e.r, re = e.u, ie = e.d, ae = ee + (O - ne) / 2, oe = te + (re - ie) / 2, se = (n = (ne + O) / 2, (re + ie) / 2), ce = D / 180, le = new Z.Arc(ae, oe, n, se, -D - ce, -D / 2 + ce), ue = new Z.Arc(ae, oe, n, se, -D / 2 - ce, 0 + ce), de = new Z.Arc(ae, oe, n, se, 0 - ce, D / 2 + ce), fe = new Z.Arc(ae, oe, n, se, D / 2 - ce, D + ce), pe = new Z.CubicBezier(this, 0, 1), me = [];
							for (me = (me = (me = (me = me.concat(Z.findIntersections(le, pe))).concat(Z.findIntersections(ue, pe))).concat(Z.findIntersections(de, pe))).concat(Z.findIntersections(fe, pe)), T = [], E = 0; E < me.length; E++) {
								var he = (me[E][1].min + me[E][1].max) / 2;
								T.push(he);
							}
							return T;
						}
					}
				},
				{
					key: `countOfSegments`,
					value: function() {
						return 1;
					}
				},
				{
					key: `drawPrimitive`,
					value: function(e, t) {
						var n = this.cp0, r = this.cp1, i = this.cp2, a = this.cp3;
						e.createSVGElement(`path`, {
							d: `M` + A.measure.em2px(n.x) + `,` + A.measure.em2px(-n.y) + ` C` + A.measure.em2px(r.x) + `,` + A.measure.em2px(-r.y) + ` ` + A.measure.em2px(i.x) + `,` + A.measure.em2px(-i.y) + ` ` + A.measure.em2px(a.x) + `,` + A.measure.em2px(-a.y),
							"stroke-dasharray": t
						});
					}
				},
				{
					key: `toString`,
					value: function() {
						return `CubicBezier(` + this.cp0.x + `, ` + this.cp0.y + `)-(` + this.cp1.x + `, ` + this.cp1.y + `)-(` + this.cp2.x + `, ` + this.cp2.y + `)-(` + this.cp3.x + `, ` + this.cp3.y + `)`;
					}
				}
			]), n;
		}(X), X.CubicBeziers = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e) {
				var r;
				kt(this, n), (r = t.call(this)).cbs = e;
				var i = r.cbs.length;
				return r.delegate = i == 0 ? function(e, t, n) {
					return n;
				} : function(t, n, r) {
					var a = t * i, o = Math.floor(a);
					o < 0 && (o = 0), o >= i && (o = i - 1);
					var s = a - o;
					return n(e[o], s);
				}, r;
			}
			return jt(n, [
				{
					key: `startPosition`,
					value: function() {
						return this.cbs[0].cp0;
					}
				},
				{
					key: `endPosition`,
					value: function() {
						return this.cbs[this.cbs.length - 1].cp3;
					}
				},
				{
					key: `position`,
					value: function(e) {
						return this.delegate(e, (function(e, t) {
							return e.position(t);
						}), void 0);
					}
				},
				{
					key: `derivative`,
					value: function(e) {
						return this.delegate(e, (function(e, t) {
							return e.derivative(t);
						}), void 0);
					}
				},
				{
					key: `angle`,
					value: function(e) {
						return this.delegate(e, (function(e, t) {
							return e.angle(t);
						}), 0);
					}
				},
				{
					key: `velocity`,
					value: function(e) {
						var t = this.cbs.length;
						return this.delegate(e, (function(e, n) {
							return t * e.velocity(n);
						}), 0);
					}
				},
				{
					key: `boundingBox`,
					value: function(e) {
						if (this.cbs.length != 0) {
							var t, n = this.cbs[0].boundingBox(e), r = this.cbs.length;
							for (t = 1; t < r; t++) n = n.combineRect(this.cbs[t].boundingBox(e));
							return n;
						}
					}
				},
				{
					key: `tOfIntersections`,
					value: function(e) {
						var t = [], n = 0, r = this.cbs.length;
						for (n = 0; n < r; n++) for (var i = this.cbs[n].tOfIntersections(e), a = 0; a < i.length; a++) t.push((i[a] + n) / r);
						return t;
					}
				},
				{
					key: `divide`,
					value: function(e) {
						if (e < 0 || e > 1) throw c(`ExecutionError`, `illegal cubic Bezier parameter t:` + e);
						if (e === 0) return [new X.CubicBeziers([]), this];
						if (e === 1) return [this, new X.CubicBeziers([])];
						var t = this.cbs.length, n = e * t, r = Math.floor(n);
						r === t && (r = t - 1);
						var i = n - r, a = this.cbs.slice(0, r), o = this.cbs.slice(r + 1), s = this.cbs[r].divide(i);
						return a.push(s[0]), o.unshift(s[1]), [new X.CubicBeziers(a), new X.CubicBeziers(o)];
					}
				},
				{
					key: `slice`,
					value: function(e, t) {
						if (!(e >= t)) {
							if (e < 0 && (e = 0), t > 1 && (t = 1), e === 0 && t === 1) return this;
							var n = this.cbs.length, r = e * n, i = t * n, a = Math.floor(r), o = Math.floor(i);
							a === n && (a = n - 1), o === n && (o = n - 1);
							var s, c = r - a, l = i - o;
							return a === o ? s = [this.cbs[a].slice(c, l)] : ((s = this.cbs.slice(a + 1, o)).push(this.cbs[o].slice(0, l)), s.unshift(this.cbs[a].slice(c, 1))), new X.CubicBeziers(s);
						}
					}
				},
				{
					key: `countOfSegments`,
					value: function() {
						return this.cbs.length;
					}
				},
				{
					key: `drawPrimitive`,
					value: function(e, t) {
						for (var n = this.cbs.length, r = this.cbs, i = r[0], a = i.cp0, o = i.cp1, s = i.cp2, c = i.cp3, l = `M` + A.measure.em2px(a.x) + `,` + A.measure.em2px(-a.y) + ` C` + A.measure.em2px(o.x) + `,` + A.measure.em2px(-o.y) + ` ` + A.measure.em2px(s.x) + `,` + A.measure.em2px(-s.y) + ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y), u = 1; u < n; u++) s = (i = r[u]).cp2, c = i.cp3, l += ` S` + A.measure.em2px(s.x) + `,` + A.measure.em2px(-s.y) + ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y);
						e.createSVGElement(`path`, {
							d: l,
							"stroke-dasharray": t
						});
					}
				},
				{
					key: `drawSkipped`,
					value: function(e) {
						for (var t = this.cbs.length, n = this.cbs, r = ``, i = 0; i < t; i += 2) {
							var a = n[i], o = a.cp0, s = a.cp1, c = a.cp2, l = a.cp3;
							r += `M` + A.measure.em2px(o.x) + `,` + A.measure.em2px(-o.y) + ` C` + A.measure.em2px(s.x) + `,` + A.measure.em2px(-s.y) + ` ` + A.measure.em2px(c.x) + `,` + A.measure.em2px(-c.y) + ` ` + A.measure.em2px(l.x) + `,` + A.measure.em2px(-l.y);
						}
						e.createSVGElement(`path`, { d: r });
					}
				}
			], [{
				key: `interpolation`,
				value: function(e, t, n) {
					var r, i = X.CubicBeziers.cubicSplineInterpolation(e, t), a = i[0], o = i[1], s = X.CubicBeziers.cubicSplineInterpolation(e, n), c = s[0], l = s[1], u = e.length, d = Array(u - 1);
					for (r = 0; r < u - 1; r++) d[r] = new X.CubicBezier(new U.Point(t[r], n[r]), new U.Point(a[r], c[r]), new U.Point(o[r], l[r]), new U.Point(t[r + 1], n[r + 1]));
					return new X.CubicBeziers(d);
				}
			}, {
				key: `cubicSplineInterpolation`,
				value: function(e, t) {
					var n, r = e.length - 1, i = Array(r);
					for (n = 0; n < r; n++) i[n] = e[n + 1] - e[n];
					var a = Array(r);
					for (n = 1; n < r; n++) a[n] = 3 * (t[n + 1] - t[n]) / i[n] - 3 * (t[n] - t[n - 1]) / i[n - 1];
					var o = Array(r + 1), s = Array(r + 1), c = Array(r + 1);
					for (o[0] = 1, s[0] = 0, c[0] = 0, n = 1; n < r; n++) o[n] = 2 * (e[n + 1] - e[n - 1]) - i[n - 1] * s[n - 1], s[n] = i[n] / o[n], c[n] = (a[n] - i[n - 1] * c[n - 1]) / o[n];
					o[r] = 1, c[r] = 0;
					var l = Array(r), u = Array(r + 1);
					for (u[r] = 0, n = r - 1; n >= 0; n--) {
						var d = i[n], f = u[n + 1], p = d * d * c[n] - s[n] * f;
						u[n] = p, l[n] = t[n + 1] - t[n] - (f + 2 * p) / 3;
					}
					var m = Array(r), h = Array(r);
					for (n = 0; n < r; n++) {
						var g = t[n], _ = l[n], v = u[n];
						m[n] = g + _ / 3, h[n] = g + (2 * _ + v) / 3;
					}
					return [m, h];
				}
			}]), n;
		}(X), X.CubicBSpline = function() {
			function e(t, n, r) {
				if (kt(this, e), n.length < 1) throw c(`ExecutionError`, `the number of internal control points of cubic B-spline must be greater than or equal to 1`);
				var i = [];
				i.push(t);
				for (var a = 0, o = n.length; a < o; a++) i.push(n[a]);
				i.push(r), this.cps = i;
				var s = this.cps.length - 1, l = function(e) {
					return e < 0 ? i[0] : e > s ? i[s] : i[e];
				}, u = function(e) {
					var t = Math.abs(e);
					return t <= 1 ? (3 * t * t * t - 6 * t * t + 4) / 6 : t <= 2 ? -(t - 2) * (t - 2) * (t - 2) / 6 : 0;
				};
				this.px = function(e) {
					for (var t = (s + 2) * e - 1, n = Math.ceil(t - 2), r = Math.floor(t + 2), i = 0, a = n; a <= r; a++) i += u(t - a) * l(a).x;
					return i;
				}, this.py = function(e) {
					for (var t = (s + 2) * e - 1, n = Math.ceil(t - 2), r = Math.floor(t + 2), i = 0, a = n; a <= r; a++) i += u(t - a) * l(a).y;
					return i;
				};
				var d = function(e) {
					var t = e > 0 ? 1 : e < 0 ? -1 : 0, n = Math.abs(e);
					return n <= 1 ? t * (3 * n * n - 4 * n) / 2 : n <= 2 ? -t * (n - 2) * (n - 2) / 2 : 0;
				};
				this.dpx = function(e) {
					for (var t = (s + 2) * e - 1, n = Math.ceil(t - 2), r = Math.floor(t + 2), i = 0, a = n; a <= r; a++) i += d(t - a) * l(a).x;
					return i;
				}, this.dpy = function(e) {
					for (var t = (s + 2) * e - 1, n = Math.ceil(t - 2), r = Math.floor(t + 2), i = 0, a = n; a <= r; a++) i += d(t - a) * l(a).y;
					return i;
				};
			}
			return jt(e, [
				{
					key: `position`,
					value: function(e) {
						return new U.Point(this.px(e), this.py(e));
					}
				},
				{
					key: `angle`,
					value: function(e) {
						return Math.atan2(this.dpy(e), this.dpx(e));
					}
				},
				{
					key: `toCubicBeziers`,
					value: function() {
						var e = [], t = this.cps, n = t[0], r = t[1], i = t[2], a = n.x, o = n.y, s = a + (r.x - a) / 3, c = o + (r.y - o) / 3, l = a + 2 * (r.x - a) / 3, u = o + 2 * (r.y - o) / 3, d = r.x + (i.x - r.x) / 3, f = r.y + (i.y - r.y) / 3, p = (l + d) / 2, m = (u + f) / 2, h = n, g = new U.Point(s, c), _ = new U.Point(l, u), v = new U.Point(p, m), y = new X.CubicBezier(h, g, _, v);
						e.push(y);
						for (var b = this.cps.length - 1, x = 2; x < b; x++) n = r, r = i, i = t[x + 1], a = p, o = m, s = 2 * p - l, c = 2 * m - u, l = n.x + 2 * (r.x - n.x) / 3, u = n.y + 2 * (r.y - n.y) / 3, p = (l + (d = r.x + (i.x - r.x) / 3)) / 2, m = (u + (f = r.y + (i.y - r.y) / 3)) / 2, h = v, g = new U.Point(s, c), _ = new U.Point(l, u), v = new U.Point(p, m), y = new X.CubicBezier(h, g, _, v), e.push(y);
						return n = r, r = i, a = p, o = m, s = 2 * p - l, c = 2 * m - u, l = n.x + 2 * (r.x - n.x) / 3, u = n.y + 2 * (r.y - n.y) / 3, p = r.x, m = r.y, h = v, g = new U.Point(s, c), _ = new U.Point(l, u), v = new U.Point(p, m), y = new X.CubicBezier(h, g, _, v), e.push(y), e;
					}
				},
				{
					key: `countOfSegments`,
					value: function() {
						return this.cps.length - 1;
					}
				}
			]), e;
		}(), X.Line = function() {
			function e(t, n) {
				kt(this, e), this.s = t, this.e = n;
			}
			return jt(e, [
				{
					key: `position`,
					value: function(e) {
						return new U.Point(this.s.x + e * (this.e.x - this.s.x), this.s.y + e * (this.e.y - this.s.y));
					}
				},
				{
					key: `slice`,
					value: function(e, t) {
						if (!(e >= t)) {
							if (e < 0 && (e = 0), t > 1 && (t = 1), e === 0 && t === 1) return this;
							var n = this.s, r = this.e, i = r.x - n.x, a = r.y - n.y, o = new U.Point(n.x + e * i, n.y + e * a), s = new U.Point(n.x + t * i, n.y + t * a);
							return new X.Line(o, s);
						}
					}
				},
				{
					key: `tOfIntersections`,
					value: function(e) {
						if (e.isPoint()) return [];
						var t = this.s, n = this.e;
						if (e.isRect()) {
							var r, i = e.x + e.r, a = e.x - e.l, o = e.y + e.u, s = e.y - e.d, c = t.x, l = t.y, u = n.x - c, d = n.y - l, f = function(e) {
								return c + e * u;
							}, p = function(e) {
								return l + e * d;
							}, m = [];
							r = (r = X.solutionsOfLinearEq(u, c - i)).concat(X.solutionsOfLinearEq(u, c - a));
							for (var h = 0; h < r.length; h++) {
								var g = p(_ = r[h]);
								g >= s && g <= o && m.push(_);
							}
							for (r = (r = X.solutionsOfLinearEq(d, l - o)).concat(X.solutionsOfLinearEq(d, l - s)), h = 0; h < r.length; h++) {
								var _, v = f(_ = r[h]);
								v >= a && v <= i && m.push(_);
							}
							return m;
						}
						if (e.isCircle()) {
							var y = e.l, b = e.r, x = e.u, S = e.d, C = e.x + (b - y) / 2, w = e.y + (x - S) / 2, T = (i = (y + b) / 2, (x + S) / 2), E = t.x, D = t.y, ee = n.x - E, te = -ee, ne = (s = n.y - D) * i, O = te * T, re = ne * ne + O * O, ie = (n = -(S = ne * C + O * w + ((ee * D - s * E) * i + (i - T) * te * w)) / re, re * i * i - S * S);
							if (ie < 0) return [];
							var ae, oe, se = Math.sqrt(ie) / re, ce = T / i, le = ne * n + O * se + C, ue = ce * (O * n - ne * se + w - w) + w, de = ne * n - O * se + C, fe = ce * (O * n + ne * se + w - w) + w;
							return Math.abs(ee) > Math.abs(s) ? (ae = (le - E) / ee, oe = (de - E) / ee) : (ae = (ue - D) / s, oe = (fe - D) / s), m = [], ae >= 0 && ae <= 1 && m.push(ae), oe >= 0 && oe <= 1 && m.push(oe), m;
						}
					}
				},
				{
					key: `toShape`,
					value: function(e, t, n, r) {
						var i = e.env, a = A.measure.thickness, o = this.s, s = this.e;
						if (o.x !== s.x || o.y !== s.y) {
							var c, l = s.x - o.x, u = s.y - o.y, d = Math.atan2(u, l), f = Y.none;
							switch (n) {
								case `=`:
									n = `-`, r = `2`;
									break;
								case `==`:
									n = `--`, r = `2`;
									break;
								case `:`:
								case `::`: n = `.`, r = `2`;
							}
							switch (n) {
								case ``: return i.angle = d, i.lastCurve = new Q.Line(o, s, i.p, i.c, void 0), f;
								case `-`:
								case `.`:
								case `..`:
									switch (r) {
										case `2`:
											c = a / 2;
											break;
										case `3`:
											c = a;
											break;
										default: c = 0;
									}
									break;
								case `--`:
									var p = 3 * a;
									if ((g = Math.sqrt(l * l + u * u)) >= p) switch (r) {
										case `2`:
											c = a / 2;
											break;
										case `3`:
											c = a;
											break;
										default: c = 0;
									}
									break;
								case `~`:
								case `~~`:
									switch (r) {
										case `2`:
											c = 1.5 * a;
											break;
										case `3`:
											c = 2 * a;
											break;
										default: c = 0;
									}
									break;
								default:
									var m = t.boundingBox(e);
									if (m == null) return i.angle = 0, i.lastCurve = Q.none, Y.none;
									var h = m.l + m.r;
									h == 0 && (h = A.measure.strokeWidth);
									var g = Math.sqrt(l * l + u * u);
									if (Math.floor(g / h) == 0) return i.angle = 0, i.lastCurve = Q.none, Y.none;
									c = Math.max(m.u, m.d);
							}
							if (c !== void 0) {
								var _ = this.boundingBox(c);
								return f = new Y.LineShape(this, t, n, r, _), e.appendShapeToFront(f), i.angle = d, i.lastCurve = new Q.Line(o, s, i.p, i.c, f), f;
							}
						}
						return i.angle = 0, i.lastCurve = Q.none, Y.none;
					}
				},
				{
					key: `boundingBox`,
					value: function(e) {
						var t = this.s, n = this.e, r = n.x - t.x, i = n.y - t.y, a = Math.atan2(i, r), o = e * Math.cos(a + Math.PI / 2), s = e * Math.sin(a + Math.PI / 2);
						return new U.Rect(t.x, t.y, {
							l: t.x - Math.min(t.x + o, t.x - o, n.x + o, n.x - o),
							r: Math.max(t.x + o, t.x - o, n.x + o, n.x - o) - t.x,
							u: Math.max(t.y + s, t.y - s, n.y + s, n.y - s) - t.y,
							d: t.y - Math.min(t.y + s, t.y - s, n.y + s, n.y - s)
						});
					}
				},
				{
					key: `drawLine`,
					value: function(e, t, n, r, i) {
						if (i.isEmpty) this._drawLine(e, t, n, r);
						else {
							var a = new bt(0, 1).differenceRanges(i), o = this;
							a.foreach((function(i) {
								o.slice(i.start, i.end)._drawLine(e, t, n, r);
							}));
						}
					}
				},
				{
					key: `_drawLine`,
					value: function(e, t, n, r) {
						var i = A.measure.thickness, a = this.s, o = this.e;
						if (a.x !== o.x || a.y !== o.y) {
							var s = o.x - a.x, c = o.y - a.y, l = Math.atan2(c, s), u = {
								x: 0,
								y: 0
							};
							switch (n) {
								case ``: break;
								case `-`:
									this.drawStraightLine(e, a, o, u, l, i, r, ``);
									break;
								case `=`:
									this.drawStraightLine(e, a, o, u, l, i, `2`, ``);
									break;
								case `.`:
								case `..`:
									this.drawStraightLine(e, a, o, u, l, i, r, A.measure.dottedDasharray);
									break;
								case `:`:
								case `::`:
									this.drawStraightLine(e, a, o, u, l, i, `2`, A.measure.dottedDasharray);
									break;
								case `--`:
								case `==`:
									var d = 3 * i;
									(E = Math.sqrt(s * s + c * c)) >= d && (u = {
										x: (D = (E - d) / 2 - Math.floor((E - d) / 2 / d) * d) * Math.cos(l),
										y: D * Math.sin(l)
									}, this.drawStraightLine(e, a, o, u, l, i, n === `==` ? `2` : r, A.measure.em2px(d) + ` ` + A.measure.em2px(d)));
									break;
								case `~`:
									if ((E = Math.sqrt(s * s + c * c)) >= (b = 4 * i)) {
										u = {
											x: (D = (E - (T = Math.floor(E / b)) * b) / 2) * Math.cos(l),
											y: D * Math.sin(l)
										};
										for (var f = i * Math.cos(l + Math.PI / 2), p = i * Math.sin(l + Math.PI / 2), m = i * Math.cos(l), h = i * Math.sin(l), g = a.x + u.x, _ = -a.y - u.y, v = `M` + A.measure.em2px(g) + `,` + A.measure.em2px(_) + ` Q` + A.measure.em2px(g + m + f) + `,` + A.measure.em2px(_ - h - p) + ` ` + A.measure.em2px(g + 2 * m) + `,` + A.measure.em2px(_ - 2 * h) + ` T` + A.measure.em2px(g + 4 * m) + `,` + A.measure.em2px(_ - 4 * h), y = 1; y < T; y++) v += ` T` + A.measure.em2px(g + (4 * y + 2) * m) + `,` + A.measure.em2px(_ - (4 * y + 2) * h) + ` T` + A.measure.em2px(g + (4 * y + 4) * m) + `,` + A.measure.em2px(_ - (4 * y + 4) * h);
										this.drawSquigglyLineShape(e, v, a, o, f, p, r);
									}
									break;
								case `~~`:
									var b;
									if ((E = Math.sqrt(s * s + c * c)) >= (b = 4 * i)) {
										for (u = {
											x: (D = (E - b) / 2 - (T = Math.floor((E - b) / 2 / b)) * b) * Math.cos(l),
											y: D * Math.sin(l)
										}, f = i * Math.cos(l + Math.PI / 2), p = i * Math.sin(l + Math.PI / 2), m = i * Math.cos(l), h = i * Math.sin(l), g = a.x + u.x, _ = -a.y - u.y, v = ``, y = 0; y <= T; y++) v += ` M` + A.measure.em2px(g + 8 * y * m) + `,` + A.measure.em2px(_ - 8 * y * h) + ` Q` + A.measure.em2px(g + (8 * y + 1) * m + f) + `,` + A.measure.em2px(_ - (8 * y + 1) * h - p) + ` ` + A.measure.em2px(g + (8 * y + 2) * m) + `,` + A.measure.em2px(_ - (8 * y + 2) * h) + ` T` + A.measure.em2px(g + (8 * y + 4) * m) + `,` + A.measure.em2px(_ - (8 * y + 4) * h);
										this.drawSquigglyLineShape(e, v, a, o, f, p, r);
									}
									break;
								default:
									var x = new Mt();
									x.c = Mt.originPosition;
									var S = new St(Y.none, x), C = t.boundingBox(S);
									if (C == null) return;
									var w = C.l + C.r;
									w == 0 && (w = A.measure.strokeWidth);
									var T, E = Math.sqrt(s * s + c * c);
									if ((T = Math.floor(E / w)) == 0) return;
									var D = (E - T * w) / 2, ee = Math.cos(l), te = Math.sin(l), ne = w * ee, O = w * te, re = a.x + (D + C.l) * ee, ie = a.y + (D + C.l) * te;
									for (S = new St(Y.none, x), y = 0; y < T; y++) x.c = new U.Point(re + y * ne, ie + y * O), x.angle = l, t.toDropShape(S).draw(e);
							}
						}
					}
				},
				{
					key: `drawStraightLine`,
					value: function(e, t, n, r, i, a, o, s) {
						if (o === `3`) {
							var c = a * Math.cos(i + Math.PI / 2), l = a * Math.sin(i + Math.PI / 2);
							e.createSVGElement(`line`, {
								x1: A.measure.em2px(t.x + r.x),
								y1: -A.measure.em2px(t.y + r.y),
								x2: A.measure.em2px(n.x),
								y2: -A.measure.em2px(n.y),
								"stroke-dasharray": s
							}), e.createSVGElement(`line`, {
								x1: A.measure.em2px(t.x + c + r.x),
								y1: -A.measure.em2px(t.y + l + r.y),
								x2: A.measure.em2px(n.x + c),
								y2: -A.measure.em2px(n.y + l),
								"stroke-dasharray": s
							}), e.createSVGElement(`line`, {
								x1: A.measure.em2px(t.x - c + r.x),
								y1: -A.measure.em2px(t.y - l + r.y),
								x2: A.measure.em2px(n.x - c),
								y2: -A.measure.em2px(n.y - l),
								"stroke-dasharray": s
							});
						} else o === `2` ? (c = a * Math.cos(i + Math.PI / 2) / 2, l = a * Math.sin(i + Math.PI / 2) / 2, e.createSVGElement(`line`, {
							x1: A.measure.em2px(t.x + c + r.x),
							y1: -A.measure.em2px(t.y + l + r.y),
							x2: A.measure.em2px(n.x + c),
							y2: -A.measure.em2px(n.y + l),
							"stroke-dasharray": s
						}), e.createSVGElement(`line`, {
							x1: A.measure.em2px(t.x - c + r.x),
							y1: -A.measure.em2px(t.y - l + r.y),
							x2: A.measure.em2px(n.x - c),
							y2: -A.measure.em2px(n.y - l),
							"stroke-dasharray": s
						})) : e.createSVGElement(`line`, {
							x1: A.measure.em2px(t.x + r.x),
							y1: -A.measure.em2px(t.y + r.y),
							x2: A.measure.em2px(n.x),
							y2: -A.measure.em2px(n.y),
							"stroke-dasharray": s
						});
					}
				},
				{
					key: `drawSquigglyLineShape`,
					value: function(e, t, n, r, i, a, o) {
						o === `3` ? (e.createSVGElement(`path`, { d: t }), e.createGroup(e.transformBuilder().translate(i, a)).createSVGElement(`path`, { d: t }), e.createGroup(e.transformBuilder().translate(-i, -a)).createSVGElement(`path`, { d: t })) : o === `2` ? (e.createGroup(e.transformBuilder().translate(i / 2, a / 2)).createSVGElement(`path`, { d: t }), e.createGroup(e.transformBuilder().translate(-i / 2, -a / 2)).createSVGElement(`path`, { d: t })) : e.createSVGElement(`path`, { d: t });
					}
				}
			]), e;
		}();
		var Z = function() {
			function e() {
				kt(this, e);
			}
			return jt(e, [{
				key: `bezierFatLine`,
				value: function(e) {
					var t, n, r, i, a = this.cps[0], o = this.cps[e];
					if (a.x !== o.x || a.y !== o.y) t = a.y - o.y, n = o.x - a.x, t /= i = Math.sqrt(t * t + n * n), n /= i, r = (a.x * o.y - a.y * o.x) / i;
					else {
						var s = this.bezier.angle(this.tmin);
						t = -Math.sin(s), n = Math.cos(s), r = -t * this.cp0.x - n * this.cp0.y;
					}
					for (var c = r, l = r, u = 1; u < e; u++) {
						var d = -t * this.cps[u].x - n * this.cps[u].y;
						d > l ? l = d : d < c && (c = d);
					}
					return {
						min: [
							t,
							n,
							c
						],
						max: [
							t,
							n,
							l
						]
					};
				}
			}, {
				key: `clippedLineRange`,
				value: function(e, t, n) {
					for (var r, i, a, o, s, c = e.length - 1, l = Array(c + 1), u = tt, d = 0; d <= c; d++) l[d] = [
						d / c,
						-t[0] * e[d].x - t[1] * e[d].y - t[2],
						1
					];
					if (l[0][1] < 0) {
						var f = !0;
						for (d = 1; d <= c; d++) (r = -(m = u(l[0], l[d]))[2] / m[0]) > 0 && r < 1 && (i === void 0 || r < i) && (i = r), l[d][1] >= 0 && (f = !1);
						if (f) return;
					} else i = 0;
					if (l[c][1] < 0) for (d = 0; d < c; d++) (r = -(h = u(l[c], l[d]))[2] / h[0]) > 0 && r < 1 && (a === void 0 || r > a) && (a = r);
					else a = 1;
					for (d = 0; d <= c; d++) l[d] = [
						d / c,
						n[0] * e[d].x + n[1] * e[d].y + n[2],
						1
					];
					if (l[0][1] < 0) {
						var p = !0;
						for (d = 1; d <= c; d++) {
							var m;
							(r = -(m = u(l[0], l[d]))[2] / m[0]) > 0 && r < 1 && (o === void 0 || r < o) && (o = r), l[d][1] >= 0 && (p = !1);
						}
						if (p) return;
					} else o = 0;
					if (l[c][1] < 0) for (d = 0; d < c; d++) {
						var h;
						(r = -(h = u(l[c], l[d]))[2] / h[0]) > 0 && r < 1 && (s === void 0 || r > s) && (s = r);
					}
					else s = 1;
					var g = Math.max(i, o), _ = Math.min(a, s);
					return {
						min: this.tmin + g * (this.tmax - this.tmin),
						max: this.tmin + _ * (this.tmax - this.tmin)
					};
				}
			}], [
				{
					key: `findIntersections`,
					value: function(t, n) {
						for (var r = e.maxIterations, i = e.goalAccuracy, a = [[
							t,
							n,
							!1
						]], o = 0, s = []; o < r && a.length > 0;) {
							o++;
							var c = a.shift(), l = (t = c[0], n = c[1], c[2]), u = t.fatLine(), d = n.clippedRange(u.min, u.max);
							if (d != null) {
								var f = d.min, p = d.max, m = p - f;
								if (m < i && t.paramLength() < i) l ? s.push([n.clip(f, p).paramRange(), t.paramRange()]) : s.push([t.paramRange(), n.clip(f, p).paramRange()]);
								else if (m <= .8 * n.paramLength()) a.push([
									n.clip(f, p),
									t,
									!l
								]);
								else if (m > t.paramLength()) {
									var h = (p + f) / 2;
									a.push([
										n.clip(f, h),
										t,
										!l
									]), a.push([
										n.clip(h, p),
										t,
										!l
									]);
								} else {
									var g = n.clip(f, p), _ = t.paramRange(), v = (_.min + _.max) / 2;
									a.push([
										g,
										t.clip(_.min, v),
										!l
									]), a.push([
										g,
										t.clip(v, _.max),
										!l
									]);
								}
							}
						}
						return s;
					}
				},
				{
					key: `maxIterations`,
					get: function() {
						return 30;
					}
				},
				{
					key: `goalAccuracy`,
					get: function() {
						return 1e-4;
					}
				}
			]), e;
		}();
		Z.Line = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e, r, i, a) {
				var o;
				return kt(this, n), (o = t.call(this)).p0 = e, o.p1 = r, o.tmin = i, o.tmax = a, o;
			}
			return jt(n, [
				{
					key: `paramRange`,
					value: function() {
						return {
							min: this.tmin,
							max: this.tmax
						};
					}
				},
				{
					key: `paramLength`,
					value: function() {
						return this.tmax - this.tmin;
					}
				},
				{
					key: `containsParam`,
					value: function(e) {
						return e >= this.tmin && e <= this.tmax;
					}
				},
				{
					key: `position`,
					value: function(e) {
						return {
							x: this.p0.x + e * (this.p1.x - this.p0.x),
							y: this.p0.y + e * (this.p1.y - this.p0.y)
						};
					}
				},
				{
					key: `fatLine`,
					value: function() {
						var e = this.p1.y - this.p0.y, t = this.p0.x - this.p1.x, n = this.p1.x * this.p0.y - this.p0.x * this.p1.y, r = Math.sqrt(e * e + t * t);
						return r === 0 ? (e = 1, t = 0) : (e /= r, t /= r, n /= r), {
							min: [
								e,
								t,
								n
							],
							max: [
								e,
								t,
								n
							]
						};
					}
				},
				{
					key: `clip`,
					value: function(e, t) {
						return new Z.Line(this.p0, this.p1, e, t);
					}
				},
				{
					key: `clippedRange`,
					value: function(e, t) {
						var n = [, ,];
						return n[0] = this.position(this.tmin), n[1] = this.position(this.tmax), this.clippedLineRange(n, e, t);
					}
				},
				{
					key: `drawFatLine`,
					value: function() {
						this.fatLine().min;
						var e = function(e, t) {
							return -(e * t[0] + t[2]) / t[1];
						}, t = this.p0.x, n = this.p1.x;
						A.svgForDebug.createSVGElement(`line`, {
							x1: A.measure.em2px(t),
							y1: -A.measure.em2px(e(t, lmax)),
							x2: A.measure.em2px(n),
							y2: -A.measure.em2px(e(n, lmax)),
							"stroke-width": A.measure.em2px(.02 * A.measure.oneem),
							stroke: `red`
						});
					}
				}
			]), n;
		}(Z), Z.QuadBezier = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e, r, i) {
				var a;
				return kt(this, n), (a = t.call(this)).bezier = e, a.tmin = r, a.tmax = i, a.cp0 = e.position(r), a.cp1 = new U.Point((1 - i) * (1 - r) * e.cp0.x + (r + i - 2 * r * i) * e.cp1.x + r * i * e.cp2.x, (1 - i) * (1 - r) * e.cp0.y + (r + i - 2 * r * i) * e.cp1.y + r * i * e.cp2.y), a.cp2 = e.position(i), a.cps = [
					a.cp0,
					a.cp1,
					a.cp2
				], a;
			}
			return jt(n, [
				{
					key: `paramRange`,
					value: function() {
						return {
							min: this.tmin,
							max: this.tmax
						};
					}
				},
				{
					key: `paramLength`,
					value: function() {
						return this.tmax - this.tmin;
					}
				},
				{
					key: `fatLine`,
					value: function() {
						return this.bezierFatLine(2);
					}
				},
				{
					key: `clip`,
					value: function(e, t) {
						return new Z.QuadBezier(this.bezier, e, t);
					}
				},
				{
					key: `clippedRange`,
					value: function(e, t) {
						return this.clippedLineRange(this.cps, e, t);
					}
				},
				{
					key: `drawFatLine`,
					value: function() {
						var e = this.fatLine(), t = e.min, n = e.max, r = function(e, t) {
							return -(e * t[0] + t[2]) / t[1];
						}, i = this.cp0.x, a = this.cp2.x;
						A.svgForDebug.createSVGElement(`line`, {
							x1: A.measure.em2px(i),
							y1: -A.measure.em2px(r(i, t)),
							x2: A.measure.em2px(a),
							y2: -A.measure.em2px(r(a, t)),
							"stroke-width": A.measure.em2px(.02 * A.measure.oneem),
							stroke: `blue`
						}), A.svgForDebug.createSVGElement(`line`, {
							x1: A.measure.em2px(i),
							y1: -A.measure.em2px(r(i, n)),
							x2: A.measure.em2px(a),
							y2: -A.measure.em2px(r(a, n)),
							"stroke-width": A.measure.em2px(.02 * A.measure.oneem),
							stroke: `red`
						});
					}
				}
			]), n;
		}(Z), Z.CubicBezier = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e, r, i) {
				var a;
				return kt(this, n), (a = t.call(this)).bezier = e, a.tmin = r, a.tmax = i, a.cp0 = e.position(r), a.cp1 = new U.Point((1 - i) * (1 - r) * (1 - r) * e.cp0.x + (1 - r) * (2 * r + i - 3 * r * i) * e.cp1.x + r * (2 * i + r - 3 * r * i) * e.cp2.x + r * r * i * e.cp3.x, (1 - i) * (1 - r) * (1 - r) * e.cp0.y + (1 - r) * (2 * r + i - 3 * r * i) * e.cp1.y + r * (2 * i + r - 3 * r * i) * e.cp2.y + r * r * i * e.cp3.y), a.cp2 = new U.Point((1 - r) * (1 - i) * (1 - i) * e.cp0.x + (1 - i) * (2 * i + r - 3 * r * i) * e.cp1.x + i * (2 * r + i - 3 * r * i) * e.cp2.x + r * i * i * e.cp3.x, (1 - r) * (1 - i) * (1 - i) * e.cp0.y + (1 - i) * (2 * i + r - 3 * r * i) * e.cp1.y + i * (2 * r + i - 3 * r * i) * e.cp2.y + r * i * i * e.cp3.y), a.cp3 = e.position(i), a.cps = [
					a.cp0,
					a.cp1,
					a.cp2,
					a.cp3
				], a;
			}
			return jt(n, [
				{
					key: `paramRange`,
					value: function() {
						return {
							min: this.tmin,
							max: this.tmax
						};
					}
				},
				{
					key: `paramLength`,
					value: function() {
						return this.tmax - this.tmin;
					}
				},
				{
					key: `fatLine`,
					value: function() {
						return this.bezierFatLine(3);
					}
				},
				{
					key: `clip`,
					value: function(e, t) {
						return new Z.CubicBezier(this.bezier, e, t);
					}
				},
				{
					key: `clippedRange`,
					value: function(e, t) {
						return this.clippedLineRange(this.cps, e, t);
					}
				},
				{
					key: `drawFatLine`,
					value: function() {
						var e = this.fatLine(), t = e.min, n = e.max, r = function(e, t) {
							return -(e * t[0] + t[2]) / t[1];
						}, i = this.cp0.x, a = this.cp3.x;
						A.svgForDebug.createSVGElement(`line`, {
							x1: A.measure.em2px(i),
							y1: -A.measure.em2px(r(i, t)),
							x2: A.measure.em2px(a),
							y2: -A.measure.em2px(r(a, t)),
							"stroke-width": A.measure.em2px(.02 * A.measure.oneem),
							stroke: `blue`
						}), A.svgForDebug.createSVGElement(`line`, {
							x1: A.measure.em2px(i),
							y1: -A.measure.em2px(r(i, n)),
							x2: A.measure.em2px(a),
							y2: -A.measure.em2px(r(a, n)),
							"stroke-width": A.measure.em2px(.02 * A.measure.oneem),
							stroke: `red`
						});
					}
				}
			]), n;
		}(Z), Z.Arc = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e, r, i, a, o, s) {
				var c;
				return kt(this, n), (c = t.call(this)).x = e, c.y = r, c.rx = i, c.ry = a, c.angleMin = o, c.angleMax = s, c;
			}
			return jt(n, [
				{
					key: `paramRange`,
					value: function() {
						return {
							min: this.angleMin,
							max: this.angleMax
						};
					}
				},
				{
					key: `paramLength`,
					value: function() {
						return this.angleMax - this.angleMin;
					}
				},
				{
					key: `normalizeAngle`,
					value: function(e) {
						return (e = e % 2 * Math.PI) > Math.PI ? e - 2 * Math.PI : e < -Math.PI ? e + 2 * Math.PI : e;
					}
				},
				{
					key: `containsParam`,
					value: function(e) {
						return e >= this.angleMin && e <= this.angleMax;
					}
				},
				{
					key: `fatLine`,
					value: function() {
						var e = this.rx, t = this.ry, n = (this.angleMax + this.angleMin) / 2, r = (this.angleMax - this.angleMin) / 2, i = Math.cos(n), a = Math.sin(n), o = Math.sqrt(e * e * a * a + t * t * i * i);
						if (o < l.machinePrecision) var s = [
							1,
							0,
							this.x * t * i + this.y * e * a + e * t * Math.cos(r)
						], c = [
							1,
							0,
							this.x * t * i + this.y * e * a + e * t
						];
						else {
							var u = e / o, d = t / o;
							s = [
								-d * i,
								-u * a,
								this.x * d * i + this.y * u * a + e * t / o * Math.cos(r)
							], c = [
								-d * i,
								-u * a,
								this.x * d * i + this.y * u * a + e * t / o
							];
						}
						return {
							min: s,
							max: c
						};
					}
				},
				{
					key: `clip`,
					value: function(e, t) {
						return new Z.Arc(this.x, this.y, this.rx, this.ry, e, t);
					}
				},
				{
					key: `toCircleLine`,
					value: function(e, t, n, r, i) {
						var a = e[0], o = e[1], s = a * r, c = o * i, u = e[2] * r + (r - i) * o * n, d = Math.sqrt(s * s + c * c);
						return d < l.machinePrecision ? (s = 1, c = 0) : (s /= d, c /= d, u /= d), [
							s,
							c,
							u
						];
					}
				},
				{
					key: `clippedRange`,
					value: function(e, t) {
						var n = this.x, r = this.y, i = this.rx, a = this.ry, o = this.toCircleLine(e, n, r, i, a), s = this.toCircleLine(t, n, r, i, a), c = i, l = this.angleMin, u = this.angleMax, d = -(o[0] * n + o[1] * r + o[2]), f = [];
						if (c * c - d * d >= 0) {
							var p = o[0] * d - o[1] * Math.sqrt(c * c - d * d), m = o[1] * d + o[0] * Math.sqrt(c * c - d * d), h = o[0] * d + o[1] * Math.sqrt(c * c - d * d), g = o[1] * d - o[0] * Math.sqrt(c * c - d * d), _ = Math.atan2(m, p), v = Math.atan2(g, h);
							this.containsParam(_) && f.push(_), this.containsParam(v) && f.push(v);
						}
						var y, b, x = -(o[0] * (n + c * Math.cos(l)) + o[1] * (r + c * Math.sin(l)) + o[2]), S = -(o[0] * (n + c * Math.cos(u)) + o[1] * (r + c * Math.sin(u)) + o[2]);
						if (x < 0) {
							if (f.length == 0) return;
							y = Math.min.apply(Math, f);
						} else y = this.angleMin;
						if (S < 0) {
							if (f.length == 0) return;
							b = Math.max.apply(Math, f);
						} else b = this.angleMax;
						f = [], c * c - (d = s[0] * n + s[1] * r + s[2]) * d >= 0 && (p = -o[0] * d + o[1] * Math.sqrt(c * c - d * d), m = -o[1] * d - o[0] * Math.sqrt(c * c - d * d), h = -o[0] * d - o[1] * Math.sqrt(c * c - d * d), g = -o[1] * d + o[0] * Math.sqrt(c * c - d * d), _ = Math.atan2(m, p), v = Math.atan2(g, h), this.containsParam(_) && f.push(_), this.containsParam(v) && f.push(v));
						var C, w;
						if (x = s[0] * (n + c * Math.cos(l)) + s[1] * (r + c * Math.sin(l)) + s[2], S = s[0] * (n + c * Math.cos(u)) + s[1] * (r + c * Math.sin(u)) + s[2], x < 0) {
							if (f.length == 0) return;
							C = Math.min.apply(Math, f);
						} else C = this.angleMin;
						if (S < 0) {
							if (f.length == 0) return;
							w = Math.max.apply(Math, f);
						} else w = this.angleMax;
						return {
							min: Math.max(y, C),
							max: Math.min(b, w)
						};
					}
				},
				{
					key: `drawFatLine`,
					value: function() {
						var e = this.fatLine(), t = e.min, n = e.max, r = function(e, t) {
							return -(e * t[0] + t[2]) / t[1];
						}, i = this.x + this.r * Math.cos(this.angleMin), a = this.x + this.r * Math.cos(this.angleMax);
						A.svgForDebug.createSVGElement(`line`, {
							x1: A.measure.em2px(i),
							y1: -A.measure.em2px(r(i, t)),
							x2: A.measure.em2px(a),
							y2: -A.measure.em2px(r(a, t)),
							"stroke-width": A.measure.em2px(.02 * A.measure.oneem),
							stroke: `blue`
						}), A.svgForDebug.createSVGElement(`line`, {
							x1: A.measure.em2px(i),
							y1: -A.measure.em2px(r(i, n)),
							x2: A.measure.em2px(a),
							y2: -A.measure.em2px(r(a, n)),
							"stroke-width": A.measure.em2px(.02 * A.measure.oneem),
							stroke: `red`
						});
					}
				}
			]), n;
		}(Z);
		var Q = function e() {
			kt(this, e);
		};
		function Nt(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function Pt(e, t, n) {
			return t && Nt(e.prototype, t), n && Nt(e, n), e;
		}
		function Ft(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		Q.None = function(e) {
			wt(n, e);
			var t = Et(n);
			function n() {
				return kt(this, n), t.call(this);
			}
			return jt(n, [
				{
					key: `isDefined`,
					get: function() {
						return !1;
					}
				},
				{
					key: `segments`,
					value: function() {
						return [];
					}
				},
				{
					key: `angle`,
					value: function() {
						return 0;
					}
				}
			]), n;
		}(Q), Q.none = new Q.None(), Q.Line = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e, r, i, a, o) {
				var s;
				return kt(this, n), (s = t.call(this)).start = e, s.end = r, s.p = i, s.c = a, s.lineShape = o, s;
			}
			return jt(n, [
				{
					key: `isDefined`,
					get: function() {
						return !0;
					}
				},
				{
					key: `position`,
					value: function(e) {
						return new U.Point(this.p.x + e * (this.c.x - this.p.x), this.p.y + e * (this.c.y - this.p.y));
					}
				},
				{
					key: `derivative`,
					value: function(e) {
						return new U.Point(this.c.x - this.p.x, this.c.y - this.p.y);
					}
				},
				{
					key: `angle`,
					value: function(e) {
						var t = this.c.x - this.p.x, n = this.c.y - this.p.y;
						return t === 0 && n === 0 ? 0 : Math.atan2(n, t);
					}
				},
				{
					key: `tOfPlace`,
					value: function(e, t, n, r) {
						var i = e ? this.start : this.p, a = t ? this.end : this.c;
						if (i.x === a.x && i.y === a.y) return 0;
						var o, s, c = a.x - i.x, l = a.y - i.y, u = Math.sqrt(c * c + l * l);
						n > .5 ? (o = a.x - (1 - n) * c + r * c / u, s = a.y - (1 - n) * l + r * l / u) : (o = i.x + n * c + r * c / u, s = i.y + n * l + r * l / u);
						var d = this.c.x - this.p.x, f = this.c.y - this.p.y;
						return d === 0 && f === 0 ? 0 : Math.abs(d) > Math.abs(f) ? (o - this.p.x) / d : (s - this.p.y) / f;
					}
				},
				{
					key: `sliceHole`,
					value: function(e, t) {
						if (this.lineShape !== void 0 && !e.isPoint()) {
							var n = this.lineShape, r = n.line, i = r.tOfIntersections(e);
							i.push(0), i.push(1), i.sort();
							for (var a = i[0], o = 1; o < i.length; o++) {
								var s = i[o], c = r.position((s + a) / 2);
								if (e.contains(c)) {
									var l = new bt(a, s);
									n.sliceHole(l);
								}
								a = s;
							}
						}
					}
				},
				{
					key: `segments`,
					value: function() {
						return [new Z.Line(this.p, this.c, 0, 1)];
					}
				}
			]), n;
		}(Q), Q.QuadBezier = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e, r, i, a) {
				var o;
				return kt(this, n), (o = t.call(this)).origBezier = e, o.tOfShavedStart = r, o.tOfShavedEnd = i, a.isNone || (o.curveShape = a, r > 0 && a.sliceHole(new bt(0, r)), i < 1 && a.sliceHole(new bt(i, 1))), o;
			}
			return jt(n, [
				{
					key: `isDefined`,
					get: function() {
						return !0;
					}
				},
				{
					key: `position`,
					value: function(e) {
						return this.origBezier.position(e);
					}
				},
				{
					key: `derivative`,
					value: function(e) {
						return this.origBezier.derivative(e);
					}
				},
				{
					key: `angle`,
					value: function(e) {
						return this.origBezier.angle(e);
					}
				},
				{
					key: `tOfPlace`,
					value: function(e, t, n, r) {
						var i, a;
						e ? (i = this.tOfShavedStart, a = t ? this.tOfShavedEnd - this.tOfShavedStart : 1 - this.tOfShavedStart) : (i = 0, a = t ? this.tOfShavedEnd : 1);
						var o = this.origBezier, s = i + a * n;
						if (r !== 0) {
							var c = o.length(s);
							s = o.tOfLength(c + r);
						}
						return s;
					}
				},
				{
					key: `sliceHole`,
					value: function(e, t) {
						var n = this.curveShape;
						if (n !== void 0 && !e.isPoint()) {
							var r = n.curve, i = r.tOfIntersections(e);
							i.push(0), i.push(1), i.sort();
							for (var a = i[0], o = 1; o < i.length; o++) {
								var s = i[o];
								if (a <= t && t <= s) {
									var c = r.position((s + a) / 2);
									if (e.contains(c)) {
										var l = new bt(a, s);
										n.sliceHole(l);
									}
								}
								a = s;
							}
						}
					}
				},
				{
					key: `segments`,
					value: function() {
						return [new Z.QuadBezier(this.origBezier, 0, 1)];
					}
				}
			]), n;
		}(Q), Q.CubicBezier = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e, r, i, a) {
				var o;
				return kt(this, n), (o = t.call(this)).origBezier = e, o.tOfShavedStart = r, o.tOfShavedEnd = i, a.isNone || (o.curveShape = a, r > 0 && a.sliceHole(new bt(0, r)), i < 1 && a.sliceHole(new bt(i, 1))), o;
			}
			return jt(n, [
				{
					key: `originalLine`,
					value: function() {
						return this.originalLine;
					}
				},
				{
					key: `isDefined`,
					get: function() {
						return !0;
					}
				},
				{
					key: `position`,
					value: function(e) {
						return this.origBezier.position(e);
					}
				},
				{
					key: `derivative`,
					value: function(e) {
						return this.origBezier.derivative(e);
					}
				},
				{
					key: `angle`,
					value: function(e) {
						return this.origBezier.angle(e);
					}
				},
				{
					key: `tOfPlace`,
					value: function(e, t, n, r) {
						var i, a;
						e ? (i = this.tOfShavedStart, a = t ? this.tOfShavedEnd - this.tOfShavedStart : 1 - this.tOfShavedStart) : (i = 0, a = t ? this.tOfShavedEnd : 1);
						var o = this.origBezier, s = i + a * n;
						if (r !== 0) {
							var c = o.length(s);
							s = o.tOfLength(c + r);
						}
						return s;
					}
				},
				{
					key: `sliceHole`,
					value: function(e, t) {
						var n = this.curveShape;
						if (n !== void 0 && !e.isPoint()) {
							var r = n.curve, i = r.tOfIntersections(e);
							i.push(0), i.push(1), i.sort();
							for (var a = i[0], o = 1; o < i.length; o++) {
								var s = i[o];
								if (a <= t && t <= s) {
									var c = r.position((s + a) / 2);
									if (e.contains(c)) {
										var l = new bt(a, s);
										n.sliceHole(l);
									}
								}
								a = s;
							}
						}
					}
				},
				{
					key: `segments`,
					value: function() {
						return [new Z.CubicBezier(this.origBezier, 0, 1)];
					}
				}
			]), n;
		}(Q), Q.CubicBSpline = function(e) {
			wt(n, e);
			var t = Et(n);
			function n(e, r, i, a, o, s) {
				var c;
				return kt(this, n), (c = t.call(this)).s = e, c.e = r, c.origBeziers = i, c.tOfShavedStart = a, c.tOfShavedEnd = o, s.isNone || (c.curveShape = s, a > 0 && s.sliceHole(new bt(0, a)), o < 1 && s.sliceHole(new bt(o, 1))), c;
			}
			return jt(n, [
				{
					key: `isDefined`,
					get: function() {
						return !0;
					}
				},
				{
					key: `position`,
					value: function(e) {
						return this.origBeziers.position(e);
					}
				},
				{
					key: `derivative`,
					value: function(e) {
						return this.origBeziers.derivative(e);
					}
				},
				{
					key: `angle`,
					value: function(e) {
						return this.origBeziers.angle(e);
					}
				},
				{
					key: `tOfPlace`,
					value: function(e, t, n, r) {
						var i, a;
						e ? (i = this.tOfShavedStart, a = t ? this.tOfShavedEnd - this.tOfShavedStart : 1 - this.tOfShavedStart) : (i = 0, a = t ? this.tOfShavedEnd : 1);
						var o = this.origBeziers, s = i + a * n;
						if (r !== 0) {
							var c = o.length(s);
							s = o.tOfLength(c + r);
						}
						return s;
					}
				},
				{
					key: `sliceHole`,
					value: function(e, t) {
						var n = this.curveShape;
						if (n !== void 0 && !e.isPoint()) {
							var r = n.curve, i = r.tOfIntersections(e);
							i.push(0), i.push(1), i.sort();
							for (var a = i[0], o = 1; o < i.length; o++) {
								var s = i[o];
								if (a <= t && t <= s) {
									var c = r.position((s + a) / 2);
									if (e.contains(c)) {
										var l = new bt(a, s);
										n.sliceHole(l);
									}
								}
								a = s;
							}
						}
					}
				},
				{
					key: `segments`,
					value: function() {
						for (var e = Array(this.origBeziers.length), t = e.length, n = 0; n < t; n++) e[n] = new Z.CubicBezier(this.origBezier, n / t, (n + 1) / t);
						return e;
					}
				}
			]), n;
		}(Q);
		var It = function e() {
			Ft(this, e);
		};
		function Lt(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		function Rt(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function zt(e, t, n) {
			return t && Rt(e.prototype, t), n && Rt(e, n), e;
		}
		function $(e, t) {
			for (var n in t) e.prototype.hasOwnProperty(n) ? console.log(`WARN`, `method ` + n + ` is already exists in class ` + e.name) : e.prototype[n] = t[n];
		}
		It.Position = function() {
			function e(t) {
				Ft(this, e), this.pos = t;
			}
			return Pt(e, [{
				key: `position`,
				value: function(e) {
					return this.pos;
				}
			}, {
				key: `toString`,
				value: function() {
					return this.pos.toString();
				}
			}]), e;
		}(), It.Macro = function() {
			function e(t) {
				Ft(this, e), this.macro = t;
			}
			return Pt(e, [{
				key: `position`,
				value: function(e) {
					return env.c = this.macro.position(e), env.c;
				}
			}, {
				key: `toString`,
				value: function() {
					return this.macro.toString();
				}
			}]), e;
		}(), It.Base = function() {
			function e(t, n, r) {
				Ft(this, e), this.origin = t, this.xBase = n, this.yBase = r;
			}
			return Pt(e, [{
				key: `position`,
				value: function(e) {
					var t = e.env;
					return t.origin = this.origin, t.xBase = this.xBase, t.yBase = this.yBase, t.c;
				}
			}, {
				key: `toString`,
				value: function() {
					return `origin:` + this.origin + `, xBase:` + this.xBase + `, yBase:` + this.yBase;
				}
			}]), e;
		}(), It.Stack = function() {
			function e(t) {
				Ft(this, e), this.stack = t;
			}
			return Pt(e, [{
				key: `position`,
				value: function(e) {
					var t = e.env;
					return this.stack.isEmpty || (this.stack.tail.reverse().foreach((function(e) {
						t.capturePosition(e);
					})), t.c = this.stack.head), t.c;
				}
			}, {
				key: `toString`,
				value: function() {
					return this.stack.toString();
				}
			}]), e;
		}(), $(F.PosDecor, { toShape: function(e) {
			this.pos.toShape(e), this.decor.toShape(e);
		} }), $(F.Pos.Coord, { toShape: function(e) {
			e.env.c = this.coord.position(e), this.pos2s.foreach((function(t) {
				t.toShape(e);
			}));
		} }), $(F.Pos.Plus, { toShape: function(e) {
			var t = e.env, n = this.coord.position(e);
			t.c = n.move(t.c.x + n.x, t.c.y + n.y);
		} }), $(F.Pos.Minus, { toShape: function(e) {
			var t = e.env, n = this.coord.position(e);
			t.c = n.move(t.c.x - n.x, t.c.y - n.y);
		} }), $(F.Pos.Skew, { toShape: function(e) {
			var t = e.env, n = this.coord.position(e);
			t.c = new U.Point(n.x + t.c.x, n.y + t.c.y).combineRect(t.c);
		} }), $(F.Pos.Cover, { toShape: function(e) {
			var t = e.env, n = this.coord.position(e);
			t.c = t.c.combineRect(n);
		} }), $(F.Pos.Then, { toShape: function(e) {
			var t = e.env;
			t.capturePosition(t.c), t.c = this.coord.position(e);
		} }), $(F.Pos.SwapPAndC, { toShape: function(e) {
			var t = e.env;
			t.swapPAndC(), t.c = this.coord.position(e);
		} }), $(F.Pos.SetBase, { toShape: function(e) {
			var t = e.env, n = t.p, r = t.c.x - n.x, i = t.c.y - n.y;
			t.setOrigin(n.x, n.y), t.setXBase(r, i), t.setYBase(-i, r), t.c = this.coord.position(e);
		} }), $(F.Pos.SetYBase, { toShape: function(e) {
			var t = e.env;
			t.setYBase(t.c.x - t.origin.x, t.c.y - t.origin.y), t.c = this.coord.position(e);
		} }), $(F.Pos.ConnectObject, { toShape: function(e) {
			this.object.toConnectShape(e);
		} }), $(F.Pos.DropObject, { toShape: function(e) {
			this.object.toDropShape(e);
		} }), $(F.Pos.Place, { toShape: function(e) {
			var t = e.env;
			if (t.lastCurve.isDefined) {
				var n, r = this.place, i = r.shaveP > 0, a = r.shaveC > 0, o = i ? r.shaveP - 1 : 0, s = a ? r.shaveC - 1 : 0;
				if (i && (n = 0), a && (n = 1), i == a && (n = .5), r.factor !== void 0) if (r.factor.isIntercept) {
					if (a = i = !1, (n = r.factor.value(e)) === void 0) return;
				} else n = r.factor.value(e);
				var c = A.measure.length2em(r.slide.dimen.getOrElse(`0`)) + (o - s) * A.measure.jot, l = t.lastCurve.tOfPlace(i, a, n, c), u = t.lastCurve.position(l), d = t.lastCurve.angle(l);
				return t.c = u, t.angle = d, l;
			}
		} }), $(F.Pos.PushCoord, { toShape: function(e) {
			var t = e.env, n = this.coord.position(e);
			t.pushPos(n);
		} }), $(F.Pos.EvalCoordThenPop, { toShape: function(e) {
			var t = e.env;
			t.c = this.coord.position(e), t.popPos();
		} }), $(F.Pos.LoadStack, { toShape: function(e) {
			var t = e.env;
			t.startCapturePositions(), this.coord.position(e);
			var n = t.endCapturePositions();
			t.setStack(n), t.pushPos(t.c);
		} }), $(F.Pos.DoCoord, { toShape: function(e) {
			var t = e.env, n = this.coord;
			t.stack.reverse().foreach((function(r) {
				t.c = r, n.position(e);
			}));
		} }), $(F.Pos.InitStack, { toShape: function(e) {
			e.env.initStack();
		} }), $(F.Pos.EnterFrame, { toShape: function(e) {
			e.env.enterStackFrame();
		} }), $(F.Pos.LeaveFrame, { toShape: function(e) {
			e.env.leaveStackFrame();
		} }), $(F.Place.Factor, { value: function(e) {
			return this.factor;
		} }), $(F.Place.Intercept, { value: function(e) {
			var t = e.env;
			if (t.lastCurve.isDefined) {
				var n = t.duplicate();
				n.angle = 0, n.lastCurve = Q.none, n.p = n.c = Mt.originPosition;
				var r = new St(Y.none, n);
				this.pos.toShape(r), e.appendShapeToFront(r.shape), n.lastCurve.isDefined || (n.lastCurve = new Q.Line(n.p, n.c, n.p, n.c, void 0));
				for (var i = [], a = t.lastCurve.segments(), o = n.lastCurve.segments(), s = 0; s < a.length; s++) for (var c = 0; c < o.length; c++) i = i.concat(Z.findIntersections(a[s], o[c]));
				if (i.length === 0) {
					console.log(`perhaps no curve intersection.`);
					for (var l = t.lastCurve, u = n.lastCurve, d = 1e-5, f = 0, p = 2, m = 0, h = 0, g = function(e) {
						return 1 / (1 + Math.exp(-e));
					}, _ = function(e) {
						var t = Math.exp(-e);
						return t / (1 + t) / (1 + t);
					}, v = g(m), y = g(h), b = _(m), x = _(h), S = l.derivative(v), C = u.derivative(y), w = S.x * b, T = -C.x * x, E = S.y * b, D = -C.y * x, ee = w * w + E * E, te = w * T + E * D, ne = T * w + D * E, O = T * T + D * D, re = l.position(v), ie = u.position(y), ae = re.x - ie.x, oe = re.y - ie.y, se = w * ae + E * oe, ce = T * ae + D * oe, le = Math.sqrt(se * se + ce * ce) < d, ue = .001 * Math.max(ee, O); !le && f < 100;) {
						f++;
						do {
							var de = O + ue, fe = (ee + ue) * de - te * ne, pe = (de * se - te * ce) / fe, me = (-ne * se + ee * ce) / fe;
							if (pe * pe + me * me < 10000000000000002e-26 * (m * m + h * h)) le = !0;
							else {
								var he = m - pe, ge = h - me, _e = g(he), ve = g(ge), ye = l.position(_e), be = u.position(ve), xe = ye.x - be.x, Se = ye.y - be.y, k = (ae * ae + oe * oe - (xe * xe + Se * Se)) / (pe * (ue * pe + se) + me * (ue * me + ce));
								if (k > 0) {
									h = ge, v = _e, y = ve, b = _(m = he), x = _(h), S = l.derivative(v), C = u.derivative(y), w = S.x * b, T = -C.x * x, ee = w * w + (E = S.y * b) * E, te = w * T + E * (D = -C.y * x), ne = T * w + D * E, O = T * T + D * D, se = w * (ae = xe) + E * (oe = Se), ce = T * ae + D * oe, le = Math.sqrt(se * se + ce * ce) < d;
									var Ce = 2 * k - 1;
									ue += Math.max(1 / 3, 1 - Ce * Ce * Ce), p = 2;
								} else ue *= p, p *= 2;
							}
						} while (!(le || k !== void 0 && k > 0));
					}
					return g(m);
				}
				var we = (i[0][0].min + i[0][0].max) / 2;
				for (s = 1; s < i.length; s++) {
					var Te = (i[s][0].min + i[s][0].max) / 2;
					we > Te && (we = Te);
				}
				return we;
			}
		} }), $(F.Pos.SavePos, { toShape: function(e) {
			var t = e.env;
			t.savePos(this.id, new It.Position(t.c));
		} }), $(F.Pos.SaveMacro, { toShape: function(e) {
			e.env.savePos(this.id, new It.Macro(this.macro));
		} }), $(F.Pos.SaveBase, { toShape: function(e) {
			var t = e.env;
			t.savePos(this.id, new It.Base(t.origin, t.xBase, t.yBase));
		} }), $(F.Pos.SaveStack, { toShape: function(e) {
			var t = e.env;
			t.savePos(this.id, new It.Stack(t.stack));
		} }), $(F.Object, {
			toDropShape: function(e) {
				var t = e.env;
				if (t.c === void 0) return Y.none;
				var n = this.modifiers;
				if (n.isEmpty) return this.object.toDropShape(e);
				var r = t.duplicate(), i = new St(Y.none, r), a = O.empty;
				n.foreach((function(e) {
					e.preprocess(i, a), a = a.prepend(e);
				}));
				var o = this.object.toDropShape(i), s = r.c;
				if (s === void 0) return Y.none;
				var c = r.originalReferencePoint;
				return (r = t.duplicate()).c = s, r.originalReferencePoint = c, i = new St(Y.none, r), o = n.head.modifyShape(i, o, n.tail), e.appendShapeToFront(o), t.c = r.c.move(t.c.x, t.c.y), o;
			},
			toConnectShape: function(e) {
				var t = e.env;
				if (t.c === void 0) return Y.none;
				var n = this.modifiers;
				if (n.isEmpty) return this.object.toConnectShape(e);
				var r = t.duplicate(), i = new St(Y.none, r), a = O.empty;
				n.foreach((function(e) {
					e.preprocess(i, a), a = a.prepend(e);
				}));
				var o = this.object.toConnectShape(i);
				t.angle = r.angle, t.lastCurve = r.lastCurve;
				var s = r.c;
				if (s === void 0) return Y.none;
				var c = r.originalReferencePoint;
				return (r = t.duplicate()).c = s, r.originalReferencePoint = c, i = new St(Y.none, r), o = n.head.modifyShape(i, o, n.tail), e.appendShapeToFront(o), t.c = r.c.move(t.c.x, t.c.y), o;
			},
			boundingBox: function(e) {
				var t = e.duplicateEnv(), n = t.env;
				return n.angle = 0, n.p = n.c = Mt.originPosition, t.shape = Y.none, this.toDropShape(t).getBoundingBox();
			}
		}), $(F.ObjectBox, {
			toConnectShape: function(e) {
				var t = (n = e.env).c, n = e.env, r = (A.measure.thickness, n.p.edgePoint(n.c.x, n.c.y)), i = n.c.edgePoint(n.p.x, n.p.y);
				if (r.x !== i.x || r.y !== i.y) {
					var a = new X.Line(r, i).toShape(e, this, `196883`, ``);
					return n.originalReferencePoint = t, a;
				}
				return n.angle = 0, n.lastCurve = Q.none, n.originalReferencePoint = t, Y.none;
			},
			boundingBox: function(e) {
				var t = e.duplicateEnv(), n = t.env;
				return n.angle = 0, n.p = n.c = Mt.originPosition, t.shape = Y.none, this.toDropShape(t).getBoundingBox();
			}
		}), $(F.ObjectBox.WrapUpObject, {
			toDropShape: function(e) {
				var t = e.env, n = this.object.toDropShape(e);
				return t.originalReferencePoint = t.c, n;
			},
			toConnectShape: function(e) {
				var t = e.env, n = this.object.toConnectShape(e);
				return t.originalReferencePoint = t.c, n;
			}
		}), $(F.ObjectBox.CompositeObject, { toDropShape: function(e) {
			var t = e.env, n = t.c;
			if (n === void 0) return Y.none;
			var r = n, i = t.duplicate(), a = new St(Y.none, i);
			this.objects.foreach((function(e) {
				i.c = n;
				var t = e.toDropShape(a);
				r = U.combineRect(r, i.c), r = U.combineRect(r, t.getBoundingBox().toPoint());
			})), t.c = r;
			var o = a.shape;
			return e.appendShapeToFront(o), t.originalReferencePoint = n, o;
		} }), $(F.ObjectBox.Xybox, { toDropShape: function(e) {
			var t = e.env, n = t.c;
			if (n === void 0) return Y.none;
			var r = new Mt(), i = new St(Y.none, r);
			this.posDecor.toShape(i);
			var a = i.shape, o = a.getBoundingBox();
			if (o === void 0) return Y.none;
			var s = Math.max(0, o.l - o.x), c = Math.max(0, o.r + o.x), l = Math.max(0, o.u + o.y), u = Math.max(0, o.d - o.y);
			t.c = new U.Rect(n.x, n.y, {
				l: s,
				r: c,
				u: l,
				d: u
			}), t.originalReferencePoint = n;
			var d = new Y.TranslateShape(n.x, n.y, a);
			return e.appendShapeToFront(d), d;
		} }), $(F.ObjectBox.Xymatrix, { toDropShape: function(e) {
			var t = e.env, n = t.c, r = this.xymatrix.toShape(e);
			return t.originalReferencePoint = n, r;
		} }), $(F.ObjectBox.Text, { toDropShape: function(e) {
			var t = e.env, n = new Y.TextShape(t.c, this.math);
			return e.appendShapeToFront(n), t.c = n.getBoundingBox(), t.originalReferencePoint = n.getOriginalReferencePoint(), n;
		} }), $(F.ObjectBox.Empty, { toDropShape: function(e) {
			var t = e.env;
			return t.originalReferencePoint = t.c, t.c = new U.Point(t.c.x, t.c.y), Y.none;
		} }), $(F.ObjectBox.Txt, { toDropShape: function(e) {
			var t = e.env;
			if (t.c === void 0) return Y.none;
			var n = this.textObject.toDropShape(e);
			return t.originalReferencePoint = t.c, n;
		} }), $(F.ObjectBox.Txt.Width.Vector, { width: function(e) {
			return this.vector.xy().x;
		} }), $(F.ObjectBox.Txt.Width.Default, { width: function(e) {
			var t = e.env.c;
			return t.r + t.l;
		} }), $(F.ObjectBox.Cir, {
			toDropShape: function(e) {
				var t = e.env;
				if (t.c === void 0) return Y.none;
				t.originalReferencePoint = t.c;
				var n = this.radius.radius(e), r = t.c.x, i = t.c.y, a = this.cir.toDropShape(e, r, i, n);
				return t.c = new U.Ellipse(r, i, n, n, n, n), a;
			},
			toConnectShape: function(e) {
				var t = e.env;
				return t.originalReferencePoint = t.c, Y.none;
			}
		}), $(F.ObjectBox.Cir.Radius.Vector, { radius: function(e) {
			return this.vector.xy(e).x;
		} }), $(F.ObjectBox.Cir.Radius.Default, { radius: function(e) {
			return e.env.c.r;
		} }), $(F.ObjectBox.Cir.Cir.Segment, {
			toDropShape: function(e, t, n, r) {
				e.env;
				var i, a, o = this.startPointDegree(e), s = this.endPointDegree(e, o), c = s - o;
				if ((c = c < 0 ? c + 360 : c) === 0) return Y.none;
				this.orient === `^` ? (i = c > 180 ? `1` : `0`, a = `0`) : (i = c > 180 ? `0` : `1`, a = `1`);
				var l = Math.PI / 180, u = t + r * Math.cos(o * l), d = n + r * Math.sin(o * l), f = t + r * Math.cos(s * l), p = n + r * Math.sin(s * l), m = new Y.CircleSegmentShape(t, n, u, d, r, i, a, f, p);
				return e.appendShapeToFront(m), m;
			},
			startPointDegree: function(e) {
				var t = this.startDiag.toString();
				return this.orient === `^` ? this.diagToAngleACW(t) : this.diagToAngleCW(t);
			},
			endPointDegree: function(e, t) {
				var n = this.endDiag.toString();
				return this.orient === `^` ? this.diagToAngleACW(n, t) : this.diagToAngleCW(n, t);
			},
			diagToAngleACW: function(e, t) {
				switch (e) {
					case `l`: return 90;
					case `r`: return -90;
					case `d`: return 180;
					case `u`: return 0;
					case `dl`:
					case `ld`: return 135;
					case `dr`:
					case `rd`: return -135;
					case `ul`:
					case `lu`: return 45;
					case `ur`:
					case `ru`: return -45;
					default: return t === void 0 ? 0 : t + 180;
				}
			},
			diagToAngleCW: function(e, t) {
				switch (e) {
					case `l`: return -90;
					case `r`: return 90;
					case `d`: return 0;
					case `u`: return 180;
					case `dl`:
					case `ld`: return -45;
					case `dr`:
					case `rd`: return 45;
					case `ul`:
					case `lu`: return -135;
					case `ur`:
					case `ru`: return 135;
					default: return t === void 0 ? 0 : t + 180;
				}
			}
		}), $(F.ObjectBox.Cir.Cir.Full, { toDropShape: function(e, t, n, r) {
			var i = new Y.FullCircleShape(t, n, r);
			return e.appendShapeToFront(i), i;
		} }), $(F.ObjectBox.Frame, {
			toDropShape: function(e) {
				var t = e.env;
				return t.originalReferencePoint = t.c, this.toDropFilledShape(e, `currentColor`, !1);
			},
			toDropFilledShape: function(e, t, n) {
				var r = e.env.c;
				if (r === void 0) return Y.none;
				var i = A.measure.thickness, a = r.x, o = r.y, s = r.l, c = r.r, l = r.u, u = r.d, d = Y.none;
				switch (this.main) {
					case `--`:
						var f = 3 * i;
						if (n) {
							var p = this.radius.xy(e);
							d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !1, t, A.measure.em2px(f) + ` ` + A.measure.em2px(f));
						} else {
							var m = this.radius.radius(e);
							d = new Y.RectangleShape(a, o, s, c, l, u, m, !1, t, A.measure.em2px(f) + ` ` + A.measure.em2px(f));
						}
						break;
					case `==`:
						f = 3 * i, n ? (p = this.radius.xy(e), d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !0, t, A.measure.em2px(f) + ` ` + A.measure.em2px(f))) : (m = this.radius.radius(e), d = new Y.RectangleShape(a, o, s, c, l, u, m, !0, t, A.measure.em2px(f) + ` ` + A.measure.em2px(f)));
						break;
					case `o-`:
						f = 3 * i, m = A.measure.lineElementLength, d = new Y.RectangleShape(a, o, s, c, l, u, m, !1, t, A.measure.em2px(f) + ` ` + A.measure.em2px(f));
						break;
					case `oo`:
						var h = (p = this.radius.xy(e)).x;
						d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, h, h, !0, t, void 0);
						break;
					case `ee`:
						p = this.radius.xy(e), d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !0, t, void 0);
						break;
					case `-,`:
						var g = this.radius.depth(e);
						m = this.radius.radius(e), d = new Y.CompositeShape(new Y.RectangleShape(a, o, s, c, l, u, m, !1, t, void 0), new Y.BoxShadeShape(a, o, s, c, l, u, g));
						break;
					case `.o`:
						h = (p = this.radius.xy(e)).x, d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, h, h, !1, t, A.measure.dottedDasharray);
						break;
					case `-o`:
						f = 3 * i, h = (p = this.radius.xy(e)).x, d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, h, h, !1, t, A.measure.em2px(f) + ` ` + A.measure.em2px(f));
						break;
					case `.e`:
						p = this.radius.xy(e), d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !1, t, A.measure.dottedDasharray);
						break;
					case `-e`:
						f = 3 * i, p = this.radius.xy(e), d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !1, t, A.measure.em2px(f) + ` ` + A.measure.em2px(f));
						break;
					case `-`:
						n ? (p = this.radius.xy(e), d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !1, t, void 0)) : (m = this.radius.radius(e), d = new Y.RectangleShape(a, o, s, c, l, u, m, !1, t, void 0));
						break;
					case `=`:
						n ? (p = this.radius.xy(e), d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !0, t, void 0)) : (m = this.radius.radius(e), d = new Y.RectangleShape(a, o, s, c, l, u, m, !0, t, void 0));
						break;
					case `.`:
						n ? (p = this.radius.xy(e), d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !1, t, A.measure.dottedDasharray)) : (m = this.radius.radius(e), d = new Y.RectangleShape(a, o, s, c, l, u, m, !1, t, A.measure.dottedDasharray));
						break;
					case `,`:
						g = this.radius.depth(e), d = new Y.BoxShadeShape(a, o, s, c, l, u, g, t);
						break;
					case `o`:
						h = (p = this.radius.xy(e)).x, d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, h, h, !1, t, void 0);
						break;
					case `e`:
						p = this.radius.xy(e), d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !1, t, void 0);
						break;
					case `\\{`:
						d = new Y.LeftBrace(a - s, o, l, u, 0, t);
						break;
					case `\\}`:
						d = new Y.LeftBrace(a + c, o, u, l, 180, t);
						break;
					case `^\\}`:
					case `^\\{`:
						d = new Y.LeftBrace(a, o + l, c, s, 270, t);
						break;
					case `_\\{`:
					case `_\\}`:
						d = new Y.LeftBrace(a, o - u, s, c, 90, t);
						break;
					case `(`:
						d = new Y.LeftParenthesis(a - s, o + (l - u) / 2, l + u, 0, t);
						break;
					case `)`:
						d = new Y.LeftParenthesis(a + c, o + (l - u) / 2, l + u, 180, t);
						break;
					case `^(`:
					case `^)`:
						d = new Y.LeftParenthesis(a + (c - s) / 2, o + l, s + c, 270, t);
						break;
					case `_(`:
					case `_)`:
						d = new Y.LeftParenthesis(a + (c - s) / 2, o - u, s + c, 90, t);
						break;
					case `*`:
						r.isCircle() ? (p = this.radius.xy(e), d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !1, `currentColor`, void 0, t, !0)) : (m = this.radius.radius(e), d = new Y.RectangleShape(a, o, s, c, l, u, m, !1, `currentColor`, void 0, t, !0));
						break;
					case `**`:
						r.isCircle() ? (p = this.radius.xy(e), d = new Y.EllipseShape(a + (c - s) / 2, o + (l - u) / 2, p.x, p.y, !1, `currentColor`, void 0, t, !1)) : (m = this.radius.radius(e), d = new Y.RectangleShape(a, o, s, c, l, u, m, !1, `currentColor`, void 0, t, !1));
						break;
					default: return Y.none;
				}
				return e.appendShapeToFront(d), d;
			},
			toConnectShape: function(e) {
				var t = e.env, n = t.c, r = t.p;
				n !== void 0 && r !== void 0 || Y.none, t.originalReferencePoint = n;
				var i = t.duplicate();
				i.c = r.combineRect(n);
				var a = new St(Y.none, i), o = this.toDropShape(a);
				return e.appendShapeToFront(o), o;
			}
		}), $(F.ObjectBox.Frame.Radius.Vector, {
			radius: function(e) {
				return this.vector.xy(e).x;
			},
			depth: function(e) {
				return this.vector.xy(e).x;
			},
			xy: function(e) {
				return this.vector.xy(e);
			}
		}), $(F.ObjectBox.Frame.Radius.Default, {
			radius: function(e) {
				return 0;
			},
			depth: function(e) {
				return A.measure.thickness / 2;
			},
			xy: function(e) {
				var t = e.env.c;
				return {
					x: (t.l + t.r) / 2,
					y: (t.u + t.d) / 2
				};
			}
		}), $(F.ObjectBox.Dir, {
			toDropShape: function(e) {
				var t = e.env, n = t.c;
				t.originalReferencePoint = n;
				var r = t.angle;
				if (n === void 0) return Y.none;
				t.c = new U.Point(n.x, n.y), A.measure.thickness;
				var i = Y.none;
				switch (this.main) {
					case ``: return Y.none;
					case `>`:
						switch (this.variant) {
							case `2`:
								var a = (i = new Y.GT2ArrowheadShape(n, r)).getRadius();
								t.c = new U.Ellipse(n.x, n.y, a, a, a, a);
								break;
							case `3`:
								a = (i = new Y.GT3ArrowheadShape(n, r)).getRadius(), t.c = new U.Ellipse(n.x, n.y, a, a, a, a);
								break;
							default: i = this.variant === `^` ? new Y.UpperGTArrowheadShape(n, r) : this.variant === `_` ? new Y.LowerGTArrowheadShape(n, r) : new Y.GTArrowheadShape(n, r);
						}
						break;
					case `<`:
						switch (this.variant) {
							case `2`:
								a = (i = new Y.LT2ArrowheadShape(n, r)).getRadius(), t.c = new U.Ellipse(n.x, n.y, a, a, a, a);
								break;
							case `3`:
								a = (i = new Y.LT3ArrowheadShape(n, r)).getRadius(), t.c = new U.Ellipse(n.x, n.y, a, a, a, a);
								break;
							default: i = this.variant === `^` ? new Y.UpperLTArrowheadShape(n, r) : this.variant === `_` ? new Y.LowerLTArrowheadShape(n, r) : new Y.LTArrowheadShape(n, r);
						}
						break;
					case `|`:
						switch (this.variant) {
							case `^`:
								i = new Y.UpperColumnArrowheadShape(n, r);
								break;
							case `_`:
								i = new Y.LowerColumnArrowheadShape(n, r);
								break;
							case `2`:
								i = new Y.Column2ArrowheadShape(n, r);
								break;
							case `3`:
								i = new Y.Column3ArrowheadShape(n, r);
								break;
							default: i = new Y.ColumnArrowheadShape(n, r);
						}
						break;
					case `(`:
						switch (this.variant) {
							case `^`:
								i = new Y.UpperLParenArrowheadShape(n, r);
								break;
							case `_`:
								i = new Y.LowerLParenArrowheadShape(n, r);
								break;
							default: i = new Y.LParenArrowheadShape(n, r);
						}
						break;
					case `)`:
						switch (this.variant) {
							case `^`:
								i = new Y.UpperRParenArrowheadShape(n, r);
								break;
							case `_`:
								i = new Y.LowerRParenArrowheadShape(n, r);
								break;
							default: i = new Y.RParenArrowheadShape(n, r);
						}
						break;
					case "`":
						i = this.variant === `_` ? new Y.LowerBackquoteArrowheadShape(n, r) : new Y.UpperBackquoteArrowheadShape(n, r);
						break;
					case `'`:
						i = this.variant === `_` ? new Y.LowerQuoteArrowheadShape(n, r) : new Y.UpperQuoteArrowheadShape(n, r);
						break;
					case `*`:
						i = new Y.AsteriskArrowheadShape(n, 0);
						break;
					case `o`:
						i = new Y.OArrowheadShape(n, 0);
						break;
					case `+`:
						i = new Y.PlusArrowheadShape(n, r);
						break;
					case `x`:
						i = new Y.XArrowheadShape(n, r);
						break;
					case `/`:
						i = new Y.SlashArrowheadShape(n, r);
						break;
					case `-`:
					case `--`:
						A.measure.lineElementLength, i = this.variant === `3` ? new Y.Line3ArrowheadShape(n, r) : this.variant === `2` ? new Y.Line2ArrowheadShape(n, r) : new Y.LineArrowheadShape(n, r);
						break;
					case `=`:
					case `==`:
						i = new Y.Line2ArrowheadShape(n, r);
						break;
					case `.`:
					case `..`:
						i = this.variant === `3` ? new Y.Dot3ArrowheadShape(n, r) : this.variant === `2` ? new Y.Dot2ArrowheadShape(n, r) : new Y.DotArrowheadShape(n, r);
						break;
					case `:`:
					case `::`:
						i = new Y.Dot2ArrowheadShape(n, r);
						break;
					case `~`:
					case `~~`:
						i = this.variant === `3` ? new Y.Tilde3ArrowheadShape(n, r) : this.variant === `2` ? new Y.Tilde2ArrowheadShape(n, r) : new Y.TildeArrowheadShape(n, r);
						break;
					case `>>`:
						switch (this.variant) {
							case `^`:
								i = new Y.UpperGTGTArrowheadShape(n, r);
								break;
							case `_`:
								i = new Y.LowerGTGTArrowheadShape(n, r);
								break;
							case `2`:
								a = (i = new Y.GTGT2ArrowheadShape(n, r)).getRadius(), t.c = new U.Ellipse(n.x, n.y, a, a, a, a);
								break;
							case `3`:
								a = (i = new Y.GTGT3ArrowheadShape(n, r)).getRadius(), t.c = new U.Ellipse(n.x, n.y, a, a, a, a);
								break;
							default: i = new Y.GTGTArrowheadShape(n, r);
						}
						break;
					case `<<`:
						switch (this.variant) {
							case `^`:
								i = new Y.UpperLTLTArrowheadShape(n, r);
								break;
							case `_`:
								i = new Y.LowerLTLTArrowheadShape(n, r);
								break;
							case `2`:
								a = (i = new Y.LTLT2ArrowheadShape(n, r)).getRadius(), t.c = new U.Ellipse(n.x, n.y, a, a, a, a);
								break;
							case `3`:
								a = (i = new Y.LTLT3ArrowheadShape(n, r)).getRadius(), t.c = new U.Ellipse(n.x, n.y, a, a, a, a);
								break;
							default: i = new Y.LTLTArrowheadShape(n, r);
						}
						break;
					case `||`:
						switch (this.variant) {
							case `^`:
								i = new Y.UpperColumnColumnArrowheadShape(n, r);
								break;
							case `_`:
								i = new Y.LowerColumnColumnArrowheadShape(n, r);
								break;
							case `2`:
								i = new Y.ColumnColumn2ArrowheadShape(n, r);
								break;
							case `3`:
								i = new Y.ColumnColumn3ArrowheadShape(n, r);
								break;
							default: i = new Y.ColumnColumnArrowheadShape(n, r);
						}
						break;
					case `|-`:
						switch (this.variant) {
							case `^`:
								i = new Y.UpperColumnLineArrowheadShape(n, r);
								break;
							case `_`:
								i = new Y.LowerColumnLineArrowheadShape(n, r);
								break;
							case `2`:
								i = new Y.ColumnLine2ArrowheadShape(n, r);
								break;
							case `3`:
								i = new Y.ColumnLine3ArrowheadShape(n, r);
								break;
							default: i = new Y.ColumnLineArrowheadShape(n, r);
						}
						break;
					case `>|`:
						i = new Y.GTColumnArrowheadShape(n, r);
						break;
					case `>>|`:
						i = new Y.GTGTColumnArrowheadShape(n, r);
						break;
					case `|<`:
						i = new Y.ColumnLTArrowheadShape(n, r);
						break;
					case `|<<`:
						i = new Y.ColumnLTLTArrowheadShape(n, r);
						break;
					case `//`:
						i = new Y.SlashSlashArrowheadShape(n, r);
						break;
					case `=>`:
						i = new Y.LineGT2ArrowheadShape(n, r);
						break;
					default:
						var o = A.repositories.dirRepository.get(this.main);
						if (o === void 0) throw c(`ExecutionError`, `\\dir ` + this.variant + `{` + this.main + `} not defined.`);
						i = o.toDropShape(e);
				}
				return e.appendShapeToFront(i), i;
			},
			toConnectShape: function(e) {
				var t = e.env;
				t.originalReferencePoint = t.c, A.measure.thickness;
				var n = t.p.edgePoint(t.c.x, t.c.y), r = t.c.edgePoint(t.p.x, t.p.y);
				return n.x !== r.x || n.y !== r.y ? new X.Line(n, r).toShape(e, this, this.main, this.variant) : (t.angle = 0, t.lastCurve = Q.none, Y.none);
			}
		}), $(F.ObjectBox.Curve, {
			toDropShape: function(e) {
				var t = e.env;
				return t.originalReferencePoint = t.c, Y.none;
			},
			toConnectShape: function(e) {
				var t = e.env;
				t.originalReferencePoint = t.c;
				var n = void 0, r = void 0;
				this.objects.foreach((function(e) {
					n = e.objectForDrop(n), r = e.objectForConnect(r);
				})), n === void 0 && r === void 0 && (r = new F.Object(O.empty, new F.ObjectBox.Dir(``, `-`))), A.measure.thickness;
				var i = t.c, a = t.p, o = [];
				this.poslist.foreach((function(t) {
					t.addPositions(o, e);
				})), t.c = i, t.p = a;
				var s = Y.none, c = a, l = i;
				switch (o.length) {
					case 0: return c.x === l.x && c.y === l.y ? (t.lastCurve = Q.none, t.angle = 0, Y.none) : r === void 0 ? n.toConnectShape(e) : r.toConnectShape(e);
					case 1:
						var u = (f = new X.QuadBezier(c, o[0], l)).tOfShavedStart(c), d = f.tOfShavedEnd(l);
						if (u === void 0 || d === void 0 || u >= d) return t.angle = 0, t.lastCurve = Q.none, Y.none;
						s = f.toShape(e, n, r), t.lastCurve = new Q.QuadBezier(f, u, d, s), t.angle = Math.atan2(l.y - c.y, l.x - c.x);
						break;
					case 2:
						var f;
						if (u = (f = new X.CubicBezier(c, o[0], o[1], l)).tOfShavedStart(c), d = f.tOfShavedEnd(l), u === void 0 || d === void 0 || u >= d) return t.angle = 0, t.lastCurve = Q.none, Y.none;
						s = f.toShape(e, n, r), t.lastCurve = new Q.CubicBezier(f, u, d, s), t.angle = Math.atan2(l.y - c.y, l.x - c.x);
						break;
					default:
						var p = new X.CubicBSpline(c, o, l), m = new X.CubicBeziers(p.toCubicBeziers());
						if (u = m.tOfShavedStart(c), d = m.tOfShavedEnd(l), u === void 0 || d === void 0 || u >= d) return t.angle = 0, t.lastCurve = Q.none, Y.none;
						s = m.toShape(e, n, r), t.lastCurve = new Q.CubicBSpline(c, l, m, u, d, s), t.angle = Math.atan2(l.y - c.y, l.x - c.x);
				}
				return s;
			}
		}), $(F.ObjectBox.Curve.Object.Drop, {
			objectForDrop: function(e) {
				return this.object;
			},
			objectForConnect: function(e) {
				return e;
			}
		}), $(F.ObjectBox.Curve.Object.Connect, {
			objectForDrop: function(e) {
				return e;
			},
			objectForConnect: function(e) {
				return this.object;
			}
		}), $(F.ObjectBox.Curve.PosList.CurPos, { addPositions: function(e, t) {
			var n = t.env;
			e.push(n.c);
		} }), $(F.ObjectBox.Curve.PosList.Pos, { addPositions: function(e, t) {
			var n = t.env;
			this.pos.toShape(t), e.push(n.c);
		} }), $(F.ObjectBox.Curve.PosList.AddStack, { addPositions: function(e, t) {
			t.env.stack.reverse().foreach((function(t) {
				e.push(t);
			}));
		} }), $(F.Coord.C, { position: function(e) {
			return e.env.c;
		} }), $(F.Coord.P, { position: function(e) {
			return e.env.p;
		} }), $(F.Coord.X, { position: function(e) {
			var t = e.env, n = t.p, r = t.c, i = t.origin, a = t.xBase, o = r.y - n.y, s = n.x - r.x, c = r.x * n.y - r.y * n.x, u = a.y, d = -a.x, f = a.x * i.y - a.y * i.x, p = o * d - u * s;
			if (Math.abs(p) < l.machinePrecision) return console.log(`there is no intersection point.`), Mt.originPosition;
			var m = -(d * c - s * f) / p, h = (u * c - o * f) / p;
			return new U.Point(m, h);
		} }), $(F.Coord.Y, { position: function(e) {
			var t = e.env, n = t.p, r = t.c, i = t.origin, a = t.yBase, o = r.y - n.y, s = n.x - r.x, c = r.x * n.y - r.y * n.x, u = a.y, d = -a.x, f = a.x * i.y - a.y * i.x, p = o * d - u * s;
			if (Math.abs(p) < l.machinePrecision) return console.log(`there is no intersection point.`), Mt.originPosition;
			var m = -(d * c - s * f) / p, h = (u * c - o * f) / p;
			return new U.Point(m, h);
		} }), $(F.Coord.Vector, { position: function(e) {
			var t = this.vector.xy(e);
			return new U.Point(t.x, t.y);
		} }), $(F.Coord.Id, { position: function(e) {
			return e.env.lookupPos(this.id).position(e);
		} }), $(F.Coord.Group, { position: function(e) {
			var t = e.env, n = t.origin, r = t.xBase, i = t.yBase, a = t.p;
			return this.posDecor.toShape(e), t.p = a, t.origin = n, t.xBase = r, t.yBase = i, t.c;
		} }), $(F.Coord.StackPosition, { position: function(e) {
			return e.env.stackAt(this.number);
		} }), $(F.Coord.DeltaRowColumn, { position: function(e) {
			var t = e.env, n = t.xymatrixRow, r = t.xymatrixCol;
			if (n === void 0 || r === void 0) throw c(`ExecutionError`, `xymatrix rows and columns not found for ` + this.toSring());
			var i = this.prefix + (n + this.dr) + `,` + (r + this.dc);
			return e.env.lookupPos(i, `in entry "` + t.xymatrixRow + `,` + t.xymatrixCol + `": No ` + this + ` (is ` + i + `) from here.`).position(e);
		} }), $(F.Coord.Hops, { position: function(e) {
			var t = e.env, n = t.xymatrixRow, r = t.xymatrixCol;
			if (n === void 0 || r === void 0) throw c(`ExecutionError`, `xymatrix rows and columns not found for ` + this.toSring());
			this.hops.foreach((function(e) {
				switch (e) {
					case `u`:
						--n;
						break;
					case `d`:
						n += 1;
						break;
					case `l`:
						--r;
						break;
					case `r`: r += 1;
				}
			}));
			var i = this.prefix + n + `,` + r;
			return e.env.lookupPos(i, `in entry "` + t.xymatrixRow + `,` + t.xymatrixCol + `": No ` + this + ` (is ` + i + `) from here.`).position(e);
		} }), $(F.Coord.HopsWithPlace, { position: function(e) {
			var t = e.env, n = t.xymatrixRow, r = t.xymatrixCol;
			if (n === void 0 || r === void 0) throw c(`ExecutionError`, `xymatrix rows and columns not found for ` + this.toSring());
			this.hops.foreach((function(e) {
				switch (e) {
					case `u`:
						--n;
						break;
					case `d`:
						n += 1;
						break;
					case `l`:
						--r;
						break;
					case `r`: r += 1;
				}
			}));
			var i = this.prefix + n + `,` + r, a = e.env.lookupPos(i, `in entry "` + t.xymatrixRow + `,` + t.xymatrixCol + `": No ` + this + ` (is ` + i + `) from here.`).position(e), o = (t.c, t.duplicate());
			o.p = t.c, o.c = a;
			var s, l = o.c.x - o.p.x, u = o.c.y - o.p.y;
			s = l === 0 && u === 0 ? 0 : Math.atan2(u, l), o.angle = s;
			var d = o.p.edgePoint(o.c.x, o.c.y), f = o.c.edgePoint(o.p.x, o.p.y);
			o.lastCurve = new Q.Line(d, f, o.p, o.c, void 0);
			var p = new St(Y.none, o), m = this.place.toShape(p);
			return o.lastCurve.position(m);
		} }), $(F.Vector.InCurBase, {
			xy: function(e) {
				return e.env.absVector(this.x, this.y);
			},
			angle: function(e) {
				var t = e.env.absVector(this.x, this.y);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Vector.Abs, {
			xy: function(e) {
				return {
					x: A.measure.length2em(this.x),
					y: A.measure.length2em(this.y)
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Vector.Angle, {
			xy: function(e) {
				var t = Math.PI / 180 * this.degree;
				return e.env.absVector(Math.cos(t), Math.sin(t));
			},
			angle: function(e) {
				return Math.PI / 180 * this.degree;
			}
		}), $(F.Vector.Dir, {
			xy: function(e) {
				var t = A.measure.length2em(this.dimen), n = this.dir.angle(e);
				return {
					x: t * Math.cos(n),
					y: t * Math.sin(n)
				};
			},
			angle: function(e) {
				return this.dir.angle(e);
			}
		}), $(F.Vector.Corner, {
			xy: function(e) {
				var t = this.corner.xy(e);
				return {
					x: t.x * this.factor,
					y: t.y * this.factor
				};
			},
			angle: function(e) {
				return this.corner.angle(e);
			}
		}), $(F.Corner.L, {
			xy: function(e) {
				return {
					x: -e.env.c.l,
					y: 0
				};
			},
			angle: function(e) {
				return Math.PI;
			}
		}), $(F.Corner.R, {
			xy: function(e) {
				return {
					x: e.env.c.r,
					y: 0
				};
			},
			angle: function(e) {
				return 0;
			}
		}), $(F.Corner.D, {
			xy: function(e) {
				return {
					x: 0,
					y: -e.env.c.d
				};
			},
			angle: function(e) {
				return -Math.PI / 2;
			}
		}), $(F.Corner.U, {
			xy: function(e) {
				return {
					x: 0,
					y: e.env.c.u
				};
			},
			angle: function(e) {
				return Math.PI / 2;
			}
		}), $(F.Corner.CL, {
			xy: function(e) {
				var t = e.env.c;
				return {
					x: -t.l,
					y: (t.u - t.d) / 2
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Corner.CR, {
			xy: function(e) {
				var t = e.env.c;
				return {
					x: t.r,
					y: (t.u - t.d) / 2
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Corner.CD, {
			xy: function(e) {
				var t = e.env.c;
				return {
					x: (t.r - t.l) / 2,
					y: -t.d
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Corner.CU, {
			xy: function(e) {
				var t = e.env.c;
				return {
					x: (t.r - t.l) / 2,
					y: t.u
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Corner.LU, {
			xy: function(e) {
				var t = e.env.c;
				return {
					x: -t.l,
					y: t.u
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Corner.LD, {
			xy: function(e) {
				var t = e.env.c;
				return {
					x: -t.l,
					y: -t.d
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Corner.RU, {
			xy: function(e) {
				var t = e.env.c;
				return {
					x: t.r,
					y: t.u
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Corner.RD, {
			xy: function(e) {
				var t = e.env.c;
				return {
					x: t.r,
					y: -t.d
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Corner.NearestEdgePoint, {
			xy: function(e) {
				var t = e.env, n = t.c, r = n.edgePoint(t.p.x, t.p.y);
				return {
					x: r.x - n.x,
					y: r.y - n.y
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Corner.PropEdgePoint, {
			xy: function(e) {
				var t = e.env, n = t.c, r = n.proportionalEdgePoint(t.p.x, t.p.y);
				return {
					x: r.x - n.x,
					y: r.y - n.y
				};
			},
			angle: function(e) {
				var t = this.xy(e);
				return Math.atan2(t.y, t.x);
			}
		}), $(F.Corner.Axis, {
			xy: function(e) {
				return {
					x: 0,
					y: A.measure.axisHeightLength
				};
			},
			angle: function(e) {
				return Math.PI / 2;
			}
		}), $(F.Modifier, { proceedModifyShape: function(e, t, n) {
			return n.isEmpty ? t : n.head.modifyShape(e, t, n.tail);
		} }), $(F.Modifier.Vector, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = this.vector.xy(e), i = e.env;
				return i.c = i.c.shiftFrame(-r.x, -r.y), t = new Y.TranslateShape(-r.x, -r.y, t), this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.RestoreOriginalRefPoint, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = e.env, i = r.originalReferencePoint;
				if (i !== void 0) {
					var a = r.c.x - i.x, o = r.c.y - i.y;
					r.c = r.c.shiftFrame(a, o), t = new Y.TranslateShape(a, o, t);
				}
				return this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.Point, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = e.env.c;
				return e.env.c = new U.Point(r.x, r.y), this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.Rect, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = e.env.c;
				return e.env.c = new U.Rect(r.x, r.y, {
					l: r.l,
					r: r.r,
					u: r.u,
					d: r.d
				}), this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.Circle, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = e.env.c;
				return e.env.c = new U.Ellipse(r.x, r.y, r.l, r.r, r.u, r.d), this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.L, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = e.env, i = r.c;
				if (i !== void 0) {
					var a, o, s = i.r + i.l, c = i.u + i.d;
					s < c ? (a = (i.l - i.r) / 2, o = (i.d - i.u) / 2) : (a = -i.r + c / 2, o = (i.d - i.u) / 2), r.c = r.c.shiftFrame(a, o), t = new Y.TranslateShape(a, o, t);
				}
				return this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.R, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = e.env, i = r.c;
				if (i !== void 0) {
					var a, o, s = i.r + i.l, c = i.u + i.d;
					s < c ? (a = (i.l - i.r) / 2, o = (i.d - i.u) / 2) : (a = i.l - c / 2, o = (i.d - i.u) / 2), r.c = r.c.shiftFrame(a, o), t = new Y.TranslateShape(a, o, t);
				}
				return this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.U, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = e.env, i = r.c;
				if (i !== void 0) {
					var a, o, s = i.r + i.l;
					s > i.u + i.d ? (a = (i.l - i.r) / 2, o = (i.d - i.u) / 2) : (a = (i.l - i.r) / 2, o = i.d - s / 2), r.c = r.c.shiftFrame(a, o), t = new Y.TranslateShape(a, o, t);
				}
				return this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.D, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = e.env, i = r.c;
				if (i !== void 0) {
					var a, o, s = i.r + i.l;
					s > i.u + i.d ? (a = (i.l - i.r) / 2, o = (i.d - i.u) / 2) : (a = (i.l - i.r) / 2, o = -i.u + s / 2), r.c = r.c.shiftFrame(a, o), t = new Y.TranslateShape(a, o, t);
				}
				return this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.C, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r, i, a = e.env, o = a.c;
				return o !== void 0 && (r = (o.l - o.r) / 2, i = (o.d - o.u) / 2, a.c = a.c.shiftFrame(r, i), t = new Y.TranslateShape(r, i, t)), this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.ChangeColor, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				return t = this.proceedModifyShape(e, t, n), new Y.ChangeColorShape(this.colorName, t);
			}
		}), $(F.Modifier.Shape.Alphabets, {
			preprocess: function(e, t) {
				var n = A.repositories.modifierRepository.get(this.alphabets);
				if (n !== void 0) return n.preprocess(e, t);
			},
			modifyShape: function(e, t, n) {
				var r = A.repositories.modifierRepository.get(this.alphabets);
				if (r !== void 0) return r.modifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.DefineShape, {
			preprocess: function(e, t) {
				var n = t.reverse();
				A.repositories.modifierRepository.put(this.shape, new F.Modifier.Shape.CompositeModifiers(n));
			},
			modifyShape: function(e, t, n) {
				return this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.CompositeModifiers, {
			preprocess: function(e, t) {
				this.modifiers.foreach((function(n) {
					n.preprocess(e, t), t = t.prepend(n);
				}));
			},
			modifyShape: function(e, t, n) {
				return t = this.proceedModifyShape(e, t, this.modifiers), this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Invisible, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				return t = this.proceedModifyShape(e, t, n), Y.none;
			}
		}), $(F.Modifier.Hidden, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				return this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Direction, {
			preprocess: function(e, t) {
				e.env.angle = this.direction.angle(e);
			},
			modifyShape: function(e, t, n) {
				return e.env.angle = this.direction.angle(e), this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.AddOp, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = e.env.c;
				return e.env.c = this.op.apply(this.size, r, e), e.appendShapeToFront(new Y.InvisibleBoxShape(e.env.c)), this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.AddOp.Grow, {
			apply: function(e, t, n) {
				var r = n.env, i = e.isDefault ? {
					x: 2 * r.objectmargin,
					y: 2 * r.objectmargin
				} : e.vector.xy(n), a = Math.abs(i.x / 2), o = Math.abs(i.y / 2);
				return t.grow(a, o);
			},
			applyToDimen: function(e, t) {
				return e + t;
			}
		}), $(F.Modifier.AddOp.Shrink, {
			apply: function(e, t, n) {
				var r = n.env, i = e.isDefault ? {
					x: 2 * r.objectmargin,
					y: 2 * r.objectmargin
				} : e.vector.xy(n), a = -Math.abs(i.x / 2), o = -Math.abs(i.y / 2);
				return t.grow(a, o);
			},
			applyToDimen: function(e, t) {
				return e - t;
			}
		}), $(F.Modifier.AddOp.Set, {
			apply: function(e, t, n) {
				var r = n.env, i = e.isDefault ? {
					x: r.objectwidth,
					y: r.objectheight
				} : e.vector.xy(n), a = Math.abs(i.x), o = Math.abs(i.y);
				return t.toSize(a, o);
			},
			applyToDimen: function(e, t) {
				return t;
			}
		}), $(F.Modifier.AddOp.GrowTo, {
			apply: function(e, t, n) {
				var r = Math.max(t.l + t.r, t.u + t.d), i = e.isDefault ? {
					x: r,
					y: r
				} : e.vector.xy(n), a = Math.abs(i.x), o = Math.abs(i.y);
				return t.growTo(a, o);
			},
			applyToDimen: function(e, t) {
				return Math.max(Math.max(e, t), 0);
			}
		}), $(F.Modifier.AddOp.ShrinkTo, {
			apply: function(e, t, n) {
				var r = Math.min(t.l + t.r, t.u + t.d), i = e.isDefault ? {
					x: r,
					y: r
				} : e.vector.xy(n), a = Math.abs(i.x), o = Math.abs(i.y);
				return t.shrinkTo(a, o);
			},
			applyToDimen: function(e, t) {
				return Math.max(Math.min(e, t), 0);
			}
		}), $(F.Modifier.Shape.Frame, {
			preprocess: function(e, t) {},
			modifyShape: function(e, t, n) {
				var r = e.env;
				if (r.c !== void 0) {
					this.main;
					var i = new F.ObjectBox.Frame.Radius.Default(), a = `currentColor`;
					this.options.foreach((function(e) {
						i = e.getRadius(i);
					})), this.options.foreach((function(e) {
						a = e.getColorName(a);
					}));
					var o = r.duplicate(), s = new St(Y.none, o), c = new F.ObjectBox.Frame(i, this.main).toDropFilledShape(s, a, r.c.isCircle());
					t = new Y.CompositeShape(t, c);
				}
				return this.proceedModifyShape(e, t, n);
			}
		}), $(F.Modifier.Shape.Frame.Radius, {
			getRadius: function(e) {
				return new F.ObjectBox.Frame.Radius.Vector(this.vector);
			},
			getColorName: function(e) {
				return e;
			}
		}), $(F.Modifier.Shape.Frame.Color, {
			getRadius: function(e) {
				return e;
			},
			getColorName: function(e) {
				return this.colorName;
			}
		}), $(F.Direction.Compound, { angle: function(e) {
			var t = this.dir.angle(e);
			return this.rots.foreach((function(n) {
				t = n.rotate(t, e);
			})), t;
		} }), $(F.Direction.Diag, { angle: function(e) {
			return this.diag.angle(e);
		} }), $(F.Direction.Vector, { angle: function(e) {
			return this.vector.angle(e);
		} }), $(F.Direction.ConstructVector, { angle: function(e) {
			var t = e.env, n = t.origin, r = t.xBase, i = t.yBase, a = t.p, o = t.c;
			this.posDecor.toShape(e);
			var s = Math.atan2(t.c.y - t.p.y, t.c.x - t.p.x);
			return t.c = o, t.p = a, t.origin = n, t.xBase = r, t.yBase = i, s;
		} }), $(F.Direction.RotVector, { rotate: function(e, t) {
			return e + this.vector.angle(t);
		} }), $(F.Direction.RotCW, { rotate: function(e, t) {
			return e + Math.PI / 2;
		} }), $(F.Direction.RotAntiCW, { rotate: function(e, t) {
			return e - Math.PI / 2;
		} }), $(F.Diag.Default, {
			isEmpty: !0,
			angle: function(e) {
				return e.env.angle;
			}
		}), $(F.Diag.Angle, {
			isEmpty: !1,
			angle: function(e) {
				return this.ang;
			}
		}), $(F.Decor, { toShape: function(e) {
			this.commands.foreach((function(t) {
				t.toShape(e);
			}));
		} }), $(F.Command.Save, { toShape: function(e) {
			e.env.saveState(), this.pos.toShape(e);
		} }), $(F.Command.Restore, { toShape: function(e) {
			e.env.restoreState();
		} }), $(F.Command.Pos, { toShape: function(e) {
			this.pos.toShape(e);
		} }), $(F.Command.AfterPos, { toShape: function(e) {
			this.pos.toShape(e), this.decor.toShape(e);
		} }), $(F.Command.Drop, { toShape: function(e) {
			this.object.toDropShape(e);
		} }), $(F.Command.Connect, { toShape: function(e) {
			this.object.toConnectShape(e);
		} }), $(F.Command.Relax, { toShape: function(e) {} }), $(F.Command.Ignore, { toShape: function(e) {} }), $(F.Command.ShowAST, { toShape: function(e) {
			console.log(this.pos.toString() + ` ` + this.decor);
		} }), $(F.Command.Ar, { toShape: function(e) {
			var t = e.env, n = t.origin, r = t.xBase, i = t.yBase, a = t.p, o = t.c;
			t.pathActionForBeforeSegment = y.empty, t.pathActionForAfterSegment = y.empty, t.labelsForNextSegmentOnly = y.empty, t.labelsForLastSegmentOnly = y.empty, t.labelsForEverySegment = y.empty, t.segmentSlideEm = y.empty, t.lastTurnDiag = y.empty, t.arrowVariant = ``, t.tailTip = new F.Command.Ar.Form.Tip.Tipchars(``), t.headTip = new F.Command.Ar.Form.Tip.Tipchars(`>`), t.stemConn = new F.Command.Ar.Form.Conn.Connchars(`-`), t.reverseAboveAndBelow = !1, t.arrowObjectModifiers = O.empty, this.forms.foreach((function(t) {
				t.toShape(e);
			})), t.pathActionForBeforeSegment.isDefined || (t.pathActionForBeforeSegment = new y.Some(new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.ConnectObject(new F.Object(t.arrowObjectModifiers, t.stemConn.getObject(e))))), new F.Decor(O.empty)))), t.labelsForNextSegmentOnly = new y.Some(new F.Command.Path.Labels(O.empty.append(new F.Command.Path.Label.At(new F.Pos.Place(new F.Place(1, 1, new F.Place.Factor(0), new F.Slide(y.empty))), t.tailTip.getObject(e), y.empty)))), t.labelsForLastSegmentOnly = new y.Some(new F.Command.Path.Labels(O.empty.append(new F.Command.Path.Label.At(new F.Pos.Place(new F.Place(1, 1, new F.Place.Factor(1), new F.Slide(y.empty))), t.headTip.getObject(e), y.empty)))), this.path.toShape(e), t.c = o, t.p = a, t.origin = n, t.xBase = r, t.yBase = i;
		} }), $(F.Command.Ar.Form.BuildArrow, { toShape: function(e) {
			var t = e.env;
			t.arrowVariant = this.variant, t.tailTip = this.tailTip, t.stemConn = this.stemConn, t.headTip = this.headTip;
		} }), $(F.Command.Ar.Form.ChangeVariant, { toShape: function(e) {
			e.env.arrowVariant = this.variant;
		} }), $(F.Command.Ar.Form.ChangeStem, { toShape: function(e) {
			e.env.stemConn = new F.Command.Ar.Form.Conn.Connchars(this.connchar);
		} }), $(F.Command.Ar.Form.DashArrowStem, { toShape: function(e) {} }), $(F.Command.Ar.Form.CurveArrow, { toShape: function(e) {
			var t = e.env, n = A.measure.em2length(2 * A.measure.length2em(this.dist));
			t.pathActionForBeforeSegment = new y.Some(new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.ConnectObject(new F.Object(t.arrowObjectModifiers, new F.ObjectBox.Curve(O.empty, O.empty.append(new F.ObjectBox.Curve.Object.Connect(t.stemConn.getObject(e))), O.empty.append(new F.ObjectBox.Curve.PosList.Pos(new F.Pos.Coord(new F.Coord.Group(new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.ConnectObject(new F.Object(O.empty, new F.ObjectBox.Dir(``, ``)))).append(new F.Pos.Place(new F.Place(0, 0, void 0, new F.Slide(y.empty)))).append(new F.Pos.Plus(new F.Coord.Vector(new F.Vector.Dir(this.direction, n))))), new F.Decor(O.empty))), O.empty)))))))), new F.Decor(O.empty)));
		} }), $(F.Command.Ar.Form.CurveFitToDirection, { toShape: function(e) {
			var t = e.env;
			t.pathActionForBeforeSegment = new y.Some(new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.ConnectObject(new F.Object(t.arrowObjectModifiers, new F.ObjectBox.Curve(O.empty, O.empty.append(new F.ObjectBox.Curve.Object.Connect(t.stemConn.getObject(e))), O.empty.append(new F.ObjectBox.Curve.PosList.Pos(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.SwapPAndC(new F.Coord.C())).append(new F.Pos.Plus(new F.Coord.Vector(new F.Vector.Dir(this.outDirection, `3pc`))))))).append(new F.ObjectBox.Curve.PosList.Pos(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.SwapPAndC(new F.Coord.C())).append(new F.Pos.Plus(new F.Coord.Vector(new F.Vector.Dir(this.inDirection, `3pc`)))))))))))), new F.Decor(O.empty)));
		} }), $(F.Command.Ar.Form.CurveWithControlPoints, { toShape: function(e) {
			var t = e.env, n = t.duplicate();
			n.startCapturePositions();
			var r = new St(Y.none, n);
			this.coord.position(r);
			var i = n.endCapturePositions();
			i = i.append(n.c);
			var a = O.empty;
			i.reverse().foreach((function(e) {
				var n = t.inverseAbsVector(e.x, e.y);
				a = a.prepend(new F.ObjectBox.Curve.PosList.Pos(new F.Pos.Coord(new F.Coord.Vector(new F.Vector.InCurBase(n.x, n.y)), O.empty)));
			})), t.pathActionForBeforeSegment = new y.Some(new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.ConnectObject(new F.Object(t.arrowObjectModifiers, new F.ObjectBox.Curve(O.empty, O.empty.append(new F.ObjectBox.Curve.Object.Connect(t.stemConn.getObject(e))), a))))), new F.Decor(O.empty)));
		} }), $(F.Command.Ar.Form.AddShape, { toShape: function(e) {
			e.env.arrowObjectModifiers = O.empty.append(this.shape);
		} }), $(F.Command.Ar.Form.AddModifiers, { toShape: function(e) {
			e.env.arrowObjectModifiers = this.modifiers;
		} }), $(F.Command.Ar.Form.Slide, { toShape: function(e) {
			e.env.segmentSlideEm = new y.Some(A.measure.length2em(this.slideDimen));
		} }), $(F.Command.Ar.Form.LabelAt, { toShape: function(e) {
			e.env.labelsForEverySegment = new y.Some(new F.Command.Path.Labels(O.empty.append(new F.Command.Path.Label.At(new F.Pos.Place(this.anchor), this.it, y.empty))));
		} }), $(F.Command.Ar.Form.LabelAbove, { toShape: function(e) {
			var t, n = e.env;
			t = n.reverseAboveAndBelow ? new F.Command.Path.Label.Below(new F.Pos.Place(this.anchor), this.it, y.empty) : new F.Command.Path.Label.Above(new F.Pos.Place(this.anchor), this.it, y.empty), n.labelsForEverySegment = new y.Some(new F.Command.Path.Labels(O.empty.append(t)));
		} }), $(F.Command.Ar.Form.LabelBelow, { toShape: function(e) {
			var t, n = e.env;
			t = n.reverseAboveAndBelow ? new F.Command.Path.Label.Above(new F.Pos.Place(this.anchor), this.it, y.empty) : new F.Command.Path.Label.Below(new F.Pos.Place(this.anchor), this.it, y.empty), n.labelsForEverySegment = new y.Some(new F.Command.Path.Labels(O.empty.append(t)));
		} }), $(F.Command.Ar.Form.ReverseAboveAndBelow, { toShape: function(e) {
			e.env.reverseAboveAndBelow = !0;
		} }), $(F.Command.Ar.Form.Conn.Connchars, { getObject: function(e) {
			var t = e.env, n = new F.ObjectBox.Dir(t.arrowVariant, this.connchars);
			return new F.Object(t.arrowObjectModifiers, n);
		} }), $(F.Command.Ar.Form.Conn.Object, { getObject: function(e) {
			var t = e.env.arrowObjectModifiers.concat(this.object.modifiers);
			return new F.Object(t, this.object.object);
		} }), $(F.Command.Ar.Form.Conn.Dir, { getObject: function(e) {
			var t = e.env, n = this.dir, r = n;
			return n.variant === `` && t.arrowVariant !== `` && (r = new F.ObjectBox.Dir(t.arrowVariant, n.main)), new F.Object(t.arrowObjectModifiers, r);
		} }), $(F.Command.Ar.Form.Tip.Tipchars, { getObject: function(e) {
			var t = e.env, n = new F.ObjectBox.Dir(t.arrowVariant, this.tipchars);
			return new F.Object(t.arrowObjectModifiers, n);
		} }), $(F.Command.Ar.Form.Tip.Object, { getObject: function(e) {
			var t = e.env.arrowObjectModifiers.concat(this.object.modifiers);
			return new F.Object(t, this.object.object);
		} }), $(F.Command.Ar.Form.Tip.Dir, { getObject: function(e) {
			var t = e.env, n = this.dir, r = n;
			return n.variant === `` && t.arrowVariant !== `` && (r = new F.ObjectBox.Dir(t.arrowVariant, n.main)), new F.Object(t.arrowObjectModifiers, r);
		} }), $(F.Command.Path, { toShape: function(e) {
			var t = e.env, n = t.origin, r = t.xBase, i = t.yBase, a = t.p, o = t.c;
			t.pathActionForBeforeSegment = y.empty, t.pathActionForAfterSegment = y.empty, t.labelsForNextSegmentOnly = y.empty, t.labelsForLastSegmentOnly = y.empty, t.labelsForEverySegment = y.empty, t.segmentSlideEm = y.empty, t.lastTurnDiag = y.empty, this.path.toShape(e), t.c = o, t.p = a, t.origin = n, t.xBase = r, t.yBase = i;
		} }), $(F.Command.AfterPath, { toShape: function(e) {
			this.path.toShape(e), this.decor.toShape(e);
		} }), $(F.Command.Path.Path, { toShape: function(e) {
			this.pathElements.foreach((function(t) {
				t.toShape(e);
			}));
		} }), $(F.Command.Path.SetBeforeAction, { toShape: function(e) {
			e.env.pathActionForBeforeSegment = new y.Some(this.posDecor);
		} }), $(F.Command.Path.SetAfterAction, { toShape: function(e) {
			e.env.pathActionForAfterSegment = new y.Some(this.posDecor);
		} }), $(F.Command.Path.AddLabelNextSegmentOnly, { toShape: function(e) {
			e.env.labelsForNextSegmentOnly = new y.Some(this.labels);
		} }), $(F.Command.Path.AddLabelLastSegmentOnly, { toShape: function(e) {
			e.env.labelsForLastSegmentOnly = new y.Some(this.labels);
		} }), $(F.Command.Path.AddLabelEverySegment, { toShape: function(e) {
			e.env.labelsForEverySegment = new y.Some(this.labels);
		} }), $(F.Command.Path.StraightSegment, { toShape: function(e) {
			var t = e.env;
			this.segment.setupPositions(e);
			var n = t.c;
			t.pathActionForBeforeSegment.foreach((function(t) {
				t.toShape(e);
			})), t.labelsForNextSegmentOnly.foreach((function(n) {
				n.toShape(e), t.labelsForNextSegmentOnly = y.empty;
			})), t.labelsForEverySegment.foreach((function(t) {
				t.toShape(e);
			})), t.c = n, t.pathActionForAfterSegment.foreach((function(t) {
				t.toShape(e);
			})), this.segment.toLabelsShape(e);
		} }), $(F.Command.Path.LastSegment, { toShape: function(e) {
			var t = e.env;
			this.segment.setupPositions(e);
			var n = t.c;
			t.pathActionForBeforeSegment.foreach((function(t) {
				t.toShape(e);
			})), t.labelsForNextSegmentOnly.foreach((function(n) {
				n.toShape(e), t.labelsForNextSegmentOnly = y.empty;
			})), t.labelsForLastSegmentOnly.foreach((function(n) {
				n.toShape(e), t.labelsForNextSegmentOnly = y.empty;
			})), t.labelsForEverySegment.foreach((function(t) {
				t.toShape(e);
			})), t.c = n, t.pathActionForAfterSegment.foreach((function(t) {
				t.toShape(e);
			})), this.segment.toLabelsShape(e);
		} }), $(F.Command.Path.TurningSegment, { toShape: function(e) {
			var t = e.env, n = t.c;
			this.segment.pos.toShape(e), t.p = n;
			var r = this.turn.explicitizedCircle(e), i = this.turn.radius.radius(e);
			t.lastTurnDiag = new y.Some(r.endDiag);
			var a = r.startVector(e), o = r.endVector(e), s = t.segmentSlideEm.getOrElse(0);
			this.segment.slide.dimen.foreach((function(e) {
				s = A.measure.length2em(e), t.segmentSlideEm = new y.Some(s);
			})), s !== 0 && (t.p = t.p.move(t.p.x - s * a.y, t.p.y + s * a.x), t.c = t.c.move(t.c.x - s * o.y, t.c.y + s * o.x), i = r.orient === `^` ? Math.max(0, i - s) : Math.max(0, i + s));
			var c, u = t.p.edgePoint(t.p.x + a.x, t.p.y + a.y), d = t.c, f = r.relativeStartPoint(e, i), p = r.relativeEndPoint(e, i), m = r.relativeEndPoint(e, i + (r.orient === `^` ? s : -s)), h = a.x * o.y - a.y * o.x;
			if (Math.abs(h) < l.machinePrecision) c = 0;
			else {
				var g = d.x - u.x + f.x - p.x, _ = d.y - u.y + f.y - p.y;
				(c = (o.y * g - o.x * _) / h) < 0 && (c = 0);
			}
			var v = u.x - f.x + c * a.x, b = u.y - f.y + c * a.y, x = (r.toDropShape(e, v, b, i), new U.Point(v + m.x, b + m.y));
			t.c = new U.Point(v + f.x, b + f.y), t.pathActionForBeforeSegment.foreach((function(t) {
				t.toShape(e);
			})), t.labelsForNextSegmentOnly.foreach((function(n) {
				n.toShape(e), t.labelsForNextSegmentOnly = y.empty;
			})), t.labelsForEverySegment.foreach((function(t) {
				t.toShape(e);
			})), t.c = x, t.pathActionForAfterSegment.foreach((function(t) {
				t.toShape(e);
			})), this.segment.toLabelsShape(e);
		} }), $(F.Command.Path.Turn.Cir, { explicitizedCircle: function(e) {
			var t, n, r, i = e.env;
			return t = this.cir.startDiag.isEmpty ? i.lastTurnDiag.getOrElse(new F.Diag.R()) : this.cir.startDiag, n = this.cir.orient, r = this.cir.endDiag.isEmpty ? t.turn(n) : this.cir.endDiag, new F.ObjectBox.Cir.Cir.Segment(t, n, r);
		} }), $(F.ObjectBox.Cir.Cir.Segment, {
			startVector: function(e) {
				var t = this.startDiag.angle(e);
				return {
					x: Math.cos(t),
					y: Math.sin(t)
				};
			},
			endVector: function(e) {
				var t = this.endDiag.angle(e);
				return {
					x: Math.cos(t),
					y: Math.sin(t)
				};
			},
			relativeStartPointAngle: function(e) {
				return this.startPointDegree(e) / 180 * Math.PI;
			},
			relativeStartPoint: function(e, t) {
				var n = this.startPointDegree(e) / 180 * Math.PI;
				return {
					x: t * Math.cos(n),
					y: t * Math.sin(n)
				};
			},
			relativeEndPoint: function(e, t) {
				var n;
				return n = this.endPointDegree(e, this.relativeStartPointAngle(e)) / 180 * Math.PI, {
					x: t * Math.cos(n),
					y: t * Math.sin(n)
				};
			}
		}), $(F.Command.Path.Turn.Diag, { explicitizedCircle: function(e) {
			var t, n, r, i = e.env, a = (t = this.diag.isEmpty ? i.lastTurnDiag.getOrElse(new F.Diag.R()) : this.diag).angle(e);
			return n = (i.c.x - i.p.x) * Math.sin(a) - (i.c.y - i.p.y) * Math.cos(a) < 0 ? `^` : `_`, r = t.turn(n), new F.ObjectBox.Cir.Cir.Segment(t, n, r);
		} }), $(F.Command.Path.TurnRadius.Default, { radius: function(e) {
			return A.measure.turnradius;
		} }), $(F.Command.Path.TurnRadius.Dimen, { radius: function(e) {
			return A.measure.length2em(this.dimen);
		} }), $(F.Command.Path.Segment, {
			setupPositions: function(e) {
				var t = e.env;
				t.p = t.c, this.pos.toShape(e);
				var n = t.p, r = t.c, i = r.x - n.x, a = r.y - n.y, o = Math.atan2(a, i) + Math.PI / 2, s = t.segmentSlideEm.getOrElse(0);
				this.slide.dimen.foreach((function(e) {
					s = A.measure.length2em(e), t.segmentSlideEm = new y.Some(s);
				})), s !== 0 && (n = n.move(n.x + s * Math.cos(o), n.y + s * Math.sin(o)), r = r.move(r.x + s * Math.cos(o), r.y + s * Math.sin(o))), t.p = n, t.c = r;
			},
			toLabelsShape: function(e) {
				var t = e.env, n = t.c, r = t.p;
				this.labels.toShape(e), t.c = n, t.p = r;
			}
		}), $(F.Command.Path.Labels, { toShape: function(e) {
			this.labels.foreach((function(t) {
				t.toShape(e);
			}));
		} }), $(F.Command.Path.Label, { toShape: function(e) {
			var t = e.env, n = t.p, r = t.c, i = this.anchor.toShape(e), a = this.getLabelMargin(e);
			if (a !== 0) {
				var o = (b = t.lastCurve).isNone ? Math.atan2(r.y - n.y, r.x - n.x) + Math.PI / 2 : b.angle(i) + Math.PI / 2 + (a > 0 ? 0 : Math.PI);
				r = t.c;
				var s = new St(Y.none, t);
				this.it.toDropShape(s);
				var c = s.shape, l = c.getBoundingBox();
				if (l !== void 0) {
					var u = l.x - r.x, d = l.y - r.y, f = l.l, p = l.r, m = l.u, h = l.d, g = Math.cos(o), _ = Math.sin(o), v = Math.min((u - f) * g + (d - h) * _, (u - f) * g + (d + m) * _, (u + p) * g + (d - h) * _, (u + p) * g + (d + m) * _), y = Math.abs(a) - v;
					t.c = t.c.move(r.x + y * g, r.y + y * _), e.appendShapeToFront(new Y.TranslateShape(y * g, y * _, c));
				}
			} else this.it.toDropShape(e);
			var b = t.lastCurve;
			this.shouldSliceHole && b.isDefined && i !== void 0 && b.sliceHole(t.c, i), this.aliasOption.foreach((function(e) {
				t.savePos(e, new It.Position(t.c));
			}));
		} }), $(F.Command.Path.Label.Above, {
			getLabelMargin: function(e) {
				return e.env.labelmargin;
			},
			shouldSliceHole: !1
		}), $(F.Command.Path.Label.Below, {
			getLabelMargin: function(e) {
				return -e.env.labelmargin;
			},
			shouldSliceHole: !1
		}), $(F.Command.Path.Label.At, {
			getLabelMargin: function(e) {
				return 0;
			},
			shouldSliceHole: !0
		}), $(F.Command.Xymatrix, { toShape: function(e) {
			var t = e.env;
			if (t.c === void 0) return Y.none;
			var n = t.duplicate(), r = new St(Y.none, n);
			n.xymatrixPrefix = ``, n.xymatrixRowSepEm = A.measure.length2em(`2pc`), n.xymatrixColSepEm = A.measure.length2em(`2pc`), n.xymatrixPretendEntryHeight = y.empty, n.xymatrixPretendEntryWidth = y.empty, n.xymatrixFixedRow = !1, n.xymatrixFixedCol = !1, n.xymatrixOrientationAngle = 0, n.xymatrixEntryModifiers = O.empty, this.setup.foreach((function(e) {
				e.toShape(r);
			}));
			var i, a, o = n.xymatrixOrientationAngle, s = 0, c = 0, l = new Bt(this.rows.map((function(e) {
				c += 1, a = 0;
				var t = new Bt.Row(e.entries.map((function(e) {
					a += 1;
					var t = n.duplicate();
					t.origin = {
						x: 0,
						y: 0
					}, t.p = t.c = Mt.originPosition, t.angle = 0, t.lastCurve = Q.none, t.xymatrixRow = c, t.xymatrixCol = a;
					var r, i, o, s, l = new St(Y.none, t), u = e.toShape(l), d = t.c;
					if (n.xymatrixPretendEntryHeight.isDefined) {
						var f = n.xymatrixPretendEntryHeight.get;
						o = f / 2, s = f / 2;
					} else o = d.u, s = d.d;
					if (n.xymatrixPretendEntryWidth.isDefined) {
						var p = n.xymatrixPretendEntryWidth.get;
						r = p / 2, i = p / 2;
					} else r = d.l, i = d.r;
					var m = new U.Rect(0, 0, {
						l: r,
						r: i,
						u: o,
						d: s
					});
					return new Bt.Entry(t.c, u, e.decor, m);
				})), o);
				return s = Math.max(s, a), t;
			})), o);
			if ((i = c) === 0) return Y.none;
			l.rows.foreach((function(e) {
				a = 0, e.entries.foreach((function(e) {
					a += 1, l.getColumn(a).addEntry(e);
				}));
			}));
			var u, d, f = n.xymatrixColSepEm, p = [], m = t.c.x;
			if (p.push(m), n.xymatrixFixedCol) {
				var h = 0, g = 0;
				l.columns.foreach((function(e) {
					h = Math.max(h, e.getL()), g = Math.max(g, e.getR());
				})), l.columns.tail.foreach((function(e) {
					m = m + g + f + h, p.push(m);
				})), u = h, d = p[p.length - 1] + g;
			} else {
				var _ = l.columns.head;
				l.columns.tail.foreach((function(e) {
					m = m + _.getR() + f + e.getL(), p.push(m), _ = e;
				})), u = l.columns.head.getL(), d = m + l.columns.at(s - 1).getR() - p[0];
			}
			var v, b, x = n.xymatrixRowSepEm, S = [], C = t.c.y;
			if (S.push(C), n.xymatrixFixedRow) {
				var w = 0, T = 0;
				l.rows.foreach((function(e) {
					w = Math.max(w, e.getU()), T = Math.max(T, e.getD());
				})), l.rows.tail.foreach((function(e) {
					C -= T + x + w, S.push(C);
				})), v = w, b = S[0] - S[S.length - 1] + T;
			} else {
				var E = l.rows.head;
				l.rows.tail.foreach((function(e) {
					C -= E.getD() + x + e.getU(), S.push(C), E = e;
				})), v = l.rows.head.getU(), b = S[0] - C + l.rows.at(i - 1).getD();
			}
			t.c = new U.Rect(t.c.x, t.c.y, {
				l: u,
				r: d,
				u: v,
				d: b
			});
			var D = n.xymatrixPrefix, ee = Math.cos(o), te = Math.sin(o), ne = 0;
			l.rows.foreach((function(e) {
				var t = 0;
				e.entries.foreach((function(e) {
					var r = p[t], i = S[ne], a = r * ee - i * te, o = r * te + i * ee, s = t + 1, c = ne + 1, l = new It.Position(e.c.move(a, o));
					n.savePos(c + `,` + s, l), n.savePos(D + c + `,` + s, l), t += 1;
				})), ne += 1;
			})), r = new St(Y.none, n), ne = 0, l.rows.foreach((function(e) {
				var t = 0;
				e.entries.foreach((function(e) {
					var i = p[t], a = S[ne], o = i * ee - a * te, s = i * te + a * ee, c = t + 1, l = ne + 1, u = new Y.TranslateShape(o, s, e.objectShape);
					r.appendShapeToFront(u), n.c = e.c.move(o, s), n.xymatrixRow = l, n.xymatrixCol = c, e.decor.toShape(r), t += 1;
				})), ne += 1;
			}));
			var re = r.shape;
			return e.appendShapeToFront(re), t.savedPosition = n.savedPosition, re;
		} });
		var Bt = function() {
			function e(t, n) {
				Lt(this, e), this.rows = t, this.columns = O.empty, this.orientation = n;
			}
			return zt(e, [{
				key: `getColumn`,
				value: function(t) {
					if (this.columns.length() >= t) return this.columns.at(t - 1);
					var n = new e.Column(this.orientation);
					return this.columns = this.columns.append(n), n;
				}
			}, {
				key: `toString`,
				value: function() {
					return `Xymatrix{
` + this.rows.mkString(`\\\\
`) + `
}`;
				}
			}]), e;
		}();
		function Vt(e, t, n) {
			var r = [], i = [], a = {
				lastNoSuccess: void 0,
				whiteSpaceRegex: l.whiteSpaceRegex,
				createTextNode: function(t) {
					var n = new o.Z(t, e.stack.env, e.configuration).mml(), a = A.textObjectIdCounter;
					return A.textObjectIdCounter++, r.push(n), i.push(a), n;
				}
			}, s = new Se(e.string, e.i, a), u = k.parse(t, s);
			if (e.i = u.next.offset, u.successful) {
				var d = `` + A.xypicCommandIdCounter;
				A.xypicCommandIdCounter++, A.xypicCommandMap[d] = u.get();
				var f = JSON.stringify(i);
				return e.create(n, {
					"data-cmd-id": d,
					"data-text-mml-ids": f
				}, r);
			}
			var p = a.lastNoSuccess.next.pos().lineContents();
			throw c(`SyntaxError`, a.lastNoSuccess.msg + `. Parse error at or near "` + p + `".`);
		}
		Bt.Row = function() {
			function e(t, n) {
				Lt(this, e), this.entries = t, this.orientation = n, H(this, `getU`), H(this, `getD`);
			}
			return zt(e, [
				{
					key: `getU`,
					value: function() {
						var e = this.orientation, t = 0;
						return this.entries.foreach((function(n) {
							t = Math.max(t, n.getU(e));
						})), t;
					}
				},
				{
					key: `getD`,
					value: function() {
						var e = this.orientation, t = 0;
						return this.entries.foreach((function(n) {
							t = Math.max(t, n.getD(e));
						})), t;
					}
				},
				{
					key: `toString`,
					value: function() {
						return this.entries.mkString(` & `);
					}
				}
			]), e;
		}(), Bt.Column = function() {
			function e(t) {
				Lt(this, e), this.entries = O.empty, this.orientation = t, H(this, `getL`), H(this, `getR`);
			}
			return zt(e, [
				{
					key: `addEntry`,
					value: function(e) {
						this.entries = this.entries.append(e), this.getL.reset, this.getR.reset;
					}
				},
				{
					key: `getL`,
					value: function() {
						var e = this.orientation, t = 0;
						return this.entries.foreach((function(n) {
							t = Math.max(t, n.getL(e));
						})), t;
					}
				},
				{
					key: `getR`,
					value: function() {
						var e = this.orientation, t = 0;
						return this.entries.foreach((function(n) {
							t = Math.max(t, n.getR(e));
						})), t;
					}
				},
				{
					key: `toString`,
					value: function() {
						return this.entries.mkString(` \\\\ `);
					}
				}
			]), e;
		}(), Bt.Entry = function() {
			function e(t, n, r, i) {
				Lt(this, e), this.c = t, this.objectShape = n, this.decor = r, this.frame = i;
			}
			return zt(e, [
				{
					key: `getDistanceToEdgePoint`,
					value: function(e, t) {
						var n = e.edgePoint(e.x + Math.cos(t), e.y + Math.sin(t)), r = n.x - e.x, i = n.y - e.y;
						return Math.sqrt(r * r + i * i);
					}
				},
				{
					key: `getU`,
					value: function(e) {
						return e === 0 ? this.frame.u : this.getDistanceToEdgePoint(this.frame, e + Math.PI / 2);
					}
				},
				{
					key: `getD`,
					value: function(e) {
						return e === 0 ? this.frame.d : this.getDistanceToEdgePoint(this.frame, e - Math.PI / 2);
					}
				},
				{
					key: `getL`,
					value: function(e) {
						return e === 0 ? this.frame.l : this.getDistanceToEdgePoint(this.frame, e + Math.PI);
					}
				},
				{
					key: `getR`,
					value: function(e) {
						return e === 0 ? this.frame.r : this.getDistanceToEdgePoint(this.frame, e);
					}
				},
				{
					key: `toString`,
					value: function() {
						return this.objectShape.toString() + ` ` + this.decor;
					}
				}
			]), e;
		}(), $(F.Command.Xymatrix.Setup.Prefix, { toShape: function(e) {
			e.env.xymatrixPrefix = this.prefix;
		} }), $(F.Command.Xymatrix.Setup.ChangeSpacing.Row, { toShape: function(e) {
			var t = e.env;
			t.xymatrixRowSepEm = this.addop.applyToDimen(t.xymatrixRowSepEm, A.measure.length2em(this.dimen));
		} }), $(F.Command.Xymatrix.Setup.ChangeSpacing.Column, { toShape: function(e) {
			var t = e.env;
			t.xymatrixColSepEm = this.addop.applyToDimen(t.xymatrixColSepEm, A.measure.length2em(this.dimen));
		} }), $(F.Command.Xymatrix.Setup.ChangeSpacing.RowAndColumn, { toShape: function(e) {
			var t = e.env, n = this.addop.applyToDimen(t.xymatrixRowSepEm, A.measure.length2em(this.dimen));
			t.xymatrixRowSepEm = n, t.xymatrixColSepEm = n;
		} }), $(F.Command.Xymatrix.Setup.PretendEntrySize.Height, { toShape: function(e) {
			e.env.xymatrixPretendEntryHeight = new y.Some(A.measure.length2em(this.dimen));
		} }), $(F.Command.Xymatrix.Setup.PretendEntrySize.Width, { toShape: function(e) {
			e.env.xymatrixPretendEntryWidth = new y.Some(A.measure.length2em(this.dimen));
		} }), $(F.Command.Xymatrix.Setup.PretendEntrySize.HeightAndWidth, { toShape: function(e) {
			var t = new y.Some(A.measure.length2em(this.dimen));
			e.env.xymatrixPretendEntryHeight = t, e.env.xymatrixPretendEntryWidth = t;
		} }), $(F.Command.Xymatrix.Setup.FixGrid.Row, { toShape: function(e) {
			e.env.xymatrixFixedRow = !0;
		} }), $(F.Command.Xymatrix.Setup.FixGrid.Column, { toShape: function(e) {
			e.env.xymatrixFixedCol = !0;
		} }), $(F.Command.Xymatrix.Setup.FixGrid.RowAndColumn, { toShape: function(e) {
			e.env.xymatrixFixedRow = !0, e.env.xymatrixFixedCol = !0;
		} }), $(F.Command.Xymatrix.Setup.AdjustEntrySize.Margin, { toShape: function(e) {
			var t = e.env;
			t.objectmargin = this.addop.applyToDimen(t.objectmargin, A.measure.length2em(this.dimen));
		} }), $(F.Command.Xymatrix.Setup.AdjustEntrySize.Width, { toShape: function(e) {
			var t = e.env;
			t.objectwidth = this.addop.applyToDimen(t.objectwidth, A.measure.length2em(this.dimen));
		} }), $(F.Command.Xymatrix.Setup.AdjustEntrySize.Height, { toShape: function(e) {
			var t = e.env;
			t.objectheight = this.addop.applyToDimen(t.objectheight, A.measure.length2em(this.dimen));
		} }), $(F.Command.Xymatrix.Setup.AdjustLabelSep, { toShape: function(e) {
			var t = e.env;
			t.labelmargin = this.addop.applyToDimen(t.labelmargin, A.measure.length2em(this.dimen));
		} }), $(F.Command.Xymatrix.Setup.SetOrientation, { toShape: function(e) {
			e.env.xymatrixOrientationAngle = this.direction.angle(e);
		} }), $(F.Command.Xymatrix.Setup.AddModifier, { toShape: function(e) {
			var t = e.env;
			t.xymatrixEntryModifiers = t.xymatrixEntryModifiers.prepend(this.modifier);
		} }), $(F.Command.Xymatrix.Entry.SimpleEntry, { toShape: function(e) {
			var t = e.env, n = A.measure.em2length(t.objectmargin + t.objectwidth), r = A.measure.em2length(t.objectmargin + t.objectheight), i = new F.Modifier.AddOp(new F.Modifier.AddOp.GrowTo(), new F.Modifier.AddOp.VactorSize(new F.Vector.Abs(n, r))), a = A.measure.em2length(t.objectmargin), o = new F.Modifier.AddOp(new F.Modifier.AddOp.Grow(), new F.Modifier.AddOp.VactorSize(new F.Vector.Abs(a, a))), s = this.modifiers.concat(t.xymatrixEntryModifiers).prepend(i).prepend(o);
			return new F.Object(s, this.objectbox).toDropShape(e);
		} }), $(F.Command.Xymatrix.Entry.EmptyEntry, { toShape: function(e) {
			var t = e.env, n = A.measure.em2length(t.objectmargin + t.objectwidth), r = A.measure.em2length(t.objectmargin + t.objectheight), i = new F.Modifier.AddOp(new F.Modifier.AddOp.GrowTo(), new F.Modifier.AddOp.VactorSize(new F.Vector.Abs(n, r))), a = A.measure.em2length(t.objectmargin), o = new F.Modifier.AddOp(new F.Modifier.AddOp.Grow(), new F.Modifier.AddOp.VactorSize(new F.Vector.Abs(a, a))), s = t.xymatrixEntryModifiers.prepend(i).prepend(o);
			return new F.Object(s, new F.ObjectBox.Empty()).toDropShape(e);
		} }), $(F.Command.Xymatrix.Entry.ObjectEntry, { toShape: function(e) {
			return this.object.toDropShape(e);
		} }), $(F.Command.Twocell, { toShape: function(e) {
			var t = e.env;
			if (t.c === void 0) return Y.none;
			var n = t.duplicate(), r = new St(Y.none, n);
			n.twocellmodmapobject = t.twocellmodmapobject || new F.Object(O.empty, new F.ObjectBox.Dir(``, `|`)), n.twocellhead = t.twocellhead || new F.Object(O.empty, new F.ObjectBox.Dir(``, `>`)), n.twocelltail = t.twocelltail || new F.Object(O.empty, new F.ObjectBox.Dir(``, ``)), n.twocellarrowobject = t.twocellarrowobject || new F.Object(O.empty, new F.ObjectBox.Dir(``, `=>`)), n.twocellUpperCurveObjectSpacer = t.twocellUpperCurveObjectSpacer, n.twocellUpperCurveObject = t.twocellUpperCurveObject, n.twocellLowerCurveObjectSpacer = t.twocellLowerCurveObjectSpacer, n.twocellLowerCurveObject = t.twocellLowerCurveObject, n.twocellUpperLabel = y.empty, n.twocellLowerLabel = y.empty, n.twocellCurvatureEm = y.empty, n.twocellShouldDrawCurve = !0, n.twocellShouldDrawModMap = !1, this.switches.foreach((function(e) {
				e.setup(r);
			})), this.twocell.toShape(r, this.arrow), e.appendShapeToFront(r.shape);
		} }), $(F.Command.Twocell.Hops2cell, {
			toShape: function(e, t) {
				var n = e.env, r = n.c, i = n.angle, a = n.c, o = this.targetPosition(e);
				if (a !== void 0 && o !== void 0) {
					var s = o.x - a.x, c = o.y - a.y;
					if (s !== 0 || c !== 0) {
						var l = new U.Point(a.x + .5 * s, a.y + .5 * c), u = Math.atan2(c, s), d = u + Math.PI / 2, f = n.twocellCurvatureEm.getOrElse(this.getDefaultCurvature()), p = Math.cos(d), m = Math.sin(d), h = this.getUpperControlPoint(a, o, l, f, p, m), g = this.getLowerControlPoint(a, o, l, f, p, m);
						if (n.twocellShouldDrawCurve) {
							var _, v;
							if (v = (_ = n.twocellUpperCurveObjectSpacer) === void 0 ? new F.Object(O.empty, new F.ObjectBox.Dir(``, `-`)) : n.twocellUpperCurveObject === void 0 ? void 0 : n.twocellUpperCurveObject.getOrElse(void 0), this.toUpperCurveShape(e, a, h, o, _, v), n.lastCurve.isDefined) {
								n.angle = u;
								var y = this.getUpperLabelPosition(a, o, l, f, p, m), b = this.getUpperLabelAngle(d, a, o, l, f, p, m);
								n.twocellUpperLabel.foreach((function(t) {
									t.toShape(e, y, Math.cos(b), Math.sin(b), u);
								})), this.hasUpperTips && t.toUpperTipsShape(e);
							}
							if (v = (_ = n.twocellLowerCurveObjectSpacer) === void 0 ? new F.Object(O.empty, new F.ObjectBox.Dir(``, `-`)) : n.twocellLowerCurveObject === void 0 ? void 0 : n.twocellLowerCurveObject.getOrElse(void 0), this.toLowerCurveShape(e, a, g, o, _, v), n.lastCurve.isDefined) {
								n.angle = u;
								var x = this.getLowerLabelPosition(a, o, l, f, p, m), S = this.getLowerLabelAngle(d, a, o, l, f, p, m);
								n.twocellLowerLabel.foreach((function(t) {
									t.toShape(e, x, Math.cos(S), Math.sin(S), u);
								})), this.hasLowerTips && t.toLowerTipsShape(e);
							}
						}
						n.c = this.getDefaultArrowPoint(a, o, l, f, p, m), n.angle = d + Math.PI;
						var C = l;
						t.toArrowShape(e, C), n.c = r, n.angle = i;
					}
				}
			},
			_toCurveShape: function(e, t, n, r, i, a) {
				var o = e.env, s = new X.QuadBezier(t, n, r), c = s.tOfShavedStart(t), l = s.tOfShavedEnd(r);
				if (c === void 0 || l === void 0 || c >= l) o.lastCurve = Q.none;
				else {
					var u = s.toShape(e, i, a);
					o.lastCurve = new Q.QuadBezier(s, c, l, u);
				}
			},
			targetPosition: function(e) {
				var t = e.env, n = t.xymatrixRow, r = t.xymatrixCol;
				if (n === void 0 || r === void 0) throw c(`ExecutionError`, `rows and columns not found for hops [` + this.hops + `]`);
				for (var i = 0; i < this.hops.length; i++) switch (this.hops[i]) {
					case `u`:
						--n;
						break;
					case `d`:
						n += 1;
						break;
					case `l`:
						--r;
						break;
					case `r`: r += 1;
				}
				var a = n + `,` + r;
				return e.env.lookupPos(a, `in entry "` + t.xymatrixRow + `,` + t.xymatrixCol + `": No ` + this + ` (is ` + a + `) from here.`).position(e);
			}
		}), $(F.Command.Twocell.Twocell, {
			getUpperControlPoint: function(e, t, n, r, i, a) {
				return new U.Point(n.x + r * i, n.y + r * a);
			},
			getLowerControlPoint: function(e, t, n, r, i, a) {
				return new U.Point(n.x - r * i, n.y - r * a);
			},
			getUpperLabelPosition: function(e, t, n, r, i, a) {
				return new U.Point(n.x + .5 * r * i, n.y + .5 * r * a);
			},
			getLowerLabelPosition: function(e, t, n, r, i, a) {
				return new U.Point(n.x - .5 * r * i, n.y - .5 * r * a);
			},
			getUpperLabelAngle: function(e, t, n, r, i, a, o) {
				return e + (i < 0 ? Math.PI : 0);
			},
			getLowerLabelAngle: function(e, t, n, r, i, a, o) {
				return e + (i < 0 ? 0 : Math.PI);
			},
			getDefaultArrowPoint: function(e, t, n, r, i, a) {
				return n;
			},
			toUpperCurveShape: function(e, t, n, r, i, a) {
				this._toCurveShape(e, t, n, r, i, a);
			},
			toLowerCurveShape: function(e, t, n, r, i, a) {
				this._toCurveShape(e, t, n, r, i, a);
			},
			getDefaultCurvature: function() {
				return 3.5 * A.measure.lineElementLength;
			},
			hasUpperTips: !0,
			hasLowerTips: !0
		}), $(F.Command.Twocell.UpperTwocell, {
			getUpperControlPoint: function(e, t, n, r, i, a) {
				return new U.Point(n.x + r * i, n.y + r * a);
			},
			getLowerControlPoint: function(e, t, n, r, i, a) {
				return n;
			},
			getUpperLabelPosition: function(e, t, n, r, i, a) {
				return new U.Point(n.x + .5 * r * i, n.y + .5 * r * a);
			},
			getLowerLabelPosition: function(e, t, n, r, i, a) {
				return n;
			},
			getUpperLabelAngle: function(e, t, n, r, i, a, o) {
				return e + (i < 0 ? Math.PI : 0);
			},
			getLowerLabelAngle: function(e, t, n, r, i, a, o) {
				return e + (i < 0 ? 0 : Math.PI);
			},
			getDefaultArrowPoint: function(e, t, n, r, i, a) {
				return new U.Point(n.x + .25 * r * i, n.y + .25 * r * a);
			},
			toUpperCurveShape: function(e, t, n, r, i, a) {
				this._toCurveShape(e, t, n, r, i, a);
			},
			toLowerCurveShape: function(e, t, n, r, i, a) {
				var o = t.edgePoint(r.x, r.y), s = r.edgePoint(t.x, t.y);
				o.x !== s.x || o.y !== s.y ? e.env.lastCurve = new Q.Line(o, s, t, r, void 0) : e.env.lastCurve = Q.none;
			},
			getDefaultCurvature: function() {
				return 7 * A.measure.lineElementLength;
			},
			hasUpperTips: !0,
			hasLowerTips: !1
		}), $(F.Command.Twocell.LowerTwocell, {
			getUpperControlPoint: function(e, t, n, r, i, a) {
				return n;
			},
			getLowerControlPoint: function(e, t, n, r, i, a) {
				return new U.Point(n.x + r * i, n.y + r * a);
			},
			getUpperLabelPosition: function(e, t, n, r, i, a) {
				return n;
			},
			getLowerLabelPosition: function(e, t, n, r, i, a) {
				return new U.Point(n.x + .5 * r * i, n.y + .5 * r * a);
			},
			getUpperLabelAngle: function(e, t, n, r, i, a, o) {
				return e + (i < 0 ? 0 : Math.PI);
			},
			getLowerLabelAngle: function(e, t, n, r, i, a, o) {
				return e + (i < 0 ? Math.PI : 0);
			},
			getDefaultArrowPoint: function(e, t, n, r, i, a) {
				return new U.Point(n.x + .25 * r * i, n.y + .25 * r * a);
			},
			toUpperCurveShape: function(e, t, n, r, i, a) {
				var o = t.edgePoint(r.x, r.y), s = r.edgePoint(t.x, t.y);
				o.x !== s.x || o.y !== s.y ? e.env.lastCurve = new Q.Line(o, s, t, r, void 0) : e.env.lastCurve = Q.none;
			},
			toLowerCurveShape: function(e, t, n, r, i, a) {
				this._toCurveShape(e, t, n, r, i, a);
			},
			getDefaultCurvature: function() {
				return -7 * A.measure.lineElementLength;
			},
			hasUpperTips: !1,
			hasLowerTips: !0
		}), $(F.Command.Twocell.CompositeMap, {
			getUpperControlPoint: function(e, t, n, r, i, a) {
				var o = this.getMidBoxSize();
				return new U.Ellipse(n.x + r * i, n.y + r * a, o, o, o, o);
			},
			getLowerControlPoint: function(e, t, n, r, i, a) {
				var o = this.getMidBoxSize();
				return new U.Ellipse(n.x + r * i, n.y + r * a, o, o, o, o);
			},
			getUpperLabelPosition: function(e, t, n, r, i, a) {
				var o = n.x + r * i - t.x, s = n.y + r * a - t.y;
				return Math.sqrt(o * o + s * s), new U.Point(t.x + .5 * o, t.y + .5 * s);
			},
			getLowerLabelPosition: function(e, t, n, r, i, a) {
				var o = n.x + r * i - e.x, s = n.y + r * a - e.y;
				return Math.sqrt(o * o + s * s), new U.Point(e.x + .5 * o, e.y + .5 * s);
			},
			getUpperLabelAngle: function(e, t, n, r, i, a, o) {
				var s = n.x - r.x + i * a, c = n.y - r.y + i * o, l = Math.atan2(c, s), u = i < 0 ? Math.PI : 0;
				return l + Math.PI / 2 + u;
			},
			getLowerLabelAngle: function(e, t, n, r, i, a, o) {
				var s = r.x + i * a - t.x, c = r.y + i * o - t.y, l = Math.atan2(c, s), u = i < 0 ? Math.PI : 0;
				return l + Math.PI / 2 + u;
			},
			getDefaultArrowPoint: function(e, t, n, r, i, a) {
				return n;
			},
			toUpperCurveShape: function(e, t, n, r, i, a) {
				var o = e.env, s = t, c = n, l = s.edgePoint(c.x, c.y), u = c.edgePoint(s.x, s.y), d = o.p, f = o.c;
				o.p = s, o.c = c, new X.Line(l, u).toShape(e, void 0, `-`, ``), o.p = d, o.c = f;
			},
			toLowerCurveShape: function(e, t, n, r, i, a) {
				var o = e.env, s = n, c = r, l = s.edgePoint(c.x, c.y), u = c.edgePoint(s.x, s.y), d = o.p, f = o.c;
				o.p = s, o.c = c, new X.Line(l, u).toShape(e, void 0, `-`, ``), o.p = d, o.c = f;
			},
			getMidBoxSize: function() {
				return .5 * A.measure.lineElementLength;
			},
			getDefaultCurvature: function() {
				return 3.5 * A.measure.lineElementLength;
			},
			hasUpperTips: !0,
			hasLowerTips: !0
		}), $(F.Command.Twocell.Switch.UpperLabel, {
			setup: function(e) {
				e.env.twocellUpperLabel = new y.Some(this);
			},
			toShape: function(e, t, n, r, i) {
				this.label.toShape(e, t, n, r, i);
			}
		}), $(F.Command.Twocell.Switch.LowerLabel, {
			setup: function(e) {
				e.env.twocellLowerLabel = new y.Some(this);
			},
			toShape: function(e, t, n, r, i) {
				this.label.toShape(e, t, n, r, i);
			}
		}), $(F.Command.Twocell.Switch.SetCurvature, { setup: function(e) {
			var t = e.env;
			this.nudge.isOmit ? t.twocellShouldDrawCurve = !1 : t.twocellCurvatureEm = new y.Some(this.nudge.number * A.measure.lineElementLength);
		} }), $(F.Command.Twocell.Switch.DoNotSetCurvedArrows, { setup: function(e) {
			e.env.twocellShouldDrawCurve = !1;
		} }), $(F.Command.Twocell.Switch.PlaceModMapObject, { setup: function(e) {
			e.env.twocellShouldDrawModMap = !0;
		} }), $(F.Command.Twocell.Switch.ChangeHeadTailObject, { setup: function(e) {
			var t = e.env;
			switch (this.what) {
				case "`":
					t.twocelltail = this.object;
					break;
				case `'`: t.twocellhead = this.object;
			}
		} }), $(F.Command.Twocell.Switch.ChangeCurveObject, { setup: function(e) {
			var t = e.env;
			switch (this.what) {
				case ``:
					t.twocellUpperCurveObjectSpacer = this.spacer, t.twocellUpperCurveObject = this.maybeObject, t.twocellLowerCurveObjectSpacer = this.spacer, t.twocellLowerCurveObject = this.maybeObject;
					break;
				case `^`:
					t.twocellUpperCurveObjectSpacer = this.spacer, t.twocellUpperCurveObject = this.maybeObject;
					break;
				case `_`: t.twocellLowerCurveObjectSpacer = this.spacer, t.twocellLowerCurveObject = this.maybeObject;
			}
		} }), $(F.Command.Twocell.Label, {
			toShape: function(e, t, n, r, i) {
				var a, o = this.maybeNudge;
				if (o.isDefined) {
					var s = o.get;
					if (s.isOmit) return;
					a = s.number * A.measure.lineElementLength;
				} else a = this.getDefaultLabelOffset();
				var c = e.env, l = c.c;
				c.c = new U.Point(t.x + a * n, t.y + a * r), this.labelObject.toDropShape(e), c.c = l;
			},
			getDefaultLabelOffset: function() {
				return A.measure.lineElementLength;
			}
		}), $(F.Command.Twocell.Nudge.Number, { isOmit: !1 }), $(F.Command.Twocell.Nudge.Omit, { isOmit: !0 }), $(F.Command.Twocell.Arrow, { toTipsShape: function(e, t, n) {
			var r = e.env, i = r.lastCurve, a = r.c, o = r.angle, s = t ? Math.PI : 0, c = i.tOfPlace(!0, !0, t ? 0 : 1, 0);
			r.c = i.position(c), r.angle = i.angle(c) + s, r.twocellhead.toDropShape(e), c = i.tOfPlace(!0, !0, t ? 1 : 0, 0), r.c = i.position(c), r.angle = i.angle(c) + s, n ? r.twocellhead.toDropShape(e) : r.twocelltail.toDropShape(e), r.twocellShouldDrawModMap && (c = i.tOfPlace(!1, !1, .5, 0), r.c = i.position(c), r.angle = i.angle(c) + s, r.twocellmodmapobject.toDropShape(e)), r.c = a, r.angle = o;
		} }), $(F.Command.Twocell.Arrow.WithOrientation, {
			toUpperTipsShape: function(e) {
				switch (this.tok) {
					case ``:
					case `^`:
					case `_`:
					case `=`:
					case `\\omit`:
					case `'`:
						this.toTipsShape(e, !1, !1);
						break;
					case "`":
						this.toTipsShape(e, !0, !1);
						break;
					case `"`: this.toTipsShape(e, !1, !0);
				}
			},
			toLowerTipsShape: function(e) {
				switch (this.tok) {
					case ``:
					case `^`:
					case `_`:
					case `=`:
					case `\\omit`:
					case "`":
						this.toTipsShape(e, !1, !1);
						break;
					case `'`:
						this.toTipsShape(e, !0, !1);
						break;
					case `"`: this.toTipsShape(e, !1, !0);
				}
			},
			toArrowShape: function(e, t) {
				var n = e.env, r = n.c;
				switch (this.tok) {
					case `^`:
						var i = n.angle;
						n.angle = i + Math.PI, n.twocellarrowobject.toDropShape(e), n.c = new U.Point(r.x + A.measure.lineElementLength * Math.cos(i - Math.PI / 2), r.y + A.measure.lineElementLength * Math.sin(i - Math.PI / 2)), this.labelObject.toDropShape(e), n.angle = i;
						break;
					case ``:
					case `_`:
						i = n.angle, n.twocellarrowobject.toDropShape(e), n.c = new U.Point(r.x + A.measure.lineElementLength * Math.cos(i + Math.PI / 2), r.y + A.measure.lineElementLength * Math.sin(i + Math.PI / 2)), this.labelObject.toDropShape(e);
						break;
					case `=`:
						i = n.angle;
						var a = new Y.TwocellEqualityArrowheadShape(n.c, n.angle);
						e.appendShapeToFront(a), n.c = new U.Point(r.x + A.measure.lineElementLength * Math.cos(i + Math.PI / 2), r.y + A.measure.lineElementLength * Math.sin(i + Math.PI / 2)), this.labelObject.toDropShape(e);
						break;
					default: this.labelObject.toDropShape(e);
				}
				n.c = r;
			}
		}), $(F.Command.Twocell.Arrow.WithPosition, {
			toUpperTipsShape: function(e) {
				this.toTipsShape(e, !1, !1);
			},
			toLowerTipsShape: function(e) {
				this.toTipsShape(e, !1, !1);
			},
			toArrowShape: function(e, t) {
				var n, r = e.env, i = r.c, a = r.angle, o = this.nudge;
				if (o.isOmit) n = i;
				else {
					var s = o.number * A.measure.lineElementLength;
					n = new U.Point(t.x + s * Math.cos(a), t.y + s * Math.sin(a));
				}
				r.c = n, r.twocellarrowobject.toDropShape(e), o.isOmit || (r.c = new U.Point(n.x + A.measure.lineElementLength * Math.cos(a + Math.PI / 2), n.y + A.measure.lineElementLength * Math.sin(a + Math.PI / 2)), this.labelObject.toDropShape(e)), r.c = i;
			}
		}), $(F.Pos.Xyimport.TeXCommand, { toShape: function(e) {
			var t = e.env;
			if (t.c === void 0) return Y.none;
			var n = t.duplicate(), r = new St(Y.none, n), i = this.graphics.toDropShape(r), a = this.width, o = this.height;
			if (a === 0 || o === 0) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\xyimport should be non-zero.`);
			var s = n.c, l = s.l + s.r, u = s.u + s.d;
			if (l === 0 || u === 0) throw c(`ExecutionError`, `the width and height of the graphics to import should be non-zero.`);
			var d = this.xOffset, f = this.yOffset;
			t.c = s.toRect({
				u: u / o * (o - f),
				d: u / o * f,
				l: l / a * d,
				r: l / a * (a - d)
			}), t.setXBase(l / a, 0), t.setYBase(0, u / o);
			var p = s.l - t.c.l, m = s.d - t.c.d;
			i = new Y.TranslateShape(p, m, r.shape), e.appendShapeToFront(i);
		} }), $(F.Pos.Xyimport.Graphics, { toShape: function(e) {
			var t = e.env;
			if (t.c === void 0) return Y.none;
			var n = t.duplicate(), r = new St(Y.none, n), i = this.width, a = this.height;
			if (i === 0 || a === 0) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\xyimport should be non-zero.`);
			var o = this.graphics;
			if (o.setup(r), !n.includegraphicsWidth.isDefined || !n.includegraphicsHeight.isDefined) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\includegraphics are required.`);
			var s = n.includegraphicsWidth.get, l = n.includegraphicsHeight.get;
			if (s === 0 || l === 0) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\includegraphics should be non-zero.`);
			var u = this.xOffset, d = this.yOffset;
			t.c = n.c.toRect({
				u: l / a * (a - d),
				d: l / a * d,
				l: s / i * u,
				r: s / i * (i - u)
			}), t.setXBase(s / i, 0), t.setYBase(0, l / a);
			var f = new Y.ImageShape(t.c, o.filepath);
			e.appendShapeToFront(f);
		} }), $(F.Command.Includegraphics, { setup: function(e) {
			var t = e.env;
			t.includegraphicsWidth = y.empty, t.includegraphicsHeight = y.empty, this.attributeList.foreach((function(t) {
				t.setup(e);
			}));
		} }), $(F.Command.Includegraphics.Attr.Width, { setup: function(e) {
			e.env.includegraphicsWidth = new y.Some(A.measure.length2em(this.dimen));
		} }), $(F.Command.Includegraphics.Attr.Height, { setup: function(e) {
			e.env.includegraphicsHeight = new y.Some(A.measure.length2em(this.dimen));
		} });
		var Ht = {};
		Ht.Macro = i.Z.Macro, Ht.xybox = function(e, t, n) {
			var r = Vt(e, et.xybox(), F.xypic.prototype.kind);
			e.Push(r);
		}, Ht.xymatrixbox = function(e, t, n) {
			var r = Vt(e, et.xymatrixbox(), F.xypic.prototype.kind);
			e.Push(r);
		}, Ht.newdir = function(e, t, n) {
			var r = Vt(e, et.newdir(), F.xypic.newdir.prototype.kind);
			e.Push(r);
		}, Ht.xyincludegraphics = function(e, t, n) {
			var r = Vt(e, et.includegraphics(), F.xypic.includegraphics.prototype.kind);
			e.Push(r);
		}, Ht.xyEnvironment = function(e, t) {
			var n = Vt(e, et.xy(), F.xypic.prototype.kind);
			return e.Push(t), n;
		}, new r.QQ(`xypic-command`, {
			hole: [`Macro`, `{\\style{visibility:hidden}{x}}`],
			objectstyle: [`Macro`, `\\textstyle`],
			labelstyle: [`Macro`, `\\scriptstyle`],
			twocellstyle: [`Macro`, `\\scriptstyle`],
			xybox: [`xybox`, `xybox`],
			xymatrix: [`xymatrixbox`, `xymatrix`],
			newdir: [`newdir`, `newdir`],
			includegraphics: [`xyincludegraphics`, `includegraphics`]
		}, Ht), new r.QM(`xypic-environment`, a.Z.environment, { xy: [
			`xyEnvironment`,
			null,
			!1
		] }, Ht), t.VK.create(`xypic`, {
			handler: {
				macro: [`xypic-command`],
				environment: [`xypic-environment`]
			},
			preprocessors: [function(e) {
				e.math, e.document, e.data, A.xypicCommandIdCounter = 0, A.xypicCommandMap = {}, A.textObjectIdCounter = 0, A.wrapperOfTextObjectMap = {};
			}],
			nodes: {
				xypic: function(e, t, n) {
					var r = e.mmlFactory;
					return new F.xypic(r, t, n);
				},
				"xypic-newdir": function(e, t, n) {
					var r = e.mmlFactory;
					return new F.xypic.newdir(r, t, n);
				},
				"xypic-includegraphics": function(e, t, n) {
					var r = e.mmlFactory;
					return new F.xypic.includegraphics(r, t, n);
				}
			}
		}), Ie.embeddedModifierMap = {
			o: new F.Modifier.Shape.Circle(),
			l: new F.Modifier.Shape.L(),
			r: new F.Modifier.Shape.R(),
			u: new F.Modifier.Shape.U(),
			d: new F.Modifier.Shape.D(),
			c: new F.Modifier.Shape.C(),
			aliceblue: new F.Modifier.Shape.ChangeColor(`aliceblue`),
			antiquewhite: new F.Modifier.Shape.ChangeColor(`antiquewhite`),
			aqua: new F.Modifier.Shape.ChangeColor(`aqua`),
			aquamarine: new F.Modifier.Shape.ChangeColor(`aquamarine`),
			azure: new F.Modifier.Shape.ChangeColor(`azure`),
			beige: new F.Modifier.Shape.ChangeColor(`beige`),
			bisque: new F.Modifier.Shape.ChangeColor(`bisque`),
			black: new F.Modifier.Shape.ChangeColor(`black`),
			blanchedalmond: new F.Modifier.Shape.ChangeColor(`blanchedalmond`),
			blue: new F.Modifier.Shape.ChangeColor(`blue`),
			blueviolet: new F.Modifier.Shape.ChangeColor(`blueviolet`),
			brown: new F.Modifier.Shape.ChangeColor(`brown`),
			burlywood: new F.Modifier.Shape.ChangeColor(`burlywood`),
			cadetblue: new F.Modifier.Shape.ChangeColor(`cadetblue`),
			chartreuse: new F.Modifier.Shape.ChangeColor(`chartreuse`),
			chocolate: new F.Modifier.Shape.ChangeColor(`chocolate`),
			coral: new F.Modifier.Shape.ChangeColor(`coral`),
			cornflowerblue: new F.Modifier.Shape.ChangeColor(`cornflowerblue`),
			cornsilk: new F.Modifier.Shape.ChangeColor(`cornsilk`),
			crimson: new F.Modifier.Shape.ChangeColor(`crimson`),
			cyan: new F.Modifier.Shape.ChangeColor(`cyan`),
			darkblue: new F.Modifier.Shape.ChangeColor(`darkblue`),
			darkcyan: new F.Modifier.Shape.ChangeColor(`darkcyan`),
			darkgoldenrod: new F.Modifier.Shape.ChangeColor(`darkgoldenrod`),
			darkgray: new F.Modifier.Shape.ChangeColor(`darkgray`),
			darkgreen: new F.Modifier.Shape.ChangeColor(`darkgreen`),
			darkgrey: new F.Modifier.Shape.ChangeColor(`darkgrey`),
			darkkhaki: new F.Modifier.Shape.ChangeColor(`darkkhaki`),
			darkmagenta: new F.Modifier.Shape.ChangeColor(`darkmagenta`),
			darkolivegreen: new F.Modifier.Shape.ChangeColor(`darkolivegreen`),
			darkorange: new F.Modifier.Shape.ChangeColor(`darkorange`),
			darkorchid: new F.Modifier.Shape.ChangeColor(`darkorchid`),
			darkred: new F.Modifier.Shape.ChangeColor(`darkred`),
			darksalmon: new F.Modifier.Shape.ChangeColor(`darksalmon`),
			darkseagreen: new F.Modifier.Shape.ChangeColor(`darkseagreen`),
			darkslateblue: new F.Modifier.Shape.ChangeColor(`darkslateblue`),
			darkslategray: new F.Modifier.Shape.ChangeColor(`darkslategray`),
			darkslategrey: new F.Modifier.Shape.ChangeColor(`darkslategrey`),
			darkturquoise: new F.Modifier.Shape.ChangeColor(`darkturquoise`),
			darkviolet: new F.Modifier.Shape.ChangeColor(`darkviolet`),
			deeppink: new F.Modifier.Shape.ChangeColor(`deeppink`),
			deepskyblue: new F.Modifier.Shape.ChangeColor(`deepskyblue`),
			dimgray: new F.Modifier.Shape.ChangeColor(`dimgray`),
			dimgrey: new F.Modifier.Shape.ChangeColor(`dimgrey`),
			dodgerblue: new F.Modifier.Shape.ChangeColor(`dodgerblue`),
			firebrick: new F.Modifier.Shape.ChangeColor(`firebrick`),
			floralwhite: new F.Modifier.Shape.ChangeColor(`floralwhite`),
			forestgreen: new F.Modifier.Shape.ChangeColor(`forestgreen`),
			fuchsia: new F.Modifier.Shape.ChangeColor(`fuchsia`),
			gainsboro: new F.Modifier.Shape.ChangeColor(`gainsboro`),
			ghostwhite: new F.Modifier.Shape.ChangeColor(`ghostwhite`),
			gold: new F.Modifier.Shape.ChangeColor(`gold`),
			goldenrod: new F.Modifier.Shape.ChangeColor(`goldenrod`),
			gray: new F.Modifier.Shape.ChangeColor(`gray`),
			grey: new F.Modifier.Shape.ChangeColor(`grey`),
			green: new F.Modifier.Shape.ChangeColor(`green`),
			greenyellow: new F.Modifier.Shape.ChangeColor(`greenyellow`),
			honeydew: new F.Modifier.Shape.ChangeColor(`honeydew`),
			hotpink: new F.Modifier.Shape.ChangeColor(`hotpink`),
			indianred: new F.Modifier.Shape.ChangeColor(`indianred`),
			indigo: new F.Modifier.Shape.ChangeColor(`indigo`),
			ivory: new F.Modifier.Shape.ChangeColor(`ivory`),
			khaki: new F.Modifier.Shape.ChangeColor(`khaki`),
			lavender: new F.Modifier.Shape.ChangeColor(`lavender`),
			lavenderblush: new F.Modifier.Shape.ChangeColor(`lavenderblush`),
			lawngreen: new F.Modifier.Shape.ChangeColor(`lawngreen`),
			lemonchiffon: new F.Modifier.Shape.ChangeColor(`lemonchiffon`),
			lightblue: new F.Modifier.Shape.ChangeColor(`lightblue`),
			lightcoral: new F.Modifier.Shape.ChangeColor(`lightcoral`),
			lightcyan: new F.Modifier.Shape.ChangeColor(`lightcyan`),
			lightgoldenrodyellow: new F.Modifier.Shape.ChangeColor(`lightgoldenrodyellow`),
			lightgray: new F.Modifier.Shape.ChangeColor(`lightgray`),
			lightgreen: new F.Modifier.Shape.ChangeColor(`lightgreen`),
			lightgrey: new F.Modifier.Shape.ChangeColor(`lightgrey`),
			lightpink: new F.Modifier.Shape.ChangeColor(`lightpink`),
			lightsalmon: new F.Modifier.Shape.ChangeColor(`lightsalmon`),
			lightseagreen: new F.Modifier.Shape.ChangeColor(`lightseagreen`),
			lightskyblue: new F.Modifier.Shape.ChangeColor(`lightskyblue`),
			lightslategray: new F.Modifier.Shape.ChangeColor(`lightslategray`),
			lightslategrey: new F.Modifier.Shape.ChangeColor(`lightslategrey`),
			lightsteelblue: new F.Modifier.Shape.ChangeColor(`lightsteelblue`),
			lightyellow: new F.Modifier.Shape.ChangeColor(`lightyellow`),
			lime: new F.Modifier.Shape.ChangeColor(`lime`),
			limegreen: new F.Modifier.Shape.ChangeColor(`limegreen`),
			linen: new F.Modifier.Shape.ChangeColor(`linen`),
			magenta: new F.Modifier.Shape.ChangeColor(`magenta`),
			maroon: new F.Modifier.Shape.ChangeColor(`maroon`),
			mediumaquamarine: new F.Modifier.Shape.ChangeColor(`mediumaquamarine`),
			mediumblue: new F.Modifier.Shape.ChangeColor(`mediumblue`),
			mediumorchid: new F.Modifier.Shape.ChangeColor(`mediumorchid`),
			mediumpurple: new F.Modifier.Shape.ChangeColor(`mediumpurple`),
			mediumseagreen: new F.Modifier.Shape.ChangeColor(`mediumseagreen`),
			mediumslateblue: new F.Modifier.Shape.ChangeColor(`mediumslateblue`),
			mediumspringgreen: new F.Modifier.Shape.ChangeColor(`mediumspringgreen`),
			mediumturquoise: new F.Modifier.Shape.ChangeColor(`mediumturquoise`),
			mediumvioletred: new F.Modifier.Shape.ChangeColor(`mediumvioletred`),
			midnightblue: new F.Modifier.Shape.ChangeColor(`midnightblue`),
			mintcream: new F.Modifier.Shape.ChangeColor(`mintcream`),
			mistyrose: new F.Modifier.Shape.ChangeColor(`mistyrose`),
			moccasin: new F.Modifier.Shape.ChangeColor(`moccasin`),
			navajowhite: new F.Modifier.Shape.ChangeColor(`navajowhite`),
			navy: new F.Modifier.Shape.ChangeColor(`navy`),
			oldlace: new F.Modifier.Shape.ChangeColor(`oldlace`),
			olive: new F.Modifier.Shape.ChangeColor(`olive`),
			olivedrab: new F.Modifier.Shape.ChangeColor(`olivedrab`),
			orange: new F.Modifier.Shape.ChangeColor(`orange`),
			orangered: new F.Modifier.Shape.ChangeColor(`orangered`),
			orchid: new F.Modifier.Shape.ChangeColor(`orchid`),
			palegoldenrod: new F.Modifier.Shape.ChangeColor(`palegoldenrod`),
			palegreen: new F.Modifier.Shape.ChangeColor(`palegreen`),
			paleturquoise: new F.Modifier.Shape.ChangeColor(`paleturquoise`),
			palevioletred: new F.Modifier.Shape.ChangeColor(`palevioletred`),
			papayawhip: new F.Modifier.Shape.ChangeColor(`papayawhip`),
			peachpuff: new F.Modifier.Shape.ChangeColor(`peachpuff`),
			peru: new F.Modifier.Shape.ChangeColor(`peru`),
			pink: new F.Modifier.Shape.ChangeColor(`pink`),
			plum: new F.Modifier.Shape.ChangeColor(`plum`),
			powderblue: new F.Modifier.Shape.ChangeColor(`powderblue`),
			purple: new F.Modifier.Shape.ChangeColor(`purple`),
			red: new F.Modifier.Shape.ChangeColor(`red`),
			rosybrown: new F.Modifier.Shape.ChangeColor(`rosybrown`),
			royalblue: new F.Modifier.Shape.ChangeColor(`royalblue`),
			saddlebrown: new F.Modifier.Shape.ChangeColor(`saddlebrown`),
			salmon: new F.Modifier.Shape.ChangeColor(`salmon`),
			sandybrown: new F.Modifier.Shape.ChangeColor(`sandybrown`),
			seagreen: new F.Modifier.Shape.ChangeColor(`seagreen`),
			seashell: new F.Modifier.Shape.ChangeColor(`seashell`),
			sienna: new F.Modifier.Shape.ChangeColor(`sienna`),
			silver: new F.Modifier.Shape.ChangeColor(`silver`),
			skyblue: new F.Modifier.Shape.ChangeColor(`skyblue`),
			slateblue: new F.Modifier.Shape.ChangeColor(`slateblue`),
			slategray: new F.Modifier.Shape.ChangeColor(`slategray`),
			slategrey: new F.Modifier.Shape.ChangeColor(`slategrey`),
			snow: new F.Modifier.Shape.ChangeColor(`snow`),
			springgreen: new F.Modifier.Shape.ChangeColor(`springgreen`),
			steelblue: new F.Modifier.Shape.ChangeColor(`steelblue`),
			tan: new F.Modifier.Shape.ChangeColor(`tan`),
			teal: new F.Modifier.Shape.ChangeColor(`teal`),
			thistle: new F.Modifier.Shape.ChangeColor(`thistle`),
			tomato: new F.Modifier.Shape.ChangeColor(`tomato`),
			turquoise: new F.Modifier.Shape.ChangeColor(`turquoise`),
			violet: new F.Modifier.Shape.ChangeColor(`violet`),
			wheat: new F.Modifier.Shape.ChangeColor(`wheat`),
			white: new F.Modifier.Shape.ChangeColor(`white`),
			whitesmoke: new F.Modifier.Shape.ChangeColor(`whitesmoke`),
			yellow: new F.Modifier.Shape.ChangeColor(`yellow`),
			yellowgreen: new F.Modifier.Shape.ChangeColor(`yellowgreen`)
		};
		var Ut = n(81), Wt = n(748), Gt = n(226);
		function Kt(e) {
			return Kt = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
				return typeof e;
			} : function(e) {
				return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e;
			}, Kt(e);
		}
		function qt(e, t) {
			if (typeof t != `function` && t !== null) throw TypeError(`Super expression must either be null or a function`);
			e.prototype = Object.create(t && t.prototype, { constructor: {
				value: e,
				writable: !0,
				configurable: !0
			} }), t && Jt(e, t);
		}
		function Jt(e, t) {
			return Jt = Object.setPrototypeOf || function(e, t) {
				return e.__proto__ = t, e;
			}, Jt(e, t);
		}
		function Yt(e) {
			var t = function() {
				if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return !1;
				if (typeof Proxy == `function`) return !0;
				try {
					return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {}))), !0;
				} catch {
					return !1;
				}
			}();
			return function() {
				var n, r = Qt(e);
				if (t) {
					var i = Qt(this).constructor;
					n = Reflect.construct(r, arguments, i);
				} else n = r.apply(this, arguments);
				return Xt(this, n);
			};
		}
		function Xt(e, t) {
			if (t && (Kt(t) === `object` || typeof t == `function`)) return t;
			if (t !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
			return Zt(e);
		}
		function Zt(e) {
			if (e === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
			return e;
		}
		function Qt(e) {
			return Qt = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
				return e.__proto__ || Object.getPrototypeOf(e);
			}, Qt(e);
		}
		function $t(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		function en(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function tn(e, t, n) {
			return t && en(e.prototype, t), n && en(e, n), e;
		}
		var nn = it, rn = function() {
			function e() {
				$t(this, e);
			}
			return tn(e, null, [{
				key: `createSVG`,
				value: function(e, t, n, r, i, a, o) {
					return new on(e, t, n, r, i, a, o);
				}
			}]), e;
		}(), an = function() {
			function e(t) {
				$t(this, e), this.xypicWrapper = t;
			}
			return tn(e, [
				{
					key: `createElement`,
					value: function(e) {
						return this.xypicWrapper.svg(e);
					}
				},
				{
					key: `createGroup`,
					value: function(e) {
						return new un(this, e);
					}
				},
				{
					key: `createChangeColorGroup`,
					value: function(e) {
						return new dn(this, e);
					}
				},
				{
					key: `createSVGElement`,
					value: function(e, t) {
						var n = this.createElement(e);
						if (t) {
							for (var r in t) if (t.hasOwnProperty(r)) {
								var i = t[r].toString();
								r === `xlink:href` ? this.xypicWrapper.setAttribute(n, r, i, `http://www.w3.org/1999/xlink`) : this.xypicWrapper.setAttribute(n, r, i);
							}
						}
						return this.appendChild(n), n;
					}
				},
				{
					key: `appendChild`,
					value: function(e) {
						return this.xypicWrapper.adaptor.append(this.drawArea, e), e;
					}
				},
				{
					key: `transformBuilder`,
					value: function() {
						return new sn();
					}
				}
			]), e;
		}(), on = function(e) {
			qt(n, e);
			var t = Yt(n);
			function n(e, r, i, a, o, s, c) {
				var l;
				$t(this, n);
				var u = (l = t.call(this, e)).createElement(`svg`);
				if (l.xypicWrapper.setAttribute(u, `xmlns`, `http://www.w3.org/2000/svg`), l.xypicWrapper.setAttribute(u, `version`, `1.1`), c) for (var d in c) c.hasOwnProperty(d) && l.xypicWrapper.setAttribute(u, d, c[d].toString());
				for (var f in u.style && (u.style.width = A.measure.Em(a), u.style.height = A.measure.Em(r + i)), c = {
					fill: `none`,
					stroke: s,
					"stroke-linecap": `round`,
					"stroke-width": A.measure.em2px(o)
				}, l.drawArea = l.createElement(`g`), c) c.hasOwnProperty(f) && l.xypicWrapper.setAttribute(l.drawArea, f, c[f].toString());
				return l.xypicWrapper.append(u, l.drawArea), l.svg = u, l.boundingBox = void 0, l.color = s, l;
			}
			return tn(n, [
				{
					key: `setHeight`,
					value: function(e) {
						this.xypicWrapper.setStyle(this.svg, `height`, A.measure.Em(e));
					}
				},
				{
					key: `setWidth`,
					value: function(e) {
						this.xypicWrapper.setStyle(this.svg, `width`, A.measure.Em(e));
					}
				},
				{
					key: `setAttribute`,
					value: function(e, t) {
						this.xypicWrapper.setAttribute(this.svg, e, t.toString());
					}
				},
				{
					key: `extendBoundingBox`,
					value: function(e) {
						this.boundingBox = U.combineRect(this.boundingBox, e);
					}
				},
				{
					key: `getOrigin`,
					value: function() {
						return {
							x: 0,
							y: 0
						};
					}
				},
				{
					key: `getCurrentColor`,
					value: function() {
						return this.color;
					}
				}
			]), n;
		}(an), sn = function() {
			function e(t) {
				$t(this, e), this.transform = t || O.empty;
			}
			return tn(e, [
				{
					key: `translate`,
					value: function(t, n) {
						return new e(this.transform.append(new cn(t, n)));
					}
				},
				{
					key: `rotateDegree`,
					value: function(t) {
						return new e(this.transform.append(new ln(t / 180 * Math.PI)));
					}
				},
				{
					key: `rotateRadian`,
					value: function(t) {
						return new e(this.transform.append(new ln(t)));
					}
				},
				{
					key: `toString`,
					value: function() {
						var e = ``;
						return this.transform.foreach((function(t) {
							e += t.toTranslateForm();
						})), e;
					}
				},
				{
					key: `apply`,
					value: function(e, t) {
						var n = {
							x: e,
							y: t
						};
						return this.transform.foreach((function(e) {
							n = e.apply(n.x, n.y);
						})), n;
					}
				}
			]), e;
		}(), cn = function() {
			function e(t, n) {
				$t(this, e), this.dx = t, this.dy = n;
			}
			return tn(e, [{
				key: `apply`,
				value: function(e, t) {
					return {
						x: e - this.dx,
						y: t + this.dy
					};
				}
			}, {
				key: `toTranslateForm`,
				value: function() {
					return `translate(` + A.measure.em2px(this.dx) + `,` + A.measure.em2px(-this.dy) + `) `;
				}
			}]), e;
		}(), ln = function() {
			function e(t) {
				$t(this, e), this.radian = t;
			}
			return tn(e, [{
				key: `apply`,
				value: function(e, t) {
					var n = Math.cos(this.radian), r = Math.sin(this.radian);
					return {
						x: n * e + r * t,
						y: -r * e + n * t
					};
				}
			}, {
				key: `toTranslateForm`,
				value: function() {
					return `rotate(` + nn(-180 * this.radian / Math.PI) + `) `;
				}
			}]), e;
		}(), un = function(e) {
			qt(n, e);
			var t = Yt(n);
			function n(e, r) {
				var i;
				$t(this, n), (i = t.call(this, e.xypicWrapper)).parent = e, i.drawArea = e.createSVGElement(`g`, r === void 0 ? {} : { transform: r.toString() });
				var a = e.getOrigin();
				return i.origin = r === void 0 ? a : r.apply(a.x, a.y), H(Zt(i), `getCurrentColor`), i;
			}
			return tn(n, [
				{
					key: `remove`,
					value: function() {
						this.xypicWrapper.remove(this.drawArea);
					}
				},
				{
					key: `extendBoundingBox`,
					value: function(e) {
						this.parent.extendBoundingBox(e);
					}
				},
				{
					key: `getOrigin`,
					value: function() {
						return this.origin;
					}
				},
				{
					key: `getCurrentColor`,
					value: function() {
						return this.parent.getCurrentColor();
					}
				}
			]), n;
		}(an), dn = function(e) {
			qt(n, e);
			var t = Yt(n);
			function n(e, r) {
				var i;
				return $t(this, n), (i = t.call(this, e.xypicWrapper)).parent = e, i.drawArea = e.createSVGElement(`g`, { stroke: r }), i.color = r, H(Zt(i), `getOrigin`), i;
			}
			return tn(n, [
				{
					key: `remove`,
					value: function() {
						this.xypicWrapper.remove(this.drawArea);
					}
				},
				{
					key: `extendBoundingBox`,
					value: function(e) {
						this.parent.extendBoundingBox(e);
					}
				},
				{
					key: `getOrigin`,
					value: function() {
						return this.parent.getOrigin();
					}
				},
				{
					key: `getCurrentColor`,
					value: function() {
						return this.color;
					}
				}
			]), n;
		}(an);
		function fn(e) {
			return fn = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
				return typeof e;
			} : function(e) {
				return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e;
			}, fn(e);
		}
		function pn(e, t) {
			var n = typeof Symbol < `u` && e[Symbol.iterator] || e[`@@iterator`];
			if (!n) {
				if (Array.isArray(e) || (n = function(e, t) {
					if (e) {
						if (typeof e == `string`) return mn(e, t);
						var n = Object.prototype.toString.call(e).slice(8, -1);
						if (n === `Object` && e.constructor && (n = e.constructor.name), n === `Map` || n === `Set`) return Array.from(e);
						if (n === `Arguments` || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(n)) return mn(e, t);
					}
				}(e)) || t && e && typeof e.length == `number`) {
					n && (e = n);
					var r = 0, i = function() {};
					return {
						s: i,
						n: function() {
							return r >= e.length ? { done: !0 } : {
								done: !1,
								value: e[r++]
							};
						},
						e: function(e) {
							throw e;
						},
						f: i
					};
				}
				throw TypeError(`Invalid attempt to iterate non-iterable instance.
In order to be iterable, non-array objects must have a [Symbol.iterator]() method.`);
			}
			var a, o = !0, s = !1;
			return {
				s: function() {
					n = n.call(e);
				},
				n: function() {
					var e = n.next();
					return o = e.done, e;
				},
				e: function(e) {
					s = !0, a = e;
				},
				f: function() {
					try {
						o || n.return == null || n.return();
					} finally {
						if (s) throw a;
					}
				}
			};
		}
		function mn(e, t) {
			(t == null || t > e.length) && (t = e.length);
			for (var n = 0, r = Array(t); n < t; n++) r[n] = e[n];
			return r;
		}
		function hn(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		function gn(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function _n(e, t, n) {
			return t && gn(e.prototype, t), n && gn(e, n), e;
		}
		function vn(e, t) {
			if (typeof t != `function` && t !== null) throw TypeError(`Super expression must either be null or a function`);
			e.prototype = Object.create(t && t.prototype, { constructor: {
				value: e,
				writable: !0,
				configurable: !0
			} }), t && yn(e, t);
		}
		function yn(e, t) {
			return yn = Object.setPrototypeOf || function(e, t) {
				return e.__proto__ = t, e;
			}, yn(e, t);
		}
		function bn(e) {
			var t = function() {
				if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return !1;
				if (typeof Proxy == `function`) return !0;
				try {
					return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {}))), !0;
				} catch {
					return !1;
				}
			}();
			return function() {
				var n, r = Sn(e);
				if (t) {
					var i = Sn(this).constructor;
					n = Reflect.construct(r, arguments, i);
				} else n = r.apply(this, arguments);
				return xn(this, n);
			};
		}
		function xn(e, t) {
			if (t && (fn(t) === `object` || typeof t == `function`)) return t;
			if (t !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
			return function(e) {
				if (e === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
				return e;
			}(e);
		}
		function Sn(e) {
			return Sn = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
				return e.__proto__ || Object.getPrototypeOf(e);
			}, Sn(e);
		}
		var Cn = `http://www.w3.org/2000/svg`, wn = it;
		function Tn(e, t) {
			var n = function(e) {
				vn(n, e);
				var t = bn(n);
				function n(e, r) {
					var i, a = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
					hn(this, n), i = t.call(this, e, r, a);
					for (var o = A.wrapperOfTextObjectMap, s = r.textMmls, c = i.childNodes, l = s.length, u = 0; u < l; u++) {
						var d = s[u].xypicTextObjectId;
						o[d] = c[u];
					}
					return i._textObjects = [], i;
				}
				return _n(n, [
					{
						key: `getElement`,
						value: function() {
							return this.chtml;
						}
					},
					{
						key: `appendTextObject`,
						value: function(e) {
							this._textObjects.push(e);
						}
					},
					{
						key: `getChildWrapper`,
						value: function(e) {
							var t = e.xypicTextObjectId;
							if (t == null) throw c(`IllegalStateError`, `BUG`);
							var n = A.wrapperOfTextObjectMap[t];
							if (n == null) throw c(`IllegalStateError`, `unknown textObjectId:` + t);
							return n;
						}
					},
					{
						key: `toCHTML`,
						value: function(e) {
							var t = A.svgForDebug, n = A.svgForTestLayout;
							this._textObjects = [], this.setupMeasure(this), this._toCHTML(e), A.svgForDebug = t, A.svgForTestLayout = n;
						}
					},
					{
						key: `setupMeasure`,
						value: function(e) {
							var t = it, n = e.length2em(`1em`), r = parseFloat(e.px(100).replace(`px`, ``)) / 100, i = e.font.params.axis_height, a = e.length2em(`0.15em`), o = function(t) {
								return Math.round(parseFloat(e.px(100 * t).replace(`px`, ``))) / 100;
							};
							A.measure = {
								length2em: function(n) {
									return t(e.length2em(n));
								},
								oneem: n,
								em2length: function(e) {
									return t(e / n) + `em`;
								},
								Em: function(t) {
									return e.em(t);
								},
								em: r,
								em2px: o,
								axis_height: i,
								strokeWidth: e.length2em(`0.04em`),
								thickness: a,
								jot: e.length2em(`3pt`),
								objectmargin: e.length2em(`3pt`),
								objectwidth: e.length2em(`0pt`),
								objectheight: e.length2em(`0pt`),
								labelmargin: e.length2em(`2.5pt`),
								turnradius: e.length2em(`10pt`),
								lineElementLength: e.length2em(`5pt`),
								axisHeightLength: i * e.length2em(`10pt`),
								dottedDasharray: n + ` ` + o(a)
							};
						}
					},
					{
						key: `append`,
						value: function(e, t) {
							this.adaptor.append(e, t);
						}
					},
					{
						key: `remove`,
						value: function(e) {
							this.adaptor.remove(e);
						}
					},
					{
						key: `svg`,
						value: function(e) {
							var t = arguments.length > 1 && arguments[1] !== void 0 ? arguments[1] : {}, n = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : [];
							return this.adaptor.node(e, t, n, Cn);
						}
					},
					{
						key: `setAttribute`,
						value: function(e, t, n, r) {
							return this.adaptor.setAttribute(e, t, n, r);
						}
					},
					{
						key: `setStyle`,
						value: function(e, t, n) {
							this.adaptor.setStyle(e, t, n);
						}
					},
					{
						key: `drawTextObject`,
						value: function(e, t, n) {
							var r = A.measure.length2em(`0.2em`), i = t.xypicWrapper, a = i.getChildWrapper(e.math), o = a.adaptor, s = a.getBBox(), c = s.scale, l = (s.h + r) * c, u = (s.d + r) * c, d = (s.w + 2 * r) * c, f = (l + u) / 2, p = d / 2, m = e.c;
							if (e.originalBBox = {
								H: l,
								D: u,
								W: d
							}, !n) {
								var h = a.html(`mjx-xypic-object`);
								o.append(i.getElement(), h), o.setStyle(h, `color`, t.getCurrentColor()), a.toCHTML(h);
								var g = t.getOrigin();
								o.setAttribute(h, `data-x`, m.x - p - g.x + r * c), o.setAttribute(h, `data-y`, -m.y - f - g.y + r * c), o.setAttribute(h, `data-xypic-id`, e.math.xypicTextObjectId), i.appendTextObject(h);
							}
							return m.toRect({
								u: f,
								d: f,
								l: p,
								r: p
							});
						}
					}
				]), n;
			}(e), r = function(e) {
				vn(n, e);
				var t = bn(n);
				function n(e, r) {
					var i, a = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
					return hn(this, n), (i = t.call(this, e, r, a)).shape = null, i;
				}
				return _n(n, [
					{
						key: `computeBBox`,
						value: function(e) {
							e.empty();
							var t = this.node.cmd;
							if (t) {
								var n = this.length2em(`0.2em`);
								if (this.shape == null) {
									var r = A.svgForDebug, i = A.svgForTestLayout;
									this._textObjects = [], this.setupMeasure(this), this.adaptor;
									var a = A.measure.strokeWidth, o = 1, s = 0, c = 1, l = A.measure.em2px, d = rn.createSVG(this, o, s, c, a, `black`, {
										viewBox: [
											0,
											-l(o + s),
											l(c),
											l(o + s)
										].join(` `),
										role: `img`,
										focusable: !1,
										overflow: `visible`
									});
									A.svgForDebug = d, A.svgForTestLayout = d;
									var f = new Mt(), p = new St(Y.none, f);
									t.toShape(p), this.shape = p.shape, A.svgForDebug = r, A.svgForTestLayout = i;
								}
								var h = this.shape.getBoundingBox();
								h !== void 0 && (h = new U.Rect(0, 0, {
									l: Math.max(0, -(h.x - h.l)),
									r: Math.max(0, h.x + h.r),
									u: Math.max(0, h.y + h.u),
									d: Math.max(0, -(h.y - h.d))
								}), e.updateFrom(new Gt.bK({
									w: h.l + h.r + 2 * n,
									h: h.u + 2 * n,
									d: h.d
								})));
							}
						}
					},
					{
						key: `kind`,
						get: function() {
							return F.xypic.prototype.kind;
						}
					},
					{
						key: `_toCHTML`,
						value: function(e) {
							var t = this.standardCHTMLnode(e);
							this.cthml = t;
							var n = this.adaptor, r = this.length2em(`0.2em`), i = A.measure.strokeWidth, a = 1, o = 0, s = 1, c = A.measure.em2px, l = rn.createSVG(this, a, o, s, i, `black`, {
								viewBox: [
									0,
									-c(a + o),
									c(s),
									c(a + o)
								].join(` `),
								role: `img`,
								focusable: !1,
								overflow: `visible`
							});
							A.svgForDebug = l, A.svgForTestLayout = l, n.append(t, l.svg);
							var u = this.node.cmd;
							if (u) {
								if (this.shape == null) {
									var d = new Mt(), f = new St(Y.none, d);
									u.toShape(f), this.shape = f.shape;
								}
								var p = this.shape;
								p.draw(l);
								var m = p.getBoundingBox();
								if (m !== void 0) {
									var h = (m = new U.Rect(0, 0, {
										l: Math.max(0, -(m.x - m.l)),
										r: Math.max(0, m.x + m.r),
										u: Math.max(0, m.y + m.u),
										d: Math.max(0, -(m.y - m.d))
									})).x - m.l - r, g = -m.y - m.u - r, _ = m.l + m.r + 2 * r, v = m.u + m.d + 2 * r;
									l.setWidth(_), l.setHeight(v), l.setAttribute(`viewBox`, [
										c(h),
										c(g),
										c(_),
										c(v)
									].join(` `)), n.setStyle(t, `vertical-align`, wn(-m.d - r + A.measure.axis_height) + `em`);
									var y, b = pn(this._textObjects);
									try {
										for (b.s(); !(y = b.n()).done;) {
											var x = y.value, S = parseFloat(n.getAttribute(x, `data-x`)), C = parseFloat(n.getAttribute(x, `data-y`));
											n.setStyle(x, `left`, wn(S - h) + `em`), n.setStyle(x, `top`, wn(C + m.y - m.d - .5 * r) + `em`);
										}
									} catch (e) {
										b.e(e);
									} finally {
										b.f();
									}
								} else n.remove(l.svg);
							} else n.remove(l.svg);
						}
					}
				], [{
					key: `styles`,
					get: function() {
						return {
							"mjx-xypic path": { "stroke-width": `inherit` },
							".MathJax mjx-xypic path": { "stroke-width": `inherit` },
							"mjx-xypic-object": {
								"text-align": `center`,
								position: `absolute`
							},
							"mjx-xypic": { position: `relative` }
						};
					}
				}]), n;
			}(n);
			t[r.prototype.kind] = r;
			var i = function(e) {
				vn(n, e);
				var t = bn(n);
				function n(e, r) {
					var i = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
					return hn(this, n), t.call(this, e, r, i);
				}
				return _n(n, [{
					key: `kind`,
					get: function() {
						return F.xypic.newdir.prototype.kind;
					}
				}, {
					key: `_toCHTML`,
					value: function(e) {
						var t = this.node.cmd;
						A.repositories.dirRepository.put(t.dirMain, t.compositeObject);
					}
				}]), n;
			}(n);
			t[i.prototype.kind] = i;
			var a = function(e) {
				vn(n, e);
				var t = bn(n);
				function n(e, r) {
					var i, a = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
					return hn(this, n), (i = t.call(this, e, r, a))._setupGraphics(), i.computeBBox(i.bbox), i.bboxComputed = !0, i;
				}
				return _n(n, [
					{
						key: `kind`,
						get: function() {
							return F.xypic.includegraphics.prototype.kind;
						}
					},
					{
						key: `_setupGraphics`,
						value: function() {
							this.setupMeasure(this);
							var e = new Mt(), t = new St(Y.none, e), n = this.node.cmd;
							if (n.setup(t), !e.includegraphicsWidth.isDefined || !e.includegraphicsHeight.isDefined) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\includegraphics are required.`);
							var r = e.includegraphicsWidth.get, i = e.includegraphicsHeight.get;
							this.imageWidth = this.length2em(r), this.imageHeight = this.length2em(i), this.filepath = n.filepath;
						}
					},
					{
						key: `computeBBox`,
						value: function(e) {
							e.empty(), e.updateFrom(new Gt.bK({
								w: this.imageWidth,
								h: this.imageHeight,
								d: 0
							}));
						}
					},
					{
						key: `_toCHTML`,
						value: function(e) {
							var t = this.standardCHTMLnode(e);
							this.cthml = t, this.adaptor.setStyle(t, `position`, `relative`), this.adaptor.setStyle(t, `vertical-align`, `0em`);
							var n = this.html(`img`);
							this.adaptor.setAttribute(n, `src`, this.filepath), this.adaptor.setStyle(n, `width`, wn(this.imageWidth) + `em`), this.adaptor.setStyle(n, `height`, wn(this.imageHeight) + `em`), this.adaptor.append(t, n);
						}
					}
				]), n;
			}(n);
			t[a.prototype.kind] = a;
		}
		Ut.wO !== void 0 && Tn(Ut.wO, Wt.w);
		var En = n(952), Dn = n(84);
		function On(e) {
			return On = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
				return typeof e;
			} : function(e) {
				return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e;
			}, On(e);
		}
		function kn(e, t) {
			var n = typeof Symbol < `u` && e[Symbol.iterator] || e[`@@iterator`];
			if (!n) {
				if (Array.isArray(e) || (n = function(e, t) {
					if (e) {
						if (typeof e == `string`) return An(e, t);
						var n = Object.prototype.toString.call(e).slice(8, -1);
						if (n === `Object` && e.constructor && (n = e.constructor.name), n === `Map` || n === `Set`) return Array.from(e);
						if (n === `Arguments` || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(n)) return An(e, t);
					}
				}(e)) || t && e && typeof e.length == `number`) {
					n && (e = n);
					var r = 0, i = function() {};
					return {
						s: i,
						n: function() {
							return r >= e.length ? { done: !0 } : {
								done: !1,
								value: e[r++]
							};
						},
						e: function(e) {
							throw e;
						},
						f: i
					};
				}
				throw TypeError(`Invalid attempt to iterate non-iterable instance.
In order to be iterable, non-array objects must have a [Symbol.iterator]() method.`);
			}
			var a, o = !0, s = !1;
			return {
				s: function() {
					n = n.call(e);
				},
				n: function() {
					var e = n.next();
					return o = e.done, e;
				},
				e: function(e) {
					s = !0, a = e;
				},
				f: function() {
					try {
						o || n.return == null || n.return();
					} finally {
						if (s) throw a;
					}
				}
			};
		}
		function An(e, t) {
			(t == null || t > e.length) && (t = e.length);
			for (var n = 0, r = Array(t); n < t; n++) r[n] = e[n];
			return r;
		}
		function jn(e, t) {
			if (!(e instanceof t)) throw TypeError(`Cannot call a class as a function`);
		}
		function Mn(e, t) {
			for (var n = 0; n < t.length; n++) {
				var r = t[n];
				r.enumerable = r.enumerable || !1, r.configurable = !0, `value` in r && (r.writable = !0), Object.defineProperty(e, r.key, r);
			}
		}
		function Nn(e, t, n) {
			return t && Mn(e.prototype, t), n && Mn(e, n), e;
		}
		function Pn(e, t) {
			if (typeof t != `function` && t !== null) throw TypeError(`Super expression must either be null or a function`);
			e.prototype = Object.create(t && t.prototype, { constructor: {
				value: e,
				writable: !0,
				configurable: !0
			} }), t && Fn(e, t);
		}
		function Fn(e, t) {
			return Fn = Object.setPrototypeOf || function(e, t) {
				return e.__proto__ = t, e;
			}, Fn(e, t);
		}
		function In(e) {
			var t = function() {
				if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return !1;
				if (typeof Proxy == `function`) return !0;
				try {
					return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {}))), !0;
				} catch {
					return !1;
				}
			}();
			return function() {
				var n, r = Rn(e);
				if (t) {
					var i = Rn(this).constructor;
					n = Reflect.construct(r, arguments, i);
				} else n = r.apply(this, arguments);
				return Ln(this, n);
			};
		}
		function Ln(e, t) {
			if (t && (On(t) === `object` || typeof t == `function`)) return t;
			if (t !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
			return function(e) {
				if (e === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
				return e;
			}(e);
		}
		function Rn(e) {
			return Rn = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
				return e.__proto__ || Object.getPrototypeOf(e);
			}, Rn(e);
		}
		var zn = `http://www.w3.org/2000/svg`, Bn = it;
		function Vn(e, t) {
			var n = function(e) {
				Pn(n, e);
				var t = In(n);
				function n(e, r) {
					var i, a = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
					jn(this, n), i = t.call(this, e, r, a);
					for (var o = A.wrapperOfTextObjectMap, s = r.textMmls, c = i.childNodes, l = s.length, u = 0; u < l; u++) {
						var d = s[u].xypicTextObjectId;
						o[d] = c[u];
					}
					return i._textObjects = [], i;
				}
				return Nn(n, [
					{
						key: `getElement`,
						value: function() {
							return this.svgNode;
						}
					},
					{
						key: `appendTextObject`,
						value: function(e) {
							this._textObjects.push(e);
						}
					},
					{
						key: `getChildWrapper`,
						value: function(e) {
							var t = e.xypicTextObjectId;
							if (t == null) throw c(`IllegalStateError`, `BUG`);
							var n = A.wrapperOfTextObjectMap[t];
							if (n == null) throw c(`IllegalStateError`, `unknown textObjectId:` + t);
							return n;
						}
					},
					{
						key: `toSVG`,
						value: function(e) {
							var t = A.svgForDebug, n = A.svgForTestLayout;
							this._textObjects = [], this.setupMeasure(this), this._toSVG(e), A.svgForDebug = t, A.svgForTestLayout = n;
						}
					},
					{
						key: `setupMeasure`,
						value: function(e) {
							var t = it, n = e.length2em(`1em`), r = parseFloat(e.px(100).replace(`px`, ``)) / 100, i = e.font.params.axis_height, a = e.length2em(`0.15em`), o = function(t) {
								return Math.round(parseFloat(e.px(100 * t).replace(`px`, ``))) / 100;
							};
							A.measure = {
								length2em: function(n) {
									return t(e.length2em(n));
								},
								oneem: n,
								em2length: function(e) {
									return t(e / n) + `em`;
								},
								Em: function(t) {
									return e.em(t);
								},
								em: r,
								em2px: o,
								axis_height: i,
								strokeWidth: e.length2em(`0.04em`),
								thickness: a,
								jot: e.length2em(`3pt`),
								objectmargin: e.length2em(`3pt`),
								objectwidth: e.length2em(`0pt`),
								objectheight: e.length2em(`0pt`),
								labelmargin: e.length2em(`2.5pt`),
								turnradius: e.length2em(`10pt`),
								lineElementLength: e.length2em(`5pt`),
								axisHeightLength: i * e.length2em(`10pt`),
								dottedDasharray: n + ` ` + o(a)
							};
						}
					},
					{
						key: `append`,
						value: function(e, t) {
							this.adaptor.append(e, t);
						}
					},
					{
						key: `remove`,
						value: function(e) {
							this.adaptor.remove(e);
						}
					},
					{
						key: `svg`,
						value: function(e) {
							var t = arguments.length > 1 && arguments[1] !== void 0 ? arguments[1] : {}, n = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : [];
							return this.adaptor.node(e, t, n, zn);
						}
					},
					{
						key: `setAttribute`,
						value: function(e, t, n, r) {
							return this.adaptor.setAttribute(e, t, n, r);
						}
					},
					{
						key: `setStyle`,
						value: function(e, t, n) {
							this.adaptor.setStyle(e, t, n);
						}
					},
					{
						key: `drawTextObject`,
						value: function(e, t, n) {
							var r = A.measure.length2em(`0.2em`), i = t.xypicWrapper, a = i.getChildWrapper(e.math), o = a.adaptor, s = a.getBBox(), c = s.scale, l = (s.h + r) * c, u = (s.d + r) * c, d = (s.w + 2 * r) * c, f = (l + u) / 2, p = d / 2, m = e.c;
							if (e.originalBBox = {
								H: l,
								D: u,
								W: d
							}, !n) {
								var h = a.svg(`g`);
								o.append(i.getElement(), h), o.setAttribute(h, `stroke`, t.getCurrentColor()), o.setAttribute(h, `fill`, t.getCurrentColor()), a.toSVG(h);
								var g = t.getOrigin();
								o.setAttribute(h, `data-x`, m.x - p - g.x + r * c), o.setAttribute(h, `data-y`, -m.y + (l - u) / 2 - g.y), o.setAttribute(h, `data-xypic-id`, e.math.xypicTextObjectId), i.appendTextObject(h);
							}
							return m.toRect({
								u: f,
								d: f,
								l: p,
								r: p
							});
						}
					}
				]), n;
			}(e), r = function(e) {
				Pn(n, e);
				var t = In(n);
				function n(e, r) {
					var i, a = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
					return jn(this, n), (i = t.call(this, e, r, a)).shape = null, i;
				}
				return Nn(n, [
					{
						key: `computeBBox`,
						value: function(e) {
							e.empty();
							var t = this.node.cmd;
							if (t) {
								var n = this.length2em(`0.2em`);
								if (this.shape == null) {
									var r = A.svgForDebug, i = A.svgForTestLayout;
									this._textObjects = [], this.setupMeasure(this), this.adaptor;
									var a = A.measure.strokeWidth, o = 1, s = 0, c = 1, l = A.measure.em2px, d = rn.createSVG(this, o, s, c, a, `black`, {
										viewBox: [
											0,
											-l(o + s),
											l(c),
											l(o + s)
										].join(` `),
										role: `img`,
										focusable: !1,
										overflow: `visible`
									});
									A.svgForDebug = d, A.svgForTestLayout = d;
									var f = new Mt(), p = new St(Y.none, f);
									t.toShape(p), this.shape = p.shape, A.svgForDebug = r, A.svgForTestLayout = i;
								}
								var h = this.shape.getBoundingBox();
								h !== void 0 && (h = new U.Rect(0, 0, {
									l: Math.max(0, -(h.x - h.l)),
									r: Math.max(0, h.x + h.r),
									u: Math.max(0, h.y + h.u),
									d: Math.max(0, -(h.y - h.d))
								}), e.updateFrom(new Gt.bK({
									w: h.l + h.r + 2 * n,
									h: h.u + 2 * n,
									d: h.d
								})));
							}
						}
					},
					{
						key: `kind`,
						get: function() {
							return F.xypic.prototype.kind;
						}
					},
					{
						key: `_toSVG`,
						value: function(e) {
							var t = this.standardSVGnode(e);
							this.svgNode = t;
							var n = this.adaptor, r = this.length2em(`0.2em`), i = A.measure.strokeWidth, a = 1, o = 0, s = 1, c = A.measure.em2px, l = rn.createSVG(this, a, o, s, i, `black`, {
								viewBox: [
									0,
									-c(a + o),
									c(s),
									c(a + o)
								].join(` `),
								role: `img`,
								focusable: !1,
								overflow: `visible`
							});
							A.svgForDebug = l, A.svgForTestLayout = l, n.append(t, l.drawArea);
							var u = this.node.cmd;
							if (u) {
								if (this.shape == null) {
									var d = new Mt(), f = new St(Y.none, d);
									u.toShape(f), this.shape = f.shape;
								}
								var p = this.shape;
								p.draw(l);
								var m = p.getBoundingBox();
								if (m !== void 0) {
									var h = (m = new U.Rect(0, 0, {
										l: Math.max(0, -(m.x - m.l)),
										r: Math.max(0, m.x + m.r),
										u: Math.max(0, m.y + m.u),
										d: Math.max(0, -(m.y - m.d))
									})).x - m.l - r, g = -m.y - m.u - r, _ = m.l + m.r + 2 * r, v = m.u + m.d + 2 * r;
									l.setWidth(_), l.setHeight(v), l.setAttribute(`viewBox`, [
										c(h),
										c(g),
										c(_),
										c(v)
									].join(` `));
									var y = this.fixed(1) / c(1);
									n.setAttribute(l.drawArea, `transform`, `translate(` + this.fixed(-h) + `,` + this.fixed(m.y + A.measure.axis_height) + `) scale(` + y + `, ` + -y + `)`);
									var b, x = kn(this._textObjects);
									try {
										for (x.s(); !(b = x.n()).done;) {
											var S = b.value, C = parseFloat(n.getAttribute(S, `data-x`)), w = parseFloat(n.getAttribute(S, `data-y`)), T = C - h, E = -w + m.y + A.measure.axis_height;
											this.place(T, E, S);
										}
									} catch (e) {
										x.e(e);
									} finally {
										x.f();
									}
								} else n.remove(l.drawArea);
							} else n.remove(l.drawArea);
						}
					}
				], [{
					key: `styles`,
					get: function() {
						return {
							"g[data-mml-node=\"xypic\"] path": { "stroke-width": `inherit` },
							".MathJax g[data-mml-node=\"xypic\"] path": { "stroke-width": `inherit` }
						};
					}
				}]), n;
			}(n);
			t[r.prototype.kind] = r;
			var i = function(e) {
				Pn(n, e);
				var t = In(n);
				function n(e, r) {
					var i = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
					return jn(this, n), t.call(this, e, r, i);
				}
				return Nn(n, [
					{
						key: `kind`,
						get: function() {
							return F.xypic.newdir.prototype.kind;
						}
					},
					{
						key: `computeBBox`,
						value: function(e) {
							var t = this.node.cmd;
							A.repositories.dirRepository.put(t.dirMain, t.compositeObject);
						}
					},
					{
						key: `_toSVG`,
						value: function(e) {
							var t = this.node.cmd;
							A.repositories.dirRepository.put(t.dirMain, t.compositeObject);
						}
					}
				]), n;
			}(n);
			t[i.prototype.kind] = i;
			var a = function(e) {
				Pn(n, e);
				var t = In(n);
				function n(e, r) {
					var i, a = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
					return jn(this, n), (i = t.call(this, e, r, a))._setupGraphics(), i.computeBBox(i.bbox), i.bboxComputed = !0, i;
				}
				return Nn(n, [
					{
						key: `kind`,
						get: function() {
							return F.xypic.includegraphics.prototype.kind;
						}
					},
					{
						key: `_setupGraphics`,
						value: function() {
							this.setupMeasure(this);
							var e = new Mt(), t = new St(Y.none, e), n = this.node.cmd;
							if (n.setup(t), !e.includegraphicsWidth.isDefined || !e.includegraphicsHeight.isDefined) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\includegraphics are required.`);
							var r = e.includegraphicsWidth.get, i = e.includegraphicsHeight.get;
							this.imageWidth = this.length2em(r), this.imageHeight = this.length2em(i), this.filepath = n.filepath;
						}
					},
					{
						key: `computeBBox`,
						value: function(e) {
							e.empty(), e.updateFrom(new Gt.bK({
								w: this.imageWidth,
								h: this.imageHeight,
								d: 0
							}));
						}
					},
					{
						key: `_toSVG`,
						value: function(e) {
							var t = this.standardSVGnode(e);
							this.svgNode = t;
							var n = this.fixed(1), r = this.svg(`image`, {
								x: `0`,
								y: `0`,
								preserveAspectRatio: `none`,
								width: Bn(this.imageWidth),
								height: Bn(this.imageHeight),
								transform: `scale(` + n + `,` + -n + `) translate(0,` + Bn(-this.imageHeight) + `)`
							});
							this.adaptor.setAttribute(r, `xlink:href`, this.filepath, `http://www.w3.org/1999/xlink`), this.adaptor.append(t, r);
						}
					}
				]), n;
			}(n);
			t[a.prototype.kind] = a;
		}
		En.y !== void 0 && Vn(En.y, Dn.N);
		var Hn = MathJax._.components.loader.Loader;
		Hn && (MathJax._.output.chtml.Wrapper.CHTMLWrapper || Hn.ready(`output/chtml`).then((function() {
			var e = MathJax._.output.chtml;
			Tn(e.Wrapper.CHTMLWrapper, e.Wrappers_ts.CHTMLWrappers);
		})).catch((function(e) {
			return console.log(`Caught`, e);
		})), MathJax._.output.svg.Wrapper.SVGWrapper || Hn.ready(`output/svg`).then((function() {
			var e = MathJax._.output.svg;
			Vn(e.Wrapper.SVGWrapper, e.Wrappers_ts.SVGWrappers);
		})).catch((function(e) {
			return console.log(`Caught`, e);
		})));
	})();
})();
//#endregion

//# sourceMappingURL=xypic-DrMJn58R.js.map