from eva.search import SearchDetector


def test_search_detector_triggers_for_current_lookup() -> None:
    decision = SearchDetector().should_search("what is the latest Python 3.12 release")
    assert decision.should_search is True


def test_search_detector_triggers_for_world_superlative_question() -> None:
    decision = SearchDetector().should_search("who is the oldest person in the world rn")
    assert decision.should_search is True


def test_search_detector_triggers_for_person_superlative_question() -> None:
    decision = SearchDetector().should_search("who is the oldest person rn")
    assert decision.should_search is True


def test_search_detector_does_not_trigger_for_creative_prompt() -> None:
    decision = SearchDetector().should_search("write a poem about apples")
    assert decision.should_search is False


def test_search_detector_does_not_trigger_for_channel_question() -> None:
    decision = SearchDetector().should_search("who said that in this chat")
    assert decision.should_search is False
