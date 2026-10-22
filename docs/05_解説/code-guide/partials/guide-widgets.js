  var LAYER_LABEL = {
    screen: '画面', bff: 'BFF', api: 'API', service: 'サービス', repo: 'リポジトリ',
    db: 'DB', ci: 'CI', infra: 'インフラ', browser: 'ブラウザ', web: 'Web'
  };

  /* ---------------------------------------------------------------
     フロー図
  --------------------------------------------------------------- */
  // CSS の .flow-step::before と一致させる（丸の位置・大きさ、再生ドットの大きさ）
  var MARK_LEFT = -48, MARK_TOP = 8, MARK = 30, DOT = 14;
  var stopCurrent = null;

  function initFlows() {
    $$('.flow').forEach(function (flow) {
      var steps = $$(':scope > .flow-step', flow);
      if (!steps.length) { return; }
      var title = flow.getAttribute('data-title') || '処理の流れ';
      flow.setAttribute('role', 'group');
      flow.setAttribute('aria-label', title);

      var head = el('div', { 'class': 'flow-head' });
      head.appendChild(el('div', { 'class': 'flow-title', role: 'heading', 'aria-level': '4' }, title));
      var btn = el('button', { type: 'button', 'class': 'flow-play', 'aria-pressed': 'false' }, '▶ 流れを再生');
      head.appendChild(btn);

      var layers = [];
      steps.forEach(function (s) {
        var l = s.getAttribute('data-layer');
        if (l && layers.indexOf(l) < 0) { layers.push(l); }
      });
      var legend = el('ul', { 'class': 'flow-legend', 'aria-label': 'レイヤーの凡例' });
      layers.forEach(function (l) {
        var li = el('li');
        li.setAttribute('data-layer', l);
        li.appendChild(el('i', { 'aria-hidden': 'true' }));
        li.appendChild(document.createTextNode(LAYER_LABEL[l] || l));
        legend.appendChild(li);
      });
      var live = el('div', { 'class': 'visually-hidden', 'aria-live': 'polite' });
      var dot = el('div', { 'class': 'flow-dot no-anim', 'aria-hidden': 'true' });

      flow.insertBefore(head, flow.firstChild);
      if (layers.length) { flow.insertBefore(legend, steps[0]); }
      flow.appendChild(live);
      flow.appendChild(dot);

      steps.forEach(function (s, i) {
        var l = s.getAttribute('data-layer');
        var meta = el('div', { 'class': 'flow-meta' });
        if (l) { meta.appendChild(el('span', { 'class': 'flow-layer' }, LAYER_LABEL[l] || l)); }
        var sn = SN[refKey(s)];
        if (sn) { meta.appendChild(el('span', { 'class': 'flow-open' }, sn.symbol || baseName(sn.path))); }
        if (meta.childNodes.length) { s.insertBefore(meta, s.firstChild); }
        if (i === steps.length - 1) { s.classList.add('is-last'); }
      });

      var timer = null, playing = false, idx = -1;

      function clearActive() { steps.forEach(function (s) { s.classList.remove('is-active'); }); }
      function stop() {
        playing = false; clearTimeout(timer); timer = null; idx = -1;
        clearActive();
        flow.classList.remove('is-playing');
        btn.textContent = '▶ 流れを再生';
        btn.setAttribute('aria-pressed', 'false');
        if (stopCurrent === stop) { stopCurrent = null; }
      }
      function place(i, animate) {
        var s = steps[i];
        var x = s.offsetLeft + MARK_LEFT + MARK / 2 - DOT / 2;
        var y = s.offsetTop + MARK_TOP + MARK / 2 - DOT / 2;
        if (!animate || RM.matches) { dot.classList.add('no-anim'); } else { dot.classList.remove('no-anim'); }
        dot.style.transform = 'translate(' + x + 'px,' + y + 'px)';
      }
      function go(i, animate) {
        idx = i;
        steps.forEach(function (s, k) { s.classList.toggle('is-active', k === i); });
        if (!RM.matches) { place(i, animate); }
        var t = steps[i].querySelector('strong');
        live.textContent = 'ステップ ' + (i + 1) + '/' + steps.length + (t ? '：' + t.textContent : '');
        if (steps[i].scrollIntoView) { steps[i].scrollIntoView({ block: 'nearest', behavior: RM.matches ? 'auto' : 'smooth' }); }
      }
      function next() {
        if (!playing) { return; }
        if (idx + 1 >= steps.length) { timer = setTimeout(stop, 900); return; }
        go(idx + 1, true);
        timer = setTimeout(next, 900);
      }
      function play() {
        if (stopCurrent) { stopCurrent(); }
        playing = true; stopCurrent = stop;
        flow.classList.add('is-playing');
        btn.textContent = '■ 停止';
        btn.setAttribute('aria-pressed', 'true');
        go(0, false);
        // 直後の移動から動きを付ける
        window.requestAnimationFrame(function () { dot.classList.remove('no-anim'); });
        timer = setTimeout(next, 900);
      }

      btn.addEventListener('click', function () { if (playing) { stop(); } else { play(); } });
      steps.forEach(function (s) {
        s.addEventListener('click', function () { if (playing) { stop(); } });
      });
    });
  }

  /* ---------------------------------------------------------------
     表の絞り込み
  --------------------------------------------------------------- */
  function initFilters() {
    $$('table.filterable').forEach(function (table, n) {
      var id = 'filter-' + (n + 1);
      var anchor = table.parentNode && table.parentNode.classList && (table.parentNode.classList.contains('table-wrap') || table.parentNode.classList.contains('tablewrap')) ? table.parentNode : table;
      var wrap = el('div', { 'class': 'table-filter' });
      var input = el('input', { type: 'search', id: id, placeholder: 'ファイル名・内容で絞り込み', 'aria-label': '表を絞り込む', autocomplete: 'off' });
      var count = el('span', { 'class': 'count', 'aria-live': 'polite' });
      wrap.appendChild(input); wrap.appendChild(count);
      anchor.parentNode.insertBefore(wrap, anchor);

      var rows = $$('tbody tr', table);
      if (!rows.length) { rows = $$('tr', table).slice(1); }
      var norm = function (s) { return String(s).normalize('NFKC').toLowerCase(); };
      var texts = rows.map(function (r) { return norm(r.textContent); });
      function apply() {
        var terms = norm(input.value).split(/\s+/).filter(Boolean);
        var shown = 0;
        rows.forEach(function (r, i) {
          var ok = terms.every(function (t) { return texts[i].indexOf(t) >= 0; });
          r.hidden = !ok;
          if (ok) { shown++; }
        });
        count.textContent = terms.length ? shown + ' / ' + rows.length + ' 件' : '';
      }
      input.addEventListener('input', apply);
    });
  }

  /* ---------------------------------------------------------------
     目次の現在地ハイライト
  --------------------------------------------------------------- */
  function initToc() {
    var side = $('.toc-side');
    if (!side) { return; }
    var heads = $$('.content section[id], .content h3[id]');
    if (!heads.length) { return; }
    var ticking = false;
    function update() {
      ticking = false;
      var current = null;
      for (var i = 0; i < heads.length; i++) {
        if (heads[i].getBoundingClientRect().top <= 120) { current = heads[i]; } else { break; }
      }
      $$('a[aria-current]', side).forEach(function (a) { a.removeAttribute('aria-current'); });
      $$('li.is-current', side).forEach(function (li) { li.classList.remove('is-current'); });
      if (!current) { return; }
      var sec = current.tagName === 'SECTION' ? current : current.closest('section[id]');
      var ids = [];
      if (sec) { ids.push(sec.id); }
      if (current !== sec) { ids.push(current.id); }
      var last = null;
      ids.forEach(function (id) {
        var a = null;
        $$('a', side).forEach(function (x) { if (x.getAttribute('href') === '#' + id) { a = x; } });
        if (a) { a.setAttribute('aria-current', 'true'); last = a; var li = a.closest('li'); if (li) { li.classList.add('is-current'); } }
      });
      if (last && side.scrollHeight > side.clientHeight) {
        var lr = last.getBoundingClientRect(), sr = side.getBoundingClientRect();
        if (lr.top < sr.top || lr.bottom > sr.bottom) { last.scrollIntoView({ block: 'nearest' }); }
      }
    }
    window.addEventListener('scroll', function () {
      if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
    }, { passive: true });
    window.addEventListener('resize', update);
    update();
  }
