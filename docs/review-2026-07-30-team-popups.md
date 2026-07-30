# Review — Connection Lost / Enter League popups + switch_episode

ทีม emulator, 3 commits: `7127f30` (% escape), `6dceada` (2 popups), `a3c689c`
(switch_episode). รีวิวโดยทีม branch หลัก.

**ภาพรวม: งานดี.** pytest ยังเขียว, lint 0 orphan, template verify score จริง
(1.0 บนภาพตัวเอง / <0.40 บน home) ตาม HANDOFF. `probe_connectionlost` วางหัว chain
ถูก. `switch_episode` reset ไป left edge ก่อน step (กัน swipe drift) + retry เปิด map
= คิดครบ.

## แก้ให้แล้วบน branch `fix/restart-app-restarter-and-help` (commit `9c7f1a5`)

### P1 — restart_app ไม่มี Restarter ใน 9/10 config

`probe_connectionlost` → `restart_app` แต่ `build_restarter()` คืน `None` เมื่อ config
ไม่มี `session_reset_s` (มีแค่ `boxrun_toggle.json`). อีก 9 ไฟล์ → `restart_app`
**warn แล้ว noop** → เสีย pidof stability verify, `recover_login` อาจ race ตอน app
ยังโหลด. แก้: `build_restarter` สร้าง Restarter เมื่อมี state ใช้ `restart_app` ด้วย +
test ยืนยันทุก config ที่ใช้ action ได้ Restarter จริง.

### nit#1 — run_toggle --help ยัง crash

`7127f30` escape `%` เฉพาะ `main.py`; `tools/run_toggle.py:247` เรียก
`describe_choices()` ดิบเหมือนกัน → `--help` crash เดิม. แก้บรรทัดเดียว.

## ฝากทีมพิจารณา (ยังไม่แตะ — style/coverage)

### 2. `probe_enterleague` ใช้ tap_xy+wait ไม่ใช่ close_popup

Phase 6 migrate 194 dismiss เป็น `close_popup`+`verify` (tap แล้ว re-read, ยิงซ้ำ
ถ้า marker ยังอยู่ — กัน tap โดนตอน dialog fade in แล้วไม่มีผล). popup ใหม่นี้กลับ
ปิดแบบเดา. แนะนำ:

```jsonc
{ "type": "close_popup", "x": 960, "y": 700, "verify": "enterleague_marker.png" }
```

`probe_connectionlost` **ยกเว้นได้** — มัน restart ไม่ใช่ปิด.

### 3. enter_league: on_match goto = on_absent goto = probe_inactive

ปลายทางเดียวกันทั้งเจอ/ไม่เจอ. popup อื่น on_match กลับ `home` (ให้ probe chain
เดินใหม่จากต้น). ไม่ผิด แต่ผิด pattern — เจตนาหรือเปล่า?

### 4. switch_episode ไม่มี test

Tool อื่น (`report_runs` / `lint_config`) มี test หมด. 127 บรรทัด untested.
อย่างน้อยเทส "banner ไม่มี → error ชัด" (mockable ไม่ต้องมี device).

### 5. trailing newline หาย 10 config

`\ No newline at end of file` ทั้ง 10 ไฟล์ที่แก้. diff รอบหน้าจะเห็น noise 1 บรรทัด
ต่อไฟล์. เขียน JSON ปิดท้าย `\n` (`json.dumps(...) + "\n"`).

## แนะนำลำดับ merge

`fix/restart-app-restarter-and-help` (P1 + nit#1) → เข้า
`feature/parity-anti-detection` ก่อน merge ขึ้น main. nit 2-5 จะแก้ในนี้เลย หรือ
follow-up ก็ได้ — ไม่บล็อก.
