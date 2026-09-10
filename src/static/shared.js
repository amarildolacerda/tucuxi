// shared.js — utilidades comuns a todas as seções (fonte única de verdade)
// CameraFault permanece global (definido em /static/camera_fault.js, script clássico).

export function maskRtspUrl(url) {
  if (!url) return '';
  return url.replace(/(:\/\/[^:]+:)([^@]+)(@)/, '$1***$3');
}

export function formatUptime(ms) {
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export async function fetchData(url) {
  const response = await fetch(url);
  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('Não autenticado');
  }
  return response.json();
}

const _apiCache = new Map(); // url -> { ts, promise }
export async function fetchCached(url, ttlMs = 60000) {
  const cached = _apiCache.get(url);
  if (cached && (Date.now() - cached.ts) < ttlMs) return cached.promise;
  const promise = fetchData(url);
  _apiCache.set(url, { ts: Date.now(), promise });
  promise.catch(() => { const c = _apiCache.get(url); if (c && c.promise === promise) _apiCache.delete(url); });
  return promise;
}

export function invalidateCache(url) {
  if (url) _apiCache.delete(url);
  else _apiCache.clear();
}

export function timeAgo(ts) {
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return 'agora';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function openDialog(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('hidden-panel');
}
export function closeDialog(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden-panel');
}

export function showMenuMessage(message, targetId = 'camera-form-message') {
  const messageContainer = document.getElementById(targetId);
  if (messageContainer) {
    messageContainer.textContent = message;
    messageContainer.classList.remove('error');
    setTimeout(() => {
      messageContainer.textContent = '';
    }, 5000);
  }
}

export function ageLabelFromMs(ms) {
  if (!Number.isFinite(ms) || ms < 0) return '—';
  const seconds = Math.floor(ms / 1000);
  if (seconds < 5) return 'agora';
  if (seconds < 60) return `há ${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `há ${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `há ${h}h`;
  const d = Math.floor(h / 24);
  return `há ${d}d`;
}

/* ========== Dialogs compartilhados (overview + events) ========== */

export function thumbPhaseBadge(item) {
  if (item.dropped === true) return '<span class="thumb-phase-badge thumb-phase-dropped">descartado</span>';
  const lvl = item.level != null ? Number(item.level) : null;
  if (lvl === null || lvl === undefined) return '';
  const labels = ['N0', 'N1', 'N2', 'N3', 'N4'];
  const classes = ['thumb-phase-n0', 'thumb-phase-n1', 'thumb-phase-n2', 'thumb-phase-n3', 'thumb-phase-n4'];
  const label = labels[lvl] || ('N' + lvl);
  const cls = classes[lvl] || 'thumb-phase-n0';
  return `<span class="thumb-phase-badge ${cls}">${label}</span>`;
}

let livePlayerInterval = null;

export function openLivePlayer(cameraId, cameraName, source) {
  const overlay = document.getElementById('live-player-overlay');
  const title = document.getElementById('live-player-title');
  const videoEl = document.getElementById('live-video');
  const imgEl = document.getElementById('live-snapshot');
  const videoContainer = document.getElementById('live-video-container');
  const imgContainer = document.getElementById('live-snapshot-container');

  title.textContent = cameraName;
  overlay.classList.remove('hidden-panel');

  const isHLS = source.endsWith('.m3u8') || source.includes('.m3u8');
  const isHTTP = source.startsWith('http') && !isHLS;

  if (isHLS && typeof Hls !== 'undefined' && Hls.isSupported()) {
    videoContainer.style.display = '';
    imgContainer.style.display = 'none';
    const hls = new Hls({ liveSyncDurationCount: 2, enableWorker: true });
    hls.loadSource(source);
    hls.attachMedia(videoEl);
    hls.on(Hls.Events.MANIFEST_PARSED, () => videoEl.play().catch(() => {}));
    overlay._hls = hls;
  } else if (isHLS && videoEl.canPlayType('application/vnd.apple.mpegurl')) {
    videoContainer.style.display = '';
    imgContainer.style.display = 'none';
    videoEl.src = source;
    videoEl.play().catch(() => {});
  } else if (isHTTP) {
    videoContainer.style.display = '';
    imgContainer.style.display = 'none';
    videoEl.src = source;
    videoEl.play().catch(() => {});
  } else {
    videoContainer.style.display = 'none';
    imgContainer.style.display = '';
    imgEl.src = `/camera/${cameraId}/snapshot?ts=${Date.now()}`;
    livePlayerInterval = setInterval(() => {
      imgEl.src = `/camera/${cameraId}/snapshot?ts=${Date.now()}`;
    }, 500);
  }
}

export function closeLivePlayer() {
  const overlay = document.getElementById('live-player-overlay');
  const videoEl = document.getElementById('live-video');
  overlay.classList.add('hidden-panel');
  if (overlay._hls) {
    overlay._hls.destroy();
    overlay._hls = null;
  }
  videoEl.pause();
  videoEl.src = '';
  if (livePlayerInterval) {
    clearInterval(livePlayerInterval);
    livePlayerInterval = null;
  }
}

export function openThumbHistory(cameraId, cameraName) {
  const overlay = document.getElementById('thumb-history-overlay');
  const title = document.getElementById('thumb-history-title');
  const grid = document.getElementById('thumb-history-grid');
  const empty = document.getElementById('thumb-history-empty');

  title.textContent = `Histórico — ${cameraName}`;
  grid.innerHTML = '';
  empty.style.display = 'none';
  overlay.classList.remove('hidden-panel');

  fetch(`/camera/${cameraId}/thumbnails`)
    .then(r => r.json())
    .then(items => {
      if (!items || items.length === 0) {
        empty.style.display = '';
        return;
      }
      grid.innerHTML = items.map(item => `
        <div class="thumb-history-item" onclick="openThumbDetail('${item.url}', '${item.timestamp}', '${item.event_type || ''}', '${item.level != null ? item.level : ''}', '${item.disposition || ''}', ${item.dropped === true})">
          <img src="${item.url}" alt="thumbnail" loading="lazy" />
          <span class="thumb-history-time">${new Date(item.timestamp).toLocaleString()} ${thumbPhaseBadge(item)}</span>
          <span class="thumb-history-event">${item.event_type || ''}</span>
        </div>
      `).join('');
    })
    .catch(() => {
      empty.textContent = 'Falha ao carregar histórico.';
      empty.style.display = '';
    });
}

export function closeThumbHistory() {
  const overlay = document.getElementById('thumb-history-overlay');
  if (overlay) overlay.classList.add('hidden-panel');
}

export function openClipHistory(cameraId, cameraName) {
  const overlay = document.getElementById('clip-history-overlay');
  const title = document.getElementById('clip-history-title');
  const grid = document.getElementById('clip-history-grid');
  const empty = document.getElementById('clip-history-empty');

  title.textContent = `Clipes — ${cameraName}`;
  grid.innerHTML = '';
  empty.style.display = 'none';
  overlay.classList.remove('hidden-panel');

  fetch(`/camera/${cameraId}/clips`)
    .then(r => r.json())
    .then(items => {
      if (!items || items.length === 0) {
        empty.style.display = '';
        return;
      }
      grid.innerHTML = items.map(item => `
        <div class="clip-history-item">
          <video src="${item.url}" controls preload="metadata" style="width:100%;border-radius:var(--radius-sm);"></video>
          <span style="font-size:0.8rem;color:var(--muted-subtle);">
            ${new Date(item.timestamp).toLocaleString()} — ${item.duration_s ? item.duration_s.toFixed(0) + 's' : ''}
          </span>
        </div>
      `).join('');
    })
    .catch(() => {
      empty.textContent = 'Falha ao carregar clipes.';
      empty.style.display = '';
    });
}

export function closeClipHistory() {
  const overlay = document.getElementById('clip-history-overlay');
  if (overlay) overlay.classList.add('hidden-panel');
}

export const thumbZoomState = { scale: 1, x: 0, y: 0, dragging: false, dragStartX: 0, dragStartY: 0, originX: 0, originY: 0 };

export function applyThumbZoom() {
  const img = document.getElementById('thumb-detail-img');
  const label = document.getElementById('thumb-detail-zoom-label');
  if (!img) return;
  img.style.transform = `translate(${thumbZoomState.x}px, ${thumbZoomState.y}px) scale(${thumbZoomState.scale})`;
  img.style.width = img.dataset.naturalWidth ? `${img.dataset.naturalWidth}px` : '';
  img.style.height = img.dataset.naturalHeight ? `${img.dataset.naturalHeight}px` : '';
  if (label) label.textContent = `${Math.round(thumbZoomState.scale * 100)}%`;
}

export function resetThumbZoom() {
  thumbZoomState.scale = 1;
  thumbZoomState.x = 0;
  thumbZoomState.y = 0;
  applyThumbZoom();
}

export function setupThumbDetailZoom() {
  const viewport = document.getElementById('thumb-detail-viewport');
  const img = document.getElementById('thumb-detail-img');
  const btnIn = document.getElementById('thumb-detail-zoom-in');
  const btnOut = document.getElementById('thumb-detail-zoom-out');
  const btnReset = document.getElementById('thumb-detail-zoom-reset');
  if (!viewport || !img) return;
  if (viewport._zoomWired) return;
  viewport._zoomWired = true;

  viewport.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.2 : 1 / 1.2;
    const newScale = Math.max(0.2, Math.min(8, thumbZoomState.scale * factor));
    const ratio = newScale / thumbZoomState.scale;
    thumbZoomState.x = cx - ratio * (cx - thumbZoomState.x);
    thumbZoomState.y = cy - ratio * (cy - thumbZoomState.y);
    thumbZoomState.scale = newScale;
    applyThumbZoom();
  }, { passive: false });

  viewport.addEventListener('mousedown', (e) => {
    if (thumbZoomState.scale <= 1) return;
    thumbZoomState.dragging = true;
    thumbZoomState.dragStartX = e.clientX;
    thumbZoomState.dragStartY = e.clientY;
    thumbZoomState.originX = thumbZoomState.x;
    thumbZoomState.originY = thumbZoomState.y;
    viewport.classList.add('grabbing');
    e.preventDefault();
  });
  window.addEventListener('mousemove', (e) => {
    if (!thumbZoomState.dragging) return;
    thumbZoomState.x = thumbZoomState.originX + (e.clientX - thumbZoomState.dragStartX);
    thumbZoomState.y = thumbZoomState.originY + (e.clientY - thumbZoomState.dragStartY);
    applyThumbZoom();
  });
  window.addEventListener('mouseup', () => {
    thumbZoomState.dragging = false;
    viewport.classList.remove('grabbing');
  });

  viewport.addEventListener('dblclick', (e) => {
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    if (thumbZoomState.scale > 1) {
      resetThumbZoom();
    } else {
      const newScale = 2;
      const ratio = newScale / thumbZoomState.scale;
      thumbZoomState.x = cx - ratio * (cx - thumbZoomState.x);
      thumbZoomState.y = cy - ratio * (cy - thumbZoomState.y);
      thumbZoomState.scale = newScale;
      applyThumbZoom();
    }
  });

  btnIn && btnIn.addEventListener('click', () => {
    const newScale = Math.min(8, thumbZoomState.scale * 1.2);
    thumbZoomState.x = viewport.clientWidth / 2 - (newScale / thumbZoomState.scale) * (viewport.clientWidth / 2 - thumbZoomState.x);
    thumbZoomState.y = viewport.clientHeight / 2 - (newScale / thumbZoomState.scale) * (viewport.clientHeight / 2 - thumbZoomState.y);
    thumbZoomState.scale = newScale;
    applyThumbZoom();
  });
  btnOut && btnOut.addEventListener('click', () => {
    const newScale = Math.max(0.2, thumbZoomState.scale / 1.2);
    const ratio = newScale / thumbZoomState.scale;
    thumbZoomState.x = viewport.clientWidth / 2 - ratio * (viewport.clientWidth / 2 - thumbZoomState.x);
    thumbZoomState.y = viewport.clientHeight / 2 - ratio * (viewport.clientHeight / 2 - thumbZoomState.y);
    thumbZoomState.scale = newScale;
    applyThumbZoom();
  });
  btnReset && btnReset.addEventListener('click', resetThumbZoom);
}

