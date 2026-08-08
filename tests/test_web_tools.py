from agent.tools import (
    _has_cjk,
    extract_search_query,
    extract_weather_city,
    get_weather,
    get_current_time,
)


def test_has_cjk():
    assert _has_cjk("查一下天气") is True
    assert _has_cjk("search Paris weather") is False


def test_extract_weather_city_zh():
    assert extract_weather_city("查一下成都明天天气") == "成都"
    assert extract_weather_city("北京天气怎么样") == "北京"


def test_extract_weather_city_en():
    assert extract_weather_city("search Paris weather") == "Paris"
    assert extract_weather_city("What is the weather in London tomorrow?") == "London"
    assert extract_weather_city("weather in new york") == "New York"
    assert extract_weather_city("Paris weather") == "Paris"
    assert extract_weather_city("whats the forecast for Tokyo") == "Tokyo"


def test_extract_search_query_en():
    assert extract_search_query("search latest AI news") == "latest AI news"
    assert extract_search_query("please tell me about the new iPhone") == "the new iPhone"
    assert extract_search_query("google how to make pancakes") == "how to make pancakes"


def test_get_weather_formats():
    en = get_weather("Paris", lang="en")
    assert en
    assert "Today" in en
    assert "°C" in en

    zh = get_weather("成都", lang="zh")
    assert zh
    assert "℃" in zh


def test_get_current_time_langs():
    assert "年" in get_current_time("zh")
    assert get_current_time("en").startswith("20")
