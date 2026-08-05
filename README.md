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

    /cysetup is unrestricted and destructive.
    Any member can reconfigure the Chengyu channel/role and reset monthly scores. See [chengyu_commands.py (line 203)](/workspaces/Leo/chengyu_commands.py:203) and [chengyu_commands.py (line 210)](/workspaces/Leo/chengyu_commands.py:210). Require manage_guild or bot-owner permission, and do not implicitly erase scores during configuration.

    on_ready() repeats destructive and expensive startup work after reconnects.
    Discord can emit on_ready more than once. Each occurrence clears every karaoke queue, reloads dictionaries, and globally syncs commands at [main.py (line 111)](/workspaces/Leo/main.py:111). Move one-time initialization to setup_hook() or protect it with an initialization flag.

    Monthly reset side effects are not recoverable.
    Scores and the reset checkpoint are committed before role changes and announcements at [chengyu.py (line 351)](/workspaces/Leo/chengyu.py:351). If Discord rejects a role operation or message, the hourly retry sees the reset as complete and never retries the missed work. Persist a pending-reset record or separate “score snapshot” from “side effects completed.”

    Unhandled slash-command errors are logged but no failure response is sent to the user at [main.py (line 84)](/workspaces/Leo/main.py:84).

    Pinyin indexes store only one entry per pronunciation, so homophones overwrite one another at [dictionary.py (line 141)](/workspaces/Leo/dictionary.py:141). Use dict[str, list[entry]].

    English definition searches scan the full dictionary synchronously for every request at [dictionary.py (line 170)](/workspaces/Leo/dictionary.py:170). Pre-index tokens or move searches off the event loop.

    Both dependencies are unpinned in [requirements.txt (line 1)](/workspaces/Leo/requirements.txt:1), making deployments nondeterministic.

    Startup validates only the Chengyu database, not karaoke.db, at [main.py (line 31)](/workspaces/Leo/main.py:31).

    main.py creates databases and starts the bot at import time, preventing clean unit testing of startup behavior. Introduce create_bot() and an if __name__ == "__main__": entry point.
