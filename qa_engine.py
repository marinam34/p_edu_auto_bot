import os, numpy as np
from typing import List
from config import OPENROUTER_API_KEY
from openai import OpenAI
from langchain_community.embeddings import HuggingFaceEmbeddings


DATA_DIR      = "data"
SUPPORT_FILE  = os.path.join(DATA_DIR, "support_info.txt")

ROLE_TO_FILE = {
    "Администратор": "admin.txt",
    "Участник":      "student.txt",
    "Проктор":       "proctor.txt",
    "Менеджер":      "manager.txt",
    "Другое":        "student.txt",
    "Не указано":    "student.txt",
}

TOP_K_SUPPORT = 20

_instruction_cache: dict[str, str] = {}
_support_cache = {
    "mtime": None,
    "entries": [],
    "embeddings": None,
}


embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

def _embed_texts(texts: List[str]) -> np.ndarray:
    """Список строк → [n, dim]"""
    return np.asarray(embedding_model.embed_documents(texts), dtype=np.float32)

def _embed_query(text: str) -> np.ndarray:
    return np.asarray(embedding_model.embed_query(text), dtype=np.float32)


def _instr_path(role: str) -> str:
    return os.path.join(DATA_DIR, ROLE_TO_FILE.get(role, "student.txt"))

def _load_instruction(role: str) -> str:
    path = _instr_path(role)
    if path not in _instruction_cache:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Файл инструкции отсутствует: {path}")
        with open(path, "r", encoding="utf-8") as f:
            _instruction_cache[path] = f.read()
    return _instruction_cache[path]


def _parse_support_file(raw: str) -> List[str]:
    return [c.strip() for c in raw.split("---\n") if c.strip()]

def _ensure_support_cache():
    mtime = os.path.getmtime(SUPPORT_FILE) if os.path.exists(SUPPORT_FILE) else None
    if mtime is None:
        _support_cache.update({"mtime": None, "entries": [], "embeddings": None})
        return
    if _support_cache["mtime"] == mtime:
        return

    with open(SUPPORT_FILE, "r", encoding="utf-8") as f:
        raw = f.read()

    entries = _parse_support_file(raw)
    embeddings = _embed_texts(entries) if entries else None
    _support_cache.update({"mtime": mtime, "entries": entries, "embeddings": embeddings})

def _top_k_support(question: str, k: int = TOP_K_SUPPORT) -> str:
    _ensure_support_cache()
    entries, embeddings = _support_cache["entries"], _support_cache["embeddings"]
    if not entries:
        return ""

    q_vec   = _embed_query(question)
    norms_e = np.linalg.norm(embeddings, axis=1)
    norm_q  = np.linalg.norm(q_vec) + 1e-9
    sims    = (embeddings @ q_vec) / (norms_e * norm_q)
    top_idx = sims.argsort()[-k:][::-1]
    return "\n---\n".join(entries[i] for i in top_idx)


def add_support_entry(question: str, answer: str):

    entry = f"Вопрос: {question}\nОтвет: {answer}"
    os.makedirs(os.path.dirname(SUPPORT_FILE), exist_ok=True)
    with open(SUPPORT_FILE, "a", encoding="utf-8") as f:
        f.write(entry + "\n---\n")

    vec = _embed_texts([entry])[0]
    if _support_cache["entries"]:
        _support_cache["entries"].append(entry)
        _support_cache["embeddings"] = (
            np.vstack([_support_cache["embeddings"], vec])
            if _support_cache["embeddings"] is not None else vec[None, :]
        )
    else:
        _support_cache["entries"]    = [entry]
        _support_cache["embeddings"] = vec[None, :]

    _support_cache["mtime"] = os.path.getmtime(SUPPORT_FILE)


client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

def get_answer(question: str, user_role: str = "Другое") -> str:
    instruction_text = _load_instruction(user_role)
    support_context  = _top_k_support(question, TOP_K_SUPPORT)

    prompt = f"""\
Ты — помощник компании ProctorEdu. Используй инструкцию и похожие ответы из техподдержки.
Только если не можешь найти ответ на вопрос там, то начинай думать сам. Если взял ответ из ответов тех поддрежки, то скажи что ответ согласно информации от тех поддрежки. Если взял из инструкции тоже скажи об этом.

ИНСТРУКЦИЯ:
\"\"\"{instruction_text}\"\"\"

ОТВЕТЫ ТЕХ ПОДДЕРЖКИ НА ПОХОЖИЕ ВОПРОСЫ:
\"\"\"{support_context}\"\"\"

ВОПРОС:
\"\"\"{question}\"\"\"

ОТВЕТ:"""

    try:
        completion = client.chat.completions.create(
            model="deepseek/deepseek-chat-v3-0324:free",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Ошибка генерации ответа: {e}"
