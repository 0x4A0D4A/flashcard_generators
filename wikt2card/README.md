# wikt2card

Fetch Wiktionary entries and add them directly to your Anki collection.

## Features

- Fetches complete entries from English Wiktionary
- Extracts pronunciation (IPA), etymology, definitions, examples, synonyms, antonyms, and related terms
- Downloads and embeds audio pronunciation
- Shows a formatted preview before adding
- Checks for duplicates within the target deck
- Supports nested decks (e.g., "wikt2card French::Verbs")
- Configurable default decks per language

## Prerequisites

1. **Anki** - Install Anki desktop application
2. **AnkiConnect** - Install the AnkiConnect add-on:
   - In Anki: Tools → Add-ons → Get Add-ons
   - Enter code: `2055492159`
   - Restart Anki

## Installation

1. Install Python dependencies:
```bash
pip3 install -r requirements.txt
```

2. Make the script executable:
```bash
chmod +x wikt2card.py
```

3. (Optional) Add to your PATH:
```bash
# Add to ~/.bashrc or ~/.zshrc
alias wikt2card='/path/to/wikt2card.py'

# Or symlink it somewhere on your PATH
ln -s /path/to/wikt2card.py ~/.local/bin/wikt2card
```

## Usage

**Basic usage:**
```bash
./wikt2card.py french eau
```

**Specify a custom deck:**
```bash
./wikt2card.py spanish agua --deck "My Spanish Deck"
```

**Nested decks:**
```bash
./wikt2card.py french manger --deck "wikt2card French::Verbs"
```

**Multi-word language names:**
```bash
./wikt2card.py "old irish" <word>
```

**Skip the confirmation prompt:**
```bash
./wikt2card.py french eau --yes
```

**Use another note type** (it must have `Front` and `Back` fields):
```bash
./wikt2card.py french eau --note-type "Basic (and reversed card)"
```

**Show fetch/parse debug output:**
```bash
./wikt2card.py french eau --verbose
```

**Options:** `--deck NAME`, `--note-type NAME`, `-y/--yes`, `-v/--verbose`.

## Configuration

Default deck names can be configured in `~/.config/wikt2card/config.json`:

```json
{
  "defaults": {
    "french": "wikt2card French",
    "spanish": "Spanish Vocabulary",
    "german": "wikt2card German::Nouns"
  }
}
```

If no default is configured, the deck name will be `wikt2card <Language>`.

## Workflow

1. Run the command with a language and word
2. The script fetches the Wiktionary entry
3. A formatted preview is displayed in your terminal
4. You'll be prompted: "Add this card to Anki? (y/n)"
5. If you confirm, the card is added immediately
6. **Keep Anki running** while using this tool (AnkiConnect must be active)

## Card Format

Cards are tagged `wikt2card` and `wikt2card::<language>` (e.g. `wikt2card::french`).

**Front:** The word (with audio pronunciation if available)

**Back:** Complete entry including:
- Pronunciation (IPA)
- Etymology
- Definitions (organized by part of speech)
- Usage examples
- Synonyms and antonyms
- Derived and related terms

## Duplicate Detection

The script checks if a card with the same word already exists in the target deck before adding. It uses AnkiConnect's duplicate detection scoped to the specific deck (not checking child decks); the check and the final add use identical settings. The deck is only created once you confirm the card, so declining or a failed lookup leaves no empty deck behind.

## Tests

The tests run offline against saved Wiktionary pages and a fake AnkiConnect, so Anki does not need to be running:

```bash
pip3 install -r requirements-dev.txt
python3 -m pytest tests
```

## Supported Languages

Any language with entries on English Wiktionary, including:
- French, Spanish, German, Italian, Portuguese
- Russian, Polish, Czech
- Japanese, Chinese, Korean
- Arabic, Hebrew
- And many more!

## Requirements

- Python 3.7+
- Anki running with AnkiConnect add-on installed
- Internet connection (to fetch Wiktionary entries)

## Troubleshooting

**"Could not connect to AnkiConnect"**
- Make sure Anki is running
- Verify AnkiConnect add-on is installed (code: 2055492159)
- Check that nothing is blocking localhost:8765

**"Could not find [Language] section"**
- Verify the word exists on https://en.wiktionary.org/wiki/[word]
- Check that the language name is correct (use lowercase)
- Some words may only exist in English or other languages

**"Card already exists"**
- The word is already in the target deck
- You can manually delete it in Anki if you want to re-add it

## License

GPL-3.0 License
