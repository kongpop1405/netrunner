# netrunner project conventions

## Progress reporting & commits

- งานสำเร็จหรือคืบหน้าระหว่างทาง (live-test ผ่าน, bug fix verify แล้ว, feature เสร็จบางส่วน) → **รายงานให้ user ทราบทันที** ไม่ต้องรอจบ session
- Commit เป็นระยะตามงานที่เสร็จจริง (ไม่รวบทุกอย่างเป็น 1 commit ท้าย session) — 1 commit = 1 fix/feature ที่ verify แล้ว
- **Stage เฉพาะไฟล์ของ scope งานตัวเองเท่านั้น** — ถ้า repo มี unrelated changes ค้างอยู่ (จาก branch/session อื่นที่ปนเข้ามาในดัชนี) ห้าม `git add -A`/`git add .` เหมารวม ใช้ `git add <path เฉพาะไฟล์ของงานนี้>` เสมอ ปล่อยไฟล์อื่นไว้ตามเดิมให้ session ที่เป็นเจ้าของจัดการเอง
- **`git status --short` หลัง stage ทุกครั้งก่อน commit** — ระบุไฟล์ตรง ๆ ก็ยังกวาดของคนอื่นได้ ถ้าไฟล์นั้นมี diff จากงานอื่นปนอยู่. พลาดมาแล้ว: `git add docs/RUN.md` เข้า commit ที่เป็น docs ล้วน แต่ diff ของมันคือเอกสารของ boost fix คนละก้อน — ต้อง `git restore --staged` ออก. เช็ค `git diff --cached --stat` ว่าทุกไฟล์ที่ staged เป็นของ scope นี้จริงก่อนเขียน message

## แก้/เพิ่ม CLI flag ใน tools/*.py — ต้องเช็ค caller ทุกตัวด้วยเสมอ

เมื่อเพิ่ม/แก้ argparse flag ใน `tools/run_toggle.py`, `tools/run_episode_loop.py` หรือ script อื่นที่มี `.bat` launcher เรียกใช้ — **ห้ามถือว่างานจบแค่แก้ `.py`**:

- `grep -rl "<script name>" launchers/` หา `.bat` ทุกตัวที่เรียก script นั้นก่อนปิดงาน
- เช็คแต่ละ `.bat` ว่า flag ใหม่ต้อง (a) เพิ่ม prompt ให้ user เลือก หรือ (b) ปล่อยเป็น default เงียบๆ ตาม CLI default ก็พอ — ถามถ้าไม่ชัด
- พลาดมาแล้ว: เพิ่ม `--relic-mode` เข้า `run_toggle.py` แล้วไม่ได้แก้ `launchers/boxrun_toggle.bat` — user รัน `.bat` ไม่เห็น prompt relic เลยเพราะ `.bat` เขียนก่อน flag นี้มีอยู่ และไม่ได้ pass flag นี้ไปให้ python เลย
- Launcher คนละตัวที่ไม่ได้เรียก script ที่แก้ (เช่น `boxrun_magnet.bat`/`boxrun_default.bat` ไม่เรียก `run_toggle.py`) — ไม่ต้องแตะ
- **ลบ helper function (ไม่ใช่แค่ flag) ต้อง `grep -rn "<func_name>" tools/ tests/`** ก่อนปิดงาน — ไม่พอแค่ grep ชื่อ flag ใน `.bat`. พลาดจริง 2026-08-04: ลบ `_strip_relay`/`_is_relay` ออกจาก `run_toggle.py` (relay กลายเป็น always-on ไม่ต้อง strip แล้ว) แต่ `tools/run_episode_loop.py` `from tools.run_toggle import (..., _strip_relay, ...)` ตรงๆ — `pytest` collect error `ImportError` ทันที เพราะ module อื่น import symbol นั้นข้าม file, ไม่ใช่แค่เรียกผ่าน CLI. รันเทสต์ทั้ง suite (`pytest tests/ -q`) หลังลบ symbol เสมอ ไม่ใช่แค่เทสต์ของไฟล์ที่แก้

## Python override ที่ return ชื่อ state = ข้าม state ที่ splice เข้ามาใหม่

`BoxQuitRunner._run_actions` (และ subclass อื่นของ `Runner`) return ชื่อ state เพื่อ redirect การเดินของ FSM ได้ — **ชื่อที่ hardcode ตรงนั้นจะ bypass ทุก state ที่ถูกแทรกเข้ามาใน config ทีหลัง เงียบ ๆ**:

- เจอจริง 2026-08-04: แทรก relay poll ไว้หน้า `check_shop_after_run` (`check_box` → `relay_poll1_check_box` → `relay_poll2_check_box` → `check_shop_after_run`) แต่ `_run_actions` return `"check_shop_after_run"` ตรง ๆ ตอน "เห็นกล่องแล้วเล่นต่อ" — ซึ่งเป็น path ที่ใช้บ่อยที่สุด (`quit_after=0` = default) → poll ที่เพิ่งเพิ่มไม่เคยถูกเรียกในเคสนั้นเลย
- **Fix = อ่าน goto จาก config ไม่ใช่ตั้งชื่อเอง** — `_continue_run_target()` อ่าน `states["check_box"]["on_absent"]` แล้วคืน target จริง (รองรับทั้ง `{"goto": X}` และ list) + fallback ชื่อเดิมถ้าอ่านไม่ได้
- **กฎเดียวกับ `_PLAY_TAP_XY`** — ที่นั่นเคยพังเพราะ key ด้วยชื่อ state (`verify_no_enterleague`) แล้วมีคนแทรก `probe_relic` มารับ Play tap ต่อ. หลักคือ **"ใครถือ edge คนนั้นถือ routing"** — match ที่ action shape หรืออ่าน edge จาก config ไม่ใช่จำชื่อ state
- ก่อนแทรก state ใหม่กลาง chain → `grep -n '"<ชื่อ state ปลายทาง>"' tools/ src/` หา Python ที่อ้างชื่อนั้นตรง ๆ ด้วย ไม่ใช่แก้แค่ JSON

## Threshold ระดับ config ตัดผ่ากลาง cluster — วัดก่อนเชื่อ

`match_threshold` ตัวเดียวทั้ง config ใช้ไม่ได้กับ template ที่ **พื้นหลังเป็น gameplay สด** — score แกว่งตามฉาก (coin rain / BONUSTIME / ดาว) จน threshold ตัดผ่ากลางกอง "เจอจริง" แล้วได้ผลแบบสุ่มหัวก้อย:

- เจอจริง 2026-08-04: `relay_prompt2_marker.png` (crop ข้อความ "Tap to activate Cookie Relay Boost!" — ตัวหนังสือขาวบนพื้นเกม) score ตอน prompt โผล่จริง = **0.73-0.87** ส่วนตอนไม่มี prompt ≤ **0.464**. `match_threshold` 0.82 อยู่กลางกองแรก → live 11 hit ผ่านแค่ 2 (เสีย relay ~4 ใน 5) และไม่มี error ให้เห็น มีแต่ DEBUG score line
- **วิธีวัด**: เก็บเฟรมจริงหลายสิบเฟรม (`adb exec-out screencap -p`, ผ่าน Bash ไม่ใช่ PS — BOM) → `cv2.matchTemplate` + `minMaxLoc` ทุกเฟรม → **แยกกลุ่มด้วยตาว่าเฟรมไหน prompt โผล่จริง** (เปิดรูปดู ไม่ใช่เดาจาก score) → sweep threshold ดู true-positive/false-positive ต่อค่า
- **ตั้ง per-state `"threshold"`** (validator รับ `0 < thr <= 1`, `src/fsm.py` อ่าน `spec.get("threshold", cfg.match_threshold)`) ให้อยู่ **ในช่อง gap ระหว่าง 2 cluster** ไม่ใช่ชิดขอบใดขอบหนึ่ง
- **template ที่พื้นหลังคงที่ไม่ต้องลด** — stage 1 (`Continue` pill สีเขียวอิ่ม) ไม่เคยเกิน 0.40 ทั้ง 83 เฟรม เก็บ global 0.82 ไว้ ลดไปมีแต่เปิดช่อง false positive
- **crop ที่เป็นตัวหนังสือล้วน = เสี่ยงสุด** — ถ้าเลือกได้ crop เอา UI element ที่มีสี/รูปทรงเฉพาะ (ปุ่ม, กรอบ, ไอคอน) ดีกว่าข้อความ

## Poll ที่รอ UI window สั้น — ต้องครอบทุกจุดที่ FSM แวะ

UI ที่โผล่ ~2-3 วิ (relay prompt) จะพลาดถ้า state ที่ตรวจมันแขวนอยู่แค่ chain เดียว — **FSM ใช้เวลาส่วนใหญ่อยู่นอก chain นั้น**:

- เจอจริง: relay chain แขวนแค่ hop state (`jump_2/3/4`, `guard_not_inactive`) แต่มี 2 ช่วงที่ไม่มีใครตรวจเลย — (1) `running` → guard chain ยาว 8 state ก่อนถึง hop (2) `check_box` absent → ออกจาก run phase (`check_shop_after_run` → `probe_boostshop` → …). live: 5 จาก 11 hit จับได้ที่ `relay_poll2_running` ที่เพิ่งเพิ่ม = hop chain เดิมพลาดไป 45%
- **หา gap ด้วยการไล่ graph** ไม่ใช่เดา: state ไหน `goto` ไปไหน แล้วนับว่าตั้งแต่จุดที่ UI อาจโผล่ ถึง state ที่ตรวจมัน ห่างกันกี่ hop × poll_ms
- Poll state ใหม่ต้องมี **fresh-frame wait บน absent path** ทุกตัว (ดู section "State ที่มีแต่ `goto`") ไม่งั้น stage 2 ตัดสินจาก frame ของ stage 1
- **Prompt ที่คิดว่าโผล่ตอนตายอาจโผล่กลาง run** — relay prompt live-confirmed ว่าโผล่ตอน `result_marker` ยัง 0.32-0.47 (ยังวิ่งอยู่) ตรงข้ามกับที่ `_note` เดิมเขียนว่า "on death". อย่าออกแบบ poll จาก assumption ว่า UI โผล่เฉพาะ state ไหน — วัดจาก log จริง

