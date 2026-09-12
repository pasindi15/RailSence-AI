"""
notifications/email_service.py
------------------------------
Reusable email notification service for RailSense AI Member C.

Sends automated notification emails for:
1. Successful booking confirmations
2. Human administrator cancellation approvals (with refund details)
3. Human administrator cancellation rejections (with admin reason)

Security & Reliability Rules:
- Credentials loaded via environment variables: SMTP_HOST, SMTP_PORT, SMTP_USERNAME,
  SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_USE_TLS.
- Never prints or leaks SMTP passwords or connection strings.
- Non-blocking failure semantics: If SMTP is offline or raises an error, the database
  transaction is NEVER rolled back. Errors are caught and logged safely.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger("railsense.notifications")


class EmailService:
    """
    Handles dispatching transactional email notifications via standard SMTP.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        from_email: str | None = None,
        use_tls: bool | None = None,
    ):
        self.host = host or os.getenv("SMTP_HOST", "localhost")
        try:
            self.port = port if port is not None else int(os.getenv("SMTP_PORT", "587"))
        except ValueError:
            self.port = 587

        self.username = (username if username is not None else os.getenv("SMTP_USERNAME", "")).strip() or None
        raw_pw = password if password is not None else os.getenv("SMTP_PASSWORD", "")
        # Remove spaces often formatted in app passwords (e.g. 'hhqk akaj stgc peby' -> 'hhqkakajstgcpeby')
        self.password = raw_pw.replace(" ", "").strip() if raw_pw else None
        self.from_email = (from_email or os.getenv("SMTP_FROM_EMAIL", "noreply@railsense.ai")).strip()
        
        if use_tls is not None:
            self.use_tls = use_tls
        else:
            tls_env = os.getenv("SMTP_USE_TLS", "true").strip().lower()
            self.use_tls = tls_env in ("true", "1", "yes")

    def _deliver(self, clean_to: str, msg: MIMEMultipart, subject: str) -> bool:
        """Internal worker executing the network SMTP delivery."""
        try:
            server = smtplib.SMTP(self.host, self.port, timeout=10)
            if self.use_tls:
                server.starttls()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.sendmail(self.from_email, [clean_to], msg.as_string())
            server.quit()
            logger.info(f"Email successfully dispatched to {clean_to} (Subject: {subject})")
            return True
        except Exception as exc:
            logger.warning(
                f"Failed to send email notification to {clean_to} (Subject: {subject}): {type(exc).__name__} - {exc}"
            )
            return False

    def _send_email(self, to_email: str, subject: str, text_content: str, html_content: str | None = None) -> bool:
        """
        Low-level SMTP message delivery.
        Returns True if successful, False if delivery failed or recipient was invalid.
        Never raises exceptions to callers; non-blocking and safe.
        """
        if not to_email or not str(to_email).strip():
            logger.info("Skipping email delivery: No recipient email address provided.")
            return False

        clean_to = str(to_email).strip()

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"RailSense AI <{self.from_email}>"
        msg["To"] = clean_to

        msg.attach(MIMEText(text_content, "plain"))
        if html_content:
            msg.attach(MIMEText(html_content, "html"))

        # Dispatch delivery in background thread so SMTP network handshake does not block HTTP responses
        import threading
        t = threading.Thread(target=self._deliver, args=(clean_to, msg, subject), daemon=True)
        t.start()
        return True

    def send_booking_confirmation_email(
        self,
        recipient_email: str | None,
        booking_reference: str,
        from_station: str,
        to_station: str,
        travel_date: str,
        train_id: str,
        seat_class: str,
        passenger_count: int,
        fare: str,
        status: str = "CONFIRMED",
    ) -> bool:
        """
        Dispatches booking confirmation notification.
        Subject: RailSense AI - Booking Confirmed
        """
        if not recipient_email:
            logger.info(f"No passenger email registered for booking {booking_reference}; email skipped.")
            return False

        subject = "RailSense AI - Booking Confirmed"
        text_body = (
            f"Dear Passenger,\n\n"
            f"Your train booking has been successfully confirmed!\n\n"
            f"--- Booking Details ---\n"
            f"Booking Reference : {booking_reference}\n"
            f"Train Service     : {train_id}\n"
            f"Route             : {from_station} to {to_station}\n"
            f"Travel Date       : {travel_date}\n"
            f"Seat Class        : {seat_class}\n"
            f"Passengers        : {passenger_count}\n"
            f"Total Fare        : Rs. {fare}\n"
            f"Booking Status    : {status}\n\n"
            f"Thank you for choosing RailSense AI Railway Reservation.\n"
        )
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #222; background-color: #f9f9f9; padding: 20px;">
            <div style="max-width: 580px; margin: 0 auto; background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 24px;">
                <h2 style="color: #8B4513; margin-top: 0;">RailSense AI — Booking Confirmed</h2>
                <p>Dear Passenger,</p>
                <p>Your railway ticket reservation has been confirmed in the ledger.</p>
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Booking Reference:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee; font-family: monospace; font-size: 16px; color: #8B4513;">{booking_reference}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Train Service:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{train_id}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Journey Route:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{from_station} &rarr; {to_station}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Travel Date:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{travel_date}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Class & Count:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{seat_class} ({passenger_count} passenger{'s' if passenger_count > 1 else ''})</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Confirmed Fare:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">Rs. {fare}</td></tr>
                    <tr><td style="padding: 8px;"><strong>Status:</strong></td><td style="padding: 8px; color: green; font-weight: bold;">{status}</td></tr>
                </table>
                <p style="font-size: 13px; color: #666;">RailSense AI Autonomous Train Ticketing System</p>
            </div>
        </body>
        </html>
        """
        return self._send_email(recipient_email, subject, text_body, html_body)

    def send_cancellation_approved_email(
        self,
        recipient_email: str | None,
        booking_reference: str,
        refund_amount: str,
        from_station: str = "",
        to_station: str = "",
        travel_date: str = "",
        train_id: str = "",
        admin_reason: str | None = None,
    ) -> bool:
        """
        Dispatches cancellation approved notification.
        Only called after a human administrator approves the cancellation.
        Subject: RailSense AI - Cancellation Approved
        """
        if not recipient_email:
            logger.info(f"No passenger email registered for booking {booking_reference}; approval email skipped.")
            return False

        subject = "RailSense AI - Cancellation Approved"
        route_str = f"{from_station} to {to_station}" if from_station and to_station else "Your journey"
        text_body = (
            f"Dear Passenger,\n\n"
            f"Your cancellation request for booking reference {booking_reference} has been APPROVED by an administrator.\n\n"
            f"--- Cancellation Details ---\n"
            f"Booking Reference : {booking_reference}\n"
            f"Cancellation Result: APPROVED\n"
            f"Ticket Status      : CANCELLED\n"
            f"Applicable Refund  : Rs. {refund_amount}\n"
            f"Journey Details    : {route_str} on {travel_date}\n"
            f"{f'Admin Remarks      : {admin_reason}' if admin_reason else ''}\n\n"
            f"Thank you for using RailSense AI.\n"
        )
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #222; background-color: #f9f9f9; padding: 20px;">
            <div style="max-width: 580px; margin: 0 auto; background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 24px;">
                <h2 style="color: #2e7d32; margin-top: 0;">RailSense AI — Cancellation Approved</h2>
                <p>Dear Passenger,</p>
                <p>Your cancellation request for booking <strong style="font-family: monospace;">{booking_reference}</strong> has been reviewed and <strong>APPROVED</strong> by the railway administration.</p>
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Booking Reference:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee; font-family: monospace;">{booking_reference}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Decision:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee; color: #2e7d32; font-weight: bold;">CANCELLATION APPROVED</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Ticket Status:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee; color: #d32f2f; font-weight: bold;">CANCELLED</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Final Refund Amount:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold; font-size: 16px; color: #2e7d32;">Rs. {refund_amount}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Journey:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{route_str} on {travel_date}</td></tr>
                    {f'<tr><td style="padding: 8px;"><strong>Admin Remarks:</strong></td><td style="padding: 8px;">{admin_reason}</td></tr>' if admin_reason else ''}
                </table>
                <p style="font-size: 13px; color: #666;">RailSense AI Autonomous Train Ticketing System</p>
            </div>
        </body>
        </html>
        """
        return self._send_email(recipient_email, subject, text_body, html_body)

    def send_cancellation_rejected_email(
        self,
        recipient_email: str | None,
        booking_reference: str,
        admin_reason: str | None = None,
        from_station: str = "",
        to_station: str = "",
        travel_date: str = "",
    ) -> bool:
        """
        Dispatches cancellation rejected notification.
        Only called after a human administrator rejects the cancellation request.
        Subject: RailSense AI - Cancellation Request Rejected
        Booking status remains CONFIRMED.
        """
        if not recipient_email:
            logger.info(f"No passenger email registered for booking {booking_reference}; rejection email skipped.")
            return False

        subject = "RailSense AI - Cancellation Request Rejected"
        reason_text = admin_reason or "Does not meet cancellation and refund policy requirements."
        route_str = f"{from_station} to {to_station}" if from_station and to_station else "Your journey"
        text_body = (
            f"Dear Passenger,\n\n"
            f"Your cancellation request for booking reference {booking_reference} has been REJECTED by an administrator.\n\n"
            f"--- Rejection Details ---\n"
            f"Booking Reference  : {booking_reference}\n"
            f"Cancellation Result : REJECTED\n"
            f"Booking Status     : CONFIRMED (Your ticket remains valid)\n"
            f"Administrator Reason: {reason_text}\n"
            f"Journey            : {route_str} on {travel_date}\n\n"
            f"Your booking remains active. You may board the train on your scheduled travel date.\n"
        )
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #222; background-color: #f9f9f9; padding: 20px;">
            <div style="max-width: 580px; margin: 0 auto; background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 24px;">
                <h2 style="color: #c62828; margin-top: 0;">RailSense AI — Cancellation Request Rejected</h2>
                <p>Dear Passenger,</p>
                <p>Your cancellation request for booking <strong style="font-family: monospace;">{booking_reference}</strong> has been reviewed and <strong>REJECTED</strong> by the railway administration.</p>
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Booking Reference:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee; font-family: monospace;">{booking_reference}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Decision:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee; color: #c62828; font-weight: bold;">REJECTED</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Booking Status:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee; color: #2e7d32; font-weight: bold;">CONFIRMED (Ticket Remains Valid)</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Administrator Reason:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{reason_text}</td></tr>
                    <tr><td style="padding: 8px;"><strong>Journey:</strong></td><td style="padding: 8px;">{route_str} on {travel_date}</td></tr>
                </table>
                <p style="font-size: 14px; color: #333;">Your booking remains confirmed and valid for travel.</p>
                <p style="font-size: 13px; color: #666;">RailSense AI Autonomous Train Ticketing System</p>
            </div>
        </body>
        </html>
        """
        return self._send_email(recipient_email, subject, text_body, html_body)


# Singleton instance getter
_default_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    global _default_email_service
    if _default_email_service is None:
        _default_email_service = EmailService()
    return _default_email_service
