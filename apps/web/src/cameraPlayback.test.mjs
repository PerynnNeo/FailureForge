import test from 'node:test';
import assert from 'node:assert/strict';
import { synchronizeCameras } from './cameraPlayback.ts';

class Video extends EventTarget {
  duration = 12;
  position = 0;
  paused = true;
  seeking = false;
  playbackRate = 1;
  seeks = 0;
  get currentTime() { return this.position; }
  set currentTime(time) {
    this.seeks++;
    this.position = time;
    this.dispatchEvent(new Event('seeking'));
    this.dispatchEvent(new Event('seeked'));
  }
  async play() { if (this.paused) { this.paused = false; this.dispatchEvent(new Event('play')); } }
  pause() { if (!this.paused) { this.paused = true; this.dispatchEvent(new Event('pause')); } }
}

test('either native player can start, seek, pause and restart the two recordings', async () => {
  const first = new Video(), second = new Video();
  const sync = synchronizeCameras(first, second, assert.fail);
  await second.play();
  assert.equal(first.paused, false);
  first.currentTime = 3.8;
  second.currentTime = 8.2;
  assert.equal(first.currentTime, 8.2);
  assert.equal(first.seeks, 2);
  assert.equal(second.seeks, 2);
  first.pause();
  assert.equal(second.paused, true);
  sync.restart();
  assert.deepEqual([first.currentTime, second.currentTime, first.paused, second.paused], [0, 0, false, false]);
  sync.disconnect();
  await second.play();
  assert.equal(first.paused, true);
});

test('the active camera corrects drift without a follower timeupdate pulling it backwards', async () => {
  const first = new Video(), second = new Video();
  const sync = synchronizeCameras(first, second, assert.fail);
  await first.play();
  first.position = 3;
  second.position = 2;
  second.dispatchEvent(new Event('timeupdate'));
  assert.equal(first.currentTime, 3);
  first.dispatchEvent(new Event('timeupdate'));
  assert.equal(second.currentTime, 3);
  second.playbackRate = 2;
  second.dispatchEvent(new Event('ratechange'));
  assert.equal(first.playbackRate, 2);
  sync.disconnect();
});