## adb ยิงขนานกับ bot = `PermissionError: [WinError 5]`

Capture loop ที่ยิง `adb exec-out screencap` ทุก 2 วิ พร้อมกับ bot ที่กำลังรัน → bot crash ตอน spawn adb subprocess (`_winapi.CreateProcess` → `Access is denied`). **ห้าม capture ขนานกับ bot** — ถ้าต้องเก็บเฟรมให้ (ก) เก็บก่อน/หลังรัน หรือ (ข) ให้ bot เก็บเอง (`reveal_snap_dir` pattern) หรือ (ค) รัน capture รอบแยกที่ไม่มี bot. Crash แบบนี้ไม่ใช่บั๊กของ config/patch — เช็คก่อนว่ามี process อื่นแย่ง adb อยู่มั้ยก่อนไล่ debug ผิดทาง

## `.bat` หา repo root เอง — ย้ายไฟล์ได้อิสระ ไม่ต้องแก้ `cd`

ทุก launcher (16 ไฟล์ รวม `install.bat`) เริ่มด้วย **root finder** ที่ไต่ขึ้นจากที่อยู่ของตัวเองจนเจอ `main.py` แทนการนับ `..` (2026-08-06):

```batch
set "ROOT=%~dp0"
:findroot
if exist "%ROOT%main.py" goto gotroot
set "PREV=%ROOT%"
for %%I in ("%ROOT%..") do set "ROOT=%%~fI\"
if "%ROOT%"=="%PREV%" goto noroot
goto findroot
:noroot
echo   [X] Could not find the project root ^(no main.py above "%~dp0"^).
pause
exit /b 1
:gotroot
cd /d "%ROOT%"
```

