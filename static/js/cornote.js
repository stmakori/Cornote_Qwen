/**
 * Cornote - general UI helpers
 */
(function () {
  'use strict';

  // Auto-resize any textarea as user types
  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = el.scrollHeight + 'px';
  }

  document.addEventListener('DOMContentLoaded', function () {

    // Keyboard shortcut: Ctrl+G  → click the Grade All button
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'g') {
        e.preventDefault();
        const gradeBtn = document.querySelector('[hx-post*="grade"]');
        if (gradeBtn) gradeBtn.click();
      }
    });

    // Keyboard shortcut: Ctrl+S  → manually trigger all pending HTMX saves
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        document.querySelectorAll('[hx-trigger*="keyup"]').forEach(function (el) {
          htmx.trigger(el, 'keyup');
        });
      }
    });

    // Show a subtle fullscreen overlay hint when first arriving at notebook
    const grid = document.querySelector('.cornell-grid');
    if (grid) {
      const key = 'cornote_fs_hint_shown';
      if (!sessionStorage.getItem(key)) {
        sessionStorage.setItem(key, '1');
      }
    }

    // Announce HTMX errors gracefully
    document.body.addEventListener('htmx:responseError', function (evt) {
      console.warn('HTMX request failed:', evt.detail.xhr.status, evt.detail.requestConfig.path);
    });

    // After HTMX settles (e.g. after grading), select the first question
    document.body.addEventListener('htmx:afterSettle', function () {
      const first = document.querySelector('.q-nav-btn');
      if (first) {
        const pk = first.id.replace('qnav-', '');
        selectQuestion(parseInt(pk, 10));
      }
    });
  });
})();

// ── Question sidebar navigation ──────────────────────────────
function selectQuestion(pk) {
  // Deactivate all nav buttons
  document.querySelectorAll('.q-nav-btn').forEach(b => b.classList.remove('active'));
  // Hide all detail blocks
  document.querySelectorAll('.q-detail .question-block').forEach(b => b.classList.add('d-none'));

  // Activate selected
  const btn = document.getElementById('qnav-' + pk);
  const block = document.getElementById('question-' + pk);
  if (btn) btn.classList.add('active');
  if (block) {
    block.classList.remove('d-none');
    const idx = parseInt(block.dataset.index || '0', 10);
    const total = document.querySelectorAll('.q-nav-btn').length;
    const label = document.getElementById('q-detail-label');
    if (label) label.textContent = `Question ${idx + 1} of ${total}`;
    // Scroll nav button into view
    btn?.scrollIntoView({ block: 'nearest' });
  }
}

function navigateQ(direction) {
  const active = document.querySelector('.q-detail .question-block:not(.d-none)');
  if (!active) return;
  const allBlocks = Array.from(document.querySelectorAll('.q-detail .question-block'));
  const currentIdx = allBlocks.indexOf(active);
  const next = allBlocks[currentIdx + direction];
  if (next) selectQuestion(parseInt(next.dataset.pk, 10));
}

// Question flag toggle - global so inline onclick can reach it
function toggleFlag(questionPk, btn) {
  const csrf = document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith('csrftoken='))?.split('=')[1] || '';
  fetch(`/notebooks/answer/${questionPk}/flag/`, {
    method: 'POST',
    headers: { 'X-CSRFToken': csrf },
  })
  .then(r => r.json())
  .then(data => {
    const block = btn.closest('.question-block');
    const icon = btn.querySelector('i');
    if (data.needs_review) {
      block.classList.add('question-flagged');
      icon.className = 'bi bi-flag-fill';
      btn.classList.replace('text-muted', 'text-warning');
      btn.title = 'Flagged for review - click to unflag';
    } else {
      block.classList.remove('question-flagged');
      icon.className = 'bi bi-flag';
      btn.classList.replace('text-warning', 'text-muted');
      btn.title = 'Flag for review';
    }
  })
  .catch(() => {});
}
