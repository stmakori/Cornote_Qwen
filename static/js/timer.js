/**
 * Cornote Pomodoro Timer
 * Uses FOCUS_MINS and BREAK_MINS globals set by the template.
 */
(function () {
  'use strict';

  const FOCUS_SECS = (typeof FOCUS_MINS !== 'undefined' ? FOCUS_MINS : 25) * 60;
  const BREAK_SECS = (typeof BREAK_MINS !== 'undefined' ? BREAK_MINS : 5) * 60;

  let remaining   = FOCUS_SECS;
  let isRunning   = false;
  let isFocus     = true;
  let cyclesDone  = 0;
  let intervalId  = null;

  const display    = document.getElementById('timer-display');
  const icon       = document.getElementById('timer-icon');
  const phaseBadge = document.getElementById('timer-phase-badge');
  const cyclesInput = document.getElementById('cycles-input');

  function pad(n) { return String(n).padStart(2, '0'); }

  function updateDisplay() {
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    if (display) display.textContent = pad(m) + ':' + pad(s);
    document.title = pad(m) + ':' + pad(s) + ' - Cornote';
  }

  function tick() {
    if (remaining > 0) {
      remaining--;
      updateDisplay();
    } else {
      clearInterval(intervalId);
      isRunning = false;
      onPhaseEnd();
    }
  }

  function onPhaseEnd() {
    if (icon) icon.className = 'bi bi-play-fill';
    playChime();

    if (isFocus) {
      cyclesDone++;
      if (cyclesInput) cyclesInput.value = cyclesDone;
      isFocus   = false;
      remaining = BREAK_SECS;
      if (phaseBadge) {
        phaseBadge.textContent = 'Break';
        phaseBadge.classList.add('break-phase');
      }
      showTimerNotification('Focus session complete!', 'Time for a ' + BREAK_MINS + '-minute break.');
    } else {
      isFocus   = true;
      remaining = FOCUS_SECS;
      if (phaseBadge) {
        phaseBadge.textContent = 'Focus';
        phaseBadge.classList.remove('break-phase');
      }
      showTimerNotification('Break over!', 'Start your next focus session.');
    }
    updateDisplay();
  }

  function playChime() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const notes = [523, 659, 784];
      notes.forEach(function (freq, i) {
        const osc  = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = freq;
        osc.type = 'sine';
        gain.gain.setValueAtTime(0, ctx.currentTime + i * 0.22);
        gain.gain.linearRampToValueAtTime(0.18, ctx.currentTime + i * 0.22 + 0.05);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.22 + 0.55);
        osc.start(ctx.currentTime + i * 0.22);
        osc.stop(ctx.currentTime + i * 0.22 + 0.6);
      });
    } catch (e) { /* audio not available */ }
  }

  function showTimerNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(title, { body: body, icon: '/static/favicon.ico' });
    }
  }

  function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }

  // Public API attached to window
  window.timerToggle = function () {
    requestNotificationPermission();
    if (isRunning) {
      clearInterval(intervalId);
      isRunning = false;
      if (icon) icon.className = 'bi bi-play-fill';
    } else {
      isRunning = true;
      if (icon) icon.className = 'bi bi-pause-fill';
      intervalId = setInterval(tick, 1000);
    }
  };

  window.timerReset = function () {
    clearInterval(intervalId);
    isRunning = false;
    isFocus   = true;
    remaining = FOCUS_SECS;
    if (icon)       icon.className = 'bi bi-play-fill';
    if (phaseBadge) { phaseBadge.textContent = 'Focus'; phaseBadge.classList.remove('break-phase'); }
    updateDisplay();
  };

  // Log session to server on page unload (best-effort)
  window.addEventListener('beforeunload', function () {
    if (cyclesDone > 0 && typeof NOTEBOOK_PK !== 'undefined') {
      const form = document.getElementById('session-form');
      if (form) {
        navigator.sendBeacon(form.action, new FormData(form));
      }
    }
    document.title = 'Cornote';
  });

  updateDisplay();
})();
