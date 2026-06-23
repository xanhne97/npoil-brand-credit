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

=== V6 - CÔNG THỨC XẾP HẠNG CÔNG BẰNG ===

Bản V6 bổ sung cơ chế xếp hạng theo thang 100 điểm:
- Bài/nhiệm vụ hợp lệ: 30%
- Tương tác: 25%
- Share: 25%
- Tăng trưởng follow/bạn bè: 10%
- Tuân thủ bài chính thức/trọng điểm: 10%

Nguyên tắc công bằng:
- Không tính số follow/bạn bè có sẵn.
- Chỉ tính phần tăng thêm trong tháng.
- Điểm tăng trưởng được tính tương đối trong cùng nhóm lọc, không dùng trần cứng gây đồng điểm.
- Nếu bằng điểm, hệ thống ưu tiên: số bài hợp lệ, số bài trọng điểm, tương tác thực tế, share thực tế, tăng trưởng thực tế.

Admin có thể chỉnh tại:
/admin/scoring

Bảng xếp hạng mới:
/leaderboard

Báo cáo Excel mới:
/admin/reports


--- V7 - TẮT NHẬP TAY CHỈ SỐ TƯƠNG TÁC/FOLLOW ---
Bản V7 bỏ phần người dùng tự nhập like/share/view/follow/bạn bè vì không khả thi và khó kiểm soát.
Hệ thống mặc định xếp hạng theo nhiệm vụ hợp lệ 80% và tuân thủ bài chính thức/trọng điểm 20%.
Các cột like/share/view/follow vẫn được giữ trong database để giai đoạn sau tích hợp API/OCR tự động lấy chỉ số, nhưng không hiển thị trên form người dùng và không tham gia điểm mặc định.

==============================
V8 - CƠ CHẾ TỰ ĐỘNG CẤP 1
==============================
Bản V8 bổ sung trang /admin/automation để cấu hình tự động kiểm tra bài gửi.

Cơ chế tự động hiện tại KHÔNG phụ thuộc API Facebook/TikTok, gồm:
- Tự kiểm tra link trùng
- Tự kiểm tra đúng nền tảng Facebook/TikTok
- Tự kiểm tra thời gian nhiệm vụ
- Tự kiểm tra mã nhiệm vụ
- Tự kiểm tra hashtag bắt buộc
- Tự kiểm tra giới hạn bài/ngày
- Tự duyệt nếu đạt điều kiện và nhiệm vụ bật auto approve
- Tự từ chối các lỗi chắc chắn nếu admin bật rule

Trang mới:
/admin/automation

Nút quét lại:
Admin có thể bấm "Chạy quét tự động" để hệ thống quét lại các bài pending/need_review sau khi thay đổi rule.

Lưu ý:
Giai đoạn này chưa tự lấy like/share/follow từ Facebook/TikTok. Khi tích hợp API/OCR ở bản sau, các chỉ số này mới được bật lại.

==============================
V9 - KHO NỘI DUNG CHÍNH THỨC
==============================
Bản V9 bổ sung module kho nội dung chính thức của công ty.

Trang người dùng:
- /content-library: Xem kho nội dung, copy caption chuẩn, mở bài gốc, gửi bài hoàn thành nhiệm vụ.
- Khi gửi bài từ kho nội dung, caption sẽ được điền sẵn gồm nội dung mẫu, mã nhiệm vụ và hashtag.

Trang admin:
- /admin/content-library: Thêm nội dung chính thức, link bài gốc, caption mẫu, mã nhiệm vụ, hashtag, điểm và credit.
- Admin có thể chọn tạo nhiệm vụ tương ứng ngay khi thêm nội dung.
- Nếu chưa tạo nhiệm vụ, admin có thể bấm "Tạo nhiệm vụ" từ nội dung đó.

Lưu ý deploy:
- Phải upload đủ thư mục templates/ và static/ lên GitHub.
- Không upload venv/, .env, __pycache__/ và file .db.


==============================
V10 - THÔNG BÁO TỰ ĐỘNG
==============================
Bản V10 bổ sung trung tâm thông báo trong hệ thống:
- Người dùng nhận thông báo khi bài được tự duyệt, admin duyệt, bị từ chối, cần bổ sung minh chứng hoặc đạt giải.
- Admin nhận thông báo khi có người đăng ký mới, có bài gửi cần kiểm tra hoặc người dùng bổ sung minh chứng.
- Admin có thể gửi thông báo hàng loạt tại /admin/notifications.
- Người dùng xem thông báo tại /notifications và có thể đánh dấu đã đọc.

Khi upload lên GitHub/Render nhớ upload đủ thư mục templates/ và static/.
Không upload: venv, .env, __pycache__, npoil_brand_credit.db.


V11 - Dashboard KPI tổng quan
- Thêm trang /admin/kpi để ban quản lý xem KPI theo tháng, nhóm và đơn vị.
- Theo dõi: người tham gia, người hoạt động, bài gửi, bài hợp lệ, bài chờ duyệt, credit đã cấp/đã dùng, lượt tìm kiếm khách hàng, số lead trả về, top người dẫn đầu, KPI theo nhóm và nhiệm vụ hiệu quả.
- Có nút xuất Excel KPI tại /admin/kpi/download.
- Menu Admin có thêm mục “KPI tổng quan”.

==============================
V12 - KẾT NỐI TIKTOK API
==============================

Bản V12 bổ sung:
- Người dùng kết nối tài khoản TikTok tại /tiktok
- Admin đồng bộ video TikTok tại /admin/tiktok-sync
- Hệ thống tự quét video công khai, kiểm tra mã nhiệm vụ + hashtag
- Nếu video khớp nhiệm vụ, hệ thống tự tạo bài tham gia, cộng điểm và credit

Cấu hình Render cần thêm Environment Variables:
TIKTOK_CLIENT_KEY=client key từ TikTok Developer App
TIKTOK_CLIENT_SECRET=client secret từ TikTok Developer App
TIKTOK_REDIRECT_URI=https://ten-app-cua-ban.onrender.com/auth/tiktok/callback
TIKTOK_SCOPES=user.info.basic,video.list

Trên TikTok Developer Portal, cần khai báo Redirect URI giống chính xác TIKTOK_REDIRECT_URI.

Luồng test:
1. Deploy bản V12 lên Render.
2. Vào /tiktok bằng tài khoản user.
3. Bấm Kết nối TikTok.
4. Sau khi kết nối thành công, admin vào /admin/tiktok-sync.
5. Bấm Quét tất cả tài khoản hoặc Quét từng tài khoản.
6. Video TikTok công khai có mã nhiệm vụ và hashtag sẽ được tự ghi nhận.

Lưu ý:
- TikTok API chỉ lấy được dữ liệu người dùng đã cấp quyền.
- Video phải công khai và có caption chứa mã nhiệm vụ + hashtag.
- Các chỉ số like/comment/share/view được lưu lại từ API để về sau có thể bật công thức điểm tự động.
