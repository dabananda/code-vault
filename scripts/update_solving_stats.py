"""
Pulls the file tree of the CodeVault repository (github.com/dabananda/CodeVault)
via the GitHub API and computes:
  - number of solved problems per platform (problems/<platform>/...)
  - number of solved solutions per language (by file extension)

The counting rules mirror CodeVault/scripts/update_readme.py so both
repositories always agree on the same numbers:
  - A code file directly inside a platform folder counts as one problem.
  - A code file inside a sub-folder is grouped by that sub-folder UNLESS
    the file has a generic name (main, solution, sol, program, code,
    index) - in that case the sub-folder itself is "the problem"
    (handles problems/uva/<problem name>/main.cpp).
    Otherwise each descriptively-named file is its own problem
    (handles problems/geeksforgeeks/<topic>/<Problem Name>.cpp).

No GitHub token is required for a public repository (subject to the
standard unauthenticated GitHub API rate limit), but the workflow sets
GITHUB_TOKEN automatically when run from Actions, which raises that
limit substantially.
"""

import os
import urllib.request
import json
from pathlib import PurePosixPath

README = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md")

CODEVAULT_OWNER = "dabananda"
CODEVAULT_REPO = "CodeVault"
BRANCHES_TO_TRY = ["main", "master"]

LANGUAGE_EXTENSIONS = {
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".c": "C",
    ".java": "Java",
    ".cs": "C#",
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".sql": "SQL",
    ".go": "Go",
    ".rs": "Rust",
    ".kt": "Kotlin",
    ".rb": "Ruby",
}

GENERIC_FILE_STEMS = {"main", "solution", "sol", "program", "code", "index"}

PLATFORM_DISPLAY_NAMES = {
    "leetcode": "LeetCode",
    "codeforces": "Codeforces",
    "beecrowd": "BeeCrowd",
    "hackerrank": "HackerRank",
    "codechef": "CodeChef",
    "geeksforgeeks": "GeeksforGeeks",
    "coding-ninjas": "Coding Ninjas",
    "uva": "UVA",
    "vjudge": "VJudge",
}


def api_request(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_problem_paths():
    """Returns a flat list of file paths (as strings) under problems/ in CodeVault."""
    last_error = None

    for branch in BRANCHES_TO_TRY:
        url = (
            f"https://api.github.com/repos/{CODEVAULT_OWNER}/{CODEVAULT_REPO}"
            f"/git/trees/{branch}?recursive=1"
        )
        try:
            data = api_request(url)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

        tree = data.get("tree", [])
        paths = [
            item["path"]
            for item in tree
            if item.get("type") == "blob" and item["path"].startswith("problems/")
        ]

        if paths:
            return paths

    if last_error:
        raise RuntimeError(f"Could not fetch CodeVault tree: {last_error}")

    return []


def is_code_file(path: PurePosixPath) -> bool:
    return path.suffix.lower() in LANGUAGE_EXTENSIONS


def compute_stats(paths):
    platform_problem_keys = {}
    language_counts = {lang: 0 for lang in dict.fromkeys(LANGUAGE_EXTENSIONS.values())}

    for raw_path in paths:
        path = PurePosixPath(raw_path)
        parts = path.parts  # e.g. ("problems", "uva", "494 - ...", "main.cpp")

        if len(parts) < 2 or not is_code_file(path):
            continue

        ext = path.suffix.lower()
        language_counts[LANGUAGE_EXTENSIONS[ext]] += 1

        platform = parts[1]
        remainder = parts[2:]  # path segments after the platform folder
        problem_keys = platform_problem_keys.setdefault(platform, set())

        if len(remainder) == 1:
            # Flat file directly under the platform folder.
            problem_keys.add(("file", "", path.stem.lower()))
        else:
            parent_dir = "/".join(remainder[:-1])
            stem = path.stem.lower()

            if stem in GENERIC_FILE_STEMS:
                # e.g. problems/uva/<problem name>/main.cpp
                problem_keys.add(("dir", parent_dir))
            else:
                # e.g. problems/geeksforgeeks/graph/DFS of Graph.cpp
                problem_keys.add(("file", parent_dir, stem))

    platform_counts = {platform: len(keys) for platform, keys in platform_problem_keys.items()}
    language_counts = {lang: count for lang, count in language_counts.items() if count > 0}

    return platform_counts, language_counts


def display_name(platform: str) -> str:
    return PLATFORM_DISPLAY_NAMES.get(platform, platform.title())


def build_platform_table(platform_counts):
    table = "| Platform | Problems |\n|----------|---------:|\n"
    total = 0
    for platform, count in sorted(platform_counts.items(), key=lambda kv: -kv[1]):
        table += f"| {display_name(platform)} | {count} |\n"
        total += count
    table += f"| **Total** | **{total}** |"
    return table, total


def build_language_table(language_counts):
    table = "| Language | Solutions |\n|----------|----------:|\n"
    total = 0
    for language, count in sorted(language_counts.items(), key=lambda kv: -kv[1]):
        table += f"| {language} | {count} |\n"
        total += count
    table += f"| **Total** | **{total}** |"
    return table, total


def replace_between(text, start, end, replacement):
    """Block-style replace: puts replacement on its own line(s)."""
    begin = text.index(start) + len(start)
    finish = text.index(end)
    return text[:begin] + "\n" + replacement + "\n" + text[finish:]


def replace_inline(text, start, end, replacement):
    """Inline replace: no surrounding newlines. Replaces EVERY occurrence
    of the start/end marker pair (a marker may appear more than once in
    the README, e.g. the same total-problems count quoted in two spots)."""
    result = []
    pos = 0
    while True:
        begin = text.find(start, pos)
        if begin == -1:
            result.append(text[pos:])
            break
        finish = text.find(end, begin)
        if finish == -1:
            result.append(text[pos:])
            break
        result.append(text[pos:begin])
        result.append(start)
        result.append(replacement)
        result.append(end)
        pos = finish + len(end)
    return "".join(result)


def main():
    paths = fetch_problem_paths()
    platform_counts, language_counts = compute_stats(paths)

    platform_table, total_problems = build_platform_table(platform_counts)
    language_table, total_solutions = build_language_table(language_counts)

    with open(README, "r", encoding="utf-8") as f:
        readme = f.read()

    readme = replace_between(
        readme, "<!-- START_PLATFORM_STATS -->", "<!-- END_PLATFORM_STATS -->", platform_table
    )
    readme = replace_between(
        readme, "<!-- START_LANGUAGE_STATS -->", "<!-- END_LANGUAGE_STATS -->", language_table
    )
    readme = replace_inline(
        readme,
        "<!-- START_TOTAL_PROBLEMS -->",
        "<!-- END_TOTAL_PROBLEMS -->",
        str(total_problems),
    )

    with open(README, "w", encoding="utf-8") as f:
        f.write(readme)

    print("Profile README updated successfully.")
    print(f"Total problems: {total_problems}")
    print(f"Total solutions: {total_solutions}")
    print("Platform breakdown:", dict(sorted(platform_counts.items(), key=lambda kv: -kv[1])))
    print("Language breakdown:", dict(sorted(language_counts.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
