"""Prompt assembly: page separators and version stamp."""
from mmh_discovery.extractor.prompt import PROMPT_VERSION, SYSTEM, user_prompt


def test_user_prompt_contains_page_separators():
    pages = [
        ("https://example.org/", "<html>home</html>"),
        ("https://example.org/contact", "<html>contact</html>"),
    ]
    prompt = user_prompt(pages)
    assert "--- page: https://example.org/ ---" in prompt
    assert "--- page: https://example.org/contact ---" in prompt
    home_pos = prompt.index("<html>home</html>")
    contact_sep = prompt.index("--- page: https://example.org/contact ---")
    assert home_pos < contact_sep
    assert prompt.count("--- page:") == 2


def test_system_prompt_states_verbatim_rule_and_schema():
    assert "VERBATIM" in SYSTEM
    for key in ("emails", "phones", "socials", "contact_forms", "raw_context"):
        assert key in SYSTEM


def test_prompt_version_is_stamped():
    # exact value will bump over time; the stamp format (llm:{version}) is the contract
    assert PROMPT_VERSION.startswith("v") and PROMPT_VERSION[1:].isdigit()
