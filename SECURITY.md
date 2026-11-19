# Security

MailBrief holds a signed-in Outlook session, an archive of your email, and (during a remote sign-in) shows a
page that your Microsoft password is typed into. Reports about any of that are very welcome.

## Reporting a problem

Please report privately, not in a public issue: on GitHub, **Security → Report a vulnerability** (private
vulnerability reporting) on this repository. Include what you did, what happened, and the version
(`mailbrief --version`). Leave out your own email content and secrets.

This is a one-person project with no bounty and no guaranteed response time, but security reports come first.

## What is in scope

- The remote sign-in page (`mailbrief/session/remote_login.py`): reaching it without the one-time link,
  reading what is typed, keeping a session after it closes.
- Email content steering the tool: an email that makes MailBrief change the mailbox beyond its own `MB:`
  categories, send your data somewhere, or put a link of its own into a digest or answer.
- Linked-image downloads (`mailbrief/web_images.py`) reaching addresses on your own network.
- The Telegram bot answering anyone other than your registered private chat.
- Secrets (bot token, session cookies, AI key, encryption key) ending up in logs or output.

## What to know before you rely on it

- `data/` and `.env` together are your mailbox: the encrypted archive and session, and the key that opens
  them. Anyone with both can read your saved mail and act as you in Outlook. Protect the machine.
- Email text is sent to the AI endpoint you set in `AI_BASE_URL`. Digests, quotes and files you ask for go
  to Telegram, whose bot chats are not end-to-end encrypted.
- The remote sign-in is off unless you start it. It shows a live picture of Microsoft's real sign-in page
  in a browser on your own machine, so that machine could see what you type: only use it on a server you
  control, over https. On your own PC, plain `mailbrief login` is the safer way.
- MailBrief uses Outlook on the web's internal interface. It is unofficial, can break, and may not be allowed
  by your organisation's IT policy.
