from app.scrapers.base import classify_model, is_target_gpu, parse_brl


def test_parse_brl():
    assert parse_brl("R$ 9.499,90") == 9499.90
    assert parse_brl("R$ 12.345,67") == 12345.67
    assert parse_brl("R$9499,90") == 9499.90
    assert parse_brl("9499") == 9499.0
    assert parse_brl("") is None
    assert parse_brl("sem preço") is None


def test_classify_model_5080():
    assert classify_model("Placa de Vídeo RTX 5080 Galax 1-Click OC 16GB GDDR7") == "rtx5080"
    assert classify_model("GeForce RTX5080 ASUS TUF Gaming OC") == "rtx5080"
    assert classify_model("NVIDIA GeForce RTX™ 5080 16GB GDDR7") == "rtx5080"
    assert classify_model("GeForce RTX-5080 OC Edition") == "rtx5080"


def test_classify_model_5090():
    assert classify_model("Placa de Vídeo RTX 5090 ASUS ROG Astral 32GB") == "rtx5090"
    assert classify_model("GeForce RTX5090 Gigabyte Aorus Master") == "rtx5090"
    assert classify_model("MSI GeForce RTX™ 5090 32GB GDDR7") == "rtx5090"


def test_classify_model_rejects_other_models_and_accessories():
    assert classify_model("Placa de Vídeo RTX 5070 Ti 16GB") is None
    assert classify_model("Placa de Vídeo RTX 5060 8GB") is None
    assert classify_model("Water Block Bykski para RTX 5090") is None
    assert classify_model("PC Gamer Intel i9 com RTX 5090") is None
    assert classify_model("Notebook Gamer RTX 5080 Mobile") is None
    assert classify_model("Suporte para placa de vídeo RTX 5080") is None
    assert classify_model("Cabo adaptador 12VHPWR para RTX 5090") is None


def test_is_target_gpu():
    assert is_target_gpu("GeForce RTX 5080 TUF")
    assert is_target_gpu("GeForce RTX 5090 ROG")
    assert not is_target_gpu("GeForce RTX 5070 Ti")
    assert not is_target_gpu("Mousepad RTX 5090")
