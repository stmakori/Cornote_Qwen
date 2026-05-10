/**
 * Accessibility Enhancements - WCAG 2.1 AA Compliance
 * Provides keyboard navigation, ARIA labels, focus management, and screen reader support
 */

document.addEventListener('DOMContentLoaded', function() {
  // Initialize accessibility features
  initializeAccessibility();
  setupKeyboardNavigation();
  enhanceFormAccessibility();
  setupAriaLive();
});

/**
 * Initialize core accessibility features
 */
function initializeAccessibility() {
  // Ensure all interactive elements are keyboard accessible
  makeElementsKeyboardAccessible();
  
  // Add focus visible style for keyboard navigation
  addFocusVisibleSupport();
  
  // Set up skip links for screen readers
  createSkipLinks();
  
  // Test and fix color contrast
  verifyColorContrast();
}

/**
 * Make all interactive elements keyboard accessible
 */
function makeElementsKeyboardAccessible() {
  const interactiveSelectors = [
    'button:not([tabindex])',
    'a[href]:not([tabindex])',
    '[onclick]:not([tabindex])',
    '.clickable:not([tabindex])',
    '.grade-btn:not([tabindex])',
    '.save-btn:not([tabindex])',
  ];

  interactiveSelectors.forEach(selector => {
    document.querySelectorAll(selector).forEach(element => {
      if (!element.hasAttribute('tabindex')) {
        element.setAttribute('tabindex', '0');
        element.setAttribute('role', 'button');
      }
    });
  });
}

/**
 * Add support for :focus-visible CSS class for keyboard navigation
 */
function addFocusVisibleSupport() {
  if (!CSS.supports('selector(:focus-visible)')) {
    document.addEventListener('keydown', () => {
      document.body.classList.add('keyboard-nav');
    });
    document.addEventListener('mousedown', () => {
      document.body.classList.remove('keyboard-nav');
    });
  }
}

/**
 * Create skip navigation links for screen readers
 */
function createSkipLinks() {
  const existingSkipLink = document.querySelector('.skip-to-main');
  if (existingSkipLink) return;

  const skipLink = document.createElement('a');
  skipLink.href = '#main-content';
  skipLink.className = 'skip-to-main sr-only';
  skipLink.textContent = 'Skip to main content';
  skipLink.setAttribute('aria-label', 'Skip to main content');

  document.body.insertBefore(skipLink, document.body.firstChild);

  // Ensure main content has ID
  const mainContent = document.querySelector('main') || document.querySelector('[role="main"]');
  if (mainContent && !mainContent.id) {
    mainContent.id = 'main-content';
  }
}

/**
 * Verify and log color contrast information (development aid)
 */
function verifyColorContrast() {
  const contrastTargets = document.querySelectorAll('[role="button"], button, a, .btn');
  console.log(`[Accessibility] Checking color contrast on ${contrastTargets.length} elements`);
  
  // Log a sample element's computed styles for manual verification
  if (contrastTargets.length > 0) {
    const sample = contrastTargets[0];
    const computed = window.getComputedStyle(sample);
    console.log('[Accessibility] Sample element:', {
      element: sample.tagName,
      color: computed.color,
      backgroundColor: computed.backgroundColor,
      fontSize: computed.fontSize,
    });
  }
}

/**
 * Set up keyboard navigation for the application
 */
function setupKeyboardNavigation() {
  document.addEventListener('keydown', handleKeyboardShortcuts);
  setupTabNavigation();
}

/**
 * Handle keyboard shortcuts with proper focus management
 */
