import pytest

from app.maps import MAPS
from tools.render_map import render


@pytest.mark.parametrize("name", MAPS)
def test_every_map_renders_a_preview(name, tmp_path):
    out = render(name, tmp_path / f"{name}.png", nav=True, width=400)
    assert out.stat().st_size > 1000
