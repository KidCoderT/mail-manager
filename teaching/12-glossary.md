# Glossary

<!-- TOC -->
**Contents**

- [14. Glossary](#14-glossary)
<!-- /TOC -->

## 14. Glossary

| Term | Meaning |
|---|---|
| **OWA** | Outlook Web App, Outlook in a browser |
| **service.svc** | OWA's internal JSON API (`?action=FindConversation`, `GetItem`, …) |
| **FindConversation** | The call that returns a page of the inbox list (conversations) |
| **GetItem** | Read-only call that returns full messages by ID |
| **GetAttachment** | Read-only call that returns attachment contents (base64) |
| **StartupData** | Settings Outlook loads at startup, including your address |
| **ConversationId** | Shared by every message in a thread |
| **ConversationIndex** | Binary thread-tree key: 22-byte root plus 5 bytes per reply level |
| **ItemIds / GlobalItemIds** | A thread's messages in the inbox / in every folder |
| **Focused / Other** | The two tabs of Focused Inbox (`FocusedViewFilter` 0 / 1) |
| **storage_state** | Playwright's snapshot of cookies and local storage, i.e. the login |
| **Headless** | A browser running without a window |
| **Virtualized list** | A list that only renders and loads what's on screen |
| **Cursor** | "Processed up to here": a time plus recent IDs |
| **Backfill** | One-off processing of all historical mail |
| **Idempotent** | Running twice has the same effect as running once |
| **Atomic write** | Write to a temp file, then rename: all-or-nothing |
| **Fernet** | Authenticated symmetric encryption from the `cryptography` library |
| **Prompt injection** | Text inside data (an email) trying to act as instructions to an AI |
| **429** | HTTP "Too Many Requests", a rate limit |
| **Data URL** | An image embedded as text: `data:image/png;base64,…` |
| **ponytail comment** | A marked, deliberate simplification naming its limit and upgrade path |
| **Category** | Outlook's label: a name stored on an email (several allowed), shown with a colour |
| **Master category list** | Your mailbox's list of category names → colours (Settings → Categories) |
| **UpdateItem** | Exchange call that changes fields of an email; MailBrief may only use it on `Categories` |
| **ChangeKey** | Exchange's version stamp for an email, returned with its id |
| **`check_request`** | The guard every Outlook request passes: reads allowed, writes only for `MB:` categories |
| **Service / daemon** | A program that keeps running in the background (here: `mailbrief serve`) |
| **Child process** | A separate program started by another; it can crash or be killed without taking the parent down |
| **Exit code** | The number a program returns when it ends: 0 = fine, anything else = a specific problem |
| **OS file lock** | A lock the operating system holds on a file for a process and drops automatically when the process ends |
| **SIGINT / SIGTERM** | "Please stop" signals: Ctrl+C / what `docker stop` sends |
| **Process group** | Processes that receive Ctrl+C together; a run gets its own so Ctrl+C reaches only `serve` |
| **pythonw** | Windows Python with no console window (and so no stdout) |
| **Container / image** | Docker: an image is a packaged app plus everything it needs; a container is a running copy of it |
| **Volume** | A folder from the host mounted into a container, so data outlives the container |
