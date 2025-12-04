import random
import string

from app.runner.assertions import AssertionEngine


def random_string():
    return "".join(random.choice(string.ascii_letters) for _ in range(random.randint(3, 12)))


def test_assertion_engine_handles_random_payloads():
    engine = AssertionEngine()
    values = [random.randint(0, 100) for _ in range(10)]

    for _ in range(50):
        values.append(random.randint(0, 100))
        expected = random.choice(values)
        actual = random.choice(values)
        context = {"node": {"response": actual}}
        engine.evaluate(
            [
                {
                    "id": random_string(),
                    "type": "equals",
                    "target": "node",
                    "expected": expected,
                    "message": "values should match",
                }
            ],
            context,
            [],
        )

    # No exceptions should be raised during fuzzing

