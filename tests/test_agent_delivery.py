from brandpilot.naming import asset_name


def test_asset_name_unique_and_readable():
    a, b = asset_name("poster_v1.png"), asset_name("poster_v1.png")
    assert a != b
    for n in (a, b):
        assert n.startswith("poster_v1-") and n.endswith(".png")
