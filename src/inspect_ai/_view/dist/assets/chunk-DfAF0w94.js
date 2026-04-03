var e = Object.create, t = Object.defineProperty, n = Object.getOwnPropertyDescriptor, r = Object.getOwnPropertyNames, i = Object.getPrototypeOf, a = Object.prototype.hasOwnProperty, o = (e2, t2) => () => (t2 || e2((t2 = { exports: {} }).exports, t2), t2.exports), s = (e2, i2, o2, s2) => {
  if (i2 && typeof i2 == `object` || typeof i2 == `function`) for (var c2 = r(i2), l2 = 0, u = c2.length, d; l2 < u; l2++) d = c2[l2], !a.call(e2, d) && d !== o2 && t(e2, d, { get: ((e3) => i2[e3]).bind(null, d), enumerable: !(s2 = n(i2, d)) || s2.enumerable });
  return e2;
}, c = (n2, r2, a2) => (a2 = n2 == null ? {} : e(i(n2)), s(t(a2, `default`, { value: n2, enumerable: true }), n2)), l = (e2) => (t2) => c(t2.default);
export {
  l,
  o
};
//# sourceMappingURL=chunk-DfAF0w94.js.map
