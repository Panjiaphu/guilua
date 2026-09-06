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

  function supported() {
    return Boolean(synthesis && typeof window.SpeechSynthesisUtterance === "function");
  }

  function unlock() {
    if (!supported()) return false;
    try {
      if (typeof synthesis.resume === "function") synthesis.resume();
      return true;
    } catch (_error) {
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
    queuedKeys.delete(job.key);
    if (active === job) active = null;
    notify(job, state, detail);
    window.queueMicrotask(pump);
  }

  function failBeforeStart(job, detail) {
    if (!job || job.finished || job.started) return;
    try { synthesis.cancel(); } catch (_error) {}
    finish(job, "FAILED", detail || "tts_start_failed");
  }

  function startJob(job) {
    if (active !== job || job.finished) return;
    var utterance = new window.SpeechSynthesisUtterance(job.text);
    job.utterance = utterance; // Keep a strong reference for mobile Safari.
    utterance.lang = normalizeLanguage(job.language);
    var voice = matchingVoice(job.language);
    if (voice) utterance.voice = voice;
    utterance.onstart = function () {
      if (job.finished) return;
      job.started = true;
      startedKeys.add(job.key);
      window.clearTimeout(job.startTimer);
      notify(job, "STARTED");
    };
    utterance.onend = function () { finish(job, "COMPLETED"); };
    utterance.onerror = function (event) {
      finish(job, "FAILED", event && event.error || "tts_playback_failed");
    };
    job.startTimer = window.setTimeout(function () { failBeforeStart(job, "tts_start_timeout"); }, startTimeoutMs);
    try {
      if (synthesis.paused && typeof synthesis.resume === "function") synthesis.resume();
      synthesis.speak(utterance);
    } catch (_error) {
      failBeforeStart(job, "tts_start_failed");
    }
  }

  function pump() {
    if (active || !queue.length) return;
    var job = queue.shift();
    if (!job || job.finished) return window.queueMicrotask(pump);
    if (!supported()) {
      finish(job, "FAILED", "tts_unsupported");
      return;
    }
    active = job;
    notify(job, "PREPARING");
    // Manual playback stays inside the click/tap call stack. Moving speak()
    // behind a Promise can lose Safari's user-activation token and become a
    // silent no-op. Automatic delivery can wait briefly for populated voices.
    if (!job.automatic || voices().length) {
      startJob(job);
      return;
    }
    waitForVoices().then(function () { startJob(job); });
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
      utterance: null
    };
    queuedKeys.add(key);
    if (options.priority) queue.unshift(job);
    else queue.push(job);
    notify(job, "QUEUED");
    if (options.immediate) pump();
    else window.queueMicrotask(pump);
    return true;
  }

  function cancel(options) {
    options = options || {};
    var pending = queue.splice(0);
    pending.forEach(function (job) { finish(job, "FAILED", "tts_cancelled"); });
    if (active) {
      var job = active;
      try { synthesis.cancel(); } catch (_error) {}
      finish(job, "FAILED", "tts_cancelled");
    }
    if (options.forgetStarted) startedKeys.clear();
  }

  function playManual(options) {
    options = Object.assign({}, options || {}, {
      key: String(options && options.key || "manual-" + Date.now() + "-" + (++sequence)),
      automatic: false,
      priority: true,
      immediate: true
    });
    cancel();
    return enqueue(options);
  }

  function diagnostics() {
    return {
      supported: supported(),
      active: active ? { key: active.key, started: active.started, automatic: active.automatic } : null,
      queued: queue.map(function (job) { return { key: job.key, automatic: job.automatic }; }),
      startedKeys: Array.from(startedKeys)
    };
  }

  window.GroupV3TtsManager = Object.freeze({
    supported: supported,
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
