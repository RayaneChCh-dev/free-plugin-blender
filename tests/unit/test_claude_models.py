from fpb import claude_models


def test_ids_are_exact_claude_model_ids():
    ids = [key for key, _label, _text in claude_models.MODELS]
    assert ids[:6] == ["claude-opus-5-5", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5-5",
                       "claude-sonnet-5", "claude-haiku-5-5"]
    assert claude_models.DEFAULT_MODEL == "claude-opus-5-5"


def test_effort_levels_and_default():
    assert [key for key, *_ in claude_models.EFFORTS] == ["low", "medium", "high", "xhigh", "max"]
    assert claude_models.DEFAULT_EFFORT == "medium"


def test_cli_arguments():
    assert claude_models.cli_arguments("claude-sonnet-5-5", "high") == ["--model", "claude-sonnet-5-5",
                                                                      "--effort", "high"]
    assert claude_models.cli_arguments("DEFAULT", "medium") == ["--effort", "medium"]
    assert claude_models.cli_arguments("claude-opus-5-5", "bogus") == ["--model", "claude-opus-5-5"]


def test_labels():
    assert claude_models.model_label("claude-haiku-5-5") == "Haiku 5.5"
    assert claude_models.effort_label("xhigh") == "XHigh"
    assert claude_models.model_label("unknown") == "unknown"
