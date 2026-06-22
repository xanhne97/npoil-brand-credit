import io
import json
import os
import sqlite3
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

import uuid
from datetime import datetime, date
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, redirect, render_template, request, send_file,
    session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from scraper import scrape_from_keywords

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "npoil_brand_credit.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
UPLOAD_DIR = BASE_DIR / "static" / "uploads" / "proofs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB

REQUIRED_HASHTAGS_DEFAULT = "#NPOIL #NPOILVietnam #DauNhotNPOIL #NPOILTruyenThongThuongHieu"
SEARCH_CREDIT_PER_KEYWORD = 5
EXPORT_EXCEL_CREDIT = 10
ALLOWED_UPLOAD_EXT = {"png", "jpg", "jpeg", "webp", "pdf"}


class PostgresConnection:
    """Small wrapper so the app can use the same conn.execute(...) style with PostgreSQL."""

    def __init__(self):
        if psycopg2 is None:
            raise RuntimeError("Thiếu psycopg2-binary. Hãy cài: pip install psycopg2-binary")
        db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        self.conn = psycopg2.connect(db_url)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()

    def execute(self, query, params=None):
        # SQLite uses ? placeholders; psycopg2 uses %s placeholders.
        query = query.replace("?", "%s")
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, params or ())
        return cur

    def executescript(self, script):
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(script)
        return cur


def db():
    if USE_POSTGRES:
        return PostgresConnection()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def current_month():
    return datetime.now().strftime("%Y-%m")


def today_text():
    return date.today().isoformat()


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def allowed_file(filename):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_UPLOAD_EXT


def save_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        raise ValueError("File minh chứng chỉ hỗ trợ png, jpg, jpeg, webp hoặc pdf")
    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[1].lower()
    new_name = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(UPLOAD_DIR / new_name)
    return f"uploads/proofs/{new_name}"


def normalize_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def platform_match(platform, url):
    platform = (platform or "").lower()
    url = normalize_url(url)
    if platform in ("both", "all", ""):
        return True
    host = urlparse(url).netloc.lower()
    if platform == "facebook":
        return any(x in host for x in ["facebook.com", "fb.watch"])
    if platform == "tiktok":
        return "tiktok.com" in host
    return True


def missing_tokens(text, tokens):
    text = (text or "").lower()
    missing = []
    for token in tokens:
        token = token.strip()
        if token and token.lower() not in text:
            missing.append(token)
    return missing


def int_form(name, default=0):
    try:
        value = request.form.get(name, default)
        if value in (None, ""):
            return default
        return int(float(value))
    except (ValueError, TypeError):
        return default


