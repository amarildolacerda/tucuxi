// overview.js — seção "Visão geral" (carregada no boot)
import { fetchData, ageLabelFromMs, maskRtspUrl } from '../shared.js';
import { loadSection } from '../core.js';

// Estado de módulo
let showOfflineCameras = false;
const snapshotTimes = {};
const cameraFaultState = {}; // id -> { status, firstFailAt, timer }
const SNAPSHOT_RETRY_INTERVAL_MS = CameraFault.FAULT_DEFAULTS.retryIntervalMs;
const SNAPSHOT_OFFLINE_RETRY_INTERVAL_MS = CameraFault.FAULT_DEFAULTS.offlineRetryIntervalMs;
const SNAPSHOT_OFFLINE_THRESHOLD_MS = CameraFault.FAULT_DEFAULTS.offlineThresholdMs;
const SNAPSHOT_MAX_AGE_MS = 30000;

let _overviewTimer = null;
let _statusTimer = null;

function createSummaryCard(title, value, subtitle = "") {
  return `
    <div class="card">
      <h3>${title}</h3>
      <p class="summary-value">${value}</p>
      <p>${subtitle}</p>
    </div>
  `;
}

function createCameraCard(camera, offline = false, lastEventTs = null, n0Count = 0) {
  const faultOffline = cameraFaultState[camera.id] && cameraFaultState[camera.id].status === 'offline';
  offline = offline || faultOffline;
  const zoneLabel = camera.zone || '-';
  const imgId = `snapshot-${camera.id}`;
  const offlineBadge = offline
    ? '<span class="badge-offline">Offline</span>'
    : '';
  const n0Badge = n0Count > 0
    ? `<span class="badge badge-info" title="Eventos N0 (captura) desta câmera">N0: ${n0Count}</span>`
    : '';
  const lastEventLabel = lastEventTs
    ? new Date(lastEventTs).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
    : 'Sem eventos';

  return `
    <div class="card camera-card${offline ? ' camera-card-offline' : ''}" data-camera-id="${camera.id}">
      <div class="camera-card-header">
        <strong>${camera.name}</strong>
        <span class="camera-badge">ID ${camera.id}</span> <span class="n0-badge-slot">${n0Badge}</span>
      </div>
      <p class="camera-zone">Zona: ${zoneLabel} ${offlineBadge}</p>
      <p class="camera-source">Fonte: ${maskRtspUrl(camera.source)}</p>
      <p class="camera-card-time">Último evento: ${lastEventLabel}</p>
      <div
        class="camera-preview-wrapper"
        data-camera-id="${camera.id}"
        onclick="openThumbHistory(${camera.id}, '${camera.name}')"
        style="cursor:pointer;"
      >
        <img
          id="${imgId}"
          class="camera-preview"
          alt="Preview da câmera"
          onload="onSnapshotLoad(${camera.id}, this)"
          onerror="onSnapshotError(${camera.id}, this)"
        />
        <span class="snapshot-age" data-camera-id="${camera.id}" hidden>--</span>
        <div class="camera-preview-error" style="display:none;">
          <span>Falha ao carregar preview</span>
          <button class="button-mini" onclick="event.stopPropagation(); retrySnapshot(${camera.id})">Tentar novamente</button>
        </div>
      </div>
      <div class="camera-card-actions">
        <button class="button-secondary button-mini" onclick="event.stopPropagation(); openLivePlayer(${camera.id}, '${camera.name}', '${camera.source}')">Ao vivo</button>
      </div>
    </div>
  `;
}

function retrySnapshot(cameraId) {
  const img = document.getElementById(`snapshot-${cameraId}`);
  if (img) {
    const wrapper = img.parentElement;
    wrapper.classList.add('loading');
    wrapper.classList.remove('error');
    img.style.display = '';
    img.nextElementSibling.style.display = 'none';
    fetchSnapshotWithHeader(cameraId, `/camera/${cameraId}/snapshot?ts=${Date.now()}`);
  }
}

