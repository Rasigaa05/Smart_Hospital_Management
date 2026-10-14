import os
import sqlite3
from functools import wraps
from pathlib import Path
from datetime import date, datetime
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# For local development only. Set SECRET_KEY in your environment before deployment.
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "dev-only-change-this-secret-before-deployment",
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Keep hospital.db beside app.py, even if Flask is launched from another folder.
BASE_DIR = Path(__file__).resolve().parent
DATABASE = str(BASE_DIR / "hospital.db")


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# ==========================================
# INITIALIZE DATABASE
# ==========================================

def initialize_database():
    conn = get_db_connection()

    try:
        # Patients table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                gender TEXT NOT NULL,
                phone TEXT NOT NULL,
                condition_name TEXT NOT NULL
            )
        """)

        # Appointments table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_name TEXT NOT NULL,
                doctor_name TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                appointment_time TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Scheduled'
            )
        """)

        # Doctors table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                specialization TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL
            )
        """)


            # Departments table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_name TEXT NOT NULL UNIQUE,
                department_head TEXT NOT NULL,
                location TEXT NOT NULL
            )
        """)
                # Beds table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS beds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bed_number TEXT NOT NULL UNIQUE,
                bed_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Available',
                patient_id INTEGER,
                FOREIGN KEY (patient_id) REFERENCES patients(id)
            )
        """)

                # Billing table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_name TEXT NOT NULL,
                consultation_fee REAL NOT NULL DEFAULT 0,
                medicine_charges REAL NOT NULL DEFAULT 0,
                test_charges REAL NOT NULL DEFAULT 0,
                total_amount REAL NOT NULL DEFAULT 0,
                payment_status TEXT NOT NULL DEFAULT 'Unpaid',
                bill_date TEXT NOT NULL
            )
        """)

        # Admin account table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)

        # Create the initial demo admin only if it does not already exist.
        admin_exists = conn.execute(
            "SELECT id FROM admins WHERE username = ?",
            ("admin",),
        ).fetchone()

        if admin_exists is None:
            conn.execute(
                "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                ("admin", generate_password_hash("Hospital@123")),
            )

               # Add appointment status to existing databases safely
        appointment_columns = conn.execute(
            "PRAGMA table_info(appointments)"
        ).fetchall()

        column_names = [
            column["name"] for column in appointment_columns
        ]

        if "status" not in column_names:
            conn.execute("""
                ALTER TABLE appointments
                ADD COLUMN status TEXT NOT NULL DEFAULT 'Scheduled'
            """)

        conn.commit()

    finally:
        conn.close()

# ==========================================
# ADMIN AUTHENTICATION
# ==========================================

def login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if "admin_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view_function(*args, **kwargs)

    return wrapped_view
@app.route("/login", methods=["GET", "POST"])
def login():

    # If already logged in, go to dashboard
    if "admin_id" in session:
        return redirect(url_for("dashboard"))

    # Process login form
    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db_connection()

        try:
            admin = conn.execute(
                "SELECT * FROM admins WHERE username = ?",
                (username,)
            ).fetchone()
        finally:
            conn.close()

        # Verify username and password
        if admin and check_password_hash(
            admin["password_hash"], password
        ):
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]

            flash("Login successful!", "success")

            return redirect(url_for("dashboard"))

        else:
            flash("Invalid username or password.", "error")

    # Display login page
    return render_template("login.html")



@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ==========================================
# DASHBOARD
# ==========================================

