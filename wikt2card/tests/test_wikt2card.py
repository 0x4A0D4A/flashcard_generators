"""Offline tests for wikt2card.

Parsing is tested against saved Wiktionary pages in ./fixtures, and AnkiConnect
is replaced by a fake, so no network access or running Anki is needed.
"""

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wikt2card as w  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(word: str) -> str:
    return (FIXTURES / f"{word}.html").read_text(encoding="utf-8")


def parse(language: str, word: str):
    return w.parse_wiktionary_entry(load(word), language, word)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def test_eau_definitions_and_examples():
    info, audio = parse("french", "eau")
    senses = info["definitions"]["Noun"]
    assert len(senses) == 5
    assert senses[0]["text"].startswith("water, a liquid")  # no stray " ,"
    assert "H2O" in senses[2]["text"]
    assert senses[0]["examples"][0].endswith("He drank a cool glass of water.")
    assert audio and audio.startswith("https://") and audio.endswith(".mp3")


def test_pronunciation_skips_rhymes_and_labels_dialects():
    info, _ = parse("french", "eau")
    assert info["pronunciation"] == ["/o/"]  # "-o" is the rhyme line
    info, _ = parse("french", "manger")
    assert "/mɑ̃.ʒe/" in info["pronunciation"]
    assert any(p.startswith("Paris:") for p in info["pronunciation"])


def test_multiple_parts_of_speech():
    info, _ = parse("french", "manger")
    assert set(info["definitions"]) == {"Verb", "Noun"}
    assert info["definitions"]["Verb"][0]["text"] == "(transitive) to eat"


def test_inline_synonyms_are_collected():
    info, _ = parse("french", "manger")
    assert "dévorer" in info["synonyms"]


def test_derived_terms_have_no_edit_link():
    for lang, word in (("french", "eau"), ("french", "manger"), ("irish", "uisce")):
        info, _ = parse(lang, word)
        assert info["derived"]
        assert "edit" not in info["derived"]


def test_etymology_has_no_footnote_markers():
    info, _ = parse("irish", "uisce")
    assert info["etymology"]
    assert "[1]" not in info["etymology"][0]


def test_irish_entry():
    info, _ = parse("irish", "uisce")
    assert info["definitions"]["Noun"][0]["text"] == "water"


def test_missing_language_raises():
    with pytest.raises(w.WiktError):
        parse("klingon", "eau")


# --------------------------------------------------------------------------
# Language / deck helpers
# --------------------------------------------------------------------------

def test_language_helpers():
    assert w.language_title("old irish") == "Old Irish"
    assert w.language_heading_id("old irish") == "Old_Irish"
    assert w.language_heading_id("FRENCH") == "French"


def test_default_deck_name_matches_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "CONFIG_FILE", tmp_path / "config.json")
    assert w.get_deck_name("french") == "wikt2card French"
    assert w.get_deck_name("middle english") == "wikt2card Middle English"
    assert w.get_deck_name("french", "Custom") == "Custom"


def test_configured_deck_name(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"defaults": {"german": "wikt2card German::Nouns"}}')
    monkeypatch.setattr(w, "CONFIG_FILE", cfg)
    assert w.get_deck_name("german") == "wikt2card German::Nouns"


# --------------------------------------------------------------------------
# Card formatting / note payload
# --------------------------------------------------------------------------

def test_format_for_anki_escapes_html():
    info = {
        "pronunciation": ["/o/"],
        "etymology": ["a < b & c"],
        "definitions": {"Noun": [{"text": "<script>", "examples": ["q & a"], "subsenses": []}]},
        "synonyms": ["<b>"], "antonyms": [], "derived": [], "related": [],
    }
    out = w.format_for_anki(info)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "a &lt; b &amp; c" in out
    assert "&lt;b&gt;" in out


def test_format_renders_subsenses():
    sub = {"text": "inner", "examples": [], "subsenses": []}
    info = {
        "pronunciation": [], "etymology": [],
        "definitions": {"Noun": [{"text": "outer", "examples": [], "subsenses": [sub]}]},
        "synonyms": [], "antonyms": [], "derived": [], "related": [],
    }
    assert "<ol type='a'><li>inner</li></ol>" in w.format_for_anki(info)


