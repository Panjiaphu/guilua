(function (window) {
  "use strict";
  var active = null;
  function begin(track) {
    if (active) throw new Error("group_radio_recording_busy");
    if (!track || track.readyState !== "live" || track.muted || !track.enabled || !window.MediaRecorder) {
      throw new Error("group_radio_recording_unavailable");
    }
    var mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find(function (type) {
      return window.MediaRecorder.isTypeSupported(type);
    });
    var recorder = new window.MediaRecorder(new MediaStream([track]), mime ? { mimeType: mime } : {});
    var entry = { recorder: recorder, chunks: [], started: Date.now(), discarded: false };
    entry.done = new Promise(function (resolve) {
      entry.resolve = resolve;
      recorder.addEventListener("dataavailable", function (event) {
        if (!entry.discarded && event.data && event.data.size) entry.chunks.push(event.data);
      });
      recorder.addEventListener("error", function () {
        entry.discarded = true; entry.chunks = []; resolve(null);
      });
      recorder.addEventListener("stop", function () {
        var type = recorder.mimeType || (entry.chunks[0] && entry.chunks[0].type) || mime;
        var blob = entry.discarded ? null : new Blob(entry.chunks, { type: type });
        entry.chunks = [];
        resolve(blob && blob.size ? { blob: blob, seconds: Math.max(.001, (Date.now() - entry.started) / 1000),
          extension: /mp4|m4a/.test(type) ? "m4a" : /ogg/.test(type) ? "ogg" : "webm" } : null);
      });
    });
    recorder.start(250);
    active = entry;
  }
  function stop(discard) {
    var entry = active;
    active = null;
    if (!entry) return Promise.resolve(null);
    if (discard) { entry.discarded = true; entry.chunks = []; }
    if (entry.recorder.state !== "inactive") entry.recorder.stop();
    // A broken recorder must never block floor release or Exit.
    var timer = window.setTimeout(function () { entry.discarded = true; entry.chunks = []; entry.resolve(null); }, 1500);
    return entry.done.finally(function () { window.clearTimeout(timer); });
  }
  window.GroupV3RadioRecording = Object.freeze({ begin: begin, stop: stop });
}(window));
