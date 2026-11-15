# SmartVoice บน AWS EC2 — คู่มือติดตั้งสำหรับทดลองใช้ (Stage 1)

ติดตั้ง SmartVoice ทั้งระบบบน EC2 เครื่องเดียว เพื่อให้ตัวแทนบริษัทเข้าทดลองใช้ผ่านเบราว์เซอร์ทาง HTTPS

```
ผู้ใช้ ──HTTPS──▶ EC2 (Ubuntu 24.04)
                  ├─ Caddy :443  (ใบรับรอง Let's Encrypt อัตโนมัติ)
                  │    └─▶ Streamlit 127.0.0.1:8501  (systemd: smartvoice)
                  ├─ /opt/smartvoice/app/data   SQLite + ไฟล์เสียง + หลักฐาน (EBS เข้ารหัส)
                  └─ backup ทุกคืน 02:30 ─▶ S3 ส่วนตัว (ถ้าตั้ง bucket)
                         │
                         └─▶ pyannoteAI API / Typhoon API (ขาออก HTTPS)
```

**ขอบเขต:** แบบนี้เป็น **ขั้นทดลองใช้ ไม่ใช่ production** มีเครื่องเดียว (ถ้าเครื่องล่ม ระบบก็หยุด) และประมวลผลเสียงใน process เดียวกับเว็บ ระบบหลายเครื่อง + PostgreSQL + S3 เป็นขั้นถัดไปตาม `docs/cloud_migration_plan.md`

---

## 0. ก่อนเริ่ม — ต้องตัดสินใจ/เตรียมให้เรียบร้อย

| เรื่อง | ทำไมต้องรู้ก่อน |
|---|---|
| **ข้อมูลที่จะใช้ทดลอง** | ถ้าใช้เสียงสายจริงของลูกค้า ต้องได้รับอนุมัติให้ส่งเสียงไป pyannoteAI และข้อความไป Typhoon (PDPA / เงื่อนไขผู้ให้บริการ) ถ้ายังไม่ได้ ให้ใช้โหมดสาธิต (ข้อ 7) |
| **บัญชี AWS** | AWS Academy Learner Lab เหมาะกับการซ้อมติดตั้งเท่านั้น: session มีเวลาจำกัดและเครื่องจะหยุดเมื่อหมด session, IP อาจเปลี่ยน, สิทธิ์ IAM และงบจำกัด และเป็นบัญชีเพื่อการศึกษา — ถ้าจะให้ตัวแทนบริษัทเข้าใช้ต่อเนื่อง ควรใช้บัญชี AWS ปกติ **ห้ามใส่ข้อมูลลูกค้าจริงใน Learner Lab** |
| **ชื่อโดเมน** | HTTPS ต้องใช้ชื่อ DNS ที่ชี้มาที่เครื่อง เช่น `smartvoice.<โดเมนบริษัท>` ถ้ายังไม่มี ใช้ชื่อจาก sslip.io ได้ชั่วคราว (เช่น IP `203.0.113.10` → `203-0-113-10.sslip.io`) แต่อาจติดโควตาออกใบรับรองของ Let's Encrypt |
| **API key + เครดิต** | pyannoteAI และ Typhoon ทุกสายที่ประมวลผลมีค่าใช้จ่าย ควรทดสอบสายจริง 1 สายให้ผ่านก่อนเปิดให้บริษัทใช้ |

---

## 1. สร้าง EC2

| ค่า | แนะนำ |
|---|---|
| AMI | **Ubuntu Server 24.04 LTS** (มี Python 3.12 ซึ่งแอปรองรับ 3.10–3.12) |
| ขนาด | `t3.small` (2 GB RAM) สำหรับผู้ใช้ไม่กี่คน, `t3.medium` ถ้าอัปโหลด/ประมวลผลพร้อมกันหลายไฟล์ — ไม่ต้องมี GPU |
| ดิสก์ | gp3 30 GB ขึ้นไป **เปิด Encryption** (ไฟล์เสียงใช้พื้นที่มากที่สุด) |
| Security group ขาเข้า | `443/tcp` และ `80/tcp` จาก `0.0.0.0/0` (80 ใช้ขอใบรับรองและ redirect ไป HTTPS) · `22/tcp` **เฉพาะ IP ของผู้ดูแล** · ห้ามเปิด `8501` |
| Elastic IP | ผูกให้เครื่อง เพื่อให้ IP/DNS ไม่เปลี่ยนเมื่อ stop/start |
| IAM role (ถ้าจะ backup ไป S3) | role ที่เขียนได้เฉพาะ bucket ของ SmartVoice (ใน Learner Lab ใช้ `LabInstanceProfile`) |

