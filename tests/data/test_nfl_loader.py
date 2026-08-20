from src.data.historical import nfl_loader


def test_loader_uses_nflreadpy_schedule_and_drops_unplayed(monkeypatch):
    class Frame:
        def to_dicts(self):
            return [
                {"season": 2024, "week": 1, "gameday": "2024-09-08", "home_team": "KC", "away_team": "BAL", "home_score": 27, "away_score": 20},
                {"season": 2024, "week": 2, "gameday": "2024-09-15", "home_team": "KC", "away_team": "CIN", "home_score": None, "away_score": None},
            ]

    class Nfl:
        def load_schedules(self, seasons):
            assert seasons == [2024]
            return Frame()

    monkeypatch.setattr(nfl_loader, "_nflreadpy", lambda: Nfl())
    rows = nfl_loader.load_games([2024])
    assert len(rows) == 1
    assert rows[0]["home_team_name"] == "KC"
