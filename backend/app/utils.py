import random
import string


def generate_key_value() -> str:
    parts = []
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(4):
        part = "".join(random.choices(alphabet, k=5))
        parts.append(part)
    return "MPH-" + "-".join(parts)