ตั้ง DNS record `A` ของโดเมนให้ชี้ไปที่ Elastic IP แล้วรอให้ resolve ได้ก่อนข้อ 3 (Caddy ต้องใช้ขอใบรับรอง)

**S3 bucket สำหรับ backup (แนะนำ):** สร้าง bucket ใหม่ใน region เดียวกัน เปิด **Block all public access**, เปิด default encryption และ versioning

---

## 2. นำโค้ดขึ้นเครื่อง

repository เป็น private — เลือกวิธีใดวิธีหนึ่ง (ห้ามใส่ GitHub token ลงในเครื่องแบบถาวร):

```bash
# บนเครื่องของผู้ดูแล: ทำไฟล์ zip จาก commit ที่ต้องการ (ไม่รวม .env, data/)
git archive --format=tar.gz -o smartvoice.tar.gz HEAD
scp -i <key.pem> smartvoice.tar.gz ubuntu@<domain>:~
```

```bash
# บน EC2
mkdir -p ~/smartvoice-src && tar -xzf ~/smartvoice.tar.gz -C ~/smartvoice-src
```

(อีกวิธี: GitHub deploy key แบบ read-only แล้ว `git clone`)

**ห้ามคัดลอก** `.env`, `data/`, ไฟล์เสียง หรือฐานข้อมูลจากเครื่อง local ขึ้นไปเว้นแต่ได้รับอนุมัติให้ย้ายข้อมูลจริง

---

## 3. ติดตั้ง

```bash
cd ~/smartvoice-src
sudo bash deploy/aws-ec2/install.sh --domain <domain> --s3-bucket <bucket>   # --s3-bucket ไม่บังคับ
```

สคริปต์จะ:
- ติดตั้ง Python venv, ฟอนต์ไทย (สำหรับรายงาน PDF), Caddy และ AWS CLI (เมื่อระบุ bucket)
- คัดลอกโค้ดไป `/opt/smartvoice/app` และสร้าง venv ที่ `/opt/smartvoice/venv`
- **ติดตั้งครั้งแรก:** สร้าง `.env` พร้อม `SMARTVOICE_BOOTSTRAP_PASSWORD` แบบสุ่ม แล้ว **แสดงรหัสนี้ครั้งเดียว** — ระบบบน server จะไม่ใช้ `admin1234`
- เปิด service `smartvoice`, ตั้ง backup ทุกคืน และตั้ง HTTPS ผ่าน Caddy

ตรวจสถานะ:

```bash
systemctl status smartvoice caddy
journalctl -u smartvoice -f
```

---

## 4. เข้าใช้งานครั้งแรก

1. เปิด `https://<domain>` → ล็อกอิน `admin` ด้วยรหัสที่สคริปต์แสดง
2. **เปลี่ยนรหัสผ่านทันที** (กล่องบัญชีใน sidebar → เปลี่ยนรหัสผ่าน) — ระบบเตือนจนกว่าจะเปลี่ยน
3. หน้า **ตั้งค่าระบบ** → ใส่ `PYANNOTE_API_KEY`, `TYPHOON_API_KEY` → บันทึก → `sudo systemctl restart smartvoice`
4. ดูหน้าแรก (ส่วนตรวจความพร้อมของผู้ดูแล) ว่าไม่มีข้อผิดพลาด — การตรวจนี้ดูแค่ว่ามี key ยังไม่ยืนยันเครดิต
5. อัปโหลดเสียงทดสอบที่ได้รับอนุญาต **1 สาย** แล้วตรวจผลถอดเสียง/ผู้พูด/สรุป/คะแนน ก่อนเปิดให้คนอื่นใช้

## 5. สร้างบัญชีให้ตัวแทนบริษัท

หน้า **จัดการผู้ใช้** → เพิ่มบัญชีทีละคน เลือกบทบาทตามที่จะให้เห็น (`Agent` / `QA` / `Supervisor`; ให้ `Admin` เฉพาะผู้ดูแลระบบ) ส่งรหัสเริ่มต้นผ่านช่องทางที่ปลอดภัยและให้แต่ละคนเปลี่ยนเอง — ระบบไม่มีปุ่มรีเซ็ตรหัสโดย Admin (ตามนโยบาย) ถ้าลืมรหัสให้ปิดใช้งานบัญชีเดิมแล้วสร้างบัญชีใหม่ด้วยชื่อผู้ใช้อื่น

**การกันเดารหัสผ่าน:** ใส่ผิด 5 ครั้งต่อบัญชีจะล็อกบัญชีนั้น 60 วินาที และผิด 20 ครั้งจาก IP เดียวจะล็อก IP นั้น 5 นาที (ทั้งสำนักงานที่ใช้ IP เดียวกันจะโดนด้วย) นับรวมทุกแท็บ/ทุกเบราว์เซอร์ ตัวนับอยู่ในหน่วยความจำ — รีสตาร์ท service แล้วนับใหม่

