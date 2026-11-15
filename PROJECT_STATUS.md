# SmartVoice — สถานะสำหรับพัฒนาต่อ

## Cloud migration handover — 15 พฤศจิกายน 2026

**Current phase: Phase 4 — PostgreSQL Migration Design (Planned / Not Implemented).** อ่าน [แผนส่งต่อฉบับเต็ม](docs/cloud_migration_plan.md) และ [architecture ปัจจุบัน](docs/architecture.md) ก่อนพัฒนาต่อ หมายเลข Phase เป็นหมวดงาน ไม่ใช่หลักฐานว่า Phase 1–3 เสร็จทั้งหมด

- ก่อนเริ่มเอกสาร: working tree สะอาด, branch `master`, local HEAD และ GitHub HEAD/master ตรงกันที่ `0c66644077e2d2e5fc930167a4116278d4eaa8d4`; ตรวจ remote ด้วย `git ls-remote origin HEAD refs/heads/master` สำเร็จ
- API-only migration อยู่ใน source แล้ว: pyannoteAI + Typhoon; SQLite 9 application tables, local runtime storage และ process-local background threads ยังอยู่ ไม่ได้เพิ่ม PostgreSQL หรือแก้ application code ในงานส่งต่อ
- ตรวจ source ยืนยัน SQLite coupling, customer/warranty check-then-insert, SO transaction รายใบ, case claim แบบ conditional atomic UPDATE, username NOCASE และ last-admin check ที่แยกจาก write; `call_customer_links` ไม่มี UNIQUE(call_id) แม้ใช้ INSERT OR REPLACE จึงต้องตกลงความหมายก่อนแปลงเป็น upsert
- PM แจ้งว่าเคยทดลอง AWS Academy EC2; รอบนี้ไม่ได้เข้าตรวจ AWS และยังไม่ยืนยัน deployment ของ API-only รุ่นล่าสุดหรือ Production Architecture ไม่มีการสร้าง/แก้ AWS resources
- Live API end-to-end, PostgreSQL integration/concurrency, cloud storage/workers และ multi-user cloud acceptance ยังไม่ได้ยืนยัน; 541 passed ในรายงานเดิมเป็น automated tests ที่ mock APIs
- เอกสารเปลี่ยนเฉพาะ `PROJECT_STATUS.md`, `docs/architecture.md`, `docs/cloud_migration_plan.md` บน branch `docs/cloud-migration-handover`; ผล commit/push ให้ดูรายงานส่งมอบ ไม่ถือว่า branch นี้ merge แล้ว

### Verification ของงานเอกสารนี้

อ่าน AGENTS/README/SETUP/CHANGELOG/architecture/database design และตรวจ source/tests ที่เกี่ยวข้อง เทียบ Git history เพื่อแยกการเปลี่ยน API จากกฎธุรกิจ ตรวจ `.gitignore` ว่าครอบคลุม secrets/runtime/backup และต้องตรวจ staged diff ก่อน commit ไม่อ่านหรือแนบฐานข้อมูล/เสียงลูกค้าจริง

ผล full suite รอบส่งต่อ: **541 passed in 89.25s** รวม `test_config.py` ใช้ API mocks และ environment เฉพาะ process โดยปิด dotenv และตั้ง DB_PATH/TEMP/TMP ไปยัง `.pytest_cache` ไม่เปลี่ยน `.env` ไม่มี live API หรือ Cloud test ในรอบนี้

คำสั่งที่รันจริง (PowerShell ที่ repository root):

```powershell
$env:STT_PROVIDER='pyannote_api'
$env:LLM_PROVIDER='typhoon'
$env:PYTHON_DOTENV_DISABLED='1'
$env:TYPHOON_API_KEY='test-only'
$env:PYANNOTE_API_KEY='test-only'
$env:DB_PATH=Join-Path $PWD '.pytest_cache/handover-runtime/test.db'
$env:TEMP=Join-Path $PWD '.pytest_cache/temp'
$env:TMP=$env:TEMP
& '.venv/Scripts/python.exe' -m pytest tests/ -q --basetemp=.pytest_cache/handover-verification
```

### งานถัดไปสำหรับ Claude Code / PM

