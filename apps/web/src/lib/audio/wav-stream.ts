/**
 * Play a WAV response while it is still downloading.
 *
 * The core streams uncached question audio: a PCM16 WAV header with an open-ended length,
 * then samples as Timbre produces them (services/core/.../api/voice_turns.py). Each piece is
 * scheduled right after the previous one, so playback starts before synthesis finishes and
 * has no gaps. Audio that is not PCM16 is decoded whole instead.
 */

export interface WavStreamPlayback {
  /** Resolves when the last sample has played (or playback was stopped). */
  done: Promise<void>;
  stop: () => void;
}

interface Format {
  rate: number;
  channels: number;
  bits: number;
  format: number;
  dataOffset: number;
}

/** Find `fmt ` and the start of `data` in a RIFF/WAVE header; null until enough bytes arrived. */
export function parseWavHeader(b: Uint8Array): Format | null {
  if (b.length < 12) return null;
  const v = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const tag = (o: number) => String.fromCharCode(b[o], b[o + 1], b[o + 2], b[o + 3]);
  if (tag(0) !== "RIFF" || tag(8) !== "WAVE") throw new Error("not a WAV stream");
  let off = 12;
  let fmt: Omit<Format, "dataOffset"> | null = null;
  while (off + 8 <= b.length) {
    const id = tag(off);
    const size = v.getUint32(off + 4, true);
    if (id === "data") return fmt ? { ...fmt, dataOffset: off + 8 } : null;
    if (off + 8 + size > b.length) return null; // the chunk is not complete yet
    if (id === "fmt ") {
      fmt = {
        format: v.getUint16(off + 8, true),
        channels: v.getUint16(off + 10, true),
        rate: v.getUint32(off + 12, true),
        bits: v.getUint16(off + 22, true),
      };
    }
    off += 8 + size + (size % 2);
  }
  return null;
}

export function playWavStream(res: Response, ctx: AudioContext): WavStreamPlayback {
  const sources: AudioBufferSourceNode[] = [];
  let stopped = false;
  let cursor = 0;
  let resolveDone: () => void = () => {};
  const done = new Promise<void>((r) => (resolveDone = r));
  let reading = true;

  const settleIfFinished = () => {
    if (!reading && !sources.length) resolveDone();
  };

  const schedule = (pcm: Int16Array, rate: number) => {
    if (stopped || !pcm.length) return;
    const buf = ctx.createBuffer(1, pcm.length, rate);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.05, cursor);
    cursor = at + buf.duration;
    sources.push(src);
    src.onended = () => {
      sources.splice(sources.indexOf(src), 1);
      settleIfFinished();
    };
    src.start(at);
  };

  const run = async () => {
    const reader = res.body?.getReader();
    if (!reader) throw new Error("no audio body");
    let head = new Uint8Array(0);
    let fmt: Format | null = null;
    let carry: Uint8Array | null = null;
    const whole: Uint8Array[] = [];
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end || stopped) break;
      if (!fmt) {
        const joined = new Uint8Array(head.length + value.length);
        joined.set(head);
        joined.set(value, head.length);
        head = joined;
        fmt = parseWavHeader(head);
        if (!fmt) continue;
        if (fmt.format !== 1 || fmt.bits !== 16 || fmt.channels !== 1) {
          whole.push(head); // not PCM16 mono: decode the whole file at the end
          continue;
        }
        let rest = head.slice(fmt.dataOffset);
        head = new Uint8Array(0);
        if (rest.length % 2) {
          carry = rest.slice(rest.length - 1);
          rest = rest.slice(0, rest.length - 1);
        }
        schedule(new Int16Array(rest.buffer, rest.byteOffset, rest.length / 2), fmt.rate);
        continue;
      }
      if (whole.length) {
        whole.push(value);
        continue;
      }
      let bytes: Uint8Array = value;
      if (carry) {
        const joined = new Uint8Array(carry.length + bytes.length);
        joined.set(carry);
        joined.set(bytes, carry.length);
        bytes = joined;
        carry = null;
      }
      if (bytes.length % 2) {
        carry = bytes.slice(bytes.length - 1);
        bytes = bytes.slice(0, bytes.length - 1);
      }
      const aligned = bytes.byteOffset % 2 ? bytes.slice() : bytes;
      schedule(new Int16Array(aligned.buffer, aligned.byteOffset, aligned.length / 2), fmt.rate);
    }
    if (whole.length && !stopped) {
      const total = whole.reduce((n, c) => n + c.length, 0);
      const all = new Uint8Array(total);
      let off = 0;
      for (const c of whole) {
        all.set(c, off);
        off += c.length;
      }
      const buf = await ctx.decodeAudioData(all.buffer);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      sources.push(src);
      src.onended = () => {
        sources.splice(sources.indexOf(src), 1);
        settleIfFinished();
      };
      src.start();
    }
  };

  void run()
    .catch(() => {
      /* a broken stream just ends playback early */
    })
    .finally(() => {
      reading = false;
      settleIfFinished();
    });

  return {
    done,
    stop: () => {
      stopped = true;
      for (const s of [...sources]) {
        try {
          s.stop();
        } catch {
          /* already stopped */
        }
      }
      sources.length = 0;
      resolveDone();
    },
  };
}
