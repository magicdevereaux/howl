"""
Seed the database with 100 diverse demo users for Howl.

Usage (from the repo root):
    python -m scripts.seed_demo_users

Idempotent: deletes any existing demo*@howl.app rows before inserting fresh ones.
Avatar data is pre-generated — no Celery worker or API key needed.

Distribution:
  Gender:     ~38 men, ~38 women, ~16 non-binary, ~8 other
  Age:        18-65, weighted toward 22-45
  Sexuality:  straight, gay, lesbian, bisexual, pansexual, other
  Looking for: men, women, non-binary, everyone
  Age prefs:  set for ~40% of users, null for the rest
"""

import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt

from app.db import SessionLocal
from app.models.user import AvatarStatus, User

random.seed(42)  # reproducible demo data

# ---------------------------------------------------------------------------
# Data pools
# ---------------------------------------------------------------------------

_MAN_NAMES = [
    "James", "Noah", "Liam", "Oliver", "Ethan", "Mason", "Lucas", "Logan",
    "Aiden", "Jackson", "Sebastian", "Mateo", "Henry", "Alexander", "Owen",
    "Daniel", "Leo", "Julian", "Ryan", "Nathan", "Theodore", "Isaiah",
    "Elijah", "Gabriel", "Caleb", "Adrian", "Miles", "Ezra", "Marcus",
    "Finn", "Kai", "Remy", "Soren", "Cade", "Dex",
]

_WOMAN_NAMES = [
    "Emma", "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Amelia", "Harper",
    "Evelyn", "Luna", "Chloe", "Penelope", "Layla", "Riley", "Zoey",
    "Nora", "Lily", "Eleanor", "Hannah", "Lillian", "Maya", "Scarlett",
    "Violet", "Aurora", "Savannah", "Audrey", "Brooklyn", "Stella", "Hazel",
    "Elena", "Aria", "Isla", "Willow", "Quinn", "Sage",
]

_NEUTRAL_NAMES = [
    "Avery", "Jordan", "Alex", "Taylor", "Morgan", "Casey", "Riley",
    "Jamie", "Skyler", "Rowan", "Reese", "Blake", "Drew", "Emery",
    "Phoenix", "Shea", "Tatum", "Lennon", "River", "Indigo",
]

_LOCATIONS = [
    "New York, NY", "Los Angeles, CA", "Chicago, IL", "Austin, TX",
    "Seattle, WA", "San Francisco, CA", "Denver, CO", "Boston, MA",
    "Portland, OR", "Nashville, TN", "Atlanta, GA", "Miami, FL",
    "Minneapolis, MN", "Phoenix, AZ", "Philadelphia, PA", "Detroit, MI",
    "New Orleans, LA", "Salt Lake City, UT", "Pittsburgh, PA", "Raleigh, NC",
    "Dallas, TX", "Houston, TX", "San Diego, CA", "Oakland, CA", "Brooklyn, NY",
]

