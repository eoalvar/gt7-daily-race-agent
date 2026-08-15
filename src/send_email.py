import os
import smtplib
from pathlib import Path
from email.message import EmailMessage


# Arquivo que contém o relatório mais recente
REPORT_FILE = Path("reports/latest.txt")


# Dados armazenados nos GitHub Secrets
EMAIL_USERNAME = os.environ["EMAIL_USERNAME"]
EMAIL_APP_PASSWORD = os.environ["EMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]


# Confere se o relatório existe
if not REPORT_FILE.exists():
    raise RuntimeError("reports/latest.txt not found")


# Lê o relatório
report = REPORT_FILE.read_text(encoding="utf-8")


# Cria o e-mail
message = EmailMessage()

message["Subject"] = "GT7 Daily Race C - Daily Report"
message["From"] = EMAIL_USERNAME
message["To"] = EMAIL_TO

message.set_content(report)


# Envia pelo Gmail
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:

    smtp.login(
        EMAIL_USERNAME,
        EMAIL_APP_PASSWORD
    )

    smtp.send_message(message)


print("Email sent successfully.")
