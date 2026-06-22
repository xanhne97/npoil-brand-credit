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

DEFAULT_SETTINGS = {
    # Credit tìm kiếm
    "search_credit_per_keyword": {"value": "5", "label": "Credit trừ cho mỗi từ khóa tìm kiếm"},
    "export_excel_credit": {"value": "10", "label": "Credit trừ khi xuất Excel"},

    # Công thức cộng điểm/credit khi duyệt từng bài gửi mới
    "like_points_divisor": {"value": "999999", "label": "DỰ PHÒNG AUTO: Bao nhiêu like/reaction được cộng 1 điểm khi hệ thống tự lấy chỉ số"},
    "comment_points": {"value": "0", "label": "DỰ PHÒNG AUTO: Điểm cộng cho mỗi comment khi hệ thống tự lấy chỉ số"},
    "share_points": {"value": "0", "label": "DỰ PHÒNG AUTO: Điểm cộng cho mỗi lượt share lại khi hệ thống tự lấy chỉ số"},
    "view_step": {"value": "999999", "label": "DỰ PHÒNG AUTO: Mốc view để cộng điểm khi hệ thống tự lấy chỉ số"},
    "view_step_points": {"value": "0", "label": "DỰ PHÒNG AUTO: Điểm cộng cho mỗi mốc view khi hệ thống tự lấy chỉ số"},
    "follower_points": {"value": "0", "label": "DỰ PHÒNG AUTO: Điểm cộng cho mỗi follow TikTok tăng khi hệ thống tự lấy chỉ số"},
    "friends_points_divisor": {"value": "999999", "label": "DỰ PHÒNG AUTO: Bao nhiêu bạn bè Facebook tăng được cộng 1 điểm khi hệ thống tự lấy chỉ số"},
    "extra_credit_divisor": {"value": "999999", "label": "DỰ PHÒNG AUTO: Bao nhiêu điểm cộng thêm từ chỉ số tự động được quy đổi 1 credit"},

    # Công thức xếp hạng công bằng theo tháng, tính tương đối trong cùng nhóm lọc
    "score_weight_tasks": {"value": "80", "label": "Tỷ trọng điểm nhiệm vụ/bài hợp lệ trong bảng xếp hạng tháng"},
    "score_weight_interactions": {"value": "0", "label": "Tỷ trọng điểm tương tác tự động trong bảng xếp hạng tháng - tạm tắt"},
    "score_weight_shares": {"value": "0", "label": "Tỷ trọng điểm lượt share lại tự động trong bảng xếp hạng tháng - tạm tắt"},
    "score_weight_growth": {"value": "0", "label": "Tỷ trọng điểm tăng trưởng follow/bạn bè tự động - tạm tắt"},
    "score_weight_compliance": {"value": "20", "label": "Tỷ trọng điểm tuân thủ bài chính thức/trọng điểm"},
    "min_valid_posts_for_winner": {"value": "6", "label": "Số bài/video hợp lệ tối thiểu để đủ điều kiện xét giải"},

    # V8 - Cơ chế tự động cấp 1: hệ thống tự kiểm tra, tự duyệt hoặc tự từ chối theo rule rõ ràng
    "auto_approve_passed_submissions": {"value": "1", "label": "Tự động duyệt bài đạt đủ điều kiện cơ bản"},
    "auto_reject_duplicate_link": {"value": "1", "label": "Tự động từ chối link đã được gửi trước đó"},
    "auto_reject_wrong_platform": {"value": "1", "label": "Tự động từ chối link sai nền tảng nhiệm vụ"},
    "auto_reject_outside_time": {"value": "1", "label": "Tự động từ chối bài ngoài thời gian nhiệm vụ"},
    "auto_reject_daily_limit": {"value": "1", "label": "Tự động từ chối khi vượt giới hạn bài/ngày"},
    "auto_reject_missing_code_hashtag": {"value": "0", "label": "Tự động từ chối khi thiếu mã nhiệm vụ/hashtag; 0 = chuyển admin kiểm tra"},
    "require_proof_for_auto_approve": {"value": "0", "label": "Bắt buộc có minh chứng mới được tự duyệt; 0 = không bắt buộc"},

    "leaderboard_comment_weight": {"value": "2", "label": "Hệ số comment khi tính chỉ số tương tác thô"},
    "leaderboard_view_unit": {"value": "100", "label": "Bao nhiêu view được tính là 1 đơn vị tương tác thô"},
    "leaderboard_view_weight": {"value": "1", "label": "Hệ số điểm thô cho mỗi đơn vị view"},
    "leaderboard_friends_growth_weight": {"value": "0.5", "label": "Hệ số quy đổi bạn bè Facebook tăng so với follow TikTok tăng"},
}

AUTOMATION_SETTING_KEYS = [
    "auto_approve_passed_submissions",
    "auto_reject_duplicate_link",
    "auto_reject_wrong_platform",
    "auto_reject_outside_time",
    "auto_reject_daily_limit",
    "auto_reject_missing_code_hashtag",
    "require_proof_for_auto_approve",
]


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


def get_inserted_id(cursor):
    """Return inserted id for SQLite or PostgreSQL queries that use RETURNING id."""
    try:
        row = cursor.fetchone()
        if row:
            try:
                return row["id"]
            except Exception:
                return row[0]
    except Exception:
        pass
    return getattr(cursor, "lastrowid", None)


def seed_default_settings(conn):
    for setting_key, meta in DEFAULT_SETTINGS.items():
        existing = conn.execute(
            "SELECT setting_key FROM app_settings WHERE setting_key=?",
            (setting_key,),
        ).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO app_settings (setting_key, setting_value, label, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (setting_key, meta["value"], meta["label"], now_text()),
            )

    # V7: bỏ cơ chế người dùng tự nhập like/share/follow vì dễ sai và khó kiểm soát.
    # Khi DB cũ đã có cấu hình V6, tự chuyển sang mô hình chấm theo nhiệm vụ + tuân thủ.
    # Các chỉ số tương tác/follow vẫn giữ trong database để giai đoạn sau lấy tự động từ API/OCR.
    flag = conn.execute(
        "SELECT setting_key FROM app_settings WHERE setting_key=?",
        ("system_v7_disable_manual_metrics",),
    ).fetchone()
    if not flag:
        v7_values = {
            "like_points_divisor": "999999",
            "comment_points": "0",
            "share_points": "0",
            "view_step": "999999",
            "view_step_points": "0",
            "follower_points": "0",
            "friends_points_divisor": "999999",
            "extra_credit_divisor": "999999",
            "score_weight_tasks": "80",
            "score_weight_interactions": "0",
            "score_weight_shares": "0",
            "score_weight_growth": "0",
            "score_weight_compliance": "20",
        }
        for key, value in v7_values.items():
            conn.execute(
                "UPDATE app_settings SET setting_value=?, updated_at=? WHERE setting_key=?",
                (value, now_text(), key),
            )
        conn.execute(
            "INSERT INTO app_settings (setting_key, setting_value, label, updated_at) VALUES (?, ?, ?, ?)",
            ("system_v7_disable_manual_metrics", "1", "Đã áp dụng V7: tắt nhập tay chỉ số tương tác/follow", now_text()),
        )


def get_app_settings(conn):
    settings = {key: meta["value"] for key, meta in DEFAULT_SETTINGS.items()}
    try:
        rows = conn.execute("SELECT setting_key, setting_value FROM app_settings").fetchall()
        for row in rows:
            settings[row["setting_key"]] = row["setting_value"]
    except Exception:
        pass
    return settings


def setting_int(settings, key, default=0):
    try:
        return int(float(settings.get(key, default)))
    except (ValueError, TypeError, AttributeError):
        return default


def setting_float(settings, key, default=0.0):
    try:
        return float(settings.get(key, default))
    except (ValueError, TypeError, AttributeError):
        return default



def row_value(row, key, default=0):
    try:
        value = row[key]
    except Exception:
        return default
    return default if value is None else value


