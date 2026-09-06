const CACHE_NAME = "timeblock-pwa-v28-group-r1-history-on-demand";
// Frozen Direct 1:1 source-contract marker; the active cache is versioned separately:
// const CACHE_NAME = "timeblock-pwa-v21-group-communication";
const CALL_V1_RUNTIME_VERSION = "call-v1-viewport-contract-20260903";
const CALL_VIBRATION_PATTERN = [
  320, 305, 120, 505, 120, 505, 120, 505,
  320, 305, 120, 505, 120, 505, 120, 505,
  320, 305, 120, 505, 120, 505, 120, 505,
  320, 305, 120, 505, 120, 505, 120, 505,
];
const MISSED_CALL_VIBRATION_PATTERN = [180, 120, 220];
const CALL_RUNTIME_ASSETS = new Set([
  "/static/css/call_workspace.css",
  "/static/js/assistant.js",
  "/static/js/messaging.js",
  "/static/js/messaging_core_v2.js",
  "/static/js/incoming_call_ringtone.js",
  "/static/js/timeblock_call_runtime.js",
  "/static/js/call_audio_ownership.js",
  "/static/js/call_audio_ownership_install.js",
  "/static/css/call_v3.css",
  "/static/js/call-v1/session.js",
  "/static/js/call-v1/media.js",
  "/static/js/call-v1/peer.js",
  "/static/js/call-v1/signaling.js",
  "/static/js/call-v1/ring-audio.js",
  "/static/js/call-v1/runtime.js",
  "/static/js/call-v1/translation_plugin.js",
  "/static/js/call-v1/bootstrap.js",
  "/static/css/call_translation_plugin.css",
  "/static/css/group_launcher_v3.css",
  "/static/js/group_launcher_v3.js",
]);
const CORE_ASSETS = [
  "/static/css/main.css",
  "/static/css/responsive.css",
  "/static/js/pwa-install.js",
  "/static/img/timeblock-icon-192.png",
  "/static/img/timeblock-icon-512.png",
  "/static/img/timeblock-badge-96.png",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS)).catch(() => undefined),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => {
      if (url.pathname === "/delivery/driver" || url.pathname.startsWith("/delivery/driver/")) {
        const requestedLocale = url.searchParams.get("lang");
        const locale = ["zh-TW", "vi", "en"].includes(requestedLocale) ? requestedLocale : "zh-TW";
        const offlineMessage = {
          "zh-TW": "Timeblock Delivery 目前離線。請重新連線後再試。",
          vi: "Timeblock Delivery hiện đang ngoại tuyến. Hãy kết nối lại rồi thử lại.",
          en: "Timeblock Delivery is temporarily offline. Reconnect and try again.",
        }[locale];
        return new Response(offlineMessage, {
          status: 503,
          headers: {
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Language": locale,
            "Cache-Control": "no-store",
          },
        });
      }
      return new Response(
        "Timeblock is temporarily offline. Reconnect and try again.",
        { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } },
      );
    }));
    return;
  }
  const isStaticAsset = url.pathname.startsWith("/static/") && /\.(?:css|js|png|svg|webmanifest)$/.test(url.pathname);
  if (!isStaticAsset) return;

  if (CALL_RUNTIME_ASSETS.has(url.pathname)) {
    event.respondWith(fetch(request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
      }
      return response;
    }).catch(() => caches.match(request)));
    return;
  }

  event.respondWith(caches.match(request).then((cached) => {
    const network = fetch(request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
      }
      return response;
    });
    return cached || network;
  }));
});

