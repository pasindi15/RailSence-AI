"""
notifications package
---------------------
Provides email notification facilities for RailSense AI Member C.
"""

from .email_service import EmailService, get_email_service

__all__ = ["EmailService", "get_email_service"]
