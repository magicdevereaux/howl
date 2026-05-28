"""
Seed the database with 1000 diverse bot users for Howl.

Usage (from the repo root):
    python -m scripts.seed_demo_users

Idempotent: deletes any existing demo*@howl.app rows before inserting.
No Celery worker or API keys needed — all avatar data is pre-written.

Archetype distribution (weighted):
    responsive   25%   — reliable, engaged texters
    slow_burn    20%   — take their time but are worth it
    flirty       20%   — playful and warm
    intellectual 20%   — substantive, ask real questions
    ghost        10%   — interested at first, then vanish
    desperate     5%   — a little too eager (recognisable red flag)
"""

import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt

from app.db import SessionLocal
from app.models.user import AvatarStatus, User

random.seed(42)

# ---------------------------------------------------------------------------
# Data pools
# ---------------------------------------------------------------------------

_MAN_NAMES = [
    "James", "Noah", "Liam", "Oliver", "Ethan", "Mason", "Lucas", "Logan",
    "Aiden", "Jackson", "Sebastian", "Mateo", "Henry", "Alexander", "Owen",
    "Daniel", "Leo", "Julian", "Ryan", "Nathan", "Theodore", "Isaiah",
    "Elijah", "Gabriel", "Caleb", "Adrian", "Miles", "Ezra", "Marcus",
    "Finn", "Kai", "Remy", "Soren", "Cade", "Dex", "Reid", "Asher",
    "Beckett", "Cole", "Flynn", "Grayson", "Hudson", "Jude", "Knox",
]

_WOMAN_NAMES = [
    "Emma", "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Amelia", "Harper",
    "Evelyn", "Luna", "Chloe", "Penelope", "Layla", "Riley", "Zoey",
    "Nora", "Lily", "Eleanor", "Hannah", "Lillian", "Maya", "Scarlett",
    "Violet", "Aurora", "Savannah", "Audrey", "Brooklyn", "Stella", "Hazel",
    "Elena", "Aria", "Isla", "Willow", "Quinn", "Sage", "Blair", "Brynn",
    "Cora", "Delilah", "Elara", "Faye", "Gemma", "Hadley", "Iris",
]

_NEUTRAL_NAMES = [
    "Avery", "Jordan", "Alex", "Taylor", "Morgan", "Casey", "Riley",
    "Jamie", "Skyler", "Rowan", "Reese", "Blake", "Drew", "Emery",
    "Phoenix", "Shea", "Tatum", "Lennon", "River", "Indigo", "Salem",
    "Haven", "Story", "Wren", "Zion",
]

# Slightly generic / forgettable names for desperate archetype
_DESPERATE_NAMES = [
    "Mike", "John", "Sarah", "Jessica", "Ashley", "Chris", "Dave", "Amy",
    "Kevin", "Brittany", "Brad", "Tiffany", "Chad", "Melissa", "Steve",
]

_LOCATIONS = [
    "New York, NY", "Los Angeles, CA", "Chicago, IL", "Austin, TX",
    "Seattle, WA", "San Francisco, CA", "Denver, CO", "Boston, MA",
    "Portland, OR", "Nashville, TN", "Atlanta, GA", "Miami, FL",
    "Minneapolis, MN", "Phoenix, AZ", "Philadelphia, PA", "Detroit, MI",
    "New Orleans, LA", "Salt Lake City, UT", "Pittsburgh, PA", "Raleigh, NC",
    "Dallas, TX", "Houston, TX", "San Diego, CA", "Oakland, CA", "Brooklyn, NY",
    "Richmond, VA", "Buffalo, NY", "Kansas City, MO", "Indianapolis, IN",
    "Columbus, OH",
]

