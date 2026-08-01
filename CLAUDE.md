# netrunner project conventions

## Progress reporting & commits

- งานสำเร็จหรือคืบหน้าระหว่างทาง (live-test ผ่าน, bug fix verify แล้ว, feature เสร็จบางส่วน) → **รายงานให้ user ทราบทันที** ไม่ต้องรอจบ session
- Commit เป็นระยะตามงานที่เสร็จจริง (ไม่รวบทุกอย่างเป็น 1 commit ท้าย session) — 1 commit = 1 fix/feature ที่ verify แล้ว
- **Stage เฉพาะไฟล์ของ scope งานตัวเองเท่านั้น** — ถ้า repo มี unrelated changes ค้างอยู่ (จาก branch/session อื่นที่ปนเข้ามาในดัชนี) ห้าม `git add -A`/`git add .` เหมารวม ใช้ `git add <path เฉพาะไฟล์ของงานนี้>` เสมอ ปล่อยไฟล์อื่นไว้ตามเดิมให้ session ที่เป็นเจ้าของจัดการเอง

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

## Plan lifecycle — แยกโฟลเดอร์เมื่อเสร็จ

Plan doc (`docs/plans/PLAN_*.html`) ที่ feature/fix ตาม scope ถูก implement + verify ครบแล้ว (ไม่ใช่แค่บางส่วน) → **ย้ายเข้า `docs/plans/done/`** (ย้ายทั้งไฟล์ HTML และโฟลเดอร์ `assets/<slug>/` ของมันถ้ามี):

- เช็คสถานะจริงก่อนย้ายเสมอ — เทียบ Goal/Scope section ของ plan กับโค้ดจริง (grep function/state/flag ที่ plan พูดถึง) ไม่ใช่เดาจากวันที่ไฟล์
- **DONE** (มีครบ + verify แล้ว) → ย้ายเข้า `docs/plans/done/`
- **PARTIAL** (มีบางส่วน) → อยู่ที่เดิม (`docs/plans/`), ถือว่ายัง active
- **แนวทางถูกยกเลิก** (ตัดสินใจไม่ทำตาม design เดิมแล้ว, มี plan อื่น supersede) → ถามก่อนว่าจะเก็บที่ไหน ไม่ auto-ย้าย
- ก่อนย้ายไฟล์ ต้องรายงาน user ว่า plan ไหนจะย้าย พร้อมหลักฐานที่ยืนยันว่า DONE จริง — ห้าม auto-apply โดยไม่ confirm
