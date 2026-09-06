(function installGroupV3DeviceManager(window) {
  "use strict";

  var activeStream = null;
  var meterContext = null;
  var meterSource = null;
  var meterAnalyser = null;
  var meterFrame = 0;
  var STORAGE_KEY = "group-v3-device-preferences-v1";
  var preferences = Object.create(null);

  try {
    var stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}");
    ["audioInput", "videoInput", "audioOutput"].forEach(function (kind) {
      if (typeof stored[kind] === "string") preferences[kind] = stored[kind];
    });
  } catch (_error) {}

  function persistPreferences() {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences)); } catch (_error) {}
  }

  function normalizeError(error) {
    var name = String(error && error.name || "");
    var message = String(error && error.message || "");
    var code = "device_error";
    if (name === "NotAllowedError" || name === "SecurityError") code = "permission_denied";
    else if (name === "NotFoundError" || name === "OverconstrainedError") code = "device_not_found";
    else if (name === "NotReadableError" || name === "AbortError") code = "device_busy";
    else if (name === "TypeError" || message.indexOf("getUserMedia") >= 0) code = "browser_unsupported";
    return { code: code, name: name, message: message };
  }

  function ensureMediaDevices() {
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
      var error = new Error("media_devices_unsupported");
      error.code = "browser_unsupported";
      throw error;
    }
  }

  async function enumerate() {
    ensureMediaDevices();
    if (typeof navigator.mediaDevices.enumerateDevices !== "function") {
      var unsupported = new Error("enumerate_devices_unsupported");
      unsupported.code = "browser_unsupported";
      throw unsupported;
    }
    var devices = await navigator.mediaDevices.enumerateDevices();
    var result = { audioInputs: [], videoInputs: [], audioOutputs: [] };
    devices.forEach(function (device) {
      var item = { deviceId: device.deviceId || "", groupId: device.groupId || "", label: device.label || "" };
      if (device.kind === "audioinput") result.audioInputs.push(item);
      if (device.kind === "videoinput") result.videoInputs.push(item);
      if (device.kind === "audiooutput") result.audioOutputs.push(item);
    });
    return result;
  }

  function remember(kind, deviceId) {
    if (["audioInput", "videoInput", "audioOutput"].indexOf(kind) < 0) return;
    if (deviceId) preferences[kind] = String(deviceId);
    else delete preferences[kind];
    persistPreferences();
  }

  function remembered(kind) {
    return preferences[kind] || "";
  }

  function constraints(options) {
    options = options || {};
    var audio = options.audioEnabled === false ? false : {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    };
    var video = options.videoEnabled === false ? false : { facingMode: "user" };
    if (audio && options.audioDeviceId) audio.deviceId = { exact: options.audioDeviceId };
    if (video && options.videoDeviceId) video.deviceId = { exact: options.videoDeviceId };
    return { audio: audio, video: video };
  }

  async function acquire(options) {
    ensureMediaDevices();
    options = options || {};
    var kind = options.mediaKind === "video" ? "video" : "audio";
    var request = Object.assign({}, options, {
      videoEnabled: kind === "video" && options.videoEnabled !== false,
      audioEnabled: options.audioEnabled !== false
    });
    if (!request.audioDeviceId) request.audioDeviceId = remembered("audioInput");
    if (!request.videoDeviceId) request.videoDeviceId = remembered("videoInput");
    if (activeStream) stop();
    try {
      activeStream = await navigator.mediaDevices.getUserMedia(constraints(request));
    } catch (error) {
      var normalized = normalizeError(error);
      error.code = normalized.code;
      error.deviceError = normalized;
      throw error;
    }
    var audioTrack = activeStream.getAudioTracks()[0];
    var videoTrack = activeStream.getVideoTracks()[0];
    if (audioTrack && audioTrack.getSettings().deviceId) remember("audioInput", audioTrack.getSettings().deviceId);
    if (videoTrack && videoTrack.getSettings().deviceId) remember("videoInput", videoTrack.getSettings().deviceId);
    return activeStream;
  }

  function stop() {
    window.cancelAnimationFrame(meterFrame);
    meterFrame = 0;
    if (meterSource) {
      try { meterSource.disconnect(); } catch (_error) {}
    }
    meterSource = null;
    meterAnalyser = null;
    if (meterContext && meterContext.close) meterContext.close().catch(function () {});
    meterContext = null;
    if (activeStream) activeStream.getTracks().forEach(function (track) { track.stop(); });
    activeStream = null;
  }

  function startMeter(stream, callback) {
    if (!stream || typeof callback !== "function" || typeof window.AudioContext !== "function") return function () {};
    var track = stream.getAudioTracks()[0];
    if (!track) return function () {};
    try {
      meterContext = new window.AudioContext();
      meterSource = meterContext.createMediaStreamSource(new MediaStream([track]));
      meterAnalyser = meterContext.createAnalyser();
      meterAnalyser.fftSize = 256;
      meterSource.connect(meterAnalyser);
      var data = new Uint8Array(meterAnalyser.fftSize);
      var tick = function () {
        if (!meterAnalyser) return;
        meterAnalyser.getByteTimeDomainData(data);
        var sum = 0;
        data.forEach(function (value) { var normalized = (value - 128) / 128; sum += normalized * normalized; });
        callback(Math.min(1, Math.sqrt(sum / data.length) * 3));
        meterFrame = window.requestAnimationFrame(tick);
      };
      tick();
    } catch (_error) {}
    return function () {
      window.cancelAnimationFrame(meterFrame);
      meterFrame = 0;
      if (meterSource) {
        try { meterSource.disconnect(); } catch (_error) {}
      }
      meterSource = null;
      meterAnalyser = null;
      if (meterContext && meterContext.close) meterContext.close().catch(function () {});
      meterContext = null;
    };
  }

  function outputSelectionSupported(element) {
    var prototype = window.HTMLMediaElement && window.HTMLMediaElement.prototype;
    return typeof (element && element.setSinkId || prototype && prototype.setSinkId) === "function";
  }

  async function setOutput(element, deviceId) {
    if (!element || !deviceId) return false;
    if (!outputSelectionSupported(element)) return false;
    try {
      await element.setSinkId(deviceId);
      remember("audioOutput", deviceId);
      return true;
    } catch (_error) {
      return false;
    }
  }

  async function applyOutput(element) {
    var deviceId = remembered("audioOutput");
    if (!deviceId) return { supported: outputSelectionSupported(element), applied: false, mode: "default" };
    if (!outputSelectionSupported(element)) return { supported: false, applied: false, mode: "os-managed" };
    var applied = await setOutput(element, deviceId);
    return { supported: true, applied: applied, mode: applied ? "selected" : "failed" };
  }

  window.GroupV3DeviceManager = Object.freeze({
    enumerate: enumerate,
    acquire: acquire,
    stop: stop,
    startMeter: startMeter,
    setOutput: setOutput,
    applyOutput: applyOutput,
    outputSelectionSupported: outputSelectionSupported,
    normalizeError: normalizeError,
    remembered: remembered,
    remember: remember,
    preferences: function () {
      return { audioInput: remembered("audioInput"), videoInput: remembered("videoInput"), audioOutput: remembered("audioOutput") };
    }
  });
})(window);