def seed_default_prizes(conn):
    existing = conn.execute("SELECT COUNT(*) AS c FROM prize_tiers").fetchone()["c"]
    if existing:
        return

    defaults = [
        {
            "title": "Dưới 30 thành viên đăng ký hợp lệ",
            "min_participants": 0,
            "max_participants": 29,
            "note": "Áp dụng khi chương trình có dưới 30 người tham gia hợp lệ.",
            "items": [
                (1, "Giải Nhất", 1, 1000000),
                (2, "Giải Nhì", 1, 750000),
                (3, "Giải Ba", 1, 500000),
            ],
        },
        {
            "title": "Từ 30 - 50 thành viên đăng ký hợp lệ",
            "min_participants": 30,
            "max_participants": 50,
            "note": "Áp dụng khi chương trình có từ 30 đến 50 người tham gia hợp lệ.",
            "items": [
                (1, "Giải Nhất", 1, 1500000),
                (2, "Giải Nhì", 1, 1000000),
                (3, "Giải Ba", 1, 750000),
            ],
        },
        {
            "title": "Trên 50 thành viên đăng ký hợp lệ",
            "min_participants": 51,
            "max_participants": None,
            "note": "Áp dụng khi chương trình có trên 50 người tham gia hợp lệ.",
            "items": [
                (1, "Giải Nhất", 1, 2000000),
                (2, "Giải Nhì", 1, 1500000),
                (3, "Giải Ba", 1, 1000000),
                (4, "Giải Khuyến khích", 1, 500000),
            ],
        },
    ]

    for tier in defaults:
        insert_sql = """
            INSERT INTO prize_tiers
            (title, min_participants, max_participants, note, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        if USE_POSTGRES:
            insert_sql += " RETURNING id"
        cur = conn.execute(
            insert_sql,
            (
                tier["title"], tier["min_participants"], tier["max_participants"],
                tier["note"], 1, now_text(),
            ),
        )
        tier_id = get_inserted_id(cur)
        for rank_order, prize_name, quantity, prize_value in tier["items"]:
            conn.execute(
                """
                INSERT INTO prize_items
                (tier_id, prize_name, quantity, prize_value, rank_order, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (tier_id, prize_name, quantity, prize_value, rank_order, 1, now_text()),
            )


def participant_count_for_prize(conn):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE is_admin=0 AND status='active'"
    ).fetchone()["c"]


def get_active_prize_tier(conn, participant_count):
    return conn.execute(
        """
        SELECT * FROM prize_tiers
        WHERE active=1
          AND min_participants <= ?
          AND (max_participants IS NULL OR max_participants >= ?)
        ORDER BY min_participants DESC, id DESC
        LIMIT 1
        """,
        (participant_count, participant_count),
    ).fetchone()


def get_prize_tiers_with_items(conn, active_only=False):
    where = "WHERE active=1" if active_only else ""
    tiers = conn.execute(
        f"SELECT * FROM prize_tiers {where} ORDER BY min_participants ASC, id ASC"
    ).fetchall()
    result = []
    for tier in tiers:
        items = conn.execute(
            """
            SELECT * FROM prize_items
            WHERE tier_id=?
            ORDER BY rank_order ASC, id ASC
            """,
            (tier["id"],),
        ).fetchall()
        result.append({"tier": tier, "items": items})
    return result


def normalize_component(value, max_value, weight):
    value = float(value or 0)
    max_value = float(max_value or 0)
    weight = float(weight or 0)
    if max_value <= 0 or value <= 0 or weight <= 0:
        return 0.0
    return round((value / max_value) * weight, 2)


def get_fair_ranking_rows(conn, month, group_type="all", unit_keyword="", limit=None, prize_eligible_only=False, include_zero=False):
    """Return monthly leaderboard rows using fair relative scoring.

    V7 default ranking focuses on verified tasks and compliance.
    Interaction/share/growth columns are kept for future automatic fetching,
    but user-submitted manual numbers are no longer required.
    """
    settings = get_app_settings(conn)
    where_sql, filter_params = user_filter_sql(group_type, unit_keyword)
    where_sql = where_sql + " AND u.status='active'"

    rows = conn.execute(
        f"""
        SELECT u.id, u.name, u.email, u.group_type, u.department, u.distributor_name, u.dealer_name,
               u.credit_balance,
               COALESCE(st.valid_posts,0) AS valid_posts,
               COALESCE(st.base_task_points,0) AS base_task_points,
               COALESCE(st.total_likes,0) AS total_likes,
               COALESCE(st.total_comments,0) AS total_comments,
               COALESCE(st.total_shares,0) AS total_shares,
               COALESCE(st.total_views,0) AS total_views,
               COALESCE(st.follower_growth,0) AS follower_growth,
               COALESCE(st.friends_growth,0) AS friends_growth,
               COALESCE(st.compliance_count,0) AS compliance_count,
               COALESCE(st.raw_points_awarded,0) AS raw_points_awarded
        FROM users u
        LEFT JOIN (
            SELECT s.user_id,
                   COUNT(*) AS valid_posts,
                   SUM(COALESCE(m.points_reward,0)) AS base_task_points,
                   SUM(COALESCE(s.like_count,0)) AS total_likes,
                   SUM(COALESCE(s.comment_count,0)) AS total_comments,
                   SUM(COALESCE(s.share_count,0)) AS total_shares,
                   SUM(COALESCE(s.view_count,0)) AS total_views,
                   SUM(CASE WHEN s.follower_after > s.follower_before THEN s.follower_after - s.follower_before ELSE 0 END) AS follower_growth,
                   SUM(CASE WHEN s.friends_after > s.friends_before THEN s.friends_after - s.friends_before ELSE 0 END) AS friends_growth,
                   SUM(CASE WHEN m.mission_type IN ('official_share','priority','official_post') OR COALESCE(m.official_post_url,'') <> '' THEN 1 ELSE 0 END) AS compliance_count,
                   SUM(COALESCE(s.points_awarded,0)) AS raw_points_awarded
            FROM submissions s
            JOIN missions m ON m.id=s.mission_id
            WHERE s.status IN ('auto_approved','approved')
              AND substr(COALESCE(s.approved_at, s.created_at),1,7)=?
            GROUP BY s.user_id
        ) st ON st.user_id=u.id
        WHERE {where_sql}
        """,
        (month, *filter_params),
    ).fetchall()

    comment_weight = setting_float(settings, "leaderboard_comment_weight", 2)
    view_unit = max(1.0, setting_float(settings, "leaderboard_view_unit", 100))
    view_weight = setting_float(settings, "leaderboard_view_weight", 1)
    friends_growth_weight = setting_float(settings, "leaderboard_friends_growth_weight", 0.5)

    weight_tasks = setting_float(settings, "score_weight_tasks", 30)
    weight_interactions = setting_float(settings, "score_weight_interactions", 25)
    weight_shares = setting_float(settings, "score_weight_shares", 25)
    weight_growth = setting_float(settings, "score_weight_growth", 10)
    weight_compliance = setting_float(settings, "score_weight_compliance", 10)
    min_valid_posts = setting_int(settings, "min_valid_posts_for_winner", 6)

    prepared = []
    for row in rows:
        valid_posts = int(row_value(row, "valid_posts", 0) or 0)
        if not include_zero and valid_posts <= 0:
            continue
        if prize_eligible_only and valid_posts < min_valid_posts:
            continue

        total_likes = int(row_value(row, "total_likes", 0) or 0)
        total_comments = int(row_value(row, "total_comments", 0) or 0)
        total_views = int(row_value(row, "total_views", 0) or 0)
        total_shares = int(row_value(row, "total_shares", 0) or 0)
        follower_growth = int(row_value(row, "follower_growth", 0) or 0)
        friends_growth = int(row_value(row, "friends_growth", 0) or 0)
        base_task_points = float(row_value(row, "base_task_points", 0) or 0)
        compliance_count = int(row_value(row, "compliance_count", 0) or 0)

        raw_interactions = total_likes + (total_comments * comment_weight) + ((total_views / view_unit) * view_weight)
        growth_raw = follower_growth + (friends_growth * friends_growth_weight)

        item = dict(row)
        item.update({
            "task_raw": round(base_task_points, 2),
            "interaction_raw": round(raw_interactions, 2),
            "share_raw": total_shares,
            "growth_raw": round(growth_raw, 2),
            "compliance_raw": compliance_count,
            "min_valid_posts": min_valid_posts,
            "is_prize_eligible": valid_posts >= min_valid_posts,
        })
        prepared.append(item)

    max_task = max([x["task_raw"] for x in prepared] or [0])
    max_interaction = max([x["interaction_raw"] for x in prepared] or [0])
    max_share = max([x["share_raw"] for x in prepared] or [0])
    max_growth = max([x["growth_raw"] for x in prepared] or [0])
    max_compliance = max([x["compliance_raw"] for x in prepared] or [0])

    for item in prepared:
        item["score_tasks"] = normalize_component(item["task_raw"], max_task, weight_tasks)
        item["score_interactions"] = normalize_component(item["interaction_raw"], max_interaction, weight_interactions)
        item["score_shares"] = normalize_component(item["share_raw"], max_share, weight_shares)
        item["score_growth"] = normalize_component(item["growth_raw"], max_growth, weight_growth)
        item["score_compliance"] = normalize_component(item["compliance_raw"], max_compliance, weight_compliance)
        item["final_score"] = round(
            item["score_tasks"] + item["score_interactions"] + item["score_shares"] + item["score_growth"] + item["score_compliance"],
            2,
        )
        # Backward-compatible display field used by older templates.
        item["total_points"] = item["final_score"]

    prepared.sort(
        key=lambda x: (
            -x["final_score"],
            -int(x.get("valid_posts") or 0),
            -int(x.get("compliance_raw") or 0),
            -float(x.get("interaction_raw") or 0),
            -int(x.get("share_raw") or 0),
            -float(x.get("growth_raw") or 0),
            (x.get("name") or "").lower(),
        )
    )
    if limit:
        prepared = prepared[: int(limit)]
    return prepared


