  var SN = {};
  try { SN = JSON.parse(document.getElementById('snippets-data').textContent) || {}; } catch (e) { SN = {}; }
  // コード本体は JSON ではなく <script type="text/plain" data-snippet="キー"> に原文のまま置いてある。
  // script の終端タグ相当と HTML コメント開始相当の並びだけ、「<」と続きの間にバックスラッシュを 1 つ足してあるので、1 つ引いて戻す
  Array.prototype.slice.call(document.querySelectorAll('script[data-snippet]')).forEach(function (s) {
    var k = s.getAttribute('data-snippet');
    if (SN[k]) { SN[k].code = s.textContent.replace(/<(\\+)(\/script|!--)/gi, function (m, bs, tail) { return '<' + bs.slice(1) + tail; }); }
  });
  document.documentElement.classList.add('js');

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    if (attrs) { Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); }); }
    if (text != null) { n.textContent = text; }
    return n;
  }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  var RM = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  var FINE = window.matchMedia ? window.matchMedia('(hover: hover) and (pointer: fine)') : { matches: false };

  /* ---------------------------------------------------------------
     コード参照（data-ref）
  --------------------------------------------------------------- */
  function refKey(node) { return (node.getAttribute('data-ref') || '').trim(); }
  function rangeText(sn) {
    return sn.start === sn.end ? 'L' + sn.start : 'L' + sn.start + '-' + sn.end;
  }
  function baseName(p) { return p.split('/').pop(); }
  // build.py が data-focus（部分文字列）を実ファイルの行番号に解決して付ける属性。無ければ 0
  function focusOf(node) { return parseInt(node.getAttribute('data-focus-line') || '0', 10) || 0; }

  function initRefs() {
    $$('[data-ref]').forEach(function (node) {
      var key = refKey(node);
      if (!key) { return; }
      if (!SN[key]) { node.classList.add('ref-missing'); node.title = 'コードを解決できていません: ' + key; return; }
      // 順路の停留所（li.stop）は全面をクリック対象にしない。「コードを見る」ボタンが showRef を呼ぶ
      if (node.classList.contains('stop')) { node.classList.add('stop-has-ref'); return; }
      node.classList.add('has-ref');
      if (!node.hasAttribute('tabindex')) { node.setAttribute('tabindex', '0'); }
      node.setAttribute('role', 'button');
      node.setAttribute('aria-haspopup', 'dialog');
    });
  }

  /* ---------------------------------------------------------------
     ドロワー
  --------------------------------------------------------------- */
  var drawer, backdrop, elPath, elTitle, elRange, elNote, elBody, elCode, btnBack, btnCopy, linkGh, btnClose;
  var cur = null;        // { key, note, focus }
  var hist = [];         // 直前に見た参照
  var opener = null;
  var copyTimer = null;
  var hlLoaded = false;

  function buildDrawer() {
    backdrop = el('div', { 'class': 'drawer-backdrop', 'aria-hidden': 'true' });
    drawer = el('div', { 'class': 'drawer', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'drawer-title', 'aria-hidden': 'true', tabindex: '-1' });

    var head = el('div', { 'class': 'drawer-head' });
    elPath = el('div', { 'class': 'drawer-path' });
    var row = el('div', { 'class': 'drawer-title-row' });
    elTitle = el('div', { 'class': 'drawer-title', id: 'drawer-title' });
    elRange = el('span', { 'class': 'drawer-range' });
    row.appendChild(elTitle); row.appendChild(elRange);

    var actions = el('div', { 'class': 'drawer-actions' });
    btnBack = el('button', { type: 'button', 'class': 'btn', disabled: 'disabled' }, '← 戻る');
    linkGh = el('a', { 'class': 'btn', target: '_blank', rel: 'noopener noreferrer' }, 'GitHub で開く ↗');
    btnCopy = el('button', { type: 'button', 'class': 'btn' }, 'パスをコピー');
    var spacer = el('span', { 'class': 'spacer' });
    btnClose = el('button', { type: 'button', 'class': 'btn icon', 'aria-label': '閉じる' }, '×');
    [btnBack, linkGh, btnCopy, spacer, btnClose].forEach(function (n) { actions.appendChild(n); });
    // レビュー回答ガイドだけが定義するフック（「訳を表示」のスイッチを足す）。他の出力では何もしない
    if (typeof buildDrawerExtra === 'function') { buildDrawerExtra(actions, spacer); }

    head.appendChild(elPath); head.appendChild(row); head.appendChild(actions);

    elNote = el('p', { 'class': 'drawer-note' });
    elNote.hidden = true;
    elBody = el('div', { 'class': 'drawer-body', tabindex: '0', role: 'region', 'aria-label': 'コード' });
    var pre = el('pre', { 'class': 'code-view hljs' });
    elCode = el('code');
    pre.appendChild(elCode); elBody.appendChild(pre);

    drawer.appendChild(head); drawer.appendChild(elNote); drawer.appendChild(elBody);
    document.body.appendChild(backdrop);
    document.body.appendChild(drawer);

    btnClose.addEventListener('click', closeDrawer);
    btnBack.addEventListener('click', goBack);
    btnCopy.addEventListener('click', copyPath);
    backdrop.addEventListener('click', onBackdropClick);
  }

  function splitHighlighted(html) {
    // hljs の出力を行ごとに分け、行をまたぐ <span> を閉じて開き直す
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

  function highlightLines(sn) {
    var raw = sn.code.split('\n');
    if (window.hljs && window.hljs.highlight && sn.lang && sn.lang !== 'plaintext' && window.hljs.getLanguage && window.hljs.getLanguage(sn.lang)) {
      try {
        var html = window.hljs.highlight(sn.code, { language: sn.lang, ignoreIllegals: true }).value;
        var lines = splitHighlighted(html);
        if (lines.length === raw.length) { return lines; }
      } catch (e) { /* 素のテキストで表示する */ }
    }
    return raw.map(esc);
  }

  function renderCode(sn, focus) {
    // レビュー回答ガイドだけが定義するフック（コードの日本語訳つきの 3 列表示）。訳を出したら true
    if (typeof renderCodeTr === 'function' && renderCodeTr(sn, focus)) { return; }
    var lines = highlightLines(sn);
    var html = '';
    for (var i = 0; i < lines.length; i++) {
      var n = sn.start + i;
      html += '<span class="cl' + (focus && n === focus ? ' is-focus' : '') + '" data-n="' + n + '">' + lines[i] + '\n</span>';
    }
    elCode.innerHTML = html;
  }

  // 注目行（is-focus）が上から 1/3 あたりに来るようにスクロールする
  function scrollToFocus() {
    var f = elCode.querySelector('.cl.is-focus');
    if (!f) { return; }
    var delta = f.getBoundingClientRect().top - elBody.getBoundingClientRect().top;
    elBody.scrollTop = Math.max(0, elBody.scrollTop + delta - Math.round(elBody.clientHeight / 3));
  }

  function renderHead(sn, note, focus) {
    var p = sn.path, idx = p.lastIndexOf('/');
    elPath.textContent = '';
    if (idx >= 0) {
      elPath.appendChild(document.createTextNode(p.slice(0, idx + 1)));
    }
    var f = el('span', { 'class': 'file' }, p.slice(idx + 1));
    elPath.appendChild(f);
    elTitle.textContent = sn.symbol || baseName(sn.path);
    var n = sn.end - sn.start + 1;
    elRange.textContent = rangeText(sn) + '（' + n + ' 行）' + (focus ? ' ／ 注目 L' + focus : '');
    linkGh.setAttribute('href', sn.url);
    if (note) {
      elNote.textContent = '';
      elNote.appendChild(el('b', null, '見どころ'));
      elNote.appendChild(document.createTextNode(note));
      elNote.hidden = false;
    } else {
      elNote.hidden = true;
    }
  }

  function markOpen() {
    $$('[data-ref].has-ref, .stop.stop-has-ref').forEach(function (n) {
      var on = !!cur && refKey(n) === cur.key && focusOf(n) === (cur.focus || 0);
      n.classList.toggle('is-open', on);
      if (!n.classList.contains('stop')) { n.setAttribute('aria-expanded', on ? 'true' : 'false'); }
    });
  }

  function updateBack() {
    if (hist.length) { btnBack.removeAttribute('disabled'); btnBack.textContent = '← 戻る（' + hist.length + '）'; }
    else { btnBack.setAttribute('disabled', 'disabled'); btnBack.textContent = '← 戻る'; }
  }

  function showRef(key, note, openerNode, isBack, focus) {
    var sn = SN[key];
    if (!sn) { return; }
    hideTip();
    var wasOpen = drawer.classList.contains('is-open');
    focus = focus || 0;
    if (wasOpen && cur && !isBack && (cur.key !== key || (cur.focus || 0) !== focus)) { hist.push(cur); }
    if (!wasOpen) { hist = []; opener = openerNode || document.activeElement; }
    cur = { key: key, note: note || sn.note || '', focus: focus };
    renderHead(sn, cur.note, focus);
    renderCode(sn, focus);
    elBody.scrollTop = 0; elBody.scrollLeft = 0;
    scrollToFocus();
    markOpen();
    updateBack();
    if (!wasOpen) {
      drawer.classList.add('is-open'); backdrop.classList.add('is-open');
      drawer.setAttribute('aria-hidden', 'false');
      drawer.focus();
      if (document.activeElement !== drawer) { window.requestAnimationFrame(function () { drawer.focus(); }); }
    }
  }

  function goBack() {
    if (!hist.length) { return; }
    var prev = hist.pop();
    showRef(prev.key, prev.note, null, true, prev.focus);
  }

  function closeDrawer() {
    if (!drawer || !drawer.classList.contains('is-open')) { return; }
    drawer.classList.remove('is-open'); backdrop.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
    cur = null; hist = [];
    markOpen(); updateBack();
    var back = opener; opener = null;
    if (back && document.contains(back) && back.focus) { back.focus(); }
  }

  function onBackdropClick(e) {
    // 背景の下にコード参照があれば、閉じずにそちらへ切り替える（「戻る」で戻れる）
    var under = document.elementsFromPoint ? document.elementsFromPoint(e.clientX, e.clientY) : [];
    for (var i = 0; i < under.length; i++) {
      var n = under[i];
      if (n === backdrop || n === drawer) { continue; }
      var hit = n.closest && n.closest('[data-ref].has-ref');
      if (hit) { openFromNode(hit); return; }
    }
    closeDrawer();
  }

  function copyPath() {
    if (!cur) { return; }
    var text = SN[cur.key].path;
    function done(msg) {
      btnCopy.textContent = msg;
      clearTimeout(copyTimer);
      copyTimer = setTimeout(function () { btnCopy.textContent = 'パスをコピー'; }, 1800);
    }
    function fallback() {
      try {
        var r = document.createRange();
        r.selectNodeContents(elPath);
        var sel = window.getSelection();
        sel.removeAllRanges(); sel.addRange(r);
        var ok = document.execCommand && document.execCommand('copy');
        done(ok ? 'コピーしました' : 'パスを選択しました（⌘/Ctrl+C）');
      } catch (err) { done('パスを選択しました（⌘/Ctrl+C）'); }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done('コピーしました'); }, fallback);
    } else { fallback(); }
  }

  function focusables() {
    return $$('button:not([disabled]), a[href], [tabindex="0"]', drawer).filter(function (n) { return n.offsetParent !== null || n === drawer; });
  }

  function openFromNode(node) {
    showRef(refKey(node), node.getAttribute('data-note') || '', node, false, focusOf(node));
  }

  function initRefEvents() {
    document.addEventListener('click', function (e) {
      var node = e.target.closest ? e.target.closest('[data-ref].has-ref') : null;
      if (!node) { return; }
      // フロー図のカード上でテキスト選択したときは開かない
      var sel = window.getSelection && window.getSelection();
      if (node.classList.contains('flow-step') && sel && !sel.isCollapsed && node.contains(sel.anchorNode)) { return; }
      e.preventDefault();
      openFromNode(node);
    });
    document.addEventListener('keydown', function (e) {
      var node = e.target;
      if (drawer && drawer.classList.contains('is-open')) {
        if (e.key === 'Escape') { e.preventDefault(); closeDrawer(); return; }
        if (e.key === 'Tab') {
          var f = focusables();
          if (!f.length) { return; }
          var first = f[0], last = f[f.length - 1];
          if (e.shiftKey && (document.activeElement === first || document.activeElement === drawer)) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
          return;
        }
      }
      if ((e.key === 'Enter' || e.key === ' ') && node && node.classList && node.classList.contains('has-ref') && node.hasAttribute('data-ref')) {
        if (node.tagName === 'A' && node.hasAttribute('href')) { return; }   // 素の a[href] は click が発火する
        e.preventDefault();
        openFromNode(node);
      }
    });
    document.addEventListener('focusin', function (e) {
      if (drawer && drawer.classList.contains('is-open') && !drawer.contains(e.target)) { drawer.focus(); }
    });
  }

  /* ---------------------------------------------------------------
     ホバーのツールチップ（path:L10-40）
  --------------------------------------------------------------- */
  var tip = null, tipTimer = null;
  function hideTip() {
    clearTimeout(tipTimer);
    if (tip) { tip.hidden = true; }
  }
  function showTip(node) {
    var sn = SN[refKey(node)];
    if (!sn) { return; }
    if (!tip) { tip = el('div', { 'class': 'ref-tip', role: 'tooltip' }); document.body.appendChild(tip); }
    var fl = focusOf(node);
    tip.textContent = fl ? sn.path + ':' + fl : sn.path + ':' + rangeText(sn);
    tip.hidden = false;
    var r = node.getBoundingClientRect();
    var tw = tip.offsetWidth, th = tip.offsetHeight;
    var left = Math.max(8, Math.min(r.left, window.innerWidth - tw - 8));
    var top = r.bottom + 6;
    if (top + th > window.innerHeight - 8) { top = Math.max(8, r.top - th - 6); }
    tip.style.left = left + 'px'; tip.style.top = top + 'px';
  }
  function initTip() {
    document.addEventListener('mouseover', function (e) {
      if (!FINE.matches || !e.target.closest) { return; }
      var node = e.target.closest('[data-ref].has-ref');
      if (!node || (e.relatedTarget && node.contains(e.relatedTarget))) { return; }
      clearTimeout(tipTimer);
      tipTimer = setTimeout(function () { showTip(node); }, 250);
    });
    document.addEventListener('mouseout', function (e) {
      if (!e.target.closest) { return; }
      var node = e.target.closest('[data-ref].has-ref');
      if (!node || (e.relatedTarget && node.contains(e.relatedTarget))) { return; }
      hideTip();
    });
    document.addEventListener('scroll', hideTip, true);
    document.addEventListener('click', hideTip, true);
  }

  /* ---------------------------------------------------------------
     直書きコード（pre.code）のハイライト
  --------------------------------------------------------------- */
  function highlightPres() {
    if (!(window.hljs && window.hljs.highlight && window.hljs.getLanguage)) { return; }
    $$('pre.code[data-lang]').forEach(function (pre) {
      if (pre.getAttribute('data-hl')) { return; }
      var lang = pre.getAttribute('data-lang');
      if (!window.hljs.getLanguage(lang)) { return; }
      try {
        var html = window.hljs.highlight(pre.textContent, { language: lang, ignoreIllegals: true }).value;
        pre.innerHTML = html;
        pre.classList.add('hljs');
        pre.setAttribute('data-hl', '1');
      } catch (e) { /* 素のテキストのまま */ }
    });
  }

  function onHljsReady() {
    if (hlLoaded) { return; }
    hlLoaded = true;
    highlightPres();
    if (cur && SN[cur.key]) {
      var st = elBody.scrollTop, sl = elBody.scrollLeft;
      renderCode(SN[cur.key], cur.focus);
      elBody.scrollTop = st; elBody.scrollLeft = sl;
    }
  }
  function initHljs() {
    if (window.hljs) { onHljsReady(); return; }
    var s = document.getElementById('hljs-script');
    if (s) { s.addEventListener('load', onHljsReady); }
  }
