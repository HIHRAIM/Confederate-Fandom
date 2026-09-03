# Confederate Fandom Privacy Policy

_Last updated: 2026-09-01_

Confederate Fandom is a self-hosted, open-source bot that does three things on wikis of the Fandom farm: it copies the three latest posts of one Telegram channel onto the main pages of one or several wikis, it standardises the names of Pokémon species on another wiki once a night, and it runs maintenance work on any Fandom wiki when an administrator asks it to. This document describes what data the software processes, why, for how long, and what choices people have.

> **Who is responsible for your data.** Confederate Fandom is software, not a service: anyone can run their own instance. The person or team operating a given instance (the **operator**) controls that instance's database, configuration and wiki account, and is the data controller for it. This document describes what the software itself does; a specific operator may add their own infrastructure (hosting, logging, backups) around it.

## What the bot processes

The bot administrates one Telegram channel and receives its posts. **Publication is the product**: by design, the text and the picture of a post in that channel are copied onto a wiki page that anyone can read, together with a link back to the post. A channel post carries no author — it is published under the channel's name — so what the bot copies is the channel's own output, not any individual's messages.

The bot also receives the commands its administrators type, and their answers to its questions — the dialog that sets up a run is ordinary messages in whatever chat or channel it was started in. Those answers are what the run is made of (which wiki, which pages, what to replace with what) and they are stored with the task. A message from anyone who is not an administrator is answered that the command is not for them, and nothing about it is kept.

Because the wiki work can now be delegated, the bot stores something about identifiable people for the first time: for each **wiki administrator** the operator appoints, their numeric id on Discord or Telegram, the name they are shown under there, and their account name on Fandom. All three are needed to answer the only question the bot asks about them — whether this person holds rights on the wiki they are asking it to work on — and the appointment is removed, row and all, with `/remwikiadmin`.

## What the bot stores

All data lives in a local SQLite database (`src/fd.db`) on the operator's machine.

| Data | Contents | Retention |
|---|---|---|
| Channel posts | The text or caption of the post and its formatting (which words are bold, italic or a link), its Telegram timestamp, its message id, its album id, the two identifiers of its largest photo size, the channel or person it was reposted from where it is a repost, and whether the row came from Telegram or from the channel's public web preview | The newest **60** posts of the channel; older rows are deleted as new posts arrive |
| Slot state | For each wiki and each of the three news slots: the message it was built from and the identifier of the picture uploaded into it | Overwritten at each pass; three rows per wiki |
| Bookkeeping | The numeric id and `@name` the followed channel resolved to, the time of the last pass, the error text of the last failed pass | Overwritten; kept until the file is deleted |
| Wiki administrators | For each person the operator appoints: the messenger, their numeric id there, their display name, their account name on Fandom, and who appointed them and when | Until `/remwikiadmin`, or until the file is deleted |
| Tasks and schedules | What was asked for, on which wiki, with which parameters, by whom (messenger, id, display name, Fandom account), when it ran and what it changed | The page list of a finished run is deleted after **30 days**; the row is kept as the record of who asked for what |

Beside the database, a finished run leaves up to three files in `src/reports/`: the diffs it made, whatever a reading mechanic collected, and the pages it could not write. They hold **wiki content and nothing else** — no traceback, no path on the host machine, no configuration — because they are sent to whoever asked for the run. A failure is written as its type and its message with anything path-shaped removed; the full traceback stays in the operator's own log. The files are a copy of what was already delivered and are deleted after **14 days**.

The Telegram token and the wiki password are read from `src/.env`, which is never committed. The bot writes one copy of the wiki password into `src/botconfig/user-password.cfg`, because Pywikibot reads its credentials from a file of its own and must be able to log in again unattended; that file is kept out of git and is readable only by the account running the bot where the platform supports it. Pywikibot's login cookies sit beside it, one file per wiki in `src/botconfig/cookies/`.

**Not stored:** no readers of the channel, no editors of the wikis, no members of any chat, no message from anyone other than the channel itself, no analytics, no IP addresses.

## Where data goes

- **To every wiki in `config.WIKIS`**, and this is the point of the software: the shortened text of a post, its date, its picture and a link to the post are written to the three templates and the three files named there, under the bot's wiki account. Those pages are as public as each wiki is, and a wiki keeps their history — an edit that is later replaced remains visible in that history.
- **To the wiki of `config.SPECIES_WIKI`**, where the second job corrects the names of Pokémon species in the articles. That job reads and writes article text only; it collects nothing about anybody.
- **To any Fandom wiki an administrator names in a task**, and only what that task was asked to do there. The bot refuses to work on a wiki where its account holds no status (bot, content moderator or administrator), and refuses a request from a wiki administrator who holds no rights on that particular wiki — both checks are made against the wiki itself, before anything is written.
- **To the person who asked for a run**, in the chat they asked from: the counters, and the files described above.
- **To the service chats and channels**, if the operator configured any — in Telegram and in Discord alike: what a news pass changed and what it could not do, when the bot started and stopped, and a line per task saying that it started, how far it has got and how it ended, naming who asked for it by their username and numeric id in brackets. Never as a mention, and no post text.
- **Nowhere else.** The software talks to Telegram's Bot API, to Discord's API, and to the wikis it is configured for or told to work on.

## What other people can see

Everything published on the wikis: the text, the picture and the date of the three latest posts of the channel, the link back to each of them, and — where a post is a repost — the name of the channel or person it was taken from, which the channel itself displays above that post. Anyone reading a wiki sees them, and so does anyone reading the page history afterwards.

## Choices

- **The channel's operators** decide what the bot publishes by deciding what the channel posts. A post edited in the channel is corrected on every wiki at the next pass — while the bot is running it hears the edit from Telegram, and afterwards it notices it by re-reading the channel's public preview.
- **A deleted post is a special case.** Telegram does not tell bots when a channel post is deleted, so the bot keeps publishing its copy until three newer posts have pushed it out. To take a published post off the main page at once, publish new posts, or have an administrator edit the post's text and run `/update`.
- **A wiki administrator** can ask the operator to remove their appointment; `/remwikiadmin` deletes the row that names them. The tasks they ran keep their name and id, because a wiki's edit history keeps the edits and the record of who asked for them belongs beside it.
- **Anyone whose page a run would change** sees it in that wiki's history and its recent changes like any other edit, made under the bot's account with a summary saying what was done. Every mechanic's edits can be undone on the wiki in the ordinary way; a deletion or a move cannot, which is why those need a confirmation and are marked as such in the bot's own catalogue.
- **The operator** can stop the bot, delete `src/fd.db` — which erases every stored post, appointment and task — delete `src/reports/`, and revoke the BotPassword on the wikis and the token with @BotFather.

## Security

Secrets live in `src/.env` and, for Pywikibot's own use, in `src/botconfig/user-password.cfg`; both are excluded from git and neither is ever written to a log, a reply, a report file or a wiki page. The account should be a dedicated bot account whose BotPassword carries only the grants the bot needs. One account and one BotPassword serve every wiki.

Two rules keep the machine out of what leaves it. Errors that reach a person or a file are written as the exception's type and message with anything path-shaped removed (`tasks/report.py: safe_error`), and the full traceback stays in the operator's own log. And the bot's own administrators are named in `config.py` rather than stored, so no corruption or edit of the database can hand out control of the bot; a wiki administrator's appointment, which *is* stored, grants nothing on a wiki where that person has no rights of their own.

## Age requirements

The bot is operated by administrators and publishes the output of a channel; it collects nothing from members of the public and is not directed at children.

## Changes

This document changes with the software. The date at the top is the last change.
