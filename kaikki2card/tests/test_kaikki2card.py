"""Offline tests for kaikki2card.

A tiny hand-made Irish-like dump stands in for the 3 GB raw file, and
AnkiConnect is replaced by a fake, so nothing touches the network or a real
Anki collection.
"""

import gzip
import json
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import kaikki2card as k  # noqa: E402


def entry(word, pos="noun", lang_code="ga", senses=None, **extra):
    e = {"word": word, "pos": pos, "lang": "Irish", "lang_code": lang_code,
         "senses": senses if senses is not None else [{"glosses": [f"gloss of {word}"]}]}
    e.update(extra)
    return e


def lines(entries):
    return [json.dumps(e, ensure_ascii=False).encode() for e in entries]


DUMP = [
    entry("bean", senses=[{"glosses": ["woman"], "tags": ["feminine"]},
                          {"glosses": ["wife"], "examples": [
                              {"text": "Is bean mhaith í.", "english": "She is a good woman.", "type": "example"},
                              {"text": "A cited line", "ref": "1900, Somebody", "type": "quotation"}]}],
          forms=[{"form": "mná", "tags": ["genitive", "singular"]},
                 {"form": "an bhean", "tags": ["definite"]},            # multi-word -> dropped
                 {"form": "no-table-tags", "tags": ["table-tags"]},     # junk -> dropped
                 {"form": "bad", "tags": ["error-unrecognized-form"]},  # junk -> dropped
                 {"form": "bean", "tags": ["nominative"]}],             # same as headword -> dropped
          sounds=[{"ipa": "/bʲan̪ˠ/", "tags": ["Munster"]}, {"note": "no ipa"}],
          etymology_text="PIE word\n *gʷḗn\nFrom Old Irish ben.",
          derived=[{"word": "bean chéile"}], synonyms=[{"word": "baintreach"}]),
    entry("bhean", senses=[{"glosses": ["lenited form of bean"], "tags": ["form-of", "lenition"],
                            "form_of": [{"word": "bean"}]}]),
    entry("cat", senses=[{"glosses": ["cat"]}]),                         # no stub for "gcat"
    entry("bád", senses=[{"glosses": ["boat"]}]),
    entry("a", senses=[{"glosses": ["vocative particle"]}]),
    entry("A", senses=[{"glosses": ["the letter A"]}]),
    entry("Murchadh", pos="name", senses=[{"glosses": ["a male given name"]}]),
    entry("lúb", senses=[{"glosses": ["alt of loop"], "alt_of": [{"word": "loop2"}]}]),  # missing target
    entry("ciorcal", senses=[{"glosses": ["see ciorcal2"], "form_of": [{"word": "ciorcal2"}]}]),
    entry("ciorcal2", senses=[{"glosses": ["see ciorcal"], "form_of": [{"word": "ciorcal"}]}]),  # cycle
    entry("water", lang_code="en", senses=[{"glosses": ["x"]}],
          translations=[{"lang_code": "ga", "word": "uisce"}]),
]
# An English entry that merely mentions the Irish code in a translation
DUMP_LINES = lines(DUMP)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    k.load_language(c, "ga", DUMP_LINES)
    return c


# --------------------------------------------------------------------------
# Compacting and loading
# --------------------------------------------------------------------------

def test_compact_entry_filters_and_cleans():
    c = k.compact_entry(DUMP[0])
    assert [s["glosses"] for s in c["senses"]] == [["woman"], ["wife"]]
    assert c["senses"][1]["examples"] == [{"text": "Is bean mhaith í.", "translation": "She is a good woman."}]
    assert c["sounds"] == [{"ipa": "/bʲan̪ˠ/", "tags": ["Munster"]}]
    assert c["etymology"] == "From Old Irish ben."
    assert c["derived"] == ["bean chéile"] and c["synonyms"] == ["baintreach"]


def test_usable_forms_drops_noise():
    assert k.usable_forms(DUMP[0]) == [("mná", "genitive singular")]


def test_load_language_only_keeps_that_language(conn):
    n = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    assert n == len(DUMP) - 1  # the English entry is skipped
    assert conn.execute("SELECT COUNT(*) FROM entries WHERE word='water'").fetchone()[0] == 0


def test_reload_replaces_a_language_but_keeps_others(conn):
    k.load_language(conn, "fr", lines([entry("eau", lang_code="fr")]))
    k.load_language(conn, "ga", lines([entry("bean")]))  # rebuild ga with fewer entries
    langs = dict(conn.execute("SELECT lang, COUNT(*) FROM entries GROUP BY lang"))
    assert langs == {"ga": 1, "fr": 1}


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

