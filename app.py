import os
import re
import uuid
from functools import wraps
from PyPDF2 import PdfReader
from werkzeug.utils import secure_filename
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    url_for,
    flash
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from database.db import get_connection
from config import SECRET_KEY


app = Flask(__name__)

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )

def detect_skills_from_text(text, cursor):

    detected_skills = []

    text_lower = text.lower()

    cursor.execute("""
        SELECT id, skill_name
        FROM skills
        ORDER BY skill_name
    """)

    skills = cursor.fetchall()

    for skill_id, skill_name in skills:

        skill_lower = skill_name.lower()

        pattern = r"\b" + re.escape(skill_lower) + r"\b"

        if re.search(pattern, text_lower):

            detected_skills.append(
                (skill_id, skill_name)
            )

    return detected_skills
app.secret_key = os.getenv("SECRET_KEY","skillbridge-dev-secret")

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf"}
MAX_FILE_SIZE = 5 * 1024 * 1024

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def admin_required(view_function):

    @wraps(view_function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        if session.get("user_role") != "admin":
            flash("Admin access required.")
            return redirect(url_for("dashboard"))

        return view_function(*args, **kwargs)

    return wrapper

# ================= HOME =================

@app.route("/")
def home():

    return render_template("index.html")


# ================= REGISTER =================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if len(password) < 6:

            return render_template(
                "register.html",
                error="Password must contain at least 6 characters."
            )

        password_hash = generate_password_hash(password)

        connection = get_connection()

        if connection is None:

            return render_template(
                "register.html",
                error="Database connection failed."
            )

        try:

            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO users
                (name, email, password_hash)
                VALUES (%s, %s, %s)
                """,
                (
                    name,
                    email,
                    password_hash
                )
            )

            connection.commit()

            cursor.close()
            connection.close()

            return redirect(url_for("login"))

        except Exception as e:

            connection.rollback()
            connection.close()

            print("Registration Error:", e)

            if "duplicate key" in str(e).lower():

                error = "This email is already registered."

            else:

                error = "Registration failed."

            return render_template(
                "register.html",
                error=error
            )

    return render_template("register.html")


# ================= LOGIN =================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"].strip().lower()
        password = request.form["password"]

        connection = get_connection()

        if connection is None:

            return render_template(
                "login.html",
                error="Database connection failed."
            )

        try:

            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT id, name, email, password_hash,role
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cursor.fetchone()
            session["user_id"] = user[0]
            session["user_name"] = user[1]
            session["user_email"] = user[2]
            session["user_role"] = user[4]

            cursor.close()
            connection.close()

        except Exception as e:

            print("Login Error:", e)

            connection.close()

            return render_template(
                "login.html",
                error="Something went wrong."
            )

        # User doesn't exist

        if user is None:

            return render_template(
                "login.html",
                error="Invalid email or password."
            )

        user_id = user[0]
        user_name = user[1]
        password_hash = user[3]
        admin = user[4]

        # Verify password

        if not check_password_hash(
            password_hash,
            password
        ):

            return render_template(
                "login.html",
                error="Invalid email or password."
            )

        # Create session

        session["user_id"] = user_id
        session["user_name"] = user_name
        session["user_email"] = email
        session["user_role"] = admin

        return redirect(
            url_for("dashboard")
        )

    return render_template("login.html")


# ================= DASHBOARD =================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    return render_template(
        "dashboard.html",
        name=session["user_name"],
        email=session["user_email"]
    )

@app.route("/skills", methods=["GET", "POST"])
def skills():

    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    connection = get_connection()

    if connection is None:
        return "Database connection failed."

    cursor = connection.cursor()

    error = None
    message = None

    try:
        # ================= ADD / UPDATE SKILL =================
        if request.method == "POST":

            skill_id = request.form.get("skill_id")
            skill_level = request.form.get("skill_level")

            if not skill_id or not skill_level:
                error = "Please select a skill and skill level."

            else:
                skill_level = int(skill_level)

                if skill_level < 0 or skill_level > 100:
                    error = "Skill level must be between 0 and 100."

                else:
                    # Check whether the user already has this skill
                    cursor.execute(
                        """
                        SELECT id
                        FROM student_skills
                        WHERE user_id = %s
                        AND skill_id = %s
                        """,
                        (user_id, skill_id)
                    )

                    existing = cursor.fetchone()

                    if existing:
                        cursor.execute(
                            """
                            UPDATE student_skills
                            SET skill_level = %s
                            WHERE user_id = %s
                            AND skill_id = %s
                            """,
                            (skill_level, user_id, skill_id)
                        )
                        message = "Skill updated successfully."

                    else:
                        cursor.execute(
                            """
                            INSERT INTO student_skills
                            (user_id, skill_id, skill_level)
                            VALUES (%s, %s, %s)
                            """,
                            (user_id, skill_id, skill_level)
                        )
                        message = "Skill added successfully."

                    connection.commit()

        # ================= GET ALL AVAILABLE SKILLS =================
        cursor.execute(
            """
            SELECT id, skill_name
            FROM skills
            ORDER BY skill_name
            """
        )

        skills_list = cursor.fetchall()

        # ================= GET USER'S SKILLS =================
        cursor.execute(
            """
            SELECT
                s.skill_name,
                ss.skill_level
            FROM student_skills ss
            JOIN skills s
                ON s.id = ss.skill_id
            WHERE ss.user_id = %s
            ORDER BY ss.skill_level DESC
            """,
            (user_id,)
        )

        student_skills = cursor.fetchall()

        return render_template(
            "skills.html",
            skills=skills_list,
            student_skills=student_skills,
            message=message,
            error=error
        )

    except Exception as e:
        connection.rollback()
        print("SKILLS ERROR:", e)

        return render_template(
            "skills.html",
            skills=[],
            student_skills=[],
            message=None,
            error=str(e)
        )

    finally:
        cursor.close()
        connection.close()


@app.route("/profile", methods=["GET", "POST"])
def profile():

    # Check login
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    connection = get_connection()

    if connection is None:
        return "Database connection failed."

    cursor = connection.cursor()

    # ================= SAVE PROFILE =================

    if request.method == "POST":

        education = request.form["education"].strip()
        branch = request.form["branch"].strip()
        semester = int(request.form["semester"])
        career_goal = request.form["career_goal"].strip()
        experience = request.form["experience"].strip()

        try:

            cursor.execute(
                """
                SELECT id
                FROM student_profiles
                WHERE user_id = %s
                """,
                (user_id,)
            )

            existing_profile = cursor.fetchone()

            if existing_profile:

                cursor.execute(
                    """
                    UPDATE student_profiles
                    SET education = %s,
                        branch = %s,
                        semester = %s,
                        career_goal = %s,
                        experience = %s
                    WHERE user_id = %s
                    """,
                    (
                        education,
                        branch,
                        semester,
                        career_goal,
                        experience,
                        user_id
                    )
                )

            else:

                cursor.execute(
                    """
                    INSERT INTO student_profiles
                    (
                        user_id,
                        education,
                        branch,
                        semester,
                        career_goal,
                        experience
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        education,
                        branch,
                        semester,
                        career_goal,
                        experience
                    )
                )

            connection.commit()

            cursor.close()
            connection.close()

            return redirect(
                url_for("profile")
            )

        except Exception as e:

            connection.rollback()

            cursor.close()
            connection.close()

            print("Profile Error:", e)

            return render_template(
                "profile.html",
                error="Could not save profile."
            )


    # ================= GET PROFILE =================

    cursor.execute(
        """
        SELECT
            education,
            branch,
            semester,
            career_goal,
            experience
        FROM student_profiles
        WHERE user_id = %s
        """,
        (user_id,)
    )

    row = cursor.fetchone()

    cursor.close()
    connection.close()


    profile_data = None

    if row:

        profile_data = {
            "education": row[0],
            "branch": row[1],
            "semester": row[2],
            "career_goal": row[3],
            "experience": row[4]
        }


    return render_template(
        "profile.html",
        profile=profile_data
    )