def get_user(user_id):
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_user(user_id)


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "year": datetime.now().year,
        "month_now": current_month(),
    }


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Vui lòng đăng nhập để tiếp tục.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or not user["is_admin"]:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def init_db():
    sqlite_schema = """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                group_type TEXT NOT NULL DEFAULT 'employee',
                department TEXT,
                distributor_name TEXT,
                dealer_name TEXT,
                phone TEXT,
                facebook_url TEXT,
                tiktok_url TEXT,
                credit_balance INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS missions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                platform TEXT NOT NULL DEFAULT 'facebook',
                mission_type TEXT NOT NULL DEFAULT 'official_share',
                official_post_url TEXT,
                mission_code TEXT NOT NULL,
                required_hashtags TEXT,
                points_reward INTEGER NOT NULL DEFAULT 0,
                credit_reward INTEGER NOT NULL DEFAULT 0,
                max_extra_points INTEGER NOT NULL DEFAULT 100,
                max_per_day INTEGER NOT NULL DEFAULT 2,
                start_date TEXT,
                end_date TEXT,
                auto_approve INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mission_id INTEGER NOT NULL,
                post_url TEXT NOT NULL,
                content_text TEXT,
                proof_file TEXT,
                platform TEXT,
                like_count INTEGER NOT NULL DEFAULT 0,
                comment_count INTEGER NOT NULL DEFAULT 0,
                share_count INTEGER NOT NULL DEFAULT 0,
                view_count INTEGER NOT NULL DEFAULT 0,
                follower_before INTEGER NOT NULL DEFAULT 0,
                follower_after INTEGER NOT NULL DEFAULT 0,
                friends_before INTEGER NOT NULL DEFAULT 0,
                friends_after INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                auto_check_note TEXT,
                points_awarded INTEGER NOT NULL DEFAULT 0,
                credit_awarded INTEGER NOT NULL DEFAULT 0,
                admin_note TEXT,
                created_at TEXT NOT NULL,
                approved_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(mission_id) REFERENCES missions(id)
            );

            CREATE TABLE IF NOT EXISTS point_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                submission_id INTEGER,
                points INTEGER NOT NULL,
                reason TEXT,
                month_key TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS credit_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                transaction_type TEXT NOT NULL,
                reason TEXT,
                balance_after INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS search_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                keywords TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                radius_m INTEGER,
                result_count INTEGER NOT NULL DEFAULT 0,
                credit_cost INTEGER NOT NULL DEFAULT 0,
                export_charged INTEGER NOT NULL DEFAULT 0,
                results_json TEXT,
                created_at TEXT NOT NULL
            );
            """

    postgres_schema = """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                group_type TEXT NOT NULL DEFAULT 'employee',
                department TEXT,
                distributor_name TEXT,
                dealer_name TEXT,
                phone TEXT,
                facebook_url TEXT,
                tiktok_url TEXT,
                credit_balance INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS missions (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                platform TEXT NOT NULL DEFAULT 'facebook',
                mission_type TEXT NOT NULL DEFAULT 'official_share',
                official_post_url TEXT,
                mission_code TEXT NOT NULL,
                required_hashtags TEXT,
                points_reward INTEGER NOT NULL DEFAULT 0,
                credit_reward INTEGER NOT NULL DEFAULT 0,
                max_extra_points INTEGER NOT NULL DEFAULT 100,
                max_per_day INTEGER NOT NULL DEFAULT 2,
                start_date TEXT,
                end_date TEXT,
                auto_approve INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                mission_id INTEGER NOT NULL REFERENCES missions(id),
                post_url TEXT NOT NULL,
                content_text TEXT,
                proof_file TEXT,
                platform TEXT,
                like_count INTEGER NOT NULL DEFAULT 0,
                comment_count INTEGER NOT NULL DEFAULT 0,
                share_count INTEGER NOT NULL DEFAULT 0,
                view_count INTEGER NOT NULL DEFAULT 0,
                follower_before INTEGER NOT NULL DEFAULT 0,
                follower_after INTEGER NOT NULL DEFAULT 0,
                friends_before INTEGER NOT NULL DEFAULT 0,
                friends_after INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                auto_check_note TEXT,
                points_awarded INTEGER NOT NULL DEFAULT 0,
                credit_awarded INTEGER NOT NULL DEFAULT 0,
                admin_note TEXT,
                created_at TEXT NOT NULL,
                approved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS point_transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                submission_id INTEGER,
                points INTEGER NOT NULL,
                reason TEXT,
                month_key TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS credit_transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                amount INTEGER NOT NULL,
                transaction_type TEXT NOT NULL,
                reason TEXT,
                balance_after INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS search_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                keywords TEXT NOT NULL,
                latitude DOUBLE PRECISION NOT NULL,
                longitude DOUBLE PRECISION NOT NULL,
                radius_m INTEGER,
                result_count INTEGER NOT NULL DEFAULT 0,
                credit_cost INTEGER NOT NULL DEFAULT 0,
                export_charged INTEGER NOT NULL DEFAULT 0,
                results_json TEXT,
                created_at TEXT NOT NULL
            );
            """

    with db() as conn:
        conn.executescript(postgres_schema if USE_POSTGRES else sqlite_schema)

        admin_email = os.getenv("ADMIN_EMAIL", "admin@npoil.vn").strip().lower()
        admin_password = os.getenv("ADMIN_PASSWORD", "Admin@123456")
        existing = conn.execute("SELECT id FROM users WHERE email=?", (admin_email,)).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO users
                (name, email, password_hash, group_type, credit_balance, is_admin, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Admin NPOIL",
                    admin_email,
                    generate_password_hash(admin_password),
                    "employee",
                    200,
                    1,
                    now_text(),
                ),
            )

        mission_count = conn.execute("SELECT COUNT(*) AS c FROM missions").fetchone()["c"]
        if mission_count == 0:
            conn.execute(
                """
                INSERT INTO missions
                (title, description, platform, mission_type, official_post_url, mission_code,
                 required_hashtags, points_reward, credit_reward, max_extra_points, max_per_day,
                 start_date, end_date, auto_approve, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Nhiệm vụ mẫu: Chia sẻ bài truyền thông NPOIL",
                    "Người tham gia chia sẻ hoặc tự đăng bài có mã nhiệm vụ và hashtag bắt buộc. Hệ thống tự kiểm tra link, hashtag, mã nhiệm vụ, giới hạn bài/ngày và tự cộng điểm nếu hợp lệ.",
                    "both",
                    "official_share",
                    "",
                    "NPOIL-T7-001",
                    REQUIRED_HASHTAGS_DEFAULT,
                    10,
                    8,
                    100,
                    2,
                    today_text(),
                    "2026-12-31",
                    1,
                    "active",
                    now_text(),
                ),
            )

def add_credit(conn, user_id, amount, tx_type, reason):
    user = conn.execute("SELECT credit_balance FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        return 0
    new_balance = int(user["credit_balance"] or 0) + int(amount)
    if new_balance < 0:
        raise ValueError("Không đủ credit")
    conn.execute("UPDATE users SET credit_balance=? WHERE id=?", (new_balance, user_id))
    conn.execute(
        """
        INSERT INTO credit_transactions
        (user_id, amount, transaction_type, reason, balance_after, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, amount, tx_type, reason, new_balance, now_text()),
    )
    return new_balance


