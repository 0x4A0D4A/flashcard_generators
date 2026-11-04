#!/usr/bin/env python3
"""
wikt2card - Fetch Wiktionary entries and add them directly to Anki

Usage:
    wikt2card <language> <word> [--deck DECK_NAME]

Examples:
    wikt2card french eau
    wikt2card spanish agua --deck "My Spanish Deck"
"""

import sys
import json
import re
import argparse
import copy
import logging
import requests
from html import escape as html_escape
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from bs4 import BeautifulSoup
from typing import Optional, Dict, List, Tuple

log = logging.getLogger('wikt2card')


# ============================================================================
# Configuration Management
# ============================================================================

CONFIG_DIR = Path.home() / ".config" / "wikt2card"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> Dict:
    """Load configuration from ~/.config/wikt2card/config.json"""
    if not CONFIG_FILE.exists():
        return {"defaults": {}}
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load config file: {e}")
        return {"defaults": {}}



def get_deck_name(language: str, deck_override: Optional[str] = None) -> str:
    """Get the deck name for a language, respecting config and overrides"""
    if deck_override:
        return deck_override
    
    config = load_config()
    if language.lower() in config.get("defaults", {}):
        return config["defaults"][language.lower()]
    
    # Default: "wikt2card <Language>" with capitalized language
    return f"wikt2card {language_title(language)}"


# ============================================================================
# AnkiConnect Interface
# ============================================================================

ANKI_CONNECT_URL = "http://localhost:8765"
REQUEST_TIMEOUT = 30  # seconds

SESSION = requests.Session()
SESSION.headers["User-Agent"] = (
    "wikt2card/1.0 (https://github.com/0x4A0D4A/flashcard_generators)"
)


class AnkiError(Exception):
    """Raised when AnkiConnect cannot be reached or reports an error"""


