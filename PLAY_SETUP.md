# PLAY SETUP — get the screen ready before running a bot

The bots recognize the game by matching cropped pictures ("templates") against the
emulator screen. Those pictures were cropped at **exactly 1920×1080**. If the emulator
is any other size, nothing matches and the bot **looks broken** — it does nothing, or
taps random spots (you'll see `jump`/`tap` in the log while the game just sits on the
menu). This is the #1 reason a bot "doesn't work" on a new machine.

Do this checklist once per machine, then before each run.

## 1. Set the LDPlayer instance to 1920×1080 (one time)

1. Open **LDMultiPlayer** (the multi-instance manager).
2. **Stop** the instance if it's running (you can't change resolution while it runs).
3. Click the ⚙️/Settings on that instance → **Resolution** → choose **Custom** →
   width **1920**, height **1080**, DPI **240** → Save.
4. Start the instance.

Quick command-line alternative (instance must be stopped first):

```
"C:\LDPlayer\LDPlayer14\ldconsole.exe" modify --index 0 --resolution 1920,1080,240
```

(`--index 0` = the first instance; use the right index if you have several.)

**Verify:** run `install.bat` again, or run any bot — the log now prints either
`resolution 1920x1080 OK` or a loud warning telling you it's the wrong size.

## 2. Enable ADB (one time)

LDPlayer → Settings → **Other** → ADB debugging → **Open local connection** → Save,
restart the instance.

## 3. Put the game on the right screen (every run)

For **coinrun** / **boxrun_default** (the run-grinders):

- Be on the **home screen** — the one with the big green **Play!** button bottom-right.
- Any Episode is fine (the bot finds the **Play!** button, not the episode name).
- Don't leave a popup open over Play! (daily reward, event, friend info). Close them first.

For **giftdraw** / **sendlife** / **addfriend**: see the matching section in
[RUN.md](RUN.md) — each needs its own starting screen (Gift Draw popup open / Friends tab /
Find tab).

## 4. Don't touch the emulator while it runs

Any manual tap or screen change mid-run makes the bot's next tap land on the wrong thing.
Start the bot, then leave the window alone until you stop it with `Ctrl+C`.

---

### Still not working after all of the above?

The templates were also cropped from one specific account's UI. If your account shows a
different skin/language/layout on a button, that template may need re-cropping — that part
needs whoever set this up (it's not something the installer can fix). Send them today's
file from the `logs\` folder; run once with `-v` first so the log includes the match
scores:

```
python main.py --config config/cookierun/coinrun.json --dry-run -v --max-cycles 10
```