อ่าน AGENTS.md และ cloud_migration_plan.md ก่อน ตรวจ Git status/latest commit แล้วเริ่ม **Phase 4 implementation preparation** ด้วยการยืนยัน DAL/driver/schema, link cardinality, SO concurrency, last-admin locking, audit guarantee และ authentication fallback เขียน contract/concurrency tests ก่อน implementation ไม่ทำ API-only migration ซ้ำ ไม่เปลี่ยนกฎธุรกิจ/สิทธิ์/soft-delete/audit เงียบ ๆ และไม่ deploy หรือย้ายข้อมูลลูกค้าจริงโดยไม่มี approval

ข้อความ API-only ด้านล่างเป็นรายงานรอบ implementation ก่อน handover; ส่วน Local รุ่นเก่าถูกเก็บไว้เป็นประวัติ

## สถานะปัจจุบัน — API เท่านั้น (15 พฤศจิกายน 2026)

ตามคำสั่ง PM ถอดการรันโมเดล AI Local ออก: Whisper/Pyannote บนเครื่อง, Ollama transport, GPU/CUDA helpers และ dependencies ที่เกี่ยวข้อง ตัวติดตั้ง `run.bat`/`run.sh`, `requirements.txt`, `pyproject.toml` ใช้ชุด API เท่านั้น

- เสียงใช้ pyannoteAI API (Whisper Turbo + Precision-2/3); ข้อความใช้ Typhoon API ค่าเริ่มต้น `STT_PROVIDER=pyannote_api`, `LLM_PROVIDER=typhoon`
- Settings ตัด Local provider, Whisper backend/device/compute, HuggingFace token และ Ollama URL/model ออก คง API keys/model, Discord และเสียงตัวอย่าง
- `.env` รุ่นเดิมที่ตั้ง `local`/`ollama` จะได้รับข้อความให้เปิด Settings และบันทึกโหมด API; ไม่มีการเปลี่ยน provider หรือแก้ `.env` จริงอัตโนมัติ
- `MOCK_STT=true` ใช้เสียงตัวอย่างแทน STT เท่านั้น การวิเคราะห์ยังเรียก Typhoon และมีค่าใช้บริการ
- `smartvoice/stt/transcribe.py` และ `scripts/compare_stt_models.py` ถูกถอดออก ส่วน helpers จัดข้อความ/label ที่ไม่โหลดโมเดลยังอยู่
- `scripts/compare_llm_models.py` เปลี่ยนเป็นเปรียบเทียบ Typhoon API และต้องใช้ `--allow-api` เพื่อส่ง transcript ไปยังบริการที่มีค่าใช้จ่าย
- คงชื่อโมดูล `ollama_client.py` เพื่อให้ imports เดิมทำงาน แต่ transport ใช้ Typhoon API เท่านั้น
- ฐานข้อมูล, pipeline, prompts, insight rules, สิทธิ์และข้อมูลลูกค้าไม่มีการเปลี่ยน ไม่มีการลบข้อมูล Local, `.env`, แพ็กเกจที่ติดตั้ง หรือ model cache
- ยังไม่ได้ deploy Cloud, ย้าย SQLite เป็น PostgreSQL, ย้ายไฟล์ไป Object Storage หรือเรียกบริการ AI จริง

### ผลตรวจสอบรอบนี้

- Tests ใหม่ก่อน implementation ล้มเหลวครบ 5 กรณีตามคาด จากค่าเริ่มต้น Local, การยอมรับ provider เก่า, imports และ dependencies Local
- หลังถอด Local: 532 passed (เว้น test_config.py ตามแนวทางเดิม)
- รอบสุดท้าย: **541 passed in 85.42s** รันทั้ง `tests/` รวม test_config.py ที่เหลือเฉพาะ pure helpers; ใช้ API จำลองและ keys สำหรับทดสอบ ไม่ใช่บัญชีจริง
- จำนวน tests เปลี่ยนจาก baseline เพราะถอด tests เฉพาะ Local inference/Whisper combo/Local STT benchmark และแทนด้วย API-only, readiness, legacy Settings migration, missing-key และ launcher checks ไม่ได้ลด tests ของกฎธุรกิจ
- `pip check`: No broken requirements found; Python source 49 ไฟล์ parse ผ่าน
- ไม่ได้รันตัวติดตั้งจริงหรือทดสอบ Python ทุกเวอร์ชัน/ทุก OS; launcher ตรวจผ่าน tests และการตรวจ source
- ตรวจ import ใน subprocess ที่บล็อกแพ็กเกจ Local AI แล้ว pipeline/preflight/STT ยัง import ได้