- **ย้าย `.bat` ไปโฟลเดอร์ไหนก็ได้ในโปรเจกต์ ไม่ต้องแก้อะไรข้างใน** — นี่คือเหตุผลที่เปลี่ยนมาใช้: `cd /d "%~dp0..\.."` แบบเดิมผูกกับความลึก ย้ายทีไรลืมนับใหม่ทุกที **พังเงียบ 3 รอบใน repo นี้** (commit `45e2b1b`, `87f7d91`, และ promote ตอน `15aa842`) เจอตอน user ดับเบิลคลิกเท่านั้น เพราะ `lint_config.py` อ่านแต่ JSON และ unit test ไม่แตะ `.bat`
- **`if "%ROOT%"=="%PREV%"` คือ guard กันวน infinite** — ที่ drive root `cd ..` ไม่เปลี่ยน path อีก ต้องหยุด. ห้ามตัดบรรทัดนี้ออก
- **`for %%I in ("%ROOT%..") do set "ROOT=%%~fI\"`** — `%%~fI` ทำ path ให้เป็น absolute+normalize (ไม่เหลือ `..` ซ้อน). ต่อ `\` ท้ายเสมอ เพราะ `%ROOT%main.py` ต่อสายตรง
- **path หลัง `cd` ต้องเขียนจาก repo root เสมอ** — `--config config/cookierun/x.json`, `%PY% tools\run_toggle.py`. ไฟล์ใน `_archive/` ก็ใช้ path เต็มจาก root (`config\cookierun\_archive\tools\...`) ไม่ใช่ relative จากที่ `.bat` ตั้ง

### Verify launcher — รันจริง อย่าอ่าน pattern

Checker ที่ตรวจ "จำนวน `..` ตรงความลึกมั้ย" **หมดความหมายแล้ว**. สิ่งที่ยังต้องพิสูจน์คือ *ผลลัพธ์* — เลยต้องรัน `.bat` จริง:

- สร้าง **stub** จากไฟล์จริง: แทนบรรทัด `%PY% ...` ด้วย `echo NETRUNNER_CWD=%CD%`, comment `pause` ออก, แล้ว `subprocess.run(["cmd","/c",stub])` → CWD ต้องเป็น repo root
- **copy stub ไปวางอีกชั้นด้วย** (เช่น `docs/flow/`) แล้วรันซ้ำ — พิสูจน์ว่า "ย้ายได้จริง" ไม่ใช่แค่เชื่อ
- เช็คต่อว่า **ทุก `--config` / `.py` ที่ไฟล์อ้างถึง resolve ได้จาก CWD นั้น** ไม่ใช่แค่ landed root
- **Stub ต้องตอบ `set /p` ด้วยค่าที่ผ่าน validate** ไม่ใช่ปล่อยว่าง (ไม่งั้น `findstr` วนถามซ้ำ → timeout):
  - repo นี้มี **2 syntax**: `set /p "VAR=prompt"` และ `set /p VAR="prompt"` — regex ต้องครอบทั้งคู่
  - prompt แบบ `How many ...?` validate ว่าเป็น **positive** whole number → ตอบ `1` (`0` ไม่ผ่าน) · picker แบบ `0=none 1=magnet` → `0` · y/n → `y`
- ตั้ง `timeout` ต่อ stub (20s พอ) + ลบ stub ใน `finally` — stub ที่ค้างเพราะ timeout จะโผล่ใน `git status` รอบถัดไป
- Doc ที่อ้างพฤติกรรม launcher (`docs/flow/COMPARE_bots.html`, `launchers/*/README.md`) ต้องแก้ในคอมมิตเดียวกัน

## Branching

เมื่อเริ่มงานใหม่หรือ session ใหม่ และสรุปปัญหา/scope ได้แล้ว **ถ้าต้องแก้โค้ด ให้สร้าง branch ใหม่ก่อนแก้เสมอ**:

| สถานการณ์ | สร้าง branch จาก |
|---|---|
| งานใหม่/feature ใหม่ (ไม่เกี่ยวกับสิ่งที่ทำค้างอยู่) | `main` |
| งานแทรกเข้ามาระหว่าง session เดิมกำลังทำ (bug ที่เจอกลางทาง, ฟีเจอร์ย่อยที่ต่อยอด) | branch ของ session นั้นที่กำลังทำอยู่ |

- อย่าแก้โค้ดบน `main` ตรง ๆ
- ถ้าไม่แน่ใจว่างานนี้ "ใหม่" หรือ "แทรกใน session เดิม" ให้ถามก่อนสร้าง branch

### เช็ค branch เก่าก่อนสร้างใหม่

ก่อนสร้าง branch ใหม่ทุกครั้ง (ไม่ว่ากรณีไหนในตารางข้างบน) — เช็คก่อนว่ามี branch ที่มีอยู่แล้ว (`git branch -a`) ตรง scope งานนี้ไหม:

- ถ้ามี branch เดิมที่ยังทำงานเรื่องเดียวกัน/ต่อยอดกันได้ → **เสนอสลับไปทำงานต่อบน branch นั้นแทนสร้างใหม่**
- ไม่ใช่แค่เช็คชื่อ branch ปัจจุบันเฉย ๆ — ต้อง list branch อื่นด้วยว่ามีอันที่ตรงกว่าไหม ก่อนตัดสินใจสร้างใหม่หรือถาม user
- ถ้าไม่มี branch เดิมที่ตรง → ทำตามตารางด้านบน (งานใหม่จาก main / งานแทรกจาก branch ปัจจุบัน)

### Tag ก่อนแตก branch

ก่อนแตก branch ใหม่จาก `main` ทุกครั้ง: เช็คว่า `main` ที่จุดนี้มี tag กำกับไว้หรือยัง (`git tag --points-at main`) — ถ้ายังไม่มี ให้ติด tag ก่อนแตก branch เสมอ

**Pattern:** `0.<n>.<x>-<short-feature-slug>` (ไม่มี `v` นำหน้า, ตัวคั่นคือ `-` ไม่ใช่ `_`)

- **x** คือค่า default ที่เพิ่มแทบทุกครั้ง — branch ใหม่ทั่วไป, งานแทรกใน session เดิม, bug fix ย่อย, ต่อยอด feature เดิม
- **n** เพิ่ม**เฉพาะ**การเปลี่ยนแปลงใหญ่จริง ๆ เท่านั้น (เช่น restructure ครั้งใหญ่, breaking change, milestone หลักของ project) — ไม่ใช่แค่ "feature ใหม่" ทั่วไป. เมื่อ n เพิ่ม ให้ reset x เป็น 0
- **ตัดสิน n จาก impact เชิงเนื้อหาเท่านั้น** — ห้ามใช้ diff size (บรรทัด/ไฟล์ที่เปลี่ยน) หรือจำนวน commit ระหว่าง tag เป็นเกณฑ์ตรง ๆ ทั้งคู่ทำให้เข้าใจผิดได้ (merge commit ที่รวมหลาย branch อาจมี commit-count เยอะทั้งที่เนื้อหาเป็นแค่ doc reorg; หรือ commit เดียวที่ diff น้อยแต่เปลี่ยน architecture ทั้งระบบ) — อ่าน commit message + diff จริงในช่วงนั้นแล้วถามว่า "นี่คือจุดเปลี่ยนสถานะ project จริงไหม" (เช่น prototype → usable tool) ก่อนตัดสิน ไม่ใช่นับตัวเลขเฉย ๆ

```
0.1.0-episode-loop
0.1.1-episode-loop-retry-fix
0.1.2-relic-stop-mode
0.1.3-relic-tap-template
0.1.4-auto-detect-ep
0.2.0-major-restructure     ← ตัวอย่าง n เพิ่ม: เปลี่ยนแปลงใหญ่จริง ๆ เท่านั้น
```

ดูตัวล่าสุดด้วย `git tag -l "0.*" --sort=-v:refname`

**⚠️ Slug ต้องตั้งชื่อตามงานที่อยู่บน `main` ณ จุดนั้นจริง ๆ (ดู `git log main -1`), ไม่ใช่งานที่กำลังจะทำต่อบน branch ใหม่** — พลาดจริงมาแล้ว 2026-08-01: กำลังจะทำ bot `sendlife-mailbox` แล้วตั้ง tag เป็น `0.1.0-sendlife-mailbox` ทั้งที่งานนั้นยังไม่ merge เข้า main เลย ต้องแก้เป็น `0.1.0-project-conventions` (ตรงกับ commit ล่าสุดจริงบน main ตอนนั้น). วิธีเช็คไม่ให้พลาด: อ่าน commit message ล่าสุดของ `main` มาตั้งชื่อ tag ก่อนเสมอ ไม่ใช่เอาจาก task ที่กำลังคุยอยู่ในหัว

**เมื่อสลับ branch (`git checkout -b <new> main`) จาก branch ที่มี unrelated staged/modified changes ค้างอยู่** (เช่นจาก session อื่นที่ทำ reorg/refactor คนละเรื่อง): git ไม่ auto-clean tracked-file changes ให้ — state พวกนั้นติดตามมาที่ branch ใหม่ด้วย (เจอจริง 2026-08-01, plan-file-move staged changes จาก `chore/reorg-folders` ติดมาที่ `feature/sendlife-mailbox`). แก้ด้วย `git restore --staged <path เฉพาะที่ไม่ใช่ของงานนี้>` เพื่อ unstage ออกจาก index — **ไม่ใช้ `--worktree`/`reset --hard`** เพราะ permission classifier บล็อก destructive discard; `git restore --staged` (ไม่มี `--worktree`) ไม่แตะ working tree เนื้อไฟล์ ปลอดภัยและผ่านได้

## Stash pop ข้าม branch — ต้อง verify content เสมอ

`git stash push` แล้ว checkout ไป branch อื่น แล้ว `git stash pop` — ไฟล์ที่ถูกสร้างใหม่บน branch ที่ stash ไว้ (ยังไม่เคย commit บน branch ปลายทาง) เสี่ยง**เนื้อหาหายเงียบ**ถ้า pop ไปคนละรอบ/คนละ branch ที่ diff กันเยอะ (เจอจริง 2026-08-01: `CLAUDE.md` หาย 2 section หลัง stash pop ข้าม branch, ไม่มี error/conflict message เตือนเลย):

- หลัง `stash pop` ทุกครั้งที่ข้าม branch — **grep หา section/keyword ที่คาดว่าต้องอยู่** ก่อน commit เสมอ ไม่เชื่อแค่ "pop สำเร็จไม่มี error"
- ถ้าพบว่าหาย — เช็คว่าเนื้อหานั้นมาจาก commit ไหน (`git log --all -- <file>`) แล้วกู้กลับผ่าน `git show <commit>:<file>` หรือ cherry-pick ส่วนที่หาย ไม่ใช่พิมพ์จำจากบทสนทนา
- ป้องกันไว้ก่อน: ถ้ารู้ตัวว่าจะสลับ branch ระหว่างมี uncommitted work — commit ให้เสร็จก่อนสลับดีกว่า stash ข้าม branch เมื่อเป็นไปได้

## Merge เข้า main — ห้ามทำเอง

**การ merge เข้า `main` เป็นสิทธิ์ user เท่านั้น** ไม่ว่ากรณีใด:

- ห้าม `git merge` เข้า `main` เอง แม้เป็น fast-forward ที่ไม่มี conflict
- ห้าม `git checkout main` แล้ว merge branch อื่นเข้ามาโดยไม่ขอก่อน
- เตรียม branch/commit ให้พร้อม แล้ว**เสนอ** user ให้ merge เอง หรือขอ confirm ก่อนทำแทน — อย่าตัดสินใจ merge เงียบ ๆ ระหว่างทำงาน แม้จะดูเป็นงานเล็กหรือไม่มีความเสี่ยงทางเทคนิคก็ตาม
- **หลัง merge เข้า `main` สำเร็จ (ไม่ว่าใครทำ) → เช็ค `git tag --points-at main` ทันทีในเทิร์นถัดไปที่แตะ repo นี้** ก่อนทำอะไรอื่น ถ้าไม่มี tag ที่จุด merge นั้น ให้ tag ตาม pattern เดิม (สล็อกจาก commit message ล่าสุดจริงบน main ตอนนั้น) แล้วถาม user ก่อน push — **อย่ารอจนกว่าจะมี "งานถัดไป" มาเจอเองเหมือนที่พลาดมาแล้ว 2026-08-08**: `main` เดินหน้าไป 28 commits ข้ามหลายวัน (2-8 ส.ค., รวม merge จาก `feature/cookie-relay-chain`) โดยไม่มี tag กำกับเลย เพราะไม่มี session ไหนกลับมาเช็คหลัง merge จนกว่าจะบังเอิญเจอตอน commit อื่นที่ไม่เกี่ยวกัน — ทุก merge คือจุดที่ต้อง tag-check ทันที ไม่ใช่แค่ตอนจะแตก branch ใหม่

## Livelock ที่ log อ่านเหมือนปกติ — จอที่ไม่มี marker เลย

Bot ค้างได้แบบที่ **log ไหลลื่นทุกบรรทัด** ไม่มี error ไม่มี warning — เกิดเมื่อจออยู่บนหน้าที่**ไม่มี template ในทุก config**: ทุก state miss แล้ว fall through, guard chain กับ relay poll transition ตามปกติ, jump/slide ยิงลงเมนูแทนตัวเกม (เจอจริง 2026-08-06: หน้า Party Run "Select a Mode" ค้างเป็นชั่วโมง)

- **`progress_watchdog` จับได้แต่ช้า** — transition ยังเกิดต่อเนื่อง (watchdog นับ "ไม่มี progress state" ไม่ใช่ "ไม่มี transition") จึงต้องรอครบ `no_progress_s` 300s = ยิง tap มั่ว 40-100 ครั้งก่อนกู้. **`_BLIND_LAP_CYCLES` (fsm.py, 160) ตัดเร็วกว่า** ด้วยตัวชี้วัดที่ไม่ผูกเวลา: นับ poll ที่ **ไม่ match อะไรเลย ข้าม state** (`absent_streak` reset ทุก transition จึงมองวง 30 states ไม่เห็น)
- **สงสัยเมื่อไร**: log วน guard chain ซ้ำ ๆ นานผิดปกติโดยไม่มี `run_result`/`check_box` โผล่เลย → **snap จอทันที** ไม่ต้องรออ่าน log ต่อ (ดู section "Snap ก่อนแตะจอเสมอ")
- **แก้แบบถาวร** = crop marker ของหน้านั้น + เพิ่ม `guard_not_<x>` เข้า guard chain ที่ปิดมันได้ ไม่ใช่แค่เคลียร์มือครั้งเดียว
- **หา entry point ด้วย** — จอนั้นเปิดมาได้ยังไง. เจอจริง: `probe_friendinfo` ยิง 2 tap ติดกันก่อน re-check แล้ว tap ที่ 2 ตกลง home ตรงแถบ Party Run พอดี. **Blind tap ชุดติดกัน = ต้องเหลือ tap เดียวต่อ pass แล้วให้ self-loop ตรวจซ้ำ** ไม่ใช่ยิงรวดแล้วเช็คทีหลัง
- **Guard ต้องอยู่ก่อน blind action ที่มันกัน** — ไม่ใช่แค่ "มีอยู่ใน config". guard ที่วางหลัง blind tap = ยิงบนจอที่ tap นั้นเพิ่งเปิด. ตรวจด้วยการไล่ absent chain จาก `start_state` แล้วดูว่า guard อยู่ก่อนทุก tap ในโซนอันตราย (`tests/test_popup.py::TestGuardParity`)
- **Config ที่รันบนจอเดียวกันต้องมี guard ชุดเดียวกัน** — guard ที่มีใน 8 config แต่ไม่มีใน errand config = ย้ายว่า launcher ตัวไหนค้าง ไม่ได้แก้. เจอจริง: `addfriend` ยิง `(1640,107)` บน **absent path** (ยิงตอนไม่รู้ว่าจออะไร) ห่างจากพิกัดที่เปิด Party Run 7px และไม่มี watchdog เลย — จบเมื่อ `--max-cycles` หมดเท่านั้น

## วัดพิกัดปุ่มต้องวัดบนหน้าที่จะปิดจริง ไม่ใช่หน้าที่หน้าตาคล้าย

Dialog คนละหน้ามีปุ่ม X คนละที่ — **ปุ่มใน dialog header** (Friend's Info: 1637,108) กับ **ปุ่มมุมขวาบนของจอ** (Party Run: 1820,135) ห่างกัน 180px. เอาพิกัดจากหน้าหนึ่งไปใช้กับอีกหน้า = tap ลงพื้นหลังเปล่า

**Dialog ซ้อนชั้นก็เลื่อนปุ่มด้วย** — วัดจากเฟรมชั้นเดียวแล้วใช้กับเฟรมซ้อน = ผิดอีกแบบ. เจอจริง 2026-08-06: "Friend's Info" ชั้นเดียวปิดที่ `(1633,107)` (0.974 → 0.343 tap เดียว) แต่เมื่อ "Friend's Cookie" ซ้อนทับ ปุ่มชั้นในย้ายไป `~(1555,125)` และ `(1633,107)` กลายเป็น BGR(85,85,85) = **เงาใต้การ์ด**. Retry พิกัดเดียวไม่เคลียร์ 2 ชั้นได้เท่าไรก็ตาม — แต่ `close_popup` ไม่ค้าง: warn แล้วส่งต่อ, pass ถัดไปเก็บชั้นที่เหลือ

- เจอจริง 2026-08-06: guard ที่เขียนใหม่ detect หน้า Party Run ถูก (score 1.00) แต่ tap พิกัดที่วัดจาก Friend's Info → **tap 38 pass ติดกันไม่ปิดเลย** = livelock ซ้อนใน guard ที่เขียนมาแก้ livelock. `(1638,108)` บนเฟรม Party Run คือ BGR (93,53,51) พื้นหลังมืด
- **วิธีวัด**: หา blob วงกลมเทาบนเฟรม**ของหน้านั้น** — `hsv[:,:,1] < 70` (สีจาง) + `hsv[:,:,2] > 140` (สว่าง) → `findContours` → เอา contour ใหญ่สุด → center ของ bbox. เช็คด้วยว่า `frame[y,x]` ที่จุดนั้นเป็นสีขาว/เทาจริง
- **ยืนยันด้วย live tap ก่อนเขียนลง config** — tap แล้ว re-score marker ต้องตกจาก 1.00 ลงต่ำกว่า threshold. ถ้าไม่ตก พิกัดผิด

## Threshold ที่ derive จากโครงโค้ด vs วัดจากพฤติกรรมจริง

เลขที่คิดจาก "จำนวน state × 1.5" อ่านดูมีเหตุผลแต่ไม่ได้อ้างอิงอะไรจริง. `_BLIND_LAP_CYCLES` ตั้ง 48 (32 states × 1.5) แล้ว **ยิงกลาง run จริง**: healthy run วัดได้ **70 poll ติดกันที่ไม่ match อะไรเลย** เพราะ `home` → probe 10 ตัว → `boost_shop` → in-run jump chain **ไม่ match โดยดีไซน์** (jump chain เดินบน absent edge ล้วน). Recovery กลาง run = เสียหัวใจ + run 7.3M คะแนนทิ้ง = แย่กว่าอาการที่จะแก้

- **วัด baseline ของ "ปกติ" ก่อนตั้งเส้น** — รัน `-v` แล้วนับ streak จาก `found=False` ใน debug log ไม่ใช่เดาจากขนาดตาราง state
- **ต้องมี 2 ตัวเลข**: ปกติสูงสุด (70) กับ อาการจริง (Events popup 229) → เส้นอยู่กลาง (160 = headroom 2.3×)
- **ล็อกด้วยเทสที่อ้างตัวเลขที่วัด** (`test_the_blind_threshold_clears_a_healthy_run`) ไม่ใช่ assert ค่าคงที่เปล่า ๆ — คนหลังจะเห็นว่าเลขมาจากไหนและต้องเถียงกับการวัด
- **Detector ทุกตัวต้องได้ grace ตอน recovery ทำงาน** — `_RECOVERY_GRACE_S` ดัน `last_progress_at` ไปอนาคต ซึ่งปิดปาก wall-clock แต่ไม่แตะ streak. restart+relogin poll ~99s โดยไม่ match อะไร → streak ทะลุเส้น → ยิง recovery ซ้อน recovery ที่ยังทำงานอยู่

## Action ที่ปิด popup ต้อง verify — ไม่ใช่เพราะ retry แต่เพราะ log

`close_popup` + `verify` ต่างจาก `tap_xy` + `goto` ตัวเอง ที่ **observability** ก่อนเรื่อง retry: มัน re-read เฟรมหลัง settle แล้ว `log.warning` เมื่อปิดไม่ลง. `tap_xy` + self-loop ยิงเดา ไม่รู้ผล **ไม่มี log** — พิกัดผิดกับปิดสำเร็จอ่านเหมือนกันเป๊ะ

- นี่คือเหตุผลที่ Party Run guard ยิง 38 pass เงียบ ๆ ได้: guard **detect ถูก** แต่ปิดไม่ลงและไม่มีใครรู้
- **Guard/probe ทุกตัวที่ tap แล้ว goto ตัวเอง ต้องใช้ `close_popup`** เว้นแต่มี `match_timeout_ms` กั้น (เช่น `mb_open` ที่ยิง 3 จุดคนละหน้าที่ = flow ไม่ใช่ guard)
- ตรงกับกฎ "log ระดับ DEBUG ที่ไม่มีใครอ่าน = บั๊กซ่อนได้นาน" — action ที่เงียบตอนพังคือ action ที่ซ่อนบั๊กได้เป็นชั่วโมง
- **ข้อยกเว้น: popup ที่ "อาจมีหรือไม่มี" ห้ามใช้ `close_popup`** — `close_popup`'s `verify` ตั้งสมมติฐานว่า popup มีอยู่แน่นอน แค่เช็คว่าปิดสำเร็จไหม ถ้าจริงๆ ไม่มี popup เลย (เช่น boost mode ที่ข้าม shop chain ทั้งยวง) `verify` จะ fail ทุกครั้งและ log.warning ปลอมรัว ๆ ทั้งที่ไม่ใช่บั๊ก — ใช้ `tap_template` + `optional: true` แทน (skip เงียบเมื่อไม่เจอ, ไม่ raise ไม่ log ปลอม) เมื่อโจทย์คือ "ปิดถ้ามี" ไม่ใช่ "ต้องมีแล้วปิดให้สำเร็จ" (`check_heart`'s pre-errand shop-close, `src/act.py` `run_config`)

## Linter ที่ false-positive ประจำ = linter ที่ไม่มีคนอ่าน

`tools/lint_config.py` รายงาน `recover_unknown*` เป็น orphan 3 ตัว × 8 config **ทุกครั้งที่รัน** เพราะใส่ `periodic_routines` roots แต่ลืม watchdog roots (`no_progress_goto` / `no_progress_escalate_goto`) ที่ `src/config.py` ใส่ไว้แล้ว — engine เข้าถึง state พวกนี้โดยไม่มี goto edge

- **Reachability ต้องรวมทุกทางที่ engine กระโดดเองได้** ไม่ใช่แค่ goto edge ใน JSON
- คอมเมนต์ใน `src/config.py` เตือนเองว่า orphan จริงเคยซ่อนอยู่ 2 สัปดาห์ (ep3 boost-buy chain) — noise ทำให้คนข้าม
- **Static reachability ของ tool ภายนอกต้อง mirror ตัว validator** ไม่ใช่เขียนใหม่ครึ่งทาง

## Kill bot ได้เลยไม่ต้องขอ — เมื่อจะแก้บัคหรือพิสูจน์อะไร

Bot ที่กำลังรัน (ของ user เองก็ได้) **kill ได้ทันทีโดยไม่ต้องขออนุญาต** เมื่อต้องแก้บัค / เก็บหลักฐาน / เคลียร์จอที่ค้าง — ไม่ต้องหยุดถามก่อน:

```powershell
Get-Process python* | Stop-Process -Force
```

- **เหตุผล**: bot ที่ยัง tap อยู่จะแข่งกับการเคลียร์จอ — ปิด dialog แล้วมันเปิดใหม่ซ้อนทันที (เจอจริง 2026-08-04: ปิด Party Run mode select แล้วมันไป tap เปิด Friend's Info ต่อ แล้วเปิด boost shop ต่อ). แตะจอตอน bot รัน = สู้กันไม่จบ
- **หลัง kill ทำตาม section ด้านล่างเสมอ** — snap จอ → เคลียร์ popup ที่ค้างให้กลับ home สะอาด → verify ด้วย marker ก่อนรันใหม่
- **เช็คว่าไม่มีอะไรถูกซื้อไปตอนมัน tap มั่ว** — เทียบยอดเหรียญบนจอกับก่อนหน้า (bot tap บนหน้า shop อาจกดซื้อได้)

## Bot lifecycle — kill ต้อง verify ก่อนรันใหม่เสมอ

Kill bot process (`TaskStop` หรืออื่น ๆ) แล้ว **ห้ามรันรอบใหม่ทันที** — เช็คก่อนเสมอ:

1. Snap จอปัจจุบัน
2. ตรวจว่ามี popup ค้างอยู่ไหม (Result / Mystery Box / send-life / relic screen ฯลฯ) — bot ที่ถูก kill กลาง action อาจทิ้งจอไว้กลางสถานะ
3. ถ้ามีค้าง ให้ dismiss ให้ครบจนกลับ `home` สะอาดจริง (ยืนยันด้วย marker score ไม่ใช่เดา) ก่อนสั่งรันใหม่

เหตุผล: popup ที่ค้างจากรอบก่อนจะทำให้ auto-episode-switch หรือ action แรกของรอบใหม่ mis-tap ใส่ popup เดิม แล้วดูเหมือน bug ใหม่ทั้งที่จริงคือสถานะค้างจากรอบที่แล้ว

## แก้ config JSON — ผ่าน json module เท่านั้น

**ห้ามแก้ `config/**/*.json` ด้วย string replace/sed มือเปล่า** แม้เป็นการแก้แค่ 1 บรรทัด (เช่นแก้ `_note`):

- ใช้ `json.load()` → แก้ค่าใน object → `json.dump()` เสมอ — escape ถูกต้องอัตโนมัติ กัน unescaped quote ทำ JSON พังทั้งไฟล์
- หลังแก้ทุกครั้ง ต้อง `json.load()` ยืนยันไฟล์ parse ผ่านจริง ก่อน commit
- ถ้าจำเป็นต้อง string-replace จริง ๆ (เช่นแก้ comment/note ที่ยาวมาก) ต้อง verify JSON valid ทันทีหลังแก้ ก่อนทำอย่างอื่นต่อ

## `absent_wait_ms` ไม่รับ range เหมือน `wait.ms`

Engine validate ต่างกัน: `wait.ms` รับ `[min, max]` (random ใหม่ทุกครั้ง) แต่ **`absent_wait_ms` ต้องเป็น fixed positive integer เท่านั้น** — ใส่ range แล้ว `tools/lint_config.py` reject ตอน load (`'absent_wait_ms' must be a positive integer (ms)`). อย่าสมมติว่า timing field ทุกตัวใน config schema รับ range แบบเดียวกันหมด เช็ค README/lint ก่อนถ้าไม่ชัวร์

## Dialog/popup marker ต้อง test ทุก content variant ก่อนเชื่อ

Marker ที่ crop จาก text บรรทัดเดียว **อาจ match แค่บาง instance ของ popup เดียวกัน** ถ้าเนื้อหาบางบรรทัดเป็น optional/conditional — พลาดจริง 2026-08-01: OvenBreak mailbox send-life dialog บาง friend มีบรรทัด "(+3 Gift Points)" บางคนไม่มี, marker ที่ crop เฉพาะบรรทัดนั้น score 0.42 (absent) บน friend ที่ไม่มีบรรทัดนี้ → bot สรุปผิดว่า list หมดทั้งที่ dialog เปิดค้างอยู่จริง (0 sends ทั้ง run แรก)

- **แก้แบบยั่งยืน**: หา element ที่ "คงที่ทุก variant" ของ popup เดียวกันมา crop แทน — ในเคสนี้คือ Cancel+Confirm button row (ไม่มีชื่อ ไม่มี conditional text ติด, score 1.000 ทั้ง 2 variant)
- **ก่อนเชื่อ marker ว่าใช้ได้จริง**: อย่า verify กับ snap เดียว — ต้องเจอ instance ที่ต่างกันจริง (คนละชื่อ, คนละเนื้อหา optional) อย่างน้อย 2-3 แบบ แล้ว verify score ทุกแบบ ไม่ใช่แค่แบบแรกที่เจอ

## State ที่มีแต่ `goto` = frame ค้าง — chain ที่รอ UI ชั่วคราวจะไม่มีวันเห็น

Engine re-grab frame ใหม่เมื่อมี action จริงเกิดขึ้น (tap/wait) — **hop state ที่เหลือแต่ `goto` ล้วนจะวนบน frame เดิมที่ cache ไว้** จนกว่า pure-goto chain จะ revisit ครบทุก state (`src/fsm.py`, stale-frame goto-cycle guard). ผลคือ chain ที่รอ UI โผล่สั้น ๆ ไม่มีวันเห็นมัน

- เจอจริง 2026-08-04: `--jump n --slide n` ตัด action ออกจาก `jump_2`/`jump_3`/`jump_4`/`guard_not_inactive` จนเหลือแต่ goto → relay prompt (โผล่ ~2-3 วิ) เห็นแต่ frame ก่อนหน้า prompt ตลอด relay chain ไม่เคย fire เลย
- **`launchers/boxrun_toggle.bat` จึงตรึง `JUMPSLIDE=y`** ห้ามเปลี่ยนเป็น `n` — comment ในไฟล์อธิบายไว้แล้ว
- กฎทั่วไป: **ก่อนตัด action ออกจาก state ต้องเช็คว่า state นั้นยังเหลือสิ่งที่ทำให้ frame refresh มั้ย** ถ้าไม่เหลือ chain อื่นที่พึ่ง frame สดจะพังเงียบ ๆ ตามไปด้วย — ไม่มี error ให้เห็น มีแต่ "ไม่เคย match"
- ตรงข้ามกับ warm-up burst: `jump=n + slide=n` ยัง trigger burst ได้ (ยิง tap จริง) แต่ burst ยิงครั้งเดียวตอนต้น run ไม่ช่วย frame refresh ที่ hop หลังจากนั้น

## Blind action (ไม่มี template verify) — ต้องพิสูจน์ว่าปุ่มมีจริงก่อนเชื่อ

Action ที่ยิงพิกัดตายตัวโดยไม่ detect อะไรก่อน (`relay_tap`, `faststart_tap`, `tap_xy` ใน `on_absent`) **ไม่มีทางรายงานว่าตัวเองพัง** — log เขียน `act: tap (x,y)` เหมือนกันหมดไม่ว่าจะโดนปุ่มหรือโดนอากาศ. พลาดจริง 2026-08-03: `relay_tap(960,540)` อยู่ในทุก config มานาน แต่จุดนั้นเป็น **พื้นหลังเรียบล้วน** (texture 0.00% · std 2.5) — ไม่มีปุ่ม Cookie Relay ตรงนั้นเลย ทุก tap เป็น no-op เปล่ามาตลอด

- **วัดก่อนเชื่อ** — crop รอบพิกัดจาก snap จริงแล้ววัด: ปุ่มจริงมี texture (Canny edge density) สูง + สีอิ่ม, ที่ว่างได้ ~0% และ std ต่ำ. เทียบกับพิกัดที่รู้ว่าถูก (เช่นปุ่ม pause) เป็น control
- **หา UI ที่ "โผล่ ๆ หาย ๆ"** ด้วยการ sample หลายเฟรมแล้ววัด stillness (diff ระหว่างเฟรมติดกัน) — UI control นิ่งใกล้ 0, gameplay churn สูง (25+). ถ้าไม่มี cell ไหนนิ่งเลย = ไม่มีปุ่มในจอนั้นจริง
- **`_note` ที่บอกว่า "verified" อาจ verify คนละอย่าง** — ของจริงเคยมี note ว่า "(490,955) misread from a partner-count BADGE → restored (960,540) as originally verified" ทั้งที่**ผิดทั้งคู่** พิกัดหนึ่งเป็น indicator อีกพิกัดเป็นที่ว่าง
- **Prompt ที่โผล่สั้น ๆ ต้อง poll ถี่ระดับ hop** ไม่ใช่รอบละครั้ง (relay window ~2-3 วิ) และ **ทุก stage ต้องเข้าถึงตรงได้** เผื่อ stage ก่อนหน้าถูกกดไปแล้วโดยบังเอิญ (faststart spam กด Continue ให้เองบ่อย)
- **สอง stage ที่ข้อความเหมือนกัน ห้าม crop ข้อความ** — relay stage 1/2 ใช้ประโยคเดียวกันเป๊ะ crop text ได้ margin ≤0.05 (แยกไม่ออก) ต้อง crop **ปุ่มที่มีเฉพาะ stage นั้น** แทน (margin 0.65)

## Template path ที่ inject ตอนรัน — `lint_config.py` ไม่เห็น

`lint_config.py` อ่านแค่ JSON บน disk. Path ที่ `src/boost.py` (หรือ tool อื่น) **เขียนทับ `detect` ตอนรัน** ไม่เคยถูกตรวจ — พลาดจริง 2026-08-02: `PROFILES[*]["banner"]` เก็บชื่อไฟล์เปล่าไม่มี `boxrun/` และ tick template ขาด `giftdraw/` พังพร้อมกัน **ทั้ง 3 boost** โดย lint ผ่านหมด

- Config ทุกไฟล์อาจ path ถูก 100% แต่ยังพังได้ ถ้าโค้ดเขียน `detect`/`template` ทับตอนรัน
- **เช็คด้วยการ resolve จริง** — `TemplateStore.get()` ทุก path ที่ code ยิงเข้าไป ไม่ใช่แค่ที่อยู่ใน JSON:
  ```python
  for k, p in boostmod.PROFILES.items():
      if p.get('banner'): store.get(p['banner'])   # raises if missing
  ```
- อาการเวลาพัง = `PerceiveError: template not found` **กลาง run** ไม่ใช่ตอน load — ถ้ามี bug อื่นบังไม่ให้ไปถึง chain นั้น จะไม่มีใครเห็นเลย

## Bug ซ้อนกัน — แก้ทีละชั้นแล้ว live-test ซ้ำทุกชั้น

Bug ตัวแรกที่ทำให้ "ไปไม่ถึง" code path จะ **บัง bug ที่อยู่ข้างในทั้งหมด**. เจอจริง: `after_play` กด Play ซ้ำจนปิด shop → ไม่เคยเข้า buy chain → path bug (ข้อบน) กับ tick bug ไม่มีใครเห็นเลย ทั้งที่มีอยู่ทั้งคู่

- อย่าสรุปว่า "แก้เสร็จ" หลังแก้ชั้นเดียว — **รัน live ใหม่ทุกครั้งหลังแก้แต่ละชั้น** จนกว่าจะเห็น flow ที่ต้องการทำงานครบจริงบนจอ
- **หลักฐานที่ไม่ครอบคลุมช่วงเวลาที่เกิดเหตุ = ไม่ใช่หลักฐาน** — พลาด 3 รอบใน session เดียวเพราะสรุปจาก log/sample ที่ข้ามช่วงที่เหตุการณ์เกิด (poller sample 1.2s แล้วหยุดทันทีที่เห็น result marker → ข้าม relay prompt ที่โผล่ก่อนหน้านั้นพอดี)
- **User เห็นจอจริง เรามองผ่าน log** — ถ้า user ยืนยันว่าเห็นอะไรที่ log ไม่มี ให้เชื่อ user แล้วไปหาว่าทำไมเครื่องมือเราจับไม่ได้ อย่ายืนยันข้อสรุปเดิมจากหลักฐานชุดเดิม

## Config เดี่ยว ≠ toggle family — `apply_boost` ไม่ได้ inject ให้

Config ที่รันตรงผ่าน `main.py` (`boxrun_magnet` · `boxrun_speed` · `boxrun_relay` · `coinrun`) **ไม่มีใครเรียก `src/boost.py::apply_boost`** — สิ่งที่ toggle family ได้มาฟรีจาก `run_toggle.py` config เดี่ยวไม่ได้ ต้องเขียนลง JSON เอง

- เจอจริง: picker tick logic ถูก inject ให้เฉพาะ toggle family ส่วน config เดี่ยวพึ่งสมมติฐาน "boost ที่ต้องการติ๊กไว้อยู่แล้ว" — **แต่เกมจำ tick ข้าม session** พอ toggle run เปลี่ยน tick ไป config เดี่ยวก็ roll ผิดตัวแล้ววน `retry_buy` เผาเหรียญ
- แก้ bug ใน `src/boost.py` แล้ว **ต้องเช็คว่า config เดี่ยวได้ fix ตามด้วยหรือเปล่า** — ปกติไม่ได้ ต้อง patch JSON แยก (gen action จาก `boost.PICK`/`_toggle_action` แทน hardcode ซ้ำ)
- flag ของ `run_toggle.py` ที่ผูกกับโครงสร้าง config (`_strip_relay`, `_strip_faststart`) **ต้องแก้ตามเมื่อโครงเปลี่ยน** ไม่งั้น flag กลายเป็น no-op เงียบ ๆ (`--relay n` เคยลบ `relay_tap` — พอเปลี่ยนเป็น relay chain ต้องเปลี่ยนเป็น re-point goto แทน)

## Doc เขียนว่าอะไร ≠ ของจริง — รัน tool เช็คก่อนเชื่อ

Doc ในรีโปนี้ (`docs/HANDOFF.md`, `docs/RUN.md`, plan HTML) เขียนสถานะไว้ ณ วันที่เขียน แล้วโค้ดเดินต่อโดยไม่มีใครกลับมาอัพเดต — **ห้ามอ้าง claim ใน doc เป็นสถานะปัจจุบันโดยไม่ verify**:

- **⚠️ แก้ไปแล้ว 2026-08-06 — เก็บไว้เป็นตัวอย่างว่า doc ผิดได้ทั้งสองทาง**: doc เคยเขียนว่า lint รายงาน 3 unreachable (`recover_unknown`, `_probe`, `_restart`) แล้วสรุปต่อว่า "ทางกู้จึงไม่เคยทำงาน และไม่มีอะไรใน `src/` dispatch มันด้วย" — **ข้อสรุปนั้นผิด**. `src/fsm.py` dispatch มันผ่าน `no_progress_goto` (engine root ไม่มี goto edge) และ live test 2026-08-06 เห็น chain ทำงานครบ `fire #1 → probe → fire #2 → restart_app → recover_login → home`. ตัวที่ผิดคือ **lint** ที่ลืมใส่ watchdog roots. บทเรียน: doc ที่อ้าง tool output ต้องแยก "tool ว่าอะไร" ออกจาก "แปลว่าอะไร" — output ถูกแต่ข้อสรุปผิดได้ และ tool เองก็ผิดได้ (ดู [Linter ที่ false-positive ประจำ](#linter-ที่-false-positive-ประจำ--linter-ที่ไม่มีคนอ่าน))
- state count / active-config list ใน doc เก่าผิดได้ถึง 2 เท่า เพราะเขียนมือ — **นับจาก JSON จริงเสมอ** (`json.load` แล้ว `len(d['states'])`) อย่าลอกตัวเลขจาก doc ก่อนหน้า
- เขียน doc ใหม่ที่มีตัวเลข → gen ตัวเลขจาก source ตอนเขียน + เขียน footer บอกว่า derive จากไฟล์ไหน ให้รอบหน้า regen ได้

