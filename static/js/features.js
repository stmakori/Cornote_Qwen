/**
 * Cornote - Advanced Features
 * Full-screen mode, enhanced keyboard shortcuts, error handling
 */
(function () {
  'use strict';

  // ════════════════════════════════════════════════════════════
  //  FULL-SCREEN STUDY MODE
  // ════════════════════════════════════════════════════════════
  function initFullScreenMode() {
    const gridArea = document.querySelector('.cornell-grid');
    if (!gridArea) return;

    // Create fullscreen toggle button (if toolbar exists)
    const toolbar = document.querySelector('.notebook-toolbar');
    if (toolbar) {
      const fsBtn = document.createElement('button');
      fsBtn.className = 'btn btn-ghost btn-sm fullscreen-toggle';
      fsBtn.title = 'Full-screen Mode (Ctrl+Shift+F)';
      fsBtn.innerHTML = '<i class="bi bi-fullscreen"></i>';
      fsBtn.onclick = (e) => {
        e.preventDefault();
        toggleFullScreen();
      };
      toolbar.appendChild(fsBtn);
    }

    // Listen for fullscreen keyboard shortcut
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'f') {
        e.preventDefault();
        toggleFullScreen();
      }
    });

    function toggleFullScreen() {
      document.body.classList.toggle('fullscreen-mode');
      const icon = document.querySelector('.fullscreen-toggle i');
      if (document.body.classList.contains('fullscreen-mode')) {
        icon.className = 'bi bi-fullscreen-exit';
        localStorage.setItem('cornote_fullscreen', 'true');
      } else {
        icon.className = 'bi bi-fullscreen';
        localStorage.removeItem('cornote_fullscreen');
      }
    }

    // Restore fullscreen state from localStorage
    if (localStorage.getItem('cornote_fullscreen') === 'true') {
      toggleFullScreen();
    }
  }

  // ════════════════════════════════════════════════════════════
  //  ENHANCED KEYBOARD SHORTCUTS
  // ════════════════════════════════════════════════════════════
  function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Ctrl+G or Cmd+G → Grade all answers
      if ((e.ctrlKey || e.metaKey) && e.key === 'g') {
        e.preventDefault();
        const gradeBtn = document.querySelector('[hx-post*="grade"]');
        if (gradeBtn) {
          gradeBtn.click();
          showNotification('Grading answers...', 'info');
        }
      }

      // Ctrl+S or Cmd+S → Save all
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        document.querySelectorAll('[hx-post*="save"]').forEach((el) => {
          htmx.trigger(el, 'keyup');
        });
        showNotification('Saving...', 'info');
      }

      // Ctrl+1 → Focus questions
      if ((e.ctrlKey || e.metaKey) && e.key === '1') {
        e.preventDefault();
        const questions = document.querySelector('.cornell-questions');
        if (questions) {
          questions.focus();
          questions.scrollTop = 0;
        }
      }

      // Ctrl+2 → Focus notes
      if ((e.ctrlKey || e.metaKey) && e.key === '2') {
        e.preventDefault();
        const notes = document.querySelector('.notes-textarea');
        if (notes) notes.focus();
      }

      // Ctrl+3 → Focus summary
      if ((e.ctrlKey || e.metaKey) && e.key === '3') {
        e.preventDefault();
        const summary = document.querySelector('.summary-textarea');
        if (summary) summary.focus();
      }

      // Ctrl+Shift+H or Cmd+Shift+H → Get a hint for the current question
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'h') {
        e.preventDefault();
        const hintBtn = document.querySelector('.q-detail .question-block:not(.d-none) .hint-btn');
        if (hintBtn && !hintBtn.disabled) {
          hintBtn.click();
          showNotification('Requesting hint...', 'info');
        }
      }

      // Ctrl+? or Ctrl+Shift+/ → Show shortcuts help (browser may use Ctrl+Shift+/)
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === '?' || e.key === '/')) {
        e.preventDefault();
        showShortcutsModal();
      }

      // Plain ? on notebook page (not in form fields)
      if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const t = e.target;
        if (t && t.isContentEditable) return;
        const tag = t && t.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (!document.querySelector('.cornell-grid')) return;
        e.preventDefault();
        showShortcutsModal();
      }
    });
  }

  // ════════════════════════════════════════════════════════════
  //  NOTIFICATION SYSTEM
  // ════════════════════════════════════════════════════════════
  function showNotification(message, type = 'info') {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    alertDiv.style.position = 'fixed';
    alertDiv.style.top = '80px';
    alertDiv.style.right = '20px';
    alertDiv.style.zIndex = '1050';
    alertDiv.style.minWidth = '300px';
    alertDiv.innerHTML = `
      ${message}
      <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    document.body.appendChild(alertDiv);

    setTimeout(() => {
      alertDiv.remove();
    }, 3000);
  }

  // ════════════════════════════════════════════════════════════
  //  SHORTCUTS HELP MODAL
  // ════════════════════════════════════════════════════════════
  function showShortcutsModal() {
    const modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.tabIndex = '-1';
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content" style="background: var(--bg-surface); border-color: var(--bg-border);">
          <div class="modal-header" style="border-bottom-color: var(--bg-border);">
            <h5 class="modal-title">
              <i class="bi bi-keyboard me-2"></i>Keyboard Shortcuts
            </h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body" style="color: var(--text-primary);">
            <table class="table table-sm" style="color: inherit;">
              <tbody>
                <tr>
                  <td><kbd>Ctrl+G</kbd></td>
                  <td>Grade all answers</td>
                </tr>
                <tr>
                  <td><kbd>Ctrl+S</kbd></td>
                  <td>Save all (notes, answers, summary)</td>
                </tr>
                <tr>
                  <td><kbd>Ctrl+Shift+H</kbd></td>
                  <td>Get a hint for the current question</td>
                </tr>
                <tr>
                  <td><kbd>Ctrl+1</kbd></td>
                  <td>Focus questions column</td>
                </tr>
                <tr>
                  <td><kbd>Ctrl+2</kbd></td>
                  <td>Focus notes section</td>
                </tr>
                <tr>
                  <td><kbd>Ctrl+3</kbd></td>
                  <td>Focus summary area</td>
                </tr>
                <tr>
                  <td><kbd>Ctrl+Shift+/</kbd> or <kbd>?</kbd></td>
                  <td>Show this help (when not typing in a field)</td>
                </tr>
                <tr>
                  <td><kbd>Ctrl+Shift+F</kbd></td>
                  <td>Toggle full-screen mode</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="modal-footer" style="border-top-color: var(--bg-border);">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();

    modal.addEventListener('hidden.bs.modal', () => {
      modal.remove();
    });
  }

  // ════════════════════════════════════════════════════════════
  //  BETTER ERROR HANDLING
  // ════════════════════════════════════════════════════════════
  function initErrorHandling() {
    document.body.addEventListener('htmx:responseError', (evt) => {
      const status = evt.detail.xhr.status;
      const path = evt.detail.requestConfig.path;

      let message = 'An error occurred';
      if (status === 403) {
        message = 'Access denied. Please log in again.';
      } else if (status === 404) {
        message = 'Resource not found. Please refresh the page.';
      } else if (status === 500) {
        message = 'Server error. Your work may have been saved. Please try again.';
      } else if (status === 0) {
        message = 'Network error. Check your connection.';
      }

      showNotification(message, 'danger');
      console.error(`HTMX Error [${status}]: ${path}`, evt.detail);
    });

    // Also handle fetch errors
    window.addEventListener('error', (evt) => {
      if (evt.message.includes('fetch')) {
        showNotification('Network error. Please check your connection.', 'warning');
      }
    });
  }

  // ════════════════════════════════════════════════════════════
  //  MOBILE OPTIMIZATIONS
  // ════════════════════════════════════════════════════════════
  function initMobileOptimizations() {
    // Detect mobile
    const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
    
    if (isMobile) {
      document.body.classList.add('mobile-view');
      
      // Adjust Cornell grid for mobile
      const grid = document.querySelector('.cornell-grid');
      if (grid) {
        grid.style.gridTemplateColumns = '1fr';
        grid.style.height = 'auto';
      }

      // Increase touch target sizes
      const buttons = document.querySelectorAll('.btn');
      buttons.forEach((btn) => {
        if (!btn.classList.contains('btn-lg')) {
          btn.style.padding = '0.75rem 1rem';
          btn.style.minHeight = '44px';
        }
      });
    }
  }

  // ════════════════════════════════════════════════════════════
  //  INITIALIZATION
  // ════════════════════════════════════════════════════════════
  document.addEventListener('DOMContentLoaded', () => {
    initFullScreenMode();
    initKeyboardShortcuts();
    initErrorHandling();
    initMobileOptimizations();

    // Show shortcuts hint on notebook detail page
    const grid = document.querySelector('.cornell-grid');
    if (grid && !sessionStorage.getItem('cornote_shortcuts_hint')) {
      setTimeout(() => {
        showNotification('Tip: Press ? for keyboard shortcuts', 'info');
        sessionStorage.setItem('cornote_shortcuts_hint', '1');
      }, 2000);
    }
  });

  // Expose functions globally for direct use
  window.cornoteFeatures = {
    showNotification,
    showShortcutsModal,
  };
})();
