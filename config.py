import os

BASE_DIR = "/Volumes/HIKSEMI/world-model-research"
DB_PATH  = os.path.join(BASE_DIR, "papers.db")
PDF_DIR  = os.path.join(BASE_DIR, "pdfs")

# AI interface (OpenAI-compatible)
LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_API_KEY  = "sk-c32c17f206eb42b2a065d166f34a51b0"
LLM_MODEL    = "qwen-plus"

# Semantic Scholar (optional — higher rate limit with key)
S2_API_KEY = ""

TARGET_VENUES = ["neurips", "icml", "iclr", "cvpr", "corl"]
YEAR_RANGE    = (2021, 2026)

KEYWORDS = [
    # Core world model terms
    "world model",
    "generative world model",
    "world foundation model",
    "visual world model",
    "driving world model",
    "embodied world model",
    # Visual generation
    "video diffusion",
    "text-to-video",
    "video generation",
    "4D generation",
    "cosmos world model",
    "hunyuan",
    # RL-based (lower priority but still collected)
    "model-based RL",
    "video prediction world model",
    "dreamer",
    "PlaNet",
    "TD-MPC",
]
