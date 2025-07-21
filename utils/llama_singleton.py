# llama_singleton.py

import os
import contextlib
import io
from llama_cpp import Llama

# Resolve model path relative to project root
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "models", "llama-2-7b-chat.Q4_K_M.gguf"
)

# Singleton instance
_llm = None

def get_llm():
    """
    Returns a globally cached instance of the LLaMA model.
    Loads the model on first call only.
    Suppresses verbose loading output.
    """
    global _llm
    if _llm is None:
        with contextlib.redirect_stdout(io.StringIO()):
            _llm = Llama(
                model_path=MODEL_PATH,
                n_ctx=2048,
                n_threads=os.cpu_count(),
                verbose=False  # Suppresses internal logging
            )
    return _llm
