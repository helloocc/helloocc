"""Generate a terminal-style GitHub SVG for the profile README."""
from __future__ import annotations

import base64
import datetime
import html
import os
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dateutil import relativedelta
from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
IMG_DIR = ROOT / "img"
DARK_SVG = IMG_DIR / "github_stats_dark.svg"
LIGHT_SVG = IMG_DIR / "github_stats_light.svg"

USER_NAME = os.environ.get("USER_NAME") or os.environ.get("GITHUB_ACTOR") or "helloocc"
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
TZ = ZoneInfo("Asia/Shanghai")
TOP_LANGUAGES = 4
TOP_REPOS = 5
LANG_ALIAS = {"JavaScript": "JS", "TypeScript": "TS", "Objective-C": "ObjC"}

THEMES = {
    "dark": {
        "bg": "#2e3440",
        "panel": "#3b4252",
        "border": "#c8c3e0",
        "label": "#d08770",
        "text": "#eceff4",
        "muted": "#7b88a1",
        "highlight": "#1DB954",
        "progress": "#1DB954",
        "prompt_a": "#4c566a",
        "prompt_b": "#81a1c1",
        "prompt_c": "#d08770",
        "capsule": "#eceff4",
        "capsule_text": "#2e3440",
        "palette": ["#bf616a", "#d08770", "#ebcb8b", "#a3be8c", "#88c0d0", "#81a1c1", "#b48ead", "#eceff4"],
    },
    "light": {
        "bg": "#eceff4",
        "panel": "#e5e9f0",
        "border": "#81a1c1",
        "label": "#bf616a",
        "text": "#2e3440",
        "muted": "#4c566a",
        "highlight": "#1DB954",
        "progress": "#1DB954",
        "prompt_a": "#4c566a",
        "prompt_b": "#81a1c1",
        "prompt_c": "#d08770",
        "capsule": "#2e3440",
        "capsule_text": "#eceff4",
        "palette": ["#bf616a", "#d08770", "#ebcb8b", "#a3be8c", "#88c0d0", "#81a1c1", "#b48ead", "#4c566a"],
    },
}


def github_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "helloocc-github-stats"}
    if ACCESS_TOKEN:
        h["Authorization"] = f"token {ACCESS_TOKEN}"
    return h


def github_get(url: str):
    resp = requests.get(url, headers=github_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json()


def graphql(query: str, variables: dict) -> dict:
    resp = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=github_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def format_plural(unit: int) -> str:
    return "s" if unit != 1 else ""


def account_uptime(created_at: str) -> str:
    created = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
    diff = relativedelta.relativedelta(datetime.datetime.utcnow(), created)
    return "{} {}, {} {}, {} {}".format(
        diff.years,
        "year" + format_plural(diff.years),
        diff.months,
        "month" + format_plural(diff.months),
        diff.days,
        "day" + format_plural(diff.days),
    )


def comma(n) -> str:
    if n in (None, "", "—"):
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def fetch_user() -> dict:
    return github_get(f"https://api.github.com/users/{USER_NAME}")


def fetch_repos() -> list[dict]:
    repos = []
    page = 1
    while True:
        batch = github_get(
            f"https://api.github.com/users/{USER_NAME}/repos?per_page=100&page={page}&type=owner&sort=updated"
        )
        if not isinstance(batch, list) or not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_contributed_count() -> int | None:
    if not ACCESS_TOKEN:
        return None
    query = """
    query ($login: String!) {
      user(login: $login) {
        repositories(first: 1, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
          totalCount
        }
      }
    }
    """
    return int(graphql(query, {"login": USER_NAME})["user"]["repositories"]["totalCount"])


def fetch_commit_count(created_at: str) -> int | None:
    if not ACCESS_TOKEN:
        return None
    query = """
    query ($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          restrictedContributionsCount
        }
      }
    }
    """
    start = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.timezone.utc)
    total = 0
    cursor = start
    while cursor < now:
        nxt = min(cursor.replace(year=cursor.year + 1), now)
        col = graphql(
            query,
            {
                "login": USER_NAME,
                "from": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )["user"]["contributionsCollection"]
        total += int(col["totalCommitContributions"]) + int(col["restrictedContributionsCount"])
        cursor = nxt
    return total


def top_languages(repos: list[dict]) -> str:
    langs = [repo["language"] for repo in repos if not repo.get("fork") and repo.get("language")]
    if not langs:
        return "—"
    ranked = [LANG_ALIAS.get(name, name) for name, _ in Counter(langs).most_common(TOP_LANGUAGES)]
    return ", ".join(ranked)


def avatar_data_uri(avatar_url: str, size: int = 280) -> str:
    url = avatar_url
    sep = "&" if "?" in url else "?"
    resp = requests.get(f"{url}{sep}s={size}", headers={"User-Agent": "helloocc-github-stats"}, timeout=20)
    resp.raise_for_status()
    img = Image.open(BytesIO(resp.content)).convert("RGB")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def kv_line(x: int, y: int, key: str, value: str, theme: dict) -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="14" fill="{theme["label"]}">{html.escape(key)}</text>'
        f'<text x="{x + 92}" y="{y}" font-size="14" fill="{theme["text"]}">{html.escape(value)}</text>'
    )


