/** Native controls on either video can drive the pair. Only the driver corrects drift. */
export function synchronizeCameras(first: HTMLVideoElement, second: HTMLVideoElement, onError: () => void) {
  let driver = first;
  let connected = true;
  const mirroredSeeks = new Map<HTMLVideoElement, number>();
  const listeners = new AbortController();

  function align(source: HTMLVideoElement, other: HTMLVideoElement, tolerance: number) {
    if (!Number.isFinite(other.duration)) return;
    const time = Math.min(source.currentTime, other.duration);
    if (Math.abs(other.currentTime - time) <= tolerance) return;
    mirroredSeeks.set(other, time);
    other.currentTime = time;
  }

  function start(video: HTMLVideoElement) {
    void video.play().catch((error: Error) => {
      if (!connected || error.name === 'AbortError') return;
      first.pause(); second.pause(); onError();
    });
  }

  function follow(source: HTMLVideoElement, other: HTMLVideoElement) {
    const on = (name: string, callback: () => void) => source.addEventListener(name, callback, { signal: listeners.signal });
    const takeControl = () => { driver = source; mirroredSeeks.delete(source); };
    on('pointerdown', takeControl);
    on('keydown', takeControl);
    on('play', () => {
      if (source.paused || !other.paused) return;
      takeControl(); align(source, other, 0.025); start(other);
    });
    on('pause', () => {
      if (!source.paused || other.paused) return;
      takeControl(); other.pause(); align(source, other, 0.025);
    });
    on('seeking', () => {
      const expected = mirroredSeeks.get(source);
      if (expected !== undefined && Math.abs(expected - source.currentTime) < .12) return;
      takeControl(); align(source, other, 0.015);
    });
    on('seeked', () => mirroredSeeks.delete(source));
    on('ratechange', () => {
      if (source.playbackRate !== other.playbackRate) other.playbackRate = source.playbackRate;
    });
    on('timeupdate', () => {
      if (driver === source && !source.paused && !source.seeking && !other.seeking) align(source, other, .12);
    });
    on('loadedmetadata', () => { if (driver === other) align(other, source, .025); });
  }
  follow(first, second); follow(second, first);
  return {
    restart() {
      driver = first; mirroredSeeks.clear();
      first.currentTime = 0; second.currentTime = 0;
      start(first); start(second);
    },
    disconnect() { connected = false; listeners.abort(); first.pause(); second.pause(); },
  };
}
