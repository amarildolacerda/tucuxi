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

const LEVEL_LABELS = { default: 'Padrão', low: 'Baixa', medium: 'Média', high: 'Alta' };
const LEVEL_DESCS = {
  default: 'Usa a configuração geral do sistema (.env).',
  low: 'Menos alertas. Ideal para áreas movimentadas.',
  medium: 'Equilibrado. Padrão para uso geral.',
  high: 'Mais alertas. Ideal para perímetros críticos.',
};

async function renderSensitivityConfig() {
  const container = document.getElementById('sensitivity-config');
  if (!container) return;
  try {
    const resp = await fetch('/api/cameras');
    const list = await resp.json();
    if (!list.length) {
      container.textContent = 'Nenhuma câmera configurada.';
      return;
    }
    container.innerHTML = '';
    const section = document.createElement('div');
    section.className = 'sensitivity-section';

    for (const cam of list) {
      const camDiv = document.createElement('div');
      camDiv.className = 'config-module-group sensitivity-camera-group';

      const h4 = document.createElement('h4');
      h4.textContent = cam.name;
      camDiv.appendChild(h4);

      const currentResp = await fetch(`/api/cameras/${cam.id}/sensitivity`);
      const current = await currentResp.json();

      const selector = document.createElement('div');
      selector.className = 'sensitivity-selector';
      for (const [val, label] of Object.entries(LEVEL_LABELS)) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `button-mini sensitivity-btn${current.level === val ? ' active' : ''}`;
        btn.dataset.sensitivityLevel = val;
        btn.textContent = label;
        btn.addEventListener('click', () => selectLevel(cam.id, val, camDiv));
        selector.appendChild(btn);
      }
      camDiv.appendChild(selector);

      const desc = document.createElement('p');
      desc.className = 'sensitivity-desc';
      desc.textContent = LEVEL_DESCS[current.level] || '';
      camDiv.appendChild(desc);

      section.appendChild(camDiv);
    }

    container.appendChild(section);
  } catch (e) {
    container.textContent = 'Falha ao carregar sensibilidade.';
  }
}

async function selectLevel(cameraId, level, camDiv) {
  const desc = camDiv.querySelector('.sensitivity-desc');
  if (desc) desc.textContent = LEVEL_DESCS[level] || '';
  const resp = await fetch(`/api/cameras/${cameraId}/sensitivity`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    if (desc) desc.textContent = `Erro: ${err.error || 'falha ao salvar'}`;
  }
}

export function initSection() {
  setupSettings();
  renderSettings();
}

export function teardownSection() {
  // listeners recriados a cada initSection
}
