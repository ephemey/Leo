import urllib.request
import re
import sys

# Using a reliable, uncompressed CC-CEDICT mirror on GitHub
CEDICT_URL = "https://raw.githubusercontent.com/spamscanner/spamscanner/master/cedict_1_0_ts_utf-8_mdbg.txt"

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
                # Read raw text line by line (decoding as UTF-8)
                for line_num, line_bytes in enumerate(response, 1):
                    line = line_bytes.decode('utf-8').strip()
                    
                    if not line or line.startswith("#"): 
                        continue
                    
                    # Match CC-CEDICT syntax
                    match = re.match(r'^(\S+)\s+(\S+)\s+\[(.*?)\]\s+/(.*)/$', line)
                    
                    if match:
                        trad, simp, pinyin, defs_raw = match.groups()
                        definitions = defs_raw.split('/')
                        
                        entry = {
                            "traditional": trad,
                            "simplified": simp,
                            "pinyin": pinyin,
                            "definitions": [d for d in definitions if d]
                        }
                        
                        # Index the entry
                        self.by_simplified[simp] = entry
                        self.by_traditional[trad] = entry
                        self.by_pinyin[pinyin.lower().replace(" ", "")] = entry

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
            
        return None