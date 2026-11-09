from enum import Enum


class Status(str, Enum):
    SCRAPED = "scraped"
    CLEANED = "cleaned"
    REJECTED = "rejected"
    ENRICHED = "enriched"
    NO_BUYER = "no_buyer"
    SIGNALLED = "signalled"
    SELECTED = "selected"
    DRAFTED = "drafted"
    SENT = "sent"
    REPLIED = "replied"
    BOOKED = "booked"
    BOUNCED = "bounced"
    SUPPRESSED = "suppressed"
    UNSUBSCRIBED = "unsubscribed"
