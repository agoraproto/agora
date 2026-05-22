"""The 20-agent swarm — personalities, capabilities, prompts.

Each entry defines an autonomous LLM-driven agent that registers on
Agora, transacts via x402, and lives on Base Sepolia. The DIDs are
derived deterministically from the agent's `slug` so re-running the
bootstrap is idempotent.
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class ProviderSpec:
    slug: str
    name: str
    description: str
    capability: str                 # canonical capability tag
    base_price_usdc: Decimal        # > 0.50 USDC (escrow minFee)
    system_prompt: str              # Anthropic prompt that shapes the LLM
    input_schema_hint: str          # what the task_spec should contain


@dataclass
class BuyerSpec:
    slug: str
    name: str
    description: str
    needs: list[str]                # capability tags this buyer hires for
    tick_seconds: int               # how often to hire someone
    initial_usdc: Decimal           # starting wallet balance
    task_templates: dict[str, str] = field(default_factory=dict)


# ─── 10 Provider Agents ────────────────────────────────────────────

PROVIDERS = [
    ProviderSpec(
        slug="translator-en-de",
        name="Helga the Translator",
        description="Single-message English ↔ German translator. Idiomatic, formal register by default.",
        capability="Translation",
        base_price_usdc=Decimal("0.80"),
        system_prompt=(
            "You are Helga, a precise EN↔DE translator. Translate the user's "
            "text into the requested target language. Return only the "
            "translation, no preamble, no explanation."
        ),
        input_schema_hint="{ text: str, target: 'de' | 'en' }",
    ),
    ProviderSpec(
        slug="summarizer",
        name="Sam the Summarizer",
        description="Condenses long text into 3-bullet summaries.",
        capability="Summarization",
        base_price_usdc=Decimal("0.70"),
        system_prompt=(
            "You are Sam. Summarize the user's text in exactly three concise "
            "bullet points. Each bullet under 20 words. No preamble."
        ),
        input_schema_hint="{ text: str }",
    ),
    ProviderSpec(
        slug="sentiment",
        name="Sentinel the Sentiment Analyst",
        description="Returns positive / neutral / negative + 1-sentence reasoning.",
        capability="SentimentAnalysis",
        base_price_usdc=Decimal("0.55"),
        system_prompt=(
            "You are Sentinel. Classify the user's text into 'positive', "
            "'negative', or 'neutral'. Output JSON exactly: "
            "{\"label\": \"...\", \"reason\": \"<one short sentence>\"}."
        ),
        input_schema_hint="{ text: str }",
    ),
    ProviderSpec(
        slug="joke-maker",
        name="Jester Joey",
        description="Generates a single short joke about the requested topic.",
        capability="JokeGeneration",
        base_price_usdc=Decimal("0.60"),
        system_prompt=(
            "You are Joey, a stand-up comedian. Generate one short, "
            "PG-rated joke (setup + punchline, two lines max) about the "
            "user's topic. No explanation."
        ),
        input_schema_hint="{ topic: str }",
    ),
    ProviderSpec(
        slug="code-reviewer",
        name="Cody the Code Reviewer",
        description="Quick review of a short code snippet: 1 bug + 1 suggestion.",
        capability="CodeReview",
        base_price_usdc=Decimal("0.90"),
        system_prompt=(
            "You are Cody. Review the user's code snippet. Reply in JSON: "
            "{\"bug\": \"<the most likely bug or 'none'>\", "
            "\"suggestion\": \"<one improvement>\"}."
        ),
        input_schema_hint="{ code: str, language: str }",
    ),
    ProviderSpec(
        slug="fact-checker",
        name="Veronica the Fact Checker",
        description="Sanity-check a single claim and rate confidence.",
        capability="FactCheck",
        base_price_usdc=Decimal("0.85"),
        system_prompt=(
            "You are Veronica. Assess the user's claim. Reply in JSON: "
            "{\"verdict\": \"likely_true|uncertain|likely_false\", "
            "\"reasoning\": \"<2 sentences max>\"}. "
            "Do not invent citations."
        ),
        input_schema_hint="{ claim: str }",
    ),
    ProviderSpec(
        slug="tarot-reader",
        name="Tara the Tarot Reader",
        description="Entertainment: pulls 3 cards and gives a reading.",
        capability="TarotReading",
        base_price_usdc=Decimal("0.55"),
        system_prompt=(
            "You are Tara, an entertainer who does tarot for fun. Pull "
            "three random major-arcana cards and give a 3-paragraph "
            "reading about the user's question. Theatrical tone. End "
            "with: 'Take this as fiction, not advice.'"
        ),
        input_schema_hint="{ question: str }",
    ),
    ProviderSpec(
        slug="image-describer",
        name="Iris the Image Describer",
        description="Writes alt-text for images (no real image, simulated).",
        capability="ImageDescription",
        base_price_usdc=Decimal("0.55"),
        system_prompt=(
            "You are Iris. The user describes an image in words; you "
            "produce a polished one-sentence alt-text suitable for "
            "screen readers. Reply with only that sentence."
        ),
        input_schema_hint="{ raw_description: str }",
    ),
    ProviderSpec(
        slug="idea-generator",
        name="Isabella the Idea Generator",
        description="Brainstorms 5 ideas for a given topic.",
        capability="Brainstorming",
        base_price_usdc=Decimal("0.65"),
        system_prompt=(
            "You are Isabella. Produce a numbered list of exactly five "
            "distinct creative ideas for the user's topic. Each idea "
            "one short sentence. No preamble."
        ),
        input_schema_hint="{ topic: str }",
    ),
    ProviderSpec(
        slug="rhyme-maker",
        name="Romeo the Rhyme Maker",
        description="Provides 3 rhymes for a word.",
        capability="Rhyming",
        base_price_usdc=Decimal("0.51"),
        system_prompt=(
            "You are Romeo. Return three real-word rhymes for the "
            "user's word, comma-separated. No preamble."
        ),
        input_schema_hint="{ word: str }",
    ),
]


# ─── 10 Buyer Agents ───────────────────────────────────────────────

BUYERS = [
    BuyerSpec(
        slug="marketing-alice",
        name="Marketing Alice",
        description="Marketer who frequently needs translations and sentiment.",
        needs=["Translation", "SentimentAnalysis", "Brainstorming"],
        tick_seconds=120,
        initial_usdc=Decimal("2.0"),
        task_templates={
            "Translation": '{"text": "Limited-time offer: 20% off this week.", "target": "de"}',
            "SentimentAnalysis": '{"text": "I am not sure this product is right for me."}',
            "Brainstorming": '{"topic": "headlines for a Black Friday email"}',
        },
    ),
    BuyerSpec(
        slug="dev-bob",
        name="DevBob",
        description="Engineer who reviews code and summarizes docs.",
        needs=["CodeReview", "Summarization"],
        tick_seconds=180,
        initial_usdc=Decimal("2.0"),
        task_templates={
            "CodeReview": '{"code": "def add(a, b):\\n    return a - b", "language": "python"}',
            "Summarization": '{"text": "Distributed systems trade availability for consistency. CAP theorem says you can have only two."}',
        },
    ),
    BuyerSpec(
        slug="writer-carl",
        name="Writer Carl",
        description="Author looking for rhymes and ideas for poems.",
        needs=["Rhyming", "Brainstorming"],
        tick_seconds=150,
        initial_usdc=Decimal("1.5"),
        task_templates={
            "Rhyming": '{"word": "ocean"}',
            "Brainstorming": '{"topic": "metaphors for grief"}',
        },
    ),
    BuyerSpec(
        slug="teacher-dana",
        name="Teacher Dana",
        description="High-school teacher; needs summaries and fact-checks.",
        needs=["Summarization", "FactCheck"],
        tick_seconds=200,
        initial_usdc=Decimal("2.0"),
        task_templates={
            "Summarization": '{"text": "Photosynthesis converts CO2 and water into glucose using sunlight. The byproduct is oxygen."}',
            "FactCheck": '{"claim": "Sharks have been around longer than trees."}',
        },
    ),
    BuyerSpec(
        slug="social-eva",
        name="Social Eva",
        description="Community manager; reads sentiment, writes jokes.",
        needs=["SentimentAnalysis", "JokeGeneration"],
        tick_seconds=140,
        initial_usdc=Decimal("1.5"),
        task_templates={
            "SentimentAnalysis": '{"text": "Honestly your latest update is awful."}',
            "JokeGeneration": '{"topic": "Mondays"}',
        },
    ),
    BuyerSpec(
        slug="novelist-fred",
        name="Novelist Fred",
        description="Writes fiction; needs ideas and rhymes.",
        needs=["Brainstorming", "Rhyming"],
        tick_seconds=220,
        initial_usdc=Decimal("1.5"),
        task_templates={
            "Brainstorming": '{"topic": "plot twists for a detective novel"}',
            "Rhyming": '{"word": "midnight"}',
        },
    ),
    BuyerSpec(
        slug="insight-greg",
        name="Insight Greg",
        description="Analyst; sentiment + summary heavy.",
        needs=["SentimentAnalysis", "Summarization"],
        tick_seconds=170,
        initial_usdc=Decimal("2.0"),
        task_templates={
            "SentimentAnalysis": '{"text": "Q3 results were a mixed bag but the trend looks promising."}',
            "Summarization": '{"text": "Earnings beat by 5%. Guidance raised. Stock up 3% AH."}',
        },
    ),
    BuyerSpec(
        slug="consultant-helga",
        name="Consultant Helga",
        description="Bilingual consultant; lots of translation, some fact-check.",
        needs=["Translation", "FactCheck"],
        tick_seconds=160,
        initial_usdc=Decimal("2.0"),
        task_templates={
            "Translation": '{"text": "Please find attached our proposal.", "target": "de"}',
            "FactCheck": '{"claim": "Germany has more public holidays than any EU country."}',
        },
    ),
    BuyerSpec(
        slug="entrepreneur-ingrid",
        name="Entrepreneur Ingrid",
        description="Founder; brainstorms a lot.",
        needs=["Brainstorming", "Summarization"],
        tick_seconds=130,
        initial_usdc=Decimal("1.5"),
        task_templates={
            "Brainstorming": '{"topic": "names for a sustainable cleaning-products brand"}',
            "Summarization": '{"text": "VC term sheet: $2M at $10M post, 1x non-participating preferred, 1x liquidation."}',
        },
    ),
    BuyerSpec(
        slug="streamer-joe",
        name="Streamer Joe",
        description="Twitch streamer; jokes and tarot for content.",
        needs=["JokeGeneration", "TarotReading"],
        tick_seconds=110,
        initial_usdc=Decimal("1.5"),
        task_templates={
            "JokeGeneration": '{"topic": "ranked gaming"}',
            "TarotReading": '{"question": "Will my stream hit 5k followers this month?"}',
        },
    ),
]


def all_specs() -> dict:
    return {
        "providers": {p.slug: p for p in PROVIDERS},
        "buyers": {b.slug: b for b in BUYERS},
    }


if __name__ == "__main__":
    print(f"Providers: {len(PROVIDERS)}")
    for p in PROVIDERS:
        print(f"  {p.slug:25s} cap={p.capability:18s} price={p.base_price_usdc} USDC")
    print(f"\nBuyers: {len(BUYERS)}")
    for b in BUYERS:
        print(f"  {b.slug:25s} needs={b.needs} tick={b.tick_seconds}s budget={b.initial_usdc} USDC")
    print(f"\nTotal initial USDC needed: {sum(b.initial_usdc for b in BUYERS)}")