function retrySnapshotNow(cameraId) {
  const img = document.getElementById(`snapshot-${cameraId}`);
  if (!img) return;
  const wrapper = img.parentElement;
  wrapper.classList.add('loading');
  wrapper.classList.remove('error');
  img.style.display = '';
  img.nextElementSibling.style.display = 'none';
  fetchSnapshotWithHeader(cameraId, `/camera/${cameraId}/snapshot?ts=${Date.now()}`);
}

function onSnapshotError(cameraId, el) {
  const wrapper = el.parentElement;
  wrapper.classList.remove('loading');
  wrapper.classList.add('error');
  el.dataset.loading = '';
  const img = el;
  img.style.display = 'none';
  const ageSpan = wrapper.querySelector('.snapshot-age');
  if (ageSpan) ageSpan.hidden = true;
  img.nextElementSibling.style.display = 'flex';

  const prev = cameraFaultState[cameraId] || null;
  const { state } = CameraFault.transitionFault(prev, 'error', Date.now());
  cameraFaultState[cameraId] = state;
  scheduleSnapshotRetry(cameraId);
  refreshSnapshotFallback(cameraId);
}

function ageLabel(capturedIso) {
  const captured = new Date(capturedIso).getTime();
  if (!Number.isFinite(captured)) return '—';
  return ageLabelFromMs(Date.now() - captured);
}

function refreshSnapshotAges() {
  document.querySelectorAll('.snapshot-age[data-camera-id]').forEach(span => {
    const id = span.dataset.cameraId;
    const ts = snapshotTimes[id];
    if (!ts) return;
    span.textContent = `📷 ${ageLabel(ts)}`;
    span.title = `Frame capturado em ${new Date(ts).toLocaleString('pt-BR')}`;
    span.hidden = false;
  });
}
if (!window._snapshotAgeTimer) {
  window._snapshotAgeTimer = setInterval(refreshSnapshotAges, 1000);
}

function fetchSnapshotTime(cameraId, srcUrl) {
  try {
    const xhr = new XMLHttpRequest();
    xhr.open('GET', srcUrl);
    xhr.onload = function () {
      const ts = xhr.getResponseHeader('X-Snapshot-Time');
      if (ts) {
        snapshotTimes[cameraId] = ts;
        refreshSnapshotAges();
      }
    };
    xhr.send();
  } catch (e) { /* sem header: span fica oculto */ }
}

async function fetchSnapshotWithHeader(cameraId, url) {
  try {
    const resp = await fetch(url);
    const img = document.getElementById(`snapshot-${cameraId}`);
    if (!resp.ok) { if (img) onSnapshotError(cameraId, img); return; }
    const ts = resp.headers.get('X-Snapshot-Time');
    if (ts) { snapshotTimes[cameraId] = ts; refreshSnapshotAges(); }
    const blob = await resp.blob();
    if (!img) return;
    const blobUrl = URL.createObjectURL(blob);
    img.src = blobUrl;
  } catch (e) {
    const img = document.getElementById(`snapshot-${cameraId}`);
    if (img) onSnapshotError(cameraId, img);
  }
}

function onSnapshotLoad(cameraId, el) {
  if (el.src && el.src.startsWith('blob:')) {
    const wrapper = el.parentElement;
    wrapper.classList.remove('loading');
    wrapper.classList.remove('error');
    const t = cameraFaultState[cameraId];
    if (t && t.timer) clearTimeout(t.timer);
    delete cameraFaultState[cameraId];
    refreshSnapshotFallback(cameraId);
    el.dataset.loading = '';
    return;
  }
  fetchSnapshotWithHeader(cameraId, el.currentSrc || el.src);
}

function scheduleSnapshotRetry(cameraId) {
  const state = cameraFaultState[cameraId];
  if (!state || state.timer) return;
  const interval = CameraFault.nextRetryIntervalMs(state);
  state.timer = setTimeout(() => {
    state.timer = null;
    const res = CameraFault.transitionFault(state, 'error', Date.now());
    cameraFaultState[cameraId] = res.state;
    if (res.offline) refreshSnapshotFallback(cameraId);
    if (res.reload) retrySnapshotNow(cameraId);
    if (res.state && res.state.status === 'offline') {
      scheduleSnapshotRetry(cameraId);
    } else if (res.state) {
      scheduleSnapshotRetry(cameraId);
    }
  }, interval);
}

