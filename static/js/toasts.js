/**
 * Cornote achievement toasts.
 *
 * Usage:
 *   window.cornoteToast({
 *     title:    'Badge earned: Streak Master',   // required
 *     subtitle: 'Studied 7 days in a row',        // optional
 *     icon:     'bi-fire' | '🏅',                 // optional; Bootstrap Icon class or emoji
 *     variant:  'success' | 'primary',            // optional; default accent glow
 *     duration: 5000,                             // optional; ms before auto-dismiss
 *   });
 *
 * Markup/CSS: .toast-stack / .toast-achievement in static/css/cornote.css.
 * Dismissal is driven by setTimeout, NOT animationend — reduced-motion hides the
 * .toast-progress bar entirely, so an animationend listener would never fire.
 */
(function () {
  'use strict';

  var LEAVE_MS = 300; // matches toastOut in cornote.css
  var MAX_VISIBLE = 4;

  function getStack() {
    var stack = document.getElementById('toastStack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'toast-stack';
      stack.id = 'toastStack';
      stack.setAttribute('aria-live', 'polite');
      document.body.appendChild(stack);
    }
    return stack;
  }

  function buildBadge(icon) {
    var badge = document.createElement('div');
    badge.className = 'toast-badge';
    badge.setAttribute('aria-hidden', 'true');
    if (typeof icon === 'string' && /^bi[- ]/.test(icon)) {
      var i = document.createElement('i');
      i.className = icon.indexOf('bi ') === 0 ? icon : 'bi ' + icon;
      badge.appendChild(i);
    } else {
      badge.textContent = icon || '🏅'; // 🏅
    }
    return badge;
  }

  function cornoteToast(opts) {
    opts = opts || {};
    var stack = getStack();
    var duration = typeof opts.duration === 'number' && opts.duration > 0 ? opts.duration : 5000;

    var el = document.createElement('div');
    el.className = 'toast-achievement' + (opts.variant ? ' variant-' + opts.variant : '');
    el.setAttribute('role', 'status');
    el.style.setProperty('--toast-duration', (duration / 1000) + 's');

    var body = document.createElement('div');
    var title = document.createElement('div');
    title.className = 'toast-title';
    title.textContent = opts.title || 'Achievement unlocked';
    body.appendChild(title);
    if (opts.subtitle) {
      var sub = document.createElement('div');
      sub.className = 'toast-subtitle';
      sub.textContent = opts.subtitle;
      body.appendChild(sub);
    }

    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Dismiss');
    close.innerHTML = '&times;';

    var progress = document.createElement('div');
    progress.className = 'toast-progress';

    el.appendChild(buildBadge(opts.icon));
    el.appendChild(body);
    el.appendChild(close);
    el.appendChild(progress);

    var timer = null;
    var leaving = false;
    function dismiss() {
      if (leaving) return;
      leaving = true;
      if (timer) clearTimeout(timer);
      el.classList.add('leaving');
      setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, LEAVE_MS);
    }

    close.addEventListener('click', dismiss);
    timer = setTimeout(dismiss, duration);

    // Keep the stack from piling up: drop the oldest when over the cap
    var existing = stack.querySelectorAll('.toast-achievement:not(.leaving)');
    if (existing.length >= MAX_VISIBLE && existing[0].__cornoteDismiss) {
      existing[0].__cornoteDismiss();
    }

    el.__cornoteDismiss = dismiss;
    stack.appendChild(el);
    return { element: el, dismiss: dismiss };
  }

  window.cornoteToast = cornoteToast;
})();
