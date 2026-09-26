import workletUrl from './worklet.ts?worker&url'

/** Microphone → 16 kHz PCM16 frames (ArrayBuffer, 100 ms each). */
export class MicCapture {
  private stream: MediaStream | null = null
  private ctx: AudioContext | null = null

  async start(onChunk: (pcm16: ArrayBuffer) => void): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        // Echo cancellation helps once the agent speaks (M3). Browser noise
        // suppression and AGC stay at Chrome defaults (on).
        echoCancellation: true,
      },
    })
    this.ctx = new AudioContext()
    await this.ctx.audioWorklet.addModule(workletUrl)
    const source = this.ctx.createMediaStreamSource(this.stream)
    const node = new AudioWorkletNode(this.ctx, 'pcm16-capture')
    node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => onChunk(e.data)
    // Route through a muted gain so the graph is pulled without playing the mic back.
    const mute = this.ctx.createGain()
    mute.gain.value = 0
    source.connect(node).connect(mute).connect(this.ctx.destination)
    if (this.ctx.state === 'suspended') await this.ctx.resume()
  }

  stop(): void {
    this.stream?.getTracks().forEach((t) => t.stop())
    this.stream = null
    void this.ctx?.close()
    this.ctx = null
  }
}
