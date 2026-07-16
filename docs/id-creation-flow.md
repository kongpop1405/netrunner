# Cookie Run Classic — ID creation flow

Manual-driven capture of the account-creation steps, recorded live via ADB on a cloned LDPlayer instance. Each step logs: what the screen shows, the tap/input sent, its coordinates, and the resulting screen.

## Environment

- Instance: `cookie-idtest` (LDPlayer index 3), cloned from index 2 (`LDPlayer-2`).
- Resolution: 1280x720.
- ADB: `C:\LDPlayer\LDPlayer14\adb.exe`, device `127.0.0.1:5561` (port = `5555 + 2*index`).
- Package: `com.devsisters.crg`.
- Game version: 26.6.12.

## Launch

App does **not** start via `monkey`/`am` reliably — launch by tapping the home-screen icon.

- `input tap 463 171` — "CookieRun Classic" icon on the LDPlayer home screen → splash → age gate.

## Steps

### Step 1 — Age gate ("Please enter your age.")

Screen: white card, `-`/`+` stepper starting at `0`, a slider, orange **Confirm** button. Player ID still `-` (fresh account, no ID yet).

Action: raise age into the 20–30 range, then Confirm.

- `+` button: tap `807 312` (1280x720 coords). Each tap = +1.
- Set age 25: tap `807 312` × 25 (150 ms apart).
- Result: value shows `25`, slider moved right. ✅ verified.

- Confirm: tap `640 450`. ✅ verified → advances to Terms of Service.

### Step 2 — Terms of Service ("On Terms of Service")

Screen: dialog "Before you begin playing... please accept our Terms of Service and Privacy Policy." Buttons: `Terms Of Service >` (opens docs) and `OK` (accept).

Action: accept — tap OK.

- `OK`: tap `855 470` (1280x720 coords). ✅ verified → title screen with DevPlay Login.

### Step 3 — Title screen / DevPlay Login

Screen: Cookie Run title art, orange button **`D DevPlay Login`** near the bottom. Player ID still `-`.

Action: tap DevPlay Login.

- `DevPlay Login`: tap `640 640` (1280x720 coords). ✅ verified → login-method chooser.

### Step 4 — Login method chooser

Screen: 4 stacked buttons — `Sign in with Google`, `Sign in with Apple`, `Sign in with E-mail`, and a yellow **`Play`** at the bottom (= guest login, no account link).

Action: guest — tap the bottom yellow `Play`.

- `Play` (guest): tap `843 486` (1280x720 coords). ✅ verified → data-download prompt.

### Step 5 — Data download

Screen: dialog "Downloading 290MB of data." with a green **Confirm**; a "Checking game data… 40%" progress bar behind it.

Action: accept the download.

- `Confirm`: tap `640 458` (1280x720 coords). ✅ verified → "Retrieving game data…" progress bar, then straight into the game home screen (no nickname prompt on this build).

### Step 6 — First launch into home (account created)

Screen: game home — Episode 1 "Escape from the Oven", hearts/coins/crystals HUD, `Play!` button. A tutorial popup: "Hi there! New to the game? Let me show you how to play!" with green **Confirm**.

The guest account now exists — the home HUD loaded with starter currency (210,000 coins, 5 crystals).

Action: dismiss the tutorial popup.

- `Confirm`: tap `640 458` (1280x720 coords). ✅ verified → forced tutorial run "The Witch's Oven" starts.

### Step 7 — Skip the tutorial run

The tutorial is a forced auto-run (Jump/Slide/Boost/Treasure HUD, speech bubbles). To skip instead of playing it out:

1. Pause: tap the `‖` button top-right `1188 64`. → pause overlay (Continue / Quit).
2. Quit: tap `630 425`. → confirm dialog "Quit the tutorial? You can restart it any time from the settings."
3. Confirm quit: tap `630 382`. ✅ verified → back to home, then the Set Nickname prompt.

Note: tutorial can be restarted later from settings, so quitting is safe.

### Step 8 — Set Nickname

Screen: popup "Set Nickname — What do you want to be called? (Cannot be changed again for 24 hrs)", a text field "Enter your nickname!", and a **Confirm** button (dark/disabled until text is entered).

