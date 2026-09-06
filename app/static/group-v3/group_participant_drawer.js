(function installGroupParticipantDrawer(window, document) {
  "use strict";

  function esc(value) {
    return String(value == null ? "" : value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  function render(container, participants, labels) {
    if (!container) return;
    var wasHidden = container.hidden;
    labels = labels || {};
    container.innerHTML = '<header><strong>' + esc(labels.title || "Participants") + '</strong><button type="button" data-action="close-participants" aria-label="' + esc(labels.close || "Close") + '">×</button></header>' +
      '<div class="group-participant-drawer__list">' + (participants || []).map(function (person) {
        var identity = person.livekit_identity || person.id || "";
        return '<article data-participant-identity="' + esc(identity) + '"><div><strong>' + esc(person.display_name || labels.member || "Member") + '</strong><small>' +
          esc(person.connection_status || person.status || "connected") + ' · ' + esc(person.mic_state || "mic") + ' · ' + esc(person.camera_state || "camera") +
          '</small></div><div class="group-participant-drawer__actions"><button type="button" data-video-focus="' + esc(identity) + '">' + window.GroupV3Icon("focus", 16) + esc(labels.focus || "Focus") +
          '</button><button type="button" data-video-hide="' + esc(identity) + '">' + window.GroupV3Icon("eye-off", 16) + esc(labels.hide || "Hide") + '</button><button type="button" data-video-restore="' + esc(identity) + '">' + window.GroupV3Icon("eye", 16) + esc(labels.restore || "Restore") + '</button></div></article>';
      }).join("") + '</div>';
    container.hidden = wasHidden;
  }

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest && event.target.closest('[data-action="toggle-participant-drawer"]');
    if (toggle) {
      var drawer = document.querySelector("[data-participant-drawer]");
      if (drawer) drawer.hidden = !drawer.hidden;
      event.preventDefault();
      return;
    }
    var close = event.target.closest && event.target.closest('[data-action="close-participants"]');
    if (close) {
      var openDrawer = document.querySelector("[data-participant-drawer]");
      if (openDrawer) openDrawer.hidden = true;
      event.preventDefault();
      return;
    }
    var button = event.target.closest && event.target.closest("[data-video-focus], [data-video-hide], [data-video-restore]");
    if (!button || !window.GroupV3VideoLayout) return;
    if (button.dataset.videoFocus) window.GroupV3VideoLayout.focus(button.dataset.videoFocus);
    if (button.dataset.videoHide) window.GroupV3VideoLayout.hide(button.dataset.videoHide);
    if (button.dataset.videoRestore) window.GroupV3VideoLayout.restore(button.dataset.videoRestore);
    event.preventDefault();
  });

  window.GroupV3ParticipantDrawer = Object.freeze({ render: render });
}(window, document));