คำสั่งทดสอบ (กำหนดเฉพาะ environment ของ process โดยไม่แก้ .env):

```powershell
$env:STT_PROVIDER='pyannote_api'
$env:LLM_PROVIDER='typhoon'
$env:PYTHON_DOTENV_DISABLED='1'
$env:TYPHOON_API_KEY='test-only'
$env:PYANNOTE_API_KEY='test-only'
$env:TEMP=Join-Path $PWD '.pytest_cache/temp'
$env:TMP=$env:TEMP
& '.venv/Scripts/python.exe' -m pytest tests/ -q --basetemp=.pytest_cache/api-only-final
```

## ประวัติการส่งต่องานก่อนเปลี่ยนเป็น API เท่านั้น

ข้อความด้านล่างเป็นสถานะวันที่ 14 พฤศจิกายน 2026; แนวทาง Local ที่กล่าวถึงถูกยกเลิกโดยสถานะปัจจุบันด้านบน


อัปเดต 14 พฤศจิกายน 2026 (Asia/Bangkok)

## สถานะที่ยืนยันได้

งานเพิ่มทางเลือก API และเก็บงานที่ค้างผ่านการทดสอบอัตโนมัติแล้ว: **552 passed** บน Python 3.12.14 และ Streamlit 1.55.0; `pip check` ผ่าน ไม่มี dependency ขัดแย้ง

**ยังไม่ยืนยันการทำงานกับบริการ AI จริง**: การทดสอบ API ใช้คำตอบจำลอง ยังไม่ได้ตรวจ key, เครดิต, สิทธิ์โมเดล, ความแม่นยำภาษาไทย, latency หรือค่าใช้จ่ายจริง ไม่ได้ส่งเสียงลูกค้าหรือข้อความไปยังผู้ให้บริการ ไม่ได้ deploy หรือสร้างทรัพยากร AWS

GitHub repository **Private**: https://github.com/SojiKlay/smartvoice-master ผู้ใช้อนุญาตและ **push initial commit `df0ef44` สำเร็จแล้ว** บน branch `master` รวม 101 ไฟล์โค้ดและเอกสาร โดยไม่รวมข้อมูล runtime/credentials

## ภาพรวมและโครงสร้าง

SmartVoice เป็นระบบวิเคราะห์สาย call center ภาษาไทย สำหรับงานขายที่นอน/เฟอร์นิเจอร์ การร้องเรียน ติดตามส่งสินค้า และประกัน

Pipeline เดิม:

`audio → Whisper local → Pyannote local → LLM speaker correction → Thai speaker rules/splitters → transcript cleanup → LLM analysis → insight_rules → SQLite → Streamlit`

ทางเลือกใหม่:

`audio → pyannoteAI (Whisper Turbo + Precision diarization) → pipeline/rules เดิม → Typhoon API → insight_rules เดิม → SQLite → Streamlit`

การเปลี่ยนครั้งนี้เป็นการเปลี่ยน backend AI ไม่ใช่เขียนระบบ cloud ใหม่ เว็บ ฐานข้อมูล ไฟล์เสียง และ worker ยังคงอยู่ในเครื่องที่รันแอป สามารถใช้เครื่องสเปคต่ำสำหรับโหมด API ได้โดยไม่ต้องโหลดโมเดล AI ในเครื่อง แต่ยังต้องมี RAM/disk สำหรับเว็บและข้อมูล

ไฟล์หลัก:

| ส่วน | ตำแหน่ง |
|---|---|
| Login และ router ตามสิทธิ์ | `Home.py`, `smartvoice/auth.py`, `smartvoice/ui_helpers.py` |
| หน้าใช้งาน | `pages/` (บางชื่อไฟล์มี emoji ต้องรักษาชื่อจริง) |
| Orchestration / speaker rules | `smartvoice/pipeline.py`, `smartvoice/processing_control.py` |
| Speech backend | `smartvoice/stt/orchestrator.py`, `audio.py`, `transcribe.py`, `diarize.py` |
| LLM / prompts / ตรวจหลักฐาน | `smartvoice/ollama_client.py`, `prompts.py`, `insight_rules.py` |
| ตั้งค่า / ตรวจ readiness | `config.py`, `env_settings.py`, `preflight.py` ภายใน `smartvoice/` |
| SQLite / เคส / ลูกค้า / SO | `smartvoice/db.py`, `case_workflow.py`, `customer_entry.py`, `sales_orders.py` |
| การอัปโหลด / audit / รายงาน | `file_manager.py`, `audit.py`, `dashboard_report.py` ภายใน `smartvoice/` |
| Runtime ส่วนตัว (ห้ามอัปโหลด) | `data/`, `.env`, `.streamlit/secrets.toml` |
| Tests / คู่มือ | `tests/`, `SETUP.md`, `docs/`, `AGENTS.md` |

ตารางหลัก: calls, customers, warranty_registrations, sales_orders, sales_order_lines, call_customer_links, cases, users, audit_log

## เป้าหมายก่อนโควต้าหมดและสิ่งที่ตรวจพบ

ผู้ใช้ต้องการย้ายการประมวลผล AI ออกจากเครื่องสเปคต่ำ โดยคงตระกูลโมเดลเดิมและยอมเปลี่ยนรุ่นได้ เตรียมทดลองบน AWS Academy Learner Lab ภายหลัง

ตรวจประวัติแชต Codex และไฟล์จริงแล้วพบว่า API adapters, Settings, readiness, ชุด dependencies แบบเบา และ tests ถูกเขียนไว้แล้ว แต่ full suite หลังปรับ dependencies ยังไม่สำเร็จก่อนโควต้าหมด รอบนี้จึงตรวจและเก็บงานเดิมต่อ ไม่ได้เปลี่ยน prompts, insight rules หรือออกแบบฐานข้อมูลใหม่

ไม่มี initial commit ให้ใช้เทียบ diff รายการด้านล่างอ้างอิงประวัติแชตและโค้ดที่ตรวจ ไม่ใช่หลักฐานว่าการเปลี่ยนแปลงทั้งหมดในโปรเจ็กต์เกิดจากงาน API นี้

## งานที่เสร็จแล้วและไฟล์ที่เกี่ยวข้อง

| ไฟล์ | ผลงาน |
|---|---|
| `smartvoice/config.py` | เพิ่มการอ่าน provider, model, key, timeout และ token limit ผ่าน `api_settings()` |
| `smartvoice/ollama_client.py` | เพิ่ม Typhoon chat completions; รองรับชื่อรุ่นจาก config; error/429/คำตอบขาดหรือ JSON ไม่ถูกต้องไม่ถูกตีเป็นผลวิเคราะห์สำเร็จเงียบ ๆ |
| `smartvoice/stt/orchestrator.py` | เพิ่ม upload เสียง, สร้าง job, polling และแปลงผลรวม Whisper/Pyannote เป็น segment รูปแบบเดิม; มี checkpoint เพื่อ resume/reuse |
| `smartvoice/pipeline.py` | ตรวจ Typhoon key ก่อนเริ่มงานเสียงในโหมดที่ใช้ Typhoon; รักษา orchestration และกฎเดิม |
| `smartvoice/preflight.py` | readiness แยก local/API; API ไม่บังคับ Ollama หรือโมเดล local; ตรวจค่าที่ตั้งไว้โดยไม่เรียก API จริง |
| `smartvoice/env_settings.py` | preset สำหรับ local กำหนด provider กลับเป็น local/Ollama อย่างชัดเจน |
| `smartvoice/audit.py` | ปิดบังค่า API key ทั้งสองบริการใน audit |
| `smartvoice/file_manager.py` | เมื่อลบเสียงผ่านแอป ลบ checkpoint ของเสียงด้วย |
| `smartvoice/ui_helpers.py` | แสดงชื่อโมเดลตาม provider ใน sidebar |
| `pages/1_📤_Admin.py` | ใช้ readiness ตาม provider ก่อนประมวลผล |
| `pages/4_Settings.py` | เลือก provider/รุ่นและใส่ key ผ่านช่องรหัสผ่าน; เก็บ key เดิมเมื่อเว้นว่าง; รอบนี้แก้ไม่เตือน GPU/ตรวจ combo local เมื่อใช้ speech API และแก้คำแนะนำเปิดแอปใหม่ |
| `.env.example` | ตัวอย่างตัวแปร API ไม่มี key จริง; ค่าเริ่มต้นยังคง local/Ollama |
| `requirements-api.txt` | dependencies สำหรับ API โดยไม่ติดตั้ง torch/CUDA/transformers/Ollama; pin Streamlit 1.55.0 |
| `SETUP.md` | วิธีติดตั้ง API, ค่า config, ข้อจำกัด และวิธีกู้คืนงานจาก checkpoint |
| `tests/test_api_backends.py` | ทดสอบ provider/payload/errors/cache/resume/cancellation/redaction/Settings รวม regression คำเตือน GPU |
| `.gitignore` | กัน runtime/เสียง/ฐานข้อมูล/keys/secrets; จำกัด scratch pattern ให้เฉพาะ root เพื่อไม่ซ่อน `__init__.py` |
| `PROJECT_STATUS.md` | เอกสารส่งต่อฉบับนี้ สร้างตามคำขอผู้ใช้ |

