  /* ---------------------------------------------------------------
     レビュー回答ガイドの初心者向け補助
     初心者モード・コードの日本語訳（ドロワー）・用語ポップアップ・つながり図の矢印
     （住所・注目行と訳・重なりの図の HTML は build.py が組み立て時に入れる）
  --------------------------------------------------------------- */
  var BM_KEY = 'guapp-review-beginner';
  var BM_ON = true;          // 初心者モード（既定 ON。localStorage が使えなくても ON で動く）
  var bmSwitches = [];       // ヘッダーとドロワーのスイッチ（同じ状態に連動）
  var drawerSwitchWrap = null;
  var TRD = {};              // 訳: path → [{a, b, ja}]
  var GL = [];               // 用語集
  var termRe = null, termMap = {};
  var conns = [];            // つながり図

  function readJson(id, fallback) {
    var n = document.getElementById(id);
    if (!n) { return fallback; }
    try { return JSON.parse(n.textContent); } catch (e) { return fallback; }
  }
  function bmLoad() { try { if (window.localStorage.getItem(BM_KEY) === '0') { BM_ON = false; } } catch (e) { /* 既定の ON のまま */ } }
  function bmSave() { try { window.localStorage.setItem(BM_KEY, BM_ON ? '1' : '0'); } catch (e) { /* 保存できなくても動く */ } }

  function setBM(on, initial) {
    BM_ON = !!on;
    document.documentElement.classList.toggle('bm-off', !BM_ON);
    bmSwitches.forEach(function (c) { c.checked = BM_ON; });
    closeTermPop();
    unwrapTerms();
    if (BM_ON) { wrapTermsIn(document.getElementById('content'), true); }
    redrawDrawerCode();
    conns.forEach(scheduleDraw);
    if (!initial) { bmSave(); }
  }

  /* ---------- ドロワー: 3 列の対訳 ---------- */
  function buildDrawerExtra(actions, spacer) {
    var lab = el('label', { 'class': 'bm-switch drawer-tr-switch' });
    var inp = el('input', { type: 'checkbox', role: 'switch' });
    inp.checked = BM_ON;
    lab.appendChild(inp);
    lab.appendChild(el('span', null, '訳を表示'));
    inp.addEventListener('change', function () { setBM(inp.checked); });
    bmSwitches.push(inp);
    lab.hidden = true;
    drawerSwitchWrap = lab;
    actions.insertBefore(lab, spacer);
  }

  // スニペットの範囲に重なる訳のブロック（範囲の外は切り落とす）
  function trFor(sn) {
    var list = TRD[sn.path];
    if (!list) { return []; }
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var b = list[i];
      if (b.b < sn.start || b.a > sn.end) { continue; }
      out.push({ a: Math.max(b.a, sn.start), b: Math.min(b.b, sn.end), ja: b.ja });
    }
    return out;
  }

  // drawer.js の renderCode から呼ばれる。訳を出したら true（出さないときは従来の表示）
  function renderCodeTr(sn, focus) {
    var blocks = trFor(sn);
    if (drawerSwitchWrap) { drawerSwitchWrap.hidden = !blocks.length; }
    var on = BM_ON && blocks.length > 0;
    drawer.classList.toggle('has-tr', on);
    elCode.className = on ? 'tr-grid' : '';
    if (!on) { return false; }
    var lines = highlightLines(sn);
    var startAt = {};
    blocks.forEach(function (b) { startAt[b.a] = b; });
    var html = '', blk = null;
    for (var i = 0; i < lines.length; i++) {
      var n = sn.start + i;
      var first = startAt[n];
      if (first) { blk = first; }
      html += '<span class="cl' + (focus && n === focus ? ' is-focus' : '') + (first ? ' blk-first' : '') + '" data-n="' + n + '">' + lines[i] + '\n</span>';
      if (blk && n === blk.b) {
        html += '<span class="tr-cell" style="--r:' + (blk.a - sn.start + 1) + ';--n:' + (blk.b - blk.a + 1) + '">' + esc(blk.ja) + '</span>';
        blk = null;
      }
    }
    elCode.innerHTML = html;
    wrapTermsIn(elCode, false);
    return true;
  }

  function redrawDrawerCode() {
    if (!drawer || !cur || !SN[cur.key] || !drawer.classList.contains('is-open')) {
      if (drawer) { drawer.classList.remove('has-tr'); }
      return;
    }
    var st = elBody.scrollTop, sl = elBody.scrollLeft;
    renderCode(SN[cur.key], cur.focus);
    elBody.scrollTop = st; elBody.scrollLeft = sl;
  }

  /* ---------- 用語ポップアップ ---------- */
  var TERM_OK = 'p,li,td,.stop-see,.stop-say,.aid-tr,.tr-cell';
  var TERM_NO = 'code,kbd,pre,a,h1,h2,h3,h4,h5,h6,button,summary,.loc,.tid,.req,.layer,.tstat,.status,.sev,.qa-time,.stop-loc,.stop-addr,.aid-code,.conn-map,.overlap-gen,.term,.term-pop,.has-ref,.toc-list,.flow-head,.script-title,.bm-bar,.drawer-head,.drawer-note';
  var WORDCH = /[A-Za-z0-9_\-]/;

  function buildTermRe() {
    var items = [];
    GL.forEach(function (g, gi) {
      [g.term].concat(g.aliases || []).forEach(function (t) { if (t) { items.push({ t: t, gi: gi }); } });
    });
    items.sort(function (x, y) { return y.t.length - x.t.length; });   // 長い語を優先
    termMap = {};
    items.forEach(function (it) { termMap[it.t] = it.gi; });
    termRe = items.length ? new RegExp(items.map(function (it) { return it.t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|'), 'g') : null;
  }

  // 短い英数字の語は語の境界で照合する（前後が英数字・ハイフン・アンダースコアなら一致させない）
  function termBoundaryOk(text, s, e) {
    var first = text.charAt(s), last = text.charAt(e - 1);
    if (/[A-Za-z0-9]/.test(first) && s > 0 && WORDCH.test(text.charAt(s - 1))) { return false; }
    if (/[A-Za-z0-9]/.test(last) && e < text.length && WORDCH.test(text.charAt(e))) { return false; }
    return true;
  }

  // node から root の手前まで祖先をたどり、sel に合う最初の要素を返す（ドロワーの pre.code-view・code は対象外にしない）
  function upTo(node, sel, root) {
    while (node && node !== root) {
      if (node.matches && node.matches(sel)) { return node; }
      node = node.parentNode;
    }
    return null;
  }

  // root の中の地の文で、用語集の語を最初の 1 回だけボタンにする。ページは section ごと、ドロワーは描画ごと
  function wrapTermsIn(root, perSection) {
    if (!termRe || !root) { return; }
    var nodes = [];
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var n;
    while ((n = walker.nextNode())) { if (n.nodeValue && n.nodeValue.trim()) { nodes.push(n); } }
    var localSeen = {};
    nodes.forEach(function (node) {
      var p = node.parentNode;
      if (!p || !p.matches || upTo(p, TERM_NO, root) || !upTo(p, TERM_OK, root)) { return; }
      var seen = localSeen;
      if (perSection) {
        var sec = p.closest('section');
        if (!sec) { return; }
        seen = sec._termSeen || (sec._termSeen = {});
      }
      var text = node.nodeValue, last = 0, m, frag = null;
      termRe.lastIndex = 0;
      while ((m = termRe.exec(text))) {
        var s = m.index, e = s + m[0].length;
        if (!termBoundaryOk(text, s, e)) { termRe.lastIndex = s + 1; continue; }
        var gi = termMap[m[0]];
        if (seen[gi]) { continue; }
        seen[gi] = true;
        frag = frag || document.createDocumentFragment();
        if (s > last) { frag.appendChild(document.createTextNode(text.slice(last, s))); }
        frag.appendChild(el('button', { type: 'button', 'class': 'term', 'data-gi': String(gi), 'aria-haspopup': 'dialog', 'aria-expanded': 'false' }, m[0]));
        last = e;
      }
      if (frag) {
        if (last < text.length) { frag.appendChild(document.createTextNode(text.slice(last))); }
        p.replaceChild(frag, node);
      }
    });
  }

  function unwrapTerms() {
    var parents = [];
    $$('button.term').forEach(function (b) {
      var p = b.parentNode;
      p.replaceChild(document.createTextNode(b.textContent), b);
      if (parents.indexOf(p) < 0) { parents.push(p); }
    });
    parents.forEach(function (p) { p.normalize(); });
    $$('section').forEach(function (s) { s._termSeen = null; });
  }

  var pop = null, popBtn = null, popTimer = null, popByKey = false;
  function closeTermPop(restore) {
    clearTimeout(popTimer);
    if (pop && pop.parentNode) { pop.parentNode.removeChild(pop); }
    var b = popBtn;
    pop = null; popBtn = null;
    if (b) {
      b.setAttribute('aria-expanded', 'false');
      if (restore && document.contains(b) && b.focus) { b.focus(); }
    }
  }
  function schedulePopClose() {
    clearTimeout(popTimer);
    popTimer = setTimeout(function () { closeTermPop(false); }, 260);
  }
  function openTermPop(btn, focusIn) {
    var g = GL[parseInt(btn.getAttribute('data-gi'), 10)];
    if (!g) { return; }
    clearTimeout(popTimer);
    if (popBtn === btn && pop) { return; }
    closeTermPop();
    hideTip();
    pop = el('div', { 'class': 'term-pop', role: 'dialog', 'aria-label': '用語の説明: ' + g.term, tabindex: '-1' });
    pop.appendChild(el('div', { 'class': 'tp-term' }, g.term));
    pop.appendChild(el('p', { 'class': 'tp-short' }, g.short));
    if (g.analogy) {
      var pa = el('p', { 'class': 'tp-analogy' });
      pa.appendChild(el('b', null, 'たとえば'));
      pa.appendChild(document.createTextNode(g.analogy));
      pop.appendChild(pa);
    }
    if (g.ref && SN[g.ref]) {
      var rb = el('button', { type: 'button', 'class': 'btn tp-ref' }, 'コードを見る');
      rb.addEventListener('click', function () { var k = g.ref; closeTermPop(false); showRef(k, '', btn, false, 0); });
      pop.appendChild(rb);
    }
    // ドロワーの中の語は、ドロワーの子にする（ドロワーのフォーカス囲いの外に出さない）
    (btn.closest('.drawer') || document.body).appendChild(pop);
    var r = btn.getBoundingClientRect();
    var tw = pop.offsetWidth, th = pop.offsetHeight;
    var left = Math.max(8, Math.min(r.left, window.innerWidth - tw - 8));
    var top = r.bottom + 6;
    if (top + th > window.innerHeight - 8) { top = Math.max(8, r.top - th - 6); }
    pop.style.left = left + 'px'; pop.style.top = top + 'px';
    btn.setAttribute('aria-expanded', 'true');
    popBtn = btn; popByKey = !!focusIn;
    pop.addEventListener('mouseenter', function () { clearTimeout(popTimer); });
    pop.addEventListener('mouseleave', schedulePopClose);
    if (focusIn) { pop.focus(); }
  }

  function initTerms() {
    document.addEventListener('click', function (e) {
      var t = e.target.closest ? e.target.closest('button.term') : null;
      if (t) {
        e.preventDefault();
        if (popBtn === t) { closeTermPop(false); } else { openTermPop(t, e.detail === 0); }
        return;
      }
      if (pop && !pop.contains(e.target)) { closeTermPop(false); }
    });
    document.addEventListener('mouseover', function (e) {
      if (!FINE.matches || !e.target.closest) { return; }
      var t = e.target.closest('button.term');
      if (!t || (e.relatedTarget && t.contains(e.relatedTarget))) { return; }
      clearTimeout(popTimer);
      popTimer = setTimeout(function () { openTermPop(t, false); }, 220);
    });
    document.addEventListener('mouseout', function (e) {
      if (!FINE.matches || !e.target.closest) { return; }
      var t = e.target.closest('button.term');
      if (!t || (e.relatedTarget && (t.contains(e.relatedTarget) || (pop && pop.contains(e.relatedTarget))))) { return; }
      schedulePopClose();
    });
    // ドロワーの Esc（drawer.js）より先に、ポップオーバーを閉じる
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && pop) {
        e.preventDefault(); e.stopPropagation();
        closeTermPop(popByKey);
      }
    }, true);
    document.addEventListener('scroll', function (e) {
      if (pop && !(pop.contains && pop.contains(e.target))) { closeTermPop(false); }
    }, true);
  }

  /* ---------- 停留所の注目行（コードは埋め込み済みのスニペットから入れる） ---------- */
  function initAidLines() {
    $$('.stop-aid').forEach(function (a) {
      var stop = a.closest('.stop');
      var sn = stop && SN[refKey(stop)];
      var c = $('.aid-line', a);
      if (!sn || !c) { return; }
      var ln = parseInt(a.getAttribute('data-ln'), 10);
      var line = (sn.code.split('\n')[ln - sn.start] || '').replace(/^\s+/, '').replace(/\s+$/, '');
      if (line.length > 240) { line = line.slice(0, 240) + '…'; }
      c.textContent = line;
    });
  }

  /* ---------- つながり図 ---------- */
  var SVGNS = 'http://www.w3.org/2000/svg';
  function svgEl(tag, attrs) {
    var n = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }

  function initConn() {
    $$('.conn-map').forEach(function (root) {
      var ol = root.nextElementSibling;   // initRoutes が ol を包む前に結びつける
      if (!ol || !ol.matches || !ol.matches('ol.route')) { return; }
      var m = { root: root, ol: ol, stops: $$(':scope > .stop', ol), fns: $$('.conn-fn', root), grid: $('.conn-grid', root), svg: null, arrows: [], active: -1, raf: 0 };
      ol._conn = m;
      conns.push(m);
      m.fns.forEach(function (b, i) { b.addEventListener('click', function () { connGo(m, i, b); }); });
      if (window.ResizeObserver) { new window.ResizeObserver(function () { scheduleDraw(m); }).observe(m.grid); }
    });
    window.addEventListener('resize', function () { conns.forEach(scheduleDraw); });
    window.addEventListener('load', function () { conns.forEach(scheduleDraw); });
    if (document.fonts && document.fonts.ready) { document.fonts.ready.then(function () { conns.forEach(scheduleDraw); }); }
  }

  function connGo(m, i, btn) {
    var s = m.stops[i];
    if (!s) { return; }
    if (s.scrollIntoView) { s.scrollIntoView({ block: 'center', behavior: RM.matches ? 'auto' : 'smooth' }); }
    s.classList.add('is-flash');
    clearTimeout(s._flash);
    s._flash = setTimeout(function () { s.classList.remove('is-flash'); }, 2400);
    var key = refKey(s);
    if (SN[key]) { showRef(key, s.getAttribute('data-note') || '', btn, false, focusOf(s)); }
  }

  // 順路の「流れを再生」から呼ばれる。i 番目の箱と、そこへ向かう矢印を光らせる（-1 で消す）
  function connActive(ol, i) {
    var m = ol._conn;
    if (!m) { return; }
    m.active = i;
    applyActive(m);
  }
  function applyActive(m) {
    m.fns.forEach(function (b, k) { b.classList.toggle('is-active', k === m.active); });
    m.arrows.forEach(function (a) { a.g.classList.toggle('is-active', a.i === m.active); });
  }

  function scheduleDraw(m) {
    if (m.raf) { return; }
    m.raf = window.requestAnimationFrame(function () { m.raf = 0; drawConn(m); });
  }

  function drawConn(m) {
    var g = m.grid;
    if (!g || !g.offsetWidth || !m.fns.length) { return; }
    if (m.svg && m.svg.parentNode) { m.svg.parentNode.removeChild(m.svg); }
    var W = g.offsetWidth, H = g.offsetHeight;
    var svg = svgEl('svg', { 'class': 'conn-svg', 'aria-hidden': 'true', focusable: 'false', width: W, height: H, viewBox: '0 0 ' + W + ' ' + H });
    g.appendChild(svg);
    m.svg = svg; m.arrows = [];
    var gr = g.getBoundingClientRect();
    function rel(node) {
      var r = node.getBoundingClientRect();
      return { l: r.left - gr.left - g.clientLeft, r: r.right - gr.left - g.clientLeft, t: r.top - gr.top - g.clientTop, b: r.bottom - gr.top - g.clientTop };
    }
    var labels = [];
    for (var i = 1; i < m.fns.length; i++) {
      var a = m.fns[i - 1], b = m.fns[i];
      var ra = rel(a), rb = rel(b);
      // 矢印は箱の右寄りから出入りさせる（左寄りのファイル名・フォルダ名の文字に線が重ならないように）
      var x1 = ra.r - Math.min(16, (ra.r - ra.l) * 0.2), y1 = ra.b, x2 = rb.r - Math.min(16, (rb.r - rb.l) * 0.2), y2 = rb.t - 1;
      var ye = Math.max(y1 + 8, y2 - 9);
      var d = (ye - y1) / 2;
      // ラベルは、2 つの箱が別々の入れ子に分かれる境目（箱と箱のすき間）の中央に置く
      var lca = a.parentNode;
      while (lca && !lca.contains(b)) { lca = lca.parentNode; }
      var sa = a, sb = b;
      while (sa.parentNode !== lca) { sa = sa.parentNode; }
      while (sb.parentNode !== lca) { sb = sb.parentNode; }
      var rs = rel(sa), rt = rel(sb);
      var ly = rs.b < rt.t ? (rs.b + rt.t) / 2 : (y1 + y2) / 2;
      // 曲線上で y が ly に最も近い点の x
      var bestX = (x1 + x2) / 2, bestDy = 1e9;
      for (var k = 0; k <= 50; k++) {
        var t = k / 50, u = 1 - t;
        var cy = u * u * u * y1 + 3 * u * u * t * (y1 + d) + 3 * u * t * t * (ye - d) + t * t * t * ye;
        var cx = u * u * u * x1 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x2;
        if (Math.abs(cy - ly) < bestDy) { bestDy = Math.abs(cy - ly); bestX = cx; }
      }
      var ga = svgEl('g', { 'class': 'conn-arrow' });
      ga.appendChild(svgEl('path', { 'class': 'conn-line', d: 'M' + x1 + ' ' + y1 + ' C' + x1 + ' ' + (y1 + d) + ' ' + x2 + ' ' + (ye - d) + ' ' + x2 + ' ' + ye }));
      ga.appendChild(svgEl('path', { 'class': 'conn-tri', d: 'M' + x2 + ' ' + y2 + ' L' + (x2 - 5) + ' ' + (y2 - 9) + ' L' + (x2 + 5) + ' ' + (y2 - 9) + ' Z' }));
      svg.appendChild(ga);
      m.arrows.push({ g: ga, i: i });
      var text = b.getAttribute('data-link');
      if (text) {
        var bg = svgEl('rect', { 'class': 'conn-lbl-bg', rx: 4, ry: 4 });
        var tx = svgEl('text', { 'class': 'conn-lbl', 'text-anchor': 'middle' });
        tx.textContent = text;
        ga.appendChild(bg); ga.appendChild(tx);
        var bb = tx.getBBox();
        var w = bb.width + 12, h = bb.height + 6;
        var cxl = Math.max(w / 2 + 2, Math.min(bestX, W - w / 2 - 2));
        labels.push({ bg: bg, tx: tx, cx: cxl, cy: ly, w: w, h: h });
      }
    }
    // ラベルどうしが縦横とも重なるときは、下のものを下へずらす
    labels.sort(function (p, q) { return p.cy - q.cy; });
    labels.forEach(function (lb, idx) {
      if (idx > 0) {
        var pv = labels[idx - 1];
        if (Math.abs(lb.cx - pv.cx) < (lb.w + pv.w) / 2 && lb.cy - pv.cy < (lb.h + pv.h) / 2 + 2) {
          lb.cy = pv.cy + (lb.h + pv.h) / 2 + 2;
        }
      }
      lb.bg.setAttribute('x', lb.cx - lb.w / 2); lb.bg.setAttribute('y', lb.cy - lb.h / 2);
      lb.bg.setAttribute('width', lb.w); lb.bg.setAttribute('height', lb.h);
      lb.tx.setAttribute('x', lb.cx); lb.tx.setAttribute('y', lb.cy);
    });
    applyActive(m);
  }

  function initAid() {
    bmLoad();
    TRD = {};
    var tr = readJson('translations-data', {});
    Object.keys(tr).forEach(function (p) { TRD[p] = tr[p].map(function (x) { return { a: x[0], b: x[1], ja: x[2] }; }); });
    GL = readJson('glossary-data', []);
    buildTermRe();
    var main = document.getElementById('bm-main');
    if (main) {
      bmSwitches.push(main);
      main.addEventListener('change', function () { setBM(main.checked); });
    }
    initAidLines();
    initConn();
    initTerms();
    setBM(BM_ON, true);
  }
