(function installGroupRadioUi(window) {
  "use strict";

  function esc(value) {
    return String(value == null ? "" : value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function icon(name, size) {
    if (typeof window.GroupV3Icon === "function") return window.GroupV3Icon(name, size || 19);
    var path = name === "plus" ? '<path d="M12 5v14M5 12h14"/>' : '<path d="M5 12h14"/>';
    return '<svg class="ui-icon ui-icon-fallback" width="' + (size || 19) + '" height="' + (size || 19) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">' + path + '</svg>';
  }

  function panelControls(labels) {
    labels = labels || {};
    return '<div class="group-radio-translation-controls panel-resize-controls" role="group" aria-label="' + esc(labels.translation || "Radio translation") + '">' +
      '<button type="button" class="icon-button" data-workspace-action="radio-translation-minus" aria-label="' + esc(labels.minus || "Collapse translation") + '" title="' + esc(labels.minus || "Collapse translation") + '">' + icon("chevron-down", 19) + '</button>' +
      '<span data-radio-translation-mode-label>COLLAPSED</span>' +
      '<button type="button" class="icon-button" data-workspace-action="radio-translation-plus" aria-label="' + esc(labels.plus || "Expand translation") + '" title="' + esc(labels.plus || "Expand translation") + '">' + icon("chevron-up", 19) + '</button>' +
      '</div>';
  }

  function timeline(items, labels, t) {
    return (items || []).map(function (item) {
      var segment = item.segment;
      var name = item.speaker_display_name || "";
      var time = item.started_at ? new Date(item.started_at).toLocaleString() : "";
      return '<article class="radio-message" data-radio-burst="' + esc(item.id) + '"><header><strong>' +
        esc(name) + '</strong><time datetime="' + esc(item.started_at || "") + '">' + esc(time) +
        '</time><span>' + esc(t("radioState_" + item.state)) + '</span></header>' +
        (segment ? window.GroupV3TranslationView.historyItem(Object.assign({}, segment, { show_original_enabled: true }), labels) :
          '<p role="status">' + esc(t(item.state === "failed" || item.state === "device_lost" ? "radioTextFailed" :
            item.state === "talking" ? "talkingNow" : "radioTextProcessing")) + '</p>') + '</article>';
    }).join("");
  }

  function roomPicker(spaces, currentId, options, t) {
    var rows = (spaces || []).map(function (space) {
      return '<button type="button" class="radio-room-picker-row ' + (space.id === currentId ? "is-active" : "") +
        '" data-action="select-space" data-id="' + esc(space.id) + '">' +
        '<span>' + esc(space.title) + '</span>' + (space.id === currentId ? '<b>•</b>' : '') + '</button>';
    }).join("");
    return '<aside class="radio-room-picker" ' + (options.roomsOpen ? "" : "hidden") + '><header><h2>' +
      esc(t("rooms")) + '</h2><button type="button" class="icon-button" data-action="radio-rooms" aria-label="' +
      esc(t("close")) + '">' + icon("log-out", 18) + '</button></header>' + (rows || '<p>' + esc(t("noSpaces")) + '</p>') + '</aside>';
  }

  function room(options) {
    var t = options.t, current = options.state;
    function button(action, label, name, disabled, extra) {
      return '<button type="button" class="action-button ' + (extra || "") + '" data-action="' + action +
        '" aria-label="' + esc(t(label)) + '" ' + (disabled ? "disabled " : "") + '>' + icon(name) + '<span>' + esc(t(label)) + '</span></button>';
    }
    var talking = current === "TALKING";
    var disconnected = current === "DISCONNECTED";
    var primary = button(talking ? "stop-radio" : disconnected ? "join-radio" : "start-radio",
      talking ? "stopBurst" : disconnected ? "joinRadioRoom" : "startTalking", talking ? "save" : "mic",
      ["READY", "TALKING", "DISCONNECTED"].indexOf(current) < 0, "action-primary radio-ptt");
    var members = options.participants || [];
    var speaker = talking ? t("talkingNow") : options.floor && options.floor.display_name || t("floorAvailable");
    var recovery = current === "DEVICE_LOST" ? '<aside class="radio-recovery" role="alert"><span>' +
      esc(t("deviceLostTitle")) + '</span><small>' + esc(t("devicePrivacy")) + '</small>' +
      button("reconnect-radio", "reconnectDevice", "headphones") + '</aside>' : "";
    return '<section class="radio-content radio-room surface-content state-' + current.toLowerCase() + '">' +
      '<header class="radio-room-header">' + button("leave-radio", "backToGroup", "log-out") +
      '<h1>' + esc(t("groupRadio")) + ' · ' + esc(options.title) + '</h1>' +
      button("radio-rooms", "rooms", "panel-right", false, "radio-room-picker-toggle") +
      button("radio-members", "participants", "users") + '</header>' +
      '<div class="radio-floor" role="status"><strong>' + esc(speaker) + '</strong><span data-radio-elapsed></span><small>' +
      esc(t("radioState_" + current.toLowerCase())) + '</small></div>' + recovery +
      '<div class="radio-timeline" data-translation-archive aria-label="' + esc(t("translationHistory")) + '">' +
      (options.error ? '<p role="alert">' + esc(options.error) + '</p>' : "") +
      (timeline(options.history, options.labels, t) || '<p class="radio-empty">' + esc(t("radioRoomEmpty")) + '</p>') +
      button("history-more", "historyOlder", "history") + '</div>' +
      '<footer class="radio-room-dock">' + primary + button("leave-radio", "leaveRadio", "log-out") +
      '</footer><aside class="radio-room-members" ' + (options.membersOpen ? "" : "hidden") + '><header><h2>' +
      esc(t("participants")) + '</h2>' + button("radio-members", "close", "users") + '</header>' +
      members.map(function (person) { return '<div><strong>' + esc(person.display_name) + '</strong><small>' +
        esc(t("radioMember_" + person.status)) + '</small></div>'; }).join("") +
      '</aside>' + roomPicker(options.spaces, options.spaceId, options, t) + '<div class="audio-host" data-audio-host></div></section>';
  }

  window.GroupV3RadioUi = Object.freeze({ panelControls: panelControls, room: room, timeline: timeline });
}(window));