# ================= LOGOUT =================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


@app.route("/resume", methods=["GET", "POST"])
def resume():

    # User must be logged in
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        # Check whether file exists
        if "resume" not in request.files:
            flash("Please select a PDF resume.")
            return redirect(url_for("resume"))

        file = request.files["resume"]

        # Check filename
        if file.filename == "":
            flash("Please select a PDF resume.")
            return redirect(url_for("resume"))

        # Check extension
        if not allowed_file(file.filename):
            flash("Only PDF files are allowed.")
            return redirect(url_for("resume"))

        try:
            # Secure filename
            filename = secure_filename(file.filename)

            # Add user ID to avoid filename conflicts
            user_id = session["user_id"]

            saved_filename = f"{user_id}_{filename}"

            filepath = os.path.join(
                app.config["UPLOAD_FOLDER"],
                saved_filename
            )

            # Save PDF
            file.save(filepath)

            # Extract text from PDF
            reader = PdfReader(filepath)

            extracted_text = ""

            for page in reader.pages:
                page_text = page.extract_text()

                if page_text:
                    extracted_text += page_text + "\n"

            # Check whether text was extracted
            if not extracted_text.strip():
                flash(
                    "Could not extract text from this PDF. "
                    "Please upload a text-based PDF."
                )
                return redirect(url_for("resume"))

            # Convert text to lowercase for matching
            text_lower = extracted_text.lower()

            connection = get_connection()

            if connection is None:
                flash("Database connection failed.")
                return redirect(url_for("resume"))

            cursor = connection.cursor()

            # Save resume information
            cursor.execute(
                """
                INSERT INTO resumes
                (user_id, filename, extracted_text)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    saved_filename,
                    extracted_text
                )
            )

            resume_id = cursor.fetchone()[0]

            # Get all skills from database
            cursor.execute(
                """
                SELECT id, skill_name
                FROM skills
                ORDER BY skill_name
                """
            )

            skills = cursor.fetchall()

            detected_skills = []

            # Detect skills
            for skill_id, skill_name in skills:

                skill_lower = skill_name.lower()

                # Word-boundary matching
                pattern = r"\b" + re.escape(skill_lower) + r"\b"

                if re.search(pattern, text_lower):

                    detected_skills.append(skill_name)

                    cursor.execute(
                        """
                        INSERT INTO resume_skills
                        (resume_id, skill_id)
                        VALUES (%s, %s)
                        """,
                        (
                            resume_id,
                            skill_id
                        )
                    )

            connection.commit()

            cursor.close()
            connection.close()

            return render_template(
                "resume.html",
                filename=saved_filename,
                extracted_text=extracted_text,
                detected_skills=detected_skills
            )

        except Exception as e:

            print("Resume analysis error:", e)

            flash(
                "An error occurred while analyzing the resume."
            )

            return redirect(url_for("resume"))

    return render_template("resume.html")
@app.route("/job-analyzer", methods=["GET", "POST"])
def job_analyzer():

    # User must be logged in
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        job_title = request.form.get("job_title", "").strip()
        description = request.form.get("description", "").strip()

        # Validate job title
        if not job_title:
            flash("Please enter the job title.")
            return redirect(url_for("job_analyzer"))

        # Validate description
        if not description:
            flash("Please enter the job description.")
            return redirect(url_for("job_analyzer"))

        connection = None
        cursor = None

        try:

            connection = get_connection()

            if connection is None:
                flash("Database connection failed.")
                return redirect(url_for("job_analyzer"))

            cursor = connection.cursor()

            user_id = session["user_id"]

            # --------------------------------
            # SAVE JOB DESCRIPTION
            # --------------------------------

            cursor.execute(
                """
                INSERT INTO job_descriptions
                (user_id, job_title, description)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    job_title,
                    description
                )
            )

            job_id = cursor.fetchone()[0]

            # --------------------------------
            # DETECT SKILLS
            # --------------------------------

            detected = detect_skills_from_text(
                description,
                cursor
            )

            detected_skills = []

            # --------------------------------
            # SAVE DETECTED SKILLS
            # --------------------------------

            for skill_id, skill_name in detected:

                detected_skills.append(skill_name)

                cursor.execute(
                    """
                    INSERT INTO job_skills
                    (job_id, skill_id)
                    VALUES (%s, %s)
                    ON CONFLICT (job_id, skill_id)
                    DO NOTHING
                    """,
                    (
                        job_id,
                        skill_id
                    )
                )

            connection.commit()

            return render_template(
                "job_analyzer.html",
                job_title=job_title,
                description=description,
                detected_skills=detected_skills
            )

        except Exception as e:

            if connection:
                connection.rollback()

            print("Job analyzer error:", e)

            flash(
                "An error occurred while analyzing "
                "the job description."
            )

            return redirect(url_for("job_analyzer"))

        finally:

            if cursor:
                cursor.close()

            if connection:
                connection.close()

    return render_template("job_analyzer.html")