def test_exact_headword(conn):
    r = k.resolve_token(conn, "ga", "bean")
    assert (r.label, r.lemmas) == ("exact", ["bean"])


def test_stub_is_followed_to_lemma(conn):
    r = k.resolve_token(conn, "ga", "bhean")
    assert (r.label, r.lemmas) == ("exact+form_of", ["bean"])


def test_mutation_candidate_when_no_stub_exists(conn):
    r = k.resolve_token(conn, "ga", "gcat")
    assert (r.label, r.candidate, r.lemmas) == ("mutation", "cat", ["cat"])


def test_inflected_form_table(conn):
    r = k.resolve_token(conn, "ga", "mná")
    assert (r.label, r.lemmas) == ("form-table", ["bean"])


def test_unresolved(conn):
    r = k.resolve_token(conn, "ga", "zzzz")
    assert r.label == "unresolved" and not r.entries


def test_stub_with_missing_target_is_kept(conn):
    r = k.resolve_token(conn, "ga", "lúb")
    assert r.lemmas == ["lúb"]


def test_stub_cycle_terminates(conn):
    r = k.resolve_token(conn, "ga", "ciorcal")
    assert r.entries  # no infinite loop


def test_resolve_text_prefers_lowercase_spelling(conn):
    result = k.resolve_text(conn, "ga", "A bean. A cat. a bád.")
    assert result["freq"]["a"] == 3
    assert result["resolutions"]["a"].lemmas == ["a"]  # the particle, not the letter "A"


def test_resolve_text_keeps_capital_for_names(conn):
    result = k.resolve_text(conn, "ga", "Murchadh agus Murchadh.")
    assert result["resolutions"]["murchadh"].lemmas == ["Murchadh"]


def test_coverage_report(conn):
    result = k.resolve_text(conn, "ga", "bean bhean gcat zzzz zzzz")
    out = k.format_coverage(result)
    assert "Tokens: 5" in out and "unresolved" in out and "zzzz (2)" in out


# --------------------------------------------------------------------------
# Cards
# --------------------------------------------------------------------------

TEXT = ("Bhí bean ann. Tá bean eile ann. Bhí cat ann agus cat eile. "
        "Murchadh agus Murchadh. Tá bád ann <b>agus</b> bád eile.")


def cards_for(conn, **kw):
    return k.build_cards(k.resolve_text(conn, "ga", TEXT), TEXT, **kw)


def test_cards_skip_proper_nouns_and_rank_by_frequency(conn):
    cards = cards_for(conn, min_count=2)
    fronts = [c["front"] for c in cards]
    assert "Murchadh" not in fronts
    assert set(fronts) == {"bean", "cat", "bád"}
    assert cards[0]["count"] >= cards[-1]["count"]


def test_cards_have_no_limit_by_default(conn):
    all_cards = cards_for(conn, min_count=1)
    assert len(all_cards) > 2
    assert len(cards_for(conn, min_count=1, limit=2)) == 2
    assert [c["front"] for c in cards_for(conn, min_count=1, limit=2)] == \
        [c["front"] for c in all_cards[:2]]


