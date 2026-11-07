#!/usr/bin/env python3
"""
AD1 Full XOR Sweep — Raphael Technique
Decrypts the entire AD1 image with key [0x23, 0x12, 0x2e, 0x3a]
and finds all clean HTB{...} flags.
Output: JSON lines to stdout.
"""
import json, os, re, sys, time
from pathlib import Path

# Repo-relative default with an env override. The previous value was an
# absolute path into the author's machine; challenge_1245 is engagement
# data and is not committed.
_REPO_ROOT = Path(__file__).resolve().parents[3]
AD1_PATH = os.environ.get(
    "AD1_PATH",
    str(_REPO_ROOT / "challenge_1245" / "invisible-theft.ad1"),
)
XOR_KEY = bytes([0x23, 0x12, 0x2e, 0x3a])


def xor_decrypt(data: bytes) -> bytes:
    return bytes(data[i] ^ XOR_KEY[i % 4] for i in range(len(data)))


def is_clean_flag(flag_str: str) -> bool:
    """A clean flag has high letter ratio, very few control/special chars."""
    inner = flag_str[4:-1]  # between HTB{ and }
    if len(inner) < 4:
        return False
    letters = sum(1 for c in inner if c.isalpha())
    controls = sum(1 for c in inner if ord(c) < 0x20 or ord(c) > 0x7E)
    total = len(inner)
    letter_ratio = letters / total
    control_ratio = controls / total
    return letter_ratio > 0.35 and control_ratio < 0.05


def main():
    start = time.time()
    print(json.dumps({"event": "start", "path": AD1_PATH, "key": list(XOR_KEY)}))

    if not os.path.isfile(AD1_PATH):
        print(json.dumps({
            "event": "error",
            "error": f"AD1 image not found: {AD1_PATH}",
            "hint": "set AD1_PATH to the engagement image, or place it at "
                    "challenge_1245/invisible-theft.ad1 in the checkout",
        }))
        return 2

    with open(AD1_PATH, "rb") as f:
        data = f.read()
    
    size_mb = len(data) / (1024 * 1024)
    print(json.dumps({"event": "reading", "size_mb": round(size_mb, 1)}))
    
    # XOR-decrypt the entire file
    decrypted = xor_decrypt(data)
    
    elapsed = time.time() - start
    print(json.dumps({"event": "decrypted", "elapsed_s": round(elapsed, 1), "size_mb": round(size_mb, 1)}))
    
    # Find all HTB{...} patterns
    flags_found = []
    for m in re.finditer(rb'HTB\{[^}]{3,80}\}', decrypted):
        flag_bytes = m.group()
        try:
            flag_str = flag_bytes.decode("ascii")
        except UnicodeDecodeError:
            continue
        
        if is_clean_flag(flag_str):
            offset = m.start()
            flags_found.append({"flag": flag_str, "offset": offset})
    
    # Deduplicate
    seen = set()
    unique = []
    for f in flags_found:
        if f["flag"] not in seen:
            seen.add(f["flag"])
            unique.append(f)
    
    total_time = time.time() - start
    
    result = {
        "event": "complete",
        "total_flags": len(unique),
        "elapsed_s": round(total_time, 1),
        "flags": [f["flag"] for f in unique],
        "offsets": [f["offset"] for f in unique]
    }
    
    print(json.dumps(result))
    
    # Also write flags to a file for the brain to pick up
    if unique:
        with open("/tmp/ad1_flags_found.txt", "w") as of:
            for f in unique:
                of.write(f["flag"] + "\n")
    
    return 0 if unique else 1


if __name__ == "__main__":
    sys.exit(main())