def invoke_anki(action: str, **params) -> Dict:
    """Send a request to AnkiConnect"""
    payload = {
        "action": action,
        "version": 6,
        "params": params
    }

    try:
        response = SESSION.post(ANKI_CONNECT_URL, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.ConnectionError:
        raise AnkiError(
            "Could not connect to AnkiConnect. Is Anki running, and is the "
            "AnkiConnect add-on installed?"
        )
    except (requests.exceptions.RequestException, ValueError) as e:
        raise AnkiError(f"Error communicating with Anki: {e}")

    if len(result) != 2:
        raise AnkiError("AnkiConnect response has unexpected number of fields")
    if "error" not in result:
        raise AnkiError("AnkiConnect response is missing required error field")
    if "result" not in result:
        raise AnkiError("AnkiConnect response is missing required result field")
    if result["error"] is not None:
        raise AnkiError(result["error"])

    return result["result"]


def check_anki_connection():
    """Verify that AnkiConnect is available"""
    version = invoke_anki("version")
    if version < 6:
        print(f"Warning: AnkiConnect version {version} may not be supported")


def deck_exists(deck_name: str) -> bool:
    """Check whether a deck already exists"""
    return deck_name in invoke_anki("deckNames")


def create_deck_if_needed(deck_name: str):
    """Create the deck if it doesn't exist"""
    invoke_anki("createDeck", deck=deck_name)


def audio_filename(audio_url: str) -> str:
    """Derive a safe, collision-resistant media filename from an audio URL.

    Wikimedia file names already encode the language and word (e.g.
    Fr-eau.ogg.mp3), and keeping them preserves the real extension.
    """
    base = unquote(urlparse(audio_url).path.rsplit('/', 1)[-1])
    base = re.sub(r'[^\w.\-]', '_', base) or 'audio'
    return f"wikt2card_{base}"


def build_note(deck_name: str, word: str, details: str, audio_url: Optional[str] = None) -> Dict:
    """Build the AnkiConnect note payload.

    Used for both the duplicate check and the actual add, so that both use
    the same duplicate scope (the target deck, excluding child decks).
    """
    note = {
        "deckName": deck_name,
        "modelName": "Basic",
        "fields": {
            "Front": word,
            "Back": details
        },
        "options": {
            "allowDuplicate": False,
            "duplicateScope": "deck",
            "duplicateScopeOptions": {
                "deckName": deck_name,
                "checkChildren": False
            }
        },
        "tags": ["wikt2card"]
    }

    # Add audio if available
    if audio_url:
        note["audio"] = [{
            "url": audio_url,
            "filename": audio_filename(audio_url),
            "fields": ["Front"]
        }]

    return note


def can_add_note(note: Dict) -> bool:
    """Check if a note can be added (i.e., not a duplicate)"""
    result = invoke_anki("canAddNotesWithErrorDetail", notes=[note])

    # result is a list with one element per note
    if result and len(result) > 0:
        return result[0].get("canAdd", False)

    return False


def add_note_to_anki(note: Dict):
    """Add a note to Anki"""
    return invoke_anki("addNote", note=note)


# ============================================================================
# Wiktionary Fetching and Parsing
# ============================================================================

class WiktError(Exception):
    """Raised when a Wiktionary entry cannot be fetched or parsed"""


def language_title(language: str) -> str:
    """Title-case every word of a language name ('old irish' -> 'Old Irish')"""
    return ' '.join(part.capitalize() for part in language.split())


def language_heading_id(language: str) -> str:
    """The h2 id Wiktionary uses for a language ('old irish' -> 'Old_Irish')"""
    return language_title(language).replace(' ', '_')


def fetch_wiktionary_entry(word: str) -> str:
    """Fetch the HTML content from Wiktionary"""
    url = f"https://en.wiktionary.org/wiki/{quote(word.replace(' ', '_'), safe='')}"
    
    log.debug(f"\n=== FETCHING FROM WIKTIONARY ===")
    log.debug(f"URL: {url}")
    
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        log.debug(f"Status: {response.status_code}")
        log.debug(f"Content length: {len(response.text)} bytes")
        log.debug(f"Content type: {response.headers.get('content-type', 'unknown')}")
        
        return response.text
    except requests.exceptions.RequestException as e:
        raise WiktError(f"Error fetching Wiktionary entry: {e}")


def extract_audio_url(soup: BeautifulSoup, language_section) -> Optional[str]:
    """Extract the audio file URL from the pronunciation section"""
    log.debug(f"\n=== EXTRACTING AUDIO ===")
    
    # The language_section is the h2 tag, we need to start from its parent div
    if language_section.parent and language_section.parent.name == 'div' and \
       'mw-heading' in language_section.parent.get('class', []):
        start_element = language_section.parent
    else:
        start_element = language_section
    
    # Find pronunciation section within the language section
    current = start_element.find_next_sibling()
    
    while current:
        # Stop at next language section
        if current.name == 'h2':
            break
        if current.name == 'div' and 'mw-heading' in current.get('class', []):
            if current.find('h2'):
                break
        
        # Look for pronunciation heading - might be wrapped in div.mw-heading
        heading_elem = None
        if current.name == 'div' and 'mw-heading' in current.get('class', []):
            heading_elem = current.find(['h3', 'h4'])
        
        if heading_elem:
            heading_text = heading_elem.get_text().strip()
            log.debug(f"Checking section: {heading_text}")
            
            if 'pronunciation' in heading_text.lower():
                log.debug(f"Found pronunciation section!")
                # Found pronunciation section, look for audio in subsequent siblings
                audio_section = current.find_next_sibling()
                while audio_section:
                    # Stop at next section heading
                    if audio_section.name == 'div' and 'mw-heading' in audio_section.get('class', []):
                        break
                    
                    # Look for audio elements
                    log.debug(f"  Searching in: {audio_section.name}")
                    audio_elements = audio_section.find_all('audio')
                    for audio in audio_elements:
                        log.debug(f"    Found audio tag: {audio}")
                        sources = audio.find_all('source')
                        for source in sources:
                            src = source.get('src')
                            log.debug(f"      Source: {src}")
                            if src:
                                # Prefer mp3, then ogg
                                if '.mp3' in src or '.ogg' in src:
                                    if src.startswith('//'):
                                        url = 'https:' + src
                                    elif src.startswith('/'):
                                        url = 'https://en.wiktionary.org' + src
                                    else:
                                        url = src
                                    log.debug(f"      -> Using: {url}")
                                    return url
                    
                    audio_section = audio_section.find_next_sibling()
                break
        
        current = current.find_next_sibling()
    
    log.debug(f"No audio found")
    return None


NYM_SECTIONS = {
    'synonyms': 'synonyms',
    'antonyms': 'antonyms',
    'derived': 'derived terms',
    'related': 'related terms',
}


def clean_text(text: str) -> str:
    """Collapse whitespace, including the stray spaces left around inline markup"""
    text = ' '.join(text.split())
    return re.sub(r'\s+([,.;:!?)])', r'\1', re.sub(r'\(\s+', '(', text))


def format_ipa(ipa) -> str:
    """Return an IPA string, labelled with its dialect/qualifier if present.

    Rhyme lines (which also use the IPA class) are skipped.
    """
    li = ipa.find_parent('li')
    if li is not None:
        if clean_text(li.get_text()).lower().startswith('rhymes'):
            return ''
        labels = []
        for q in li.find_all('span', class_='ib-content'):
            if q.find_parent('li') is li:
                labels.append(clean_text(q.get_text()))
        label = ', '.join(labels)
        if label:
            return f"{label}: {clean_text(ipa.get_text())}"
    return clean_text(ipa.get_text())


def parse_sense(li) -> Dict:
    """Parse one definition <li>: its text, usage examples and sub-senses"""
    own = copy.copy(li)
    for nested in own.find_all(['ol', 'ul', 'dl']):
        nested.decompose()
    
    examples = []
    for div in li.select('div.h-usage-example'):
        if div.find_parent('li') is not li:
            continue  # belongs to a nested sub-sense
        ex = div.find('i', class_='e-example')
        if ex is None:
            continue
        text = clean_text(ex.get_text())
        tr = div.find('span', class_='e-translation')
        if tr is not None:
            text += f" \u2014 {clean_text(tr.get_text())}"
        if text and text not in examples:
            examples.append(text)
    
    subsenses = []
    for sub_ol in li.find_all('ol', recursive=False):
        for sub_li in sub_ol.find_all('li', recursive=False):
            sub = parse_sense(sub_li)
            if sub['text']:
                subsenses.append(sub)
    
    return {'text': clean_text(own.get_text()), 'examples': examples, 'subsenses': subsenses}


def extract_term_links(elem) -> List[str]:
    """Collect term names from the links in a nyms/derived/related section"""
    terms = []
    for link in elem.find_all('a', href=True):
        if link.find_parent('span', class_='mw-editsection'):
            continue
        text = clean_text(link.get_text())
        if text and not text.startswith('Thesaurus:') and text != 'edit':
            terms.append(text)
    return terms


def parse_wiktionary_entry(html: str, language: str, word: str) -> Tuple[Dict, Optional[str]]:
    """
    Parse the Wiktionary HTML and extract all content for the specified language.
    Returns a tuple of (info_dict, audio_url)
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    log.debug(f"\n=== PARSING WIKTIONARY ENTRY ===")
    log.debug(f"Word: {word}")
    log.debug(f"Language: {language}")
    
    # Find all h2 headings
    all_h2s = soup.find_all('h2')
    log.debug(f"\nFound {len(all_h2s)} h2 headings:")
    for i, h2 in enumerate(all_h2s[:10]):  # Show first 10
        h2_id = h2.get('id', 'no-id')
        h2_text = h2.get_text().strip()
        log.debug(f"  {i+1}. id='{h2_id}' text='{h2_text}'")
    
    # Find the language heading by ID attribute
    heading_id = language_heading_id(language)
    language_heading = soup.find('h2', id=heading_id)

    if not language_heading:
        # Fallback: try finding by text content
        log.debug(f"\nCouldn't find h2 with id='{heading_id}', trying text match...")
        for h2 in all_h2s:
            if h2.get_text().strip().lower() == language.lower():
                language_heading = h2
                log.debug(f"Found by text: {h2}")
                break
    
    if not language_heading:
        available = [h2.get('id') for h2 in all_h2s if h2.get('id')]
        raise WiktError(
            f"Could not find a {language_title(language)} section for '{word}'. "
            f"Available language sections: {available}. "
            f"Check https://en.wiktionary.org/wiki/{quote(word.replace(' ', '_'), safe='')}"
        )
    
    log.debug(f"\nFound language section: {language_heading}")
    
    # Extract audio URL
    audio_url = extract_audio_url(soup, language_heading)
    log.debug(f"Audio URL: {audio_url}")
    
    # The h2 might be wrapped in a div.mw-heading, so start from the right place
    if language_heading.parent and language_heading.parent.name == 'div' and \
       'mw-heading' in language_heading.parent.get('class', []):
        # Start from the wrapper div's next sibling
        start_element = language_heading.parent
        log.debug(f"H2 is wrapped in div.mw-heading, starting from: {start_element.name}")
    else:
        # Start from the h2 itself
        start_element = language_heading
        log.debug(f"H2 is not wrapped, starting from: {start_element.name}")
    
    # Find all sibling elements until next h2
    content_elements = []
    current = start_element.find_next_sibling()
    
    log.debug(f"\nCollecting content elements...")
    while current:
        # Stop if we hit another language section (h2 or div containing h2)
        if current.name == 'h2':
            log.debug(f"Stopped at next h2: {current.get('id')}")
            break
        if current.name == 'div' and 'mw-heading' in current.get('class', []):
            if current.find('h2'):
                log.debug(f"Stopped at div containing h2: {current.find('h2').get('id')}")
                break
        
        content_elements.append(current)
        if current.name == 'div' and 'mw-heading' in current.get('class', []):
            inner = current.find(['h3', 'h4'])
            if inner:
                log.debug(f"  Found section: {inner.get_text().strip()}")
        current = current.find_next_sibling()
    
    log.debug(f"Collected {len(content_elements)} elements")
    
    # Extract structured information
    info = {
        'word': word,
        'language': language,
        'pronunciation': [],
        'etymology': [],
        'definitions': {},
        'synonyms': [],
        'antonyms': [],
        'related': [],
        'derived': [],
    }
    
    current_section = ''
    current_pos = None
    
    log.debug(f"\nParsing content...")
    for i, elem in enumerate(content_elements):
        # Check if this is a section heading (wrapped in div.mw-heading)
        if elem.name == 'div' and 'mw-heading' in elem.get('class', []):
            heading = elem.find(['h3', 'h4', 'h5'])
            if heading:
                section_title = heading.get_text().strip()
                current_section = section_title.lower()
                log.debug(f"  Section {i}: {section_title}")
                
                # Check if this is a part of speech heading
                pos_keywords = ['noun', 'verb', 'adjective', 'adverb', 'pronoun', 
                               'preposition', 'conjunction', 'interjection', 'article',
                               'participle', 'phrase', 'proverb']
                if any(pos in current_section for pos in pos_keywords):
                    current_pos = section_title
                    if current_pos not in info['definitions']:
                        info['definitions'][current_pos] = []
        
        # Extract pronunciation
        if current_section == 'pronunciation' or current_section.startswith('pronunciation '):
            for ipa in elem.find_all('span', class_='IPA'):
                entry = format_ipa(ipa)
                if entry and entry not in info['pronunciation']:
                    info['pronunciation'].append(entry)
        
        # Extract etymology
        if current_section.startswith('etymology'):
            if elem.name == 'p':
                text = clean_text(re.sub(r'\[\d+\]', '', elem.get_text()))  # drop footnote markers
                if text and text not in info['etymology']:
                    info['etymology'].append(text)
        
        # Extract definitions from ordered lists
        if elem.name == 'ol' and current_pos:
            for li in elem.find_all('li', recursive=False):
                sense = parse_sense(li)
                if sense['text']:
                    info['definitions'][current_pos].append(sense)
                # Synonyms/antonyms are often listed inline under each sense
                for key, css in (('synonyms', 'synonym'), ('antonyms', 'antonym')):
                    for span in li.select(f'span.nyms.{css}'):
                        for text in extract_term_links(span):
                            if text not in info[key]:
                                info[key].append(text)
        
        # Extract synonyms, antonyms, derived and related terms
        for key, prefix in NYM_SECTIONS.items():
            if current_section.startswith(prefix):
                for text in extract_term_links(elem):
                    if text not in info[key]:
                        info[key].append(text)
    
    log.debug(f"\n=== PARSING SUMMARY ===")
    log.debug(f"Pronunciation entries: {len(info['pronunciation'])}")
    log.debug(f"Etymology entries: {len(info['etymology'])}")
    log.debug(f"Definitions by POS:")
    for pos, defs in info['definitions'].items():
        log.debug(f"  {pos}: {len(defs)} definition(s)")
        for j, d in enumerate(defs[:2]):  # Show first 2
            if isinstance(d, dict):
                log.debug(f"    {j+1}. {d['text'][:60]}...")
            else:
                log.debug(f"    {j+1}. {d[:60]}...")
    log.debug(f"Synonyms: {len(info['synonyms'])}")
    log.debug(f"Antonyms: {len(info['antonyms'])}")
    log.debug(f"Derived terms: {len(info['derived'])}")
    log.debug(f"Related terms: {len(info['related'])}")
    
    return info, audio_url


# ============================================================================
# Console Display
# ============================================================================

def format_for_display(info: Dict) -> str:
    """Format the parsed information for console display"""
    lines = []
    lines.append("=" * 70)
    lines.append(f"WORD: {info['word']}")
    lines.append(f"LANGUAGE: {language_title(info['language'])}")
    lines.append("=" * 70)
    lines.append("")
    
    # Pronunciation
    if info['pronunciation']:
        lines.append("PRONUNCIATION:")
        for pron in info['pronunciation']:
            lines.append(f"  {pron}")
        lines.append("")
    
    # Etymology
    if info['etymology']:
        lines.append("ETYMOLOGY:")
        for etym in info['etymology']:
            # Word wrap at 68 characters
            words = etym.split()
            current_line = "  "
            for word in words:
                if len(current_line) + len(word) + 1 > 68:
                    lines.append(current_line)
                    current_line = "  " + word
                else:
                    current_line += (" " if current_line != "  " else "") + word
            if current_line != "  ":
                lines.append(current_line)
        lines.append("")
    
    # Definitions by part of speech
    if info['definitions']:
        lines.append("DEFINITIONS:")
        for pos, defs in info['definitions'].items():
            lines.append(f"\n  {pos}:")
            for i, defn in enumerate(defs, 1):
                lines.append(f"    {i}. {defn['text']}")
                for example in defn['examples']:
                    lines.append(f"       • {example}")
                for j, sub in enumerate(defn.get('subsenses', []), 1):
                    lines.append(f"       {i}.{j}. {sub['text']}")
                    for example in sub['examples']:
                        lines.append(f"          • {example}")
        lines.append("")
    
    # Synonyms
    if info['synonyms']:
        syn_text = ', '.join(info['synonyms'][:15])  # Limit to first 15
        lines.append(f"SYNONYMS: {syn_text}")
        if len(info['synonyms']) > 15:
            lines.append(f"  ... and {len(info['synonyms']) - 15} more")
        lines.append("")
    
    # Antonyms
    if info['antonyms']:
        ant_text = ', '.join(info['antonyms'][:15])
        lines.append(f"ANTONYMS: {ant_text}")
        if len(info['antonyms']) > 15:
            lines.append(f"  ... and {len(info['antonyms']) - 15} more")
        lines.append("")
    
    # Derived terms
    if info['derived']:
        der_text = ', '.join(info['derived'][:10])
        lines.append(f"DERIVED TERMS: {der_text}")
        if len(info['derived']) > 10:
            lines.append(f"  ... and {len(info['derived']) - 10} more")
        lines.append("")
    
    # Related terms
    if info['related']:
        rel_text = ', '.join(info['related'][:10])
        lines.append(f"RELATED TERMS: {rel_text}")
        if len(info['related']) > 10:
            lines.append(f"  ... and {len(info['related']) - 10} more")
        lines.append("")
    
    lines.append("=" * 70)
    return "\n".join(lines)


def sense_to_html(sense: Dict) -> str:
    """Render one definition (with examples and sub-senses) as an HTML <li>"""
    parts = [f"<li>{html_escape(sense['text'])}"]
    if sense['examples']:
        parts.append("<ul style='margin-top: 5px; margin-bottom: 5px;'>")
        for example in sense['examples']:
            parts.append(f"<li><em>{html_escape(example)}</em></li>")
        parts.append("</ul>")
    if sense.get('subsenses'):
        parts.append("<ol type='a'>")
        parts.extend(sense_to_html(sub) for sub in sense['subsenses'])
        parts.append("</ol>")
    parts.append("</li>")
    return ''.join(parts)


def format_for_anki(info: Dict) -> str:
    """Format the parsed information as HTML for the Anki card back"""
    # All scraped text is escaped: it ends up inside HTML in the Anki field
    esc = html_escape
    html_parts = []

    # Pronunciation
    if info['pronunciation']:
        pron = ', '.join(esc(p) for p in info['pronunciation'])
        html_parts.append(f"<p><strong>Pronunciation:</strong> {pron}</p>")

    # Etymology
    if info['etymology']:
        etym = esc(' '.join(info['etymology']))
        html_parts.append(f"<p><strong>Etymology:</strong> {etym}</p>")

    # Definitions by part of speech
    if info['definitions']:
        for pos, defs in info['definitions'].items():
            html_parts.append(f"<p><strong>{esc(pos)}:</strong></p>")
            html_parts.append("<ol>")
            for defn in defs:
                html_parts.append(sense_to_html(defn))
            html_parts.append("</ol>")

    # Synonyms, antonyms, derived and related terms
    for label, key, limit in (
        ("Synonyms", 'synonyms', 15),
        ("Antonyms", 'antonyms', 15),
        ("Derived terms", 'derived', 10),
        ("Related terms", 'related', 10),
    ):
        items = info[key]
        if items:
            text = ', '.join(esc(i) for i in items[:limit])
            html_parts.append(f"<p><strong>{label}:</strong> {text}")
            if len(items) > limit:
                html_parts.append(f" <em>(+{len(items) - limit} more)</em>")
            html_parts.append("</p>")

    return '\n'.join(html_parts)


# ============================================================================
# Main CLI Logic
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Fetch Wiktionary entries and add them to Anki',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  wikt2card french eau
  wikt2card spanish agua --deck "My Spanish Deck"
        """
    )
    
    parser.add_argument('language', help='Language of the word (e.g., french, spanish)')
    parser.add_argument('word', help='Word to look up')
    parser.add_argument('--deck', help='Override the deck name')
    
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show detailed fetch/parse debug output')

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format='%(message)s'
    )

    try:
        run(args)
    except (AnkiError, WiktError) as e:
        print(f"Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)


def run(args):
    """Fetch, preview and (on confirmation) add a card"""
    language = args.language.lower()
    word = args.word
    deck_name = get_deck_name(language, args.deck)
    
    print(f"Fetching Wiktionary entry for '{word}' ({language})...")
    
    # Check AnkiConnect
    check_anki_connection()
    
    # Fetch and parse
    html = fetch_wiktionary_entry(word)
    info, audio_url = parse_wiktionary_entry(html, language, word)
    
    if not info['definitions']:
        print(f"Warning: No definitions found for {language} '{word}'")
        print("The card will be created but may be incomplete.")
    
    # Format for Anki
    anki_details = format_for_anki(info)
    
    # Check for duplicates (a deck that doesn't exist yet can't contain any)
    print(f"\nChecking for duplicates in deck '{deck_name}'...")
    note = build_note(deck_name, word, anki_details, audio_url)
    if deck_exists(deck_name) and not can_add_note(note):
        print(f"Error: Card for '{word}' already exists in deck '{deck_name}'")
        sys.exit(1)
    
    # Display preview
    print("\n" + format_for_display(info))
    
    if audio_url:
        print(f"\n[Audio available: {audio_url}]")
    
    # Prompt for confirmation
    print(f"\nTarget deck: {deck_name}")
    response = input("\nAdd this card to Anki? (y/n): ").strip().lower()
    
    if response == 'y' or response == 'yes':
        print("\nAdding card to Anki...")
        create_deck_if_needed(deck_name)
        note_id = add_note_to_anki(note)
        print(f"✓ Card added successfully! (Note ID: {note_id})")
    else:
        print("Card not added.")


if __name__ == '__main__':
    main()
