"""Generated documents with valid check digits, so no test holds a real CPF or CNPJ."""

import random


def fake_cpf(seed, leading_zero=False):
    rng = random.Random(seed)
    while True:
        d = [rng.randint(0, 9) for _ in range(9)]
        if leading_zero:
            d[0] = 0
        for size in (9, 10):
            d.append(sum(d[i] * (size + 1 - i) for i in range(size)) * 10 % 11 % 10)
        if len(set(d)) > 1:
            return "".join(map(str, d))


def fake_cnpj(seed):
    rng = random.Random(seed)
    d = [rng.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        rest = sum(d[i] * weights[i] for i in range(size)) % 11
        d.append(0 if rest < 2 else 11 - rest)
    return "".join(map(str, d))