## แก้บอทเสร็จ → อัพเดต `docs/flow/COMPARE_bots.html` เสมอ

`docs/flow/COMPARE_bots.html` คือเอกสารเทียบบอททุกตัว (launcher → config → state count → boost → flow → known bug). **ทุกครั้งที่แก้ config / launcher / `src/` ที่กระทบพฤติกรรมบอท ต้องอัพเดตไฟล์นี้ให้ตรงในคอมมิตเดียวกัน** — ไม่ใช่ "ไว้ทีหลัง" เพราะกลายเป็นแหล่งข้อมูลผิดที่คนอ่านเชื่อทันที (เจอมาแล้ว: doc บอก `boxrun_relay` ต่างจาก magnet ที่ relay ×2 ทั้งที่ blind tap นั้นถูกลบไปแล้ว, state count ค้างที่ 52 ทั้งที่จริง 60)

ต้องเช็คทุกจุดที่ผูกกับสิ่งที่แก้:

- **state count** — regen จาก JSON จริง (`len(json.load(f)['states'])`) ห้ามพิมพ์มือ ห้ามลอกของเดิม
- **ตาราง launcher §01** — flag ที่ `.bat` ส่งจริง (`--boost` / `--relay` / `--relic-mode` / cycle cap) ต้องตรง argv ในไฟล์
- **flow diagram §03** — ชื่อ state + ลำดับ goto ต้องตรง chain จริง (เพิ่ม/ลบ state = แก้ทั้งชั้นย่อและชั้นเต็ม)
- **§04 สายพันธุ์** — ถ้าแก้จน config ที่เคย "ต่างจุดเดียว" กลายเป็นเหมือนกัน ต้องเปลี่ยน node เป็นสีแดง + บอกว่าซ้ำใคร
- **claim ที่กลายเป็นเท็จ** — `grep` หาพิกัด/ชื่อ state/ชื่อ template ที่แก้ไป แล้วไล่แก้ทุกที่ที่อ้างถึง (รวม note box ที่อธิบาย "ทำไม" ด้วย ไม่ใช่แค่ตาราง)
- **บั๊กที่เพิ่งแก้** — เพิ่มลง section "bug ที่แก้แล้ว" พร้อม **หลักฐาน live-verify** (score ที่วัดได้ / log line จริง) ไม่ใช่แค่ "แก้แล้ว"