## การตั้งค่า API และขอบเขตที่ต้องเข้าใจ

| ค่า | ค่าเริ่มต้นหรือค่าที่ใช้ในโหมด API |
|---|---|
| `STT_PROVIDER` | เปลี่ยนจาก `local` เป็น `pyannote_api` |
| `LLM_PROVIDER` | เปลี่ยนจาก `ollama` เป็น `typhoon` |
| `MOCK_STT` | ตั้ง `false` เมื่อต้องการเสียงจริง |
| `PYANNOTE_API_MODEL` | `precision-2`; backend รองรับ `precision-3` ด้วย |
| `STT_API_MODEL` | `faster-whisper-large-v3-turbo` |
| `TYPHOON_MODEL` | `typhoon-v2.5-30b-a3b-instruct`; เปลี่ยนรุ่นใน Settings/env ได้ |
| รุ่นเล็กที่เตรียมให้เลือก | `typhoon-v2.1-12b-instruct` ต้องตรวจสิทธิ์และ availability กับบัญชีจริง |
| `AI_API_TIMEOUT` / `AI_JOB_TIMEOUT` | 120 / 1800 วินาที |
| `TYPHOON_MAX_TOKENS` | 4096 |

ต้องตั้ง `PYANNOTE_API_KEY` และ `TYPHOON_API_KEY` ในเครื่อง/เซิร์ฟเวอร์เท่านั้น ไม่ส่งในแชตหรือ Git API ส่งเสียงต้นฉบับให้ pyannoteAI และส่ง transcript ให้ Typhoon จึงต้องใช้ข้อมูลที่ได้รับอนุญาต เครดิต API ของบริการเหล่านี้ไม่ใช่เครดิต AWS Academy

โมเดลเสียง API ไม่ใช่ `biodatlab/distill-whisper-th-large-v3` ตัว local เดิม และไม่ใช่ Pyannote Community-1; ต้องเทียบคุณภาพจริงก่อนรับรองผล ระบบไม่ได้เปลี่ยนรุ่นหรือ retry คำขอที่มีค่าใช้จ่ายอัตโนมัติ

Typhoon ใช้ prompts เดิมและ JSON parser ฝั่งแอป ไม่ได้บังคับ JSON schema ที่บริการ ค่า `json_mode` ของ local Ollama ไม่ได้แปลงเป็นคำสั่ง JSON mode ของ Typhoon