Action: tap the field, type a nickname, Confirm.

- Field: tap `640 379` → soft keyboard / IME.
- Enter text: `adb shell input text "<nickname>"` (ASCII; no spaces via `input text` — use `%s` for a space).
- `Confirm`: tap `640 490` (enabled once the field is non-empty).
- Result: pending — this is where you left off; nickname not yet chosen.

## Summary

Full guest-ID creation path (LDPlayer 1280x720, `com.devsisters.crg`):

1. Home icon `463 171` → launch
2. Age gate: `+` `807 312` ×N (20–30), Confirm `640 450`
3. Terms of Service: OK `855 470`
4. Title: DevPlay Login `640 640`
5. Login chooser: `Play` (guest) `843 486`
6. Data download: Confirm `640 458` → ~290MB
7. Home + tutorial popup: Confirm `640 458` → forced tutorial run
8. Skip tutorial: pause `1188 64` → Quit `630 425` → confirm Quit `630 382`
9. Set Nickname: tap field `640 379`, `input text <name>`, Confirm `640 490`

The account is created on guest login (Play) and populated after the data download. The tutorial run is forced but skippable via pause→Quit. Nickname is the only text entry required, and it's prompted after the tutorial is quit (not during signup).

Extra first-run step on a truly fresh app-data wipe (`pm clear com.devsisters.crg`): an Android **notification permission** dialog appears before the age gate — tap `DON'T ALLOW` at `639 473` (exact bounds from `uiautomator dump`: `[284,431][995,515]`). It can take a second tap; verify it's gone via a UI dump (`permission_deny` absent) before proceeding.

## Cloning base images — findings

Tested whether an LDPlayer clone (`ldconsole copy --from N`) can skip setup steps for fresh-ID farming. **Key result: the 290MB data download is bound to the guest login session, not the device.** So no single base image gives both a new ID and a skipped download.

| Base | cut point | skips age/ToS | skips login | new ID | skips 290MB |
|------|-----------|:---:|:---:|:---:|:---:|
| `cr-base-loaded` | after download, at Set-Nickname | ✅ | ✅ | ❌ (same ID cloned) | ✅ |
| `cr-base-preauth` | at DevPlay-Login / login-chooser (Player ID still `-`) | ✅ | ❌ | ✅ | ❌ (re-downloads per clone) |

- **`cr-base-loaded`** — clone lands directly on the Set-Nickname popup, no download. But every clone carries the *same* guest player-id, so it's only useful for quickly resetting the *same* account, not making new ones.
- **`cr-base-preauth`** — clone lands on the DevPlay-Login screen; age gate + ToS + notification prompt are already persisted. Each clone does its own `DevPlay Login → Play` and gets a **fresh** guest ID — but pays the 290MB download again (verified live: guest login on the clone re-triggered "Downloading 290MB").

**For farming new IDs use `cr-base-preauth`**: it removes the annoying pre-login steps (notification, age, ToS) and leaves a clean 3-tap tail — `DevPlay Login 640 640` → `Play 843 486` → download `Confirm 640 458` — then the tutorial-skip + nickname steps above.

Clone procedure: `ldconsole quit --index N` (must be stopped, disk-flushed) → `ldconsole copy --name <clone> --from N`. adb port of any instance = `5555 + 2*index`.

### Instance map (this machine, as of test)

| index | name | port | role |
|-------|------|------|------|
| 0 | LDPlayer | 5555 | original (adbd was flaky) |
| 1 | LDPlayer-1 | 5557 | netrunner cookierun bot |
| 2 | LDPlayer-2 | 5559 | Cookie-Run source |
| 3 | cookie-idtest | 5561 | first manual ID walkthrough |
| 4 | cr-base-loaded | 5563 | base: after-download (same ID) |
| 5 | cr-base-preauth | 5565 | base: pre-login (new ID per clone) |

Note: LDPlayer14 adbd goes `offline` easily when instances are killed/relaunched in quick succession (see RUN.md) — a single working instance at a time is the reliable path; reboot the instance to recover a stuck port.