def test_cards_cli_limit_is_optional_and_validated(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    raw = k.raw_path()
    raw.parent.mkdir(parents=True)
    with gzip.open(raw, "wb") as fh:
        for line in DUMP_LINES:
            fh.write(line + b"\n")
    assert k.main(["build", "--lang", "ga"]) == 0
    text = tmp_path / "t.txt"
    text.write_text(TEXT, encoding="utf-8")
    out = tmp_path / "c.tsv"
    assert k.main(["cards", "--lang", "ga", str(text), "--skip-top", "0", "--min-count", "1",
                   "--out", str(out)]) == 0
    unlimited = len(out.read_text(encoding="utf-8").splitlines())
    assert k.main(["cards", "--lang", "ga", str(text), "--skip-top", "0", "--min-count", "1",
                   "--limit", "1", "--out", str(out)]) == 0
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1 < unlimited
    capsys.readouterr()
    assert k.main(["cards", "--lang", "ga", str(text), "--limit", "0"]) == 2
    assert "--limit must be at least 1" in capsys.readouterr().out


def test_cards_min_count_skip_top_and_known(conn):
    assert cards_for(conn, min_count=5) == []
    top = cards_for(conn, min_count=2)[0]["front"]
    assert top not in [c["front"] for c in cards_for(conn, min_count=2, skip_top=1)]
    assert "bean" not in [c["front"] for c in cards_for(conn, min_count=2, known=frozenset({"bean"}))]


def test_card_back_has_ipa_example_sentence_and_escaping(conn):
    cards = {c["front"]: c for c in cards_for(conn, min_count=2)}
    assert "/bʲan̪ˠ/" in cards["bean"]["back"]
    assert "Is bean mhaith í." in cards["bean"]["back"]
    assert "<em>Bhí bean ann.</em>" in cards["bean"]["back"]
    assert "&lt;b&gt;agus&lt;/b&gt;" in cards["bád"]["back"]  # sentence text is escaped
    assert "<b>agus</b>" not in cards["bád"]["back"]


def test_entry_to_html_escapes_glosses():
    e = k.compact_entry(entry("x", senses=[{"glosses": ["a < b & c"]}]))
    html = k.entry_to_html({**e, "word": "x<y", "pos": "noun"})
    assert "a &lt; b &amp; c" in html and "x&lt;y" in html


# --------------------------------------------------------------------------
# Anki (fake AnkiConnect, real wikt2card helpers)
# --------------------------------------------------------------------------

@pytest.fixture
def anki(monkeypatch):
    w = k.load_wikt2card()

    class Fake:
        def __init__(self):
            self.decks, self.calls, self.dupes, self.added = [], [], set(), []

        def __call__(self, action, **params):
            self.calls.append(action)
            if action == "version":
                return 6
            if action == "deckNames":
                return self.decks
            if action == "createDeck":
                self.decks.append(params["deck"])
                return 1
            if action == "canAddNotesWithErrorDetail":
                return [{"canAdd": params["notes"][0]["fields"]["Front"] not in self.dupes}]
            if action == "addNote":
                self.added.append(params["note"])
                return 1
            raise AssertionError(action)

    fake = Fake()
    monkeypatch.setattr(w, "invoke_anki", fake)
    monkeypatch.setattr(k, "load_wikt2card", lambda: w)
    return fake


CARDS = [{"front": "bean", "back": "<p>b</p>", "count": 3, "forms": ["bean"]},
         {"front": "cat", "back": "<p>c</p>", "count": 2, "forms": ["cat"]}]


def test_anki_creates_deck_then_adds_all(anki):
    assert k.add_cards_to_anki(CARDS, "ga", "Deck", "Basic", assume_yes=True) == 0
    assert anki.calls.count("addNote") == 2
    assert anki.calls.index("createDeck") < anki.calls.index("addNote")


def test_anki_skips_duplicates_in_existing_deck(anki):
    anki.decks.append("Deck")
    anki.dupes.add("bean")
    k.add_cards_to_anki(CARDS, "ga", "Deck", "Basic", assume_yes=True)
    assert anki.calls.count("addNote") == 1


MP3 = "https://upload.wikimedia.org/wikipedia/commons/transcoded/f/f2/Fr-%C3%A9tranger.ogg/Fr-%C3%A9tranger.ogg.mp3"
OGG = "https://upload.wikimedia.org/wikipedia/commons/f/f2/Fr-%C3%A9tranger.ogg"


def test_pick_audio_url_prefers_mp3_then_ogg_and_ignores_junk():
    assert k.pick_audio_url([]) is None
    assert k.pick_audio_url([{"sounds": [{"ipa": "/x/"}]}]) is None
    assert k.pick_audio_url([{"sounds": [{"ogg_url": OGG, "mp3_url": MP3}]}]) == MP3
    assert k.pick_audio_url([{"sounds": [{"ogg_url": OGG}]}]) == OGG
    assert k.pick_audio_url([{"sounds": [{"mp3_url": "file:///etc/passwd"}]}]) is None
    # first recording wins, across entries
    assert k.pick_audio_url([{"sounds": []}, {"sounds": [{"mp3_url": MP3}, {"mp3_url": OGG}]}]) == MP3


def test_audio_survives_compact_entry_and_reaches_the_card(conn):
    e = k.compact_entry(entry("x", sounds=[{"audio": "a.ogg", "ogg_url": OGG, "mp3_url": MP3}]))
    assert k.pick_audio_url([e]) == MP3


def test_anki_sends_audio_for_cards_that_have_it(anki):
    cards = [{**CARDS[0], "audio_url": MP3}, CARDS[1]]
    k.add_cards_to_anki(cards, "fr", "Deck", "Basic", assume_yes=True)
    with_audio, without = anki.added
    assert with_audio["audio"][0]["url"] == MP3
    assert with_audio["audio"][0]["fields"] == ["Front"]
    assert with_audio["audio"][0]["filename"].endswith(".mp3")
    assert "audio" not in without


def test_anki_default_tags_without_tag_option(anki):
    k.add_cards_to_anki(CARDS, "ga", "Deck", "Basic", assume_yes=True)
    assert all(n["tags"] == ["kaikki2card", "kaikki2card::ga"] for n in anki.added)


def test_anki_extra_tags_on_new_notes_only(anki):
    anki.decks.append("Deck")
    anki.dupes.add("bean")
    k.add_cards_to_anki(CARDS, "ga", "Deck", "Basic", assume_yes=True,
                        tags=["book::niamh", "ch01"])
    # the existing card is skipped (not re-added, not re-tagged); the new one gets the tags
    assert [n["fields"]["Front"] for n in anki.added] == ["cat"]
    assert anki.added[0]["tags"] == ["kaikki2card", "kaikki2card::ga", "book::niamh", "ch01"]
    assert "updateNoteTags" not in anki.calls and "addTags" not in anki.calls


def test_validate_tags():
    assert k.validate_tags(["book::niamh", "ch01"]) is None
    assert k.validate_tags([]) is None
    assert "whitespace" in k.validate_tags(["book niamh"])
    assert "whitespace" in k.validate_tags(["ok", " "])


def test_cards_cli_tag_goes_into_tsv_and_bad_tag_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    raw = k.raw_path()
    raw.parent.mkdir(parents=True)
    with gzip.open(raw, "wb") as fh:
        for line in DUMP_LINES:
            fh.write(line + b"\n")
    assert k.main(["build", "--lang", "ga"]) == 0
    text = tmp_path / "t.txt"
    text.write_text(TEXT, encoding="utf-8")
    out = tmp_path / "c.tsv"
    assert k.main(["cards", "--lang", "ga", str(text), "--skip-top", "0", "--out", str(out),
                   "--tag", "book::niamh", "--tag", "ch01"]) == 0
    rows = out.read_text(encoding="utf-8").splitlines()
    assert rows and all(r.split("\t")[2] == "kaikki2card kaikki2card::ga book::niamh ch01" for r in rows)
    capsys.readouterr()
    assert k.main(["cards", "--lang", "ga", str(text), "--tag", "bad tag"]) == 2
    assert "invalid --tag" in capsys.readouterr().out


def test_anki_declined_adds_nothing(anki, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    k.add_cards_to_anki(CARDS, "ga", "Deck", "Basic", assume_yes=False)
    assert "addNote" not in anki.calls and "createDeck" not in anki.calls


# --------------------------------------------------------------------------
# End to end with a temp data dir: extract -> build -> lookup/resolve/cards
# --------------------------------------------------------------------------

def test_extract_build_and_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    raw = k.raw_path()
    raw.parent.mkdir(parents=True)
    with gzip.open(raw, "wb") as fh:
        for line in DUMP_LINES:
            fh.write(line + b"\n")

    assert k.main(["build", "--lang", "ga"]) == 0
    assert k.subset_path("ga").exists() and k.db_path().exists()
    assert "Built 'ga'" in capsys.readouterr().out

    assert k.main(["lookup", "--lang", "ga", "bhean"]) == 0
    assert "[exact+form_of] -> bean" in capsys.readouterr().out
    assert k.main(["lookup", "--lang", "ga", "zzzz"]) == 1

    text = tmp_path / "t.txt"
    text.write_text(TEXT, encoding="utf-8")
    assert k.main(["resolve", "--lang", "ga", str(text), "--out", str(tmp_path / "l.tsv")]) == 0
    assert (tmp_path / "l.tsv").read_text(encoding="utf-8").startswith("lemma\tcount\tforms")
    assert k.main(["cards", "--lang", "ga", str(text), "--skip-top", "0",
                   "--out", str(tmp_path / "c.tsv")]) == 0
    tsv = (tmp_path / "c.tsv").read_text(encoding="utf-8").splitlines()
    assert all(len(row.split("\t")) == 3 for row in tsv)


def test_data_dir_honours_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert k.data_dir() == tmp_path / "kaikki"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert k.data_dir() == Path.home() / ".local" / "share" / "kaikki"