@app.route("/")
@login_required
def dashboard():
    conn = get_db_connection()
    try:
        total_patients = conn.execute(
            "SELECT COUNT(*) FROM patients"
        ).fetchone()[0]

        total_doctors = conn.execute(
            "SELECT COUNT(*) FROM doctors"
        ).fetchone()[0]

        total_appointments = conn.execute(
            "SELECT COUNT(*) FROM appointments"
        ).fetchone()[0]

        total_beds = conn.execute(
            "SELECT COUNT(*) FROM beds"
        ).fetchone()[0]

        available_beds = conn.execute("""
            SELECT COUNT(*) FROM beds
            WHERE status = 'Available'
        """).fetchone()[0]

        occupied_beds = conn.execute("""
            SELECT COUNT(*) FROM beds
            WHERE status = 'Occupied'
        """).fetchone()[0]

        total_departments = conn.execute(
            "SELECT COUNT(*) FROM departments"
        ).fetchone()[0]

        billing_result = conn.execute("""
            SELECT
                COALESCE(SUM(total_amount), 0),
                COALESCE(SUM(
                    CASE WHEN payment_status = 'Paid'
                    THEN total_amount ELSE 0 END
                ), 0),
                COALESCE(SUM(
                    CASE WHEN payment_status = 'Unpaid'
                    THEN total_amount ELSE 0 END
                ), 0)
            FROM bills
        """).fetchone()

        total_billing_amount = billing_result[0]
        paid_amount = billing_result[1]
        unpaid_amount = billing_result[2]

        upcoming_appointments = conn.execute("""
            SELECT *
            FROM appointments
            WHERE appointment_date >= ?
            AND status = 'Scheduled'
            ORDER BY appointment_date ASC,
                    appointment_time ASC
            LIMIT 5
        """, (date.today().isoformat(),)).fetchall()

    finally:
        conn.close()

    return render_template(
        "index.html",
        total_patients=total_patients,
        total_doctors=total_doctors,
        total_appointments=total_appointments,
        total_beds=total_beds,
        available_beds=available_beds,
        occupied_beds=occupied_beds,
        total_departments=total_departments,
        total_billing_amount=total_billing_amount,
        paid_amount=paid_amount,
        unpaid_amount=unpaid_amount,
        upcoming_appointments=upcoming_appointments
    )


# ==========================================
# PATIENT MANAGEMENT WITH SEARCH
# ==========================================

@app.route("/patients")
@login_required
def patients():
    search = request.args.get("search", "").strip()
    conn = get_db_connection()

    try:
        if search:
            patient_list = conn.execute("""
                SELECT *
                FROM patients
                WHERE name LIKE ? OR phone LIKE ?
                ORDER BY id DESC
            """, (f"%{search}%", f"%{search}%")).fetchall()
        else:
            patient_list = conn.execute("""
                SELECT *
                FROM patients
                ORDER BY id DESC
            """).fetchall()
    finally:
        conn.close()

    return render_template(
        "patients.html",
        patients=patient_list,
        search=search,
    )


