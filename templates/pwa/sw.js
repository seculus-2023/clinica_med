/* Service worker MedAccess v{{ versao }} */
const VERSAO = 'medaccess-{{ versao }}';
const ESTATICO = VERSAO + '-static';
const PRECACHE = [
  '/offline/',
  '/static/css/app.css',
  '/static/js/app.js',
  '/static/img/login-bg.jpg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(ESTATICO).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSAO)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function ehEstatico(url) {
  return url.pathname.startsWith('/static/') || /cdn\.jsdelivr\.net|fonts\.(googleapis|gstatic)\.com/.test(url.host);
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Arquivos estáticos e bibliotecas: cache primeiro
  if (ehEstatico(url)) {
    event.respondWith(
      caches.match(req).then((cache) => cache || fetch(req).then((resp) => {
        const copia = resp.clone();
        caches.open(ESTATICO).then((c) => c.put(req, copia));
        return resp;
      }))
    );
    return;
  }

  // Páginas: sempre da rede. Dados de pacientes NÃO são guardados em cache (LGPD);
  // sem conexão, exibe a página offline.
  if (req.mode === 'navigate' && url.origin === self.location.origin) {
    event.respondWith(fetch(req).catch(() => caches.match('/offline/')));
  }
});
