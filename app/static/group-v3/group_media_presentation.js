(function (window, document) {
  "use strict";
  // DOM identity is independent from the rendering cadence and Room ownership.
  var remotes = new Map();
  var local = null;
  function root() { return document.getElementById("group-native-app"); }
  function tile(identity) {
    var host = root();
    return identity && host && host.querySelector('[data-video-identity="' + CSS.escape(String(identity)) + '"]');
  }
  function mark(entry) {
    var node = entry.element, target = tile(entry.identity);
    if (!node || !target || node.tagName !== "VIDEO") return;
    var track = entry.track && (entry.track.mediaStreamTrack || entry.track);
    target.classList.toggle("has-video", node.readyState >= 2 && node.videoWidth > 0 &&
      (!track || (track.readyState !== "ended" && track.enabled !== false && !track.muted)) &&
      !(entry.track && entry.track.isMuted));
    if (!target.dataset.videoFit) target.dataset.videoFit = "FIT";
  }
  function place(entry) {
    var host = root();
    var target = entry.kind === "video" ? tile(entry.identity) : host && host.querySelector("[data-audio-host]");
    if (!target) return; // Wait for the exact participant, never first-tile fallback.
    if (!entry.element) {
      entry.element = entry.track.attach();
      entry.element.className = "remote-media";
      entry.element.dataset.groupV3Media = "true";
      entry.element.autoplay = true;
      entry.element.playsInline = true;
      entry.element.addEventListener("loadeddata", function () { mark(entry); });
      entry.element.addEventListener("resize", function () { mark(entry); });
      entry.element.addEventListener("playing", function () { mark(entry); });
    }
    if (entry.element.parentNode !== target) target.appendChild(entry.element);
    if (entry.kind === "audio" && window.GroupV3DeviceManager && window.GroupV3DeviceManager.applyOutput) {
      window.GroupV3DeviceManager.applyOutput(entry.element).catch(function () {});
    }
    mark(entry);
    if (entry.element.paused && entry.element.play) {
      var result = entry.element.play();
      if (result && result.catch) result.catch(function () { entry.playbackBlocked = true; });
    }
  }
  function remote(track, identity) {
    if (!track || !identity || !track.attach) return;
    var entry = remotes.get(track);
    if (!entry) {
      entry = { track: track, identity: String(identity), kind: String(track.kind), element: null };
      remotes.set(track, entry);
    }
    place(entry);
  }
  function syncLocal(stream, identity) {
    if (!stream || !identity) return;
    var videoTrack = stream.getVideoTracks()[0];
    if (!videoTrack) return;
    if (!local || local.stream !== stream) {
      if (local) local.element.remove();
      var element = document.createElement("video");
      local = { stream: stream, identity: identity, kind: "video", track: videoTrack, element: element };
      element.className = "local-media";
      element.dataset.groupV3Media = "true";
      element.autoplay = true;
      element.playsInline = true;
      element.muted = true;
      element.srcObject = stream;
      var entry = local;
      element.addEventListener("loadeddata", function () { mark(entry); });
      element.addEventListener("playing", function () { mark(entry); });
    }
    local.identity = identity;
    place(local);
  }
  function unsubscribe(track) {
    var entry = remotes.get(track);
    if (track && track.detach) track.detach().forEach(function (node) { node.remove(); });
    if (entry) {
      var target = tile(entry.identity);
      if (target) target.classList.remove("has-video");
      remotes.delete(track);
    }
  }
  function clear() {
    Array.from(remotes.keys()).forEach(unsubscribe);
    if (local) { local.element.srcObject = null; local.element.remove(); }
    local = null;
  }
  function diagnostics() {
    return Array.from(remotes.values()).concat(local ? [local] : []).map(function (entry) {
      var el = entry.element, track = entry.track.mediaStreamTrack || entry.track;
      return { identity: entry.identity, sid: entry.track.sid || "", kind: entry.kind,
        subscribed: true, muted: Boolean(entry.track.isMuted || track.muted),
        trackState: track.readyState || "", pendingTile: !tile(entry.identity),
        attached: Boolean(el && el.isConnected), readyState: el && el.readyState,
        videoWidth: el && el.videoWidth, videoHeight: el && el.videoHeight,
        currentTime: el && el.currentTime, paused: el && el.paused,
        playbackBlocked: Boolean(entry.playbackBlocked) };
    });
  }
  window.GroupMediaPresentation = Object.freeze({
    remote: remote, local: syncLocal, unsubscribe: unsubscribe, clear: clear,
    sync: function () { remotes.forEach(place); if (local) place(local); },
    diagnostics: diagnostics
  });
}(window, document));
