import pandas as pd

from sharp_scout.data.nflfastr import nfl_rating_plays


def test_nfl_rating_plays_drop_kneels_spikes_and_garbage_time():
    pbp = pd.DataFrame(
        {
            "play_type": ["pass", "run", "qb_kneel", "qb_spike", None, "pass"],
            "wp": [0.5, 0.6, 0.98, 0.4, 0.5, 0.97],
            "epa": [0.4, 0.1, -0.9, -0.5, 0.2, 1.2],
        }
    )
    assert nfl_rating_plays(pbp)["epa"].tolist() == [0.4, 0.1]
