import psycopg2
from config import DATABASE_URL


def get_connection():
    try:
        connection = psycopg2.connect(DATABASE_URL)
        return connection

    except Exception as e:
        print("Database connection error:", e)
        return None