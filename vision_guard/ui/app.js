const apiReady = new Promise(resolve => {
  if (window.pywebview?.api) {
    resolve();
    return;
  }
  window.addEventListener('pywebviewready', resolve, { once: true });
});

const stateLabel = {
  disarmed: '已撤防',
  arming: '正在布防',
  armed: '布防中',
  triggered: '已触发',
  cooldown: '冷却中',
  error: '需要处理',
  stopped: '已停止',
};

const stateHint = {
  disarmed: '摄像头未被占用。点击布防后，后台引擎会开始低帧率运动检测。',
  arming: '正在初始化摄像头，请稍候。',
  armed: '系统正在监控画面变化，预录制缓冲区在内存中滚动维护。',
  triggered: '检测到明显运动，正在固化事件证据。',
  cooldown: '事件已保存，正在短暂冷却以避免重复触发。',
  error: '后台引擎遇到问题。请查看提示，确认摄像头权限或占用情况。',
  stopped: '核心引擎已停止。',
};

const viewTitle = {
  dashboard: '安全总览',
  events: '事件时间线',
  settings: '运行设置',
};

const els = {
  navItems: document.querySelectorAll('.nav-item'),
  views: {
    dashboard: document.querySelector('#dashboardView'),
    events: document.querySelector('#eventsView'),
    settings: document.querySelector('#settingsView'),
  },
  viewTitle: document.querySelector('#viewTitle'),
  toast: document.querySelector('#toast'),
  sideState: document.querySelector('#sideState'),
  statusDot: document.querySelector('#statusDot'),
  stateText: document.querySelector('#stateText'),
  stateHint: document.querySelector('#stateHint'),
  cameraText: document.querySelector('#cameraText'),
  lastEventText: document.querySelector('#lastEventText'),
  totalEvents: document.querySelector('#totalEvents'),
  savedEvents: document.querySelector('#savedEvents'),
  failedEvents: document.querySelector('#failedEvents'),
  recordingText: document.querySelector('#recordingText'),
  recentEvents: document.querySelector('#recentEvents'),
  eventsList: document.querySelector('#eventsList'),
  armBtn: document.querySelector('#armBtn'),
  disarmBtn: document.querySelector('#disarmBtn'),
  refreshBtn: document.querySelector('#refreshBtn'),
  openStorageBtn: document.querySelector('#openStorageBtn'),
  saveSettingsBtn: document.querySelector('#saveSettingsBtn'),
  settingsForm: document.querySelector('#settingsForm'),
};

let latestConfig = null;
let currentView = 'dashboard';

async function callApi(method, ...args) {
  await apiReady;
  const result = await window.pywebview.api[method](...args);
  if (!result?.ok) {
    throw new Error(result?.error || '操作失败');
  }
  return result;
}

function showToast(message, type = 'info') {
  els.toast.textContent = message;
  els.toast.hidden = !message;
  els.toast.dataset.type = type;
  if (message) {
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      els.toast.hidden = true;
    }, 4200);
  }
}

function fmtTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function setView(name) {
  currentView = name;
  els.viewTitle.textContent = viewTitle[name];
  els.navItems.forEach(item => item.classList.toggle('active', item.dataset.view === name));
  Object.entries(els.views).forEach(([key, node]) => node.classList.toggle('active', key === name));
}

function renderStatus(status) {
  const state = status.state || 'error';
  els.sideState.textContent = stateLabel[state] || state;
  els.stateText.textContent = stateLabel[state] || state;
  els.stateHint.textContent = status.last_error || stateHint[state] || '';
  els.cameraText.textContent = `#${status.camera_id} · ${status.camera_ready ? '可用' : '未占用'}`;
  els.lastEventText.textContent = fmtTime(status.last_event_at);
  els.recordingText.textContent = status.recording ? '录制中' : '空闲';
  els.statusDot.className = `status-dot ${state}`;
  els.armBtn.disabled = ['armed', 'arming', 'triggered', 'cooldown'].includes(state);
  els.disarmBtn.disabled = ['disarmed', 'stopped'].includes(state);
}

function renderStats(stats) {
  els.totalEvents.textContent = stats?.total ?? 0;
  els.savedEvents.textContent = stats?.saved ?? 0;
  els.failedEvents.textContent = stats?.failed ?? 0;
}

function renderEvents(events, target) {
  if (!events.length) {
    target.innerHTML = '<p class="empty">暂无安全事件</p>';
    return;
  }
  target.innerHTML = events.map(event => eventTemplate(event)).join('');
}

