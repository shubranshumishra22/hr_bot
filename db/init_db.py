"""Creates a mock HR SQLite or PostgreSQL database with employees, leave balances,
leave requests, IT/HR tickets, and pending OTPs. Re-runnable: drops and recreates tables.
"""
import sqlite3
import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import HR_DB_PATH, DATABASE_URL

SCHEMA = """
DROP TABLE IF EXISTS leave_requests;
DROP TABLE IF EXISTS tickets;
DROP TABLE IF EXISTS leave_balances;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS pending_otps;

CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    telegram_id TEXT UNIQUE,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    department TEXT,
    manager_id INTEGER
);

CREATE TABLE leave_balances (
    employee_id INTEGER NOT NULL,
    leave_type TEXT NOT NULL,
    balance REAL NOT NULL,
    PRIMARY KEY (employee_id, leave_type),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);

CREATE TABLE leave_requests (
    id {auto_increment_type},
    employee_id INTEGER NOT NULL,
    leave_type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    days REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_manager_approval',
    requested_at TEXT NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);

CREATE TABLE tickets (
    id {auto_increment_type},
    employee_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);

CREATE TABLE pending_otps (
    email TEXT PRIMARY KEY,
    otp TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Seeding 10 employees
SEED_EMPLOYEES = [
    # id, telegram_id, name, email, department, manager_id
    (1, None, "Asha Rao",      "asha.rao@company.com",      "Engineering", 3),
    (2, None, "Vikram Shah",   "ss2341@srmist.edu.in",   "Sales",       3),
    (3, None, "Priya Iyer",    "shubranshumishra22@gmail.com",    "Engineering", None), # Manager
    (4, None, "Rohan Sharma",  "rohan.sharma@company.com",  "Marketing",   3),
    (5, None, "Sneha Patel",   "sneha.patel@company.com",   "HR",          None), # HR Manager
    (6, None, "Amit Verma",    "amit.verma@company.com",    "Engineering", 3),
    (7, None, "Neha Gupta",     "neha.gupta@company.com",    "Finance",     None), # Finance Manager
    (8, None, "Rahul Nair",    "rahul.nair@company.com",    "Sales",       2),
    (9, None, "Divya Joshi",   "divya.joshi@company.com",   "Marketing",   4),
    (10, None, "Kabir Singh",  "kabir.singh@company.com",   "Engineering", 3),
]

SEED_BALANCES = [
    # employee_id, leave_type, balance
    (1, "earned_leave", 12.0), (1, "sick_leave", 6.0), (1, "casual_leave", 4.0),
    (2, "earned_leave", 8.5),  (2, "sick_leave", 6.0), (2, "casual_leave", 2.0),
    (3, "earned_leave", 15.0), (3, "sick_leave", 6.0), (3, "casual_leave", 5.0),
    (4, "earned_leave", 10.0), (4, "sick_leave", 5.0), (4, "casual_leave", 3.0),
    (5, "earned_leave", 14.0), (5, "sick_leave", 7.0), (5, "casual_leave", 4.0),
    (6, "earned_leave", 11.0), (6, "sick_leave", 6.0), (6, "casual_leave", 3.5),
    (7, "earned_leave", 13.0), (7, "sick_leave", 6.0), (7, "casual_leave", 4.0),
    (8, "earned_leave", 9.0),  (8, "sick_leave", 4.0), (8, "casual_leave", 2.0),
    (9, "earned_leave", 10.5), (9, "sick_leave", 5.0), (9, "casual_leave", 3.0),
    (10, "earned_leave", 12.0),(10, "sick_leave", 6.0),(10, "casual_leave", 4.0),
]


def init_db():
    is_postgres = False
    if DATABASE_URL:
        import psycopg2
        print("Connecting to PostgreSQL database on Neon...")
        conn = psycopg2.connect(DATABASE_URL)
        is_postgres = True
    else:
        print("Connecting to SQLite database locally...")
        conn = sqlite3.connect(HR_DB_PATH)

    # Format auto-increment keyword based on database system
    auto_increment_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    formatted_schema = SCHEMA.format(auto_increment_type=auto_increment_type)

    cursor = conn.cursor()
    
    # Execute table drops and creations
    if is_postgres:
        cursor.execute(formatted_schema)
    else:
        cursor.executescript(formatted_schema)

    # Prepare query placeholders
    placeholder = "%s" if is_postgres else "?"
    
    insert_employee_sql = f"INSERT INTO employees (id, telegram_id, name, email, department, manager_id) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})"
    insert_balance_sql = f"INSERT INTO leave_balances (employee_id, leave_type, balance) VALUES ({placeholder}, {placeholder}, {placeholder})"

    # Insert seeded records
    cursor.executemany(insert_employee_sql, SEED_EMPLOYEES)
    cursor.executemany(insert_balance_sql, SEED_BALANCES)

    conn.commit()
    conn.close()
    
    print("Database schema successfully generated & seeded with 10 employees.")


if __name__ == "__main__":
    init_db()
