# Booking Policies — RailSense AI

> These are the **actual policies enforced by the booking system** (`cancellation/rules.py`, `availability.py`, `schemas/booking.py`).

---

## Booking

- Tickets can be booked **up to 365 days in advance** (1 year).
- Minimum booking notice: the travel date must be **today or in the future** (bookings for past dates are rejected).
- Maximum **10 passengers per booking**.
- The **National Identity Card (NIC)** number of every passenger is required to make a booking.
- Each booking gets a unique **Booking Reference** (format: `RS-XXXXX`) and a **QR Ticket Token**.
- Supported seat classes: **First Class** and **Second Class** only. Third Class / unreserved is not available online.
- Bookings are confirmed only when payment is recorded and fraud review (if triggered) is cleared.
- A **5-minute seat hold** may be placed while the booking is being processed; held seats are temporarily removed from availability.
- If there is a mistake in passenger details or travel date, report it within 24 hours of issuance.

---

## Cancellation & Refunds

Cancellations are reviewed by an admin (Human-in-the-Loop). The refund amount is calculated automatically based on the policy tier below.

### Standard Cancellation Tiers

| Notice Before Departure | Refund | Deduction |
|---|---|---|
| **More than 48 hours** | 75% of fare | 25% administrative fee |
| **24 to 48 hours** | 50% of fare | 50% deduction |
| **Less than 24 hours** | 0% — Non-refundable | Full fare forfeited |

### Special Cancellation Cases

| Reason | Refund |
|---|---|
| **Railway Service Disruption** (train cancelled / service issue) | 100% full refund |
| **Duplicate Booking** (verified by system) | 100% full refund |
| **Personal Medical Emergency** (documented) | 80% compassionate refund |

### How Cancellation Works

1. Passenger submits a cancellation request with a reason.
2. The system calculates the suggested refund automatically using the rules above.
3. A **case reference** is created and sent to admin review queue.
4. Admin approves or rejects the cancellation request.
5. If **approved**: booking status changes to `CANCELLED`, seats are **immediately restored** to available, and refund is issued.
6. If **rejected**: booking remains `CONFIRMED` and active.
7. **Cancelled tickets are never deleted** — they remain in the database with `CANCELLED` status for audit purposes.

---

## Seat Availability & Double-Booking Protection

- Available seats = Schedule Capacity − Number of **CONFIRMED** bookings − Active seat holds.
- `CANCELLED`, `EXPIRED`, and `REJECTED` bookings do **not** consume seat capacity.
- A **row-level database lock** (`SELECT FOR UPDATE`) is applied during every booking to prevent two passengers from simultaneously taking the last seat.
- When a booking is cancelled, seats are immediately freed — no waiting period.

---

## Advance Booking Window

| Setting | Value |
|---|---|
| Maximum advance booking | **365 days (1 year)** |
| Minimum notice | Journey date must be today or future |
| Seat hold duration | 5 minutes (automatic expiry) |

---

## Ticket Validity

- Tickets are valid for the **specific train, date, and class** chosen at booking.
- Tickets cannot be transferred to a different passenger or date after confirmation.
- Point-to-point: ticket covers the **exact origin → destination** pair booked.

---

## Fraud Review

- Bookings that show unusual patterns (e.g., multiple bookings in short time, conflicting journeys) may be automatically flagged by the **IsolationForest ML model** (Security Agent, Port 8004).
- Flagged bookings enter `PENDING_FRAUD_REVIEW` status.
- An admin reviews and either **ALLOWS** or **REJECTS** the booking.
- If rejected: booking becomes `REJECTED` (non-refundable, seats freed).
- If allowed: booking is confirmed normally.

---

## Luggage

- Each passenger may carry one piece of luggage up to **25 kg** free of charge in reserved classes.
- Excess luggage is charged at **LKR 5 per kg** above the free allowance.
- Bicycles and large sporting equipment require a separate luggage ticket, purchased at the station.

---

## Service Disruptions & Delays

- Sri Lanka Railways does not guarantee exact arrival/departure times; delays may occur due to weather, signal faults, or track maintenance.
- In the event of a **cancelled service**, passengers may use their ticket on the next available train on the same route at no extra charge.
- Live delay predictions are available through the M2 Operations Agent (Port 8005).

---

## Complaints

- Equipment faults (AC, doors, seating) reported during travel are forwarded to the Maintenance Department (M4 Asset Intelligence Agent).
- Formal complaints can be filed at any staffed station counter or via the RailSense passenger helpline.
