APP_STYLE = """
QMainWindow, QWidget { background: #f5f7fa; color: #172033; font-family: "Segoe UI"; }
QFrame#panel, QFrame#card { background: #ffffff; border: 1px solid #e1e6ef; border-radius: 12px; }
QLabel#appTitle { color: #14213d; font-size: 24px; font-weight: 700; }
QLabel#subtitle { color: #667085; font-size: 13px; }
QLabel#sectionTitle { color: #14213d; font-size: 18px; font-weight: 650; }
QLabel#muted { color: #667085; }
QLineEdit, QComboBox, QTableView, QListWidget, QTextEdit { background: #ffffff; border: 1px solid #cfd6e2; border-radius: 7px; padding: 7px; }
QLineEdit:focus, QComboBox:focus, QTableView:focus, QTextEdit:focus { border: 2px solid #4f7cff; }
QPushButton { background: #315efb; color: white; border: 0; border-radius: 7px; padding: 9px 16px; font-weight: 600; }
QPushButton:hover { background: #244bd1; }
QPushButton#secondary { background: #e9eef8; color: #243b67; }
QPushButton#danger { background: #c9374b; }
QPushButton:disabled { background: #b7c0cf; color: #f7f8fa; }
QLabel#badgeSuccess { color: #087443; background: #e3f7ed; padding: 7px 10px; border-radius: 7px; }
QLabel#badgeWarning { color: #915c00; background: #fff3d6; padding: 7px 10px; border-radius: 7px; }
QLabel#badgeDanger { color: #a3283b; background: #fde8ec; padding: 7px 10px; border-radius: 7px; }
QProgressBar { height: 10px; border: 0; border-radius: 5px; background: #e6eaf0; text-align: center; }
QProgressBar::chunk { background: #315efb; border-radius: 5px; }
QHeaderView::section { background: #eef2f7; color: #344054; padding: 7px; border: 0; font-weight: 600; }
QToolTip { background: #172033; color: #ffffff; border: 0; padding: 5px; }
"""
