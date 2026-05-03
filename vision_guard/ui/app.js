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
  previewToggle: document.querySelector('#previewToggle'),
  previewImage: document.querySelector('#previewImage'),
  cameraStage: document.querySelector('#cameraStage'),
  previewOverlay: document.querySelector('#previewOverlay'),
  previewFpsText: document.querySelector('#previewFpsText'),
  previewFrameText: document.querySelector('#previewFrameText'),
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
let latestStatus = null;
let previewEnabled = false;
let previewTimer = null;
let previewBusy = false;
let previewActiveSent = null;
let previewHasFrame = false;

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
  schedulePreviewLoop();
}

function renderStatus(status) {
  latestStatus = status;
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
  els.previewFpsText.textContent = `上限 ${status.capture_fps || '-'} FPS`;
  updatePreviewOverlay(null, { preserveFrame: true });
  schedulePreviewLoop();
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

function previewShouldRun() {
  if (!previewEnabled || currentView !== 'dashboard') return false;
  if (document.hidden) return false;
  const state = latestStatus?.state;
  return ['armed', 'triggered', 'cooldown', 'arming'].includes(state);
}

function previewIntervalMs() {
  const fps = Math.max(1, Number(latestStatus?.capture_fps || latestConfig?.camera?.capture_fps || 10));
  return Math.max(33, Math.round(1000 / fps));
}

function schedulePreviewLoop() {
  if (previewTimer) {
    window.clearTimeout(previewTimer);
    previewTimer = null;
  }
  const shouldRun = previewShouldRun();
  syncPreviewActive(shouldRun);
  if (!shouldRun) {
    updatePreviewOverlay();
    return;
  }
  previewTimer = window.setTimeout(fetchPreviewFrame, previewIntervalMs());
}

function syncPreviewActive(active) {
  if (previewActiveSent === active) return;
  previewActiveSent = active;
  apiReady.then(() => window.pywebview.api.set_preview_active(active)).catch(() => {
    previewActiveSent = null;
  });
}

async function fetchPreviewFrame() {
  if (!previewShouldRun() || previewBusy) {
    schedulePreviewLoop();
    return;
  }
  previewBusy = true;
  try {
    const result = await callApi('get_preview_frame');
    const frame = result.frame;
    if (frame.available && frame.image) {
      els.previewImage.src = frame.image;
      els.cameraStage.classList.add('active');
      previewHasFrame = true;
      els.previewFrameText.textContent = frame.captured_at ? fmtTime(frame.captured_at) : '实时帧';
    } else {
      if (!previewHasFrame) {
        els.cameraStage.classList.remove('active');
        els.previewFrameText.textContent = '等待帧';
      }
    }
    updatePreviewOverlay(frame, { preserveFrame: true });
  } catch {
    els.previewFrameText.textContent = '预览错误';
  } finally {
    previewBusy = false;
    schedulePreviewLoop();
  }
}

function updatePreviewOverlay(frame = null, options = {}) {
  if (previewShouldRun() && frame?.available) {
    els.previewOverlay.innerHTML = '<strong>实时预览中</strong><span>画面来自后台捕捉引擎，不会额外占用摄像头。</span>';
    return;
  }
  const preserveFrame = options.preserveFrame && previewHasFrame && previewShouldRun();
  if (!preserveFrame) {
    els.cameraStage.classList.remove('active');
  }
  if (!previewEnabled) {
    previewHasFrame = false;
    els.previewImage.removeAttribute('src');
    els.previewOverlay.innerHTML = '<strong>预览关闭</strong><span>打开开关后，将从后台捕捉引擎读取实时画面。</span>';
    els.previewFrameText.textContent = '等待帧';
    return;
  }
  if (currentView !== 'dashboard' || document.hidden) {
    els.previewOverlay.innerHTML = '<strong>预览暂停</strong><span>离开总览页或窗口不可见时不会渲染画面。</span>';
    return;
  }
  if (!latestStatus?.camera_ready) {
    previewHasFrame = false;
    els.previewImage.removeAttribute('src');
    els.previewOverlay.innerHTML = '<strong>等待摄像头</strong><span>点击布防后，后台引擎会提供实时画面。</span>';
    return;
  }
  if (preserveFrame) {
    return;
  }
  els.previewOverlay.innerHTML = '<strong>等待画面</strong><span>摄像头已连接，正在获取最近帧。</span>';
}

async function loadConfig() {
  const result = await callApi('get_config');
  latestConfig = result.config;
  fillSettingsForm(result.config);
}

function fillSettingsForm(config) {
  applyTheme(config?.ui?.theme || 'studio');
  els.settingsForm.querySelectorAll('[data-path]').forEach(input => {
    let value = getPath(config, input.dataset.path);
    if (input.dataset.path === 'ui.theme' && value === 'dark') {
      value = 'studio';
    }
    if (input.tagName === 'SELECT') {
      input.value = String(value);
    } else {
      input.value = value;
    }
  });
}

function applyTheme(theme) {
  const normalized = theme === 'dark' ? 'studio' : theme;
  document.body.dataset.theme = normalized || 'studio';
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

els.previewToggle.addEventListener('change', () => {
  previewEnabled = els.previewToggle.checked;
  updatePreviewOverlay();
  schedulePreviewLoop();
});

els.settingsForm.addEventListener('change', event => {
  if (event.target?.dataset?.path === 'ui.theme') {
    applyTheme(event.target.value);
  }
});

document.addEventListener('visibilitychange', schedulePreviewLoop);

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
    applyTheme(result.config?.ui?.theme);
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
