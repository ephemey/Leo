# Leo

TODO

front end editing chengyu dictionary

need to be able to export / display current chengyu scores as there is no way to view Railway's volume

Critical / High Impact


4. Xinhua idiom check too broad (chengyu.py:177-179)
The secondary _is_idiom_entry check matches any xinhua word entry with word, pinyin, explanation — not just idioms. Regular vocabulary could enter the chengyu chain. Add a type tag at indexing time to distinguish idiom entries.

Medium Impact

6. Monthly reset only fires lazily (chengyu_commands.py)
_reset_if_needed only runs when someone interacts. If the bot is quiet around month-end, role assignment is silently delayed. Add a background discord.ext.tasks loop.

7. Inconsistent search() return type (dictionary.py)
Returns dict | list[dict] | None. Every caller needs isinstance checks. Should always return list[dict].

8. Bare except Exception: pass in /cysetup (chengyu_commands.py:133-147)
DB and seed failures are silently swallowed. At minimum logger.exception(...) them.

Low / Style
9. Dead used_entries set in channel_states — never written to or read; DB is the real source of truth. Remove it.

10. UPSERT pattern (chengyu.py:313-341) — replace double INSERT/UPDATE with a single INSERT ... ON CONFLICT DO UPDATE.

11. convert_pinyin_syllable crashes on empty string (dictionary.py:27) — syllable[-1] raises IndexError on "".

12. Unpinned dependencies in requirements.txt — pin discord.py and python-dotenv to exact versions.

13. Connection leak in startup_checks (startup_checks.py:41-45) — use with contextlib.closing(sqlite3.connect(...)).

14. CJK regex too narrow (chengyu_commands.py:64) — [^一-鿿] misses CJK Extension A/B characters.

The three most impactful fixes to make first: blocking I/O (#1), SQLite concurrency (#2), and the NULL role crash (#3). Want me to tackle any of these?