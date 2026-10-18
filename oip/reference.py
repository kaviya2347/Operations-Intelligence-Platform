"""Reference data: clients, queues, service levels, calendar events, disposition codes.

Client names are fictional. Targets mirror typical contact-centre contracts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

CLIENTS = [
    {"client_id": "C01", "client_code": "NWT", "client_name": "Northwind Telecom", "industry": "Telecom", "contract_tier": "Gold"},
    {"client_id": "C02", "client_code": "HAL", "client_name": "Halcyon Insurance", "industry": "Insurance", "contract_tier": "Silver"},
    {"client_id": "C03", "client_code": "KES", "client_name": "Kestrel Retail", "industry": "E-commerce", "contract_tier": "Gold"},
    {"client_id": "C04", "client_code": "MER", "client_name": "Meridian Bank", "industry": "Banking", "contract_tier": "Platinum"},
]


@dataclass(frozen=True)
class Queue:
    queue_id: str
    code: str
    name: str
    client_id: str
    channel: str              # Voice | Chat | Email | Back office
    open_hour: int            # handling hours (local)
    close_hour: int
    sl_threshold_sec: int     # answer / first response threshold (business seconds for Email & Back office)
    sl_target: float          # contractual service level target
    aht_target_sec: int
    base_daily_volume: float
    base_aht_sec: float
    patience_sec: float = 90.0
    concurrency: int = 1
    abandon_target: float = 0.05
    label_variants: tuple = field(default_factory=tuple)

    @property
    def realtime(self) -> bool:
        return self.channel in ("Voice", "Chat")


QUEUES: list[Queue] = [
    Queue("Q01", "NWT-BILL", "Billing", "C01", "Voice", 8, 22, 20, 0.80, 360, 720, 345, 290,
          label_variants=("NWT-BILL", "NWT Billing", "nwt_billing", "NWT-BILLING ", "Billing (NWT)")),
    Queue("Q02", "NWT-TECH", "Technical Support", "C01", "Voice", 8, 22, 20, 0.80, 540, 470, 515, 320,
          label_variants=("NWT-TECH", "NWT Tech Support", "nwt_tech", "TECH SUPPORT-NWT")),
    Queue("Q03", "HAL-CLM", "Claims", "C02", "Voice", 9, 20, 30, 0.80, 600, 290, 575, 340,
          label_variants=("HAL-CLM", "Halcyon Claims", "hal_claims", "HAL CLM")),
    Queue("Q04", "MER-CARD", "Cards", "C04", "Voice", 8, 22, 20, 0.85, 300, 580, 290, 260, abandon_target=0.04,
          label_variants=("MER-CARD", "Meridian Cards", "mer_cards", "MER CARDS ")),
    Queue("Q05", "NWT-CHAT", "Chat Care", "C01", "Chat", 8, 23, 30, 0.80, 720, 330, 690, 420, concurrency=2,
          label_variants=("NWT-CHAT", "NWT Chat", "nwt_chatcare")),
    Queue("Q06", "KES-ORD", "Orders", "C03", "Chat", 9, 23, 45, 0.80, 600, 380, 600, 440, concurrency=2,
          label_variants=("KES-ORD", "Kestrel Orders", "kes_orders")),
    Queue("Q07", "HAL-POL", "Policy Servicing", "C02", "Email", 9, 21, 4 * 3600, 0.90, 420, 140, 420,
          label_variants=("HAL-POL", "Halcyon Policy Mail", "hal_policy")),
    Queue("Q08", "KES-RET", "Returns", "C03", "Email", 9, 21, 4 * 3600, 0.90, 360, 170, 360,
          label_variants=("KES-RET", "Kestrel Returns", "kes_returns")),
    Queue("Q09", "MER-KYC", "KYC Back Office", "C04", "Back office", 9, 19, 10 * 3600, 0.95, 900, 120, 880,
          label_variants=("MER-KYC", "Meridian KYC", "mer_kyc_bo")),
]
QUEUE_BY_ID = {q.queue_id: q for q in QUEUES}
QUEUE_BY_CODE = {q.code: q for q in QUEUES}

# Public holidays observed by the delivery centre (volume multiplier)
HOLIDAYS = {
    date(2026, 3, 4): ("Holi", 0.62),
    date(2026, 3, 20): ("Eid al-Fitr", 0.80),
    date(2026, 4, 3): ("Good Friday", 0.85),
    date(2026, 4, 14): ("Tamil New Year", 0.74),
    date(2026, 5, 1): ("May Day", 0.80),
}

DOW_FACTOR = [1.17, 1.06, 1.00, 0.98, 0.97, 0.80, 0.62]   # Mon..Sun

# Intraday arrival shape for real-time queues (relative weight per hour, 0..23)
HOURLY_SHAPE = [0.05, 0.03, 0.02, 0.02, 0.03, 0.06, 0.15, 0.40, 0.75, 1.00, 1.18, 1.22, 1.05, 0.92, 0.98,
                1.02, 0.96, 0.90, 1.00, 1.04, 0.86, 0.62, 0.38, 0.18]
# Email/back office arrive around the clock, heavier in business hours
HOURLY_SHAPE_ASYNC = [0.25, 0.18, 0.14, 0.12, 0.14, 0.22, 0.45, 0.70, 0.95, 1.10, 1.15, 1.12, 1.00, 0.98, 1.02,
                      1.00, 0.96, 0.92, 0.85, 0.78, 0.70, 0.58, 0.45, 0.33]

# Planted operational scenarios (what RCA, anomaly detection and forecasting should find)
SCENARIOS = {
    "billing_roster_gap": {
        "queue": "Q01", "start": date(2026, 4, 6),
        "description": "New roster cycle moved the morning shift start to 10:30, leaving 10:00-12:00 and 18:00-19:30 under-scheduled on weekdays.",
        "intervals": {"10:00": 0.66, "10:30": 0.66, "11:00": 0.70, "11:30": 0.74, "18:00": 0.78, "18:30": 0.78, "19:00": 0.80},
    },
    "cards_latency": {
        "queue": "Q04", "start": date(2026, 4, 20), "end": date(2026, 4, 24), "aht_mult": 1.36,
        "description": "Card management system latency inflated handle time by about a third.",
    },
    "kestrel_sale": {
        "queues": ("Q06", "Q08"), "orders": (date(2026, 5, 15), date(2026, 5, 18), 1.62, 1.35),
        "returns": (date(2026, 5, 22), date(2026, 5, 28), 1.45, 1.20),
        "description": "Summer sale: order chats spiked and returns emails followed a week later; WFM forecast under-called the uplift.",
    },
    "chat_release_csat": {
        "queue": "Q05", "start": date(2026, 3, 23), "end": date(2026, 3, 29), "csat_shift": -0.85,
        "description": "Mobile app release broke the bill-download flow; chat CSAT dropped for a week.",
    },
    "billing_cycle": {"queue": "Q01", "days": (1, 2, 3, 4, 5), "mult": 1.22,
                      "description": "Bills are generated on the 1st; billing calls rise for five days."},
}

REASONS = {
    "Q01": ["Bill explanation", "Payment arrangement", "Plan change", "Dispute raised", "Refund request"],
    "Q02": ["No network", "Slow data", "Device setup", "SIM issue", "Outage enquiry"],
    "Q03": ["New claim", "Claim status", "Document submission", "Claim rejection", "Surveyor visit"],
    "Q04": ["Card block", "Transaction dispute", "Limit enquiry", "Card delivery", "Reward points"],
    "Q05": ["Bill download", "Plan enquiry", "Recharge failed", "Roaming", "Account update"],
    "Q06": ["Order status", "Delivery delay", "Cancel order", "Payment failed", "Wrong item"],
    "Q07": ["Endorsement", "Nominee change", "Renewal query", "Policy copy", "Address change"],
    "Q08": ["Return pickup", "Refund status", "Exchange", "Damaged item", "Return rejected"],
    "Q09": ["New account KYC", "Re-KYC", "Address proof", "Signature mismatch", "Document rejected"],
}

# Canonical resolution statuses and the messy labels seen in the CRM export
# Share of contacts that are repeat contacts from the previous seven days (drives FCR)
REPEAT_RATE = {"Q01": 0.105, "Q02": 0.165, "Q03": 0.14, "Q04": 0.085, "Q05": 0.12, "Q06": 0.10, "Q07": 0.085, "Q08": 0.11, "Q09": 0.13}

RESOLUTION_LABELS = {
    "Resolved": ["Resolved", "RESOLVED", "resolved", "RSLVD", "Res.", "Resolved "],
    "Escalated": ["Escalated", "ESCALATED", "Esc", "escalated to L2"],
    "Callback scheduled": ["Callback scheduled", "CB Sched", "callback", "CALLBACK"],
    "Pending customer": ["Pending customer", "Pending - Cust", "PENDING", "awaiting customer"],
}

SHIFTS = {  # name: (start_hour, end_hour)
    "Morning": (8, 16.5),
    "General": (11, 19.5),
    "Evening": (14.5, 23),
}

SITES = ["Chennai", "Coimbatore"]

FIRST_NAMES = ["Arun", "Divya", "Karthik", "Priya", "Vignesh", "Lakshmi", "Suresh", "Anitha", "Ramesh", "Kavya", "Manoj",
               "Deepa", "Prakash", "Revathi", "Sanjay", "Meena", "Gokul", "Swathi", "Harish", "Nandhini", "Ashwin",
               "Keerthana", "Bala", "Janani", "Dinesh", "Pooja", "Naveen", "Sowmya", "Rahul", "Aishwarya", "Vijay",
               "Gayathri", "Ajay", "Sneha", "Mohan", "Bhavani", "Rohit", "Ishwarya", "Sathish", "Hema", "Imran",
               "Fathima", "Joseph", "Mary", "Abdul", "Ayesha", "Ravi", "Uma", "Senthil", "Kalpana"]
LAST_NAMES = ["Kumar", "Raman", "Srinivasan", "Iyer", "Natarajan", "Murugan", "Subramanian", "Krishnan", "Pillai",
              "Venkatesh", "Rajan", "Shankar", "Babu", "Selvam", "Prasad", "Reddy", "Nair", "Menon", "Joseph", "Khan"]
EMAIL_DOMAINS = ["gmail.com", "yahoo.co.in", "outlook.com", "rediffmail.com", "hotmail.com"]
