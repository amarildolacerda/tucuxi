// settings.js — seção "Configurações"
import { fetchData, showMenuMessage, invalidateCache } from '../shared.js';

async function renderSettings() {
  const toggle = document.getElementById('privacy-mode-toggle');
  if (!toggle) return;
  try {
    const data = await fetchData('/api/settings');
    toggle.checked = !!data.privacy_mode;
  } catch (e) { /* offline: mantém estado atual */ }
  renderSettingsConfig();
  renderSensitivityConfig();
}

function appendConfigValue(dd, v) {
  const text = Array.isArray(v) ? v.join(', ') : String(v);
  dd.title = text;
  if (typeof v === 'boolean') {
    const badge = document.createElement('span');
    badge.className = 'config-value-badge ' + (v ? 'is-on' : 'is-off');
    badge.textContent = v ? 'Ativado' : 'Desativado';
    dd.appendChild(badge);
  } else if (typeof v === 'number') {
    const tag = document.createElement('span');
    tag.className = 'config-value-num';
    tag.textContent = text;
    dd.appendChild(tag);
  } else {
    const span = document.createElement('span');
    span.className = 'config-value-text';
    span.textContent = text;
    dd.appendChild(span);
  }
}

function renderSettingsConfig() {
  const container = document.getElementById('settings-config');
  if (!container) return;
  fetch('/api/config')
    .then(r => {
      if (r.status === 401) { window.location.href = '/login'; return null; }
      return r.json();
    })
    .then(cfg => {
      if (!cfg) return;
      container.innerHTML = '';
      const section = document.createElement('div');
      section.className = 'settings-config-sections';

      const groups = [
        { title: 'Movimento (N1)', data: cfg.motion, keys: ['min_area_px', 'persist_frames', 'rain_spatial_ratio', 'frame_wait_seconds', 'worker_healthy_timeout_seconds'], labels: { min_area_px: 'Área mínima (px)', persist_frames: 'Persistência (frames)', rain_spatial_ratio: 'Filtro chuva (%)', frame_wait_seconds: 'Espera frame (s)', worker_healthy_timeout_seconds: 'Timeout worker saudável (s)' } },
        { title: 'Alertas', data: cfg.alerts, keys: ['no_motion_alert_seconds', 'cooldown_seconds'], labels: { no_motion_alert_seconds: 'Sem movimento alerta (s)', cooldown_seconds: 'Cooldown padrão (s)' } },
        { title: 'Detector (YOLO)', data: cfg.detector, keys: ['model_path', 'confidence', 'iou'], labels: { model_path: 'Modelo', confidence: 'Confiança', iou: 'IoU' } },
        { title: 'Identidade', data: cfg.identity, keys: ['enabled', 'face_model_path', 'match_threshold'], labels: { enabled: 'Habilitado', face_model_path: 'Modelo face', match_threshold: 'Threshold match' } },
        { title: 'Thumbnails', data: cfg.thumbnails, keys: ['interval_seconds', 'diff_threshold', 'history_size'], labels: { interval_seconds: 'Intervalo (s)', diff_threshold: 'Threshold diff', history_size: 'Histórico' } },
        { title: 'Clips', data: cfg.clips, keys: ['pre_seconds', 'post_seconds', 'fps', 'history_size'], labels: { pre_seconds: 'Pré (s)', post_seconds: 'Pós (s)', fps: 'FPS', history_size: 'Histórico' } },
        { title: 'Tracking', data: cfg.tracking, keys: ['iou_threshold', 'max_age_seconds'], labels: { iou_threshold: 'IoU threshold', max_age_seconds: 'Max age (s)' } },
        { title: 'Comportamento', data: cfg.behavior, keys: ['loitering_seconds', 'loitering_max_distance', 'fall_aspect_ratio'], labels: { loitering_seconds: 'Loitering (s)', loitering_max_distance: 'Loitering dist. max', fall_aspect_ratio: 'Fall aspect ratio' } },
      ];

      groups.forEach(g => {
        if (!g.data) return;
        const groupDiv = document.createElement('div');
        groupDiv.className = 'config-module-group';
        const h4 = document.createElement('h4');
        h4.textContent = g.title;
        groupDiv.appendChild(h4);
        const dl = document.createElement('dl');
        dl.className = 'settings-config-list';
        g.keys.forEach(k => {
          const v = g.data[k];
          if (v === undefined || v === null) return;
          const dt = document.createElement('dt');
          dt.textContent = g.labels[k] || k;
          const dd = document.createElement('dd');
          appendConfigValue(dd, v);
          dl.appendChild(dt);
          dl.appendChild(dd);
        });
        if (dl.children.length) {
          groupDiv.appendChild(dl);
          const count = document.createElement('span');
          count.className = 'config-group-count';
          count.textContent = String(dl.children.length / 2);
          h4.appendChild(count);
        }
        if (groupDiv.children.length > 1) section.appendChild(groupDiv);
      });

      if (cfg.privacy_mode != null) {
        const groupDiv = document.createElement('div');
        groupDiv.className = 'config-module-group';
        const h4 = document.createElement('h4');
        h4.textContent = 'Privacidade';
        groupDiv.appendChild(h4);
        const dl = document.createElement('dl');
        dl.className = 'settings-config-list';
        const dt = document.createElement('dt');
        dt.textContent = 'Modo privacidade';
        const dd = document.createElement('dd');
        appendConfigValue(dd, cfg.privacy_mode);
        dl.appendChild(dt);
        dl.appendChild(dd);
        groupDiv.appendChild(dl);
        const count = document.createElement('span');
        count.className = 'config-group-count';
        count.textContent = '1';
        h4.appendChild(count);
        section.appendChild(groupDiv);
      }

      if (!section.children.length) {
        container.textContent = 'Sem informações de configuração disponíveis.';
        return;
      }
      container.appendChild(section);
    })
    .catch(() => {
      container.textContent = 'Falha ao carregar configurações.';
    });
}

