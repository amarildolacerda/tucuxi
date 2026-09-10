// events.js — seção "Eventos"
import { timeAgo, escapeHtml, fetchData, fetchCached, invalidateCache } from '../shared.js';

const thumbCache = {};
const THUMB_CACHE_TTL_MS = 30000;
const EVENT_FILTERS_KEY = 'secur.eventFilters';

let lastEvents = [];
let lastAlertTypes = new Set();
let _eventsTimer = null;

function _pickThumb(items, eventTs) {
  if (!items || !items.length) return null;
  let best = null, bestDiff = Infinity;
  items.forEach(item => {
    const diff = Math.abs(new Date(item.timestamp).getTime() - new Date(eventTs).getTime());
    if (diff < bestDiff) { bestDiff = diff; best = item; }
  });
  return best ? best.url : null;
}
function getCameraThumb(cameraId, eventTs) {
  if (!cameraId) return Promise.resolve(null);
  const cached = thumbCache[cameraId];
  if (cached && (Date.now() - cached.ts) < THUMB_CACHE_TTL_MS) {
    return cached.promise.then(items => _pickThumb(items, eventTs));
  }
  const promise = fetch(`/camera/${cameraId}/thumbnails`).then(r => r.ok ? r.json() : []).catch(() => []);
  thumbCache[cameraId] = { ts: Date.now(), promise };
  return promise.then(items => _pickThumb(items, eventTs));
}

function createEventCard(event, thumbUrl, alertTypes = new Set()) {
  const isAlert = alertTypes.has(event.event_type);
  const badge = isAlert
    ? '<span class="badge badge-alert">alerta</span>'
    : '<span class="badge badge-info">info</span>';
  const thumbHtml = thumbUrl
    ? `<img class="event-thumb" src="${thumbUrl}" alt="thumbnail" loading="lazy" />`
    : '<div class="event-thumb event-thumb-empty">&#x1F4F7;</div>';
  return `
    <div class="card event-card">
      ${thumbHtml}
      <div class="event-card-body">
        <div class="event-card-header">
          <span class="event-type">${event.event_type} ${badge}</span>
          <span class="event-time" data-ts="${new Date(event.timestamp).toISOString()}">${timeAgo(event.timestamp)}</span>
        </div>
        <p class="event-meta">Câmera ${event.camera_id || '-'}${event.zone ? ' · ' + event.zone : ''}</p>
        ${event.details ? `<p class="event-details">${event.details}</p>` : ''}
      </div>
    </div>
  `;
}

function readFilterState() {
  const url = new URLSearchParams(window.location.search);
  const state = {
    camera: url.get('camera') || '',
    zone: url.get('zone') || '',
    type: url.get('type') || '',
    level: url.get('level') || '',
    since: url.get('since') || '1',
    alerts: url.get('alerts') === '1',
    retained: url.get('retained') === '1',
  };
  const hasUrlFilters = url.has('camera') || url.has('zone') || url.has('type') || url.has('level') || url.has('since') || url.has('alerts') || url.has('retained');
  if (hasUrlFilters) return state;
  try {
    const saved = JSON.parse(localStorage.getItem(EVENT_FILTERS_KEY) || 'null');
    if (saved) return { camera: '', zone: '', type: '', level: '', since: '', alerts: false, retained: false, ...saved };
  } catch (e) { /* ignore */ }
  return state;
}

function saveFilterState(state) {
  try {
    localStorage.setItem(EVENT_FILTERS_KEY, JSON.stringify(state));
  } catch (e) { /* ignore */ }
}

function syncUrl(state) {
  const url = new URLSearchParams();
  if (state.camera) url.set('camera', state.camera);
  if (state.zone) url.set('zone', state.zone);
  if (state.type) url.set('type', state.type);
  if (state.level) url.set('level', state.level);
  if (state.since) url.set('since', state.since);
  if (state.alerts) url.set('alerts', '1');
  if (state.retained) url.set('retained', '1');
  const qs = url.toString();
  history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
}

function applyEventFilters(events, alertTypes) {
  const state = readFilterState();
  const sinceHours = Number(state.since) || 0;
  const cutoff = sinceHours ? Date.now() - sinceHours * 3600 * 1000 : null;
  return events.filter(e => {
    if (state.camera && String(e.camera_id) !== state.camera) return false;
    if (state.zone && (e.zone || '') !== state.zone) return false;
    if (state.type && e.event_type !== state.type) return false;
    if (state.level && Number(e.level) !== Number(state.level)) return false;
    if (cutoff && new Date(e.timestamp).getTime() < cutoff) return false;
    if (state.alerts && !alertTypes.has(e.event_type)) return false;
    if (state.retained && !e.retained) return false;
    return true;
  });
}

