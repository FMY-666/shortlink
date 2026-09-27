ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)


def base62(n: int) -> str:
    if n < 0:
        raise ValueError("id 不能是负数")
    if n == 0:
        return ALPHABET[0]

    out = []
    while n > 0:
        n, rem = divmod(n, BASE)
        out.append(ALPHABET[rem])
    return "".join(reversed(out))


def make_code(n: int, length: int = 6) -> str:
    return base62(n).rjust(length, ALPHABET[0])