export function openThumbDetail(url, timestamp, eventType, level, disposition, dropped, extra = {}) {
  const overlay = document.getElementById('thumb-detail-overlay');
  const title = document.getElementById('thumb-detail-title');
  const img = document.getElementById('thumb-detail-img');
  const meta = document.getElementById('thumb-detail-meta');

  if (!overlay._keysWired) {
    overlay._keysWired = true;
    overlay.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeThumbDetail();
        return;
      }
      if (e.key === '+' || e.key === '=') {
        e.preventDefault();
        thumbZoomState.scale = Math.min(8, thumbZoomState.scale * 1.2);
        applyThumbZoom();
      } else if (e.key === '-' || e.key === '_') {
        e.preventDefault();
        thumbZoomState.scale = Math.max(0.2, thumbZoomState.scale / 1.2);
        applyThumbZoom();
      } else if (e.key === '0') {
        e.preventDefault();
        resetThumbZoom();
      }
    });
  }
  if (!overlay.hasAttribute('tabindex')) overlay.setAttribute('tabindex', '-1');
  overlay.focus();

  title.textContent = extra.camera ? `${extra.camera} — Detalhe` : 'Detalhe do evento';
  img.src = url;
  img.onload = () => {
    img.dataset.naturalWidth = img.naturalWidth;
    img.dataset.naturalHeight = img.naturalHeight;
    resetThumbZoom();
  };
  if (img.complete) {
    img.dataset.naturalWidth = img.naturalWidth;
    img.dataset.naturalHeight = img.naturalHeight;
    resetThumbZoom();
  }

  const lvl = level !== '' && level !== null && level !== undefined ? Number(level) : null;
  const lvlLabel = lvl !== null ? (['N0', 'N1', 'N2', 'N3', 'N4'][lvl] || ('N' + lvl)) : null;
  const dispLabel = disposition ? `<span class="badge badge-info">${disposition}</span>` : '';
  const droppedLabel = dropped ? '<span class="badge badge-off">descartado</span>' : '';
  const lvlBadge = lvlLabel ? `<span class="badge badge-info">${lvlLabel}</span>` : '';

  const ageMs = Date.now() - new Date(timestamp).getTime();
  const ageLabel = ageMs >= 0 ? ageLabelFromMs(ageMs) : '—';
  meta.innerHTML = `
    ${extra.camera ? `<span><strong>Câmera:</strong> ${extra.camera}</span>` : ''}
    ${extra.zone ? `<span><strong>Zona:</strong> ${extra.zone}</span>` : ''}
    <span><strong>Data:</strong> ${new Date(timestamp).toLocaleString()} <em>(${ageLabel})</em></span>
    ${eventType ? `<span><strong>Tipo:</strong> ${eventType}</span>` : ''}
    ${lvlBadge}
    ${dispLabel}
    ${droppedLabel}
    ${extra.details ? `<span><strong>Detalhes:</strong> ${extra.details}</span>` : ''}
  `;

  setupThumbDetailZoom();
  resetThumbZoom();
  overlay.classList.remove('hidden-panel');
}

export function closeThumbDetail() {
  const overlay = document.getElementById('thumb-detail-overlay');
  if (overlay) overlay.classList.add('hidden-panel');
}

// Expõe no window para que os onclick inline dos dialogs funcionem (módulos
// ES não criam globais).
window.openLivePlayer = openLivePlayer;
window.closeLivePlayer = closeLivePlayer;
window.openThumbHistory = openThumbHistory;
window.closeThumbHistory = closeThumbHistory;
window.openThumbDetail = openThumbDetail;
window.closeThumbDetail = closeThumbDetail;
window.openClipHistory = openClipHistory;
window.closeClipHistory = closeClipHistory;
