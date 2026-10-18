"""A deliberately failing unit test (task 6.3): it proves the Jenkins pipeline turns red when a unit test fails.

It is committed once, its build must be FAILURE because of this test, and a revert commit removes it.
"""


def test_ci_turns_red_on_a_failing_unit_test():
    assert 1 + 1 == 3, "deliberate failure to verify that the pipeline reports a failed build"
