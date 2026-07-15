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

/** Accept the slightly different transcript payload shapes used by saved/imported sessions. */
export function normalizeTranscript(value) {
  const source = Array.isArray(value) ? value : (value?.utterances || value?.transcript || []);
  return Array.isArray(source) ? source.filter((item) => item && typeof item === 'object').map((item, index) => ({
    utterance_id: item.utterance_id ?? item.id ?? index + 1,
    text: String(item.text || item.content || ''),
    speaker: String(item.speaker || item.speaker_label || ''),
    t0: Number(item.t0 ?? item.start ?? item.start_time ?? 0) || 0,
    t1: Number(item.t1 ?? item.end ?? item.end_time ?? 0) || 0,
  })).filter((item) => item.text.trim()) : [];
}

/** Normalize both {epics:[...]} and flat story responses into one UI contract. */
export function normalizeStories(value) {
  const envelope = value && typeof value === 'object' ? value : {};
  const source = envelope.package && typeof envelope.package === 'object' ? envelope.package : envelope;
  const flatStories = Array.isArray(source.stories) ? source.stories : (Array.isArray(value) ? value : []);
  let epics = Array.isArray(source.epics) ? source.epics.map((epic) => ({
    ...epic,
    stories: Array.isArray(epic?.stories) ? epic.stories : flatStories.filter((story) => story?.epic_id === (epic?.id || epic?.key)),
  })) : [];
  if (!epics.length && flatStories.length) {
    const stories = flatStories;
    epics = [{ id: 'E1', title: 'Unassigned stories', description: '', stories }];
  }
  return epics.filter(Boolean).map((epic, index) => ({
    id: String(epic.id || epic.key || `E${index + 1}`),
    title: String(epic.title || epic.summary || `Epic ${index + 1}`),
    description: String(epic.description || ''),
    stories: (Array.isArray(epic.stories) ? epic.stories : []).filter(Boolean).map((story, storyIndex) => ({
      ...story,
      id: String(story.id || story.key || `S${storyIndex + 1}`),
      title: String(story.title || story.summary || `Story ${storyIndex + 1}`),
      text: String(story.text || story.user_story || story.description || (
        story.as_a && story.i_want && story.so_that ? `As a ${story.as_a}, I want ${story.i_want}, so that ${story.so_that}.` : ''
      )),
      acceptance_criteria: Array.isArray(story.acceptance_criteria) ? story.acceptance_criteria.map((criterion) => {
        if (typeof criterion === 'string') return criterion;
        if (criterion && typeof criterion === 'object') return `Given ${criterion.given || ''}, when ${criterion.when || ''}, then ${criterion.then || ''}.`;
        return '';
      }).filter(Boolean) : [],
      evidence_utterances: Array.isArray(story.evidence_utterances) ? story.evidence_utterances : [],
    })),
  }));
}

/** Rasterize a rendered SVG element to base64 PNG data (no data-URL prefix).
 * Mermaid SVGs carry self-contained inline styles, so the canvas stays untainted. */
