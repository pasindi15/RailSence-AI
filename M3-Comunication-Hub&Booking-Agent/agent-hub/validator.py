"""
agent-hub/validator.py
----------------------
RailSense AI — Agent Communication Hub Validation Helpers
Phase 2: Validation of message envelope and recipient against registry.

Architectural rules:
- Validates receiver_agent against the central Agent Registry.
- Raises HTTP 404 if the receiver agent is unrecognised.
- Does NOT perform routing, JWT verification, or audit persistence.
"""

from __future__ import annotations

import os
import sys

# Ensure agent-hub directory is in sys.path
_CURRENT_DIR = os.path.dirname(__file__)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_CURRENT_DIR))

from fastapi import HTTPException, status
from registry import AgentEntry, AgentNotFoundError, get_agent_entry


def validate_receiver(receiver_agent: str) -> AgentEntry:
    """
    Validate that receiver_agent is registered in the agent registry.

    Parameters
    ----------
    receiver_agent : str
        The logical name of the receiving agent (e.g. 'booking-agent').

    Returns
    -------
    AgentEntry
        The registered agent descriptor.

    Raises
    ------
    HTTPException (404)
        If the receiver_agent is not registered in the agent registry.
    """
    try:
        return get_agent_entry(receiver_agent)
    except AgentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Receiver agent '{receiver_agent}' is not registered in the agent registry.",
        )
