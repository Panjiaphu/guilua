(function installGroupV3Ringback(window) {
  "use strict";

  var ownerId = Math.random().toString(36).slice(2) + Date.now().toString(36);
  var channel = typeof window.BroadcastChannel === "function" ? new window.BroadcastChannel("group-v3-ringback") : null;
  var context = null;
  var activeKey = "";
  var toneTimer = 0;
  var armed = false;
  var leader = true;

  function ensureAudio() {
    if (!context && typeof window.AudioContext === "function") context = new window.AudioContext();
    if (context && context.state === "suspended") context.resume().catch(function () {});
    return context;
  }

  function stopTone() {
    window.clearInterval(toneTimer);
    toneTimer = 0;
  }

  function tone() {
    var audio = ensureAudio();
    if (!audio || !leader || !activeKey) return;
    try {
      var oscillator = audio.createOscillator();
      var gain = audio.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = 440;
      gain.gain.setValueAtTime(0.0001, audio.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.035, audio.currentTime + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.42);
      oscillator.connect(gain).connect(audio.destination);
      oscillator.start();
      oscillator.stop(audio.currentTime + 0.45);
    } catch (_error) {}
  }

  function start(key) {
    key = String(key || "").trim();
    if (!key) return;
    if (activeKey !== key) {
      stopTone();
      activeKey = key;
      leader = true;
      if (channel) channel.postMessage({ type: "claim", key: activeKey, owner: ownerId });
    }
    if (armed && leader && !toneTimer) {
      tone();
      toneTimer = window.setInterval(tone, 1900);
    }
  }

  function stop() {
    if (channel && activeKey) channel.postMessage({ type: "stop", key: activeKey, owner: ownerId });
    activeKey = "";
    leader = true;
    stopTone();
  }

  function arm() {
    armed = true;
    ensureAudio();
    if (activeKey && leader) start(activeKey);
  }

  if (channel) {
    channel.addEventListener("message", function (event) {
      var message = event.data || {};
      if (!activeKey || message.key !== activeKey || message.owner === ownerId) return;
      if (message.type === "claim" && String(message.owner) < String(ownerId)) {
        leader = false;
        stopTone();
      } else if (message.type === "stop") {
        stopTone();
      }
    });
  }

  window.GroupV3Ringback = Object.freeze({ start: start, stop: stop, arm: arm });
  window.addEventListener("pagehide", stop);
})(window);
