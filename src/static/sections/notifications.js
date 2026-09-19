// notifications.js — seção "Notificações"
import { fetchData, escapeHtml, showMenuMessage, invalidateCache } from '../shared.js';

async function renderNotifications() {
  const body = document.getElementById('notifications-table-body');
  if (!body) return;
  let data;
  try {
    data = await fetchData('/api/notifications');
  } catch (e) {
    body.innerHTML = '<tr><td colspan="99">Falha ao carregar configuração.</td></tr>';
    return;
  }

  const headerRow = document.getElementById('notif-header-row');
  if (headerRow) {
    headerRow.insertAdjacentHTML('beforeend', data.channels.map(c => `<th>${c.label}</th>`).join(''));
  }

  const events = data.events.filter(e => !e.legacy);
  body.innerHTML = events.map(event => {
    const cells = data.channels.map(channel => {
      const enabled = !!(data.routing[channel.key] && data.routing[channel.key][event.key]);
      return `
        <td class="notif-toggle-cell">
          <label class="switch">
            <input type="checkbox" data-channel="${channel.key}" data-event="${event.key}" ${enabled ? 'checked' : ''} />
            <span class="slider"></span>
          </label>
        </td>
      `;
    }).join('');
    const categoryLabel = event.category === 'alerta' ? 'Alerta' : 'Info';
    return `
      <tr>
        <td>${escapeHtml(event.label)}</td>
        <td><span class="badge ${event.category === 'alerta' ? 'badge-alert' : 'badge-info'}">${categoryLabel}</span></td>
        ${cells}
      </tr>
    `;
  }).join('');

  body.querySelectorAll('input[type="checkbox"]').forEach(input => {
    input.addEventListener('change', async () => {
      const payload = {
        channel: input.dataset.channel,
        event_type: input.dataset.event,
        enabled: input.checked,
      };
      const res = await fetch('/api/notifications/routing', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        input.checked = !input.checked;
        showMenuMessage('Falha ao salvar configuração.', 'camera-form-message');
      } else {
        invalidateCache('/api/notifications');
      }
    });
  });
}

export function initSection() {
  renderNotifications();
}

export function teardownSection() {
  // listeners recriados a cada initSection
}