@app.route("/add_patient", methods=["POST"])
@login_required
def add_patient():
    name = request.form.get("name", "").strip()
    age = request.form.get("age", "").strip()
    gender = request.form.get("gender", "").strip()
    phone = request.form.get("phone", "").strip()
    condition_name = request.form.get("condition_name", "").strip()

    if not all([name, age, gender, phone, condition_name]):
        flash("Please fill in all fields.", "error")
        return redirect(url_for("patients"))

    try:
        age_value = int(age)
        if not 1 <= age_value <= 120:
            raise ValueError
    except ValueError:
        flash("Please enter a valid age between 1 and 120.", "error")
        return redirect(url_for("patients"))

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO patients (name, age, gender, phone, condition_name)
            VALUES (?, ?, ?, ?, ?)
        """, (name, age_value, gender, phone, condition_name))
        conn.commit()
    finally:
        conn.close()

    flash("Patient registered successfully!", "success")
    return redirect(url_for("patients"))


@app.route("/delete_patient/<int:patient_id>", methods=["POST"])
@login_required
def delete_patient(patient_id):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
        conn.commit()
    finally:
        conn.close()

    flash("Patient record deleted.", "success")
    return redirect(url_for("patients"))

@app.route("/edit_patient/<int:patient_id>", methods=["GET", "POST"])
@login_required
def edit_patient(patient_id):
    conn = get_db_connection()

    try:
        patient = conn.execute(
            "SELECT * FROM patients WHERE id = ?",
            (patient_id,)
        ).fetchone()

        if patient is None:
            flash("Patient record not found.", "error")
            return redirect(url_for("patients"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            age = request.form.get("age", "").strip()
            gender = request.form.get("gender", "").strip()
            phone = request.form.get("phone", "").strip()
            condition_name = request.form.get(
                "condition_name", ""
            ).strip()

            if not all([
                name, age, gender, phone, condition_name
            ]):
                flash("Please fill in all fields.", "error")
                return redirect(
                    url_for("edit_patient", patient_id=patient_id)
                )

            try:
                age_value = int(age)
                if not 1 <= age_value <= 120:
                    raise ValueError
            except ValueError:
                flash(
                    "Please enter a valid age between 1 and 120.",
                    "error"
                )
                return redirect(
                    url_for("edit_patient", patient_id=patient_id)
                )

            conn.execute("""
                UPDATE patients
                SET name = ?,
                    age = ?,
                    gender = ?,
                    phone = ?,
                    condition_name = ?
                WHERE id = ?
            """, (
                name,
                age_value,
                gender,
                phone,
                condition_name,
                patient_id
            ))

            conn.commit()

            flash("Patient details updated successfully!", "success")
            return redirect(url_for("patients"))

    finally:
        conn.close()

    return render_template("edit_patient.html", patient=patient)

# ==========================================
# APPOINTMENT MANAGEMENT
# ==========================================

@app.route("/appointments")
@login_required
def appointments():
    conn = get_db_connection()

    try:
        appointment_list = conn.execute("""
            SELECT *
            FROM appointments
            ORDER BY appointment_date DESC, appointment_time DESC
        """).fetchall()

        patient_list = conn.execute("""
            SELECT id, name
            FROM patients
            ORDER BY name
        """).fetchall()

        doctor_list = conn.execute("""
            SELECT id, name, specialization
            FROM doctors
            ORDER BY name
        """).fetchall()

    finally:
        conn.close()

    return render_template(
        "appointments.html",
        appointments=appointment_list,
        patients=patient_list,
        doctors=doctor_list
    )
@app.route("/delete_appointment/<int:appointment_id>", methods=["POST"])
@login_required
def delete_appointment(appointment_id):
    conn = get_db_connection()

    try:
        conn.execute(
            "DELETE FROM appointments WHERE id = ?",
            (appointment_id,)
        )
        conn.commit()
    finally:
        conn.close()

    flash("Appointment deleted successfully!", "success")
    return redirect(url_for("appointments"))

@app.route("/add_appointment", methods=["POST"])
@login_required
def add_appointment():
    patient_name = request.form.get("patient_name", "").strip()
    doctor_name = request.form.get("doctor_name", "").strip()
    appointment_date = request.form.get("appointment_date", "").strip()
    appointment_time = request.form.get("appointment_time", "").strip()
    reason = request.form.get("reason", "").strip()

    if not all([
        patient_name,
        doctor_name,
        appointment_date,
        appointment_time,
        reason
    ]):
        flash("Please fill in all appointment fields.", "error")
        return redirect(url_for("appointments"))

    try:
        selected_date = date.fromisoformat(appointment_date)
        datetime.strptime(appointment_time, "%H:%M")
    except ValueError:
        flash("Please enter a valid appointment date and time.", "error")
        return redirect(url_for("appointments"))

    if selected_date < date.today():
        flash("Appointment date cannot be in the past.", "error")
        return redirect(url_for("appointments"))

    conn = get_db_connection()

    try:
        patient = conn.execute(
            "SELECT name FROM patients WHERE name = ?",
            (patient_name,)
        ).fetchone()

        doctor = conn.execute(
            "SELECT name FROM doctors WHERE name = ?",
            (doctor_name,)
        ).fetchone()

        if not patient or not doctor:
            flash(
                "Please select a registered patient and doctor.",
                "error"
            )
            return redirect(url_for("appointments"))

        conn.execute("""
            INSERT INTO appointments (
                patient_name,
                doctor_name,
                appointment_date,
                appointment_time,
                reason,
                  status

            )
            VALUES (?, ?, ?, ?, ?,?)
        """, (
            patient_name,
            doctor_name,
            appointment_date,
            appointment_time,
            reason,
            "scheduled"
            
        ))

        conn.commit()

    finally:
        conn.close()

    flash("Appointment scheduled successfully!", "success")
    return redirect(url_for("appointments"))

@app.route("/edit_appointment/<int:appointment_id>", methods=["GET", "POST"])
@login_required
def edit_appointment(appointment_id):
    conn = get_db_connection()

    try:
        appointment = conn.execute(
            "SELECT * FROM appointments WHERE id = ?",
            (appointment_id,)
        ).fetchone()

        if appointment is None:
            flash("Appointment not found.", "error")
            return redirect(url_for("appointments"))

        if request.method == "POST":
            patient_name = request.form.get(
                "patient_name", ""
            ).strip()

            doctor_name = request.form.get(
                "doctor_name", ""
            ).strip()

            appointment_date = request.form.get(
                "appointment_date", ""
            ).strip()

            appointment_time = request.form.get(
                "appointment_time", ""
            ).strip()

            reason = request.form.get(
                "reason", ""
            ).strip()

            if not all([
                patient_name,
                doctor_name,
                appointment_date,
                appointment_time,
                reason
            ]):
                flash("All fields are required.", "error")
                return render_template(
                    "edit_appointment.html",
                    appointment=appointment
                )

            conn.execute(
                """
                UPDATE appointments
                SET patient_name = ?,
                    doctor_name = ?,
                    appointment_date = ?,
                    appointment_time = ?,
                    reason = ?
                WHERE id = ?
                """,
                (
                    patient_name,
                    doctor_name,
                    appointment_date,
                    appointment_time,
                    reason,
                    appointment_id
                )
            )

            conn.commit()

            flash("Appointment updated successfully!", "success")
            return redirect(url_for("appointments"))
        return render_template(
            "edit_appointment.html",
            appointment=appointment
        )

    finally:
        conn.close()


# Update appointment status
@app.route(
    "/update_appointment_status/<int:appointment_id>",
    methods=["POST"]
)
@login_required
def update_appointment_status(appointment_id):
        
    status = request.form.get("status", "").strip()

    allowed_statuses = ["Scheduled", "Completed", "Cancelled"]

    if status not in allowed_statuses:
        flash("Invalid appointment status.", "error")
        return redirect(url_for("appointments"))

    conn = get_db_connection()

    try:
        appointment = conn.execute(
            "SELECT id FROM appointments WHERE id = ?",
            (appointment_id,)
        ).fetchone()

        if appointment is None:
            flash("Appointment not found.", "error")
            return redirect(url_for("appointments"))

        conn.execute(
            "UPDATE appointments SET status = ? WHERE id = ?",
            (status, appointment_id)
        )
        conn.commit()

    finally:
        conn.close()

    flash("Appointment status updated successfully!", "success")
    return redirect(url_for("appointments"))

# ==========================================
# DOCTOR MANAGEMENT WITH SEARCH
# ==========================================

@app.route("/doctors")
@login_required
def doctors():
    search = request.args.get("search", "").strip()
    conn = get_db_connection()

    try:
        if search:
            doctor_list = conn.execute("""
                SELECT *
                FROM doctors
                WHERE name LIKE ? OR specialization LIKE ?
                ORDER BY id DESC
            """, (f"%{search}%", f"%{search}%")).fetchall()
        else:
            doctor_list = conn.execute("""
                SELECT *
                FROM doctors
                ORDER BY id DESC
            """).fetchall()
    finally:
        conn.close()

    return render_template(
        "doctors.html",
        doctors=doctor_list,
        search=search,
    )


@app.route("/add_doctor", methods=["POST"])
@login_required
def add_doctor():
    name = request.form.get("name", "").strip()
    specialization = request.form.get("specialization", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()

    if not all([name, specialization, phone, email]):
        flash("Please fill in all doctor fields.", "error")
        return redirect(url_for("doctors"))

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO doctors (name, specialization, phone, email)
            VALUES (?, ?, ?, ?)
        """, (name, specialization, phone, email))
        conn.commit()
    finally:
        conn.close()

    flash("Doctor added successfully!", "success")
    return redirect(url_for("doctors"))


