//#region ../../node_modules/.pnpm/mathxyjax3@0.8.3/node_modules/mathxyjax3/dist/liteDOM-Cp0aN3bP.js
(function() {
	var e, t, n, r, i, a, o, s, c, l = {
		244: function(e, t, n) {
			var r, i = this && this.__extends || (r = function(e, t) {
				return r = Object.setPrototypeOf || { __proto__: [] } instanceof Array && function(e, t) {
					e.__proto__ = t;
				} || function(e, t) {
					for (var n in t) Object.prototype.hasOwnProperty.call(t, n) && (e[n] = t[n]);
				}, r(e, t);
			}, function(e, t) {
				if (typeof t != `function` && t !== null) throw TypeError(`Class extends value ` + String(t) + ` is not a constructor or null`);
				function n() {
					this.constructor = e;
				}
				r(e, t), e.prototype = t === null ? Object.create(t) : (n.prototype = t.prototype, new n());
			}), a = this && this.__assign || function() {
				return a = Object.assign || function(e) {
					for (var t, n = 1, r = arguments.length; n < r; n++) for (var i in t = arguments[n]) Object.prototype.hasOwnProperty.call(t, i) && (e[i] = t[i]);
					return e;
				}, a.apply(this, arguments);
			};
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.NodeMixin = t.NodeMixinOptions = void 0;
			var o = n(77);
			t.NodeMixinOptions = {
				badCSS: !0,
				badSizes: !0
			}, t.NodeMixin = function(e, n) {
				var r;
				return n === void 0 && (n = {}), n = (0, o.userOptions)((0, o.defaultOptions)({}, t.NodeMixinOptions), n), r = function(e) {
					function t() {
						var t = [...arguments], n = e.call(this, t[0]) || this, r = n.constructor;
						return n.options = (0, o.userOptions)((0, o.defaultOptions)({}, r.OPTIONS), t[1]), n;
					}
					return i(t, e), t.prototype.fontSize = function(t) {
						return n.badCSS ? this.options.fontSize : e.prototype.fontSize.call(this, t);
					}, t.prototype.fontFamily = function(t) {
						return n.badCSS ? this.options.fontFamily : e.prototype.fontFamily.call(this, t);
					}, t.prototype.nodeSize = function(r, i, a) {
						if (i === void 0 && (i = 1), a === void 0 && (a = null), !n.badSizes) return e.prototype.nodeSize.call(this, r, i, a);
						var o = this.textContent(r), s = Array.from(o.replace(t.cjkPattern, ``)).length;
						return [(Array.from(o).length - s) * this.options.cjkCharWidth + s * this.options.unknownCharWidth, this.options.unknownCharHeight];
					}, t.prototype.nodeBBox = function(t) {
						return n.badSizes ? {
							left: 0,
							right: 0,
							top: 0,
							bottom: 0
						} : e.prototype.nodeBBox.call(this, t);
					}, t;
				}(e), r.OPTIONS = a(a({}, n.badCSS ? {
					fontSize: 16,
					fontFamily: `Times`
				} : {}), n.badSizes ? {
					cjkCharWidth: 1,
					unknownCharWidth: .6,
					unknownCharHeight: .8
				} : {}), r.cjkPattern = new RegExp([
					`[`,
					`ᄀ-ᅟ`,
					`〈〉`,
					`⺀-〾`,
					`぀-㉇`,
					`㉐-䶿`,
					`一-꓆`,
					`ꥠ-ꥼ`,
					`가-힣`,
					`豈-﫿`,
					`︐-︙`,
					`︰-﹫`,
					`！-｠￠-￦`,
					`𛀀-𛀁`,
					`🈀-🉑`,
					`𠀀-𿿽`,
					`]`
				].join(``), `gu`), r;
			};
		},
		877: function(e, t, n) {
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.LiteDocument = void 0;
			var r = n(946);
			t.LiteDocument = function() {
				function e() {
					this.root = new r.LiteElement(`html`, {}, [this.head = new r.LiteElement(`head`), this.body = new r.LiteElement(`body`)]), this.type = ``;
				}
				return Object.defineProperty(e.prototype, `kind`, {
					get: function() {
						return `#document`;
					},
					enumerable: !1,
					configurable: !0
				}), e;
			}();
		},
		946: function(e, t) {
			var n = this && this.__assign || function() {
				return n = Object.assign || function(e) {
					for (var t, n = 1, r = arguments.length; n < r; n++) for (var i in t = arguments[n]) Object.prototype.hasOwnProperty.call(t, i) && (e[i] = t[i]);
					return e;
				}, n.apply(this, arguments);
			}, r = this && this.__read || function(e, t) {
				var n = typeof Symbol == `function` && e[Symbol.iterator];
				if (!n) return e;
				var r, i, a = n.call(e), o = [];
				try {
					for (; (t === void 0 || t-- > 0) && !(r = a.next()).done;) o.push(r.value);
				} catch (e) {
					i = { error: e };
				} finally {
					try {
						r && !r.done && (n = a.return) && n.call(a);
					} finally {
						if (i) throw i.error;
					}
				}
				return o;
			}, i = this && this.__spreadArray || function(e, t, n) {
				if (n || arguments.length === 2) for (var r, i = 0, a = t.length; i < a; i++) !r && i in t || (r ||= Array.prototype.slice.call(t, 0, i), r[i] = t[i]);
				return e.concat(r || Array.prototype.slice.call(t));
			}, a = this && this.__values || function(e) {
				var t = typeof Symbol == `function` && Symbol.iterator, n = t && e[t], r = 0;
				if (n) return n.call(e);
				if (e && typeof e.length == `number`) return { next: function() {
					return e && r >= e.length && (e = void 0), {
						value: e && e[r++],
						done: !e
					};
				} };
				throw TypeError(t ? `Object is not iterable.` : `Symbol.iterator is not defined.`);
			};
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.LiteElement = void 0, t.LiteElement = function(e, t, o) {
				var s, c;
				t === void 0 && (t = {}), o === void 0 && (o = []), this.kind = e, this.attributes = n({}, t), this.children = i([], r(o), !1);
				try {
					for (var l = a(this.children), u = l.next(); !u.done; u = l.next()) u.value.parent = this;
				} catch (e) {
					s = { error: e };
				} finally {
					try {
						u && !u.done && (c = l.return) && c.call(l);
					} finally {
						if (s) throw s.error;
					}
				}
				this.styles = null;
			};
		},
		6: function(e, t) {
			var n = this && this.__read || function(e, t) {
				var n = typeof Symbol == `function` && e[Symbol.iterator];
				if (!n) return e;
				var r, i, a = n.call(e), o = [];
				try {
					for (; (t === void 0 || t-- > 0) && !(r = a.next()).done;) o.push(r.value);
				} catch (e) {
					i = { error: e };
				} finally {
					try {
						r && !r.done && (n = a.return) && n.call(a);
					} finally {
						if (i) throw i.error;
					}
				}
				return o;
			}, r = this && this.__spreadArray || function(e, t, n) {
				if (n || arguments.length === 2) for (var r, i = 0, a = t.length; i < a; i++) !r && i in t || (r ||= Array.prototype.slice.call(t, 0, i), r[i] = t[i]);
				return e.concat(r || Array.prototype.slice.call(t));
			};
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.LiteList = void 0, t.LiteList = function() {
				function e(e) {
					this.nodes = [], this.nodes = r([], n(e), !1);
				}
				return e.prototype.append = function(e) {
					this.nodes.push(e);
				}, e.prototype[Symbol.iterator] = function() {
					var e = 0;
					return { next: function() {
						return e === this.nodes.length ? {
							value: null,
							done: !0
						} : {
							value: this.nodes[e++],
							done: !1
						};
					} };
				}, e;
			}();
		},
		246: function(e, t, n) {
			var r = this && this.__createBinding || (Object.create ? function(e, t, n, r) {
				r === void 0 && (r = n);
				var i = Object.getOwnPropertyDescriptor(t, n);
				i && !(`get` in i ? !t.__esModule : i.writable || i.configurable) || (i = {
					enumerable: !0,
					get: function() {
						return t[n];
					}
				}), Object.defineProperty(e, r, i);
			} : function(e, t, n, r) {
				r === void 0 && (r = n), e[r] = t[n];
			}), i = this && this.__setModuleDefault || (Object.create ? function(e, t) {
				Object.defineProperty(e, `default`, {
					enumerable: !0,
					value: t
				});
			} : function(e, t) {
				e.default = t;
			}), a = this && this.__importStar || function(e) {
				if (e && e.__esModule) return e;
				var t = {};
				if (e != null) for (var n in e) n !== `default` && Object.prototype.hasOwnProperty.call(e, n) && r(t, e, n);
				return i(t, e), t;
			}, o = this && this.__read || function(e, t) {
				var n = typeof Symbol == `function` && e[Symbol.iterator];
				if (!n) return e;
				var r, i, a = n.call(e), o = [];
				try {
					for (; (t === void 0 || t-- > 0) && !(r = a.next()).done;) o.push(r.value);
				} catch (e) {
					i = { error: e };
				} finally {
					try {
						r && !r.done && (n = a.return) && n.call(a);
					} finally {
						if (i) throw i.error;
					}
				}
				return o;
			}, s = this && this.__values || function(e) {
				var t = typeof Symbol == `function` && Symbol.iterator, n = t && e[t], r = 0;
				if (n) return n.call(e);
				if (e && typeof e.length == `number`) return { next: function() {
					return e && r >= e.length && (e = void 0), {
						value: e && e[r++],
						done: !e
					};
				} };
				throw TypeError(t ? `Object is not iterable.` : `Symbol.iterator is not defined.`);
			};
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.LiteParser = t.PATTERNS = void 0;
			var c, l = a(n(29)), u = n(946), d = n(735);
			(function(e) {
				e.TAGNAME = `[a-z][^\\s\\n>]*`, e.ATTNAME = `[a-z][^\\s\\n>=]*`, e.VALUE = `(?:'[^']*'|"[^"]*"|[^\\s\\n]+)`, e.VALUESPLIT = `(?:'([^']*)'|"([^"]*)"|([^\\s\\n]+))`, e.SPACE = `(?:\\s|\\n)+`, e.OPTIONALSPACE = `(?:\\s|\\n)*`, e.ATTRIBUTE = e.ATTNAME + `(?:` + e.OPTIONALSPACE + `=` + e.OPTIONALSPACE + e.VALUE + `)?`, e.ATTRIBUTESPLIT = `(` + e.ATTNAME + `)(?:` + e.OPTIONALSPACE + `=` + e.OPTIONALSPACE + e.VALUESPLIT + `)?`, e.TAG = `(<(?:` + e.TAGNAME + `(?:` + e.SPACE + e.ATTRIBUTE + `)*` + e.OPTIONALSPACE + `/?|/` + e.TAGNAME + `|!--[^]*?--|![^]*?)(?:>|$))`, e.tag = new RegExp(e.TAG, `i`), e.attr = new RegExp(e.ATTRIBUTE, `i`), e.attrsplit = new RegExp(e.ATTRIBUTESPLIT, `i`);
			})(c = t.PATTERNS ||= {}), t.LiteParser = function() {
				function e() {}
				return e.prototype.parseFromString = function(e, t, n) {
					t === void 0 && (t = `text/html`), n === void 0 && (n = null);
					for (var r = n.createDocument(), i = n.body(r), a = e.replace(/<\?.*?\?>/g, ``).split(c.tag); a.length;) {
						var o = a.shift(), s = a.shift();
						o && this.addText(n, i, o), s && s.charAt(s.length - 1) === `>` && (s.charAt(1) === `!` ? this.addComment(n, i, s) : i = s.charAt(1) === `/` ? this.closeTag(n, i, s) : this.openTag(n, i, s, a));
					}
					return this.checkDocument(n, r), r;
				}, e.prototype.addText = function(e, t, n) {
					return n = l.translate(n), e.append(t, e.text(n));
				}, e.prototype.addComment = function(e, t, n) {
					return e.append(t, new d.LiteComment(n));
				}, e.prototype.closeTag = function(e, t, n) {
					for (var r = n.slice(2, n.length - 1).toLowerCase(); e.parent(t) && e.kind(t) !== r;) t = e.parent(t);
					return e.parent(t);
				}, e.prototype.openTag = function(e, t, n, r) {
					var i = this.constructor.PCDATA, a = this.constructor.SELF_CLOSING, o = n.match(/<(.*?)[\s\n>\/]/)[1].toLowerCase(), s = e.node(o), l = n.replace(/^<.*?[\s\n>]/, ``).split(c.attrsplit);
					return (l.pop().match(/>$/) || l.length < 5) && (this.addAttributes(e, s, l), e.append(t, s), a[o] || n.match(/\/>$/) || (i[o] ? this.handlePCDATA(e, s, o, r) : t = s)), t;
				}, e.prototype.addAttributes = function(e, t, n) {
					for (var r = this.constructor.CDATA_ATTR; n.length;) {
						var i = o(n.splice(0, 5), 5), a = i[1], s = i[2], c = i[3], u = i[4], d = s || c || u || ``;
						r[a] || (d = l.translate(d)), e.setAttribute(t, a, d);
					}
				}, e.prototype.handlePCDATA = function(e, t, n, r) {
					for (var i = [], a = `</` + n + `>`, o = ``; r.length && o !== a;) i.push(o), i.push(r.shift()), o = r.shift();
					e.append(t, e.text(i.join(``)));
				}, e.prototype.checkDocument = function(e, t) {
					var n, r, i, a, o = this.getOnlyChild(e, e.body(t));
					if (o) {
						try {
							for (var c = s(e.childNodes(e.body(t))), l = c.next(); !l.done && (p = l.value) !== o; l = c.next()) p instanceof d.LiteComment && p.value.match(/^<!DOCTYPE/) && (t.type = p.value);
						} catch (e) {
							n = { error: e };
						} finally {
							try {
								l && !l.done && (r = c.return) && r.call(c);
							} finally {
								if (n) throw n.error;
							}
						}
						switch (e.kind(o)) {
							case `html`:
								try {
									for (var u = s(o.children), f = u.next(); !f.done; f = u.next()) {
										var p = f.value;
										switch (e.kind(p)) {
											case `head`:
												t.head = p;
												break;
											case `body`: t.body = p;
										}
									}
								} catch (e) {
									i = { error: e };
								} finally {
									try {
										f && !f.done && (a = u.return) && a.call(u);
									} finally {
										if (i) throw i.error;
									}
								}
								t.root = o, e.remove(o), e.parent(t.body) !== o && e.append(o, t.body), e.parent(t.head) !== o && e.insert(t.head, t.body);
								break;
							case `head`:
								t.head = e.replace(o, t.head);
								break;
							case `body`: t.body = e.replace(o, t.body);
						}
					}
				}, e.prototype.getOnlyChild = function(e, t) {
					var n, r, i = null;
					try {
						for (var a = s(e.childNodes(t)), o = a.next(); !o.done; o = a.next()) {
							var c = o.value;
							if (c instanceof u.LiteElement) {
								if (i) return null;
								i = c;
							}
						}
					} catch (e) {
						n = { error: e };
					} finally {
						try {
							o && !o.done && (r = a.return) && r.call(a);
						} finally {
							if (n) throw n.error;
						}
					}
					return i;
				}, e.prototype.serialize = function(e, t, n) {
					var r = this;
					n === void 0 && (n = !1);
					var i = this.constructor.SELF_CLOSING, a = this.constructor.CDATA_ATTR, o = e.kind(t), s = e.allAttributes(t).map((function(e) {
						return e.name + `="` + (a[e.name] ? e.value : r.protectAttribute(e.value)) + `"`;
					})).join(` `), c = this.serializeInner(e, t, n);
					return `<` + o + (s ? ` ` + s : ``) + (n && !c || i[o] ? n ? `/>` : `>` : `>${c}</${o}>`);
				}, e.prototype.serializeInner = function(e, t, n) {
					var r = this;
					return n === void 0 && (n = !1), this.constructor.PCDATA.hasOwnProperty(t.kind) ? e.childNodes(t).map((function(t) {
						return e.value(t);
					})).join(``) : e.childNodes(t).map((function(t) {
						var i = e.kind(t);
						return i === `#text` ? r.protectHTML(e.value(t)) : i === `#comment` ? t.value : r.serialize(e, t, n);
					})).join(``);
				}, e.prototype.protectAttribute = function(e) {
					return typeof e != `string` && (e = String(e)), e.replace(/"/g, `&quot;`);
				}, e.prototype.protectHTML = function(e) {
					return e.replace(/&/g, `&amp;`).replace(/</g, `&lt;`).replace(/>/g, `&gt;`);
				}, e.SELF_CLOSING = {
					area: !0,
					base: !0,
					br: !0,
					col: !0,
					command: !0,
					embed: !0,
					hr: !0,
					img: !0,
					input: !0,
					keygen: !0,
					link: !0,
					menuitem: !0,
					meta: !0,
					param: !0,
					source: !0,
					track: !0,
					wbr: !0
				}, e.PCDATA = {
					option: !0,
					textarea: !0,
					fieldset: !0,
					title: !0,
					style: !0,
					script: !0
				}, e.CDATA_ATTR = {
					style: !0,
					datafld: !0,
					datasrc: !0,
					href: !0,
					src: !0,
					longdesc: !0,
					usemap: !0,
					cite: !0,
					datetime: !0,
					action: !0,
					axis: !0,
					profile: !0,
					content: !0,
					scheme: !0
				}, e;
			}();
		},
		735: function(e, t) {
			var n, r = this && this.__extends || (n = function(e, t) {
				return n = Object.setPrototypeOf || { __proto__: [] } instanceof Array && function(e, t) {
					e.__proto__ = t;
				} || function(e, t) {
					for (var n in t) Object.prototype.hasOwnProperty.call(t, n) && (e[n] = t[n]);
				}, n(e, t);
			}, function(e, t) {
				if (typeof t != `function` && t !== null) throw TypeError(`Class extends value ` + String(t) + ` is not a constructor or null`);
				function r() {
					this.constructor = e;
				}
				n(e, t), e.prototype = t === null ? Object.create(t) : (r.prototype = t.prototype, new r());
			});
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.LiteComment = t.LiteText = void 0;
			var i = function() {
				function e(e) {
					e === void 0 && (e = ``), this.value = e;
				}
				return Object.defineProperty(e.prototype, `kind`, {
					get: function() {
						return `#text`;
					},
					enumerable: !1,
					configurable: !0
				}), e;
			}();
			t.LiteText = i, t.LiteComment = function(e) {
				function t() {
					return e !== null && e.apply(this, arguments) || this;
				}
				return r(t, e), Object.defineProperty(t.prototype, `kind`, {
					get: function() {
						return `#comment`;
					},
					enumerable: !1,
					configurable: !0
				}), t;
			}(i);
		},
		492: function(e, t, n) {
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.LiteWindow = void 0;
			var r = n(946), i = n(877), a = n(6), o = n(246);
			t.LiteWindow = function() {
				this.DOMParser = o.LiteParser, this.NodeList = a.LiteList, this.HTMLCollection = a.LiteList, this.HTMLElement = r.LiteElement, this.DocumentFragment = a.LiteList, this.Document = i.LiteDocument, this.document = new i.LiteDocument();
			};
		},
		250: function(e, t, n) {
			var r, i = this && this.__extends || (r = function(e, t) {
				return r = Object.setPrototypeOf || { __proto__: [] } instanceof Array && function(e, t) {
					e.__proto__ = t;
				} || function(e, t) {
					for (var n in t) Object.prototype.hasOwnProperty.call(t, n) && (e[n] = t[n]);
				}, r(e, t);
			}, function(e, t) {
				if (typeof t != `function` && t !== null) throw TypeError(`Class extends value ` + String(t) + ` is not a constructor or null`);
				function n() {
					this.constructor = e;
				}
				r(e, t), e.prototype = t === null ? Object.create(t) : (n.prototype = t.prototype, new n());
			}), a = this && this.__assign || function() {
				return a = Object.assign || function(e) {
					for (var t, n = 1, r = arguments.length; n < r; n++) for (var i in t = arguments[n]) Object.prototype.hasOwnProperty.call(t, i) && (e[i] = t[i]);
					return e;
				}, a.apply(this, arguments);
			}, o = this && this.__values || function(e) {
				var t = typeof Symbol == `function` && Symbol.iterator, n = t && e[t], r = 0;
				if (n) return n.call(e);
				if (e && typeof e.length == `number`) return { next: function() {
					return e && r >= e.length && (e = void 0), {
						value: e && e[r++],
						done: !e
					};
				} };
				throw TypeError(t ? `Object is not iterable.` : `Symbol.iterator is not defined.`);
			}, s = this && this.__read || function(e, t) {
				var n = typeof Symbol == `function` && e[Symbol.iterator];
				if (!n) return e;
				var r, i, a = n.call(e), o = [];
				try {
					for (; (t === void 0 || t-- > 0) && !(r = a.next()).done;) o.push(r.value);
				} catch (e) {
					i = { error: e };
				} finally {
					try {
						r && !r.done && (n = a.return) && n.call(a);
					} finally {
						if (i) throw i.error;
					}
				}
				return o;
			}, c = this && this.__spreadArray || function(e, t, n) {
				if (n || arguments.length === 2) for (var r, i = 0, a = t.length; i < a; i++) !r && i in t || (r ||= Array.prototype.slice.call(t, 0, i), r[i] = t[i]);
				return e.concat(r || Array.prototype.slice.call(t));
			};
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.liteAdaptor = t.LiteAdaptor = t.LiteBase = void 0;
			var l = n(857), u = n(244), d = n(877), f = n(946), p = n(735), m = n(492), h = n(246), g = n(878), _ = function(e) {
				function t() {
					var t = e.call(this) || this;
					return t.parser = new h.LiteParser(), t.window = new m.LiteWindow(), t;
				}
				return i(t, e), t.prototype.parse = function(e, t) {
					return this.parser.parseFromString(e, t, this);
				}, t.prototype.create = function(e, t) {
					return t === void 0 && (t = null), new f.LiteElement(e);
				}, t.prototype.text = function(e) {
					return new p.LiteText(e);
				}, t.prototype.comment = function(e) {
					return new p.LiteComment(e);
				}, t.prototype.createDocument = function() {
					return new d.LiteDocument();
				}, t.prototype.head = function(e) {
					return e.head;
				}, t.prototype.body = function(e) {
					return e.body;
				}, t.prototype.root = function(e) {
					return e.root;
				}, t.prototype.doctype = function(e) {
					return e.type;
				}, t.prototype.tags = function(e, t, n) {
					n === void 0 && (n = null);
					var r = [], i = [];
					if (n) return i;
					for (var a = e; a;) {
						var o = a.kind;
						o !== `#text` && o !== `#comment` && (a = a, o === t && i.push(a), a.children.length && (r = a.children.concat(r))), a = r.shift();
					}
					return i;
				}, t.prototype.elementById = function(e, t) {
					for (var n = [], r = e; r;) {
						if (r.kind !== `#text` && r.kind !== `#comment`) {
							if ((r = r).attributes.id === t) return r;
							r.children.length && (n = r.children.concat(n));
						}
						r = n.shift();
					}
					return null;
				}, t.prototype.elementsByClass = function(e, t) {
					for (var n = [], r = [], i = e; i;) i.kind !== `#text` && i.kind !== `#comment` && (((i = i).attributes.class || ``).trim().split(/ +/).includes(t) && r.push(i), i.children.length && (n = i.children.concat(n))), i = n.shift();
					return r;
				}, t.prototype.getElements = function(e, t) {
					var n, r, i = [], a = this.body(t);
					try {
						for (var s = o(e), c = s.next(); !c.done; c = s.next()) {
							var l = c.value;
							if (typeof l == `string`) if (l.charAt(0) === `#`) {
								var u = this.elementById(a, l.slice(1));
								u && i.push(u);
							} else l.charAt(0) === `.` ? i = i.concat(this.elementsByClass(a, l.slice(1))) : l.match(/^[-a-z][-a-z0-9]*$/i) && (i = i.concat(this.tags(a, l)));
							else Array.isArray(l) ? i = i.concat(l) : l instanceof this.window.NodeList || l instanceof this.window.HTMLCollection ? i = i.concat(l.nodes) : i.push(l);
						}
					} catch (e) {
						n = { error: e };
					} finally {
						try {
							c && !c.done && (r = s.return) && r.call(s);
						} finally {
							if (n) throw n.error;
						}
					}
					return i;
				}, t.prototype.contains = function(e, t) {
					for (; t && t !== e;) t = this.parent(t);
					return !!t;
				}, t.prototype.parent = function(e) {
					return e.parent;
				}, t.prototype.childIndex = function(e) {
					return e.parent ? e.parent.children.findIndex((function(t) {
						return t === e;
					})) : -1;
				}, t.prototype.append = function(e, t) {
					return t.parent && this.remove(t), e.children.push(t), t.parent = e, t;
				}, t.prototype.insert = function(e, t) {
					if (e.parent && this.remove(e), t && t.parent) {
						var n = this.childIndex(t);
						t.parent.children.splice(n, 0, e), e.parent = t.parent;
					}
				}, t.prototype.remove = function(e) {
					var t = this.childIndex(e);
					return t >= 0 && e.parent.children.splice(t, 1), e.parent = null, e;
				}, t.prototype.replace = function(e, t) {
					var n = this.childIndex(t);
					return n >= 0 && (t.parent.children[n] = e, e.parent = t.parent, t.parent = null), t;
				}, t.prototype.clone = function(e) {
					var t = this, n = new f.LiteElement(e.kind);
					return n.attributes = a({}, e.attributes), n.children = e.children.map((function(e) {
						if (e.kind === `#text`) return new p.LiteText(e.value);
						if (e.kind === `#comment`) return new p.LiteComment(e.value);
						var r = t.clone(e);
						return r.parent = n, r;
					})), n;
				}, t.prototype.split = function(e, t) {
					var n = new p.LiteText(e.value.slice(t));
					return e.value = e.value.slice(0, t), e.parent.children.splice(this.childIndex(e) + 1, 0, n), n.parent = e.parent, n;
				}, t.prototype.next = function(e) {
					var t = e.parent;
					if (!t) return null;
					var n = this.childIndex(e) + 1;
					return n >= 0 && n < t.children.length ? t.children[n] : null;
				}, t.prototype.previous = function(e) {
					var t = e.parent;
					if (!t) return null;
					var n = this.childIndex(e) - 1;
					return n >= 0 ? t.children[n] : null;
				}, t.prototype.firstChild = function(e) {
					return e.children[0];
				}, t.prototype.lastChild = function(e) {
					return e.children[e.children.length - 1];
				}, t.prototype.childNodes = function(e) {
					return c([], s(e.children), !1);
				}, t.prototype.childNode = function(e, t) {
					return e.children[t];
				}, t.prototype.kind = function(e) {
					return e.kind;
				}, t.prototype.value = function(e) {
					return e.kind === `#text` ? e.value : e.kind === `#comment` ? e.value.replace(/^<!(--)?((?:.|\n)*)\1>$/, `$2`) : ``;
				}, t.prototype.textContent = function(e) {
					var t = this;
					return e.children.reduce((function(e, n) {
						return e + (n.kind === `#text` ? n.value : n.kind === `#comment` ? `` : t.textContent(n));
					}), ``);
				}, t.prototype.innerHTML = function(e) {
					return this.parser.serializeInner(this, e);
				}, t.prototype.outerHTML = function(e) {
					return this.parser.serialize(this, e);
				}, t.prototype.serializeXML = function(e) {
					return this.parser.serialize(this, e, !0);
				}, t.prototype.setAttribute = function(e, t, n, r) {
					r === void 0 && (r = null), typeof n != `string` && (n = String(n)), r && (t = r.replace(/.*\//, ``) + `:` + t.replace(/^.*:/, ``)), e.attributes[t] = n, t === `style` && (e.styles = null);
				}, t.prototype.getAttribute = function(e, t) {
					return e.attributes[t];
				}, t.prototype.removeAttribute = function(e, t) {
					delete e.attributes[t];
				}, t.prototype.hasAttribute = function(e, t) {
					return e.attributes.hasOwnProperty(t);
				}, t.prototype.allAttributes = function(e) {
					var t, n, r = e.attributes, i = [];
					try {
						for (var a = o(Object.keys(r)), s = a.next(); !s.done; s = a.next()) {
							var c = s.value;
							i.push({
								name: c,
								value: r[c]
							});
						}
					} catch (e) {
						t = { error: e };
					} finally {
						try {
							s && !s.done && (n = a.return) && n.call(a);
						} finally {
							if (t) throw t.error;
						}
					}
					return i;
				}, t.prototype.addClass = function(e, t) {
					var n = (e.attributes.class || ``).split(/ /);
					n.find((function(e) {
						return e === t;
					})) || (n.push(t), e.attributes.class = n.join(` `));
				}, t.prototype.removeClass = function(e, t) {
					var n = (e.attributes.class || ``).split(/ /), r = n.findIndex((function(e) {
						return e === t;
					}));
					r >= 0 && (n.splice(r, 1), e.attributes.class = n.join(` `));
				}, t.prototype.hasClass = function(e, t) {
					return !!(e.attributes.class || ``).split(/ /).find((function(e) {
						return e === t;
					}));
				}, t.prototype.setStyle = function(e, t, n) {
					e.styles ||= new g.Styles(this.getAttribute(e, `style`)), e.styles.set(t, n), e.attributes.style = e.styles.cssText;
				}, t.prototype.getStyle = function(e, t) {
					if (!e.styles) {
						var n = this.getAttribute(e, `style`);
						if (!n) return ``;
						e.styles = new g.Styles(n);
					}
					return e.styles.get(t);
				}, t.prototype.allStyles = function(e) {
					return this.getAttribute(e, `style`);
				}, t.prototype.insertRules = function(e, t) {
					e.children = [this.text(t.join(`

`) + `

` + this.textContent(e))];
				}, t.prototype.fontSize = function(e) {
					return 0;
				}, t.prototype.fontFamily = function(e) {
					return ``;
				}, t.prototype.nodeSize = function(e, t, n) {
					return t === void 0 && (t = 1), n === void 0 && (n = null), [0, 0];
				}, t.prototype.nodeBBox = function(e) {
					return {
						left: 0,
						right: 0,
						top: 0,
						bottom: 0
					};
				}, t;
			}(l.AbstractDOMAdaptor);
			t.LiteBase = _;
			var v = function(e) {
				function t() {
					return e !== null && e.apply(this, arguments) || this;
				}
				return i(t, e), t;
			}((0, u.NodeMixin)(_));
			t.LiteAdaptor = v, t.liteAdaptor = function(e) {
				return e === void 0 && (e = null), new v(null, e);
			};
		},
		306: function(e, t) {
			t.q = void 0, t.q = `3.2.2`;
		},
		723: function(e, t) {
			MathJax._.components.global.isObject, MathJax._.components.global.combineConfig, MathJax._.components.global.combineDefaults, t.r8 = MathJax._.components.global.combineWithMathJax, MathJax._.components.global.MathJax;
		},
		857: function(e, t) {
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.AbstractDOMAdaptor = MathJax._.core.DOMAdaptor.AbstractDOMAdaptor;
		},
		29: function(e, t) {
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.options = MathJax._.util.Entities.options, t.entities = MathJax._.util.Entities.entities, t.add = MathJax._.util.Entities.add, t.remove = MathJax._.util.Entities.remove, t.translate = MathJax._.util.Entities.translate, t.numeric = MathJax._.util.Entities.numeric;
		},
		77: function(e, t) {
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.isObject = MathJax._.util.Options.isObject, t.APPEND = MathJax._.util.Options.APPEND, t.REMOVE = MathJax._.util.Options.REMOVE, t.OPTIONS = MathJax._.util.Options.OPTIONS, t.Expandable = MathJax._.util.Options.Expandable, t.expandable = MathJax._.util.Options.expandable, t.makeArray = MathJax._.util.Options.makeArray, t.keys = MathJax._.util.Options.keys, t.copy = MathJax._.util.Options.copy, t.insert = MathJax._.util.Options.insert, t.defaultOptions = MathJax._.util.Options.defaultOptions, t.userOptions = MathJax._.util.Options.userOptions, t.selectOptions = MathJax._.util.Options.selectOptions, t.selectOptionsFromKeys = MathJax._.util.Options.selectOptionsFromKeys, t.separateOptions = MathJax._.util.Options.separateOptions, t.lookup = MathJax._.util.Options.lookup;
		},
		878: function(e, t) {
			Object.defineProperty(t, `__esModule`, { value: !0 }), t.Styles = MathJax._.util.Styles.Styles;
		}
	}, u = {};
	function d(e) {
		var t = u[e];
		if (t !== void 0) return t.exports;
		var n = u[e] = { exports: {} };
		return l[e].call(n.exports, n, n.exports, d), n.exports;
	}
	e = d(723), t = d(306), n = d(250), r = d(877), i = d(946), a = d(6), o = d(246), s = d(735), c = d(492), MathJax.loader && MathJax.loader.checkVersion(`adaptors/liteDOM`, t.q, `adaptors`), (0, e.r8)({ _: { adaptors: {
		liteAdaptor: n,
		lite: {
			Document: r,
			Element: i,
			List: a,
			Parser: o,
			Text: s,
			Window: c
		}
	} } }), MathJax.startup && (MathJax.startup.registerConstructor(`liteAdaptor`, n.liteAdaptor), MathJax.startup.useAdaptor(`liteAdaptor`, !0));
})();
//#endregion

//# sourceMappingURL=liteDOM-Cp0aN3bP.js.map