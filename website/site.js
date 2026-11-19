/* MailBrief site: one terminal on every page. Theme, the fictional session, man pages,
   docs filter, copy buttons and the glyph backdrop.
   No network, no eval, no innerHTML: every string reaches the page through textContent. */
(function () {
  'use strict';

  var root = document.documentElement;
  var GITHUB = 'https://github.com/KidCoderT/mail-manager';
  var calm = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  /* ---------- theme (runs before first paint when loaded in <head>) ---------- */
  var THEME_KEY = 'mailbrief-theme';
  var lightQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;

  function storedTheme() {
    try {
      var v = localStorage.getItem(THEME_KEY);
      return v === 'light' || v === 'system' ? v : 'dark';
    } catch (e) {
      return 'dark';
    }
  }

  function applyTheme(choice) {
    root.setAttribute('data-theme', choice === 'system' ? (lightQuery && lightQuery.matches ? 'light' : 'dark') : choice);
  }

  function setTheme(choice) {
    choice = choice === 'light' || choice === 'system' ? choice : 'dark';
    try { localStorage.setItem(THEME_KEY, choice); } catch (e) { /* private mode: choice lasts for this page */ }
    applyTheme(choice);
    var select = document.getElementById('theme-select');
    if (select) select.value = choice;
  }

  applyTheme(storedTheme());
  root.classList.add('js');

  function initTheme() {
    var select = document.getElementById('theme-select');
    if (select) {
      select.value = storedTheme();
      select.addEventListener('change', function () { setTheme(select.value); });
    }
    if (lightQuery && lightQuery.addEventListener) {
      lightQuery.addEventListener('change', function () {
        if (storedTheme() === 'system') applyTheme('system');
      });
    }
  }

  /* ---------- the real CLI, as data: [name, usage arguments, summary] ----------
     scripts/check_website.py fails if a parser command is missing from this list. */
  var MAN = [
    ['login', '[--remote]', 'sign in to Outlook once in a visible browser'],
    ['run', '[--all] [--backfill] [--digest SCOPE] [--as-of YYYY-MM-DD] [--json] [--send] [--commit] [--plain] [--quiet]',
      'classify new mail, save it, label it in Outlook and print the digest'],
    ['emails', '[--period P] [--day D] [--search TEXT] [--show ID] [--thread ID] [--digest] [--export] [--send]',
      'browse saved emails, grouped by thread'],
    ['events', '[--days N] [--past N] [--send]', 'upcoming events found in your saved emails (no Outlook, no AI)'],
    ['labels', '<status|apply|clear|retag>', 'MailBrief\'s MB: labels (categories) in Outlook'],
    ['labels status', '', 'labelled / pending / cleared emails per period'],
    ['labels apply', '[--period P] [--days N] [--limit N] [--dry-run]', 'label now: pending emails, and cleared ones again'],
    ['labels clear', '[--period P] [--days N] [--all] [--label NAME] [--everywhere] [--colours] [--limit N] [--dry-run] [--yes]',
      'remove MB: labels (your own categories stay)'],
    ['labels retag', '[--period P] [--days N] [--limit N] [--dry-run] [--yes]',
      'ask the AI again about saved emails, with your current profile and topics'],
    ['rules', '<list|add|remove|profile>', 'your own labels: courses, senders, topics, profile'],
    ['rules list', '', 'your rules and how many saved emails each matches'],
    ['rules add', '<course|sender|topic> VALUE [--label NAME] [--direct] [--priority N] [--boost]', 'add or replace a rule'],
    ['rules remove', '<course|sender|topic> VALUE', 'remove a rule (labelled emails keep the label)'],
    ['rules profile', '"TEXT"', 'set who you are and what you want'],
    ['add-destination', 'telegram [--chat-id ID]', 'add where digests are sent'],
    ['index', '<status|update|rebuild>', 'the search index that chat uses'],
    ['chat', '"QUESTION"', 'ask your saved emails a question in the terminal'],
    ['bot', '', 'run only the Telegram chat listener in the foreground'],
    ['serve', '[--at "SCHEDULE"]', 'run forever, firing runs on the RUN_AT schedule'],
    ['stop', '', 'ask a running serve to stop'],
    ['status', '', 'is serve running? schedule, next and last run, log file'],
    ['autostart', '<on|off>', 'Windows: start serve hidden at logon']
  ];

  function anchorOf(name) { return 'cmd-' + name.replace(/ /g, '-'); }

  // The entry whose name is the longest prefix of the words, or null.
  function findMan(words) {
    for (var n = Math.min(2, words.length); n > 0; n--) {
      var name = words.slice(0, n).join(' ');
      for (var i = 0; i < MAN.length; i++) if (MAN[i][0] === name) return MAN[i];
    }
    return null;
  }

  /* ---------- output lines ----------
     A line is a string (plain), [cls, text] (one styled line), {segs:[[cls, text, extra], ...], pre}
     or {row:[name, text], run}. extra is {run: command} for a clickable command or {href}. */
  var OPEN = ['t-cyan', '  ↗ open'];
  function segs() { return { segs: Array.prototype.slice.call(arguments) }; }
  function pre(text, cls) { return { pre: true, segs: [[cls || '', text]] }; }
  function row(name, text, run) { return { row: [name, text], run: run || name }; }
  function cmd(text, run) { return ['', text, { run: run || text }]; }
  function link(text, href) { return ['', text, { href: href }]; }

  var SCRIPTS = {
    run: [
      ['t-dim', '[00:04] Signed in'],
      ['t-dim', '[00:52] Classifying 9 emails with the AI…'],
      ['t-dim', '[01:07] Labelling in Outlook 9/9'],
      ['t-dim', '[01:30] ✓ Writing the new digest of 9 emails (32s)'],
      '',
      segs(['t-h', '📬 9 new emails'], ['t-dim', ' — FYI 4 · Newsletter 2 · Needs Reply 2 · Urgent 1']),
      '',
      ['t-pink', 'TOP PRIORITIES TODAY'],
      segs(['', '• Housing: the semester 2 acceptance fee is due Friday'], OPEN),
      '',
      ['t-pink', 'NEEDS A REPLY'],
      segs(['', '• Dr Okafor asks whether you can help set up the lab demo on Thursday'], OPEN),
      '',
      ['t-pink', 'DEADLINES & MEETINGS'],
      segs(['', '• CS2040S problem set 4 is due Sun 23:59'], OPEN),
      '',
      ['t-pink', 'OPPORTUNITIES & EVENTS'],
      segs(['', '• ⭐ Campus HackDay sign-ups close on the 30th'], OPEN),
      '',
      ['t-dim', 'With --send, a real run delivers this digest to your Telegram.']
    ],
    events: [
      ['t-h', 'UPCOMING EVENTS'],
      ['t-dim', 'Next 14 days from Sat 17 Oct 2026. Built by code from saved mail: no Outlook, no AI.'],
      '',
      ['t-pink', 'THU 22 OCT'],
      segs(['t-cyan', '14:00'], ['', ' · Lab demo setup · Robotics Lab 2'], OPEN),
      ['t-dim', '  Dr Okafor needs two helpers for the open-day demo'],
      '',
      ['t-pink', 'SUN 25 OCT'],
      segs(['t-cyan', '23:59'], ['', ' · CS2040S problem set 4 due'], OPEN),
      '',
      ['t-pink', 'FRI 30 OCT'],
      segs(['t-cyan', '18:00'], ['', ' · ⭐ Campus HackDay · Innovation Hub'], OPEN),
      ['t-dim', '  24 hours, teams of four, beginners welcome'],
      ['t-dim', '  Sign up by Fri 30 Oct 12:00']
    ],
    chat: [
      segs(['t-dim', 'You  '], ['', 'when is the CS1101S midterm, and what can I bring?']),
      '',
      segs(['', '• It is on '], ['t-violet', '"Saturday 7 Nov, 10:00, MPSH 2"'], ['t-dim', ' [1]']),
      segs(['', '• You may bring '], ['t-violet', '"ONE A4 double-sided cheat sheet"'], ['t-dim', ' [1]']),
      '',
      ['t-pink', 'Sources'],
      segs(['t-dim', '[1] '], ['', '17 Oct · CS1101S Teaching Team · CS1101S Midterm logistics'], OPEN),
      ['t-dim', '📎 Midterm_seating.pdf would be sent in Telegram']
    ],
    status: [
      pre('Service:   running (pid 34732, since Sat 17 Oct 16:12)'),
      pre('Schedule:  daily 07:30'),
      pre('Next run:  Sun 18 Oct 07:30'),
      pre('Last run:  Sat 17 Oct 16:12 (new): ok, 19s'),
      pre('Autostart: on (starts at logon)'),
      pre('Log:       data\\logs\\2026-10.log')
    ],
    'labels status': [
      segs(['', 'Outlook labels: '], ['t-cyan', 'on']),
      pre('              labelled  pending  cleared', 't-dim'),
      pre('this-week           60        0        0'),
      pre('this-month         152        0        0'),
      pre('last-month         205        0        0'),
      pre('older                3        0        0'),
      pre('all                360        0        0'),
      '',
      ['t-dim', 'Each inbox email carries two categories, such as MB: Urgent and MB: P1.']
    ]
  };

  var ABOUT = [
    ['t-h', 'MailBrief'],
    'Reads your new Microsoft 365 Outlook mail each morning and sends you one digest on Telegram.',
    '',
    row('digest', 'new mail, sorted into what needs you today', 'mailbrief run'),
    row('events', 'a calendar built from the dates found in your mail', 'mailbrief events'),
    row('chat', 'ask a question; answers quote the email they came from', 'mailbrief chat'),
    row('labels', 'MB: categories in Outlook, plus rules of your own', 'mailbrief labels status'),
    '',
    ['t-dim', 'Self-hosted, for one person and their own mailbox. In Outlook it only adds its own MB:'],
    ['t-dim', 'categories: it never deletes, moves, sends, replies or marks anything as read.'],
    ['t-dim', 'Email text goes to the AI endpoint you choose. The archive stays encrypted on your machine.'],
    '',
    ['t-dim', 'A personal project, not affiliated with Microsoft or Telegram. It uses Outlook on the'],
    ['t-dim', 'web\'s internal interface, so check your organisation\'s policy before you use it.'],
    '',
    segs(['t-dim', 'next: '], cmd('setup'), ['t-dim', ' · '], cmd('commands'), ['t-dim', ' · '], cmd('github'))
  ];

  var HELP = [
    ['t-h', 'This terminal'],
    row('about', 'what MailBrief is'),
    row('commands', 'every real mailbrief command'),
    row('man <command>', 'usage and flags for one command', 'man run'),
    row('setup', 'open the complete setup guide'),
    row('docs', 'open the full reference'),
    row('github', 'open the source'),
    row('tour', 'play the demo session'),
    row('theme <name>', 'dark, light or system', 'theme light'),
    row('clear', 'empty this pane'),
    '',
    ['t-h', 'Simulated, with invented mail'],
    row('mailbrief run', 'the morning digest'),
    row('mailbrief events', 'the upcoming events calendar'),
    row('mailbrief chat', 'ask a question about your mail'),
    row('mailbrief status', 'the scheduler and its last run'),
    row('mailbrief labels status', 'categories applied in Outlook'),
    '',
    ['t-dim', 'A leading "uv run" is fine. Tab completes, Up and Down recall history.'],
    ['t-dim', 'Every answer is prewritten. Nothing is executed and nothing leaves this page.']
  ];

  // Not commands, but people will type them.
  var EGGS = {
    sudo: 'Nice try. MailBrief needs no admin rights, and neither does this page.',
    rm: 'MailBrief never deletes anything. Neither does this page.',
    exit: 'This is a web page. The door is the tab\'s close button.',
    vim: 'You would never get out. Try: docs',
    whoami: 'guest. MailBrief itself is single user: just you and your own mailbox.',
    pwd: '~/mailbrief',
    hello: 'Hello. Type help to see what this terminal answers.'
  };

  function manLines(entry) {
    var name = entry[0];
    var lines = [
      segs(['t-pink', 'NAME   '], ['t-h', 'mailbrief ' + name]),
      segs(['', '       ' + entry[2]]),
      segs(['t-pink', 'USAGE  '], ['', 'uv run mailbrief ' + name + (entry[1] ? ' ' + entry[1] : '')])
    ];
    var subs = MAN.filter(function (m) { return m[0].indexOf(name + ' ') === 0; });
    if (subs.length) {
      lines.push('');
      subs.forEach(function (m) { lines.push(row(m[0], m[2], 'man ' + m[0])); });
    }
    lines.push(segs(['t-pink', 'MORE   '], link('docs.html#' + anchorOf(name), 'docs.html#' + anchorOf(name)),
      ['t-dim', '  every flag, examples and exit codes']));
    return lines;
  }

  function commandList() {
    var lines = [['t-h', 'mailbrief <command>'], ['t-dim', 'Click a command, or type man <command>.'], ''];
    MAN.forEach(function (m) {
      if (m[0].indexOf(' ') === -1) lines.push(row(m[0], m[2], 'man ' + m[0]));
    });
    lines.push('');
    lines.push(segs(['t-dim', 'Telegram commands, settings and hosting: '], link('docs.html', 'docs.html')));
    return lines;
  }

  function squash(raw) { return String(raw).trim().replace(/\s+/g, ' '); }

  function normalize(raw) {
    return squash(raw).toLowerCase().replace(/^uv run( |$)/, '').replace(/^mailbrief( |$)/, '');
  }

  // man run | help run | run --help -> the words naming the command, or null.
  function manTarget(words) {
    if ((words[0] === 'man' || words[0] === 'help') && words.length > 1) return words.slice(1);
    var last = words[words.length - 1];
    if (words.length > 1 && (last === '--help' || last === '-h')) return words.slice(0, -1);
    return null;
  }

  // -> {lines} | {clear} | {lines, go} | {lines, tour}
  function respond(raw) {
    var typed = squash(raw).toLowerCase();
    var c = normalize(raw);
    var words = c ? c.split(' ') : [];
    var bare = typed !== c; // the user wrote "mailbrief ..." themselves

    if (c === 'clear' || c === 'cls') return { clear: true };
    if (c === 'help' || c === '?') return { lines: HELP };
    if (!c || c === '--help' || c === '-h' || c === 'commands' || c === 'ls') return { lines: commandList() };
    if (c === 'about') return { lines: ABOUT };
    if (c === 'tour' || c === 'demo') return { lines: [['t-dim', 'Playing four examples. Type, press Escape, or use Stop tour to take over.']], tour: true };
    if (c === 'home') return { lines: [['t-dim', 'You are home. Type help, or about.']] };
    if (c === 'github' || c === 'source' || c === 'repo') {
      return { lines: [segs(['t-dim', 'Opening '], link(GITHUB, GITHUB))], go: GITHUB };
    }
    if (words[0] === 'theme') {
      var choice = words[1];
      if (choice !== 'dark' && choice !== 'light' && choice !== 'system') {
        return { lines: [['t-dim', 'Usage: theme dark | light | system. Now: ' + storedTheme() + '.']] };
      }
      setTheme(choice);
      return { lines: [['t-dim', 'Theme: ' + choice + '.']] };
    }

    var target = manTarget(words);
    if (target) {
      var page = findMan(target);
      if (page) return { lines: manLines(page) };
      return { lines: [['t-pink', 'No manual entry for ' + target.join(' ') + '.'], segs(['t-dim', 'See them all: '], cmd('commands'))] };
    }
    // "setup" and "docs" are this site's pages; "mailbrief status" etc. stay MailBrief's.
    if (!bare && c === 'setup') return { lines: [['t-dim', 'Opening the complete setup guide.']], go: 'setup.html' };
    if (!bare && words[0] === 'docs') {
      var section = findMan(words.slice(1));
      var url = 'docs.html' + (section ? '#' + anchorOf(section[0]) : '');
      return { lines: [segs(['t-dim', 'Opening '], link(url, url))], go: url };
    }

    var entry = findMan(words);
    if (entry) {
      var name = entry[0];
      if (Object.prototype.hasOwnProperty.call(SCRIPTS, name)) {
        var note = name === 'chat' && c !== 'chat'
          ? [['t-dim', 'The playground has one prewritten answer, to this question:'], '']
          : c !== name && c !== 'run --send' && c !== 'run --send --commit'
            ? [['t-dim', 'The playground has one prewritten ' + name + '; your flags are ignored.'], '']
            : [];
        return { lines: note.length ? note.concat(SCRIPTS[name]) : SCRIPTS[name] };
      }
      return { lines: [segs(['t-violet', 'mailbrief ' + name], ['t-dim', ' is real, but it is not simulated here. Its manual:']), '']
        .concat(manLines(entry)) };
    }
    if (c === 'digest') return { lines: SCRIPTS.run };

    if (words[0] === 'echo') return { lines: [squash(raw).slice(5)] };
    if (Object.prototype.hasOwnProperty.call(EGGS, words[0])) return { lines: [['t-dim', EGGS[words[0]]]] };
    return { lines: [
      ['t-pink', 'command not found: ' + squash(raw).slice(0, 60)],
      segs(['t-dim', 'Type '], cmd('help'), ['t-dim', ' for the list, or try '], cmd('mailbrief run'), ['t-dim', '.'])
    ] };
  }

  /* ---------- completion ---------- */
  var WORDS = ['help', 'about', 'commands', 'setup', 'docs', 'github', 'tour', 'clear',
    'theme dark', 'theme light', 'theme system'];

  function complete(raw) {
    var lower = String(raw).replace(/^\s+/, '').replace(/\s+/g, ' ').toLowerCase();
    var head = /^(uv run )?(mailbrief )?(man |help )?/.exec(lower)[0];
    var rest = lower.slice(head.length);
    if (!rest) return null;
    var pool = MAN.map(function (m) { return m[0]; });
    if (head.indexOf('mailbrief') === -1 && !/(man|help) $/.test(head)) pool = WORDS.concat(['man', 'mailbrief'], pool);
    for (var i = 0; i < pool.length; i++) {
      if (pool[i].indexOf(rest) === 0 && pool[i] !== rest) return head + pool[i];
    }
    return null;
  }

  /* ---------- rendering ---------- */
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function commandButton(cls, text, run) {
    var node = el('button', cls, text);
    node.type = 'button';
    node.setAttribute('data-command', run);
    return node;
  }

  function renderSeg(s) {
    var extra = s[2];
    if (extra && extra.run) return commandButton('cmd-link', s[1], extra.run);
    if (extra && extra.href) {
      var a = el('a', s[0], s[1]);
      a.href = extra.href;
      if (/^https?:/.test(extra.href)) a.rel = 'noopener noreferrer';
      return a;
    }
    return el('span', s[0], s[1]);
  }

  function renderLine(line) {
    if (typeof line === 'string') return el('div', 'ln', line || ' ');
    if (Array.isArray(line)) return el('div', 'ln ' + line[0], line[1]);
    if (line.row) {
      var r = el('div', 'ln ln-row');
      r.appendChild(commandButton('cmd-link', line.row[0], line.run));
      r.appendChild(el('span', 't-dim', line.row[1]));
      return r;
    }
    var node = el('div', line.pre ? 'ln ln-pre' : 'ln');
    line.segs.forEach(function (s) { node.appendChild(renderSeg(s)); });
    return node;
  }

  // The "decrypt" effect: random glyphs settle into the real text, left to right.
  var GLYPHS = '!<>-_\\/[]{}=+*^?#01';
  function scramble(node) {
    var text = node.textContent;
    if (calm || !text || node._scrambling) return;
    node._scrambling = true;
    node.setAttribute('aria-label', text);
    var frame = 0;
    var total = Math.min(28, 8 + text.length);
    var timer = setInterval(function () {
      frame++;
      var settled = Math.floor(text.length * frame / total);
      var out = text.slice(0, settled);
      for (var i = settled; i < text.length; i++) {
        out += /\s/.test(text[i]) ? text[i] : GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
      }
      node.textContent = out;
      if (frame >= total) {
        clearInterval(timer);
        node.textContent = text;
        node._scrambling = false;
      }
    }, 32);
  }

  /* ---------- the terminal ---------- */
  var MAX_BLOCKS = 30;
  var TOUR = ['about', 'mailbrief run', 'mailbrief events', 'mailbrief chat "when is the midterm?"'];

  function initTerminal() {
    var form = document.getElementById('terminal-form');
    var input = document.getElementById('terminal-input');
    var output = document.getElementById('terminal-output');
    if (!form || !input) return;
    var home = !!output;
    var pane = home ? output.closest('.pane') : null;
    var results = document.getElementById('terminal-results');
    var ghost = form.querySelector('.ghost');
    var search = document.getElementById('docs-search');

    var history = [];
    var cursor = 0; // index into history; history.length means "the draft"
    var draft = '';
    var typing = null;
    var pendingRun = null;
    var pendingStep = null;
    var touring = 0;
    var stopButton = document.getElementById('stop-tour');

    function stopTour() {
      touring++;
      clearInterval(typing);
      clearTimeout(pendingRun);
      clearTimeout(pendingStep);
      if (stopButton) stopButton.hidden = true;
    }
    if (stopButton) stopButton.addEventListener('click', stopTour);

    function showGhost() {
      if (!ghost) return;
      var done = input.value ? complete(input.value) : null;
      ghost.textContent = '';
      if (!done || done.indexOf(input.value.toLowerCase()) !== 0) return;
      ghost.appendChild(el('i', '', input.value));
      ghost.appendChild(document.createTextNode(done.slice(input.value.length)));
    }

    function print(shown, lines) {
      if (results) results.hidden = false;
      var block = el('div', 'block block-new');
      var line = el('div', 'block-cmd');
      var prompt = el('span', 'prompt', '❯');
      prompt.setAttribute('aria-hidden', 'true');
      line.appendChild(prompt);
      line.appendChild(el('span', '', shown));
      var out = el('div', 'block-out');
      lines.forEach(function (l) { out.appendChild(renderLine(l)); });
      block.appendChild(line);
      block.appendChild(out);
      output.appendChild(block);
      while (output.children.length > MAX_BLOCKS) output.removeChild(output.firstChild);
      // Start reading at the command, not at the end of its output.
      var start = results && output.children.length === 1 ? results : block;
      pane.scrollTop = start.offsetTop - pane.offsetTop - 12;
    }

    function go(url) {
      window.location.href = url;
    }

    // Navigation is explicit; all other commands keep their home-terminal meaning.
    function runElsewhere(shown) {
      var c = normalize(shown);
      var typed = shown.toLowerCase();
      var words = c ? c.split(' ') : [];
      if (shown.charAt(0) === '/' && search) {
        search.value = shown.slice(1).trim();
        search.dispatchEvent(new Event('input'));
        window.scrollTo(0, 0);
        return;
      }
      if (c === 'home') { window.location.href = 'index.html'; return; }
      var navigation = typed === 'setup' || words[0] === 'docs' || ['github', 'source', 'repo'].indexOf(c) !== -1;
      if (navigation) {
        if (search && search.value) { search.value = ''; search.dispatchEvent(new Event('input')); }
        var destination = respond(shown);
        if (destination.go) { window.location.href = destination.go; return; }
      }
      window.location.href = 'index.html#!' + encodeURIComponent(shown);
    }

    function run(raw) {
      var shown = squash(raw).slice(0, 120);
      if (!shown) return;
      if (history[history.length - 1] !== shown) history.push(shown);
      if (history.length > 50) history.shift();
      cursor = history.length;
      draft = '';
      if (!home) { runElsewhere(shown); return; }

      var result = respond(shown);
      if (result.clear) {
        output.textContent = '';
        if (results) results.hidden = true;
        pane.scrollTop = 0;
        return;
      }
      print(shown, result.lines);
      if (result.go) go(result.go);
      if (result.tour) tour();
    }

    // Only the opt-in tour types commands. All pending work is cancellable.
    function typeAndRun(text, then) {
      clearInterval(typing);
      var id = touring;
      if (calm || !home) { input.value = ''; run(text); if (then) then(); return; }
      var i = 0;
      input.value = '';
      typing = setInterval(function () {
        if (id !== touring) return;
        input.value = text.slice(0, ++i);
        if (i < text.length) return;
        clearInterval(typing);
        pendingRun = setTimeout(function () {
          if (id !== touring) return;
          input.value = ''; showGhost(); run(text); if (then) then();
        }, 140);
      }, 22);
    }

    function tour() {
      stopTour();
      var id = ++touring;
      if (stopButton) stopButton.hidden = false;
      var step = 0;
      (function next() {
        if (id !== touring) return;
        if (step >= TOUR.length) { if (stopButton) stopButton.hidden = true; return; }
        pendingStep = setTimeout(function () {
          if (id === touring) typeAndRun(TOUR[step++], next);
        }, step ? 6500 : 400);
      })();
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      stopTour();
      var value = input.value;
      input.value = '';
      showGhost();
      run(value);
    });

    input.addEventListener('input', function () { stopTour(); showGhost(); });
    input.addEventListener('pointerdown', stopTour);

    input.addEventListener('keydown', function (event) {
      if (event.key !== 'Shift' && event.key !== 'Control' && event.key !== 'Alt' && event.key !== 'Meta') stopTour();
      if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
        if (!history.length) return;
        event.preventDefault();
        if (cursor === history.length) draft = input.value;
        cursor = Math.max(0, Math.min(history.length, cursor + (event.key === 'ArrowUp' ? -1 : 1)));
        input.value = cursor === history.length ? draft : history[cursor];
        showGhost();
      } else if (event.key === 'Tab' && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey) {
        // Only swallow Tab when there is something to complete, so keyboard focus is never trapped.
        var done = complete(input.value);
        if (done) {
          event.preventDefault();
          input.value = done;
          showGhost();
        }
      } else if (event.key === 'Escape') {
        input.value = '';
        showGhost();
      }
    });

    document.addEventListener('click', function (event) {
      var button = event.target.closest && event.target.closest('[data-command]');
      if (!button) return;
      stopTour();
      run(button.getAttribute('data-command'));
      if (home && window.matchMedia('(pointer: fine)').matches) input.focus({ preventScroll: true });
    });

    // Start typing anywhere and it lands in the prompt.
    document.addEventListener('keydown', function (event) {
      if (event.ctrlKey || event.metaKey || event.altKey || event.key.length !== 1 || event.key === ' ') return;
      var tag = (event.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || event.target.isContentEditable) return;
      input.focus({ preventScroll: true });
    });

    if (!home) return;
    // Click empty space in the pane to focus the prompt, unless text is being selected.
    pane.addEventListener('click', function (event) {
      if (event.target.closest('a, button, summary, details, .telegram-preview') || String(window.getSelection())) return;
      input.focus({ preventScroll: true });
    });
    if (window.matchMedia('(pointer: fine)').matches) input.focus({ preventScroll: true });

    // index.html#!command runs that command: how the other pages hand over.
    if (location.hash.indexOf('#!') === 0) {
      var handed = '';
      try { handed = decodeURIComponent(location.hash.slice(2)); } catch (e) { handed = ''; }
      window.history.replaceState(null, '', location.pathname + location.search);
      if (handed) {
        output.textContent = '';
        run(handed);
      }
    }
  }

  /* ---------- docs filter ---------- */
  function initDocsFilter() {
    var search = document.getElementById('docs-search');
    var content = document.querySelector('.docs-content');
    if (!search || !content) return;
    var sections = Array.prototype.slice.call(content.querySelectorAll('.doc-section'));
    var links = Array.prototype.slice.call(document.querySelectorAll('.docs-nav a[href^="#"]'));
    var empty = el('p', 'docs-empty', 'No section matches that. Try a command name, such as run or labels.');
    empty.hidden = true;
    empty.setAttribute('role', 'status');
    content.appendChild(empty);

    function filter() {
      var words = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      var shown = 0;
      sections.forEach(function (section) {
        var text = section.textContent.toLowerCase();
        var hit = words.every(function (w) { return text.indexOf(w) !== -1; });
        section.hidden = !hit;
        if (hit) shown++;
      });
      links.forEach(function (link) {
        var target = document.getElementById(decodeURIComponent(link.getAttribute('href').slice(1)));
        var section = target && target.closest('.doc-section');
        var item = link.closest('li') || link;
        // A nav item stays if its own section is visible or it holds a visible child link.
        link.hidden = !!(section && section.hidden);
        if (item !== link) item.hidden = false;
      });
      links.forEach(function (link) {
        var item = link.closest('li');
        if (item) item.hidden = !item.querySelector('a:not([hidden])');
      });
      empty.hidden = shown > 0 || !sections.length;
    }

    search.addEventListener('input', filter);
    search.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && search.value) {
        search.value = '';
        filter();
      }
    });
    if (search.value) filter();
  }

  /* ---------- copy buttons ---------- */
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var area = el('textarea', 'visually-hidden');
      area.value = text;
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(area);
      if (ok) resolve(); else reject(new Error('copy failed'));
    });
  }

  function initCopy() {
    document.querySelectorAll('main pre').forEach(function (block) {
      if (block.closest('#playground') || block.hasAttribute('data-no-copy')) return;
      var wrap = el('div', 'code-block');
      block.parentNode.insertBefore(wrap, block);
      wrap.appendChild(block);
      var button = el('button', 'copy-button', 'Copy');
      button.type = 'button';
      wrap.appendChild(button);
    });

    document.addEventListener('click', function (event) {
      var button = event.target.closest && event.target.closest('.copy-button');
      if (!button) return;
      var source = button.parentElement.querySelector('pre');
      if (!source) return;
      var code = source.querySelector('code') || source;
      copyText(code.textContent.replace(/\n$/, '')).then(
        function () { button.textContent = 'Copied'; },
        function () { button.textContent = 'Press Ctrl+C'; }
      ).then(function () {
        clearTimeout(button._reset);
        button._reset = setTimeout(function () { button.textContent = 'Copy'; }, 1600);
      });
    });
  }

  /* ---------- backdrop: a slow field of shifting glyphs behind the home window ---------- */
  function initBackdrop() {
    // ponytail: skipped on small screens (the window covers it) and under reduced motion.
    if (calm || !document.body.classList.contains('home') || window.innerWidth < 900) return;
    var canvas = el('canvas', 'backdrop');
    canvas.setAttribute('aria-hidden', 'true');
    document.body.insertBefore(canvas, document.body.firstChild);
    var ctx = canvas.getContext('2d');
    if (!ctx) return;
    var CELL = 22;
    var cols = 0, rows = 0, wave = null;

    function draw(col, rowIndex, bright) {
      var x = col * CELL, y = rowIndex * CELL;
      ctx.clearRect(x, y, CELL, CELL);
      if (Math.random() < 0.45) return; // leave gaps: a field, not a wall
      ctx.globalAlpha = bright ? 0.18 : 0.04 + Math.random() * 0.08;
      ctx.fillText(GLYPHS[Math.floor(Math.random() * GLYPHS.length)], x + CELL / 2, y + CELL / 2);
    }

    function resize() {
      var ratio = window.devicePixelRatio || 1;
      canvas.width = window.innerWidth * ratio;
      canvas.height = window.innerHeight * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.font = '13px "Cascadia Code", ui-monospace, Consolas, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = getComputedStyle(root).getPropertyValue('--glyph').trim() || '#b8a4ff';
      cols = Math.ceil(window.innerWidth / CELL);
      rows = Math.ceil(window.innerHeight / CELL);
      for (var c = 0; c < cols; c++) for (var r = 0; r < rows; r++) draw(c, r, false);
    }

    resize();
    window.addEventListener('resize', resize);
    new MutationObserver(resize).observe(root, { attributes: true, attributeFilter: ['data-theme'] });
    setInterval(function () {
      if (document.hidden) return;
      for (var i = 0; i < cols * rows / 90; i++) {
        draw(Math.floor(Math.random() * cols), Math.floor(Math.random() * rows), false);
      }
      // Now and then one row shifts left to right, like a line being rewritten.
      if (!wave && Math.random() < 0.04) wave = { row: Math.floor(Math.random() * rows), col: 0 };
      if (wave) {
        draw(wave.col, wave.row, true);
        if (wave.col > 2) draw(wave.col - 3, wave.row, false);
        if (++wave.col >= cols + 3) wave = null;
      }
    }, 350);
  }

  function initContents() {
    var narrow = window.matchMedia('(max-width: 820px)');
    document.querySelectorAll('.contents').forEach(function (details) {
      function layout() { details.open = !narrow.matches; }
      layout();
      narrow.addEventListener('change', layout);
      details.addEventListener('click', function (event) {
        if (narrow.matches && event.target.closest('a, [data-command]')) details.open = false;
      });
    });
  }

  function init() {
    initTheme();
    initContents();
    initTerminal();
    initDocsFilter();
    initCopy();
    initBackdrop();
    Array.prototype.forEach.call(document.querySelectorAll('[data-scramble]'), scramble);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  // The one runnable check: open any page with #selftest in the URL and read the console.
  if (location.hash === '#selftest') {
    var same = function (a, b, what) { console.assert(a === b, what + ': got ' + JSON.stringify(a)); };
    same(normalize('  UV  run   MailBrief   RUN '), 'run', 'normalize');
    same(normalize('mailbrief'), '', 'bare mailbrief');
    same(respond('uv run mailbrief labels status').lines, SCRIPTS['labels status'], 'known command');
    same(respond('mailbrief chat "anything <b>"').lines.length, SCRIPTS.chat.length + 2, 'chat question');
    same(respond('rm -rf /').lines[0][1], EGGS.rm, 'egg');
    same(respond('zzz').lines[0][1], 'command not found: zzz', 'unknown hint');
    same(respond('__proto__').lines[0][1], 'command not found: __proto__', 'prototype key');
    same(respond('constructor').lines[0][1], 'command not found: constructor', 'inherited key');
    same(respond('labels apply --period all').lines[4].segs[1][1], 'uv run mailbrief labels apply ' + findMan(['labels', 'apply'])[1], 'real-only man');
    same(respond('man labels retag').lines.length, 4, 'man page');
    same(respond('mailbrief status').lines, SCRIPTS.status, 'status is the simulation');
    same(respond('setup').go, 'setup.html', 'setup opens the full guide');
    same(respond('docs run').go, 'docs.html#cmd-run', 'docs jump');
    same(respond('CLEAR').clear, true, 'clear');
    same(complete('uv run mailbrief la'), 'uv run mailbrief labels', 'completion');
    same(complete('man ru'), 'man run', 'man completion');
    same(complete('ab'), 'about', 'word completion');
    same(complete(''), null, 'no completion on empty');
    console.log('mailbrief selftest done');
  }
})();
