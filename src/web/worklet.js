/**
 * worklet.js — AudioWorkletProcessor for ReqPilot mic capture.
 *
 * Loaded by audio-capture.js via audioWorklet.addModule() (worklet modules are
 * ES modules, so `export` is legal here). Forwards input channel 0 as
 * Float32Array frames of ~4096 samples at 16 kHz to the main thread.
 * If the AudioContext runs at a rate other than 16 kHz (the browser is allowed
 * to ignore the requested sampleRate), frames are downsampled here with
 * linear interpolation before posting.
 *
 * `resampleLinear` is a pure function and is exported so it can be unit-tested
 * outside the worklet (e.g. `import { resampleLinear } from './worklet.js'`
 * in Node). The processor class is only defined when running inside a real
 * AudioWorkletGlobalScope, so importing this file elsewhere is safe.
 */

export const TARGET_RATE = 16000;
export const TARGET_CHUNK = 4096; // ~256 ms at 16 kHz

/**
 * Linearly resample a Float32Array from `inRate` to `outRate`.
 * Pure: no side effects, returns a new array (or a copy when rates match).
 *
 * @param {Float32Array|number[]} input  mono PCM samples
 * @param {number} inRate   input sample rate in Hz (> 0)
 * @param {number} outRate  output sample rate in Hz (> 0)
 * @returns {Float32Array}
 */
export function resampleLinear(input, inRate, outRate) {
  const src = input instanceof Float32Array ? input : Float32Array.from(input);
  if (!(inRate > 0) || !(outRate > 0)) {
    throw new RangeError(`resampleLinear: invalid rates ${inRate} -> ${outRate}`);
  }
  if (inRate === outRate || src.length === 0) return src.slice();

  const ratio = inRate / outRate;
  const outLen = Math.max(1, Math.round(src.length / ratio));
  const out = new Float32Array(outLen);
  const last = src.length - 1;
  for (let i = 0; i < outLen; i++) {
    const pos = Math.min(i * ratio, last);
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, last);
    const frac = pos - i0;
    out[i] = src[i0] + (src[i1] - src[i0]) * frac;
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Processor — only inside an AudioWorkletGlobalScope                  */
/* ------------------------------------------------------------------ */

if (typeof AudioWorkletProcessor !== 'undefined' && typeof registerProcessor === 'function') {
  class PcmForwarder extends AudioWorkletProcessor {
    constructor(options) {
      super();
      const opts = (options && options.processorOptions) || {};
      this._targetRate = opts.targetRate || TARGET_RATE;
      // `sampleRate` is a global in AudioWorkletGlobalScope = the context rate.
      this._inRate = sampleRate;
      // Buffer enough input samples that one flush yields ~TARGET_CHUNK output samples.
      this._inChunk = Math.max(128, Math.round(TARGET_CHUNK * this._inRate / this._targetRate));
      this._chunks = [];
      this._buffered = 0;
      this._paused = false;
      this.port.onmessage = (e) => {
        if (e.data === 'pause') this._paused = true;
        else if (e.data === 'resume') this._paused = false;
        else if (e.data === 'flush') this._flush();
      };
    }

    _flush() {
      if (this._buffered === 0) return;
      const merged = new Float32Array(this._buffered);
      let off = 0;
      for (const c of this._chunks) { merged.set(c, off); off += c.length; }
      this._chunks = [];
      this._buffered = 0;
      const out = this._inRate === this._targetRate
        ? merged
        : resampleLinear(merged, this._inRate, this._targetRate);
      this.port.postMessage(out, [out.buffer]);
    }

    process(inputs) {
      if (this._paused) return true;
      const channel = inputs[0] && inputs[0][0];
      if (!channel || channel.length === 0) return true;
      this._chunks.push(new Float32Array(channel)); // copy — input buffers are reused
      this._buffered += channel.length;
      if (this._buffered >= this._inChunk) this._flush();
      return true;
    }
  }

  registerProcessor('pcm-forwarder', PcmForwarder);
}
