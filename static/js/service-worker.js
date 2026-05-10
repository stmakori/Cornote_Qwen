/**
 * Cornote Service Worker - Offline Support
 * Caches static assets and study content for offline access
 */

const CACHE_NAME = 'cornote-v1';
const RUNTIME_CACHE = 'cornote-runtime-v1';
const API_CACHE = 'cornote-api-v1';

// Assets to pre-cache on install
const STATIC_ASSETS = [
  '/',
  '/static/css/cornote.css',
  '/static/js/cornote.js',
  '/static/js/timer.js',
  '/static/js/accessibility.js',
  '/static/js/features.js',
];

/**
 * Install event - cache essential assets
 */
self.addEventListener('install', (event) => {
  console.log('[ServiceWorker] Installing...');

  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[ServiceWorker] Caching static assets');
      return cache.addAll(STATIC_ASSETS).catch((error) => {
        console.warn('[ServiceWorker] Error caching assets:', error);
      });
    })
  );

  // Force the new service worker to take control immediately
  self.skipWaiting();
});

/**
 * Activate event - clean up old caches
 */
self.addEventListener('activate', (event) => {
  console.log('[ServiceWorker] Activating...');

  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME && cacheName !== RUNTIME_CACHE && cacheName !== API_CACHE) {
            console.log('[ServiceWorker] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );

  // Take control of all clients immediately
  return self.clients.claim();
});

/**
 * Fetch event - serve from cache, fallback to network
 */
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Skip non-GET requests
  if (event.request.method !== 'GET') {
    return;
  }

  // Skip external resources
  if (url.origin !== location.origin) {
    return;
  }

  // Handle API requests (study data)
  if (url.pathname.includes('/api/') || url.pathname.includes('/notebooks/')) {
    return event.respondWith(networkFirstStrategy(event.request));
  }

  // Handle static assets
  if (url.pathname.includes('/static/')) {
    return event.respondWith(cacheFirstStrategy(event.request));
  }

  // Default: network first, then cache
  event.respondWith(networkFirstStrategy(event.request));
});

/**
 * Cache first strategy - return cached response, fallback to network
 */
async function cacheFirstStrategy(request) {
  const cachedResponse = await caches.match(request);

  if (cachedResponse) {
    console.log('[ServiceWorker] Serving from cache:', request.url);
    return cachedResponse;
  }

  try {
    const networkResponse = await fetch(request);

    // Cache successful responses
    if (networkResponse && networkResponse.status === 200) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(request, networkResponse.clone());
    }

    return networkResponse;
  } catch (error) {
    console.warn('[ServiceWorker] Fetch failed for:', request.url, error);

    // Return offline page or cached version
    const cachedResponse = await caches.match(request);
    return cachedResponse || createOfflinePage();
  }
}

/**
 * Network first strategy - try network, fallback to cache
 */
async function networkFirstStrategy(request) {
  try {
    const networkResponse = await fetch(request);

    // Cache successful API responses
    if (networkResponse && networkResponse.status === 200 && request.method === 'GET') {
      const cache = await caches.open(API_CACHE);
      cache.put(request, networkResponse.clone());
    }

    return networkResponse;
  } catch (error) {
    console.warn('[ServiceWorker] Network request failed, trying cache:', request.url);

    // Fall back to cached response
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }

    // If it's an API request and no cache, return empty response
    if (request.url.includes('/api/')) {
      return new Response(
        JSON.stringify({
          error: 'Offline - content not available',
          offline: true,
        }),
        { headers: { 'Content-Type': 'application/json' } }
      );
    }

    return createOfflinePage();
  }
}

/**
 * Create offline fallback page
 */
function createOfflinePage() {
  return new Response(
    `
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Offline - Cornote</title>
      <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          background: #0f172a;
          color: #e2e8f0;
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 100vh;
          padding: 2rem;
        }
        .container {
          max-width: 500px;
          text-align: center;
        }
        h1 { font-size: 2rem; margin-bottom: 1rem; color: #f59e0b; }
        p { font-size: 1rem; margin-bottom: 0.5rem; color: #cbd5e1; }
        .icon { font-size: 4rem; margin-bottom: 1rem; }
        a {
          display: inline-block;
          margin-top: 2rem;
          padding: 0.75rem 1.5rem;
          background: #2563eb;
          color: white;
          text-decoration: none;
          border-radius: 0.5rem;
          transition: all 0.3s ease;
        }
        a:hover { background: #1d4ed8; }
      </style>
    </head>
    <body>
      <div class="container">
        <div class="icon">📡</div>
        <h1>You're Offline</h1>
        <p>It looks like you've lost your internet connection. Your study materials are still accessible if you've viewed them before.</p>
        <p style="margin-top: 1.5rem; font-size: 0.9rem; color: #94a3b8;">
          Cornote has cached your recently viewed content. Some features may be limited.
        </p>
        <a href="/">← Back to Cornote</a>
      </div>
    </body>
    </html>
    `,
    {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    }
  );
}

/**
 * Handle messages from the client
 */
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'CLEAR_CACHE') {
    console.log('[ServiceWorker] Clearing all caches...');
    caches.keys().then((cacheNames) => {
      cacheNames.forEach((cacheName) => {
        caches.delete(cacheName);
      });
    });
  }

  if (event.data && event.data.type === 'GET_CACHE_STATUS') {
    caches.keys().then((cacheNames) => {
      event.ports[0].postMessage({
        type: 'CACHE_STATUS',
        caches: cacheNames,
      });
    });
  }
});

/**
 * Periodic background sync (when online)
 * Sync queued answers when the app comes back online
 */
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-answers') {
    event.waitUntil(syncQueuedAnswers());
  }
});

/**
 * Sync queued answers to server
 */
async function syncQueuedAnswers() {
  try {
    // Get IndexedDB queue (if implemented by client)
    const queue = await getAllQueued();

    for (const item of queue) {
      try {
        const response = await fetch(item.url, {
          method: item.method,
          headers: item.headers,
          body: item.body,
        });

        if (response.ok) {
          await removeFromQueue(item.id);
        }
      } catch (error) {
        console.warn('[ServiceWorker] Failed to sync item:', item.id, error);
      }
    }
  } catch (error) {
    console.warn('[ServiceWorker] Sync failed:', error);
    throw error;
  }
}

/**
 * Placeholder functions for IndexedDB queue
 * These would be implemented when IndexedDB is set up
 */
async function getAllQueued() {
  // TODO: Implement IndexedDB retrieval
  return [];
}

async function removeFromQueue(id) {
  // TODO: Implement IndexedDB deletion
}

console.log('[ServiceWorker] Service Worker loaded and ready');