def add_points(conn, user_id, submission_id, points, reason):
    conn.execute(
        """
        INSERT INTO point_transactions
        (user_id, submission_id, points, reason, month_key, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, submission_id, points, reason, current_month(), now_text()),
    )


def calculate_submission_score(mission, form_values):
    base_points = int(mission["points_reward"] or 0)
    base_credit = int(mission["credit_reward"] or 0)

    like_count = form_values["like_count"]
    comment_count = form_values["comment_count"]
    share_count = form_values["share_count"]
    view_count = form_values["view_count"]
    follower_growth = max(0, form_values["follower_after"] - form_values["follower_before"])
    friends_growth = max(0, form_values["friends_after"] - form_values["friends_before"])

    extra = 0
    extra += like_count // 5                  # 1 điểm / 5 like
    extra += comment_count                    # 1 điểm / comment
    extra += share_count * 2                  # 2 điểm / share lại
    extra += (view_count // 500) * 5          # 5 điểm / 500 view
    extra += follower_growth                  # 1 điểm / follow tăng
    extra += friends_growth // 2              # 1 điểm / 2 bạn bè tăng
    extra = min(extra, int(mission["max_extra_points"] or 100))

    points = base_points + extra
    credit = base_credit + max(0, extra // 5)
    return points, credit


def auto_check_submission(conn, user_id, mission, post_url, content_text):
    notes = []
    errors = []

    post_url = normalize_url(post_url)
    content_text = content_text or ""

    # Check thời gian nhiệm vụ
    today = date.today()
    start = parse_date(mission["start_date"])
    end = parse_date(mission["end_date"])
    if start and today < start:
        errors.append("Nhiệm vụ chưa bắt đầu")
    if end and today > end:
        errors.append("Nhiệm vụ đã kết thúc")

    # Check link trùng
    duplicate = conn.execute(
        "SELECT id FROM submissions WHERE post_url=? AND status IN ('auto_approved','approved','pending','need_review')",
        (post_url,),
    ).fetchone()
    if duplicate:
        errors.append("Link bài đã được gửi trước đó")

    # Check nền tảng
    if not platform_match(mission["platform"], post_url):
        errors.append(f"Link không đúng nền tảng yêu cầu: {mission['platform']}")

    # Check mã nhiệm vụ
    mission_code = (mission["mission_code"] or "").strip()
    if mission_code and mission_code.lower() not in content_text.lower():
        errors.append(f"Thiếu mã nhiệm vụ: {mission_code}")

    # Check hashtag
    hashtags = (mission["required_hashtags"] or "").split()
    missing_hashtags = missing_tokens(content_text, hashtags)
    if missing_hashtags:
        errors.append("Thiếu hashtag: " + ", ".join(missing_hashtags))

    # Check giới hạn bài/ngày/người theo nhiệm vụ
    max_per_day = int(mission["max_per_day"] or 2)
    today_start = today_text() + " 00:00:00"
    today_end = today_text() + " 23:59:59"
    count_today = conn.execute(
        """
        SELECT COUNT(*) AS c FROM submissions
        WHERE user_id=? AND mission_id=?
          AND status IN ('auto_approved','approved','pending','need_review')
          AND created_at BETWEEN ? AND ?
        """,
        (user_id, mission["id"], today_start, today_end),
    ).fetchone()["c"]
    if count_today >= max_per_day:
        errors.append(f"Đã vượt giới hạn {max_per_day} bài/ngày cho nhiệm vụ này")

    if errors:
        return "need_review", " | ".join(errors)

    notes.append("Tự động kiểm tra hợp lệ: đúng link, đúng thời gian, đủ mã nhiệm vụ/hashtag, không trùng, không vượt giới hạn")
    if int(mission["auto_approve"] or 0) == 1:
        return "auto_approved", " | ".join(notes)
    return "pending", "Tự động kiểm tra đạt điều kiện cơ bản, chờ admin duyệt"


@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        group_type = request.form.get("group_type", "employee")

        if not name or not email or not password:
            flash("Vui lòng nhập đầy đủ họ tên, email và mật khẩu.", "danger")
            return render_template("register.html")
        if len(password) < 6:
            flash("Mật khẩu nên có ít nhất 6 ký tự.", "danger")
            return render_template("register.html")

        try:
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO users
                    (name, email, password_hash, group_type, department, distributor_name, dealer_name,
                     phone, facebook_url, tiktok_url, credit_balance, is_admin, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        email,
                        generate_password_hash(password),
                        group_type,
                        request.form.get("department", "").strip(),
                        request.form.get("distributor_name", "").strip(),
                        request.form.get("dealer_name", "").strip(),
                        request.form.get("phone", "").strip(),
                        normalize_url(request.form.get("facebook_url", "")),
                        normalize_url(request.form.get("tiktok_url", "")),
                        20,  # tặng credit khởi tạo để test hệ thống
                        0,
                        now_text(),
                    ),
                )
            flash("Đăng ký thành công. Bạn có thể đăng nhập ngay.", "success")
            return redirect(url_for("login"))
        except Exception as exc:
            msg = str(exc).lower()
            if "unique" in msg or "duplicate" in msg or isinstance(exc, sqlite3.IntegrityError):
                flash("Email này đã tồn tại.", "danger")
            else:
                flash(f"Không thể đăng ký: {exc}", "danger")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email=? AND status='active'", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash("Đăng nhập thành công.", "success")
            return redirect(url_for("dashboard"))
        flash("Email hoặc mật khẩu không đúng.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Đã đăng xuất.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    with db() as conn:
        month = current_month()
        points = conn.execute(
            "SELECT COALESCE(SUM(points),0) AS total FROM point_transactions WHERE user_id=? AND month_key=?",
            (user["id"], month),
        ).fetchone()["total"]
        total_submissions = conn.execute(
            "SELECT COUNT(*) AS c FROM submissions WHERE user_id=?", (user["id"],)
        ).fetchone()["c"]
        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM submissions WHERE user_id=? AND status IN ('pending','need_review')",
            (user["id"],),
        ).fetchone()["c"]
        searches = conn.execute(
            "SELECT COUNT(*) AS c FROM search_logs WHERE user_id=?", (user["id"],)
        ).fetchone()["c"]
        latest_submissions = conn.execute(
            """
            SELECT s.*, m.title AS mission_title
            FROM submissions s JOIN missions m ON m.id=s.mission_id
            WHERE s.user_id=? ORDER BY s.id DESC LIMIT 5
            """,
            (user["id"],),
        ).fetchall()
    return render_template(
        "dashboard.html",
        points=points,
        total_submissions=total_submissions,
        pending=pending,
        searches=searches,
        latest_submissions=latest_submissions,
    )


@app.route("/missions")
@login_required
def missions():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM missions WHERE status='active' ORDER BY id DESC"
        ).fetchall()
    return render_template("missions.html", missions=rows)


@app.route("/missions/<int:mission_id>/submit", methods=["GET", "POST"])
@login_required
def submit_mission(mission_id):
    user = current_user()
    with db() as conn:
        mission = conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
    if not mission:
        abort(404)

    if request.method == "POST":
        post_url = normalize_url(request.form.get("post_url", ""))
        content_text = request.form.get("content_text", "").strip()
        if not post_url or not content_text:
            flash("Vui lòng nhập link bài và nội dung/caption có mã nhiệm vụ + hashtag.", "danger")
            return render_template("submit_mission.html", mission=mission)

        form_values = {
            "like_count": int_form("like_count"),
            "comment_count": int_form("comment_count"),
            "share_count": int_form("share_count"),
            "view_count": int_form("view_count"),
            "follower_before": int_form("follower_before"),
            "follower_after": int_form("follower_after"),
            "friends_before": int_form("friends_before"),
            "friends_after": int_form("friends_after"),
        }

        try:
            proof_file = save_upload(request.files.get("proof_file"))
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("submit_mission.html", mission=mission)

        with db() as conn:
            mission = conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
            status, note = auto_check_submission(conn, user["id"], mission, post_url, content_text)
            points, credit = (0, 0)
            approved_at = None
            if status == "auto_approved":
                points, credit = calculate_submission_score(mission, form_values)
                approved_at = now_text()

            cur = conn.execute(
                """
                INSERT INTO submissions
                (user_id, mission_id, post_url, content_text, proof_file, platform,
                 like_count, comment_count, share_count, view_count,
                 follower_before, follower_after, friends_before, friends_after,
                 status, auto_check_note, points_awarded, credit_awarded, created_at, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"], mission_id, post_url, content_text, proof_file, mission["platform"],
                    form_values["like_count"], form_values["comment_count"], form_values["share_count"], form_values["view_count"],
                    form_values["follower_before"], form_values["follower_after"], form_values["friends_before"], form_values["friends_after"],
                    status, note, points, credit, now_text(), approved_at,
                ),
            )
            submission_id = cur.lastrowid
            if status == "auto_approved":
                add_points(conn, user["id"], submission_id, points, f"Hoàn thành nhiệm vụ: {mission['title']}")
                add_credit(conn, user["id"], credit, "earn", f"Credit từ nhiệm vụ: {mission['title']}")
                flash(f"Bài đã được duyệt tự động. Cộng {points} điểm và {credit} credit.", "success")
            else:
                flash("Bài đã được ghi nhận và chuyển vào danh sách cần kiểm tra.", "warning")
        return redirect(url_for("my_submissions"))

    return render_template("submit_mission.html", mission=mission)