function populateFilterOptions(events) {
  const cameraSelect = document.getElementById('filter-camera');
  const zoneSelect = document.getElementById('filter-zone');
  const typeSelect = document.getElementById('filter-type');
  const cameras = [...new Set(events.map(e => String(e.camera_id)))].sort();
  const zones = [...new Set(events.map(e => e.zone).filter(Boolean))].sort();
  const types = [...new Set(events.map(e => e.event_type))].sort();
  const state = readFilterState();

  if (cameraSelect && !cameraSelect.dataset.populated) {
    cameraSelect.dataset.populated = '1';
    cameras.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c;
      opt.textContent = `Câmera ${c}`;
      if (c === state.camera) opt.selected = true;
      cameraSelect.appendChild(opt);
    });
    zones.forEach(z => {
      const opt = document.createElement('option');
      opt.value = z;
      opt.textContent = z;
      if (z === state.zone) opt.selected = true;
      zoneSelect.appendChild(opt);
    });
    types.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      if (t === state.type) opt.selected = true;
      typeSelect.appendChild(opt);
    });
  }
  const sinceSelect = document.getElementById('filter-since');
  if (sinceSelect) sinceSelect.value = state.since;
  const levelSelect = document.getElementById('filter-level');
  if (levelSelect) levelSelect.value = state.level;
  const alertsCheck = document.getElementById('filter-alerts');
  if (alertsCheck) alertsCheck.checked = state.alerts;
  const retainedCheck = document.getElementById('filter-retained');
  if (retainedCheck) retainedCheck.checked = state.retained;
}

function renderEventCards(events, alertTypes) {
  const grid = document.getElementById('events-grid');
  const empty = document.getElementById('events-empty');
  if (!grid) return;

  const filtered = applyEventFilters(events, alertTypes);
  if (!filtered.length) {
    grid.innerHTML = '';
    if (empty) empty.classList.remove('hidden-panel');
    return;
  }
  if (empty) empty.classList.add('hidden-panel');

  grid.innerHTML = '';

  filtered.forEach((event) => {
    const card = document.createElement('div');
    const lvl = event.level != null ? Number(event.level) : 0;
    let cardClass = 'card event-card';
    if (lvl === 3) cardClass += ' event-card-n3';
    if (lvl === 4) cardClass += ' event-card-n4';
    card.className = cardClass;
    card.dataset.eventId = event.id;
    card.dataset.timestamp = event.timestamp;
    card.dataset.eventType = event.event_type || '';
    card.dataset.level = lvl;
    card.dataset.disposition = event.disposition || '';
    card.dataset.dropped = event.dropped ? '1' : '0';
    card.dataset.cameraId = event.camera_id || '';
    card.dataset.cameraName = event.camera_name || event.camera_id || '';
    card.dataset.zone = event.zone || '';
    card.dataset.details = event.details || '';
    card.dataset.retained = event.retained ? '1' : '0';
    const thumb = document.createElement('div');
    thumb.className = 'event-thumb event-thumb-empty';
    thumb.style.cursor = 'pointer';
    thumb.innerHTML = '&#x1F4F7;';
    card.appendChild(thumb);
    const body = document.createElement('div');
    body.className = 'event-card-body';
    const lvlLabel = ['N0', 'N1', 'N2', 'N3', 'N4'][lvl] || ('N' + lvl);
    const droppedBadge = event.dropped ? '<span class="badge badge-off">descartado N1</span>' : '';
    const retainedBadge = event.retained ? '<span class="badge badge-ok">retido</span>' : '';
    const levelBadge = `<span class="badge badge-info">${lvlLabel}</span>`;
    body.innerHTML = `
      <div class="event-card-header">
        <span class="event-type">${event.event_type} ${alertTypes.has(event.event_type) ? '<span class="badge badge-alert">alerta</span>' : '<span class="badge badge-info">info</span>'} ${levelBadge} ${droppedBadge} ${retainedBadge}</span>
        <span class="event-time" data-ts="${new Date(event.timestamp).toISOString()}">${timeAgo(event.timestamp)}</span>
        <label class="retain-checkbox" title="Marcar para não apagar no prune">
          <input type="checkbox" ${event.retained ? 'checked' : ''} data-event-id="${event.id}">
          <span class="checkbox-label">Reter</span>
        </label>
      </div>
      <p class="event-meta">Câmera ${event.camera_id || '-'}${event.zone ? ' · ' + event.zone : ''}</p>
      ${event.details ? `<p class="event-details">${event.details}</p>` : ''}
    `;
    card.appendChild(body);
    grid.appendChild(card);
    const thumbUrl = event.thumbnail_url || null;
    if (thumbUrl) {
      const img = document.createElement('img');
      img.className = 'event-thumb';
      img.src = thumbUrl;
      img.alt = 'thumbnail';
      img.loading = 'lazy';
      img.style.cursor = 'zoom-in';
      thumb.replaceWith(img);
    } else {
      getCameraThumb(event.camera_id, event.timestamp).then(url => {
        if (url) {
          const img = document.createElement('img');
          img.className = 'event-thumb';
          img.src = url;
          img.alt = 'thumbnail';
          img.loading = 'lazy';
          img.style.cursor = 'zoom-in';
          thumb.replaceWith(img);
        }
      });
    }
  });

  if (!window._eventTimeTimer) {
    window._eventTimeTimer = setInterval(() => {
      document.querySelectorAll('#events-grid .event-time[data-ts]').forEach(el => {
        el.textContent = timeAgo(el.dataset.ts);
      });
    }, 30000);
  }
}