# 30 bios spanning personality archetypes → produce varied spirit animals
_BIOS = [
    # Lone wolves / independent types
    "Software engineer by day, ultramarathon runner by dawn. I've completed seven 100-mile races and I'm addicted to the solitude of mountain trails. I cook elaborate vegetarian meals, read philosophy, and believe the best conversations happen at 2am or mile 80. Looking for someone who doesn't flinch at discomfort.",
    "National park ranger, wilderness guide, and amateur mycologist. I spend more nights under the stars than under a roof. I track animals, forage for chanterelles, and know how to find water anywhere in the Sierra Nevada. Quiet mornings matter to me. So does leaving things better than I found them.",
    "I repair vintage motorcycles in a studio apartment surrounded by maps of places I've ridden to. I'm independent to a fault, curious about everything mechanical and philosophical, and deeply loyal to the small circle of people I trust. Black coffee, long silences, and honest conversations.",
    # Creative types
    "Muralist and printmaker obsessed with the intersection of ecology and art. I've painted buildings across four continents and I still get excited by a blank wall. My studio smells like linseed oil and strong espresso. I believe art should make people uncomfortable in useful ways.",
    "Novelist working on my third book, jazz pianist on the weekends. I write about places I've never been and people I almost became. I think deeply about language, structure, and the gap between what we mean and what we say. Looking for someone worth writing about.",
    "Choreographer and movement coach. I believe everything communicates through the body before the mouth gets a chance. I train six days a week and I'm very interested in people who are obsessed with something — anything — and unashamed about it.",
    "Ceramic artist and part-time ceramics teacher. I'm drawn to imperfection, to things that show their process. My hands are always stained with clay. I host a small dinner every Sunday and I'm an extremely competitive board game player.",
    "Multi-instrumentalist who plays in two bands simultaneously. Folk-punk and ambient electronic — yes, both. I love the tension between structure and chaos in music and in people. I read obscure 20th-century poetry and fix bikes in my spare time.",
    # Intellectual / analytical types
    "PhD candidate in urban sociology, jazz pianist on the side. I think deeply about cities, who belongs in them, and who gets pushed out. My idea of a Saturday is a long walk through a neighborhood I don't know followed by a late dinner somewhere loud. I ask too many questions and mean all of them.",
    "Marine biologist studying coral reef resilience. I'm underwater half my life and the other half writing grants and advocating for ocean policy. I DJ on weekends because the ocean is loud and so am I. Fluent in two languages, working on a third, probably texting you from a boat.",
    "Emergency physician and amateur astronomer. I'm comfortable with uncertainty and controlled chaos. I spend my nights off looking at galaxies through a telescope in my backyard. I'm calm in a crisis, animated at a dinner table, and I make a very good risotto.",
    "Data scientist by week, competitive rock climber by weekend. I find elegance in algorithms and in granite faces. I'm analytical but not cold — I just process the world differently. Strong opinions, loosely held. I like people who can change my mind.",
    "Environmental attorney fighting for wilderness protection. I spend my weeks in courtrooms and my weekends in the mountains I'm defending. Principled to a fault. I hike fast, argue carefully, and am extremely good at losing gracefully.",
    # Social / community types
    "Private chef and food writer who spent a year cooking in Oaxaca, Tokyo, and Lyon. I host a dinner party every month with rotating strangers who always leave as friends. Food is how I say I love you, so be warned.",
    "Community organizer and high school debate coach. I spend my days building power in communities that have been overlooked, and my evenings teaching teenagers to argue with evidence. Loud at restaurants, thoughtful at 1am, always making plans.",
    "Festival organizer and professional connector. I know everyone — not because I network, but because I'm genuinely curious about people. I throw the best parties. I'm also surprisingly introverted after 10pm.",
    "Pediatric nurse and competitive salsa dancer. I've held premature babies through NICU crises and then gone straight to a dance floor. I'm good under pressure and I have very good rhythm. Looking for someone who can keep up on both counts.",
    # Adventurous types
    "Wilderness photographer and former wildfire smoke jumper. I've spent most of my career in places most people see only in documentaries. I don't own much, but I know how to fix things, navigate without cell service, and find beauty in the unglamorous.",
    "Rock climber, backcountry skier, and environmental scientist. I need to be outside to think clearly. I've stood on the summit of eleven 14ers and I'm working through the rest. I want someone who finds the mountains necessary, not just scenic.",
    "Deep-sea diver and underwater cinematographer. I film the parts of the ocean no one has named yet. I'm comfortable with the unknown, allergic to small talk, and I make extremely good soup.",
    "Long-haul cyclist — I've ridden coast-to-coast twice. I move slowly through the world and notice things most people miss at highway speed. I fix everything myself, read everything I can carry, and believe the best life happens at twelve miles an hour.",
    # Nurturing / quiet types
    "High school English teacher and weekend urban farmer. I grow tomatoes, teach poetry, and believe both require the same kind of attention. My students write letters to their future selves. I still have every one of mine.",
    "Occupational therapist working with adults recovering from strokes. Patience is not a virtue I practice — it's a skill I've built. I'm a good listener, a better cook, and someone who finds deep meaning in small improvements.",
    "Librarian by day, amateur astronomer and mystery novelist by night. I'm quiet in crowds and very loud in small groups. I have strong opinions about narrative structure and which cheeses deserve to be on a board.",
    "Hospice social worker and avid bread baker. I sit with people at the hardest moments of their lives and I've learned to find humor and beauty everywhere. I make sourdough, grow herbs, and read everything by Marilynne Robinson.",
    # Professional / driven types
    "Architect designing affordable housing in cities that desperately need it. I care intensely about how space shapes behavior and who gets access to beauty. I draw constantly, argue about cities, and I'm a surprisingly good amateur pastry chef.",
    "Surgeon who spends weekends training for triathlons and learning to throw pottery. I operate at intensity in most things I do, which can be a lot — I know this. I'm working on the balance. I like people who are similarly works-in-progress.",
    "Venture capitalist who grew up on a small farm and hasn't quite reconciled those two lives. I build companies during the week and raise chickens on weekends. I think a lot about what we're optimizing for and whether it's right.",
    "Human rights lawyer and competitive fencer. I spend my days arguing for people who can't argue for themselves and my evenings trying to get stabbed with a sword. Extremely direct. Very bad at small talk. Excellent at big talk.",
    "Music producer and former competitive swimmer. I hear everything — rhythm in conversation, melody in architecture. I'm in the studio until 3am most nights and at the pool by 6am. I need someone who is interesting to me, which is harder to find than it sounds.",
]

