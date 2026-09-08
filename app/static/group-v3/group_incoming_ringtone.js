(function installGroupV3IncomingRingtone(window, document) {
  "use strict";

  var ownerId = Math.random().toString(36).slice(2) + Date.now().toString(36);
  var channel = typeof window.BroadcastChannel === "function"
    ? new window.BroadcastChannel("group-v3-ringtone-v2")
    : null;
  var context = null;
  var activeKey = "";
  var heartbeatTimer = 0;
  var toneTimer = 0;
  var durationTimer = 0;
  var fallbackElectionTimer = 0;
  var armed = false;
  var leader = false;
  var lockPending = false;
  var lockRelease = null;
  var signaledKey = "";
  var peers = new Map();
  var exhaustedKeys = new Set();
  var activeNodes = new Set();
  var preferences = { enabled: true, volume: 0.7, durationSeconds: 30 };
  var PEER_LEASE_MS = 3500;

  function clamp(value, low, high, fallback) {
    value = Number(value);
    return Number.isFinite(value) ? Math.max(low, Math.min(high, value)) : fallback;
  }

  function readPreferences(overrides) {
    var stored = {};
    try { stored = JSON.parse(window.localStorage.getItem("groupV3RingtonePreferences") || "{}"); }
    catch (_error) { stored = {}; }
    overrides = overrides || {};
    return {
      enabled: overrides.enabled !== undefined
        ? overrides.enabled !== false
        : stored.incoming_ringtone_enabled !== false,
      volume: clamp(
        overrides.volume !== undefined ? overrides.volume : Number(stored.incoming_ringtone_volume_percent) / 100,
        0.05, 1, 0.7
      ),
      durationSeconds: clamp(
        overrides.durationSeconds !== undefined ? overrides.durationSeconds : stored.incoming_ringtone_duration_seconds,
        15, 60, 30
      )
    };
  }

  function ensureAudio() {
    var AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!context && typeof AudioContext === "function") context = new AudioContext();
    if (context && context.state === "suspended") context.resume().catch(function () {});
    return context;
  }

  function releaseNodes() {
    activeNodes.forEach(function (node) {
      try { node.stop(); } catch (_error) {}
      try { node.disconnect(); } catch (_error) {}
    });
    activeNodes.clear();
  }

  function stopTone() {
    window.clearInterval(toneTimer);
    toneTimer = 0;
    releaseNodes();
  }

  function signalActive(key) {
    if (signaledKey === key) return;
    if (signaledKey) signalStopped(signaledKey);
    signaledKey = key;
    window.dispatchEvent(new CustomEvent("group-v3:ringtone-started", {
      detail: { key: key, owner: ownerId }
    }));
  }

  function signalStopped(key) {
    if (!signaledKey || (key && signaledKey !== key)) return;
    var stoppedKey = signaledKey;
    signaledKey = "";
    window.dispatchEvent(new CustomEvent("group-v3:ringtone-stopped", {
      detail: { key: stoppedKey, owner: ownerId }
    }));
  }

  function tone() {
    var audio = ensureAudio();
    if (!audio || !leader || !activeKey || !preferences.enabled ||
        !armed || document.visibilityState !== "visible") return;
    try {
      [0, 0.28].forEach(function (offset) {
        var oscillator = audio.createOscillator();
        var gain = audio.createGain();
        oscillator.type = "sine";
        oscillator.frequency.value = 740;
        gain.gain.setValueAtTime(0.0001, audio.currentTime + offset);
        gain.gain.exponentialRampToValueAtTime(0.055 * preferences.volume, audio.currentTime + offset + 0.025);
        gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + offset + 0.22);
        oscillator.connect(gain).connect(audio.destination);
        activeNodes.add(oscillator);
        activeNodes.add(gain);
        oscillator.onended = function () {
          activeNodes.delete(oscillator);
          activeNodes.delete(gain);
          try { oscillator.disconnect(); } catch (_error) {}
          try { gain.disconnect(); } catch (_error) {}
        };
        oscillator.start(audio.currentTime + offset);
        oscillator.stop(audio.currentTime + offset + 0.24);
      });
    } catch (_error) {}
  }

  function startTone() {
    if (toneTimer || !leader || !activeKey || !armed ||
        !preferences.enabled || document.visibilityState !== "visible") return;
    tone();
    toneTimer = window.setInterval(tone, 1700);
  }

  function releaseLeadership() {
    window.clearTimeout(fallbackElectionTimer);
    fallbackElectionTimer = 0;
    if (lockRelease) {
      var release = lockRelease;
      lockRelease = null;
      release();
    }
    leader = false;
    stopTone();
  }

  function eligibleForAudibleOwnership() {
    return Boolean(
      activeKey && armed && preferences.enabled && document.visibilityState === "visible"
    );
  }

  function prunePeers() {
    var threshold = Date.now() - PEER_LEASE_MS;
    peers.forEach(function (value, key) {
      if (value.seenAt < threshold || value.key !== activeKey) peers.delete(key);
    });
  }

  function applyFallbackElection() {
    fallbackElectionTimer = 0;
    if (!eligibleForAudibleOwnership()) {
      if (leader) releaseLeadership();
      return;
    }
    prunePeers();
    var owners = [ownerId];
    peers.forEach(function (value, key) { if (value.key === activeKey) owners.push(key); });
    var shouldLead = owners.sort()[0] === ownerId;
    if (shouldLead !== leader) {
      leader = shouldLead;
      if (leader) startTone();
      else stopTone();
    }
  }

  function electFallback() {
    if (window.navigator.locks && typeof window.navigator.locks.request === "function") return;
    window.clearTimeout(fallbackElectionTimer);
    fallbackElectionTimer = 0;
    if (!eligibleForAudibleOwnership()) {
      if (leader) releaseLeadership();
      return;
    }
    if (!channel) {
      applyFallbackElection();
      return;
    }
    // Give BroadcastChannel peers one short discovery window so two tabs do
    // not both emit the first cadence before deterministic owner election.
    fallbackElectionTimer = window.setTimeout(applyFallbackElection, 120);
  }

  function requestWebLock() {
    if (!eligibleForAudibleOwnership() || leader || lockPending || !window.navigator.locks ||
        typeof window.navigator.locks.request !== "function") return false;
    var requestedKey = activeKey;
    lockPending = true;
    window.navigator.locks.request(
      "group-v3-ringtone:" + requestedKey,
      { ifAvailable: true, mode: "exclusive" },
      function (lock) {
        lockPending = false;
        if (!lock || activeKey !== requestedKey || !eligibleForAudibleOwnership()) return;
        leader = true;
        startTone();
        return new Promise(function (resolve) { lockRelease = resolve; });
      }
    ).catch(function () { lockPending = false; });
    return true;
  }

  function announce() {
    if (channel && eligibleForAudibleOwnership()) channel.postMessage({
      type: "active", key: activeKey, owner: ownerId, eligible: true, seenAt: Date.now()
    });
  }

  function maintainOwnership() {
    if (!activeKey) return;
    if (!eligibleForAudibleOwnership()) {
      if (leader) releaseLeadership();
      return;
    }
    announce();
    if (!requestWebLock()) electFallback();
    if (leader) startTone();
  }

  function start(key, options) {
    key = String(key || "").trim();
    if (!key || exhaustedKeys.has(key)) return;
    preferences = readPreferences(options);
    if (!preferences.enabled) return stop();
    if (activeKey !== key) {
      releaseLeadership();
      window.clearTimeout(durationTimer);
      activeKey = key;
      peers.clear();
      signalActive(key);
      durationTimer = window.setTimeout(function () {
        if (activeKey) {
          exhaustedKeys.add(activeKey);
          if (exhaustedKeys.size > 32) exhaustedKeys.delete(exhaustedKeys.values().next().value);
        }
        stop();
      }, preferences.durationSeconds * 1000);
    }
    window.clearInterval(heartbeatTimer);
    heartbeatTimer = window.setInterval(maintainOwnership, 1000);
    maintainOwnership();
  }

  function stop() {
    var releasedKey = activeKey;
    activeKey = "";
    window.clearTimeout(durationTimer);
    durationTimer = 0;
    window.clearInterval(heartbeatTimer);
    heartbeatTimer = 0;
    releaseLeadership();
    peers.clear();
    signalStopped(releasedKey);
    if (channel && releasedKey) channel.postMessage({ type: "release", key: releasedKey, owner: ownerId });
  }

  function arm() {
    armed = true;
    ensureAudio();
    maintainOwnership();
  }

  function configure(options) {
    preferences = readPreferences(options);
    if (!preferences.enabled) stop();
    else if (activeKey) start(activeKey, preferences);
    return Object.assign({}, preferences);
  }

  if (channel) {
    channel.addEventListener("message", function (event) {
      var message = event.data || {};
      if (!activeKey || message.key !== activeKey || message.owner === ownerId) return;
      if (message.type === "active" && message.eligible === true) {
        peers.set(String(message.owner), { key: message.key, seenAt: Date.now() });
        electFallback();
      } else if (message.type === "release") {
        peers.delete(String(message.owner));
        electFallback();
        requestWebLock();
      }
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState !== "visible") {
      releaseLeadership();
      if (channel && activeKey) channel.postMessage({ type: "release", key: activeKey, owner: ownerId });
    }
    else if (activeKey) maintainOwnership();
  });
  window.addEventListener("pagehide", stop);
  window.addEventListener("beforeunload", stop);

  window.GroupV3IncomingRingtone = Object.freeze({
    start: start,
    stop: stop,
    arm: arm,
    configure: configure,
    diagnostics: function () {
      return {
        key: activeKey,
        owner: ownerId,
        armed: armed,
        leader: leader,
        visible: document.visibilityState === "visible",
        volume: preferences.volume,
        duration_seconds: preferences.durationSeconds
      };
    }
  });
})(window, document);
