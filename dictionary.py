import json
import logging
import os
import urllib.request
import re

logger = logging.getLogger(__name__)

CEDICT_URL = "https://raw.githubusercontent.com/spamscanner/spamscanner/master/cedict_1_0_ts_utf-8_mdbg.txt"

# Tone mark mapping for Pinyin conversion
PINYIN_TONE_MAP = {
    'a': 'āáǎàa',
    'e': 'ēéěèe',
    'i': 'īíǐìi',
    'o': 'ōóǒòo',
    'u': 'ūúǔùu',
    'v': 'ǖǘǚǜü',
    'ü': 'ǖǘǚǜü'
}

def convert_pinyin_syllable(syllable: str) -> str:
    """Converts a single numbered pinyin syllable (e.g., 'hao3') to tone marks."""
    syllable = syllable.lower().replace('u:', 'v') # Handle u-umlaut representation
    
    # If no tone number at the end, return as-is
    if not syllable[-1].isdigit():
        return syllable
        
    tone = int(syllable[-1])
    word = syllable[:-1]
    
    if tone < 1 or tone > 5:
        return word

    # Tone placement rules:
    # 1. If there's an 'a' or 'e', it takes the tone mark.
    # 2. In 'ou', 'o' takes the tone mark.
    # 3. Otherwise, the last vowel takes the tone mark.
    pos = -1
    if 'a' in word:
        pos = word.find('a')
    elif 'e' in word:
        pos = word.find('e')
    elif 'ou' in word:
        pos = word.find('o')
    else:
        # Find the last vowel
        for i in range(len(word) - 1, -1, -1):
            if word[i] in 'eiouvü':
                pos = i
                break
                
    if pos != -1 and tone != 5:
        char = word[pos]
        # Map tone (1-4) to unicode characters (0-indexed in mapping string)
        replacement = PINYIN_TONE_MAP[char][tone - 1]
        word = word[:pos] + replacement + word[pos + 1:]
        
    # Replace any remaining raw 'v' with 'ü'
    return word.replace('v', 'ü')

def convert_pinyin_sentence(pinyin_str: str) -> str:
    """Converts an entire pinyin string (e.g., 'ni3 hao3') to tone marks."""
    # Split by spaces, convert each part, and join back
    parts = pinyin_str.split(' ')
    converted = [convert_pinyin_syllable(part) for part in parts]
    return " ".join(converted)


