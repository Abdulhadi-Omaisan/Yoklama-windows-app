import tkinter as tk
from tkinter import messagebox, ttk
import sqlite3
import cv2
import face_recognition
import numpy as np
import pickle
import os
import threading
import queue
from datetime import datetime
import time

# --- إعدادات وثوابت ---
DB_NAME = 'attendance.db'
IMAGES_DIR = 'student_faces'
BG_COLOR = "#f0f4f8"
PRIMARY_COLOR = "#2980b9"
ACCENT_COLOR = "#27ae60"
ERROR_COLOR = "#c0392b"
FONT_HEADER = ("Helvetica", 20, "bold")
FONT_NORMAL = ("Helvetica", 12)

if not os.path.exists(IMAGES_DIR):
    os.makedirs(IMAGES_DIR)

# --- توزيع المواد على الدكاترة ---
SUBJECT_INSTRUCTORS = {
    "Mathematics": "dr_math",
    "Physics": "dr_math",
    "Science": "dr_math",
    "Chemistry": "dr_math",
    "Programming": "dr_cs",
    "Algorithms": "dr_cs",
    "Networks": "dr_cs",
    "Databases": "dr_cs",
    "Graduation Project": "dr_cs",
    "Seminar": "dr_cs",
    "English": "dr_math"
}

# --- الجدول الدراسي ---
WEEKLY_SCHEDULE = {
    "Sunday": [("Mathematics", "08:00 AM", "Room 101"), ("Science", "10:00 AM", "Lab A")],
    "Monday": [("Physics", "09:00 AM", "Lab B"), ("Programming", "11:00 AM", "Computer Lab")],
    "Tuesday": [("Mathematics", "08:30 AM", "Room 101"), ("Algorithms", "10:30 AM", "Room 202")],
    "Wednesday": [("Networks", "09:00 AM", "Net Lab"), ("Databases", "12:00 PM", "PC Lab")],
    "Thursday": [("Graduation Project", "08:00 AM", "Auditorium")]
}