@app.route("/my-submissions")
@login_required
def my_submissions():
    user = current_user()
    with db() as conn:
        rows = conn.execute(
            """
            SELECT s.*, m.title AS mission_title, m.mission_code
            FROM submissions s JOIN missions m ON m.id=s.mission_id
            WHERE s.user_id=? ORDER BY s.id DESC
            """,
            (user["id"],),
        ).fetchall()
    return render_template("my_submissions.html", submissions=rows)


@app.route("/wallet")
@login_required
def wallet():
    user = current_user()
    with db() as conn:
        credit_rows = conn.execute(
            "SELECT * FROM credit_transactions WHERE user_id=? ORDER BY id DESC LIMIT 100",
            (user["id"],),
        ).fetchall()
        point_rows = conn.execute(
            "SELECT * FROM point_transactions WHERE user_id=? ORDER BY id DESC LIMIT 100",
            (user["id"],),
        ).fetchall()
    return render_template("wallet.html", credit_rows=credit_rows, point_rows=point_rows)


@app.route("/search", methods=["GET", "POST"])
@login_required
def search():
    user = current_user()
    data = []
    log_id = None
    if request.method == "POST":
        keyword_str = request.form.get("keywords", "")
        keywords = [kw.strip() for kw in keyword_str.splitlines() if kw.strip()]
        lat = request.form.get("latitude", type=float)
        lng = request.form.get("longitude", type=float)
        radius_m = request.form.get("radius_m", type=int) or 0

        if not keywords:
            flash("Vui lòng nhập ít nhất 1 từ khóa.", "danger")
            return render_template("search.html", data=data)
        if lat is None or lng is None:
            flash("Vui lòng nhập vĩ độ và kinh độ.", "danger")
            return render_template("search.html", data=data)
        if len(keywords) > 20:
            flash("Mỗi lần tìm tối đa 20 từ khóa để tránh tốn quota API.", "danger")
            return render_template("search.html", data=data)

        credit_cost = len(keywords) * SEARCH_CREDIT_PER_KEYWORD
        with db() as conn:
            fresh_user = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if fresh_user["credit_balance"] < credit_cost:
                flash(f"Không đủ credit. Cần {credit_cost} credit, hiện có {fresh_user['credit_balance']} credit.", "danger")
                return render_template("search.html", data=data)

            data = scrape_from_keywords(keywords, center_coords=(lat, lng), radius_m=radius_m or None)
            add_credit(conn, user["id"], -credit_cost, "spend", f"Tìm kiếm Google Maps: {len(keywords)} từ khóa")
            cur = conn.execute(
                """
                INSERT INTO search_logs
                (user_id, keywords, latitude, longitude, radius_m, result_count, credit_cost, results_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"], "\n".join(keywords), lat, lng, radius_m, len(data), credit_cost,
                    json.dumps(data, ensure_ascii=False), now_text(),
                ),
            )
            log_id = cur.lastrowid
        flash(f"Đã tìm kiếm xong. Trừ {credit_cost} credit.", "success")

    return render_template("search.html", data=data, log_id=log_id,
                           search_credit_per_keyword=SEARCH_CREDIT_PER_KEYWORD,
                           export_excel_credit=EXPORT_EXCEL_CREDIT)


@app.route("/search/download/<int:log_id>")
@login_required
def download_search(log_id):
    user = current_user()
    with db() as conn:
        log = conn.execute("SELECT * FROM search_logs WHERE id=? AND user_id=?", (log_id, user["id"])).fetchone()
        if not log:
            abort(404)
        if not int(log["export_charged"] or 0):
            fresh_user = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if fresh_user["credit_balance"] < EXPORT_EXCEL_CREDIT:
                flash(f"Không đủ credit để xuất Excel. Cần {EXPORT_EXCEL_CREDIT} credit.", "danger")
                return redirect(url_for("search"))
            add_credit(conn, user["id"], -EXPORT_EXCEL_CREDIT, "spend", "Xuất Excel kết quả tìm kiếm")
            conn.execute("UPDATE search_logs SET export_charged=1 WHERE id=?", (log_id,))

        data = json.loads(log["results_json"] or "[]")

    output = io.BytesIO()
    df = pd.DataFrame(data)
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="KetQua")
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"npoil_leads_{log_id}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/leaderboard")
@login_required
def leaderboard():
    month = request.args.get("month", current_month())
    with db() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.name, u.group_type, u.department, u.distributor_name, u.dealer_name,
                   COALESCE(SUM(p.points),0) AS total_points,
                   COUNT(DISTINCT s.id) AS valid_posts,
                   u.credit_balance
            FROM users u
            LEFT JOIN point_transactions p ON p.user_id=u.id AND p.month_key=?
            LEFT JOIN submissions s ON s.user_id=u.id AND s.status IN ('auto_approved','approved')
            WHERE u.is_admin=0
            GROUP BY u.id
            ORDER BY total_points DESC, valid_posts DESC
            LIMIT 100
            """,
            (month,),
        ).fetchall()
    return render_template("leaderboard.html", rows=rows, month=month)


