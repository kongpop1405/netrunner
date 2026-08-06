# Evidence frames

Screenshots that a document elsewhere in `docs/` cites as the basis for a number
or a coordinate. Kept here rather than in `unknown_screens/`, which is gitignored
because the bot writes to it on every watchdog fire — a frame nobody can open is
not evidence.

Only frames a doc actually references belong here. Everything else stays in
`unknown_screens/` and gets deleted with it.

| File | Cited by | What it proves |
| --- | --- | --- |
| `blind_false_positive_in_run.png` | `RUN.md` — *Why `_BLIND_LAP_CYCLES` is 160* | A perfectly healthy run at 7.37M points, captured at the moment the blind-screen detector fired on it at the old threshold of 48. The cookie is mid-level; nothing was stuck. Sizing that threshold off the state-table length instead of a measurement cost a heart and the run. |
| `friendinfo_stacked_2layers.png` | `RUN.md` — *Both guards close with `close_popup`* | "Friend's Cookie" stacked over "Friend's Info": two grey X buttons overlap, and the outer one at (1633,107) is covered by the inner card — that pixel reads BGR(85,85,85), a shadow. This is why three taps at one coordinate cleared nothing. |
| `friendinfo_single_layer.png` | `RUN.md` — same section | The same dialog family with one layer only. Here (1633,107) *is* the button and closes it in a single tap (marker 0.974 → 0.343), which is why the earlier measurement called the inner coordinate dead. Both frames are needed: neither alone describes the dialog. |

Captured 2026-08-06 at 1920×1080 on LDPlayer (`127.0.0.1:5555`), the resolution
every template in this repo is cropped for.