**Verify ก่อนจบ**: serve ผ่าน `python -m http.server` แล้วเปิด browser ดูจริง (`file:` ถูกบล็อกใน playwright) — เช็คว่า HTML ไม่พัง + CSS class ที่ใช้มีจริงในไฟล์ (คลาสที่ไม่มีจะ render เป็นกล่องเปล่า ไม่ error ให้เห็น) แล้ว kill server ทิ้ง

### อัพเดต state count ใน HTML — scope byte-range ของตารางก่อน substitute

ไฟล์นี้มีตารางหลายอันที่ **shape ของ cell เหมือนกันเป๊ะ** — `<td class="mono">sendlife</td><td class="mono">400</td>` คือ **poll_ms** ไม่ใช่ state count. Regex ที่ anchor แค่ "cell ถัดจากชื่อ config" จับโดนทั้งคู่:

```python
# หา byte-range ของตารางที่ header ประกาศคอลัมน์ states เท่านั้น
ranges = []
for m in re.finditer(r"<thead", s):
    hdr_end, tbl_end = s.find("</thead>", m.start()), s.find("</table>", m.start())
    if 'class="mono">states<' in s[m.start():hdr_end]:
        ranges.append((m.start(), tbl_end))
# แล้ว substitute เฉพาะใน range พวกนั้น ประกอบเอกสารกลับทีหลัง
```

