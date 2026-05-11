import { n as o$1 } from "./chunk-DfAF0w94.js";
//#region ../../node_modules/.pnpm/mathxyjax3@0.8.3/node_modules/mathxyjax3/dist/lib-CBtriEt5.js
var t = o$1(((exports) => {
	function t(e, t, n) {
		if (n === void 0 && (n = Array.prototype), e && typeof n.find == `function`) return n.find.call(e, t);
		for (var r = 0; r < e.length; r++) if (Object.prototype.hasOwnProperty.call(e, r)) {
			var i = e[r];
			if (t.call(void 0, i, r, e)) return i;
		}
	}
	function n(e, t) {
		return t === void 0 && (t = Object), t && typeof t.freeze == `function` ? t.freeze(e) : e;
	}
	function r(e, t) {
		if (typeof e != `object` || !e) throw TypeError(`target is not an object`);
		for (var n in t) Object.prototype.hasOwnProperty.call(t, n) && (e[n] = t[n]);
		return e;
	}
	var i = n({
		HTML: `text/html`,
		isHTML: function(e) {
			return e === i.HTML;
		},
		XML_APPLICATION: `application/xml`,
		XML_TEXT: `text/xml`,
		XML_XHTML_APPLICATION: `application/xhtml+xml`,
		XML_SVG_IMAGE: `image/svg+xml`
	}), a = n({
		HTML: `http://www.w3.org/1999/xhtml`,
		isHTML: function(e) {
			return e === a.HTML;
		},
		SVG: `http://www.w3.org/2000/svg`,
		XML: `http://www.w3.org/XML/1998/namespace`,
		XMLNS: `http://www.w3.org/2000/xmlns/`
	});
	exports.assign = r, exports.find = t, exports.freeze = n, exports.MIME_TYPE = i, exports.NAMESPACE = a;
})), n = o$1(((exports) => {
	var n = t(), r = n.find, i = n.NAMESPACE;
	function a(e) {
		return e !== ``;
	}
	function o(e) {
		return e ? e.split(/[\t\n\f\r ]+/).filter(a) : [];
	}
	function s(e, t) {
		return e.hasOwnProperty(t) || (e[t] = !0), e;
	}
	function c(e) {
		if (!e) return [];
		var t = o(e);
		return Object.keys(t.reduce(s, {}));
	}
	function l(e) {
		return function(t) {
			return e && e.indexOf(t) !== -1;
		};
	}
	function u(e, t) {
		for (var n in e) Object.prototype.hasOwnProperty.call(e, n) && (t[n] = e[n]);
	}
	function d(e, t) {
		var n = e.prototype;
		if (!(n instanceof t)) {
			function r() {}
			r.prototype = t.prototype, r = new r(), u(n, r), e.prototype = n = r;
		}
		n.constructor != e && (typeof e != `function` && console.error(`unknown Class:` + e), n.constructor = e);
	}
	var f = {}, p = f.ELEMENT_NODE = 1, m = f.ATTRIBUTE_NODE = 2, h = f.TEXT_NODE = 3, g = f.CDATA_SECTION_NODE = 4, _ = f.ENTITY_REFERENCE_NODE = 5, v = f.ENTITY_NODE = 6, y = f.PROCESSING_INSTRUCTION_NODE = 7, b = f.COMMENT_NODE = 8, x = f.DOCUMENT_NODE = 9, S = f.DOCUMENT_TYPE_NODE = 10, C = f.DOCUMENT_FRAGMENT_NODE = 11, w = f.NOTATION_NODE = 12, T = {}, E = {};
	T.INDEX_SIZE_ERR = (E[1] = `Index size error`, 1), T.DOMSTRING_SIZE_ERR = (E[2] = `DOMString size error`, 2);
	var D = T.HIERARCHY_REQUEST_ERR = (E[3] = `Hierarchy request error`, 3);
	T.WRONG_DOCUMENT_ERR = (E[4] = `Wrong document`, 4), T.INVALID_CHARACTER_ERR = (E[5] = `Invalid character`, 5), T.NO_DATA_ALLOWED_ERR = (E[6] = `No data allowed`, 6), T.NO_MODIFICATION_ALLOWED_ERR = (E[7] = `No modification allowed`, 7);
	var O = T.NOT_FOUND_ERR = (E[8] = `Not found`, 8);
	T.NOT_SUPPORTED_ERR = (E[9] = `Not supported`, 9);
	var k = T.INUSE_ATTRIBUTE_ERR = (E[10] = `Attribute in use`, 10);
	T.INVALID_STATE_ERR = (E[11] = `Invalid state`, 11), T.SYNTAX_ERR = (E[12] = `Syntax error`, 12), T.INVALID_MODIFICATION_ERR = (E[13] = `Invalid modification`, 13), T.NAMESPACE_ERR = (E[14] = `Invalid namespace`, 14), T.INVALID_ACCESS_ERR = (E[15] = `Invalid access`, 15);
	function A(e, t) {
		if (t instanceof Error) var n = t;
		else n = this, Error.call(this, E[e]), this.message = E[e], Error.captureStackTrace && Error.captureStackTrace(this, A);
		return n.code = e, t && (this.message = this.message + `: ` + t), n;
	}
	A.prototype = Error.prototype, u(T, A);
	function j() {}
	j.prototype = {
		length: 0,
		item: function(e) {
			return e >= 0 && e < this.length ? this[e] : null;
		},
		toString: function(e, t) {
			for (var n = [], r = 0; r < this.length; r++) $(this[r], n, e, t);
			return n.join(``);
		},
		filter: function(e) {
			return Array.prototype.filter.call(this, e);
		},
		indexOf: function(e) {
			return Array.prototype.indexOf.call(this, e);
		}
	};
	function M(e, t) {
		this._node = e, this._refresh = t, N(this);
	}
	function N(e) {
		var t = e._node._inc || e._node.ownerDocument._inc;
		if (e._inc !== t) {
			var n = e._refresh(e._node);
			if (Te(e, `length`, n.length), !e.$$length || n.length < e.$$length) for (var r = n.length; r in e; r++) Object.prototype.hasOwnProperty.call(e, r) && delete e[r];
			u(n, e), e._inc = t;
		}
	}
	M.prototype.item = function(e) {
		return N(this), this[e] || null;
	}, d(M, j);
	function P() {}
	function F(e, t) {
		for (var n = e.length; n--;) if (e[n] === t) return n;
	}
	function I(e, t, n, r) {
		if (r ? t[F(t, r)] = n : t[t.length++] = n, e) {
			n.ownerElement = e;
			var i = e.ownerDocument;
			i && (r && te(i, e, r), ee(i, e, n));
		}
	}
	function L(e, t, n) {
		var r = F(t, n);
		if (r >= 0) {
			for (var i = t.length - 1; r < i;) t[r] = t[++r];
			if (t.length = i, e) {
				var a = e.ownerDocument;
				a && (te(a, e, n), n.ownerElement = null);
			}
		} else throw new A(O, Error(e.tagName + `@` + n));
	}
	P.prototype = {
		length: 0,
		item: j.prototype.item,
		getNamedItem: function(e) {
			for (var t = this.length; t--;) {
				var n = this[t];
				if (n.nodeName == e) return n;
			}
		},
		setNamedItem: function(e) {
			var t = e.ownerElement;
			if (t && t != this._ownerElement) throw new A(k);
			var n = this.getNamedItem(e.nodeName);
			return I(this._ownerElement, this, e, n), n;
		},
		setNamedItemNS: function(e) {
			var t = e.ownerElement, n;
			if (t && t != this._ownerElement) throw new A(k);
			return n = this.getNamedItemNS(e.namespaceURI, e.localName), I(this._ownerElement, this, e, n), n;
		},
		removeNamedItem: function(e) {
			var t = this.getNamedItem(e);
			return L(this._ownerElement, this, t), t;
		},
		removeNamedItemNS: function(e, t) {
			var n = this.getNamedItemNS(e, t);
			return L(this._ownerElement, this, n), n;
		},
		getNamedItemNS: function(e, t) {
			for (var n = this.length; n--;) {
				var r = this[n];
				if (r.localName == t && r.namespaceURI == e) return r;
			}
			return null;
		}
	};
	function R() {}
	R.prototype = {
		hasFeature: function(e, t) {
			return !0;
		},
		createDocument: function(e, t, n) {
			var r = new H();
			if (r.implementation = this, r.childNodes = new j(), r.doctype = n || null, n && r.appendChild(n), t) {
				var i = r.createElementNS(e, t);
				r.appendChild(i);
			}
			return r;
		},
		createDocumentType: function(e, t, n) {
			var r = new Z();
			return r.name = e, r.nodeName = e, r.publicId = t || ``, r.systemId = n || ``, r;
		}
	};
	function z() {}
	z.prototype = {
		firstChild: null,
		lastChild: null,
		previousSibling: null,
		nextSibling: null,
		attributes: null,
		parentNode: null,
		childNodes: null,
		ownerDocument: null,
		nodeValue: null,
		namespaceURI: null,
		prefix: null,
		localName: null,
		insertBefore: function(e, t) {
			return K(this, e, t);
		},
		replaceChild: function(e, t) {
			K(this, e, t, ue), t && this.removeChild(t);
		},
		removeChild: function(e) {
			return ne(this, e);
		},
		appendChild: function(e) {
			return this.insertBefore(e, null);
		},
		hasChildNodes: function() {
			return this.firstChild != null;
		},
		cloneNode: function(e) {
			return we(this.ownerDocument || this, this, e);
		},
		normalize: function() {
			for (var e = this.firstChild; e;) {
				var t = e.nextSibling;
				t && t.nodeType == h && e.nodeType == h ? (this.removeChild(t), e.appendData(t.data)) : (e.normalize(), e = t);
			}
		},
		isSupported: function(e, t) {
			return this.ownerDocument.implementation.hasFeature(e, t);
		},
		hasAttributes: function() {
			return this.attributes.length > 0;
		},
		lookupPrefix: function(e) {
			for (var t = this; t;) {
				var n = t._nsMap;
				if (n) {
					for (var r in n) if (Object.prototype.hasOwnProperty.call(n, r) && n[r] === e) return r;
				}
				t = t.nodeType == m ? t.ownerDocument : t.parentNode;
			}
			return null;
		},
		lookupNamespaceURI: function(e) {
			for (var t = this; t;) {
				var n = t._nsMap;
				if (n && Object.prototype.hasOwnProperty.call(n, e)) return n[e];
				t = t.nodeType == m ? t.ownerDocument : t.parentNode;
			}
			return null;
		},
		isDefaultNamespace: function(e) {
			return this.lookupPrefix(e) == null;
		}
	};
	function B(e) {
		return e == `<` && `&lt;` || e == `>` && `&gt;` || e == `&` && `&amp;` || e == `"` && `&quot;` || `&#` + e.charCodeAt() + `;`;
	}
	u(f, z), u(f, z.prototype);
	function V(e, t) {
		if (t(e)) return !0;
		if (e = e.firstChild) do
			if (V(e, t)) return !0;
		while (e = e.nextSibling);
	}
	function H() {
		this.ownerDocument = this;
	}
	function ee(e, t, n) {
		e && e._inc++, n.namespaceURI === i.XMLNS && (t._nsMap[n.prefix ? n.localName : ``] = n.value);
	}
	function te(e, t, n, r) {
		e && e._inc++, n.namespaceURI === i.XMLNS && delete t._nsMap[n.prefix ? n.localName : ``];
	}
	function U(e, t, n) {
		if (e && e._inc) {
			e._inc++;
			var r = t.childNodes;
			if (n) r[r.length++] = n;
			else {
				for (var i = t.firstChild, a = 0; i;) r[a++] = i, i = i.nextSibling;
				r.length = a, delete r[r.length];
			}
		}
	}
	function ne(e, t) {
		var n = t.previousSibling, r = t.nextSibling;
		return n ? n.nextSibling = r : e.firstChild = r, r ? r.previousSibling = n : e.lastChild = n, t.parentNode = null, t.previousSibling = null, t.nextSibling = null, U(e.ownerDocument, e), t;
	}
	function re(e) {
		return e && (e.nodeType === z.DOCUMENT_NODE || e.nodeType === z.DOCUMENT_FRAGMENT_NODE || e.nodeType === z.ELEMENT_NODE);
	}
	function ie(e) {
		return e && (G(e) || ae(e) || W(e) || e.nodeType === z.DOCUMENT_FRAGMENT_NODE || e.nodeType === z.COMMENT_NODE || e.nodeType === z.PROCESSING_INSTRUCTION_NODE);
	}
	function W(e) {
		return e && e.nodeType === z.DOCUMENT_TYPE_NODE;
	}
	function G(e) {
		return e && e.nodeType === z.ELEMENT_NODE;
	}
	function ae(e) {
		return e && e.nodeType === z.TEXT_NODE;
	}
	function oe(e, t) {
		var n = e.childNodes || [];
		if (r(n, G) || W(t)) return !1;
		var i = r(n, W);
		return !(t && i && n.indexOf(i) > n.indexOf(t));
	}
	function se(e, t) {
		var n = e.childNodes || [];
		function i(e) {
			return G(e) && e !== t;
		}
		if (r(n, i)) return !1;
		var a = r(n, W);
		return !(t && a && n.indexOf(a) > n.indexOf(t));
	}
	function ce(e, t, n) {
		if (!re(e)) throw new A(D, `Unexpected parent node type ` + e.nodeType);
		if (n && n.parentNode !== e) throw new A(O, `child not in parent`);
		if (!ie(t) || W(t) && e.nodeType !== z.DOCUMENT_NODE) throw new A(D, `Unexpected node type ` + t.nodeType + ` for parent node type ` + e.nodeType);
	}
	function le(e, t, n) {
		var i = e.childNodes || [], a = t.childNodes || [];
		if (t.nodeType === z.DOCUMENT_FRAGMENT_NODE) {
			var o = a.filter(G);
			if (o.length > 1 || r(a, ae)) throw new A(D, `More than one element or text in fragment`);
			if (o.length === 1 && !oe(e, n)) throw new A(D, `Element in fragment can not be inserted before doctype`);
		}
		if (G(t) && !oe(e, n)) throw new A(D, `Only one element can be added and only after doctype`);
		if (W(t)) {
			if (r(i, W)) throw new A(D, `Only one doctype is allowed`);
			var s = r(i, G);
			if (n && i.indexOf(s) < i.indexOf(n)) throw new A(D, `Doctype can only be inserted before an element`);
			if (!n && s) throw new A(D, `Doctype can not be appended since element is present`);
		}
	}
	function ue(e, t, n) {
		var i = e.childNodes || [], a = t.childNodes || [];
		if (t.nodeType === z.DOCUMENT_FRAGMENT_NODE) {
			var o = a.filter(G);
			if (o.length > 1 || r(a, ae)) throw new A(D, `More than one element or text in fragment`);
			if (o.length === 1 && !se(e, n)) throw new A(D, `Element in fragment can not be inserted before doctype`);
		}
		if (G(t) && !se(e, n)) throw new A(D, `Only one element can be added and only after doctype`);
		if (W(t)) {
			function e(e) {
				return W(e) && e !== n;
			}
			if (r(i, e)) throw new A(D, `Only one doctype is allowed`);
			var s = r(i, G);
			if (n && i.indexOf(s) < i.indexOf(n)) throw new A(D, `Doctype can only be inserted before an element`);
		}
	}
	function K(e, t, n, r) {
		ce(e, t, n), e.nodeType === z.DOCUMENT_NODE && (r || le)(e, t, n);
		var i = t.parentNode;
		if (i && i.removeChild(t), t.nodeType === C) {
			var a = t.firstChild;
			if (a == null) return t;
			var o = t.lastChild;
		} else a = o = t;
		var s = n ? n.previousSibling : e.lastChild;
		a.previousSibling = s, o.nextSibling = n, s ? s.nextSibling = a : e.firstChild = a, n == null ? e.lastChild = o : n.previousSibling = o;
		do {
			a.parentNode = e;
			var c = e.ownerDocument || e;
			q(a, c);
		} while (a !== o && (a = a.nextSibling));
		return U(e.ownerDocument || e, e), t.nodeType == C && (t.firstChild = t.lastChild = null), t;
	}
	function q(e, t) {
		if (e.ownerDocument !== t) {
			if (e.ownerDocument = t, e.nodeType === p && e.attributes) for (var n = 0; n < e.attributes.length; n++) {
				var r = e.attributes.item(n);
				r && (r.ownerDocument = t);
			}
			for (var i = e.firstChild; i;) q(i, t), i = i.nextSibling;
		}
	}
	function de(e, t) {
		t.parentNode && t.parentNode.removeChild(t), t.parentNode = e, t.previousSibling = e.lastChild, t.nextSibling = null, t.previousSibling ? t.previousSibling.nextSibling = t : e.firstChild = t, e.lastChild = t, U(e.ownerDocument, e, t);
		return q(t, e.ownerDocument || e), t;
	}
	H.prototype = {
		nodeName: `#document`,
		nodeType: x,
		doctype: null,
		documentElement: null,
		_inc: 1,
		insertBefore: function(e, t) {
			if (e.nodeType == C) {
				for (var n = e.firstChild; n;) {
					var r = n.nextSibling;
					this.insertBefore(n, t), n = r;
				}
				return e;
			}
			return K(this, e, t), q(e, this), this.documentElement === null && e.nodeType === p && (this.documentElement = e), e;
		},
		removeChild: function(e) {
			return this.documentElement == e && (this.documentElement = null), ne(this, e);
		},
		replaceChild: function(e, t) {
			K(this, e, t, ue), q(e, this), t && this.removeChild(t), G(e) && (this.documentElement = e);
		},
		importNode: function(e, t) {
			return Ce(this, e, t);
		},
		getElementById: function(e) {
			var t = null;
			return V(this.documentElement, function(n) {
				if (n.nodeType == p && n.getAttribute(`id`) == e) return t = n, !0;
			}), t;
		},
		getElementsByClassName: function(e) {
			var t = c(e);
			return new M(this, function(n) {
				var r = [];
				return t.length > 0 && V(n.documentElement, function(i) {
					if (i !== n && i.nodeType === p) {
						var a = i.getAttribute(`class`);
						if (a) {
							var o = e === a;
							if (!o) {
								var s = c(a);
								o = t.every(l(s));
							}
							o && r.push(i);
						}
					}
				}), r;
			});
		},
		createElement: function(e) {
			var t = new J();
			t.ownerDocument = this, t.nodeName = e, t.tagName = e, t.localName = e, t.childNodes = new j();
			var n = t.attributes = new P();
			return n._ownerElement = t, t;
		},
		createDocumentFragment: function() {
			var e = new Q();
			return e.ownerDocument = this, e.childNodes = new j(), e;
		},
		createTextNode: function(e) {
			var t = new fe();
			return t.ownerDocument = this, t.appendData(e), t;
		},
		createComment: function(e) {
			var t = new pe();
			return t.ownerDocument = this, t.appendData(e), t;
		},
		createCDATASection: function(e) {
			var t = new me();
			return t.ownerDocument = this, t.appendData(e), t;
		},
		createProcessingInstruction: function(e, t) {
			var n = new ve();
			return n.ownerDocument = this, n.tagName = n.nodeName = n.target = e, n.nodeValue = n.data = t, n;
		},
		createAttribute: function(e) {
			var t = new Y();
			return t.ownerDocument = this, t.name = e, t.nodeName = e, t.localName = e, t.specified = !0, t;
		},
		createEntityReference: function(e) {
			var t = new _e();
			return t.ownerDocument = this, t.nodeName = e, t;
		},
		createElementNS: function(e, t) {
			var n = new J(), r = t.split(`:`), i = n.attributes = new P();
			return n.childNodes = new j(), n.ownerDocument = this, n.nodeName = t, n.tagName = t, n.namespaceURI = e, r.length == 2 ? (n.prefix = r[0], n.localName = r[1]) : n.localName = t, i._ownerElement = n, n;
		},
		createAttributeNS: function(e, t) {
			var n = new Y(), r = t.split(`:`);
			return n.ownerDocument = this, n.nodeName = t, n.name = t, n.namespaceURI = e, n.specified = !0, r.length == 2 ? (n.prefix = r[0], n.localName = r[1]) : n.localName = t, n;
		}
	}, d(H, z);
	function J() {
		this._nsMap = {};
	}
	J.prototype = {
		nodeType: p,
		hasAttribute: function(e) {
			return this.getAttributeNode(e) != null;
		},
		getAttribute: function(e) {
			var t = this.getAttributeNode(e);
			return t && t.value || ``;
		},
		getAttributeNode: function(e) {
			return this.attributes.getNamedItem(e);
		},
		setAttribute: function(e, t) {
			var n = this.ownerDocument.createAttribute(e);
			n.value = n.nodeValue = `` + t, this.setAttributeNode(n);
		},
		removeAttribute: function(e) {
			var t = this.getAttributeNode(e);
			t && this.removeAttributeNode(t);
		},
		appendChild: function(e) {
			return e.nodeType === C ? this.insertBefore(e, null) : de(this, e);
		},
		setAttributeNode: function(e) {
			return this.attributes.setNamedItem(e);
		},
		setAttributeNodeNS: function(e) {
			return this.attributes.setNamedItemNS(e);
		},
		removeAttributeNode: function(e) {
			return this.attributes.removeNamedItem(e.nodeName);
		},
		removeAttributeNS: function(e, t) {
			var n = this.getAttributeNodeNS(e, t);
			n && this.removeAttributeNode(n);
		},
		hasAttributeNS: function(e, t) {
			return this.getAttributeNodeNS(e, t) != null;
		},
		getAttributeNS: function(e, t) {
			var n = this.getAttributeNodeNS(e, t);
			return n && n.value || ``;
		},
		setAttributeNS: function(e, t, n) {
			var r = this.ownerDocument.createAttributeNS(e, t);
			r.value = r.nodeValue = `` + n, this.setAttributeNode(r);
		},
		getAttributeNodeNS: function(e, t) {
			return this.attributes.getNamedItemNS(e, t);
		},
		getElementsByTagName: function(e) {
			return new M(this, function(t) {
				var n = [];
				return V(t, function(r) {
					r !== t && r.nodeType == p && (e === `*` || r.tagName == e) && n.push(r);
				}), n;
			});
		},
		getElementsByTagNameNS: function(e, t) {
			return new M(this, function(n) {
				var r = [];
				return V(n, function(i) {
					i !== n && i.nodeType === p && (e === `*` || i.namespaceURI === e) && (t === `*` || i.localName == t) && r.push(i);
				}), r;
			});
		}
	}, H.prototype.getElementsByTagName = J.prototype.getElementsByTagName, H.prototype.getElementsByTagNameNS = J.prototype.getElementsByTagNameNS, d(J, z);
	function Y() {}
	Y.prototype.nodeType = m, d(Y, z);
	function X() {}
	X.prototype = {
		data: ``,
		substringData: function(e, t) {
			return this.data.substring(e, e + t);
		},
		appendData: function(e) {
			e = this.data + e, this.nodeValue = this.data = e, this.length = e.length;
		},
		insertData: function(e, t) {
			this.replaceData(e, 0, t);
		},
		appendChild: function(e) {
			throw Error(E[D]);
		},
		deleteData: function(e, t) {
			this.replaceData(e, t, ``);
		},
		replaceData: function(e, t, n) {
			var r = this.data.substring(0, e), i = this.data.substring(e + t);
			n = r + n + i, this.nodeValue = this.data = n, this.length = n.length;
		}
	}, d(X, z);
	function fe() {}
	fe.prototype = {
		nodeName: `#text`,
		nodeType: h,
		splitText: function(e) {
			var t = this.data, n = t.substring(e);
			t = t.substring(0, e), this.data = this.nodeValue = t, this.length = t.length;
			var r = this.ownerDocument.createTextNode(n);
			return this.parentNode && this.parentNode.insertBefore(r, this.nextSibling), r;
		}
	}, d(fe, X);
	function pe() {}
	pe.prototype = {
		nodeName: `#comment`,
		nodeType: b
	}, d(pe, X);
	function me() {}
	me.prototype = {
		nodeName: `#cdata-section`,
		nodeType: g
	}, d(me, X);
	function Z() {}
	Z.prototype.nodeType = S, d(Z, z);
	function he() {}
	he.prototype.nodeType = w, d(he, z);
	function ge() {}
	ge.prototype.nodeType = v, d(ge, z);
	function _e() {}
	_e.prototype.nodeType = _, d(_e, z);
	function Q() {}
	Q.prototype.nodeName = `#document-fragment`, Q.prototype.nodeType = C, d(Q, z);
	function ve() {}
	ve.prototype.nodeType = y, d(ve, z);
	function ye() {}
	ye.prototype.serializeToString = function(e, t, n) {
		return be.call(e, t, n);
	}, z.prototype.toString = be;
	function be(e, t) {
		var n = [], r = this.nodeType == 9 && this.documentElement || this, i = r.prefix, a = r.namespaceURI;
		if (a && i == null) {
			var i = r.lookupPrefix(a);
			if (i == null) var o = [{
				namespace: a,
				prefix: null
			}];
		}
		return $(this, n, e, t, o), n.join(``);
	}
	function xe(e, t, n) {
		var r = e.prefix || ``, a = e.namespaceURI;
		if (!a || r === `xml` && a === i.XML || a === i.XMLNS) return !1;
		for (var o = n.length; o--;) {
			var s = n[o];
			if (s.prefix === r) return s.namespace !== a;
		}
		return !0;
	}
	function Se(e, t, n) {
		e.push(` `, t, `="`, n.replace(/[<>&"\t\n\r]/g, B), `"`);
	}
	function $(e, t, n, r, a) {
		if (a ||= [], r) if (e = r(e), e) {
			if (typeof e == `string`) {
				t.push(e);
				return;
			}
		} else return;
		switch (e.nodeType) {
			case p:
				var o = e.attributes, s = o.length, c = e.firstChild, l = e.tagName;
				n = i.isHTML(e.namespaceURI) || n;
				var u = l;
				if (!n && !e.prefix && e.namespaceURI) {
					for (var d, f = 0; f < o.length; f++) if (o.item(f).name === `xmlns`) {
						d = o.item(f).value;
						break;
					}
					if (!d) for (var v = a.length - 1; v >= 0; v--) {
						var w = a[v];
						if (w.prefix === `` && w.namespace === e.namespaceURI) {
							d = w.namespace;
							break;
						}
					}
					if (d !== e.namespaceURI) for (var v = a.length - 1; v >= 0; v--) {
						var w = a[v];
						if (w.namespace === e.namespaceURI) {
							w.prefix && (u = w.prefix + `:` + l);
							break;
						}
					}
				}
				t.push(`<`, u);
				for (var T = 0; T < s; T++) {
					var E = o.item(T);
					E.prefix == `xmlns` ? a.push({
						prefix: E.localName,
						namespace: E.value
					}) : E.nodeName == `xmlns` && a.push({
						prefix: ``,
						namespace: E.value
					});
				}
				for (var T = 0; T < s; T++) {
					var E = o.item(T);
					if (xe(E, n, a)) {
						var D = E.prefix || ``, O = E.namespaceURI;
						Se(t, D ? `xmlns:` + D : `xmlns`, O), a.push({
							prefix: D,
							namespace: O
						});
					}
					$(E, t, n, r, a);
				}
				if (l === u && xe(e, n, a)) {
					var D = e.prefix || ``, O = e.namespaceURI;
					Se(t, D ? `xmlns:` + D : `xmlns`, O), a.push({
						prefix: D,
						namespace: O
					});
				}
				if (c || n && !/^(?:meta|link|img|br|hr|input)$/i.test(l)) {
					if (t.push(`>`), n && /^script$/i.test(l)) for (; c;) c.data ? t.push(c.data) : $(c, t, n, r, a.slice()), c = c.nextSibling;
					else for (; c;) $(c, t, n, r, a.slice()), c = c.nextSibling;
					t.push(`</`, u, `>`);
				} else t.push(`/>`);
				return;
			case x:
			case C:
				for (var c = e.firstChild; c;) $(c, t, n, r, a.slice()), c = c.nextSibling;
				return;
			case m: return Se(t, e.name, e.value);
			case h: return t.push(e.data.replace(/[<&>]/g, B));
			case g: return t.push(`<![CDATA[`, e.data, `]]>`);
			case b: return t.push(`<!--`, e.data, `-->`);
			case S:
				var k = e.publicId, A = e.systemId;
				if (t.push(`<!DOCTYPE `, e.name), k) t.push(` PUBLIC `, k), A && A != `.` && t.push(` `, A), t.push(`>`);
				else if (A && A != `.`) t.push(` SYSTEM `, A, `>`);
				else {
					var j = e.internalSubset;
					j && t.push(` [`, j, `]`), t.push(`>`);
				}
				return;
			case y: return t.push(`<?`, e.target, ` `, e.data, `?>`);
			case _: return t.push(`&`, e.nodeName, `;`);
			default: t.push(`??`, e.nodeName);
		}
	}
	function Ce(e, t, n) {
		var r;
		switch (t.nodeType) {
			case p: r = t.cloneNode(!1), r.ownerDocument = e;
			case C: break;
			case m:
				n = !0;
				break;
		}
		if (r ||= t.cloneNode(!1), r.ownerDocument = e, r.parentNode = null, n) for (var i = t.firstChild; i;) r.appendChild(Ce(e, i, n)), i = i.nextSibling;
		return r;
	}
	function we(e, t, n) {
		var r = new t.constructor();
		for (var i in t) if (Object.prototype.hasOwnProperty.call(t, i)) {
			var a = t[i];
			typeof a != `object` && a != r[i] && (r[i] = a);
		}
		switch (t.childNodes && (r.childNodes = new j()), r.ownerDocument = e, r.nodeType) {
			case p:
				var o = t.attributes, s = r.attributes = new P(), c = o.length;
				s._ownerElement = r;
				for (var l = 0; l < c; l++) r.setAttributeNode(we(e, o.item(l), !0));
				break;
			case m: n = !0;
		}
		if (n) for (var u = t.firstChild; u;) r.appendChild(we(e, u, n)), u = u.nextSibling;
		return r;
	}
	function Te(e, t, n) {
		e[t] = n;
	}
	try {
		if (Object.defineProperty) {
			Object.defineProperty(M.prototype, `length`, { get: function() {
				return N(this), this.$$length;
			} }), Object.defineProperty(z.prototype, `textContent`, {
				get: function() {
					return e(this);
				},
				set: function(e) {
					switch (this.nodeType) {
						case p:
						case C:
							for (; this.firstChild;) this.removeChild(this.firstChild);
							(e || String(e)) && this.appendChild(this.ownerDocument.createTextNode(e));
							break;
						default: this.data = e, this.value = e, this.nodeValue = e;
					}
				}
			});
			function e(t) {
				switch (t.nodeType) {
					case p:
					case C:
						var n = [];
						for (t = t.firstChild; t;) t.nodeType !== 7 && t.nodeType !== 8 && n.push(e(t)), t = t.nextSibling;
						return n.join(``);
					default: return t.nodeValue;
				}
			}
			Te = function(e, t, n) {
				e[`$$` + t] = n;
			};
		}
	} catch {}
	exports.DocumentType = Z, exports.DOMException = A, exports.DOMImplementation = R, exports.Element = J, exports.Node = z, exports.NodeList = j, exports.XMLSerializer = ye;
})), r = o$1(((exports) => {
	var n = t().freeze;
	exports.XML_ENTITIES = n({
		amp: `&`,
		apos: `'`,
		gt: `>`,
		lt: `<`,
		quot: `"`
	}), exports.HTML_ENTITIES = n({
		Aacute: `Á`,
		aacute: `á`,
		Abreve: `Ă`,
		abreve: `ă`,
		ac: `∾`,
		acd: `∿`,
		acE: `∾̳`,
		Acirc: `Â`,
		acirc: `â`,
		acute: `´`,
		Acy: `А`,
		acy: `а`,
		AElig: `Æ`,
		aelig: `æ`,
		af: `⁡`,
		Afr: `𝔄`,
		afr: `𝔞`,
		Agrave: `À`,
		agrave: `à`,
		alefsym: `ℵ`,
		aleph: `ℵ`,
		Alpha: `Α`,
		alpha: `α`,
		Amacr: `Ā`,
		amacr: `ā`,
		amalg: `⨿`,
		AMP: `&`,
		amp: `&`,
		And: `⩓`,
		and: `∧`,
		andand: `⩕`,
		andd: `⩜`,
		andslope: `⩘`,
		andv: `⩚`,
		ang: `∠`,
		ange: `⦤`,
		angle: `∠`,
		angmsd: `∡`,
		angmsdaa: `⦨`,
		angmsdab: `⦩`,
		angmsdac: `⦪`,
		angmsdad: `⦫`,
		angmsdae: `⦬`,
		angmsdaf: `⦭`,
		angmsdag: `⦮`,
		angmsdah: `⦯`,
		angrt: `∟`,
		angrtvb: `⊾`,
		angrtvbd: `⦝`,
		angsph: `∢`,
		angst: `Å`,
		angzarr: `⍼`,
		Aogon: `Ą`,
		aogon: `ą`,
		Aopf: `𝔸`,
		aopf: `𝕒`,
		ap: `≈`,
		apacir: `⩯`,
		apE: `⩰`,
		ape: `≊`,
		apid: `≋`,
		apos: `'`,
		ApplyFunction: `⁡`,
		approx: `≈`,
		approxeq: `≊`,
		Aring: `Å`,
		aring: `å`,
		Ascr: `𝒜`,
		ascr: `𝒶`,
		Assign: `≔`,
		ast: `*`,
		asymp: `≈`,
		asympeq: `≍`,
		Atilde: `Ã`,
		atilde: `ã`,
		Auml: `Ä`,
		auml: `ä`,
		awconint: `∳`,
		awint: `⨑`,
		backcong: `≌`,
		backepsilon: `϶`,
		backprime: `‵`,
		backsim: `∽`,
		backsimeq: `⋍`,
		Backslash: `∖`,
		Barv: `⫧`,
		barvee: `⊽`,
		Barwed: `⌆`,
		barwed: `⌅`,
		barwedge: `⌅`,
		bbrk: `⎵`,
		bbrktbrk: `⎶`,
		bcong: `≌`,
		Bcy: `Б`,
		bcy: `б`,
		bdquo: `„`,
		becaus: `∵`,
		Because: `∵`,
		because: `∵`,
		bemptyv: `⦰`,
		bepsi: `϶`,
		bernou: `ℬ`,
		Bernoullis: `ℬ`,
		Beta: `Β`,
		beta: `β`,
		beth: `ℶ`,
		between: `≬`,
		Bfr: `𝔅`,
		bfr: `𝔟`,
		bigcap: `⋂`,
		bigcirc: `◯`,
		bigcup: `⋃`,
		bigodot: `⨀`,
		bigoplus: `⨁`,
		bigotimes: `⨂`,
		bigsqcup: `⨆`,
		bigstar: `★`,
		bigtriangledown: `▽`,
		bigtriangleup: `△`,
		biguplus: `⨄`,
		bigvee: `⋁`,
		bigwedge: `⋀`,
		bkarow: `⤍`,
		blacklozenge: `⧫`,
		blacksquare: `▪`,
		blacktriangle: `▴`,
		blacktriangledown: `▾`,
		blacktriangleleft: `◂`,
		blacktriangleright: `▸`,
		blank: `␣`,
		blk12: `▒`,
		blk14: `░`,
		blk34: `▓`,
		block: `█`,
		bne: `=⃥`,
		bnequiv: `≡⃥`,
		bNot: `⫭`,
		bnot: `⌐`,
		Bopf: `𝔹`,
		bopf: `𝕓`,
		bot: `⊥`,
		bottom: `⊥`,
		bowtie: `⋈`,
		boxbox: `⧉`,
		boxDL: `╗`,
		boxDl: `╖`,
		boxdL: `╕`,
		boxdl: `┐`,
		boxDR: `╔`,
		boxDr: `╓`,
		boxdR: `╒`,
		boxdr: `┌`,
		boxH: `═`,
		boxh: `─`,
		boxHD: `╦`,
		boxHd: `╤`,
		boxhD: `╥`,
		boxhd: `┬`,
		boxHU: `╩`,
		boxHu: `╧`,
		boxhU: `╨`,
		boxhu: `┴`,
		boxminus: `⊟`,
		boxplus: `⊞`,
		boxtimes: `⊠`,
		boxUL: `╝`,
		boxUl: `╜`,
		boxuL: `╛`,
		boxul: `┘`,
		boxUR: `╚`,
		boxUr: `╙`,
		boxuR: `╘`,
		boxur: `└`,
		boxV: `║`,
		boxv: `│`,
		boxVH: `╬`,
		boxVh: `╫`,
		boxvH: `╪`,
		boxvh: `┼`,
		boxVL: `╣`,
		boxVl: `╢`,
		boxvL: `╡`,
		boxvl: `┤`,
		boxVR: `╠`,
		boxVr: `╟`,
		boxvR: `╞`,
		boxvr: `├`,
		bprime: `‵`,
		Breve: `˘`,
		breve: `˘`,
		brvbar: `¦`,
		Bscr: `ℬ`,
		bscr: `𝒷`,
		bsemi: `⁏`,
		bsim: `∽`,
		bsime: `⋍`,
		bsol: `\\`,
		bsolb: `⧅`,
		bsolhsub: `⟈`,
		bull: `•`,
		bullet: `•`,
		bump: `≎`,
		bumpE: `⪮`,
		bumpe: `≏`,
		Bumpeq: `≎`,
		bumpeq: `≏`,
		Cacute: `Ć`,
		cacute: `ć`,
		Cap: `⋒`,
		cap: `∩`,
		capand: `⩄`,
		capbrcup: `⩉`,
		capcap: `⩋`,
		capcup: `⩇`,
		capdot: `⩀`,
		CapitalDifferentialD: `ⅅ`,
		caps: `∩︀`,
		caret: `⁁`,
		caron: `ˇ`,
		Cayleys: `ℭ`,
		ccaps: `⩍`,
		Ccaron: `Č`,
		ccaron: `č`,
		Ccedil: `Ç`,
		ccedil: `ç`,
		Ccirc: `Ĉ`,
		ccirc: `ĉ`,
		Cconint: `∰`,
		ccups: `⩌`,
		ccupssm: `⩐`,
		Cdot: `Ċ`,
		cdot: `ċ`,
		cedil: `¸`,
		Cedilla: `¸`,
		cemptyv: `⦲`,
		cent: `¢`,
		CenterDot: `·`,
		centerdot: `·`,
		Cfr: `ℭ`,
		cfr: `𝔠`,
		CHcy: `Ч`,
		chcy: `ч`,
		check: `✓`,
		checkmark: `✓`,
		Chi: `Χ`,
		chi: `χ`,
		cir: `○`,
		circ: `ˆ`,
		circeq: `≗`,
		circlearrowleft: `↺`,
		circlearrowright: `↻`,
		circledast: `⊛`,
		circledcirc: `⊚`,
		circleddash: `⊝`,
		CircleDot: `⊙`,
		circledR: `®`,
		circledS: `Ⓢ`,
		CircleMinus: `⊖`,
		CirclePlus: `⊕`,
		CircleTimes: `⊗`,
		cirE: `⧃`,
		cire: `≗`,
		cirfnint: `⨐`,
		cirmid: `⫯`,
		cirscir: `⧂`,
		ClockwiseContourIntegral: `∲`,
		CloseCurlyDoubleQuote: `”`,
		CloseCurlyQuote: `’`,
		clubs: `♣`,
		clubsuit: `♣`,
		Colon: `∷`,
		colon: `:`,
		Colone: `⩴`,
		colone: `≔`,
		coloneq: `≔`,
		comma: `,`,
		commat: `@`,
		comp: `∁`,
		compfn: `∘`,
		complement: `∁`,
		complexes: `ℂ`,
		cong: `≅`,
		congdot: `⩭`,
		Congruent: `≡`,
		Conint: `∯`,
		conint: `∮`,
		ContourIntegral: `∮`,
		Copf: `ℂ`,
		copf: `𝕔`,
		coprod: `∐`,
		Coproduct: `∐`,
		COPY: `©`,
		copy: `©`,
		copysr: `℗`,
		CounterClockwiseContourIntegral: `∳`,
		crarr: `↵`,
		Cross: `⨯`,
		cross: `✗`,
		Cscr: `𝒞`,
		cscr: `𝒸`,
		csub: `⫏`,
		csube: `⫑`,
		csup: `⫐`,
		csupe: `⫒`,
		ctdot: `⋯`,
		cudarrl: `⤸`,
		cudarrr: `⤵`,
		cuepr: `⋞`,
		cuesc: `⋟`,
		cularr: `↶`,
		cularrp: `⤽`,
		Cup: `⋓`,
		cup: `∪`,
		cupbrcap: `⩈`,
		CupCap: `≍`,
		cupcap: `⩆`,
		cupcup: `⩊`,
		cupdot: `⊍`,
		cupor: `⩅`,
		cups: `∪︀`,
		curarr: `↷`,
		curarrm: `⤼`,
		curlyeqprec: `⋞`,
		curlyeqsucc: `⋟`,
		curlyvee: `⋎`,
		curlywedge: `⋏`,
		curren: `¤`,
		curvearrowleft: `↶`,
		curvearrowright: `↷`,
		cuvee: `⋎`,
		cuwed: `⋏`,
		cwconint: `∲`,
		cwint: `∱`,
		cylcty: `⌭`,
		Dagger: `‡`,
		dagger: `†`,
		daleth: `ℸ`,
		Darr: `↡`,
		dArr: `⇓`,
		darr: `↓`,
		dash: `‐`,
		Dashv: `⫤`,
		dashv: `⊣`,
		dbkarow: `⤏`,
		dblac: `˝`,
		Dcaron: `Ď`,
		dcaron: `ď`,
		Dcy: `Д`,
		dcy: `д`,
		DD: `ⅅ`,
		dd: `ⅆ`,
		ddagger: `‡`,
		ddarr: `⇊`,
		DDotrahd: `⤑`,
		ddotseq: `⩷`,
		deg: `°`,
		Del: `∇`,
		Delta: `Δ`,
		delta: `δ`,
		demptyv: `⦱`,
		dfisht: `⥿`,
		Dfr: `𝔇`,
		dfr: `𝔡`,
		dHar: `⥥`,
		dharl: `⇃`,
		dharr: `⇂`,
		DiacriticalAcute: `´`,
		DiacriticalDot: `˙`,
		DiacriticalDoubleAcute: `˝`,
		DiacriticalGrave: "`",
		DiacriticalTilde: `˜`,
		diam: `⋄`,
		Diamond: `⋄`,
		diamond: `⋄`,
		diamondsuit: `♦`,
		diams: `♦`,
		die: `¨`,
		DifferentialD: `ⅆ`,
		digamma: `ϝ`,
		disin: `⋲`,
		div: `÷`,
		divide: `÷`,
		divideontimes: `⋇`,
		divonx: `⋇`,
		DJcy: `Ђ`,
		djcy: `ђ`,
		dlcorn: `⌞`,
		dlcrop: `⌍`,
		dollar: `$`,
		Dopf: `𝔻`,
		dopf: `𝕕`,
		Dot: `¨`,
		dot: `˙`,
		DotDot: `⃜`,
		doteq: `≐`,
		doteqdot: `≑`,
		DotEqual: `≐`,
		dotminus: `∸`,
		dotplus: `∔`,
		dotsquare: `⊡`,
		doublebarwedge: `⌆`,
		DoubleContourIntegral: `∯`,
		DoubleDot: `¨`,
		DoubleDownArrow: `⇓`,
		DoubleLeftArrow: `⇐`,
		DoubleLeftRightArrow: `⇔`,
		DoubleLeftTee: `⫤`,
		DoubleLongLeftArrow: `⟸`,
		DoubleLongLeftRightArrow: `⟺`,
		DoubleLongRightArrow: `⟹`,
		DoubleRightArrow: `⇒`,
		DoubleRightTee: `⊨`,
		DoubleUpArrow: `⇑`,
		DoubleUpDownArrow: `⇕`,
		DoubleVerticalBar: `∥`,
		DownArrow: `↓`,
		Downarrow: `⇓`,
		downarrow: `↓`,
		DownArrowBar: `⤓`,
		DownArrowUpArrow: `⇵`,
		DownBreve: `̑`,
		downdownarrows: `⇊`,
		downharpoonleft: `⇃`,
		downharpoonright: `⇂`,
		DownLeftRightVector: `⥐`,
		DownLeftTeeVector: `⥞`,
		DownLeftVector: `↽`,
		DownLeftVectorBar: `⥖`,
		DownRightTeeVector: `⥟`,
		DownRightVector: `⇁`,
		DownRightVectorBar: `⥗`,
		DownTee: `⊤`,
		DownTeeArrow: `↧`,
		drbkarow: `⤐`,
		drcorn: `⌟`,
		drcrop: `⌌`,
		Dscr: `𝒟`,
		dscr: `𝒹`,
		DScy: `Ѕ`,
		dscy: `ѕ`,
		dsol: `⧶`,
		Dstrok: `Đ`,
		dstrok: `đ`,
		dtdot: `⋱`,
		dtri: `▿`,
		dtrif: `▾`,
		duarr: `⇵`,
		duhar: `⥯`,
		dwangle: `⦦`,
		DZcy: `Џ`,
		dzcy: `џ`,
		dzigrarr: `⟿`,
		Eacute: `É`,
		eacute: `é`,
		easter: `⩮`,
		Ecaron: `Ě`,
		ecaron: `ě`,
		ecir: `≖`,
		Ecirc: `Ê`,
		ecirc: `ê`,
		ecolon: `≕`,
		Ecy: `Э`,
		ecy: `э`,
		eDDot: `⩷`,
		Edot: `Ė`,
		eDot: `≑`,
		edot: `ė`,
		ee: `ⅇ`,
		efDot: `≒`,
		Efr: `𝔈`,
		efr: `𝔢`,
		eg: `⪚`,
		Egrave: `È`,
		egrave: `è`,
		egs: `⪖`,
		egsdot: `⪘`,
		el: `⪙`,
		Element: `∈`,
		elinters: `⏧`,
		ell: `ℓ`,
		els: `⪕`,
		elsdot: `⪗`,
		Emacr: `Ē`,
		emacr: `ē`,
		empty: `∅`,
		emptyset: `∅`,
		EmptySmallSquare: `◻`,
		emptyv: `∅`,
		EmptyVerySmallSquare: `▫`,
		emsp: ` `,
		emsp13: ` `,
		emsp14: ` `,
		ENG: `Ŋ`,
		eng: `ŋ`,
		ensp: ` `,
		Eogon: `Ę`,
		eogon: `ę`,
		Eopf: `𝔼`,
		eopf: `𝕖`,
		epar: `⋕`,
		eparsl: `⧣`,
		eplus: `⩱`,
		epsi: `ε`,
		Epsilon: `Ε`,
		epsilon: `ε`,
		epsiv: `ϵ`,
		eqcirc: `≖`,
		eqcolon: `≕`,
		eqsim: `≂`,
		eqslantgtr: `⪖`,
		eqslantless: `⪕`,
		Equal: `⩵`,
		equals: `=`,
		EqualTilde: `≂`,
		equest: `≟`,
		Equilibrium: `⇌`,
		equiv: `≡`,
		equivDD: `⩸`,
		eqvparsl: `⧥`,
		erarr: `⥱`,
		erDot: `≓`,
		Escr: `ℰ`,
		escr: `ℯ`,
		esdot: `≐`,
		Esim: `⩳`,
		esim: `≂`,
		Eta: `Η`,
		eta: `η`,
		ETH: `Ð`,
		eth: `ð`,
		Euml: `Ë`,
		euml: `ë`,
		euro: `€`,
		excl: `!`,
		exist: `∃`,
		Exists: `∃`,
		expectation: `ℰ`,
		ExponentialE: `ⅇ`,
		exponentiale: `ⅇ`,
		fallingdotseq: `≒`,
		Fcy: `Ф`,
		fcy: `ф`,
		female: `♀`,
		ffilig: `ﬃ`,
		fflig: `ﬀ`,
		ffllig: `ﬄ`,
		Ffr: `𝔉`,
		ffr: `𝔣`,
		filig: `ﬁ`,
		FilledSmallSquare: `◼`,
		FilledVerySmallSquare: `▪`,
		fjlig: `fj`,
		flat: `♭`,
		fllig: `ﬂ`,
		fltns: `▱`,
		fnof: `ƒ`,
		Fopf: `𝔽`,
		fopf: `𝕗`,
		ForAll: `∀`,
		forall: `∀`,
		fork: `⋔`,
		forkv: `⫙`,
		Fouriertrf: `ℱ`,
		fpartint: `⨍`,
		frac12: `½`,
		frac13: `⅓`,
		frac14: `¼`,
		frac15: `⅕`,
		frac16: `⅙`,
		frac18: `⅛`,
		frac23: `⅔`,
		frac25: `⅖`,
		frac34: `¾`,
		frac35: `⅗`,
		frac38: `⅜`,
		frac45: `⅘`,
		frac56: `⅚`,
		frac58: `⅝`,
		frac78: `⅞`,
		frasl: `⁄`,
		frown: `⌢`,
		Fscr: `ℱ`,
		fscr: `𝒻`,
		gacute: `ǵ`,
		Gamma: `Γ`,
		gamma: `γ`,
		Gammad: `Ϝ`,
		gammad: `ϝ`,
		gap: `⪆`,
		Gbreve: `Ğ`,
		gbreve: `ğ`,
		Gcedil: `Ģ`,
		Gcirc: `Ĝ`,
		gcirc: `ĝ`,
		Gcy: `Г`,
		gcy: `г`,
		Gdot: `Ġ`,
		gdot: `ġ`,
		gE: `≧`,
		ge: `≥`,
		gEl: `⪌`,
		gel: `⋛`,
		geq: `≥`,
		geqq: `≧`,
		geqslant: `⩾`,
		ges: `⩾`,
		gescc: `⪩`,
		gesdot: `⪀`,
		gesdoto: `⪂`,
		gesdotol: `⪄`,
		gesl: `⋛︀`,
		gesles: `⪔`,
		Gfr: `𝔊`,
		gfr: `𝔤`,
		Gg: `⋙`,
		gg: `≫`,
		ggg: `⋙`,
		gimel: `ℷ`,
		GJcy: `Ѓ`,
		gjcy: `ѓ`,
		gl: `≷`,
		gla: `⪥`,
		glE: `⪒`,
		glj: `⪤`,
		gnap: `⪊`,
		gnapprox: `⪊`,
		gnE: `≩`,
		gne: `⪈`,
		gneq: `⪈`,
		gneqq: `≩`,
		gnsim: `⋧`,
		Gopf: `𝔾`,
		gopf: `𝕘`,
		grave: "`",
		GreaterEqual: `≥`,
		GreaterEqualLess: `⋛`,
		GreaterFullEqual: `≧`,
		GreaterGreater: `⪢`,
		GreaterLess: `≷`,
		GreaterSlantEqual: `⩾`,
		GreaterTilde: `≳`,
		Gscr: `𝒢`,
		gscr: `ℊ`,
		gsim: `≳`,
		gsime: `⪎`,
		gsiml: `⪐`,
		Gt: `≫`,
		GT: `>`,
		gt: `>`,
		gtcc: `⪧`,
		gtcir: `⩺`,
		gtdot: `⋗`,
		gtlPar: `⦕`,
		gtquest: `⩼`,
		gtrapprox: `⪆`,
		gtrarr: `⥸`,
		gtrdot: `⋗`,
		gtreqless: `⋛`,
		gtreqqless: `⪌`,
		gtrless: `≷`,
		gtrsim: `≳`,
		gvertneqq: `≩︀`,
		gvnE: `≩︀`,
		Hacek: `ˇ`,
		hairsp: ` `,
		half: `½`,
		hamilt: `ℋ`,
		HARDcy: `Ъ`,
		hardcy: `ъ`,
		hArr: `⇔`,
		harr: `↔`,
		harrcir: `⥈`,
		harrw: `↭`,
		Hat: `^`,
		hbar: `ℏ`,
		Hcirc: `Ĥ`,
		hcirc: `ĥ`,
		hearts: `♥`,
		heartsuit: `♥`,
		hellip: `…`,
		hercon: `⊹`,
		Hfr: `ℌ`,
		hfr: `𝔥`,
		HilbertSpace: `ℋ`,
		hksearow: `⤥`,
		hkswarow: `⤦`,
		hoarr: `⇿`,
		homtht: `∻`,
		hookleftarrow: `↩`,
		hookrightarrow: `↪`,
		Hopf: `ℍ`,
		hopf: `𝕙`,
		horbar: `―`,
		HorizontalLine: `─`,
		Hscr: `ℋ`,
		hscr: `𝒽`,
		hslash: `ℏ`,
		Hstrok: `Ħ`,
		hstrok: `ħ`,
		HumpDownHump: `≎`,
		HumpEqual: `≏`,
		hybull: `⁃`,
		hyphen: `‐`,
		Iacute: `Í`,
		iacute: `í`,
		ic: `⁣`,
		Icirc: `Î`,
		icirc: `î`,
		Icy: `И`,
		icy: `и`,
		Idot: `İ`,
		IEcy: `Е`,
		iecy: `е`,
		iexcl: `¡`,
		iff: `⇔`,
		Ifr: `ℑ`,
		ifr: `𝔦`,
		Igrave: `Ì`,
		igrave: `ì`,
		ii: `ⅈ`,
		iiiint: `⨌`,
		iiint: `∭`,
		iinfin: `⧜`,
		iiota: `℩`,
		IJlig: `Ĳ`,
		ijlig: `ĳ`,
		Im: `ℑ`,
		Imacr: `Ī`,
		imacr: `ī`,
		image: `ℑ`,
		ImaginaryI: `ⅈ`,
		imagline: `ℐ`,
		imagpart: `ℑ`,
		imath: `ı`,
		imof: `⊷`,
		imped: `Ƶ`,
		Implies: `⇒`,
		in: `∈`,
		incare: `℅`,
		infin: `∞`,
		infintie: `⧝`,
		inodot: `ı`,
		Int: `∬`,
		int: `∫`,
		intcal: `⊺`,
		integers: `ℤ`,
		Integral: `∫`,
		intercal: `⊺`,
		Intersection: `⋂`,
		intlarhk: `⨗`,
		intprod: `⨼`,
		InvisibleComma: `⁣`,
		InvisibleTimes: `⁢`,
		IOcy: `Ё`,
		iocy: `ё`,
		Iogon: `Į`,
		iogon: `į`,
		Iopf: `𝕀`,
		iopf: `𝕚`,
		Iota: `Ι`,
		iota: `ι`,
		iprod: `⨼`,
		iquest: `¿`,
		Iscr: `ℐ`,
		iscr: `𝒾`,
		isin: `∈`,
		isindot: `⋵`,
		isinE: `⋹`,
		isins: `⋴`,
		isinsv: `⋳`,
		isinv: `∈`,
		it: `⁢`,
		Itilde: `Ĩ`,
		itilde: `ĩ`,
		Iukcy: `І`,
		iukcy: `і`,
		Iuml: `Ï`,
		iuml: `ï`,
		Jcirc: `Ĵ`,
		jcirc: `ĵ`,
		Jcy: `Й`,
		jcy: `й`,
		Jfr: `𝔍`,
		jfr: `𝔧`,
		jmath: `ȷ`,
		Jopf: `𝕁`,
		jopf: `𝕛`,
		Jscr: `𝒥`,
		jscr: `𝒿`,
		Jsercy: `Ј`,
		jsercy: `ј`,
		Jukcy: `Є`,
		jukcy: `є`,
		Kappa: `Κ`,
		kappa: `κ`,
		kappav: `ϰ`,
		Kcedil: `Ķ`,
		kcedil: `ķ`,
		Kcy: `К`,
		kcy: `к`,
		Kfr: `𝔎`,
		kfr: `𝔨`,
		kgreen: `ĸ`,
		KHcy: `Х`,
		khcy: `х`,
		KJcy: `Ќ`,
		kjcy: `ќ`,
		Kopf: `𝕂`,
		kopf: `𝕜`,
		Kscr: `𝒦`,
		kscr: `𝓀`,
		lAarr: `⇚`,
		Lacute: `Ĺ`,
		lacute: `ĺ`,
		laemptyv: `⦴`,
		lagran: `ℒ`,
		Lambda: `Λ`,
		lambda: `λ`,
		Lang: `⟪`,
		lang: `⟨`,
		langd: `⦑`,
		langle: `⟨`,
		lap: `⪅`,
		Laplacetrf: `ℒ`,
		laquo: `«`,
		Larr: `↞`,
		lArr: `⇐`,
		larr: `←`,
		larrb: `⇤`,
		larrbfs: `⤟`,
		larrfs: `⤝`,
		larrhk: `↩`,
		larrlp: `↫`,
		larrpl: `⤹`,
		larrsim: `⥳`,
		larrtl: `↢`,
		lat: `⪫`,
		lAtail: `⤛`,
		latail: `⤙`,
		late: `⪭`,
		lates: `⪭︀`,
		lBarr: `⤎`,
		lbarr: `⤌`,
		lbbrk: `❲`,
		lbrace: `{`,
		lbrack: `[`,
		lbrke: `⦋`,
		lbrksld: `⦏`,
		lbrkslu: `⦍`,
		Lcaron: `Ľ`,
		lcaron: `ľ`,
		Lcedil: `Ļ`,
		lcedil: `ļ`,
		lceil: `⌈`,
		lcub: `{`,
		Lcy: `Л`,
		lcy: `л`,
		ldca: `⤶`,
		ldquo: `“`,
		ldquor: `„`,
		ldrdhar: `⥧`,
		ldrushar: `⥋`,
		ldsh: `↲`,
		lE: `≦`,
		le: `≤`,
		LeftAngleBracket: `⟨`,
		LeftArrow: `←`,
		Leftarrow: `⇐`,
		leftarrow: `←`,
		LeftArrowBar: `⇤`,
		LeftArrowRightArrow: `⇆`,
		leftarrowtail: `↢`,
		LeftCeiling: `⌈`,
		LeftDoubleBracket: `⟦`,
		LeftDownTeeVector: `⥡`,
		LeftDownVector: `⇃`,
		LeftDownVectorBar: `⥙`,
		LeftFloor: `⌊`,
		leftharpoondown: `↽`,
		leftharpoonup: `↼`,
		leftleftarrows: `⇇`,
		LeftRightArrow: `↔`,
		Leftrightarrow: `⇔`,
		leftrightarrow: `↔`,
		leftrightarrows: `⇆`,
		leftrightharpoons: `⇋`,
		leftrightsquigarrow: `↭`,
		LeftRightVector: `⥎`,
		LeftTee: `⊣`,
		LeftTeeArrow: `↤`,
		LeftTeeVector: `⥚`,
		leftthreetimes: `⋋`,
		LeftTriangle: `⊲`,
		LeftTriangleBar: `⧏`,
		LeftTriangleEqual: `⊴`,
		LeftUpDownVector: `⥑`,
		LeftUpTeeVector: `⥠`,
		LeftUpVector: `↿`,
		LeftUpVectorBar: `⥘`,
		LeftVector: `↼`,
		LeftVectorBar: `⥒`,
		lEg: `⪋`,
		leg: `⋚`,
		leq: `≤`,
		leqq: `≦`,
		leqslant: `⩽`,
		les: `⩽`,
		lescc: `⪨`,
		lesdot: `⩿`,
		lesdoto: `⪁`,
		lesdotor: `⪃`,
		lesg: `⋚︀`,
		lesges: `⪓`,
		lessapprox: `⪅`,
		lessdot: `⋖`,
		lesseqgtr: `⋚`,
		lesseqqgtr: `⪋`,
		LessEqualGreater: `⋚`,
		LessFullEqual: `≦`,
		LessGreater: `≶`,
		lessgtr: `≶`,
		LessLess: `⪡`,
		lesssim: `≲`,
		LessSlantEqual: `⩽`,
		LessTilde: `≲`,
		lfisht: `⥼`,
		lfloor: `⌊`,
		Lfr: `𝔏`,
		lfr: `𝔩`,
		lg: `≶`,
		lgE: `⪑`,
		lHar: `⥢`,
		lhard: `↽`,
		lharu: `↼`,
		lharul: `⥪`,
		lhblk: `▄`,
		LJcy: `Љ`,
		ljcy: `љ`,
		Ll: `⋘`,
		ll: `≪`,
		llarr: `⇇`,
		llcorner: `⌞`,
		Lleftarrow: `⇚`,
		llhard: `⥫`,
		lltri: `◺`,
		Lmidot: `Ŀ`,
		lmidot: `ŀ`,
		lmoust: `⎰`,
		lmoustache: `⎰`,
		lnap: `⪉`,
		lnapprox: `⪉`,
		lnE: `≨`,
		lne: `⪇`,
		lneq: `⪇`,
		lneqq: `≨`,
		lnsim: `⋦`,
		loang: `⟬`,
		loarr: `⇽`,
		lobrk: `⟦`,
		LongLeftArrow: `⟵`,
		Longleftarrow: `⟸`,
		longleftarrow: `⟵`,
		LongLeftRightArrow: `⟷`,
		Longleftrightarrow: `⟺`,
		longleftrightarrow: `⟷`,
		longmapsto: `⟼`,
		LongRightArrow: `⟶`,
		Longrightarrow: `⟹`,
		longrightarrow: `⟶`,
		looparrowleft: `↫`,
		looparrowright: `↬`,
		lopar: `⦅`,
		Lopf: `𝕃`,
		lopf: `𝕝`,
		loplus: `⨭`,
		lotimes: `⨴`,
		lowast: `∗`,
		lowbar: `_`,
		LowerLeftArrow: `↙`,
		LowerRightArrow: `↘`,
		loz: `◊`,
		lozenge: `◊`,
		lozf: `⧫`,
		lpar: `(`,
		lparlt: `⦓`,
		lrarr: `⇆`,
		lrcorner: `⌟`,
		lrhar: `⇋`,
		lrhard: `⥭`,
		lrm: `‎`,
		lrtri: `⊿`,
		lsaquo: `‹`,
		Lscr: `ℒ`,
		lscr: `𝓁`,
		Lsh: `↰`,
		lsh: `↰`,
		lsim: `≲`,
		lsime: `⪍`,
		lsimg: `⪏`,
		lsqb: `[`,
		lsquo: `‘`,
		lsquor: `‚`,
		Lstrok: `Ł`,
		lstrok: `ł`,
		Lt: `≪`,
		LT: `<`,
		lt: `<`,
		ltcc: `⪦`,
		ltcir: `⩹`,
		ltdot: `⋖`,
		lthree: `⋋`,
		ltimes: `⋉`,
		ltlarr: `⥶`,
		ltquest: `⩻`,
		ltri: `◃`,
		ltrie: `⊴`,
		ltrif: `◂`,
		ltrPar: `⦖`,
		lurdshar: `⥊`,
		luruhar: `⥦`,
		lvertneqq: `≨︀`,
		lvnE: `≨︀`,
		macr: `¯`,
		male: `♂`,
		malt: `✠`,
		maltese: `✠`,
		Map: `⤅`,
		map: `↦`,
		mapsto: `↦`,
		mapstodown: `↧`,
		mapstoleft: `↤`,
		mapstoup: `↥`,
		marker: `▮`,
		mcomma: `⨩`,
		Mcy: `М`,
		mcy: `м`,
		mdash: `—`,
		mDDot: `∺`,
		measuredangle: `∡`,
		MediumSpace: ` `,
		Mellintrf: `ℳ`,
		Mfr: `𝔐`,
		mfr: `𝔪`,
		mho: `℧`,
		micro: `µ`,
		mid: `∣`,
		midast: `*`,
		midcir: `⫰`,
		middot: `·`,
		minus: `−`,
		minusb: `⊟`,
		minusd: `∸`,
		minusdu: `⨪`,
		MinusPlus: `∓`,
		mlcp: `⫛`,
		mldr: `…`,
		mnplus: `∓`,
		models: `⊧`,
		Mopf: `𝕄`,
		mopf: `𝕞`,
		mp: `∓`,
		Mscr: `ℳ`,
		mscr: `𝓂`,
		mstpos: `∾`,
		Mu: `Μ`,
		mu: `μ`,
		multimap: `⊸`,
		mumap: `⊸`,
		nabla: `∇`,
		Nacute: `Ń`,
		nacute: `ń`,
		nang: `∠⃒`,
		nap: `≉`,
		napE: `⩰̸`,
		napid: `≋̸`,
		napos: `ŉ`,
		napprox: `≉`,
		natur: `♮`,
		natural: `♮`,
		naturals: `ℕ`,
		nbsp: `\xA0`,
		nbump: `≎̸`,
		nbumpe: `≏̸`,
		ncap: `⩃`,
		Ncaron: `Ň`,
		ncaron: `ň`,
		Ncedil: `Ņ`,
		ncedil: `ņ`,
		ncong: `≇`,
		ncongdot: `⩭̸`,
		ncup: `⩂`,
		Ncy: `Н`,
		ncy: `н`,
		ndash: `–`,
		ne: `≠`,
		nearhk: `⤤`,
		neArr: `⇗`,
		nearr: `↗`,
		nearrow: `↗`,
		nedot: `≐̸`,
		NegativeMediumSpace: `​`,
		NegativeThickSpace: `​`,
		NegativeThinSpace: `​`,
		NegativeVeryThinSpace: `​`,
		nequiv: `≢`,
		nesear: `⤨`,
		nesim: `≂̸`,
		NestedGreaterGreater: `≫`,
		NestedLessLess: `≪`,
		NewLine: `
`,
		nexist: `∄`,
		nexists: `∄`,
		Nfr: `𝔑`,
		nfr: `𝔫`,
		ngE: `≧̸`,
		nge: `≱`,
		ngeq: `≱`,
		ngeqq: `≧̸`,
		ngeqslant: `⩾̸`,
		nges: `⩾̸`,
		nGg: `⋙̸`,
		ngsim: `≵`,
		nGt: `≫⃒`,
		ngt: `≯`,
		ngtr: `≯`,
		nGtv: `≫̸`,
		nhArr: `⇎`,
		nharr: `↮`,
		nhpar: `⫲`,
		ni: `∋`,
		nis: `⋼`,
		nisd: `⋺`,
		niv: `∋`,
		NJcy: `Њ`,
		njcy: `њ`,
		nlArr: `⇍`,
		nlarr: `↚`,
		nldr: `‥`,
		nlE: `≦̸`,
		nle: `≰`,
		nLeftarrow: `⇍`,
		nleftarrow: `↚`,
		nLeftrightarrow: `⇎`,
		nleftrightarrow: `↮`,
		nleq: `≰`,
		nleqq: `≦̸`,
		nleqslant: `⩽̸`,
		nles: `⩽̸`,
		nless: `≮`,
		nLl: `⋘̸`,
		nlsim: `≴`,
		nLt: `≪⃒`,
		nlt: `≮`,
		nltri: `⋪`,
		nltrie: `⋬`,
		nLtv: `≪̸`,
		nmid: `∤`,
		NoBreak: `⁠`,
		NonBreakingSpace: `\xA0`,
		Nopf: `ℕ`,
		nopf: `𝕟`,
		Not: `⫬`,
		not: `¬`,
		NotCongruent: `≢`,
		NotCupCap: `≭`,
		NotDoubleVerticalBar: `∦`,
		NotElement: `∉`,
		NotEqual: `≠`,
		NotEqualTilde: `≂̸`,
		NotExists: `∄`,
		NotGreater: `≯`,
		NotGreaterEqual: `≱`,
		NotGreaterFullEqual: `≧̸`,
		NotGreaterGreater: `≫̸`,
		NotGreaterLess: `≹`,
		NotGreaterSlantEqual: `⩾̸`,
		NotGreaterTilde: `≵`,
		NotHumpDownHump: `≎̸`,
		NotHumpEqual: `≏̸`,
		notin: `∉`,
		notindot: `⋵̸`,
		notinE: `⋹̸`,
		notinva: `∉`,
		notinvb: `⋷`,
		notinvc: `⋶`,
		NotLeftTriangle: `⋪`,
		NotLeftTriangleBar: `⧏̸`,
		NotLeftTriangleEqual: `⋬`,
		NotLess: `≮`,
		NotLessEqual: `≰`,
		NotLessGreater: `≸`,
		NotLessLess: `≪̸`,
		NotLessSlantEqual: `⩽̸`,
		NotLessTilde: `≴`,
		NotNestedGreaterGreater: `⪢̸`,
		NotNestedLessLess: `⪡̸`,
		notni: `∌`,
		notniva: `∌`,
		notnivb: `⋾`,
		notnivc: `⋽`,
		NotPrecedes: `⊀`,
		NotPrecedesEqual: `⪯̸`,
		NotPrecedesSlantEqual: `⋠`,
		NotReverseElement: `∌`,
		NotRightTriangle: `⋫`,
		NotRightTriangleBar: `⧐̸`,
		NotRightTriangleEqual: `⋭`,
		NotSquareSubset: `⊏̸`,
		NotSquareSubsetEqual: `⋢`,
		NotSquareSuperset: `⊐̸`,
		NotSquareSupersetEqual: `⋣`,
		NotSubset: `⊂⃒`,
		NotSubsetEqual: `⊈`,
		NotSucceeds: `⊁`,
		NotSucceedsEqual: `⪰̸`,
		NotSucceedsSlantEqual: `⋡`,
		NotSucceedsTilde: `≿̸`,
		NotSuperset: `⊃⃒`,
		NotSupersetEqual: `⊉`,
		NotTilde: `≁`,
		NotTildeEqual: `≄`,
		NotTildeFullEqual: `≇`,
		NotTildeTilde: `≉`,
		NotVerticalBar: `∤`,
		npar: `∦`,
		nparallel: `∦`,
		nparsl: `⫽⃥`,
		npart: `∂̸`,
		npolint: `⨔`,
		npr: `⊀`,
		nprcue: `⋠`,
		npre: `⪯̸`,
		nprec: `⊀`,
		npreceq: `⪯̸`,
		nrArr: `⇏`,
		nrarr: `↛`,
		nrarrc: `⤳̸`,
		nrarrw: `↝̸`,
		nRightarrow: `⇏`,
		nrightarrow: `↛`,
		nrtri: `⋫`,
		nrtrie: `⋭`,
		nsc: `⊁`,
		nsccue: `⋡`,
		nsce: `⪰̸`,
		Nscr: `𝒩`,
		nscr: `𝓃`,
		nshortmid: `∤`,
		nshortparallel: `∦`,
		nsim: `≁`,
		nsime: `≄`,
		nsimeq: `≄`,
		nsmid: `∤`,
		nspar: `∦`,
		nsqsube: `⋢`,
		nsqsupe: `⋣`,
		nsub: `⊄`,
		nsubE: `⫅̸`,
		nsube: `⊈`,
		nsubset: `⊂⃒`,
		nsubseteq: `⊈`,
		nsubseteqq: `⫅̸`,
		nsucc: `⊁`,
		nsucceq: `⪰̸`,
		nsup: `⊅`,
		nsupE: `⫆̸`,
		nsupe: `⊉`,
		nsupset: `⊃⃒`,
		nsupseteq: `⊉`,
		nsupseteqq: `⫆̸`,
		ntgl: `≹`,
		Ntilde: `Ñ`,
		ntilde: `ñ`,
		ntlg: `≸`,
		ntriangleleft: `⋪`,
		ntrianglelefteq: `⋬`,
		ntriangleright: `⋫`,
		ntrianglerighteq: `⋭`,
		Nu: `Ν`,
		nu: `ν`,
		num: `#`,
		numero: `№`,
		numsp: ` `,
		nvap: `≍⃒`,
		nVDash: `⊯`,
		nVdash: `⊮`,
		nvDash: `⊭`,
		nvdash: `⊬`,
		nvge: `≥⃒`,
		nvgt: `>⃒`,
		nvHarr: `⤄`,
		nvinfin: `⧞`,
		nvlArr: `⤂`,
		nvle: `≤⃒`,
		nvlt: `<⃒`,
		nvltrie: `⊴⃒`,
		nvrArr: `⤃`,
		nvrtrie: `⊵⃒`,
		nvsim: `∼⃒`,
		nwarhk: `⤣`,
		nwArr: `⇖`,
		nwarr: `↖`,
		nwarrow: `↖`,
		nwnear: `⤧`,
		Oacute: `Ó`,
		oacute: `ó`,
		oast: `⊛`,
		ocir: `⊚`,
		Ocirc: `Ô`,
		ocirc: `ô`,
		Ocy: `О`,
		ocy: `о`,
		odash: `⊝`,
		Odblac: `Ő`,
		odblac: `ő`,
		odiv: `⨸`,
		odot: `⊙`,
		odsold: `⦼`,
		OElig: `Œ`,
		oelig: `œ`,
		ofcir: `⦿`,
		Ofr: `𝔒`,
		ofr: `𝔬`,
		ogon: `˛`,
		Ograve: `Ò`,
		ograve: `ò`,
		ogt: `⧁`,
		ohbar: `⦵`,
		ohm: `Ω`,
		oint: `∮`,
		olarr: `↺`,
		olcir: `⦾`,
		olcross: `⦻`,
		oline: `‾`,
		olt: `⧀`,
		Omacr: `Ō`,
		omacr: `ō`,
		Omega: `Ω`,
		omega: `ω`,
		Omicron: `Ο`,
		omicron: `ο`,
		omid: `⦶`,
		ominus: `⊖`,
		Oopf: `𝕆`,
		oopf: `𝕠`,
		opar: `⦷`,
		OpenCurlyDoubleQuote: `“`,
		OpenCurlyQuote: `‘`,
		operp: `⦹`,
		oplus: `⊕`,
		Or: `⩔`,
		or: `∨`,
		orarr: `↻`,
		ord: `⩝`,
		order: `ℴ`,
		orderof: `ℴ`,
		ordf: `ª`,
		ordm: `º`,
		origof: `⊶`,
		oror: `⩖`,
		orslope: `⩗`,
		orv: `⩛`,
		oS: `Ⓢ`,
		Oscr: `𝒪`,
		oscr: `ℴ`,
		Oslash: `Ø`,
		oslash: `ø`,
		osol: `⊘`,
		Otilde: `Õ`,
		otilde: `õ`,
		Otimes: `⨷`,
		otimes: `⊗`,
		otimesas: `⨶`,
		Ouml: `Ö`,
		ouml: `ö`,
		ovbar: `⌽`,
		OverBar: `‾`,
		OverBrace: `⏞`,
		OverBracket: `⎴`,
		OverParenthesis: `⏜`,
		par: `∥`,
		para: `¶`,
		parallel: `∥`,
		parsim: `⫳`,
		parsl: `⫽`,
		part: `∂`,
		PartialD: `∂`,
		Pcy: `П`,
		pcy: `п`,
		percnt: `%`,
		period: `.`,
		permil: `‰`,
		perp: `⊥`,
		pertenk: `‱`,
		Pfr: `𝔓`,
		pfr: `𝔭`,
		Phi: `Φ`,
		phi: `φ`,
		phiv: `ϕ`,
		phmmat: `ℳ`,
		phone: `☎`,
		Pi: `Π`,
		pi: `π`,
		pitchfork: `⋔`,
		piv: `ϖ`,
		planck: `ℏ`,
		planckh: `ℎ`,
		plankv: `ℏ`,
		plus: `+`,
		plusacir: `⨣`,
		plusb: `⊞`,
		pluscir: `⨢`,
		plusdo: `∔`,
		plusdu: `⨥`,
		pluse: `⩲`,
		PlusMinus: `±`,
		plusmn: `±`,
		plussim: `⨦`,
		plustwo: `⨧`,
		pm: `±`,
		Poincareplane: `ℌ`,
		pointint: `⨕`,
		Popf: `ℙ`,
		popf: `𝕡`,
		pound: `£`,
		Pr: `⪻`,
		pr: `≺`,
		prap: `⪷`,
		prcue: `≼`,
		prE: `⪳`,
		pre: `⪯`,
		prec: `≺`,
		precapprox: `⪷`,
		preccurlyeq: `≼`,
		Precedes: `≺`,
		PrecedesEqual: `⪯`,
		PrecedesSlantEqual: `≼`,
		PrecedesTilde: `≾`,
		preceq: `⪯`,
		precnapprox: `⪹`,
		precneqq: `⪵`,
		precnsim: `⋨`,
		precsim: `≾`,
		Prime: `″`,
		prime: `′`,
		primes: `ℙ`,
		prnap: `⪹`,
		prnE: `⪵`,
		prnsim: `⋨`,
		prod: `∏`,
		Product: `∏`,
		profalar: `⌮`,
		profline: `⌒`,
		profsurf: `⌓`,
		prop: `∝`,
		Proportion: `∷`,
		Proportional: `∝`,
		propto: `∝`,
		prsim: `≾`,
		prurel: `⊰`,
		Pscr: `𝒫`,
		pscr: `𝓅`,
		Psi: `Ψ`,
		psi: `ψ`,
		puncsp: ` `,
		Qfr: `𝔔`,
		qfr: `𝔮`,
		qint: `⨌`,
		Qopf: `ℚ`,
		qopf: `𝕢`,
		qprime: `⁗`,
		Qscr: `𝒬`,
		qscr: `𝓆`,
		quaternions: `ℍ`,
		quatint: `⨖`,
		quest: `?`,
		questeq: `≟`,
		QUOT: `"`,
		quot: `"`,
		rAarr: `⇛`,
		race: `∽̱`,
		Racute: `Ŕ`,
		racute: `ŕ`,
		radic: `√`,
		raemptyv: `⦳`,
		Rang: `⟫`,
		rang: `⟩`,
		rangd: `⦒`,
		range: `⦥`,
		rangle: `⟩`,
		raquo: `»`,
		Rarr: `↠`,
		rArr: `⇒`,
		rarr: `→`,
		rarrap: `⥵`,
		rarrb: `⇥`,
		rarrbfs: `⤠`,
		rarrc: `⤳`,
		rarrfs: `⤞`,
		rarrhk: `↪`,
		rarrlp: `↬`,
		rarrpl: `⥅`,
		rarrsim: `⥴`,
		Rarrtl: `⤖`,
		rarrtl: `↣`,
		rarrw: `↝`,
		rAtail: `⤜`,
		ratail: `⤚`,
		ratio: `∶`,
		rationals: `ℚ`,
		RBarr: `⤐`,
		rBarr: `⤏`,
		rbarr: `⤍`,
		rbbrk: `❳`,
		rbrace: `}`,
		rbrack: `]`,
		rbrke: `⦌`,
		rbrksld: `⦎`,
		rbrkslu: `⦐`,
		Rcaron: `Ř`,
		rcaron: `ř`,
		Rcedil: `Ŗ`,
		rcedil: `ŗ`,
		rceil: `⌉`,
		rcub: `}`,
		Rcy: `Р`,
		rcy: `р`,
		rdca: `⤷`,
		rdldhar: `⥩`,
		rdquo: `”`,
		rdquor: `”`,
		rdsh: `↳`,
		Re: `ℜ`,
		real: `ℜ`,
		realine: `ℛ`,
		realpart: `ℜ`,
		reals: `ℝ`,
		rect: `▭`,
		REG: `®`,
		reg: `®`,
		ReverseElement: `∋`,
		ReverseEquilibrium: `⇋`,
		ReverseUpEquilibrium: `⥯`,
		rfisht: `⥽`,
		rfloor: `⌋`,
		Rfr: `ℜ`,
		rfr: `𝔯`,
		rHar: `⥤`,
		rhard: `⇁`,
		rharu: `⇀`,
		rharul: `⥬`,
		Rho: `Ρ`,
		rho: `ρ`,
		rhov: `ϱ`,
		RightAngleBracket: `⟩`,
		RightArrow: `→`,
		Rightarrow: `⇒`,
		rightarrow: `→`,
		RightArrowBar: `⇥`,
		RightArrowLeftArrow: `⇄`,
		rightarrowtail: `↣`,
		RightCeiling: `⌉`,
		RightDoubleBracket: `⟧`,
		RightDownTeeVector: `⥝`,
		RightDownVector: `⇂`,
		RightDownVectorBar: `⥕`,
		RightFloor: `⌋`,
		rightharpoondown: `⇁`,
		rightharpoonup: `⇀`,
		rightleftarrows: `⇄`,
		rightleftharpoons: `⇌`,
		rightrightarrows: `⇉`,
		rightsquigarrow: `↝`,
		RightTee: `⊢`,
		RightTeeArrow: `↦`,
		RightTeeVector: `⥛`,
		rightthreetimes: `⋌`,
		RightTriangle: `⊳`,
		RightTriangleBar: `⧐`,
		RightTriangleEqual: `⊵`,
		RightUpDownVector: `⥏`,
		RightUpTeeVector: `⥜`,
		RightUpVector: `↾`,
		RightUpVectorBar: `⥔`,
		RightVector: `⇀`,
		RightVectorBar: `⥓`,
		ring: `˚`,
		risingdotseq: `≓`,
		rlarr: `⇄`,
		rlhar: `⇌`,
		rlm: `‏`,
		rmoust: `⎱`,
		rmoustache: `⎱`,
		rnmid: `⫮`,
		roang: `⟭`,
		roarr: `⇾`,
		robrk: `⟧`,
		ropar: `⦆`,
		Ropf: `ℝ`,
		ropf: `𝕣`,
		roplus: `⨮`,
		rotimes: `⨵`,
		RoundImplies: `⥰`,
		rpar: `)`,
		rpargt: `⦔`,
		rppolint: `⨒`,
		rrarr: `⇉`,
		Rrightarrow: `⇛`,
		rsaquo: `›`,
		Rscr: `ℛ`,
		rscr: `𝓇`,
		Rsh: `↱`,
		rsh: `↱`,
		rsqb: `]`,
		rsquo: `’`,
		rsquor: `’`,
		rthree: `⋌`,
		rtimes: `⋊`,
		rtri: `▹`,
		rtrie: `⊵`,
		rtrif: `▸`,
		rtriltri: `⧎`,
		RuleDelayed: `⧴`,
		ruluhar: `⥨`,
		rx: `℞`,
		Sacute: `Ś`,
		sacute: `ś`,
		sbquo: `‚`,
		Sc: `⪼`,
		sc: `≻`,
		scap: `⪸`,
		Scaron: `Š`,
		scaron: `š`,
		sccue: `≽`,
		scE: `⪴`,
		sce: `⪰`,
		Scedil: `Ş`,
		scedil: `ş`,
		Scirc: `Ŝ`,
		scirc: `ŝ`,
		scnap: `⪺`,
		scnE: `⪶`,
		scnsim: `⋩`,
		scpolint: `⨓`,
		scsim: `≿`,
		Scy: `С`,
		scy: `с`,
		sdot: `⋅`,
		sdotb: `⊡`,
		sdote: `⩦`,
		searhk: `⤥`,
		seArr: `⇘`,
		searr: `↘`,
		searrow: `↘`,
		sect: `§`,
		semi: `;`,
		seswar: `⤩`,
		setminus: `∖`,
		setmn: `∖`,
		sext: `✶`,
		Sfr: `𝔖`,
		sfr: `𝔰`,
		sfrown: `⌢`,
		sharp: `♯`,
		SHCHcy: `Щ`,
		shchcy: `щ`,
		SHcy: `Ш`,
		shcy: `ш`,
		ShortDownArrow: `↓`,
		ShortLeftArrow: `←`,
		shortmid: `∣`,
		shortparallel: `∥`,
		ShortRightArrow: `→`,
		ShortUpArrow: `↑`,
		shy: `­`,
		Sigma: `Σ`,
		sigma: `σ`,
		sigmaf: `ς`,
		sigmav: `ς`,
		sim: `∼`,
		simdot: `⩪`,
		sime: `≃`,
		simeq: `≃`,
		simg: `⪞`,
		simgE: `⪠`,
		siml: `⪝`,
		simlE: `⪟`,
		simne: `≆`,
		simplus: `⨤`,
		simrarr: `⥲`,
		slarr: `←`,
		SmallCircle: `∘`,
		smallsetminus: `∖`,
		smashp: `⨳`,
		smeparsl: `⧤`,
		smid: `∣`,
		smile: `⌣`,
		smt: `⪪`,
		smte: `⪬`,
		smtes: `⪬︀`,
		SOFTcy: `Ь`,
		softcy: `ь`,
		sol: `/`,
		solb: `⧄`,
		solbar: `⌿`,
		Sopf: `𝕊`,
		sopf: `𝕤`,
		spades: `♠`,
		spadesuit: `♠`,
		spar: `∥`,
		sqcap: `⊓`,
		sqcaps: `⊓︀`,
		sqcup: `⊔`,
		sqcups: `⊔︀`,
		Sqrt: `√`,
		sqsub: `⊏`,
		sqsube: `⊑`,
		sqsubset: `⊏`,
		sqsubseteq: `⊑`,
		sqsup: `⊐`,
		sqsupe: `⊒`,
		sqsupset: `⊐`,
		sqsupseteq: `⊒`,
		squ: `□`,
		Square: `□`,
		square: `□`,
		SquareIntersection: `⊓`,
		SquareSubset: `⊏`,
		SquareSubsetEqual: `⊑`,
		SquareSuperset: `⊐`,
		SquareSupersetEqual: `⊒`,
		SquareUnion: `⊔`,
		squarf: `▪`,
		squf: `▪`,
		srarr: `→`,
		Sscr: `𝒮`,
		sscr: `𝓈`,
		ssetmn: `∖`,
		ssmile: `⌣`,
		sstarf: `⋆`,
		Star: `⋆`,
		star: `☆`,
		starf: `★`,
		straightepsilon: `ϵ`,
		straightphi: `ϕ`,
		strns: `¯`,
		Sub: `⋐`,
		sub: `⊂`,
		subdot: `⪽`,
		subE: `⫅`,
		sube: `⊆`,
		subedot: `⫃`,
		submult: `⫁`,
		subnE: `⫋`,
		subne: `⊊`,
		subplus: `⪿`,
		subrarr: `⥹`,
		Subset: `⋐`,
		subset: `⊂`,
		subseteq: `⊆`,
		subseteqq: `⫅`,
		SubsetEqual: `⊆`,
		subsetneq: `⊊`,
		subsetneqq: `⫋`,
		subsim: `⫇`,
		subsub: `⫕`,
		subsup: `⫓`,
		succ: `≻`,
		succapprox: `⪸`,
		succcurlyeq: `≽`,
		Succeeds: `≻`,
		SucceedsEqual: `⪰`,
		SucceedsSlantEqual: `≽`,
		SucceedsTilde: `≿`,
		succeq: `⪰`,
		succnapprox: `⪺`,
		succneqq: `⪶`,
		succnsim: `⋩`,
		succsim: `≿`,
		SuchThat: `∋`,
		Sum: `∑`,
		sum: `∑`,
		sung: `♪`,
		Sup: `⋑`,
		sup: `⊃`,
		sup1: `¹`,
		sup2: `²`,
		sup3: `³`,
		supdot: `⪾`,
		supdsub: `⫘`,
		supE: `⫆`,
		supe: `⊇`,
		supedot: `⫄`,
		Superset: `⊃`,
		SupersetEqual: `⊇`,
		suphsol: `⟉`,
		suphsub: `⫗`,
		suplarr: `⥻`,
		supmult: `⫂`,
		supnE: `⫌`,
		supne: `⊋`,
		supplus: `⫀`,
		Supset: `⋑`,
		supset: `⊃`,
		supseteq: `⊇`,
		supseteqq: `⫆`,
		supsetneq: `⊋`,
		supsetneqq: `⫌`,
		supsim: `⫈`,
		supsub: `⫔`,
		supsup: `⫖`,
		swarhk: `⤦`,
		swArr: `⇙`,
		swarr: `↙`,
		swarrow: `↙`,
		swnwar: `⤪`,
		szlig: `ß`,
		Tab: `	`,
		target: `⌖`,
		Tau: `Τ`,
		tau: `τ`,
		tbrk: `⎴`,
		Tcaron: `Ť`,
		tcaron: `ť`,
		Tcedil: `Ţ`,
		tcedil: `ţ`,
		Tcy: `Т`,
		tcy: `т`,
		tdot: `⃛`,
		telrec: `⌕`,
		Tfr: `𝔗`,
		tfr: `𝔱`,
		there4: `∴`,
		Therefore: `∴`,
		therefore: `∴`,
		Theta: `Θ`,
		theta: `θ`,
		thetasym: `ϑ`,
		thetav: `ϑ`,
		thickapprox: `≈`,
		thicksim: `∼`,
		ThickSpace: `  `,
		thinsp: ` `,
		ThinSpace: ` `,
		thkap: `≈`,
		thksim: `∼`,
		THORN: `Þ`,
		thorn: `þ`,
		Tilde: `∼`,
		tilde: `˜`,
		TildeEqual: `≃`,
		TildeFullEqual: `≅`,
		TildeTilde: `≈`,
		times: `×`,
		timesb: `⊠`,
		timesbar: `⨱`,
		timesd: `⨰`,
		tint: `∭`,
		toea: `⤨`,
		top: `⊤`,
		topbot: `⌶`,
		topcir: `⫱`,
		Topf: `𝕋`,
		topf: `𝕥`,
		topfork: `⫚`,
		tosa: `⤩`,
		tprime: `‴`,
		TRADE: `™`,
		trade: `™`,
		triangle: `▵`,
		triangledown: `▿`,
		triangleleft: `◃`,
		trianglelefteq: `⊴`,
		triangleq: `≜`,
		triangleright: `▹`,
		trianglerighteq: `⊵`,
		tridot: `◬`,
		trie: `≜`,
		triminus: `⨺`,
		TripleDot: `⃛`,
		triplus: `⨹`,
		trisb: `⧍`,
		tritime: `⨻`,
		trpezium: `⏢`,
		Tscr: `𝒯`,
		tscr: `𝓉`,
		TScy: `Ц`,
		tscy: `ц`,
		TSHcy: `Ћ`,
		tshcy: `ћ`,
		Tstrok: `Ŧ`,
		tstrok: `ŧ`,
		twixt: `≬`,
		twoheadleftarrow: `↞`,
		twoheadrightarrow: `↠`,
		Uacute: `Ú`,
		uacute: `ú`,
		Uarr: `↟`,
		uArr: `⇑`,
		uarr: `↑`,
		Uarrocir: `⥉`,
		Ubrcy: `Ў`,
		ubrcy: `ў`,
		Ubreve: `Ŭ`,
		ubreve: `ŭ`,
		Ucirc: `Û`,
		ucirc: `û`,
		Ucy: `У`,
		ucy: `у`,
		udarr: `⇅`,
		Udblac: `Ű`,
		udblac: `ű`,
		udhar: `⥮`,
		ufisht: `⥾`,
		Ufr: `𝔘`,
		ufr: `𝔲`,
		Ugrave: `Ù`,
		ugrave: `ù`,
		uHar: `⥣`,
		uharl: `↿`,
		uharr: `↾`,
		uhblk: `▀`,
		ulcorn: `⌜`,
		ulcorner: `⌜`,
		ulcrop: `⌏`,
		ultri: `◸`,
		Umacr: `Ū`,
		umacr: `ū`,
		uml: `¨`,
		UnderBar: `_`,
		UnderBrace: `⏟`,
		UnderBracket: `⎵`,
		UnderParenthesis: `⏝`,
		Union: `⋃`,
		UnionPlus: `⊎`,
		Uogon: `Ų`,
		uogon: `ų`,
		Uopf: `𝕌`,
		uopf: `𝕦`,
		UpArrow: `↑`,
		Uparrow: `⇑`,
		uparrow: `↑`,
		UpArrowBar: `⤒`,
		UpArrowDownArrow: `⇅`,
		UpDownArrow: `↕`,
		Updownarrow: `⇕`,
		updownarrow: `↕`,
		UpEquilibrium: `⥮`,
		upharpoonleft: `↿`,
		upharpoonright: `↾`,
		uplus: `⊎`,
		UpperLeftArrow: `↖`,
		UpperRightArrow: `↗`,
		Upsi: `ϒ`,
		upsi: `υ`,
		upsih: `ϒ`,
		Upsilon: `Υ`,
		upsilon: `υ`,
		UpTee: `⊥`,
		UpTeeArrow: `↥`,
		upuparrows: `⇈`,
		urcorn: `⌝`,
		urcorner: `⌝`,
		urcrop: `⌎`,
		Uring: `Ů`,
		uring: `ů`,
		urtri: `◹`,
		Uscr: `𝒰`,
		uscr: `𝓊`,
		utdot: `⋰`,
		Utilde: `Ũ`,
		utilde: `ũ`,
		utri: `▵`,
		utrif: `▴`,
		uuarr: `⇈`,
		Uuml: `Ü`,
		uuml: `ü`,
		uwangle: `⦧`,
		vangrt: `⦜`,
		varepsilon: `ϵ`,
		varkappa: `ϰ`,
		varnothing: `∅`,
		varphi: `ϕ`,
		varpi: `ϖ`,
		varpropto: `∝`,
		vArr: `⇕`,
		varr: `↕`,
		varrho: `ϱ`,
		varsigma: `ς`,
		varsubsetneq: `⊊︀`,
		varsubsetneqq: `⫋︀`,
		varsupsetneq: `⊋︀`,
		varsupsetneqq: `⫌︀`,
		vartheta: `ϑ`,
		vartriangleleft: `⊲`,
		vartriangleright: `⊳`,
		Vbar: `⫫`,
		vBar: `⫨`,
		vBarv: `⫩`,
		Vcy: `В`,
		vcy: `в`,
		VDash: `⊫`,
		Vdash: `⊩`,
		vDash: `⊨`,
		vdash: `⊢`,
		Vdashl: `⫦`,
		Vee: `⋁`,
		vee: `∨`,
		veebar: `⊻`,
		veeeq: `≚`,
		vellip: `⋮`,
		Verbar: `‖`,
		verbar: `|`,
		Vert: `‖`,
		vert: `|`,
		VerticalBar: `∣`,
		VerticalLine: `|`,
		VerticalSeparator: `❘`,
		VerticalTilde: `≀`,
		VeryThinSpace: ` `,
		Vfr: `𝔙`,
		vfr: `𝔳`,
		vltri: `⊲`,
		vnsub: `⊂⃒`,
		vnsup: `⊃⃒`,
		Vopf: `𝕍`,
		vopf: `𝕧`,
		vprop: `∝`,
		vrtri: `⊳`,
		Vscr: `𝒱`,
		vscr: `𝓋`,
		vsubnE: `⫋︀`,
		vsubne: `⊊︀`,
		vsupnE: `⫌︀`,
		vsupne: `⊋︀`,
		Vvdash: `⊪`,
		vzigzag: `⦚`,
		Wcirc: `Ŵ`,
		wcirc: `ŵ`,
		wedbar: `⩟`,
		Wedge: `⋀`,
		wedge: `∧`,
		wedgeq: `≙`,
		weierp: `℘`,
		Wfr: `𝔚`,
		wfr: `𝔴`,
		Wopf: `𝕎`,
		wopf: `𝕨`,
		wp: `℘`,
		wr: `≀`,
		wreath: `≀`,
		Wscr: `𝒲`,
		wscr: `𝓌`,
		xcap: `⋂`,
		xcirc: `◯`,
		xcup: `⋃`,
		xdtri: `▽`,
		Xfr: `𝔛`,
		xfr: `𝔵`,
		xhArr: `⟺`,
		xharr: `⟷`,
		Xi: `Ξ`,
		xi: `ξ`,
		xlArr: `⟸`,
		xlarr: `⟵`,
		xmap: `⟼`,
		xnis: `⋻`,
		xodot: `⨀`,
		Xopf: `𝕏`,
		xopf: `𝕩`,
		xoplus: `⨁`,
		xotime: `⨂`,
		xrArr: `⟹`,
		xrarr: `⟶`,
		Xscr: `𝒳`,
		xscr: `𝓍`,
		xsqcup: `⨆`,
		xuplus: `⨄`,
		xutri: `△`,
		xvee: `⋁`,
		xwedge: `⋀`,
		Yacute: `Ý`,
		yacute: `ý`,
		YAcy: `Я`,
		yacy: `я`,
		Ycirc: `Ŷ`,
		ycirc: `ŷ`,
		Ycy: `Ы`,
		ycy: `ы`,
		yen: `¥`,
		Yfr: `𝔜`,
		yfr: `𝔶`,
		YIcy: `Ї`,
		yicy: `ї`,
		Yopf: `𝕐`,
		yopf: `𝕪`,
		Yscr: `𝒴`,
		yscr: `𝓎`,
		YUcy: `Ю`,
		yucy: `ю`,
		Yuml: `Ÿ`,
		yuml: `ÿ`,
		Zacute: `Ź`,
		zacute: `ź`,
		Zcaron: `Ž`,
		zcaron: `ž`,
		Zcy: `З`,
		zcy: `з`,
		Zdot: `Ż`,
		zdot: `ż`,
		zeetrf: `ℨ`,
		ZeroWidthSpace: `​`,
		Zeta: `Ζ`,
		zeta: `ζ`,
		Zfr: `ℨ`,
		zfr: `𝔷`,
		ZHcy: `Ж`,
		zhcy: `ж`,
		zigrarr: `⇝`,
		Zopf: `ℤ`,
		zopf: `𝕫`,
		Zscr: `𝒵`,
		zscr: `𝓏`,
		zwj: `‍`,
		zwnj: `‌`
	}), exports.entityMap = exports.HTML_ENTITIES;
})), i = o$1(((exports) => {
	var n = t().NAMESPACE, r = /[A-Z_a-z\xC0-\xD6\xD8-\xF6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD]/, i = RegExp(`[\\-\\.0-9` + r.source.slice(1, -1) + `\\u00B7\\u0300-\\u036F\\u203F-\\u2040]`), a = RegExp(`^` + r.source + i.source + `*(?::` + r.source + i.source + `*)?$`), o = 0, s = 1, c = 2, l = 3, u = 4, d = 5, f = 6, p = 7;
	function m(e, t) {
		this.message = e, this.locator = t, Error.captureStackTrace && Error.captureStackTrace(this, m);
	}
	m.prototype = Error(), m.prototype.name = m.name;
	function h() {}
	h.prototype = { parse: function(e, t, n) {
		var r = this.domBuilder;
		r.startDocument(), S(t, t = {}), g(e, t, n, r, this.errorHandler), r.endDocument();
	} };
	function g(e, t, r, i, a) {
		function o(e) {
			if (e > 65535) {
				e -= 65536;
				var t = 55296 + (e >> 10), n = 56320 + (e & 1023);
				return String.fromCharCode(t, n);
			} else return String.fromCharCode(e);
		}
		function s(e) {
			var t = e.slice(1, -1);
			return Object.hasOwnProperty.call(r, t) ? r[t] : t.charAt(0) === `#` ? o(parseInt(t.substr(1).replace(`x`, `0x`))) : (a.error(`entity not found:` + e), e);
		}
		function c(t) {
			if (t > S) {
				var n = e.substring(S, t).replace(/&#?\w+;/g, s);
				p && l(S), i.characters(n, 0, t - S), S = t;
			}
		}
		function l(t, n) {
			for (; t >= d && (n = f.exec(e));) u = n.index, d = u + n[0].length, p.lineNumber++;
			p.columnNumber = t - u + 1;
		}
		for (var u = 0, d = 0, f = /.*(?:\r\n?|\n)|.*$/g, p = i.locator, h = [{ currentNSMap: t }], g = {}, S = 0;;) {
			try {
				var E = e.indexOf(`<`, S);
				if (E < 0) {
					if (!e.substr(S).match(/^\s*$/)) {
						var D = i.doc, O = D.createTextNode(e.substr(S));
						D.appendChild(O), i.currentElement = O;
					}
					return;
				}
				switch (E > S && c(E), e.charAt(E + 1)) {
					case `/`:
						var k = e.indexOf(`>`, E + 3), A = e.substring(E + 2, k).replace(/[ \t\n\r]+$/g, ``), j = h.pop();
						k < 0 ? (A = e.substring(E + 2).replace(/[\s<].*/, ``), a.error(`end tag name: ` + A + ` is not complete:` + j.tagName), k = E + 1 + A.length) : A.match(/\s</) && (A = A.replace(/[\s<].*/, ``), a.error(`end tag name: ` + A + ` maybe not complete`), k = E + 1 + A.length);
						var M = j.localNSMap, N = j.tagName == A;
						if (N || j.tagName && j.tagName.toLowerCase() == A.toLowerCase()) {
							if (i.endElement(j.uri, j.localName, A), M) for (var P in M) Object.prototype.hasOwnProperty.call(M, P) && i.endPrefixMapping(P);
							N || a.fatalError(`end tag name: ` + A + ` is not match the current start tagName:` + j.tagName);
						} else h.push(j);
						k++;
						break;
					case `?`:
						p && l(E), k = w(e, E, i);
						break;
					case `!`:
						p && l(E), k = C(e, E, i, a);
						break;
					default:
						p && l(E);
						var F = new T(), I = h[h.length - 1].currentNSMap, k = v(e, E, F, I, s, a), L = F.length;
						if (!F.closed && x(e, k, F.tagName, g) && (F.closed = !0, r.nbsp || a.warning(`unclosed xml attribute`)), p && L) {
							for (var R = _(p, {}), z = 0; z < L; z++) {
								var B = F[z];
								l(B.offset), B.locator = _(p, {});
							}
							i.locator = R, y(F, i, I) && h.push(F), i.locator = p;
						} else y(F, i, I) && h.push(F);
						n.isHTML(F.uri) && !F.closed ? k = b(e, k, F.tagName, s, i) : k++;
				}
			} catch (e) {
				if (e instanceof m) throw e;
				a.error(`element parse error: ` + e), k = -1;
			}
			k > S ? S = k : c(Math.max(E, S) + 1);
		}
	}
	function _(e, t) {
		return t.lineNumber = e.lineNumber, t.columnNumber = e.columnNumber, t;
	}
	function v(e, t, r, i, a, m) {
		function h(e, t, n) {
			r.attributeNames.hasOwnProperty(e) && m.fatalError(`Attribute ` + e + ` redefined`), r.addValue(e, t.replace(/[\t\n\r]/g, ` `).replace(/&#?\w+;/g, a), n);
		}
		for (var g, _, v = ++t, y = o;;) {
			var b = e.charAt(v);
			switch (b) {
				case `=`:
					if (y === s) g = e.slice(t, v), y = l;
					else if (y === c) y = l;
					else throw Error(`attribute equal must after attrName`);
					break;
				case `'`:
				case `"`:
					if (y === l || y === s) if (y === s && (m.warning(`attribute value must after "="`), g = e.slice(t, v)), t = v + 1, v = e.indexOf(b, t), v > 0) _ = e.slice(t, v), h(g, _, t - 1), y = d;
					else throw Error(`attribute value no end '` + b + `' match`);
					else if (y == u) _ = e.slice(t, v), h(g, _, t), m.warning(`attribute "` + g + `" missed start quot(` + b + `)!!`), t = v + 1, y = d;
					else throw Error(`attribute value must after "="`);
					break;
				case `/`:
					switch (y) {
						case o: r.setTagName(e.slice(t, v));
						case d:
						case f:
						case p: y = p, r.closed = !0;
						case u:
						case s: break;
						case c:
							r.closed = !0;
							break;
						default: throw Error(`attribute invalid close char('/')`);
					}
					break;
				case ``: return m.error(`unexpected end of input`), y == o && r.setTagName(e.slice(t, v)), v;
				case `>`:
					switch (y) {
						case o: r.setTagName(e.slice(t, v));
						case d:
						case f:
						case p: break;
						case u:
						case s: _ = e.slice(t, v), _.slice(-1) === `/` && (r.closed = !0, _ = _.slice(0, -1));
						case c:
							y === c && (_ = g), y == u ? (m.warning(`attribute "` + _ + `" missed quot(")!`), h(g, _, t)) : ((!n.isHTML(i[``]) || !_.match(/^(?:disabled|checked|selected)$/i)) && m.warning(`attribute "` + _ + `" missed value!! "` + _ + `" instead!!`), h(_, _, t));
							break;
						case l: throw Error(`attribute value missed!!`);
					}
					return v;
				case ``: b = ` `;
				default: if (b <= ` `) switch (y) {
					case o:
						r.setTagName(e.slice(t, v)), y = f;
						break;
					case s:
						g = e.slice(t, v), y = c;
						break;
					case u:
						var _ = e.slice(t, v);
						m.warning(`attribute "` + _ + `" missed quot(")!!`), h(g, _, t);
					case d:
						y = f;
						break;
				}
				else switch (y) {
					case c:
						r.tagName, (!n.isHTML(i[``]) || !g.match(/^(?:disabled|checked|selected)$/i)) && m.warning(`attribute "` + g + `" missed value!! "` + g + `" instead2!!`), h(g, g, t), t = v, y = s;
						break;
					case d: m.warning(`attribute space is required"` + g + `"!!`);
					case f:
						y = s, t = v;
						break;
					case l:
						y = u, t = v;
						break;
					case p: throw Error(`elements closed character '/' and '>' must be connected to`);
				}
			}
			v++;
		}
	}
	function y(e, t, r) {
		for (var i = e.tagName, a = null, o = e.length; o--;) {
			var s = e[o], c = s.qName, l = s.value, u = c.indexOf(`:`);
			if (u > 0) var d = s.prefix = c.slice(0, u), f = c.slice(u + 1), p = d === `xmlns` && f;
			else f = c, d = null, p = c === `xmlns` && ``;
			s.localName = f, p !== !1 && (a ?? (a = {}, S(r, r = {})), r[p] = a[p] = l, s.uri = n.XMLNS, t.startPrefixMapping(p, l));
		}
		for (var o = e.length; o--;) {
			s = e[o];
			var d = s.prefix;
			d && (d === `xml` && (s.uri = n.XML), d !== `xmlns` && (s.uri = r[d || ``]));
		}
		var u = i.indexOf(`:`);
		u > 0 ? (d = e.prefix = i.slice(0, u), f = e.localName = i.slice(u + 1)) : (d = null, f = e.localName = i);
		var m = e.uri = r[d || ``];
		if (t.startElement(m, f, i, e), e.closed) {
			if (t.endElement(m, f, i), a) for (d in a) Object.prototype.hasOwnProperty.call(a, d) && t.endPrefixMapping(d);
		} else return e.currentNSMap = r, e.localNSMap = a, !0;
	}
	function b(e, t, n, r, i) {
		if (/^(?:script|textarea)$/i.test(n)) {
			var a = e.indexOf(`</` + n + `>`, t), o = e.substring(t + 1, a);
			if (/[&<]/.test(o)) return /^script$/i.test(n) ? (i.characters(o, 0, o.length), a) : (o = o.replace(/&#?\w+;/g, r), i.characters(o, 0, o.length), a);
		}
		return t + 1;
	}
	function x(e, t, n, r) {
		var i = r[n];
		return i ?? (i = e.lastIndexOf(`</` + n + `>`), i < t && (i = e.lastIndexOf(`</` + n)), r[n] = i), i < t;
	}
	function S(e, t) {
		for (var n in e) Object.prototype.hasOwnProperty.call(e, n) && (t[n] = e[n]);
	}
	function C(e, t, n, r) {
		switch (e.charAt(t + 2)) {
			case `-`: if (e.charAt(t + 3) === `-`) {
				var i = e.indexOf(`-->`, t + 4);
				return i > t ? (n.comment(e, t + 4, i - t - 4), i + 3) : (r.error(`Unclosed comment`), -1);
			} else return -1;
			default:
				if (e.substr(t + 3, 6) == `CDATA[`) {
					var i = e.indexOf(`]]>`, t + 9);
					return n.startCDATA(), n.characters(e, t + 9, i - t - 9), n.endCDATA(), i + 3;
				}
				var a = E(e, t), o = a.length;
				if (o > 1 && /!doctype/i.test(a[0][0])) {
					var s = a[1][0], c = !1, l = !1;
					o > 3 && (/^public$/i.test(a[2][0]) ? (c = a[3][0], l = o > 4 && a[4][0]) : /^system$/i.test(a[2][0]) && (l = a[3][0]));
					var u = a[o - 1];
					return n.startDTD(s, c, l), n.endDTD(), u.index + u[0].length;
				}
		}
		return -1;
	}
	function w(e, t, n) {
		var r = e.indexOf(`?>`, t);
		if (r) {
			var i = e.substring(t, r).match(/^<\?(\S*)\s*([\s\S]*?)\s*$/);
			return i ? (i[0].length, n.processingInstruction(i[1], i[2]), r + 2) : -1;
		}
		return -1;
	}
	function T() {
		this.attributeNames = {};
	}
	T.prototype = {
		setTagName: function(e) {
			if (!a.test(e)) throw Error(`invalid tagName:` + e);
			this.tagName = e;
		},
		addValue: function(e, t, n) {
			if (!a.test(e)) throw Error(`invalid attribute:` + e);
			this.attributeNames[e] = this.length, this[this.length++] = {
				qName: e,
				value: t,
				offset: n
			};
		},
		length: 0,
		getLocalName: function(e) {
			return this[e].localName;
		},
		getLocator: function(e) {
			return this[e].locator;
		},
		getQName: function(e) {
			return this[e].qName;
		},
		getURI: function(e) {
			return this[e].uri;
		},
		getValue: function(e) {
			return this[e].value;
		}
	};
	function E(e, t) {
		var n, r = [], i = /'[^']+'|"[^"]+"|[^\s<>\/=]+=?|(\/?\s*>|<)/g;
		for (i.lastIndex = t, i.exec(e); n = i.exec(e);) if (r.push(n), n[1]) return r;
	}
	exports.XMLReader = h, exports.ParseError = m;
})), a = o$1(((exports) => {
	var a = t(), o = n(), s = r(), c = i(), l = o.DOMImplementation, u = a.NAMESPACE, d = c.ParseError, f = c.XMLReader;
	function p(e) {
		return e.replace(/\r[\n\u0085]/g, `
`).replace(/[\r\u0085\u2028]/g, `
`);
	}
	function m(e) {
		this.options = e || { locator: {} };
	}
	m.prototype.parseFromString = function(e, t) {
		var n = this.options, r = new f(), i = n.domBuilder || new g(), a = n.errorHandler, o = n.locator, c = n.xmlns || {}, l = /\/x?html?$/.test(t), d = l ? s.HTML_ENTITIES : s.XML_ENTITIES;
		o && i.setDocumentLocator(o), r.errorHandler = h(a, i, o), r.domBuilder = n.domBuilder || i, l && (c[``] = u.HTML), c.xml = c.xml || u.XML;
		var m = n.normalizeLineEndings || p;
		return e && typeof e == `string` ? r.parse(m(e), c, d) : r.errorHandler.error(`invalid doc source`), i.doc;
	};
	function h(e, t, n) {
		if (!e) {
			if (t instanceof g) return t;
			e = t;
		}
		var r = {}, i = e instanceof Function;
		n ||= {};
		function a(t) {
			var a = e[t];
			!a && i && (a = e.length == 2 ? function(n) {
				e(t, n);
			} : e), r[t] = a && function(e) {
				a(`[xmldom ` + t + `]	` + e + v(n));
			} || function() {};
		}
		return a(`warning`), a(`error`), a(`fatalError`), r;
	}
	function g() {
		this.cdata = !1;
	}
	function _(e, t) {
		t.lineNumber = e.lineNumber, t.columnNumber = e.columnNumber;
	}
	g.prototype = {
		startDocument: function() {
			this.doc = new l().createDocument(null, null, null), this.locator && (this.doc.documentURI = this.locator.systemId);
		},
		startElement: function(e, t, n, r) {
			var i = this.doc, a = i.createElementNS(e, n || t), o = r.length;
			b(this, a), this.currentElement = a, this.locator && _(this.locator, a);
			for (var s = 0; s < o; s++) {
				var e = r.getURI(s), c = r.getValue(s), n = r.getQName(s), l = i.createAttributeNS(e, n);
				this.locator && _(r.getLocator(s), l), l.value = l.nodeValue = c, a.setAttributeNode(l);
			}
		},
		endElement: function(e, t, n) {
			var r = this.currentElement;
			r.tagName, this.currentElement = r.parentNode;
		},
		startPrefixMapping: function(e, t) {},
		endPrefixMapping: function(e) {},
		processingInstruction: function(e, t) {
			var n = this.doc.createProcessingInstruction(e, t);
			this.locator && _(this.locator, n), b(this, n);
		},
		ignorableWhitespace: function(e, t, n) {},
		characters: function(e, t, n) {
			if (e = y.apply(this, arguments), e) {
				if (this.cdata) var r = this.doc.createCDATASection(e);
				else var r = this.doc.createTextNode(e);
				this.currentElement ? this.currentElement.appendChild(r) : /^\s*$/.test(e) && this.doc.appendChild(r), this.locator && _(this.locator, r);
			}
		},
		skippedEntity: function(e) {},
		endDocument: function() {
			this.doc.normalize();
		},
		setDocumentLocator: function(e) {
			(this.locator = e) && (e.lineNumber = 0);
		},
		comment: function(e, t, n) {
			e = y.apply(this, arguments);
			var r = this.doc.createComment(e);
			this.locator && _(this.locator, r), b(this, r);
		},
		startCDATA: function() {
			this.cdata = !0;
		},
		endCDATA: function() {
			this.cdata = !1;
		},
		startDTD: function(e, t, n) {
			var r = this.doc.implementation;
			if (r && r.createDocumentType) {
				var i = r.createDocumentType(e, t, n);
				this.locator && _(this.locator, i), b(this, i), this.doc.doctype = i;
			}
		},
		warning: function(e) {
			console.warn(`[xmldom warning]	` + e, v(this.locator));
		},
		error: function(e) {
			console.error(`[xmldom error]	` + e, v(this.locator));
		},
		fatalError: function(e) {
			throw new d(e, this.locator);
		}
	};
	function v(e) {
		if (e) return `
@` + (e.systemId || ``) + `#[line:` + e.lineNumber + `,col:` + e.columnNumber + `]`;
	}
	function y(e, t, n) {
		return typeof e == `string` ? e.substr(t, n) : e.length >= t + n || t ? new java.lang.String(e, t, n) + `` : e;
	}
	`endDTD,startEntity,endEntity,attributeDecl,elementDecl,externalEntityDecl,internalEntityDecl,resolveEntity,getExternalSubset,notationDecl,unparsedEntityDecl`.replace(/\w+/g, function(e) {
		g.prototype[e] = function() {
			return null;
		};
	});
	function b(e, t) {
		e.currentElement ? e.currentElement.appendChild(t) : e.doc.appendChild(t);
	}
	exports.__DOMHandler = g, exports.normalizeLineEndings = p, exports.DOMParser = m;
}));
var lib_CBtriEt5_default = o$1(((exports) => {
	var t = n();
	exports.DOMImplementation = t.DOMImplementation, exports.XMLSerializer = t.XMLSerializer, exports.DOMParser = a().DOMParser;
}))();
//#endregion
export { lib_CBtriEt5_default as default };

//# sourceMappingURL=lib-CBtriEt5.js.map