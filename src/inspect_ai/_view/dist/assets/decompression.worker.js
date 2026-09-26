(function() {
	//#region ../../node_modules/.pnpm/fzstd@0.1.1/node_modules/fzstd/esm/index.mjs
	var ab = ArrayBuffer;
	var u8$1 = Uint8Array;
	var u16$1 = Uint16Array;
	var i16 = Int16Array;
	var i32$1 = Int32Array;
	var slc$1 = function(v, s, e) {
		if (u8$1.prototype.slice) return u8$1.prototype.slice.call(v, s, e);
		if (s == null || s < 0) s = 0;
		if (e == null || e > v.length) e = v.length;
		var n = new u8$1(e - s);
		n.set(v.subarray(s, e));
		return n;
	};
	var fill = function(v, n, s, e) {
		if (u8$1.prototype.fill) return u8$1.prototype.fill.call(v, n, s, e);
		if (s == null || s < 0) s = 0;
		if (e == null || e > v.length) e = v.length;
		for (; s < e; ++s) v[s] = n;
		return v;
	};
	var cpw = function(v, t, s, e) {
		if (u8$1.prototype.copyWithin) return u8$1.prototype.copyWithin.call(v, t, s, e);
		if (s == null || s < 0) s = 0;
		if (e == null || e > v.length) e = v.length;
		while (s < e) v[t++] = v[s++];
	};
	var ec$1 = [
		"invalid zstd data",
		"window size too large (>2046MB)",
		"invalid block type",
		"FSE accuracy too high",
		"match distance too far back",
		"unexpected EOF"
	];
	var err$1 = function(ind, msg, nt) {
		var e = new Error(msg || ec$1[ind]);
		e.code = ind;
		if (Error.captureStackTrace) Error.captureStackTrace(e, err$1);
		if (!nt) throw e;
		return e;
	};
	var rb = function(d, b, n) {
		var i = 0, o = 0;
		for (; i < n; ++i) o |= d[b++] << (i << 3);
		return o;
	};
	var b4 = function(d, b) {
		return (d[b] | d[b + 1] << 8 | d[b + 2] << 16 | d[b + 3] << 24) >>> 0;
	};
	var rzfh = function(dat, w) {
		var n3 = dat[0] | dat[1] << 8 | dat[2] << 16;
		if (n3 == 3126568 && dat[3] == 253) {
			var flg = dat[4];
			var ss = flg >> 5 & 1, cc = flg >> 2 & 1, df = flg & 3, fcf = flg >> 6;
			if (flg & 8) err$1(0);
			var bt = 6 - ss;
			var db = df == 3 ? 4 : df;
			var di = rb(dat, bt, db);
			bt += db;
			var fsb = fcf ? 1 << fcf : ss;
			var fss = rb(dat, bt, fsb) + (fcf == 1 && 256);
			var ws = fss;
			if (!ss) {
				var wb = 1 << 10 + (dat[5] >> 3);
				ws = wb + (wb >> 3) * (dat[5] & 7);
			}
			if (ws > 2145386496) err$1(1);
			var buf = new u8$1((w == 1 ? fss || ws : w ? 0 : ws) + 12);
			buf[0] = 1, buf[4] = 4, buf[8] = 8;
			return {
				b: bt + fsb,
				y: 0,
				l: 0,
				d: di,
				w: w && w != 1 ? w : buf.subarray(12),
				e: ws,
				o: new i32$1(buf.buffer, 0, 3),
				u: fss,
				c: cc,
				m: Math.min(131072, ws)
			};
		} else if ((n3 >> 4 | dat[3] << 20) == 25481893) return b4(dat, 4) + 8;
		err$1(0);
	};
	var msb = function(val) {
		var bits = 0;
		for (; 1 << bits <= val; ++bits);
		return bits - 1;
	};
	var rfse = function(dat, bt, mal) {
		var tpos = (bt << 3) + 4;
		var al = (dat[bt] & 15) + 5;
		if (al > mal) err$1(3);
		var sz = 1 << al;
		var probs = sz, sym = -1, re = -1, i = -1, ht = sz;
		var buf = new ab(512 + (sz << 2));
		var freq = new i16(buf, 0, 256);
		var dstate = new u16$1(buf, 0, 256);
		var nstate = new u16$1(buf, 512, sz);
		var bb1 = 512 + (sz << 1);
		var syms = new u8$1(buf, bb1, sz);
		var nbits = new u8$1(buf, bb1 + sz);
		while (sym < 255 && probs > 0) {
			var bits = msb(probs + 1);
			var cbt = tpos >> 3;
			var msk = (1 << bits + 1) - 1;
			var val = (dat[cbt] | dat[cbt + 1] << 8 | dat[cbt + 2] << 16) >> (tpos & 7) & msk;
			var msk1fb = (1 << bits) - 1;
			var msv = msk - probs - 1;
			var sval = val & msk1fb;
			if (sval < msv) tpos += bits, val = sval;
			else {
				tpos += bits + 1;
				if (val > msk1fb) val -= msv;
			}
			freq[++sym] = --val;
			if (val == -1) {
				probs += val;
				syms[--ht] = sym;
			} else probs -= val;
			if (!val) do {
				var rbt = tpos >> 3;
				re = (dat[rbt] | dat[rbt + 1] << 8) >> (tpos & 7) & 3;
				tpos += 2;
				sym += re;
			} while (re == 3);
		}
		if (sym > 255 || probs) err$1(0);
		var sympos = 0;
		var sstep = (sz >> 1) + (sz >> 3) + 3;
		var smask = sz - 1;
		for (var s = 0; s <= sym; ++s) {
			var sf = freq[s];
			if (sf < 1) {
				dstate[s] = -sf;
				continue;
			}
			for (i = 0; i < sf; ++i) {
				syms[sympos] = s;
				do
					sympos = sympos + sstep & smask;
				while (sympos >= ht);
			}
		}
		if (sympos) err$1(0);
		for (i = 0; i < sz; ++i) {
			var ns = dstate[syms[i]]++;
			var nb = nbits[i] = al - msb(ns);
			nstate[i] = (ns << nb) - sz;
		}
		return [tpos + 7 >> 3, {
			b: al,
			s: syms,
			n: nbits,
			t: nstate
		}];
	};
	var rhu = function(dat, bt) {
		var i = 0, wc = -1;
		var buf = new u8$1(292), hb = dat[bt];
		var hw = buf.subarray(0, 256);
		var rc = buf.subarray(256, 268);
		var ri = new u16$1(buf.buffer, 268);
		if (hb < 128) {
			var _a = rfse(dat, bt + 1, 6), ebt = _a[0], fdt = _a[1];
			bt += hb;
			var epos = ebt << 3;
			var lb = dat[bt];
			if (!lb) err$1(0);
			var st1 = 0, st2 = 0, btr1 = fdt.b, btr2 = btr1;
			var fpos = (++bt << 3) - 8 + msb(lb);
			for (;;) {
				fpos -= btr1;
				if (fpos < epos) break;
				var cbt = fpos >> 3;
				st1 += (dat[cbt] | dat[cbt + 1] << 8) >> (fpos & 7) & (1 << btr1) - 1;
				hw[++wc] = fdt.s[st1];
				fpos -= btr2;
				if (fpos < epos) break;
				cbt = fpos >> 3;
				st2 += (dat[cbt] | dat[cbt + 1] << 8) >> (fpos & 7) & (1 << btr2) - 1;
				hw[++wc] = fdt.s[st2];
				btr1 = fdt.n[st1];
				st1 = fdt.t[st1];
				btr2 = fdt.n[st2];
				st2 = fdt.t[st2];
			}
			if (++wc > 255) err$1(0);
		} else {
			wc = hb - 127;
			for (; i < wc; i += 2) {
				var byte = dat[++bt];
				hw[i] = byte >> 4;
				hw[i + 1] = byte & 15;
			}
			++bt;
		}
		var wes = 0;
		for (i = 0; i < wc; ++i) {
			var wt = hw[i];
			if (wt > 11) err$1(0);
			wes += wt && 1 << wt - 1;
		}
		var mb = msb(wes) + 1;
		var ts = 1 << mb;
		var rem = ts - wes;
		if (rem & rem - 1) err$1(0);
		hw[wc++] = msb(rem) + 1;
		for (i = 0; i < wc; ++i) {
			var wt = hw[i];
			++rc[hw[i] = wt && mb + 1 - wt];
		}
		var hbuf = new u8$1(ts << 1);
		var syms = hbuf.subarray(0, ts), nb = hbuf.subarray(ts);
		ri[mb] = 0;
		for (i = mb; i > 0; --i) {
			var pv = ri[i];
			fill(nb, i, pv, ri[i - 1] = pv + rc[i] * (1 << mb - i));
		}
		if (ri[0] != ts) err$1(0);
		for (i = 0; i < wc; ++i) {
			var bits = hw[i];
			if (bits) {
				var code = ri[bits];
				fill(syms, i, code, ri[bits] = code + (1 << mb - bits));
			}
		}
		return [bt, {
			n: nb,
			b: mb,
			s: syms
		}];
	};
	var dllt = (/*#__PURE__*/ rfse(/*#__PURE__*/ new u8$1([
		81,
		16,
		99,
		140,
		49,
		198,
		24,
		99,
		12,
		33,
		196,
		24,
		99,
		102,
		102,
		134,
		70,
		146,
		4
	]), 0, 6))[1];
	var dmlt = (/*#__PURE__*/ rfse(/*#__PURE__*/ new u8$1([
		33,
		20,
		196,
		24,
		99,
		140,
		33,
		132,
		16,
		66,
		8,
		33,
		132,
		16,
		66,
		8,
		33,
		68,
		68,
		68,
		68,
		68,
		68,
		68,
		68,
		36,
		9
	]), 0, 6))[1];
	var doct = (/*#__PURE__ */ rfse(/*#__PURE__*/ new u8$1([
		32,
		132,
		16,
		66,
		102,
		70,
		68,
		68,
		68,
		68,
		36,
		73,
		2
	]), 0, 5))[1];
	var b2bl = function(b, s) {
		var len = b.length, bl = new i32$1(len);
		for (var i = 0; i < len; ++i) {
			bl[i] = s;
			s += 1 << b[i];
		}
		return bl;
	};
	var llb = /*#__PURE__ */ new u8$1((/*#__PURE__ */ new i32$1([
		0,
		0,
		0,
		0,
		16843009,
		50528770,
		134678020,
		202050057,
		269422093
	])).buffer, 0, 36);
	var llbl = /*#__PURE__ */ b2bl(llb, 0);
	var mlb = /*#__PURE__ */ new u8$1((/*#__PURE__ */ new i32$1([
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		16843009,
		50528770,
		117769220,
		185207048,
		252579084,
		16
	])).buffer, 0, 53);
	var mlbl = /*#__PURE__ */ b2bl(mlb, 3);
	var dhu = function(dat, out, hu) {
		var len = dat.length, ss = out.length, lb = dat[len - 1], msk = (1 << hu.b) - 1, eb = -hu.b;
		if (!lb) err$1(0);
		var st = 0, btr = hu.b, pos = (len << 3) - 8 + msb(lb) - btr, i = -1;
		for (; pos > eb && i < ss;) {
			var cbt = pos >> 3;
			var val = (dat[cbt] | dat[cbt + 1] << 8 | dat[cbt + 2] << 16) >> (pos & 7);
			st = (st << btr | val) & msk;
			out[++i] = hu.s[st];
			pos -= btr = hu.n[st];
		}
		if (pos != eb || i + 1 != ss) err$1(0);
	};
	var dhu4 = function(dat, out, hu) {
		var bt = 6;
		var sz1 = out.length + 3 >> 2, sz2 = sz1 << 1, sz3 = sz1 + sz2;
		dhu(dat.subarray(bt, bt += dat[0] | dat[1] << 8), out.subarray(0, sz1), hu);
		dhu(dat.subarray(bt, bt += dat[2] | dat[3] << 8), out.subarray(sz1, sz2), hu);
		dhu(dat.subarray(bt, bt += dat[4] | dat[5] << 8), out.subarray(sz2, sz3), hu);
		dhu(dat.subarray(bt), out.subarray(sz3), hu);
	};
	var rzb = function(dat, st, out) {
		var _a;
		var bt = st.b;
		var b0 = dat[bt], btype = b0 >> 1 & 3;
		st.l = b0 & 1;
		var sz = b0 >> 3 | dat[bt + 1] << 5 | dat[bt + 2] << 13;
		var ebt = (bt += 3) + sz;
		if (btype == 1) {
			if (bt >= dat.length) return;
			st.b = bt + 1;
			if (out) {
				fill(out, dat[bt], st.y, st.y += sz);
				return out;
			}
			return fill(new u8$1(sz), dat[bt]);
		}
		if (ebt > dat.length) return;
		if (btype == 0) {
			st.b = ebt;
			if (out) {
				out.set(dat.subarray(bt, ebt), st.y);
				st.y += sz;
				return out;
			}
			return slc$1(dat, bt, ebt);
		}
		if (btype == 2) {
			var b3 = dat[bt], lbt = b3 & 3, sf = b3 >> 2 & 3;
			var lss = b3 >> 4, lcs = 0, s4 = 0;
			if (lbt < 2) {
				if (sf & 1) lss |= dat[++bt] << 4 | (sf & 2 && dat[++bt] << 12);
				else lss = b3 >> 3;
			} else {
				s4 = sf;
				if (sf < 2) lss |= (dat[++bt] & 63) << 4, lcs = dat[bt] >> 6 | dat[++bt] << 2;
				else if (sf == 2) lss |= dat[++bt] << 4 | (dat[++bt] & 3) << 12, lcs = dat[bt] >> 2 | dat[++bt] << 6;
				else lss |= dat[++bt] << 4 | (dat[++bt] & 63) << 12, lcs = dat[bt] >> 6 | dat[++bt] << 2 | dat[++bt] << 10;
			}
			++bt;
			var buf = out ? out.subarray(st.y, st.y + st.m) : new u8$1(st.m);
			var spl = buf.length - lss;
			if (lbt == 0) buf.set(dat.subarray(bt, bt += lss), spl);
			else if (lbt == 1) fill(buf, dat[bt++], spl);
			else {
				var hu = st.h;
				if (lbt == 2) {
					var hud = rhu(dat, bt);
					lcs += bt - (bt = hud[0]);
					st.h = hu = hud[1];
				} else if (!hu) err$1(0);
				(s4 ? dhu4 : dhu)(dat.subarray(bt, bt += lcs), buf.subarray(spl), hu);
			}
			var ns = dat[bt++];
			if (ns) {
				if (ns == 255) ns = (dat[bt++] | dat[bt++] << 8) + 32512;
				else if (ns > 127) ns = ns - 128 << 8 | dat[bt++];
				var scm = dat[bt++];
				if (scm & 3) err$1(0);
				var dts = [
					dmlt,
					doct,
					dllt
				];
				for (var i = 2; i > -1; --i) {
					var md = scm >> (i << 1) + 2 & 3;
					if (md == 1) {
						var rbuf = new u8$1([
							0,
							0,
							dat[bt++]
						]);
						dts[i] = {
							s: rbuf.subarray(2, 3),
							n: rbuf.subarray(0, 1),
							t: new u16$1(rbuf.buffer, 0, 1),
							b: 0
						};
					} else if (md == 2) _a = rfse(dat, bt, 9 - (i & 1)), bt = _a[0], dts[i] = _a[1];
					else if (md == 3) {
						if (!st.t) err$1(0);
						dts[i] = st.t[i];
					}
				}
				var _b = st.t = dts, mlt = _b[0], oct = _b[1], llt = _b[2];
				var lb = dat[ebt - 1];
				if (!lb) err$1(0);
				var spos = (ebt << 3) - 8 + msb(lb) - llt.b, cbt = spos >> 3, oubt = 0;
				var lst = (dat[cbt] | dat[cbt + 1] << 8) >> (spos & 7) & (1 << llt.b) - 1;
				cbt = (spos -= oct.b) >> 3;
				var ost = (dat[cbt] | dat[cbt + 1] << 8) >> (spos & 7) & (1 << oct.b) - 1;
				cbt = (spos -= mlt.b) >> 3;
				var mst = (dat[cbt] | dat[cbt + 1] << 8) >> (spos & 7) & (1 << mlt.b) - 1;
				for (++ns; --ns;) {
					var llc = llt.s[lst];
					var lbtr = llt.n[lst];
					var mlc = mlt.s[mst];
					var mbtr = mlt.n[mst];
					var ofc = oct.s[ost];
					var obtr = oct.n[ost];
					cbt = (spos -= ofc) >> 3;
					var ofp = 1 << ofc;
					var off = ofp + ((dat[cbt] | dat[cbt + 1] << 8 | dat[cbt + 2] << 16 | dat[cbt + 3] << 24) >>> (spos & 7) & ofp - 1);
					cbt = (spos -= mlb[mlc]) >> 3;
					var ml = mlbl[mlc] + ((dat[cbt] | dat[cbt + 1] << 8 | dat[cbt + 2] << 16) >> (spos & 7) & (1 << mlb[mlc]) - 1);
					cbt = (spos -= llb[llc]) >> 3;
					var ll = llbl[llc] + ((dat[cbt] | dat[cbt + 1] << 8 | dat[cbt + 2] << 16) >> (spos & 7) & (1 << llb[llc]) - 1);
					cbt = (spos -= lbtr) >> 3;
					lst = llt.t[lst] + ((dat[cbt] | dat[cbt + 1] << 8) >> (spos & 7) & (1 << lbtr) - 1);
					cbt = (spos -= mbtr) >> 3;
					mst = mlt.t[mst] + ((dat[cbt] | dat[cbt + 1] << 8) >> (spos & 7) & (1 << mbtr) - 1);
					cbt = (spos -= obtr) >> 3;
					ost = oct.t[ost] + ((dat[cbt] | dat[cbt + 1] << 8) >> (spos & 7) & (1 << obtr) - 1);
					if (off > 3) {
						st.o[2] = st.o[1];
						st.o[1] = st.o[0];
						st.o[0] = off -= 3;
					} else {
						var idx = off - (ll != 0);
						if (idx) {
							off = idx == 3 ? st.o[0] - 1 : st.o[idx];
							if (idx > 1) st.o[2] = st.o[1];
							st.o[1] = st.o[0];
							st.o[0] = off;
						} else off = st.o[0];
					}
					for (var i = 0; i < ll; ++i) buf[oubt + i] = buf[spl + i];
					oubt += ll, spl += ll;
					var stin = oubt - off;
					if (stin < 0) {
						var len = -stin;
						var bs = st.e + stin;
						if (len > ml) len = ml;
						for (var i = 0; i < len; ++i) buf[oubt + i] = st.w[bs + i];
						oubt += len, ml -= len, stin = 0;
					}
					for (var i = 0; i < ml; ++i) buf[oubt + i] = buf[stin + i];
					oubt += ml;
				}
				if (oubt != spl) while (spl < buf.length) buf[oubt++] = buf[spl++];
				else oubt = buf.length;
				if (out) st.y += oubt;
				else buf = slc$1(buf, 0, oubt);
			} else if (out) {
				st.y += lss;
				if (spl) for (var i = 0; i < lss; ++i) buf[i] = buf[spl + i];
			} else if (spl) buf = slc$1(buf, spl);
			st.b = ebt;
			return buf;
		}
		err$1(2);
	};
	var cct = function(bufs, ol) {
		if (bufs.length == 1) return bufs[0];
		var buf = new u8$1(ol);
		for (var i = 0, b = 0; i < bufs.length; ++i) {
			var chk = bufs[i];
			buf.set(chk, b);
			b += chk.length;
		}
		return buf;
	};
	/**
	* Decompressor for Zstandard streamed data
	*/
	var Decompress = /* @__PURE__ */ function() {
		/**
		* Creates a Zstandard decompressor
		* @param ondata The handler for stream data
		*/
		function Decompress(ondata) {
			this.ondata = ondata;
			this.c = [];
			this.l = 0;
			this.z = 0;
		}
		/**
		* Pushes data to be decompressed
		* @param chunk The chunk of data to push
		* @param final Whether or not this is the last chunk in the stream
		*/
		Decompress.prototype.push = function(chunk, final) {
			if (typeof this.s == "number") {
				var sub = Math.min(chunk.length, this.s);
				chunk = chunk.subarray(sub);
				this.s -= sub;
			}
			var ncs = chunk.length + this.l;
			if (!this.s) {
				if (final) {
					if (!ncs) {
						this.ondata(new u8$1(0), true);
						return;
					}
					if (ncs < 5) err$1(5);
				} else if (ncs < 18) {
					this.c.push(chunk);
					this.l = ncs;
					return;
				}
				if (this.l) {
					this.c.push(chunk);
					chunk = cct(this.c, ncs);
					this.c = [];
					this.l = 0;
				}
				if (typeof (this.s = rzfh(chunk)) == "number") return this.push(chunk, final);
			}
			if (typeof this.s != "number") {
				if (ncs < (this.z || 3)) {
					if (final) err$1(5);
					this.c.push(chunk);
					this.l = ncs;
					return;
				}
				if (this.l) {
					this.c.push(chunk);
					chunk = cct(this.c, ncs);
					this.c = [];
					this.l = 0;
				}
				if (!this.z && ncs < (this.z = chunk[this.s.b] & 2 ? 4 : 3 + (chunk[this.s.b] >> 3 | chunk[this.s.b + 1] << 5 | chunk[this.s.b + 2] << 13))) {
					if (final) err$1(5);
					this.c.push(chunk);
					this.l = ncs;
					return;
				} else this.z = 0;
				for (;;) {
					var blk = rzb(chunk, this.s);
					if (!blk) {
						if (final) err$1(5);
						var adc = chunk.subarray(this.s.b);
						this.s.b = 0;
						this.c.push(adc), this.l += adc.length;
						return;
					} else {
						this.ondata(blk, false);
						cpw(this.s.w, 0, blk.length);
						this.s.w.set(blk, this.s.w.length - blk.length);
					}
					if (this.s.l) {
						var rest = chunk.subarray(this.s.b);
						this.s = this.s.c * 4;
						this.push(rest, final);
						return;
					}
				}
			} else if (final) err$1(5);
		};
		return Decompress;
	}();
	//#endregion
	//#region ../../node_modules/.pnpm/fflate@0.8.3/node_modules/fflate/esm/browser.js
	var u8 = Uint8Array;
	var u16 = Uint16Array;
	var i32 = Int32Array;
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
		0,
		0,
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
		0,
		0
	]);
	var clim = new u8([
		16,
		17,
		18,
		0,
		8,
		7,
		9,
		6,
		10,
		5,
		11,
		4,
		12,
		3,
		13,
		2,
		14,
		1,
		15
	]);
	var freb = function(eb, start) {
		var b = new u16(31);
		for (var i = 0; i < 31; ++i) b[i] = start += 1 << eb[i - 1];
		var r = new i32(b[30]);
		for (var i = 1; i < 30; ++i) for (var j = b[i]; j < b[i + 1]; ++j) r[j] = j - b[i] << 5 | i;
		return {
			b,
			r
		};
	};
	var _a = freb(fleb, 2);
	var fl = _a.b;
	var revfl = _a.r;
	fl[28] = 258, revfl[258] = 28;
	var _b = freb(fdeb, 0);
	var fd = _b.b;
	_b.r;
	var rev = new u16(32768);
	for (var i = 0; i < 32768; ++i) {
		var x = (i & 43690) >> 1 | (i & 21845) << 1;
		x = (x & 52428) >> 2 | (x & 13107) << 2;
		x = (x & 61680) >> 4 | (x & 3855) << 4;
		rev[i] = ((x & 65280) >> 8 | (x & 255) << 8) >> 1;
	}
	var hMap = (function(cd, mb, r) {
		var s = cd.length;
		var i = 0;
		var l = new u16(mb);
		for (; i < s; ++i) if (cd[i]) ++l[cd[i] - 1];
		var le = new u16(mb);
		for (i = 1; i < mb; ++i) le[i] = le[i - 1] + l[i - 1] << 1;
		var co;
		if (r) {
			co = new u16(1 << mb);
			var rvb = 15 - mb;
			for (i = 0; i < s; ++i) if (cd[i]) {
				var sv = i << 4 | cd[i];
				var r_1 = mb - cd[i];
				var v = le[cd[i] - 1]++ << r_1;
				for (var m = v | (1 << r_1) - 1; v <= m; ++v) co[rev[v] >> rvb] = sv;
			}
		} else {
			co = new u16(s);
			for (i = 0; i < s; ++i) if (cd[i]) co[i] = rev[le[cd[i] - 1]++] >> 15 - cd[i];
		}
		return co;
	});
	var flt = new u8(288);
	for (var i = 0; i < 144; ++i) flt[i] = 8;
	for (var i = 144; i < 256; ++i) flt[i] = 9;
	for (var i = 256; i < 280; ++i) flt[i] = 7;
	for (var i = 280; i < 288; ++i) flt[i] = 8;
	var fdt = new u8(32);
	for (var i = 0; i < 32; ++i) fdt[i] = 5;
	var flrm = /*#__PURE__*/ hMap(flt, 9, 1);
	var fdrm = /*#__PURE__*/ hMap(fdt, 5, 1);
	var max = function(a) {
		var m = a[0];
		for (var i = 1; i < a.length; ++i) if (a[i] > m) m = a[i];
		return m;
	};
	var bits = function(d, p, m) {
		var o = p / 8 | 0;
		return (d[o] | d[o + 1] << 8) >> (p & 7) & m;
	};
	var bits16 = function(d, p) {
		var o = p / 8 | 0;
		return (d[o] | d[o + 1] << 8 | d[o + 2] << 16) >> (p & 7);
	};
	var shft = function(p) {
		return (p + 7) / 8 | 0;
	};
	var slc = function(v, s, e) {
		if (s == null || s < 0) s = 0;
		if (e == null || e > v.length) e = v.length;
		return new u8(v.subarray(s, e));
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
	];
	var err = function(ind, msg, nt) {
		var e = new Error(msg || ec[ind]);
		e.code = ind;
		if (Error.captureStackTrace) Error.captureStackTrace(e, err);
		if (!nt) throw e;
		return e;
	};
	var inflt = function(dat, st, buf, dict) {
		var sl = dat.length, dl = dict ? dict.length : 0;
		if (!sl || st.f && !st.l) return buf || new u8(0);
		var noBuf = !buf;
		var resize = noBuf || st.i != 2;
		var noSt = st.i;
		if (noBuf) buf = new u8(sl * 3);
		var cbuf = function(l) {
			var bl = buf.length;
			if (l > bl) {
				var nbuf = new u8(Math.max(bl * 2, l));
				nbuf.set(buf);
				buf = nbuf;
			}
		};
		var final = st.f || 0, pos = st.p || 0, bt = st.b || 0, lm = st.l, dm = st.d, lbt = st.m, dbt = st.n;
		var tbts = sl * 8;
		do {
			if (!lm) {
				final = bits(dat, pos, 1);
				var type = bits(dat, pos + 1, 3);
				pos += 3;
				if (!type) {
					var s = shft(pos) + 4, l = dat[s - 4] | dat[s - 3] << 8, t = s + l;
					if (t > sl) {
						if (noSt) err(0);
						break;
					}
					if (resize) cbuf(bt + l);
					buf.set(dat.subarray(s, t), bt);
					st.b = bt += l, st.p = pos = t * 8, st.f = final;
					continue;
				} else if (type == 1) lm = flrm, dm = fdrm, lbt = 9, dbt = 5;
				else if (type == 2) {
					var hLit = bits(dat, pos, 31) + 257, hcLen = bits(dat, pos + 10, 15) + 4;
					var tl = hLit + bits(dat, pos + 5, 31) + 1;
					pos += 14;
					var ldt = new u8(tl);
					var clt = new u8(19);
					for (var i = 0; i < hcLen; ++i) clt[clim[i]] = bits(dat, pos + i * 3, 7);
					pos += hcLen * 3;
					var clb = max(clt), clbmsk = (1 << clb) - 1;
					var clm = hMap(clt, clb, 1);
					for (var i = 0; i < tl;) {
						var r = clm[bits(dat, pos, clbmsk)];
						pos += r & 15;
						var s = r >> 4;
						if (s < 16) ldt[i++] = s;
						else {
							var c = 0, n = 0;
							if (s == 16) n = 3 + bits(dat, pos, 3), pos += 2, c = ldt[i - 1];
							else if (s == 17) n = 3 + bits(dat, pos, 7), pos += 3;
							else if (s == 18) n = 11 + bits(dat, pos, 127), pos += 7;
							while (n--) ldt[i++] = c;
						}
					}
					var lt = ldt.subarray(0, hLit), dt = ldt.subarray(hLit);
					lbt = max(lt);
					dbt = max(dt);
					lm = hMap(lt, lbt, 1);
					dm = hMap(dt, dbt, 1);
				} else err(1);
				if (pos > tbts) {
					if (noSt) err(0);
					break;
				}
			}
			if (resize) cbuf(bt + 131072);
			var lms = (1 << lbt) - 1, dms = (1 << dbt) - 1;
			var lpos = pos;
			for (;; lpos = pos) {
				var c = lm[bits16(dat, pos) & lms], sym = c >> 4;
				pos += c & 15;
				if (pos > tbts) {
					if (noSt) err(0);
					break;
				}
				if (!c) err(2);
				if (sym < 256) buf[bt++] = sym;
				else if (sym == 256) {
					lpos = pos, lm = null;
					break;
				} else {
					var add = sym - 254;
					if (sym > 264) {
						var i = sym - 257, b = fleb[i];
						add = bits(dat, pos, (1 << b) - 1) + fl[i];
						pos += b;
					}
					var d = dm[bits16(dat, pos) & dms], dsym = d >> 4;
					if (!d) err(3);
					pos += d & 15;
					var dt = fd[dsym];
					if (dsym > 3) {
						var b = fdeb[dsym];
						dt += bits16(dat, pos) & (1 << b) - 1, pos += b;
					}
					if (pos > tbts) {
						if (noSt) err(0);
						break;
					}
					if (resize) cbuf(bt + 131072);
					var end = bt + add;
					if (bt < dt) {
						var shift = dl - dt, dend = Math.min(dt, end);
						if (shift + bt < 0) err(3);
						for (; bt < dend; ++bt) buf[bt] = dict[shift + bt];
					}
					for (; bt < end; ++bt) buf[bt] = buf[bt - dt];
				}
			}
			st.l = lm, st.p = lpos, st.b = bt, st.f = final;
			if (lm) final = 1, st.m = lbt, st.d = dm, st.n = dbt;
		} while (!final);
		return bt != buf.length && noBuf ? slc(buf, 0, bt) : buf.subarray(0, bt);
	};
	var et = /*#__PURE__*/ new u8(0);
	/**
	* Streaming DEFLATE decompression
	*/
	var Inflate = /* @__PURE__ */ function() {
		function Inflate(opts, cb) {
			if (typeof opts == "function") cb = opts, opts = {};
			this.ondata = cb;
			var dict = opts && opts.dictionary && opts.dictionary.subarray(-32768);
			this.s = {
				i: 0,
				b: dict ? dict.length : 0
			};
			this.o = new u8(32768);
			this.p = new u8(0);
			if (dict) this.o.set(dict);
		}
		Inflate.prototype.e = function(c) {
			if (!this.ondata) err(5);
			if (this.d) err(4);
			if (!this.p.length) this.p = c;
			else if (c.length) {
				var n = new u8(this.p.length + c.length);
				n.set(this.p), n.set(c, this.p.length), this.p = n;
			}
		};
		Inflate.prototype.c = function(final) {
			this.s.i = +(this.d = final || false);
			var bts = this.s.b;
			var dt = inflt(this.p, this.s, this.o);
			this.ondata(slc(dt, bts, this.s.b), this.d);
			this.o = slc(dt, this.s.b - 32768), this.s.b = this.o.length;
			this.p = slc(this.p, this.s.p / 8 | 0), this.s.p &= 7;
		};
		/**
		* Pushes a chunk to be inflated
		* @param chunk The chunk to push
		* @param final Whether this is the final chunk
		*/
		Inflate.prototype.push = function(chunk, final) {
			this.e(chunk), this.c(final);
		};
		return Inflate;
	}();
	var td = typeof TextDecoder != "undefined" && /*#__PURE__*/ new TextDecoder();
	try {
		td.decode(et, { stream: true });
	} catch (e) {}
	//#endregion
	//#region src/client/remote/inflate.ts
	const kChunkSize = 8192;
	/**
	* Inflates a DEFLATE ZIP entry, enforcing its directory size as output
	* arrives.
	*
	* Input goes in small chunks, so an entry that inflates past its declared
	* size fails after one chunk's output instead of after the whole stream.
	* fflate's one-shot size hint would allocate the attacker-declared size up
	* front and silently truncate excess.
	*/
	function inflateBounded(data, size) {
		const chunks = [];
		let loaded = 0;
		const stream = new Inflate((chunk, final) => {
			loaded += chunk.length;
			if (loaded > size || final && loaded !== size) throw new Error("Decompressed ZIP entry size does not match its directory");
			chunks.push(chunk);
		});
		let position = 0;
		do {
			const end = Math.min(position + kChunkSize, data.length);
			stream.push(data.slice(position, end), end === data.length);
			position = end;
		} while (position < data.length);
		const output = new Uint8Array(loaded);
		let offset = 0;
		for (const part of chunks) {
			output.set(part, offset);
			offset += part.length;
		}
		return output;
	}
	//#endregion
	//#region src/client/remote/zstd-decoder.ts
	function createZstdDecoder(Decompress) {
		/**
		* Maximum history allocation allowed by the viewer (2^25 = 32 MiB).
		*/
		const MAX_WINDOW_LOG = 25;
		const MAX_HISTORY_WORK = 34359738368;
		const MAX_FRAME_BLOCK_COUNT = 1e6;
		/**
		* Error thrown when zstd data uses a window size too large for fzstd.
		*/
		class ZstdWindowSizeError extends Error {
			windowLog;
			maxWindowLog;
			constructor(windowLog) {
				super(`Zstd window size too large (windowLog=${windowLog}, max=${MAX_WINDOW_LOG}). The viewer supports zstd frames with history windows up to 32 MiB. Recompress using smaller zstd frames or ZIP deflate.`);
				this.name = "ZstdWindowSizeError";
				this.windowLog = windowLog;
				this.maxWindowLog = MAX_WINDOW_LOG;
				Object.setPrototypeOf(this, ZstdWindowSizeError.prototype);
			}
		}
		function scanFrames(data, expectedSize, onFrame) {
			const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
			let offset = 0;
			let historyWork = 0;
			let frameBlockCount = 0;
			const countOperation = () => {
				if (++frameBlockCount > MAX_FRAME_BLOCK_COUNT) throw new Error("Zstd frame/block count exceeds the viewer budget");
			};
			const addHistoryWork = (size) => {
				historyWork += size;
				if (historyWork > MAX_HISTORY_WORK) throw new Error("Zstd history work exceeds the 32 GiB viewer budget; use smaller windows or ZIP deflate");
			};
			const requireBytes = (count) => {
				if (count > data.length - offset) throw new Error("Truncated zstd frame");
			};
			while (offset < data.length) {
				countOperation();
				const frameStart = offset;
				requireBytes(4);
				const magic = view.getUint32(offset, true);
				offset += 4;
				if ((magic & 4294967280) === 407710288) {
					requireBytes(4);
					const size = view.getUint32(offset, true);
					offset += 4;
					requireBytes(size);
					offset += size;
					continue;
				}
				if (magic !== 4247762216) throw new Error("Invalid zstd frame");
				requireBytes(1);
				const descriptor = view.getUint8(offset++);
				const singleSegment = (descriptor & 32) !== 0;
				let windowSize = 0;
				if (!singleSegment) {
					requireBytes(1);
					const windowDescriptor = view.getUint8(offset++);
					const base = 2 ** (10 + (windowDescriptor >> 3));
					windowSize = base + base / 8 * (windowDescriptor & 7);
				}
				const dictionaryFlag = descriptor & 3;
				const dictionaryBytes = dictionaryFlag === 3 ? 4 : dictionaryFlag;
				requireBytes(dictionaryBytes);
				offset += dictionaryBytes;
				const sizeFlag = descriptor >> 6;
				const sizeBytes = sizeFlag ? 2 ** sizeFlag : singleSegment ? 1 : 0;
				requireBytes(sizeBytes);
				let contentSize = sizeFlag === 1 ? 256 : 0;
				for (let index = 0; index < sizeBytes; index++) contentSize += view.getUint8(offset++) * 256 ** index;
				if (sizeBytes && (!Number.isSafeInteger(contentSize) || contentSize > expectedSize)) throw new Error("Zstd frame size exceeds its ZIP entry size");
				if (singleSegment) windowSize = contentSize;
				if (windowSize > 2 ** MAX_WINDOW_LOG) throw new ZstdWindowSizeError(Math.ceil(Math.log2(windowSize)));
				addHistoryWork(windowSize);
				let last = false;
				while (!last) {
					countOperation();
					requireBytes(3);
					const block = view.getUint8(offset) + view.getUint16(offset + 1, true) * 256;
					offset += 3;
					last = (block & 1) !== 0;
					const type = block >> 1 & 3;
					const size = block >> 3;
					if (type === 3 || size > 131072) throw new Error("Invalid zstd block");
					addHistoryWork(windowSize);
					const compressedSize = type === 1 ? 1 : size;
					requireBytes(compressedSize);
					offset += compressedSize;
				}
				if (descriptor & 4) {
					requireBytes(4);
					offset += 4;
				}
				onFrame?.(data.subarray(frameStart, offset));
			}
			return Math.max(historyWork, frameBlockCount * 1024);
		}
		function decompress(data, expectedSize) {
			scanFrames(data, expectedSize);
			const pages = [];
			let page = /* @__PURE__ */ new Uint8Array();
			let used = 0;
			let total = 0;
			const collect = (chunk) => {
				total += chunk.length;
				if (total > expectedSize) throw new Error("Zstd output exceeds its ZIP entry size");
				let offset = 0;
				while (offset < chunk.length) {
					if (used === page.length) {
						page = new Uint8Array(Math.min(65536, expectedSize));
						pages.push(page);
						used = 0;
					}
					const count = Math.min(chunk.length - offset, page.length - used);
					page.set(chunk.subarray(offset, offset + count), used);
					offset += count;
					used += count;
				}
			};
			scanFrames(data, expectedSize, (frame) => {
				new Decompress(collect).push(frame, true);
			});
			if (total !== expectedSize) throw new Error("Zstd output does not match its ZIP entry size");
			const result = new Uint8Array(total);
			let offset = 0;
			for (const part of pages) {
				const count = Math.min(part.length, total - offset);
				result.set(part.subarray(0, count), offset);
				offset += count;
			}
			return result;
		}
		return {
			scanFrames,
			decompress,
			ZstdWindowSizeError
		};
	}
	//#endregion
	//#region src/client/remote/decompression.worker.ts
	const zstd = createZstdDecoder(Decompress);
	self.addEventListener("message", (event) => {
		const message = event.data;
		if (typeof message !== "object" || message === null) return;
		if ("type" in message && message.type === "init") {
			self.postMessage({
				type: "init_complete",
				success: true
			});
			return;
		}
		if (!("type" in message) || message.type !== "decompress" || !("requestId" in message) || typeof message.requestId !== "number") return;
		const { requestId } = message;
		try {
			if (!("data" in message) || !(message.data instanceof Uint8Array) || !("expectedSize" in message) || typeof message.expectedSize !== "number" || !("method" in message) || message.method !== "zstd" && message.method !== "deflate") throw new Error("Malformed decompression request");
			const result = message.method === "deflate" ? inflateBounded(message.data, message.expectedSize) : zstd.decompress(message.data, message.expectedSize);
			self.postMessage({
				requestId,
				success: true,
				data: result
			}, { transfer: [result.buffer] });
		} catch (err) {
			self.postMessage({
				requestId,
				success: false,
				error: err instanceof Error ? err.message : "Unknown error"
			});
		}
	});
	//#endregion
})();

//# sourceMappingURL=decompression.worker.js.map