# 20 pre-generated spirit animal profiles
_SPIRIT_ANIMALS = [
    {
        "animal": "wolf",
        "personality_traits": ["loyal", "independent", "nocturnal", "strategic"],
        "avatar_description": "A silver wolf-human hybrid with piercing amber eyes and paint-stained hands. Moves through the world at its own pace, always scanning the horizon.",
    },
    {
        "animal": "fox",
        "personality_traits": ["clever", "adaptable", "curious", "witty"],
        "avatar_description": "A rust-furred fox-human hybrid with sharp green eyes and an ever-shifting expression. Always mid-thought, always three steps ahead.",
    },
    {
        "animal": "bear",
        "personality_traits": ["nurturing", "patient", "grounded", "protective"],
        "avatar_description": "A broad-shouldered bear-human hybrid with warm brown eyes and hands built for work. Radiates quiet reliability and unexpected gentleness.",
    },
    {
        "animal": "owl",
        "personality_traits": ["intellectual", "observant", "wise", "nocturnal"],
        "avatar_description": "A tawny owl-human hybrid with wide knowing eyes behind wire-rimmed glasses. Perches at the edges of conversations, absorbing everything.",
    },
    {
        "animal": "otter",
        "personality_traits": ["playful", "inventive", "social", "spontaneous"],
        "avatar_description": "A bright-eyed otter-human hybrid with quick hands always reaching for something interesting. Perpetually delighted by the world.",
    },
    {
        "animal": "eagle",
        "personality_traits": ["visionary", "principled", "fearless", "independent"],
        "avatar_description": "A sharp-eyed eagle-human hybrid with broad wings folded like a lawyer's brief. Sees further than most and speaks only when it matters.",
    },
    {
        "animal": "lion",
        "personality_traits": ["confident", "generous", "charismatic", "bold"],
        "avatar_description": "A golden lion-human hybrid with a commanding presence and warm, searching eyes. Fills a room without trying.",
    },
    {
        "animal": "deer",
        "personality_traits": ["gentle", "intuitive", "empathetic", "perceptive"],
        "avatar_description": "A graceful deer-human hybrid with soft eyes that miss nothing. Moves through chaos with unexpected calm.",
    },
    {
        "animal": "panther",
        "personality_traits": ["intense", "focused", "disciplined", "mysterious"],
        "avatar_description": "A sleek panther-human hybrid with luminous gold eyes. Every movement is deliberate — fluid and powerful.",
    },
    {
        "animal": "dolphin",
        "personality_traits": ["joyful", "intelligent", "communicative", "playful"],
        "avatar_description": "A streamlined dolphin-human hybrid with bright curious eyes and an infectious laugh. Equally at home in deep water or a crowded dance floor.",
    },
    {
        "animal": "hawk",
        "personality_traits": ["sharp", "strategic", "perceptive", "decisive"],
        "avatar_description": "A keen-eyed hawk-human hybrid with taloned hands and a direct gaze. Sees patterns others miss and acts on them without hesitation.",
    },
    {
        "animal": "crow",
        "personality_traits": ["intelligent", "adaptable", "witty", "resourceful"],
        "avatar_description": "A blue-black crow-human hybrid with bright inquisitive eyes. Collects ideas the way other birds collect shiny objects.",
    },
    {
        "animal": "cat",
        "personality_traits": ["independent", "curious", "graceful", "selective"],
        "avatar_description": "A sleek cat-human hybrid with sea-glass green eyes and an air of absolute self-possession. Chooses carefully who they let in.",
    },
    {
        "animal": "elephant",
        "personality_traits": ["wise", "compassionate", "loyal", "patient"],
        "avatar_description": "A silver-grey elephant-human hybrid with deep knowing eyes. Carries the weight of memory with grace and shares it generously.",
    },
    {
        "animal": "tiger",
        "personality_traits": ["passionate", "determined", "bold", "intense"],
        "avatar_description": "A golden-striped tiger-human hybrid with blazing amber eyes and coiled energy. Fully present in everything they do.",
    },
    {
        "animal": "salmon",
        "personality_traits": ["resilient", "purposeful", "determined", "instinctive"],
        "avatar_description": "A shimmering salmon-human hybrid with focused eyes and an upstream bearing. Has been through fire and is stronger for it.",
    },
    {
        "animal": "coyote",
        "personality_traits": ["clever", "humorous", "adaptable", "unconventional"],
        "avatar_description": "A tawny coyote-human hybrid with a crooked smile and bright mischievous eyes. Thrives in the margins between what's expected and what's possible.",
    },
    {
        "animal": "hummingbird",
        "personality_traits": ["vibrant", "energetic", "creative", "passionate"],
        "avatar_description": "An iridescent hummingbird-human hybrid with impossibly quick hands and a warm glow. Lives at full speed and makes everything around them brighter.",
    },
    {
        "animal": "raven",
        "personality_traits": ["intellectual", "mysterious", "creative", "perceptive"],
        "avatar_description": "A glossy raven-human hybrid with deep violet eyes that catch the light. Speaks rarely but says something worth hearing every time.",
    },
    {
        "animal": "lynx",
        "personality_traits": ["independent", "perceptive", "quiet", "loyal"],
        "avatar_description": "A silver-tufted lynx-human hybrid with pale grey eyes that see in any light. Solitary by nature, fiercely devoted by choice.",
    },
]

