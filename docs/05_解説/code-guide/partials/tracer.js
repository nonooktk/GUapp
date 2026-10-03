  /* ---------------------------------------------------------------
     コードトレーサー
     左: アプリの画面写真と hotspot ／ 右: IDE 風（層の帯・ファイル一覧・エディター・解説/流れ/通信/DB）
     データは build.py が #tracer-data（JSON）と script[data-file]（コード全文）・script[data-image]（画像）に埋め込む
  --------------------------------------------------------------- */
  var D = {};
  try { D = JSON.parse(document.getElementById('tracer-data').textContent) || {}; } catch (e) { D = {}; }
  document.documentElement.classList.add('js');

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (html != null) { n.innerHTML = html; }
    return n;
  }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function baseName(p) { return p.split('/').pop(); }
  function extOf(p) { var b = baseName(p); return b.indexOf('.') > 0 ? b.split('.').pop().toUpperCase() : ''; }
  var RM = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  var FINE = window.matchMedia ? window.matchMedia('(hover: hover) and (pointer: fine)') : { matches: false };
  var NARROW = window.matchMedia ? window.matchMedia('(max-width: 899.98px)') : { matches: false };
  function store(k, v) { try { if (v === undefined) { return window.localStorage.getItem(k); } window.localStorage.setItem(k, v); } catch (e) { /* 保存できなくても動く */ } return null; }

  /* ---------- データ ---------- */
  var STATE = {}, IMG = {}, SRC = {}, FILES = D.files || {};
  (D.states || []).forEach(function (s) { STATE[s.id] = s; });
  $$('script[data-image]').forEach(function (s) { IMG[s.getAttribute('data-image')] = s.textContent.replace(/\s+/g, ''); });
  $$('script[data-file]').forEach(function (s) { SRC[s.getAttribute('data-file')] = s; });
  var LAYER_LABEL = {};
  (D.layers || []).forEach(function (l) { LAYER_LABEL[l.id] = l.label; });
  function layerName(id) { return LAYER_LABEL[id] || id || 'その他'; }

  function getFile(path) {
    var f = FILES[path];
    if (!f) { return null; }
    if (!f.lines) {
      var node = SRC[path];
      // コード本体は原文のまま置いてある。`</script` と `<!--` の `<` の後ろにだけバックスラッシュを足してあるので、1 つ引いて戻す
      f.text = node ? node.textContent.replace(/<(\\+)(\/script|!--)/gi, function (m, bs, tail) { return '<' + bs.slice(1) + tail; }) : '';
      f.lines = f.text.split('\n');
      f.tr = (f.tr || []).map(function (b) { return { a: b[0], b: b[1], ja: b[2] }; });
    }
    return f;
  }

  /* ---------- ハイライト（hljs があれば。無ければ素のテキスト） ---------- */
  function splitHighlighted(html) {
    var open = [], out = [];
    html.split('\n').forEach(function (line) {
      var prefix = open.join('');
      var re = /<span[^>]*>|<\/span>/g, m;
      while ((m = re.exec(line))) {
        if (m[0].charAt(1) === '/') { open.pop(); } else { open.push(m[0]); }
      }
      var closes = '';
      for (var i = 0; i < open.length; i++) { closes += '</span>'; }
      out.push(prefix + line + closes);
    });
    return out;
  }
  function hlReady() { return !!(window.hljs && window.hljs.highlight && window.hljs.getLanguage); }
  function hlLines(f) {
    if (f.hl) { return f.hl; }
    var out = null;
    if (hlReady() && f.lang && f.lang !== 'plaintext' && window.hljs.getLanguage(f.lang)) {
      try {
        var lines = splitHighlighted(window.hljs.highlight(f.text, { language: f.lang, ignoreIllegals: true }).value);
        if (lines.length === f.lines.length) { out = lines; }
      } catch (e) { /* 素のテキストで表示する */ }
    }
    f.hl = out || f.lines.map(esc);
    f.hlDone = !!out;
    return f.hl;
  }
  function hlJson(value) {
    var text = JSON.stringify(value, null, 2);
    if (hlReady() && window.hljs.getLanguage('json')) {
      try { return window.hljs.highlight(text, { language: 'json', ignoreIllegals: true }).value; } catch (e) { /* 素のテキスト */ }
    }
    return esc(text);
  }

  /* ---------- 状態 ---------- */
  var S = {
    id: null, trace: null, g: 0, i: 0,
    vis: [],              // 群ごと: { order: [path], last: {path: idx} }
    op: '',               // 「商品カード を押した」などの操作の説明
    imgSeq: [], imgPos: 0, imgStart: 0,
    pressed: {},          // 'stateId#hotspotIdx' → true
    done: {},             // 最後まで進んだ action
    playing: false, timer: 0,
    trOn: true, tab: 'explain', exp: {},
    ed: null              // いま描画しているエディターの { g, path }
  };

  function realOf(a) {
    var al = (D.aliases || {})[a];
    return al ? { action: al.action, stop: al.stop, alias: true } : { action: a, stop: 1, alias: false };
  }
  function grp() { return S.trace.groups[S.g]; }
  function stopNow() { return grp().stops[S.i]; }
  function lastIdx() { return grp().stops.length - 1; }

  /* ---------- 用語ポップアップ（解説パネルの地の文） ---------- */
  var GL = D.glossary || [], termRe = null, termMap = {};
  var WORDCH = /[A-Za-z0-9_\-]/;
  (function buildTermRe() {
    var items = [];
    GL.forEach(function (g, gi) { [g.term].concat(g.aliases || []).forEach(function (t) { if (t) { items.push({ t: t, gi: gi }); } }); });
    items.sort(function (x, y) { return y.t.length - x.t.length; });
    items.forEach(function (it) { termMap[it.t] = it.gi; });
    termRe = items.length ? new RegExp(items.map(function (it) { return it.t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|'), 'g') : null;
  })();
  function termBoundaryOk(text, s, e) {
    var first = text.charAt(s), last = text.charAt(e - 1);
    if (/[A-Za-z0-9]/.test(first) && s > 0 && WORDCH.test(text.charAt(s - 1))) { return false; }
    if (/[A-Za-z0-9]/.test(last) && e < text.length && WORDCH.test(text.charAt(e))) { return false; }
    return true;
  }
  function wrapTerms(root) {
    if (!termRe || !root) { return; }
    var nodes = [], walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null), n;
    while ((n = walker.nextNode())) { if (n.nodeValue && n.nodeValue.trim()) { nodes.push(n); } }
    var seen = {};
    nodes.forEach(function (node) {
      var p = node.parentNode;
      if (!p || (p.closest && p.closest('code,kbd,button,.tag,.exp-head,.op'))) { return; }
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
        var b = el('button', 'term', esc(m[0]));
        b.type = 'button'; b.setAttribute('data-gi', String(gi)); b.setAttribute('aria-haspopup', 'dialog'); b.setAttribute('aria-expanded', 'false');
        frag.appendChild(b);
        last = e;
      }
      if (frag) {
        if (last < text.length) { frag.appendChild(document.createTextNode(text.slice(last))); }
        p.replaceChild(frag, node);
      }
    });
  }
  var pop = null, popBtn = null, popTimer = 0, popByKey = false;
  function closePop(restore) {
    clearTimeout(popTimer);
    if (pop && pop.parentNode) { pop.parentNode.removeChild(pop); }
    var b = popBtn;
    pop = null; popBtn = null;
    if (b) {
      b.setAttribute('aria-expanded', 'false');
      if (restore && document.contains(b) && b.focus) { b.focus(); }
    }
  }
  function openPop(btn, focusIn) {
    var g = GL[parseInt(btn.getAttribute('data-gi'), 10)];
    if (!g) { return; }
    clearTimeout(popTimer);
    if (popBtn === btn && pop) { return; }
    closePop();
    pop = el('div', 'term-pop');
    pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', '用語の説明: ' + g.term); pop.tabIndex = -1;
    pop.appendChild(el('div', 'tp-term', esc(g.term)));
    pop.appendChild(el('p', 'tp-short', esc(g.short)));
    if (g.analogy) { pop.appendChild(el('p', 'tp-analogy', '<b>たとえば</b>' + esc(g.analogy))); }
    document.body.appendChild(pop);
    var r = btn.getBoundingClientRect(), tw = pop.offsetWidth, th = pop.offsetHeight;
    var left = Math.max(8, Math.min(r.left, window.innerWidth - tw - 8)), top = r.bottom + 6;
    if (top + th > window.innerHeight - 8) { top = Math.max(8, r.top - th - 6); }
    pop.style.left = left + 'px'; pop.style.top = top + 'px';
    btn.setAttribute('aria-expanded', 'true');
    popBtn = btn; popByKey = !!focusIn;
    pop.addEventListener('mouseenter', function () { clearTimeout(popTimer); });
    pop.addEventListener('mouseleave', function () { popTimer = setTimeout(function () { closePop(false); }, 260); });
    if (focusIn) { pop.focus(); }
  }
  function initTerms() {
    document.addEventListener('click', function (e) {
      var t = e.target.closest ? e.target.closest('button.term') : null;
      if (t) { e.preventDefault(); if (popBtn === t) { closePop(false); } else { openPop(t, e.detail === 0); } return; }
      if (pop && !pop.contains(e.target)) { closePop(false); }
    });
    document.addEventListener('mouseover', function (e) {
      if (!FINE.matches || !e.target.closest) { return; }
      var t = e.target.closest('button.term');
      if (!t || (e.relatedTarget && t.contains(e.relatedTarget))) { return; }
      clearTimeout(popTimer);
      popTimer = setTimeout(function () { openPop(t, false); }, 220);
    });
    document.addEventListener('mouseout', function (e) {
      if (!FINE.matches || !e.target.closest) { return; }
      var t = e.target.closest('button.term');
      if (!t || (e.relatedTarget && (t.contains(e.relatedTarget) || (pop && pop.contains(e.relatedTarget))))) { return; }
      clearTimeout(popTimer);
      popTimer = setTimeout(function () { closePop(false); }, 260);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && pop) { e.preventDefault(); closePop(popByKey); }
    }, true);
    document.addEventListener('scroll', function (e) { if (pop && !(pop.contains && pop.contains(e.target))) { closePop(false); } }, true);
  }

  /* ---------------------------------------------------------------
     左: 画面写真
  --------------------------------------------------------------- */
  var elShot = $('#shot'), elPhone = $('#phone-scroll'), elSname = $('#sname'), elSpath = $('#spath'), elOp = $('#opline');

  function curStateId() { return S.imgSeq[S.imgPos]; }

  function primaryIndex(st) {
    var flow = D.flow || [], best = -1, bestRank = 1e9;
    (st.hotspots || []).forEach(function (h, i) {
      if (S.pressed[st.id + '#' + i]) { return; }
      var real = realOf(h.action).action, r = flow.indexOf(real);
      if (r < 0 || S.done[real]) { return; }
      if (r < bestRank) { bestRank = r; best = i; }
    });
    return best;
  }

  function renderPhone(keepScroll) {
    var st = STATE[curStateId()];
    if (!st) { return; }
    elSname.textContent = st.title || st.id;
    elSpath.textContent = st.path || '';
    var uri = IMG[st.id], changed = S.shownState !== st.id, keepTop = elPhone.scrollTop;
    S.shownState = st.id;
    elShot.style.aspectRatio = st.width + ' / ' + st.height;
    elShot.innerHTML = '';
    var img = el('img');
    img.alt = (st.title || st.id) + 'の画面写真';
    img.draggable = false;
    if (uri) { img.src = uri; }
    elShot.appendChild(img);
    var prim = primaryIndex(st), primEl = null;
    (st.hotspots || []).forEach(function (h, i) {
      var b = el('button', 'hs');
      b.type = 'button';
      b.style.left = (h.x / st.width * 100) + '%'; b.style.top = (h.y / st.height * 100) + '%';
      b.style.width = (h.w / st.width * 100) + '%'; b.style.height = (h.h / st.height * 100) + '%';
      var pressed = !!S.pressed[st.id + '#' + i];
      if (pressed) { b.classList.add('is-pressed'); }
      if (i === prim) { b.classList.add('is-primary'); primEl = b; }
      b.title = h.label + 'を押す';
      b.setAttribute('aria-label', h.label + 'を押す' + (pressed ? '（押した）' : '') + (i === prim ? '（次に押すところ）' : ''));
      b.addEventListener('click', function () { pressHotspot(st, i); });
      elShot.appendChild(b);
    });
    if (keepScroll || !changed) { elPhone.scrollTop = keepTop; }
    else {
      var top = 0;
      if (primEl) { top = Math.max(0, primEl.offsetTop - elPhone.clientHeight * 0.3); }
      elPhone.scrollTop = top;
    }
    renderOpline();
  }

  function renderOpline() {
    var show = S.op && S.id !== 'initial';
    elOp.hidden = !show;
    if (!show) { return; }
    var seqLast = S.imgPos >= S.imgSeq.length - 1;
    elOp.innerHTML = '<b>操作</b>' + esc(S.op);
    if (!seqLast) {
      var nxt = STATE[S.imgSeq[S.imgPos + 1]];
      var b = el('button', 'btn', '次の画面へ' + (nxt ? '（' + esc(nxt.title) + '）' : ''));
      b.type = 'button';
      b.addEventListener('click', function () { nextScreen(); });
      elOp.appendChild(b);
    }
  }

  function nextScreen() {
    if (S.imgPos < S.imgSeq.length - 1) { S.imgPos++; renderPhone(false); }
  }

  function pressHotspot(st, idx) {
    var h = st.hotspots[idx], real = realOf(h.action);
    S.pressed[st.id + '#' + idx] = true;
    var spec = D.traces[real.action];
    if (!spec) {
      // 順路が無い操作: 次の画面へ移るだけ
      S.op = h.label + 'を押す（この操作の順路はありません）';
      S.imgSeq = [st.id]; if (h.next) { S.imgSeq.push(h.next); }
      S.imgPos = S.imgSeq.length - 1; S.imgStart = S.imgPos;
      renderPhone(false); renderOpline();
      return;
    }
    var running = S.id === real.action && (S.g > 0 || S.i < lastIdx());
    var ac = (D.actions || {})[real.action] || (D.actions || {})[h.action] || {};
    var endState = ac.to || h.next || st.id;
    if (!running) {
      startTrace(real.action, h.label + 'を押す');
      var seq = [st.id];
      var mid = h.next && h.next !== endState && h.next !== st.id;
      if (mid) { seq.push(h.next); }
      if (seq[seq.length - 1] !== endState) { seq.push(endState); }
      S.imgSeq = seq; S.imgPos = mid ? 1 : 0; S.imgStart = S.imgPos;
      if (real.alias && real.stop > 1) { go(0, real.stop - 1); }
    } else if (real.alias && real.stop > 1) {
      S.op = h.label + 'を押す';
      go(0, real.stop - 1);
    }
    // 同じ action の hotspot が複数あるときは、すべて押す（または最後の 1 つを押す）と次の画面へ進む
    var same = [];
    st.hotspots.forEach(function (x, k) { if (x.action === h.action) { same.push(k); } });
    if (same.length > 1) {
      var all = same.every(function (k) { return S.pressed[st.id + '#' + k]; });
      if (all || same[same.length - 1] === idx) { S.imgPos = S.imgSeq.length - 1; }
    }
    renderPhone(false);
    renderStop();
  }

  /* ---------------------------------------------------------------
     トレースの開始・移動
  --------------------------------------------------------------- */
  function startTrace(id, opText) {
    stopPlay();
    closePop(false);
    S.id = id; S.trace = D.traces[id];
    S.g = 0; S.i = 0; S.mainI = 0; S.vis = []; S.exp = {}; S.ed = null;
    S.op = opText || '';
    S.trace.groups.forEach(function () { S.vis.push({ order: [], last: {} }); });
    markVisit();
    var ac = (D.actions || {})[id];
    var hasDb = !!(ac && ac.db);
    $('#tab-db').hidden = !hasDb;
    if (!hasDb && S.tab === 'db') { setTab('explain'); }
    buildFlow(); buildNet(); buildDb();
    buildGroupUi();
    renderStop();
  }

  function markVisit() {
    var s = stopNow(), v = S.vis[S.g];
    if (v.order.indexOf(s.path) < 0) { v.order.push(s.path); }
    v.last[s.path] = S.i;
  }

  function go(g, i) {
    var wasEnd = S.g === 0 && S.i === lastIdx();
    var gChanged = g !== S.g;
    S.g = g; S.i = i;
    if (g === 0) { S.mainI = i; }
    markVisit();
    if (gChanged) { S.ed = null; buildGroupUi(); }
    // 本筋の最後に着いたら写真を最後の状態へ。そこから戻ったら、開始時の写真に戻す
    var isEnd = S.g === 0 && S.i === lastIdx();
    if (isEnd && S.imgSeq.length) {
      S.done[S.id] = true;
      if (S.imgPos !== S.imgSeq.length - 1) { S.imgPos = S.imgSeq.length - 1; renderPhone(false); }
    } else if (wasEnd && !isEnd && S.imgPos > S.imgStart) {
      S.imgPos = S.imgStart; renderPhone(false);
    }
    renderStop();
  }
  function next() { if (S.i < lastIdx()) { go(S.g, S.i + 1); return true; } return false; }
  function prev() { if (S.i > 0) { go(S.g, S.i - 1); return true; } return false; }

  /* ---------- 自動再生 ---------- */
  var elPlay = $('#btn-play');
  function stopPlay() {
    S.playing = false; clearTimeout(S.timer);
    if (elPlay) { elPlay.textContent = '▶ 自動再生'; elPlay.setAttribute('aria-pressed', 'false'); }
  }
  function tick() {
    if (!S.playing) { return; }
    if (!next()) { stopPlay(); return; }
    S.timer = setTimeout(tick, 2500);
  }
  function startPlay() {
    if (S.i >= lastIdx()) { go(S.g, 0); }
    S.playing = true;
    elPlay.textContent = '■ 停止'; elPlay.setAttribute('aria-pressed', 'true');
    S.timer = setTimeout(tick, 2500);
  }

  /* ---------------------------------------------------------------
     右: 層の帯・リンク・位置
  --------------------------------------------------------------- */
  var elLayers = $('#layers'), elLink = $('#linkline'), elPos = $('#pos');

  function buildLayers() {
    var used = {};
    S.trace.groups.forEach(function (g) { g.stops.forEach(function (s) { used[s.layer || ''] = true; }); });
    elLayers.innerHTML = '';
    (D.layers || []).forEach(function (l) {
      if (l.id === 'infra' && !used.infra) { return; }
      var b = el('span', 'lyr', esc(l.label));
      b.setAttribute('role', 'listitem'); b.setAttribute('data-layer', l.id); b.setAttribute('data-l', l.id);
      elLayers.appendChild(b);
    });
  }

  function renderHeader() {
    var s = stopNow();
    $$('.lyr', elLayers).forEach(function (n) {
      var on = n.getAttribute('data-l') === s.layer;
      n.classList.toggle('is-on', on);
      if (on) { n.setAttribute('aria-current', 'step'); } else { n.removeAttribute('aria-current'); }
    });
    var link = s.link;
    var head = '前から来た経路';
    if (S.i === 0) {
      head = '起点';
      if (grp().extra) { link = '別ルート（参考）: ' + (grp().routes[0].label || grp().routes[0].title); }
      else if (S.id === 'initial') { link = 'ページを開く（Next.js のサーバーが画面を組み立てる）'; }
      else { link = S.op || (S.trace.title || ''); }
    }
    elLink.innerHTML = '<b>' + head + '：</b><span class="lk">' + esc(link || '') + '</span>';
    var n = grp().stops.length;
    elPos.textContent = (grp().extra ? '参考 ' : '') + (S.i + 1) + ' / ' + n;
    $('#btn-prev').disabled = S.i <= 0;
    $('#btn-next').disabled = S.i >= lastIdx();
    $('#btn-main').hidden = !grp().extra;
  }

  /* ---------------------------------------------------------------
     右: ファイル一覧・タブ・エディター
  --------------------------------------------------------------- */
  var elTree = $('#filetree'), elTabs = $('#tabs'), elCrumb = $('#crumb'), elCode = $('#code');

  function groupPaths(g) {
    var order = [], count = {};
    S.trace.groups[g].stops.forEach(function (s, i) {
      if (!(s.path in count)) { order.push(s.path); count[s.path] = { n: 0, first: i }; }
      count[s.path].n++;
    });
    return { order: order, count: count };
  }

  function buildTreeUi() {
    var gp = groupPaths(S.g), root = { dirs: {}, files: [] };
    gp.order.slice().sort().forEach(function (p) {
      var parts = p.split('/'), node = root;
      for (var k = 0; k < parts.length - 1; k++) { node = node.dirs[parts[k]] || (node.dirs[parts[k]] = { dirs: {}, files: [] }); }
      node.files.push(p);
    });
    function render(node) {
      var ul = el('ul');
      Object.keys(node.dirs).sort().forEach(function (name) {
        var d = node.dirs[name], label = name;
        // 子が 1 つのフォルダだけが続くときは、1 行にまとめる（apps/web/lib/server）
        while (!d.files.length && Object.keys(d.dirs).length === 1) {
          var only = Object.keys(d.dirs)[0]; label += '/' + only; d = d.dirs[only];
        }
        var li = el('li');
        li.appendChild(el('span', 'ft-dir', esc(label)));
        li.appendChild(render(d));
        ul.appendChild(li);
      });
      node.files.forEach(function (p) {
        var li = el('li'), b = el('button', 'ft-file');
        b.type = 'button'; b.setAttribute('data-path', p); b.title = p;
        b.innerHTML = '<span class="nm">' + esc(baseName(p)) + '</span><span class="cnt">' + gp.count[p].n + '</span>';
        b.addEventListener('click', function () { go(S.g, gp.count[p].first); });
        li.appendChild(b); ul.appendChild(li);
      });
      return ul;
    }
    elTree.innerHTML = '';
    elTree.appendChild(render(root));
  }

  function renderTreeNow() {
    var v = S.vis[S.g], now = stopNow().path;
    $$('.ft-file', elTree).forEach(function (b) {
      var p = b.getAttribute('data-path');
      b.classList.toggle('is-now', p === now);
      b.classList.toggle('is-seen', p !== now && v.order.indexOf(p) >= 0);
      if (p === now) { b.setAttribute('aria-current', 'true'); } else { b.removeAttribute('aria-current'); }
    });
  }

  function renderTabs() {
    var v = S.vis[S.g], now = stopNow().path;
    elTabs.innerHTML = '';
    v.order.forEach(function (p) {
      var b = el('button', 'tab' + (p === now ? ' is-now' : ''));
      b.type = 'button'; b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', p === now ? 'true' : 'false'); b.title = p;
      var ext = extOf(p);
      b.innerHTML = (ext ? '<span class="ext">' + esc(ext) + '</span>' : '') + '<span class="nm">' + esc(baseName(p)) + '</span>';
      b.addEventListener('click', function () { go(S.g, v.last[p]); });
      elTabs.appendChild(b);
      if (p === now && b.scrollIntoView) { try { b.scrollIntoView({ block: 'nearest', inline: 'nearest' }); } catch (e) { /* 古いブラウザ */ } }
    });
  }

  function renderCrumb() {
    var s = stopNow(), parts = s.path.split('/'), out = [];
    parts.forEach(function (x, k) {
      if (k === parts.length - 1) {
        var ext = extOf(s.path);
        out.push((ext ? '<span class="ext">' + esc(ext) + '</span> ' : '') + esc(x));
      } else { out.push(esc(x)); }
    });
    elCrumb.innerHTML = out.join('<span class="sep">›</span>') + '<span class="sep">›</span><span class="fn">' + esc(s.label) + '</span>' + ' <span class="sep">L' + s.start + '-' + s.end + '</span>';
  }

  // この群でそのファイルを通る範囲（停留所の data-ref の範囲の和集合）
  function rangesFor(g, path) {
    var key = g + '|' + path, c = S.rcache || (S.rcache = {});
    if (S.rcacheTrace !== S.id) { S.rcache = c = {}; S.rcacheTrace = S.id; }
    if (c[key]) { return c[key]; }
    var rs = [];
    S.trace.groups[g].stops.forEach(function (s) { if (s.path === path) { rs.push([s.start, s.end]); } });
    rs.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var merged = [];
    rs.forEach(function (r) {
      var l = merged[merged.length - 1];
      if (l && r[0] <= l[1] + 1) { l[1] = Math.max(l[1], r[1]); } else { merged.push([r[0], r[1]]); }
    });
    return (c[key] = merged);
  }

  function buildEditor(path) {
    var f = getFile(path), N = f ? f.lines.length : 0;
    if (!f) { elCode.innerHTML = '<div class="code-empty">このファイルのコードは埋め込まれていません: ' + esc(path) + '</div>'; S.rows = []; return; }
    var ranges = rangesFor(S.g, path), vis = new Uint8Array(N + 2), gaps = [], cur = 1, k;
    ranges.forEach(function (r) {
      if (r[0] > cur) { gaps.push([cur, r[0] - 1]); }
      for (k = r[0]; k <= Math.min(r[1], N); k++) { vis[k] = 1; }
      cur = r[1] + 1;
    });
    if (cur <= N) { gaps.push([cur, N]); }
    var gapAt = {};
    gaps.forEach(function (gp) {
      var key = S.g + '|' + path + '|' + gp[0];
      gp.key = key;
      if (S.exp[key]) { for (k = gp[0]; k <= gp[1]; k++) { vis[k] = 2; } gapAt[gp[0]] = gp; }
    });
    // 訳: 各ブロックの、画面に出ている最後の行の直後に 1 段で入れる
    var trAt = {};
    f.tr.forEach(function (b) {
      for (var n = Math.min(b.b, N); n >= b.a; n--) { if (vis[n]) { (trAt[n] = trAt[n] || []).push(b.ja); break; } }
    });
    var hl = hlLines(f), html = '', n = 1;
    while (n <= N) {
      if (vis[n]) {
        if (gapAt[n]) { html += '<button type="button" class="fold open" data-key="' + esc(gapAt[n].key) + '">▲ ' + (gapAt[n][1] - gapAt[n][0] + 1) + ' 行を畳む</button>'; }
        html += '<div class="cl' + (vis[n] === 2 ? ' ex' : '') + '" data-n="' + n + '">' + hl[n - 1] + '</div>';
        if (trAt[n]) { trAt[n].forEach(function (ja) { html += '<div class="tr">' + esc(ja) + '</div>'; }); }
        n++;
      } else {
        var e = n;
        while (e + 1 <= N && !vis[e + 1]) { e++; }
        var gk = S.g + '|' + path + '|' + n;
        html += '<button type="button" class="fold" data-key="' + esc(gk) + '" aria-label="' + (e - n + 1) + ' 行を開く（この流れでは通らない）">… ' + (e - n + 1) + ' 行（この流れでは通らない）</button>';
        n = e + 1;
      }
    }
    elCode.innerHTML = '<div class="code-view hljs">' + html + '</div>';
    S.rows = [];
    $$('.cl', elCode).forEach(function (r) { S.rows[parseInt(r.getAttribute('data-n'), 10)] = r; });
    S.edHl = f.hlDone;
    elCode.style.setProperty('--pw', elCode.clientWidth + 'px');
  }

  function renderEditor(forceScroll) {
    var s = stopNow(), same = S.ed && S.ed.g === S.g && S.ed.path === s.path;
    if (!same) { buildEditor(s.path); S.ed = { g: S.g, path: s.path }; elCode.scrollLeft = 0; }
    $$('.cl.foc, .cl.rng', elCode).forEach(function (r) { r.classList.remove('foc'); r.classList.remove('rng'); });
    for (var n = s.start; n <= s.end; n++) { if (S.rows[n]) { S.rows[n].classList.add('rng'); } }
    var fr = S.rows[s.focus];
    if (fr) {
      fr.classList.add('foc');
      var top = fr.getBoundingClientRect().top - elCode.getBoundingClientRect().top + elCode.scrollTop - elCode.clientHeight * 0.33;
      elCode.scrollTo({ top: Math.max(0, top), behavior: (RM.matches || !same) ? 'auto' : 'smooth' });
    }
  }

  function onFoldClick(e) {
    var b = e.target.closest ? e.target.closest('button.fold') : null;
    if (!b) { return; }
    var key = b.getAttribute('data-key');
    var offset = b.getBoundingClientRect().top - elCode.getBoundingClientRect().top;
    if (S.exp[key]) { delete S.exp[key]; } else { S.exp[key] = true; }
    var s = stopNow();
    buildEditor(s.path);
    var firstLine = parseInt(key.split('|')[2], 10);
    var target = S.rows[firstLine] || null;
    if (!target) { // 畳んだとき: 畳み行の位置を保つ
      var fb = elCode.querySelector('button.fold[data-key="' + key.replace(/"/g, '\\"') + '"]');
      target = fb;
    }
    if (target) { elCode.scrollTop = target.getBoundingClientRect().top - elCode.getBoundingClientRect().top + elCode.scrollTop - offset; }
    $$('.cl.foc, .cl.rng', elCode).forEach(function (r) { r.classList.remove('foc'); r.classList.remove('rng'); });
    for (var n = s.start; n <= s.end; n++) { if (S.rows[n]) { S.rows[n].classList.add('rng'); } }
    if (S.rows[s.focus]) { S.rows[s.focus].classList.add('foc'); }
  }

  /* ---------------------------------------------------------------
     下のパネル
  --------------------------------------------------------------- */
  var PANELS = ['explain', 'flow', 'net', 'db'];
  function setTab(name) {
    S.tab = name;
    PANELS.forEach(function (p) {
      var t = $('#tab-' + p), body = $('#p-' + p);
      var on = p === name;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      body.hidden = !on;
    });
    if (name === 'flow') { scrollFlowToNow(); }
  }

  function renderExplain() {
    var s = stopNow(), box = $('#p-explain');
    var gp = grp();
    var head = '<div class="exp-head" data-layer="' + esc(s.layer) + '"><span class="no">' + (S.i + 1) + '/' + gp.stops.length + '</span>'
      + '<span class="layer" data-layer="' + esc(s.layer) + '">' + esc(layerName(s.layer)) + '</span>'
      + '<span class="path">' + esc(s.path) + ':' + s.focus + '</span><span class="fnn">' + esc(s.label) + '</span></div>';
    var op = '';
    if (gp.extra) { op = '<p class="op">別ルート（参考）: ' + esc(gp.routes[0].label || gp.routes[0].title) + '。本筋の流れではありません。</p>'; }
    else if (S.i === 0 && S.op && S.id !== 'initial') { op = '<p class="op">操作: ' + esc(S.op) + '</p>'; }
    box.innerHTML = op + head
      + (s.see ? '<p class="exp-see"><span class="tag see">見る</span>' + s.see + '</p>' : '')
      + (s.say ? '<p class="exp-say"><span class="tag say">言う</span>' + s.say + '</p>' : '')
      + (s.next ? '<p class="exp-next"><span class="tag next">次へ</span>' + s.next + '</p>' : '');
    $$('.exp-see,.exp-say', box).forEach(wrapTerms);
    closePop(false);
  }

  function stopRowHtml(s, g, i) {
    return '<button type="button" class="fl" data-g="' + g + '" data-i="' + i + '" data-layer="' + esc(s.layer) + '">'
      + '<span class="no">' + (i + 1) + '</span><span class="layer" data-layer="' + esc(s.layer) + '">' + esc(layerName(s.layer)) + '</span>'
      + '<span class="fn">' + esc(s.label) + '</span><span class="loc">' + esc(s.path) + ':' + s.focus + '</span></button>';
  }
  function flowListHtml(g) {
    var gr = S.trace.groups[g], html = '<ol class="flow">', route = -1;
    gr.stops.forEach(function (s, i) {
      if (s.route !== route) {
        route = s.route;
        var r = gr.routes[route];
        var part = (r.from !== 1 || r.to !== r.total) ? '（この順路の ' + r.from + '〜' + r.to + ' 番目）' : '';
        html += '<li class="fl-route">' + esc(r.label || r.title) + part + ' ・ ' + r.count + ' 停留所</li>';
      }
      html += '<li>' + stopRowHtml(s, g, i) + '</li>';
    });
    return html + '</ol>';
  }
  function buildFlow() {
    var box = $('#p-flow'), html = flowListHtml(0);
    var extras = S.trace.groups.map(function (g, k) { return k; }).filter(function (k) { return k > 0; });
    if (extras.length) {
      html += '<p class="extra-note">別ルート（参考）: 本筋には含めていない順路です。押すと、その流れをたどれます（「本筋に戻る」で戻ります）。</p>';
      extras.forEach(function (k) {
        var g = S.trace.groups[k];
        html += '<details class="extra"><summary>' + esc(g.title) + '（' + g.stops.length + ' 停留所）</summary>' + flowListHtml(k) + '</details>';
      });
    }
    box.innerHTML = html;
    $$('.fl', box).forEach(function (b) {
      b.addEventListener('click', function () { go(parseInt(b.getAttribute('data-g'), 10), parseInt(b.getAttribute('data-i'), 10)); });
    });
  }
  function renderFlowNow() {
    $$('#p-flow .fl').forEach(function (b) {
      var g = parseInt(b.getAttribute('data-g'), 10), i = parseInt(b.getAttribute('data-i'), 10);
      var now = g === S.g && i === S.i;
      b.classList.toggle('is-now', now);
      b.classList.toggle('is-past', g === S.g && i < S.i);
      if (now) { b.setAttribute('aria-current', 'step'); } else { b.removeAttribute('aria-current'); }
      if (now && g > 0) { var d = b.closest('details'); if (d) { d.open = true; } }
    });
  }
  function scrollFlowToNow() {
    var n = $('#p-flow .fl.is-now'), box = $('#p-flow');
    if (n && !box.hidden) {
      var top = n.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - box.clientHeight * 0.3;
      box.scrollTop = Math.max(0, top);
    }
  }

  /* ----- 通信 ----- */
  function fwdPath(p) { return /^\/api\//.test(p) ? p.replace(/^\/api\//, '/api/v1/') : p; }
  function jsonBox(title, value) {
    return '<div class="net-box"><h5>' + esc(title) + '</h5><pre class="json hljs" tabindex="0">' + hlJson(value) + '</pre></div>';
  }
  function buildNet() {
    var box = $('#p-net'), ac = (D.actions || {})[S.id] || {}, tr = S.trace;
    var net = ac.network || [], html = '';
    var note = (!net.length && tr.network_note) ? tr.network_note : (ac.note || '');
    if (note) { html += '<p class="net-note">' + esc(note) + '</p>'; }
    if (!net.length) {
      if (!note) { html += '<p class="empty">この操作の通信の記録はありません。</p>'; }
      if (tr.server_calls && tr.server_calls.length) {
        html += '<div class="net-sc" data-layer="bff"><span class="t">コードから組み立てた説明（ブラウザからは見えません）</span>'
          + 'Next.js のサーバー（Server Component）が、FastAPI を直接呼びます。<ul>'
          + tr.server_calls.map(function (c) { return '<li><code>' + esc(c.method) + ' ' + esc(c.path) + '</code>' + (c.note ? '（' + esc(c.note) + '）' : '') + '</li>'; }).join('')
          + '</ul>内部トークンの <code>X-Internal-Token</code> は、サーバーの設定から付きます。</div>';
      }
    }
    net.forEach(function (n) {
      var bad = n.status >= 400;
      html += '<section class="net-item"><h4 class="net-title"><span class="m">' + esc(n.method) + '</span><span class="p">' + esc(n.path) + '</span><span class="st' + (bad ? ' bad' : '') + '">' + esc(n.status) + '</span></h4><div class="net-grid">';
      html += jsonBox('リクエストのヘッダー（ブラウザ → BFF）', n.request_headers || {});
      if (n.request_body !== undefined) { html += jsonBox('リクエストの本文', n.request_body); }
      if (n.response_body !== undefined) { html += jsonBox('レスポンスの本文（BFF → ブラウザ）', n.response_body); }
      html += '</div>';
      if (/^\/api\//.test(n.path)) {
        var fh = tr.forward_headers || [];
        html += '<div class="net-fwd" data-layer="bff"><span class="t">BFF → FastAPI（コードから組み立て直した説明。ブラウザからは見えません）</span>'
          + 'BFF がこの' + (n.request_body !== undefined ? '本文' : 'リクエスト') + 'を FastAPI の <code>' + esc(n.method) + ' ' + esc(fwdPath(n.path)) + '</code> に転送する（内部トークンを付ける）。'
          + (fh.length ? '<ul>' + fh.map(function (h) { return '<li>' + esc(h) + '</li>'; }).join('') + '</ul>' : '')
          + '</div>';
      }
      html += '</section>';
    });
    box.innerHTML = html;
  }

  /* ----- DB（before / after の差分） ----- */
  var DB_LABEL = {
    variants: '在庫（variants）', orders_count: '注文の件数（orders）', latest_order: '最新の注文（orders）',
    latest_order_items: '最新の注文の明細（order_items）', cart: 'カート（carts・cart_items）',
    stock: '在庫', status: '状態', quantity: '数量', order_number: '注文番号', total: '合計', created_at: '作成日時', items: '明細'
  };
  var DB_KEY_LEAF = { stock: 1, orders_count: 1, status: 1 };
  function rowKey(it, i) {
    if (it && typeof it === 'object') {
      var k = it.id != null ? it.id : (it.variant_id != null ? it.variant_id : (it.order_number != null ? it.order_number : null));
      if (k != null) { return '#' + k + (it.color && it.size ? ' ' + it.color + '/' + it.size : ''); }
    }
    return '[' + i + ']';
  }
  function flatten(v, segs, out) {
    if (Array.isArray(v)) {
      if (!v.length) { out.push({ segs: segs, val: '（空）', key: segs.join(' › ') }); }
      v.forEach(function (it, i) { flatten(it, segs.concat([rowKey(it, i)]), out); });
    } else if (v && typeof v === 'object') {
      Object.keys(v).forEach(function (k) {
        if (v.color && v.size && (k === 'color' || k === 'size')) { return; }
        flatten(v[k], segs.concat([k]), out);
      });
    } else { out.push({ segs: segs, val: v, key: segs.join(' › ') }); }
  }
  function fmtVal(v) { return v === null ? 'null' : (typeof v === 'string' ? v : String(v)); }
  function pathHtml(segs) {
    var raw = segs.join(' › '), ja = DB_LABEL[segs[0]] ? DB_LABEL[segs[0]] : '';
    var leaf = segs[segs.length - 1];
    if (segs.length > 1 && DB_LABEL[leaf]) { ja = (ja ? ja + ' の ' : '') + DB_LABEL[leaf]; }
    return esc(raw) + (ja ? '<small>' + esc(ja) + '</small>' : '');
  }
  function buildDb() {
    var box = $('#p-db'), ac = (D.actions || {})[S.id] || {};
    if (!ac.db) { box.innerHTML = ''; return; }
    var a = [], b = [], before = {}, after = {};
    flatten(ac.db.before, [], a); flatten(ac.db.after, [], b);
    a.forEach(function (x) { before[x.key] = x; }); b.forEach(function (x) { after[x.key] = x; });
    var keys = [], seen = {};
    a.concat(b).forEach(function (x) { if (!seen[x.key]) { seen[x.key] = true; keys.push(x.key); } });
    var changed = [], same = [];
    keys.forEach(function (k) {
      var x = before[k], y = after[k];
      if (x && y && fmtVal(x.val) === fmtVal(y.val)) { same.push(k); } else { changed.push({ k: k, x: x, y: y, segs: (y || x).segs }); }
    });
    changed.sort(function (p, q) {
      var kp = DB_KEY_LEAF[p.segs[p.segs.length - 1]] ? 0 : 1, kq = DB_KEY_LEAF[q.segs[q.segs.length - 1]] ? 0 : 1;
      return kp - kq;
    });
    function delta(c) {
      var p = c.x && c.x.val, q = c.y && c.y.val;
      if (typeof p === 'number' && typeof q === 'number') { var d = q - p; return (d > 0 ? '+' : (d < 0 ? '−' : '±')) + Math.abs(d); }
      return '';
    }
    var chips = changed.filter(function (c) { return DB_KEY_LEAF[c.segs[c.segs.length - 1]]; }).map(function (c) {
      var nm = c.segs[c.segs.length - 1] === 'stock' ? '在庫 ' + c.segs[c.segs.length - 2] : (c.segs[c.segs.length - 1] === 'status' ? (c.segs[0] === 'cart' ? 'カートの状態' : '状態') : c.segs[c.segs.length - 1]);
      var d = delta(c);
      return '<span class="db-chip">' + esc(nm) + '：' + esc(c.x ? fmtVal(c.x.val) : '（なし）') + ' → ' + esc(c.y ? fmtVal(c.y.val) : '（なし）') + (d ? '<span class="d">' + esc(d) + '</span>' : '') + '</span>';
    }).join('');
    var html = '<p class="db-lead">この操作の前後で、DB（ローカルの MySQL）を SELECT して比べた結果です。変わった項目だけを表にし、変わらなかった項目は下にたたんでいます。</p>';
    if (chips) { html += '<div class="db-chips">' + chips + '</div>'; }
    html += '<table class="db"><thead><tr><th scope="col">項目</th><th scope="col">前（before）</th><th scope="col">後（after）</th><th scope="col">差</th></tr></thead><tbody>';
    if (!changed.length) { html += '<tr><td colspan="4" class="empty">変わった項目はありません。</td></tr>'; }
    changed.forEach(function (c) {
      var isKey = !!DB_KEY_LEAF[c.segs[c.segs.length - 1]];
      html += '<tr' + (isKey ? ' class="key"' : '') + '><td class="key-path">' + pathHtml(c.segs) + '</td>'
        + '<td class="old">' + (c.x ? esc(fmtVal(c.x.val)) : '（なし）') + '</td><td class="new">' + (c.y ? esc(fmtVal(c.y.val)) : '（なし）') + '</td><td class="dlt">' + esc(delta(c)) + '</td></tr>';
    });
    html += '</tbody></table>';
    if (same.length) {
      html += '<details class="db-same"><summary>変わらなかった項目（' + same.length + ' 件）</summary><ul>'
        + same.map(function (k) { return '<li>' + esc(k) + ' ＝ ' + esc(fmtVal(before[k].val)) + '</li>'; }).join('') + '</ul></details>';
    }
    box.innerHTML = html;
  }

  /* ---------------------------------------------------------------
     描画のまとめ
  --------------------------------------------------------------- */
  function buildGroupUi() {
    buildLayers();
    buildTreeUi();
  }
  function renderStop() {
    renderHeader();
    renderTreeNow();
    renderTabs();
    renderCrumb();
    renderEditor();
    renderExplain();
    renderFlowNow();
    if (S.tab === 'flow') { scrollFlowToNow(); }
    renderOpline();
  }

  /* ---------------------------------------------------------------
     操作
  --------------------------------------------------------------- */
  function resetAll() {
    stopPlay();
    S.pressed = {}; S.done = {}; S.shownState = null;
    startTrace('initial', '');
    S.imgSeq = [D.initial_state]; S.imgPos = 0; S.imgStart = 0;
    renderPhone(false);
    renderOpline();
  }

  function initEvents() {
    $('#btn-prev').addEventListener('click', function () { stopPlay(); prev(); });
    $('#btn-next').addEventListener('click', function () { stopPlay(); next(); });
    $('#btn-play').addEventListener('click', function () { if (S.playing) { stopPlay(); } else { startPlay(); } });
    $('#btn-reset').addEventListener('click', resetAll);
    $('#btn-main').addEventListener('click', function () { stopPlay(); go(0, S.mainI || 0); });
    $$('.ptab').forEach(function (t) { t.addEventListener('click', function () { setTab(t.getAttribute('data-p')); }); });
    var sw = $('#sw-tr');
    sw.addEventListener('change', function () { setTr(sw.checked); store('guapp-tracer-tr', sw.checked ? '1' : '0'); });
    elCode.addEventListener('click', onFoldClick);
    document.addEventListener('keydown', function (e) {
      if (e.altKey || e.ctrlKey || e.metaKey) { return; }
      var t = e.target, tag = t && t.tagName ? t.tagName.toLowerCase() : '';
      if (tag === 'input' || tag === 'select' || tag === 'textarea' || (t && t.isContentEditable)) { return; }
      if (e.key === 'ArrowRight' || e.key === 'F10') { e.preventDefault(); stopPlay(); next(); }
      else if (e.key === 'ArrowLeft' && !e.shiftKey) { e.preventDefault(); stopPlay(); prev(); }
    });
    if (window.ResizeObserver) {
      new window.ResizeObserver(function () { elCode.style.setProperty('--pw', elCode.clientWidth + 'px'); }).observe(elCode);
    } else { window.addEventListener('resize', function () { elCode.style.setProperty('--pw', elCode.clientWidth + 'px'); }); }
  }
  function setTr(on) {
    S.trOn = on;
    elCode.classList.toggle('tr-off', !on);
    $('#sw-tr').checked = on;
  }

  function onHljs() {
    // 遅れて hljs が読み込めたら、ハイライトをやり直す
    Object.keys(FILES).forEach(function (p) { if (FILES[p].lines) { FILES[p].hl = null; } });
    if (S.trace) {
      var st = elCode.scrollTop, sl = elCode.scrollLeft;
      S.ed = null; renderEditor();
      elCode.scrollTop = st; elCode.scrollLeft = sl;
      buildNet();
    }
  }

  function init() {
    if (!D.traces || !D.traces.initial) { elShot.textContent = 'トレースのデータを読み込めませんでした。'; return; }
    if (NARROW.matches) { $('#files-wrap').open = false; }
    var saved = store('guapp-tracer-tr');
    setTr(saved !== '0');
    initTerms();
    initEvents();
    resetAll();
    if (hlReady()) { onHljs(); } else {
      var s = document.getElementById('hljs-script');
      if (s) { s.addEventListener('load', onHljs); }
    }
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
