import pytest
from resolver import resolve_symbol

@pytest.mark.parametrize("inp,exp", [
    ("PETR4", "PETR4.SA"),
    ("petr4", "PETR4.SA"),
    ("VALE3", "VALE3.SA"),
    ("IVVB11", "IVVB11.SA"),
    ("AAPL", "AAPL"),
    ("BOVA11", "BOVA11.SA"),
])
def test_symbol_resolution(inp, exp):
    raw, resolved = resolve_symbol(inp)
    assert resolved.symbol == exp