# ---------------------------------------------------------------------------
# Demographic plan — 100 slots with full coverage of filter combinations
# ---------------------------------------------------------------------------

# Gender distribution: 38 men, 38 women, 16 non-binary, 8 other
_GENDERS = (
    ["man"] * 38
    + ["woman"] * 38
    + ["non-binary"] * 16
    + ["other"] * 8
)
random.shuffle(_GENDERS)

# Sexuality distribution
_SEXUALITIES_BY_GENDER = {
    "man": (
        ["straight"] * 18 + ["gay"] * 8 + ["bisexual"] * 6
        + ["pansexual"] * 4 + ["other"] * 2
    ),
    "woman": (
        ["straight"] * 16 + ["lesbian"] * 8 + ["bisexual"] * 8
        + ["pansexual"] * 4 + ["other"] * 2
    ),
    "non-binary": (
        ["bisexual"] * 5 + ["pansexual"] * 5 + ["other"] * 3
        + ["gay"] * 2 + ["straight"] * 1
    ),
    "other": (
        ["pansexual"] * 3 + ["bisexual"] * 2 + ["other"] * 2
        + ["straight"] * 1
    ),
}

# looking_for — broadly correlated with gender/sexuality but with intentional variance
_LOOKING_FOR_OPTIONS = ["men", "women", "non-binary", "everyone"]

# Age weights — realistic skew toward 22-38
_AGE_POOL = (
    list(range(18, 23)) * 2    # 18-22: 10 slots
    + list(range(23, 35)) * 4  # 23-34: 48 slots
    + list(range(35, 45)) * 3  # 35-44: 30 slots
    + list(range(45, 55)) * 2  # 45-54: 20 slots
    + list(range(55, 66)) * 1  # 55-65: 11 slots
)
random.shuffle(_AGE_POOL)


def _pick_name(gender: str, idx: int) -> str:
    if gender == "man":
        return _MAN_NAMES[idx % len(_MAN_NAMES)]
    if gender == "woman":
        return _WOMAN_NAMES[idx % len(_WOMAN_NAMES)]
    return _NEUTRAL_NAMES[idx % len(_NEUTRAL_NAMES)]


def _pick_sexuality(gender: str, idx: int) -> str:
    pool = _SEXUALITIES_BY_GENDER.get(gender, ["other"])
    return pool[idx % len(pool)]


