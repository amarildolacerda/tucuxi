// core.js — núcleo do dashboard (shell, lazy-load, navegação, sessão)
// Carregado como ES module após shared.js. CameraFault é global (camera_fault.js).
import { fetchData, formatUptime } from './shared.js';

const SECTION_MODULES = {
  overview: () => import('./sections/overview.js'),
  events: () => import('./sections/events.js'),
  cameras: () => import('./sections/cameras.js'),
  zones: () => import('./sections/zones.js'),
  identities: () => import('./sections/identities.js'),
  users: () => import('./sections/users.js'),
  permissions: () => import('./sections/permissions.js'),
  audit: () => import('./sections/audit.js'),
  notifications: () => import('./sections/notifications.js'),
  settings: () => import('./sections/settings.js'),
  retention: () => import('./sections/retention.js'),
};

const _loadedSections = new Set();
let _currentSection = null;
let _currentTeardown = null;
const _bootTime = Date.now();

async function loadSection(name) {
  if (!SECTION_MODULES[name]) { console.warn('Seção desconhecida:', name); return; }
  // teardown da seção anterior
  if (_currentTeardown) { try { _currentTeardown(); } catch (e) { console.error(e); } _currentTeardown = null; }

  const main = document.getElementById('main-page');
  if (!main) return;
  const resp = await fetch(`/section/${name}`);
  if (resp.status === 401) { window.location.href = '/login'; return; }
  if (!resp.ok) { main.innerHTML = `<div class="empty-state"><p>Erro ao carregar seção.</p></div>`; return; }
  main.innerHTML = await resp.text();

  // marca nav ativo
  document.querySelectorAll('.nav-link[data-section], .nav-sublink[data-section]').forEach(l => {
    l.classList.toggle('active', l.dataset.section === name);
  });

  if (!_loadedSections.has(name)) {
    await SECTION_MODULES[name]();
    _loadedSections.add(name);
  }
  const mod = await SECTION_MODULES[name]();
  if (typeof mod.initSection === 'function') mod.initSection();
  if (typeof mod.teardownSection === 'function') _currentTeardown = mod.teardownSection;
  _currentSection = name;
}

function setupSidebarNavigation() {
  document.querySelectorAll('.nav-link[data-section], .nav-sublink[data-section]').forEach(link => {
    link.addEventListener('click', () => loadSection(link.dataset.section));
  });
  const sysStatus = document.getElementById('nav-system-status');
  if (sysStatus) {
    sysStatus.addEventListener('click', (e) => {
      e.preventDefault();
      loadSection('overview');
    });
  }
}

async function renderStatusFooter() {
  let status = null;
  try { status = await fetchData('/status'); } catch (e) { status = null; }
  if (!status) {
    const health = document.getElementById('status-health');
    if (health) { health.textContent = 'Status: indisponível'; health.className = 'status-bad'; }
    return;
  }
  const health = document.getElementById('status-health');
  const cameras = document.getElementById('status-cameras');
  const workers = document.getElementById('status-workers');
  const recent = document.getElementById('status-recent');
  if (health) { health.textContent = `Status: ${status.status || 'ok'}`; health.className = status.status === 'ok' ? 'status-good' : 'status-bad'; }
  if (cameras) cameras.textContent = `Câmeras: ${status.camera_count ?? '—'}`;
  if (workers) workers.textContent = `Workers: ${status.active_workers ?? '—'}`;
  if (recent) recent.textContent = `Eventos recentes: ${status.recent_events ?? '—'}`;
  const uptime = document.getElementById('status-uptime');
  if (uptime) uptime.textContent = `Uptime: ${formatUptime(Date.now() - _bootTime)}`;
  const version = document.getElementById('status-version');
  if (version) version.textContent = `Versão: ${status.version ?? '—'}`;
}

function startFooter() {
  renderStatusFooter();
  setInterval(renderStatusFooter, 5000);
}

async function bootDashboard() {
  const meResp = await fetch('/api/auth/me');
  if (meResp.status === 401) { window.location.href = '/login'; return; }
  const data = await meResp.json();
  const bar = document.getElementById('user-bar');
  const nameEl = document.getElementById('user-bar-name');
  if (bar && nameEl && data.type === 'session' && data.user) {
    nameEl.textContent = data.user.username + ' (' + data.user.role + ')';
    bar.style.display = 'flex';
  }
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async () => {
      await fetch('/api/auth/logout', { method: 'POST' });
      window.location.href = '/login';
    });
  }
  setupSidebarNavigation();
  startFooter();
  await loadSection('overview'); // única seção carregada no boot

  // Check for updates and show banner
  fetch('/api/system/update-check')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (data && data.update_available) {
        const banner = document.createElement('div');
        banner.className = 'update-banner';
        banner.innerHTML = `Nova versão disponível: <strong>${data.latest_version}</strong> — <a href="/?section=settings">Atualizar</a>`;
        document.body.prepend(banner);
      }
    })
    .catch(() => {}); // Silent fail for update check
}

window.addEventListener('DOMContentLoaded', bootDashboard);
export { loadSection, setupSidebarNavigation, bootDashboard };