Checkpoint `<audio-path>.smartvoice-api.json` เก็บ job ID และผลเสียงต้นฉบับ ซึ่งเป็นข้อมูลส่วนตัว ห้ามอัปโหลด เมื่อ timeout แล้วลองใหม่จะติดตาม job เดิมหรือใช้ผลเดิม แต่ LLM จะรันใหม่และอาจมีค่าใช้จ่ายซ้ำ ถ้าส่ง job แล้วไม่ได้รับ ID ระบบกันส่งซ้ำอัตโนมัติ ให้ตรวจประวัติงานกับผู้ให้บริการก่อนลบ checkpoint การกดหยุดในแอปไม่ใช่ยกเลิกงานที่รับไปแล้วบนบริการ

## ผลการทดสอบ

- รอบแรกในสภาพแวดล้อมไฟล์ชั่วคราวเดิม: 543 passed / 9 failed มีปัญหา path และสิทธิ์ของไฟล์ชั่วคราว
- รอบสุดท้ายหลังแก้ Settings และกำหนด TEMP/TMP ภายในโปรเจ็กต์: **552 passed in 90.26s** ไม่มี tests ล้มเหลวในชุดที่รัน
- `python -m pip check`: **No broken requirements found**
- Tests ครอบคลุม API จำลอง, Settings ผ่าน Streamlit AppTest, pipeline และ business rules เดิม, DB/auth/audit และหน้าใช้งานตามชุดเดิม
- เว้น `tests/test_config.py` ตาม AGENTS เพราะมีผลข้างเคียงกับ environment และต้องใช้ torch ซึ่งไม่ได้ติดตั้งในชุด API
- ไม่ได้ทดสอบ inference local/GPU, API keys จริง, คุณภาพเสียงจริง, provider rate limits จริง, cloud/network deployment หรือโหลดหลายผู้ใช้

คำสั่งทดสอบที่ผ่านบนเครื่องนี้ (PowerShell ที่ root โปรเจ็กต์):

```powershell
New-Item -ItemType Directory -Force .pytest_cache/temp | Out-Null
$env:TEMP = Join-Path $PWD '.pytest_cache/temp'
$env:TMP = $env:TEMP
& '.venv/Scripts/python.exe' -m pytest tests/ --ignore=tests/test_config.py -q --basetemp=.pytest_cache/work
& '.venv/Scripts/python.exe' -m pip check
```

ผลรันภายในเครื่องเก็บใน `.pytest_cache/test-results.txt` ซึ่ง Git ignore

## ติดตั้งและเปิดใช้งาน

ใช้ virtual environment แยก อย่าสร้างทับ environment ที่มีอยู่โดยไม่ตรวจสอบ บนเครื่องนี้มี `.venv` และติดตั้งชุด API แล้ว

```powershell
py -3.11 -m venv .venv
& '.venv/Scripts/python.exe' -m pip install -r requirements-api.txt
& '.venv/Scripts/python.exe' -m pip install pytest
& '.venv/Scripts/python.exe' -m streamlit run Home.py
```

ข้ามคำสั่งสร้าง venv ถ้ามีแล้ว เครื่องนี้ทดสอบด้วย Python 3.12.14; โหมด local ใช้ Python 3.10/3.11 ตามคู่มือเดิม โหมด API ให้ใช้คำสั่งเปิด Streamlit ด้านบน เพราะ `run.bat`/`run.sh` และ dependencies หลักยังเป็นชุด local เต็ม

เปิด `http://localhost:8501` ตั้ง provider/key ใน Settings แล้วบันทึกและเปิดแอปใหม่ หากยังไม่มีบัญชี แอปมีบัญชี bootstrap ตาม `SETUP.md`/`auth.py` ให้เปลี่ยนรหัสผ่านก่อนเปิดให้ผู้อื่นใช้งาน ไม่เก็บรหัสผ่านจริงในเอกสารนี้

## Git และ GitHub

