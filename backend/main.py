from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel
import uuid
import qrcode
import io
import base64
import sqlite3
from datetime import datetime, timezone
import json
import hashlib
import hmac
import os
import secrets
import time

from services import (
    save_upload,
    demo_ocr,
    demo_face_verify,
    demo_liveness,
    sanitize_name
)


# =========================================================
# PATHS
# =========================================================

BASE = Path(__file__).parent
FRONTEND = BASE.parent / "frontend"
DATA_DIR = BASE.parent / "data"

DATA_DIR.mkdir(exist_ok=True)

DATABASE = DATA_DIR / "digiguest.db"
# Uploads and the local session key stay under data/, which is not mounted as static content.
SESSION_SECRET_PATH = DATA_DIR / ".host_session_secret"
SESSION_COOKIE = "digiguest_host"
SESSION_MAX_AGE = 8 * 60 * 60
HOST_EMAIL = os.getenv("DIGIGUEST_HOST_EMAIL", "host@digiguest.com").strip().lower()
HOST_PASSWORD = os.getenv("DIGIGUEST_HOST_PASSWORD", "123456")

if os.getenv("DIGIGUEST_SESSION_SECRET"):
    SESSION_SECRET = os.environ["DIGIGUEST_SESSION_SECRET"].encode("utf-8")
elif SESSION_SECRET_PATH.exists():
    SESSION_SECRET = SESSION_SECRET_PATH.read_bytes()
else:
    SESSION_SECRET = secrets.token_bytes(32)
    SESSION_SECRET_PATH.write_bytes(SESSION_SECRET)


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="DigiGuest API",
    version="0.2.0"
)

app.mount(
    "/static",
    StaticFiles(directory=FRONTEND),
    name="static"
)


def require_host_session(request: Request):
    """Validate the signed, expiring HttpOnly cookie issued by the host login."""
    cookie = request.cookies.get(SESSION_COOKIE, "")
    try:
        expires_text, signature = cookie.split(".", 1)
        expires = int(expires_text)
    except (ValueError, TypeError):
        raise HTTPException(401, "Host login required")
    expected = hmac.new(SESSION_SECRET, expires_text.encode("ascii"), hashlib.sha256).hexdigest()
    if expires <= int(time.time()) or not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Host session expired. Please log in again.")
    return True


class HostLoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/host/login")
def host_login(req: HostLoginRequest, response: Response, request: Request):
    email_ok = hmac.compare_digest(req.email.strip().lower().encode("utf-8"), HOST_EMAIL.encode("utf-8"))
    password_ok = hmac.compare_digest(req.password.encode("utf-8"), HOST_PASSWORD.encode("utf-8"))
    if not (email_ok and password_ok):
        raise HTTPException(401, "Invalid host email or password.")
    expires = str(int(time.time()) + SESSION_MAX_AGE)
    signature = hmac.new(SESSION_SECRET, expires.encode("ascii"), hashlib.sha256).hexdigest()
    response.set_cookie(
        SESSION_COOKIE,
        f"{expires}.{signature}",
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return {"success": True, "message": "Host signed in."}


@app.post("/api/host/logout")
def host_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return {"success": True}


# =========================================================
# DATABASE
# =========================================================

def get_db():

    connection = sqlite3.connect(
        DATABASE
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_database():

    connection = get_db()

    # Guests table
    connection.execute("""
        CREATE TABLE IF NOT EXISTS guests (

            token TEXT PRIMARY KEY,

            booking_id TEXT NOT NULL,

            name TEXT NOT NULL,

            phone TEXT,

            email TEXT,

            guest_count INTEGER NOT NULL,

            purpose TEXT,

            identity_verified INTEGER DEFAULT 0,

            face_verified INTEGER DEFAULT 0,

            liveness_verified INTEGER DEFAULT 0,

            booking_verified INTEGER DEFAULT 0,

            status TEXT DEFAULT 'VERIFIED',

            checked_in INTEGER DEFAULT 0,

            created_at TEXT,

            checked_in_at TEXT

        )
    """)

    # Bookings table
    connection.execute("""
        CREATE TABLE IF NOT EXISTS bookings (

            booking_id TEXT PRIMARY KEY,

            guest_name TEXT NOT NULL,

            property_name TEXT NOT NULL,

            check_in TEXT NOT NULL,

            check_out TEXT NOT NULL,

            status TEXT DEFAULT 'CONFIRMED'

        )
    """)

    # Per-person verification summary for the booking's single QR pass.
    connection.execute("""
        CREATE TABLE IF NOT EXISTS guest_members (
            token TEXT NOT NULL,
            guest_number INTEGER NOT NULL,
            age_category TEXT NOT NULL,
            identity_verified INTEGER NOT NULL DEFAULT 0,
            face_verified INTEGER NOT NULL DEFAULT 0,
            liveness_verified INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (token, guest_number),
            FOREIGN KEY (token) REFERENCES guests(token)
        )
    """)

    # Demo bookings
    demo_bookings = [
        (
            "DG48291",
            "Demo Guest",
            "DigiGuest Beach Villa",
            "2026-09-26",
            "2026-09-28",
            "CONFIRMED"
        ),
        (
            "DG73924",
            "Rahul Sharma",
            "DigiGuest Beach Villa",
            "2026-09-27",
            "2026-09-30",
            "CONFIRMED"
        ),
        (
            "DG15683",
            "Aisha Khan",
            "DigiGuest City Apartment",
            "2026-09-28",
            "2026-10-01",
            "CONFIRMED"
        ),
        (
            "DG90417",
            "Arjun Mehta",
            "DigiGuest City Apartment",
            "2026-09-29",
            "2026-10-02",
            "CONFIRMED"
        )
    ]

    connection.executemany("""
        INSERT OR IGNORE INTO bookings (
            booking_id,
            guest_name,
            property_name,
            check_in,
            check_out,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, demo_bookings)

    connection.commit()
    connection.close()

init_database()


# =========================================================
# HELPER
# =========================================================

def guest_to_dict(row):

    if row is None:
        return None

    connection = get_db()
    members = connection.execute(
        """SELECT age_category, identity_verified
           FROM guest_members WHERE token = ?""",
        (row["token"],),
    ).fetchall()
    connection.close()

    if members:
        verified_guest_count = sum(
            1 for member in members
            if member["age_category"] == "5plus" and member["identity_verified"]
        )
        under5_exempt_count = sum(
            1 for member in members if member["age_category"] == "under5"
        )
    else:
        # Compatibility for passes created before per-guest summaries existed.
        verified_guest_count = row["guest_count"] if row["identity_verified"] else 0
        under5_exempt_count = 0

    return {
        "token": row["token"],
        "booking_id": row["booking_id"],
        "name": row["name"],
        "guest_count": row["guest_count"],
        "verified_guest_count": verified_guest_count,
        "under5_exempt_count": under5_exempt_count,
        "verification_status": "Verified" if row["status"] == "VERIFIED" else "Verification failed",
        "identity_verified":
            bool(row["identity_verified"]),

        "face_verified":
            bool(row["face_verified"]),

        "liveness_verified":
            bool(row["liveness_verified"]),

        "booking_verified":
            bool(row["booking_verified"]),

        "status": row["status"],

        "checked_in":
            bool(row["checked_in"]),

        "created_at":
            row["created_at"],

        "checked_in_at":
            row["checked_in_at"]
    }


def save_temp_upload(upload_file: UploadFile) -> str:
    try:
        return save_upload(upload_file)
    except ValueError as error:
        status_code = 413 if "5 MB" in str(error) else 400
        raise HTTPException(status_code, str(error))


def discard_temp_upload(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        # A failed cleanup must not hide the verification response.
        pass


# =========================================================
# PAGES
# =========================================================

@app.get("/")
def home():

    return FileResponse(
        FRONTEND / "index.html"
    )


@app.get("/host.html")
def host_page():

    return FileResponse(
        FRONTEND / "host.html"
    )

# =========================================================
# BOOKING VALIDATION
# =========================================================

@app.get("/api/booking/{booking_id}")
def get_booking(booking_id: str):

    booking_id = booking_id.strip().upper()

    if not booking_id:
        raise HTTPException(
            400,
            "Booking ID is required"
        )

    connection = get_db()

    row = connection.execute(
        """
        SELECT *
        FROM bookings
        WHERE booking_id = ?
        """,
        (booking_id,)
    ).fetchone()

    connection.close()

    if row is None:
        raise HTTPException(
            404,
            "Booking not found. Please check your Booking ID."
        )

    if row["status"] != "CONFIRMED":
        raise HTTPException(
            400,
            "This booking is not available for verification."
        )

    return {
        "booking_id": row["booking_id"],
        "guest_name": row["guest_name"],
        "property_name": row["property_name"],
        "check_in": row["check_in"],
        "check_out": row["check_out"],
        "status": row["status"]
    }


# =========================================================
# DEMO VERIFICATION APIs
# =========================================================

@app.post("/api/ocr")
async def ocr(
    id_file: UploadFile = File(...)
):
    path = save_temp_upload(id_file)
    try:
        result = demo_ocr(path)
        return {
            "success": bool(result.get("success")),
            "message": "Demo ID check completed." if result.get("success") else "Could not read this demo ID image.",
        }
    finally:
        discard_temp_upload(path)


@app.post("/api/face-verify")
async def face_verify(
    id_file: UploadFile = File(...),
    selfie: UploadFile = File(...)
):

    paths = []
    try:
        id_path = save_temp_upload(id_file)
        paths.append(id_path)
        selfie_path = save_temp_upload(selfie)
        paths.append(selfie_path)
        result = demo_face_verify(id_path, selfie_path)
        return {
            "success": bool(result.get("success")),
            "match": bool(result.get("match")),
            "message": "Demo face check completed. This is not biometric verification.",
        }
    finally:
        for path in paths:
            discard_temp_upload(path)


@app.post("/api/liveness")
async def liveness(
    selfie: UploadFile = File(...)
):

    path = save_temp_upload(selfie)
    try:
        result = demo_liveness(path)
        return {
            "success": bool(result.get("success")),
            "live": bool(result.get("live")),
            "message": "Demo liveness check completed. This is not production security.",
        }
    finally:
        discard_temp_upload(path)


# =========================================================
# GUEST VERIFICATION
# =========================================================

@app.post("/api/verify")
async def verify_guest(
    booking_id: str = Form(...),
    name: str = Form(...),
    guest_count: int = Form(...),
    age_categories: str = Form(...),
    id_files: list[UploadFile] = File(default=[]),
    selfies: list[UploadFile] = File(default=[]),
):
    """Create one group pass after demo checks for every guest aged 5+."""
    booking_id = booking_id.strip().upper()
    clean_name = sanitize_name(name)
    if not booking_id:
        raise HTTPException(400, "Booking ID is required")
    if not clean_name:
        raise HTTPException(400, "Guest name is required")
    if guest_count < 1 or guest_count > 20:
        raise HTTPException(400, "Guest count must be between 1 and 20")
    try:
        categories = json.loads(age_categories)
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(400, "Guest age categories must be valid JSON")
    if (not isinstance(categories, list) or len(categories) != guest_count or
            any(category not in {"under5", "5plus"} for category in categories)):
        raise HTTPException(400, "Provide an age category for every guest")

    adult_indexes = [i for i, category in enumerate(categories) if category == "5plus"]
    if len(id_files) != len(adult_indexes) or len(selfies) != len(adult_indexes):
        raise HTTPException(400, "Every guest aged 5 or older must provide an ID and selfie")
    for upload in id_files + selfies:
        if not upload.filename or upload.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(400, "ID and selfie uploads must be JPG, PNG, or WEBP images")

    connection = get_db()
    temp_paths = []
    verified_members = []
    try:
        booking = connection.execute(
            "SELECT status FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
        if booking is None:
            raise HTTPException(404, "Booking not found. Please check your Booking ID.")
        if booking["status"] != "CONFIRMED":
            raise HTTPException(400, "This booking is not available for verification.")

        # Run the existing demo checks without retaining the uploaded images.
        for index, id_upload, selfie_upload in zip(adult_indexes, id_files, selfies):
            id_path = save_temp_upload(id_upload)
            temp_paths.append(id_path)
            selfie_path = save_temp_upload(selfie_upload)
            temp_paths.append(selfie_path)
            ocr_result = demo_ocr(id_path)
            face_result = demo_face_verify(id_path, selfie_path)
            live_result = demo_liveness(selfie_path)
            if not ocr_result.get("success") or not face_result.get("match") or not live_result.get("live"):
                raise HTTPException(400, f"Demo verification failed for Guest {index + 1}")
            verified_members.append(index)

        token = "DG-" + uuid.uuid4().hex[:10].upper()
        created_at = datetime.now(timezone.utc).isoformat()
        # A group with only exempt children has no pending ID or selfie checks.
        all_adults_verified = True
        guest = {
            "token": token,
            "booking_id": booking_id,
            "name": clean_name,
            "guest_count": guest_count,
            "identity_verified": all_adults_verified,
            "face_verified": all_adults_verified,
            "liveness_verified": all_adults_verified,
            "booking_verified": True,
            "status": "VERIFIED",
            "checked_in": False,
            "created_at": created_at,
            "checked_in_at": None,
        }
        connection.execute(
            """INSERT INTO guests (
                token, booking_id, name, phone, email, guest_count, purpose,
                identity_verified, face_verified, liveness_verified,
                booking_verified, status, checked_in, created_at, checked_in_at
            ) VALUES (?, ?, ?, NULL, NULL, ?, NULL, ?, ?, ?, 1, 'VERIFIED', 0, ?, NULL)""",
            (token, booking_id, clean_name, guest_count, int(all_adults_verified),
             int(all_adults_verified), int(all_adults_verified), created_at),
        )
        connection.executemany(
            """INSERT INTO guest_members (
                token, guest_number, age_category, identity_verified,
                face_verified, liveness_verified
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (token, i + 1, category, int(category == "under5" or i in verified_members),
                 int(category == "5plus" and i in verified_members),
                 int(category == "5plus" and i in verified_members))
                for i, category in enumerate(categories)
            ],
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        for path in temp_paths:
            discard_temp_upload(path)
        connection.close()

    return {
        **guest,
        "verified_adult_count": len(verified_members),
        "under5_count": categories.count("under5"),
    }


# =========================================================
# GET GUEST
# =========================================================

@app.get("/api/guest/{token}")
def get_guest(
    token: str,
    _host: bool = Depends(require_host_session),
):

    connection = get_db()

    row = connection.execute(
        """
        SELECT *
        FROM guests
        WHERE token = ?
        """,

        (token,)
    ).fetchone()

    connection.close()


    if row is None:

        raise HTTPException(
            404,
            "Invalid or expired QR token. Guest pass not found."
        )


    return guest_to_dict(row)


# =========================================================
# CHECK-IN
# =========================================================

class CheckInRequest(BaseModel):

    token: str


@app.post("/api/check-in")
def check_in(
    req: CheckInRequest,
    _host: bool = Depends(require_host_session),
):

    connection = get_db()

    row = connection.execute(
        """
        SELECT *
        FROM guests
        WHERE token = ?
        """,

        (req.token,)
    ).fetchone()


    if row is None:

        connection.close()

        raise HTTPException(
            404,
            "Guest pass not found"
        )


    if row["status"] != "VERIFIED":

        connection.close()

        raise HTTPException(
            400,
            "Guest is not verified"
        )


    # Already checked in
    if row["checked_in"]:

        connection.close()

        return guest_to_dict(row)


    checked_in_at = datetime.now(
        timezone.utc
    ).isoformat()


    connection.execute(
        """
        UPDATE guests

        SET
            checked_in = 1,
            checked_in_at = ?

        WHERE token = ?
        """,

        (
            checked_in_at,
            req.token
        )
    )


    connection.commit()


    updated_row = connection.execute(
        """
        SELECT *
        FROM guests
        WHERE token = ?
        """,

        (req.token,)
    ).fetchone()


    connection.close()


    return guest_to_dict(
        updated_row
    )


# =========================================================
# QR CODE
# =========================================================

@app.get("/api/qr/{token}")
def qr(
    token: str
):

    connection = get_db()

    row = connection.execute(
        """
        SELECT token
        FROM guests
        WHERE token = ?
        """,

        (token,)
    ).fetchone()

    connection.close()


    if row is None:

        raise HTTPException(
            404,
            "Guest pass not found"
        )


    img = qrcode.make(
        token
    )


    buffer = io.BytesIO()

    img.save(
        buffer,
        format="PNG"
    )


    encoded = base64.b64encode(
        buffer.getvalue()
    ).decode()


    return {

        "token":
            token,

        "qr_data_url":
            f"data:image/png;base64,{encoded}"
    }
