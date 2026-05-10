/**
 * Offline Support - Client Side
 * Registers service worker and handles offline/online state
 */

document.addEventListener('DOMContentLoaded', function() {
  initializeOfflineSupport();
});

/**
 * Initialize offline support
 */
function initializeOfflineSupport() {
  // Register service worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/js/service-worker.js')
      .then((registration) => {
        console.log('[OfflineSupport] Service Worker registered:', registration);
        
        // Check for updates periodically
        setInterval(() => {
          registration.update();
        }, 60000); // Check every minute
      })
      .catch((error) => {
        console.warn('[OfflineSupport] Service Worker registration failed:', error);
      });

    // Listen for controller change
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      console.log('[OfflineSupport] Service Worker controller changed');
    });
  } else {
    console.log('[OfflineSupport] Service Workers not supported');
  }

  // Set up online/offline listeners
  window.addEventListener('online', handleOnline);
  window.addEventListener('offline', handleOffline);

  // Check initial online status
  if (!navigator.onLine) {
    handleOffline();
  }

  // Set up IndexedDB for offline queue (optional but recommended)
  initializeOfflineQueue();
}

/**
 * Handle going online
 */
function handleOnline() {
  console.log('[OfflineSupport] Going online');

  // Remove offline indicator
  removeOfflineIndicator();

  // Show notification
  showNotification('You are online!', {
    type: 'success',
    duration: 3000,
  });

  // Try to sync queued actions
  syncOfflineQueue();

  // Notify service worker to check for updates
  if (navigator.serviceWorker.controller) {
    navigator.serviceWorker.controller.postMessage({
      type: 'CHECK_FOR_UPDATES',
    });
  }
}

/**
 * Handle going offline
 */
function handleOffline() {
  console.log('[OfflineSupport] Going offline');

  // Show offline indicator
  showOfflineIndicator();

  // Show notification
  showNotification('You are offline - some features may be limited', {
    type: 'warning',
    duration: 5000,
  });

  // Disable certain buttons that require network
  disableNetworkDependentButtons();
}

/**
 * Show offline indicator
 */
function showOfflineIndicator() {
  const existingIndicator = document.querySelector('[data-offline-indicator]');
  if (existingIndicator) return;

  const indicator = document.createElement('div');
  indicator.setAttribute('data-offline-indicator', 'true');
  indicator.className = 'offline-indicator';
  indicator.innerHTML = `
    <div class="offline-bar">
      <span class="offline-icon">📡</span>
      <span class="offline-text">Offline Mode - Limited functionality</span>
      <button type="button" class="close-btn" aria-label="Dismiss notification">&times;</button>
    </div>
  `;

  document.body.insertBefore(indicator, document.body.firstChild);

  indicator.querySelector('.close-btn').addEventListener('click', () => {
    indicator.remove();
  });

  // Add CSS if not already present
  if (!document.querySelector('[data-offline-css]')) {
    const style = document.createElement('style');
    style.setAttribute('data-offline-css', 'true');
    style.textContent = `
      .offline-indicator {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 9999;
      }
      .offline-bar {
        background: linear-gradient(90deg, #f59e0b, #f97316);
        color: white;
        padding: 0.75rem 1rem;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.75rem;
        font-weight: 500;
        animation: slideDown 0.3s ease-out;
      }
      .offline-icon {
        font-size: 1.2rem;
      }
      .offline-text {
        flex: 1;
      }
      .close-btn {
        background: rgba(255, 255, 255, 0.2);
        border: none;
        color: white;
        cursor: pointer;
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
        font-size: 1.5rem;
        line-height: 1;
        transition: all 0.2s ease;
      }
      .close-btn:hover {
        background: rgba(255, 255, 255, 0.3);
      }
      @keyframes slideDown {
        from {
          transform: translateY(-100%);
          opacity: 0;
        }
        to {
          transform: translateY(0);
          opacity: 1;
        }
      }
      body.has-offline-indicator {
        padding-top: 3rem;
      }
    `;
    document.head.appendChild(style);
  }

  document.body.classList.add('has-offline-indicator');
}

/**
 * Remove offline indicator
 */
function removeOfflineIndicator() {
  const indicator = document.querySelector('[data-offline-indicator]');
  if (indicator) {
    indicator.remove();
    document.body.classList.remove('has-offline-indicator');
  }
}

/**
 * Disable buttons that require network
 */
function disableNetworkDependentButtons() {
  const networkButtons = document.querySelectorAll('[data-requires-network], .grade-btn, .sync-btn');
  networkButtons.forEach((btn) => {
    btn.disabled = true;
    btn.title = 'Requires internet connection';
    btn.classList.add('opacity-50');
  });
}

/**
 * Enable network-dependent buttons
 */
function enableNetworkDependentButtons() {
  const networkButtons = document.querySelectorAll('[data-requires-network], .grade-btn, .sync-btn');
  networkButtons.forEach((btn) => {
    btn.disabled = false;
    btn.title = '';
    btn.classList.remove('opacity-50');
  });
}

