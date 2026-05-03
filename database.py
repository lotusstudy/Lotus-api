import sqlite3
import os
from datetime import datetime

# Database path - works on both local and Render
if os.environ.get('RENDER'):
    # Render persistent disk
    DB_DIR = '/var/data'
    os.makedirs(DB_DIR, exist_ok=True)
    DB_PATH = os.path.join(DB_DIR, 'lotus_academy.db')
else:
    # Local development
    DB_PATH = os.path.join(os.path.dirname(__file__), 'lotus_academy.db')

def get_db():
    """Get database connection with row factory"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """Initialize database with all tables and indexes"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Create tables
    cursor.executescript('''
        -- Students table
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            class TEXT NOT NULL,
            board TEXT NOT NULL,
            stream TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, class, board)
        );
        
        -- Student attendance table
        CREATE TABLE IF NOT EXISTS student_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PRESENT', 'ABSENT', 'LATE')),
            time TEXT DEFAULT '00:00:00',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            UNIQUE(student_id, date)
        );
        
        -- Teachers table
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, subject)
        );
        
        -- Teacher attendance table
        CREATE TABLE IF NOT EXISTS teacher_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PRESENT', 'ABSENT', 'LATE')),
            time TEXT DEFAULT '00:00:00',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
            UNIQUE(teacher_id, date)
        );
        
        -- Metadata table
        CREATE TABLE IF NOT EXISTS meta (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_updated_date TEXT,
            total_syncs INTEGER DEFAULT 0,
            last_sync_time TIMESTAMP
        );
        
        -- Sync log table
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            files_processed INTEGER,
            records_added INTEGER,
            status TEXT,
            error_message TEXT
        );
        
        -- Create indexes for better performance
        CREATE INDEX IF NOT EXISTS idx_student_att_date 
            ON student_attendance(date);
        CREATE INDEX IF NOT EXISTS idx_student_att_student 
            ON student_attendance(student_id);
        CREATE INDEX IF NOT EXISTS idx_student_att_composite 
            ON student_attendance(student_id, date);
        
        CREATE INDEX IF NOT EXISTS idx_teacher_att_date 
            ON teacher_attendance(date);
        CREATE INDEX IF NOT EXISTS idx_teacher_att_teacher 
            ON teacher_attendance(teacher_id);
        CREATE INDEX IF NOT EXISTS idx_teacher_att_composite 
            ON teacher_attendance(teacher_id, date);
        
        CREATE INDEX IF NOT EXISTS idx_students_class 
            ON students(class);
        CREATE INDEX IF NOT EXISTS idx_students_name 
            ON students(name);
        CREATE INDEX IF NOT EXISTS idx_teachers_name 
            ON teachers(name);
    ''')
    
    # Insert default meta row if not exists
    cursor.execute('''
        INSERT OR IGNORE INTO meta (id, last_updated_date, total_syncs) 
        VALUES (1, NULL, 0)
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully")

def get_total_days():
    """Get total unique days from attendance records"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(DISTINCT date) as total FROM (
            SELECT date FROM student_attendance
            UNION
            SELECT date FROM teacher_attendance
        )
    ''')
    result = cursor.fetchone()
    conn.close()
    return result['total'] if result else 0

def get_student_attendance_details(student_id):
    """Get detailed attendance stats for a student"""
    conn = get_db()
    cursor = conn.cursor()
    
    total_days = get_total_days()
    
    cursor.execute('''
        SELECT COUNT(*) as present 
        FROM student_attendance 
        WHERE student_id = ? AND status = 'PRESENT'
    ''', (student_id,))
    present = cursor.fetchone()['present']
    
    cursor.execute('''
        SELECT COUNT(*) as absent 
        FROM student_attendance 
        WHERE student_id = ? AND status = 'ABSENT'
    ''', (student_id,))
    absent = cursor.fetchone()['absent']
    
    conn.close()
    
    percentage = round((present / total_days) * 100, 2) if total_days > 0 else 0
    
    return {
        'total_days': total_days,
        'present': present,
        'absent': absent,
        'percentage': percentage
    }

def get_teacher_attendance_details(teacher_id):
    """Get detailed attendance stats for a teacher"""
    conn = get_db()
    cursor = conn.cursor()
    
    total_days = get_total_days()
    
    cursor.execute('''
        SELECT COUNT(*) as present 
        FROM teacher_attendance 
        WHERE teacher_id = ? AND status = 'PRESENT'
    ''', (teacher_id,))
    present = cursor.fetchone()['present']
    
    cursor.execute('''
        SELECT COUNT(*) as absent 
        FROM teacher_attendance 
        WHERE teacher_id = ? AND status = 'ABSENT'
    ''', (teacher_id,))
    absent = cursor.fetchone()['absent']
    
    conn.close()
    
    percentage = round((present / total_days) * 100, 2) if total_days > 0 else 0
    
    return {
        'total_days': total_days,
        'present': present,
        'absent': absent,
        'percentage': percentage
    }

def get_student_attendance_percentage(student_id):
    """Get attendance percentage for a student"""
    details = get_student_attendance_details(student_id)
    return details['percentage']

def get_teacher_attendance_percentage(teacher_id):
    """Get attendance percentage for a teacher"""
    details = get_teacher_attendance_details(teacher_id)
    return details['percentage']

def get_last_updated_date():
    """Get last sync date from meta table"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT last_updated_date FROM meta WHERE id = 1')
    result = cursor.fetchone()
    conn.close()
    return result['last_updated_date'] if result else None

def update_last_updated_date(date):
    """Update last sync date in meta table"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE meta 
        SET last_updated_date = ?, 
            total_syncs = total_syncs + 1,
            last_sync_time = CURRENT_TIMESTAMP
        WHERE id = 1
    ''', (date,))
    conn.commit()
    conn.close()

def log_sync(files_processed, records_added, status, error=None):
    """Log sync operation"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO sync_log (files_processed, records_added, status, error_message)
        VALUES (?, ?, ?, ?)
    ''', (files_processed, records_added, status, error))
    conn.commit()
    conn.close()

def get_sync_history(limit=10):
    """Get recent sync history"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM sync_log 
        ORDER BY sync_time DESC 
        LIMIT ?
    ''', (limit,))
    results = cursor.fetchall()
    conn.close()
    return [dict(row) for row in results]

# Initialize database when module loads
if __name__ == '__main__':
    init_db()