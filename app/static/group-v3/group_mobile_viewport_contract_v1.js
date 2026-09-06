(function groupMobileViewportContract(window, document) {
  "use strict";

  var root = document.getElementById("group-native-app");
  var body = document.body;
  if (!root || !body) return;

  var viewport = window.visualViewport;
  var layoutViewportHeight = 0;
  var viewportFrame = 0;
  var restoreFrame = 0;
  var scrollPinned = false;
  var lastSnapshot = {
    layoutHeight: 0,
    visualHeight: 0,
    offsetTop: 0,
    pageTop: 0,
    visibleBottom: 0,
    keyboardHeight: 0,
    keyboardOpen: false,
    standalone: false
  };
  var EDITABLE_SELECTOR = [
    "textarea",
    "[contenteditable='true']",
    "input:not([type])",
    "input[type='text']",
    "input[type='search']",
    "input[type='email']",
    "input[type='url']",
    "input[type='tel']",
    "input[type='password']",
    "input[type='number']"
  ].join(",");

  function number(value, fallback) {
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function isEditable(element) {
    return Boolean(element && element.matches && element.matches(EDITABLE_SELECTOR));
  }

  function hasEditableFocus() {
    return isEditable(document.activeElement);
  }

  function isStandalone() {
    var displayMode = window.matchMedia && window.matchMedia("(display-mode: standalone)");
    return Boolean((displayMode && displayMode.matches) || window.navigator.standalone === true);
  }

  function isNearScrollEnd(container) {
    if (!container) return true;
    return container.scrollHeight - container.scrollTop - container.clientHeight <= 96;
  }

  function rememberScrollPin(element) {
    if (!isEditable(element)) return;
    scrollPinned = isNearScrollEnd(root.querySelector(".thread-scroll"));
  }

  function applyVisualViewport() {
    viewportFrame = 0;
    var visualHeight = Math.max(1, Math.round(number(viewport && viewport.height, window.innerHeight || document.documentElement.clientHeight || 1)));
    var offsetTop = Math.max(0, Math.round(number(viewport && viewport.offsetTop, 0)));
    var pageTop = Math.max(0, Math.round(number(viewport && viewport.pageTop, 0)));
    var visibleBottom = offsetTop + visualHeight;
    var currentLayoutHeight = Math.max(1, Math.round(window.innerHeight || document.documentElement.clientHeight || visualHeight));
    var activeEditor = hasEditableFocus();
    var wasKeyboardOpen = body.classList.contains("group-keyboard-open");

    if (!layoutViewportHeight || (!activeEditor && !wasKeyboardOpen)) {
      layoutViewportHeight = currentLayoutHeight;
    } else if (currentLayoutHeight > layoutViewportHeight) {
      layoutViewportHeight = currentLayoutHeight;
    }

    var layoutHeight = Math.max(currentLayoutHeight, layoutViewportHeight);
    var keyboardHeight = Math.max(0, layoutHeight - visualHeight - offsetTop);
    var keyboardThreshold = Math.max(96, Math.round(layoutHeight * 0.12));
    var keyboardOpen = keyboardHeight > keyboardThreshold && Boolean(activeEditor || wasKeyboardOpen);
    var standalone = isStandalone();

    body.style.setProperty("--group-visual-viewport-height", visualHeight + "px");
    body.style.setProperty("--group-visual-viewport-offset-top", offsetTop + "px");
    body.style.setProperty("--group-visual-viewport-bottom", visibleBottom + "px");
    body.style.setProperty("--group-visual-viewport-page-top", pageTop + "px");
    body.style.setProperty("--group-keyboard-height", (keyboardOpen ? keyboardHeight : 0) + "px");
    body.classList.toggle("group-pwa-standalone", standalone);
    body.classList.toggle("group-keyboard-open", keyboardOpen);
    root.dataset.keyboardState = keyboardOpen ? "OPEN" : "CLOSED";
    root.dataset.viewportState = standalone ? "STANDALONE" : "BROWSER";

    lastSnapshot = {
      layoutHeight: layoutHeight,
      visualHeight: visualHeight,
      offsetTop: offsetTop,
      pageTop: pageTop,
      visibleBottom: visibleBottom,
      keyboardHeight: keyboardOpen ? keyboardHeight : 0,
      keyboardOpen: keyboardOpen,
      standalone: standalone
    };

    window.dispatchEvent(new CustomEvent("group-v3:viewport", { detail: lastSnapshot }));

    if (keyboardOpen && activeEditor && scrollPinned) {
      window.requestAnimationFrame(function () {
        var scroll = root.querySelector(".thread-scroll");
        if (scroll) scroll.scrollTop = scroll.scrollHeight;
      });
    }
  }

  function syncVisualViewport() {
    if (viewportFrame) window.cancelAnimationFrame(viewportFrame);
    viewportFrame = 0;
    applyVisualViewport();
  }

  function restoreClosedKeyboardLayout() {
    if (!isStandalone() || hasEditableFocus()) return false;
    body.classList.remove("group-keyboard-open");
    body.style.setProperty("--group-keyboard-height", "0px");
    syncVisualViewport();
    return true;
  }

  function scheduleRestore() {
    if (!isStandalone()) return;
    if (restoreFrame) window.cancelAnimationFrame(restoreFrame);
    restoreFrame = 0;
    restoreClosedKeyboardLayout();
  }

  function handleFocusIn(event) {
    rememberScrollPin(event.target);
    syncVisualViewport();
  }

  function handleFocusOut() {
    syncVisualViewport();
    scheduleRestore();
  }

  function handleOrientationChange() {
    layoutViewportHeight = 0;
    scheduleRestore();
    syncVisualViewport();
  }

  function handleVisibilityChange() {
    if (!document.hidden) {
      scheduleRestore();
      syncVisualViewport();
    }
  }

  document.addEventListener("focusin", handleFocusIn);
  document.addEventListener("focusout", handleFocusOut);
  document.addEventListener("visibilitychange", handleVisibilityChange);
  window.addEventListener("resize", syncVisualViewport);
  window.addEventListener("orientationchange", handleOrientationChange, { passive: true });
  window.addEventListener("pageshow", scheduleRestore, { passive: true });
  viewport && viewport.addEventListener("resize", syncVisualViewport);
  viewport && viewport.addEventListener("scroll", syncVisualViewport);

  var standaloneQuery = window.matchMedia && window.matchMedia("(display-mode: standalone)");
  if (standaloneQuery && standaloneQuery.addEventListener) standaloneQuery.addEventListener("change", syncVisualViewport);

  syncVisualViewport();

  window.GroupMobileViewportContractV1 = Object.freeze({
    sync: syncVisualViewport,
    restoreClosedKeyboardLayout: restoreClosedKeyboardLayout,
    scheduleRestore: scheduleRestore,
    isStandalone: isStandalone,
    snapshot: function () { return Object.assign({}, lastSnapshot); }
  });
}(window, document));
