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
var liteDOMCp0aN3bP$2 = {};
var hasRequiredLiteDOMCp0aN3bP;
function requireLiteDOMCp0aN3bP() {
  if (hasRequiredLiteDOMCp0aN3bP) return liteDOMCp0aN3bP$2;
  hasRequiredLiteDOMCp0aN3bP = 1;
  (function() {
    var e, t, n, r, i, a, o, s, c, l = { 244: function(e2, t2, n2) {
      var r2, i2 = this && this.__extends || (r2 = function(e3, t3) {
        return r2 = Object.setPrototypeOf || { __proto__: [] } instanceof Array && function(e4, t4) {
          e4.__proto__ = t4;
        } || function(e4, t4) {
          for (var n3 in t4) Object.prototype.hasOwnProperty.call(t4, n3) && (e4[n3] = t4[n3]);
        }, r2(e3, t3);
      }, function(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Class extends value ` + String(t3) + ` is not a constructor or null`);
        function n3() {
          this.constructor = e3;
        }
        r2(e3, t3), e3.prototype = t3 === null ? Object.create(t3) : (n3.prototype = t3.prototype, new n3());
      }), a2 = this && this.__assign || function() {
        return a2 = Object.assign || function(e3) {
          for (var t3, n3 = 1, r3 = arguments.length; n3 < r3; n3++) for (var i3 in t3 = arguments[n3]) Object.prototype.hasOwnProperty.call(t3, i3) && (e3[i3] = t3[i3]);
          return e3;
        }, a2.apply(this, arguments);
      };
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.NodeMixin = t2.NodeMixinOptions = void 0;
      var o2 = n2(77);
      t2.NodeMixinOptions = { badCSS: true, badSizes: true }, t2.NodeMixin = function(e3, n3) {
        var r3;
        return n3 === void 0 && (n3 = {}), n3 = (0, o2.userOptions)((0, o2.defaultOptions)({}, t2.NodeMixinOptions), n3), r3 = (function(e4) {
          function t3() {
            var t4 = [...arguments], n4 = e4.call(this, t4[0]) || this, r4 = n4.constructor;
            return n4.options = (0, o2.userOptions)((0, o2.defaultOptions)({}, r4.OPTIONS), t4[1]), n4;
          }
          return i2(t3, e4), t3.prototype.fontSize = function(t4) {
            return n3.badCSS ? this.options.fontSize : e4.prototype.fontSize.call(this, t4);
          }, t3.prototype.fontFamily = function(t4) {
            return n3.badCSS ? this.options.fontFamily : e4.prototype.fontFamily.call(this, t4);
          }, t3.prototype.nodeSize = function(r4, i3, a3) {
            if (i3 === void 0 && (i3 = 1), a3 === void 0 && (a3 = null), !n3.badSizes) return e4.prototype.nodeSize.call(this, r4, i3, a3);
            var o3 = this.textContent(r4), s2 = Array.from(o3.replace(t3.cjkPattern, ``)).length;
            return [(Array.from(o3).length - s2) * this.options.cjkCharWidth + s2 * this.options.unknownCharWidth, this.options.unknownCharHeight];
          }, t3.prototype.nodeBBox = function(t4) {
            return n3.badSizes ? { left: 0, right: 0, top: 0, bottom: 0 } : e4.prototype.nodeBBox.call(this, t4);
          }, t3;
        })(e3), r3.OPTIONS = a2(a2({}, n3.badCSS ? { fontSize: 16, fontFamily: `Times` } : {}), n3.badSizes ? { cjkCharWidth: 1, unknownCharWidth: 0.6, unknownCharHeight: 0.8 } : {}), r3.cjkPattern = new RegExp([`[`, `ᄀ-ᅟ`, `〈〉`, `⺀-〾`, `぀-㉇`, `㉐-䶿`, `一-꓆`, `ꥠ-ꥼ`, `가-힣`, `豈-﫿`, `︐-︙`, `︰-﹫`, `！-｠￠-￦`, `𛀀-𛀁`, `🈀-🉑`, `𠀀-𿿽`, `]`].join(``), `gu`), r3;
      };
    }, 877: function(e2, t2, n2) {
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.LiteDocument = void 0;
      var r2 = n2(946);
      t2.LiteDocument = (function() {
        function e3() {
          this.root = new r2.LiteElement(`html`, {}, [this.head = new r2.LiteElement(`head`), this.body = new r2.LiteElement(`body`)]), this.type = ``;
        }
        return Object.defineProperty(e3.prototype, `kind`, { get: function() {
          return `#document`;
        }, enumerable: false, configurable: true }), e3;
      })();
    }, 946: function(e2, t2) {
      var n2 = this && this.__assign || function() {
        return n2 = Object.assign || function(e3) {
          for (var t3, n3 = 1, r3 = arguments.length; n3 < r3; n3++) for (var i3 in t3 = arguments[n3]) Object.prototype.hasOwnProperty.call(t3, i3) && (e3[i3] = t3[i3]);
          return e3;
        }, n2.apply(this, arguments);
      }, r2 = this && this.__read || function(e3, t3) {
        var n3 = typeof Symbol == `function` && e3[Symbol.iterator];
        if (!n3) return e3;
        var r3, i3, a3 = n3.call(e3), o2 = [];
        try {
          for (; (t3 === void 0 || t3-- > 0) && !(r3 = a3.next()).done; ) o2.push(r3.value);
        } catch (e4) {
          i3 = { error: e4 };
        } finally {
          try {
            r3 && !r3.done && (n3 = a3.return) && n3.call(a3);
          } finally {
            if (i3) throw i3.error;
          }
        }
        return o2;
      }, i2 = this && this.__spreadArray || function(e3, t3, n3) {
        if (n3 || arguments.length === 2) for (var r3, i3 = 0, a3 = t3.length; i3 < a3; i3++) !r3 && i3 in t3 || (r3 ||= Array.prototype.slice.call(t3, 0, i3), r3[i3] = t3[i3]);
        return e3.concat(r3 || Array.prototype.slice.call(t3));
      }, a2 = this && this.__values || function(e3) {
        var t3 = typeof Symbol == `function` && Symbol.iterator, n3 = t3 && e3[t3], r3 = 0;
        if (n3) return n3.call(e3);
        if (e3 && typeof e3.length == `number`) return { next: function() {
          return e3 && r3 >= e3.length && (e3 = void 0), { value: e3 && e3[r3++], done: !e3 };
        } };
        throw TypeError(t3 ? `Object is not iterable.` : `Symbol.iterator is not defined.`);
      };
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.LiteElement = void 0, t2.LiteElement = function(e3, t3, o2) {
        var s2, c2;
        t3 === void 0 && (t3 = {}), o2 === void 0 && (o2 = []), this.kind = e3, this.attributes = n2({}, t3), this.children = i2([], r2(o2), false);
        try {
          for (var l2 = a2(this.children), u2 = l2.next(); !u2.done; u2 = l2.next()) u2.value.parent = this;
        } catch (e4) {
          s2 = { error: e4 };
        } finally {
          try {
            u2 && !u2.done && (c2 = l2.return) && c2.call(l2);
          } finally {
            if (s2) throw s2.error;
          }
        }
        this.styles = null;
      };
    }, 6: function(e2, t2) {
      var n2 = this && this.__read || function(e3, t3) {
        var n3 = typeof Symbol == `function` && e3[Symbol.iterator];
        if (!n3) return e3;
        var r3, i2, a2 = n3.call(e3), o2 = [];
        try {
          for (; (t3 === void 0 || t3-- > 0) && !(r3 = a2.next()).done; ) o2.push(r3.value);
        } catch (e4) {
          i2 = { error: e4 };
        } finally {
          try {
            r3 && !r3.done && (n3 = a2.return) && n3.call(a2);
          } finally {
            if (i2) throw i2.error;
          }
        }
        return o2;
      }, r2 = this && this.__spreadArray || function(e3, t3, n3) {
        if (n3 || arguments.length === 2) for (var r3, i2 = 0, a2 = t3.length; i2 < a2; i2++) !r3 && i2 in t3 || (r3 ||= Array.prototype.slice.call(t3, 0, i2), r3[i2] = t3[i2]);
        return e3.concat(r3 || Array.prototype.slice.call(t3));
      };
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.LiteList = void 0, t2.LiteList = (function() {
        function e3(e4) {
          this.nodes = [], this.nodes = r2([], n2(e4), false);
        }
        return e3.prototype.append = function(e4) {
          this.nodes.push(e4);
        }, e3.prototype[Symbol.iterator] = function() {
          var e4 = 0;
          return { next: function() {
            return e4 === this.nodes.length ? { value: null, done: true } : { value: this.nodes[e4++], done: false };
          } };
        }, e3;
      })();
    }, 246: function(e2, t2, n2) {
      var r2 = this && this.__createBinding || (Object.create ? function(e3, t3, n3, r3) {
        r3 === void 0 && (r3 = n3);
        var i3 = Object.getOwnPropertyDescriptor(t3, n3);
        i3 && !(`get` in i3 ? !t3.__esModule : i3.writable || i3.configurable) || (i3 = { enumerable: true, get: function() {
          return t3[n3];
        } }), Object.defineProperty(e3, r3, i3);
      } : function(e3, t3, n3, r3) {
        r3 === void 0 && (r3 = n3), e3[r3] = t3[n3];
      }), i2 = this && this.__setModuleDefault || (Object.create ? function(e3, t3) {
        Object.defineProperty(e3, `default`, { enumerable: true, value: t3 });
      } : function(e3, t3) {
        e3.default = t3;
      }), a2 = this && this.__importStar || function(e3) {
        if (e3 && e3.__esModule) return e3;
        var t3 = {};
        if (e3 != null) for (var n3 in e3) n3 !== `default` && Object.prototype.hasOwnProperty.call(e3, n3) && r2(t3, e3, n3);
        return i2(t3, e3), t3;
      }, o2 = this && this.__read || function(e3, t3) {
        var n3 = typeof Symbol == `function` && e3[Symbol.iterator];
        if (!n3) return e3;
        var r3, i3, a3 = n3.call(e3), o3 = [];
        try {
          for (; (t3 === void 0 || t3-- > 0) && !(r3 = a3.next()).done; ) o3.push(r3.value);
        } catch (e4) {
          i3 = { error: e4 };
        } finally {
          try {
            r3 && !r3.done && (n3 = a3.return) && n3.call(a3);
          } finally {
            if (i3) throw i3.error;
          }
        }
        return o3;
      }, s2 = this && this.__values || function(e3) {
        var t3 = typeof Symbol == `function` && Symbol.iterator, n3 = t3 && e3[t3], r3 = 0;
        if (n3) return n3.call(e3);
        if (e3 && typeof e3.length == `number`) return { next: function() {
          return e3 && r3 >= e3.length && (e3 = void 0), { value: e3 && e3[r3++], done: !e3 };
        } };
        throw TypeError(t3 ? `Object is not iterable.` : `Symbol.iterator is not defined.`);
      };
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.LiteParser = t2.PATTERNS = void 0;
      var c2, l2 = a2(n2(29)), u2 = n2(946), d2 = n2(735);
      (function(e3) {
        e3.TAGNAME = `[a-z][^\\s\\n>]*`, e3.ATTNAME = `[a-z][^\\s\\n>=]*`, e3.VALUE = `(?:'[^']*'|"[^"]*"|[^\\s\\n]+)`, e3.VALUESPLIT = `(?:'([^']*)'|"([^"]*)"|([^\\s\\n]+))`, e3.SPACE = `(?:\\s|\\n)+`, e3.OPTIONALSPACE = `(?:\\s|\\n)*`, e3.ATTRIBUTE = e3.ATTNAME + `(?:` + e3.OPTIONALSPACE + `=` + e3.OPTIONALSPACE + e3.VALUE + `)?`, e3.ATTRIBUTESPLIT = `(` + e3.ATTNAME + `)(?:` + e3.OPTIONALSPACE + `=` + e3.OPTIONALSPACE + e3.VALUESPLIT + `)?`, e3.TAG = `(<(?:` + e3.TAGNAME + `(?:` + e3.SPACE + e3.ATTRIBUTE + `)*` + e3.OPTIONALSPACE + `/?|/` + e3.TAGNAME + `|!--[^]*?--|![^]*?)(?:>|$))`, e3.tag = new RegExp(e3.TAG, `i`), e3.attr = new RegExp(e3.ATTRIBUTE, `i`), e3.attrsplit = new RegExp(e3.ATTRIBUTESPLIT, `i`);
      })(c2 = t2.PATTERNS ||= {}), t2.LiteParser = (function() {
        function e3() {
        }
        return e3.prototype.parseFromString = function(e4, t3, n3) {
          n3 === void 0 && (n3 = null);
          for (var r3 = n3.createDocument(), i3 = n3.body(r3), a3 = e4.replace(/<\?.*?\?>/g, ``).split(c2.tag); a3.length; ) {
            var o3 = a3.shift(), s3 = a3.shift();
            o3 && this.addText(n3, i3, o3), s3 && s3.charAt(s3.length - 1) === `>` && (s3.charAt(1) === `!` ? this.addComment(n3, i3, s3) : i3 = s3.charAt(1) === `/` ? this.closeTag(n3, i3, s3) : this.openTag(n3, i3, s3, a3));
          }
          return this.checkDocument(n3, r3), r3;
        }, e3.prototype.addText = function(e4, t3, n3) {
          return n3 = l2.translate(n3), e4.append(t3, e4.text(n3));
        }, e3.prototype.addComment = function(e4, t3, n3) {
          return e4.append(t3, new d2.LiteComment(n3));
        }, e3.prototype.closeTag = function(e4, t3, n3) {
          for (var r3 = n3.slice(2, n3.length - 1).toLowerCase(); e4.parent(t3) && e4.kind(t3) !== r3; ) t3 = e4.parent(t3);
          return e4.parent(t3);
        }, e3.prototype.openTag = function(e4, t3, n3, r3) {
          var i3 = this.constructor.PCDATA, a3 = this.constructor.SELF_CLOSING, o3 = n3.match(/<(.*?)[\s\n>\/]/)[1].toLowerCase(), s3 = e4.node(o3), l3 = n3.replace(/^<.*?[\s\n>]/, ``).split(c2.attrsplit);
          return (l3.pop().match(/>$/) || l3.length < 5) && (this.addAttributes(e4, s3, l3), e4.append(t3, s3), a3[o3] || n3.match(/\/>$/) || (i3[o3] ? this.handlePCDATA(e4, s3, o3, r3) : t3 = s3)), t3;
        }, e3.prototype.addAttributes = function(e4, t3, n3) {
          for (var r3 = this.constructor.CDATA_ATTR; n3.length; ) {
            var i3 = o2(n3.splice(0, 5), 5), a3 = i3[1], s3 = i3[2], c3 = i3[3], u3 = i3[4], d3 = s3 || c3 || u3 || ``;
            r3[a3] || (d3 = l2.translate(d3)), e4.setAttribute(t3, a3, d3);
          }
        }, e3.prototype.handlePCDATA = function(e4, t3, n3, r3) {
          for (var i3 = [], a3 = `</` + n3 + `>`, o3 = ``; r3.length && o3 !== a3; ) i3.push(o3), i3.push(r3.shift()), o3 = r3.shift();
          e4.append(t3, e4.text(i3.join(``)));
        }, e3.prototype.checkDocument = function(e4, t3) {
          var n3, r3, i3, a3, o3 = this.getOnlyChild(e4, e4.body(t3));
          if (o3) {
            try {
              for (var c3 = s2(e4.childNodes(e4.body(t3))), l3 = c3.next(); !l3.done && (p = l3.value) !== o3; l3 = c3.next()) p instanceof d2.LiteComment && p.value.match(/^<!DOCTYPE/) && (t3.type = p.value);
            } catch (e5) {
              n3 = { error: e5 };
            } finally {
              try {
                l3 && !l3.done && (r3 = c3.return) && r3.call(c3);
              } finally {
                if (n3) throw n3.error;
              }
            }
            switch (e4.kind(o3)) {
              case `html`:
                try {
                  for (var u3 = s2(o3.children), f = u3.next(); !f.done; f = u3.next()) {
                    var p = f.value;
                    switch (e4.kind(p)) {
                      case `head`:
                        t3.head = p;
                        break;
                      case `body`:
                        t3.body = p;
                    }
                  }
                } catch (e5) {
                  i3 = { error: e5 };
                } finally {
                  try {
                    f && !f.done && (a3 = u3.return) && a3.call(u3);
                  } finally {
                    if (i3) throw i3.error;
                  }
                }
                t3.root = o3, e4.remove(o3), e4.parent(t3.body) !== o3 && e4.append(o3, t3.body), e4.parent(t3.head) !== o3 && e4.insert(t3.head, t3.body);
                break;
              case `head`:
                t3.head = e4.replace(o3, t3.head);
                break;
              case `body`:
                t3.body = e4.replace(o3, t3.body);
            }
          }
        }, e3.prototype.getOnlyChild = function(e4, t3) {
          var n3, r3, i3 = null;
          try {
            for (var a3 = s2(e4.childNodes(t3)), o3 = a3.next(); !o3.done; o3 = a3.next()) {
              var c3 = o3.value;
              if (c3 instanceof u2.LiteElement) {
                if (i3) return null;
                i3 = c3;
              }
            }
          } catch (e5) {
            n3 = { error: e5 };
          } finally {
            try {
              o3 && !o3.done && (r3 = a3.return) && r3.call(a3);
            } finally {
              if (n3) throw n3.error;
            }
          }
          return i3;
        }, e3.prototype.serialize = function(e4, t3, n3) {
          var r3 = this;
          n3 === void 0 && (n3 = false);
          var i3 = this.constructor.SELF_CLOSING, a3 = this.constructor.CDATA_ATTR, o3 = e4.kind(t3), s3 = e4.allAttributes(t3).map((function(e5) {
            return e5.name + `="` + (a3[e5.name] ? e5.value : r3.protectAttribute(e5.value)) + `"`;
          })).join(` `), c3 = this.serializeInner(e4, t3, n3);
          return `<` + o3 + (s3 ? ` ` + s3 : ``) + (n3 && !c3 || i3[o3] ? n3 ? `/>` : `>` : `>${c3}</${o3}>`);
        }, e3.prototype.serializeInner = function(e4, t3, n3) {
          var r3 = this;
          return n3 === void 0 && (n3 = false), this.constructor.PCDATA.hasOwnProperty(t3.kind) ? e4.childNodes(t3).map((function(t4) {
            return e4.value(t4);
          })).join(``) : e4.childNodes(t3).map((function(t4) {
            var i3 = e4.kind(t4);
            return i3 === `#text` ? r3.protectHTML(e4.value(t4)) : i3 === `#comment` ? t4.value : r3.serialize(e4, t4, n3);
          })).join(``);
        }, e3.prototype.protectAttribute = function(e4) {
          return typeof e4 != `string` && (e4 = String(e4)), e4.replace(/"/g, `&quot;`);
        }, e3.prototype.protectHTML = function(e4) {
          return e4.replace(/&/g, `&amp;`).replace(/</g, `&lt;`).replace(/>/g, `&gt;`);
        }, e3.SELF_CLOSING = { area: true, base: true, br: true, col: true, command: true, embed: true, hr: true, img: true, input: true, keygen: true, link: true, menuitem: true, meta: true, param: true, source: true, track: true, wbr: true }, e3.PCDATA = { option: true, textarea: true, fieldset: true, title: true, style: true, script: true }, e3.CDATA_ATTR = { style: true, datafld: true, datasrc: true, href: true, src: true, longdesc: true, usemap: true, cite: true, datetime: true, action: true, axis: true, profile: true, content: true, scheme: true }, e3;
      })();
    }, 735: function(e2, t2) {
      var n2, r2 = this && this.__extends || (n2 = function(e3, t3) {
        return n2 = Object.setPrototypeOf || { __proto__: [] } instanceof Array && function(e4, t4) {
          e4.__proto__ = t4;
        } || function(e4, t4) {
          for (var n3 in t4) Object.prototype.hasOwnProperty.call(t4, n3) && (e4[n3] = t4[n3]);
        }, n2(e3, t3);
      }, function(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Class extends value ` + String(t3) + ` is not a constructor or null`);
        function r3() {
          this.constructor = e3;
        }
        n2(e3, t3), e3.prototype = t3 === null ? Object.create(t3) : (r3.prototype = t3.prototype, new r3());
      });
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.LiteComment = t2.LiteText = void 0;
      var i2 = (function() {
        function e3(e4) {
          e4 === void 0 && (e4 = ``), this.value = e4;
        }
        return Object.defineProperty(e3.prototype, `kind`, { get: function() {
          return `#text`;
        }, enumerable: false, configurable: true }), e3;
      })();
      t2.LiteText = i2, t2.LiteComment = (function(e3) {
        function t3() {
          return e3 !== null && e3.apply(this, arguments) || this;
        }
        return r2(t3, e3), Object.defineProperty(t3.prototype, `kind`, { get: function() {
          return `#comment`;
        }, enumerable: false, configurable: true }), t3;
      })(i2);
    }, 492: function(e2, t2, n2) {
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.LiteWindow = void 0;
      var r2 = n2(946), i2 = n2(877), a2 = n2(6), o2 = n2(246);
      t2.LiteWindow = function() {
        this.DOMParser = o2.LiteParser, this.NodeList = a2.LiteList, this.HTMLCollection = a2.LiteList, this.HTMLElement = r2.LiteElement, this.DocumentFragment = a2.LiteList, this.Document = i2.LiteDocument, this.document = new i2.LiteDocument();
      };
    }, 250: function(e2, t2, n2) {
      var r2, i2 = this && this.__extends || (r2 = function(e3, t3) {
        return r2 = Object.setPrototypeOf || { __proto__: [] } instanceof Array && function(e4, t4) {
          e4.__proto__ = t4;
        } || function(e4, t4) {
          for (var n3 in t4) Object.prototype.hasOwnProperty.call(t4, n3) && (e4[n3] = t4[n3]);
        }, r2(e3, t3);
      }, function(e3, t3) {
        if (typeof t3 != `function` && t3 !== null) throw TypeError(`Class extends value ` + String(t3) + ` is not a constructor or null`);
        function n3() {
          this.constructor = e3;
        }
        r2(e3, t3), e3.prototype = t3 === null ? Object.create(t3) : (n3.prototype = t3.prototype, new n3());
      }), a2 = this && this.__assign || function() {
        return a2 = Object.assign || function(e3) {
          for (var t3, n3 = 1, r3 = arguments.length; n3 < r3; n3++) for (var i3 in t3 = arguments[n3]) Object.prototype.hasOwnProperty.call(t3, i3) && (e3[i3] = t3[i3]);
          return e3;
        }, a2.apply(this, arguments);
      }, o2 = this && this.__values || function(e3) {
        var t3 = typeof Symbol == `function` && Symbol.iterator, n3 = t3 && e3[t3], r3 = 0;
        if (n3) return n3.call(e3);
        if (e3 && typeof e3.length == `number`) return { next: function() {
          return e3 && r3 >= e3.length && (e3 = void 0), { value: e3 && e3[r3++], done: !e3 };
        } };
        throw TypeError(t3 ? `Object is not iterable.` : `Symbol.iterator is not defined.`);
      }, s2 = this && this.__read || function(e3, t3) {
        var n3 = typeof Symbol == `function` && e3[Symbol.iterator];
        if (!n3) return e3;
        var r3, i3, a3 = n3.call(e3), o3 = [];
        try {
          for (; (t3 === void 0 || t3-- > 0) && !(r3 = a3.next()).done; ) o3.push(r3.value);
        } catch (e4) {
          i3 = { error: e4 };
        } finally {
          try {
            r3 && !r3.done && (n3 = a3.return) && n3.call(a3);
          } finally {
            if (i3) throw i3.error;
          }
        }
        return o3;
      }, c2 = this && this.__spreadArray || function(e3, t3, n3) {
        if (n3 || arguments.length === 2) for (var r3, i3 = 0, a3 = t3.length; i3 < a3; i3++) !r3 && i3 in t3 || (r3 ||= Array.prototype.slice.call(t3, 0, i3), r3[i3] = t3[i3]);
        return e3.concat(r3 || Array.prototype.slice.call(t3));
      };
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.liteAdaptor = t2.LiteAdaptor = t2.LiteBase = void 0;
      var l2 = n2(857), u2 = n2(244), d2 = n2(877), f = n2(946), p = n2(735), m = n2(492), h = n2(246), g = n2(878), _ = (function(e3) {
        function t3() {
          var t4 = e3.call(this) || this;
          return t4.parser = new h.LiteParser(), t4.window = new m.LiteWindow(), t4;
        }
        return i2(t3, e3), t3.prototype.parse = function(e4, t4) {
          return this.parser.parseFromString(e4, t4, this);
        }, t3.prototype.create = function(e4, t4) {
          return new f.LiteElement(e4);
        }, t3.prototype.text = function(e4) {
          return new p.LiteText(e4);
        }, t3.prototype.comment = function(e4) {
          return new p.LiteComment(e4);
        }, t3.prototype.createDocument = function() {
          return new d2.LiteDocument();
        }, t3.prototype.head = function(e4) {
          return e4.head;
        }, t3.prototype.body = function(e4) {
          return e4.body;
        }, t3.prototype.root = function(e4) {
          return e4.root;
        }, t3.prototype.doctype = function(e4) {
          return e4.type;
        }, t3.prototype.tags = function(e4, t4, n3) {
          n3 === void 0 && (n3 = null);
          var r3 = [], i3 = [];
          if (n3) return i3;
          for (var a3 = e4; a3; ) {
            var o3 = a3.kind;
            o3 !== `#text` && o3 !== `#comment` && (a3 = a3, o3 === t4 && i3.push(a3), a3.children.length && (r3 = a3.children.concat(r3))), a3 = r3.shift();
          }
          return i3;
        }, t3.prototype.elementById = function(e4, t4) {
          for (var n3 = [], r3 = e4; r3; ) {
            if (r3.kind !== `#text` && r3.kind !== `#comment`) {
              if ((r3 = r3).attributes.id === t4) return r3;
              r3.children.length && (n3 = r3.children.concat(n3));
            }
            r3 = n3.shift();
          }
          return null;
        }, t3.prototype.elementsByClass = function(e4, t4) {
          for (var n3 = [], r3 = [], i3 = e4; i3; ) i3.kind !== `#text` && i3.kind !== `#comment` && (((i3 = i3).attributes.class || ``).trim().split(/ +/).includes(t4) && r3.push(i3), i3.children.length && (n3 = i3.children.concat(n3))), i3 = n3.shift();
          return r3;
        }, t3.prototype.getElements = function(e4, t4) {
          var n3, r3, i3 = [], a3 = this.body(t4);
          try {
            for (var s3 = o2(e4), c3 = s3.next(); !c3.done; c3 = s3.next()) {
              var l3 = c3.value;
              if (typeof l3 == `string`) if (l3.charAt(0) === `#`) {
                var u3 = this.elementById(a3, l3.slice(1));
                u3 && i3.push(u3);
              } else l3.charAt(0) === `.` ? i3 = i3.concat(this.elementsByClass(a3, l3.slice(1))) : l3.match(/^[-a-z][-a-z0-9]*$/i) && (i3 = i3.concat(this.tags(a3, l3)));
              else Array.isArray(l3) ? i3 = i3.concat(l3) : l3 instanceof this.window.NodeList || l3 instanceof this.window.HTMLCollection ? i3 = i3.concat(l3.nodes) : i3.push(l3);
            }
          } catch (e5) {
            n3 = { error: e5 };
          } finally {
            try {
              c3 && !c3.done && (r3 = s3.return) && r3.call(s3);
            } finally {
              if (n3) throw n3.error;
            }
          }
          return i3;
        }, t3.prototype.contains = function(e4, t4) {
          for (; t4 && t4 !== e4; ) t4 = this.parent(t4);
          return !!t4;
        }, t3.prototype.parent = function(e4) {
          return e4.parent;
        }, t3.prototype.childIndex = function(e4) {
          return e4.parent ? e4.parent.children.findIndex((function(t4) {
            return t4 === e4;
          })) : -1;
        }, t3.prototype.append = function(e4, t4) {
          return t4.parent && this.remove(t4), e4.children.push(t4), t4.parent = e4, t4;
        }, t3.prototype.insert = function(e4, t4) {
          if (e4.parent && this.remove(e4), t4 && t4.parent) {
            var n3 = this.childIndex(t4);
            t4.parent.children.splice(n3, 0, e4), e4.parent = t4.parent;
          }
        }, t3.prototype.remove = function(e4) {
          var t4 = this.childIndex(e4);
          return t4 >= 0 && e4.parent.children.splice(t4, 1), e4.parent = null, e4;
        }, t3.prototype.replace = function(e4, t4) {
          var n3 = this.childIndex(t4);
          return n3 >= 0 && (t4.parent.children[n3] = e4, e4.parent = t4.parent, t4.parent = null), t4;
        }, t3.prototype.clone = function(e4) {
          var t4 = this, n3 = new f.LiteElement(e4.kind);
          return n3.attributes = a2({}, e4.attributes), n3.children = e4.children.map((function(e5) {
            if (e5.kind === `#text`) return new p.LiteText(e5.value);
            if (e5.kind === `#comment`) return new p.LiteComment(e5.value);
            var r3 = t4.clone(e5);
            return r3.parent = n3, r3;
          })), n3;
        }, t3.prototype.split = function(e4, t4) {
          var n3 = new p.LiteText(e4.value.slice(t4));
          return e4.value = e4.value.slice(0, t4), e4.parent.children.splice(this.childIndex(e4) + 1, 0, n3), n3.parent = e4.parent, n3;
        }, t3.prototype.next = function(e4) {
          var t4 = e4.parent;
          if (!t4) return null;
          var n3 = this.childIndex(e4) + 1;
          return n3 >= 0 && n3 < t4.children.length ? t4.children[n3] : null;
        }, t3.prototype.previous = function(e4) {
          var t4 = e4.parent;
          if (!t4) return null;
          var n3 = this.childIndex(e4) - 1;
          return n3 >= 0 ? t4.children[n3] : null;
        }, t3.prototype.firstChild = function(e4) {
          return e4.children[0];
        }, t3.prototype.lastChild = function(e4) {
          return e4.children[e4.children.length - 1];
        }, t3.prototype.childNodes = function(e4) {
          return c2([], s2(e4.children), false);
        }, t3.prototype.childNode = function(e4, t4) {
          return e4.children[t4];
        }, t3.prototype.kind = function(e4) {
          return e4.kind;
        }, t3.prototype.value = function(e4) {
          return e4.kind === `#text` ? e4.value : e4.kind === `#comment` ? e4.value.replace(/^<!(--)?((?:.|\n)*)\1>$/, `$2`) : ``;
        }, t3.prototype.textContent = function(e4) {
          var t4 = this;
          return e4.children.reduce((function(e5, n3) {
            return e5 + (n3.kind === `#text` ? n3.value : n3.kind === `#comment` ? `` : t4.textContent(n3));
          }), ``);
        }, t3.prototype.innerHTML = function(e4) {
          return this.parser.serializeInner(this, e4);
        }, t3.prototype.outerHTML = function(e4) {
          return this.parser.serialize(this, e4);
        }, t3.prototype.serializeXML = function(e4) {
          return this.parser.serialize(this, e4, true);
        }, t3.prototype.setAttribute = function(e4, t4, n3, r3) {
          r3 === void 0 && (r3 = null), typeof n3 != `string` && (n3 = String(n3)), r3 && (t4 = r3.replace(/.*\//, ``) + `:` + t4.replace(/^.*:/, ``)), e4.attributes[t4] = n3, t4 === `style` && (e4.styles = null);
        }, t3.prototype.getAttribute = function(e4, t4) {
          return e4.attributes[t4];
        }, t3.prototype.removeAttribute = function(e4, t4) {
          delete e4.attributes[t4];
        }, t3.prototype.hasAttribute = function(e4, t4) {
          return e4.attributes.hasOwnProperty(t4);
        }, t3.prototype.allAttributes = function(e4) {
          var t4, n3, r3 = e4.attributes, i3 = [];
          try {
            for (var a3 = o2(Object.keys(r3)), s3 = a3.next(); !s3.done; s3 = a3.next()) {
              var c3 = s3.value;
              i3.push({ name: c3, value: r3[c3] });
            }
          } catch (e5) {
            t4 = { error: e5 };
          } finally {
            try {
              s3 && !s3.done && (n3 = a3.return) && n3.call(a3);
            } finally {
              if (t4) throw t4.error;
            }
          }
          return i3;
        }, t3.prototype.addClass = function(e4, t4) {
          var n3 = (e4.attributes.class || ``).split(/ /);
          n3.find((function(e5) {
            return e5 === t4;
          })) || (n3.push(t4), e4.attributes.class = n3.join(` `));
        }, t3.prototype.removeClass = function(e4, t4) {
          var n3 = (e4.attributes.class || ``).split(/ /), r3 = n3.findIndex((function(e5) {
            return e5 === t4;
          }));
          r3 >= 0 && (n3.splice(r3, 1), e4.attributes.class = n3.join(` `));
        }, t3.prototype.hasClass = function(e4, t4) {
          return !!(e4.attributes.class || ``).split(/ /).find((function(e5) {
            return e5 === t4;
          }));
        }, t3.prototype.setStyle = function(e4, t4, n3) {
          e4.styles ||= new g.Styles(this.getAttribute(e4, `style`)), e4.styles.set(t4, n3), e4.attributes.style = e4.styles.cssText;
        }, t3.prototype.getStyle = function(e4, t4) {
          if (!e4.styles) {
            var n3 = this.getAttribute(e4, `style`);
            if (!n3) return ``;
            e4.styles = new g.Styles(n3);
          }
          return e4.styles.get(t4);
        }, t3.prototype.allStyles = function(e4) {
          return this.getAttribute(e4, `style`);
        }, t3.prototype.insertRules = function(e4, t4) {
          e4.children = [this.text(t4.join(`

`) + `

` + this.textContent(e4))];
        }, t3.prototype.fontSize = function(e4) {
          return 0;
        }, t3.prototype.fontFamily = function(e4) {
          return ``;
        }, t3.prototype.nodeSize = function(e4, t4, n3) {
          return [0, 0];
        }, t3.prototype.nodeBBox = function(e4) {
          return { left: 0, right: 0, top: 0, bottom: 0 };
        }, t3;
      })(l2.AbstractDOMAdaptor);
      t2.LiteBase = _;
      var v = (function(e3) {
        function t3() {
          return e3 !== null && e3.apply(this, arguments) || this;
        }
        return i2(t3, e3), t3;
      })((0, u2.NodeMixin)(_));
      t2.LiteAdaptor = v, t2.liteAdaptor = function(e3) {
        return e3 === void 0 && (e3 = null), new v(null, e3);
      };
    }, 306: function(e2, t2) {
      t2.q = void 0, t2.q = `3.2.2`;
    }, 723: function(e2, t2) {
      MathJax._.components.global.isObject, MathJax._.components.global.combineConfig, MathJax._.components.global.combineDefaults, t2.r8 = MathJax._.components.global.combineWithMathJax, MathJax._.components.global.MathJax;
    }, 857: function(e2, t2) {
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.AbstractDOMAdaptor = MathJax._.core.DOMAdaptor.AbstractDOMAdaptor;
    }, 29: function(e2, t2) {
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.options = MathJax._.util.Entities.options, t2.entities = MathJax._.util.Entities.entities, t2.add = MathJax._.util.Entities.add, t2.remove = MathJax._.util.Entities.remove, t2.translate = MathJax._.util.Entities.translate, t2.numeric = MathJax._.util.Entities.numeric;
    }, 77: function(e2, t2) {
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.isObject = MathJax._.util.Options.isObject, t2.APPEND = MathJax._.util.Options.APPEND, t2.REMOVE = MathJax._.util.Options.REMOVE, t2.OPTIONS = MathJax._.util.Options.OPTIONS, t2.Expandable = MathJax._.util.Options.Expandable, t2.expandable = MathJax._.util.Options.expandable, t2.makeArray = MathJax._.util.Options.makeArray, t2.keys = MathJax._.util.Options.keys, t2.copy = MathJax._.util.Options.copy, t2.insert = MathJax._.util.Options.insert, t2.defaultOptions = MathJax._.util.Options.defaultOptions, t2.userOptions = MathJax._.util.Options.userOptions, t2.selectOptions = MathJax._.util.Options.selectOptions, t2.selectOptionsFromKeys = MathJax._.util.Options.selectOptionsFromKeys, t2.separateOptions = MathJax._.util.Options.separateOptions, t2.lookup = MathJax._.util.Options.lookup;
    }, 878: function(e2, t2) {
      Object.defineProperty(t2, `__esModule`, { value: true }), t2.Styles = MathJax._.util.Styles.Styles;
    } }, u = {};
    function d(e2) {
      var t2 = u[e2];
      if (t2 !== void 0) return t2.exports;
      var n2 = u[e2] = { exports: {} };
      return l[e2].call(n2.exports, n2, n2.exports, d), n2.exports;
    }
    e = d(723), t = d(306), n = d(250), r = d(877), i = d(946), a = d(6), o = d(246), s = d(735), c = d(492), MathJax.loader && MathJax.loader.checkVersion(`adaptors/liteDOM`, t.q, `adaptors`), (0, e.r8)({ _: { adaptors: { liteAdaptor: n, lite: { Document: r, Element: i, List: a, Parser: o, Text: s, Window: c } } } }), MathJax.startup && (MathJax.startup.registerConstructor(`liteAdaptor`, n.liteAdaptor), MathJax.startup.useAdaptor(`liteAdaptor`, true));
  })();
  return liteDOMCp0aN3bP$2;
}
var liteDOMCp0aN3bPExports = requireLiteDOMCp0aN3bP();
const liteDOMCp0aN3bP = /* @__PURE__ */ getDefaultExportFromCjs(liteDOMCp0aN3bPExports);
const liteDOMCp0aN3bP$1 = /* @__PURE__ */ _mergeNamespaces({
  __proto__: null,
  default: liteDOMCp0aN3bP
}, [liteDOMCp0aN3bPExports]);
export {
  liteDOMCp0aN3bP$1 as l
};
//# sourceMappingURL=liteDOM-Cp0aN3bP.js.map
