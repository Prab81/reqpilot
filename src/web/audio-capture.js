/**
 * audio-capture.js — browser mic capture for ReqPilot.
 *
 * getUserMedia (echoCancellation OFF, noiseSuppression ON, autoGainControl ON)
 * → AudioContext requested at 16 kHz → AudioWorklet ('pcm-forwarder' in
 * worklet.js) → Float32Array frames (~4096 samples @ 16 kHz) delivered to
 * `onFrame` on the main thread. The caller sends those as binary WS messages.
 *
 * If the browser ignores the requested 16 kHz context rate, the worklet
 * downsamples with linear interpolation (see worklet.js / resampleLinear).
 *
 * Pause  = stop posting frames + suspend the context, keep the MediaStream.
 * Stop   = full teardown (tracks stopped, context closed).
 */

export const TARGET_RATE = 16000;

/** Build getUserMedia constraints (pure). */
export function micConstraints(deviceId) {
  const audio = {
    echoCancellation: false,
    noiseSuppression: true,
    autoGainControl: true,
  };
  if (deviceId) audio.deviceId = { exact: deviceId };
  return { audio };
}

/** Enumerate audio input devices. Labels are only populated once mic permission is granted. */
export async function listAudioInputs() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return [];
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === 'audioinput');
  } catch {
    return [];
  }
}

/** Map a getUserMedia error to a user-facing message (pure). */
export function micErrorMessage(err) {
  const name = err && err.name;
  switch (name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
      return 'Microphone access was denied. The session stays usable read-only — '
        + 'allow the microphone in the browser address bar and press Start again.';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return 'No microphone was found. Plug one in (or pick another device) and press Start again.';
    case 'NotReadableError':
    case 'TrackStartError':
      return 'The microphone is in use by another application and could not be opened.';
    case 'OverconstrainedError':
      return 'The selected microphone is no longer available. Pick another device.';
    case 'SecurityError':
      return 'Microphone capture requires a secure context (localhost or https).';
    default:
      return `Could not start the microphone: ${(err && err.message) || err}`;
  }
}

export class AudioCapture {
  /**
   * @param {{onFrame?: (frame: Float32Array) => void,
   *          onError?: (err: Error) => void,
   *          workletUrl?: string}} opts
   */
  constructor(opts = {}) {
    this.onFrame = opts.onFrame || (() => {});
    this.onError = opts.onError || (() => {});
    this.workletUrl = opts.workletUrl || './worklet.js';
    this.stream = null;
    this.context = null;
    this.source = null;
    this.node = null;
    this.sink = null;
    this.deviceId = null;
    this.actualRate = null;
    this.state = 'idle'; // idle | recording | paused
  }

  /** Start (or restart on a specific device). Throws on permission/device errors. */
  async start(deviceId) {
    if (this.state === 'paused' && (!deviceId || deviceId === this.deviceId)) {
      return this.resume();
    }
    await this.stop();

    // May throw NotAllowedError etc. — caller shows the banner.
    this.stream = await navigator.mediaDevices.getUserMedia(micConstraints(deviceId));
    this.deviceId = deviceId || null;

    this.context = new AudioContext({ sampleRate: TARGET_RATE });
    this.actualRate = this.context.sampleRate; // may differ if the browser ignored 16000
    await this.context.audioWorklet.addModule(this.workletUrl);

    this.source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, 'pcm-forwarder', {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: 1,
      processorOptions: { targetRate: TARGET_RATE },
    });
    this.node.port.onmessage = (e) => {
      if (this.state === 'recording' && e.data instanceof Float32Array) {
        this.onFrame(e.data);
      }
    };
    // Zero-gain sink keeps the graph pulled without audible monitoring.
    this.sink = this.context.createGain();
    this.sink.gain.value = 0;
    this.source.connect(this.node);
    this.node.connect(this.sink);
    this.sink.connect(this.context.destination);

    if (this.context.state === 'suspended') await this.context.resume();
    this.state = 'recording';

    // Surface unexpected device loss (unplugged mic, revoked permission).
    const track = this.stream.getAudioTracks()[0];
    if (track) {
      track.onended = () => {
        if (this.state !== 'idle') {
          this.state = 'idle';
          this.onError(new Error('Microphone track ended unexpectedly — capture stopped.'));
        }
      };
    }
  }

  /** Stop sending frames + suspend the context; the MediaStream stays open. */
  async pause() {
    if (this.state !== 'recording') return;
    this.state = 'paused';
    if (this.node) this.node.port.postMessage('pause');
    if (this.context && this.context.state === 'running') {
      try { await this.context.suspend(); } catch { /* already closing */ }
    }
  }

  async resume() {
    if (this.state !== 'paused') return;
    if (this.context) {
      try { await this.context.resume(); } catch { /* fall through */ }
    }
    if (this.node) this.node.port.postMessage('resume');
    this.state = 'recording';
  }

  /** Full teardown: flush the worklet, stop tracks, close the context. */
  async stop() {
    const wasActive = this.state !== 'idle';
    this.state = 'idle';
    if (this.node) {
      if (wasActive) {
        try { this.node.port.postMessage('flush'); } catch { /* closed */ }
      }
      try { this.node.disconnect(); } catch { /* noop */ }
      this.node.port.onmessage = null;
      this.node = null;
    }
    if (this.source) { try { this.source.disconnect(); } catch { /* noop */ } this.source = null; }
    if (this.sink) { try { this.sink.disconnect(); } catch { /* noop */ } this.sink = null; }
    if (this.stream) {
      for (const t of this.stream.getTracks()) { t.onended = null; t.stop(); }
      this.stream = null;
    }
    if (this.context) {
      const ctx = this.context;
      this.context = null;
      if (ctx.state !== 'closed') { try { await ctx.close(); } catch { /* noop */ } }
    }
  }

  /** Switch input device, preserving recording/paused state. */
  async switchDevice(deviceId) {
    const was = this.state;
    if (was === 'idle') { this.deviceId = deviceId || null; return; }
    await this.start(deviceId);
    if (was === 'paused') await this.pause();
  }
}
