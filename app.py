from flask import Flask, render_template, request, redirect
from werkzeug.security import generate_password_hash
from database.db import get_connection

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


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

        if not connection:
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
                (name, email, password_hash)
            )

            connection.commit()

            cursor.close()
            connection.close()

            return redirect("/login")

        except Exception as e:

            connection.rollback()
            connection.close()

            if "duplicate key" in str(e).lower():
                error = "This email is already registered."

            else:
                error = "Registration failed."

            return render_template(
                "register.html",
                error=error
            )

    return render_template("register.html")


@app.route("/login")
def login():

    return """
    <h1>Login Page</h1>
    <p>Login module will be implemented next.</p>
    """


if __name__ == "__main__":
    app.run(debug=True)