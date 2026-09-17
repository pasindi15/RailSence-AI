# DEMO / ACADEMIC RAILWAY POLICY: PASSENGER BOOKING ANOMALY REVIEW
Document ID: POL-SEC-004
Domain: security
Status: ACTIVE (DEMO / ACADEMIC SPECIFICATION)
Version: v1.0
Effective Date: 2026-01-01

## Article 1: High-Velocity Reservation Limits
1.1 (DEMO-SEC-POL-01 §3.1) Any passenger identity submitting more than two (2) reservation requests within a sixty (60) second rolling interval triggers an automated behavioral anomaly review.
1.2 High-frequency booking spikes are held in PENDING_FRAUD_REVIEW status to protect inventory from automated ticket hoarding scripts while preserving legitimate passenger access.
1.3 High-frequency submissions must not be presumed fraudulent; authorized reviewers must verify whether the pattern reflects legitimate group travel or travel agency operations.

## Article 2: Cross-Train Overlapping Journey Conflicts
2.1 (DEMO-SEC-POL-02 §4.2) A passenger identity associated with concurrent or overlapping departure and arrival intervals on differing train services requires administrative verification.
2.2 Where physical transit between services is impossible within the scheduled departure and arrival intervals, the reservation is flagged for conflicting journey review.
2.3 Reviewers must confirm whether overlapping bookings were made in error, represent family members traveling on distinct routes, or indicate speculative hoarding.

## Article 3: Cumulative Seat Volume Accumulation
3.1 (DEMO-SEC-POL-03 §2.4) Any single passenger identity accumulating more than six (6) reserved seats across active un-travelled bookings within a twenty-four (24) hour window triggers a volume review.
3.2 Volume thresholds protect peak holiday and weekend express trains from unauthorized commercial reselling.

## Article 4: Grounded Human Adjudication and Uncertainty
4.1 Algorithmic anomaly scores and machine learning indices are strictly advisory signals. No automated system possesses the authority to unilaterally cancel bookings, declare fraud, or refuse service without human administrative review.
4.2 Administrative officers must evaluate behavioral telemetry alongside passenger history, masked identification records, and external circumstances (such as railway service disruptions or holiday travel surges).
4.3 If algorithmic scoring is temporarily unavailable due to a service outage, reservations must not be classified as suspicious; instead, the system records assessment unavailable and proceeds per administrative continuity protocols.
