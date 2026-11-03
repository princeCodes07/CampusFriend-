"""Owner-approved checkout locations and GHS fees; independent of admin zone records."""
from decimal import Decimal


LOCATION_CHOICES = (
    ("campus", "Campus"),
    ("pickup", "Pickup (Palms Eatery)"),
    ("ayeduase", "Ayeduase"),
    ("kotei", "Kotei"),
    ("boadi", "Boadi"),
    ("newsite", "Newsite"),
    ("other", "Other location"),
)
LOCATION_LABELS = dict(LOCATION_CHOICES)
DELIVERY_FEES = {
    "campus": Decimal("0.00"),
    "pickup": Decimal("0.00"),
    "ayeduase": Decimal("10.00"),
    "kotei": Decimal("10.00"),
    "boadi": Decimal("10.00"),
    "newsite": Decimal("10.00"),
    # Zero is the amount collected ONLINE, not a promise of free delivery.
    "other": Decimal("0.00"),
}
