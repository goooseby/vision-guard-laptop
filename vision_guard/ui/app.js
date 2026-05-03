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
  disarmed: '摄像头未被占用。点击布防后，后台引擎会开始运动检测。',
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
  storageUsedText: document.querySelector('#storageUsedText'),
  diskFreeText: document.querySelector('#diskFreeText'),
  missingFilesText: document.querySelector('#missingFilesText'),
  storagePathText: document.querySelector('#storagePathText'),
  eventPreset: document.querySelector('#eventPreset'),
  eventDateFrom: document.querySelector('#eventDateFrom'),
  eventDateTo: document.querySelector('#eventDateTo'),
  applyFilterBtn: document.querySelector('#applyFilterBtn'),
  deleteSelectedBtn: document.querySelector('#deleteSelectedBtn'),
  cleanupBtn: document.querySelector('#cleanupBtn'),
  previewToggle: document.querySelector('#previewToggle'),
  previewImage: document.querySelector('#previewImage'),
  cameraStage: document.querySelector('#cameraStage'),
  previewOverlay: document.querySelector('#previewOverlay'),
  previewFpsText: document.querySelector('#previewFpsText'),
  previewFrameText: document.querySelector('#previewFrameText'),
  heatmapLayer: document.querySelector('#heatmapLayer'),
  roiOverlay: document.querySelector('#roiOverlay'),
  motionScoreText: document.querySelector('#motionScoreText'),
  motionGaugeBar: document.querySelector('#motionGaugeBar'),
  motionUpdatedText: document.querySelector('#motionUpdatedText'),
  recentEvents: document.querySelector('#recentEvents'),
  eventsList: document.querySelector('#eventsList'),
  armBtn: document.querySelector('#armBtn'),
  disarmBtn: document.querySelector('#disarmBtn'),
  refreshBtn: document.querySelector('#refreshBtn'),
  openStorageBtn: document.querySelector('#openStorageBtn'),
  saveSettingsBtn: document.querySelector('#saveSettingsBtn'),
  settingsForm: document.querySelector('#settingsForm'),
  resetRoiBtn: document.querySelector('#resetRoiBtn'),
};

let latestConfig = null;
let currentView = 'dashboard';
let latestStatus = null;
let previewEnabled = false;
let previewTimer = null;
let previewBusy = false;
let previewActiveSent = null;
let previewHasFrame = false;
let roiDrag = null;
let latestEvents = [];
const selectedEvents = new Set();

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
  updateRoiEditability();
  schedulePreviewLoop();
}

function renderStatus(status) {
  latestStatus = status;
  const state = status.state || 'error';
  els.sideState.textContent = stateLabel[state] || state;
  els.stateText.textContent = stateLabel[state] || state;
  els.stateHint.textContent = status.last_error || stateHint[state] || '';
  els.cameraText.textContent = `#${status.camera_id} 路 ${status.camera_ready ? '可用' : '未占用'}`;
  els.lastEventText.textContent = fmtTime(status.last_event_at);
  els.recordingText.textContent = status.recording ? '录制中' : '空闲';
  els.statusDot.className = `status-dot ${state}`;
  els.armBtn.disabled = ['armed', 'arming', 'triggered', 'cooldown'].includes(state);
  els.disarmBtn.disabled = ['disarmed', 'stopped'].includes(state);
  els.previewFpsText.textContent = `上限 ${status.capture_fps || '-'} FPS`;
  renderMotion(status);
  updateDetectionOverlays(status);
  updatePreviewOverlay(null, { preserveFrame: true });
  schedulePreviewLoop();
}

function renderStats(stats) {
  els.totalEvents.textContent = stats?.total ?? 0;
  els.savedEvents.textContent = stats?.saved ?? 0;
  els.failedEvents.textContent = stats?.failed ?? 0;
}

