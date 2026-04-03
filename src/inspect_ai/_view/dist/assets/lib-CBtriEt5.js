import { o as o$1 } from "./chunk-DfAF0w94.js";
var t = o$1(((exports$1) => {
  function t2(e, t3, n3) {
    if (n3 === void 0 && (n3 = Array.prototype), e && typeof n3.find == `function`) return n3.find.call(e, t3);
    for (var r3 = 0; r3 < e.length; r3++) if (Object.prototype.hasOwnProperty.call(e, r3)) {
      var i3 = e[r3];
      if (t3.call(void 0, i3, r3, e)) return i3;
    }
  }
  function n2(e, t3) {
    return t3 === void 0 && (t3 = Object), t3 && typeof t3.freeze == `function` ? t3.freeze(e) : e;
  }
  function r2(e, t3) {
    if (typeof e != `object` || !e) throw TypeError(`target is not an object`);
    for (var n3 in t3) Object.prototype.hasOwnProperty.call(t3, n3) && (e[n3] = t3[n3]);
    return e;
  }
  var i2 = n2({ HTML: `text/html`, isHTML: function(e) {
    return e === i2.HTML;
  }, XML_APPLICATION: `application/xml`, XML_TEXT: `text/xml`, XML_XHTML_APPLICATION: `application/xhtml+xml`, XML_SVG_IMAGE: `image/svg+xml` }), a2 = n2({ HTML: `http://www.w3.org/1999/xhtml`, isHTML: function(e) {
    return e === a2.HTML;
  }, SVG: `http://www.w3.org/2000/svg`, XML: `http://www.w3.org/XML/1998/namespace`, XMLNS: `http://www.w3.org/2000/xmlns/` });
  exports$1.assign = r2, exports$1.find = t2, exports$1.freeze = n2, exports$1.MIME_TYPE = i2, exports$1.NAMESPACE = a2;
})), n = o$1(((exports$1) => {
  var n2 = t(), r2 = n2.find, i2 = n2.NAMESPACE;
  function a2(e) {
    return e !== ``;
  }
  function o2(e) {
    return e ? e.split(/[\t\n\f\r ]+/).filter(a2) : [];
  }
  function s(e, t2) {
    return e.hasOwnProperty(t2) || (e[t2] = true), e;
  }
  function c(e) {
    if (!e) return [];
    var t2 = o2(e);
    return Object.keys(t2.reduce(s, {}));
  }
  function l(e) {
    return function(t2) {
      return e && e.indexOf(t2) !== -1;
    };
  }
  function u(e, t2) {
    for (var n3 in e) Object.prototype.hasOwnProperty.call(e, n3) && (t2[n3] = e[n3]);
  }
  function d(e, t2) {
    var n3 = e.prototype;
    if (!(n3 instanceof t2)) {
      let r3 = function() {
      };
      r3.prototype = t2.prototype, r3 = new r3(), u(n3, r3), e.prototype = n3 = r3;
    }
    n3.constructor != e && (typeof e != `function` && console.error(`unknown Class:` + e), n3.constructor = e);
  }
  var f = {}, p = f.ELEMENT_NODE = 1, m = f.ATTRIBUTE_NODE = 2, h = f.TEXT_NODE = 3, g = f.CDATA_SECTION_NODE = 4, _ = f.ENTITY_REFERENCE_NODE = 5, v = f.ENTITY_NODE = 6, y = f.PROCESSING_INSTRUCTION_NODE = 7, b = f.COMMENT_NODE = 8, x = f.DOCUMENT_NODE = 9, S = f.DOCUMENT_TYPE_NODE = 10, C = f.DOCUMENT_FRAGMENT_NODE = 11, w = f.NOTATION_NODE = 12, T = {}, E = {};
  T.INDEX_SIZE_ERR = (E[1] = `Index size error`, 1), T.DOMSTRING_SIZE_ERR = (E[2] = `DOMString size error`, 2);
  var D = T.HIERARCHY_REQUEST_ERR = (E[3] = `Hierarchy request error`, 3);
  T.WRONG_DOCUMENT_ERR = (E[4] = `Wrong document`, 4), T.INVALID_CHARACTER_ERR = (E[5] = `Invalid character`, 5), T.NO_DATA_ALLOWED_ERR = (E[6] = `No data allowed`, 6), T.NO_MODIFICATION_ALLOWED_ERR = (E[7] = `No modification allowed`, 7);
  var O = T.NOT_FOUND_ERR = (E[8] = `Not found`, 8);
  T.NOT_SUPPORTED_ERR = (E[9] = `Not supported`, 9);
  var k = T.INUSE_ATTRIBUTE_ERR = (E[10] = `Attribute in use`, 10);
  T.INVALID_STATE_ERR = (E[11] = `Invalid state`, 11), T.SYNTAX_ERR = (E[12] = `Syntax error`, 12), T.INVALID_MODIFICATION_ERR = (E[13] = `Invalid modification`, 13), T.NAMESPACE_ERR = (E[14] = `Invalid namespace`, 14), T.INVALID_ACCESS_ERR = (E[15] = `Invalid access`, 15);
  function A(e, t2) {
    if (t2 instanceof Error) var n3 = t2;
    else n3 = this, Error.call(this, E[e]), this.message = E[e], Error.captureStackTrace && Error.captureStackTrace(this, A);
    return n3.code = e, t2 && (this.message = this.message + `: ` + t2), n3;
  }
  A.prototype = Error.prototype, u(T, A);
  function j() {
  }
  j.prototype = { length: 0, item: function(e) {
    return e >= 0 && e < this.length ? this[e] : null;
  }, toString: function(e, t2) {
    for (var n3 = [], r3 = 0; r3 < this.length; r3++) $(this[r3], n3, e, t2);
    return n3.join(``);
  }, filter: function(e) {
    return Array.prototype.filter.call(this, e);
  }, indexOf: function(e) {
    return Array.prototype.indexOf.call(this, e);
  } };
  function M(e, t2) {
    this._node = e, this._refresh = t2, N(this);
  }
  function N(e) {
    var t2 = e._node._inc || e._node.ownerDocument._inc;
    if (e._inc !== t2) {
      var n3 = e._refresh(e._node);
      if (Te(e, `length`, n3.length), !e.$$length || n3.length < e.$$length) for (var r3 = n3.length; r3 in e; r3++) Object.prototype.hasOwnProperty.call(e, r3) && delete e[r3];
      u(n3, e), e._inc = t2;
    }
  }
  M.prototype.item = function(e) {
    return N(this), this[e] || null;
  }, d(M, j);
  function P() {
  }
  function F(e, t2) {
    for (var n3 = e.length; n3--; ) if (e[n3] === t2) return n3;
  }
  function I(e, t2, n3, r3) {
    if (r3 ? t2[F(t2, r3)] = n3 : t2[t2.length++] = n3, e) {
      n3.ownerElement = e;
      var i3 = e.ownerDocument;
      i3 && (r3 && te(i3, e, r3), ee(i3, e, n3));
    }
  }
  function L(e, t2, n3) {
    var r3 = F(t2, n3);
    if (r3 >= 0) {
      for (var i3 = t2.length - 1; r3 < i3; ) t2[r3] = t2[++r3];
      if (t2.length = i3, e) {
        var a3 = e.ownerDocument;
        a3 && (te(a3, e, n3), n3.ownerElement = null);
      }
    } else throw new A(O, Error(e.tagName + `@` + n3));
  }
  P.prototype = { length: 0, item: j.prototype.item, getNamedItem: function(e) {
    for (var t2 = this.length; t2--; ) {
      var n3 = this[t2];
      if (n3.nodeName == e) return n3;
    }
  }, setNamedItem: function(e) {
    var t2 = e.ownerElement;
    if (t2 && t2 != this._ownerElement) throw new A(k);
    var n3 = this.getNamedItem(e.nodeName);
    return I(this._ownerElement, this, e, n3), n3;
  }, setNamedItemNS: function(e) {
    var t2 = e.ownerElement, n3;
    if (t2 && t2 != this._ownerElement) throw new A(k);
    return n3 = this.getNamedItemNS(e.namespaceURI, e.localName), I(this._ownerElement, this, e, n3), n3;
  }, removeNamedItem: function(e) {
    var t2 = this.getNamedItem(e);
    return L(this._ownerElement, this, t2), t2;
  }, removeNamedItemNS: function(e, t2) {
    var n3 = this.getNamedItemNS(e, t2);
    return L(this._ownerElement, this, n3), n3;
  }, getNamedItemNS: function(e, t2) {
    for (var n3 = this.length; n3--; ) {
      var r3 = this[n3];
      if (r3.localName == t2 && r3.namespaceURI == e) return r3;
    }
    return null;
  } };
  function R() {
  }
  R.prototype = { hasFeature: function(e, t2) {
    return true;
  }, createDocument: function(e, t2, n3) {
    var r3 = new H();
    if (r3.implementation = this, r3.childNodes = new j(), r3.doctype = n3 || null, n3 && r3.appendChild(n3), t2) {
      var i3 = r3.createElementNS(e, t2);
      r3.appendChild(i3);
    }
    return r3;
  }, createDocumentType: function(e, t2, n3) {
    var r3 = new Z();
    return r3.name = e, r3.nodeName = e, r3.publicId = t2 || ``, r3.systemId = n3 || ``, r3;
  } };
  function z() {
  }
  z.prototype = { firstChild: null, lastChild: null, previousSibling: null, nextSibling: null, attributes: null, parentNode: null, childNodes: null, ownerDocument: null, nodeValue: null, namespaceURI: null, prefix: null, localName: null, insertBefore: function(e, t2) {
    return K(this, e, t2);
  }, replaceChild: function(e, t2) {
    K(this, e, t2, ue), t2 && this.removeChild(t2);
  }, removeChild: function(e) {
    return ne(this, e);
  }, appendChild: function(e) {
    return this.insertBefore(e, null);
  }, hasChildNodes: function() {
    return this.firstChild != null;
  }, cloneNode: function(e) {
    return we(this.ownerDocument || this, this, e);
  }, normalize: function() {
    for (var e = this.firstChild; e; ) {
      var t2 = e.nextSibling;
      t2 && t2.nodeType == h && e.nodeType == h ? (this.removeChild(t2), e.appendData(t2.data)) : (e.normalize(), e = t2);
    }
  }, isSupported: function(e, t2) {
    return this.ownerDocument.implementation.hasFeature(e, t2);
  }, hasAttributes: function() {
    return this.attributes.length > 0;
  }, lookupPrefix: function(e) {
    for (var t2 = this; t2; ) {
      var n3 = t2._nsMap;
      if (n3) {
        for (var r3 in n3) if (Object.prototype.hasOwnProperty.call(n3, r3) && n3[r3] === e) return r3;
      }
      t2 = t2.nodeType == m ? t2.ownerDocument : t2.parentNode;
    }
    return null;
  }, lookupNamespaceURI: function(e) {
    for (var t2 = this; t2; ) {
      var n3 = t2._nsMap;
      if (n3 && Object.prototype.hasOwnProperty.call(n3, e)) return n3[e];
      t2 = t2.nodeType == m ? t2.ownerDocument : t2.parentNode;
    }
    return null;
  }, isDefaultNamespace: function(e) {
    return this.lookupPrefix(e) == null;
  } };
  function B(e) {
    return e == `<` && `&lt;` || e == `>` && `&gt;` || e == `&` && `&amp;` || e == `"` && `&quot;` || `&#` + e.charCodeAt() + `;`;
  }
  u(f, z), u(f, z.prototype);
  function V(e, t2) {
    if (t2(e)) return true;
    if (e = e.firstChild) do
      if (V(e, t2)) return true;
    while (e = e.nextSibling);
  }
  function H() {
    this.ownerDocument = this;
  }
  function ee(e, t2, n3) {
    e && e._inc++, n3.namespaceURI === i2.XMLNS && (t2._nsMap[n3.prefix ? n3.localName : ``] = n3.value);
  }
  function te(e, t2, n3, r3) {
    e && e._inc++, n3.namespaceURI === i2.XMLNS && delete t2._nsMap[n3.prefix ? n3.localName : ``];
  }
  function U(e, t2, n3) {
    if (e && e._inc) {
      e._inc++;
      var r3 = t2.childNodes;
      if (n3) r3[r3.length++] = n3;
      else {
        for (var i3 = t2.firstChild, a3 = 0; i3; ) r3[a3++] = i3, i3 = i3.nextSibling;
        r3.length = a3, delete r3[r3.length];
      }
    }
  }
  function ne(e, t2) {
    var n3 = t2.previousSibling, r3 = t2.nextSibling;
    return n3 ? n3.nextSibling = r3 : e.firstChild = r3, r3 ? r3.previousSibling = n3 : e.lastChild = n3, t2.parentNode = null, t2.previousSibling = null, t2.nextSibling = null, U(e.ownerDocument, e), t2;
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
  function oe(e, t2) {
    var n3 = e.childNodes || [];
    if (r2(n3, G) || W(t2)) return false;
    var i3 = r2(n3, W);
    return !(t2 && i3 && n3.indexOf(i3) > n3.indexOf(t2));
  }
  function se(e, t2) {
    var n3 = e.childNodes || [];
    function i3(e2) {
      return G(e2) && e2 !== t2;
    }
    if (r2(n3, i3)) return false;
    var a3 = r2(n3, W);
    return !(t2 && a3 && n3.indexOf(a3) > n3.indexOf(t2));
  }
  function ce(e, t2, n3) {
    if (!re(e)) throw new A(D, `Unexpected parent node type ` + e.nodeType);
    if (n3 && n3.parentNode !== e) throw new A(O, `child not in parent`);
    if (!ie(t2) || W(t2) && e.nodeType !== z.DOCUMENT_NODE) throw new A(D, `Unexpected node type ` + t2.nodeType + ` for parent node type ` + e.nodeType);
  }
  function le(e, t2, n3) {
    var i3 = e.childNodes || [], a3 = t2.childNodes || [];
    if (t2.nodeType === z.DOCUMENT_FRAGMENT_NODE) {
      var o3 = a3.filter(G);
      if (o3.length > 1 || r2(a3, ae)) throw new A(D, `More than one element or text in fragment`);
      if (o3.length === 1 && !oe(e, n3)) throw new A(D, `Element in fragment can not be inserted before doctype`);
    }
    if (G(t2) && !oe(e, n3)) throw new A(D, `Only one element can be added and only after doctype`);
    if (W(t2)) {
      if (r2(i3, W)) throw new A(D, `Only one doctype is allowed`);
      var s2 = r2(i3, G);
      if (n3 && i3.indexOf(s2) < i3.indexOf(n3)) throw new A(D, `Doctype can only be inserted before an element`);
      if (!n3 && s2) throw new A(D, `Doctype can not be appended since element is present`);
    }
  }
  function ue(e, t2, n3) {
    var i3 = e.childNodes || [], a3 = t2.childNodes || [];
    if (t2.nodeType === z.DOCUMENT_FRAGMENT_NODE) {
      var o3 = a3.filter(G);
      if (o3.length > 1 || r2(a3, ae)) throw new A(D, `More than one element or text in fragment`);
      if (o3.length === 1 && !se(e, n3)) throw new A(D, `Element in fragment can not be inserted before doctype`);
    }
    if (G(t2) && !se(e, n3)) throw new A(D, `Only one element can be added and only after doctype`);
    if (W(t2)) {
      let e2 = function(e3) {
        return W(e3) && e3 !== n3;
      };
      if (r2(i3, e2)) throw new A(D, `Only one doctype is allowed`);
      var s2 = r2(i3, G);
      if (n3 && i3.indexOf(s2) < i3.indexOf(n3)) throw new A(D, `Doctype can only be inserted before an element`);
    }
  }
  function K(e, t2, n3, r3) {
    ce(e, t2, n3), e.nodeType === z.DOCUMENT_NODE && (r3 || le)(e, t2, n3);
    var i3 = t2.parentNode;
    if (i3 && i3.removeChild(t2), t2.nodeType === C) {
      var a3 = t2.firstChild;
      if (a3 == null) return t2;
      var o3 = t2.lastChild;
    } else a3 = o3 = t2;
    var s2 = n3 ? n3.previousSibling : e.lastChild;
    a3.previousSibling = s2, o3.nextSibling = n3, s2 ? s2.nextSibling = a3 : e.firstChild = a3, n3 == null ? e.lastChild = o3 : n3.previousSibling = o3;
    do {
      a3.parentNode = e;
      var c2 = e.ownerDocument || e;
      q(a3, c2);
    } while (a3 !== o3 && (a3 = a3.nextSibling));
    return U(e.ownerDocument || e, e), t2.nodeType == C && (t2.firstChild = t2.lastChild = null), t2;
  }
  function q(e, t2) {
    if (e.ownerDocument !== t2) {
      if (e.ownerDocument = t2, e.nodeType === p && e.attributes) for (var n3 = 0; n3 < e.attributes.length; n3++) {
        var r3 = e.attributes.item(n3);
        r3 && (r3.ownerDocument = t2);
      }
      for (var i3 = e.firstChild; i3; ) q(i3, t2), i3 = i3.nextSibling;
    }
  }
  function de(e, t2) {
    t2.parentNode && t2.parentNode.removeChild(t2), t2.parentNode = e, t2.previousSibling = e.lastChild, t2.nextSibling = null, t2.previousSibling ? t2.previousSibling.nextSibling = t2 : e.firstChild = t2, e.lastChild = t2, U(e.ownerDocument, e, t2);
    var n3 = e.ownerDocument || e;
    return q(t2, n3), t2;
  }
  H.prototype = { nodeName: `#document`, nodeType: x, doctype: null, documentElement: null, _inc: 1, insertBefore: function(e, t2) {
    if (e.nodeType == C) {
      for (var n3 = e.firstChild; n3; ) {
        var r3 = n3.nextSibling;
        this.insertBefore(n3, t2), n3 = r3;
      }
      return e;
    }
    return K(this, e, t2), q(e, this), this.documentElement === null && e.nodeType === p && (this.documentElement = e), e;
  }, removeChild: function(e) {
    return this.documentElement == e && (this.documentElement = null), ne(this, e);
  }, replaceChild: function(e, t2) {
    K(this, e, t2, ue), q(e, this), t2 && this.removeChild(t2), G(e) && (this.documentElement = e);
  }, importNode: function(e, t2) {
    return Ce(this, e, t2);
  }, getElementById: function(e) {
    var t2 = null;
    return V(this.documentElement, function(n3) {
      if (n3.nodeType == p && n3.getAttribute(`id`) == e) return t2 = n3, true;
    }), t2;
  }, getElementsByClassName: function(e) {
    var t2 = c(e);
    return new M(this, function(n3) {
      var r3 = [];
      return t2.length > 0 && V(n3.documentElement, function(i3) {
        if (i3 !== n3 && i3.nodeType === p) {
          var a3 = i3.getAttribute(`class`);
          if (a3) {
            var o3 = e === a3;
            if (!o3) {
              var s2 = c(a3);
              o3 = t2.every(l(s2));
            }
            o3 && r3.push(i3);
          }
        }
      }), r3;
    });
  }, createElement: function(e) {
    var t2 = new J();
    t2.ownerDocument = this, t2.nodeName = e, t2.tagName = e, t2.localName = e, t2.childNodes = new j();
    var n3 = t2.attributes = new P();
    return n3._ownerElement = t2, t2;
  }, createDocumentFragment: function() {
    var e = new Q();
    return e.ownerDocument = this, e.childNodes = new j(), e;
  }, createTextNode: function(e) {
    var t2 = new fe();
    return t2.ownerDocument = this, t2.appendData(e), t2;
  }, createComment: function(e) {
    var t2 = new pe();
    return t2.ownerDocument = this, t2.appendData(e), t2;
  }, createCDATASection: function(e) {
    var t2 = new me();
    return t2.ownerDocument = this, t2.appendData(e), t2;
  }, createProcessingInstruction: function(e, t2) {
    var n3 = new ve();
    return n3.ownerDocument = this, n3.tagName = n3.nodeName = n3.target = e, n3.nodeValue = n3.data = t2, n3;
  }, createAttribute: function(e) {
    var t2 = new Y();
    return t2.ownerDocument = this, t2.name = e, t2.nodeName = e, t2.localName = e, t2.specified = true, t2;
  }, createEntityReference: function(e) {
    var t2 = new _e();
    return t2.ownerDocument = this, t2.nodeName = e, t2;
  }, createElementNS: function(e, t2) {
    var n3 = new J(), r3 = t2.split(`:`), i3 = n3.attributes = new P();
    return n3.childNodes = new j(), n3.ownerDocument = this, n3.nodeName = t2, n3.tagName = t2, n3.namespaceURI = e, r3.length == 2 ? (n3.prefix = r3[0], n3.localName = r3[1]) : n3.localName = t2, i3._ownerElement = n3, n3;
  }, createAttributeNS: function(e, t2) {
    var n3 = new Y(), r3 = t2.split(`:`);
    return n3.ownerDocument = this, n3.nodeName = t2, n3.name = t2, n3.namespaceURI = e, n3.specified = true, r3.length == 2 ? (n3.prefix = r3[0], n3.localName = r3[1]) : n3.localName = t2, n3;
  } }, d(H, z);
  function J() {
    this._nsMap = {};
  }
  J.prototype = { nodeType: p, hasAttribute: function(e) {
    return this.getAttributeNode(e) != null;
  }, getAttribute: function(e) {
    var t2 = this.getAttributeNode(e);
    return t2 && t2.value || ``;
  }, getAttributeNode: function(e) {
    return this.attributes.getNamedItem(e);
  }, setAttribute: function(e, t2) {
    var n3 = this.ownerDocument.createAttribute(e);
    n3.value = n3.nodeValue = `` + t2, this.setAttributeNode(n3);
  }, removeAttribute: function(e) {
    var t2 = this.getAttributeNode(e);
    t2 && this.removeAttributeNode(t2);
  }, appendChild: function(e) {
    return e.nodeType === C ? this.insertBefore(e, null) : de(this, e);
  }, setAttributeNode: function(e) {
    return this.attributes.setNamedItem(e);
  }, setAttributeNodeNS: function(e) {
    return this.attributes.setNamedItemNS(e);
  }, removeAttributeNode: function(e) {
    return this.attributes.removeNamedItem(e.nodeName);
  }, removeAttributeNS: function(e, t2) {
    var n3 = this.getAttributeNodeNS(e, t2);
    n3 && this.removeAttributeNode(n3);
  }, hasAttributeNS: function(e, t2) {
    return this.getAttributeNodeNS(e, t2) != null;
  }, getAttributeNS: function(e, t2) {
    var n3 = this.getAttributeNodeNS(e, t2);
    return n3 && n3.value || ``;
  }, setAttributeNS: function(e, t2, n3) {
    var r3 = this.ownerDocument.createAttributeNS(e, t2);
    r3.value = r3.nodeValue = `` + n3, this.setAttributeNode(r3);
  }, getAttributeNodeNS: function(e, t2) {
    return this.attributes.getNamedItemNS(e, t2);
  }, getElementsByTagName: function(e) {
    return new M(this, function(t2) {
      var n3 = [];
      return V(t2, function(r3) {
        r3 !== t2 && r3.nodeType == p && (e === `*` || r3.tagName == e) && n3.push(r3);
      }), n3;
    });
  }, getElementsByTagNameNS: function(e, t2) {
    return new M(this, function(n3) {
      var r3 = [];
      return V(n3, function(i3) {
        i3 !== n3 && i3.nodeType === p && (e === `*` || i3.namespaceURI === e) && (t2 === `*` || i3.localName == t2) && r3.push(i3);
      }), r3;
    });
  } }, H.prototype.getElementsByTagName = J.prototype.getElementsByTagName, H.prototype.getElementsByTagNameNS = J.prototype.getElementsByTagNameNS, d(J, z);
  function Y() {
  }
  Y.prototype.nodeType = m, d(Y, z);
  function X() {
  }
  X.prototype = { data: ``, substringData: function(e, t2) {
    return this.data.substring(e, e + t2);
  }, appendData: function(e) {
    e = this.data + e, this.nodeValue = this.data = e, this.length = e.length;
  }, insertData: function(e, t2) {
    this.replaceData(e, 0, t2);
  }, appendChild: function(e) {
    throw Error(E[D]);
  }, deleteData: function(e, t2) {
    this.replaceData(e, t2, ``);
  }, replaceData: function(e, t2, n3) {
    var r3 = this.data.substring(0, e), i3 = this.data.substring(e + t2);
    n3 = r3 + n3 + i3, this.nodeValue = this.data = n3, this.length = n3.length;
  } }, d(X, z);
  function fe() {
  }
  fe.prototype = { nodeName: `#text`, nodeType: h, splitText: function(e) {
    var t2 = this.data, n3 = t2.substring(e);
    t2 = t2.substring(0, e), this.data = this.nodeValue = t2, this.length = t2.length;
    var r3 = this.ownerDocument.createTextNode(n3);
    return this.parentNode && this.parentNode.insertBefore(r3, this.nextSibling), r3;
  } }, d(fe, X);
  function pe() {
  }
  pe.prototype = { nodeName: `#comment`, nodeType: b }, d(pe, X);
  function me() {
  }
  me.prototype = { nodeName: `#cdata-section`, nodeType: g }, d(me, X);
  function Z() {
  }
  Z.prototype.nodeType = S, d(Z, z);
  function he() {
  }
  he.prototype.nodeType = w, d(he, z);
  function ge() {
  }
  ge.prototype.nodeType = v, d(ge, z);
  function _e() {
  }
  _e.prototype.nodeType = _, d(_e, z);
  function Q() {
  }
  Q.prototype.nodeName = `#document-fragment`, Q.prototype.nodeType = C, d(Q, z);
  function ve() {
  }
  ve.prototype.nodeType = y, d(ve, z);
  function ye() {
  }
  ye.prototype.serializeToString = function(e, t2, n3) {
    return be.call(e, t2, n3);
  }, z.prototype.toString = be;
  function be(e, t2) {
    var n3 = [], r3 = this.nodeType == 9 && this.documentElement || this, i3 = r3.prefix, a3 = r3.namespaceURI;
    if (a3 && i3 == null) {
      var i3 = r3.lookupPrefix(a3);
      if (i3 == null) var o3 = [{ namespace: a3, prefix: null }];
    }
    return $(this, n3, e, t2, o3), n3.join(``);
  }
  function xe(e, t2, n3) {
    var r3 = e.prefix || ``, a3 = e.namespaceURI;
    if (!a3 || r3 === `xml` && a3 === i2.XML || a3 === i2.XMLNS) return false;
    for (var o3 = n3.length; o3--; ) {
      var s2 = n3[o3];
      if (s2.prefix === r3) return s2.namespace !== a3;
    }
    return true;
  }
  function Se(e, t2, n3) {
    e.push(` `, t2, `="`, n3.replace(/[<>&"\t\n\r]/g, B), `"`);
  }
  function $(e, t2, n3, r3, a3) {
    if (a3 ||= [], r3) if (e = r3(e), e) {
      if (typeof e == `string`) {
        t2.push(e);
        return;
      }
    } else return;
    switch (e.nodeType) {
      case p:
        var o3 = e.attributes, s2 = o3.length, c2 = e.firstChild, l2 = e.tagName;
        n3 = i2.isHTML(e.namespaceURI) || n3;
        var u2 = l2;
        if (!n3 && !e.prefix && e.namespaceURI) {
          for (var d2, f2 = 0; f2 < o3.length; f2++) if (o3.item(f2).name === `xmlns`) {
            d2 = o3.item(f2).value;
            break;
          }
          if (!d2) for (var v2 = a3.length - 1; v2 >= 0; v2--) {
            var w2 = a3[v2];
            if (w2.prefix === `` && w2.namespace === e.namespaceURI) {
              d2 = w2.namespace;
              break;
            }
          }
          if (d2 !== e.namespaceURI) for (var v2 = a3.length - 1; v2 >= 0; v2--) {
            var w2 = a3[v2];
            if (w2.namespace === e.namespaceURI) {
              w2.prefix && (u2 = w2.prefix + `:` + l2);
              break;
            }
          }
        }
        t2.push(`<`, u2);
        for (var T2 = 0; T2 < s2; T2++) {
          var E2 = o3.item(T2);
          E2.prefix == `xmlns` ? a3.push({ prefix: E2.localName, namespace: E2.value }) : E2.nodeName == `xmlns` && a3.push({ prefix: ``, namespace: E2.value });
        }
        for (var T2 = 0; T2 < s2; T2++) {
          var E2 = o3.item(T2);
          if (xe(E2, n3, a3)) {
            var D2 = E2.prefix || ``, O2 = E2.namespaceURI;
            Se(t2, D2 ? `xmlns:` + D2 : `xmlns`, O2), a3.push({ prefix: D2, namespace: O2 });
          }
          $(E2, t2, n3, r3, a3);
        }
        if (l2 === u2 && xe(e, n3, a3)) {
          var D2 = e.prefix || ``, O2 = e.namespaceURI;
          Se(t2, D2 ? `xmlns:` + D2 : `xmlns`, O2), a3.push({ prefix: D2, namespace: O2 });
        }
        if (c2 || n3 && !/^(?:meta|link|img|br|hr|input)$/i.test(l2)) {
          if (t2.push(`>`), n3 && /^script$/i.test(l2)) for (; c2; ) c2.data ? t2.push(c2.data) : $(c2, t2, n3, r3, a3.slice()), c2 = c2.nextSibling;
          else for (; c2; ) $(c2, t2, n3, r3, a3.slice()), c2 = c2.nextSibling;
          t2.push(`</`, u2, `>`);
        } else t2.push(`/>`);
        return;
      case x:
      case C:
        for (var c2 = e.firstChild; c2; ) $(c2, t2, n3, r3, a3.slice()), c2 = c2.nextSibling;
        return;
      case m:
        return Se(t2, e.name, e.value);
      case h:
        return t2.push(e.data.replace(/[<&>]/g, B));
      case g:
        return t2.push(`<![CDATA[`, e.data, `]]>`);
      case b:
        return t2.push(`<!--`, e.data, `-->`);
      case S:
        var k2 = e.publicId, A2 = e.systemId;
        if (t2.push(`<!DOCTYPE `, e.name), k2) t2.push(` PUBLIC `, k2), A2 && A2 != `.` && t2.push(` `, A2), t2.push(`>`);
        else if (A2 && A2 != `.`) t2.push(` SYSTEM `, A2, `>`);
        else {
          var j2 = e.internalSubset;
          j2 && t2.push(` [`, j2, `]`), t2.push(`>`);
        }
        return;
      case y:
        return t2.push(`<?`, e.target, ` `, e.data, `?>`);
      case _:
        return t2.push(`&`, e.nodeName, `;`);
      default:
        t2.push(`??`, e.nodeName);
    }
  }
  function Ce(e, t2, n3) {
    var r3;
    switch (t2.nodeType) {
      case p:
        r3 = t2.cloneNode(false), r3.ownerDocument = e;
      case C:
        break;
      case m:
        n3 = true;
        break;
    }
    if (r3 ||= t2.cloneNode(false), r3.ownerDocument = e, r3.parentNode = null, n3) for (var i3 = t2.firstChild; i3; ) r3.appendChild(Ce(e, i3, n3)), i3 = i3.nextSibling;
    return r3;
  }
  function we(e, t2, n3) {
    var r3 = new t2.constructor();
    for (var i3 in t2) if (Object.prototype.hasOwnProperty.call(t2, i3)) {
      var a3 = t2[i3];
      typeof a3 != `object` && a3 != r3[i3] && (r3[i3] = a3);
    }
    switch (t2.childNodes && (r3.childNodes = new j()), r3.ownerDocument = e, r3.nodeType) {
      case p:
        var o3 = t2.attributes, s2 = r3.attributes = new P(), c2 = o3.length;
        s2._ownerElement = r3;
        for (var l2 = 0; l2 < c2; l2++) r3.setAttributeNode(we(e, o3.item(l2), true));
        break;
      case m:
        n3 = true;
    }
    if (n3) for (var u2 = t2.firstChild; u2; ) r3.appendChild(we(e, u2, n3)), u2 = u2.nextSibling;
    return r3;
  }
  function Te(e, t2, n3) {
    e[t2] = n3;
  }
  try {
    if (Object.defineProperty) {
      let e = function(t2) {
        switch (t2.nodeType) {
          case p:
          case C:
            var n3 = [];
            for (t2 = t2.firstChild; t2; ) t2.nodeType !== 7 && t2.nodeType !== 8 && n3.push(e(t2)), t2 = t2.nextSibling;
            return n3.join(``);
          default:
            return t2.nodeValue;
        }
      };
      Object.defineProperty(M.prototype, `length`, { get: function() {
        return N(this), this.$$length;
      } }), Object.defineProperty(z.prototype, `textContent`, { get: function() {
        return e(this);
      }, set: function(e2) {
        switch (this.nodeType) {
          case p:
          case C:
            for (; this.firstChild; ) this.removeChild(this.firstChild);
            (e2 || String(e2)) && this.appendChild(this.ownerDocument.createTextNode(e2));
            break;
          default:
            this.data = e2, this.value = e2, this.nodeValue = e2;
        }
      } });
      Te = function(e2, t2, n3) {
        e2[`$$` + t2] = n3;
      };
    }
  } catch {
  }
  exports$1.DocumentType = Z, exports$1.DOMException = A, exports$1.DOMImplementation = R, exports$1.Element = J, exports$1.Node = z, exports$1.NodeList = j, exports$1.XMLSerializer = ye;
})), r = o$1(((exports$1) => {
  var n2 = t().freeze;
  exports$1.XML_ENTITIES = n2({ amp: `&`, apos: `'`, gt: `>`, lt: `<`, quot: `"` }), exports$1.HTML_ENTITIES = n2({ Aacute: `Á`, aacute: `á`, Abreve: `Ă`, abreve: `ă`, ac: `∾`, acd: `∿`, acE: `∾̳`, Acirc: `Â`, acirc: `â`, acute: `´`, Acy: `А`, acy: `а`, AElig: `Æ`, aelig: `æ`, af: `⁡`, Afr: `𝔄`, afr: `𝔞`, Agrave: `À`, agrave: `à`, alefsym: `ℵ`, aleph: `ℵ`, Alpha: `Α`, alpha: `α`, Amacr: `Ā`, amacr: `ā`, amalg: `⨿`, AMP: `&`, amp: `&`, And: `⩓`, and: `∧`, andand: `⩕`, andd: `⩜`, andslope: `⩘`, andv: `⩚`, ang: `∠`, ange: `⦤`, angle: `∠`, angmsd: `∡`, angmsdaa: `⦨`, angmsdab: `⦩`, angmsdac: `⦪`, angmsdad: `⦫`, angmsdae: `⦬`, angmsdaf: `⦭`, angmsdag: `⦮`, angmsdah: `⦯`, angrt: `∟`, angrtvb: `⊾`, angrtvbd: `⦝`, angsph: `∢`, angst: `Å`, angzarr: `⍼`, Aogon: `Ą`, aogon: `ą`, Aopf: `𝔸`, aopf: `𝕒`, ap: `≈`, apacir: `⩯`, apE: `⩰`, ape: `≊`, apid: `≋`, apos: `'`, ApplyFunction: `⁡`, approx: `≈`, approxeq: `≊`, Aring: `Å`, aring: `å`, Ascr: `𝒜`, ascr: `𝒶`, Assign: `≔`, ast: `*`, asymp: `≈`, asympeq: `≍`, Atilde: `Ã`, atilde: `ã`, Auml: `Ä`, auml: `ä`, awconint: `∳`, awint: `⨑`, backcong: `≌`, backepsilon: `϶`, backprime: `‵`, backsim: `∽`, backsimeq: `⋍`, Backslash: `∖`, Barv: `⫧`, barvee: `⊽`, Barwed: `⌆`, barwed: `⌅`, barwedge: `⌅`, bbrk: `⎵`, bbrktbrk: `⎶`, bcong: `≌`, Bcy: `Б`, bcy: `б`, bdquo: `„`, becaus: `∵`, Because: `∵`, because: `∵`, bemptyv: `⦰`, bepsi: `϶`, bernou: `ℬ`, Bernoullis: `ℬ`, Beta: `Β`, beta: `β`, beth: `ℶ`, between: `≬`, Bfr: `𝔅`, bfr: `𝔟`, bigcap: `⋂`, bigcirc: `◯`, bigcup: `⋃`, bigodot: `⨀`, bigoplus: `⨁`, bigotimes: `⨂`, bigsqcup: `⨆`, bigstar: `★`, bigtriangledown: `▽`, bigtriangleup: `△`, biguplus: `⨄`, bigvee: `⋁`, bigwedge: `⋀`, bkarow: `⤍`, blacklozenge: `⧫`, blacksquare: `▪`, blacktriangle: `▴`, blacktriangledown: `▾`, blacktriangleleft: `◂`, blacktriangleright: `▸`, blank: `␣`, blk12: `▒`, blk14: `░`, blk34: `▓`, block: `█`, bne: `=⃥`, bnequiv: `≡⃥`, bNot: `⫭`, bnot: `⌐`, Bopf: `𝔹`, bopf: `𝕓`, bot: `⊥`, bottom: `⊥`, bowtie: `⋈`, boxbox: `⧉`, boxDL: `╗`, boxDl: `╖`, boxdL: `╕`, boxdl: `┐`, boxDR: `╔`, boxDr: `╓`, boxdR: `╒`, boxdr: `┌`, boxH: `═`, boxh: `─`, boxHD: `╦`, boxHd: `╤`, boxhD: `╥`, boxhd: `┬`, boxHU: `╩`, boxHu: `╧`, boxhU: `╨`, boxhu: `┴`, boxminus: `⊟`, boxplus: `⊞`, boxtimes: `⊠`, boxUL: `╝`, boxUl: `╜`, boxuL: `╛`, boxul: `┘`, boxUR: `╚`, boxUr: `╙`, boxuR: `╘`, boxur: `└`, boxV: `║`, boxv: `│`, boxVH: `╬`, boxVh: `╫`, boxvH: `╪`, boxvh: `┼`, boxVL: `╣`, boxVl: `╢`, boxvL: `╡`, boxvl: `┤`, boxVR: `╠`, boxVr: `╟`, boxvR: `╞`, boxvr: `├`, bprime: `‵`, Breve: `˘`, breve: `˘`, brvbar: `¦`, Bscr: `ℬ`, bscr: `𝒷`, bsemi: `⁏`, bsim: `∽`, bsime: `⋍`, bsol: `\\`, bsolb: `⧅`, bsolhsub: `⟈`, bull: `•`, bullet: `•`, bump: `≎`, bumpE: `⪮`, bumpe: `≏`, Bumpeq: `≎`, bumpeq: `≏`, Cacute: `Ć`, cacute: `ć`, Cap: `⋒`, cap: `∩`, capand: `⩄`, capbrcup: `⩉`, capcap: `⩋`, capcup: `⩇`, capdot: `⩀`, CapitalDifferentialD: `ⅅ`, caps: `∩︀`, caret: `⁁`, caron: `ˇ`, Cayleys: `ℭ`, ccaps: `⩍`, Ccaron: `Č`, ccaron: `č`, Ccedil: `Ç`, ccedil: `ç`, Ccirc: `Ĉ`, ccirc: `ĉ`, Cconint: `∰`, ccups: `⩌`, ccupssm: `⩐`, Cdot: `Ċ`, cdot: `ċ`, cedil: `¸`, Cedilla: `¸`, cemptyv: `⦲`, cent: `¢`, CenterDot: `·`, centerdot: `·`, Cfr: `ℭ`, cfr: `𝔠`, CHcy: `Ч`, chcy: `ч`, check: `✓`, checkmark: `✓`, Chi: `Χ`, chi: `χ`, cir: `○`, circ: `ˆ`, circeq: `≗`, circlearrowleft: `↺`, circlearrowright: `↻`, circledast: `⊛`, circledcirc: `⊚`, circleddash: `⊝`, CircleDot: `⊙`, circledR: `®`, circledS: `Ⓢ`, CircleMinus: `⊖`, CirclePlus: `⊕`, CircleTimes: `⊗`, cirE: `⧃`, cire: `≗`, cirfnint: `⨐`, cirmid: `⫯`, cirscir: `⧂`, ClockwiseContourIntegral: `∲`, CloseCurlyDoubleQuote: `”`, CloseCurlyQuote: `’`, clubs: `♣`, clubsuit: `♣`, Colon: `∷`, colon: `:`, Colone: `⩴`, colone: `≔`, coloneq: `≔`, comma: `,`, commat: `@`, comp: `∁`, compfn: `∘`, complement: `∁`, complexes: `ℂ`, cong: `≅`, congdot: `⩭`, Congruent: `≡`, Conint: `∯`, conint: `∮`, ContourIntegral: `∮`, Copf: `ℂ`, copf: `𝕔`, coprod: `∐`, Coproduct: `∐`, COPY: `©`, copy: `©`, copysr: `℗`, CounterClockwiseContourIntegral: `∳`, crarr: `↵`, Cross: `⨯`, cross: `✗`, Cscr: `𝒞`, cscr: `𝒸`, csub: `⫏`, csube: `⫑`, csup: `⫐`, csupe: `⫒`, ctdot: `⋯`, cudarrl: `⤸`, cudarrr: `⤵`, cuepr: `⋞`, cuesc: `⋟`, cularr: `↶`, cularrp: `⤽`, Cup: `⋓`, cup: `∪`, cupbrcap: `⩈`, CupCap: `≍`, cupcap: `⩆`, cupcup: `⩊`, cupdot: `⊍`, cupor: `⩅`, cups: `∪︀`, curarr: `↷`, curarrm: `⤼`, curlyeqprec: `⋞`, curlyeqsucc: `⋟`, curlyvee: `⋎`, curlywedge: `⋏`, curren: `¤`, curvearrowleft: `↶`, curvearrowright: `↷`, cuvee: `⋎`, cuwed: `⋏`, cwconint: `∲`, cwint: `∱`, cylcty: `⌭`, Dagger: `‡`, dagger: `†`, daleth: `ℸ`, Darr: `↡`, dArr: `⇓`, darr: `↓`, dash: `‐`, Dashv: `⫤`, dashv: `⊣`, dbkarow: `⤏`, dblac: `˝`, Dcaron: `Ď`, dcaron: `ď`, Dcy: `Д`, dcy: `д`, DD: `ⅅ`, dd: `ⅆ`, ddagger: `‡`, ddarr: `⇊`, DDotrahd: `⤑`, ddotseq: `⩷`, deg: `°`, Del: `∇`, Delta: `Δ`, delta: `δ`, demptyv: `⦱`, dfisht: `⥿`, Dfr: `𝔇`, dfr: `𝔡`, dHar: `⥥`, dharl: `⇃`, dharr: `⇂`, DiacriticalAcute: `´`, DiacriticalDot: `˙`, DiacriticalDoubleAcute: `˝`, DiacriticalGrave: "`", DiacriticalTilde: `˜`, diam: `⋄`, Diamond: `⋄`, diamond: `⋄`, diamondsuit: `♦`, diams: `♦`, die: `¨`, DifferentialD: `ⅆ`, digamma: `ϝ`, disin: `⋲`, div: `÷`, divide: `÷`, divideontimes: `⋇`, divonx: `⋇`, DJcy: `Ђ`, djcy: `ђ`, dlcorn: `⌞`, dlcrop: `⌍`, dollar: `$`, Dopf: `𝔻`, dopf: `𝕕`, Dot: `¨`, dot: `˙`, DotDot: `⃜`, doteq: `≐`, doteqdot: `≑`, DotEqual: `≐`, dotminus: `∸`, dotplus: `∔`, dotsquare: `⊡`, doublebarwedge: `⌆`, DoubleContourIntegral: `∯`, DoubleDot: `¨`, DoubleDownArrow: `⇓`, DoubleLeftArrow: `⇐`, DoubleLeftRightArrow: `⇔`, DoubleLeftTee: `⫤`, DoubleLongLeftArrow: `⟸`, DoubleLongLeftRightArrow: `⟺`, DoubleLongRightArrow: `⟹`, DoubleRightArrow: `⇒`, DoubleRightTee: `⊨`, DoubleUpArrow: `⇑`, DoubleUpDownArrow: `⇕`, DoubleVerticalBar: `∥`, DownArrow: `↓`, Downarrow: `⇓`, downarrow: `↓`, DownArrowBar: `⤓`, DownArrowUpArrow: `⇵`, DownBreve: `̑`, downdownarrows: `⇊`, downharpoonleft: `⇃`, downharpoonright: `⇂`, DownLeftRightVector: `⥐`, DownLeftTeeVector: `⥞`, DownLeftVector: `↽`, DownLeftVectorBar: `⥖`, DownRightTeeVector: `⥟`, DownRightVector: `⇁`, DownRightVectorBar: `⥗`, DownTee: `⊤`, DownTeeArrow: `↧`, drbkarow: `⤐`, drcorn: `⌟`, drcrop: `⌌`, Dscr: `𝒟`, dscr: `𝒹`, DScy: `Ѕ`, dscy: `ѕ`, dsol: `⧶`, Dstrok: `Đ`, dstrok: `đ`, dtdot: `⋱`, dtri: `▿`, dtrif: `▾`, duarr: `⇵`, duhar: `⥯`, dwangle: `⦦`, DZcy: `Џ`, dzcy: `џ`, dzigrarr: `⟿`, Eacute: `É`, eacute: `é`, easter: `⩮`, Ecaron: `Ě`, ecaron: `ě`, ecir: `≖`, Ecirc: `Ê`, ecirc: `ê`, ecolon: `≕`, Ecy: `Э`, ecy: `э`, eDDot: `⩷`, Edot: `Ė`, eDot: `≑`, edot: `ė`, ee: `ⅇ`, efDot: `≒`, Efr: `𝔈`, efr: `𝔢`, eg: `⪚`, Egrave: `È`, egrave: `è`, egs: `⪖`, egsdot: `⪘`, el: `⪙`, Element: `∈`, elinters: `⏧`, ell: `ℓ`, els: `⪕`, elsdot: `⪗`, Emacr: `Ē`, emacr: `ē`, empty: `∅`, emptyset: `∅`, EmptySmallSquare: `◻`, emptyv: `∅`, EmptyVerySmallSquare: `▫`, emsp: ` `, emsp13: ` `, emsp14: ` `, ENG: `Ŋ`, eng: `ŋ`, ensp: ` `, Eogon: `Ę`, eogon: `ę`, Eopf: `𝔼`, eopf: `𝕖`, epar: `⋕`, eparsl: `⧣`, eplus: `⩱`, epsi: `ε`, Epsilon: `Ε`, epsilon: `ε`, epsiv: `ϵ`, eqcirc: `≖`, eqcolon: `≕`, eqsim: `≂`, eqslantgtr: `⪖`, eqslantless: `⪕`, Equal: `⩵`, equals: `=`, EqualTilde: `≂`, equest: `≟`, Equilibrium: `⇌`, equiv: `≡`, equivDD: `⩸`, eqvparsl: `⧥`, erarr: `⥱`, erDot: `≓`, Escr: `ℰ`, escr: `ℯ`, esdot: `≐`, Esim: `⩳`, esim: `≂`, Eta: `Η`, eta: `η`, ETH: `Ð`, eth: `ð`, Euml: `Ë`, euml: `ë`, euro: `€`, excl: `!`, exist: `∃`, Exists: `∃`, expectation: `ℰ`, ExponentialE: `ⅇ`, exponentiale: `ⅇ`, fallingdotseq: `≒`, Fcy: `Ф`, fcy: `ф`, female: `♀`, ffilig: `ﬃ`, fflig: `ﬀ`, ffllig: `ﬄ`, Ffr: `𝔉`, ffr: `𝔣`, filig: `ﬁ`, FilledSmallSquare: `◼`, FilledVerySmallSquare: `▪`, fjlig: `fj`, flat: `♭`, fllig: `ﬂ`, fltns: `▱`, fnof: `ƒ`, Fopf: `𝔽`, fopf: `𝕗`, ForAll: `∀`, forall: `∀`, fork: `⋔`, forkv: `⫙`, Fouriertrf: `ℱ`, fpartint: `⨍`, frac12: `½`, frac13: `⅓`, frac14: `¼`, frac15: `⅕`, frac16: `⅙`, frac18: `⅛`, frac23: `⅔`, frac25: `⅖`, frac34: `¾`, frac35: `⅗`, frac38: `⅜`, frac45: `⅘`, frac56: `⅚`, frac58: `⅝`, frac78: `⅞`, frasl: `⁄`, frown: `⌢`, Fscr: `ℱ`, fscr: `𝒻`, gacute: `ǵ`, Gamma: `Γ`, gamma: `γ`, Gammad: `Ϝ`, gammad: `ϝ`, gap: `⪆`, Gbreve: `Ğ`, gbreve: `ğ`, Gcedil: `Ģ`, Gcirc: `Ĝ`, gcirc: `ĝ`, Gcy: `Г`, gcy: `г`, Gdot: `Ġ`, gdot: `ġ`, gE: `≧`, ge: `≥`, gEl: `⪌`, gel: `⋛`, geq: `≥`, geqq: `≧`, geqslant: `⩾`, ges: `⩾`, gescc: `⪩`, gesdot: `⪀`, gesdoto: `⪂`, gesdotol: `⪄`, gesl: `⋛︀`, gesles: `⪔`, Gfr: `𝔊`, gfr: `𝔤`, Gg: `⋙`, gg: `≫`, ggg: `⋙`, gimel: `ℷ`, GJcy: `Ѓ`, gjcy: `ѓ`, gl: `≷`, gla: `⪥`, glE: `⪒`, glj: `⪤`, gnap: `⪊`, gnapprox: `⪊`, gnE: `≩`, gne: `⪈`, gneq: `⪈`, gneqq: `≩`, gnsim: `⋧`, Gopf: `𝔾`, gopf: `𝕘`, grave: "`", GreaterEqual: `≥`, GreaterEqualLess: `⋛`, GreaterFullEqual: `≧`, GreaterGreater: `⪢`, GreaterLess: `≷`, GreaterSlantEqual: `⩾`, GreaterTilde: `≳`, Gscr: `𝒢`, gscr: `ℊ`, gsim: `≳`, gsime: `⪎`, gsiml: `⪐`, Gt: `≫`, GT: `>`, gt: `>`, gtcc: `⪧`, gtcir: `⩺`, gtdot: `⋗`, gtlPar: `⦕`, gtquest: `⩼`, gtrapprox: `⪆`, gtrarr: `⥸`, gtrdot: `⋗`, gtreqless: `⋛`, gtreqqless: `⪌`, gtrless: `≷`, gtrsim: `≳`, gvertneqq: `≩︀`, gvnE: `≩︀`, Hacek: `ˇ`, hairsp: ` `, half: `½`, hamilt: `ℋ`, HARDcy: `Ъ`, hardcy: `ъ`, hArr: `⇔`, harr: `↔`, harrcir: `⥈`, harrw: `↭`, Hat: `^`, hbar: `ℏ`, Hcirc: `Ĥ`, hcirc: `ĥ`, hearts: `♥`, heartsuit: `♥`, hellip: `…`, hercon: `⊹`, Hfr: `ℌ`, hfr: `𝔥`, HilbertSpace: `ℋ`, hksearow: `⤥`, hkswarow: `⤦`, hoarr: `⇿`, homtht: `∻`, hookleftarrow: `↩`, hookrightarrow: `↪`, Hopf: `ℍ`, hopf: `𝕙`, horbar: `―`, HorizontalLine: `─`, Hscr: `ℋ`, hscr: `𝒽`, hslash: `ℏ`, Hstrok: `Ħ`, hstrok: `ħ`, HumpDownHump: `≎`, HumpEqual: `≏`, hybull: `⁃`, hyphen: `‐`, Iacute: `Í`, iacute: `í`, ic: `⁣`, Icirc: `Î`, icirc: `î`, Icy: `И`, icy: `и`, Idot: `İ`, IEcy: `Е`, iecy: `е`, iexcl: `¡`, iff: `⇔`, Ifr: `ℑ`, ifr: `𝔦`, Igrave: `Ì`, igrave: `ì`, ii: `ⅈ`, iiiint: `⨌`, iiint: `∭`, iinfin: `⧜`, iiota: `℩`, IJlig: `Ĳ`, ijlig: `ĳ`, Im: `ℑ`, Imacr: `Ī`, imacr: `ī`, image: `ℑ`, ImaginaryI: `ⅈ`, imagline: `ℐ`, imagpart: `ℑ`, imath: `ı`, imof: `⊷`, imped: `Ƶ`, Implies: `⇒`, in: `∈`, incare: `℅`, infin: `∞`, infintie: `⧝`, inodot: `ı`, Int: `∬`, int: `∫`, intcal: `⊺`, integers: `ℤ`, Integral: `∫`, intercal: `⊺`, Intersection: `⋂`, intlarhk: `⨗`, intprod: `⨼`, InvisibleComma: `⁣`, InvisibleTimes: `⁢`, IOcy: `Ё`, iocy: `ё`, Iogon: `Į`, iogon: `į`, Iopf: `𝕀`, iopf: `𝕚`, Iota: `Ι`, iota: `ι`, iprod: `⨼`, iquest: `¿`, Iscr: `ℐ`, iscr: `𝒾`, isin: `∈`, isindot: `⋵`, isinE: `⋹`, isins: `⋴`, isinsv: `⋳`, isinv: `∈`, it: `⁢`, Itilde: `Ĩ`, itilde: `ĩ`, Iukcy: `І`, iukcy: `і`, Iuml: `Ï`, iuml: `ï`, Jcirc: `Ĵ`, jcirc: `ĵ`, Jcy: `Й`, jcy: `й`, Jfr: `𝔍`, jfr: `𝔧`, jmath: `ȷ`, Jopf: `𝕁`, jopf: `𝕛`, Jscr: `𝒥`, jscr: `𝒿`, Jsercy: `Ј`, jsercy: `ј`, Jukcy: `Є`, jukcy: `є`, Kappa: `Κ`, kappa: `κ`, kappav: `ϰ`, Kcedil: `Ķ`, kcedil: `ķ`, Kcy: `К`, kcy: `к`, Kfr: `𝔎`, kfr: `𝔨`, kgreen: `ĸ`, KHcy: `Х`, khcy: `х`, KJcy: `Ќ`, kjcy: `ќ`, Kopf: `𝕂`, kopf: `𝕜`, Kscr: `𝒦`, kscr: `𝓀`, lAarr: `⇚`, Lacute: `Ĺ`, lacute: `ĺ`, laemptyv: `⦴`, lagran: `ℒ`, Lambda: `Λ`, lambda: `λ`, Lang: `⟪`, lang: `⟨`, langd: `⦑`, langle: `⟨`, lap: `⪅`, Laplacetrf: `ℒ`, laquo: `«`, Larr: `↞`, lArr: `⇐`, larr: `←`, larrb: `⇤`, larrbfs: `⤟`, larrfs: `⤝`, larrhk: `↩`, larrlp: `↫`, larrpl: `⤹`, larrsim: `⥳`, larrtl: `↢`, lat: `⪫`, lAtail: `⤛`, latail: `⤙`, late: `⪭`, lates: `⪭︀`, lBarr: `⤎`, lbarr: `⤌`, lbbrk: `❲`, lbrace: `{`, lbrack: `[`, lbrke: `⦋`, lbrksld: `⦏`, lbrkslu: `⦍`, Lcaron: `Ľ`, lcaron: `ľ`, Lcedil: `Ļ`, lcedil: `ļ`, lceil: `⌈`, lcub: `{`, Lcy: `Л`, lcy: `л`, ldca: `⤶`, ldquo: `“`, ldquor: `„`, ldrdhar: `⥧`, ldrushar: `⥋`, ldsh: `↲`, lE: `≦`, le: `≤`, LeftAngleBracket: `⟨`, LeftArrow: `←`, Leftarrow: `⇐`, leftarrow: `←`, LeftArrowBar: `⇤`, LeftArrowRightArrow: `⇆`, leftarrowtail: `↢`, LeftCeiling: `⌈`, LeftDoubleBracket: `⟦`, LeftDownTeeVector: `⥡`, LeftDownVector: `⇃`, LeftDownVectorBar: `⥙`, LeftFloor: `⌊`, leftharpoondown: `↽`, leftharpoonup: `↼`, leftleftarrows: `⇇`, LeftRightArrow: `↔`, Leftrightarrow: `⇔`, leftrightarrow: `↔`, leftrightarrows: `⇆`, leftrightharpoons: `⇋`, leftrightsquigarrow: `↭`, LeftRightVector: `⥎`, LeftTee: `⊣`, LeftTeeArrow: `↤`, LeftTeeVector: `⥚`, leftthreetimes: `⋋`, LeftTriangle: `⊲`, LeftTriangleBar: `⧏`, LeftTriangleEqual: `⊴`, LeftUpDownVector: `⥑`, LeftUpTeeVector: `⥠`, LeftUpVector: `↿`, LeftUpVectorBar: `⥘`, LeftVector: `↼`, LeftVectorBar: `⥒`, lEg: `⪋`, leg: `⋚`, leq: `≤`, leqq: `≦`, leqslant: `⩽`, les: `⩽`, lescc: `⪨`, lesdot: `⩿`, lesdoto: `⪁`, lesdotor: `⪃`, lesg: `⋚︀`, lesges: `⪓`, lessapprox: `⪅`, lessdot: `⋖`, lesseqgtr: `⋚`, lesseqqgtr: `⪋`, LessEqualGreater: `⋚`, LessFullEqual: `≦`, LessGreater: `≶`, lessgtr: `≶`, LessLess: `⪡`, lesssim: `≲`, LessSlantEqual: `⩽`, LessTilde: `≲`, lfisht: `⥼`, lfloor: `⌊`, Lfr: `𝔏`, lfr: `𝔩`, lg: `≶`, lgE: `⪑`, lHar: `⥢`, lhard: `↽`, lharu: `↼`, lharul: `⥪`, lhblk: `▄`, LJcy: `Љ`, ljcy: `љ`, Ll: `⋘`, ll: `≪`, llarr: `⇇`, llcorner: `⌞`, Lleftarrow: `⇚`, llhard: `⥫`, lltri: `◺`, Lmidot: `Ŀ`, lmidot: `ŀ`, lmoust: `⎰`, lmoustache: `⎰`, lnap: `⪉`, lnapprox: `⪉`, lnE: `≨`, lne: `⪇`, lneq: `⪇`, lneqq: `≨`, lnsim: `⋦`, loang: `⟬`, loarr: `⇽`, lobrk: `⟦`, LongLeftArrow: `⟵`, Longleftarrow: `⟸`, longleftarrow: `⟵`, LongLeftRightArrow: `⟷`, Longleftrightarrow: `⟺`, longleftrightarrow: `⟷`, longmapsto: `⟼`, LongRightArrow: `⟶`, Longrightarrow: `⟹`, longrightarrow: `⟶`, looparrowleft: `↫`, looparrowright: `↬`, lopar: `⦅`, Lopf: `𝕃`, lopf: `𝕝`, loplus: `⨭`, lotimes: `⨴`, lowast: `∗`, lowbar: `_`, LowerLeftArrow: `↙`, LowerRightArrow: `↘`, loz: `◊`, lozenge: `◊`, lozf: `⧫`, lpar: `(`, lparlt: `⦓`, lrarr: `⇆`, lrcorner: `⌟`, lrhar: `⇋`, lrhard: `⥭`, lrm: `‎`, lrtri: `⊿`, lsaquo: `‹`, Lscr: `ℒ`, lscr: `𝓁`, Lsh: `↰`, lsh: `↰`, lsim: `≲`, lsime: `⪍`, lsimg: `⪏`, lsqb: `[`, lsquo: `‘`, lsquor: `‚`, Lstrok: `Ł`, lstrok: `ł`, Lt: `≪`, LT: `<`, lt: `<`, ltcc: `⪦`, ltcir: `⩹`, ltdot: `⋖`, lthree: `⋋`, ltimes: `⋉`, ltlarr: `⥶`, ltquest: `⩻`, ltri: `◃`, ltrie: `⊴`, ltrif: `◂`, ltrPar: `⦖`, lurdshar: `⥊`, luruhar: `⥦`, lvertneqq: `≨︀`, lvnE: `≨︀`, macr: `¯`, male: `♂`, malt: `✠`, maltese: `✠`, Map: `⤅`, map: `↦`, mapsto: `↦`, mapstodown: `↧`, mapstoleft: `↤`, mapstoup: `↥`, marker: `▮`, mcomma: `⨩`, Mcy: `М`, mcy: `м`, mdash: `—`, mDDot: `∺`, measuredangle: `∡`, MediumSpace: ` `, Mellintrf: `ℳ`, Mfr: `𝔐`, mfr: `𝔪`, mho: `℧`, micro: `µ`, mid: `∣`, midast: `*`, midcir: `⫰`, middot: `·`, minus: `−`, minusb: `⊟`, minusd: `∸`, minusdu: `⨪`, MinusPlus: `∓`, mlcp: `⫛`, mldr: `…`, mnplus: `∓`, models: `⊧`, Mopf: `𝕄`, mopf: `𝕞`, mp: `∓`, Mscr: `ℳ`, mscr: `𝓂`, mstpos: `∾`, Mu: `Μ`, mu: `μ`, multimap: `⊸`, mumap: `⊸`, nabla: `∇`, Nacute: `Ń`, nacute: `ń`, nang: `∠⃒`, nap: `≉`, napE: `⩰̸`, napid: `≋̸`, napos: `ŉ`, napprox: `≉`, natur: `♮`, natural: `♮`, naturals: `ℕ`, nbsp: ` `, nbump: `≎̸`, nbumpe: `≏̸`, ncap: `⩃`, Ncaron: `Ň`, ncaron: `ň`, Ncedil: `Ņ`, ncedil: `ņ`, ncong: `≇`, ncongdot: `⩭̸`, ncup: `⩂`, Ncy: `Н`, ncy: `н`, ndash: `–`, ne: `≠`, nearhk: `⤤`, neArr: `⇗`, nearr: `↗`, nearrow: `↗`, nedot: `≐̸`, NegativeMediumSpace: `​`, NegativeThickSpace: `​`, NegativeThinSpace: `​`, NegativeVeryThinSpace: `​`, nequiv: `≢`, nesear: `⤨`, nesim: `≂̸`, NestedGreaterGreater: `≫`, NestedLessLess: `≪`, NewLine: `
`, nexist: `∄`, nexists: `∄`, Nfr: `𝔑`, nfr: `𝔫`, ngE: `≧̸`, nge: `≱`, ngeq: `≱`, ngeqq: `≧̸`, ngeqslant: `⩾̸`, nges: `⩾̸`, nGg: `⋙̸`, ngsim: `≵`, nGt: `≫⃒`, ngt: `≯`, ngtr: `≯`, nGtv: `≫̸`, nhArr: `⇎`, nharr: `↮`, nhpar: `⫲`, ni: `∋`, nis: `⋼`, nisd: `⋺`, niv: `∋`, NJcy: `Њ`, njcy: `њ`, nlArr: `⇍`, nlarr: `↚`, nldr: `‥`, nlE: `≦̸`, nle: `≰`, nLeftarrow: `⇍`, nleftarrow: `↚`, nLeftrightarrow: `⇎`, nleftrightarrow: `↮`, nleq: `≰`, nleqq: `≦̸`, nleqslant: `⩽̸`, nles: `⩽̸`, nless: `≮`, nLl: `⋘̸`, nlsim: `≴`, nLt: `≪⃒`, nlt: `≮`, nltri: `⋪`, nltrie: `⋬`, nLtv: `≪̸`, nmid: `∤`, NoBreak: `⁠`, NonBreakingSpace: ` `, Nopf: `ℕ`, nopf: `𝕟`, Not: `⫬`, not: `¬`, NotCongruent: `≢`, NotCupCap: `≭`, NotDoubleVerticalBar: `∦`, NotElement: `∉`, NotEqual: `≠`, NotEqualTilde: `≂̸`, NotExists: `∄`, NotGreater: `≯`, NotGreaterEqual: `≱`, NotGreaterFullEqual: `≧̸`, NotGreaterGreater: `≫̸`, NotGreaterLess: `≹`, NotGreaterSlantEqual: `⩾̸`, NotGreaterTilde: `≵`, NotHumpDownHump: `≎̸`, NotHumpEqual: `≏̸`, notin: `∉`, notindot: `⋵̸`, notinE: `⋹̸`, notinva: `∉`, notinvb: `⋷`, notinvc: `⋶`, NotLeftTriangle: `⋪`, NotLeftTriangleBar: `⧏̸`, NotLeftTriangleEqual: `⋬`, NotLess: `≮`, NotLessEqual: `≰`, NotLessGreater: `≸`, NotLessLess: `≪̸`, NotLessSlantEqual: `⩽̸`, NotLessTilde: `≴`, NotNestedGreaterGreater: `⪢̸`, NotNestedLessLess: `⪡̸`, notni: `∌`, notniva: `∌`, notnivb: `⋾`, notnivc: `⋽`, NotPrecedes: `⊀`, NotPrecedesEqual: `⪯̸`, NotPrecedesSlantEqual: `⋠`, NotReverseElement: `∌`, NotRightTriangle: `⋫`, NotRightTriangleBar: `⧐̸`, NotRightTriangleEqual: `⋭`, NotSquareSubset: `⊏̸`, NotSquareSubsetEqual: `⋢`, NotSquareSuperset: `⊐̸`, NotSquareSupersetEqual: `⋣`, NotSubset: `⊂⃒`, NotSubsetEqual: `⊈`, NotSucceeds: `⊁`, NotSucceedsEqual: `⪰̸`, NotSucceedsSlantEqual: `⋡`, NotSucceedsTilde: `≿̸`, NotSuperset: `⊃⃒`, NotSupersetEqual: `⊉`, NotTilde: `≁`, NotTildeEqual: `≄`, NotTildeFullEqual: `≇`, NotTildeTilde: `≉`, NotVerticalBar: `∤`, npar: `∦`, nparallel: `∦`, nparsl: `⫽⃥`, npart: `∂̸`, npolint: `⨔`, npr: `⊀`, nprcue: `⋠`, npre: `⪯̸`, nprec: `⊀`, npreceq: `⪯̸`, nrArr: `⇏`, nrarr: `↛`, nrarrc: `⤳̸`, nrarrw: `↝̸`, nRightarrow: `⇏`, nrightarrow: `↛`, nrtri: `⋫`, nrtrie: `⋭`, nsc: `⊁`, nsccue: `⋡`, nsce: `⪰̸`, Nscr: `𝒩`, nscr: `𝓃`, nshortmid: `∤`, nshortparallel: `∦`, nsim: `≁`, nsime: `≄`, nsimeq: `≄`, nsmid: `∤`, nspar: `∦`, nsqsube: `⋢`, nsqsupe: `⋣`, nsub: `⊄`, nsubE: `⫅̸`, nsube: `⊈`, nsubset: `⊂⃒`, nsubseteq: `⊈`, nsubseteqq: `⫅̸`, nsucc: `⊁`, nsucceq: `⪰̸`, nsup: `⊅`, nsupE: `⫆̸`, nsupe: `⊉`, nsupset: `⊃⃒`, nsupseteq: `⊉`, nsupseteqq: `⫆̸`, ntgl: `≹`, Ntilde: `Ñ`, ntilde: `ñ`, ntlg: `≸`, ntriangleleft: `⋪`, ntrianglelefteq: `⋬`, ntriangleright: `⋫`, ntrianglerighteq: `⋭`, Nu: `Ν`, nu: `ν`, num: `#`, numero: `№`, numsp: ` `, nvap: `≍⃒`, nVDash: `⊯`, nVdash: `⊮`, nvDash: `⊭`, nvdash: `⊬`, nvge: `≥⃒`, nvgt: `>⃒`, nvHarr: `⤄`, nvinfin: `⧞`, nvlArr: `⤂`, nvle: `≤⃒`, nvlt: `<⃒`, nvltrie: `⊴⃒`, nvrArr: `⤃`, nvrtrie: `⊵⃒`, nvsim: `∼⃒`, nwarhk: `⤣`, nwArr: `⇖`, nwarr: `↖`, nwarrow: `↖`, nwnear: `⤧`, Oacute: `Ó`, oacute: `ó`, oast: `⊛`, ocir: `⊚`, Ocirc: `Ô`, ocirc: `ô`, Ocy: `О`, ocy: `о`, odash: `⊝`, Odblac: `Ő`, odblac: `ő`, odiv: `⨸`, odot: `⊙`, odsold: `⦼`, OElig: `Œ`, oelig: `œ`, ofcir: `⦿`, Ofr: `𝔒`, ofr: `𝔬`, ogon: `˛`, Ograve: `Ò`, ograve: `ò`, ogt: `⧁`, ohbar: `⦵`, ohm: `Ω`, oint: `∮`, olarr: `↺`, olcir: `⦾`, olcross: `⦻`, oline: `‾`, olt: `⧀`, Omacr: `Ō`, omacr: `ō`, Omega: `Ω`, omega: `ω`, Omicron: `Ο`, omicron: `ο`, omid: `⦶`, ominus: `⊖`, Oopf: `𝕆`, oopf: `𝕠`, opar: `⦷`, OpenCurlyDoubleQuote: `“`, OpenCurlyQuote: `‘`, operp: `⦹`, oplus: `⊕`, Or: `⩔`, or: `∨`, orarr: `↻`, ord: `⩝`, order: `ℴ`, orderof: `ℴ`, ordf: `ª`, ordm: `º`, origof: `⊶`, oror: `⩖`, orslope: `⩗`, orv: `⩛`, oS: `Ⓢ`, Oscr: `𝒪`, oscr: `ℴ`, Oslash: `Ø`, oslash: `ø`, osol: `⊘`, Otilde: `Õ`, otilde: `õ`, Otimes: `⨷`, otimes: `⊗`, otimesas: `⨶`, Ouml: `Ö`, ouml: `ö`, ovbar: `⌽`, OverBar: `‾`, OverBrace: `⏞`, OverBracket: `⎴`, OverParenthesis: `⏜`, par: `∥`, para: `¶`, parallel: `∥`, parsim: `⫳`, parsl: `⫽`, part: `∂`, PartialD: `∂`, Pcy: `П`, pcy: `п`, percnt: `%`, period: `.`, permil: `‰`, perp: `⊥`, pertenk: `‱`, Pfr: `𝔓`, pfr: `𝔭`, Phi: `Φ`, phi: `φ`, phiv: `ϕ`, phmmat: `ℳ`, phone: `☎`, Pi: `Π`, pi: `π`, pitchfork: `⋔`, piv: `ϖ`, planck: `ℏ`, planckh: `ℎ`, plankv: `ℏ`, plus: `+`, plusacir: `⨣`, plusb: `⊞`, pluscir: `⨢`, plusdo: `∔`, plusdu: `⨥`, pluse: `⩲`, PlusMinus: `±`, plusmn: `±`, plussim: `⨦`, plustwo: `⨧`, pm: `±`, Poincareplane: `ℌ`, pointint: `⨕`, Popf: `ℙ`, popf: `𝕡`, pound: `£`, Pr: `⪻`, pr: `≺`, prap: `⪷`, prcue: `≼`, prE: `⪳`, pre: `⪯`, prec: `≺`, precapprox: `⪷`, preccurlyeq: `≼`, Precedes: `≺`, PrecedesEqual: `⪯`, PrecedesSlantEqual: `≼`, PrecedesTilde: `≾`, preceq: `⪯`, precnapprox: `⪹`, precneqq: `⪵`, precnsim: `⋨`, precsim: `≾`, Prime: `″`, prime: `′`, primes: `ℙ`, prnap: `⪹`, prnE: `⪵`, prnsim: `⋨`, prod: `∏`, Product: `∏`, profalar: `⌮`, profline: `⌒`, profsurf: `⌓`, prop: `∝`, Proportion: `∷`, Proportional: `∝`, propto: `∝`, prsim: `≾`, prurel: `⊰`, Pscr: `𝒫`, pscr: `𝓅`, Psi: `Ψ`, psi: `ψ`, puncsp: ` `, Qfr: `𝔔`, qfr: `𝔮`, qint: `⨌`, Qopf: `ℚ`, qopf: `𝕢`, qprime: `⁗`, Qscr: `𝒬`, qscr: `𝓆`, quaternions: `ℍ`, quatint: `⨖`, quest: `?`, questeq: `≟`, QUOT: `"`, quot: `"`, rAarr: `⇛`, race: `∽̱`, Racute: `Ŕ`, racute: `ŕ`, radic: `√`, raemptyv: `⦳`, Rang: `⟫`, rang: `⟩`, rangd: `⦒`, range: `⦥`, rangle: `⟩`, raquo: `»`, Rarr: `↠`, rArr: `⇒`, rarr: `→`, rarrap: `⥵`, rarrb: `⇥`, rarrbfs: `⤠`, rarrc: `⤳`, rarrfs: `⤞`, rarrhk: `↪`, rarrlp: `↬`, rarrpl: `⥅`, rarrsim: `⥴`, Rarrtl: `⤖`, rarrtl: `↣`, rarrw: `↝`, rAtail: `⤜`, ratail: `⤚`, ratio: `∶`, rationals: `ℚ`, RBarr: `⤐`, rBarr: `⤏`, rbarr: `⤍`, rbbrk: `❳`, rbrace: `}`, rbrack: `]`, rbrke: `⦌`, rbrksld: `⦎`, rbrkslu: `⦐`, Rcaron: `Ř`, rcaron: `ř`, Rcedil: `Ŗ`, rcedil: `ŗ`, rceil: `⌉`, rcub: `}`, Rcy: `Р`, rcy: `р`, rdca: `⤷`, rdldhar: `⥩`, rdquo: `”`, rdquor: `”`, rdsh: `↳`, Re: `ℜ`, real: `ℜ`, realine: `ℛ`, realpart: `ℜ`, reals: `ℝ`, rect: `▭`, REG: `®`, reg: `®`, ReverseElement: `∋`, ReverseEquilibrium: `⇋`, ReverseUpEquilibrium: `⥯`, rfisht: `⥽`, rfloor: `⌋`, Rfr: `ℜ`, rfr: `𝔯`, rHar: `⥤`, rhard: `⇁`, rharu: `⇀`, rharul: `⥬`, Rho: `Ρ`, rho: `ρ`, rhov: `ϱ`, RightAngleBracket: `⟩`, RightArrow: `→`, Rightarrow: `⇒`, rightarrow: `→`, RightArrowBar: `⇥`, RightArrowLeftArrow: `⇄`, rightarrowtail: `↣`, RightCeiling: `⌉`, RightDoubleBracket: `⟧`, RightDownTeeVector: `⥝`, RightDownVector: `⇂`, RightDownVectorBar: `⥕`, RightFloor: `⌋`, rightharpoondown: `⇁`, rightharpoonup: `⇀`, rightleftarrows: `⇄`, rightleftharpoons: `⇌`, rightrightarrows: `⇉`, rightsquigarrow: `↝`, RightTee: `⊢`, RightTeeArrow: `↦`, RightTeeVector: `⥛`, rightthreetimes: `⋌`, RightTriangle: `⊳`, RightTriangleBar: `⧐`, RightTriangleEqual: `⊵`, RightUpDownVector: `⥏`, RightUpTeeVector: `⥜`, RightUpVector: `↾`, RightUpVectorBar: `⥔`, RightVector: `⇀`, RightVectorBar: `⥓`, ring: `˚`, risingdotseq: `≓`, rlarr: `⇄`, rlhar: `⇌`, rlm: `‏`, rmoust: `⎱`, rmoustache: `⎱`, rnmid: `⫮`, roang: `⟭`, roarr: `⇾`, robrk: `⟧`, ropar: `⦆`, Ropf: `ℝ`, ropf: `𝕣`, roplus: `⨮`, rotimes: `⨵`, RoundImplies: `⥰`, rpar: `)`, rpargt: `⦔`, rppolint: `⨒`, rrarr: `⇉`, Rrightarrow: `⇛`, rsaquo: `›`, Rscr: `ℛ`, rscr: `𝓇`, Rsh: `↱`, rsh: `↱`, rsqb: `]`, rsquo: `’`, rsquor: `’`, rthree: `⋌`, rtimes: `⋊`, rtri: `▹`, rtrie: `⊵`, rtrif: `▸`, rtriltri: `⧎`, RuleDelayed: `⧴`, ruluhar: `⥨`, rx: `℞`, Sacute: `Ś`, sacute: `ś`, sbquo: `‚`, Sc: `⪼`, sc: `≻`, scap: `⪸`, Scaron: `Š`, scaron: `š`, sccue: `≽`, scE: `⪴`, sce: `⪰`, Scedil: `Ş`, scedil: `ş`, Scirc: `Ŝ`, scirc: `ŝ`, scnap: `⪺`, scnE: `⪶`, scnsim: `⋩`, scpolint: `⨓`, scsim: `≿`, Scy: `С`, scy: `с`, sdot: `⋅`, sdotb: `⊡`, sdote: `⩦`, searhk: `⤥`, seArr: `⇘`, searr: `↘`, searrow: `↘`, sect: `§`, semi: `;`, seswar: `⤩`, setminus: `∖`, setmn: `∖`, sext: `✶`, Sfr: `𝔖`, sfr: `𝔰`, sfrown: `⌢`, sharp: `♯`, SHCHcy: `Щ`, shchcy: `щ`, SHcy: `Ш`, shcy: `ш`, ShortDownArrow: `↓`, ShortLeftArrow: `←`, shortmid: `∣`, shortparallel: `∥`, ShortRightArrow: `→`, ShortUpArrow: `↑`, shy: `­`, Sigma: `Σ`, sigma: `σ`, sigmaf: `ς`, sigmav: `ς`, sim: `∼`, simdot: `⩪`, sime: `≃`, simeq: `≃`, simg: `⪞`, simgE: `⪠`, siml: `⪝`, simlE: `⪟`, simne: `≆`, simplus: `⨤`, simrarr: `⥲`, slarr: `←`, SmallCircle: `∘`, smallsetminus: `∖`, smashp: `⨳`, smeparsl: `⧤`, smid: `∣`, smile: `⌣`, smt: `⪪`, smte: `⪬`, smtes: `⪬︀`, SOFTcy: `Ь`, softcy: `ь`, sol: `/`, solb: `⧄`, solbar: `⌿`, Sopf: `𝕊`, sopf: `𝕤`, spades: `♠`, spadesuit: `♠`, spar: `∥`, sqcap: `⊓`, sqcaps: `⊓︀`, sqcup: `⊔`, sqcups: `⊔︀`, Sqrt: `√`, sqsub: `⊏`, sqsube: `⊑`, sqsubset: `⊏`, sqsubseteq: `⊑`, sqsup: `⊐`, sqsupe: `⊒`, sqsupset: `⊐`, sqsupseteq: `⊒`, squ: `□`, Square: `□`, square: `□`, SquareIntersection: `⊓`, SquareSubset: `⊏`, SquareSubsetEqual: `⊑`, SquareSuperset: `⊐`, SquareSupersetEqual: `⊒`, SquareUnion: `⊔`, squarf: `▪`, squf: `▪`, srarr: `→`, Sscr: `𝒮`, sscr: `𝓈`, ssetmn: `∖`, ssmile: `⌣`, sstarf: `⋆`, Star: `⋆`, star: `☆`, starf: `★`, straightepsilon: `ϵ`, straightphi: `ϕ`, strns: `¯`, Sub: `⋐`, sub: `⊂`, subdot: `⪽`, subE: `⫅`, sube: `⊆`, subedot: `⫃`, submult: `⫁`, subnE: `⫋`, subne: `⊊`, subplus: `⪿`, subrarr: `⥹`, Subset: `⋐`, subset: `⊂`, subseteq: `⊆`, subseteqq: `⫅`, SubsetEqual: `⊆`, subsetneq: `⊊`, subsetneqq: `⫋`, subsim: `⫇`, subsub: `⫕`, subsup: `⫓`, succ: `≻`, succapprox: `⪸`, succcurlyeq: `≽`, Succeeds: `≻`, SucceedsEqual: `⪰`, SucceedsSlantEqual: `≽`, SucceedsTilde: `≿`, succeq: `⪰`, succnapprox: `⪺`, succneqq: `⪶`, succnsim: `⋩`, succsim: `≿`, SuchThat: `∋`, Sum: `∑`, sum: `∑`, sung: `♪`, Sup: `⋑`, sup: `⊃`, sup1: `¹`, sup2: `²`, sup3: `³`, supdot: `⪾`, supdsub: `⫘`, supE: `⫆`, supe: `⊇`, supedot: `⫄`, Superset: `⊃`, SupersetEqual: `⊇`, suphsol: `⟉`, suphsub: `⫗`, suplarr: `⥻`, supmult: `⫂`, supnE: `⫌`, supne: `⊋`, supplus: `⫀`, Supset: `⋑`, supset: `⊃`, supseteq: `⊇`, supseteqq: `⫆`, supsetneq: `⊋`, supsetneqq: `⫌`, supsim: `⫈`, supsub: `⫔`, supsup: `⫖`, swarhk: `⤦`, swArr: `⇙`, swarr: `↙`, swarrow: `↙`, swnwar: `⤪`, szlig: `ß`, Tab: `	`, target: `⌖`, Tau: `Τ`, tau: `τ`, tbrk: `⎴`, Tcaron: `Ť`, tcaron: `ť`, Tcedil: `Ţ`, tcedil: `ţ`, Tcy: `Т`, tcy: `т`, tdot: `⃛`, telrec: `⌕`, Tfr: `𝔗`, tfr: `𝔱`, there4: `∴`, Therefore: `∴`, therefore: `∴`, Theta: `Θ`, theta: `θ`, thetasym: `ϑ`, thetav: `ϑ`, thickapprox: `≈`, thicksim: `∼`, ThickSpace: `  `, thinsp: ` `, ThinSpace: ` `, thkap: `≈`, thksim: `∼`, THORN: `Þ`, thorn: `þ`, Tilde: `∼`, tilde: `˜`, TildeEqual: `≃`, TildeFullEqual: `≅`, TildeTilde: `≈`, times: `×`, timesb: `⊠`, timesbar: `⨱`, timesd: `⨰`, tint: `∭`, toea: `⤨`, top: `⊤`, topbot: `⌶`, topcir: `⫱`, Topf: `𝕋`, topf: `𝕥`, topfork: `⫚`, tosa: `⤩`, tprime: `‴`, TRADE: `™`, trade: `™`, triangle: `▵`, triangledown: `▿`, triangleleft: `◃`, trianglelefteq: `⊴`, triangleq: `≜`, triangleright: `▹`, trianglerighteq: `⊵`, tridot: `◬`, trie: `≜`, triminus: `⨺`, TripleDot: `⃛`, triplus: `⨹`, trisb: `⧍`, tritime: `⨻`, trpezium: `⏢`, Tscr: `𝒯`, tscr: `𝓉`, TScy: `Ц`, tscy: `ц`, TSHcy: `Ћ`, tshcy: `ћ`, Tstrok: `Ŧ`, tstrok: `ŧ`, twixt: `≬`, twoheadleftarrow: `↞`, twoheadrightarrow: `↠`, Uacute: `Ú`, uacute: `ú`, Uarr: `↟`, uArr: `⇑`, uarr: `↑`, Uarrocir: `⥉`, Ubrcy: `Ў`, ubrcy: `ў`, Ubreve: `Ŭ`, ubreve: `ŭ`, Ucirc: `Û`, ucirc: `û`, Ucy: `У`, ucy: `у`, udarr: `⇅`, Udblac: `Ű`, udblac: `ű`, udhar: `⥮`, ufisht: `⥾`, Ufr: `𝔘`, ufr: `𝔲`, Ugrave: `Ù`, ugrave: `ù`, uHar: `⥣`, uharl: `↿`, uharr: `↾`, uhblk: `▀`, ulcorn: `⌜`, ulcorner: `⌜`, ulcrop: `⌏`, ultri: `◸`, Umacr: `Ū`, umacr: `ū`, uml: `¨`, UnderBar: `_`, UnderBrace: `⏟`, UnderBracket: `⎵`, UnderParenthesis: `⏝`, Union: `⋃`, UnionPlus: `⊎`, Uogon: `Ų`, uogon: `ų`, Uopf: `𝕌`, uopf: `𝕦`, UpArrow: `↑`, Uparrow: `⇑`, uparrow: `↑`, UpArrowBar: `⤒`, UpArrowDownArrow: `⇅`, UpDownArrow: `↕`, Updownarrow: `⇕`, updownarrow: `↕`, UpEquilibrium: `⥮`, upharpoonleft: `↿`, upharpoonright: `↾`, uplus: `⊎`, UpperLeftArrow: `↖`, UpperRightArrow: `↗`, Upsi: `ϒ`, upsi: `υ`, upsih: `ϒ`, Upsilon: `Υ`, upsilon: `υ`, UpTee: `⊥`, UpTeeArrow: `↥`, upuparrows: `⇈`, urcorn: `⌝`, urcorner: `⌝`, urcrop: `⌎`, Uring: `Ů`, uring: `ů`, urtri: `◹`, Uscr: `𝒰`, uscr: `𝓊`, utdot: `⋰`, Utilde: `Ũ`, utilde: `ũ`, utri: `▵`, utrif: `▴`, uuarr: `⇈`, Uuml: `Ü`, uuml: `ü`, uwangle: `⦧`, vangrt: `⦜`, varepsilon: `ϵ`, varkappa: `ϰ`, varnothing: `∅`, varphi: `ϕ`, varpi: `ϖ`, varpropto: `∝`, vArr: `⇕`, varr: `↕`, varrho: `ϱ`, varsigma: `ς`, varsubsetneq: `⊊︀`, varsubsetneqq: `⫋︀`, varsupsetneq: `⊋︀`, varsupsetneqq: `⫌︀`, vartheta: `ϑ`, vartriangleleft: `⊲`, vartriangleright: `⊳`, Vbar: `⫫`, vBar: `⫨`, vBarv: `⫩`, Vcy: `В`, vcy: `в`, VDash: `⊫`, Vdash: `⊩`, vDash: `⊨`, vdash: `⊢`, Vdashl: `⫦`, Vee: `⋁`, vee: `∨`, veebar: `⊻`, veeeq: `≚`, vellip: `⋮`, Verbar: `‖`, verbar: `|`, Vert: `‖`, vert: `|`, VerticalBar: `∣`, VerticalLine: `|`, VerticalSeparator: `❘`, VerticalTilde: `≀`, VeryThinSpace: ` `, Vfr: `𝔙`, vfr: `𝔳`, vltri: `⊲`, vnsub: `⊂⃒`, vnsup: `⊃⃒`, Vopf: `𝕍`, vopf: `𝕧`, vprop: `∝`, vrtri: `⊳`, Vscr: `𝒱`, vscr: `𝓋`, vsubnE: `⫋︀`, vsubne: `⊊︀`, vsupnE: `⫌︀`, vsupne: `⊋︀`, Vvdash: `⊪`, vzigzag: `⦚`, Wcirc: `Ŵ`, wcirc: `ŵ`, wedbar: `⩟`, Wedge: `⋀`, wedge: `∧`, wedgeq: `≙`, weierp: `℘`, Wfr: `𝔚`, wfr: `𝔴`, Wopf: `𝕎`, wopf: `𝕨`, wp: `℘`, wr: `≀`, wreath: `≀`, Wscr: `𝒲`, wscr: `𝓌`, xcap: `⋂`, xcirc: `◯`, xcup: `⋃`, xdtri: `▽`, Xfr: `𝔛`, xfr: `𝔵`, xhArr: `⟺`, xharr: `⟷`, Xi: `Ξ`, xi: `ξ`, xlArr: `⟸`, xlarr: `⟵`, xmap: `⟼`, xnis: `⋻`, xodot: `⨀`, Xopf: `𝕏`, xopf: `𝕩`, xoplus: `⨁`, xotime: `⨂`, xrArr: `⟹`, xrarr: `⟶`, Xscr: `𝒳`, xscr: `𝓍`, xsqcup: `⨆`, xuplus: `⨄`, xutri: `△`, xvee: `⋁`, xwedge: `⋀`, Yacute: `Ý`, yacute: `ý`, YAcy: `Я`, yacy: `я`, Ycirc: `Ŷ`, ycirc: `ŷ`, Ycy: `Ы`, ycy: `ы`, yen: `¥`, Yfr: `𝔜`, yfr: `𝔶`, YIcy: `Ї`, yicy: `ї`, Yopf: `𝕐`, yopf: `𝕪`, Yscr: `𝒴`, yscr: `𝓎`, YUcy: `Ю`, yucy: `ю`, Yuml: `Ÿ`, yuml: `ÿ`, Zacute: `Ź`, zacute: `ź`, Zcaron: `Ž`, zcaron: `ž`, Zcy: `З`, zcy: `з`, Zdot: `Ż`, zdot: `ż`, zeetrf: `ℨ`, ZeroWidthSpace: `​`, Zeta: `Ζ`, zeta: `ζ`, Zfr: `ℨ`, zfr: `𝔷`, ZHcy: `Ж`, zhcy: `ж`, zigrarr: `⇝`, Zopf: `ℤ`, zopf: `𝕫`, Zscr: `𝒵`, zscr: `𝓏`, zwj: `‍`, zwnj: `‌` }), exports$1.entityMap = exports$1.HTML_ENTITIES;
})), i = o$1(((exports$1) => {
  var n2 = t().NAMESPACE, r2 = /[A-Z_a-z\xC0-\xD6\xD8-\xF6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD]/, i2 = RegExp(`[\\-\\.0-9` + r2.source.slice(1, -1) + `\\u00B7\\u0300-\\u036F\\u203F-\\u2040]`), a2 = RegExp(`^` + r2.source + i2.source + `*(?::` + r2.source + i2.source + `*)?$`), o2 = 0, s = 1, c = 2, l = 3, u = 4, d = 5, f = 6, p = 7;
  function m(e, t2) {
    this.message = e, this.locator = t2, Error.captureStackTrace && Error.captureStackTrace(this, m);
  }
  m.prototype = Error(), m.prototype.name = m.name;
  function h() {
  }
  h.prototype = { parse: function(e, t2, n3) {
    var r3 = this.domBuilder;
    r3.startDocument(), S(t2, t2 = {}), g(e, t2, n3, r3, this.errorHandler), r3.endDocument();
  } };
  function g(e, t2, r3, i3, a3) {
    function o3(e2) {
      if (e2 > 65535) {
        e2 -= 65536;
        var t3 = 55296 + (e2 >> 10), n3 = 56320 + (e2 & 1023);
        return String.fromCharCode(t3, n3);
      } else return String.fromCharCode(e2);
    }
    function s2(e2) {
      var t3 = e2.slice(1, -1);
      return Object.hasOwnProperty.call(r3, t3) ? r3[t3] : t3.charAt(0) === `#` ? o3(parseInt(t3.substr(1).replace(`x`, `0x`))) : (a3.error(`entity not found:` + e2), e2);
    }
    function c2(t3) {
      if (t3 > S2) {
        var n3 = e.substring(S2, t3).replace(/&#?\w+;/g, s2);
        p2 && l2(S2), i3.characters(n3, 0, t3 - S2), S2 = t3;
      }
    }
    function l2(t3, n3) {
      for (; t3 >= d2 && (n3 = f2.exec(e)); ) u2 = n3.index, d2 = u2 + n3[0].length, p2.lineNumber++;
      p2.columnNumber = t3 - u2 + 1;
    }
    for (var u2 = 0, d2 = 0, f2 = /.*(?:\r\n?|\n)|.*$/g, p2 = i3.locator, h2 = [{ currentNSMap: t2 }], g2 = {}, S2 = 0; ; ) {
      try {
        var E2 = e.indexOf(`<`, S2);
        if (E2 < 0) {
          if (!e.substr(S2).match(/^\s*$/)) {
            var D = i3.doc, O = D.createTextNode(e.substr(S2));
            D.appendChild(O), i3.currentElement = O;
          }
          return;
        }
        switch (E2 > S2 && c2(E2), e.charAt(E2 + 1)) {
          case `/`:
            var k = e.indexOf(`>`, E2 + 3), A = e.substring(E2 + 2, k).replace(/[ \t\n\r]+$/g, ``), j = h2.pop();
            k < 0 ? (A = e.substring(E2 + 2).replace(/[\s<].*/, ``), a3.error(`end tag name: ` + A + ` is not complete:` + j.tagName), k = E2 + 1 + A.length) : A.match(/\s</) && (A = A.replace(/[\s<].*/, ``), a3.error(`end tag name: ` + A + ` maybe not complete`), k = E2 + 1 + A.length);
            var M = j.localNSMap, N = j.tagName == A;
            if (N || j.tagName && j.tagName.toLowerCase() == A.toLowerCase()) {
              if (i3.endElement(j.uri, j.localName, A), M) for (var P in M) Object.prototype.hasOwnProperty.call(M, P) && i3.endPrefixMapping(P);
              N || a3.fatalError(`end tag name: ` + A + ` is not match the current start tagName:` + j.tagName);
            } else h2.push(j);
            k++;
            break;
          case `?`:
            p2 && l2(E2), k = w(e, E2, i3);
            break;
          case `!`:
            p2 && l2(E2), k = C(e, E2, i3, a3);
            break;
          default:
            p2 && l2(E2);
            var F = new T(), I = h2[h2.length - 1].currentNSMap, k = v(e, E2, F, I, s2, a3), L = F.length;
            if (!F.closed && x(e, k, F.tagName, g2) && (F.closed = true, r3.nbsp || a3.warning(`unclosed xml attribute`)), p2 && L) {
              for (var R = _(p2, {}), z = 0; z < L; z++) {
                var B = F[z];
                l2(B.offset), B.locator = _(p2, {});
              }
              i3.locator = R, y(F, i3, I) && h2.push(F), i3.locator = p2;
            } else y(F, i3, I) && h2.push(F);
            n2.isHTML(F.uri) && !F.closed ? k = b(e, k, F.tagName, s2, i3) : k++;
        }
      } catch (e2) {
        if (e2 instanceof m) throw e2;
        a3.error(`element parse error: ` + e2), k = -1;
      }
      k > S2 ? S2 = k : c2(Math.max(E2, S2) + 1);
    }
  }
  function _(e, t2) {
    return t2.lineNumber = e.lineNumber, t2.columnNumber = e.columnNumber, t2;
  }
  function v(e, t2, r3, i3, a3, m2) {
    function h2(e2, t3, n3) {
      r3.attributeNames.hasOwnProperty(e2) && m2.fatalError(`Attribute ` + e2 + ` redefined`), r3.addValue(e2, t3.replace(/[\t\n\r]/g, ` `).replace(/&#?\w+;/g, a3), n3);
    }
    for (var g2, _2, v2 = ++t2, y2 = o2; ; ) {
      var b2 = e.charAt(v2);
      switch (b2) {
        case `=`:
          if (y2 === s) g2 = e.slice(t2, v2), y2 = l;
          else if (y2 === c) y2 = l;
          else throw Error(`attribute equal must after attrName`);
          break;
        case `'`:
        case `"`:
          if (y2 === l || y2 === s) if (y2 === s && (m2.warning(`attribute value must after "="`), g2 = e.slice(t2, v2)), t2 = v2 + 1, v2 = e.indexOf(b2, t2), v2 > 0) _2 = e.slice(t2, v2), h2(g2, _2, t2 - 1), y2 = d;
          else throw Error(`attribute value no end '` + b2 + `' match`);
          else if (y2 == u) _2 = e.slice(t2, v2), h2(g2, _2, t2), m2.warning(`attribute "` + g2 + `" missed start quot(` + b2 + `)!!`), t2 = v2 + 1, y2 = d;
          else throw Error(`attribute value must after "="`);
          break;
        case `/`:
          switch (y2) {
            case o2:
              r3.setTagName(e.slice(t2, v2));
            case d:
            case f:
            case p:
              y2 = p, r3.closed = true;
            case u:
            case s:
              break;
            case c:
              r3.closed = true;
              break;
            default:
              throw Error(`attribute invalid close char('/')`);
          }
          break;
        case ``:
          return m2.error(`unexpected end of input`), y2 == o2 && r3.setTagName(e.slice(t2, v2)), v2;
        case `>`:
          switch (y2) {
            case o2:
              r3.setTagName(e.slice(t2, v2));
            case d:
            case f:
            case p:
              break;
            case u:
            case s:
              _2 = e.slice(t2, v2), _2.slice(-1) === `/` && (r3.closed = true, _2 = _2.slice(0, -1));
            case c:
              y2 === c && (_2 = g2), y2 == u ? (m2.warning(`attribute "` + _2 + `" missed quot(")!`), h2(g2, _2, t2)) : ((!n2.isHTML(i3[``]) || !_2.match(/^(?:disabled|checked|selected)$/i)) && m2.warning(`attribute "` + _2 + `" missed value!! "` + _2 + `" instead!!`), h2(_2, _2, t2));
              break;
            case l:
              throw Error(`attribute value missed!!`);
          }
          return v2;
        case ``:
          b2 = ` `;
        default:
          if (b2 <= ` `) switch (y2) {
            case o2:
              r3.setTagName(e.slice(t2, v2)), y2 = f;
              break;
            case s:
              g2 = e.slice(t2, v2), y2 = c;
              break;
            case u:
              var _2 = e.slice(t2, v2);
              m2.warning(`attribute "` + _2 + `" missed quot(")!!`), h2(g2, _2, t2);
            case d:
              y2 = f;
              break;
          }
          else switch (y2) {
            case c:
              r3.tagName, (!n2.isHTML(i3[``]) || !g2.match(/^(?:disabled|checked|selected)$/i)) && m2.warning(`attribute "` + g2 + `" missed value!! "` + g2 + `" instead2!!`), h2(g2, g2, t2), t2 = v2, y2 = s;
              break;
            case d:
              m2.warning(`attribute space is required"` + g2 + `"!!`);
            case f:
              y2 = s, t2 = v2;
              break;
            case l:
              y2 = u, t2 = v2;
              break;
            case p:
              throw Error(`elements closed character '/' and '>' must be connected to`);
          }
      }
      v2++;
    }
  }
  function y(e, t2, r3) {
    for (var i3 = e.tagName, a3 = null, o3 = e.length; o3--; ) {
      var s2 = e[o3], c2 = s2.qName, l2 = s2.value, u2 = c2.indexOf(`:`);
      if (u2 > 0) var d2 = s2.prefix = c2.slice(0, u2), f2 = c2.slice(u2 + 1), p2 = d2 === `xmlns` && f2;
      else f2 = c2, d2 = null, p2 = c2 === `xmlns` && ``;
      s2.localName = f2, p2 !== false && (a3 ?? (a3 = {}, S(r3, r3 = {})), r3[p2] = a3[p2] = l2, s2.uri = n2.XMLNS, t2.startPrefixMapping(p2, l2));
    }
    for (var o3 = e.length; o3--; ) {
      s2 = e[o3];
      var d2 = s2.prefix;
      d2 && (d2 === `xml` && (s2.uri = n2.XML), d2 !== `xmlns` && (s2.uri = r3[d2 || ``]));
    }
    var u2 = i3.indexOf(`:`);
    u2 > 0 ? (d2 = e.prefix = i3.slice(0, u2), f2 = e.localName = i3.slice(u2 + 1)) : (d2 = null, f2 = e.localName = i3);
    var m2 = e.uri = r3[d2 || ``];
    if (t2.startElement(m2, f2, i3, e), e.closed) {
      if (t2.endElement(m2, f2, i3), a3) for (d2 in a3) Object.prototype.hasOwnProperty.call(a3, d2) && t2.endPrefixMapping(d2);
    } else return e.currentNSMap = r3, e.localNSMap = a3, true;
  }
  function b(e, t2, n3, r3, i3) {
    if (/^(?:script|textarea)$/i.test(n3)) {
      var a3 = e.indexOf(`</` + n3 + `>`, t2), o3 = e.substring(t2 + 1, a3);
      if (/[&<]/.test(o3)) return /^script$/i.test(n3) ? (i3.characters(o3, 0, o3.length), a3) : (o3 = o3.replace(/&#?\w+;/g, r3), i3.characters(o3, 0, o3.length), a3);
    }
    return t2 + 1;
  }
  function x(e, t2, n3, r3) {
    var i3 = r3[n3];
    return i3 ?? (i3 = e.lastIndexOf(`</` + n3 + `>`), i3 < t2 && (i3 = e.lastIndexOf(`</` + n3)), r3[n3] = i3), i3 < t2;
  }
  function S(e, t2) {
    for (var n3 in e) Object.prototype.hasOwnProperty.call(e, n3) && (t2[n3] = e[n3]);
  }
  function C(e, t2, n3, r3) {
    switch (e.charAt(t2 + 2)) {
      case `-`:
        if (e.charAt(t2 + 3) === `-`) {
          var i3 = e.indexOf(`-->`, t2 + 4);
          return i3 > t2 ? (n3.comment(e, t2 + 4, i3 - t2 - 4), i3 + 3) : (r3.error(`Unclosed comment`), -1);
        } else return -1;
      default:
        if (e.substr(t2 + 3, 6) == `CDATA[`) {
          var i3 = e.indexOf(`]]>`, t2 + 9);
          return n3.startCDATA(), n3.characters(e, t2 + 9, i3 - t2 - 9), n3.endCDATA(), i3 + 3;
        }
        var a3 = E(e, t2), o3 = a3.length;
        if (o3 > 1 && /!doctype/i.test(a3[0][0])) {
          var s2 = a3[1][0], c2 = false, l2 = false;
          o3 > 3 && (/^public$/i.test(a3[2][0]) ? (c2 = a3[3][0], l2 = o3 > 4 && a3[4][0]) : /^system$/i.test(a3[2][0]) && (l2 = a3[3][0]));
          var u2 = a3[o3 - 1];
          return n3.startDTD(s2, c2, l2), n3.endDTD(), u2.index + u2[0].length;
        }
    }
    return -1;
  }
  function w(e, t2, n3) {
    var r3 = e.indexOf(`?>`, t2);
    if (r3) {
      var i3 = e.substring(t2, r3).match(/^<\?(\S*)\s*([\s\S]*?)\s*$/);
      return i3 ? (i3[0].length, n3.processingInstruction(i3[1], i3[2]), r3 + 2) : -1;
    }
    return -1;
  }
  function T() {
    this.attributeNames = {};
  }
  T.prototype = { setTagName: function(e) {
    if (!a2.test(e)) throw Error(`invalid tagName:` + e);
    this.tagName = e;
  }, addValue: function(e, t2, n3) {
    if (!a2.test(e)) throw Error(`invalid attribute:` + e);
    this.attributeNames[e] = this.length, this[this.length++] = { qName: e, value: t2, offset: n3 };
  }, length: 0, getLocalName: function(e) {
    return this[e].localName;
  }, getLocator: function(e) {
    return this[e].locator;
  }, getQName: function(e) {
    return this[e].qName;
  }, getURI: function(e) {
    return this[e].uri;
  }, getValue: function(e) {
    return this[e].value;
  } };
  function E(e, t2) {
    var n3, r3 = [], i3 = /'[^']+'|"[^"]+"|[^\s<>\/=]+=?|(\/?\s*>|<)/g;
    for (i3.lastIndex = t2, i3.exec(e); n3 = i3.exec(e); ) if (r3.push(n3), n3[1]) return r3;
  }
  exports$1.XMLReader = h, exports$1.ParseError = m;
})), a = o$1(((exports$1) => {
  var a2 = t(), o2 = n(), s = r(), c = i(), l = o2.DOMImplementation, u = a2.NAMESPACE, d = c.ParseError, f = c.XMLReader;
  function p(e) {
    return e.replace(/\r[\n\u0085]/g, `
`).replace(/[\r\u0085\u2028]/g, `
`);
  }
  function m(e) {
    this.options = e || { locator: {} };
  }
  m.prototype.parseFromString = function(e, t2) {
    var n2 = this.options, r2 = new f(), i2 = n2.domBuilder || new g(), a3 = n2.errorHandler, o3 = n2.locator, c2 = n2.xmlns || {}, l2 = /\/x?html?$/.test(t2), d2 = l2 ? s.HTML_ENTITIES : s.XML_ENTITIES;
    o3 && i2.setDocumentLocator(o3), r2.errorHandler = h(a3, i2, o3), r2.domBuilder = n2.domBuilder || i2, l2 && (c2[``] = u.HTML), c2.xml = c2.xml || u.XML;
    var m2 = n2.normalizeLineEndings || p;
    return e && typeof e == `string` ? r2.parse(m2(e), c2, d2) : r2.errorHandler.error(`invalid doc source`), i2.doc;
  };
  function h(e, t2, n2) {
    if (!e) {
      if (t2 instanceof g) return t2;
      e = t2;
    }
    var r2 = {}, i2 = e instanceof Function;
    n2 ||= {};
    function a3(t3) {
      var a4 = e[t3];
      !a4 && i2 && (a4 = e.length == 2 ? function(n3) {
        e(t3, n3);
      } : e), r2[t3] = a4 && function(e2) {
        a4(`[xmldom ` + t3 + `]	` + e2 + v(n2));
      } || function() {
      };
    }
    return a3(`warning`), a3(`error`), a3(`fatalError`), r2;
  }
  function g() {
    this.cdata = false;
  }
  function _(e, t2) {
    t2.lineNumber = e.lineNumber, t2.columnNumber = e.columnNumber;
  }
  g.prototype = { startDocument: function() {
    this.doc = new l().createDocument(null, null, null), this.locator && (this.doc.documentURI = this.locator.systemId);
  }, startElement: function(e, t2, n2, r2) {
    var i2 = this.doc, a3 = i2.createElementNS(e, n2 || t2), o3 = r2.length;
    b(this, a3), this.currentElement = a3, this.locator && _(this.locator, a3);
    for (var s2 = 0; s2 < o3; s2++) {
      var e = r2.getURI(s2), c2 = r2.getValue(s2), n2 = r2.getQName(s2), l2 = i2.createAttributeNS(e, n2);
      this.locator && _(r2.getLocator(s2), l2), l2.value = l2.nodeValue = c2, a3.setAttributeNode(l2);
    }
  }, endElement: function(e, t2, n2) {
    var r2 = this.currentElement;
    r2.tagName, this.currentElement = r2.parentNode;
  }, startPrefixMapping: function(e, t2) {
  }, endPrefixMapping: function(e) {
  }, processingInstruction: function(e, t2) {
    var n2 = this.doc.createProcessingInstruction(e, t2);
    this.locator && _(this.locator, n2), b(this, n2);
  }, ignorableWhitespace: function(e, t2, n2) {
  }, characters: function(e, t2, n2) {
    if (e = y.apply(this, arguments), e) {
      if (this.cdata) var r2 = this.doc.createCDATASection(e);
      else var r2 = this.doc.createTextNode(e);
      this.currentElement ? this.currentElement.appendChild(r2) : /^\s*$/.test(e) && this.doc.appendChild(r2), this.locator && _(this.locator, r2);
    }
  }, skippedEntity: function(e) {
  }, endDocument: function() {
    this.doc.normalize();
  }, setDocumentLocator: function(e) {
    (this.locator = e) && (e.lineNumber = 0);
  }, comment: function(e, t2, n2) {
    e = y.apply(this, arguments);
    var r2 = this.doc.createComment(e);
    this.locator && _(this.locator, r2), b(this, r2);
  }, startCDATA: function() {
    this.cdata = true;
  }, endCDATA: function() {
    this.cdata = false;
  }, startDTD: function(e, t2, n2) {
    var r2 = this.doc.implementation;
    if (r2 && r2.createDocumentType) {
      var i2 = r2.createDocumentType(e, t2, n2);
      this.locator && _(this.locator, i2), b(this, i2), this.doc.doctype = i2;
    }
  }, warning: function(e) {
    console.warn(`[xmldom warning]	` + e, v(this.locator));
  }, error: function(e) {
    console.error(`[xmldom error]	` + e, v(this.locator));
  }, fatalError: function(e) {
    throw new d(e, this.locator);
  } };
  function v(e) {
    if (e) return `
@` + (e.systemId || ``) + `#[line:` + e.lineNumber + `,col:` + e.columnNumber + `]`;
  }
  function y(e, t2, n2) {
    return typeof e == `string` ? e.substr(t2, n2) : e.length >= t2 + n2 || t2 ? new java.lang.String(e, t2, n2) + `` : e;
  }
  `endDTD,startEntity,endEntity,attributeDecl,elementDecl,externalEntityDecl,internalEntityDecl,resolveEntity,getExternalSubset,notationDecl,unparsedEntityDecl`.replace(/\w+/g, function(e) {
    g.prototype[e] = function() {
      return null;
    };
  });
  function b(e, t2) {
    e.currentElement ? e.currentElement.appendChild(t2) : e.doc.appendChild(t2);
  }
  exports$1.__DOMHandler = g, exports$1.normalizeLineEndings = p, exports$1.DOMParser = m;
})), o = o$1(((exports$1) => {
  var t2 = n();
  exports$1.DOMImplementation = t2.DOMImplementation, exports$1.XMLSerializer = t2.XMLSerializer, exports$1.DOMParser = a().DOMParser;
}));
const libCBtriEt5 = o();
export {
  libCBtriEt5 as default
};
//# sourceMappingURL=lib-CBtriEt5.js.map
