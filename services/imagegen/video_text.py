"""Lightweight, dependency-free lyric semantics used by the deterministic planner."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

STOPWORDS = {
    # English
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "could", "did",
    "do", "does", "don", "for", "from", "had", "has", "have", "he", "her", "here", "hers",
    "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "just", "like", "me",
    "more", "my", "no", "not", "now", "of", "on", "one", "only", "or", "our", "out", "she",
    "so", "some", "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "to", "too", "up", "us", "was", "we", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "you", "your", "yours", "all", "any", "every",
    "let", "got", "get", "going", "gonna", "wanna", "yeah", "oh", "ooh", "ah", "la", "na",
    # Portuguese
    "a", "ao", "aos", "as", "ás", "aquela", "aquele", "aquilo", "as", "até", "com", "como",
    "da", "das", "de", "dela", "dele", "depois", "do", "dos", "e", "é", "ela", "elas", "ele",
    "eles", "em", "entre", "era", "essa", "esse", "esta", "este", "eu", "foi", "há", "isso",
    "isto", "já", "lhe", "lhes", "mais", "mas", "me", "mesmo", "meu", "minha", "muito", "na",
    "não", "nas", "nem", "no", "nos", "nós", "num", "numa", "o", "os", "ou", "para", "pela",
    "pelo", "por", "qual", "que", "quem", "se", "sem", "ser", "seu", "sua", "são", "só", "tá",
    "te", "tem", "tu", "um", "uma", "você", "vocês", "vou", "vai", "vamos", "ainda", "bem",
    "quando", "onde", "porque", "também", "todo", "toda", "todos", "todas", "sim", "nunca",
    "sempre", "coisa", "coisas", "fazer", "faz", "ter", "tenho", "tens", "está", "estou",
}

POSITIVE_WORDS = {
    "love", "amor", "light", "luz", "sun", "sol", "hope", "esperança", "home", "casa",
    "smile", "sorriso", "dream", "sonho", "together", "juntos", "free", "livre", "peace",
    "paz", "joy", "alegria", "gold", "ouro", "heart", "coração", "dance", "dançar", "fly",
    "voar", "warm", "quente", "beautiful", "bonito", "vida", "life", "felicidade", "happy",
}
NEGATIVE_WORDS = {
    "rain", "chuva", "cold", "frio", "lost", "perdido", "pain", "dor", "cry", "choro",
    "dark", "escuro", "alone", "sozinho", "fear", "medo", "war", "guerra", "blood", "sangue",
    "goodbye", "adeus", "tears", "lágrimas", "empty", "vazio", "broken", "quebrado", "night",
    "noite", "shadow", "sombra", "dead", "morte", "fall", "cair", "storm", "tempestade",
}

MOTIF_RULES: dict[str, tuple[tuple[str, ...], str, str]] = {
    # motif: keywords, scene location phrase, visual motif noun
    "journey": (
        ("road", "estrada", "way", "caminho", "travel", "viajar", "journey", "viagem", "run", "correr", "drive", "drive"),
        "an open road winding through a vast landscape",
        "a distant traveller on the road",
    ),
    "ocean": (
        ("sea", "mar", "ocean", "onda", "waves", "tide", "beach", "praia", "shore", "sail", "barco"),
        "a windswept ocean coast at the edge of the world",
        "a solitary figure facing the sea",
    ),
    "river": (
        ("river", "rio", "stream", "waterfall", "cachoeira", "water", "água"),
        "a luminous river cutting through a quiet valley",
        "a river reflecting the sky",
    ),
    "mountain": (
        ("mountain", "montanha", "hill", "colina", "peak", "summit", "cliff", "abismo", "valley"),
        "towering mountains above a sea of clouds",
        "a tiny figure against enormous peaks",
    ),
    "forest": (
        ("forest", "floresta", "tree", "árvore", "wood", "woods", "mata", "leaf", "folha", "jungle"),
        "a mist-filled forest with shafts of light",
        "light filtering between ancient trees",
    ),
    "desert": (
        ("desert", "deserto", "sand", "areia", "dune", "duna", "dust", "poeira", "mirage"),
        "endless desert dunes under a burning sky",
        "wind lifting dust across the dunes",
    ),
    "city": (
        ("city", "cidade", "street", "rua", "town", "neon", "building", "prédio", "subway", "downtown"),
        "a glowing city of towers and wet streets",
        "neon reflections in rain-slicked streets",
    ),
    "home": (
        ("home", "casa", "room", "quarto", "window", "janela", "door", "porta", "kitchen", "bed"),
        "a warm room with a window full of dusk",
        "a familiar window glowing from within",
    ),
    "space": (
        ("sky", "céu", "star", "estrela", "stars", "moon", "lua", "space", "espaço", "cosmos",
         "planet", "planeta", "universe", "universo", "galaxy", "via láctea"),
        "a vast night sky scattered with stars",
        "a small figure beneath an immense sky",
    ),
    "fire": (
        ("fire", "fogo", "flame", "chama", "burn", "queimar", "ember", "brasa", "spark", "faísca"),
        "a landscape lit by drifting embers and firelight",
        "embers rising into the dark",
    ),
    "rain": (
        ("rain", "chuva", "storm", "tempestade", "thunder", "trovão", "wet", "molhado"),
        "rain sweeping across a lonely landscape",
        "rain beading on glass and skin",
    ),
    "snow": (
        ("snow", "neve", "ice", "gelo", "frost", "winter", "inverno", "cold", "frio"),
        "a silent world under falling snow",
        "breath turning to mist in frozen air",
    ),
    "flowers": (
        ("flower", "flor", "flowers", "flores", "garden", "jardim", "rose", "rosa", "bloom",
         "primavera", "spring"),
        "a wild garden in full bloom",
        "petals drifting on the wind",
    ),
    "dance": (
        ("dance", "dançar", "dancing", "move", "body", "corpo", "rhythm", "ritmo", "sway"),
        "a dreamlike ballroom dissolving into light",
        "two figures caught mid-motion",
    ),
    "war": (
        ("war", "guerra", "fight", "luta", "battle", "batalha", "soldier", "soldado", "weapon",
         "army", "exército"),
        "a scarred landscape under a pale sky",
        "a lone figure walking through remembered ruins",
    ),
    "childhood": (
        ("child", "criança", "youth", "infância", "memory", "memória", "remember", "lembrar",
         "past", "passado", "old", "velho"),
        "a sunlit place half-remembered from childhood",
        "a figure standing at the edge of memory",
    ),
    "freedom": (
        ("free", "livre", "freedom", "liberdade", "open", "aberto", "escape", "fugir", "fly", "voar"),
        "an immense open horizon with nothing in the way",
        "arms open to the wind",
    ),
    "night": (
        ("night", "noite", "midnight", "meia-noite", "dark", "escuro", "shadow", "sombra"),
        "a moonlit world of blue shadows",
        "a silhouette outlined by moonlight",
    ),
    "sunrise": (
        ("sun", "sol", "dawn", "amanhecer", "morning", "manhã", "sunrise", "light", "luz",
         "golden", "dourado"),
        "a horizon burning with the first light of day",
        "sunlight breaking over a sleeping world",
    ),
}

MOOD_WORDS = {
    "romantic": {"love", "amor", "heart", "coração", "kiss", "beijo", "you", "você", "together", "juntos", "forever", "sempre"},
    "melancholic": {"rain", "chuva", "lost", "perdido", "gone", "saudade", "tears", "lágrimas", "empty", "vazio", "goodbye", "adeus"},
    "epic": {"fire", "fogo", "war", "guerra", "king", "rei", "rise", "erguer", "fight", "luta", "storm", "tempestade", "thunder"},
    "hopeful": {"light", "luz", "sun", "sol", "hope", "esperança", "rise", "levantar", "dream", "sonho", "free", "livre"},
    "dark": {"night", "noite", "shadow", "sombra", "fear", "medo", "blood", "sangue", "cold", "frio", "broken", "quebrado"},
    "dreamy": {"dream", "sonho", "sleep", "dormir", "float", "flutuar", "sky", "céu", "stars", "estrelas", "moon", "lua"},
}


def normalize_token(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in value if not unicodedata.combining(char))


def lyric_key(text: str) -> str:
    value = normalize_token(text)
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return " ".join(value.split())


def tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-zÀ-ÿ0-9']+", text.lower()) if token.strip("'")]


def keyword_counts(texts: list[str], limit: int = 24) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for text in texts:
        for token in tokens(text):
            normalized = normalize_token(token)
            if len(normalized) < 3 or token in STOPWORDS or normalized in STOPWORDS:
                continue
            if normalized.isdigit():
                continue
            counter[normalized] += 1
    return counter.most_common(limit)


def extract_keywords(texts: list[str], limit: int = 8) -> list[str]:
    return [word for word, _count in keyword_counts(texts, limit=limit)]


def simple_stem(word: str) -> str:
    word = normalize_token(word)
    for suffix in ("ing", "ers", "es", "ed", "er", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _stem_set(texts: list[str]) -> set[str]:
    return {simple_stem(token) for text in texts for token in tokens(text)}


def _keyword_present(keyword: str, stems: set[str], combined: str) -> bool:
    keyword = normalize_token(keyword)
    if " " in keyword:
        return keyword in combined
    return simple_stem(keyword) in stems


def detect_motifs(texts: list[str], limit: int = 5) -> list[str]:
    combined = " ".join(normalize_token(text) for text in texts)
    stems = _stem_set(texts)
    scored: list[tuple[int, str]] = []
    for motif, (words, _location, _noun) in MOTIF_RULES.items():
        score = sum(1 for word in words if _keyword_present(word, stems, combined))
        if score:
            scored.append((score, motif))
    scored.sort(reverse=True)
    return [motif for _score, motif in scored[:limit]]


def motif_location(motif: str) -> str:
    return MOTIF_RULES.get(motif, ("", "a cinematic landscape", "a cinematic landscape"))[1]


def motif_subject(motif: str) -> str:
    return MOTIF_RULES.get(motif, ("", "", "a lone figure"))[2]


def infer_mood(texts: list[str], energy: float = 0.5) -> str:
    combined = " ".join(normalize_token(text) for text in texts)
    stems = _stem_set(texts)
    scores: dict[str, int] = {}
    for mood, words in MOOD_WORDS.items():
        scores[mood] = sum(1 for word in words if _keyword_present(word, stems, combined))
    positive = sum(1 for word in POSITIVE_WORDS if _keyword_present(word, stems, combined))
    negative = sum(1 for word in NEGATIVE_WORDS if _keyword_present(word, stems, combined))
    if energy > 0.72 and scores.get("epic", 0) >= 1:
        return "epic"
    if positive > negative + 1:
        scores["hopeful"] = scores.get("hopeful", 0) + positive
    elif negative > positive:
        scores["melancholic"] = scores.get("melancholic", 0) + negative
    if not any(scores.values()):
        if energy > 0.66:
            return "energetic"
        if energy < 0.3:
            return "introspective"
        return "dreamy"
    return max(scores, key=lambda key: scores[key])


MOOD_LIGHTING = {
    "romantic": "warm amber light, soft halation, intimate close framing",
    "melancholic": "cool blue overcast light, soft rain haze, quiet negative space",
    "epic": "dramatic god rays, deep contrast, monumental scale",
    "hopeful": "golden sunrise light, glowing atmosphere, open horizon",
    "dark": "low-key chiaroscuro, deep shadows, single cold light source",
    "dreamy": "pastel diffusion, floating light motes, soft focus",
    "energetic": "vivid colour contrast, dynamic streaks of light, high energy",
    "introspective": "muted natural light, shallow focus, still atmosphere",
}

MOOD_COLOURS = {
    "romantic": ("#1B1320", "#5C2A3E", "#C86B85", "#F2B6A0", "#FFE2C4"),
    "melancholic": ("#0A1018", "#1C2A3A", "#426178", "#8FA8B7", "#DCE6E8"),
    "epic": ("#0D0B08", "#2E1D12", "#7A3E1D", "#D68A3C", "#F5D9A0"),
    "hopeful": ("#10202A", "#285664", "#5FA6A0", "#E8C07A", "#FFF0D0"),
    "dark": ("#050506", "#17131C", "#3B2A44", "#7A5A77", "#C7A6B8"),
    "dreamy": ("#1A1830", "#413A68", "#8A7BB8", "#D6B8E0", "#F7E7EE"),
    "energetic": ("#0C0617", "#391A54", "#B3246B", "#FF7A45", "#FFE261"),
    "introspective": ("#101210", "#283129", "#5A6553", "#A89C7B", "#E7E0CE"),
}


def mood_lighting(mood: str) -> str:
    return MOOD_LIGHTING.get(mood, "cinematic natural light")


def mood_colours(mood: str) -> tuple[str, ...]:
    return MOOD_COLOURS.get(mood, MOOD_COLOURS["dreamy"])


def summarize(texts: list[str], limit: int = 160) -> str:
    value = " / ".join(part.strip() for part in texts if part.strip())
    return value[: limit - 1] + "…" if len(value) > limit else value


def extract_names(texts: list[str]) -> list[str]:
    """Find capitalised words that look like proper names, ignoring first words."""
    found: list[str] = []
    for text in texts:
        words = re.findall(r"\b[A-ZÀ-Ý][a-zà-ÿ]{2,}\b", text)
        for word in words:
            normalized = normalize_token(word)
            if normalized in STOPWORDS or word.lower() in STOPWORDS:
                continue
            if word not in found:
                found.append(word)
    return found[:4]
