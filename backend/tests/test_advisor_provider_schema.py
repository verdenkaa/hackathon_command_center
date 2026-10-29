"""Keep decoding grammar small, without relaxing server validation."""
import pytest
from pydantic import ValidationError

from app.advisor_schemas import AnalysisReply, QuestionReply


@pytest.mark.parametrize('model', [AnalysisReply, QuestionReply])
def test_provider_schema_omits_expensive_bounds_but_keeps_shape(model):
    from app.services.advisor import provider_schema
    original = model.model_json_schema()
    wire = provider_schema(model)
    def inspect(value):
        if isinstance(value, dict):
            assert not {'minItems', 'maxItems', 'minimum', 'maximum', 'minLength', 'maxLength'} & value.keys()
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
    inspect(wire)
    assert wire['required'] == original['required']
    assert wire['properties'].keys() == original['properties'].keys()
    assert model.model_json_schema() == original


def test_server_still_rejects_empty_evidence_and_too_many_recommendations():
    with pytest.raises(ValidationError):
        QuestionReply.model_validate({'answer': 'Answer', 'grounds': [], 'limitations': ['Unknown'], 'related': {}})
    with pytest.raises(ValidationError):
        AnalysisReply.model_validate({'captain_intervention': 'required', 'result': 'recommendations', 'recommendations': [{}] * 21})