function renderStorageStats(stats) {
  if (!stats) return;
  els.storageUsedText.textContent = formatBytes(stats.total_bytes || 0);
  els.diskFreeText.textContent = formatBytes(stats.disk_free_bytes || 0);
  els.missingFilesText.textContent = stats.missing_files ?? 0;
  els.storagePathText.textContent = stats.storage_path || '-';
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
      <input class="event-select" type="checkbox" data-select="${escapeHtml(event.event_id)}" ${selectedEvents.has(event.event_id) ? 'checked' : ''}>
      <div class="thumb">${thumb}</div>
      <div class="event-meta">
        <strong>${escapeHtml(event.label)}</strong>
        <span>${fmtTime(event.triggered_at)}</span>
        <span>${escapeHtml(event.file_name || event.video_path || '无录像文件')}</span>
        <div class="badges">
          <span class="badge ${event.status}">${statusText(event.status)}</span>
          ${fileBadge}
          <span class="badge">${Number(event.duration_seconds || 0).toFixed(1)}s</span>
          <span class="badge">${formatBytes(event.total_size_bytes || 0)}</span>
        </div>
      </div>
      <div class="inline-actions">
        <button ${playDisabled} data-open="${escapeHtml(event.event_id)}">播放</button>
        <button class="secondary" data-delete="${escapeHtml(event.event_id)}">删除</button>
      </div>
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

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let size = value / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[index]}`;
}

function currentEventFilters() {
  const preset = els.eventPreset?.value || 'all';
  const filters = { limit: 500 };
  if (preset !== 'all' && preset !== 'custom') {
    filters.preset = preset;
  }
  if (preset === 'custom') {
    if (els.eventDateFrom.value) filters.date_from = `${els.eventDateFrom.value}T00:00:00`;
    if (els.eventDateTo.value) filters.date_to = `${els.eventDateTo.value}T23:59:59`;
  }
  return filters;
}

function updateBulkButtons() {
  els.deleteSelectedBtn.disabled = selectedEvents.size === 0;
}

function renderMotion(payload) {
  const score = Number(payload?.motion?.score ?? payload?.motion_score ?? 0);
  const threshold = Number(payload?.motion?.threshold ?? payload?.motion_threshold ?? latestConfig?.motion?.motion_sensitivity ?? 1);
  const ratio = Number(payload?.motion?.ratio ?? payload?.motion_score_ratio ?? Math.min(1, score / Math.max(1, threshold)));
  const active = Boolean(payload?.motion?.active ?? payload?.motion_active);
  const updatedAt = payload?.motion?.updated_at ?? payload?.motion_updated_at;

  els.motionScoreText.textContent = `${Math.round(score)} / ${threshold}`;
  els.motionGaugeBar.style.width = `${Math.max(0, Math.min(100, ratio * 100))}%`;
  els.motionGaugeBar.classList.toggle('hot', active);
  els.motionUpdatedText.textContent = updatedAt ? fmtTime(updatedAt) : '-';
}

function updateDetectionOverlays(payload) {
  const motion = payload?.motion || payload || {};
  const roi = motion.roi || motion.motion_roi || latestStatus?.motion_roi || fullRoi();
  renderRoiOverlay(roi);
  renderHeatmap(motion.boxes || motion.heatmap_boxes || []);
  updateRoiEditability();
}

function renderRoiOverlay(roi) {
  const enabled = Boolean(latestConfig?.motion?.roi_enabled);
  els.roiOverlay.hidden = !enabled;
  if (!enabled) return;
  setOverlayRect(els.roiOverlay, roi);
}

function renderHeatmap(boxes) {
  const enabled = Boolean(latestConfig?.motion?.heatmap_enabled);
  if (!enabled || !previewHasFrame) {
    els.heatmapLayer.innerHTML = '';
    return;
  }
  els.heatmapLayer.innerHTML = boxes.map(box => {
    const opacity = Math.max(.22, Math.min(.68, Number(box.score || 0) / Math.max(1, latestConfig?.motion?.motion_sensitivity || 2500)));
    return `<span class="heat-box" style="${rectStyle(box)} opacity:${opacity}"></span>`;
  }).join('');
}

function setOverlayRect(element, roi) {
  element.style.left = `${Number(roi.x || 0) * 100}%`;
  element.style.top = `${Number(roi.y || 0) * 100}%`;
  element.style.width = `${Number(roi.width || 1) * 100}%`;
  element.style.height = `${Number(roi.height || 1) * 100}%`;
}

function rectStyle(rect) {
  return `left:${Number(rect.x || 0) * 100}%;top:${Number(rect.y || 0) * 100}%;width:${Number(rect.width || 0) * 100}%;height:${Number(rect.height || 0) * 100}%;`;
}

function fullRoi() {
  return { x: 0, y: 0, width: 1, height: 1 };
}

async function refreshStatus() {
  const result = await callApi('get_status');
  renderStatus(result.status);
}

async function refreshEvents() {
  const result = await callApi('list_events_filtered', currentEventFilters());
  latestEvents = result.events;
  selectedEvents.clear();
  renderStats(result.stats);
  renderStorageStats(result.stats);
  renderEvents(result.events.slice(0, 3), els.recentEvents);
  renderEvents(result.events, els.eventsList);
  updateBulkButtons();
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
      renderMotion(frame);
      updateDetectionOverlays(frame.motion);
    } else if (!previewHasFrame) {
      els.cameraStage.classList.remove('active');
      els.previewFrameText.textContent = '等待帧';
      updateDetectionOverlays(frame.motion);
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
    els.heatmapLayer.innerHTML = '';
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
    els.heatmapLayer.innerHTML = '';
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
  updateDetectionOverlays(latestStatus);
}

function fillSettingsForm(config) {
  applyTheme(config?.ui?.theme || 'studio');
  els.settingsForm.querySelectorAll('[data-path]').forEach(input => {
    let value = getPath(config, input.dataset.path);
    if (input.dataset.path === 'ui.theme' && value === 'dark') {
      value = 'studio';
    }
    if (input.dataset.scale === 'percent') {
      value = Math.round(Number(value || 0) * 100);
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
      if (input.dataset.scale === 'percent') {
        value /= 100;
      }
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

function updateRoiEditability() {
  const editable = previewEnabled && currentView === 'dashboard';
  els.cameraStage.classList.toggle('roi-editable', editable);
}

function pointToStage(event) {
  const rect = els.cameraStage.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
    y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
  };
}

function roiFromPoints(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const width = Math.max(.01, Math.abs(a.x - b.x));
  const height = Math.max(.01, Math.abs(a.y - b.y));
  return {
    x: Number(x.toFixed(4)),
    y: Number(y.toFixed(4)),
    width: Number(width.toFixed(4)),
    height: Number(height.toFixed(4)),
  };
}

function setRoiInputs(roi) {
  Object.entries({
    'motion.roi_x': roi.x,
    'motion.roi_y': roi.y,
    'motion.roi_width': roi.width,
    'motion.roi_height': roi.height,
  }).forEach(([path, value]) => {
    const input = els.settingsForm.querySelector(`[data-path="${path}"]`);
    if (input) input.value = Math.round(value * 100);
  });
}

async function saveRoi(roi) {
  if (!latestConfig) return;
  latestConfig.motion.roi_enabled = true;
  latestConfig.motion.roi_x = roi.x;
  latestConfig.motion.roi_y = roi.y;
  latestConfig.motion.roi_width = roi.width;
  latestConfig.motion.roi_height = roi.height;
  setRoiInputs(roi);
  try {
    const result = await callApi('save_config', { motion: {
      roi_enabled: true,
      roi_x: roi.x,
      roi_y: roi.y,
      roi_width: roi.width,
      roi_height: roi.height,
    } });
    latestConfig = result.config;
    fillSettingsForm(result.config);
    renderStatus(result.status);
    showToast('检测区域已更新');
  } catch (error) {
    showToast(error.message, 'error');
  }
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
  updateRoiEditability();
  updatePreviewOverlay();
  schedulePreviewLoop();
});

els.settingsForm.addEventListener('change', event => {
  if (event.target?.dataset?.path === 'ui.theme') {
    applyTheme(event.target.value);
  }
});

els.resetRoiBtn.addEventListener('click', async () => {
  const full = fullRoi();
  setRoiInputs(full);
  try {
    const result = await callApi('save_config', { motion: {
      roi_enabled: false,
      roi_x: 0,
      roi_y: 0,
      roi_width: 1,
      roi_height: 1,
    } });
    latestConfig = result.config;
    fillSettingsForm(result.config);
    renderStatus(result.status);
    showToast('检测区域已重置为全画面');
  } catch (error) {
    showToast(error.message, 'error');
  }
});

els.cameraStage.addEventListener('pointerdown', event => {
  if (!els.cameraStage.classList.contains('roi-editable') || !previewHasFrame) return;
  event.preventDefault();
  const start = pointToStage(event);
  roiDrag = { start, current: start };
  els.roiOverlay.hidden = false;
  els.cameraStage.setPointerCapture(event.pointerId);
  setOverlayRect(els.roiOverlay, roiFromPoints(start, start));
});

els.cameraStage.addEventListener('pointermove', event => {
  if (!roiDrag) return;
  roiDrag.current = pointToStage(event);
  setOverlayRect(els.roiOverlay, roiFromPoints(roiDrag.start, roiDrag.current));
});

els.cameraStage.addEventListener('pointerup', event => {
  if (!roiDrag) return;
  const roi = roiFromPoints(roiDrag.start, pointToStage(event));
  roiDrag = null;
  els.cameraStage.releasePointerCapture(event.pointerId);
  if (roi.width < .03 || roi.height < .03) {
    updateDetectionOverlays(latestStatus);
    return;
  }
  saveRoi(roi);
});

els.cameraStage.addEventListener('pointercancel', () => {
  roiDrag = null;
  updateDetectionOverlays(latestStatus);
});

document.addEventListener('visibilitychange', schedulePreviewLoop);

els.openStorageBtn.addEventListener('click', async () => {
  try {
    await callApi('reveal_storage');
  } catch (error) {
    showToast(error.message, 'error');
  }
});

els.applyFilterBtn.addEventListener('click', refreshEvents);

els.eventPreset.addEventListener('change', () => {
  const custom = els.eventPreset.value === 'custom';
  els.eventDateFrom.disabled = !custom;
  els.eventDateTo.disabled = !custom;
  if (!custom) refreshEvents();
});

els.deleteSelectedBtn.addEventListener('click', async () => {
  const ids = Array.from(selectedEvents);
  if (!ids.length) return;
  const totalSize = latestEvents
    .filter(event => selectedEvents.has(event.event_id))
    .reduce((total, event) => total + Number(event.total_size_bytes || 0), 0);
  if (!window.confirm(`确认删除 ${ids.length} 条事件并释放约 ${formatBytes(totalSize)}？`)) return;
  try {
    const result = await callApi('delete_events', ids);
    showToast(`已删除 ${result.result.deleted_records} 条事件，释放 ${formatBytes(result.result.freed_bytes)}`);
    await refreshEvents();
  } catch (error) {
    showToast(error.message, 'error');
  }
});

els.cleanupBtn.addEventListener('click', async () => {
  if (!window.confirm('按当前保留天数和容量上限清理旧事件？')) return;
  try {
    const result = await callApi('cleanup_events', 'configured');
    showToast(`清理完成：删除 ${result.result.deleted_records} 条，释放 ${formatBytes(result.result.freed_bytes)}`);
    await refreshEvents();
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
  const deleteButton = event.target.closest('[data-delete]');
  if (deleteButton) {
    const eventId = deleteButton.dataset.delete;
    if (!window.confirm('确认删除这条事件及其录像/缩略图？')) return;
    try {
      const result = await callApi('delete_events', [eventId]);
      showToast(`已删除 ${result.result.deleted_records} 条事件`);
      await refreshEvents();
    } catch (error) {
      showToast(error.message, 'error');
    }
    return;
  }

  const button = event.target.closest('[data-open]');
  if (!button) return;
  try {
    await callApi('open_video', button.dataset.open);
  } catch (error) {
    showToast(error.message, 'error');
  }
});

document.addEventListener('change', event => {
  const checkbox = event.target.closest('[data-select]');
  if (!checkbox) return;
  if (checkbox.checked) {
    selectedEvents.add(checkbox.dataset.select);
  } else {
    selectedEvents.delete(checkbox.dataset.select);
  }
  updateBulkButtons();
});

apiReady.then(async () => {
  await Promise.all([refreshAll(), loadConfig()]);
  window.setInterval(refreshStatus, 2500);
  window.setInterval(refreshEvents, 7000);
}).catch(error => {
  showToast(error.message, 'error');
});
