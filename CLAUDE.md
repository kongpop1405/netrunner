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

## ย้าย `.bat` ข้ามชั้นโฟลเดอร์ — ต้องแก้ `cd` แล้ว smoke test ทุกกลุ่ม

ทุก launcher เริ่มด้วย `cd /d "%~dp0.."` เพื่อไต่จากที่อยู่ของตัวเองขึ้นไป repo root. `%~dp0` คือ path ของ `.bat` **ตัวมันเอง** ดังนั้นย้ายไฟล์ลง/ขึ้นชั้น = จำนวน `..` ต้องเปลี่ยนตาม:

| ไฟล์อยู่ที่ | `cd` ที่ถูก |
|---|---|
| `launchers/` | `cd /d "%~dp0.."` |
| `launchers/<sub>/` | `cd /d "%~dp0..\.."` |

- **พังเงียบ ไม่มีอะไรจับได้** — `cd` ผิดทำให้ไปโผล่ `launchers/` แทน repo root แล้วหา `config/` ไม่เจอ. `lint_config.py` อ่านแต่ JSON ไม่เห็น `.bat`, unit test ไม่แตะ launcher เลย — เจอตอน user ดับเบิลคลิกจริงเท่านั้น
- **Smoke test หลังย้ายทุกครั้ง** อย่างน้อย 1 ตัวต่อโฟลเดอร์: copy `.bat` เป็น stub ที่แทนบรรทัด `%PY% ...` ด้วย `echo CWD=%CD% && if exist config\cookierun (echo OK) else (echo BROKEN)` แล้วรันจากตำแหน่งจริง — CWD ต้องเป็น repo root
  - **Stub ต้องข้าม input validation ด้วย** — launcher ที่มี `set /p` + `findstr` validate (เช่น `giftdraw.bat`) จะ `exit /b 1` ก่อนถึงบรรทัดที่ stub ถ้าปล่อยตัวแปรว่าง ให้ replace `set /p` ด้วยค่าที่ผ่าน validate ไม่ใช่ลบทิ้ง
- **ย้ายกลับขึ้นราก = ต้องแก้ `cd` กลับด้วย** ทุกครั้ง — README ใน `launchers/utility/` กับ `launchers/archive/` เขียนกฎนี้ไว้แล้ว อัพเดตด้วยถ้าโครงเปลี่ยน
- Doc ที่อ้าง path launcher (`docs/RUN.md`, `docs/flow/COMPARE_bots.html`) ต้องแก้ในคอมมิตเดียวกัน — ดู section COMPARE_bots ด้านล่าง

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

- `HANDOFF.md` เขียนว่า "lint 0 orphan" แต่ `python tools/lint_config.py config/cookierun/*.json` รายงาน **3 unreachable ทุก box-farm config** (`recover_unknown`, `recover_unknown_probe`, `recover_unknown_restart`) — ทางกู้ "เจอจอไม่รู้จัก → restart" จึงไม่เคยทำงาน และไม่มีอะไรใน `src/` dispatch มันด้วย
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

## Plan lifecycle — แยกโฟลเดอร์เมื่อเสร็จ

Plan doc (`docs/plans/PLAN_*.html`) ที่ feature/fix ตาม scope ถูก implement + verify ครบแล้ว (ไม่ใช่แค่บางส่วน) → **ย้ายเข้า `docs/plans/done/`** (ย้ายทั้งไฟล์ HTML และโฟลเดอร์ `assets/<slug>/` ของมันถ้ามี):

- เช็คสถานะจริงก่อนย้ายเสมอ — เทียบ Goal/Scope section ของ plan กับโค้ดจริง (grep function/state/flag ที่ plan พูดถึง) ไม่ใช่เดาจากวันที่ไฟล์
- **DONE** (มีครบ + verify แล้ว) → ย้ายเข้า `docs/plans/done/`
- **PARTIAL** (มีบางส่วน) → อยู่ที่เดิม (`docs/plans/`), ถือว่ายัง active
- **แนวทางถูกยกเลิก** (ตัดสินใจไม่ทำตาม design เดิมแล้ว, มี plan อื่น supersede) → ถามก่อนว่าจะเก็บที่ไหน ไม่ auto-ย้าย
- ก่อนย้ายไฟล์ ต้องรายงาน user ว่า plan ไหนจะย้าย พร้อมหลักฐานที่ยืนยันว่า DONE จริง — ห้าม auto-apply โดยไม่ confirm
