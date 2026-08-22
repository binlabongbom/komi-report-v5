# Parser Profiles - First Time Setup

ต้องการใช้ **Check Parser Tool** และ Parser Profiles ที่พร้อมใช้แล้ว?

## 🚀 First Time Setup (สำหรับคนรับโปรแกรมใหม่)

### Option 1: Automatic Setup (ง่ายที่สุด)
```bash
cd konica_meter\ 9
python tools/setup_parser_profiles.py
```

ตัวอักษร "✓" ข้างๆ Profile หมายความว่ากำลังใช้งาน

### Option 2: Manual (ทำให้เข้าใจมากขึ้น)
```bash
# 1. ก็อปไฟล์ profiles ไปที่ home directory
cp tools/default_profiles.json ~/konica_parser_user_profiles.json

# 2. ตรวจสอบ
ls -la ~/konica_parser_user_profiles.json

# 3. เริ่มใช้ tool
python tools/check_parser.py
```

---

## 📦 What You Get (ที่คุณจะได้รับ)

6 Pre-configured Parser Profiles พร้อมใช้:

| # | Name | Machine Model | Type | Purpose |
|---|------|---------------|------|---------|
| 1 | **C450i Summary** | C450i, C750i, C900i | Summary | รวมทั้งหมด |
| 2 | **C450i User Account** | C450i, C750i, C900i | User | แยกตามผู้ใช้ |
| 3 | **Press C4070** | Press_C4070 | Production | เครื่องพิมพ์ C4070 |
| 4 | **Press C7090** | Press_C7090 | Production | เครื่องพิมพ์ C7090 |
| 5 | **Press C12010S** | Press_C12010S | Production | เครื่องพิมพ์ C12010S |
| 6 | **Label 230** | Label_230 | Label | มิเตอร์ Label |

**Slots 7-10** เว้นไว้สำหรับการปรับแต่งเพิ่มเติม

---

## ✅ Verify Setup

### Check 1: ตรวจไฟล์ profiles
```bash
ls -la ~/konica_parser_user_profiles.json
# ควรจะได้ไฟล์ขนาด 2-5 KB
```

### Check 2: ตรวจ Profiles ที่อยู่ใน Tool
```bash
python tools/check_parser.py
# ควรจะเห็น 6 profiles ปรากฏในซ้ายมือ
# Slots 7-10 ว่างเปล่าสำหรับปรับแต่ง
```

### Check 3: ทดสอบการ Load ไฟล์
```bash
python tools/check_parser.py
# 1. เลือก Profile 1: "C450i Summary"
# 2. Click [Upload] หรือ Drag-drop ไฟล์ C450i
# 3. ควรจะ detect ได้ถูก
```

---

## 🔧 Troubleshooting

### ❌ "File not found: default_profiles.json"
**วิธีแก้:** ตรวจสอบว่าคุณอยู่ในโปรแกรม directory ที่ถูกต้อง
```bash
# ควรหา default_profiles.json ตรงนี้:
ls konica_meter\ 9/tools/default_profiles.json
```

### ❌ "No module named 'PyQt6'"
**วิธีแก้:** ติดตั้ง PyQt6
```bash
pip install PyQt6
# หรือจาก requirements.txt
pip install -r requirements.txt
```

### ❌ Setup Script ไม่ทำงาน
**วิธีแก้:** ลองทำ manual setup
```bash
cp tools/default_profiles.json ~/konica_parser_user_profiles.json
python tools/check_parser.py
```

### ❌ Profiles ว่างเปล่า
**ต่อ:** ตรวจสอบไฟล์ profiles
```bash
# ตรวจสอบ JSON
cat ~/konica_parser_user_profiles.json | head -20

# ถ้าหาย ให้รัน setup ใหม่
python tools/setup_parser_profiles.py
```

---

## 📝 Next Steps

### สำหรับ Development
1. ✓ Setup default profiles (ขั้นตอนนี้แล้ว)
2. Test with sample meter files
3. Customize profiles as needed
4. Save changes (auto-saved in `~/konica_parser_user_profiles.json`)

### สำหรับ Deployment
1. Keep `tools/default_profiles.json` in repository
2. When distributing → users run setup script first
3. Main program auto-loads from `~/konica_parser_user_profiles.json`

---

## 📚 Learn More

- Check Parser Tool: `python tools/check_parser.py`
- View profiles: `cat ~/konica_parser_user_profiles.json`
- Integration: See `database.py` for how profiles are used
- Edit: Open Check Parser Tool and modify profiles graphically

---

**Questions?** Check the repository docs or contact the dev team!
