NPOIL Brand Credit - V4

Ban V4 bo sung:
- Admin cau hinh diem/credit tai /admin/scoring
- Bang xep hang loc theo thang, nhom, phong ban/NPP/dai ly
- Bao cao admin nang cap, co loc va tai Excel
- Duyet bai nang cao: duyet, tu choi, yeu cau bo sung minh chung
- Nguoi dung co the bo sung lai minh chung khi admin yeu cau
- Sua cau hinh PostgreSQL/SQLite va pin Werkzeug==2.3.8 de tranh loi version

Chay local:
1. Giai nen source
2. Tao file .env tu .env.example neu can
3. python -m venv venv
4. venv\Scripts\activate
5. pip install -r requirements.txt
6. python app.py
7. Mo http://127.0.0.1:5000

Tai khoan admin mac dinh:
Email: admin@npoil.vn
Mat khau: Admin@123456

Deploy Render:
- Build Command: pip install -r requirements.txt
- Start Command: gunicorn app:app
- Environment Variables can thiet:
  SECRET_KEY
  DATABASE_URL (Internal Database URL PostgreSQL)
  DEMO_MODE=1 hoac DEMO_MODE=0 neu dung SerpApi that
  SERPAPI_API_KEY neu DEMO_MODE=0
  ADMIN_EMAIL
  ADMIN_PASSWORD