/**
 * Initialize offline queue using IndexedDB
 */
function initializeOfflineQueue() {
  if (!('indexedDB' in window)) {
    console.warn('[OfflineSupport] IndexedDB not supported');
    return;
  }

  const request = indexedDB.open('cornoteDB', 1);

  request.onerror = () => {
    console.warn('[OfflineSupport] Failed to open IndexedDB:', request.error);
  };

  request.onsuccess = (event) => {
    const db = event.target.result;
    console.log('[OfflineSupport] IndexedDB opened successfully');

    // Check if object store exists
    if (!db.objectStoreNames.contains('offlineQueue')) {
      console.log('[OfflineSupport] Creating offlineQueue object store');
    }
  };

  request.onupgradeneeded = (event) => {
    const db = event.target.result;

    // Create object store for offline queue
    if (!db.objectStoreNames.contains('offlineQueue')) {
      const store = db.createObjectStore('offlineQueue', { keyPath: 'id', autoIncrement: true });
      store.createIndex('timestamp', 'timestamp', { unique: false });
      console.log('[OfflineSupport] Created offlineQueue store');
    }

    // Create object store for cached answers
    if (!db.objectStoreNames.contains('cachedAnswers')) {
      const answerStore = db.createObjectStore('cachedAnswers', { keyPath: 'answerId', autoIncrement: false });
      answerStore.createIndex('notebook', 'notebook', { unique: false });
      console.log('[OfflineSupport] Created cachedAnswers store');
    }
  };
}

/**
 * Queue an action for offline execution
 */
window.queueOfflineAction = function(action, data) {
  if (!('indexedDB' in window)) {
    console.warn('[OfflineSupport] Cannot queue action - IndexedDB not available');
    return Promise.reject('IndexedDB not available');
  }

  const request = indexedDB.open('cornoteDB', 1);

  return new Promise((resolve, reject) => {
    request.onsuccess = (event) => {
      const db = event.target.result;
      const transaction = db.transaction(['offlineQueue'], 'readwrite');
      const store = transaction.objectStore('offlineQueue');

      const item = {
        action,
        data,
        timestamp: Date.now(),
        synced: false,
      };

      store.add(item);

      transaction.oncomplete = () => {
        console.log('[OfflineSupport] Action queued:', action);
        resolve(item);
      };

      transaction.onerror = () => {
        console.error('[OfflineSupport] Failed to queue action:', transaction.error);
        reject(transaction.error);
      };
    };

    request.onerror = () => {
      reject(request.error);
    };
  });
};

/**
 * Sync offline queue when coming back online
 */
function syncOfflineQueue() {
  if (!('indexedDB' in window)) {
    return;
  }

  const request = indexedDB.open('cornoteDB', 1);

  request.onsuccess = (event) => {
    const db = event.target.result;
    const transaction = db.transaction(['offlineQueue'], 'readonly');
    const store = transaction.objectStore('offlineQueue');
    const getAllRequest = store.getAll();

    getAllRequest.onsuccess = () => {
      const items = getAllRequest.result;
      console.log(`[OfflineSupport] Syncing ${items.length} offline items`);

      items.forEach((item) => {
        syncOfflineItem(item, db);
      });
    };
  };
}

/**
 * Sync individual offline item
 */
function syncOfflineItem(item, db) {
  // This would be implemented based on the specific action type
  console.log('[OfflineSupport] Syncing item:', item);

  // After successful sync, remove from queue
  removeOfflineItem(item.id, db);
}

/**
 * Remove item from offline queue
 */
function removeOfflineItem(itemId, db) {
  const transaction = db.transaction(['offlineQueue'], 'readwrite');
  const store = transaction.objectStore('offlineQueue');
  store.delete(itemId);

  transaction.oncomplete = () => {
    console.log('[OfflineSupport] Removed item from queue:', itemId);
  };
}

/**
 * Show notification (simple toast)
 */
function showNotification(message, options = {}) {
  const { type = 'info', duration = 3000 } = options;

  const notification = document.createElement('div');
  notification.className = `toast notification notification-${type}`;
  notification.textContent = message;
  notification.style.cssText = `
    position: fixed;
    bottom: 2rem;
    right: 2rem;
    background: ${type === 'success' ? '#059669' : type === 'error' ? '#ef4444' : type === 'warning' ? '#f59e0b' : '#3b82f6'};
    color: white;
    padding: 1rem;
    border-radius: 0.5rem;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    z-index: 5000;
    animation: slideInRight 0.3s ease-out;
    max-width: 300px;
  `;

  document.body.appendChild(notification);

  if (duration > 0) {
    setTimeout(() => {
      notification.style.animation = 'slideOutRight 0.3s ease-out';
      setTimeout(() => {
        notification.remove();
      }, 300);
    }, duration);
  }
}

console.log('[OfflineSupport] Offline support module loaded');
