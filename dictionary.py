import urllib.request
import gzip
import re

# URL for the official CC-CEDICT gzip file
CEDICT_URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"

class ChineseDictionary:
    def __init__(self):
        # We'll build indexing dictionaries for fast lookups
        self.by_simplified = {}
        self.by_traditional = {}
        self.by_pinyin = {}

    def load_dictionary(self):
        print("Downloading and loading CC-CEDICT...")
        
        # Request headers to look like a browser request
        req = urllib.request.Request(
            CEDICT_URL, 
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        
        with urllib.request.urlopen(req) as response:
            with gzip.open(response, 'rt', encoding='utf-8') as f:
                for line in f:
                    if line.startswith("#"):  # Skip comment lines
                        continue
                    
                    # Match the CC-CEDICT line format:
                    # TRADITIONAL SIMPLIFIED [pin1 yin1] /def1/def2/
                    match = re.match(r'(\S+)\s+(\S+)\s+\[(.*?)\]\s+/(.*)/', line)
                    if match:
                        trad, simp, pinyin, defs_raw = match.groups()
                        # Convert slashes to a cleaner list format
                        definitions = defs_raw.strip('/').split('/')
                        
                        entry = {
                            "traditional": trad,
                            "simplified": simp,
                            "pinyin": pinyin,
                            "definitions": definitions
                        }
                        
                        # Store references in our lookup maps
                        self.by_simplified[simp] = entry
                        self.by_traditional[trad] = entry
                        # Lowercase pinyin lookup (removing spaces for easy matches)
                        clean_pinyin = pinyin.lower().replace(" ", "")
                        self.by_pinyin[clean_pinyin] = entry
                        
        print(f"Successfully loaded {len(self.by_simplified)} entries!")

    def search(self, query: str):
        """Search the dictionary by Simplified, Traditional, or Pinyin."""
        query_clean = query.strip()
        
        # 1. Search by Simplified
        if query_clean in self.by_simplified:
            return self.by_simplified[query_clean]
            
        # 2. Search by Traditional
        if query_clean in self.by_traditional:
            return self.by_traditional[query_clean]
            
        # 3. Search by Pinyin (e.g. "ni3hao3" or "ni hao")
        pinyin_query = query_clean.lower().replace(" ", "")
        if pinyin_query in self.by_pinyin:
            return self.by_pinyin[pinyin_query]
            
        return None