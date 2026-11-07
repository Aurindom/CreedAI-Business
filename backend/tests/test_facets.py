import pytest
from pydantic import ValidationError

from app import db
from app.matching import recommend
from app.schemas import BusinessProfile, Catalog, Facet, Fact, ProblemCard
from conftest import fact

CHANNEL = Facet(id="channel", label="Where it comes in", capabilities=["phone"], values={"voice": "voice calls", "chat": "website chat"})


def split(catalog, **stated):
    """Gives the fixture a channel split, a card that needs chat, and the stated channels per tool."""
    catalog.facets = [CHANNEL]
    catalog.problem_cards.append(ProblemCard(id="chat", title="t", plain_words="w", capability="phone", trades=["hvac"], requires={"channel": "chat"}))
    for tool in catalog.tools:
        if tool.id in stated:
            tool.capability("phone").facets["channel"] = stated[tool.id]
    return recommend(catalog, BusinessProfile(trade="hvac"), catalog.problem("chat"))


def ids(options):
    return [o.tool_id for o in options]


def test_unstated_facet_goes_to_check_first_and_cannot_win(catalog):
    result = split(catalog)
    assert result.options == [] and result.winner_tool_id is None
    assert all("Not confirmed it handles website chat" in o.fit_note for o in result.check_first)


def test_confirmed_facet_is_ranked_and_others_are_held_back(catalog):
    result = split(catalog, solo=fact(["chat"]), voice=fact(["voice"]), suite=Fact(status="unknown"))
    assert ids(result.options) == ["solo"] and result.winner_tool_id == "solo"
    assert {"voice", "suite"} <= set(ids(result.check_first))


def test_a_facet_value_cannot_be_stated_without_a_source():
    with pytest.raises(ValidationError):
        Fact(status="present", value=["chat"])


def test_card_without_requires_ignores_facets(catalog):
    split(catalog, solo=fact(["voice"]))
    result = recommend(catalog, BusinessProfile(trade="hvac"), catalog.problem("calls"))
    assert "solo" in ids(result.options)


def raw(catalog, change):
    data = catalog.model_dump()
    data["facets"] = [CHANNEL.model_dump()]
    change(data)
    return data


def card_needs(value, facet="channel"):
    return lambda d: d["problem_cards"][0].update(requires={facet: value})


def tool_says(tool_index, cap_index, value, facet="channel"):
    return lambda d: d["tools"][tool_index]["capabilities"][cap_index].update(facets={facet: fact(value).model_dump()})


@pytest.mark.parametrize("change", [
    lambda d: d["facets"].append(CHANNEL.model_dump()),
    lambda d: d["facets"][0].update(values={}),
    lambda d: d["facets"][0].update(capabilities=["nowhere"]),
    card_needs("fax"),
    card_needs("chat", facet="colour"),
    lambda d: d["problem_cards"][1].update(requires={"channel": "chat"}),
    tool_says(0, 0, []),
    tool_says(0, 0, "chat"),
    tool_says(0, 0, ["fax"]),
    tool_says(0, 1, ["chat"]),
])
def test_bad_facet_data_is_rejected_at_load(catalog, change):
    with pytest.raises(ValidationError):
        Catalog.model_validate(raw(catalog, change))


def test_good_facet_data_loads(catalog):
    data = raw(catalog, lambda d: (card_needs("chat")(d), tool_says(0, 0, ["chat", "voice"])(d)))
    assert Catalog.model_validate(data).facet("channel").describe("chat") == "website chat"


def test_facets_survive_the_database_and_removed_rows_go(catalog, tmp_path):
    loaded = Catalog.model_validate(raw(catalog, lambda d: (card_needs("chat")(d), tool_says(0, 0, ["chat"])(d))))
    loaded.problem_cards[0].phrases = ["answer calls"]
    conn = db.connect(tmp_path / "f.db")
    db.seed(conn, loaded)
    stored = db.read_catalog(conn)
    assert stored.facets == loaded.facets
    assert {c.id: c for c in stored.problem_cards} == {c.id: c for c in loaded.problem_cards}
    loaded.tools = loaded.tools[1:]
    db.seed(conn, loaded)
    assert catalog.tools[0].id not in {t.id for t in db.read_catalog(conn).tools}
    conn.close()