export async function svgToPngBase64(svgElement, scale = 2, background = '#ffffff') {
  const serialized = new XMLSerializer().serializeToString(svgElement);
  const url = URL.createObjectURL(new Blob([serialized], { type: 'image/svg+xml;charset=utf-8' }));
  try {
    const image = await new Promise((resolve, reject) => {
      const loader = new Image();
      loader.onload = () => resolve(loader);
      loader.onerror = () => reject(new Error('The diagram SVG could not be rasterized.'));
      loader.src = url;
    });
    const viewBox = (svgElement.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
    const rect = svgElement.getBoundingClientRect();
    const baseWidth = rect.width || (viewBox.length === 4 && viewBox[2]) || image.width || 640;
    const baseHeight = rect.height || (viewBox.length === 4 && viewBox[3]) || image.height || 400;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(baseWidth * scale));
    canvas.height = Math.max(1, Math.round(baseHeight * scale));
    const context = canvas.getContext('2d');
    context.fillStyle = background;
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/png').split(',')[1];
  } finally {
    URL.revokeObjectURL(url);
  }
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
    entryView: $('entryView'), sessionShell: $('sessionShell'), controlStrip: $('controlStrip'),
    importDialog: $('importDialog'), importForm: $('importForm'), importText: $('importText'),
    importTitle: $('importTitle'), transcriptFile: $('transcriptFile'), fileChoice: $('fileChoice'),
    importProgress: $('importProgress'), submitImport: $('submitImport'),
    settingsDialog: $('settingsDialog'), configStatus: $('configStatus'), providerBadge: $('providerBadge'),
    privacyTitle: $('privacyTitle'), privacyCopy: $('privacyCopy'), sessionModeBadge: $('sessionModeBadge'),
    liveView: $('liveView'), brdView: $('brdView'), storiesView: $('storiesView'), jiraView: $('jiraView'),
    brdPreview: $('brdPreview'), brdStatus: $('brdStatus'), brdMeta: $('brdMeta'),
    exportBrdDocx: $('exportBrdDocx'), storiesList: $('storiesList'), storySummary: $('storySummary'),
    exportStoriesDocx: $('exportStoriesDocx'), exportStoriesCsv: $('exportStoriesCsv'),
    storyNavCount: $('storyNavCount'), mergeStories: $('mergeStories'), jiraReadiness: $('jiraReadiness'),
    jiraProject: $('jiraProject'), jiraScope: $('jiraScope'), jiraPreview: $('jiraPreview'),
    jiraPreviewCount: $('jiraPreviewCount'), confirmJira: $('confirmJira'), exportJira: $('exportJira'),
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
    mode: null,
    view: 'live',
    brd: '',
    epics: [],
    selectedStories: new Set(),
    config: null,
    jiraPlan: null,
    unavailable: new Set(),
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
    dom.exportBrd.disabled = !app.sessionId || app.unavailable.has('brd');
  }

  async function api(path, options = {}) {
    const headers = { Accept: 'application/json', ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const response = await fetch(path, { ...options, headers });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try { detail = (await response.json()).detail || detail; } catch { /* use status */ }
      throw new Error(detail);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function unavailable(error) {
    return /(?:404|405|501)\b/.test(String(error?.message || ''));
  }

  function showSessionShell(mode = app.mode || 'saved') {
    app.mode = mode;
    dom.entryView.hidden = true;
    dom.sessionShell.hidden = false;
    dom.sessionShell.dataset.mode = mode;
    dom.controlStrip.hidden = mode !== 'live';
    dom.sessionModeBadge.textContent = mode === 'import' ? 'Imported transcript' : mode === 'live' ? 'Live capture' : 'Saved session';
    switchView('live');
  }

  function showEntry() {
    if (app.phase === 'recording' || app.phase === 'paused') {
      showError('Stop or pause the live session before returning home.');
      return;
    }
    dom.sessionShell.hidden = true;
    dom.entryView.hidden = false;
    dom.sessionTitle.textContent = app.sessionId ? (app.state.title || 'Untitled discovery') : 'No session open';
  }

  function switchView(name) {
    app.view = name;
    const views = { live: dom.liveView, brd: dom.brdView, stories: dom.storiesView, jira: dom.jiraView };
    Object.entries(views).forEach(([key, node]) => {
      node.hidden = key !== name;
      node.classList.toggle('active-view', key === name);
    });
    document.querySelectorAll('[data-view]').forEach((button) => {
      const active = button.dataset.view === name;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    dom.controlStrip.hidden = name !== 'live' || app.mode !== 'live';
    if (name === 'brd' && app.sessionId && !app.brd) loadBrd(false);
    if (name === 'stories' && app.sessionId && !app.epics.length) loadStories();
    if (name === 'jira') renderJiraReadiness();
  }

  async function ensureSession() {
    if (app.sessionId) return app.sessionId;
    const created = await api('/api/session', { method: 'POST' });
    app.sessionId = created.id || created.session_id;
    if (!app.sessionId) throw new Error('The server did not return a session id.');
    return app.sessionId;
  }

  async function importTranscript(event) {
    event.preventDefault();
    hideError();
    const file = dom.transcriptFile.files?.[0];
    const textValue = dom.importText.value.trim();
    if (!file && !textValue) {
      showError('Choose a TXT, VTT, or DOCX file, or paste transcript text.');
      dom.importText.focus();
      return;
    }
    const allowed = ['txt', 'vtt', 'docx'];
    if (file && !allowed.includes((file.name.split('.').pop() || '').toLowerCase())) {
      showError('That file type is not supported. Choose TXT, VTT, or DOCX.');
      return;
    }
    const form = new FormData();
    if (file) form.append('file', file);
    else if (textValue) form.append('text', textValue);
    form.append('filename', file?.name || 'pasted-transcript.txt');
    if (dom.importTitle.value.trim()) form.append('title', dom.importTitle.value.trim());
    dom.submitImport.disabled = true;
    dom.importProgress.hidden = false;
    const bar = dom.importProgress.querySelector('.progress-track span');
    const meter = dom.importProgress.querySelector('[role="progressbar"]');
    bar.style.width = '28%'; meter.setAttribute('aria-valuenow', '28');
    try {
      const result = await api('/api/session/import', { method: 'POST', body: form });
      bar.style.width = '82%'; meter.setAttribute('aria-valuenow', '82');
      app.sessionId = result.id || result.session_id || result.session?.id;
      if (!app.sessionId) throw new Error('The import completed without a session id.');
      app.state = normalizeState(result.state || result.session?.state);
      app.revision = Number(result.rev || result.session?.rev) || 0;
      app.brd = String(result.markdown || result.brd?.markdown || '');
      app.epics = normalizeStories(result.stories || result);
      await Promise.allSettled([loadTranscript(), app.state.requirements.length ? Promise.resolve() : loadState()]);
      bar.style.width = '100%'; meter.setAttribute('aria-valuenow', '100');
      renderState(); renderBrd(); renderStories();
      dom.importDialog.close();
      showSessionShell('import');
      setPhase('complete', 'Transcript analyzed', 'The canvas, BRD, and delivery workspace are ready to review.');
      toast('Transcript imported');
    } catch (error) {
      if (unavailable(error)) app.unavailable.add('import');
      showError(`Could not import the transcript: ${error.message}`);
    } finally {
      dom.submitImport.disabled = false;
      window.setTimeout(() => { dom.importProgress.hidden = true; bar.style.width = '0'; }, 400);
    }
  }

  async function loadState() {
    if (!app.sessionId) return;
    const result = await api(`/api/session/${encodeURIComponent(app.sessionId)}/state`);
    app.state = normalizeState(result.state || result);
    app.revision = Number(result.rev) || app.revision;
    renderState();
  }

  async function loadTranscript() {
    if (!app.sessionId) return;
    try {
      const result = await api(`/api/session/${encodeURIComponent(app.sessionId)}/transcript`);
      const utterances = normalizeTranscript(result);
      resetTranscript('No transcript content was saved for this session.');
      utterances.forEach(renderFinal);
    } catch (error) {
      if (unavailable(error)) {
        app.unavailable.add('transcript');
        resetTranscript('Transcript restore is unavailable in this server version. The structured canvas is still ready.');
      } else throw error;
    }
  }

  function markdownToFragment(markdown) {
    const fragment = document.createDocumentFragment();
    let list = null;
    String(markdown || '').split(/\r?\n/).forEach((raw) => {
      const line = raw.trimEnd();
      const heading = /^(#{1,4})\s+(.+)$/.exec(line);
      const bullet = /^[-*]\s+(.+)$/.exec(line);
      if (heading) {
        list = null;
        fragment.append(element(`h${Math.min(4, heading[1].length + 1)}`, '', heading[2]));
      } else if (bullet) {
        if (!list) { list = element('ul'); fragment.append(list); }
        list.append(element('li', '', bullet[1]));
      } else if (/^```/.test(line)) {
        list = null;
      } else if (line.trim()) {
        list = null;
        fragment.append(element('p', '', line.replace(/\*\*/g, '')));
      } else list = null;
    });
    return fragment;
  }

  function renderBrd() {
    clear(dom.brdPreview);
    if (!app.brd) {
      const empty = element('div', 'artifact-empty');
      empty.append(element('span', '', '▤'), element('h2', '', 'Your BRD will appear here'), element('p', '', 'Generate the document when the transcript has been analyzed.'));
      dom.brdPreview.append(empty);
      dom.brdStatus.textContent = 'Not generated';
      dom.brdMeta.textContent = 'Generate a BRD when the transcript has been analyzed.';
      return;
    }
    dom.brdPreview.append(markdownToFragment(app.brd));
    dom.brdStatus.textContent = 'Ready to review';
    dom.brdMeta.textContent = `${app.brd.split(/\r?\n/).filter(Boolean).length} document lines · analysis rev ${app.revision}`;
    $('brdNavState').textContent = 'Ready';
  }

  async function loadBrd(regenerate = false) {
    if (!app.sessionId || app.unavailable.has('brd')) return;
    $('refreshBrd').disabled = true;
    dom.brdStatus.textContent = regenerate ? 'Regenerating…' : 'Loading…';
    try {
      const result = await api(`/api/session/${encodeURIComponent(app.sessionId)}/brd`, { method: 'POST' });
      app.brd = String(result.markdown || result.brd || '');
      renderBrd();
      dom.exportBrdDocx.href = `/api/session/${encodeURIComponent(app.sessionId)}/brd.docx`;
    } catch (error) {
      if (unavailable(error)) {
        app.unavailable.add('brd');
        dom.brdStatus.textContent = 'Unavailable';
        dom.brdMeta.textContent = 'BRD generation is not available in this server version.';
        dom.exportBrd.disabled = true; dom.exportBrdDocx.hidden = true;
      } else showError(`Could not generate the BRD: ${error.message}`);
    } finally { $('refreshBrd').disabled = false; }
  }

  function flattenStories() {
    return app.epics.flatMap((epic) => epic.stories.map((story) => ({ epic, story })));
  }

  async function loadStories() {
    if (!app.sessionId || app.unavailable.has('stories')) return;
    try {
      const result = await api(`/api/session/${encodeURIComponent(app.sessionId)}/stories`);
      app.epics = normalizeStories(result);
      renderStories();
    } catch (error) {
      if (unavailable(error)) {
        app.unavailable.add('stories');
        $('generateStories').disabled = true;
        clear(dom.storiesList); dom.storiesList.append(element('p', 'unavailable-note', 'Story generation is unavailable in this server version.'));
      } else showError(`Could not load stories: ${error.message}`);
    }
  }

  async function generateStories() {
    if (!app.sessionId) return;
    const buttons = document.querySelectorAll('#generateStories, [data-generate-stories]');
    buttons.forEach((button) => { button.disabled = true; });
    try {
      const result = await api(`/api/session/${encodeURIComponent(app.sessionId)}/stories/generate`, { method: 'POST' });
      app.epics = normalizeStories(result);
      renderStories(); toast('Backlog generated');
    } catch (error) {
      if (unavailable(error)) { app.unavailable.add('stories'); buttons.forEach((button) => { button.hidden = true; }); }
      showError(`Could not generate stories: ${error.message}`);
    } finally { buttons.forEach((button) => { button.disabled = false; }); }
  }

  function renderStories() {
    clear(dom.storiesList);
    const flat = flattenStories();
    dom.storySummary.textContent = `${app.epics.length} epic${app.epics.length === 1 ? '' : 's'} · ${flat.length} stor${flat.length === 1 ? 'y' : 'ies'}`;
    dom.storyNavCount.textContent = String(flat.length);
    const exportable = Boolean(app.sessionId) && flat.length > 0 && !app.unavailable.has('stories');
    dom.exportStoriesDocx.disabled = !exportable;
    dom.exportStoriesCsv.disabled = !exportable;
    app.epics.forEach((epic) => {
      const section = element('section', 'epic-group');
      const header = element('header', 'epic-header');
      const copy = element('div'); copy.append(element('span', 'item-id', epic.id), element('h2', '', epic.title));
      header.append(copy, element('span', 'count-badge', `${epic.stories.length} stories`));
      section.append(header);
      if (epic.description) section.append(element('p', 'epic-description', epic.description));
      epic.stories.forEach((story) => section.append(renderStory(epic, story)));
      dom.storiesList.append(section);
    });
    if (!flat.length) {
      const empty = element('div', 'artifact-empty');
      empty.append(element('span', '', '◇'), element('h2', '', 'Turn requirements into a ready backlog'), element('p', '', 'Stories include acceptance criteria and transcript evidence.'));
      const generate = element('button', 'button button-primary', 'Generate epics & stories'); generate.type = 'button'; generate.addEventListener('click', generateStories); empty.append(generate);
      dom.storiesList.append(empty);
    }
    updateStorySelection();
  }

  function renderStory(epic, story) {
    const card = element('article', 'story-card'); card.dataset.storyId = story.id;
    const select = element('input'); select.type = 'checkbox'; select.checked = app.selectedStories.has(story.id); select.setAttribute('aria-label', `Select ${story.id}`);
    select.addEventListener('change', () => { if (select.checked) app.selectedStories.add(story.id); else app.selectedStories.delete(story.id); updateStorySelection(); });
    const body = element('div', 'story-body');
    const head = element('header'); head.append(element('span', 'story-key', story.id), element('h3', '', story.title));
    const actions = element('div', 'story-actions');
    const edit = element('button', 'icon-button', '✎'); edit.type = 'button'; edit.setAttribute('aria-label', `Edit ${story.id}`); edit.addEventListener('click', () => openStoryEdit(epic, story));
    const remove = element('button', 'icon-button', '×'); remove.type = 'button'; remove.setAttribute('aria-label', `Delete ${story.id}`); remove.addEventListener('click', () => storyOverride('delete', [story.id]));
    actions.append(edit, remove); head.append(actions); body.append(head);
    body.append(element('p', 'story-text', story.text));
    if (story.acceptance_criteria.length) {
      const block = element('div', 'acceptance-block'); block.append(element('strong', '', 'Acceptance criteria'));
      const list = element('ul'); story.acceptance_criteria.forEach((criterion) => list.append(element('li', '', criterion))); block.append(list); body.append(block);
    }
    const refs = evidence(story); if (refs) body.append(refs);
    card.append(select, body); return card;
  }

  function updateStorySelection() {
    const count = app.selectedStories.size;
    dom.mergeStories.disabled = count < 2;
    dom.mergeStories.textContent = count >= 2 ? `Merge ${count} selected` : 'Merge selected';
  }

  function openStoryEdit(epic, story) {
    app.pendingEdit = { kind: 'story', item: story, epic };
    dom.editText.value = story.text || story.title || '';
    dom.editDialog.showModal(); dom.editText.focus();
  }

  async function storyOverride(action, ids, text) {
    if (!app.sessionId) return;
    try {
      const result = await api(`/api/session/${encodeURIComponent(app.sessionId)}/stories/override`, {
        method: 'POST', body: JSON.stringify({ action, ids, id: ids[0], ...(text !== undefined ? { text } : {}) }),
      });
      app.epics = normalizeStories(result.stories || result);
      app.selectedStories.clear(); renderStories(); toast('Backlog updated');
    } catch (error) { showError(`Could not update the backlog: ${error.message}`); }
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = filename; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function downloadBacklog(extension) {
    if (!app.sessionId) return;
    const button = extension === 'csv' ? dom.exportStoriesCsv : dom.exportStoriesDocx;
    button.disabled = true;
    try {
      const response = await fetch(`/api/session/${encodeURIComponent(app.sessionId)}/stories.${extension}`);
      if (!response.ok) {
        let detail = `${response.status} ${response.statusText}`;
        try { detail = (await response.json()).detail || detail; } catch { /* use status */ }
        throw new Error(detail);
      }
      downloadBlob(await response.blob(), `reqpilot-backlog-${app.sessionId}.${extension}`);
      toast(extension === 'csv' ? 'CSV backlog downloaded' : 'Word backlog downloaded');
    } catch (error) { showError(`Could not download the backlog: ${error.message}`); }
    finally { button.disabled = false; }
  }

  async function collectDiagramImages() {
    const stages = document.querySelectorAll('#visualsList .diagram-stage[data-diagram-id]');
    const diagrams = [];
    for (const stage of stages) {
      const svg = stage.querySelector('svg');
      if (!svg || !stage.dataset.diagramId) continue;
      try {
        diagrams.push({ id: stage.dataset.diagramId, png_base64: await svgToPngBase64(svg) });
      } catch { /* the server keeps the text-only diagram line for this one */ }
    }
    return diagrams;
  }

  async function exportBrdDocxWithDiagrams(event) {
    event.preventDefault();
    if (!app.sessionId || app.unavailable.has('brd')) return;
    dom.exportBrdDocx.setAttribute('aria-disabled', 'true');
    try {
      const diagrams = await collectDiagramImages();
      const response = await fetch(`/api/session/${encodeURIComponent(app.sessionId)}/brd.docx`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ diagrams }),
      });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      downloadBlob(await response.blob(), `${safeFilename(app.state.title)}-BRD.docx`);
      toast(diagrams.length ? 'BRD downloaded with rendered diagrams' : 'BRD downloaded');
    } catch (error) { showError(`Could not download the BRD document: ${error.message}`); }
    finally { dom.exportBrdDocx.removeAttribute('aria-disabled'); }
  }

  function statusValue(value) {
    if (typeof value === 'boolean') return value;
    if (value && typeof value === 'object') return Boolean(value.configured ?? value.ready ?? value.available);
    return ['ready', 'configured', 'available', 'connected', 'local'].includes(String(value || '').toLowerCase());
  }

  async function loadConfig() {
    try {
      app.config = await api('/api/config/status');
      renderConfig(); renderJiraReadiness();
      const provider = app.config.provider?.name || app.config.provider || 'Configured provider';
      const local = statusValue(app.config.local_only ?? app.config.local ?? app.config.offline);
      dom.providerBadge.textContent = `${local ? 'Local' : 'Provider'} · ${provider}`;
      dom.providerBadge.classList.add('ready');
      dom.privacyTitle.textContent = local ? 'Local-only mode is active' : 'Local-first capture';
      dom.privacyCopy.textContent = local ? 'Transcripts and analysis stay on this machine.' : 'Audio stays local; configured analysis requests may use a cloud provider.';
    } catch (error) {
      app.unavailable.add('config');
      dom.providerBadge.textContent = 'Status unavailable';
      renderConfig();
    }
  }

  function sanitizedConfigRows(config) {
    const provider = config?.provider?.name || config?.provider || 'Not reported';
    return [
      ['Analysis provider', String(provider), statusValue(config?.provider?.configured ?? config?.provider_ready ?? true)],
      ['Local-only mode', statusValue(config?.local_only ?? config?.local ?? config?.offline) ? 'Enabled' : 'Not enabled', true],
      ['Speech engine', String(config?.asr?.status || config?.asr || config?.speech || 'Not reported'), statusValue(config?.asr?.ready ?? config?.asr_ready ?? config?.asr)],
      ['Jira connection', statusValue(config?.jira?.configured ?? config?.jira_configured) ? 'Configured' : 'Not configured', statusValue(config?.jira?.configured ?? config?.jira_configured)],
    ];
  }

  function renderConfig() {
    clear(dom.configStatus);
    if (!app.config) {
      dom.configStatus.append(element('p', 'unavailable-note', 'Runtime status is unavailable. ReqPilot will keep unsupported actions disabled.'));
      return;
    }
    sanitizedConfigRows(app.config).forEach(([label, value, ready]) => {
      const row = element('div', 'config-row');
      row.append(element('span', `config-indicator ${ready ? 'ready' : 'pending'}`, ready ? '✓' : '!'));
      const copy = element('div'); copy.append(element('strong', '', label), element('span', '', value)); row.append(copy); dom.configStatus.append(row);
    });
  }

  function renderJiraReadiness() {
    clear(dom.jiraReadiness);
    const storyCount = flattenStories().length;
    const jiraReady = statusValue(app.config?.jira?.configured ?? app.config?.jira_configured);
    const checks = [
      [jiraReady, 'Jira connection configured', 'Add Jira configuration on the server'],
      [storyCount > 0, `${storyCount} backlog item${storyCount === 1 ? '' : 's'} ready`, 'Generate stories first'],
      [Boolean(dom.jiraProject.value.trim()), 'Destination project entered', 'Enter a destination project key'],
    ];
    checks.forEach(([ready, yes, no]) => {
      const row = element('p', `check-row ${ready ? 'ready' : 'pending'}`);
      row.append(element('span', '', ready ? '✓' : '•'), document.createTextNode(ready ? yes : no)); dom.jiraReadiness.append(row);
    });
    $('previewJira').disabled = !storyCount || !dom.jiraProject.value.trim() || app.unavailable.has('jira');
  }

  async function previewJira() {
    if (!app.sessionId) return;
    const project_key = dom.jiraProject.value.trim().toUpperCase();
    try {
      const result = await api(`/api/session/${encodeURIComponent(app.sessionId)}/jira/preview`, {
        method: 'POST', body: JSON.stringify({ project_key, scope: dom.jiraScope.value, story_ids: [...app.selectedStories] }),
      });
      app.jiraPlan = result;
      const issues = Array.isArray(result.issues) ? result.issues : Array.isArray(result.preview) ? result.preview : [];
      clear(dom.jiraPreview);
      issues.forEach((issue, index) => {
        const row = element('article', 'jira-issue');
        row.append(element('span', 'issue-type', String(issue.issue_type || issue.type || 'Story')), element('strong', '', issue.summary || issue.title || `Issue ${index + 1}`));
        if (issue.parent || issue.epic) row.append(element('small', '', `Linked to ${issue.parent || issue.epic}`));
        dom.jiraPreview.append(row);
      });
      emptyIf(dom.jiraPreview, issues.length, 'The server returned an empty export plan.');
      dom.jiraPreviewCount.textContent = String(issues.length);
      dom.confirmJira.checked = false; dom.exportJira.disabled = true;
    } catch (error) {
      if (unavailable(error)) { app.unavailable.add('jira'); $('previewJira').disabled = true; }
      showError(`Could not build the Jira preview: ${error.message}`);
    }
  }

  async function exportJira() {
    if (!app.sessionId || !app.jiraPlan || !dom.confirmJira.checked) return;
    dom.exportJira.disabled = true;
    try {
      const result = await api(`/api/session/${encodeURIComponent(app.sessionId)}/jira/export`, {
        method: 'POST', body: JSON.stringify({ project_key: dom.jiraProject.value.trim().toUpperCase(), preview: app.jiraPlan }),
      });
      toast(`${Number(result.created_count ?? result.created?.length ?? 0)} Jira issues created`);
      dom.confirmJira.checked = false;
    } catch (error) { showError(`Jira export failed: ${error.message}`); }
    finally { dom.exportJira.disabled = !dom.confirmJira.checked; }
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
    meta.append(element('span', '', partial ? 'Listening…' : (message.speaker || `Utterance ${message.utterance_id ?? ''}`)));
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
    if (kind === 'diagram') {
      stage.dataset.diagramId = String(item.id || '');
      renderMermaid(stage, item.mermaid, `diagram-${token}-${index}`);
    } else renderMetric(stage, item);
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
    if (kind === 'story') await storyOverride('edit', [item.id], text);
    else await applyOverride(kind, item, 'edit', text);
  }

  async function exportBrd() {
    if (!app.sessionId) return;
    dom.exportBrd.disabled = true;
    try {
      if (!app.brd) await loadBrd(true);
      const markdown = app.brd;
      if (!markdown) throw new Error('No BRD content is available yet.');
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
      app.sessionId = sessionId; app.brd = ''; app.epics = []; app.selectedStories.clear();
      const result = await api(`/api/session/${encodeURIComponent(sessionId)}/state`);
      app.state = normalizeState(result.state || result); app.revision = Number(result.rev) || 0;
      await Promise.allSettled([loadTranscript(), loadStories(), loadBrd(false)]);
      renderState(); renderStories(); renderBrd(); showSessionShell('saved');
      dom.sessionsDialog.close(); setPhase('complete', 'Saved session reopened', 'Transcript, canvas, document, and backlog are restored.');
      toast('Session reopened');
    } catch (error) { showError(`Could not reopen the session: ${error.message}`); }
  }

  function resetTranscript(message = 'The structured output is ready to review. Start a new session to capture another conversation.') {
    app.utterances.clear(); app.partialNode = null; clear(dom.transcript);
    const empty = element('div', 'empty-state'); empty.id = 'transcriptEmpty';
    empty.append(element('span', 'empty-icon', '“'), element('h2', '', 'Saved canvas loaded'),
      element('p', '', message));
    dom.transcript.append(empty); dom.transcriptEmpty = empty; dom.utteranceCount.textContent = '0 captured';
  }

  async function newSession() {
    await app.capture.stop();
    if (app.socket?.readyState <= WebSocket.OPEN) app.socket.close(1000, 'new session');
    stopTimer(); app.sessionId = null; app.state = { ...EMPTY_STATE }; app.revision = 0; app.brd = ''; app.epics = [];
    app.pinned.clear(); app.selectedStories.clear(); resetTranscript(); renderState(); renderStories(); renderBrd(); dom.sessionTimer.textContent = '00:00';
    dom.sessionsDialog.close(); setPhase('idle', 'Ready for a new session', 'Your audio and notes stay on this machine.'); showEntry();
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
  $('goHome').addEventListener('click', showEntry);
  $('chooseLive').addEventListener('click', () => showSessionShell('live'));
  $('chooseImport').addEventListener('click', () => dom.importDialog.showModal());
  document.querySelectorAll('[data-close-dialog]').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
  dom.importForm.addEventListener('submit', importTranscript);
  dom.transcriptFile.addEventListener('change', () => { dom.fileChoice.textContent = dom.transcriptFile.files?.[0]?.name || 'No file selected'; });
  $('dropZone').addEventListener('dragover', (event) => { event.preventDefault(); $('dropZone').classList.add('is-dragging'); });
  $('dropZone').addEventListener('dragleave', () => $('dropZone').classList.remove('is-dragging'));
  $('dropZone').addEventListener('drop', (event) => {
    event.preventDefault(); $('dropZone').classList.remove('is-dragging');
    if (event.dataTransfer.files?.length) { dom.transcriptFile.files = event.dataTransfer.files; dom.fileChoice.textContent = event.dataTransfer.files[0].name; }
  });
  document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
  $('refreshBrd').addEventListener('click', () => loadBrd(true));
  $('generateStories').addEventListener('click', generateStories);
  dom.exportStoriesDocx.addEventListener('click', () => downloadBacklog('docx'));
  dom.exportStoriesCsv.addEventListener('click', () => downloadBacklog('csv'));
  dom.exportBrdDocx.addEventListener('click', exportBrdDocxWithDiagrams);
  document.querySelectorAll('[data-generate-stories]').forEach((button) => button.addEventListener('click', generateStories));
  $('selectAllStories').addEventListener('click', () => { flattenStories().forEach(({ story }) => app.selectedStories.add(story.id)); renderStories(); });
  dom.mergeStories.addEventListener('click', () => storyOverride('merge', [...app.selectedStories]));
  $('openSettings').addEventListener('click', () => { renderConfig(); dom.settingsDialog.showModal(); });
  dom.jiraProject.addEventListener('input', renderJiraReadiness);
  $('previewJira').addEventListener('click', previewJira);
  dom.confirmJira.addEventListener('change', () => { dom.exportJira.disabled = !dom.confirmJira.checked || !app.jiraPlan; });
  dom.exportJira.addEventListener('click', exportJira);
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
  loadConfig();
}
