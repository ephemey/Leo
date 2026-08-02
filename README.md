# Leo

A Discord bot for the Chinese-English Language Exchange (CELX) server https://discord.gg/c-e


TODO

front end editing chengyu dictionary

adding poetry / longer idioms to chengyu dictionary

need to be able to export / display current chengyu scores as there is no way to view Railway's volume

karaoke points awarded for participation when more than n people in channel undeafened
- There is no /khelp command in this file itself
- The "participating user" is identified purely by interaction.user.id — the Discord user who ran the slash command. There is no linkage to voice state at all; a user could run /kadd without being in any voice channel.
Gap: startup_checks.check_filesystem (called before the bot connects) only pre-validates the chengyu DB directory (main.py:32, startup_checks.py:18-25) — the karaoke DB path isn't checked at startup. If DATABASE_PATH is misconfigured or unwritable, chengyu fails fast with a clear error, but karaoke would only fail lazily inside KaraokePoints.__init__ a few lines later with a raw sqlite3.OperationalError. Not something you asked me to fix, but worth knowing — say the word if you want that startup check extended to cover karaoke.db too.


Issues: 

Critical / High Impact

4. Xinhua idiom check too broad (chengyu.py:177-179)
The secondary _is_idiom_entry check matches any xinhua word entry with word, pinyin, explanation — not just idioms. Regular vocabulary could enter the chengyu chain. Add a type tag at indexing time to distinguish idiom entries.

Medium Impact

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
