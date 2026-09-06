(function installGroupVideoLayout(window, document) {
  "use strict";

  var activeSpeakerIdentity = "";
  var pendingSpeakerIdentity = "";
  var speakerTimer = 0;
  var focusedIdentity = "";
  var hiddenIdentities = new Set();
  var runtimeKey = "";
  var mode = "AUTO";
  var customOrder = [];
  var fits = new Map();
  function emit() { window.dispatchEvent(new CustomEvent("group-video-layout:change", { detail: snapshot() })); }
  function setMode(value) {
    if (["AUTO", "GRID", "SPEAKER", "CUSTOM"].indexOf(value) < 0) return;
    mode = value; focusedIdentity = ""; emit();
  }
  function reset() {
    mode = "AUTO"; customOrder = []; fits.clear(); focusedIdentity = "";
    hiddenIdentities.clear(); emit();
  }
  function reorder(from, to) {
    if (mode !== "CUSTOM" || from === to) return;
    var ids = Array.from(document.querySelectorAll(".video-tile[data-video-identity]")).map(function (tile) { return tile.dataset.videoIdentity; });
    var order = customOrder.filter(function (id) { return ids.indexOf(id) >= 0; });
    ids.forEach(function (id) { if (order.indexOf(id) < 0) order.push(id); });
    var source = order.indexOf(from), target = order.indexOf(to);
    if (source < 0 || target < 0) return;
    order.splice(source, 1); order.splice(target, 0, from); customOrder = order; emit();
  }
  function toolbar(t) {
    return '<label class="video-layout-select"><span class="sr-only">' + t("videoLayout") +
      '</span><select data-video-layout aria-label="' + t("videoLayout") + '">' +
      ["AUTO", "GRID", "SPEAKER", "CUSTOM"].map(function (value) {
        return '<option value="' + value + '" ' + (mode === value ? "selected" : "") + '>' +
          t("videoLayout" + value.charAt(0) + value.slice(1).toLowerCase()) + '</option>';
      }).join("") + '</select></label><button type="button" class="icon-button" data-video-reset aria-label="' +
      t("videoLayoutReset") + '" title="' + t("videoLayoutReset") + '">' + window.GroupV3Icon("refresh-cw", 18) + '</button>';
  }

  function setActiveSpeaker(identity) {
    pendingSpeakerIdentity = String(identity || "");
    window.clearTimeout(speakerTimer);
    speakerTimer = window.setTimeout(function () {
      speakerTimer = 0;
      activeSpeakerIdentity = pendingSpeakerIdentity;
      window.dispatchEvent(new CustomEvent("group-video-layout:change", { detail: snapshot() }));
    }, 180);
    return snapshot();
  }

  function focus(identity) {
    focusedIdentity = focusedIdentity === String(identity || "") ? "" : String(identity || "");
    window.dispatchEvent(new CustomEvent("group-video-layout:change", { detail: snapshot() }));
    return snapshot();
  }

  function clearFocus() {
    focusedIdentity = "";
    window.dispatchEvent(new CustomEvent("group-video-layout:change", { detail: snapshot() }));
    return snapshot();
  }

  function hide(identity) {
    var value = String(identity || "");
    if (value) {
      hiddenIdentities.add(value);
      if (focusedIdentity === value) focusedIdentity = "";
    }
    window.dispatchEvent(new CustomEvent("group-video-layout:change", { detail: snapshot() }));
    return snapshot();
  }

  function restore(identity) {
    if (identity) hiddenIdentities.delete(String(identity));
    else hiddenIdentities.clear();
    window.dispatchEvent(new CustomEvent("group-video-layout:change", { detail: snapshot() }));
    return snapshot();
  }

  function presentationIdentity(participants) {
    var list = (participants || []).filter(function (item) { return !hiddenIdentities.has(String(item.livekit_identity || item.id || "")); });
    var focused = focusedIdentity && list.some(function (item) { return String(item.livekit_identity || item.id || "") === focusedIdentity; }) ? focusedIdentity : "";
    var active = activeSpeakerIdentity && list.some(function (item) { return String(item.livekit_identity || item.id || "") === activeSpeakerIdentity; }) ? activeSpeakerIdentity : "";
    return focused || active || (list[0] && String(list[0].livekit_identity || list[0].id || "")) || "";
  }

  function layoutClass(count) {
    var value = Math.max(0, Number(count) || 0);
    if (value <= 1) return "count-1";
    if (value === 2) return "count-2";
    if (value <= 4) return "count-" + value;
    if (value <= 6) return "count-" + value;
    if (value <= 10) return "count-" + value;
    return "count-10-plus";
  }

  function snapshot() {
    return {
      activeSpeakerIdentity: activeSpeakerIdentity,
      focusedIdentity: focusedIdentity,
      hiddenIdentities: Array.from(hiddenIdentities)
      ,mode: mode, customOrder: customOrder.slice()
    };
  }

  function applyDom() {
    var native = document.querySelector(".native-app");
    var key = native && native.dataset.runtimeKey || "";
    if (key !== runtimeKey) {
      runtimeKey = key;
      activeSpeakerIdentity = pendingSpeakerIdentity = focusedIdentity = "";
      hiddenIdentities.clear();
      mode = "AUTO"; customOrder = []; fits.clear();
      window.clearTimeout(speakerTimer);
    }
    var current = snapshot();
    var visible = Array.from(document.querySelectorAll(".video-tile[data-video-identity]")).filter(function (tile) {
      return current.hiddenIdentities.indexOf(tile.dataset.videoIdentity) < 0;
    });
    var preferred = current.focusedIdentity || current.activeSpeakerIdentity;
    var featured = visible.find(function (tile) { return tile.dataset.videoIdentity === preferred; }) || visible[0];
    document.querySelectorAll(".video-grid").forEach(function (grid) {
      Array.from(grid.classList).filter(function (name) { return /^count-/.test(name); }).forEach(function (name) { grid.classList.remove(name); });
      grid.classList.add(layoutClass(visible.length));
      grid.classList.toggle("has-explicit-focus", Boolean(current.focusedIdentity && featured));
      grid.dataset.layout = mode;
      var filmstrip = !current.focusedIdentity && (mode === "SPEAKER" || mode === "AUTO" && visible.length >= 7) && visible.length > 1;
      grid.classList.toggle("has-filmstrip", filmstrip);
      var strip = grid.querySelector(".video-filmstrip");
      if (filmstrip && !strip) { strip = document.createElement("div"); strip.className = "video-filmstrip"; grid.appendChild(strip); }
      grid.querySelectorAll(".video-tile").forEach(function (tile) {
        var parent = filmstrip && tile !== featured ? strip : grid;
        if (tile.parentElement !== parent) parent.appendChild(tile);
        tile.style.order = String(mode === "CUSTOM" && customOrder.indexOf(tile.dataset.videoIdentity) >= 0 ? customOrder.indexOf(tile.dataset.videoIdentity) : 0);
      });
      if (!filmstrip && strip) strip.remove();
      var select = document.querySelector("[data-video-layout]");
      if (select && select.value !== mode) select.value = mode;
    });
    document.querySelectorAll(".video-tile[data-video-identity]").forEach(function (tile) {
      var identity = String(tile.dataset.videoIdentity || "");
      var hidden = current.hiddenIdentities.indexOf(identity) >= 0;
      tile.classList.toggle("is-presentation-hidden", hidden);
      tile.classList.toggle("is-speaking", Boolean(current.activeSpeakerIdentity && identity === current.activeSpeakerIdentity));
      tile.classList.toggle("is-featured", tile === featured);
      tile.dataset.videoFit = fits.get(identity) || "FIT";
    });
  }

  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-video-layout]")) setMode(event.target.value);
  });
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-video-reset]")) { reset(); return; }
    var fit = event.target.closest("[data-video-fit-toggle]");
    if (fit) {
      var id = fit.closest("[data-video-identity]").dataset.videoIdentity;
      fits.set(id, fits.get(id) === "FILL" ? "FIT" : "FILL"); emit(); return;
    }
    var tile = event.target.closest(".video-tile");
    if (tile && !event.target.closest("button, select") && event.detail <= 1) focus(tile.dataset.videoIdentity);
  });
  document.addEventListener("dblclick", function (event) {
    var tile = event.target.closest(".video-tile");
    if (tile && !event.target.closest("button")) { focusedIdentity = tile.dataset.videoIdentity; emit(); }
  });
  var drag = null;
  document.addEventListener("pointerdown", function (event) {
    var handle = event.target.closest("[data-video-drag]");
    if (!handle || mode !== "CUSTOM") return;
    var tile = handle.closest("[data-video-identity]");
    drag = { id: tile.dataset.videoIdentity, pointer: event.pointerId, handle: handle,
      ready: event.pointerType === "mouse", x: event.clientX, y: event.clientY };
    handle.setPointerCapture(event.pointerId);
    drag.timer = window.setTimeout(function () { if (drag) { drag.ready = true; drag.handle.classList.add("is-dragging"); } }, 350);
  });
  document.addEventListener("pointermove", function (event) {
    if (!drag || event.pointerId !== drag.pointer) return;
    if (!drag.ready && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > 12) {
      window.clearTimeout(drag.timer); drag = null; return;
    }
    if (drag.ready) event.preventDefault();
  }, { passive: false });
  function finishDrag(event, cancelled) {
    if (!drag) return;
    var current = drag; drag = null;
    window.clearTimeout(current.timer); current.handle.classList.remove("is-dragging");
    var hit = document.elementFromPoint(event.clientX, event.clientY);
    var tile = hit && hit.closest(".video-tile");
    if (!cancelled && current.ready && tile) reorder(current.id, tile.dataset.videoIdentity);
  }
  document.addEventListener("pointerup", function (event) { finishDrag(event, false); });
  document.addEventListener("pointercancel", function (event) { finishDrag(event, true); });
  document.addEventListener("keydown", function (event) {
    var handle = event.target.closest("[data-video-drag]");
    if (!handle || mode !== "CUSTOM" || !/^Arrow/.test(event.key)) return;
    event.preventDefault();
    var tiles = Array.from(document.querySelectorAll(".video-tile")).sort(function (a, b) { return Number(a.style.order) - Number(b.style.order); });
    var tile = handle.closest(".video-tile"), index = tiles.indexOf(tile);
    var next = tiles[index + (event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1)];
    if (next) reorder(tile.dataset.videoIdentity, next.dataset.videoIdentity);
  });

  window.GroupV3VideoLayout = Object.freeze({
    setActiveSpeaker: setActiveSpeaker,
    focus: focus,
    clearFocus: clearFocus,
    hide: hide,
    restore: restore,
    presentationIdentity: presentationIdentity,
    layoutClass: layoutClass,
    snapshot: snapshot
    ,setMode: setMode, reset: reset, reorder: reorder, toolbar: toolbar
  });
  window.addEventListener("group-video-layout:change", applyDom);
  window.addEventListener("group-v3:rendered", applyDom);
  window.addEventListener("group-workspace:change", applyDom);
}(window, document));