def stamp_text(fetched_at: float | None = None) -> str:
    return datetime.datetime.now(TZ).strftime("%Y-%m-%d")


def build_svg(
    theme_name: str,
    avatar_uri: str,
    profile: dict,
    stats: dict,
    top_repos: list[dict],
    fetched_at: float | None = None,
) -> str:
    theme = THEMES[theme_name]
    login = profile["display_name"]

    fields = [
        ("Role: ", profile["role"]),
        ("Focus: ", profile["focus"]),
        ("Stack: ", profile["stack"]),
        ("Deploy: ", profile["deploy"]),
        ("Location: ", profile["location"]),
        ("GitHub: ", f"On GitHub since {profile['since']}"),
    ]
    if profile.get("os"):
        fields.insert(4, ("OS: ", profile["os"]))
    info = [kv_line(326, 88 + i * 30, key, value, theme)
            for i, (key, value) in enumerate(fields)]

    palette = []
    for i, color in enumerate(theme["palette"]):
        palette.append(f'<rect x="{326 + i * 22}" y="334" width="16" height="16" rx="2" fill="{color}"/>')

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="980" height="420" viewBox="0 0 980 420" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">
  <title>{html.escape(login)} GitHub terminal</title>
  <rect width="980" height="420" rx="18" fill="{theme["bg"]}"/>
  <rect x="16" y="16" width="276" height="340" rx="14" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="2"/>
  <clipPath id="avatarClip"><rect x="24" y="54" width="260" height="260" rx="10"/></clipPath>
  <image href="{avatar_uri}" xlink:href="{avatar_uri}" x="24" y="54" width="260" height="260" clip-path="url(#avatarClip)" preserveAspectRatio="xMidYMid slice"/>
  <rect x="308" y="16" width="656" height="340" rx="14" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="2"/>
  <text x="636" y="44" text-anchor="middle" font-size="18" fill="{theme["text"]}">&lt; {html.escape(login)} &gt;</text>
  <text x="636" y="60" text-anchor="middle" font-size="11" fill="{theme["muted"]}">--------------------------------</text>
  {''.join(info)}
  {''.join(palette)}
  <path d="M16 372 L78 372 L90 404 L16 404 Z" fill="{theme["prompt_a"]}"/>
  <path d="M70 372 L148 372 L160 404 L82 404 Z" fill="{theme["prompt_b"]}"/>
  <path d="M140 372 L248 372 L260 404 L152 404 Z" fill="{theme["prompt_c"]}"/>
  <text x="28" y="394" font-size="12" fill="{theme["text"]}">gh</text>
  <text x="92" y="394" font-size="12" fill="{theme["bg"]}">~/</text>
  <text x="164" y="394" font-size="12" fill="{theme["bg"]}">{html.escape(login)}</text>
  <text x="272" y="394" font-size="14" fill="{theme["text"]}">_</text>
  <rect x="668" y="376" width="296" height="28" rx="14" fill="{theme["capsule"]}"/>
  <text x="816" y="395" text-anchor="middle" font-size="12" fill="{theme["capsule_text"]}">{html.escape(profile["website"])}</text>
</svg>
"""


def collect_github() -> dict:
    user = fetch_user()
    profile = {
        "github": user.get("login") or USER_NAME,
        "display_name": "HelloC",
        "role": "Full-stack Engineer / Indie Builder",
        "focus": "Web Apps · Mini Programs · Automation",
        "stack": "TypeScript · Node.js · Python",
        "deploy": "Docker · CI/CD",
        "location": "Hangzhou, China · Remote",
        "since": user["created_at"][:4],
        "website": "helloc.net",
        "os": os.environ.get("PROFILE_OS", ""),
    }
    avatar_url = user.get("avatar_url") or f"https://github.com/{USER_NAME}.png"
    return {
        "profile": profile,
        "stats": {},
        "avatar_uri": avatar_data_uri(avatar_url),
        "top_repos": [],
    }


def render_card(theme: str, github: dict, fetched_at: float | None = None) -> str:
    return build_svg(
        theme,
        github["avatar_uri"],
        github["profile"],
        github["stats"],
        github.get("top_repos") or [],
        fetched_at,
    )


def main() -> int:
    github = collect_github()
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    DARK_SVG.write_text(render_card("dark", github), encoding="utf-8")
    LIGHT_SVG.write_text(render_card("light", github), encoding="utf-8")
    print(f"Wrote {DARK_SVG.relative_to(ROOT)} and {LIGHT_SVG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
