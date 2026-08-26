# TeleRadiopedia-Bot Privacy Policy

_Last updated: 2026-08-18_

TeleRadiopedia-Bot is a self-hosted, open-source bot that copies the three latest posts of one Telegram channel onto the main page of one or several wikis. This document describes what data the software processes, why, for how long, and what choices people have.

> **Who is responsible for your data.** TeleRadiopedia-Bot is software, not a service: anyone can run their own instance. The person or team operating a given instance (the **operator**) controls that instance's database, configuration and wiki account, and is the data controller for it. This document describes what the software itself does; a specific operator may add their own infrastructure (hosting, logging, backups) around it.

## What the bot processes

The bot administrates one Telegram channel and receives its posts. **Publication is the product**: by design, the text and the picture of a post in that channel are copied onto a wiki page that anyone can read, together with a link back to the post. A channel post carries no author — it is published under the channel's name — so what the bot copies is the channel's own output, not any individual's messages.

The bot also receives the three commands its administrators type in a private chat. Nothing else reaches it: it is in no groups, it relays no messages between people, and a message written to it by anyone who is not an administrator is answered and not stored.

## What the bot stores

All data lives in a local SQLite database (`src/tprp.db`) on the operator's machine.

| Data | Contents | Retention |
|---|---|---|
| Channel posts | The text or caption of the post and its formatting (which words are bold, italic or a link), its Telegram timestamp, its message id, its album id, the two identifiers of its largest photo size, the channel or person it was reposted from where it is a repost, and whether the row came from Telegram or from the channel's public web preview | The newest **60** posts of the channel; older rows are deleted as new posts arrive |
| Slot state | For each wiki and each of the three news slots: the message it was built from and the identifier of the picture uploaded into it | Overwritten at each pass; three rows per wiki |
| Bookkeeping | The numeric id and `@name` the followed channel resolved to, the time of the last pass, the error text of the last failed pass | Overwritten; kept until the file is deleted |

The Telegram token and the wiki password are read from `src/.env`, which is never committed. The bot writes one copy of the wiki password into `src/botconfig/user-password.cfg`, because Pywikibot reads its credentials from a file of its own and must be able to log in again unattended; that file is kept out of git and is readable only by the account running the bot where the platform supports it. Pywikibot's login cookie sits beside it.

**Not stored:** no readers of the channel, no editors of the wikis, no members of any chat, no message from anyone other than the channel itself, no analytics, no IP addresses.

## Where data goes

- **To every wiki in `config.WIKIS`**, and this is the point of the software: the shortened text of a post, its date, its picture and a link to the post are written to the three templates and the three files named there, under the bot's wiki account. Those pages are as public as each wiki is, and a wiki keeps their history — an edit that is later replaced remains visible in that history.
- **To the service chats**, if the operator configured any: what a pass changed, what it could not do, and when the bot started and stopped. No post text is sent there.
- **Nowhere else.** The software talks to Telegram's Bot API and to the wikis named in `config.WIKIS`.

## What other people can see

Everything published on the wikis: the text, the picture and the date of the three latest posts of the channel, the link back to each of them, and — where a post is a repost — the name of the channel or person it was taken from, which the channel itself displays above that post. Anyone reading a wiki sees them, and so does anyone reading the page history afterwards.

## Choices

- **The channel's operators** decide what the bot publishes by deciding what the channel posts. A post edited in the channel is corrected on every wiki at the next pass — while the bot is running it hears the edit from Telegram, and afterwards it notices it by re-reading the channel's public preview.
- **A deleted post is a special case.** Telegram does not tell bots when a channel post is deleted, so the bot keeps publishing its copy until three newer posts have pushed it out. To take a published post off the main page at once, publish new posts, or have an administrator edit the post's text and run `/update`.
- **The operator** can stop the bot, delete `src/tprp.db` — which erases every stored post — and revoke the BotPassword on the wikis and the token with @BotFather.

## Security

Secrets live in `src/.env` and, for Pywikibot's own use, in `src/botconfig/user-password.cfg`; both are excluded from git and neither is ever written to a log, a reply or a wiki page. The account should be a dedicated bot account whose BotPassword carries only the grants the bot needs: editing pages and uploading files. One account and one BotPassword serve every wiki of `config.WIKIS`.

## Age requirements

The bot is operated by administrators and publishes the output of a channel; it collects nothing from members of the public and is not directed at children.

## Changes

This document changes with the software. The date at the top is the last change.
