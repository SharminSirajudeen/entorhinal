"""Every fixed value, in one place. Prices: Nebius Token Factory's public catalog
(tokenfactory.nebius.com/api/public/models_info), read 28 Oct 2026."""

LIGHTNING = "nvidia/Nemotron-3_5-Lightning"
SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"

# $ per 1M tokens: input, cached input, output
PRICES = {
    LIGHTNING: (0.06, 0.03, 0.24),
    SUPER: (0.30, 0.06, 0.90),
    ULTRA: (1.00, 0.12, 3.00),
}

# The change judge decides which old facts a session makes untrue. On two pilot sessions Ultra found the changed fact
# 2/2 but used 11,832 of 12,000 output tokens on a 326-fact memory (a larger one truncates and nothing goes stale), at
# $0.0485 / $0.0283 a call; Super found 1/2 at $0.0082 / $0.0049. n = 2 is not a quality comparison.
S6_MODEL = SUPER
DAILY_CAP_USD = 0.80  # the hosted demo refuses new work once the day's spend would pass this