# --- إعداد قاعدة البيانات ---
def create_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS students (
                    student_id TEXT PRIMARY KEY, secret_code TEXT, name TEXT,
                    face_encoding BLOB, is_face_registered INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS instructors (
                    instructor_id TEXT PRIMARY KEY, secret_code TEXT, name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
                    subject_name TEXT PRIMARY KEY, is_active INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
                    student_id TEXT, subject_name TEXT, timestamp TEXT,
                    UNIQUE(student_id, subject_name, timestamp))''')
    
    try:
        c.execute("INSERT OR IGNORE INTO students (student_id, secret_code, name) VALUES (?, ?, ?)", ('101', '1234', 'Ahmed Ali'))
        c.execute("INSERT OR IGNORE INTO instructors (instructor_id, secret_code, name) VALUES (?, ?, ?)", ('dr_math', '1000', 'Dr. Sami'))
        c.execute("INSERT OR IGNORE INTO instructors (instructor_id, secret_code, name) VALUES (?, ?, ?)", ('dr_cs', '2000', 'Dr. Omar'))
        
        all_subjects = []
        for day_subs in WEEKLY_SCHEDULE.values():
            for s in day_subs: all_subjects.append(s[0])
        for sub in set(all_subjects):
            c.execute("INSERT OR IGNORE INTO sessions (subject_name, is_active) VALUES (?, 0)", (sub,))
        conn.commit()
    except Exception as e: print(f"DB Error: {e}")
    conn.close()

create_db()

current_user = None
current_user_role = None

# --- التطبيق الرئيسي ---
class SmartAttendanceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("University Smart Attendance System")
        self.geometry("1000x700") # حجم مبدئي كبير
        self.configure(bg=BG_COLOR)
        
        # Styles
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabel", background=BG_COLOR, font=FONT_NORMAL)
        style.configure("Header.TLabel", font=FONT_HEADER, foreground=PRIMARY_COLOR, background=BG_COLOR)
        style.configure("TButton", font=("Helvetica", 11, "bold"), background=PRIMARY_COLOR, foreground="white", padding=10)
        style.map("TButton", background=[('active', '#1abc9c')])
        style.configure("Capture.TButton", font=("Helvetica", 14, "bold"), background=ACCENT_COLOR, foreground="white", padding=15)
        
        self.container = tk.Frame(self, bg=BG_COLOR)
        self.container.pack(fill="both", expand=True)
        
        # --- (تصحيح المشكلة 1: جعل الشبكة تتمدد) ---
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)
        
        self.frames = {}
        for F in (LoginFrame, RegistrationFrame, TeacherDashboard, StudentDashboard):
            frame = F(self.container, self)
            self.frames[F] = frame
            frame.grid(row=0, column=0, sticky="nsew") # nsew يعني التمدد في كل الاتجاهات
            
        self.show_frame(LoginFrame)

    def show_frame(self, frame_class):
        frame = self.frames[frame_class]
        frame.tkraise()
        if hasattr(frame, 'on_show'): frame.on_show()

# --- Login ---
class LoginFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_COLOR)
        self.controller = controller
        center_frame = tk.Frame(self, bg="white", padx=40, pady=40, bd=1, relief="solid")
        center_frame.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(center_frame, text="System Login", font=FONT_HEADER, bg="white", fg=PRIMARY_COLOR).pack(pady=(0, 20))
        tk.Label(center_frame, text="User ID:", bg="white", font=FONT_NORMAL).pack(anchor="w")
        self.entry_id = ttk.Entry(center_frame, font=FONT_NORMAL, width=30); self.entry_id.pack(pady=5)
        tk.Label(center_frame, text="Secret Code:", bg="white", font=FONT_NORMAL).pack(anchor="w")
        self.entry_code = ttk.Entry(center_frame, show="*", font=FONT_NORMAL, width=30); self.entry_code.pack(pady=5)
        ttk.Button(center_frame, text="LOGIN", command=self.login).pack(pady=20, fill="x")
        tk.Label(center_frame, text="Hint: Student(101/1234) | Doc(dr_cs/2000)", bg="white", fg="gray").pack()

    def login(self):
        global current_user, current_user_role
        uid = self.entry_id.get(); code = self.entry_code.get()
        conn = sqlite3.connect(DB_NAME); c = conn.cursor()
        
        if c.execute("SELECT name FROM instructors WHERE instructor_id=? AND secret_code=?", (uid, code)).fetchone():
            current_user = uid; current_user_role = 'teacher'; conn.close()
            self.controller.show_frame(TeacherDashboard)
            return

        res = c.execute("SELECT is_face_registered FROM students WHERE student_id=? AND secret_code=?", (uid, code)).fetchone()
        conn.close()
        if res:
            current_user = uid; current_user_role = 'student'
            self.controller.show_frame(RegistrationFrame if res[0]==0 else StudentDashboard)
        else: messagebox.showerror("Error", "Invalid Credentials")

# --- Registration ---
class RegistrationFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_COLOR)
        self.controller = controller; self.capture_queue = queue.Queue(); self.capture_requested = False
        ttk.Label(self, text="Face Enrollment", style="Header.TLabel").pack(pady=20)
        info = tk.Frame(self, bg="white", padx=20, pady=20); info.pack(pady=10)
        tk.Label(info, text="1. Wait for GREEN box.\n2. Click 'CAPTURE'.\n(3 Angles)", bg="white", font=FONT_NORMAL).pack()
        self.btn_capture = ttk.Button(self, text="📸 CAPTURE", command=lambda: setattr(self, 'capture_requested', True), style="Capture.TButton", state="disabled")
        self.btn_capture.pack(pady=20)
        self.btn_start = ttk.Button(self, text="Start Camera", command=self.start_thread); self.btn_start.pack()
        ttk.Button(self, text="Logout", command=lambda: controller.show_frame(LoginFrame)).pack(pady=10)

    def start_thread(self):
        self.btn_start.config(state="disabled"); self.btn_capture.config(state="normal")
        threading.Thread(target=self.run_camera, daemon=True).start(); self.check_queue()

    def run_camera(self):
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened(): self.capture_queue.put(("error", "No Camera")); return
        encs = []; steps = ["Front", "Right", "Left"]; idx = 0
        while idx < 3:
            ret, frame = cap.read()
            if not ret: continue
            try:
                frame = np.ascontiguousarray(frame.astype(np.uint8))
                rgb = cv2.cvtColor(cv2.resize(frame, (0,0), fx=0.5, fy=0.5), cv2.COLOR_BGR2RGB)
                boxes = face_recognition.face_locations(rgb)
                color = (0, 255, 0) if boxes else (0, 0, 255)
                if boxes:
                    t,r,b,l = boxes[0]; cv2.rectangle(frame, (l*2, t*2), (r*2, b*2), color, 2)
                cv2.putText(frame, f"{steps[idx]}", (20,40), 4, 1, color, 2)
                cv2.imshow("Registration", frame)
                key = cv2.waitKey(30)
                if self.capture_requested and boxes:
                    self.capture_requested = False
                    full_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    encs.append(face_recognition.face_encodings(full_rgb)[0])
                    cv2.imwrite(f"{IMAGES_DIR}/{current_user}_{steps[idx]}.jpg", frame)
                    idx += 1; cv2.waitKey(200)
                if key == 27: break
            except: continue
        cap.release(); cv2.destroyAllWindows()
        if len(encs)==3: self.capture_queue.put(("success", np.mean(encs, axis=0)))
        else: self.capture_queue.put(("cancel", None))

    def check_queue(self):
        try:
            msg = self.capture_queue.get_nowait()
            if msg[0] == "success":
                conn = sqlite3.connect(DB_NAME); conn.cursor().execute("UPDATE students SET face_encoding=?, is_face_registered=1 WHERE student_id=?", (pickle.dumps(msg[1]), current_user)); conn.commit(); conn.close()
                messagebox.showinfo("Done", "Registered!"); self.controller.show_frame(StudentDashboard)
            elif msg[0] == "error": messagebox.showerror("Error", msg[1])
            self.btn_start.config(state="normal"); self.btn_capture.config(state="disabled")
        except: self.after(100, self.check_queue)

# --- Teacher Dashboard ---
class TeacherDashboard(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_COLOR)
        header = tk.Frame(self, bg=PRIMARY_COLOR, padx=20, pady=15); header.pack(fill="x")
        self.lbl_welcome = tk.Label(header, text="Instructor Dashboard", font=("Arial", 14, "bold"), bg=PRIMARY_COLOR, fg="white"); self.lbl_welcome.pack(side="left")
        tk.Button(header, text="Logout", bg="#c0392b", fg="white", bd=0, padx=10, command=lambda: controller.show_frame(LoginFrame)).pack(side="right")
        
        # Scrollable Area (Fixed Width Issue)
        canvas = tk.Canvas(self, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas, bg=BG_COLOR)
        
        # --- (تصحيح المشكلة 2: إجبار الإطار الداخلي على أخذ عرض الشاشة) ---
        self.window_id = canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(self.window_id, width=e.width))
        
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")
        self.ui_elements = {}

    def on_show(self):
        self.lbl_welcome.config(text=f"Instructor: {current_user}")
        for w in self.scrollable_frame.winfo_children(): w.destroy()
        self.ui_elements = {}
        
        for day, subs in WEEKLY_SCHEDULE.items():
            my_subjects = [s for s in subs if SUBJECT_INSTRUCTORS.get(s[0]) == current_user]
            if not my_subjects: continue
            
            day_frame = tk.Frame(self.scrollable_frame, bg="white", bd=1, relief="solid"); day_frame.pack(fill="x", pady=10, padx=5)
            tk.Label(day_frame, text=day, font=("Arial", 12, "bold"), bg="#444", fg="white", padx=10, pady=5, anchor="w").pack(fill="x")
            
            for sub in my_subjects:
                row = tk.Frame(day_frame, bg="white", padx=10, pady=10); row.pack(fill="x", pady=1)
                
                info = tk.Frame(row, bg="white"); info.pack(side="left", fill="x", expand=True)
                tk.Label(info, text=sub[0], font=("Arial", 12, "bold"), bg="white", fg=PRIMARY_COLOR).pack(anchor="w")
                tk.Label(info, text=f"⏰ {sub[1]} | 📍 {sub[2]}", font=("Arial", 10), bg="white", fg="gray").pack(anchor="w")
                
                stats = tk.Frame(row, bg="white"); stats.pack(side="left", padx=20)
                lbl_st = tk.Label(stats, text="Closed", font=("Arial", 10, "bold"), bg="white", fg=ERROR_COLOR); lbl_st.pack()
                lbl_cnt = tk.Label(stats, text="Count: 0", font=("Arial", 10), bg="white"); lbl_cnt.pack()
                
                btn = tk.Button(row, text="Open", bg=ACCENT_COLOR, fg="white", bd=0, padx=10, command=lambda s=sub[0]: self.toggle(s)); btn.pack(side="right")
                self.ui_elements[sub[0]] = {'st': lbl_st, 'cnt': lbl_cnt, 'btn': btn}
                tk.Frame(day_frame, bg="#eee", height=1).pack(fill="x")
        self.update_live()

    def toggle(self, sub):
        conn = sqlite3.connect(DB_NAME); c = conn.cursor()
        curr = c.execute("SELECT is_active FROM sessions WHERE subject_name=?", (sub,)).fetchone()
        new = 1 if curr and curr[0]==0 else 0
        c.execute("UPDATE sessions SET is_active=? WHERE subject_name=?", (new, sub)); conn.commit(); conn.close()
        self.update_single(sub)

    def update_live(self):
        if not self.winfo_ismapped(): return
        for sub in self.ui_elements: self.update_single(sub)
        self.after(3000, self.update_live)

    def update_single(self, sub):
        conn = sqlite3.connect(DB_NAME); c = conn.cursor()
        active = c.execute("SELECT is_active FROM sessions WHERE subject_name=?", (sub,)).fetchone()
        active = active[0] if active else 0
        cnt = c.execute("SELECT COUNT(*) FROM attendance WHERE subject_name=? AND timestamp LIKE ?", (sub, f"{datetime.now().strftime('%Y-%m-%d')}%")).fetchone()[0]
        conn.close()
        el = self.ui_elements[sub]
        el['st'].config(text="● OPEN" if active else "● CLOSED", fg=ACCENT_COLOR if active else "gray")
        el['btn'].config(text="Close" if active else "Open", bg=ERROR_COLOR if active else ACCENT_COLOR)
        el['cnt'].config(text=f"Present: {cnt}")

# --- Student Dashboard ---
class StudentDashboard(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_COLOR)
        self.controller = controller; self.verify_queue = queue.Queue()
        
        header = tk.Frame(self, bg=PRIMARY_COLOR, padx=20, pady=15); header.pack(fill="x")
        self.lbl_welcome = tk.Label(header, text="Welcome", font=("Arial", 14, "bold"), bg=PRIMARY_COLOR, fg="white"); self.lbl_welcome.pack(side="left")
        tk.Button(header, text="Logout", bg="#c0392b", fg="white", bd=0, padx=10, command=lambda: controller.show_frame(LoginFrame)).pack(side="right")
        
        canvas = tk.Canvas(self, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas, bg=BG_COLOR)
        
        # --- (تصحيح المشكلة 2: إجبار الإطار الداخلي على أخذ عرض الشاشة) ---
        self.window_id = canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(self.window_id, width=e.width))
        
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")

        for day, subs in WEEKLY_SCHEDULE.items():
            day_cont = tk.Frame(self.scrollable_frame, bg="white", bd=1, relief="solid"); day_cont.pack(fill="x", pady=10, padx=5)
            tk.Label(day_cont, text=day, font=("Arial", 12, "bold"), bg=PRIMARY_COLOR, fg="white", pady=5, padx=10, anchor="w").pack(fill="x")
            for sub in subs:
                row = tk.Frame(day_cont, bg="white", padx=10, pady=10); row.pack(fill="x", pady=1)
                info = tk.Frame(row, bg="white"); info.pack(side="left", fill="x", expand=True)
                tk.Label(info, text=sub[0], font=("Arial", 12, "bold"), bg="white", fg="#333").pack(anchor="w")
                tk.Label(info, text=f"⏰ {sub[1]} | 📍 {sub[2]}", font=("Arial", 10), bg="white", fg="gray").pack(anchor="w")
                tk.Button(row, text="Mark Attendance", bg=ACCENT_COLOR, fg="white", bd=0, padx=15, pady=5, command=lambda s=sub[0]: self.start_verify(s)).pack(side="right")
                tk.Frame(day_cont, bg="#eee", height=1).pack(fill="x")

    def on_show(self): self.lbl_welcome.config(text=f"Student ID: {current_user}")
    def start_verify(self, sub): threading.Thread(target=self.run_verify, args=(sub,), daemon=True).start(); self.check_queue()
    def run_verify(self, sub):
        conn = sqlite3.connect(DB_NAME); c = conn.cursor()
        active = c.execute("SELECT is_active FROM sessions WHERE subject_name=?", (sub,)).fetchone()
        if not active or active[0]==0: conn.close(); self.verify_queue.put(("error", "Closed")); return
        enc = pickle.loads(c.execute("SELECT face_encoding FROM students WHERE student_id=?", (current_user,)).fetchone()[0]); conn.close()
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW); found = False; start = time.time()
        while time.time()-start < 8:
            ret, frame = cap.read()
            if not ret: break
            try:
                frame = np.ascontiguousarray(frame.astype(np.uint8))
                rgb = cv2.cvtColor(cv2.resize(frame, (0,0), fx=0.5, fy=0.5), cv2.COLOR_BGR2RGB)
                boxes = face_recognition.face_locations(rgb)
                color = (0, 0, 255); txt = "Scanning..."
                if boxes:
                    match = face_recognition.compare_faces([enc], face_recognition.face_encodings(rgb, boxes)[0], 0.5)
                    if match[0]:
                        color = (0, 255, 0); txt = "MATCHED!"; found = True
                        t,r,b,l = boxes[0]; cv2.rectangle(frame, (l*2, t*2), (r*2, b*2), color, 3)
                        cv2.putText(frame, txt, (30,50), 4, 1, color, 2); cv2.imshow("Verify", frame); cv2.waitKey(1000); break
                cv2.putText(frame, txt, (30,50), 4, 1, color, 2); cv2.imshow("Verify", frame)
                if cv2.waitKey(30)==27: break
            except: continue
        cap.release(); cv2.destroyAllWindows()
        self.verify_queue.put(("success", sub) if found else ("error", "Failed"))

    def check_queue(self):
        try:
            msg = self.verify_queue.get_nowait()
            if msg[0]=="success":
                try:
                    conn = sqlite3.connect(DB_NAME); conn.cursor().execute("INSERT INTO attendance VALUES (?, ?, ?)", (current_user, msg[1], datetime.now().strftime("%Y-%m-%d"))); conn.commit(); conn.close()
                    messagebox.showinfo("Success", "Marked!")
                except: messagebox.showwarning("Info", "Already marked")
            else: messagebox.showerror("Error", msg[1])
        except: self.after(100, self.check_queue)

if __name__ == "__main__":
    app = SmartAttendanceApp()
    app.mainloop()