# Bios for each archetype personality
_BIOS: dict[str, list[str]] = {
    "responsive": [
        "Software engineer by day, trail runner by dawn. I've hiked every major peak in the Sierra Nevada. Strong opinions about coffee brewing methods. Looking for someone who can keep up.",
        "High school English teacher who reads a novel a week. Weekend potlucks, vinyl records, and terrible puns. Come argue about books with me.",
        "Marine biologist studying coral reef resilience. I spend half my life underwater. I DJ on weekends because the ocean is loud and so am I.",
        "I repair vintage motorcycles in a studio apartment surrounded by maps. Independent to a fault but loyal to the people I choose.",
        "Occupational therapist and amateur astronomer. I'm a good listener and a better cook. Ask me about the time I accidentally burned garlic bread for twenty people.",
        "Emergency physician and hobbyist cyclist. Comfortable with controlled chaos. My risotto has been described as life-changing.",
        "Wildlife photographer and former park ranger. I've spent more nights under canvas than under a roof. Looking for someone comfortable with silence.",
        "Pediatric nurse who salsa dances on weekends. I hold premature babies through NICU crises and then go straight to the dance floor. Good under pressure.",
        "UX designer obsessed with how people make decisions. I overthink menus at restaurants and that's a feature, not a bug.",
        "Baker and part-time ceramicist. My hands are always stained with either flour or clay. I host a dinner party every Sunday.",
    ],
    "slow_burn": [
        "PhD candidate in urban sociology, jazz pianist on the side. I think deeply about cities and who gets to belong in them. I ask a lot of questions and mean all of them.",
        "Architect designing affordable housing in cities that need it. I care about space and who gets access to beauty. I draw constantly.",
        "Environmental attorney and competitive rock climber. I spend my weeks defending wilderness and my weekends inside it.",
        "Novelist working on my third book. I write about places I've never been and people I almost became. Looking for someone worth writing about.",
        "Hospice social worker and sourdough baker. I sit with people at the hardest moments and I've learned to find humor everywhere.",
        "Wilderness guide and amateur mycologist. I track animals, forage for chanterelles, and know how to find water in the Sierra Nevada.",
        "Classical violinist who secretly loves metal. The cognitive dissonance is the point. Looking for someone who contains multitudes.",
        "Data scientist who rock climbs competitively. I find elegance in both algorithms and granite faces. Strong opinions, loosely held.",
        "Medical illustrator who paints in my spare time. I exist at the intersection of precision and chaos. It keeps things interesting.",
        "Librarian and amateur mystery novelist. I'm quiet in crowds and very loud in small groups. Strong opinions about narrative structure.",
    ],
    "flirty": [
        "Festival organizer and professional connector. I know everyone not because I network but because I'm genuinely curious about people. I throw great parties.",
        "Multi-instrumentalist who plays in two bands simultaneously and finds the tension between structure and chaos interesting in music and people.",
        "Private chef who spent a year cooking in Tokyo, Oaxaca, and Lyon. Food is how I say I love you. Be warned.",
        "Choreographer and movement coach. I believe everything communicates through the body first. I'm interested in people who are obsessed with something.",
        "Music producer and former competitive swimmer. I hear rhythm in conversation. Need someone who finds me interesting to be around.",
        "Comedy writer and recreational cyclist. I'm funnier in person. Allegedly. My friends disagree on whether that's a compliment.",
        "Travel writer who's been to 47 countries. I still get excited about new neighborhoods. Come explore something with me.",
        "Wedding photographer who cries at every ceremony. I contain multitudes. Also I make an incredible grilled cheese.",
        "Interior designer with terrible taste in reality TV. I will absolutely judge your bookshelf but I'll be charming about it.",
        "Sommelier at a restaurant I pretend is too fancy for me. I know a lot about wine and nothing about being chill.",
    ],
    "intellectual": [
        "Surgeon who does triathlons and throws pottery. I operate at intensity in most things I do. I'm working on the balance. Works in progress welcome.",
        "Venture capitalist who grew up on a small farm and hasn't reconciled those two lives. I build companies during the week and raise chickens on weekends.",
        "Human rights lawyer and competitive fencer. I spend my days arguing for people who can't, and my evenings trying to get stabbed with a sword.",
        "Deep-sea diver and underwater cinematographer. I film parts of the ocean no one has named yet. Allergic to small talk.",
        "Linguist studying how languages die. It sounds morbid but it's actually about what survives. I'm interested in what endures.",
        "Bioethicist who used to be a paramedic. I've seen the full arc of what it means to be alive. Looking for someone who wants to talk about it.",
        "Climate scientist who runs ultramarathons. I study slow disasters and I outrun them on weekends. Neither is a metaphor.",
        "Archaeologist specializing in medieval textiles. I've learned more about people from fabric than from bones. Ask me why.",
        "Philosopher working at a tech company. The cognitive dissonance is productive. I'm interested in how we decide what matters.",
        "Anthropologist studying remote island communities. Six months a year off the grid, six months in a city. Both feel right.",
    ],
    "ghost": [
        "Just figuring things out. Outdoors, good food, good conversation. Not sure what else to say here.",
        "Introvert who cleans up okay. I like hiking and cooking. I'm told I'm funny once you get to know me.",
        "Into music, travel, and being outside. Ask me anything.",
        "I work in tech. I like being outdoors on weekends. Looking for something real.",
        "Nurse. I care a lot about the people in my life. Looking for someone genuine.",
        "Runner, reader, overthinker. Looking to connect with someone interesting.",
        "Quiet most of the time. Loud when it matters. I have strong opinions about breakfast.",
        "I make good coffee and listen well. That's the pitch.",
        "Works with my hands. Values honesty. Not great at bios.",
        "Teacher. Dog person. Pretty normal. Looking for the same.",
    ],
    "desperate": [
        "I'll be honest, I've been hurt a lot but I'm ready to give love another chance with the right person. I promise I won't take you for granted.",
        "Looking for my other half. I know that sounds cheesy but I genuinely believe in soulmates and I know you're out there. Let's meet.",
        "I'm honestly the most loyal person you'll ever meet. Anyone who gives me a chance will not regret it. I just need someone to see that.",
        "Not here to waste time. I want something real and I'm ready for it right now. If you're serious too, message me.",
        "Just tired of being alone honestly. I have so much love to give and no one to give it to. That sounds sad but I'm a really fun person I promise.",
        "I'll treat you like you deserve to be treated. My ex didn't appreciate that. Their loss. Ready to spoil someone who actually wants it.",
        "Everyone tells me I'm too much but I think the right person will appreciate that. Still looking for them. Maybe it's you?",
        "I don't play games. I know what I want. I want a real connection with someone who won't run away from something good.",
    ],
}

