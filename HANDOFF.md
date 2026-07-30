# HANDOFF — งานที่เหลือต้องมี emulator

สถานะ ณ 2026-07-30, branch `feature/parity-anti-detection` (24+ commits จาก `main`).
เครื่องที่พัฒนา branch นี้**ไม่มี LDPlayer** — ทุกอย่างที่ทำได้โดยไม่มีจอจริงทำไปแล้ว
และมีเทสครอบ (**pytest 259 passed, 7 skipped**). ที่เหลือทั้งหมดในไฟล์นี้ต้องการ
เครื่องที่รัน LDPlayer + Cookie Run จริง.

เอกสารประกอบ:

- `docs/plans/PLAN_feature-parity-anti-detection.html` — แพลนเต็ม 9 phase พร้อม
  findings ต่อ phase (เปิดในเบราว์เซอร์)
- `docs/popup-coverage.md` — popup ไหน handle แล้ว / ตัวไหนขาด + วิธี crop
- `RUN.md` section "Parity + anti-detection upgrade" — สรุป feature ใหม่
- `README.md` — config schema + action types ล่าสุด

## เช็คก่อนเริ่ม

```powershell
python -m pytest tests/                              # ต้อง 259 passed (7 skip ถ้าไม่มี tesseract)
python tools/lint_config.py config/cookierun/*.json  # ต้อง OK ทั้ง 13 ไฟล์
```

---

## 1) Verification gate — ทำก่อนอย่างอื่น อย่ารันบน account จริงทันที

โค้ดทั้ง branch ยังไม่เคยแตะเกมจริง. รัน dry-run (ไม่ส่ง tap) ต่อ config ที่จะใช้:

```powershell
python main.py --config config/cookierun/boxrun_toggle.json --dry-run --max-cycles 120 -v
```

จุดที่ต้องจ้องเป็นพิเศษ (เรียงตามความเสี่ยง):

1. **`mb_open`** (Mystery Box) — restructure จาก chain 8 state เหลือ 1 self-loop.
   พิกัด tap ก๊อปจากของเดิมที่พิสูจน์ live แล้ว แต่ flow ใหม่ยังไม่เคยรัน:
   เปิดกล่องครบทุกใบมั้ย / inactive popup ระหว่างเปิดกล่องต้อง recover ผ่าน absent
   path / `match_timeout_ms: 25000` อาจสั้นไปตอน reveal หลายกล่อง (escape กลางคัน
   = พลาดกล่อง ไม่พัง — สั้นไปค่อยขยาย)
2. **Pacing บน `boxrun_toggle`** — ดู log ว่า inter-game idle 30-60s โผล่ทุก lap
   (ยกเว้น lap แรก) และค่าต่างกันจริง
3. **Session reset** — บีบ `session_reset_s` เป็น `[60, 90]` ชั่วคราวในสำเนา config
   เพื่อเทส: app ต้องปิด+เปิดใหม่, ผ่าน stability check 3 รอบ, กลับมา farm ต่อ,
   ไม่ idle ซ้ำใน lap แรกหลัง reset
4. **Send-lives errand** — บีบ `interval_s` เป็น `[60, 90]`: ต้อง detour เข้า
   `lives_scan` เฉพาะตอนอยู่ home, ส่งครบ, กลับมา farm
5. **ep3 / norelay_noquit** — boost chain เพิ่งถูกต่อกลับ (เดิม orphan — bot เล่น
   โดยไม่ซื้อ boost มาตลอด). ดูว่า probe→buy→picker→roll→Play เดินครบ
6. **ep5 / ep6box / ep6v2** — popup chain (congrats/levelup/ranking/giftdraw/
   friendinfo) เพิ่งถูกต่อเข้า `probe_sendlife` — เดิม 4 popup นี้ไม่มีอะไรปิดเลย

ผ่านแล้วค่อยรัน 1 config บน account ทดลอง ทิ้งไว้หลายชั่วโมง แล้วดู
`logs/netrunner.log` + `unknown_screens/`.

## 2) Baseline analytics — ทำก่อนเปิด pacing ที่ config อื่น

Pacing + session reset **ลด yield โดยตั้งใจ** (แลกกับความเหมือนคน). ถ้าไม่มีตัวเลข
before จะไม่รู้ว่าแลกไปเท่าไหร่:

```powershell
# รัน config เดิม (fixed pacing) สัก 1 วัน แล้ว:
python tools/report_runs.py --logs logs --out docs/reports/runs-before.html
# เปิด pacing แล้วรันเท่ากัน:
python tools/report_runs.py --logs logs --out docs/reports/runs-after.html
```

เทียบ runs/hour, boxes/hour, livelock, adb fail.

## 3) Crop templates @1920×1080 — ปลดล็อก Phase 6 + Phase 3

