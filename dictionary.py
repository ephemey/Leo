import urllib.request
import re
import sys

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

    def load_dictionary(self):
        print("Starting dictionary download from GitHub mirror...", flush=True)
        
        req = urllib.request.Request(
            CEDICT_URL, 
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                for line_num, line_bytes in enumerate(response, 1):
                    line = line_bytes.decode('utf-8').strip()
                    
                    if not line or line.startswith("#"): 
                        continue
                    
                    match = re.match(r'^(\S+)\s+(\S+)\s+\[(.*?)\]\s+/(.*)/$', line)
                    
                    if match:
                        trad, simp, pinyin_raw, defs_raw = match.groups()
                        
                        # Process raw definitions
                        raw_definitions = [d.strip() for d in defs_raw.split('/') if d.strip()]
                        
                        definitions = []
                        measure_words = []
                        variants = []
                        
                        for d in raw_definitions:
                            # 1. Extract Measure Words (CL:...)
                            if d.startswith("CL:"):
                                # Strip 'CL:' and clean up the classifiers
                                classifiers = d[3:].split(',')
                                for cl in classifiers:
                                    # Clean up format like 隻|只[zhi1] to nice tone marks
                                    cl_match = re.match(r'([^\[]+)(?:\[(.*?)\])?', cl)
                                    if cl_match:
                                        chars, pin = cl_match.groups()
                                        if pin:
                                            formatted_pin = convert_pinyin_sentence(pin)
                                            measure_words.append(f"{chars} (`{formatted_pin}`)")
                                        else:
                                            measure_words.append(chars)
                                continue
                            
                            # 2. Extract Variant indicators
                            if "variant of" in d or "old variant of" in d:
                                variants.append(d)
                                continue
                                
                            # 3. Format figurative/literal annotations nicely
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
                        
                        # Indexing
                        self.by_simplified[simp] = entry
                        self.by_traditional[trad] = entry
                        
                        # Store both raw pinyin ('ni3hao3') and clean tone-marked version for searches
                        self.by_pinyin[pinyin_raw.lower().replace(" ", "")] = entry
                        self.by_pinyin[entry["pinyin"].lower().replace(" ", "")] = entry

            print(f"SUCCESS: Loaded {len(self.by_simplified)} entries into memory!", flush=True)
            
        except Exception as e:
            print(f"ERROR: Failed to download or parse the dictionary: {e}", file=sys.stderr, flush=True)

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