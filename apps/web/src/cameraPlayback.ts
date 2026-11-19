/** Native controls on either video can drive the pair. Only the driver corrects drift. */
export function synchronizeCameras(first: HTMLVideoElement, second: HTMLVideoElement, onError: () => void,
  recordedDurations?: readonly [number, number]) {
  let driver = first;
  let connected = true;
  const mirroredSeeks = new Map<HTMLVideoElement, number>();
  const mirroredRates = new Map<HTMLVideoElement, number>();
  const stepping = new Set<HTMLVideoElement>();
  const listeners = new AbortController();

  // Independent captures can be time-compressed by different amounts.
  function scale(video: HTMLVideoElement) {
    return recordedDurations && Number.isFinite(video.duration) && video.duration > 0
      ? recordedDurations[video === first ? 0 : 1] / video.duration : 1;
  }

  function relativeRate(source: HTMLVideoElement, other: HTMLVideoElement) {
    return scale(source) / scale(other);
  }

  function align(source: HTMLVideoElement, other: HTMLVideoElement, tolerance: number) {
    if (!Number.isFinite(other.duration)) return;
    const time = Math.min(source.currentTime * relativeRate(source, other), other.duration);
    if (Math.abs(other.currentTime - time) <= tolerance) return;
    mirroredSeeks.set(other, time);
    other.currentTime = time;
  }

  function start(video: HTMLVideoElement) {
    void video.play().catch((error: Error) => {
      if (!connected || error.name === 'AbortError' || video.error) return;
      first.pause(); second.pause(); onError();
    });
  }

  function followRate(source: HTMLVideoElement, other: HTMLVideoElement) {
    const rate = source.playbackRate * relativeRate(source, other);
    // Browsers support a limited range of native rates. Seek the follower on
    // clock updates if the recording scales would require a rate outside it.
    if (rate < .0625 || rate > 16) {
      stepping.add(other);
      other.pause();
      return;
    }
    stepping.delete(other);
    if (Math.abs(other.playbackRate - rate) > .00001) {
      try {
        mirroredRates.set(other, rate);
        other.playbackRate = rate;
      } catch {
        mirroredRates.delete(other);
        stepping.add(other);
        other.pause();
      }
    }
  }

  function match(source: HTMLVideoElement, other: HTMLVideoElement, tolerance: number) {
    followRate(source, other);
    align(source, other, stepping.has(other) ? 0 : tolerance);
    if (source.paused || stepping.has(other) || !other.paused) return;
    // play() on an ended video restarts it at zero. Hold its final frame until
    // the user seeks back into the interval shared by both recordings.
    if (!Number.isFinite(other.duration) || source.currentTime * relativeRate(source, other) < other.duration) start(other);
  }

  function follow(source: HTMLVideoElement, other: HTMLVideoElement) {
    const on = (name: string, callback: () => void) => source.addEventListener(name, callback, { signal: listeners.signal });
    const takeControl = () => { driver = source; mirroredSeeks.delete(source); stepping.delete(source); };
    on('pointerdown', takeControl);
    on('keydown', takeControl);
    on('play', () => {
      if (source.paused || !other.paused) return;
      takeControl(); match(source, other, 0.025);
    });
    on('pause', () => {
      if (!source.paused || stepping.has(source) || source.error || other.error) return;
      if (source.ended && source.duration * scale(source) < other.duration * scale(other)) {
        if (!other.paused || stepping.has(other)) {
          if (driver === source) align(source, other, .025);
          driver = other;
          stepping.delete(other);
          if (other.paused) start(other);
        }
        return;
      }
      if (other.paused) return;
      takeControl(); other.pause(); align(source, other, 0.025);
    });
    on('seeking', () => {
      const expected = mirroredSeeks.get(source);
      if (expected !== undefined && Math.abs(expected - source.currentTime) < .12) return;
      takeControl(); match(source, other, 0.015);
    });
    on('seeked', () => mirroredSeeks.delete(source));
    on('ratechange', () => {
      const expected = mirroredRates.get(source);
      mirroredRates.delete(source);
      if (expected !== undefined && Math.abs(expected - source.playbackRate) < .00001) return;
      takeControl(); match(source, other, .025);
    });
    on('timeupdate', () => {
      if (driver === source && !source.paused && !source.seeking && !other.seeking) match(source, other, .12);
    });
    on('loadedmetadata', () => { if (driver === other) match(other, source, .025); });
  }
  follow(first, second); follow(second, first);
  if (!first.paused) match(first, second, .025);
  else if (!second.paused) { driver = second; match(second, first, .025); }
  return {
    restart() {
      driver = first; mirroredSeeks.clear();
      stepping.clear();
      first.currentTime = 0; align(first, second, 0);
      followRate(first, second);
      start(first);
      if (!stepping.has(second)) start(second);
    },
    disconnect(pause = true) {
      connected = false;
      listeners.abort();
      if (pause) { first.pause(); second.pause(); }
    },
  };
}