**ห้ามใช้ template จาก cookierun-classic-bot ตรง ๆ** — ของนั้น crop ที่ 1280×720,
`matchTemplate` เป็น single-scale ใช้ข้าม resolution ไม่ได้. ใช้เป็น reference
ภาพเท่านั้น (อยู่ที่ `D:\Project\Mini Project\cookierun-classic-bot\templates\`).

วิธี: `python tools/snap.py --device 127.0.0.1:5555 --out snaps/` ตอนจอนั้นโผล่
→ crop ส่วนที่เป็นเอกลักษณ์ (title ribbon แคบ ๆ match ดีสุด) → วางใน
`templates/cookierun/`.

**Popup 10 ตัว** — ลิสต์เต็ม + handling + priority อยู่ใน `docs/popup-coverage.md`.
สองตัวแรกสำคัญสุด:

- `CONNECTION_LOST` — ไม่ใช่ปิด popup: ใช้ action `restart_app` (พร้อมแล้ว,
  ยังไม่มี config ใช้) แล้วต่อ `recover_login`. วางไว้หัว probe chain
- `PARTY_RUN` — โผล่หลัง announcement, บัง home

**Boost banner 8 ตัว** — crop pill ของ boost ที่ equip อยู่ + วัด buy taps →
เพิ่ม entry ใน `PROFILES` (`src/boost.py`). ตัวไหนพร้อม/ขาดดูจาก:

```powershell
python main.py --help   # บรรทัด --boost บอก ready + สิ่งที่แต่ละตัวขาด
```

**ไม่ต้องนั่งเฝ้า popup**: ลูปที่ค้างจะ snap จอเข้า `unknown_screens/` + ส่ง
Discord เอง (ตั้ง `DISCORD_WEBHOOK_URL` ใน `.env`) — รัน unattended สองสามวัน
ภาพจะมาเอง.

## 4) Captcha — วัดพิกัดเมื่อเจอ challenge จริงครั้งแรก

Algorithm (`odd_cells_out` + action `solve_cards`) เสร็จและมีเทส 35 ตัว แต่
**ยังไม่มีใครเคยเห็น challenge จริง** — ไม่มี config ไหน wire ไว้ (ตั้งใจ).

เมื่อ collector เก็บภาพ captcha แรกได้:

1. วัด center ของการ์ดทั้ง 6 + ขนาดการ์ด + ปุ่ม Confirm จากภาพ
2. Crop marker หัวข้อ challenge (ไว้ detect ว่ามันโผล่)
3. เพิ่ม state (ดูตัวอย่าง action ใน README) — `bail_goto` ชี้ state ที่
   stop + alert เท่านั้น **อย่าให้เดา**: `gap_min` ทำให้บอทไม่แตะอะไรเลย
   ตอนไม่มั่นใจ ซึ่งตั้งใจ — ตอบผิดเสี่ยงแบน รอคนถูกกว่า
4. เทสกับภาพจริงก่อน enable: `odd_cells_out(frame, cells, size)` ใน REPL

## 5) OCR counter — ต้องลง tesseract binary

`--quit-after-boxes` จะอ่านเลขจริงจาก pill เมื่อมี tesseract; ไม่มีก็ fallback
นับแบบหยาบ (ยังทำงาน). ลง:

```powershell
winget install UB-Mannheim.TesseractOCR
python -m pip install pytesseract
python -m pytest tests/test_ocr.py    # 7 เทสที่เคย skip ต้องรัน
```

แล้ว calibrate `BoxQuitRunner.COUNTER_OFFSET` (`tools/run_toggle.py`) กับจอจริง —
ค่าปัจจุบัน `(70, 0, 90, 90)` ประมาณจากสัดส่วน marker ยังไม่เคย verify.

## 6) สิ่งที่ตั้งใจไม่ทำ (อย่าเข้าใจว่าลืม)

- **Pacing/reset/routine เปิดเฉพาะ `boxrun_toggle.json`** — config อื่นยัง fixed
  จนกว่า toggle จะพิสูจน์ตัวเองบนจอจริง. เปิดเพิ่ม = ก๊อป field จาก toggle
- **`check_heart` ไม่มี `match_timeout_ms`** — self-loop รอ heart regen เป็น
  เจตนา อย่าใส่
- **8 boost ที่ยังไม่พร้อมถูก refuse ตอน launch** — ไม่ใช่ bug; มันบอกเองว่าขาดอะไร
- **`solve_cards` ไม่อยู่ในทุก config** — รอพิกัดจริง (ข้อ 4)
- **Backlog** (obstacle dodge, multi-instance, multi-resolution, เกมที่สอง) —
  เหตุผลที่ยังไม่ทำอยู่ใน plan HTML section 10

## แผนที่โค้ดฉบับย่อ

| อยากแก้เรื่อง | ไปที่ |
|---|---|
| จังหวะ tap / delay / jitter | `src/act.py` (ค่า class-level บน `Actor`) |
| ลูปหลัก, pacing, reset, routine | `src/fsm.py` (`Runner.run`) |
| เพิ่ม/แก้ boost | `src/boost.py` (`PROFILES`) |
| Restart app | `src/session.py` |
| Config field ใหม่ | `src/config.py` (`load` + `_validate`) |
| ตรวจ config | `tools/lint_config.py` |
| อ่านสถิติ | `tools/report_runs.py` |

ทุกไฟล์มี docstring/comment อธิบาย "ทำไม" พร้อมเหตุการณ์จริงที่ทำให้ต้องเขียนแบบนั้น
— **อ่านก่อนแก้** โดยเฉพาะก่อน "simplify" retry logic หรือ threshold ใด ๆ.