## 6. Backup และกู้คืน

- ทุกคืน 02:30 (เวลาไทย) `smartvoice-backup.timer` ทำ snapshot ฐานข้อมูลที่ตรวจ `integrity_check` แล้วไว้ใน `data/backups/` (เก็บ 14 ชุดล่าสุด) และถ้าตั้ง bucket ไว้จะ sync snapshot + ไฟล์เสียง + หลักฐานไป `s3://<bucket>/smartvoice/` (เข้ารหัส SSE; ไม่ลบของใน S3)
- สั่ง backup ทันที: `sudo systemctl start smartvoice-backup && journalctl -u smartvoice-backup -n 20`
- ตั้ง EBS snapshot รายวัน (AWS Backup / Data Lifecycle Manager) เป็นอีกชั้นหนึ่ง

**กู้คืนฐานข้อมูล** (ทดลองกู้อย่างน้อย 1 ครั้งก่อนให้บริษัทใช้จริง):

```bash
sudo systemctl stop smartvoice
sudo -u smartvoice cp /opt/smartvoice/app/data/smartvoice.db /opt/smartvoice/app/data/smartvoice.db.before-restore
sudo -u smartvoice cp /opt/smartvoice/app/data/backups/smartvoice-<เวลา>.db /opt/smartvoice/app/data/smartvoice.db
sudo systemctl start smartvoice
```

(จาก S3: `aws s3 cp s3://<bucket>/smartvoice/backups/smartvoice-<เวลา>.db /tmp/` แล้วคัดลอกแบบเดียวกัน) ข้อมูลที่เกิดหลัง snapshot นั้นจะหายไป และงานที่ส่งให้ API ไปแล้วไม่ย้อนกลับ

## 7. โหมดสาธิต (ยังไม่มีอนุมัติใช้เสียงจริง)

หน้าตั้งค่าระบบ → **โหมดสาธิต** (`MOCK_STT=true`) ระบบจะใช้บทสนทนาตัวอย่างแทนการถอดเสียง แต่ **ยังเรียก Typhoon จริง** (มีค่าใช้จ่าย) ถ้าต้องการข้อมูลตัวอย่างบน Dashboard:

```bash
cd /opt/smartvoice/app && sudo -u smartvoice /opt/smartvoice/venv/bin/python scripts/seed_mock_data.py
```

ข้อมูลตัวอย่างเป็นข้อมูลสมมติ อย่าใช้ปนกับข้อมูลจริงในฐานเดียวกัน

## 8. อัปเดตเวอร์ชัน

นำโค้ดใหม่ขึ้นเครื่อง (ข้อ 2) แล้วรัน `install.sh` คำสั่งเดิมซ้ำ — `data/` และ `.env` ไม่ถูกแตะ จากนั้น service รีสตาร์ทเอง การรีสตาร์ทจะหยุดงานประมวลผลที่กำลังทำอยู่ (สายนั้นกลับเป็นรอประมวลผล) ให้อัปเดตตอนไม่มีงานค้าง

## 9. สิ่งที่ระบบนี้ยังไม่มี (รู้ไว้ก่อนเปิดให้ใช้)

- เครื่องเดียว: ไม่มี failover ถ้า EC2 หยุด ระบบหยุด
- งานประมวลผลอยู่ใน process ของเว็บ: รีสตาร์ท = งานที่กำลังทำหยุด
- log ของแอป (`journalctl -u smartvoice`, `data/logs/`) ไม่บันทึกคำพูดลูกค้าจากคำตอบ AI แล้ว แต่ `calls.error_msg` ในฐานข้อมูลยังเก็บ traceback ของสายที่ล้มเหลว (เห็นเฉพาะ Admin/Supervisor)
- การตั้งค่าเก็บใน `.env` บนเครื่อง ยังไม่ใช้ AWS Secrets Manager
- ไม่มี monitoring/alert — อย่างน้อยให้ตั้ง CloudWatch alarm ของ EC2 status check และพื้นที่ดิสก์

## ไฟล์ในโฟลเดอร์นี้

| ไฟล์ | หน้าที่ |
|---|---|
| `install.sh` | ติดตั้ง/อัปเดตทั้งหมด (รันด้วย root) |
| `smartvoice.service` | systemd service ของเว็บแอป — ฟังเฉพาะ 127.0.0.1, เขียนได้เฉพาะ `data/` และ `.env` |
| `Caddyfile.template` | HTTPS reverse proxy (`__DOMAIN__` ถูกแทนตอนติดตั้ง) |
| `backup.sh`, `smartvoice-backup.service`, `smartvoice-backup.timer` | backup ทุกคืนผ่าน `scripts/backup_db.py` แล้ว sync ไป S3 |
