"""Score job listings against user profile using OpenAI."""
import json
import re
from openai import OpenAI
from . import config


def _sanitize(text: str) -> str:
    """Convert unicode characters to ASCII-safe text for API processing."""
    replacements = {
        "\u2014": "-",  # em dash
        "\u2013": "-",  # en dash
        "\u2018": "'",  # left single quote
        "\u2019": "'",  # right single quote
        "\u201c": '"',  # left double quote
        "\u201d": '"',  # right double quote
        "\u2022": "-",  # bullet
        "\u2026": "...",  # ellipsis
        "\xa0": " ",  # non-breaking space
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


SYSTEM_PROMPT = """You are an expert job matching assistant. Your task is to evaluate how well a job posting matches a candidate's profile.

Return ONLY a JSON object with exactly these two fields:
{
  "score": <number from 0 to 10>,
  "reasoning": "<one sentence explaining the score>"
}

Scoring guidelines:
- 9-10: Perfect match - role, seniority, industry, and requirements align exactly
- 7-8: Strong match - most criteria align with minor gaps
- 5-6: Moderate match - some alignment but notable gaps
- 3-4: Weak match - limited alignment
- 1-2: Poor match - significant misalignment
- 0: No match - completely irrelevant

IMPORTANT location scoring adjustments:
- ADD +1 point for fully remote roles or roles explicitly open to Canada
- ADD +0.5 points for "remote-first" or "North America remote" roles
- SUBTRACT -2 points for onsite-only roles or roles requiring specific US city presence
- SUBTRACT -1 point if Canada is not explicitly mentioned and role seems US-only

Be honest and critical. Only give high scores when there's genuine alignment."""


USER_TEMPLATE = """## Candidate Profile
{profile}

## Job Posting
**Title:** {title}
**Company:** {company}
**Location:** {location}

**Description:**
{description}

Evaluate this job's fit for the candidate and respond with JSON only."""


def score_job(
    title: str,
    company: str,
    location: str,
    description: str,
    profile: str,
) -> tuple[float, str]:
    """
    Score a job posting against the user's profile.

    Returns:
        Tuple of (score, reasoning) where score is 0-10 and reasoning is a sentence.
        Returns (0.0, "") if any error occurs.
    """
    if not config.OPENAI_API_KEY:
        print("    Warning: No OpenAI API key configured")
        return (0.0, "")

    try:
        client = OpenAI(api_key=config.OPENAI_API_KEY)

        # Prepare the prompt
        user_content = USER_TEMPLATE.format(
            profile=_sanitize(profile[:3000]),
            title=_sanitize(title[:200]),
            company=_sanitize(company[:100]),
            location=_sanitize(location[:100]),
            description=_sanitize(description[:6000]),
        )

        # Call OpenAI
        response = client.chat.completions.create(
            model=config.SCORING_MODEL,
            max_completion_tokens=200,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )

        # Parse the response
        text = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        result = json.loads(text)
        score = float(result.get("score", 0))
        reasoning = str(result.get("reasoning", ""))

        return (min(max(score, 0), 10), reasoning)

    except json.JSONDecodeError as e:
        print(f"    Scorer JSON error: {e}")
        return (0.0, "")
    except Exception as e:
        print(f"    Scorer error: {e}")
        return (0.0, "")