function setupSettings() {
  const configToggle = document.getElementById('settings-config-toggle');
  if (configToggle) {
    configToggle.addEventListener('click', () => {
      const panel = document.getElementById('settings-config');
      if (!panel) return;
      panel.classList.toggle('hidden-panel');
      const open = !panel.classList.contains('hidden-panel');
      configToggle.classList.toggle('is-open', open);
      configToggle.setAttribute('aria-expanded', String(open));
      if (open) {
        panel.classList.remove('animate-in');
        void panel.offsetWidth;
        panel.classList.add('animate-in');
      }
    });
  }
  const toggle = document.getElementById('privacy-mode-toggle');
  if (!toggle) return;
  toggle.addEventListener('change', async () => {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ privacy_mode: toggle.checked }),
    });
    if (!res.ok) {
      toggle.checked = !toggle.checked;
      showMenuMessage('Falha ao salvar configuração.', 'camera-form-message');
    } else {
      invalidateCache('/api/settings');
    }
  });
}

const LEVEL_LABELS = { low: 'Baixa', medium: 'Média', high: 'Alta', custom: 'Personalizado' };
const LEVEL_DESCS = {
  low: 'Menos alertas. Ideal para áreas movimentadas.',
  medium: 'Equilibrado. Padrão para uso geral.',
  high: 'Mais alertas. Ideal para perímetros críticos.',
  custom: 'Ajuste manual de cada parâmetro.',
};
const SLIDER_DEFS = [
  { key: 'motion_min_area', label: 'Área mínima de movimento', min: 1000, max: 15000, step: 500, unit: 'px' },
  { key: 'motion_persist_frames', label: 'Frames de persistência', min: 1, max: 8, step: 1, unit: 'frames' },
  { key: 'detector_confidence', label: 'Confiança da IA', min: 0.10, max: 0.80, step: 0.05, unit: '' },
  { key: 'detector_iou', label: 'NMS (sobreposição)', min: 0.20, max: 0.70, step: 0.05, unit: '' },
  { key: 'track_iou_threshold', label: 'Limiar de rastreamento', min: 0.10, max: 0.60, step: 0.05, unit: '' },
];

