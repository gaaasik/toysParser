import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from main import validate_and_normalize, validate_schema, load_schema


def test_validate_and_normalize_basic(tmp_path):
    sku = "ABC123"
    obj = {
        "Артикул": sku,
        "Наименование товара": "Фильтр масляный Brand ABC123",
        "Описание товара": "Назначение: фильтрация масла. Применение: двигатели Brand.",
        "Марка": "Brand",
        "Модель": ["Model A", "Model B"],
    }
    normalized = validate_and_normalize(obj, sku)
    assert normalized["Артикул"] == sku
    assert isinstance(normalized["Модель"], list) and len(normalized["Модель"]) == 2


def test_validate_and_normalize_missing_fields():
    sku = "XYZ999"
    obj = {}
    normalized = validate_and_normalize(obj, sku)
    assert normalized["Артикул"] == sku
    assert "не найден" in normalized["Наименование товара"]
    assert normalized["Модель"] == ["нет данных"]


def test_schema_validation(tmp_path):
    schema = load_schema()
    valid_obj = {
        "Артикул": "123",
        "Наименование товара": "Колодки тормозные Brand 123",
        "Описание товара": "Назначение → Тех.характеристики → Преимущества → Применение",
        "Марка": "Brand",
        "Модель": ["A", "B"],
        "Источники": ["https://example.com"]
    }
    # Should pass through validate_schema unchanged
    checked = validate_schema(valid_obj)
    assert checked.get("schema_error") is None

    invalid_obj = {
        "Артикул": "",
        "Наименование товара": "",
        "Описание товара": "",
        "Марка": "",
        "Модель": [],
    }
    checked2 = validate_schema(invalid_obj)
    assert "schema_error" in checked2
