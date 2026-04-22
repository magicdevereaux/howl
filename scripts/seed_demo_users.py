"""
Seed the database with 10 demo users for Howl.

Usage (from the repo root):
    python -m scripts.seed_demo_users

Idempotent: deletes any existing demo*@howl.app rows before inserting fresh ones.
Avatar data is pre-generated so this script needs no Celery worker or API key.
"""

import sys
import os

# Allow running as `python -m scripts.seed_demo_users` from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

import bcrypt

from app.db import SessionLocal
from app.models.user import AvatarStatus, User


# ---------------------------------------------------------------------------
# Demo user data
# ---------------------------------------------------------------------------

DEMO_USERS = [
    {
        "email": "demo1@howl.app",
        "name": "Jordan",
        "location": "San Francisco, CA",
        "bio": (
            "Software engineer by day, trail runner by dawn. I've hiked every major peak in the "
            "Sierra Nevada and I'm always planning the next one. I cook elaborate dinners for "
            "friends and believe a good meal is the best reason to gather. Looking for someone "
            "who doesn't mind starting weekends at 5am."
        ),
        "animal": "fox",
        "personality_traits": ["curious", "driven", "outdoorsy", "creative"],
        "avatar_description": (
            "A lithe fox-human hybrid with rust-red fur and sharp green eyes, wearing trail "
            "running gear. Moves with quick, deliberate energy—always scanning the horizon "
            "for the next adventure."
        ),
    },
    {
        "email": "demo2@howl.app",
        "name": "Maya",
        "location": "Austin, TX",
        "bio": (
            "Muralist and printmaker currently working on a series about vanishing ecosystems. "
            "I spend my mornings in the studio and my evenings at live music shows—Austin is "
            "heaven for both. I've lived in four countries and somehow always end up somewhere "
            "with great street food. Fluent in sarcasm and two actual languages."
        ),
        "animal": "wolf",
        "personality_traits": ["passionate", "wanderlust", "artistic", "witty"],
        "avatar_description": (
            "A silver-grey wolf-human hybrid with paint-stained hands and warm amber eyes. "
            "Wears layers of color like armor—always mid-thought, mid-stroke, mid-song."
        ),
    },
    {
        "email": "demo3@howl.app",
        "name": "Sam",
        "location": "New York, NY",
        "bio": (
            "PhD candidate in urban sociology, jazz pianist on the side. I think deeply about "
            "cities, space, and who gets to belong where. My idea of a perfect Saturday is "
            "a long walk through a neighborhood I don't know yet followed by a late-night "
            "session at a small venue. I ask a lot of questions and I mean it."
        ),
        "animal": "owl",
        "personality_traits": ["intellectual", "empathetic", "observant", "musical"],
        "avatar_description": (
            "A tawny owl-human hybrid with wide, knowing eyes behind wire-rimmed glasses. "
            "Perches at the edge of conversations, absorbing everything before offering "
            "exactly the insight you needed."
        ),
    },
    {
        "email": "demo4@howl.app",
        "name": "Riley",
        "location": "Seattle, WA",
        "bio": (
            "National park ranger turned wilderness guide. I've spent more nights under canvas "
            "than under a roof in the last three years and I wouldn't change a thing. I make "
            "sourdough, ferment hot sauce, and can navigate by stars. Looking for someone "
            "comfortable with mud and comfortable with silence."
        ),
        "animal": "bear",
        "personality_traits": ["grounded", "patient", "self-sufficient", "warm"],
        "avatar_description": (
            "A broad-shouldered bear-human hybrid with dark fur and kind, steady brown eyes. "
            "Hands built for work, voice built for campfire stories. Radiates quiet reliability."
        ),
    },
    {
        "email": "demo5@howl.app",
        "name": "Alex",
        "location": "Los Angeles, CA",
        "bio": (
            "Choreographer and movement coach. I believe everything communicates through the "
            "body before the mouth gets a chance. I train six days a week and teach on the "
            "seventh, which is technically rest. I'm drawn to people who are deeply interested "
            "in something—anything—and unashamed about it."
        ),
        "animal": "panther",
        "personality_traits": ["intense", "disciplined", "expressive", "perceptive"],
        "avatar_description": (
            "A sleek panther-human hybrid with midnight-black fur and luminous gold eyes. "
            "Every movement is deliberate—fluid and powerful, like they're always listening "
            "to music no one else can hear."
        ),
    },
    {
        "email": "demo6@howl.app",
        "name": "Casey",
        "location": "Boston, MA",
        "bio": (
            "Emergency medicine resident, marathon runner, amateur ceramicist. Sleep is "
            "theoretical but coffee is real. I find beauty in how systems work under pressure—"
            "hospitals, bodies, long races. I'm looking for someone who takes their own "
            "interests seriously and lets me do the same."
        ),
        "animal": "deer",
        "personality_traits": ["resilient", "focused", "gentle", "precise"],
        "avatar_description": (
            "A graceful deer-human hybrid with soft brown eyes that miss nothing. Moves "
            "through chaos with surprising calm—antlers catch the light like a crown earned "
            "rather than given."
        ),
    },
    {
        "email": "demo7@howl.app",
        "name": "Morgan",
        "location": "Chicago, IL",
        "bio": (
            "Private chef and food writer obsessed with the intersection of culture and "
            "cuisine. I've cooked in Oaxaca, Tokyo, and a Michelin-starred kitchen in Lyon. "
            "I host a dinner party every month with a rotating cast of strangers who always "
            "leave as friends. Food is how I say I love you."
        ),
        "animal": "lion",
        "personality_traits": ["bold", "generous", "ambitious", "charismatic"],
        "avatar_description": (
            "A golden lion-human hybrid with a magnificent mane and warm, commanding eyes. "
            "Fills a room with presence the moment they enter—equally at home at a street "
            "cart or a tasting menu."
        ),
    },
    {
        "email": "demo8@howl.app",
        "name": "Quinn",
        "location": "Portland, OR",
        "bio": (
            "Multi-instrumentalist, bicycle mechanic, avid reader of extremely niche "
            "non-fiction. I play in two bands simultaneously and somehow that's the most "
            "organized part of my life. I love rainy afternoons, vintage synthesizers, "
            "and conversations that go somewhere unexpected. Very good at parallel parking."
        ),
        "animal": "otter",
        "personality_traits": ["playful", "inventive", "sociable", "spontaneous"],
        "avatar_description": (
            "A bright-eyed otter-human hybrid with quick hands always reaching for something "
            "interesting. Perpetually delighted by the world, carrying a wrench in one pocket "
            "and a dog-eared paperback in the other."
        ),
    },
    {
        "email": "demo9@howl.app",
        "name": "Avery",
        "location": "Denver, CO",
        "bio": (
            "Rock climber, backcountry skier, environmental attorney. I spend my weeks "
            "fighting for wilderness protection and my weekends inside it. I've summited "
            "eleven 14ers and I'm working through the rest. Looking for someone who "
            "understands why the mountains feel necessary, not just scenic."
        ),
        "animal": "eagle",
        "personality_traits": ["principled", "fearless", "independent", "visionary"],
        "avatar_description": (
            "A sharp-eyed eagle-human hybrid with broad wings folded like a lawyer's brief. "
            "Sees further than most, speaks carefully, acts decisively. The kind of presence "
            "that makes hard things feel achievable."
        ),
    },
    {
        "email": "demo10@howl.app",
        "name": "Taylor",
        "location": "Miami, FL",
        "bio": (
            "Marine biologist researching coral reef recovery. I spend half my life underwater "
            "and the other half explaining why that matters. I DJ on weekends because the "
            "ocean is loud and so am I. I believe in sunscreen, second chances, and dancing "
            "until the venue closes. Probably texting you from a boat."
        ),
        "animal": "cat",
        "personality_traits": ["independent", "curious", "vibrant", "adaptable"],
        "avatar_description": (
            "A sleek cat-human hybrid with sea-glass green eyes and sun-bleached fur. "
            "Equally comfortable in the deep ocean and a crowded dance floor—always landing "
            "on their feet, always ready for what's next."
        ),
    },
]

# A bcrypt hash of the string "howl-demo-placeholder" — not intended for real login.
_DEMO_PASSWORD_HASH = bcrypt.hashpw(b"howl-demo-placeholder", bcrypt.gensalt()).decode()


def seed() -> None:
    db = SessionLocal()
    try:
        # Remove existing demo users (idempotency)
        deleted = (
            db.query(User)
            .filter(User.email.like("demo%@howl.app"))
            .delete(synchronize_session=False)
        )
        db.commit()
        if deleted:
            print(f"Removed {deleted} existing demo user(s).")

        now = datetime.now(timezone.utc)

        for data in DEMO_USERS:
            user = User(
                email=data["email"],
                password_hash=_DEMO_PASSWORD_HASH,
                name=data["name"],
                location=data["location"],
                bio=data["bio"],
                animal=data["animal"],
                personality_traits=data["personality_traits"],
                avatar_description=data["avatar_description"],
                avatar_url=None,
                avatar_status=AvatarStatus.ready,
                avatar_status_updated_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(user)

        db.commit()
        print(f"Seeded {len(DEMO_USERS)} demo users successfully.")

    except Exception as exc:
        db.rollback()
        print(f"Seed failed: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
