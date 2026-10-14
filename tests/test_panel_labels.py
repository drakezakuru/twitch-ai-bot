import json
import re
import subprocess
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import pytest
from jinja2 import Environment

from app.widget_inventory import WIDGET_INVENTORY


ROOT = Path(__file__).resolve().parents[1]
PARTIALS = ROOT / "templates/partials"


@dataclass
class Element:
    tag: str
    attrs: dict
    parent: object = None
    children: list = field(default_factory=list)
    text: str = ""
    direct_text: str = ""

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()


class Template(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Element("root", {})
        self.stack = [self.root]
        self.duplicates = []
        self.feed(re.sub(r"\{%.*?%\}", "", source, flags=re.S))

    def handle_starttag(self, tag, attrs):
        keys = [key for key, _ in attrs]
        self.duplicates.extend(key for key in set(keys) if keys.count(key) > 1)
        element = Element(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(element)
        if tag not in {"input", "br", "hr", "img", "meta", "link", "source", "wbr"}:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1].direct_text += data
        for element in self.stack:
            element.text += data

    @property
    def elements(self):
        return list(self.root.descendants())

    def by_id(self, identifier):
        return next(el for el in self.elements if el.attrs.get("id") == identifier)


def template(name):
    return Template((PARTIALS / f"{name}.html").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dictionaries():
    # Evaluate dictionary declarations only: no panel bootstrap, network or DOM calls.
    result = subprocess.run(
        ["node", "-e", r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/app.js', 'utf8');
const context = vm.createContext({});
const end = source.indexOf('const _legacySourceByNode');
vm.runInContext(source.slice(source.indexOf('const LANGS ='), end), context);
const files = ['static/app.js', ...fs.readdirSync('static/app')
    .filter(name => name.endsWith('.js') && name !== '21_panel_labels.js')
    .sort().map(name => 'static/app/' + name)];
for (const file of files) {
    const text = file === 'static/app.js' ? source.slice(end) : fs.readFileSync(file, 'utf8');
    for (const match of text.matchAll(/Object.assign\(LANGS\.(ru|en|ua),\s*\{[\s\S]*?\}\);/g)) {
        vm.runInContext(match[0], context, {filename: file});
    }
}
const additions = fs.readFileSync('static/app/21_panel_labels.js', 'utf8');
vm.runInContext(additions, context);
const isolated = vm.createContext({});
vm.runInContext("const LANGS = {ru: {sentinel: 'ru'}, en: {sentinel: 'en'}, ua: {sentinel: 'ua'}};", isolated);
vm.runInContext(additions, isolated);
console.log(JSON.stringify({all: vm.runInContext('LANGS', context),
    added: vm.runInContext('LANGS', isolated)}));
"""],
        cwd=ROOT, check=True, capture_output=True, text=True, timeout=15,
    )
    return json.loads(result.stdout)


def test_additions_extend_all_three_dictionaries_with_real_translations(dictionaries):
    added = dictionaries["added"]
    keys = set(added["ru"]) - {"sentinel"}
    assert len(keys) >= 70
    for language in ("ru", "en", "ua"):
        assert added[language]["sentinel"] == language
        assert set(added[language]) - {"sentinel"} == keys
        for key in keys:
            assert added[language][key].strip()
            assert added[language][key] != key
    for key in keys:
        assert added["ru"][key] != added["en"][key], key
        assert added["ua"][key] != added["en"][key], key


def test_new_keys_and_accessible_names_resolve_in_runtime_dictionaries(dictionaries):
    referenced = set()
    for path in PARTIALS.glob("*.html"):
        parsed = Template(path.read_text(encoding="utf-8"))
        assert not parsed.duplicates, (path.name, parsed.duplicates)
        for element in parsed.elements:
            for attr, key in element.attrs.items():
                if attr.startswith("data-i18n") and (
                    key.startswith("panel.") or attr == "data-i18n-aria-label" or path.stem == "brain"
                ):
                    resolved = ([key.replace("{{ widget.slug }}", widget.slug)
                                 for widget in WIDGET_INVENTORY]
                                if "{{ widget.slug }}" in key else [key])
                    for resolved_key in resolved:
                        referenced.add(resolved_key)
                        for language in ("ru", "en", "ua"):
                            assert dictionaries["all"][language].get(resolved_key), (
                                path.name, language, resolved_key)
    assert set(dictionaries["added"]["ru"]) - {"sentinel"} <= referenced


def localized_name(parsed, element):
    if element.attrs.get("data-i18n-aria-label"):
        return element.attrs["data-i18n-aria-label"]
    labels = [el for el in parsed.elements if el.tag == "label" and
              el.attrs.get("for") == element.attrs.get("id") and el.attrs.get("for")]
    parent = element.parent
    while parent:
        if parent.tag == "label":
            labels.append(parent)
        parent = parent.parent
    for label in labels:
        for el in [label, *label.descendants()]:
            if el.attrs.get("data-i18n"):
                return el.attrs["data-i18n"]
    return None


@pytest.mark.parametrize("section,identifier,kind", [
    ("chat", "chatMessage", "text"),
    ("chat", "chatBot", "select"),
    ("bots", "bpHz", "number"),
    ("bots", "bpEnabled", "switch"),
    ("chatlogger", "chatLogToken", "password"),
    ("analytics", "feedbackBotFilter", "select"),
    # Q09: редакторы профиля/lore/сводок переехали из «Мозга» в карточку канала
    ("brain", "sumRunStart", "datetime-local"),
    ("brain", "sumRunEnd", "datetime-local"),
    ("channels", "ccpBio", "textarea"),
    ("channels", "ccpFaceFile", "file"),
    ("channels", "cpSumLiveEnabled", "switch"),
    ("bots", "botAIKey", "password"),
    ("bots", "affinityContact", "range"),
    ("bots", "affinityChat", "range"),
    # Q15b: cpModels/cpVisionModels заменены редактором cpModelsEditor (динамический, вне шаблона)
    ("bots", "botAIModelSelect", "select"),
    # Q16 F3: глобальная TTS-форма убрана — скорость теперь botTTSSpeed (bots.html)
    ("bots", "botTTSSpeed", "range"),
    ("widgets", "waSubTarget", "number"),
    ("widgets", "wa2ArHair", "color"),
    ("widgets", "wa2ArOutfit", "color"),
    ("widgets", "wa2ArAccent", "color"),
    ("widgets", "wa2ArEye", "color"),
    ("director", "directorRangeSmallMax", "number"),
])
def test_controls_have_localized_semantic_names(section, identifier, kind, dictionaries):
    parsed = template(section)
    control = parsed.by_id(identifier)
    assert (control.attrs.get("role") or control.attrs.get("type", control.tag)) == kind
    key = localized_name(parsed, control)
    assert key, identifier
    for language in ("ru", "en", "ua"):
        assert dictionaries["all"][language].get(key), (identifier, key, language)


def test_permission_checkboxes_keep_values_and_translate_their_labels(dictionaries):
    # Q16 F4: чекбоксы доступа переехали вместе с консолью в bots.html
    parsed = template("bots")
    permissions = parsed.by_id("modTTSPermissions")
    checkboxes = [el for el in permissions.descendants() if el.tag == "input"]
    assert [el.attrs["value"] for el in checkboxes] == ["send_tts", "play_media", "play_sound", "upload_media"]
    assert "checked" in checkboxes[0].attrs
    for checkbox in checkboxes:
        assert checkbox.attrs["type"] == "checkbox"
        key = localized_name(parsed, checkbox)
        assert key == "panel.permission." + checkbox.attrs["value"]
        for language in ("ru", "en", "ua"):
            assert dictionaries["all"][language][key] != checkbox.attrs["value"]


def test_translating_text_never_removes_nested_controls():
    for path in PARTIALS.glob("*.html"):
        parsed = Template(path.read_text(encoding="utf-8"))
        for element in parsed.elements:
            if "data-i18n" in element.attrs:
                assert not any(child.tag in {"input", "select", "textarea", "button"}
                               for child in element.descendants()), (path.name, element.attrs)


def test_all_icon_only_buttons_have_localized_accessible_names():
    for path in PARTIALS.glob("*.html"):
        for element in Template(path.read_text(encoding="utf-8")).elements:
            if element.tag == "button" and not re.search(r"[A-Za-zА-Яа-я]", element.text):
                assert element.attrs.get("data-i18n-aria-label"), (path.name, element.attrs)
                assert element.attrs.get("aria-label"), (path.name, element.attrs)


@pytest.mark.parametrize("section,identifiers", [
    ("dashboard", ["runtimeStatus", "moderationWidgetList"]),
    ("analytics", ["feedbackSummaryBox", "perBotStatsBox"]),
    ("brain", ["summarizerRunsList"]),
    ("channels", ["cpLoreList", "cpSumLiveScopeStatus"]),
    ("bots", ["botViewerMemoryList", "botLearningList"]),
    ("bots", ["bpWhisperWarn", "bpStatus"]),
    ("chatlogger", ["chatLogNow", "chatLogTokenStatus", "chatLoggerResults"]),
    ("channels", ["channelsOverview", "bulkChannelsResults"]),
    ("settings", ["providerStatusSummary", "offlineModeStatus"]),
    ("widgets", ["widgetsAdminHint"]),
    ("director", ["directorLifecycleHint", "directorConfigStatus"]),
])
def test_stable_status_containers_announce_updates(section, identifiers):
    parsed = template(section)
    for identifier in identifiers:
        assert parsed.by_id(identifier).attrs.get("aria-live") == "polite"


def test_distinct_director_range_bounds():
    parsed = template("director")
    keys = [parsed.by_id(f"directorRange{size}{bound}").attrs["data-i18n-aria-label"]
            for size in ("Small", "Medium", "Large") for bound in ("Min", "Max")]
    assert len(set(keys)) == 6


@pytest.mark.parametrize("section,identifier,handler", [
    ("bots", "bpEnabled", "uiToggle(this, () => toggleBeepPipeline())"),
    # Q16 F5: автозапись replay — тумблер бота (bots.html)
    ("bots", "botReplayAutoRecord", "uiToggle(this, () => saveBotReplayAuto())"),
    # Q16 F1: глобальный рубильник провокаций убран (тумблер бота conflictEnabled — bots.html)
])
def test_accessible_names_preserve_arrow_callback_handlers(section, identifier, handler):
    control = template(section).by_id(identifier)
    assert control.attrs["onclick"] == handler
    assert control.attrs.get("data-i18n-aria-label")
    assert control.attrs["role"] == "switch"
    assert control.attrs["tabindex"] == "0"


def test_machine_values_and_provider_names_are_not_translated():
    parsed = template("settings")
    providers = parsed.by_id("globalAIProvider")
    for option in providers.children:
        assert "data-i18n" not in option.attrs
    channels = template("channels")
    assert [el.attrs["value"] for el in channels.by_id("cpLoreNewSource").children] == ["manual", "summary", "chat"]
    assert [el.attrs["value"] for el in channels.by_id("ccpStyle").children] == ["", "educational", "entertaining", "competitive"]
    assert channels.by_id("ccpFaceFile").attrs["onchange"] == "uploadGlobalStreamerFace(this, 'ccp')"


@pytest.mark.parametrize("section,identifier", [
    ("bots", identifier) for identifier in (
        "moderationMode", "moderationTimeoutPolicy", "moderationToggle",
        "moderationCanTimeoutToggle", "moderationEventSubToggle", "antispamViewerToggle",
        "modAntispamLinksToggle", "modAntispamCaps", "modAntispamRepeat", "modAntispamEmote",
        "modAntispamExempt", "modRulePattern", "modRuleCategory", "modRuleAction",
        "modRuleSeverity", "modRuleChannel", "modRuleImportText", "modEventsUser",
        "modEventsCategory", "modEventsChannel", "modTestText",
    )
] + [
    # Q16 F4: консоль модератора TTS в карточке бота
    ("bots", identifier) for identifier in ("modTTSRole", "modTTSDefaultAlias", "modMediaFile")
] + [
    ("widgets", identifier) for identifier in (
        "waNpSource", "waNpIcon", "waNpLastfmUser", "waNpLastfmKey", "waNpMprisPlayer",
        "waBgEnabled", "waBgSensitivity", "waBgInterval", "waBgPreDelay", "waBgDuration",
        "waBgPercentRange", "waBgImage", "waBgPrompt", "waBgCategories", "wa2LtName",
        "wa2LtTagline", "wa2LtSocial", "wa2LtAvatar", "wa2LtTheme", "wa2LtVisible",
        "wa2MascotPreset", "wa2MascotUrl", "wa2MascotIdle", "wa2ArCorner", "wa2ArSpeed",
        "wa2ArSize", "wa2RlParticipants", "wa2RlSpin", "wa2RlAuto", "wa2RlWinner",
        "wa2RlVisible", "wa2LeTheme", "wa2LeFilter", "wa2ReKind", "wa2ReUser", "wa2ReAmount",
    )
])
def test_remaining_template_controls_have_explicit_localized_names(section, identifier, dictionaries):
    parsed = template(section)
    key = localized_name(parsed, parsed.by_id(identifier))
    assert key, identifier
    for language in ("ru", "en", "ua"):
        assert dictionaries["all"][language].get(key), (identifier, language, key)


@pytest.mark.parametrize("section,identifier,values", [
    ("bots", "moderationMode", ["off", "log_only", "replace", "full"]),
    ("bots", "moderationTimeoutPolicy", ["auto", "ask", "learn"]),
    ("bots", "modRuleCategory", ["custom", "insult", "hate", "threat", "sexual", "spam"]),
    ("bots", "modRuleAction", ["replace", "block", "timeout", "log"]),
    ("bots", "modEventsCategory", ["", "insult", "hate", "threat", "sexual", "spam", "custom"]),
    ("bots", "modTTSRole", ["owner", "moderator", "viewer", "bot"]),
    ("widgets", "wa2LtTheme", ["minimal", "neon", "glass"]),
    ("widgets", "wa2MascotPreset", ["blob", "owl", "cat", "bot", "ghost", "custom"]),
    ("widgets", "wa2ArCorner", ["br", "bl", "tr", "tl"]),
    ("widgets", "wa2ArSpeed", ["slow", "normal", "fast", "turbo"]),
    ("widgets", "wa2ArSize", ["S", "M", "L", "XL"]),
    ("widgets", "wa2LeTheme", ["neon", "glass", "rainbow", "minimal"]),
    ("widgets", "wa2LeFilter", ["", "follow", "subscribe", "cheer", "raid"]),
    ("widgets", "wa2ReKind", ["manual", "follow", "subscribe", "cheer", "raid"]),
])
def test_translated_options_preserve_backend_values(section, identifier, values, dictionaries):
    options = template(section).by_id(identifier).children
    assert [option.attrs["value"] for option in options] == values
    for option in options:
        key = option.attrs["data-i18n"]
        for language in ("ru", "en", "ua"):
            assert dictionaries["all"][language].get(key), (identifier, key, language)


@pytest.mark.parametrize("section,start,end", [
    ("bots", "<!-- Общий режим + настройки -->", "<!-- ========== CHAT USERS TAB"),
    ("widgets", '<label class="text-sm"><strong data-i18n="widgets.np_source">', '<!-- Schedule -->'),
    ("widgets", "<!-- §13: Blur Guard", '<div id="waBgStatus"'),
    # Q12a: карточка «Прочие виджеты — контент» удалена — формы переехали в карточки
    # каталога (условия {% if widget.slug == ... %}), их перевод покрывает test_q12_widget_forms.
])
def test_targeted_regions_have_no_untranslated_copy(section, start, end):
    source = (PARTIALS / f"{section}.html").read_text(encoding="utf-8")
    region = source.split(start, 1)[1].split(end, 1)[0]
    parsed = Template(region)
    for element in parsed.elements:
        # tts-bot/chat-reader/tts-raw — технические имена аудио-консьюмеров (Q16 F4)
        if element.tag == "code" or element.direct_text.strip() in {"📥 CSV", "Last.fm", "MPRIS / playerctl", "tts-bot", "chat-reader", "tts-raw"}:
            continue
        if re.search(r"[A-Za-zА-Яа-яІіЇїЄє]", element.direct_text):
            assert element.attrs.get("data-i18n"), (section, element.direct_text, element.attrs)
        if element.attrs.get("placeholder"):
            assert element.attrs.get("data-i18n-placeholder"), (section, element.attrs)


def test_now_playing_fallback_keeps_provider_values_commands_and_password_type(dictionaries):
    parsed = template("widgets")
    control = parsed.by_id("waNpSource")
    assert control.attrs["onchange"] == "waNpSourceSave()"
    assert [option.attrs["value"] for option in control.children] == ["manual", "lastfm", "mpris"]
    assert control.children[0].attrs["data-i18n"] == "panel.np.manual"
    assert "data-i18n" not in control.children[1].attrs
    assert "data-i18n" not in control.children[2].attrs
    assert parsed.by_id("waNpLastfmKey").attrs["type"] == "password"
    assert any(element.tag == "code" and element.text == "!np clear" for element in parsed.elements)
    for language in ("ru", "en", "ua"):
        assert dictionaries["all"][language]["panel.np.command"].startswith("!np <")


@pytest.mark.parametrize("identifier,attribute,value", [
    ("waBgProtectionMode", "onchange", "waBgModeSync()"),
    ("waBgDuration", "oninput", "waBgPreviewSync(this.value, document.getElementById('waBgPercent').value,true)"),
    ("waBgPercentRange", "oninput", "document.getElementById('waBgPercent').value=this.value;waBgPreviewSync(document.getElementById('waBgDuration').value,this.value,true)"),
    ("wa2MascotIdle", "min", "30"),
    ("wa2MascotIdle", "max", "3600"),
    ("wa2RlSpin", "min", "1"),
    ("wa2RlSpin", "max", "60"),
    ("wa2ArHair", "type", "color"),
    ("wa2ArOutfit", "type", "color"),
    ("wa2ArAccent", "type", "color"),
    ("wa2ArEye", "type", "color"),
])
def test_translated_widget_controls_preserve_input_contracts(identifier, attribute, value):
    control = template("widgets").by_id(identifier)
    assert control.attrs[attribute] == value
    if control.attrs.get("type") == "color":
        assert control.parent.tag == "label"
        assert "data-i18n" not in control.parent.attrs
        assert any(child.attrs.get("data-i18n") for child in control.parent.children)


def test_catalog_renders_translated_examples_decisions_and_unchanged_urls(dictionaries):
    source = (PARTIALS / "widgets.html").read_text(encoding="utf-8")
    rendered = Environment(autoescape=True).from_string(source).render(widget_inventory=WIDGET_INVENTORY)
    parsed = Template(rendered)
    assert not parsed.duplicates
    cards = {el.attrs["data-widget-slug"]: el for el in parsed.elements if "data-widget-slug" in el.attrs}
    assert set(cards) == {widget.slug for widget in WIDGET_INVENTORY}
    for widget in WIDGET_INVENTORY:
        elements = list(cards[widget.slug].descendants())
        by_key = {el.attrs["data-i18n"]: el for el in elements if "data-i18n" in el.attrs}
        for suffix, fallback in (("example", widget.example), ("note", widget.catalog_note)):
            key = f"panel.catalog.{suffix}_{widget.slug}"
            assert by_key[key].text == fallback
            assert dictionaries["all"]["ru"][key] == fallback
            for language in ("en", "ua"):
                assert dictionaries["all"][language][key] != fallback
        output = next(el for el in elements if el.tag == "input" and "readonly" in el.attrs)
        assert output.attrs["value"] == widget.route
        assert output.attrs["data-i18n-aria-label"] == "panel.catalog.url"
        assert any(el.tag == "iframe" and el.attrs.get("src") == widget.preview_url
                   and el.attrs.get("data-i18n-title") == "widgets.preview_title" for el in elements)
        if widget.binding_slug:
            assert any(el.attrs.get("onclick") == f"waWidgetBindingAdd('{widget.binding_slug}')" for el in elements)
        else:
            # Q11b: у виджета без биндингов нет ни одного упоминания биндингов
            assert not any(
                "bindings" in (attr or "") for el in elements for attr in el.attrs.values() if isinstance(attr, str)
            ), widget.slug
