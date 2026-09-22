from __future__ import annotations


COLORS = {
    "app": "#F5F7FA", "surface": "#FFFFFF", "surface_alt": "#F9FAFB", "border": "#E4E7EC",
    "text": "#101828", "secondary": "#667085", "muted": "#98A2B3", "accent": "#714B67",
    "accent_hover": "#5F3F57", "accent_soft": "#F4EDF2", "success": "#157F5B",
    "success_soft": "#ECFDF3", "warning": "#B54708", "warning_soft": "#FFFAEB",
    "danger": "#B42318", "danger_soft": "#FEF3F2", "info": "#175CD3", "info_soft": "#EFF8FF",
    "nav": "#18212F", "nav_muted": "#A9B2C0", "nav_active": "#2B3545",
}


APP_STYLE = f"""
QMainWindow, QWidget {{ background: {COLORS['app']}; color: {COLORS['text']}; font-family: "Segoe UI Variable", "Segoe UI"; font-size: 13px; }}
QWidget#sidebar {{ background: {COLORS['nav']}; }}
QLabel#appTitle {{ color: {COLORS['text']}; font-size: 25px; font-weight: 700; }}
QLabel#pageTitle {{ color: {COLORS['text']}; font-size: 24px; font-weight: 700; }}
QLabel#sectionTitle {{ color: {COLORS['text']}; font-size: 16px; font-weight: 700; }}
QLabel#muted, QLabel#subtitle {{ color: {COLORS['secondary']}; }}
QLabel#eyebrow {{ color: {COLORS['accent']}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QFrame#card, QFrame#surfaceCard {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 12px; }}
QLineEdit, QComboBox, QTableView, QListWidget, QTextEdit {{ background: {COLORS['surface']}; border: 1px solid #D0D5DD; border-radius: 7px; padding: 7px; selection-background-color: {COLORS['accent_soft']}; selection-color: {COLORS['text']}; }}
QLineEdit:focus, QComboBox:focus, QTableView:focus, QTextEdit:focus {{ border: 2px solid {COLORS['accent']}; }}
QPushButton {{ background: {COLORS['accent']}; color: white; border: 0; border-radius: 7px; padding: 9px 16px; font-weight: 700; min-height: 18px; }}
QPushButton:hover {{ background: {COLORS['accent_hover']}; }}
QPushButton#secondary {{ background: {COLORS['surface']}; color: {COLORS['text']}; border: 1px solid {COLORS['border']}; }}
QPushButton#secondary:hover {{ background: {COLORS['accent_soft']}; border-color: {COLORS['accent']}; }}
QPushButton#danger {{ background: {COLORS['danger']}; }}
QPushButton:disabled {{ background: #D0D5DD; color: #98A2B3; }}
QLabel#badgeSuccess {{ color: {COLORS['success']}; background: {COLORS['success_soft']}; padding: 6px 9px; border-radius: 7px; font-weight: 700; }}
QLabel#badgeWarning {{ color: {COLORS['warning']}; background: {COLORS['warning_soft']}; padding: 6px 9px; border-radius: 7px; font-weight: 700; }}
QLabel#badgeDanger {{ color: {COLORS['danger']}; background: {COLORS['danger_soft']}; padding: 6px 9px; border-radius: 7px; font-weight: 700; }}
QLabel#badgeInfo {{ color: {COLORS['info']}; background: {COLORS['info_soft']}; padding: 6px 9px; border-radius: 7px; font-weight: 700; }}
QProgressBar {{ height: 8px; border: 0; border-radius: 4px; background: #EAECF0; text-align: center; }}
QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 4px; }}
QHeaderView::section {{ background: {COLORS['surface_alt']}; color: #344054; padding: 8px; border: 0; border-bottom: 1px solid {COLORS['border']}; font-weight: 700; }}
QTableView {{ gridline-color: transparent; alternate-background-color: {COLORS['surface_alt']}; }}
QToolTip {{ background: {COLORS['nav']}; color: white; border: 0; padding: 6px; }}
QScrollArea {{ border: 0; background: transparent; }}
QFrame#workflowItem {{ background: transparent; border-radius: 8px; }}
QFrame#workflowItem[workflowState="current"] {{ background: {COLORS['nav_active']}; }}
QFrame#workflowItem[workflowState="completed"] {{ background: transparent; }}
QLabel#workflowMarker {{ color: {COLORS['nav_muted']}; border: 1px solid #5E6A7B; border-radius: 12px; font-weight: 700; }}
QFrame#workflowItem[workflowState="current"] QLabel#workflowMarker {{ color: white; background: {COLORS['accent']}; border-color: {COLORS['accent']}; }}
QFrame#workflowItem[workflowState="completed"] QLabel#workflowMarker {{ color: white; background: {COLORS['success']}; border-color: {COLORS['success']}; }}
QLabel#workflowTitle {{ color: {COLORS['nav_muted']}; font-weight: 700; }}
QLabel#workflowHint {{ color: #788596; font-size: 11px; }}
QFrame#workflowItem[workflowState="current"] QLabel#workflowTitle {{ color: white; }}
QFrame#workflowItem[workflowState="current"] QLabel#workflowHint {{ color: #D8DEE8; }}
QFrame#workflowItem[workflowState="completed"] QLabel#workflowTitle {{ color: #D8DEE8; }}
"""