async function renderSensitivityConfig() {
  const container = document.getElementById('sensitivity-config');
  if (!container) return;
  try {
    const [presets, camerasResp] = await Promise.all([
      fetch('/api/sensitivity/presets').then(r => r.json()),
      fetch('/api/cameras').then(r => r.json()),
    ]);
    const cameras = camerasResp.cameras || camerasResp;
    if (!cameras.length) {
      container.textContent = 'Nenhuma câmera configurada.';
      return;
    }
    container.innerHTML = '';
    const section = document.createElement('div');
    section.className = 'sensitivity-section';

    for (const cam of cameras) {
      const camDiv = document.createElement('div');
      camDiv.className = 'config-module-group sensitivity-camera-group';

      const h4 = document.createElement('h4');
      h4.textContent = cam.name;
      camDiv.appendChild(h4);

      const currentResp = await fetch(`/api/cameras/${cam.id}/sensitivity`);
      const current = await currentResp.json();

      // Selector buttons
      const selector = document.createElement('div');
      selector.className = 'sensitivity-selector';
      for (const [val, label] of Object.entries(LEVEL_LABELS)) {
        const btn = document.createElement('button');
        btn.className = 'button-mini sensitivity-btn' + (current.level === val ? ' active' : '');
        btn.textContent = label;
        btn.title = LEVEL_DESCS[val];
        btn.addEventListener('click', () => selectLevel(cam.id, val, camDiv));
        selector.appendChild(btn);
      }
      camDiv.appendChild(selector);

      // Description
      const desc = document.createElement('p');
      desc.className = 'sensitivity-desc';
      desc.textContent = LEVEL_DESCS[current.level] || '';
      camDiv.appendChild(desc);

      // Custom sliders (hidden by default)
      const slidersDiv = document.createElement('div');
      slidersDiv.className = 'sensitivity-sliders' + (current.level === 'custom' ? '' : ' hidden');
      slidersDiv.id = `sensitivity-sliders-${cam.id}`;

      const params = current.effective_params;
      for (const sd of SLIDER_DEFS) {
        const row = document.createElement('div');
        row.className = 'slider-row';
        const label = document.createElement('label');
        label.textContent = sd.label;
        const input = document.createElement('input');
        input.type = 'range';
        input.min = sd.min;
        input.max = sd.max;
        input.step = sd.step;
        input.value = params[sd.key];
        input.dataset.key = sd.key;
        const valueSpan = document.createElement('span');
        valueSpan.className = 'slider-value';
        valueSpan.textContent = params[sd.key] + (sd.unit ? ' ' + sd.unit : '');
        input.addEventListener('input', () => {
          valueSpan.textContent = input.value + (sd.unit ? ' ' + sd.unit : '');
        });
        row.appendChild(label);
        row.appendChild(input);
        row.appendChild(valueSpan);
        slidersDiv.appendChild(row);
      }

      // Save custom button
      const saveBtn = document.createElement('button');
      saveBtn.className = 'button-primary';
      saveBtn.textContent = 'Salvar personalizado';
      saveBtn.addEventListener('click', () => saveCustom(cam.id, slidersDiv));
      slidersDiv.appendChild(saveBtn);

      camDiv.appendChild(slidersDiv);
      section.appendChild(camDiv);
    }

    container.appendChild(section);
  } catch (e) {
    container.textContent = 'Falha ao carregar sensibilidade.';
  }
}

async function selectLevel(cameraId, level, camDiv) {
  // Update active button
  camDiv.querySelectorAll('.sensitivity-btn').forEach(btn => {
    btn.classList.toggle('active', btn.textContent === LEVEL_LABELS[level]);
  });
  // Show/hide sliders
  const slidersDiv = camDiv.querySelector('.sensitivity-sliders');
  if (slidersDiv) {
    slidersDiv.classList.toggle('hidden', level !== 'custom');
    if (level !== 'custom') {
      await fetch(`/api/cameras/${cameraId}/sensitivity`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level }),
      });
    }
  }
}

async function saveCustom(cameraId, slidersDiv) {
  const params = {};
  slidersDiv.querySelectorAll('input[type="range"]').forEach(input => {
    params[input.dataset.key] = parseFloat(input.value);
  });
  const resp = await fetch(`/api/cameras/${cameraId}/sensitivity`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level: 'custom', custom_params: params }),
  });
  if (!resp.ok) {
    const err = await resp.json();
    showMenuMessage(err.error || 'Erro ao salvar', 'camera-form-message');
  } else {
    showMenuMessage('Sensibilidade salva', 'camera-form-message');
  }
}

export function initSection() {
  setupSettings();
  renderSettings();
}

export function teardownSection() {
  // listeners recriados a cada initSection
}
