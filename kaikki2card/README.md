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

## Usage

```bash
./kaikki2card.py fetch                     # 3.08 GB download, resumable, once
./kaikki2card.py build --lang ga           # cut Irish out of the dump, load SQLite
./kaikki2card.py lookup --lang ga bhean    # -> bean (lenited form of bean)
./kaikki2card.py resolve --lang ga novel.txt           # coverage report
./kaikki2card.py cards --lang ga novel.txt --out cards.tsv   # preview + TSV for Anki import
./kaikki2card.py cards --lang ga novel.txt --anki --deck "Irish::Niamh"   # via AnkiConnect
```

`build` reuses the cached `<lang>.jsonl.gz`; add `--refresh` to re-cut it from
a newer raw dump. `cards` skips proper nouns, the `--skip-top` most frequent
lemmas (default 100, mostly function words) and any lemma listed in a
`--known FILE`, and adds the first short sentence of the text that uses the
word. It makes a card for every remaining lemma seen at least `--min-count`
times (default 2; use `--min-count 1` for every word); `--limit N` caps the
list to the N most frequent. `--anki` reuses `../wikt2card`'s AnkiConnect helpers (so it needs
`pip install -r ../wikt2card/requirements.txt`) and skips cards already in the
deck. Nothing is written to Anki without `--anki`.

### One deck, one tag per book

Keep every book in a single deck and mark where each card came from with
`--tag` (repeatable; no whitespace; `a::b` makes a hierarchical tag):

```bash
./kaikki2card.py cards --lang ga niamh.txt --anki --deck "Irish::Mining" --tag book::niamh
./kaikki2card.py cards --lang ga ch03.txt  --anki --deck "Irish::Mining" --tag book::niamh --tag book::niamh::ch03
```

Cards also carry `kaikki2card` and `kaikki2card::<lang>`. A lemma that is
already in the deck is skipped and left untouched, so it does **not** gain a
later book's tag. To study one book, build a filtered deck in Anki with the
search `deck:"Irish::Mining" tag:book::niamh is:new`. `--out` writes the same
tags into the TSV's tag column.

Tests are offline: `python3 -m pytest tests` (needs pytest and, for the Anki
tests, `requests`/`beautifulsoup4`).

## Measured results (Irish, this laptop, 2026-11-05)

The research report estimated these; the right-hand column is what actually
happened. Raw file: Wiktionary dump of 2026-10-01, extracted 2026-10-30.

| Step | Report's estimate | Measured |
| --- | --- | --- |
| `fetch` (3,082,476,978 B) | n/a | ~7.6 min at ~6 MB/s; size matched exactly, `gzip -t` OK |
| `extract --lang ga` (11.1M lines, 26.6 GB uncompressed) | 15-40 min | **102 s**, 93 s CPU; 38,988 entries (matches the research count), 9.2 MB |
| `build --lang ga` | n/a | **3.5-4.6 s**; 183,324 forms |
| Irish database | 50-60 MB | **28.8 MB** |
| `resolve` a whole novel | seconds | **1.65 s** for 110,710 tokens / 7,038 distinct words |

Peak disk is the 3.08 GB download plus ~40 MB of derived data; the 26.6 GB
uncompressed file is never written out. No network access is needed after
`fetch`.

### Coverage on a real novel

Text: *Niamh* (Peter O'Leary, Project Gutenberg #50913, boilerplate removed;
early-20th-century Roman-script Irish).

| resolved by | distinct words | tokens |
| --- | --- | --- |
| headword (`exact`, incl. via a form-of stub) | 33.5% | 77.8% |
| mutation rules | 11.5% | 5.1% |
| inflected-forms table | 11.6% | 5.5% |
| **total resolved** | **56.6%** | **88.4%** |
| unresolved | 43.4% | 11.6% |

Note that "resolved" means *an entry was found*, not that it is the right
word. A spot check of ~30 random resolutions found most correct (`mhór`->`mór`,
`cia`->`cé`, `chonacadar`->`feic`, `marbhófá`->`maraigh`, `gcreideamh`->`creideamh`)
but ~700 words have more than one candidate lemma and the tool just takes the
first, so some picks are wrong or merely plausible (`bhean`->`bean`/`bain`,
`h-iasachtaí`->`iasachtaí`).

## Known gaps

- **Old orthography and names dominate what is unresolved.** The most frequent
  misses are names (Murchadh, Gormfhlaith, Sitric, Lochlanach), archaic
  spellings (`árdrígh`, `beannuighthe`, `ímpídhe`, `n-oídhche`, `dúbhairt`,
  `éirean` for `Éireann`) and clitic contractions (`arsa’n`, `do’n`, `a’s`).
  A normaliser for pre-standard spelling and an apostrophe-clitic splitter
  would be the next language rules; no Wiktionary data fixes these.
- **No part-of-speech disambiguation.** The first candidate lemma wins. The
  research recommends a tagger (Stanza, 95.3 lemma accuracy for Irish on
  treebank text, lower on literary Irish) to choose between candidates;
  it has not been tried.
- **Irish has almost no audio or examples in Wiktionary**: audio on 10 entries,
  about 2,300 real examples. Cards carry the in-text sentence instead. French is
  much better covered (about 23% of entries have a recording).
- **Audio is streamed, not stored.** The database only holds *links* to the
  recordings on Wikimedia Commons. A card whose lemma has a recording gets an
  autoplaying `<audio>` element (mp3 first, ogg as fallback) at the top of its
  Back field, so the client fetches the file when the card is shown, one file
  per review. Nothing is downloaded when cards are made, nothing is stored in
  the collection, and with no connection the player stays silent. Autoplay
  depends on the Anki client; `controls` gives a play button when it is
  blocked. AnkiConnect is deliberately not asked to download the files:
  Commons answers its generic User-Agent with 403. Cards already in the deck
  are skipped, so they do not gain audio retroactively. `cards` marks cards
  that have a recording with `[audio]` in the preview; `--out` TSVs carry the
  element in the Back column.
- Etymology and some `forms` still contain template residue after cleaning
  (only the leading `X word\n form` header is stripped).
- `--anki` is covered by tests against a fake AnkiConnect but has **not been run
  against a real Anki** (Anki was not running when this was built).

## Extending to French and Japanese

`--lang fr` / `--lang ja` already work for `extract`, `build` and `lookup`: the
core never mentions Irish. A language only needs an entry in `languages.py`
(`LANGUAGES = {"ga": irish_candidates}`):

- **French:** add a candidate function for elisions (`l'eau`, `qu'il`) and, in
  practice, a lemmatizer, since Wiktionary's `forms` table covers inflections
  but not homographs (`est`, `sont`).
- **Japanese:** `languages.tokenize` splits on letters and cannot segment
  Japanese; it needs a morphological analyser (e.g. SudachiPy or Stanza) behind
  the same `tokenize`/`candidates` hooks.

The database is one file for all languages (`lang` column), and `build --lang`
replaces only that language's rows. French will be larger than Irish (the
English-edition French file is ~5x Irish's size postprocessed: 566 MiB vs
107 MiB, per the research report), but the same streaming pass applies.
