from flask import Flask, render_template, request, redirect
import sqlite3
import qrcode
import os
from datetime import datetime

app = Flask(__name__)

# Create database automatically
conn = sqlite3.connect('database/attendance.db')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    usn TEXT,
    date TEXT,
    time TEXT
)
''')

conn.commit()
conn.close()


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/admin')
def admin():
    qr_data = "http://172.20.10.5:5000/attendance"

    qr = qrcode.make(qr_data)

    if not os.path.exists("static"):
        os.makedirs("static")

    qr.save("static/attendance_qr.png")

    return render_template('admin.html')


@app.route('/attendance', methods=['GET', 'POST'])
def attendance():

    if request.method == 'POST':

        name = request.form['name']
        usn = request.form['usn']

        now = datetime.now()

        date = now.strftime("%d-%m-%Y")
        time = now.strftime("%H:%M:%S")

        conn = sqlite3.connect('database/attendance.db')
        cursor = conn.cursor()

        cursor.execute('''
        INSERT INTO attendance (name, usn, date, time)
        VALUES (?, ?, ?, ?)
        ''', (name, usn, date, time))

        conn.commit()
        conn.close()

        return redirect('/records')

    return render_template('attendance.html')


@app.route('/records')
def records():

    conn = sqlite3.connect('database/attendance.db')
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM attendance")

    data = cursor.fetchall()

    conn.close()

    return render_template('records.html', records=data)


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)