function markSnapshotOffline(cameraId) {
  const state = cameraFaultState[cameraId];
  if (!state) return;
  state.status = 'offline';
  refreshSnapshotFallback(cameraId);
  scheduleSnapshotRetry(cameraId);
}

function refreshSnapshotFallback(cameraId) {
  const img = document.getElementById(`snapshot-${cameraId}`);
  if (!img) return;
  const wrapper = img.parentElement;
  const fallback = wrapper.querySelector('.camera-preview-error');
  if (!fallback) return;
  const state = cameraFaultState[cameraId];
  const msg = fallback.querySelector('span');
  if (msg) {
    if (state && state.status === 'offline') {
      msg.textContent = 'Sem resposta (offline)';
    } else if (state && state.status === 'retrying') {
      msg.textContent = 'Tentando novamente…';
    } else {
      msg.textContent = 'Falha ao carregar preview';
    }
  }
}

const snapshotObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    const wrapper = entry.target;
    const img = wrapper.querySelector('.camera-preview');
    if (entry.isIntersecting) {
      wrapper.classList.add('in-viewport');
      if (img && !img.dataset.loaded) {
        img.dataset.loaded = '1';
        img.src = `/camera/${wrapper.dataset.cameraId}/snapshot?ts=${Date.now()}`;
      }
    } else {
      wrapper.classList.remove('in-viewport');
    }
  });
}, { rootMargin: '100px' });

function observeSnapshots() {
  document.querySelectorAll('.camera-preview-wrapper').forEach(wrapper => {
    snapshotObserver.observe(wrapper);
  });
}

function refreshSnapshot(cameraId, force = false) {
  const img = document.getElementById(`snapshot-${cameraId}`);
  if (!img || img.dataset.loading === '1') return;
  const wrapper = img.parentElement;
  if (wrapper.classList.contains('error')) return;
  const ts = snapshotTimes[String(cameraId)];
  if (!force && ts && (Date.now() - new Date(ts).getTime()) < SNAPSHOT_MAX_AGE_MS) return;
  img.dataset.loading = '1';
  img.src = `/camera/${cameraId}/snapshot?ts=${Date.now()}`;
}

function updateVisibleSnapshots(cameras) {
  cameras.forEach(camera => {
    const img = document.getElementById(`snapshot-${camera.id}`);
    if (!img || !img.dataset.loaded) return;
    const wrapper = img.parentElement;
    if (!wrapper || !wrapper.classList.contains('in-viewport')) return;
    if (wrapper.classList.contains('error')) return;
    refreshSnapshot(camera.id, false);
  });
}

function setupHoverFreshSnapshots() {
  if (window._hoverFreshWired) return;
  window._hoverFreshWired = true;
  document.addEventListener('mouseover', (e) => {
    const wrapper = e.target.closest('.camera-preview-wrapper');
    if (!wrapper) return;
    const cameraId = wrapper.dataset.cameraId;
    if (cameraId) refreshSnapshot(cameraId, true);
  });
}

function buildLastEventMap(events) {
  const map = new Map();
  events.forEach(e => {
    if (e.camera_id == null) return;
    const ts = new Date(e.timestamp).getTime();
    if (!map.has(e.camera_id) || ts > map.get(e.camera_id)) map.set(e.camera_id, ts);
  });
  return map;
}

function countEventsByCamera(events) {
  const map = new Map();
  events.forEach(e => {
    if (e.camera_id == null) return;
    const key = String(e.camera_id);
    map.set(key, (map.get(key) || 0) + 1);
  });
  return map;
}

function sortCamerasByLastEvent(cameras, lastEventMap) {
  return [...cameras].sort((a, b) => (lastEventMap.get(b.id) || 0) - (lastEventMap.get(a.id) || 0));
}