@app.route("/prizes")
@login_required
def prizes():
    """Trang hiển thị cơ cấu giải thưởng theo số lượng người đăng ký hợp lệ."""
    with db() as conn:
        participant_count = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE is_admin=0 AND status='active'"
        ).fetchone()["c"]

    prize_groups = [
        {
            "key": "under_30",
            "title": "Trường hợp dưới 30 thành viên đăng ký hợp lệ",
            "condition": "Dưới 30 người",
            "prizes": [
                {"name": "01 Giải Nhất", "value": "1.000.000 VNĐ"},
                {"name": "01 Giải Nhì", "value": "750.000 VNĐ"},
                {"name": "01 Giải Ba", "value": "500.000 VNĐ"},
            ],
        },
        {
            "key": "from_30_to_50",
            "title": "Trường hợp từ 30 - 50 thành viên đăng ký hợp lệ",
            "condition": "Từ 30 đến 50 người",
            "prizes": [
                {"name": "01 Giải Nhất", "value": "1.500.000 VNĐ"},
                {"name": "01 Giải Nhì", "value": "1.000.000 VNĐ"},
                {"name": "01 Giải Ba", "value": "750.000 VNĐ"},
            ],
        },
        {
            "key": "over_50",
            "title": "Trường hợp trên 50 thành viên đăng ký hợp lệ",
            "condition": "Trên 50 người",
            "prizes": [
                {"name": "01 Giải Nhất", "value": "2.000.000 VNĐ"},
                {"name": "01 Giải Nhì", "value": "1.500.000 VNĐ"},
                {"name": "01 Giải Ba", "value": "1.000.000 VNĐ"},
                {"name": "01 Giải Khuyến khích", "value": "500.000 VNĐ"},
            ],
        },
    ]

    if participant_count < 30:
        current_tier = "under_30"
    elif participant_count <= 50:
        current_tier = "from_30_to_50"
    else:
        current_tier = "over_50"

    special_award = {
        "name": "Nhà sáng tạo nội dung tốt nhất năm",
        "description": "Cuối chương trình xét chọn 01 cá nhân tiêu biểu dựa trên kết quả 06 tháng và mức độ phù hợp hình ảnh thương hiệu.",
    }

    return render_template(
        "prizes.html",
        participant_count=participant_count,
        prize_groups=prize_groups,
        current_tier=current_tier,
        special_award=special_award,
    )


