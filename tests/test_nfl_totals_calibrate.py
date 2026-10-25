from sharp_scout.nfl.totals.calibrate import walk_forward_total_bias


def test_walk_forward_bias_corrects_low_sim():
    # Sim systematically 5 pts low vs finals
    hist_sim = [40.0] * 10
    hist_fin = [45.0] * 10
    bias = walk_forward_total_bias(hist_sim, hist_fin, min_history=10)
    assert bias == -5.0
    assert 40.0 - bias == 45.0
