/**
 * Cornote - type-aware answer widgets (true/false, multiple choice/select,
 * ordering, matching). Each widget keeps its backing textarea (id built from
 * `data-input-prefix` + pk, default prefix "answer-raw") in sync and fires
 * `input`+`change` on it - `change` is what the notebook view's HTMX autosave
 * listens for (hx-trigger="keyup changed delay:1200ms, change"), `input` is
 * what exam.html's plain `oninput="markAnswered(...)"` listens for. Firing
 * both means the same widget works in both contexts with no backend changes.
 */
(function () {
  'use strict';

  function getAnswerInput(el, pk) {
    const prefix = el.dataset.inputPrefix || 'answer-raw';
    return document.getElementById(prefix + '-' + pk);
  }

  function setAnswer(ta, value, opts) {
    if (!ta) return;
    ta.value = value;
    // Multi-step widgets (multi-select, matching, ordering) need several
    // clicks on the same question - tell cornote.js's autosave-driven
    // auto-advance to sit this one out (see cornote.js htmx:afterSwap).
    if (opts && opts.skipAdvance) window.__cornoteSkipAutoAdvance = true;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    ta.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function shuffle(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      const tmp = a[i]; a[i] = a[j]; a[j] = tmp;
    }
    return a;
  }

  // ── True / False ──────────────────────────────────────────
  function initTFToggle(el) {
    if (el.dataset.wgInit) return;
    el.dataset.wgInit = '1';
    const pk = el.dataset.pk;
    const saved = el.dataset.saved || '';
    const readonly = !!el.dataset.readonly;
    const ta = getAnswerInput(el, pk);

    el.querySelectorAll('.tf-toggle-btn').forEach((btn) => {
      if (btn.dataset.value === saved) btn.classList.add('selected');
      if (readonly) return;
      btn.addEventListener('click', () => {
        el.querySelectorAll('.tf-toggle-btn').forEach((b) => b.classList.remove('selected'));
        btn.classList.add('selected');
        setAnswer(ta, btn.dataset.value);
      });
    });
  }

  // ── Choice list (multiple choice = single select, multiple select = multi) ─
  function initChoiceList(el) {
    if (el.dataset.wgInit) return;
    el.dataset.wgInit = '1';
    const pk = el.dataset.pk;
    const mode = el.dataset.mode;
    const saved = el.dataset.saved || '';
    const readonly = !!el.dataset.readonly;
    const savedSet = mode === 'multi'
      ? new Set(saved.split(' | ').map((s) => s.trim()).filter(Boolean))
      : new Set(saved.trim() ? [saved.trim()] : []);

    const ta = getAnswerInput(el, pk);
    const cards = Array.from(el.querySelectorAll('.choice-card'));
    cards.forEach((card) => {
      if (savedSet.has(card.dataset.value)) card.classList.add('selected');
    });
    if (readonly) return;

    function sync() {
      const selected = cards.filter((c) => c.classList.contains('selected')).map((c) => c.dataset.value);
      if (mode === 'multi') {
        setAnswer(ta, selected.join(' | '), { skipAdvance: true });
      } else {
        setAnswer(ta, selected[0] || '');
      }
    }

    cards.forEach((card) => {
      card.addEventListener('click', () => {
        if (mode === 'single') {
          cards.forEach((c) => c.classList.remove('selected'));
          card.classList.add('selected');
        } else {
          card.classList.toggle('selected');
        }
        sync();
      });
    });
  }

  // ── Ordering (native HTML5 drag-and-drop + up/down buttons) ────────────
  function initOrderList(el) {
    if (el.dataset.wgInit) return;
    el.dataset.wgInit = '1';
    const pk = el.dataset.pk;
    const readonly = !!el.dataset.readonly;
    let items;
    try { items = JSON.parse(el.dataset.items || '[]'); } catch (e) { items = []; }
    const saved = el.dataset.saved || '';
    const savedOrder = saved ? saved.split(' → ').map((s) => s.trim()).filter(Boolean) : [];
    let order = (savedOrder.length === items.length && items.length > 0) ? savedOrder : shuffle(items);
    const ta = getAnswerInput(el, pk);

    function persist() {
      setAnswer(ta, order.join(' → '), { skipAdvance: true });
    }

    function attachHandlers() {
      const rows = Array.from(el.querySelectorAll('.order-item'));
      rows.forEach((li, idx) => {
        li.addEventListener('dragstart', () => li.classList.add('dragging'));
        li.addEventListener('dragend', () => {
          li.classList.remove('dragging');
          rows.forEach((r) => r.classList.remove('drag-over'));
        });
        li.addEventListener('dragover', (e) => { e.preventDefault(); li.classList.add('drag-over'); });
        li.addEventListener('dragleave', () => li.classList.remove('drag-over'));
        li.addEventListener('drop', (e) => {
          e.preventDefault();
          const dragging = el.querySelector('.order-item.dragging');
          if (!dragging || dragging === li) return;
          const fromIdx = Array.from(el.children).indexOf(dragging);
          const toIdx = Array.from(el.children).indexOf(li);
          const moved = order.splice(fromIdx, 1)[0];
          order.splice(toIdx, 0, moved);
          render();
          persist();
        });
        li.querySelectorAll('.order-move-btn').forEach((btn) => {
          btn.addEventListener('click', () => {
            const dir = parseInt(btn.dataset.dir, 10);
            const newIdx = idx + dir;
            if (newIdx < 0 || newIdx >= order.length) return;
            const moved = order.splice(idx, 1)[0];
            order.splice(newIdx, 0, moved);
            render();
            persist();
          });
        });
      });
    }

    function render() {
      el.innerHTML = '';
      order.forEach((text, idx) => {
        const li = document.createElement('li');
        li.className = 'order-item';
        li.draggable = !readonly;
        li.innerHTML =
          '<span class="order-handle"></span>' +
          '<span class="order-index">' + (idx + 1) + '</span>' +
          '<span class="order-text"></span>' +
          (readonly ? '' :
            '<span class="order-move">' +
              '<button type="button" class="order-move-btn" data-dir="-1" aria-label="Move up">▲</button>' +
              '<button type="button" class="order-move-btn" data-dir="1" aria-label="Move down">▼</button>' +
            '</span>');
        li.querySelector('.order-text').textContent = text;
        el.appendChild(li);
      });
      if (!readonly) attachHandlers();
    }

    render();
    // Only persist once the student actually reorders something - an
    // untouched shuffle is not an answer yet.
  }

  // ── Matching (click left item, then right item, to connect them) ───────
  function initMatchPair(el) {
    if (el.dataset.wgInit) return;
    el.dataset.wgInit = '1';
    const pk = el.dataset.pk;
    const readonly = !!el.dataset.readonly;
    let pairs;
    try { pairs = JSON.parse(el.dataset.pairs || '[]'); } catch (e) { pairs = []; }
    const saved = el.dataset.saved || '';

    const leftCol = el.querySelector('.match-pair-col-left');
    const rightCol = el.querySelector('.match-pair-col-right');
    const leftItems = pairs.map((p) => p.left);
    const rightItems = shuffle(pairs.map((p) => p.right));
    const ta = getAnswerInput(el, pk);

    let connections = [];
    if (saved) {
      saved.split(' ~ ').forEach((chunk) => {
        const parts = chunk.split(' => ');
        const l = parts[0] && parts[0].trim();
        const r = parts[1] && parts[1].trim();
        if (l && r) connections.push({ left: l, right: r });
      });
    }

    let armedLeft = null;
    let armedRight = null;

    function persist() {
      setAnswer(ta, connections.map((c) => c.left + ' => ' + c.right).join(' ~ '), { skipAdvance: true });
    }

    function pairNumberFor(text, side) {
      const idx = connections.findIndex((c) => c[side] === text);
      return idx === -1 ? null : idx + 1;
    }

    function makeItem(text, side) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'match-pair-item';
      btn.textContent = text;
      const pairNum = pairNumberFor(text, side);
      if (pairNum) {
        btn.classList.add('matched');
        btn.dataset.pair = String(pairNum);
      }
      if (readonly) {
        btn.disabled = true;
        return btn;
      }
      btn.addEventListener('click', () => {
        if (btn.classList.contains('matched')) return;
        if (side === 'left') {
          if (armedLeft === text) { armedLeft = null; btn.classList.remove('selected'); return; }
          leftCol.querySelectorAll('.match-pair-item').forEach((b) => b.classList.remove('selected'));
          armedLeft = text;
          btn.classList.add('selected');
        } else {
          if (armedRight === text) { armedRight = null; btn.classList.remove('selected'); return; }
          rightCol.querySelectorAll('.match-pair-item').forEach((b) => b.classList.remove('selected'));
          armedRight = text;
          btn.classList.add('selected');
        }
        if (armedLeft && armedRight) {
          connections = connections.filter((c) => c.left !== armedLeft && c.right !== armedRight);
          connections.push({ left: armedLeft, right: armedRight });
          armedLeft = null;
          armedRight = null;
          render();
          persist();
        }
      });
      return btn;
    }

    function render() {
      leftCol.innerHTML = '';
      rightCol.innerHTML = '';
      leftItems.forEach((text) => leftCol.appendChild(makeItem(text, 'left')));
      rightItems.forEach((text) => rightCol.appendChild(makeItem(text, 'right')));
    }

    render();
  }

  function initAll(root) {
    root.querySelectorAll('.tf-toggle[data-pk]').forEach(initTFToggle);
    root.querySelectorAll('.choice-list[data-pk]').forEach(initChoiceList);
    root.querySelectorAll('.order-list[data-pk]').forEach(initOrderList);
    root.querySelectorAll('.match-pair[data-pk]').forEach(initMatchPair);
  }

  document.addEventListener('DOMContentLoaded', () => initAll(document));
  document.body.addEventListener('htmx:afterSwap', (evt) => {
    const target = evt && evt.detail && evt.detail.target;
    if (!target) return;
    if (target.id === 'questions-column' || (target.closest && target.closest('#questions-column'))) {
      initAll(target);
    }
  });

  window.CornoteAnswerWidgets = { initAll };
})();
