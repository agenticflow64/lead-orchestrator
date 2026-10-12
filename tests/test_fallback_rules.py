"""Unit tests for the deterministic regex fallback of the classifier."""

from app.classifier import classify_by_rules


def test_type_accuracy_on_dataset(dataset):
    correct = sum(1 for _, text, expected_type, _ in dataset if classify_by_rules(text)["type"] == expected_type)
    accuracy = correct / len(dataset)
    assert accuracy >= 0.9, f"type accuracy too low: {accuracy:.2f} ({correct}/{len(dataset)})"


def test_urgency_accuracy_on_dataset(dataset):
    correct = sum(
        1 for _, text, _, expected_urgency in dataset if classify_by_rules(text)["urgency"] == expected_urgency
    )
    accuracy = correct / len(dataset)
    assert accuracy >= 0.9, f"urgency accuracy too low: {accuracy:.2f} ({correct}/{len(dataset)})"


def test_complaint_vs_support_boundary():
    # No.8: emotions + money demand, but no technical failure -> complaint, not support.
    text = "Уже третью неделю жду ответа на моё обращение №1042! Это уже безобразие, требую вернуть деньги!"
    assert classify_by_rules(text)["type"] == "complaint"


def test_no_fields_invented():
    # No.7: neither name nor contact present -> empty strings, not guesses.
    result = classify_by_rules("Не могу войти в аккаунт, пишет «неверный пароль», хотя пароль точно верный.")
    assert result["type"] == "support"
    assert result["name"] == ""
    assert result["contact"] == ""


def test_unexpected_contact_format_extracted():
    # No.12: telegram handle inside the text body.
    result = classify_by_rules(
        "Предлагаю партнерство: у нас база клиентов, нужна ваша команда под интеграции. Пишите в tg @maketalk"
    )
    assert result["type"] == "partnership"
    assert result["contact"] == "@maketalk"


def test_partial_field_extraction():
    # No.3: name only, no contact.
    result = classify_by_rules("Есть прайс на месячное сопровождение? Нужно примерно, чтобы посчитать бюджет. Дмитрий")
    assert result["type"] == "price_question"
    assert result["name"] == "Дмитрий"
    assert result["contact"] == ""


def test_spam_urgency_always_low():
    result = classify_by_rules("Заработок из дома 5000р/день!!! Пиши скорее, мест мало!!!")
    assert result["type"] == "spam"
    assert result["urgency"] == "low"


def test_signature_with_email():
    result = classify_by_rules(
        "Здравствуйте! Сколько стоит интеграция с 1С? Александр, a.petrov@company.ru"
    )
    assert result["name"] == "Александр"
    assert result["contact"] == "a.petrov@company.ru"


def test_name_after_comma_with_capitalized_word():
    # "Жалоба, Сергей" -> the name is Сергей, not Жалоба.
    result = classify_by_rules("Качество работы оставляет желать лучшего, доделки не выполнены в срок. Жалоба, Сергей")
    assert result["name"] == "Сергей"


def test_summary_is_single_sentence():
    result = classify_by_rules("Сайт не открывается с телефона уже час, ошибка 500. Что делать? Срочно!")
    assert result["summary"].endswith(("500.", "!"))
    assert "\n" not in result["summary"]
