"""Score the labelled examples with the live decider and show where each lands.

    uv run scripts/calibrate.py [--threshold 0.5]

Use it after changing a gate question or the default threshold: every example should come
out with its expected decision, both as the first message and mid-conversation (after an
unrelated order reply), since a topic switch must not change the verdict.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from support.decider import DeciderClient, DeciderError  # noqa: E402
from support.examples import EXAMPLES  # noqa: E402
from support.gate import DEFAULT_SCOPE_THRESHOLD, assess, decide  # noqa: E402

MID_CONVERSATION = (
    "Your order A-1042 has shipped. It has the Vista 27-inch 4K monitor. It's with BlueDart "
    "(tracking number BD7731904IN). Estimated delivery is 25 Oct 2026."
)


async def main(threshold: float) -> int:
    client = DeciderClient()
    misses = runs = 0
    print(f"{'expect':13} {'got':13} {'when':5} {'scope':>6} {'follow':>6} message")
    try:
        for ex in EXAMPLES:
            contexts = [ex["context"]] if ex.get("context") else [None, MID_CONVERSATION]
            for context in contexts:
                result = await assess(client, ex["text"], context)
                v = decide(result["answers"], threshold)
                ok = v["decision"] == ex["expect"]
                misses += not ok
                runs += 1
                follow = "" if v["follow_up"] is None else f"{v['follow_up']:.3f}"
                print(f"{ex['expect']:13} {v['decision']:13} {'mid' if context else 'first':5} {v['in_scope']:6.3f} "
                      f"{follow:>6} {'' if ok else '<< '}{ex['text'][:55]}")
    except DeciderError as e:
        print(e)
        return 2
    finally:
        await client.aclose()
    print(f"\n{runs - misses}/{runs} as expected at threshold={threshold}")
    return 1 if misses else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--threshold", type=float, default=DEFAULT_SCOPE_THRESHOLD)
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.threshold)))
