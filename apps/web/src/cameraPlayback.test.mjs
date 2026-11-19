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
  get ended() { return this.position >= this.duration; }
  get currentTime() { return this.position; }
  set currentTime(time) {
    this.seeks++;
    this.position = time;
    this.dispatchEvent(new Event('seeking'));
    this.dispatchEvent(new Event('seeked'));
  }
  async play() { if (this.paused) { this.paused = false; this.dispatchEvent(new Event('play')); } }
  pause() { if (!this.paused) { this.paused = true; this.dispatchEvent(new Event('pause')); } }
  finish() {
    this.position = this.duration;
    this.pause();
    this.dispatchEvent(new Event('ended'));
  }
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

test('two runs of different lengths play on one timeline with the follower clamped to its shorter duration', async () => {
  const first = new Video(), second = new Video();
  first.duration = 12;
  second.duration = 7;
  const sync = synchronizeCameras(first, second, assert.fail);

  // starting one drives the other
  await first.play();
  assert.equal(second.paused, false, 'playing the driver starts the follower');

  // a seek past the follower's end is mirrored clamped to the follower's shorter duration
  first.currentTime = 10;
  assert.equal(second.currentTime, 7, 'follower seek is clamped to its own duration');

  // a seek the follower can reach is mirrored exactly
  first.currentTime = 4;
  assert.equal(second.currentTime, 4);

  // pause mirrors to the follower
  first.pause();
  assert.equal(second.paused, true, 'pausing the driver pauses the follower');

  // restart resets both to 0 and plays both
  sync.restart();
  assert.deepEqual([first.currentTime, second.currentTime, first.paused, second.paused], [0, 0, false, false]);
  sync.disconnect();
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

test('the longer recording continues after either player drove the shorter one to its native end', async () => {
  for (const shortDrives of [true, false]) {
    const longer = new Video(), shorter = new Video();
    shorter.duration = 7;
    const sync = synchronizeCameras(longer, shorter, assert.fail);
    await (shortDrives ? shorter : longer).play();
    longer.position = 7;
    shorter.finish();
    longer.position = 9;
    longer.dispatchEvent(new Event('timeupdate'));
    assert.deepEqual([longer.currentTime, shorter.currentTime, longer.paused, shorter.paused], [9, 7, false, true]);
    longer.currentTime = 4;
    assert.deepEqual([shorter.currentTime, shorter.paused], [4, false]);
    sync.disconnect();
  }
});

test('time-compressed videos seek, change rate and hold the last frame by recorded time', async () => {
  const first = new Video(), second = new Video();
  const sync = synchronizeCameras(first, second, assert.fail, [24, 48]); // both MP4s last twelve seconds
  await first.play();
  assert.equal(second.playbackRate, .5);
  first.currentTime = 6;
  assert.equal(second.currentTime, 3);
  second.currentTime = 4;
  assert.equal(first.currentTime, 8);
  second.playbackRate = 1;
  second.dispatchEvent(new Event('ratechange'));
  assert.equal(first.playbackRate, 2);
  second.position = 6;
  first.finish();
  second.position = 9;
  second.dispatchEvent(new Event('timeupdate'));
  assert.deepEqual([first.currentTime, first.paused, second.paused], [12, true, false]);
  sync.disconnect();
});

test('an unsupported native speed follows user seeks and playback ticks using frames', async () => {
  const first = new Video(), second = new Video();
  const sync = synchronizeCameras(first, second, assert.fail, [12, 1200]);
  await first.play();
  assert.equal(second.paused, true);
  first.currentTime = 8;
  assert.equal(second.currentTime, .08);
  first.finish();
  assert.equal(second.paused, false, 'remaining footage should play after the short run finishes');
  sync.disconnect();
});

test('removing the link after a decode error leaves the healthy player running independently', async () => {
  const first = new Video(), second = new Video();
  const sync = synchronizeCameras(first, second, assert.fail);
  await first.play();
  second.error = {code: 3};
  second.pause();
  assert.equal(first.paused, false);
  sync.disconnect(false);
  second.currentTime = 3;
  assert.equal(first.currentTime, 0);
});
