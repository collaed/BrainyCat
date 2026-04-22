"""Multilingual stopwords for TF-IDF embeddings.

Covers: EN, FR, DE, ES, IT, PT, RO, SV, NL, LU, ZH
Source: stopwords-iso (curated, machine-readable)
"""

# fmt: off
STOPWORDS: set[str] = {
    # English
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "this", "that", "was", "are",
    "be", "has", "had", "have", "not", "no", "as", "his", "her", "he",
    "she", "they", "their", "its", "my", "your", "our", "we", "you", "i",
    "me", "him", "us", "them", "who", "which", "what", "when", "where",
    "how", "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "than", "too", "very", "can", "will", "just", "do",
    "did", "does", "been", "being", "would", "could", "should", "may",
    "might", "shall", "about", "up", "out", "so", "if", "then", "into",
    "also", "only", "own", "same", "here", "there", "these", "those",
    "through", "during", "before", "after", "above", "below", "between",
    "under", "again", "further", "once", "why", "any", "because",
    # French
    "le", "la", "les", "un", "une", "des", "et", "en", "du", "au", "aux",
    "est", "que", "qui", "dans", "pour", "sur", "par", "avec", "ce", "se",
    "ne", "pas", "plus", "son", "sa", "ses", "nous", "vous", "ils", "elles",
    "leur", "leurs", "cette", "ces", "mon", "ton", "notre", "votre",
    "mais", "ou", "donc", "car", "ni", "si", "comme", "tout", "tous",
    "toute", "toutes", "autre", "autres", "même", "aussi", "bien",
    "encore", "entre", "vers", "chez", "sans", "sous", "depuis", "avant",
    "après", "pendant", "contre", "très", "peu", "trop", "assez",
    "fait", "faire", "dit", "été", "avoir", "être", "peut", "ont",
    # German
    "der", "die", "das", "ein", "eine", "und", "oder", "aber", "ist",
    "war", "sind", "hat", "haben", "wird", "werden", "kann", "können",
    "mit", "von", "zu", "auf", "für", "bei", "nach", "über",
    "aus", "um", "als", "wie", "wenn", "weil", "dass", "nicht", "kein",
    "keine", "noch", "nur", "auch", "schon", "sehr", "mehr", "viel",
    "ich", "er", "sie", "es", "wir", "ihr", "den", "dem", "sich", "sein", "seine", "seinem", "seinen", "seiner", "mein",
    "dein", "unser", "euer", "dieser", "diese", "dieses", "jeder",
    "jede", "jedes", "alle", "alles", "wer", "wo", "hier",
    "dort", "dann", "nun", "doch", "eben", "etwa", "ganz", "gar",
    # Spanish
    "el", "los", "las", "uno", "una", "unos", "unas", "del", "al",
    "era", "fue", "ser", "estar", "hay", "tiene", "puede",
    "con", "sin", "sobre", "hasta", "desde", "durante",
    "yo", "tu", "él", "ella", "nosotros", "ellos", "ellas", "nos",
    "te", "lo", "su", "sus", "mi", "mis",
    "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
    "aquel", "aquella", "todo", "toda", "todos", "todas", "otro", "otra",
    "otros", "otras", "mucho", "poco", "muy", "más", "menos", "tan",
    "como", "cuando", "donde", "porque", "pero", "sino", "aunque",
    # Italian
    "il", "gli", "dei", "degli", "delle", "della",
    "nel", "nella", "nei", "negli", "nelle", "sul", "sulla",
    "sui", "sugli", "sulle", "col", "coi", "dal", "dalla", "dai",
    "dagli", "dalle", "alla", "ai", "agli", "che", "chi", "cui", "non", "più", "anche", "solo", "già",
    "ancora", "sempre", "mai", "molto", "troppo", "tanto",
    "ogni", "tutto", "tutti", "tutta", "tutte", "altro", "altri",
    "altra", "altre", "questo", "questa", "questi", "queste",
    "quello", "quella", "quelli", "quelle", "suo", "sua", "suoi", "sue",
    "mio", "mia", "miei", "mie", "tuo", "tua", "tuoi", "tue",
    "nostro", "nostra", "nostri", "nostre", "vostro", "vostra",
    "loro", "sono", "stato", "stata", "stati", "state", "essere",
    "avere", "fare", "dire", "potere", "volere", "dovere",
    # Portuguese
    "os", "uma", "uns", "umas", "da", "dos", "na", "nas", "ao", "aos", "pelo", "pela", "pelos",
    "pelas", "num", "numa", "nuns", "numas", "com", "sem", "sob",
    "até", "para", "por", "em",
    "eu", "ele", "ela", "nós", "vós", "eles", "elas",
    "meu", "minha", "meus", "minhas", "teu", "teus", "tuas",
    "seu", "seus", "suas", "nosso", "nossa", "nossos", "nossas",
    "estes", "esse", "essa", "esses", "essas",
    "aquele", "aquela", "aqueles", "aquelas", "isto", "isso", "aquilo",
    "quem", "qual", "quais", "quanto", "quanta", "quantos",
    "mas", "porém", "contudo", "todavia", "entretanto", "pois", "quando", "onde", "enquanto", "embora", "não", "sim", "também", "ainda", "já", "nunca",
    "muito", "pouco", "bem", "mal", "assim",
    # Romanian
    "cel", "cea", "cei", "cele", "acest", "această", "acești", "aceste",
    "acel", "acea", "acei", "acele", "care", "cine", "unde", "când",
    "cum", "dar", "sau", "iar", "nici", "fie", "deci", "așadar",
    "prin", "spre", "din", "dintre", "până", "fără",
    "sunt", "fost", "avea", "face", "spune",
    "doar", "chiar", "încă", "deja", "mereu", "niciodată",
    "mult", "puțin", "foarte", "prea", "destul", "tot", "toți",
    # Swedish
    "och", "att", "det", "som", "för", "med", "har", "var",
    "inte", "till", "kan", "ska", "från", "vid", "efter", "över", "mellan", "utan", "genom", "mot", "hos", "bland",
    "jag", "han", "hon", "vi", "de", "sig",
    "min", "hans", "hennes", "vår", "deras", "sitt",
    "denna", "detta", "dessa", "vilken", "vilket", "vilka",
    "varje", "annan", "annat", "andra", "mycket", "lite",
    "mer", "mest", "mindre", "minst", "bara", "redan", "aldrig",
    # Dutch
    "het", "een", "van", "dat", "op", "aan", "met", "maar", "nog", "wel", "geen", "ook", "dan", "bij", "uit",
    "naar", "door", "om", "want", "dus", "toch", "ik", "je", "hij", "zij", "wij", "hen", "hun", "ons",
    "mijn", "jouw", "zijn", "haar", "onze", "jullie", "deze", "welk", "welke", "elk", "elke",
    "veel", "weinig", "meer", "meest", "minder", # Chinese (common function words — pinyin for matching)
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她",
    "们", "那", "里", "后", "来", "时", "大", "让", "把", "给",
    # Luxembourgish
    "déi", "eng", "awer", "ass", "sinn", "huet", "mat", "vun", "fir", "iwwer", "ëm", "wann", "well", "net", "keng", "nëmmen", "schonn", "ech", "dir", "hien", "mir", "mäin", "däin", "seng", "eisen", "hir",
}
# fmt: on