- **print `old -> new` ต่อจุด** ทุกครั้ง — เห็น `sendlife 400 -> 19` ทันทีว่าผิดตาราง (เจอจริง 2 รอบ: 2026-08-05 แก้เป็น 16, 2026-08-06 แก้เป็น 19 ด้วย pattern คนละตัว)
- **substitute เฉพาะชื่อที่มีใน `config/cookierun/` วันนี้** — ตาราง archive §09 list config ที่ไม่มีแล้ว ต้องคงเลขประวัติศาสตร์ไว้
- **เทียบ tag balance กับไฟล์ก่อนแก้ ไม่ใช่กับ 0** — ไฟล์นี้มี `<p>` เกิน 1 ตัวมาตั้งแต่ต้น (35/36) การเช็คแบบ "ต้องเท่ากัน" จะ false alarm ทุกครั้ง
- **เลขที่เขียนกลางประโยค** ("baseline · 52 states") นับไว้คนละเวลาคนละเกณฑ์ — อย่าไล่แก้ด้วย regex ใส่ note บอกว่าเป็น snapshot แล้วชี้ไป `lint_config.py` เป็นค่าจริง

## Evidence frame ที่ doc อ้าง → `docs/evidence/` ไม่ใช่ `unknown_screens/`

`unknown_screens/` อยู่ใน `.gitignore` (bot เขียนทุกครั้งที่ watchdog ยิง) — **เฟรมที่ doc อ้างเป็นหลักฐานต้องย้ายออกมา** ไม่งั้นคนอ่าน clone มาแล้วเปิดไม่ได้ = ตัวเลขในเอกสารพิสูจน์ไม่ได้