function eventTemplate(event) {
  const thumb = event.thumbnail_data_url
    ? `<img src="${event.thumbnail_data_url}" alt="${escapeHtml(event.label)} 缩略图">`
    : '<span>无缩略图</span>';
  const fileBadge = event.video_exists
    ? '<span class="badge saved">文件可用</span>'
    : '<span class="badge missing">文件丢失</span>';
  const playDisabled = event.video_exists ? '' : 'disabled';
  return `
    <article class="event">
      <div class="thumb">${thumb}</div>
      <div class="event-meta">
        <strong>${escapeHtml(event.label)}</strong>
        <span>${fmtTime(event.triggered_at)}</span>
        <span>${escapeHtml(event.file_name || event.video_path || '无录像文件')}</span>
        <div class="badges">
          <span class="badge ${event.status}">${statusText(event.status)}</span>
          ${fileBadge}
          <span class="badge">${Number(event.duration_seconds || 0).toFixed(1)}s</span>
        </div>
      </div>
      <button ${playDisabled} data-open="${escapeHtml(event.event_id)}">播放</button>
    </article>
  `;
}

function statusText(status) {
  if (status === 'saved') return '已保存';
  if (status === 'partial') return '部分保存';
  if (status === 'failed') return '保存失败';
  return status || '未知';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function refreshStatus() {
  const result = await callApi('get_status');
  renderStatus(result.status);
}

async function refreshEvents() {
  const result = await callApi('list_events');
  renderStats(result.stats);
  renderEvents(result.events.slice(0, 3), els.recentEvents);
  renderEvents(result.events, els.eventsList);
}

async function refreshAll() {
  try {
    await Promise.all([refreshStatus(), refreshEvents()]);
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function loadConfig() {
  const result = await callApi('get_config');
  latestConfig = result.config;
  fillSettingsForm(result.config);
}

function fillSettingsForm(config) {
  els.settingsForm.querySelectorAll('[data-path]').forEach(input => {
    const value = getPath(config, input.dataset.path);
    if (input.tagName === 'SELECT') {
      input.value = String(value);
    } else {
      input.value = value;
    }
  });
}

function collectSettingsPatch() {
  const patch = {};
  els.settingsForm.querySelectorAll('[data-path]').forEach(input => {
    let value = input.value;
    if (input.tagName === 'SELECT' && ['true', 'false'].includes(value)) {
      value = value === 'true';
    } else if (input.type === 'number') {
      value = Number(value);
    }
    setPath(patch, input.dataset.path, value);
  });
  return patch;
}

function getPath(object, path) {
  return path.split('.').reduce((current, key) => current?.[key], object);
}

function setPath(object, path, value) {
  const keys = path.split('.');
  const last = keys.pop();
  const target = keys.reduce((current, key) => {
    current[key] = current[key] || {};
    return current[key];
  }, object);
  target[last] = value;
}

els.navItems.forEach(item => {
  item.addEventListener('click', () => setView(item.dataset.view));
});

document.querySelectorAll('[data-view-shortcut]').forEach(item => {
  item.addEventListener('click', () => setView(item.dataset.viewShortcut));
});

els.armBtn.addEventListener('click', async () => {
  try {
    const result = await callApi('arm');
    renderStatus(result.status);
    showToast('布防已启动');
  } catch (error) {
    showToast(error.message, 'error');
  }
});

els.disarmBtn.addEventListener('click', async () => {
  try {
    const result = await callApi('disarm');
    renderStatus(result.status);
    showToast('已撤防');
  } catch (error) {
    showToast(error.message, 'error');
  }
});

els.refreshBtn.addEventListener('click', refreshAll);

els.openStorageBtn.addEventListener('click', async () => {
  try {
    await callApi('reveal_storage');
  } catch (error) {
    showToast(error.message, 'error');
  }
});

els.saveSettingsBtn.addEventListener('click', async () => {
  try {
    const result = await callApi('save_config', collectSettingsPatch());
    latestConfig = result.config;
    fillSettingsForm(result.config);
    renderStatus(result.status);
    showToast('设置已保存');
  } catch (error) {
    showToast(error.message, 'error');
  }
});

document.addEventListener('click', async event => {
  const button = event.target.closest('[data-open]');
  if (!button) return;
  try {
    await callApi('open_video', button.dataset.open);
  } catch (error) {
    showToast(error.message, 'error');
  }
});

apiReady.then(async () => {
  await Promise.all([refreshAll(), loadConfig()]);
  window.setInterval(refreshStatus, 2500);
  window.setInterval(refreshEvents, 7000);
}).catch(error => {
  showToast(error.message, 'error');
});
