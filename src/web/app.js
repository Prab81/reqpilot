import { AudioCapture, listAudioInputs, micErrorMessage } from './audio-capture.js';

const EMPTY_STATE = Object.freeze({
  title: '', summary: [], requirements: [], decisions: [], open_questions: [],
  diagrams: [], metrics: [], gaps: [],
});

const ITEM_COLLECTIONS = Object.freeze({
  requirement: 'requirements', decision: 'decisions', question: 'open_questions',
  diagram: 'diagrams', metric: 'metrics', gap: 'gaps',
});

/** Normalize an untrusted state payload to the renderer contract. */
export function normalizeState(value) {
  const source = value && typeof value === 'object' ? value : {};
  const list = (key) => Array.isArray(source[key]) ? source[key].filter((x) => x && typeof x === 'object') : [];
  return {
    title: typeof source.title === 'string' ? source.title : '',
    summary: Array.isArray(source.summary) ? source.summary.filter((x) => typeof x === 'string') : [],
    requirements: list('requirements'), decisions: list('decisions'),
    open_questions: list('open_questions'), diagrams: list('diagrams'),
    metrics: list('metrics'), gaps: list('gaps'),
  };
}

/** Keep downloaded filenames portable across Windows and macOS. */
export function safeFilename(value, fallback = 'reqpilot-session') {
  const cleaned = String(value || '').trim().replace(/[<>:"/\\|?*\x00-\x1f]/g, '-')
    .replace(/\s+/g, '-').replace(/-+/g, '-').replace(/^[-.]+|[-.]+$/g, '');
  return (cleaned || fallback).slice(0, 80);
}

/** Turn seconds into the compact timestamp used in the transcript. */
export function formatTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

/** A bounded, deterministic coverage indicator (guidance, not a quality score). */
export function calculateCoverage(state) {
  const s = normalizeState(state);
  if (!s.requirements.length && !s.open_questions.length) return 0;
  const confirmed = s.requirements.filter((r) => r.status === 'confirmed').length;
  const answered = s.open_questions.filter((q) => q.status === 'answered').length;
  const requirementsScore = s.requirements.length
    ? ((s.requirements.length - (s.requirements.length - confirmed) * 0.35) / s.requirements.length) * 65
    : 0;
  const questionScore = s.open_questions.length ? (answered / s.open_questions.length) * 35 : 0;
  return Math.max(0, Math.min(100, Math.round(requirementsScore + questionScore)));
}

const hasDOM = typeof window !== 'undefined' && typeof document !== 'undefined';

if (hasDOM) {
  const $ = (id) => document.getElementById(id);
  const dom = {
    errorBanner: $('errorBanner'), errorText: $('errorText'), statusDot: $('statusDot'),
    statusLabel: $('statusLabel'), statusDetail: $('statusDetail'), sessionTitle: $('sessionTitle'),
    micDevice: $('micDevice'), sessionTimer: $('sessionTimer'), start: $('startSession'),
    pause: $('pauseSession'), stop: $('stopSession'), exportBrd: $('exportBrd'),
    transcript: $('transcript'), transcriptEmpty: $('transcriptEmpty'), utteranceCount: $('utteranceCount'),
    stateRevision: $('stateRevision'), summaryList: $('summaryList'), summaryCount: $('summaryCount'),
    requirementsList: $('requirementsList'), requirementsCount: $('requirementsCount'),
    decisionsList: $('decisionsList'), decisionsCount: $('decisionsCount'),
    visualsList: $('visualsList'), visualsCount: $('visualsCount'), questionList: $('questionList'),
    questionCount: $('questionCount'), gapsList: $('gapsList'), gapsCount: $('gapsCount'),
    coveragePercent: $('coveragePercent'), coverageBar: $('coverageBar'),
    progressTrack: document.querySelector('.progress-track'), sessionsDialog: $('sessionsDialog'),
    sessionsList: $('sessionsList'), editDialog: $('editDialog'), editForm: $('editForm'),
    editText: $('editText'), toastRegion: $('toastRegion'),
  };

  const app = {
    sessionId: null,
    socket: null,
    capture: null,
    phase: 'idle',
    state: { ...EMPTY_STATE },
    revision: 0,
    utterances: new Map(),
    partialNode: null,
    startedAt: null,
    elapsedBeforePause: 0,
    timerHandle: null,
    questionFilter: 'suggested',
    pinned: new Set(),
    pendingEdit: null,
    renderToken: 0,
  };

  if (window.mermaid) {
    window.mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral',
      flowchart: { htmlLabels: false, curve: 'basis' }, fontFamily: 'Inter, system-ui, sans-serif' });
  }

  app.capture = new AudioCapture({
    workletUrl: './worklet.js',
    onFrame(frame) {
      if (app.socket?.readyState === WebSocket.OPEN && app.phase === 'recording') {
        app.socket.send(frame.buffer);
      }
    },
    onError(error) {
      showError(error.message);
      setPhase('error', 'Microphone disconnected', 'Reconnect the microphone and start again.');
    },
  });

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function clear(node) { node.replaceChildren(); }

  function showError(message) {
    dom.errorText.textContent = message;
    dom.errorBanner.hidden = false;
  }

  function hideError() { dom.errorBanner.hidden = true; }

  function toast(message) {
    const item = element('div', 'toast', message);
    dom.toastRegion.append(item);
    window.setTimeout(() => item.remove(), 3500);
  }

  function setPhase(phase, label, detail) {
    app.phase = phase;
    dom.statusDot.dataset.state = phase;
    dom.statusLabel.textContent = label;
    dom.statusDetail.textContent = detail;
    const active = phase === 'recording' || phase === 'paused' || phase === 'connecting';
    dom.start.hidden = active;
    dom.pause.hidden = !active || phase === 'connecting';
    dom.stop.hidden = !active || phase === 'connecting';
    dom.pause.textContent = phase === 'paused' ? 'Resume' : 'Pause';
    dom.micDevice.disabled = active;
    dom.exportBrd.disabled = !app.sessionId;
  }

  async function api(path, options = {}) {
    const headers = { Accept: 'application/json', ...(options.headers || {}) };
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const response = await fetch(path, { ...options, headers });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try { detail = (await response.json()).detail || detail; } catch { /* use status */ }
      throw new Error(detail);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async function ensureSession() {
    if (app.sessionId) return app.sessionId;
    const created = await api('/api/session', { method: 'POST' });
    app.sessionId = created.id || created.session_id;
    if (!app.sessionId) throw new Error('The server did not return a session id.');
    return app.sessionId;
  }

  function openSocket(sessionId) {
    if (app.socket && app.socket.readyState <= WebSocket.OPEN) app.socket.close(1000, 'replaced');
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${location.host}/ws/session/${encodeURIComponent(sessionId)}`);
    socket.binaryType = 'arraybuffer';
    app.socket = socket;

    return new Promise((resolve, reject) => {
      let settled = false;
      const timeout = window.setTimeout(() => {
        if (!settled) { settled = true; socket.close(); reject(new Error('The live session did not become ready.')); }
      }, 10000);

      socket.addEventListener('message', (event) => {
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.type === 'ready' && !settled) {
          settled = true; window.clearTimeout(timeout); resolve(socket);
        }
        handleSocketMessage(message);
      });
      socket.addEventListener('error', () => {
        if (!settled) { settled = true; window.clearTimeout(timeout); reject(new Error('Could not connect to the live session.')); }
      });
      socket.addEventListener('close', (event) => {
        window.clearTimeout(timeout);
        if (app.socket !== socket || app.phase === 'idle' || app.phase === 'complete') return;
        if (!settled) { settled = true; reject(new Error('The live session closed before it was ready.')); }
        else {
          stopTimer();
          app.capture.stop();
          setPhase('error', 'Connection interrupted', `Session ${sessionId} is saved; reopen it when the server is available.`);
          showError(event.reason || 'The connection to ReqPilot was interrupted.');
        }
      });
    });
  }

  function handleSocketMessage(message) {
    switch (message.type) {
      case 'partial': renderPartial(message); break;
      case 'final': renderFinal(message); break;
      case 'state':
        app.state = normalizeState(message.state);
        app.revision = Number(message.rev) || app.revision + 1;
        renderState();
        break;
      case 'status': renderStatus(message); break;
      case 'error':
        showError(`${message.where ? `${message.where}: ` : ''}${message.message || 'Unknown processing error'}`);
        break;
      default: break;
    }
  }

  function renderStatus(status) {
    if (app.phase !== 'recording' && app.phase !== 'paused') return;
    const bits = [status.asr, status.engine, status.provider].filter(Boolean);
    if (bits.length) dom.statusDetail.textContent = bits.join(' · ');
  }

  async function startSession() {
    hideError();
    setPhase('connecting', 'Preparing your session', 'Connecting securely to the local engine…');
    try {
      const sessionId = await ensureSession();
      const socket = await openSocket(sessionId);
      await app.capture.start(dom.micDevice.value || undefined);
      socket.send(JSON.stringify({ type: 'start' }));
      await refreshDevices();
      startTimer(true);
      setPhase('recording', 'Listening', 'Live audio is being transcribed locally.');
      toast('Microphone connected');
    } catch (error) {
      await app.capture.stop();
      if (app.socket?.readyState === WebSocket.OPEN) app.socket.close(1000, 'capture failed');
      const message = error?.name ? micErrorMessage(error) : error.message;
      showError(message);
      setPhase('idle', 'Ready to try again', 'You can still reopen and review saved sessions.');
    }
  }

  async function togglePause() {
    if (app.phase === 'recording') {
      await app.capture.pause();
      app.elapsedBeforePause += Date.now() - app.startedAt;
      stopTimer(false);
      setPhase('paused', 'Paused', 'No microphone audio is being sent.');
    } else if (app.phase === 'paused') {
      await app.capture.resume();
      startTimer(false);
      setPhase('recording', 'Listening', 'Capture resumed in the same session.');
    }
  }

  async function stopSession() {
    dom.stop.disabled = true;
    try {
      if (app.socket?.readyState === WebSocket.OPEN) app.socket.send(JSON.stringify({ type: 'stop' }));
      await app.capture.stop();
      stopTimer();
      setPhase('complete', 'Session complete', 'Final analysis is running; your BRD is ready to export.');
      toast('Session saved locally');
    } finally {
      dom.stop.disabled = false;
    }
  }

  function startTimer(reset) {
    if (reset) app.elapsedBeforePause = 0;
    app.startedAt = Date.now();
    window.clearInterval(app.timerHandle);
    const update = () => {
      const elapsed = app.elapsedBeforePause + (Date.now() - app.startedAt);
      dom.sessionTimer.textContent = formatTime(elapsed / 1000);
    };
    update();
    app.timerHandle = window.setInterval(update, 1000);
  }

  function stopTimer(finalize = true) {
    window.clearInterval(app.timerHandle);
    app.timerHandle = null;
    if (finalize && app.startedAt && app.phase === 'recording') app.elapsedBeforePause += Date.now() - app.startedAt;
  }

  async function refreshDevices() {
    const devices = await listAudioInputs();
    const selected = dom.micDevice.value;
    clear(dom.micDevice);
    const fallback = element('option', '', 'System default'); fallback.value = '';
    dom.micDevice.append(fallback);
    devices.forEach((device, index) => {
      const option = element('option', '', device.label || `Microphone ${index + 1}`);
      option.value = device.deviceId;
      dom.micDevice.append(option);
    });
    if ([...dom.micDevice.options].some((o) => o.value === selected)) dom.micDevice.value = selected;
  }

  function transcriptEntry(message, partial = false) {
    const row = element('article', `utterance${partial ? ' is-partial' : ''}`);
    if (message.utterance_id !== undefined) row.dataset.utteranceId = String(message.utterance_id);
    const marker = element('span', 'utterance-marker'); marker.setAttribute('aria-hidden', 'true');
    const body = element('div', 'utterance-body');
    const meta = element('div', 'utterance-meta');
    meta.append(element('span', '', partial ? 'Listening…' : `Utterance ${message.utterance_id ?? ''}`));
    meta.append(element('time', '', formatTime(message.t0 ?? app.elapsedBeforePause / 1000)));
    body.append(meta, element('p', 'utterance-text', message.text || ''));
    row.append(marker, body);
    return row;
  }

  function ensureTranscriptStarted() {
    dom.transcriptEmpty?.remove();
    dom.transcriptEmpty = null;
  }

  function renderPartial(message) {
    if (!message.text) return;
    ensureTranscriptStarted();
    if (!app.partialNode || app.partialNode.dataset.utteranceId !== String(message.utterance_id)) {
      app.partialNode?.remove();
      app.partialNode = transcriptEntry(message, true);
      dom.transcript.append(app.partialNode);
    } else {
      app.partialNode.querySelector('.utterance-text').textContent = message.text;
    }
    dom.transcript.scrollTop = dom.transcript.scrollHeight;
  }

  function renderFinal(message) {
    if (!message.text) return;
    ensureTranscriptStarted();
    if (app.partialNode?.dataset.utteranceId === String(message.utterance_id)) app.partialNode.remove();
    app.partialNode = null;
    const existing = dom.transcript.querySelector(`[data-utterance-id="${CSS.escape(String(message.utterance_id))}"]:not(.is-partial)`);
    const row = transcriptEntry(message);
    if (existing) existing.replaceWith(row); else dom.transcript.append(row);
    app.utterances.set(message.utterance_id, message);
    dom.utteranceCount.textContent = `${app.utterances.size} captured`;
    dom.transcript.scrollTop = dom.transcript.scrollHeight;
  }

  function evidence(item) {
    const refs = Array.isArray(item.evidence_utterances) ? item.evidence_utterances : [];
    if (!refs.length) return null;
    const node = element('span', 'evidence', `Evidence · ${refs.map((id) => `U${id}`).join(', ')}`);
    node.title = 'Transcript utterance references';
    return node;
  }

  function statusPill(status) {
    const value = String(status || 'captured');
    return element('span', `status-pill status-${value}`, value.replace('_', ' '));
  }

  function itemActions(kind, item, { dismiss = true } = {}) {
    const actions = element('div', 'item-actions');
    const pinKey = `${kind}:${item.id}`;
    const pin = element('button', 'icon-button action-pin', app.pinned.has(pinKey) ? '●' : '○');
    pin.type = 'button'; pin.title = app.pinned.has(pinKey) ? 'Pinned' : 'Pin item';
    pin.setAttribute('aria-label', pin.title);
    pin.disabled = app.pinned.has(pinKey);
    pin.addEventListener('click', () => applyOverride(kind, item, 'pin'));
    const edit = element('button', 'icon-button', '✎'); edit.type = 'button'; edit.title = 'Edit item';
    edit.setAttribute('aria-label', `Edit ${item.id || kind}`); edit.addEventListener('click', () => openEdit(kind, item));
    actions.append(pin, edit);
    if (dismiss) {
      const remove = element('button', 'icon-button', '×'); remove.type = 'button'; remove.title = 'Dismiss item';
      remove.setAttribute('aria-label', `Dismiss ${item.id || kind}`);
      remove.addEventListener('click', () => applyOverride(kind, item, 'dismiss'));
      actions.append(remove);
    }
    return actions;
  }

  function renderState() {
    const state = app.state;
    const token = ++app.renderToken;
    dom.sessionTitle.textContent = state.title || 'Untitled discovery';
    dom.stateRevision.textContent = `Analysis rev ${app.revision}`;

    clear(dom.summaryList);
    state.summary.forEach((text) => {
      const row = element('div', 'summary-item');
      row.append(element('span', 'summary-check', '✓'), element('p', '', text));
      dom.summaryList.append(row);
    });
    emptyIf(dom.summaryList, state.summary.length, 'The meeting summary will take shape after the first few points are discussed.');
    dom.summaryCount.textContent = String(state.summary.length);

    clear(dom.requirementsList);
    state.requirements.forEach((item) => dom.requirementsList.append(renderCard('requirement', item)));
    emptyIf(dom.requirementsList, state.requirements.length, 'Captured needs, constraints, and acceptance details will appear here.');
    dom.requirementsCount.textContent = String(state.requirements.length);

    clear(dom.decisionsList);
    state.decisions.forEach((item) => dom.decisionsList.append(renderCard('decision', item)));
    emptyIf(dom.decisionsList, state.decisions.length, 'Confirmed choices will be separated from assumptions.');
    dom.decisionsCount.textContent = String(state.decisions.length);

    clear(dom.visualsList);
    const visuals = [...state.diagrams.map((item) => ['diagram', item]), ...state.metrics.map((item) => ['metric', item])];
    visuals.forEach(([kind, item], index) => {
      const card = renderVisual(kind, item, token, index);
      dom.visualsList.append(card);
    });
    emptyIf(dom.visualsList, visuals.length, 'Flows and metrics are generated when the discussion supports them.');
    dom.visualsCount.textContent = String(visuals.length);

    renderQuestions();
    clear(dom.gapsList);
    state.gaps.forEach((gap) => {
      const row = element('div', 'gap-item');
      row.append(element('span', 'gap-symbol', '!'), element('p', '', gap.text || ''), statusPill(gap.category || 'general'));
      dom.gapsList.append(row);
    });
    emptyIf(dom.gapsList, state.gaps.length, 'No gaps detected yet.');
    dom.gapsCount.textContent = String(state.gaps.length);

    const coverage = calculateCoverage(state);
    dom.coveragePercent.textContent = `${coverage}%`;
    dom.coverageBar.style.width = `${coverage}%`;
    dom.progressTrack.setAttribute('aria-valuenow', String(coverage));
  }

  function emptyIf(container, count, text) {
    if (!count) container.append(element('p', 'section-empty', text));
  }

  function renderCard(kind, item) {
    const card = element('article', `item-card ${app.pinned.has(`${kind}:${item.id}`) ? 'is-pinned' : ''}`);
    const head = element('header', 'item-card-head');
    const id = element('span', 'item-id', item.id || kind.slice(0, 1).toUpperCase());
    head.append(id);
    if (kind === 'requirement') head.append(statusPill(item.status));
    head.append(itemActions(kind, item));
    const text = element('p', 'item-copy', item.text || '');
    card.append(head, text);
    const refs = evidence(item); if (refs) card.append(refs);
    return card;
  }

  function renderVisual(kind, item, token, index) {
    const card = element('article', 'visual-card');
    const header = element('header', 'visual-head');
    const heading = element('h3', '', item.title || (kind === 'diagram' ? 'Process flow' : 'Metric'));
    header.append(heading, itemActions(kind, item));
    const stage = element('div', `visual-stage ${kind}-stage`);
    card.append(header, stage);
    const refs = evidence(item); if (refs) card.append(refs);
    if (kind === 'diagram') renderMermaid(stage, item.mermaid, `diagram-${token}-${index}`);
    else renderMetric(stage, item);
    return card;
  }

  async function renderMermaid(stage, source, id) {
    if (!source || !window.mermaid) {
      diagramFallback(stage, source, 'Diagram preview unavailable'); return;
    }
    try {
      const rendered = await window.mermaid.render(id, source);
      stage.innerHTML = rendered.svg;
      rendered.bindFunctions?.(stage);
    } catch {
      diagramFallback(stage, source, 'This process could not be drawn safely');
    }
  }

  function diagramFallback(stage, source, message) {
    clear(stage);
    const fallback = element('div', 'diagram-fallback');
    fallback.append(element('strong', '', message), element('p', '', 'The source is preserved below for review.'));
    if (source) fallback.append(element('pre', '', source));
    stage.append(fallback);
  }

  function renderMetric(stage, item) {
    const labels = Array.isArray(item.labels) ? item.labels.map(String) : [];
    const values = Array.isArray(item.values) ? item.values.map(Number).map((v) => Number.isFinite(v) ? Math.max(0, v) : 0) : [];
    const size = Math.min(labels.length, values.length);
    if (!size) { stage.append(element('p', 'section-empty', 'No chart values available.')); return; }
    if (item.kind === 'pie') stage.append(pieChart(labels.slice(0, size), values.slice(0, size)));
    else stage.append(barChart(labels.slice(0, size), values.slice(0, size)));
  }

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const chartColors = ['#635bff', '#18a178', '#ef9f27', '#e46072', '#4c7bd9', '#9b6acb'];
  function svgElement(tag, attrs = {}) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }

  function barChart(labels, values) {
    const width = 520, height = 240, left = 42, bottom = 54, top = 18;
    const chart = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Bar chart' });
    const max = Math.max(...values, 1); const plotH = height - bottom - top;
    const step = (width - left - 12) / values.length; const barW = Math.min(54, step * 0.62);
    values.forEach((value, i) => {
      const h = (value / max) * plotH; const x = left + i * step + (step - barW) / 2; const y = top + plotH - h;
      chart.append(svgElement('rect', { x, y, width: barW, height: h, rx: 5, fill: chartColors[i % chartColors.length] }));
      const val = svgElement('text', { x: x + barW / 2, y: Math.max(13, y - 6), 'text-anchor': 'middle', class: 'chart-value' }); val.textContent = String(value); chart.append(val);
      const label = svgElement('text', { x: x + barW / 2, y: height - 24, 'text-anchor': 'middle', class: 'chart-label' }); label.textContent = labels[i].slice(0, 14); chart.append(label);
    });
    chart.append(svgElement('line', { x1: left, y1: top + plotH, x2: width - 8, y2: top + plotH, class: 'chart-axis' }));
    return chart;
  }

  function pieChart(labels, values) {
    const wrapper = element('div', 'pie-layout');
    const chart = svgElement('svg', { viewBox: '0 0 220 220', role: 'img', 'aria-label': 'Pie chart' });
    const total = values.reduce((sum, n) => sum + n, 0);
    let offset = 25;
    if (total <= 0) chart.append(svgElement('circle', { cx: 110, cy: 110, r: 78, fill: '#e8e9e3' }));
    values.forEach((value, i) => {
      const portion = total ? value / total : 0; const end = offset + portion * 100;
      const circle = svgElement('circle', { cx: 110, cy: 110, r: 70, fill: 'none', stroke: chartColors[i % chartColors.length], 'stroke-width': 42,
        'stroke-dasharray': `${portion * 439.82} ${439.82 - portion * 439.82}`, 'stroke-dashoffset': `${-(offset / 100) * 439.82}`, transform: 'rotate(-90 110 110)' });
      chart.append(circle); offset = end;
    });
    const legend = element('ul', 'chart-legend');
    labels.forEach((label, i) => {
      const row = element('li'); const swatch = element('i'); swatch.style.background = chartColors[i % chartColors.length];
      row.append(swatch, element('span', '', label), element('strong', '', String(values[i]))); legend.append(row);
    });
    wrapper.append(chart, legend); return wrapper;
  }

  function renderQuestions() {
    const all = app.state.open_questions;
    const visible = all.filter((q) => app.questionFilter === 'asked'
      ? q.status === 'asked' || q.status === 'answered'
      : (q.status || 'suggested') === app.questionFilter);
    const open = all.filter((q) => q.status === 'suggested' || !q.status).length;
    dom.questionCount.textContent = `${open} open`;
    clear(dom.questionList);
    visible.forEach((question) => dom.questionList.append(renderQuestion(question)));
    if (!visible.length) {
      const empty = element('div', 'empty-state small');
      empty.append(element('span', 'empty-icon sparkle', '✦'), element('h2', '', `No ${app.questionFilter} questions`),
        element('p', '', app.questionFilter === 'suggested' ? 'New prompts will appear as the discussion develops.' : 'Question status changes will appear here.'));
      dom.questionList.append(empty);
    }
  }

  function renderQuestion(question) {
    const card = element('article', 'question-card');
    const meta = element('div', 'question-meta');
    meta.append(statusPill(question.category || 'general'));
    if (question.requirement_id) meta.append(element('span', 'linked-requirement', `↳ ${question.requirement_id}`));
    meta.append(itemActions('question', question));
    card.append(meta, element('p', 'question-copy', question.text || ''));
    const actions = element('div', 'question-actions');
    const status = question.status || 'suggested';
    if (status === 'suggested') {
      actions.append(questionButton('Mark asked', 'asked', question), questionButton('Park', 'parked', question));
    } else if (status === 'asked') {
      actions.append(questionButton('Mark answered', 'answered', question), questionButton('Park', 'parked', question));
    } else if (status === 'answered') {
      actions.append(element('span', 'resolved-label', '✓ Answered'));
    } else if (status === 'parked') {
      actions.append(questionButton('Return to queue', 'suggested', question));
    }
    card.append(actions); return card;
  }

  function questionButton(label, action, question) {
    const button = element('button', 'mini-button', label); button.type = 'button';
    button.addEventListener('click', () => applyOverride('question', question, action)); return button;
  }

  async function applyOverride(kind, item, action, text) {
    if (!app.sessionId) return;
    try {
      const questionStatus = kind === 'question' && ['suggested', 'asked', 'answered', 'parked'].includes(action);
      const payload = {
        kind: kind === 'question' ? 'open_question' : kind,
        id: item.id,
        action: questionStatus ? 'edit' : action,
        ...(questionStatus ? { status: action } : {}),
        ...(text !== undefined ? { text } : {}),
      };
      const result = await api(`/api/session/${encodeURIComponent(app.sessionId)}/override`, {
        method: 'POST', body: JSON.stringify(payload),
      });
      const key = `${kind}:${item.id}`;
      if (action === 'pin') app.pinned.add(key);
      if (result?.state) {
        app.state = normalizeState(result.state);
        app.revision = Number(result.rev) || app.revision;
      } else if (action === 'dismiss') {
        const collection = ITEM_COLLECTIONS[kind];
        if (collection) app.state[collection] = app.state[collection].filter((candidate) => candidate.id !== item.id);
      } else if (questionStatus) {
        item.status = action;
      } else if (action === 'edit' && text !== undefined) item.text = text;
      renderState(); toast('Change saved');
    } catch (error) { showError(`Could not save the change: ${error.message}`); }
  }

  function openEdit(kind, item) {
    app.pendingEdit = { kind, item };
    dom.editText.value = item.text || '';
    dom.editDialog.showModal();
    dom.editText.focus();
  }

  async function saveEdit(event) {
    if (event.submitter?.value === 'cancel') {
      app.pendingEdit = null;
      return;
    }
    event.preventDefault();
    const text = dom.editText.value.trim();
    if (!text || !app.pendingEdit) return;
    const { kind, item } = app.pendingEdit;
    dom.editDialog.close(); app.pendingEdit = null;
    await applyOverride(kind, item, 'edit', text);
  }

  async function exportBrd() {
    if (!app.sessionId) return;
    dom.exportBrd.disabled = true;
    try {
      const result = await api(`/api/session/${encodeURIComponent(app.sessionId)}/brd`, { method: 'POST' });
      const markdown = result.markdown || '';
      const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob); const link = document.createElement('a');
      link.href = url; link.download = `${safeFilename(app.state.title)}-BRD.md`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000); toast('BRD downloaded');
    } catch (error) { showError(`Could not generate the BRD: ${error.message}`); }
    finally { dom.exportBrd.disabled = false; }
  }

  async function showSessions() {
    dom.sessionsDialog.showModal();
    clear(dom.sessionsList); dom.sessionsList.append(element('p', 'section-empty', 'Loading saved sessions…'));
    try {
      const result = await api('/api/sessions');
      const sessions = Array.isArray(result) ? result : (result.sessions || []);
      clear(dom.sessionsList);
      sessions.forEach((session) => {
        const button = element('button', 'session-row'); button.type = 'button';
        const copy = element('span'); copy.append(element('strong', '', session.title || 'Untitled discovery'),
          element('small', '', [session.started || session.updated_at || session.created_at,
            session.utterance_count !== undefined ? `${session.utterance_count} utterances` : ''].filter(Boolean).join(' · ') || session.id));
        button.append(copy, element('span', 'session-arrow', '→'));
        button.addEventListener('click', () => reopenSession(session.id || session.session_id));
        dom.sessionsList.append(button);
      });
      emptyIf(dom.sessionsList, sessions.length, 'No saved sessions yet.');
    } catch (error) {
      clear(dom.sessionsList); dom.sessionsList.append(element('p', 'section-empty', `Could not load sessions: ${error.message}`));
    }
  }

  async function reopenSession(sessionId) {
    if (!sessionId) return;
    await app.capture.stop();
    if (app.socket?.readyState <= WebSocket.OPEN) app.socket.close(1000, 'reopen');
    stopTimer(); resetTranscript();
    try {
      const result = await api(`/api/session/${encodeURIComponent(sessionId)}/state`);
      app.sessionId = sessionId; app.state = normalizeState(result.state || result);
      app.revision = Number(result.rev) || 0; renderState();
      dom.sessionsDialog.close(); setPhase('complete', 'Saved session reopened', 'Review the canvas or export a fresh BRD.');
      toast('Session reopened');
    } catch (error) { showError(`Could not reopen the session: ${error.message}`); }
  }

  function resetTranscript() {
    app.utterances.clear(); app.partialNode = null; clear(dom.transcript);
    const empty = element('div', 'empty-state'); empty.id = 'transcriptEmpty';
    empty.append(element('span', 'empty-icon', '“'), element('h2', '', 'Saved canvas loaded'),
      element('p', '', 'The structured output is ready to review. Start a new session to capture another conversation.'));
    dom.transcript.append(empty); dom.transcriptEmpty = empty; dom.utteranceCount.textContent = '0 captured';
  }

  async function newSession() {
    await app.capture.stop();
    if (app.socket?.readyState <= WebSocket.OPEN) app.socket.close(1000, 'new session');
    stopTimer(); app.sessionId = null; app.state = { ...EMPTY_STATE }; app.revision = 0;
    app.pinned.clear(); resetTranscript(); renderState(); dom.sessionTimer.textContent = '00:00';
    dom.sessionsDialog.close(); setPhase('idle', 'Ready for a new session', 'Your audio and notes stay on this machine.');
  }

  dom.start.addEventListener('click', startSession);
  dom.pause.addEventListener('click', togglePause);
  dom.stop.addEventListener('click', stopSession);
  dom.exportBrd.addEventListener('click', exportBrd);
  $('dismissError').addEventListener('click', hideError);
  $('openSessions').addEventListener('click', showSessions);
  $('newSession').addEventListener('click', newSession);
  $('scrollTranscript').addEventListener('click', () => { dom.transcript.scrollTop = dom.transcript.scrollHeight; });
  dom.editForm.addEventListener('submit', saveEdit);
  document.querySelectorAll('[data-question-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      app.questionFilter = button.dataset.questionFilter;
      document.querySelectorAll('[data-question-filter]').forEach((tab) => {
        const selected = tab === button; tab.classList.toggle('active', selected); tab.setAttribute('aria-pressed', String(selected));
      });
      renderQuestions();
    });
  });
  navigator.mediaDevices?.addEventListener?.('devicechange', refreshDevices);
  refreshDevices();
}
