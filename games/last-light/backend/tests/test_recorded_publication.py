"""Replay real outputs after correcting a missing source authorization in the fixture."""
import json
from pathlib import Path

import pytest
from npc_director.contracts.content import ContentNeed, ContentPolicy, ContentFact, ContentCandidate, ContentReview
from npc_director.governance.content_review import ContentReviewError, validate_content_review
from npc_director.state.content_store import ContentStore


def fixture():
    raw=json.loads((Path(__file__).parent/'fixtures/recorded_briefing.json').read_text())
    need=ContentNeed(need_id='n',purpose='写简报',content_kind='background',reuse_checked=True,allowed_kinds=['background'])
    policy=ContentPolicy(session_id='s',npc_id='lin',allowed_kinds=['background'],
        canonical_facts=[ContentFact(fact_key='f',statement='列车停车，主照明断电。')],
        hard_constraints=['不增添事实。'],max_new_quests=0)
    return need,policy,ContentCandidate.model_validate(raw['candidate']),ContentReview.model_validate(raw['review'])


def test_model_approval_does_not_override_source_permissions():
    need,policy,candidate,review=fixture()
    assert review.action=='approve'
    with pytest.raises(ContentReviewError):validate_content_review(need,candidate,review,policy)


def test_authorized_source_replay_uses_real_staging_and_publication(tmp_path):
    need,policy,candidate,review=fixture()
    policy=policy.model_copy(update={'available_lore_refs':['f']})
    reviewed=validate_content_review(need,candidate,review,policy)
    store=ContentStore(tmp_path/'content.sqlite')
    staged=store.stage_reviewed('s','episode','turn','lin',reviewed)
    assert store.list_published('s')==[]
    store.freeze_turn_policy('s','turn',staged.policy_digest)
    with store.transaction() as connection:
        store.publish_turn_in_connection(connection,'s','turn',expected_policy_digest=staged.policy_digest)
    assert len(store.list_published('s','lin'))==1
    assert store.list_published('s','zhou')==[]  # Original candidate is private, not silently made public.
