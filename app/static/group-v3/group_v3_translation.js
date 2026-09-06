(function installGroupTranslationController(window, document) {
  "use strict";

  var mounted = new WeakMap();
  var activeStates = new Set();
  var autoplayConsumed = window.__groupV3AutoplayConsumed || (window.__groupV3AutoplayConsumed = new Set());
  var autoplayQueued = window.__groupV3AutoplayQueued || (window.__groupV3AutoplayQueued = new Set());
  var realtimeEligible = window.__groupV3RealtimeEligible || (window.__groupV3RealtimeEligible = new Map());
  var historySeen = window.__groupV3HistorySeen || (window.__groupV3HistorySeen = new Map());
  var reconcileRequested = window.__groupV3RealtimeReconcile || (window.__groupV3RealtimeReconcile = new Set());
  var traces = [];
  function trace(state, stage, status, detail, segmentId) {
    // Never retain audio, transcript, credentials or complete response bodies.
    traces.push({ runtime: state && state.runtimeKey || "", stage: stage, status: status,
      detail: /^[a-zA-Z0-9_.-]{1,100}$/.test(String(detail || "")) ? String(detail) : "",
      segmentId: segmentId || "", at: Date.now() });
    if (traces.length > 100) traces.shift();
  }

  function runtime() {
    return window.GroupV3Runtime && window.GroupV3Runtime.snapshot ? window.GroupV3Runtime.snapshot() : null;
  }

  function translate(key) {
    try {
      var snapshot = runtime() || {};
      return window.GroupV3I18n.translator(snapshot.locale || "vi")(key);
    } catch (_error) {
      return key;
    }
  }

  function runtimeKey(snapshot) {
    snapshot = snapshot || {};
    var kind = String(snapshot.runtime_kind || "group");
    var id = String(snapshot.runtime_id || snapshot.space_id || "none");
    return kind + ":" + id;
  }

  function uuid() {
    return window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() :
      "segment-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  function labels() {
    return {
      vi: translate("vietnamese"),
      auto: translate("translationDetectLanguage"),
      en: translate("english"),
      "zh-TW": translate("traditionalChinese"),
      author: translate("translationAuthor"),
      received: translate("translationReceived"),
      original: translate("translationOriginal"),
      distributed: translate("translationDistributed"),
      showOriginal: translate("translationShowOriginal"),
      pending: translate("translationPending"),
      recipients: translate("recipients"),
      play: translate("translationPlay"),
      retry: translate("translationRetry"),
      failed: translate("translationVariantError"),
      noRecipients: translate("translationNoRecipients"), variants: translate("translationVariants")
    };
  }

  function stateFor(panel, snapshot) {
    var current = mounted.get(panel);
    var key = runtimeKey(snapshot);
    if (current && (current.runtimeKey !== key || current.disposed)) {
      disposeState(current);
      current = null;
    }
    if (!current) {
      current = {
        panel: panel,
        runtimeKey: key,
        generation: 0,
        historyLoaded: false,
        segments: new Map(),
        historySequence: 0,
        phase: "READY",
        timer: 0,
        submitting: false,
        recording: null,
        requests: new Set(),
        ttsText: "",
        ttsKey: "",
        ttsPlaying: false,
        historyPending: false,
        historyTimer: 0,
        historyAttempts: 0,
        historyDeadline: 0,
        refreshIntent: false,
        disposed: false
      };
      mounted.set(panel, current);
      activeStates.add(current);
    }
    current.panel = panel;
    return current;
  }

  function isCurrent(panel, state, generation) {
    var snapshot = runtime();
    return Boolean(snapshot && mounted.get(panel) === state && !state.disposed &&
      state.runtimeKey === runtimeKey(snapshot) && state.generation === generation);
  }

  function statusText(status) {
    var key = {
      READY: "translationReadyState",
      RECORDING: "translationRecording",
      STOPPING: "translationStopping",
      PROCESSING: "translationProcessing",
      PREPARING: "translationProcessing",
      PROCESSING_STT: "translationRecognizing",
      TRANSLATING: "translationProcessing",
      RESULT_READY: "translationResultReady",
      ERROR: "translationError"
    }[status];
    return translate(key || status);
  }

  function setStatus(panel, status) {
    var state = mounted.get(panel);
    if (state) state.phase = status;
    panel.dataset.translationState = status;
    var node = panel.querySelector("[data-v2-status]");
    if (node) node.textContent = statusText(status);
    var button = panel.querySelector('[data-v2-action="record"]');
    if (button) {
      var recording = status === "RECORDING";
      var busy = ["PREPARING", "STOPPING", "PROCESSING", "PROCESSING_STT", "TRANSLATING"].indexOf(status) >= 0;
      var key = recording ? "translationStopSave" : busy ? "translationProcessing" : "translationRecord";
      var symbol = recording ? "save" : busy ? "languages" : "mic";
      var elapsed = recording && state && state.recording ? " · " + Math.floor((Date.now() - state.recording.startedAt) / 1000) + "s" : "";
      button.innerHTML = (window.GroupV3Icon ? window.GroupV3Icon(symbol, 18) : "") + "<span>" + translate(key) + elapsed + "</span>";
      button.setAttribute("aria-label", translate(key));
      button.setAttribute("aria-pressed", String(recording));
      button.disabled = busy || !translationAvailable(panel, runtime());
      button.dataset.voiceIcon = symbol;
    }
    panel.querySelectorAll('textarea, select, input, [data-v2-action="send"]').forEach(function (control) {
      control.disabled = !translationAvailable(panel, runtime()) || ["READY", "RESULT_READY", "ERROR"].indexOf(status) < 0;
    });
  }

  function setError(panel, message, category) {
    var node = panel.querySelector("[data-v2-error]");
    if (!node) return;
    node.hidden = !message;
    node.textContent = message || "";
    node.dataset.errorCategory = message ? category || "TRANSLATION_VARIANT_ERROR" : "";
  }

  function reportTtsState(panel, state, detail) {
    var key = state === "UNSUPPORTED" || detail === "tts_unsupported"
      ? "translationTtsUnavailable"
      : state === "VOICE_LOADING"
        ? "translationTtsVoiceLoading"
        : state === "UNLOCK_REQUIRED" || state === "BLOCKED"
          ? "translationTtsActivationRequired"
          : "translationTtsError";
    var message = translate(key);
    setError(panel, message, state === "UNSUPPORTED" ? "TTS_UNSUPPORTED" : "TTS_PLAYBACK_STATE");
    if (panel === document.body) {
      window.dispatchEvent(new CustomEvent("group-v3:tts-error", { detail: {
        code: String(detail || state || "tts_error"), state: state || "ERROR"
      } }));
    }
  }
  function warning(panel, message) {
    var node = panel.querySelector("[data-v2-warning]");
    if (!node) return;
    node.hidden = !message;
    node.querySelector("span").textContent = message || "";
  }

  function errorText(error, fallbackKey) {
    if (error && error.name === "AbortError") return "";
    var code = String(error && (error.code || error.message) || "").toLowerCase();
    var known = {
      translation_request_failed: "translationError",
      group_translation_history_failed: "translationHistoryError",
      group_translation_profile_failed: "translationProfileError",
      group_translation_runtime_not_active: "translationUnavailable",
      group_translation_participant_required: "translationUnavailable",
      group_translation_voice_consent_required: "translationConsentRequired",
      group_translation_provider_not_configured: "translationProviderUnavailable"
      ,group_translation_detected_language_unsupported: "group_translation_detected_language_unsupported"
    };
    var key = known[code] || fallbackKey || "translationError";
    var value = translate(key);
    return value === key ? translate("translationError") : value;
  }

  function api(path, options, state) {
    options = options || {};
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    var init = Object.assign({}, options, { credentials: "same-origin", cache: "no-store" });
    var stage = /\/profile$/.test(path) ? "PROFILE" : /v2-history/.test(path) ? "HISTORY_SYNC" :
      /segments\/voice/.test(path) ? "STT" : "TRANSLATION_VARIANT";
    init.headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    if (controller) {
      init.signal = controller.signal;
      if (state) state.requests.add(controller);
    }
    return fetch(path, init).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          var error = new Error(String(payload.detail || payload.error || "translation_request_failed"));
          error.code = String(payload.detail || payload.error || "translation_request_failed");
          error.status = response.status;
          error.payload = payload;
          error.category = stage + "_ERROR";
          trace(state, stage, response.status, error.code);
          throw error;
        }
        trace(state, stage, response.status, "", payload.segment && payload.segment.id);
        return payload;
      });
    }).catch(function (error) {
      if (!error.category) {
        error.category = stage + "_ERROR";
        trace(state, stage, error.status || 0, error.code || error.name);
      }
      throw error;
    }).finally(function () {
      if (controller && state) state.requests.delete(controller);
    });
  }

  function endpoint(snapshot, suffix) {
    return "/api/group/spaces/" + encodeURIComponent(snapshot.space_id) + "/translation/" + suffix;
  }

  function translationAvailable(panel, snapshot) {
    if (!snapshot || !snapshot.space_id || !snapshot.runtime_id) return false;
    if (snapshot.media_connected === false) return false;
    if (document.querySelector(".prejoin-backdrop")) return false;
    var content = panel.closest(".chat-content, .radio-content");
    if (!content) return true;
    var classes = String(content.className || "");
    return !/(state-ringing|state-connecting|state-prejoin|state-answering)/i.test(classes) &&
      !content.querySelector(".incoming-stage, .decision-stage");
  }

  function setAvailability(panel, available) {
    var state = mounted.get(panel);
    if (state && state.available === available) return;
    if (state) state.available = available;
    var message = panel.querySelector("[data-v2-availability]");
    var controls = panel.querySelectorAll("textarea, select, input, button[data-v2-action]");
    controls.forEach(function (control) { control.disabled = !available; });
    if (available && state) setStatus(panel, state.phase);
    if (!message) return;
    message.hidden = available;
    message.textContent = available ? "" : translate("translationUnavailable");
  }

  function renderHistory(panel, segments) {
    var host = panel.querySelector("[data-v2-history]");
    if (!host) return;
    if (!segments || !segments.length) {
      host.innerHTML = '<p class="group-translation-v2__empty">' +
        String(translate("historyEmpty")).replaceAll("<", "&lt;") + "</p>";
      return;
    }
    host.innerHTML = segments.map(function (item) {
      return window.GroupV3TranslationView.historyItem(item, labels());
    }).join("");
  }

  function playbackKey(snapshot, item) {
    return runtimeKey(snapshot) + ":" + String(item && item.id || "") + ":" +
      String(item && (item.display_language || item.target_language) || "") + ":" + String(item && item.state || "FINAL");
  }

  function idSet(store, snapshot) {
    var key = runtimeKey(snapshot);
    var values = store.get(key);
    if (!values) {
      values = new Set();
      store.set(key, values);
    }
    return values;
  }

  function observeHistory(segments, snapshot) {
    if (!snapshot || !snapshot.runtime_id) return;
    var key = runtimeKey(snapshot);
    var seen = historySeen.get(key);
    if (!seen) {
      seen = idSet(historySeen, snapshot);
      (segments || []).forEach(function (item) { if (item && item.id) seen.add(String(item.id)); });
      reconcileRequested.delete(key);
      return;
    }
    var eligible = idSet(realtimeEligible, snapshot);
    (segments || []).forEach(function (item) {
      if (!item || !item.id) return;
      var id = String(item.id);
      if (reconcileRequested.has(key) && !seen.has(id)) eligible.add(id);
      seen.add(id);
    });
    reconcileRequested.delete(key);
  }

  function markRealtimeEligible(detail) {
    var snapshot = runtime();
    var eventType = String(detail && detail.type || "");
    var id = String(detail && (detail.resource_id || detail.id) || "");
    if (!snapshot || !snapshot.runtime_id || !id || eventType === "translation.segment.history_changed") return;
    idSet(realtimeEligible, snapshot).add(id);
  }

  function setButtonPlayback(panel, text, playing) {
    panel.querySelectorAll("[data-v2-play]").forEach(function (button) {
      if (button.dataset.v2Play === text) button.setAttribute("aria-pressed", String(playing));
    });
  }

  function stopPlayback() {
    if (window.GroupV3TtsManager) window.GroupV3TtsManager.cancel();
    activeStates.forEach(function (state) {
      state.ttsPlaying = false;
      setButtonPlayback(state.panel, state.ttsText, false);
      state.ttsText = "";
      state.ttsKey = "";
    });
  }

  function play(text, language, panel, automatic, key) {
    var state = mounted.get(panel);
    if (!text || !state || state.disposed) return false;
    var manager = window.GroupV3TtsManager;
    if (!manager || !manager.supported()) {
      reportTtsState(panel, "UNSUPPORTED", "tts_unsupported");
      return false;
    }
    if (!automatic && state.ttsPlaying && state.ttsText === text) {
      stopPlayback();
      return true;
    }
    if (!automatic) stopPlayback();
    if (!automatic) state.ttsText = text;
    state.ttsKey = key || "";
    var playback = automatic ? String(key || "") : String(key || "manual") + "-" + Date.now() + "-" + Math.random().toString(16).slice(2);
    var options = {
      key: playback,
      text: text,
      language: language,
      automatic: automatic,
      onState: function (playbackState, detail) {
        if (playbackState === "STARTED") {
          if (!automatic) state.ttsPlaying = true;
          setButtonPlayback(panel, text, true);
          if (automatic) autoplayConsumed.add(playback);
          autoplayQueued.delete(playback);
          setError(panel, "");
        }
        if (["VOICE_LOADING", "UNLOCK_REQUIRED", "BLOCKED"].indexOf(playbackState) >= 0) {
          reportTtsState(panel, playbackState, detail);
        }
        if (playbackState === "COMPLETED" || playbackState === "FAILED") {
          if (!automatic) {
            state.ttsPlaying = false;
            state.ttsText = "";
            state.ttsKey = "";
          }
          autoplayQueued.delete(playback);
          setButtonPlayback(panel, text, false);
          if (playbackState === "FAILED" && detail !== "tts_cancelled") {
            reportTtsState(panel, detail === "tts_unsupported" ? "UNSUPPORTED" : "ERROR", detail);
          }
        }
      }
    };
    var accepted = automatic ? manager.enqueue(options) : manager.playManual(options);
    if (automatic && accepted) autoplayQueued.add(playback);
    if (!accepted && automatic && manager.hasStarted(playback)) autoplayConsumed.add(playback);
    if (!automatic) setError(panel, "");
    return accepted;
  }

  // Archive/Radio playback is generated from authorized TEXT, never a recorded file.
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-v2-play]");
    if (!button || button.closest("[data-v2-panel]")) return;
    var snapshot = runtime() || {};
    if (snapshot.device_lost) return;
    var state = stateFor(document.body, snapshot);
    state.archive = true;
    play(button.dataset.v2Play, button.dataset.v2Language, document.body, false, "archive");
  });

  function maybeAutoRead(segments, panel, snapshot) {
    if (!snapshot || !snapshot.auto_read || snapshot.device_lost || snapshot.media_connected === false) return;
    var eligible = idSet(realtimeEligible, snapshot);
    (segments || []).slice().sort(function (a, b) {
      return (Date.parse(a.created_at) || 0) - (Date.parse(b.created_at) || 0) || String(a.id || "").localeCompare(String(b.id || ""));
    }).forEach(function (item) {
      if (!item || item.state !== "FINAL" || item.author_view || !item.translated_text ||
        String(item.speaker_membership_id || "") === String(snapshot.membership_id || "")) return;
      if (!eligible.has(String(item.id || ""))) return;
      var playback = playbackKey(snapshot, item);
      if (autoplayConsumed.has(playback) || autoplayQueued.has(playback)) return;
      play(item.translated_text, item.display_language || item.target_language, panel, true, playback);
    });
  }

  function readRadioHistory(segments) {
    var snapshot = runtime();
    if (!snapshot || snapshot.runtime_kind !== "radio" || !snapshot.runtime_id) return;
    var state = stateFor(document.body, snapshot);
    state.archive = true;
    observeHistory(segments, snapshot);
    maybeAutoRead(segments, document.body, snapshot);
  }

  function containsProcessing(segments) {
    return (segments || []).some(function (segment) { return segment && segment.state === "PROCESSING"; });
  }

  function requestHistoryRefresh(panel) {
    var state = mounted.get(panel);
    if (!state || state.disposed) return;
    state.refreshIntent = true;
    if (state.recording || state.submitting || state.historyPending) return;
    state.refreshIntent = false;
    loadHistory(panel);
  }

  function scheduleHistoryConvergence(panel, state, segments) {
    window.clearTimeout(state.historyTimer);
    state.historyTimer = 0;
    if (!containsProcessing(segments)) {
      state.historyAttempts = 0;
      state.historyDeadline = 0;
      return;
    }
    if (!state.historyDeadline) state.historyDeadline = Date.now() + 15000;
    if (Date.now() >= state.historyDeadline || state.historyAttempts >= 6) return;
    var delays = [400, 800, 1400, 2200, 3200, 4500];
    var delay = delays[Math.min(state.historyAttempts, delays.length - 1)];
    state.historyAttempts += 1;
    state.historyTimer = window.setTimeout(function () { requestHistoryRefresh(panel); }, delay);
  }

  function loadHistory(panel) {
    var snapshot = runtime();
    var state = stateFor(panel, snapshot);
    if (!translationAvailable(panel, snapshot)) {
      setAvailability(panel, false);
      return Promise.resolve([]);
    }
    setAvailability(panel, true);
    state.historyPending = true;
    var generation = state.generation;
    var sequence = ++state.historySequence;
    var query = "v2-history?runtime_kind=" + encodeURIComponent(snapshot.runtime_kind) +
      "&runtime_id=" + encodeURIComponent(snapshot.runtime_id) + "&limit=50";
    return api(endpoint(snapshot, query), {}, state).then(function (payload) {
      if (!isCurrent(panel, state, generation) || sequence !== state.historySequence) return [];
      var segments = payload.segments || [];
      observeHistory(segments, snapshot);
      if (state.phase === "PROCESSING_STT" && segments.some(function (segment) {
        return segment.client_segment_id === state.pendingSegmentId && segment.source_text;
      })) setStatus(panel, "TRANSLATING");
      segments.forEach(function (segment) { state.segments.set(String(segment.id), segment); });
      var ordered = Array.from(state.segments.values()).sort(function (a, b) {
        return (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0);
      }).slice(0, 50);
      state.segments = new Map(ordered.map(function (segment) { return [String(segment.id), segment]; }));
      renderHistory(panel, ordered);
      maybeAutoRead(segments, panel, snapshot);
      scheduleHistoryConvergence(panel, state, segments);
      state.historyLoaded = true;
      warning(panel, "");
      return segments;
    }).catch(function (error) {
      if (!isCurrent(panel, state, generation) || error.name === "AbortError") return [];
      warning(panel, errorText(error, "translationHistoryError"));
      return [];
    }).finally(function () {
      if (sequence === state.historySequence) state.historyPending = false;
      if (state.refreshIntent && !state.recording && !state.submitting) window.queueMicrotask(function () { requestHistoryRefresh(panel); });
    });
  }

  function syncSharedProfile(profile) {
    if (!profile) return;
    if (window.GroupV3Runtime && typeof window.GroupV3Runtime.updateProfile === "function") {
      window.GroupV3Runtime.updateProfile(profile);
    }
  }

  function saveProfile(panel) {
    var snapshot = runtime();
    var state = mounted.get(panel);
    if (!snapshot || !state || !snapshot.space_id) return Promise.reject(new Error("translationUnavailable"));
    var source = panel.querySelector("[data-v2-source]");
    var target = panel.querySelector("[data-v2-target]");
    var autoRead = panel.querySelector("[data-v2-auto-read]");
    return api(endpoint(snapshot, "profile"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        spoken_language: source && source.value !== "auto" && source.value || snapshot.spoken_language || "vi",
        preferred_output_language: target && target.value || snapshot.target_language || "vi",
        auto_translate_enabled: Boolean(snapshot.auto_translate),
        auto_read_enabled: Boolean(autoRead && autoRead.checked),
        show_original_enabled: true
      })
    }, state).then(function (payload) {
      syncSharedProfile(payload.profile);
      setError(panel, "");
      return payload.profile;
    });
  }

  function mergeSegment(panel, item) {
    if (!item) return;
    var state = mounted.get(panel);
    if (state) state.segments.set(String(item.id), item);
    var host = panel.querySelector("[data-v2-history]");
    if (!host) return;
    host.querySelectorAll(".group-translation-v2__empty").forEach(function (node) { node.remove(); });
    var existing = Array.from(host.querySelectorAll("[data-segment-id]")).find(function (node) {
      return node.dataset.segmentId === String(item.id || "");
    });
    var html = window.GroupV3TranslationView.historyItem(item, labels());
    if (existing) existing.outerHTML = html;
    else host.insertAdjacentHTML("afterbegin", html);
  }

  function submitText(panel) {
    var snapshot = runtime();
    var state = mounted.get(panel);
    var text = panel.querySelector("[data-v2-text]");
    var source = panel.querySelector("[data-v2-source]");
    var sourceText = text && String(text.value || "").trim();
    if (!translationAvailable(panel, snapshot)) {
      setError(panel, translate("translationUnavailable"));
      return Promise.reject(new Error("translationUnavailable"));
    }
    if (!snapshot || !state || !snapshot.space_id || !snapshot.runtime_id || !sourceText) return Promise.resolve(null);
    state.submitting = true;
    var clientSegmentId = uuid();
    setError(panel, "");
    setStatus(panel, "PROCESSING");
    return api(endpoint(snapshot, "segments/text"), {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": clientSegmentId },
      body: JSON.stringify({
        runtime_kind: snapshot.runtime_kind,
        runtime_id: snapshot.runtime_id,
        client_segment_id: clientSegmentId,
        source_language: source && source.value || snapshot.spoken_language || "vi",
        source_text: sourceText
      })
    }, state).then(function (payload) {
      if (text) text.value = "";
      var item = payload.segment;
      mergeSegment(panel, item);
      completeSegment(panel, item);
      return loadHistory(panel).then(function () { return item; });
    }).catch(function (error) {
      if (error.name !== "AbortError") {
        setStatus(panel, "ERROR");
        setError(panel, errorText(error), error.category);
      }
      throw error;
    }).finally(function () {
      state.submitting = false;
      if (state.refreshIntent) window.queueMicrotask(function () { requestHistoryRefresh(panel); });
    });
  }

  function completeSegment(panel, item) {
    var failed = item && (item.state === "FAILED" || item.state === "PARTIAL" ||
      (item.variants || []).some(function (variant) { return variant.state === "FAILED"; }));
    setStatus(panel, failed ? "ERROR" : "RESULT_READY");
    if (failed) {
      setError(panel, translate("translationVariantError"), "TRANSLATION_VARIANT_ERROR");
      trace(mounted.get(panel), "TRANSLATION_VARIANT", 200, item.failure_code, item.id);
    } else setError(panel, "");
  }

  function recordingFailure(panel, message, category) {
    var state = mounted.get(panel);
    if (state) {
      window.clearInterval(state.timer);
      state.timer = 0;
      state.submitting = false;
    }
    setStatus(panel, "ERROR");
    setError(panel, message, category || "RECORDING_ERROR");
    trace(state, category || "RECORDING_ERROR", 0, category || "RECORDING_ERROR");
  }

  function stopRecording(panel) {
    var state = mounted.get(panel), recording = state && state.recording;
    if (!recording || recording.recorder.state !== "recording") return;
    window.clearInterval(state.timer);
    state.timer = 0;
    recording.durationMs = Math.max(1, Date.now() - recording.startedAt);
    setStatus(panel, "STOPPING");
    try { recording.recorder.stop(); }
    catch (_error) {
      recording.failed = true;
      state.recording = null;
      recordingFailure(panel, translate("translationRecordingError"));
    }
  }

  function startRecording(panel) {
    var snapshot = runtime(), state = mounted.get(panel);
    var track = window.GroupV3Runtime && window.GroupV3Runtime.getLocalAudioTrack && window.GroupV3Runtime.getLocalAudioTrack();
    if (!state || state.disposed) return;
    if (!translationAvailable(panel, snapshot) || !track || track.readyState !== "live" ||
        track.enabled === false || track.muted || !window.MediaRecorder || typeof window.MediaStream !== "function") {
      recordingFailure(panel, translate("translationMicUnavailable"));
      return;
    }
    if (snapshot.consent_status !== "granted") {
      recordingFailure(panel, translate("translationConsentRequired"));
      return;
    }
    if (state.recording) return;
    var recorder;
    var mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find(function (candidate) {
      return MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(candidate);
    });
    try {
      // Wrap, never clone/stop/acquire the Group owner's microphone track.
      recorder = new MediaRecorder(new MediaStream([track]), mime ? { mimeType: mime } : undefined);
    } catch (_error) {
      recordingFailure(panel, translate("translationRecordingError"));
      return;
    }
    var generation = ++state.generation, chunks = [], segmentId = uuid();
    state.pendingSegmentId = segmentId;
    var source = panel.querySelector("[data-v2-source]");
    var recording = { recorder: recorder, generation: generation, snapshot: snapshot,
      segmentId: segmentId, chunks: chunks, startedAt: Date.now(), durationMs: 0, failed: false,
      sourceLanguage: source && source.value || snapshot.spoken_language || "vi" };
    state.recording = recording;
    state.submitting = true;
    recorder.addEventListener("dataavailable", function (event) {
      if (event.data && event.data.size) chunks.push(event.data);
    });
    recorder.addEventListener("error", function () {
      recording.failed = true;
      state.recording = null;
      if (isCurrent(panel, state, generation)) recordingFailure(panel, translate("translationRecordingError"));
    });
    recorder.addEventListener("stop", function () {
      window.clearInterval(state.timer);
      state.timer = 0;
      if (state.recording === recording) state.recording = null;
      if (!isCurrent(panel, state, generation) || recording.failed) return;
      var actualMime = recorder.mimeType || (chunks[0] && chunks[0].type) || mime || "";
      var extension = /mp4|m4a/.test(actualMime) ? "m4a" : /ogg/.test(actualMime) ? "ogg" : /webm/.test(actualMime) ? "webm" : "";
      if (!chunks.length || !chunks.some(function (chunk) { return chunk.size > 0; })) {
        recordingFailure(panel, translate("translationEmptyAudio"), "EMPTY_AUDIO_ERROR");
        return;
      }
      if (!extension) {
        recordingFailure(panel, translate("translationRecordingError"));
        return;
      }
      var form = new FormData();
      form.append("audio", new Blob(chunks, { type: actualMime }), "group-translation." + extension);
      form.append("runtime_kind", snapshot.runtime_kind);
      form.append("runtime_id", snapshot.runtime_id);
      form.append("client_segment_id", segmentId);
      form.append("source_language", recording.sourceLanguage);
      form.append("duration_seconds", String((recording.durationMs || Math.max(1, Date.now() - recording.startedAt)) / 1000));
      setStatus(panel, "PROCESSING_STT");
      api(endpoint(snapshot, "segments/voice"), {
        method: "POST", headers: { "Idempotency-Key": segmentId }, body: form
      }, state).then(function (payload) {
        if (!isCurrent(panel, state, generation)) return;
        // The synchronous endpoint returns STT + variants together; no invented
        // timer/progress estimate. Translate phase projects those returned variants.
        setStatus(panel, "TRANSLATING");
        mergeSegment(panel, payload.segment);
        completeSegment(panel, payload.segment);
        return loadHistory(panel);
      }).catch(function (error) {
        if (isCurrent(panel, state, generation) && error.name !== "AbortError") {
          recordingFailure(panel, errorText(error, "translationSttError"), error.category || "STT_ERROR");
        }
      }).finally(function () {
        if (!state.disposed) state.submitting = false;
        if (state.refreshIntent) window.queueMicrotask(function () { requestHistoryRefresh(panel); });
      });
    }, { once: true });
    setError(panel, "");
    try {
      recorder.start();
      setStatus(panel, "RECORDING");
      state.timer = window.setInterval(function () {
        if (state.recording === recording && !state.disposed) setStatus(panel, "RECORDING");
      }, 1000);
    } catch (_error) {
      recording.failed = true;
      state.recording = null;
      recordingFailure(panel, translate("translationRecordingError"));
    }
  }

  function handleFailure(panel, error) {
    if (!error || error.name === "AbortError") return;
    setError(panel, errorText(error, error.category === "PROFILE_ERROR" ? "translationProfileError" : undefined), error.category);
    if (panel.dataset.translationState !== "RECORDING" && panel.dataset.translationState !== "STOPPING") setStatus(panel, "ERROR");
  }

  function bind(panel) {
    var snapshot = runtime();
    if (!snapshot) return;
    var existing = mounted.get(panel);
    if (existing && existing.runtimeKey === runtimeKey(snapshot) && !existing.disposed) {
      if (translationAvailable(panel, snapshot) || !existing.submitting) {
        setAvailability(panel, translationAvailable(panel, snapshot));
        if (translationAvailable(panel, snapshot) && !existing.historyLoaded && !existing.historyPending) loadHistory(panel);
        return;
      }
      // A terminal media transition invalidates pending capture/requests.
      disposeState(existing);
    }
    if (existing) disposeState(existing);
    var state = stateFor(panel, snapshot);
    panel.dataset.translationRuntime = state.runtimeKey;
    panel.innerHTML = window.GroupV3TranslationView.panel({
      title: translate("translationPlugin"),
      subtitle: translate("translationTextFirst"),
      readyLabel: statusText("READY"),
      source: snapshot.spoken_language || "vi",
      target: snapshot.target_language || "vi",
      autoRead: Boolean(snapshot.auto_read),
      labels: labels(),
      sourceLabel: translate("spokenLanguageLabel"),
      targetLabel: translate("preferredOutputLabel"),
      placeholder: translate("translationTextPlaceholder"),
      sendLabel: translate("translationSend"),
      recordLabel: translate("translationRecord"),
      autoReadLabel: translate("autoReadRecipient"),
      emptyLabel: translate("historyEmpty")
    });
    setAvailability(panel, translationAvailable(panel, snapshot));
    panel.querySelector('[data-v2-action="send"]').addEventListener("click", function () {
      if (state.submitting || state.recording || !panel.querySelector("[data-v2-text]").value.trim()) return;
      state.submitting = true;
      setStatus(panel, "PREPARING");
      saveProfile(panel).then(function () { return submitText(panel); }).catch(function (error) { handleFailure(panel, error); })
        .finally(function () {
          state.submitting = false;
          if (state.refreshIntent) window.queueMicrotask(function () { requestHistoryRefresh(panel); });
        });
    });
    panel.querySelector('[data-v2-action="record"]').addEventListener("click", function () {
      var current = mounted.get(panel);
      if (current && current.recording) stopRecording(panel);
      else if (current && !current.submitting) {
        current.submitting = true;
        setStatus(panel, "PREPARING");
        saveProfile(panel).then(function () { startRecording(panel); }).catch(function (error) {
          current.submitting = false;
          handleFailure(panel, error);
        });
      }
    });
    ["[data-v2-target]", "[data-v2-source]", "[data-v2-auto-read]"].forEach(function (selector) {
      var control = panel.querySelector(selector);
      if (control) control.addEventListener("change", function () {
        saveProfile(panel).then(function () { return loadHistory(panel); }).catch(function (error) { handleFailure(panel, error); });
      });
    });
    panel.addEventListener("click", function (event) {
      if (event.target.closest("[data-v2-history-retry]")) { loadHistory(panel); return; }
      var playButton = event.target.closest && event.target.closest("[data-v2-play]");
      if (playButton) {
        play(playButton.dataset.v2Play, playButton.dataset.v2Language, panel, false, "manual");
        return;
      }
      var retry = event.target.closest && event.target.closest("[data-v2-retry]");
      if (!retry) return;
      var currentSnapshot = runtime();
      var currentState = mounted.get(panel);
      if (!currentSnapshot || !currentState || currentState.submitting || currentState.recording) return;
      currentState.submitting = true;
      setStatus(panel, "TRANSLATING");
      api(endpoint(currentSnapshot, "segments/" + encodeURIComponent(retry.dataset.v2Retry) + "/variants/" + encodeURIComponent(retry.dataset.v2TargetLanguage) + "/retry"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_language: retry.dataset.v2TargetLanguage })
      }, currentState).then(function (payload) {
        mergeSegment(panel, payload.segment);
        completeSegment(panel, payload.segment);
        return loadHistory(panel);
      }).catch(function (error) { handleFailure(panel, error); }).finally(function () {
        currentState.submitting = false;
        if (currentState.refreshIntent) window.queueMicrotask(function () { requestHistoryRefresh(panel); });
      });
    });
    loadHistory(panel);
  }

  function disposeState(state) {
    if (!state || state.disposed) return;
    state.disposed = true;
    window.clearInterval(state.timer);
    window.clearTimeout(state.historyTimer);
    state.timer = 0;
    state.historyTimer = 0;
    state.generation += 1;
    state.requests.forEach(function (controller) { try { controller.abort(); } catch (_error) {} });
    state.requests.clear();
    if (state.recording && state.recording.recorder) {
      try {
        if (state.recording.recorder.state !== "inactive") state.recording.recorder.stop();
      } catch (_error) {}
    }
    state.recording = null;
    activeStates.delete(state);
  }

  function cleanupDetached() {
    activeStates.forEach(function (state) {
      if (!state.panel || !document.documentElement.contains(state.panel)) disposeState(state);
    });
  }

  function mountAll() {
    cleanupDetached();
    document.querySelectorAll("[data-group-translation-v2]").forEach(bind);
  }

  function cleanup() {
    activeStates.forEach(disposeState);
    stopPlayback();
  }

  window.addEventListener("group-v3:rendered", mountAll);
  function reconcileHistories() {
    activeStates.forEach(function (state) {
      if (!state.disposed && !state.archive) requestHistoryRefresh(state.panel);
    });
  }
  window.addEventListener("group-v3:translation-segment", function (event) {
    markRealtimeEligible(event.detail || {});
    reconcileHistories();
  });
  window.addEventListener("group-v3:translation-reconcile", function () {
    var snapshot = runtime();
    if (snapshot && snapshot.runtime_id) reconcileRequested.add(runtimeKey(snapshot));
    reconcileHistories();
  });
  window.addEventListener("group-video-layout:change", mountAll);
  window.addEventListener("group-v3:media-disconnected", cleanup);
  window.addEventListener("pagehide", cleanup, { once: true });
  window.addEventListener("beforeunload", cleanup, { once: true });
  new MutationObserver(mountAll).observe(document.documentElement, { childList: true, subtree: true });
  window.GroupV3TranslationController = Object.freeze({ mountAll: mountAll, loadHistory: loadHistory, cleanup: cleanup, play: play, stopPlayback: stopPlayback, readRadioHistory: readRadioHistory,
    diagnostics: function () { return traces.slice(); } });
  mountAll();
}(window, document));
