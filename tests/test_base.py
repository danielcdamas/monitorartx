from app.scrapers.base import is_rtx5080_gpu, parse_brl


def test_parse_brl():
    assert parse_brl("R$ 9.499,90") == 9499.90
    assert parse_brl("R$ 12.345,67") == 12345.67
    assert parse_brl("R$9499,90") == 9499.90
    assert parse_brl("9499") == 9499.0
    assert parse_brl("") is None
    assert parse_brl("sem preço") is None


def test_is_rtx5080_gpu_accepts_cards():
    assert is_rtx5080_gpu("Placa de Vídeo RTX 5080 Galax 1-Click OC 16GB GDDR7")
    assert is_rtx5080_gpu("GeForce RTX5080 ASUS TUF Gaming OC")
    assert is_rtx5080_gpu("MSI GeForce RTX 5080 Ventus 3X OC 16GB")


def test_is_rtx5080_gpu_rejects_other_models_and_accessories():
    assert not is_rtx5080_gpu("Placa de Vídeo RTX 5070 Ti 16GB")
    assert not is_rtx5080_gpu("Water Block Bykski para RTX 5080")
    assert not is_rtx5080_gpu("PC Gamer Intel i9 com RTX 5080")
    assert not is_rtx5080_gpu("Notebook Gamer RTX 5080 Mobile")
    assert not is_rtx5080_gpu("Suporte para placa de vídeo RTX 5080")
    assert not is_rtx5080_gpu("Cabo adaptador 12VHPWR para RTX 5080")