# ===================== ADMIN =====================
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    with db() as conn:
        stats = {
            "users": conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_admin=0").fetchone()["c"],
            "missions": conn.execute("SELECT COUNT(*) AS c FROM missions").fetchone()["c"],
            "pending": conn.execute("SELECT COUNT(*) AS c FROM submissions WHERE status IN ('pending','need_review')").fetchone()["c"],
            "searches": conn.execute("SELECT COUNT(*) AS c FROM search_logs").fetchone()["c"],
        }
        latest = conn.execute(
            """
            SELECT s.*, u.name AS user_name, m.title AS mission_title
            FROM submissions s
            JOIN users u ON u.id=s.user_id
            JOIN missions m ON m.id=s.mission_id
            ORDER BY s.id DESC LIMIT 10
            """
        ).fetchall()
    return render_template("admin/dashboard.html", stats=stats, latest=latest)


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    with db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    return render_template("admin/users.html", users=rows)


@app.route("/admin/users/<int:user_id>/credit", methods=["POST"])
@login_required
@admin_required
def admin_adjust_credit(user_id):
    amount = int_form("amount")
    reason = request.form.get("reason", "Admin điều chỉnh credit").strip() or "Admin điều chỉnh credit"
    if amount == 0:
        flash("Số credit điều chỉnh không được bằng 0.", "danger")
        return redirect(url_for("admin_users"))
    try:
        with db() as conn:
            add_credit(conn, user_id, amount, "adjust", reason)
        flash("Đã điều chỉnh credit.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("admin_users"))


@app.route("/admin/missions", methods=["GET", "POST"])
@login_required
@admin_required
def admin_missions():
    if request.method == "POST":
        with db() as conn:
            conn.execute(
                """
                INSERT INTO missions
                (title, description, platform, mission_type, official_post_url, mission_code,
                 required_hashtags, points_reward, credit_reward, max_extra_points, max_per_day,
                 start_date, end_date, auto_approve, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.form.get("title", "").strip(),
                    request.form.get("description", "").strip(),
                    request.form.get("platform", "both"),
                    request.form.get("mission_type", "official_share"),
                    normalize_url(request.form.get("official_post_url", "")),
                    request.form.get("mission_code", "").strip(),
                    request.form.get("required_hashtags", REQUIRED_HASHTAGS_DEFAULT).strip(),
                    int_form("points_reward", 10),
                    int_form("credit_reward", 5),
                    int_form("max_extra_points", 100),
                    int_form("max_per_day", 2),
                    request.form.get("start_date", today_text()),
                    request.form.get("end_date", "2026-12-31"),
                    1 if request.form.get("auto_approve") == "on" else 0,
                    request.form.get("status", "active"),
                    now_text(),
                ),
            )
        flash("Đã tạo nhiệm vụ mới.", "success")
        return redirect(url_for("admin_missions"))

    with db() as conn:
        rows = conn.execute("SELECT * FROM missions ORDER BY id DESC").fetchall()
    return render_template("admin/missions.html", missions=rows, default_hashtags=REQUIRED_HASHTAGS_DEFAULT)


@app.route("/admin/missions/<int:mission_id>/toggle", methods=["POST"])
@login_required
@admin_required
def admin_toggle_mission(mission_id):
    with db() as conn:
        mission = conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
        if not mission:
            abort(404)
        new_status = "inactive" if mission["status"] == "active" else "active"
        conn.execute("UPDATE missions SET status=? WHERE id=?", (new_status, mission_id))
    flash("Đã cập nhật trạng thái nhiệm vụ.", "success")
    return redirect(url_for("admin_missions"))


@app.route("/admin/submissions")
@login_required
@admin_required
def admin_submissions():
    status = request.args.get("status", "pending")
    if status == "all":
        where = "1=1"
        params = ()
    elif status == "pending":
        where = "s.status IN ('pending','need_review')"
        params = ()
    else:
        where = "s.status=?"
        params = (status,)
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT s.*, u.name AS user_name, u.email, m.title AS mission_title, m.points_reward, m.credit_reward
            FROM submissions s
            JOIN users u ON u.id=s.user_id
            JOIN missions m ON m.id=s.mission_id
            WHERE {where}
            ORDER BY s.id DESC
            """,
            params,
        ).fetchall()
    return render_template("admin/submissions.html", submissions=rows, status=status)


@app.route("/admin/submissions/<int:submission_id>/approve", methods=["POST"])
@login_required
@admin_required
def admin_approve_submission(submission_id):
    admin_note = request.form.get("admin_note", "Admin duyệt").strip()
    with db() as conn:
        sub = conn.execute(
            """
            SELECT s.*, m.title AS mission_title, m.points_reward, m.credit_reward, m.max_extra_points
            FROM submissions s JOIN missions m ON m.id=s.mission_id
            WHERE s.id=?
            """,
            (submission_id,),
        ).fetchone()
        if not sub:
            abort(404)
        if sub["status"] in ("approved", "auto_approved"):
            flash("Bài này đã được duyệt trước đó.", "warning")
            return redirect(url_for("admin_submissions"))

        # Cho phép admin nhập điểm/credit thủ công, nếu bỏ trống dùng điểm hệ thống đề xuất
        points = int_form("points_awarded", None)
        credit = int_form("credit_awarded", None)
        if points is None or credit is None:
            # Tạo object giả gần giống mission để dùng lại hàm tính điểm
            mission_like = dict(sub)
            form_values = {
                "like_count": sub["like_count"],
                "comment_count": sub["comment_count"],
                "share_count": sub["share_count"],
                "view_count": sub["view_count"],
                "follower_before": sub["follower_before"],
                "follower_after": sub["follower_after"],
                "friends_before": sub["friends_before"],
                "friends_after": sub["friends_after"],
            }
            points, credit = calculate_submission_score(mission_like, form_values)

        conn.execute(
            """
            UPDATE submissions
            SET status='approved', points_awarded=?, credit_awarded=?, admin_note=?, approved_at=?
            WHERE id=?
            """,
            (points, credit, admin_note, now_text(), submission_id),
        )
        add_points(conn, sub["user_id"], submission_id, points, f"Admin duyệt nhiệm vụ: {sub['mission_title']}")
        add_credit(conn, sub["user_id"], credit, "earn", f"Admin duyệt nhiệm vụ: {sub['mission_title']}")
    flash("Đã duyệt bài và cộng điểm/credit.", "success")
    return redirect(url_for("admin_submissions"))


@app.route("/admin/submissions/<int:submission_id>/reject", methods=["POST"])
@login_required
@admin_required
def admin_reject_submission(submission_id):
    admin_note = request.form.get("admin_note", "Không hợp lệ").strip()
    with db() as conn:
        conn.execute(
            "UPDATE submissions SET status='rejected', admin_note=? WHERE id=?",
            (admin_note, submission_id),
        )
    flash("Đã từ chối bài gửi.", "info")
    return redirect(url_for("admin_submissions"))


@app.route("/admin/reports")
@login_required
@admin_required
def admin_reports():
    month = request.args.get("month", current_month())
    with db() as conn:
        rows = conn.execute(
            """
            SELECT u.name, u.email, u.group_type, u.department, u.distributor_name, u.dealer_name,
                   COALESCE(SUM(p.points),0) AS total_points,
                   COUNT(DISTINCT CASE WHEN s.status IN ('approved','auto_approved') THEN s.id END) AS valid_submissions,
                   COALESCE(SUM(CASE WHEN c.amount > 0 THEN c.amount ELSE 0 END),0) AS credit_earned,
                   ABS(COALESCE(SUM(CASE WHEN c.amount < 0 THEN c.amount ELSE 0 END),0)) AS credit_spent,
                   u.credit_balance
            FROM users u
            LEFT JOIN point_transactions p ON p.user_id=u.id AND p.month_key=?
            LEFT JOIN submissions s ON s.user_id=u.id
            LEFT JOIN credit_transactions c ON c.user_id=u.id AND substr(c.created_at,1,7)=?
            WHERE u.is_admin=0
            GROUP BY u.id
            ORDER BY total_points DESC
            """,
            (month, month),
        ).fetchall()
    return render_template("admin/reports.html", rows=rows, month=month)


@app.route("/admin/reports/download")
@login_required
@admin_required
def admin_reports_download():
    month = request.args.get("month", current_month())
    with db() as conn:
        rows = conn.execute(
            """
            SELECT u.name AS 'Họ tên', u.email AS 'Email', u.group_type AS 'Nhóm',
                   u.department AS 'Phòng ban', u.distributor_name AS 'Nhà phân phối',
                   u.dealer_name AS 'Đại lý',
                   COALESCE(SUM(p.points),0) AS 'Tổng điểm',
                   COUNT(DISTINCT CASE WHEN s.status IN ('approved','auto_approved') THEN s.id END) AS 'Bài hợp lệ',
                   u.credit_balance AS 'Credit hiện có'
            FROM users u
            LEFT JOIN point_transactions p ON p.user_id=u.id AND p.month_key=?
            LEFT JOIN submissions s ON s.user_id=u.id
            WHERE u.is_admin=0
            GROUP BY u.id
            ORDER BY 'Tổng điểm' DESC
            """,
            (month,),
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="BaoCao")
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"bao_cao_thi_dua_npoil_{month}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


init_db()

if __name__ == "__main__":
    app.run(debug=True)
