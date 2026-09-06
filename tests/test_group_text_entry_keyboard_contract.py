from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_group_text_entry_uses_ai_owned_keyboard_contract():
    template = (ROOT / "app/templates/group_communication_v3.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app/static/group-v3/group_v3_app.js").read_text(encoding="utf-8")
    contract = (
        ROOT / "app/static/group-v3/group_text_entry_keyboard_contract_v1.css"
    ).read_text(encoding="utf-8")

    assert "group_text_entry_keyboard_contract_v1.css?v=20260903-keyboard-1" in template
    assert "group_v3_app.js?v=20260906-r1-owner-qa-closure-1" in template
    assert '<textarea name="content" data-group-text-entry rows="1"' in app_js
    assert 'enterkeyhint="send" autocapitalize="sentences" spellcheck="true"' in app_js
    assert 'input name="title" data-group-text-entry' in app_js
    assert 'event.shiftKey || event.altKey || event.ctrlKey || event.metaKey' in app_js
    assert 'form.requestSubmit()' in app_js
    assert 'font-size: max(16px, 1em)' in contract
    assert 'font-size: 16px' in contract
    assert 'grid-template-rows: minmax(0, 1fr) auto' in contract
    assert 'scrollIntoView' not in app_js


def test_direct_communication_template_is_not_restyled_by_group_contract():
    direct_template = (ROOT / "app/templates/communication.html").read_text(
        encoding="utf-8"
    )
    assert "group_text_entry_keyboard_contract_v1.css" not in direct_template