@app.route("/skill-gap", methods=["GET", "POST"])
def skill_gap():

    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    matched = []
    missing = []
    match_percentage = 0
    analyzed = False
    required_text = ""

    if request.method == "POST":

        required_text = request.form.get(
            "required_skills",
            ""
        ).strip()

        if required_text:

            # Convert commas into new lines
            required_text = required_text.replace(",", "\n")

            # Create clean required skill list
            required_skills = []

            for skill in required_text.splitlines():

                skill = skill.strip()

                if skill:
                    required_skills.append(skill)

            # Remove duplicates
            required_skills = list(
                dict.fromkeys(
                    required_skills
                )
            )

            # Get student's skills from database
            connection = get_connection()

            if connection is None:
                return "Database connection failed."

            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT skills.skill_name
                FROM student_skills
                JOIN skills
                ON skills.id = student_skills.skill_id
                WHERE student_skills.user_id = %s
                """,
                (user_id,)
            )

            rows = cursor.fetchall()

            cursor.close()
            connection.close()

            # Convert database skills to lowercase dictionary
            student_skills = {}

            for row in rows:

                skill_name = row[0].strip()

                student_skills[
                    skill_name.lower()
                ] = skill_name

            # Compare skills
            for required_skill in required_skills:

                normalized_required = (
                    required_skill.lower().strip()
                )

                if normalized_required in student_skills:

                    matched.append(
                        student_skills[
                            normalized_required
                        ]
                    )

                else:

                    missing.append(
                        required_skill
                    )

            # Calculate percentage
            total_required = len(
                required_skills
            )

            if total_required > 0:

                match_percentage = round(
                    (
                        len(matched)
                        / total_required
                    ) * 100
                )

            analyzed = True

    return render_template(
        "skill_gap.html",
        matched=matched,
        missing=missing,
        match_percentage=match_percentage,
        analyzed=analyzed,
        required_text=required_text
    )

@app.route("/learning-roadmap")
def learning_roadmap():

    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    connection = get_connection()

    if connection is None:
        return "Database connection failed"

    cursor = connection.cursor()

    try:

        # ------------------------------------------------
        # 1. GET USER CAREER GOAL
        # ------------------------------------------------

        cursor.execute("""
            SELECT career_goal
            FROM student_profiles
            WHERE user_id = %s
        """, (user_id,))

        profile = cursor.fetchone()

        career_goal = profile[0] if profile else None


        # ------------------------------------------------
        # 2. GET USER SKILLS
        # ------------------------------------------------

        cursor.execute("""
            SELECT s.skill_name, ss.skill_level
            FROM student_skills ss
            JOIN skills s
            ON ss.skill_id = s.id
            WHERE ss.user_id = %s
        """, (user_id,))

        user_skills = cursor.fetchall()


        # Convert to dictionary

        skill_levels = {
            skill.lower(): level
            for skill, level in user_skills
        }


        # ------------------------------------------------
        # 3. CREATE ROADMAP
        # ------------------------------------------------

        roadmap = []


        # Data Science roadmap

        data_science_skills = {

            "statistics": {
                "description":
                    "Learn probability, descriptive statistics, distributions and hypothesis testing.",

                "duration": "2 weeks",

                "topics":
                    "Probability, Statistics, Hypothesis Testing",

                "resource":
                    "https://www.khanacademy.org/math/statistics-probability"
            },


            "python": {
                "description":
                    "Strengthen Python programming for data analysis and machine learning.",

                "duration": "2 weeks",

                "topics":
                    "Functions, OOP, NumPy, File Handling",

                "resource":
                    "https://docs.python.org/3/tutorial/"
            },


            "pandas": {
                "description":
                    "Learn how to clean, transform and analyze structured datasets.",

                "duration": "2 weeks",

                "topics":
                    "DataFrames, Cleaning, Filtering, GroupBy",

                "resource":
                    "https://pandas.pydata.org/docs/getting_started/"
            },


            "numpy": {
                "description":
                    "Learn numerical computing concepts used in data science.",

                "duration": "1 week",

                "topics":
                    "Arrays, Operations, Broadcasting, Statistics",

                "resource":
                    "https://numpy.org/learn/"
            },


            "data visualization": {
                "description":
                    "Learn to communicate insights using effective visualizations.",

                "duration": "2 weeks",

                "topics":
                    "Matplotlib, Charts, Dashboards",

                "resource":
                    "https://matplotlib.org/stable/tutorials/"
            },


            "machine learning": {
                "description":
                    "Learn supervised and unsupervised machine learning algorithms.",

                "duration": "4 weeks",

                "topics":
                    "Regression, Classification, Clustering, Evaluation",

                "resource":
                    "https://scikit-learn.org/stable/user_guide.html"
            },


            "sql": {
                "description":
                    "Strengthen SQL skills for querying and analyzing databases.",

                "duration": "2 weeks",

                "topics":
                    "SELECT, JOIN, GROUP BY, Subqueries, Window Functions",

                "resource":
                    "https://www.postgresql.org/docs/"
            },


            "power bi": {
                "description":
                    "Learn business intelligence and interactive dashboard creation.",

                "duration": "2 weeks",

                "topics":
                    "Power Query, Data Modeling, DAX, Dashboards",

                "resource":
                    "https://learn.microsoft.com/power-bi/"
            },

        }


        # ------------------------------------------------
        # 4. CHECK MISSING / WEAK SKILLS
        # ------------------------------------------------

        for skill, information in data_science_skills.items():

            current_level = skill_levels.get(skill, 0)


            if current_level < 60:

                if current_level < 30:
                    priority = "High"

                elif current_level < 60:
                    priority = "Medium"

                else:
                    priority = "Low"


                roadmap.append({

                    "skill": skill.title(),

                    "priority": priority,

                    "description":
                        information["description"],

                    "duration":
                        information["duration"],

                    "topics":
                        information["topics"],

                    "resource":
                        information["resource"]

                })


        # ------------------------------------------------
        # 5. PRIORITY SORTING
        # ------------------------------------------------

        priority_order = {
            "High": 1,
            "Medium": 2,
            "Low": 3
        }


        roadmap.sort(
            key=lambda item:
            priority_order[item["priority"]]
        )


        return render_template(
            "learning_roadmap.html",
            roadmap=roadmap,
            career_goal=career_goal
        )


    except Exception as e:

        print("Learning roadmap error:", e)

        return "Unable to generate learning roadmap."


    finally:

        cursor.close()

        connection.close()

@app.route("/project-recommendations")
def project_recommendations():

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_connection()

    if connection is None:
        return "Database connection failed."

    try:

        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                project_name,
                description,
                difficulty,
                career_domain,
                required_skills,
                technologies,
                project_url
            FROM projects
            ORDER BY id;
        """)

        rows = cursor.fetchall()

        projects = []

        for row in rows:

            projects.append({
                "id": row[0],
                "project_name": row[1],
                "description": row[2],
                "difficulty": row[3],
                "career_domain": row[4],
                "required_skills": row[5],
                "technologies": row[6],
                "project_url": row[7]
            })

        cursor.close()
        connection.close()

        return render_template(
            "project_recommendations.html",
            projects=projects
        )

    except Exception as e:

        if connection:
            connection.close()

        return f"Error loading projects: {e}"

