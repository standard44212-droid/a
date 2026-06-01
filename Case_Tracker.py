import sys
import json
import os

import easyocr
import mss
import numpy as np

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QLineEdit,
)
from PyQt6.QtGui import QGuiApplication, QPainter, QColor, QPen
from PyQt6.QtCore import QRect, QPoint, Qt


class ScreenSelector(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.showFullScreen()

        self.start_point = QPoint()
        self.end_point = QPoint()
        self.selecting = False

        self.step = "inventory"
        self.callback = None

    def mousePressEvent(self, event):
        self.start_point = event.pos()
        self.end_point = event.pos()
        self.selecting = True

    def mouseMoveEvent(self, event):
        self.end_point = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        self.end_point = event.pos()
        self.selecting = False

        rect = QRect(self.start_point, self.end_point).normalized()

        result = {
            "left": rect.left(),
            "top": rect.top(),
            "width": rect.width(),
            "height": rect.height()
        }

        self.callback(self.step, result)
        self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # dark overlay (but transparent)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))

        if self.selecting:
            pen = QPen(QColor(0, 255, 0), 2)
            painter.setPen(pen)

            rect = QRect(self.start_point, self.end_point)
            painter.drawRect(rect)


class CaseTracker(QWidget):
    def __init__(self):
        super().__init__()

        self.config_file = "config.json"
        self.load_config()

        self.reader = easyocr.Reader(['en'], gpu=False)

        self.setWindowTitle("Case Tracker")
        self.setGeometry(100, 100, 500, 550)

        self.setStyleSheet("""
            QWidget {
                background-color: black;
                color: white;
                font-size: 14px;
            }

            QPushButton {
                background-color: #222;
                border: 1px solid #555;
                padding: 8px;
            }

            QLineEdit {
                background-color: #111;
                border: 1px solid #555;
                padding: 5px;
                color: white;
            }
        """)

        layout = QVBoxLayout()

        self.case_cost = QLineEdit()
        self.case_cost.setPlaceholderText("Cost Per 5 Cases")

        self.start_button = QPushButton("Start Session")
        self.stop_button = QPushButton("Stop Session")
        self.reset_button = QPushButton("Reset Session")
        self.calibrate_button = QPushButton("Recalibrate OCR")
        self.test_ocr_button = QPushButton("Test OCR")

        self.status_label = QLabel("Status: Waiting")
        self.rolls_label = QLabel("Rolls: 0")

        self.last_roll_label = QLabel("Last Roll: $0.00")
        self.session_label = QLabel("Session P/L: $0.00")

        self.starting_label = QLabel("Starting Net Worth: $0.00")
        self.current_label = QLabel("Current Net Worth: $0.00")

        layout.addWidget(self.case_cost)

        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.reset_button)

        layout.addWidget(self.calibrate_button)
        layout.addWidget(self.test_ocr_button)

        layout.addSpacing(15)

        layout.addWidget(self.status_label)
        layout.addWidget(self.rolls_label)

        layout.addSpacing(15)

        layout.addWidget(self.last_roll_label)
        layout.addWidget(self.session_label)

        layout.addSpacing(15)

        layout.addWidget(self.starting_label)
        layout.addWidget(self.current_label)

        self.calibrate_button.clicked.connect(self.calibrate_ocr)
        self.test_ocr_button.clicked.connect(self.test_ocr)

        self.setLayout(layout)

    # ---------------- CONFIG ----------------

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    self.config = json.load(f)
            except:
                self.config = {
                    "inventory_region": None,
                    "cash_region": None
                }
        else:
            self.config = {
                "inventory_region": None,
                "cash_region": None
            }

    def save_config(self):
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)

    # ---------------- OCR CORE ----------------

    def capture_region(self, region):
        with mss.mss() as sct:
            img = np.array(sct.grab(region))
        return img

    def read_region(self, region):
        img = self.capture_region(region)

        results = self.reader.readtext(
            img,
            detail=0,
            paragraph=False,
            allowlist="0123456789,.$"
        )

        if not results:
            return "NO TEXT"

        print("OCR RESULTS:", results)
        return " ".join(results)

    # ---------------- BUTTONS ----------------

    def calibrate_ocr(self):
        self.hide()

        self.overlay = ScreenSelector()

        self.calibration_data = {}

        def handle_selection(step, region):
            self.calibration_data[step] = region

            if step == "inventory":
                self.overlay = ScreenSelector()
                self.overlay.step = "cash"
                self.overlay.callback = handle_selection
            else:
                self.config["inventory_region"] = self.calibration_data["inventory"]
                self.config["cash_region"] = self.calibration_data["cash"]

                self.save_config()

                self.status_label.setText("Calibration Saved")
                self.show()

        self.overlay.callback = handle_selection

    def test_ocr(self):
        inv = self.config.get("inventory_region")
        cash = self.config.get("cash_region")

        if not inv or not cash:
            self.status_label.setText("Status: Configure OCR regions first")
            return

        try:
            inv_text = self.read_region(inv)
            cash_text = self.read_region(cash)

            print("Inventory OCR:", inv_text)
            print("Cash OCR:", cash_text)

            self.status_label.setText(
                f"Inventory: {inv_text} | Cash: {cash_text}"
            )

        except Exception as e:
            self.status_label.setText(f"OCR Error: {str(e)}")


# ---------------- RUN APP ----------------

app = QApplication(sys.argv)
window = CaseTracker()
window.show()
sys.exit(app.exec())