- ย้ายเฉพาะเฟรมที่ **มี doc อ้างถึงจริง** — ที่เหลืออยู่ `unknown_screens/` ตามเดิม ลบพร้อมกันได้
- `docs/evidence/README.md` ต้องบอก **ต่อไฟล์ว่าพิสูจน์อะไร + doc ไหนอ้าง** ไม่ใช่แค่ list ชื่อ (เฟรมเกม 1920×1080 ดูเหมือนกันหมดสำหรับคนที่ไม่ได้อยู่ตอนวัด)
- ตั้งชื่อตาม **สิ่งที่พิสูจน์** ไม่ใช่ timestamp — `blind_false_positive_in_run.png` บอกได้เอง, `20260806_212129_jump_4.png` บอกไม่ได้

## `verify_no_*` gate — `lint_config.py` จับที่ขาดไม่ได้

Popup มี 2 ชนิด ต่างกันที่ **Play! ยังเห็นมั้ย** — ตัดสินว่าต้องเพิ่ม gate หรือไม่:

- **บัง Play!** (เช่น Connection Lost — `home_play_marker` เหลือ ~0.36) → `home` ตกลง `on_absent` เอง → probe chain จัดการได้ **ไม่ต้องมี gate**
- **ไม่บัง Play!** (เช่น Enter League — dialog กลางจอ ปุ่ม Play อยู่มุมล่างขวา `home_play_marker` ยัง match ~1.00 ทะลุ dialog) → `home` ไม่มีวันเข้า `on_absent` → **probe state ที่ควรจัดการเอื้อมไม่ถึงเลย** บอทกด Play ลง dialog ตลอดไป → ต้องมี `verify_no_*` gate ใน pre-Play chain
- **`lint_config.py` เตือนไม่ได้** — state ยัง reachable ทั้ง 2 ทาง ไม่มี orphan ให้จับ. ต้องเช็คมือทุกครั้งที่เจอ popup ใหม่: match `home_play_marker.png` กับ capture ของ popup นั้น — ได้ ~1.00 = ต้องเพิ่ม gate, ได้ <0.40 = probe chain พอ
- Gate ต่อกันแบบ fallthrough และ **Play tap จริงอยู่ที่ `on_absent` ของ gate ตัวสุดท้าย** ไม่ใช่ state แยก — เพิ่ม gate ใหม่ = ย้าย action นั้นไปไว้ที่ตัวใหม่

## แก้ behavior — ต้องเช็ค test ที่ assert ของเดิมด้วย

Test ที่ hardcode ค่าของ profile/config ตัวใดตัวหนึ่งจะ fail เมื่อ fix เปลี่ยนค่านั้น — **fail แบบนี้ไม่ใช่ regression แต่เป็น test ล้าสมัย ต้องแก้พร้อม fix ไม่ใช่ข้าม**:

- พลาดมาแล้ว: fix ให้ `speed` tap Random Boost cell ก่อน (2 tap) แต่ `test_speed_drops_the_random_boost_cell_and_its_wait` + `test_shorter_profile_drops_the_extra_tap_and_its_wait` assert ว่า speed = 1 tap
- ถ้า test นั้นคุม **กลไก** ที่ยังต้องมีอยู่ (เช่น "profile สั้นกว่า baseline ต้องตัด tap + wait ที่เหลือ") → เขียนใหม่ให้ใช้ **synthetic profile** ผ่าน `monkeypatch` แทนผูกกับ shipped profile ตัวจริง — กลไกยังถูกคุม แต่ไม่พังทุกครั้งที่ค่าจริงเปลี่ยน
- `CHOICES` ใน `src/boost.py` เป็น tuple ที่ build จาก `PROFILES` ตอน import — patch `PROFILES` อย่างเดียวไม่พอ ต้อง `monkeypatch.setattr(boost, "CHOICES", ...)` ด้วย

## ทุก fix ต้อง live-verify ก่อน commit

ห้าม commit fix ที่ยังไม่เห็นผลจริงบนเกม/อุปกรณ์จริง แม้ logic จะดูถูกต้องบนกระดาษ:

- dry-run/unit test ไม่พอสำหรับ fix ที่เกี่ยวกับ UI timing, coordinate, หรือ state ของเกมจริง
- ต้องรันจริงอย่างน้อย 1 รอบเห็นพฤติกรรมที่ fix ตั้งใจแก้ (เช่น relic claim สำเร็จจริง ไม่ใช่แค่ routing ถูกใน dry-run)
- ถ้า fix ยัง verify ไม่ได้ (ต้องรอ state ที่หายาก เช่น relic ครบ) ให้บอก user ตรง ๆ ว่ายัง unverified แทนที่จะ commit เงียบ ๆ แล้วหวังว่าจะถูก
- **ข้อยกเว้น: 1 commit มีหลาย item ปนกันได้ ถ้าระบุสถานะแต่ละตัวแยกใน commit message** — ไม่ต้องรอทุก item verified 100% ก่อน commit เสมอไป (พลาดจริง 2026-08-04 เป็นบวก: commit `15aa842` รวม relay fix ที่ยัง unverified + launcher rename/create ที่ verify แล้วจริง (dry-run+pytest ผ่านหมด) — user เลือก commit+push ต่อทันทีเมื่อถูกถามตรง ๆ ว่า "relay ยัง unverified — push ไหม") — เขียน commit body แยกชัดว่าอันไหน live-verify แล้ว อันไหนยังไม่ อย่าเหมาบอกว่า "แก้แล้ว" เท่ากันหมด ให้ user เห็นแล้วตัดสินใจเอง ไม่ใช่ Claude เดาแทน

### Live test — adb / capture / scan marker

**หา adb ผ่านโค้ดของ repo อย่า hardcode** — `python -c "import main; print(main._find_adb())"` (อ่าน `.env` → PATH → LDPlayer install ที่ใหม่สุด). เครื่องนี้ได้ `C:\LDPlayer\LDPlayer14\adb.exe`, device `127.0.0.1:5555` + `emulator-5554`

```bash
ADB="C:\LDPlayer\LDPlayer14\adb.exe"
"$ADB" -s 127.0.0.1:5555 shell pidof com.devsisters.crg      # เกมรันอยู่มั้ย
"$ADB" -s 127.0.0.1:5555 exec-out screencap -p > /tmp/now.png # ต้องผ่าน Bash tool
head -c 8 /tmp/now.png | xxd                                  # ต้องเห็น 8950 4e47
```

- **screencap ต้องใช้ Bash tool ไม่ใช่ PowerShell** — PS `>` เติม BOM ทำ PNG พัง (ดู global CLAUDE.md)
- **Scan marker ทั้งชุดกับเฟรม** เพื่อรู้ว่าอยู่จอไหน — `cv2.matchTemplate` ทุกไฟล์ใน `templates/cookierun/**` (ข้าม `_archive`) เรียง score. เร็วกว่าเดาจากภาพ และเห็น false-positive ด้วย (เจอจริง: `picker_marker` 640×60 ได้ 0.879 บนจอ Events, `boxcounter_marker` 0.944 — ทั้งคู่ไม่อยู่บน absent chain จึงยังไม่ระเบิด)
- **วัด streak จริงด้วย `-v`** — `main.py … -v 2>dbg.log` แล้วนับ `found=False` ติดกันจาก `log.debug("state=%s detect=%s found=%s …")` ใน `src/fsm.py`. นี่คือวิธีเดียวที่รู้ baseline ของ "ปกติ"
- **เปิดจอสำหรับเทส guard** — Party Run: tap `(1580,175)` บน home · Events: tap `(1660,340)` · ปิด result: `(690,930)` · จอเปลี่ยนทุกครั้งที่ tap **ต้อง snap ใหม่ก่อนวัดพิกัดถัดไป** (เจอจริง: วัด `(1555,125)` จากเฟรมเก่าแล้วยิงบนเฟรมใหม่ = ตกคนละที่)
- **Recovery ที่ทำงานถูกจะกินหัวใจ 1 ดวง** ถ้ายิงกลาง run — เทส watchdog บนจอที่ค้างจริง ไม่ใช่ตอนกำลังเล่น

## Snap ก่อนแตะจอเสมอเมื่อเจอสถานะค้าง/แปลก

เมื่อ user รายงานว่าบอทค้าง หรือเจอสถานะจอที่ไม่คาดคิด — **ห้ามสั่ง tap/action ใด ๆ ก่อน snap ดูจอจริงก่อนเสมอ**:

- สถานะค้างอาจเป็นโอกาสหายาก (เช่น relic ครบ, popup ที่ไม่เคยเจอ) — แตะจอทันทีอาจทำให้พลาดโอกาส เก็บ template/coord จากสถานะนั้นไปตลอดกาล
- Snap แล้ววิเคราะห์ก่อนว่าเป็นอะไรจริง ก่อนตัดสินใจว่าจะ dismiss/เก็บข้อมูล/ปล่อยไว้

## Humanized timing — ทุก config ใหม่ต้อง jitter, ห้าม pattern ซ้ำ

**ทุก bot/config ที่สร้างใหม่ ต้องหลีกเลี่ยง tap ตำแหน่ง/จังหวะซ้ำแบบ robot** (user requirement, 2026-08-01):

