# The kit of the service page (`dwc36/ui`)

Generic pieces, self-contained: a piece imports only from this folder (and `core/format/`), reads no store, calls no API and carries no text of
its own. Texts arrive by props and slots; the few words every piece needs ("Try again", "Sending…") come from a translator the page PROVIDES
(`provide: { svText: (key, params) => string }`, keys in `sv-text.js` `KIT_KEYS`, catalog area `kit`). Colours only through tokens
(`styles/tokens.css` and the `--wf-*` of the family); the classes are in `styles/kit.css`. Everything that is touched is a real `button` of at
least 44 px. `tests/layers.test.js` and `tests/ui-kit.test.js` keep these rules.

They are **candidates for the family**: taking one to `TallerPlugins/vue/_shared36` is copying its files plus the classes it uses.

| Piece | Files | What it is | Used by | State |
|---|---|---|---|---|
| `SvActionRow` | `SvActionRow.vue` | The row of the page: name, sentence, control and the outcome of touching it (sending, verifying, done, refused, not confirmed). Its control is a built-in button or a slot. | every section | tested, not yet on a screen |
| `SvSwitch` | `SvSwitch.vue` | A switch whose word is what is read; `role="switch"`. | action rows | tested, not yet on a screen |
| `SvSheet` | `SvSheet.vue` | A box over the page: focus kept inside, Escape and a touch outside close it, focus returns to the opener. | dialogs, section picker, My session | tested, not yet on a screen |
| `SvConfirmDialog` | `SvConfirmDialog.vue` | THE confirmation for levels 3 and 4: the object affected, what will happen, the box of level 4, a button that repeats the verb. | every destructive action | tested, not yet on a screen |

| `SvBand` | `SvBand.vue` | The one band of the page (level, icon, fact, what it implies, a button). | the shell | on screen (shell) |
| `SvSectionNav` | `SvSectionNav.vue` | First level in three forms from the same entries: picker (narrow), wrapping row (medium), rail (wide); real links, counts, locked entry. | the shell | on screen (shell) |
| `SvTabs` | `SvTabs.vue` | Second level: a row of tabs that wraps; real links; arrow keys, Home, End. | the shell | on screen (shell) |

| `SvTextView` | `SvTextView.vue` | A reader of a long text in a wide sheet: one scroll, line numbers, wrapped lines (switch), search with next / previous, copy, download, rows drawn by pieces of 400, a wait with a bar that offers retry after 10 s. | file reader of Setup | on screen (Setup > Files); family candidate |
| `SvCopyButton` | `SvCopyButton.vue` | THE copy button: same icon and same word everywhere ("Copy" / "Copied"), keeps its size. | API reference, Commands, Bridge | on screen; family candidate |

Not yet built (design guide section 6; they come with the first screen that needs them): verdict, fold, item, word of state / chip /
stat, datum with age, table, load more. The header (badge, title, status chip, session chip) is markup of the shell with the classes of the kit.

How a screen wires a row:

```vue
<sv-action-row icon="mdi-restart" :name="t('...')" :desc="t('...')" :label="t('...')" :arm-label="t('...')"
               :action="restart" :permission="restart.permission()" @run="restart.run({ process: id })" @retry="restart.run({ process: id })" />
<sv-confirm-dialog :confirm="restart.confirm" :verb="t('...')" :object="{ name }" @accept="restart.accept()" @cancel="restart.cancel()" />
```

`restart` is a `createAction(...)` of `core/store/action.js`: the row only draws its state.

## Buttons: text, icon or both

One rule for the whole page (the same action has the same icon and the same word wherever it appears):

1. **Primary and risky actions: text with a verb** ("Restart", "Apply", "Download package"); an icon on the left is optional. Never an icon alone.
2. **Actions repeated in rows and tables** (copy, view, refresh): icon + text when there is room (the default: `SvCopyButton`); when the row is dense, only the icon with `aria-label` (the verb and the object) and a `title`. The word stays in the accessible name.
3. **Destructive or little known actions never go as an icon alone**: they carry the verb ("Delete range", "Kick") and, when they cut something, ask a second touch.
4. **Same action, same icon, same word**: copy = `mdi-content-copy` + "Copy" (done: `mdi-check` + "Copied"); refresh = `mdi-refresh` + "Refresh"; view = "View"; close = "Close".
5. **A button keeps its size while it waits.** The text stays (it is only hidden) and a spinner turns over it after 300 ms and for at least 500 ms (`sv-busy.js`, `.sv-btn[aria-busy='true']`); the other text it can show (the armed one) lends its width through `data-alt`.
6. Everything touched is at least 44 px (`--sv-touch`).

## Forms

A form is a grid, never loose styles: `.sv-fgrid` (two columns, one under 560 px) of `.sv-fcell` (label above with `.sv-label`, the control, the hint below with room;
`.sv-fcell-wide` takes the whole row) and a foot `.sv-fbar` with the MAIN button (filled, not dotted) next to what it will do ("Nothing is saved until you touch Save").
A number is a compact field (`.sv-field-num`, 120 to 160 px). The main button is disabled until something changed. Used by Data > Backups; the other forms follow it when they are touched.

## Vertical rhythm

Space comes from the scale of tokens, nothing else: **8** (`--sv-s2`) between related things, **12** (`--sv-s3`) between two rows of controls and between the blocks of a fold,
**16** (`--sv-s4`) from a group to the next block (a legend, a list) and inside every card, **24** (`--sv-s5`) between sections. The segments of a filter wrap
(`.sv-seg-wrap`, 8 between them) so they never run off a phone. In the header bar the chips are 36 px to see and 44 px to touch (an invisible hit area): a small thing
inside a bar is never made bigger to reach 44 px.