def test_audio_filename_keeps_extension_and_is_safe():
    url = "https://upload.wikimedia.org/wikipedia/commons/transcoded/0/04/Fr-eau.ogg/Fr-eau.ogg.mp3"
    assert w.audio_filename(url) == "wikt2card_Fr-eau.ogg.mp3"
    odd = "https://x/y/LL-Q150_%28fra%29-a%20b.wav"
    assert w.audio_filename(odd) == "wikt2card_LL-Q150__fra_-a_b.wav"


def test_build_note_scope_tags_and_audio():
    note = w.build_note("D", "eau", "back", "https://x/Fr-eau.ogg", "old irish", "Basic")
    assert note["deckName"] == "D"
    assert note["options"]["duplicateScope"] == "deck"
    assert note["options"]["duplicateScopeOptions"] == {"deckName": "D", "checkChildren": False}
    assert note["tags"] == ["wikt2card", "wikt2card::old_irish"]
    assert note["audio"][0]["filename"] == "wikt2card_Fr-eau.ogg"
    assert "audio" not in w.build_note("D", "eau", "back")


# --------------------------------------------------------------------------
# End-to-end flow against a fake AnkiConnect
# --------------------------------------------------------------------------

class FakeAnki:
    def __init__(self, decks=(), can_add=True):
        self.decks = list(decks)
        self.can_add = can_add
        self.calls = []

    def __call__(self, action, **params):
        self.calls.append((action, params))
        if action == "version":
            return 6
        if action == "deckNames":
            return self.decks
        if action == "createDeck":
            self.decks.append(params["deck"])
            return 1
        if action == "canAddNotesWithErrorDetail":
            return [{"canAdd": self.can_add}]
        if action == "addNote":
            return 42
        raise AssertionError(f"unexpected action {action}")

    def actions(self):
        return [a for a, _ in self.calls]


def make_args(**kw):
    ns = dict(language="french", word="eau", deck="Test", note_type="Basic",
              yes=False, verbose=False)
    ns.update(kw)
    return argparse.Namespace(**ns)


@pytest.fixture
def anki(monkeypatch):
    fake = FakeAnki()
    monkeypatch.setattr(w, "invoke_anki", fake)
    monkeypatch.setattr(w, "fetch_wiktionary_entry", lambda word: load(word))
    return fake


def test_declining_creates_nothing(anki, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    w.run(make_args())
    assert "createDeck" not in anki.actions()
    assert "addNote" not in anki.actions()


def test_confirming_creates_deck_then_adds(anki, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")
    w.run(make_args())
    acts = anki.actions()
    assert acts.index("createDeck") < acts.index("addNote")
    # new deck: no duplicate check against a deck that doesn't exist yet
    assert "canAddNotesWithErrorDetail" not in acts


def test_yes_flag_skips_prompt(anki, monkeypatch):
    def no_prompt(_):
        raise AssertionError("should not prompt")
    monkeypatch.setattr("builtins.input", no_prompt)
    w.run(make_args(yes=True))
    assert "addNote" in anki.actions()


def test_duplicate_in_existing_deck_exits(anki, monkeypatch):
    anki.decks.append("Test")
    anki.can_add = False
    monkeypatch.setattr("builtins.input", lambda _: "y")
    with pytest.raises(SystemExit):
        w.run(make_args())
    assert "addNote" not in anki.actions()


def test_check_and_add_use_the_same_note(anki, monkeypatch):
    anki.decks.append("Test")
    monkeypatch.setattr("builtins.input", lambda _: "y")
    w.run(make_args())
    check = next(p for a, p in anki.calls if a == "canAddNotesWithErrorDetail")
    add = next(p for a, p in anki.calls if a == "addNote")
    assert check["notes"][0] == add["note"]


def test_anki_not_running_is_a_clean_error(monkeypatch):
    def refuse(*a, **k):
        raise w.requests.exceptions.ConnectionError()
    monkeypatch.setattr(w.SESSION, "post", refuse)
    with pytest.raises(w.AnkiError, match="Is Anki running"):
        w.invoke_anki("version")
