// Checks public/worklets/pcm16-capture.js outside a browser: frame size, output rate, gain in
// the speech band and attenuation above 8 kHz, at 48 kHz, 44.1 kHz and 16 kHz input.
// Run: node scripts/check-pcm-worklet.mjs   (exit code 1 on failure)
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const src = readFileSync(fileURLToPath(new URL("../public/worklets/pcm16-capture.js", import.meta.url)), "utf8");

function load(rate) {
  let Proc;
  const ctx = {
    sampleRate: rate,
    Math,
    Float32Array,
    Int16Array,
    AudioWorkletProcessor: class {
      constructor() {
        this.port = { posted: [], postMessage(m) { this.posted.push(m); }, onmessage: null };
      }
    },
    registerProcessor: (_name, cls) => {
      Proc = cls;
    },
  };
  vm.runInNewContext(src, ctx);
  return new Proc();
}

function run(rate, freq, seconds = 1) {
  const p = load(rate);
  const n = Math.round(rate * seconds);
  for (let off = 0; off < n; off += 128) {
    const block = new Float32Array(Math.min(128, n - off));
    for (let i = 0; i < block.length; i++) block[i] = 0.5 * Math.sin((2 * Math.PI * freq * (off + i)) / rate);
    p.process([[block]]);
  }
  const frames = p.port.posted.filter((m) => m instanceof ArrayBuffer);
  const samples = frames.flatMap((b) => Array.from(new Int16Array(b)));
  return { frames, samples, levels: p.port.posted.filter((m) => m && m.type === "level") };
}

function rms(xs) {
  const tail = xs.slice(200); // skip the filter's start-up
  return Math.sqrt(tail.reduce((a, x) => a + (x / 32768) ** 2, 0) / tail.length);
}

const failures = [];
const check = (ok, msg) => {
  console.log(`${ok ? "ok  " : "FAIL"} ${msg}`);
  if (!ok) failures.push(msg);
};

for (const rate of [48000, 44100, 16000]) {
  const speech = run(rate, 1000);
  check(speech.frames.every((b) => b.byteLength === 1024), `${rate}: every frame is 1,024 bytes`);
  const total = speech.frames.length * 512;
  check(Math.abs(total - 16000) <= 512, `${rate}: ~16,000 samples per second (got ${total})`);
  const g = rms(speech.samples) / (0.5 / Math.SQRT2);
  check(g > 0.9 && g < 1.1, `${rate}: 1 kHz passes at unity gain (${g.toFixed(3)})`);
  check(speech.levels.length > 10, `${rate}: level messages are sent`);
  if (rate !== 16000) {
    const alias = run(rate, 12000);
    const a = rms(alias.samples) / (0.5 / Math.SQRT2);
    check(a < 0.05, `${rate}: 12 kHz is removed, not aliased (${a.toFixed(4)})`);
  }
}

const p = load(48000);
p.process([[new Float32Array(300)]]);
p.port.onmessage({ data: { type: "flush" } });
const flushed = p.port.posted.filter((m) => m instanceof ArrayBuffer);
check(flushed.length === 1 && flushed[0].byteLength === 1024, "flush sends the partial frame, padded");

if (failures.length) process.exit(1);
