import os
import smtplib
from pathlib import Path
from email.message import EmailMessage


REPORT_FILE = Path(
    "reports/latest.txt"
)

SUBJECT_FILE = Path(
    "reports/email_subject.txt"
)


EMAIL_USERNAME = os.environ[
    "EMAIL_USERNAME"
]

EMAIL_APP_PASSWORD = os.environ[
    "EMAIL_APP_PASSWORD"
]

EMAIL_TO = os.environ[
    "EMAIL_TO"
]


if not REPORT_FILE.exists():

    raise RuntimeError(
        "reports/latest.txt not found"
    )


report = REPORT_FILE.read_text(
    encoding="utf-8"
)


if SUBJECT_FILE.exists():

    subject = SUBJECT_FILE.read_text(
        encoding="utf-8"
    ).strip()

else:

    subject = (
        "GT7 Daily Race C"
    )


message = EmailMessage()

message[
    "Subject"
] = subject

message[
    "From"
] = EMAIL_USERNAME

message[
    "To"
] = EMAIL_TO


message.set_content(
    report
)


with smtplib.SMTP_SSL(
    "smtp.gmail.com",
    465
) as smtp:

    smtp.login(
        EMAIL_USERNAME,
        EMAIL_APP_PASSWORD
    )

    smtp.send_message(
        message
    )


print(
    "Email sent successfully."
)