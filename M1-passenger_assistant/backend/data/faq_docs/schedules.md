# Train Schedules — Sri Lanka Railways (SLR) Reference Data

## Main Line — Colombo Fort to Kandy / Badulla

| Train | ID | Departs | Arrives | 1st Class | 2nd Class | Total |
|---|---|---|---|---|---|---|
| **Podi Menike Express** | 1005 | Colombo Fort 05:55 | Badulla 16:35 | 40 seats | 120 seats | 160 |
| **Udarata Menike Express** | 1015 | Colombo Fort 08:30 | Badulla 19:15 | 30 seats | 140 seats | 170 |
| **Intercity Express** | 1020 | Colombo Fort 15:35 | Kandy 18:10 | 40 seats | 120 seats | 160 |
| **Podi Menike (Return)** | 1010 | Kandy 14:35 | Colombo Fort 17:20 | 40 seats | 120 seats | 160 |

**Stops (1005 / 1015):** Colombo Fort → Polgahawela → Peradeniya → Kandy → Nanu Oya → Ella → Badulla

---

## Coastal Line — Colombo Fort to Galle / Matara

| Train | ID | Departs | Arrives | 1st Class | 2nd Class | Total |
|---|---|---|---|---|---|---|
| **Ruhunu Kumari** | 8054 | Colombo Fort 05:50 | Matara 09:10 | 40 seats | 120 seats | 160 |
| **Dakshina Intercity** | 8050 | Colombo Fort 06:50 | Matara 09:05 | 40 seats | 120 seats | 160 |
| **Sagarika Express** | 8055 | Colombo Fort 15:20 | Galle 17:35 | 40 seats | 120 seats | 160 |

**Stops:** Colombo Fort → Panadura → Aluthgama → Hikkaduwa → Galle → Matara

---

## Northern Line — Colombo Fort to Jaffna

| Train | ID | Departs | Arrives | 1st Class | 2nd Class | Total |
|---|---|---|---|---|---|---|
| **Yal Devi Express** | 4085 | Colombo Fort 05:45 | Jaffna 13:20 | 45 seats | 150 seats | 195 |
| **Uttara Devi (Overnight)** | 4095 | Colombo Fort 20:15 | Jaffna 04:10+1 | 40 seats | 120 seats | 160 |

**Stops:** Colombo Fort → Kurunegala → Anuradhapura → Vavuniya → Jaffna

---

## Northern Line — to Anuradhapura

| Train | ID | Departs | Arrives | 1st Class | 2nd Class | Total |
|---|---|---|---|---|---|---|
| **Rajarata Rejini** | 4025 | Colombo Fort 06:35 | Anuradhapura 10:50 | 40 seats | 120 seats | 160 |
| **Rajarata Rejina** | 8056 | Vavuniya 03:45 | Matara 13:10 | 30 seats | 150 seats | 180 |

---

## Kelani Valley Line — Colombo Fort to Avissawella

| Train | ID | Departs | Arrives | 1st Class | 2nd Class | Total |
|---|---|---|---|---|---|---|
| **Kelani Valley Commuter** | 2210 | Colombo Fort 06:10 | Avissawella 07:40 | — | 120 seats | 120 |
| **Kelani Valley Commuter** | 2230 | Colombo Fort 17:05 | Avissawella 18:35 | — | 120 seats | 120 |

> Kelani Valley commuter trains are 2nd Class only — no First Class carriages.

---

## How Seat Availability Works (Booking System)

The RailSense booking system tracks seats **dynamically in real time**:

### When a booking is CONFIRMED ✅
- The passenger count is subtracted from the available seats for that train, date, and class.
- Formula: `Available = Schedule_Capacity − SUM(confirmed_passenger_counts)`
- Active seat holds (5-minute locks) also reduce availability temporarily.

### When a booking is CANCELLED ❌
- The system does **NOT delete** the booking record — it changes the status to `CANCELLED`.
- `CANCELLED` bookings are excluded from the seat count formula automatically.
- The seats are **immediately restored** to available — other passengers can book them.

### Double-booking protection 🔒
- The database uses a **row-level lock** (`SELECT FOR UPDATE`) on the schedule row during each booking.
- A final seat-count check runs inside the locked transaction before confirming.
- This prevents two passengers from simultaneously taking the last seat.

---

## Notes

- Times shown are scheduled departures/arrivals under normal operating
  conditions. Actual departures may vary due to signal delays, weather,
  or track maintenance — this is exactly what the `delay_check` intent
  and the Operations Agent's live prediction cover.
- Train numbers follow the SLR numbering convention.
- IDs like `IC-XXXX`, `EXP-OVERLAP`, or `ND-XXXX` are internal
  test/historical identifiers — they are NOT real passenger services.