class ChineseDictionary:
    def __init__(self):
        self.by_simplified = {}
        self.by_traditional = {}
        self.by_pinyin = {}

    def _parse_cedict(self, lines) -> None:
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r'^(\S+)\s+(\S+)\s+\[(.*?)\]\s+/(.*)/$', line)
            if not match:
                continue
            trad, simp, pinyin_raw, defs_raw = match.groups()
            raw_definitions = [d.strip() for d in defs_raw.split('/') if d.strip()]
            definitions = []
            measure_words = []
            variants = []
            for d in raw_definitions:
                if d.startswith("CL:"):
                    classifiers = d[3:].split(',')
                    for cl in classifiers:
                        cl_match = re.match(r'([^\[]+)(?:\[(.*?)\])?', cl)
                        if cl_match:
                            chars, pin = cl_match.groups()
                            if pin:
                                measure_words.append(f"{chars} (`{convert_pinyin_sentence(pin)}`)")
                            else:
                                measure_words.append(chars)
                    continue
                if "variant of" in d or "old variant of" in d:
                    variants.append(d)
                    continue
                d = d.replace("fig.", "*fig.*").replace("lit.", "*lit.*")
                definitions.append(d)
            entry = {
                "traditional": trad,
                "simplified": simp,
                "pinyin_raw": pinyin_raw,
                "pinyin": convert_pinyin_sentence(pinyin_raw),
                "definitions": definitions,
                "measure_words": measure_words,
                "variants": variants
            }
            self.by_simplified[simp] = entry
            self.by_traditional[trad] = entry
            self.by_pinyin[pinyin_raw.lower().replace(" ", "")] = entry
            self.by_pinyin[entry["pinyin"].lower().replace(" ", "")] = entry
        logger.info("Loaded %d entries into memory!", len(self.by_simplified))

    def load_dictionary(self, cache_path: str | None = None) -> None:
        if cache_path and os.path.exists(cache_path):
            logger.info("Loading CEDICT from disk cache: %s", cache_path)
            with open(cache_path, "r", encoding="utf-8") as f:
                self._parse_cedict(f)
            return

        logger.info("Starting dictionary download from GitHub mirror...")
        req = urllib.request.Request(CEDICT_URL, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
            if cache_path:
                cache_dir = os.path.dirname(cache_path)
                if cache_dir:
                    os.makedirs(cache_dir, exist_ok=True)
                with open(cache_path, "wb") as f:
                    f.write(raw)
                logger.info("Saved CEDICT cache to %s (%d bytes)", cache_path, len(raw))
            self._parse_cedict(raw.decode("utf-8").splitlines())
        except Exception as e:
            logger.error("Failed to download or parse the dictionary: %s", e)

    def search(self, query: str):
        query_clean = query.strip()
        
        # 1. Search by Simplified
        if query_clean in self.by_simplified:
            return self.by_simplified[query_clean]
            
        # 2. Search by Traditional
        if query_clean in self.by_traditional:
            return self.by_traditional[query_clean]
            
        # 3. Search by Pinyin
        pinyin_query = query_clean.lower().replace(" ", "")
        if pinyin_query in self.by_pinyin:
            return self.by_pinyin[pinyin_query]
            
        # 4. Fallback: Search by English Definition with Relevance Sorting
        english_query = query_clean.lower()
        matches = []
        
        # 1. Collect ALL potential matches first
        for simp, entry in self.by_simplified.items():
            for definition in entry["definitions"]:
                def_lower = definition.lower()
                
                # Check for word boundaries to avoid 'cat' matching 'catastrophe'
                if re.search(r'\b' + re.escape(english_query) + r'\b', def_lower):
                    # Store metadata for sorting
                    matches.append({
                        'entry': entry,
                        'is_exact': english_query == def_lower,
                        'position': def_lower.find(english_query),
                        'def_length': len(definition),
                        'char_length': len(simp)
                    })
                    break 

        if not matches:
            return None

        # 2. Sort the matches based on your new relevance rules
        matches.sort(key=lambda x: (
            not x['is_exact'],   # Exact matches first
            x['position'],       # Keyword at the start of the definition first
            x['def_length'],     # Shorter/simpler definitions first
            x['char_length']     # Shorter Chinese words (common vocabulary) first
        ))

        # 3. Extract just the entry data for the top 5
        top_results = [m['entry'] for m in matches[:5]]

        # 4. Return as single result or list for the main.py handler
        if len(top_results) == 1:
            return top_results
        return top_results

        return None


XINHUA_BASE_URL = "https://raw.githubusercontent.com/pwxcoo/chinese-xinhua/master/data/"
XINHUA_FILES = [
    ("idiom.json", "idiom"),
    ("word.json", "word"),
    ("ci.json", "ci"),
    ("xiehouyu.json", "xiehouyu"),
]


class XinhuaDictionary:
    """Fallback Chinese dictionary sourced from pwxcoo/chinese-xinhua.

    Downloads the four dataset files on first run and caches them to disk
    under ``data_dir`` (default: ``data/``).  Subsequent startups load from
    disk without hitting the network.

    ``search(query)`` returns ``(kind, entry)`` or ``None``:
      - kind ``"idiom"``    – entry has keys: word, pinyin, explanation, derivation, example, abbreviation
      - kind ``"word"``     – entry has keys: word, oldword, strokes, pinyin, radicals, explanation, more
      - kind ``"ci"``       – entry has keys: ci, explanation
      - kind ``"xiehouyu"`` – entry has keys: riddle, answer
    """

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or os.getenv("XINHUA_DATA_DIR", "data")
        self.idioms: dict[str, dict] = {}
        self.words: dict[str, dict] = {}
        self.ci: dict[str, dict] = {}
        self.xiehouyu: dict[str, dict] = {}

    def _cache_path(self, filename: str) -> str:
        return os.path.join(self.data_dir, filename)

    def to_chengyu_entry(self, entry: dict) -> dict | None:
        word = entry.get("word", "").strip()
        if not word:
            return None

        pinyin_raw = entry.get("pinyin", "").strip()
        explanation = entry.get("explanation", "").strip()
        definitions = [f"idiom: {explanation}"] if explanation else ["idiom"]

        return {
            "simplified": word,
            "traditional": word,
            "pinyin_raw": pinyin_raw,
            "pinyin": pinyin_raw,
            "definitions": definitions,
            "measure_words": [],
            "variants": [],
        }

    def _download(self, filename: str, dest: str) -> None:
        url = XINHUA_BASE_URL + filename
        logger.info("Downloading %s ...", url)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
            os.makedirs(self.data_dir, exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
            logger.info("Saved %s (%d bytes)", dest, len(data))
        except Exception as e:
            logger.error("Failed to download %s: %s", url, e)
            raise

    def load(self) -> None:
        """Download (if needed) and parse all four xinhua datasets."""
        for filename, kind in XINHUA_FILES:
            dest = self._cache_path(filename)
            if not os.path.exists(dest):
                self._download(filename, dest)

            try:
                with open(dest, "r", encoding="utf-8") as f:
                    entries = json.load(f)
            except Exception as e:
                logger.error("Failed to load %s: %s", dest, e)
                continue

            if kind == "idiom":
                for entry in entries:
                    w = entry.get("word", "").strip()
                    if w:
                        self.idioms[w] = entry
            elif kind == "word":
                for entry in entries:
                    w = entry.get("word", "").strip()
                    if w:
                        self.words[w] = entry
            elif kind == "ci":
                for entry in entries:
                    w = entry.get("ci", "").strip()
                    if w:
                        self.ci[w] = entry
            elif kind == "xiehouyu":
                for entry in entries:
                    r = entry.get("riddle", "").strip()
                    if r:
                        self.xiehouyu[r] = entry

        logger.info(
            "XinhuaDictionary loaded: %d idioms, %d chars, %d ci, %d xiehouyu",
            len(self.idioms),
            len(self.words),
            len(self.ci),
            len(self.xiehouyu),
        )

    def search(self, query: str) -> tuple[str, dict] | None:
        """Return ``(kind, entry)`` from the first dataset that matches *query*, or ``None``."""
        q = query.strip()
        if q in self.idioms:
            return ("idiom", self.idioms[q])
        if q in self.words:
            return ("word", self.words[q])
        if q in self.ci:
            return ("ci", self.ci[q])
        if q in self.xiehouyu:
            return ("xiehouyu", self.xiehouyu[q])
        return None