_SPIRIT_ANIMALS = [
    {"animal": "wolf", "personality_traits": ["loyal", "independent", "nocturnal", "strategic"], "avatar_description": "A silver wolf-human hybrid with piercing amber eyes. Moves through the world at its own pace."},
    {"animal": "fox", "personality_traits": ["clever", "adaptable", "curious", "witty"], "avatar_description": "A rust-furred fox-human hybrid with sharp green eyes. Always mid-thought, always three steps ahead."},
    {"animal": "bear", "personality_traits": ["nurturing", "patient", "grounded", "protective"], "avatar_description": "A broad-shouldered bear-human hybrid with warm brown eyes. Radiates quiet reliability."},
    {"animal": "owl", "personality_traits": ["intellectual", "observant", "wise", "nocturnal"], "avatar_description": "A tawny owl-human hybrid with wide knowing eyes. Absorbs everything before offering exactly the insight you needed."},
    {"animal": "otter", "personality_traits": ["playful", "inventive", "social", "spontaneous"], "avatar_description": "A bright-eyed otter-human hybrid. Perpetually delighted by the world."},
    {"animal": "eagle", "personality_traits": ["visionary", "principled", "fearless", "independent"], "avatar_description": "A sharp-eyed eagle-human hybrid with broad wings folded like a lawyer's brief. Sees further than most."},
    {"animal": "lion", "personality_traits": ["confident", "generous", "charismatic", "bold"], "avatar_description": "A golden lion-human hybrid with a commanding presence. Fills a room without trying."},
    {"animal": "deer", "personality_traits": ["gentle", "intuitive", "empathetic", "perceptive"], "avatar_description": "A graceful deer-human hybrid with soft eyes that miss nothing. Moves through chaos with unexpected calm."},
    {"animal": "panther", "personality_traits": ["intense", "focused", "disciplined", "mysterious"], "avatar_description": "A sleek panther-human hybrid with luminous gold eyes. Every movement is deliberate."},
    {"animal": "dolphin", "personality_traits": ["joyful", "intelligent", "communicative", "playful"], "avatar_description": "A streamlined dolphin-human hybrid with bright curious eyes and an infectious laugh."},
    {"animal": "hawk", "personality_traits": ["sharp", "strategic", "perceptive", "decisive"], "avatar_description": "A keen-eyed hawk-human hybrid. Sees patterns others miss and acts on them without hesitation."},
    {"animal": "crow", "personality_traits": ["intelligent", "adaptable", "witty", "resourceful"], "avatar_description": "A blue-black crow-human hybrid with bright inquisitive eyes. Collects ideas like shiny objects."},
    {"animal": "cat", "personality_traits": ["independent", "curious", "graceful", "selective"], "avatar_description": "A sleek cat-human hybrid with sea-glass green eyes and absolute self-possession."},
    {"animal": "elephant", "personality_traits": ["wise", "compassionate", "loyal", "patient"], "avatar_description": "A silver-grey elephant-human hybrid with deep knowing eyes. Carries the weight of memory with grace."},
    {"animal": "tiger", "personality_traits": ["passionate", "determined", "bold", "intense"], "avatar_description": "A golden-striped tiger-human hybrid with blazing amber eyes and coiled energy."},
    {"animal": "salmon", "personality_traits": ["resilient", "purposeful", "determined", "instinctive"], "avatar_description": "A shimmering salmon-human hybrid with focused eyes and an upstream bearing. Has been through fire."},
    {"animal": "coyote", "personality_traits": ["clever", "humorous", "adaptable", "unconventional"], "avatar_description": "A tawny coyote-human hybrid with a crooked smile. Thrives in the margins between expected and possible."},
    {"animal": "hummingbird", "personality_traits": ["vibrant", "energetic", "creative", "passionate"], "avatar_description": "An iridescent hummingbird-human hybrid with impossibly quick hands. Lives at full speed."},
    {"animal": "raven", "personality_traits": ["intellectual", "mysterious", "creative", "perceptive"], "avatar_description": "A glossy raven-human hybrid with deep violet eyes. Speaks rarely but says something worth hearing."},
    {"animal": "lynx", "personality_traits": ["independent", "perceptive", "quiet", "loyal"], "avatar_description": "A silver-tufted lynx-human hybrid with pale grey eyes. Solitary by nature, fiercely devoted by choice."},
]