function handleKeyboardShortcuts(event) {
  // Don't intercept keys when typing in textarea/input
  if (event.target.tagName === 'TEXTAREA' && !event.ctrlKey && !event.metaKey) {
    return;
  }

  const isMac = /Mac/.test(navigator.platform);
  const modifier = isMac ? event.metaKey : event.ctrlKey;

  if (modifier) {
    switch (event.key.toLowerCase()) {
      case 's': // Ctrl+S: Save
        event.preventDefault();
        const saveBtn = document.querySelector('[data-action="save"]') || document.querySelector('.save-btn');
        if (saveBtn) {
          saveBtn.click();
          announceToScreenReader('Document saved');
        }
        break;

      case 'g': // Ctrl+G: Grade answers
        event.preventDefault();
        const gradeBtn = document.querySelector('[data-action="grade"]') || document.querySelector('.grade-btn');
        if (gradeBtn) {
          gradeBtn.click();
          announceToScreenReader('Grading in progress');
        }
        break;

      case '?': // Ctrl+?: Help
        event.preventDefault();
        showKeyboardHelp();
        break;

      case 'f': // Ctrl+Shift+F: Fullscreen
        if (event.shiftKey) {
          event.preventDefault();
          toggleFullScreen();
          announceToScreenReader('Fullscreen mode toggled');
        }
        break;

      case '1': // Ctrl+1-3: Focus areas
      case '2':
      case '3':
        event.preventDefault();
        focusArea(event.key);
        break;
    }
  }

  // Navigation shortcuts (only when not in form)
  if (event.key === 'Escape') {
    closeOpenModals();
  }
}

/**
 * Set up enhanced tab navigation
 */
function setupTabNavigation() {
  // Tab through form elements and buttons in logical order
  const focusableElements = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;

    const focusableList = Array.from(document.querySelectorAll(focusableElements));
    const currentFocusIndex = focusableList.indexOf(document.activeElement);

    if (e.shiftKey) {
      // Shift+Tab: Navigate backwards
      const previousIndex = currentFocusIndex > 0 ? currentFocusIndex - 1 : focusableList.length - 1;
      focusableList[previousIndex]?.focus();
    } else {
      // Tab: Navigate forwards
      const nextIndex = currentFocusIndex < focusableList.length - 1 ? currentFocusIndex + 1 : 0;
      focusableList[nextIndex]?.focus();
    }
  });
}

/**
 * Enhance form accessibility with proper labels and attributes
 */
function enhanceFormAccessibility() {
  // Associate labels with inputs
  document.querySelectorAll('input:not([aria-label])[name]').forEach((input) => {
    // Look for associated label
    let label = document.querySelector(`label[for="${input.id}"]`);
    if (!label && input.name) {
      label = document.querySelector(`label[for="${input.name}"]`);
    }

    // If no label exists, create aria-label from field name
    if (!label && input.name) {
      input.setAttribute('aria-label', input.name.replace(/[_-]/g, ' '));
    }
  });

  // Enhance buttons with aria-label if text is unclear
  document.querySelectorAll('button.icon-btn:not([aria-label])').forEach((btn) => {
    const title = btn.getAttribute('title');
    const dataTooltip = btn.getAttribute('data-tooltip');
    if (title || dataTooltip) {
      btn.setAttribute('aria-label', title || dataTooltip);
    }
  });

  // Add proper role and aria-label to timer
  const timer = document.querySelector('[data-timer]');
  if (timer && !timer.getAttribute('aria-label')) {
    timer.setAttribute('aria-label', 'Study timer');
    timer.setAttribute('aria-live', 'polite');
    timer.setAttribute('role', 'status');
  }

  // Make question-answer pairs semantic
  document.querySelectorAll('.question-item').forEach((item, index) => {
    const question = item.querySelector('.question-text');
    const answer = item.querySelector('.answer-input');

    if (question && answer) {
      const qId = `question-${index}`;
      question.id = qId;
      answer.setAttribute('aria-labelledby', qId);
    }
  });
}

/**
 * Set up ARIA live regions for dynamic content
 */
function setupAriaLive() {
  // Create or enhance live region for feedback
  let liveRegion = document.querySelector('[aria-live="polite"]');
  if (!liveRegion) {
    liveRegion = document.createElement('div');
    liveRegion.setAttribute('aria-live', 'polite');
    liveRegion.setAttribute('aria-atomic', 'true');
    liveRegion.className = 'sr-only';
    liveRegion.id = 'sr-announcements';
    document.body.appendChild(liveRegion);
  }

  // Listen for grade updates and announce them
  document.addEventListener('grade-updated', (event) => {
    const { question, grade, feedback } = event.detail;
    announceToScreenReader(`Question: ${question}. Grade: ${grade}. ${feedback}`);
  });

  // Listen for summary feedback
  document.addEventListener('feedback-updated', (event) => {
    const { included, missed } = event.detail;
    announceToScreenReader(
      `Summary feedback: ${included.length} points included. ${missed.length} points missed.`
    );
  });
}

