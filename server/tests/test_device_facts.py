from __future__ import annotations

from andy.device import DeviceState, _spoken_duration, _touched_zones


class Bare(DeviceState):
    """A DeviceState with states set directly, and no connection behind it."""

    def __init__(self, states: dict) -> None:  # noqa: D107
        super().__init__(client=None)  # type: ignore[arg-type]
        self._states = states


def facts(states: dict) -> dict:
    return Bare(states).interpreted()


def test_andy_can_say_what_day_and_time_it_is() -> None:
    """A desk robot that cannot answer this has no excuse.

    Nothing told the agent the time, so it said it did not know.
    """
    result = facts({})
    assert result["date_today"]
    assert result["time_now"]
    assert any(m in result["time_now"] for m in ("am", "pm"))


def test_proximity_is_reported_as_its_own_reach() -> None:
    result = facts({"presence": False})
    assert result["someone_close_to_me"] is False
    assert "someone_present" not in result


def test_the_head_is_described_in_words_not_servo_steps() -> None:
    assert facts({"motion_yaw_position": 466.0})["head_pointing"] == "straight ahead"
    assert facts({"motion_yaw_position": 381.0})["head_pointing"] == "to its left"
    assert facts({"motion_yaw_position": 552.0})["head_pointing"] == "to its right"
    tilted = facts({"motion_yaw_position": 466.0, "motion_pitch_position": 705.0})
    assert tilted["head_pointing"] == "straight ahead, tilted up"


def test_a_hand_on_the_head_is_located() -> None:
    assert _touched_zones("No touch", "No touch", "No touch") is None
    assert _touched_zones("Touch", "No touch", "Touch") == "left, right"
    assert (
        facts({"head_touch_centre": "Touch"})["where_on_the_head"] == "centre"
    )


def test_time_awake_is_spoken_not_counted() -> None:
    assert _spoken_duration(5) == "5 seconds"
    assert _spoken_duration(600) == "10 minutes"
    assert _spoken_duration(7_200) == "2 hours"
    assert _spoken_duration(400_000) == "4 days"
    assert facts({"uptime": 3_600.0})["awake_for"] == "60 minutes"


def test_warmth_and_signal_are_judged_not_reported() -> None:
    assert "comfortable" in facts({"pmic_temperature": 40.0})["how_warm_andy_is"]
    assert "hot" in facts({"pmic_temperature": 80.0})["how_warm_andy_is"]
    assert facts({"wi-fi_signal": -51.0})["wifi"] == "strong"
    assert facts({"wi-fi_signal": -80.0})["wifi"] == "weak"


def test_hardware_detail_stays_out_of_every_turn() -> None:
    """Forty numbers in front of the model on every turn is forty ignored."""
    states = {
        "motion_yaw_temperature": 21.0,
        "body_power": 0.5,
        "heap_free": 74_400.0,
        "motion_faults": 0.0,
        "voice_errors": 0.0,
        "acceleration_y": 0.92,
    }
    everyday = facts(states)
    for hidden in ("free_memory", "drawing_power", "neck_motors", "upright"):
        assert hidden not in everyday

    deep = Bare(states).diagnostics()
    assert deep["neck_motors"].startswith("21 degrees")
    assert deep["free_memory"] == "72 kilobytes"
    assert deep["anything_gone_wrong"] == "no"
    assert deep["upright"] is True


def test_a_fault_is_reported_rather_than_smoothed_over() -> None:
    deep = Bare({"motion_faults": 2.0, "voice_errors": 1.0}).diagnostics()
    assert "2 movement faults" in deep["anything_gone_wrong"]


def test_being_tipped_over_is_visible() -> None:
    assert Bare({"acceleration_y": 0.1}).diagnostics()["upright"] is False


def test_the_part_of_the_day_comes_from_the_sky_not_the_clock() -> None:
    """Eight in the evening is daylight in June and dark in December.

    The robot knows where it is and works out the sun's elevation, so the sky
    decides and the hour only says which side of noon it is.
    """
    from andy.device import _part_of_day

    # Deep night, whatever the hour claims.
    assert _part_of_day(20, -25.0, False) == "night"
    assert _part_of_day(5, -25.0, False) == "night"
    # The sun is just at the horizon: which side of noon names it.
    assert _part_of_day(6, 1.0, True) == "around sunrise"
    assert _part_of_day(19, 1.0, True) == "around sunset"
    # High sun: the ordinary names.
    assert _part_of_day(9, 40.0, True) == "morning"
    assert _part_of_day(14, 40.0, True) == "afternoon"
    assert _part_of_day(19, 20.0, True) == "evening"


def test_without_a_sun_reading_the_clock_still_answers() -> None:
    """A robot with no position must not lose the ability to say 'morning'."""
    from andy.device import _part_of_day

    assert _part_of_day(9, None, None) == "morning"
    assert _part_of_day(14, None, None) == "afternoon"
    assert _part_of_day(21, None, None) == "evening"
    assert _part_of_day(21, None, False) == "night"


def test_the_sun_reaches_the_everyday_facts() -> None:
    result = facts(
        {
            "sun_elevation": -20.0,
            "daylight": False,
            "next_sunrise": "05:51",
            "next_sunset": "19:03",
        }
    )
    assert result["part_of_day"] == "night"
    assert result["daylight_outside"] is False
    assert result["sun_next"] == "rises 05:51, sets 19:03"


def test_an_unlocated_robot_says_nothing_about_the_sun() -> None:
    """The robot withholds sun readings until it knows where it is.

    Latitude zero gives a real-looking sunrise for the Gulf of Guinea, so the
    firmware publishes none of it until the position is learned. Here that
    shows up as absent states, and the hour has to answer on its own.
    """
    unlocated = facts({})
    assert "sun_next" not in unlocated
    assert "daylight_outside" not in unlocated
    assert "where_andy_is" not in unlocated
    assert unlocated["part_of_day"] in {
        "morning", "afternoon", "evening", "night"
    }


def test_once_located_the_sun_is_used_and_andy_knows_the_place() -> None:
    located = facts(
        {
            "sun_elevation": -20.0,
            "daylight": False,
            "next_sunrise": "05:55",
            "next_sunset": "18:48",
            "where_andy_is": "Sharjah",
        }
    )
    assert located["part_of_day"] == "night"
    assert located["sun_next"] == "rises 05:55, sets 18:48"
    assert located["where_andy_is"] == "Sharjah"


def test_the_weather_reaches_the_everyday_facts() -> None:
    """Andy reads it for himself from his own position."""
    result = facts({"weather_summary": "Haze, 32 degrees, feels like 40, humidity 74%"})
    assert result["weather_outside"].startswith("Haze")


def test_no_weather_reading_is_absent_rather_than_invented() -> None:
    assert "weather_outside" not in facts({})


def test_the_weather_numbers_stay_out_of_every_turn() -> None:
    """The spoken summary is the everyday fact; the numbers are on request."""
    states = {
        "weather_summary": "Haze, 32 degrees, feels like 40, humidity 74%",
        "outside_temperature": 32.0,
        "outside_feels_like": 40.0,
        "outside_humidity": 74.0,
    }
    everyday = facts(states)
    assert "outside_temperature" not in everyday

    deep = Bare(states).diagnostics()
    assert deep["outside_temperature"] == "32 degrees"
    assert deep["outside_humidity"] == "74 percent"
