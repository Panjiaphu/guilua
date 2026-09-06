(function installGroupTranslationView(window) {
  "use strict";

  function esc(value) {
    return String(value == null ? "" : value).replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  function languageOptions(selected, labels, detect) {
    return (detect ? ["auto", "vi", "en", "zh-TW"] : ["vi", "en", "zh-TW"]).map(function (language) {
      return '<option value="' + language + '" ' + (language === selected ? "selected" : "") + ">" +
        esc((labels && labels[language]) || language) + "</option>";
    }).join("");
  }

  function playButton(text, language, labels) {
    if (!text) return "";
    return '<button type="button" class="group-translation-v2__play" data-v2-play="' + esc(text) +
      '" data-v2-language="' + esc(language || "") + '" aria-pressed="false" aria-label="' +
      esc(labels.play || "Play translation") + '">' + esc(labels.play || "Play") + "</button>";
  }

  function retryButton(item, language, labels) {
    if (labels.readOnly) return "";
    return '<button type="button" class="group-translation-v2__retry" data-v2-retry="' +
      esc(item.id) + '" data-v2-target-language="' + esc(language) + '">' +
      esc(labels.retry || "Retry") + "</button>";
  }

  function panel(options) {
    options = options || {};
    var labels = options.labels || {};
    return '<section class="group-translation-v2" aria-labelledby="group-translation-v2-title" data-v2-panel>' +
      '<div class="group-translation-v2__header"><div><span class="group-translation-v2__eyebrow">' +
      esc(options.title || "Group Translation") + '</span><h2 id="group-translation-v2-title">' +
      esc(options.subtitle || "Text first · voice on demand") + '</h2></div><span data-v2-status class="group-translation-v2__status" role="status" aria-live="polite">' +
      esc(options.readyLabel || "Ready") + '</span></div><div class="group-translation-v2__languages"><label><span>' +
      esc(options.sourceLabel || "Spoken language") + '</span><select data-v2-source aria-label="' +
      esc(options.sourceLabel || "Spoken language") + '">' + languageOptions(options.source || "vi", labels, true) +
      '</select></label><label><span>' + esc(options.targetLabel || "Recipient language") +
      '</span><select data-v2-target aria-label="' + esc(options.targetLabel || "Recipient language") + '">' +
      languageOptions(options.target || "en", labels) + '</select></label></div><div class="group-translation-v2__composer">' +
      '<textarea data-v2-text data-group-text-entry rows="2" maxlength="12000" placeholder="' + esc(options.placeholder || "Type a message to translate") +
      '" aria-label="' + esc(options.placeholder || "Type a message to translate") + '"></textarea>' +
      '<div class="group-translation-v2__actions"><button type="button" class="action-button action-primary" data-v2-action="send">' +
      esc(options.sendLabel || "Send") + '</button><button type="button" class="action-button action-secondary" data-v2-action="record" aria-pressed="false">' +
      esc(options.recordLabel || "Voice") + '</button></div></div><label class="group-translation-v2__auto-read"><input type="checkbox" data-v2-auto-read ' +
      (options.autoRead ? "checked" : "") + '> ' + esc(options.autoReadLabel || "Auto Read on recipient device") +
      '</label><div data-v2-availability class="group-translation-v2__availability" hidden></div><div data-v2-error class="group-translation-v2__error" role="alert" hidden></div>' +
      '<div data-v2-warning role="status" hidden><span></span><button type="button" data-v2-history-retry>' + esc(labels.retry || "Retry") + '</button></div>' +
      '<div class="group-translation-v2__history" data-v2-history aria-live="polite"><p class="group-translation-v2__empty">' +
      esc(options.emptyLabel || "No FINAL translations yet.") + '</p></div></section>';
  }

  function authorVariant(item, variant, labels) {
    var inconsistentFinal = variant.state === "FINAL" && variant.translated_text == null;
    var failed = variant.state === "FAILED" || inconsistentFinal;
    var state = failed ? "FAILED" : variant.state;
    var text = failed ? (labels.failed || "Translation failed") : variant.translated_text == null ? (labels.pending || "Processing…") : variant.translated_text;
    var playable = variant.state === "FINAL" && Boolean(variant.translated_text);
    return '<div class="group-translation-v2__variant ' + (failed ? "is-failed" : "") + '" data-variant-language="' +
      esc(variant.target_language) + '"><span>' + esc(labels.readOnly || variant.recipient_count > 0 ? (labels.variants || "Translation") : (labels.noRecipients || "No recipients")) + ' · ' +
      esc(variant.target_language) + ' · ' + esc(state) +
      (labels.readOnly ? '' : ' · ' + esc(String(variant.recipient_count || 0)) + ' ' + esc(labels.recipients || "recipients")) + '</span><strong>' + esc(text) + '</strong>' +
      (playable ? playButton(variant.translated_text, variant.target_language, labels) : "") +
      (failed ? retryButton(item, variant.target_language, labels) : "") + '</div>';
  }

  function historyItem(item, labels) {
    labels = labels || {};
    var author = Boolean(item && (item.author_view || item.projection === "author"));
    var inconsistentFinal = item && item.state === "FINAL" && item.translated_text == null && !item.author_view && item.projection !== "author";
    var failed = item && item.state === "FAILED" || inconsistentFinal;
    var displayState = failed ? "FAILED" : item && item.state || "PROCESSING";
    var source = item && item.source_text || "";
    var translated = item && item.translated_text;
    var finalText = failed ? (labels.failed || "Translation failed") : translated == null ? (labels.pending || "Processing…") : translated;
    var common = ' class="group-translation-v2__item ' + (failed ? "is-failed" : "") + '" data-segment-id="' +
      esc(item && item.id) + '"';
    var metadata = '<div class="translation-history-context"><strong>' + esc(item.speaker_display_name || "") +
      '</strong><time datetime="' + esc(item.created_at || "") + '">' +
      esc(item.created_at ? new Date(item.created_at).toLocaleString() : "") +
      '</time></div>';
    if (author) {
      var variants = (item.variants || []).filter(function (variant) {
        return variant.target_language !== item.source_language;
      }).map(function (variant) { return authorVariant(item, variant, labels); }).join("");
      return '<article' + common + '>' + metadata + '<div class="group-translation-v2__item-meta"><span>' +
        esc(labels.author || "You sent") + '</span><span>' + esc(item.state || "PROCESSING") +
        '</span></div><p class="group-translation-v2__source-label">' + esc(labels.original || "Original") +
        ' · ' + esc(item.source_language) + '</p><p class="group-translation-v2__source">' + esc(source) +
        '</p>' + playButton(source, item.source_language, labels) +
        '<div class="group-translation-v2__distributed-label">' + esc(labels.variants || "Translation results") +
        '</div><div class="group-translation-v2__variants">' + variants + '</div></article>';
    }
    var original = item && item.show_original_enabled ?
      '<details class="group-translation-v2__original"' + (labels.readOnly ? ' open' : '') + '><summary>' + esc(labels.showOriginal || "Show original") +
      '</summary><p>' + esc(item.source_language) + ' · ' + esc(source) + '</p></details>' : "";
    return '<article' + common + '>' + metadata + '<div class="group-translation-v2__item-meta"><span>' +
      esc(labels.received || "Received translation") + ' · ' + esc(item && item.display_language || item && item.target_language) +
      '</span><span>' + esc(displayState) + '</span></div><p class="group-translation-v2__result">' +
      esc(finalText) + '</p>' + playButton(translated, item && item.target_language, labels) + original + '</article>';
  }

  window.GroupV3TranslationView = Object.freeze({
    panel: panel,
    historyItem: historyItem
  });
}(window));
