"""
Data models and CRUD operations for Lotus Academy
"""
from datetime import datetime
from database import get_db, date_exists_in_attendance as check_date_exists

def get_or_create_student(name, student_class, board, stream=None):
    """
    Get existing student or create new one
    Returns student_id
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Try to insert (ignore if exists)
    cursor.execute('''
        INSERT OR IGNORE INTO students (name, class, board, stream) 
        VALUES (?, ?, ?, ?)
    ''', (name, student_class, board, stream))
    
    conn.commit()
    
    # Get the ID (either existing or newly created)
    cursor.execute('''
        SELECT id FROM students 
        WHERE name = ? AND class = ? AND board = ?
    ''', (name, student_class, board))
    
    result = cursor.fetchone()
    conn.close()
    
    return result['id'] if result else None

def get_or_create_teacher(name, subject):
    """
    Get existing teacher or create new one
    Returns teacher_id
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Try to insert (ignore if exists)
    cursor.execute('''
        INSERT OR IGNORE INTO teachers (name, subject) 
        VALUES (?, ?)
    ''', (name, subject))
    
    conn.commit()
    
    # Get the ID
    cursor.execute('''
        SELECT id FROM teachers 
        WHERE name = ? AND subject = ?
    ''', (name, subject))
    
    result = cursor.fetchone()
    conn.close()
    
    return result['id'] if result else None

def insert_student_attendance(student_id, date, status, time='00:00:00'):
    """
    Insert or ignore student attendance record
    Prevents duplicate entries for same student on same date
    """
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR IGNORE INTO student_attendance (student_id, date, status, time) 
        VALUES (?, ?, ?, ?)
    ''', (student_id, date, status, time))
    
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    return rows_affected > 0

def insert_teacher_attendance(teacher_id, date, status, time='00:00:00'):
    """
    Insert or ignore teacher attendance record
    Prevents duplicate entries for same teacher on same date
    """
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR IGNORE INTO teacher_attendance (teacher_id, date, status, time) 
        VALUES (?, ?, ?, ?)
    ''', (teacher_id, date, status, time))
    
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    return rows_affected > 0

def date_exists_in_attendance(date):
    """
    Check if a date already has attendance records
    Returns True if date exists in either student or teacher attendance
    """
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) as count FROM student_attendance WHERE date = ?', (date,))
    student_count = cursor.fetchone()['count']
    
    cursor.execute('SELECT COUNT(*) as count FROM teacher_attendance WHERE date = ?', (date,))
    teacher_count = cursor.fetchone()['count']
    
    conn.close()
    
    return (student_count + teacher_count) > 0

def get_all_students(class_filter=None, search=None):
    """
    Get all students with optional filters
    """
    conn = get_db()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM students WHERE 1=1'
    params = []
    
    if class_filter:
        query += ' AND class = ?'
        params.append(class_filter)
    
    if search:
        query += ' AND name LIKE ?'
        params.append(f'%{search}%')
    
    query += ' ORDER BY class, name'
    
    cursor.execute(query, params)
    students = cursor.fetchall()
    conn.close()
    
    return [dict(s) for s in students]

def get_all_teachers():
    """
    Get all teachers
    """
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM teachers ORDER BY name')
    teachers = cursor.fetchall()
    conn.close()
    
    return [dict(t) for t in teachers]

def get_student_by_id(student_id):
    """
    Get student by ID with attendance history
    """
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM students WHERE id = ?', (student_id,))
    student = cursor.fetchone()
    
    if not student:
        conn.close()
        return None
    
    student_dict = dict(student)
    
    cursor.execute('''
        SELECT date, status, time 
        FROM student_attendance 
        WHERE student_id = ? 
        ORDER BY date DESC
    ''', (student_id,))
    
    student_dict['attendance_history'] = [dict(a) for a in cursor.fetchall()]
    conn.close()
    
    return student_dict

def get_teacher_by_id(teacher_id):
    """
    Get teacher by ID with attendance history
    """
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM teachers WHERE id = ?', (teacher_id,))
    teacher = cursor.fetchone()
    
    if not teacher:
        conn.close()
        return None
    
    teacher_dict = dict(teacher)
    
    cursor.execute('''
        SELECT date, status, time 
        FROM teacher_attendance 
        WHERE teacher_id = ? 
        ORDER BY date DESC
    ''', (teacher_id,))
    
    teacher_dict['attendance_history'] = [dict(a) for a in cursor.fetchall()]
    conn.close()
    
    return teacher_dict

def get_class_averages():
    """
    Get average attendance for each class
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Get total days
    cursor.execute('''
        SELECT COUNT(DISTINCT date) as total FROM (
            SELECT date FROM student_attendance
            UNION
            SELECT date FROM teacher_attendance
        )
    ''')
    total_days = cursor.fetchone()['total']
    
    # Get class-wise attendance
    cursor.execute('''
        SELECT 
            s.class,
            COUNT(DISTINCT s.id) as student_count,
            COALESCE(SUM(CASE WHEN sa.status = 'PRESENT' THEN 1 ELSE 0 END), 0) as total_present,
            COALESCE(COUNT(DISTINCT sa.date), 0) as days_recorded
        FROM students s
        LEFT JOIN student_attendance sa ON s.id = sa.student_id
        GROUP BY s.class
        ORDER BY CAST(s.class AS INTEGER)
    ''')
    
    results = []
    for row in cursor.fetchall():
        class_data = dict(row)
        
        if total_days > 0:
            # Calculate class average
            cursor.execute('''
                SELECT AVG(present_count) as avg_present
                FROM (
                    SELECT COUNT(*) as present_count
                    FROM student_attendance sa2
                    WHERE sa2.student_id IN (
                        SELECT id FROM students WHERE class = ?
                    )
                    AND sa2.status = 'PRESENT'
                    GROUP BY sa2.student_id
                )
            ''', (class_data['class'],))
            
            avg_result = cursor.fetchone()
            avg_present = avg_result['avg_present'] if avg_result['avg_present'] else 0
            avg_percentage = round((avg_present / total_days) * 100, 2) if total_days > 0 else 0
        else:
            avg_percentage = 0
        
        results.append({
            'class': class_data['class'],
            'student_count': class_data['student_count'],
            'average_attendance': avg_percentage
        })
    
    conn.close()
    return results

def search_all(query):
    """
    Search students and teachers by name
    """
    conn = get_db()
    cursor = conn.cursor()
    
    results = {
        'students': [],
        'teachers': []
    }
    
    if not query:
        conn.close()
        return results
    
    # Search students
    cursor.execute('''
        SELECT s.*, 
               COUNT(CASE WHEN sa.status = 'PRESENT' THEN 1 END) as present_count
        FROM students s
        LEFT JOIN student_attendance sa ON s.id = sa.student_id
        WHERE s.name LIKE ?
        GROUP BY s.id
        LIMIT 20
    ''', (f'%{query}%',))
    
    results['students'] = [dict(r) for r in cursor.fetchall()]
    
    # Search teachers
    cursor.execute('''
        SELECT t.*,
               COUNT(CASE WHEN ta.status = 'PRESENT' THEN 1 END) as present_count
        FROM teachers t
        LEFT JOIN teacher_attendance ta ON t.id = ta.teacher_id
        WHERE t.name LIKE ?
        GROUP BY t.id
        LIMIT 20
    ''', (f'%{query}%',))
    
    results['teachers'] = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    return results