- **`poll_ms` และทุก `wait.ms` ใช้ range `[min, max]` เสมอ** ไม่ใช่ fixed number — engine สุ่มใหม่ทุกครั้งที่ execute (ดู `src/act.py`, `wait` action)
- **`tap_template` แทน `tap_xy`** ทุกที่ที่มี template ให้ match ได้ — ตำแหน่ง tap ตาม element จริงที่ match เจอ ไม่ใช่ pixel ตายตัว ผลรวมกับ engine jitter (`Actor._jitter`: Gaussian spatial jitter + randomized delay + occasional "hesitate" — อัตโนมัติทุก tap อยู่แล้ว ไม่ต้องเขียนเพิ่ม)
- `tap_xy` ใช้ได้เฉพาะจุดที่ไม่มี template ให้ match จริง ๆ (เช่น blind rescue tap, relay tap ที่ไม่มี UI element ให้จับ)
- **Verify ด้วย `-v` log หลังเขียน** — coord ต้องขยับทุก cycle (ไม่ซ้ำ pixel เป๊ะ), wait duration ต้องกระจายในช่วงที่กำหนด ไม่ใช่ค่าเดิมทุกรอบ

## CookieRun game quirks (manual live-test)

- **Quit ไม่กลับ home ทันที** — หลัง pause→Quit→confirm, เกมมักโยนไป Result popup ใหม่ แล้ว auto-continue เข้า run ถัดไปเองทันที (ไม่รอ user) แม้เพิ่ง quit ไป. ต้องวน pause→Quit→confirm→OK **หลายรอบ** (เจอมาแล้ว 5+ รอบใน session เดียว) กว่าจะถึง home ที่นิ่งจริง — snap ยืนยันเห็น "Play!" + ไม่มี popup ค้างทุกครั้งก่อนสรุปว่าถึง home แล้ว
- **Relic fragment ผูกกับจำนวน box ที่ farm สะสมจริง ไม่ใช่ episode หรือเวลา** — เคย verify live: ep1 ใช้ไป 21+ box (~93 นาทีต่อเนื่อง) กว่า relic badge จะโผล่ครั้งแรก. อย่าคาดเวลาที่ relic จะมาโดยดูจาก episode หรือนาฬิกา ต้องดูจากจำนวน box banked แทน (`run_result: N/M session boxes` ใน log)
- **Blind adb tap บนเกมจริงต้อง snap+verify ทุก step ก่อน tap ต่อไป** — ห้ามไล่ tap รัวๆ ตาม assumption ว่าตำแหน่งเดิมจะยังตรง. พลาดมาแล้ว: tap ปุ่ม "Episode" บน home แต่ไปโดน "Play" แทน เพราะมี panel อื่น (Friends list) เปิดค้างอยู่ทำให้ layout เลื่อน — coordinate ที่เคยถูกอาจผิดทันทีถ้าจอมี state ต่างจากตอน measure

## Errand ที่เรียกข้าม config (`run_config`) — self-contained เสมอ, ปิด popup ที่บังก่อน

`run_config` (`src/act.py`/`src/config.py`/`src/fsm.py`, เพิ่ม 2026-08-08) คือ engine action ให้ config หนึ่ง detour เข้า config อื่นทั้งไฟล์บน `Runner` ใหม่ (share `device` เดิม, **ไม่** share `webhook_url`/`restarter`/`errand_runner` — errand จะ schedule session reset หรือ chain errand ซ้อนไม่ได้) แล้วกลับมาทำงานต่อเมื่อ config นั้นจบด้วย `stop` ของมันเอง. Pattern นี้คือทางที่ถูกสำหรับ "sub-bot ทั้งตัว" (ไม่ใช่แค่ไม่กี่ tap) ที่ config หลักต้องแวะทำระหว่างรอ — ใช้ครั้งแรกกับ `check_heart` heart=0 → `sendlife.json` → `sendlife_mailbox.json` → กลับมาเช็ค heart ต่อ (`docs/RUN.md` §"Heart gate").

- **Config ที่จะถูกเรียกแบบ errand ต้อง self-contained จาก state ที่ parent จะอยู่ตอนเรียก (ปกติคือ home)** — ห้ามพึ่ง precondition ที่ user เปิดมือไว้ก่อน. `sendlife_mailbox.json` เดิมคาดว่า Mailbox popup เปิดอยู่แล้ว (เขียนไว้เป็น standalone bot ที่ user เปิดเอง) — พอเรียกจาก errand chain มันไม่มีทางเปิด popup เองเลย ต้องเพิ่ม `open_mailbox`/`close_mailbox` state ให้เปิด/ปิดจาก home เองครบวงจร ก่อนจะ chain ได้จริง
- **ก่อนเรียก errand ต้องเคลียร์ popup ที่บังอยู่ก่อนเสมอ** — bug จริงที่เจอ: `check_heart` เดิมไม่ปิด boost shop popup ก่อนเรียก `sendlife_mailbox.json`, shop บัง mailbox icon พอดี ทำ `open_mailbox`'s `tap_template` ค้าง retry 500+ polls (ไม่ crash ไม่ error — แค่หา template ไม่เจอเงียบๆ ตลอด). Fix: `tap_template` + `optional: true` ปิด shop ก่อน (ดู "Action ที่ปิด popup ต้อง verify" ด้านบนสำหรับว่าทำไมไม่ใช่ `close_popup`)
- **Live-test เจอ bug ที่ dry-run/unit-test ไม่เจอ** — ทั้งสอง bug ข้างบน (switch_episode timing, shop-close missing) เจอจากรัน background live-test ยาวจริงบนเครื่อง ไม่ใช่จาก dry-run หรือ pytest — errand chain ที่ตัดกันหลาย config ต้อง live-verify end-to-end อย่างน้อย 1 full cycle ก่อนเชื่อว่าใช้ได้จริง
- **`_run_errand` ต้อง settle ก่อน grab frame แรกของ sub-Runner** — sub-Runner ใหม่เริ่มจับภาพทันทีที่ config ก่อนหน้าจบ ไม่รอ animation ของ action สุดท้ายนั้น settle เลย. บั๊กจริง 2026-08-08: `sendlife.json`'s bottom-of-list retry chain จบด้วย swipe แล้ว `run_config` ส่งต่อ `sendlife_mailbox.json` ทันที — list ยังเด้งกลับจาก over-scroll (Android list bounce-back) ตอน `open_mailbox` capture เฟรมแรก ทำ `tap_template` score 0.66 (< threshold 0.85) ซ้ำทุก poll นาน 5477s/5115s สองรอบก่อน external restart ช่วยกู้. Fix: `_run_errand` (`src/fsm.py`) `time.sleep(1.0)` ก่อนสร้าง sub-Runner ทุกครั้ง — ครอบทุก errand ในอนาคตด้วย ไม่ใช่แค่ mailbox
- **`same_state_streak`/`no_act_streak` watchdog ไม่จับ "on_match เจอ แต่ action ข้างในล้มเหลวซ้ำ ๆ" เลย** — สอง gap ซ้อนกัน: (1) `_run_actions` ตั้ง `acted=True` **ก่อน** ลอง action จริง (`src/fsm.py`) ดังนั้น `tap_template` ที่ raise `ActError` ทุก poll ก็ยังนับเป็น "acted" → `no_act_streak` reset ทุกรอบ ไม่มีวัน trip; (2) `timeout_ms`/`absent_retries` ทำงานเฉพาะ path `on_absent` (`detect` ไม่เจอ marker) เท่านั้น — ถ้า `detect` เจอเสมอ (`on_match` เข้าทุกครั้ง) แต่ action ข้างในพัง `timeout_ms` **ไม่มีผลเลย** ต่อให้ตั้งไว้สั้นแค่ไหน. `same_state_streak >= 100` เป็นเส้นเดียวที่จับได้ แต่ยิง webhook alert ครั้งเดียวแล้วปล่อยค้างต่อ ไม่ auto-recover — และ errand sub-Runner ไม่ได้ pass `webhook_url` ผ่านไปด้วย (ตั้งใจ กัน misreport) เลยไม่มีแม้แต่ alert. **Config ที่มี `tap_template` ธรรมดา (ไม่ `optional`) ใน `on_match` ต้องมี `progress_states`/`no_progress_goto`/`no_progress_s` เป็น backstop เสมอ** ถ้ามีความเสี่ยงที่ tap นั้นจะ miss ซ้ำได้ (target อาจไม่ settle, coordinate อาจขยับ) — `no_progress_s` ตั้งสั้นได้เท่าที่ progress state จริงเกิดขึ้นถี่แค่ไหน (`sendlife_mailbox.json` ใช้ 30s เพราะทุก hop ปกติเสร็จในไม่กี่วินาที)

## Plan lifecycle — แยกโฟลเดอร์เมื่อเสร็จ

Plan doc (`docs/plans/PLAN_*.html`) ที่ feature/fix ตาม scope ถูก implement + verify ครบแล้ว (ไม่ใช่แค่บางส่วน) → **ย้ายเข้า `docs/plans/done/`** (ย้ายทั้งไฟล์ HTML และโฟลเดอร์ `assets/<slug>/` ของมันถ้ามี):

- เช็คสถานะจริงก่อนย้ายเสมอ — เทียบ Goal/Scope section ของ plan กับโค้ดจริง (grep function/state/flag ที่ plan พูดถึง) ไม่ใช่เดาจากวันที่ไฟล์
- **DONE** (มีครบ + verify แล้ว) → ย้ายเข้า `docs/plans/done/`
- **PARTIAL** (มีบางส่วน) → อยู่ที่เดิม (`docs/plans/`), ถือว่ายัง active
- **แนวทางถูกยกเลิก** (ตัดสินใจไม่ทำตาม design เดิมแล้ว, มี plan อื่น supersede) → ถามก่อนว่าจะเก็บที่ไหน ไม่ auto-ย้าย
- ก่อนย้ายไฟล์ ต้องรายงาน user ว่า plan ไหนจะย้าย พร้อมหลักฐานที่ยืนยันว่า DONE จริง — ห้าม auto-apply โดยไม่ confirm