@app.route("/progress")
def progress():

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_connection()

    if connection is None:
        return "Database connection failed."

    try:

        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                item_type,
                item_name,
                status,
                progress_percentage
            FROM progress
            WHERE user_id = %s
            ORDER BY id DESC;
        """, (session["user_id"],))

        rows = cursor.fetchall()

        progress_items = []

        for row in rows:

            progress_items.append({
                "id": row[0],
                "item_type": row[1],
                "item_name": row[2],
                "status": row[3],
                "progress_percentage": row[4]
            })

        # Calculate overall progress

        if progress_items:

            total = sum(
                item["progress_percentage"]
                for item in progress_items
            )

            overall_progress = round(
                total / len(progress_items)
            )

        else:

            overall_progress = 0

        cursor.close()
        connection.close()

        return render_template(
            "progress.html",
            progress_items=progress_items,
            overall_progress=overall_progress
        )

    except Exception as e:

        if connection:
            connection.close()

        return f"Error loading progress: {e}"


@app.route("/update-progress/<int:progress_id>", methods=["POST"])
def update_progress(progress_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    status = request.form.get("status")

    allowed_statuses = [
        "Not Started",
        "In Progress",
        "Completed"
    ]

    if status not in allowed_statuses:
        return "Invalid progress status."

    if status == "Not Started":
        percentage = 0

    elif status == "In Progress":
        percentage = 50

    else:
        percentage = 100

    connection = get_connection()

    if connection is None:
        return "Database connection failed."

    try:

        cursor = connection.cursor()

        cursor.execute("""
            UPDATE progress
            SET
                status = %s,
                progress_percentage = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            AND user_id = %s;
        """, (
            status,
            percentage,
            progress_id,
            session["user_id"]
        ))

        connection.commit()

        cursor.close()
        connection.close()

        return redirect(url_for("progress"))

    except Exception as e:

        connection.rollback()
        connection.close()

        return f"Error updating progress: {e}"

@app.route("/ai-dashboard")
def ai_dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    connection = get_connection()

    if connection is None:
        return "Database connection failed."

    cursor = connection.cursor()

    try:

        # -----------------------------
        # USER SKILLS
        # -----------------------------

        cursor.execute("""
            SELECT s.skill_name, ss.skill_level
            FROM student_skills ss
            JOIN skills s
            ON ss.skill_id = s.id
            WHERE ss.user_id = %s
            ORDER BY ss.skill_level DESC
        """, (user_id,))

        skill_data = cursor.fetchall()

        skill_names = [row[0] for row in skill_data]

        skill_levels = [row[1] for row in skill_data]


        # -----------------------------
        # TOTAL SKILLS
        # -----------------------------

        total_skills = len(skill_data)


        # -----------------------------
        # SKILL SCORE
        # -----------------------------

        if total_skills > 0:

            skill_score = round(
                sum(skill_levels) / total_skills
            )

        else:

            skill_score = 0


        # -----------------------------
        # SKILL GAPS
        # -----------------------------

        skill_gaps = 0

        try:

            cursor.execute("""
                SELECT COUNT(*)
                FROM skill_gaps
                WHERE user_id = %s
                AND gap_status = 'Missing'
            """, (user_id,))

            result = cursor.fetchone()

            if result:
                skill_gaps = result[0]

        except Exception:

            connection.rollback()

            skill_gaps = 0


        # -----------------------------
        # LEARNING PROGRESS
        # -----------------------------

        learning_progress = 0

        try:

            cursor.execute("""
                SELECT AVG(progress_percentage)
                FROM learning_progress
                WHERE user_id = %s
            """, (user_id,))

            result = cursor.fetchone()

            if result and result[0] is not None:

                learning_progress = round(
                    float(result[0])
                )

        except Exception:

            connection.rollback()

            learning_progress = 0


        return render_template(

            "ai_dashboard.html",

            skill_names=skill_names,

            skill_levels=skill_levels,

            total_skills=total_skills,

            skill_score=skill_score,

            skill_gaps=skill_gaps,

            learning_progress=learning_progress

        )

    finally:

        cursor.close()
        connection.close()

@app.route("/admin-dashboard")
@admin_required
def admin_dashboard():


    connection = get_connection()

    total_users = 0
    total_profiles = 0
    total_skills = 0
    active_students = 0
    recent_users = []

    if connection:
        try:
            cursor = connection.cursor()

            # Total users
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]

            # Total student profiles
            cursor.execute("SELECT COUNT(*) FROM student_profiles")
            total_profiles = cursor.fetchone()[0]

            # Available skills
            cursor.execute("SELECT COUNT(*) FROM skills")
            total_skills = cursor.fetchone()[0]

            # Active students
            cursor.execute("""
                SELECT COUNT(DISTINCT user_id)
                FROM student_skills
            """)
            active_students = cursor.fetchone()[0]

            # Recent users
            cursor.execute("""
                SELECT id, name, email, created_at
                FROM users
                ORDER BY created_at DESC
                LIMIT 10
            """)

            recent_users = cursor.fetchall()

            cursor.close()
            connection.close()

        except Exception as e:
            print("Admin dashboard error:", e)

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_profiles=total_profiles,
        total_skills=total_skills,
        active_students=active_students,
        recent_users=recent_users
    )
if __name__ == "__main__":
    app.run(debug=True)