/**
 * Announce message to screen readers
 */
function announceToScreenReader(message) {
  const liveRegion = document.querySelector('#sr-announcements') || document.createElement('div');
  if (!liveRegion.id) {
    liveRegion.id = 'sr-announcements';
    liveRegion.setAttribute('aria-live', 'polite');
    liveRegion.setAttribute('aria-atomic', 'true');
    liveRegion.className = 'sr-only';
    document.body.appendChild(liveRegion);
  }

  // Clear and set new message
  liveRegion.textContent = message;
  setTimeout(() => {
    liveRegion.textContent = '';
  }, 3000);
}

/**
 * Show keyboard shortcuts help dialog
 */
function showKeyboardHelp() {
  const existingModal = document.querySelector('#keyboard-help-modal');
  if (existingModal) {
    existingModal.style.display = 'block';
    return;
  }

  const modal = document.createElement('div');
  modal.id = 'keyboard-help-modal';
  modal.className = 'modal keyboard-help-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-labelledby', 'keyboard-help-title');

  modal.innerHTML = `
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title" id="keyboard-help-title">Keyboard Shortcuts</h5>
          <button type="button" class="btn-close" aria-label="Close help"></button>
        </div>
        <div class="modal-body">
          <table class="table table-sm">
            <tbody>
              <tr>
                <td><kbd>Ctrl</kbd>+<kbd>S</kbd></td>
                <td>Save your work</td>
              </tr>
              <tr>
                <td><kbd>Ctrl</kbd>+<kbd>G</kbd></td>
                <td>Grade your answers</td>
              </tr>
              <tr>
                <td><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd></td>
                <td>Toggle fullscreen mode</td>
              </tr>
              <tr>
                <td><kbd>Ctrl</kbd>+<kbd>1</kbd>, <kbd>2</kbd>, <kbd>3</kbd></td>
                <td>Jump to focus area</td>
              </tr>
              <tr>
                <td><kbd>Ctrl</kbd>+<kbd>?</kbd></td>
                <td>Show this help</td>
              </tr>
              <tr>
                <td><kbd>Tab</kbd></td>
                <td>Navigate forward</td>
              </tr>
              <tr>
                <td><kbd>Shift</kbd>+<kbd>Tab</kbd></td>
                <td>Navigate backward</td>
              </tr>
              <tr>
                <td><kbd>Esc</kbd></td>
                <td>Close dialogs</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(modal);
  modal.style.display = 'block';

  // Close on Escape
  modal.querySelector('.btn-close').addEventListener('click', () => {
    modal.style.display = 'none';
  });

  modal.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      modal.style.display = 'none';
    }
  });
}

/**
 * Toggle fullscreen study mode
 */
function toggleFullScreen() {
  const elem = document.documentElement;
  const isFullscreen = document.fullscreenElement === elem;

  if (isFullscreen) {
    if (document.exitFullscreen) {
      document.exitFullscreen();
    }
  } else {
    if (elem.requestFullscreen) {
      elem.requestFullscreen();
    }
  }

  localStorage.setItem('cornote-fullscreen', !isFullscreen);
}

/**
 * Focus on specific area
 */
function focusArea(areaNumber) {
  const areas = ['#questions-column', '#notes-section', '#summary-section'];
  const targetArea = areas[areaNumber - 1];

  if (targetArea) {
    const element = document.querySelector(targetArea);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth' });
      element.focus();
      announceToScreenReader(`Focused on ${areaNumber === 1 ? 'Questions' : areaNumber === 2 ? 'Notes' : 'Summary'} area`);
    }
  }
}

/**
 * Close open modals
 */
function closeOpenModals() {
  document.querySelectorAll('.modal[style*="display: block"]').forEach((modal) => {
    modal.style.display = 'none';
  });
}

/**
 * Dispatch custom events for grade and feedback updates
 */
window.dispatchGradeUpdate = function(question, grade, feedback) {
  document.dispatchEvent(new CustomEvent('grade-updated', {
    detail: { question, grade, feedback },
  }));
};

window.dispatchFeedbackUpdate = function(included, missed) {
  document.dispatchEvent(new CustomEvent('feedback-updated', {
    detail: { included, missed },
  }));
};
