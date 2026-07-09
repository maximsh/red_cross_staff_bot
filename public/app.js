/* ========================================================
   HR Tracker — Combined Application Logic (SPA Router)
   ======================================================== */

const tg = window.Telegram?.WebApp;

// State
let activeView = 'employee'; // 'employee' | 'dashboard'
let initData = '';
let currentStatus = 'offline';
let refreshInterval = null;
let isAdmin = false;

// DOM elements
const els = {
  loading: document.getElementById('loading'),
  toast: document.getElementById('toast'),
  
  // Views
  employeeView: document.getElementById('employeeView'),
  dashboardView: document.getElementById('dashboardView'),

  // Employee elements
  empName: document.getElementById('empName'),
  empDate: document.getElementById('empDate'),
  empStatusBadge: document.getElementById('empStatusBadge'),
  empStatusText: document.getElementById('empStatusText'),
  btnCheckin: document.getElementById('btnCheckin'),
  btnFieldStart: document.getElementById('btnFieldStart'),
  btnFieldEnd: document.getElementById('btnFieldEnd'),
  btnCheckout: document.getElementById('btnCheckout'),
  timeline: document.getElementById('timeline'),

  // Dashboard elements
  dashDate: document.getElementById('dashDate'),
  countOffice: document.getElementById('countOffice'),
  countField: document.getElementById('countField'),
  countOffline: document.getElementById('countOffline'),
  employeeList: document.getElementById('employeeList'),
  emptyState: document.getElementById('emptyState'),
  
  // Modal elements
  modalOverlay: document.getElementById('modalOverlay'),
  modalName: document.getElementById('modalName'),
  modalStatus: document.getElementById('modalStatus'),
  modalTimeline: document.getElementById('modalTimeline'),
  modalClose: document.getElementById('modalClose'),
  modalAdminActions: document.getElementById('modalAdminActions'),
  adminBtns: document.querySelectorAll('.admin-btn'),
  adminAliasesInput: document.getElementById('adminAliasesInput'),
  adminSaveAliasesBtn: document.getElementById('adminSaveAliasesBtn'),
};

// ===== Common API requests =====
async function apiRequest(method, endpoint, body = null) {
  const options = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Telegram-Init-Data': initData,
    },
  };

  if (body) {
    options.body = JSON.stringify(body);
  }

  const response = await fetch(endpoint, options);
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }

  return data;
}

// ===== Routing & Init =====
function init() {
  if (tg) {
    tg.ready();
    tg.expand();

    // Apply Telegram theme colors dynamically
    document.documentElement.style.setProperty('--tg-theme-bg-color', tg.themeParams.bg_color || '#1a1a2e');
    document.documentElement.style.setProperty('--tg-theme-text-color', tg.themeParams.text_color || '#eaeaea');
    document.documentElement.style.setProperty('--tg-theme-hint-color', tg.themeParams.hint_color || '#8a8a9a');
    document.documentElement.style.setProperty('--tg-theme-button-color', tg.themeParams.button_color || '#6c63ff');
    document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', tg.themeParams.secondary_bg_color || '#16213e');

    initData = tg.initData;

    // Detect start parameter (?startapp=dashboard)
    const startParam = tg.initDataUnsafe?.start_param || '';
    if (startParam === 'dashboard') {
      activeView = 'dashboard';
    }
  } else {
    // Check search query parameters if tested directly in browser
    const urlParams = new URLSearchParams(window.location.search);
    const startParam = urlParams.get('tgWebAppStartParam') || '';
    if (startParam === 'dashboard') {
      activeView = 'dashboard';
    }
    initData = 'test_mode';
  }

  // Switch to correct view container
  if (activeView === 'dashboard') {
    els.dashboardView.classList.add('active');
    initDashboard();
  } else {
    els.employeeView.classList.add('active');
    initEmployee();
  }
}

