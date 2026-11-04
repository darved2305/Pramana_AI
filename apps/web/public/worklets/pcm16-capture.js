/*
 * AudioWorklet: microphone -> 16 kHz mono PCM16 (s16le) in 1,024-byte frames (512 samples),
 * the frame size Gnani Prisma's realtime API expects.
 *
 * The context usually runs at 48 kHz or 44.1 kHz. Input is low-pass filtered (windowed-sinc
 * FIR, cutoff just under the 8 kHz Nyquist limit of the target rate) before fractional
 * resampling, so speech above 8 kHz does not alias into the band Prisma hears. At 16 kHz the
 * samples pass straight through.
 *
 * Messages to the main thread: ArrayBuffer (one frame, transferred) and
 * {type: "level", rms} about every 50 ms for a level meter.
 * Messages from the main thread: {type: "flush"} sends the partial frame, zero-padded.
 */
const TARGET_RATE = 16000;
const FRAME_SAMPLES = 512;
const TAPS = 63;

function lowpassKernel(inRate) {
  const cutoff = (0.45 * TARGET_RATE) / inRate; // normalised to the input rate
  const mid = (TAPS - 1) / 2;
  const k = new Float32Array(TAPS);
  let sum = 0;
  for (let i = 0; i < TAPS; i++) {
    const x = i - mid;
    const sinc = x === 0 ? 2 * cutoff : Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x);
    const blackman =
      0.42 - 0.5 * Math.cos((2 * Math.PI * i) / (TAPS - 1)) + 0.08 * Math.cos((4 * Math.PI * i) / (TAPS - 1));
    k[i] = sinc * blackman;
    sum += k[i];
  }
  for (let i = 0; i < TAPS; i++) k[i] /= sum; // unity gain at DC
  return k;
}

class Pcm16CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.inRate = sampleRate;
    this.step = this.inRate / TARGET_RATE;
    this.passthrough = Math.abs(this.step - 1) < 1e-9;
    this.kernel = this.passthrough ? null : lowpassKernel(this.inRate);
    this.history = new Float32Array(TAPS); // ring buffer of raw input
    this.hpos = 0;
    this.prev = 0; // last filtered sample (for interpolation)
    this.curr = 0;
    this.t = 0; // position of the next output sample, in input samples since `curr`
    this.frame = new Int16Array(FRAME_SAMPLES);
    this.fill = 0;
    this.levelAcc = 0;
    this.levelN = 0;
    this.port.onmessage = (e) => {
      if (e.data && e.data.type === "flush") this.flush();
    };
  }

  filtered(x) {
    this.history[this.hpos] = x;
    this.hpos = (this.hpos + 1) % TAPS;
    let acc = 0;
    let j = this.hpos;
    for (let i = 0; i < TAPS; i++) {
      acc += this.kernel[i] * this.history[j];
      j = j + 1 === TAPS ? 0 : j + 1;
    }
    return acc;
  }

  emit(v) {
    const c = v < -1 ? -1 : v > 1 ? 1 : v;
    this.frame[this.fill++] = c < 0 ? c * 0x8000 : c * 0x7fff;
    this.levelAcc += c * c;
    this.levelN++;
    if (this.fill === FRAME_SAMPLES) {
      const out = this.frame.buffer;
      this.port.postMessage(out, [out]);
      this.frame = new Int16Array(FRAME_SAMPLES);
      this.fill = 0;
    }
    if (this.levelN >= 800) {
      this.port.postMessage({ type: "level", rms: Math.sqrt(this.levelAcc / this.levelN) });
      this.levelAcc = 0;
      this.levelN = 0;
    }
  }

  flush() {
    if (this.fill === 0) return;
    for (let i = this.fill; i < FRAME_SAMPLES; i++) this.frame[i] = 0;
    this.fill = FRAME_SAMPLES - 1;
    this.emit(0);
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const ch = input[0];
    const n = ch.length;
    const chans = input.length;
    for (let i = 0; i < n; i++) {
      let x = ch[i];
      if (chans > 1) {
        let s = 0;
        for (let c = 0; c < chans; c++) s += input[c][i];
        x = s / chans; // downmix to mono
      }
      if (this.passthrough) {
        this.emit(x);
        continue;
      }
      this.prev = this.curr;
      this.curr = this.filtered(x);
      // Emit every output sample that falls between prev (t = -1) and curr (t = 0).
      while (this.t <= 0) {
        const frac = this.t + 1;
        this.emit(this.prev + (this.curr - this.prev) * frac);
        this.t += this.step;
      }
      this.t -= 1;
    }
    return true;
  }
}

registerProcessor("pcm16-capture", Pcm16CaptureProcessor);
