(function installGroupV3TtsManager(window) {
  "use strict";

  var synthesis = window.speechSynthesis || null;
  var queue = [];
  var active = null;
  var startedKeys = new Set();
  var queuedKeys = new Set();
  var startTimeoutMs = 3000;
  var voiceWaitMs = 500;
  var sequence = 0;
  var managerState = "LOCKED";
  var managerDetail = "";
  var ringtoneActive = false;
  var primingUtterance = null;
  var utteranceRefs = new Set();

  function supported() {
    return Boolean(synthesis && typeof window.SpeechSynthesisUtterance === "function");
  }

  if (!supported()) managerState = "UNSUPPORTED";

  function setManagerState(next, detail) {
    managerState = next;
    managerDetail = detail || "";
    window.dispatchEvent(new CustomEvent("group-v3:tts-state", { detail: {
      state: managerState,
      detail: managerDetail,
      supported: supported(),
      queued: queue.length,
      active: active && active.key || ""
    } }));
  }

  function releaseUtterance(utterance) {
    if (!utterance) return;
    utterance.onstart = utterance.onend = utterance.onerror = null;
    utteranceRefs.delete(utterance);
  }

  function primeInGesture() {
    if (!supported() || managerState === "READY" || primingUtterance || active || queue.length) return;
    var utterance = new window.SpeechSynthesisUtterance("\u200b");
    primingUtterance = utterance;
    utteranceRefs.add(utterance);
    utterance.volume = 0.01;
    utterance.lang = normalizeLanguage("en");
    var ready = function () {
      if (primingUtterance !== utterance) return;
      primingUtterance = null;
      releaseUtterance(utterance);
      setManagerState("READY");
      window.queueMicrotask(pump);
    };
    utterance.onstart = ready;
    utterance.onend = ready;
    utterance.onerror = function (event) {
      if (primingUtterance !== utterance) return;
      primingUtterance = null;
      releaseUtterance(utterance);
      setManagerState("UNLOCK_REQUIRED", event && event.error || "tts_unlock_failed");
    };
    try {
      synthesis.speak(utterance);
    } catch (_error) {
      primingUtterance = null;
      releaseUtterance(utterance);
      setManagerState("UNLOCK_REQUIRED", "tts_unlock_failed");
    }
  }

  function unlock() {
    if (!supported()) {
      setManagerState("UNSUPPORTED", "tts_unsupported");
      return false;
    }
    try {
      if (typeof synthesis.resume === "function") synthesis.resume();
      if (!active && queue.length) pump(true);
      else if (active && !active.started && !active.utterance) startJob(active);
      else if (!active) primeInGesture();
      return true;
    } catch (_error) {
      setManagerState("UNLOCK_REQUIRED", "tts_unlock_failed");
      return false;
    }
  }

  function normalizeLanguage(language) {
    if (language === "zh-TW") return "zh-TW";
    if (language === "vi") return "vi-VN";
    return "en-US";
  }

  function voices() {
    try { return synthesis && typeof synthesis.getVoices === "function" ? synthesis.getVoices() || [] : []; }
    catch (_error) { return []; }
  }

  function matchingVoice(language) {
    var wanted = normalizeLanguage(language).toLowerCase();
    var prefix = wanted.split("-")[0];
    var available = voices();
    return available.find(function (voice) { return String(voice.lang || "").toLowerCase() === wanted; }) ||
      available.find(function (voice) { return String(voice.lang || "").toLowerCase().split("-")[0] === prefix; }) || null;
  }

  function waitForVoices() {
    if (!supported() || voices().length || typeof synthesis.addEventListener !== "function") return Promise.resolve();
    return new Promise(function (resolve) {
      var settled = false;
      var finish = function () {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        synthesis.removeEventListener("voiceschanged", finish);
        resolve();
      };
      var timer = window.setTimeout(finish, voiceWaitMs);
      synthesis.addEventListener("voiceschanged", finish, { once: true });
    });
  }

  function notify(job, state, detail) {
    if (typeof job.onState === "function") {
      try { job.onState(state, detail || ""); } catch (_error) {}
    }
  }

  function finish(job, state, detail) {
    if (!job || job.finished) return;
    job.finished = true;
    window.clearTimeout(job.startTimer);
    releaseUtterance(job.utterance);
    job.utterance = null;
    queuedKeys.delete(job.key);
    if (active === job) active = null;
    notify(job, state, detail);
    if (supported() && state === "COMPLETED") setManagerState("READY");
    else if (state === "FAILED" && detail === "tts_unsupported") setManagerState("UNSUPPORTED", detail);
    else if (state === "FAILED" && detail !== "tts_cancelled") setManagerState("ERROR", detail);
    window.queueMicrotask(pump);
  }

  function retryBeforeStart(job, detail, nextState) {
    if (!job || job.finished || job.started) return;
    window.clearTimeout(job.startTimer);
    releaseUtterance(job.utterance);
    job.utterance = null;
    try { synthesis.cancel(); } catch (_error) {}
    if (active === job) active = null;
    job.attempts += 1;
    queue.unshift(job);
    notify(job, nextState || "BLOCKED", detail || "tts_start_failed");
    setManagerState(nextState || "BLOCKED", detail || "tts_start_failed");
  }

  function startJob(job) {
    if (active !== job || job.finished || job.utterance) return;
    var utterance = new window.SpeechSynthesisUtterance(job.text);
    job.utterance = utterance; // Keep a strong reference for mobile Safari.
    utteranceRefs.add(utterance);
    utterance.lang = normalizeLanguage(job.language);
    var voice = matchingVoice(job.language);
    if (voice) {
      // A stale/foreign voice object must not abort the whole TTS queue. Some
      // WebKit builds refresh their voice objects while voiceschanged fires.
      try { utterance.voice = voice; } catch (_error) {}
    }
    utterance.onstart = function () {
      if (job.finished) return;
      job.started = true;
      startedKeys.add(job.key);
      window.clearTimeout(job.startTimer);
      notify(job, "STARTED");
      setManagerState("PLAYING");
    };
    utterance.onend = function () { finish(job, "COMPLETED"); };
    utterance.onerror = function (event) {
      var detail = event && event.error || "tts_playback_failed";
      if (!job.started && job.automatic && detail !== "canceled" && detail !== "interrupted") {
        retryBeforeStart(job, detail, detail === "not-allowed" ? "UNLOCK_REQUIRED" : "BLOCKED");
      } else finish(job, "FAILED", detail);
    };
    job.startTimer = window.setTimeout(function () {
      if (job.automatic) retryBeforeStart(job, "tts_start_timeout", "UNLOCK_REQUIRED");
      else finish(job, "FAILED", "tts_start_timeout");
    }, startTimeoutMs);
    try {
      if (synthesis.paused && typeof synthesis.resume === "function") synthesis.resume();
      synthesis.speak(utterance);
    } catch (_error) {
      if (job.automatic) retryBeforeStart(job, "tts_start_failed", "UNLOCK_REQUIRED");
      else finish(job, "FAILED", "tts_start_failed");
    }
  }

  function pump(userGesture) {
    if (ringtoneActive || active || !queue.length) return;
    var job = queue.shift();
    if (!job || job.finished) return window.queueMicrotask(pump);
    if (!supported()) {
      finish(job, "FAILED", "tts_unsupported");
      return;
    }
    active = job;
    notify(job, "PREPARING");
    if (job.automatic && !userGesture && ["LOCKED", "UNLOCK_REQUIRED", "BLOCKED"].indexOf(managerState) >= 0) {
      active = null;
      queue.unshift(job);
      notify(job, "UNLOCK_REQUIRED", "tts_user_activation_required");
      setManagerState("UNLOCK_REQUIRED", "tts_user_activation_required");
      return;
    }
    // Manual playback stays inside the click/tap call stack. Moving speak()
    // behind a Promise can lose Safari's user-activation token and become a
    // silent no-op. Automatic delivery can wait briefly for populated voices.
    if (userGesture || !job.automatic || voices().length) {
      if (managerState !== "PLAYING") setManagerState("READY");
      startJob(job);
      return;
    }
    setManagerState("VOICE_LOADING");
    notify(job, "VOICE_LOADING");
    waitForVoices().then(function () {
      if (active === job && !job.finished) {
        setManagerState("READY");
        startJob(job);
      }
    });
  }

  function enqueue(options) {
    options = options || {};
    var text = String(options.text || "").trim();
    var key = String(options.key || "tts-" + Date.now() + "-" + (++sequence));
    if (!text || !supported()) {
      if (typeof options.onState === "function") options.onState("FAILED", "tts_unsupported");
      return false;
    }
    if (startedKeys.has(key) || queuedKeys.has(key)) return false;
    var job = {
      key: key,
      text: text,
      language: options.language || "en",
      automatic: Boolean(options.automatic),
      onState: options.onState,
      started: false,
      finished: false,
      startTimer: 0,
      utterance: null,
      attempts: 0
    };
    queuedKeys.add(key);
    if (options.priority) queue.unshift(job);
    else queue.push(job);
    notify(job, "QUEUED");
    if (options.immediate) pump(Boolean(options.userGesture));
    else window.queueMicrotask(pump);
    return true;
  }

  function cancel(options) {
    options = options || {};
    var pending = queue.splice(0);
    pending.forEach(function (job) { finish(job, "FAILED", "tts_cancelled"); });
    if (active) {
      var job = active;
      releaseUtterance(job.utterance);
      job.utterance = null;
      try { synthesis.cancel(); } catch (_error) {}
      finish(job, "FAILED", "tts_cancelled");
    }
    if (primingUtterance) {
      releaseUtterance(primingUtterance);
      primingUtterance = null;
    }
    if (options.forgetStarted) startedKeys.clear();
  }

  function playManual(options) {
    options = Object.assign({}, options || {}, {
      key: String(options && options.key || "manual-" + Date.now() + "-" + (++sequence)),
      automatic: false,
      priority: true,
      immediate: true,
      userGesture: true
    });
    cancel();
    return enqueue(options);
  }

  function diagnostics() {
    return {
      supported: supported(),
      state: managerState,
      detail: managerDetail,
      ringtoneActive: ringtoneActive,
      active: active ? { key: active.key, started: active.started, automatic: active.automatic } : null,
      queued: queue.map(function (job) { return { key: job.key, automatic: job.automatic }; }),
      startedKeys: Array.from(startedKeys)
    };
  }

  window.addEventListener("group-v3:ringtone-started", function () {
    ringtoneActive = true;
    cancel();
  });
  window.addEventListener("group-v3:ringtone-stopped", function () {
    ringtoneActive = false;
    window.queueMicrotask(pump);
  });

  window.GroupV3TtsManager = Object.freeze({
    supported: supported,
    state: function () { return managerState; },
    unlock: unlock,
    enqueue: enqueue,
    playManual: playManual,
    cancel: cancel,
    hasStarted: function (key) { return startedKeys.has(String(key || "")); },
    diagnostics: diagnostics,
    configureForTests: function (options) {
      options = options || {};
      if (Number(options.startTimeoutMs) > 0) startTimeoutMs = Number(options.startTimeoutMs);
      if (Number(options.voiceWaitMs) >= 0) voiceWaitMs = Number(options.voiceWaitMs);
    }
  });
})(window);
