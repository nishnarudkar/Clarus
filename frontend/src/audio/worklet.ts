// AudioWorklet: mic Float32 at the context rate → 16 kHz mono PCM16 frames of CHUNK_MS.
// Runs in AudioWorkletGlobalScope, which the DOM lib doesn't type, hence the declarations.

declare const sampleRate: number
declare function registerProcessor(name: string, ctor: unknown): void
declare class AudioWorkletProcessor {
  readonly port: MessagePort
}

const TARGET_RATE = 16000
// AssemblyAI accepts 50–1000 ms per audio message; 100 ms keeps latency low with margin.
const CHUNK_MS = 100
const CHUNK_SAMPLES = (TARGET_RATE * CHUNK_MS) / 1000

class Pcm16Capture extends AudioWorkletProcessor {
  // Input samples per output sample (3 for 48 kHz).
  private ratio = sampleRate / TARGET_RATE
  private phase = 0
  private sum = 0
  private count = 0
  private out = new Int16Array(CHUNK_SAMPLES)
  private outLen = 0

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0]
    if (!channel) return true
    for (let i = 0; i < channel.length; i++) {
      // Box-filter decimation: average the input samples that fall into each output
      // sample. Crude low-pass, adequate for speech recognition.
      this.sum += channel[i]
      this.count++
      this.phase += 1
      while (this.phase >= this.ratio) {
        this.phase -= this.ratio
        this.emit(this.sum / this.count)
        this.sum = 0
        this.count = 0
        if (this.ratio < 1) {
          // Upsampling (context below 16 kHz): repeat the sample.
          this.sum = channel[i]
          this.count = 1
        }
      }
    }
    return true
  }

  private emit(sample: number): void {
    const s = Math.max(-1, Math.min(1, sample))
    this.out[this.outLen++] = s < 0 ? s * 0x8000 : s * 0x7fff
    if (this.outLen === CHUNK_SAMPLES) {
      const buf = this.out.buffer
      this.port.postMessage(buf, [buf])
      this.out = new Int16Array(CHUNK_SAMPLES)
      this.outLen = 0
    }
  }
}

registerProcessor('pcm16-capture', Pcm16Capture)
