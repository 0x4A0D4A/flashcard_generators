"""
Per-language plug-ins for kaikki2card.

The core only needs one hook per language: given a surface token, return an
ordered list of candidate dictionary forms to try against the database. A
language without a plug-in just gets the token and its lowercase form, so
adding French or Japanese later means adding a function here and registering
it, not touching the core.
"""

import re
from typing import Callable, Dict, List

# Letters only (no digits/underscore), allowing internal apostrophes and
# hyphens so Irish "d'fhág", "n-athair" and French "l'eau" stay in one token.
TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)

# What a plug-in returns: candidates in priority order, best first.
CandidateFn = Callable[[str], List[str]]


def tokenize(text: str) -> List[str]:
    """Split text into word tokens"""
    return TOKEN_RE.findall(text)


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ============================================================================
# Default
# ============================================================================

def default_candidates(token: str) -> List[str]:
    """The token as written, then lowercased"""
    return _dedupe([token, token.lower()])


# ============================================================================
# Irish (Gaeilge)
# ============================================================================

IRISH_VOWELS = "aeiouáéíóúAEIOUÁÉÍÓÚ"
# Letters that can be lenited (a following 'h' marks the mutation)
IRISH_LENITABLE = "bcdfgmpstBCDFGMPSTbCDFGMPST"
# Eclipsis: written prefix -> restored initial
IRISH_ECLIPSIS = {
    "mb": "b", "gc": "c", "nd": "d", "bhf": "f", "ng": "g", "bp": "p", "dt": "t",
}
# Elided prefixes before verbs/vowels: d'fhág, m'athair, b'fhearr
IRISH_ELISIONS = ("d'", "d’", "m'", "m’", "b'", "b’")


def _irish_demutate(word: str) -> List[str]:
    """Undo lenition, eclipsis and h/n/t prefixes on the start of a word"""
    out = []
    low = word

    # Lenition: consonant + 'h' (bhean -> bean, shúil -> súil, ...)
    if len(low) > 2 and low[1] in "hH" and low[0] in IRISH_LENITABLE:
        out.append(low[0] + low[2:])

    # Eclipsis: mbád -> bád, gcat -> cat, ndoras -> doras, bhfear -> fear, ...
    for prefix, restored in IRISH_ECLIPSIS.items():
        if low.lower().startswith(prefix) and len(low) > len(prefix):
            out.append(restored + low[len(prefix):])

    # Prothesis before vowels: n-athair, nathair, t-athair, hathair, h-ainm
    for p in ("n-", "t-", "h-"):
        if low.lower().startswith(p) and len(low) > 2 and low[2] in IRISH_VOWELS:
            out.append(low[2:])
    if len(low) > 1 and low[0] in "nthNTH" and low[1] in IRISH_VOWELS:
        out.append(low[1:])
    # t- before s: tsúil -> súil (the "an tsúil" article)
    if len(low) > 2 and low[:2].lower() == "ts":
        out.append(low[1:])

    return out


def irish_candidates(token: str) -> List[str]:
    """Candidate dictionary forms for an Irish token, best first.

    The token itself and its lowercase form come first, so a form Wiktionary
    already knows (including mutated forms it lists) always wins over a
    rule-generated guess.
    """
    bases = default_candidates(token)
    out = list(bases)

    # Strip an elided d'/m'/b' first, then try demutation on the remainder
    stripped = []
    for base in bases:
        for elision in IRISH_ELISIONS:
            if base.lower().startswith(elision) and len(base) > len(elision):
                stripped.append(base[len(elision):])
    out.extend(stripped)

    for base in bases + stripped:
        out.extend(_irish_demutate(base))
        out.extend(c.lower() for c in _irish_demutate(base))
    out.extend(s.lower() for s in stripped)
    return _dedupe(out)


# ============================================================================
# Registry
# ============================================================================

LANGUAGES: Dict[str, CandidateFn] = {
    "ga": irish_candidates,
}


def get_candidates_fn(lang_code: str) -> CandidateFn:
    """The candidate generator for a language code (default for unknown ones)"""
    return LANGUAGES.get(lang_code, default_candidates)
