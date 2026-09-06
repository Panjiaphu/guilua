(function installGroupCommunicationWorkspace(window, document) {
  "use strict";

  /* Presentation-only state. Media rooms, tracks, translation and radio floor
     remain mounted and owned by their existing runtimes. */
  var MOBILE_VIDEO_MODES = ["COMPACT", "STANDARD", "MAXIMIZED"];
  var DESKTOP_VIDEO_MODES = ["STANDARD", "MAXIMIZED"];
  var TRANSLATION_MODES = ["COLLAPSED", "HALF", "FULL"];
  var DESKTOP_TRANSLATION_MODES = ["CLOSED", "NORMAL", "WIDE"];
  var RADIO_MODES = ["COMPACT", "STANDARD", "MAXIMIZED"];

  var state = {
    runtimeKey: "",
    surface: "",
    requested: {
      mediaMode: "STANDARD",
      translationMode: "COLLAPSED",
      radioMode: "STANDARD",
      radioTranslationMode: "COLLAPSED"
    },
    effective: {
      mediaMode: "STANDARD",
      translationMode: "COLLAPSED",
      desktopTranslationMode: "CLOSED",
      radioMode: "STANDARD",
      radioTranslationMode: "COLLAPSED"
    },
    overlay: { participantsOpen: false, moreOpen: false },
    viewport: {
      orientation: "portrait",
      keyboardOpen: false,
      visualHeight: 0,
      mobile: false
    },
    active: false
  };
  var lastVideoIntent = "video";

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function isMobile(target) {
    var native = target && target.querySelector ? target.querySelector(".native-app") : null;
    if (native) return native.classList.contains("native-mobile");
    return Boolean(window.matchMedia && window.matchMedia("(max-width: 640px)").matches);
  }

  function normalize(value, list, fallback) {
    var candidate = String(value || "").toUpperCase();
    return list.indexOf(candidate) >= 0 ? candidate : fallback;
  }

  function canonicalTranslation(value) {
    var candidate = String(value || "").toUpperCase();
    if (candidate === "CLOSED") return "COLLAPSED";
    if (candidate === "NORMAL") return "HALF";
    if (candidate === "WIDE") return "FULL";
    return normalize(candidate, TRANSLATION_MODES, "COLLAPSED");
  }

  function desktopTranslation(value) {
    var candidate = canonicalTranslation(value);
    return candidate === "FULL" ? "WIDE" : candidate === "HALF" ? "NORMAL" : "CLOSED";
  }

  function resetForRuntime(runtimeKey, surface) {
    lastVideoIntent = "video";
    state.runtimeKey = String(runtimeKey || "");
    state.surface = String(surface || "");
    state.requested = {
      mediaMode: "STANDARD",
      translationMode: "COLLAPSED",
      radioMode: "STANDARD",
      radioTranslationMode: "COLLAPSED"
    };
    state.effective = {
      mediaMode: "STANDARD",
      translationMode: "COLLAPSED",
      desktopTranslationMode: "CLOSED",
      radioMode: "STANDARD",
      radioTranslationMode: "COLLAPSED"
    };
    state.overlay = { participantsOpen: false, moreOpen: false };
  }

  function ensureRuntime(runtimeKey, surface) {
    var key = String(runtimeKey || surface || "");
    if (!key) return;
    if (state.runtimeKey !== key || state.surface !== String(surface || "")) resetForRuntime(key, surface);
  }

  function deriveEffective() {
    var requested = state.requested;
    var mobile = state.viewport.mobile;
    var mediaMode = mobile
      ? normalize(requested.mediaMode, MOBILE_VIDEO_MODES, "STANDARD")
      : normalize(requested.mediaMode, DESKTOP_VIDEO_MODES, "STANDARD");
    var translationMode = canonicalTranslation(requested.translationMode);
    var radioMode = normalize(requested.radioMode, RADIO_MODES, "STANDARD");
    var radioTranslationMode = canonicalTranslation(requested.radioTranslationMode);

    /* Suppression is effective-only: requested values are restored when the
       user exits the temporary immersive mode. */
    if (state.surface === "video" && mediaMode === "MAXIMIZED") {
      if (lastVideoIntent === "translation" && translationMode !== "COLLAPSED") mediaMode = "STANDARD";
      else translationMode = "COLLAPSED";
    }
    if (state.surface === "video" && translationMode === "FULL") mediaMode = mobile ? "COMPACT" : "STANDARD";
    if (state.surface === "radio" && radioTranslationMode === "FULL") radioMode = "COMPACT";

    state.effective = {
      mediaMode: mediaMode,
      translationMode: translationMode,
      desktopTranslationMode: desktopTranslation(translationMode),
      radioMode: radioMode,
      radioTranslationMode: radioTranslationMode
    };
  }

  function legacySnapshot() {
    var effective = state.effective;
    var requested = state.requested;
    return {
      runtimeKey: state.runtimeKey,
      surface: state.surface,
      active: state.active,
      orientation: state.viewport.orientation,
      keyboardOpen: state.viewport.keyboardOpen,
      visualHeight: state.viewport.visualHeight,
      mobile: state.viewport.mobile,
      requested: clone(requested),
      effective: clone(effective),
      overlay: clone(state.overlay),
      videoMode: effective.mediaMode,
      requestedVideoMode: requested.mediaMode,
      translationMode: requested.translationMode,
      effectiveTranslationMode: effective.translationMode,
      requestedTranslationMode: requested.translationMode,
      desktopTranslationMode: effective.desktopTranslationMode,
      radioMode: effective.radioMode,
      requestedRadioMode: requested.radioMode,
      radioTranslationMode: effective.radioTranslationMode,
      requestedRadioTranslationMode: requested.radioTranslationMode
    };
  }

  function snapshot() {
    return clone(legacySnapshot());
  }

  function emit() {
    apply();
    window.dispatchEvent(new CustomEvent("group-workspace:change", { detail: snapshot() }));
  }

  function setVideoMode(next) {
    var list = state.viewport.mobile ? MOBILE_VIDEO_MODES : DESKTOP_VIDEO_MODES;
    var candidate = String(next || "").toUpperCase();
    if (candidate === "BALANCED") candidate = "STANDARD";
    if (candidate === "FULL") candidate = "MAXIMIZED";
    state.requested.mediaMode = normalize(candidate, list, "STANDARD");
    lastVideoIntent = "video";
    emit();
    return snapshot();
  }

  function setTranslationMode(next, radio) {
    var mode = canonicalTranslation(next);
    if (radio) state.requested.radioTranslationMode = mode;
    else {
      state.requested.translationMode = mode;
      lastVideoIntent = "translation";
    }
    emit();
    return snapshot();
  }

  function setRadioMode(next) {
    state.requested.radioMode = normalize(next, RADIO_MODES, "STANDARD");
    emit();
    return snapshot();
  }

  function step(list, current, delta) {
    var index = list.indexOf(String(current || "").toUpperCase());
    if (index < 0) index = 0;
    index = Math.max(0, Math.min(list.length - 1, index + Number(delta || 0)));
    return list[index];
  }

  function stepVideo(delta) {
    var list = state.viewport.mobile ? MOBILE_VIDEO_MODES : DESKTOP_VIDEO_MODES;
    return setVideoMode(step(list, state.effective.mediaMode, delta));
  }

  function stepTranslation(delta, radio) {
    var current = radio ? state.effective.radioTranslationMode : state.effective.translationMode;
    return setTranslationMode(step(TRANSLATION_MODES, current, delta), radio);
  }

  function stepRadio(delta) {
    return setRadioMode(step(RADIO_MODES, state.requested.radioMode, delta));
  }

  function setRuntime(runtimeKey, surface) {
    ensureRuntime(runtimeKey, surface);
    apply();
    return snapshot();
  }

  function apply(target) {
    target = target || document.getElementById("group-native-app");
    if (!target) return snapshot();
    var native = target.querySelector(".native-app");
    var surface = native && native.dataset.state || "";
    var runtimeKey = native && native.dataset.runtimeKey || surface || "";
    state.viewport.mobile = isMobile(target);
    state.viewport.orientation = window.innerWidth > window.innerHeight ? "landscape" : "portrait";
    state.viewport.visualHeight = Math.round((window.visualViewport && window.visualViewport.height) || window.innerHeight || 0);
    state.viewport.keyboardOpen = document.body.classList.contains("group-keyboard-open") || Boolean(target.dataset.keyboardState === "OPEN");
    ensureRuntime(runtimeKey, surface);
    var media = Boolean(native && native.querySelector(".video-call-layout, .call-communication-layout, .radio-room, .radio-content.state-ready, .radio-content.state-talking, .radio-content.state-floor_busy, .radio-content.state-finalizing_burst, .radio-content.state-device_lost, .radio-content.state-disconnected"));
    state.active = media && (surface === "video" || surface === "call" || surface === "radio");
    deriveEffective();

    var effective = state.effective;
    var requested = state.requested;
    target.dataset.runtimeKey = state.runtimeKey;
    target.dataset.surface = state.surface;
    target.dataset.videoMode = effective.mediaMode;
    target.dataset.videoRequestedMode = requested.mediaMode;
    target.dataset.translationMode = effective.translationMode;
    target.dataset.desktopTranslationMode = effective.desktopTranslationMode;
    target.dataset.translationRequestedMode = requested.translationMode;
    target.dataset.radioMode = effective.radioMode;
    target.dataset.radioRequestedMode = requested.radioMode;
    target.dataset.radioTranslationMode = effective.radioTranslationMode;
    target.dataset.radioTranslationRequestedMode = requested.radioTranslationMode;
    target.dataset.communicationMode = state.active ? "IMMERSIVE" : "NORMAL";

    var videoShell = target.querySelector(".video-call-layout");
    var callShell = target.querySelector(".call-communication-layout");
    var translationShell = target.querySelector(".translation-dock");
    var radioShell = target.querySelector(".radio-content");
    var radioTranslationShell = target.querySelector(".radio-translation-card");
    if (videoShell) {
      videoShell.dataset.videoMode = effective.mediaMode;
      videoShell.dataset.videoRequestedMode = requested.mediaMode;
      videoShell.dataset.translationMode = effective.translationMode;
      videoShell.dataset.desktopTranslationMode = effective.desktopTranslationMode;
      videoShell.dataset.translationRequestedMode = requested.translationMode;
    }
    if (callShell) {
      callShell.dataset.translationMode = effective.translationMode;
      callShell.dataset.desktopTranslationMode = effective.desktopTranslationMode;
      callShell.dataset.translationRequestedMode = requested.translationMode;
    }
    if (translationShell) {
      translationShell.dataset.translationMode = effective.translationMode;
      translationShell.dataset.desktopTranslationMode = effective.desktopTranslationMode;
      translationShell.dataset.translationRequestedMode = requested.translationMode;
      var translationLabel = translationShell.querySelector("[data-translation-mode-label]");
      if (translationLabel) translationLabel.textContent = state.viewport.mobile ? effective.translationMode : effective.desktopTranslationMode;
      translationShell.querySelectorAll('[data-workspace-action="translation-minus"]').forEach(function (button) { button.disabled = effective.translationMode === "COLLAPSED"; });
      translationShell.querySelectorAll('[data-workspace-action="translation-plus"]').forEach(function (button) { button.disabled = effective.translationMode === "FULL"; });
    }
    if (radioShell) {
      radioShell.dataset.radioMode = effective.radioMode;
      radioShell.dataset.radioRequestedMode = requested.radioMode;
      radioShell.dataset.radioTranslationMode = effective.radioTranslationMode;
      radioShell.dataset.radioTranslationRequestedMode = requested.radioTranslationMode;
    }
    if (radioTranslationShell) {
      radioTranslationShell.dataset.radioTranslationMode = effective.radioTranslationMode;
      radioTranslationShell.dataset.radioTranslationRequestedMode = requested.radioTranslationMode;
      var radioLabel = radioTranslationShell.querySelector("[data-radio-translation-mode-label]");
      if (radioLabel) radioLabel.textContent = effective.radioTranslationMode;
      radioTranslationShell.querySelectorAll('[data-workspace-action="radio-translation-minus"]').forEach(function (button) { button.disabled = requested.radioTranslationMode === "COLLAPSED"; });
      radioTranslationShell.querySelectorAll('[data-workspace-action="radio-translation-plus"]').forEach(function (button) { button.disabled = requested.radioTranslationMode === "FULL"; });
    }
    target.querySelectorAll("[data-video-mode-label]").forEach(function (node) { node.textContent = effective.mediaMode; });
    target.querySelectorAll("[data-radio-mode-label]").forEach(function (node) { node.textContent = effective.radioMode; });
    target.querySelectorAll('[data-workspace-action="video-minus"]').forEach(function (button) {
      button.disabled = effective.mediaMode === (state.viewport.mobile ? "COMPACT" : "STANDARD");
    });
    target.querySelectorAll('[data-workspace-action="video-plus"]').forEach(function (button) { button.disabled = effective.mediaMode === "MAXIMIZED"; });
    target.querySelectorAll('[data-workspace-action="radio-minus"]').forEach(function (button) { button.disabled = requested.radioMode === "COMPACT"; });
    target.querySelectorAll('[data-workspace-action="radio-plus"]').forEach(function (button) { button.disabled = requested.radioMode === "MAXIMIZED"; });
    document.body.classList.toggle("group-communication-immersive", state.active);
    document.body.dataset.groupCommunicationSurface = state.surface;
    document.body.dataset.groupCommunicationRuntimeKey = state.runtimeKey;
    return snapshot();
  }

  function handleClick(event) {
    var control = event.target.closest && event.target.closest("[data-workspace-action]");
    if (!control || control.disabled) return;
    var action = control.dataset.workspaceAction;
    if (action === "video-plus") stepVideo(1);
    else if (action === "video-minus") stepVideo(-1);
    else if (action === "video-maximize") setVideoMode("MAXIMIZED");
    else if (action === "video-restore") setVideoMode("STANDARD");
    else if (action === "translation-plus") stepTranslation(1, false);
    else if (action === "translation-minus") stepTranslation(-1, false);
    else if (action === "radio-plus") stepRadio(1);
    else if (action === "radio-minus") stepRadio(-1);
    else if (action === "radio-maximize") setRadioMode("MAXIMIZED");
    else if (action === "radio-restore") setRadioMode("STANDARD");
    else if (action === "radio-translation-plus") stepTranslation(1, true);
    else if (action === "radio-translation-minus") stepTranslation(-1, true);
    else return;
    event.preventDefault();
    event.stopPropagation();
  }

  document.addEventListener("click", handleClick, true);
  window.addEventListener("resize", function () { apply(); });
  window.addEventListener("orientationchange", function () { apply(); });
  window.addEventListener("group-v3:rendered", function () { apply(); });
  window.addEventListener("group-v3:viewport", function (event) {
    state.viewport.keyboardOpen = Boolean(event.detail && event.detail.keyboardOpen);
    state.viewport.visualHeight = Math.round(event.detail && event.detail.visualHeight || state.viewport.visualHeight || 0);
    apply();
  });

  window.GroupCommunicationWorkspace = Object.freeze({
    MOBILE_VIDEO_MODES: MOBILE_VIDEO_MODES.slice(),
    DESKTOP_VIDEO_MODES: DESKTOP_VIDEO_MODES.slice(),
    VIDEO_MODES: MOBILE_VIDEO_MODES.slice(),
    TRANSLATION_MODES: TRANSLATION_MODES.slice(),
    DESKTOP_TRANSLATION_MODES: DESKTOP_TRANSLATION_MODES.slice(),
    RADIO_MODES: RADIO_MODES.slice(),
    snapshot: snapshot,
    apply: apply,
    setRuntime: setRuntime,
    setVideoMode: setVideoMode,
    setTranslationMode: setTranslationMode,
    setRadioMode: setRadioMode,
    stepVideo: stepVideo,
    stepTranslation: stepTranslation,
    stepRadio: stepRadio
  });
}(window, document));