self.addEventListener("push", (event) => {
  let payload = {};
  try { payload = event.data?.json() || {}; }
  catch (_error) { payload = { body: event.data?.text() || "" }; }

  const type = String(payload.type || "system");
  const incomingCall = type === "incoming_call" || type.startsWith("call.incoming.");
  const missedCall = type.startsWith("call.missed.");
  const callNotification = incomingCall || missedCall;
  const callId = payload.callId || payload.call_id || null;
  const defaultCallUrl = callId
    ? `/assistant?mode=messages&communication=calls&call_id=${encodeURIComponent(callId)}${incomingCall ? "&answer=1" : ""}`
    : "/assistant?mode=alerts";
  const requestedUrl = String(payload.url || defaultCallUrl);
  const safeUrl = requestedUrl.startsWith("/") && !requestedUrl.startsWith("//")
    ? requestedUrl
    : defaultCallUrl;
  const title = String(payload.title || "Timeblock").slice(0, 120);
  const options = {
    body: String(payload.body || "").slice(0, 180),
    icon: payload.icon || "/static/img/timeblock-icon-192.png",
    badge: payload.badge || "/static/img/timeblock-badge-96.png",
    tag: String(payload.tag || "timeblock-notification").slice(0, 120),
    renotify: callNotification || type === "chat.message",
    requireInteraction: incomingCall,
    timestamp: Date.parse(payload.timestamp || "") || Date.now(),
    vibrate: incomingCall
      ? CALL_VIBRATION_PATTERN
      : (missedCall ? MISSED_CALL_VIBRATION_PATTERN : undefined),
    data: {
      url: safeUrl,
      type,
      conversationId: payload.conversationId || null,
      messageId: payload.messageId || null,
      senderId: payload.senderId || "",
      callId,
    },
  };
  event.waitUntil((async () => {
    if (incomingCall) {
      const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const foreground = clients.some((client) => {
        if (client.visibilityState !== "visible") return false;
        try { return new URL(client.url).pathname === "/assistant"; }
        catch (_error) { return false; }
      });
      if (foreground) {
        options.silent = true;
        options.vibrate = undefined;
      }
    }
    return self.registration.showNotification(title, options);
  })());
});

self.addEventListener("message", (event) => {
  if (event.data?.type !== "call-terminal") return;
  const callId = String(event.data?.callId || "");
  if (!callId) return;
  event.waitUntil(self.registration.getNotifications().then((notifications) => {
    notifications.forEach((notification) => {
      const notificationCallId = String(notification.data?.callId || "");
      const tag = String(notification.tag || "");
      if (notificationCallId === callId || tag.includes(callId)) notification.close();
    });
  }).catch(() => undefined));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil((async () => {
    const callId = event.notification?.data?.callId;
    const fallbackUrl = event.notification?.data?.url || "/assistant?mode=alerts";
    let requestedUrl = fallbackUrl;
    if (callId) {
      try {
        const response = await fetch(`/api/messaging/calls/${encodeURIComponent(callId)}`, {
          credentials: "include",
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        const payload = await response.json().catch(() => ({}));
        if (payload.call?.id) {
          const status = String(payload.call.status || "").toLowerCase();
          requestedUrl = ["ended", "rejected", "cancelled", "missed"].includes(status)
            ? `/assistant?mode=messages&call_id=${encodeURIComponent(payload.call.id)}`
            : `/assistant?mode=messages&call_id=${encodeURIComponent(payload.call.id)}`;
        }
      } catch (_error) {
        requestedUrl = `/assistant?mode=messages&call_id=${encodeURIComponent(callId)}`;
      }
    }
    const target = new URL(requestedUrl, self.location.origin);
    if (target.origin !== self.location.origin) target.href = new URL("/assistant?mode=alerts", self.location.origin).href;
    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of clients) {
      if (!("focus" in client)) continue;
      if ("navigate" in client) await client.navigate(target.href);
      return client.focus();
    }
    return self.clients.openWindow ? self.clients.openWindow(target.href) : undefined;
  })());
});

self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil((async () => {
    const subscription = event.newSubscription || await self.registration.pushManager.subscribe(
      event.oldSubscription?.options || { userVisibleOnly: true },
    );
    await fetch("/api/assistant/notifications/push/subscriptions", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subscription: subscription.toJSON(),
        platform: "web",
        device_name: "Timeblock PWA",
        content_encoding: "aes128gcm",
      }),
    });
  })().catch(() => undefined));
});
