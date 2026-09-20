# Fares — RailSense AI Booking System

> Fares below are the **exact values used by the booking system** (`fare.py`).
> Total fare = fare per passenger × number of passengers.

---

## Main Line — Colombo Fort ↔ Kandy

| Class | Fare per Passenger |
|---|---|
| **First Class** | LKR 2,500.00 |
| **Second Class** | LKR 1,200.00 |

*Applies to: Podi Menike (1005 / 1010), Udarata Menike (1015), Intercity Express (1020)*

---

## Main Line — Colombo Fort ↔ Badulla

| Class | Fare per Passenger |
|---|---|
| **First Class** | LKR 4,000.00 |
| **Second Class** | LKR 2,000.00 |

*Applies to: Podi Menike (1005), Udarata Menike (1015)*

---

## Main Line — Kandy ↔ Badulla

| Class | Fare per Passenger |
|---|---|
| **First Class** | LKR 2,000.00 |
| **Second Class** | LKR 1,000.00 |

*Intermediate segment on the Hill Country line*

---

## Coastal Line — Colombo Fort ↔ Galle

| Class | Fare per Passenger |
|---|---|
| **First Class** | LKR 1,800.00 |
| **Second Class** | LKR 800.00 |

*Applies to: Sagarika Express (8055)*

---

## Coastal Line — Colombo Fort ↔ Matara

| Class | Fare per Passenger |
|---|---|
| **First Class** | LKR 2,200.00 |
| **Second Class** | LKR 1,000.00 |

*Applies to: Ruhunu Kumari (8054), Dakshina Intercity (8050)*

---

## Northern Line — Colombo Fort ↔ Anuradhapura

| Class | Fare per Passenger |
|---|---|
| **First Class** | LKR 3,000.00 |
| **Second Class** | LKR 1,500.00 |

*Applies to: Rajarata Rejini (4025)*

---

## Northern Line — Colombo Fort ↔ Jaffna

| Class | Fare per Passenger |
|---|---|
| **First Class** | LKR — *(not yet defined)* |
| **Second Class** | LKR — *(not yet defined)* |

*Applies to: Yal Devi (4085), Uttara Devi (4095)*
> Currently the system uses the Anuradhapura fare as a fallback for Jaffna journeys.

---

## Kelani Valley Line — Colombo Fort ↔ Avissawella

| Class | Fare per Passenger |
|---|---|
| **Second Class only** | LKR 500.00 |

*Applies to: Kelani Valley Commuter (2210, 2230) — no First Class carriages*

---

## Fare Calculation Rules

- **Formula:** `Total Fare = Fare Per Passenger × Passenger Count`
- **Maximum passengers per booking:** 10
- **"Colombo Fort" and "Maradana"** are treated as the same origin station by the fare engine
- **Exact decimal arithmetic** is used — no rounding errors
- The fare is locked at booking confirmation and does not change afterwards
- **Concessions:** The online booking system applies no discounts or concession rates. Concession fares (for example senior or student rates) are not available through this assistant.

---

## Seat Classes Available

| Class Name | What it is |
|---|---|
| **First Class** | Reserved, air-conditioned or observation saloon |
| **Second Class** | Reserved seating |

> Third Class / Unreserved travel is not supported for online booking through RailSense AI.