function renderCameraTiles(cameras, workerStatus, lastEventMap = new Map(), n0ByCamera = new Map()) {
  const tilesContainer = document.getElementById('camera-tiles');
  const emptyState = document.getElementById('camera-empty-state');
  if (!tilesContainer) return;

  if (!cameras.length) {
    tilesContainer.innerHTML = '';
    updateOfflineSection([], null, lastEventMap, n0ByCamera);
    if (emptyState) emptyState.classList.remove('hidden-panel');
    return;
  }
  if (emptyState) emptyState.classList.add('hidden-panel');

  const activeIds = new Set((workerStatus || []).filter(w => w.healthy !== false).map(w => w.camera_id));
  const offlineCameras = workerStatus ? cameras.filter(c => !activeIds.has(c.id)) : [];
  const onlineCameras = workerStatus ? cameras.filter(c => activeIds.has(c.id)) : cameras;

  const existing = new Map();
  tilesContainer.querySelectorAll('.camera-card[data-camera-id]').forEach(el => {
    existing.set(String(el.dataset.cameraId), el);
  });
  const fragment = document.createDocumentFragment();
  onlineCameras.forEach(c => {
    const key = String(c.id);
    const n0Count = n0ByCamera.get(key) || 0;
    const existingEl = existing.get(key);
    if (existingEl) {
      updateCameraCard(existingEl, c, false, lastEventMap.get(c.id), n0Count);
      existing.delete(key);
      return;
    }
    const wrapper = document.createElement('div');
    wrapper.innerHTML = createCameraCard(c, false, lastEventMap.get(c.id), n0Count);
    fragment.appendChild(wrapper.firstElementChild);
  });
  const newChildren = Array.from(fragment.children);
  tilesContainer.innerHTML = '';
  newChildren.forEach(el => tilesContainer.appendChild(el));
  existing.forEach(el => tilesContainer.appendChild(el));

  updateOfflineSection(cameras, workerStatus, lastEventMap, n0ByCamera);
  observeSnapshots();
}

function updateCameraCard(el, camera, offline, lastEventTs, n0Count) {
  const faultOffline = cameraFaultState[camera.id] && cameraFaultState[camera.id].status === 'offline';
  const isOffline = offline || faultOffline;
  el.classList.toggle('camera-card-offline', isOffline);

  const n0Slot = el.querySelector('.n0-badge-slot');
  if (n0Slot) {
    n0Slot.innerHTML = n0Count > 0
      ? `<span class="badge badge-info" title="Eventos N0 (captura) desta câmera">N0: ${n0Count}</span>`
      : '';
  }

  const zoneP = el.querySelector('.camera-zone');
  if (zoneP) {
    let offlineBadge = zoneP.querySelector('.badge-offline');
    if (isOffline && !offlineBadge) {
      offlineBadge = document.createElement('span');
      offlineBadge.className = 'badge-offline';
      offlineBadge.textContent = 'Offline';
      zoneP.appendChild(document.createTextNode(' '));
      zoneP.appendChild(offlineBadge);
    } else if (!isOffline && offlineBadge) {
      offlineBadge.remove();
    }
  }

  const timeEl = el.querySelector('.camera-card-time');
  if (timeEl) {
    const label = lastEventTs
      ? new Date(lastEventTs).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
      : 'Sem eventos';
    timeEl.textContent = `Último evento: ${label}`;
  }
}

function updateOfflineSection(cameras, workerStatus, lastEventMap = new Map(), n0ByCamera = new Map()) {
  const offlineBar = document.getElementById('camera-offline-bar');
  const offlineSection = document.getElementById('camera-offline-section');
  const offlineList = document.getElementById('camera-offline-list');
  const offlineLabel = document.getElementById('camera-offline-toggle-label');
  if (!offlineBar || !offlineSection) return;

  const activeIds = new Set((workerStatus || []).filter(w => w.healthy !== false).map(w => w.camera_id));
  const offlineCameras = workerStatus ? cameras.filter(c => !activeIds.has(c.id)) : [];

  if (offlineCameras.length) {
    if (offlineList) offlineList.innerHTML = offlineCameras.map(c => createCameraCard(c, true, lastEventMap.get(c.id), n0ByCamera.get(String(c.id)) || 0)).join('');
    if (offlineLabel) offlineLabel.textContent = `Ver offline (${offlineCameras.length})`;
    offlineBar.classList.remove('hidden-panel');
    offlineSection.classList.toggle('hidden-panel', !showOfflineCameras);
  } else {
    if (offlineList) offlineList.innerHTML = '';
    offlineBar.classList.add('hidden-panel');
    offlineSection.classList.add('hidden-panel');
  }
}

