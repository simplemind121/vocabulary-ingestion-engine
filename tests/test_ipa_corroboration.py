from app.services.ipa_corroboration import (
    ConfusionModel,
    corroborate,
    load_pronunciation_dictionary,
    to_book_notation,
)

READERS = ("a", "b")


def _model() -> ConfusionModel:
    """A book in which both readers print 'a' for schwa and drop length marks."""
    model = ConfusionModel(min_count=3, min_share=0.2)
    model.learn(
        [
            ("kәm'pәuz", {"a": "kampauz", "b": "kam'pauz"}),
            ("әb'dʒekt", {"a": "abd3ekt", "b": "ab'd3ekt"}),
            ("'melәdi", {"a": "meladi", "b": "'meladi"}),
            ("di:m", {"a": "dim", "b": "dim"}),
            ("ri:p", {"a": "rip", "b": "rip"}),
            ("fi:l", {"a": "fil", "b": "fil"}),
        ]
    )
    return model


def test_dictionary_form_is_accepted_when_every_reader_prints_its_usual_garble():
    outcome, stress_seen = corroborate(
        "kәn'sәlt", {"a": "kansalt", "b": "kan'salt"}, _model()
    )
    assert (outcome, stress_seen) == ("CORROBORATED", True)
    assert to_book_notation("kәn'sɒ:lt") == "kənˈsɔːlt"
    assert to_book_notation(".intә'lektʃuәl") == "ˌintəˈlektʃuəl"


def test_a_reader_that_prints_a_stable_letter_differently_contradicts_the_dictionary():
    # The book prints "inti…"; the dictionary says "intә…". Readers never turn
    # schwa into "i" in this book, so the dictionary form is not what is printed.
    model = _model()
    assert corroborate("intә'lekt", {"a": "intilekt", "b": "inti'lekt"}, model)[0] == (
        "READINGS_CONTRADICT_DICTIONARY"
    )
    # An extra printed sound the dictionary lacks is a contradiction too.
    assert corroborate("pri'zu:m", {"a": "prizjum", "b": "pri'zjum"}, model)[0] == (
        "READINGS_CONTRADICT_DICTIONARY"
    )


def test_stress_on_a_different_syllable_is_not_accepted():
    outcome, _ = corroborate("kәn'sәlt", {"a": "kansalt", "b": "'kansalt"}, _model())
    assert outcome == "STRESS_POSITION_DIFFERS"
    unseen = corroborate("kәn'sәlt", {"a": "kansalt", "b": "kansalt"}, _model())
    assert unseen == ("CORROBORATED", False)  # accepted, stress position unverified


def test_nothing_is_filled_in_without_a_dictionary_entry_or_a_second_reading():
    model = _model()
    assert corroborate(None, {"a": "x", "b": "x"}, model)[0] == "NO_DICTIONARY_ENTRY"
    assert corroborate("di:m", {"a": "dim"}, model)[0] == "FEWER_THAN_TWO_READINGS"


def test_rare_confusions_are_not_learned_as_normal_behaviour():
    model = ConfusionModel(min_count=3, min_share=0.2)
    model.learn([("әt", {"a": "at"})] * 9 + [("әt", {"a": "it"})])
    assert model.allowed("a", "ә", "a") is True
    assert model.allowed("a", "ә", "i") is False


def test_dictionary_loader_reads_word_and_phonetic_columns(tmp_path):
    path = tmp_path / "dictionary.csv"
    path.write_text(
        "word,phonetic,definition\nCompose,kәm'pәuz,x\nnophon,,y\ncompose,other,z\n",
        encoding="utf-8",
    )
    assert load_pronunciation_dictionary(path) == {"compose": "kәm'pәuz"}