_GENDERS = (
    ["man"] * 38 + ["woman"] * 38 + ["non-binary"] * 16 + ["other"] * 8
)

_SEXUALITIES_BY_GENDER: dict[str, list[str]] = {
    "man":       ["straight"] * 18 + ["gay"] * 8 + ["bisexual"] * 6 + ["pansexual"] * 4 + ["other"] * 2,
    "woman":     ["straight"] * 16 + ["lesbian"] * 8 + ["bisexual"] * 8 + ["pansexual"] * 4 + ["other"] * 2,
    "non-binary": ["bisexual"] * 5 + ["pansexual"] * 5 + ["other"] * 4 + ["gay"] * 2,
    "other":     ["pansexual"] * 3 + ["bisexual"] * 2 + ["other"] * 3,
}

_LOOKING_FOR_BY_GENDER_SEXUALITY: dict[tuple, str] = {
    ("man", "straight"):    "women",
    ("man", "gay"):         "men",
    ("man", "bisexual"):    "everyone",
    ("man", "pansexual"):   "everyone",
    ("woman", "straight"):  "men",
    ("woman", "lesbian"):   "women",
    ("woman", "bisexual"):  "everyone",
    ("woman", "pansexual"): "everyone",
}

# Archetype weights: 1000 users
_ARCHETYPE_SLOTS = (
    ["responsive"]   * 250 +
    ["slow_burn"]    * 200 +
    ["flirty"]       * 200 +
    ["intellectual"] * 200 +
    ["ghost"]        * 100 +
    ["desperate"]    * 50
)

_DEMO_PASSWORD_HASH = bcrypt.hashpw(b"howl-demo-placeholder", bcrypt.gensalt()).decode()


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

def _pick_name(gender: str, archetype: str, idx: int) -> str:
    if archetype == "desperate":
        return _DESPERATE_NAMES[idx % len(_DESPERATE_NAMES)]
    if gender == "man":
        return _MAN_NAMES[idx % len(_MAN_NAMES)]
    if gender == "woman":
        return _WOMAN_NAMES[idx % len(_WOMAN_NAMES)]
    return _NEUTRAL_NAMES[idx % len(_NEUTRAL_NAMES)]


def _pick_sexuality(gender: str, idx: int) -> str:
    pool = _SEXUALITIES_BY_GENDER.get(gender, ["other"])
    return pool[idx % len(pool)]


def _pick_looking_for(gender: str, sexuality: str) -> str:
    return _LOOKING_FOR_BY_GENDER_SEXUALITY.get((gender, sexuality), "everyone")