function setupOfflineToggle() {
  const toggle = document.getElementById('show-offline-cameras');
  if (!toggle) return;
  toggle.addEventListener('change', () => {
    showOfflineCameras = toggle.checked;
    const offlineSection = document.getElementById('camera-offline-section');
    if (offlineSection) offlineSection.classList.toggle('hidden-panel', !showOfflineCameras);
  });
}

function statusBadgeClass(item) {
  if (!item.configured) return 'badge-off';
  return item.operational ? 'badge-ok' : 'badge-warn';
}

function statusBadgeLabel(item) {
  if (!item.configured) return 'Inativo';
  return item.operational ? 'Operacional' : 'Configurado';
}

function renderSystemStatus() {
  const container = document.getElementById('system-status-cards');
  if (!container) return;
  fetch('/api/system-status')
    .then(r => {
      if (r.status === 401) { window.location.href = '/login'; return null; }
      return r.json();
    })
    .then(data => {
      if (!data) return;
      const groups = data.modules || [];
      container.innerHTML = groups.map(g => {
        const cards = g.items.map(it => `
          <div class="card">
            <h3>${g.group}</h3>
            <p><strong>${it.name}</strong></p>
            <p>${it.detail || ''}</p>
            <span class="badge ${statusBadgeClass(it)}">${statusBadgeLabel(it)}</span>
          </div>`).join('');
        return cards;
      }).join('');
    })
    .catch(() => {
      container.innerHTML = '<div class="card"><p>Falha ao carregar status</p></div>';
    });
}

async function renderOverview() {
  let payload;
  try {
    payload = await fetchData('/api/dashboard');
  } catch (e) { return; }
  const cameras = payload.cameras || [];
  const events = payload.events || [];
  const zones = payload.zones || [];
  const n0events = payload.n0_events || [];
  const n0ByCamera = countEventsByCamera(n0events);
  const summaryCards = document.getElementById('summary-cards');
  const lastEvent = events.length > 0 ? events[0] : null;
  const lastEventTime = lastEvent ? new Date(lastEvent.timestamp).toLocaleString() : 'Nenhum evento';
  summaryCards.innerHTML = [
    createSummaryCard('Câmeras conectadas', cameras.length, 'Fontes ativas de vídeo'),
    createSummaryCard('Zonas cadastradas', zones.length, 'Classificações de alerta'),
    createSummaryCard('Eventos recentes', events.length, 'Últimos 100 eventos carregados'),
    createSummaryCard('Último evento', lastEvent ? lastEvent.event_type : 'Nenhum', lastEventTime),
  ].join('');
  const lastEventMap = buildLastEventMap(events);
  const sortedCameras = sortCamerasByLastEvent(cameras, lastEventMap);
  const cameraTiles = document.getElementById('camera-tiles');
  const workerStatus = payload.worker_status || null;
  if (!cameraTiles.dataset.rendered) {
    if (sortedCameras.length > 0) {
      cameraTiles.dataset.rendered = '1';
      renderCameraTiles(sortedCameras, workerStatus, lastEventMap, n0ByCamera);
    }
  } else {
    updateOfflineSection(sortedCameras, workerStatus, lastEventMap, n0ByCamera);
  }
  updateVisibleSnapshots(sortedCameras);
}

export function initSection() {
  setupOfflineToggle();
  setupHoverFreshSnapshots();
  const addBtn = document.getElementById('empty-add-camera');
  if (addBtn) addBtn.addEventListener('click', () => loadSection('cameras'));
  renderOverview();
  renderSystemStatus();
  _overviewTimer = setInterval(renderOverview, 5000);
  _statusTimer = setInterval(renderSystemStatus, 15000);
}

export function teardownSection() {
  if (_overviewTimer) { clearInterval(_overviewTimer); _overviewTimer = null; }
  if (_statusTimer) { clearInterval(_statusTimer); _statusTimer = null; }
}

// Expõe no window para onclick/onload inline dos cards de câmera
window.retrySnapshot = retrySnapshot;
window.onSnapshotLoad = onSnapshotLoad;
window.onSnapshotError = onSnapshotError;
