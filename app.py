from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'

# Hardcoded login credentials
LOGIN_USERNAME = 'admin'
LOGIN_PASSWORD = 'admin'

# MySQL database connection
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'attendance',
}

conn = mysql.connector.connect(**db_config)
c = conn.cursor()

# Create students table if it doesn't exist
c.execute('''CREATE TABLE IF NOT EXISTS students (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                roll_no INT UNIQUE NOT NULL,
                attendance_percentage DECIMAL(5, 2) DEFAULT 0
            )''')

# Create subjects table if it doesn't exist
c.execute('''CREATE TABLE IF NOT EXISTS subjects (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE
            )''')

# Create attendance table if it doesn't exist
c.execute('''CREATE TABLE IF NOT EXISTS attendance (
                id INT AUTO_INCREMENT PRIMARY KEY,
                student_id INT NOT NULL,
                subject_id INT NOT NULL,
                date DATE NOT NULL,
                status VARCHAR(50) NOT NULL,
                attendance_percentage DECIMAL(5, 2) DEFAULT 0,  -- Add this line
                FOREIGN KEY (student_id) REFERENCES students (id),
                FOREIGN KEY (subject_id) REFERENCES subjects (id)
            )''')

# Drop the trigger if it already exists
c.execute("DROP TRIGGER IF EXISTS update_student_attendance_percentage")

# Trigger to update attendance percentage when inserting or updating attendance records for students
c.execute('''CREATE TRIGGER update_student_attendance_percentage
            AFTER INSERT ON attendance
            FOR EACH ROW
            BEGIN
                UPDATE students
                SET attendance_percentage = (
                    SELECT (SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(id))
                    FROM attendance
                    WHERE student_id = NEW.student_id
                )
                WHERE id = NEW.student_id;
            END''')

# Drop the trigger if it already exists
c.execute("DROP TRIGGER IF EXISTS prevent_student_deletion")

# Trigger to prevent deletion of students with associated attendance records
c.execute('''CREATE TRIGGER prevent_student_deletion
            BEFORE DELETE ON students
            FOR EACH ROW
            BEGIN
                DECLARE attendance_count INT;
                SELECT COUNT(*) INTO attendance_count
                FROM attendance
                WHERE student_id = OLD.id;

                IF attendance_count > 0 THEN
                    SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'Cannot delete a student with attendance records';
                END IF;
            END''')

@app.route('/')
def home():
    if 'username' not in session:
        # User is not logged in, redirect to login
        return redirect(url_for('login'))

    # Get the total classes conducted per subject
    c.execute("SELECT subjects.name, COUNT(DISTINCT attendance.date) as total_classes FROM subjects LEFT JOIN attendance ON subjects.id = attendance.subject_id GROUP BY subjects.id")
    subject_data = c.fetchall()

    # Get the defaulters list
    c.execute("SELECT students.name, students.roll_no, subjects.name, (SUM(CASE WHEN attendance.status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(attendance.id)) as attendance_percentage FROM students INNER JOIN attendance ON students.id = attendance.student_id INNER JOIN subjects ON subjects.id = attendance.subject_id GROUP BY students.id, subjects.id HAVING attendance_percentage < 75")
    defaulters_data = c.fetchall()

    return render_template('index.html', subject_data=subject_data, defaulters_data=defaulters_data)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        # User is already logged in, redirect to home
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username == LOGIN_USERNAME and password == LOGIN_PASSWORD:
            # Authentication successful, store username in session
            session['username'] = username
            return redirect(url_for('home'))
        else:
            # Invalid credentials, show error message
            error = 'Invalid username or password'
            return render_template('login.html', error=error)

    return render_template('login.html')

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    # Clear the user's session
    session.clear()
    return redirect(url_for('login'))

@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if request.method == 'POST':
        name = request.form['name']
        roll_no = request.form['roll_no']

        # Insert the student into the database
        c.execute("INSERT INTO students (name, roll_no) VALUES (%s, %s)", (name, roll_no))
        conn.commit()

        return redirect(url_for('students_list'))

    return render_template('add_student.html')

@app.route('/add_subject', methods=['GET','POST'])
def add_subject():
    if request.method == 'POST':
        subject_name = request.form['subject_name']

        # Insert the subject into the database
        c.execute("INSERT INTO subjects (name) VALUES (%s)", (subject_name,))
        conn.commit()

        return redirect(url_for('home'))

    return render_template('add_subject.html')

@app.route('/mark_attendance', methods=['GET', 'POST'])
def mark_attendance():
    if request.method == 'POST':
        subject_id = request.form['subject']
        date = request.form['date']
        students = request.form.getlist('students')

        # Check if attendance for the given date and subject already exists
        c.execute("SELECT COUNT(*) FROM attendance WHERE date = %s AND subject_id = %s", (date, subject_id))
        attendance_count = c.fetchone()[0]

        if attendance_count > 0:
            flash('Attendance for the selected date and subject already exists', 'error')
            return redirect(url_for('mark_attendance'))

        for student_id in students:
            status = request.form.get(f'status_{student_id}')
            # Exclude attendance_percentage from the column list
            c.execute("INSERT INTO attendance (student_id, subject_id, date, status) VALUES (%s, %s, %s, %s)",
                      (student_id, subject_id, date, status))

        conn.commit()
        return redirect(url_for('students_list'))

    # Get all students
    c.execute("SELECT * FROM students")
    students = c.fetchall()

    # Get all subjects
    c.execute("SELECT * FROM subjects")
    subjects = c.fetchall()

    return render_template('mark_attendance.html', students=students, subjects=subjects)

@app.route('/students_list')
def students_list():
    # Get all students
    c.execute("SELECT * FROM students")
    students = c.fetchall()

    # Get all subjects
    c.execute("SELECT * FROM subjects")
    subjects = c.fetchall()

    students_data = []
    for student in students:
        student_id = student[0]
        name = student[1]
        roll_no = student[2]

        attendance_data = []
        for subject in subjects:
            subject_id = subject[0]
            subject_name = subject[1]

            # Calculate attendance for each subject
            c.execute("SELECT COUNT(*) FROM attendance WHERE student_id=%s AND subject_id=%s AND status='Present'",
                      (student_id, subject_id))
            present_attendance = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM attendance WHERE student_id=%s AND subject_id=%s",
                      (student_id, subject_id))
            total_attendance = c.fetchone()[0]

            attendance_data.append({
                'subject': subject_name,
                'present_attendance': present_attendance,
                'total_attendance': total_attendance
            })

        students_data.append({
            'name': name,
            'roll_no': roll_no,
            'attendance_data': attendance_data
        })

    return render_template('students_list.html', students_data=students_data, subjects=subjects)

if __name__ == '__main__':
    app.run(debug=True)
