# Leo

A Discord bot for the Chinese-English Language Exchange (CELX) server https://discord.gg/c-e


TODO

front end editing chengyu dictionary

adding poetry / longer idioms to chengyu dictionary

need to be able to export / display current chengyu scores as there is no way to view Railway's volume

- There is no /khelp command in this file itself

Gap: startup_checks.check_filesystem (called before the bot connects) only pre-validates the chengyu DB directory (main.py:32, startup_checks.py:18-25) — the karaoke DB path isn't checked at startup. If DATABASE_PATH is misconfigured or unwritable, chengyu fails fast with a clear error, but karaoke would only fail lazily inside KaraokePoints.__init__ a few lines later with a raw sqlite3.OperationalError. Not something you asked me to fix, but worth knowing — say the word if you want that startup check extended to cover karaoke.db too.


Confirm trad<->simp conversion is working as intended especially for chengyu jielong
    - xinhua dictionary only has simplified :(

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


---

Codex issues:

Urgent

/cysetup is unrestricted and destructive.
Any member can reconfigure the Chengyu channel/role and reset monthly scores. See [chengyu_commands.py (line 203)](/workspaces/Leo/chengyu_commands.py:203) and [chengyu_commands.py (line 210)](/workspaces/Leo/chengyu_commands.py:210). Require manage_guild or bot-owner permission, and do not implicitly erase scores during configuration.


High priority



Chengyu chain state is lost on restart.
Used entries persist, but the current/previous idiom exists only in channel_states memory at [chengyu.py (line 292)](/workspaces/Leo/chengyu.py:292). After restart, the next unused four-character idiom is accepted without matching the previous chain. Persist the current entry, ideally as part of the same transaction that records the score and marks the entry used.

on_ready() repeats destructive and expensive startup work after reconnects.
Discord can emit on_ready more than once. Each occurrence clears every karaoke queue, reloads dictionaries, and globally syncs commands at [main.py (line 111)](/workspaces/Leo/main.py:111). Move one-time initialization to setup_hook() or protect it with an initialization flag.

Dictionary loading has a live-data race.
_load_dictionaries() mutates shared dictionaries in a worker thread after the bot is already connected at [main.py (line 117)](/workspaces/Leo/main.py:117). A command can search while those dictionaries are being mutated. Load before accepting commands or build temporary indexes and atomically swap them in.

Monthly reset side effects are not recoverable.
Scores and the reset checkpoint are committed before role changes and announcements at [chengyu.py (line 351)](/workspaces/Leo/chengyu.py:351). If Discord rejects a role operation or message, the hourly retry sees the reset as complete and never retries the missed work. Persist a pending-reset record or separate “score snapshot” from “side effects completed.”

Medium priority and optimizations
None of the server-specific slash commands are explicitly guild-only. /kadd can raise in DMs because a Discord User has no voice state. Add @app_commands.guild_only() and validate guild_id.

Unhandled slash-command errors are logged but no failure response is sent to the user at [main.py (line 84)](/workspaces/Leo/main.py:84).

/knotice can be toggled by anyone and fires when someone joins any voice channel in the guild, not a designated karaoke channel. See [karaoke.py (line 258)](/workspaces/Leo/karaoke.py:258).

Loading the four Xinhua JSON files used about 236 MiB RSS locally for 324,110 entries. Consider lazy-loading the less-used datasets or indexing them into SQLite.

Pinyin indexes store only one entry per pronunciation, so homophones overwrite one another at [dictionary.py (line 141)](/workspaces/Leo/dictionary.py:141). Use dict[str, list[entry]].

English definition searches scan the full dictionary synchronously for every request at [dictionary.py (line 170)](/workspaces/Leo/dictionary.py:170). Pre-index tokens or move searches off the event loop.

Both dependencies are unpinned in [requirements.txt (line 1)](/workspaces/Leo/requirements.txt:1), making deployments nondeterministic.

Startup validates only the Chengyu database, not karaoke.db, at [main.py (line 31)](/workspaces/Leo/main.py:31).

main.py creates databases and starts the bot at import time, preventing clean unit testing of startup behavior. Introduce create_bot() and an if __name__ == "__main__": entry point.