// ===== Employee View Initialization & Logic =====
function initEmployee() {
  // Set greeting name
  const user = tg?.initDataUnsafe?.user;
  if (user) {
    els.empName.textContent = `Привіт, ${user.first_name}!`;
  } else {
    els.empName.textContent = 'Привіт! (тест)';
  }

  // Set date
  const today = new Date();
  const options = { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' };
  els.empDate.textContent = today.toLocaleDateString('uk-UA', options);

  // Bind actions
  els.btnCheckin.addEventListener('click', () => sendEmployeeAction('checkin'));
  els.btnFieldStart.addEventListener('click', () => sendEmployeeAction('field-start'));
  els.btnFieldEnd.addEventListener('click', () => sendEmployeeAction('field-end'));
  els.btnCheckout.addEventListener('click', () => sendEmployeeAction('checkout'));

  // Load employee status
  loadEmployeeStatus();
}

async function loadEmployeeStatus() {
  try {
    const data = await apiRequest('GET', '/api/my-status');
    currentStatus = data.status || 'offline';
    
    // Update badge UI
    els.empStatusBadge.setAttribute('data-status', currentStatus);
    const statusMap = {
      offline: 'Не на роботі',
      in_office: 'В офісі',
      field_trip: 'На виїзді',
    };
    els.empStatusText.textContent = statusMap[currentStatus] || currentStatus;

    // Update button states
    const actions = data.validActions || ['checkin'];
    els.btnCheckin.disabled = !actions.includes('checkin');
    els.btnFieldStart.disabled = !actions.includes('field_start');
    els.btnFieldEnd.disabled = !actions.includes('field_end');
    els.btnCheckout.disabled = !actions.includes('checkout');

    // Render timeline
    renderEmployeeTimeline(data.todayEvents || []);
    hideLoading();
  } catch (err) {
    console.error('Failed to load employee status:', err);
    hideLoading();
    showToast('Помилка завантаження', 'error');
  }
}

async function sendEmployeeAction(action) {
  const btnMap = {
    'checkin': els.btnCheckin,
    'field-start': els.btnFieldStart,
    'field-end': els.btnFieldEnd,
    'checkout': els.btnCheckout,
  };
  const btn = btnMap[action];
  if (!btn || btn.disabled) return;

  if (tg?.HapticFeedback) {
    tg.HapticFeedback.impactOccurred('medium');
  }

  btn.classList.add('loading');

  try {
    const data = await apiRequest('POST', `/api/${action}`);
    currentStatus = data.status;

    // Refresh state
    await loadEmployeeStatus();

    if (tg?.HapticFeedback) {
      tg.HapticFeedback.notificationOccurred('success');
    }

    const messages = {
      'checkin': '✅ Прихід зареєстровано',
      'field-start': '🚗 Виїзд зареєстровано',
      'field-end': '↩️ Повернення зареєстровано',
      'checkout': '🏠 Вихід зареєстровано',
    };
    showToast(messages[action] || 'Готово', 'success');
  } catch (err) {
    console.error(`Action ${action} failed:`, err);
    if (tg?.HapticFeedback) {
      tg.HapticFeedback.notificationOccurred('error');
    }
    showToast(err.message || 'Помилка', 'error');
  } finally {
    btn.classList.remove('loading');
  }
}

function renderEmployeeTimeline(events) {
  if (!events || events.length === 0) {
    els.timeline.innerHTML = '<div class="timeline-empty">Подій ще немає</div>';
    return;
  }

  const eventLabels = {
    checkin: { label: 'Прийшов на роботу', icon: '🏢' },
    checkout: { label: 'Пішов додому', icon: '🏠' },
    field_start: { label: 'Виїхав', icon: '🚗' },
    field_end: { label: 'Повернувся', icon: '↩️' },
  };

  els.timeline.innerHTML = events.map((event, index) => {
    const info = eventLabels[event.event_type] || { label: event.event_type, icon: '📌' };
    return `
      <div class="timeline-item" style="animation: slideIn 0.3s ease-out ${index * 0.05}s both">
        <div class="timeline-dot ${event.event_type}">${info.icon}</div>
        <div class="timeline-info">
          <span class="timeline-label">${info.label}</span>
          <span class="timeline-time">${formatTime(event.created_at)}</span>
        </div>
      </div>
    `;
  }).join('');
}

// ===== Dashboard View Initialization & Logic =====
function initDashboard() {
  // Set date
  updateDashboardTime();

  // Modal setup
  els.modalClose.addEventListener('click', closeModal);
  els.modalOverlay.addEventListener('click', (e) => {
    if (e.target === els.modalOverlay) closeModal();
  });
  
  if (els.adminSaveAliasesBtn) {
    els.adminSaveAliasesBtn.addEventListener('click', () => {
      const targetId = parseInt(els.modalName.getAttribute('data-id'), 10);
      if (targetId) sendAdminAliases(targetId, els.adminAliasesInput.value);
    });
  }

  // Load dashboard data
  loadDashboardData();

  // Set 30s auto-refresh
  refreshInterval = setInterval(() => {
    loadDashboardData(true);
  }, 30000);
}

function updateDashboardTime() {
  const today = new Date();
  const options = { day: 'numeric', month: 'long', year: 'numeric' };
  const timeOpts = { hour: '2-digit', minute: '2-digit' };
  els.dashDate.textContent = `${today.toLocaleDateString('uk-UA', options)}, ${today.toLocaleTimeString('uk-UA', timeOpts)}`;
}

async function loadDashboardData(silent = false) {
  try {
    const data = await apiRequest('GET', '/api/statuses');
    
    // Update admin status
    isAdmin = data.summary.isAdmin;

    // Update numbers
    animateNumber(els.countOffice, data.summary.in_office);
    animateNumber(els.countField, data.summary.field_trip);
    animateNumber(els.countOffline, data.summary.offline);

    // Group employees
    const groups = {
      in_office: { title: 'В офісі', employees: [] },
      field_trip: { title: 'На виїзді', employees: [] },
      offline: { title: 'Не на роботі', employees: [] },
    };

    data.employees.forEach(emp => {
      const status = emp.status || 'offline';
      if (groups[status]) groups[status].employees.push(emp);
    });

    // Render list
    let html = '';
    let hasAny = false;

    for (const [status, group] of Object.entries(groups)) {
      if (group.employees.length === 0) continue;
      hasAny = true;

      html += `
        <div class="status-group">
          <div class="group-header">
            <div class="group-dot ${status}"></div>
            <span class="group-title">${group.title}</span>
            <span class="group-count">${group.employees.length}</span>
          </div>
          <div class="group-employees">
            ${group.employees.map((emp, i) => {
              const initials = getInitials(emp.first_name, emp.last_name);
              const avatarHtml = emp.photo_url 
                ? `<img src="${emp.photo_url}" class="employee-avatar-img" alt="${escapeHtml(emp.first_name)}" />`
                : initials;
              const timeStr = emp.last_event_at ? formatTime(emp.last_event_at) : '';
              
              const statusLabels = {
                in_office: `з ${timeStr}`,
                field_trip: `виїзд ${timeStr}`,
                offline: timeStr ? `пішов ${timeStr}` : '',
              };

              const noteHtml = emp.note ? `<div class="employee-note">${escapeHtml(emp.note)}</div>` : '';

              return `
                <div class="employee-card" data-id="${emp.telegram_id}" data-status="${status}" style="animation: slideIn 0.3s ease-out ${i * 0.04}s both">
                  <div class="employee-avatar">${avatarHtml}</div>
                  <div class="employee-info">
                    <div class="employee-name">${escapeHtml(emp.first_name)} ${escapeHtml(emp.last_name || '')}</div>
                    <div class="employee-detail">${statusLabels[status]}</div>
                    ${noteHtml}
                  </div>
                  <div class="employee-status-icon">●</div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    els.employeeList.innerHTML = html;

    // Show or hide empty state
    if (!hasAny) {
      els.emptyState.style.display = 'block';
      els.employeeList.style.display = 'none';
    } else {
      els.emptyState.style.display = 'none';
      els.employeeList.style.display = 'flex';
    }

    // Bind modal click events
    els.employeeList.querySelectorAll('.employee-card').forEach(card => {
      card.addEventListener('click', () => {
        const id = parseInt(card.getAttribute('data-id'), 10);
        openEmployeeDetail(id);
      });
    });

    updateDashboardTime();
    if (!silent) hideLoading();
  } catch (err) {
    console.error('Failed to load dashboard:', err);
    if (!silent) hideLoading();
  }
}

async function openEmployeeDetail(telegramId) {
  if (tg?.HapticFeedback) {
    tg.HapticFeedback.impactOccurred('light');
  }

  try {
    const [statusData, eventsData] = await Promise.all([
      apiRequest('GET', `/api/status/${telegramId}`),
      apiRequest('GET', `/api/today/${telegramId}`),
    ]);

    const name = `${statusData.first_name} ${statusData.last_name || ''}`.trim();
    els.modalName.textContent = name;
    els.modalName.setAttribute('data-id', telegramId);

    const statusLabels = {
      in_office: '🟢 В офісі',
      field_trip: '🟡 На виїзді',
      offline: '⚫ Не на роботі',
    };
    els.modalStatus.textContent = statusLabels[statusData.status] || statusData.status;
    els.modalStatus.className = `modal-status ${statusData.status}`;

    // Update admin actions UI
    if (isAdmin) {
      els.modalAdminActions.style.display = 'block';
      const validActions = statusData.validActions || ['checkin'];
      els.adminBtns.forEach(btn => {
        if (!btn.hasAttribute('data-action')) return;
        const actionRaw = btn.getAttribute('data-action');
        const apiAction = actionRaw.replace('-', '_');
        btn.disabled = !validActions.includes(apiAction);
        btn.onclick = () => sendAdminAction(telegramId, apiAction);
      });
      if (els.adminAliasesInput) {
        els.adminAliasesInput.value = statusData.aliases || '';
      }
    } else {
      els.modalAdminActions.style.display = 'none';
    }

    // Render timeline inside modal
    if (!eventsData.events || eventsData.events.length === 0) {
      els.modalTimeline.innerHTML = `
        <div class="modal-timeline-title">📅 Сьогодні</div>
        <div class="modal-empty">Подій за сьогодні немає</div>
      `;
    } else {
      const eventLabels = {
        checkin: { label: 'Прийшов на роботу', icon: '🏢' },
        checkout: { label: 'Пішов додому', icon: '🏠' },
        field_start: { label: 'Виїхав', icon: '🚗' },
        field_end: { label: 'Повернувся', icon: '↩️' },
      };

      const eventsHtml = eventsData.events.map(event => {
        const info = eventLabels[event.event_type] || { label: event.event_type, icon: '📌' };
        return `
          <div class="modal-event">
            <div class="modal-event-dot ${event.event_type}">${info.icon}</div>
            <div class="modal-event-info">
              <div class="modal-event-label">${info.label}</div>
              <div class="modal-event-time">${formatTime(event.created_at)}</div>
            </div>
          </div>
        `;
      }).join('');

      els.modalTimeline.innerHTML = `
        <div class="modal-timeline-title">📅 Сьогодні</div>
        ${eventsHtml}
      `;
    }

    showModal();
  } catch (err) {
    console.error('Failed to load employee detail modal:', err);
  }
}

function showModal() {
  els.modalOverlay.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  els.modalOverlay.classList.remove('active');
  document.body.style.overflow = '';
}

async function sendAdminAction(telegramId, action) {
  const btn = document.querySelector(`.admin-btn[data-action="${action.replace('_', '-')}"]`);
  if (!btn || btn.disabled) return;

  if (tg?.HapticFeedback) {
    tg.HapticFeedback.impactOccurred('medium');
  }

  const originalText = btn.textContent;
  btn.textContent = '...';
  btn.disabled = true;

  try {
    await apiRequest('POST', '/api/admin/set-status', {
      telegram_id: telegramId,
      action: action,
      note: 'Змінено адміністратором'
    });

    showToast('Статус успішно змінено', 'success');
    
    // Refresh the modal content with the new state
    await openEmployeeDetail(telegramId);
    
    // Refresh dashboard list silently
    loadDashboardData(true);

    if (tg?.HapticFeedback) {
      tg.HapticFeedback.notificationOccurred('success');
    }
  } catch (err) {
    console.error(`Admin action ${action} failed:`, err);
    if (tg?.HapticFeedback) {
      tg.HapticFeedback.notificationOccurred('error');
    }
    showToast(err.message || 'Помилка', 'error');
    btn.textContent = originalText;
    btn.disabled = false;
  }
}

async function sendAdminAliases(telegramId, aliases) {
  const btn = els.adminSaveAliasesBtn;
  if (!btn || btn.disabled) return;

  if (tg?.HapticFeedback) {
    tg.HapticFeedback.impactOccurred('medium');
  }

  const originalText = btn.textContent;
  btn.textContent = '...';
  btn.disabled = true;

  try {
    await apiRequest('POST', '/api/admin/set-aliases', {
      telegram_id: telegramId,
      aliases: aliases
    });

    showToast('Аліаси успішно збережено', 'success');
    
    // Refresh dashboard list silently
    loadDashboardData(true);

    if (tg?.HapticFeedback) {
      tg.HapticFeedback.notificationOccurred('success');
    }
  } catch (err) {
    console.error(`Admin set aliases failed:`, err);
    if (tg?.HapticFeedback) {
      tg.HapticFeedback.notificationOccurred('error');
    }
    showToast(err.message || 'Помилка', 'error');
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
}

// ===== Helper Functions =====
function formatTime(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  const kyivTime = new Date(date.getTime() + 3 * 60 * 60 * 1000);
  const hours = String(kyivTime.getUTCHours()).padStart(2, '0');
  const minutes = String(kyivTime.getUTCMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

function getInitials(firstName, lastName) {
  let initials = (firstName || '?')[0].toUpperCase();
  if (lastName) initials += lastName[0].toUpperCase();
  return initials;
}

function animateNumber(element, targetValue) {
  const currentValue = parseInt(element.textContent, 10) || 0;
  if (currentValue === targetValue) return;
  element.textContent = targetValue;
  element.style.animation = 'none';
  void element.offsetHeight; // trigger reflow
  element.style.animation = 'countUp 0.3s ease-out';
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function hideLoading() {
  els.loading.classList.remove('active');
}

let toastTimer = null;
function showToast(message, type = 'success') {
  clearTimeout(toastTimer);
  els.toast.textContent = message;
  els.toast.className = `toast ${type} show`;
  toastTimer = setTimeout(() => {
    els.toast.classList.replace('show', 'hide');
    setTimeout(() => {
      els.toast.className = 'toast';
    }, 300);
  }, 2500);
}

// Start
document.addEventListener('DOMContentLoaded', init);
