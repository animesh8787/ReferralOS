"""Skill taxonomy with alias handling ("Postgres" == "PostgreSQL", "k8s" == "Kubernetes").

Used by resume parsing, GitHub inference, JD analysis and tailoring so every module agrees on names.
shortcut: ~100 common skills, edit SKILLS to extend; single-letter languages (C) are case-sensitive and can
false-positive on stray capital letters, so callers treat matches as candidates, never as proof.
"""
import re

# canonical -> (category, aliases)
SKILLS: dict[str, tuple[str, list[str]]] = {
    "Python": ("language", ["python3"]), "Java": ("language", []), "JavaScript": ("language", ["js", "ecmascript"]),
    "TypeScript": ("language", ["ts"]), "Go": ("language", ["golang"]), "Rust": ("language", []),
    "C++": ("language", ["cpp"]), "C": ("language", []), "C#": ("language", ["csharp"]), "Kotlin": ("language", []),
    "Swift": ("language", []), "Ruby": ("language", []), "PHP": ("language", []), "Scala": ("language", []),
    "SQL": ("language", []), "Bash": ("language", ["shell scripting", "shell"]), "R": ("language", []),
    "React": ("framework", ["react.js", "reactjs"]), "Next.js": ("framework", ["nextjs"]),
    "Node.js": ("framework", ["node", "nodejs"]), "Express": ("framework", ["express.js"]),
    "Django": ("framework", []), "Flask": ("framework", []), "FastAPI": ("framework", []),
    "Spring Boot": ("framework", ["spring"]), "Angular": ("framework", []), "Vue": ("framework", ["vue.js"]),
    "PostgreSQL": ("database", ["postgres"]), "MySQL": ("database", []), "MongoDB": ("database", ["mongo"]),
    "Redis": ("database", []), "SQLite": ("database", []), "Elasticsearch": ("database", ["elastic search"]),
    "DynamoDB": ("database", []), "Cassandra": ("database", []), "Kafka": ("infrastructure", ["apache kafka"]),
    "RabbitMQ": ("infrastructure", []), "AWS": ("cloud", ["amazon web services"]), "GCP": ("cloud", ["google cloud", "google cloud platform"]),
    "Azure": ("cloud", ["microsoft azure"]), "Docker": ("infrastructure", []), "Kubernetes": ("infrastructure", ["k8s"]),
    "Terraform": ("infrastructure", []), "Linux": ("infrastructure", []), "Git": ("tool", []), "GitHub Actions": ("tool", []),
    "CI/CD": ("methodology", ["cicd", "continuous integration"]), "Jenkins": ("tool", []),
    "REST APIs": ("methodology", ["rest", "restful", "rest api", "restful apis"]), "GraphQL": ("methodology", []),
    "gRPC": ("methodology", []), "Microservices": ("methodology", ["microservice"]),
    "Machine Learning": ("ai_ml", ["ml"]), "Deep Learning": ("ai_ml", []), "NLP": ("ai_ml", ["natural language processing"]),
    "Computer Vision": ("ai_ml", []), "PyTorch": ("ai_ml", []), "TensorFlow": ("ai_ml", []),
    "scikit-learn": ("ai_ml", ["sklearn", "scikit learn"]), "Pandas": ("ai_ml", []), "NumPy": ("ai_ml", []),
    "LLMs": ("ai_ml", ["large language models", "llm"]), "RAG": ("ai_ml", ["retrieval augmented generation"]),
    "Spark": ("data", ["apache spark", "pyspark"]), "Airflow": ("data", ["apache airflow"]), "dbt": ("data", []),
    "Data Structures": ("concept", ["data structures and algorithms", "dsa"]), "Algorithms": ("concept", []),
    "System Design": ("concept", ["distributed systems"]), "Agile": ("methodology", ["scrum"]),
    "HTML": ("language", ["html5"]), "CSS": ("language", ["css3"]), "Tailwind CSS": ("framework", ["tailwind"]),
    "JUnit": ("tool", []), "Pytest": ("tool", []), "Prometheus": ("tool", []), "Grafana": ("tool", []),
}
# a framework you used implies its language; used by resume parsing to link a listed language to the projects that necessarily use it.
# Ambiguous cases (OpenCV: C++ or Python) are left out on purpose.
IMPLIES: dict[str, tuple[str, ...]] = {
    **{f: ("Python",) for f in ("Django", "Flask", "FastAPI", "PyTorch", "TensorFlow", "scikit-learn", "Pandas", "NumPy", "Airflow", "Pytest")},
    **{f: ("JavaScript",) for f in ("React", "Next.js", "Node.js", "Express", "Angular", "Vue")},
    "TypeScript": ("JavaScript",), "Spring Boot": ("Java",), "JUnit": ("Java",),
}
CASE_SENSITIVE = {"Go", "C", "R"}  # too ambiguous to match case-insensitively

_ALIAS: dict[str, str] = {}
for canon, (_, aliases) in SKILLS.items():
    _ALIAS[canon.lower()] = canon
    for a in aliases:
        _ALIAS[a.lower()] = canon

_names = sorted({n for n in _ALIAS} | {n for n in CASE_SENSITIVE}, key=len, reverse=True)
_RX = re.compile(r"(?<![\w+#.])(" + "|".join(re.escape(n) for n in _names) + r")(?![\w+#]|\.\w)", re.I)


def normalize(token: str) -> str | None:
    t = token.strip()
    if t in CASE_SENSITIVE:
        return t
    return _ALIAS.get(t.lower())


def category(canon: str) -> str:
    return SKILLS[canon][0] if canon in SKILLS else "other"


def find_skills(text: str) -> list[tuple[str, int]]:
    """[(canonical, char offset)] in order of appearance; may repeat."""
    out = []
    for m in _RX.finditer(text):
        raw = m.group(1)
        low = raw.lower()
        if low in {c.lower() for c in CASE_SENSITIVE} and raw not in CASE_SENSITIVE:
            continue  # "go"/"c"/"r" in lowercase prose is not a language
        canon = normalize(raw)
        if canon:
            out.append((canon, m.start()))
    return out


def skill_set(text: str) -> set[str]:
    return {c for c, _ in find_skills(text)}