def get_ranking_rows(conn, month, limit=None):
    return get_fair_ranking_rows(conn, month, limit=limit, prize_eligible_only=True)


def user_filter_sql(group_type, unit_keyword):
    where = ["u.is_admin=0"]
    params = []
    if group_type and group_type != "all":
        where.append("u.group_type=?")
        params.append(group_type)
    if unit_keyword:
        like = f"%{unit_keyword.lower()}%"
        where.append(
            "(LOWER(COALESCE(u.department,'')) LIKE ? OR "
            "LOWER(COALESCE(u.distributor_name,'')) LIKE ? OR "
            "LOWER(COALESCE(u.dealer_name,'')) LIKE ? OR "
            "LOWER(COALESCE(u.name,'')) LIKE ? OR "
            "LOWER(COALESCE(u.email,'')) LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    return " AND ".join(where), params


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


@app.template_filter("vnd")
def format_vnd(value):
    try:
        amount = int(float(value or 0))
    except (TypeError, ValueError):
        amount = 0
    return f"{amount:,}".replace(",", ".") + " VNĐ"


def group_type_label(value):
    return {
        "employee": "Nhân viên",
        "distributor": "Nhà phân phối",
        "dealer": "Đại lý",
    }.get(value or "", value or "-")


def unit_name_from_row(row):
    if not row:
        return "-"
    try:
        return row["department"] or row["distributor_name"] or row["dealer_name"] or "-"
    except Exception:
        return "-"


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


def get_table_columns(conn, table_name):
    if USE_POSTGRES:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=?",
            (table_name,),
        ).fetchall()
        return {row["column_name"] for row in rows}
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def apply_schema_migrations(conn):
    """Add columns needed by newer versions without resetting existing data."""
    try:
        winner_cols = get_table_columns(conn, "monthly_winners")
        if "final_score" not in winner_cols:
            if USE_POSTGRES:
                conn.execute("ALTER TABLE monthly_winners ADD COLUMN final_score DOUBLE PRECISION NOT NULL DEFAULT 0")
            else:
                conn.execute("ALTER TABLE monthly_winners ADD COLUMN final_score REAL NOT NULL DEFAULT 0")
    except Exception:
        # Migration should never block the app from starting in demo/local mode.
        pass


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
            

            CREATE TABLE IF NOT EXISTS official_contents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'facebook',
                content_type TEXT NOT NULL DEFAULT 'official_share',
                official_post_url TEXT,
                suggested_caption TEXT,
                mission_code TEXT,
                required_hashtags TEXT,
                points_reward INTEGER NOT NULL DEFAULT 10,
                credit_reward INTEGER NOT NULL DEFAULT 5,
                max_per_day INTEGER NOT NULL DEFAULT 2,
                start_date TEXT,
                end_date TEXT,
                mission_id INTEGER,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                FOREIGN KEY(mission_id) REFERENCES missions(id)
            );
            
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                label TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prize_tiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                min_participants INTEGER NOT NULL DEFAULT 0,
                max_participants INTEGER,
                note TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prize_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tier_id INTEGER NOT NULL,
                prize_name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                prize_value INTEGER NOT NULL DEFAULT 0,
                rank_order INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY(tier_id) REFERENCES prize_tiers(id)
            );

            CREATE TABLE IF NOT EXISTS monthly_winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month_key TEXT NOT NULL,
                rank_no INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                email TEXT,
                group_type TEXT,
                unit_name TEXT,
                total_points INTEGER NOT NULL DEFAULT 0,
                final_score REAL NOT NULL DEFAULT 0,
                valid_posts INTEGER NOT NULL DEFAULT 0,
                prize_tier_title TEXT,
                prize_name TEXT NOT NULL,
                prize_value INTEGER NOT NULL DEFAULT 0,
                finalized_at TEXT NOT NULL,
                UNIQUE(month_key, user_id)
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
            

            CREATE TABLE IF NOT EXISTS official_contents (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'facebook',
                content_type TEXT NOT NULL DEFAULT 'official_share',
                official_post_url TEXT,
                suggested_caption TEXT,
                mission_code TEXT,
                required_hashtags TEXT,
                points_reward INTEGER NOT NULL DEFAULT 10,
                credit_reward INTEGER NOT NULL DEFAULT 5,
                max_per_day INTEGER NOT NULL DEFAULT 2,
                start_date TEXT,
                end_date TEXT,
                mission_id INTEGER REFERENCES missions(id),
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );
            
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                label TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prize_tiers (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                min_participants INTEGER NOT NULL DEFAULT 0,
                max_participants INTEGER,
                note TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prize_items (
                id SERIAL PRIMARY KEY,
                tier_id INTEGER NOT NULL REFERENCES prize_tiers(id),
                prize_name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                prize_value INTEGER NOT NULL DEFAULT 0,
                rank_order INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS monthly_winners (
                id SERIAL PRIMARY KEY,
                month_key TEXT NOT NULL,
                rank_no INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id),
                user_name TEXT NOT NULL,
                email TEXT,
                group_type TEXT,
                unit_name TEXT,
                total_points INTEGER NOT NULL DEFAULT 0,
                final_score REAL NOT NULL DEFAULT 0,
                valid_posts INTEGER NOT NULL DEFAULT 0,
                prize_tier_title TEXT,
                prize_name TEXT NOT NULL,
                prize_value INTEGER NOT NULL DEFAULT 0,
                finalized_at TEXT NOT NULL,
                UNIQUE(month_key, user_id)
            );
            """

    with db() as conn:
        conn.executescript(postgres_schema if USE_POSTGRES else sqlite_schema)
        apply_schema_migrations(conn)
        seed_default_settings(conn)
        seed_default_prizes(conn)

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


def create_mission_from_content(conn, content_row, auto_approve=1, status="active"):
    """Create a mission from one official content item and return mission id."""
    title = content_row["title"]
    description = "Chia sẻ/đăng lại nội dung chính thức từ kho nội dung công ty. Vui lòng giữ mã nhiệm vụ và hashtag bắt buộc trong caption."
    insert_sql = """
        INSERT INTO missions
        (title, description, platform, mission_type, official_post_url, mission_code,
         required_hashtags, points_reward, credit_reward, max_extra_points, max_per_day,
         start_date, end_date, auto_approve, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    if USE_POSTGRES:
        insert_sql += " RETURNING id"
    cur = conn.execute(
        insert_sql,
        (
            title,
            description,
            content_row["platform"] or "both",
            content_row["content_type"] or "official_share",
            normalize_url(content_row["official_post_url"] or ""),
            content_row["mission_code"] or "",
            content_row["required_hashtags"] or REQUIRED_HASHTAGS_DEFAULT,
            int(content_row["points_reward"] or 10),
            int(content_row["credit_reward"] or 5),
            100,
            int(content_row["max_per_day"] or 2),
            content_row["start_date"] or today_text(),
            content_row["end_date"] or "2026-12-31",
            int(auto_approve),
            status,
            now_text(),
        ),
    )
    return get_inserted_id(cur)

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


def calculate_submission_score(mission, form_values, settings=None):
    settings = settings or {key: meta["value"] for key, meta in DEFAULT_SETTINGS.items()}

    base_points = int(mission["points_reward"] or 0)
    base_credit = int(mission["credit_reward"] or 0)

    like_count = form_values["like_count"]
    comment_count = form_values["comment_count"]
    share_count = form_values["share_count"]
    view_count = form_values["view_count"]
    follower_growth = max(0, form_values["follower_after"] - form_values["follower_before"])
    friends_growth = max(0, form_values["friends_after"] - form_values["friends_before"])

    like_divisor = max(1, setting_int(settings, "like_points_divisor", 5))
    comment_points = setting_int(settings, "comment_points", 1)
    share_points = setting_int(settings, "share_points", 2)
    view_step = max(1, setting_int(settings, "view_step", 500))
    view_step_points = setting_int(settings, "view_step_points", 5)
    follower_points = setting_int(settings, "follower_points", 1)
    friends_divisor = max(1, setting_int(settings, "friends_points_divisor", 2))
    extra_credit_divisor = max(1, setting_int(settings, "extra_credit_divisor", 5))

    extra = 0
    extra += like_count // like_divisor
    extra += comment_count * comment_points
    extra += share_count * share_points
    extra += (view_count // view_step) * view_step_points
    extra += follower_growth * follower_points
    extra += friends_growth // friends_divisor
    extra = min(extra, int(mission["max_extra_points"] or 100))

    points = base_points + extra
    credit = base_credit + max(0, extra // extra_credit_divisor)
    return points, credit


def auto_setting_enabled(settings, key, default=1):
    return setting_int(settings, key, default) == 1


def auto_check_submission(conn, user_id, mission, post_url, content_text, proof_file=None, exclude_submission_id=None):
    """
    V8 automation engine cấp 1.
    Tự kiểm tra các điều kiện rõ ràng, không cần API Facebook/TikTok:
    - thời gian nhiệm vụ
    - link trùng
    - đúng nền tảng
    - mã nhiệm vụ
    - hashtag
    - giới hạn số bài/ngày
    - minh chứng nếu admin bật bắt buộc

    Kết quả có thể là:
    - auto_approved: đạt rule và nhiệm vụ cho phép tự duyệt
    - rejected: sai rule cứng như trùng link/sai nền tảng/hết hạn/vượt giới hạn
    - need_review: cần admin kiểm tra thêm
    - pending: đạt rule cơ bản nhưng nhiệm vụ tắt tự duyệt
    """
    settings = get_app_settings(conn)
    notes = []
    hard_errors = []
    soft_errors = []

    post_url = normalize_url(post_url)
    content_text = content_text or ""

    def add_rule_error(message, setting_key, default=1):
        if auto_setting_enabled(settings, setting_key, default):
            hard_errors.append(message)
        else:
            soft_errors.append(message)

    # Check thời gian nhiệm vụ
    today = date.today()
    start = parse_date(mission["start_date"])
    end = parse_date(mission["end_date"])
    if start and today < start:
        add_rule_error("Nhiệm vụ chưa bắt đầu", "auto_reject_outside_time", 1)
    if end and today > end:
        add_rule_error("Nhiệm vụ đã kết thúc", "auto_reject_outside_time", 1)

    # Check link trùng
    duplicate_sql = """
        SELECT id FROM submissions
        WHERE post_url=?
          AND status IN ('auto_approved','approved','pending','need_review','need_more_proof')
    """
    duplicate_params = [post_url]
    if exclude_submission_id:
        duplicate_sql += " AND id<>?"
        duplicate_params.append(exclude_submission_id)
    duplicate = conn.execute(duplicate_sql, tuple(duplicate_params)).fetchone()
    if duplicate:
        add_rule_error("Link bài đã được gửi trước đó", "auto_reject_duplicate_link", 1)

    # Check nền tảng
    if not platform_match(mission["platform"], post_url):
        add_rule_error(f"Link không đúng nền tảng yêu cầu: {mission['platform']}", "auto_reject_wrong_platform", 1)

    # Check mã nhiệm vụ
    mission_code = (mission["mission_code"] or "").strip()
    if mission_code and mission_code.lower() not in content_text.lower():
        add_rule_error(f"Thiếu mã nhiệm vụ: {mission_code}", "auto_reject_missing_code_hashtag", 0)

    # Check hashtag
    hashtags = (mission["required_hashtags"] or "").split()
    missing_hashtags = missing_tokens(content_text, hashtags)
    if missing_hashtags:
        add_rule_error("Thiếu hashtag: " + ", ".join(missing_hashtags), "auto_reject_missing_code_hashtag", 0)

    # Check minh chứng nếu admin bật bắt buộc
    if auto_setting_enabled(settings, "require_proof_for_auto_approve", 0) and not proof_file:
        soft_errors.append("Thiếu file/ảnh minh chứng nên chưa thể tự duyệt")

    # Check giới hạn bài/ngày/người theo nhiệm vụ
    max_per_day = int(mission["max_per_day"] or 2)
    today_start = today_text() + " 00:00:00"
    today_end = today_text() + " 23:59:59"
    count_today = conn.execute(
        """
        SELECT COUNT(*) AS c FROM submissions
        WHERE user_id=? AND mission_id=?
          AND status IN ('auto_approved','approved','pending','need_review','need_more_proof')
          AND created_at BETWEEN ? AND ?
        """,
        (user_id, mission["id"], today_start, today_end),
    ).fetchone()["c"]
    if count_today >= max_per_day:
        add_rule_error(f"Đã vượt giới hạn {max_per_day} bài/ngày cho nhiệm vụ này", "auto_reject_daily_limit", 1)

    if hard_errors:
        return "rejected", "Tự động từ chối: " + " | ".join(hard_errors + soft_errors)

    if soft_errors:
        return "need_review", "Cần admin kiểm tra: " + " | ".join(soft_errors)

    notes.append("Tự động kiểm tra hợp lệ: đúng link, đúng thời gian, đủ mã nhiệm vụ/hashtag, không trùng, không vượt giới hạn")
    if int(mission["auto_approve"] or 0) == 1 and auto_setting_enabled(settings, "auto_approve_passed_submissions", 1):
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



@app.route("/content-library")
@login_required
def content_library():
    """Kho nội dung chính thức để người tham gia lấy caption, mở bài gốc và gửi nhiệm vụ."""
    today = today_text()
    platform = request.args.get("platform", "all").strip()
    params = [today, today]
    where = "c.status='active' AND (c.start_date IS NULL OR c.start_date='' OR c.start_date<=?) AND (c.end_date IS NULL OR c.end_date='' OR c.end_date>=?)"
    if platform in ("facebook", "tiktok", "both"):
        where += " AND c.platform=?"
        params.append(platform)
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, m.status AS mission_status, m.title AS mission_title
            FROM official_contents c
            LEFT JOIN missions m ON m.id=c.mission_id
            WHERE {where}
            ORDER BY c.id DESC
            """,
            tuple(params),
        ).fetchall()
    return render_template("content_library.html", contents=rows, platform=platform)


@app.route("/content-library/<int:content_id>/copy")
@login_required
def content_library_detail(content_id):
    with db() as conn:
        content = conn.execute(
            """
            SELECT c.*, m.status AS mission_status, m.title AS mission_title
            FROM official_contents c
            LEFT JOIN missions m ON m.id=c.mission_id
            WHERE c.id=?
            """,
            (content_id,),
        ).fetchone()
    if not content:
        abort(404)
    return render_template("content_detail.html", content=content)

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

    content_id = request.args.get("content_id", "").strip()
    official_content = None
    if content_id.isdigit():
        with db() as conn:
            official_content = conn.execute("SELECT * FROM official_contents WHERE id=?", (int(content_id),)).fetchone()

    if request.method == "POST":
        post_url = normalize_url(request.form.get("post_url", ""))
        content_text = request.form.get("content_text", "").strip()
        if not post_url or not content_text:
            flash("Vui lòng nhập link bài và nội dung/caption có mã nhiệm vụ + hashtag.", "danger")
            return render_template("submit_mission.html", mission=mission, official_content=official_content)

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
            return render_template("submit_mission.html", mission=mission, official_content=official_content)

        with db() as conn:
            mission = conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
            status, note = auto_check_submission(conn, user["id"], mission, post_url, content_text, proof_file)
            points, credit = (0, 0)
            approved_at = None
            settings = get_app_settings(conn)
            if status == "auto_approved":
                points, credit = calculate_submission_score(mission, form_values, settings)
                approved_at = now_text()

            insert_sql = """
                INSERT INTO submissions
                (user_id, mission_id, post_url, content_text, proof_file, platform,
                 like_count, comment_count, share_count, view_count,
                 follower_before, follower_after, friends_before, friends_after,
                 status, auto_check_note, points_awarded, credit_awarded, created_at, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if USE_POSTGRES:
                insert_sql += " RETURNING id"
            cur = conn.execute(
                insert_sql,
                (
                    user["id"], mission_id, post_url, content_text, proof_file, mission["platform"],
                    form_values["like_count"], form_values["comment_count"], form_values["share_count"], form_values["view_count"],
                    form_values["follower_before"], form_values["follower_after"], form_values["friends_before"], form_values["friends_after"],
                    status, note, points, credit, now_text(), approved_at,
                ),
            )
            submission_id = get_inserted_id(cur)
            if status == "auto_approved":
                add_points(conn, user["id"], submission_id, points, f"Hoàn thành nhiệm vụ: {mission['title']}")
                add_credit(conn, user["id"], credit, "earn", f"Credit từ nhiệm vụ: {mission['title']}")
                flash(f"Bài đã được duyệt tự động. Cộng {points} điểm và {credit} credit.", "success")
            elif status == "rejected":
                flash("Bài bị hệ thống tự động từ chối: " + note, "danger")
            else:
                flash("Bài đã được ghi nhận và chuyển vào danh sách cần kiểm tra.", "warning")
        return redirect(url_for("my_submissions"))

    return render_template("submit_mission.html", mission=mission, official_content=official_content)


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

        with db() as conn:
            settings = get_app_settings(conn)
            search_credit_per_keyword = setting_int(settings, "search_credit_per_keyword", SEARCH_CREDIT_PER_KEYWORD)
            credit_cost = len(keywords) * search_credit_per_keyword
            fresh_user = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if fresh_user["credit_balance"] < credit_cost:
                flash(f"Không đủ credit. Cần {credit_cost} credit, hiện có {fresh_user['credit_balance']} credit.", "danger")
                return render_template("search.html", data=data)

            data = scrape_from_keywords(keywords, center_coords=(lat, lng), radius_m=radius_m or None)
            add_credit(conn, user["id"], -credit_cost, "spend", f"Tìm kiếm Google Maps: {len(keywords)} từ khóa")
            insert_sql = """
                INSERT INTO search_logs
                (user_id, keywords, latitude, longitude, radius_m, result_count, credit_cost, results_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if USE_POSTGRES:
                insert_sql += " RETURNING id"
            cur = conn.execute(
                insert_sql,
                (
                    user["id"], "\n".join(keywords), lat, lng, radius_m, len(data), credit_cost,
                    json.dumps(data, ensure_ascii=False), now_text(),
                ),
            )
            log_id = get_inserted_id(cur)
        flash(f"Đã tìm kiếm xong. Trừ {credit_cost} credit.", "success")

    with db() as conn:
        settings = get_app_settings(conn)
    return render_template("search.html", data=data, log_id=log_id,
                           search_credit_per_keyword=setting_int(settings, "search_credit_per_keyword", SEARCH_CREDIT_PER_KEYWORD),
                           export_excel_credit=setting_int(settings, "export_excel_credit", EXPORT_EXCEL_CREDIT))


@app.route("/search/download/<int:log_id>")
@login_required
def download_search(log_id):
    user = current_user()
    with db() as conn:
        log = conn.execute("SELECT * FROM search_logs WHERE id=? AND user_id=?", (log_id, user["id"])).fetchone()
        if not log:
            abort(404)
        settings = get_app_settings(conn)
        export_excel_credit = setting_int(settings, "export_excel_credit", EXPORT_EXCEL_CREDIT)
        if not int(log["export_charged"] or 0):
            fresh_user = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if fresh_user["credit_balance"] < export_excel_credit:
                flash(f"Không đủ credit để xuất Excel. Cần {export_excel_credit} credit.", "danger")
                return redirect(url_for("search"))
            add_credit(conn, user["id"], -export_excel_credit, "spend", "Xuất Excel kết quả tìm kiếm")
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
    month = request.args.get("month", current_month()).strip() or current_month()
    group_type = request.args.get("group_type", "all").strip() or "all"
    unit = request.args.get("unit", "").strip()
    with db() as conn:
        rows = get_fair_ranking_rows(conn, month, group_type, unit, limit=100, prize_eligible_only=False, include_zero=False)
    return render_template("leaderboard.html", rows=rows, month=month, group_type=group_type, unit=unit)


@app.route("/prizes")
@login_required
def prizes():
    """Trang hiển thị cơ cấu giải thưởng động từ database."""
    with db() as conn:
        participant_count = participant_count_for_prize(conn)
        current_tier = get_active_prize_tier(conn, participant_count)
        prize_groups = get_prize_tiers_with_items(conn, active_only=True)
        latest_winners = conn.execute(
            """
            SELECT * FROM monthly_winners
            ORDER BY month_key DESC, rank_no ASC
            LIMIT 5
            """
        ).fetchall()

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
        latest_winners=latest_winners,
    )


@app.route("/winners")
@login_required
def winners():
    month = request.args.get("month", "").strip()
    with db() as conn:
        months = conn.execute(
            "SELECT DISTINCT month_key FROM monthly_winners ORDER BY month_key DESC"
        ).fetchall()
        if not month and months:
            month = months[0]["month_key"]
        if not month:
            month = current_month()
        rows = conn.execute(
            "SELECT * FROM monthly_winners WHERE month_key=? ORDER BY rank_no ASC",
            (month,),
        ).fetchall()
    return render_template("winners.html", rows=rows, months=months, month=month)


# ===================== ADMIN =====================
@app.route("/admin/prizes", methods=["GET", "POST"])
@login_required
@admin_required
def admin_prizes():
    if request.method == "POST":
        action = request.form.get("action", "").strip()
        with db() as conn:
            if action == "create_tier":
                max_raw = request.form.get("max_participants", "").strip()
                max_participants = int(max_raw) if max_raw else None
                conn.execute(
                    """
                    INSERT INTO prize_tiers
                    (title, min_participants, max_participants, note, active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.form.get("title", "").strip(),
                        int_form("min_participants", 0),
                        max_participants,
                        request.form.get("note", "").strip(),
                        1 if request.form.get("active") == "on" else 0,
                        now_text(),
                    ),
                )
                flash("Đã thêm mốc giải thưởng.", "success")
            elif action == "update_tier":
                tier_id = int_form("tier_id")
                max_raw = request.form.get("max_participants", "").strip()
                max_participants = int(max_raw) if max_raw else None
                conn.execute(
                    """
                    UPDATE prize_tiers
                    SET title=?, min_participants=?, max_participants=?, note=?, active=?
                    WHERE id=?
                    """,
                    (
                        request.form.get("title", "").strip(),
                        int_form("min_participants", 0),
                        max_participants,
                        request.form.get("note", "").strip(),
                        1 if request.form.get("active") == "on" else 0,
                        tier_id,
                    ),
                )
                flash("Đã cập nhật mốc giải thưởng.", "success")
            elif action == "create_item":
                conn.execute(
                    """
                    INSERT INTO prize_items
                    (tier_id, prize_name, quantity, prize_value, rank_order, active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int_form("tier_id"),
                        request.form.get("prize_name", "").strip(),
                        max(1, int_form("quantity", 1)),
                        max(0, int_form("prize_value", 0)),
                        max(1, int_form("rank_order", 1)),
                        1 if request.form.get("active") == "on" else 0,
                        now_text(),
                    ),
                )
                flash("Đã thêm giải thưởng trong mốc.", "success")
            elif action == "update_item":
                conn.execute(
                    """
                    UPDATE prize_items
                    SET prize_name=?, quantity=?, prize_value=?, rank_order=?, active=?
                    WHERE id=?
                    """,
                    (
                        request.form.get("prize_name", "").strip(),
                        max(1, int_form("quantity", 1)),
                        max(0, int_form("prize_value", 0)),
                        max(1, int_form("rank_order", 1)),
                        1 if request.form.get("active") == "on" else 0,
                        int_form("item_id"),
                    ),
                )
                flash("Đã cập nhật giải thưởng.", "success")
            elif action == "delete_item":
                conn.execute("DELETE FROM prize_items WHERE id=?", (int_form("item_id"),))
                flash("Đã xóa giải thưởng.", "info")
        return redirect(url_for("admin_prizes"))

    with db() as conn:
        participant_count = participant_count_for_prize(conn)
        current_tier = get_active_prize_tier(conn, participant_count)
        groups = get_prize_tiers_with_items(conn, active_only=False)
    return render_template(
        "admin/prizes.html",
        groups=groups,
        participant_count=participant_count,
        current_tier=current_tier,
    )


@app.route("/admin/winners")
@login_required
@admin_required
def admin_winners():
    month = request.args.get("month", current_month()).strip() or current_month()
    with db() as conn:
        participant_count = participant_count_for_prize(conn)
        current_tier = get_active_prize_tier(conn, participant_count)
        prize_items = []
        if current_tier:
            prize_items = conn.execute(
                """
                SELECT * FROM prize_items
                WHERE tier_id=? AND active=1
                ORDER BY rank_order ASC, id ASC
                """,
                (current_tier["id"],),
            ).fetchall()
        winners_rows = conn.execute(
            "SELECT * FROM monthly_winners WHERE month_key=? ORDER BY rank_no ASC",
            (month,),
        ).fetchall()
        ranking_preview = get_ranking_rows(conn, month, limit=20)
    return render_template(
        "admin/winners.html",
        month=month,
        participant_count=participant_count,
        current_tier=current_tier,
        prize_items=prize_items,
        winners=winners_rows,
        ranking_preview=ranking_preview,
    )


@app.route("/admin/winners/close", methods=["POST"])
@login_required
@admin_required
def admin_close_winners():
    month = request.form.get("month", current_month()).strip() or current_month()
    with db() as conn:
        participant_count = participant_count_for_prize(conn)
        current_tier = get_active_prize_tier(conn, participant_count)
        if not current_tier:
            flash("Chưa có mốc giải thưởng phù hợp. Vui lòng cấu hình tại Admin → Giải thưởng.", "danger")
            return redirect(url_for("admin_winners", month=month))
        prize_items = conn.execute(
            """
            SELECT * FROM prize_items
            WHERE tier_id=? AND active=1
            ORDER BY rank_order ASC, id ASC
            """,
            (current_tier["id"],),
        ).fetchall()
        slots = []
        for item in prize_items:
            for _ in range(max(1, int(item["quantity"] or 1))):
                slots.append(item)
        if not slots:
            flash("Mốc giải hiện tại chưa có giải thưởng active.", "danger")
            return redirect(url_for("admin_winners", month=month))

        ranking_rows = get_ranking_rows(conn, month, limit=len(slots))
        if not ranking_rows:
            flash("Chưa có người đủ điều kiện để chốt giải trong tháng này.", "warning")
            return redirect(url_for("admin_winners", month=month))

        conn.execute("DELETE FROM monthly_winners WHERE month_key=?", (month,))
        finalized_at = now_text()
        for idx, (ranker, prize) in enumerate(zip(ranking_rows, slots), start=1):
            conn.execute(
                """
                INSERT INTO monthly_winners
                (month_key, rank_no, user_id, user_name, email, group_type, unit_name,
                 total_points, final_score, valid_posts, prize_tier_title, prize_name, prize_value, finalized_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    month,
                    idx,
                    ranker["id"],
                    ranker["name"],
                    ranker["email"],
                    ranker["group_type"],
                    unit_name_from_row(ranker),
                    int(round(float(ranker["final_score"] or 0))),
                    float(ranker["final_score"] or 0),
                    int(ranker["valid_posts"] or 0),
                    current_tier["title"],
                    prize["prize_name"],
                    int(prize["prize_value"] or 0),
                    finalized_at,
                ),
            )
    flash(f"Đã chốt {min(len(ranking_rows), len(slots))} giải thưởng cho tháng {month}.", "success")
    return redirect(url_for("admin_winners", month=month))


@app.route("/admin/winners/download")
@login_required
@admin_required
def admin_winners_download():
    month = request.args.get("month", current_month()).strip() or current_month()
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM monthly_winners WHERE month_key=? ORDER BY rank_no ASC",
            (month,),
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df = df.rename(columns={
            "month_key": "Tháng",
            "rank_no": "Hạng",
            "user_name": "Họ tên",
            "email": "Email",
            "group_type": "Nhóm",
            "unit_name": "Đơn vị",
            "total_points": "Điểm làm tròn",
            "final_score": "Điểm xếp hạng 100",
            "valid_posts": "Bài hợp lệ",
            "prize_tier_title": "Mốc giải",
            "prize_name": "Tên giải",
            "prize_value": "Giá trị giải",
            "finalized_at": "Thời gian chốt",
        })
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="DanhSachTraoGiai")
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"danh_sach_trao_giai_npoil_{month}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    with db() as conn:
        stats = {
            "users": conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_admin=0").fetchone()["c"],
            "missions": conn.execute("SELECT COUNT(*) AS c FROM missions").fetchone()["c"],
            "contents": conn.execute("SELECT COUNT(*) AS c FROM official_contents").fetchone()["c"],
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



@app.route("/admin/content-library", methods=["GET", "POST"])
@login_required
@admin_required
def admin_content_library():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Vui lòng nhập tiêu đề nội dung.", "danger")
            return redirect(url_for("admin_content_library"))
        with db() as conn:
            content_insert = """
                INSERT INTO official_contents
                (title, platform, content_type, official_post_url, suggested_caption, mission_code,
                 required_hashtags, points_reward, credit_reward, max_per_day, start_date, end_date,
                 mission_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if USE_POSTGRES:
                content_insert += " RETURNING id"
            mission_id = None
            temp_row = {
                "title": title,
                "platform": request.form.get("platform", "facebook"),
                "content_type": request.form.get("content_type", "official_share"),
                "official_post_url": normalize_url(request.form.get("official_post_url", "")),
                "suggested_caption": request.form.get("suggested_caption", "").strip(),
                "mission_code": request.form.get("mission_code", "").strip(),
                "required_hashtags": request.form.get("required_hashtags", REQUIRED_HASHTAGS_DEFAULT).strip(),
                "points_reward": int_form("points_reward", 10),
                "credit_reward": int_form("credit_reward", 5),
                "max_per_day": int_form("max_per_day", 2),
                "start_date": request.form.get("start_date", today_text()),
                "end_date": request.form.get("end_date", "2026-12-31"),
            }
            if request.form.get("create_mission") == "on":
                mission_id = create_mission_from_content(conn, temp_row, auto_approve=1, status="active")
            cur = conn.execute(
                content_insert,
                (
                    temp_row["title"], temp_row["platform"], temp_row["content_type"], temp_row["official_post_url"],
                    temp_row["suggested_caption"], temp_row["mission_code"], temp_row["required_hashtags"],
                    temp_row["points_reward"], temp_row["credit_reward"], temp_row["max_per_day"],
                    temp_row["start_date"], temp_row["end_date"], mission_id,
                    request.form.get("status", "active"), now_text(),
                ),
            )
            content_id = get_inserted_id(cur)
        if mission_id:
            flash("Đã thêm nội dung chính thức và tạo nhiệm vụ tương ứng.", "success")
        else:
            flash("Đã thêm nội dung chính thức.", "success")
        return redirect(url_for("admin_content_library"))

    with db() as conn:
        rows = conn.execute(
            """
            SELECT c.*, m.title AS mission_title, m.status AS mission_status
            FROM official_contents c
            LEFT JOIN missions m ON m.id=c.mission_id
            ORDER BY c.id DESC
            """
        ).fetchall()
    return render_template("admin/content_library.html", contents=rows, default_hashtags=REQUIRED_HASHTAGS_DEFAULT)


@app.route("/admin/content-library/<int:content_id>/toggle", methods=["POST"])
@login_required
@admin_required
def admin_toggle_content(content_id):
    with db() as conn:
        content = conn.execute("SELECT * FROM official_contents WHERE id=?", (content_id,)).fetchone()
        if not content:
            abort(404)
        new_status = "inactive" if content["status"] == "active" else "active"
        conn.execute("UPDATE official_contents SET status=? WHERE id=?", (new_status, content_id))
    flash("Đã cập nhật trạng thái nội dung.", "success")
    return redirect(url_for("admin_content_library"))


@app.route("/admin/content-library/<int:content_id>/create-mission", methods=["POST"])
@login_required
@admin_required
def admin_content_create_mission(content_id):
    with db() as conn:
        content = conn.execute("SELECT * FROM official_contents WHERE id=?", (content_id,)).fetchone()
        if not content:
            abort(404)
        if content["mission_id"]:
            flash("Nội dung này đã liên kết với nhiệm vụ rồi.", "warning")
            return redirect(url_for("admin_content_library"))
        mission_id = create_mission_from_content(conn, content, auto_approve=1, status="active")
        conn.execute("UPDATE official_contents SET mission_id=? WHERE id=?", (mission_id, content_id))
    flash("Đã tạo nhiệm vụ từ nội dung chính thức.", "success")
    return redirect(url_for("admin_content_library"))

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
            settings = get_app_settings(conn)
            points, credit = calculate_submission_score(mission_like, form_values, settings)

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


@app.route("/admin/submissions/<int:submission_id>/need-proof", methods=["POST"])
@login_required
@admin_required
def admin_need_proof_submission(submission_id):
    admin_note = request.form.get("admin_note", "Vui lòng bổ sung minh chứng rõ hơn.").strip()
    with db() as conn:
        conn.execute(
            "UPDATE submissions SET status='need_more_proof', admin_note=? WHERE id=?",
            (admin_note, submission_id),
        )
    flash("Đã yêu cầu người dùng bổ sung minh chứng.", "warning")
    return redirect(url_for("admin_submissions", status="need_more_proof"))


@app.route("/submissions/<int:submission_id>/update-proof", methods=["POST"])
@login_required
def update_submission_proof(submission_id):
    user = current_user()
    try:
        proof_file = save_upload(request.files.get("proof_file"))
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("my_submissions"))
    if not proof_file:
        flash("Vui lòng chọn file minh chứng để bổ sung.", "danger")
        return redirect(url_for("my_submissions"))

    with db() as conn:
        sub = conn.execute(
            "SELECT * FROM submissions WHERE id=? AND user_id=?",
            (submission_id, user["id"]),
        ).fetchone()
        if not sub:
            abort(404)
        if sub["status"] != "need_more_proof":
            flash("Bài này không ở trạng thái cần bổ sung minh chứng.", "warning")
            return redirect(url_for("my_submissions"))
        conn.execute(
            """
            UPDATE submissions
            SET proof_file=?, status='need_review', auto_check_note=?, admin_note=NULL
            WHERE id=?
            """,
            (proof_file, "Người dùng đã bổ sung minh chứng, chờ admin kiểm tra lại.", submission_id),
        )
    flash("Đã bổ sung minh chứng. Bài được chuyển lại cho admin kiểm tra.", "success")
    return redirect(url_for("my_submissions"))


@app.route("/admin/reports")
@login_required
@admin_required
def admin_reports():
    month = request.args.get("month", current_month()).strip() or current_month()
    group_type = request.args.get("group_type", "all").strip() or "all"
    unit = request.args.get("unit", "").strip()
    with db() as conn:
        rows = get_fair_ranking_rows(conn, month, group_type, unit, include_zero=True)
        submission_stats = conn.execute(
            """
            SELECT user_id,
                   SUM(CASE WHEN status IN ('approved','auto_approved') THEN 1 ELSE 0 END) AS valid_submissions,
                   SUM(CASE WHEN status IN ('pending','need_review','need_more_proof') THEN 1 ELSE 0 END) AS pending_submissions,
                   SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected_submissions
            FROM submissions
            WHERE substr(created_at,1,7)=?
            GROUP BY user_id
            """,
            (month,),
        ).fetchall()
        credit_stats = conn.execute(
            """
            SELECT user_id,
                   SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS credit_earned,
                   ABS(SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END)) AS credit_spent
            FROM credit_transactions
            WHERE substr(created_at,1,7)=?
            GROUP BY user_id
            """,
            (month,),
        ).fetchall()
        search_stats = conn.execute(
            """
            SELECT user_id, COUNT(*) AS search_count, SUM(credit_cost) AS search_credit_cost
            FROM search_logs
            WHERE substr(created_at,1,7)=?
            GROUP BY user_id
            """,
            (month,),
        ).fetchall()

    sub_map = {r["user_id"]: dict(r) for r in submission_stats}
    credit_map = {r["user_id"]: dict(r) for r in credit_stats}
    search_map = {r["user_id"]: dict(r) for r in search_stats}
    for row in rows:
        sub = sub_map.get(row["id"], {})
        cred = credit_map.get(row["id"], {})
        sea = search_map.get(row["id"], {})
        row["valid_submissions"] = int(row.get("valid_posts") or sub.get("valid_submissions") or 0)
        row["pending_submissions"] = int(sub.get("pending_submissions") or 0)
        row["rejected_submissions"] = int(sub.get("rejected_submissions") or 0)
        row["credit_earned"] = int(cred.get("credit_earned") or 0)
        row["credit_spent"] = int(cred.get("credit_spent") or 0)
        row["search_count"] = int(sea.get("search_count") or 0)
        row["search_credit_cost"] = int(sea.get("search_credit_cost") or 0)
    return render_template("admin/reports.html", rows=rows, month=month, group_type=group_type, unit=unit)


@app.route("/admin/reports/download")
@login_required
@admin_required
def admin_reports_download():
    month = request.args.get("month", current_month()).strip() or current_month()
    group_type = request.args.get("group_type", "all").strip() or "all"
    unit = request.args.get("unit", "").strip()
    with db() as conn:
        rows = get_fair_ranking_rows(conn, month, group_type, unit, include_zero=True)
        submission_stats = conn.execute(
            """
            SELECT user_id,
                   SUM(CASE WHEN status IN ('approved','auto_approved') THEN 1 ELSE 0 END) AS valid_submissions,
                   SUM(CASE WHEN status IN ('pending','need_review','need_more_proof') THEN 1 ELSE 0 END) AS pending_submissions,
                   SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected_submissions
            FROM submissions
            WHERE substr(created_at,1,7)=?
            GROUP BY user_id
            """,
            (month,),
        ).fetchall()
        credit_stats = conn.execute(
            """
            SELECT user_id,
                   SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS credit_earned,
                   ABS(SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END)) AS credit_spent
            FROM credit_transactions
            WHERE substr(created_at,1,7)=?
            GROUP BY user_id
            """,
            (month,),
        ).fetchall()
        search_stats = conn.execute(
            """
            SELECT user_id, COUNT(*) AS search_count, SUM(credit_cost) AS search_credit_cost
            FROM search_logs
            WHERE substr(created_at,1,7)=?
            GROUP BY user_id
            """,
            (month,),
        ).fetchall()
    sub_map = {r["user_id"]: dict(r) for r in submission_stats}
    credit_map = {r["user_id"]: dict(r) for r in credit_stats}
    search_map = {r["user_id"]: dict(r) for r in search_stats}
    export_rows = []
    for idx, row in enumerate(rows, start=1):
        sub = sub_map.get(row["id"], {})
        cred = credit_map.get(row["id"], {})
        sea = search_map.get(row["id"], {})
        export_rows.append({
            "Hạng": idx,
            "Họ tên": row.get("name"),
            "Email": row.get("email"),
            "Nhóm": row.get("group_type"),
            "Phòng ban": row.get("department"),
            "Nhà phân phối": row.get("distributor_name"),
            "Đại lý": row.get("dealer_name"),
            "Điểm xếp hạng 100": row.get("final_score"),
            "Điểm nhiệm vụ": row.get("score_tasks"),
            "Điểm tương tác": row.get("score_interactions"),
            "Điểm share": row.get("score_shares"),
            "Điểm tăng trưởng": row.get("score_growth"),
            "Điểm tuân thủ": row.get("score_compliance"),
            "Bài hợp lệ": row.get("valid_posts"),
            "Bài chờ": int(sub.get("pending_submissions") or 0),
            "Bài từ chối": int(sub.get("rejected_submissions") or 0),
            "Like": row.get("total_likes"),
            "Comment": row.get("total_comments"),
            "Share": row.get("total_shares"),
            "View": row.get("total_views"),
            "Follow tăng": row.get("follower_growth"),
            "Bạn bè tăng": row.get("friends_growth"),
            "Credit nhận": int(cred.get("credit_earned") or 0),
            "Credit đã dùng": int(cred.get("credit_spent") or 0),
            "Số lượt tìm kiếm": int(sea.get("search_count") or 0),
            "Credit tìm kiếm": int(sea.get("search_credit_cost") or 0),
            "Credit hiện có": row.get("credit_balance"),
            "Đủ điều kiện xét giải": "Có" if row.get("is_prize_eligible") else "Không",
        })
    df = pd.DataFrame(export_rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="BaoCaoCongBang")
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"bao_cao_thi_dua_cong_bang_npoil_{month}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/admin/automation", methods=["GET", "POST"])
@login_required
@admin_required
def admin_automation():
    if request.method == "POST":
        with db() as conn:
            for key in AUTOMATION_SETTING_KEYS:
                # Checkbox: có tick = 1, không tick = 0
                value = "1" if request.form.get(key) == "on" else "0"
                conn.execute(
                    """
                    UPDATE app_settings
                    SET setting_value=?, updated_at=?
                    WHERE setting_key=?
                    """,
                    (value, now_text(), key),
                )
        flash("Đã cập nhật cơ chế tự động.", "success")
        return redirect(url_for("admin_automation"))

    with db() as conn:
        settings = get_app_settings(conn)
        stats = {
            "auto_approved": conn.execute("SELECT COUNT(*) AS c FROM submissions WHERE status='auto_approved'").fetchone()["c"],
            "need_review": conn.execute("SELECT COUNT(*) AS c FROM submissions WHERE status IN ('pending','need_review')").fetchone()["c"],
            "rejected": conn.execute("SELECT COUNT(*) AS c FROM submissions WHERE status='rejected'").fetchone()["c"],
            "need_more_proof": conn.execute("SELECT COUNT(*) AS c FROM submissions WHERE status='need_more_proof'").fetchone()["c"],
        }
    rules = [
        {"key": key, "label": DEFAULT_SETTINGS[key]["label"], "value": settings.get(key, DEFAULT_SETTINGS[key]["value"])}
        for key in AUTOMATION_SETTING_KEYS
    ]
    return render_template("admin/automation.html", rules=rules, stats=stats)


@app.route("/admin/automation/run", methods=["POST"])
@login_required
@admin_required
def admin_run_automation():
    scanned = 0
    auto_approved = 0
    rejected = 0
    need_review = 0
    pending = 0

    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM submissions
            WHERE status IN ('pending','need_review')
            ORDER BY id ASC
            LIMIT 200
            """
        ).fetchall()
        settings = get_app_settings(conn)

        for sub in rows:
            mission = conn.execute("SELECT * FROM missions WHERE id=?", (sub["mission_id"],)).fetchone()
            if not mission:
                continue
            scanned += 1
            status, note = auto_check_submission(
                conn,
                sub["user_id"],
                mission,
                sub["post_url"],
                sub["content_text"] or "",
                sub["proof_file"],
                exclude_submission_id=sub["id"],
            )

            form_values = {
                "like_count": int(row_value(sub, "like_count", 0)),
                "comment_count": int(row_value(sub, "comment_count", 0)),
                "share_count": int(row_value(sub, "share_count", 0)),
                "view_count": int(row_value(sub, "view_count", 0)),
                "follower_before": int(row_value(sub, "follower_before", 0)),
                "follower_after": int(row_value(sub, "follower_after", 0)),
                "friends_before": int(row_value(sub, "friends_before", 0)),
                "friends_after": int(row_value(sub, "friends_after", 0)),
            }

            points, credit = (0, 0)
            approved_at = None
            if status == "auto_approved":
                points, credit = calculate_submission_score(mission, form_values, settings)
                approved_at = now_text()
                tx_exists = conn.execute(
                    "SELECT id FROM point_transactions WHERE submission_id=? LIMIT 1",
                    (sub["id"],),
                ).fetchone()
                if not tx_exists:
                    add_points(conn, sub["user_id"], sub["id"], points, f"Tự động duyệt lại nhiệm vụ: {mission['title']}")
                    add_credit(conn, sub["user_id"], credit, "earn", f"Credit tự động từ nhiệm vụ: {mission['title']}")
                auto_approved += 1
            elif status == "rejected":
                rejected += 1
            elif status == "need_review":
                need_review += 1
            else:
                pending += 1

            conn.execute(
                """
                UPDATE submissions
                SET status=?, auto_check_note=?, points_awarded=?, credit_awarded=?, approved_at=?
                WHERE id=?
                """,
                (status, note, points, credit, approved_at, sub["id"]),
            )

    flash(
        f"Đã quét {scanned} bài: tự duyệt {auto_approved}, tự từ chối {rejected}, cần kiểm tra {need_review}, chờ duyệt {pending}.",
        "success",
    )
    return redirect(url_for("admin_automation"))


@app.route("/admin/scoring", methods=["GET", "POST"])
@login_required
@admin_required
def admin_scoring():
    if request.method == "POST":
        with db() as conn:
            for setting_key in DEFAULT_SETTINGS:
                value = request.form.get(setting_key, DEFAULT_SETTINGS[setting_key]["value"]).strip()
                if value == "":
                    value = DEFAULT_SETTINGS[setting_key]["value"]
                conn.execute(
                    """
                    UPDATE app_settings
                    SET setting_value=?, updated_at=?
                    WHERE setting_key=?
                    """,
                    (value, now_text(), setting_key),
                )
        flash("Đã cập nhật cấu hình điểm/credit.", "success")
        return redirect(url_for("admin_scoring"))

    with db() as conn:
        settings = get_app_settings(conn)
    setting_rows = [
        {"key": key, "label": meta["label"], "value": settings.get(key, meta["value"]), "default": meta["value"]}
        for key, meta in DEFAULT_SETTINGS.items()
    ]
    return render_template("admin/scoring.html", setting_rows=setting_rows)


init_db()

if __name__ == "__main__":
    app.run(debug=True)