@app.route("/delete_doctor/<int:doctor_id>", methods=["POST"])
@login_required
def delete_doctor(doctor_id):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
        conn.commit()
    finally:
        conn.close()

    flash("Doctor record deleted.", "success")
    return redirect(url_for("doctors"))

@app.route("/edit_doctor/<int:doctor_id>", methods=["GET", "POST"])
@login_required
def edit_doctor(doctor_id):
    conn = get_db_connection()

    try:
        doctor = conn.execute(
            "SELECT * FROM doctors WHERE id = ?",
            (doctor_id,)
        ).fetchone()

        if doctor is None:
            flash("Doctor not found.", "error")
            return redirect(url_for("doctors"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            specialization = request.form.get("specialization", "").strip()
            phone = request.form.get("phone", "").strip()
            email = request.form.get("email", "").strip()

            if not all([name, specialization, phone, email]):
                flash("All fields are required.", "error")
                return render_template(
                    "edit_doctor.html",
                    doctor=doctor
                )

            conn.execute(
                """
                UPDATE doctors
                SET name = ?, specialization = ?, phone = ?, email = ?
                WHERE id = ?
                """,
                (name, specialization, phone, email, doctor_id)
            )

            conn.commit()

            flash("Doctor details updated successfully!", "success")
            return redirect(url_for("doctors"))

        return render_template("edit_doctor.html", doctor=doctor)

    finally:
        conn.close()


# ==========================================
# START APPLICATION
# ==========================================

initialize_database()
# ==================== BILLING MANAGEMENT ====================

@app.route("/bills")
@login_required
def bills():
    conn = get_db_connection()

    all_bills = conn.execute(
        "SELECT * FROM bills ORDER BY id DESC"
    ).fetchall()

    patients = conn.execute(
        "SELECT * FROM patients ORDER BY name"
    ).fetchall()

    conn.close()

    return render_template(
        "bills.html",
        bills=all_bills,
        patients=patients
    )


@app.route("/add_bill", methods=["POST"])
@login_required
def add_bill():
    patient_name = request.form.get("patient_name", "").strip()

    try:
        consultation_fee = float(
            request.form.get("consultation_fee", 0)
        )
        medicine_charges = float(
            request.form.get("medicine_charges", 0)
        )
        test_charges = float(
            request.form.get("test_charges", 0)
        )

        if any(
            amount < 0
            for amount in [
                consultation_fee,
                medicine_charges,
                test_charges
            ]
        ):
            flash("Charges cannot be negative.", "error")
            return redirect(url_for("bills"))

    except (ValueError, TypeError):
        flash("Please enter valid charges.", "error")
        return redirect(url_for("bills"))

    if not patient_name:
        flash("Please select a patient.", "error")
        return redirect(url_for("bills"))

    total_amount = (
        consultation_fee
        + medicine_charges
        + test_charges
    )

    conn = get_db_connection()

    patient = conn.execute(
        "SELECT id FROM patients WHERE name = ?",
        (patient_name,)
    ).fetchone()

    if patient is None:
        conn.close()
        flash("Please select a registered patient.", "error")
        return redirect(url_for("bills"))

    conn.execute(
        """
        INSERT INTO bills (
            patient_name,
            consultation_fee,
            medicine_charges,
            test_charges,
            total_amount,
            payment_status,
            bill_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_name,
            consultation_fee,
            medicine_charges,
            test_charges,
            total_amount,
            "Unpaid",
            date.today().isoformat()
        )
    )

    conn.commit()
    conn.close()

    flash("Bill added successfully!", "success")
    return redirect(url_for("bills"))


@app.route("/update_bill_status/<int:bill_id>", methods=["POST"])
@login_required
def update_bill_status(bill_id):
    payment_status = request.form.get("payment_status", "")

    if payment_status not in ["Paid", "Unpaid"]:
        flash("Invalid payment status.", "error")
        return redirect(url_for("bills"))

    conn = get_db_connection()

    conn.execute(
        "UPDATE bills SET payment_status = ? WHERE id = ?",
        (payment_status, bill_id)
    )

    conn.commit()
    conn.close()

    flash("Payment status updated successfully!", "success")
    return redirect(url_for("bills"))


@app.route("/delete_bill/<int:bill_id>", methods=["POST"])
@login_required
def delete_bill(bill_id):
    conn = get_db_connection()

    conn.execute(
        "DELETE FROM bills WHERE id = ?",
        (bill_id,)
    )

    conn.commit()
    conn.close()

    flash("Bill deleted successfully!", "success")
    return redirect(url_for("bills"))

# ==================== DEPARTMENT MANAGEMENT ====================

@app.route("/departments")
@login_required
def departments():
    conn = get_db_connection()

    all_departments = conn.execute(
        "SELECT * FROM departments ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return render_template(
        "departments.html",
        departments=all_departments
    )


@app.route("/add_department", methods=["POST"])
@login_required
def add_department():
    department_name = request.form.get(
        "department_name", ""
    ).strip()

    department_head = request.form.get(
        "department_head", ""
    ).strip()

    location = request.form.get(
        "location", ""
    ).strip()

    if not department_name or not department_head or not location:
        flash("Please fill in all department fields.", "error")
        return redirect(url_for("departments"))

    conn = get_db_connection()

    try:
        conn.execute(
            """
            INSERT INTO departments (
                department_name,
                department_head,
                location
            )
            VALUES (?, ?, ?)
            """,
            (department_name, department_head, location)
        )

        conn.commit()
        flash("Department added successfully!", "success")

    except sqlite3.IntegrityError:
        flash("This department name already exists.", "error")

    finally:
        conn.close()

    return redirect(url_for("departments"))


@app.route("/edit_department/<int:department_id>", methods=["GET", "POST"])
@login_required
def edit_department(department_id):
    conn = get_db_connection()

    department = conn.execute(
        "SELECT * FROM departments WHERE id = ?",
        (department_id,)
    ).fetchone()

    if department is None:
        conn.close()
        flash("Department not found.", "error")
        return redirect(url_for("departments"))

    if request.method == "POST":
        department_name = request.form.get(
            "department_name", ""
        ).strip()

        department_head = request.form.get(
            "department_head", ""
        ).strip()

        location = request.form.get(
            "location", ""
        ).strip()

        if not department_name or not department_head or not location:
            conn.close()
            flash("Please fill in all department fields.", "error")
            return redirect(
                url_for("edit_department", department_id=department_id)
            )

        try:
            conn.execute(
                """
                UPDATE departments
                SET department_name = ?,
                    department_head = ?,
                    location = ?
                WHERE id = ?
                """,
                (
                    department_name,
                    department_head,
                    location,
                    department_id
                )
            )

            conn.commit()
            flash("Department updated successfully!", "success")
            conn.close()

            return redirect(url_for("departments"))

        except sqlite3.IntegrityError:
            conn.close()
            flash("This department name already exists.", "error")
            return redirect(
                url_for("edit_department", department_id=department_id)
            )

    conn.close()

    return render_template(
        "edit_department.html",
        department=department
    )


@app.route("/delete_department/<int:department_id>", methods=["POST"])
@login_required
def delete_department(department_id):
    conn = get_db_connection()

    conn.execute(
        "DELETE FROM departments WHERE id = ?",
        (department_id,)
    )

    conn.commit()
    conn.close()

    flash("Department deleted successfully!", "success")
    return redirect(url_for("departments"))

# ==================== BED MANAGEMENT ====================

@app.route("/beds")
@login_required
def beds():
    conn = get_db_connection()

    all_beds = conn.execute("""
        SELECT beds.*, patients.name AS patient_name
        FROM beds
        LEFT JOIN patients ON beds.patient_id = patients.id
        ORDER BY beds.id DESC
    """).fetchall()

    patients = conn.execute("""
        SELECT id, name FROM patients ORDER BY name
    """).fetchall()

    conn.close()

    return render_template(
        "beds.html",
        beds=all_beds,
        patients=patients
    )


@app.route("/add_bed", methods=["POST"])
@login_required
def add_bed():
    bed_number = request.form.get("bed_number", "").strip()
    bed_type = request.form.get("bed_type", "").strip()

    if not bed_number:
        flash("Please enter a bed number.")
        return redirect(url_for("beds"))

    if bed_type not in ["General", "Private", "ICU"]:
        flash("Please select a valid bed type.")
        return redirect(url_for("beds"))

    conn = get_db_connection()

    try:
        conn.execute("""
            INSERT INTO beds (bed_number, bed_type, status, patient_id)
            VALUES (?, ?, 'Available', NULL)
        """, (bed_number, bed_type))

        conn.commit()
        flash("Bed added successfully!")

    except sqlite3.IntegrityError:
        flash("This bed number already exists.")

    finally:
        conn.close()

    return redirect(url_for("beds"))


@app.route("/allocate_bed/<int:bed_id>", methods=["POST"])
@login_required
def allocate_bed(bed_id):
    patient_id = request.form.get("patient_id", "").strip()

    if not patient_id.isdigit():
        flash("Please select a valid patient.")
        return redirect(url_for("beds"))

    conn = get_db_connection()

    bed = conn.execute(
        "SELECT * FROM beds WHERE id = ?",
        (bed_id,)
    ).fetchone()

    patient = conn.execute(
        "SELECT id FROM patients WHERE id = ?",
        (int(patient_id),)
    ).fetchone()

    if bed is None:
        flash("Bed not found.")

    elif bed["status"] != "Available":
        flash("This bed is already occupied.")

    elif patient is None:
        flash("Patient not found.")

    else:
        conn.execute("""
            UPDATE beds
            SET status = 'Occupied', patient_id = ?
            WHERE id = ?
        """, (int(patient_id), bed_id))

        conn.commit()
        flash("Bed allocated successfully!")

    conn.close()
    return redirect(url_for("beds"))


@app.route("/release_bed/<int:bed_id>", methods=["POST"])
@login_required
def release_bed(bed_id):
    conn = get_db_connection()

    bed = conn.execute(
        "SELECT * FROM beds WHERE id = ?",
        (bed_id,)
    ).fetchone()

    if bed is None:
        flash("Bed not found.")

    elif bed["status"] != "Occupied":
        flash("This bed is not currently occupied.")

    else:
        conn.execute("""
            UPDATE beds
            SET status = 'Available', patient_id = NULL
            WHERE id = ?
        """, (bed_id,))

        conn.commit()
        flash("Bed released successfully!")

    conn.close()
    return redirect(url_for("beds"))


@app.route("/delete_bed/<int:bed_id>", methods=["POST"])
@login_required
def delete_bed(bed_id):
    conn = get_db_connection()

    bed = conn.execute(
        "SELECT * FROM beds WHERE id = ?",
        (bed_id,)
    ).fetchone()

    if bed is None:
        flash("Bed not found.")

    elif bed["status"] == "Occupied":
        flash("Release the bed before deleting it.")

    else:
        conn.execute(
            "DELETE FROM beds WHERE id = ?",
            (bed_id,)
        )

        conn.commit()
        flash("Bed deleted successfully!")

    conn.close()
    return redirect(url_for("beds"))
# ==================== MEDI ASSIST ====================

@app.route("/medi_assist")
@login_required
def medi_assist():
    return render_template("Medi_Assist.html")



if __name__ == "__main__":
    app.run(debug=True)