def _pick_age(archetype: str) -> int:
    if archetype == "desperate":
        return random.randint(26, 42)   # slightly older range feels more authentic
    return random.choice(
        list(range(18, 23)) * 2 +
        list(range(23, 35)) * 4 +
        list(range(35, 45)) * 3 +
        list(range(45, 55)) * 2 +
        list(range(55, 66)) * 1
    )


def _pick_age_prefs(age: int, idx: int) -> tuple[int | None, int | None]:
    if idx % 5 == 0:
        spread = random.randint(5, 10)
        return max(18, age - spread), min(65, age + spread)
    if idx % 5 == 1:
        return max(18, age - random.randint(5, 15)), None
    return None, None


# ---------------------------------------------------------------------------
# Build 1000-user manifest
# ---------------------------------------------------------------------------

def _build_users() -> list[dict]:
    archetypes = _ARCHETYPE_SLOTS[:]
    random.shuffle(archetypes)

    genders = (_GENDERS * 10)[:1000]
    random.shuffle(genders)

    gender_counters: dict[str, int] = {}
    archetype_counters: dict[str, int] = {}
    users = []

    for i in range(1000):
        archetype = archetypes[i]
        gender    = genders[i]
        g_idx     = gender_counters.get(gender, 0)
        a_idx     = archetype_counters.get(archetype, 0)
        gender_counters[gender] = g_idx + 1
        archetype_counters[archetype] = a_idx + 1

        sexuality   = _pick_sexuality(gender, g_idx)
        looking_for = _pick_looking_for(gender, sexuality)
        age         = _pick_age(archetype)
        age_min, age_max = _pick_age_prefs(age, i)
        name        = _pick_name(gender, archetype, a_idx)
        location    = _LOCATIONS[i % len(_LOCATIONS)]
        bio_pool    = _BIOS[archetype]
        bio         = bio_pool[a_idx % len(bio_pool)]
        spirit      = _SPIRIT_ANIMALS[i % len(_SPIRIT_ANIMALS)]

        users.append({
            "email":              f"demo{i + 1}@howl.app",
            "name":               name,
            "age":                age,
            "gender":             gender,
            "sexuality":          sexuality,
            "looking_for":        looking_for,
            "age_preference_min": age_min,
            "age_preference_max": age_max,
            "location":           location,
            "bio":                bio,
            "archetype":          archetype,
            **spirit,
        })

    return users


DEMO_USERS = _build_users()


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

def seed() -> None:
    db = SessionLocal()
    try:
        deleted = (
            db.query(User)
            .filter(User.email.like("demo%@howl.app"))
            .delete(synchronize_session=False)
        )
        db.commit()
        if deleted:
            print(f"Removed {deleted} existing demo user(s).")

        base_time = datetime.now(timezone.utc) - timedelta(days=30)

        for i, data in enumerate(DEMO_USERS):
            created_at = base_time + timedelta(hours=i * 0.72)  # spread over ~30 days
            user = User(
                email=data["email"],
                password_hash=_DEMO_PASSWORD_HASH,
                name=data["name"],
                age=data["age"],
                gender=data["gender"],
                sexuality=data["sexuality"],
                looking_for=data["looking_for"],
                age_preference_min=data["age_preference_min"],
                age_preference_max=data["age_preference_max"],
                location=data["location"],
                bio=data["bio"],
                animal=data["animal"],
                personality_traits=data["personality_traits"],
                avatar_description=data["avatar_description"],
                avatar_url=None,
                avatar_status=AvatarStatus.ready,
                avatar_status_updated_at=created_at,
                is_bot=True,
                archetype=data["archetype"],
                created_at=created_at,
                updated_at=created_at,
            )
            db.add(user)

        db.commit()

        # Summary
        arch_counts: dict[str, int] = {}
        for u in DEMO_USERS:
            arch_counts[u["archetype"]] = arch_counts.get(u["archetype"], 0) + 1
        ages = [u["age"] for u in DEMO_USERS]

        print(f"Seeded {len(DEMO_USERS)} demo users.")
        print(f"  Archetypes:  {dict(sorted(arch_counts.items()))}")
        print(f"  Age range:   {min(ages)}–{max(ages)}, mean {sum(ages) // len(ages)}")

    except Exception as exc:
        db.rollback()
        print(f"Seed failed: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
