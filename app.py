from flask import Flask, render_template, request, Response, redirect, url_for, session
import sqlite3
import qrcode
import os
import secrets
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "smart_attendance_secret_key"
ADMIN_PASSWORD = "admin123"

DB_PATH = "database/attendance.db"
QR_PATH = "static/attendance_qr.png"

NGROK_URL = "https://tactful-self-voltage.ngrok-free.dev"

COLLEGE_LAT = 15.818804
COLLEGE_LON = 74.497229
ALLOWED_RANGE = 0.001

os.makedirs("database", exist_ok=True)
os.makedirs("static", exist_ok=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT,
        token TEXT UNIQUE,
        created_at TEXT,
        expires_at TEXT,
        status TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        name TEXT,
        usn TEXT,
        date TEXT,
        time TEXT,
        latitude TEXT,
        longitude TEXT,
        ip_address TEXT,
        device_info TEXT,
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    )
    """)

    conn.commit()
    conn.close()


init_db()


@app.route("/")
def home():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM sessions")
    total_sessions = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance")
    total_attendance = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT subject) FROM sessions")
    total_subjects = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT usn) FROM attendance")
    total_students = cursor.fetchone()[0]

    cursor.execute("""
    SELECT sessions.subject, attendance.name, attendance.usn, attendance.time
    FROM attendance
    JOIN sessions ON attendance.session_id = sessions.id
    ORDER BY attendance.id DESC
    LIMIT 5
    """)
    recent_activity = cursor.fetchall()

    cursor.execute("""
    SELECT sessions.subject, COUNT(attendance.id)
    FROM attendance
    JOIN sessions ON attendance.session_id = sessions.id
    GROUP BY sessions.subject
    ORDER BY COUNT(attendance.id) DESC
    """)
    subject_stats = cursor.fetchall()

    conn.close()

    return render_template(
        "index.html",
        total_sessions=total_sessions,
        total_attendance=total_attendance,
        total_subjects=total_subjects,
        total_students=total_students,
        recent_activity=recent_activity,
        subject_stats=subject_stats
    )
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        password = request.form["password"]

        if password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        else:
            error = "Invalid password. Access denied."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("home"))

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))

    qr_generated = False
    session_info = None

    if request.method == "POST":
        subject = request.form["subject"]

        token = secrets.token_urlsafe(16)
        now = datetime.now()
        expiry = now + timedelta(seconds=60)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO sessions (subject, token, created_at, expires_at, status)
        VALUES (?, ?, ?, ?, ?)
        """, (
            subject,
            token,
            now.strftime("%Y-%m-%d %H:%M:%S"),
            expiry.strftime("%Y-%m-%d %H:%M:%S"),
            "ACTIVE"
        ))

        session_id = cursor.lastrowid
        conn.commit()
        conn.close()

        qr_url = f"{NGROK_URL}/attendance/{token}"
        print("QR URL:", qr_url)

        qr = qrcode.make(qr_url)
        qr.save(QR_PATH)

        qr_generated = True
        session_info = {
            "id": session_id,
            "subject": subject,
            "token": token,
            "qr_url": qr_url,
            "expires_at": expiry.strftime("%Y-%m-%d %H:%M:%S")
        }

    return render_template(
        "admin.html",
        qr_generated=qr_generated,
        session=session_info
    )

@app.route("/attendance/<token>", methods=["GET", "POST"])
def attendance(token):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM sessions WHERE token = ?", (token,))
    session = cursor.fetchone()

    if not session:
        conn.close()
        return render_template("error.html", message="Invalid QR Code. Please scan the latest QR code.")

    session_id = session[0]
    subject = session[1]
    expires_at = datetime.strptime(session[4], "%Y-%m-%d %H:%M:%S")

    if datetime.now() > expires_at:
        cursor.execute("UPDATE sessions SET status = ? WHERE id = ?", ("EXPIRED", session_id))
        conn.commit()
        conn.close()
        return render_template("error.html", message="QR Code expired. Please ask teacher to generate a new QR code.")

    if request.method == "POST":
        name = request.form["name"]
        usn = request.form["usn"]
        latitude = request.form["latitude"]
        longitude = request.form["longitude"]

        if latitude == "" or longitude == "":
            conn.close()
            return render_template("error.html", message="Location permission is required to mark attendance.")

        try:
            student_lat = float(latitude)
            student_lon = float(longitude)
        except ValueError:
            conn.close()
            return render_template("error.html", message="Invalid location data. Attendance rejected.")

        if abs(student_lat - COLLEGE_LAT) > ALLOWED_RANGE or abs(student_lon - COLLEGE_LON) > ALLOWED_RANGE:
            conn.close()
            return render_template(
                "error.html",
                message="You are outside the classroom area. Attendance rejected."
            )

        cursor.execute("""
        SELECT * FROM attendance WHERE session_id = ? AND usn = ?
        """, (session_id, usn))

        existing = cursor.fetchone()

        if existing:
            conn.close()
            return render_template("error.html", message="Attendance already marked for this session.")

        now = datetime.now()
        date = now.strftime("%d-%m-%Y")
        time = now.strftime("%H:%M:%S")

        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
        if "," in ip_address:
            ip_address = ip_address.split(",")[0].strip()

        device_info = request.headers.get("User-Agent")

        cursor.execute("""
        INSERT INTO attendance
        (session_id, name, usn, date, time, latitude, longitude, ip_address, device_info)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            name,
            usn,
            date,
            time,
            latitude,
            longitude,
            ip_address,
            device_info
        ))

        conn.commit()
        conn.close()

        return render_template("success.html", name=name, usn=usn, subject=subject, time=time)

    conn.close()
    return render_template("attendance.html", subject=subject)


@app.route("/records")
def records():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT sessions.subject, attendance.id, attendance.name, attendance.usn,
           attendance.date, attendance.time, attendance.latitude, attendance.longitude,
           attendance.ip_address
    FROM attendance
    JOIN sessions ON attendance.session_id = sessions.id
    ORDER BY sessions.subject, attendance.id DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    grouped_records = {}

    for row in rows:
        subject = row[0]

        if subject not in grouped_records:
            grouped_records[subject] = []

        grouped_records[subject].append(row)

    return render_template("records.html", grouped_records=grouped_records)

@app.route("/export")
def export_csv():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT sessions.subject, attendance.name, attendance.usn,
           attendance.date, attendance.time, attendance.latitude,
           attendance.longitude, attendance.ip_address
    FROM attendance
    JOIN sessions ON attendance.session_id = sessions.id
    ORDER BY sessions.subject, attendance.id DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    csv_data = "Subject,Name,USN,Date,Time,Latitude,Longitude,IP Address\n"

    for row in rows:
        csv_data += ",".join(str(item) for item in row) + "\n"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=attendance_records.csv"}
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)