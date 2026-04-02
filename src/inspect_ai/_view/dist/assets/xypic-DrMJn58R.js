import { g as getDefaultExportFromCjs } from "./_commonjsHelpers.js";
function _mergeNamespaces(n, m) {
  for (var i = 0; i < m.length; i++) {
    const e = m[i];
    if (typeof e !== "string" && !Array.isArray(e)) {
      for (const k in e) {
        if (k !== "default" && !(k in n)) {
          const d = Object.getOwnPropertyDescriptor(e, k);
          if (d) {
            Object.defineProperty(n, k, d.get ? d : {
              enumerable: true,
              get: () => e[k]
            });
          }
        }
      }
    }
  }
  return Object.freeze(Object.defineProperty(n, Symbol.toStringTag, { value: "Module" }));
}
var xypicDrMJn58R$2 = {};
var hasRequiredXypicDrMJn58R;
function requireXypicDrMJn58R() {
  if (hasRequiredXypicDrMJn58R) return xypicDrMJn58R$2;
  hasRequiredXypicDrMJn58R = 1;
  (function() {
    var e = { 401: function(e2, t2) {
      MathJax._.components.global.isObject, MathJax._.components.global.combineConfig, t2.PV = MathJax._.components.global.combineDefaults, MathJax._.components.global.combineWithMathJax, t2.NI = MathJax._.components.global.MathJax;
    }, 771: function(e2, t2) {
      t2.v = MathJax._.core.MmlTree.MML.MML;
    }, 376: function(e2, t2) {
      t2.Ls = MathJax._.core.MmlTree.MmlNode.TEXCLASS, MathJax._.core.MmlTree.MmlNode.TEXCLASSNAMES, MathJax._.core.MmlTree.MmlNode.indentAttributes, t2.oI = MathJax._.core.MmlTree.MmlNode.AbstractMmlNode, MathJax._.core.MmlTree.MmlNode.AbstractMmlTokenNode, MathJax._.core.MmlTree.MmlNode.AbstractMmlLayoutNode, MathJax._.core.MmlTree.MmlNode.AbstractMmlBaseNode, MathJax._.core.MmlTree.MmlNode.AbstractMmlEmptyNode, MathJax._.core.MmlTree.MmlNode.TextNode, MathJax._.core.MmlTree.MmlNode.XMLNode;
    }, 226: function(e2, t2) {
      MathJax._.util.BBox.BBoxStyleAdjust, t2.bK = MathJax._.util.BBox.BBox;
    }, 238: function(e2, t2) {
      t2.VK = MathJax._.input.tex.Configuration.Configuration, MathJax._.input.tex.Configuration.ConfigurationHandler, MathJax._.input.tex.Configuration.ParserConfiguration;
    }, 953: function(e2, t2) {
      t2.Z = MathJax._.input.tex.ParseMethods.default;
    }, 166: function(e2, t2) {
      MathJax._.input.tex.SymbolMap.AbstractSymbolMap, MathJax._.input.tex.SymbolMap.RegExpMap, MathJax._.input.tex.SymbolMap.AbstractParseMap, MathJax._.input.tex.SymbolMap.CharacterMap, MathJax._.input.tex.SymbolMap.DelimiterMap, MathJax._.input.tex.SymbolMap.MacroMap, t2.QQ = MathJax._.input.tex.SymbolMap.CommandMap, t2.QM = MathJax._.input.tex.SymbolMap.EnvironmentMap;
    }, 847: function(e2, t2) {
      t2.Z = MathJax._.input.tex.TexError.default;
    }, 789: function(e2, t2) {
      t2.Z = MathJax._.input.tex.TexParser.default;
    }, 361: function(e2, t2) {
      t2.Z = MathJax._.input.tex.base.BaseMethods.default;
    }, 81: function(e2, t2) {
      MathJax._.output.chtml.Wrapper.FONTSIZE, MathJax._.output.chtml.Wrapper.SPACE, t2.wO = MathJax._.output.chtml.Wrapper.CHTMLWrapper;
    }, 748: function(e2, t2) {
      t2.w = MathJax._.output.chtml.Wrappers_ts.CHTMLWrappers;
    }, 952: function(e2, t2) {
      t2.y = MathJax._.output.svg.Wrapper.SVGWrapper;
    }, 84: function(e2, t2) {
      t2.N = MathJax._.output.svg.Wrappers_ts.SVGWrappers;
    } }, t = {};
    function n(r) {
      var i = t[r];
      if (i !== void 0) return i.exports;
      var a = t[r] = { exports: {} };
      return e[r](a, a.exports, n), a.exports;
    }
    (function() {
      var e2 = n(401);
      (0, e2.PV)(e2.NI._, `output`, { common: { Wrapper: {} }, chtml: { Wrapper: {}, Wrappers_ts: {} }, svg: { Wrapper: {}, Wrappers_ts: {} } });
      var t2 = n(238), r = n(166), i = n(361), a = n(953), o = n(789), s = n(847);
      function c(e3, t3) {
        return console.error(e3, t3), new s.Z(e3, t3);
      }
      var l = { whiteSpaceRegex: /^(\s+|%[^\r\n]*(\r\n|\r|\n)?)+/, lengthResolution: 128, interpolationResolution: 5, machinePrecision: 1e-12 };
      function u(e3) {
        return u = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e4) {
          return typeof e4;
        } : function(e4) {
          return e4 && typeof Symbol == `function` && e4.constructor === Symbol && e4 !== Symbol.prototype ? `symbol` : typeof e4;
        }, u(e3);
      }
      function d(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function f(e3, t3, n2) {
        return t3 && d(e3.prototype, t3), n2 && d(e3, n2), e3;
      }
      function p(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Super expression must either be null or a function`);
        e3.prototype = Object.create(t3 && t3.prototype, { constructor: { value: e3, writable: true, configurable: true } }), t3 && m(e3, t3);
      }
      function m(e3, t3) {
        return m = Object.setPrototypeOf || function(e4, t4) {
          return e4.__proto__ = t4, e4;
        }, m(e3, t3);
      }
      function h(e3) {
        var t3 = (function() {
          if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return false;
          if (typeof Proxy == `function`) return true;
          try {
            return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {
            }))), true;
          } catch {
            return false;
          }
        })();
        return function() {
          var n2, r2 = _(e3);
          if (t3) {
            var i2 = _(this).constructor;
            n2 = Reflect.construct(r2, arguments, i2);
          } else n2 = r2.apply(this, arguments);
          return g(this, n2);
        };
      }
      function g(e3, t3) {
        if (t3 && (u(t3) === `object` || typeof t3 == `function`)) return t3;
        if (t3 !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
        return (function(e4) {
          if (e4 === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
          return e4;
        })(e3);
      }
      function _(e3) {
        return _ = Object.setPrototypeOf ? Object.getPrototypeOf : function(e4) {
          return e4.__proto__ || Object.getPrototypeOf(e4);
        }, _(e3);
      }
      function v(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      var y = function e3() {
        v(this, e3);
      }, b = (function(e3) {
        p(n2, e3);
        var t3 = h(n2);
        function n2(e4) {
          var r2;
          return v(this, n2), (r2 = t3.call(this)).get = e4, r2;
        }
        return f(n2, [{ key: `isEmpty`, get: function() {
          return false;
        } }, { key: `isDefined`, get: function() {
          return true;
        } }, { key: `getOrElse`, value: function(e4) {
          return this.get;
        } }, { key: `flatMap`, value: function(e4) {
          return e4(this.get);
        } }, { key: `map`, value: function(e4) {
          return new n2(e4(this.get));
        } }, { key: `foreach`, value: function(e4) {
          e4(this.get);
        } }, { key: `toString`, value: function() {
          return `Some(` + this.get + `)`;
        } }], [{ key: `unapply`, value: function(e4) {
          return new n2(e4.get);
        } }]), n2;
      })(y), x = (function(e3) {
        p(n2, e3);
        var t3 = h(n2);
        function n2() {
          return v(this, n2), t3.call(this);
        }
        return f(n2, [{ key: `isEmpty`, get: function() {
          return true;
        } }, { key: `isDefined`, get: function() {
          return false;
        } }, { key: `getOrElse`, value: function(e4) {
          return e4;
        } }, { key: `flatMap`, value: function(e4) {
          return this;
        } }, { key: `foreach`, value: function(e4) {
        } }, { key: `map`, value: function(e4) {
          return this;
        } }, { key: `toString`, value: function() {
          return `None`;
        } }], [{ key: `unapply`, value: function(e4) {
          return new b(e4);
        } }]), n2;
      })(y);
      function S(e3) {
        return S = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e4) {
          return typeof e4;
        } : function(e4) {
          return e4 && typeof Symbol == `function` && e4.constructor === Symbol && e4 !== Symbol.prototype ? `symbol` : typeof e4;
        }, S(e3);
      }
      function C(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function w(e3, t3, n2) {
        return t3 && C(e3.prototype, t3), n2 && C(e3, n2), e3;
      }
      function T(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Super expression must either be null or a function`);
        e3.prototype = Object.create(t3 && t3.prototype, { constructor: { value: e3, writable: true, configurable: true } }), t3 && E(e3, t3);
      }
      function E(e3, t3) {
        return E = Object.setPrototypeOf || function(e4, t4) {
          return e4.__proto__ = t4, e4;
        }, E(e3, t3);
      }
      function D(e3) {
        var t3 = (function() {
          if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return false;
          if (typeof Proxy == `function`) return true;
          try {
            return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {
            }))), true;
          } catch {
            return false;
          }
        })();
        return function() {
          var n2, r2 = te(e3);
          if (t3) {
            var i2 = te(this).constructor;
            n2 = Reflect.construct(r2, arguments, i2);
          } else n2 = r2.apply(this, arguments);
          return ee(this, n2);
        };
      }
      function ee(e3, t3) {
        if (t3 && (S(t3) === `object` || typeof t3 == `function`)) return t3;
        if (t3 !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
        return (function(e4) {
          if (e4 === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
          return e4;
        })(e3);
      }
      function te(e3) {
        return te = Object.setPrototypeOf ? Object.getPrototypeOf : function(e4) {
          return e4.__proto__ || Object.getPrototypeOf(e4);
        }, te(e3);
      }
      function ne(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      y.Some = b, y.None = x, y.empty = new x();
      var O = function e3() {
        ne(this, e3);
      }, re = (function(e3) {
        T(n2, e3);
        var t3 = D(n2);
        function n2(e4, r2) {
          var i2;
          return ne(this, n2), (i2 = t3.call(this)).head = e4, i2.tail = r2, i2;
        }
        return w(n2, [{ key: `isEmpty`, get: function() {
          return false;
        } }, { key: `at`, value: function(e4) {
          if (e4 < 0 || e4 >= this.length()) throw Error(`no such element at ` + e4 + `. index must be lower than ` + this.length() + `.`);
          for (var t4 = this, n3 = 0; n3 < e4; n3++) t4 = t4.tail;
          return t4.head;
        } }, { key: `length`, value: function() {
          for (var e4 = this, t4 = 0; !e4.isEmpty; ) t4++, e4 = e4.tail;
          return t4;
        } }, { key: `prepend`, value: function(e4) {
          return new n2(e4, this);
        } }, { key: `append`, value: function(e4) {
          var t4 = new n2(e4, O.empty);
          return this.reverse().foreach((function(e5) {
            t4 = new n2(e5, t4);
          })), t4;
        } }, { key: `concat`, value: function(e4) {
          var t4 = e4;
          return this.reverse().foreach((function(e5) {
            t4 = new n2(e5, t4);
          })), t4;
        } }, { key: `foldLeft`, value: function(e4, t4) {
          var n3, r2;
          for (n3 = t4(e4, this.head), r2 = this.tail; !r2.isEmpty; ) n3 = t4(n3, r2.head), r2 = r2.tail;
          return n3;
        } }, { key: `foldRight`, value: function(e4, t4) {
          return this.tail.isEmpty ? t4(this.head, e4) : t4(this.head, this.tail.foldRight(e4, t4));
        } }, { key: `map`, value: function(e4) {
          return new n2(e4(this.head), this.tail.map(e4));
        } }, { key: `flatMap`, value: function(e4) {
          return e4(this.head).concat(this.tail.flatMap(e4));
        } }, { key: `foreach`, value: function(e4) {
          for (var t4 = this; !t4.isEmpty; ) e4(t4.head), t4 = t4.tail;
        } }, { key: `reverse`, value: function() {
          var e4 = O.empty;
          return this.foreach((function(t4) {
            e4 = new n2(t4, e4);
          })), e4;
        } }, { key: `mkString`, value: function() {
          var e4, t4, r2, i2, a2;
          switch (arguments.length) {
            case 0:
              e4 = t4 = r2 = ``;
              break;
            case 1:
              t4 = arguments[0], e4 = r2 = ``;
              break;
            case 2:
              e4 = arguments[0], t4 = arguments[1], r2 = ``;
              break;
            default:
              e4 = arguments[0], t4 = arguments[1], r2 = arguments[2];
          }
          for (i2 = e4 + this.head.toString(), a2 = this.tail; a2 instanceof n2; ) i2 += t4 + a2.head.toString(), a2 = a2.tail;
          return i2 += r2;
        } }, { key: `toString`, value: function() {
          return this.mkString(`[`, `, `, `]`);
        } }], [{ key: `unapply`, value: function(e4) {
          return new y.Some([e4.head, e4.tail]);
        } }]), n2;
      })(O);
      O.Cons = re;
      var ie = (function(e3) {
        T(n2, e3);
        var t3 = D(n2);
        function n2() {
          return ne(this, n2), t3.call(this);
        }
        return w(n2, [{ key: `isEmpty`, get: function() {
          return true;
        } }, { key: `at`, value: function(e4) {
          throw Error(`cannot get element from an empty list.`);
        } }, { key: `length`, value: function() {
          return 0;
        } }, { key: `prepend`, value: function(e4) {
          return new re(e4, O.empty);
        } }, { key: `append`, value: function(e4) {
          return new re(e4, O.empty);
        } }, { key: `concat`, value: function(e4) {
          return e4;
        } }, { key: `foldLeft`, value: function(e4, t4) {
          return e4;
        } }, { key: `foldRight`, value: function(e4, t4) {
          return e4;
        } }, { key: `flatMap`, value: function(e4) {
          return this;
        } }, { key: `map`, value: function(e4) {
          return this;
        } }, { key: `foreach`, value: function(e4) {
        } }, { key: `reverse`, value: function() {
          return this;
        } }, { key: `mkString`, value: function() {
          switch (arguments.length) {
            case 0:
            case 1:
              return ``;
            case 2:
              return arguments[0];
            default:
              return arguments[0] + arguments[2];
          }
        } }, { key: `toString`, value: function() {
          return `[]`;
        } }], [{ key: `unapply`, value: function(e4) {
          return new y.Some(e4);
        } }]), n2;
      })(O);
      function ae(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      O.Nil = ie, O.empty = new ie(), O.fromArray = function(e3) {
        var t3, n2;
        for (t3 = O.empty, n2 = e3.length - 1; n2 >= 0; ) t3 = new re(e3[n2], t3), --n2;
        return t3;
      };
      var oe = (function() {
        function e3(t4, n3) {
          (function(e4, t5) {
            if (!(e4 instanceof t5)) throw TypeError(`Cannot call a class as a function`);
          })(this, e3), this.head = t4, this.tail = n3;
        }
        var t3, n2, r2;
        return t3 = e3, r2 = [{ key: `unapply`, value: function(e4) {
          return new Option.Some([e4.head, e4.tail]);
        } }], (n2 = [{ key: `toString`, value: function() {
          return `(` + this.head + `~` + this.tail + `)`;
        } }]) && ae(t3.prototype, n2), r2 && ae(t3, r2), e3;
      })();
      function se(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      function ce(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function le(e3, t3, n2) {
        return t3 && ce(e3.prototype, t3), e3;
      }
      var ue = (function() {
        function e3() {
          se(this, e3), this.cases = [];
        }
        return le(e3, [{ key: `Case`, value: function(e4, t3) {
          return this.cases.push([e4, t3]), this;
        } }, { key: `match`, value: function(e4) {
          var t3, n2, r2, i2;
          for (t3 = 0, n2 = this.cases.length; t3 < n2; ) {
            if (e4 instanceof (r2 = this.cases[t3][0]) && (i2 = r2.unapply(e4)).isDefined) return this.cases[t3][1](i2.get);
            t3 += 1;
          }
          throw new de(e4);
        } }]), e3;
      })(), de = (function() {
        function e3(t3) {
          se(this, e3), this.obj = t3;
        }
        return le(e3, [{ key: `toString`, value: function() {
          return `MatchError(` + this.obj + `)`;
        } }]), e3;
      })();
      function fe(e3) {
        return fe = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e4) {
          return typeof e4;
        } : function(e4) {
          return e4 && typeof Symbol == `function` && e4.constructor === Symbol && e4 !== Symbol.prototype ? `symbol` : typeof e4;
        }, fe(e3);
      }
      function pe(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Super expression must either be null or a function`);
        e3.prototype = Object.create(t3 && t3.prototype, { constructor: { value: e3, writable: true, configurable: true } }), t3 && me(e3, t3);
      }
      function me(e3, t3) {
        return me = Object.setPrototypeOf || function(e4, t4) {
          return e4.__proto__ = t4, e4;
        }, me(e3, t3);
      }
      function he(e3) {
        var t3 = (function() {
          if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return false;
          if (typeof Proxy == `function`) return true;
          try {
            return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {
            }))), true;
          } catch {
            return false;
          }
        })();
        return function() {
          var n2, r2 = _e(e3);
          if (t3) {
            var i2 = _e(this).constructor;
            n2 = Reflect.construct(r2, arguments, i2);
          } else n2 = r2.apply(this, arguments);
          return ge(this, n2);
        };
      }
      function ge(e3, t3) {
        if (t3 && (fe(t3) === `object` || typeof t3 == `function`)) return t3;
        if (t3 !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
        return (function(e4) {
          if (e4 === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
          return e4;
        })(e3);
      }
      function _e(e3) {
        return _e = Object.setPrototypeOf ? Object.getPrototypeOf : function(e4) {
          return e4.__proto__ || Object.getPrototypeOf(e4);
        }, _e(e3);
      }
      function ve(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      function ye(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function be(e3, t3, n2) {
        return t3 && ye(e3.prototype, t3), n2 && ye(e3, n2), e3;
      }
      var xe = (function() {
        function e3(t3, n2) {
          ve(this, e3), this.source = t3, this.offset = n2 === void 0 ? 0 : n2, this._index = null, this._line = null;
        }
        return be(e3, [{ key: `index`, value: function() {
          if (this._index !== null) return this._index;
          this._index = [], this._index.push(0);
          for (var e4 = 0; e4 < this.source.length; ) this.source.charAt(e4) === `
` && this._index.push(e4 + 1), e4 += 1;
          return this._index.push(this.source.length), this._index;
        } }, { key: `line`, value: function() {
          var e4, t3, n2;
          if (this._line !== null) return this._line;
          for (e4 = 0, t3 = this.index().length - 1; e4 + 1 < t3; ) n2 = t3 + e4 >> 1, this.offset < this.index()[n2] ? t3 = n2 : e4 = n2;
          return this._line = e4 + 1, this._line;
        } }, { key: `column`, value: function() {
          return this.offset - this.index()[this.line() - 1] + 1;
        } }, { key: `lineContents`, value: function() {
          var e4, t3;
          return e4 = this.index(), t3 = this.line(), this.source.substring(e4[t3 - 1], e4[t3]);
        } }, { key: `toString`, value: function() {
          return this.line().toString() + `.` + this.column();
        } }, { key: `longString`, value: function() {
          var e4, t3;
          for (e4 = this.lineContents() + `
`, t3 = 0; t3 < this.column(); ) this.lineContents().charAt(t3) === `	` ? e4 += `	` : e4 += ` `, t3 += 1;
          return e4 += `^`;
        } }, { key: `isLessThan`, value: function(t3) {
          return t3 instanceof e3 ? this.offset < t3.offset : this.line() < t3.line() || this.line() === t3.line() && this.column() < t3.column();
        } }]), e3;
      })(), Se = (function() {
        function e3(t3, n2, r2) {
          ve(this, e3), this.source = t3, this.offset = n2, this.context = r2;
        }
        return be(e3, [{ key: `first`, value: function() {
          return this.offset < this.source.length ? this.source.charAt(this.offset) : e3.EofCh;
        } }, { key: `rest`, value: function() {
          return this.offset < this.source.length ? new e3(this.source, this.offset + 1, this.context) : this;
        } }, { key: `pos`, value: function() {
          return new xe(this.source, this.offset);
        } }, { key: `atEnd`, value: function() {
          return this.offset >= this.source.length;
        } }, { key: `drop`, value: function(e4) {
          var t3, n2;
          for (t3 = this, n2 = e4; n2 > 0; ) t3 = t3.rest(), --n2;
          return t3;
        } }]), e3;
      })();
      Se.EofCh = ``;
      var k = (function() {
        function e3() {
          ve(this, e3);
        }
        return be(e3, null, [{ key: `parse`, value: function(e4, t3) {
          return e4.apply(t3);
        } }, { key: `parseAll`, value: function(t3, n2) {
          return t3.andl((function() {
            return e3.eos();
          })).apply(n2);
        } }, { key: `parseString`, value: function(t3, n2) {
          var r2 = new Se(n2, 0, { lastNoSuccess: void 0 });
          return e3.parse(t3, r2);
        } }, { key: `parseAllString`, value: function(t3, n2) {
          var r2 = new Se(n2, 0, { lastNoSuccess: void 0 });
          return e3.parseAll(t3, r2);
        } }, { key: `_handleWhiteSpace`, value: function(e4) {
          var t3 = e4.context.whiteSpaceRegex, n2 = e4.source, r2 = e4.offset, i2 = t3.exec(n2.substring(r2, n2.length));
          return i2 === null ? r2 : r2 + i2[0].length;
        } }, { key: `literal`, value: function(t3) {
          return new Oe((function(n2) {
            var r2, i2, a2, o2, s2, c2;
            for (r2 = n2.source, i2 = n2.offset, o2 = 0, s2 = a2 = e3._handleWhiteSpace(n2); o2 < t3.length && s2 < r2.length && t3.charAt(o2) === r2.charAt(s2); ) o2 += 1, s2 += 1;
            return o2 === t3.length ? new we(t3, n2.drop(s2 - i2)) : (c2 = a2 === r2.length ? `end of source` : "`" + r2.charAt(a2) + `'`, new Ee("`" + t3 + `' expected but ` + c2 + ` found`, n2.drop(a2 - i2)));
          }));
        } }, { key: `regex`, value: function(e4) {
          if (e4.toString().substring(0, 2) !== `/^`) throw "regex must start with `^' but " + e4;
          return new Oe((function(t3) {
            var n2, r2, i2, a2;
            return n2 = t3.source, r2 = t3.offset, (i2 = e4.exec(n2.substring(r2, n2.length))) === null ? (a2 = r2 === n2.length ? `end of source` : "`" + n2.charAt(r2) + `'`, new Ee(`string matching regex ` + e4 + ` expected but ` + a2 + ` found`, t3)) : new we(i2[0], t3.drop(i2[0].length));
          }));
        } }, { key: `regexLiteral`, value: function(t3) {
          if (t3.toString().substring(0, 2) !== `/^`) throw "regex must start with `^' but " + t3;
          return new Oe((function(n2) {
            var r2, i2, a2, o2, s2;
            return r2 = n2.source, i2 = n2.offset, a2 = e3._handleWhiteSpace(n2), (o2 = t3.exec(r2.substring(a2, r2.length))) === null ? (s2 = a2 === r2.length ? `end of source` : "`" + r2.charAt(a2) + `'`, new Ee(`string matching regex ` + t3 + ` expected but ` + s2 + ` found`, n2.drop(a2 - i2))) : new we(o2[0], n2.drop(a2 + o2[0].length - i2));
          }));
        } }, { key: `eos`, value: function() {
          return new Oe((function(t3) {
            var n2, r2;
            return n2 = t3.source, t3.offset, r2 = e3._handleWhiteSpace(t3), n2.length === r2 ? new we(``, t3) : new Ee("end of source expected but `" + n2.charAt(r2) + `' found`, t3);
          }));
        } }, { key: `commit`, value: function(e4) {
          return new Oe((function(t3) {
            var n2 = e4()(t3);
            return new ue().Case(we, (function(e5) {
              return n2;
            })).Case(De, (function(e5) {
              return n2;
            })).Case(Ee, (function(e5) {
              return new De(e5[0], e5[1]);
            })).match(n2);
          }));
        } }, { key: `elem`, value: function(t3) {
          return e3.accept(t3).named(`"` + t3 + `"`);
        } }, { key: `accept`, value: function(t3) {
          return e3.acceptIf((function(e4) {
            return e4 === t3;
          }), (function(e4) {
            return "`" + t3 + "' expected but `" + e4 + `' found`;
          }));
        } }, { key: `acceptIf`, value: function(e4, t3) {
          return new Oe((function(n2) {
            return e4(n2.first()) ? new we(n2.first(), n2.rest()) : new Ee(t3(n2.first()), n2);
          }));
        } }, { key: `failure`, value: function(e4) {
          return new Oe((function(t3) {
            return new Ee(e4, t3);
          }));
        } }, { key: `err`, value: function(e4) {
          return new Oe((function(t3) {
            return new De(e4, t3);
          }));
        } }, { key: `success`, value: function(e4) {
          return new Oe((function(t3) {
            return new we(e4, t3);
          }));
        } }, { key: `log`, value: function(e4, t3) {
          return new Oe((function(n2) {
            console.log(`trying ` + t3 + ` at ` + n2);
            var r2 = e4().apply(n2);
            return console.log(t3 + ` --> ` + r2), r2;
          }));
        } }, { key: `rep`, value: function(t3) {
          var n2 = e3.success(O.empty);
          return e3.rep1(t3).or((function() {
            return n2;
          }));
        } }, { key: `rep1`, value: function(e4) {
          return new Oe((function(t3) {
            var n2, r2, i2, a2;
            if (n2 = [], r2 = t3, (a2 = (i2 = e4()).apply(t3)) instanceof we) {
              for (; a2 instanceof we; ) n2.push(a2.result), r2 = a2.next, a2 = i2.apply(r2);
              return new we(O.fromArray(n2), r2);
            }
            return a2;
          }));
        } }, { key: `repN`, value: function(t3, n2) {
          return t3 === 0 ? e3.success(FP.List.empty) : new Oe((function(e4) {
            var r2, i2, a2, o2;
            for (r2 = [], i2 = e4, o2 = (a2 = n2()).apply(i2); o2 instanceof we; ) {
              if (r2.push(o2.result), i2 = o2.next, t3 === r2.length) return new we(O.fromArray(r2), i2);
              o2 = a2.apply(i2);
            }
            return o2;
          }));
        } }, { key: `repsep`, value: function(t3, n2) {
          var r2 = e3.success(O.empty);
          return e3.rep1sep(t3, n2).or((function() {
            return r2;
          }));
        } }, { key: `rep1sep`, value: function(t3, n2) {
          return t3().and(e3.rep(n2().andr(t3))).to((function(e4) {
            return new O.Cons(e4.head, e4.tail);
          }));
        } }, { key: `chainl1`, value: function(t3, n2, r2) {
          return t3().and(e3.rep(r2().and(n2))).to((function(e4) {
            return e4.tail.foldLeft(e4.head, (function(e5, t4) {
              return t4.head(e5, t4.tail);
            }));
          }));
        } }, { key: `chainr1`, value: function(e4, t3, n2, r2) {
          return e4().and(this.rep(t3().and(e4))).to((function(e5) {
            return new O.Cons(new oe(n2, e5.head), e5.tail).foldRight(r2, (function(e6, t4) {
              return e6.head(e6.tail, t4);
            }));
          }));
        } }, { key: `opt`, value: function(t3) {
          return t3().to((function(e4) {
            return new y.Some(e4);
          })).or((function() {
            return e3.success(y.empty);
          }));
        } }, { key: `not`, value: function(e4) {
          return new Oe((function(t3) {
            return e4().apply(t3).successful ? new Ee(`Expected failure`, t3) : new we(y.empty, t3);
          }));
        } }, { key: `guard`, value: function(e4) {
          return new Oe((function(t3) {
            var n2 = e4().apply(t3);
            return n2.successful ? new we(n2.result, t3) : n2;
          }));
        } }, { key: `mkList`, value: function(e4) {
          return new O.Cons(e4.head, e4.tail);
        } }, { key: `fun`, value: function(e4) {
          return function() {
            return e4;
          };
        } }, { key: `lazyParser`, value: function(t3) {
          var n2, r2;
          return t3 instanceof String || typeof t3 == `string` ? (n2 = e3.literal(t3), function() {
            return n2;
          }) : t3 instanceof Function ? t3 : t3 instanceof Object ? t3 instanceof Oe ? function() {
            return t3;
          } : t3 instanceof RegExp ? (r2 = e3.regexLiteral(t3), function() {
            return r2;
          }) : e3.err(`unhandlable type`) : e3.err(`unhandlable type`);
        } }, { key: `seq`, value: function() {
          var t3, n2, r2;
          if ((t3 = arguments.length) === 0) return e3.err(`at least one element must be specified`);
          for (n2 = e3.lazyParser(arguments[0])(), r2 = 1; r2 < t3; ) n2 = n2.and(e3.lazyParser(arguments[r2])), r2 += 1;
          return n2;
        } }, { key: `or`, value: function() {
          var t3, n2, r2;
          if ((t3 = arguments.length) === 0) return e3.err(`at least one element must be specified`);
          for (n2 = e3.lazyParser(arguments[0])(), r2 = 1; r2 < t3; ) n2 = n2.or(e3.lazyParser(arguments[r2])), r2 += 1;
          return n2;
        } }]), e3;
      })(), Ce = (function() {
        function e3() {
          ve(this, e3);
        }
        return be(e3, [{ key: `isEmpty`, value: function() {
          return !this.successful;
        } }, { key: `getOrElse`, value: function(e4) {
          return this.isEmpty ? e4() : this.get();
        } }]), e3;
      })();
      k.ParseResult = Ce;
      var we = (function(e3) {
        pe(n2, e3);
        var t3 = he(n2);
        function n2(e4, r2) {
          var i2;
          return ve(this, n2), (i2 = t3.call(this)).result = e4, i2.next = r2, i2;
        }
        return be(n2, [{ key: `successful`, get: function() {
          return true;
        } }, { key: `map`, value: function(e4) {
          return new n2(e4(this.result), this.next);
        } }, { key: `mapPartial`, value: function(e4, t4) {
          try {
            return new n2(e4(this.result), this.next);
          } catch (e5) {
            if (e5 instanceof de) return new Ee(t4(this.result), this.next);
            throw e5;
          }
        } }, { key: `flatMapWithNext`, value: function(e4) {
          return e4(this.result).apply(this.next);
        } }, { key: `append`, value: function(e4) {
          return this;
        } }, { key: `get`, value: function() {
          return this.result;
        } }, { key: `toString`, value: function() {
          return `[` + this.next.pos() + `] parsed: ` + this.result;
        } }], [{ key: `unapply`, value: function(e4) {
          return new y.Some([e4.result, e4.next]);
        } }]), n2;
      })(Ce);
      k.Success = we;
      var Te = (function(e3) {
        pe(n2, e3);
        var t3 = he(n2);
        function n2() {
          return ve(this, n2), t3.call(this);
        }
        return be(n2, [{ key: `successful`, get: function() {
          return false;
        } }, { key: `_setLastNoSuccess`, value: function() {
          var e4 = this.next.context;
          e4.lastNoSuccess !== void 0 && this.next.pos().isLessThan(e4.lastNoSuccess.next.pos()) || (e4.lastNoSuccess = this);
        } }, { key: `map`, value: function(e4) {
          return this;
        } }, { key: `mapPartial`, value: function(e4, t4) {
          return this;
        } }, { key: `flatMapWithNext`, value: function(e4) {
          return this;
        } }, { key: `get`, value: function() {
          return k.error(`No result when parsing failed`);
        } }]), n2;
      })(Ce);
      k.NoSuccess = Te;
      var Ee = (function(e3) {
        pe(n2, e3);
        var t3 = he(n2);
        function n2(e4, r2) {
          var i2;
          return ve(this, n2), (i2 = t3.call(this)).msg = e4, i2.next = r2, i2._setLastNoSuccess(), i2;
        }
        return be(n2, [{ key: `append`, value: function(e4) {
          var t4 = e4();
          if (t4 instanceof we) return t4;
          if (t4 instanceof Te) return t4.next.pos().isLessThan(this.next.pos()) ? this : t4;
          throw new de(t4);
        } }, { key: `toString`, value: function() {
          return `[` + this.next.pos() + `] failure: ` + this.msg + `

` + this.next.pos().longString();
        } }], [{ key: `unapply`, value: function(e4) {
          return new y.Some([e4.msg, e4.next]);
        } }]), n2;
      })(Te);
      k.Failure = Ee;
      var De = (function(e3) {
        pe(n2, e3);
        var t3 = he(n2);
        function n2(e4, r2) {
          var i2;
          return ve(this, n2), (i2 = t3.call(this)).msg = e4, i2.next = r2, i2._setLastNoSuccess(), i2;
        }
        return be(n2, [{ key: `append`, value: function(e4) {
          return this;
        } }, { key: `toString`, value: function() {
          return `[` + this.next.pos() + `] error: ` + this.msg + `

` + this.next.pos().longString();
        } }], [{ key: `unapply`, value: function(e4) {
          return new y.Some([e4.msg, e4.next]);
        } }]), n2;
      })(Te);
      k.ParseError = De;
      var Oe = (function() {
        function e3(t3) {
          ve(this, e3), this.apply = t3, this.name = ``;
        }
        return be(e3, [{ key: `named`, value: function(e4) {
          return this.name = e4, this;
        } }, { key: `toString`, value: function() {
          return `Parser (` + this.name + `)`;
        } }, { key: `flatMap`, value: function(t3) {
          var n2 = this;
          return new e3((function(e4) {
            return n2.apply(e4).flatMapWithNext(t3);
          }));
        } }, { key: `map`, value: function(t3) {
          var n2 = this;
          return new e3((function(e4) {
            return n2.apply(e4).map(t3);
          }));
        } }, { key: `append`, value: function(t3) {
          var n2 = this;
          return new e3((function(e4) {
            return n2.apply(e4).append((function() {
              return t3().apply(e4);
            }));
          }));
        } }, { key: `and`, value: function(e4) {
          return this.flatMap((function(t3) {
            return e4().map((function(e5) {
              return new oe(t3, e5);
            }));
          })).named(`~`);
        } }, { key: `andr`, value: function(e4) {
          return this.flatMap((function(t3) {
            return e4().map((function(e5) {
              return e5;
            }));
          })).named(`~>`);
        } }, { key: `andl`, value: function(e4) {
          return this.flatMap((function(t3) {
            return e4().map((function(e5) {
              return t3;
            }));
          })).named(`<~`);
        } }, { key: `or`, value: function(e4) {
          return this.append(e4).named(`|`);
        } }, { key: `andOnce`, value: function(e4) {
          var t3 = this;
          return new ke((function() {
            return t3.flatMap((function(t4) {
              return k.commit(e4).map((function(e5) {
                return new oe(t4, e5);
              }));
            })).named(`~!`);
          }));
        } }, { key: `longestOr`, value: function(t3) {
          var n2 = this;
          return new e3((function(e4) {
            var r2, i2;
            return r2 = n2.apply(e4), i2 = t3()(e4), r2.successful ? i2.successful ? i2.next.pos().isLessThan(r2.next.pos()) ? r2 : i2 : r2 : i2.successful ? i2 : r2 instanceof De || i2.next.pos().isLessThan(r2.next.pos()) ? r2 : i2;
          })).named(`|||`);
        } }, { key: `to`, value: function(e4) {
          return this.map(e4).named(this.toString() + `^^`);
        } }, { key: `ret`, value: function(t3) {
          var n2 = this;
          return new e3((function(e4) {
            return n2.apply(e4).map((function(e5) {
              return t3();
            }));
          })).named(this.toString() + `^^^`);
        } }, { key: `toIfPossible`, value: function(t3, n2) {
          n2 === void 0 && (n2 = function(e4) {
            return `Constructor function not defined at ` + e4;
          });
          var r2 = this;
          return new e3((function(e4) {
            return r2.apply(e4).mapPartial(t3, n2);
          })).named(this.toString() + `^?`);
        } }, { key: `into`, value: function(e4) {
          return this.flatMap(e4);
        } }, { key: `rep`, value: function() {
          var e4 = this;
          return k.rep((function() {
            return e4;
          }));
        } }, { key: `chain`, value: function(e4) {
          var t3, n2;
          return t3 = this, n2 = function() {
            return t3;
          }, k.chainl1(n2, n2, e4);
        } }, { key: `rep1`, value: function() {
          var e4 = this;
          return k.rep1((function() {
            return e4;
          }));
        } }, { key: `opt`, value: function() {
          var e4 = this;
          return k.opt((function() {
            return e4;
          }));
        } }]), e3;
      })();
      k.Parser = Oe;
      var ke = (function(e3) {
        pe(n2, e3);
        var t3 = he(n2);
        function n2(e4) {
          return ve(this, n2), t3.call(this, e4);
        }
        return be(n2, [{ key: `and`, value: function(e4) {
          var t4 = this;
          return new n2((function() {
            return t4.flatMap((function(t5) {
              return k.commit(e4).map((function(e5) {
                return oe(t5, e5);
              }));
            }));
          })).named(`~`);
        } }]), n2;
      })(Oe);
      k.OnceParser = ke;
      var Ae = n(376), je = n(771);
      function Me(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      function Ne(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function Pe(e3, t3, n2) {
        return t3 && Ne(e3.prototype, t3), e3;
      }
      var Fe = (function() {
        function e3() {
          Me(this, e3), this.userDirMap = {};
        }
        return Pe(e3, [{ key: `get`, value: function(e4) {
          return this.userDirMap[e4];
        } }, { key: `put`, value: function(e4, t3) {
          this.userDirMap[e4] = t3;
        } }]), e3;
      })(), Ie = (function() {
        function e3() {
          Me(this, e3), this.userModifierMap = {};
        }
        return Pe(e3, [{ key: `get`, value: function(t3) {
          var n2 = e3.embeddedModifierMap[t3];
          return n2 === void 0 ? this.userModifierMap[t3] : n2;
        } }, { key: `put`, value: function(t3, n2) {
          e3.embeddedModifierMap[t3] === void 0 && (this.userModifierMap[t3] = n2);
        } }]), e3;
      })(), A = { repositories: { modifierRepository: new Ie(), dirRepository: new Fe() }, xypicCommandIdCounter: 0, xypicCommandMap: {}, textObjectIdCounter: 0, wrapperOfTextObjectMap: {} };
      function Le(e3) {
        return Le = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e4) {
          return typeof e4;
        } : function(e4) {
          return e4 && typeof Symbol == `function` && e4.constructor === Symbol && e4 !== Symbol.prototype ? `symbol` : typeof e4;
        }, Le(e3);
      }
      function Re(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function j(e3, t3, n2) {
        return t3 && Re(e3.prototype, t3), e3;
      }
      function M(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Super expression must either be null or a function`);
        e3.prototype = Object.create(t3 && t3.prototype, { constructor: { value: e3, writable: true, configurable: true } }), t3 && ze(e3, t3);
      }
      function ze(e3, t3) {
        return ze = Object.setPrototypeOf || function(e4, t4) {
          return e4.__proto__ = t4, e4;
        }, ze(e3, t3);
      }
      function N(e3) {
        var t3 = (function() {
          if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return false;
          if (typeof Proxy == `function`) return true;
          try {
            return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {
            }))), true;
          } catch {
            return false;
          }
        })();
        return function() {
          var n2, r2 = Ve(e3);
          if (t3) {
            var i2 = Ve(this).constructor;
            n2 = Reflect.construct(r2, arguments, i2);
          } else n2 = r2.apply(this, arguments);
          return Be(this, n2);
        };
      }
      function Be(e3, t3) {
        if (t3 && (Le(t3) === `object` || typeof t3 == `function`)) return t3;
        if (t3 !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
        return (function(e4) {
          if (e4 === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
          return e4;
        })(e3);
      }
      function Ve(e3) {
        return Ve = Object.setPrototypeOf ? Object.getPrototypeOf : function(e4) {
          return e4.__proto__ || Object.getPrototypeOf(e4);
        }, Ve(e3);
      }
      function P(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      var F = function e3() {
        P(this, e3);
      }, He = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2) {
          var a2;
          P(this, n2), (a2 = t3.call(this, e4, r2, i2)).textMmls = i2, a2.texClass = Ae.Ls.ORD;
          var o2 = r2[`data-cmd-id`];
          a2.cmd = A.xypicCommandMap[o2];
          for (var s2 = JSON.parse(r2[`data-text-mml-ids`]), c2 = 0, l2 = s2.length; c2 < l2; c2++) i2[c2].xypicTextObjectId = s2[c2];
          return a2;
        }
        return n2;
      })(Ae.oI);
      He.defaults = Ae.oI.defaults, (F.xypic = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2) {
          return P(this, n2), t3.call(this, e4, r2, i2);
        }
        return j(n2, [{ key: `kind`, get: function() {
          return `xypic`;
        } }, { key: `toString`, value: function() {
          return this.kind + `(` + this.cmd + `)`;
        } }]), n2;
      })(He)).defaults = He.defaults, je.v[F.xypic.prototype.kind] = F.xypic, F.xypic.newdir = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2) {
          return P(this, n2), t3.call(this, e4, r2, i2);
        }
        return j(n2, [{ key: `kind`, get: function() {
          return `xypic-newdir`;
        } }, { key: `toString`, value: function() {
          return this.kind + `(` + this.cmd + `)`;
        } }]), n2;
      })(He), F.xypic.newdir.defaults = He.defaults, je.v[F.xypic.newdir.prototype.kind] = F.xypic.newdir, F.xypic.includegraphics = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2) {
          return P(this, n2), t3.call(this, e4, r2, i2);
        }
        return j(n2, [{ key: `kind`, get: function() {
          return `xypic-includegraphics`;
        } }, { key: `toString`, value: function() {
          return this.kind + `(` + this.cmd + `)`;
        } }]), n2;
      })(He), F.xypic.includegraphics.defaults = He.defaults, je.v[F.xypic.includegraphics.prototype.kind] = F.xypic.includegraphics, F.PosDecor = (function() {
        function e3(t3, n2) {
          P(this, e3), this.pos = t3, this.decor = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.pos.toString() + ` ` + this.decor;
        } }]), e3;
      })(), (F.Pos = function e3() {
        P(this, e3);
      }).Coord = (function() {
        function e3(t3, n2) {
          P(this, e3), this.coord = t3, this.pos2s = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.coord.toString() + ` ` + this.pos2s.mkString(` `);
        } }]), e3;
      })(), F.Pos.Plus = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `+(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.Minus = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `-(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.Skew = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `!(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.Cover = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `.(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.Then = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `,(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.SwapPAndC = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `;(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.SetBase = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `:(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.SetYBase = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `::(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.ConnectObject = (function() {
        function e3(t3) {
          P(this, e3), this.object = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `**(` + this.object + `)`;
        } }]), e3;
      })(), F.Pos.DropObject = (function() {
        function e3(t3) {
          P(this, e3), this.object = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `*(` + this.object + `)`;
        } }]), e3;
      })(), F.Pos.Place = (function() {
        function e3(t3) {
          P(this, e3), this.place = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `?(` + this.place + `)`;
        } }]), e3;
      })(), F.Pos.PushCoord = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@+(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.EvalCoordThenPop = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@-(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.LoadStack = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@=(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.DoCoord = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@@(` + this.coord + `)`;
        } }]), e3;
      })(), F.Pos.InitStack = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@i`;
        } }]), e3;
      })(), F.Pos.EnterFrame = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@(`;
        } }]), e3;
      })(), F.Pos.LeaveFrame = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@)`;
        } }]), e3;
      })(), F.Pos.SavePos = (function() {
        function e3(t3) {
          P(this, e3), this.id = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `="` + this.id + `"`;
        } }]), e3;
      })(), F.Pos.SaveMacro = (function() {
        function e3(t3, n2) {
          P(this, e3), this.macro = t3, this.id = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `=(` + this.macro + ` "` + this.id + `")`;
        } }]), e3;
      })(), F.Pos.SaveBase = (function() {
        function e3(t3) {
          P(this, e3), this.id = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `=:"` + this.id + `"`;
        } }]), e3;
      })(), F.Pos.SaveStack = (function() {
        function e3(t3) {
          P(this, e3), this.id = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `=@"` + this.id + `"`;
        } }]), e3;
      })(), (F.Coord = function e3() {
        P(this, e3);
      }).Vector = (function() {
        function e3(t3) {
          P(this, e3), this.vector = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.vector.toString();
        } }]), e3;
      })(), F.Coord.C = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `c`;
        } }]), e3;
      })(), F.Coord.P = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `p`;
        } }]), e3;
      })(), F.Coord.X = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `x`;
        } }]), e3;
      })(), F.Coord.Y = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `y`;
        } }]), e3;
      })(), F.Coord.Id = (function() {
        function e3(t3) {
          P(this, e3), this.id = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `"` + this.id + `"`;
        } }]), e3;
      })(), F.Coord.Group = (function() {
        function e3(t3) {
          P(this, e3), this.posDecor = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `{` + this.posDecor + `}`;
        } }]), e3;
      })(), F.Coord.StackPosition = (function() {
        function e3(t3) {
          P(this, e3), this.number = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `s{` + this.number + `}`;
        } }]), e3;
      })(), F.Coord.DeltaRowColumn = (function() {
        function e3(t3, n2, r2) {
          P(this, e3), this.prefix = t3, this.dr = n2, this.dc = r2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `[` + (this.prefix === `` ? `` : `"` + this.prefix + `"`) + this.dr + `,` + this.dc + `]`;
        } }]), e3;
      })(), F.Coord.Hops = (function() {
        function e3(t3, n2) {
          P(this, e3), this.prefix = t3, this.hops = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `[` + (this.prefix === `` ? `` : `"` + this.prefix + `"`) + this.hops.mkString(``) + `]`;
        } }]), e3;
      })(), F.Coord.HopsWithPlace = (function() {
        function e3(t3, n2, r2) {
          P(this, e3), this.prefix = t3, this.hops = n2, this.place = r2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `[` + (this.prefix === `` ? `` : `"` + this.prefix + `"`) + this.hops.mkString(``) + this.place + `]`;
        } }]), e3;
      })(), (F.Vector = function e3() {
        P(this, e3);
      }).InCurBase = (function() {
        function e3(t3, n2) {
          P(this, e3), this.x = t3, this.y = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `(` + this.x + `, ` + this.y + `)`;
        } }]), e3;
      })(), F.Vector.Abs = (function() {
        function e3(t3, n2) {
          P(this, e3), this.x = t3, this.y = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `<` + this.x + `, ` + this.y + `>`;
        } }]), e3;
      })(), F.Vector.Angle = (function() {
        function e3(t3) {
          P(this, e3), this.degree = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `a(` + this.degree + `)`;
        } }]), e3;
      })(), F.Vector.Dir = (function() {
        function e3(t3, n2) {
          P(this, e3), this.dir = t3, this.dimen = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `/` + this.dir + ` ` + this.dimen + `/`;
        } }]), e3;
      })(), F.Vector.Corner = (function() {
        function e3(t3, n2) {
          P(this, e3), this.corner = t3, this.factor = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.corner.toString() + `(` + this.factor + `)`;
        } }]), e3;
      })(), (F.Corner = function e3() {
        P(this, e3);
      }).L = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `L`;
        } }]), e3;
      })(), F.Corner.R = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `R`;
        } }]), e3;
      })(), F.Corner.D = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `D`;
        } }]), e3;
      })(), F.Corner.U = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `U`;
        } }]), e3;
      })(), F.Corner.CL = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `CL`;
        } }]), e3;
      })(), F.Corner.CR = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `CR`;
        } }]), e3;
      })(), F.Corner.CD = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `CD`;
        } }]), e3;
      })(), F.Corner.CU = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `CU`;
        } }]), e3;
      })(), F.Corner.LD = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `LD`;
        } }]), e3;
      })(), F.Corner.RD = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `RD`;
        } }]), e3;
      })(), F.Corner.LU = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `LU`;
        } }]), e3;
      })(), F.Corner.RU = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `RU`;
        } }]), e3;
      })(), F.Corner.NearestEdgePoint = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `E`;
        } }]), e3;
      })(), F.Corner.PropEdgePoint = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `P`;
        } }]), e3;
      })(), F.Corner.Axis = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `A`;
        } }]), e3;
      })(), (F.Place = (function() {
        function e3(t3, n2, r2, i2) {
          P(this, e3), this.shaveP = t3, this.shaveC = n2, this.factor = r2, this.slide = i2;
        }
        return j(e3, [{ key: `compound`, value: function(e4) {
          return new F.Place(this.shaveP + e4.shaveP, this.shaveC + e4.shaveC, e4.factor === void 0 ? this.factor : e4.factor, e4.slide);
        } }, { key: `toString`, value: function() {
          for (var e4 = ``, t3 = 0; t3 < this.shaveP; t3++) e4 += `<`;
          for (var n2 = 0; n2 < this.shaveC; n2++) e4 += `>`;
          return this.factor !== void 0 && (e4 += `(` + this.factor + `)`), this.slide.dimen.foreach((function(t4) {
            e4 += `/` + t4 + `/`;
          })), e4;
        } }]), e3;
      })()).Factor = (function() {
        function e3(t3) {
          P(this, e3), this.factor = t3;
        }
        return j(e3, [{ key: `isIntercept`, get: function() {
          return false;
        } }, { key: `toString`, value: function() {
          return this.factor.toString();
        } }]), e3;
      })(), F.Place.Intercept = (function() {
        function e3(t3) {
          P(this, e3), this.pos = t3;
        }
        return j(e3, [{ key: `isIntercept`, get: function() {
          return true;
        } }, { key: `toString`, value: function() {
          return `!{` + this.pos + `}`;
        } }]), e3;
      })(), F.Slide = (function() {
        function e3(t3) {
          P(this, e3), this.dimen = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.dimen.getOrElse(``);
        } }]), e3;
      })(), F.Object = (function() {
        function e3(t3, n2) {
          P(this, e3), this.modifiers = t3, this.object = n2;
        }
        return j(e3, [{ key: `dirVariant`, value: function() {
          return this.object.dirVariant();
        } }, { key: `dirMain`, value: function() {
          return this.object.dirMain();
        } }, { key: `isDir`, value: function() {
          return this.object.isDir();
        } }, { key: `toString`, value: function() {
          return this.modifiers.mkString() + this.object.toString();
        } }]), e3;
      })(), (F.ObjectBox = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `isEmpty`, get: function() {
          return false;
        } }, { key: `dirVariant`, value: function() {
        } }, { key: `dirMain`, value: function() {
        } }, { key: `isDir`, value: function() {
          return false;
        } }]), e3;
      })()).Text = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).math = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `{` + this.math.toString() + `}`;
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Empty = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `isEmpty`, get: function() {
          return true;
        } }, { key: `toString`, value: function() {
          return `{}`;
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Xymatrix = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).xymatrix = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return this.xymatrix.toString();
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Txt = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          var i2;
          return P(this, n2), (i2 = t3.call(this)).width = e4, i2.textObject = r2, i2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\txt` + this.width + `{` + this.textObject.toString() + `}`;
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Txt.Width = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return n2;
      })(F.ObjectBox), F.ObjectBox.Txt.Width.Vector = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).vector = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return this.vector.toString();
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Txt.Width.Default = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return ``;
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.WrapUpObject = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).object = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\object` + this.object.toString();
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.CompositeObject = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).objects = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\composite{` + this.objects.mkString(` * `) + `}`;
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Xybox = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).posDecor = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\xybox{` + this.posDecor.toString() + `}`;
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Cir = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          var i2;
          return P(this, n2), (i2 = t3.call(this)).radius = e4, i2.cir = r2, i2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\cir` + this.radius + `{` + this.cir + `}`;
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Cir.Radius = function e3() {
        P(this, e3);
      }, F.ObjectBox.Cir.Radius.Vector = (function() {
        function e3(t3) {
          P(this, e3), this.vector = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.vector.toString();
        } }]), e3;
      })(), F.ObjectBox.Cir.Radius.Default = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return ``;
        } }]), e3;
      })(), F.ObjectBox.Cir.Cir = function e3() {
        P(this, e3);
      }, F.ObjectBox.Cir.Cir.Segment = (function() {
        function e3(t3, n2, r2) {
          P(this, e3), this.startDiag = t3, this.orient = n2, this.endDiag = r2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.startDiag.toString() + this.orient + this.endDiag;
        } }]), e3;
      })(), F.ObjectBox.Cir.Cir.Full = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return ``;
        } }]), e3;
      })(), F.ObjectBox.Dir = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          var i2;
          return P(this, n2), (i2 = t3.call(this)).variant = e4, i2.main = r2, i2;
        }
        return j(n2, [{ key: `dirVariant`, value: function() {
          return this.variant;
        } }, { key: `dirMain`, value: function() {
          return this.main;
        } }, { key: `isDir`, value: function() {
          return true;
        } }, { key: `toString`, value: function() {
          return `\\dir` + this.variant + `{` + this.main + `}`;
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Curve = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2) {
          var a2;
          return P(this, n2), (a2 = t3.call(this)).modifiers = e4, a2.objects = r2, a2.poslist = i2, a2;
        }
        return j(n2, [{ key: `dirVariant`, value: function() {
          return ``;
        } }, { key: `dirMain`, value: function() {
          return `-`;
        } }, { key: `isDir`, value: function() {
          return false;
        } }, { key: `toString`, value: function() {
          return `\\curve` + this.modifiers.mkString(``) + `{` + this.objects.mkString(` `) + ` ` + this.poslist.mkString(`&`) + `}`;
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Curve.Modifier = function e3() {
        P(this, e3);
      }, F.ObjectBox.Curve.Modifier.p = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~p`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.P = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~P`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.l = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~l`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.L = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~L`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.c = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~c`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.C = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~C`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.pc = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~pc`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.pC = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~pC`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.Pc = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~Pc`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.PC = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~PC`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.lc = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~lc`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.lC = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~lC`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.Lc = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~Lc`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.LC = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~LC`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Modifier.cC = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~cC`;
        } }]), e3;
      })(), F.ObjectBox.Curve.Object = function e3() {
        P(this, e3);
      }, F.ObjectBox.Curve.Object.Drop = (function() {
        function e3(t3) {
          P(this, e3), this.object = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~*` + this.object;
        } }]), e3;
      })(), F.ObjectBox.Curve.Object.Connect = (function() {
        function e3(t3) {
          P(this, e3), this.object = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~**` + this.object;
        } }]), e3;
      })(), F.ObjectBox.Curve.PosList = function e3() {
        P(this, e3);
      }, F.ObjectBox.Curve.PosList.CurPos = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return ``;
        } }]), e3;
      })(), F.ObjectBox.Curve.PosList.Pos = (function() {
        function e3(t3) {
          P(this, e3), this.pos = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.pos.toString();
        } }]), e3;
      })(), F.ObjectBox.Curve.PosList.AddStack = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~@`;
        } }]), e3;
      })(), (F.Modifier = function e3() {
        P(this, e3);
      }).Vector = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).vector = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `!` + this.vector;
        } }]), n2;
      })(F.Modifier), F.Modifier.RestoreOriginalRefPoint = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `!`;
        } }]), n2;
      })(F.Modifier), F.Modifier.AddOp = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          var i2;
          return P(this, n2), (i2 = t3.call(this)).op = e4, i2.size = r2, i2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return this.op.toString() + ` ` + this.size;
        } }]), n2;
      })(F.Modifier), F.Modifier.AddOp.Grow = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `+`;
        } }]), e3;
      })(), F.Modifier.AddOp.Shrink = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `-`;
        } }]), e3;
      })(), F.Modifier.AddOp.Set = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `=`;
        } }]), e3;
      })(), F.Modifier.AddOp.GrowTo = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `+=`;
        } }]), e3;
      })(), F.Modifier.AddOp.ShrinkTo = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `-=`;
        } }]), e3;
      })(), F.Modifier.AddOp.VactorSize = (function() {
        function e3(t3) {
          P(this, e3), this.vector = t3;
        }
        return j(e3, [{ key: `isDefault`, get: function() {
          return false;
        } }, { key: `toString`, value: function() {
          return this.vector.toString();
        } }]), e3;
      })(), F.Modifier.AddOp.DefaultSize = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `isDefault`, get: function() {
          return true;
        } }, { key: `toString`, value: function() {
          return ``;
        } }]), e3;
      })(), F.Modifier.Shape = function e3() {
        P(this, e3);
      }, F.Modifier.Shape.Point = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[.]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.Rect = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.Alphabets = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).alphabets = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[` + this.alphabets + `]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.DefineShape = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).shape = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[` + this.shape + `]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.Circle = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[o]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.L = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[l]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.R = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[r]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.U = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[u]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.D = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[d]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.C = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[c]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.ChangeColor = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).colorName = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[` + this.colorName + `]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.CompositeModifiers = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).modifiers = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return this.modifiers.mkString(``);
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.Frame = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          var i2;
          return P(this, n2), (i2 = t3.call(this)).main = e4, i2.options = r2, i2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `[F` + this.main + this.options.mkString(``) + `]`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Shape.Frame.Radius = (function() {
        function e3(t3) {
          P(this, e3), this.vector = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `:` + this.vector;
        } }]), e3;
      })(), F.Modifier.Shape.Frame.Color = (function() {
        function e3(t3) {
          P(this, e3), this.colorName = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `:` + this.colorName;
        } }]), e3;
      })(), F.Modifier.Invisible = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `i`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Hidden = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `h`;
        } }]), n2;
      })(F.Modifier), F.Modifier.Direction = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).direction = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return this.direction.toString();
        } }]), n2;
      })(F.Modifier), (F.Direction = function e3() {
        P(this, e3);
      }).Compound = (function() {
        function e3(t3, n2) {
          P(this, e3), this.dir = t3, this.rots = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.dir.toString() + this.rots.mkString();
        } }]), e3;
      })(), F.Direction.Diag = (function() {
        function e3(t3) {
          P(this, e3), this.diag = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.diag.toString();
        } }]), e3;
      })(), F.Direction.Vector = (function() {
        function e3(t3) {
          P(this, e3), this.vector = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `v` + this.vector.toString();
        } }]), e3;
      })(), F.Direction.ConstructVector = (function() {
        function e3(t3) {
          P(this, e3), this.posDecor = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `q{` + this.posDecor.toString() + `}`;
        } }]), e3;
      })(), F.Direction.RotVector = (function() {
        function e3(t3) {
          P(this, e3), this.vector = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `:` + this.vector.toString();
        } }]), e3;
      })(), F.Direction.RotAntiCW = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `_`;
        } }]), e3;
      })(), F.Direction.RotCW = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `^`;
        } }]), e3;
      })(), (F.Diag = function e3() {
        P(this, e3);
      }).Default = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return ``;
        } }]), e3;
      })(), F.Diag.Angle = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.symbol;
        } }]), e3;
      })(), F.Diag.LD = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `symbol`, get: function() {
          return `ld`;
        } }, { key: `ang`, get: function() {
          return -3 * Math.PI / 4;
        } }, { key: `turn`, value: function(e4) {
          return e4 === `^` ? new F.Diag.RD() : new F.Diag.LU();
        } }]), n2;
      })(F.Diag.Angle), F.Diag.RD = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `symbol`, get: function() {
          return `rd`;
        } }, { key: `ang`, get: function() {
          return -Math.PI / 4;
        } }, { key: `turn`, value: function(e4) {
          return e4 === `^` ? new F.Diag.RU() : new F.Diag.LD();
        } }]), n2;
      })(F.Diag.Angle), F.Diag.LU = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `symbol`, get: function() {
          return `lu`;
        } }, { key: `ang`, get: function() {
          return 3 * Math.PI / 4;
        } }, { key: `turn`, value: function(e4) {
          return e4 === `^` ? new F.Diag.LD() : new F.Diag.RU();
        } }]), n2;
      })(F.Diag.Angle), F.Diag.RU = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `symbol`, get: function() {
          return `ru`;
        } }, { key: `ang`, get: function() {
          return Math.PI / 4;
        } }, { key: `turn`, value: function(e4) {
          return e4 === `^` ? new F.Diag.LU() : new F.Diag.RD();
        } }]), n2;
      })(F.Diag.Angle), F.Diag.L = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `symbol`, get: function() {
          return `l`;
        } }, { key: `ang`, get: function() {
          return Math.PI;
        } }, { key: `turn`, value: function(e4) {
          return e4 === `^` ? new F.Diag.D() : new F.Diag.U();
        } }]), n2;
      })(F.Diag.Angle), F.Diag.R = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `symbol`, get: function() {
          return `r`;
        } }, { key: `ang`, get: function() {
          return 0;
        } }, { key: `turn`, value: function(e4) {
          return e4 === `^` ? new F.Diag.U() : new F.Diag.D();
        } }]), n2;
      })(F.Diag.Angle), F.Diag.D = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `symbol`, get: function() {
          return `d`;
        } }, { key: `ang`, get: function() {
          return -Math.PI / 2;
        } }, { key: `turn`, value: function(e4) {
          return e4 === `^` ? new F.Diag.R() : new F.Diag.L();
        } }]), n2;
      })(F.Diag.Angle), F.Diag.U = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `symbol`, get: function() {
          return `u`;
        } }, { key: `ang`, get: function() {
          return Math.PI / 2;
        } }, { key: `turn`, value: function(e4) {
          return e4 === `^` ? new F.Diag.L() : new F.Diag.R();
        } }]), n2;
      })(F.Diag.Angle), F.ObjectBox.Frame = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          var i2;
          return P(this, n2), (i2 = t3.call(this)).radius = e4, i2.main = r2, i2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\frm` + this.radius + `{` + this.main + `}`;
        } }]), n2;
      })(F.ObjectBox), F.ObjectBox.Frame.Radius = function e3() {
        P(this, e3);
      }, F.ObjectBox.Frame.Radius.Vector = (function() {
        function e3(t3) {
          P(this, e3), this.vector = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.vector.toString();
        } }]), e3;
      })(), F.ObjectBox.Frame.Radius.Default = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return ``;
        } }]), e3;
      })(), F.Decor = (function() {
        function e3(t3) {
          P(this, e3), this.commands = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.commands.mkString(` `);
        } }]), e3;
      })(), (F.Command = function e3() {
        P(this, e3);
      }).Save = (function() {
        function e3(t3) {
          P(this, e3), this.pos = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\save ` + this.pos;
        } }]), e3;
      })(), F.Command.Restore = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\restore`;
        } }]), e3;
      })(), F.Command.Pos = (function() {
        function e3(t3) {
          P(this, e3), this.pos = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\POS ` + this.pos;
        } }]), e3;
      })(), F.Command.AfterPos = (function() {
        function e3(t3, n2) {
          P(this, e3), this.decor = t3, this.pos = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\afterPOS{` + this.decor + `} ` + this.pos;
        } }]), e3;
      })(), F.Command.Drop = (function() {
        function e3(t3) {
          P(this, e3), this.object = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\drop ` + this.object;
        } }]), e3;
      })(), F.Command.Connect = (function() {
        function e3(t3) {
          P(this, e3), this.object = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\connect ` + this.object;
        } }]), e3;
      })(), F.Command.Relax = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\relax`;
        } }]), e3;
      })(), F.Command.Ignore = (function() {
        function e3(t3, n2) {
          P(this, e3), this.pos = t3, this.decor = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\ignore{` + this.pos + ` ` + this.decor + `}`;
        } }]), e3;
      })(), F.Command.ShowAST = (function() {
        function e3(t3, n2) {
          P(this, e3), this.pos = t3, this.decor = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\xyshowAST{` + this.pos + ` ` + this.decor + `}`;
        } }]), e3;
      })(), F.Command.Path = (function() {
        function e3(t3) {
          P(this, e3), this.path = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\PATH ` + this.path;
        } }]), e3;
      })(), F.Command.AfterPath = (function() {
        function e3(t3, n2) {
          P(this, e3), this.decor = t3, this.path = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\afterPATH{` + this.decor + `} ` + this.path;
        } }]), e3;
      })(), F.Command.Path.Path = (function() {
        function e3(t3) {
          P(this, e3), this.pathElements = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.pathElements.mkString(`[`, `, `, `]`);
        } }]), e3;
      })(), F.Command.Path.SetBeforeAction = (function() {
        function e3(t3) {
          P(this, e3), this.posDecor = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~={` + this.posDecor + `}`;
        } }]), e3;
      })(), F.Command.Path.SetAfterAction = (function() {
        function e3(t3) {
          P(this, e3), this.posDecor = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~/{` + this.posDecor + `}`;
        } }]), e3;
      })(), F.Command.Path.AddLabelNextSegmentOnly = (function() {
        function e3(t3) {
          P(this, e3), this.labels = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~<{` + this.labels + `}`;
        } }]), e3;
      })(), F.Command.Path.AddLabelLastSegmentOnly = (function() {
        function e3(t3) {
          P(this, e3), this.labels = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~>{` + this.labels + `}`;
        } }]), e3;
      })(), F.Command.Path.AddLabelEverySegment = (function() {
        function e3(t3) {
          P(this, e3), this.labels = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~+{` + this.labels + `}`;
        } }]), e3;
      })(), F.Command.Path.StraightSegment = (function() {
        function e3(t3) {
          P(this, e3), this.segment = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `'` + this.segment;
        } }]), e3;
      })(), F.Command.Path.TurningSegment = (function() {
        function e3(t3, n2) {
          P(this, e3), this.turn = t3, this.segment = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return "`" + this.turn + ` ` + this.segment;
        } }]), e3;
      })(), F.Command.Path.LastSegment = (function() {
        function e3(t3) {
          P(this, e3), this.segment = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.segment.toString();
        } }]), e3;
      })(), F.Command.Path.Turn = function e3() {
        P(this, e3);
      }, F.Command.Path.Turn.Diag = (function() {
        function e3(t3, n2) {
          P(this, e3), this.diag = t3, this.radius = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.diag.toString() + ` ` + this.radius;
        } }]), e3;
      })(), F.Command.Path.Turn.Cir = (function() {
        function e3(t3, n2) {
          P(this, e3), this.cir = t3, this.radius = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.cir.toString() + ` ` + this.radius;
        } }]), e3;
      })(), F.Command.Path.TurnRadius = function e3() {
        P(this, e3);
      }, F.Command.Path.TurnRadius.Default = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return ``;
        } }]), e3;
      })(), F.Command.Path.TurnRadius.Dimen = (function() {
        function e3(t3) {
          P(this, e3), this.dimen = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `/` + this.dimen;
        } }]), e3;
      })(), F.Command.Path.Segment = (function() {
        function e3(t3, n2, r2) {
          P(this, e3), this.pos = t3, this.slide = n2, this.labels = r2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.pos.toString() + ` ` + this.slide + ` ` + this.labels;
        } }]), e3;
      })(), F.Command.Path.Labels = (function() {
        function e3(t3) {
          P(this, e3), this.labels = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.labels.mkString(` `);
        } }]), e3;
      })(), F.Command.Path.Label = function e3(t3, n2, r2) {
        P(this, e3), this.anchor = t3, this.it = n2, this.aliasOption = r2;
      }, F.Command.Path.Label.Above = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2) {
          return P(this, n2), t3.call(this, e4, r2, i2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `^(` + this.anchor + ` ` + this.it + ` ` + this.aliasOption + `)`;
        } }]), n2;
      })(F.Command.Path.Label), F.Command.Path.Label.Below = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2) {
          return P(this, n2), t3.call(this, e4, r2, i2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `_(` + this.anchor + ` ` + this.it + ` ` + this.aliasOption + `)`;
        } }]), n2;
      })(F.Command.Path.Label), F.Command.Path.Label.At = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2) {
          return P(this, n2), t3.call(this, e4, r2, i2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `|(` + this.anchor + ` ` + this.it + ` ` + this.aliasOption + `)`;
        } }]), n2;
      })(F.Command.Path.Label), F.Command.Ar = (function() {
        function e3(t3, n2) {
          P(this, e3), this.forms = t3, this.path = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\ar ` + this.forms.mkString(` `) + ` ` + this.path;
        } }]), e3;
      })(), F.Command.Ar.Form = function e3() {
        P(this, e3);
      }, F.Command.Ar.Form.BuildArrow = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2, a2) {
          var o2;
          return P(this, n2), (o2 = t3.call(this)).variant = e4, o2.tailTip = r2, o2.stemConn = i2, o2.headTip = a2, o2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@` + this.variant + `{` + this.tailTip.toString() + `, ` + this.stemConn.toString() + `, ` + this.headTip.toString() + `}`;
        } }]), n2;
      })(F.Command.Ar.Form), F.Command.Ar.Form.ChangeVariant = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).variant = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@` + this.variant;
        } }]), n2;
      })(F.Command.Ar.Form), F.Command.Ar.Form.Tip = function e3() {
        P(this, e3);
      }, F.Command.Ar.Form.Tip.Tipchars = (function() {
        function e3(t3) {
          P(this, e3), this.tipchars = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.tipchars;
        } }]), e3;
      })(), F.Command.Ar.Form.Tip.Object = (function() {
        function e3(t3) {
          P(this, e3), this.object = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `*` + this.object;
        } }]), e3;
      })(), F.Command.Ar.Form.Tip.Dir = (function() {
        function e3(t3) {
          P(this, e3), this.dir = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.dir;
        } }]), e3;
      })(), F.Command.Ar.Form.Conn = function e3() {
        P(this, e3);
      }, F.Command.Ar.Form.Conn.Connchars = (function() {
        function e3(t3) {
          P(this, e3), this.connchars = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.connchars;
        } }]), e3;
      })(), F.Command.Ar.Form.Conn.Object = (function() {
        function e3(t3) {
          P(this, e3), this.object = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `*` + this.object;
        } }]), e3;
      })(), F.Command.Ar.Form.Conn.Dir = (function() {
        function e3(t3) {
          P(this, e3), this.dir = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.dir;
        } }]), e3;
      })(), F.Command.Ar.Form.ChangeStem = (function() {
        function e3(t3) {
          P(this, e3), this.connchar = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@` + this.connchar;
        } }]), e3;
      })(), F.Command.Ar.Form.DashArrowStem = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@!`;
        } }]), e3;
      })(), F.Command.Ar.Form.CurveArrow = (function() {
        function e3(t3, n2) {
          P(this, e3), this.direction = t3, this.dist = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@/` + this.direction + ` ` + this.dist + `/`;
        } }]), e3;
      })(), F.Command.Ar.Form.CurveFitToDirection = (function() {
        function e3(t3, n2) {
          P(this, e3), this.outDirection = t3, this.inDirection = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@(` + this.outDirection + `,` + this.inDirection + `)`;
        } }]), e3;
      })(), F.Command.Ar.Form.CurveWithControlPoints = (function() {
        function e3(t3) {
          P(this, e3), this.coord = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return "@`{" + this.coord + `}`;
        } }]), e3;
      })(), F.Command.Ar.Form.AddShape = (function() {
        function e3(t3) {
          P(this, e3), this.shape = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@[` + this.shape + `]`;
        } }]), e3;
      })(), F.Command.Ar.Form.AddModifiers = (function() {
        function e3(t3) {
          P(this, e3), this.modifiers = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@*{` + this.modifiers.mkString(` `) + `}`;
        } }]), e3;
      })(), F.Command.Ar.Form.Slide = (function() {
        function e3(t3) {
          P(this, e3), this.slideDimen = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@<` + this.slideDimen + `>`;
        } }]), e3;
      })(), F.Command.Ar.Form.LabelAt = (function() {
        function e3(t3, n2) {
          P(this, e3), this.anchor = t3, this.it = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `|` + this.anchor + ` ` + this.it;
        } }]), e3;
      })(), F.Command.Ar.Form.LabelAbove = (function() {
        function e3(t3, n2) {
          P(this, e3), this.anchor = t3, this.it = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `^` + this.anchor + ` ` + this.it;
        } }]), e3;
      })(), F.Command.Ar.Form.LabelBelow = (function() {
        function e3(t3, n2) {
          P(this, e3), this.anchor = t3, this.it = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `_` + this.anchor + ` ` + this.it;
        } }]), e3;
      })(), F.Command.Ar.Form.ReverseAboveAndBelow = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@?`;
        } }]), e3;
      })(), F.Command.Xymatrix = (function() {
        function e3(t3, n2) {
          P(this, e3), this.setup = t3, this.rows = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\xymatrix` + this.setup + `{
` + this.rows.mkString(``, `\\\\
`, ``) + `
}`;
        } }]), e3;
      })(), F.Command.Xymatrix.Setup = function e3() {
        P(this, e3);
      }, F.Command.Xymatrix.Setup.Prefix = (function() {
        function e3(t3) {
          P(this, e3), this.prefix = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `"` + this.prefix + `"`;
        } }]), e3;
      })(), F.Command.Xymatrix.Setup.ChangeSpacing = function e3(t3, n2) {
        P(this, e3), this.addop = t3, this.dimen = n2;
      }, F.Command.Xymatrix.Setup.ChangeSpacing.Row = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          return P(this, n2), t3.call(this, e4, r2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@R` + this.addop + this.dimen;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.ChangeSpacing), F.Command.Xymatrix.Setup.ChangeSpacing.Column = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          return P(this, n2), t3.call(this, e4, r2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@C` + this.addop + this.dimen;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.ChangeSpacing), F.Command.Xymatrix.Setup.ChangeSpacing.RowAndColumn = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          return P(this, n2), t3.call(this, e4, r2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@` + this.addop + this.dimen;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.ChangeSpacing), F.Command.Xymatrix.Setup.PretendEntrySize = function e3(t3) {
        P(this, e3), this.dimen = t3;
      }, F.Command.Xymatrix.Setup.PretendEntrySize.Height = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          return P(this, n2), t3.call(this, e4);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@!R=` + this.dimen;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.PretendEntrySize), F.Command.Xymatrix.Setup.PretendEntrySize.Width = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          return P(this, n2), t3.call(this, e4);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@!C=` + this.dimen;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.PretendEntrySize), F.Command.Xymatrix.Setup.PretendEntrySize.HeightAndWidth = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          return P(this, n2), t3.call(this, e4);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@!=` + this.dimen;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.PretendEntrySize), F.Command.Xymatrix.Setup.FixGrid = function e3() {
        P(this, e3);
      }, F.Command.Xymatrix.Setup.FixGrid.Row = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@!R`;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.FixGrid), F.Command.Xymatrix.Setup.FixGrid.Column = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@!C`;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.FixGrid), F.Command.Xymatrix.Setup.FixGrid.RowAndColumn = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@!`;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.FixGrid), F.Command.Xymatrix.Setup.AdjustEntrySize = function e3(t3, n2) {
        P(this, e3), this.addop = t3, this.dimen = n2;
      }, F.Command.Xymatrix.Setup.AdjustEntrySize.Margin = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          return P(this, n2), t3.call(this, e4, r2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@M` + this.addop + this.dimen;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.AdjustEntrySize), F.Command.Xymatrix.Setup.AdjustEntrySize.Width = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          return P(this, n2), t3.call(this, e4, r2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@W` + this.addop + this.dimen;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.AdjustEntrySize), F.Command.Xymatrix.Setup.AdjustEntrySize.Height = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          return P(this, n2), t3.call(this, e4, r2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `@H` + this.addop + this.dimen;
        } }]), n2;
      })(F.Command.Xymatrix.Setup.AdjustEntrySize), F.Command.Xymatrix.Setup.AdjustLabelSep = (function() {
        function e3(t3, n2) {
          P(this, e3), this.addop = t3, this.dimen = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@L` + this.addop + this.dimen;
        } }]), e3;
      })(), F.Command.Xymatrix.Setup.SetOrientation = (function() {
        function e3(t3) {
          P(this, e3), this.direction = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@` + this.direction;
        } }]), e3;
      })(), F.Command.Xymatrix.Setup.AddModifier = (function() {
        function e3(t3) {
          P(this, e3), this.modifier = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `@*` + this.modifier;
        } }]), e3;
      })(), F.Command.Xymatrix.Row = (function() {
        function e3(t3) {
          P(this, e3), this.entries = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.entries.mkString(` & `);
        } }]), e3;
      })(), F.Command.Xymatrix.Entry = function e3() {
        P(this, e3);
      }, F.Command.Xymatrix.Entry.SimpleEntry = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2) {
          var a2;
          return P(this, n2), (a2 = t3.call(this)).modifiers = e4, a2.objectbox = r2, a2.decor = i2, a2;
        }
        return j(n2, [{ key: `isEmpty`, get: function() {
          return false;
        } }, { key: `toString`, value: function() {
          return this.modifiers.mkString(`**{`, ``, `}`) + ` ` + this.objectbox + ` ` + this.decor;
        } }]), n2;
      })(F.Command.Xymatrix.Entry), F.Command.Xymatrix.Entry.ObjectEntry = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2) {
          var a2;
          return P(this, n2), (a2 = t3.call(this)).object = e4, a2.pos = r2, a2.decor = i2, a2;
        }
        return j(n2, [{ key: `isEmpty`, get: function() {
          return false;
        } }, { key: `toString`, value: function() {
          return `*` + this.object + ` ` + this.pos + ` ` + this.decor;
        } }]), n2;
      })(F.Command.Xymatrix.Entry), F.Command.Xymatrix.Entry.EmptyEntry = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).decor = e4, r2;
        }
        return j(n2, [{ key: `isEmpty`, get: function() {
          return true;
        } }, { key: `toString`, value: function() {
          return `` + this.decor;
        } }]), n2;
      })(F.Command.Xymatrix.Entry), F.Command.Twocell = (function() {
        function e3(t3, n2, r2) {
          P(this, e3), this.twocell = t3, this.switches = n2, this.arrow = r2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.twocell.toString() + this.switches.mkString(``) + this.arrow;
        } }]), e3;
      })(), F.Command.Twocell.Hops2cell = function e3(t3, n2) {
        P(this, e3), this.hops = t3, this.maybeDisplace = n2;
      }, F.Command.Twocell.Twocell = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          return P(this, n2), t3.call(this, e4, r2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\xtwocell[` + this.hops + `]` + this.maybeDisplace.getOrElse(`{}`);
        } }]), n2;
      })(F.Command.Twocell.Hops2cell), F.Command.Twocell.UpperTwocell = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          return P(this, n2), t3.call(this, e4, r2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\xuppertwocell[` + this.hops + `]` + this.maybeDisplace.getOrElse(`{}`);
        } }]), n2;
      })(F.Command.Twocell.Hops2cell), F.Command.Twocell.LowerTwocell = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          return P(this, n2), t3.call(this, e4, r2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\xlowertwocell[` + this.hops + `]` + this.maybeDisplace.getOrElse(`{}`);
        } }]), n2;
      })(F.Command.Twocell.Hops2cell), F.Command.Twocell.CompositeMap = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          return P(this, n2), t3.call(this, e4, r2);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\xcompositemap[` + this.hops + `]` + this.maybeDisplace.getOrElse(`{}`);
        } }]), n2;
      })(F.Command.Twocell.Hops2cell), F.Command.Twocell.Switch = function e3() {
        P(this, e3);
      }, F.Command.Twocell.Switch.UpperLabel = (function() {
        function e3(t3) {
          P(this, e3), this.label = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `^` + this.label;
        } }]), e3;
      })(), F.Command.Twocell.Switch.LowerLabel = (function() {
        function e3(t3) {
          P(this, e3), this.label = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `_` + this.label;
        } }]), e3;
      })(), F.Command.Twocell.Switch.SetCurvature = (function() {
        function e3(t3) {
          P(this, e3), this.nudge = t3;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.nudge.toString();
        } }]), e3;
      })(), F.Command.Twocell.Switch.DoNotSetCurvedArrows = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\omit`;
        } }]), e3;
      })(), F.Command.Twocell.Switch.PlaceModMapObject = (function() {
        function e3() {
          P(this, e3);
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~!`;
        } }]), e3;
      })(), F.Command.Twocell.Switch.ChangeHeadTailObject = (function() {
        function e3(t3, n2) {
          P(this, e3), this.what = t3, this.object = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~` + this.what + `{` + this.object + `}`;
        } }]), e3;
      })(), F.Command.Twocell.Switch.ChangeCurveObject = (function() {
        function e3(t3, n2, r2) {
          P(this, e3), this.what = t3, this.spacer = n2, this.maybeObject = r2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `~` + this.what + `{` + this.spacer + (this.maybeObject.isDefined ? `~**` + this.maybeObject.get : ``) + `}`;
        } }]), e3;
      })(), F.Command.Twocell.Label = (function() {
        function e3(t3, n2) {
          P(this, e3), this.maybeNudge = t3, this.labelObject = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return this.maybeNudge.toString() + this.labelObject;
        } }]), e3;
      })(), F.Command.Twocell.Nudge = function e3() {
        P(this, e3);
      }, F.Command.Twocell.Nudge.Number = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).number = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `<` + this.number + `>`;
        } }]), n2;
      })(F.Command.Twocell.Nudge), F.Command.Twocell.Nudge.Omit = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2() {
          return P(this, n2), t3.call(this);
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `<\\omit>`;
        } }]), n2;
      })(F.Command.Twocell.Nudge), F.Command.Twocell.Arrow = function e3() {
        P(this, e3);
      }, F.Command.Twocell.Arrow.WithOrientation = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          var i2;
          return P(this, n2), (i2 = t3.call(this)).tok = e4, i2.labelObject = r2, i2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `{[` + this.tok + `] ` + this.labelObject + `}`;
        } }]), n2;
      })(F.Command.Twocell.Arrow), F.Command.Twocell.Arrow.WithPosition = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2) {
          var i2;
          return P(this, n2), (i2 = t3.call(this)).nudge = e4, i2.labelObject = r2, i2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `{[` + this.nudge + `] ` + this.labelObject + `}`;
        } }]), n2;
      })(F.Command.Twocell.Arrow), F.Command.Newdir = (function() {
        function e3(t3, n2) {
          P(this, e3), this.dirMain = t3, this.compositeObject = n2;
        }
        return j(e3, [{ key: `toString`, value: function() {
          return `\\newdir{` + this.dirMain + `}{` + this.compositeObject + `}`;
        } }]), e3;
      })(), F.Pos.Xyimport = function e3() {
        P(this, e3);
      }, F.Pos.Xyimport.TeXCommand = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2, a2, o2) {
          var s2;
          return P(this, n2), (s2 = t3.call(this)).width = e4, s2.height = r2, s2.xOffset = i2, s2.yOffset = a2, s2.graphics = o2, s2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\xyimport(` + this.width + `, ` + this.height + `)(` + this.xOffset + `, ` + this.yOffset + `){` + this.graphics + `}`;
        } }]), n2;
      })(F.Pos.Xyimport), F.Pos.Xyimport.Graphics = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4, r2, i2, a2, o2) {
          var s2;
          return P(this, n2), (s2 = t3.call(this)).width = e4, s2.height = r2, s2.xOffset = i2, s2.yOffset = a2, s2.graphics = o2, s2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `\\xyimport(` + this.width + `, ` + this.height + `)(` + this.xOffset + `, ` + this.yOffset + `){` + this.graphics + `}`;
        } }]), n2;
      })(F.Pos.Xyimport), F.Command.Includegraphics = (function() {
        function e3(t3, n2, r2) {
          P(this, e3), this.isClipped = t3, this.attributeList = n2, this.filepath = r2;
        }
        return j(e3, [{ key: `isIncludegraphics`, get: function() {
          return true;
        } }, { key: `toString`, value: function() {
          return `\\includegraphics` + (this.isClipped ? `*` : ``) + this.attributeList.mkString(`[`, `,`, `]`) + `{` + this.filepath + `}`;
        } }]), e3;
      })(), F.Command.Includegraphics.Attr = function e3() {
        P(this, e3);
      }, F.Command.Includegraphics.Attr.Width = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).dimen = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `width=` + this.dimen;
        } }]), n2;
      })(F.Command.Includegraphics.Attr), F.Command.Includegraphics.Attr.Height = (function(e3) {
        M(n2, e3);
        var t3 = N(n2);
        function n2(e4) {
          var r2;
          return P(this, n2), (r2 = t3.call(this)).dimen = e4, r2;
        }
        return j(n2, [{ key: `toString`, value: function() {
          return `height=` + this.dimen;
        } }]), n2;
      })(F.Command.Includegraphics.Attr);
      var I = k.fun, Ue = k.elem, We = function(e3) {
        return I(k.elem(e3));
      }, L = k.literal, Ge = k.regex, Ke = k.regexLiteral, R = function(e3) {
        return I(k.literal(e3));
      }, qe = k.seq, z = k.or, Je = function(e3) {
        return k.lazyParser(e3)().rep();
      }, Ye = function(e3) {
        return k.lazyParser(e3)().rep1();
      }, Xe = function(e3) {
        return k.lazyParser(e3)().opt();
      }, Ze = k.success, B = function(e3) {
        return function() {
          var t3 = e3.memo;
          return t3 === void 0 && (t3 = e3.memo = e3()), t3;
        };
      }, V = new k(), Qe = { xy: B((function() {
        return V.posDecor().to((function(e3) {
          return e3;
        }));
      })), xybox: B((function() {
        return L(`{`).andr(V.posDecor).andl(R(`}`)).to((function(e3) {
          return e3;
        }));
      })), xymatrixbox: B((function() {
        return V.xymatrix().to((function(e3) {
          return new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty), new F.Decor(O.empty.append(e3)));
        }));
      })), posDecor: B((function() {
        return qe(V.pos, V.decor).to((function(e3) {
          return new F.PosDecor(e3.head, e3.tail);
        }));
      })), pos: B((function() {
        return qe(V.coord, Je(V.pos2)).to((function(e3) {
          return new F.Pos.Coord(e3.head, e3.tail);
        }));
      })), nonemptyPos: B((function() {
        return z(qe(V.nonemptyCoord, Je(V.pos2)), qe(V.coord, Ye(V.pos2))).to((function(e3) {
          return new F.Pos.Coord(e3.head, e3.tail);
        }));
      })), pos2: B((function() {
        return z(L(`+`).andr(V.coord).to((function(e3) {
          return new F.Pos.Plus(e3);
        })), L(`-`).andr(V.coord).to((function(e3) {
          return new F.Pos.Minus(e3);
        })), L(`!`).andr(V.coord).to((function(e3) {
          return new F.Pos.Skew(e3);
        })), L(`.`).andr(V.coord).to((function(e3) {
          return new F.Pos.Cover(e3);
        })), L(`,`).andr(V.coord).to((function(e3) {
          return new F.Pos.Then(e3);
        })), L(`;`).andr(V.coord).to((function(e3) {
          return new F.Pos.SwapPAndC(e3);
        })), L(`::`).andr(V.coord).to((function(e3) {
          return new F.Pos.SetYBase(e3);
        })), L(`:`).andr(V.coord).to((function(e3) {
          return new F.Pos.SetBase(e3);
        })), L(`**`).andr(V.object).to((function(e3) {
          return new F.Pos.ConnectObject(e3);
        })), L(`*`).andr(V.object).to((function(e3) {
          return new F.Pos.DropObject(e3);
        })), L(`?`).andr(V.place).to((function(e3) {
          return new F.Pos.Place(e3);
        })), L(`@+`).andr(V.coord).to((function(e3) {
          return new F.Pos.PushCoord(e3);
        })), L(`@-`).andr(V.coord).to((function(e3) {
          return new F.Pos.EvalCoordThenPop(e3);
        })), L(`@=`).andr(V.coord).to((function(e3) {
          return new F.Pos.LoadStack(e3);
        })), L(`@@`).andr(V.coord).to((function(e3) {
          return new F.Pos.DoCoord(e3);
        })), L(`@i`).to((function() {
          return new F.Pos.InitStack();
        })), L(`@(`).to((function() {
          return new F.Pos.EnterFrame();
        })), L(`@)`).to((function() {
          return new F.Pos.LeaveFrame();
        })), L(`=:`).andr(R(`"`)).andr(V.id).andl(We(`"`)).to((function(e3) {
          return new F.Pos.SaveBase(e3);
        })), L(`=@`).andr(R(`"`)).andr(V.id).andl(We(`"`)).to((function(e3) {
          return new F.Pos.SaveStack(e3);
        })), L(`=`).andr(R(`"`)).andr(V.id).andl(We(`"`)).to((function(e3) {
          return new F.Pos.SavePos(e3);
        })), L(`=`).andr(V.nonemptyCoord).andl(R(`"`)).and(V.id).andl(We(`"`)).to((function(e3) {
          return new F.Pos.SaveMacro(e3.head, e3.tail);
        })), V.xyimport);
      })), coord: B((function() {
        return z(V.nonemptyCoord, Ze(`empty`).to((function() {
          return new F.Coord.C();
        })));
      })), nonemptyCoord: B((function() {
        return z(L(`c`).to((function() {
          return new F.Coord.C();
        })), L(`p`).to((function() {
          return new F.Coord.P();
        })), L(`x`).to((function() {
          return new F.Coord.X();
        })), L(`y`).to((function() {
          return new F.Coord.Y();
        })), V.vector().to((function(e3) {
          return new F.Coord.Vector(e3);
        })), L(`"`).andr(V.id).andl(We(`"`)).to((function(e3) {
          return new F.Coord.Id(e3);
        })), L(`{`).andr(V.posDecor).andl(R(`}`)).to((function(e3) {
          return new F.Coord.Group(e3);
        })), L(`s`).andr(I(Ke(/^\d/))).to((function(e3) {
          return new F.Coord.StackPosition(parseInt(e3));
        })), L(`s`).andr(R(`{`)).and(V.nonnegativeNumber).andl(R(`}`)).to((function(e3) {
          return new F.Coord.StackPosition(e3);
        })), L(`[`).andr(I(Xe(L(`"`).andr(V.id).andl(We(`"`))).to((function(e3) {
          return e3.getOrElse(``);
        })))).and(V.number).andl(R(`,`)).and(V.number).andl(R(`]`)).to((function(e3) {
          return new F.Coord.DeltaRowColumn(e3.head.head, e3.head.tail, e3.tail);
        })), L(`[`).andr(I(Xe(L(`"`).andr(V.id).andl(We(`"`))).to((function(e3) {
          return e3.getOrElse(``);
        })))).and(I(Je(Ge(/^[lrud]/)))).andl(R(`]`)).to((function(e3) {
          return new F.Coord.Hops(e3.head, e3.tail);
        })), L(`[`).andr(I(Xe(L(`"`).andr(V.id).andl(We(`"`))).to((function(e3) {
          return e3.getOrElse(``);
        })))).and(I(Ye(Ge(/^[lrud]/)))).and(V.place).andl(R(`]`)).to((function(e3) {
          return new F.Coord.DeltaRowColumn(e3.head.head, e3.head.tail, new F.Pos.Place(e3.tail));
        })));
      })), vector: B((function() {
        return z(L(`(`).andr(V.factor).andl(R(`,`)).and(V.factor).andl(R(`)`)).to((function(e3) {
          return new F.Vector.InCurBase(e3.head, e3.tail);
        })), L(`<`).andr(V.dimen).andl(R(`,`)).and(V.dimen).andl(R(`>`)).to((function(e3) {
          return new F.Vector.Abs(e3.head, e3.tail);
        })), L(`<`).andr(V.dimen).andl(R(`>`)).to((function(e3) {
          return new F.Vector.Abs(e3, e3);
        })), L(`a`).andr(R(`(`)).andr(V.number).andl(R(`)`)).to((function(e3) {
          return new F.Vector.Angle(e3);
        })), L(`/`).andr(V.direction).and(V.looseDimen).andl(R(`/`)).to((function(e3) {
          return new F.Vector.Dir(e3.head, e3.tail);
        })), L(`0`).to((function(e3) {
          return new F.Vector.Abs(`0mm`, `0mm`);
        })), (function() {
          return V.corner().and(I(k.opt(I(L(`(`).andr(V.factor).andl(R(`)`)))).to((function(e3) {
            return e3.getOrElse(1);
          })))).to((function(e3) {
            return new F.Vector.Corner(e3.head, e3.tail);
          }));
        }));
      })), corner: B((function() {
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
      })), place: B((function() {
        return z(L(`<`).andr(V.place).to((function(e3) {
          return new F.Place(1, 0, void 0, void 0).compound(e3);
        })), L(`>`).andr(V.place).to((function(e3) {
          return new F.Place(0, 1, void 0, void 0).compound(e3);
        })), L(`(`).andr(V.factor).andl(R(`)`)).and(V.place).to((function(e3) {
          return new F.Place(0, 0, new F.Place.Factor(e3.head), void 0).compound(e3.tail);
        })), L(`!`).andr(R(`{`)).andr(V.pos).andl(R(`}`)).and(V.slide).to((function(e3) {
          return new F.Place(0, 0, new F.Place.Intercept(e3.head), e3.tail);
        })), (function() {
          return V.slide().to((function(e3) {
            return new F.Place(0, 0, void 0, e3);
          }));
        }));
      })), slide: B((function() {
        return z(L(`/`).andr(V.dimen).andl(R(`/`)).to((function(e3) {
          return new F.Slide(new y.Some(e3));
        })), Ze(`no slide`).to((function() {
          return new F.Slide(y.empty);
        })));
      })), factor: B(I(Ke(/^[+\-]?(\d+(\.\d*)?|\d*\.\d+)/).to((function(e3) {
        return parseFloat(e3);
      })))), number: B(I(Ke(/^[+\-]?\d+/).to((function(e3) {
        return parseInt(e3);
      })))), nonnegativeNumber: B(I(Ke(/^\d+/).to((function(e3) {
        return parseInt(e3);
      })))), unit: B(I(Ke(/^(em|ex|px|pt|pc|in|cm|mm|mu)/).to((function(e3) {
        return e3;
      })))), dimen: B((function() {
        return V.factor().and(V.unit).to((function(e3) {
          return e3.head.toString() + e3.tail;
        }));
      })), looseDimen: B((function() {
        return V.looseFactor().and(V.unit).to((function(e3) {
          return e3.head.toString() + e3.tail;
        }));
      })), looseFactor: B(I(z(Ke(/^(\d \d*(\.\d*))/).to((function(e3) {
        return parseFloat(e3.replace(/ /, ``));
      })), Ke(/^[+\-]?(\d+(\.\d*)?|\d*\.\d+)/).to((function(e3) {
        return parseFloat(e3);
      }))))), id: B(I(Ge(/^[^"]+/))), object: B((function() {
        return z(Je(V.modifier).and(V.objectbox).to((function(e3) {
          return new F.Object(e3.head, e3.tail);
        })));
      })), objectbox: B((function() {
        return z(V.mathText, L(`@`).andr(V.dir), L(`\\dir`).andr(V.dir), L(`\\cir`).andr(V.cirRadius).andl(R(`{`)).and(V.cir).andl(R(`}`)).to((function(e3) {
          return new F.ObjectBox.Cir(e3.head, e3.tail);
        })), L(`\\frm`).andr(V.frameRadius).andl(R(`{`)).and(V.frameMain).andl(R(`}`)).to((function(e3) {
          return new F.ObjectBox.Frame(e3.head, e3.tail);
        })), L(`\\object`).andr(V.object).to((function(e3) {
          return new F.ObjectBox.WrapUpObject(e3);
        })), L(`\\composite`).and(R(`{`)).andr(V.compositeObject).andl(R(`}`)).to((function(e3) {
          return new F.ObjectBox.CompositeObject(e3);
        })), L(`\\xybox`).and(R(`{`)).andr(V.posDecor).andl(R(`}`)).to((function(e3) {
          return new F.ObjectBox.Xybox(e3);
        })), L(`\\xymatrix`).andr(V.xymatrix).to((function(e3) {
          return new F.ObjectBox.Xymatrix(e3);
        })), V.txt, V.curve, Ge(/^(\\[a-zA-Z@][a-zA-Z0-9@]+)/).andl(R(`{`)).and(V.text).andl(R(`}`)).and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail;
          return V.toMath(t3.head + `{` + t3.tail + `}`, n2);
        })));
      })), compositeObject: B((function() {
        return V.object().and(I(Je(L(`*`).andr(V.object)))).to((function(e3) {
          return e3.tail.prepend(e3.head);
        }));
      })), mathText: B((function() {
        return L(`{`).andr(V.text).andl(We(`}`)).and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail;
          return V.toMath(`\\hbox{$\\objectstyle{` + t3 + `}$}`, n2);
        }));
      })), toMath: function(e3, t3) {
        var n2 = t3(e3);
        return new F.ObjectBox.Text(n2);
      }, textNodeCreator: B((function() {
        return new k.Parser((function(e3) {
          return new k.Success(e3.context.createTextNode, e3);
        }));
      })), text: B((function() {
        return Ge(/^[^{}\\%]*/).and((function() {
          return z(Ge(/^(\\\{|\\\}|\\%|\\)/).to((function(e3) {
            return e3;
          })), Ue(`{`).andr(V.text).andl(We(`}`)).to((function(e3) {
            return `{` + e3 + `}`;
          })), Ge(/^%[^\r\n]*(\r\n|\r|\n)?/).to((function(e3) {
            return ` `;
          }))).and(I(Ge(/^[^{}\\%]*/))).rep().to((function(e3) {
            var t3 = ``;
            return e3.foreach((function(e4) {
              t3 += e4.head + e4.tail;
            })), t3;
          }));
        })).to((function(e3) {
          return e3.head + e3.tail;
        }));
      })), txt: B((function() {
        return L(`\\txt`).andr(V.txtWidth).and(I(Ge(/^(\\[a-zA-Z@][a-zA-Z0-9@]+)?/))).andl(R(`{`)).and(V.text).andl(R(`}`)).and(V.textNodeCreator).to((function(e3) {
          var t3, n2 = e3.head, r2 = e3.tail, i2 = n2.head.head, a2 = n2.head.tail, o2 = n2.tail, s2 = o2.split(`\\\\`);
          if (s2.length <= 1) t3 = a2 + `{\\hbox{` + o2 + `}}`;
          else {
            t3 = `\\hbox{$\\begin{array}{c}
`;
            for (var c2 = 0; c2 < s2.length; c2++) t3 += a2 + `{\\hbox{` + s2[c2].replace(/(^[\r\n\s]+)|([\r\n\s]+$)/g, ``) + `}}`, c2 != s2.length - 1 && (t3 += `\\\\
`);
            t3 += `\\end{array}$}`;
          }
          return new F.ObjectBox.Txt(i2, V.toMath(t3, r2));
        }));
      })), txtWidth: B((function() {
        return z(L(`<`).andr(V.dimen).andl(R(`>`)).to((function(e3) {
          return new F.Vector.Abs(e3, e3);
        })).to((function(e3) {
          return new F.ObjectBox.Txt.Width.Vector(e3);
        })), Ze(`default`).to((function() {
          return new F.ObjectBox.Txt.Width.Default();
        })));
      })), dir: B((function() {
        return Ke(/^[\^_0123]/).opt().andl(R(`{`)).and(V.dirMain).andl(R(`}`)).to((function(e3) {
          return new F.ObjectBox.Dir(e3.head.getOrElse(``), e3.tail);
        }));
      })), dirMain: B((function() {
        return Ge(/^(-|\.|~|>|<|\(|\)|`|'|\||\*|\+|x|\/|o|=|:|[a-zA-Z@ ])+/).opt().to((function(e3) {
          return e3.getOrElse(``);
        }));
      })), cirRadius: B((function() {
        return z(V.vector().to((function(e3) {
          return new F.ObjectBox.Cir.Radius.Vector(e3);
        })), Ze(`default`).to((function() {
          return new F.ObjectBox.Cir.Radius.Default();
        })));
      })), frameRadius: B((function() {
        return z(V.frameRadiusVector().to((function(e3) {
          return new F.ObjectBox.Frame.Radius.Vector(e3);
        })), Ze(`default`).to((function() {
          return new F.ObjectBox.Frame.Radius.Default();
        })));
      })), frameRadiusVector: B((function() {
        return z(L(`<`).andr(V.dimen).andl(R(`,`)).and(V.dimen).andl(R(`>`)).to((function(e3) {
          return new F.Vector.Abs(e3.head, e3.tail);
        })), L(`<`).andr(V.dimen).andl(R(`>`)).to((function(e3) {
          return new F.Vector.Abs(e3, e3);
        })));
      })), frameMain: B((function() {
        return Ge(/^(((_|\^)?(\\\{|\\\}|\(|\)))|[\-=oe,\.\*]*)/);
      })), cir: B((function() {
        return z(V.nonemptyCir, Ze(`full`).to((function() {
          return new F.ObjectBox.Cir.Cir.Full();
        })));
      })), nonemptyCir: B((function() {
        return V.diag().and(I(Ke(/^[_\^]/))).and(V.diag).to((function(e3) {
          return new F.ObjectBox.Cir.Cir.Segment(e3.head.head, e3.head.tail, e3.tail);
        }));
      })), curve: B((function() {
        return L(`\\crv`).andr(V.curveModifier).andl(R(`{`)).and(V.curveObject).and(V.curvePoslist).andl(R(`}`)).to((function(e3) {
          return new F.ObjectBox.Curve(e3.head.head, e3.head.tail, e3.tail);
        }));
      })), curveModifier: B((function() {
        return Je(I(L(`~`).andr(V.curveOption)));
      })), curveOption: B((function() {
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
      })), curveObject: B((function() {
        return Je(z(L(`~*`).andr(V.object).to((function(e3) {
          return new F.ObjectBox.Curve.Object.Drop(e3);
        })), L(`~**`).andr(V.object).to((function(e3) {
          return new F.ObjectBox.Curve.Object.Connect(e3);
        }))));
      })), curvePoslist: B((function() {
        return z(L(`&`).andr(V.curvePoslist2).to((function(e3) {
          return e3.prepend(new F.ObjectBox.Curve.PosList.CurPos());
        })), L(`~@`).andr(R(`&`)).andr(V.curvePoslist2).to((function(e3) {
          return e3.prepend(new F.ObjectBox.Curve.PosList.AddStack());
        })), L(`~@`).to((function() {
          return O.empty.prepend(new F.ObjectBox.Curve.PosList.AddStack());
        })), V.pos().andl(R(`&`)).and(V.curvePoslist2).to((function(e3) {
          return e3.tail.prepend(new F.ObjectBox.Curve.PosList.Pos(e3.head));
        })), V.nonemptyPos().to((function(e3) {
          return O.empty.prepend(new F.ObjectBox.Curve.PosList.Pos(e3));
        })), Ze(`empty`).to((function() {
          return O.empty;
        })));
      })), curvePoslist2: B((function() {
        return z(L(`&`).andr(V.curvePoslist2).to((function(e3) {
          return e3.prepend(new F.ObjectBox.Curve.PosList.CurPos());
        })), L(`~@`).andr(R(`&`)).andr(V.curvePoslist2).to((function(e3) {
          return e3.prepend(new F.ObjectBox.Curve.PosList.AddStack());
        })), L(`~@`).to((function() {
          return O.empty.prepend(new F.ObjectBox.Curve.PosList.AddStack());
        })), V.nonemptyPos().andl(R(`&`)).and(V.curvePoslist2).to((function(e3) {
          return e3.tail.prepend(new F.ObjectBox.Curve.PosList.Pos(e3.head));
        })), V.nonemptyPos().to((function(e3) {
          return O.empty.prepend(new F.ObjectBox.Curve.PosList.Pos(e3));
        })), Ze(`empty`).to((function() {
          return O.empty.prepend(new F.ObjectBox.Curve.PosList.CurPos());
        })));
      })), modifier: B((function() {
        return z(L(`!`).andr(V.vector).to((function(e3) {
          return new F.Modifier.Vector(e3);
        })), L(`!`).to((function(e3) {
          return new F.Modifier.RestoreOriginalRefPoint();
        })), L(`[`).andr(V.shape).andl(R(`]`)).to((function(e3) {
          return e3;
        })), L(`i`).to((function(e3) {
          return new F.Modifier.Invisible();
        })), L(`h`).to((function(e3) {
          return new F.Modifier.Hidden();
        })), V.addOp().and(V.size).to((function(e3) {
          return new F.Modifier.AddOp(e3.head, e3.tail);
        })), V.nonemptyDirection().to((function(e3) {
          return new F.Modifier.Direction(e3);
        })));
      })), addOp: B((function() {
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
      })), size: B((function() {
        return z((function() {
          return V.vector().to((function(e3) {
            return new F.Modifier.AddOp.VactorSize(e3);
          }));
        }), Ze(`default size`).to((function() {
          return new F.Modifier.AddOp.DefaultSize();
        })));
      })), shape: B((function() {
        return z(L(`.`).to((function() {
          return new F.Modifier.Shape.Point();
        })), V.frameShape, V.alphabets().to((function(e3) {
          return new F.Modifier.Shape.Alphabets(e3);
        })), L(`=`).andr(V.alphabets).to((function(e3) {
          return new F.Modifier.Shape.DefineShape(e3);
        })), Ze(`rect`).to((function() {
          return new F.Modifier.Shape.Rect();
        })));
      })), frameShape: B((function() {
        return L(`F`).andr(V.frameMain).and(I(Je(L(`:`).andr(I(z(V.frameRadiusVector().to((function(e3) {
          return new F.Modifier.Shape.Frame.Radius(e3);
        })), V.colorName().to((function(e3) {
          return new F.Modifier.Shape.Frame.Color(e3);
        })))))))).to((function(e3) {
          var t3 = e3.head;
          return t3 === `` && (t3 = `-`), new F.Modifier.Shape.Frame(t3, e3.tail);
        }));
      })), alphabets: B((function() {
        return Ge(/^([a-zA-Z]+)/);
      })), colorName: B((function() {
        return Ge(/^([a-zA-Z][a-zA-Z0-9]*)/);
      })), direction: B((function() {
        return qe(V.direction0, Je(V.direction1)).to((function(e3) {
          return new F.Direction.Compound(e3.head, e3.tail);
        }));
      })), direction0: B((function() {
        return z(V.direction2, V.diag().to((function(e3) {
          return new F.Direction.Diag(e3);
        })));
      })), direction1: B((function() {
        return z(L(`:`).andr(V.vector).to((function(e3) {
          return new F.Direction.RotVector(e3);
        })), L(`_`).to((function(e3) {
          return new F.Direction.RotAntiCW();
        })), L(`^`).to((function(e3) {
          return new F.Direction.RotCW();
        })));
      })), direction2: B((function() {
        return z(L(`v`).andr(V.vector).to((function(e3) {
          return new F.Direction.Vector(e3);
        })), L(`q`).andr(R(`{`)).andr(V.posDecor).andl(R(`}`)).to((function(e3) {
          return new F.Direction.ConstructVector(e3);
        })));
      })), nonemptyDirection: B((function() {
        return z(qe(V.nonemptyDirection0, Je(V.direction1)), qe(V.direction0, Ye(V.direction1))).to((function(e3) {
          return new F.Direction.Compound(e3.head, e3.tail);
        }));
      })), nonemptyDirection0: B((function() {
        return z(V.direction2, V.nonemptyDiag().to((function(e3) {
          return new F.Direction.Diag(e3);
        })));
      })), diag: B((function() {
        return z(V.nonemptyDiag, Ze(`empty`).to((function(e3) {
          return new F.Diag.Default();
        })));
      })), nonemptyDiag: B((function() {
        return z(Ke(/^(ld|dl)/).to((function(e3) {
          return new F.Diag.LD();
        })), Ke(/^(rd|dr)/).to((function(e3) {
          return new F.Diag.RD();
        })), Ke(/^(lu|ul)/).to((function(e3) {
          return new F.Diag.LU();
        })), Ke(/^(ru|ur)/).to((function(e3) {
          return new F.Diag.RU();
        })), L(`l`).to((function(e3) {
          return new F.Diag.L();
        })), L(`r`).to((function(e3) {
          return new F.Diag.R();
        })), L(`d`).to((function(e3) {
          return new F.Diag.D();
        })), L(`u`).to((function(e3) {
          return new F.Diag.U();
        })));
      })), decor: B((function() {
        return V.command().rep().to((function(e3) {
          return new F.Decor(e3);
        }));
      })), command: B((function() {
        return z(L(`\\ar`).andr(I(Je(V.arrowForm))).and(V.path).to((function(e3) {
          return new F.Command.Ar(e3.head, e3.tail);
        })), L(`\\xymatrix`).andr(V.xymatrix), L(`\\PATH`).andr(V.path).to((function(e3) {
          return new F.Command.Path(e3);
        })), L(`\\afterPATH`).andr(R(`{`)).andr(V.decor).andl(R(`}`)).and(V.path).to((function(e3) {
          return new F.Command.AfterPath(e3.head, e3.tail);
        })), L(`\\save`).andr(V.pos).to((function(e3) {
          return new F.Command.Save(e3);
        })), L(`\\restore`).to((function() {
          return new F.Command.Restore();
        })), L(`\\POS`).andr(V.pos).to((function(e3) {
          return new F.Command.Pos(e3);
        })), L(`\\afterPOS`).andr(R(`{`)).andr(V.decor).andl(R(`}`)).and(V.pos).to((function(e3) {
          return new F.Command.AfterPos(e3.head, e3.tail);
        })), L(`\\drop`).andr(V.object).to((function(e3) {
          return new F.Command.Drop(e3);
        })), L(`\\connect`).andr(V.object).to((function(e3) {
          return new F.Command.Connect(e3);
        })), L(`\\relax`).to((function() {
          return new F.Command.Relax();
        })), L(`\\xyignore`).andr(R(`{`)).andr(V.pos).and(V.decor).andl(R(`}`)).to((function(e3) {
          return new F.Command.Ignore(e3.head, e3.tail);
        })), L(`\\xyshowAST`).andr(R(`{`)).andr(V.pos).and(V.decor).andl(R(`}`)).to((function(e3) {
          return new F.Command.ShowAST(e3.head, e3.tail);
        })), V.twocellCommand);
      })), arrowForm: B((function() {
        return z(L(`@`).andr(I(Ge(/^([\-\.~=:])/))).to((function(e3) {
          return new F.Command.Ar.Form.ChangeStem(e3);
        })), L(`@`).andr(R(`!`)).to((function(e3) {
          return new F.Command.Ar.Form.DashArrowStem();
        })), L(`@`).andr(R(`/`)).andr(V.direction).and(I(Xe(V.looseDimen))).andl(R(`/`)).to((function(e3) {
          return new F.Command.Ar.Form.CurveArrow(e3.head, e3.tail.getOrElse(`.5pc`));
        })), L(`@`).andr(R(`(`)).andr(V.direction).andl(R(`,`)).and(V.direction).andl(R(`)`)).to((function(e3) {
          return new F.Command.Ar.Form.CurveFitToDirection(e3.head, e3.tail);
        })), L(`@`).andr(R("`")).andr(V.coord).to((function(e3) {
          return new F.Command.Ar.Form.CurveWithControlPoints(e3);
        })), L(`@`).andr(R(`[`)).andr(V.shape).andl(R(`]`)).to((function(e3) {
          return new F.Command.Ar.Form.AddShape(e3);
        })), L(`@`).andr(R(`*`)).andr(R(`{`)).andr(I(Je(V.modifier))).andl(R(`}`)).to((function(e3) {
          return new F.Command.Ar.Form.AddModifiers(e3);
        })), L(`@`).andr(R(`<`)).andr(V.dimen).andl(R(`>`)).to((function(e3) {
          return new F.Command.Ar.Form.Slide(e3);
        })), L(`|`).andr(V.anchor).and(V.it).to((function(e3) {
          return new F.Command.Ar.Form.LabelAt(e3.head, e3.tail);
        })), L(`^`).andr(V.anchor).and(V.it).to((function(e3) {
          return new F.Command.Ar.Form.LabelAbove(e3.head, e3.tail);
        })), L(`_`).andr(V.anchor).and(V.it).to((function(e3) {
          return new F.Command.Ar.Form.LabelBelow(e3.head, e3.tail);
        })), L(`@`).andr(R(`?`)).to((function() {
          return new F.Command.Ar.Form.ReverseAboveAndBelow();
        })), L(`@`).andr(I(Ge(/^([\^_0123])/).opt())).and(I(Xe(V.tipConnTip))).to((function(e3) {
          var t3 = e3.head.getOrElse(``);
          if (e3.tail.isDefined) {
            var n2 = e3.tail.get;
            return new F.Command.Ar.Form.BuildArrow(t3, n2.tail, n2.stem, n2.head);
          }
          return new F.Command.Ar.Form.ChangeVariant(t3);
        })));
      })), tipConnTip: B((function() {
        return L(`{`).andr(I(Xe(V.nonemptyTip))).and(I(Xe(V.nonemptyConn))).and(I(Xe(V.nonemptyTip))).andl(R(`}`)).to((function(e3) {
          var t3, n2, r2, i2 = e3.head.head, a2 = e3.head.tail, o2 = e3.tail, s2 = new F.Command.Ar.Form.Tip.Tipchars(``);
          return a2.isDefined || o2.isDefined ? (t3 = i2.getOrElse(s2), n2 = a2.getOrElse(new F.Command.Ar.Form.Conn.Connchars(``)), r2 = o2.getOrElse(s2)) : i2.isDefined ? (t3 = s2, n2 = new F.Command.Ar.Form.Conn.Connchars(`-`), r2 = i2.getOrElse(s2)) : (t3 = s2, n2 = new F.Command.Ar.Form.Conn.Connchars(``), r2 = s2), { tail: t3, stem: n2, head: r2 };
        }));
      })), nonemptyTip: B((function() {
        return z(Ge(/^([<>()|'`+\/a-zA-Z ]+)/).to((function(e3) {
          return new F.Command.Ar.Form.Tip.Tipchars(e3);
        })), L(`*`).andr(V.object).to((function(e3) {
          return new F.Command.Ar.Form.Tip.Object(e3);
        })), V.dir().to((function(e3) {
          return new F.Command.Ar.Form.Tip.Dir(e3);
        })));
      })), nonemptyConn: B((function() {
        return z(Ge(/^([\-\.~=:]+)/).to((function(e3) {
          return new F.Command.Ar.Form.Conn.Connchars(e3);
        })), L(`*`).andr(V.object).to((function(e3) {
          return new F.Command.Ar.Form.Conn.Object(e3);
        })), V.dir().to((function(e3) {
          return new F.Command.Ar.Form.Conn.Dir(e3);
        })));
      })), path: B((function() {
        return V.path2(O.empty).to((function(e3) {
          return new F.Command.Path.Path(e3);
        }));
      })), path2: function(e3) {
        var t3 = B((function() {
          return V.path2(e3);
        }));
        return z(V.path3().and(t3).to((function(e4) {
          return e4.tail.prepend(e4.head);
        })), qe(`~`, `{`, t3, `}`).to((function(e4) {
          return e4.head.tail;
        })).into((function(e4) {
          return V.path2(e4);
        })), V.segment().to((function(e4) {
          return O.empty.prepend(new F.Command.Path.LastSegment(e4));
        })), Ze(e3).to((function(e4) {
          return e4;
        })));
      }, path3: B((function() {
        return z(qe(`~`, `=`, `{`, V.posDecor, `}`).to((function(e3) {
          return new F.Command.Path.SetBeforeAction(e3.head.tail);
        })), qe(`~`, `/`, `{`, V.posDecor, `}`).to((function(e3) {
          return new F.Command.Path.SetAfterAction(e3.head.tail);
        })), qe(`~`, `<`, `{`, V.labels, `}`).to((function(e3) {
          return new F.Command.Path.AddLabelNextSegmentOnly(e3.head.tail);
        })), qe(`~`, `>`, `{`, V.labels, `}`).to((function(e3) {
          return new F.Command.Path.AddLabelLastSegmentOnly(e3.head.tail);
        })), qe(`~`, `+`, `{`, V.labels, `}`).to((function(e3) {
          return new F.Command.Path.AddLabelEverySegment(e3.head.tail);
        })), qe(`'`, V.segment).to((function(e3) {
          return new F.Command.Path.StraightSegment(e3.tail);
        })), qe("`", V.turn, V.segment).to((function(e3) {
          return new F.Command.Path.TurningSegment(e3.head.tail, e3.tail);
        })));
      })), turn: B((function() {
        return z(V.nonemptyCir().and(V.turnRadius).to((function(e3) {
          return new F.Command.Path.Turn.Cir(e3.head, e3.tail);
        })), V.diag().and(V.turnRadius).to((function(e3) {
          return new F.Command.Path.Turn.Diag(e3.head, e3.tail);
        })));
      })), turnRadius: B((function() {
        return z(L(`/`).andr(V.dimen).to((function(e3) {
          return new F.Command.Path.TurnRadius.Dimen(e3);
        })), Ze(`default`).to((function() {
          return new F.Command.Path.TurnRadius.Default();
        })));
      })), segment: B((function() {
        return V.nonemptyPos().and(V.pathSlide).and(V.labels).to((function(e3) {
          return new F.Command.Path.Segment(e3.head.head, e3.head.tail, e3.tail);
        }));
      })), pathSlide: B((function() {
        return z(L(`<`).andr(V.dimen).andl(R(`>`)).to((function(e3) {
          return new F.Slide(new y.Some(e3));
        })), Ze(`no slide`).to((function() {
          return new F.Slide(y.empty);
        })));
      })), labels: B((function() {
        return V.label().rep().to((function(e3) {
          return new F.Command.Path.Labels(e3);
        }));
      })), label: B((function() {
        return z(qe(`^`, V.anchor, V.it, V.alias).to((function(e3) {
          return new F.Command.Path.Label.Above(new F.Pos.Place(e3.head.head.tail), e3.head.tail, e3.tail);
        })), qe(`_`, V.anchor, V.it, V.alias).to((function(e3) {
          return new F.Command.Path.Label.Below(new F.Pos.Place(e3.head.head.tail), e3.head.tail, e3.tail);
        })), qe(`|`, V.anchor, V.it, V.alias).to((function(e3) {
          return new F.Command.Path.Label.At(new F.Pos.Place(e3.head.head.tail), e3.head.tail, e3.tail);
        })));
      })), anchor: B((function() {
        return z(L(`-`).andr(V.anchor).to((function(e3) {
          return new F.Place(1, 1, new F.Place.Factor(0.5), void 0).compound(e3);
        })), V.place);
      })), it: B((function() {
        return Je(L(`[`).andr(V.shape).andl(R(`]`)).to((function(e3) {
          return e3;
        }))).and(V.it2).to((function(e3) {
          return new F.Object(e3.head.concat(e3.tail.modifiers), e3.tail.object);
        }));
      })), it2: B((function() {
        return z(Ke(/^[0-9a-zA-Z]/).and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail;
          return new F.Object(O.empty, V.toMath(`\\labelstyle ` + t3, n2));
        })), Ke(/^(\\[a-zA-Z][a-zA-Z0-9]*)/).and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail;
          return new F.Object(O.empty, V.toMath(`\\labelstyle ` + t3, n2));
        })), L(`{`).andr(V.text).andl(We(`}`)).and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail;
          return new F.Object(O.empty, V.toMath(`\\labelstyle ` + t3, n2));
        })), L(`*`).andr(V.object), L(`@`).andr(V.dir).to((function(e3) {
          return new F.Object(O.empty, e3);
        })));
      })), alias: B((function() {
        return qe(`=`, `"`, V.id, `"`).opt().to((function(e3) {
          return e3.map((function(e4) {
            return e4.head.tail;
          }));
        }));
      })), xymatrix: B((function() {
        return V.setup().andl(R(`{`)).and(V.rows).andl(R(`}`)).to((function(e3) {
          return new F.Command.Xymatrix(e3.head, e3.tail);
        }));
      })), setup: B((function() {
        return Je(I(z(L(`"`).andr(I(Ge(/^[^"]+/))).andl(We(`"`)).to((function(e3) {
          return new F.Command.Xymatrix.Setup.Prefix(e3);
        })), L(`@!`).andr(I(Ge(/^[RC]/).opt().to((function(e3) {
          return e3.getOrElse(``);
        })))).and(I(z(Ue(`0`).to((function() {
          return `0em`;
        })), Ue(`=`).andr(V.dimen)))).to((function(e3) {
          var t3 = e3.tail;
          switch (e3.head) {
            case `R`:
              return new F.Command.Xymatrix.Setup.PretendEntrySize.Height(t3);
            case `C`:
              return new F.Command.Xymatrix.Setup.PretendEntrySize.Width(t3);
            default:
              return new F.Command.Xymatrix.Setup.PretendEntrySize.HeightAndWidth(t3);
          }
        })), L(`@!`).andr(I(z(Ue(`R`).to((function() {
          return new F.Command.Xymatrix.Setup.FixGrid.Row();
        })), Ue(`C`).to((function() {
          return new F.Command.Xymatrix.Setup.FixGrid.Column();
        }))).opt().to((function(e3) {
          return e3.getOrElse(new F.Command.Xymatrix.Setup.FixGrid.RowAndColumn());
        })))), L(`@`).andr(I(Ge(/^[MWHL]/))).and(V.addOp).and(V.dimen).to((function(e3) {
          var t3 = e3.head.tail, n2 = e3.tail;
          switch (e3.head.head) {
            case `M`:
              return new F.Command.Xymatrix.Setup.AdjustEntrySize.Margin(t3, n2);
            case `W`:
              return new F.Command.Xymatrix.Setup.AdjustEntrySize.Width(t3, n2);
            case `H`:
              return new F.Command.Xymatrix.Setup.AdjustEntrySize.Height(t3, n2);
            case `L`:
              return new F.Command.Xymatrix.Setup.AdjustLabelSep(t3, n2);
          }
        })), L(`@`).andr(V.nonemptyDirection).to((function(e3) {
          return new F.Command.Xymatrix.Setup.SetOrientation(e3);
        })), L(`@*[`).andr(V.shape).andl(R(`]`)).to((function(e3) {
          return new F.Command.Xymatrix.Setup.AddModifier(e3);
        })), L(`@*`).andr(V.addOp).and(V.size).to((function(e3) {
          return new F.Command.Xymatrix.Setup.AddModifier(new F.Modifier.AddOp(e3.head, e3.tail));
        })), L(`@`).andr(I(Ge(/^[RC]/).opt().to((function(e3) {
          return e3.getOrElse(``);
        })))).and(V.addOp).and(V.dimen).to((function(e3) {
          var t3 = e3.head.tail, n2 = e3.tail;
          switch (e3.head.head) {
            case `R`:
              return new F.Command.Xymatrix.Setup.ChangeSpacing.Row(t3, n2);
            case `C`:
              return new F.Command.Xymatrix.Setup.ChangeSpacing.Column(t3, n2);
            default:
              return new F.Command.Xymatrix.Setup.ChangeSpacing.RowAndColumn(t3, n2);
          }
        })), L(`@1`).to((function() {
          return new F.Command.Xymatrix.Setup.AdjustEntrySize.Margin(new F.Modifier.AddOp.Set(), `1pc`);
        })))));
      })), rows: B((function() {
        return V.row().and(I(Je(L(`\\\\`).andr(V.row)))).to((function(e3) {
          var t3 = e3.tail.prepend(e3.head);
          if (!t3.isEmpty) {
            var n2 = t3.at(t3.length() - 1);
            n2.entries.length() === 1 && n2.entries.at(0).isEmpty && (t3 = t3.reverse().tail.reverse());
          }
          return t3;
        }));
      })), row: B((function() {
        return V.entry().and(I(Je(L(`&`).andr(V.entry)))).to((function(e3) {
          return new F.Command.Xymatrix.Row(e3.tail.prepend(e3.head));
        }));
      })), entry: B((function() {
        return z(L(`*`).andr(V.object).and(V.pos).and(V.decor).to((function(e3) {
          var t3 = e3.head.head, n2 = e3.head.tail, r2 = e3.tail;
          return new F.Command.Xymatrix.Entry.ObjectEntry(t3, n2, r2);
        })), V.entryModifier().rep().and(V.looseObjectbox).and(V.decor).to((function(e3) {
          var t3 = e3.head.head.foldLeft(O.empty, (function(e4, t4) {
            return t4.concat(e4);
          })), n2 = e3.head.tail.isEmpty, r2 = e3.head.tail.object, i2 = e3.tail;
          return n2 && t3.isEmpty ? new F.Command.Xymatrix.Entry.EmptyEntry(i2) : new F.Command.Xymatrix.Entry.SimpleEntry(t3, r2, i2);
        })));
      })), entryModifier: B((function() {
        return z(L(`**`).andr(R(`[`)).andr(V.shape).andl(R(`]`)).to((function(e3) {
          return O.empty.append(e3);
        })), L(`**`).andr(R(`{`)).andr(I(Je(V.modifier))).andl(R(`}`)));
      })), looseObjectbox: B((function() {
        return z(V.objectbox().to((function(e4) {
          return { isEmpty: false, object: e4 };
        })), Ge(/^[^\\{}%&]+/).opt().to((function(e4) {
          return e4.getOrElse(``);
        })).and(I(Je(z(Ue(`{`).andr(V.text).andl(We(`}`)).to((function(e4) {
          return `{` + e4 + `}`;
        })), Ue(`\\`).andr(I((e3 = Ge(/^(\\|ar|xymatrix|PATH|afterPATH|save|restore|POS|afterPOS|drop|connect|xyignore|([lrud]+(twocell|uppertwocell|lowertwocell|compositemap))|xtwocell|xuppertwocell|xlowertwocell|xcompositemap)/), k.not(k.lazyParser(e3))))).andr(I(Ge(/^[{}%&]/).opt().to((function(e4) {
          return e4.getOrElse(``);
        })))).to((function(e4) {
          return `\\` + e4;
        })), Ge(/^%[^\r\n]*(\r\n|\r|\n)?/).to((function(e4) {
          return ` `;
        }))).and(I(Ge(/^[^\\{}%&]+/).opt().to((function(e4) {
          return e4.getOrElse(``);
        })))).to((function(e4) {
          return e4.head + e4.tail;
        }))).to((function(e4) {
          return e4.mkString(``);
        })))).and(V.textNodeCreator).to((function(e4) {
          var t3 = e4.head, n2 = e4.tail, r2 = t3.head + t3.tail;
          return { isEmpty: r2.trim().length === 0, object: V.toMath(`\\hbox{$\\objectstyle{` + r2 + `}$}`, n2) };
        })));
        var e3;
      })), twocellCommand: B((function() {
        return V.twocell().and(I(Je(V.twocellSwitch))).and(V.twocellArrow).to((function(e3) {
          return new F.Command.Twocell(e3.head.head, e3.head.tail, e3.tail);
        }));
      })), twocell: B((function() {
        return z(Ke(/^\\[lrud]+twocell/).to((function(e3) {
          var t3 = e3.substring(1, e3.length - 7);
          return new F.Command.Twocell.Twocell(t3, y.empty);
        })), Ke(/^\\[lrud]+uppertwocell/).to((function(e3) {
          var t3 = e3.substring(1, e3.length - 12);
          return new F.Command.Twocell.UpperTwocell(t3, y.empty);
        })), Ke(/^\\[lrud]+lowertwocell/).to((function(e3) {
          var t3 = e3.substring(1, e3.length - 12);
          return new F.Command.Twocell.LowerTwocell(t3, y.empty);
        })), Ke(/^\\[lrud]+compositemap/).to((function(e3) {
          var t3 = e3.substring(1, e3.length - 12);
          return new F.Command.Twocell.CompositeMap(t3, y.empty);
        })), z(L(`\\xtwocell`).to((function() {
          return F.Command.Twocell.Twocell;
        })), L(`\\xuppertwocell`).to((function() {
          return F.Command.Twocell.UpperTwocell;
        })), L(`\\xlowertwocell`).to((function() {
          return F.Command.Twocell.LowerTwocell;
        })), L(`\\xcompositemap`).to((function() {
          return F.Command.Twocell.CompositeMap;
        }))).andl(R(`[`)).and(I(Ge(/^[lrud]+/))).andl(R(`]`)).andl(R(`{`)).and(V.text).andl(R(`}`)).and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail, r2 = new F.Object(O.empty, V.toMath(`\\labelstyle ` + t3.tail, n2));
          return new t3.head.head(t3.head.tail, new y.Some(r2));
        })));
      })), twocellSwitch: B((function() {
        return z(L(`^`).andr(V.twocellLabel).to((function(e3) {
          return new F.Command.Twocell.Switch.UpperLabel(e3);
        })), L(`_`).andr(V.twocellLabel).to((function(e3) {
          return new F.Command.Twocell.Switch.LowerLabel(e3);
        })), L(`\\omit`).to((function() {
          return new F.Command.Twocell.Switch.DoNotSetCurvedArrows();
        })), L(`~!`).to((function() {
          return new F.Command.Twocell.Switch.PlaceModMapObject();
        })), Ke(/^(~[`'])/).andl(R(`{`)).and(V.object).andl(R(`}`)).to((function(e3) {
          var t3 = e3.head.substring(1);
          return new F.Command.Twocell.Switch.ChangeHeadTailObject(t3, e3.tail);
        })), Ke(/^(~[\^_]?)/).andl(R(`{`)).and(V.object).and(I(Xe(L(`~**`).andr(V.object)))).andl(R(`}`)).to((function(e3) {
          var t3 = e3.head.head.substring(1), n2 = e3.head.tail, r2 = e3.tail;
          return new F.Command.Twocell.Switch.ChangeCurveObject(t3, n2, r2);
        })), V.nudge().to((function(e3) {
          return new F.Command.Twocell.Switch.SetCurvature(e3);
        })));
      })), twocellLabel: B((function() {
        return z(Ke(/^[0-9a-zA-Z]/).and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail, r2 = new F.Object(O.empty, V.toMath(`\\twocellstyle ` + t3, n2));
          return new F.Command.Twocell.Label(y.empty, r2);
        })), Ke(/^(\\[a-zA-Z][a-zA-Z0-9]*)/).and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail, r2 = new F.Object(O.empty, V.toMath(`\\twocellstyle ` + t3, n2));
          return new F.Command.Twocell.Label(y.empty, r2);
        })), L(`{`).andr(I(Xe(V.nudge))).andl(R(`*`)).and(V.object).andl(R(`}`)).to((function(e3) {
          return new F.Command.Twocell.Label(e3.head, e3.tail);
        })), L(`{`).andr(I(Xe(V.nudge))).and(V.text).andl(We(`}`)).and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail, r2 = new F.Object(O.empty, V.toMath(`\\twocellstyle ` + t3.tail, n2));
          return new F.Command.Twocell.Label(t3.head, r2);
        })));
      })), nudge: B((function() {
        return z(L(`<\\omit>`).to((function() {
          return new F.Command.Twocell.Nudge.Omit();
        })), L(`<`).andr(V.factor).andl(R(`>`)).to((function(e3) {
          return new F.Command.Twocell.Nudge.Number(e3);
        })));
      })), twocellArrow: B((function() {
        return z(L(`{`).andr(I(Ke(/^([\^_=`'"!]|\\omit)/))).and(V.twocellLabelEntry).andl(R(`}`)).to((function(e3) {
          return new F.Command.Twocell.Arrow.WithOrientation(e3.head, e3.tail);
        })), L(`{`).andr(V.nudge).and(V.twocellLabelEntry).andl(R(`}`)).to((function(e3) {
          return new F.Command.Twocell.Arrow.WithPosition(e3.head, e3.tail);
        })), L(`{`).andr(V.twocellLabelEntry).andl(R(`}`)).to((function(e3) {
          return new F.Command.Twocell.Arrow.WithOrientation(``, e3);
        })), Ze(`no arrow label`).andr(V.textNodeCreator).to((function(e3) {
          return new F.Command.Twocell.Arrow.WithOrientation(``, new F.Object(O.empty, V.toMath(`\\twocellstyle{}`, e3)));
        })));
      })), twocellLabelEntry: B((function() {
        return z(L(`*`).andr(V.object), V.text().and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail;
          return new F.Object(O.empty, V.toMath(`\\twocellstyle ` + t3, n2));
        })));
      })), newdir: B((function() {
        return L(`{`).andr(V.dirMain).andl(We(`}`)).andl(R(`{`)).and(V.compositeObject).andl(R(`}`)).to((function(e3) {
          return new F.Command.Newdir(e3.head, new F.ObjectBox.CompositeObject(e3.tail));
        }));
      })), xyimport: B((function() {
        return L(`\\xyimport`).andr(R(`(`)).andr(V.factor).andl(R(`,`)).and(V.factor).andl(R(`)`)).and(I(Xe(L(`(`).andr(V.factor).andl(R(`,`)).and(V.factor).andl(R(`)`))))).andl(R(`{`)).and(I(z(L(`\\includegraphics`).andr(V.includegraphics), V.text().and(V.textNodeCreator).to((function(e3) {
          var t3 = e3.head, n2 = e3.tail;
          return V.toMath(`\\hbox{$\\objectstyle{` + t3 + `}$}`, n2);
        }))))).andl(R(`}`)).to((function(e3) {
          var t3, n2, r2 = e3.head.head.head, i2 = e3.head.head.tail;
          e3.head.tail.isDefined ? (t3 = e3.head.tail.get.head, n2 = e3.head.tail.get.tail) : (t3 = 0, n2 = 0);
          var a2 = e3.tail;
          return a2.isIncludegraphics === void 0 ? new F.Pos.Xyimport.TeXCommand(r2, i2, t3, n2, a2) : new F.Pos.Xyimport.Graphics(r2, i2, t3, n2, a2);
        }));
      })), includegraphics: B((function() {
        return L(`[`).andr(I(Xe(V.includegraphicsAttrList))).andl(R(`]`)).andl(R(`{`)).and(I(Ke(/^[^\s{}]+/))).andl(R(`}`)).to((function(e3) {
          var t3 = e3.head.getOrElse(O.empty), n2 = e3.tail;
          return new F.Command.Includegraphics(false, t3, n2);
        }));
      })), includegraphicsAttrList: B((function() {
        return V.includegraphicsAttr().and(I(Je(L(`,`).andr(V.includegraphicsAttr)))).to((function(e3) {
          return e3.tail.prepend(e3.head);
        }));
      })), includegraphicsAttr: B((function() {
        return z(L(`width`).andr(R(`=`)).andr(V.dimen).to((function(e3) {
          return new F.Command.Includegraphics.Attr.Width(e3);
        })), L(`height`).andr(R(`=`)).andr(V.dimen).to((function(e3) {
          return new F.Command.Includegraphics.Attr.Height(e3);
        })));
      })) };
      for (var $e in Qe) V[$e] = Qe[$e];
      var et = V, tt = function(e3, t3) {
        return [e3[1] * t3[2] - e3[2] * t3[1], e3[2] * t3[0] - e3[0] * t3[2], e3[0] * t3[1] - e3[1] * t3[0]];
      }, nt = function(e3) {
        return e3 < 0 ? -1 : e3 > 0 ? 1 : 0;
      }, rt = function(e3) {
        return Math.abs(e3) < l.machinePrecision ? 0 : e3;
      }, H = function(e3, t3) {
        var n2 = e3[t3], r2 = function() {
          var r3 = n2.call(this), a2 = function() {
            return r3;
          };
          return a2.reset = i2, e3[t3] = a2, r3;
        }, i2 = function() {
          e3[t3] = r2;
        };
        r2.reset = i2, i2();
      }, it = function(e3) {
        return Math.round(100 * e3) / 100;
      };
      function at(e3) {
        return at = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e4) {
          return typeof e4;
        } : function(e4) {
          return e4 && typeof Symbol == `function` && e4.constructor === Symbol && e4 !== Symbol.prototype ? `symbol` : typeof e4;
        }, at(e3);
      }
      function ot(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Super expression must either be null or a function`);
        e3.prototype = Object.create(t3 && t3.prototype, { constructor: { value: e3, writable: true, configurable: true } }), t3 && st(e3, t3);
      }
      function st(e3, t3) {
        return st = Object.setPrototypeOf || function(e4, t4) {
          return e4.__proto__ = t4, e4;
        }, st(e3, t3);
      }
      function ct(e3) {
        var t3 = (function() {
          if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return false;
          if (typeof Proxy == `function`) return true;
          try {
            return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {
            }))), true;
          } catch {
            return false;
          }
        })();
        return function() {
          var n2, r2 = ut(e3);
          if (t3) {
            var i2 = ut(this).constructor;
            n2 = Reflect.construct(r2, arguments, i2);
          } else n2 = r2.apply(this, arguments);
          return lt(this, n2);
        };
      }
      function lt(e3, t3) {
        if (t3 && (at(t3) === `object` || typeof t3 == `function`)) return t3;
        if (t3 !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
        return (function(e4) {
          if (e4 === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
          return e4;
        })(e3);
      }
      function ut(e3) {
        return ut = Object.setPrototypeOf ? Object.getPrototypeOf : function(e4) {
          return e4.__proto__ || Object.getPrototypeOf(e4);
        }, ut(e3);
      }
      function dt(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      function ft(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function pt(e3, t3, n2) {
        return t3 && ft(e3.prototype, t3), n2 && ft(e3, n2), e3;
      }
      var U = (function() {
        function e3() {
          dt(this, e3);
        }
        return pt(e3, [{ key: `toRect`, value: function(t3) {
          return new e3.Rect(this.x, this.y, t3);
        } }, { key: `toPoint`, value: function() {
          return new e3.Point(this.x, this.y);
        } }, { key: `combineRect`, value: function(t3) {
          return e3.combineRect(this, t3);
        } }], [{ key: `combineRect`, value: function(e4, t3) {
          if (e4 === void 0) return t3;
          if (t3 === void 0) return e4;
          var n2 = -(Math.min(e4.x - e4.l, t3.x - t3.l) - e4.x), r2 = Math.max(e4.x + e4.r, t3.x + t3.r) - e4.x, i2 = -(Math.min(e4.y - e4.d, t3.y - t3.d) - e4.y), a2 = Math.max(e4.y + e4.u, t3.y + t3.u) - e4.y;
          return e4.toRect({ l: n2, r: r2, d: i2, u: a2 });
        } }]), e3;
      })();
      function mt(e3) {
        return mt = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e4) {
          return typeof e4;
        } : function(e4) {
          return e4 && typeof Symbol == `function` && e4.constructor === Symbol && e4 !== Symbol.prototype ? `symbol` : typeof e4;
        }, mt(e3);
      }
      function W(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Super expression must either be null or a function`);
        e3.prototype = Object.create(t3 && t3.prototype, { constructor: { value: e3, writable: true, configurable: true } }), t3 && ht(e3, t3);
      }
      function ht(e3, t3) {
        return ht = Object.setPrototypeOf || function(e4, t4) {
          return e4.__proto__ = t4, e4;
        }, ht(e3, t3);
      }
      function G(e3) {
        var t3 = (function() {
          if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return false;
          if (typeof Proxy == `function`) return true;
          try {
            return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {
            }))), true;
          } catch {
            return false;
          }
        })();
        return function() {
          var n2, r2 = _t(e3);
          if (t3) {
            var i2 = _t(this).constructor;
            n2 = Reflect.construct(r2, arguments, i2);
          } else n2 = r2.apply(this, arguments);
          return gt(this, n2);
        };
      }
      function gt(e3, t3) {
        if (t3 && (mt(t3) === `object` || typeof t3 == `function`)) return t3;
        if (t3 !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
        return K(e3);
      }
      function K(e3) {
        if (e3 === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
        return e3;
      }
      function _t(e3) {
        return _t = Object.setPrototypeOf ? Object.getPrototypeOf : function(e4) {
          return e4.__proto__ || Object.getPrototypeOf(e4);
        }, _t(e3);
      }
      function q(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      function vt(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function J(e3, t3, n2) {
        return t3 && vt(e3.prototype, t3), e3;
      }
      U.Point = (function(e3) {
        ot(n2, e3);
        var t3 = ct(n2);
        function n2(e4, r2) {
          var i2;
          return dt(this, n2), (i2 = t3.call(this)).x = e4, i2.y = r2, i2;
        }
        return pt(n2, [{ key: `l`, get: function() {
          return 0;
        } }, { key: `r`, get: function() {
          return 0;
        } }, { key: `u`, get: function() {
          return 0;
        } }, { key: `d`, get: function() {
          return 0;
        } }, { key: `isPoint`, value: function() {
          return true;
        } }, { key: `isRect`, value: function() {
          return false;
        } }, { key: `isCircle`, value: function() {
          return false;
        } }, { key: `edgePoint`, value: function(e4, t4) {
          return this;
        } }, { key: `proportionalEdgePoint`, value: function(e4, t4) {
          return this;
        } }, { key: `grow`, value: function(e4, t4) {
          var n3 = Math.max(0, e4), r2 = Math.max(0, t4);
          return this.toRect({ l: n3, r: n3, u: r2, d: r2 });
        } }, { key: `toSize`, value: function(e4, t4) {
          return this.toRect({ l: e4 / 2, r: e4 / 2, u: t4 / 2, d: t4 / 2 });
        } }, { key: `growTo`, value: function(e4, t4) {
          var n3 = Math.max(0, e4), r2 = Math.max(0, t4);
          return this.toRect({ l: n3 / 2, r: n3 / 2, u: r2 / 2, d: r2 / 2 });
        } }, { key: `shrinkTo`, value: function(e4, t4) {
          return this;
        } }, { key: `move`, value: function(e4, t4) {
          return new U.Point(e4, t4);
        } }, { key: `shiftFrame`, value: function(e4, t4) {
          return this;
        } }, { key: `rotate`, value: function(e4) {
          return this;
        } }, { key: `contains`, value: function(e4) {
          return false;
        } }, { key: `toString`, value: function() {
          return `{x:` + this.x + `, y:` + this.y + `}`;
        } }]), n2;
      })(U), U.Rect = (function(e3) {
        ot(n2, e3);
        var t3 = ct(n2);
        function n2(e4, r2, i2) {
          var a2;
          return dt(this, n2), (a2 = t3.call(this)).x = e4, a2.y = r2, a2.l = i2.l || 0, a2.r = i2.r || 0, a2.u = i2.u || 0, a2.d = i2.d || 0, a2;
        }
        return pt(n2, [{ key: `isPoint`, value: function() {
          return this.l === 0 && this.r === 0 && this.u === 0 && this.d === 0;
        } }, { key: `isRect`, value: function() {
          return !this.isPoint();
        } }, { key: `isCircle`, value: function() {
          return false;
        } }, { key: `edgePoint`, value: function(e4, t4) {
          if (this.isPoint()) return this;
          var n3, r2 = e4 - this.x, i2 = t4 - this.y;
          return r2 > 0 ? (n3 = i2 * this.r / r2) > this.u ? new U.Point(this.x + this.u * r2 / i2, this.y + this.u) : n3 < -this.d ? new U.Point(this.x - this.d * r2 / i2, this.y - this.d) : new U.Point(this.x + this.r, this.y + n3) : r2 < 0 ? (n3 = -i2 * this.l / r2) > this.u ? new U.Point(this.x + this.u * r2 / i2, this.y + this.u) : n3 < -this.d ? new U.Point(this.x - this.d * r2 / i2, this.y - this.d) : new U.Point(this.x - this.l, this.y + n3) : i2 > 0 ? new U.Point(this.x, this.y + this.u) : new U.Point(this.x, this.y - this.d);
        } }, { key: `proportionalEdgePoint`, value: function(e4, t4) {
          if (this.isPoint()) return this;
          var n3 = e4 - this.x, r2 = t4 - this.y;
          if (Math.abs(n3) < l.machinePrecision && Math.abs(r2) < l.machinePrecision) return new U.Point(this.x - this.l, this.y + this.u);
          var i2, a2 = this.l + this.r, o2 = this.u + this.d, s2 = Math.PI, c2 = Math.atan2(r2, n3);
          return -3 * s2 / 4 < c2 && c2 <= -s2 / 4 ? (i2 = (c2 + 3 * s2 / 4) / (s2 / 2), new U.Point(this.x + this.r - i2 * a2, this.y + this.u)) : -s2 / 4 < c2 && c2 <= s2 / 4 ? (i2 = (c2 + s2 / 4) / (s2 / 2), new U.Point(this.x - this.l, this.y + this.u - i2 * o2)) : s2 / 4 < c2 && c2 <= 3 * s2 / 4 ? (i2 = (c2 - s2 / 4) / (s2 / 2), new U.Point(this.x - this.l + i2 * a2, this.y - this.d)) : (i2 = (c2 - (c2 > 0 ? 3 * s2 / 4 : -5 * s2 / 4)) / (s2 / 2), new U.Point(this.x + this.r, this.y - this.d + i2 * o2));
        } }, { key: `grow`, value: function(e4, t4) {
          return this.toRect({ l: Math.max(0, this.l + e4), r: Math.max(0, this.r + e4), u: Math.max(0, this.u + t4), d: Math.max(0, this.d + t4) });
        } }, { key: `toSize`, value: function(e4, t4) {
          var n3, r2, i2, a2, o2 = this.l + this.r, s2 = this.u + this.d;
          return o2 === 0 ? (a2 = e4 / 2, i2 = e4 / 2) : (a2 = e4 * this.l / o2, i2 = e4 * this.r / o2), s2 === 0 ? (n3 = t4 / 2, r2 = t4 / 2) : (n3 = t4 * this.u / s2, r2 = t4 * this.d / s2), this.toRect({ l: a2, r: i2, u: n3, d: r2 });
        } }, { key: `growTo`, value: function(e4, t4) {
          var n3 = this.u, r2 = this.d, i2 = this.r, a2 = this.l, o2 = a2 + i2, s2 = n3 + r2;
          return e4 > o2 && (o2 === 0 ? (a2 = e4 / 2, i2 = e4 / 2) : (a2 = e4 * this.l / o2, i2 = e4 * this.r / o2)), t4 > s2 && (s2 === 0 ? (n3 = t4 / 2, r2 = t4 / 2) : (n3 = t4 * this.u / s2, r2 = t4 * this.d / s2)), this.toRect({ l: a2, r: i2, u: n3, d: r2 });
        } }, { key: `shrinkTo`, value: function(e4, t4) {
          var n3 = this.u, r2 = this.d, i2 = this.r, a2 = this.l, o2 = a2 + i2, s2 = n3 + r2;
          return e4 < o2 && (o2 === 0 ? (a2 = e4 / 2, i2 = e4 / 2) : (a2 = e4 * this.l / o2, i2 = e4 * this.r / o2)), t4 < s2 && (s2 === 0 ? (n3 = t4 / 2, r2 = t4 / 2) : (n3 = t4 * this.u / s2, r2 = t4 * this.d / s2)), this.toRect({ l: a2, r: i2, u: n3, d: r2 });
        } }, { key: `move`, value: function(e4, t4) {
          return new U.Rect(e4, t4, { l: this.l, r: this.r, u: this.u, d: this.d });
        } }, { key: `shiftFrame`, value: function(e4, t4) {
          return new U.Rect(this.x, this.y, { l: Math.max(0, this.l - e4), r: Math.max(0, this.r + e4), u: Math.max(0, this.u + t4), d: Math.max(0, this.d - t4) });
        } }, { key: `rotate`, value: function(e4) {
          var t4 = Math.cos(e4), n3 = Math.sin(e4), r2 = -this.l, i2 = this.r, a2 = this.u, o2 = -this.d, s2 = { x: r2 * t4 - a2 * n3, y: r2 * n3 + a2 * t4 }, c2 = { x: r2 * t4 - o2 * n3, y: r2 * n3 + o2 * t4 }, l2 = { x: i2 * t4 - a2 * n3, y: i2 * n3 + a2 * t4 }, u2 = { x: i2 * t4 - o2 * n3, y: i2 * n3 + o2 * t4 };
          return this.toRect({ l: -Math.min(s2.x, c2.x, l2.x, u2.x), r: Math.max(s2.x, c2.x, l2.x, u2.x), u: Math.max(s2.y, c2.y, l2.y, u2.y), d: -Math.min(s2.y, c2.y, l2.y, u2.y) });
        } }, { key: `contains`, value: function(e4) {
          var t4 = e4.x, n3 = e4.y;
          return t4 >= this.x - this.l && t4 <= this.x + this.r && n3 >= this.y - this.d && n3 <= this.y + this.u;
        } }, { key: `toString`, value: function() {
          return `{x:` + this.x + `, y:` + this.y + `, l:` + this.l + `, r:` + this.r + `, u:` + this.u + `, d:` + this.d + `}`;
        } }]), n2;
      })(U), U.Ellipse = (function(e3) {
        ot(n2, e3);
        var t3 = ct(n2);
        function n2(e4, r2, i2, a2, o2, s2) {
          var c2;
          return dt(this, n2), (c2 = t3.call(this)).x = e4, c2.y = r2, c2.l = i2, c2.r = a2, c2.u = o2, c2.d = s2, c2;
        }
        return pt(n2, [{ key: `isPoint`, value: function() {
          return this.r === 0 && this.l === 0 || this.u === 0 && this.d === 0;
        } }, { key: `isRect`, value: function() {
          return false;
        } }, { key: `isCircle`, value: function() {
          return !this.isPoint();
        } }, { key: `isPerfectCircle`, value: function() {
          return this.l === this.r && this.l === this.u && this.l === this.d;
        } }, { key: `edgePoint`, value: function(e4, t4) {
          if (this.isPoint()) return this;
          if (this.isPerfectCircle()) {
            var n3, r2 = e4 - this.x, i2 = t4 - this.y;
            return n3 = Math.abs(r2) < l.machinePrecision && Math.abs(i2) < l.machinePrecision ? -Math.PI / 2 : Math.atan2(i2, r2), new U.Point(this.x + this.r * Math.cos(n3), this.y + this.r * Math.sin(n3));
          }
          var a2 = this.l, o2 = this.r, s2 = this.u, c2 = this.d, u2 = this.x, d2 = this.y, f2 = u2 + (o2 - a2) / 2, p2 = d2 + (s2 - c2) / 2, m2 = (a2 + o2) / 2, h2 = (s2 + c2) / 2, g2 = -(r2 = e4 - u2), _2 = (i2 = t4 - d2) * m2, v2 = g2 * h2, y2 = _2 * _2 + v2 * v2, b2 = -(c2 = _2 * f2 + v2 * p2 + ((r2 * d2 - i2 * u2) * m2 + (m2 - h2) * g2 * p2)) / y2, x2 = y2 * m2 * m2 - c2 * c2;
          if (x2 < 0) return new U.Point(this.x, this.y - this.d);
          var S2 = Math.sqrt(x2) / y2, C2 = h2 / m2, w2 = _2 * b2 + v2 * S2 + f2, T2 = C2 * (v2 * b2 - _2 * S2 + p2 - p2) + p2, E2 = _2 * b2 - v2 * S2 + f2, D2 = C2 * (v2 * b2 + _2 * S2 + p2 - p2) + p2, ee2 = nt;
          return ee2(w2 - f2) === ee2(e4 - f2) && ee2(T2 - p2) === ee2(t4 - p2) ? new U.Point(w2, T2) : new U.Point(E2, D2);
        } }, { key: `proportionalEdgePoint`, value: function(e4, t4) {
          if (this.isPoint()) return this;
          if (this.isPerfectCircle()) {
            var n3, r2 = e4 - this.x, i2 = t4 - this.y;
            return n3 = Math.abs(r2) < l.machinePrecision && Math.abs(i2) < l.machinePrecision ? -Math.PI / 2 : Math.atan2(i2, r2), new U.Point(this.x - this.r * Math.cos(n3), this.y - this.r * Math.sin(n3));
          }
          var a2 = this.l, o2 = this.r, s2 = this.u, c2 = this.d, u2 = this.x, d2 = this.y, f2 = u2 + (o2 - a2) / 2, p2 = d2 + (s2 - c2) / 2, m2 = (a2 + o2) / 2, h2 = (s2 + c2) / 2, g2 = -(r2 = e4 - u2), _2 = (i2 = t4 - d2) * m2, v2 = g2 * h2, y2 = _2 * _2 + v2 * v2, b2 = -(c2 = _2 * f2 + v2 * p2 + ((r2 * d2 - i2 * u2) * m2 + (m2 - h2) * g2 * p2)) / y2, x2 = y2 * m2 * m2 - c2 * c2;
          if (x2 < 0) return new U.Point(this.x, this.y - this.d);
          var S2 = Math.sqrt(x2) / y2, C2 = h2 / m2, w2 = _2 * b2 + v2 * S2 + f2, T2 = C2 * (v2 * b2 - _2 * S2 + p2 - p2) + p2, E2 = _2 * b2 - v2 * S2 + f2, D2 = C2 * (v2 * b2 + _2 * S2 + p2 - p2) + p2;
          return sign(w2 - f2) === sign(e4 - f2) && sign(T2 - p2) === sign(t4 - p2) ? new U.Point(E2, D2) : new U.Point(w2, T2);
        } }, { key: `grow`, value: function(e4, t4) {
          return new U.Ellipse(this.x, this.y, Math.max(0, this.l + e4), Math.max(0, this.r + e4), Math.max(0, this.u + t4), Math.max(0, this.d + t4));
        } }, { key: `toSize`, value: function(e4, t4) {
          var n3, r2, i2, a2, o2 = this.l + this.r, s2 = this.u + this.d;
          return o2 === 0 ? (a2 = e4 / 2, i2 = e4 / 2) : (a2 = e4 * this.l / o2, i2 = e4 * this.r / o2), s2 === 0 ? (n3 = t4 / 2, r2 = t4 / 2) : (n3 = t4 * this.u / s2, r2 = t4 * this.d / s2), new U.Ellipse(this.x, this.y, a2, i2, n3, r2);
        } }, { key: `growTo`, value: function(e4, t4) {
          var n3 = this.u, r2 = this.d, i2 = this.r, a2 = this.l, o2 = a2 + i2, s2 = n3 + r2;
          return e4 > o2 && (o2 === 0 ? (a2 = e4 / 2, i2 = e4 / 2) : (a2 = e4 * this.l / o2, i2 = e4 * this.r / o2)), t4 > s2 && (s2 === 0 ? (n3 = t4 / 2, r2 = t4 / 2) : (n3 = t4 * this.u / s2, r2 = t4 * this.d / s2)), new U.Ellipse(this.x, this.y, a2, i2, n3, r2);
        } }, { key: `shrinkTo`, value: function(e4, t4) {
          var n3 = this.u, r2 = this.d, i2 = this.r, a2 = this.l, o2 = a2 + i2, s2 = n3 + r2;
          return e4 < o2 && (o2 === 0 ? (a2 = e4 / 2, i2 = e4 / 2) : (a2 = e4 * this.l / o2, i2 = e4 * this.r / o2)), t4 < s2 && (s2 === 0 ? (n3 = t4 / 2, r2 = t4 / 2) : (n3 = t4 * this.u / s2, r2 = t4 * this.d / s2)), new U.Ellipse(this.x, this.y, a2, i2, n3, r2);
        } }, { key: `move`, value: function(e4, t4) {
          return new U.Ellipse(e4, t4, this.l, this.r, this.u, this.d);
        } }, { key: `shiftFrame`, value: function(e4, t4) {
          return new U.Ellipse(this.x, this.y, Math.max(0, this.l - e4), Math.max(0, this.r + e4), Math.max(0, this.u + t4), Math.max(0, this.d - t4));
        } }, { key: `rotate`, value: function(e4) {
          return this;
        } }, { key: `contains`, value: function(e4) {
          var t4 = e4.x, n3 = e4.y;
          if (this.isPoint()) return false;
          var r2 = this.l, i2 = this.r, a2 = this.u, o2 = this.d, s2 = (r2 + i2) / 2, c2 = t4 - (this.x + (i2 - r2) / 2), l2 = (n3 - (this.y + (a2 - o2) / 2)) / ((a2 + o2) / 2 / s2);
          return c2 * c2 + l2 * l2 <= s2 * s2;
        } }, { key: `toString`, value: function() {
          return `{x:` + this.x + `, y:` + this.y + `, l:` + this.l + `, r:` + this.r + `, u:` + this.u + `, d:` + this.d + `}`;
        } }]), n2;
      })(U);
      var Y = (function() {
        function e3() {
          q(this, e3);
        }
        return J(e3, [{ key: `isNone`, get: function() {
          return false;
        } }]), e3;
      })();
      function yt(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      Y.NoneShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2() {
          return q(this, n2), t3.call(this);
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
        } }, { key: `getBoundingBox`, value: function() {
        } }, { key: `toString`, value: function() {
          return `NoneShape`;
        } }, { key: `isNone`, get: function() {
          return true;
        } }]), n2;
      })(Y), Y.none = new Y.NoneShape(), Y.InvisibleBoxShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4) {
          var r2;
          return q(this, n2), (r2 = t3.call(this)).bbox = e4, r2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
        } }, { key: `getBoundingBox`, value: function() {
          return this.bbox;
        } }, { key: `toString`, value: function() {
          return `InvisibleBoxShape[bbox:` + this.bbox.toString() + `]`;
        } }]), n2;
      })(Y), Y.TranslateShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2, i2) {
          var a2;
          return q(this, n2), (a2 = t3.call(this)).dx = e4, a2.dy = r2, a2.shape = i2, H(K(a2), `getBoundingBox`), a2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          var t4 = e4.createGroup(e4.transformBuilder().translate(this.dx, this.dy));
          this.shape.draw(t4);
        } }, { key: `getBoundingBox`, value: function() {
          var e4 = this.shape.getBoundingBox();
          if (e4 !== void 0) return new U.Rect(e4.x + this.dx, e4.y + this.dy, e4);
        } }, { key: `toString`, value: function() {
          return `TranslateShape[dx:` + this.dx + `, dy:` + this.dy + `, shape:` + this.shape.toString() + `]`;
        } }]), n2;
      })(Y), Y.CompositeShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).foregroundShape = e4, i2.backgroundShape = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          this.backgroundShape.draw(e4), this.foregroundShape.draw(e4);
        } }, { key: `getBoundingBox`, value: function() {
          return U.combineRect(this.foregroundShape.getBoundingBox(), this.backgroundShape.getBoundingBox());
        } }, { key: `toString`, value: function() {
          return `(` + this.foregroundShape.toString() + `, ` + this.backgroundShape.toString() + `)`;
        } }]), n2;
      })(Y), Y.ChangeColorShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).color = e4, i2.shape = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          var t4 = e4.createChangeColorGroup(this.color);
          this.shape.draw(t4);
        } }, { key: `getBoundingBox`, value: function() {
          return this.shape.getBoundingBox();
        } }, { key: `toString`, value: function() {
          return this.shape + `, color:` + this.color;
        } }]), n2;
      })(Y), Y.CircleSegmentShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2, i2, a2, o2, s2, c2, l2, u2) {
          var d2;
          return q(this, n2), (d2 = t3.call(this)).x = e4, d2.y = r2, d2.sx = i2, d2.sy = a2, d2.r = o2, d2.large = s2, d2.flip = c2, d2.ex = l2, d2.ey = u2, H(K(d2), `getBoundingBox`), d2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          e4.createSVGElement(`path`, { d: `M` + A.measure.em2px(this.sx) + `,` + A.measure.em2px(-this.sy) + ` A` + A.measure.em2px(this.r) + `,` + A.measure.em2px(this.r) + ` 0 ` + this.large + `,` + this.flip + ` ` + A.measure.em2px(this.ex) + `,` + A.measure.em2px(-this.ey) });
        } }, { key: `getBoundingBox`, value: function() {
          return new U.Ellipse(this.x, this.y, this.r, this.r, this.r, this.r);
        } }, { key: `toString`, value: function() {
          return `CircleSegmentShape[x:` + this.x + `, y:` + this.y + `, sx:` + this.sx + `, sy:` + this.sy + `, r:` + this.r + `, large:` + this.large + `, flip:` + this.flip + `, ex:` + this.ex + `, ey:` + this.ey + `]`;
        } }]), n2;
      })(Y), Y.FullCircleShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2, i2) {
          var a2;
          return q(this, n2), (a2 = t3.call(this)).x = e4, a2.y = r2, a2.r = i2, H(K(a2), `getBoundingBox`), a2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          e4.createSVGElement(`circle`, { cx: A.measure.em2px(this.x), cy: A.measure.em2px(-this.y), r: A.measure.em2px(this.r) });
        } }, { key: `getBoundingBox`, value: function() {
          return new U.Ellipse(this.x, this.y, this.r, this.r, this.r, this.r);
        } }, { key: `toString`, value: function() {
          return `FullCircleShape[x:` + this.x + `, y:` + this.y + `, r:` + this.r + `]`;
        } }]), n2;
      })(Y), Y.RectangleShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2, i2, a2, o2, s2, c2, l2, u2, d2, f2, p2) {
          var m2;
          return q(this, n2), (m2 = t3.call(this)).x = e4, m2.y = r2, m2.left = i2, m2.right = a2, m2.up = o2, m2.down = s2, m2.r = c2, m2.isDoubled = l2, m2.color = u2, m2.dasharray = d2, m2.fillColor = f2, m2.hideLine = p2 || false, H(K(m2), `getBoundingBox`), m2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          var t4 = { x: A.measure.em2px(this.x - this.left), y: -A.measure.em2px(this.y + this.up), width: A.measure.em2px(this.left + this.right), height: A.measure.em2px(this.up + this.down), rx: A.measure.em2px(this.r) };
          this.dasharray !== void 0 && (t4[`stroke-dasharray`] = this.dasharray), this.hideLine ? t4.stroke = `none` : this.color !== void 0 && (t4.stroke = this.color), this.fillColor !== void 0 && (t4.fill = this.fillColor), e4.createSVGElement(`rect`, t4), this.isDoubled && (t4 = { x: A.measure.em2px(this.x - this.left + A.measure.thickness), y: -A.measure.em2px(this.y + this.up - A.measure.thickness), width: A.measure.em2px(this.left + this.right - 2 * A.measure.thickness), height: A.measure.em2px(this.up + this.down - 2 * A.measure.thickness), rx: A.measure.em2px(Math.max(this.r - A.measure.thickness, 0)) }, this.dasharray !== void 0 && (t4[`stroke-dasharray`] = this.dasharray), this.hideLine ? t4.stroke = `none` : this.color !== void 0 && (t4.stroke = this.color), this.fillColor !== void 0 && (t4.fill = this.fillColor), e4.createSVGElement(`rect`, t4));
        } }, { key: `getBoundingBox`, value: function() {
          return new U.Rect(this.x, this.y, { l: this.left, r: this.right, u: this.up, d: this.down });
        } }, { key: `toString`, value: function() {
          return `RectangleShape[x:` + this.x + `, y:` + this.y + `, left:` + this.left + `, right:` + this.right + `, up:` + this.up + `, down:` + this.down + `, r:` + this.r + `, isDouble:` + this.isDouble + `, dasharray:` + this.dasharray + `]`;
        } }]), n2;
      })(Y), Y.EllipseShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2, i2, a2, o2, s2, c2, l2, u2) {
          var d2;
          return q(this, n2), (d2 = t3.call(this)).x = e4, d2.y = r2, d2.rx = i2, d2.ry = a2, d2.isDoubled = o2, d2.color = s2, d2.dasharray = c2, d2.fillColor = l2, d2.hideLine = u2 || false, H(K(d2), `getBoundingBox`), d2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          var t4 = { cx: A.measure.em2px(this.x), cy: -A.measure.em2px(this.y), rx: A.measure.em2px(this.rx), ry: A.measure.em2px(this.ry) };
          this.dasharray !== void 0 && (t4[`stroke-dasharray`] = this.dasharray), this.hideLine ? t4.stroke = `none` : this.color !== void 0 && (t4.stroke = this.color), this.fillColor !== void 0 && (t4.fill = this.fillColor), e4.createSVGElement(`ellipse`, t4), this.isDoubled && (t4 = { cx: A.measure.em2px(this.x), cy: -A.measure.em2px(this.y), rx: A.measure.em2px(Math.max(this.rx - A.measure.thickness)), ry: A.measure.em2px(Math.max(this.ry - A.measure.thickness)) }, this.dasharray !== void 0 && (t4[`stroke-dasharray`] = this.dasharray), this.hideLine ? t4.stroke = `none` : this.color !== void 0 && (t4.stroke = this.color), this.fillColor !== void 0 && (t4.fill = this.fillColor), e4.createSVGElement(`ellipse`, t4));
        } }, { key: `getBoundingBox`, value: function() {
          return new U.Rect(this.x, this.y, { l: this.rx, r: this.rx, u: this.ry, d: this.ry });
        } }, { key: `toString`, value: function() {
          return `EllipseShape[x:` + this.x + `, y:` + this.y + `, rx:` + this.rx + `, ry:` + this.ry + `, isDoubled:` + this.isDoubled + `, dasharray:` + this.dasharray + `]`;
        } }]), n2;
      })(Y), Y.BoxShadeShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2, i2, a2, o2, s2, c2, l2) {
          var u2;
          return q(this, n2), (u2 = t3.call(this)).x = e4, u2.y = r2, u2.left = i2, u2.right = a2, u2.up = o2, u2.down = s2, u2.depth = c2, u2.color = l2 || `currentColor`, H(K(u2), `getBoundingBox`), u2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          var t4 = A.measure.em2px(this.x), n3 = A.measure.em2px(this.y), r2 = A.measure.em2px(this.left), i2 = A.measure.em2px(this.right), a2 = A.measure.em2px(this.up), o2 = A.measure.em2px(this.down), s2 = A.measure.em2px(this.depth);
          e4.createSVGElement(`path`, { d: `M` + (t4 - r2 + s2) + `,` + (-n3 + o2) + `L` + (t4 + i2) + `,` + (-n3 + o2) + `L` + (t4 + i2) + `,` + (-n3 - a2 + s2) + `L` + (t4 + i2 + s2) + `,` + (-n3 - a2 + s2) + `L` + (t4 + i2 + s2) + `,` + (-n3 + o2 + s2) + `L` + (t4 - r2 + s2) + `,` + (-n3 + o2 + s2) + `Z`, stroke: this.color, fill: this.color });
        } }, { key: `getBoundingBox`, value: function() {
          return new U.Rect(this.x, this.y, { l: this.left, r: this.right + this.depth, u: this.up, d: this.down + this.depth });
        } }, { key: `toString`, value: function() {
          return `RectangleShape[x:` + this.x + `, y:` + this.y + `, left:` + this.left + `, right:` + this.right + `, up:` + this.up + `, down:` + this.down + `, depth:` + this.depth + `]`;
        } }]), n2;
      })(Y), Y.LeftBrace = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2, i2, a2, o2, s2) {
          var c2;
          return q(this, n2), (c2 = t3.call(this)).x = e4, c2.y = r2, c2.up = i2, c2.down = a2, c2.degree = o2, c2.color = s2 || `currentColor`, H(K(c2), `getBoundingBox`), c2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          var t4, n3 = A.measure.oneem, r2 = Math.max(1.41975, this.down / n3 * 1.125) - 0.660375, i2 = 0.660375 - Math.max(1.41975, this.up / n3 * 1.125);
          t4 = `M` + A.measure.em2px(-0.0675) + ` ` + A.measure.em2px(r2) + `T` + A.measure.em2px(-0.068625) + ` ` + A.measure.em2px(0.07875 + r2) + `Q` + A.measure.em2px(-0.068625) + ` ` + A.measure.em2px(0.190125 + r2) + ` ` + A.measure.em2px(-0.0585) + ` ` + A.measure.em2px(0.250875 + r2) + `T` + A.measure.em2px(-0.01125) + ` ` + A.measure.em2px(0.387 + r2) + `Q` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(0.55575 + r2) + ` ` + A.measure.em2px(0.2475) + ` ` + A.measure.em2px(0.6525 + r2) + `L` + A.measure.em2px(0.262125) + ` ` + A.measure.em2px(0.660375 + r2) + `L` + A.measure.em2px(0.3015) + ` ` + A.measure.em2px(0.660375 + r2) + `L` + A.measure.em2px(0.30825) + ` ` + A.measure.em2px(0.653625 + r2) + `V` + A.measure.em2px(0.622125 + r2) + `Q` + A.measure.em2px(0.30825) + ` ` + A.measure.em2px(0.60975 + r2) + ` ` + A.measure.em2px(0.2925) + ` ` + A.measure.em2px(0.60075 + r2) + `Q` + A.measure.em2px(0.205875) + ` ` + A.measure.em2px(0.541125 + r2) + ` ` + A.measure.em2px(0.149625) + ` ` + A.measure.em2px(0.44775 + r2) + `T` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(0.239625 + r2) + `Q` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(0.2385 + r2) + ` ` + A.measure.em2px(0.073125) + ` ` + A.measure.em2px(0.235125 + r2) + `Q` + A.measure.em2px(0.068625) + ` ` + A.measure.em2px(0.203625 + r2) + ` ` + A.measure.em2px(0.0675) + ` ` + A.measure.em2px(0.041625 + r2) + `L` + A.measure.em2px(0.0675) + ` ` + A.measure.em2px(0.75825) + `Q` + A.measure.em2px(0.0675) + ` ` + A.measure.em2px(0.496125) + ` ` + A.measure.em2px(0.066375) + ` ` + A.measure.em2px(0.486) + `Q` + A.measure.em2px(0.05625) + ` ` + A.measure.em2px(0.336375) + ` ` + A.measure.em2px(-0.021375) + ` ` + A.measure.em2px(0.212625) + `T` + A.measure.em2px(-0.226125) + ` ` + A.measure.em2px(0.010125) + `L` + A.measure.em2px(-0.241875) + ` 0L` + A.measure.em2px(-0.226125) + ` ` + A.measure.em2px(-0.010125) + `Q` + A.measure.em2px(-0.106875) + ` ` + A.measure.em2px(-0.084375) + ` ` + A.measure.em2px(-0.025875) + ` ` + A.measure.em2px(-0.207) + `T` + A.measure.em2px(0.066375) + ` ` + A.measure.em2px(-0.486) + `Q` + A.measure.em2px(0.0675) + ` ` + A.measure.em2px(-0.496125) + ` ` + A.measure.em2px(0.0675) + ` ` + A.measure.em2px(-0.75825) + `L` + A.measure.em2px(0.0675) + ` ` + A.measure.em2px(-0.041625 + i2) + `Q` + A.measure.em2px(0.068625) + ` ` + A.measure.em2px(-0.203625 + i2) + ` ` + A.measure.em2px(0.073125) + ` ` + A.measure.em2px(-0.235125 + i2) + `Q` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(-0.2385 + i2) + ` ` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(-0.239625 + i2) + `Q` + A.measure.em2px(0.093375) + ` ` + A.measure.em2px(-0.354375 + i2) + ` ` + A.measure.em2px(0.149625) + ` ` + A.measure.em2px(-0.44775 + i2) + `T` + A.measure.em2px(0.2925) + ` ` + A.measure.em2px(-0.60075 + i2) + `Q` + A.measure.em2px(0.30825) + ` ` + A.measure.em2px(-0.60975 + i2) + ` ` + A.measure.em2px(0.30825) + ` ` + A.measure.em2px(-0.622125 + i2) + `L` + A.measure.em2px(0.30825) + ` ` + A.measure.em2px(-0.653625 + i2) + `L` + A.measure.em2px(0.3015) + ` ` + A.measure.em2px(-0.660375 + i2) + `L` + A.measure.em2px(0.262125) + ` ` + A.measure.em2px(-0.660375 + i2) + `L` + A.measure.em2px(0.2475) + ` ` + A.measure.em2px(-0.6525 + i2) + `Q` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(-0.55575 + i2) + ` ` + A.measure.em2px(-0.01125) + ` ` + A.measure.em2px(-0.387 + i2) + `Q` + A.measure.em2px(-0.048375) + ` ` + A.measure.em2px(-0.311625 + i2) + ` ` + A.measure.em2px(-0.0585) + ` ` + A.measure.em2px(-0.250875 + i2) + `T` + A.measure.em2px(-0.068625) + ` ` + A.measure.em2px(-0.07875 + i2) + `Q` + A.measure.em2px(-0.0675) + ` ` + A.measure.em2px(i2) + ` ` + A.measure.em2px(-0.0675) + ` ` + A.measure.em2px(i2) + `L` + A.measure.em2px(-0.0675) + ` ` + A.measure.em2px(-0.759375) + `V` + A.measure.em2px(-0.5985) + `Q` + A.measure.em2px(-0.0675) + ` ` + A.measure.em2px(-0.47925) + ` ` + A.measure.em2px(-0.075375) + ` ` + A.measure.em2px(-0.41175) + `T` + A.measure.em2px(-0.11475) + ` ` + A.measure.em2px(-0.27) + `Q` + A.measure.em2px(-0.133875) + ` ` + A.measure.em2px(-0.2205) + ` ` + A.measure.em2px(-0.160875) + ` ` + A.measure.em2px(-0.17775) + `T` + A.measure.em2px(-0.212625) + ` ` + A.measure.em2px(-0.106875) + `T` + A.measure.em2px(-0.25875) + ` ` + A.measure.em2px(-0.06075) + `T` + A.measure.em2px(-0.293625) + ` ` + A.measure.em2px(-0.0315) + `T` + A.measure.em2px(-0.307125) + ` ` + A.measure.em2px(-0.02025) + `Q` + A.measure.em2px(-0.30825) + ` ` + A.measure.em2px(-0.019125) + ` ` + A.measure.em2px(-0.30825) + ` 0T` + A.measure.em2px(-0.307125) + ` ` + A.measure.em2px(0.02025) + `Q` + A.measure.em2px(-0.307125) + ` ` + A.measure.em2px(0.021375) + ` ` + A.measure.em2px(-0.284625) + ` ` + A.measure.em2px(0.03825) + `T` + A.measure.em2px(-0.2295) + ` ` + A.measure.em2px(0.091125) + `T` + A.measure.em2px(-0.162) + ` ` + A.measure.em2px(0.176625) + `T` + A.measure.em2px(-0.10125) + ` ` + A.measure.em2px(0.30825) + `T` + A.measure.em2px(-0.068625) + ` ` + A.measure.em2px(0.482625) + `Q` + A.measure.em2px(-0.0675) + ` ` + A.measure.em2px(0.496125) + ` ` + A.measure.em2px(-0.0675) + ` ` + A.measure.em2px(0.759375) + `Z`, e4.createSVGElement(`path`, { d: t4, fill: this.color, stroke: this.color, "stroke-width": `0pt`, transform: `translate(` + A.measure.em2px(this.x) + `,` + A.measure.em2px(-this.y) + `) rotate(` + -this.degree + `) scale(` + n3 / 1.125 + `)` });
        } }, { key: `getBoundingBox`, value: function() {
          var e4 = A.measure.oneem;
          return new U.Rect(this.x, this.y, { l: 0.274 * e4, r: 0.274 * e4, u: Math.max(1.41975 * e4 / 1.125, this.up), d: Math.max(1.41975 * e4 / 1.125, this.down) }).rotate(this.degree * Math.PI / 180);
        } }, { key: `toString`, value: function() {
          return `LeftBrace[x:` + this.x + `, y:` + this.y + `, up:` + this.up + `, down:` + this.down + `]`;
        } }]), n2;
      })(Y), Y.LeftParenthesis = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2, i2, a2, o2) {
          var s2;
          return q(this, n2), (s2 = t3.call(this)).x = e4, s2.y = r2, s2.height = i2, s2.degree = a2, s2.color = o2 || `currentColor`, H(K(s2), `getBoundingBox`), s2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          var t4, n3 = A.measure.oneem, r2 = Math.max(0.660375, this.height / 2 / n3 * 1.125) - 0.660375, i2 = -r2;
          t4 = `M` + A.measure.em2px(-0.0675) + ` ` + A.measure.em2px(r2) + `T` + A.measure.em2px(-0.068625) + ` ` + A.measure.em2px(0.07875 + r2) + `Q` + A.measure.em2px(-0.068625) + ` ` + A.measure.em2px(0.190125 + r2) + ` ` + A.measure.em2px(-0.0585) + ` ` + A.measure.em2px(0.250875 + r2) + `T` + A.measure.em2px(-0.01125) + ` ` + A.measure.em2px(0.387 + r2) + `Q` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(0.55575 + r2) + ` ` + A.measure.em2px(0.2475) + ` ` + A.measure.em2px(0.6525 + r2) + `L` + A.measure.em2px(0.262125) + ` ` + A.measure.em2px(0.660375 + r2) + `L` + A.measure.em2px(0.3015) + ` ` + A.measure.em2px(0.660375 + r2) + `L` + A.measure.em2px(0.30825) + ` ` + A.measure.em2px(0.653625 + r2) + `V` + A.measure.em2px(0.622125 + r2) + `Q` + A.measure.em2px(0.30825) + ` ` + A.measure.em2px(0.60975 + r2) + ` ` + A.measure.em2px(0.2925) + ` ` + A.measure.em2px(0.60075 + r2) + `Q` + A.measure.em2px(0.205875) + ` ` + A.measure.em2px(0.541125 + r2) + ` ` + A.measure.em2px(0.149625) + ` ` + A.measure.em2px(0.44775 + r2) + `T` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(0.239625 + r2) + `Q` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(0.2385 + r2) + ` ` + A.measure.em2px(0.073125) + ` ` + A.measure.em2px(0.235125 + r2) + `Q` + A.measure.em2px(0.068625) + ` ` + A.measure.em2px(0.203625 + r2) + ` ` + A.measure.em2px(0.0675) + ` ` + A.measure.em2px(0.041625 + r2) + `L` + A.measure.em2px(0.0675) + ` ` + A.measure.em2px(-0.041625 + i2) + `Q` + A.measure.em2px(0.068625) + ` ` + A.measure.em2px(-0.203625 + i2) + ` ` + A.measure.em2px(0.073125) + ` ` + A.measure.em2px(-0.235125 + i2) + `Q` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(-0.2385 + i2) + ` ` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(-0.239625 + i2) + `Q` + A.measure.em2px(0.093375) + ` ` + A.measure.em2px(-0.354375 + i2) + ` ` + A.measure.em2px(0.149625) + ` ` + A.measure.em2px(-0.44775 + i2) + `T` + A.measure.em2px(0.2925) + ` ` + A.measure.em2px(-0.60075 + i2) + `Q` + A.measure.em2px(0.30825) + ` ` + A.measure.em2px(-0.60975 + i2) + ` ` + A.measure.em2px(0.30825) + ` ` + A.measure.em2px(-0.622125 + i2) + `L` + A.measure.em2px(0.30825) + ` ` + A.measure.em2px(-0.653625 + i2) + `L` + A.measure.em2px(0.3015) + ` ` + A.measure.em2px(-0.660375 + i2) + `L` + A.measure.em2px(0.262125) + ` ` + A.measure.em2px(-0.660375 + i2) + `L` + A.measure.em2px(0.2475) + ` ` + A.measure.em2px(-0.6525 + i2) + `Q` + A.measure.em2px(0.07425) + ` ` + A.measure.em2px(-0.55575 + i2) + ` ` + A.measure.em2px(-0.01125) + ` ` + A.measure.em2px(-0.387 + i2) + `Q` + A.measure.em2px(-0.048375) + ` ` + A.measure.em2px(-0.311625 + i2) + ` ` + A.measure.em2px(-0.0585) + ` ` + A.measure.em2px(-0.250875 + i2) + `T` + A.measure.em2px(-0.068625) + ` ` + A.measure.em2px(-0.07875 + i2) + `Q` + A.measure.em2px(-0.0675) + ` ` + A.measure.em2px(i2) + ` ` + A.measure.em2px(-0.0675) + ` ` + A.measure.em2px(i2) + `Z`, e4.createSVGElement(`path`, { d: t4, fill: this.color, stroke: this.color, "stroke-width": `0pt`, transform: `translate(` + A.measure.em2px(this.x) + `,` + A.measure.em2px(-this.y) + `) rotate(` + -this.degree + `) scale(` + n3 / 1.125 + `)` });
        } }, { key: `getBoundingBox`, value: function() {
          var e4 = A.measure.oneem;
          return new U.Rect(this.x, this.y, { l: 0.06 * e4, r: 0.274 * e4, u: Math.max(0.660375 * e4 / 1.125, this.height / 2), d: Math.max(0.660375 * e4 / 1.125, this.height / 2) }).rotate(this.degree * Math.PI / 180);
        } }, { key: `toString`, value: function() {
          return `LeftBrace[x:` + this.x + `, y:` + this.y + `, up:` + this.up + `, down:` + this.down + `]`;
        } }]), n2;
      })(Y), Y.TextShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.math = r2, i2.originalBBox = void 0, H(K(i2), `getBoundingBox`), H(K(i2), `getOriginalReferencePoint`), i2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          this._draw(e4, false);
        } }, { key: `getBoundingBox`, value: function() {
          return this._draw(A.svgForTestLayout, true);
        } }, { key: `_draw`, value: function(e4, t4) {
          return e4.xypicWrapper.drawTextObject(this, e4, t4);
        } }, { key: `getOriginalReferencePoint`, value: function() {
          this.getBoundingBox();
          var e4 = this.originalBBox, t4 = this.c, n3 = e4.H, r2 = e4.D;
          return new U.Point(t4.x, t4.y - (n3 - r2) / 2);
        } }, { key: `toString`, value: function() {
          return `TextShape[c:` + this.c.toString() + `, math:` + this.math.toString() + `]`;
        } }]), n2;
      })(Y), Y.ImageShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.url = r2, H(K(i2), `getBoundingBox`), H(K(i2), `getOriginalReferencePoint`), i2;
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          var t4 = this.c;
          e4.createSVGElement(`image`, { x: A.measure.em2px(t4.x - t4.l), y: A.measure.em2px(-t4.y - t4.u), width: A.measure.em2px(t4.l + t4.r), height: A.measure.em2px(t4.u + t4.d), preserveAspectRatio: `none`, "xlink:href": this.url });
        } }, { key: `getBoundingBox`, value: function() {
          return this.c;
        } }, { key: `getOriginalReferencePoint`, value: function() {
          return this.c;
        } }, { key: `toString`, value: function() {
          return `ImageShape[c:` + this.c.toString() + `, height:` + this.height + `, width:` + this.width + `, url:` + this.url + `]`;
        } }]), n2;
      })(Y), Y.ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2() {
          return q(this, n2), t3.call(this);
        }
        return J(n2, [{ key: `draw`, value: function(e4) {
          var t4 = e4.createGroup(e4.transformBuilder().translate(this.c.x, this.c.y).rotateRadian(this.angle));
          this.drawDelegate(t4);
        } }, { key: `getBoundingBox`, value: function() {
          return this.c.toRect(this.getBox()).rotate(this.angle);
        } }, { key: `toString`, value: function() {
          return `ArrowheadShape[c:` + this.c.toString() + `, angle:` + this.angle + `]`;
        } }]), n2;
      })(Y), Y.GT2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0.456 * e4, r: 0, d: 0.229 * e4, u: 0.229 * e4 };
        } }, { key: `getRadius`, value: function() {
          return 0.213 * A.measure.oneem;
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = e4.createGroup(e4.transformBuilder().rotateDegree(-10)), r2 = e4.createGroup(e4.transformBuilder().rotateDegree(10));
          n3.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), r2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.GT3ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0.507 * e4, r: 0, d: 0.268 * e4, u: 0.268 * e4 };
        } }, { key: `getRadius`, value: function() {
          return 0.325 * A.measure.oneem;
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = e4.createGroup(e4.transformBuilder().rotateDegree(-15)), r2 = e4.createGroup(e4.transformBuilder().rotateDegree(15));
          n3.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: A.measure.em2px(-0.507 * t4), y2: 0 }), r2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperGTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0.489 * e4, r: 0, d: 0, u: 0.147 * e4 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem;
          e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerGTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0.489 * e4, r: 0, d: 0.147 * e4, u: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem;
          e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.GTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0.489 * e4, r: 0, d: 0.147 * e4, u: 0.147 * e4 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem;
          e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LT2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0, r: 0.456 * e4, d: 0.229 * e4, u: 0.229 * e4 };
        } }, { key: `getRadius`, value: function() {
          return 0.213 * A.measure.oneem;
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = e4.createGroup(e4.transformBuilder().rotateDegree(10)), r2 = e4.createGroup(e4.transformBuilder().rotateDegree(-10));
          n3.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), r2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LT3ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0, r: 0.507 * e4, d: 0.268 * e4, u: 0.268 * e4 };
        } }, { key: `getRadius`, value: function() {
          return 0.325 * A.measure.oneem;
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = e4.createGroup(e4.transformBuilder().rotateDegree(15)), r2 = e4.createGroup(e4.transformBuilder().rotateDegree(-15));
          n3.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: A.measure.em2px(0.507 * t4), y2: 0 }), r2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperLTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0, r: 0.489 * e4, d: 0, u: 0.147 * e4 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem;
          e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerLTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0, r: 0.489 * e4, d: 0.147 * e4, u: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem;
          e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0, r: 0.489 * e4, d: 0.147 * e4, u: 0.147 * e4 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem;
          e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperColumnArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0, u: A.measure.lineElementLength, d: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: 0, y2: -t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerColumnArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0, u: 0, d: A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: 0, y2: t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.Column2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0, u: 0.5 * (A.measure.lineElementLength + A.measure.thickness), d: 0.5 * (A.measure.lineElementLength + A.measure.thickness) };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(0.5 * (A.measure.lineElementLength + A.measure.thickness));
          e4.createSVGElement(`line`, { x1: 0, y1: t4, x2: 0, y2: -t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.Column3ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0, u: 0.5 * A.measure.lineElementLength + A.measure.thickness, d: 0.5 * A.measure.lineElementLength + A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength + A.measure.thickness);
          e4.createSVGElement(`line`, { x1: 0, y1: t4, x2: 0, y2: -t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.ColumnArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: t4, x2: 0, y2: -t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperLParenArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0.5 * A.measure.lineElementLength, r: 0, u: A.measure.lineElementLength, d: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`path`, { d: `M0,0 A ` + t4 + `,` + t4 + ` 0 0,1 0,` + -2 * t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerLParenArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0.5 * A.measure.lineElementLength, r: 0, u: 0, d: A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`path`, { d: `M0,0 A ` + t4 + `,` + t4 + ` 0 0,0 0,` + 2 * t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LParenArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0.5 * A.measure.lineElementLength, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`path`, { d: `M` + t4 + `,` + -t4 + ` A ` + t4 + `,` + t4 + ` 0 0,0 ` + t4 + `,` + t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperRParenArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0.5 * A.measure.lineElementLength, u: A.measure.lineElementLength, d: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`path`, { d: `M0,0 A ` + t4 + `,` + t4 + ` 0 0,0 0,` + -2 * t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerRParenArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0.5 * A.measure.lineElementLength, u: 0, d: A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`path`, { d: `M0,0 A ` + t4 + `,` + t4 + ` 0 0,1 0,` + 2 * t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.RParenArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0.5 * A.measure.lineElementLength, r: 0, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`path`, { d: `M` + -t4 + `,` + -t4 + ` A ` + t4 + `,` + t4 + ` 0 0,1 ` + -t4 + `,` + t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerBackquoteArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0.5 * A.measure.lineElementLength, r: 0, u: 0, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`path`, { d: `M0,0 A ` + t4 + `,` + t4 + ` 0 0,0 ` + -t4 + `,` + t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperBackquoteArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0.5 * A.measure.lineElementLength, r: 0, u: 0.5 * A.measure.lineElementLength, d: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`path`, { d: `M0,0 A ` + t4 + `,` + t4 + ` 0 0,1 ` + -t4 + `,` + -t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerQuoteArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0.5 * A.measure.lineElementLength, u: 0, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`path`, { d: `M0,0 A ` + t4 + `,` + t4 + ` 0 0,1 ` + t4 + `,` + t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperQuoteArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0.5 * A.measure.lineElementLength, u: 0.5 * A.measure.lineElementLength, d: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`path`, { d: `M0,0 A ` + t4 + `,` + t4 + ` 0 0,0 ` + t4 + `,` + -t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.AsteriskArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = 0, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: A.measure.thickness, r: A.measure.thickness, u: A.measure.thickness, d: A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          e4.createSVGElement(`circle`, { cx: 0, cy: 0, r: A.measure.em2px(A.measure.thickness), fill: `currentColor` });
        } }]), n2;
      })(Y.ArrowheadShape), Y.OArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = 0, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: A.measure.thickness, r: A.measure.thickness, u: A.measure.thickness, d: A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          e4.createSVGElement(`circle`, { cx: 0, cy: 0, r: A.measure.em2px(A.measure.thickness) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.PlusArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0.5 * A.measure.lineElementLength, r: 0.5 * A.measure.lineElementLength, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.lineElementLength / 2, n3 = A.measure.em2px(t4);
          e4.createSVGElement(`line`, { x1: -n3, y1: 0, x2: n3, y2: 0 }), e4.createSVGElement(`line`, { x1: 0, y1: n3, x2: 0, y2: -n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.XArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2 + Math.PI / 4, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0.5 * A.measure.lineElementLength, r: 0.5 * A.measure.lineElementLength, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.lineElementLength / 2, n3 = A.measure.em2px(t4);
          e4.createSVGElement(`line`, { x1: -n3, y1: 0, x2: n3, y2: 0 }), e4.createSVGElement(`line`, { x1: 0, y1: n3, x2: 0, y2: -n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.SlashArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2 - Math.PI / 10, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0, u: A.measure.lineElementLength / 2, d: A.measure.lineElementLength / 2 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.lineElementLength / 2, n3 = A.measure.em2px(t4);
          e4.createSVGElement(`line`, { x1: 0, y1: n3, x2: 0, y2: -n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.Line3ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: A.measure.lineElementLength, u: A.measure.thickness, d: A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(A.measure.lineElementLength), n3 = A.measure.em2px(A.measure.thickness);
          e4.createSVGElement(`line`, { x1: 0, y1: n3, x2: t4, y2: n3 }), e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: t4, y2: 0 }), e4.createSVGElement(`line`, { x1: 0, y1: -n3, x2: t4, y2: -n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.Line2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: A.measure.lineElementLength, u: 0.5 * A.measure.thickness, d: 0.5 * A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(0.5 * A.measure.thickness), n3 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: t4, x2: n3, y2: t4 }), e4.createSVGElement(`line`, { x1: 0, y1: -t4, x2: n3, y2: -t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LineArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: A.measure.lineElementLength, u: 0, d: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: t4, y2: 0 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.Dot3ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0, u: A.measure.thickness, d: A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.oneem;
          var t4 = A.measure.em2px(A.measure.thickness), n3 = A.measure.em2px(A.measure.thickness), r2 = A.measure.dottedDasharray;
          e4.createSVGElement(`line`, { x1: 0, y1: t4, x2: n3, y2: t4, "stroke-dasharray": r2 }), e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: n3, y2: 0, "stroke-dasharray": r2 }), e4.createSVGElement(`line`, { x1: 0, y1: -t4, x2: n3, y2: -t4, "stroke-dasharray": r2 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.Dot2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0, u: 0.5 * A.measure.thickness, d: 0.5 * A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(0.5 * A.measure.thickness), n3 = A.measure.em2px(A.measure.thickness), r2 = A.measure.dottedDasharray;
          e4.createSVGElement(`line`, { x1: 0, y1: t4, x2: n3, y2: t4, "stroke-dasharray": r2 }), e4.createSVGElement(`line`, { x1: 0, y1: -t4, x2: n3, y2: -t4, "stroke-dasharray": r2 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.DotArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0, u: 0, d: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.oneem;
          var t4 = A.measure.em2px(A.measure.thickness), n3 = A.measure.dottedDasharray;
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: t4, y2: 0, "stroke-dasharray": n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.Tilde3ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: -2 * A.measure.thickness, r: 2 * A.measure.thickness, u: 2 * A.measure.thickness, d: 2 * A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(A.measure.thickness);
          e4.createSVGElement(`path`, { d: `M` + -2 * t4 + `,` + t4 + ` Q` + -t4 + `,0 0,` + t4 + ` T` + 2 * t4 + `,` + t4 + `M` + -2 * t4 + `,0 Q` + -t4 + `,` + -t4 + ` 0,0 T` + 2 * t4 + `,0M` + -2 * t4 + `,` + -t4 + ` Q` + -t4 + `,` + -2 * t4 + ` 0,` + -t4 + ` T` + 2 * t4 + `,` + -t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.Tilde2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: -2 * A.measure.thickness, r: 2 * A.measure.thickness, u: 1.5 * A.measure.thickness, d: 1.5 * A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(A.measure.thickness);
          e4.createSVGElement(`path`, { d: `M` + -2 * t4 + `,` + 0.5 * t4 + ` Q` + -t4 + `,` + -0.5 * t4 + ` 0,` + 0.5 * t4 + ` T` + 2 * t4 + `,` + 0.5 * t4 + `M` + -2 * t4 + `,` + -0.5 * t4 + ` Q` + -t4 + `,` + -1.5 * t4 + ` 0,` + -0.5 * t4 + ` T` + 2 * t4 + `,` + -0.5 * t4 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.TildeArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: -2 * A.measure.thickness, r: 2 * A.measure.thickness, u: A.measure.thickness, d: A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(A.measure.thickness);
          e4.createSVGElement(`path`, { d: `M` + -2 * t4 + `,0 Q` + -t4 + `,` + -t4 + ` 0,0 T` + 2 * t4 + `,0` });
        } }]), n2;
      })(Y.ArrowheadShape), Y.TildeArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: -2 * A.measure.thickness, r: 2 * A.measure.thickness, u: A.measure.thickness, d: A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(A.measure.thickness);
          e4.createSVGElement(`path`, { d: `M` + -2 * t4 + `,0 Q` + -t4 + `,` + -t4 + ` 0,0 T` + 2 * t4 + `,0` });
        } }]), n2;
      })(Y.ArrowheadShape), Y.GTGTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0.489 * e4 + 2 * A.measure.thickness, r: 0, d: 0.147 * e4, u: 0.147 * e4 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = A.measure.em2px(2 * n3);
          e4.createSVGElement(`path`, { d: `M` + -r2 + `,0 Q` + (A.measure.em2px(-0.222 * t4) - r2) + `,` + A.measure.em2px(0.02 * t4) + ` ` + (A.measure.em2px(-0.489 * t4) - r2) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M` + -r2 + `,0 Q` + (A.measure.em2px(-0.222 * t4) - r2) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + (A.measure.em2px(-0.489 * t4) - r2) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperGTGTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0.489 * e4 + 2 * A.measure.thickness, r: 0, d: 0, u: 0.147 * e4 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = A.measure.em2px(2 * n3);
          e4.createSVGElement(`path`, { d: `M` + -r2 + `,0 Q` + (A.measure.em2px(-0.222 * t4) - r2) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + (A.measure.em2px(-0.489 * t4) - r2) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerGTGTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0.489 * e4 + 2 * A.measure.thickness, r: 0, d: 0.147 * e4, u: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = A.measure.em2px(2 * n3);
          e4.createSVGElement(`path`, { d: `M` + -r2 + `,0 Q` + (A.measure.em2px(-0.222 * t4) - r2) + `,` + A.measure.em2px(0.02 * t4) + ` ` + (A.measure.em2px(-0.489 * t4) - r2) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.GTGT2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0.456 * e4 + 2 * A.measure.thickness, r: 0, d: 0.229 * e4, u: 0.229 * e4 };
        } }, { key: `getRadius`, value: function() {
          return 0.213 * A.measure.oneem;
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = e4.createGroup(e4.transformBuilder().rotateDegree(-10)), i2 = e4.createGroup(e4.transformBuilder().rotateDegree(10));
          r2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), i2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
          var a2 = e4.createGroup(e4.transformBuilder().translate(-2 * n3, 0).rotateDegree(-10)), o2 = e4.createGroup(e4.transformBuilder().translate(-2 * n3, 0).rotateDegree(10));
          a2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), o2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.GTGT3ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0.507 * e4 + 2 * A.measure.thickness, r: 0, d: 0.268 * e4, u: 0.268 * e4 };
        } }, { key: `getRadius`, value: function() {
          return 0.325 * A.measure.oneem;
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = e4.createGroup(e4.transformBuilder().rotateDegree(-15)), i2 = e4.createGroup(e4.transformBuilder().rotateDegree(15));
          r2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), i2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
          var a2 = e4.createGroup(e4.transformBuilder().translate(-2 * n3, 0).rotateDegree(-15)), o2 = e4.createGroup(e4.transformBuilder().translate(-2 * n3, 0).rotateDegree(15));
          a2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), o2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: A.measure.em2px(-0.507 * t4 - 2 * n3), y2: 0 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LTLTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0, r: 0.489 * e4 + 2 * A.measure.thickness, d: 0.147 * e4, u: 0.147 * e4 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = A.measure.em2px(2 * n3);
          e4.createSVGElement(`path`, { d: `M` + r2 + `,0 Q` + (A.measure.em2px(0.222 * t4) + r2) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + (A.measure.em2px(0.489 * t4) + r2) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`path`, { d: `M` + r2 + `,0 Q` + (A.measure.em2px(0.222 * t4) + r2) + `,` + A.measure.em2px(0.02 * t4) + ` ` + (A.measure.em2px(0.489 * t4) + r2) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperLTLTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0, r: 0.489 * e4 + 2 * A.measure.thickness, d: 0, u: 0.147 * e4 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = A.measure.em2px(2 * n3);
          e4.createSVGElement(`path`, { d: `M` + r2 + `,0 Q` + (A.measure.em2px(0.222 * t4) + r2) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + (A.measure.em2px(0.489 * t4) + r2) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerLTLTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0, r: 0.489 * e4 + 2 * A.measure.thickness, d: 0.147 * e4, u: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = A.measure.em2px(2 * n3);
          e4.createSVGElement(`path`, { d: `M` + r2 + `,0 Q` + (A.measure.em2px(0.222 * t4) + r2) + `,` + A.measure.em2px(0.02 * t4) + ` ` + (A.measure.em2px(0.489 * t4) + r2) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LTLT2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0, r: 0.456 + e4 + 2 * A.measure.thickness, d: 0.229 * e4, u: 0.229 * e4 };
        } }, { key: `getRadius`, value: function() {
          return 0.213 * A.measure.oneem;
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = e4.createGroup(e4.transformBuilder().translate(2 * n3, 0).rotateDegree(10)), i2 = e4.createGroup(e4.transformBuilder().translate(2 * n3, 0).rotateDegree(-10));
          r2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), i2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
          var a2 = e4.createGroup(e4.transformBuilder().rotateDegree(10)), o2 = e4.createGroup(e4.transformBuilder().rotateDegree(-10));
          a2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), o2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LTLT3ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: 0, r: 0.507 * e4 + 2 * A.measure.thickness, d: 0.268 * e4, u: 0.268 * e4 };
        } }, { key: `getRadius`, value: function() {
          return 0.325 * A.measure.oneem;
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = e4.createGroup(e4.transformBuilder().translate(2 * n3, 0).rotateDegree(15)), i2 = e4.createGroup(e4.transformBuilder().translate(2 * n3, 0).rotateDegree(-15));
          r2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), i2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
          var a2 = e4.createGroup(e4.transformBuilder().rotateDegree(15)), o2 = e4.createGroup(e4.transformBuilder().rotateDegree(-15));
          a2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), o2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: A.measure.em2px(0.507 * t4 + 2 * n3), y2: 0 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.ColumnColumnArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: A.measure.thickness, r: 0, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.thickness, n3 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: n3, x2: 0, y2: -n3 }), e4.createSVGElement(`line`, { x1: -A.measure.em2px(t4), y1: n3, x2: -A.measure.em2px(t4), y2: -n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperColumnColumnArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: A.measure.thickness, r: 0, u: A.measure.lineElementLength, d: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.thickness, n3 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: 0, y2: -n3 }), e4.createSVGElement(`line`, { x1: -A.measure.em2px(t4), y1: 0, x2: -A.measure.em2px(t4), y2: -n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerColumnColumnArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: A.measure.thickness, r: 0, u: 0, d: A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.thickness, n3 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: 0, y2: n3 }), e4.createSVGElement(`line`, { x1: -A.measure.em2px(t4), y1: 0, x2: -A.measure.em2px(t4), y2: n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.ColumnColumn2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: A.measure.thickness, r: 0, u: 0.5 * (A.measure.lineElementLength + A.measure.thickness), d: 0.5 * (A.measure.lineElementLength + A.measure.thickness) };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.thickness, n3 = A.measure.em2px(0.5 * (A.measure.lineElementLength + A.measure.thickness));
          e4.createSVGElement(`line`, { x1: 0, y1: n3, x2: 0, y2: -n3 }), e4.createSVGElement(`line`, { x1: -A.measure.em2px(t4), y1: n3, x2: -A.measure.em2px(t4), y2: -n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.ColumnColumn3ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: A.measure.thickness, r: 0, u: 0.5 * A.measure.lineElementLength + A.measure.thickness, d: 0.5 * A.measure.lineElementLength + A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.thickness, n3 = (t4 = A.measure.thickness, A.measure.em2px(0.5 * A.measure.lineElementLength + A.measure.thickness));
          e4.createSVGElement(`line`, { x1: 0, y1: n3, x2: 0, y2: -n3 }), e4.createSVGElement(`line`, { x1: -A.measure.em2px(t4), y1: n3, x2: -A.measure.em2px(t4), y2: -n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.ColumnLineArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: A.measure.lineElementLength, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: t4, x2: 0, y2: -t4 });
          var n3 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: n3, y2: 0 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.UpperColumnLineArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: A.measure.lineElementLength, u: A.measure.lineElementLength, d: 0 };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: 0, y2: -t4 });
          var n3 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: n3, y2: 0 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LowerColumnLineArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: A.measure.lineElementLength, u: 0, d: A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.thickness;
          var t4 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: 0, y2: t4 });
          var n3 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: n3, y2: 0 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.ColumnLine2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: A.measure.lineElementLength, u: 0.5 * (A.measure.lineElementLength + A.measure.thickness), d: 0.5 * (A.measure.lineElementLength + A.measure.thickness) };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.thickness, n3 = A.measure.em2px(0.5 * (A.measure.lineElementLength + A.measure.thickness));
          e4.createSVGElement(`line`, { x1: 0, y1: -n3, x2: 0, y2: n3 });
          var r2 = A.measure.em2px(0.5 * t4), i2 = A.measure.em2px(A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: r2, x2: i2, y2: r2 }), e4.createSVGElement(`line`, { x1: 0, y1: -r2, x2: i2, y2: -r2 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.ColumnLine3ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: A.measure.lineElementLength, u: 0.5 * A.measure.lineElementLength + A.measure.thickness, d: 0.5 * A.measure.lineElementLength + A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.thickness, n3 = A.measure.em2px(0.5 * A.measure.lineElementLength + A.measure.thickness);
          e4.createSVGElement(`line`, { x1: 0, y1: -n3, x2: 0, y2: n3 });
          var r2 = A.measure.em2px(A.measure.lineElementLength), i2 = A.measure.em2px(t4);
          e4.createSVGElement(`line`, { x1: 0, y1: i2, x2: r2, y2: i2 }), e4.createSVGElement(`line`, { x1: 0, y1: 0, x2: r2, y2: 0 }), e4.createSVGElement(`line`, { x1: 0, y1: -i2, x2: r2, y2: -i2 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.GTColumnArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0.489 * A.measure.oneem, r: 0, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: n3, x2: 0, y2: -n3 }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.GTGTColumnArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0.489 * A.measure.oneem + 2 * A.measure.thickness, r: 0, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: r2, x2: 0, y2: -r2 });
          var i2 = A.measure.em2px(2 * n3);
          e4.createSVGElement(`path`, { d: `M` + -i2 + `,0 Q` + (A.measure.em2px(-0.222 * t4) - i2) + `,` + A.measure.em2px(0.02 * t4) + ` ` + (A.measure.em2px(-0.489 * t4) - i2) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M` + -i2 + `,0 Q` + (A.measure.em2px(-0.222 * t4) - i2) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + (A.measure.em2px(-0.489 * t4) - i2) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.ColumnLTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0.489 * A.measure.oneem, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = (A.measure.thickness, A.measure.em2px(0.5 * A.measure.lineElementLength));
          e4.createSVGElement(`line`, { x1: 0, y1: n3, x2: 0, y2: -n3 }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.ColumnLTLTArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: 0, r: 0.489 * A.measure.oneem + 2 * A.measure.thickness, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.thickness, r2 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: r2, x2: 0, y2: -r2 });
          var i2 = A.measure.em2px(2 * n3);
          e4.createSVGElement(`path`, { d: `M` + i2 + `,0 Q` + (A.measure.em2px(0.222 * t4) + i2) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + (A.measure.em2px(0.489 * t4) + i2) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`path`, { d: `M` + i2 + `,0 Q` + (A.measure.em2px(0.222 * t4) + i2) + `,` + A.measure.em2px(0.02 * t4) + ` ` + (A.measure.em2px(0.489 * t4) + i2) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), e4.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) });
        } }]), n2;
      })(Y.ArrowheadShape), Y.SlashSlashArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2 - Math.PI / 10, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return { l: A.measure.thickness, r: 0, u: 0.5 * A.measure.lineElementLength, d: 0.5 * A.measure.lineElementLength };
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.em2px(A.measure.thickness), n3 = A.measure.em2px(0.5 * A.measure.lineElementLength);
          e4.createSVGElement(`line`, { x1: 0, y1: n3, x2: 0, y2: -n3 }), e4.createSVGElement(`line`, { x1: -t4, y1: n3, x2: -t4, y2: -n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LineGT2ArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          var e4 = A.measure.oneem;
          return { l: A.measure.lineElementLength, r: A.measure.lineElementLength, d: 0.229 * e4, u: 0.229 * e4 };
        } }, { key: `getRadius`, value: function() {
          return 0.213 * A.measure.oneem;
        } }, { key: `drawDelegate`, value: function(e4) {
          var t4 = A.measure.oneem, n3 = A.measure.lineElementLength, r2 = A.measure.em2px(n3), i2 = 0.5 * A.measure.thickness, a2 = A.measure.em2px(i2), o2 = this.getRadius(), s2 = A.measure.em2px(Math.sqrt(o2 * o2 - i2 * i2)), c2 = e4.createGroup(e4.transformBuilder().translate(n3, 0).rotateDegree(-10)), l2 = e4.createGroup(e4.transformBuilder().translate(n3, 0).rotateDegree(10));
          c2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(-0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(-0.147 * t4) }), l2.createSVGElement(`path`, { d: `M0,0 Q` + A.measure.em2px(-0.222 * t4) + `,` + A.measure.em2px(0.02 * t4) + ` ` + A.measure.em2px(-0.489 * t4) + `,` + A.measure.em2px(0.147 * t4) }), e4.createSVGElement(`path`, { d: `M` + -r2 + `,` + a2 + ` L` + (r2 - s2) + `,` + a2 + ` M` + -r2 + `,` + -a2 + ` L` + (r2 - s2) + `,` + -a2 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.TwocellEqualityArrowheadShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2) {
          var i2;
          return q(this, n2), (i2 = t3.call(this)).c = e4, i2.angle = r2, H(K(i2), `getBoundingBox`), i2;
        }
        return J(n2, [{ key: `getBox`, value: function() {
          return A.measure.oneem, { l: A.measure.lineElementLength, r: A.measure.lineElementLength, d: 0.5 * A.measure.thickness, u: 0.5 * A.measure.thickness };
        } }, { key: `drawDelegate`, value: function(e4) {
          A.measure.oneem;
          var t4 = A.measure.em2px(A.measure.lineElementLength), n3 = A.measure.em2px(0.5 * A.measure.thickness);
          e4.createSVGElement(`path`, { d: `M` + -t4 + `,` + n3 + ` L` + t4 + `,` + n3 + ` M` + -t4 + `,` + -n3 + ` L` + t4 + `,` + -n3 });
        } }]), n2;
      })(Y.ArrowheadShape), Y.LineShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2, i2, a2, o2) {
          var s2;
          return q(this, n2), (s2 = t3.call(this)).line = e4, s2.object = r2, s2.main = i2, s2.variant = a2, s2.bbox = o2, s2.holeRanges = O.empty, s2;
        }
        return J(n2, [{ key: `sliceHole`, value: function(e4) {
          this.holeRanges = this.holeRanges.prepend(e4);
        } }, { key: `draw`, value: function(e4) {
          this.line.drawLine(e4, this.object, this.main, this.variant, this.holeRanges);
        } }, { key: `getBoundingBox`, value: function() {
          return this.bbox;
        } }, { key: `toString`, value: function() {
          return `LineShape[line:` + this.line + `, object:` + this.object + `, main:` + this.main + `, variant:` + this.variant + `]`;
        } }]), n2;
      })(Y), Y.CurveShape = (function(e3) {
        W(n2, e3);
        var t3 = G(n2);
        function n2(e4, r2, i2, a2) {
          var o2;
          return q(this, n2), (o2 = t3.call(this)).curve = e4, o2.objectForDrop = r2, o2.objectForConnect = i2, o2.bbox = a2, o2.holeRanges = O.empty, o2;
        }
        return J(n2, [{ key: `sliceHole`, value: function(e4) {
          this.holeRanges = this.holeRanges.prepend(e4);
        } }, { key: `draw`, value: function(e4) {
          this.curve.drawCurve(e4, this.objectForDrop, this.objectForConnect, this.holeRanges);
        } }, { key: `getBoundingBox`, value: function() {
          return this.bbox;
        } }, { key: `toString`, value: function() {
          return `CurveShape[curve` + this.curve + `, objectForDrop:` + (this.objectForDrop === void 0 ? `null` : this.objectForDrop.toString()) + `, objectForConnect:` + (this.objectForConnect === void 0 ? `null` : this.objectForConnect.toString()) + `]`;
        } }]), n2;
      })(Y);
      var bt = (function() {
        function e3(t4, n3) {
          (function(e4, t5) {
            if (!(e4 instanceof t5)) throw TypeError(`Cannot call a class as a function`);
          })(this, e3), t4 > n3 ? (this.start = n3, this.end = t4) : (this.start = t4, this.end = n3);
        }
        var t3, n2;
        return t3 = e3, (n2 = [{ key: `difference`, value: function(t4) {
          var n3 = O.empty, r2 = this.start, i2 = this.end, a2 = t4.start, o2 = t4.end;
          return i2 <= a2 || o2 <= r2 ? n3 = n3.prepend(this) : r2 < a2 ? n3 = i2 <= o2 ? n3.prepend(new e3(r2, a2)) : (n3 = n3.prepend(new e3(r2, a2))).prepend(new e3(o2, i2)) : o2 < i2 && (n3 = n3.prepend(new e3(o2, i2))), n3;
        } }, { key: `differenceRanges`, value: function(e4) {
          var t4 = O.empty.prepend(this);
          return e4.foreach((function(e5) {
            t4 = t4.flatMap((function(t5) {
              return t5.difference(e5);
            }));
          })), t4;
        } }, { key: `toString`, value: function() {
          return `[` + this.start + `, ` + this.end + `]`;
        } }]) && yt(t3.prototype, n2), e3;
      })();
      function xt(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      var St = (function() {
        function e3(t4, n3) {
          (function(e4, t5) {
            if (!(e4 instanceof t5)) throw TypeError(`Cannot call a class as a function`);
          })(this, e3), this.shape = t4, this.env = n3;
        }
        var t3, n2;
        return t3 = e3, (n2 = [{ key: `duplicateEnv`, value: function() {
          var t4 = this.env.duplicate();
          return new e3(this.shape, t4);
        } }, { key: `appendShapeToFront`, value: function(e4) {
          e4.isNone || (this.shape.isNone ? this.shape = e4 : this.shape = new Y.CompositeShape(e4, this.shape));
        } }, { key: `appendShapeToBack`, value: function(e4) {
          e4.isNone || (this.shape.isNone ? this.shape = e4 : this.shape = new Y.CompositeShape(this.shape, e4));
        } }]) && xt(t3.prototype, n2), e3;
      })();
      function Ct(e3) {
        return Ct = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e4) {
          return typeof e4;
        } : function(e4) {
          return e4 && typeof Symbol == `function` && e4.constructor === Symbol && e4 !== Symbol.prototype ? `symbol` : typeof e4;
        }, Ct(e3);
      }
      function wt(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Super expression must either be null or a function`);
        e3.prototype = Object.create(t3 && t3.prototype, { constructor: { value: e3, writable: true, configurable: true } }), t3 && Tt(e3, t3);
      }
      function Tt(e3, t3) {
        return Tt = Object.setPrototypeOf || function(e4, t4) {
          return e4.__proto__ = t4, e4;
        }, Tt(e3, t3);
      }
      function Et(e3) {
        var t3 = (function() {
          if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return false;
          if (typeof Proxy == `function`) return true;
          try {
            return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {
            }))), true;
          } catch {
            return false;
          }
        })();
        return function() {
          var n2, r2 = Ot(e3);
          if (t3) {
            var i2 = Ot(this).constructor;
            n2 = Reflect.construct(r2, arguments, i2);
          } else n2 = r2.apply(this, arguments);
          return Dt(this, n2);
        };
      }
      function Dt(e3, t3) {
        if (t3 && (Ct(t3) === `object` || typeof t3 == `function`)) return t3;
        if (t3 !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
        return (function(e4) {
          if (e4 === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
          return e4;
        })(e3);
      }
      function Ot(e3) {
        return Ot = Object.setPrototypeOf ? Object.getPrototypeOf : function(e4) {
          return e4.__proto__ || Object.getPrototypeOf(e4);
        }, Ot(e3);
      }
      function kt(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      function At(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function jt(e3, t3, n2) {
        return t3 && At(e3.prototype, t3), n2 && At(e3, n2), e3;
      }
      var Mt = (function() {
        function e3() {
          kt(this, e3);
          var t3 = A.measure.length2em(`1mm`);
          this.origin = { x: 0, y: 0 }, this.xBase = { x: t3, y: 0 }, this.yBase = { x: 0, y: t3 }, this.savedPosition = {}, this.stateStack = O.empty, this.stackFrames = O.empty, this.stack = O.empty, this.angle = 0, this.lastCurve = Q.none, this.p = this.c = e3.originPosition, this.shouldCapturePos = false, this.capturedPositions = O.empty, this.objectmargin = A.measure.objectmargin, this.objectheight = A.measure.objectheight, this.objectwidth = A.measure.objectwidth, this.labelmargin = A.measure.labelmargin;
        }
        return jt(e3, [{ key: `duplicate`, value: function() {
          var t3 = new e3();
          return e3.copyFields(this, t3), t3;
        } }, { key: `saveState`, value: function() {
          var e4 = this.duplicate();
          this.stateStack = this.stateStack.prepend(e4);
        } }, { key: `restoreState`, value: function() {
          if (!this.stateStack.isEmpty) {
            var t3 = this.stateStack.head;
            this.stateStack = this.stateStack.tail, e3.copyFields(t3, this);
          }
        } }, { key: `absVector`, value: function(e4, t3) {
          return { x: this.origin.x + e4 * this.xBase.x + t3 * this.yBase.x, y: this.origin.y + e4 * this.xBase.y + t3 * this.yBase.y };
        } }, { key: `inverseAbsVector`, value: function(e4, t3) {
          var n2 = this.xBase.x, r2 = this.xBase.y, i2 = this.yBase.x, a2 = this.yBase.y, o2 = n2 * a2 - r2 * i2, s2 = e4 - this.origin.x, c2 = t3 - this.origin.y;
          return { x: (a2 * s2 - i2 * c2) / o2, y: (-r2 * s2 + n2 * c2) / o2 };
        } }, { key: `setOrigin`, value: function(e4, t3) {
          this.origin = { x: e4, y: t3 };
        } }, { key: `setXBase`, value: function(e4, t3) {
          this.xBase = { x: e4, y: t3 };
        } }, { key: `setYBase`, value: function(e4, t3) {
          this.yBase = { x: e4, y: t3 };
        } }, { key: `swapPAndC`, value: function() {
          var e4 = this.p;
          this.p = this.c, this.c = e4;
        } }, { key: `enterStackFrame`, value: function() {
          this.stackFrames = this.stackFrames.prepend(this.stack), this.initStack();
        } }, { key: `leaveStackFrame`, value: function() {
          this.stackFrames.isEmpty ? this.initStack() : (this.stack = this.stackFrames.head, this.stackFrames = this.stackFrames.tail);
        } }, { key: `savePos`, value: function(e4, t3) {
          this.savedPosition[e4] = t3;
        } }, { key: `startCapturePositions`, value: function() {
          this.shouldCapturePos = true, this.capturedPositions = O.empty;
        } }, { key: `endCapturePositions`, value: function() {
          this.shouldCapturePos = false;
          var e4 = this.capturedPositions;
          return this.capturedPositions = O.empty, e4;
        } }, { key: `capturePosition`, value: function(e4) {
          this.shouldCapturePos && e4 !== void 0 && (this.capturedPositions = this.capturedPositions.prepend(e4));
        } }, { key: `pushPos`, value: function(e4) {
          e4 !== void 0 && (this.stack = this.stack.prepend(e4));
        } }, { key: `popPos`, value: function() {
          if (this.stack.isEmpty) throw c(`ExecutionError`, `cannot pop from the empty stack`);
          var e4 = this.stack.head;
          return this.stack = this.stack.tail, e4;
        } }, { key: `initStack`, value: function() {
          this.stack = O.empty;
        } }, { key: `setStack`, value: function(e4) {
          this.stack = e4;
        } }, { key: `stackAt`, value: function(e4) {
          return this.stack.at(e4);
        } }, { key: `lookupPos`, value: function(e4, t3) {
          var n2 = this.savedPosition[e4];
          if (n2 === void 0) throw c(`ExecutionError`, t3 === void 0 ? `<pos> "` + e4 + `" not defined.` : t3);
          return n2;
        } }, { key: `toString`, value: function() {
          var e4 = ``;
          for (var t3 in this.savedPosition) this.savedPosition.hasOwnProperty(t3) && (e4.length > 0 && (e4 += `, `), e4 += t3.toString() + `:` + this.savedPosition[t3]);
          return `Env
  p:` + this.p + `
  c:` + this.c + `
  angle:` + this.angle + `
  lastCurve:` + this.lastCurve + `
  savedPosition:{` + e4 + `}
  origin:{x:` + this.origin.x + `, y:` + this.origin.y + `}
  xBase:{x:` + this.xBase.x + `, y:` + this.xBase.y + `}
  yBase:{x:` + this.yBase.x + `, y:` + this.yBase.y + `}
  stackFrames:` + this.stackFrames + `
  stack:` + this.stack + `
  shouldCapturePos:` + this.shouldCapturePos + `
  capturedPositions:` + this.capturedPositions;
        } }], [{ key: `copyFields`, value: function(e4, t3) {
          for (var n2 in e4) e4.hasOwnProperty(n2) && (t3[n2] = e4[n2]);
          for (var r2 in t3.savedPosition = {}, e4.savedPosition) e4.savedPosition.hasOwnProperty(r2) && (t3.savedPosition[r2] = e4.savedPosition[r2]);
        } }]), e3;
      })();
      Mt.originPosition = new U.Point(0, 0);
      var X = (function() {
        function e3() {
          kt(this, e3);
        }
        return jt(e3, [{ key: `velocity`, value: function(e4) {
          var t3 = this.dpx(e4), n2 = this.dpy(e4);
          return Math.sqrt(t3 * t3 + n2 * n2);
        } }, { key: `length`, value: function(e4) {
          if (e4 < 0 || e4 > 1) throw c(`ExecutionError`, `illegal cubic Bezier parameter t:` + e4);
          this.buildLengthArray();
          var t3 = e4 * l.lengthResolution, n2 = Math.floor(t3), r2 = Math.ceil(t3);
          if (n2 === r2) return this.lengthArray[n2];
          var i2 = this.lengthArray[n2];
          return i2 + (this.lengthArray[r2] - i2) / (r2 - n2) * (t3 - n2);
        } }, { key: `tOfLength`, value: function(e4) {
          this.buildLengthArray();
          var t3, n2, r2, i2 = this.lengthArray;
          if (e4 < i2[0]) return 0;
          if (e4 > i2[i2.length - 1]) return 1;
          for (var a2 = 0, o2 = i2.length - 2; a2 <= o2 && (n2 = i2[t3 = a2 + o2 >> 1], r2 = i2[t3 + 1], !(e4 >= n2 && e4 <= r2)); ) e4 < n2 ? o2 = t3 - 1 : a2 = t3 + 1;
          var s2 = l.lengthResolution;
          return n2 === r2 ? t3 / s2 : (t3 + (e4 - n2) / (r2 - n2)) / s2;
        } }, { key: `tOfShavedStart`, value: function(e4) {
          if (e4.isPoint()) return 0;
          var t3 = this.tOfIntersections(e4);
          return t3.length == 0 ? void 0 : Math.min.apply(Math, t3);
        } }, { key: `tOfShavedEnd`, value: function(e4) {
          if (e4.isPoint()) return 1;
          var t3 = this.tOfIntersections(e4);
          return t3.length == 0 ? void 0 : Math.max.apply(Math, t3);
        } }, { key: `shaveStart`, value: function(e4) {
          if (e4.isPoint()) return this;
          var t3 = this.tOfIntersections(e4);
          if (t3.length != 0) {
            var n2 = Math.min.apply(Math, t3);
            return this.divide(n2)[1];
          }
        } }, { key: `shaveEnd`, value: function(e4) {
          if (e4.isPoint()) return this;
          var t3 = this.tOfIntersections(e4);
          if (t3.length != 0) {
            var n2 = Math.max.apply(Math, t3);
            return this.divide(n2)[0];
          }
        } }, { key: `buildLengthArray`, value: function() {
          if (this.lengthArray === void 0) {
            var e4 = l.lengthResolution, t3 = Array(e4 + 1), n2 = 0, r2 = 0.5 / e4, i2 = 0, a2 = r2 / 3;
            t3[0] = 0, n2 = this.velocity(0) + 4 * this.velocity(r2);
            var o2 = this.velocity(2 * r2);
            for (t3[1] = a2 * (n2 + o2), i2 = 2; i2 <= e4; i2++) n2 += 2 * o2 + 4 * this.velocity((2 * i2 - 1) * r2), o2 = this.velocity(2 * i2 * r2), t3[i2] = a2 * (n2 + o2);
            this.lengthArray = t3;
          }
        } }, { key: `drawParallelCurve`, value: function(t3, n2) {
          var r2, i2, a2, o2, s2, c2, u2, d2, f2 = this.countOfSegments() * l.interpolationResolution, p2 = Array(f2 + 1), m2 = Array(f2 + 1), h2 = Array(f2 + 1), g2 = Array(f2 + 1), _2 = Array(f2 + 1), v2 = Math.PI / 2, y2 = n2;
          for (r2 = 0; r2 <= f2; r2++) i2 = r2 / f2, p2[r2] = i2, a2 = this.angle(i2), s2 = (o2 = this.position(i2)).x, c2 = o2.y, u2 = y2 * Math.cos(a2 + v2), d2 = y2 * Math.sin(a2 + v2), m2[r2] = s2 + u2, h2[r2] = c2 + d2, g2[r2] = s2 - u2, _2[r2] = c2 - d2;
          e3.CubicBeziers.interpolation(p2, m2, h2).drawPrimitive(t3, `none`), e3.CubicBeziers.interpolation(p2, g2, _2).drawPrimitive(t3, `none`);
        } }, { key: `drawParallelDottedCurve`, value: function(e4, t3, n2) {
          var r2 = 1 / A.measure.em, i2 = r2 / 2, a2 = r2 + t3, o2 = this.length(1), s2 = Math.floor((o2 - r2) / a2), c2 = n2;
          if (s2 >= 0) {
            var l2, u2 = Math.PI / 2, d2 = this.startPosition();
            for (this.endPosition(), l2 = 0; l2 <= s2; l2++) {
              d2 = i2 + l2 * a2;
              var f2 = this.tOfLength(d2), p2 = this.angle(f2), m2 = this.position(f2), h2 = m2.x, g2 = m2.y, _2 = c2 * Math.cos(p2 + u2), v2 = c2 * Math.sin(p2 + u2);
              e4.createSVGElement(`circle`, { cx: A.measure.em2px(h2 + _2), cy: -A.measure.em2px(g2 + v2), r: 0.12, fill: `currentColor` }), e4.createSVGElement(`circle`, { cx: A.measure.em2px(h2 - _2), cy: -A.measure.em2px(g2 - v2), r: 0.12, fill: `currentColor` });
            }
          }
        } }, { key: `drawParallelDashedCurve`, value: function(t3, n2, r2) {
          var i2, a2, o2, s2, c2, l2, u2, d2, f2 = this.length(1), p2 = Math.floor((f2 - n2) / (2 * n2)), m2 = 2 * p2 + 1, h2 = (f2 - n2) / 2 - p2 * n2, g2 = Array(p2 + 1), _2 = Array(p2 + 1), v2 = Array(p2 + 1), y2 = Array(p2 + 1), b2 = Array(p2 + 1), x2 = Math.PI / 2, S2 = r2;
          for (i2 = 0; i2 <= m2; i2++) a2 = this.tOfLength(h2 + i2 * n2), g2[i2] = a2, o2 = this.angle(a2), c2 = (s2 = this.position(a2)).x, l2 = s2.y, u2 = S2 * Math.cos(o2 + x2), d2 = S2 * Math.sin(o2 + x2), _2[i2] = c2 + u2, v2[i2] = l2 + d2, y2[i2] = c2 - u2, b2[i2] = l2 - d2;
          e3.CubicBeziers.interpolation(g2, _2, v2).drawSkipped(t3), e3.CubicBeziers.interpolation(g2, y2, b2).drawSkipped(t3);
        } }, { key: `drawSquigCurve`, value: function(e4, t3) {
          var n2 = A.measure.length2em(`0.15em`), r2 = this.length(1), i2 = 4 * n2, a2 = n2;
          if (r2 >= i2) {
            var o2, s2, c2, l2, u2, d2, f2, p2, m2, h2 = Math.floor(r2 / i2), g2 = (r2 - h2 * i2) / 2, _2 = Math.PI / 2;
            switch (t3) {
              case `3`:
                o2 = g2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 = `M` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 = `M` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), m2 = `M` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2);
                for (var v2 = 0; v2 < h2; v2++) o2 = g2 + i2 * v2 + n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` Q` + A.measure.em2px(c2.x + 2 * u2) + `,` + A.measure.em2px(-c2.y - 2 * d2), p2 += ` Q` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), m2 += ` Q` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), o2 = g2 + i2 * v2 + 2 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` ` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 += ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), m2 += ` ` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), o2 = g2 + i2 * v2 + 3 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` Q` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), p2 += ` Q` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), m2 += ` ` + A.measure.em2px(c2.x - 2 * u2) + `,` + A.measure.em2px(-c2.y + 2 * d2), o2 = g2 + i2 * (v2 + 1), s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` ` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 += ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), m2 += ` ` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2);
                e4.createSVGElement(`path`, { d: f2 }), e4.createSVGElement(`path`, { d: p2 }), e4.createSVGElement(`path`, { d: m2 });
                break;
              case `2`:
                for (o2 = g2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2) / 2, d2 = a2 * Math.sin(l2 + _2) / 2, f2 = `M` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 = `M` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), v2 = 0; v2 < h2; v2++) o2 = g2 + i2 * v2 + n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2) / 2, d2 = a2 * Math.sin(l2 + _2) / 2, f2 += ` Q` + A.measure.em2px(c2.x + 3 * u2) + `,` + A.measure.em2px(-c2.y - 3 * d2), p2 += ` Q` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), o2 = g2 + i2 * v2 + 2 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2) / 2, d2 = a2 * Math.sin(l2 + _2) / 2, f2 += ` ` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 += ` ` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), o2 = g2 + i2 * v2 + 3 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2) / 2, d2 = a2 * Math.sin(l2 + _2) / 2, f2 += ` Q` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), p2 += ` Q` + A.measure.em2px(c2.x - 3 * u2) + `,` + A.measure.em2px(-c2.y + 3 * d2), o2 = g2 + i2 * (v2 + 1), s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2) / 2, d2 = a2 * Math.sin(l2 + _2) / 2, f2 += ` ` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 += ` ` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2);
                e4.createSVGElement(`path`, { d: f2 }), e4.createSVGElement(`path`, { d: p2 });
                break;
              default:
                for (o2 = g2, s2 = this.tOfLength(o2), c2 = this.position(s2), f2 = `M` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), v2 = 0; v2 < h2; v2++) o2 = g2 + i2 * v2 + n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` Q` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), o2 = g2 + i2 * v2 + 2 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), f2 += ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), o2 = g2 + i2 * v2 + 3 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` Q` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), o2 = g2 + i2 * (v2 + 1), s2 = this.tOfLength(o2), c2 = this.position(s2), f2 += ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y);
                e4.createSVGElement(`path`, { d: f2 });
            }
          }
        } }, { key: `drawDashSquigCurve`, value: function(e4, t3) {
          var n2 = A.measure.thickness, r2 = this.length(1), i2 = 4 * n2, a2 = n2;
          if (r2 >= i2) {
            var o2, s2, c2, l2, u2, d2, f2, p2, m2, h2 = Math.floor((r2 - i2) / 2 / i2), g2 = (r2 - i2) / 2 - h2 * i2, _2 = Math.PI / 2;
            switch (t3) {
              case `3`:
                f2 = p2 = m2 = ``;
                for (var v2 = 0; v2 <= h2; v2++) o2 = g2 + i2 * v2 * 2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` M` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 += ` M` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), m2 += ` M` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), o2 = g2 + i2 * v2 * 2 + n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` Q` + A.measure.em2px(c2.x + 2 * u2) + `,` + A.measure.em2px(-c2.y - 2 * d2), p2 += ` Q` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), m2 += ` Q` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), o2 = g2 + i2 * v2 * 2 + 2 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` ` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 += ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), m2 += ` ` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), o2 = g2 + i2 * v2 * 2 + 3 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` Q` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), p2 += ` Q` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), m2 += ` ` + A.measure.em2px(c2.x - 2 * u2) + `,` + A.measure.em2px(-c2.y + 2 * d2), o2 = g2 + i2 * (2 * v2 + 1), s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` ` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 += ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), m2 += ` ` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2);
                e4.createSVGElement(`path`, { d: f2 }), e4.createSVGElement(`path`, { d: p2 }), e4.createSVGElement(`path`, { d: m2 });
                break;
              case `2`:
                for (f2 = p2 = ``, v2 = 0; v2 <= h2; v2++) o2 = g2 + i2 * v2 * 2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2) / 2, d2 = a2 * Math.sin(l2 + _2) / 2, f2 += ` M` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 += ` M` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), o2 = g2 + i2 * v2 * 2 + n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2) / 2, d2 = a2 * Math.sin(l2 + _2) / 2, f2 += ` Q` + A.measure.em2px(c2.x + 3 * u2) + `,` + A.measure.em2px(-c2.y - 3 * d2), p2 += ` Q` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), o2 = g2 + i2 * v2 * 2 + 2 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2) / 2, d2 = a2 * Math.sin(l2 + _2) / 2, f2 += ` ` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 += ` ` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), o2 = g2 + i2 * v2 * 2 + 3 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2) / 2, d2 = a2 * Math.sin(l2 + _2) / 2, f2 += ` Q` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), p2 += ` Q` + A.measure.em2px(c2.x - 3 * u2) + `,` + A.measure.em2px(-c2.y + 3 * d2), o2 = g2 + i2 * (2 * v2 + 1), s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2) / 2, d2 = a2 * Math.sin(l2 + _2) / 2, f2 += ` ` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), p2 += ` ` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2);
                e4.createSVGElement(`path`, { d: f2 }), e4.createSVGElement(`path`, { d: p2 });
                break;
              default:
                for (f2 = ``, v2 = 0; v2 <= h2; v2++) o2 = g2 + i2 * v2 * 2, s2 = this.tOfLength(o2), c2 = this.position(s2), f2 += ` M` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), o2 = g2 + i2 * v2 * 2 + n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` Q` + A.measure.em2px(c2.x + u2) + `,` + A.measure.em2px(-c2.y - d2), o2 = g2 + i2 * v2 * 2 + 2 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), f2 += ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), o2 = g2 + i2 * v2 * 2 + 3 * n2, s2 = this.tOfLength(o2), c2 = this.position(s2), l2 = this.angle(s2), u2 = a2 * Math.cos(l2 + _2), d2 = a2 * Math.sin(l2 + _2), f2 += ` Q` + A.measure.em2px(c2.x - u2) + `,` + A.measure.em2px(-c2.y + d2), o2 = g2 + i2 * (2 * v2 + 1), s2 = this.tOfLength(o2), c2 = this.position(s2), f2 += ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y);
                e4.createSVGElement(`path`, { d: f2 });
            }
          }
        } }, { key: `drawCurve`, value: function(e4, t3, n2, r2) {
          if (r2.isEmpty) this._drawCurve(e4, t3, n2);
          else {
            var i2 = new bt(0, 1).differenceRanges(r2), a2 = this;
            i2.foreach((function(r3) {
              a2.slice(r3.start, r3.end)._drawCurve(e4, t3, n2);
            }));
          }
        } }, { key: `_drawCurve`, value: function(e4, t3, n2) {
          var r2, i2 = A.measure.length2em(`0.15em`);
          if (n2 !== void 0) {
            var a2 = n2.dirMain(), o2 = n2.dirVariant();
            switch (a2) {
              case `=`:
                a2 = `-`, o2 = `2`;
                break;
              case `==`:
                a2 = `--`, o2 = `2`;
                break;
              case `:`:
              case `::`:
                a2 = `.`, o2 = `2`;
            }
            switch (a2) {
              case ``:
                break;
              case `-`:
                switch (o2) {
                  case `2`:
                    r2 = i2 / 2, this.drawParallelCurve(e4, r2);
                    break;
                  case `3`:
                    r2 = i2, this.drawParallelCurve(e4, r2), this.drawPrimitive(e4, `none`);
                    break;
                  default:
                    r2 = 0, this.drawPrimitive(e4, `none`);
                }
                break;
              case `.`:
              case `..`:
                switch (o2) {
                  case `2`:
                    r2 = i2 / 2, this.drawParallelDottedCurve(e4, i2, r2);
                    break;
                  case `3`:
                    r2 = i2, this.drawParallelDottedCurve(e4, i2, r2), this.drawPrimitive(e4, A.measure.dottedDasharray);
                    break;
                  default:
                    r2 = 0, this.drawPrimitive(e4, A.measure.dottedDasharray);
                }
                break;
              case `--`:
                var s2 = 3 * i2;
                if ((v2 = this.length(1)) >= s2) switch (o2) {
                  case `2`:
                    r2 = i2 / 2, this.drawParallelDashedCurve(e4, s2, r2);
                    break;
                  case `3`:
                    r2 = i2, this.drawParallelDashedCurve(e4, s2, r2);
                    var c2 = (v2 - s2) / 2 - Math.floor((v2 - s2) / 2 / s2) * s2, l2 = this.tOfLength(c2);
                    this.divide(l2)[1].drawPrimitive(e4, A.measure.em2px(s2) + ` ` + A.measure.em2px(s2));
                    break;
                  default:
                    r2 = 0, c2 = (v2 - s2) / 2 - Math.floor((v2 - s2) / 2 / s2) * s2, l2 = this.tOfLength(c2), this.divide(l2)[1].drawPrimitive(e4, A.measure.em2px(s2) + ` ` + A.measure.em2px(s2));
                }
                break;
              case `~`:
                switch (this.drawSquigCurve(e4, o2), o2) {
                  case `2`:
                    r2 = 1.5 * i2;
                    break;
                  case `3`:
                    r2 = 2 * i2;
                    break;
                  default:
                    r2 = 0;
                }
                break;
              case `~~`:
                switch (this.drawDashSquigCurve(e4, o2), o2) {
                  case `2`:
                    r2 = 1.5 * i2;
                    break;
                  case `3`:
                    r2 = 2 * i2;
                    break;
                  default:
                    r2 = 0;
                }
                break;
              default:
                (b2 = new Mt()).c = Mt.originPosition;
                var u2 = new St(Y.none, b2), d2 = n2.boundingBox(u2);
                if (d2 == null) return;
                var f2, p2, m2 = d2.l, h2 = m2 + d2.r;
                if (t3 !== void 0) {
                  var g2 = t3.boundingBox(u2);
                  g2 !== void 0 && (f2 = (p2 = g2.l) + g2.r);
                } else f2 = 0;
                var _2 = h2 + f2;
                _2 == 0 && (_2 = A.measure.strokeWidth);
                var v2 = this.length(1);
                if ((T2 = Math.floor(v2 / _2)) == 0) return;
                c2 = (v2 - T2 * _2) / 2, u2 = new St(Y.none, b2);
                for (var y2 = 0; y2 < T2; y2++) E2 = c2 + y2 * _2, t3 !== void 0 && (D2 = this.tOfLength(E2 + p2), b2.c = this.position(D2), b2.angle = this.angle(D2), t3.toDropShape(u2).draw(e4)), D2 = this.tOfLength(E2 + f2 + m2), b2.c = this.position(D2), b2.angle = this.angle(D2), n2.toDropShape(u2).draw(e4);
            }
          } else {
            var b2;
            (b2 = new Mt()).c = Mt.originPosition, u2 = new St(Y.none, b2);
            var x2 = t3, S2 = x2.boundingBox(u2);
            if (S2 === void 0) return;
            var C2 = S2.l + S2.r, w2 = C2;
            w2 == 0 && (w2 = A.measure.strokeWidth);
            var T2;
            if (v2 = this.length(1), (T2 = Math.floor(v2 / w2)) == 0) return;
            for (c2 = (v2 - T2 * w2 + w2 - C2) / 2 + S2.l, u2 = new St(Y.none, b2), y2 = 0; y2 < T2; y2++) {
              var E2 = c2 + y2 * w2, D2 = this.tOfLength(E2);
              b2.c = this.position(D2), b2.angle = 0, x2.toDropShape(u2).draw(e4);
            }
          }
        } }, { key: `toShape`, value: function(e4, t3, n2) {
          var r2, i2 = e4.env, a2 = A.measure.length2em(`0.15em`), o2 = Y.none;
          if (n2 !== void 0) {
            var s2 = n2.dirMain(), c2 = n2.dirVariant();
            switch (s2) {
              case `=`:
                s2 = `-`, c2 = `2`;
                break;
              case `==`:
                s2 = `--`, c2 = `2`;
                break;
              case `:`:
              case `::`:
                s2 = `.`, c2 = `2`;
            }
            switch (s2) {
              case ``:
                r2 = 0;
                break;
              case `-`:
              case `.`:
              case `..`:
                switch (c2) {
                  case `2`:
                    r2 = a2 / 2;
                    break;
                  case `3`:
                    r2 = a2;
                    break;
                  default:
                    r2 = 0;
                }
                break;
              case `--`:
                var l2 = 3 * a2;
                if ((h2 = this.length(1)) >= l2) switch (c2) {
                  case `2`:
                    r2 = a2 / 2;
                    break;
                  case `3`:
                    r2 = a2;
                    break;
                  default:
                    r2 = 0;
                }
                break;
              case `~`:
              case `~~`:
                switch (c2) {
                  case `2`:
                    r2 = 1.5 * a2;
                    break;
                  case `3`:
                    r2 = 2 * a2;
                    break;
                  default:
                    r2 = 0;
                }
                break;
              default:
                var u2 = n2.boundingBox(e4);
                if (u2 == null) return i2.angle = 0, i2.lastCurve = Q.none, Y.none;
                r2 = Math.max(u2.u, u2.d);
                var d2, f2 = u2.l + u2.r;
                if (t3 !== void 0) {
                  var p2 = t3.boundingBox(e4);
                  p2 !== void 0 && (d2 = p2.l + p2.r, r2 = Math.max(r2, p2.u, p2.d));
                } else d2 = 0;
                var m2 = f2 + d2;
                m2 == 0 && (m2 = A.measure.strokeWidth);
                var h2 = this.length(1);
                return Math.floor(h2 / m2) == 0 ? (i2.angle = 0, i2.lastCurve = Q.none, Y.none) : (o2 = new Y.CurveShape(this, t3, n2, this.boundingBox(r2)), e4.appendShapeToFront(o2), o2);
            }
            return r2 === void 0 ? Y.none : (o2 = new Y.CurveShape(this, t3, n2, this.boundingBox(r2)), e4.appendShapeToFront(o2), o2);
          }
          if (t3 !== void 0) {
            var g2 = t3.boundingBox(e4);
            if (g2 == null) return i2.angle = 0, i2.lastCurve = Q.none, Y.none;
            var _2 = g2.l + g2.r;
            return _2 == 0 && (_2 = A.measure.strokeWidth), h2 = this.length(1), Math.floor(h2 / _2) == 0 ? (i2.angle = 0, i2.lastCurve = Q.none, Y.none) : (r2 = Math.max(g2.u, g2.d), o2 = new Y.CurveShape(this, t3, n2, this.boundingBox(r2)), e4.appendShapeToFront(o2), o2);
          }
          return o2;
        } }], [{ key: `sign`, value: function(e4) {
          return e4 > 0 ? 1 : e4 === 0 ? 0 : -1;
        } }, { key: `solutionsOfCubicEq`, value: function(t3, n2, r2, i2) {
          if (t3 === 0) return e3.solutionsOfQuadEq(n2, r2, i2);
          var a2 = n2 / 3 / t3, o2 = r2 / t3, s2 = a2 * a2 - o2 / 3, c2 = -(i2 / t3) / 2 + o2 * a2 / 2 - a2 * a2 * a2, l2 = c2 * c2 - s2 * s2 * s2;
          if (l2 === 0) {
            var u2 = 2 * (h2 = c2 ** (1 / 3)) - a2, d2 = -h2 - a2;
            return e3.filterByIn0to1([u2, d2]);
          }
          if (l2 > 0) {
            var f2 = c2 + e3.sign(c2) * Math.sqrt(l2), p2 = (m2 = e3.sign(f2) * Math.abs(f2) ** (1 / 3)) + (h2 = s2 / m2) - a2;
            return e3.filterByIn0to1([p2]);
          }
          var m2 = 2 * Math.sqrt(s2), h2 = Math.acos(2 * c2 / s2 / m2), g2 = (u2 = m2 * Math.cos(h2 / 3) - a2, d2 = m2 * Math.cos((h2 + 2 * Math.PI) / 3) - a2, m2 * Math.cos((h2 + 4 * Math.PI) / 3) - a2);
          return e3.filterByIn0to1([u2, d2, g2]);
        } }, { key: `solutionsOfQuadEq`, value: function(t3, n2, r2) {
          if (t3 === 0) return e3.solutionsOfLinearEq(n2, r2);
          var i2 = n2 * n2 - 4 * r2 * t3;
          if (i2 >= 0) {
            var a2 = Math.sqrt(i2), o2 = (-n2 + a2) / 2 / t3, s2 = (-n2 - a2) / 2 / t3;
            return e3.filterByIn0to1([o2, s2]);
          }
          return [];
        } }, { key: `solutionsOfLinearEq`, value: function(t3, n2) {
          return t3 === 0 ? n2 === 0 ? 0 : [] : e3.filterByIn0to1([-n2 / t3]);
        } }, { key: `filterByIn0to1`, value: function(e4) {
          for (var t3 = [], n2 = 0; n2 < e4.length; n2++) {
            var r2 = e4[n2];
            r2 >= 0 && r2 <= 1 && t3.push(r2);
          }
          return t3;
        } }]), e3;
      })();
      X.QuadBezier = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4, r2, i2) {
          var a2;
          kt(this, n2), (a2 = t3.call(this)).cp0 = e4, a2.cp1 = r2, a2.cp2 = i2;
          var o2 = e4.x, s2 = 2 * (r2.x - e4.x), c2 = i2.x - 2 * r2.x + e4.x;
          a2.px = function(e5) {
            return o2 + e5 * s2 + e5 * e5 * c2;
          }, a2.dpx = function(e5) {
            return s2 + 2 * e5 * c2;
          };
          var l2 = e4.y, u2 = 2 * (r2.y - e4.y), d2 = i2.y - 2 * r2.y + e4.y;
          return a2.py = function(e5) {
            return l2 + e5 * u2 + e5 * e5 * d2;
          }, a2.dpy = function(e5) {
            return u2 + 2 * e5 * d2;
          }, a2;
        }
        return jt(n2, [{ key: `startPosition`, value: function() {
          return this.cp0;
        } }, { key: `endPosition`, value: function() {
          return this.cp2;
        } }, { key: `position`, value: function(e4) {
          return new U.Point(this.px(e4), this.py(e4));
        } }, { key: `derivative`, value: function(e4) {
          return new U.Point(this.dpx(e4), this.dpy(e4));
        } }, { key: `angle`, value: function(e4) {
          return Math.atan2(this.dpy(e4), this.dpx(e4));
        } }, { key: `boundingBox`, value: function(e4) {
          var t4 = this.maxMin(this.cp0.x, this.cp1.x, this.cp2.x, e4), n3 = this.maxMin(this.cp0.y, this.cp1.y, this.cp2.y, e4);
          if (e4 === 0) return new U.Rect(this.cp0.x, this.cp0.y, { l: this.cp0.x - t4.min, r: t4.max - this.cp0.x, u: n3.max - this.cp0.y, d: this.cp0.y - n3.min });
          var r2 = Math.PI / 2, i2 = this.cp0.x, a2 = this.cp0.y, o2 = this.cp2.x, s2 = this.cp2.y, c2 = this.angle(0) + r2, l2 = this.angle(1) + r2, u2 = e4 * Math.cos(c2), d2 = e4 * Math.sin(c2), f2 = e4 * Math.cos(l2), p2 = e4 * Math.sin(l2), m2 = Math.min(t4.min, i2 + u2, i2 - u2, o2 + f2, o2 - f2), h2 = Math.max(t4.max, i2 + u2, i2 - u2, o2 + f2, o2 - f2), g2 = Math.min(n3.min, a2 + d2, a2 - d2, s2 + p2, s2 - p2), _2 = Math.max(n3.max, a2 + d2, a2 - d2, s2 + p2, s2 - p2);
          return new U.Rect(i2, a2, { l: i2 - m2, r: h2 - i2, u: _2 - a2, d: a2 - g2 });
        } }, { key: `maxMin`, value: function(e4, t4, n3, r2) {
          var i2, a2;
          e4 > n3 ? (i2 = e4, a2 = n3) : (i2 = n3, a2 = e4);
          var o2, s2, c2 = rt, l2 = c2(e4), u2 = c2(t4 - e4), d2 = c2(n3 - 2 * t4 + e4);
          return d2 != 0 && (s2 = -u2 / d2) > 0 && s2 < 1 && (o2 = (function(e5) {
            return l2 + 2 * e5 * u2 + e5 * e5 * d2;
          })(s2), i2 = Math.max(i2, o2 + r2, o2 - r2), a2 = Math.min(a2, o2 + r2, o2 - r2)), { min: a2, max: i2 };
        } }, { key: `divide`, value: function(e4) {
          if (e4 < 0 || e4 > 1) throw c(`ExecutionError`, `illegal quadratic Bezier parameter t:` + e4);
          var t4 = this.cp0.x, n3 = this.cp1.x, r2 = this.cp2.x, i2 = this.cp0.y, a2 = this.cp1.y, o2 = this.cp2.y, s2 = this.px(e4), l2 = this.py(e4), u2 = this.cp0, d2 = new U.Point(t4 + e4 * (n3 - t4), i2 + e4 * (a2 - i2)), f2 = new U.Point(s2, l2), p2 = f2, m2 = new U.Point(n3 + e4 * (r2 - n3), a2 + e4 * (o2 - a2)), h2 = this.cp2;
          return [new X.QuadBezier(u2, d2, f2), new X.QuadBezier(p2, m2, h2)];
        } }, { key: `slice`, value: function(e4, t4) {
          if (!(e4 >= t4)) {
            if (e4 < 0 && (e4 = 0), t4 > 1 && (t4 = 1), e4 === 0 && t4 === 1) return this;
            this.cp0.x;
            var n3 = this.cp1.x, r2 = this.cp2.x, i2 = (this.cp0.y, this.cp1.y), a2 = this.cp2.y, o2 = this.px(e4), s2 = this.py(e4), c2 = n3 + e4 * (r2 - n3), l2 = i2 + e4 * (a2 - i2), u2 = new U.Point(o2, s2), d2 = new U.Point(o2 + t4 * (c2 - o2), s2 + t4 * (l2 - s2)), f2 = new U.Point(this.px(t4), this.py(t4));
            return new X.QuadBezier(u2, d2, f2);
          }
        } }, { key: `tOfIntersections`, value: function(e4) {
          if (e4.isPoint()) return [];
          if (e4.isRect()) {
            var t4, n3 = e4.x + e4.r, r2 = e4.x - e4.l, i2 = e4.y + e4.u, a2 = e4.y - e4.d, o2 = rt, s2 = this.cp0.x, c2 = this.cp1.x, l2 = this.cp2.x, u2 = o2(s2), d2 = o2(2 * (c2 - s2)), f2 = o2(l2 - 2 * c2 + s2), p2 = function(e5) {
              return u2 + e5 * d2 + e5 * e5 * f2;
            }, m2 = this.cp0.y, h2 = this.cp1.y, g2 = this.cp2.y, _2 = o2(m2), v2 = o2(2 * (h2 - m2)), y2 = o2(g2 - 2 * h2 + m2), b2 = function(e5) {
              return _2 + e5 * v2 + e5 * e5 * y2;
            }, x2 = [];
            t4 = (t4 = X.solutionsOfQuadEq(f2, d2, u2 - n3)).concat(X.solutionsOfQuadEq(f2, d2, u2 - r2));
            for (var S2 = 0; S2 < t4.length; S2++) (T2 = b2(de2 = t4[S2])) >= a2 && T2 <= i2 && x2.push(de2);
            for (t4 = (t4 = X.solutionsOfQuadEq(y2, v2, _2 - i2)).concat(X.solutionsOfQuadEq(y2, v2, _2 - a2)), S2 = 0; S2 < t4.length; S2++) (w2 = p2(de2 = t4[S2])) >= r2 && w2 <= n3 && x2.push(de2);
            return x2;
          }
          if (e4.isCircle()) {
            var C2 = Math.PI, w2 = e4.x, T2 = e4.y, E2 = e4.l, D2 = e4.r, ee2 = e4.u, te2 = e4.d, ne2 = w2 + (D2 - E2) / 2, O2 = T2 + (ee2 - te2) / 2, re2 = (n3 = (E2 + D2) / 2, (ee2 + te2) / 2), ie2 = C2 / 180, ae2 = new Z.Arc(ne2, O2, n3, re2, -C2 - ie2, -C2 / 2 + ie2), oe2 = new Z.Arc(ne2, O2, n3, re2, -C2 / 2 - ie2, 0 + ie2), se2 = new Z.Arc(ne2, O2, n3, re2, 0 - ie2, C2 / 2 + ie2), ce2 = new Z.Arc(ne2, O2, n3, re2, C2 / 2 - ie2, C2 + ie2), le2 = new Z.QuadBezier(this, 0, 1), ue2 = [];
            for (ue2 = (ue2 = (ue2 = (ue2 = ue2.concat(Z.findIntersections(ae2, le2))).concat(Z.findIntersections(oe2, le2))).concat(Z.findIntersections(se2, le2))).concat(Z.findIntersections(ce2, le2)), x2 = [], S2 = 0; S2 < ue2.length; S2++) {
              var de2 = (ue2[S2][1].min + ue2[S2][1].max) / 2;
              x2.push(de2);
            }
            return x2;
          }
        } }, { key: `countOfSegments`, value: function() {
          return 1;
        } }, { key: `drawPrimitive`, value: function(e4, t4) {
          var n3 = this.cp0, r2 = this.cp1, i2 = this.cp2;
          e4.createSVGElement(`path`, { d: `M` + A.measure.em2px(n3.x) + `,` + A.measure.em2px(-n3.y) + ` Q` + A.measure.em2px(r2.x) + `,` + A.measure.em2px(-r2.y) + ` ` + A.measure.em2px(i2.x) + `,` + A.measure.em2px(-i2.y), "stroke-dasharray": t4 });
        } }, { key: `toString`, value: function() {
          return `QuadBezier(` + this.cp0.x + `, ` + this.cp0.y + `)-(` + this.cp1.x + `, ` + this.cp1.y + `)-(` + this.cp2.x + `, ` + this.cp2.y + `)`;
        } }]), n2;
      })(X), X.CubicBezier = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4, r2, i2, a2) {
          var o2;
          kt(this, n2), (o2 = t3.call(this)).cp0 = e4, o2.cp1 = r2, o2.cp2 = i2, o2.cp3 = a2;
          var s2 = e4.x, c2 = 3 * (r2.x - e4.x), l2 = 3 * (i2.x - 2 * r2.x + e4.x), u2 = a2.x - 3 * i2.x + 3 * r2.x - e4.x;
          o2.px = function(e5) {
            return s2 + e5 * c2 + e5 * e5 * l2 + e5 * e5 * e5 * u2;
          }, o2.dpx = function(e5) {
            return c2 + 2 * e5 * l2 + 3 * e5 * e5 * u2;
          };
          var d2 = e4.y, f2 = 3 * (r2.y - e4.y), p2 = 3 * (i2.y - 2 * r2.y + e4.y), m2 = a2.y - 3 * i2.y + 3 * r2.y - e4.y;
          return o2.py = function(e5) {
            return d2 + e5 * f2 + e5 * e5 * p2 + e5 * e5 * e5 * m2;
          }, o2.dpy = function(e5) {
            return f2 + 2 * e5 * p2 + 3 * e5 * e5 * m2;
          }, o2;
        }
        return jt(n2, [{ key: `startPosition`, value: function() {
          return this.cp0;
        } }, { key: `endPosition`, value: function() {
          return this.cp3;
        } }, { key: `position`, value: function(e4) {
          return new U.Point(this.px(e4), this.py(e4));
        } }, { key: `derivative`, value: function(e4) {
          return new U.Point(this.dpx(e4), this.dpy(e4));
        } }, { key: `angle`, value: function(e4) {
          return Math.atan2(this.dpy(e4), this.dpx(e4));
        } }, { key: `boundingBox`, value: function(e4) {
          var t4 = this.maxMin(this.cp0.x, this.cp1.x, this.cp2.x, this.cp3.x, e4), n3 = this.maxMin(this.cp0.y, this.cp1.y, this.cp2.y, this.cp3.y, e4);
          if (e4 === 0) return new U.Rect(this.cp0.x, this.cp0.y, { l: this.cp0.x - t4.min, r: t4.max - this.cp0.x, u: n3.max - this.cp0.y, d: this.cp0.y - n3.min });
          var r2 = Math.PI / 2, i2 = this.cp0.x, a2 = this.cp0.y, o2 = this.cp3.x, s2 = this.cp3.y, c2 = this.angle(0) + r2, l2 = this.angle(1) + r2, u2 = e4 * Math.cos(c2), d2 = e4 * Math.sin(c2), f2 = e4 * Math.cos(l2), p2 = e4 * Math.sin(l2), m2 = Math.min(t4.min, i2 + u2, i2 - u2, o2 + f2, o2 - f2), h2 = Math.max(t4.max, i2 + u2, i2 - u2, o2 + f2, o2 - f2), g2 = Math.min(n3.min, a2 + d2, a2 - d2, s2 + p2, s2 - p2), _2 = Math.max(n3.max, a2 + d2, a2 - d2, s2 + p2, s2 - p2);
          return new U.Rect(i2, a2, { l: i2 - m2, r: h2 - i2, u: _2 - a2, d: a2 - g2 });
        } }, { key: `maxMin`, value: function(e4, t4, n3, r2, i2) {
          var a2, o2;
          e4 > r2 ? (a2 = e4, o2 = r2) : (a2 = r2, o2 = e4);
          var s2, c2 = rt, l2 = c2(e4), u2 = c2(t4 - e4), d2 = c2(n3 - 2 * t4 + e4), f2 = c2(r2 - 3 * n3 + 3 * t4 - e4), p2 = function(e5) {
            e5 > 0 && e5 < 1 && (s2 = (function(e6) {
              return l2 + 3 * e6 * u2 + 3 * e6 * e6 * d2 + e6 * e6 * e6 * f2;
            })(e5), a2 = Math.max(a2, s2 + i2, s2 - i2), o2 = Math.min(o2, s2 + i2, s2 - i2));
          };
          if (f2 == 0) d2 != 0 && p2(-u2 / d2 / 2);
          else {
            var m2 = d2 * d2 - u2 * f2;
            m2 > 0 ? (p2((-d2 + Math.sqrt(m2)) / f2), p2((-d2 - Math.sqrt(m2)) / f2)) : m2 == 0 && p2(-d2 / f2);
          }
          return { min: o2, max: a2 };
        } }, { key: `divide`, value: function(e4) {
          if (e4 < 0 || e4 > 1) throw c(`ExecutionError`, `illegal cubic Bezier parameter t:` + e4);
          var t4 = this.cp0.x, n3 = this.cp1.x, r2 = this.cp2.x, i2 = this.cp3.x, a2 = this.cp0.y, o2 = this.cp1.y, s2 = this.cp2.y, l2 = this.cp3.y, u2 = this.px(e4), d2 = this.py(e4), f2 = this.cp0, p2 = new U.Point(t4 + e4 * (n3 - t4), a2 + e4 * (o2 - a2)), m2 = new U.Point(t4 + 2 * e4 * (n3 - t4) + e4 * e4 * (r2 - 2 * n3 + t4), a2 + 2 * e4 * (o2 - a2) + e4 * e4 * (s2 - 2 * o2 + a2)), h2 = new U.Point(u2, d2), g2 = h2, _2 = new U.Point(n3 + 2 * e4 * (r2 - n3) + e4 * e4 * (i2 - 2 * r2 + n3), o2 + 2 * e4 * (s2 - o2) + e4 * e4 * (l2 - 2 * s2 + o2)), v2 = new U.Point(r2 + e4 * (i2 - r2), s2 + e4 * (l2 - s2)), y2 = this.cp3;
          return [new X.CubicBezier(f2, p2, m2, h2), new X.CubicBezier(g2, _2, v2, y2)];
        } }, { key: `slice`, value: function(e4, t4) {
          if (!(e4 >= t4)) {
            if (e4 < 0 && (e4 = 0), t4 > 1 && (t4 = 1), e4 === 0 && t4 === 1) return this;
            this.cp0.x;
            var n3 = this.cp1.x, r2 = this.cp2.x, i2 = this.cp3.x, a2 = (this.cp0.y, this.cp1.y), o2 = this.cp2.y, s2 = this.cp3.y, c2 = this.px(e4), l2 = this.py(e4), u2 = n3 + 2 * e4 * (r2 - n3) + e4 * e4 * (i2 - 2 * r2 + n3), d2 = a2 + 2 * e4 * (o2 - a2) + e4 * e4 * (s2 - 2 * o2 + a2), f2 = r2 + e4 * (i2 - r2), p2 = o2 + e4 * (s2 - o2), m2 = new U.Point(c2, l2), h2 = new U.Point(c2 + t4 * (u2 - c2), l2 + t4 * (d2 - l2)), g2 = new U.Point(c2 + 2 * t4 * (u2 - c2) + t4 * t4 * (f2 - 2 * u2 + c2), l2 + 2 * t4 * (d2 - l2) + t4 * t4 * (p2 - 2 * d2 + l2)), _2 = new U.Point(this.px(t4), this.py(t4));
            return new X.CubicBezier(m2, h2, g2, _2);
          }
        } }, { key: `tOfIntersections`, value: function(e4) {
          if (e4.isPoint()) return [];
          if (e4.isRect()) {
            var t4, n3 = e4.x + e4.r, r2 = e4.x - e4.l, i2 = e4.y + e4.u, a2 = e4.y - e4.d, o2 = rt, s2 = this.cp0.x, c2 = this.cp1.x, l2 = this.cp2.x, u2 = this.cp3.x, d2 = this.cp0.y, f2 = this.cp1.y, p2 = this.cp2.y, m2 = this.cp3.y, h2 = o2(s2), g2 = o2(3 * (c2 - s2)), _2 = o2(3 * (l2 - 2 * c2 + s2)), v2 = o2(u2 - 3 * l2 + 3 * c2 - s2), y2 = function(e5) {
              return h2 + e5 * g2 + e5 * e5 * _2 + e5 * e5 * e5 * v2;
            }, b2 = o2(d2), x2 = o2(3 * (f2 - d2)), S2 = o2(3 * (p2 - 2 * f2 + d2)), C2 = o2(m2 - 3 * p2 + 3 * f2 - d2), w2 = function(e5) {
              return b2 + e5 * x2 + e5 * e5 * S2 + e5 * e5 * e5 * C2;
            }, T2 = [];
            t4 = (t4 = X.solutionsOfCubicEq(v2, _2, g2, h2 - n3)).concat(X.solutionsOfCubicEq(v2, _2, g2, h2 - r2));
            for (var E2 = 0; E2 < t4.length; E2++) (te2 = w2(he2 = t4[E2])) >= a2 && te2 <= i2 && T2.push(he2);
            for (t4 = (t4 = X.solutionsOfCubicEq(C2, S2, x2, b2 - i2)).concat(X.solutionsOfCubicEq(C2, S2, x2, b2 - a2)), E2 = 0; E2 < t4.length; E2++) (ee2 = y2(he2 = t4[E2])) >= r2 && ee2 <= n3 && T2.push(he2);
            return T2;
          }
          if (e4.isCircle()) {
            var D2 = Math.PI, ee2 = e4.x, te2 = e4.y, ne2 = e4.l, O2 = e4.r, re2 = e4.u, ie2 = e4.d, ae2 = ee2 + (O2 - ne2) / 2, oe2 = te2 + (re2 - ie2) / 2, se2 = (n3 = (ne2 + O2) / 2, (re2 + ie2) / 2), ce2 = D2 / 180, le2 = new Z.Arc(ae2, oe2, n3, se2, -D2 - ce2, -D2 / 2 + ce2), ue2 = new Z.Arc(ae2, oe2, n3, se2, -D2 / 2 - ce2, 0 + ce2), de2 = new Z.Arc(ae2, oe2, n3, se2, 0 - ce2, D2 / 2 + ce2), fe2 = new Z.Arc(ae2, oe2, n3, se2, D2 / 2 - ce2, D2 + ce2), pe2 = new Z.CubicBezier(this, 0, 1), me2 = [];
            for (me2 = (me2 = (me2 = (me2 = me2.concat(Z.findIntersections(le2, pe2))).concat(Z.findIntersections(ue2, pe2))).concat(Z.findIntersections(de2, pe2))).concat(Z.findIntersections(fe2, pe2)), T2 = [], E2 = 0; E2 < me2.length; E2++) {
              var he2 = (me2[E2][1].min + me2[E2][1].max) / 2;
              T2.push(he2);
            }
            return T2;
          }
        } }, { key: `countOfSegments`, value: function() {
          return 1;
        } }, { key: `drawPrimitive`, value: function(e4, t4) {
          var n3 = this.cp0, r2 = this.cp1, i2 = this.cp2, a2 = this.cp3;
          e4.createSVGElement(`path`, { d: `M` + A.measure.em2px(n3.x) + `,` + A.measure.em2px(-n3.y) + ` C` + A.measure.em2px(r2.x) + `,` + A.measure.em2px(-r2.y) + ` ` + A.measure.em2px(i2.x) + `,` + A.measure.em2px(-i2.y) + ` ` + A.measure.em2px(a2.x) + `,` + A.measure.em2px(-a2.y), "stroke-dasharray": t4 });
        } }, { key: `toString`, value: function() {
          return `CubicBezier(` + this.cp0.x + `, ` + this.cp0.y + `)-(` + this.cp1.x + `, ` + this.cp1.y + `)-(` + this.cp2.x + `, ` + this.cp2.y + `)-(` + this.cp3.x + `, ` + this.cp3.y + `)`;
        } }]), n2;
      })(X), X.CubicBeziers = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4) {
          var r2;
          kt(this, n2), (r2 = t3.call(this)).cbs = e4;
          var i2 = r2.cbs.length;
          return r2.delegate = i2 == 0 ? function(e5, t4, n3) {
            return n3;
          } : function(t4, n3, r3) {
            var a2 = t4 * i2, o2 = Math.floor(a2);
            o2 < 0 && (o2 = 0), o2 >= i2 && (o2 = i2 - 1);
            var s2 = a2 - o2;
            return n3(e4[o2], s2);
          }, r2;
        }
        return jt(n2, [{ key: `startPosition`, value: function() {
          return this.cbs[0].cp0;
        } }, { key: `endPosition`, value: function() {
          return this.cbs[this.cbs.length - 1].cp3;
        } }, { key: `position`, value: function(e4) {
          return this.delegate(e4, (function(e5, t4) {
            return e5.position(t4);
          }), void 0);
        } }, { key: `derivative`, value: function(e4) {
          return this.delegate(e4, (function(e5, t4) {
            return e5.derivative(t4);
          }), void 0);
        } }, { key: `angle`, value: function(e4) {
          return this.delegate(e4, (function(e5, t4) {
            return e5.angle(t4);
          }), 0);
        } }, { key: `velocity`, value: function(e4) {
          var t4 = this.cbs.length;
          return this.delegate(e4, (function(e5, n3) {
            return t4 * e5.velocity(n3);
          }), 0);
        } }, { key: `boundingBox`, value: function(e4) {
          if (this.cbs.length != 0) {
            var t4, n3 = this.cbs[0].boundingBox(e4), r2 = this.cbs.length;
            for (t4 = 1; t4 < r2; t4++) n3 = n3.combineRect(this.cbs[t4].boundingBox(e4));
            return n3;
          }
        } }, { key: `tOfIntersections`, value: function(e4) {
          var t4 = [], n3 = 0, r2 = this.cbs.length;
          for (n3 = 0; n3 < r2; n3++) for (var i2 = this.cbs[n3].tOfIntersections(e4), a2 = 0; a2 < i2.length; a2++) t4.push((i2[a2] + n3) / r2);
          return t4;
        } }, { key: `divide`, value: function(e4) {
          if (e4 < 0 || e4 > 1) throw c(`ExecutionError`, `illegal cubic Bezier parameter t:` + e4);
          if (e4 === 0) return [new X.CubicBeziers([]), this];
          if (e4 === 1) return [this, new X.CubicBeziers([])];
          var t4 = this.cbs.length, n3 = e4 * t4, r2 = Math.floor(n3);
          r2 === t4 && (r2 = t4 - 1);
          var i2 = n3 - r2, a2 = this.cbs.slice(0, r2), o2 = this.cbs.slice(r2 + 1), s2 = this.cbs[r2].divide(i2);
          return a2.push(s2[0]), o2.unshift(s2[1]), [new X.CubicBeziers(a2), new X.CubicBeziers(o2)];
        } }, { key: `slice`, value: function(e4, t4) {
          if (!(e4 >= t4)) {
            if (e4 < 0 && (e4 = 0), t4 > 1 && (t4 = 1), e4 === 0 && t4 === 1) return this;
            var n3 = this.cbs.length, r2 = e4 * n3, i2 = t4 * n3, a2 = Math.floor(r2), o2 = Math.floor(i2);
            a2 === n3 && (a2 = n3 - 1), o2 === n3 && (o2 = n3 - 1);
            var s2, c2 = r2 - a2, l2 = i2 - o2;
            return a2 === o2 ? s2 = [this.cbs[a2].slice(c2, l2)] : ((s2 = this.cbs.slice(a2 + 1, o2)).push(this.cbs[o2].slice(0, l2)), s2.unshift(this.cbs[a2].slice(c2, 1))), new X.CubicBeziers(s2);
          }
        } }, { key: `countOfSegments`, value: function() {
          return this.cbs.length;
        } }, { key: `drawPrimitive`, value: function(e4, t4) {
          for (var n3 = this.cbs.length, r2 = this.cbs, i2 = r2[0], a2 = i2.cp0, o2 = i2.cp1, s2 = i2.cp2, c2 = i2.cp3, l2 = `M` + A.measure.em2px(a2.x) + `,` + A.measure.em2px(-a2.y) + ` C` + A.measure.em2px(o2.x) + `,` + A.measure.em2px(-o2.y) + ` ` + A.measure.em2px(s2.x) + `,` + A.measure.em2px(-s2.y) + ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y), u2 = 1; u2 < n3; u2++) s2 = (i2 = r2[u2]).cp2, c2 = i2.cp3, l2 += ` S` + A.measure.em2px(s2.x) + `,` + A.measure.em2px(-s2.y) + ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y);
          e4.createSVGElement(`path`, { d: l2, "stroke-dasharray": t4 });
        } }, { key: `drawSkipped`, value: function(e4) {
          for (var t4 = this.cbs.length, n3 = this.cbs, r2 = ``, i2 = 0; i2 < t4; i2 += 2) {
            var a2 = n3[i2], o2 = a2.cp0, s2 = a2.cp1, c2 = a2.cp2, l2 = a2.cp3;
            r2 += `M` + A.measure.em2px(o2.x) + `,` + A.measure.em2px(-o2.y) + ` C` + A.measure.em2px(s2.x) + `,` + A.measure.em2px(-s2.y) + ` ` + A.measure.em2px(c2.x) + `,` + A.measure.em2px(-c2.y) + ` ` + A.measure.em2px(l2.x) + `,` + A.measure.em2px(-l2.y);
          }
          e4.createSVGElement(`path`, { d: r2 });
        } }], [{ key: `interpolation`, value: function(e4, t4, n3) {
          var r2, i2 = X.CubicBeziers.cubicSplineInterpolation(e4, t4), a2 = i2[0], o2 = i2[1], s2 = X.CubicBeziers.cubicSplineInterpolation(e4, n3), c2 = s2[0], l2 = s2[1], u2 = e4.length, d2 = Array(u2 - 1);
          for (r2 = 0; r2 < u2 - 1; r2++) d2[r2] = new X.CubicBezier(new U.Point(t4[r2], n3[r2]), new U.Point(a2[r2], c2[r2]), new U.Point(o2[r2], l2[r2]), new U.Point(t4[r2 + 1], n3[r2 + 1]));
          return new X.CubicBeziers(d2);
        } }, { key: `cubicSplineInterpolation`, value: function(e4, t4) {
          var n3, r2 = e4.length - 1, i2 = Array(r2);
          for (n3 = 0; n3 < r2; n3++) i2[n3] = e4[n3 + 1] - e4[n3];
          var a2 = Array(r2);
          for (n3 = 1; n3 < r2; n3++) a2[n3] = 3 * (t4[n3 + 1] - t4[n3]) / i2[n3] - 3 * (t4[n3] - t4[n3 - 1]) / i2[n3 - 1];
          var o2 = Array(r2 + 1), s2 = Array(r2 + 1), c2 = Array(r2 + 1);
          for (o2[0] = 1, s2[0] = 0, c2[0] = 0, n3 = 1; n3 < r2; n3++) o2[n3] = 2 * (e4[n3 + 1] - e4[n3 - 1]) - i2[n3 - 1] * s2[n3 - 1], s2[n3] = i2[n3] / o2[n3], c2[n3] = (a2[n3] - i2[n3 - 1] * c2[n3 - 1]) / o2[n3];
          o2[r2] = 1, c2[r2] = 0;
          var l2 = Array(r2), u2 = Array(r2 + 1);
          for (u2[r2] = 0, n3 = r2 - 1; n3 >= 0; n3--) {
            var d2 = i2[n3], f2 = u2[n3 + 1], p2 = d2 * d2 * c2[n3] - s2[n3] * f2;
            u2[n3] = p2, l2[n3] = t4[n3 + 1] - t4[n3] - (f2 + 2 * p2) / 3;
          }
          var m2 = Array(r2), h2 = Array(r2);
          for (n3 = 0; n3 < r2; n3++) {
            var g2 = t4[n3], _2 = l2[n3], v2 = u2[n3];
            m2[n3] = g2 + _2 / 3, h2[n3] = g2 + (2 * _2 + v2) / 3;
          }
          return [m2, h2];
        } }]), n2;
      })(X), X.CubicBSpline = (function() {
        function e3(t3, n2, r2) {
          if (kt(this, e3), n2.length < 1) throw c(`ExecutionError`, `the number of internal control points of cubic B-spline must be greater than or equal to 1`);
          var i2 = [];
          i2.push(t3);
          for (var a2 = 0, o2 = n2.length; a2 < o2; a2++) i2.push(n2[a2]);
          i2.push(r2), this.cps = i2;
          var s2 = this.cps.length - 1, l2 = function(e4) {
            return e4 < 0 ? i2[0] : e4 > s2 ? i2[s2] : i2[e4];
          }, u2 = function(e4) {
            var t4 = Math.abs(e4);
            return t4 <= 1 ? (3 * t4 * t4 * t4 - 6 * t4 * t4 + 4) / 6 : t4 <= 2 ? -(t4 - 2) * (t4 - 2) * (t4 - 2) / 6 : 0;
          };
          this.px = function(e4) {
            for (var t4 = (s2 + 2) * e4 - 1, n3 = Math.ceil(t4 - 2), r3 = Math.floor(t4 + 2), i3 = 0, a3 = n3; a3 <= r3; a3++) i3 += u2(t4 - a3) * l2(a3).x;
            return i3;
          }, this.py = function(e4) {
            for (var t4 = (s2 + 2) * e4 - 1, n3 = Math.ceil(t4 - 2), r3 = Math.floor(t4 + 2), i3 = 0, a3 = n3; a3 <= r3; a3++) i3 += u2(t4 - a3) * l2(a3).y;
            return i3;
          };
          var d2 = function(e4) {
            var t4 = e4 > 0 ? 1 : e4 < 0 ? -1 : 0, n3 = Math.abs(e4);
            return n3 <= 1 ? t4 * (3 * n3 * n3 - 4 * n3) / 2 : n3 <= 2 ? -t4 * (n3 - 2) * (n3 - 2) / 2 : 0;
          };
          this.dpx = function(e4) {
            for (var t4 = (s2 + 2) * e4 - 1, n3 = Math.ceil(t4 - 2), r3 = Math.floor(t4 + 2), i3 = 0, a3 = n3; a3 <= r3; a3++) i3 += d2(t4 - a3) * l2(a3).x;
            return i3;
          }, this.dpy = function(e4) {
            for (var t4 = (s2 + 2) * e4 - 1, n3 = Math.ceil(t4 - 2), r3 = Math.floor(t4 + 2), i3 = 0, a3 = n3; a3 <= r3; a3++) i3 += d2(t4 - a3) * l2(a3).y;
            return i3;
          };
        }
        return jt(e3, [{ key: `position`, value: function(e4) {
          return new U.Point(this.px(e4), this.py(e4));
        } }, { key: `angle`, value: function(e4) {
          return Math.atan2(this.dpy(e4), this.dpx(e4));
        } }, { key: `toCubicBeziers`, value: function() {
          var e4 = [], t3 = this.cps, n2 = t3[0], r2 = t3[1], i2 = t3[2], a2 = n2.x, o2 = n2.y, s2 = a2 + (r2.x - a2) / 3, c2 = o2 + (r2.y - o2) / 3, l2 = a2 + 2 * (r2.x - a2) / 3, u2 = o2 + 2 * (r2.y - o2) / 3, d2 = r2.x + (i2.x - r2.x) / 3, f2 = r2.y + (i2.y - r2.y) / 3, p2 = (l2 + d2) / 2, m2 = (u2 + f2) / 2, h2 = n2, g2 = new U.Point(s2, c2), _2 = new U.Point(l2, u2), v2 = new U.Point(p2, m2), y2 = new X.CubicBezier(h2, g2, _2, v2);
          e4.push(y2);
          for (var b2 = this.cps.length - 1, x2 = 2; x2 < b2; x2++) n2 = r2, r2 = i2, i2 = t3[x2 + 1], a2 = p2, o2 = m2, s2 = 2 * p2 - l2, c2 = 2 * m2 - u2, l2 = n2.x + 2 * (r2.x - n2.x) / 3, u2 = n2.y + 2 * (r2.y - n2.y) / 3, p2 = (l2 + (d2 = r2.x + (i2.x - r2.x) / 3)) / 2, m2 = (u2 + (f2 = r2.y + (i2.y - r2.y) / 3)) / 2, h2 = v2, g2 = new U.Point(s2, c2), _2 = new U.Point(l2, u2), v2 = new U.Point(p2, m2), y2 = new X.CubicBezier(h2, g2, _2, v2), e4.push(y2);
          return n2 = r2, r2 = i2, a2 = p2, o2 = m2, s2 = 2 * p2 - l2, c2 = 2 * m2 - u2, l2 = n2.x + 2 * (r2.x - n2.x) / 3, u2 = n2.y + 2 * (r2.y - n2.y) / 3, p2 = r2.x, m2 = r2.y, h2 = v2, g2 = new U.Point(s2, c2), _2 = new U.Point(l2, u2), v2 = new U.Point(p2, m2), y2 = new X.CubicBezier(h2, g2, _2, v2), e4.push(y2), e4;
        } }, { key: `countOfSegments`, value: function() {
          return this.cps.length - 1;
        } }]), e3;
      })(), X.Line = (function() {
        function e3(t3, n2) {
          kt(this, e3), this.s = t3, this.e = n2;
        }
        return jt(e3, [{ key: `position`, value: function(e4) {
          return new U.Point(this.s.x + e4 * (this.e.x - this.s.x), this.s.y + e4 * (this.e.y - this.s.y));
        } }, { key: `slice`, value: function(e4, t3) {
          if (!(e4 >= t3)) {
            if (e4 < 0 && (e4 = 0), t3 > 1 && (t3 = 1), e4 === 0 && t3 === 1) return this;
            var n2 = this.s, r2 = this.e, i2 = r2.x - n2.x, a2 = r2.y - n2.y, o2 = new U.Point(n2.x + e4 * i2, n2.y + e4 * a2), s2 = new U.Point(n2.x + t3 * i2, n2.y + t3 * a2);
            return new X.Line(o2, s2);
          }
        } }, { key: `tOfIntersections`, value: function(e4) {
          if (e4.isPoint()) return [];
          var t3 = this.s, n2 = this.e;
          if (e4.isRect()) {
            var r2, i2 = e4.x + e4.r, a2 = e4.x - e4.l, o2 = e4.y + e4.u, s2 = e4.y - e4.d, c2 = t3.x, l2 = t3.y, u2 = n2.x - c2, d2 = n2.y - l2, f2 = function(e5) {
              return c2 + e5 * u2;
            }, p2 = function(e5) {
              return l2 + e5 * d2;
            }, m2 = [];
            r2 = (r2 = X.solutionsOfLinearEq(u2, c2 - i2)).concat(X.solutionsOfLinearEq(u2, c2 - a2));
            for (var h2 = 0; h2 < r2.length; h2++) {
              var g2 = p2(_2 = r2[h2]);
              g2 >= s2 && g2 <= o2 && m2.push(_2);
            }
            for (r2 = (r2 = X.solutionsOfLinearEq(d2, l2 - o2)).concat(X.solutionsOfLinearEq(d2, l2 - s2)), h2 = 0; h2 < r2.length; h2++) {
              var _2, v2 = f2(_2 = r2[h2]);
              v2 >= a2 && v2 <= i2 && m2.push(_2);
            }
            return m2;
          }
          if (e4.isCircle()) {
            var y2 = e4.l, b2 = e4.r, x2 = e4.u, S2 = e4.d, C2 = e4.x + (b2 - y2) / 2, w2 = e4.y + (x2 - S2) / 2, T2 = (i2 = (y2 + b2) / 2, (x2 + S2) / 2), E2 = t3.x, D2 = t3.y, ee2 = n2.x - E2, te2 = -ee2, ne2 = (s2 = n2.y - D2) * i2, O2 = te2 * T2, re2 = ne2 * ne2 + O2 * O2, ie2 = (n2 = -(S2 = ne2 * C2 + O2 * w2 + ((ee2 * D2 - s2 * E2) * i2 + (i2 - T2) * te2 * w2)) / re2, re2 * i2 * i2 - S2 * S2);
            if (ie2 < 0) return [];
            var ae2, oe2, se2 = Math.sqrt(ie2) / re2, ce2 = T2 / i2, le2 = ne2 * n2 + O2 * se2 + C2, ue2 = ce2 * (O2 * n2 - ne2 * se2 + w2 - w2) + w2, de2 = ne2 * n2 - O2 * se2 + C2, fe2 = ce2 * (O2 * n2 + ne2 * se2 + w2 - w2) + w2;
            return Math.abs(ee2) > Math.abs(s2) ? (ae2 = (le2 - E2) / ee2, oe2 = (de2 - E2) / ee2) : (ae2 = (ue2 - D2) / s2, oe2 = (fe2 - D2) / s2), m2 = [], ae2 >= 0 && ae2 <= 1 && m2.push(ae2), oe2 >= 0 && oe2 <= 1 && m2.push(oe2), m2;
          }
        } }, { key: `toShape`, value: function(e4, t3, n2, r2) {
          var i2 = e4.env, a2 = A.measure.thickness, o2 = this.s, s2 = this.e;
          if (o2.x !== s2.x || o2.y !== s2.y) {
            var c2, l2 = s2.x - o2.x, u2 = s2.y - o2.y, d2 = Math.atan2(u2, l2), f2 = Y.none;
            switch (n2) {
              case `=`:
                n2 = `-`, r2 = `2`;
                break;
              case `==`:
                n2 = `--`, r2 = `2`;
                break;
              case `:`:
              case `::`:
                n2 = `.`, r2 = `2`;
            }
            switch (n2) {
              case ``:
                return i2.angle = d2, i2.lastCurve = new Q.Line(o2, s2, i2.p, i2.c, void 0), f2;
              case `-`:
              case `.`:
              case `..`:
                switch (r2) {
                  case `2`:
                    c2 = a2 / 2;
                    break;
                  case `3`:
                    c2 = a2;
                    break;
                  default:
                    c2 = 0;
                }
                break;
              case `--`:
                var p2 = 3 * a2;
                if ((g2 = Math.sqrt(l2 * l2 + u2 * u2)) >= p2) switch (r2) {
                  case `2`:
                    c2 = a2 / 2;
                    break;
                  case `3`:
                    c2 = a2;
                    break;
                  default:
                    c2 = 0;
                }
                break;
              case `~`:
              case `~~`:
                switch (r2) {
                  case `2`:
                    c2 = 1.5 * a2;
                    break;
                  case `3`:
                    c2 = 2 * a2;
                    break;
                  default:
                    c2 = 0;
                }
                break;
              default:
                var m2 = t3.boundingBox(e4);
                if (m2 == null) return i2.angle = 0, i2.lastCurve = Q.none, Y.none;
                var h2 = m2.l + m2.r;
                h2 == 0 && (h2 = A.measure.strokeWidth);
                var g2 = Math.sqrt(l2 * l2 + u2 * u2);
                if (Math.floor(g2 / h2) == 0) return i2.angle = 0, i2.lastCurve = Q.none, Y.none;
                c2 = Math.max(m2.u, m2.d);
            }
            if (c2 !== void 0) {
              var _2 = this.boundingBox(c2);
              return f2 = new Y.LineShape(this, t3, n2, r2, _2), e4.appendShapeToFront(f2), i2.angle = d2, i2.lastCurve = new Q.Line(o2, s2, i2.p, i2.c, f2), f2;
            }
          }
          return i2.angle = 0, i2.lastCurve = Q.none, Y.none;
        } }, { key: `boundingBox`, value: function(e4) {
          var t3 = this.s, n2 = this.e, r2 = n2.x - t3.x, i2 = n2.y - t3.y, a2 = Math.atan2(i2, r2), o2 = e4 * Math.cos(a2 + Math.PI / 2), s2 = e4 * Math.sin(a2 + Math.PI / 2);
          return new U.Rect(t3.x, t3.y, { l: t3.x - Math.min(t3.x + o2, t3.x - o2, n2.x + o2, n2.x - o2), r: Math.max(t3.x + o2, t3.x - o2, n2.x + o2, n2.x - o2) - t3.x, u: Math.max(t3.y + s2, t3.y - s2, n2.y + s2, n2.y - s2) - t3.y, d: t3.y - Math.min(t3.y + s2, t3.y - s2, n2.y + s2, n2.y - s2) });
        } }, { key: `drawLine`, value: function(e4, t3, n2, r2, i2) {
          if (i2.isEmpty) this._drawLine(e4, t3, n2, r2);
          else {
            var a2 = new bt(0, 1).differenceRanges(i2), o2 = this;
            a2.foreach((function(i3) {
              o2.slice(i3.start, i3.end)._drawLine(e4, t3, n2, r2);
            }));
          }
        } }, { key: `_drawLine`, value: function(e4, t3, n2, r2) {
          var i2 = A.measure.thickness, a2 = this.s, o2 = this.e;
          if (a2.x !== o2.x || a2.y !== o2.y) {
            var s2 = o2.x - a2.x, c2 = o2.y - a2.y, l2 = Math.atan2(c2, s2), u2 = { x: 0, y: 0 };
            switch (n2) {
              case ``:
                break;
              case `-`:
                this.drawStraightLine(e4, a2, o2, u2, l2, i2, r2, ``);
                break;
              case `=`:
                this.drawStraightLine(e4, a2, o2, u2, l2, i2, `2`, ``);
                break;
              case `.`:
              case `..`:
                this.drawStraightLine(e4, a2, o2, u2, l2, i2, r2, A.measure.dottedDasharray);
                break;
              case `:`:
              case `::`:
                this.drawStraightLine(e4, a2, o2, u2, l2, i2, `2`, A.measure.dottedDasharray);
                break;
              case `--`:
              case `==`:
                var d2 = 3 * i2;
                (E2 = Math.sqrt(s2 * s2 + c2 * c2)) >= d2 && (u2 = { x: (D2 = (E2 - d2) / 2 - Math.floor((E2 - d2) / 2 / d2) * d2) * Math.cos(l2), y: D2 * Math.sin(l2) }, this.drawStraightLine(e4, a2, o2, u2, l2, i2, n2 === `==` ? `2` : r2, A.measure.em2px(d2) + ` ` + A.measure.em2px(d2)));
                break;
              case `~`:
                if ((E2 = Math.sqrt(s2 * s2 + c2 * c2)) >= (b2 = 4 * i2)) {
                  u2 = { x: (D2 = (E2 - (T2 = Math.floor(E2 / b2)) * b2) / 2) * Math.cos(l2), y: D2 * Math.sin(l2) };
                  for (var f2 = i2 * Math.cos(l2 + Math.PI / 2), p2 = i2 * Math.sin(l2 + Math.PI / 2), m2 = i2 * Math.cos(l2), h2 = i2 * Math.sin(l2), g2 = a2.x + u2.x, _2 = -a2.y - u2.y, v2 = `M` + A.measure.em2px(g2) + `,` + A.measure.em2px(_2) + ` Q` + A.measure.em2px(g2 + m2 + f2) + `,` + A.measure.em2px(_2 - h2 - p2) + ` ` + A.measure.em2px(g2 + 2 * m2) + `,` + A.measure.em2px(_2 - 2 * h2) + ` T` + A.measure.em2px(g2 + 4 * m2) + `,` + A.measure.em2px(_2 - 4 * h2), y2 = 1; y2 < T2; y2++) v2 += ` T` + A.measure.em2px(g2 + (4 * y2 + 2) * m2) + `,` + A.measure.em2px(_2 - (4 * y2 + 2) * h2) + ` T` + A.measure.em2px(g2 + (4 * y2 + 4) * m2) + `,` + A.measure.em2px(_2 - (4 * y2 + 4) * h2);
                  this.drawSquigglyLineShape(e4, v2, a2, o2, f2, p2, r2);
                }
                break;
              case `~~`:
                var b2;
                if ((E2 = Math.sqrt(s2 * s2 + c2 * c2)) >= (b2 = 4 * i2)) {
                  for (u2 = { x: (D2 = (E2 - b2) / 2 - (T2 = Math.floor((E2 - b2) / 2 / b2)) * b2) * Math.cos(l2), y: D2 * Math.sin(l2) }, f2 = i2 * Math.cos(l2 + Math.PI / 2), p2 = i2 * Math.sin(l2 + Math.PI / 2), m2 = i2 * Math.cos(l2), h2 = i2 * Math.sin(l2), g2 = a2.x + u2.x, _2 = -a2.y - u2.y, v2 = ``, y2 = 0; y2 <= T2; y2++) v2 += ` M` + A.measure.em2px(g2 + 8 * y2 * m2) + `,` + A.measure.em2px(_2 - 8 * y2 * h2) + ` Q` + A.measure.em2px(g2 + (8 * y2 + 1) * m2 + f2) + `,` + A.measure.em2px(_2 - (8 * y2 + 1) * h2 - p2) + ` ` + A.measure.em2px(g2 + (8 * y2 + 2) * m2) + `,` + A.measure.em2px(_2 - (8 * y2 + 2) * h2) + ` T` + A.measure.em2px(g2 + (8 * y2 + 4) * m2) + `,` + A.measure.em2px(_2 - (8 * y2 + 4) * h2);
                  this.drawSquigglyLineShape(e4, v2, a2, o2, f2, p2, r2);
                }
                break;
              default:
                var x2 = new Mt();
                x2.c = Mt.originPosition;
                var S2 = new St(Y.none, x2), C2 = t3.boundingBox(S2);
                if (C2 == null) return;
                var w2 = C2.l + C2.r;
                w2 == 0 && (w2 = A.measure.strokeWidth);
                var T2, E2 = Math.sqrt(s2 * s2 + c2 * c2);
                if ((T2 = Math.floor(E2 / w2)) == 0) return;
                var D2 = (E2 - T2 * w2) / 2, ee2 = Math.cos(l2), te2 = Math.sin(l2), ne2 = w2 * ee2, O2 = w2 * te2, re2 = a2.x + (D2 + C2.l) * ee2, ie2 = a2.y + (D2 + C2.l) * te2;
                for (S2 = new St(Y.none, x2), y2 = 0; y2 < T2; y2++) x2.c = new U.Point(re2 + y2 * ne2, ie2 + y2 * O2), x2.angle = l2, t3.toDropShape(S2).draw(e4);
            }
          }
        } }, { key: `drawStraightLine`, value: function(e4, t3, n2, r2, i2, a2, o2, s2) {
          if (o2 === `3`) {
            var c2 = a2 * Math.cos(i2 + Math.PI / 2), l2 = a2 * Math.sin(i2 + Math.PI / 2);
            e4.createSVGElement(`line`, { x1: A.measure.em2px(t3.x + r2.x), y1: -A.measure.em2px(t3.y + r2.y), x2: A.measure.em2px(n2.x), y2: -A.measure.em2px(n2.y), "stroke-dasharray": s2 }), e4.createSVGElement(`line`, { x1: A.measure.em2px(t3.x + c2 + r2.x), y1: -A.measure.em2px(t3.y + l2 + r2.y), x2: A.measure.em2px(n2.x + c2), y2: -A.measure.em2px(n2.y + l2), "stroke-dasharray": s2 }), e4.createSVGElement(`line`, { x1: A.measure.em2px(t3.x - c2 + r2.x), y1: -A.measure.em2px(t3.y - l2 + r2.y), x2: A.measure.em2px(n2.x - c2), y2: -A.measure.em2px(n2.y - l2), "stroke-dasharray": s2 });
          } else o2 === `2` ? (c2 = a2 * Math.cos(i2 + Math.PI / 2) / 2, l2 = a2 * Math.sin(i2 + Math.PI / 2) / 2, e4.createSVGElement(`line`, { x1: A.measure.em2px(t3.x + c2 + r2.x), y1: -A.measure.em2px(t3.y + l2 + r2.y), x2: A.measure.em2px(n2.x + c2), y2: -A.measure.em2px(n2.y + l2), "stroke-dasharray": s2 }), e4.createSVGElement(`line`, { x1: A.measure.em2px(t3.x - c2 + r2.x), y1: -A.measure.em2px(t3.y - l2 + r2.y), x2: A.measure.em2px(n2.x - c2), y2: -A.measure.em2px(n2.y - l2), "stroke-dasharray": s2 })) : e4.createSVGElement(`line`, { x1: A.measure.em2px(t3.x + r2.x), y1: -A.measure.em2px(t3.y + r2.y), x2: A.measure.em2px(n2.x), y2: -A.measure.em2px(n2.y), "stroke-dasharray": s2 });
        } }, { key: `drawSquigglyLineShape`, value: function(e4, t3, n2, r2, i2, a2, o2) {
          o2 === `3` ? (e4.createSVGElement(`path`, { d: t3 }), e4.createGroup(e4.transformBuilder().translate(i2, a2)).createSVGElement(`path`, { d: t3 }), e4.createGroup(e4.transformBuilder().translate(-i2, -a2)).createSVGElement(`path`, { d: t3 })) : o2 === `2` ? (e4.createGroup(e4.transformBuilder().translate(i2 / 2, a2 / 2)).createSVGElement(`path`, { d: t3 }), e4.createGroup(e4.transformBuilder().translate(-i2 / 2, -a2 / 2)).createSVGElement(`path`, { d: t3 })) : e4.createSVGElement(`path`, { d: t3 });
        } }]), e3;
      })();
      var Z = (function() {
        function e3() {
          kt(this, e3);
        }
        return jt(e3, [{ key: `bezierFatLine`, value: function(e4) {
          var t3, n2, r2, i2, a2 = this.cps[0], o2 = this.cps[e4];
          if (a2.x !== o2.x || a2.y !== o2.y) t3 = a2.y - o2.y, n2 = o2.x - a2.x, t3 /= i2 = Math.sqrt(t3 * t3 + n2 * n2), n2 /= i2, r2 = (a2.x * o2.y - a2.y * o2.x) / i2;
          else {
            var s2 = this.bezier.angle(this.tmin);
            t3 = -Math.sin(s2), n2 = Math.cos(s2), r2 = -t3 * this.cp0.x - n2 * this.cp0.y;
          }
          for (var c2 = r2, l2 = r2, u2 = 1; u2 < e4; u2++) {
            var d2 = -t3 * this.cps[u2].x - n2 * this.cps[u2].y;
            d2 > l2 ? l2 = d2 : d2 < c2 && (c2 = d2);
          }
          return { min: [t3, n2, c2], max: [t3, n2, l2] };
        } }, { key: `clippedLineRange`, value: function(e4, t3, n2) {
          for (var r2, i2, a2, o2, s2, c2 = e4.length - 1, l2 = Array(c2 + 1), u2 = tt, d2 = 0; d2 <= c2; d2++) l2[d2] = [d2 / c2, -t3[0] * e4[d2].x - t3[1] * e4[d2].y - t3[2], 1];
          if (l2[0][1] < 0) {
            var f2 = true;
            for (d2 = 1; d2 <= c2; d2++) (r2 = -(m2 = u2(l2[0], l2[d2]))[2] / m2[0]) > 0 && r2 < 1 && (i2 === void 0 || r2 < i2) && (i2 = r2), l2[d2][1] >= 0 && (f2 = false);
            if (f2) return;
          } else i2 = 0;
          if (l2[c2][1] < 0) for (d2 = 0; d2 < c2; d2++) (r2 = -(h2 = u2(l2[c2], l2[d2]))[2] / h2[0]) > 0 && r2 < 1 && (a2 === void 0 || r2 > a2) && (a2 = r2);
          else a2 = 1;
          for (d2 = 0; d2 <= c2; d2++) l2[d2] = [d2 / c2, n2[0] * e4[d2].x + n2[1] * e4[d2].y + n2[2], 1];
          if (l2[0][1] < 0) {
            var p2 = true;
            for (d2 = 1; d2 <= c2; d2++) {
              var m2;
              (r2 = -(m2 = u2(l2[0], l2[d2]))[2] / m2[0]) > 0 && r2 < 1 && (o2 === void 0 || r2 < o2) && (o2 = r2), l2[d2][1] >= 0 && (p2 = false);
            }
            if (p2) return;
          } else o2 = 0;
          if (l2[c2][1] < 0) for (d2 = 0; d2 < c2; d2++) {
            var h2;
            (r2 = -(h2 = u2(l2[c2], l2[d2]))[2] / h2[0]) > 0 && r2 < 1 && (s2 === void 0 || r2 > s2) && (s2 = r2);
          }
          else s2 = 1;
          var g2 = Math.max(i2, o2), _2 = Math.min(a2, s2);
          return { min: this.tmin + g2 * (this.tmax - this.tmin), max: this.tmin + _2 * (this.tmax - this.tmin) };
        } }], [{ key: `findIntersections`, value: function(t3, n2) {
          for (var r2 = e3.maxIterations, i2 = e3.goalAccuracy, a2 = [[t3, n2, false]], o2 = 0, s2 = []; o2 < r2 && a2.length > 0; ) {
            o2++;
            var c2 = a2.shift(), l2 = (t3 = c2[0], n2 = c2[1], c2[2]), u2 = t3.fatLine(), d2 = n2.clippedRange(u2.min, u2.max);
            if (d2 != null) {
              var f2 = d2.min, p2 = d2.max, m2 = p2 - f2;
              if (m2 < i2 && t3.paramLength() < i2) l2 ? s2.push([n2.clip(f2, p2).paramRange(), t3.paramRange()]) : s2.push([t3.paramRange(), n2.clip(f2, p2).paramRange()]);
              else if (m2 <= 0.8 * n2.paramLength()) a2.push([n2.clip(f2, p2), t3, !l2]);
              else if (m2 > t3.paramLength()) {
                var h2 = (p2 + f2) / 2;
                a2.push([n2.clip(f2, h2), t3, !l2]), a2.push([n2.clip(h2, p2), t3, !l2]);
              } else {
                var g2 = n2.clip(f2, p2), _2 = t3.paramRange(), v2 = (_2.min + _2.max) / 2;
                a2.push([g2, t3.clip(_2.min, v2), !l2]), a2.push([g2, t3.clip(v2, _2.max), !l2]);
              }
            }
          }
          return s2;
        } }, { key: `maxIterations`, get: function() {
          return 30;
        } }, { key: `goalAccuracy`, get: function() {
          return 1e-4;
        } }]), e3;
      })();
      Z.Line = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4, r2, i2, a2) {
          var o2;
          return kt(this, n2), (o2 = t3.call(this)).p0 = e4, o2.p1 = r2, o2.tmin = i2, o2.tmax = a2, o2;
        }
        return jt(n2, [{ key: `paramRange`, value: function() {
          return { min: this.tmin, max: this.tmax };
        } }, { key: `paramLength`, value: function() {
          return this.tmax - this.tmin;
        } }, { key: `containsParam`, value: function(e4) {
          return e4 >= this.tmin && e4 <= this.tmax;
        } }, { key: `position`, value: function(e4) {
          return { x: this.p0.x + e4 * (this.p1.x - this.p0.x), y: this.p0.y + e4 * (this.p1.y - this.p0.y) };
        } }, { key: `fatLine`, value: function() {
          var e4 = this.p1.y - this.p0.y, t4 = this.p0.x - this.p1.x, n3 = this.p1.x * this.p0.y - this.p0.x * this.p1.y, r2 = Math.sqrt(e4 * e4 + t4 * t4);
          return r2 === 0 ? (e4 = 1, t4 = 0) : (e4 /= r2, t4 /= r2, n3 /= r2), { min: [e4, t4, n3], max: [e4, t4, n3] };
        } }, { key: `clip`, value: function(e4, t4) {
          return new Z.Line(this.p0, this.p1, e4, t4);
        } }, { key: `clippedRange`, value: function(e4, t4) {
          var n3 = [, ,];
          return n3[0] = this.position(this.tmin), n3[1] = this.position(this.tmax), this.clippedLineRange(n3, e4, t4);
        } }, { key: `drawFatLine`, value: function() {
          this.fatLine().min;
          var e4 = function(e5, t5) {
            return -(e5 * t5[0] + t5[2]) / t5[1];
          }, t4 = this.p0.x, n3 = this.p1.x;
          A.svgForDebug.createSVGElement(`line`, { x1: A.measure.em2px(t4), y1: -A.measure.em2px(e4(t4, lmax)), x2: A.measure.em2px(n3), y2: -A.measure.em2px(e4(n3, lmax)), "stroke-width": A.measure.em2px(0.02 * A.measure.oneem), stroke: `red` });
        } }]), n2;
      })(Z), Z.QuadBezier = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4, r2, i2) {
          var a2;
          return kt(this, n2), (a2 = t3.call(this)).bezier = e4, a2.tmin = r2, a2.tmax = i2, a2.cp0 = e4.position(r2), a2.cp1 = new U.Point((1 - i2) * (1 - r2) * e4.cp0.x + (r2 + i2 - 2 * r2 * i2) * e4.cp1.x + r2 * i2 * e4.cp2.x, (1 - i2) * (1 - r2) * e4.cp0.y + (r2 + i2 - 2 * r2 * i2) * e4.cp1.y + r2 * i2 * e4.cp2.y), a2.cp2 = e4.position(i2), a2.cps = [a2.cp0, a2.cp1, a2.cp2], a2;
        }
        return jt(n2, [{ key: `paramRange`, value: function() {
          return { min: this.tmin, max: this.tmax };
        } }, { key: `paramLength`, value: function() {
          return this.tmax - this.tmin;
        } }, { key: `fatLine`, value: function() {
          return this.bezierFatLine(2);
        } }, { key: `clip`, value: function(e4, t4) {
          return new Z.QuadBezier(this.bezier, e4, t4);
        } }, { key: `clippedRange`, value: function(e4, t4) {
          return this.clippedLineRange(this.cps, e4, t4);
        } }, { key: `drawFatLine`, value: function() {
          var e4 = this.fatLine(), t4 = e4.min, n3 = e4.max, r2 = function(e5, t5) {
            return -(e5 * t5[0] + t5[2]) / t5[1];
          }, i2 = this.cp0.x, a2 = this.cp2.x;
          A.svgForDebug.createSVGElement(`line`, { x1: A.measure.em2px(i2), y1: -A.measure.em2px(r2(i2, t4)), x2: A.measure.em2px(a2), y2: -A.measure.em2px(r2(a2, t4)), "stroke-width": A.measure.em2px(0.02 * A.measure.oneem), stroke: `blue` }), A.svgForDebug.createSVGElement(`line`, { x1: A.measure.em2px(i2), y1: -A.measure.em2px(r2(i2, n3)), x2: A.measure.em2px(a2), y2: -A.measure.em2px(r2(a2, n3)), "stroke-width": A.measure.em2px(0.02 * A.measure.oneem), stroke: `red` });
        } }]), n2;
      })(Z), Z.CubicBezier = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4, r2, i2) {
          var a2;
          return kt(this, n2), (a2 = t3.call(this)).bezier = e4, a2.tmin = r2, a2.tmax = i2, a2.cp0 = e4.position(r2), a2.cp1 = new U.Point((1 - i2) * (1 - r2) * (1 - r2) * e4.cp0.x + (1 - r2) * (2 * r2 + i2 - 3 * r2 * i2) * e4.cp1.x + r2 * (2 * i2 + r2 - 3 * r2 * i2) * e4.cp2.x + r2 * r2 * i2 * e4.cp3.x, (1 - i2) * (1 - r2) * (1 - r2) * e4.cp0.y + (1 - r2) * (2 * r2 + i2 - 3 * r2 * i2) * e4.cp1.y + r2 * (2 * i2 + r2 - 3 * r2 * i2) * e4.cp2.y + r2 * r2 * i2 * e4.cp3.y), a2.cp2 = new U.Point((1 - r2) * (1 - i2) * (1 - i2) * e4.cp0.x + (1 - i2) * (2 * i2 + r2 - 3 * r2 * i2) * e4.cp1.x + i2 * (2 * r2 + i2 - 3 * r2 * i2) * e4.cp2.x + r2 * i2 * i2 * e4.cp3.x, (1 - r2) * (1 - i2) * (1 - i2) * e4.cp0.y + (1 - i2) * (2 * i2 + r2 - 3 * r2 * i2) * e4.cp1.y + i2 * (2 * r2 + i2 - 3 * r2 * i2) * e4.cp2.y + r2 * i2 * i2 * e4.cp3.y), a2.cp3 = e4.position(i2), a2.cps = [a2.cp0, a2.cp1, a2.cp2, a2.cp3], a2;
        }
        return jt(n2, [{ key: `paramRange`, value: function() {
          return { min: this.tmin, max: this.tmax };
        } }, { key: `paramLength`, value: function() {
          return this.tmax - this.tmin;
        } }, { key: `fatLine`, value: function() {
          return this.bezierFatLine(3);
        } }, { key: `clip`, value: function(e4, t4) {
          return new Z.CubicBezier(this.bezier, e4, t4);
        } }, { key: `clippedRange`, value: function(e4, t4) {
          return this.clippedLineRange(this.cps, e4, t4);
        } }, { key: `drawFatLine`, value: function() {
          var e4 = this.fatLine(), t4 = e4.min, n3 = e4.max, r2 = function(e5, t5) {
            return -(e5 * t5[0] + t5[2]) / t5[1];
          }, i2 = this.cp0.x, a2 = this.cp3.x;
          A.svgForDebug.createSVGElement(`line`, { x1: A.measure.em2px(i2), y1: -A.measure.em2px(r2(i2, t4)), x2: A.measure.em2px(a2), y2: -A.measure.em2px(r2(a2, t4)), "stroke-width": A.measure.em2px(0.02 * A.measure.oneem), stroke: `blue` }), A.svgForDebug.createSVGElement(`line`, { x1: A.measure.em2px(i2), y1: -A.measure.em2px(r2(i2, n3)), x2: A.measure.em2px(a2), y2: -A.measure.em2px(r2(a2, n3)), "stroke-width": A.measure.em2px(0.02 * A.measure.oneem), stroke: `red` });
        } }]), n2;
      })(Z), Z.Arc = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4, r2, i2, a2, o2, s2) {
          var c2;
          return kt(this, n2), (c2 = t3.call(this)).x = e4, c2.y = r2, c2.rx = i2, c2.ry = a2, c2.angleMin = o2, c2.angleMax = s2, c2;
        }
        return jt(n2, [{ key: `paramRange`, value: function() {
          return { min: this.angleMin, max: this.angleMax };
        } }, { key: `paramLength`, value: function() {
          return this.angleMax - this.angleMin;
        } }, { key: `normalizeAngle`, value: function(e4) {
          return (e4 = e4 % 2 * Math.PI) > Math.PI ? e4 - 2 * Math.PI : e4 < -Math.PI ? e4 + 2 * Math.PI : e4;
        } }, { key: `containsParam`, value: function(e4) {
          return e4 >= this.angleMin && e4 <= this.angleMax;
        } }, { key: `fatLine`, value: function() {
          var e4 = this.rx, t4 = this.ry, n3 = (this.angleMax + this.angleMin) / 2, r2 = (this.angleMax - this.angleMin) / 2, i2 = Math.cos(n3), a2 = Math.sin(n3), o2 = Math.sqrt(e4 * e4 * a2 * a2 + t4 * t4 * i2 * i2);
          if (o2 < l.machinePrecision) var s2 = [1, 0, this.x * t4 * i2 + this.y * e4 * a2 + e4 * t4 * Math.cos(r2)], c2 = [1, 0, this.x * t4 * i2 + this.y * e4 * a2 + e4 * t4];
          else {
            var u2 = e4 / o2, d2 = t4 / o2;
            s2 = [-d2 * i2, -u2 * a2, this.x * d2 * i2 + this.y * u2 * a2 + e4 * t4 / o2 * Math.cos(r2)], c2 = [-d2 * i2, -u2 * a2, this.x * d2 * i2 + this.y * u2 * a2 + e4 * t4 / o2];
          }
          return { min: s2, max: c2 };
        } }, { key: `clip`, value: function(e4, t4) {
          return new Z.Arc(this.x, this.y, this.rx, this.ry, e4, t4);
        } }, { key: `toCircleLine`, value: function(e4, t4, n3, r2, i2) {
          var a2 = e4[0], o2 = e4[1], s2 = a2 * r2, c2 = o2 * i2, u2 = e4[2] * r2 + (r2 - i2) * o2 * n3, d2 = Math.sqrt(s2 * s2 + c2 * c2);
          return d2 < l.machinePrecision ? (s2 = 1, c2 = 0) : (s2 /= d2, c2 /= d2, u2 /= d2), [s2, c2, u2];
        } }, { key: `clippedRange`, value: function(e4, t4) {
          var n3 = this.x, r2 = this.y, i2 = this.rx, a2 = this.ry, o2 = this.toCircleLine(e4, n3, r2, i2, a2), s2 = this.toCircleLine(t4, n3, r2, i2, a2), c2 = i2, l2 = this.angleMin, u2 = this.angleMax, d2 = -(o2[0] * n3 + o2[1] * r2 + o2[2]), f2 = [];
          if (c2 * c2 - d2 * d2 >= 0) {
            var p2 = o2[0] * d2 - o2[1] * Math.sqrt(c2 * c2 - d2 * d2), m2 = o2[1] * d2 + o2[0] * Math.sqrt(c2 * c2 - d2 * d2), h2 = o2[0] * d2 + o2[1] * Math.sqrt(c2 * c2 - d2 * d2), g2 = o2[1] * d2 - o2[0] * Math.sqrt(c2 * c2 - d2 * d2), _2 = Math.atan2(m2, p2), v2 = Math.atan2(g2, h2);
            this.containsParam(_2) && f2.push(_2), this.containsParam(v2) && f2.push(v2);
          }
          var y2, b2, x2 = -(o2[0] * (n3 + c2 * Math.cos(l2)) + o2[1] * (r2 + c2 * Math.sin(l2)) + o2[2]), S2 = -(o2[0] * (n3 + c2 * Math.cos(u2)) + o2[1] * (r2 + c2 * Math.sin(u2)) + o2[2]);
          if (x2 < 0) {
            if (f2.length == 0) return;
            y2 = Math.min.apply(Math, f2);
          } else y2 = this.angleMin;
          if (S2 < 0) {
            if (f2.length == 0) return;
            b2 = Math.max.apply(Math, f2);
          } else b2 = this.angleMax;
          f2 = [], c2 * c2 - (d2 = s2[0] * n3 + s2[1] * r2 + s2[2]) * d2 >= 0 && (p2 = -o2[0] * d2 + o2[1] * Math.sqrt(c2 * c2 - d2 * d2), m2 = -o2[1] * d2 - o2[0] * Math.sqrt(c2 * c2 - d2 * d2), h2 = -o2[0] * d2 - o2[1] * Math.sqrt(c2 * c2 - d2 * d2), g2 = -o2[1] * d2 + o2[0] * Math.sqrt(c2 * c2 - d2 * d2), _2 = Math.atan2(m2, p2), v2 = Math.atan2(g2, h2), this.containsParam(_2) && f2.push(_2), this.containsParam(v2) && f2.push(v2));
          var C2, w2;
          if (x2 = s2[0] * (n3 + c2 * Math.cos(l2)) + s2[1] * (r2 + c2 * Math.sin(l2)) + s2[2], S2 = s2[0] * (n3 + c2 * Math.cos(u2)) + s2[1] * (r2 + c2 * Math.sin(u2)) + s2[2], x2 < 0) {
            if (f2.length == 0) return;
            C2 = Math.min.apply(Math, f2);
          } else C2 = this.angleMin;
          if (S2 < 0) {
            if (f2.length == 0) return;
            w2 = Math.max.apply(Math, f2);
          } else w2 = this.angleMax;
          return { min: Math.max(y2, C2), max: Math.min(b2, w2) };
        } }, { key: `drawFatLine`, value: function() {
          var e4 = this.fatLine(), t4 = e4.min, n3 = e4.max, r2 = function(e5, t5) {
            return -(e5 * t5[0] + t5[2]) / t5[1];
          }, i2 = this.x + this.r * Math.cos(this.angleMin), a2 = this.x + this.r * Math.cos(this.angleMax);
          A.svgForDebug.createSVGElement(`line`, { x1: A.measure.em2px(i2), y1: -A.measure.em2px(r2(i2, t4)), x2: A.measure.em2px(a2), y2: -A.measure.em2px(r2(a2, t4)), "stroke-width": A.measure.em2px(0.02 * A.measure.oneem), stroke: `blue` }), A.svgForDebug.createSVGElement(`line`, { x1: A.measure.em2px(i2), y1: -A.measure.em2px(r2(i2, n3)), x2: A.measure.em2px(a2), y2: -A.measure.em2px(r2(a2, n3)), "stroke-width": A.measure.em2px(0.02 * A.measure.oneem), stroke: `red` });
        } }]), n2;
      })(Z);
      var Q = function e3() {
        kt(this, e3);
      };
      function Nt(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function Pt(e3, t3, n2) {
        return t3 && Nt(e3.prototype, t3), e3;
      }
      function Ft(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      Q.None = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2() {
          return kt(this, n2), t3.call(this);
        }
        return jt(n2, [{ key: `isDefined`, get: function() {
          return false;
        } }, { key: `segments`, value: function() {
          return [];
        } }, { key: `angle`, value: function() {
          return 0;
        } }]), n2;
      })(Q), Q.none = new Q.None(), Q.Line = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4, r2, i2, a2, o2) {
          var s2;
          return kt(this, n2), (s2 = t3.call(this)).start = e4, s2.end = r2, s2.p = i2, s2.c = a2, s2.lineShape = o2, s2;
        }
        return jt(n2, [{ key: `isDefined`, get: function() {
          return true;
        } }, { key: `position`, value: function(e4) {
          return new U.Point(this.p.x + e4 * (this.c.x - this.p.x), this.p.y + e4 * (this.c.y - this.p.y));
        } }, { key: `derivative`, value: function(e4) {
          return new U.Point(this.c.x - this.p.x, this.c.y - this.p.y);
        } }, { key: `angle`, value: function(e4) {
          var t4 = this.c.x - this.p.x, n3 = this.c.y - this.p.y;
          return t4 === 0 && n3 === 0 ? 0 : Math.atan2(n3, t4);
        } }, { key: `tOfPlace`, value: function(e4, t4, n3, r2) {
          var i2 = e4 ? this.start : this.p, a2 = t4 ? this.end : this.c;
          if (i2.x === a2.x && i2.y === a2.y) return 0;
          var o2, s2, c2 = a2.x - i2.x, l2 = a2.y - i2.y, u2 = Math.sqrt(c2 * c2 + l2 * l2);
          n3 > 0.5 ? (o2 = a2.x - (1 - n3) * c2 + r2 * c2 / u2, s2 = a2.y - (1 - n3) * l2 + r2 * l2 / u2) : (o2 = i2.x + n3 * c2 + r2 * c2 / u2, s2 = i2.y + n3 * l2 + r2 * l2 / u2);
          var d2 = this.c.x - this.p.x, f2 = this.c.y - this.p.y;
          return d2 === 0 && f2 === 0 ? 0 : Math.abs(d2) > Math.abs(f2) ? (o2 - this.p.x) / d2 : (s2 - this.p.y) / f2;
        } }, { key: `sliceHole`, value: function(e4, t4) {
          if (this.lineShape !== void 0 && !e4.isPoint()) {
            var n3 = this.lineShape, r2 = n3.line, i2 = r2.tOfIntersections(e4);
            i2.push(0), i2.push(1), i2.sort();
            for (var a2 = i2[0], o2 = 1; o2 < i2.length; o2++) {
              var s2 = i2[o2], c2 = r2.position((s2 + a2) / 2);
              if (e4.contains(c2)) {
                var l2 = new bt(a2, s2);
                n3.sliceHole(l2);
              }
              a2 = s2;
            }
          }
        } }, { key: `segments`, value: function() {
          return [new Z.Line(this.p, this.c, 0, 1)];
        } }]), n2;
      })(Q), Q.QuadBezier = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4, r2, i2, a2) {
          var o2;
          return kt(this, n2), (o2 = t3.call(this)).origBezier = e4, o2.tOfShavedStart = r2, o2.tOfShavedEnd = i2, a2.isNone || (o2.curveShape = a2, r2 > 0 && a2.sliceHole(new bt(0, r2)), i2 < 1 && a2.sliceHole(new bt(i2, 1))), o2;
        }
        return jt(n2, [{ key: `isDefined`, get: function() {
          return true;
        } }, { key: `position`, value: function(e4) {
          return this.origBezier.position(e4);
        } }, { key: `derivative`, value: function(e4) {
          return this.origBezier.derivative(e4);
        } }, { key: `angle`, value: function(e4) {
          return this.origBezier.angle(e4);
        } }, { key: `tOfPlace`, value: function(e4, t4, n3, r2) {
          var i2, a2;
          e4 ? (i2 = this.tOfShavedStart, a2 = t4 ? this.tOfShavedEnd - this.tOfShavedStart : 1 - this.tOfShavedStart) : (i2 = 0, a2 = t4 ? this.tOfShavedEnd : 1);
          var o2 = this.origBezier, s2 = i2 + a2 * n3;
          if (r2 !== 0) {
            var c2 = o2.length(s2);
            s2 = o2.tOfLength(c2 + r2);
          }
          return s2;
        } }, { key: `sliceHole`, value: function(e4, t4) {
          var n3 = this.curveShape;
          if (n3 !== void 0 && !e4.isPoint()) {
            var r2 = n3.curve, i2 = r2.tOfIntersections(e4);
            i2.push(0), i2.push(1), i2.sort();
            for (var a2 = i2[0], o2 = 1; o2 < i2.length; o2++) {
              var s2 = i2[o2];
              if (a2 <= t4 && t4 <= s2) {
                var c2 = r2.position((s2 + a2) / 2);
                if (e4.contains(c2)) {
                  var l2 = new bt(a2, s2);
                  n3.sliceHole(l2);
                }
              }
              a2 = s2;
            }
          }
        } }, { key: `segments`, value: function() {
          return [new Z.QuadBezier(this.origBezier, 0, 1)];
        } }]), n2;
      })(Q), Q.CubicBezier = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4, r2, i2, a2) {
          var o2;
          return kt(this, n2), (o2 = t3.call(this)).origBezier = e4, o2.tOfShavedStart = r2, o2.tOfShavedEnd = i2, a2.isNone || (o2.curveShape = a2, r2 > 0 && a2.sliceHole(new bt(0, r2)), i2 < 1 && a2.sliceHole(new bt(i2, 1))), o2;
        }
        return jt(n2, [{ key: `originalLine`, value: function() {
          return this.originalLine;
        } }, { key: `isDefined`, get: function() {
          return true;
        } }, { key: `position`, value: function(e4) {
          return this.origBezier.position(e4);
        } }, { key: `derivative`, value: function(e4) {
          return this.origBezier.derivative(e4);
        } }, { key: `angle`, value: function(e4) {
          return this.origBezier.angle(e4);
        } }, { key: `tOfPlace`, value: function(e4, t4, n3, r2) {
          var i2, a2;
          e4 ? (i2 = this.tOfShavedStart, a2 = t4 ? this.tOfShavedEnd - this.tOfShavedStart : 1 - this.tOfShavedStart) : (i2 = 0, a2 = t4 ? this.tOfShavedEnd : 1);
          var o2 = this.origBezier, s2 = i2 + a2 * n3;
          if (r2 !== 0) {
            var c2 = o2.length(s2);
            s2 = o2.tOfLength(c2 + r2);
          }
          return s2;
        } }, { key: `sliceHole`, value: function(e4, t4) {
          var n3 = this.curveShape;
          if (n3 !== void 0 && !e4.isPoint()) {
            var r2 = n3.curve, i2 = r2.tOfIntersections(e4);
            i2.push(0), i2.push(1), i2.sort();
            for (var a2 = i2[0], o2 = 1; o2 < i2.length; o2++) {
              var s2 = i2[o2];
              if (a2 <= t4 && t4 <= s2) {
                var c2 = r2.position((s2 + a2) / 2);
                if (e4.contains(c2)) {
                  var l2 = new bt(a2, s2);
                  n3.sliceHole(l2);
                }
              }
              a2 = s2;
            }
          }
        } }, { key: `segments`, value: function() {
          return [new Z.CubicBezier(this.origBezier, 0, 1)];
        } }]), n2;
      })(Q), Q.CubicBSpline = (function(e3) {
        wt(n2, e3);
        var t3 = Et(n2);
        function n2(e4, r2, i2, a2, o2, s2) {
          var c2;
          return kt(this, n2), (c2 = t3.call(this)).s = e4, c2.e = r2, c2.origBeziers = i2, c2.tOfShavedStart = a2, c2.tOfShavedEnd = o2, s2.isNone || (c2.curveShape = s2, a2 > 0 && s2.sliceHole(new bt(0, a2)), o2 < 1 && s2.sliceHole(new bt(o2, 1))), c2;
        }
        return jt(n2, [{ key: `isDefined`, get: function() {
          return true;
        } }, { key: `position`, value: function(e4) {
          return this.origBeziers.position(e4);
        } }, { key: `derivative`, value: function(e4) {
          return this.origBeziers.derivative(e4);
        } }, { key: `angle`, value: function(e4) {
          return this.origBeziers.angle(e4);
        } }, { key: `tOfPlace`, value: function(e4, t4, n3, r2) {
          var i2, a2;
          e4 ? (i2 = this.tOfShavedStart, a2 = t4 ? this.tOfShavedEnd - this.tOfShavedStart : 1 - this.tOfShavedStart) : (i2 = 0, a2 = t4 ? this.tOfShavedEnd : 1);
          var o2 = this.origBeziers, s2 = i2 + a2 * n3;
          if (r2 !== 0) {
            var c2 = o2.length(s2);
            s2 = o2.tOfLength(c2 + r2);
          }
          return s2;
        } }, { key: `sliceHole`, value: function(e4, t4) {
          var n3 = this.curveShape;
          if (n3 !== void 0 && !e4.isPoint()) {
            var r2 = n3.curve, i2 = r2.tOfIntersections(e4);
            i2.push(0), i2.push(1), i2.sort();
            for (var a2 = i2[0], o2 = 1; o2 < i2.length; o2++) {
              var s2 = i2[o2];
              if (a2 <= t4 && t4 <= s2) {
                var c2 = r2.position((s2 + a2) / 2);
                if (e4.contains(c2)) {
                  var l2 = new bt(a2, s2);
                  n3.sliceHole(l2);
                }
              }
              a2 = s2;
            }
          }
        } }, { key: `segments`, value: function() {
          for (var e4 = Array(this.origBeziers.length), t4 = e4.length, n3 = 0; n3 < t4; n3++) e4[n3] = new Z.CubicBezier(this.origBezier, n3 / t4, (n3 + 1) / t4);
          return e4;
        } }]), n2;
      })(Q);
      var It = function e3() {
        Ft(this, e3);
      };
      function Lt(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      function Rt(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function zt(e3, t3, n2) {
        return t3 && Rt(e3.prototype, t3), e3;
      }
      function $(e3, t3) {
        for (var n2 in t3) e3.prototype.hasOwnProperty(n2) ? console.log(`WARN`, `method ` + n2 + ` is already exists in class ` + e3.name) : e3.prototype[n2] = t3[n2];
      }
      It.Position = (function() {
        function e3(t3) {
          Ft(this, e3), this.pos = t3;
        }
        return Pt(e3, [{ key: `position`, value: function(e4) {
          return this.pos;
        } }, { key: `toString`, value: function() {
          return this.pos.toString();
        } }]), e3;
      })(), It.Macro = (function() {
        function e3(t3) {
          Ft(this, e3), this.macro = t3;
        }
        return Pt(e3, [{ key: `position`, value: function(e4) {
          return env.c = this.macro.position(e4), env.c;
        } }, { key: `toString`, value: function() {
          return this.macro.toString();
        } }]), e3;
      })(), It.Base = (function() {
        function e3(t3, n2, r2) {
          Ft(this, e3), this.origin = t3, this.xBase = n2, this.yBase = r2;
        }
        return Pt(e3, [{ key: `position`, value: function(e4) {
          var t3 = e4.env;
          return t3.origin = this.origin, t3.xBase = this.xBase, t3.yBase = this.yBase, t3.c;
        } }, { key: `toString`, value: function() {
          return `origin:` + this.origin + `, xBase:` + this.xBase + `, yBase:` + this.yBase;
        } }]), e3;
      })(), It.Stack = (function() {
        function e3(t3) {
          Ft(this, e3), this.stack = t3;
        }
        return Pt(e3, [{ key: `position`, value: function(e4) {
          var t3 = e4.env;
          return this.stack.isEmpty || (this.stack.tail.reverse().foreach((function(e5) {
            t3.capturePosition(e5);
          })), t3.c = this.stack.head), t3.c;
        } }, { key: `toString`, value: function() {
          return this.stack.toString();
        } }]), e3;
      })(), $(F.PosDecor, { toShape: function(e3) {
        this.pos.toShape(e3), this.decor.toShape(e3);
      } }), $(F.Pos.Coord, { toShape: function(e3) {
        e3.env.c = this.coord.position(e3), this.pos2s.foreach((function(t3) {
          t3.toShape(e3);
        }));
      } }), $(F.Pos.Plus, { toShape: function(e3) {
        var t3 = e3.env, n2 = this.coord.position(e3);
        t3.c = n2.move(t3.c.x + n2.x, t3.c.y + n2.y);
      } }), $(F.Pos.Minus, { toShape: function(e3) {
        var t3 = e3.env, n2 = this.coord.position(e3);
        t3.c = n2.move(t3.c.x - n2.x, t3.c.y - n2.y);
      } }), $(F.Pos.Skew, { toShape: function(e3) {
        var t3 = e3.env, n2 = this.coord.position(e3);
        t3.c = new U.Point(n2.x + t3.c.x, n2.y + t3.c.y).combineRect(t3.c);
      } }), $(F.Pos.Cover, { toShape: function(e3) {
        var t3 = e3.env, n2 = this.coord.position(e3);
        t3.c = t3.c.combineRect(n2);
      } }), $(F.Pos.Then, { toShape: function(e3) {
        var t3 = e3.env;
        t3.capturePosition(t3.c), t3.c = this.coord.position(e3);
      } }), $(F.Pos.SwapPAndC, { toShape: function(e3) {
        var t3 = e3.env;
        t3.swapPAndC(), t3.c = this.coord.position(e3);
      } }), $(F.Pos.SetBase, { toShape: function(e3) {
        var t3 = e3.env, n2 = t3.p, r2 = t3.c.x - n2.x, i2 = t3.c.y - n2.y;
        t3.setOrigin(n2.x, n2.y), t3.setXBase(r2, i2), t3.setYBase(-i2, r2), t3.c = this.coord.position(e3);
      } }), $(F.Pos.SetYBase, { toShape: function(e3) {
        var t3 = e3.env;
        t3.setYBase(t3.c.x - t3.origin.x, t3.c.y - t3.origin.y), t3.c = this.coord.position(e3);
      } }), $(F.Pos.ConnectObject, { toShape: function(e3) {
        this.object.toConnectShape(e3);
      } }), $(F.Pos.DropObject, { toShape: function(e3) {
        this.object.toDropShape(e3);
      } }), $(F.Pos.Place, { toShape: function(e3) {
        var t3 = e3.env;
        if (t3.lastCurve.isDefined) {
          var n2, r2 = this.place, i2 = r2.shaveP > 0, a2 = r2.shaveC > 0, o2 = i2 ? r2.shaveP - 1 : 0, s2 = a2 ? r2.shaveC - 1 : 0;
          if (i2 && (n2 = 0), a2 && (n2 = 1), i2 == a2 && (n2 = 0.5), r2.factor !== void 0) if (r2.factor.isIntercept) {
            if (a2 = i2 = false, (n2 = r2.factor.value(e3)) === void 0) return;
          } else n2 = r2.factor.value(e3);
          var c2 = A.measure.length2em(r2.slide.dimen.getOrElse(`0`)) + (o2 - s2) * A.measure.jot, l2 = t3.lastCurve.tOfPlace(i2, a2, n2, c2), u2 = t3.lastCurve.position(l2), d2 = t3.lastCurve.angle(l2);
          return t3.c = u2, t3.angle = d2, l2;
        }
      } }), $(F.Pos.PushCoord, { toShape: function(e3) {
        var t3 = e3.env, n2 = this.coord.position(e3);
        t3.pushPos(n2);
      } }), $(F.Pos.EvalCoordThenPop, { toShape: function(e3) {
        var t3 = e3.env;
        t3.c = this.coord.position(e3), t3.popPos();
      } }), $(F.Pos.LoadStack, { toShape: function(e3) {
        var t3 = e3.env;
        t3.startCapturePositions(), this.coord.position(e3);
        var n2 = t3.endCapturePositions();
        t3.setStack(n2), t3.pushPos(t3.c);
      } }), $(F.Pos.DoCoord, { toShape: function(e3) {
        var t3 = e3.env, n2 = this.coord;
        t3.stack.reverse().foreach((function(r2) {
          t3.c = r2, n2.position(e3);
        }));
      } }), $(F.Pos.InitStack, { toShape: function(e3) {
        e3.env.initStack();
      } }), $(F.Pos.EnterFrame, { toShape: function(e3) {
        e3.env.enterStackFrame();
      } }), $(F.Pos.LeaveFrame, { toShape: function(e3) {
        e3.env.leaveStackFrame();
      } }), $(F.Place.Factor, { value: function(e3) {
        return this.factor;
      } }), $(F.Place.Intercept, { value: function(e3) {
        var t3 = e3.env;
        if (t3.lastCurve.isDefined) {
          var n2 = t3.duplicate();
          n2.angle = 0, n2.lastCurve = Q.none, n2.p = n2.c = Mt.originPosition;
          var r2 = new St(Y.none, n2);
          this.pos.toShape(r2), e3.appendShapeToFront(r2.shape), n2.lastCurve.isDefined || (n2.lastCurve = new Q.Line(n2.p, n2.c, n2.p, n2.c, void 0));
          for (var i2 = [], a2 = t3.lastCurve.segments(), o2 = n2.lastCurve.segments(), s2 = 0; s2 < a2.length; s2++) for (var c2 = 0; c2 < o2.length; c2++) i2 = i2.concat(Z.findIntersections(a2[s2], o2[c2]));
          if (i2.length === 0) {
            console.log(`perhaps no curve intersection.`);
            for (var l2 = t3.lastCurve, u2 = n2.lastCurve, d2 = 1e-5, f2 = 0, p2 = 2, m2 = 0, h2 = 0, g2 = function(e4) {
              return 1 / (1 + Math.exp(-e4));
            }, _2 = function(e4) {
              var t4 = Math.exp(-e4);
              return t4 / (1 + t4) / (1 + t4);
            }, v2 = g2(m2), y2 = g2(h2), b2 = _2(m2), x2 = _2(h2), S2 = l2.derivative(v2), C2 = u2.derivative(y2), w2 = S2.x * b2, T2 = -C2.x * x2, E2 = S2.y * b2, D2 = -C2.y * x2, ee2 = w2 * w2 + E2 * E2, te2 = w2 * T2 + E2 * D2, ne2 = T2 * w2 + D2 * E2, O2 = T2 * T2 + D2 * D2, re2 = l2.position(v2), ie2 = u2.position(y2), ae2 = re2.x - ie2.x, oe2 = re2.y - ie2.y, se2 = w2 * ae2 + E2 * oe2, ce2 = T2 * ae2 + D2 * oe2, le2 = Math.sqrt(se2 * se2 + ce2 * ce2) < d2, ue2 = 1e-3 * Math.max(ee2, O2); !le2 && f2 < 100; ) {
              f2++;
              do {
                var de2 = O2 + ue2, fe2 = (ee2 + ue2) * de2 - te2 * ne2, pe2 = (de2 * se2 - te2 * ce2) / fe2, me2 = (-ne2 * se2 + ee2 * ce2) / fe2;
                if (pe2 * pe2 + me2 * me2 < 10000000000000002e-26 * (m2 * m2 + h2 * h2)) le2 = true;
                else {
                  var he2 = m2 - pe2, ge2 = h2 - me2, _e2 = g2(he2), ve2 = g2(ge2), ye2 = l2.position(_e2), be2 = u2.position(ve2), xe2 = ye2.x - be2.x, Se2 = ye2.y - be2.y, k2 = (ae2 * ae2 + oe2 * oe2 - (xe2 * xe2 + Se2 * Se2)) / (pe2 * (ue2 * pe2 + se2) + me2 * (ue2 * me2 + ce2));
                  if (k2 > 0) {
                    h2 = ge2, v2 = _e2, y2 = ve2, b2 = _2(m2 = he2), x2 = _2(h2), S2 = l2.derivative(v2), C2 = u2.derivative(y2), w2 = S2.x * b2, T2 = -C2.x * x2, ee2 = w2 * w2 + (E2 = S2.y * b2) * E2, te2 = w2 * T2 + E2 * (D2 = -C2.y * x2), ne2 = T2 * w2 + D2 * E2, O2 = T2 * T2 + D2 * D2, se2 = w2 * (ae2 = xe2) + E2 * (oe2 = Se2), ce2 = T2 * ae2 + D2 * oe2, le2 = Math.sqrt(se2 * se2 + ce2 * ce2) < d2;
                    var Ce2 = 2 * k2 - 1;
                    ue2 += Math.max(1 / 3, 1 - Ce2 * Ce2 * Ce2), p2 = 2;
                  } else ue2 *= p2, p2 *= 2;
                }
              } while (!(le2 || k2 !== void 0 && k2 > 0));
            }
            return g2(m2);
          }
          var we2 = (i2[0][0].min + i2[0][0].max) / 2;
          for (s2 = 1; s2 < i2.length; s2++) {
            var Te2 = (i2[s2][0].min + i2[s2][0].max) / 2;
            we2 > Te2 && (we2 = Te2);
          }
          return we2;
        }
      } }), $(F.Pos.SavePos, { toShape: function(e3) {
        var t3 = e3.env;
        t3.savePos(this.id, new It.Position(t3.c));
      } }), $(F.Pos.SaveMacro, { toShape: function(e3) {
        e3.env.savePos(this.id, new It.Macro(this.macro));
      } }), $(F.Pos.SaveBase, { toShape: function(e3) {
        var t3 = e3.env;
        t3.savePos(this.id, new It.Base(t3.origin, t3.xBase, t3.yBase));
      } }), $(F.Pos.SaveStack, { toShape: function(e3) {
        var t3 = e3.env;
        t3.savePos(this.id, new It.Stack(t3.stack));
      } }), $(F.Object, { toDropShape: function(e3) {
        var t3 = e3.env;
        if (t3.c === void 0) return Y.none;
        var n2 = this.modifiers;
        if (n2.isEmpty) return this.object.toDropShape(e3);
        var r2 = t3.duplicate(), i2 = new St(Y.none, r2), a2 = O.empty;
        n2.foreach((function(e4) {
          e4.preprocess(i2, a2), a2 = a2.prepend(e4);
        }));
        var o2 = this.object.toDropShape(i2), s2 = r2.c;
        if (s2 === void 0) return Y.none;
        var c2 = r2.originalReferencePoint;
        return (r2 = t3.duplicate()).c = s2, r2.originalReferencePoint = c2, i2 = new St(Y.none, r2), o2 = n2.head.modifyShape(i2, o2, n2.tail), e3.appendShapeToFront(o2), t3.c = r2.c.move(t3.c.x, t3.c.y), o2;
      }, toConnectShape: function(e3) {
        var t3 = e3.env;
        if (t3.c === void 0) return Y.none;
        var n2 = this.modifiers;
        if (n2.isEmpty) return this.object.toConnectShape(e3);
        var r2 = t3.duplicate(), i2 = new St(Y.none, r2), a2 = O.empty;
        n2.foreach((function(e4) {
          e4.preprocess(i2, a2), a2 = a2.prepend(e4);
        }));
        var o2 = this.object.toConnectShape(i2);
        t3.angle = r2.angle, t3.lastCurve = r2.lastCurve;
        var s2 = r2.c;
        if (s2 === void 0) return Y.none;
        var c2 = r2.originalReferencePoint;
        return (r2 = t3.duplicate()).c = s2, r2.originalReferencePoint = c2, i2 = new St(Y.none, r2), o2 = n2.head.modifyShape(i2, o2, n2.tail), e3.appendShapeToFront(o2), t3.c = r2.c.move(t3.c.x, t3.c.y), o2;
      }, boundingBox: function(e3) {
        var t3 = e3.duplicateEnv(), n2 = t3.env;
        return n2.angle = 0, n2.p = n2.c = Mt.originPosition, t3.shape = Y.none, this.toDropShape(t3).getBoundingBox();
      } }), $(F.ObjectBox, { toConnectShape: function(e3) {
        var t3 = (n2 = e3.env).c, n2 = e3.env, r2 = (A.measure.thickness, n2.p.edgePoint(n2.c.x, n2.c.y)), i2 = n2.c.edgePoint(n2.p.x, n2.p.y);
        if (r2.x !== i2.x || r2.y !== i2.y) {
          var a2 = new X.Line(r2, i2).toShape(e3, this, `196883`, ``);
          return n2.originalReferencePoint = t3, a2;
        }
        return n2.angle = 0, n2.lastCurve = Q.none, n2.originalReferencePoint = t3, Y.none;
      }, boundingBox: function(e3) {
        var t3 = e3.duplicateEnv(), n2 = t3.env;
        return n2.angle = 0, n2.p = n2.c = Mt.originPosition, t3.shape = Y.none, this.toDropShape(t3).getBoundingBox();
      } }), $(F.ObjectBox.WrapUpObject, { toDropShape: function(e3) {
        var t3 = e3.env, n2 = this.object.toDropShape(e3);
        return t3.originalReferencePoint = t3.c, n2;
      }, toConnectShape: function(e3) {
        var t3 = e3.env, n2 = this.object.toConnectShape(e3);
        return t3.originalReferencePoint = t3.c, n2;
      } }), $(F.ObjectBox.CompositeObject, { toDropShape: function(e3) {
        var t3 = e3.env, n2 = t3.c;
        if (n2 === void 0) return Y.none;
        var r2 = n2, i2 = t3.duplicate(), a2 = new St(Y.none, i2);
        this.objects.foreach((function(e4) {
          i2.c = n2;
          var t4 = e4.toDropShape(a2);
          r2 = U.combineRect(r2, i2.c), r2 = U.combineRect(r2, t4.getBoundingBox().toPoint());
        })), t3.c = r2;
        var o2 = a2.shape;
        return e3.appendShapeToFront(o2), t3.originalReferencePoint = n2, o2;
      } }), $(F.ObjectBox.Xybox, { toDropShape: function(e3) {
        var t3 = e3.env, n2 = t3.c;
        if (n2 === void 0) return Y.none;
        var r2 = new Mt(), i2 = new St(Y.none, r2);
        this.posDecor.toShape(i2);
        var a2 = i2.shape, o2 = a2.getBoundingBox();
        if (o2 === void 0) return Y.none;
        var s2 = Math.max(0, o2.l - o2.x), c2 = Math.max(0, o2.r + o2.x), l2 = Math.max(0, o2.u + o2.y), u2 = Math.max(0, o2.d - o2.y);
        t3.c = new U.Rect(n2.x, n2.y, { l: s2, r: c2, u: l2, d: u2 }), t3.originalReferencePoint = n2;
        var d2 = new Y.TranslateShape(n2.x, n2.y, a2);
        return e3.appendShapeToFront(d2), d2;
      } }), $(F.ObjectBox.Xymatrix, { toDropShape: function(e3) {
        var t3 = e3.env, n2 = t3.c, r2 = this.xymatrix.toShape(e3);
        return t3.originalReferencePoint = n2, r2;
      } }), $(F.ObjectBox.Text, { toDropShape: function(e3) {
        var t3 = e3.env, n2 = new Y.TextShape(t3.c, this.math);
        return e3.appendShapeToFront(n2), t3.c = n2.getBoundingBox(), t3.originalReferencePoint = n2.getOriginalReferencePoint(), n2;
      } }), $(F.ObjectBox.Empty, { toDropShape: function(e3) {
        var t3 = e3.env;
        return t3.originalReferencePoint = t3.c, t3.c = new U.Point(t3.c.x, t3.c.y), Y.none;
      } }), $(F.ObjectBox.Txt, { toDropShape: function(e3) {
        var t3 = e3.env;
        if (t3.c === void 0) return Y.none;
        var n2 = this.textObject.toDropShape(e3);
        return t3.originalReferencePoint = t3.c, n2;
      } }), $(F.ObjectBox.Txt.Width.Vector, { width: function(e3) {
        return this.vector.xy().x;
      } }), $(F.ObjectBox.Txt.Width.Default, { width: function(e3) {
        var t3 = e3.env.c;
        return t3.r + t3.l;
      } }), $(F.ObjectBox.Cir, { toDropShape: function(e3) {
        var t3 = e3.env;
        if (t3.c === void 0) return Y.none;
        t3.originalReferencePoint = t3.c;
        var n2 = this.radius.radius(e3), r2 = t3.c.x, i2 = t3.c.y, a2 = this.cir.toDropShape(e3, r2, i2, n2);
        return t3.c = new U.Ellipse(r2, i2, n2, n2, n2, n2), a2;
      }, toConnectShape: function(e3) {
        var t3 = e3.env;
        return t3.originalReferencePoint = t3.c, Y.none;
      } }), $(F.ObjectBox.Cir.Radius.Vector, { radius: function(e3) {
        return this.vector.xy(e3).x;
      } }), $(F.ObjectBox.Cir.Radius.Default, { radius: function(e3) {
        return e3.env.c.r;
      } }), $(F.ObjectBox.Cir.Cir.Segment, { toDropShape: function(e3, t3, n2, r2) {
        e3.env;
        var i2, a2, o2 = this.startPointDegree(e3), s2 = this.endPointDegree(e3, o2), c2 = s2 - o2;
        if ((c2 = c2 < 0 ? c2 + 360 : c2) === 0) return Y.none;
        this.orient === `^` ? (i2 = c2 > 180 ? `1` : `0`, a2 = `0`) : (i2 = c2 > 180 ? `0` : `1`, a2 = `1`);
        var l2 = Math.PI / 180, u2 = t3 + r2 * Math.cos(o2 * l2), d2 = n2 + r2 * Math.sin(o2 * l2), f2 = t3 + r2 * Math.cos(s2 * l2), p2 = n2 + r2 * Math.sin(s2 * l2), m2 = new Y.CircleSegmentShape(t3, n2, u2, d2, r2, i2, a2, f2, p2);
        return e3.appendShapeToFront(m2), m2;
      }, startPointDegree: function(e3) {
        var t3 = this.startDiag.toString();
        return this.orient === `^` ? this.diagToAngleACW(t3) : this.diagToAngleCW(t3);
      }, endPointDegree: function(e3, t3) {
        var n2 = this.endDiag.toString();
        return this.orient === `^` ? this.diagToAngleACW(n2, t3) : this.diagToAngleCW(n2, t3);
      }, diagToAngleACW: function(e3, t3) {
        switch (e3) {
          case `l`:
            return 90;
          case `r`:
            return -90;
          case `d`:
            return 180;
          case `u`:
            return 0;
          case `dl`:
          case `ld`:
            return 135;
          case `dr`:
          case `rd`:
            return -135;
          case `ul`:
          case `lu`:
            return 45;
          case `ur`:
          case `ru`:
            return -45;
          default:
            return t3 === void 0 ? 0 : t3 + 180;
        }
      }, diagToAngleCW: function(e3, t3) {
        switch (e3) {
          case `l`:
            return -90;
          case `r`:
            return 90;
          case `d`:
            return 0;
          case `u`:
            return 180;
          case `dl`:
          case `ld`:
            return -45;
          case `dr`:
          case `rd`:
            return 45;
          case `ul`:
          case `lu`:
            return -135;
          case `ur`:
          case `ru`:
            return 135;
          default:
            return t3 === void 0 ? 0 : t3 + 180;
        }
      } }), $(F.ObjectBox.Cir.Cir.Full, { toDropShape: function(e3, t3, n2, r2) {
        var i2 = new Y.FullCircleShape(t3, n2, r2);
        return e3.appendShapeToFront(i2), i2;
      } }), $(F.ObjectBox.Frame, { toDropShape: function(e3) {
        var t3 = e3.env;
        return t3.originalReferencePoint = t3.c, this.toDropFilledShape(e3, `currentColor`, false);
      }, toDropFilledShape: function(e3, t3, n2) {
        var r2 = e3.env.c;
        if (r2 === void 0) return Y.none;
        var i2 = A.measure.thickness, a2 = r2.x, o2 = r2.y, s2 = r2.l, c2 = r2.r, l2 = r2.u, u2 = r2.d, d2 = Y.none;
        switch (this.main) {
          case `--`:
            var f2 = 3 * i2;
            if (n2) {
              var p2 = this.radius.xy(e3);
              d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, false, t3, A.measure.em2px(f2) + ` ` + A.measure.em2px(f2));
            } else {
              var m2 = this.radius.radius(e3);
              d2 = new Y.RectangleShape(a2, o2, s2, c2, l2, u2, m2, false, t3, A.measure.em2px(f2) + ` ` + A.measure.em2px(f2));
            }
            break;
          case `==`:
            f2 = 3 * i2, n2 ? (p2 = this.radius.xy(e3), d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, true, t3, A.measure.em2px(f2) + ` ` + A.measure.em2px(f2))) : (m2 = this.radius.radius(e3), d2 = new Y.RectangleShape(a2, o2, s2, c2, l2, u2, m2, true, t3, A.measure.em2px(f2) + ` ` + A.measure.em2px(f2)));
            break;
          case `o-`:
            f2 = 3 * i2, m2 = A.measure.lineElementLength, d2 = new Y.RectangleShape(a2, o2, s2, c2, l2, u2, m2, false, t3, A.measure.em2px(f2) + ` ` + A.measure.em2px(f2));
            break;
          case `oo`:
            var h2 = (p2 = this.radius.xy(e3)).x;
            d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, h2, h2, true, t3, void 0);
            break;
          case `ee`:
            p2 = this.radius.xy(e3), d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, true, t3, void 0);
            break;
          case `-,`:
            var g2 = this.radius.depth(e3);
            m2 = this.radius.radius(e3), d2 = new Y.CompositeShape(new Y.RectangleShape(a2, o2, s2, c2, l2, u2, m2, false, t3, void 0), new Y.BoxShadeShape(a2, o2, s2, c2, l2, u2, g2));
            break;
          case `.o`:
            h2 = (p2 = this.radius.xy(e3)).x, d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, h2, h2, false, t3, A.measure.dottedDasharray);
            break;
          case `-o`:
            f2 = 3 * i2, h2 = (p2 = this.radius.xy(e3)).x, d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, h2, h2, false, t3, A.measure.em2px(f2) + ` ` + A.measure.em2px(f2));
            break;
          case `.e`:
            p2 = this.radius.xy(e3), d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, false, t3, A.measure.dottedDasharray);
            break;
          case `-e`:
            f2 = 3 * i2, p2 = this.radius.xy(e3), d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, false, t3, A.measure.em2px(f2) + ` ` + A.measure.em2px(f2));
            break;
          case `-`:
            n2 ? (p2 = this.radius.xy(e3), d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, false, t3, void 0)) : (m2 = this.radius.radius(e3), d2 = new Y.RectangleShape(a2, o2, s2, c2, l2, u2, m2, false, t3, void 0));
            break;
          case `=`:
            n2 ? (p2 = this.radius.xy(e3), d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, true, t3, void 0)) : (m2 = this.radius.radius(e3), d2 = new Y.RectangleShape(a2, o2, s2, c2, l2, u2, m2, true, t3, void 0));
            break;
          case `.`:
            n2 ? (p2 = this.radius.xy(e3), d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, false, t3, A.measure.dottedDasharray)) : (m2 = this.radius.radius(e3), d2 = new Y.RectangleShape(a2, o2, s2, c2, l2, u2, m2, false, t3, A.measure.dottedDasharray));
            break;
          case `,`:
            g2 = this.radius.depth(e3), d2 = new Y.BoxShadeShape(a2, o2, s2, c2, l2, u2, g2, t3);
            break;
          case `o`:
            h2 = (p2 = this.radius.xy(e3)).x, d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, h2, h2, false, t3, void 0);
            break;
          case `e`:
            p2 = this.radius.xy(e3), d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, false, t3, void 0);
            break;
          case `\\{`:
            d2 = new Y.LeftBrace(a2 - s2, o2, l2, u2, 0, t3);
            break;
          case `\\}`:
            d2 = new Y.LeftBrace(a2 + c2, o2, u2, l2, 180, t3);
            break;
          case `^\\}`:
          case `^\\{`:
            d2 = new Y.LeftBrace(a2, o2 + l2, c2, s2, 270, t3);
            break;
          case `_\\{`:
          case `_\\}`:
            d2 = new Y.LeftBrace(a2, o2 - u2, s2, c2, 90, t3);
            break;
          case `(`:
            d2 = new Y.LeftParenthesis(a2 - s2, o2 + (l2 - u2) / 2, l2 + u2, 0, t3);
            break;
          case `)`:
            d2 = new Y.LeftParenthesis(a2 + c2, o2 + (l2 - u2) / 2, l2 + u2, 180, t3);
            break;
          case `^(`:
          case `^)`:
            d2 = new Y.LeftParenthesis(a2 + (c2 - s2) / 2, o2 + l2, s2 + c2, 270, t3);
            break;
          case `_(`:
          case `_)`:
            d2 = new Y.LeftParenthesis(a2 + (c2 - s2) / 2, o2 - u2, s2 + c2, 90, t3);
            break;
          case `*`:
            r2.isCircle() ? (p2 = this.radius.xy(e3), d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, false, `currentColor`, void 0, t3, true)) : (m2 = this.radius.radius(e3), d2 = new Y.RectangleShape(a2, o2, s2, c2, l2, u2, m2, false, `currentColor`, void 0, t3, true));
            break;
          case `**`:
            r2.isCircle() ? (p2 = this.radius.xy(e3), d2 = new Y.EllipseShape(a2 + (c2 - s2) / 2, o2 + (l2 - u2) / 2, p2.x, p2.y, false, `currentColor`, void 0, t3, false)) : (m2 = this.radius.radius(e3), d2 = new Y.RectangleShape(a2, o2, s2, c2, l2, u2, m2, false, `currentColor`, void 0, t3, false));
            break;
          default:
            return Y.none;
        }
        return e3.appendShapeToFront(d2), d2;
      }, toConnectShape: function(e3) {
        var t3 = e3.env, n2 = t3.c, r2 = t3.p;
        n2 !== void 0 && r2 !== void 0 || Y.none, t3.originalReferencePoint = n2;
        var i2 = t3.duplicate();
        i2.c = r2.combineRect(n2);
        var a2 = new St(Y.none, i2), o2 = this.toDropShape(a2);
        return e3.appendShapeToFront(o2), o2;
      } }), $(F.ObjectBox.Frame.Radius.Vector, { radius: function(e3) {
        return this.vector.xy(e3).x;
      }, depth: function(e3) {
        return this.vector.xy(e3).x;
      }, xy: function(e3) {
        return this.vector.xy(e3);
      } }), $(F.ObjectBox.Frame.Radius.Default, { radius: function(e3) {
        return 0;
      }, depth: function(e3) {
        return A.measure.thickness / 2;
      }, xy: function(e3) {
        var t3 = e3.env.c;
        return { x: (t3.l + t3.r) / 2, y: (t3.u + t3.d) / 2 };
      } }), $(F.ObjectBox.Dir, { toDropShape: function(e3) {
        var t3 = e3.env, n2 = t3.c;
        t3.originalReferencePoint = n2;
        var r2 = t3.angle;
        if (n2 === void 0) return Y.none;
        t3.c = new U.Point(n2.x, n2.y), A.measure.thickness;
        var i2 = Y.none;
        switch (this.main) {
          case ``:
            return Y.none;
          case `>`:
            switch (this.variant) {
              case `2`:
                var a2 = (i2 = new Y.GT2ArrowheadShape(n2, r2)).getRadius();
                t3.c = new U.Ellipse(n2.x, n2.y, a2, a2, a2, a2);
                break;
              case `3`:
                a2 = (i2 = new Y.GT3ArrowheadShape(n2, r2)).getRadius(), t3.c = new U.Ellipse(n2.x, n2.y, a2, a2, a2, a2);
                break;
              default:
                i2 = this.variant === `^` ? new Y.UpperGTArrowheadShape(n2, r2) : this.variant === `_` ? new Y.LowerGTArrowheadShape(n2, r2) : new Y.GTArrowheadShape(n2, r2);
            }
            break;
          case `<`:
            switch (this.variant) {
              case `2`:
                a2 = (i2 = new Y.LT2ArrowheadShape(n2, r2)).getRadius(), t3.c = new U.Ellipse(n2.x, n2.y, a2, a2, a2, a2);
                break;
              case `3`:
                a2 = (i2 = new Y.LT3ArrowheadShape(n2, r2)).getRadius(), t3.c = new U.Ellipse(n2.x, n2.y, a2, a2, a2, a2);
                break;
              default:
                i2 = this.variant === `^` ? new Y.UpperLTArrowheadShape(n2, r2) : this.variant === `_` ? new Y.LowerLTArrowheadShape(n2, r2) : new Y.LTArrowheadShape(n2, r2);
            }
            break;
          case `|`:
            switch (this.variant) {
              case `^`:
                i2 = new Y.UpperColumnArrowheadShape(n2, r2);
                break;
              case `_`:
                i2 = new Y.LowerColumnArrowheadShape(n2, r2);
                break;
              case `2`:
                i2 = new Y.Column2ArrowheadShape(n2, r2);
                break;
              case `3`:
                i2 = new Y.Column3ArrowheadShape(n2, r2);
                break;
              default:
                i2 = new Y.ColumnArrowheadShape(n2, r2);
            }
            break;
          case `(`:
            switch (this.variant) {
              case `^`:
                i2 = new Y.UpperLParenArrowheadShape(n2, r2);
                break;
              case `_`:
                i2 = new Y.LowerLParenArrowheadShape(n2, r2);
                break;
              default:
                i2 = new Y.LParenArrowheadShape(n2, r2);
            }
            break;
          case `)`:
            switch (this.variant) {
              case `^`:
                i2 = new Y.UpperRParenArrowheadShape(n2, r2);
                break;
              case `_`:
                i2 = new Y.LowerRParenArrowheadShape(n2, r2);
                break;
              default:
                i2 = new Y.RParenArrowheadShape(n2, r2);
            }
            break;
          case "`":
            i2 = this.variant === `_` ? new Y.LowerBackquoteArrowheadShape(n2, r2) : new Y.UpperBackquoteArrowheadShape(n2, r2);
            break;
          case `'`:
            i2 = this.variant === `_` ? new Y.LowerQuoteArrowheadShape(n2, r2) : new Y.UpperQuoteArrowheadShape(n2, r2);
            break;
          case `*`:
            i2 = new Y.AsteriskArrowheadShape(n2, 0);
            break;
          case `o`:
            i2 = new Y.OArrowheadShape(n2, 0);
            break;
          case `+`:
            i2 = new Y.PlusArrowheadShape(n2, r2);
            break;
          case `x`:
            i2 = new Y.XArrowheadShape(n2, r2);
            break;
          case `/`:
            i2 = new Y.SlashArrowheadShape(n2, r2);
            break;
          case `-`:
          case `--`:
            A.measure.lineElementLength, i2 = this.variant === `3` ? new Y.Line3ArrowheadShape(n2, r2) : this.variant === `2` ? new Y.Line2ArrowheadShape(n2, r2) : new Y.LineArrowheadShape(n2, r2);
            break;
          case `=`:
          case `==`:
            i2 = new Y.Line2ArrowheadShape(n2, r2);
            break;
          case `.`:
          case `..`:
            i2 = this.variant === `3` ? new Y.Dot3ArrowheadShape(n2, r2) : this.variant === `2` ? new Y.Dot2ArrowheadShape(n2, r2) : new Y.DotArrowheadShape(n2, r2);
            break;
          case `:`:
          case `::`:
            i2 = new Y.Dot2ArrowheadShape(n2, r2);
            break;
          case `~`:
          case `~~`:
            i2 = this.variant === `3` ? new Y.Tilde3ArrowheadShape(n2, r2) : this.variant === `2` ? new Y.Tilde2ArrowheadShape(n2, r2) : new Y.TildeArrowheadShape(n2, r2);
            break;
          case `>>`:
            switch (this.variant) {
              case `^`:
                i2 = new Y.UpperGTGTArrowheadShape(n2, r2);
                break;
              case `_`:
                i2 = new Y.LowerGTGTArrowheadShape(n2, r2);
                break;
              case `2`:
                a2 = (i2 = new Y.GTGT2ArrowheadShape(n2, r2)).getRadius(), t3.c = new U.Ellipse(n2.x, n2.y, a2, a2, a2, a2);
                break;
              case `3`:
                a2 = (i2 = new Y.GTGT3ArrowheadShape(n2, r2)).getRadius(), t3.c = new U.Ellipse(n2.x, n2.y, a2, a2, a2, a2);
                break;
              default:
                i2 = new Y.GTGTArrowheadShape(n2, r2);
            }
            break;
          case `<<`:
            switch (this.variant) {
              case `^`:
                i2 = new Y.UpperLTLTArrowheadShape(n2, r2);
                break;
              case `_`:
                i2 = new Y.LowerLTLTArrowheadShape(n2, r2);
                break;
              case `2`:
                a2 = (i2 = new Y.LTLT2ArrowheadShape(n2, r2)).getRadius(), t3.c = new U.Ellipse(n2.x, n2.y, a2, a2, a2, a2);
                break;
              case `3`:
                a2 = (i2 = new Y.LTLT3ArrowheadShape(n2, r2)).getRadius(), t3.c = new U.Ellipse(n2.x, n2.y, a2, a2, a2, a2);
                break;
              default:
                i2 = new Y.LTLTArrowheadShape(n2, r2);
            }
            break;
          case `||`:
            switch (this.variant) {
              case `^`:
                i2 = new Y.UpperColumnColumnArrowheadShape(n2, r2);
                break;
              case `_`:
                i2 = new Y.LowerColumnColumnArrowheadShape(n2, r2);
                break;
              case `2`:
                i2 = new Y.ColumnColumn2ArrowheadShape(n2, r2);
                break;
              case `3`:
                i2 = new Y.ColumnColumn3ArrowheadShape(n2, r2);
                break;
              default:
                i2 = new Y.ColumnColumnArrowheadShape(n2, r2);
            }
            break;
          case `|-`:
            switch (this.variant) {
              case `^`:
                i2 = new Y.UpperColumnLineArrowheadShape(n2, r2);
                break;
              case `_`:
                i2 = new Y.LowerColumnLineArrowheadShape(n2, r2);
                break;
              case `2`:
                i2 = new Y.ColumnLine2ArrowheadShape(n2, r2);
                break;
              case `3`:
                i2 = new Y.ColumnLine3ArrowheadShape(n2, r2);
                break;
              default:
                i2 = new Y.ColumnLineArrowheadShape(n2, r2);
            }
            break;
          case `>|`:
            i2 = new Y.GTColumnArrowheadShape(n2, r2);
            break;
          case `>>|`:
            i2 = new Y.GTGTColumnArrowheadShape(n2, r2);
            break;
          case `|<`:
            i2 = new Y.ColumnLTArrowheadShape(n2, r2);
            break;
          case `|<<`:
            i2 = new Y.ColumnLTLTArrowheadShape(n2, r2);
            break;
          case `//`:
            i2 = new Y.SlashSlashArrowheadShape(n2, r2);
            break;
          case `=>`:
            i2 = new Y.LineGT2ArrowheadShape(n2, r2);
            break;
          default:
            var o2 = A.repositories.dirRepository.get(this.main);
            if (o2 === void 0) throw c(`ExecutionError`, `\\dir ` + this.variant + `{` + this.main + `} not defined.`);
            i2 = o2.toDropShape(e3);
        }
        return e3.appendShapeToFront(i2), i2;
      }, toConnectShape: function(e3) {
        var t3 = e3.env;
        t3.originalReferencePoint = t3.c, A.measure.thickness;
        var n2 = t3.p.edgePoint(t3.c.x, t3.c.y), r2 = t3.c.edgePoint(t3.p.x, t3.p.y);
        return n2.x !== r2.x || n2.y !== r2.y ? new X.Line(n2, r2).toShape(e3, this, this.main, this.variant) : (t3.angle = 0, t3.lastCurve = Q.none, Y.none);
      } }), $(F.ObjectBox.Curve, { toDropShape: function(e3) {
        var t3 = e3.env;
        return t3.originalReferencePoint = t3.c, Y.none;
      }, toConnectShape: function(e3) {
        var t3 = e3.env;
        t3.originalReferencePoint = t3.c;
        var n2 = void 0, r2 = void 0;
        this.objects.foreach((function(e4) {
          n2 = e4.objectForDrop(n2), r2 = e4.objectForConnect(r2);
        })), n2 === void 0 && r2 === void 0 && (r2 = new F.Object(O.empty, new F.ObjectBox.Dir(``, `-`))), A.measure.thickness;
        var i2 = t3.c, a2 = t3.p, o2 = [];
        this.poslist.foreach((function(t4) {
          t4.addPositions(o2, e3);
        })), t3.c = i2, t3.p = a2;
        var s2 = Y.none, c2 = a2, l2 = i2;
        switch (o2.length) {
          case 0:
            return c2.x === l2.x && c2.y === l2.y ? (t3.lastCurve = Q.none, t3.angle = 0, Y.none) : r2 === void 0 ? n2.toConnectShape(e3) : r2.toConnectShape(e3);
          case 1:
            var u2 = (f2 = new X.QuadBezier(c2, o2[0], l2)).tOfShavedStart(c2), d2 = f2.tOfShavedEnd(l2);
            if (u2 === void 0 || d2 === void 0 || u2 >= d2) return t3.angle = 0, t3.lastCurve = Q.none, Y.none;
            s2 = f2.toShape(e3, n2, r2), t3.lastCurve = new Q.QuadBezier(f2, u2, d2, s2), t3.angle = Math.atan2(l2.y - c2.y, l2.x - c2.x);
            break;
          case 2:
            var f2;
            if (u2 = (f2 = new X.CubicBezier(c2, o2[0], o2[1], l2)).tOfShavedStart(c2), d2 = f2.tOfShavedEnd(l2), u2 === void 0 || d2 === void 0 || u2 >= d2) return t3.angle = 0, t3.lastCurve = Q.none, Y.none;
            s2 = f2.toShape(e3, n2, r2), t3.lastCurve = new Q.CubicBezier(f2, u2, d2, s2), t3.angle = Math.atan2(l2.y - c2.y, l2.x - c2.x);
            break;
          default:
            var p2 = new X.CubicBSpline(c2, o2, l2), m2 = new X.CubicBeziers(p2.toCubicBeziers());
            if (u2 = m2.tOfShavedStart(c2), d2 = m2.tOfShavedEnd(l2), u2 === void 0 || d2 === void 0 || u2 >= d2) return t3.angle = 0, t3.lastCurve = Q.none, Y.none;
            s2 = m2.toShape(e3, n2, r2), t3.lastCurve = new Q.CubicBSpline(c2, l2, m2, u2, d2, s2), t3.angle = Math.atan2(l2.y - c2.y, l2.x - c2.x);
        }
        return s2;
      } }), $(F.ObjectBox.Curve.Object.Drop, { objectForDrop: function(e3) {
        return this.object;
      }, objectForConnect: function(e3) {
        return e3;
      } }), $(F.ObjectBox.Curve.Object.Connect, { objectForDrop: function(e3) {
        return e3;
      }, objectForConnect: function(e3) {
        return this.object;
      } }), $(F.ObjectBox.Curve.PosList.CurPos, { addPositions: function(e3, t3) {
        var n2 = t3.env;
        e3.push(n2.c);
      } }), $(F.ObjectBox.Curve.PosList.Pos, { addPositions: function(e3, t3) {
        var n2 = t3.env;
        this.pos.toShape(t3), e3.push(n2.c);
      } }), $(F.ObjectBox.Curve.PosList.AddStack, { addPositions: function(e3, t3) {
        t3.env.stack.reverse().foreach((function(t4) {
          e3.push(t4);
        }));
      } }), $(F.Coord.C, { position: function(e3) {
        return e3.env.c;
      } }), $(F.Coord.P, { position: function(e3) {
        return e3.env.p;
      } }), $(F.Coord.X, { position: function(e3) {
        var t3 = e3.env, n2 = t3.p, r2 = t3.c, i2 = t3.origin, a2 = t3.xBase, o2 = r2.y - n2.y, s2 = n2.x - r2.x, c2 = r2.x * n2.y - r2.y * n2.x, u2 = a2.y, d2 = -a2.x, f2 = a2.x * i2.y - a2.y * i2.x, p2 = o2 * d2 - u2 * s2;
        if (Math.abs(p2) < l.machinePrecision) return console.log(`there is no intersection point.`), Mt.originPosition;
        var m2 = -(d2 * c2 - s2 * f2) / p2, h2 = (u2 * c2 - o2 * f2) / p2;
        return new U.Point(m2, h2);
      } }), $(F.Coord.Y, { position: function(e3) {
        var t3 = e3.env, n2 = t3.p, r2 = t3.c, i2 = t3.origin, a2 = t3.yBase, o2 = r2.y - n2.y, s2 = n2.x - r2.x, c2 = r2.x * n2.y - r2.y * n2.x, u2 = a2.y, d2 = -a2.x, f2 = a2.x * i2.y - a2.y * i2.x, p2 = o2 * d2 - u2 * s2;
        if (Math.abs(p2) < l.machinePrecision) return console.log(`there is no intersection point.`), Mt.originPosition;
        var m2 = -(d2 * c2 - s2 * f2) / p2, h2 = (u2 * c2 - o2 * f2) / p2;
        return new U.Point(m2, h2);
      } }), $(F.Coord.Vector, { position: function(e3) {
        var t3 = this.vector.xy(e3);
        return new U.Point(t3.x, t3.y);
      } }), $(F.Coord.Id, { position: function(e3) {
        return e3.env.lookupPos(this.id).position(e3);
      } }), $(F.Coord.Group, { position: function(e3) {
        var t3 = e3.env, n2 = t3.origin, r2 = t3.xBase, i2 = t3.yBase, a2 = t3.p;
        return this.posDecor.toShape(e3), t3.p = a2, t3.origin = n2, t3.xBase = r2, t3.yBase = i2, t3.c;
      } }), $(F.Coord.StackPosition, { position: function(e3) {
        return e3.env.stackAt(this.number);
      } }), $(F.Coord.DeltaRowColumn, { position: function(e3) {
        var t3 = e3.env, n2 = t3.xymatrixRow, r2 = t3.xymatrixCol;
        if (n2 === void 0 || r2 === void 0) throw c(`ExecutionError`, `xymatrix rows and columns not found for ` + this.toSring());
        var i2 = this.prefix + (n2 + this.dr) + `,` + (r2 + this.dc);
        return e3.env.lookupPos(i2, `in entry "` + t3.xymatrixRow + `,` + t3.xymatrixCol + `": No ` + this + ` (is ` + i2 + `) from here.`).position(e3);
      } }), $(F.Coord.Hops, { position: function(e3) {
        var t3 = e3.env, n2 = t3.xymatrixRow, r2 = t3.xymatrixCol;
        if (n2 === void 0 || r2 === void 0) throw c(`ExecutionError`, `xymatrix rows and columns not found for ` + this.toSring());
        this.hops.foreach((function(e4) {
          switch (e4) {
            case `u`:
              --n2;
              break;
            case `d`:
              n2 += 1;
              break;
            case `l`:
              --r2;
              break;
            case `r`:
              r2 += 1;
          }
        }));
        var i2 = this.prefix + n2 + `,` + r2;
        return e3.env.lookupPos(i2, `in entry "` + t3.xymatrixRow + `,` + t3.xymatrixCol + `": No ` + this + ` (is ` + i2 + `) from here.`).position(e3);
      } }), $(F.Coord.HopsWithPlace, { position: function(e3) {
        var t3 = e3.env, n2 = t3.xymatrixRow, r2 = t3.xymatrixCol;
        if (n2 === void 0 || r2 === void 0) throw c(`ExecutionError`, `xymatrix rows and columns not found for ` + this.toSring());
        this.hops.foreach((function(e4) {
          switch (e4) {
            case `u`:
              --n2;
              break;
            case `d`:
              n2 += 1;
              break;
            case `l`:
              --r2;
              break;
            case `r`:
              r2 += 1;
          }
        }));
        var i2 = this.prefix + n2 + `,` + r2, a2 = e3.env.lookupPos(i2, `in entry "` + t3.xymatrixRow + `,` + t3.xymatrixCol + `": No ` + this + ` (is ` + i2 + `) from here.`).position(e3), o2 = (t3.c, t3.duplicate());
        o2.p = t3.c, o2.c = a2;
        var s2, l2 = o2.c.x - o2.p.x, u2 = o2.c.y - o2.p.y;
        s2 = l2 === 0 && u2 === 0 ? 0 : Math.atan2(u2, l2), o2.angle = s2;
        var d2 = o2.p.edgePoint(o2.c.x, o2.c.y), f2 = o2.c.edgePoint(o2.p.x, o2.p.y);
        o2.lastCurve = new Q.Line(d2, f2, o2.p, o2.c, void 0);
        var p2 = new St(Y.none, o2), m2 = this.place.toShape(p2);
        return o2.lastCurve.position(m2);
      } }), $(F.Vector.InCurBase, { xy: function(e3) {
        return e3.env.absVector(this.x, this.y);
      }, angle: function(e3) {
        var t3 = e3.env.absVector(this.x, this.y);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Vector.Abs, { xy: function(e3) {
        return { x: A.measure.length2em(this.x), y: A.measure.length2em(this.y) };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Vector.Angle, { xy: function(e3) {
        var t3 = Math.PI / 180 * this.degree;
        return e3.env.absVector(Math.cos(t3), Math.sin(t3));
      }, angle: function(e3) {
        return Math.PI / 180 * this.degree;
      } }), $(F.Vector.Dir, { xy: function(e3) {
        var t3 = A.measure.length2em(this.dimen), n2 = this.dir.angle(e3);
        return { x: t3 * Math.cos(n2), y: t3 * Math.sin(n2) };
      }, angle: function(e3) {
        return this.dir.angle(e3);
      } }), $(F.Vector.Corner, { xy: function(e3) {
        var t3 = this.corner.xy(e3);
        return { x: t3.x * this.factor, y: t3.y * this.factor };
      }, angle: function(e3) {
        return this.corner.angle(e3);
      } }), $(F.Corner.L, { xy: function(e3) {
        return { x: -e3.env.c.l, y: 0 };
      }, angle: function(e3) {
        return Math.PI;
      } }), $(F.Corner.R, { xy: function(e3) {
        return { x: e3.env.c.r, y: 0 };
      }, angle: function(e3) {
        return 0;
      } }), $(F.Corner.D, { xy: function(e3) {
        return { x: 0, y: -e3.env.c.d };
      }, angle: function(e3) {
        return -Math.PI / 2;
      } }), $(F.Corner.U, { xy: function(e3) {
        return { x: 0, y: e3.env.c.u };
      }, angle: function(e3) {
        return Math.PI / 2;
      } }), $(F.Corner.CL, { xy: function(e3) {
        var t3 = e3.env.c;
        return { x: -t3.l, y: (t3.u - t3.d) / 2 };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Corner.CR, { xy: function(e3) {
        var t3 = e3.env.c;
        return { x: t3.r, y: (t3.u - t3.d) / 2 };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Corner.CD, { xy: function(e3) {
        var t3 = e3.env.c;
        return { x: (t3.r - t3.l) / 2, y: -t3.d };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Corner.CU, { xy: function(e3) {
        var t3 = e3.env.c;
        return { x: (t3.r - t3.l) / 2, y: t3.u };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Corner.LU, { xy: function(e3) {
        var t3 = e3.env.c;
        return { x: -t3.l, y: t3.u };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Corner.LD, { xy: function(e3) {
        var t3 = e3.env.c;
        return { x: -t3.l, y: -t3.d };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Corner.RU, { xy: function(e3) {
        var t3 = e3.env.c;
        return { x: t3.r, y: t3.u };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Corner.RD, { xy: function(e3) {
        var t3 = e3.env.c;
        return { x: t3.r, y: -t3.d };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Corner.NearestEdgePoint, { xy: function(e3) {
        var t3 = e3.env, n2 = t3.c, r2 = n2.edgePoint(t3.p.x, t3.p.y);
        return { x: r2.x - n2.x, y: r2.y - n2.y };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Corner.PropEdgePoint, { xy: function(e3) {
        var t3 = e3.env, n2 = t3.c, r2 = n2.proportionalEdgePoint(t3.p.x, t3.p.y);
        return { x: r2.x - n2.x, y: r2.y - n2.y };
      }, angle: function(e3) {
        var t3 = this.xy(e3);
        return Math.atan2(t3.y, t3.x);
      } }), $(F.Corner.Axis, { xy: function(e3) {
        return { x: 0, y: A.measure.axisHeightLength };
      }, angle: function(e3) {
        return Math.PI / 2;
      } }), $(F.Modifier, { proceedModifyShape: function(e3, t3, n2) {
        return n2.isEmpty ? t3 : n2.head.modifyShape(e3, t3, n2.tail);
      } }), $(F.Modifier.Vector, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = this.vector.xy(e3), i2 = e3.env;
        return i2.c = i2.c.shiftFrame(-r2.x, -r2.y), t3 = new Y.TranslateShape(-r2.x, -r2.y, t3), this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.RestoreOriginalRefPoint, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = e3.env, i2 = r2.originalReferencePoint;
        if (i2 !== void 0) {
          var a2 = r2.c.x - i2.x, o2 = r2.c.y - i2.y;
          r2.c = r2.c.shiftFrame(a2, o2), t3 = new Y.TranslateShape(a2, o2, t3);
        }
        return this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.Point, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = e3.env.c;
        return e3.env.c = new U.Point(r2.x, r2.y), this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.Rect, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = e3.env.c;
        return e3.env.c = new U.Rect(r2.x, r2.y, { l: r2.l, r: r2.r, u: r2.u, d: r2.d }), this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.Circle, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = e3.env.c;
        return e3.env.c = new U.Ellipse(r2.x, r2.y, r2.l, r2.r, r2.u, r2.d), this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.L, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = e3.env, i2 = r2.c;
        if (i2 !== void 0) {
          var a2, o2, s2 = i2.r + i2.l, c2 = i2.u + i2.d;
          s2 < c2 ? (a2 = (i2.l - i2.r) / 2, o2 = (i2.d - i2.u) / 2) : (a2 = -i2.r + c2 / 2, o2 = (i2.d - i2.u) / 2), r2.c = r2.c.shiftFrame(a2, o2), t3 = new Y.TranslateShape(a2, o2, t3);
        }
        return this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.R, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = e3.env, i2 = r2.c;
        if (i2 !== void 0) {
          var a2, o2, s2 = i2.r + i2.l, c2 = i2.u + i2.d;
          s2 < c2 ? (a2 = (i2.l - i2.r) / 2, o2 = (i2.d - i2.u) / 2) : (a2 = i2.l - c2 / 2, o2 = (i2.d - i2.u) / 2), r2.c = r2.c.shiftFrame(a2, o2), t3 = new Y.TranslateShape(a2, o2, t3);
        }
        return this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.U, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = e3.env, i2 = r2.c;
        if (i2 !== void 0) {
          var a2, o2, s2 = i2.r + i2.l;
          s2 > i2.u + i2.d ? (a2 = (i2.l - i2.r) / 2, o2 = (i2.d - i2.u) / 2) : (a2 = (i2.l - i2.r) / 2, o2 = i2.d - s2 / 2), r2.c = r2.c.shiftFrame(a2, o2), t3 = new Y.TranslateShape(a2, o2, t3);
        }
        return this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.D, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = e3.env, i2 = r2.c;
        if (i2 !== void 0) {
          var a2, o2, s2 = i2.r + i2.l;
          s2 > i2.u + i2.d ? (a2 = (i2.l - i2.r) / 2, o2 = (i2.d - i2.u) / 2) : (a2 = (i2.l - i2.r) / 2, o2 = -i2.u + s2 / 2), r2.c = r2.c.shiftFrame(a2, o2), t3 = new Y.TranslateShape(a2, o2, t3);
        }
        return this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.C, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2, i2, a2 = e3.env, o2 = a2.c;
        return o2 !== void 0 && (r2 = (o2.l - o2.r) / 2, i2 = (o2.d - o2.u) / 2, a2.c = a2.c.shiftFrame(r2, i2), t3 = new Y.TranslateShape(r2, i2, t3)), this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.ChangeColor, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        return t3 = this.proceedModifyShape(e3, t3, n2), new Y.ChangeColorShape(this.colorName, t3);
      } }), $(F.Modifier.Shape.Alphabets, { preprocess: function(e3, t3) {
        var n2 = A.repositories.modifierRepository.get(this.alphabets);
        if (n2 !== void 0) return n2.preprocess(e3, t3);
      }, modifyShape: function(e3, t3, n2) {
        var r2 = A.repositories.modifierRepository.get(this.alphabets);
        if (r2 !== void 0) return r2.modifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.DefineShape, { preprocess: function(e3, t3) {
        var n2 = t3.reverse();
        A.repositories.modifierRepository.put(this.shape, new F.Modifier.Shape.CompositeModifiers(n2));
      }, modifyShape: function(e3, t3, n2) {
        return this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.CompositeModifiers, { preprocess: function(e3, t3) {
        this.modifiers.foreach((function(n2) {
          n2.preprocess(e3, t3), t3 = t3.prepend(n2);
        }));
      }, modifyShape: function(e3, t3, n2) {
        return t3 = this.proceedModifyShape(e3, t3, this.modifiers), this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Invisible, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        return t3 = this.proceedModifyShape(e3, t3, n2), Y.none;
      } }), $(F.Modifier.Hidden, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        return this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Direction, { preprocess: function(e3, t3) {
        e3.env.angle = this.direction.angle(e3);
      }, modifyShape: function(e3, t3, n2) {
        return e3.env.angle = this.direction.angle(e3), this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.AddOp, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = e3.env.c;
        return e3.env.c = this.op.apply(this.size, r2, e3), e3.appendShapeToFront(new Y.InvisibleBoxShape(e3.env.c)), this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.AddOp.Grow, { apply: function(e3, t3, n2) {
        var r2 = n2.env, i2 = e3.isDefault ? { x: 2 * r2.objectmargin, y: 2 * r2.objectmargin } : e3.vector.xy(n2), a2 = Math.abs(i2.x / 2), o2 = Math.abs(i2.y / 2);
        return t3.grow(a2, o2);
      }, applyToDimen: function(e3, t3) {
        return e3 + t3;
      } }), $(F.Modifier.AddOp.Shrink, { apply: function(e3, t3, n2) {
        var r2 = n2.env, i2 = e3.isDefault ? { x: 2 * r2.objectmargin, y: 2 * r2.objectmargin } : e3.vector.xy(n2), a2 = -Math.abs(i2.x / 2), o2 = -Math.abs(i2.y / 2);
        return t3.grow(a2, o2);
      }, applyToDimen: function(e3, t3) {
        return e3 - t3;
      } }), $(F.Modifier.AddOp.Set, { apply: function(e3, t3, n2) {
        var r2 = n2.env, i2 = e3.isDefault ? { x: r2.objectwidth, y: r2.objectheight } : e3.vector.xy(n2), a2 = Math.abs(i2.x), o2 = Math.abs(i2.y);
        return t3.toSize(a2, o2);
      }, applyToDimen: function(e3, t3) {
        return t3;
      } }), $(F.Modifier.AddOp.GrowTo, { apply: function(e3, t3, n2) {
        var r2 = Math.max(t3.l + t3.r, t3.u + t3.d), i2 = e3.isDefault ? { x: r2, y: r2 } : e3.vector.xy(n2), a2 = Math.abs(i2.x), o2 = Math.abs(i2.y);
        return t3.growTo(a2, o2);
      }, applyToDimen: function(e3, t3) {
        return Math.max(Math.max(e3, t3), 0);
      } }), $(F.Modifier.AddOp.ShrinkTo, { apply: function(e3, t3, n2) {
        var r2 = Math.min(t3.l + t3.r, t3.u + t3.d), i2 = e3.isDefault ? { x: r2, y: r2 } : e3.vector.xy(n2), a2 = Math.abs(i2.x), o2 = Math.abs(i2.y);
        return t3.shrinkTo(a2, o2);
      }, applyToDimen: function(e3, t3) {
        return Math.max(Math.min(e3, t3), 0);
      } }), $(F.Modifier.Shape.Frame, { preprocess: function(e3, t3) {
      }, modifyShape: function(e3, t3, n2) {
        var r2 = e3.env;
        if (r2.c !== void 0) {
          this.main;
          var i2 = new F.ObjectBox.Frame.Radius.Default(), a2 = `currentColor`;
          this.options.foreach((function(e4) {
            i2 = e4.getRadius(i2);
          })), this.options.foreach((function(e4) {
            a2 = e4.getColorName(a2);
          }));
          var o2 = r2.duplicate(), s2 = new St(Y.none, o2), c2 = new F.ObjectBox.Frame(i2, this.main).toDropFilledShape(s2, a2, r2.c.isCircle());
          t3 = new Y.CompositeShape(t3, c2);
        }
        return this.proceedModifyShape(e3, t3, n2);
      } }), $(F.Modifier.Shape.Frame.Radius, { getRadius: function(e3) {
        return new F.ObjectBox.Frame.Radius.Vector(this.vector);
      }, getColorName: function(e3) {
        return e3;
      } }), $(F.Modifier.Shape.Frame.Color, { getRadius: function(e3) {
        return e3;
      }, getColorName: function(e3) {
        return this.colorName;
      } }), $(F.Direction.Compound, { angle: function(e3) {
        var t3 = this.dir.angle(e3);
        return this.rots.foreach((function(n2) {
          t3 = n2.rotate(t3, e3);
        })), t3;
      } }), $(F.Direction.Diag, { angle: function(e3) {
        return this.diag.angle(e3);
      } }), $(F.Direction.Vector, { angle: function(e3) {
        return this.vector.angle(e3);
      } }), $(F.Direction.ConstructVector, { angle: function(e3) {
        var t3 = e3.env, n2 = t3.origin, r2 = t3.xBase, i2 = t3.yBase, a2 = t3.p, o2 = t3.c;
        this.posDecor.toShape(e3);
        var s2 = Math.atan2(t3.c.y - t3.p.y, t3.c.x - t3.p.x);
        return t3.c = o2, t3.p = a2, t3.origin = n2, t3.xBase = r2, t3.yBase = i2, s2;
      } }), $(F.Direction.RotVector, { rotate: function(e3, t3) {
        return e3 + this.vector.angle(t3);
      } }), $(F.Direction.RotCW, { rotate: function(e3, t3) {
        return e3 + Math.PI / 2;
      } }), $(F.Direction.RotAntiCW, { rotate: function(e3, t3) {
        return e3 - Math.PI / 2;
      } }), $(F.Diag.Default, { isEmpty: true, angle: function(e3) {
        return e3.env.angle;
      } }), $(F.Diag.Angle, { isEmpty: false, angle: function(e3) {
        return this.ang;
      } }), $(F.Decor, { toShape: function(e3) {
        this.commands.foreach((function(t3) {
          t3.toShape(e3);
        }));
      } }), $(F.Command.Save, { toShape: function(e3) {
        e3.env.saveState(), this.pos.toShape(e3);
      } }), $(F.Command.Restore, { toShape: function(e3) {
        e3.env.restoreState();
      } }), $(F.Command.Pos, { toShape: function(e3) {
        this.pos.toShape(e3);
      } }), $(F.Command.AfterPos, { toShape: function(e3) {
        this.pos.toShape(e3), this.decor.toShape(e3);
      } }), $(F.Command.Drop, { toShape: function(e3) {
        this.object.toDropShape(e3);
      } }), $(F.Command.Connect, { toShape: function(e3) {
        this.object.toConnectShape(e3);
      } }), $(F.Command.Relax, { toShape: function(e3) {
      } }), $(F.Command.Ignore, { toShape: function(e3) {
      } }), $(F.Command.ShowAST, { toShape: function(e3) {
        console.log(this.pos.toString() + ` ` + this.decor);
      } }), $(F.Command.Ar, { toShape: function(e3) {
        var t3 = e3.env, n2 = t3.origin, r2 = t3.xBase, i2 = t3.yBase, a2 = t3.p, o2 = t3.c;
        t3.pathActionForBeforeSegment = y.empty, t3.pathActionForAfterSegment = y.empty, t3.labelsForNextSegmentOnly = y.empty, t3.labelsForLastSegmentOnly = y.empty, t3.labelsForEverySegment = y.empty, t3.segmentSlideEm = y.empty, t3.lastTurnDiag = y.empty, t3.arrowVariant = ``, t3.tailTip = new F.Command.Ar.Form.Tip.Tipchars(``), t3.headTip = new F.Command.Ar.Form.Tip.Tipchars(`>`), t3.stemConn = new F.Command.Ar.Form.Conn.Connchars(`-`), t3.reverseAboveAndBelow = false, t3.arrowObjectModifiers = O.empty, this.forms.foreach((function(t4) {
          t4.toShape(e3);
        })), t3.pathActionForBeforeSegment.isDefined || (t3.pathActionForBeforeSegment = new y.Some(new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.ConnectObject(new F.Object(t3.arrowObjectModifiers, t3.stemConn.getObject(e3))))), new F.Decor(O.empty)))), t3.labelsForNextSegmentOnly = new y.Some(new F.Command.Path.Labels(O.empty.append(new F.Command.Path.Label.At(new F.Pos.Place(new F.Place(1, 1, new F.Place.Factor(0), new F.Slide(y.empty))), t3.tailTip.getObject(e3), y.empty)))), t3.labelsForLastSegmentOnly = new y.Some(new F.Command.Path.Labels(O.empty.append(new F.Command.Path.Label.At(new F.Pos.Place(new F.Place(1, 1, new F.Place.Factor(1), new F.Slide(y.empty))), t3.headTip.getObject(e3), y.empty)))), this.path.toShape(e3), t3.c = o2, t3.p = a2, t3.origin = n2, t3.xBase = r2, t3.yBase = i2;
      } }), $(F.Command.Ar.Form.BuildArrow, { toShape: function(e3) {
        var t3 = e3.env;
        t3.arrowVariant = this.variant, t3.tailTip = this.tailTip, t3.stemConn = this.stemConn, t3.headTip = this.headTip;
      } }), $(F.Command.Ar.Form.ChangeVariant, { toShape: function(e3) {
        e3.env.arrowVariant = this.variant;
      } }), $(F.Command.Ar.Form.ChangeStem, { toShape: function(e3) {
        e3.env.stemConn = new F.Command.Ar.Form.Conn.Connchars(this.connchar);
      } }), $(F.Command.Ar.Form.DashArrowStem, { toShape: function(e3) {
      } }), $(F.Command.Ar.Form.CurveArrow, { toShape: function(e3) {
        var t3 = e3.env, n2 = A.measure.em2length(2 * A.measure.length2em(this.dist));
        t3.pathActionForBeforeSegment = new y.Some(new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.ConnectObject(new F.Object(t3.arrowObjectModifiers, new F.ObjectBox.Curve(O.empty, O.empty.append(new F.ObjectBox.Curve.Object.Connect(t3.stemConn.getObject(e3))), O.empty.append(new F.ObjectBox.Curve.PosList.Pos(new F.Pos.Coord(new F.Coord.Group(new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.ConnectObject(new F.Object(O.empty, new F.ObjectBox.Dir(``, ``)))).append(new F.Pos.Place(new F.Place(0, 0, void 0, new F.Slide(y.empty)))).append(new F.Pos.Plus(new F.Coord.Vector(new F.Vector.Dir(this.direction, n2))))), new F.Decor(O.empty))), O.empty)))))))), new F.Decor(O.empty)));
      } }), $(F.Command.Ar.Form.CurveFitToDirection, { toShape: function(e3) {
        var t3 = e3.env;
        t3.pathActionForBeforeSegment = new y.Some(new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.ConnectObject(new F.Object(t3.arrowObjectModifiers, new F.ObjectBox.Curve(O.empty, O.empty.append(new F.ObjectBox.Curve.Object.Connect(t3.stemConn.getObject(e3))), O.empty.append(new F.ObjectBox.Curve.PosList.Pos(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.SwapPAndC(new F.Coord.C())).append(new F.Pos.Plus(new F.Coord.Vector(new F.Vector.Dir(this.outDirection, `3pc`))))))).append(new F.ObjectBox.Curve.PosList.Pos(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.SwapPAndC(new F.Coord.C())).append(new F.Pos.Plus(new F.Coord.Vector(new F.Vector.Dir(this.inDirection, `3pc`)))))))))))), new F.Decor(O.empty)));
      } }), $(F.Command.Ar.Form.CurveWithControlPoints, { toShape: function(e3) {
        var t3 = e3.env, n2 = t3.duplicate();
        n2.startCapturePositions();
        var r2 = new St(Y.none, n2);
        this.coord.position(r2);
        var i2 = n2.endCapturePositions();
        i2 = i2.append(n2.c);
        var a2 = O.empty;
        i2.reverse().foreach((function(e4) {
          var n3 = t3.inverseAbsVector(e4.x, e4.y);
          a2 = a2.prepend(new F.ObjectBox.Curve.PosList.Pos(new F.Pos.Coord(new F.Coord.Vector(new F.Vector.InCurBase(n3.x, n3.y)), O.empty)));
        })), t3.pathActionForBeforeSegment = new y.Some(new F.PosDecor(new F.Pos.Coord(new F.Coord.C(), O.empty.append(new F.Pos.ConnectObject(new F.Object(t3.arrowObjectModifiers, new F.ObjectBox.Curve(O.empty, O.empty.append(new F.ObjectBox.Curve.Object.Connect(t3.stemConn.getObject(e3))), a2))))), new F.Decor(O.empty)));
      } }), $(F.Command.Ar.Form.AddShape, { toShape: function(e3) {
        e3.env.arrowObjectModifiers = O.empty.append(this.shape);
      } }), $(F.Command.Ar.Form.AddModifiers, { toShape: function(e3) {
        e3.env.arrowObjectModifiers = this.modifiers;
      } }), $(F.Command.Ar.Form.Slide, { toShape: function(e3) {
        e3.env.segmentSlideEm = new y.Some(A.measure.length2em(this.slideDimen));
      } }), $(F.Command.Ar.Form.LabelAt, { toShape: function(e3) {
        e3.env.labelsForEverySegment = new y.Some(new F.Command.Path.Labels(O.empty.append(new F.Command.Path.Label.At(new F.Pos.Place(this.anchor), this.it, y.empty))));
      } }), $(F.Command.Ar.Form.LabelAbove, { toShape: function(e3) {
        var t3, n2 = e3.env;
        t3 = n2.reverseAboveAndBelow ? new F.Command.Path.Label.Below(new F.Pos.Place(this.anchor), this.it, y.empty) : new F.Command.Path.Label.Above(new F.Pos.Place(this.anchor), this.it, y.empty), n2.labelsForEverySegment = new y.Some(new F.Command.Path.Labels(O.empty.append(t3)));
      } }), $(F.Command.Ar.Form.LabelBelow, { toShape: function(e3) {
        var t3, n2 = e3.env;
        t3 = n2.reverseAboveAndBelow ? new F.Command.Path.Label.Above(new F.Pos.Place(this.anchor), this.it, y.empty) : new F.Command.Path.Label.Below(new F.Pos.Place(this.anchor), this.it, y.empty), n2.labelsForEverySegment = new y.Some(new F.Command.Path.Labels(O.empty.append(t3)));
      } }), $(F.Command.Ar.Form.ReverseAboveAndBelow, { toShape: function(e3) {
        e3.env.reverseAboveAndBelow = true;
      } }), $(F.Command.Ar.Form.Conn.Connchars, { getObject: function(e3) {
        var t3 = e3.env, n2 = new F.ObjectBox.Dir(t3.arrowVariant, this.connchars);
        return new F.Object(t3.arrowObjectModifiers, n2);
      } }), $(F.Command.Ar.Form.Conn.Object, { getObject: function(e3) {
        var t3 = e3.env.arrowObjectModifiers.concat(this.object.modifiers);
        return new F.Object(t3, this.object.object);
      } }), $(F.Command.Ar.Form.Conn.Dir, { getObject: function(e3) {
        var t3 = e3.env, n2 = this.dir, r2 = n2;
        return n2.variant === `` && t3.arrowVariant !== `` && (r2 = new F.ObjectBox.Dir(t3.arrowVariant, n2.main)), new F.Object(t3.arrowObjectModifiers, r2);
      } }), $(F.Command.Ar.Form.Tip.Tipchars, { getObject: function(e3) {
        var t3 = e3.env, n2 = new F.ObjectBox.Dir(t3.arrowVariant, this.tipchars);
        return new F.Object(t3.arrowObjectModifiers, n2);
      } }), $(F.Command.Ar.Form.Tip.Object, { getObject: function(e3) {
        var t3 = e3.env.arrowObjectModifiers.concat(this.object.modifiers);
        return new F.Object(t3, this.object.object);
      } }), $(F.Command.Ar.Form.Tip.Dir, { getObject: function(e3) {
        var t3 = e3.env, n2 = this.dir, r2 = n2;
        return n2.variant === `` && t3.arrowVariant !== `` && (r2 = new F.ObjectBox.Dir(t3.arrowVariant, n2.main)), new F.Object(t3.arrowObjectModifiers, r2);
      } }), $(F.Command.Path, { toShape: function(e3) {
        var t3 = e3.env, n2 = t3.origin, r2 = t3.xBase, i2 = t3.yBase, a2 = t3.p, o2 = t3.c;
        t3.pathActionForBeforeSegment = y.empty, t3.pathActionForAfterSegment = y.empty, t3.labelsForNextSegmentOnly = y.empty, t3.labelsForLastSegmentOnly = y.empty, t3.labelsForEverySegment = y.empty, t3.segmentSlideEm = y.empty, t3.lastTurnDiag = y.empty, this.path.toShape(e3), t3.c = o2, t3.p = a2, t3.origin = n2, t3.xBase = r2, t3.yBase = i2;
      } }), $(F.Command.AfterPath, { toShape: function(e3) {
        this.path.toShape(e3), this.decor.toShape(e3);
      } }), $(F.Command.Path.Path, { toShape: function(e3) {
        this.pathElements.foreach((function(t3) {
          t3.toShape(e3);
        }));
      } }), $(F.Command.Path.SetBeforeAction, { toShape: function(e3) {
        e3.env.pathActionForBeforeSegment = new y.Some(this.posDecor);
      } }), $(F.Command.Path.SetAfterAction, { toShape: function(e3) {
        e3.env.pathActionForAfterSegment = new y.Some(this.posDecor);
      } }), $(F.Command.Path.AddLabelNextSegmentOnly, { toShape: function(e3) {
        e3.env.labelsForNextSegmentOnly = new y.Some(this.labels);
      } }), $(F.Command.Path.AddLabelLastSegmentOnly, { toShape: function(e3) {
        e3.env.labelsForLastSegmentOnly = new y.Some(this.labels);
      } }), $(F.Command.Path.AddLabelEverySegment, { toShape: function(e3) {
        e3.env.labelsForEverySegment = new y.Some(this.labels);
      } }), $(F.Command.Path.StraightSegment, { toShape: function(e3) {
        var t3 = e3.env;
        this.segment.setupPositions(e3);
        var n2 = t3.c;
        t3.pathActionForBeforeSegment.foreach((function(t4) {
          t4.toShape(e3);
        })), t3.labelsForNextSegmentOnly.foreach((function(n3) {
          n3.toShape(e3), t3.labelsForNextSegmentOnly = y.empty;
        })), t3.labelsForEverySegment.foreach((function(t4) {
          t4.toShape(e3);
        })), t3.c = n2, t3.pathActionForAfterSegment.foreach((function(t4) {
          t4.toShape(e3);
        })), this.segment.toLabelsShape(e3);
      } }), $(F.Command.Path.LastSegment, { toShape: function(e3) {
        var t3 = e3.env;
        this.segment.setupPositions(e3);
        var n2 = t3.c;
        t3.pathActionForBeforeSegment.foreach((function(t4) {
          t4.toShape(e3);
        })), t3.labelsForNextSegmentOnly.foreach((function(n3) {
          n3.toShape(e3), t3.labelsForNextSegmentOnly = y.empty;
        })), t3.labelsForLastSegmentOnly.foreach((function(n3) {
          n3.toShape(e3), t3.labelsForNextSegmentOnly = y.empty;
        })), t3.labelsForEverySegment.foreach((function(t4) {
          t4.toShape(e3);
        })), t3.c = n2, t3.pathActionForAfterSegment.foreach((function(t4) {
          t4.toShape(e3);
        })), this.segment.toLabelsShape(e3);
      } }), $(F.Command.Path.TurningSegment, { toShape: function(e3) {
        var t3 = e3.env, n2 = t3.c;
        this.segment.pos.toShape(e3), t3.p = n2;
        var r2 = this.turn.explicitizedCircle(e3), i2 = this.turn.radius.radius(e3);
        t3.lastTurnDiag = new y.Some(r2.endDiag);
        var a2 = r2.startVector(e3), o2 = r2.endVector(e3), s2 = t3.segmentSlideEm.getOrElse(0);
        this.segment.slide.dimen.foreach((function(e4) {
          s2 = A.measure.length2em(e4), t3.segmentSlideEm = new y.Some(s2);
        })), s2 !== 0 && (t3.p = t3.p.move(t3.p.x - s2 * a2.y, t3.p.y + s2 * a2.x), t3.c = t3.c.move(t3.c.x - s2 * o2.y, t3.c.y + s2 * o2.x), i2 = r2.orient === `^` ? Math.max(0, i2 - s2) : Math.max(0, i2 + s2));
        var c2, u2 = t3.p.edgePoint(t3.p.x + a2.x, t3.p.y + a2.y), d2 = t3.c, f2 = r2.relativeStartPoint(e3, i2), p2 = r2.relativeEndPoint(e3, i2), m2 = r2.relativeEndPoint(e3, i2 + (r2.orient === `^` ? s2 : -s2)), h2 = a2.x * o2.y - a2.y * o2.x;
        if (Math.abs(h2) < l.machinePrecision) c2 = 0;
        else {
          var g2 = d2.x - u2.x + f2.x - p2.x, _2 = d2.y - u2.y + f2.y - p2.y;
          (c2 = (o2.y * g2 - o2.x * _2) / h2) < 0 && (c2 = 0);
        }
        var v2 = u2.x - f2.x + c2 * a2.x, b2 = u2.y - f2.y + c2 * a2.y, x2 = (r2.toDropShape(e3, v2, b2, i2), new U.Point(v2 + m2.x, b2 + m2.y));
        t3.c = new U.Point(v2 + f2.x, b2 + f2.y), t3.pathActionForBeforeSegment.foreach((function(t4) {
          t4.toShape(e3);
        })), t3.labelsForNextSegmentOnly.foreach((function(n3) {
          n3.toShape(e3), t3.labelsForNextSegmentOnly = y.empty;
        })), t3.labelsForEverySegment.foreach((function(t4) {
          t4.toShape(e3);
        })), t3.c = x2, t3.pathActionForAfterSegment.foreach((function(t4) {
          t4.toShape(e3);
        })), this.segment.toLabelsShape(e3);
      } }), $(F.Command.Path.Turn.Cir, { explicitizedCircle: function(e3) {
        var t3, n2, r2, i2 = e3.env;
        return t3 = this.cir.startDiag.isEmpty ? i2.lastTurnDiag.getOrElse(new F.Diag.R()) : this.cir.startDiag, n2 = this.cir.orient, r2 = this.cir.endDiag.isEmpty ? t3.turn(n2) : this.cir.endDiag, new F.ObjectBox.Cir.Cir.Segment(t3, n2, r2);
      } }), $(F.ObjectBox.Cir.Cir.Segment, { startVector: function(e3) {
        var t3 = this.startDiag.angle(e3);
        return { x: Math.cos(t3), y: Math.sin(t3) };
      }, endVector: function(e3) {
        var t3 = this.endDiag.angle(e3);
        return { x: Math.cos(t3), y: Math.sin(t3) };
      }, relativeStartPointAngle: function(e3) {
        return this.startPointDegree(e3) / 180 * Math.PI;
      }, relativeStartPoint: function(e3, t3) {
        var n2 = this.startPointDegree(e3) / 180 * Math.PI;
        return { x: t3 * Math.cos(n2), y: t3 * Math.sin(n2) };
      }, relativeEndPoint: function(e3, t3) {
        var n2;
        return n2 = this.endPointDegree(e3, this.relativeStartPointAngle(e3)) / 180 * Math.PI, { x: t3 * Math.cos(n2), y: t3 * Math.sin(n2) };
      } }), $(F.Command.Path.Turn.Diag, { explicitizedCircle: function(e3) {
        var t3, n2, r2, i2 = e3.env, a2 = (t3 = this.diag.isEmpty ? i2.lastTurnDiag.getOrElse(new F.Diag.R()) : this.diag).angle(e3);
        return n2 = (i2.c.x - i2.p.x) * Math.sin(a2) - (i2.c.y - i2.p.y) * Math.cos(a2) < 0 ? `^` : `_`, r2 = t3.turn(n2), new F.ObjectBox.Cir.Cir.Segment(t3, n2, r2);
      } }), $(F.Command.Path.TurnRadius.Default, { radius: function(e3) {
        return A.measure.turnradius;
      } }), $(F.Command.Path.TurnRadius.Dimen, { radius: function(e3) {
        return A.measure.length2em(this.dimen);
      } }), $(F.Command.Path.Segment, { setupPositions: function(e3) {
        var t3 = e3.env;
        t3.p = t3.c, this.pos.toShape(e3);
        var n2 = t3.p, r2 = t3.c, i2 = r2.x - n2.x, a2 = r2.y - n2.y, o2 = Math.atan2(a2, i2) + Math.PI / 2, s2 = t3.segmentSlideEm.getOrElse(0);
        this.slide.dimen.foreach((function(e4) {
          s2 = A.measure.length2em(e4), t3.segmentSlideEm = new y.Some(s2);
        })), s2 !== 0 && (n2 = n2.move(n2.x + s2 * Math.cos(o2), n2.y + s2 * Math.sin(o2)), r2 = r2.move(r2.x + s2 * Math.cos(o2), r2.y + s2 * Math.sin(o2))), t3.p = n2, t3.c = r2;
      }, toLabelsShape: function(e3) {
        var t3 = e3.env, n2 = t3.c, r2 = t3.p;
        this.labels.toShape(e3), t3.c = n2, t3.p = r2;
      } }), $(F.Command.Path.Labels, { toShape: function(e3) {
        this.labels.foreach((function(t3) {
          t3.toShape(e3);
        }));
      } }), $(F.Command.Path.Label, { toShape: function(e3) {
        var t3 = e3.env, n2 = t3.p, r2 = t3.c, i2 = this.anchor.toShape(e3), a2 = this.getLabelMargin(e3);
        if (a2 !== 0) {
          var o2 = (b2 = t3.lastCurve).isNone ? Math.atan2(r2.y - n2.y, r2.x - n2.x) + Math.PI / 2 : b2.angle(i2) + Math.PI / 2 + (a2 > 0 ? 0 : Math.PI);
          r2 = t3.c;
          var s2 = new St(Y.none, t3);
          this.it.toDropShape(s2);
          var c2 = s2.shape, l2 = c2.getBoundingBox();
          if (l2 !== void 0) {
            var u2 = l2.x - r2.x, d2 = l2.y - r2.y, f2 = l2.l, p2 = l2.r, m2 = l2.u, h2 = l2.d, g2 = Math.cos(o2), _2 = Math.sin(o2), v2 = Math.min((u2 - f2) * g2 + (d2 - h2) * _2, (u2 - f2) * g2 + (d2 + m2) * _2, (u2 + p2) * g2 + (d2 - h2) * _2, (u2 + p2) * g2 + (d2 + m2) * _2), y2 = Math.abs(a2) - v2;
            t3.c = t3.c.move(r2.x + y2 * g2, r2.y + y2 * _2), e3.appendShapeToFront(new Y.TranslateShape(y2 * g2, y2 * _2, c2));
          }
        } else this.it.toDropShape(e3);
        var b2 = t3.lastCurve;
        this.shouldSliceHole && b2.isDefined && i2 !== void 0 && b2.sliceHole(t3.c, i2), this.aliasOption.foreach((function(e4) {
          t3.savePos(e4, new It.Position(t3.c));
        }));
      } }), $(F.Command.Path.Label.Above, { getLabelMargin: function(e3) {
        return e3.env.labelmargin;
      }, shouldSliceHole: false }), $(F.Command.Path.Label.Below, { getLabelMargin: function(e3) {
        return -e3.env.labelmargin;
      }, shouldSliceHole: false }), $(F.Command.Path.Label.At, { getLabelMargin: function(e3) {
        return 0;
      }, shouldSliceHole: true }), $(F.Command.Xymatrix, { toShape: function(e3) {
        var t3 = e3.env;
        if (t3.c === void 0) return Y.none;
        var n2 = t3.duplicate(), r2 = new St(Y.none, n2);
        n2.xymatrixPrefix = ``, n2.xymatrixRowSepEm = A.measure.length2em(`2pc`), n2.xymatrixColSepEm = A.measure.length2em(`2pc`), n2.xymatrixPretendEntryHeight = y.empty, n2.xymatrixPretendEntryWidth = y.empty, n2.xymatrixFixedRow = false, n2.xymatrixFixedCol = false, n2.xymatrixOrientationAngle = 0, n2.xymatrixEntryModifiers = O.empty, this.setup.foreach((function(e4) {
          e4.toShape(r2);
        }));
        var i2, a2, o2 = n2.xymatrixOrientationAngle, s2 = 0, c2 = 0, l2 = new Bt(this.rows.map((function(e4) {
          c2 += 1, a2 = 0;
          var t4 = new Bt.Row(e4.entries.map((function(e5) {
            a2 += 1;
            var t5 = n2.duplicate();
            t5.origin = { x: 0, y: 0 }, t5.p = t5.c = Mt.originPosition, t5.angle = 0, t5.lastCurve = Q.none, t5.xymatrixRow = c2, t5.xymatrixCol = a2;
            var r3, i3, o3, s3, l3 = new St(Y.none, t5), u3 = e5.toShape(l3), d3 = t5.c;
            if (n2.xymatrixPretendEntryHeight.isDefined) {
              var f3 = n2.xymatrixPretendEntryHeight.get;
              o3 = f3 / 2, s3 = f3 / 2;
            } else o3 = d3.u, s3 = d3.d;
            if (n2.xymatrixPretendEntryWidth.isDefined) {
              var p3 = n2.xymatrixPretendEntryWidth.get;
              r3 = p3 / 2, i3 = p3 / 2;
            } else r3 = d3.l, i3 = d3.r;
            var m3 = new U.Rect(0, 0, { l: r3, r: i3, u: o3, d: s3 });
            return new Bt.Entry(t5.c, u3, e5.decor, m3);
          })), o2);
          return s2 = Math.max(s2, a2), t4;
        })), o2);
        if ((i2 = c2) === 0) return Y.none;
        l2.rows.foreach((function(e4) {
          a2 = 0, e4.entries.foreach((function(e5) {
            a2 += 1, l2.getColumn(a2).addEntry(e5);
          }));
        }));
        var u2, d2, f2 = n2.xymatrixColSepEm, p2 = [], m2 = t3.c.x;
        if (p2.push(m2), n2.xymatrixFixedCol) {
          var h2 = 0, g2 = 0;
          l2.columns.foreach((function(e4) {
            h2 = Math.max(h2, e4.getL()), g2 = Math.max(g2, e4.getR());
          })), l2.columns.tail.foreach((function(e4) {
            m2 = m2 + g2 + f2 + h2, p2.push(m2);
          })), u2 = h2, d2 = p2[p2.length - 1] + g2;
        } else {
          var _2 = l2.columns.head;
          l2.columns.tail.foreach((function(e4) {
            m2 = m2 + _2.getR() + f2 + e4.getL(), p2.push(m2), _2 = e4;
          })), u2 = l2.columns.head.getL(), d2 = m2 + l2.columns.at(s2 - 1).getR() - p2[0];
        }
        var v2, b2, x2 = n2.xymatrixRowSepEm, S2 = [], C2 = t3.c.y;
        if (S2.push(C2), n2.xymatrixFixedRow) {
          var w2 = 0, T2 = 0;
          l2.rows.foreach((function(e4) {
            w2 = Math.max(w2, e4.getU()), T2 = Math.max(T2, e4.getD());
          })), l2.rows.tail.foreach((function(e4) {
            C2 -= T2 + x2 + w2, S2.push(C2);
          })), v2 = w2, b2 = S2[0] - S2[S2.length - 1] + T2;
        } else {
          var E2 = l2.rows.head;
          l2.rows.tail.foreach((function(e4) {
            C2 -= E2.getD() + x2 + e4.getU(), S2.push(C2), E2 = e4;
          })), v2 = l2.rows.head.getU(), b2 = S2[0] - C2 + l2.rows.at(i2 - 1).getD();
        }
        t3.c = new U.Rect(t3.c.x, t3.c.y, { l: u2, r: d2, u: v2, d: b2 });
        var D2 = n2.xymatrixPrefix, ee2 = Math.cos(o2), te2 = Math.sin(o2), ne2 = 0;
        l2.rows.foreach((function(e4) {
          var t4 = 0;
          e4.entries.foreach((function(e5) {
            var r3 = p2[t4], i3 = S2[ne2], a3 = r3 * ee2 - i3 * te2, o3 = r3 * te2 + i3 * ee2, s3 = t4 + 1, c3 = ne2 + 1, l3 = new It.Position(e5.c.move(a3, o3));
            n2.savePos(c3 + `,` + s3, l3), n2.savePos(D2 + c3 + `,` + s3, l3), t4 += 1;
          })), ne2 += 1;
        })), r2 = new St(Y.none, n2), ne2 = 0, l2.rows.foreach((function(e4) {
          var t4 = 0;
          e4.entries.foreach((function(e5) {
            var i3 = p2[t4], a3 = S2[ne2], o3 = i3 * ee2 - a3 * te2, s3 = i3 * te2 + a3 * ee2, c3 = t4 + 1, l3 = ne2 + 1, u3 = new Y.TranslateShape(o3, s3, e5.objectShape);
            r2.appendShapeToFront(u3), n2.c = e5.c.move(o3, s3), n2.xymatrixRow = l3, n2.xymatrixCol = c3, e5.decor.toShape(r2), t4 += 1;
          })), ne2 += 1;
        }));
        var re2 = r2.shape;
        return e3.appendShapeToFront(re2), t3.savedPosition = n2.savedPosition, re2;
      } });
      var Bt = (function() {
        function e3(t3, n2) {
          Lt(this, e3), this.rows = t3, this.columns = O.empty, this.orientation = n2;
        }
        return zt(e3, [{ key: `getColumn`, value: function(t3) {
          if (this.columns.length() >= t3) return this.columns.at(t3 - 1);
          var n2 = new e3.Column(this.orientation);
          return this.columns = this.columns.append(n2), n2;
        } }, { key: `toString`, value: function() {
          return `Xymatrix{
` + this.rows.mkString(`\\\\
`) + `
}`;
        } }]), e3;
      })();
      function Vt(e3, t3, n2) {
        var r2 = [], i2 = [], a2 = { lastNoSuccess: void 0, whiteSpaceRegex: l.whiteSpaceRegex, createTextNode: function(t4) {
          var n3 = new o.Z(t4, e3.stack.env, e3.configuration).mml(), a3 = A.textObjectIdCounter;
          return A.textObjectIdCounter++, r2.push(n3), i2.push(a3), n3;
        } }, s2 = new Se(e3.string, e3.i, a2), u2 = k.parse(t3, s2);
        if (e3.i = u2.next.offset, u2.successful) {
          var d2 = `` + A.xypicCommandIdCounter;
          A.xypicCommandIdCounter++, A.xypicCommandMap[d2] = u2.get();
          var f2 = JSON.stringify(i2);
          return e3.create(n2, { "data-cmd-id": d2, "data-text-mml-ids": f2 }, r2);
        }
        var p2 = a2.lastNoSuccess.next.pos().lineContents();
        throw c(`SyntaxError`, a2.lastNoSuccess.msg + `. Parse error at or near "` + p2 + `".`);
      }
      Bt.Row = (function() {
        function e3(t3, n2) {
          Lt(this, e3), this.entries = t3, this.orientation = n2, H(this, `getU`), H(this, `getD`);
        }
        return zt(e3, [{ key: `getU`, value: function() {
          var e4 = this.orientation, t3 = 0;
          return this.entries.foreach((function(n2) {
            t3 = Math.max(t3, n2.getU(e4));
          })), t3;
        } }, { key: `getD`, value: function() {
          var e4 = this.orientation, t3 = 0;
          return this.entries.foreach((function(n2) {
            t3 = Math.max(t3, n2.getD(e4));
          })), t3;
        } }, { key: `toString`, value: function() {
          return this.entries.mkString(` & `);
        } }]), e3;
      })(), Bt.Column = (function() {
        function e3(t3) {
          Lt(this, e3), this.entries = O.empty, this.orientation = t3, H(this, `getL`), H(this, `getR`);
        }
        return zt(e3, [{ key: `addEntry`, value: function(e4) {
          this.entries = this.entries.append(e4), this.getL.reset, this.getR.reset;
        } }, { key: `getL`, value: function() {
          var e4 = this.orientation, t3 = 0;
          return this.entries.foreach((function(n2) {
            t3 = Math.max(t3, n2.getL(e4));
          })), t3;
        } }, { key: `getR`, value: function() {
          var e4 = this.orientation, t3 = 0;
          return this.entries.foreach((function(n2) {
            t3 = Math.max(t3, n2.getR(e4));
          })), t3;
        } }, { key: `toString`, value: function() {
          return this.entries.mkString(` \\\\ `);
        } }]), e3;
      })(), Bt.Entry = (function() {
        function e3(t3, n2, r2, i2) {
          Lt(this, e3), this.c = t3, this.objectShape = n2, this.decor = r2, this.frame = i2;
        }
        return zt(e3, [{ key: `getDistanceToEdgePoint`, value: function(e4, t3) {
          var n2 = e4.edgePoint(e4.x + Math.cos(t3), e4.y + Math.sin(t3)), r2 = n2.x - e4.x, i2 = n2.y - e4.y;
          return Math.sqrt(r2 * r2 + i2 * i2);
        } }, { key: `getU`, value: function(e4) {
          return e4 === 0 ? this.frame.u : this.getDistanceToEdgePoint(this.frame, e4 + Math.PI / 2);
        } }, { key: `getD`, value: function(e4) {
          return e4 === 0 ? this.frame.d : this.getDistanceToEdgePoint(this.frame, e4 - Math.PI / 2);
        } }, { key: `getL`, value: function(e4) {
          return e4 === 0 ? this.frame.l : this.getDistanceToEdgePoint(this.frame, e4 + Math.PI);
        } }, { key: `getR`, value: function(e4) {
          return e4 === 0 ? this.frame.r : this.getDistanceToEdgePoint(this.frame, e4);
        } }, { key: `toString`, value: function() {
          return this.objectShape.toString() + ` ` + this.decor;
        } }]), e3;
      })(), $(F.Command.Xymatrix.Setup.Prefix, { toShape: function(e3) {
        e3.env.xymatrixPrefix = this.prefix;
      } }), $(F.Command.Xymatrix.Setup.ChangeSpacing.Row, { toShape: function(e3) {
        var t3 = e3.env;
        t3.xymatrixRowSepEm = this.addop.applyToDimen(t3.xymatrixRowSepEm, A.measure.length2em(this.dimen));
      } }), $(F.Command.Xymatrix.Setup.ChangeSpacing.Column, { toShape: function(e3) {
        var t3 = e3.env;
        t3.xymatrixColSepEm = this.addop.applyToDimen(t3.xymatrixColSepEm, A.measure.length2em(this.dimen));
      } }), $(F.Command.Xymatrix.Setup.ChangeSpacing.RowAndColumn, { toShape: function(e3) {
        var t3 = e3.env, n2 = this.addop.applyToDimen(t3.xymatrixRowSepEm, A.measure.length2em(this.dimen));
        t3.xymatrixRowSepEm = n2, t3.xymatrixColSepEm = n2;
      } }), $(F.Command.Xymatrix.Setup.PretendEntrySize.Height, { toShape: function(e3) {
        e3.env.xymatrixPretendEntryHeight = new y.Some(A.measure.length2em(this.dimen));
      } }), $(F.Command.Xymatrix.Setup.PretendEntrySize.Width, { toShape: function(e3) {
        e3.env.xymatrixPretendEntryWidth = new y.Some(A.measure.length2em(this.dimen));
      } }), $(F.Command.Xymatrix.Setup.PretendEntrySize.HeightAndWidth, { toShape: function(e3) {
        var t3 = new y.Some(A.measure.length2em(this.dimen));
        e3.env.xymatrixPretendEntryHeight = t3, e3.env.xymatrixPretendEntryWidth = t3;
      } }), $(F.Command.Xymatrix.Setup.FixGrid.Row, { toShape: function(e3) {
        e3.env.xymatrixFixedRow = true;
      } }), $(F.Command.Xymatrix.Setup.FixGrid.Column, { toShape: function(e3) {
        e3.env.xymatrixFixedCol = true;
      } }), $(F.Command.Xymatrix.Setup.FixGrid.RowAndColumn, { toShape: function(e3) {
        e3.env.xymatrixFixedRow = true, e3.env.xymatrixFixedCol = true;
      } }), $(F.Command.Xymatrix.Setup.AdjustEntrySize.Margin, { toShape: function(e3) {
        var t3 = e3.env;
        t3.objectmargin = this.addop.applyToDimen(t3.objectmargin, A.measure.length2em(this.dimen));
      } }), $(F.Command.Xymatrix.Setup.AdjustEntrySize.Width, { toShape: function(e3) {
        var t3 = e3.env;
        t3.objectwidth = this.addop.applyToDimen(t3.objectwidth, A.measure.length2em(this.dimen));
      } }), $(F.Command.Xymatrix.Setup.AdjustEntrySize.Height, { toShape: function(e3) {
        var t3 = e3.env;
        t3.objectheight = this.addop.applyToDimen(t3.objectheight, A.measure.length2em(this.dimen));
      } }), $(F.Command.Xymatrix.Setup.AdjustLabelSep, { toShape: function(e3) {
        var t3 = e3.env;
        t3.labelmargin = this.addop.applyToDimen(t3.labelmargin, A.measure.length2em(this.dimen));
      } }), $(F.Command.Xymatrix.Setup.SetOrientation, { toShape: function(e3) {
        e3.env.xymatrixOrientationAngle = this.direction.angle(e3);
      } }), $(F.Command.Xymatrix.Setup.AddModifier, { toShape: function(e3) {
        var t3 = e3.env;
        t3.xymatrixEntryModifiers = t3.xymatrixEntryModifiers.prepend(this.modifier);
      } }), $(F.Command.Xymatrix.Entry.SimpleEntry, { toShape: function(e3) {
        var t3 = e3.env, n2 = A.measure.em2length(t3.objectmargin + t3.objectwidth), r2 = A.measure.em2length(t3.objectmargin + t3.objectheight), i2 = new F.Modifier.AddOp(new F.Modifier.AddOp.GrowTo(), new F.Modifier.AddOp.VactorSize(new F.Vector.Abs(n2, r2))), a2 = A.measure.em2length(t3.objectmargin), o2 = new F.Modifier.AddOp(new F.Modifier.AddOp.Grow(), new F.Modifier.AddOp.VactorSize(new F.Vector.Abs(a2, a2))), s2 = this.modifiers.concat(t3.xymatrixEntryModifiers).prepend(i2).prepend(o2);
        return new F.Object(s2, this.objectbox).toDropShape(e3);
      } }), $(F.Command.Xymatrix.Entry.EmptyEntry, { toShape: function(e3) {
        var t3 = e3.env, n2 = A.measure.em2length(t3.objectmargin + t3.objectwidth), r2 = A.measure.em2length(t3.objectmargin + t3.objectheight), i2 = new F.Modifier.AddOp(new F.Modifier.AddOp.GrowTo(), new F.Modifier.AddOp.VactorSize(new F.Vector.Abs(n2, r2))), a2 = A.measure.em2length(t3.objectmargin), o2 = new F.Modifier.AddOp(new F.Modifier.AddOp.Grow(), new F.Modifier.AddOp.VactorSize(new F.Vector.Abs(a2, a2))), s2 = t3.xymatrixEntryModifiers.prepend(i2).prepend(o2);
        return new F.Object(s2, new F.ObjectBox.Empty()).toDropShape(e3);
      } }), $(F.Command.Xymatrix.Entry.ObjectEntry, { toShape: function(e3) {
        return this.object.toDropShape(e3);
      } }), $(F.Command.Twocell, { toShape: function(e3) {
        var t3 = e3.env;
        if (t3.c === void 0) return Y.none;
        var n2 = t3.duplicate(), r2 = new St(Y.none, n2);
        n2.twocellmodmapobject = t3.twocellmodmapobject || new F.Object(O.empty, new F.ObjectBox.Dir(``, `|`)), n2.twocellhead = t3.twocellhead || new F.Object(O.empty, new F.ObjectBox.Dir(``, `>`)), n2.twocelltail = t3.twocelltail || new F.Object(O.empty, new F.ObjectBox.Dir(``, ``)), n2.twocellarrowobject = t3.twocellarrowobject || new F.Object(O.empty, new F.ObjectBox.Dir(``, `=>`)), n2.twocellUpperCurveObjectSpacer = t3.twocellUpperCurveObjectSpacer, n2.twocellUpperCurveObject = t3.twocellUpperCurveObject, n2.twocellLowerCurveObjectSpacer = t3.twocellLowerCurveObjectSpacer, n2.twocellLowerCurveObject = t3.twocellLowerCurveObject, n2.twocellUpperLabel = y.empty, n2.twocellLowerLabel = y.empty, n2.twocellCurvatureEm = y.empty, n2.twocellShouldDrawCurve = true, n2.twocellShouldDrawModMap = false, this.switches.foreach((function(e4) {
          e4.setup(r2);
        })), this.twocell.toShape(r2, this.arrow), e3.appendShapeToFront(r2.shape);
      } }), $(F.Command.Twocell.Hops2cell, { toShape: function(e3, t3) {
        var n2 = e3.env, r2 = n2.c, i2 = n2.angle, a2 = n2.c, o2 = this.targetPosition(e3);
        if (a2 !== void 0 && o2 !== void 0) {
          var s2 = o2.x - a2.x, c2 = o2.y - a2.y;
          if (s2 !== 0 || c2 !== 0) {
            var l2 = new U.Point(a2.x + 0.5 * s2, a2.y + 0.5 * c2), u2 = Math.atan2(c2, s2), d2 = u2 + Math.PI / 2, f2 = n2.twocellCurvatureEm.getOrElse(this.getDefaultCurvature()), p2 = Math.cos(d2), m2 = Math.sin(d2), h2 = this.getUpperControlPoint(a2, o2, l2, f2, p2, m2), g2 = this.getLowerControlPoint(a2, o2, l2, f2, p2, m2);
            if (n2.twocellShouldDrawCurve) {
              var _2, v2;
              if (v2 = (_2 = n2.twocellUpperCurveObjectSpacer) === void 0 ? new F.Object(O.empty, new F.ObjectBox.Dir(``, `-`)) : n2.twocellUpperCurveObject === void 0 ? void 0 : n2.twocellUpperCurveObject.getOrElse(void 0), this.toUpperCurveShape(e3, a2, h2, o2, _2, v2), n2.lastCurve.isDefined) {
                n2.angle = u2;
                var y2 = this.getUpperLabelPosition(a2, o2, l2, f2, p2, m2), b2 = this.getUpperLabelAngle(d2, a2, o2, l2, f2, p2, m2);
                n2.twocellUpperLabel.foreach((function(t4) {
                  t4.toShape(e3, y2, Math.cos(b2), Math.sin(b2), u2);
                })), this.hasUpperTips && t3.toUpperTipsShape(e3);
              }
              if (v2 = (_2 = n2.twocellLowerCurveObjectSpacer) === void 0 ? new F.Object(O.empty, new F.ObjectBox.Dir(``, `-`)) : n2.twocellLowerCurveObject === void 0 ? void 0 : n2.twocellLowerCurveObject.getOrElse(void 0), this.toLowerCurveShape(e3, a2, g2, o2, _2, v2), n2.lastCurve.isDefined) {
                n2.angle = u2;
                var x2 = this.getLowerLabelPosition(a2, o2, l2, f2, p2, m2), S2 = this.getLowerLabelAngle(d2, a2, o2, l2, f2, p2, m2);
                n2.twocellLowerLabel.foreach((function(t4) {
                  t4.toShape(e3, x2, Math.cos(S2), Math.sin(S2), u2);
                })), this.hasLowerTips && t3.toLowerTipsShape(e3);
              }
            }
            n2.c = this.getDefaultArrowPoint(a2, o2, l2, f2, p2, m2), n2.angle = d2 + Math.PI;
            var C2 = l2;
            t3.toArrowShape(e3, C2), n2.c = r2, n2.angle = i2;
          }
        }
      }, _toCurveShape: function(e3, t3, n2, r2, i2, a2) {
        var o2 = e3.env, s2 = new X.QuadBezier(t3, n2, r2), c2 = s2.tOfShavedStart(t3), l2 = s2.tOfShavedEnd(r2);
        if (c2 === void 0 || l2 === void 0 || c2 >= l2) o2.lastCurve = Q.none;
        else {
          var u2 = s2.toShape(e3, i2, a2);
          o2.lastCurve = new Q.QuadBezier(s2, c2, l2, u2);
        }
      }, targetPosition: function(e3) {
        var t3 = e3.env, n2 = t3.xymatrixRow, r2 = t3.xymatrixCol;
        if (n2 === void 0 || r2 === void 0) throw c(`ExecutionError`, `rows and columns not found for hops [` + this.hops + `]`);
        for (var i2 = 0; i2 < this.hops.length; i2++) switch (this.hops[i2]) {
          case `u`:
            --n2;
            break;
          case `d`:
            n2 += 1;
            break;
          case `l`:
            --r2;
            break;
          case `r`:
            r2 += 1;
        }
        var a2 = n2 + `,` + r2;
        return e3.env.lookupPos(a2, `in entry "` + t3.xymatrixRow + `,` + t3.xymatrixCol + `": No ` + this + ` (is ` + a2 + `) from here.`).position(e3);
      } }), $(F.Command.Twocell.Twocell, { getUpperControlPoint: function(e3, t3, n2, r2, i2, a2) {
        return new U.Point(n2.x + r2 * i2, n2.y + r2 * a2);
      }, getLowerControlPoint: function(e3, t3, n2, r2, i2, a2) {
        return new U.Point(n2.x - r2 * i2, n2.y - r2 * a2);
      }, getUpperLabelPosition: function(e3, t3, n2, r2, i2, a2) {
        return new U.Point(n2.x + 0.5 * r2 * i2, n2.y + 0.5 * r2 * a2);
      }, getLowerLabelPosition: function(e3, t3, n2, r2, i2, a2) {
        return new U.Point(n2.x - 0.5 * r2 * i2, n2.y - 0.5 * r2 * a2);
      }, getUpperLabelAngle: function(e3, t3, n2, r2, i2, a2, o2) {
        return e3 + (i2 < 0 ? Math.PI : 0);
      }, getLowerLabelAngle: function(e3, t3, n2, r2, i2, a2, o2) {
        return e3 + (i2 < 0 ? 0 : Math.PI);
      }, getDefaultArrowPoint: function(e3, t3, n2, r2, i2, a2) {
        return n2;
      }, toUpperCurveShape: function(e3, t3, n2, r2, i2, a2) {
        this._toCurveShape(e3, t3, n2, r2, i2, a2);
      }, toLowerCurveShape: function(e3, t3, n2, r2, i2, a2) {
        this._toCurveShape(e3, t3, n2, r2, i2, a2);
      }, getDefaultCurvature: function() {
        return 3.5 * A.measure.lineElementLength;
      }, hasUpperTips: true, hasLowerTips: true }), $(F.Command.Twocell.UpperTwocell, { getUpperControlPoint: function(e3, t3, n2, r2, i2, a2) {
        return new U.Point(n2.x + r2 * i2, n2.y + r2 * a2);
      }, getLowerControlPoint: function(e3, t3, n2, r2, i2, a2) {
        return n2;
      }, getUpperLabelPosition: function(e3, t3, n2, r2, i2, a2) {
        return new U.Point(n2.x + 0.5 * r2 * i2, n2.y + 0.5 * r2 * a2);
      }, getLowerLabelPosition: function(e3, t3, n2, r2, i2, a2) {
        return n2;
      }, getUpperLabelAngle: function(e3, t3, n2, r2, i2, a2, o2) {
        return e3 + (i2 < 0 ? Math.PI : 0);
      }, getLowerLabelAngle: function(e3, t3, n2, r2, i2, a2, o2) {
        return e3 + (i2 < 0 ? 0 : Math.PI);
      }, getDefaultArrowPoint: function(e3, t3, n2, r2, i2, a2) {
        return new U.Point(n2.x + 0.25 * r2 * i2, n2.y + 0.25 * r2 * a2);
      }, toUpperCurveShape: function(e3, t3, n2, r2, i2, a2) {
        this._toCurveShape(e3, t3, n2, r2, i2, a2);
      }, toLowerCurveShape: function(e3, t3, n2, r2, i2, a2) {
        var o2 = t3.edgePoint(r2.x, r2.y), s2 = r2.edgePoint(t3.x, t3.y);
        o2.x !== s2.x || o2.y !== s2.y ? e3.env.lastCurve = new Q.Line(o2, s2, t3, r2, void 0) : e3.env.lastCurve = Q.none;
      }, getDefaultCurvature: function() {
        return 7 * A.measure.lineElementLength;
      }, hasUpperTips: true, hasLowerTips: false }), $(F.Command.Twocell.LowerTwocell, { getUpperControlPoint: function(e3, t3, n2, r2, i2, a2) {
        return n2;
      }, getLowerControlPoint: function(e3, t3, n2, r2, i2, a2) {
        return new U.Point(n2.x + r2 * i2, n2.y + r2 * a2);
      }, getUpperLabelPosition: function(e3, t3, n2, r2, i2, a2) {
        return n2;
      }, getLowerLabelPosition: function(e3, t3, n2, r2, i2, a2) {
        return new U.Point(n2.x + 0.5 * r2 * i2, n2.y + 0.5 * r2 * a2);
      }, getUpperLabelAngle: function(e3, t3, n2, r2, i2, a2, o2) {
        return e3 + (i2 < 0 ? 0 : Math.PI);
      }, getLowerLabelAngle: function(e3, t3, n2, r2, i2, a2, o2) {
        return e3 + (i2 < 0 ? Math.PI : 0);
      }, getDefaultArrowPoint: function(e3, t3, n2, r2, i2, a2) {
        return new U.Point(n2.x + 0.25 * r2 * i2, n2.y + 0.25 * r2 * a2);
      }, toUpperCurveShape: function(e3, t3, n2, r2, i2, a2) {
        var o2 = t3.edgePoint(r2.x, r2.y), s2 = r2.edgePoint(t3.x, t3.y);
        o2.x !== s2.x || o2.y !== s2.y ? e3.env.lastCurve = new Q.Line(o2, s2, t3, r2, void 0) : e3.env.lastCurve = Q.none;
      }, toLowerCurveShape: function(e3, t3, n2, r2, i2, a2) {
        this._toCurveShape(e3, t3, n2, r2, i2, a2);
      }, getDefaultCurvature: function() {
        return -7 * A.measure.lineElementLength;
      }, hasUpperTips: false, hasLowerTips: true }), $(F.Command.Twocell.CompositeMap, { getUpperControlPoint: function(e3, t3, n2, r2, i2, a2) {
        var o2 = this.getMidBoxSize();
        return new U.Ellipse(n2.x + r2 * i2, n2.y + r2 * a2, o2, o2, o2, o2);
      }, getLowerControlPoint: function(e3, t3, n2, r2, i2, a2) {
        var o2 = this.getMidBoxSize();
        return new U.Ellipse(n2.x + r2 * i2, n2.y + r2 * a2, o2, o2, o2, o2);
      }, getUpperLabelPosition: function(e3, t3, n2, r2, i2, a2) {
        var o2 = n2.x + r2 * i2 - t3.x, s2 = n2.y + r2 * a2 - t3.y;
        return new U.Point(t3.x + 0.5 * o2, t3.y + 0.5 * s2);
      }, getLowerLabelPosition: function(e3, t3, n2, r2, i2, a2) {
        var o2 = n2.x + r2 * i2 - e3.x, s2 = n2.y + r2 * a2 - e3.y;
        return new U.Point(e3.x + 0.5 * o2, e3.y + 0.5 * s2);
      }, getUpperLabelAngle: function(e3, t3, n2, r2, i2, a2, o2) {
        var s2 = n2.x - r2.x + i2 * a2, c2 = n2.y - r2.y + i2 * o2, l2 = Math.atan2(c2, s2), u2 = i2 < 0 ? Math.PI : 0;
        return l2 + Math.PI / 2 + u2;
      }, getLowerLabelAngle: function(e3, t3, n2, r2, i2, a2, o2) {
        var s2 = r2.x + i2 * a2 - t3.x, c2 = r2.y + i2 * o2 - t3.y, l2 = Math.atan2(c2, s2), u2 = i2 < 0 ? Math.PI : 0;
        return l2 + Math.PI / 2 + u2;
      }, getDefaultArrowPoint: function(e3, t3, n2, r2, i2, a2) {
        return n2;
      }, toUpperCurveShape: function(e3, t3, n2, r2, i2, a2) {
        var o2 = e3.env, s2 = t3, c2 = n2, l2 = s2.edgePoint(c2.x, c2.y), u2 = c2.edgePoint(s2.x, s2.y), d2 = o2.p, f2 = o2.c;
        o2.p = s2, o2.c = c2, new X.Line(l2, u2).toShape(e3, void 0, `-`, ``), o2.p = d2, o2.c = f2;
      }, toLowerCurveShape: function(e3, t3, n2, r2, i2, a2) {
        var o2 = e3.env, s2 = n2, c2 = r2, l2 = s2.edgePoint(c2.x, c2.y), u2 = c2.edgePoint(s2.x, s2.y), d2 = o2.p, f2 = o2.c;
        o2.p = s2, o2.c = c2, new X.Line(l2, u2).toShape(e3, void 0, `-`, ``), o2.p = d2, o2.c = f2;
      }, getMidBoxSize: function() {
        return 0.5 * A.measure.lineElementLength;
      }, getDefaultCurvature: function() {
        return 3.5 * A.measure.lineElementLength;
      }, hasUpperTips: true, hasLowerTips: true }), $(F.Command.Twocell.Switch.UpperLabel, { setup: function(e3) {
        e3.env.twocellUpperLabel = new y.Some(this);
      }, toShape: function(e3, t3, n2, r2, i2) {
        this.label.toShape(e3, t3, n2, r2, i2);
      } }), $(F.Command.Twocell.Switch.LowerLabel, { setup: function(e3) {
        e3.env.twocellLowerLabel = new y.Some(this);
      }, toShape: function(e3, t3, n2, r2, i2) {
        this.label.toShape(e3, t3, n2, r2, i2);
      } }), $(F.Command.Twocell.Switch.SetCurvature, { setup: function(e3) {
        var t3 = e3.env;
        this.nudge.isOmit ? t3.twocellShouldDrawCurve = false : t3.twocellCurvatureEm = new y.Some(this.nudge.number * A.measure.lineElementLength);
      } }), $(F.Command.Twocell.Switch.DoNotSetCurvedArrows, { setup: function(e3) {
        e3.env.twocellShouldDrawCurve = false;
      } }), $(F.Command.Twocell.Switch.PlaceModMapObject, { setup: function(e3) {
        e3.env.twocellShouldDrawModMap = true;
      } }), $(F.Command.Twocell.Switch.ChangeHeadTailObject, { setup: function(e3) {
        var t3 = e3.env;
        switch (this.what) {
          case "`":
            t3.twocelltail = this.object;
            break;
          case `'`:
            t3.twocellhead = this.object;
        }
      } }), $(F.Command.Twocell.Switch.ChangeCurveObject, { setup: function(e3) {
        var t3 = e3.env;
        switch (this.what) {
          case ``:
            t3.twocellUpperCurveObjectSpacer = this.spacer, t3.twocellUpperCurveObject = this.maybeObject, t3.twocellLowerCurveObjectSpacer = this.spacer, t3.twocellLowerCurveObject = this.maybeObject;
            break;
          case `^`:
            t3.twocellUpperCurveObjectSpacer = this.spacer, t3.twocellUpperCurveObject = this.maybeObject;
            break;
          case `_`:
            t3.twocellLowerCurveObjectSpacer = this.spacer, t3.twocellLowerCurveObject = this.maybeObject;
        }
      } }), $(F.Command.Twocell.Label, { toShape: function(e3, t3, n2, r2, i2) {
        var a2, o2 = this.maybeNudge;
        if (o2.isDefined) {
          var s2 = o2.get;
          if (s2.isOmit) return;
          a2 = s2.number * A.measure.lineElementLength;
        } else a2 = this.getDefaultLabelOffset();
        var c2 = e3.env, l2 = c2.c;
        c2.c = new U.Point(t3.x + a2 * n2, t3.y + a2 * r2), this.labelObject.toDropShape(e3), c2.c = l2;
      }, getDefaultLabelOffset: function() {
        return A.measure.lineElementLength;
      } }), $(F.Command.Twocell.Nudge.Number, { isOmit: false }), $(F.Command.Twocell.Nudge.Omit, { isOmit: true }), $(F.Command.Twocell.Arrow, { toTipsShape: function(e3, t3, n2) {
        var r2 = e3.env, i2 = r2.lastCurve, a2 = r2.c, o2 = r2.angle, s2 = t3 ? Math.PI : 0, c2 = i2.tOfPlace(true, true, t3 ? 0 : 1, 0);
        r2.c = i2.position(c2), r2.angle = i2.angle(c2) + s2, r2.twocellhead.toDropShape(e3), c2 = i2.tOfPlace(true, true, t3 ? 1 : 0, 0), r2.c = i2.position(c2), r2.angle = i2.angle(c2) + s2, n2 ? r2.twocellhead.toDropShape(e3) : r2.twocelltail.toDropShape(e3), r2.twocellShouldDrawModMap && (c2 = i2.tOfPlace(false, false, 0.5, 0), r2.c = i2.position(c2), r2.angle = i2.angle(c2) + s2, r2.twocellmodmapobject.toDropShape(e3)), r2.c = a2, r2.angle = o2;
      } }), $(F.Command.Twocell.Arrow.WithOrientation, { toUpperTipsShape: function(e3) {
        switch (this.tok) {
          case ``:
          case `^`:
          case `_`:
          case `=`:
          case `\\omit`:
          case `'`:
            this.toTipsShape(e3, false, false);
            break;
          case "`":
            this.toTipsShape(e3, true, false);
            break;
          case `"`:
            this.toTipsShape(e3, false, true);
        }
      }, toLowerTipsShape: function(e3) {
        switch (this.tok) {
          case ``:
          case `^`:
          case `_`:
          case `=`:
          case `\\omit`:
          case "`":
            this.toTipsShape(e3, false, false);
            break;
          case `'`:
            this.toTipsShape(e3, true, false);
            break;
          case `"`:
            this.toTipsShape(e3, false, true);
        }
      }, toArrowShape: function(e3, t3) {
        var n2 = e3.env, r2 = n2.c;
        switch (this.tok) {
          case `^`:
            var i2 = n2.angle;
            n2.angle = i2 + Math.PI, n2.twocellarrowobject.toDropShape(e3), n2.c = new U.Point(r2.x + A.measure.lineElementLength * Math.cos(i2 - Math.PI / 2), r2.y + A.measure.lineElementLength * Math.sin(i2 - Math.PI / 2)), this.labelObject.toDropShape(e3), n2.angle = i2;
            break;
          case ``:
          case `_`:
            i2 = n2.angle, n2.twocellarrowobject.toDropShape(e3), n2.c = new U.Point(r2.x + A.measure.lineElementLength * Math.cos(i2 + Math.PI / 2), r2.y + A.measure.lineElementLength * Math.sin(i2 + Math.PI / 2)), this.labelObject.toDropShape(e3);
            break;
          case `=`:
            i2 = n2.angle;
            var a2 = new Y.TwocellEqualityArrowheadShape(n2.c, n2.angle);
            e3.appendShapeToFront(a2), n2.c = new U.Point(r2.x + A.measure.lineElementLength * Math.cos(i2 + Math.PI / 2), r2.y + A.measure.lineElementLength * Math.sin(i2 + Math.PI / 2)), this.labelObject.toDropShape(e3);
            break;
          default:
            this.labelObject.toDropShape(e3);
        }
        n2.c = r2;
      } }), $(F.Command.Twocell.Arrow.WithPosition, { toUpperTipsShape: function(e3) {
        this.toTipsShape(e3, false, false);
      }, toLowerTipsShape: function(e3) {
        this.toTipsShape(e3, false, false);
      }, toArrowShape: function(e3, t3) {
        var n2, r2 = e3.env, i2 = r2.c, a2 = r2.angle, o2 = this.nudge;
        if (o2.isOmit) n2 = i2;
        else {
          var s2 = o2.number * A.measure.lineElementLength;
          n2 = new U.Point(t3.x + s2 * Math.cos(a2), t3.y + s2 * Math.sin(a2));
        }
        r2.c = n2, r2.twocellarrowobject.toDropShape(e3), o2.isOmit || (r2.c = new U.Point(n2.x + A.measure.lineElementLength * Math.cos(a2 + Math.PI / 2), n2.y + A.measure.lineElementLength * Math.sin(a2 + Math.PI / 2)), this.labelObject.toDropShape(e3)), r2.c = i2;
      } }), $(F.Pos.Xyimport.TeXCommand, { toShape: function(e3) {
        var t3 = e3.env;
        if (t3.c === void 0) return Y.none;
        var n2 = t3.duplicate(), r2 = new St(Y.none, n2), i2 = this.graphics.toDropShape(r2), a2 = this.width, o2 = this.height;
        if (a2 === 0 || o2 === 0) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\xyimport should be non-zero.`);
        var s2 = n2.c, l2 = s2.l + s2.r, u2 = s2.u + s2.d;
        if (l2 === 0 || u2 === 0) throw c(`ExecutionError`, `the width and height of the graphics to import should be non-zero.`);
        var d2 = this.xOffset, f2 = this.yOffset;
        t3.c = s2.toRect({ u: u2 / o2 * (o2 - f2), d: u2 / o2 * f2, l: l2 / a2 * d2, r: l2 / a2 * (a2 - d2) }), t3.setXBase(l2 / a2, 0), t3.setYBase(0, u2 / o2);
        var p2 = s2.l - t3.c.l, m2 = s2.d - t3.c.d;
        i2 = new Y.TranslateShape(p2, m2, r2.shape), e3.appendShapeToFront(i2);
      } }), $(F.Pos.Xyimport.Graphics, { toShape: function(e3) {
        var t3 = e3.env;
        if (t3.c === void 0) return Y.none;
        var n2 = t3.duplicate(), r2 = new St(Y.none, n2), i2 = this.width, a2 = this.height;
        if (i2 === 0 || a2 === 0) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\xyimport should be non-zero.`);
        var o2 = this.graphics;
        if (o2.setup(r2), !n2.includegraphicsWidth.isDefined || !n2.includegraphicsHeight.isDefined) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\includegraphics are required.`);
        var s2 = n2.includegraphicsWidth.get, l2 = n2.includegraphicsHeight.get;
        if (s2 === 0 || l2 === 0) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\includegraphics should be non-zero.`);
        var u2 = this.xOffset, d2 = this.yOffset;
        t3.c = n2.c.toRect({ u: l2 / a2 * (a2 - d2), d: l2 / a2 * d2, l: s2 / i2 * u2, r: s2 / i2 * (i2 - u2) }), t3.setXBase(s2 / i2, 0), t3.setYBase(0, l2 / a2);
        var f2 = new Y.ImageShape(t3.c, o2.filepath);
        e3.appendShapeToFront(f2);
      } }), $(F.Command.Includegraphics, { setup: function(e3) {
        var t3 = e3.env;
        t3.includegraphicsWidth = y.empty, t3.includegraphicsHeight = y.empty, this.attributeList.foreach((function(t4) {
          t4.setup(e3);
        }));
      } }), $(F.Command.Includegraphics.Attr.Width, { setup: function(e3) {
        e3.env.includegraphicsWidth = new y.Some(A.measure.length2em(this.dimen));
      } }), $(F.Command.Includegraphics.Attr.Height, { setup: function(e3) {
        e3.env.includegraphicsHeight = new y.Some(A.measure.length2em(this.dimen));
      } });
      var Ht = {};
      Ht.Macro = i.Z.Macro, Ht.xybox = function(e3, t3, n2) {
        var r2 = Vt(e3, et.xybox(), F.xypic.prototype.kind);
        e3.Push(r2);
      }, Ht.xymatrixbox = function(e3, t3, n2) {
        var r2 = Vt(e3, et.xymatrixbox(), F.xypic.prototype.kind);
        e3.Push(r2);
      }, Ht.newdir = function(e3, t3, n2) {
        var r2 = Vt(e3, et.newdir(), F.xypic.newdir.prototype.kind);
        e3.Push(r2);
      }, Ht.xyincludegraphics = function(e3, t3, n2) {
        var r2 = Vt(e3, et.includegraphics(), F.xypic.includegraphics.prototype.kind);
        e3.Push(r2);
      }, Ht.xyEnvironment = function(e3, t3) {
        var n2 = Vt(e3, et.xy(), F.xypic.prototype.kind);
        return e3.Push(t3), n2;
      }, new r.QQ(`xypic-command`, { hole: [`Macro`, `{\\style{visibility:hidden}{x}}`], objectstyle: [`Macro`, `\\textstyle`], labelstyle: [`Macro`, `\\scriptstyle`], twocellstyle: [`Macro`, `\\scriptstyle`], xybox: [`xybox`, `xybox`], xymatrix: [`xymatrixbox`, `xymatrix`], newdir: [`newdir`, `newdir`], includegraphics: [`xyincludegraphics`, `includegraphics`] }, Ht), new r.QM(`xypic-environment`, a.Z.environment, { xy: [`xyEnvironment`, null, false] }, Ht), t2.VK.create(`xypic`, { handler: { macro: [`xypic-command`], environment: [`xypic-environment`] }, preprocessors: [function(e3) {
        e3.math, e3.document, e3.data, A.xypicCommandIdCounter = 0, A.xypicCommandMap = {}, A.textObjectIdCounter = 0, A.wrapperOfTextObjectMap = {};
      }], nodes: { xypic: function(e3, t3, n2) {
        var r2 = e3.mmlFactory;
        return new F.xypic(r2, t3, n2);
      }, "xypic-newdir": function(e3, t3, n2) {
        var r2 = e3.mmlFactory;
        return new F.xypic.newdir(r2, t3, n2);
      }, "xypic-includegraphics": function(e3, t3, n2) {
        var r2 = e3.mmlFactory;
        return new F.xypic.includegraphics(r2, t3, n2);
      } } }), Ie.embeddedModifierMap = { o: new F.Modifier.Shape.Circle(), l: new F.Modifier.Shape.L(), r: new F.Modifier.Shape.R(), u: new F.Modifier.Shape.U(), d: new F.Modifier.Shape.D(), c: new F.Modifier.Shape.C(), aliceblue: new F.Modifier.Shape.ChangeColor(`aliceblue`), antiquewhite: new F.Modifier.Shape.ChangeColor(`antiquewhite`), aqua: new F.Modifier.Shape.ChangeColor(`aqua`), aquamarine: new F.Modifier.Shape.ChangeColor(`aquamarine`), azure: new F.Modifier.Shape.ChangeColor(`azure`), beige: new F.Modifier.Shape.ChangeColor(`beige`), bisque: new F.Modifier.Shape.ChangeColor(`bisque`), black: new F.Modifier.Shape.ChangeColor(`black`), blanchedalmond: new F.Modifier.Shape.ChangeColor(`blanchedalmond`), blue: new F.Modifier.Shape.ChangeColor(`blue`), blueviolet: new F.Modifier.Shape.ChangeColor(`blueviolet`), brown: new F.Modifier.Shape.ChangeColor(`brown`), burlywood: new F.Modifier.Shape.ChangeColor(`burlywood`), cadetblue: new F.Modifier.Shape.ChangeColor(`cadetblue`), chartreuse: new F.Modifier.Shape.ChangeColor(`chartreuse`), chocolate: new F.Modifier.Shape.ChangeColor(`chocolate`), coral: new F.Modifier.Shape.ChangeColor(`coral`), cornflowerblue: new F.Modifier.Shape.ChangeColor(`cornflowerblue`), cornsilk: new F.Modifier.Shape.ChangeColor(`cornsilk`), crimson: new F.Modifier.Shape.ChangeColor(`crimson`), cyan: new F.Modifier.Shape.ChangeColor(`cyan`), darkblue: new F.Modifier.Shape.ChangeColor(`darkblue`), darkcyan: new F.Modifier.Shape.ChangeColor(`darkcyan`), darkgoldenrod: new F.Modifier.Shape.ChangeColor(`darkgoldenrod`), darkgray: new F.Modifier.Shape.ChangeColor(`darkgray`), darkgreen: new F.Modifier.Shape.ChangeColor(`darkgreen`), darkgrey: new F.Modifier.Shape.ChangeColor(`darkgrey`), darkkhaki: new F.Modifier.Shape.ChangeColor(`darkkhaki`), darkmagenta: new F.Modifier.Shape.ChangeColor(`darkmagenta`), darkolivegreen: new F.Modifier.Shape.ChangeColor(`darkolivegreen`), darkorange: new F.Modifier.Shape.ChangeColor(`darkorange`), darkorchid: new F.Modifier.Shape.ChangeColor(`darkorchid`), darkred: new F.Modifier.Shape.ChangeColor(`darkred`), darksalmon: new F.Modifier.Shape.ChangeColor(`darksalmon`), darkseagreen: new F.Modifier.Shape.ChangeColor(`darkseagreen`), darkslateblue: new F.Modifier.Shape.ChangeColor(`darkslateblue`), darkslategray: new F.Modifier.Shape.ChangeColor(`darkslategray`), darkslategrey: new F.Modifier.Shape.ChangeColor(`darkslategrey`), darkturquoise: new F.Modifier.Shape.ChangeColor(`darkturquoise`), darkviolet: new F.Modifier.Shape.ChangeColor(`darkviolet`), deeppink: new F.Modifier.Shape.ChangeColor(`deeppink`), deepskyblue: new F.Modifier.Shape.ChangeColor(`deepskyblue`), dimgray: new F.Modifier.Shape.ChangeColor(`dimgray`), dimgrey: new F.Modifier.Shape.ChangeColor(`dimgrey`), dodgerblue: new F.Modifier.Shape.ChangeColor(`dodgerblue`), firebrick: new F.Modifier.Shape.ChangeColor(`firebrick`), floralwhite: new F.Modifier.Shape.ChangeColor(`floralwhite`), forestgreen: new F.Modifier.Shape.ChangeColor(`forestgreen`), fuchsia: new F.Modifier.Shape.ChangeColor(`fuchsia`), gainsboro: new F.Modifier.Shape.ChangeColor(`gainsboro`), ghostwhite: new F.Modifier.Shape.ChangeColor(`ghostwhite`), gold: new F.Modifier.Shape.ChangeColor(`gold`), goldenrod: new F.Modifier.Shape.ChangeColor(`goldenrod`), gray: new F.Modifier.Shape.ChangeColor(`gray`), grey: new F.Modifier.Shape.ChangeColor(`grey`), green: new F.Modifier.Shape.ChangeColor(`green`), greenyellow: new F.Modifier.Shape.ChangeColor(`greenyellow`), honeydew: new F.Modifier.Shape.ChangeColor(`honeydew`), hotpink: new F.Modifier.Shape.ChangeColor(`hotpink`), indianred: new F.Modifier.Shape.ChangeColor(`indianred`), indigo: new F.Modifier.Shape.ChangeColor(`indigo`), ivory: new F.Modifier.Shape.ChangeColor(`ivory`), khaki: new F.Modifier.Shape.ChangeColor(`khaki`), lavender: new F.Modifier.Shape.ChangeColor(`lavender`), lavenderblush: new F.Modifier.Shape.ChangeColor(`lavenderblush`), lawngreen: new F.Modifier.Shape.ChangeColor(`lawngreen`), lemonchiffon: new F.Modifier.Shape.ChangeColor(`lemonchiffon`), lightblue: new F.Modifier.Shape.ChangeColor(`lightblue`), lightcoral: new F.Modifier.Shape.ChangeColor(`lightcoral`), lightcyan: new F.Modifier.Shape.ChangeColor(`lightcyan`), lightgoldenrodyellow: new F.Modifier.Shape.ChangeColor(`lightgoldenrodyellow`), lightgray: new F.Modifier.Shape.ChangeColor(`lightgray`), lightgreen: new F.Modifier.Shape.ChangeColor(`lightgreen`), lightgrey: new F.Modifier.Shape.ChangeColor(`lightgrey`), lightpink: new F.Modifier.Shape.ChangeColor(`lightpink`), lightsalmon: new F.Modifier.Shape.ChangeColor(`lightsalmon`), lightseagreen: new F.Modifier.Shape.ChangeColor(`lightseagreen`), lightskyblue: new F.Modifier.Shape.ChangeColor(`lightskyblue`), lightslategray: new F.Modifier.Shape.ChangeColor(`lightslategray`), lightslategrey: new F.Modifier.Shape.ChangeColor(`lightslategrey`), lightsteelblue: new F.Modifier.Shape.ChangeColor(`lightsteelblue`), lightyellow: new F.Modifier.Shape.ChangeColor(`lightyellow`), lime: new F.Modifier.Shape.ChangeColor(`lime`), limegreen: new F.Modifier.Shape.ChangeColor(`limegreen`), linen: new F.Modifier.Shape.ChangeColor(`linen`), magenta: new F.Modifier.Shape.ChangeColor(`magenta`), maroon: new F.Modifier.Shape.ChangeColor(`maroon`), mediumaquamarine: new F.Modifier.Shape.ChangeColor(`mediumaquamarine`), mediumblue: new F.Modifier.Shape.ChangeColor(`mediumblue`), mediumorchid: new F.Modifier.Shape.ChangeColor(`mediumorchid`), mediumpurple: new F.Modifier.Shape.ChangeColor(`mediumpurple`), mediumseagreen: new F.Modifier.Shape.ChangeColor(`mediumseagreen`), mediumslateblue: new F.Modifier.Shape.ChangeColor(`mediumslateblue`), mediumspringgreen: new F.Modifier.Shape.ChangeColor(`mediumspringgreen`), mediumturquoise: new F.Modifier.Shape.ChangeColor(`mediumturquoise`), mediumvioletred: new F.Modifier.Shape.ChangeColor(`mediumvioletred`), midnightblue: new F.Modifier.Shape.ChangeColor(`midnightblue`), mintcream: new F.Modifier.Shape.ChangeColor(`mintcream`), mistyrose: new F.Modifier.Shape.ChangeColor(`mistyrose`), moccasin: new F.Modifier.Shape.ChangeColor(`moccasin`), navajowhite: new F.Modifier.Shape.ChangeColor(`navajowhite`), navy: new F.Modifier.Shape.ChangeColor(`navy`), oldlace: new F.Modifier.Shape.ChangeColor(`oldlace`), olive: new F.Modifier.Shape.ChangeColor(`olive`), olivedrab: new F.Modifier.Shape.ChangeColor(`olivedrab`), orange: new F.Modifier.Shape.ChangeColor(`orange`), orangered: new F.Modifier.Shape.ChangeColor(`orangered`), orchid: new F.Modifier.Shape.ChangeColor(`orchid`), palegoldenrod: new F.Modifier.Shape.ChangeColor(`palegoldenrod`), palegreen: new F.Modifier.Shape.ChangeColor(`palegreen`), paleturquoise: new F.Modifier.Shape.ChangeColor(`paleturquoise`), palevioletred: new F.Modifier.Shape.ChangeColor(`palevioletred`), papayawhip: new F.Modifier.Shape.ChangeColor(`papayawhip`), peachpuff: new F.Modifier.Shape.ChangeColor(`peachpuff`), peru: new F.Modifier.Shape.ChangeColor(`peru`), pink: new F.Modifier.Shape.ChangeColor(`pink`), plum: new F.Modifier.Shape.ChangeColor(`plum`), powderblue: new F.Modifier.Shape.ChangeColor(`powderblue`), purple: new F.Modifier.Shape.ChangeColor(`purple`), red: new F.Modifier.Shape.ChangeColor(`red`), rosybrown: new F.Modifier.Shape.ChangeColor(`rosybrown`), royalblue: new F.Modifier.Shape.ChangeColor(`royalblue`), saddlebrown: new F.Modifier.Shape.ChangeColor(`saddlebrown`), salmon: new F.Modifier.Shape.ChangeColor(`salmon`), sandybrown: new F.Modifier.Shape.ChangeColor(`sandybrown`), seagreen: new F.Modifier.Shape.ChangeColor(`seagreen`), seashell: new F.Modifier.Shape.ChangeColor(`seashell`), sienna: new F.Modifier.Shape.ChangeColor(`sienna`), silver: new F.Modifier.Shape.ChangeColor(`silver`), skyblue: new F.Modifier.Shape.ChangeColor(`skyblue`), slateblue: new F.Modifier.Shape.ChangeColor(`slateblue`), slategray: new F.Modifier.Shape.ChangeColor(`slategray`), slategrey: new F.Modifier.Shape.ChangeColor(`slategrey`), snow: new F.Modifier.Shape.ChangeColor(`snow`), springgreen: new F.Modifier.Shape.ChangeColor(`springgreen`), steelblue: new F.Modifier.Shape.ChangeColor(`steelblue`), tan: new F.Modifier.Shape.ChangeColor(`tan`), teal: new F.Modifier.Shape.ChangeColor(`teal`), thistle: new F.Modifier.Shape.ChangeColor(`thistle`), tomato: new F.Modifier.Shape.ChangeColor(`tomato`), turquoise: new F.Modifier.Shape.ChangeColor(`turquoise`), violet: new F.Modifier.Shape.ChangeColor(`violet`), wheat: new F.Modifier.Shape.ChangeColor(`wheat`), white: new F.Modifier.Shape.ChangeColor(`white`), whitesmoke: new F.Modifier.Shape.ChangeColor(`whitesmoke`), yellow: new F.Modifier.Shape.ChangeColor(`yellow`), yellowgreen: new F.Modifier.Shape.ChangeColor(`yellowgreen`) };
      var Ut = n(81), Wt = n(748), Gt = n(226);
      function Kt(e3) {
        return Kt = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e4) {
          return typeof e4;
        } : function(e4) {
          return e4 && typeof Symbol == `function` && e4.constructor === Symbol && e4 !== Symbol.prototype ? `symbol` : typeof e4;
        }, Kt(e3);
      }
      function qt(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Super expression must either be null or a function`);
        e3.prototype = Object.create(t3 && t3.prototype, { constructor: { value: e3, writable: true, configurable: true } }), t3 && Jt(e3, t3);
      }
      function Jt(e3, t3) {
        return Jt = Object.setPrototypeOf || function(e4, t4) {
          return e4.__proto__ = t4, e4;
        }, Jt(e3, t3);
      }
      function Yt(e3) {
        var t3 = (function() {
          if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return false;
          if (typeof Proxy == `function`) return true;
          try {
            return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {
            }))), true;
          } catch {
            return false;
          }
        })();
        return function() {
          var n2, r2 = Qt(e3);
          if (t3) {
            var i2 = Qt(this).constructor;
            n2 = Reflect.construct(r2, arguments, i2);
          } else n2 = r2.apply(this, arguments);
          return Xt(this, n2);
        };
      }
      function Xt(e3, t3) {
        if (t3 && (Kt(t3) === `object` || typeof t3 == `function`)) return t3;
        if (t3 !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
        return Zt(e3);
      }
      function Zt(e3) {
        if (e3 === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
        return e3;
      }
      function Qt(e3) {
        return Qt = Object.setPrototypeOf ? Object.getPrototypeOf : function(e4) {
          return e4.__proto__ || Object.getPrototypeOf(e4);
        }, Qt(e3);
      }
      function $t(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      function en(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function tn(e3, t3, n2) {
        return t3 && en(e3.prototype, t3), n2 && en(e3, n2), e3;
      }
      var nn = it, rn = (function() {
        function e3() {
          $t(this, e3);
        }
        return tn(e3, null, [{ key: `createSVG`, value: function(e4, t3, n2, r2, i2, a2, o2) {
          return new on(e4, t3, n2, r2, i2, a2, o2);
        } }]), e3;
      })(), an = (function() {
        function e3(t3) {
          $t(this, e3), this.xypicWrapper = t3;
        }
        return tn(e3, [{ key: `createElement`, value: function(e4) {
          return this.xypicWrapper.svg(e4);
        } }, { key: `createGroup`, value: function(e4) {
          return new un(this, e4);
        } }, { key: `createChangeColorGroup`, value: function(e4) {
          return new dn(this, e4);
        } }, { key: `createSVGElement`, value: function(e4, t3) {
          var n2 = this.createElement(e4);
          if (t3) {
            for (var r2 in t3) if (t3.hasOwnProperty(r2)) {
              var i2 = t3[r2].toString();
              r2 === `xlink:href` ? this.xypicWrapper.setAttribute(n2, r2, i2, `http://www.w3.org/1999/xlink`) : this.xypicWrapper.setAttribute(n2, r2, i2);
            }
          }
          return this.appendChild(n2), n2;
        } }, { key: `appendChild`, value: function(e4) {
          return this.xypicWrapper.adaptor.append(this.drawArea, e4), e4;
        } }, { key: `transformBuilder`, value: function() {
          return new sn();
        } }]), e3;
      })(), on = (function(e3) {
        qt(n2, e3);
        var t3 = Yt(n2);
        function n2(e4, r2, i2, a2, o2, s2, c2) {
          var l2;
          $t(this, n2);
          var u2 = (l2 = t3.call(this, e4)).createElement(`svg`);
          if (l2.xypicWrapper.setAttribute(u2, `xmlns`, `http://www.w3.org/2000/svg`), l2.xypicWrapper.setAttribute(u2, `version`, `1.1`), c2) for (var d2 in c2) c2.hasOwnProperty(d2) && l2.xypicWrapper.setAttribute(u2, d2, c2[d2].toString());
          for (var f2 in u2.style && (u2.style.width = A.measure.Em(a2), u2.style.height = A.measure.Em(r2 + i2)), c2 = { fill: `none`, stroke: s2, "stroke-linecap": `round`, "stroke-width": A.measure.em2px(o2) }, l2.drawArea = l2.createElement(`g`), c2) c2.hasOwnProperty(f2) && l2.xypicWrapper.setAttribute(l2.drawArea, f2, c2[f2].toString());
          return l2.xypicWrapper.append(u2, l2.drawArea), l2.svg = u2, l2.boundingBox = void 0, l2.color = s2, l2;
        }
        return tn(n2, [{ key: `setHeight`, value: function(e4) {
          this.xypicWrapper.setStyle(this.svg, `height`, A.measure.Em(e4));
        } }, { key: `setWidth`, value: function(e4) {
          this.xypicWrapper.setStyle(this.svg, `width`, A.measure.Em(e4));
        } }, { key: `setAttribute`, value: function(e4, t4) {
          this.xypicWrapper.setAttribute(this.svg, e4, t4.toString());
        } }, { key: `extendBoundingBox`, value: function(e4) {
          this.boundingBox = U.combineRect(this.boundingBox, e4);
        } }, { key: `getOrigin`, value: function() {
          return { x: 0, y: 0 };
        } }, { key: `getCurrentColor`, value: function() {
          return this.color;
        } }]), n2;
      })(an), sn = (function() {
        function e3(t3) {
          $t(this, e3), this.transform = t3 || O.empty;
        }
        return tn(e3, [{ key: `translate`, value: function(t3, n2) {
          return new e3(this.transform.append(new cn(t3, n2)));
        } }, { key: `rotateDegree`, value: function(t3) {
          return new e3(this.transform.append(new ln(t3 / 180 * Math.PI)));
        } }, { key: `rotateRadian`, value: function(t3) {
          return new e3(this.transform.append(new ln(t3)));
        } }, { key: `toString`, value: function() {
          var e4 = ``;
          return this.transform.foreach((function(t3) {
            e4 += t3.toTranslateForm();
          })), e4;
        } }, { key: `apply`, value: function(e4, t3) {
          var n2 = { x: e4, y: t3 };
          return this.transform.foreach((function(e5) {
            n2 = e5.apply(n2.x, n2.y);
          })), n2;
        } }]), e3;
      })(), cn = (function() {
        function e3(t3, n2) {
          $t(this, e3), this.dx = t3, this.dy = n2;
        }
        return tn(e3, [{ key: `apply`, value: function(e4, t3) {
          return { x: e4 - this.dx, y: t3 + this.dy };
        } }, { key: `toTranslateForm`, value: function() {
          return `translate(` + A.measure.em2px(this.dx) + `,` + A.measure.em2px(-this.dy) + `) `;
        } }]), e3;
      })(), ln = (function() {
        function e3(t3) {
          $t(this, e3), this.radian = t3;
        }
        return tn(e3, [{ key: `apply`, value: function(e4, t3) {
          var n2 = Math.cos(this.radian), r2 = Math.sin(this.radian);
          return { x: n2 * e4 + r2 * t3, y: -r2 * e4 + n2 * t3 };
        } }, { key: `toTranslateForm`, value: function() {
          return `rotate(` + nn(-180 * this.radian / Math.PI) + `) `;
        } }]), e3;
      })(), un = (function(e3) {
        qt(n2, e3);
        var t3 = Yt(n2);
        function n2(e4, r2) {
          var i2;
          $t(this, n2), (i2 = t3.call(this, e4.xypicWrapper)).parent = e4, i2.drawArea = e4.createSVGElement(`g`, r2 === void 0 ? {} : { transform: r2.toString() });
          var a2 = e4.getOrigin();
          return i2.origin = r2 === void 0 ? a2 : r2.apply(a2.x, a2.y), H(Zt(i2), `getCurrentColor`), i2;
        }
        return tn(n2, [{ key: `remove`, value: function() {
          this.xypicWrapper.remove(this.drawArea);
        } }, { key: `extendBoundingBox`, value: function(e4) {
          this.parent.extendBoundingBox(e4);
        } }, { key: `getOrigin`, value: function() {
          return this.origin;
        } }, { key: `getCurrentColor`, value: function() {
          return this.parent.getCurrentColor();
        } }]), n2;
      })(an), dn = (function(e3) {
        qt(n2, e3);
        var t3 = Yt(n2);
        function n2(e4, r2) {
          var i2;
          return $t(this, n2), (i2 = t3.call(this, e4.xypicWrapper)).parent = e4, i2.drawArea = e4.createSVGElement(`g`, { stroke: r2 }), i2.color = r2, H(Zt(i2), `getOrigin`), i2;
        }
        return tn(n2, [{ key: `remove`, value: function() {
          this.xypicWrapper.remove(this.drawArea);
        } }, { key: `extendBoundingBox`, value: function(e4) {
          this.parent.extendBoundingBox(e4);
        } }, { key: `getOrigin`, value: function() {
          return this.parent.getOrigin();
        } }, { key: `getCurrentColor`, value: function() {
          return this.color;
        } }]), n2;
      })(an);
      function fn(e3) {
        return fn = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e4) {
          return typeof e4;
        } : function(e4) {
          return e4 && typeof Symbol == `function` && e4.constructor === Symbol && e4 !== Symbol.prototype ? `symbol` : typeof e4;
        }, fn(e3);
      }
      function pn(e3, t3) {
        var n2 = typeof Symbol < `u` && e3[Symbol.iterator] || e3[`@@iterator`];
        if (!n2) {
          if (Array.isArray(e3) || (n2 = (function(e4, t4) {
            if (e4) {
              if (typeof e4 == `string`) return mn(e4, t4);
              var n3 = Object.prototype.toString.call(e4).slice(8, -1);
              if (n3 === `Object` && e4.constructor && (n3 = e4.constructor.name), n3 === `Map` || n3 === `Set`) return Array.from(e4);
              if (n3 === `Arguments` || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(n3)) return mn(e4, t4);
            }
          })(e3)) || t3) {
            n2 && (e3 = n2);
            var r2 = 0, i2 = function() {
            };
            return { s: i2, n: function() {
              return r2 >= e3.length ? { done: true } : { done: false, value: e3[r2++] };
            }, e: function(e4) {
              throw e4;
            }, f: i2 };
          }
          throw TypeError(`Invalid attempt to iterate non-iterable instance.
In order to be iterable, non-array objects must have a [Symbol.iterator]() method.`);
        }
        var a2, o2 = true, s2 = false;
        return { s: function() {
          n2 = n2.call(e3);
        }, n: function() {
          var e4 = n2.next();
          return o2 = e4.done, e4;
        }, e: function(e4) {
          s2 = true, a2 = e4;
        }, f: function() {
          try {
            o2 || n2.return == null || n2.return();
          } finally {
            if (s2) throw a2;
          }
        } };
      }
      function mn(e3, t3) {
        (t3 == null || t3 > e3.length) && (t3 = e3.length);
        for (var n2 = 0, r2 = Array(t3); n2 < t3; n2++) r2[n2] = e3[n2];
        return r2;
      }
      function hn(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      function gn(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function _n(e3, t3, n2) {
        return t3 && gn(e3.prototype, t3), n2 && gn(e3, n2), e3;
      }
      function vn(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Super expression must either be null or a function`);
        e3.prototype = Object.create(t3 && t3.prototype, { constructor: { value: e3, writable: true, configurable: true } }), t3 && yn(e3, t3);
      }
      function yn(e3, t3) {
        return yn = Object.setPrototypeOf || function(e4, t4) {
          return e4.__proto__ = t4, e4;
        }, yn(e3, t3);
      }
      function bn(e3) {
        var t3 = (function() {
          if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return false;
          if (typeof Proxy == `function`) return true;
          try {
            return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {
            }))), true;
          } catch {
            return false;
          }
        })();
        return function() {
          var n2, r2 = Sn(e3);
          if (t3) {
            var i2 = Sn(this).constructor;
            n2 = Reflect.construct(r2, arguments, i2);
          } else n2 = r2.apply(this, arguments);
          return xn(this, n2);
        };
      }
      function xn(e3, t3) {
        if (t3 && (fn(t3) === `object` || typeof t3 == `function`)) return t3;
        if (t3 !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
        return (function(e4) {
          if (e4 === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
          return e4;
        })(e3);
      }
      function Sn(e3) {
        return Sn = Object.setPrototypeOf ? Object.getPrototypeOf : function(e4) {
          return e4.__proto__ || Object.getPrototypeOf(e4);
        }, Sn(e3);
      }
      var Cn = `http://www.w3.org/2000/svg`, wn = it;
      function Tn(e3, t3) {
        var n2 = (function(e4) {
          vn(n3, e4);
          var t4 = bn(n3);
          function n3(e5, r3) {
            var i3, a3 = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
            hn(this, n3), i3 = t4.call(this, e5, r3, a3);
            for (var o2 = A.wrapperOfTextObjectMap, s2 = r3.textMmls, c2 = i3.childNodes, l2 = s2.length, u2 = 0; u2 < l2; u2++) {
              var d2 = s2[u2].xypicTextObjectId;
              o2[d2] = c2[u2];
            }
            return i3._textObjects = [], i3;
          }
          return _n(n3, [{ key: `getElement`, value: function() {
            return this.chtml;
          } }, { key: `appendTextObject`, value: function(e5) {
            this._textObjects.push(e5);
          } }, { key: `getChildWrapper`, value: function(e5) {
            var t5 = e5.xypicTextObjectId;
            if (t5 == null) throw c(`IllegalStateError`, `BUG`);
            var n4 = A.wrapperOfTextObjectMap[t5];
            if (n4 == null) throw c(`IllegalStateError`, `unknown textObjectId:` + t5);
            return n4;
          } }, { key: `toCHTML`, value: function(e5) {
            var t5 = A.svgForDebug, n4 = A.svgForTestLayout;
            this._textObjects = [], this.setupMeasure(this), this._toCHTML(e5), A.svgForDebug = t5, A.svgForTestLayout = n4;
          } }, { key: `setupMeasure`, value: function(e5) {
            var t5 = it, n4 = e5.length2em(`1em`), r3 = parseFloat(e5.px(100).replace(`px`, ``)) / 100, i3 = e5.font.params.axis_height, a3 = e5.length2em(`0.15em`), o2 = function(t6) {
              return Math.round(parseFloat(e5.px(100 * t6).replace(`px`, ``))) / 100;
            };
            A.measure = { length2em: function(n5) {
              return t5(e5.length2em(n5));
            }, oneem: n4, em2length: function(e6) {
              return t5(e6 / n4) + `em`;
            }, Em: function(t6) {
              return e5.em(t6);
            }, em: r3, em2px: o2, axis_height: i3, strokeWidth: e5.length2em(`0.04em`), thickness: a3, jot: e5.length2em(`3pt`), objectmargin: e5.length2em(`3pt`), objectwidth: e5.length2em(`0pt`), objectheight: e5.length2em(`0pt`), labelmargin: e5.length2em(`2.5pt`), turnradius: e5.length2em(`10pt`), lineElementLength: e5.length2em(`5pt`), axisHeightLength: i3 * e5.length2em(`10pt`), dottedDasharray: n4 + ` ` + o2(a3) };
          } }, { key: `append`, value: function(e5, t5) {
            this.adaptor.append(e5, t5);
          } }, { key: `remove`, value: function(e5) {
            this.adaptor.remove(e5);
          } }, { key: `svg`, value: function(e5) {
            var t5 = arguments.length > 1 && arguments[1] !== void 0 ? arguments[1] : {}, n4 = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : [];
            return this.adaptor.node(e5, t5, n4, Cn);
          } }, { key: `setAttribute`, value: function(e5, t5, n4, r3) {
            return this.adaptor.setAttribute(e5, t5, n4, r3);
          } }, { key: `setStyle`, value: function(e5, t5, n4) {
            this.adaptor.setStyle(e5, t5, n4);
          } }, { key: `drawTextObject`, value: function(e5, t5, n4) {
            var r3 = A.measure.length2em(`0.2em`), i3 = t5.xypicWrapper, a3 = i3.getChildWrapper(e5.math), o2 = a3.adaptor, s2 = a3.getBBox(), c2 = s2.scale, l2 = (s2.h + r3) * c2, u2 = (s2.d + r3) * c2, d2 = (s2.w + 2 * r3) * c2, f2 = (l2 + u2) / 2, p2 = d2 / 2, m2 = e5.c;
            if (e5.originalBBox = { H: l2, D: u2, W: d2 }, !n4) {
              var h2 = a3.html(`mjx-xypic-object`);
              o2.append(i3.getElement(), h2), o2.setStyle(h2, `color`, t5.getCurrentColor()), a3.toCHTML(h2);
              var g2 = t5.getOrigin();
              o2.setAttribute(h2, `data-x`, m2.x - p2 - g2.x + r3 * c2), o2.setAttribute(h2, `data-y`, -m2.y - f2 - g2.y + r3 * c2), o2.setAttribute(h2, `data-xypic-id`, e5.math.xypicTextObjectId), i3.appendTextObject(h2);
            }
            return m2.toRect({ u: f2, d: f2, l: p2, r: p2 });
          } }]), n3;
        })(e3), r2 = (function(e4) {
          vn(n3, e4);
          var t4 = bn(n3);
          function n3(e5, r3) {
            var i3, a3 = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
            return hn(this, n3), (i3 = t4.call(this, e5, r3, a3)).shape = null, i3;
          }
          return _n(n3, [{ key: `computeBBox`, value: function(e5) {
            e5.empty();
            var t5 = this.node.cmd;
            if (t5) {
              var n4 = this.length2em(`0.2em`);
              if (this.shape == null) {
                var r3 = A.svgForDebug, i3 = A.svgForTestLayout;
                this._textObjects = [], this.setupMeasure(this), this.adaptor;
                var a3 = A.measure.strokeWidth, o2 = 1, s2 = 0, c2 = 1, l2 = A.measure.em2px, u2 = `black`, d2 = rn.createSVG(this, o2, s2, c2, a3, u2, { viewBox: [0, -l2(o2 + s2), l2(c2), l2(o2 + s2)].join(` `), role: `img`, focusable: false, overflow: `visible` });
                A.svgForDebug = d2, A.svgForTestLayout = d2;
                var f2 = new Mt(), p2 = new St(Y.none, f2);
                t5.toShape(p2), this.shape = p2.shape, A.svgForDebug = r3, A.svgForTestLayout = i3;
              }
              var m2 = this.shape, h2 = m2.getBoundingBox();
              h2 !== void 0 && (h2 = new U.Rect(0, 0, { l: Math.max(0, -(h2.x - h2.l)), r: Math.max(0, h2.x + h2.r), u: Math.max(0, h2.y + h2.u), d: Math.max(0, -(h2.y - h2.d)) }), e5.updateFrom(new Gt.bK({ w: h2.l + h2.r + 2 * n4, h: h2.u + 2 * n4, d: h2.d })));
            }
          } }, { key: `kind`, get: function() {
            return F.xypic.prototype.kind;
          } }, { key: `_toCHTML`, value: function(e5) {
            var t5 = this.standardCHTMLnode(e5);
            this.cthml = t5;
            var n4 = this.adaptor, r3 = this.length2em(`0.2em`), i3 = A.measure.strokeWidth, a3 = 1, o2 = 0, s2 = 1, c2 = A.measure.em2px, l2 = rn.createSVG(this, a3, o2, s2, i3, `black`, { viewBox: [0, -c2(a3 + o2), c2(s2), c2(a3 + o2)].join(` `), role: `img`, focusable: false, overflow: `visible` });
            A.svgForDebug = l2, A.svgForTestLayout = l2, n4.append(t5, l2.svg);
            var u2 = this.node.cmd;
            if (u2) {
              if (this.shape == null) {
                var d2 = new Mt(), f2 = new St(Y.none, d2);
                u2.toShape(f2), this.shape = f2.shape;
              }
              var p2 = this.shape;
              p2.draw(l2);
              var m2 = p2.getBoundingBox();
              if (m2 !== void 0) {
                var h2 = (m2 = new U.Rect(0, 0, { l: Math.max(0, -(m2.x - m2.l)), r: Math.max(0, m2.x + m2.r), u: Math.max(0, m2.y + m2.u), d: Math.max(0, -(m2.y - m2.d)) })).x - m2.l - r3, g2 = -m2.y - m2.u - r3, _2 = m2.l + m2.r + 2 * r3, v2 = m2.u + m2.d + 2 * r3;
                l2.setWidth(_2), l2.setHeight(v2), l2.setAttribute(`viewBox`, [c2(h2), c2(g2), c2(_2), c2(v2)].join(` `)), n4.setStyle(t5, `vertical-align`, wn(-m2.d - r3 + A.measure.axis_height) + `em`);
                var y2, b2 = pn(this._textObjects);
                try {
                  for (b2.s(); !(y2 = b2.n()).done; ) {
                    var x2 = y2.value, S2 = parseFloat(n4.getAttribute(x2, `data-x`)), C2 = parseFloat(n4.getAttribute(x2, `data-y`));
                    n4.setStyle(x2, `left`, wn(S2 - h2) + `em`), n4.setStyle(x2, `top`, wn(C2 + m2.y - m2.d - 0.5 * r3) + `em`);
                  }
                } catch (e6) {
                  b2.e(e6);
                } finally {
                  b2.f();
                }
              } else n4.remove(l2.svg);
            } else n4.remove(l2.svg);
          } }], [{ key: `styles`, get: function() {
            return { "mjx-xypic path": { "stroke-width": `inherit` }, ".MathJax mjx-xypic path": { "stroke-width": `inherit` }, "mjx-xypic-object": { "text-align": `center`, position: `absolute` }, "mjx-xypic": { position: `relative` } };
          } }]), n3;
        })(n2);
        t3[r2.prototype.kind] = r2;
        var i2 = (function(e4) {
          vn(n3, e4);
          var t4 = bn(n3);
          function n3(e5, r3) {
            var i3 = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
            return hn(this, n3), t4.call(this, e5, r3, i3);
          }
          return _n(n3, [{ key: `kind`, get: function() {
            return F.xypic.newdir.prototype.kind;
          } }, { key: `_toCHTML`, value: function(e5) {
            var t5 = this.node.cmd;
            A.repositories.dirRepository.put(t5.dirMain, t5.compositeObject);
          } }]), n3;
        })(n2);
        t3[i2.prototype.kind] = i2;
        var a2 = (function(e4) {
          vn(n3, e4);
          var t4 = bn(n3);
          function n3(e5, r3) {
            var i3, a3 = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
            return hn(this, n3), (i3 = t4.call(this, e5, r3, a3))._setupGraphics(), i3.computeBBox(i3.bbox), i3.bboxComputed = true, i3;
          }
          return _n(n3, [{ key: `kind`, get: function() {
            return F.xypic.includegraphics.prototype.kind;
          } }, { key: `_setupGraphics`, value: function() {
            this.setupMeasure(this);
            var e5 = new Mt(), t5 = new St(Y.none, e5), n4 = this.node.cmd;
            if (n4.setup(t5), !e5.includegraphicsWidth.isDefined || !e5.includegraphicsHeight.isDefined) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\includegraphics are required.`);
            var r3 = e5.includegraphicsWidth.get, i3 = e5.includegraphicsHeight.get;
            this.imageWidth = this.length2em(r3), this.imageHeight = this.length2em(i3), this.filepath = n4.filepath;
          } }, { key: `computeBBox`, value: function(e5) {
            e5.empty(), e5.updateFrom(new Gt.bK({ w: this.imageWidth, h: this.imageHeight, d: 0 }));
          } }, { key: `_toCHTML`, value: function(e5) {
            var t5 = this.standardCHTMLnode(e5);
            this.cthml = t5, this.adaptor.setStyle(t5, `position`, `relative`), this.adaptor.setStyle(t5, `vertical-align`, `0em`);
            var n4 = this.html(`img`);
            this.adaptor.setAttribute(n4, `src`, this.filepath), this.adaptor.setStyle(n4, `width`, wn(this.imageWidth) + `em`), this.adaptor.setStyle(n4, `height`, wn(this.imageHeight) + `em`), this.adaptor.append(t5, n4);
          } }]), n3;
        })(n2);
        t3[a2.prototype.kind] = a2;
      }
      Ut.wO !== void 0 && Tn(Ut.wO, Wt.w);
      var En = n(952), Dn = n(84);
      function On(e3) {
        return On = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e4) {
          return typeof e4;
        } : function(e4) {
          return e4 && typeof Symbol == `function` && e4.constructor === Symbol && e4 !== Symbol.prototype ? `symbol` : typeof e4;
        }, On(e3);
      }
      function kn(e3, t3) {
        var n2 = typeof Symbol < `u` && e3[Symbol.iterator] || e3[`@@iterator`];
        if (!n2) {
          if (Array.isArray(e3) || (n2 = (function(e4, t4) {
            if (e4) {
              if (typeof e4 == `string`) return An(e4, t4);
              var n3 = Object.prototype.toString.call(e4).slice(8, -1);
              if (n3 === `Object` && e4.constructor && (n3 = e4.constructor.name), n3 === `Map` || n3 === `Set`) return Array.from(e4);
              if (n3 === `Arguments` || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(n3)) return An(e4, t4);
            }
          })(e3)) || t3) {
            n2 && (e3 = n2);
            var r2 = 0, i2 = function() {
            };
            return { s: i2, n: function() {
              return r2 >= e3.length ? { done: true } : { done: false, value: e3[r2++] };
            }, e: function(e4) {
              throw e4;
            }, f: i2 };
          }
          throw TypeError(`Invalid attempt to iterate non-iterable instance.
In order to be iterable, non-array objects must have a [Symbol.iterator]() method.`);
        }
        var a2, o2 = true, s2 = false;
        return { s: function() {
          n2 = n2.call(e3);
        }, n: function() {
          var e4 = n2.next();
          return o2 = e4.done, e4;
        }, e: function(e4) {
          s2 = true, a2 = e4;
        }, f: function() {
          try {
            o2 || n2.return == null || n2.return();
          } finally {
            if (s2) throw a2;
          }
        } };
      }
      function An(e3, t3) {
        (t3 == null || t3 > e3.length) && (t3 = e3.length);
        for (var n2 = 0, r2 = Array(t3); n2 < t3; n2++) r2[n2] = e3[n2];
        return r2;
      }
      function jn(e3, t3) {
        if (!(e3 instanceof t3)) throw TypeError(`Cannot call a class as a function`);
      }
      function Mn(e3, t3) {
        for (var n2 = 0; n2 < t3.length; n2++) {
          var r2 = t3[n2];
          r2.enumerable = r2.enumerable || false, r2.configurable = true, `value` in r2 && (r2.writable = true), Object.defineProperty(e3, r2.key, r2);
        }
      }
      function Nn(e3, t3, n2) {
        return t3 && Mn(e3.prototype, t3), n2 && Mn(e3, n2), e3;
      }
      function Pn(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Super expression must either be null or a function`);
        e3.prototype = Object.create(t3 && t3.prototype, { constructor: { value: e3, writable: true, configurable: true } }), t3 && Fn(e3, t3);
      }
      function Fn(e3, t3) {
        return Fn = Object.setPrototypeOf || function(e4, t4) {
          return e4.__proto__ = t4, e4;
        }, Fn(e3, t3);
      }
      function In(e3) {
        var t3 = (function() {
          if (typeof Reflect > `u` || !Reflect.construct || Reflect.construct.sham) return false;
          if (typeof Proxy == `function`) return true;
          try {
            return Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], (function() {
            }))), true;
          } catch {
            return false;
          }
        })();
        return function() {
          var n2, r2 = Rn(e3);
          if (t3) {
            var i2 = Rn(this).constructor;
            n2 = Reflect.construct(r2, arguments, i2);
          } else n2 = r2.apply(this, arguments);
          return Ln(this, n2);
        };
      }
      function Ln(e3, t3) {
        if (t3 && (On(t3) === `object` || typeof t3 == `function`)) return t3;
        if (t3 !== void 0) throw TypeError(`Derived constructors may only return object or undefined`);
        return (function(e4) {
          if (e4 === void 0) throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);
          return e4;
        })(e3);
      }
      function Rn(e3) {
        return Rn = Object.setPrototypeOf ? Object.getPrototypeOf : function(e4) {
          return e4.__proto__ || Object.getPrototypeOf(e4);
        }, Rn(e3);
      }
      var zn = `http://www.w3.org/2000/svg`, Bn = it;
      function Vn(e3, t3) {
        var n2 = (function(e4) {
          Pn(n3, e4);
          var t4 = In(n3);
          function n3(e5, r3) {
            var i3, a3 = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
            jn(this, n3), i3 = t4.call(this, e5, r3, a3);
            for (var o2 = A.wrapperOfTextObjectMap, s2 = r3.textMmls, c2 = i3.childNodes, l2 = s2.length, u2 = 0; u2 < l2; u2++) {
              var d2 = s2[u2].xypicTextObjectId;
              o2[d2] = c2[u2];
            }
            return i3._textObjects = [], i3;
          }
          return Nn(n3, [{ key: `getElement`, value: function() {
            return this.svgNode;
          } }, { key: `appendTextObject`, value: function(e5) {
            this._textObjects.push(e5);
          } }, { key: `getChildWrapper`, value: function(e5) {
            var t5 = e5.xypicTextObjectId;
            if (t5 == null) throw c(`IllegalStateError`, `BUG`);
            var n4 = A.wrapperOfTextObjectMap[t5];
            if (n4 == null) throw c(`IllegalStateError`, `unknown textObjectId:` + t5);
            return n4;
          } }, { key: `toSVG`, value: function(e5) {
            var t5 = A.svgForDebug, n4 = A.svgForTestLayout;
            this._textObjects = [], this.setupMeasure(this), this._toSVG(e5), A.svgForDebug = t5, A.svgForTestLayout = n4;
          } }, { key: `setupMeasure`, value: function(e5) {
            var t5 = it, n4 = e5.length2em(`1em`), r3 = parseFloat(e5.px(100).replace(`px`, ``)) / 100, i3 = e5.font.params.axis_height, a3 = e5.length2em(`0.15em`), o2 = function(t6) {
              return Math.round(parseFloat(e5.px(100 * t6).replace(`px`, ``))) / 100;
            };
            A.measure = { length2em: function(n5) {
              return t5(e5.length2em(n5));
            }, oneem: n4, em2length: function(e6) {
              return t5(e6 / n4) + `em`;
            }, Em: function(t6) {
              return e5.em(t6);
            }, em: r3, em2px: o2, axis_height: i3, strokeWidth: e5.length2em(`0.04em`), thickness: a3, jot: e5.length2em(`3pt`), objectmargin: e5.length2em(`3pt`), objectwidth: e5.length2em(`0pt`), objectheight: e5.length2em(`0pt`), labelmargin: e5.length2em(`2.5pt`), turnradius: e5.length2em(`10pt`), lineElementLength: e5.length2em(`5pt`), axisHeightLength: i3 * e5.length2em(`10pt`), dottedDasharray: n4 + ` ` + o2(a3) };
          } }, { key: `append`, value: function(e5, t5) {
            this.adaptor.append(e5, t5);
          } }, { key: `remove`, value: function(e5) {
            this.adaptor.remove(e5);
          } }, { key: `svg`, value: function(e5) {
            var t5 = arguments.length > 1 && arguments[1] !== void 0 ? arguments[1] : {}, n4 = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : [];
            return this.adaptor.node(e5, t5, n4, zn);
          } }, { key: `setAttribute`, value: function(e5, t5, n4, r3) {
            return this.adaptor.setAttribute(e5, t5, n4, r3);
          } }, { key: `setStyle`, value: function(e5, t5, n4) {
            this.adaptor.setStyle(e5, t5, n4);
          } }, { key: `drawTextObject`, value: function(e5, t5, n4) {
            var r3 = A.measure.length2em(`0.2em`), i3 = t5.xypicWrapper, a3 = i3.getChildWrapper(e5.math), o2 = a3.adaptor, s2 = a3.getBBox(), c2 = s2.scale, l2 = (s2.h + r3) * c2, u2 = (s2.d + r3) * c2, d2 = (s2.w + 2 * r3) * c2, f2 = (l2 + u2) / 2, p2 = d2 / 2, m2 = e5.c;
            if (e5.originalBBox = { H: l2, D: u2, W: d2 }, !n4) {
              var h2 = a3.svg(`g`);
              o2.append(i3.getElement(), h2), o2.setAttribute(h2, `stroke`, t5.getCurrentColor()), o2.setAttribute(h2, `fill`, t5.getCurrentColor()), a3.toSVG(h2);
              var g2 = t5.getOrigin();
              o2.setAttribute(h2, `data-x`, m2.x - p2 - g2.x + r3 * c2), o2.setAttribute(h2, `data-y`, -m2.y + (l2 - u2) / 2 - g2.y), o2.setAttribute(h2, `data-xypic-id`, e5.math.xypicTextObjectId), i3.appendTextObject(h2);
            }
            return m2.toRect({ u: f2, d: f2, l: p2, r: p2 });
          } }]), n3;
        })(e3), r2 = (function(e4) {
          Pn(n3, e4);
          var t4 = In(n3);
          function n3(e5, r3) {
            var i3, a3 = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
            return jn(this, n3), (i3 = t4.call(this, e5, r3, a3)).shape = null, i3;
          }
          return Nn(n3, [{ key: `computeBBox`, value: function(e5) {
            e5.empty();
            var t5 = this.node.cmd;
            if (t5) {
              var n4 = this.length2em(`0.2em`);
              if (this.shape == null) {
                var r3 = A.svgForDebug, i3 = A.svgForTestLayout;
                this._textObjects = [], this.setupMeasure(this), this.adaptor;
                var a3 = A.measure.strokeWidth, o2 = 1, s2 = 0, c2 = 1, l2 = A.measure.em2px, u2 = `black`, d2 = rn.createSVG(this, o2, s2, c2, a3, u2, { viewBox: [0, -l2(o2 + s2), l2(c2), l2(o2 + s2)].join(` `), role: `img`, focusable: false, overflow: `visible` });
                A.svgForDebug = d2, A.svgForTestLayout = d2;
                var f2 = new Mt(), p2 = new St(Y.none, f2);
                t5.toShape(p2), this.shape = p2.shape, A.svgForDebug = r3, A.svgForTestLayout = i3;
              }
              var m2 = this.shape, h2 = m2.getBoundingBox();
              h2 !== void 0 && (h2 = new U.Rect(0, 0, { l: Math.max(0, -(h2.x - h2.l)), r: Math.max(0, h2.x + h2.r), u: Math.max(0, h2.y + h2.u), d: Math.max(0, -(h2.y - h2.d)) }), e5.updateFrom(new Gt.bK({ w: h2.l + h2.r + 2 * n4, h: h2.u + 2 * n4, d: h2.d })));
            }
          } }, { key: `kind`, get: function() {
            return F.xypic.prototype.kind;
          } }, { key: `_toSVG`, value: function(e5) {
            var t5 = this.standardSVGnode(e5);
            this.svgNode = t5;
            var n4 = this.adaptor, r3 = this.length2em(`0.2em`), i3 = A.measure.strokeWidth, a3 = 1, o2 = 0, s2 = 1, c2 = A.measure.em2px, l2 = rn.createSVG(this, a3, o2, s2, i3, `black`, { viewBox: [0, -c2(a3 + o2), c2(s2), c2(a3 + o2)].join(` `), role: `img`, focusable: false, overflow: `visible` });
            A.svgForDebug = l2, A.svgForTestLayout = l2, n4.append(t5, l2.drawArea);
            var u2 = this.node.cmd;
            if (u2) {
              if (this.shape == null) {
                var d2 = new Mt(), f2 = new St(Y.none, d2);
                u2.toShape(f2), this.shape = f2.shape;
              }
              var p2 = this.shape;
              p2.draw(l2);
              var m2 = p2.getBoundingBox();
              if (m2 !== void 0) {
                var h2 = (m2 = new U.Rect(0, 0, { l: Math.max(0, -(m2.x - m2.l)), r: Math.max(0, m2.x + m2.r), u: Math.max(0, m2.y + m2.u), d: Math.max(0, -(m2.y - m2.d)) })).x - m2.l - r3, g2 = -m2.y - m2.u - r3, _2 = m2.l + m2.r + 2 * r3, v2 = m2.u + m2.d + 2 * r3;
                l2.setWidth(_2), l2.setHeight(v2), l2.setAttribute(`viewBox`, [c2(h2), c2(g2), c2(_2), c2(v2)].join(` `));
                var y2 = this.fixed(1) / c2(1);
                n4.setAttribute(l2.drawArea, `transform`, `translate(` + this.fixed(-h2) + `,` + this.fixed(m2.y + A.measure.axis_height) + `) scale(` + y2 + `, ` + -y2 + `)`);
                var b2, x2 = kn(this._textObjects);
                try {
                  for (x2.s(); !(b2 = x2.n()).done; ) {
                    var S2 = b2.value, C2 = parseFloat(n4.getAttribute(S2, `data-x`)), w2 = parseFloat(n4.getAttribute(S2, `data-y`)), T2 = C2 - h2, E2 = -w2 + m2.y + A.measure.axis_height;
                    this.place(T2, E2, S2);
                  }
                } catch (e6) {
                  x2.e(e6);
                } finally {
                  x2.f();
                }
              } else n4.remove(l2.drawArea);
            } else n4.remove(l2.drawArea);
          } }], [{ key: `styles`, get: function() {
            return { 'g[data-mml-node="xypic"] path': { "stroke-width": `inherit` }, '.MathJax g[data-mml-node="xypic"] path': { "stroke-width": `inherit` } };
          } }]), n3;
        })(n2);
        t3[r2.prototype.kind] = r2;
        var i2 = (function(e4) {
          Pn(n3, e4);
          var t4 = In(n3);
          function n3(e5, r3) {
            var i3 = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
            return jn(this, n3), t4.call(this, e5, r3, i3);
          }
          return Nn(n3, [{ key: `kind`, get: function() {
            return F.xypic.newdir.prototype.kind;
          } }, { key: `computeBBox`, value: function(e5) {
            var t5 = this.node.cmd;
            A.repositories.dirRepository.put(t5.dirMain, t5.compositeObject);
          } }, { key: `_toSVG`, value: function(e5) {
            var t5 = this.node.cmd;
            A.repositories.dirRepository.put(t5.dirMain, t5.compositeObject);
          } }]), n3;
        })(n2);
        t3[i2.prototype.kind] = i2;
        var a2 = (function(e4) {
          Pn(n3, e4);
          var t4 = In(n3);
          function n3(e5, r3) {
            var i3, a3 = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : null;
            return jn(this, n3), (i3 = t4.call(this, e5, r3, a3))._setupGraphics(), i3.computeBBox(i3.bbox), i3.bboxComputed = true, i3;
          }
          return Nn(n3, [{ key: `kind`, get: function() {
            return F.xypic.includegraphics.prototype.kind;
          } }, { key: `_setupGraphics`, value: function() {
            this.setupMeasure(this);
            var e5 = new Mt(), t5 = new St(Y.none, e5), n4 = this.node.cmd;
            if (n4.setup(t5), !e5.includegraphicsWidth.isDefined || !e5.includegraphicsHeight.isDefined) throw c(`ExecutionError`, `the 'width' and 'height' attributes of the \\includegraphics are required.`);
            var r3 = e5.includegraphicsWidth.get, i3 = e5.includegraphicsHeight.get;
            this.imageWidth = this.length2em(r3), this.imageHeight = this.length2em(i3), this.filepath = n4.filepath;
          } }, { key: `computeBBox`, value: function(e5) {
            e5.empty(), e5.updateFrom(new Gt.bK({ w: this.imageWidth, h: this.imageHeight, d: 0 }));
          } }, { key: `_toSVG`, value: function(e5) {
            var t5 = this.standardSVGnode(e5);
            this.svgNode = t5;
            var n4 = this.fixed(1), r3 = this.svg(`image`, { x: `0`, y: `0`, preserveAspectRatio: `none`, width: Bn(this.imageWidth), height: Bn(this.imageHeight), transform: `scale(` + n4 + `,` + -n4 + `) translate(0,` + Bn(-this.imageHeight) + `)` });
            this.adaptor.setAttribute(r3, `xlink:href`, this.filepath, `http://www.w3.org/1999/xlink`), this.adaptor.append(t5, r3);
          } }]), n3;
        })(n2);
        t3[a2.prototype.kind] = a2;
      }
      En.y !== void 0 && Vn(En.y, Dn.N);
      var Hn = MathJax._.components.loader.Loader;
      Hn && (MathJax._.output.chtml.Wrapper.CHTMLWrapper || Hn.ready(`output/chtml`).then((function() {
        var e3 = MathJax._.output.chtml;
        Tn(e3.Wrapper.CHTMLWrapper, e3.Wrappers_ts.CHTMLWrappers);
      })).catch((function(e3) {
        return console.log(`Caught`, e3);
      })), MathJax._.output.svg.Wrapper.SVGWrapper || Hn.ready(`output/svg`).then((function() {
        var e3 = MathJax._.output.svg;
        Vn(e3.Wrapper.SVGWrapper, e3.Wrappers_ts.SVGWrappers);
      })).catch((function(e3) {
        return console.log(`Caught`, e3);
      })));
    })();
  })();
  return xypicDrMJn58R$2;
}
var xypicDrMJn58RExports = requireXypicDrMJn58R();
const xypicDrMJn58R = /* @__PURE__ */ getDefaultExportFromCjs(xypicDrMJn58RExports);
const xypicDrMJn58R$1 = /* @__PURE__ */ _mergeNamespaces({
  __proto__: null,
  default: xypicDrMJn58R
}, [xypicDrMJn58RExports]);
export {
  xypicDrMJn58R$1 as x
};
//# sourceMappingURL=xypic-DrMJn58R.js.map
