# backend/utils/bitnet_singleton.py
import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# Project root
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))

# Your local path:  .../models/microsoft/bitnet-b1.58-2B-4T
LOCAL_MODEL_DIR = os.path.join(ROOT_DIR, "models", "microsoft", "bitnet-b1.58-2B-4T")

# Fallback HF repo id (only used if local dir not found)
REMOTE_MODEL_ID = os.getenv("BITNET_MODEL_ID", "microsoft/bitnet-b1.58-2B-4T")

_tokenizer = None
_model = None

def _pick_device():
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"

def _torch_dtype_for(device: str):
    # MPS works best with float16; others use bfloat16
    return torch.float16 if device == "mps" else torch.bfloat16

def _load_from_source(src: str, device: str, local: bool):
    kwargs = dict(torch_dtype=_torch_dtype_for(device))
    if local:
        kwargs["local_files_only"] = True

    tokenizer = AutoTokenizer.from_pretrained(src, trust_remote_code=False, **({"local_files_only": True} if local else {}))
    if tokenizer.pad_token_id is None and tokenizer.eos_token is not None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(src, **kwargs)
    if device != "cpu":
        model = model.to(device)

    # Ensure PAD/EOS in generation config
    if model.generation_config.pad_token_id is None and tokenizer.pad_token_id is not None:
        model.generation_config.pad_token_id = tokenizer.pad_token_id
    if model.generation_config.eos_token_id is None and tokenizer.eos_token_id is not None:
        model.generation_config.eos_token_id = tokenizer.eos_token_id

    return tokenizer, model

def get_bitnet():
    """Returns (tokenizer, model, device), preferring local model dir if present."""
    global _tokenizer, _model
    if _model is not None:
        return _tokenizer, _model, _model.device.type

    device = _pick_device()
    if os.path.isdir(LOCAL_MODEL_DIR):
        src = LOCAL_MODEL_DIR
        local = True
    else:
        src = REMOTE_MODEL_ID
        local = False

    _tokenizer, _model = _load_from_source(src, device, local)
    return _tokenizer, _model, device

def chat(
    messages,
    max_new_tokens=256,
    temperature=0.7,
    top_p=0.95,
    do_sample=True,
):
    """
    Chat wrapper. `messages`: [{"role":"system","content":"..."}, {"role":"user","content":"..."}]
    """
    tokenizer, model, _ = get_bitnet()

    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )
    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to(model.device) for k, v in inputs.items()}

    outputs = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=do_sample,
        temperature=temperature,
        top_p=top_p,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id,
    )

    start = inputs["input_ids"].shape[-1]
    new_tokens = outputs[0, start:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
