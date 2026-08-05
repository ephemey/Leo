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

High — Karaoke points can be farmed and queues can be manipulated by any member.
/kadd allows duplicate entries, while unrestricted /knext immediately awards points based only on current voice-channel attendance. A user can repeatedly add and advance themselves to accumulate points without completing a song. Any member can also remove or bump other users by position. See [karaoke.py (line 178)](/workspaces/Leo/karaoke.py:178), [karaoke.py (line 197)](/workspaces/Leo/karaoke.py:197), [karaoke.py (line 240)](/workspaces/Leo/karaoke.py:240), and [karaoke.py (line 262)](/workspaces/Leo/karaoke.py:262). Restrict moderation/advancement commands and prevent duplicate or rapid point awards.

High — Chengyu runs in every text channel before /cysetup.
When no channel is configured, the handler does not return; it evaluates four-character messages server-wide and can award points/create independent chains. See [chengyu_commands.py (line 123)](/workspaces/Leo/chengyu_commands.py:123). It should return unless a configured channel exists and matches the message channel.

High — The committed database contains operational Discord data.
[chengyu.db](/workspaces/Leo/chengyu.db) is tracked by Git despite *.db being ignored at [.gitignore (line 223)](/workspaces/Leo/.gitignore:223). It contains guild configuration and Discord-derived user/gameplay records, conflicting with the restricted-storage description at [Privacy.md (line 29)](/workspaces/Leo/Privacy.md:29). Remove it from the index; if the repository has been shared, consider purging it from history.

High — /cysetup remains unrestricted and destructive.
It has no permission checks, resets monthly state after responding, and silently ignores reset/starter failures. See [chengyu_commands.py (line 205)](/workspaces/Leo/chengyu_commands.py:205) and [chengyu_commands.py (line 218)](/workspaces/Leo/chengyu_commands.py:218).

High — Monthly-reset failures remain unrecoverable.
Chengyu scores and the checkpoint are finalized before Discord role/message operations. Karaoke has the same defect: scores/checkpoint are committed before role rotation. A transient Discord failure permanently skips the remaining work. See [chengyu.py (line 384)](/workspaces/Leo/chengyu.py:384), [chengyu_commands.py (line 22)](/workspaces/Leo/chengyu_commands.py:22), [karaoke_points.py (line 190)](/workspaces/Leo/karaoke_points.py:190), and [karaoke.py (line 103)](/workspaces/Leo/karaoke.py:103).

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


## Issue status re-audit (August 2026)

### Important current findings

1. **High — New Chengyu reset regression.**
   The reset marks and stores the new starter in `chengyu_commands.py`, then `commit_monthly_reset()` deletes every used entry in `chengyu.py`. The starter remains the current channel state but is no longer considered used, so it can be submitted again for a point.

2. **High — Karaoke farming is only slightly mitigated.**
   The ten-second timer prevents immediate advancement, but duplicate `/kadd` entries are still allowed, anyone can remove or bump another entry, and `/knext` remains unrestricted. Bumping or removing the current singer does not reset the timer, so a newly bumped singer can inherit the previous singer's elapsed time and immediately receive points. Waiting ten seconds also does not demonstrate that a song was performed.

3. **High — Reset recovery is improved, but not complete.**
   Discord failures before the final commit will now generally be retried. However, score deletion and checkpoint advancement are separate commits, so a crash between them still loses scores while leaving the reset pending. Retried Discord operations can produce duplicate announcements, Chengyu state is mutated before the announcement succeeds, and the existing tests no longer agree with the changed two-phase API.

### Complete issue status

| Issue | Current status | Notes |
|---|---|---|
| Karaoke score farming/queue manipulation | **Partial** | Ten-second timer added, but duplicates, unrestricted controls, and timer inheritance remain |
| Chengyu active before `/cysetup` | **Resolved** | Handler now returns when no channel is configured |
| Tracked operational `chengyu.db` | **Not resolved** | The database remains tracked despite `*.db` in `.gitignore` |
| `/cysetup` unrestricted and destructive | **Partial** | It is now owner-only, but still clears monthly scores and silently swallows errors |
| Monthly-reset side effects unrecoverable | **Partial** | Retry behavior improved, but commits are not atomic and side effects are not exactly-once |
| Privacy cleanup when bot leaves a server | **Not resolved** | No `on_guild_remove` cleanup |
| Front-end Chengyu dictionary editing | **Not resolved** | No front-end editor |
| Poetry/longer idioms | **Not resolved** | Still requires exactly four characters |
| Display/export Chengyu scores | **Partial** | `/cylb` and `/cyscore` provide display; export remains absent |
| `/khelp` | **Not resolved** | No `/khelp`; global `/help` remains incomplete for karaoke |
| Karaoke DB startup validation | **Not resolved** | Startup still validates only Chengyu |
| Traditional/simplified conversion | **Partial/unchanged** | Works for CEDICT entries; Xinhua remains simplified-only |
| Repeated `on_ready()` initialization | **Not resolved** | Queues, dictionaries, and command sync still repeat |
| Unhandled command errors lack user response | **Not resolved** | Errors are still only logged |
| Pinyin homophones overwrite | **Not resolved** | The index still stores one entry per pronunciation |
| Synchronous English dictionary scan | **Not resolved** | Full scan remains |
| Unpinned dependencies | **Not resolved** | `requirements.txt` remains unpinned |
| Import-time startup in `main.py` | **Not resolved** | Databases and the bot still start at import time |

### Verification

- `python -m pytest -q`: **69 passed, 5 failed**. All failures concern the changed monthly-reset contract.
- Compilation passed.
- Mypy reports **17 errors**, up from 15 because the new owner check and timer dictionary add typing errors.
- Plain `pytest -q` still fails during collection because project modules are not on its import path.
- `git diff --check` passed.

The most urgent next fixes are the Chengyu starter deletion regression, atomic reset commits, and the remaining karaoke authorization/timer bypasses.
