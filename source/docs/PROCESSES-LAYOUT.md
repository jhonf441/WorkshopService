# Processes section: layout and what is essential

Owner complaint (11-nov): the Processes tab "looks the same as before": 35 rows drawn, every group open even when everything is fine. This note says how the
tab is organised now and why. Decisions P-14, P-15 and P-16 of the page redesign still apply (settings in Machine > Automations, states with icon and word,
a fine row is a quiet check).

## 1. Groups: folded when fine

| Case | What is drawn |
| --- | --- |
| Group with all processes fine | FOLDED: only the header (icon, name, state with icon and word, "N procesos", chevron). Its one-line explanation and its rows are in the page but hidden |
| Group with something that needs a look (notice, stopped, no data, a relaunch, a pause a person made) | Opens by itself: the explanation, then the rows that need a look (worst first), then ONE line "N procesos mas, al dia" that opens the fine ones |
| A filter or a search is on | Every group it matches is open and shows exactly the rows that match (no summary line) |

Text wireframe, everything fine:

```
[shield] Seguridad                 (ok) Todo al dia     10 procesos  v
[folder] Control de la maquina     (ok) Todo al dia      5 procesos  v
[folder] Datos e historial         (ok) Todo al dia     10 procesos  v
```

Text wireframe, one process late:

```
[shield] Seguridad                 (!) 1 con aviso      10 procesos  v
  Protegen la maquina. Se ven y se vigilan; no se pueden apagar desde aqui.
  | Guardia de seguridad         Hace 2 min que no late; deberia hacerlo cada 5 s   (!) Con aviso  Latio hace 2 min  >
  | (ok) 9 procesos mas, al dia                                                                     v
[folder] Control de la maquina     (ok) Todo al dia      5 procesos  v
```

Rules (code: `dwc36/processes-fold.js`, `ProcessesPanel.vue`, `ProcessGroup.vue`):

- The fine groups a person opened are remembered per browser (`localStorage`, key `workshopProcessesOpenGroups`, every access in try/catch; a failing
  storage means "not remembered", nothing else changes).
- What is remembered never folds a group that needs a look. A person may still fold such a group, for the rest of the session only (it is in `sessionData`,
  gone on sign-out or change of role, and never written to the browser).
- A new filter or search forgets the hand folds, so it opens what it matches.
- "Plegar todo" / "Abrir todo" (one 40 px button next to the filters, `aria-expanded`) folds every group of the list or opens them all, with the fine rows
  of the groups that need a look. It does not rewrite the remembered choice while a filter or a search narrows the list.
- The header is a real button with `aria-expanded` and `aria-controls`; its accessible name is its own text (name, state, count), the fold / unfold
  sentence is its tooltip. Targets are 40 px or more. A link to a row inside a folded level (the anchor of the home) opens every folded level around it first
  (`irAcuando` in `WorkshopService.vue`). Nothing depends on the screen size or the kiosk.
- A group whose only difference is a pause a person made says "N en pausa" with the paused icon (calm, neither fine nor a notice) and opens by itself, so a
  paused process never hides behind a fold.

## 2. The opened process: essentials first

Evidence: `ProcessDetail.vue` drew five blocks with about 20 facts (state, last beat, "right now", activity: CPU, time active, loops, errors, a pace bar with
two charts, settings, five explanations, technical: id, kind, module mode, expected cadence). A person opens a row to answer three questions: how is it,
what is it, what can I do. Everything else answers "why is the machine doing this", which is a technician's question.

Essentials (always drawn when a row is open):

1. State: the state word with its icon (a chip), the service's own detail line, the pause tag, the restart line, an error nobody recovered from, the buses
   and the link of a separate service.
2. What it does: ONE sentence (the first explanation, else the description the service publishes).
3. What the person can do: the mode (auto / siempre / nunca, double tap), Pausar / Reanudar / Reiniciar with their lock reasons, the quiet link to
   Maquina > Automatismos where the process has a setting.

Folded under ONE button "Detalle tecnico" (closed by default, not even drawn until opened): last beat, relaunches, "right now" (running / resting / forced),
kind (thread or separate service), the mode of the module, expected cadence, an old (recovered) error, the internal id as quiet code, the other
explanations (what it is for, what it uses, what stops if it fails, where it is set), CPU, time active, loops, errors, the pace bar and the two charts.

Not changed: operations, arguments, role gates, lock reasons and the double tap (`tests/golden/page-actions.json` is identical).

## 3. Names

Everything the section draws was scanned for the 35 processes in both languages (`tests/processes-folded.test.js`: every state, rows open and folded, technical
detail open): no snake_case, no raw id as a title, no literal uppercase label, no missing text, no word of the other language. Fixed on the page: the
section headings are sentence case (the old style forced uppercase); the technical block is "Detalle tecnico" / "Technical detail"; a process the catalogs do
not name yet is drawn with its id as a sentence ("bed_zones" -> "Bed zones"), never raw.

The description of the macro process used to name a variable of the board; the service text now says it in plain words (`api_macros_process_description`)
and the test no longer lists any exception.