def _pick_looking_for(gender: str, sexuality: str, g_idx: int) -> str:
    """Broadly correlated with gender/sexuality; uses g_idx for deterministic coverage."""
    # Hard-code coverage of all four looking_for values by reserving slots
    if gender == "non-binary":
        # Ensure all four values appear across the 16 non-binary users
        forced = ["non-binary", "men", "women", "everyone"][g_idx % 4]
        return forced

    lf_map = {
        ("man",   "straight"):  "women",
        ("man",   "gay"):       "men",
        ("man",   "bisexual"):  ["men", "women", "everyone"][g_idx % 3],
        ("man",   "pansexual"): "everyone",
        ("man",   "other"):     "everyone",
        ("woman", "straight"):  "men",
        ("woman", "lesbian"):   "women",
        ("woman", "bisexual"):  ["men", "women", "everyone"][g_idx % 3],
        ("woman", "pansexual"): "everyone",
        ("woman", "other"):     "everyone",
        ("other", "pansexual"): "everyone",
        ("other", "bisexual"):  "everyone",
        ("other", "straight"):  ["men", "women"][g_idx % 2],
        ("other", "other"):     "everyone",
    }
    return lf_map.get((gender, sexuality), "everyone")


def _pick_age_prefs(age: int, idx: int) -> tuple[int | None, int | None]:
    """~40% of users have explicit age preferences."""
    if idx % 5 == 0:  # 20%: tight range near own age
        spread = random.randint(5, 10)
        lo = max(18, age - spread)
        hi = min(65, age + spread)
        return lo, hi
    if idx % 5 == 1:  # 20%: only min set
        return max(18, age - random.randint(5, 15)), None
    return None, None  # 60%: no preference


# ---------------------------------------------------------------------------
# Build the 100-user manifest
# ---------------------------------------------------------------------------

def _build_users() -> list[dict]:
    users = []
    gender_counters: dict[str, int] = {}

    for i in range(100):
        gender = _GENDERS[i]
        g_idx = gender_counters.get(gender, 0)
        gender_counters[gender] = g_idx + 1

        sexuality = _pick_sexuality(gender, g_idx)
        looking_for = _pick_looking_for(gender, sexuality, g_idx)
        age = _AGE_POOL[i % len(_AGE_POOL)]
        age_min, age_max = _pick_age_prefs(age, i)
        name = _pick_name(gender, g_idx)
        location = _LOCATIONS[i % len(_LOCATIONS)]
        bio = _BIOS[i % len(_BIOS)]
        spirit = _SPIRIT_ANIMALS[i % len(_SPIRIT_ANIMALS)]

        users.append(
            {
                "email": f"demo{i + 1}@howl.app",
                "name": name,
                "age": age,
                "gender": gender,
                "sexuality": sexuality,
                "looking_for": looking_for,
                "age_preference_min": age_min,
                "age_preference_max": age_max,
                "location": location,
                "bio": bio,
                **spirit,
            }
        )
    return users


DEMO_USERS = _build_users()

# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

_DEMO_PASSWORD_HASH = bcrypt.hashpw(b"howl-demo-placeholder", bcrypt.gensalt()).decode()


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
            # Stagger created_at so ordering in Discover feels natural
            created_at = base_time + timedelta(hours=i * 7)
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
                created_at=created_at,
                updated_at=created_at,
            )
            db.add(user)

        db.commit()

        # Print distribution summary
        genders = {}
        for u in DEMO_USERS:
            genders[u["gender"]] = genders.get(u["gender"], 0) + 1
        looking = {}
        for u in DEMO_USERS:
            looking[u["looking_for"]] = looking.get(u["looking_for"], 0) + 1
        ages = [u["age"] for u in DEMO_USERS]

        print(f"Seeded {len(DEMO_USERS)} demo users.")
        print(f"  Gender:     {dict(sorted(genders.items()))}")
        print(f"  Looking for:{dict(sorted(looking.items()))}")
        print(f"  Age range:  {min(ages)}-{max(ages)}, mean {sum(ages)//len(ages)}")
        pref_set = sum(1 for u in DEMO_USERS if u["age_preference_min"] is not None)
        print(f"  Age prefs:  set for {pref_set}/{len(DEMO_USERS)} users")

    except Exception as exc:
        db.rollback()
        print(f"Seed failed: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
