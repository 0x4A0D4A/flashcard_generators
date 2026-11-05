# kaikki2card

Build flashcards from a **local copy** of Wiktionary data instead of scraping
Wiktionary live (see [`../wikt2card`](../wikt2card/)). It downloads
[kaikki.org](https://kaikki.org/)'s pre-extracted English-Wiktionary dump once,
filters it by language into SQLite, and looks words up offline, so a whole
novel's vocabulary needs no API calls and no rate limiting.

**Status: prototype, Irish (`ga`) first.** The core is language-agnostic; a
language only needs an entry in `languages.py` to get its own spelling/mutation
rules. Planned languages: Irish, French, Japanese.

## Where data lives

`$XDG_DATA_HOME/kaikki` (default `~/.local/share/kaikki`), never in the repo and
never on `/tmp`:

| Path | What |
| --- | --- |
| `raw/raw-wiktextract-data.jsonl.gz` | the raw dump (3.08 GB), kept compressed |
| `raw/raw-wiktextract-data.meta.json` | URL, size, `Last-Modified`, fetch time |
| `<lang>.jsonl.gz` | one language cut out of the raw dump |
| `kaikki.sqlite` | the lookup database |

## Raw schema notes (observed on the 2026-10-30 extraction, Irish)

Observed by reading the real raw file, not the deprecated per-language
"postprocessed" files, which differ slightly.

- One JSON object per line. Top-level keys that matter: `word`, `pos`, `lang`,
  `lang_code`, `senses`, `forms`, `sounds`, `etymology_text`, `derived`,
  `related`, `synonyms`, `antonyms`. Everything else (`head_templates`,
  `etymology_templates`, `inflection_templates`, `categories`, ...) is dropped.
- An English word that merely *translates* into Irish contains the same
  `"lang_code": "ga"` text, so a substring match is not enough; the top-level
  `lang_code` has to be parsed.
- `senses[].glosses` is a list of strings. `senses[].form_of` / `alt_of` hold
  `[{"word": lemma}]`. About 20,000 of 52,091 Irish senses are form-of/alt-of
  stubs: mutated forms (`bhean` -> `bean`), verbal nouns (`dul` -> `téigh`),
  alternative spellings.
- `senses[].examples[]` has `text` and the translation under **both** `english`
  and `translation`. `type` is `example` (2,280), `quotation` (390) or absent
  (90); quotations are citations with references and are not used on cards.
- `sounds[]` has `ipa` with dialect `tags` (Munster, Galway, Cois-Fharraige,
  Mayo, Ulster). Audio (`audio`, `ogg_url`, `mp3_url`) exists on only 10 entries.
- `forms[]` is `{form, tags, source}` and is full of noise: table markers
  (`table-tags`, `inflection-template`), `error-unrecognized-form`, and
  multi-word phrases such as `an bhean`, `leis an mbean`, `tá mé`. Only
  single-word forms are usable for token lookup.
- A word can have several entries (`bean` is a noun and a pronoun; `bí` is a
  verb and a noun), so lookups return a list.