async function renderEvents(events) {
  let alertTypes = new Set();
  try {
    const notif = await fetchCached('/api/notifications');
    alertTypes = new Set((notif.events || [])
      .filter(e => e.category === 'alerta')
      .map(e => e.key));
  } catch (e) { /* sem categorias: "só alertas" vira no-op */ }
  populateFilterOptions(events);
  renderEventCards(events, alertTypes);
  return alertTypes;
}

function setupEventFilters() {
  const ids = ['filter-camera', 'filter-zone', 'filter-type', 'filter-level', 'filter-since', 'filter-alerts', 'filter-retained'];
  ids.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => {
      const state = readFilterState();
      state.camera = document.getElementById('filter-camera').value;
      state.zone = document.getElementById('filter-zone').value;
      state.type = document.getElementById('filter-type').value;
      state.level = document.getElementById('filter-level').value;
      state.since = document.getElementById('filter-since').value;
      state.alerts = document.getElementById('filter-alerts').checked;
      state.retained = document.getElementById('filter-retained').checked;
      saveFilterState(state);
      syncUrl(state);
      renderEventCards(lastEvents, lastAlertTypes);
    });
  });

  const clearButtons = ['filter-clear', 'events-clear-filters'];
  clearButtons.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', () => {
      const camera = document.getElementById('filter-camera');
      const zone = document.getElementById('filter-zone');
      const type = document.getElementById('filter-type');
      const level = document.getElementById('filter-level');
      const since = document.getElementById('filter-since');
      const alerts = document.getElementById('filter-alerts');
      const retained = document.getElementById('filter-retained');
      if (camera) camera.value = '';
      if (zone) zone.value = '';
      if (type) type.value = '';
      if (level) level.value = '';
      if (since) since.value = '';
      if (alerts) alerts.checked = false;
      if (retained) retained.checked = false;
      saveFilterState({ camera: '', zone: '', type: '', level: '', since: '', alerts: false, retained: false });
      syncUrl({ camera: '', zone: '', type: '', level: '', since: '', alerts: false, retained: false });
      renderEventCards(lastEvents, lastAlertTypes);
    });
  });
}

function setupEventCardThumbPreview() {
  const grid = document.getElementById('events-grid');
  if (!grid || grid._thumbPreviewWired) return;
  grid._thumbPreviewWired = true;
  grid.addEventListener('click', (e) => {
    const thumb = e.target.closest('.event-thumb');
    if (!thumb || !thumb.tagName || thumb.tagName.toLowerCase() !== 'img') return;
    const card = thumb.closest('.event-card');
    if (!card) return;
    openEventThumbDialog(card, thumb.src);
  });

  grid.addEventListener('change', async (e) => {
    const checkbox = e.target.closest('.retain-checkbox input[type="checkbox"]');
    if (!checkbox) return;
    const eventId = checkbox.dataset.eventId;
    if (!eventId) return;
    const retain = checkbox.checked;
    try {
      const res = await fetch(`/api/events/${eventId}/retain`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ retain })
      });
      const data = await res.json();
      if (!res.ok) {
        checkbox.checked = !retain;
        alert(data.error || 'Erro ao atualizar');
      } else {
        const card = checkbox.closest('.event-card');
        if (card) {
          card.dataset.retained = retain ? '1' : '0';
          const badge = card.querySelector('.badge-ok');
          if (retain && !badge) {
            const header = card.querySelector('.event-card-header .event-type');
            if (header) {
              const badgeEl = document.createElement('span');
              badgeEl.className = 'badge badge-ok';
              badgeEl.textContent = 'retido';
              header.appendChild(badgeEl);
            }
          } else if (!retain && badge) {
            badge.remove();
          }
        }
      }
    } catch (e) {
      checkbox.checked = !retain;
      alert('Erro ao atualizar');
    }
  });
}

function openEventThumbDialog(card, imgSrc) {
  const meta = {
    camera: card.dataset.cameraName || card.dataset.cameraId || '',
    zone: card.dataset.zone || '',
    details: card.dataset.details || '',
  };
  openThumbDetail(
    imgSrc,
    card.dataset.timestamp || new Date().toISOString(),
    card.dataset.eventType || '',
    card.dataset.level != null ? Number(card.dataset.level) : null,
    card.dataset.disposition || '',
    card.dataset.dropped === '1',
    meta,
  );
}

async function loadEvents() {
  const state = readFilterState();
  const params = new URLSearchParams();
  if (state.level) params.set('level', state.level);
  if (state.retained) params.set('retained', '1');
  try {
    lastEvents = await fetchData('/events?' + params.toString());
  } catch (e) { return; }
  lastAlertTypes = await renderEvents(lastEvents);
}

export function initSection() {
  setupEventFilters();
  setupEventCardThumbPreview();
  loadEvents();
  _eventsTimer = setInterval(loadEvents, 5000);
}

export function teardownSection() {
  if (_eventsTimer) { clearInterval(_eventsTimer); _eventsTimer = null; }
}