- Local branch: `master` ติดตาม `origin/master`; initial commit `df0ef44` push สำเร็จแล้ว เอกสารสถานะนี้อัปเดตใน commit ถัดมา
- Remote `origin`: `https://github.com/SojiKlay/smartvoice-master.git`
- Repository บน GitHub ตรวจเห็นป้าย **Private** ในรอบที่สร้าง; ก่อน push ตรวจ remote แล้วไม่มีประวัติเดิม
- ส่งเฉพาะโค้ดและเอกสารที่ตรวจสอบ ไม่ส่งข้อมูล runtime และไม่สร้าง Codespace
- ตรวจ candidate files ก่อนสร้างรายงาน 100 ไฟล์: ไม่พบรูปแบบ token/private key/credential URL ที่สแกน; ตรวจ credential assignments ที่พบเป็นค่า test, label และ bootstrap ของระบบ
- `git check-ignore` ยืนยัน `.env`, `.env.production`, `.streamlit/secrets.toml`, หลักฐานใน `data/`, เสียง และ private key ถูก ignore; ไฟล์ `__init__.py` กลับมาอยู่ใน candidate list
- ตรวจเนื้อหา staged ทั้ง 101 ไฟล์ก่อน commit แล้ว ไม่พบรูปแบบ token/private key ที่ตรวจหา การสแกนรูปแบบไม่รับรองข้อมูลส่วนตัวในข้อความทั่วไปทั้งหมด; ไฟล์เสียง/ฐานข้อมูล/ข้อมูลลูกค้าไม่เป็นส่วนของชุดส่งต่อ
- `git diff --cached --check` พบ whitespace เดิมบางจุดในเอกสาร/pages/prompts/requirements จึงคงไว้เพื่อไม่แก้โค้ดนอกขอบเขต; ไม่ใช่ test failure
- ผล tests ล่าสุดยังเป็น 552 passed; รอบ push นี้เปลี่ยนเฉพาะเอกสารสถานะ ไม่มีการแก้ implementation เพิ่ม
- ไม่มีการแก้ไข `.env` จริงเพื่อเปิด API และไม่มีการย้าย/ล้างข้อมูลผู้ใช้

## งานค้างและขั้นตอนถัดไป

1. ผู้ใช้จัดเตรียม key/เครดิตของ pyannoteAI และ Typhoon ใน Settings หรือ `.env` เอง พร้อมอนุญาตค่าใช้จ่ายและเลือกเสียงทดสอบที่ส่งภายนอกได้ จึงจะทดสอบ live ได้
2. เริ่มเสียงสั้นหนึ่งสาย ตรวจ transcript, ผู้พูด, summary, sentiment, QA, next action และ anomaly กับเสียงจริง แล้วจึงทดสอบชุดตัวอย่างเพิ่มเติม ถ้าลดรุ่น LLM ให้เทียบคุณภาพใหม่
3. Push initial commit สำเร็จแล้ว: เชื่อม GitHub หรือแนบไฟล์โค้ดให้ ChatGPT บนเว็บ โดยให้สิทธิ์เข้าถึง private repository เฉพาะที่ต้องใช้
4. ประเมิน EC2 หลัง live test ผ่านเท่านั้น ต้องได้รับอนุญาตก่อน deploy/สร้างทรัพยากรที่มีค่าใช้จ่าย งานนี้ยังไม่ได้เตรียม deployment อัตโนมัติ
5. ก่อนใช้งานจริงต้องวางแผน HTTPS, เปลี่ยนรหัส bootstrap, backup SQLite/เสียง, พื้นที่ดิสก์, การเข้าถึงข้อมูล, restart/worker และ concurrent users ระบบปัจจุบันยังไม่ใช่ distributed worker/queue

## ส่งต่อให้ ChatGPT Project_Smartvoice บนเว็บ

แนบเอกสารนี้พร้อมโค้ดที่ผ่านการตรวจ หรือเชื่อม private repository ที่มีโค้ดแล้ว การส่งลิงก์อย่างเดียวไม่ทำให้ ChatGPT มีสิทธิ์อ่าน private repo อัตโนมัติ ห้ามแนบ `.env`, credentials, `data/`, เสียงลูกค้า, checkpoints หรือฐานข้อมูลจริง

อ่าน `AGENTS.md` ก่อนแก้โค้ด รักษา prompts, speaker correction multi-pass, evidence validation ใน `insight_rules.py`, role guards, soft delete และ audit trail อย่าลด test เพื่อให้ผ่าน ห้ามอ้างว่า API หรือ cloud ใช้งานจริงแล้วจากผล mock tests เป้าหมายถัดไปคือยืนยัน live integration ที่ได้รับอนุญาต ไม่ใช่ redesign ระบบทั้งหมด
