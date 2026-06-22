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

==============================
CẬP NHẬT V5 - GIẢI THƯỞNG + GIAO DIỆN RESPONSIVE
==============================
Bản V5 bổ sung:
- Giao diện mới đẹp hơn, có sidebar desktop và thanh menu ngang responsive trên mobile.
- Trang /admin/prizes để admin tự chỉnh mốc giải thưởng, số lượng giải và giá trị giải.
- Trang /admin/winners để admin chốt giải theo tháng từ bảng xếp hạng.
- Trang /winners để người dùng xem danh sách vinh danh đã chốt.
- Xuất Excel danh sách trao giải tại /admin/winners/download.

Sau khi deploy V5 lên Render:
1. Đăng nhập admin.
2. Vào Admin → Quản lý giải thưởng để kiểm tra mốc giải.
3. Vào Admin → Chốt giải để chọn tháng và bấm Chốt giải.
4. Vào Vinh danh để xem kết quả người thắng giải.

Lưu ý:
- Nếu đang dùng PostgreSQL, bảng mới sẽ tự được tạo khi app khởi động.
- Nếu đang dùng SQLite local, không upload file npoil_brand_credit.db lên GitHub.
- Nếu deploy trên Render, nên dùng PostgreSQL để dữ liệu tồn tại lâu dài.
